"""Dernières images de la caméra reçues par l'Atelier (vague 5, section 12.7 du plan), sans ROS.

Le pont ROS 2 du serveur (atelier/serveur/pont_ros.py) range ici chaque JPEG reçu sur un sujet de
SUJETS_IMAGES (sensor_msgs/CompressedImage) ; les routes /api/camera/* (routes/camera.py) les
lisent : la dernière image, son numéro, son âge, sa taille et la cadence de réception. Une image
n'est gardée qu'une fois (la dernière) : rien ne s'accumule en mémoire.

  SOURCES_IMAGES         nom court de la route (?source=) → sujet ROS 2
  taille_jpeg(octets)    (largeur, hauteur) lues dans l'en-tête d'un JPEG, sans le décoder
  DernieresImages        la dernière image d'un sujet, sûre entre fils (le pont écrit, les routes lisent)
  partie_mjpeg(image)    une partie du flux multipart/x-mixed-replace (boundary image-g1)
  Cadence                au plus N images par seconde dans un flux, sans en perdre à cause du hasard
                         des arrivées (même règle que la publication du nœud camera_usb)
"""
import math
import struct
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional

from atelier.lieu.equipe import SUJETS_IMAGES

SOURCES_IMAGES = {"poitrine": "/camera_poitrine/image/compressed", "visiteurs": "/visiteurs/image/compressed"}
assert set(SOURCES_IMAGES.values()) == set(SUJETS_IMAGES), "SOURCES_IMAGES et SUJETS_IMAGES divergent"
FRONTIERE = "image-g1"
FENETRE_IPS_S = 2.0          # cadence de réception mesurée sur les 2 dernières secondes


def taille_jpeg(octets):
    """(largeur, hauteur) lues dans l'en-tête d'un JPEG (marqueur SOF), ou None s'il est illisible."""
    donnees = bytes(octets[:min(len(octets), 1 << 20)])
    if donnees[:2] != b"\xff\xd8":
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
        longueur = struct.unpack(">H", donnees[i + 2:i + 4])[0]
        if 0xC0 <= marqueur <= 0xCF and marqueur not in (0xC4, 0xC8, 0xCC):
            if i + 9 > len(donnees):
                return None
            hauteur, largeur = struct.unpack(">HH", donnees[i + 5:i + 9])
            return (largeur, hauteur) if largeur and hauteur else None
        i += 2 + longueur
    return None


@dataclass(frozen=True)
class ImageRecue:
    """Une image reçue : octets JPEG, numéro (compteur des images reçues, à partir de 1), instant
    de réception (horloge monotone), taille lue dans le JPEG, horodatage ROS de l'image (s)."""
    numero: int
    octets: bytes
    recue: float
    largeur: Optional[int]
    hauteur: Optional[int]
    temps: Optional[float] = None

    def age(self, maintenant=None):
        return (time.monotonic() if maintenant is None else maintenant) - self.recue


class DernieresImages:
    """La dernière image d'un sujet, et de quoi mesurer la cadence de réception."""

    def __init__(self):
        self._verrou = threading.Lock()
        self._derniere = None
        self._numero = 0
        self._instants = deque(maxlen=120)

    def ajouter(self, octets, temps=None, instant=None):
        """Range une image reçue ; renvoie son numéro."""
        instant = time.monotonic() if instant is None else instant
        taille = taille_jpeg(octets) or (None, None)
        with self._verrou:
            self._numero += 1
            self._derniere = ImageRecue(self._numero, bytes(octets), instant, taille[0], taille[1], temps)
            self._instants.append(instant)
            return self._numero

    def derniere(self):
        """La dernière ImageRecue, ou None."""
        with self._verrou:
            return self._derniere

    def ips(self, maintenant=None):
        """Images reçues par seconde sur les 2 dernières secondes (0 sans image récente)."""
        maintenant = time.monotonic() if maintenant is None else maintenant
        with self._verrou:
            recents = [t for t in self._instants if maintenant - t <= FENETRE_IPS_S]
        if len(recents) < 2:
            return 0.0
        return round((len(recents) - 1) / max(recents[-1] - recents[0], 1e-6), 1)

    def etat(self, maintenant=None):
        """{recue, numero, age_s, largeur, hauteur, octets, ips} (route /api/camera/etat)."""
        maintenant = time.monotonic() if maintenant is None else maintenant
        image = self.derniere()
        if image is None:
            return {"recue": False, "numero": 0, "age_s": None, "largeur": None, "hauteur": None,
                    "octets": None, "ips": 0.0}
        return {"recue": True, "numero": image.numero, "age_s": round(image.age(maintenant), 2),
                "largeur": image.largeur, "hauteur": image.hauteur, "octets": len(image.octets),
                "ips": self.ips(maintenant)}

    def oublier(self):
        with self._verrou:
            self._derniere = None
            self._instants.clear()


def entetes_image(image, maintenant=None):
    """En-têtes HTTP d'une image (route /api/camera/image)."""
    entetes = {"X-Image-Numero": str(image.numero), "X-Image-Age-S": f"{image.age(maintenant):.3f}",
               "Cache-Control": "no-store"}
    if image.largeur:
        entetes["X-Image-Largeur"] = str(image.largeur)
        entetes["X-Image-Hauteur"] = str(image.hauteur)
    return entetes


class Cadence:
    """Au plus frequence_hz images par seconde, régulièrement (le flux MJPEG de routes/camera.py).

    garder(instant) dit si une image peut partir à cet instant (secondes, horloge monotone) ; vrai, il
    compte l'envoi. Une image un peu en avance (d'un quart de période au plus) part quand même : une
    caméra à 10 images par seconde n'en perd aucune à cause des écarts d'arrivée, et le flux n'envoie
    jamais plus de frequence_hz images par seconde en moyenne, même si la caméra va plus vite. Après
    un trou (plus d'une période de retard), le compte repart de l'instant présent. C'est la règle de
    g1_equipe.image_jpeg.Cadence (publication du nœud camera_usb), recopiée ici : l'Atelier n'importe
    pas les paquets ROS.
    """

    def __init__(self, frequence_hz):
        if not frequence_hz or not math.isfinite(frequence_hz) or frequence_hz <= 0:
            raise ValueError(f"fréquence impossible : {frequence_hz}")
        self.periode = 1.0 / float(frequence_hz)
        self.prochain = None

    def garder(self, instant):
        """Vrai si une image peut partir à cet instant (et l'envoi est compté)."""
        if self.prochain is None or instant >= self.prochain - self.periode / 4.0:
            if self.prochain is None or instant - self.prochain > self.periode:
                self.prochain = instant + self.periode       # départ, ou retard : on repart d'ici
            else:
                self.prochain += self.periode
            return True
        return False


def partie_mjpeg(image):
    """Une partie du flux MJPEG : frontière, en-têtes (Content-Type, Content-Length, X-Image-Numero),
    puis le JPEG."""
    entete = (f"--{FRONTIERE}\r\nContent-Type: image/jpeg\r\nContent-Length: {len(image.octets)}\r\n"
              f"X-Image-Numero: {image.numero}\r\n\r\n")
    return entete.encode("ascii") + image.octets + b"\r\n"


__all__ = ["Cadence", "DernieresImages", "FRONTIERE", "ImageRecue", "SOURCES_IMAGES", "entetes_image",
           "partie_mjpeg", "taille_jpeg"]
