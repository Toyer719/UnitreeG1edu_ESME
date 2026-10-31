"""La vue Caméra dans Firefox sans fenêtre (vague 5, section 12.7 du plan) : agent Caméra.

Le vrai serveur (g1-atelier, pont ROS 2) et un nœud du test qui joue la caméra de poitrine (JPEG de
640 × 360 à 10 Hz) et g1-visiteurs (trois visiteurs avec leurs cadres) :
  - page d'essai essais/camera.html (la vue seule, sans la coque) : l'image arrive (naturalWidth 640),
    trois cadres dessinés, l'état affiché ; « Arrêter », vue cachée : le serveur n'envoie plus rien ;
    « Démarrer » : il reprend ; la source « Image analysée » sans g1-visiteurs dit quoi faire ;
  - sans caméra : « Pas d'image » et ce qu'il faut lancer ;
  - l'écran Caméra de l'Atelier (#camera) : la même image en direct, avec ses cadres.
Aucune erreur JavaScript. Sauté sans geckodriver, Firefox ou ROS 2. Domaine ROS : $ROS_DOMAIN_ID (105
par défaut, celui de l'agent Caméra).
"""
import json
import os
import time
import urllib.request

import pytest

os.environ.setdefault("ROS_DOMAIN_ID", "105")
pytest.importorskip("rclpy", reason="ROS 2 n'est pas chargé : source ~/robot-g1/setup/env.sh")

from .test_camera_serveur import CameraDeTest  # noqa: E402
from .test_serveur_communs import attendre, faux_bin, journaux, lieux  # noqa: E402,F401
from .test_serveur_demarrage import serveur  # noqa: E402,F401
from .test_serveur_navigateur import GECKODRIVER, navigateur  # noqa: E402,F401

pytestmark = pytest.mark.skipif(GECKODRIVER is None, reason="geckodriver absent")

VISITEURS = {"version": 1, "source": "camera", "temps": 1.0,
             "image": {"largeur": 640, "hauteur": 360, "numero": 1, "sujet": "/camera_poitrine/image/compressed"},
             "personnes": [
                 {"id": 1, "x": 2.0, "y": 0.5, "distance_m": 2.06, "angle_rad": 0.24, "confiance": 0.9,
                  "regarde_robot": True, "boite": [100.0, 60.0, 180.0, 330.0]},
                 {"id": 2, "x": 3.0, "y": 0.0, "distance_m": 3.0, "angle_rad": 0.0, "confiance": 0.8,
                  "regarde_robot": False, "boite": [290.0, 90.0, 350.0, 300.0]},
                 {"id": 3, "x": 2.5, "y": -0.6, "distance_m": 2.57, "angle_rad": -0.23, "confiance": 0.7,
                  "boite": [470.0, 70.0, 540.0, 320.0]}]}


class CameraEtVisiteurs(CameraDeTest):
    """La caméra du test, plus g1-visiteurs : trois visiteurs avec leurs cadres, 10 fois par seconde."""

    def __init__(self):
        super().__init__()
        self.pub_visiteurs = self.noeud.create_publisher(self.String, "/visiteurs/detectes", 10)
        self.noeud.create_timer(0.1, lambda: self.pub_visiteurs.publish(self.String(data=json.dumps(VISITEURS))))


@pytest.fixture
def camera_et_visiteurs():
    c = CameraEtVisiteurs()
    yield c
    c.fermer()


def _etat(base):
    with urllib.request.urlopen(base + "/api/camera/etat", timeout=10) as r:
        return json.loads(r.read())


def _flux_ouverts(base, nombre):
    return attendre(lambda: _etat(base)["flux_ouverts"] == nombre, 5, 0.2)


IMAGE_RECUE = ("const i = document.querySelector('[data-role=camera-flux]'); "
               "return i && i.complete && i.naturalWidth === 640 && i.naturalHeight === 360")
CADRES = "const c = document.querySelector('[data-role=camera-cadres]'); return c && Number(c.dataset.cadres) >= 3"


def test_page_d_essai(camera_et_visiteurs, serveur, navigateur):
    _, base = serveur
    nav = navigateur
    nav.ouvrir(base + "/essais/camera.html")
    nav.attendre(IMAGE_RECUE, delai=20, message="image de la caméra dans la vue")
    nav.attendre(CADRES, delai=10, message="trois cadres dessinés")
    etat = nav.js("return window.vueCamera.etat()")
    assert etat["actif"] and etat["flux"] and etat["largeur"] == 640 and etat["cadres"] == 3 and etat["images"] > 0
    nav.attendre("return document.querySelector('[data-role=camera-etat]').textContent.includes('640 × 360')",
                 message="état affiché")
    assert "3 visiteurs" in nav.js("return document.querySelector('[data-role=camera-etat]').textContent")
    assert _flux_ouverts(base, 1)
    # « Arrêter » : le flux est fermé, le serveur n'envoie plus rien ; « Démarrer » : il reprend
    nav.js("document.querySelector('[data-role=essai-arreter]').click()")
    assert _flux_ouverts(base, 0), "le flux continue après « Arrêter »"
    assert nav.js("return document.querySelector('[data-role=camera-cadres]').dataset.cadres") == "0"
    nav.js("document.querySelector('[data-role=essai-demarrer]').click()")
    assert _flux_ouverts(base, 1)
    nav.attendre(CADRES, delai=10, message="cadres après la reprise")
    # vue cachée (comme une vue de la coque qui n'est pas affichée) : flux fermé
    nav.js("document.querySelector('[data-role=essai-cacher]').click()")
    assert _flux_ouverts(base, 0), "le flux continue quand la vue est cachée"
    nav.js("document.querySelector('[data-role=essai-cacher]').click()")
    assert _flux_ouverts(base, 1)
    # l'image analysée par g1-visiteurs : il ne tourne pas, la vue dit quoi faire
    nav.js("document.querySelector('[data-role=essai-source]').click()")
    nav.attendre("return document.querySelector('[data-role=camera-etat]').textContent.includes('g1-visiteurs --image')",
                 message="message sans g1-visiteurs")
    assert nav.js("return document.querySelector('.camera-vue').dataset.source") == "visiteurs"
    # incrustation (petite vue) sur la caméra
    nav.js("document.querySelector('[data-role=essai-source]').click()")
    nav.js("document.querySelector('[data-role=essai-petit]').click()")
    nav.attendre(IMAGE_RECUE, delai=10, message="image dans l'incrustation")
    assert nav.js("return document.querySelector('.camera-vue').classList.contains('camera-vue-petite')")
    assert nav.js("return window.erreursAtelier") == []


def test_sans_camera(serveur, navigateur):
    _, base = serveur
    nav = navigateur
    nav.ouvrir(base + "/essais/camera.html")
    nav.attendre("return document.querySelector('[data-role=camera-etat]').textContent.includes('Pas d\\'image')",
                 delai=15, message="« Pas d'image »")
    texte = nav.js("return document.querySelector('[data-role=camera-etat]').textContent")
    assert "camera_usb" in texte and "ROS_DOMAIN_ID" in texte
    assert nav.js("return document.querySelector('.camera-vue').dataset.etat") == "sans-image"
    assert nav.js("return window.erreursAtelier") == []


def test_ecran_camera_de_l_atelier(camera_et_visiteurs, serveur, navigateur):
    _, base = serveur
    nav = navigateur
    nav.ouvrir(base + "/")
    nav.js("localStorage.setItem('atelier.lieu', 'demo'); localStorage.setItem('atelier.etage', 'rdc'); "
           "localStorage.setItem('atelier.mode', 'reel'); localStorage.setItem('atelier.repetition', '1');")
    nav.ouvrir(base + "/?recharger=1#camera")
    nav.attendre("return document.querySelector('[data-ecran=camera], .ecran-camera') !== null", delai=20,
                 message="écran Caméra ouvert")
    nav.attendre("return document.querySelector('[data-role=camera-direct] [data-role=camera-flux]') !== null",
                 delai=15, message="image en direct dans l'écran Caméra")
    nav.attendre("const i = document.querySelector('[data-role=camera-direct] [data-role=camera-flux]'); "
                 "return i.naturalWidth === 640", delai=20, message="image reçue dans l'écran Caméra")
    nav.attendre("const c = document.querySelector('[data-role=camera-direct] [data-role=camera-cadres]'); "
                 "return Number(c.dataset.cadres) >= 3", delai=10, message="cadres dans l'écran Caméra")
    # « Partir de l'exemple » : les réglages (dont les réglages avancés) s'affichent
    nav.attendre("const b = document.querySelector('[data-role=exemple]'); "
                 "if (!b || b.offsetParent === null) return false; b.click(); return true;",
                 delai=10, message="bouton « Partir de l'exemple »")
    nav.attendre("return document.querySelector('[data-role=reglages-avances]') !== null", delai=10,
                 message="réglages avancés")
    nav.attendre("return document.querySelector('[data-role=vue-dessus] [data-role=champ]') !== null",
                 message="vue de dessus")
    assert nav.js("return window.erreursAtelier") == []
    time.sleep(0.1)
