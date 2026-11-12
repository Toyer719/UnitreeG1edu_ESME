"""Outils communs aux tests du serveur de l'Atelier (agent Interface).

Pas de test ici : seulement des fixtures, importées par les fichiers test_serveur_*.py.
  lieux     copie de lieux/demo dans un dossier temporaire ($ATELIER_LIEUX), sans carte ni .sdf
  faux_bin  fausses commandes g1-monde, g1-guide et g1-slam ($ATELIER_BIN) : elles notent leurs
            arguments dans un journal et imitent les vraies (carte fabriquée, processus longs)
  client    TestClient de FastAPI sur l'application, sans pont ROS 2
"""
import os
import shutil
import signal
import struct
import sys
import time
import zlib
from pathlib import Path

import numpy as np
import pytest

import atelier
from atelier.lieu import copier_lieu

DEMO = atelier.RACINE / "lieux" / "demo"

# Fausse commande g1-monde : « generer » fabrique une vraie carte (tout libre, bord occupé) avec
# atelier.lieu ; « simuler » tourne longtemps avec un processus enfant (pour vérifier que l'arrêt
# tue tout le groupe). FAUX_ECHEC=1 : la commande échoue.
FAUX_MONDE = r'''#!{python}
"""Faux g1-monde des tests de l'interface."""
import os, subprocess, sys, time
from pathlib import Path
args = sys.argv[1:]
with open(os.environ["FAUX_JOURNAL"], "a") as f:
    f.write("g1-monde " + " ".join(args) + "\n")
def option(nom):
    return args[args.index(nom) + 1]
if os.environ.get("FAUX_ECHEC") == "1":
    print("erreur : le mur « m1 » sort de l'emprise", flush=True)
    sys.exit(3)
if args[0] == "generer":
    import numpy as np
    from atelier.lieu import (charger_monde, chemin_carte, chemin_interdit, chemin_sdf, enregistrer_carte,
                              info_carte_pour_emprise)
    lieu, etage = option("--lieu"), option("--etage")
    e = charger_monde(lieu, etage).emprise
    for chemin, nom in ((chemin_carte(lieu, etage), etage), (chemin_interdit(lieu, etage), etage + "_interdit")):
        info = info_carte_pour_emprise(e.xmin, e.ymin, e.xmax, e.ymax, image=nom + ".pgm")
        image = np.full((info.hauteur, info.largeur), 254, np.uint8)
        if nom == etage:
            image[0, :] = 0           # ligne du haut (y maximal) occupée
            image[:, 0] = 205         # colonne de gauche inconnue
        enregistrer_carte(chemin, info, image)
    chemin_sdf(lieu, etage).write_text("<sdf version='1.9'><world name='faux'/></sdf>\n")
    print("faux g1-monde : carte fabriquée", flush=True)
elif args[0] == "simuler":
    print("faux g1-monde : simulation lancée", flush=True)
    enfant = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])
    Path(os.environ["FAUX_JOURNAL"] + ".pids").open("a").write(f"{{os.getpid()}} {{enfant.pid}}\n")
    time.sleep(300)
'''

FAUX_GUIDE = r'''#!{python}
"""Faux g1-guide des tests de l'interface."""
import os, subprocess, sys, time
from pathlib import Path
args = sys.argv[1:]
with open(os.environ["FAUX_JOURNAL"], "a") as f:
    f.write("g1-guide " + " ".join(args) + "\n")
if args[0] == "navigation":
    print("faux g1-guide : navigation lancée", flush=True)
    enfant = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])
    Path(os.environ["FAUX_JOURNAL"] + ".pids").open("a").write(f"{{os.getpid()}} {{enfant.pid}}\n")
    time.sleep(300)
elif args[0] == "stop":
    print("faux g1-guide : arrêt envoyé", flush=True)
'''

FAUX_SLAM = r'''#!{python}
"""Faux g1-slam des tests de l'interface (ne parle à aucun réseau)."""
import os, sys, time
from pathlib import Path
args = sys.argv[1:]
with open(os.environ["FAUX_JOURNAL"], "a") as f:
    f.write("g1-slam " + " ".join(args) + "\n")
if args[0] == "faux-service":
    if os.environ.get("FAUX_ECHEC") == "1":
        print("erreur : domaine DDS occupé", flush=True)
        sys.exit(1)
    Path(os.environ["FAUX_JOURNAL"] + ".pids").open("a").write(f"{{os.getpid()}}\n")
    print("Faux service slam_operate prêt sur lo", flush=True)
    time.sleep(300)
    sys.exit(0)
if os.environ.get("FAUX_ECHEC") == "1":
    print("erreur : pas de réponse du service slam_operate", flush=True)
    sys.exit(1)
print("faux g1-slam : " + " ".join(args) + " : réussi", flush=True)
'''


class FauxBin:
    """Dossier de fausses commandes, et lecture de leur journal."""

    def __init__(self, dossier, journal):
        self.dossier = Path(dossier)
        self.journal = Path(journal)

    def ecrire(self, nom, modele):
        chemin = self.dossier / nom
        chemin.write_text(modele.format(python=sys.executable))
        chemin.chmod(0o755)
        return chemin

    def retirer(self, nom):
        (self.dossier / nom).unlink()

    def appels(self):
        return self.journal.read_text().splitlines() if self.journal.exists() else []

    def pids(self):
        """PID des faux processus longs et de leurs enfants."""
        fichier = Path(str(self.journal) + ".pids")
        if not fichier.exists():
            return []
        return [int(p) for ligne in fichier.read_text().split("\n") for p in ligne.split()]


def processus_vivant(pid):
    """Vrai si le processus existe et n'est pas un zombie."""
    try:
        etat = Path(f"/proc/{pid}/stat").read_text().split(") ")[-1].split()[0]
    except (FileNotFoundError, ProcessLookupError):
        return False
    return etat != "Z"


def attendre(condition, delai=10.0, pas=0.05):
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        if condition():
            return True
        time.sleep(pas)
    return condition()


def lire_png(octets):
    """Décode un PNG en niveaux de gris 8 bits écrit sans filtre (celui du serveur) → numpy."""
    assert octets[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat, largeur, hauteur = 8, b"", None, None
    while pos < len(octets):
        (longueur,) = struct.unpack(">I", octets[pos:pos + 4])
        genre = octets[pos + 4:pos + 8]
        donnees = octets[pos + 8:pos + 8 + longueur]
        (crc,) = struct.unpack(">I", octets[pos + 8 + longueur:pos + 12 + longueur])
        assert crc == zlib.crc32(genre + donnees) & 0xFFFFFFFF, f"CRC faux dans le bloc {genre}"
        if genre == b"IHDR":
            largeur, hauteur, prof, couleur = struct.unpack(">IIBB", donnees[:10])
            assert (prof, couleur) == (8, 0)
        elif genre == b"IDAT":
            idat += donnees
        pos += 12 + longueur
    brut = np.frombuffer(zlib.decompress(idat), np.uint8).reshape(hauteur, largeur + 1)
    assert (brut[:, 0] == 0).all()
    return brut[:, 1:]


@pytest.fixture
def journaux(tmp_path, monkeypatch):
    """Les journaux des processus lancés vont dans le dossier temporaire du test."""
    dossier = tmp_path / "journaux"
    dossier.mkdir()
    monkeypatch.setattr(atelier, "dossier_journaux", lambda: dossier)
    return dossier


@pytest.fixture
def lieux(tmp_path, monkeypatch, journaux):
    """$ATELIER_LIEUX temporaire avec une copie de lieux/demo, sans fichier généré."""
    dossier = tmp_path / "lieux"
    dossier.mkdir()
    copie = copier_lieu(DEMO, dossier / "demo")
    shutil.rmtree(copie / "cartes", ignore_errors=True)
    for sdf in (copie / "mondes").glob("*.sdf"):
        sdf.unlink()
    monkeypatch.setenv("ATELIER_LIEUX", str(dossier))
    return dossier


@pytest.fixture
def faux_bin(tmp_path, monkeypatch):
    dossier = tmp_path / "bin"
    dossier.mkdir()
    fb = FauxBin(dossier, tmp_path / "appels.txt")
    fb.ecrire("g1-monde", FAUX_MONDE)
    fb.ecrire("g1-guide", FAUX_GUIDE)
    fb.ecrire("g1-slam", FAUX_SLAM)
    monkeypatch.setenv("ATELIER_BIN", str(dossier))
    monkeypatch.setenv("FAUX_JOURNAL", str(fb.journal))
    monkeypatch.delenv("FAUX_ECHEC", raising=False)
    yield fb
    # filet de sécurité : aucun faux processus ne doit survivre au test
    for pid in fb.pids():
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


@pytest.fixture
def client(lieux, faux_bin):
    from fastapi.testclient import TestClient
    from atelier.serveur.main import creer_app
    app = creer_app(ros=False)
    with TestClient(app) as c:
        yield c
