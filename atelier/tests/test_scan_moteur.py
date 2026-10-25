"""Tests de MoteurUnitree (ws/src/g1_nav/g1_nav/moteur_unitree.py) contre le faux service slam_operate.

Le faux service tourne dans ce processus, sur lo (voir test_scan_slam.py). Le robot imaginaire
va vite (3 m/s) pour que les tests restent courts.
"""
import math
import sys
import time

import pytest

from atelier import RACINE

sys.path.insert(0, str(RACINE / "ws" / "src" / "g1_nav"))

from g1_nav.moteur_unitree import MoteurUnitree, decouper, longueur_chemin  # noqa: E402
from g1_nav.moteurs import CLES_ETAT  # noqa: E402

from atelier.scan import slam_client as sc  # noqa: E402
from atelier.scan.faux_slam import faux_partage  # noqa: E402


# ---------------------------------------------------------------- découpage en tronçons

def test_decouper_en_troncons_de_8_m():
    cibles = decouper((0.0, 0.0, 0.0), [(20.0, 0.0, 0.0), (20.0, 5.0, 1.0)])
    assert len(cibles) == 4                          # 20 m en 3 tronçons, puis 5 m
    points = [(0.0, 0.0)] + [c[:2] for c in cibles]
    for a, b in zip(points, points[1:]):
        assert math.dist(a, b) <= 8.0 + 1e-9
    assert cibles[0][:2] == pytest.approx((20 / 3, 0.0))
    assert cibles[2][:2] == pytest.approx((20.0, 0.0))
    assert cibles[2][2] == pytest.approx(math.pi / 2)        # au nœud, tourné vers la suite
    assert cibles[-1] == (20.0, 5.0, 1.0)                    # la destination garde son theta
    assert longueur_chemin(points) == pytest.approx(25.0)


def test_decouper_cas_limites():
    assert decouper((1.0, 1.0, 0.0), [(1.0, 1.0, 2.0)]) == [(1.0, 1.0, 2.0)]   # déjà sur place : tourner
    assert decouper(None, [(0.0, 0.0, 0.0), (8.0, 0.0, 0.5)]) == [(8.0, 0.0, 0.5)]
    cibles = decouper((0.0, 0.0), [(8.0, 0.0, 0.0)])
    assert len(cibles) == 1                                  # 8 m pile : un seul tronçon
    cibles = decouper((0.0, 0.0), [(16.01, 0.0, 0.0)], longueur_max=8.0)
    assert len(cibles) == 3


# ---------------------------------------------------------------- contre le faux service

@pytest.fixture(scope="module")
def client():
    faux_partage()
    domaine, interface = sc.dds_ouvert()
    c = sc.ClientSlam(interface, domaine, delai=3.0)
    yield c
    c.fermer()


@pytest.fixture
def faux():
    f = faux_partage(depart=(0.0, 0.0, 0.0), relocalise=True, vitesse=3.0, rotation=8.0, portee_max=8.5)
    time.sleep(0.3)        # que slam_info annonce la nouvelle position
    return f


@pytest.fixture
def moteur(client):
    m = MoteurUnitree(client=client)
    yield m
    m.annuler()
    m.fermer()


def attendre_etat(moteur, cle, delai):
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        etat = moteur.etat()
        assert set(etat) == set(CLES_ETAT)
        assert sum([etat["en_cours"], etat["arrive"], etat["echec"]]) <= 1
        if etat[cle]:
            return etat
        time.sleep(0.05)
    return moteur.etat()


def test_long_trajet_en_troncons(faux, client, moteur):
    poses = [(10.0, 0.0, 0.0), (10.0, 10.0, 0.0), (0.0, 10.0, math.pi)]
    assert attendre_etat_position(client)
    debut = time.monotonic()
    assert moteur.demarrer(poses)
    etat = moteur.etat()
    assert etat["en_cours"] and etat["reste_m"] == pytest.approx(30.0, abs=0.5)
    # Le robot avance : progresse devient vrai, reste_m baisse
    assert attendre_etat(moteur, "progresse", 3.0)["progresse"]
    etat = attendre_etat(moteur, "arrive", 30.0)
    assert etat["arrive"] and etat["reste_m"] == 0.0 and not etat["progresse"]
    assert time.monotonic() - debut < 30
    x, y, theta = faux.position()
    assert math.hypot(x, y - 10.0) < 0.01 and abs(abs(theta) - math.pi) < 0.01
    # Chaque 1102 accepté va à 8 m au plus de la position de départ du tronçon
    allers = [e for e in faux.journal if e["api"] == sc.API_ALLER]
    assert len(allers) == 6 and all(e["reponse"]["succeed"] for e in allers)
    points = [(0.0, 0.0)] + [(e["parametres"]["data"]["targetPose"]["x"],
                               e["parametres"]["data"]["targetPose"]["y"]) for e in allers]
    assert all(math.dist(a, b) <= 8.0 + 1e-6 for a, b in zip(points, points[1:]))


def attendre_etat_position(client, delai=3.0):
    fin = time.monotonic() + delai
    while time.monotonic() < fin and client.pose()[0] is None:
        time.sleep(0.05)
    return client.pose()[0] is not None


@pytest.mark.parametrize("publication", ["periodique", "evenement"])
def test_arrivee_perimee_ignoree(faux, client, moteur, publication):
    """Le is_arrived du tronçon 1 republié après l'envoi du tronçon 2 ne termine pas le trajet."""
    faux.reinitialiser((0.0, 0.0, 0.0), relocalise=True, vitesse=1.5, rotation=8.0,
                       publication_cle=publication, delai_perime=1.0)
    time.sleep(0.3)
    assert moteur.demarrer([(1.0, 0.0, 0.0), (3.0, 0.0, 0.0)])
    etat = attendre_etat(moteur, "arrive", 15.0)
    assert etat["arrive"]
    assert faux.position()[0] == pytest.approx(3.0, abs=0.01)    # vraiment arrivé au bout


def test_obstacle_puis_annuler(faux, client, moteur):
    faux.reinitialiser((0.0, 0.0, 0.0), relocalise=True, vitesse=1.0)
    time.sleep(0.3)
    assert moteur.demarrer([(6.0, 0.0, 0.0)])
    assert attendre_etat(moteur, "progresse", 3.0)["progresse"]
    faux.bloquer(True)                         # le robot s'arrête devant un obstacle
    time.sleep(1.5)
    etat = moteur.etat()
    assert etat["en_cours"] and not etat["progresse"]
    assert 0.0 < etat["reste_m"] < 6.0
    faux.bloquer(False)
    assert attendre_etat(moteur, "progresse", 3.0)["progresse"]
    # Annuler : état de repos tout de suite, le robot s'arrête (1201)
    moteur.annuler()
    etat = moteur.etat()
    assert not any(etat[c] for c in ("en_cours", "arrive", "echec")) and etat["reste_m"] is None
    time.sleep(0.4)
    x = faux.position()[0]
    time.sleep(0.4)
    assert faux.position()[0] == pytest.approx(x)
    assert faux.en_pause
    # Repartir ailleurs : 1102 puis 1202, le robot repart
    assert moteur.demarrer([(x, 1.0, 0.0)])
    assert attendre_etat(moteur, "arrive", 10.0)["arrive"]
    assert faux.position()[1] == pytest.approx(1.0, abs=0.01)


def test_refus_et_remplacement(faux, client, moteur):
    # Robot non repéré : 1102 refusé → demarrer renvoie False, état echec
    faux.reinitialiser((0.0, 0.0, 0.0), relocalise=False)
    assert moteur.demarrer([(1.0, 0.0, 0.0)]) is False
    assert attendre_etat(moteur, "echec", 2.0)["echec"]
    # Un nouveau départ remplace le précédent
    faux.reinitialiser((0.0, 0.0, 0.0), relocalise=True, vitesse=2.0)
    time.sleep(0.3)
    assert moteur.demarrer([(5.0, 0.0, 0.0)])
    time.sleep(0.5)
    assert moteur.demarrer([(0.0, 2.0, 0.0)])
    assert attendre_etat(moteur, "arrive", 10.0)["arrive"]
    assert faux.position()[:2] == pytest.approx((0.0, 2.0), abs=0.01)
    with pytest.raises(ValueError):
        moteur.demarrer([])


def test_position_fournie_et_rapidite(faux, client):
    """Les méthodes rendent la main vite ; une position qui ne change plus : progresse faux."""
    faux.reinitialiser((0.0, 0.0, 0.0), relocalise=True, vitesse=1.0)
    figee = (0.0, 0.0, 0.0)
    m = MoteurUnitree(client=client, position=lambda: figee)
    try:
        t = time.monotonic()
        assert m.demarrer([(4.0, 0.0, 0.0)])
        e = m.etat()
        m.etat()
        assert time.monotonic() - t < 1.0
        assert e["reste_m"] == pytest.approx(4.0)
        time.sleep(1.5)
        e = m.etat()
        assert e["en_cours"] and not e["progresse"] and e["reste_m"] == pytest.approx(4.0)
        t = time.monotonic()
        m.annuler()
        assert time.monotonic() - t < 1.0
    finally:
        m.fermer()
