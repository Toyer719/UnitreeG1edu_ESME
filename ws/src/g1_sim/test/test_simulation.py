"""
Tests de la simulation sans fenêtre, dans le couloir de test (worlds/couloir.sdf).

  - /points publie plus de 5 messages par seconde, dans le repère lidar, sans voir le robot ;
  - les repères odom, base_link et lidar sont cohérents avec le monde (odom = monde = map) ;
  - /cmd_vel vx = 0,3 pendant 3 s fait avancer /odom d'environ 0,9 m ;
  - le robot ne traverse ni la boîte ni un mur.

Les tests partagent une seule simulation et s'enchaînent dans l'ordre du fichier : le robot part
de (1 ; 0), avance de 0,9 m, roule vers la boîte (x = 5), puis vers le mur nord (y = 1).
Gazebo met 5 à 10 s à démarrer ; compter environ 1 min pour tout le fichier.
"""
import math
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pytest

from outils_sim import (Ecoute, Simulation, distance_boite, lidar_vers_odom, lieu_couloir,
                        points_xyz)

# Le couloir de worlds/couloir.sdf : murs de 0,15 m centrés sur y = ±1, x = 0 et x = 10
MURS = [((5.0, -1.0, 1.25), (10.0, 0.15, 2.5)), ((5.0, 1.0, 1.25), (10.0, 0.15, 2.5)),
        ((0.0, 0.0, 1.25), (0.15, 2.0, 2.5)), ((10.0, 0.0, 1.25), (0.15, 2.0, 2.5))]
BOITE = ((5.0, 0.0, 0.5), (0.5, 0.5, 1.0))

# Dimensions du robot lues dans son modèle (collision aux mesures du G1, position du LiDAR)
_LIEN = ET.parse(Path(__file__).resolve().parent.parent / 'models' / 'g1_proxy' /
                 'model.sdf').getroot().find('model/link')
_TAILLE = [float(v) for v in _LIEN.findtext('collision/geometry/box/size').split()]
_CENTRE = [float(v) for v in _LIEN.findtext('collision/pose').split()]
DEMI_LONGUEUR_ROBOT = _TAILLE[0] / 2 + _CENTRE[0]   # de base_link à l'avant, le long de x
DEMI_LARGEUR_ROBOT = _TAILLE[1] / 2 + _CENTRE[1]    # de base_link au côté gauche, le long de y
POSE_LIDAR = [float(v) for v in _LIEN.findtext("sensor[@type='gpu_lidar']/pose").split()[:3]]


@pytest.fixture(scope='module')
def sim(tmp_path_factory):
    """Lance la simulation du couloir et un nœud d'écoute ; arrête tout à la fin."""
    lieu = lieu_couloir(tmp_path_factory.mktemp('lieu_couloir'))
    simulation = Simulation(lieu, 'rdc', nom='couloir')
    debut = time.monotonic()
    simulation.demarrer()
    ecoute = Ecoute()
    try:
        ecoute.attendre_pret(simulation)
        ecoute.duree_demarrage = time.monotonic() - debut
        yield ecoute
    finally:
        ecoute.fermer()
        simulation.arreter()


def test_demarrage_moins_de_30_s(sim):
    """Du lancement à /odom et /points : moins de 30 s (critère 3 de la recette)."""
    print(f'simulation prête en {sim.duree_demarrage:.1f} s')
    assert sim.duree_demarrage < 30.0


def test_depart_robot(sim):
    """Le robot apparaît à depart_robot de mondes/rdc.monde.yaml : (1 ; 0), cap 0."""
    x, y, theta, _ = sim.pose()
    assert abs(x - 1.0) < 0.02 and abs(y) < 0.02 and abs(theta) < 0.02, (x, y, theta)


def test_points_plus_de_5_par_seconde(sim):
    """/points : plus de 5 messages par seconde (heure murale), repère lidar, 360 × 16 points."""
    debut = time.monotonic()
    time.sleep(3.0)
    nuages = sim.nuages_depuis(debut)
    frequence = len(nuages) / 3.0
    print(f'/points : {frequence:.1f} messages par seconde')
    assert frequence > 5.0
    dernier = nuages[-1]
    assert dernier.header.frame_id == 'lidar'
    assert dernier.width * dernier.height == 360 * 16
    # Le LiDAR ne voit pas le robot lui-même (masque de visibilité) : rien à moins de 0,3 m
    p = points_xyz(dernier)
    assert len(p) > 1000
    assert (np.linalg.norm(p, axis=1) < 0.3).sum() == 0


def test_reperes_coherents(sim):
    """Repères : odom → base_link = /odom, base_link → lidar = le MID-360, points sur le monde."""
    # base_link → lidar, publié par robot_state_publisher
    assert sim.attendre(lambda: ('base_link', 'lidar') in sim.tf_statique, 10.0)
    t = sim.tf_statique[('base_link', 'lidar')].transform
    position = (t.translation.x, t.translation.y, t.translation.z)
    assert position == pytest.approx(tuple(POSE_LIDAR), abs=1e-6)
    assert t.rotation.w == pytest.approx(1.0, abs=1e-6)

    # odom → base_link, publié par le plugin d'odométrie (via le pont), identique à /odom
    assert sim.attendre(lambda: ('odom', 'base_link') in sim.tf, 10.0)
    tf = sim.tf[('odom', 'base_link')].transform
    x, y, theta, _ = sim.pose()
    assert (tf.translation.x, tf.translation.y) == pytest.approx((x, y), abs=0.01)
    assert sim.derniere_odom().header.frame_id == 'odom'
    assert sim.derniere_odom().child_frame_id == 'base_link'

    # Les points, ramenés dans odom par la chaîne odom → base_link → lidar, tombent sur le sol,
    # les murs ou la boîte : odom coïncide donc avec le repère du monde (et de la carte)
    p = lidar_vers_odom(points_xyz(sim.dernier_nuage()), x, y, theta, hauteur=t.translation.z)
    distances = [np.abs(p[:, 2])] + [distance_boite(p, c, s) for c, s in MURS + [BOITE]]
    ecart = np.min(np.stack(distances), axis=0)
    print(f'{len(p)} points ; écart à la surface la plus proche : '
          f'médiane {np.median(ecart):.3f} m, 95 % sous {np.percentile(ecart, 95):.3f} m')
    assert np.percentile(ecart, 95) < 0.05
    # La boîte est vue là où elle est : des points sur sa face ouest (x = 4,75)
    face_ouest = (np.abs(p[:, 0] - 4.75) < 0.05) & (np.abs(p[:, 1]) < 0.25) & (p[:, 2] < 1.0)
    assert face_ouest.sum() >= 3


def test_cmd_vel_avance_de_0_9_m(sim):
    """Commande vx = 0,3 m/s pendant 3 s (temps simulé) : /odom avance d'environ 0,9 m."""
    avant, apres = sim.rouler(vx=0.3, duree=3.0)
    dx, dy = apres[0] - avant[0], apres[1] - avant[1]
    print(f'avance de {dx:.3f} m (dérive latérale {dy:+.3f} m, '
          f'cap {math.degrees(apres[2]):+.1f}°)')
    assert dx == pytest.approx(0.9, abs=0.05)
    assert abs(dy) < 0.02
    assert abs(apres[2]) < 0.02


def test_ne_traverse_pas_la_boite(sim):
    """Commande vx = 0,5 m/s pendant 8 s vers la boîte : arrêt contre sa face ouest (x = 4,75)."""
    avant, apres = sim.rouler(vx=0.5, duree=8.0)
    contact = BOITE[0][0] - BOITE[1][0] / 2 - DEMI_LONGUEUR_ROBOT
    print(f'arrêté en x = {apres[0]:.3f} m (contact attendu en {contact:.3f} m)')
    assert apres[0] < contact + 0.03
    assert apres[0] > contact - 0.15
    assert abs(apres[2]) < 0.1


def test_ne_traverse_pas_un_mur(sim):
    """Commande vy = 0,5 m/s pendant 4 s vers le mur nord (y = 1) : arrêt contre le mur."""
    avant, apres = sim.rouler(vy=0.5, duree=4.0)
    contact = 1.0 - 0.15 / 2 - DEMI_LARGEUR_ROBOT
    print(f'arrêté en y = {apres[1]:.3f} m (contact attendu en {contact:.3f} m)')
    assert apres[1] < contact + 0.03
    assert apres[1] > contact - 0.15
    assert abs(apres[2]) < 0.1
    # Et il ne s'est pas enfoncé avec le temps : toujours contre le mur une seconde plus tard
    time.sleep(1.0)
    assert sim.pose()[1] < contact + 0.03
