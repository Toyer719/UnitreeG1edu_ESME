"""
Interface Moteur : ce qui fait avancer le robot le long d'un itinéraire (section 4.6 du plan).

Le guide (guide.py) ne parle jamais directement à Nav2 ni au service slam_operate du robot :
il passe par un Moteur. Deux réalisations sont prévues, chacune dans son fichier :
  - MoteurNav2, dans moteur_nav2.py (agent Navigation) : Nav2, avec goThroughPoses ;
  - MoteurUnitree, dans moteur_unitree.py (agent Scan) : commande 1102 de slam_operate,
    tronçon par tronçon, en ligne droite, 8 m au plus par tronçon.
MoteurFactice, plus bas, avance sur le papier, sans robot ni ROS : il sert aux tests du guide.

Règles communes aux moteurs :
  - une pose est un tuple (x, y, theta) dans le repère map, en mètres et en radians ;
  - les méthodes rendent la main vite (moins d'une seconde) : le déplacement continue en
    arrière-plan, et le guide appelle etat() régulièrement, environ 5 fois par seconde ;
  - elles sont toutes appelées depuis le même fil, celui du guide.
"""
import abc
import math
import time

# Le robot « progresse » s'il a gagné au moins SEUIL_PROGRES_M sur la distance restante
# pendant les FENETRE_PROGRES_S dernières secondes.
SEUIL_PROGRES_M = 0.10
FENETRE_PROGRES_S = 1.0

# Les cinq clés de etat(), toujours présentes
CLES_ETAT = ('en_cours', 'arrive', 'echec', 'reste_m', 'progresse')


def etat_repos():
    """Renvoie l'état d'un moteur au repos : jamais démarré, ou annulé."""
    return {'en_cours': False, 'arrive': False, 'echec': False, 'reste_m': None,
            'progresse': False}


class Moteur(abc.ABC):
    """Fait aller le robot jusqu'à la dernière pose d'une liste, en passant par les autres."""

    @abc.abstractmethod
    def demarrer(self, poses):
        """
        Lance le déplacement et rend la main sans attendre l'arrivée.

        poses : liste de (x, y, theta) dans le repère map. La dernière est la destination,
        où le robot s'arrête tourné vers theta ; les autres sont les nœuds de l'itinéraire, à
        traverser dans l'ordre (leur theta indique seulement le sens de la marche).
        Un déplacement déjà en cours est remplacé par le nouveau.
        Renvoie True si le moteur accepte le déplacement ; sinon False, et etat() indique
        echec. Lève ValueError si poses est vide ou si une pose n'a pas trois valeurs.
        """

    @abc.abstractmethod
    def annuler(self):
        """
        Arrête le robot au plus vite et abandonne le déplacement en cours.

        Sans effet si rien n'est en cours. Ensuite, etat() renvoie l'état de repos
        (etat_repos()) : une annulation demandée par le guide n'est pas un échec.
        """

    @abc.abstractmethod
    def etat(self):
        """
        Renvoie l'état du déplacement : un dict neuf avec exactement les clés de CLES_ETAT.

        en_cours  (bool) le robot est en route vers la dernière pose ;
        arrive    (bool) la dernière pose est atteinte, à la tolérance du moteur près ;
        echec     (bool) le moteur a renoncé : but refusé, abandon de Nav2, erreur de 1102... ;
        reste_m   (float ou None) distance restante jusqu'à la dernière pose, en mètres, en
                  passant par les poses restantes ; 0.0 à l'arrivée ; None si inconnue ;
        progresse (bool) reste_m a baissé d'au moins SEUIL_PROGRES_M pendant les
                  FENETRE_PROGRES_S dernières secondes (voir SuiviProgres).
        Au plus une des clés en_cours, arrive et echec est vraie. Toutes fausses : repos.
        """


def verifier_poses(poses):
    """Renvoie poses en liste de tuples de trois flottants ; lève ValueError si invalide."""
    poses = [tuple(float(v) for v in p) for p in poses]
    if not poses:
        raise ValueError('il faut au moins une pose (x, y, theta)')
    for p in poses:
        if len(p) != 3:
            raise ValueError(f'pose {p} : il faut trois valeurs (x, y, theta)')
    return poses


class SuiviProgres:
    """
    Calcule la clé « progresse » à partir des valeurs successives de reste_m.

    À utiliser dans les moteurs : effacer() à chaque départ, noter(reste_m) à chaque nouvelle
    mesure, progresse() dans etat().
    """

    def __init__(self, seuil_m=SEUIL_PROGRES_M, fenetre_s=FENETRE_PROGRES_S,
                 horloge=time.monotonic):
        self.seuil_m = seuil_m
        self.fenetre_s = fenetre_s
        self.horloge = horloge
        self._mesures = []    # (instant, reste_m), de la plus ancienne à la plus récente

    def effacer(self):
        """Oublie les mesures précédentes."""
        self._mesures = []

    def noter(self, reste_m):
        """Enregistre la distance restante mesurée maintenant. None est ignoré."""
        if reste_m is None:
            return
        maintenant = self.horloge()
        self._mesures.append((maintenant, float(reste_m)))
        # On garde une seule mesure plus ancienne que la fenêtre : la référence
        while len(self._mesures) > 2 and self._mesures[1][0] <= maintenant - self.fenetre_s:
            self._mesures.pop(0)

    def progresse(self):
        """
        Vrai si reste_m a baissé d'au moins seuil_m depuis la référence.

        La référence est la dernière mesure prise au moins fenetre_s secondes avant
        maintenant ; à défaut (départ récent), la première mesure.
        """
        if len(self._mesures) < 2:
            return False
        limite = self.horloge() - self.fenetre_s
        reference = self._mesures[0][1]
        for instant, reste in self._mesures:
            if instant <= limite:
                reference = reste
        return reference - self._mesures[-1][1] >= self.seuil_m


class MoteurFactice(Moteur):
    """
    Moteur sans robot ni ROS, pour les tests : un point qui glisse le long des poses.

    Il va en ligne droite d'une pose à la suivante, à vitesse constante, et tourne sans
    délai. Le temps vient de horloge (time.monotonic par défaut, ou une fausse horloge de
    test). bloquer() l'immobilise comme un obstacle ; echouer() simule un abandon.
    L'attribut position (x, y, theta) joue le rôle de l'odométrie.
    """

    def __init__(self, depart=(0.0, 0.0, 0.0), vitesse=0.5, horloge=time.monotonic):
        self.position = tuple(float(v) for v in depart)
        self.vitesse = vitesse
        self.horloge = horloge
        self.bloque = False
        self._suivi = SuiviProgres(horloge=horloge)
        self._restantes = []
        self._etat = etat_repos()
        self._instant = horloge()

    def demarrer(self, poses):
        poses = verifier_poses(poses)
        self._avancer()
        self._restantes = poses
        self._suivi.effacer()
        self._etat = dict(etat_repos(), en_cours=True, reste_m=self._reste())
        return True

    def annuler(self):
        self._avancer()
        self._restantes = []
        self._etat = etat_repos()

    def bloquer(self, oui=True):
        """Immobilise le robot (oui=True), comme devant un obstacle, ou le libère."""
        self._avancer()
        self.bloque = oui

    def echouer(self):
        """Provoque un abandon du moteur : le robot s'arrête, etat() indique echec."""
        self._avancer()
        self._restantes = []
        self._etat = dict(etat_repos(), echec=True)

    def etat(self):
        self._avancer()
        if self._etat['en_cours']:
            if self._restantes:
                reste = self._reste()
                self._suivi.noter(reste)
                self._etat.update(reste_m=reste, progresse=self._suivi.progresse())
            else:
                self._etat = dict(etat_repos(), arrive=True, reste_m=0.0)
        return dict(self._etat)

    def _reste(self):
        points = [self.position[:2]] + [p[:2] for p in self._restantes]
        return sum(math.dist(a, b) for a, b in zip(points, points[1:]))

    def _avancer(self):
        """Fait avancer le point de la distance parcourue depuis l'appel précédent."""
        maintenant = self.horloge()
        pas = 0.0 if self.bloque else self.vitesse * (maintenant - self._instant)
        self._instant = maintenant
        while self._restantes:
            x, y, _ = self.position
            cx, cy, ctheta = self._restantes[0]
            distance = math.hypot(cx - x, cy - y)
            if pas < distance:
                cap = math.atan2(cy - y, cx - x)
                self.position = (x + pas * math.cos(cap), y + pas * math.sin(cap), cap)
                break
            pas -= distance
            self.position = (cx, cy, ctheta)
            self._restantes.pop(0)
