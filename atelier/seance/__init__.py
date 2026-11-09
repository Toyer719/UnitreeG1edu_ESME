"""Boîte noire et rapport de séance (vague 6, section 13.3 du plan) : agent Boîte noire.

Modules du paquet :
  manifeste    le dossier d'une séance et seance.json (écritures atomiques sous verrou de fichier)
  actions      le journal des actions (genre et texte en français, file et fil d'écriture)
  enregistreur l'enregistreur ROS 2 léger et borné (g1-seance enregistrer), rosbag2 sqlite3
  lecture      la lecture du bag (sqlite3 + rclpy), sa réindexation
  analyse      trajets, états du pont, modes, erreurs, repérage, anomalies, chronologie (fonctions pures)
  rapport      rapport.json, rapport.md, rapport.html et trajets.png (g1-seance rapport)
  export       le .zip d'une séance (g1-seance exporter)
  __main__     la commande g1-seance

Contrat : GestionnaireSeance(etat_serveur), un par serveur, créé par EtatServeur (etat.seance). Ses méthodes
sont appelées par le serveur et ne doivent JAMAIS lever d'exception vers lui ni le ralentir (sauf demarrer et
arreter, appelées par les routes, qui peuvent lever ErreurAtelier) :
  demarrer(mode, lieu=None, etage=None, ouverture="auto") -> dict   ouvre la séance (mode reel ou repetition),
        ou rend celle qui est déjà ouverte : le manifeste (schéma seance) ; Simulation : 409 ;
  arreter(fermeture="terminer") -> dict | None   la ferme (journal du Jetson, fin de l'enregistrement, manifeste),
        puis lance le rapport en arrière-plan ; None s'il n'y en avait pas ;
  etat() -> dict | None          la séance ouverte, en bref (champ seance de /ws/etat, badge « ● Enregistrement ») ;
  noter_action(action) -> None   appelée par l'accroche de main.py (JournalDesActions), APRÈS chaque réponse à une
        demande POST, PUT, PATCH ou DELETE sous /api/ : action = {t, methode, chemin, requete, statut, reponse,
        duree_ms, client} (13.3) ; sans séance ouverte, rien ; rend la main tout de suite (file + fil) ;
  avant_arret_jetson(local=False) -> dict | None   juste avant chaque « g1-jetson arreter » lancé par l'Atelier
        (routes/simulation.py) : g1-jetson journal dans journaux/jetson/ de la séance (30 s au plus) ;
  demarrage_serveur() -> None    au démarrage du serveur : une séance restée « ouverte » sans enregistreur vivant
        devient « interrompue » (bag réindexé, rapport), en arrière-plan ; aucune séance ne s'ouvre seule ;
  fermer(fermeture="arret_atelier") -> None   à l'arrêt du serveur, 10 s au plus (le rapport se fait à part).
Pour les routes (routes/seance.py) : manifeste_ouvert(), derniere(), lancer_rapport(dossier).

À l'ouverture : le dossier et seance.json (« ouverte »), la copie du lieu (lieu/), le journal du serveur
(journaux/serveur.log), le journal des actions, l'enregistreur (g1-seance enregistrer, rôle « seance » de
etat.gestionnaire ; absent si l'Atelier tourne sans ROS 2 ou sans la commande), le diagnostic du début en arrière-plan
(diagnostic_debut.json), et un fil de surveillance (une fois par seconde : état de l'enregistreur, journaux des
commandes lancées, nombre d'actions, manifeste).
"""
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import atelier
from atelier.lieu.seance import FICHIERS_SEANCE, OUVERTURES, reglage
from . import manifeste as M
from .actions import JournalActions
from .enregistreur import lire_etat

JOURNAL = logging.getLogger("atelier.seance")

PERIODE_SURVEILLANCE_S = 1.0
DELAI_JETSON_S = 30.0             # g1-jetson journal (13.3)
DELAI_FERMETURE_S = 10.0          # fermer() à l'arrêt de l'Atelier
FERMETURES_NOTEES = ("terminer", "g1-seance", "simulation")   # notées dans le journal des actions par la séance
ATTENTE_ENREGISTREUR_S = 8.0      # après SIGINT, l'enregistreur ferme son bag (en moins d'une seconde d'habitude)
ATTENTE_REPRISE_S = 15.0          # reprise : un enregistreur orphelin s'arrête seul en 1 à 2 s
LIGNES_JETSON = 100000
MESSAGES_MAX = 50
# Fichiers du lieu copiés dans lieu/ (petits) ; plus la carte 2D de l'étage (cartes/<étage>*.yaml et .pgm)
FICHIERS_LIEU_COPIES = ("lieu.yaml", "salles.yaml", "itineraires.yaml", "zones.yaml", "demo.yaml",
                        "personnalites.yaml", "dialogues.yaml", "camera.yaml", "guide.yaml")
MODES_SEANCE = {"reel": "reel", "robot": "reel", "repetition": "repetition"}
BADGES = {"demarrage": "enregistrement", "en_cours": "enregistrement", "coupe": "coupe"}
MESSAGE_SIMULATION = ("Pas de séance en Simulation : la boîte noire n'enregistre que les séances avec le robot "
                      "(Réel) ou en répétition sans robot.")


def _erreur(statut, detail):
    from atelier.serveur.communs import ErreurAtelier
    return ErreurAtelier(statut, detail)


def ligne_de_commande(pid):
    try:
        return Path(f"/proc/{int(pid)}/cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
    except (OSError, ValueError, TypeError):
        return ""


def atelier_vivant(pid):
    """Vrai si ce PID est un serveur de l'Atelier qui tourne (et pas ce serveur-ci)."""
    return bool(pid) and int(pid) != os.getpid() and "atelier.serveur" in ligne_de_commande(pid)


def enregistreur_vivant(pid, dossier=None):
    texte = ligne_de_commande(pid) if pid else ""
    return "atelier.seance" in texte and "enregistrer" in texte and (dossier is None or str(dossier) in texte)


def copier_lieu(source, destination, etage=None):
    """Copie dans destination les petits fichiers du lieu et la carte 2D de l'étage (ou de tous les étages).
    Renvoie la liste des fichiers copiés (chemins relatifs)."""
    source, destination = Path(source), Path(destination)
    copies = []
    destination.mkdir(parents=True, exist_ok=True)
    for nom in FICHIERS_LIEU_COPIES:
        if (source / nom).is_file():
            shutil.copy2(source / nom, destination / nom)
            copies.append(nom)
    cartes = source / "cartes"
    if cartes.is_dir():
        motif = f"{etage}*" if etage else "*"
        for f in sorted(cartes.glob(motif)):
            if f.is_file() and f.suffix in (".yaml", ".pgm") and (etage is None or f.stem in (
                    etage, f"{etage}_interdit", f"{etage}_lent")):
                (destination / "cartes").mkdir(exist_ok=True)
                shutil.copy2(f, destination / "cartes" / f.name)
                copies.append(f"cartes/{f.name}")
    return copies


def copier_fin(source, destination, maximum):
    """Copie les derniers `maximum` octets d'un journal (le début est coupé et le fichier le dit)."""
    source, destination = Path(source), Path(destination)
    taille = source.stat().st_size
    destination.parent.mkdir(parents=True, exist_ok=True)
    with open(source, "rb") as entree, open(destination, "wb") as sortie:
        if taille > maximum:
            entree.seek(taille - maximum)
            entree.readline()           # commencer au début d'une ligne
            sortie.write(f"[… début du journal coupé : {taille - maximum} octets de plus dans {source}]\n"
                         .encode("utf-8"))
        shutil.copyfileobj(entree, sortie)


class _FiltreAcces(logging.Filter):
    """Journal d'accès d'uvicorn dans serveur.log : seulement les demandes qui changent quelque chose (POST, PUT,
    PATCH, DELETE) et les erreurs ; pas les lectures (la page lit beaucoup, et sans intérêt)."""

    def filter(self, record):
        try:
            methode, statut = record.args[1], int(record.args[4])
        except (IndexError, TypeError, ValueError):
            return True
        return methode != "GET" or statut >= 400


class _Ouverte:
    """Ce que le gestionnaire garde de la séance ouverte."""

    def __init__(self, dossier, manifeste):
        self.dossier = dossier
        self.manifeste = manifeste
        self.debut = M.lire_heure(manifeste["debut"]) or time.time()
        self.journal = None
        self.processus = None             # le Processus de l'enregistreur (etat.gestionnaire, rôle seance)
        self.journaux = {}                # journal d'une commande lancée pendant la séance → rôle
        self.gestionnaires_log = []       # (logger, handler) à retirer à la fermeture
        self.fin = threading.Event()
        self.fil = None
        self.ecrit = None                 # dernier texte écrit du manifeste (pour n'écrire que les changements)
        self.fermeture = False
        self.journal_ferme = False      # le journal des actions est fermé : plus aucune action notée


class GestionnaireSeance:
    """La séance de la boîte noire, une à la fois par serveur (voir le contrat en tête du module)."""

    def __init__(self, etat_serveur=None):
        self.etat_serveur = etat_serveur
        self._verrou = threading.RLock()
        self._ouverte = None
        self._derniere = None             # dossier de la dernière séance fermée par ce serveur
        self._rapports = []               # processus des rapports lancés (ramassés quand ils finissent)
        self._reprise = None
        self._cree = time.time()          # une séance ouverte depuis est à ce serveur (même PID qu'un ancien)

    # ------------------------------------------------------------ outils

    def _mode_navigation(self):
        try:
            return self.etat_serveur.mode_navigation() if self.etat_serveur is not None else None
        except Exception:       # noqa: BLE001
            return None

    def _mode(self, mode):
        """Le mode de la séance (reel ou repetition) ; ErreurAtelier 409 en Simulation, 400 si inconnu."""
        if mode in (None, ""):
            courant = self._mode_navigation()
            if courant == "simu":
                raise _erreur(409, MESSAGE_SIMULATION)
            return MODES_SEANCE.get(courant, "reel")
        if mode == "simu":
            raise _erreur(409, MESSAGE_SIMULATION)
        if mode not in MODES_SEANCE:
            raise _erreur(400, f"Mode « {mode} » inconnu : reel (le robot) ou repetition (sans robot).")
        return MODES_SEANCE[mode]

    def _lieu(self, lieu, etage):
        """(id du lieu, étage, dossier) ; le lieu de la navigation qui tourne si aucun n'est donné."""
        from atelier.serveur.communs import dossier_du_lieu, etage_du_lieu, fiche_du_lieu
        sim = getattr(self.etat_serveur, "simulation", None) or {}
        if not lieu and sim.get("lieu"):
            lieu, etage = sim["lieu"], etage or sim.get("etage")
        if not lieu:
            return None, None, None
        dossier = dossier_du_lieu(lieu)
        if etage:
            etage_du_lieu(dossier, etage)
        else:
            try:
                from atelier.lieu.principal import point_principal
                p = point_principal(dossier)
                etage = p.etage if p else None
            except Exception:       # noqa: BLE001
                etage = None
            if etage is None:
                etages = fiche_du_lieu(dossier).etages
                etage = etages[0].id if etages else None
        return lieu, etage, dossier

    def _ecrire(self, o, forcer=False):
        """Réécrit le manifeste de la séance ouverte s'il a changé ; jamais d'exception."""
        try:
            texte = json.dumps(o.manifeste, ensure_ascii=False, sort_keys=True)
            if forcer or texte != o.ecrit:
                M.ecrire_manifeste(o.dossier, o.manifeste)
                o.ecrit = texte
        except Exception:       # noqa: BLE001
            JOURNAL.exception("boîte noire : manifeste non écrit")

    def _message(self, o, texte):
        messages = o.manifeste.setdefault("messages", [])
        if texte not in messages and len(messages) < MESSAGES_MAX:
            messages.append(str(texte)[:300])

    # ------------------------------------------------------------ ouverture

    def demarrer(self, mode=None, lieu=None, etage=None, ouverture="auto"):
        if self.etat_serveur is None:
            raise _erreur(503, "La boîte noire a besoin du serveur de l'Atelier : lancez g1-atelier (ou, sans "
                               "Atelier, g1-seance enregistrer --dossier DOSSIER).")
        mode = self._mode(mode)
        with self._verrou:
            if self._ouverte is not None:
                return json.loads(json.dumps(self._ouverte.manifeste))
            lieu, etage, dossier_lieu = self._lieu(lieu, etage)
            ident, dossier = M.creer_dossier()
            port = os.environ.get("ATELIER_PORT")
            m = M.nouveau_manifeste(ident, mode, lieu, etage, ouverture if ouverture in OUVERTURES else "manuel",
                                    port=int(port) if port and port.isdigit() else None)
            o = _Ouverte(dossier, m)
            self._ecrire(o, forcer=True)
            noms = {}
            if dossier_lieu is not None:
                try:
                    copier_lieu(dossier_lieu, M.chemin(dossier, "lieu"), etage)
                    from atelier.lieu import charger_salles
                    noms = {s.id: s.nom for s in charger_salles(M.chemin(dossier, "lieu"))}
                except Exception as e:      # noqa: BLE001 : la séance s'ouvre quand même
                    self._message(o, f"Copie du lieu incomplète : {e}")
            self._brancher_journal_serveur(o)
            o.journal = JournalActions(M.chemin(dossier, "actions"), o.debut, mode, noms,
                                       sur_note=lambda n: o.manifeste.__setitem__("actions", n),
                                       mode_actuel=self._mode_navigation)
            self._lancer_enregistreur(o)
            self._ouverte = o
            self._ecrire(o, forcer=True)
            o.fil = threading.Thread(target=self._surveiller, args=(o,), name="séance (surveillance)", daemon=True)
            o.fil.start()
            threading.Thread(target=self._diagnostic, args=(o,), name="séance (diagnostic)", daemon=True).start()
            JOURNAL.warning("boîte noire : séance %s ouverte (%s, lieu %s, %s)", ident, mode, lieu, ouverture)
            return json.loads(json.dumps(m))

    def _brancher_journal_serveur(self, o):
        """journaux/serveur.log : les journaux du serveur (atelier.*, uvicorn, et les demandes qui changent quelque
        chose) pendant la séance. La sortie d'erreur de l'Atelier reste la même (logging.lastResort)."""
        try:
            fichier = M.chemin(o.dossier, "serveur")
            fichier.parent.mkdir(parents=True, exist_ok=True)
            gestionnaire = logging.FileHandler(fichier, encoding="utf-8")
            gestionnaire.setLevel(logging.INFO)
            gestionnaire.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s : %(message)s"))
            racine = logging.getLogger()
            if not racine.handlers and logging.lastResort is not None:
                racine.addHandler(logging.lastResort)       # les avertissements vont toujours au terminal
                o.gestionnaires_log.append((racine, logging.lastResort))
            racine.addHandler(gestionnaire)
            o.gestionnaires_log.append((racine, gestionnaire))
            for nom in ("uvicorn", "uvicorn.access"):
                journal = logging.getLogger(nom)
                if not journal.propagate:
                    gestionnaire_nom = logging.FileHandler(fichier, encoding="utf-8")
                    gestionnaire_nom.setFormatter(gestionnaire.formatter)
                    if nom == "uvicorn.access":
                        gestionnaire_nom.addFilter(_FiltreAcces())
                    journal.addHandler(gestionnaire_nom)
                    o.gestionnaires_log.append((journal, gestionnaire_nom))
            if JOURNAL.level == logging.NOTSET or JOURNAL.level > logging.INFO:
                JOURNAL.setLevel(logging.INFO)
        except Exception as e:      # noqa: BLE001
            self._message(o, f"Journal du serveur non gardé : {e}")

    def _debrancher_journal_serveur(self, o):
        for journal, gestionnaire in o.gestionnaires_log:
            try:
                journal.removeHandler(gestionnaire)
                if gestionnaire is not logging.lastResort:
                    gestionnaire.close()
            except Exception:       # noqa: BLE001
                pass
        o.gestionnaires_log = []

    def _lancer_enregistreur(self, o):
        e = o.manifeste["enregistrement"]
        etat = self.etat_serveur
        if not getattr(etat, "ros", True):
            e.update(etat="absent", message="L'Atelier tourne sans ROS 2 : rien n'est enregistré (actions et rapport "
                                            "seulement).")
            return
        from atelier.serveur.processus import CommandeAbsente
        try:
            p = etat.gestionnaire.lancer("seance", "g1-seance",
                                         ["enregistrer", "--dossier", str(o.dossier), "--atelier", str(os.getpid())],
                                         {"seance": o.manifeste["id"]})
        except CommandeAbsente:
            e.update(etat="absent", message="Enregistrement impossible : la commande g1-seance est introuvable "
                                            "(actions et rapport seulement).")
            return
        except Exception as ex:     # noqa: BLE001
            e.update(etat="erreur", message=f"Enregistrement impossible : {ex}"[:300])
            return
        o.processus = p
        e.update(etat="demarrage", pid=p.popen.pid)
        if p.journal:
            o.journaux[str(p.journal)] = "seance"

    def _diagnostic(self, o):
        """Le diagnostic du début (13.2), en arrière-plan : diagnostic_debut.json ; rien s'il n'existe pas encore."""
        try:
            from atelier.diagnostic import diagnostiquer
            resultat = diagnostiquer(o.manifeste["mode"], getattr(self.etat_serveur, "pont", None), source="seance")
        except NotImplementedError:
            return
        except Exception as e:      # noqa: BLE001
            with self._verrou:
                self._message(o, f"Diagnostic du début impossible : {e}")
            return
        if not isinstance(resultat, dict):
            return
        try:
            from atelier.lieu.fichiers import ecrire_atomique
            ecrire_atomique(M.chemin(o.dossier, "diagnostic_debut"),
                            json.dumps(resultat, ensure_ascii=False, indent=1) + "\n")
        except OSError as e:
            JOURNAL.warning("boîte noire : diagnostic du début non écrit (%s)", e)
            return
        nom = FICHIERS_SEANCE["diagnostic_debut"]
        with self._verrou:
            if self._ouverte is o:
                o.manifeste["diagnostic_debut"] = nom
                self._ecrire(o)
            else:
                M.modifier_manifeste(o.dossier, lambda m: m.__setitem__("diagnostic_debut", nom))

    # ------------------------------------------------------------ surveillance

    def _surveiller(self, o):
        while not o.fin.wait(PERIODE_SURVEILLANCE_S):
            try:
                with self._verrou:
                    if o.fermeture:
                        continue
                    self._mettre_a_jour(o)
                    self._ecrire(o)
            except Exception:       # noqa: BLE001 : la surveillance ne s'arrête jamais sur une erreur
                JOURNAL.exception("boîte noire : surveillance")

    def _mettre_a_jour(self, o):
        """L'état de l'enregistreur (enregistrement.json et son processus), les journaux des commandes lancées."""
        e = o.manifeste["enregistrement"]
        lu = lire_etat(o.dossier)
        if lu:
            for cle in ("etat", "octets", "message", "pid"):
                if cle in lu:
                    e[cle] = lu[cle]
            e["sujets"] = list(lu.get("sujets") or [])[:200]
            e["messages"] = lu.get("messages", 0)
            e["cpu_moyen"] = lu.get("cpu_moyen")
        p = o.processus
        if p is not None and not p.en_cours and e.get("etat") in ("demarrage", "en_cours"):
            code = p.popen.poll() if p.popen is not None else None
            e["etat"] = "erreur"
            seul = (f"L'enregistreur s'est arrêté seul (code {code}) : la séance continue sans enregistrement. "
                    "Voyez son journal dans la séance.")
            e["message"] = (e.get("message") or seul)[:300]
        try:
            for role, proc in dict(self.etat_serveur.gestionnaire.processus).items():
                if proc.journal and (proc.en_cours or (proc.fin or 0) >= o.debut):
                    o.journaux.setdefault(str(proc.journal), role)
        except Exception:       # noqa: BLE001
            pass
        if o.journal is not None:
            o.manifeste["actions"] = o.journal.nombre

    # ------------------------------------------------------------ lecture

    def etat(self):
        o = self._ouverte
        if o is None:
            return None
        try:
            m = o.manifeste
            e = m.get("enregistrement") or {}
            return {"id": m["id"], "etat": "ouverte", "mode": m["mode"], "lieu": m.get("lieu"),
                    "etage": m.get("etage"), "debut": m["debut"], "depuis_s": round(time.time() - o.debut, 1),
                    "actions": m.get("actions", 0), "badge": BADGES.get(e.get("etat"), "arrete"),
                    "enregistrement": {"etat": e.get("etat"), "octets": e.get("octets", 0),
                                       "message": e.get("message")},
                    "diagnostic_debut": m.get("diagnostic_debut"), "fermeture": o.fermeture}
        except Exception:       # noqa: BLE001
            return None

    def manifeste_ouvert(self):
        o = self._ouverte
        if o is None:
            return None
        with self._verrou:
            return json.loads(json.dumps(o.manifeste))

    def derniere(self):
        """Le manifeste de la dernière séance fermée (par ce serveur, sinon la plus récente du dossier), ou None."""
        if self._derniere is not None:
            m = M.lire_manifeste(self._derniere)
            if m is not None:
                return m
        ouverte = self._ouverte.dossier if self._ouverte is not None else None
        for _, dossier in M.liste_seances():
            if dossier == ouverte:
                continue
            m = M.lire_manifeste(dossier)
            if m is not None and m.get("etat") != "ouverte":
                return m
        return None

    def noter_action(self, action):
        try:
            o = self._ouverte
            # corrections de la vague 6 : les actions faites pendant « Terminer la séance » (journal du Jetson jusqu'à
            # 30 s, arrêt de l'enregistreur) sont gardées, ARRÊT compris : le journal se ferme en dernier
            if o is not None and o.journal is not None and not o.journal_ferme:
                o.journal.noter(action)
        except Exception:       # noqa: BLE001 : la boîte noire ne gêne jamais une demande
            pass
        return None

    # ------------------------------------------------------------ journal du conteneur du Jetson

    def avant_arret_jetson(self, local=False, raison="avant_arret", delai=DELAI_JETSON_S):
        o = self._ouverte
        if o is None:
            return None
        try:
            return self._journal_jetson(o, local, raison, delai)
        except Exception:       # noqa: BLE001 : jamais un empêchement d'arrêter le robot
            JOURNAL.exception("boîte noire : journal du Jetson")
            return None

    def _journal_jetson(self, o, local, raison, delai):
        from atelier.serveur.processus import CommandeAbsente, lancer_et_attendre
        nom = f"conteneur_{time.strftime('%Y-%m-%d_%Hh%Mm%Ss')}_{raison}.log"
        relatif = f"{FICHIERS_SEANCE['jetson']}/{nom}"
        fichier = o.dossier / relatif
        fichier.parent.mkdir(parents=True, exist_ok=True)
        arguments = ["journal", "--lignes", str(LIGNES_JETSON)] + (["--local"] if local else [])
        debut = time.monotonic()
        try:
            r = lancer_et_attendre("g1-jetson", arguments, delai)
        except CommandeAbsente:
            r = {"code": None, "sortie": "g1-jetson est introuvable : journal du conteneur non récupéré.\n"}
        fichier.write_text(r.get("sortie") or "", encoding="utf-8")
        ok = r.get("code") == 0
        derniere = [x for x in (r.get("sortie") or "").strip().splitlines() if x.strip()][-1:] or [""]
        trop_long = r.get("code") is None and time.monotonic() - debut >= delai - 0.5
        pourquoi = "délai dépassé" if trop_long else f"code {r.get('code')}"
        entree = {"fichier": relatif, "t": M.heure_iso(), "raison": raison, "octets": fichier.stat().st_size,
                  "ok": ok, "message": None if ok else f"g1-jetson journal : {pourquoi} ({derniere[0][:200]})"[:300]}
        with self._verrou:
            o.manifeste.setdefault("jetson", []).append(entree)
            self._ecrire(o)
        JOURNAL.warning("boîte noire : journal du conteneur du Jetson gardé (%s, %s octets)", nom, entree["octets"])
        return entree

    # ------------------------------------------------------------ fermeture

    def arreter(self, fermeture="terminer", delai=None):
        """Ferme la séance ouverte et lance son rapport ; None s'il n'y en a pas. delai : temps maximal (s) de la
        fermeture (fermer() à l'arrêt de l'Atelier : 10 s)."""
        with self._verrou:
            o = self._ouverte
            if o is None or o.fermeture:
                return None
            o.fermeture = True
            debut = time.monotonic()
            reste = (lambda: max(0.5, delai - (time.monotonic() - debut))) if delai else (lambda: None)
            m = o.manifeste
            # 0. « Terminer la séance » est noté par la séance elle-même, à l'heure de la demande (la demande qui la
            #    ferme ne peut plus l'être), par la file : dans l'ordre des actions ; le journal reste ouvert jusqu'à
            #    l'étape 3
            if o.journal is not None and fermeture in FERMETURES_NOTEES:
                try:
                    o.journal.noter({"t": M.heure_iso(ms=True), "methode": "POST", "chemin": "/api/seance/arreter",
                                      "requete": {"fermeture": fermeture}, "statut": 200, "reponse": None,
                                      "duree_ms": 0.0, "client": "local"})
                except Exception:       # noqa: BLE001
                    pass
            # 1. le journal du conteneur du Jetson, si le robot tourne encore (raison fin)
            if self._mode_navigation() == "robot":
                attente = DELAI_JETSON_S if delai is None else min(DELAI_JETSON_S, max(1.0, reste() * 0.5))
                self.avant_arret_jetson(local=False, raison="fin", delai=attente)
            # 2. l'enregistreur : SIGINT, le bag se ferme proprement
            if o.processus is not None and o.processus.en_cours:
                attente = ATTENTE_ENREGISTREUR_S if delai is None else min(ATTENTE_ENREGISTREUR_S, max(1.0, reste()))
                try:
                    o.processus.arreter(attente_sigint=attente)
                except Exception:       # noqa: BLE001
                    JOURNAL.exception("boîte noire : arrêt de l'enregistreur")
            o.fin.set()
            try:
                self._mettre_a_jour(o)
            except Exception:       # noqa: BLE001
                pass
            e = m["enregistrement"]
            if e.get("etat") in ("demarrage", "en_cours"):
                e["etat"] = "arrete"
            # 3. le journal des actions, fermé en dernier (les actions faites pendant 1 et 2 y sont), file vidée
            if o.journal is not None:
                o.journal_ferme = True
                o.journal.arreter(delai=2.0)
                m["actions"] = o.journal.nombre
            # 4. la fin des journaux des commandes lancées pendant la séance
            self._copier_journaux(o)
            self._debrancher_journal_serveur(o)
            # 5. le manifeste, puis le rapport en arrière-plan
            fin = time.time()
            m.update(etat="fermee", fin=M.heure_iso(fin), duree_s=round(max(0.0, fin - o.debut), 1),
                     fermeture=fermeture)
            m["rapport"] = {"etat": "en_cours", "fichiers": [], "message": None, "date": None}
            self._ecrire(o, forcer=True)
            self._ouverte = None
            self._derniere = o.dossier
            try:
                self.lancer_rapport(o.dossier)
            except Exception as ex:     # noqa: BLE001
                echec = {"etat": "echec", "fichiers": [], "message": f"Rapport non lancé : {ex}"[:300],
                         "date": M.heure_iso()}
                M.modifier_manifeste(o.dossier, lambda x: x.__setitem__("rapport", echec))
            JOURNAL.warning("boîte noire : séance %s fermée (%s, %s actions)", m["id"], fermeture, m.get("actions"))
            return json.loads(json.dumps(M.lire_manifeste(o.dossier) or m))

    def _copier_journaux(self, o):
        maximum = int(reglage("journal_max_mo") * 1000 * 1000)
        for chemin_journal in sorted(o.journaux):
            source = Path(chemin_journal)
            if not source.is_file():
                continue
            try:
                copier_fin(source, M.chemin(o.dossier, "journaux") / source.name, maximum)
            except OSError as e:
                self._message(o, f"Journal non copié ({source.name}) : {e}")

    def fermer(self, fermeture="arret_atelier"):
        try:
            self.arreter(fermeture, delai=DELAI_FERMETURE_S)
        except Exception:       # noqa: BLE001
            JOURNAL.exception("boîte noire : séance non fermée")
        return None

    # ------------------------------------------------------------ rapport

    def lancer_rapport(self, dossier, attendre=False):
        """g1-seance rapport DOSSIER, détaché (il survit à l'arrêt de l'Atelier) ; attendre : jusqu'à sa fin."""
        dossier = Path(dossier)
        self._rapports = [p for p in self._rapports if p.poll() is None]
        env = dict(os.environ)
        env.pop("ATELIER_LIEUX", None)          # le rapport ne lit que le dossier de la séance
        env["PYTHONPATH"] = str(atelier.RACINE) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        journal = M.chemin(dossier, "journaux")
        journal.mkdir(parents=True, exist_ok=True)
        with open(journal / "rapport.log", "ab") as sortie:
            p = subprocess.Popen([sys.executable, "-m", "atelier.seance", "rapport", str(dossier)],
                                 cwd=str(atelier.RACINE), env=env, stdin=subprocess.DEVNULL, stdout=sortie,
                                 stderr=subprocess.STDOUT, start_new_session=True)
        self._rapports.append(p)
        if attendre:
            try:
                p.wait(timeout=600)
            except subprocess.TimeoutExpired:
                pass
        return p

    # ------------------------------------------------------------ reprise après un plantage

    def demarrage_serveur(self):
        if self._reprise is not None and self._reprise.is_alive():
            return None
        self._reprise = threading.Thread(target=self._reprendre, name="séance (reprise)", daemon=True)
        self._reprise.start()
        return None

    def _reprendre(self):
        """Les séances restées « ouvertes » par un Atelier qui ne tourne plus deviennent « interrompues » ; leur
        bag est réindexé et leur rapport fait par g1-seance rapport (un à la fois)."""
        try:
            seances = M.liste_seances()
        except Exception:       # noqa: BLE001
            return
        for _, dossier in seances:
            try:
                self._reprendre_une(dossier)
            except Exception:       # noqa: BLE001
                JOURNAL.exception("boîte noire : reprise de %s", dossier)

    def _reprendre_une(self, dossier):
        m = M.lire_manifeste(dossier)
        if not m or m.get("etat") != "ouverte":
            return False
        o = self._ouverte
        if o is not None and o.dossier == dossier:
            return False
        pid_atelier = (m.get("atelier") or {}).get("pid")
        a_ce_serveur = pid_atelier == os.getpid() and (M.lire_heure(m.get("debut")) or 0.0) >= self._cree - 1.0
        if a_ce_serveur or atelier_vivant(pid_atelier):
            return False                    # ouverte par ce serveur-ci, ou par un autre Atelier qui tourne
        lu = lire_etat(dossier) or {}
        pid = lu.get("pid") or (m.get("enregistrement") or {}).get("pid")
        fin_attente = time.monotonic() + ATTENTE_REPRISE_S
        while pid and enregistreur_vivant(pid, dossier) and time.monotonic() < fin_attente:
            time.sleep(0.5)             # l'enregistreur orphelin voit que l'Atelier n'est plus là et ferme son bag
        if pid and enregistreur_vivant(pid, dossier):
            try:
                os.kill(int(pid), 2)        # SIGINT : fermeture propre
            except OSError:
                pass
            time.sleep(2.0)
        fin = M.derniere_ecriture(dossier) or time.time()
        message = ("Séance retrouvée ouverte au démarrage de l'Atelier : l'Atelier précédent s'est arrêté sans la "
                   "fermer (plantage ou coupure). Elle est marquée interrompue ; ce qui a été enregistré est gardé.")

        def interrompre(x):
            debut = M.lire_heure(x.get("debut")) or fin
            x.update(etat="interrompue", fin=M.heure_iso(max(fin, debut)), duree_s=round(max(0.0, fin - debut), 1),
                     fermeture="plantage")
            e = x.setdefault("enregistrement", {"etat": "arrete", "octets": 0})
            lu2 = lire_etat(dossier) or {}
            for cle in ("etat", "octets", "message"):
                if cle in lu2:
                    e[cle] = lu2[cle]
            if e.get("etat") in ("demarrage", "en_cours"):
                e["etat"] = "arrete"
            if (dossier / FICHIERS_SEANCE["actions"]).is_file():
                with open(dossier / FICHIERS_SEANCE["actions"], "rb") as f:
                    x["actions"] = sum(1 for _ in f)
            messages = x.setdefault("messages", [])
            if message not in messages and len(messages) < MESSAGES_MAX:
                messages.append(message)
            x["rapport"] = {"etat": "en_cours", "fichiers": [], "message": None, "date": None}
        M.modifier_manifeste(dossier, interrompre)
        JOURNAL.warning("boîte noire : séance %s interrompue retrouvée, rapport en cours", dossier.name)
        self.lancer_rapport(dossier, attendre=True)
        return True
