"""g1-visiteurs (outils/visiteurs.py, vague 5, section 12.7 du plan) : agent Caméra.

Sans YOLO : détections tirées d'un résultat (tenseurs ou listes), faux modèle → message conforme
au schéma personnes, réglages (camera.yaml du lieu ou exemple), modèle introuvable, cadres dessinés,
cadence de la boucle. Avec le vrai modèle (sautés sans ultralytics ni modeles/yolo/yolo11n-pose.pt) :
l'image du bus d'ultralytics (sans fenêtre) donne au moins 3 personnes ; puis avec ROS 2, l'image
du bus publiée en 640 × 360 sur /camera_poitrine/image/compressed → /visiteurs/detectes et
/visiteurs/image/compressed. Domaine ROS : $ROS_DOMAIN_ID (105 par défaut).
"""
import importlib.util
import io
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pytest

import atelier
from atelier.lieu import copier_lieu, valider_message
from atelier.lieu import equipe as E

os.environ.setdefault("ROS_DOMAIN_ID", "105")
OUTIL = atelier.RACINE / "outils" / "visiteurs.py"
G1_VISITEURS = atelier.RACINE / "bin" / "g1-visiteurs"
MODELE = atelier.RACINE / "modeles" / "yolo" / "yolo11n-pose.pt"
DEMO = atelier.RACINE / "lieux" / "demo"


def _charger():
    spec = importlib.util.spec_from_file_location("visiteurs_outil", OUTIL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V = _charger()


def _ultralytics():
    try:
        import ultralytics
        return Path(ultralytics.__file__).parent / "assets"
    except ImportError:
        return None


ASSETS = _ultralytics()
sans_yolo = pytest.mark.skipif(ASSETS is None or not MODELE.is_file(),
                               reason="ultralytics ou modeles/yolo/yolo11n-pose.pt absent")


# ---------------------------------------------------------------- faux YOLO

class Tenseur:
    """Imite un tenseur torch : .cpu().numpy().tolist()."""

    def __init__(self, valeurs):
        self.valeurs = np.asarray(valeurs, dtype=float)

    def cpu(self):
        return self

    def numpy(self):
        return self.valeurs


class Resultat:
    def __init__(self, boites, confiances, ids=None, points=None):
        self.boxes = type("Boites", (), {"xyxy": Tenseur(boites), "conf": Tenseur(confiances),
                                         "id": None if ids is None else Tenseur(ids)})()
        self.keypoints = None if points is None else type("Points", (), {"data": Tenseur(points)})()


class FauxModele:
    """Un modèle qui « voit » toujours les mêmes personnes, et note ses appels."""

    def __init__(self, resultat):
        self.resultat = resultat
        self.appels = []

    def track(self, image, **options):
        self.appels.append((image.shape, options))
        return [self.resultat]


def personne_debout(cx=320, haut=40, bas=312):
    from .test_camera_geometrie import points_personne
    return points_personne(cx, haut, bas)


def test_detections_du_resultat():
    r = Resultat([[300, 40, 340, 312], [10, 20, 30, 40]], [0.9, 0.4], ids=[3, 4],
                 points=[personne_debout(), personne_debout(20, 20, 40)])
    d = V.detections_du_resultat(r)
    assert [x["id"] for x in d] == [3, 4] and d[0]["boite"] == [300, 40, 340, 312]
    assert d[0]["confiance"] == pytest.approx(0.9) and len(d[0]["points"]) == 17
    sans_suivi = V.detections_du_resultat(Resultat([[1, 2, 3, 4]], [0.8]))
    assert sans_suivi == [{"id": None, "boite": [1.0, 2.0, 3.0, 4.0], "confiance": 0.8, "points": None}]
    vide = type("R", (), {"boxes": None})()
    assert V.detections_du_resultat(vide) == []


def test_faux_modele_vers_message():
    modele = FauxModele(Resultat([[300, 40, 340, 312]], [0.92], ids=[5], points=[personne_debout()]))
    detecteur = V.Detecteur(modele, confiance=0.4, appareil="cpu")
    image = np.zeros((360, 640, 3), np.uint8)
    message, detections = V.analyser_image(detecteur, image, E.exemple_equipe("camera"), 42.0, numero=7,
                                           sujet=V.SUJET_ENTREE)
    assert valider_message("personnes", message) == []
    assert message["image"] == {"largeur": 640, "hauteur": 360, "numero": 7, "sujet": V.SUJET_ENTREE}
    p, = message["personnes"]
    assert p["id"] == 5 and p["boite"] == [300.0, 40.0, 340.0, 312.0] and p["regarde_robot"] is True
    assert p["distance_m"] == pytest.approx(2.08, abs=0.02) and message["temps"] == 42.0
    forme, options = modele.appels[0]
    assert forme == (360, 640, 3)
    assert options == {"persist": True, "tracker": "bytetrack.yaml", "classes": [0], "conf": 0.4, "device": "cpu",
                       "verbose": False}
    assert V.resume(message) == "1 visiteur : n° 5 à 2,1 m (taille, face)"
    assert V.resume({"personnes": []}) == "aucun visiteur"
    dessin = V.dessiner(image, message)
    assert dessin.shape == image.shape and dessin.any() and not image.any()


def test_reglages_et_modele(tmp_path, monkeypatch):
    camera, origine = V.lire_camera(None)
    assert camera == E.exemple_equipe("camera") and "exemple" in origine
    lieu = copier_lieu(DEMO, tmp_path / "essai")
    camera, origine = V.lire_camera(str(lieu))              # pas de camera.yaml : l'exemple
    assert "exemple" in origine
    reglages = E.exemple_equipe("camera")
    reglages["detection"]["distance_max_m"] = 7.5
    E.enregistrer_equipe(lieu, "camera", reglages)
    camera, origine = V.lire_camera(str(lieu))
    assert camera["detection"]["distance_max_m"] == 7.5 and "camera.yaml du lieu" in origine
    (lieu / "camera.yaml").write_text("version: 1\ncamera: [\n", encoding="utf-8")
    with pytest.raises(V.Erreur, match="camera.yaml du lieu"):
        V.lire_camera(str(lieu))
    with pytest.raises(V.Erreur, match="introuvable"):
        V.trouver_modele("modele_qui_n_existe_pas.pt")
    faux = tmp_path / "m.pt"
    faux.write_bytes(b"x")
    assert V.trouver_modele(str(faux)) == faux
    if MODELE.is_file():
        assert V.trouver_modele("yolo11n-pose.pt") == MODELE


class SourceDeTest:
    """Des images numérotées, toujours une nouvelle."""
    sujet = "/essai"
    description = "source de test"

    def __init__(self):
        self.numero = 0

    def prendre(self, apres=0):
        self.numero += 1
        return self.numero, np.zeros((360, 640, 3), np.uint8), float(self.numero)


class PublieurDeTest:
    def __init__(self):
        self.messages, self.images = [], []

    def publier(self, message):
        self.messages.append(message)

    def publier_image(self, image, temps):
        self.images.append(temps)


def test_boucle_a_la_frequence_demandee():
    modele = FauxModele(Resultat([[300, 40, 340, 312]], [0.9], ids=[1], points=[personne_debout()]))
    publieur = PublieurDeTest()
    debut = time.monotonic()
    dernier = V.boucle(V.Detecteur(modele), SourceDeTest(), E.exemple_equipe("camera"), publieur, 10.0, image=True,
                       duree=1.05)
    duree = time.monotonic() - debut
    assert 9 <= len(publieur.messages) <= 12 and duree < 1.6
    assert 3 <= len(publieur.images) <= 5                  # images avec cadres : 3 par seconde
    assert dernier == publieur.messages[-1] and all(valider_message("personnes", m) == [] for m in publieur.messages)
    publieur = PublieurDeTest()
    V.boucle(V.Detecteur(modele), SourceDeTest(), None, publieur, 10.0, une_fois=True)
    assert len(publieur.messages) == 1


def test_aide_et_refus():
    r = subprocess.run([sys.executable, str(OUTIL), "--help"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "/visiteurs/detectes" in r.stdout and "affiche cette aide" in r.stdout
    r = subprocess.run([sys.executable, str(OUTIL), "--source", "robot", "--sans-ros", "--une-fois"],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 1 and "demande ROS 2" in r.stderr
    r = subprocess.run([sys.executable, str(OUTIL), "--modele", "absent.pt", "--sans-ros", "--une-fois",
                        "--source", "x.jpg"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 1 and "introuvable" in r.stderr
    r = subprocess.run([sys.executable, str(OUTIL), "--frequence", "0", "--sans-ros"], capture_output=True,
                       text=True, timeout=60)
    assert r.returncode == 1 and "--frequence" in r.stderr
    # l'alias gl-visiteurs (« l » pour « 1 ») : un lien vers g1-visiteurs, comme les autres commandes
    alias = G1_VISITEURS.parent / "gl-visiteurs"
    assert alias.is_symlink() and os.readlink(alias) == "g1-visiteurs"
    r = subprocess.run([str(alias), "--help"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "/visiteurs/detectes" in r.stdout


# ---------------------------------------------------------------- vrai modèle

def image_du_bus_640x360(dossier):
    """L'image du bus comme la publierait camera_usb : 1280 × 720 (YUYV), puis JPEG de 640 × 360."""
    from PIL import Image
    sys.path.insert(0, str(atelier.RACINE / "ws" / "src" / "g1_equipe"))
    from g1_equipe.image_jpeg import image_vers_yuyv, yuyv_vers_jpeg
    with Image.open(ASSETS / "bus.jpg") as bus:
        brut = image_vers_yuyv(bus, 1280, 720)
    jpeg, taille = yuyv_vers_jpeg(brut, 1280, 720, 70, 640)
    assert taille == (640, 360)
    chemin = Path(dossier) / "bus_640x360.jpg"
    chemin.write_bytes(jpeg)
    return chemin


@sans_yolo
def test_bus_sans_fenetre(tmp_path):
    chemin = image_du_bus_640x360(tmp_path)
    r = subprocess.run([str(G1_VISITEURS), "--source", str(chemin), "--une-fois", "--sans-ros"],
                       capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stderr
    message = json.loads(r.stdout)
    assert valider_message("personnes", message) == [] and message["image"]["largeur"] == 640
    assert len(message["personnes"]) >= 3, r.stderr
    for p in message["personnes"]:
        x0, y0, x1, y1 = p["boite"]
        assert 0 <= x0 < x1 <= 640 and 0 <= y0 < y1 <= 360 and 1.0 < p["distance_m"] <= 4.0
    assert "visiteurs :" in r.stderr


@sans_yolo
def test_bus_par_ros(tmp_path):
    """L'image du bus publiée comme par camera_usb → g1-visiteurs --image → /visiteurs/detectes."""
    rclpy = pytest.importorskip("rclpy", reason="ROS 2 n'est pas chargé")
    import array
    from rclpy.executors import SingleThreadedExecutor
    from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
    from sensor_msgs.msg import CompressedImage
    from std_msgs.msg import String
    jpeg = image_du_bus_640x360(tmp_path).read_bytes()
    contexte = rclpy.Context()
    rclpy.init(context=contexte)
    noeud = rclpy.create_node("camera_bus_test", context=contexte)
    capteurs = QoSProfile(depth=2, reliability=ReliabilityPolicy.BEST_EFFORT, history=HistoryPolicy.KEEP_LAST)
    pub = noeud.create_publisher(CompressedImage, V.SUJET_ENTREE, capteurs)
    recus, images = [], []
    noeud.create_subscription(String, V.SUJET_SORTIE, lambda m: recus.append(json.loads(m.data)), 10)
    noeud.create_subscription(CompressedImage, V.SUJET_IMAGE, lambda m: images.append(bytes(m.data)), capteurs)

    def publier():
        msg = CompressedImage()
        msg.header.stamp = noeud.get_clock().now().to_msg()
        msg.header.frame_id = "camera_poitrine"
        msg.format = "jpeg"
        msg.data = array.array("B", jpeg)
        pub.publish(msg)
    noeud.create_timer(0.1, publier)
    executeur = SingleThreadedExecutor(context=contexte)
    executeur.add_node(noeud)
    fin = threading.Event()
    fil = threading.Thread(target=lambda: [executeur.spin_once(timeout_sec=0.02) for _ in iter(fin.is_set, True)],
                           daemon=True)
    fil.start()
    processus = subprocess.Popen([str(G1_VISITEURS), "--image", "--duree", "60"], stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True, start_new_session=True)
    try:
        debut = time.monotonic()
        while time.monotonic() - debut < 60 and not (recus and len(recus[-1]["personnes"]) >= 3 and images):
            time.sleep(0.2)
        assert recus, "rien sur /visiteurs/detectes"
        message = recus[-1]
        assert valider_message("personnes", message) == [] and message["source"] == "camera"
        assert len(message["personnes"]) >= 3 and message["image"]["sujet"] == V.SUJET_ENTREE
        assert (message["image"]["largeur"], message["image"]["hauteur"]) == (640, 360)
        assert images and images[-1][:2] == b"\xff\xd8"
        assert time.monotonic() - debut < 60
    finally:
        os.killpg(processus.pid, 2)
        try:
            sortie = processus.communicate(timeout=20)[0]
        except subprocess.TimeoutExpired:
            os.killpg(processus.pid, 9)
            sortie = processus.communicate()[0]
        fin.set()
        fil.join(timeout=3)
        executeur.shutdown()
        noeud.destroy_node()
        rclpy.shutdown(context=contexte)
    assert processus.returncode in (0, -2), sortie
    assert "lit /camera_poitrine/image/compressed" in sortie
