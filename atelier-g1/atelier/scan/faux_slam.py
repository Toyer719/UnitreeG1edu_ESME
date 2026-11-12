"""Faux service slam_operate, pour les tests et l'interface, sans robot.

Il répond aux mêmes commandes que le vrai service du G1 (1801, 1802, 1804, 1102, 1201, 1202,
1901), avec des JSON plausibles, et publie rt/slam_info (la position) et rt/slam_key_info
(is_arrived). Il vérifie le déroulé : pas de 1802 sans 1801, pas de 1804 sans carte
enregistrée, pas de 1102 sans 1804. Il tourne sur l'interface « lo » : rien ne sort du PC.

Deux façons de faire bouger le robot pour 1102 :
  - DeplacementInterne : un point qui glisse en ligne droite, sans simulateur ;
  - DeplacementGazebo : le robot proxy de Gazebo, piloté par /cmd_vel et suivi par /odom,
    qui s'arrête devant un obstacle vu dans /points (comme 1102 sur le vrai robot).

Lancement : g1-slam faux-service [--gazebo] [--relocalise] [--lieu L]
Les formats de réponse sont ceux supposés par slam_client.py (à vérifier sur le robot).
"""
import json
import math
import threading
import time

from atelier.scan import slam_client as sc

# Codes d'erreur du faux service, dans le champ errorCode de la réponse (à vérifier sur le robot :
# les vrais codes sont inconnus)
ERREUR_DEROULE = 1        # commande hors du bon déroulé (ex. 1802 sans 1801)
ERREUR_PARAMETRES = 2     # JSON illisible ou champ manquant
ERREUR_TROP_LOIN = 3      # cible de 1102 au-delà de la portée
ERREUR_CARTE = 4          # 1804 sur une carte inconnue


def _angle(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


# ---------------------------------------------------------------- façons de bouger

class DeplacementInterne:
    """Robot sur le papier : la pose est intégrée à partir des vitesses commandées.

    bloque (bool) : un obstacle imaginaire devant le robot, pour les tests.
    """

    def __init__(self, depart=(0.0, 0.0, 0.0)):
        self._pose = tuple(float(v) for v in depart)
        self.bloque = False
        self._verrou = threading.Lock()

    def position(self):
        with self._verrou:
            return self._pose

    def placer(self, pose):
        with self._verrou:
            self._pose = tuple(float(v) for v in pose)

    def commander(self, vx, vy, wz, dt):
        """vx, vy : vitesse dans le repère map (m/s) ; wz : rotation (rad/s) ; dt : durée (s)."""
        with self._verrou:
            x, y, t = self._pose
            self._pose = (x + vx * dt, y + vy * dt, _angle(t + wz * dt))

    def obstacle(self, direction, distance=None):
        return self.bloque

    def fermer(self):
        pass


class DeplacementGazebo:
    """Robot proxy de Gazebo : /cmd_vel (repère du robot), /odom et /points, par ROS 2.

    Un obstacle est un point de /points devant le robot, dans le sens de la marche, entre
    0,15 et 1,5 m du sol. Le LiDAR est à HAUTEUR_LIDAR au-dessus du sol (modèle g1_proxy).
    """

    HAUTEUR_LIDAR = 1.245      # m, comme le LiDAR du model.sdf de g1_proxy
    DISTANCE_ARRET = 0.75      # m, du centre du robot au bord de la zone surveillée
    DEMI_LARGEUR = 0.3         # m

    def __init__(self):
        import rclpy
        from geometry_msgs.msg import Twist
        from nav_msgs.msg import Odometry
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.qos import qos_profile_sensor_data
        from sensor_msgs.msg import PointCloud2

        self._Twist = Twist
        self._rclpy = rclpy
        if not rclpy.ok():
            rclpy.init()
        self._noeud = rclpy.create_node("faux_slam")
        self._cmd = self._noeud.create_publisher(Twist, "/cmd_vel", 10)
        self._noeud.create_subscription(Odometry, "/odom", self._odom, 10)
        self._noeud.create_subscription(PointCloud2, "/points", self._points, qos_profile_sensor_data)
        self._pose = None
        self._nuage = None
        self._arrets = 0              # consignes nulles déjà publiées d'affilée
        self._verrou = threading.Lock()
        self._executeur = SingleThreadedExecutor()
        self._executeur.add_node(self._noeud)
        self._fil = threading.Thread(target=self._tourner, daemon=True)
        self._fil.start()

    def _tourner(self):
        try:
            self._executeur.spin()
        except Exception:
            pass

    def _odom(self, msg):
        from atelier.lieu.conversions import quaternion_vers_cap
        p = msg.pose.pose
        with self._verrou:
            self._pose = (p.position.x, p.position.y, quaternion_vers_cap(p.orientation))

    def _points(self, msg):
        from atelier.scan.carte3d import points_du_nuage
        try:
            points = points_du_nuage(msg)
        except Exception:
            return
        with self._verrou:
            self._nuage = points

    def position(self):
        with self._verrou:
            return self._pose

    def placer(self, pose):
        pass    # la pose vient de /odom

    def commander(self, vx, vy, wz, dt):
        if not self._rclpy.ok():
            return          # ROS 2 s'arrête (Ctrl+C) : plus rien à publier
        # À l'arrêt, quelques consignes nulles suffisent (VelocityControl garde la dernière) :
        # on laisse ensuite /cmd_vel libre pour un autre programme (manette, Nav2)
        if vx == 0.0 and vy == 0.0 and wz == 0.0:
            self._arrets += 1
            if self._arrets > 5:
                return
        else:
            self._arrets = 0
        pose = self.position()
        msg = self._Twist()
        if pose is not None:
            c, s = math.cos(pose[2]), math.sin(pose[2])
            msg.linear.x = c * vx + s * vy        # repère map → repère du robot
            msg.linear.y = -s * vx + c * vy
            msg.angular.z = float(wz)
        self._cmd.publish(msg)

    def obstacle(self, direction, distance=None):
        """Vrai si un point de /points est devant le robot, dans le sens de la marche, avant
        la cible (distance : mètres restants jusqu'à elle)."""
        import numpy as np
        with self._verrou:
            nuage, pose = self._nuage, self._pose
        if nuage is None or pose is None or len(nuage) == 0:
            return False
        # Direction de la marche, dans le repère du LiDAR (tourné comme le robot)
        u = np.array([math.cos(direction - pose[2]), math.sin(direction - pose[2])])
        hauteur = nuage[:, 2] + self.HAUTEUR_LIDAR
        devant = nuage[:, :2] @ u
        cote = np.abs(nuage[:, 0] * u[1] - nuage[:, 1] * u[0])
        limite = self.DISTANCE_ARRET if distance is None else min(self.DISTANCE_ARRET, distance + 0.25)
        proche = ((hauteur > 0.15) & (hauteur < 1.5) & (devant > 0.0)
                  & (devant < limite) & (cote < self.DEMI_LARGEUR))
        return bool(proche.any())

    def fermer(self):
        try:
            self._cmd.publish(self._Twist())
            self._executeur.shutdown(timeout_sec=2.0)
            self._fil.join(timeout=2.0)
            self._noeud.destroy_node()
            self._rclpy.try_shutdown()
        except Exception:
            pass


# ---------------------------------------------------------------- le faux service

class FauxSlam:
    """Faux service slam_operate.

    depart       pose de départ (x, y, theta) du robot interne
    vitesse      m/s en ligne droite ; rotation : rad/s
    portee_max   m : 1102 refuse une cible plus loin (le vrai robot : moins de 8 à 10 m)
    publication_cle  « periodique » : slam_key_info à 2 Hz (is_arrived vrai ou faux) ;
                     « evenement » : un seul message, à l'arrivée
    delai_perime s : après un nouveau 1102, is_arrived reste vrai encore ce temps-là
                     (un vrai robot peut republier l'ancienne arrivée)
    relocalise   commencer déjà repéré sur la carte « carte » (comme après un 1804)
    deplacement  DeplacementInterne (par défaut) ou DeplacementGazebo
    """

    def __init__(self, depart=(0.0, 0.0, 0.0), vitesse=0.5, rotation=1.0, portee_max=10.0,
                 publication_cle="periodique", delai_perime=0.5, frequence=10.0,
                 relocalise=False, carte="faux.pcd", deplacement=None, bavard=False):
        self.vitesse = vitesse
        self.rotation = rotation
        self.portee_max = portee_max
        self.publication_cle = publication_cle
        self.delai_perime = delai_perime
        self.frequence = frequence
        self.bavard = bavard
        self.deplacement = deplacement or DeplacementInterne(depart)
        # Arrivée en position (m) et en orientation (rad) : pile sur la cible pour le robot
        # imaginaire, à 5 cm et 3° près pour le robot proxy de Gazebo
        interne = isinstance(self.deplacement, DeplacementInterne)
        self.tolerance = 0.001 if interne else 0.05
        self.tolerance_cap = 0.001 if interne else 0.05
        self._verrou = threading.RLock()
        self.journal = []               # [{api, parametres, reponse}], dans l'ordre des appels
        self._serveur = None
        self._fil = None
        self._arret = threading.Event()
        self.reinitialiser(depart, relocalise, carte)

    # ------------------------------------------------ état

    def reinitialiser(self, depart=None, relocalise=False, carte="faux.pcd", **options):
        """Remet le service à zéro (pour enchaîner les tests dans un même processus)."""
        with self._verrou:
            for nom, valeur in options.items():
                if not hasattr(self, nom):
                    raise AttributeError(f"option inconnue : {nom}")
                setattr(self, nom, valeur)
            if depart is not None:
                self.deplacement.placer(depart)
            if isinstance(self.deplacement, DeplacementInterne):
                self.deplacement.bloque = False
            self.mode = "relocalise" if relocalise else "repos"   # repos | scan | relocalise
            self.cartes = {sc.adresse_carte(carte)} if carte else set()
            self.carte = sc.adresse_carte(carte) if (relocalise and carte) else None
            self.cible = None
            self.en_pause = False
            self.arrive = False
            self.arrive_precedent = False   # arrivée de la tâche d'avant (republiée un moment)
            self.tache = 0                  # numéro du dernier 1102 accepté
            self.instant_tache = 0.0
            self.cle_publiee = 0            # dernière tâche dont l'arrivée a été publiée
            self.journal.clear()

    def bloquer(self, oui=True):
        """Pose (ou retire) un obstacle imaginaire devant le robot interne."""
        self.deplacement.bloque = oui

    def position(self):
        return self.deplacement.position()

    # ------------------------------------------------ réponses

    @staticmethod
    def _reponse(succes=True, code=0, info=""):
        return 0, json.dumps({"succeed": succes, "errorCode": code, "info": info})

    def _refus(self, code, info):
        return self._reponse(False, code, info)

    def _traiter(self, api, texte):
        """Appelé par le serveur du SDK pour chaque commande : renvoie (code RPC, texte JSON)."""
        try:
            parametres = json.loads(texte) if texte else {}
            donnees = parametres.get("data", {}) if isinstance(parametres, dict) else None
            if not isinstance(donnees, dict):
                raise ValueError("pas de champ data")
        except ValueError as e:
            resultat = self._refus(ERREUR_PARAMETRES, f"paramètres illisibles : {e}")
            parametres = texte
        else:
            with self._verrou:
                resultat = self._commande(api, donnees)
        with self._verrou:
            self.journal.append({"api": api, "parametres": parametres, "reponse": json.loads(resultat[1])})
        if self.bavard:
            print(f"[faux slam_operate] {api} ({sc.NOMS_API.get(api, '?')}) : {resultat[1]}", flush=True)
        return resultat

    def _commande(self, api, d):
        if api == sc.API_DEBUT_SCAN:
            if self.mode == "scan":
                return self._refus(ERREUR_DEROULE, "un scan est déjà en cours")
            if d.get("slam_type") not in ("indoor", "outdoor"):
                return self._refus(ERREUR_PARAMETRES, "slam_type doit valoir indoor ou outdoor")
            self.mode, self.cible, self.carte = "scan", None, None
            return self._reponse(info="cartographie commencée")

        if api == sc.API_FIN_SCAN:
            if self.mode != "scan":
                return self._refus(ERREUR_DEROULE, "aucun scan en cours : envoyez d'abord 1801")
            adresse = d.get("address")
            if not isinstance(adresse, str) or not adresse.endswith(".pcd"):
                return self._refus(ERREUR_PARAMETRES, "address doit être un chemin en .pcd")
            self.cartes.add(adresse)
            self.mode = "repos"
            return self._reponse(info=f"carte enregistrée : {adresse}")

        if api == sc.API_RELOCALISER:
            try:
                x, y = float(d["x"]), float(d["y"])
                q = (float(d["q_x"]), float(d["q_y"]), float(d["q_z"]), float(d["q_w"]))
                adresse = d["address"]
            except (KeyError, TypeError, ValueError):
                return self._refus(ERREUR_PARAMETRES, "il faut x, y, z, q_x, q_y, q_z, q_w et address")
            if adresse not in self.cartes:
                return self._refus(ERREUR_CARTE, f"carte inconnue : {adresse}")
            if self.mode == "scan":
                return self._refus(ERREUR_DEROULE, "un scan est en cours : terminez-le d'abord (1802)")
            from atelier.lieu.conversions import quaternion_vers_cap
            self.deplacement.placer((x, y, quaternion_vers_cap(q)))
            self.mode, self.carte, self.cible = "relocalise", adresse, None
            return self._reponse(info="robot repéré sur la carte")

        if api == sc.API_ALLER:
            if self.mode != "relocalise":
                return self._refus(ERREUR_DEROULE, "robot non repéré sur une carte : envoyez d'abord 1804")
            try:
                p = d["targetPose"]
                x, y = float(p["x"]), float(p["y"])
                q = (float(p["q_x"]), float(p["q_y"]), float(p["q_z"]), float(p["q_w"]))
            except (KeyError, TypeError, ValueError):
                return self._refus(ERREUR_PARAMETRES, "il faut targetPose {x, y, z, q_x, q_y, q_z, q_w}")
            pose = self.position()
            if pose is None:
                return self._refus(ERREUR_DEROULE, "position du robot inconnue")
            distance = math.hypot(x - pose[0], y - pose[1])
            if distance > self.portee_max:
                return self._refus(ERREUR_TROP_LOIN, f"cible à {distance:.1f} m, au-delà de {self.portee_max:.0f} m")
            from atelier.lieu.conversions import quaternion_vers_cap
            self.cible = (x, y, quaternion_vers_cap(q))
            self.en_pause = False
            self.arrive_precedent = self.arrive
            self.arrive = False
            self.tache += 1
            self.instant_tache = time.monotonic()
            return self._reponse(info="navigation commencée")

        if api == sc.API_PAUSE:
            self.en_pause = True
            return self._reponse(info="navigation en pause")

        if api == sc.API_REPRENDRE:
            self.en_pause = False
            return self._reponse(info="navigation reprise")

        if api == sc.API_ARRETER:
            self.mode, self.cible, self.en_pause, self.carte = "repos", None, False, None
            return self._reponse(info="service arrêté")

        return 3203, ""

    # ------------------------------------------------ boucle de mouvement et publications

    def demarrer(self):
        """Ouvre le service (DDS doit être ouvert : slam_client.initialiser_dds) et la boucle."""
        from unitree_sdk2py.core.channel import ChannelPublisher
        from unitree_sdk2py.idl.std_msgs.msg.dds_ import String_
        from unitree_sdk2py.rpc.server import Server

        self._String = String_
        self._pub_info = ChannelPublisher(sc.SUJET_INFO, String_)
        self._pub_info.Init()
        self._pub_cle = ChannelPublisher(sc.SUJET_INFO_CLE, String_)
        self._pub_cle.Init()

        serveur = Server(sc.NOM_SERVICE)
        serveur._SetApiVersion(sc.VERSION_API)
        for api in sc.NOMS_API:
            serveur._RegistHandler(api, lambda texte, api=api: self._traiter(api, texte), False)
        serveur.Start(False)
        self._serveur = serveur
        self._arret.clear()
        self._fil = threading.Thread(target=self._boucle, name="faux_slam", daemon=True)
        self._fil.start()
        return self

    def fermer(self):
        """Arrête la boucle et le robot. Le serveur du SDK ne se ferme pas : quittez le programme."""
        self._arret.set()
        if self._fil is not None:
            self._fil.join(timeout=2)
        self.deplacement.commander(0.0, 0.0, 0.0, 0.0)
        self.deplacement.fermer()

    def _publier(self, publication, donnees):
        try:
            publication.Write(self._String(data=json.dumps(donnees)))
        except Exception:
            pass

    def _boucle(self):
        pas = 0.05
        prochaine_info = prochaine_cle = 0.0
        precedent = time.monotonic()
        while not self._arret.wait(pas):
            maintenant = time.monotonic()
            dt, precedent = maintenant - precedent, maintenant
            with self._verrou:
                self._avancer(dt)
                pose = self.position()
                if maintenant >= prochaine_info and self.mode != "repos" and pose is not None:
                    prochaine_info = maintenant + 1.0 / self.frequence
                    self._publier(self._pub_info, {
                        "type": "pos_info", "errorCode": 0, "info": "faux service",
                        "data": {"currentPose": sc.pose_unitree(*pose)}})
                if self.tache and maintenant >= prochaine_cle:
                    prochaine_cle = self._publier_cle(maintenant, prochaine_cle)

    def _publier_cle(self, maintenant, prochaine):
        """Publie slam_key_info ; renvoie l'instant de la prochaine publication."""
        message = {"type": "task_result", "errorCode": 0, "info": "faux service",
                   "task_result": {"is_arrived": self.arrive, "task": self.tache}}
        if self.publication_cle == "evenement":
            if self.arrive and self.cle_publiee != self.tache:
                self.cle_publiee = self.tache
                self._publier(self._pub_cle, message)
            return maintenant
        # Périodique : juste après un nouveau 1102, on republie encore l'ancienne arrivée
        if not self.arrive and maintenant - self.instant_tache < self.delai_perime:
            message["task_result"]["is_arrived"] = self.arrive_precedent
            message["task_result"]["task"] = self.tache - 1
        self._publier(self._pub_cle, message)
        return maintenant + 0.5

    def _avancer(self, dt):
        """Une étape du mouvement vers la cible de 1102 : ligne droite, puis rotation sur place."""
        pose = self.position()
        if self.cible is None or self.en_pause or self.mode != "relocalise" or pose is None:
            self.deplacement.commander(0.0, 0.0, 0.0, dt)
            return
        x, y, t = pose
        cx, cy, ct = self.cible
        dx, dy = cx - x, cy - y
        distance = math.hypot(dx, dy)
        if distance > self.tolerance:
            direction = math.atan2(dy, dx)
            if self.deplacement.obstacle(direction, distance):
                self.deplacement.commander(0.0, 0.0, 0.0, dt)      # s'arrête, sans contourner
                return
            if isinstance(self.deplacement, DeplacementInterne):
                v = min(self.vitesse, distance / max(dt, 1e-3))      # tombe pile sur la cible
            else:
                v = min(self.vitesse, max(1.5 * distance, 0.08))      # ralentit à l'approche
            self.deplacement.commander(v * dx / distance, v * dy / distance, 0.0, dt)
            return
        ecart = _angle(ct - t)
        if abs(ecart) > self.tolerance_cap:
            if isinstance(self.deplacement, DeplacementInterne):
                w = math.copysign(min(self.rotation, abs(ecart) / max(dt, 1e-3)), ecart)
            else:
                w = math.copysign(min(self.rotation, max(1.5 * abs(ecart), 0.15)), ecart)
            self.deplacement.commander(0.0, 0.0, w, dt)
            return
        self.deplacement.commander(0.0, 0.0, 0.0, dt)
        self.cible = None
        self.arrive = True


# ---------------------------------------------------------------- pour les tests

_PARTAGE = None


def domaine_essai():
    """Domaine DDS propre à ce processus de test, pour ne pas croiser un autre test en cours."""
    import os
    return 150 + os.getpid() % 80


def faux_partage(**options):
    """Un seul faux service par processus (le serveur du SDK ne se ferme pas) : le crée au
    premier appel, puis le remet à zéro. Ouvre DDS sur « lo » si ce n'est pas déjà fait."""
    global _PARTAGE
    if sc.dds_ouvert() is None:
        sc.initialiser_dds(sc.INTERFACE_FAUX, domaine_essai())
    elif sc.dds_ouvert()[1] != sc.INTERFACE_FAUX:
        raise RuntimeError("DDS est ouvert sur une autre interface que lo : test impossible")
    depart = options.pop("depart", (0.0, 0.0, 0.0))
    relocalise = options.pop("relocalise", True)
    carte = options.pop("carte", "faux.pcd")
    if _PARTAGE is None:
        _PARTAGE = FauxSlam(depart=depart, relocalise=relocalise, carte=carte, **options).demarrer()
    else:
        defauts = dict(vitesse=0.5, rotation=1.0, portee_max=10.0, publication_cle="periodique",
                       delai_perime=0.5, frequence=10.0)
        defauts.update(options)
        _PARTAGE.reinitialiser(depart, relocalise, carte, **defauts)
    return _PARTAGE


# ---------------------------------------------------------------- répétition du niveau 2 (section 10.6 du plan)
#
# g1-slam faux-service --jumeau --lieu L --etage E : le robot est le robot proxy de Gazebo, commandé
# par le faux G1 (paquet g1_jumeau) et non par ce service. Sa vérité terrain est /g1_jumeau/odom
# (repère du monde Gazebo = map de l'étage) et son nuage /g1_jumeau/points (repère lidar). En plus du
# serveur du SDK sur lo (pour g1-slam --faux), un frontal ROS 2 répond sur /api/slam_operate/* comme le
# vrai robot, et publie la relocalisation une fois repéré.

ERREUR_RELOCALISATION = 5           # 1804 : le robot n'est pas à la position donnée
FREQUENCE_RELOCALISATION = 10.0     # Hz, /unitree/slam_relocation/odom et /points
COVARIANCE_XY = 0.0004              # m², covariance de la relocalisation publiée (x et y)
COVARIANCE_LACET = 0.0001           # rad²
POSE_LIDAR = (-0.004, 0.0, 1.245)   # LiDAR dans base_link (model.sdf de g1_proxy)
SUJETS_JUMEAU = {"requete": "/api/slam_operate/request", "reponse": "/api/slam_operate/response",
                 "verite": "/g1_jumeau/odom", "nuage": "/g1_jumeau/points",
                 "relocalisation": "/unitree/slam_relocation/odom", "points": "/unitree/slam_relocation/points",
                 "info": "/slam_info", "panne": "/faux_slam/panne",
                 "carte_globale": "/unitree/slam_relocation/global_map"}
PAS_CARTE_GLOBALE = 0.1             # m : points de la fausse carte globale, sur les murs et objets du monde


class DeplacementJumeau:
    """Robot proxy commandé par le faux G1 : ce service ne le fait jamais bouger.

    position() est la vérité terrain (/g1_jumeau/odom, repère map) exprimée dans le repère d'Unitree
    (atelier.lieu.carte_vers_unitree avec le repère de l'étage) ; placer() et commander() ne font rien.
    """

    def __init__(self, repere):
        self.repere = tuple(float(v) for v in repere)
        self.bloque = False
        self._verite = None          # (horodatage en s, pose map)
        self._verrou = threading.Lock()

    def noter(self, horodatage, pose_carte):
        with self._verrou:
            self._verite = (horodatage, tuple(float(v) for v in pose_carte))

    def verite(self):
        """(horodatage, pose dans map) de la dernière vérité terrain, ou None."""
        with self._verrou:
            return self._verite

    def position(self):
        from atelier.lieu import carte_vers_unitree
        verite = self.verite()
        return None if verite is None else carte_vers_unitree(verite[1], self.repere)

    def placer(self, pose):
        pass

    def commander(self, vx, vy, wz, dt):
        pass                         # jamais de vitesse : la marche passe par le pont et le faux G1

    def obstacle(self, direction, distance=None):
        return False

    def fermer(self):
        pass


class FauxSlamJumeau(FauxSlam):
    """Faux slam_operate de la répétition du niveau 2.

    1804 : une address inconnue donne ERREUR_CARTE ; une pose initiale, ramenée dans map, à plus de
    ECART_MAX_M ou ECART_MAX_RAD de la vérité donne ERREUR_RELOCALISATION (et plus de relocalisation
    publiée) ; sinon le robot est repéré, sans être déplacé. 1102 est refusé (ERREUR_DEROULE).
    Cartes connues : carte_unitree du lieu et CARTE_REPETITION.
    """

    def __init__(self, repere, cartes, **options):
        self.repere = tuple(float(v) for v in repere)
        self.cartes_connues = {sc.adresse_carte(c) for c in cartes if c}
        self.sur_relocalise = None      # appelée après chaque 1804 réussi (frontal ROS 2 : la carte globale)
        super().__init__(relocalise=False, carte=None, deplacement=DeplacementJumeau(self.repere), **options)

    def reinitialiser(self, depart=None, relocalise=False, carte=None, **options):
        super().reinitialiser(depart, relocalise, carte, **options)
        with self._verrou:
            self.cartes |= getattr(self, "cartes_connues", set())

    def _commande(self, api, d):
        if api == sc.API_ALLER:
            return self._refus(ERREUR_DEROULE, "pas de 1102 en répétition du niveau 2 : la navigation passe par Nav2")
        if api != sc.API_RELOCALISER:
            return super()._commande(api, d)
        from atelier.lieu import ECART_MAX_M, ECART_MAX_RAD, quaternion_vers_cap, unitree_vers_carte
        try:
            x, y = float(d["x"]), float(d["y"])
            q = (float(d["q_x"]), float(d["q_y"]), float(d["q_z"]), float(d["q_w"]))
            adresse = d["address"]
            cap = quaternion_vers_cap(q)
        except (KeyError, TypeError, ValueError):
            return self._refus(ERREUR_PARAMETRES, "il faut x, y, z, q_x, q_y, q_z, q_w et address")
        if adresse not in self.cartes:
            return self._refus(ERREUR_CARTE, f"carte inconnue : {adresse}")
        if self.mode == "scan":
            return self._refus(ERREUR_DEROULE, "un scan est en cours : terminez-le d'abord (1802)")
        verite = self.deplacement.verite()
        if verite is None:
            self.mode, self.carte = "repos", None
            return self._refus(ERREUR_DEROULE, "position du robot inconnue : /g1_jumeau/odom n'est pas publié "
                                               "(faux G1 lancé ?)")
        annoncee = unitree_vers_carte((x, y, cap), self.repere)
        distance = math.hypot(annoncee[0] - verite[1][0], annoncee[1] - verite[1][1])
        ecart_cap = abs(_angle(annoncee[2] - verite[1][2]))
        if distance > ECART_MAX_M or ecart_cap > ECART_MAX_RAD:
            self.mode, self.carte, self.cible = "repos", None, None
            return self._refus(ERREUR_RELOCALISATION, "relocalisation impossible : le robot n'est pas à la position "
                                                      f"donnée (à {distance:.1f} m et {math.degrees(ecart_cap):.0f}°)")
        self.mode, self.carte, self.cible = "relocalise", adresse, None
        if self.sur_relocalise is not None:          # vague 5 : la carte globale, une fois par 1804 réussi
            try:
                self.sur_relocalise()
            except Exception as e:      # noqa: BLE001 : le repérage reste réussi
                print(f"[faux slam_operate] carte globale non publiée : {e}", flush=True)
        return self._reponse(info="robot repéré sur la carte")


def _secondes(stamp):
    return stamp.sec + stamp.nanosec * 1e-9


def _nuage_xyz(points, repere, stamp):
    """Tableau (N, 3) → sensor_msgs/PointCloud2 (x, y, z en float32)."""
    import numpy as np
    from sensor_msgs.msg import PointCloud2, PointField
    points = np.ascontiguousarray(np.asarray(points, dtype=np.float32).reshape(-1, 3))
    msg = PointCloud2()
    msg.header.frame_id, msg.header.stamp = repere, stamp
    msg.height, msg.width = 1, len(points)
    msg.fields = [PointField(name=n, offset=4 * i, datatype=PointField.FLOAT32, count=1) for i, n in enumerate("xyz")]
    msg.is_bigendian, msg.is_dense = False, True
    msg.point_step, msg.row_step = 12, 12 * len(points)
    msg.data = points.tobytes()
    return msg


class FrontalRos:
    """Frontal ROS 2 du faux service, comme le vrai robot vu depuis le Jetson.

      /api/slam_operate/request  (unitree_api/Request)  → faux._traiter(api_id, parameter)
      /api/slam_operate/response (unitree_api/Response) identity recopiée, status.code, data (JSON)
      /g1_jumeau/odom, /g1_jumeau/points                vérité terrain et nuage du robot proxy
      /unitree/slam_relocation/odom   une fois repéré, à 10 Hz : frame map, child body, pose de la
                                      vérité dans le repère d'Unitree (z 1,245), covariance diagonale
      /unitree/slam_relocation/points le dernier nuage, placé dans le repère d'Unitree, frame map
      /slam_info                      pos_info (repère d'Unitree)
      /faux_slam/panne                « aucune » ou « muet » (plus de relocalisation : essais de perte)
      /unitree/slam_relocation/global_map  vague 5 (section 12.5 du plan) : la carte globale, publiée une
                                      fois après chaque 1804 réussi (QoS fiable, transient_local), comme
                                      le vrai robot d'après sa documentation ; carte_globale : ses points
                                      (repère d'Unitree), tirés du monde de l'étage (lancer_jumeau)
    bruit : écart-type (m) ajouté à la position publiée (et la moitié, en radians, au cap) ;
    retard : secondes entre la mesure et la publication (horodatage : celui de Gazebo).
    """

    def __init__(self, faux, bruit=0.0, retard=0.0, frequence=FREQUENCE_RELOCALISATION, graine=None,
                 bavard=True, carte_globale=None):
        import random
        from collections import deque

        import rclpy
        from nav_msgs.msg import Odometry
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy, qos_profile_sensor_data
        from rclpy.signals import SignalHandlerOptions
        from sensor_msgs.msg import PointCloud2
        from std_msgs.msg import String
        from unitree_api.msg import Request, Response

        self.faux = faux
        self.repere = faux.repere
        self.bruit = max(0.0, float(bruit))
        self.retard = max(0.0, float(retard))
        self.bavard = bavard
        self.panne = "aucune"
        self.publiees = 0               # relocalisations publiées
        self.carte_globale = carte_globale
        self.cartes_publiees = 0        # cartes globales publiées (une par 1804 réussi)
        self._hasard = random.Random(graine)
        self._verites = deque(maxlen=200)       # (horodatage s, pose map) : vérité de chaque instant
        self._nuage = None                      # dernier PointCloud2 de /g1_jumeau/points
        self._nuage_publie = None
        self._file = deque()                    # (instant de publication, publieur, message)
        self._verrou = threading.Lock()
        self._Odometry, self._String, self._Response = Odometry, String, Response

        self._rclpy = rclpy
        self._contexte = rclpy.Context()
        rclpy.init(context=self._contexte, signal_handler_options=SignalHandlerOptions.NO)
        self._noeud = rclpy.create_node("faux_slam", context=self._contexte)
        fiable = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.VOLATILE)
        n = self._noeud
        n.create_subscription(Request, SUJETS_JUMEAU["requete"], self._sur_requete, fiable)
        n.create_subscription(Odometry, SUJETS_JUMEAU["verite"], self._sur_verite, qos_profile_sensor_data)
        n.create_subscription(PointCloud2, SUJETS_JUMEAU["nuage"], self._sur_nuage, qos_profile_sensor_data)
        n.create_subscription(String, SUJETS_JUMEAU["panne"], self._sur_panne, fiable)
        self._pub_reponse = n.create_publisher(Response, SUJETS_JUMEAU["reponse"], fiable)
        self._pub_reloc = n.create_publisher(Odometry, SUJETS_JUMEAU["relocalisation"], 10)
        self._pub_points = n.create_publisher(PointCloud2, SUJETS_JUMEAU["points"], qos_profile_sensor_data)
        self._pub_info = n.create_publisher(String, SUJETS_JUMEAU["info"], 10)
        self._pub_carte = n.create_publisher(PointCloud2, SUJETS_JUMEAU["carte_globale"], QoSProfile(
            depth=1, reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.TRANSIENT_LOCAL))
        n.create_timer(1.0 / frequence, self._publier)
        n.create_timer(0.01, self._vider_file)
        self._executeur = SingleThreadedExecutor(context=self._contexte)
        self._executeur.add_node(n)
        self._fil = threading.Thread(target=self._tourner, name="frontal ROS 2 du faux slam", daemon=True)
        self._fil.start()
        if carte_globale is not None:                # après chaque 1804 réussi, par ROS 2 ou par le SDK
            faux.sur_relocalise = self._publier_carte_globale

    def _tourner(self):
        try:
            self._executeur.spin()
        except Exception:      # noqa: BLE001 : arrêt du contexte
            pass

    def _dire(self, texte):
        if self.bavard:
            print(f"[faux slam_operate] {texte}", flush=True)

    # ------------------------------------------------ réception

    def _sur_requete(self, msg):
        api = int(msg.header.identity.api_id)
        self._dire(f"requête ROS 2 {api} ({sc.NOMS_API.get(api, '?')}), id {msg.header.identity.id} : {msg.parameter}")
        code, texte = self.faux._traiter(api, msg.parameter)
        r = self._Response()
        r.header.identity.id = msg.header.identity.id
        r.header.identity.api_id = msg.header.identity.api_id
        r.header.status.code = int(code)
        r.data = texte or ""
        self._pub_reponse.publish(r)

    def _publier_carte_globale(self):
        """La carte globale, une fois après un 1804 réussi (repère d'Unitree, frame map)."""
        stamp = self._noeud.get_clock().now().to_msg()
        self._pub_carte.publish(_nuage_xyz(self.carte_globale, "map", stamp))
        self.cartes_publiees += 1
        self._dire(f"carte globale publiée sur {SUJETS_JUMEAU['carte_globale']} ({len(self.carte_globale)} points)")

    def _sur_verite(self, msg):
        from atelier.lieu import quaternion_vers_cap
        p = msg.pose.pose
        pose = (p.position.x, p.position.y, quaternion_vers_cap(p.orientation))
        with self._verrou:
            self._verites.append((_secondes(msg.header.stamp), pose, msg.header.stamp))
        self.faux.deplacement.noter(_secondes(msg.header.stamp), pose)

    def _sur_nuage(self, msg):
        with self._verrou:
            self._nuage = msg

    def _sur_panne(self, msg):
        panne = msg.data.strip()
        if panne in ("aucune", "muet"):
            self.panne = panne
            self._dire(f"panne : {panne}")

    # ------------------------------------------------ publication

    def _verite_a(self, instant):
        """Vérité terrain la plus proche de l'instant (s) : (horodatage, pose, stamp), ou None."""
        with self._verrou:
            if not self._verites:
                return None
            return min(self._verites, key=lambda v: abs(v[0] - instant))

    def _bruiter(self, pose):
        if self.bruit <= 0.0:
            return pose
        g = self._hasard.gauss
        return (pose[0] + g(0.0, self.bruit), pose[1] + g(0.0, self.bruit), _angle(pose[2] + g(0.0, self.bruit / 2)))

    def _mettre_en_file(self, publieur, msg):
        with self._verrou:
            self._file.append((time.monotonic() + self.retard, publieur, msg))

    def _vider_file(self):
        maintenant = time.monotonic()
        while True:
            with self._verrou:
                if not self._file or self._file[0][0] > maintenant:
                    return
                _, publieur, msg = self._file.popleft()
            publieur.publish(msg)

    def _publier(self):
        """10 Hz : relocalisation, nuage et slam_info, seulement une fois repéré (et sans panne)."""
        import numpy as np
        from atelier.lieu import carte_vers_unitree, cap_vers_quaternion
        if self.faux.mode != "relocalise" or self.panne == "muet":
            return
        with self._verrou:
            derniere = self._verites[-1] if self._verites else None
            nuage = self._nuage
        if derniere is None:
            return
        _, pose_carte, stamp = derniere
        bruitee = self._bruiter(pose_carte)
        decalage = (bruitee[0] - pose_carte[0], bruitee[1] - pose_carte[1], _angle(bruitee[2] - pose_carte[2]))
        u = carte_vers_unitree(bruitee, self.repere)
        m = self._Odometry()
        m.header.stamp, m.header.frame_id, m.child_frame_id = stamp, "map", "body"
        m.pose.pose.position.x, m.pose.pose.position.y, m.pose.pose.position.z = u[0], u[1], POSE_LIDAR[2]
        q = cap_vers_quaternion(u[2])
        o = m.pose.pose.orientation
        o.x, o.y, o.z, o.w = q
        covariance = [0.0] * 36
        covariance[0] = covariance[7] = max(COVARIANCE_XY, self.bruit ** 2)
        covariance[35] = max(COVARIANCE_LACET, (self.bruit / 2) ** 2)
        m.pose.covariance = covariance
        self._mettre_en_file(self._pub_reloc, m)
        self.publiees += 1
        info = {"type": "pos_info", "errorCode": 0, "info": "faux service (répétition)",
                "data": {"currentPose": sc.pose_unitree(*u)}}
        self._mettre_en_file(self._pub_info, self._String(data=json.dumps(info)))
        if nuage is not None and nuage is not self._nuage_publie:
            self._nuage_publie = nuage
            verite = self._verite_a(_secondes(nuage.header.stamp))
            if verite is None:
                return
            from atelier.scan.carte3d import points_du_nuage
            try:
                points = points_du_nuage(nuage)
            except Exception:      # noqa: BLE001 : nuage sans x, y, z
                return
            # même petit décalage que la relocalisation : le nuage est placé par la pose estimée
            p = verite[1]
            estimee = (p[0] + decalage[0], p[1] + decalage[1], p[2] + decalage[2])
            pose_u = carte_vers_unitree(estimee, self.repere)
            c, s = math.cos(pose_u[2]), math.sin(pose_u[2])
            x = points[:, 0] + POSE_LIDAR[0]
            y = points[:, 1] + POSE_LIDAR[1]
            monde = np.column_stack([pose_u[0] + c * x - s * y, pose_u[1] + s * x + c * y, points[:, 2] + POSE_LIDAR[2]])
            self._mettre_en_file(self._pub_points, _nuage_xyz(monde, "map", nuage.header.stamp))

    def fermer(self):
        try:
            self._executeur.shutdown(timeout_sec=2.0)
            self._fil.join(timeout=2.0)
            self._noeud.destroy_node()
            self._rclpy.try_shutdown(context=self._contexte)
        except Exception:      # noqa: BLE001
            pass


def lancer_jumeau(lieu, etage, bruit=0.0, retard=0.0, sdk=True, bavard=True):
    """Faux service de la répétition du niveau 2 : FauxSlamJumeau, serveur du SDK sur lo (si possible),
    et frontal ROS 2. Renvoie (faux, frontal) ; à fermer avec fermer_jumeau."""
    from atelier.lieu import CARTE_REPETITION, charger_fiche, repere_unitree
    repere = repere_unitree(lieu, etage)
    repere = (repere.x, repere.y, repere.theta)
    cartes = [charger_fiche(lieu).carte_unitree, CARTE_REPETITION]
    carte_globale = carte_globale_du_monde(lieu, etage, repere)
    faux = FauxSlamJumeau(repere, cartes, bavard=bavard)
    if sdk:
        try:
            interface, domaine = sc.connexion(True)
            sc.initialiser_dds(interface, domaine)
            faux.demarrer()
        except Exception as e:      # noqa: BLE001 : le frontal ROS 2 suffit à la répétition
            print(f"[faux slam_operate] serveur du SDK indisponible ({e}) : seul le frontal ROS 2 répond", flush=True)
    frontal = FrontalRos(faux, bruit=bruit, retard=retard, bavard=bavard, carte_globale=carte_globale)
    return faux, frontal


def carte_globale_du_monde(lieu, etage, repere, pas=PAS_CARTE_GLOBALE):
    """Fausse carte globale d'Unitree, dans le repère d'Unitree (origine au LiDAR, comme le vrai : sol à
    −1,245 m) : le nuage de l'étage s'il a été scanné (cartes/<etage>.nuage, réduit à une grille de « pas »),
    sinon les murs et objets du monde de l'étage (et son sol), échantillonnés tous les « pas » mètres.
    None si l'étage n'a ni nuage ni monde."""
    from atelier.lieu import ErreurLieu, charger_monde, chemin_monde, chemin_nuage, fichiers_nuage, lire_nuage
    from atelier.scan.affichage import nuage_du_monde, reduire_grille
    from atelier.scan.carte_unitree import vers_unitree
    points = None
    nuage = chemin_nuage(lieu, etage)
    if all(f.is_file() for f in fichiers_nuage(nuage)):
        try:
            points = reduire_grille(lire_nuage(nuage)[0].astype(float), pas)
        except ErreurLieu:
            points = None
    if points is None and chemin_monde(lieu, etage).is_file():
        try:
            points = nuage_du_monde(charger_monde(lieu, etage), pas=pas, sol_pas=4 * pas)
        except ErreurLieu:
            points = None
    if points is None or not len(points):
        return None
    unitree = vers_unitree(points, repere)
    unitree[:, 2] -= POSE_LIDAR[2]
    return unitree


def fermer_jumeau(faux, frontal):
    frontal.fermer()
    faux._arret.set()
    if faux._fil is not None:
        faux._fil.join(timeout=2)
