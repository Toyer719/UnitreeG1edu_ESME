"""Routes du scan intégré (section 9.7 du plan), utilisées par l'onglet Scan de l'Atelier.

  POST /api/scan/demarrer {lieu, etage, mode, repetition?, explorer?, nom?}   g1-scan demarrer
  POST /api/scan/arreter {lieu, session?}                                     g1-scan arreter (« Fin »)
  GET  /api/scan/etat ?lieu=L[&session=S]                                     atelier.lieu.etat_scan
  GET  /api/scan/apercu.png, /api/scan/apercu.json ?lieu=L[&session=S]        aperçu en direct
  GET  /api/scan/sessions ?lieu=L                                             scans du lieu (historique)
  GET  /api/scan/sessions/{s}/reconnaissance ?lieu=L                          éléments reconnus
  PUT  /api/scan/sessions/{s}/reconnaissance ?lieu=L {a_garder: {id: bool}}   cases « à garder »
  GET  /api/scan/sessions/{s}/carte.png, carte.yaml, monde ?lieu=L            carte et monde du scan
  GET  /api/scan/sessions/{s}/rapport ?lieu=L                                 (ajout) rapport.json
  POST /api/scan/sessions/{s}/adopter ?lieu=L {monde}                         g1-scan adopter [--monde]

Le serveur lance g1-scan (agent Orchestrateur) pour démarrer, arrêter et adopter ; il lit
directement les fichiers des sessions par atelier.lieu pour tout le reste (pas de sous-processus
à chaque interrogation). Les commandes sont cherchées dans $ATELIER_BIN (fausses dans les tests).

Un scan démarré par le serveur est rangé parmi ses processus (rôle « scan », classe SuiviScan) :
il apparaît dans « Ce qui tourne », et si l'enregistrement tourne encore quand le serveur s'arrête,
le serveur en demande la fin (g1-scan arreter), comme il arrête la simulation.

Mode robot sans répétition : avant de lancer quoi que ce soit, le serveur regarde si un câble est
branché sur l'interface du robot ($ATELIER_INTERFACE_ROBOT, eno2 par défaut), en lisant seulement
/sys/class/net/<interface>/carrier : rien n'est envoyé sur le réseau du robot.
"""
import json
import os
import signal
import subprocess
import tempfile
import time
from typing import Dict, Optional

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel, StrictBool

import atelier
from atelier.lieu import (ETATS_ACTIFS, FICHIERS_SESSION, MODES, ErreurLieu, Monde, bornes_carte,
                          charger_carte, charger_fichier, charger_info_carte, charger_itineraires, chemin_sdf,
                          chemin_session, dossier_session, etat_scan, fichiers_presents, lire_reconnaissance,
                          lire_session, lister_sessions, processus_vivant, resume_reconnaissance,
                          session_active, session_interrompue, verifier_id_session)
from atelier.lieu import changer_a_garder as _changer_a_garder

from ..communs import ErreurAtelier, dossier_du_lieu, etage_du_lieu, png_gris, rapport_du_lieu
from ..processus import CommandeAbsente, commande

routeur = APIRouter(prefix="/api/scan", tags=["scan"])

ROLE = "scan"                  # rôle du scan parmi les processus du serveur
DELAI_DEMARRER = 30.0          # s : g1-scan demarrer rend la main en moins de 3 s (contrat 9.5)
DELAI_ARRETER = 60.0           # s : g1-scan arreter attend la fermeture de l'enregistrement (30 s au plus)
DELAI_ADOPTER = 300.0          # s : l'adoption refait le masque et, avec le monde, le SDF
SANS_CACHE = {"Cache-Control": "no-store"}
INTERFACE_ROBOT = "eno2"       # port Ethernet du PC relié au robot (setup/robot.sh)
NOMS_MODES = {"robot": "robot (le vrai G1)", "simu": "simulation (robot simulé de Gazebo)"}


# ---------------------------------------------------------------- lancer g1-scan

def executer_g1_scan(arguments, delai):
    """Lance g1-scan et attend sa fin. Renvoie {code, sortie, duree_s} ; code None au-delà du délai.

    La sortie passe par un fichier temporaire, pas par un tuyau : le processus détaché de la
    session (lancé par g1-scan demarrer) peut en garder une copie, et l'on n'attend que g1-scan."""
    chemin = commande("g1-scan")
    if chemin is None:
        raise CommandeAbsente("g1-scan")
    debut = time.monotonic()
    with tempfile.TemporaryFile() as sortie:
        p = subprocess.Popen([str(chemin), *map(str, arguments)], stdout=sortie, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, start_new_session=True)
        try:
            code = p.wait(timeout=delai)
        except subprocess.TimeoutExpired:
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(p.pid, sig)
                    p.wait(timeout=3.0)
                    break
                except subprocess.TimeoutExpired:
                    continue
                except ProcessLookupError:
                    break
            code = None
        sortie.seek(0)
        texte = sortie.read().decode("utf-8", "replace")
    if code is None:
        texte += f"\n(g1-scan arrêté par l'Atelier au bout de {delai:g} s)"
    return {"code": code, "sortie": texte, "duree_s": round(time.monotonic() - debut, 2)}


def _derniere_ligne(texte):
    """Dernière ligne utile d'une sortie (le message de g1-scan qui dit quoi faire)."""
    lignes = [x.strip() for x in texte.splitlines() if x.strip()]
    return lignes[-1] if lignes else ""


async def _g1_scan(arguments, delai, quoi):
    """g1-scan au premier plan ; 503 s'il n'est pas installé, 502 s'il échoue (avec sa sortie)."""
    try:
        r = await run_in_threadpool(executer_g1_scan, arguments, delai)
    except CommandeAbsente as e:
        raise ErreurAtelier(503, f"Impossible de {quoi} : {e}. Elle est livrée par l'agent Orchestrateur "
                                 "(bin/g1-scan).") from None
    if r["code"] != 0:
        raison = _derniere_ligne(r["sortie"]) or f"code de sortie {r['code']}"
        if r["code"] is None:
            raison = f"g1-scan ne répond plus au bout de {delai:g} s"
        raise ErreurAtelier(502, f"Impossible de {quoi} : {raison.rstrip('.')}. Message complet de g1-scan "
                                 "ci-dessous.", sortie=r["sortie"])
    return r


# ---------------------------------------------------------------- lieu et session

def _id_session(session):
    try:
        return verifier_id_session(session)
    except ErreurLieu as e:
        raise ErreurAtelier(400, e.erreurs[0]) from None


def _session(dossier, session):
    """session.json d'une session du lieu (dict) ; 400 si l'id est mal formé, 404 si elle n'existe pas."""
    session = _id_session(session)
    if not dossier_session(dossier, session).is_dir():
        raise ErreurAtelier(404, f"Le scan « {session} » n'existe pas dans le lieu « {dossier.name} » : "
                                 "choisissez-en un dans la liste des scans de l'onglet Scan.")
    try:
        return lire_session(dossier, session)
    except ErreurLieu as e:
        raise ErreurAtelier(422, f"Le fichier session.json du scan « {session} » est illisible : ce scan ne "
                                 "peut plus servir, faites-en un nouveau.", e.erreurs) from None


def _etat(dossier, session=None):
    try:
        return etat_scan(dossier, session)
    except ErreurLieu as e:
        raise ErreurAtelier(422, "L'état du scan est illisible : corrigez les points ci-dessous, ou faites "
                                 "un nouveau scan.", e.erreurs) from None


def _session_visee(dossier, session):
    """Id de la session visée : celle donnée, sinon la session active du lieu, sinon la plus récente."""
    if session:
        return _session(dossier, session)["id"]
    e = _etat(dossier)
    if e["session"] is None:
        raise ErreurAtelier(404, f"Aucun scan dans le lieu « {dossier.name} » : cliquez d'abord sur « Scan ».")
    return e["session"]["id"]


def _lieux_suivis(app):
    """Lieux dont le serveur s'occupe : celui du dernier scan démarré, puis ceux consultés (onglet Scan)."""
    return getattr(app.state, "scan_lieux", [])


def _noter_lieu(app, lieu):
    """Note un lieu en tête des lieux suivis (5 au plus)."""
    app.state.scan_lieux = [lieu, *[x for x in _lieux_suivis(app) if x != lieu]][:5]


def _lieu_par_defaut(request, lieu):
    """Lieu demandé, sinon celui du dernier scan démarré par le serveur, sinon 400."""
    if lieu:
        return lieu
    dernier = getattr(request.app.state, "scan_dernier_lieu", None)
    if dernier is None:
        raise ErreurAtelier(400, "Précisez le lieu du scan, par exemple /api/scan/etat?lieu=demo : aucun scan n'a "
                                 "encore été démarré depuis l'Atelier.")
    return dernier


def scan_robot_simule_actif(app):
    """Vrai si un scan du robot simulé (mode simu, ou robot en répétition) enregistre en ce moment dans
    un lieu suivi par le serveur. Sert à la téléopération (POST /api/simulation/teleop). Une réponse
    positive est gardée 1 s (les flèches envoient une consigne toutes les 0,2 s)."""
    maintenant = time.monotonic()
    cache = getattr(app.state, "scan_teleop", None)
    if cache is not None and maintenant - cache < 1.0:
        return True
    for lieu in _lieux_suivis(app):
        try:
            s = session_active(atelier.chemin_lieu(lieu))
        except ErreurLieu:
            continue
        if s is not None and s["etat"] == "en_cours" and (s["mode"] == "simu" or s["repetition"]):
            app.state.scan_teleop = maintenant
            return True
    return False


# ---------------------------------------------------------------- scan suivi par le serveur

class SuiviScan:
    """Session de scan démarrée par ce serveur, rangée parmi ses processus (rôle « scan »).

    Elle a la même interface que processus.Processus (en_cours, arreter, etat) : le gestionnaire
    l'affiche avec la simulation et, à l'arrêt du serveur, lui demande de s'arrêter. Seul
    l'enregistrement est arrêté (g1-scan arreter) ; le traitement qui suit finit de lui-même."""

    def __init__(self, lieu, dossier, session, arguments):
        self.nom = "g1-scan"
        self.lieu = lieu
        self.dossier = dossier
        self.session = session
        self.arguments = [str(a) for a in arguments]
        self.debut = time.time()
        self.arret_demande = False
        self._cache = None             # (session.json, instant de lecture)

    def _lire(self, frais=False):
        maintenant = time.monotonic()
        if frais or self._cache is None or maintenant - self._cache[1] > 1.0:
            try:
                s = lire_session(self.dossier, self.session)
            except ErreurLieu:
                s = None
            self._cache = (s, maintenant)
        return self._cache[0]

    @property
    def en_cours(self):
        s = self._lire()
        return bool(s and s["etat"] in ETATS_ACTIFS and not session_interrompue(s))

    def arreter(self, attente_sigint=None):
        """Demande la fin de l'enregistrement s'il tourne encore (g1-scan arreter). Sans effet sinon."""
        s = self._lire(frais=True)
        if s is None or s["etat"] != "en_cours" or session_interrompue(s):
            return
        self.arret_demande = True
        try:
            executer_g1_scan(["arreter", "--lieu", self.dossier, "--session", self.session], DELAI_ARRETER)
        except CommandeAbsente:
            pass

    def etat(self):
        s = self._lire()
        code = None
        if s is not None and s["etat"] not in ETATS_ACTIFS:
            code = 0 if s["etat"] == "termine" else 1
        p = (s or {}).get("processus") or {}
        return {"commande": " ".join([self.nom, *self.arguments]), "en_cours": self.en_cours,
                "pid": p.get("pid"), "code": code, "arret_demande": self.arret_demande, "debut": self.debut,
                "duree_s": round(time.time() - self.debut, 1), "journal": (s or {}).get("journal"),
                "dernieres_lignes": [s["message"]] if s else ["session.json illisible"],
                "lieu": self.lieu, "etage": (s or {}).get("etage"), "session": self.session,
                "etat_scan": (s or {}).get("etat"), "vivant": processus_vivant(s) if s else None}


def _suivre(etat, suivi):
    with etat.gestionnaire.verrou:
        etat.gestionnaire.processus[ROLE] = suivi


# ---------------------------------------------------------------- vérifications avant le scan

def interface_robot():
    """Nom de l'interface réseau du PC reliée au robot : $ATELIER_INTERFACE_ROBOT, sinon eno2."""
    return os.environ.get("ATELIER_INTERFACE_ROBOT") or INTERFACE_ROBOT


def cable_branche(interface):
    """Vrai si un câble est branché sur l'interface (lecture de /sys/class/net, sans rien envoyer)."""
    try:
        with open(f"/sys/class/net/{interface}/carrier", encoding="ascii") as f:
            return f.read().strip() == "1"
    except (OSError, ValueError):
        return False        # interface absente ou désactivée


def _couloirs_de_l_etage(dossier, etage):
    try:
        itin = charger_itineraires(dossier)
    except ErreurLieu:
        return 0
    return sum(1 for a, b in itin.couloirs if a in itin.noeuds and b in itin.noeuds
               and itin.noeuds[a].etage == etage and itin.noeuds[b].etage == etage)


class DemandeDemarrer(BaseModel):
    lieu: str
    etage: str
    mode: str
    repetition: StrictBool = False
    explorer: StrictBool = False
    nom: Optional[str] = None


class DemandeArreter(BaseModel):
    lieu: str
    session: Optional[str] = None


class DemandeGarder(BaseModel):
    a_garder: Dict[str, StrictBool]


class DemandeAdopter(BaseModel):
    monde: StrictBool = False


@routeur.post("/demarrer")
async def demarrer(demande: DemandeDemarrer, request: Request):
    etat = request.app.state.atelier
    dossier = dossier_du_lieu(demande.lieu)
    etage_du_lieu(dossier, demande.etage)
    mode = demande.mode.strip()
    if mode not in MODES:
        raise ErreurAtelier(400, f"Mode de scan « {mode} » inconnu : choisissez « robot » (le vrai G1) ou « simu » "
                                 "(le robot simulé de Gazebo).")
    if demande.repetition and mode != "robot":
        raise ErreurAtelier(400, "La répétition sans robot ne s'emploie qu'en mode robot : elle imite le vrai robot "
                                 "avec la simulation. En mode simulation, décochez « Répétition sans robot ».")
    simule = mode == "simu" or demande.repetition
    if demande.explorer and not simule:
        raise ErreurAtelier(400, "L'exploration automatique n'existe qu'avec le robot simulé (mode simulation, ou "
                                 "répétition sans robot) : le vrai robot se conduit à la télécommande.")
    nom = (demande.nom or "").strip() or None
    if nom is not None and len(nom) > 100:
        raise ErreurAtelier(400, "Le nom du scan est trop long : 100 caractères au plus.")
    # la simulation de l'Atelier tourne-t-elle ailleurs ?
    if etat.simulation_en_cours():
        s = etat.simulation
        if (s["lieu"], s["etage"]) != (demande.lieu, demande.etage):
            raise ErreurAtelier(409, f"La simulation de l'Atelier tourne sur un autre lieu ou étage (lieu « {s['lieu']} », "
                                     f"étage « {s['etage']} ») : arrêtez la simulation (onglet Simulation), puis "
                                     "relancez le scan.")
    # un seul scan actif par lieu
    try:
        active = session_active(dossier)
    except ErreurLieu:
        active = None
    if active is not None:
        raise ErreurAtelier(409, f"Un scan est déjà en cours dans ce lieu (« {active['nom']} », état "
                                 f"{active['etat']}) : cliquez sur « Fin », ou attendez la fin de son traitement.")
    if simule and not chemin_sdf(dossier, demande.etage).is_file():
        raise ErreurAtelier(409, "Le monde Gazebo de cet étage n'existe pas encore : le robot simulé n'a rien à "
                                 "scanner. Dans l'onglet Carte, cliquez sur « Fabriquer la carte », puis relancez "
                                 "le scan.")
    if demande.explorer and _couloirs_de_l_etage(dossier, demande.etage) == 0:
        raise ErreurAtelier(409, "L'exploration automatique suit les couloirs de l'onglet Itinéraires, et cet étage "
                                 "n'en a aucun : reliez au moins deux nœuds, ou décochez « Exploration "
                                 "automatique » et pilotez le robot avec les flèches.")
    if mode == "robot" and not demande.repetition:
        interface = interface_robot()
        if not cable_branche(interface):
            raise ErreurAtelier(409, f"Robot non détecté : branchez le câble Ethernet entre le PC et le robot (prise "
                                     f"{interface}), allumez le robot, puis dans un terminal : source "
                                     "~/robot-g1/setup/robot.sh. Pour essayer sans robot, cochez « Répétition "
                                     "sans robot ».")
    if commande("g1-scan") is None:
        raise ErreurAtelier(503, "Impossible de démarrer le scan : la commande g1-scan n'est pas encore installée "
                                 f"dans {atelier.RACINE / 'bin'} (agent Orchestrateur).")

    arguments = ["demarrer", "--lieu", dossier, "--etage", demande.etage, "--mode", mode]
    if demande.repetition:
        arguments.append("--repetition")
    if demande.explorer:
        arguments.append("--explorer")
    if nom:
        arguments += ["--nom", nom]
    r = await _g1_scan(arguments, DELAI_DEMARRER, "démarrer le scan")
    # session créée : « session: <id> » en dernière ligne (contrat 9.5), sinon la session active
    session = None
    for ligne in reversed(r["sortie"].splitlines()):
        if ligne.strip().startswith("session:"):
            session = ligne.split(":", 1)[1].strip()
            break
    if session is None:
        active = session_active(dossier)
        session = active["id"] if active else None
    if session is None:
        raise ErreurAtelier(502, "g1-scan a rendu la main sans créer de session : lisez son message ci-dessous.",
                            sortie=r["sortie"])
    _id_session(session)
    _suivre(etat, SuiviScan(demande.lieu, dossier, session, arguments))
    request.app.state.scan_dernier_lieu = demande.lieu
    request.app.state.scan_teleop = None
    _noter_lieu(request.app, demande.lieu)
    reponse = _etat(dossier, session)
    reponse["sortie"] = r["sortie"]
    return reponse


@routeur.post("/arreter")
async def arreter(demande: DemandeArreter, request: Request):
    dossier = dossier_du_lieu(demande.lieu)
    session = await run_in_threadpool(_session_visee, dossier, demande.session)
    suivi = request.app.state.atelier.gestionnaire.processus.get(ROLE)
    if isinstance(suivi, SuiviScan) and suivi.session == session and suivi.dossier == dossier:
        suivi.arret_demande = True
    r = await _g1_scan(["arreter", "--lieu", dossier, "--session", session], DELAI_ARRETER, "arrêter le scan")
    request.app.state.scan_teleop = None
    reponse = _etat(dossier, session)
    reponse["sortie"] = r["sortie"]
    return reponse


@routeur.get("/etat")
def lire_etat(request: Request, lieu: Optional[str] = None, session: Optional[str] = None):
    lieu = _lieu_par_defaut(request, lieu)
    dossier = dossier_du_lieu(lieu)
    _noter_lieu(request.app, lieu)
    if session:
        _session(dossier, session)
    return _etat(dossier, session or None)


def _fichier_session(request, lieu, session, quoi, absent):
    """Octets d'un fichier de la session visée ; 404 avec le message absent s'il n'existe pas encore."""
    lieu = _lieu_par_defaut(request, lieu)
    dossier = dossier_du_lieu(lieu)
    session = _session_visee(dossier, session)
    chemin = chemin_session(dossier, session, quoi)
    try:
        # lu en entier : le processus du scan remplace ces fichiers par renommage toutes les 2 s
        return chemin.read_bytes()
    except FileNotFoundError:
        raise ErreurAtelier(404, absent) from None


ABSENT_APERCU = "L'aperçu de ce scan n'est pas encore prêt : il apparaît quelques secondes après le début du scan."


@routeur.get("/apercu.png")
def apercu_png(request: Request, lieu: Optional[str] = None, session: Optional[str] = None):
    octets = _fichier_session(request, lieu, session, "apercu_png", ABSENT_APERCU)
    return Response(octets, media_type="image/png", headers=SANS_CACHE)


@routeur.get("/apercu.json")
def apercu_json(request: Request, lieu: Optional[str] = None, session: Optional[str] = None):
    octets = _fichier_session(request, lieu, session, "apercu_json", ABSENT_APERCU)
    return Response(octets, media_type="application/json", headers=SANS_CACHE)


@routeur.get("/sessions")
def sessions(lieu: str):
    dossier = dossier_du_lieu(lieu)
    liste = lister_sessions(dossier, avec_illisibles=True)
    for s in liste:
        s["fichiers"] = fichiers_presents(dossier, s["id"])
        if not s.get("illisible"):
            s["interrompue"] = session_interrompue(s)
    return liste


# ---------------------------------------------------------------- résultat d'une session

def _session_finie(s, quoi):
    if s["etat"] in ETATS_ACTIFS:
        raise ErreurAtelier(409, f"Le scan « {s['nom']} » n'est pas fini (état {s['etat']}) : attendez la fin du "
                                 f"traitement pour {quoi}.")


@routeur.get("/sessions/{session}/reconnaissance")
def lire_reconnaissance_session(lieu: str, session: str):
    dossier = dossier_du_lieu(lieu)
    s = _session(dossier, session)
    if not chemin_session(dossier, s["id"], "reconnaissance").is_file():
        if s["etat"] in ETATS_ACTIFS:
            detail = "La reconnaissance de ce scan n'est pas encore faite : attendez la fin du traitement."
        else:
            detail = ("Ce scan n'a pas de reconnaissance (elle a échoué ou n'a pas été faite) : sa carte 2D peut "
                      "quand même servir (« Utiliser cette carte pour l'étage »).")
        raise ErreurAtelier(404, detail)
    try:
        donnees = lire_reconnaissance(dossier_session(dossier, s["id"]))
    except ErreurLieu as e:
        raise ErreurAtelier(422, "Le fichier reconnaissance.yaml de ce scan est invalide : corrigez les points "
                                 "ci-dessous, ou refaites le traitement (g1-scan traiter).", e.erreurs) from None
    return {"reconnaissance": donnees, "resume": resume_reconnaissance(donnees)}


@routeur.put("/sessions/{session}/reconnaissance")
def changer_a_garder(lieu: str, session: str, demande: DemandeGarder):
    dossier = dossier_du_lieu(lieu)
    s = _session(dossier, session)
    _session_finie(s, "choisir les éléments à garder")
    actuel = lire_reconnaissance_session(lieu, s["id"])["reconnaissance"]
    connus = {e["id"] for cle in ("murs", "passages", "objets") for e in actuel[cle]}
    inconnus = sorted(set(demande.a_garder) - connus)
    if inconnus:
        raise ErreurAtelier(400, f"Élément(s) inconnu(s) dans la reconnaissance de ce scan : {', '.join(inconnus)}. "
                                 "Rechargez la page : la reconnaissance a peut-être été refaite.")
    try:
        resultat = _changer_a_garder(dossier, s["id"], dict(demande.a_garder))
    except ErreurLieu as e:
        raise ErreurAtelier(409, "Les choix n'ont pas été enregistrés : lisez les points ci-dessous.", e.erreurs) from None
    return resultat


def _carte_session(dossier, s):
    chemin = chemin_session(dossier, s["id"], "carte")
    if not chemin.is_file():
        raise ErreurAtelier(404, "La carte 2D de ce scan n'est pas encore fabriquée"
                                 + (" : attendez la fin du traitement." if s["etat"] in ETATS_ACTIFS else
                                    " : le traitement a échoué, faites un nouveau scan."))
    return chemin


@routeur.get("/sessions/{session}/carte.png")
def carte_png(lieu: str, session: str):
    dossier = dossier_du_lieu(lieu)
    chemin = _carte_session(dossier, _session(dossier, session))
    try:
        _, image = charger_carte(chemin)
    except ErreurLieu as e:
        raise ErreurAtelier(422, "La carte de ce scan est illisible : refaites le traitement (g1-scan traiter).",
                            e.erreurs) from None
    return Response(png_gris(image), media_type="image/png", headers=SANS_CACHE)


@routeur.get("/sessions/{session}/carte.yaml")
def carte_yaml(lieu: str, session: str):
    dossier = dossier_du_lieu(lieu)
    chemin = _carte_session(dossier, _session(dossier, session))
    try:
        info = charger_info_carte(chemin)
    except ErreurLieu as e:
        raise ErreurAtelier(422, "Le fichier carte.yaml de ce scan est invalide : refaites le traitement "
                                 "(g1-scan traiter).", e.erreurs) from None
    xmin, ymin, xmax, ymax = bornes_carte(info)
    return dict(info.vers_dict(), largeur=info.largeur, hauteur=info.hauteur,
                bornes={"xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax}, modifiee=chemin.stat().st_mtime)


@routeur.get("/sessions/{session}/monde")
def monde_session(lieu: str, session: str):
    dossier = dossier_du_lieu(lieu)
    s = _session(dossier, session)
    chemin = chemin_session(dossier, s["id"], "monde")
    if not chemin.is_file():
        raise ErreurAtelier(404, "Ce scan n'a pas encore de monde : il est tiré de la reconnaissance, à la fin du "
                                 "traitement.")
    try:
        return Monde.depuis_dict(charger_fichier(chemin, "monde", FICHIERS_SESSION["monde"])).vers_dict()
    except ErreurLieu as e:
        raise ErreurAtelier(422, "Le monde tiré de ce scan est invalide : cochez ou décochez un élément pour le "
                                 "refaire, ou refaites le traitement.", e.erreurs) from None


@routeur.get("/sessions/{session}/rapport")
def rapport_session(lieu: str, session: str):
    """Ajout au contrat : rapport.json du traitement (étapes, comparaison, avertissements)."""
    dossier = dossier_du_lieu(lieu)
    s = _session(dossier, session)
    chemin = chemin_session(dossier, s["id"], "rapport")
    try:
        return json.loads(chemin.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ErreurAtelier(404, "Ce scan n'a pas encore de rapport : il est écrit à la fin du traitement.") from None
    except (UnicodeDecodeError, ValueError):
        raise ErreurAtelier(422, "Le rapport de ce scan est illisible : refaites le traitement.") from None


@routeur.post("/sessions/{session}/adopter")
async def adopter(lieu: str, session: str, demande: DemandeAdopter, request: Request):
    dossier = dossier_du_lieu(lieu)
    s = _session(dossier, session)
    if s["etat"] != "termine":
        conseil = ("attendez la fin du traitement" if s["etat"] in ETATS_ACTIFS
                   else "il a échoué : faites un nouveau scan")
        raise ErreurAtelier(409, f"Le scan « {s['nom']} » ne peut pas être adopté (état {s['etat']}) : {conseil}.")
    if demande.monde and not chemin_session(dossier, s["id"], "monde").is_file():
        raise ErreurAtelier(409, "Ce scan n'a pas de monde (la reconnaissance a échoué) : utilisez seulement sa "
                                 "carte (« Utiliser cette carte pour l'étage »).")
    arguments = ["adopter", "--lieu", dossier, "--session", s["id"]]
    if demande.monde:
        arguments.append("--monde")
    r = await _g1_scan(arguments, DELAI_ADOPTER, "adopter le scan")
    avertissements = []
    etat = request.app.state.atelier
    if etat.simulation_en_cours() and (etat.simulation["lieu"], etat.simulation["etage"]) == (lieu, s["etage"]):
        avertissements.append("La simulation de l'Atelier tourne encore sur l'ancienne carte : arrêtez-la puis "
                              "relancez-la pour essayer le nouvel étage.")
    if s["mode"] == "robot":
        avertissements.append("Ce scan vient du vrai robot : son repère n'est pas celui du monde dessiné. Replacez "
                              "les salles, les itinéraires et les zones sur la nouvelle carte.")
    return {"adopte": True, "monde": demande.monde, "session": s["id"], "etage": s["etage"], "sortie": r["sortie"],
            "avertissements": avertissements, "rapport": rapport_du_lieu(dossier)}
