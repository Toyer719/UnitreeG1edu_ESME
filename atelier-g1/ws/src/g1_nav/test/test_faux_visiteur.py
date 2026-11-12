"""
Tests du faux visiteur (g1_nav/faux_visiteur.py), sans ROS ni Gazebo.

Le robot suit l'itinéraire accueil → hall_nord → couloir nord du lieu demo à 0,4 m/s ; le visiteur
avance de sa consigne à chaque pas (10 Hz), comme le ferait le nœud pietons de g1_sim.

  python3 -m pytest ~/robot-g1/ws/src/g1_nav/test/test_faux_visiteur.py -v
"""
import math

from atelier import RACINE
from atelier.lieu import copier_lieu, valider_message
from g1_nav.faux_visiteur import FauxVisiteur, message_consigne
from g1_nav.personnes import CarteStatique
import numpy as np
import pytest

PAS_S = 0.1
CHEMIN = [(2.5, 10.0), (2.5, 13.0), (21.0, 13.0)]      # accueil → hall_nord → b204


def position_robot(t, vitesse=0.4):
    """Position du robot sur CHEMIN au temps t."""
    reste = vitesse * t
    for a, b in zip(CHEMIN, CHEMIN[1:]):
        d = math.dist(a, b)
        if reste <= d:
            return (a[0] + (b[0] - a[0]) * reste / d, a[1] + (b[1] - a[1]) * reste / d)
        reste -= d
    return CHEMIN[-1]


def distance_au_chemin(p):
    best = math.inf
    for (ax, ay), (bx, by) in zip(CHEMIN, CHEMIN[1:]):
        dx, dy = bx - ax, by - ay
        u = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / (dx * dx + dy * dy)))
        best = min(best, math.dist(p, (ax + u * dx, ay + u * dy)))
    return best


def simuler(visiteur, duree_s, depart=(1.5, 10.0), t0=0.0, vitesse=0.4, mode_a=None):
    """Fait marcher robot et visiteur ; renvoie [(t, robot, visiteur)]. mode_a : {t: mode}."""
    p = list(depart)
    suite = []
    for k in range(int(duree_s / PAS_S)):
        t = t0 + k * PAS_S
        if mode_a and round(t, 1) in mode_a:
            assert visiteur.changer_mode(mode_a[round(t, 1)])
        robot = position_robot(t, vitesse)
        visiteur.noter_robot(*robot)
        vx, vy = visiteur.consigne(p, robot, vitesse)
        assert math.hypot(vx, vy) <= 1.5 + 1e-9
        p[0] += vx * PAS_S
        p[1] += vy * PAS_S
        suite.append((t, robot, tuple(p)))
    return suite


def test_suivre_a_1_2_m_sur_la_trace():
    v = FauxVisiteur()
    suite = simuler(v, 60.0)
    apres = [math.dist(r, p) for t, r, p in suite if t > 10]
    assert 1.0 < min(apres) and max(apres) < 1.7
    # Il marche sur le chemin du robot : il ne coupe pas le coin du hall
    assert max(distance_au_chemin(p) for t, r, p in suite if t > 5) < 0.3


def test_trainer_puis_suivre():
    v = FauxVisiteur()
    suite = simuler(v, 50.0, mode_a={10.0: 'trainer', 30.0: 'suivre'})
    distance = {round(t): math.dist(r, p) for t, r, p in suite}
    assert distance[10] < 1.7
    assert distance[29] > 5.0                     # il s'est laissé distancer (0,4 contre 0,15 m/s)
    assert distance[49] < 1.8                     # puis il a rattrapé le robot


def test_partir_par_l_espace_libre(tmp_path):
    from atelier.monde import generer
    dossier = copier_lieu(RACINE / 'lieux' / 'demo', tmp_path / 'demo')
    generer(dossier, 'rdc')
    carte = CarteStatique.depuis_lieu(dossier, 'rdc', 0.05)
    v = FauxVisiteur(carte)
    suite = simuler(v, 40.0, mode_a={12.0: 'partir'}, vitesse=0.0 + 0.4)
    fin = suite[-1]
    assert math.dist(fin[1], fin[2]) > 10.0
    libres = [not carte.occupes(np.array([p]))[0] for t, r, p in suite]
    assert all(libres)
    assert v.mode == 'partir'


def test_partir_sans_carte_et_arreter():
    v = FauxVisiteur(mode='partir')
    assert v.consigne((1.0, 0.0), (0.0, 0.0)) == pytest.approx((1.0, 0.0))
    assert v.consigne((16.0, 0.0), (0.0, 0.0)) == (0.0, 0.0)       # assez loin : il s'arrête
    assert v.changer_mode('arreter') and v.consigne((1.0, 0.0), (5.0, 0.0)) == (0.0, 0.0)
    assert not v.changer_mode('danser') and v.mode == 'arreter'


def test_message_conforme():
    m = message_consigne('visiteur', 3.0, -0.2)
    assert m['vx'] == 1.5 and valider_message('pietons_consigne', m) == []
    assert 'theta' not in message_consigne('visiteur', 0.0, 0.0)
    assert valider_message('pietons_consigne', message_consigne('visiteur', 0.0, 0.0)) == []


def test_pas_de_cote_quand_le_robot_revient(tmp_path):
    """Le robot fait demi-tour vers le visiteur : il s'écarte de 1 m, puis le suit de nouveau."""
    from atelier.monde import generer
    dossier = copier_lieu(RACINE / 'lieux' / 'demo', tmp_path / 'demo')
    generer(dossier, 'rdc')
    carte = CarteStatique.depuis_lieu(dossier, 'rdc', 0.05)
    v = FauxVisiteur(carte)
    p = [16.0, 13.0]
    robot = [18.0, 13.0]
    for x in np.arange(18.0, 21.0, 0.04):           # le robot va vers b204, le visiteur suit
        robot[0] = x
        v.noter_robot(*robot)
        c = v.consigne(p, robot, 0.4, (0.4, 0.0))
        p = [p[0] + c[0] * PAS_S, p[1] + c[1] * PAS_S]
    assert 1.0 < math.dist(p, robot) < 1.8
    plus_pres, ecart_max = math.inf, 0.0
    for x in np.arange(21.0, 14.0, -0.04):          # demi-tour : il revient vers l'ouest
        robot[0] = x
        v.noter_robot(*robot)
        c = v.consigne(p, robot, 0.4, (-0.4, 0.0))
        p = [p[0] + c[0] * PAS_S, p[1] + c[1] * PAS_S]
        plus_pres = min(plus_pres, math.dist(p, robot))
        ecart_max = max(ecart_max, abs(p[1] - 13.0))
        assert not carte.occupes(np.array([p]))[0]
    assert ecart_max >= 0.95 and plus_pres > 0.8       # il s'est écarté, le robot est passé
    assert p[0] > robot[0] and math.dist(p, robot) < 2.0   # puis il le suit de nouveau, derrière
