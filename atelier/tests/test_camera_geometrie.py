"""Des pixels aux mètres : la géométrie de g1-visiteurs (atelier.equipe.camera, vague 5, section 12.7
du plan), sans YOLO ni ROS : focale, direction, distance par la taille de la personne, du buste ou
des épaules, position dans base_link, personne tournée vers le robot, filtrage des détections et
message de /visiteurs/detectes conforme au schéma personnes (cadres « boite » et « image »).
"""
import math

import pytest

from atelier.equipe import camera as C
from atelier.lieu import equipe as E
from atelier.lieu import valider_message

F = 320.0          # focale d'une image de 640 pixels de large qui voit 90°


def points_personne(cx, haut, bas, sur=0.9, sans=()):
    """17 points clés COCO d'une personne debout, centrée en cx, de « haut » (tête) à « bas »
    (chevilles) ; les points de « sans » sont invisibles (confiance 0)."""
    h = bas - haut
    p = [[0.0, 0.0, 0.0] for _ in range(17)]

    def mettre(i, x, y):
        p[i] = [x, y, 0.0 if i in sans else sur]
    mettre(C.NEZ, cx, haut + 0.06 * h)
    mettre(C.OEIL_G, cx + 0.02 * h, haut + 0.05 * h)      # œil gauche de la personne : à droite de l'image
    mettre(C.OEIL_D, cx - 0.02 * h, haut + 0.05 * h)
    mettre(C.EPAULE_G, cx + 0.12 * h, haut + 0.18 * h)
    mettre(C.EPAULE_D, cx - 0.12 * h, haut + 0.18 * h)
    mettre(C.HANCHE_G, cx + 0.08 * h, haut + 0.18 * h + 0.52 / 1.70 * h)
    mettre(C.HANCHE_D, cx - 0.08 * h, haut + 0.18 * h + 0.52 / 1.70 * h)
    mettre(C.CHEVILLE_G, cx + 0.05 * h, bas - 0.01 * h)
    mettre(C.CHEVILLE_D, cx - 0.05 * h, bas - 0.01 * h)
    return p


def test_focale_et_direction():
    assert C.focale_px(640, 90) == pytest.approx(320.0)
    assert C.focale_px(1280, 90) == pytest.approx(640.0)
    assert C.focale_px(640, 60) == pytest.approx(320 / math.tan(math.radians(30)))
    assert C.angle_image(320, 640, F) == pytest.approx(0.0)
    assert C.angle_image(0, 640, F) == pytest.approx(math.pi / 4)          # bord gauche : +45°
    assert C.angle_image(640, 640, F) == pytest.approx(-math.pi / 4)


def test_distance_par_la_taille():
    """Une personne de 1,70 m à 2 m fait 272 pixels de haut avec f = 320."""
    boite = [300, 40, 340, 312]
    d, methode = C.distance_personne(boite, points_personne(320, 40, 312), F, hauteur_image=360)
    assert methode == "taille" and d == pytest.approx(2.0, abs=0.01)
    d, _ = C.distance_personne(boite, points_personne(320, 40, 312), F, taille_m=1.5, hauteur_image=360)
    assert d == pytest.approx(2.0 * 1.5 / 1.7, abs=0.01)
    d, _ = C.distance_personne(boite, points_personne(320, 40, 312), F, correction=1.1, hauteur_image=360)
    assert d == pytest.approx(2.2, abs=0.01)


def test_distance_par_le_buste_puis_les_epaules():
    """Jambes coupées par le bas de l'image : le buste (0,52 m) ; seules les épaules : leur écart."""
    pts = points_personne(320, 40, 312, sans=(C.CHEVILLE_G, C.CHEVILLE_D))
    d, methode = C.distance_personne([300, 40, 340, 360], pts, F, hauteur_image=360)
    assert methode == "buste" and d == pytest.approx(2.0, rel=0.10)
    # cadre coupé en bas, même avec les chevilles devinées : pas la taille
    d, methode = C.distance_personne([300, 40, 340, 360], points_personne(320, 40, 312), F, hauteur_image=360)
    assert methode == "buste"
    pts = points_personne(320, 40, 312, sans=(C.CHEVILLE_G, C.CHEVILLE_D, C.HANCHE_G, C.HANCHE_D))
    d, methode = C.distance_personne([300, 40, 340, 200], pts, F, hauteur_image=360)
    assert methode == "epaules"
    ecart = 0.24 * 272                  # les épaules du test : ± 0,12 × hauteur
    assert d == pytest.approx(F * C.EPAULES_M / ecart, rel=0.01)


def test_distance_par_le_cadre_seul():
    d, methode = C.distance_personne([300, 40, 340, 312], None, F)
    assert methode == "boite" and d == pytest.approx(2.0, abs=0.01)
    assert C.distance_personne([300, 40, 340, 40], None, F) == (None, None)
    assert C.distance_personne([340, 40, 300, 312], None, F) == (None, None)


def test_position_dans_base_link():
    camera = {"camera": {"position": {"x": 0.08, "y": 0.0, "z": 1.1, "roulis": 0, "tangage": 0, "lacet": 0.0}}}
    assert C.position_dans_base_link(2.0, 0.0, camera) == pytest.approx((2.08, 0.0))
    x, y = C.position_dans_base_link(2.0, 0.1, camera)
    assert (x, y) == pytest.approx((2.08, 2.0 * math.tan(0.1)))
    gauche = {"camera": {"position": {"x": 0.0, "y": 0.1, "z": 1.1, "roulis": 0, "tangage": 0,
                                      "lacet": math.pi / 2}}}
    assert C.position_dans_base_link(3.0, 0.0, gauche) == pytest.approx((0.0, 3.1), abs=1e-9)
    assert C.position_dans_base_link(1.0, 0.0, None) == pytest.approx((1.0, 0.0))


def test_regarde_robot():
    face = points_personne(320, 40, 312)
    assert C.regarde_robot(face) is True
    de_cote = [list(p) for p in face]
    de_cote[C.NEZ] = [de_cote[C.OEIL_G][0] + 12, de_cote[C.NEZ][1], 0.9]   # nez hors des yeux
    assert C.regarde_robot(de_cote) is False
    assert C.regarde_robot(points_personne(320, 40, 312, sans=(C.OEIL_D,))) is False
    assert C.regarde_robot(None) is None and C.regarde_robot([]) is None


def test_detections_vers_message():
    camera = E.exemple_equipe("camera")          # 90°, caméra en x 0,08, 4 m au plus, confiance 0,5
    detections = [
        {"id": 7, "boite": [300, 40, 340, 312], "confiance": 0.9, "points": points_personne(320, 40, 312)},
        {"id": 8, "boite": [100, 150, 120, 210], "confiance": 0.8, "points": None},       # 9 m : trop loin
        {"id": 9, "boite": [400, 40, 440, 312], "confiance": 0.3, "points": None},        # pas assez sûr
        {"id": None, "boite": [-20, 30, 60, 400], "confiance": 0.7, "points": None},      # pas encore suivi
    ]
    personnes = C.personnes_depuis_detections(detections, camera, 640, 360)
    assert [p["id"] for p in personnes] == [7, C.ID_SANS_SUIVI + 3]
    p = personnes[0]
    assert p["boite"] == [300.0, 40.0, 340.0, 312.0] and p["methode_distance"] == "taille" and p["regarde_robot"]
    assert p["x"] == pytest.approx(2.08, abs=0.01) and p["y"] == pytest.approx(0.0, abs=0.01)
    assert personnes[1]["boite"] == [0.0, 30.0, 60.0, 360.0] and personnes[1]["suivi"] is False
    message = C.message_visiteurs(12.5, personnes, image={"largeur": 640, "hauteur": 360, "numero": 3,
                                                          "sujet": "/camera_poitrine/image/compressed"})
    assert valider_message("personnes", message) == []
    assert message["image"] == {"largeur": 640, "hauteur": 360, "numero": 3, "sujet": "/camera_poitrine/image/compressed"}
    vu = message["personnes"][0]
    assert vu["distance_m"] == pytest.approx(2.08, abs=0.01) and vu["angle_rad"] == pytest.approx(0.0, abs=0.01)
    assert C.message_visiteurs(1.0, [], image={"largeur": 640, "hauteur": 360, "numero": None})["image"] == {
        "largeur": 640, "hauteur": 360}
    # sans image : comme la vague 4 (fausse caméra)
    assert "image" not in C.message_visiteurs(1.0, [{"id": 1, "x": 1.5, "y": 0.0}])


def test_reglages_de_la_detection():
    camera = E.exemple_equipe("camera")
    camera["detection"].update(distance_max_m=10.0, correction_distance=1.2, taille_personne_m=1.6,
                               confiance_min=0.2)
    camera["camera"]["champ_horizontal_deg"] = 60.0
    d = [{"id": 1, "boite": [300, 40, 340, 312], "confiance": 0.25, "points": points_personne(320, 40, 312)}]
    p, = C.personnes_depuis_detections(d, camera, 640, 360)
    attendu = C.focale_px(640, 60) * 1.6 / 272 * 1.2
    assert p["x"] - 0.08 == pytest.approx(attendu, abs=0.01)
    assert C.personnes_depuis_detections(d, None, 640, 360) == []          # confiance 0,25 < 0,5 par défaut
