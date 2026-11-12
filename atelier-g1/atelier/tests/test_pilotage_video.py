"""Import des bras d'une chorégraphie depuis une vidéo (section 11.5 du plan, facultatif), avec le vrai
modèle de pose YOLO hors ligne (modeles/yolo/yolo11n-pose.pt) et une vidéo fabriquée depuis une
image d'exemple d'ultralytics (zidane.jpg, deux personnes). Sauté sans le modèle ou ultralytics."""
import subprocess
import sys
from pathlib import Path

import pytest

import atelier
from atelier.lieu import pilotage as D

sys.path.insert(0, str(atelier.RACINE / "ws" / "src" / "g1_pilotage"))
cv2 = pytest.importorskip("cv2")
ultralytics = pytest.importorskip("ultralytics")
MODELE = atelier.RACINE / "modeles" / "yolo" / "yolo11n-pose.pt"
IMAGE = Path(ultralytics.__file__).parent / "assets" / "zidane.jpg"
pytestmark = pytest.mark.skipif(not MODELE.is_file() or not IMAGE.is_file(),
                                reason="modèle de pose ou image d'exemple absents")


def video_d_essai(chemin, secondes=2.0, ips=10):
    image = cv2.imread(str(IMAGE))
    h, l = image.shape[:2]
    ecrivain = cv2.VideoWriter(str(chemin), cv2.VideoWriter_fourcc(*"mp4v"), ips, (l, h))
    for i in range(int(secondes * ips)):
        decale = cv2.warpAffine(image, __import__("numpy").float32([[1, 0, 3 * i], [0, 1, 0]]), (l, h))
        ecrivain.write(decale)
    ecrivain.release()
    return chemin


def test_choregraphie_sure_depuis_une_video(tmp_path):
    from g1_pilotage.video import choregraphie_depuis_video, lire_points
    video = video_d_essai(tmp_path / "danse.mp4")
    points = lire_points(video, MODELE)
    assert len(points) >= 15                                   # une personne vue sur chaque image
    d = choregraphie_depuis_video(video, "zidane", "Essai vidéo", modele=MODELE)
    assert D.verifier_choregraphie(d) == []
    assert len(d["bras"]["poses"]) >= 3 and "pas" not in d
    bougent = {n for p in d["bras"]["poses"] for n, v in p["q"].items() if abs(v) > 0.05}
    assert bougent & {"left_shoulder_pitch", "left_elbow", "right_shoulder_pitch", "right_elbow"}


def test_commande_importer_video(tmp_path):
    video = video_d_essai(tmp_path / "danse.mp4", secondes=1.5)
    r = subprocess.run([str(atelier.RACINE / "bin" / "g1-pilotage"), "importer-video", str(video), "--id", "essai",
                        "--dossier", str(tmp_path)], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    d = D.charger_choregraphie("essai", tmp_path)
    assert d["id"] == "essai" and d["bras"]["poses"]
    r = subprocess.run([str(atelier.RACINE / "bin" / "g1-pilotage"), "importer-video", str(tmp_path / "absente.mp4"),
                        "--id", "x", "--dossier", str(tmp_path)], capture_output=True, text=True, timeout=300)
    assert r.returncode == 1 and "illisible" in r.stderr
