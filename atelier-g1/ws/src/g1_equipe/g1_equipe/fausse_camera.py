"""
Fausse caméra (exécutable fausse_camera) : BOUCHON de la caméra See3CAM de l'équipe.

    ros2 run g1_equipe fausse_camera --ros-args -p lieu:=demo [-p mode:=fixe -p x:=1.5 -p y:=0.0]

Elle publie /visiteurs/detectes (std_msgs/String JSON, schéma personnes, source camera), au
rythme de detection.frequence_hz de camera.yaml (10 Hz sans fichier), comme le fera le nœud de
la caméra de l'équipe : on peut ainsi essayer le reste (salutation du nœud dialogue, onglet
Caméra de l'Atelier) sans la caméra. Modes (paramètre mode, ou message sur /fausse_camera/mode) :
  fixe [X Y]   une personne immobile en (X, Y) dans base_link (défaut : 1,5 m devant), qui
               regarde le robot ;
  aucune       personne (liste vide) ;
  pietons      les piétons de Gazebo (/pietons/etat, repère map) que la caméra verrait, placée
               et orientée comme dans camera.yaml, avec la pose du robot lue sur /odom
               (simulation : map = odom).
Elle ne commande rien.
"""
import json
import sys

from atelier import chemin_lieu
from atelier.equipe.camera import message_visiteurs, visibles_depuis_pietons
from atelier.lieu import equipe as E
from atelier.lieu import ErreurLieu, quaternion_vers_cap
from nav_msgs.msg import Odometry
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from std_msgs.msg import String

MODES = ('fixe', 'aucune', 'pietons')
FREQUENCE_DEFAUT_HZ = 10.0


def lire_mode(texte):
    """Lit « fixe », « fixe 2.0 0.5 », « aucune » ou « pietons » : (mode, (x, y) ou None)."""
    morceaux = str(texte).split()
    if not morceaux or morceaux[0] not in MODES:
        raise ValueError(f'mode inconnu : « {texte} » (modes : {", ".join(MODES)})')
    if morceaux[0] == 'fixe' and len(morceaux) == 3:
        return 'fixe', (float(morceaux[1]), float(morceaux[2]))
    if len(morceaux) != 1:
        raise ValueError(f'mode mal écrit : « {texte} » (ex. « fixe 1.5 0.0 »)')
    return morceaux[0], None


class FausseCamera(Node):
    """Publie de fausses détections de visiteurs."""

    def __init__(self):
        super().__init__('fausse_camera')
        p = self.declare_parameter
        lieu = p('lieu', '').value
        self.camera = None
        if lieu:
            try:
                self.camera = E.charger_equipe(chemin_lieu(lieu), 'camera')
            except ErreurLieu as e:
                self.get_logger().error('camera.yaml faux, réglages par défaut : ' + e.erreurs[0])
        detection = (self.camera or {}).get('detection') or {}
        frequence = float(p('frequence_hz', 0.0).value) or float(
            detection.get('frequence_hz') or FREQUENCE_DEFAUT_HZ)
        self.mode, point = lire_mode(p('mode', 'fixe').value)
        self.point = point or (float(p('x', 1.5).value), float(p('y', 0.0).value))
        self.pietons = []
        self.robot = None
        self.pub = self.create_publisher(String, '/visiteurs/detectes', 10)
        self.create_subscription(String, '/fausse_camera/mode', self.sur_mode, 10)
        self.create_subscription(String, '/pietons/etat', self.sur_pietons, 10)
        self.create_subscription(Odometry, '/odom', self.sur_odom, 10)
        self.create_timer(1.0 / min(max(frequence, 0.5), 60.0), self.publier)
        self.get_logger().info(f'fausse caméra : mode {self.mode}, {frequence:g} Hz sur '
                               '/visiteurs/detectes (BOUCHON de la caméra de l\'équipe)')

    def sur_mode(self, msg):
        """Change de mode (« fixe 2.0 0.5 », « aucune », « pietons »)."""
        try:
            self.mode, point = lire_mode(msg.data)
        except ValueError as e:
            self.get_logger().error(str(e))
            return
        if point is not None:
            self.point = point
        self.get_logger().info(f'mode {self.mode}')

    def sur_pietons(self, msg):
        """Retient les piétons de Gazebo (/pietons/etat)."""
        try:
            d = json.loads(msg.data)
        except ValueError:
            return
        if isinstance(d, dict) and isinstance(d.get('pietons'), list):
            self.pietons = d['pietons']

    def sur_odom(self, msg):
        """Retient la pose du robot (simulation : map = odom)."""
        p = msg.pose.pose
        self.robot = (p.position.x, p.position.y, quaternion_vers_cap(p.orientation))

    def personnes(self):
        """Personnes vues dans le mode courant."""
        if self.mode == 'fixe':
            return [{'id': 1, 'x': self.point[0], 'y': self.point[1], 'confiance': 0.9,
                     'regarde_robot': True}]
        if self.mode == 'pietons' and self.robot is not None:
            return visibles_depuis_pietons(self.pietons, self.robot, self.camera)
        return []

    def publier(self):
        """Publie /visiteurs/detectes."""
        temps = self.get_clock().now().nanoseconds * 1e-9
        message = message_visiteurs(temps, self.personnes())
        self.pub.publish(String(data=json.dumps(message, ensure_ascii=False)))


def main(args=None):
    """Lance la fausse caméra (ros2 run g1_equipe fausse_camera)."""
    rclpy.init(args=args)
    noeud = None
    try:
        noeud = FausseCamera()
        rclpy.spin(noeud)
    except ValueError as e:
        print(f'fausse_camera : {e}', file=sys.stderr)
        return 2
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        if noeud is not None:
            noeud.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0


if __name__ == '__main__':
    sys.exit(main())
