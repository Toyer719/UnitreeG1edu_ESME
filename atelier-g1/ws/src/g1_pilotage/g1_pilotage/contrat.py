"""
Accès au contrat du pilotage : le module atelier.lieu.pilotage (section 11.5 du plan).

Dans le conteneur du Jetson, atelier est copié dans /opt/g1/python (sur le PYTHONPATH). Sur le PC,
le paquet est compilé avec --symlink-install : le fichier source est dans ws/src/g1_pilotage, et la
racine du dépôt (qui contient atelier/) est quatre dossiers plus haut. Le module ne dépend que de
PyYAML et numpy, présents dans le Python du système.
"""
from pathlib import Path
import sys


def charger():
    """Le module atelier.lieu.pilotage ; ImportError avec un message clair s'il manque."""
    try:
        from atelier.lieu import pilotage
        return pilotage
    except ImportError:
        pass
    for parent in Path(__file__).resolve().parents:
        if (parent / 'atelier' / 'lieu' / 'pilotage.py').is_file():
            sys.path.insert(0, str(parent))
            break
    try:
        from atelier.lieu import pilotage
    except ImportError as erreur:
        raise ImportError(
            f'atelier.lieu.pilotage introuvable ({erreur}) : lancez le nœud depuis le dépôt '
            'robot-g1, ou mettez le dossier qui contient atelier/ dans PYTHONPATH') from None
    return pilotage
