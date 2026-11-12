"""L'export d'une séance (vague 6, section 13.3 du plan) : g1-seance exporter DOSSIER [--sortie F.zip] [--sans-bag].

Un seul fichier .zip avec tout le dossier de la séance (manifeste, journal des actions, rapport, enregistrement,
journaux, copie du lieu), rangé sous <id>/ : c'est ce qu'on donne à Claude pour analyser une séance. Le bag est
déjà compact (sqlite3) ; --sans-bag le laisse de côté (un .zip à envoyer par messagerie).
"""
import os
import tempfile
import zipfile
from pathlib import Path

from .manifeste import VERROU

DEFAUT_SORTIE = "seance_{id}.zip"


def fichiers_a_exporter(dossier, sans_bag=False):
    """[(chemin, nom dans le zip)] des fichiers de la séance."""
    dossier = Path(dossier)
    liste = []
    for chemin in sorted(dossier.rglob("*")):
        if not chemin.is_file() or chemin.name == VERROU or chemin.name.endswith(".tmp"):
            continue
        relatif = chemin.relative_to(dossier)
        if sans_bag and relatif.parts[0] == "bag":
            continue
        liste.append((chemin, f"{dossier.name}/{relatif.as_posix()}"))
    return liste


def exporter(dossier, sortie=None, sans_bag=False):
    """Écrit le .zip (sortie, ou seance_<id>.zip dans le dossier courant) et renvoie son chemin. L'archive est écrite
    à côté puis renommée : jamais un .zip à moitié écrit."""
    dossier = Path(dossier)
    sortie = Path(sortie) if sortie else Path.cwd() / DEFAUT_SORTIE.format(id=dossier.name)
    sortie.parent.mkdir(parents=True, exist_ok=True)
    fd, temporaire = tempfile.mkstemp(dir=sortie.parent, prefix=f".{sortie.name}.", suffix=".tmp")
    os.close(fd)
    try:
        with zipfile.ZipFile(temporaire, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for chemin, nom in fichiers_a_exporter(dossier, sans_bag):
                try:
                    z.write(chemin, nom)
                except OSError:
                    continue            # fichier disparu entre-temps (rapport en cours de réécriture)
        os.replace(temporaire, sortie)
    except BaseException:
        try:
            os.unlink(temporaire)
        except FileNotFoundError:
            pass
        raise
    return sortie
