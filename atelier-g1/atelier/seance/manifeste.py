"""Le dossier d'une séance et son manifeste seance.json (vague 6, section 13.3 du plan) : agent Boîte noire.

Le manifeste suit le schéma seance (atelier/lieu/schemas/seance.schema.json). Plusieurs programmes l'écrivent :
le serveur de l'Atelier tant que la séance est ouverte, puis g1-seance rapport (champ rapport), et la reprise
après un plantage. Chaque écriture passe par modifier_manifeste : un verrou de fichier (.seance.lock, fcntl),
puis une écriture atomique (fichier temporaire, puis renommage) : un lecteur ne voit jamais un fichier à moitié
écrit, et deux écrivains ne s'écrasent pas.

Fonctions :
  heure_iso(t=None, ms=False)          heure locale ISO 8601 avec le décalage (à la seconde, ou à la ms)
  lire_heure(texte)                    → secondes depuis 1970 (time.time), ou None
  creer_dossier(instant=None, racine=None) → (id, dossier) : AAAA-MM-JJ_HHhMM, -2, -3… si la minute est prise
  nouveau_manifeste(ident, mode, ...)  → le manifeste d'une séance qui s'ouvre (état « ouverte »)
  lire_manifeste(dossier) / ecrire_manifeste(dossier, m) / modifier_manifeste(dossier, fonction)
  liste_seances(racine=None)           → [(id, dossier)], la plus récente d'abord
  dossier_de(texte)                    → le dossier d'une séance : un id de dossier_seances(), ou un chemin
  resume(manifeste)                    → {id, etat, mode, lieu, etage, debut, fin, duree_s, actions, rapport,
                                          enregistrement} pour les listes
  derniere_ecriture(dossier)           → l'heure du fichier le plus récent du dossier (reprise après plantage)
  commit_atelier()                     → le commit Git de l'Atelier (lu dans .git, sans lancer git), ou None
"""
import contextlib
import fcntl
import json
import os
import time
from datetime import datetime
from pathlib import Path

import atelier
from atelier.lieu.fichiers import ecrire_atomique
from atelier.lieu.seance import FICHIERS_SEANCE, MOTIF_ID_SEANCE, dossier_seances, id_seance, reglage

VERROU = ".seance.lock"          # verrou des écritures du manifeste (fcntl.flock), dans le dossier de la séance
ESSAIS_DOSSIER = 50              # suffixes -2, -3… essayés si plusieurs séances s'ouvrent dans la même minute


def heure_iso(t=None, ms=False):
    """Heure locale ISO 8601 avec le décalage : 2026-11-12T14:03:05+01:00 (ou .218 avec ms)."""
    instant = datetime.fromtimestamp(time.time() if t is None else t).astimezone()
    return instant.isoformat(timespec="milliseconds" if ms else "seconds")


def lire_heure(texte):
    """Une heure ISO 8601 (avec décalage) → secondes depuis 1970 ; None si illisible."""
    if not isinstance(texte, str) or not texte:
        return None
    try:
        return datetime.fromisoformat(texte.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def chemin(dossier, nom):
    """Chemin d'un fichier de la séance d'après FICHIERS_SEANCE (« manifeste », « actions », « bag »…)."""
    return Path(dossier) / FICHIERS_SEANCE[nom]


def creer_dossier(instant=None, racine=None):
    """Crée le dossier d'une nouvelle séance et renvoie (id, dossier). L'id est l'heure d'ouverture à la minute,
    avec -2, -3… si la minute est déjà prise (mkdir exclusif : deux ouvertures simultanées ne se mélangent pas)."""
    racine = Path(racine) if racine is not None else dossier_seances()
    racine.mkdir(parents=True, exist_ok=True)
    instant = instant or datetime.now()
    existants = {d.name for d in racine.iterdir()}
    for _ in range(ESSAIS_DOSSIER):
        ident = id_seance(instant, existants)
        dossier = racine / ident
        try:
            dossier.mkdir()
            return ident, dossier
        except FileExistsError:
            existants.add(ident)
    raise RuntimeError(f"impossible de créer le dossier d'une séance dans {racine}")


def nouveau_manifeste(ident, mode, lieu=None, etage=None, ouverture="auto", debut=None, port=None):
    """Le manifeste d'une séance qui s'ouvre (schéma seance, état « ouverte »)."""
    return {
        "version": 1, "id": ident, "etat": "ouverte", "mode": mode, "lieu": lieu, "etage": etage,
        "debut": heure_iso(debut), "fin": None, "duree_s": None, "ouverture": ouverture, "fermeture": None,
        "atelier": {"version": atelier.__version__, "commit": commit_atelier(), "pid": os.getpid(), "port": port},
        "enregistrement": {"etat": "demarrage", "pid": None, "octets": 0, "message": None, "sujets": []},
        "actions": 0, "diagnostic_debut": None, "jetson": [],
        "rapport": {"etat": "absent", "fichiers": [], "message": None, "date": None},
        "reglages": {"taille_max_mo": reglage("taille_max_mo"), "place_libre_min_go": reglage("place_libre_min_go")},
        "messages": [],
    }


def lire_manifeste(dossier):
    """Le manifeste (dict) d'une séance, ou None s'il manque ou est illisible."""
    try:
        donnees = json.loads(chemin(dossier, "manifeste").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return donnees if isinstance(donnees, dict) else None


def _texte(manifeste):
    return json.dumps(manifeste, ensure_ascii=False, indent=1) + "\n"


@contextlib.contextmanager
def verrou_manifeste(dossier):
    """Verrou exclusif des écritures du manifeste, entre programmes (le serveur, g1-seance rapport)."""
    dossier = Path(dossier)
    dossier.mkdir(parents=True, exist_ok=True)
    with open(dossier / VERROU, "a+") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def ecrire_manifeste(dossier, manifeste):
    """Réécrit le manifeste entier, de façon atomique (sous le verrou)."""
    with verrou_manifeste(dossier):
        ecrire_atomique(chemin(dossier, "manifeste"), _texte(manifeste))


def modifier_manifeste(dossier, fonction):
    """Lit le manifeste, le passe à fonction(m) (qui le modifie sur place), puis le réécrit, le tout sous le
    verrou. Renvoie le manifeste écrit, ou None s'il n'y en a pas."""
    with verrou_manifeste(dossier):
        m = lire_manifeste(dossier)
        if m is None:
            return None
        fonction(m)
        ecrire_atomique(chemin(dossier, "manifeste"), _texte(m))
        return m


def liste_seances(racine=None):
    """[(id, dossier)] des séances (dossiers dont le nom est un id de séance), la plus récente d'abord."""
    racine = Path(racine) if racine is not None else dossier_seances()
    if not racine.is_dir():
        return []
    dossiers = [d for d in racine.iterdir() if d.is_dir() and MOTIF_ID_SEANCE.match(d.name)]

    def cle(d):
        # « 2026-11-12_14h03-10 » vient après « …-9 » : le suffixe se compare comme un nombre
        base, suffixe = d.name[:16], d.name[17:]
        return (base, int(suffixe) if suffixe.isdigit() else 1)
    return [(d.name, d) for d in sorted(dossiers, key=cle, reverse=True)]


def dossier_de(texte, racine=None):
    """Le dossier d'une séance : un id (2026-11-12_14h03) de dossier_seances(), ou un chemin de dossier.
    ValueError en français si rien ne correspond."""
    texte = str(texte or "").strip()
    if not texte:
        raise ValueError("dites quelle séance : son identifiant (ex. 2026-11-12_14h03) ou son dossier")
    if MOTIF_ID_SEANCE.match(texte):
        dossier = (Path(racine) if racine is not None else dossier_seances()) / texte
        if dossier.is_dir():
            return dossier
    dossier = Path(texte).expanduser()
    if dossier.is_dir() and (chemin(dossier, "manifeste").is_file() or chemin(dossier, "bag").is_dir()
                             or chemin(dossier, "actions").is_file()):
        return dossier.resolve()
    raise ValueError(f"séance introuvable : « {texte} » (g1-seance liste montre les séances)")


def resume(manifeste):
    """Le résumé d'une séance pour les listes : {id, etat, mode, lieu, etage, debut, fin, duree_s, actions,
    rapport (son état), enregistrement (son état)}."""
    m = manifeste or {}
    duree = m.get("duree_s")
    if duree is None and m.get("etat") == "ouverte":
        debut = lire_heure(m.get("debut"))
        duree = None if debut is None else round(max(0.0, time.time() - debut), 1)
    return {"id": m.get("id"), "etat": m.get("etat"), "mode": m.get("mode"), "lieu": m.get("lieu"),
            "etage": m.get("etage"), "debut": m.get("debut"), "fin": m.get("fin"), "duree_s": duree,
            "actions": m.get("actions", 0), "rapport": (m.get("rapport") or {}).get("etat", "absent"),
            "enregistrement": (m.get("enregistrement") or {}).get("etat")}


def derniere_ecriture(dossier):
    """Heure (time.time) du fichier le plus récemment écrit dans le dossier (sous-dossiers compris), sans le verrou
    du manifeste ; None si le dossier est vide."""
    plus_recent = None
    for racine, _, fichiers in os.walk(dossier):
        for nom in fichiers:
            if nom == VERROU:
                continue
            try:
                t = os.stat(os.path.join(racine, nom)).st_mtime
            except OSError:
                continue
            plus_recent = t if plus_recent is None else max(plus_recent, t)
    return plus_recent


def commit_atelier(racine=None):
    """Commit court de l'Atelier (7 caractères), lu dans .git sans lancer git ; None hors d'un dépôt Git."""
    git = Path(racine or atelier.RACINE) / ".git"
    try:
        tete = (git / "HEAD").read_text(encoding="utf-8").strip()
        if not tete.startswith("ref:"):
            return tete[:7] or None
        ref = tete.split(":", 1)[1].strip()
        fichier = git / ref
        if fichier.is_file():
            return fichier.read_text(encoding="utf-8").strip()[:7] or None
        for ligne in (git / "packed-refs").read_text(encoding="utf-8").splitlines():
            if ligne.endswith(" " + ref):
                return ligne.split(" ", 1)[0][:7]
    except OSError:
        return None
    return None
