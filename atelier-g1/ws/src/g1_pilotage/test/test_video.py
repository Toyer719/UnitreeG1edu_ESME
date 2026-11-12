"""
Import des bras depuis une vidéo, sans modèle : géométrie des bras et chorégraphie sûre.

Points du corps au format COCO (x à droite, y en bas), danseur face à la caméra : sa gauche est
à droite de l'image.
"""
import math

from g1_pilotage.video import angles_bras, choregraphie_depuis_angles, D, filtrer
import numpy as np
import pytest

R = 0.85 * 40.0                        # longueur du bras (épaules de 40 pixels)


def corps(coude_g=(0, R), coude_d=(0, R), poignet_g=(0, R), poignet_d=(0, R)):
    """Points (17, 2) et confiances (17,) : épaules en (±20, 0), hanches 50 pixels plus bas."""
    p = np.zeros((17, 2))
    p[5], p[6] = (20.0, 0.0), (-20.0, 0.0)
    p[11], p[12] = (15.0, 50.0), (-15.0, 50.0)
    p[7] = p[5] + coude_g
    p[8] = p[6] + coude_d
    p[9] = p[7] + poignet_g
    p[10] = p[8] + poignet_d
    return p, np.ones(17)


def test_bras_le_long_du_corps():
    q = angles_bras(*corps())
    for nom in ('left', 'right'):
        assert q[f'{nom}_shoulder_pitch'] == pytest.approx(0.0, abs=1e-9)
        assert q[f'{nom}_shoulder_roll'] == pytest.approx(0.0, abs=1e-9)
        assert q[f'{nom}_elbow'] == pytest.approx(0.0, abs=1e-9)


def test_bras_ecartes_a_l_horizontale():
    q = angles_bras(*corps(coude_g=(R, 0), coude_d=(-R, 0), poignet_g=(R, 0), poignet_d=(-R, 0)))
    assert q['left_shoulder_roll'] == pytest.approx(math.pi / 2)        # gauche : roulis positif
    assert q['right_shoulder_roll'] == pytest.approx(-math.pi / 2)      # droite : négatif


def test_bras_devant_et_en_haut():
    q = angles_bras(*corps(coude_g=(0, 0.0), coude_d=(0, -R), poignet_d=(0, -R)))
    assert q['left_shoulder_pitch'] == pytest.approx(-math.pi / 2)      # vers l'avant (raccourci)
    assert q['right_shoulder_pitch'] == pytest.approx(-math.pi)         # tendu vers le haut
    assert q['right_shoulder_roll'] == pytest.approx(0.0, abs=1e-9)


def test_coude_plie_a_angle_droit_et_points_peu_surs():
    p, c = corps(poignet_g=(R, 0))
    assert angles_bras(p, c)['left_elbow'] == pytest.approx(math.pi / 2)
    c[7] = 0.1                                                           # coude gauche peu sûr
    q = angles_bras(p, c)
    assert 'left_shoulder_roll' not in q and 'right_shoulder_roll' in q
    c[11] = c[12] = 0.1                                                  # hanches hors du cadre
    assert angles_bras(p, c)['right_shoulder_roll'] == pytest.approx(0.0, abs=1e-9)
    c[5] = 0.1                                                           # épaule invisible
    assert angles_bras(p, c) is None


def test_filtre_comble_et_lisse():
    s = filtrer([0.0, math.nan, 2.0, 2.0, 50.0, 2.0, 2.0, math.nan])
    assert np.all(np.isfinite(s)) and max(s) < 3.0           # la valeur aberrante disparaît


def test_choregraphie_sure_depuis_des_angles():
    instants = np.arange(0, 10.01, 0.1)
    series = {n: [0.0] * len(instants) for n in D.ARTICULATIONS_BRAS}
    series['left_shoulder_roll'] = list(1.2 + 1.2 * np.sin(2 * math.pi * instants))  # trop vite
    series['right_elbow'] = list(1.5 + 1.0 * np.sin(math.pi * instants))             # trop loin
    series['left_shoulder_pitch'] = [-3.5] * len(instants)                   # hors limites
    d = choregraphie_depuis_angles(list(instants), series, 'essai_video')
    assert D.verifier_choregraphie(d) == []
    poses = d['bras']['poses']
    assert len(poses) == 41 and poses[0]['t'] == pytest.approx(2.0)
    for p in poses:
        for nom, v in p['q'].items():
            bas, haut = D.LIMITES_BRAS[nom]
            assert bas <= v <= haut
    assert d['duree_s'] >= poses[-1]['t'] + d['bras']['rampe_s']
    assert 'pas' not in d and 'gestes' not in d                        # les bras seulement
