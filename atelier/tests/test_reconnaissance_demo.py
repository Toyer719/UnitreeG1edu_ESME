"""Reconnaissance du lieu demo (section 9.8 du plan), sans ROS ni Gazebo : objectifs de la vague.

Nuages synthétiques fabriqués depuis lieux/demo/mondes/rdc.monde.yaml (lu, jamais modifié) par
lancer de rayons le long des couloirs des itinéraires, avec du bruit, des trous et une personne
debout ajoutée dans le couloir sud. Deux capteurs : un LiDAR dense (−30° à +52°, 1° × 0,5°) et un
LiDAR clairsemé comme celui du robot proxy (16 lignes de −7° à +52°, 1°, à 1,245 m).

Un vrai scan simulé (g1-scan, ou enregistrement du critère 7 passé par g1-carte-3d et g1-carte-2d)
s'évalue aussi : G1_SCAN_DEMO=DOSSIER (nuage.pcd et carte.yaml dedans) ; sinon ce test est sauté.
"""
import os
from pathlib import Path

import pytest

from atelier import RACINE
from atelier import lieu as L
from atelier.scan import evaluation as E
from atelier.scan.reconnaissance import reconnaitre

LIEU_DEMO = RACINE / "lieux" / "demo"
PERSONNE_AJOUTEE = (12.0, 6.6, 0.25, 1.75)          # x, y, rayon, hauteur : dans le couloir sud


def _verifier(resultat, bilan, dossier):
    assert bilan["tout_atteint"], E.texte_bilan(bilan)
    assert resultat["duree_s"] < 60
    reco = L.lire_reconnaissance(dossier)
    personnes = [o for o in reco["objets"] if o["categorie"] == "personne"]
    assert personnes and not any(o["a_garder"] for o in personnes)
    monde = L.charger_fichier(Path(dossier) / "monde_scan.monde.yaml", "monde")
    assert L.valider_donnees("monde", monde) == []
    assert len(monde["murs"]) >= 18 and not monde["pietons"]


def test_demo_dense_avec_personne_ajoutee(tmp_path):
    monde = L.charger_monde(LIEU_DEMO, "rdc")
    vues = E.points_de_vue_du_lieu(LIEU_DEMO, "rdc", pas=0.5)
    resultat, bilan = E.essayer_sur_monde(monde, vues, tmp_path, personnes=[PERSONNE_AJOUTEE],
                                          bruit=0.015, trous=40, graine=1)
    _verifier(resultat, bilan, tmp_path)
    assert len(bilan["personnes"]["details"]) == 2           # personne_b204 et la personne ajoutée
    assert bilan["murs"]["rappel"] >= 0.95 and bilan["passages"]["trouves"] == 5


def test_demo_lidar_du_robot_proxy(tmp_path):
    monde = L.charger_monde(LIEU_DEMO, "rdc")
    vues = E.points_de_vue_du_lieu(LIEU_DEMO, "rdc", pas=0.1)
    resultat, bilan = E.essayer_sur_monde(monde, vues, tmp_path, personnes=[PERSONNE_AJOUTEE],
                                          champ_vertical=(-7.0, 52.0), pas_vertical=59.0 / 15, pas_horizontal=1.0,
                                          bruit=0.01, graine=2)
    _verifier(resultat, bilan, tmp_path)


@pytest.mark.skipif(not os.environ.get("G1_SCAN_DEMO"), reason="G1_SCAN_DEMO (dossier d'un scan simulé du demo) "
                                                               "non donné")
def test_vrai_scan_simule(tmp_path):
    source = Path(os.environ["G1_SCAN_DEMO"])
    resultat = reconnaitre(source / "nuage.pcd", source / "carte.yaml", tmp_path, {"depart_robot": (2.5, 10.0, 0.0)})
    info, image = L.charger_carte(source / "carte.yaml")
    bilan = E.evaluer(tmp_path / "reconnaissance.yaml", L.charger_monde(LIEU_DEMO, "rdc"), info, image)
    print(E.texte_bilan(bilan))
    _verifier(resultat, bilan, tmp_path)
