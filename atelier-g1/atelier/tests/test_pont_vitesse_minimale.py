"""Vitesse minimale du vrai G1 hors du pont (vague 5, section 12.6 du plan), sans ROS.

Le 27/10, le vrai G1 ne faisait aucun pas à 0,1 m/s et marchait à 0,2 m/s. Le pont (g1_bridge) monte
ses consignes ; le joystick et les pas des chorégraphies du pilotage passent par la même règle
(atelier.lieu.robot.vitesse_effective) : consigne_marche, pas_effectif, avertissements_choregraphie
et limites_marche d'atelier.lieu.pilotage. Aussi : l'exemple complet de /pont/etat du contrat.
"""
import copy
import math
import random

import pytest

from atelier.lieu import pilotage as D
from atelier.lieu import robot as R
from atelier.lieu import valider_message


# ---------------------------------------------------------------- joystick

@pytest.mark.parametrize("entree, attendu", [
    ((0.1, 0.0, 0.0), (0.2, 0.0, 0.0)),            # petite inclinaison : 0,2 m/s
    ((0.0, 0.0, 0.15), (0.0, 0.0, 0.3)),
    ((0.03, 0.0, 0.0), (0.0, 0.0, 0.0)),           # zone morte : arrêt
    ((0.3, 0.05, 0.1), (0.3, 0.05, 0.1)),          # marche franche : telle quelle
    ((1.0, -1.0, 2.0), (0.4, -0.25, 0.6)),         # plafonds d'abord
    ((float("nan"), 0.1, 0.0), (0.0, 0.0, 0.0)),
])
def test_consigne_du_joystick(entree, attendu):
    assert D.consigne_marche(*entree) == pytest.approx(attendu, abs=1e-9)


@pytest.mark.parametrize("entree, attendu", R.EXEMPLES_ZONES_NULLES)
def test_bruit_jamais_monte_au_minimum(entree, attendu):
    """Revue de la vague 5 : zones mortes à 0, minimums actifs : un résidu sous SEUIL_NUL_PONT reste un
    arrêt (il ne fait jamais marcher le robot à 0,2 m/s ni tourner à 0,3 rad/s)."""
    assert R.vitesse_effective(*entree, zones=R.ZONES_NULLES_PONT) == pytest.approx(attendu, abs=1e-9)


def test_consigne_du_joystick_avec_vitesse_reduite():
    limites = D.limites_marche(0.2)
    assert D.consigne_marche(0.0, 0.1, 0.0, limites) == pytest.approx((0.0, 0.125, 0.0))   # vy_max
    assert D.consigne_marche(1.0, 0.0, 0.0, limites) == pytest.approx((0.2, 0.0, 0.0))


@pytest.mark.parametrize("valeur", [0.15, "0.1", "0,19", 0.05])
def test_vitesse_maximale_sous_0_2_refusee(valeur):
    with pytest.raises(ValueError, match=R.MESSAGE_VITESSE_MAX_BASSE):
        D.limites_marche(valeur)


def test_vitesse_maximale_permise():
    assert D.limites_marche("0,2") == {"vx": 0.2, "vy": 0.125, "wz": 0.3}
    assert D.limites_marche(0.4) == D.LIMITES_MARCHE and D.limites_marche(None) == D.LIMITES_MARCHE
    for absurde in (0, -0.3, 0.5, "vite", float("inf")):
        with pytest.raises(ValueError):
            D.limites_marche(absurde)


# ---------------------------------------------------------------- pas des chorégraphies

@pytest.mark.parametrize("entree, facteur, sortie", [
    ((0.0, 0.15, 0.0), 4 / 3, (0.0, 0.2, 0.0)),     # pas de côté : 0,2 m/s, 4/3 fois moins long
    ((0.1, 0.0, 0.0), 2.0, (0.2, 0.0, 0.0)),
    ((0.1, 0.0, 0.05), 2.0, (0.2, 0.0, 0.1)),       # toute la consigne au même facteur (même arc)
    ((0.0, 0.0, 0.15), 2.0, (0.0, 0.0, 0.3)),
    ((0.08, 0.0, 0.2), 1.5, (0.12, 0.0, 0.3)),      # la rotation domine : la marche suit
    ((0.03, 0.0, 0.05), 0.0, (0.0, 0.0, 0.0)),      # trop petit : sur place
    ((0.2, 0.0, 0.0), 1.0, (0.2, 0.0, 0.0)),        # déjà assez vite : inchangé
    ((0.0, 0.0, 0.5), 1.0, (0.0, 0.0, 0.5)),
])
def test_pas_effectif(entree, facteur, sortie):
    f, faite = D.pas_effectif(*entree)
    assert f == pytest.approx(facteur) and faite == pytest.approx(sortie, abs=1e-9)


def test_pas_effectif_meme_trajet_et_sous_les_plafonds():
    """Au hasard : facteur ≥ 1 (ou 0), même direction et même arc, jamais au-delà des plafonds."""
    alea = random.Random(5)
    for _ in range(3000):
        plafonds = alea.choice([D.LIMITES_PAS, {"vx": 0.2, "vy": 0.125, "wz": 0.3}])
        v = tuple(alea.uniform(-1, 1) * plafonds[a] * alea.choice([1.0, 0.3]) for a in ("vx", "vy", "wz"))
        f, faite = D.pas_effectif(*v, plafonds=plafonds)
        if f == 0.0:
            assert faite == (0.0, 0.0, 0.0)
            assert math.hypot(v[0], v[1]) < R.ZONES_MORTES_PONT["lin"] and abs(v[2]) < R.ZONES_MORTES_PONT["rot"]
            continue
        assert f >= 1.0
        assert all(abs(c) <= plafonds[a] + 1e-9 for c, a in zip(faite, ("vx", "vy", "wz")))
        assert faite == pytest.approx(tuple(c * f for c in v), abs=1e-12)     # tout au même facteur
        # assez vite pour le vrai robot, sauf si un plafond l'en empêche
        assez = math.hypot(faite[0], faite[1]) >= R.VITESSES_MIN_PONT["lin"] - 1e-9 \
            or abs(faite[2]) >= R.VITESSES_MIN_PONT["rot"] - 1e-9
        au_plafond = any(abs(abs(c) - plafonds[a]) < 1e-9 for c, a in zip(faite, ("vx", "vy", "wz")))
        assert assez or au_plafond, (v, f, faite)


def test_avertissements_des_pas():
    d = copy.deepcopy(D.charger_choregraphie("exemple_kpop"))
    assert D.avertissements_choregraphie(d) == []                   # l'exemple est déjà à 0,2 m/s
    d["pas"] = [{"t": 2.0, "vx": 0.0, "vy": 0.1, "wz": 0.0, "duree_s": 1.0},
                {"t": 4.0, "vx": 0.03, "vy": 0.0, "wz": 0.05, "duree_s": 1.0},
                {"t": 6.0, "vx": 0.0, "vy": 0.0, "wz": 0.5, "duree_s": 1.0}]
    assert D.verifier_choregraphie(d) == []                          # avertissements, pas erreurs
    premier, second = D.avertissements_choregraphie(d)
    assert premier.startswith("pas à 2 s (vx 0, vy 0,1, wz 0)") and "pendant 0,50 s" in premier
    assert "même trajet" in premier
    assert second.startswith("pas à 4 s") and "ne bougera pas" in second
    # avec vitesse_max 0,2 : un pas de côté reste à 0,125 m/s, sous le minimum
    d["pas"] = [{"t": 2.0, "vx": 0.0, "vy": 0.1, "wz": 0.0, "duree_s": 1.0}]
    (seul,) = D.avertissements_choregraphie(d, D.limites_marche(0.2))
    assert "risque de ne pas bouger" in seul


def test_exemple_kpop_meme_deplacement_qu_avant():
    """Les pas corrigés (0,2 m/s, moins longtemps) font le même trajet que ceux d'avant (0,15 et 0,1)."""
    d = D.charger_choregraphie("exemple_kpop")
    avant = copy.deepcopy(d)
    for p, (vx, vy, duree) in zip([p for p in avant["pas"] if p["vx"] or p["vy"]],
                                  [(0.0, 0.15, 1.0), (0.0, -0.15, 1.0), (0.1, 0.0, 1.0), (-0.1, 0.0, 1.0)]):
        p.update(vx=vx, vy=vy, duree_s=duree)
    assert D.deplacement_pas(d) == pytest.approx(D.deplacement_pas(avant), abs=1e-9)


# ---------------------------------------------------------------- modes et état du pont

def test_mode_de_marche_et_fin_de_danse():
    assert D.FSM_MARCHE == 501 and D.FSM_MARCHE in D.MODES_MARCHE
    assert set(D.MODES_FIN_DANSE) == {501, 801} and set(D.MODES_FIN_DANSE) <= set(D.MODES_MARCHE)
    assert D.EXEMPLE_ETAT_PILOTAGE["fsm"] == 501
    assert valider_message("etat_pilotage", D.EXEMPLE_ETAT_PILOTAGE) == []


def test_exemple_etat_pont_complet():
    """L'exemple a les champs que le pont publie depuis la vague 5 ; l'exemple V5 aussi, assis."""
    e = R.EXEMPLE_ETAT_PONT
    assert {"demande", "minimums", "mode_robot"} <= set(e) and valider_message("etat_pont", e) == []
    assert e["mode_robot"]["en_marche"] is True and e["mode_robot"]["fsm"] in D.MODES_MARCHE
    assert e["minimums"] == R.EXEMPLE_ETAT_PONT_V5["minimums"]
    assert set(e) == set(R.EXEMPLE_ETAT_PONT_V5)
