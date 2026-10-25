"""Sessions de scan intégré (section 9 du plan) : dossiers LIEU/scans/<session>/.

Ce module est le seul qui lit et écrit session.json et reconnaissance.yaml : g1-scan (agent
Orchestrateur), la reconnaissance (agent Reconnaissance) et le serveur de l'Atelier (agent
Interface) passent tous par lui. Il ne dépend pas de ROS.

Contenu d'une session (FICHIERS_SESSION) :

    scans/2026-10-25_17h42/
    ├── enregistrement/          ros2 bag du scan (ignoré par Git)
    ├── session.json             état (schéma session_scan) : mode, étape, progression, message...
    ├── apercu.png, apercu.json  vue de dessus en direct, et points décimés + trajectoire
    ├── nuage.pcd                nuage 3D assemblé (atelier.scan.carte3d)
    ├── carte.pgm, carte.yaml    carte 2D Nav2 (atelier.scan.carte2d)
    ├── reconnaissance.yaml      murs, passages et objets reconnus (schéma reconnaissance)
    ├── monde_scan.monde.yaml    monde tiré des éléments gardés (schéma monde)
    ├── rapport.json             bilan du traitement
    └── monde_remplace.monde.yaml  ancien monde de l'étage, après g1-scan adopter --monde

Écritures atomiques (fichier temporaire, puis renommage). Les mises à jour de session.json par
plusieurs processus (processus du scan, g1-scan arreter, serveur) passent par maj_session, qui
prend un verrou (fcntl) sur scans/<session>/.session.lock.
"""
import contextlib
import fcntl
import json
import math
import os
import re
import socket
import time
from datetime import datetime
from pathlib import Path

import numpy as np

from .conversions import centres_pixels
from .fichiers import ErreurLieu, charger_fiche, dossier_lieu, ecrire_atomique, ecrire_yaml, lire_yaml
from .modeles import CATEGORIES_HORS_CARTE, Emprise, Monde, Mur, Objet, Pose
from .validation import valider_donnees

VERSION = 1
DOSSIER_SCANS = "scans"
FICHIERS_SESSION = {
    "enregistrement": "enregistrement",
    "session": "session.json",
    "apercu_png": "apercu.png",
    "apercu_json": "apercu.json",
    "nuage": "nuage.pcd",
    "carte": "carte.yaml",
    "carte_image": "carte.pgm",
    "reconnaissance": "reconnaissance.yaml",
    "monde": "monde_scan.monde.yaml",
    "rapport": "rapport.json",
    "monde_remplace": "monde_remplace.monde.yaml",     # ancien monde de l'étage, gardé par g1-scan adopter --monde
}
MOTIF_SESSION = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{2}h[0-9]{2}(-[0-9]{1,3})?$")

MODES = ("robot", "simu")
ETATS = ("en_cours", "arret_en_cours", "traitement", "termine", "echec")
ETATS_ACTIFS = ("en_cours", "arret_en_cours", "traitement")
ETAPES = ("preparation", "enregistrement", "arret", "carte_3d", "carte_2d", "reconnaissance", "monde", "fini")
ETAPES_TRAITEMENT = ("carte_3d", "carte_2d", "reconnaissance", "monde")
# Progression (0 à 100) au début et à la fin de chaque étape : la barre de l'interface
PLAGES_PROGRESSION = {"preparation": (0, 0), "enregistrement": (0, 0), "arret": (5, 5),
                      "carte_3d": (10, 50), "carte_2d": (50, 65), "reconnaissance": (65, 90),
                      "monde": (90, 99), "fini": (100, 100)}

# Sujets enregistrés selon le mode (le mode robot en répétition enregistre les mêmes que le robot)
SUJETS_PAR_MODE = {"robot": {"nuage": "/unitree/slam_mapping/points", "odom": "/unitree/slam_mapping/odom"},
                   "simu": {"nuage": "/points", "odom": "/odom"}}
SUJETS_AUTRES = ("/tf_static",)

# Aperçu en direct
APERCU_POINTS_MAX = 20000         # points au plus dans apercu.json
APERCU_TRAJECTOIRE_MAX = 5000     # poses au plus dans apercu.json
PERIODE_APERCU = 2.0              # s : apercu.png et apercu.json sont réécrits au moins toutes les 2 s
PERIODE_SESSION = 5.0             # s : session.json est réécrit au moins toutes les 5 s pendant l'enregistrement
SILENCE_MAX = 30.0                # s : une session active sans processus connu et muette depuis 30 s est interrompue

OCCUPE, LIBRE = 0, 254


# ---------------------------------------------------------------- petits outils

def instant(quand=None):
    """Date et heure ISO 8601 locale, à la seconde, avec le décalage : 2026-10-25T17:42:05+02:00."""
    quand = quand or datetime.now()
    return quand.astimezone().replace(microsecond=0).isoformat()


def _lire_instant(texte):
    try:
        return datetime.fromisoformat(texte)
    except (TypeError, ValueError):
        return None


def progression_etape(etape, fraction=0.0):
    """Progression (entier de 0 à 100) d'une étape avancée de fraction (0 à 1) : carte_3d à moitié → 30."""
    if etape not in PLAGES_PROGRESSION:
        raise ValueError(f"étape inconnue : {etape} (attendu : {', '.join(ETAPES)})")
    debut, fin = PLAGES_PROGRESSION[etape]
    fraction = min(1.0, max(0.0, float(fraction)))
    return int(round(debut + (fin - debut) * fraction))


def a_garder_par_defaut(categorie):
    """Valeur de a_garder d'un élément reconnu : faux pour une personne, vrai sinon."""
    return categorie not in CATEGORIES_HORS_CARTE


def _r(v, decimales=3):
    """Nombre arrondi au millimètre, pour des fichiers lisibles."""
    return round(float(v), decimales)


# ---------------------------------------------------------------- chemins

def dossier_scans(lieu):
    """LIEU/scans : les sessions de scan du lieu."""
    return dossier_lieu(lieu) / DOSSIER_SCANS


def verifier_id_session(session):
    """L'identifiant de session tel quel, ou ErreurLieu s'il n'a pas la forme AAAA-MM-JJ_HHhMM."""
    texte = str(session).strip()
    if not MOTIF_SESSION.match(texte):
        raise ErreurLieu(f"« {texte} » n'est pas un identifiant de session de scan : il a la forme "
                         "AAAA-MM-JJ_HHhMM, ex. 2026-10-25_17h42 (voir g1-scan etat --lieu L)")
    return texte


def dossier_session(lieu, session):
    """LIEU/scans/<session>. ErreurLieu si l'identifiant est mal formé (le dossier peut ne pas exister)."""
    return dossier_scans(lieu) / verifier_id_session(session)


def chemin_session(lieu, session, quoi="session"):
    """Chemin d'un fichier de la session : quoi est une clé de FICHIERS_SESSION (session, nuage, carte...)."""
    if quoi not in FICHIERS_SESSION:
        raise ValueError(f"fichier de session inconnu : {quoi} (attendu : {', '.join(FICHIERS_SESSION)})")
    return dossier_session(lieu, session) / FICHIERS_SESSION[quoi]


def _cle_tri(identifiant):
    """Clé de tri chronologique : 2026-10-25_17h42 < 2026-10-25_17h42-2 < 2026-10-25_17h42-10."""
    base, suffixe = identifiant.rsplit("-", 1) if identifiant.count("-") == 3 else (identifiant, "")
    return (base, int(suffixe) if suffixe else 1)


def nouvel_id_session(lieu, quand=None):
    """Identifiant libre pour une session qui commence à quand (défaut : maintenant) :
    2026-10-25_17h42, ou 2026-10-25_17h42-2 si la minute est déjà prise."""
    quand = quand or datetime.now()
    base = quand.strftime("%Y-%m-%d_%Hh%M")
    racine = dossier_scans(lieu)
    identifiant, n = base, 1
    while (racine / identifiant).exists():
        n += 1
        identifiant = f"{base}-{n}"
    return identifiant


# ---------------------------------------------------------------- session.json

def _nom_affiche(session):
    return f"scans/{session}/session.json"


def _valider_session(donnees):
    nom = _nom_affiche(donnees.get("id", "?") if isinstance(donnees, dict) else "?")
    erreurs = valider_donnees("session_scan", donnees, nom)
    if erreurs:
        raise ErreurLieu(erreurs)


def _ecrire_json(chemin, donnees):
    ecrire_atomique(chemin, json.dumps(donnees, ensure_ascii=False, indent=2) + "\n")


@contextlib.contextmanager
def verrou_session(lieu, session):
    """Verrou exclusif (entre processus) sur la session, le temps d'un lire-modifier-écrire."""
    dossier = dossier_session(lieu, session)
    if not dossier.is_dir():
        raise ErreurLieu(f"la session de scan « {session} » n'existe pas dans {dossier.parent}")
    with open(dossier / ".session.lock", "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def lire_session(lieu, session):
    """session.json d'une session → dict validé. ErreurLieu si elle n'existe pas ou est invalide."""
    chemin = chemin_session(lieu, session)
    nom = _nom_affiche(session)
    if not chemin.is_file():
        raise ErreurLieu(f"{nom} : la session de scan « {session} » n'existe pas ({chemin.parent}) ; "
                         "liste des sessions : g1-scan etat --lieu L")
    try:
        donnees = json.loads(chemin.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ErreurLieu(f"{nom} : JSON illisible ({e})") from None
    erreurs = valider_donnees("session_scan", donnees, nom)
    if erreurs:
        raise ErreurLieu(erreurs)
    return donnees


def ecrire_session(lieu, donnees):
    """Valide puis écrit session.json (atomique), après avoir mis maj à l'heure. Renvoie les données.
    Pour modifier quelques champs d'une session existante, préférer maj_session (verrou)."""
    donnees = dict(donnees)
    donnees["maj"] = instant()
    _valider_session(donnees)
    _ecrire_json(chemin_session(lieu, donnees["id"]), donnees)
    return donnees


def maj_session(lieu, session, **champs):
    """Modifie des champs de session.json, sous verrou, puis l'écrit. Renvoie la session à jour.

    statistiques est fusionné avec l'existant (on peut ne donner que points=...) ; si etape change
    sans progression, la progression devient celle du début de l'étape (PLAGES_PROGRESSION).
    ErreurLieu (et rien d'écrit) si le résultat est invalide.
    """
    with verrou_session(lieu, session):
        donnees = lire_session(lieu, session)
        if "statistiques" in champs:
            champs["statistiques"] = {**donnees["statistiques"], **champs["statistiques"]}
        if "etape" in champs and "progression" not in champs and champs["etape"] != donnees["etape"]:
            champs["progression"] = progression_etape(champs["etape"])
        donnees.update(champs)
        return ecrire_session(lieu, donnees)


def creer_session(lieu, etage, mode, nom=None, repetition=False, explorer=False, quand=None,
                  refuser_si_active=True):
    """Crée le dossier scans/<session>/ et son session.json (etat en_cours, etape preparation).

    mode : robot (vrai G1, ou répétition sans robot si repetition) ou simu (robot proxy de Gazebo).
    explorer : le robot simulé parcourt seul les couloirs (simu, ou robot en répétition).
    refuser_si_active : ErreurLieu si une autre session du lieu est encore active (et non interrompue).
    Renvoie la session (dict). Ne lance rien : c'est le travail de g1-scan demarrer.
    """
    fiche = charger_fiche(lieu)
    dossier = Path(fiche.dossier)
    if mode not in MODES:
        raise ErreurLieu(f"mode de scan « {mode} » inconnu : robot (le vrai G1) ou simu (robot simulé)")
    if fiche.etage(etage) is None:
        raise ErreurLieu(f"le lieu {dossier.name} n'a pas d'étage « {etage} » "
                         f"(étages : {', '.join(e.id for e in fiche.etages)})")
    if repetition and mode != "robot":
        raise ErreurLieu("la répétition (--repetition) ne s'emploie qu'en mode robot : elle imite le vrai "
                         "robot avec la simulation")
    if explorer and not (mode == "simu" or repetition):
        raise ErreurLieu("l'exploration automatique (--explorer) n'existe qu'avec le robot simulé (mode simu, "
                         "ou robot en répétition) : conduisez le vrai robot à la télécommande")
    if refuser_si_active:
        active = session_active(dossier)
        if active is not None:
            raise ErreurLieu(f"un scan est déjà en cours dans le lieu {dossier.name} (session {active['id']}, "
                             f"état {active['etat']}) : arrêtez-le d'abord avec g1-scan arreter --lieu "
                             f"{dossier.name}")
    quand = quand or datetime.now()
    racine = dossier / DOSSIER_SCANS
    racine.mkdir(parents=True, exist_ok=True)
    identifiant = nouvel_id_session(dossier, quand)
    while True:                       # mkdir exclusif : deux g1-scan en même temps n'ont pas le même dossier
        try:
            (racine / identifiant).mkdir()
            break
        except FileExistsError:
            identifiant = nouvel_id_session(dossier, quand)
    sujets = dict(SUJETS_PAR_MODE[mode], autres=list(SUJETS_AUTRES))
    donnees = {
        "version": VERSION, "id": identifiant, "lieu": dossier.name, "etage": etage,
        "nom": nom or f"Scan {etage} du {quand:%d/%m/%Y} à {quand:%Hh%M}",
        "mode": mode, "repetition": bool(repetition), "explorer": bool(explorer),
        "debut": instant(quand), "fin": None, "maj": instant(),
        "etat": "en_cours", "etape": "preparation", "progression": 0,
        "message": "Préparation du scan…", "sujets": sujets,
        "statistiques": {"duree_s": 0.0, "points": 0, "distance_m": 0.0, "nuages": 0},
        "processus": None, "journal": None,
        "carte_unitree": f"{etage}_{identifiant}.pcd" if mode == "robot" else None,
        "adoption": None,
    }
    try:
        return ecrire_session(dossier, donnees)
    except BaseException:
        (racine / identifiant).rmdir()
        raise


def lister_sessions(lieu, avec_illisibles=False):
    """Sessions du lieu, de la plus récente à la plus ancienne : session.json de chacune, plus
    « dossier ». avec_illisibles : ajoute aussi {id, dossier, illisible: True, erreurs} pour les
    dossiers dont session.json manque ou est invalide."""
    racine = dossier_scans(lieu)
    if not racine.is_dir():
        return []
    resultat = []
    noms = sorted((d.name for d in racine.iterdir() if d.is_dir() and MOTIF_SESSION.match(d.name)),
                  key=_cle_tri, reverse=True)
    for nom in noms:
        try:
            s = lire_session(lieu, nom)
        except ErreurLieu as e:
            if avec_illisibles:
                resultat.append({"id": nom, "dossier": str(racine / nom), "illisible": True, "erreurs": e.erreurs})
            continue
        s["dossier"] = str(racine / nom)
        resultat.append(s)
    return resultat


# ---------------------------------------------------------------- processus de la session

def _debut_processus(pid):
    """Instant de démarrage du processus (champ 22 de /proc/<pid>/stat), ou None s'il n'existe pas."""
    try:
        texte = Path(f"/proc/{int(pid)}/stat").read_text()
    except (OSError, ValueError):
        return None
    champs = texte[texte.rfind(")") + 2:].split()
    if not champs or champs[0] == "Z":          # zombie : fini
        return None
    return int(champs[19])


def infos_processus(pid=None):
    """{pid, debut, hote} du processus pid (défaut : celui-ci), pour le champ processus de session.json."""
    pid = int(pid or os.getpid())
    debut = _debut_processus(pid)
    if debut is None:
        raise ErreurLieu(f"le processus {pid} n'existe pas")
    return {"pid": pid, "debut": debut, "hote": socket.gethostname()}


def processus_vivant(session):
    """True si le processus noté dans la session tourne encore, False s'il est fini, None si on ne
    peut pas le savoir (pas de processus noté, ou session lancée sur une autre machine)."""
    p = session.get("processus")
    if not p or p.get("hote") != socket.gethostname():
        return None
    return _debut_processus(p["pid"]) == p["debut"]


def session_interrompue(session):
    """Vrai si la session est active (en_cours, arret_en_cours, traitement) mais que son processus
    est mort, ou, sans processus connu, si elle n'a rien écrit depuis SILENCE_MAX secondes."""
    if session["etat"] not in ETATS_ACTIFS:
        return False
    vivant = processus_vivant(session)
    if vivant is not None:
        return not vivant
    maj = _lire_instant(session["maj"])
    return maj is None or time.time() - maj.timestamp() > SILENCE_MAX


def session_active(lieu):
    """La session active (et non interrompue) la plus récente du lieu, ou None."""
    return next((s for s in lister_sessions(lieu) if s["etat"] in ETATS_ACTIFS and not session_interrompue(s)),
                None)


def derniere_session(lieu):
    """La session la plus récente du lieu, ou None."""
    sessions = lister_sessions(lieu)
    return sessions[0] if sessions else None


def fichiers_presents(lieu, session):
    """Fichiers déjà écrits de la session : {enregistrement, apercu_png, apercu_json, nuage, carte,
    reconnaissance, monde, rapport} → booléens."""
    d = dossier_session(lieu, session)
    return {"enregistrement": (d / FICHIERS_SESSION["enregistrement"] / "metadata.yaml").is_file(),
            "apercu_png": (d / FICHIERS_SESSION["apercu_png"]).is_file(),
            "apercu_json": (d / FICHIERS_SESSION["apercu_json"]).is_file(),
            "nuage": (d / FICHIERS_SESSION["nuage"]).is_file(),
            "carte": (d / FICHIERS_SESSION["carte"]).is_file() and (d / FICHIERS_SESSION["carte_image"]).is_file(),
            "reconnaissance": (d / FICHIERS_SESSION["reconnaissance"]).is_file(),
            "monde": (d / FICHIERS_SESSION["monde"]).is_file(),
            "rapport": (d / FICHIERS_SESSION["rapport"]).is_file()}


def etat_scan(lieu, session=None):
    """État du scan d'un lieu : la sortie de « g1-scan etat --json » et de GET /api/scan/etat.

    session : id d'une session ; par défaut la session active, sinon la plus récente.
    Renvoie {version, lieu, dossier_lieu, sessions (nombre), actif, session} ; session vaut None
    s'il n'y en a aucune, sinon le contenu de session.json plus dossier, vivant (processus_vivant),
    interrompue (session_interrompue) et fichiers (fichiers_presents).
    """
    dossier = dossier_lieu(lieu)
    if not (dossier / "lieu.yaml").is_file():
        raise ErreurLieu(f"le lieu {dossier} n'existe pas (pas de lieu.yaml)")
    sessions = lister_sessions(dossier)
    if session is not None:
        choisie = lire_session(dossier, session)
        choisie["dossier"] = str(dossier_session(dossier, session))
    else:
        choisie = next((s for s in sessions if s["etat"] in ETATS_ACTIFS and not session_interrompue(s)),
                       sessions[0] if sessions else None)
    resultat = {"version": VERSION, "lieu": dossier.name, "dossier_lieu": str(dossier),
                "sessions": len(sessions), "actif": False, "session": None}
    if choisie is not None:
        s = dict(choisie)
        s["vivant"] = processus_vivant(s)
        s["interrompue"] = session_interrompue(s)
        s["fichiers"] = fichiers_presents(dossier, s["id"])
        resultat["session"] = s
        resultat["actif"] = s["etat"] in ETATS_ACTIFS and not s["interrompue"]
    return resultat


# ---------------------------------------------------------------- reconnaissance.yaml

ENTETE_RECONNAISSANCE = ("Murs, passages et objets reconnus dans le scan. Format : "
                         "atelier/lieu/schemas/reconnaissance.schema.json. a_garder : dans le monde tiré du scan.")


def nouvelle_reconnaissance(etage, emprise, depart_robot, session=None, sol=None, parametres=None):
    """Squelette de reconnaissance.yaml, sans élément. emprise : (xmin, ymin, xmax, ymax) ;
    depart_robot : (x, y, theta)."""
    xmin, ymin, xmax, ymax = (float(v) for v in emprise)
    x, y, theta = (float(v) for v in depart_robot)
    donnees = {"version": VERSION, "session": session, "etage": etage,
               "emprise": {"min": [xmin, ymin], "max": [xmax, ymax]},
               "depart_robot": {"x": x, "y": y, "theta": theta}}
    if sol is not None:
        donnees["sol"] = float(sol)
    if parametres is not None:
        donnees["parametres"] = dict(parametres)
    donnees.update({"murs": [], "passages": [], "objets": []})
    return donnees


def _nom_reconnaissance(chemin):
    chemin = Path(chemin)
    return f"scans/{chemin.parent.name}/{chemin.name}" if MOTIF_SESSION.match(chemin.parent.name) else chemin.name


def valider_reconnaissance(donnees, fichier="reconnaissance.yaml"):
    """Messages d'erreur (schéma et règles), liste vide si tout va bien."""
    return valider_donnees("reconnaissance", donnees, fichier)


def lire_reconnaissance(chemin):
    """reconnaissance.yaml (chemin du fichier, ou dossier de la session) → dict validé, ou ErreurLieu."""
    chemin = Path(chemin)
    if chemin.is_dir():
        chemin = chemin / FICHIERS_SESSION["reconnaissance"]
    nom = _nom_reconnaissance(chemin)
    if not chemin.is_file():
        raise ErreurLieu(f"{nom} : fichier introuvable ({chemin}) ; la reconnaissance n'a pas encore été faite "
                         "(g1-scan traiter --lieu L --session S)")
    donnees = lire_yaml(chemin.read_text(encoding="utf-8"), nom)
    erreurs = valider_reconnaissance(donnees, nom)
    if erreurs:
        raise ErreurLieu(erreurs)
    return donnees


def ecrire_reconnaissance(chemin, donnees):
    """Valide puis écrit reconnaissance.yaml (chemin du fichier, ou dossier de la session), de façon
    atomique. ErreurLieu (et rien d'écrit) si les données sont invalides. Renvoie le chemin."""
    chemin = Path(chemin)
    if chemin.is_dir():
        chemin = chemin / FICHIERS_SESSION["reconnaissance"]
    erreurs = valider_reconnaissance(donnees, _nom_reconnaissance(chemin))
    if erreurs:
        raise ErreurLieu(erreurs)
    ecrire_yaml(chemin, donnees, ENTETE_RECONNAISSANCE)
    return chemin


def resume_reconnaissance(donnees):
    """Comptes pour l'affichage et rapport.json : {murs, murs_gardes, passages, passages_gardes,
    objets: {categorie: nombre}, objets_gardes: {categorie: nombre}}."""
    objets, gardes = {}, {}
    for o in donnees["objets"]:
        objets[o["categorie"]] = objets.get(o["categorie"], 0) + 1
        if o["a_garder"]:
            gardes[o["categorie"]] = gardes.get(o["categorie"], 0) + 1
    return {"murs": len(donnees["murs"]), "murs_gardes": sum(m["a_garder"] for m in donnees["murs"]),
            "passages": len(donnees["passages"]), "passages_gardes": sum(p["a_garder"] for p in donnees["passages"]),
            "objets": objets, "objets_gardes": gardes}


# ---------------------------------------------------------------- monde tiré du scan

ENTETE_MONDE_SCAN = ("Monde tiré du scan : éléments gardés de reconnaissance.yaml (atelier.lieu.monde_depuis_"
                     "reconnaissance). Format : atelier/lieu/schemas/monde.schema.json.")


def monde_depuis_reconnaissance(donnees):
    """Monde (atelier.lieu.Monde) tiré d'une reconnaissance (dict validé), selon les règles 9.4 :

      - chaque mur gardé devient un mur (source scan, avec sa confiance) ;
      - un passage non gardé est bouché : un mur de même id, de « de » à « a », de l'épaisseur et
        de la hauteur du plus grand des deux murs qui le bordent ;
      - chaque objet gardé devient une boîte ou un cylindre (sa forme mesurée), avec categorie,
        source scan et confiance ; une personne gardée y est aussi, mais atelier.monde ne la
        dessine jamais sur la carte 2D ;
      - pas de piéton ; emprise et depart_robot de la reconnaissance.
    Coordonnées arrondies au millimètre.
    """
    murs_par_id = {m["id"]: m for m in donnees["murs"]}
    murs = []

    def ajouter_mur(id_, de, a, epaisseur, hauteur, confiance):
        de, a = (_r(de[0]), _r(de[1])), (_r(a[0]), _r(a[1]))
        if de != a:                      # un mur de moins d'un millimètre n'a pas de sens
            murs.append(Mur(id_, de, a, _r(epaisseur), _r(hauteur), "scan", _r(confiance, 2)))

    for m in donnees["murs"]:
        if m["a_garder"]:
            ajouter_mur(m["id"], m["de"], m["a"], m["epaisseur"], m["hauteur"], m["confiance"])
    for p in donnees["passages"]:
        if p["a_garder"]:
            continue
        bords = [murs_par_id[i] for i in p["murs"] if i in murs_par_id]
        epaisseur = max((m["epaisseur"] for m in bords), default=0.15)
        hauteur = max((m["hauteur"] for m in bords), default=2.5)
        ajouter_mur(p["id"], p["de"], p["a"], epaisseur, hauteur, p["confiance"])
    objets = []
    for o in donnees["objets"]:
        if not o["a_garder"]:
            continue
        commun = {"categorie": o["categorie"], "source": "scan", "confiance": _r(o["confiance"], 2)}
        centre = (_r(o["centre"][0]), _r(o["centre"][1]))
        if o["forme"] == "boite":
            taille = tuple(max(_r(v), 0.001) for v in o["taille"])
            objets.append(Objet.boite(o["id"], centre, taille, _r(o["cap"], 4), **commun))
        else:
            objets.append(Objet.cylindre(o["id"], centre, max(_r(o["rayon"]), 0.001),
                                         max(_r(o["hauteur"]), 0.001), **commun))
    e = donnees["emprise"]
    emprise = Emprise(_r(e["min"][0]), _r(e["min"][1]), _r(e["max"][0]), _r(e["max"][1]))
    d = donnees["depart_robot"]
    return Monde(emprise, Pose(_r(d["x"]), _r(d["y"]), _r(d["theta"], 4)), murs, objets, [])


def ecrire_monde_scan(chemin, donnees):
    """Écrit monde_scan.monde.yaml (chemin du fichier, ou dossier de la session) depuis une
    reconnaissance validée. ErreurLieu si le monde obtenu est invalide. Renvoie le Monde."""
    chemin = Path(chemin)
    if chemin.is_dir():
        chemin = chemin / FICHIERS_SESSION["monde"]
    monde = monde_depuis_reconnaissance(donnees)
    erreurs = valider_donnees("monde", monde.vers_dict(), _nom_reconnaissance(chemin))
    if erreurs:
        raise ErreurLieu(erreurs)
    ecrire_yaml(chemin, monde.vers_dict(), ENTETE_MONDE_SCAN)
    return monde


def passages_du_monde(monde):
    """Passages d'un monde (règle 9.4) : pour chaque paire de murs alignés qui laissent entre eux un
    trou de PASSAGE_MIN à PASSAGE_MAX, sans autre mur aligné dans le trou. Liste de
    {de, a, murs: [id1, id2], largeur}, de et a étant les bouts qui bordent le trou."""
    from .geometrie import PASSAGE_MAX, PASSAGE_MIN, murs_alignes, trou_entre
    murs = list(monde.murs)
    resultat = []
    for i, m1 in enumerate(murs):
        for m2 in murs[i + 1:]:
            if not murs_alignes(m1.de, m1.a, m2.de, m2.a):
                continue
            trou = trou_entre(m1.de, m1.a, m2.de, m2.a)
            if trou is None or not PASSAGE_MIN - 1e-6 <= trou[0] <= PASSAGE_MAX + 1e-6:
                continue
            _, p, q = trou
            milieu = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
            bouche = any(m3 is not m1 and m3 is not m2 and murs_alignes(m1.de, m1.a, m3.de, m3.a)
                         and _dist_point_mur(milieu, m3) < 1e-6 for m3 in murs)
            if not bouche:
                resultat.append({"de": [p[0], p[1]], "a": [q[0], q[1]], "murs": [m1.id, m2.id],
                                 "largeur": trou[0]})
    return resultat


def _dist_point_mur(point, mur):
    from .geometrie import dist_point_segment
    return dist_point_segment(point, mur.de, mur.a)


def reconnaissance_depuis_monde(monde, etage, session=None):
    """Reconnaissance « parfaite » tirée d'un monde dessiné : la vérité terrain au format de
    reconnaissance.yaml (évaluation de la reconnaissance, exemples pour les tests).

    Murs → murs ; passages_du_monde → passages ; objets → boîte ou cylindre (un meuble prend
    l'encombrement de son modèle, une poubelle est un cylindre), catégorie Objet.categorie_effective.
    Confiance 1, a_garder par défaut (faux pour une personne). Les piétons n'y sont pas.
    """
    from .modeles import MODELES_MOBILIER
    donnees = nouvelle_reconnaissance(
        etage, (monde.emprise.xmin, monde.emprise.ymin, monde.emprise.xmax, monde.emprise.ymax),
        (monde.depart_robot.x, monde.depart_robot.y, monde.depart_robot.theta), session=session)
    for m in monde.murs:
        donnees["murs"].append({"id": m.id, "categorie": "mur", "de": list(m.de), "a": list(m.a),
                                "epaisseur": m.epaisseur, "hauteur": m.hauteur, "confiance": 1.0,
                                "a_garder": True})
    pris = set(monde.ids())
    for n, passage in enumerate(passages_du_monde(monde), start=1):
        identifiant = f"passage_{n}"
        while identifiant in pris:
            identifiant += "_bis"
        pris.add(identifiant)
        donnees["passages"].append({"id": identifiant, "categorie": "passage", "de": passage["de"],
                                    "a": passage["a"], "murs": passage["murs"], "confiance": 1.0,
                                    "a_garder": True})
    for o in monde.objets:
        categorie = o.categorie_effective
        element = {"id": o.id, "categorie": categorie}
        dims = MODELES_MOBILIER.get(o.modele, {}) if o.type == "modele" else {}
        if o.type == "cylindre" or "rayon" in dims:
            element.update(forme="cylindre", centre=list(o.centre), rayon=o.rayon or dims["rayon"],
                           hauteur=o.hauteur or dims["hauteur"])
        elif o.type == "boite":
            element.update(forme="boite", centre=list(o.centre), taille=list(o.taille), cap=o.cap)
        else:
            element.update(forme="boite", centre=list(o.centre),
                           taille=[dims["longueur"], dims["largeur"], dims["hauteur"]], cap=o.cap)
        element.update(confiance=1.0, a_garder=a_garder_par_defaut(categorie))
        donnees["objets"].append(element)
    return donnees


def changer_a_garder(lieu, session, choix):
    """Coche ou décoche a_garder : choix = {id: bool} (murs, passages ou objets). Réécrit
    reconnaissance.yaml et monde_scan.monde.yaml. Renvoie {reconnaissance, monde, resume}.

    ErreurLieu si la session est encore active (le traitement n'est pas fini), si la reconnaissance
    manque, ou si un id est inconnu (rien n'est alors modifié).
    """
    with verrou_session(lieu, session):
        s = lire_session(lieu, session)
        if s["etat"] in ETATS_ACTIFS:
            raise ErreurLieu(f"la session {session} n'est pas finie (état {s['etat']}) : attendez la fin du "
                             "traitement pour choisir les éléments à garder")
        dossier = dossier_session(lieu, session)
        donnees = lire_reconnaissance(dossier)
        elements = {e["id"]: e for cle in ("murs", "passages", "objets") for e in donnees[cle]}
        inconnus = [i for i in choix if i not in elements]
        if inconnus:
            raise ErreurLieu(f"reconnaissance de la session {session} : id inconnu(s) {', '.join(map(str, inconnus))} "
                             "(ni mur, ni passage, ni objet reconnu)")
        for i, garder in choix.items():
            if not isinstance(garder, bool):
                raise ErreurLieu(f"a_garder de « {i} » doit valoir true ou false, pas {garder!r}")
            elements[i]["a_garder"] = garder
        ecrire_reconnaissance(dossier, donnees)
        monde = ecrire_monde_scan(dossier, donnees)
    return {"reconnaissance": donnees, "monde": monde.vers_dict(), "resume": resume_reconnaissance(donnees)}


def carte_sans_elements_retires(info, image, donnees, marge=0.05):
    """Copie de la carte du scan où les objets retirés deviennent libres (règle 9.4, à l'adoption).

    Un objet retiré : a_garder faux, ou catégorie personne (jamais sur la carte). Les pixels occupés
    (0) dont le centre est dans son empreinte agrandie de marge (m) passent à libre (254). Les murs
    et les passages ne changent jamais la carte : elle reste celle du scan.
    """
    image = np.array(image, copy=True)
    X, Y = centres_pixels(info)
    for o in donnees["objets"]:
        if o["a_garder"] and o["categorie"] not in CATEGORIES_HORS_CARTE:
            continue
        dx, dy = X - o["centre"][0], Y - o["centre"][1]
        if o["forme"] == "cylindre":
            dedans = np.hypot(dx, dy) <= o["rayon"] + marge
        else:
            c, s = math.cos(o["cap"]), math.sin(o["cap"])
            u, v = c * dx + s * dy, -s * dx + c * dy
            dedans = (np.abs(u) <= o["taille"][0] / 2 + marge) & (np.abs(v) <= o["taille"][1] / 2 + marge)
        image[dedans & (image == OCCUPE)] = LIBRE
    return image
