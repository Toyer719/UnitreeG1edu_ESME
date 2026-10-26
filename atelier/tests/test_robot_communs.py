"""Outils communs aux tests du repérage et du mode robot (agent Repérage, vague 3).

Pas de test ici : seulement des outils, importés par les fichiers test_robot_*.py.

  FauxRobot     robot sans Gazebo, comme le faux G1 de la répétition : vérité terrain
                /g1_jumeau/odom (repère map, 50 Hz), odométrie locale qui dérive
                /state_estimator/odom_pelvis (2 % et 0,01 rad par mètre, origine au départ), et
                nuage /g1_jumeau/points (repère lidar, 10 Hz) d'un mur connu du repère map
  Ecoute        nœud de test : /reperage/etat, TF (map → base_link, map → odom), /points remis
                dans map, requêtes /api/slam_operate/request
  lancer(...)   un programme dans son groupe de processus, journal dans un fichier
  arreter(p)    SIGINT au groupe, puis SIGTERM et SIGKILL
Domaine DDS : $ROS_DOMAIN_ID, 63 par défaut (agent Repérage). Il faut ROS 2 (env.sh) et les
messages unitree_api ; sinon les tests qui s'en servent sont sautés.
"""
import json
import math
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np

import atelier

RACINE = atelier.RACINE
G1_NAV = RACINE / "ws" / "src" / "g1_nav"
DOMAINE = int(os.environ.get("ROS_DOMAIN_ID") or 63)
POSE_LIDAR = (-0.004, 0.0, 1.245)
DERIVE_ECHELLE = 0.02
DERIVE_LACET_PAR_M = 0.01


def environnement(**autres):
    """Environnement des programmes lancés : domaine du test, PYTHONPATH vers les sources."""
    env = dict(os.environ, ROS_DOMAIN_ID=str(DOMAINE), PYTHONUNBUFFERED="1", G1_SLAM_FAUX="1",
               ROS_LOCALHOST_ONLY="0")
    env["PYTHONPATH"] = os.pathsep.join([str(RACINE), str(G1_NAV), env.get("PYTHONPATH", "")])
    env.update({k: str(v) for k, v in autres.items()})
    return env


def lancer(arguments, journal, **env):
    """Lance un programme dans son propre groupe de processus, sortie dans le fichier journal."""
    f = open(journal, "w", encoding="utf-8")
    return subprocess.Popen([str(a) for a in arguments], stdout=f, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, env=environnement(**env), start_new_session=True)


def arreter(p, attente=10.0):
    """Arrête le groupe de processus de p : SIGINT, puis SIGTERM, puis SIGKILL. Renvoie le code."""
    for sig, delai in ((signal.SIGINT, attente), (signal.SIGTERM, 5.0), (signal.SIGKILL, 5.0)):
        try:
            os.killpg(p.pid, sig)
        except ProcessLookupError:
            break
        try:
            p.wait(timeout=delai)
            break
        except subprocess.TimeoutExpired:
            continue
    return p.poll()


def relais(lieu, journal, repere=(2.5, 10.0, 0.0), carte="repetition.pcd", **parametres):
    """Lance odom_vers_tf (sources de g1_nav) avec ses paramètres ROS."""
    arguments = [sys.executable, "-m", "g1_nav.odom_vers_tf", "--ros-args",
                 "-p", f"repere_unitree:=[{repere[0]:.6f},{repere[1]:.6f},{repere[2]:.6f}]",
                 "-p", f"carte:={carte}", "-p", f"lieu:={lieu}", "-p", "etage:=rdc"]
    for nom, valeur in parametres.items():
        arguments += ["-p", f"{nom}:={valeur}"]
    return lancer(arguments, journal)


def faux_service(lieu, journal, *options):
    """Lance g1-slam faux-service --jumeau (module de commande, comme bin/g1-slam)."""
    return lancer([sys.executable, "-m", "atelier.scan.commande", "slam", "faux-service", "--jumeau",
                   "--lieu", lieu, "--etage", "rdc", *options], journal)


def composer(a, b):
    c, s = math.cos(a[2]), math.sin(a[2])
    return (a[0] + c * b[0] - s * b[1], a[1] + s * b[0] + c * b[1],
            (a[2] + b[2] + math.pi) % (2 * math.pi) - math.pi)


def mur_connu(x=6.0, y0=8.0, y1=12.0):
    """Points d'un mur vertical du repère map, de x = 6 m, entre y0 et y1, de 0,3 à 2 m de haut."""
    ys, zs = np.meshgrid(np.arange(y0, y1, 0.1), np.arange(0.3, 2.0, 0.2))
    return np.column_stack([np.full(ys.size, x), ys.ravel(), zs.ravel()])


class _Noeud:
    """Nœud rclpy dans son propre contexte, tourné par un fil de fond."""

    def __init__(self, nom):
        import rclpy
        from rclpy.executors import SingleThreadedExecutor
        self.rclpy = rclpy
        self.contexte = rclpy.Context()
        rclpy.init(context=self.contexte, domain_id=DOMAINE)
        self.noeud = rclpy.create_node(nom, context=self.contexte)
        self.executeur = SingleThreadedExecutor(context=self.contexte)
        self.executeur.add_node(self.noeud)
        self._fin = threading.Event()
        self._fil = threading.Thread(target=self._tourner, daemon=True)

    def _tourner(self):
        while not self._fin.is_set() and self.contexte.ok():
            try:
                self.executeur.spin_once(timeout_sec=0.05)
            except Exception:      # noqa: BLE001 : arrêt en cours
                break

    def fermer(self):
        self._fin.set()
        self._fil.join(timeout=3.0)
        self.executeur.shutdown()
        self.noeud.destroy_node()
        self.rclpy.try_shutdown(context=self.contexte)


class FauxRobot(_Noeud):
    """Robot sans Gazebo, publié comme le faux G1 de la répétition (voir l'en-tête du module)."""

    def __init__(self, depart=(2.5, 10.0, 0.0), mur=None):
        super().__init__("faux_robot_test")
        from nav_msgs.msg import Odometry
        from rclpy.qos import qos_profile_sensor_data
        from sensor_msgs.msg import PointCloud2
        self.Odometry = Odometry
        self.pub_verite = self.noeud.create_publisher(Odometry, "/g1_jumeau/odom", qos_profile_sensor_data)
        self.pub_odom = self.noeud.create_publisher(Odometry, "/state_estimator/odom_pelvis",
                                                    qos_profile_sensor_data)
        self.pub_points = self.noeud.create_publisher(PointCloud2, "/g1_jumeau/points", qos_profile_sensor_data)
        self.mur = mur_connu() if mur is None else mur
        self._verrou = threading.Lock()
        self._verite = tuple(float(v) for v in depart)
        self._odom = (0.0, 0.0, 0.0)       # origine : la pose au lancement
        self._vitesse = (0.0, 0.0, 0.0)
        self.muet = False
        self._pas = 0
        self._precedent = time.monotonic()
        self.noeud.create_timer(0.02, self._avancer)
        # base_link → lidar, comme robot_state_publisher de g1_sim
        import tf2_ros
        from geometry_msgs.msg import TransformStamped
        self.statique = tf2_ros.StaticTransformBroadcaster(self.noeud)
        t = TransformStamped()
        t.header.stamp = self.noeud.get_clock().now().to_msg()
        t.header.frame_id, t.child_frame_id = "base_link", "lidar"
        t.transform.translation.x, t.transform.translation.y, t.transform.translation.z = POSE_LIDAR
        t.transform.rotation.w = 1.0
        self.statique.sendTransform(t)
        self._fil.start()

    def commander(self, vx=0.0, vy=0.0, wz=0.0):
        with self._verrou:
            self._vitesse = (float(vx), float(vy), float(wz))

    def verite(self):
        with self._verrou:
            return self._verite

    def odometrie(self):
        with self._verrou:
            return self._odom

    def _avancer(self):
        from atelier.scan.faux_slam import _nuage_xyz
        maintenant = time.monotonic()
        dt, self._precedent = maintenant - self._precedent, maintenant
        with self._verrou:
            vx, vy, wz = self._vitesse
            dx, dy, dt_cap = vx * dt, vy * dt, wz * dt
            self._verite = composer(self._verite, (dx, dy, dt_cap))
            d = math.hypot(dx, dy)
            # dérive du faux G1 : 2 % de trop, et 0,01 rad de lacet par mètre parcouru
            self._odom = composer(self._odom, (dx * (1 + DERIVE_ECHELLE), dy * (1 + DERIVE_ECHELLE),
                                               dt_cap + DERIVE_LACET_PAR_M * d))
            verite, odom = self._verite, self._odom
        stamp = self.noeud.get_clock().now().to_msg()
        for publieur, pose, repere, enfant, z in ((self.pub_verite, verite, "map", "base_link", 0.0),
                                                  (self.pub_odom, odom, "odom", "pelvis", 0.75)):
            m = self.Odometry()
            m.header.stamp, m.header.frame_id, m.child_frame_id = stamp, repere, enfant
            m.pose.pose.position.x, m.pose.pose.position.y, m.pose.pose.position.z = pose[0], pose[1], z
            m.pose.pose.orientation.z, m.pose.pose.orientation.w = math.sin(pose[2] / 2), math.cos(pose[2] / 2)
            m.twist.twist.linear.x, m.twist.twist.angular.z = vx, wz
            publieur.publish(m)
        self._pas += 1
        if self._pas % 5 == 0:
            # le mur connu, vu depuis le LiDAR à la pose vraie
            c, s = math.cos(verite[2]), math.sin(verite[2])
            dx_, dy_ = self.mur[:, 0] - verite[0], self.mur[:, 1] - verite[1]
            local = np.column_stack([c * dx_ + s * dy_ - POSE_LIDAR[0], -s * dx_ + c * dy_ - POSE_LIDAR[1],
                                     self.mur[:, 2] - POSE_LIDAR[2]])
            self.pub_points.publish(_nuage_xyz(local, "lidar", stamp))


class Ecoute(_Noeud):
    """Nœud de test : état du repérage, TF, /points (remis dans map), requêtes slam_operate."""

    def __init__(self):
        super().__init__("ecoute_reperage_test")
        import tf2_ros
        from rclpy.qos import qos_profile_sensor_data
        from sensor_msgs.msg import PointCloud2
        from std_msgs.msg import String
        from unitree_api.msg import Request
        self.String = String
        self.etats = []
        self.requetes = []
        self.points = []                   # (stamp s, tableau (N, 3) dans lidar)
        self.tampon = tf2_ros.Buffer()
        self.ecoute_tf = tf2_ros.TransformListener(self.tampon, self.noeud)
        self.pub_demande = self.noeud.create_publisher(String, "/reperage/demander", 10)
        self.pub_panne = self.noeud.create_publisher(String, "/faux_slam/panne", 10)
        self.noeud.create_subscription(String, "/reperage/etat", self._sur_etat, 10)
        self.noeud.create_subscription(Request, "/api/slam_operate/request", self.requetes.append, 10)
        self.noeud.create_subscription(PointCloud2, "/points", self._sur_points, qos_profile_sensor_data)
        self._fil.start()

    def _sur_etat(self, msg):
        self.etats.append(json.loads(msg.data))

    def _sur_points(self, msg):
        from g1_nav.nuages import lire_xyz
        self.points.append((msg.header.frame_id, lire_xyz(msg)))
        del self.points[:-5]

    def dernier(self):
        return self.etats[-1] if self.etats else None

    def demander(self, ident, x=None, y=None, theta=None):
        d = {"id": ident}
        if x is not None:
            d.update(x=float(x), y=float(y), theta=float(theta))
        self.pub_demande.publish(self.String(data=json.dumps(d)))

    def panne(self, texte):
        self.pub_panne.publish(self.String(data=texte))

    def attendre(self, condition, delai):
        fin = time.monotonic() + delai
        while time.monotonic() < fin:
            try:
                if condition():
                    return True
            except Exception:      # noqa: BLE001 : donnée pas encore là
                pass
            time.sleep(0.05)
        return False

    def transformation(self, parent, enfant):
        """(x, y, cap) de enfant dans parent par TF (dernière valeur), ou None."""
        from rclpy.time import Time
        from atelier.lieu import quaternion_vers_cap
        try:
            t = self.tampon.lookup_transform(parent, enfant, Time())
        except Exception:      # noqa: BLE001 : pas encore publiée
            return None
        return (t.transform.translation.x, t.transform.translation.y, quaternion_vers_cap(t.transform.rotation))

    def points_dans_la_carte(self):
        """Dernier /points ramené dans map par TF (map → lidar), ou None."""
        from rclpy.time import Time
        from g1_nav.nuages import appliquer, matrice_quaternion
        if not self.points:
            return None
        repere, points = self.points[-1]
        try:
            t = self.tampon.lookup_transform("map", repere, Time())
        except Exception:      # noqa: BLE001
            return None
        tr, q = t.transform.translation, t.transform.rotation
        return appliquer(matrice_quaternion((tr.x, tr.y, tr.z), (q.x, q.y, q.z, q.w)), points)


def ecart(a, b):
    """(distance, écart de cap) entre deux poses au sol."""
    return (math.hypot(a[0] - b[0], a[1] - b[1]),
            abs((a[2] - b[2] + math.pi) % (2 * math.pi) - math.pi))


def journal(chemin):
    return Path(chemin).read_text(encoding="utf-8", errors="replace") if Path(chemin).is_file() else ""
