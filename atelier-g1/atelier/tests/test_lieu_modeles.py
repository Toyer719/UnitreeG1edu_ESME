"""Tests des dataclasses du paquet de lieu (atelier.lieu.modeles) : aller-retour dict ↔ objet.

  ~/robot-g1/.venv-projet/bin/python -m pytest ~/robot-g1/atelier/tests/test_lieu_modeles.py -v
"""
import math
from pathlib import Path

import numpy as np
import pytest
import yaml

import atelier
from atelier.lieu import (Couloir, Emprise, Etage, InfoCarte, Itineraires, Lieu, Monde, Mur, Noeud, Objet,
                          Pieton, Pose, PoseEtage, Salle, Zone, Zones, valider_donnees)

DEMO = atelier.RACINE / "lieux" / "demo"
FICHIERS = {"lieu": ("lieu.yaml", Lieu), "salles": ("salles.yaml", None),
            "itineraires": ("itineraires.yaml", Itineraires), "zones": ("zones.yaml", Zones),
            "monde": ("mondes/rdc.monde.yaml", Monde)}


def lire(nom):
    return yaml.safe_load((DEMO / FICHIERS[nom][0]).read_text(encoding="utf-8"))


@pytest.mark.parametrize("nom", list(FICHIERS))
def test_aller_retour_des_fichiers_du_demo(nom):
    """Fichier du demo → objets → dictionnaire : on retrouve exactement le fichier."""
    donnees = lire(nom)
    if nom == "salles":
        objets = [Salle.depuis_dict(s) for s in donnees]
        assert [s.vers_dict() for s in objets] == donnees
        assert [Salle.depuis_dict(s.vers_dict()) for s in objets] == objets
    else:
        classe = FICHIERS[nom][1]
        objet = classe.depuis_dict(donnees)
        assert objet.vers_dict() == donnees
        assert classe.depuis_dict(objet.vers_dict()) == objet


def test_aller_retour_de_chaque_classe():
    exemples = [Pose(1.0, 2.0, 0.5), PoseEtage("rdc", 1.0, 2.0, -0.5), Etage("e1", "Étage 1", "scan"),
                Salle("b204", "Salle B204", "rdc", Pose(12.4, -3.1, 1.57), ["labo"], "Voici le labo."),
                Noeud("rdc", 7.5, 3.0), Couloir("accueil", "c1"),
                Zone("rdc", [(0, 0), (4, 0), (4, 4)], "Hall", 0.2), Zone("rdc", [(10, 0), (12, 0), (12, 1)]),
                Emprise(0, 0, 30, 20), Mur("m1", (0, 0), (30, 0), 0.15, 2.5),
                Objet.boite("t1", (5, 3), (1.2, 0.6, 0.75), 0.0), Objet.cylindre("p1", (8, 2), 0.2, 2.5),
                Objet.meuble("c1", "chaise", (5, 4), 1.57),
                Pieton("h1", [(2, 3), (25, 3)], 1.0, True),
                InfoCarte("rdc.pgm", 0.05, (-0.05, -0.05, 0.0), autres={"mode": "trinary"})]
    for objet in exemples:
        assert type(objet).depuis_dict(objet.vers_dict()) == objet, type(objet).__name__


def test_valeurs_par_defaut_des_champs_facultatifs():
    salle = Salle.depuis_dict({"id": "cdi", "nom": "CDI", "etage": "rdc", "pose": {"x": 1, "y": 2, "theta": 0}})
    assert salle.alias == [] and salle.phrase_arrivee == ""
    monde = Monde.depuis_dict({"version": 1, "emprise": {"min": [0, 0], "max": [5, 5]},
                               "depart_robot": {"x": 1, "y": 1, "theta": 0}})
    assert monde.murs == [] and monde.objets == [] and monde.pietons == []
    lieu = Lieu.depuis_dict({"version": 1, "nom": "L", "langue": "fr", "etages": [
        {"id": "rdc", "nom": "R", "source_carte": "monde"}], "accueil": {"etage": "rdc", "x": 1, "y": 1, "theta": 0}})
    assert lieu.carte_unitree is None
    assert lieu.vers_dict()["carte_unitree"] is None
    assert Zone.depuis_dict({"etage": "rdc", "polygone": [[0, 0], [1, 0], [1, 1]]}).nom == ""


def test_objets_ne_gardent_que_les_champs_de_leur_type():
    """Le schéma refuse un champ d'un autre type (ex. rayon sur une boîte)."""
    assert set(Objet.boite("t", (0, 0), (1, 1, 1)).vers_dict()) == {"id", "type", "centre", "taille", "cap"}
    assert set(Objet.cylindre("p", (0, 0), 0.2, 2).vers_dict()) == {"id", "type", "centre", "rayon", "hauteur"}
    assert set(Objet.meuble("c", "chaise", (0, 0)).vers_dict()) == {"id", "type", "modele", "centre", "cap"}
    assert set(Zone("rdc", [(0, 0), (1, 0), (1, 1)]).vers_dict()) == {"etage", "polygone"}


def test_zones_vides_par_defaut_valides():
    assert valider_donnees("zones", Zones().vers_dict()) == []
    assert valider_donnees("itineraires", Itineraires().vers_dict()) == []


def test_empreintes_et_hauteurs():
    forme, coins = Objet.boite("t", (5, 3), (2.0, 1.0, 0.75), math.pi / 2).empreinte()
    assert forme == "polygone"
    xs, ys = sorted(round(p[0], 9) for p in coins), sorted(round(p[1], 9) for p in coins)
    assert (xs[0], xs[-1], ys[0], ys[-1]) == (4.5, 5.5, 2.0, 4.0)       # tournée de 90°
    assert Objet.meuble("p", "poubelle", (1, 1)).empreinte() == ("cercle", (1, 1), 0.25)
    assert Objet.cylindre("c", (1, 1), 0.2, 2.5).empreinte() == ("cercle", (1, 1), 0.2)
    _, coins_chaise = Objet.meuble("c", "chaise", (0, 0)).empreinte()
    assert max(p[0] for p in coins_chaise) == pytest.approx(0.225)
    assert Objet.meuble("b", "banc", (0, 0)).hauteur_totale() == 0.45
    assert Objet.boite("t", (0, 0), (1, 1, 0.75)).hauteur_totale() == 0.75
    assert Objet.cylindre("c", (0, 0), 0.2, 2.5).hauteur_totale() == 2.5


def test_mur_sans_debordement():
    mur = Mur("m", (0, 6), (11, 6), 0.2, 2.5)
    assert mur.longueur == 11 and mur.cap == 0 and mur.centre == (5.5, 6)
    xs = sorted(p[0] for p in mur.coins())
    ys = sorted(p[1] for p in mur.coins())
    assert xs[0] == pytest.approx(0) and xs[-1] == pytest.approx(11)      # longueur exacte
    assert ys[0] == pytest.approx(5.9) and ys[-1] == pytest.approx(6.1)   # épaisseur centrée


def test_itineraires_longueur_voisins_et_couloir():
    itin = Itineraires({"a": Noeud("rdc", 0, 0), "b": Noeud("rdc", 3, 4), "c": Noeud("rdc", 3, 0)},
                       [Couloir("a", "b"), Couloir("c", "a")])
    assert itin.longueur(itin.couloirs[0]) == 5
    assert sorted(itin.voisins("a")) == ["b", "c"]
    a, b = itin.couloirs[0]
    assert (a, b) == ("a", "b")


def test_lieu_accesseurs(tmp_path):
    lieu = Lieu("L", [Etage("rdc", "R")], PoseEtage("rdc", 1, 1, 0),
                salles=[Salle("accueil", "Accueil", "rdc", Pose(1, 1, 0))], dossier=tmp_path / "essai")
    assert lieu.id == "essai"
    assert lieu.etage("rdc").nom == "R" and lieu.etage("r2") is None
    assert lieu.salle("accueil").nom == "Accueil" and lieu.salle("b204") is None
    assert Lieu("L", [], PoseEtage("rdc", 1, 1)).id is None


def test_nombres_numpy_ecrits_comme_des_nombres_simples():
    mur = Mur("m", (np.float64(1.5), np.float32(2.0)), (np.int64(3), 4), np.float64(0.15), 2.5)
    d = mur.vers_dict()
    assert type(d["de"][0]) is float and type(d["a"][0]) is int and type(d["epaisseur"]) is float
    yaml.safe_dump(d)    # ne lève pas d'erreur


def test_info_carte_chemin_image():
    info = InfoCarte.depuis_dict({"image": "rdc.pgm", "resolution": 0.05, "origin": [0, 0, 0], "negate": 0,
                                  "occupied_thresh": 0.65, "free_thresh": 0.196, "mode": "trinary"},
                                 chemin="/x/cartes/rdc.yaml", largeur=10, hauteur=5)
    assert info.chemin_image == Path("/x/cartes/rdc.pgm")
    assert info.autres == {"mode": "trinary"} and info.vers_dict()["mode"] == "trinary"
    assert InfoCarte("a.pgm").chemin_image is None
