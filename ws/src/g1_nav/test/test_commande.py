"""
Tests de la commande g1-guide, sans ROS : options et affichage de l'état.

  python3 -m pytest ~/robot-g1/ws/src/g1_nav/test/test_commande.py -v
"""
from g1_nav import commande
import pytest


def test_navigation_traduit_les_options(monkeypatch):
    monkeypatch.delenv('G1_VITESSE_MAX', raising=False)
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


def test_localisation_et_pont(monkeypatch):
    monkeypatch.delenv('G1_VITESSE_MAX', raising=False)
    lance = []
    monkeypatch.setattr(commande.os, 'execvp', lambda prog, args: lance.append(args))
    commande.main(['navigation', '--lieu', 'demo', '--etage', 'rdc', '--simu',
                   '--localisation', 'unitree'])
    assert lance[-1][-2:] == ['moteur:=nav2', 'localisation:=unitree']
    commande.main(['navigation', '--lieu', 'demo', '--etage', 'rdc', '--simu',
                   '--localisation', 'externe', '--pont', 'oui'])
    assert lance[-1][-2:] == ['localisation:=externe', 'pont:=true']
    commande.main(['navigation', '--lieu', 'demo', '--etage', 'rdc', '--pont', 'non'])
    assert lance[-1][-2:] == ['moteur:=nav2', 'pont:=false']
    with pytest.raises(SystemExit):
        commande.main(['navigation', '--lieu', 'demo', '--etage', 'rdc', '--pont', 'peut-etre'])


def test_texte_etat_avec_message():
    texte = commande.texte_etat({'etat': 'attente', 'cible': 'b204', 'reste_m': None,
                                 'itineraire': [], 'message': 'La navigation démarre.'})
    assert texte == 'attente, vers b204 : La navigation démarre.'


def test_vitesse_reduite(monkeypatch):
    """--vitesse-max, sinon la variable G1_VITESSE_MAX : argument vitesse_max:= du lancement."""
    lance = []
    monkeypatch.setattr(commande.os, 'execvp', lambda prog, args: lance.append(args))
    monkeypatch.delenv('G1_VITESSE_MAX', raising=False)
    commande.main(['navigation', '--lieu', 'demo', '--etage', 'rdc', '--vitesse-max', '0.2'])
    assert lance[-1][-1] == 'vitesse_max:=0.2'
    monkeypatch.setenv('G1_VITESSE_MAX', '0.15')
    commande.main(['navigation', '--lieu', 'demo', '--etage', 'rdc'])
    assert lance[-1][-1] == 'vitesse_max:=0.15'
    commande.main(['navigation', '--lieu', 'demo', '--etage', 'rdc', '--vitesse-max', '0.3'])
    assert lance[-1][-1] == 'vitesse_max:=0.3'
