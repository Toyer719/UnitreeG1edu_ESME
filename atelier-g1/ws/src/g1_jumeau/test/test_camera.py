"""
Caméra de la tête du faux G1 (section 11.13 du plan).

Image de test JPEG du service videohub (GetImageSample, 1001), seule puis de bout en bout avec
ROS 2 : faux G1 ← nœud pilotage ← GET /camera de son API (le JPEG passe par le champ binary,
int8[], dans les deux sens).
"""
import io
import json
import socket
import time
import urllib.error
import urllib.request

from g1_jumeau.camera import API_IMAGE, CODE_INCONNUE, FausseCamera, image_test
import pytest


def test_image_de_test_jpeg_lisible():
    octets = image_test(7, mur=1.7e9)
    assert octets[:2] == b'\xff\xd8' and octets[-2:] == b'\xff\xd9'
    assert 5_000 < len(octets) < 200_000
    from PIL import Image
    image = Image.open(io.BytesIO(octets))
    assert image.size == (640, 360) and image.format == 'JPEG'


def test_fausse_camera_numerote_et_refuse_les_autres_api():
    c = FausseCamera(mur=lambda: 1.7e9)
    code, a = c.traiter(API_IMAGE)
    code2, b = c.traiter(API_IMAGE)
    assert (code, code2, c.images) == (0, 0, 2) and a != b      # la bille avance
    assert c.traiter(1002) == (CODE_INCONNUE, b'')


def _port_libre():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def test_de_bout_en_bout_avec_le_noeud_pilotage(monkeypatch):
    pytest.importorskip('rclpy')
    from ament_index_python.packages import get_package_prefix, PackageNotFoundError
    from outils_jumeau import NoeudLance
    try:
        get_package_prefix('g1_pilotage')
    except PackageNotFoundError:
        pytest.skip('g1_pilotage n\'est pas compilé')
    monkeypatch.setenv('G1_PILOTAGE_JETON', '')       # sans jeton : 127.0.0.1 seulement
    port = _port_libre()
    jumeau = NoeudLance('camera_jumeau').demarrer()
    pilote = NoeudLance('camera_pilote', ['-p', 'inutile:=0'], paquet='g1_pilotage',
                        executable_nom='pilote')
    pilote.commande = pilote.commande[:1] + ['--port', str(port), '--hote', '127.0.0.1']
    pilote.demarrer()
    try:
        url = f'http://127.0.0.1:{port}'
        fin = time.monotonic() + 20.0
        image = None
        while time.monotonic() < fin and image is None:
            try:
                with urllib.request.urlopen(url + '/camera', timeout=5) as r:
                    if r.headers['Content-Type'] == 'image/jpeg':
                        image = r.read()
            except (urllib.error.URLError, ConnectionError):
                time.sleep(0.5)
        assert image is not None, pilote.texte()[-2000:] + jumeau.texte()[-2000:]
        assert image[:2] == b'\xff\xd8' and image[-2:] == b'\xff\xd9' and len(image) > 5_000
        with urllib.request.urlopen(url + '/etat', timeout=5) as r:
            assert json.loads(r.read())['version'] == 1
    finally:
        pilote.arreter()
        jumeau.arreter()
