"""Tests de l'évaluation de la reconnaissance (atelier.scan.evaluation, section 9.8 du plan), sans ROS.

Une reconnaissance « parfaite » (atelier.lieu.reconnaissance_depuis_monde) du lieu demo, sur la carte
du monde où l'on a dessiné la personne debout (le scan la voit, la carte du monde non), donne 1
partout ; chaque défaut ajouté fait baisser la bonne mesure, et seulement elle.
"""
import copy
import json
import math
import subprocess
import sys

import numpy as np
import pytest

from atelier import RACINE
from atelier import lieu as L
from atelier.scan import evaluation as E

LIEU_DEMO = RACINE / "lieux" / "demo"
PYTHON = RACINE / ".venv-projet" / "bin" / "python"


@pytest.fixture(scope="module")
def demo():
    """Monde du demo, sa carte (avec la personne debout dessinée) et sa reconnaissance parfaite."""
    monde = L.charger_monde(LIEU_DEMO, "rdc")
    info, image = L.charger_carte(L.chemin_carte(LIEU_DEMO, "rdc"))
    image = np.array(image, copy=True)
    X, Y = L.centres_pixels(info)
    for o in monde.objets:
        if o.categorie_effective == "personne":
            image[np.hypot(X - o.centre[0], Y - o.centre[1]) <= o.rayon] = 0
    return {"monde": monde, "info": info, "image": image,
            "parfaite": L.reconnaissance_depuis_monde(monde, "rdc")}


def evaluer(demo, reco):
    return E.evaluer(reco, demo["monde"], demo["info"], demo["image"])


def test_reconnaissance_parfaite(demo):
    b = evaluer(demo, demo["parfaite"])
    assert b["murs"]["rappel"] == 1.0 and b["murs"]["precision"] == 1.0
    assert b["murs"]["murs_retrouves"] == b["murs"]["murs_vus"] == 18
    assert b["passages"]["vus"] == 5 and b["passages"]["rappel"] == 1.0 and b["passages"]["precision"] == 1.0
    assert b["objets"]["vus"] == 12 and b["objets"]["detection"] == 1.0 and b["objets"]["categorie"] == 1.0
    assert b["objets"]["retrouves_stricts"] == 12
    assert b["objets"]["faux"] == []
    assert b["personnes"]["ok"] and b["personnes"]["details"][0]["pixels_apres_adoption"] == 0
    assert b["tout_atteint"]
    assert all(o["atteint"] for o in b["objectifs"].values())
    texte = E.texte_bilan(b)
    assert "Murs : rappel 100 %" in texte and "tous atteints" in texte


def test_mur_manquant(demo):
    reco = copy.deepcopy(demo["parfaite"])
    reco["murs"] = [m for m in reco["murs"] if m["id"] not in ("bloc_sud", "bloc_nord")]   # 2 × 20 m de mur
    b = evaluer(demo, reco)
    assert b["murs"]["rappel"] < 0.9 and b["murs"]["precision"] == 1.0
    assert b["murs"]["murs_retrouves"] == 16
    assert not b["objectifs"]["murs_rappel"]["atteint"] and b["objectifs"]["murs_precision"]["atteint"]


def test_mur_decale_ou_tourne(demo):
    reco = copy.deepcopy(demo["parfaite"])
    m = next(m for m in reco["murs"] if m["id"] == "bloc_sud")
    m["de"], m["a"] = [5.0, 8.5 + 0.3], [25.0, 8.5 + 0.3]                       # 30 cm plus loin
    b = evaluer(demo, reco)
    assert b["murs"]["precision"] < 1.0 and b["murs"]["rappel"] < 1.0
    assert "bloc_sud" in b["murs"]["murs_faux"]


def test_mur_non_garde_ne_compte_pas(demo):
    reco = copy.deepcopy(demo["parfaite"])
    next(m for m in reco["murs"] if m["id"] == "ext_sud")["a_garder"] = False
    assert evaluer(demo, reco)["murs"]["rappel"] < 1.0


def test_passages(demo):
    reco = copy.deepcopy(demo["parfaite"])
    p = reco["passages"][0]
    p["de"] = [p["de"][0] + 0.5, p["de"][1]] if p["de"][1] == p["a"][1] else [p["de"][0], p["de"][1] + 0.5]
    b = evaluer(demo, reco)                                  # milieu déplacé, largeur changée
    assert b["passages"]["trouves"] == 4 and b["passages"]["rappel"] == pytest.approx(0.8)
    assert b["passages"]["precision"] == pytest.approx(0.8) and b["passages"]["faux"] == [p["id"]]
    reco["passages"] = []
    b = evaluer(demo, reco)
    assert b["passages"]["rappel"] == 0.0 and b["passages"]["precision"] == 1.0


def test_categorie_fausse(demo):
    reco = copy.deepcopy(demo["parfaite"])
    next(o for o in reco["objets"] if o["id"] == "table_cdi")["categorie"] = "chaise"
    b = evaluer(demo, reco)
    assert b["objets"]["detection"] == 1.0 and b["objets"]["categorie"] == pytest.approx(11 / 12)
    assert b["objets"]["par_categorie"]["table"]["bonne_categorie"] == 1
    assert "table_cdi (table) : reconnu chaise" in E.texte_bilan(b)


def test_objet_manquant_ou_decale(demo):
    reco = copy.deepcopy(demo["parfaite"])
    reco["objets"] = [o for o in reco["objets"] if o["id"] != "poteau_1"]
    o = next(o for o in reco["objets"] if o["id"] == "banc_hall")
    o["centre"] = [o["centre"][0] + 0.4, o["centre"][1]]                      # apparié (0,5 m), pas strict (0,3 m)
    b = evaluer(demo, reco)
    assert b["objets"]["apparies"] == 11 and b["objets"]["detection"] == pytest.approx(11 / 12)
    assert b["objets"]["retrouves_stricts"] == 10


def test_faux_objets(demo):
    reco = copy.deepcopy(demo["parfaite"])
    loin = {"id": "inconnu_1", "categorie": "inconnu", "forme": "boite", "centre": [15.0, 13.0],
            "taille": [0.5, 0.5, 1.0], "cap": 0.0, "confiance": 0.3, "a_garder": True}
    pres_d_un_mur = dict(loin, id="inconnu_2", centre=[15.0, 14.3])
    decoche = dict(loin, id="inconnu_3", centre=[12.0, 7.0], a_garder=False)
    reco["objets"] += [loin, pres_d_un_mur, decoche]
    b = evaluer(demo, reco)
    assert b["objets"]["faux"] == ["inconnu_1"]
    assert b["objectifs"]["faux_objets_max"]["valeur"] == 1 and b["objectifs"]["faux_objets_max"]["atteint"]


def test_personne_cochee_ou_non_reconnue(demo):
    reco = copy.deepcopy(demo["parfaite"])
    next(o for o in reco["objets"] if o["id"] == "personne_b204")["a_garder"] = True
    b = evaluer(demo, reco)
    assert not b["personnes"]["ok"] and b["personnes"]["personnes_gardees"] == ["personne_b204"]
    reco = copy.deepcopy(demo["parfaite"])
    next(o for o in reco["objets"] if o["id"] == "personne_b204")["categorie"] = "poteau"
    b = evaluer(demo, reco)
    assert not b["personnes"]["ok"] and not b["tout_atteint"]
    # plus petite que la vraie : des pixels de la personne restent sur la carte après l'adoption
    reco = copy.deepcopy(demo["parfaite"])
    next(o for o in reco["objets"] if o["id"] == "personne_b204")["rayon"] = 0.1
    b = evaluer(demo, reco)
    assert b["personnes"]["details"][0]["pixels_apres_adoption"] > 0 and not b["personnes"]["ok"]


def test_ce_qui_n_est_pas_vu_ne_compte_pas(demo):
    """Sur une carte où seule la moitié ouest a été vue, les murs et objets de l'est ne comptent pas
    dans les rappels."""
    image = np.array(demo["image"], copy=True)
    X, _ = L.centres_pixels(demo["info"])
    image[(X > 15.0) & (image == 0)] = 254
    reco = copy.deepcopy(demo["parfaite"])
    reco["objets"] = [o for o in reco["objets"] if o["centre"][0] < 15.0]
    b = E.evaluer(reco, demo["monde"], demo["info"], image)
    assert b["objets"]["detection"] == 1.0 and b["objets"]["vus"] < 12
    assert not b["personnes"]["ok"]                          # personne_b204 (x = 21) n'a pas été vue
    assert b["personnes"]["details"][0]["vue"] is False


def test_nuage_synthetique():
    """Lancer de rayons : points sur les surfaces visibles seulement, bruit et trous, même résultat avec
    la même graine."""
    monde = L.Monde(L.Emprise(0, 0, 6, 4), L.Pose(1, 1, 0),
                    [L.Mur("m1", (0.0, 0.0), (6.0, 0.0), 0.2, 2.5), L.Mur("m2", (6.0, 0.0), (6.0, 4.0), 0.2, 2.5)],
                    [L.Objet.cylindre("p1", (3.0, 2.0), 0.2, 2.0)], [])
    vues = [(1.0, 2.0), (2.0, 3.0)]
    a = E.nuage_synthetique(monde, vues, bruit=0.0, graine=1)
    assert len(a) > 1000
    assert np.array_equal(a, E.nuage_synthetique(monde, vues, bruit=0.0, graine=1))
    # aucun point dans l'épaisseur des murs, ni derrière le poteau vu depuis les deux points de vue
    dans_m1 = (np.abs(a[:, 1]) < 0.07) & (a[:, 0] > 0.5) & (a[:, 0] < 5.5) & (a[:, 2] > 0.05)
    assert not dans_m1.any()
    dans_poteau = np.hypot(a[:, 0] - 3.0, a[:, 1] - 2.0) < 0.15
    assert not dans_poteau.any()
    bruite = E.nuage_synthetique(monde, vues, bruit=0.02, trous=10, graine=1)
    assert len(bruite) < len(a) * 1.5 and not np.array_equal(bruite, a)


def test_points_de_vue_du_demo():
    vues = E.points_de_vue_du_lieu(LIEU_DEMO, "rdc", pas=1.0)
    assert len(vues) > 50
    monde = L.charger_monde(LIEU_DEMO, "rdc")
    assert all(monde.emprise.contient(x, y) for x, y in vues)


def test_ligne_de_commande(demo, tmp_path):
    lieu = L.copier_lieu(LIEU_DEMO, tmp_path / "demo")
    session = tmp_path / "session"
    session.mkdir()
    L.ecrire_reconnaissance(session, demo["parfaite"])
    info = L.InfoCarte(image="carte.pgm", resolution=demo["info"].resolution, origin=demo["info"].origin)
    L.enregistrer_carte(session / "carte.yaml", info, demo["image"])
    python = str(PYTHON if PYTHON.exists() else sys.executable)
    commande = [python, "-m", "atelier.scan.evaluation", "--session", str(session), "--reference", str(lieu)]
    sortie = subprocess.run(commande, capture_output=True, text=True, cwd=RACINE, timeout=120)
    assert sortie.returncode == 0, sortie.stderr
    assert "Murs : rappel 100 %" in sortie.stdout and "tous atteints" in sortie.stdout
    sortie = subprocess.run(commande + ["--json"], capture_output=True, text=True, cwd=RACINE, timeout=120)
    bilan = json.loads(sortie.stdout)
    assert bilan["tout_atteint"] is True and bilan["objectifs"]["murs_rappel"]["valeur"] == 1.0
    # une reconnaissance abîmée : code 1 avec --exiger
    abimee = copy.deepcopy(demo["parfaite"])
    abimee["murs"], abimee["passages"] = abimee["murs"][:5], []
    L.ecrire_reconnaissance(session, abimee)
    sortie = subprocess.run(commande + ["--exiger"], capture_output=True, text=True, cwd=RACINE, timeout=120)
    assert sortie.returncode == 1 and "pas tous atteints" in sortie.stdout
    erreur = subprocess.run([python, "-m", "atelier.scan.evaluation", "--session", str(tmp_path / "rien"),
                             "--reference", str(lieu)], capture_output=True, text=True, cwd=RACINE, timeout=120)
    assert erreur.returncode == 1 and erreur.stderr.startswith("Erreur :")
    assert math.isfinite(bilan["murs"]["precision"])
