"""
Images de la caméra de poitrine, sans ROS (vague 5, section 12.7 du plan).

Ce que fait le nœud camera_usb, testé sans caméra ni ROS :
  yuyv_vers_jpeg     image YUYV 4:2:2 de la See3CAM → JPEG (Pillow et numpy, image YCbCr : pas de
                     conversion en RGB), réduite à la largeur publiée (1280 → 640 : une ligne et
                     une paire de pixels sur deux, moins d'une milliseconde) ;
  mire_yuyv          image de test fabriquée (dégradé, barres de couleur, carré qui avance,
                     numéro), pour essayer sans caméra ;
  image_vers_yuyv    une photo (bus.jpg…) → YUYV, pour fabriquer une fausse vidéo de test ;
  Cadence            choisit les images à publier (10 par seconde parmi 30) ;
  LecteurImages      lit les images de « v4l2-ctl --stream-to-hdr=- » (chacune précédée d'un
                     en-tête de 8 octets), ou d'un fichier YUYV brut, avec un tampon préparé
                     d'avance et un tube agrandi à 1 Mo (sans cela, 1280 × 720 tombe de 30 à 15
                     images par seconde) ;
  reglages_camera    les réglages d'exposition que la caméra accepte (--list-ctrls-menus) ;
  commandes_exposition  les -c de v4l2-ctl qui règlent l'exposition, dans le bon ordre.

Seulement la bibliothèque standard, numpy et Pillow : ils sont dans l'image du Jetson (python3-pil,
couche 2d du Dockerfile), pas OpenCV.
"""
import fcntl
import io
import math
import os
import re
import struct

import numpy as np
from PIL import Image, ImageDraw

# v4l2-ctl --stream-to-hdr : chaque image est précédée de la marque 'Vhdr' (fourcc écrit en
# gros-boutiste : les octets « rdhV ») et de sa taille (entier de 4 octets, gros-boutiste)
MARQUE_ENTETE = b'rdhV'
TAILLE_ENTETE = 8
F_SETPIPE_SZ = 1031             # fcntl : taille d'un tube (Linux)
TAILLE_TUBE = 1 << 20           # 1 Mo : le plus grand permis sans droits (pipe-max-size)
CHERCHE_MAX = 1 << 16           # octets lus au plus pour retrouver une marque (texte en tête)


class ErreurImage(ValueError):
    """Image ou flux d'images illisible (taille fausse, marque introuvable)."""


def taille_yuyv(largeur, hauteur):
    """Octets d'une image YUYV 4:2:2 (2 octets par pixel)."""
    return int(largeur) * int(hauteur) * 2


def _verifier_taille(brut, largeur, hauteur):
    if largeur <= 0 or hauteur <= 0 or largeur % 2:
        raise ErreurImage(f'taille d\'image impossible : {largeur} × {hauteur} (largeur paire)')
    attendu = taille_yuyv(largeur, hauteur)
    if len(brut) != attendu:
        raise ErreurImage(f'image YUYV de {len(brut)} octets au lieu de {attendu} '
                          f'({largeur} × {hauteur} × 2)')


def reduction_pour(largeur, largeur_publiee):
    """Facteur entier de réduction (1, 2, 3…) qui garde au moins largeur_publiee pixels."""
    if not largeur_publiee or largeur_publiee >= largeur:
        return 1
    return max(1, int(largeur) // int(largeur_publiee))


def taille_publiee(largeur, hauteur, largeur_publiee):
    """Taille de l'image publiée : jamais agrandie, proportions gardées, largeur paire."""
    if not largeur_publiee or largeur_publiee >= largeur:
        return int(largeur), int(hauteur)
    lp = max(2, int(largeur_publiee) // 2 * 2)
    return lp, max(1, int(round(hauteur * lp / largeur)))


def yuyv_vers_ycbcr(brut, largeur, hauteur, reduction=1):
    """
    YUYV 4:2:2 → tableau (hauteur', largeur', 3) Y, Cb, Cr, réduit d'un facteur entier.

    reduction paire : une ligne sur « reduction » et un pixel par paire (le Y du premier pixel),
    sans calcul ; autre facteur : l'image entière, puis un pixel sur « reduction ».
    """
    _verifier_taille(brut, largeur, hauteur)
    reduction = max(1, int(reduction))
    a = np.frombuffer(brut, np.uint8).reshape(hauteur, largeur // 2, 4)
    if reduction % 2 == 0:
        pas = reduction // 2
        y = a[::reduction, ::pas, 0]
        cb = a[::reduction, ::pas, 1]
        cr = a[::reduction, ::pas, 3]
    else:
        y = np.empty((hauteur, largeur), np.uint8)
        y[:, 0::2] = a[..., 0]
        y[:, 1::2] = a[..., 2]
        cb = np.repeat(a[..., 1], 2, axis=1)
        cr = np.repeat(a[..., 3], 2, axis=1)
        if reduction > 1:
            y, cb, cr = y[::reduction, ::reduction], cb[::reduction, ::reduction], \
                cr[::reduction, ::reduction]
    return np.ascontiguousarray(np.dstack((y, cb, cr)))


# Plage des caméras (Y de 16 à 235, Cb et Cr de 16 à 240, norme BT.601) → plage pleine du JPEG
_LUT_Y = np.clip(np.round((np.arange(256) - 16) * 255.0 / 219.0), 0, 255).astype(np.uint8)
_LUT_C = np.clip(np.round((np.arange(256) - 128) * 255.0 / 224.0 + 128), 0, 255).astype(np.uint8)
_LUT_Y_INVERSE = np.round(16 + np.arange(256) * 219.0 / 255.0).astype(np.uint8)
_LUT_C_INVERSE = np.round(128 + (np.arange(256) - 128) * 224.0 / 255.0).astype(np.uint8)


def plage_pleine(ycbcr):
    """Y, Cb et Cr : de la plage limitée des caméras (16 à 235) à celle du JPEG (0 à 255)."""
    sortie = np.empty_like(ycbcr)
    sortie[..., 0] = _LUT_Y[ycbcr[..., 0]]
    sortie[..., 1] = _LUT_C[ycbcr[..., 1]]
    sortie[..., 2] = _LUT_C[ycbcr[..., 2]]
    return sortie


def yuyv_vers_jpeg(brut, largeur, hauteur, qualite=70, largeur_publiee=None, plage_limitee=True):
    """
    Image YUYV 4:2:2 → (octets JPEG, (largeur, hauteur) publiées).

    largeur_publiee : largeur du JPEG (jamais plus grande que l'image) ; une réduction entière
    d'abord (rapide), puis un redimensionnement si le rapport n'est pas entier. plage_limitee : la
    caméra donne Y de 16 à 235 (BT.601, cas de la See3CAM) ; le JPEG attend 0 à 255.
    """
    qualite = int(min(max(int(qualite), 10), 100))
    reduction = reduction_pour(largeur, largeur_publiee)
    ycbcr = yuyv_vers_ycbcr(brut, largeur, hauteur, reduction)
    if plage_limitee:
        ycbcr = plage_pleine(ycbcr)
    image = Image.fromarray(ycbcr, 'YCbCr')
    voulue = taille_publiee(largeur, hauteur, largeur_publiee)
    if image.size != voulue:
        image = image.resize(voulue, Image.BILINEAR)
    sortie = io.BytesIO()
    image.save(sortie, format='JPEG', quality=qualite)
    return sortie.getvalue(), image.size


def taille_jpeg(octets):
    """Taille (largeur, hauteur) lue dans l'en-tête d'un JPEG (marqueur SOF), ou None."""
    donnees = bytes(octets[:min(len(octets), 1 << 20)])
    if donnees[:2] != b'\xff\xd8':
        return None
    i = 2
    while i + 4 <= len(donnees):
        if donnees[i] != 0xFF:
            return None
        marqueur = donnees[i + 1]
        if marqueur == 0xFF:            # bourrage
            i += 1
            continue
        if marqueur in (0xD8, 0x01) or 0xD0 <= marqueur <= 0xD7:
            i += 2
            continue
        longueur = struct.unpack('>H', donnees[i + 2:i + 4])[0]
        if 0xC0 <= marqueur <= 0xCF and marqueur not in (0xC4, 0xC8, 0xCC):
            if i + 9 > len(donnees):
                return None
            hauteur, largeur = struct.unpack('>HH', donnees[i + 5:i + 9])
            return (largeur, hauteur) if largeur and hauteur else None
        i += 2 + longueur
    return None


# ---------------------------------------------------------------- images de test

def _paquet_yuyv(y, cb, cr):
    """Plans Y (h, l), Cb et Cr (h, l/2) → octets YUYV."""
    hauteur, largeur = y.shape
    a = np.empty((hauteur, largeur // 2, 4), np.uint8)
    a[..., 0] = y[:, 0::2]
    a[..., 1] = cb
    a[..., 2] = y[:, 1::2]
    a[..., 3] = cr
    return a.tobytes()


class Mire:
    """
    Image de test fabriquée, comme une caméra.

    Dégradé, barres de couleur, carré blanc qui avance d'une image à l'autre, et le numéro de
    l'image ; plage limitée, comme la See3CAM.
    """

    def __init__(self, largeur, hauteur):
        if largeur <= 0 or hauteur <= 0 or largeur % 2:
            raise ErreurImage(f'taille de mire impossible : {largeur} × {hauteur} (largeur paire)')
        self.largeur, self.hauteur = int(largeur), int(hauteur)
        x = np.arange(self.largeur)
        self.y = np.tile(np.round(16 + 219 * x / max(1, self.largeur - 1)).astype(np.uint8),
                         (self.hauteur, 1))
        barres = np.array([128, 44, 156, 72, 184, 100, 212, 128], np.uint8)
        colonnes = np.arange(self.largeur // 2) * len(barres) // max(1, self.largeur // 2)
        self.cb = np.tile(barres[colonnes], (self.hauteur, 1))
        self.cr = np.tile(barres[::-1][colonnes], (self.hauteur, 1))
        self.cote = max(8, min(self.largeur, self.hauteur) // 6) // 2 * 2

    def image(self, numero):
        """Octets YUYV de l'image numero."""
        y = self.y.copy()
        cb, cr = self.cb.copy(), self.cr.copy()
        c = self.cote
        course = max(1, self.largeur - c)
        x0 = (int(numero) * 8) % course // 2 * 2
        y0 = (self.hauteur - c) // 2
        y[y0:y0 + c, x0:x0 + c] = 235
        cb[y0:y0 + c, x0 // 2:(x0 + c) // 2] = 128
        cr[y0:y0 + c, x0 // 2:(x0 + c) // 2] = 128
        texte = Image.new('L', (min(self.largeur, 220), min(self.hauteur, 24)), 16)
        ImageDraw.Draw(texte).text((4, 4), f'mire {int(numero)}', fill=235)
        t = np.asarray(texte)
        y[:t.shape[0], :t.shape[1]] = t
        cb[:t.shape[0], :t.shape[1] // 2] = 128         # numéro en blanc sur noir
        cr[:t.shape[0], :t.shape[1] // 2] = 128
        return _paquet_yuyv(y, cb, cr)


def mire_yuyv(numero, largeur, hauteur):
    """Octets YUYV d'une image de test (voir Mire) ; pour une suite d'images, garder une Mire."""
    return Mire(largeur, hauteur).image(numero)


def image_vers_yuyv(image, largeur, hauteur, fond=(110, 110, 110)):
    """
    Une image Pillow (photo) → octets YUYV de largeur × hauteur, en plage limitée.

    L'image est réduite ou agrandie pour tenir entière (proportions gardées), centrée sur un fond
    gris : c'est la fausse caméra des tests (bus.jpg d'ultralytics, 810 × 1080 → 540 × 720 au
    milieu d'une image de 1280 × 720).
    """
    if largeur <= 0 or hauteur <= 0 or largeur % 2:
        raise ErreurImage(f'taille d\'image impossible : {largeur} × {hauteur} (largeur paire)')
    image = image.convert('RGB')
    echelle = min(largeur / image.width, hauteur / image.height)
    taille = (max(1, int(round(image.width * echelle))),
              max(1, int(round(image.height * echelle))))
    toile = Image.new('RGB', (largeur, hauteur), fond)
    toile.paste(image.resize(taille, Image.BILINEAR),
                ((largeur - taille[0]) // 2, (hauteur - taille[1]) // 2))
    a = np.asarray(toile.convert('YCbCr'))
    y = _LUT_Y_INVERSE[a[..., 0]]
    # 4:2:2 : la couleur de chaque paire de pixels est la moyenne des deux
    cb = ((a[:, 0::2, 1].astype(np.uint16) + a[:, 1::2, 1]) // 2).astype(np.uint8)
    cr = ((a[:, 0::2, 2].astype(np.uint16) + a[:, 1::2, 2]) // 2).astype(np.uint8)
    return _paquet_yuyv(y, _LUT_C_INVERSE[cb], _LUT_C_INVERSE[cr])


def entete_image(taille):
    """En-tête de v4l2-ctl --stream-to-hdr devant une image de « taille » octets."""
    return MARQUE_ENTETE + struct.pack('>I', int(taille))


# ---------------------------------------------------------------- cadence de publication

class Cadence:
    """
    Choisit les images à publier : au plus frequence_hz par seconde, régulièrement.

    garder(instant) est appelé pour chaque image lue (instant en secondes, horloge monotone) ;
    il dit si l'image part. Une image un peu en avance (d'un quart de période au plus) part quand
    même : 30 images par seconde donnent bien 10 publications par seconde, pas 7,5.
    """

    def __init__(self, frequence_hz):
        if not frequence_hz or frequence_hz <= 0 or not math.isfinite(frequence_hz):
            raise ValueError(f'fréquence de publication impossible : {frequence_hz}')
        self.periode = 1.0 / float(frequence_hz)
        self.prochain = None

    def garder(self, instant):
        """Vrai si l'image lue à cet instant doit être publiée."""
        if self.prochain is None or instant >= self.prochain - self.periode / 4.0:
            if self.prochain is None or instant - self.prochain > self.periode:
                self.prochain = instant + self.periode       # départ, ou retard : on repart d'ici
            else:
                self.prochain += self.periode
            return True
        return False


# ---------------------------------------------------------------- lecture d'un flux d'images

def agrandir_tube(fd, taille=TAILLE_TUBE):
    """Agrandit le tube de lecture (Linux) ; renvoie sa nouvelle taille, ou None si impossible."""
    try:
        return fcntl.fcntl(fd, F_SETPIPE_SZ, int(taille))
    except OSError:
        return None


class LecteurImages:
    """
    Lit des images YUYV de taille fixe dans un flux (tube de v4l2-ctl, ou fichier).

    avec_entete : chaque image est précédée de l'en-tête de --stream-to-hdr (marque et taille) ;
    un texte en tête du flux est sauté, une image de taille fausse (incomplète) est sautée et
    comptée dans incompletes. Sans en-tête : des images brutes, les unes après les autres.
    lire() renvoie une vue sur le tampon (valable jusqu'à l'appel suivant), ou None à la fin.
    """

    def __init__(self, flux, largeur, hauteur, avec_entete=True):
        self.flux = flux
        self.taille = taille_yuyv(largeur, hauteur)
        self.avec_entete = avec_entete
        self.tampon = bytearray(self.taille)
        self.vue = memoryview(self.tampon)
        self.incompletes = 0
        self.sautes = 0                 # octets sautés avant une marque (texte, flux décalé)

    def _remplir(self, vue):
        """Remplit la vue ; False si le flux finit avant."""
        lus = 0
        while lus < len(vue):
            n = self.flux.readinto(vue[lus:])
            if not n:
                return False
            lus += n
        return True

    def _octets(self, n):
        tampon = bytearray(n)
        return bytes(tampon) if self._remplir(memoryview(tampon)) else None

    def _entete(self):
        """Taille de l'image suivante, ou None à la fin ; retrouve la marque si besoin."""
        debut = self._octets(TAILLE_ENTETE)
        if debut is None:
            return None
        fenetre = bytearray(debut)
        cherches = 0
        while fenetre[:4] != MARQUE_ENTETE:
            if cherches >= CHERCHE_MAX:
                raise ErreurImage('flux illisible : aucune image (marque « rdhV » de v4l2-ctl '
                                  '--stream-to-hdr introuvable)')
            un = self._octets(1)
            if un is None:
                return None
            del fenetre[0]
            fenetre += un
            cherches += 1
            self.sautes += 1
        return struct.unpack('>I', bytes(fenetre[4:8]))[0]

    def lire(self):
        """L'image suivante (memoryview sur le tampon), ou None à la fin du flux."""
        if not self.avec_entete:
            return self.vue if self._remplir(self.vue) else None
        while True:
            taille = self._entete()
            if taille is None:
                return None
            if taille == self.taille:
                return self.vue if self._remplir(self.vue) else None
            # image incomplète (ou d'une autre taille) : sautée
            self.incompletes += 1
            reste = taille
            while reste > 0:
                morceau = self._octets(min(reste, self.taille))
                if morceau is None:
                    return None
                reste -= len(morceau)


# ---------------------------------------------------------------- exposition (v4l2-ctl)

_LIGNE_CONTROLE = re.compile(r'^\s*(\w+)\s+0x[0-9a-f]+\s+\((\w+)\)\s*:\s*(.*)$')
_LIGNE_MENU = re.compile(r'^\s*(\d+):\s*(.+?)\s*$')
_CHAMP = re.compile(r'(\w+)=(-?\d+)')


def reglages_camera(texte):
    """
    Contrôles d'une caméra lus dans la sortie de « v4l2-ctl --list-ctrls-menus ».

    Renvoie {nom: {type, min, max, defaut, valeur, menu: {numéro: libellé}}}.
    """
    controles = {}
    courant = None
    for ligne in str(texte).splitlines():
        m = _LIGNE_CONTROLE.match(ligne)
        if m:
            champs = {k: int(v) for k, v in _CHAMP.findall(m.group(3))}
            courant = {'type': m.group(2), 'min': champs.get('min'), 'max': champs.get('max'),
                       'defaut': champs.get('default'), 'valeur': champs.get('value'), 'menu': {}}
            controles[m.group(1)] = courant
            continue
        m = _LIGNE_MENU.match(ligne)
        if m and courant is not None and courant['type'] == 'menu':
            courant['menu'][int(m.group(1))] = m.group(2)
    return controles


def valeur_auto_exposition(controles):
    """
    Valeur « automatique » du réglage auto_exposure de la caméra.

    0 (Auto Mode, cas de la See3CAM), sinon 3 (Aperture Priority, la plupart des webcams), sinon
    2 ; None si la caméra n'a pas ce réglage.
    """
    menu = (controles.get('auto_exposure') or {}).get('menu') or {}
    for valeur in (0, 3, 2):
        if valeur in menu:
            return valeur
    return 0 if 'auto_exposure' in controles else None


def _borner(controles, nom, valeur, avertissements):
    c = controles.get(nom)
    if c is None:
        avertissements.append(f'la caméra n\'a pas de réglage {nom} : {valeur} ignoré')
        return None
    bas = c['min'] if c['min'] is not None else valeur
    haut = c['max'] if c['max'] is not None else valeur
    borne = min(max(int(valeur), bas), haut)
    if borne != int(valeur):
        avertissements.append(f'{nom} {valeur} hors des limites de la caméra ({bas} à {haut}) : '
                              f'{borne}')
    return borne


def commandes_exposition(controles, mode, temps_100us=156, gain=4):
    """
    Réglages de l'exposition à passer à v4l2-ctl : (appels, avertissements).

    Un appel de v4l2-ctl par élément, dans l'ordre : [['auto_exposure=0']]. En manuel,
    auto_exposure=1 d'abord (sinon le temps d'exposition est refusé), puis exposure_time_absolute
    et gain (bornés aux limites de la caméra).
    """
    avertissements = []
    if mode not in ('auto', 'manuelle'):
        raise ValueError(f'exposition inconnue : « {mode} » (auto ou manuelle)')
    if 'auto_exposure' not in controles:
        avertissements.append('la caméra n\'a pas de réglage auto_exposure : exposition laissée '
                              'telle quelle')
        return [], avertissements
    if mode == 'auto':
        return [[f'auto_exposure={valeur_auto_exposition(controles)}']], avertissements
    menu = controles['auto_exposure']['menu']
    manuel = next((v for v, nom in menu.items() if 'manual' in nom.lower()), 1)
    appels = [[f'auto_exposure={manuel}']]
    suite = []
    for nom, valeur in (('exposure_time_absolute', temps_100us), ('gain', gain)):
        if valeur is None:
            continue
        borne = _borner(controles, nom, valeur, avertissements)
        if borne is not None:
            suite.append(f'{nom}={borne}')
    if suite:
        appels.append(suite)
    return appels, avertissements


def nature_fichier(chemin, largeur, hauteur):
    """
    Comment lire un fichier de test.

    'entete' (v4l2-ctl --stream-to-hdr), 'brut' (YUYV brut), 'image' (photo lisible par Pillow)
    ou 'video' (autre vidéo, lue par OpenCV s'il est là).
    """
    chemin = str(chemin)
    with open(chemin, 'rb') as f:
        debut = f.read(CHERCHE_MAX)
    if MARQUE_ENTETE in debut:
        return 'entete'
    suffixe = os.path.splitext(chemin)[1].lower()
    if suffixe in ('.jpg', '.jpeg', '.png', '.bmp', '.ppm', '.pgm', '.webp', '.gif', '.tif',
                   '.tiff'):
        return 'image'
    if suffixe in ('.mp4', '.avi', '.mkv', '.mov', '.webm', '.mjpeg', '.mjpg'):
        return 'video'
    taille = os.path.getsize(chemin)
    if taille and taille % taille_yuyv(largeur, hauteur) == 0:
        return 'brut'
    raise ErreurImage(f'{chemin} : ni des images YUYV de {largeur} × {hauteur} ({taille} octets, '
                      f'pas un multiple de {taille_yuyv(largeur, hauteur)}), ni une image, ni une '
                      'vidéo')
