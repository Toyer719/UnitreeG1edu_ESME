"""Tests de la carte 2D et du masque Keepout générés depuis le monde inventé (atelier.monde).

Les tests travaillent sur une copie de lieux/demo dans un dossier temporaire.
Les pixels sont toujours trouvés avec atelier.lieu.monde_vers_pixel (contrat 4.1).
"""
import math

import numpy as np
import pytest

import atelier
from atelier import lieu as L
from atelier import monde as M
from atelier.lieu import Emprise, Monde, Mur, Objet, Pieton, Pose, Zone, Zones

DEMO = atelier.RACINE / "lieux" / "demo"


@pytest.fixture
def demo(tmp_path):
    """Dossier d'une copie du lieu demo, déjà généré."""
    dossier = L.copier_lieu(DEMO, tmp_path / "demo")
    M.generer(dossier, "rdc")
    return dossier


@pytest.fixture
def carte(demo):
    return L.charger_carte(L.chemin_carte(demo, "rdc"))


def pixel(info, image, x, y):
    colonne, ligne = L.monde_vers_pixel(x, y, info)
    assert L.dans_image(colonne, ligne, info), f"({x}, {y}) hors de la carte"
    return int(image[ligne, colonne])


def petit_monde(**elements):
    """Monde vide de 10 × 10 m, plus les éléments donnés (murs, objets, pietons)."""
    return Monde(Emprise(0, 0, 10, 10), Pose(1, 1, 0), **elements)


# ---------------------------------------------------------------- carte du demo

def test_fichiers_et_yaml_conformes(demo, carte):
    info, image = carte
    assert (demo / "cartes" / "rdc.pgm").is_file()
    assert info.image == "rdc.pgm"
    assert info.resolution == 0.05
    assert info.origin == (-0.05, -0.05, 0.0)
    assert (info.negate, info.occupied_thresh, info.free_thresh) == (0, 0.65, 0.196)
    # 30 × 20 m à 0,05 m, plus une marge d'un pixel de chaque côté
    assert (info.largeur, info.hauteur) == (602, 402) == (image.shape[1], image.shape[0])
    assert image.dtype == np.uint8
    assert set(np.unique(image)) <= {M.OCCUPE, M.LIBRE, M.INCONNU}


@pytest.mark.parametrize("x, y, quoi", [
    (15.0, 0.0, "mur extérieur sud"),
    (30.0, 10.0, "mur extérieur est"),
    (11.0, 5.5, "mur_sud_2, côté sud du couloir sud"),
    (15.0, 8.5, "bloc_sud"),
    (15.0, 11.5, "bloc_nord"),
    (15.0, 14.5, "mur_nord_2"),
    (15.0, 17.0, "cloison_3"),
    (10.0, 2.0, "cloison_1"),
])
def test_pixel_sur_un_mur_vaut_0(carte, x, y, quoi):
    assert pixel(*carte, x, y) == 0, quoi


@pytest.mark.parametrize("x, y, quoi", [
    (15.0, 7.0, "milieu du couloir sud"),
    (15.0, 13.0, "milieu du couloir nord"),
    (27.5, 7.0, "liaison est"),
    (2.5, 10.0, "accueil"),
    (7.0, 5.5, "passage de vie scolaire (porte de 1,2 m)"),
    (9.0, 14.5, "passage de l'amphi"),
    (14.0, 7.8, "trajet du piéton sud : les piétons ne vont pas sur la carte"),
    (15.0, 10.0, "intérieur du bloc fermé : libre, mais inaccessible"),
])
def test_pixel_au_milieu_d_un_couloir_vaut_254(carte, x, y, quoi):
    assert pixel(*carte, x, y) == 254, quoi


def test_epaisseur_d_un_mur_et_largeur_d_un_passage(carte):
    info, image = carte
    # mur_sud_2 : 0,15 m centré sur y = 5,5 → pixels de 5,40 à 5,60 (recouvrement partiel compté)
    colonne, _ = L.monde_vers_pixel(11.0, 5.5, info)
    _, haut = L.monde_vers_pixel(11.0, 5.62, info)
    _, bas = L.monde_vers_pixel(11.0, 5.38, info)
    assert list(image[haut:bas + 1, colonne]) == [254, 0, 0, 0, 0, 254]
    # Passage de vie scolaire : murs jusqu'à x = 6,4 et depuis x = 7,6 → 24 pixels libres (1,2 m)
    c0, ligne = L.monde_vers_pixel(6.0, 5.5, info)
    c1, _ = L.monde_vers_pixel(8.0, 5.5, info)
    rangee = image[ligne, c0:c1 + 1]
    assert (rangee == 254).sum() == 24


def test_objets_sur_la_carte(carte):
    for x, y, quoi in [(26.0, 10.0, "poteau_1"), (25.0, 2.5, "table_cdi"), (24.6, 1.7, "chaise_cdi_1"),
                       (0.5, 7.0, "banc_hall"), (4.5, 14.1, "poubelle_hall"), (7.5, 18.8, "bureau_amphi"),
                       (0.7, 10.0, "banque_accueil")]:
        assert pixel(*carte, x, y) == 0, quoi
    # Poteau de rayon 0,2 : libre à 0,3 m du centre
    assert pixel(*carte, 26.3, 10.0) == 254


def test_banc_tourne_au_quart_de_tour(carte):
    """Le banc (1,5 × 0,4 m, cap 1.5708) occupe exactement 8 colonnes : pas de pixel de trop
    à cause de l'arrondi de π/2."""
    info, image = carte
    c0, ligne = L.monde_vers_pixel(0.2, 7.0, info)
    c1, _ = L.monde_vers_pixel(0.9, 7.0, info)
    assert (image[ligne, c0:c1 + 1] == 0).sum() == 8


def test_coin_de_la_marge_inconnu(carte):
    info, image = carte
    # Pixel du coin haut gauche : dans la marge, et aucun mur ne le recouvre
    assert image[0, 0] == M.INCONNU
    # Le reste de la marge est recouvert par les murs extérieurs, de 0,2 m d'épaisseur
    assert image[0, 10] == M.OCCUPE and image[10, 0] == M.OCCUPE


# ---------------------------------------------------------------- règles de tracé

def test_tranche_objets_bas_ignores():
    monde = petit_monde(
        murs=[Mur("muret", (1, 5), (9, 5), 0.2, 0.08)],                       # 8 cm : sous la tranche
        objets=[Objet.boite("tapis", (5, 2), (2, 1, 0.02)),
                Objet.boite("caisse", (5, 8), (1, 1, 0.3)),
                Objet.cylindre("borne", (2, 8), 0.2, 0.11)])
    info, image = M.fabriquer_carte(monde)
    assert pixel(info, image, 5, 5) == 254
    assert pixel(info, image, 5, 2) == 254
    assert pixel(info, image, 5, 8) == 0
    assert pixel(info, image, 2, 8) == 0


def test_mur_en_biais_sans_trou():
    """Un mur fin à 30° : chaque pixel occupé a un voisin occupé par un côté (pas seulement par
    un coin), donc la planification ne peut pas passer en diagonale entre deux pixels."""
    monde = petit_monde(murs=[Mur("biais", (1, 1), (1 + 8 * math.cos(0.5236), 1 + 8 * math.sin(0.5236)), 0.05, 2.5)])
    info, image = M.fabriquer_carte(monde)
    for t in np.linspace(0.05, 0.95, 50):
        x, y = 1 + 8 * t * math.cos(0.5236), 1 + 8 * t * math.sin(0.5236)
        assert pixel(info, image, x, y) == 0
    # À 0,3 m du mur, de part et d'autre : libre
    nx, ny = -math.sin(0.5236), math.cos(0.5236)
    assert pixel(info, image, 5 + 0.3 * nx, 3.31 + 0.3 * ny) == 254
    occupe = image == 0
    lignes, colonnes = np.nonzero(occupe)
    for li, c in zip(lignes, colonnes):
        voisins = [occupe[li + dl, c + dc] for dl, dc in ((0, 1), (0, -1), (1, 0), (-1, 0))
                   if 0 <= li + dl < image.shape[0] and 0 <= c + dc < image.shape[1]]
        assert any(voisins)
    # Pas de passage en diagonale : deux pixels occupés en diagonale ont un pixel commun occupé
    for li, c in zip(lignes, colonnes):
        for dl, dc in ((1, 1), (1, -1)):
            if 0 <= li + dl < image.shape[0] and 0 <= c + dc < image.shape[1] and occupe[li + dl, c + dc]:
                assert occupe[li + dl, c] or occupe[li, c + dc]


def test_pietons_absents_de_la_carte():
    sans = petit_monde()
    avec = petit_monde(pietons=[Pieton("p", [(2, 5), (8, 5)], 1.0, True)])
    assert np.array_equal(M.fabriquer_carte(sans)[1], M.fabriquer_carte(avec)[1])


def test_emprise_non_multiple_de_la_resolution():
    monde = Monde(Emprise(-1.0, 2.0, 4.03, 5.0), Pose(0, 3, 0))
    info, image = M.fabriquer_carte(monde)
    assert (info.largeur, info.hauteur) == (103, 62)
    assert info.origin == pytest.approx((-1.05, 1.95, 0.0))
    assert pixel(info, image, 0.0, 3.0) == 254


# ---------------------------------------------------------------- masque Keepout

def test_masque_meme_taille_et_origine_que_la_carte(demo, carte):
    info, _ = carte
    masque_info, masque = L.charger_carte(L.chemin_interdit(demo, "rdc"))
    assert masque_info.image == "rdc_interdit.pgm"
    assert (masque_info.largeur, masque_info.hauteur) == (info.largeur, info.hauteur)
    assert masque.shape == carte[1].shape
    assert masque_info.origin == info.origin and masque_info.resolution == info.resolution
    assert set(np.unique(masque)) == {0, 254}


def test_masque_zone_interdite_du_demo(demo):
    info, masque = L.charger_carte(L.chemin_interdit(demo, "rdc"))
    assert pixel(info, masque, 0.9, 13.2) == 0          # escalier
    assert pixel(info, masque, 0.25, 12.25) == 0        # coin de l'escalier
    assert pixel(info, masque, 0.9, 11.0) == 254        # hall, sous l'escalier
    assert pixel(info, masque, 15.0, 7.0) == 254
    # Polygone de 1,4 × 2,1 m : 28 × 42 pixels
    assert (masque == 0).sum() == 28 * 42


def test_masque_autre_etage_et_triangle():
    info, _ = M.fabriquer_carte(petit_monde())
    zones = Zones(interdites=[Zone("etage1", [(1, 1), (3, 1), (3, 3)]),
                              Zone("rdc", [(5, 5), (9, 5), (5, 9)], "triangle")])
    masque_info, masque = M.fabriquer_masque_interdit(zones, "rdc", info, image="rdc_interdit.pgm")
    assert pixel(masque_info, masque, 2.8, 1.5) == 254      # zone d'un autre étage
    assert pixel(masque_info, masque, 6, 6) == 0
    assert pixel(masque_info, masque, 8, 8) == 254          # au-delà de l'hypoténuse
    assert (masque == 0).sum() == pytest.approx(0.5 * 80 * 80, rel=0.03)


def test_masque_sans_zone_tout_libre(tmp_path):
    dossier = L.copier_lieu(DEMO, tmp_path / "demo")
    L.enregistrer_zones(dossier, Zones())
    resultat = M.generer(dossier, "rdc")
    assert resultat.zones_interdites == 0
    _, masque = L.charger_carte(resultat.masque)
    assert (masque == 254).all()


def test_lieu_valide_apres_generation(demo):
    rapport = L.valider_lieu(demo)
    assert rapport.erreurs == []
    assert not any("carte" in m or "masque" in m for m in rapport.avertissements)


def test_etage_scanne_garde_sa_carte(tmp_path):
    """source_carte: scan : la carte n'est pas remplacée, le masque est aligné sur elle."""
    dossier = L.copier_lieu(DEMO, tmp_path / "demo")
    fiche = L.charger_fiche(dossier)
    fiche.etages[0].source_carte = "scan"
    L.enregistrer_fiche(fiche, dossier)
    info_scan = L.info_carte_pour_emprise(-2, -2, 33, 21, image="rdc.pgm")
    scan = np.full((info_scan.hauteur, info_scan.largeur), 205, dtype=np.uint8)
    L.enregistrer_carte(L.chemin_carte(dossier, "rdc"), info_scan, scan)
    resultat = M.generer(dossier, "rdc")
    assert resultat.carte is None and resultat.sdf is not None
    info, image = L.charger_carte(L.chemin_carte(dossier, "rdc"))
    assert (image == 205).all()
    masque_info, masque = L.charger_carte(resultat.masque)
    assert masque.shape == image.shape and masque_info.origin == info.origin
    assert any("scan" in r for r in resultat.remarques)


def test_etage_inconnu(tmp_path):
    dossier = L.copier_lieu(DEMO, tmp_path / "demo")
    with pytest.raises(L.ErreurLieu, match="pas d'étage « etage9 »"):
        M.generer(dossier, "etage9")


def test_monde_absent(tmp_path):
    dossier = L.copier_lieu(DEMO, tmp_path / "demo")
    L.chemin_monde(dossier, "rdc").unlink()
    with pytest.raises(L.ErreurLieu, match="dessinez d'abord le monde"):
        M.generer(dossier, "rdc")
