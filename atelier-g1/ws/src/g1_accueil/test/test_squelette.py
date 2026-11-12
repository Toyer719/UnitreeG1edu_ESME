"""Le paquet g1_accueil existe et son nœud est déclaré (contrats de la vague 6, section 13.4)."""
from pathlib import Path


def test_noeud_declare():
    """Le point d'entrée accueil est déclaré dans setup.py et main() existe."""
    racine = Path(__file__).resolve().parent.parent
    assert "'accueil = g1_accueil.noeud:main'" in (racine / 'setup.py').read_text(encoding='utf-8')
    from g1_accueil import noeud
    assert callable(noeud.main)


def test_logique_sans_ros():
    """La machine d'états se crée sans ROS ; au démarrage, un choix est refusé (robot occupé)."""
    from g1_accueil.logique import Orchestrateur
    o = Orchestrateur([], 'accueil', 'rdc')
    sorties = o.entrer('/accueil/choix', {'version': 1, 'salle': 'b204', 'source': 'test'})
    evenements = [d for s, d in sorties if s == '/accueil/evenement']
    assert [e['code'] for e in evenements] == ['choix_refuse']
    assert evenements[0]['raison'] == 'occupe'
    assert not [s for s, _ in sorties if s == '/guide/aller']
    assert o.etat()['etat'] == 'demarrage'
