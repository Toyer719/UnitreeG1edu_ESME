"""
Faux v4l2-ctl des tests de camera_usb : une See3CAM_11CUG sans caméra.

Les tests le mettent en tête du PATH sous le nom v4l2-ctl. Il note chaque appel (une ligne JSON
par appel) dans $FAUX_V4L2_JOURNAL, et répond comme la vraie caméra et le vrai v4l2-ctl 1.22 (un
ioctl qui échoue est écrit sur la sortie standard, « VIDIOC_…: failed: … », code 255 ; vu sur le PC
le 31/10/2026) :
  --list-ctrls-menus     les réglages lus sur la See3CAM du PC (31/10/2026) ;
  -c a=b,c=d             accepté ; refusé avec FAUX_V4L2_REFUS=1 (« VIDIOC_S_EXT_CTRLS: failed »
                         sur la sortie standard, « Error setting controls » sur l'autre) ;
  --set-fmt-video=…      retenu dans $FAUX_V4L2_JOURNAL.format ; « Device or resource busy » sur
                         la sortie standard avec FAUX_V4L2_OCCUPE=1 (caméra déjà lue ailleurs) ;
  --get-fmt-video        le format retenu ;
  --stream-to-hdr=-      des images YUYV avec leur en-tête, à $FAUX_V4L2_IPS par seconde (30), sans
                         fin, ou $FAUX_V4L2_IMAGES images puis la sortie « No such device » (caméra
                         débranchée).
"""
import json
import os
import struct
import sys
import time

REGLAGES_SEE3CAM = """
User Controls

                     brightness 0x00980900 (int)    : min=0 max=99 step=1 default=50 value=50
                           gain 0x00980913 (int)    : min=1 max=32 step=1 default=4 value=4
           power_line_frequency 0x00980918 (menu)   : min=0 max=2 default=1 value=1 (50 Hz)
\t\t\t\t0: Disabled
\t\t\t\t1: 50 Hz
\t\t\t\t2: 60 Hz

Camera Controls

                  auto_exposure 0x009a0901 (menu)   : min=0 max=3 default=1 value=1 (Manual Mode)
\t\t\t\t0: Auto Mode
\t\t\t\t1: Manual Mode
         exposure_time_absolute 0x009a0902 (int)    : min=1 max=20000 step=1 default=156 value=156
"""


def journal(arguments):
    """Note l'appel."""
    chemin = os.environ.get('FAUX_V4L2_JOURNAL')
    if chemin:
        with open(chemin, 'a', encoding='utf-8') as f:
            f.write(json.dumps({'pid': os.getpid(), 'arguments': arguments}) + '\n')


def format_retenu():
    """(largeur, hauteur) du dernier --set-fmt-video."""
    chemin = os.environ.get('FAUX_V4L2_JOURNAL', '/tmp/faux_v4l2') + '.format'
    try:
        largeur, hauteur = open(chemin, encoding='utf-8').read().split()
        return int(largeur), int(hauteur)
    except (OSError, ValueError):
        return 1280, 720


def main(arguments):
    """Répond comme v4l2-ctl."""
    journal(arguments)
    if '--list-ctrls-menus' in arguments:
        print(REGLAGES_SEE3CAM)
        return 0
    if '-c' in arguments:
        if os.environ.get('FAUX_V4L2_REFUS') == '1':
            print('VIDIOC_S_EXT_CTRLS: failed: Permission denied')
            print('Error setting controls: Permission denied', file=sys.stderr)
            return 255
        return 0
    for a in arguments:
        if a.startswith('--set-fmt-video='):
            if os.environ.get('FAUX_V4L2_OCCUPE') == '1':
                print('VIDIOC_S_FMT: failed: Device or resource busy')
                print('VIDIOC_S_PARM: failed: Device or resource busy')
                return 255
            champs = dict(x.split('=') for x in a.split('=', 1)[1].split(','))
            chemin = os.environ.get('FAUX_V4L2_JOURNAL', '/tmp/faux_v4l2') + '.format'
            with open(chemin, 'w', encoding='utf-8') as f:
                f.write(f'{champs["width"]} {champs["height"]}')
            print('Frame rate set to 30.000 fps')
            return 0
    if '--get-fmt-video' in arguments:
        largeur, hauteur = format_retenu()
        print(f"Format Video Capture:\n\tWidth/Height      : {largeur}/{hauteur}\n"
              f"\tPixel Format      : 'YUYV' (YUYV 4:2:2)")
        return 0
    if '--stream-to-hdr=-' in arguments:
        largeur, hauteur = format_retenu()
        taille = largeur * hauteur * 2
        image = bytes([128, 128]) * (taille // 2)
        ips = float(os.environ.get('FAUX_V4L2_IPS', '30'))
        nombre = int(os.environ.get('FAUX_V4L2_IMAGES', '0'))
        sortie = sys.stdout.buffer
        n = 0
        prochain = time.monotonic()
        while not nombre or n < nombre:
            sortie.write(b'rdhV' + struct.pack('>I', taille) + image)
            sortie.flush()
            print('<', end='', file=sys.stderr, flush=True)
            n += 1
            prochain += 1.0 / ips
            time.sleep(max(0.0, prochain - time.monotonic()))
        print('\nVIDIOC_DQBUF: failed: No such device', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv[1:]))
    except (BrokenPipeError, KeyboardInterrupt):
        sys.exit(1)
