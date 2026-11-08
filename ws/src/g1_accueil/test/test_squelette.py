"""Le paquet g1_accueil existe et son nœud est déclaré (contrats de la vague 6, section 13.4)."""
from pathlib import Path


def test_noeud_declare():
    """Le point d'entrée accueil est déclaré dans setup.py et main() existe."""
    racine = Path(__file__).resolve().parent.parent
    assert "'accueil = g1_accueil.noeud:main'" in (racine / 'setup.py').read_text(encoding='utf-8')
    from g1_accueil import noeud
    assert callable(noeud.main)


def test_logique_sans_ros():
    """La machine d'états se crée sans ROS (squelette : rien à publier)."""
    from g1_accueil.logique import Orchestrateur
    o = Orchestrateur([], 'accueil', 'rdc')
    assert o.entrer('/accueil/choix', {'salle': 'b204'}) == [] and o.pas() == []
