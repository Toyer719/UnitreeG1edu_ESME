"""
Outils des tests ROS 2 de g1_equipe : lancer un exécutable du paquet, et un nœud de test.

  noeud = NoeudLance('dialogue', ['-p', 'lieu:=/tmp/demo']).demarrer()   lib/g1_equipe/dialogue
  t = Temoin()       nœud rclpy dans un fil : publie /visiteur/texte, /guide/evenement,
                     /guide/etat,
                     /mouvement/maitre, /visiteurs/detectes, /pietons/etat, /odom… ; garde tout ce
                     qui arrive sur /robot/dire, /guide/aller, /guide/stop, /personnalite/active et
                     /visiteurs/detectes (avec l'instant de réception), et vérifie les schémas

Isolement : ROS_LOCALHOST_ONLY=1, ROS_DOMAIN_ID de l'environnement (75 par défaut, celui de
l'agent Équipe). Les processus sont lancés dans leur propre groupe, et toujours arrêtés.
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import threading
import time

os.environ.setdefault('ROS_DOMAIN_ID', '75')
os.environ['ROS_LOCALHOST_ONLY'] = '1'

from atelier.lieu import valider_message  # noqa: E402
from nav_msgs.msg import Odometry  # noqa: E402
import rclpy  # noqa: E402
from rclpy.executors import SingleThreadedExecutor  # noqa: E402
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy  # noqa: E402
from std_msgs.msg import Empty, String  # noqa: E402

VERROU = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                    durability=DurabilityPolicy.TRANSIENT_LOCAL)
SCHEMAS = {'/robot/dire': 'robot_dire', '/guide/aller': 'demande_guide',
           '/personnalite/active': 'personnalite_active', '/visiteurs/detectes': 'personnes'}


def dossier_journaux():
    """Dossier des journaux des nœuds lancés par les tests."""
    try:
        import atelier
        dossier = atelier.dossier_journaux() / 'g1_equipe_tests'
    except ImportError:
        dossier = Path(tempfile.gettempdir()) / 'g1_equipe_tests'
    dossier.mkdir(parents=True, exist_ok=True)
    return dossier


def executable(nom):
    """Chemin de lib/g1_equipe/<nom> : lancé directement, il reçoit nos signaux lui-même."""
    from ament_index_python.packages import get_package_prefix
    return str(Path(get_package_prefix('g1_equipe')) / 'lib' / 'g1_equipe' / nom)


class NoeudLance:
    """Un exécutable du paquet lancé dans son groupe de processus, sortie dans un journal."""

    def __init__(self, nom, arguments_ros=()):
        self.commande = [executable(nom)]
        if arguments_ros:
            self.commande += ['--ros-args'] + list(arguments_ros)
        horodatage = time.strftime('%Y%m%d_%H%M%S')
        self.journal = dossier_journaux() / f'{nom}_{horodatage}_{os.getpid()}.log'
        self.processus = None

    def demarrer(self):
        """Lance le processus."""
        sortie = open(self.journal, 'w', encoding='utf-8')
        self.processus = subprocess.Popen(self.commande, stdout=sortie, stderr=subprocess.STDOUT,
                                          start_new_session=True, env=dict(os.environ))
        sortie.close()
        return self

    def attendre(self, delai=10.0):
        """Attend la fin du processus ; renvoie son code."""
        return self.processus.wait(timeout=delai)

    def texte(self):
        """Contenu du journal."""
        try:
            return self.journal.read_text(errors='replace')
        except OSError:
            return ''

    def attendre_texte(self, morceau, delai=10.0):
        """Attend qu'un texte apparaisse dans le journal."""
        fin = time.monotonic() + delai
        while time.monotonic() < fin:
            if morceau in self.texte():
                return True
            time.sleep(0.1)
        return False

    def arreter(self, delai=10.0):
        """Arrête le processus (SIGINT, puis SIGKILL du groupe)."""
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


class Temoin:
    """Nœud de test : joue le guide, la reconnaissance vocale, la caméra et le pilotage."""

    def __init__(self, nom='temoin_equipe'):
        if not rclpy.ok():
            rclpy.init()
        self.noeud = rclpy.create_node(nom)
        self.verrou = threading.Lock()
        self.recus = {s: [] for s in ('/robot/dire', '/guide/aller', '/guide/stop',
                                      '/personnalite/active', '/visiteurs/detectes')}
        self.erreurs_schema = []
        self._publies = set()          # (sujet, texte) publiés par le témoin : pas « reçus »
        n = self.noeud
        for sujet in ('/robot/dire', '/guide/aller', '/visiteurs/detectes'):
            n.create_subscription(String, sujet, self._recepteur(sujet), 50)
        n.create_subscription(String, '/personnalite/active',
                              self._recepteur('/personnalite/active'), VERROU)
        n.create_subscription(Empty, '/guide/stop', self._recepteur('/guide/stop'), 10)
        self.pubs = {s: n.create_publisher(String, s, 10)
                     for s in ('/visiteur/texte', '/guide/evenement', '/guide/etat',
                               '/visiteurs/detectes', '/pietons/etat', '/fausse_camera/mode')}
        self.pubs['/mouvement/maitre'] = n.create_publisher(String, '/mouvement/maitre', VERROU)
        self.pubs['/personnalite/active'] = n.create_publisher(String, '/personnalite/active',
                                                               VERROU)
        self.pubs['/robot/dire'] = n.create_publisher(String, '/robot/dire', 10)
        self.pub_odom = n.create_publisher(Odometry, '/odom', 10)
        self.executeur = SingleThreadedExecutor()
        self.executeur.add_node(n)
        self._fin = threading.Event()
        self._fil = threading.Thread(target=self._tourner, daemon=True)
        self._fil.start()

    def _tourner(self):
        while not self._fin.is_set():
            self.executeur.spin_once(timeout_sec=0.02)

    def _recepteur(self, sujet):
        def recevoir(msg):
            donnees = None
            if isinstance(msg, String) and (sujet, msg.data) in self._publies:
                return
            if isinstance(msg, String):
                try:
                    donnees = json.loads(msg.data)
                except ValueError:
                    donnees = msg.data
                if sujet in SCHEMAS and valider_message is not None:
                    if isinstance(donnees, dict):
                        erreurs = valider_message(SCHEMAS[sujet], donnees)
                    else:
                        erreurs = ['pas du JSON']
                    if erreurs:
                        self.erreurs_schema.append((sujet, erreurs))
            with self.verrou:
                self.recus[sujet].append((time.monotonic(), donnees))
        return recevoir

    def publier(self, sujet, donnees):
        """Publie un texte brut, ou un dict en JSON."""
        texte = donnees if isinstance(donnees, str) else json.dumps(donnees, ensure_ascii=False)
        self._publies.add((sujet, texte))
        self.pubs[sujet].publish(String(data=texte))

    def publier_odom(self, x, y):
        """Publie /odom (pose seulement, cap 0)."""
        m = Odometry()
        m.header.frame_id = 'odom'
        m.pose.pose.position.x, m.pose.pose.position.y = float(x), float(y)
        m.pose.pose.orientation.w = 1.0
        self.pub_odom.publish(m)

    def abonnes(self, sujet):
        """Nombre de nœuds abonnés à un sujet que publie le témoin."""
        return self.pubs[sujet].get_subscription_count()

    def messages(self, sujet, depuis=0.0):
        """Messages reçus sur un sujet depuis l'instant donné (sans l'instant)."""
        with self.verrou:
            return [d for t, d in self.recus[sujet] if t >= depuis]

    def attendre(self, condition, delai=5.0, message='délai dépassé'):
        """Attend qu'une condition soit vraie (AssertionError sinon)."""
        fin = time.monotonic() + delai
        while time.monotonic() < fin:
            valeur = condition()
            if valeur:
                return valeur
            time.sleep(0.05)
        raise AssertionError(message)

    def dire(self, texte, delai=5.0):
        """Publie une phrase et attend la réponse du nœud : (instant d'envoi, réponse)."""
        t0 = time.monotonic()
        self.publier('/visiteur/texte', texte)
        reponse = self.attendre(lambda: [m for m in self.messages('/robot/dire', t0)
                                         if m.get('source') == 'dialogue'], delai,
                                f'pas de réponse à « {texte} »')
        return t0, reponse[0]

    def fermer(self):
        """Arrête le nœud de test."""
        self._fin.set()
        self._fil.join(timeout=3)
        self.executeur.shutdown()
        self.noeud.destroy_node()
