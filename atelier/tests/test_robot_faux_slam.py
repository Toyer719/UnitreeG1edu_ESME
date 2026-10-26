"""Logique du faux slam_operate de la répétition (FauxSlamJumeau, section 10.6 du plan), sans ROS
ni SDK : 1804 contre la vérité terrain, cartes connues, refus de 1102, arrêt par 1901, et la ligne
de commande g1-slam faux-service --jumeau (refus des options incompatibles).
"""
import json

import pytest

from atelier.lieu import carte_vers_unitree
from atelier.scan import slam_client as sc
from atelier.scan.commande import principal_slam
from atelier.scan.faux_slam import (ERREUR_CARTE, ERREUR_DEROULE, ERREUR_RELOCALISATION, FauxSlamJumeau)

REPERE = (2.5, 10.0, 0.0)


def _faux(repere=REPERE, cartes=("rdc_scan.pcd", "repetition.pcd")):
    return FauxSlamJumeau(repere, cartes)


def _1804(faux, x, y, theta, carte="repetition.pcd"):
    code, texte = faux._traiter(sc.API_RELOCALISER, json.dumps(sc.parametres_relocaliser(x, y, theta, carte)))
    assert code == 0
    return json.loads(texte)


def test_cartes_connues():
    faux = _faux()
    assert faux.cartes == {"/home/unitree/rdc_scan.pcd", "/home/unitree/repetition.pcd"}
    faux.reinitialiser()
    assert "/home/unitree/repetition.pcd" in faux.cartes      # gardées après une remise à zéro


def test_1804_sans_verite_terrain():
    faux = _faux()
    r = _1804(faux, 0.0, 0.0, 0.0)
    assert r["succeed"] is False and r["errorCode"] == ERREUR_DEROULE and "g1_jumeau" in r["info"]
    assert faux.mode == "repos"


def test_1804_a_la_bonne_place():
    faux = _faux()
    faux.deplacement.noter(12.0, (2.6, 10.1, 0.1))
    r = _1804(faux, 0.0, 0.0, 0.0)
    assert r["succeed"] is True and faux.mode == "relocalise"
    assert faux.carte == "/home/unitree/repetition.pcd"
    # la position est la vérité, exprimée dans le repère d'Unitree ; 1804 ne téléporte pas le robot
    assert faux.position() == pytest.approx(carte_vers_unitree((2.6, 10.1, 0.1), REPERE))
    assert faux.deplacement.verite()[1] == (2.6, 10.1, 0.1)


@pytest.mark.parametrize("pose", [(1.2, 0.0, 0.0), (0.0, 0.0, 0.6)])
def test_1804_trop_loin_refuse(pose):
    faux = _faux()
    faux.deplacement.noter(12.0, REPERE)
    _1804(faux, 0.0, 0.0, 0.0)
    assert faux.mode == "relocalise"
    r = _1804(faux, *pose)
    assert r["succeed"] is False and r["errorCode"] == ERREUR_RELOCALISATION
    assert "pas à la position donnée" in r["info"]
    assert faux.mode == "repos" and faux.carte is None      # plus de relocalisation publiée


def test_1804_repere_tourne():
    """Variante B du critère 18 : repère (3 ; 9 ; 0,5), robot au départ (2,5 ; 10 ; 0)."""
    faux = _faux(repere=(3.0, 9.0, 0.5))
    faux.deplacement.noter(12.0, (2.5, 10.0, 0.0))
    assert _1804(faux, 0.0, 0.0, 0.0)["errorCode"] == ERREUR_RELOCALISATION
    u = carte_vers_unitree((2.5, 10.0, 0.0), (3.0, 9.0, 0.5))
    assert _1804(faux, *u)["succeed"] is True


def test_carte_inconnue_1102_et_1901():
    faux = _faux()
    faux.deplacement.noter(12.0, REPERE)
    assert _1804(faux, 0.0, 0.0, 0.0, carte="autre.pcd")["errorCode"] == ERREUR_CARTE
    _1804(faux, 0.0, 0.0, 0.0)
    code, texte = faux._traiter(sc.API_ALLER, json.dumps(sc.parametres_aller(1.0, 0.0, 0.0)))
    r = json.loads(texte)
    assert r["succeed"] is False and r["errorCode"] == ERREUR_DEROULE and "Nav2" in r["info"]
    code, texte = faux._traiter(sc.API_ARRETER, json.dumps(sc.parametres_vides()))
    assert json.loads(texte)["succeed"] and faux.mode == "repos"
    # le déplacement ne publie jamais de vitesse
    faux.deplacement.commander(1.0, 0.0, 0.0, 0.1)
    assert faux.deplacement.verite()[1] == REPERE


def test_commande_jumeau_refuse_les_options_incompatibles(capsys):
    assert principal_slam(["faux-service", "--jumeau"]) == 2
    assert "--lieu" in capsys.readouterr().out
    assert principal_slam(["faux-service", "--jumeau", "--lieu", "demo", "--gazebo"]) == 2
    assert "ne se combine pas" in capsys.readouterr().out


def test_commande_jumeau_lieu_inconnu(capsys, tmp_path):
    assert principal_slam(["faux-service", "--jumeau", "--lieu", str(tmp_path / "nulle_part")]) == 1
    assert "Erreur dans le lieu" in capsys.readouterr().out
