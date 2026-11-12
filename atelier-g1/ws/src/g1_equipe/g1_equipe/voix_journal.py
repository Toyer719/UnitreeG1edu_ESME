"""
Voix du journal (exécutable voix_journal) : BOUCHON de la partie voix de l'équipe.

    ros2 run g1_equipe voix_journal [--ros-args -p commande:=g1-parler -p fichier:=/tmp/voix.log]

Elle écoute /robot/dire (std_msgs/String JSON, schéma robot_dire), la seule entrée de la partie
voix, et /personnalite/active (fiable, transient_local), et écrit chaque phrase dans le journal
du nœud : « [Accueillant] Je vous emmène à Salle B204. Suivez-moi ! (dialogue) ». Un message hors
du schéma est signalé, pas dit.

Avec commande (ex. g1-parler, la voix française Piper du PC), elle dit vraiment les phrases, une
à la fois : « commande --vitesse V texte », V étant la vitesse de la voix de la personnalité
(voix.vitesse, 1.0 par défaut). Une phrase de priorité haute coupe celle en cours. fichier :
ajoute aussi chaque phrase à ce fichier texte. Elle ne commande rien d'autre.
"""
from collections import deque
import json
import shutil
import subprocess
import sys

from atelier.lieu import valider_message
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String

VERROU = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                    durability=DurabilityPolicy.TRANSIENT_LOCAL, history=HistoryPolicy.KEEP_LAST)
ATTENTE_MAX = 5          # phrases en attente au plus (les plus vieilles sont oubliées)


def ligne(message, personnalite=None):
    """Texte d'une phrase pour le journal : « [Nom] texte (source, code) »."""
    nom = (personnalite or {}).get('nom') or message.get('personnalite') or '—'
    details = ', '.join(x for x in (message.get('source'), message.get('code')) if x)
    return f'[{nom}] {message["texte"]}' + (f' ({details})' if details else '')


class VoixJournal(Node):
    """Écrit (et dit, avec une commande) les phrases de /robot/dire."""

    def __init__(self):
        super().__init__('voix_journal')
        commande = self.declare_parameter('commande', '').value
        self.fichier = self.declare_parameter('fichier', '').value or None
        self.commande = None
        if commande:
            self.commande = shutil.which(commande)
            if self.commande is None:
                self.get_logger().error(f'commande de voix introuvable : {commande} '
                                        '(journal seul)')
        self.personnalite = None
        self.attente = deque(maxlen=ATTENTE_MAX)
        self.en_cours = None
        self.dites = 0
        self.create_subscription(String, '/robot/dire', self.sur_dire, 20)
        self.create_subscription(String, '/personnalite/active', self.sur_personnalite, VERROU)
        self.create_timer(0.1, self.parler)
        mode = f'dites par {self.commande}' if self.commande else 'écrites dans le journal'
        self.get_logger().info(f'voix du journal : les phrases de /robot/dire sont {mode} '
                               '(BOUCHON de la voix de l\'équipe)')

    def sur_personnalite(self, msg):
        """Retient la personnalité active."""
        try:
            d = json.loads(msg.data)
        except ValueError:
            return
        if isinstance(d, dict) and not valider_message('personnalite_active', d):
            self.personnalite = d

    def sur_dire(self, msg):
        """Écrit une phrase, et la met en attente si une commande la dit."""
        try:
            d = json.loads(msg.data)
        except ValueError:
            d = None
        if isinstance(d, dict):
            erreurs = valider_message('robot_dire', d)
        else:
            erreurs = ['JSON illisible']
        if erreurs:
            self.get_logger().warn('/robot/dire hors du schéma robot_dire, pas dit : '
                                   + erreurs[0])
            return
        texte = ligne(d, self.personnalite)
        self.dites += 1
        self.get_logger().info(texte)
        if self.fichier:
            try:
                with open(self.fichier, 'a', encoding='utf-8') as f:
                    f.write(texte + '\n')
            except OSError as e:
                self.get_logger().error(f'écriture impossible dans {self.fichier} : {e}')
        if self.commande is None:
            return
        if d.get('priorite') == 'haute':
            self.attente.clear()
            self.couper()
        self.attente.append(d)

    def couper(self):
        """Coupe la phrase en cours."""
        if self.en_cours is not None and self.en_cours.poll() is None:
            self.en_cours.terminate()

    def parler(self):
        """Dit la phrase suivante quand la précédente est finie."""
        if self.en_cours is not None and self.en_cours.poll() is None:
            return
        if not self.attente:
            return
        d = self.attente.popleft()
        voix = d.get('voix') or (self.personnalite or {}).get('voix') or {}
        vitesse = float(voix.get('vitesse', 1.0))
        self.en_cours = subprocess.Popen([self.commande, '--vitesse', f'{vitesse:g}', d['texte']],
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                         stdin=subprocess.DEVNULL)

    def fermer(self):
        """Coupe la phrase en cours (à l'arrêt du nœud)."""
        self.attente.clear()
        self.couper()


def main(args=None):
    """Lance la voix du journal (ros2 run g1_equipe voix_journal)."""
    rclpy.init(args=args)
    noeud = None
    try:
        noeud = VoixJournal()
        rclpy.spin(noeud)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        if noeud is not None:
            noeud.fermer()
            noeud.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0


if __name__ == '__main__':
    sys.exit(main())
