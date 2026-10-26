"""
Tests ROS 2 des nœuds detecteur_personnes et faux_visiteur (vague 4), sans Gazebo.

Chaque nœud tourne dans un sous-processus (python3 -m), sur ROS_DOMAIN_ID (33 par défaut) :
  - detecteur_personnes reçoit un nuage fabriqué (une personne derrière le robot, un mur) sur
    /points, dans base_link, et publie /personnes/lidar (schéma personnes) ;
  - faux_visiteur reçoit un faux /pietons/etat et une fausse vérité /odom, et publie
    /pietons/consigne (schéma pietons_consigne) selon le mode de /faux_visiteur/mode.

  ROS_DOMAIN_ID=33 python3 -m pytest ~/robot-g1/ws/src/g1_nav/test/test_noeuds_personnes.py -v
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from atelier import RACINE
from atelier.lieu import valider_message
import pytest

rclpy = pytest.importorskip('rclpy')
from nav_msgs.msg import Odometry  # noqa: E402
from std_msgs.msg import String  # noqa: E402

PAQUET = Path(__file__).resolve().parent.parent
DOMAINE = int(os.environ.get('ROS_DOMAIN_ID') or 33)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_personnes import lancer, personne  # noqa: E402


def lancer_noeud(module, *parametres):
    env = dict(os.environ, ROS_DOMAIN_ID=str(DOMAINE), PYTHONUNBUFFERED='1')
    env['PYTHONPATH'] = os.pathsep.join([str(PAQUET), str(RACINE), env.get('PYTHONPATH', '')])
    commande = [sys.executable, '-m', module, '--ros-args']
    for p in parametres:
        commande += ['-p', p]
    return subprocess.Popen(commande, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, start_new_session=True)


class Ecoute:
    def __init__(self):
        self.contexte = rclpy.Context()
        rclpy.init(context=self.contexte, domain_id=DOMAINE)
        self.noeud = rclpy.create_node('test_personnes', context=self.contexte)
        self.executeur = rclpy.executors.SingleThreadedExecutor(context=self.contexte)
        self.executeur.add_node(self.noeud)
        self.recus = {}

    def ecouter(self, sujet):
        self.recus[sujet] = []
        self.noeud.create_subscription(String, sujet,
                                       lambda m: self.recus[sujet].append(json.loads(m.data)), 10)

    def attendre(self, condition, delai_s, action=None):
        fin = time.monotonic() + delai_s
        while time.monotonic() < fin:
            if action is not None:
                action()
            self.executeur.spin_once(timeout_sec=0.1)
            if condition():
                return True
        return False

    def fermer(self):
        self.executeur.shutdown()
        self.noeud.destroy_node()
        rclpy.shutdown(context=self.contexte)


def arreter(processus):
    os.killpg(processus.pid, signal.SIGINT)
    sortie, erreurs = processus.communicate(timeout=10)
    assert 'Traceback' not in erreurs, erreurs
    return sortie + erreurs


def test_detecteur_publie_les_personnes():
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import PointCloud2
    from g1_nav.nuages import creer_nuage
    noeud = lancer_noeud('g1_nav.personnes')
    ecoute = Ecoute()
    ecoute.ecouter('/personnes/lidar')
    pub = ecoute.noeud.create_publisher(PointCloud2, '/points', qos_profile_sensor_data)
    nuage = creer_nuage(lancer([personne(-1.2, 0.0), ('boite', -5, 1.5, 5, 1.65, 2.5)]),
                        'base_link')
    try:
        vus = ecoute.recus['/personnes/lidar']
        assert ecoute.attendre(lambda: any(m['personnes'] for m in vus), 20.0,
                               action=lambda: pub.publish(nuage)), 'rien sur /personnes/lidar'
        message = next(m for m in vus if m['personnes'])
        assert valider_message('personnes', message) == []
        assert message['source'] == 'lidar' and len(message['personnes']) == 1
        p = message['personnes'][0]
        assert p['derriere'] is True and 1.0 < p['distance_m'] < 1.4
    finally:
        ecoute.fermer()
        texte = arreter(noeud)
    assert 'détecteur de personnes prêt' in texte


def test_faux_visiteur_suit_puis_s_arrete():
    noeud = lancer_noeud('g1_nav.faux_visiteur', 'visiteur:=visiteur', 'verite:=/odom')
    ecoute = Ecoute()
    ecoute.ecouter('/pietons/consigne')
    ecoute.ecouter('/faux_visiteur/etat')
    pub_pietons = ecoute.noeud.create_publisher(String, '/pietons/etat', 10)
    pub_odom = ecoute.noeud.create_publisher(Odometry, '/odom', 10)
    pub_mode = ecoute.noeud.create_publisher(String, '/faux_visiteur/mode', 10)
    etat = {'version': 1, 'temps_sim': 1.0, 'pietons': [
        {'id': 'visiteur', 'x': 0.0, 'y': 0.0, 'theta': 0.0, 'vx': 0.0, 'vy': 0.0, 'rayon_m': 0.25,
         'etat': 'pilote'}]}

    def publier():
        pub_pietons.publish(String(data=json.dumps(etat)))
        o = Odometry()
        o.pose.pose.position.x = 4.0            # le robot est à 4 m devant le visiteur
        o.twist.twist.linear.x = 0.4
        pub_odom.publish(o)
    try:
        consignes = ecoute.recus['/pietons/consigne']
        assert ecoute.attendre(lambda: consignes and consignes[-1]['vx'] > 1.0, 20.0,
                               action=publier), f'pas de consigne de suivi : {consignes[-3:]}'
        assert valider_message('pietons_consigne', consignes[-1]) == []
        assert consignes[-1]['id'] == 'visiteur' and abs(consignes[-1]['vy']) < 0.05
        pub_mode.publish(String(data='arreter'))
        assert ecoute.attendre(lambda: consignes[-1]['vx'] == 0.0, 5.0, action=publier)
        etats = ecoute.recus['/faux_visiteur/etat']
        assert ecoute.attendre(lambda: etats and etats[-1]['mode'] == 'arreter', 3.0,
                               action=publier)
        assert etats[-1]['distance_m'] == pytest.approx(4.0, abs=0.01)
    finally:
        ecoute.fermer()
        texte = arreter(noeud)
    assert 'faux visiteur prêt' in texte
