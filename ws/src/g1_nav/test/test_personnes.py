"""
Tests du détecteur de personnes au LiDAR (g1_nav/personnes.py), sans ROS.

Les nuages sont fabriqués par un petit lancer de rayons qui imite le LiDAR du robot proxy (16
nappes de −7° à +52°, un rayon par degré, à 1,245 m) sur des personnes (cylindres de 0,25 m de
rayon et 1,7 m de haut), des murs, des meubles et le sol.

  python3 -m pytest ~/robot-g1/ws/src/g1_nav/test/test_personnes.py -v
"""
import math

from atelier import RACINE
from atelier.lieu import copier_lieu, valider_message
from g1_nav.personnes import (CarteStatique, DetecteurPersonnes, etendue, masque_carte,
                              message_personnes, regrouper, vers_carte)
import numpy as np
import pytest

CAPTEUR = np.array([-0.004, 0.0, 1.245])


def lancer(objets, pose=(0.0, 0.0, 0.0), azimuts=360, nappes=16):
    """
    Nuage vu par le LiDAR du robot posé en pose (x, y, theta) de la scène, dans base_link.

    objets : ('cylindre', cx, cy, rayon, hauteur) ou ('boite', xmin, ymin, xmax, ymax, hauteur),
    dans le repère de la scène.
    """
    x0, y0, cap = pose
    c, s = math.cos(cap), math.sin(cap)
    origine = np.array([x0 + c * CAPTEUR[0], y0 + s * CAPTEUR[0], CAPTEUR[2]])
    az = np.linspace(-math.pi, math.pi, azimuts, endpoint=False)
    el = np.linspace(math.radians(-7), math.radians(52), nappes)
    a, e = np.meshgrid(az + cap, el)
    d = np.stack([np.cos(e) * np.cos(a), np.cos(e) * np.sin(a), np.sin(e)], axis=-1).reshape(-1, 3)
    t = np.full(len(d), np.inf)
    sol = d[:, 2] < -1e-9
    t[sol] = -origine[2] / d[sol, 2]
    for o in objets:
        if o[0] == 'cylindre':
            _, cx, cy, r, h = o
            ox, oy = origine[0] - cx, origine[1] - cy
            aa = d[:, 0] ** 2 + d[:, 1] ** 2
            bb = 2 * (ox * d[:, 0] + oy * d[:, 1])
            cc = ox * ox + oy * oy - r * r
            disc = bb * bb - 4 * aa * cc
            ok = (disc >= 0) & (aa > 1e-12)
            tt = np.full(len(d), np.inf)
            tt[ok] = (-bb[ok] - np.sqrt(disc[ok])) / (2 * aa[ok])
            z = origine[2] + tt * d[:, 2]
            tt[(tt <= 0) | (z < 0) | (z > h)] = np.inf
        else:
            _, xmin, ymin, xmax, ymax, h = o
            bas, haut = np.array([xmin, ymin, 0.0]), np.array([xmax, ymax, h])
            with np.errstate(divide='ignore', invalid='ignore'):
                t1 = (bas - origine) / d
                t2 = (haut - origine) / d
            tmin = np.nanmax(np.minimum(t1, t2), axis=1)
            tmax = np.nanmin(np.maximum(t1, t2), axis=1)
            tt = np.where((tmax >= tmin) & (tmax > 0), np.maximum(tmin, 0), np.inf)
        t = np.minimum(t, tt)
    garde = np.isfinite(t) & (t < 40)
    monde = origine + d[garde] * t[garde, None]
    # monde → base_link
    xb = c * (monde[:, 0] - x0) + s * (monde[:, 1] - y0)
    yb = -s * (monde[:, 0] - x0) + c * (monde[:, 1] - y0)
    return np.column_stack([xb, yb, monde[:, 2]])


def personne(x, y):
    return ('cylindre', x, y, 0.25, 1.7)


def test_une_personne_derriere():
    d = DetecteurPersonnes()
    vues = d.detecter(lancer([personne(-1.2, 0.0)]), 1.0)
    assert len(vues) == 1
    p = vues[0]
    assert p['derriere'] is True and abs(abs(p['angle_rad']) - math.pi) < 0.1
    assert 0.9 < p['distance_m'] < 1.2
    assert valider_message('personnes', message_personnes(vues, 1.0)) == []


@pytest.mark.parametrize('distance', [0.8, 2.0, 4.0, 6.0, 7.5])
def test_personnes_a_toutes_les_distances(distance):
    vues = DetecteurPersonnes().detecter(lancer([personne(distance, 0.6)]), 0.0)
    assert len(vues) == 1, vues
    assert vues[0]['derriere'] is False


def test_deux_personnes_cote_a_cote():
    """Un groupe en travers du couloir : centres à 1 m, trois personnes séparées."""
    vues = DetecteurPersonnes().detecter(
        lancer([personne(1.5, -1.0), personne(1.5, 0.0), personne(1.5, 1.0)]), 0.0)
    assert len(vues) == 3
    assert sorted(round(p['y']) for p in vues) == [-1, 0, 1]


def test_murs_meubles_et_sol_ne_sont_pas_des_personnes():
    objets = [('boite', -5, 1.5, 5, 1.65, 2.5),           # mur le long du robot
              ('boite', 2.0, -2.0, 2.15, 2.0, 2.5),        # mur en face
              ('boite', -2.6, -1.0, -1.4, -0.2, 0.75),     # table
              ('boite', 0.5, -1.3, 0.95, -0.85, 0.9),      # chaise (dossier à 0,9 m)
              ('boite', 1.2, -1.45, 1.7, 1.45, 1.2)]       # la boîte du critère 5, en travers
    assert DetecteurPersonnes().detecter(lancer(objets), 0.0) == []


def test_poteau_retire_par_la_carte(tmp_path):
    """Un poteau ressemble à une personne ; sur la carte du lieu, il est retiré."""
    dossier = copier_lieu(RACINE / 'lieux' / 'demo', tmp_path / 'demo')
    from atelier.monde import generer
    generer(dossier, 'rdc')
    pose = (26.0, 11.5, -math.pi / 2)          # le robot face au poteau_1 (26 ; 10), à 1,5 m
    nuage = lancer([('cylindre', 26.0, 10.0, 0.2, 2.5)], pose=pose)
    assert len(DetecteurPersonnes().detecter(nuage, 0.0, robot_carte=pose)) == 1
    carte = CarteStatique.depuis_lieu(dossier, 'rdc')
    assert DetecteurPersonnes(carte).detecter(nuage, 0.0, robot_carte=pose) == []
    # Une vraie personne au même endroit du couloir, loin des murs : gardée
    nuage = lancer([('cylindre', 26.0, 10.0, 0.2, 2.5), personne(27.5, 11.0)], pose=pose)
    vues = DetecteurPersonnes(carte).detecter(nuage, 0.0, robot_carte=pose)
    assert len(vues) == 1
    assert vues[0]['x_map'] == pytest.approx(27.5, abs=0.3)
    assert vues[0]['y_map'] == pytest.approx(11.0, abs=0.3)


def test_suivi_meme_numero_et_vitesse():
    d = DetecteurPersonnes()
    numeros, vitesses = set(), []
    for k in range(20):
        t = k * 0.1
        vues = d.detecter(lancer([personne(2.0 + 0.1 * k, 0.5)]), t, robot_fixe=(0.0, 0.0, 0.0))
        assert len(vues) == 1
        numeros.add(vues[0]['id'])
        vitesses.append(vues[0]['vx'])
    assert len(numeros) == 1
    assert vitesses[-1] == pytest.approx(1.0, abs=0.2)
    assert d.detecter(lancer([]), 3.0) == [] and d.pistes == []      # oubliée après 1 s


def test_suivi_dans_le_repere_odom_quand_le_robot_avance():
    """Le robot avance, la personne reste sur place : même numéro, vitesse presque nulle."""
    d = DetecteurPersonnes()
    numeros = set()
    for k in range(15):
        robot = (0.05 * k, 0.0, 0.0)
        nuage = lancer([personne(3.0, 0.0)], pose=robot)
        vues = d.detecter(nuage, k * 0.1, robot_fixe=robot)
        numeros.add(vues[0]['id'])
    assert len(numeros) == 1 and abs(vues[0]['vx']) < 0.15


def test_outils():
    xy = np.array([[0, 0], [0.1, 0], [0.2, 0.05], [2, 2], [2.1, 2]])
    groupes = regrouper(xy, 0.15)
    assert sorted(len(g) for g in groupes) == [2, 3]
    assert etendue(np.array([[0, 0], [1, 0], [0.5, 0.1]]))[0] == pytest.approx(1.0, abs=0.01)
    m = masque_carte(np.array([[254, 254, 254], [254, 0, 254], [254, 254, 254]]), 0.05, 0.05)
    assert m.sum() == 5
    assert vers_carte([[1.0, 0.0]], (1.0, 2.0, math.pi / 2))[0] == pytest.approx((1.0, 3.0))
