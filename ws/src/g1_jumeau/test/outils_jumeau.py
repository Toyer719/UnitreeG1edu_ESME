"""
Outils des tests ROS 2 du faux G1 : lancer des nœuds, et un client qui l'écoute et le commande.

  jumeau = NoeudLance('jumeau', ['-p', 'latence_s:=0.3'])     lance lib/g1_jumeau/jumeau
  client = Client()     nœud rclpy dans un fil : envoie des requêtes, publie une fausse vérité
                        (/g1_jumeau/odom) et des pannes ; écoute les réponses, /g1_jumeau/cmd_vel,
                        /state_estimator/odom_pelvis, /g1_jumeau/etat (et, avec Gazebo,
                        la vraie vérité et /pont/etat)

Isolement : ROS_LOCALHOST_ONLY=1, IGN_IP=127.0.0.1, ROS_DOMAIN_ID et IGN_PARTITION de
l'environnement (62 et robot_62 par défaut, ceux de l'agent Pont).
"""
import json
import math
import os
import signal
import subprocess
import tempfile
import threading
import time
from pathlib import Path

os.environ.setdefault('ROS_DOMAIN_ID', '62')
os.environ.setdefault('IGN_PARTITION', 'robot_62')
os.environ['ROS_LOCALHOST_ONLY'] = '1'
os.environ['IGN_IP'] = '127.0.0.1'

import rclpy  # noqa: E402
from geometry_msgs.msg import Twist  # noqa: E402
from nav_msgs.msg import Odometry  # noqa: E402
from rclpy.executors import SingleThreadedExecutor  # noqa: E402
from rclpy.qos import qos_profile_sensor_data, QoSProfile, ReliabilityPolicy  # noqa: E402
from std_msgs.msg import String  # noqa: E402
from unitree_api.msg import Request, Response  # noqa: E402


def dossier_journaux():
    try:
        import atelier
        dossier = atelier.dossier_journaux() / 'g1_jumeau_tests'
    except ImportError:
        dossier = Path(tempfile.gettempdir()) / 'g1_jumeau_tests'
    dossier.mkdir(parents=True, exist_ok=True)
    return dossier


def executable(paquet, nom):
    """Chemin de lib/<paquet>/<nom> : lancé directement, il reçoit nos signaux lui-même."""
    from ament_index_python.packages import get_package_prefix
    return str(Path(get_package_prefix(paquet)) / 'lib' / paquet / nom)


class NoeudLance:
    """Une commande lancée dans son groupe de processus, sortie dans un journal."""

    def __init__(self, nom, arguments_ros=(), paquet='g1_jumeau', executable_nom='jumeau',
                 commande=None):
        if commande is None:
            commande = [executable(paquet, executable_nom)]
            if arguments_ros:
                commande += ['--ros-args'] + list(arguments_ros)
        self.commande = list(commande)
        self.journal = dossier_journaux() / f'{nom}_{time.strftime("%Y%m%d_%H%M%S")}.log'
        self.processus = None

    def demarrer(self):
        sortie = open(self.journal, 'w', encoding='utf-8')
        self.processus = subprocess.Popen(self.commande, stdout=sortie, stderr=subprocess.STDOUT,
                                          start_new_session=True, env=dict(os.environ))
        sortie.close()
        return self

    def vivant(self):
        return self.processus is not None and self.processus.poll() is None

    def signaler(self, numero):
        self.processus.send_signal(numero)

    def attendre(self, delai=10.0):
        return self.processus.wait(timeout=delai)

    def texte(self):
        try:
            return self.journal.read_text(errors='replace')
        except OSError:
            return ''

    def arreter(self, delai=20.0):
        """SIGINT (le lancement arrête ses nœuds), puis SIGKILL au groupe s'il en reste."""
        if self.processus is None:
            return
        if self.processus.poll() is None:
            self.processus.send_signal(signal.SIGINT)
            try:
                self.processus.wait(timeout=delai)
            except subprocess.TimeoutExpired:
                pass
        fin = time.monotonic() + 5.0
        while time.monotonic() < fin and _groupe_vivant(self.processus.pid):
            time.sleep(0.2)
        try:
            os.killpg(self.processus.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
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


def cap(q):
    return math.atan2(2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y * q.y + q.z * q.z))


def odometrie(x, y, theta, stamp_s=0.0, vx=0.0):
    """Un nav_msgs/Odometry de vérité terrain (repère du monde)."""
    m = Odometry()
    m.header.frame_id = 'odom'
    m.child_frame_id = 'base_link'
    m.header.stamp.sec = int(stamp_s)
    m.header.stamp.nanosec = int(round((stamp_s - int(stamp_s)) * 1e9))
    m.pose.pose.position.x, m.pose.pose.position.y = float(x), float(y)
    m.pose.pose.orientation.z = math.sin(theta / 2.0)
    m.pose.pose.orientation.w = math.cos(theta / 2.0)
    m.twist.twist.linear.x = float(vx)
    return m


class Client:
    """Nœud de test : client du faux service sport, et témoin de ce qu'il publie."""

    def __init__(self, nom='client_jumeau_test', verite=False):
        if not rclpy.ok():
            rclpy.init()
        self.noeud = rclpy.create_node(nom)
        self.verrou = threading.Lock()
        self.reponses = []        # [(instant, Response)]
        self.vitesses = []        # [(instant, (vx, vy, wz))] de /g1_jumeau/cmd_vel
        self.pelvis = []          # [(instant, Odometry)]
        self.verites = []         # [(instant, Odometry)] de /g1_jumeau/odom (Gazebo)
        self.etats = []           # [(instant, dict)] de /g1_jumeau/etat
        self.requetes = []        # [(instant, Request)] vues sur /api/sport/request
        self.etats_pont = []
        n = self.noeud
        fiable = QoSProfile(depth=100, reliability=ReliabilityPolicy.RELIABLE)
        self.pub_requete = n.create_publisher(Request, '/api/sport/request', fiable)
        self.pub_panne = n.create_publisher(String, '/g1_jumeau/panne', fiable)
        self.pub_verite = None if verite else n.create_publisher(Odometry, '/g1_jumeau/odom', 10)
        self.pub_cmd_vel = n.create_publisher(Twist, '/cmd_vel', 10)
        self.pub_reperage = n.create_publisher(String, '/reperage/etat', 10)
        n.create_subscription(Response, '/api/sport/response', self._ajouter(self.reponses),
                              qos_profile_sensor_data)
        n.create_subscription(Twist, '/g1_jumeau/cmd_vel', self._sur_vitesse, 100)
        n.create_subscription(Odometry, '/state_estimator/odom_pelvis', self._ajouter(self.pelvis),
                              qos_profile_sensor_data)
        n.create_subscription(String, '/g1_jumeau/etat',
                              lambda m: self._ajouter(self.etats)(json.loads(m.data)), 10)
        n.create_subscription(String, '/pont/etat',
                              lambda m: self._ajouter(self.etats_pont)(json.loads(m.data)), 10)
        n.create_subscription(Request, '/api/sport/request', self._ajouter(self.requetes),
                              qos_profile_sensor_data)
        if verite:
            n.create_subscription(Odometry, '/g1_jumeau/odom', self._ajouter(self.verites),
                                  qos_profile_sensor_data)
        self.executeur = SingleThreadedExecutor()
        self.executeur.add_node(n)
        self.fil = threading.Thread(target=self._tourner, daemon=True)
        self.fil.start()
        self.prochain_id = time.monotonic_ns()
        self.cmd_vel = None         # (vx, vy, wz) publié à 20 Hz ; None : rien
        self.reperage = None        # True : /reperage/etat repéré à 5 Hz
        self._actif = True
        self.fil_publication = threading.Thread(target=self._publier_en_continu, daemon=True)
        self.fil_publication.start()

    def _tourner(self):
        try:
            self.executeur.spin()
        except Exception:       # noqa: B902 (arrêt du test)
            pass

    def _ajouter(self, liste):
        def rappel(msg):
            with self.verrou:
                liste.append((time.monotonic(), msg))
                del liste[:-20000]
        return rappel

    def _sur_vitesse(self, msg):
        self._ajouter(self.vitesses)((msg.linear.x, msg.linear.y, msg.angular.z))

    def _publier_en_continu(self):
        prochain_rep = 0.0
        while self._actif:
            if self.cmd_vel is not None:
                t = Twist()
                t.linear.x, t.linear.y, t.angular.z = self.cmd_vel
                self.pub_cmd_vel.publish(t)
            if self.reperage is not None and time.monotonic() >= prochain_rep:
                self.pub_reperage.publish(String(data=json.dumps({'repere': self.reperage})))
                prochain_rep = time.monotonic() + 0.2
            time.sleep(0.05)

    # ------------------------------------------------------------ envois

    def requete(self, parametre, api_id=7105, identifiant=None):
        """Publie une requête ; renvoie son identity.id."""
        if identifiant is None:
            self.prochain_id = max(time.monotonic_ns(), self.prochain_id + 1)
            identifiant = self.prochain_id
        r = Request()
        r.header.identity.id = identifiant
        r.header.identity.api_id = api_id
        r.parameter = parametre
        self.pub_requete.publish(r)
        return identifiant

    def vitesse(self, vx, vy, wz, duree):
        return self.requete(json.dumps({'velocity': [vx, vy, wz], 'duration': duree}))

    def panne(self, nom):
        self.pub_panne.publish(String(data=nom))

    def verite(self, x, y, theta, stamp_s=0.0, vx=0.0):
        self.pub_verite.publish(odometrie(x, y, theta, stamp_s, vx))

    # ------------------------------------------------------------ lecture

    def depuis(self, liste, t0, t1=math.inf):
        with self.verrou:
            return [(t, m) for t, m in liste if t0 <= t < t1]

    def reponse(self, identifiant):
        with self.verrou:
            for t, r in self.reponses:
                if r.header.identity.id == identifiant:
                    return t, r
        return None

    def attendre(self, condition, delai, message='condition non remplie'):
        fin = time.monotonic() + delai
        while time.monotonic() < fin:
            valeur = condition()
            if valeur:
                return valeur
            time.sleep(0.01)
        raise AssertionError(f'{message} (après {delai:g} s)')

    def attendre_abonne(self, sujet, delai=10.0):
        self.attendre(lambda: self.noeud.count_subscribers(sujet) > 0, delai,
                      f'personne n\'écoute {sujet}')

    def fermer(self):
        self._actif = False
        self.fil_publication.join(timeout=2.0)
        self.executeur.shutdown(timeout_sec=2.0)
        self.fil.join(timeout=2.0)
        self.noeud.destroy_node()
