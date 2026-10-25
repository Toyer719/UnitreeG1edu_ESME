"""Tests des conversions pixel ↔ monde et angle ↔ quaternion (atelier.lieu.conversions).

  ~/robot-g1/.venv-projet/bin/python -m pytest ~/robot-g1/atelier/tests/test_lieu_conversions.py -v
"""
import math
from types import SimpleNamespace

import numpy as np
import pytest

from atelier.lieu import (InfoCarte, bornes_carte, cap_vers_quaternion, centres_pixels, charger_carte,
                          dans_image, enregistrer_carte, info_carte_pour_emprise, lire_info_carte,
                          monde_vers_pixel, normaliser_angle, pixel_vers_monde, quaternion_vers_cap)

RES = 0.05


@pytest.fixture
def carte_demo():
    """Carte du lieu demo : emprise 30 × 20 m, 0,05 m par pixel, marge d'un pixel."""
    return info_carte_pour_emprise(0.0, 0.0, 30.0, 20.0, RES, marge=1, image="rdc.pgm")


def test_carte_pour_emprise(carte_demo):
    assert (carte_demo.largeur, carte_demo.hauteur) == (602, 402)
    assert carte_demo.origin == pytest.approx((-0.05, -0.05, 0.0))
    assert bornes_carte(carte_demo) == pytest.approx((-0.05, -0.05, 30.05, 20.05))
    sans_marge = info_carte_pour_emprise(0, 0, 1.0, 0.5, 0.1, marge=0)
    assert (sans_marge.largeur, sans_marge.hauteur) == (10, 5)


# (x, y) en mètres → (colonne, ligne) attendues, sur la carte du demo
CAS_CONNUS = {
    "coin bas gauche de l'image": ((-0.05, -0.05), (0, 401)),
    "coin bas gauche de l'emprise": ((0.0, 0.0), (1, 400)),
    "coin haut gauche de l'image": ((-0.05, 20.05 - 1e-5), (0, 0)),
    "coin bas droit de l'image": ((30.05 - 1e-5, -0.05), (601, 401)),
    "coin haut droit de l'emprise": ((30.0, 20.0), (601, 0)),
    "coin haut droit de l'image (dehors)": ((30.05, 20.05), (602, -1)),
    "accueil du demo": ((2.5, 10.0), (51, 200)),
    "en dessous de l'image": ((5.0, -0.06), (101, 402)),
}


@pytest.mark.parametrize("cas", list(CAS_CONNUS))
def test_monde_vers_pixel_cas_connus(carte_demo, cas):
    (x, y), attendu = CAS_CONNUS[cas]
    assert monde_vers_pixel(x, y, carte_demo) == attendu


def test_dans_image(carte_demo):
    assert dans_image(0, 0, carte_demo) and dans_image(601, 401, carte_demo)
    assert not dans_image(602, 0, carte_demo) and not dans_image(0, -1, carte_demo)
    assert not dans_image(*monde_vers_pixel(30.05, 20.05, carte_demo), carte_demo)
    assert list(dans_image(np.array([-1, 0, 601, 602]), np.array([0, 0, 0, 0]), carte_demo)) == \
        [False, True, True, False]


def test_pixel_vers_monde_centres_des_coins(carte_demo):
    attendus = {(0, 0): (-0.025, 20.025), (601, 0): (30.025, 20.025),
                (0, 401): (-0.025, -0.025), (601, 401): (30.025, -0.025)}
    for (colonne, ligne), (x, y) in attendus.items():
        assert pixel_vers_monde(colonne, ligne, carte_demo) == pytest.approx((x, y))
        assert monde_vers_pixel(x, y, carte_demo) == (colonne, ligne)


def test_axe_y_inverse(carte_demo):
    """Monter de 1 m vers le nord fait remonter de 20 lignes dans l'image."""
    _, ligne_bas = monde_vers_pixel(5.0, 3.0, carte_demo)
    _, ligne_haut = monde_vers_pixel(5.0, 4.0, carte_demo)
    assert ligne_bas - ligne_haut == 20
    colonne_ouest, _ = monde_vers_pixel(5.0, 3.0, carte_demo)
    colonne_est, _ = monde_vers_pixel(6.0, 3.0, carte_demo)
    assert colonne_est - colonne_ouest == 20


def test_bord_de_pixel_malgre_les_flottants():
    """0.15 / 0.05 vaut 2.9999999999999996 en flottant : le point est pourtant dans le pixel 3."""
    info = InfoCarte("t.pgm", 0.05, (0.0, 0.0, 0.0), largeur=10, hauteur=10)
    assert monde_vers_pixel(0.15, 0.15, info) == (3, 6)
    assert monde_vers_pixel(0.15 - 1e-4, 0.15 - 1e-4, info) == (2, 7)


def test_origine_quelconque():
    info = InfoCarte("t.pgm", 0.1, (-3.2, 1.5, 0.0), largeur=50, hauteur=20)
    assert monde_vers_pixel(-3.2, 1.5, info) == (0, 19)
    assert monde_vers_pixel(1.75, 3.45, info) == (49, 0)
    assert pixel_vers_monde(49, 0, info) == pytest.approx((1.75, 3.45))


def test_types_de_sortie(carte_demo):
    colonne, ligne = monde_vers_pixel(1.0, 2.0, carte_demo)
    assert type(colonne) is int and type(ligne) is int
    x, y = pixel_vers_monde(3, 4, carte_demo)
    assert type(x) is float and type(y) is float


def test_tableaux_numpy_et_aller_retour_complet(carte_demo):
    X, Y = centres_pixels(carte_demo)
    assert X.shape == Y.shape == (402, 602)
    assert Y[0, 0] > Y[-1, 0] and X[0, -1] > X[0, 0]          # ligne 0 = y maximal
    colonnes, lignes = monde_vers_pixel(X, Y, carte_demo)
    assert (colonnes == np.arange(602)[None, :]).all()
    assert (lignes == np.arange(402)[:, None]).all()


def test_cartes_refusees():
    with pytest.raises(ValueError, match="taille de l'image inconnue"):
        monde_vers_pixel(0, 0, InfoCarte("t.pgm", 0.05))
    with pytest.raises(ValueError, match="tournée"):
        monde_vers_pixel(0, 0, InfoCarte("t.pgm", 0.05, (0, 0, 0.3), largeur=5, hauteur=5))
    with pytest.raises(TypeError):
        monde_vers_pixel(0, 0, {"resolution": 0.05})


def test_image_ecrite_puis_relue_au_bon_endroit(tmp_path, carte_demo):
    """Un obstacle posé en (5, 3) via les conversions se retrouve en (5, 3) après écriture du .pgm."""
    image = np.full((carte_demo.hauteur, carte_demo.largeur), 254, dtype=np.uint8)
    colonne, ligne = monde_vers_pixel(5.0, 3.0, carte_demo)
    image[ligne, colonne] = 0
    enregistrer_carte(tmp_path / "rdc.yaml", carte_demo, image)
    info, relue = charger_carte(tmp_path / "rdc.yaml")
    lignes, colonnes = np.nonzero(relue == 0)
    assert len(lignes) == 1
    assert pixel_vers_monde(int(colonnes[0]), int(lignes[0]), info) == pytest.approx((5.025, 3.025))
    assert lire_info_carte(tmp_path / "rdc.yaml") == info


# ---------------------------------------------------------------- angles

def test_cap_vers_quaternion_cas_connus():
    r = math.sqrt(0.5)
    assert cap_vers_quaternion(0.0) == pytest.approx((0, 0, 0, 1))
    assert cap_vers_quaternion(math.pi / 2) == pytest.approx((0, 0, r, r))
    assert cap_vers_quaternion(-math.pi / 2) == pytest.approx((0, 0, -r, r))
    assert cap_vers_quaternion(math.pi) == pytest.approx((0, 0, 1, 0), abs=1e-12)


@pytest.mark.parametrize("theta", list(np.linspace(-math.pi + 1e-6, math.pi, 37)))
def test_quaternion_aller_retour(theta):
    assert quaternion_vers_cap(cap_vers_quaternion(theta)) == pytest.approx(theta, abs=1e-9)


def test_quaternion_vers_cap_formes_acceptees():
    q = cap_vers_quaternion(1.2)
    assert quaternion_vers_cap(dict(zip("xyzw", q))) == pytest.approx(1.2)
    assert quaternion_vers_cap(SimpleNamespace(x=q[0], y=q[1], z=q[2], w=q[3])) == pytest.approx(1.2)
    assert quaternion_vers_cap([2 * v for v in q]) == pytest.approx(1.2)        # pas normé
    assert quaternion_vers_cap(cap_vers_quaternion(3 * math.pi / 2)) == pytest.approx(-math.pi / 2)
    with pytest.raises(ValueError):
        quaternion_vers_cap((0, 0, 0, 0))


def test_quaternion_avec_roulis_garde_le_cap():
    """Un léger roulis (x non nul) ne change pas le cap lu autour de z."""
    roulis, cap = 0.1, 0.7
    cr, sr, cy, sy = math.cos(roulis / 2), math.sin(roulis / 2), math.cos(cap / 2), math.sin(cap / 2)
    q = (sr * cy, sr * sy, cr * sy, cr * cy)      # rotation z(cap) puis x(roulis)
    assert quaternion_vers_cap(q) == pytest.approx(cap, abs=1e-9)


def test_normaliser_angle():
    assert normaliser_angle(3 * math.pi / 2) == pytest.approx(-math.pi / 2)
    assert normaliser_angle(-3 * math.pi / 2) == pytest.approx(math.pi / 2)
    assert normaliser_angle(math.pi) == pytest.approx(-math.pi)
    assert normaliser_angle(0.5) == pytest.approx(0.5)
