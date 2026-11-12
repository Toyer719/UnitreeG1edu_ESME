"""
Le nœud camera_usb en vrai (ROS 2), sans caméra (vague 5, section 12.7 du plan).

Mire et fichiers (YUYV brut, photo) : environ 10 Hz sur /camera_poitrine/image/compressed, JPEG
lisibles de la bonne taille, état conforme au schéma etat_camera. Avec un faux v4l2-ctl en tête du
PATH (une See3CAM sans caméra, faux_v4l2_ctl.py) : réglages de l'exposition dans le bon ordre et
bornés, format, flux lu ; caméra débranchée puis revenue ; caméra occupée ; caméra absente ; arrêt
propre (plus aucun v4l2-ctl). Réglage faux : refus en français. Environ 40 s.

Essai sur la vraie caméra (sauté sans elle) : G1_TEST_CAMERA=/dev/v4l/by-id/…-video-index0
(See3CAM : 25 images lues par seconde au moins, USB 3 ; une autre caméra : G1_TEST_CAMERA_IPS).
"""
import io
import json
import os
from pathlib import Path
import signal
import sys
import threading
import time

from atelier.lieu import valider_message
from g1_equipe import image_jpeg as J
from outils_equipe import NoeudLance
from PIL import Image
import pytest
import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import String

ICI = Path(__file__).resolve().parent
QOS_IMAGES = QoSProfile(depth=5, reliability=ReliabilityPolicy.BEST_EFFORT,
                        history=HistoryPolicy.KEEP_LAST)


class EcouteCamera:
    """Nœud de test dans un fil : garde les images et les états de la caméra de poitrine."""

    def __init__(self):
        if not rclpy.ok():
            rclpy.init()
        self.noeud = rclpy.create_node('ecoute_camera_poitrine')
        self.verrou = threading.Lock()
        self.images = []            # (instant, message)
        self.etats = []             # dicts
        self.noeud.create_subscription(CompressedImage, '/camera_poitrine/image/compressed',
                                       self._image, QOS_IMAGES)
        self.noeud.create_subscription(String, '/camera_poitrine/etat', self._etat, 10)
        self.executeur = SingleThreadedExecutor()
        self.executeur.add_node(self.noeud)
        self._fin = threading.Event()
        self._fil = threading.Thread(target=self._tourner, daemon=True)
        self._fil.start()

    def _tourner(self):
        while not self._fin.is_set():
            self.executeur.spin_once(timeout_sec=0.02)

    def _image(self, msg):
        with self.verrou:
            self.images.append((time.monotonic(), msg))

    def _etat(self, msg):
        with self.verrou:
            self.etats.append(json.loads(msg.data))

    def vider(self):
        with self.verrou:
            self.images.clear()
            self.etats.clear()

    def attendre(self, condition, delai, message):
        fin = time.monotonic() + delai
        while time.monotonic() < fin:
            with self.verrou:
                valeur = condition()
            if valeur:
                return valeur
            time.sleep(0.05)
        raise AssertionError(message)

    def frequence(self, duree):
        """Images reçues par seconde pendant « duree » secondes, à partir de maintenant."""
        with self.verrou:
            avant = len(self.images)
        time.sleep(duree)
        with self.verrou:
            recues = self.images[avant:]
        if len(recues) < 2:
            return 0.0
        return (len(recues) - 1) / (recues[-1][0] - recues[0][0])

    def dernier_etat(self):
        with self.verrou:
            return dict(self.etats[-1]) if self.etats else None

    def fermer(self):
        self._fin.set()
        self._fil.join(timeout=3)
        self.executeur.shutdown()
        self.noeud.destroy_node()


@pytest.fixture
def ecoute():
    e = EcouteCamera()
    yield e
    e.fermer()


@pytest.fixture
def lancer():
    """Démarre camera_usb ; tous les nœuds lancés par le test sont arrêtés à la fin."""
    lances = []

    def _lancer(*arguments):
        n = NoeudLance('camera_usb', arguments).demarrer()
        lances.append(n)
        return n
    yield _lancer
    for n in lances:
        n.arreter()


@pytest.fixture
def faux_v4l2(tmp_path, monkeypatch):
    """Faux v4l2-ctl en tête du PATH ; renvoie (journal des appels, faux périphérique)."""
    dossier = tmp_path / 'bin'
    dossier.mkdir()
    programme = dossier / 'v4l2-ctl'
    programme.write_text(f'#!/bin/sh\nexec {sys.executable} {ICI / "faux_v4l2_ctl.py"} "$@"\n')
    programme.chmod(0o755)
    journal = tmp_path / 'appels.jsonl'
    monkeypatch.setenv('PATH', f'{dossier}:{os.environ["PATH"]}')
    monkeypatch.setenv('FAUX_V4L2_JOURNAL', str(journal))
    peripherique = tmp_path / 'video_faux'
    peripherique.write_text('')
    return journal, peripherique


def appels(journal):
    if not journal.exists():
        return []
    return [json.loads(x) for x in journal.read_text().splitlines() if x.strip()]


def verifier_images(ecoute, largeur, hauteur):
    """Dernière image : JPEG lisible, de la bonne taille, au format du contrat."""
    with ecoute.verrou:
        msg = ecoute.images[-1][1]
    assert msg.format == 'jpeg' and msg.header.frame_id == 'camera_poitrine'
    donnees = bytes(msg.data)
    assert donnees[:2] == b'\xff\xd8'
    assert Image.open(io.BytesIO(donnees)).size == (largeur, hauteur)
    assert msg.header.stamp.sec > 0


def etat_ouvert(ecoute):
    """Dernier état si la caméra est ouverte (à appeler sous le verrou de l'écoute)."""
    return ecoute.etats and ecoute.etats[-1]['ouverte'] and ecoute.etats[-1]


def flux_lances(journal):
    """Appels du faux v4l2-ctl qui ont lancé un flux d'images."""
    return [a for a in appels(journal) if '--stream-to-hdr=-' in a['arguments']]


def verifier_etat(etat, **attendu):
    assert valider_message('etat_camera', etat) == [], etat
    for cle, valeur in attendu.items():
        assert etat[cle] == valeur, (cle, etat)


def test_mire_a_10_hz(ecoute, lancer):
    n = lancer('-p', 'source:=mire')
    ecoute.attendre(lambda: len(ecoute.images) >= 5, 10, 'aucune image de la mire\n' + n.texte())
    frequence = ecoute.frequence(3.0)
    assert 8.0 <= frequence <= 12.0, frequence
    verifier_images(ecoute, 640, 360)
    etat = ecoute.attendre(
        lambda: ecoute.etats and ecoute.etats[-1]['images'] > 30 and ecoute.etats[-1], 5, 'état')
    verifier_etat(etat, version=1, source='mire', peripherique=None, ouverte=True, largeur=640,
                  hauteur=360, exposition=None, erreur=None)
    assert 25 <= etat['ips_mesuree'] <= 35 and etat['publiees'] <= etat['images']
    assert etat['capture'] == {'largeur': 1280, 'hauteur': 720, 'ips': 30}
    assert etat['taille_moyenne_ko'] > 0
    assert 'mire (image de test)' in n.texte()


def test_fichier_yuyv_et_photo(ecoute, lancer, tmp_path):
    couleurs = [(200, 30, 30), (30, 200, 30), (30, 30, 200)]
    brut = b''.join(J.image_vers_yuyv(Image.new('RGB', (40, 30), c), 320, 240) for c in couleurs)
    (tmp_path / 'video.yuyv').write_bytes(brut)
    n = lancer('-p', 'source:=fichier', '-p', f'fichier:={tmp_path / "video.yuyv"}',
               '-p', 'largeur:=320', '-p', 'hauteur:=240', '-p', 'ips:=15',
               '-p', 'largeur_publiee:=320', '-p', 'qualite_jpeg:=80')
    ecoute.attendre(lambda: len(ecoute.images) >= 5, 10, 'aucune image du fichier\n' + n.texte())
    assert 8.0 <= ecoute.frequence(2.0) <= 12.0
    verifier_images(ecoute, 320, 240)
    with ecoute.verrou:
        dernieres = [bytes(m.data) for _, m in ecoute.images[-6:]]
    teintes = set()
    for jpeg in dernieres:
        pixel = Image.open(io.BytesIO(jpeg)).convert('RGB').resize((1, 1)).getpixel((0, 0))
        teintes.add(tuple(int(v) // 100 for v in pixel))
    assert len(teintes) >= 2, teintes                  # les trois images du fichier tournent
    etat = ecoute.attendre(lambda: etat_ouvert(ecoute), 5, 'état')
    verifier_etat(etat, source='fichier', peripherique=str(tmp_path / 'video.yuyv'), largeur=320,
                  hauteur=240)
    n.arreter()
    assert n.processus.returncode == 0
    ecoute.vider()
    Image.new('RGB', (810, 1080), (20, 200, 20)).save(tmp_path / 'photo.png')
    n = lancer('-p', 'source:=fichier', '-p', f'fichier:={tmp_path / "photo.png"}')
    ecoute.attendre(lambda: len(ecoute.images) >= 3, 10, 'aucune image de la photo\n' + n.texte())
    verifier_images(ecoute, 640, 360)


def test_faux_v4l2_exposition_format_et_arret(ecoute, lancer, faux_v4l2):
    journal, peripherique = faux_v4l2
    n = lancer('-p', f'peripherique:={peripherique}', '-p', 'exposition:=manuelle',
               '-p', 'gain:=0')
    ecoute.attendre(lambda: len(ecoute.images) >= 5, 10,
                    'aucune image du faux v4l2-ctl\n' + n.texte())
    assert 8.0 <= ecoute.frequence(2.0) <= 12.0
    verifier_images(ecoute, 640, 360)
    etat = ecoute.attendre(lambda: etat_ouvert(ecoute), 5, 'état')
    verifier_etat(etat, source='v4l2', peripherique=str(peripherique), exposition='manuelle',
                  erreur=None)
    assert any('gain 0' in a for a in etat['avertissements'])     # borné à 1 (min de la caméra)
    suite = [a['arguments'] for a in appels(journal)]
    assert suite[0] == ['-d', str(peripherique), '--list-ctrls-menus']
    assert suite[1] == ['-d', str(peripherique), '-c', 'auto_exposure=1']
    assert suite[2] == ['-d', str(peripherique), '-c', 'exposure_time_absolute=156,gain=1']
    assert suite[3] == ['-d', str(peripherique),
                        '--set-fmt-video=width=1280,height=720,pixelformat=YUYV', '--set-parm=30']
    assert suite[4][-1] == '--get-fmt-video'
    assert suite[5] == ['-d', str(peripherique), '--stream-mmap=4', '--stream-to-hdr=-']
    flux = [a['pid'] for a in flux_lances(journal)]
    n.arreter()
    assert n.processus.returncode == 0, n.texte()
    time.sleep(0.3)
    for pid in flux:
        assert not Path(f'/proc/{pid}').exists(), 'v4l2-ctl reste après l\'arrêt du nœud'


def test_camera_debranchee_puis_revenue(ecoute, lancer, faux_v4l2, monkeypatch):
    journal, peripherique = faux_v4l2
    monkeypatch.setenv('FAUX_V4L2_IMAGES', '15')       # 0,5 s d'images, puis « No such device »
    n = lancer('-p', f'peripherique:={peripherique}')
    assert n.attendre_texte('débranchée', 10), n.texte()
    ecoute.attendre(lambda: len(flux_lances(journal)) >= 2, 10,
                    'v4l2-ctl n\'est pas relancé après la panne\n' + n.texte())
    ecoute.attendre(lambda: ecoute.images or any(
        not e['ouverte'] and 'débranchée' in (e['erreur'] or '') for e in ecoute.etats),
        10, 'ni état de panne ni images')
    assert n.processus.poll() is None, 'le nœud s\'est arrêté'


def test_camera_occupee_et_absente(ecoute, lancer, faux_v4l2, monkeypatch):
    journal, peripherique = faux_v4l2
    monkeypatch.setenv('FAUX_V4L2_OCCUPE', '1')
    n = lancer('-p', f'peripherique:={peripherique}')
    etat = ecoute.attendre(
        lambda: ecoute.etats and ecoute.etats[-1]['erreur'] and ecoute.etats[-1], 8,
        'pas d\'état\n' + n.texte())
    verifier_etat(etat, ouverte=False, images=0, publiees=0)
    assert 'occupée par un autre programme' in etat['erreur']
    n.arreter()
    ecoute.vider()
    n = lancer('-p', 'peripherique:=/dev/inexistant_g1_camera')
    etat = ecoute.attendre(lambda: len(ecoute.etats) >= 3 and ecoute.etats[-1], 8,
                           'pas d\'état\n' + n.texte())
    verifier_etat(etat, ouverte=False, source='v4l2', peripherique='/dev/inexistant_g1_camera')
    assert 'caméra absente' in etat['erreur'] and n.processus.poll() is None


def test_exposition_refusee(ecoute, lancer, faux_v4l2, monkeypatch):
    """
    La caméra refuse le réglage de l'exposition : les images arrivent quand même.

    Un avertissement dit pourquoi ; l'exposition reste celle de la caméra.
    """
    journal, peripherique = faux_v4l2
    monkeypatch.setenv('FAUX_V4L2_REFUS', '1')
    n = lancer('-p', f'peripherique:={peripherique}')
    ecoute.attendre(lambda: len(ecoute.images) >= 3, 10, 'aucune image\n' + n.texte())
    etat = ecoute.attendre(lambda: etat_ouvert(ecoute), 5, 'état')
    verifier_etat(etat, erreur=None, exposition='auto')
    assert any('exposition non réglée (auto_exposure=0)' in a and 'Permission denied' in a
               for a in etat['avertissements']), etat['avertissements']


def test_v4l2_ctl_relance_garde_son_delai():
    """
    Revue de la vague 5 : un v4l2-ctl relancé garde son délai.

    Après un débranchement (dernière image il y a 30 s), il a ses 5 s pour donner sa première
    image ; il n'est relancé que si rien n'arrive pendant ce temps.
    """
    from g1_equipe.camera_usb import faut_relancer, SANS_IMAGE_S
    t = 1000.0
    assert not faut_relancer(t, derniere=t - 30.0, lancement=t - 0.5)       # vient d'être relancé
    assert faut_relancer(t, derniere=t - 30.0, lancement=t - SANS_IMAGE_S - 0.1)
    assert not faut_relancer(t, derniere=None, lancement=t - 1.0)             # premier lancement
    assert faut_relancer(t, derniere=None, lancement=t - 6.0)
    assert not faut_relancer(t, derniere=t - 1.0, lancement=t - 60.0)         # images récentes
    assert faut_relancer(t, derniere=t - 6.0, lancement=t - 60.0)             # flux arrêté


def test_reglages_faux_refuses():
    for arguments, morceau in ((['-p', 'exposition:=nuit'], 'inconnue'),
                               (['-p', 'source:=usb'], 'inconnue'),
                               (['-p', 'largeur:=641'], 'impossible'),
                               (['-p', 'source:=fichier'], 'fichier'),
                               (['-p', 'qualite_jpeg:=5'], 'qualite_jpeg')):
        n = NoeudLance('camera_usb', arguments).demarrer()
        try:
            assert n.attendre(15) == 2, n.texte()
        finally:
            n.arreter()
        assert morceau in n.texte(), n.texte()


@pytest.mark.skipif(not os.environ.get('G1_TEST_CAMERA'),
                    reason='G1_TEST_CAMERA non donné (vraie caméra)')
def test_vraie_camera(ecoute, lancer):
    n = lancer('-p', f'peripherique:={os.environ["G1_TEST_CAMERA"]}')
    ecoute.attendre(lambda: len(ecoute.images) >= 5, 15, 'aucune image de la caméra\n' + n.texte())
    assert ecoute.frequence(3.0) >= 8.0
    verifier_images(ecoute, 640, 360)
    etat = ecoute.attendre(lambda: etat_ouvert(ecoute), 5, 'état')
    verifier_etat(etat, exposition='auto', erreur=None)
    # See3CAM en USB 3 : 30 images lues par seconde ; une autre caméra (G1_TEST_CAMERA_IPS, ex. 8
    # pour une webcam USB 2 à 10 images par seconde en 1280 × 720) : son seuil, sans exiger l'USB 3
    autre = os.environ.get('G1_TEST_CAMERA_IPS')
    assert etat['ips_mesuree'] >= float(autre or 25), etat
    assert autre or etat['usb_mbps'] in (None, 5000, 10000), etat
    n.processus.send_signal(signal.SIGINT)
    assert n.attendre(10) == 0
