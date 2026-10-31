"""Sessions de scan intégré (sections 9 et 12.5 du plan) : dossiers LIEU/scans/<session>/.

Ce module est le seul qui lit et écrit session.json : g1-scan (agent Scan) et le serveur de l'Atelier
passent tous par lui. Il ne dépend pas de ROS.

Contenu d'une session (FICHIERS_SESSION, et les nuages d'affichage de atelier.lieu.nuage) :

    scans/2026-10-25_17h42/
    ├── enregistrement/          ros2 bag du scan (ignoré par Git)
    ├── session.json             état (schéma session_scan) : mode, étape, progression, message...
    ├── apercu.png, apercu.json  vue de dessus en direct, et points décimés + trajectoire
    ├── apercu_nuage.bin, .json  aperçu en direct du nuage 3D (toutes hauteurs, grille de 10 cm)
    ├── nuage.pcd                nuage 3D assemblé, repère map (atelier.scan.carte3d)
    ├── carte.pgm, carte.yaml    carte 2D Nav2 (atelier.scan.carte2d)
    ├── nuage_affichage.bin, .json  nuage de la carte 3D : hauteur au-dessus du sol, grille de 5 cm
    ├── rapport.json             bilan du traitement
    ├── monde_remplace.monde.yaml  ancien monde dessiné de l'étage, gardé par g1-scan adopter
    └── ancien_<AAAA-MM-JJ_HHhMM>/ résultats d'avant un g1-scan traiter --refaire

Vague 5 (section 12.5) : la reconnaissance des murs et des meubles est retirée. Les anciens fichiers
reconnaissance.yaml et monde_scan.monde.yaml des sessions d'avant restent sur le disque (personne ne
les lit) ; --refaire les range dans ancien_<horodatage>/ avec les autres résultats.

Écritures atomiques (fichier temporaire, puis renommage). Les mises à jour de session.json par
plusieurs processus (processus du scan, g1-scan arreter, serveur) passent par maj_session, qui
prend un verrou (fcntl) sur scans/<session>/.session.lock.
"""
import contextlib
import fcntl
import json
import os
import re
import socket
import time
from datetime import datetime
from pathlib import Path

from .fichiers import ErreurLieu, charger_fiche, dossier_lieu, ecrire_atomique
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
    "rapport": "rapport.json",
    "monde_remplace": "monde_remplace.monde.yaml",     # ancien monde dessiné de l'étage, gardé par g1-scan adopter
}
# Nuages d'affichage d'une session (base sans extension ; .bin et .json : atelier.lieu.nuage)
NUAGE_AFFICHAGE = "nuage_affichage"                     # fin du traitement, grille de 5 cm
APERCU_NUAGE = "apercu_nuage"                           # aperçu en direct, grille de 10 cm
# Fichiers des sessions d'avant la vague 5 (reconnaissance retirée) : rangés par g1-scan traiter --refaire
ANCIENS_FICHIERS_SESSION = ("reconnaissance.yaml", "monde_scan.monde.yaml")
# Résultats du traitement, déplacés dans ancien_<AAAA-MM-JJ_HHhMM>/ par g1-scan traiter --refaire
RESULTATS_TRAITEMENT = ("nuage.pcd", "carte.yaml", "carte.pgm", "nuage_affichage.bin", "nuage_affichage.json",
                        "rapport.json") + ANCIENS_FICHIERS_SESSION
PREFIXE_ANCIEN = "ancien_"
MOTIF_SESSION = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{2}h[0-9]{2}(-[0-9]{1,3})?$")

MODES = ("robot", "simu")
ETATS = ("en_cours", "arret_en_cours", "traitement", "termine", "echec")
ETATS_ACTIFS = ("en_cours", "arret_en_cours", "traitement")
# Vague 5 (section 12.5) : carte_3d → carte_2d → nuage. Les étapes reconnaissance et monde des sessions
# d'avant restent acceptées par le schéma (ANCIENNES_ETAPES), mais ne sont plus produites.
ETAPES = ("preparation", "enregistrement", "arret", "carte_3d", "carte_2d", "nuage", "fini")
ETAPES_TRAITEMENT = ("carte_3d", "carte_2d", "nuage")
ANCIENNES_ETAPES = ("reconnaissance", "monde")
# Progression (0 à 100) au début et à la fin de chaque étape : la barre de l'interface
PLAGES_PROGRESSION = {"preparation": (0, 0), "enregistrement": (0, 0), "arret": (5, 5),
                      "carte_3d": (10, 70), "carte_2d": (70, 85), "nuage": (85, 99), "fini": (100, 100),
                      "reconnaissance": (85, 99), "monde": (85, 99)}

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


def _nuage_present(dossier, nom):
    return (dossier / f"{nom}.bin").is_file() and (dossier / f"{nom}.json").is_file()


def fichiers_presents(lieu, session):
    """Fichiers déjà écrits de la session : {enregistrement, apercu_png, apercu_json, apercu_nuage, nuage,
    carte, nuage_affichage, rapport} → booléens."""
    d = dossier_session(lieu, session)
    return {"enregistrement": (d / FICHIERS_SESSION["enregistrement"] / "metadata.yaml").is_file(),
            "apercu_png": (d / FICHIERS_SESSION["apercu_png"]).is_file(),
            "apercu_json": (d / FICHIERS_SESSION["apercu_json"]).is_file(),
            "apercu_nuage": _nuage_present(d, APERCU_NUAGE),
            "nuage": (d / FICHIERS_SESSION["nuage"]).is_file(),
            "carte": (d / FICHIERS_SESSION["carte"]).is_file() and (d / FICHIERS_SESSION["carte_image"]).is_file(),
            "nuage_affichage": _nuage_present(d, NUAGE_AFFICHAGE),
            "rapport": (d / FICHIERS_SESSION["rapport"]).is_file()}


def ranger_resultats(lieu, session, quand=None):
    """g1-scan traiter --refaire : déplace les résultats du traitement d'avant (RESULTATS_TRAITEMENT
    présents) dans scans/<session>/ancien_<AAAA-MM-JJ_HHhMM>/ (suffixe -2, -3… si la minute est prise).
    Rien n'est effacé. Renvoie le dossier créé, ou None s'il n'y avait rien à ranger."""
    d = dossier_session(lieu, session)
    presents = [nom for nom in RESULTATS_TRAITEMENT if (d / nom).is_file()]
    if not presents:
        return None
    base = PREFIXE_ANCIEN + (quand or datetime.now()).strftime("%Y-%m-%d_%Hh%M")
    cible, n = d / base, 1
    while True:
        try:
            cible.mkdir()
            break
        except FileExistsError:
            n += 1
            cible = d / f"{base}-{n}"
    for nom in presents:
        os.replace(d / nom, cible / nom)
    return cible


def anciens_resultats(lieu, session):
    """Dossiers ancien_<horodatage>/ de la session (résultats d'avant un --refaire), du plus ancien au
    plus récent."""
    d = dossier_session(lieu, session)
    if not d.is_dir():
        return []
    return sorted(x for x in d.iterdir() if x.is_dir() and x.name.startswith(PREFIXE_ANCIEN))


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
