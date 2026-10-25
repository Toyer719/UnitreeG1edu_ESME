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
