"""
Nœud camera_poitrine (exécutable camera_usb) : la caméra de poitrine See3CAM du robot.

    ros2 run g1_equipe camera_usb                        (la See3CAM, réglages par défaut)
    ros2 run g1_equipe camera_usb --ros-args -p lieu:=demo        (réglages de camera.yaml)
    ros2 run g1_equipe camera_usb --ros-args -p source:=mire      (image de test, sans caméra)
    ros2 run g1_equipe camera_usb --ros-args -p source:=fichier -p fichier:=photo.jpg

Contrat (section 12.7 du plan) : capture par v4l2-ctl (YUYV, 1280 × 720 à 30 images par seconde
par défaut, chaque image précédée d'un en-tête, tube agrandi à 1 Mo), exposition réglée au
démarrage (auto par défaut : la See3CAM démarre en manuel à 15,6 ms, image noire dans une pièce
sombre), JPEG par Pillow sans conversion de couleurs. Il publie :
  /camera_poitrine/image/compressed  sensor_msgs/CompressedImage, format jpeg, frame_id
                                     camera_poitrine, 10 Hz, 640 pixels de large, qualité 70 ;
                                     QoS des capteurs (au mieux, profondeur 2) ;
  /camera_poitrine/etat              std_msgs/String, JSON (schéma etat_camera), 1 Hz.

Paramètres (0 ou vide : camera.yaml du lieu s'il existe, sinon le défaut) :
  source            v4l2 (la caméra), mire (image fabriquée) ou fichier (images d'un fichier) ;
  peripherique      défaut : camera.yaml, sinon /dev/g1_camera (conteneur), sinon la première
                    See3CAM de /dev/v4l/by-id ;
  lieu              id ou dossier du lieu (camera.yaml) ;
  largeur, hauteur, ips          capture (1280, 720, 30) ;
  frequence_hz, largeur_publiee, qualite_jpeg   publication (10, 640, 70) ;
  exposition        auto ou manuelle ; exposition_100us (156 = 15,6 ms) et gain (4) en manuel ;
  fichier           source fichier : YUYV brut (v4l2-ctl --stream-to), avec en-têtes
                    (--stream-to-hdr), une photo (répétée), ou une vidéo (OpenCV s'il est là),
                    relu en boucle.
Caméra absente, débranchée ou occupée : nouvel essai toutes les 2 s, « ouverte » faux et
« erreur » en français dans l'état, jamais de plantage. À l'arrêt, v4l2-ctl est arrêté.
"""
import array
from collections import deque
import json
import os
import signal
import subprocess
import sys
import threading
import time

from atelier import chemin_lieu
from atelier.lieu import equipe as E
from atelier.lieu import ErreurLieu
from g1_equipe import image_jpeg as J
from g1_equipe import peripherique as P
from rcl_interfaces.msg import ParameterDescriptor
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import String

SUJET_IMAGE = '/camera_poitrine/image/compressed'
SUJET_ETAT = '/camera_poitrine/etat'
REPERE = 'camera_poitrine'
SOURCES = ('v4l2', 'mire', 'fichier')
EXPOSITIONS = ('auto', 'manuelle')
DEFAUTS = {'largeur': 1280, 'hauteur': 720, 'ips': 30, 'frequence_hz': 10.0,
           'largeur_publiee': 640, 'qualite_jpeg': 70, 'exposition': 'auto',
           'exposition_100us': 156, 'gain': 4}
NOUVEL_ESSAI_S = 2.0            # caméra absente ou débranchée : un essai toutes les 2 s
SANS_IMAGE_S = 5.0              # plus aucune image depuis 5 s : v4l2-ctl est relancé
OUVERTE_S = 2.0                 # « ouverte » : une image lue depuis moins de 2 s
FENETRE_IPS_S = 2.0
QOS_CAPTEURS = QoSProfile(depth=2, reliability=ReliabilityPolicy.BEST_EFFORT,
                          durability=DurabilityPolicy.VOLATILE, history=HistoryPolicy.KEEP_LAST)


def reglages_du_lieu(camera):
    """Défauts tirés de camera.yaml (contenu, ou None) : {largeur, hauteur, ips, …}."""
    cam = (camera or {}).get('camera') or {}
    exposition = cam.get('exposition') or {}
    publication = cam.get('publication') or {}
    reglages = dict(DEFAUTS)
    for cle in ('largeur', 'hauteur', 'ips'):
        if cam.get(cle):
            reglages[cle] = cam[cle]
    if publication.get('frequence_hz'):
        reglages['frequence_hz'] = publication['frequence_hz']
    if publication.get('largeur'):
        reglages['largeur_publiee'] = publication['largeur']
    if publication.get('qualite_jpeg'):
        reglages['qualite_jpeg'] = publication['qualite_jpeg']
    if exposition.get('mode'):
        reglages['exposition'] = exposition['mode']
    if exposition.get('temps_100us'):
        reglages['exposition_100us'] = exposition['temps_100us']
    if exposition.get('gain') is not None:
        reglages['gain'] = exposition['gain']
    return reglages


def verifier_reglages(r):
    """Refuse (ValueError, en français) une capture ou une publication impossible."""
    if r['source'] not in SOURCES:
        raise ValueError(f'source « {r["source"]} » inconnue : {", ".join(SOURCES)}')
    if r['exposition'] not in EXPOSITIONS:
        raise ValueError(f'exposition « {r["exposition"]} » inconnue : auto ou manuelle')
    if not (160 <= r['largeur'] <= 4096 and 120 <= r['hauteur'] <= 3072) or r['largeur'] % 2:
        raise ValueError(f'taille de capture {r["largeur"]} × {r["hauteur"]} impossible '
                         '(largeur paire, de 160 × 120 à 4096 × 3072)')
    if not 1 <= r['ips'] <= 120:
        raise ValueError(f'ips {r["ips"]} : de 1 à 120 images par seconde')
    if not 0 < r['frequence_hz'] <= 30:
        raise ValueError(f'frequence_hz {r["frequence_hz"]:g} : plus que 0 et au plus 30 Hz')
    if not 160 <= r['largeur_publiee'] <= 4096:
        raise ValueError(f'largeur_publiee {r["largeur_publiee"]} : de 160 à 4096 pixels')
    if not 10 <= r['qualite_jpeg'] <= 100:
        raise ValueError(f'qualite_jpeg {r["qualite_jpeg"]} : de 10 à 100')
    if r['source'] == 'fichier' and not r['fichier']:
        raise ValueError('source:=fichier demande le paramètre fichier '
                         '(YUYV brut, photo ou vidéo)')


def faut_relancer(maintenant, derniere, lancement, delai=SANS_IMAGE_S):
    """
    Vrai si le v4l2-ctl en cours n'a donné aucune image depuis delai secondes.

    On compte depuis le plus récent de la dernière image et du lancement de ce v4l2-ctl : un
    v4l2-ctl relancé après un débranchement a toujours ses delai secondes pour donner sa première
    image (revue de la vague 5 : comparé à la dernière image d'avant, il était tué au tic suivant,
    et la caméra ne revenait jamais).
    """
    depuis = lancement if derniere is None else max(derniere, lancement)
    return maintenant - depuis > delai


class CameraPoitrine(Node):
    """Lit la caméra (ou la mire, ou un fichier) et publie les JPEG et l'état."""

    def __init__(self):
        super().__init__('camera_poitrine')
        libre = ParameterDescriptor(dynamic_typing=True)

        def p(nom, defaut):
            return self.declare_parameter(nom, defaut, libre).value

        lieu = str(p('lieu', '') or '')
        self.camera = None
        if lieu:
            try:
                self.camera = E.charger_equipe(chemin_lieu(lieu), 'camera')
            except ErreurLieu as e:
                self.get_logger().error('camera.yaml faux, réglages par défaut : ' + e.erreurs[0])
            if self.camera is None:
                self.get_logger().warning(f'pas de camera.yaml dans le lieu {lieu} : '
                                          'réglages par défaut')
        lus = reglages_du_lieu(self.camera)
        r = {'source': str(p('source', 'v4l2') or 'v4l2'), 'fichier': str(p('fichier', '') or '')}
        for cle in ('largeur', 'hauteur', 'ips', 'largeur_publiee', 'qualite_jpeg',
                    'exposition_100us'):
            r[cle] = int(p(cle, 0) or lus[cle])
        r['frequence_hz'] = float(p('frequence_hz', 0.0) or lus['frequence_hz'])
        r['exposition'] = str(p('exposition', '') or lus['exposition'])
        gain = p('gain', -1)
        r['gain'] = int(lus['gain'] if gain is None or int(gain) < 0 else gain)
        verifier_reglages(r)
        self.r = r
        peripherique = str(p('peripherique', '') or '')
        self.origine = 'paramètre'
        if not peripherique:
            peripherique, self.origine = P.peripherique_par_defaut(self.camera)
        self.peripherique = peripherique if r['source'] == 'v4l2' else (
            r['fichier'] if r['source'] == 'fichier' else None)
        self.frequence = min(r['frequence_hz'], float(r['ips']))
        self.cadence = J.Cadence(self.frequence)
        self.pub_image = self.create_publisher(CompressedImage, SUJET_IMAGE, QOS_CAPTEURS)
        self.pub_etat = self.create_publisher(String, SUJET_ETAT, 10)
        # compteurs (écrits par le fil de capture, lus par la minuterie de l'état)
        self.images = 0
        self.publiees = 0
        self.incompletes = 0
        self.taille_image = (0, 0)
        self.capture = (r['largeur'], r['hauteur'])
        self._instants = deque(maxlen=240)
        self._tailles = deque(maxlen=30)
        self._derniere = None           # instant (monotone) de la dernière image lue
        self.erreur = None
        self.avertissements = []
        self.exposition = r['exposition'] if r['source'] == 'v4l2' else None
        self.usb_mbps = None
        self.nom_camera = None
        self._processus = None
        self._fin = threading.Event()
        self._sortie_erreur = deque(maxlen=20)
        self._debut = self._lancement = time.monotonic()
        self.create_timer(1.0, self.publier_etat)
        self._fil = threading.Thread(target=self._boucle, name='capture', daemon=True)
        self._fil.start()
        quoi = {'v4l2': f'{self.peripherique} ({self.origine})', 'mire': 'mire (image de test)',
                'fichier': f'fichier {r["fichier"]}'}[r['source']]
        lp, hp = J.taille_publiee(r['largeur'], r['hauteur'], r['largeur_publiee'])
        exposition = f', exposition {r["exposition"]}' if r['source'] == 'v4l2' else ''
        self.get_logger().info(
            f'caméra de poitrine : {quoi}, capture {r["largeur"]} × {r["hauteur"]} à '
            f'{r["ips"]} i/s, publiée en {lp} × {hp} à {self.frequence:g} Hz (qualité '
            f'{r["qualite_jpeg"]}) sur {SUJET_IMAGE}{exposition}')

    # ------------------------------------------------------------ état

    def _signaler(self, erreur):
        """Note une erreur (en français) ; dans le journal une fois, tant qu'elle ne change pas."""
        if erreur != self.erreur:
            self.get_logger().error(erreur)
        self.erreur = erreur

    def ips_mesuree(self):
        """Images lues par seconde sur les deux dernières secondes, ou None."""
        maintenant = time.monotonic()
        recents = [t for t in list(self._instants) if maintenant - t <= FENETRE_IPS_S]
        if len(recents) < 2:
            return None if not recents else 0.0
        duree = recents[-1] - recents[0]
        return round((len(recents) - 1) / duree, 1) if duree > 0 else None

    def etat(self):
        """Contenu de /camera_poitrine/etat : schéma etat_camera, champs en plus permis."""
        derniere = self._derniere
        ouverte = derniere is not None and time.monotonic() - derniere < OUVERTE_S
        tailles = list(self._tailles)
        largeur, hauteur = self.taille_image
        moyenne = round(sum(tailles) / len(tailles) / 1024.0, 1) if tailles else None
        if ouverte:
            erreur = None
        elif self.erreur:
            erreur = self.erreur
        elif not self.images:
            erreur = 'en attente de la première image'
        else:
            erreur = 'plus d\'image : la caméra s\'est arrêtée'
        return {
            'version': 1, 'source': self.r['source'], 'peripherique': self.peripherique,
            'ouverte': bool(ouverte), 'largeur': int(largeur), 'hauteur': int(hauteur),
            'frequence_hz': round(self.frequence, 3), 'ips_mesuree': self.ips_mesuree(),
            'images': self.images, 'publiees': min(self.publiees, self.images),
            'taille_moyenne_ko': moyenne, 'exposition': self.exposition, 'erreur': erreur,
            'capture': {'largeur': self.capture[0], 'hauteur': self.capture[1],
                        'ips': self.r['ips']},
            'qualite_jpeg': self.r['qualite_jpeg'], 'incompletes': self.incompletes,
            'usb_mbps': self.usb_mbps, 'nom': self.nom_camera,
            'avertissements': list(self.avertissements)[-5:],
            'depuis_s': round(time.monotonic() - self._debut, 1),
        }

    def publier_etat(self):
        """Publie l'état (1 Hz) ; relance v4l2-ctl s'il ne donne plus d'image."""
        processus = self._processus
        if processus is not None and processus.poll() is None:
            if faut_relancer(time.monotonic(), self._derniere, self._lancement):
                self._signaler(f'plus aucune image de {self.peripherique} depuis '
                               f'{SANS_IMAGE_S:.0f} s : v4l2-ctl est relancé')
                self._arreter_processus()
        self.pub_etat.publish(String(data=json.dumps(self.etat(), ensure_ascii=False)))

    # ------------------------------------------------------------ images

    def _image_lue(self, brut, largeur, hauteur):
        """Une image lue : comptée, puis publiée en JPEG si la cadence le veut."""
        maintenant = time.monotonic()
        if self._derniere is None or maintenant - self._derniere > OUVERTE_S:
            self.get_logger().info(f'images reçues de {self.peripherique or "la mire"} '
                                   f'({maintenant - self._lancement:.1f} s après le lancement)')
        self.images += 1
        self._derniere = maintenant
        self._instants.append(maintenant)
        if not self.cadence.garder(maintenant):
            return
        if callable(brut):
            brut = brut()
        jpeg, taille = J.yuyv_vers_jpeg(brut, largeur, hauteur, self.r['qualite_jpeg'],
                                        self.r['largeur_publiee'])
        msg = CompressedImage()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = REPERE
        msg.format = 'jpeg'
        msg.data = array.array('B', jpeg)
        self.pub_image.publish(msg)
        self.publiees += 1
        self.taille_image = taille
        self._tailles.append(len(jpeg))
        self.erreur = None

    # ------------------------------------------------------------ boucle de capture

    def _boucle(self):
        """Fil de capture : la source choisie ; après une panne, un nouvel essai toutes les 2 s."""
        capturer = {'v4l2': self._capturer_v4l2, 'mire': self._capturer_mire,
                    'fichier': self._capturer_fichier}[self.r['source']]
        while not self._fin.is_set():
            try:
                capturer()
            except Exception as e:      # noqa: B902 : jamais de plantage à cause de la caméra
                if self._fin.is_set() or not self.context.ok():
                    break               # arrêt du nœud (Ctrl+C) pendant une publication
                self._signaler(f'erreur de capture : {e}')
            if self._fin.wait(NOUVEL_ESSAI_S):
                break

    def _v4l2(self, *arguments, delai=5.0):
        """Lance v4l2-ctl -d <périphérique> … (court) ; le résultat, ou None si v4l2-ctl manque."""
        try:
            return subprocess.run(['v4l2-ctl', '-d', self.peripherique, *arguments],
                                  capture_output=True, text=True, timeout=delai)
        except FileNotFoundError:
            self._signaler('v4l2-ctl introuvable : installez v4l-utils (dans l\'image du Jetson : '
                           'couche 2d du Dockerfile)')
        except subprocess.TimeoutExpired:
            self._signaler(f'v4l2-ctl ne répond pas sur {self.peripherique} (caméra bloquée ? '
                           'débranchez-la et rebranchez-la)')
        return None

    def _preparer_v4l2(self):
        """Exposition, puis format et cadence ; renvoie (largeur, hauteur) réelles, ou None."""
        dev = self.peripherique
        infos = P.infos_peripherique(dev)
        if not infos['existe']:
            self._signaler(f'caméra absente : {dev} n\'existe pas (caméra débranchée ? sur le '
                           'robot : g1-jetson verifier ; conteneur lancé avant de la brancher : '
                           'relancez-le)')
            return None
        self.usb_mbps, self.nom_camera = infos['usb_mbps'], infos['nom']
        avertissements = []
        if self.usb_mbps is not None and self.usb_mbps < P.USB3_MBPS and self.r['largeur'] > 640:
            avertissements.append(f'lien USB à {self.usb_mbps} Mbit/s (USB 2) : '
                                  f'{self.r["largeur"]} × {self.r["hauteur"]} à {self.r["ips"]} '
                                  'i/s ne passe pas, branchez la caméra sur un port USB 3 (bleu)')
        r = self._v4l2('--list-ctrls-menus')
        if r is None:
            return None
        if r.returncode != 0:
            self._signaler(P.message_erreur_v4l2(r.stderr, dev, r.stdout))
            return None
        controles = J.reglages_camera(r.stdout)
        appels, notes = J.commandes_exposition(controles, self.r['exposition'],
                                               self.r['exposition_100us'], self.r['gain'])
        avertissements += notes
        for appel in appels:
            r = self._v4l2('-c', ','.join(appel))
            if r is not None and r.returncode != 0:
                # v4l2-ctl : « Error setting controls: … » sur la sortie d'erreur, et l'ioctl qui
                # échoue sur la sortie standard
                lignes = r.stderr.strip().splitlines() or r.stdout.strip().splitlines() or ['?']
                avertissements.append(f'exposition non réglée ({",".join(appel)}) : '
                                      + lignes[-1][:200])
        largeur, hauteur = self.r['largeur'], self.r['hauteur']
        r = self._v4l2(f'--set-fmt-video=width={largeur},height={hauteur},pixelformat=YUYV',
                       f'--set-parm={self.r["ips"]}')
        if r is None:
            return None
        if r.returncode != 0:
            # caméra lue par un autre programme : « VIDIOC_S_FMT: failed: Device or resource
            # busy », écrit par v4l2-ctl sur la sortie standard (code 255)
            self._signaler(P.message_erreur_v4l2(r.stderr, dev, r.stdout))
            return None
        r = self._v4l2('--get-fmt-video')
        lu = P.lire_format(r.stdout) if r is not None and r.returncode == 0 else None
        if lu is None:
            detail = ((r.stderr.strip() or r.stdout.strip())[:200]) if r else ''
            self._signaler(f'format d\'image de {dev} illisible : {detail}')
            return None
        if lu[2] and lu[2] != 'YUYV':
            self._signaler(f'{dev} ne donne pas d\'images YUYV (format {lu[2]}) : ce nœud ne lit '
                           'que le YUYV (See3CAM, la plupart des webcams)')
            return None
        if (lu[0], lu[1]) != (largeur, hauteur):
            avertissements.append(f'la caméra ne fait pas {largeur} × {hauteur} : elle donne '
                                  f'{lu[0]} × {lu[1]} (v4l2-ctl -d {dev} --list-formats-ext)')
        for a in avertissements:
            if a not in self.avertissements:
                self.get_logger().warning(a)
        self.avertissements = avertissements
        return lu[0], lu[1]

    def _capturer_v4l2(self):
        """Une session de capture par v4l2-ctl, jusqu'à la fin du flux (ou l'arrêt du nœud)."""
        taille = self._preparer_v4l2()
        if taille is None or self._fin.is_set():
            return
        largeur, hauteur = self.capture = taille
        self._sortie_erreur.clear()
        self._lancement = time.monotonic()
        try:
            self._processus = subprocess.Popen(
                ['v4l2-ctl', '-d', self.peripherique, '--stream-mmap=4', '--stream-to-hdr=-'],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0, start_new_session=True)
        except FileNotFoundError:
            self._signaler('v4l2-ctl introuvable : installez v4l-utils')
            return
        processus = self._processus
        J.agrandir_tube(processus.stdout.fileno())
        lecteur_erreurs = threading.Thread(target=self._lire_erreurs, args=(processus,),
                                           daemon=True)
        lecteur_erreurs.start()
        lecteur = J.LecteurImages(processus.stdout, largeur, hauteur, avec_entete=True)
        try:
            while not self._fin.is_set():
                vue = lecteur.lire()
                if vue is None:
                    break
                self.incompletes = lecteur.incompletes
                self._image_lue(vue, largeur, hauteur)
        except J.ErreurImage as e:
            self._signaler(f'{self.peripherique} : {e}')
        finally:
            self._arreter_processus()
            lecteur_erreurs.join(timeout=1.0)
            self._arreter_processus(fermer_flux=True)
        if not self._fin.is_set():
            texte = '\n'.join(self._sortie_erreur)
            if texte.strip():
                self._signaler(P.message_erreur_v4l2(texte, self.peripherique))
            else:
                self._signaler(f'caméra {self.peripherique} arrêtée (débranchée ?) : nouvel essai '
                               f'dans {NOUVEL_ESSAI_S:.0f} s')

    def _lire_erreurs(self, processus):
        """Garde la fin de la sortie d'erreur de v4l2-ctl (le tube ne se bouche jamais)."""
        for ligne in iter(processus.stderr.readline, b''):
            texte = ligne.decode('utf-8', 'replace').strip(' <>\n')
            if texte:
                self._sortie_erreur.append(texte)

    def _arreter_processus(self, fermer_flux=False):
        """
        Arrête v4l2-ctl (SIGTERM au groupe, puis SIGKILL).

        fermer_flux : ferme aussi ses tubes (seul le fil de capture le fait : lui seul les lit).
        """
        processus = self._processus
        if processus is None:
            return
        if processus.poll() is None:
            try:
                os.killpg(processus.pid, signal.SIGTERM)
                processus.wait(timeout=2.0)
            except (ProcessLookupError, PermissionError):
                pass
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(processus.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
                processus.wait(timeout=2.0)
        if not fermer_flux:
            return
        for flux in (processus.stdout, processus.stderr):
            try:
                flux.close()
            except OSError:
                pass

    def _rythme(self, fournir, largeur, hauteur, boucle):
        """Images d'une source sans caméra, au rythme de ips ; fournir() → image ou None."""
        periode = 1.0 / self.r['ips']
        prochain = self._lancement = time.monotonic()
        vides = 0
        while not self._fin.is_set():
            image = fournir()
            if image is None:
                vides += 1
                if vides > 1:
                    self._signaler(f'aucune image de {largeur} × {hauteur} dans '
                                   f'{self.peripherique}')
                    return
                if not boucle():
                    return
                continue
            vides = 0
            self._image_lue(image, largeur, hauteur)
            prochain += periode
            attente = prochain - time.monotonic()
            if attente < -1.0:
                prochain = time.monotonic()      # en retard d'une seconde : on repart d'ici
            elif self._fin.wait(max(0.0, attente)):
                return

    def _capturer_mire(self):
        """Source mire : l'image de test de image_jpeg.Mire."""
        largeur, hauteur = self.r['largeur'], self.r['hauteur']
        mire = J.Mire(largeur, hauteur)
        compte = [0]

        def fournir():
            compte[0] += 1
            return memoryview(mire.image(compte[0]))
        self._rythme(fournir, largeur, hauteur, lambda: True)

    def _capturer_fichier(self):
        """Source fichier : YUYV brut ou avec en-têtes, photo répétée, ou vidéo (OpenCV)."""
        chemin = self.r['fichier']
        largeur, hauteur = self.r['largeur'], self.r['hauteur']
        if not os.path.isfile(chemin):
            self._signaler(f'fichier {chemin} introuvable (paramètre fichier)')
            return
        nature = J.nature_fichier(chemin, largeur, hauteur)
        if nature == 'image':
            from PIL import Image
            with Image.open(chemin) as photo:
                brut = memoryview(J.image_vers_yuyv(photo, largeur, hauteur))
            self._rythme(lambda: brut, largeur, hauteur, lambda: True)
            return
        if nature == 'video':
            self._capturer_video(chemin, largeur, hauteur)
            return
        etat = {'flux': open(chemin, 'rb')}
        etat['lecteur'] = J.LecteurImages(etat['flux'], largeur, hauteur,
                                          avec_entete=nature == 'entete')

        def recommencer():
            etat['flux'].seek(0)
            return True
        try:
            self._rythme(lambda: etat['lecteur'].lire(), largeur, hauteur, recommencer)
        finally:
            etat['flux'].close()

    def _capturer_video(self, chemin, largeur, hauteur):
        """Une vidéo lue par OpenCV (s'il est installé), convertie en YUYV seulement si publiée."""
        try:
            import cv2
        except ImportError:
            self._signaler(f'{chemin} : vidéo illisible sans OpenCV ; enregistrez plutôt une '
                           'vidéo YUYV (v4l2-ctl --stream-to-hdr=video.hdr) ou donnez une photo')
            return
        from PIL import Image
        video = cv2.VideoCapture(chemin)
        if not video.isOpened():
            self._signaler(f'{chemin} : vidéo illisible par OpenCV')
            return
        courante = {}

        def fournir():
            ok, bgr = video.read()
            if not ok:
                return None
            courante['bgr'] = bgr
            return lambda: memoryview(J.image_vers_yuyv(
                Image.fromarray(cv2.cvtColor(courante['bgr'], cv2.COLOR_BGR2RGB)), largeur,
                hauteur))

        def recommencer():
            video.set(cv2.CAP_PROP_POS_FRAMES, 0)
            return True
        try:
            self._rythme(fournir, largeur, hauteur, recommencer)
        finally:
            video.release()

    # ------------------------------------------------------------ arrêt

    def arreter(self):
        """Arrête la capture et v4l2-ctl."""
        self._fin.set()
        self._arreter_processus()
        self._fil.join(timeout=3.0)


def main(args=None):
    """Lance le nœud camera_poitrine (ros2 run g1_equipe camera_usb)."""
    rclpy.init(args=args)
    noeud = None

    def sur_sigterm(_numero, _cadre):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, sur_sigterm)
    code = 0
    try:
        noeud = CameraPoitrine()
        rclpy.spin(noeud)
    except ValueError as e:
        print(f'camera_usb : {e}', file=sys.stderr)
        code = 2
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        if noeud is not None:
            noeud.arreter()
            noeud.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return code


if __name__ == '__main__':
    sys.exit(main())
