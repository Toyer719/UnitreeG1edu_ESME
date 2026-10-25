"""
Tests de la commande g1-guide, sans ROS : options et affichage de l'état.

  python3 -m pytest ~/robot-g1/ws/src/g1_nav/test/test_commande.py -v
"""
from g1_nav import commande
import pytest


def test_navigation_traduit_les_options(monkeypatch):
    lance = []
    monkeypatch.setattr(commande.os, 'execvp', lambda prog, args: lance.append(args))
    commande.main(['navigation', '--lieu', 'demo', '--etage', 'rdc', '--simu'])
    assert lance == [['ros2', 'launch', 'g1_nav', 'navigation.launch.py', 'lieu:=demo',
                      'etage:=rdc', 'simu:=true', 'moteur:=nav2']]
    commande.main(['navigation', '--lieu', '/tmp/x', '--etage', 'e1', '--moteur', 'unitree'])
    assert lance[-1][-2:] == ['simu:=false', 'moteur:=unitree']


def test_commande_mal_tapee(capsys):
    with pytest.raises(SystemExit) as fin:
        commande.main(['navigation', '--etage', 'rdc'])
    assert fin.value.code == 2
    assert 'il manque' in capsys.readouterr().err
    with pytest.raises(SystemExit):
        commande.main(['voler'])


def test_texte_etat():
    texte = commande.texte_etat({'etat': 'en_route', 'cible': 'b204', 'reste_m': 12.46,
                                 'itineraire': ['accueil', 'hall_nord', 'b204']})
    assert texte == 'en_route, vers b204, reste 12.5 m, par accueil → hall_nord → b204'
    assert commande.texte_etat({'etat': 'attente', 'cible': None, 'reste_m': None,
                                'itineraire': []}) == 'attente'
