"""
Outils communs aux tests de g1_sim : lancer la simulation sans fenêtre, l'écouter, la piloter.

  sim = Simulation(dossier_lieu, 'rdc')    lance « ros2 launch g1_sim simulation.launch.py »
  sim.demarrer() ... sim.arreter()         dans son propre groupe de processus, toujours arrêté
  ecoute = Ecoute()                         nœud rclpy : /odom, /points, /tf, /tf_static, /cmd_vel

Isolement : ROS_LOCALHOST_ONLY=1 (rien ne sort de la machine), ROS_DOMAIN_ID de
l'environnement (32 s'il n'est pas réglé), IGN_PARTITION de l'environnement (sinon g1_sim_test).
"""
import math
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import numpy as np

# Réglages d'isolement, posés avant le premier rclpy.init() (le nœud de test en hérite)
os.environ.setdefault('ROS_DOMAIN_ID', '32')
os.environ.setdefault('IGN_PARTITION', 'g1_sim_test')
os.environ['ROS_LOCALHOST_ONLY'] = '1'
os.environ['IGN_IP'] = '127.0.0.1'

import rclpy  # noqa: E402
from geometry_msgs.msg import Twist  # noqa: E402
from nav_msgs.msg import Odometry  # noqa: E402
from rclpy.executors import SingleThreadedExecutor  # noqa: E402
from rclpy.qos import DurabilityPolicy, QoSProfile, qos_profile_sensor_data  # noqa: E402
from sensor_msgs.msg import PointCloud2  # noqa: E402
from sensor_msgs_py import point_cloud2  # noqa: E402
from tf2_msgs.msg import TFMessage  # noqa: E402

DOSSIER_PAQUET = Path(__file__).resolve().parent.parent
MONDE_COULOIR = DOSSIER_PAQUET / 'worlds' / 'couloir.sdf'
HAUTEUR_LIDAR = 1.245          # m, LiDAR du model.sdf de g1_proxy


def journal_dossier():
    """Dossier des journaux des tests (sorties de ros2 launch), créé au besoin."""
    try:
        import atelier
        dossier = atelier.dossier_journaux() / 'g1_sim_tests'
    except ImportError:
        dossier = Path(tempfile.gettempdir()) / 'g1_sim_tests'
    dossier.mkdir(parents=True, exist_ok=True)
    return dossier


def lieu_couloir(dossier):
    """Petit lieu de test dans dossier : mondes/rdc.sdf et rdc.monde.yaml = le couloir de 10 m."""
    mondes = Path(dossier) / 'mondes'
    mondes.mkdir(parents=True, exist_ok=True)
    shutil.copy(MONDE_COULOIR, mondes / 'rdc.sdf')
    shutil.copy(MONDE_COULOIR.with_name('couloir.monde.yaml'), mondes / 'rdc.monde.yaml')
    return Path(dossier)


class Simulation:
    """Lance « ros2 launch g1_sim simulation.launch.py ... sans_fenetre:=true » et l'arrête."""

    def __init__(self, lieu, etage='rdc', monde=None, nom='simulation'):
        self.commande = ['ros2', 'launch', 'g1_sim', 'simulation.launch.py', f'lieu:={lieu}',
                         f'etage:={etage}', 'sans_fenetre:=true']
        if monde:
            self.commande.append(f'monde:={monde}')
        self.journal = journal_dossier() / f'{nom}_{time.strftime("%Y%m%d_%H%M%S")}.log'
        self.processus = None

    def demarrer(self):
        sortie = open(self.journal, 'w', encoding='utf-8')
        # Nouveau groupe de processus : on pourra arrêter Gazebo et les nœuds d'un coup
        self.processus = subprocess.Popen(self.commande, stdout=sortie, stderr=subprocess.STDOUT,
                                          start_new_session=True, env=dict(os.environ))
        sortie.close()

    def en_marche(self):
        return self.processus is not None and self.processus.poll() is None

    def texte_journal(self, lignes=40):
        try:
            return '\n'.join(self.journal.read_text(errors='replace').splitlines()[-lignes:])
        except OSError:
            return ''

    def arreter(self, delai=20.0):
        """Ctrl+C au lancement (il arrête ses nœuds), puis SIGKILL au groupe si besoin."""
        if self.processus is None:
            return
        try:
            groupe = os.getpgid(self.processus.pid)
        except ProcessLookupError:
            groupe = None
        if self.processus.poll() is None:
            self.processus.send_signal(signal.SIGINT)
            try:
                self.processus.wait(timeout=delai)
            except subprocess.TimeoutExpired:
                pass
        if groupe is not None:
            fin = time.time() + 5.0
            while time.time() < fin and _groupe_vivant(groupe):
                time.sleep(0.2)
            if _groupe_vivant(groupe):
                os.killpg(groupe, signal.SIGKILL)
        if self.processus.poll() is None:
            self.processus.kill()
            self.processus.wait()


def _groupe_vivant(groupe):
    try:
        os.killpg(groupe, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def temps(entete):
    """Horodatage d'un message ROS, en secondes (temps simulé)."""
    return entete.stamp.sec + entete.stamp.nanosec * 1e-9


def cap(q):
    """Cap (lacet) d'un quaternion, en radians, pour une rotation autour de z."""
    return math.atan2(2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y * q.y + q.z * q.z))


def points_xyz(nuage):
    """PointCloud2 → tableau numpy (n, 3) des points finis, dans le repère du nuage."""
    brut = point_cloud2.read_points(nuage, field_names=('x', 'y', 'z'), skip_nans=True)
    p = np.stack([brut['x'], brut['y'], brut['z']], axis=1).astype(float)
    return p[np.isfinite(p).all(axis=1)]


def lidar_vers_odom(points, x, y, theta, hauteur=HAUTEUR_LIDAR):
    """Ramène des points du repère lidar dans odom (robot en x, y, theta ; LiDAR à hauteur)."""
    c, s = math.cos(theta), math.sin(theta)
    sortie = np.empty_like(points)
    sortie[:, 0] = c * points[:, 0] - s * points[:, 1] + x
    sortie[:, 1] = s * points[:, 0] + c * points[:, 1] + y
    sortie[:, 2] = points[:, 2] + hauteur
    return sortie


class Ecoute:
    """Nœud rclpy qui écoute la simulation dans un fil de fond, et publie sur /cmd_vel."""

    def __init__(self, nom='test_g1_sim'):
        if not rclpy.ok():
            rclpy.init()
        self.noeud = rclpy.create_node(nom)
        self.verrou = threading.Lock()
        self.odom = []           # [Odometry], les plus récents à la fin
        self.nuages = []         # [(heure murale, PointCloud2)]
        self.tf = {}             # (parent, enfant) → TransformStamped, le plus récent
        self.tf_statique = {}
        n = self.noeud
        n.create_subscription(Odometry, '/odom', self._sur_odom, 50)
        n.create_subscription(PointCloud2, '/points', self._sur_nuage, qos_profile_sensor_data)
        n.create_subscription(TFMessage, '/tf', lambda m: self._sur_tf(m, self.tf), 100)
        statique = QoSProfile(depth=10, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        n.create_subscription(TFMessage, '/tf_static',
                              lambda m: self._sur_tf(m, self.tf_statique), statique)
        self.cmd_vel = n.create_publisher(Twist, '/cmd_vel', 10)
        self.executeur = SingleThreadedExecutor()
        self.executeur.add_node(n)
        self.fil = threading.Thread(target=self.executeur.spin, daemon=True)
        self.fil.start()

    def _sur_odom(self, msg):
        with self.verrou:
            self.odom.append(msg)
            del self.odom[:-2000]

    def _sur_nuage(self, msg):
        with self.verrou:
            self.nuages.append((time.monotonic(), msg))
            del self.nuages[:-50]

    def _sur_tf(self, msg, table):
        with self.verrou:
            for t in msg.transforms:
                table[(t.header.frame_id, t.child_frame_id)] = t

    # ---------------------------------------------------------------- lecture

    def derniere_odom(self):
        with self.verrou:
            return self.odom[-1] if self.odom else None

    def dernier_nuage(self):
        with self.verrou:
            return self.nuages[-1][1] if self.nuages else None

    def pose(self):
        """(x, y, theta, temps simulé) d'après la dernière /odom."""
        o = self.derniere_odom()
        p = o.pose.pose
        return p.position.x, p.position.y, cap(p.orientation), temps(o.header)

    def attendre(self, condition, delai, pas=0.1):
        """Attend que condition() soit vraie, au plus delai secondes (heure murale)."""
        fin = time.monotonic() + delai
        while time.monotonic() < fin:
            if condition():
                return True
            time.sleep(pas)
        return condition()

    def attendre_pret(self, sim, delai=90.0):
        """Attend /odom et /points ; échoue tout de suite si le lancement s'est arrêté."""
        def pret():
            if not sim.en_marche():
                raise RuntimeError('la simulation s\'est arrêtée :\n' + sim.texte_journal())
            with self.verrou:
                return bool(self.odom) and len(self.nuages) >= 3
        if not self.attendre(pret, delai):
            raise RuntimeError(f'ni /odom ni /points après {delai:.0f} s :\n'
                               + sim.texte_journal())

    def nuages_depuis(self, debut):
        with self.verrou:
            return [m for (t, m) in self.nuages if t >= debut]

    # ---------------------------------------------------------------- commande

    def rouler(self, vx=0.0, vy=0.0, wz=0.0, duree=1.0, delai_max=None):
        """
        Envoie (vx, vy, wz) pendant duree secondes de temps SIMULÉ, puis l'arrêt.

        Renvoie (pose avant, pose après l'arrêt), chacune en (x, y, theta, temps).
        """
        commande = Twist()
        commande.linear.x, commande.linear.y, commande.angular.z = float(vx), float(vy), float(wz)
        avant = self.pose()
        fin_murale = time.monotonic() + (delai_max or 10.0 * duree + 10.0)
        while self.pose()[3] < avant[3] + duree and time.monotonic() < fin_murale:
            self.cmd_vel.publish(commande)
            time.sleep(0.02)
        self.arreter_robot()
        return avant, self.pose()

    def arreter_robot(self):
        """Vitesse nulle, puis attend que le robot soit immobile (0,3 s simulées)."""
        zero = Twist()
        for _ in range(5):
            self.cmd_vel.publish(zero)
            time.sleep(0.02)
        t0 = self.pose()[3]
        self.attendre(lambda: self.pose()[3] > t0 + 0.3, 10.0)

    def fermer(self):
        self.executeur.shutdown()
        self.noeud.destroy_node()
        self.fil.join(timeout=2.0)


def distance_boite(points, centre, taille):
    """Distance de chaque point à la surface d'une boîte alignée sur les axes."""
    demi = np.asarray(taille, dtype=float) / 2.0
    q = np.abs(points - np.asarray(centre, dtype=float)) - demi
    dehors = np.linalg.norm(np.maximum(q, 0.0), axis=1)
    dedans = np.minimum(q.max(axis=1), 0.0)
    return np.abs(dehors + dedans)
