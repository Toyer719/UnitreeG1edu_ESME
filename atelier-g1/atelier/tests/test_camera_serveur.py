"""Flux de la caméra dans l'Atelier (vague 5, section 12.7 du plan) : agent Caméra.

atelier.equipe.images (taille d'un JPEG, dernière image, partie MJPEG) ; routes /api/camera/image,
/api/camera/flux et /api/camera/etat sans ROS (refus en français, jamais d'erreur 500), puis avec
des images rangées dans le pont comme s'il les avait reçues ; enfin avec ROS 2 : un nœud du test
publie des JPEG sur /camera_poitrine/image/compressed et l'état du nœud caméra, le vrai serveur
(g1-atelier) les sert ; le flux s'arrête quand la page se ferme.

Domaine ROS : $ROS_DOMAIN_ID (105 par défaut, celui de l'agent Caméra). Partie ROS sautée sans rclpy.
"""
import http.client
import io
import json
import os
import threading
import time
import urllib.error
import urllib.request

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from atelier.equipe import images as IM
from atelier.lieu.equipe import SUJET_ETAT_CAMERA, SUJET_IMAGE_POITRINE, SUJETS_IMAGES
from atelier.serveur.main import creer_app

from .test_serveur_communs import attendre, faux_bin, journaux, lieux  # noqa: F401
from .test_serveur_demarrage import serveur  # noqa: F401

os.environ.setdefault("ROS_DOMAIN_ID", "105")


def jpeg(largeur=64, hauteur=48, couleur=(200, 30, 30)):
    sortie = io.BytesIO()
    Image.new("RGB", (largeur, hauteur), couleur).save(sortie, format="JPEG", quality=80)
    return sortie.getvalue()


def lire_parties(octets):
    """Parties (en-têtes, JPEG) d'un flux multipart/x-mixed-replace (boundary image-g1)."""
    parties = []
    for morceau in octets.split(b"--" + IM.FRONTIERE.encode())[1:]:
        tete, _, corps = morceau.partition(b"\r\n\r\n")
        entetes = dict(ligne.split(": ", 1) for ligne in tete.decode().strip().split("\r\n") if ": " in ligne)
        taille = int(entetes["Content-Length"])
        parties.append((entetes, corps[:taille]))
    return parties


# ---------------------------------------------------------------- atelier.equipe.images

def test_taille_jpeg():
    assert IM.taille_jpeg(jpeg(640, 360)) == (640, 360)
    assert IM.taille_jpeg(jpeg(33, 7)) == (33, 7)
    progressif = io.BytesIO()
    Image.new("RGB", (120, 80)).save(progressif, format="JPEG", progressive=True)
    assert IM.taille_jpeg(progressif.getvalue()) == (120, 80)
    for faux in (b"", b"GIF89a", b"\xff\xd8\xff", b"\xff\xd8" + b"\x00" * 20):
        assert IM.taille_jpeg(faux) is None


def test_dernieres_images_et_cadence():
    d = IM.DernieresImages()
    assert d.derniere() is None and d.etat()["recue"] is False and d.ips() == 0.0
    for i in range(21):
        assert d.ajouter(jpeg(), temps=12.5, instant=100.0 + i * 0.1) == i + 1
    image = d.derniere()
    assert (image.numero, image.largeur, image.hauteur, image.temps) == (21, 64, 48, 12.5)
    etat = d.etat(maintenant=102.0)
    assert etat["recue"] and etat["numero"] == 21 and etat["age_s"] == 0.0 and etat["octets"] == len(jpeg())
    assert 9.5 <= etat["ips"] <= 10.5
    assert d.ips(maintenant=110.0) == 0.0          # plus rien depuis 8 s
    d.ajouter(b"pas un jpeg", instant=200.0)
    assert d.derniere().largeur is None
    d.oublier()
    assert d.derniere() is None


def test_cadence_du_flux():
    """Au plus N images par seconde en moyenne, sans perdre d'image à 10 Hz quand elles arrivent
    un peu irrégulièrement ; après un trou, le compte repart."""
    import random
    with pytest.raises(ValueError):
        IM.Cadence(0)
    with pytest.raises(ValueError):
        IM.Cadence(float("nan"))
    # une caméra plus rapide (30 images par seconde, regardées toutes les 20 ms) : 10 par seconde
    c = IM.Cadence(10.0)
    envois = [k * 0.02 for k in range(500) if c.garder(k * 0.02)]       # 10 s
    assert 99 <= len(envois) <= 101, len(envois)
    assert min(b - a for a, b in zip(envois, envois[1:])) >= 0.075 - 1e-9
    # 10 images par seconde qui arrivent à ± 15 ms près : aucune perdue
    hasard = random.Random(5)
    c = IM.Cadence(10.0)
    arrivees = [k * 0.1 + hasard.uniform(-0.015, 0.015) for k in range(200)]
    assert all(c.garder(t) for t in arrivees)
    # un trou de 2 s : la première image d'après part, puis la cadence reprend
    c = IM.Cadence(10.0)
    assert c.garder(0.0) and not c.garder(0.05) and c.garder(2.0) and not c.garder(2.05) and c.garder(2.1)


def test_partie_mjpeg_et_en_tetes():
    d = IM.DernieresImages()
    d.ajouter(jpeg(), instant=10.0)
    partie = IM.partie_mjpeg(d.derniere())
    (entetes, corps), = lire_parties(partie)
    assert entetes == {"Content-Type": "image/jpeg", "Content-Length": str(len(jpeg())), "X-Image-Numero": "1"}
    assert corps == jpeg()
    e = IM.entetes_image(d.derniere(), maintenant=10.25)
    assert e["X-Image-Numero"] == "1" and e["X-Image-Age-S"] == "0.250"
    assert (e["X-Image-Largeur"], e["X-Image-Hauteur"]) == ("64", "48")
    assert set(IM.SOURCES_IMAGES.values()) == set(SUJETS_IMAGES)


# ---------------------------------------------------------------- routes, sans ROS

@pytest.fixture
def client(lieux, faux_bin):
    with TestClient(creer_app(ros=False)) as c:
        yield c


def _erreur(r, statut, *morceaux):
    assert r.status_code == statut, r.text
    detail = r.json()["detail"]
    for m in morceaux:
        assert m in detail, detail
    return detail


def test_sans_ros(client):
    _erreur(client.get("/api/camera/image"), 503, "pas relié à ROS 2")
    _erreur(client.get("/api/camera/image?source=visiteurs"), 503, "ROS 2")
    _erreur(client.get("/api/camera/flux"), 503, "ROS 2")
    e = client.get("/api/camera/etat").json()
    assert e["ros"]["actif"] is False and e["noeud"] is None and e["visiteurs"] is None
    assert set(e["sources"]) == {"poitrine", "visiteurs"} and e["sources"]["poitrine"]["recue"] is False
    assert "ROS 2" in e["messages"]["poitrine"] and e["flux_ouverts"] == 0


def test_refus(client):
    _erreur(client.get("/api/camera/image?source=tete"), 400, "poitrine ou visiteurs")
    _erreur(client.get("/api/camera/flux?source=tete"), 400)
    _erreur(client.get("/api/camera/flux?ips=0"), 400, "ips=0")
    _erreur(client.get("/api/camera/flux?images=0"), 400, "images=0")
    _erreur(client.get("/api/camera/flux?ips=vite"), 422)


@pytest.fixture
def pont_actif(client):
    """Le pont du serveur fait comme s'il tournait : les tests y rangent des images."""
    pont = client.app.state.atelier.pont
    pont.actif = True
    yield pont
    pont.actif = False


class Message:
    def __init__(self, donnees):
        self.data = json.dumps(donnees)


def test_image_recue(client, pont_actif):
    # la phrase affichée est courte, sans jargon ; le détail technique est dans « sortie »
    r = client.get("/api/camera/image")
    assert r.status_code == 503 and "n'envoie rien" in r.json()["detail"] and "camera_usb" not in r.json()["detail"]
    assert "(camera_usb) ne publie pas" in r.json()["sortie"] and "ROS_DOMAIN_ID" in r.json()["sortie"]
    r = client.get("/api/camera/image?source=visiteurs")
    assert r.status_code == 503 and "g1-visiteurs --image" in r.json()["sortie"]
    e = client.get("/api/camera/etat").json()
    assert "branchée" in e["messages"]["poitrine"] and "camera_usb" in e["details"]["poitrine"]
    pont_actif.images[SUJET_IMAGE_POITRINE].ajouter(jpeg(640, 360), temps=5.0)
    r = client.get("/api/camera/image?source=poitrine")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg" and r.content == jpeg(640, 360)
    assert r.headers["x-image-numero"] == "1" and float(r.headers["x-image-age-s"]) < 1.0
    assert (r.headers["x-image-largeur"], r.headers["x-image-hauteur"]) == ("640", "360")
    # une image de plus de 2 s ne compte plus ; l'erreur du nœud caméra est reprise
    pont_actif.images[SUJET_IMAGE_POITRINE].ajouter(jpeg(), instant=time.monotonic() - 5.0)
    _erreur(client.get("/api/camera/image"), 503, "Pas d'image depuis 5 s")
    etat_noeud = {"version": 1, "source": "v4l2", "peripherique": "/dev/g1_camera", "ouverte": False, "largeur": 0,
                  "hauteur": 0, "images": 0, "publiees": 0, "erreur": "caméra absente : /dev/g1_camera n'existe pas"}
    pont_actif._recepteur_json(SUJET_ETAT_CAMERA)(Message(etat_noeud))
    _erreur(client.get("/api/camera/image"), 503, "caméra absente : /dev/g1_camera")
    e = client.get("/api/camera/etat").json()
    assert e["ros"]["actif"] and e["noeud"]["erreur"].startswith("caméra absente") and e["noeud"]["perime"] is False
    assert e["sources"]["poitrine"]["numero"] == 2 and "caméra absente" in e["messages"]["poitrine"]
    vus = {"version": 1, "source": "camera", "temps": 1.0, "personnes": [
        {"id": 1, "x": 1.5, "y": 0.0, "distance_m": 1.5, "angle_rad": 0.0, "confiance": 0.9}]}
    pont_actif._recepteur_json("/visiteurs/detectes")(Message(vus))
    assert client.get("/api/camera/etat").json()["visiteurs"]["nombre"] == 1


def test_flux_mjpeg(client, pont_actif):
    images = pont_actif.images[SUJET_IMAGE_POITRINE]
    images.ajouter(jpeg(couleur=(0, 0, 0)))          # la dernière image (récente) part d'abord
    fin = threading.Event()

    def publier():
        n = 0
        while not fin.is_set():
            n += 1
            images.ajouter(jpeg(couleur=(n * 20 % 255, 50, 50)))
            time.sleep(0.03)
    fil = threading.Thread(target=publier, daemon=True)
    fil.start()
    try:
        debut = time.monotonic()
        with client.stream("GET", "/api/camera/flux?source=poitrine&images=5&ips=10") as r:
            assert r.status_code == 200
            assert r.headers["content-type"] == "multipart/x-mixed-replace; boundary=image-g1"
            corps = b"".join(r.iter_bytes())
        duree = time.monotonic() - debut
        parties = lire_parties(corps)
        numeros = [int(e["X-Image-Numero"]) for e, _ in parties]
        assert len(parties) == 5 and numeros == sorted(set(numeros)), numeros
        assert all(c[:2] == b"\xff\xd8" and e["Content-Type"] == "image/jpeg" for e, c in parties)
        assert 0.3 <= duree < 2.0, duree                       # au plus 10 par seconde
        # ips plafonné à 15 : 6 images en au moins 0,3 s
        debut = time.monotonic()
        with client.stream("GET", "/api/camera/flux?images=6&ips=100") as r:
            assert len(lire_parties(b"".join(r.iter_bytes()))) == 6
        assert time.monotonic() - debut >= 0.3
    finally:
        fin.set()
        fil.join(2)
    assert client.get("/api/camera/etat").json()["flux_ouverts"] == 0


def test_flux_sans_image_recente(client, pont_actif):
    """Une vieille image n'est pas envoyée au début : le flux attend une image nouvelle."""
    images = pont_actif.images["/visiteurs/image/compressed"]
    images.ajouter(jpeg(couleur=(1, 2, 3)), instant=time.monotonic() - 10.0)

    def plus_tard():
        time.sleep(0.4)
        images.ajouter(jpeg(couleur=(250, 250, 250)))
    threading.Thread(target=plus_tard, daemon=True).start()
    with client.stream("GET", "/api/camera/flux?source=visiteurs&images=1") as r:
        parties = lire_parties(b"".join(r.iter_bytes()))
    assert [e["X-Image-Numero"] for e, _ in parties] == ["2"]


# ---------------------------------------------------------------- avec ROS 2 et le vrai serveur

class CameraDeTest:
    """Nœud rclpy dans un fil : publie des JPEG (10 Hz) et l'état du nœud caméra (1 Hz)."""

    def __init__(self):
        import rclpy
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
        from sensor_msgs.msg import CompressedImage
        from std_msgs.msg import String
        self.rclpy = rclpy
        self.contexte = rclpy.Context()
        rclpy.init(context=self.contexte)
        self.noeud = rclpy.create_node("camera_de_test_atelier", context=self.contexte)
        capteurs = QoSProfile(depth=2, reliability=ReliabilityPolicy.BEST_EFFORT, history=HistoryPolicy.KEEP_LAST)
        self.pub_image = self.noeud.create_publisher(CompressedImage, SUJET_IMAGE_POITRINE, capteurs)
        self.pub_etat = self.noeud.create_publisher(String, SUJET_ETAT_CAMERA, 10)
        self.CompressedImage, self.String = CompressedImage, String
        self.publiees = 0
        self.noeud.create_timer(0.1, self._image)
        self.noeud.create_timer(1.0, self._etat)
        self.executeur = SingleThreadedExecutor(context=self.contexte)
        self.executeur.add_node(self.noeud)
        self._fin = threading.Event()
        self._fil = threading.Thread(target=self._tourner, daemon=True)
        self._fil.start()

    def _tourner(self):
        while not self._fin.is_set():
            self.executeur.spin_once(timeout_sec=0.02)

    def _image(self):
        import array
        msg = self.CompressedImage()
        msg.header.stamp = self.noeud.get_clock().now().to_msg()
        msg.header.frame_id = "camera_poitrine"
        msg.format = "jpeg"
        msg.data = array.array("B", jpeg(640, 360, (self.publiees * 10 % 255, 90, 160)))
        self.pub_image.publish(msg)
        self.publiees += 1

    def _etat(self):
        etat = {"version": 1, "source": "mire", "peripherique": None, "ouverte": True, "largeur": 640,
                "hauteur": 360, "images": self.publiees * 3, "publiees": self.publiees, "erreur": None}
        self.pub_etat.publish(self.String(data=json.dumps(etat)))

    def fermer(self):
        self._fin.set()
        self._fil.join(timeout=3)
        self.executeur.shutdown()
        self.noeud.destroy_node()
        self.rclpy.shutdown(context=self.contexte)


@pytest.fixture
def camera_de_test():
    pytest.importorskip("rclpy", reason="ROS 2 n'est pas chargé : source ~/robot-g1/setup/env.sh")
    c = CameraDeTest()
    yield c
    c.fermer()


def _lire(url, delai=10):
    """(statut, en-têtes (sans casse), corps) d'un GET."""
    with urllib.request.urlopen(url, timeout=delai) as r:
        return r.status, r.headers, r.read()


def test_avec_ros_et_le_vrai_serveur(camera_de_test, serveur):
    _, base = serveur

    def image_servie():
        try:
            return _lire(base + "/api/camera/image?source=poitrine")[0] == 200
        except urllib.error.HTTPError:
            return False
    assert attendre(image_servie, 20, 0.2), "le serveur ne reçoit pas les images de ROS 2"
    statut, entetes, corps = _lire(base + "/api/camera/image")
    assert corps[:2] == b"\xff\xd8" and entetes["X-Image-Largeur"] == "640" and entetes["X-Image-Hauteur"] == "360"
    debut = time.monotonic()
    statut, entetes, corps = _lire(base + "/api/camera/flux?source=poitrine&images=5")
    assert statut == 200 and len(lire_parties(corps)) == 5 and time.monotonic() - debut < 2.0
    etat = json.loads(_lire(base + "/api/camera/etat")[2])
    assert etat["ros"]["actif"] and etat["sources"]["poitrine"]["recue"]
    assert 7.0 <= etat["sources"]["poitrine"]["ips"] <= 13.0, etat["sources"]["poitrine"]
    assert attendre(lambda: json.loads(_lire(base + "/api/camera/etat")[2])["noeud"] is not None, 5, 0.2)
    assert etat["messages"]["poitrine"] is None and etat["sources"]["visiteurs"]["recue"] is False
    # un flux sans fin, puis la page qui se ferme : le serveur arrête de l'envoyer
    hote, port = base.replace("http://", "").split(":")
    connexion = http.client.HTTPConnection(hote, int(port), timeout=10)
    connexion.request("GET", "/api/camera/flux?source=poitrine")
    reponse = connexion.getresponse()
    assert reponse.status == 200 and reponse.read(2000)
    assert json.loads(_lire(base + "/api/camera/etat")[2])["flux_ouverts"] == 1
    connexion.close()
    assert attendre(lambda: json.loads(_lire(base + "/api/camera/etat")[2])["flux_ouverts"] == 0, 5, 0.2), \
        "le flux continue après la fermeture de la page"
