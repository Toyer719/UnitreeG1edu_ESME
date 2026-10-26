"""
Caméra de la tête pour la Vue du robot de l'onglet Pilotage (section 11.13 du plan).

Le service videohub du robot (SDK d'Unitree : unitree_sdk2py/go2/video/video_client.py,
GetImageSample, api 1001) rend une image JPEG dans le champ binary de sa réponse
(/api/videohub/request → /api/videohub/response, unitree_api). Le nœud ne la demande que quand
une page la regarde (GET /camera de son API, relayé par l'Atelier) : une image à la fois, au plus
toutes les CAMERA_ECART_MIN_S (5 par seconde, toutes pages comprises), la dernière étant partagée.
Jamais le flux H264 de /frontvideostream : il chargerait le réseau même sans personne pour
regarder.
En répétition, le faux G1 (g1_jumeau) répond avec une image de test.

Logique sans ROS, horloge injectable : testée seule (test/test_camera.py).
"""
import time

from .contrat import charger

D = charger()

API_IMAGE = D.API_VIDEO['get_image_sample']
DEBUT_JPEG = b'\xff\xd8'
TAILLE_MAX_OCTETS = 4 * 1024 * 1024


class Camera:
    """Dernière image de la caméra de la tête, et la demande en cours au service videohub."""

    def __init__(self, horloge=time.monotonic, ecart_min_s=D.CAMERA_ECART_MIN_S,
                 delai_s=D.CAMERA_DELAI_S):
        self.horloge = horloge
        self.ecart_min_s = float(ecart_min_s)
        self.delai_s = float(delai_s)
        self.image = None               # octets JPEG de la dernière image reçue
        self.t_image = None
        self.numero = 0                 # images reçues depuis le lancement
        self.attente = None             # (identifiant, instant) de la demande en cours
        self.t_demande = None
        self.demandes = 0
        self.erreur = None              # dernière erreur, en français

    def demander(self, identifiant, t=None):
        """
        Vrai si une demande doit partir maintenant au robot avec cet identifiant.

        Faux si l'image est assez récente, ou si une demande attend encore sa réponse.
        """
        t = self.horloge() if t is None else t
        if self.attente is not None and t - self.attente[1] < self.delai_s:
            return False
        self.expirer(t)
        if self.t_demande is not None and t - self.t_demande < self.ecart_min_s:
            return False
        self.attente = (int(identifiant), t)
        self.t_demande = t
        self.demandes += 1
        return True

    def sur_reponse(self, identifiant, code, binaire, t=None):
        """Réponse du service videohub. Faux si elle n'est pas à nous (ou périmée)."""
        t = self.horloge() if t is None else t
        if self.attente is None or int(identifiant) != self.attente[0]:
            return False
        self.attente = None
        code = int(code)
        donnees = bytes(binaire or b'')
        if code != 0:
            self.erreur = f'La caméra a refusé la demande (code {code}).'
        elif not donnees.startswith(DEBUT_JPEG):
            self.erreur = 'La caméra a rendu autre chose qu\'une image JPEG.'
        elif len(donnees) > TAILLE_MAX_OCTETS:
            self.erreur = f'Image trop grande ({len(donnees)} octets).'
        else:
            self.image, self.t_image = donnees, t
            self.numero += 1
            self.erreur = None
        return True

    def expirer(self, t=None):
        """Demande sans réponse depuis delai_s : oubliée, avec un message."""
        t = self.horloge() if t is None else t
        if self.attente is not None and t - self.attente[1] >= self.delai_s:
            self.erreur = (f'Le service videohub n\'a pas répondu en {self.delai_s:g} s : '
                           'caméra absente ou service arrêté (à vérifier sur le robot).')
            self.attente = None

    def en_attente(self, t=None):
        t = self.horloge() if t is None else t
        return self.attente is not None and t - self.attente[1] < self.delai_s

    def derniere(self, t=None):
        """(octets JPEG, âge en s, numéro) de la dernière image, ou None."""
        t = self.horloge() if t is None else t
        if self.image is None:
            return None
        return self.image, max(0.0, t - self.t_image), self.numero

    def etat(self, t=None):
        t = self.horloge() if t is None else t
        return {'images': self.numero, 'demandes': self.demandes,
                'age_s': None if self.t_image is None else round(t - self.t_image, 2),
                'erreur': self.erreur}
