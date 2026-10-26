"""Tests du choix des interfaces et de la configuration CycloneDDS du conteneur (docker/reseau.py).

Lancement : .venv-projet/bin/python -m pytest docker/tests
Les sorties de « ip -o -4 addr » sont fausses : rien ne touche au réseau de la machine.
"""
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

DOSSIER = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DOSSIER))
import reseau  # noqa: E402

# Le Jetson du G1 : réseau interne sur eth0, docker0, le pont USB de L4T et le Wi-Fi
IP_JETSON = """\
1: lo    inet 127.0.0.1/8 scope host lo\\       valid_lft forever preferred_lft forever
2: eth0    inet 192.168.123.164/24 brd 192.168.123.255 scope global eth0\\       valid_lft forever preferred_lft forever
4: l4tbr0    inet 192.168.55.1/24 brd 192.168.55.255 scope global l4tbr0\\       valid_lft forever preferred_lft forever
5: docker0    inet 172.17.0.1/16 brd 172.17.255.255 scope global docker0\\       valid_lft forever preferred_lft forever
6: wlan0    inet 192.168.1.42/24 brd 192.168.1.255 scope global dynamic noprefixroute wlan0\\       valid_lft 86000sec preferred_lft 86000sec
"""
# Le PC de développement sans câble : seulement le Wi-Fi (cas du critère 16)
IP_PC = """\
1: lo    inet 127.0.0.1/8 scope host lo\\       valid_lft forever preferred_lft forever
3: wlo1    inet 192.168.1.23/24 brd 192.168.1.255 scope global dynamic noprefixroute wlo1\\       valid_lft 53364sec preferred_lft 53364sec
4: docker0    inet 172.17.0.1/16 brd 172.17.255.255 scope global docker0\\       valid_lft forever preferred_lft forever
"""
# Le PC au câble : eno2 en 192.168.123.99 (setup/robot.sh), avec une seconde adresse et un VLAN
IP_PC_CABLE = IP_PC + """\
2: eno2    inet 192.168.123.99/24 brd 192.168.123.255 scope global noprefixroute eno2\\       valid_lft forever preferred_lft forever
2: eno2    inet 192.168.123.98/24 scope global secondary eno2\\       valid_lft forever preferred_lft forever
7: eno2.5@eno2    inet 10.0.5.2/24 scope global eno2.5\\       valid_lft forever preferred_lft forever
"""
MODELE = (DOSSIER / 'cyclonedds.xml.modele').read_text(encoding='utf-8')


def interfaces_xml(texte):
    racine = ET.fromstring(texte)
    return [(i.get('name'), i.get('multicast'))
            for i in racine.iter('NetworkInterface')]


def test_lire_adresses():
    adresses = reseau.lire_adresses(IP_PC_CABLE)
    noms = [n for n, _ in adresses]
    assert noms == ['lo', 'wlo1', 'docker0', 'eno2', 'eno2', 'eno2.5']
    assert str(adresses[3][1]) == '192.168.123.99'
    assert reseau.lire_adresses('') == []
    assert reseau.lire_adresses('n\'importe quoi\n3: x inet pas_une_adresse\n') == []


def test_auto_trouve_le_reseau_du_robot():
    assert reseau.interfaces_robot(reseau.lire_adresses(IP_JETSON)) == ['eth0']
    assert reseau.interfaces_robot(reseau.lire_adresses(IP_PC_CABLE)) == ['eno2']   # sans doublon
    assert reseau.choisir_interfaces('auto', reseau.lire_adresses(IP_JETSON)) == ['eth0']
    assert reseau.choisir_interfaces(None, reseau.lire_adresses(IP_JETSON)) == ['eth0']   # défaut


def test_auto_sans_robot_refuse():
    with pytest.raises(reseau.ErreurReseau, match='réseau du robot introuvable') as e:
        reseau.choisir_interfaces('auto', reseau.lire_adresses(IP_PC))
    assert 'wlo1 (192.168.1.23)' in str(e.value)
    assert 'G1_INTERFACES=defaut' in str(e.value)


def test_defaut_et_liste():
    adresses = reseau.lire_adresses(IP_JETSON)
    assert reseau.choisir_interfaces('defaut', adresses) is None
    assert reseau.choisir_interfaces('eth0,wlan0', adresses) == ['eth0', 'wlan0']
    assert reseau.choisir_interfaces(' eth0 , ', adresses) == ['eth0']
    with pytest.raises(reseau.ErreurReseau, match='eth1 introuvable'):
        reseau.choisir_interfaces('eth0,eth1', adresses)
    for faux in ['eth0"/><x', 'a b', 'interface-bien-trop-longue', ',']:
        with pytest.raises(reseau.ErreurReseau):
            reseau.choisir_interfaces(faux, adresses)


def test_configuration_du_jetson():
    interfaces, uri, avertissements = reseau.preparer({'G1_INTERFACES': 'auto'}, IP_JETSON, MODELE,
                                                      sortie=None)
    assert interfaces == ['eth0'] and avertissements == []
    texte = reseau.config_cyclonedds(['eth0'], modele=MODELE)
    assert interfaces_xml(texte) == [('eth0', 'default')]
    assert '<Discovery>' not in texte and '@' not in texte
    racine = ET.fromstring(texte)
    assert racine.find('Domain').get('Id') == 'any'


def test_wifi_et_pairs(tmp_path):
    sortie = tmp_path / 'cyclonedds.xml'
    env = {'G1_INTERFACES': 'auto', 'G1_WIFI': 'wlan0', 'G1_PAIRS': '192.168.1.50, 192.168.1.51'}
    interfaces, uri, avertissements = reseau.preparer(env, IP_JETSON, MODELE, str(sortie))
    assert interfaces == ['eth0', 'wlan0'] and avertissements == []
    assert uri == f'file://{sortie}'
    texte = sortie.read_text()
    assert interfaces_xml(texte) == [('eth0', 'default'), ('wlan0', 'false')]
    racine = ET.fromstring(texte)
    decouverte = racine.find('Domain/Discovery')
    assert [p.get('address') for p in decouverte.iter('Peer')] == ['192.168.1.50', '192.168.1.51']
    assert decouverte.find('MaxAutoParticipantIndex').text == '100'
    assert decouverte.find('ParticipantIndex').text == 'auto'
    assert not (tmp_path / 'cyclonedds.xml.tmp').exists()


def test_wifi_absent_et_pairs_faux():
    interfaces, _, avertissements = reseau.preparer(
        {'G1_INTERFACES': 'auto', 'G1_WIFI': 'wlan9'}, IP_JETSON, MODELE, sortie=None)
    assert interfaces == ['eth0']
    assert any('wlan9 introuvable' in a for a in avertissements)
    with pytest.raises(reseau.ErreurReseau, match='n\'est pas une adresse IP'):
        reseau.preparer({'G1_INTERFACES': 'auto', 'G1_PAIRS': '192.168.1.300'}, IP_JETSON, MODELE, None)
    with pytest.raises(reseau.ErreurReseau):
        reseau.preparer({'G1_INTERFACES': 'auto', 'G1_WIFI': 'wlan0"'}, IP_JETSON, MODELE, None)


def test_defaut_n_ecrit_rien_et_efface_l_ancien(tmp_path):
    sortie = tmp_path / 'cyclonedds.xml'
    sortie.write_text('ancienne configuration')
    interfaces, uri, avertissements = reseau.preparer(
        {'G1_INTERFACES': 'defaut', 'G1_WIFI': 'wlan0'}, IP_PC, MODELE, str(sortie))
    assert interfaces == [] and uri is None and not sortie.exists()
    assert any('ignorés' in a for a in avertissements)


def test_ligne_de_commande(tmp_path):
    """Comme demarrer.sh : sortie « interfaces=… / uri=… », code 1 sans réseau du robot."""
    ip = tmp_path / 'ip.txt'
    sortie = tmp_path / 'c.xml'

    def lancer(texte_ip, **env):
        ip.write_text(texte_ip)
        return subprocess.run([sys.executable, str(DOSSIER / 'reseau.py'), 'cyclonedds', '--ip', str(ip),
                               '--sortie', str(sortie), '--modele', str(DOSSIER / 'cyclonedds.xml.modele')],
                              capture_output=True, text=True, env={'PATH': '/usr/bin:/bin', **env})

    r = lancer(IP_JETSON, G1_INTERFACES='auto')
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ['interfaces=eth0', f'uri=file://{sortie}']
    assert interfaces_xml(sortie.read_text()) == [('eth0', 'default')]
    r = lancer(IP_PC)                           # auto par défaut, sans 192.168.123.x
    assert r.returncode == 1
    assert 'réseau du robot introuvable' in r.stderr
    r = lancer(IP_PC, G1_INTERFACES='defaut')
    assert r.returncode == 0 and r.stdout.splitlines() == ['interfaces=', 'uri=']
