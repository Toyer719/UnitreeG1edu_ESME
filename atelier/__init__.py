"""Atelier G1 : le logiciel de configuration des lieux du robot d'accueil.

Sous-paquets (un agent par sous-paquet, voir docs/plan-atelier-multi-agents.md) :
  lieu     charger, valider et enregistrer un paquet de lieu (agent Données)
  monde    monde.yaml → monde Gazebo .sdf, carte 2D et masques (agent Monde)
  scan     client slam_operate du robot, cartes issues du scan (agent Scan)
  serveur  serveur web FastAPI de l'Atelier (agent Interface)

Ce module ne contient que les chemins communs à tous les outils.
"""
import os
import re
from pathlib import Path

__version__ = "0.1.0"

# Dossier du projet (~/robot-g1) : ce fichier est dans ~/robot-g1/atelier/
RACINE = Path(__file__).resolve().parent.parent

# Forme d'un identifiant de lieu, d'étage, de salle, de nœud, de mur, d'objet ou de piéton
MOTIF_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")


def dossier_lieux():
    """Dossier qui contient les lieux : $ATELIER_LIEUX, sinon ~/robot-g1/lieux."""
    return Path(os.environ.get("ATELIER_LIEUX") or RACINE / "lieux").expanduser()


def dossier_journaux():
    """Dossier des journaux des outils (~/robot-g1/journaux), créé au besoin."""
    dossier = RACINE / "journaux"
    dossier.mkdir(parents=True, exist_ok=True)
    return dossier


def chemin_lieu(texte):
    """Dossier d'un lieu, à partir de ce que l'utilisateur a tapé après --lieu ou lieu:=.

    Un identifiant seul, sans « / » (ex. « demo »), désigne dossier_lieux()/demo.
    Tout le reste est un chemin, relatif au dossier courant ou absolu.
    Le dossier n'a pas besoin d'exister (cas de « g1-lieu creer »).
    """
    texte = str(texte).strip()
    if MOTIF_ID.match(texte):
        return dossier_lieux() / texte
    return Path(texte).expanduser().resolve()
