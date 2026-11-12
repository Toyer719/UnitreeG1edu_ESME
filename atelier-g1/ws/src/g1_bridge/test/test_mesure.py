"""
Mesures de la séance 2 (g1_bridge/mesure.py) : calculs sans ROS, puis la commande en vrai.

Le robot simulé du test répond aux 7105 du pont avec un retard pur et un premier ordre, et publie
son odométrie : la mesure doit retrouver le retard, la vitesse et le dépassement.
"""
import json
import math
import os
import subprocess
import sys
import threading
import time

import pytest

from g1_bridge.mesure import analyser, angle_normal, parcouru, texte_mesures, vitesses


def robot_simule(consigne, debut, fin, retard, tau, duree=6.0, pas=0.02, rotation=False):
    """Poses [(t, x, y, cap)] d'un robot qui suit un échelon (retard pur, puis premier ordre)."""
    poses, x, cap, v = [], 0.0, 0.0, 0.0
    t = 0.0
    while t < duree:
        commande = consigne if debut + retard <= t < fin + retard else 0.0
        v += (commande - v) * (1.0 - math.exp(-pas / tau))
        if rotation:
            cap = angle_normal(cap + v * pas)
        else:
            x += v * pas
        poses.append((t, x, 0.0, cap))
        t += pas
    return poses


def test_retard_montee_vitesse_et_depassement():
    retard, tau = 0.3, 0.2
    poses = robot_simule(0.2, 1.0, 3.0, retard, tau)
    m = analyser(poses, t_ordre=1.0, t_fin_ordre=3.0, t_dernier_envoi=3.0)
    assert m['vitesse'] == pytest.approx(0.2, abs=0.01)
    assert m['retard_s'] == pytest.approx(retard + tau * math.log(2), abs=0.05)
    assert m['montee_s'] == pytest.approx(tau * math.log(9), abs=0.06)
    # après le dernier ordre : retard puis décroissance, environ v × (retard + tau)
    assert m['depassement'] == pytest.approx(0.2 * (retard + tau), abs=0.02)
    assert m['arret_s'] == pytest.approx(retard + tau * math.log(10), abs=0.08)
    assert m['parcouru'] == pytest.approx(0.4, abs=0.03)


def test_rotation():
    poses = robot_simule(0.3, 0.5, 2.5, 0.2, 0.2, rotation=True)
    m = analyser(poses, 0.5, 2.5, 2.5, rotation=True)
    assert m['vitesse'] == pytest.approx(0.3, abs=0.015)
    assert m['depassement'] == pytest.approx(0.3 * 0.4, abs=0.02)
    assert m['parcouru'] == pytest.approx(0.6, abs=0.03)


def test_robot_qui_ne_bouge_pas():
    """Sous le seuil de marche : aucune vitesse, retard inconnu, rien ne plante."""
    poses = [(i * 0.02, 0.0, 0.0, 0.0) for i in range(200)]
    m = analyser(poses, 1.0, 2.0, 2.0)
    assert m['vitesse'] == 0.0 and m['retard_s'] is None and m['parcouru'] == 0.0
    texte = texte_mesures(m, consigne=0.1)
    assert 'retard (premier ordre → moitié de la vitesse) : inconnu\n' in texte
    assert 'inconnu s' not in texte and 'inconnu m' not in texte     # pas d'unité sans valeur
    assert 'consigne demandée : 0,10 m/s' in texte
    assert texte_mesures(m, rotation=True).endswith('parcouru en tout : 0,000 rad (0,0°)')


def test_vitesses_et_parcouru():
    poses = [(i * 0.02, 0.01 * i, 0.0, 0.0) for i in range(100)]          # 0,5 m/s
    assert all(v == pytest.approx(0.5) and w == 0.0 for _, v, w in vitesses(poses))
    assert parcouru(poses, 1.0) == pytest.approx(0.99 - 0.5, abs=0.011)
    tour = [(i * 0.1, 0.0, 0.0, angle_normal(0.1 * i)) for i in range(80)]  # passe par ±π
    assert parcouru(tour, 0.0, rotation=True) == pytest.approx(7.9, abs=1e-6)


def test_texte_en_francais():
    m = {'vitesse': 0.2, 'retard_s': 0.43, 'montee_s': 0.4, 'arret_s': 0.75,
         'depassement': 0.1, 'parcouru': 0.5}
    texte = texte_mesures(m, rotation=True, consigne=0.3)
    assert 'vitesse atteinte : 0,200 rad/s' in texte and '(5,7°)' in texte
    assert 'arrêt (dernier /cmd_vel → arrêté) : 0,75 s' in texte


# ---------------------------------------------------------------- en vrai, avec le pont

def test_mesure_d_un_echelon_par_le_pont():
    """Pont (portique) + robot simulé du test : la commande retrouve le retard et la vitesse."""
    pytest.importorskip('rclpy')
    from outils_pont import FauxRobot, NoeudLance
    from nav_msgs.msg import Odometry
    from rclpy.qos import qos_profile_sensor_data
    robot = FauxRobot(nom='robot_mesure')
    pub = robot.noeud.create_publisher(Odometry, '/state_estimator/odom_pelvis',
                                       qos_profile_sensor_data)
    actif, etat = [True], {'x': 0.0, 'v': 0.0}
    retard, tau = 0.25, 0.15

    def simuler():
        while actif[0]:
            t = time.monotonic()
            with robot.verrou:
                requetes = list(robot.requetes)
            consigne = 0.0
            for t_req, m in requetes:
                p = json.loads(m.parameter)
                if t_req + retard <= t < t_req + retard + p['duration']:
                    consigne = p['velocity'][0]
            etat['v'] += (consigne - etat['v']) * (1.0 - math.exp(-0.02 / tau))
            etat['x'] += etat['v'] * 0.02
            o = Odometry()
            o.pose.pose.position.x = etat['x']
            o.pose.pose.orientation.w = 1.0
            pub.publish(o)
            time.sleep(0.02)
    fil = threading.Thread(target=simuler, daemon=True)
    fil.start()
    pont = NoeudLance('pont_mesure', ['-p', 'exiger_reperage:=false']).demarrer()
    try:
        robot.attendre_etat('pret', delai=10.0)
        env = dict(os.environ)
        sortie = subprocess.run([sys.executable, '-m', 'g1_bridge.mesure', 'marche', '--vx', '0.1',
                                 '--duree', '1.5'], capture_output=True, text=True, timeout=40,
                                env=env)
        texte = sortie.stdout + sortie.stderr
        assert sortie.returncode == 0, texte
        assert "7105 envoyé par le pont : (0.2, 0.0, 0.0)" in texte          # vitesse minimale
        ligne = next(x for x in texte.splitlines() if x.startswith('vitesse atteinte'))
        assert abs(float(ligne.split(':')[1].split()[0].replace(',', '.')) - 0.2) < 0.03, texte
        ligne = next(x for x in texte.splitlines() if x.startswith('retard'))
        retard_mesure = float(ligne.split(':')[1].split()[0].replace(',', '.'))
        assert retard + 0.05 <= retard_mesure <= retard + tau + 0.25, texte
        # trop vite : refusé sans rien envoyer
        refus = subprocess.run([sys.executable, '-m', 'g1_bridge.mesure', 'marche', '--vx', '0.5'],
                               capture_output=True, text=True, timeout=20, env=env)
        assert refus.returncode == 2 and 'mesure refusée' in refus.stderr
    finally:
        actif[0] = False
        fil.join(timeout=2.0)
        pont.arreter()
        robot.fermer()
