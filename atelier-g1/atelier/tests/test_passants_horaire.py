"""Horaire des piétons (vague 4, section 11.3) : pauses, départ, un seul parcours.

Le trajet d'un piéton sans les champs de la vague 4 ne change pas (test_monde_sdf.py) ; ici, les
pauses (à chaque passage au point de ce rang), le départ (depart_s) et repeter: false, dans
etat_prevu (nœud pietons, banc, interface) et dans les points de passage des <actor>.
"""
import math
import xml.etree.ElementTree as ET

import pytest

from atelier.lieu import Pieton, valider_donnees
from atelier.monde import pietons as P
from atelier.monde.sdf import texte_sdf
from atelier.lieu import Monde


def pieton(**champs):
    base = {"id": "p", "trajet": [(0.0, 0.0), (4.0, 0.0)], "vitesse": 1.0, "aller_retour": True}
    base.update(champs)
    return Pieton(**base)


def test_sans_champ_v4_rien_ne_change():
    p = pieton()
    h = P.horaire(p)
    assert h.duree == pytest.approx(8.0) and h.repeter and h.depart == 0.0
    assert [m.etat for m in h.morceaux] == ["marche", "marche"]
    x, y, cap, vx, vy, etat = P.etat_prevu(p, 2.0)
    assert (x, y, cap, vx, vy) == pytest.approx((2.0, 0.0, 0.0, 1.0, 0.0)) and etat == "marche"
    x, y, cap, vx, vy, etat = P.etat_prevu(p, 6.0)       # au retour
    assert (x, y, vx) == pytest.approx((2.0, 0.0, -1.0)) and abs(abs(cap) - math.pi) < 1e-9


def test_pause_au_depart_et_a_chaque_passage():
    # va-et-vient 0 → 1 → 2 → 1 → 0 ; pause de 3 s au point 1 (passé deux fois par tour), 2 s au point 0
    p = pieton(trajet=[(0.0, 0.0), (2.0, 0.0), (4.0, 0.0)], pauses=[{"point": 1, "duree_s": 3.0},
                                                                    {"point": 0, "duree_s": 2.0}])
    h = P.horaire(p)
    assert h.duree == pytest.approx(8.0 + 2.0 + 3.0 + 3.0)
    assert [m.etat for m in h.morceaux] == ["pause", "marche", "pause", "marche", "marche", "pause", "marche"]
    assert P.etat_prevu(p, 1.0)[5] == "pause" and P.etat_prevu(p, 1.0)[:2] == (0.0, 0.0)
    assert P.etat_prevu(p, 3.0)[:2] == pytest.approx((1.0, 0.0))
    assert P.etat_prevu(p, 5.5)[5] == "pause" and P.etat_prevu(p, 5.5)[:2] == (2.0, 0.0)
    # au retour, la pause au point 1 regarde vers l'ouest (direction de la marche d'avant)
    x, y, cap, vx, vy, etat = P.etat_prevu(p, 2 + 2 + 3 + 2 + 2 + 1.0)
    assert etat == "pause" and (x, y) == (2.0, 0.0) and abs(abs(cap) - math.pi) < 1e-9
    assert P.etat_prevu(p, h.duree + 1.0)[5] == "pause"          # tour suivant : pause au point 0


def test_pieton_immobile_du_contrat():
    p = pieton(trajet=[(12.0, 13.0), (12.5, 13.0)], pauses=[{"point": 0, "duree_s": 3600}])
    for t in (0.0, 10.0, 1800.0, 3599.0):
        x, y, cap, vx, vy, etat = P.etat_prevu(p, t)
        assert (x, y, vx, vy, etat) == (12.0, 13.0, 0.0, 0.0, "pause")
    assert P.duree_tour(p) == pytest.approx(3601.0)


def test_depart_differe():
    p = pieton(depart_s=5.0)
    assert P.etat_prevu(p, 4.9)[5] == "pause" and P.etat_prevu(p, 4.9)[:2] == (0.0, 0.0)
    assert P.etat_prevu(p, 6.0)[:2] == pytest.approx((1.0, 0.0)) and P.etat_prevu(p, 6.0)[5] == "marche"
    assert P.position_pieton(p, 7.0)[:2] == pytest.approx((2.0, 0.0))


@pytest.mark.parametrize("aller_retour, fin", [(False, (4.0, 3.0)), (True, (0.0, 0.0))])
def test_un_seul_parcours(aller_retour, fin):
    p = pieton(trajet=[(0.0, 0.0), (4.0, 0.0), (4.0, 3.0)], aller_retour=aller_retour, repeter=False)
    h = P.horaire(p)
    assert h.duree == pytest.approx(7.0 if not aller_retour else 14.0)
    x, y, cap, vx, vy, etat = P.etat_prevu(p, h.duree + 100.0)
    assert (x, y, vx, vy, etat) == (fin[0], fin[1], 0.0, 0.0, "fini")
    assert P.etat_prevu(p, h.duree - 0.5)[5] == "marche"


def test_points_de_passage_avec_pause_et_un_seul_parcours():
    p = pieton(pauses=[{"point": 1, "duree_s": 2.0}], repeter=False, aller_retour=False)
    points = P.points_de_passage(p)
    assert points[0] == (0.0, 0.0, 0.0, 0.0)
    assert points[-1] == (4.0, 4.0, 0.0, 0.0)              # arrivé au dernier point, sans retour
    q = pieton(pauses=[{"point": 1, "duree_s": 2.0}])
    points = P.points_de_passage(q)
    temps = [t for t, *_ in points]
    assert temps == sorted(temps)
    # la pause est un point répété : (4, 0) à t = 4 puis le retour part de (4, 0) à t = 6
    assert (4.0, 4.0, 0.0) in [(t, x, y) for t, x, y, _ in points]
    assert (6.0, 4.0, 0.0) in [(t, x, y) for t, x, y, _ in points]
    assert P.duree_tour(q) == pytest.approx(10.0)


def test_script_de_l_actor_depart_et_repetition():
    monde = Monde.depuis_dict({
        "version": 1, "emprise": {"min": [-1, -1], "max": [5, 5]},
        "pietons": [{"id": "a", "trajet": [[0, 0], [4, 0]], "vitesse": 1.0, "aller_retour": True,
                     "depart_s": 3.5, "repeter": False},
                    {"id": "b", "trajet": [[0, 1], [4, 1]], "vitesse": 1.0, "aller_retour": True}],
        "depart_robot": {"x": 0, "y": 0, "theta": 0}})
    assert valider_donnees("monde", monde.vers_dict()) == []
    racine = ET.fromstring(texte_sdf(monde, "rdc"))
    scripts = {a.get("name"): a.find("script") for a in racine.iter("actor")}
    assert (scripts["a"].findtext("loop"), scripts["a"].findtext("delay_start")) == ("false", "3.5")
    assert (scripts["b"].findtext("loop"), scripts["b"].findtext("delay_start")) == ("true", "0")
