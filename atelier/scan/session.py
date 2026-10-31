#!/usr/bin/env python3
"""Scan intégré d'un étage : la commande g1-scan (section 9 du plan, agent Orchestrateur).

  g1-scan demarrer --lieu L --etage E --mode robot|simu [--repetition] [--explorer] [--nom N] [--json]
  g1-scan arreter  --lieu L [--session S] [--sans-traitement] [--attendre]
  g1-scan traiter  --lieu L --session S [--refaire]
  g1-scan etat     --lieu L [--session S] [--json]
  g1-scan adopter  --lieu L --session S
  g1-scan carte-unitree --lieu L [--etage E] [--delai 60]

Le déroulé, les fichiers d'une session (LIEU/scans/<session>/) et les états de session.json sont
ceux des sections 9 et 12.5 du plan. session.json n'est écrit que par atelier.lieu (maj_session).
Vague 5 : plus de reconnaissance des murs et des meubles ; le traitement fait la carte 3D, la carte 2D
et le nuage de la carte 3D, et l'adoption donne à l'étage sa carte, son nuage et un monde de
simulation tiré de la carte (la carte 2D extrudée en un seul maillage, atelier.monde).

demarrer crée la session, puis lance, détaché (dans son propre groupe de processus), le
processus de la session : « python -m atelier.scan.session session --lieu L --session S ».
Celui-ci :
  1. prépare. Mode simu : la simulation de l'étage (celle qui tourne déjà, sinon g1-monde
     simuler). Mode robot : 1801 par g1-slam scan-debut. Répétition : d'abord le faux service
     (g1-slam faux-service), la simulation et le relais /points → /unitree/slam_mapping/*
     (atelier.scan.repetition), puis 1801 au faux service, comme sur le robot ;
  2. enregistre (ros2 bag record dans enregistrement/), lance l'aperçu (atelier.scan.apercu) et,
     avec --explorer, le tour automatique des couloirs (atelier.scan.exploration) ;
  3. s'arrête sur SIGINT ou SIGTERM (g1-scan arreter), ou à la fin du tour : 1802 (mode robot),
     fermeture du bag, arrêt de tout ce qu'il a lancé. SIGUSR1 : pareil, sans le traitement ;
  4. traite : carte 3D, carte 2D, nuage d'affichage, rapport (comme g1-scan traiter).
Chaque programme lancé a son groupe de processus et son journal (journaux/scan_<lieu>_<session>.<nom>.log),
et reçoit SIGTERM si le processus de la session meurt. Leurs numéros sont notés dans
scans/<session>/.processus.json : g1-scan arreter s'en sert pour nettoyer une session interrompue.

Codes de sortie : 0 réussi, 1 échec (le message dit quoi faire), 2 commande mal tapée.
"""
import argparse
import ctypes
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from atelier import RACINE, dossier_journaux
from atelier.lieu import (FICHIERS_SESSION, ErreurLieu, charger_fiche, charger_itineraires, chemin_carte,
                          chemin_monde, chemin_pcd, chemin_sdf, creer_session, derniere_session, dossier_lieu,
                          dossier_session, ecrire_atomique, etat_scan, infos_processus, lire_session, maj_session,
                          processus_vivant, progression_etape, session_active, session_interrompue)
from atelier.lieu.scans import ETATS_ACTIFS, PERIODE_SESSION, _debut_processus, instant

DELAI_FERMETURE = 30.0          # s : arreter attend la fermeture de l'enregistrement au plus ce temps
DELAI_SIMU_EXISTANTE = 5.0      # s : une simulation qui tourne déjà publie /odom et /points
DELAI_SIMU = 90.0               # s : lancement de la simulation, jusqu'à /odom et /points
DELAI_FAUX_SERVICE = 20.0       # s : le faux service slam_operate affiche « prêt »
DELAI_RELAIS = 40.0             # s : le relais de la répétition affiche « Relais prêt »
DELAI_SLAM = 30.0               # s : g1-slam scan-debut et scan-fin (10 s d'attente du robot, plus le démarrage)
ALERTE_SANS_NUAGE = 20.0        # s d'enregistrement sans aucun nuage : le message prévient l'utilisateur
INTERFACE_ROBOT = "eno2"
RESEAU_ROBOT = "192.168.123."
# Sujets enregistrés en plus sur le vrai robot (et en répétition, où ils peuvent manquer) :
# odométrie du bassin et informations du service de cartographie, pour l'analyse après coup
SUJETS_ROBOT_EN_PLUS = ("/state_estimator/odom_pelvis", "/slam_info")
FICHIER_PROCESSUS = ".processus.json"
# Durée estimée de la carte 3D (barre de progression) : par nuage enregistré
SECONDES_PAR_NUAGE = 0.004

ETATS_LISIBLES = {"en_cours": "scan en cours", "arret_en_cours": "arrêt en cours", "traitement": "traitement",
                  "termine": "terminé", "echec": "échec"}


class ErreurScan(Exception):
    """Erreur du scan ; le message, en français, dit quoi faire."""


class ScanAnnule(Exception):
    """Arrêt demandé avant le début de l'enregistrement."""


def dire(texte):
    """Une ligne de journal, avec l'heure."""
    print(f"{time.strftime('%H:%M:%S')} {texte}", flush=True)


# ================================================================ petits outils

def _commande(nom):
    """Chemin d'une commande g1-* : $G1_SCAN_BIN/nom s'il existe (essais), sinon celle de ce dépôt."""
    autre = os.environ.get("G1_SCAN_BIN")
    if autre and (Path(autre) / nom).is_file():
        return str(Path(autre) / nom)
    return str(RACINE / "bin" / nom)


def _env(robot_reel=False):
    """Environnement des programmes lancés : ce dépôt en tête du PYTHONPATH ; pour le vrai robot,
    le réseau du robot (domaine 0, CycloneDDS sur eno2, comme setup/robot.sh)."""
    env = dict(os.environ)
    # Un seul fil de calcul pour numpy (OpenBLAS) : sinon chaque petit calcul de l'aperçu ou de
    # l'exploration occupe tous les cœurs en attente active, au détriment de Gazebo
    for variable in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        env.setdefault(variable, "1")
    chemins = [p for p in env.get("PYTHONPATH", "").split(":") if p and p != str(RACINE)]
    env["PYTHONPATH"] = ":".join([str(RACINE)] + chemins)
    if robot_reel:
        interface = os.environ.get("G1_INTERFACE") or INTERFACE_ROBOT
        env["ROS_DOMAIN_ID"] = "0"
        env["ROS_LOCALHOST_ONLY"] = "0"
        env["CYCLONEDDS_URI"] = (f'<CycloneDDS><Domain><General><Interfaces><NetworkInterface name="{interface}" '
                                 'priority="default" multicast="default"/></Interfaces></General></Domain>'
                                 '</CycloneDDS>')
    return env


def _mort_du_parent():
    """Dans l'enfant, avant exec : recevoir SIGTERM si le processus de la session meurt."""
    try:
        ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGTERM)    # PR_SET_PDEATHSIG
    except OSError:
        pass


def _groupe_vivant(pgid):
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def arreter_groupe(pgid, etapes=((signal.SIGINT, 10.0), (signal.SIGTERM, 5.0), (signal.SIGKILL, 3.0)),
                   popen=None):
    """Arrête un groupe de processus : chaque signal, puis attente de sa fin. Vrai s'il est fini."""
    for sig, attente in etapes:
        if popen is not None:
            popen.poll()
        if not _groupe_vivant(pgid):
            return True
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            return True
        fin = time.monotonic() + attente
        while time.monotonic() < fin:
            if popen is not None:
                popen.poll()
            if not _groupe_vivant(pgid):
                return True
            time.sleep(0.1)
    if popen is not None:
        popen.poll()
    return not _groupe_vivant(pgid)


def _fin_journal(chemin, lignes=6):
    try:
        texte = Path(chemin).read_text(encoding="utf-8", errors="replace").strip().splitlines()
    except OSError:
        return ""
    return " | ".join(ligne.strip() for ligne in texte[-lignes:] if ligne.strip())


def _journal(lieu, session, nom=None):
    return dossier_journaux() / (f"scan_{lieu}_{session}" + (f".{nom}" if nom else "") + ".log")


def enregistrement_complet(dossier):
    """Vrai si le ros2 bag de la session est fermé proprement (metadata.yaml présent)."""
    return (Path(dossier) / FICHIERS_SESSION["enregistrement"] / "metadata.yaml").is_file()


def reparer_enregistrement(dossier):
    """Bag interrompu (sans metadata.yaml) : essaie « ros2 bag reindex ». Vrai si c'est réparé."""
    enr = Path(dossier) / FICHIERS_SESSION["enregistrement"]
    if enregistrement_complet(dossier) or not any(enr.glob("*.db3")):
        return enregistrement_complet(dossier)
    try:
        subprocess.run(["ros2", "bag", "reindex", str(enr)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=120, env=_env())
    except (OSError, subprocess.TimeoutExpired):
        return False
    return enregistrement_complet(dossier)


def _lire_processus(dossier):
    try:
        return json.loads((Path(dossier) / FICHIER_PROCESSUS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"programmes": [], "avertissements": []}


def nettoyer_restes(dossier):
    """Arrête les programmes d'une session interrompue qui tourneraient encore. Renvoie leurs noms."""
    arretes = []
    for p in _lire_processus(dossier).get("programmes", []):
        if p.get("arrete") or p.get("hote") != socket.gethostname():
            continue
        if _debut_processus(p["pid"]) == p.get("debut") and _groupe_vivant(p["pid"]):
            arreter_groupe(p["pid"])
            arretes.append(p["nom"])
    return arretes


def _graphe_explorable(lieu, etage):
    from atelier.scan.exploration import graphe_etage
    noeuds, aretes = graphe_etage(charger_itineraires(lieu), etage)
    return len(noeuds) >= 2 and len(aretes) >= 1


def verifier_reseau_robot():
    """Le câble du robot est branché et le port a une adresse du réseau du robot (lecture locale,
    rien n'est envoyé). ErreurScan sinon."""
    interface = os.environ.get("G1_INTERFACE") or INTERFACE_ROBOT
    try:
        porteuse = Path(f"/sys/class/net/{interface}/carrier").read_text().strip()
    except OSError:
        porteuse = ""
    if porteuse != "1":
        raise ErreurScan(f"Robot non détecté : câble non détecté sur {interface}. Branchez le câble Ethernet entre "
                         "le PC et le robot (le PC suit le robot pendant le scan), puis recommencez. Pour essayer "
                         "sans robot : --repetition")
    try:
        adresses = subprocess.run(["ip", "-4", "-o", "addr", "show", "dev", interface], capture_output=True,
                                  text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        adresses = ""
    if RESEAU_ROBOT not in adresses:
        raise ErreurScan(f"Robot non détecté : le port {interface} n'a pas d'adresse sur le réseau du robot "
                         f"({RESEAU_ROBOT}x). Faites une fois « source ~/robot-g1/setup/robot.sh », puis recommencez")


def _session_visee(dossier, session=None):
    """La session demandée, sinon la session active du lieu, sinon la plus récente (ou None)."""
    if session:
        return lire_session(dossier, session)
    return session_active(dossier) or derniere_session(dossier)


def _autre_processus_vivant(s):
    """Le processus noté dans la session tourne encore, et ce n'est pas celui-ci."""
    p = s.get("processus")
    return bool(processus_vivant(s)) and p["pid"] != os.getpid()


# ================================================================ programmes lancés par la session

class Programme:
    """Un programme lancé par la session : son propre groupe de processus, son journal."""

    ARRET = ((signal.SIGINT, 10.0), (signal.SIGTERM, 5.0), (signal.SIGKILL, 3.0))

    def __init__(self, nom, commande, journal, env, arret=ARRET):
        self.nom, self.commande, self.journal, self.etapes_arret = nom, [str(c) for c in commande], journal, arret
        with open(journal, "ab") as sortie:
            sortie.write(f"\n===== {instant()} : {' '.join(self.commande)}\n".encode())
            sortie.flush()
            self.popen = subprocess.Popen(self.commande, stdout=sortie, stderr=subprocess.STDOUT,
                                          stdin=subprocess.DEVNULL, env=env, cwd=str(RACINE),
                                          start_new_session=True, preexec_fn=_mort_du_parent)
        self.pid = self.popen.pid
        self.debut = _debut_processus(self.pid)
        self.arrete = False

    def vivant(self):
        return self.popen.poll() is None

    @property
    def code(self):
        return self.popen.poll()

    def arreter(self):
        fini = arreter_groupe(self.pid, self.etapes_arret, self.popen)
        self.arrete = True
        return fini

    def infos(self):
        return {"nom": self.nom, "pid": self.pid, "debut": self.debut, "hote": socket.gethostname(),
                "journal": str(self.journal), "arrete": self.arrete}


class ProcessusSession:
    """Le processus d'une session de scan : préparation, enregistrement, arrêt, puis traitement."""

    def __init__(self, lieu, session):
        self.lieu = dossier_lieu(lieu)
        self.id = session
        self.dossier = dossier_session(self.lieu, session)
        self.s = lire_session(self.lieu, session)
        self.mode, self.repetition, self.explorer = self.s["mode"], self.s["repetition"], self.s["explorer"]
        self.robot_reel = self.mode == "robot" and not self.repetition
        self.simule = not self.robot_reel
        self.env = _env(self.robot_reel)
        self.programmes = {}
        self.avertissements = []
        self.arret_demande = False
        self.sans_traitement = False
        self.scan_slam_commence = False
        self.pilote = os.environ.get("G1_SCAN_PILOTE", "direct")
        self.py = sys.executable

    # ------------------------------------------------ outils
    def maj(self, **champs):
        try:
            self.s = maj_session(self.lieu, self.id, **champs)
        except ErreurLieu as e:
            dire(f"session.json non mis à jour : {'; '.join(e.erreurs) if hasattr(e, 'erreurs') else e}")

    def avertir(self, texte):
        dire(f"Attention : {texte}")
        self.avertissements.append(texte)
        self._noter_processus()

    def _noter_processus(self):
        donnees = {"session": self.id, "pid": os.getpid(), "programmes": [p.infos() for p in self.programmes.values()],
                   "avertissements": self.avertissements}
        try:
            ecrire_atomique(self.dossier / FICHIER_PROCESSUS, json.dumps(donnees, ensure_ascii=False, indent=2) + "\n")
        except OSError as e:
            dire(f"{FICHIER_PROCESSUS} non écrit : {e}")

    def lancer(self, nom, commande, **options):
        journal = _journal(self.lieu.name, self.id, nom)
        programme = Programme(nom, commande, journal, self.env, **options)
        self.programmes[nom] = programme
        self._noter_processus()
        dire(f"Lancé : {nom} (groupe {programme.pid}, journal {journal})")
        return programme

    def arreter_programme(self, nom):
        p = self.programmes.get(nom)
        if p is None or p.arrete:
            return
        fini = p.arreter()
        self._noter_processus()
        dire(f"Arrêté : {nom} (code {p.code})" + ("" if fini else " ; il résiste, tué de force"))

    def executer_bref(self, nom, commande, delai):
        """Lance une commande courte, au premier plan, et renvoie (code, fin de sa sortie)."""
        journal = _journal(self.lieu.name, self.id, nom)
        p = Programme(nom, commande, journal, self.env)
        try:
            code = p.popen.wait(delai)
        except subprocess.TimeoutExpired:
            p.arreter()
            code = None
        return code, _fin_journal(journal)

    def _attendre_texte(self, nom, texte, delai):
        """Attend que le journal d'un programme contienne texte. Faux s'il s'arrête ou si c'est trop long."""
        p = self.programmes[nom]
        fin = time.monotonic() + delai
        while time.monotonic() < fin:
            if self.arret_demande:
                raise ScanAnnule()
            try:
                if texte in Path(p.journal).read_text(encoding="utf-8", errors="replace"):
                    return True
            except OSError:
                pass
            if not p.vivant():
                return False
            time.sleep(0.2)
        return False

    def _sujets_publies(self, sujets, delai):
        code, _ = self.executer_bref("attente", [self.py, "-m", "atelier.scan.repetition", "attendre", *sujets,
                                                 "--delai", f"{delai:g}"], delai + 15)
        return code == 0

    def _signal(self, signum, _cadre):
        self.arret_demande = True
        if signum == signal.SIGUSR1:
            self.sans_traitement = True

    # ------------------------------------------------ les étapes
    def executer(self):
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGUSR1):
            signal.signal(sig, self._signal)
        self.maj(processus=infos_processus(), journal=str(_journal(self.lieu.name, self.id)))
        texte_mode = ("vrai robot" if self.robot_reel else "répétition du mode robot, sans robot" if self.repetition
                      else "robot simulé") + (", exploration automatique" if self.explorer else "")
        dire(f"Session {self.id} du lieu {self.lieu.name}, étage {self.s['etage']} : {texte_mode}")
        enregistrement_lance = False
        try:
            self.preparer()
            if self.arret_demande:
                raise ScanAnnule()
            self.enregistrer()
            enregistrement_lance = True
            self.attendre_fin()
        except ScanAnnule:
            self.terminer_sans_enregistrement("le scan a été arrêté avant le début de l'enregistrement : rien n'a "
                                              "été enregistré. Relancez « Scan » quand vous êtes prêt.")
            return 1
        except ErreurScan as e:
            if not enregistrement_lance:
                self.terminer_sans_enregistrement(str(e))
                return 1
            self.avertir(str(e))
        except Exception as e:                   # erreur inattendue : on garde ce qui a été enregistré
            dire(f"Erreur inattendue : {type(e).__name__} : {e}")
            if not enregistrement_lance:
                self.terminer_sans_enregistrement(f"erreur inattendue pendant la préparation ({type(e).__name__} : "
                                                  f"{e}) ; voir le journal {_journal(self.lieu.name, self.id)}")
                return 1
            self.avertir(f"erreur inattendue pendant l'enregistrement ({type(e).__name__} : {e})")
        try:
            complet = self.arreter_scan()
        finally:
            self.arreter_tout()
        if not complet:
            self.maj(etat="echec", etape="arret", message="Le scan s'est arrêté sans enregistrement complet : "
                     f"recommencez le scan. Détails : journal {_journal(self.lieu.name, self.id)}")
            return 1
        if self.sans_traitement:
            self.maj(message=f"Enregistrement fermé, sans traitement. Pour fabriquer les cartes : g1-scan traiter "
                             f"--lieu {self.lieu.name} --session {self.id}")
            dire("Fin, sans traitement (demandé).")
            return 0
        return traiter(self.lieu, self.id, avertissements=self.avertissements, dans_la_session=True)

    def preparer(self):
        etage = self.s["etage"]
        if self.repetition:
            self.maj(message="Répétition : démarrage du faux service slam_operate…")
            self.lancer("faux_slam", [_commande("g1-slam"), "faux-service", "--lieu", self.lieu, "--etage", etage])
            if not self._attendre_texte("faux_slam", "prêt", DELAI_FAUX_SERVICE):
                raise ErreurScan("le faux service slam_operate ne démarre pas : voir le journal "
                                 f"{self.programmes['faux_slam'].journal}")
        if self.simule:
            self.assurer_simulation()
        if self.repetition:
            self.lancer("relais", [self.py, "-m", "atelier.scan.repetition", "relais"])
            if not self._attendre_texte("relais", "Relais prêt", DELAI_RELAIS):
                raise ErreurScan("le relais /points → /unitree/slam_mapping/points ne démarre pas : voir le journal "
                                 f"{self.programmes['relais'].journal}")
        if self.mode == "robot":
            self.maj(message="Démarrage de la cartographie du robot (1801)…")
            commande = [_commande("g1-slam"), "scan-debut"] + (["--faux"] if self.repetition else [])
            code, sortie = self.executer_bref("slam", commande, DELAI_SLAM)
            if code != 0:
                quoi = "le faux service" if self.repetition else "le robot"
                raise ErreurScan(f"{quoi} n'a pas accepté le début du scan (1801) : {sortie or 'pas de réponse'}. "
                                 + ("" if self.repetition else "Robot allumé, câble branché, services unitree_slam et "
                                    "lidar_driver activés dans l'appli ? Puis recommencez."))
            self.scan_slam_commence = True
            dire("1801 accepté : la cartographie du robot a commencé.")

    def assurer_simulation(self):
        etage = self.s["etage"]
        self.maj(message="Recherche de la simulation de l'étage…")
        if self._sujets_publies(["/odom", "/points"], DELAI_SIMU_EXISTANTE):
            dire("Simulation déjà lancée (/odom et /points publiés) : utilisée telle quelle, elle ne sera pas arrêtée.")
            return
        if self.arret_demande:
            raise ScanAnnule()
        self.maj(message="Démarrage de la simulation de l'étage (Gazebo, sans fenêtre)…")
        self.lancer("simulation", [_commande("g1-monde"), "simuler", "--lieu", self.lieu, "--etage", etage,
                                   "--sans-fenetre"], arret=((signal.SIGINT, 20.0), (signal.SIGTERM, 8.0),
                                                             (signal.SIGKILL, 3.0)))
        fin = time.monotonic() + DELAI_SIMU
        while time.monotonic() < fin:
            if self.arret_demande:
                raise ScanAnnule()
            if not self.programmes["simulation"].vivant():
                raise ErreurScan("la simulation s'est arrêtée au démarrage : "
                                 f"{_fin_journal(self.programmes['simulation'].journal, 4)}")
            if self._sujets_publies(["/odom", "/points"], 10.0):
                dire("Simulation prête : /odom et /points sont publiés.")
                return
        raise ErreurScan(f"la simulation ne publie pas /odom et /points après {DELAI_SIMU:g} s : voir le journal "
                         f"{self.programmes['simulation'].journal}")

    def sujets_enregistres(self):
        sujets = self.s["sujets"]
        liste = [sujets["nuage"], sujets["odom"]] + list(sujets.get("autres") or [])
        if self.mode == "robot":
            liste += [s for s in SUJETS_ROBOT_EN_PLUS if s not in liste]
        return liste

    def enregistrer(self):
        sujets = self.s["sujets"]
        liste = self.sujets_enregistres()
        if set(liste) != set([sujets["nuage"], sujets["odom"]] + list(sujets.get("autres") or [])):
            self.maj(sujets={**sujets, "autres": [s for s in liste if s not in (sujets["nuage"], sujets["odom"])]})
        self.lancer("enregistrement", ["ros2", "bag", "record", "-o", self.dossier / FICHIERS_SESSION["enregistrement"],
                                       *liste], arret=((signal.SIGINT, 25.0), (signal.SIGTERM, 5.0),
                                                       (signal.SIGKILL, 3.0)))
        commande = [self.py, "-m", "atelier.scan.apercu", "--lieu", self.lieu, "--session", self.id,
                    "--nuage", sujets["nuage"], "--odom", sujets["odom"]]
        if self.simule:
            commande.append("--arret-cmd-vel")
        self.lancer("apercu", commande)
        time.sleep(1.0)
        if not self.programmes["enregistrement"].vivant():
            raise ErreurScan("ros2 bag record s'est arrêté tout de suite : "
                             f"{_fin_journal(self.programmes['enregistrement'].journal, 4)}")
        if self.explorer:
            self.lancer("exploration", [self.py, "-m", "atelier.scan.exploration", "--lieu", self.lieu,
                                        "--etage", self.s["etage"], "--session", self.id, "--pilote", self.pilote,
                                        "--journal-guide", _journal(self.lieu.name, self.id, "guide")])
            message = ("Scan en cours : le robot simulé fait seul le tour des couloirs ; le scan s'arrêtera à la fin "
                       "du tour (ou avec « Fin »).")
        elif self.robot_reel:
            message = ("Scan en cours : promenez le robot lentement dans tout l'étage (le PC suit le robot au câble), "
                       "puis « Fin ».")
        else:
            message = "Scan en cours : pilotez le robot simulé dans tout l'étage (flèches), puis « Fin »."
        if self.repetition:
            message = "Répétition, sans robot. " + message
        self.maj(etape="enregistrement", message=message)
        dire(f"Enregistrement de {', '.join(liste)} dans {self.dossier / FICHIERS_SESSION['enregistrement']}")

    def attendre_fin(self):
        debut, dernier, alerte = time.monotonic(), time.monotonic(), False
        surveilles = ["enregistrement", "simulation", "relais", "faux_slam"]
        signale_apercu = False
        while not self.arret_demande:
            exploration = self.programmes.get("exploration")
            if exploration is not None and not exploration.vivant():
                if exploration.code == 0:
                    dire("Exploration finie : le scan s'arrête de lui-même.")
                else:
                    self.avertir(f"l'exploration s'est arrêtée avant la fin du tour (code {exploration.code}) : "
                                 f"{_fin_journal(exploration.journal, 2)}")
                self.maj(message="Tour des couloirs fini : fin du scan…")
                return
            for nom in surveilles:
                p = self.programmes.get(nom)
                if p is not None and not p.vivant():
                    raise ErreurScan(f"{nom} s'est arrêté pendant le scan (code {p.code}) : "
                                     f"{_fin_journal(p.journal, 3)}")
            apercu = self.programmes.get("apercu")
            if apercu is not None and not apercu.vivant() and not signale_apercu:
                signale_apercu = True
                self.avertir(f"l'aperçu en direct s'est arrêté (code {apercu.code}) ; l'enregistrement continue")
            maintenant = time.monotonic()
            if maintenant - dernier >= PERIODE_SESSION - 1.0:
                dernier = maintenant
                self.maj()                           # au moins toutes les 5 s pendant l'enregistrement
                if not alerte and maintenant - debut > ALERTE_SANS_NUAGE and not self.s["statistiques"].get("nuages"):
                    alerte = True
                    question = ("le robot publie-t-il sa cartographie (câble, service unitree_slam) ?"
                                if self.robot_reel else "la simulation tourne-t-elle ?")
                    self.maj(message=f"Aucun nuage reçu sur {self.s['sujets']['nuage']} depuis "
                                     f"{ALERTE_SANS_NUAGE:g} s : {question}")
            time.sleep(0.2)

    def arreter_scan(self):
        """1802, fermeture du bag, aperçu ; renvoie vrai si l'enregistrement est complet."""
        dire("Fin du scan demandée.")
        self.maj(etat="arret_en_cours", etape="arret", progression=5,
                 message="Fin du scan : arrêt du robot et fermeture de l'enregistrement…")
        self.arreter_programme("exploration")
        if self.scan_slam_commence:
            commande = [_commande("g1-slam"), "scan-fin", "--nom", self.s["carte_unitree"]]
            commande += ["--faux"] if self.repetition else []
            code, sortie = self.executer_bref("slam", commande, DELAI_SLAM)
            if code == 0:
                dire(f"1802 accepté : carte {self.s['carte_unitree']} enregistrée sur le robot.")
            else:
                self.avertir(f"le robot n'a pas accepté la fin du scan (1802) : {sortie or 'pas de réponse'} ; "
                             f"la carte Unitree {self.s['carte_unitree']} n'est peut-être pas enregistrée sur le "
                             "robot (la carte 2D est fabriquée quand même)")
            self.scan_slam_commence = False
        self.arreter_programme("enregistrement")
        self.arreter_programme("apercu")
        complet = enregistrement_complet(self.dossier)
        if not complet and (self.dossier / FICHIERS_SESSION["enregistrement"]).is_dir():
            dire("Enregistrement sans metadata.yaml : tentative de réparation (ros2 bag reindex)…")
            complet = reparer_enregistrement(self.dossier)
            if complet:
                self.avertir("l'enregistrement n'avait pas été fermé proprement ; il a été réparé (ros2 bag reindex)")
        taille = sum(f.stat().st_size for f in (self.dossier / FICHIERS_SESSION["enregistrement"]).glob("*")
                     if f.is_file()) if complet else 0
        self.maj(fin=instant(), message=f"Enregistrement fermé ({taille / 1e6:.0f} Mo) ; arrêt de la simulation…"
                 if complet else "Enregistrement incomplet.")
        return complet

    def arreter_tout(self):
        """Arrête, dans l'ordre inverse du lancement, tout ce que la session a lancé."""
        if self.scan_slam_commence:                      # échec après 1801 : on termine quand même la cartographie
            commande = [_commande("g1-slam"), "scan-fin", "--nom", self.s["carte_unitree"]]
            commande += ["--faux"] if self.repetition else []
            self.executer_bref("slam", commande, DELAI_SLAM)
            self.scan_slam_commence = False
        for nom in reversed(list(self.programmes)):
            self.arreter_programme(nom)

    def terminer_sans_enregistrement(self, message):
        dire(f"Échec : {message}")
        try:
            self.arreter_tout()
        finally:
            etape = self.s["etape"] if self.s["etape"] in ("preparation", "enregistrement") else "preparation"
            self.maj(etat="echec", etape=etape, message=message[0].upper() + message[1:])


# ================================================================ traitement

class Avancement:
    """Fait avancer la barre de progression pendant une étape longue, d'après sa durée estimée."""

    def __init__(self, lieu, session, etape, duree):
        self.lieu, self.session, self.etape, self.duree = lieu, session, etape, max(duree, 1.0)
        self._fin = threading.Event()
        self._fil = threading.Thread(target=self._tourner, daemon=True)

    def _tourner(self):
        debut = time.monotonic()
        while not self._fin.wait(2.0):
            fraction = min(0.95, (time.monotonic() - debut) / self.duree)
            try:
                maj_session(self.lieu, self.session, progression=progression_etape(self.etape, fraction))
            except ErreurLieu:
                pass

    def __enter__(self):
        self._fil.start()
        return self

    def __exit__(self, *_):
        self._fin.set()
        self._fil.join(timeout=5)


def _nombre_de_messages(enregistrement, sujet):
    import yaml
    try:
        infos = yaml.safe_load((Path(enregistrement) / "metadata.yaml").read_text())["rosbag2_bagfile_information"]
        for t in infos.get("topics_with_message_count", []):
            if t["topic_metadata"]["name"] == sujet:
                return int(t["message_count"])
    except (OSError, KeyError, TypeError, ValueError, yaml.YAMLError):
        pass
    return 0


def analyser_repere(enregistrement, sujet_nuage, sujet_odom):
    """Repères du nuage et de l'odométrie (premier message de chacun) : les points sont-ils déjà dans
    le repère du monde ? Renvoie {nuage, odom, robot, deja_dans_le_monde, premiere_pose}."""
    from atelier.lieu import quaternion_vers_cap
    from atelier.scan.carte3d import REPERES_MONDE, _messages
    resultat = {"nuage": None, "odom": None, "robot": None, "deja_dans_le_monde": None, "premiere_pose": None}
    for _, msg, _ in _messages(enregistrement, [sujet_odom]):
        p = msg.pose.pose
        resultat.update(odom=msg.header.frame_id, robot=msg.child_frame_id,
                        premiere_pose=[round(p.position.x, 3), round(p.position.y, 3),
                                       round(quaternion_vers_cap(p.orientation), 4)])
        break
    for _, msg, _ in _messages(enregistrement, [sujet_nuage]):
        resultat["nuage"] = msg.header.frame_id
        break
    if resultat["nuage"] is not None:
        repere = resultat["nuage"].lstrip("/")
        resultat["deja_dans_le_monde"] = repere in REPERES_MONDE or repere == (resultat["odom"] or "").lstrip("/")
    return resultat


def _supprimer(*chemins):
    for chemin in chemins:
        try:
            Path(chemin).unlink()
        except FileNotFoundError:
            pass


def _verifier_avant_traitement(s, dossier, refaire=False):
    if s.get("adoption") and not refaire:
        raise ErreurScan(f"la session {s['id']} a déjà été adoptée : refaire son traitement changerait la carte de "
                         f"l'étage. Pour la refaire quand même (les résultats d'avant sont gardés) : g1-scan traiter "
                         f"--lieu {s['lieu']} --session {s['id']} --refaire, puis g1-scan adopter")
    interrompue = session_interrompue(s) or not _autre_processus_vivant(s)
    if s["etat"] == "en_cours":
        if not session_interrompue(s):
            raise ErreurScan(f"le scan {s['id']} est en cours : arrêtez-le d'abord "
                             f"(g1-scan arreter --lieu {s['lieu']})")
        raise ErreurScan(f"le scan {s['id']} s'est interrompu sans être arrêté : g1-scan arreter --lieu {s['lieu']} "
                         f"--session {s['id']} le termine (et lance le traitement)")
    if s["etat"] in ETATS_ACTIFS and not interrompue:
        raise ErreurScan(f"la session {s['id']} est encore en {ETATS_LISIBLES[s['etat']]} (processus "
                         f"{s['processus']['pid']}) : attendez la fin (g1-scan etat --lieu {s['lieu']})")
    if refaire and s["etat"] not in ("termine", "echec"):
        raise ErreurScan(f"--refaire ne s'emploie que sur une session finie (terminée ou en échec), pas en "
                         f"{ETATS_LISIBLES[s['etat']]}")
    if not enregistrement_complet(dossier) and not reparer_enregistrement(dossier):
        raise ErreurScan(f"la session {s['id']} n'a pas d'enregistrement complet (enregistrement/metadata.yaml) : "
                         "impossible de fabriquer ses cartes. Refaites le scan")


def traiter(lieu, session, avertissements=(), dans_la_session=False, refaire=False):
    """Carte 3D, carte 2D, nuage d'affichage et rapport d'une session (9.5, 12.5). Renvoie 0 ou 1.
    refaire : une session finie, même adoptée ; ses résultats d'avant vont dans ancien_<horodatage>/ et
    elle perd son adoption. ErreurScan si la session ne peut pas être traitée (en cours, adoptée sans
    refaire, sans enregistrement)."""
    try:
        return _traiter(lieu, session, avertissements, dans_la_session, refaire)
    except (ErreurScan, ErreurLieu):
        raise
    except Exception as e:                       # erreur inattendue : la session ne reste pas « traitement »
        dire(f"Erreur inattendue pendant le traitement : {type(e).__name__} : {e}")
        s = lire_session(lieu, session)
        if s["etat"] == "traitement":
            maj_session(lieu, session, etat="echec", etape=s["etape"],
                        message=f"Le traitement a échoué à l'étape {s['etape']} (erreur inattendue "
                                f"{type(e).__name__} : {e}). Refaites-le : g1-scan traiter --lieu "
                                f"{dossier_lieu(lieu).name} --session {session} --refaire")
        return 1


def _traiter(lieu, session, avertissements, dans_la_session, refaire=False):
    from atelier.lieu import chemin_nuage_session, enregistrer_carte, ranger_resultats
    from atelier.lieu import NUAGE_AFFICHAGE
    from atelier.scan import affichage, carte2d, carte3d
    lieu = dossier_lieu(lieu)
    dossier = dossier_session(lieu, session)
    s = lire_session(lieu, session)
    if not dans_la_session:
        _verifier_avant_traitement(s, dossier, refaire)
    avertissements = list(avertissements) or list(_lire_processus(dossier).get("avertissements", []))
    etage, mode, sujets = s["etage"], s["mode"], s["sujets"]
    enregistrement = dossier / FICHIERS_SESSION["enregistrement"]
    nuage, carte = dossier / FICHIERS_SESSION["nuage"], dossier / FICHIERS_SESSION["carte"]
    rapport_fichier = dossier / FICHIERS_SESSION["rapport"]
    base_affichage = chemin_nuage_session(dossier)
    if refaire:
        # non destructif : les résultats d'avant sont gardés ; la session devra être réadoptée
        ancien = ranger_resultats(lieu, session)
        if ancien is not None:
            dire(f"Résultats d'avant rangés dans {ancien.name}/")
        if s.get("adoption"):
            s = maj_session(lieu, session, adoption=None)
            dire("La session n'est plus adoptée : adoptez-la de nouveau (g1-scan adopter) quand elle sera prête.")
    else:
        # Un nouveau traitement remplace tout ce qu'avait fait le précédent
        _supprimer(nuage, carte, dossier / FICHIERS_SESSION["carte_image"], rapport_fichier,
                   *[base_affichage.with_name(base_affichage.name + ext) for ext in (".bin", ".json")])
    debut, etapes = time.monotonic(), []

    def maj(**champs):
        return maj_session(lieu, session, **champs)

    def echec(etape, message):
        dire(f"Échec ({etape}) : {message}")
        maj(etat="echec", etape=etape, message=message)
        return 1

    maj(processus=infos_processus(), etat="traitement", etape="carte_3d", progression=progression_etape("carte_3d"),
        fin=s["fin"] or instant(), message="Carte 3D : assemblage des nuages de l'enregistrement…")
    dire(f"Traitement de la session {session} ({mode}{', répétition' if s['repetition'] else ''})")

    # 1. carte 3D
    t0 = time.monotonic()
    capteur = None                                # vrai robot : défaut de carte3d, si /tf_static manque
    if mode == "simu" or s["repetition"]:
        from atelier.scan.apercu import position_lidar_proxy
        capteur = position_lidar_proxy()          # si /tf_static manque à l'enregistrement
    n_nuages = _nombre_de_messages(enregistrement, sujets["nuage"])
    try:
        with Avancement(lieu, session, "carte_3d", 5.0 + SECONDES_PAR_NUAGE * n_nuages):
            infos = carte3d.fabriquer_pcd(enregistrement, nuage, sujet_nuage=sujets["nuage"], sujet_odom=sujets["odom"],
                                          capteur=capteur, afficher=dire, avec_points=True)
        repere = analyser_repere(enregistrement, infos["sujet_nuage"], infos["sujet_odom"])
    except carte3d.ErreurCarte3d as e:
        return echec("carte_3d", f"La carte 3D n'a pas pu être fabriquée : {e}. Vérifiez que {sujets['nuage']} et "
                                 f"{sujets['odom']} ont bien été publiés pendant le scan, puis refaites le scan.")
    except Exception as e:
        return echec("carte_3d", f"La carte 3D n'a pas pu être fabriquée (erreur inattendue {type(e).__name__} : {e}). "
                                 f"Voir le journal {s.get('journal') or ''}, puis refaites le traitement : g1-scan "
                                 f"traiter --lieu {lieu.name} --session {session} --refaire")
    points = infos.pop("tableau")
    avertissements += list(infos.get("avertissements") or [])
    repere["capteur"] = infos.get("capteur")
    message_repere = (f"Repère des points : « {repere['nuage']} »"
                      + (", déjà celui de l'odométrie : points pris tels quels, sans transformation"
                         if repere["deja_dans_le_monde"] else
                         f", celui du capteur : points placés par l'odométrie (« {repere['odom']} ») et la position "
                         f"du LiDAR ({repere['capteur']})"))
    dire(message_repere)
    if mode == "robot" and not s["repetition"]:
        # à l'écran, une phrase simple ; le repère exact est dans le journal du scan (message_repere)
        avertissements.append("Scan du vrai robot : regardez la carte avant de l'utiliser, elle ne doit être ni "
                              "dédoublée ni tournée (sinon, refaites le scan plus lentement).")
    sol = infos["sol"]
    if sol.get("raison"):
        # revue de la vague 5 : un sol mal vu (scan court) donnait des hauteurs fausses sans rien dire
        avertissements.append(f"Sol {sol['raison']} : refaites un scan plus long si la carte 3D paraît fausse.")
    etapes.append({"etape": "carte_3d", "ok": True, "duree_s": round(time.monotonic() - t0, 1),
                   "message": f"{infos['points']} points, {infos['nuages']} nuages sur {infos['recus']} "
                              f"({infos['ignores']} ignorés), {infos['retires_mobiles']} points de passants retirés, "
                              f"sol {carte2d.texte_sol(sol)}"})

    # 2. carte 2D, en hauteur au-dessus du plan du sol
    t0 = time.monotonic()
    maj(etape="carte_2d", progression=progression_etape("carte_2d"),
        message="Carte 2D : tranche de 0,1 à 1,5 m au-dessus du sol, projetée et nettoyée…")
    try:
        if mode == "simu":                       # emprise du monde : comparable pixel à pixel au monde dessiné
            r = carte2d.fabriquer_carte_lieu(lieu, etage, pcd=nuage, sortie=carte, afficher=dire, plan=sol)
        else:                                    # emprise du nuage (repère de la carte Unitree)
            info, image, sol_carte = carte2d.fabriquer_carte(points, None, image=FICHIERS_SESSION["carte_image"],
                                                             plan=sol)
            occupes = int((image == carte2d.OCCUPE).sum())
            if occupes == 0:
                raise carte2d.ErreurCarte2d("aucun obstacle entre 0,1 et 1,5 m au-dessus du sol "
                                            f"({carte2d.texte_sol(sol_carte)})")
            enregistrer_carte(carte, info, image)
            r = {"fichier": str(carte), "sol": sol_carte, "occupes": occupes, "largeur": info.largeur,
                 "hauteur": info.hauteur}
            dire(f"Carte écrite : {carte} ({info.largeur} × {info.hauteur} pixels, {occupes} occupés)")
    except (carte2d.ErreurCarte2d, carte3d.ErreurCarte3d, ErreurLieu) as e:
        return echec("carte_2d", f"La carte 2D n'a pas pu être fabriquée : {e}. Le nuage 3D est dans {nuage} ; "
                                 "refaites le scan en passant plus près des murs.")
    except Exception as e:
        return echec("carte_2d", f"La carte 2D n'a pas pu être fabriquée (erreur inattendue {type(e).__name__} : "
                                 f"{e}) ; refaites le traitement : g1-scan traiter --lieu {lieu.name} "
                                 f"--session {session} --refaire")
    etapes.append({"etape": "carte_2d", "ok": True, "duree_s": round(time.monotonic() - t0, 1),
                   "message": f"{r['largeur']} × {r['hauteur']} pixels, {r['occupes']} occupés"})

    # 3. nuage d'affichage de la carte 3D : hauteur au-dessus du sol, grille de 5 cm
    t0 = time.monotonic()
    maj(etape="nuage", progression=progression_etape("nuage"), message="Nuage de la carte 3D…")
    try:
        entete = affichage.ecrire_nuage_affichage(base_affichage, points, sol, "scan", session=session, etage=etage,
                                                  grille=carte3d_grille(), mobiles_retires=int(infos["retires_mobiles"]))
    except Exception as e:                       # sans nuage, la carte 2D sert quand même
        texte = f"Nuage de la carte 3D non écrit ({type(e).__name__} : {e}) ; la carte 2D est prête."
        dire(texte)
        avertissements.append(texte)
        entete = None
    etapes.append({"etape": "nuage", "ok": entete is not None, "duree_s": round(time.monotonic() - t0, 1),
                   "message": f"{entete['points']} points" if entete else "pas de nuage d'affichage"})
    comparaison = None
    reference = chemin_carte(lieu, etage)
    if reference.is_file():
        try:
            c = carte2d.comparer_fichiers(carte, reference)
            comparaison = {"reference": f"cartes/{etage}.yaml", "recouvrement": round(c["recouvrement"], 3),
                           "couverture": round(c["couverture"], 3)}
            dire(f"Comparaison avec cartes/{etage}.yaml : recouvrement {c['recouvrement'] * 100:.1f} %, "
                 f"couverture {c['couverture'] * 100:.1f} %")
        except (ErreurLieu, carte2d.ErreurCarte2d) as e:
            avertissements.append(f"comparaison avec cartes/{etage}.yaml impossible : {e}")
    rapport = {"version": 1, "session": session, "termine": instant(),
               "duree_traitement_s": round(time.monotonic() - debut, 1), "etapes": etapes,
               "nuages": {"recus": int(infos["recus"]), "utilises": int(infos["nuages"]),
                          "ignores": int(infos["ignores"])},
               "base_de_temps": infos["base_de_temps"], "mobiles_retires": int(infos["retires_mobiles"]),
               "sol": {"plan": sol["plan"], "inclinaison_deg": sol["inclinaison_deg"], "methode": sol["methode"],
                       "points": sol["points"]},
               "nuage": {"fichier": FICHIERS_SESSION["nuage"], "points": int(infos["points"]),
                         "nuages": int(infos["nuages"]), "retires_mobiles": int(infos["retires_mobiles"])},
               "carte": {"fichier": FICHIERS_SESSION["carte"], "largeur": int(r["largeur"]),
                         "hauteur": int(r["hauteur"]), "resolution": carte2d.RESOLUTION,
                         "occupes": int(r["occupes"])},
               "affichage": None if entete is None else {"fichier": NUAGE_AFFICHAGE + ".bin",
                                                         "points": int(entete["points"]), "grille": entete["grille"]},
               "comparaison": comparaison, "repere": repere, "avertissements": avertissements}
    ecrire_atomique(rapport_fichier, json.dumps(rapport, ensure_ascii=False, indent=2) + "\n")
    nombre = f"{entete['points']:,}".replace(",", " ") if entete else "?"
    message = (f"Scan terminé : la carte 2D et le nuage 3D ({nombre} points) sont prêts. Regardez-les, puis "
               "« Utiliser cette carte ».")
    if avertissements and (infos["ignores"] > carte3d.PART_IGNORES_MAX * infos["recus"] or entete is None):
        message += " Attention : " + avertissements[-1]
    maj(etat="termine", etape="fini", progression=100, message=message[:2000])
    dire(f"{message} ({rapport['duree_traitement_s']:.0f} s)")
    return 0


def carte3d_grille():
    """Grille du nuage d'affichage d'une session : celle de la carte 3D (5 cm)."""
    from atelier.lieu.nuage import GRILLE_NUAGE
    return GRILLE_NUAGE


# ================================================================ adoption

def _monde_pour_l_adoption(lieu, etage, ancien_source, dossier, messages):
    """Le monde de l'étage avant l'extrusion de la carte (section 12.5) : un monde dessiné est gardé dans la
    session (monde_remplace.monde.yaml) et remplacé par un monde qui ne garde que ses piétons dans
    l'emprise de la carte ; un étage déjà scanné garde son monde, sans les éléments tirés d'une ancienne
    reconnaissance (source: scan), que la carte extrudée remplace."""
    from atelier.lieu import charger_info_carte, charger_monde, enregistrer_monde
    from atelier.monde import monde_minimal
    chemin = chemin_monde(lieu, etage)
    info = charger_info_carte(chemin_carte(lieu, etage))
    if not chemin.is_file():
        return
    garde = dossier / FICHIERS_SESSION["monde_remplace"]
    monde = charger_monde(lieu, etage)
    if ancien_source == "monde":
        if not garde.is_file():
            shutil.copyfile(chemin, garde)
        nouveau = monde_minimal(lieu, etage, info)
        e = nouveau.emprise
        dedans = [p for p in monde.pietons if all(e.contient(x, y) for x, y in p.trajet)]
        nouveau.pietons = dedans
        nouveau.carte_extrudee = monde.carte_extrudee
        enregistrer_monde(lieu, etage, nouveau)
        messages.append(f"Monde dessiné gardé dans scans/{dossier.name}/{garde.name}, puis remplacé par la carte "
                        f"extrudée ({len(monde.murs)} murs et {len(monde.objets)} objets retirés, {len(dedans)} "
                        f"piéton(s) gardé(s) sur {len(monde.pietons)})")
        return
    anciens = [m for m in monde.murs if m.source == "scan"] + [o for o in monde.objets if o.source == "scan"]
    if anciens:
        if not garde.is_file():
            shutil.copyfile(chemin, garde)
        monde.murs = [m for m in monde.murs if m.source != "scan"]
        monde.objets = [o for o in monde.objets if o.source != "scan"]
        enregistrer_monde(lieu, etage, monde)
        messages.append(f"{len(anciens)} élément(s) d'une ancienne reconnaissance retiré(s) du monde (la carte "
                        f"extrudée les remplace) ; monde d'avant gardé dans scans/{dossier.name}/{garde.name}")


def adopter(lieu, session, avec_monde=False):
    """La session devient la carte de l'étage, son nuage 3D et son monde de simulation (section 12.5).
    avec_monde : accepté et ignoré (vague 5 : le monde vient toujours de la carte, extrudée).
    Renvoie (messages, rapport de valider_lieu). ErreurScan si la session n'est pas terminée."""
    from atelier.lieu import (InfoCarte, charger_carte, chemin_nuage, chemin_nuage_session, ecrire_nuage,
                              enregistrer_carte, enregistrer_fiche, lire_nuage, valider_lieu)
    from atelier.monde import generer
    lieu = dossier_lieu(lieu)
    dossier = dossier_session(lieu, session)
    s = lire_session(lieu, session)
    etage = s["etage"]
    if s["etat"] != "termine":
        raise ErreurScan(f"la session {session} n'est pas terminée (état {ETATS_LISIBLES[s['etat']]}) : seule une "
                         "session terminée s'adopte (g1-scan etat --lieu L)")
    fiche = charger_fiche(lieu)
    if fiche.etage(etage) is None:
        raise ErreurScan(f"le lieu {lieu.name} n'a plus d'étage « {etage} »")
    if not (dossier / FICHIERS_SESSION["carte"]).is_file():
        raise ErreurScan(f"la session {session} n'a pas de carte 2D : refaites son traitement (g1-scan traiter "
                         f"--lieu {lieu.name} --session {session} --refaire)")
    ancien_source = fiche.etage(etage).source_carte
    messages = []
    # Carte : celle du scan, telle quelle (plus d'effacement de « personnes »)
    info, image = charger_carte(dossier / FICHIERS_SESSION["carte"])
    cible = chemin_carte(lieu, etage)
    cible.parent.mkdir(parents=True, exist_ok=True)
    nouvelle = InfoCarte(image=f"{etage}.pgm", resolution=info.resolution, origin=tuple(info.origin),
                         negate=info.negate, occupied_thresh=info.occupied_thresh, free_thresh=info.free_thresh)
    enregistrer_carte(cible, nouvelle, image)
    messages.append(f"Carte de l'étage remplacée : cartes/{etage}.pgm et .yaml ({image.shape[1]} × {image.shape[0]} "
                    "pixels)")
    pcd = dossier / FICHIERS_SESSION["nuage"]
    if pcd.is_file():
        destination = chemin_pcd(lieu, etage)
        temporaire = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
        shutil.copyfile(pcd, temporaire)
        os.replace(temporaire, destination)
        messages.append(f"Nuage 3D copié : cartes/{etage}.pcd")
    # Nuage de la carte 3D : celui de la session (fabriqué ici pour une session d'avant la vague 5)
    base = chemin_nuage_session(dossier)
    try:
        if not base.with_name(base.name + ".bin").is_file() and pcd.is_file():
            from atelier.scan import affichage, carte3d, sol as S
            nuage = carte3d.lire_pcd(pcd)
            affichage.ecrire_nuage_affichage(base, nuage, S.trouver_sol(nuage), "scan", session=session, etage=etage)
            messages.append("Nuage de la carte 3D fabriqué depuis nuage.pcd (session d'avant la vague 5)")
        points, entete = lire_nuage(base)
        entete = dict(entete, source="scan", session=session, etage=etage)
        ecrire_nuage(chemin_nuage(lieu, etage), points, entete)
        messages.append(f"Nuage de la carte 3D copié : cartes/{etage}.nuage.bin et .json ({entete['points']} points)")
    except (ErreurLieu, OSError) as e:
        texte = "; ".join(getattr(e, "erreurs", [str(e)]))
        messages.append(f"Attention : nuage de la carte 3D non copié ({texte})")
    fiche.etage(etage).source_carte = "scan"
    if s["mode"] == "robot" and s.get("carte_unitree"):
        fiche.carte_unitree = s["carte_unitree"]
        messages.append(f"lieu.yaml : carte_unitree: {s['carte_unitree']} (pour la relocalisation 1804)")
    enregistrer_fiche(fiche)
    messages.append(f"lieu.yaml : l'étage {etage} utilise la carte du scan (source_carte: scan)")
    # Monde de simulation : la carte extrudée (atelier.monde.generer), départ sur le point principal
    _monde_pour_l_adoption(lieu, etage, ancien_source, dossier, messages)
    from atelier.lieu.principal import synchroniser_depart
    try:
        if synchroniser_depart(lieu):
            messages.append(f"mondes/{etage}.monde.yaml : départ du robot remis sur le point principal")
    except Exception as e:  # noqa: BLE001 : l'adoption est faite ; valider_lieu dira ce qui ne va pas
        messages.append(f"Départ du robot non remis sur le point principal ({e}) : voyez g1-lieu valider")
    generation = generer(lieu, etage)
    messages.append("Génération : " + generation.texte().replace("\n", " ; "))
    maj_session(lieu, session, adoption={"quand": instant(), "monde": bool(generation.maillage)})
    if s["mode"] == "robot" and ancien_source == "monde":
        messages.append("Attention : le repère du scan du robot n'est pas celui du monde dessiné. Replacez les salles, "
                        "les nœuds des itinéraires et les zones sur la nouvelle carte.")
    return messages, valider_lieu(lieu)


# ================================================================ lignes de commande

def _ouvrir_lieu(texte):
    dossier = dossier_lieu(texte)
    if not (dossier / "lieu.yaml").is_file():
        raise ErreurScan(f"le lieu {dossier} n'existe pas (pas de lieu.yaml) ; liste des lieux : g1-lieu liste")
    return dossier


def _afficher_erreur(e):
    if isinstance(e, ErreurLieu):
        print("Erreur :")
        for m in getattr(e, "erreurs", [str(e)]):
            print(f"  - {m}")
    else:
        texte = str(e)
        print(f"Erreur : {texte[0].upper() + texte[1:] if texte else type(e).__name__}")
    return 1


def commande_demarrer(args):
    dossier = _ouvrir_lieu(args.lieu)
    fiche = charger_fiche(dossier)
    if fiche.etage(args.etage) is None:
        raise ErreurScan(f"le lieu {dossier.name} n'a pas d'étage « {args.etage} » "
                         f"(étages : {', '.join(e.id for e in fiche.etages)})")
    if args.repetition and args.mode != "robot":
        raise ErreurScan("--repetition ne s'emploie qu'avec --mode robot : elle imite le vrai robot avec la simulation")
    if args.explorer and not (args.mode == "simu" or args.repetition):
        raise ErreurScan("--explorer n'existe qu'avec le robot simulé (--mode simu, ou --mode robot --repetition) : "
                         "le vrai robot se conduit à la télécommande")
    active = session_active(dossier)
    if active is not None:
        raise ErreurScan(f"un scan est déjà en cours dans le lieu {dossier.name} (session {active['id']}, "
                         f"{ETATS_LISIBLES[active['etat']]}) : arrêtez-le d'abord avec g1-scan arreter --lieu "
                         f"{dossier.name}")
    simule = args.mode == "simu" or args.repetition
    if simule and not chemin_sdf(dossier, args.etage).is_file():
        raise ErreurScan(f"le monde Gazebo de l'étage {args.etage} n'existe pas : fabriquez-le d'abord avec "
                         f"g1-monde generer --lieu {dossier.name} --etage {args.etage}")
    if args.explorer and not _graphe_explorable(dossier, args.etage):
        raise ErreurScan(f"pour explorer seul, l'étage {args.etage} doit avoir au moins deux nœuds reliés par un "
                         "couloir dans itineraires.yaml (onglet Itinéraires)")
    if not simule:
        if os.environ.get("G1_SLAM_FAUX") == "1":
            raise ErreurScan("G1_SLAM_FAUX=1 : le vrai robot est interdit dans cet environnement (essais) ; "
                             "ajoutez --repetition pour répéter le scan sans robot")
        verifier_reseau_robot()
    if shutil.which("ros2") is None:
        raise ErreurScan("la commande ros2 est introuvable : chargez l'environnement (source ~/robot-g1/setup/env.sh)")
    s = creer_session(dossier, args.etage, args.mode, nom=args.nom, repetition=args.repetition, explorer=args.explorer)
    journal = _journal(dossier.name, s["id"])
    env = _env()
    if args.pilote:
        env["G1_SCAN_PILOTE"] = args.pilote
    try:
        with open(journal, "ab") as sortie:
            sortie.write(f"===== {instant()} : g1-scan demarrer {' '.join(sys.argv[1:])}\n".encode())
            sortie.flush()
            enfant = subprocess.Popen([sys.executable, "-m", "atelier.scan.session", "session", "--lieu",
                                       str(dossier), "--session", s["id"]], stdout=sortie, stderr=subprocess.STDOUT,
                                      stdin=subprocess.DEVNULL, env=env, cwd=str(RACINE), start_new_session=True)
    except OSError as e:
        maj_session(dossier, s["id"], etat="echec", etape="preparation",
                    message=f"Le processus du scan n'a pas pu être lancé ({e}) : vérifiez l'installation du projet.")
        raise ErreurScan(f"le processus du scan n'a pas pu être lancé : {e}")
    try:
        maj_session(dossier, s["id"], processus=infos_processus(enfant.pid), journal=str(journal))
    except ErreurLieu:
        time.sleep(0.2)
        if enfant.poll() is not None:
            maj_session(dossier, s["id"], etat="echec", etape="preparation",
                        message=f"Le processus du scan s'est arrêté tout de suite : {_fin_journal(journal, 3)}")
            raise ErreurScan(f"le processus du scan s'est arrêté tout de suite ; journal : {journal}")
    if args.json:
        print(json.dumps(etat_scan(dossier, s["id"]), ensure_ascii=False))
        return 0
    print(f"Scan démarré dans le lieu {dossier.name}, étage {args.etage} ({args.mode}"
          + (", répétition" if args.repetition else "") + (", exploration" if args.explorer else "") + ").")
    print(f"Suivi : g1-scan etat --lieu {dossier.name} ; fin : g1-scan arreter --lieu {dossier.name}")
    print(f"Journal : {journal}")
    print(f"session: {s['id']}")
    return 0


def _attendre(dossier, session, condition, delai, afficher=False):
    """Relit la session jusqu'à condition(s) vraie, ou jusqu'au délai. Renvoie la dernière session lue."""
    fin = time.monotonic() + delai
    dernier = None
    while True:
        s = lire_session(dossier, session)
        if afficher:
            ligne = f"{ETATS_LISIBLES[s['etat']]} · {s['etape']} · {s['progression']} % · {s['message']}"
            if ligne != dernier:
                dernier = ligne
                print(f"  {time.strftime('%H:%M:%S')} {ligne}", flush=True)
        if condition(s) or time.monotonic() > fin:
            return s
        if s["etat"] in ETATS_ACTIFS and session_interrompue(s):
            return s
        time.sleep(0.5)


def _lancer_traitement_fond(dossier, s):
    journal = s.get("journal") or str(_journal(dossier.name, s["id"]))
    with open(journal, "ab") as sortie:
        sortie.write(f"===== {instant()} : traitement relancé par g1-scan arreter\n".encode())
        sortie.flush()
        enfant = subprocess.Popen([sys.executable, "-m", "atelier.scan.session", "traiter", "--lieu", str(dossier),
                                   "--session", s["id"]], stdout=sortie, stderr=subprocess.STDOUT,
                                  stdin=subprocess.DEVNULL, env=_env(), cwd=str(RACINE), start_new_session=True)
    maj_session(dossier, s["id"], processus=infos_processus(enfant.pid), journal=journal)
    return enfant.pid


def _attendre_le_bout(dossier, session):
    s = _attendre(dossier, session, lambda s: s["etat"] in ("termine", "echec"), 24 * 3600, afficher=True)
    if s["etat"] == "termine":
        print(f"Terminé : {s['message']}")
        return 0
    if s["etat"] == "echec":
        print(f"Échec : {s['message']}")
    else:
        print(f"Le processus du scan s'est arrêté sans finir (état {ETATS_LISIBLES[s['etat']]}) : relancez "
              f"g1-scan arreter --lieu {dossier.name} --session {session}")
    return 1


def commande_arreter(args):
    dossier = _ouvrir_lieu(args.lieu)
    s = _session_visee(dossier, args.session)
    if s is None:
        print(f"Aucun scan dans le lieu {dossier.name} : rien à arrêter.")
        return 0
    ident = s["id"]
    if s["etat"] in ("termine", "echec"):
        print(f"La session {ident} est déjà finie ({ETATS_LISIBLES[s['etat']]}) : rien à faire.")
        return 1 if (args.attendre and s["etat"] == "echec") else 0
    if session_interrompue(s):
        restes = nettoyer_restes(dossier_session(dossier, ident))
        if restes:
            print(f"Programmes restants de la session arrêtés : {', '.join(restes)}")
        complet = enregistrement_complet(dossier_session(dossier, ident)) or reparer_enregistrement(
            dossier_session(dossier, ident))
        if not complet:
            etape = s["etape"] if s["etape"] in ("preparation", "enregistrement", "arret") else "arret"
            maj_session(dossier, ident, etat="echec", etape=etape,
                        message="Le scan s'est arrêté sans enregistrement : recommencez le scan.")
            print(f"La session {ident} s'était interrompue sans enregistrement complet : elle passe en échec. "
                  "Recommencez le scan.")
            return 1
        if s["etat"] == "en_cours":
            maj_session(dossier, ident, etat="arret_en_cours", etape="arret", progression=5, fin=s["fin"] or instant(),
                        message="Session interrompue : l'enregistrement est complet, le traitement est relancé…")
        pid = _lancer_traitement_fond(dossier, lire_session(dossier, ident))
        print(f"La session {ident} s'était interrompue ; son enregistrement est complet : traitement relancé "
              f"(processus {pid}).")
        return _attendre_le_bout(dossier, ident) if args.attendre else 0
    if s["etat"] == "traitement" or (s["etat"] == "arret_en_cours" and s["fin"]):
        print(f"Le scan {ident} est déjà arrêté : {ETATS_LISIBLES[s['etat']]} ({s['etape']}, {s['progression']} %).")
        return _attendre_le_bout(dossier, ident) if args.attendre else 0
    if not s.get("processus"):              # demarrer vient de lancer le processus : il va être noté
        s = _attendre(dossier, ident, lambda s: bool(s.get("processus")), 3.0)
        if not s.get("processus"):
            print(f"Le processus du scan {ident} n'est pas noté dans session.json : réessayez dans quelques "
                  f"secondes (g1-scan arreter --lieu {dossier.name})")
            return 1
    pid = s["processus"]["pid"]
    sig = signal.SIGUSR1 if args.sans_traitement else signal.SIGINT
    try:
        if os.getpgid(pid) == pid:
            os.killpg(pid, sig)
        else:
            os.kill(pid, sig)
    except ProcessLookupError:
        print(f"Le processus du scan ({pid}) vient de s'arrêter : relancez g1-scan arreter --lieu {dossier.name}")
        return 1
    print(f"Fin du scan {ident} demandée ; attente de la fermeture de l'enregistrement…", flush=True)
    s = _attendre(dossier, ident, lambda s: s["fin"] is not None or s["etat"] not in ("en_cours", "arret_en_cours"),
                  DELAI_FERMETURE)
    if s["etat"] == "echec":
        print(f"Échec : {s['message']}")
        return 1
    if s["fin"] is None and s["etat"] in ("en_cours", "arret_en_cours"):
        if session_interrompue(s):
            print(f"Le processus du scan s'est arrêté sans fermer l'enregistrement : relancez g1-scan arreter --lieu "
                  f"{dossier.name} --session {ident}")
        else:
            print(f"L'enregistrement n'est pas encore fermé après {DELAI_FERMETURE:g} s ; suivez : g1-scan etat --lieu "
                  f"{dossier.name}")
        return 1
    if args.sans_traitement:
        print(f"Enregistrement fermé, sans traitement. Pour le faire : g1-scan traiter --lieu {dossier.name} "
              f"--session {ident}")
        return 0
    print("Enregistrement fermé ; le traitement continue (carte 3D, carte 2D, nuage de la carte 3D).")
    return _attendre_le_bout(dossier, ident) if args.attendre else 0


def commande_traiter(args):
    dossier = _ouvrir_lieu(args.lieu)
    return traiter(dossier, args.session, refaire=args.refaire)


def _texte_session(s):
    st = s["statistiques"]
    lignes = [f"Session {s['id']} « {s['nom']} » : {s['mode']}" + (", répétition" if s["repetition"] else "")
              + (", exploration" if s["explorer"] else ""),
              f"  état : {ETATS_LISIBLES[s['etat']]}, étape {s['etape']}, {s['progression']} %"
              + (" (interrompue : son processus s'est arrêté)" if s.get("interrompue") else ""),
              f"  message : {s['message']}",
              f"  enregistrement : {st['duree_s']:.0f} s, {st['distance_m']:.1f} m parcourus, {st['points']} points, "
              f"{st.get('nuages', 0)} nuages",
              f"  début : {s['debut']}" + (f" ; fin : {s['fin']}" if s["fin"] else "")]
    fichiers = [nom for nom, present in s.get("fichiers", {}).items() if present]
    lignes.append(f"  fichiers : {', '.join(fichiers) or 'aucun'} ({s.get('dossier', '')})")
    if s.get("processus"):
        vivant = {True: "en marche", False: "arrêté", None: "état inconnu"}[s.get("vivant")]
        lignes.append(f"  processus : {s['processus']['pid']} ({vivant})")
    if s.get("journal"):
        lignes.append(f"  journal : {s['journal']}")
    if s.get("carte_unitree"):
        lignes.append(f"  carte Unitree : {s['carte_unitree']}")
    if s.get("adoption"):
        avec = " (avec sa carte extrudée pour la simulation)" if s["adoption"]["monde"] else ""
        lignes.append(f"  adoptée le {s['adoption']['quand']}{avec}")
    return "\n".join(lignes)


def commande_etat(args):
    dossier = dossier_lieu(args.lieu)
    etat = etat_scan(dossier, args.session)
    if args.json:
        print(json.dumps(etat, ensure_ascii=False))
        return 0
    actif = ", un scan actif." if etat["actif"] else "."
    print(f"Lieu {etat['lieu']} : {etat['sessions']} session(s) de scan{actif}")
    if etat["session"] is None:
        print(f"Pour scanner : g1-scan demarrer --lieu {etat['lieu']} --etage rdc --mode simu|robot")
        return 0
    print(_texte_session(etat["session"]))
    return 0


def commande_adopter(args):
    dossier = _ouvrir_lieu(args.lieu)
    messages, rapport = adopter(dossier, args.session)
    for m in messages:
        print(m)
    print(f"Vérification du lieu (g1-lieu valider) :\n{rapport.texte()}")
    return 0


def commande_carte_unitree(args):
    from atelier.scan import carte_unitree
    dossier = _ouvrir_lieu(args.lieu)
    return carte_unitree.commande(dossier, args.etage, args.delai)


def commande_session(args):
    """Le processus d'une session (lancé par demarrer, pas à la main)."""
    return ProcessusSession(args.lieu, args.session).executer()


AIDE = """Scan intégré d'un étage, de « Scan » à la carte 2D et au nuage 3D (sections 9 et 12.5 du plan).

Modes : simu (le robot simulé scanne le monde de l'étage dans Gazebo, --explorer pour qu'il
parcoure seul les couloirs) ; robot (le vrai G1, avec sa cartographie Unitree 1801/1802 ; le PC
suit le robot au câble Ethernet) ; robot --repetition (tout le déroulé du mode robot, sans robot).
Après « Fin » : carte 3D, carte 2D et nuage de la carte 3D. « Utiliser cette carte » (adopter) :
la carte et le nuage deviennent ceux de l'étage, et sa simulation tourne sur la carte extrudée.

Exemple : g1-scan demarrer --lieu demo --etage rdc --mode simu --explorer
          g1-scan etat --lieu demo          g1-scan arreter --lieu demo --attendre
          g1-scan adopter --lieu demo --session 2026-10-25_17h42
          g1-scan traiter --lieu seance --session 2026-10-27_14h22 --refaire
          g1-scan carte-unitree --lieu seance --etage rdc"""


def principal(argv=None):
    from atelier.scan.commande import Analyseur
    p = Analyseur(prog="g1-scan", description=AIDE, formatter_class=argparse.RawDescriptionHelpFormatter)
    sous = p.add_subparsers(dest="commande", metavar="COMMANDE", parser_class=Analyseur)
    sous.required = True

    s = sous.add_parser("demarrer", help="commencer un scan (rend la main tout de suite)")
    s.add_argument("--lieu", required=True, help="dossier du lieu, ou id seul (ex. demo)")
    s.add_argument("--etage", required=True, help="id de l'étage, ex. rdc")
    s.add_argument("--mode", required=True, choices=["robot", "simu"], help="robot (le vrai G1) ou simu (robot simulé)")
    s.add_argument("--repetition", action="store_true", help="mode robot sans robot : faux service et simulation")
    s.add_argument("--explorer", action="store_true", help="le robot simulé parcourt seul tous les couloirs")
    s.add_argument("--nom", help="nom affiché de la session (défaut : « Scan rdc du ... »)")
    s.add_argument("--pilote", choices=["direct", "guide"],
                   help="exploration : direct (ligne droite de nœud en nœud, défaut) ou guide (Nav2, /guide/aller)")
    s.add_argument("--json", action="store_true", help="affiche seulement l'état de la session, en JSON")
    s.set_defaults(fonction=commande_demarrer)

    s = sous.add_parser("arreter", help="« Fin » : arrêter le scan, puis le traitement continue seul")
    s.add_argument("--lieu", required=True, help="dossier du lieu, ou id seul")
    s.add_argument("--session", help="id de la session (défaut : la session active, sinon la plus récente)")
    s.add_argument("--sans-traitement", action="store_true", help="fermer l'enregistrement sans fabriquer les cartes")
    s.add_argument("--attendre", action="store_true", help="attendre la fin du traitement (code 0 : terminé)")
    s.set_defaults(fonction=commande_arreter)

    s = sous.add_parser("traiter", help="carte 3D, carte 2D et nuage de la carte 3D d'une session (au premier plan)")
    s.add_argument("--lieu", required=True, help="dossier du lieu, ou id seul")
    s.add_argument("--session", required=True, help="id de la session, ex. 2026-10-25_17h42")
    s.add_argument("--refaire", action="store_true",
                   help="refaire le traitement d'une session finie, même adoptée : les résultats d'avant sont "
                        "gardés dans ancien_<date>/, et la session est à adopter de nouveau")
    s.set_defaults(fonction=commande_traiter)

    s = sous.add_parser("etat", help="état du scan d'un lieu")
    s.add_argument("--lieu", required=True, help="dossier du lieu, ou id seul")
    s.add_argument("--session", help="id de la session (défaut : la session active, sinon la plus récente)")
    s.add_argument("--json", action="store_true", help="seulement le JSON (atelier.lieu.etat_scan)")
    s.set_defaults(fonction=commande_etat)

    s = sous.add_parser("adopter", help="« Utiliser cette carte » : la carte et le nuage de la session deviennent "
                                        "ceux de l'étage, et sa simulation tourne sur la carte extrudée")
    s.add_argument("--lieu", required=True, help="dossier du lieu, ou id seul")
    s.add_argument("--session", required=True, help="id de la session, ex. 2026-10-25_17h42")
    s.add_argument("--monde", action="store_true", help=argparse.SUPPRESS)      # vague 2 : accepté, sans effet
    s.set_defaults(fonction=commande_adopter)

    s = sous.add_parser("carte-unitree", help="attendre la carte d'Unitree (publiée au début d'un repérage) et "
                                              "l'enregistrer dans le lieu")
    s.add_argument("--lieu", required=True, help="dossier du lieu, ou id seul")
    s.add_argument("--etage", help="id de l'étage (défaut : le premier du lieu)")
    s.add_argument("--delai", type=float, default=60.0, help="attente maximale, en s (défaut 60)")
    s.set_defaults(fonction=commande_carte_unitree)

    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] == ["session"]:                   # processus de la session (interne, lancé par demarrer)
        interne = argparse.ArgumentParser(prog="g1-scan session")
        interne.add_argument("--lieu", required=True)
        interne.add_argument("--session", required=True)
        args = interne.parse_args(argv[1:])
        args.fonction = commande_session
    else:
        args = p.parse_args(argv)
    try:
        return args.fonction(args)
    except (ErreurScan, ErreurLieu) as e:
        return _afficher_erreur(e)
    except KeyboardInterrupt:
        return 1


if __name__ == "__main__":
    sys.exit(principal())
