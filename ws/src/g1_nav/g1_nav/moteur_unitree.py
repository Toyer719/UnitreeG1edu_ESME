"""
MoteurUnitree : le guide fait marcher le G1 avec la navigation d'Unitree (commande 1102).

Réalise l'interface Moteur de moteurs.py (section 4.6 du plan) sur le service slam_operate
du robot, ou sur son faux service (g1-slam faux-service), par atelier.scan.slam_client :
  - l'itinéraire est découpé en tronçons droits de 8 m au plus (limite de 1102) ;
  - chaque tronçon est envoyé avec 1102 ; le suivant part quand slam_key_info annonce
    is_arrived (un is_arrived resté vrai d'un tronçon précédent est ignoré) ;
  - 1102 va en ligne droite et s'arrête devant un obstacle sans le contourner : la position
    ne change plus, progresse passe à faux, et c'est le guide qui décide de la pause ou du
    détour (annuler, puis demarrer sur un autre itinéraire) ;
  - annuler() envoie 1201 (pause) ; le démarrage suivant envoie 1102, puis 1202 (reprendre).

Le robot doit déjà être repéré sur sa carte (g1-slam relocaliser, commande 1804).
Les appels au robot se font dans un fil de fond : les méthodes rendent la main tout de suite.

Exemple (dans le guide) :
    moteur = MoteurUnitree(noeud)              # vrai robot, port eno2
    moteur = MoteurUnitree(noeud, faux=True)   # faux service sur lo
"""
import math
import os
import queue
import threading
import time

from g1_nav.moteurs import etat_repos, Moteur, SuiviProgres, verifier_poses

LONGUEUR_MAX = 8.0          # m, longueur maximale d'un tronçon envoyé avec 1102
TOLERANCE_ARRIVEE = 0.5     # m, pour croire un is_arrived sans avoir vu is_arrived faux
DELAI_REPONSE = 0.8         # s, attente de la réponse au premier 1102 dans demarrer()
DELAI_TRONCON = 120.0       # s, au-delà, un tronçon non terminé est un échec
FRAICHEUR_ODOM = 1.0        # s, /odom plus vieux : on prend la position de slam_info


def decouper(depart, poses, longueur_max=LONGUEUR_MAX):
    """
    Découpe un itinéraire en tronçons droits de longueur_max au plus.

    depart : (x, y, ...) position actuelle, ou None si inconnue (le premier tronçon part
    alors de la première pose). poses : liste de (x, y, theta). Renvoie la liste des cibles
    (x, y, theta) à envoyer dans l'ordre. Une cible intermédiaire regarde dans le sens de la
    marche ; la dernière a le theta de la dernière pose.
    """
    points = [tuple(p) for p in poses]
    precedent = tuple(depart[:2]) if depart is not None else points[0][:2]
    cibles = []
    for i, (x, y, theta) in enumerate(points):
        dernier = i == len(points) - 1
        longueur = math.hypot(x - precedent[0], y - precedent[1])
        if longueur < 1e-6:
            if dernier:
                cibles.append((x, y, theta))
            continue
        cap = math.atan2(y - precedent[1], x - precedent[0])
        nombre = max(1, math.ceil(longueur / longueur_max - 1e-9))
        for k in range(1, nombre + 1):
            f = k / nombre
            cibles.append((precedent[0] + f * (x - precedent[0]),
                           precedent[1] + f * (y - precedent[1]), cap))
        if dernier:
            cibles[-1] = (x, y, theta)
        precedent = (x, y)
    # Le cap d'une cible intermédiaire : la direction du tronçon suivant
    for i in range(len(cibles) - 1):
        a, b = cibles[i], cibles[i + 1]
        if math.hypot(b[0] - a[0], b[1] - a[1]) > 1e-6:
            cibles[i] = (a[0], a[1], math.atan2(b[1] - a[1], b[0] - a[0]))
    return cibles


def choisir_faux(noeud=None):
    """
    Dit s'il faut le faux service (sur lo) plutôt que le robot (sur eno2).

    Variable G1_SLAM_FAUX (1 : faux, 0 : robot) ; à défaut, le paramètre use_sim_time du
    nœud du guide (vrai en simulation, avec simu:=true) ; à défaut, le robot.
    """
    choix = os.environ.get('G1_SLAM_FAUX', '').strip().lower()
    if choix:
        return choix in ('1', 'true', 'oui')
    if noeud is not None:
        try:
            return bool(noeud.get_parameter('use_sim_time').value)
        except Exception:
            return False
    return False


def longueur_chemin(points):
    """Longueur d'une ligne brisée de points (x, y, ...)."""
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(points, points[1:]))


class MoteurUnitree(Moteur):
    """
    Moteur du vrai G1 : tronçons de 8 m au plus, envoyés un par un avec 1102.

    noeud      nœud rclpy du guide (facultatif) : la position est alors lue sur sujet_odom
               (relais de /unitree/slam_relocation/odom), sinon dans slam_info
    client     un atelier.scan.slam_client.ClientSlam déjà ouvert (sinon, il est créé)
    faux       True : faux service sur lo ; None : voir choisir_faux (simulation : faux)
    position   fonction sans argument qui renvoie (x, y, theta) ou None (remplace le reste)
    """

    def __init__(self, noeud=None, client=None, faux=None, interface=None, position=None,
                 sujet_odom='/odom', longueur_max=LONGUEUR_MAX, tolerance=TOLERANCE_ARRIVEE,
                 delai_troncon=DELAI_TRONCON):
        if client is None:
            from atelier.scan.slam_client import ClientSlam, connexion
            if faux is None:
                faux = choisir_faux(noeud)
            client = ClientSlam(*connexion(faux, interface), delai=3.0 if faux else 10.0)
        self.client = client
        self.longueur_max = longueur_max
        self.tolerance = tolerance
        self.delai_troncon = delai_troncon
        self._position_fournie = position
        self._odom = None             # ((x, y, theta), instant) lu sur sujet_odom
        if noeud is not None and position is None and sujet_odom:
            from nav_msgs.msg import Odometry
            from rclpy.qos import qos_profile_sensor_data
            # Profil « capteur » : accepte un éditeur fiable (Gazebo) ou au mieux (robot)
            noeud.create_subscription(Odometry, sujet_odom, self._recevoir_odom,
                                      qos_profile_sensor_data)

        self._verrou = threading.Lock()
        self._etat = etat_repos()
        self._generation = 0
        self._troncons = []
        self._index = 0
        self._suivi = SuiviProgres()
        self._en_pause = False
        self._reponse = {}            # génération → (Event, [Reponse du premier 1102])
        self._file = queue.Queue()
        self._fin = threading.Event()
        self._fil = threading.Thread(target=self._travailler, name='moteur_unitree',
                                     daemon=True)
        self._fil.start()

    # ------------------------------------------------ position

    def _recevoir_odom(self, msg):
        p = msg.pose.pose
        q = p.orientation
        theta = math.atan2(2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y * q.y + q.z * q.z))
        self._odom = ((p.position.x, p.position.y, theta), time.monotonic())

    def position(self):
        """Position actuelle (x, y, theta) dans le repère map, ou None si inconnue."""
        if self._position_fournie is not None:
            return self._position_fournie()
        odom = self._odom
        if odom is not None and time.monotonic() - odom[1] <= FRAICHEUR_ODOM:
            return odom[0]
        pose, _ = self.client.pose()
        if pose is None and odom is not None:
            return odom[0]
        return pose

    # ------------------------------------------------ interface Moteur

    def demarrer(self, poses):
        poses = verifier_poses(poses)
        troncons = decouper(self.position(), poses, self.longueur_max)
        evenement, reponse = threading.Event(), []
        with self._verrou:
            self._generation += 1
            generation = self._generation
            self._troncons, self._index = troncons, 0
            self._suivi.effacer()
            self._etat = dict(etat_repos(), en_cours=True)
            self._reponse = {generation: (evenement, reponse)}
        self._file.put(('aller', generation, troncons))
        # Le premier 1102 est-il accepté ? On attend un peu sa réponse, sans dépasser 1 s.
        if evenement.wait(DELAI_REPONSE) and reponse and not reponse[0].ok:
            return False
        return True

    def annuler(self):
        with self._verrou:
            self._generation += 1
            self._troncons, self._index = [], 0
            self._etat = etat_repos()
        self._file.put(('pause', None, None))

    def etat(self):
        with self._verrou:
            etat = dict(self._etat)
            troncons, index = list(self._troncons), self._index
        if etat['en_cours']:
            reste = self._reste(self.position(), troncons, index)
            self._suivi.noter(reste)
            etat.update(reste_m=reste, progresse=self._suivi.progresse())
        return etat

    def fermer(self):
        """Arrête le fil de fond (le robot n'est pas arrêté : appeler annuler() avant)."""
        self._fin.set()
        self._file.put(('fin', None, None))
        self._fil.join(timeout=2.0)

    # ------------------------------------------------ fil de fond

    @staticmethod
    def _reste(pose, troncons, index):
        if pose is None:
            return None
        restants = troncons[index:]
        if not restants:
            return 0.0
        return longueur_chemin([pose] + restants)

    def _perime(self, generation):
        """Vrai si ce déplacement est remplacé (demarrer, annuler) ou si le moteur s'arrête."""
        return generation != self._generation or not self._file.empty() or self._fin.is_set()

    def _finir(self, generation, **etat):
        with self._verrou:
            if generation == self._generation:
                self._etat = dict(etat_repos(), **etat)

    def _travailler(self):
        while not self._fin.is_set():
            action, generation, troncons = self._file.get()
            if action == 'fin':
                return
            if action == 'pause':
                self.client.pause()
                self._en_pause = True
            elif action == 'aller' and generation == self._generation:
                self._naviguer(generation, troncons)

    def _signaler(self, generation, reponse):
        evenement, liste = self._reponse.get(generation, (None, None))
        if evenement is not None and not evenement.is_set():
            liste.append(reponse)
            evenement.set()

    def _naviguer(self, generation, troncons):
        from atelier.scan.slam_client import SuiviArrivee
        for i, cible in enumerate(troncons):
            if self._perime(generation):
                return
            envoi = time.monotonic()
            reponse = self.client.aller(*cible)
            self._signaler(generation, reponse)
            if not reponse.ok:
                self._finir(generation, echec=True)
                return
            if self._en_pause:
                self.client.reprendre()     # au cas où la pause survit à un nouveau 1102
                self._en_pause = False
            with self._verrou:
                if generation == self._generation:
                    self._index = i
            suivi = SuiviArrivee(self.client, envoi, cible, self.tolerance)
            while not suivi.arrive(self.position()):
                if self._perime(generation):
                    return
                if time.monotonic() - envoi > self.delai_troncon:
                    self._finir(generation, echec=True)
                    return
                time.sleep(0.05)
        self._finir(generation, arrive=True, reste_m=0.0)
