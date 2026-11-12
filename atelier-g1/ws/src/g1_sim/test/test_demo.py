"""
Simulation du lieu demo, sur une copie dans un dossier temporaire (jamais dans lieux/demo).

La copie garde mondes/rdc.sdf et cartes/rdc.yaml s'ils existent déjà ; sinon, atelier.monde les
génère dans la copie. Vérifie :
  - le robot apparaît à depart_robot (l'accueil, 2,5 ; 10), avec le cap demandé (0,5 rad) ;
  - /points publie plus de 5 messages par seconde ;
  - les repères map, odom, base_link et lidar sont cohérents : les points du LiDAR entre 0,15 et
    1,45 m de haut, ramenés dans odom puis dans map (map → odom = identité en simulation),
    tombent sur les pixels occupés de la carte cartes/rdc.pgm ; avant et après un quart de tour.
Ignoré si le paquet atelier n'est pas disponible.
"""
import math
import time

import numpy as np
import pytest

from outils_sim import Ecoute, Simulation, lidar_vers_odom, points_xyz, temps

lieu_api = pytest.importorskip('atelier.lieu')
from atelier.lieu import conversions  # noqa: E402

TOLERANCE_PIXELS = 2      # 0,1 m : un point de mur est à 2 pixels au plus d'un pixel occupé
CAP_DEPART = 0.5          # rad, remplace le cap de depart_robot dans la copie


@pytest.fixture(scope='module')
def sim_demo(tmp_path_factory):
    copie = lieu_api.copier_lieu('demo', tmp_path_factory.mktemp('lieu_demo') / 'demo')
    if not (lieu_api.chemin_sdf(copie, 'rdc').is_file()
            and lieu_api.chemin_carte(copie, 'rdc').is_file()):
        monde_api = pytest.importorskip('atelier.monde')
        monde_api.generer(copie, 'rdc')
    # Cap de départ non nul (dans la copie seulement), pour vérifier aussi l'orientation
    monde = lieu_api.charger_monde(copie, 'rdc')
    monde.depart_robot.theta = CAP_DEPART
    lieu_api.enregistrer_monde(copie, 'rdc', monde)
    simulation = Simulation(copie, 'rdc', nom='demo')
    simulation.demarrer()
    ecoute = Ecoute('test_g1_sim_demo')
    try:
        ecoute.attendre_pret(simulation)
        yield ecoute, copie
    finally:
        ecoute.fermer()
        simulation.arreter()


def _occupes_elargis(image, marge):
    """Masque des pixels à marge pixels au plus d'un pixel occupé (0)."""
    occupe = image == 0
    resultat = occupe.copy()
    for dl in range(-marge, marge + 1):
        for dc in range(-marge, marge + 1):
            resultat |= np.roll(np.roll(occupe, dl, axis=0), dc, axis=1)
    return resultat


def _accord_avec_la_carte(ecoute, dossier):
    """Part des points de la tranche 0,15–1,45 m qui tombent sur un obstacle de la carte."""
    info, image = lieu_api.charger_carte(lieu_api.chemin_carte(dossier, 'rdc'))
    proches = _occupes_elargis(image, TOLERANCE_PIXELS)
    monde = lieu_api.charger_monde(dossier, 'rdc')
    nuage = ecoute.dernier_nuage()
    x, y, theta, _ = ecoute.pose()
    p = lidar_vers_odom(points_xyz(nuage), x, y, theta)
    p = p[(p[:, 2] > 0.15) & (p[:, 2] < 1.45)]
    # Les piétons ne sont pas sur la carte : on retire les points proches d'eux
    try:
        from atelier.monde import position_pieton
        for pieton in monde.pietons:
            px, py, _ = position_pieton(pieton, temps(nuage.header))
            p = p[np.hypot(p[:, 0] - px, p[:, 1] - py) > 0.7]
    except ImportError:
        pass
    colonnes, lignes = conversions.monde_vers_pixel(p[:, 0], p[:, 1], info)
    dedans = (colonnes >= 0) & (colonnes < info.largeur) & (lignes >= 0) & (lignes < info.hauteur)
    accord = np.zeros(len(p), dtype=bool)
    accord[dedans] = proches[lignes[dedans], colonnes[dedans]]
    return accord.mean(), len(p)


def test_depart_a_l_accueil(sim_demo):
    ecoute, dossier = sim_demo
    depart = lieu_api.charger_monde(dossier, 'rdc').depart_robot
    x, y, theta, _ = ecoute.pose()
    assert (x, y) == pytest.approx((depart.x, depart.y), abs=0.03)
    assert abs(theta - depart.theta) < 0.03


def test_points_demo(sim_demo):
    ecoute, _ = sim_demo
    debut = time.monotonic()
    time.sleep(2.0)
    frequence = len(ecoute.nuages_depuis(debut)) / 2.0
    print(f'/points : {frequence:.1f} messages par seconde')
    assert frequence > 5.0


def test_points_sur_la_carte(sim_demo):
    """Repères map, odom, base_link et lidar cohérents : le LiDAR voit les murs de la carte."""
    ecoute, dossier = sim_demo
    part, nombre = _accord_avec_la_carte(ecoute, dossier)
    print(f'au départ : {100 * part:.1f} % de {nombre} points sur un obstacle de la carte')
    assert nombre > 200 and part > 0.95

    # Un quart de tour sur place (wz = 0,5 rad/s pendant π s), puis la même vérification
    avant, apres = ecoute.rouler(wz=0.5, duree=math.pi)
    tour = math.remainder(apres[2] - avant[2], 2 * math.pi)
    print(f'rotation : {math.degrees(tour):.1f}° ; déplacement '
          f'{math.hypot(apres[0] - avant[0], apres[1] - avant[1]):.3f} m')
    assert tour == pytest.approx(math.pi / 2, abs=0.05)
    time.sleep(0.5)
    part, nombre = _accord_avec_la_carte(ecoute, dossier)
    print(f'après le quart de tour : {100 * part:.1f} % de {nombre} points sur un obstacle')
    assert nombre > 200 and part > 0.95
