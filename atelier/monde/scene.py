"""Scènes d'essai des passants (vague 4, section 11.3 du plan) : agent Passants.

Une scène (schéma scene, fichiers atelier/monde/scenes/<id>.scene.yaml) s'applique à une COPIE d'un
lieu de référence : ses piétons remplacent (ou complètent, ajouter: true) ceux du monde de l'étage,
puis le monde est regénéré ; g1-banc --scene ID fait ses trajets et vérifie ses seuils (mesures).

Squelette livré par l'intégrateur : signatures du contrat, à écrire par l'agent Passants.
"""
from pathlib import Path

DOSSIER_SCENES = Path(__file__).resolve().parent / "scenes"
SUFFIXE_SCENE = ".scene.yaml"


def lister_scenes(dossier=None):
    """Chemins des scènes du dossier (défaut : atelier/monde/scenes)."""
    racine = Path(dossier or DOSSIER_SCENES)
    return sorted(racine.glob(f"*{SUFFIXE_SCENE}")) if racine.is_dir() else []


def charger_scene(ident):
    """Lit et vérifie une scène (id ou chemin) ; ErreurLieu si elle est fausse."""
    raise NotImplementedError("charger_scene : à écrire par l'agent Passants (section 11.3 du plan)")


def appliquer_scene(lieu, scene):
    """Applique la scène à une copie de lieu (jamais à lieux/demo) : piétons, réglages du guide,
    puis atelier.monde.generer. Renvoie le Monde écrit."""
    raise NotImplementedError("appliquer_scene : à écrire par l'agent Passants (section 11.3 du plan)")
