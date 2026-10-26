"""
Outils des tests ROS 2 du pont : lancer le nœud pont_g1, et un faux robot qui lui répond.

  pont = NoeudLance('pont', ['-p', 'exiger_reperage:=false'])   lance lib/g1_bridge/pont
  robot = FauxRobot()      nœud rclpy dans un fil : répond aux requêtes (ou se tait, refuse),
                           publie /cmd_vel, /reperage/etat, /guide/stop, /pont/arret ;
                           lit /pont/etat

Isolement : ROS_LOCALHOST_ONLY=1, ROS_DOMAIN_ID de l'environnement (62 par défaut, celui de
l'agent Pont). Les processus sont lancés dans leur propre groupe, et toujours arrêtés.
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
os.environ['ROS_LOCALHOST_ONLY'] = '1'

import rclpy  # noqa: E402
from geometry_msgs.msg import Twist  # noqa: E402
from rclpy.executors import SingleThreadedExecutor  # noqa: E402
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy  # noqa: E402
from std_msgs.msg import Bool, Empty, String  # noqa: E402
from unitree_api.msg import Request, Response  # noqa: E402

try:
    from atelier.lieu import valider_message
except ImportError:
    valider_message = None


def dossier_journaux():
    try:
        import atelier
        dossier = atelier.dossier_journaux() / 'g1_bridge_tests'
    except ImportError:
        dossier = Path(tempfile.gettempdir()) / 'g1_bridge_tests'
    dossier.mkdir(parents=True, exist_ok=True)
    return dossier


def executable(paquet, nom):
    """Chemin de lib/<paquet>/<nom> : lancé directement, il reçoit nos signaux lui-même."""
    from ament_index_python.packages import get_package_prefix
    return str(Path(get_package_prefix(paquet)) / 'lib' / paquet / nom)


class NoeudLance:
    """Un exécutable ROS 2 lancé dans son groupe de processus, sortie dans un journal."""

    def __init__(self, nom, arguments_ros=(), paquet='g1_bridge', executable_nom='pont'):
        self.commande = [executable(paquet, executable_nom)]
        if arguments_ros:
            self.commande += ['--ros-args'] + list(arguments_ros)
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

    def arreter(self, delai=10.0):
        if self.processus is None:
            return
        if self.processus.poll() is None:
            self.processus.send_signal(signal.SIGINT)
            try:
                self.processus.wait(timeout=delai)
            except subprocess.TimeoutExpired:
                pass
        try:
            os.killpg(self.processus.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        if self.processus.poll() is None:
            self.processus.kill()
            self.processus.wait()


def vitesses(requete):
    """(vx, vy, wz, duration) d'une requête 7105."""
    p = json.loads(requete.parameter)
    return tuple(p['velocity']) + (p['duration'],)


def est_arret(requete):
    vx, vy, wz, _ = vitesses(requete)
    return vx == vy == wz == 0.0


class FauxRobot:
    """Nœud de test : joue le service sport et l'environnement du pont."""

    def __init__(self, nom='faux_robot_test'):
        if not rclpy.ok():
            rclpy.init()
        self.noeud = rclpy.create_node(nom)
        self.verrou = threading.Lock()
        self.requetes = []          # [(instant monotone, Request)]
        self.etats = []             # [(instant, dict)]
        self.repondre = True
        self.code = 0
        self.erreurs_schema = []
        n = self.noeud
        fiable = QoSProfile(depth=50, reliability=ReliabilityPolicy.RELIABLE)
        n.create_subscription(Request, '/api/sport/request', self._sur_requete, fiable)
        n.create_subscription(String, '/pont/etat', self._sur_etat, 50)
        self.pub_reponse = n.create_publisher(Response, '/api/sport/response', fiable)
        self.pub_cmd_vel = n.create_publisher(Twist, '/cmd_vel', 10)
        self.pub_reperage = n.create_publisher(String, '/reperage/etat', 10)
        self.pub_stop = n.create_publisher(Empty, '/guide/stop', 10)
        self.pub_verrou = n.create_publisher(
            Bool, '/pont/arret', QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                                            durability=DurabilityPolicy.TRANSIENT_LOCAL))
        self.executeur = SingleThreadedExecutor()
        self.executeur.add_node(n)
        self.fil = threading.Thread(target=self._tourner, daemon=True)
        self.fil.start()
        self.reperage = None        # True / False : publié à 5 Hz ; None : rien
        self.cmd_vel = None         # (vx, vy, wz) publié à 20 Hz ; None : rien
        self._actif = True
        self.fil_publication = threading.Thread(target=self._publier_en_continu, daemon=True)
        self.fil_publication.start()

    def _tourner(self):
        try:
            self.executeur.spin()
        except Exception:       # noqa: B902 (arrêt du test)
            pass

    def _publier_en_continu(self):
        prochain_rep = 0.0
        while self._actif:
            t = time.monotonic()
            # Une seule lecture de chaque réglage : le test peut le remettre à None entre deux
            # lectures (une consigne None ferait sinon tomber ce fil, un repérage None
            # publierait « non repéré »)
            reperage, consigne = self.reperage, self.cmd_vel
            if reperage is not None and t >= prochain_rep:
                self.publier_reperage(reperage)
                prochain_rep = t + 0.2
            if consigne is not None:
                self.publier_cmd_vel(*consigne)
            time.sleep(0.05)

    def cesser(self, nom):
        """
        Arrête la publication continue de « cmd_vel » ou « reperage ».

        Attend ensuite que le fil de publication (pas de 50 ms) ait fini son tour : plus rien de
        ce sujet ne part après le retour de cette méthode.
        """
        setattr(self, nom, None)
        time.sleep(0.07)

    def _sur_requete(self, msg):
        with self.verrou:
            self.requetes.append((time.monotonic(), msg))
            repondre, code = self.repondre, self.code
        if repondre:
            r = Response()
            r.header.identity.id = msg.header.identity.id
            r.header.identity.api_id = msg.header.identity.api_id
            r.header.status.code = code
            self.pub_reponse.publish(r)

    def _sur_etat(self, msg):
        etat = json.loads(msg.data)
        if valider_message is not None:
            erreurs = valider_message('etat_pont', etat)
            if erreurs:
                self.erreurs_schema.append((etat, erreurs))
        with self.verrou:
            self.etats.append((time.monotonic(), etat))

    # ------------------------------------------------------------ publications

    def publier_cmd_vel(self, vx, vy, wz):
        t = Twist()
        t.linear.x, t.linear.y, t.angular.z = float(vx), float(vy), float(wz)
        self.pub_cmd_vel.publish(t)

    def publier_reperage(self, repere):
        self.pub_reperage.publish(String(data=json.dumps({'version': 1, 'repere': bool(repere)})))

    def guide_stop(self):
        self.pub_stop.publish(Empty())

    def verrouiller(self, actif):
        self.pub_verrou.publish(Bool(data=bool(actif)))

    # ------------------------------------------------------------ lecture

    def requetes_depuis(self, t0, t1=math.inf):
        with self.verrou:
            return [(t, m) for t, m in self.requetes if t0 <= t < t1]

    def dernier_etat(self):
        with self.verrou:
            return self.etats[-1][1] if self.etats else None

    def attendre(self, condition, delai, message='condition non remplie'):
        fin = time.monotonic() + delai
        while time.monotonic() < fin:
            valeur = condition()
            if valeur:
                return valeur
            time.sleep(0.01)
        raise AssertionError(f'{message} (après {delai:g} s)')

    def attendre_etat(self, nom, delai=5.0):
        return self.attendre(lambda: (self.dernier_etat() or {}).get('etat') == nom
                             and self.dernier_etat(), delai,
                             f'/pont/etat ne passe pas à {nom} (dernier : {self.dernier_etat()})')

    def fermer(self):
        self._actif = False
        self.fil_publication.join(timeout=2.0)
        self.executeur.shutdown(timeout_sec=2.0)
        self.fil.join(timeout=2.0)
        self.noeud.destroy_node()
