"""
Images et périphérique de la caméra de poitrine, sans ROS ni caméra (vague 5, section 12.7).

image_jpeg : YUYV → JPEG (couleurs, tailles, réduction), image de test, photo → YUYV, cadence de
publication, lecture d'un flux de v4l2-ctl (en-têtes, texte en tête, image incomplète, fin),
réglages d'exposition. peripherique : See3CAM branchées, périphérique par défaut, format lu,
messages d'erreur.
"""
import io
import os
import struct
import threading

from g1_equipe import image_jpeg as J
from g1_equipe import peripherique as P
import numpy as np
from PIL import Image
import pytest

from faux_v4l2_ctl import REGLAGES_SEE3CAM


def uni(largeur, hauteur, y=128, u=128, v=128):
    """Image YUYV d'une seule couleur."""
    return bytes([y, u, y, v]) * (largeur * hauteur // 2)


def decoder(jpeg):
    return Image.open(io.BytesIO(jpeg))


# ---------------------------------------------------------------- YUYV → JPEG

def test_gris_uni_et_plage():
    jpeg, taille = J.yuyv_vers_jpeg(uni(64, 48), 64, 48, qualite=90)
    assert jpeg[:2] == b'\xff\xd8' and taille == (64, 48)
    gris = np.asarray(decoder(jpeg).convert('RGB')).astype(float)
    # plage limitée (16 à 235) → plage pleine : 128 devient 130
    assert abs(gris.mean() - 130.4) < 2 and gris.std() < 1.5
    jpeg, _ = J.yuyv_vers_jpeg(uni(64, 48), 64, 48, qualite=90, plage_limitee=False)
    assert abs(np.asarray(decoder(jpeg).convert('RGB')).mean() - 128) < 2
    # noir et blanc de la caméra (16 et 235) → 0 et 255
    noir, _ = J.yuyv_vers_jpeg(uni(32, 32, y=16), 32, 32, qualite=95)
    blanc, _ = J.yuyv_vers_jpeg(uni(32, 32, y=235), 32, 32, qualite=95)
    assert np.asarray(decoder(noir).convert('L')).mean() < 3
    assert np.asarray(decoder(blanc).convert('L')).mean() > 252


def test_couleurs_sans_conversion():
    """Un rouge passe en YUYV puis en JPEG : il reste rouge (Cb et Cr bien rangés)."""
    rouge = Image.new('RGB', (64, 48), (220, 30, 30))
    brut = J.image_vers_yuyv(rouge, 64, 48)
    jpeg = J.yuyv_vers_jpeg(brut, 64, 48, 95)[0]
    r, g, b = np.asarray(decoder(jpeg).convert('RGB')).reshape(-1, 3).mean(0)
    assert r > 190 and g < 60 and b < 60


def test_tailles_publiees():
    brut = uni(1280, 720)
    for largeur_publiee, attendue in ((640, (640, 360)), (1280, (1280, 720)), (None, (1280, 720)),
                                      (2000, (1280, 720)), (800, (800, 450)), (500, (500, 281))):
        jpeg, taille = J.yuyv_vers_jpeg(brut, 1280, 720, 70, largeur_publiee)
        assert taille == attendue and decoder(jpeg).size == attendue
        assert J.taille_jpeg(jpeg) == attendue
    assert J.reduction_pour(1280, 640) == 2 and J.reduction_pour(1280, 400) == 3
    assert J.reduction_pour(640, 640) == 1
    assert J.yuyv_vers_ycbcr(brut, 1280, 720, 2).shape == (360, 640, 3)
    assert J.yuyv_vers_ycbcr(brut, 1280, 720, 3).shape == (240, 427, 3)
    assert J.yuyv_vers_ycbcr(uni(1280, 960), 1280, 960, 4).shape == (240, 320, 3)


def test_mauvaises_tailles():
    with pytest.raises(J.ErreurImage, match='au lieu de'):
        J.yuyv_vers_jpeg(b'\x00' * 100, 64, 48)
    with pytest.raises(ValueError):
        J.yuyv_vers_jpeg(uni(64, 48), 63, 48)
    with pytest.raises(J.ErreurImage):
        J.image_vers_yuyv(Image.new('RGB', (10, 10)), 31, 10)


def test_taille_jpeg_illisible():
    assert J.taille_jpeg(b'pas un jpeg') is None
    assert J.taille_jpeg(b'') is None
    assert J.taille_jpeg(b'\xff\xd8\xff') is None


# ---------------------------------------------------------------- images de test

def test_mire():
    mire = J.Mire(320, 240)
    a, b = mire.image(1), mire.image(2)
    assert len(a) == J.taille_yuyv(320, 240) and a != b
    assert J.mire_yuyv(5, 320, 240) == J.Mire(320, 240).image(5)
    jpeg, taille = J.yuyv_vers_jpeg(a, 320, 240)
    assert taille == (320, 240) and decoder(jpeg).size == (320, 240)


def test_photo_vers_yuyv_dans_le_cadre():
    """Une photo en hauteur tient entière dans 1280 × 720, au milieu d'un fond gris."""
    photo = Image.new('RGB', (810, 1080), (20, 200, 20))
    brut = J.image_vers_yuyv(photo, 1280, 720)
    jpeg = J.yuyv_vers_jpeg(brut, 1280, 720, 90)[0]
    image = np.asarray(decoder(jpeg).convert('RGB')).astype(int)
    assert image.shape == (720, 1280, 3)
    centre, bord = image[360, 640], image[360, 50]
    assert centre[1] > 150 and centre[0] < 80             # vert au milieu
    assert abs(bord[0] - bord[1]) < 12 and 80 < bord[0] < 140    # gris sur les côtés


# ---------------------------------------------------------------- cadence

def test_cadence_30_vers_10():
    c = J.Cadence(10)
    gardees = [i for i in range(90) if c.garder(i / 30.0 + (0.002 if i % 2 else -0.002))]
    assert 29 <= len(gardees) <= 31
    assert all(b - a == 3 for a, b in zip(gardees, gardees[1:]))


def test_cadence_lente_et_trou():
    c = J.Cadence(10)
    gardees = sum(c.garder(i / 12.0) for i in range(36))         # 12 images par seconde, 3 s
    assert 26 <= gardees <= 31
    c = J.Cadence(10)
    assert c.garder(0.0) and not c.garder(0.05)
    assert c.garder(5.0) and not c.garder(5.03) and c.garder(5.1)     # après un trou : on repart
    for faux in (0, -1, float('nan')):
        with pytest.raises(ValueError):
            J.Cadence(faux)


# ---------------------------------------------------------------- lecture d'un flux

def _alimenter(morceaux):
    """Un tube dont l'autre bout reçoit les morceaux depuis un fil, puis se ferme."""
    lecture, ecriture = os.pipe()

    def ecrire():
        with os.fdopen(ecriture, 'wb', buffering=0) as f:
            for m in morceaux:
                f.write(m)
    fil = threading.Thread(target=ecrire, daemon=True)
    fil.start()
    return os.fdopen(lecture, 'rb', buffering=0), fil


def test_lecteur_avec_en_tetes():
    l, h = 64, 48
    taille = J.taille_yuyv(l, h)
    images = [bytes([i]) * taille for i in (10, 20, 30)]
    morceaux = [b'Frame rate set to 30.000 fps\n']
    morceaux += [J.entete_image(taille) + images[0]]
    morceaux += [J.entete_image(100) + b'\x00' * 100]            # image incomplète : sautée
    for im in images[1:]:
        enveloppe = J.entete_image(taille) + im
        morceaux += [enveloppe[:5], enveloppe[5:1000], enveloppe[1000:]]   # découpée n'importe où
    flux, fil = _alimenter(morceaux)
    lecteur = J.LecteurImages(flux, l, h)
    lues = []
    while True:
        vue = lecteur.lire()
        if vue is None:
            break
        lues.append(bytes(vue))
    fil.join(2)
    assert lues == images and lecteur.incompletes == 1 and lecteur.sautes == 29


def test_lecteur_sans_en_tete_et_coupure():
    l, h = 32, 16
    taille = J.taille_yuyv(l, h)
    flux, fil = _alimenter([b'\x01' * taille, b'\x02' * taille, b'\x03' * (taille // 2)])
    lecteur = J.LecteurImages(flux, l, h, avec_entete=False)
    assert bytes(lecteur.lire()) == b'\x01' * taille and bytes(lecteur.lire()) == b'\x02' * taille
    assert lecteur.lire() is None                     # la moitié d'une image puis la fin
    fil.join(2)


def test_lecteur_flux_illisible():
    flux, fil = _alimenter([b'x' * (J.CHERCHE_MAX + 100)])
    with pytest.raises(J.ErreurImage, match='introuvable'):
        J.LecteurImages(flux, 32, 16).lire()
    flux.close()
    fil.join(2)


def test_tube_agrandi():
    lecture, ecriture = os.pipe()
    try:
        assert J.agrandir_tube(lecture) in (J.TAILLE_TUBE, None)
    finally:
        os.close(lecture)
        os.close(ecriture)
    assert struct.unpack('>I', J.entete_image(1843200)[4:])[0] == 1843200


# ---------------------------------------------------------------- exposition

def test_reglages_de_la_see3cam():
    c = J.reglages_camera(REGLAGES_SEE3CAM)
    assert c['auto_exposure']['menu'] == {0: 'Auto Mode', 1: 'Manual Mode'}
    assert c['auto_exposure']['valeur'] == 1 and c['gain']['min'] == 1 and c['gain']['max'] == 32
    assert c['exposure_time_absolute']['defaut'] == 156
    assert J.valeur_auto_exposition(c) == 0
    assert J.commandes_exposition(c, 'auto') == ([['auto_exposure=0']], [])
    appels, notes = J.commandes_exposition(c, 'manuelle', 156, 4)
    assert appels == [['auto_exposure=1'], ['exposure_time_absolute=156', 'gain=4']]
    assert notes == []
    appels, notes = J.commandes_exposition(c, 'manuelle', 50000, 0)
    assert appels[1] == ['exposure_time_absolute=20000', 'gain=1'] and len(notes) == 2
    with pytest.raises(ValueError, match='inconnue'):
        J.commandes_exposition(c, 'nuit')


def test_reglages_d_une_webcam():
    """Webcam ordinaire : « automatique » = Aperture Priority (3) ; sans réglage : rien."""
    texte = ('                  auto_exposure 0x009a0901 (menu)   : min=0 max=3 default=3 '
             'value=3 (Aperture Priority Mode)\n\t\t\t\t1: Manual Mode\n'
             '\t\t\t\t3: Aperture Priority Mode\n')
    c = J.reglages_camera(texte)
    assert J.valeur_auto_exposition(c) == 3
    appels, notes = J.commandes_exposition(c, 'manuelle', 100, 2)
    assert appels == [['auto_exposure=1']] and len(notes) == 2      # ni temps ni gain réglables
    assert J.commandes_exposition({}, 'auto')[0] == []


def test_nature_des_fichiers(tmp_path):
    taille = J.taille_yuyv(64, 48)
    (tmp_path / 'brut.yuyv').write_bytes(b'\x10' * taille * 2)
    entete = J.entete_image(taille)
    (tmp_path / 'entetes.hdr').write_bytes(b'Frame rate\n' + entete + b'\x10' * taille)
    Image.new('RGB', (8, 8)).save(tmp_path / 'photo.png')
    (tmp_path / 'film.mp4').write_bytes(b'\x00' * 10)
    (tmp_path / 'faux.bin').write_bytes(b'\x00' * 7)
    attendu = {'brut.yuyv': 'brut', 'entetes.hdr': 'entete', 'photo.png': 'image',
               'film.mp4': 'video'}
    assert {n: J.nature_fichier(tmp_path / n, 64, 48) for n in attendu} == attendu
    with pytest.raises(J.ErreurImage, match='ni des images YUYV'):
        J.nature_fichier(tmp_path / 'faux.bin', 64, 48)


# ---------------------------------------------------------------- périphérique

def test_see3cam_et_peripherique_par_defaut(tmp_path):
    by_id = tmp_path / 'by-id'
    by_id.mkdir()
    video = tmp_path / 'video7'
    video.write_text('')
    (by_id / 'usb-e-con_Systems_See3CAM_11CUG_1A15C950-video-index0').symlink_to(video)
    (by_id / 'usb-e-con_Systems_See3CAM_11CUG_1A15C950-video-index1').symlink_to(video)
    (by_id / 'usb-Sonix_Webcam-video-index0').symlink_to(video)
    (by_id / 'usb-e-con_Systems_See3CAM_11CUG_PARTI-video-index0').symlink_to(tmp_path / 'absent')
    branchees = P.see3cam_branchees(by_id)
    assert branchees == [str(by_id / 'usb-e-con_Systems_See3CAM_11CUG_1A15C950-video-index0')]
    camera = {'camera': {'peripherique': '/dev/video9'}}
    conteneur = str(tmp_path / 'g1_camera')
    assert P.peripherique_par_defaut(camera, by_id, conteneur) == ('/dev/video9', 'camera.yaml')
    assert P.peripherique_par_defaut(None, by_id, conteneur) == (branchees[0], 'See3CAM branchée')
    (tmp_path / 'g1_camera').write_text('')
    assert P.peripherique_par_defaut(None, by_id, str(tmp_path / 'g1_camera'))[1] == 'conteneur'
    sans = P.peripherique_par_defaut(None, tmp_path / 'rien', '/dev/absent_g1')
    assert sans == ('/dev/absent_g1', 'défaut')
    infos = P.infos_peripherique(branchees[0])
    assert infos['existe'] and infos['resolu'] == str(video) and infos['usb_mbps'] is None
    assert P.infos_peripherique(str(tmp_path / 'absent'))['existe'] is False


def test_format_et_messages():
    texte = ("Format Video Capture:\n\tWidth/Height      : 1280/720\n"
             "\tPixel Format      : 'YUYV' (YUYV 4:2:2)\n")
    assert P.lire_format(texte) == (1280, 720, 'YUYV')
    assert P.lire_format('rien') is None
    occupee = P.message_erreur_v4l2('VIDIOC_S_FMT: failed: Device or resource busy', '/dev/x')
    assert 'occupée' in occupee
    assert 'débranchée' in P.message_erreur_v4l2('Cannot open device /dev/x, exiting.', '/dev/x')
    assert 'groupe video' in P.message_erreur_v4l2('Permission denied', '/dev/x')
    assert P.message_erreur_v4l2('autre chose\n', '/dev/x').endswith('autre chose')
    # textes du vrai v4l2-ctl 1.22 (31/10/2026) : un ioctl qui échoue est écrit sur la sortie
    # standard (code 255), la sortie d'erreur reste vide ; l'ouverture refusée, sur la sortie
    # d'erreur (conteneur sans --group-add)
    sortie = ('VIDIOC_S_FMT: failed: Device or resource busy\n'
              'VIDIOC_S_PARM: failed: Device or resource busy\n')
    assert 'occupée' in P.message_erreur_v4l2('', '/dev/video0', sortie)
    refus = P.message_erreur_v4l2('Failed to open /dev/g1_camera: Permission denied\n',
                                  '/dev/g1_camera', '')
    assert 'groupe video' in refus and '--group-add' in refus
    absente = P.message_erreur_v4l2('Cannot open device /dev/video9, exiting.\n', '/dev/video9')
    assert 'débranchée' in absente
    # sans mot connu : la dernière ligne de la sortie d'erreur, sinon celle de la sortie standard
    autre = P.message_erreur_v4l2('', '/dev/x', 'VIDIOC_G_FMT: failed: Bizarre\n')
    assert autre.endswith('Bizarre')
    assert P.message_erreur_v4l2('erreur\n', '/dev/x', 'sortie\n').endswith(': erreur')
    assert P.message_erreur_v4l2('', '/dev/x', '') == 'v4l2-ctl a échoué sur /dev/x'
