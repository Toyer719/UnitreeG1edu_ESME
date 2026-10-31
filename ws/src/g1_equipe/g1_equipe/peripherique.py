"""
Le périphérique vidéo de la caméra de poitrine, sans ROS (vague 5, section 12.7 du plan).

  see3cam_branchees()        les See3CAM vues dans /dev/v4l/by-id (nom stable, numéro de série) ;
  infos_peripherique(chemin) chemin résolu (/dev/videoN), nom, débit du lien USB (5000 : USB 3) ;
  peripherique_par_defaut()  ce que lit le nœud camera_usb sans paramètre : camera.yaml du lieu,
                             sinon /dev/g1_camera (le conteneur du Jetson), sinon la première
                             See3CAM branchée (essais sur le PC) ;
  lire_format(texte)         taille et format d'image donnés par « v4l2-ctl --get-fmt-video ».

Rien n'est ouvert : seulement /dev et /sys lus.
"""
import os
from pathlib import Path
import re

CAMERA_CONTENEUR = '/dev/g1_camera'        # la See3CAM dans le conteneur (docker run --device)
DOSSIER_BY_ID = '/dev/v4l/by-id'
MOTIF_SEE3CAM = '*See3CAM*-video-index0'
DOSSIER_SYS_CHAR = '/sys/dev/char'
USB3_MBPS = 5000


def see3cam_branchees(dossier=DOSSIER_BY_ID):
    """Chemins by-id des See3CAM branchées (index0 : l'image ; index1 : les métadonnées)."""
    try:
        return sorted(str(p) for p in Path(dossier).glob(MOTIF_SEE3CAM) if p.exists())
    except OSError:
        return []


def _lire(chemin):
    try:
        return Path(chemin).read_text(encoding='utf-8', errors='replace').strip()
    except OSError:
        return None


def infos_peripherique(chemin, dossier_sys=DOSSIER_SYS_CHAR):
    """
    {chemin, resolu, existe, nom, usb_mbps} d'un périphérique vidéo (None si inconnu).

    Le débit vient de /sys/dev/char/<majeur>:<mineur>/device/../speed : il marche aussi dans le
    conteneur, où la caméra s'appelle /dev/g1_camera.
    """
    infos = {'chemin': str(chemin), 'resolu': None, 'existe': False, 'nom': None, 'usb_mbps': None}
    try:
        infos['resolu'] = os.path.realpath(chemin)
        st = os.stat(chemin)
    except OSError:
        return infos
    infos['existe'] = True
    if not os.path.isfile(chemin):
        sys_dev = Path(dossier_sys) / f'{os.major(st.st_rdev)}:{os.minor(st.st_rdev)}'
        infos['nom'] = _lire(sys_dev / 'name')
        vitesse = _lire(sys_dev / 'device' / '..' / 'speed')
        try:
            infos['usb_mbps'] = int(float(vitesse)) if vitesse else None
        except ValueError:
            infos['usb_mbps'] = None
    return infos


def peripherique_par_defaut(camera=None, dossier_by_id=DOSSIER_BY_ID, conteneur=CAMERA_CONTENEUR):
    """
    Le périphérique à ouvrir sans paramètre : (chemin, d'où il vient).

    camera : contenu de camera.yaml (ou None). Ordre : son « peripherique », puis /dev/g1_camera
    s'il existe (conteneur), puis la première See3CAM branchée, puis /dev/g1_camera (absent :
    le nœud le dira et réessaiera).
    """
    choisi = ((camera or {}).get('camera') or {}).get('peripherique')
    if choisi:
        return choisi, 'camera.yaml'
    if os.path.exists(conteneur):
        return conteneur, 'conteneur'
    branchees = see3cam_branchees(dossier_by_id)
    if branchees:
        return branchees[0], 'See3CAM branchée'
    return conteneur, 'défaut'


_LARGEUR_HAUTEUR = re.compile(r'Width/Height\s*:\s*(\d+)\s*/\s*(\d+)')
_FORMAT = re.compile(r"Pixel Format\s*:\s*'([^']+)'")


def lire_format(texte):
    """(largeur, hauteur, format) dans la sortie de « v4l2-ctl --get-fmt-video », ou None."""
    m = _LARGEUR_HAUTEUR.search(str(texte))
    f = _FORMAT.search(str(texte))
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), (f.group(1).strip() if f else None)


def message_erreur_v4l2(texte, chemin, sortie=''):
    """
    Phrase en français pour une erreur de v4l2-ctl, qui dit quoi faire.

    texte : sa sortie d'erreur ; sortie : sa sortie standard, où v4l2-ctl écrit les ioctl qui
    échouent (« VIDIOC_S_FMT: failed: Device or resource busy », code 255 ; v4l2-ctl 1.22).
    """
    erreurs = str(texte or '')
    t = erreurs + '\n' + str(sortie or '')
    if 'busy' in t.lower():
        return (f'caméra {chemin} occupée par un autre programme (g1-personnes, g1-visiteurs '
                '--source, cheese, un autre camera_usb ?) : fermez-le')
    if 'No such device' in t or 'No such file' in t or 'Cannot open device' in t:
        return f'caméra {chemin} débranchée ou absente : rebranchez-la (USB 3, port bleu)'
    if 'Permission denied' in t:
        return (f'pas le droit d\'ouvrir {chemin} : il faut le groupe video (dans le conteneur, '
                'g1-jetson demarrer passe --group-add)')
    # sinon, la dernière ligne de la sortie d'erreur, ou à défaut celle de la sortie standard
    lignes = ([x for x in erreurs.strip().splitlines() if x.strip()]
              or [x for x in str(sortie or '').strip().splitlines() if x.strip()])
    return f'v4l2-ctl a échoué sur {chemin}' + (f' : {lignes[-1][:300]}' if lignes else '')
