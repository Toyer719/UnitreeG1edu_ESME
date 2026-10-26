"""
Nœud g1_jumeau : le faux service « sport » du G1, pour la répétition dans Gazebo (section 10.4).

  ros2 run g1_jumeau jumeau [--ros-args -p latence_s:=0.1 -p perte:=0.2 -p panne:=muet]
  (lancé par « ros2 launch g1_sim simulation.launch.py ... jumeau:=true »)

Il répond comme le vrai robot :
  /api/sport/request (unitree_api/Request) → /api/sport/response (unitree_api/Response) :
      header.identity recopié (id, api_id), status.code 0, data vide ; api inconnue : 3203 ;
      paramètres illisibles : 3204 ; panne refus : 7301.
  7105 pilote le robot proxy de Gazebo sur /g1_jumeau/cmd_vel (geometry_msgs/Twist, 20 Hz,
      toujours) : la consigne pendant sa duration (temps mural), sinon zéro. VelocityControl de
      Gazebo garde la dernière consigne : zéro est aussi publié au lancement, en panne et en
      quittant (SIGINT, SIGTERM). Un SIGKILL laisse la dernière consigne dans Gazebo (limite de
      la simulation : le vrai robot s'arrête seul).
  /g1_jumeau/odom (vérité terrain de Gazebo) → /state_estimator/odom_pelvis (nav_msgs/Odometry),
      au même rythme : frame_id odom, child_frame_id pelvis, z 0,75 m, origine à la pose du
      lancement, dérive de 2 % et 0,01 rad par mètre ; twist recopié (repère du robot, sans
      dérive).
  /g1_jumeau/panne (std_msgs/String, fiable) : aucune, muet ou refus.
  /g1_jumeau/etat (std_msgs/String JSON, 2 Hz) : {version, panne, consigne, reste_s, requetes,
      appliquees, ...}, pour les tests.

Options pour les essais : latence_s (délai avant d'appliquer et de répondre), perte (part des
requêtes perdues : ni appliquées ni répondues), graine (tirage des pertes).
"""
import json
import math
import random
import signal
import sys

from .logique import FauxSport, OdometrieDerivee, PANNES

PERIODE_FILE_S = 0.005          # traitement des requêtes retardées (option latence_s)
PERIODE_ETAT_S = 0.5
ATTENTE_SORTIE_S = 0.5


class Sortie(Exception):
    """Levée par SIGINT ou SIGTERM : le faux G1 publie zéro vers Gazebo, puis quitte."""


def _signal_vers_sortie(numero, _cadre):
    raise Sortie(signal.Signals(numero).name)


def cap_quaternion(q):
    """Cap (lacet) d'un quaternion, en radians."""
    return math.atan2(2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y * q.y + q.z * q.z))


def creer_noeud():
    """Le nœud g1_jumeau (rclpy déjà initialisé)."""
    from geometry_msgs.msg import Twist
    from nav_msgs.msg import Odometry
    from rclpy.clock import Clock, ClockType
    from rclpy.node import Node
    from rclpy.qos import (DurabilityPolicy, qos_profile_sensor_data, QoSProfile,
                           ReliabilityPolicy)
    from std_msgs.msg import String
    from unitree_api.msg import Response
    from unitree_api.msg import Request

    class NoeudJumeau(Node):
        """g1_jumeau : faux service sport, vitesses vers Gazebo, odométrie qui dérive."""

        def __init__(self):
            super().__init__('g1_jumeau')
            self.latence = float(self.declare_parameter('latence_s', 0.0).value)
            self.perte = float(self.declare_parameter('perte', 0.0).value)
            self.tirage = random.Random(int(self.declare_parameter('graine', 0).value))
            frequence = float(self.declare_parameter('frequence_cmd_vel', 20.0).value)
            self.hauteur = float(self.declare_parameter('hauteur_pelvis', 0.75).value)
            echelle = float(self.declare_parameter('derive_echelle', 0.02).value)
            lacet = float(self.declare_parameter('derive_lacet_par_m', 0.01).value)
            panne = self.declare_parameter('panne', 'aucune').value

            self.sport = FauxSport()
            self.sport.changer_panne(panne)
            self.odometrie = OdometrieDerivee(echelle, lacet)
            self.file = []                  # [(échéance murale, requête)] si latence_s > 0
            self.perdues = 0
            self.mural = Clock(clock_type=ClockType.STEADY_TIME)
            self.Response, self.Twist, self.Odometry = Response, Twist, Odometry
            self.String = String

            fiable = QoSProfile(depth=50, reliability=ReliabilityPolicy.RELIABLE,
                                durability=DurabilityPolicy.VOLATILE)
            self.pub_reponse = self.create_publisher(Response, '/api/sport/response', fiable)
            self.pub_vitesse = self.create_publisher(Twist, '/g1_jumeau/cmd_vel', 10)
            self.pub_pelvis = self.create_publisher(
                Odometry, '/state_estimator/odom_pelvis',
                QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE))
            self.pub_etat = self.create_publisher(String, '/g1_jumeau/etat', 10)
            self.create_subscription(Request, '/api/sport/request', self._sur_requete, fiable)
            self.create_subscription(Odometry, '/g1_jumeau/odom', self._sur_verite,
                                     qos_profile_sensor_data)
            self.create_subscription(String, '/g1_jumeau/panne', self._sur_panne,
                                     QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE))
            self.create_timer(1.0 / frequence, self._publier_vitesse, clock=self.mural)
            self.create_timer(PERIODE_ETAT_S, self._publier_etat, clock=self.mural)
            if self.latence > 0:
                self.create_timer(PERIODE_FILE_S, self._vider_file, clock=self.mural)
            self.derniere_vitesse = None
            self._publier_vitesse()          # zéro au lancement
            self.get_logger().info(
                f'faux G1 prêt : /api/sport/request → /g1_jumeau/cmd_vel ({frequence:g} Hz), '
                f'/g1_jumeau/odom → /state_estimator/odom_pelvis (dérive {echelle:g} et '
                f'{lacet:g} rad/m) ; latence {self.latence:g} s, perte {self.perte:g}, '
                f'panne {self.sport.panne}')

        # -------------------------------------------------------- requêtes

        def _sur_requete(self, msg):
            if self.perte > 0 and self.tirage.random() < self.perte:
                self.perdues += 1
                return
            if self.latence > 0:
                self.file.append((self._maintenant() + self.latence, msg))
            else:
                self._traiter(msg)

        def _maintenant(self):
            return self.sport.horloge()

        def _vider_file(self):
            t = self._maintenant()
            prets = [m for echeance, m in self.file if echeance <= t]
            self.file = [(e, m) for e, m in self.file if e > t]
            for msg in prets:
                self._traiter(msg)

        def _traiter(self, msg):
            identite = msg.header.identity
            code = self.sport.traiter(identite.api_id, msg.parameter)
            if code is None:
                return                        # panne muet : ni réponse, ni mouvement
            reponse = self.Response()
            reponse.header.identity.id = identite.id
            reponse.header.identity.api_id = identite.api_id
            reponse.header.status.code = int(code)
            reponse.data = ''
            self.pub_reponse.publish(reponse)
            if code != 0:
                self.get_logger().warning(
                    f'requête {identite.id} (api {identite.api_id}) refusée : code {code}',
                    throttle_duration_sec=2.0)
            self._publier_vitesse()          # la nouvelle consigne part tout de suite

        # -------------------------------------------------------- vitesses vers Gazebo

        def _publier_vitesse(self):
            vx, vy, wz = self.sport.consigne()
            msg = self.Twist()
            msg.linear.x, msg.linear.y, msg.angular.z = float(vx), float(vy), float(wz)
            self.pub_vitesse.publish(msg)
            self.derniere_vitesse = (vx, vy, wz)

        def publier_zero(self):
            """Zéro vers Gazebo (sortie) ; attend l'accusé de réception, 0,5 s au plus."""
            from rclpy.duration import Duration
            self.sport.consigne_en_cours, self.sport.fin = (0.0, 0.0, 0.0), None
            for _ in range(3):
                self._publier_vitesse()
            try:
                self.pub_vitesse.wait_for_all_acked(Duration(seconds=ATTENTE_SORTIE_S))
            except Exception:       # noqa: B902 (selon le RMW, l'accusé peut manquer)
                pass

        # -------------------------------------------------------- odométrie du robot

        def _sur_verite(self, verite):
            p = verite.pose.pose.position
            cap = cap_quaternion(verite.pose.pose.orientation)
            x, y, theta = self.odometrie.mettre_a_jour(p.x, p.y, cap)
            msg = self.Odometry()
            msg.header.stamp = verite.header.stamp
            msg.header.frame_id = 'odom'
            msg.child_frame_id = 'pelvis'
            msg.pose.pose.position.x, msg.pose.pose.position.y = x, y
            msg.pose.pose.position.z = self.hauteur
            msg.pose.pose.orientation.z = math.sin(theta / 2.0)
            msg.pose.pose.orientation.w = math.cos(theta / 2.0)
            msg.twist.twist = verite.twist.twist
            self.pub_pelvis.publish(msg)

        # -------------------------------------------------------- pannes et état

        def _sur_panne(self, msg):
            try:
                self.sport.changer_panne(msg.data)
            except ValueError as erreur:
                self.get_logger().warning(f'/g1_jumeau/panne : {erreur}')
                return
            self.get_logger().info(f'panne : {self.sport.panne}')
            self._publier_vitesse()
            self._publier_etat()

        def _publier_etat(self):
            vx, vy, wz = self.sport.consigne()
            etat = {'version': 1, 'panne': self.sport.panne,
                    'consigne': {'vx': vx, 'vy': vy, 'wz': wz},
                    'reste_s': round(self.sport.reste(), 3), 'requetes': self.sport.requetes,
                    'appliquees': self.sport.appliquees, 'reponses': self.sport.reponses,
                    'perdues': self.perdues, 'latence_s': self.latence, 'perte': self.perte,
                    'pannes_possibles': list(PANNES)}
            self.pub_etat.publish(self.String(data=json.dumps(etat)))

    return NoeudJumeau()


def main(args=None):
    import rclpy
    from rclpy.executors import ExternalShutdownException, SingleThreadedExecutor
    from rclpy.signals import SignalHandlerOptions

    # Nos propres gestionnaires : rclpy fermerait le contexte avant que zéro ne parte vers Gazebo
    rclpy.init(args=args, signal_handler_options=SignalHandlerOptions.NO)
    signal.signal(signal.SIGINT, _signal_vers_sortie)
    signal.signal(signal.SIGTERM, _signal_vers_sortie)
    try:
        noeud = creer_noeud()
    except ValueError as erreur:
        print(f'g1_jumeau : réglage refusé : {erreur}', file=sys.stderr)
        rclpy.try_shutdown()
        return 1
    except Sortie:
        rclpy.try_shutdown()
        return 0
    executeur = SingleThreadedExecutor()
    executeur.add_node(noeud)
    try:
        executeur.spin()
    except (Sortie, KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        try:
            noeud.publier_zero()
            noeud.get_logger().info('faux G1 arrêté (zéro envoyé à Gazebo)')
        except Exception as erreur:     # noqa: B902 (contexte déjà fermé : rien à faire)
            print(f'g1_jumeau : zéro de sortie impossible : {erreur}', file=sys.stderr)
        executeur.shutdown(timeout_sec=1.0)
        noeud.destroy_node()
        rclpy.try_shutdown()
    return 0


if __name__ == '__main__':
    sys.exit(main())
