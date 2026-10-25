"""
Test du nœud ROS 2 du guide avec le moteur factice : /guide/aller, /guide/stop, /guide/etat.

Sans Gazebo ni Nav2. Le nœud tourne dans un sous-processus, sur ROS_DOMAIN_ID (33 par défaut).
Il faut rclpy (source ~/robot-g1/setup/env.sh) ; sinon le test est sauté.

  ROS_DOMAIN_ID=33 python3 -m pytest ~/robot-g1/ws/src/g1_nav/test/test_noeud_guide.py -v
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from atelier import RACINE
from atelier.lieu import copier_lieu
import pytest

rclpy = pytest.importorskip('rclpy')
from std_msgs.msg import Empty, String  # noqa: E402

PAQUET = Path(__file__).resolve().parent.parent
DOMAINE = int(os.environ.get('ROS_DOMAIN_ID') or 33)


def environnement():
    env = dict(os.environ, ROS_DOMAIN_ID=str(DOMAINE), PYTHONUNBUFFERED='1')
    env['PYTHONPATH'] = os.pathsep.join([str(PAQUET), str(RACINE), env.get('PYTHONPATH', '')])
    return env


def lancer_guide(dossier, moteur='factice'):
    return subprocess.Popen(
        [sys.executable, '-m', 'g1_nav.guide', '--ros-args', '-p', f'lieu:={dossier}',
         '-p', 'etage:=rdc', '-p', f'moteur:={moteur}', '-p', 'vitesse_factice:=4.0'],
        env=environnement(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        start_new_session=True)


class Ecoute:
    """Nœud de test : publie les commandes et garde les états reçus."""

    def __init__(self):
        self.contexte = rclpy.Context()
        rclpy.init(context=self.contexte, domain_id=DOMAINE)
        self.noeud = rclpy.create_node('test_guide', context=self.contexte)
        self.executeur = rclpy.executors.SingleThreadedExecutor(context=self.contexte)
        self.executeur.add_node(self.noeud)
        self.pub_aller = self.noeud.create_publisher(String, '/guide/aller', 10)
        self.pub_stop = self.noeud.create_publisher(Empty, '/guide/stop', 10)
        self.etats = []
        self.noeud.create_subscription(String, '/guide/etat',
                                       lambda m: self.etats.append(json.loads(m.data)), 10)

    def attendre(self, condition, delai_s):
        fin = time.monotonic() + delai_s
        while time.monotonic() < fin:
            self.executeur.spin_once(timeout_sec=0.1)
            if condition():
                return True
        return False

    def fermer(self):
        self.executeur.shutdown()
        self.noeud.destroy_node()
        rclpy.shutdown(context=self.contexte)


@pytest.fixture
def dossier(tmp_path):
    return copier_lieu(RACINE / 'lieux' / 'demo', tmp_path / 'demo')


def test_aller_stop_etat(dossier):
    guide = lancer_guide(dossier)
    ecoute = Ecoute()
    try:
        assert ecoute.attendre(lambda: ecoute.etats and ecoute.pub_aller.get_subscription_count(),
                               20.0), 'le guide ne publie pas /guide/etat'
        assert ecoute.etats[-1] == {'etat': 'attente', 'cible': None, 'reste_m': None,
                                    'itineraire': []}
        # accueil → b204 : 21,5 m à 4 m/s
        ecoute.pub_aller.publish(String(data='b204'))
        assert ecoute.attendre(lambda: ecoute.etats[-1]['etat'] == 'arrive', 20.0)
        vus = [e['etat'] for e in ecoute.etats]
        assert 'en_route' in vus and vus.index('en_route') < vus.index('arrive')
        fin = ecoute.etats[-1]
        assert set(fin) == {'etat', 'cible', 'reste_m', 'itineraire'}
        assert fin['cible'] == 'b204' and fin['reste_m'] == 0.0
        assert fin['itineraire'] == ['accueil', 'hall_nord', 'amphi', 'couloir_nord_1', 'b204']
        # Cible inconnue
        ecoute.pub_aller.publish(String(data='grenier'))
        assert ecoute.attendre(lambda: ecoute.etats[-1]['etat'] == 'echec', 5.0)
        assert ecoute.etats[-1]['cible'] == 'grenier'
        # Départ puis arrêt
        ecoute.pub_aller.publish(String(data='cdi'))
        assert ecoute.attendre(lambda: ecoute.etats[-1]['etat'] == 'en_route', 5.0)
        ecoute.pub_stop.publish(Empty())
        assert ecoute.attendre(lambda: ecoute.etats[-1]['etat'] == 'attente', 5.0)
        assert ecoute.etats[-1]['cible'] is None
    finally:
        ecoute.fermer()
        os.killpg(guide.pid, signal.SIGINT)
        sortie, erreurs = guide.communicate(timeout=10)
    assert guide.returncode == 0, erreurs
    assert 'Traceback' not in erreurs
    assert 'guide prêt' in sortie + erreurs


@pytest.mark.skipif((PAQUET / 'g1_nav' / 'moteur_unitree.py').exists(),
                    reason='moteur_unitree.py existe : l\'agent Scan l\'a écrit')
def test_moteur_unitree_absent(dossier):
    guide = lancer_guide(dossier, moteur='unitree')
    sortie, erreurs = guide.communicate(timeout=20)
    assert guide.returncode == 1
    assert 'MoteurUnitree est absent' in erreurs and 'Traceback' not in erreurs


def test_lieu_introuvable(tmp_path):
    guide = lancer_guide(tmp_path / 'nulle_part')
    sortie, erreurs = guide.communicate(timeout=20)
    assert guide.returncode == 1 and erreurs.startswith('guide : ')
    assert 'Traceback' not in erreurs
