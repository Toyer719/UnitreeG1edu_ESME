"""Tests de g1-scan carte-unitree (vague 5, décision S7, section 12.5 du plan) et de la carte globale du faux service
de la répétition (/unitree/slam_relocation/global_map, publiée une fois après chaque 1804 réussi).

  ~/robot-g1/.venv-projet/bin/python -m pytest ~/robot-g1/atelier/tests/test_scan_carte_unitree.py -v

Sans robot : conversions et fichiers sans ROS ; puis, avec ROS 2 (domaine $ROS_DOMAIN_ID, 77 par défaut),
le frontal du faux service publie la carte et la commande la reçoit. Copies de lieux/demo seulement.
"""
import json
import math
import os

import numpy as np
import pytest

import atelier
from atelier import lieu as L
from atelier.scan import carte_unitree as CU
from atelier.scan import slam_client as sc
from atelier.scan.faux_slam import POSE_LIDAR, SUJETS_JUMEAU, FauxSlamJumeau, carte_globale_du_monde

os.environ.setdefault("ROS_DOMAIN_ID", "77")
DEMO = atelier.RACINE / "lieux" / "demo"
REPERE = (2.5, 10.0, 0.0)


@pytest.fixture
def demo(tmp_path):
    return L.copier_lieu(DEMO, tmp_path / "demo")


def test_conversions_du_repere_d_unitree():
    alea = np.random.default_rng(0)
    points = alea.uniform(-10, 10, (100, 3))
    repere = (3.0, 9.0, 0.5)
    u = CU.vers_unitree(points, repere)
    assert CU.vers_carte(u, repere) == pytest.approx(points)
    # l'origine de la carte d'Unitree est en (3 ; 9) dans map, tournée de 0,5 rad
    assert CU.vers_carte([[0.0, 0.0, 1.0]], repere)[0] == pytest.approx([3.0, 9.0, 1.0])
    assert CU.vers_carte([[1.0, 0.0, 0.0]], repere)[0] == pytest.approx([3.0 + math.cos(0.5), 9.0 + math.sin(0.5), 0.0])
    assert {nom for nom, _ in CU.qos_essayees()} == {"fiable, transient_local", "fiable", "au mieux"}


def test_carte_globale_du_faux_service(demo):
    carte = carte_globale_du_monde(demo, "rdc", REPERE)
    assert len(carte) > 10000
    assert np.percentile(carte[:, 2], 1) == pytest.approx(-POSE_LIDAR[2], abs=0.01)      # sol sous le LiDAR
    dans_map = CU.vers_carte(carte, REPERE)
    e = L.charger_monde(demo, "rdc").emprise
    assert dans_map[:, 0].min() >= e.xmin - 0.2 and dans_map[:, 0].max() <= e.xmax + 0.2
    L.chemin_monde(demo, "rdc").unlink()
    assert carte_globale_du_monde(demo, "rdc", REPERE) is None                              # étage sans monde


def test_carte_globale_d_un_etage_scanne(demo):
    """Un étage adopté depuis un scan (monde réduit à la carte extrudée) : la carte globale est son nuage
    (cartes/rdc.nuage), réduit à 0,1 m, et plus les murs dessinés ; même sans monde."""
    murs = np.column_stack([np.repeat(np.arange(0.0, 20.0, 0.05), 20), np.full(8000, 5.0),
                            np.tile(np.arange(0.0, 2.0, 0.1), 400)])
    sol = np.column_stack([np.repeat(np.arange(0.0, 20.0, 0.05), 40), np.tile(np.arange(3.0, 5.0, 0.05), 400),
                           np.zeros(16000)])
    points = np.vstack([murs, sol])
    L.ecrire_nuage(L.chemin_nuage(demo, "rdc"), points,
                   L.entete_nuage(points, 0.05, {"plan": [0.0, 0.0, 0.0], "inclinaison_deg": 0.0, "methode": "impose"},
                                  "scan", session="2026-10-27_14h22", etage="rdc"))
    carte = carte_globale_du_monde(demo, "rdc", REPERE)
    dans_map = CU.vers_carte(carte, REPERE)
    assert 0.2 * len(points) / 4 < len(carte) < len(points) / 2           # réduit à une grille de 0,1 m
    assert dans_map[:, 1].min() > 2.9 and dans_map[:, 1].max() < 5.1        # le nuage, pas les murs du demo
    assert np.percentile(carte[:, 2], 1) == pytest.approx(-POSE_LIDAR[2], abs=0.05)   # sol sous le LiDAR
    assert carte[:, 2].max() == pytest.approx(1.9 - POSE_LIDAR[2], abs=0.1)              # haut du mur
    L.chemin_monde(demo, "rdc").unlink()
    assert len(carte_globale_du_monde(demo, "rdc", REPERE)) == len(carte)  # sans monde : le nuage suffit


def test_enregistrer_la_carte(demo):
    carte = carte_globale_du_monde(demo, "rdc", REPERE)
    r = CU.enregistrer(demo, "rdc", carte, afficher=lambda *_: None)
    assert r["pcd"] == demo / "cartes" / "rdc_unitree.pcd" and r["pcd"].is_file()
    points, entete = L.lire_nuage(L.chemin_nuage(demo, "rdc", "unitree"))
    assert entete["source"] == "unitree" and entete["etage"] == "rdc" and entete["grille"] == 0.05
    h = points[:, 2]
    assert abs(float(np.median(h[np.abs(h) < 0.1]))) < 0.02                    # sol à z = 0
    # x et y : repère map de l'étage (repere_unitree du demo : son départ (2,5 ; 10 ; 0))
    from atelier.scan.carte3d import lire_pcd
    pcd = lire_pcd(r["pcd"])
    assert pcd[:, 0].min() > -0.5 and pcd[:, 1].max() < 20.5
    with pytest.raises(ValueError):
        CU.enregistrer(demo, "rdc", np.zeros((0, 3)))


def test_commande_sans_carte(demo, capsys):
    pytest.importorskip("rclpy")
    lignes = []
    assert CU.commande(demo, "rdc", delai=1.0, sujet="/essai_carte_unitree/rien", afficher=lignes.append) == 1
    assert any("Repérer le robot" in ligne and "robot.sh" in ligne for ligne in lignes)
    assert not (demo / "cartes" / "rdc_unitree.pcd").exists()
    assert CU.commande(demo, "cave", delai=0.1, afficher=lignes.append) == 1
    assert "pas d'étage" in lignes[-1]


def test_le_faux_service_publie_la_carte_et_la_commande_la_recoit(demo):
    """Après un 1804 réussi, le frontal ROS 2 du faux service publie la carte globale (QoS fiable,
    transient_local) ; g1-scan carte-unitree, lancé ensuite, la reçoit quand même et l'enregistre."""
    pytest.importorskip("rclpy")
    pytest.importorskip("unitree_api.msg")
    from unitree_api.msg import Request
    from atelier.scan.faux_slam import FrontalRos
    carte = carte_globale_du_monde(demo, "rdc", REPERE)
    faux = FauxSlamJumeau(REPERE, ["repetition.pcd"], bavard=False)
    frontal = FrontalRos(faux, bavard=False, carte_globale=carte)
    try:
        faux.deplacement.noter(1.0, REPERE)                     # vérité terrain : le robot est au départ
        requete = Request()
        requete.header.identity.id, requete.header.identity.api_id = 1, sc.API_RELOCALISER
        requete.parameter = json.dumps(sc.parametres_relocaliser(0.0, 0.0, 0.0, "repetition.pcd"))
        frontal._sur_requete(requete)
        assert faux.mode == "relocalise" and frontal.cartes_publiees == 1
        lignes = []
        code = CU.commande(demo, "rdc", delai=15.0, afficher=lignes.append)
        assert code == 0, lignes
        assert any("QoS" in ligne for ligne in lignes) and SUJETS_JUMEAU["carte_globale"] == CU.SUJET
        points, entete = L.lire_nuage(L.chemin_nuage(demo, "rdc", "unitree"))
        assert entete["source"] == "unitree" and len(points) > 1000
        # un 1804 refusé ne publie rien de plus
        faux.deplacement.noter(2.0, (12.0, 10.0, 0.0))
        frontal._sur_requete(requete)
        assert frontal.cartes_publiees == 1
    finally:
        frontal.fermer()
