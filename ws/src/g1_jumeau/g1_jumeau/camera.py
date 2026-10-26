"""
Fausse caméra de la tête du faux G1 (section 11.13 du plan).

Le service videohub du SDK d'Unitree (GetImageSample, api 1001) rend une image JPEG dans le
champ binary de la réponse. Ici, une image de test fabriquée à chaque demande (Pillow, du
Python du système) : mire de couleurs, « Faux G1 : pas de caméra en répétition », numéro et
heure de l'image, et une bille qui avance d'une image à l'autre (on voit que la chaîne vit). Le
reste du faux G1 n'en dépend pas : sans Pillow, la demande est refusée (3104), comme une caméra
absente.
"""
import io
import time

API_IMAGE = 1001
CODE_INCONNUE = 3203
CODE_SANS_IMAGE = 3104
LARGEUR, HAUTEUR = 640, 360
POLICES = ('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
           '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
MIRE = ((192, 192, 192), (192, 192, 0), (0, 192, 192), (0, 192, 0), (192, 0, 192), (192, 0, 0),
        (0, 0, 192))


def _police(taille):
    from PIL import ImageFont
    for chemin in POLICES:
        try:
            return ImageFont.truetype(chemin, taille)
        except OSError:
            continue
    return ImageFont.load_default()


def image_test(numero, mur=None, largeur=LARGEUR, hauteur=HAUTEUR, qualite=70):
    """Octets JPEG de l'image de test n° numero (mur : heure affichée, time.time() sinon)."""
    from PIL import Image, ImageDraw
    mur = time.time() if mur is None else mur
    image = Image.new('RGB', (largeur, hauteur), (24, 28, 36))
    dessin = ImageDraw.Draw(image)
    bande = largeur / len(MIRE)
    for i, couleur in enumerate(MIRE):
        dessin.rectangle([round(i * bande), 0, round((i + 1) * bande), hauteur // 3], fill=couleur)
    grande, petite = _police(max(12, hauteur // 13)), _police(max(10, hauteur // 20))
    dessin.text((largeur // 24, hauteur // 3 + hauteur // 14),
                'Faux G1 : pas de caméra en répétition', fill=(255, 255, 255), font=grande)
    heure = time.strftime('%H:%M:%S', time.localtime(mur))
    dessin.text((largeur // 24, hauteur // 3 + hauteur // 5),
                f'Image de test n° {numero} · {heure}', fill=(200, 210, 225), font=petite)
    dessin.text((largeur // 24, hauteur // 3 + hauteur // 5 + hauteur // 12),
                'La vraie image vient de la caméra de la tête du robot.', fill=(160, 170, 185),
                font=petite)
    rayon = max(6, hauteur // 24)
    x = rayon + (numero * 17) % max(1, largeur - 2 * rayon)
    y = hauteur - 2 * rayon
    dessin.ellipse([x - rayon, y - rayon, x + rayon, y + rayon], fill=(232, 119, 46))
    sortie = io.BytesIO()
    image.save(sortie, format='JPEG', quality=qualite)
    return sortie.getvalue()


class FausseCamera:
    """Le service videohub du faux G1 : traiter(api_id, parametre) → (code, octets JPEG)."""

    def __init__(self, mur=time.time):
        self.mur = mur
        self.images = 0

    def traiter(self, api_id, parametre=''):
        if int(api_id) != API_IMAGE:
            return CODE_INCONNUE, b''
        try:
            octets = image_test(self.images + 1, self.mur())
        except ImportError:
            return CODE_SANS_IMAGE, b''
        self.images += 1
        return 0, octets
