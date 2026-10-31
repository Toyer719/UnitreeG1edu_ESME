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
      appliquees, ..., robot}, pour les tests.

Vague 4 (section 11.5 du plan), le faux G1 étendu (robot.py) :
  /api/sport/request : aussi les modes (7001, 7101 : 0, 1, 3, 500 puis 501, 702 puis 501, 706),
      les danses (7100, 7101 550000 + n, retour au mode d'avant), les tâches (7106), avec les
      refus réalistes (7301, 7302, 7303) ; réponses avec leur data (7001 : {"data": mode}) ;
  /api/arm/request → /api/arm/response : gestes (7106, 7401, 7402, 7404, 7400), liste (7107) ;
  /api/voice/request → /api/voice/response : TTS (1001), volume (1005, 1006), LED (1010) ;
  /arm_sdk (unitree_hg/LowCmd) reçu et vérifié (poids, rampes, limites, vitesses, taille,
      jambes) ; /lowstate (unitree_hg/LowState, 50 Hz) : bras qui suivent les ordres pondérés ;
  /lf/bmsstate (unitree_hg/BmsState, 1 Hz) : batterie simulée.
  /api/videohub/request → /api/videohub/response : caméra de la tête (GetImageSample, 1001), une
      image de test JPEG dans binary à chaque demande (camera.py, section 11.13) ; rien en panne
      muet.
Paramètres en plus : fsm_depart (501 : en marche), echelle_danses (1,0).

Vague 5 (section 12.6 du plan), fidèle au vrai G1 du 27/10 :
  - 7105 hors marche (assis, pas démarré...) : code 0 sans bouger (hors_marche:=ignorer, défaut),
    ou 7301 (hors_marche:=refuser, l'ancien faux G1) ; en course (802), 7105 est appliqué ;
  - seuil de marche : seuil_marche_m_s (0,15, sur la norme de vx, vy) et seuil_rotation_rad_s
    (0,2) : en dessous, 7105 est accepté mais le robot ne bouge pas (0 : pas de seuil) ;
  - /g1_jumeau/mode (std_msgs/Int32, fiable) : sujet d'essai, le mode changé d'un coup (comme à la
    télécommande : 3 assis, 802 course, 501 marche...), lu ensuite par 7001.

Options pour les essais : latence_s (délai avant d'appliquer et de répondre), perte (part des
requêtes perdues : ni appliquées ni répondues), graine (tirage des pertes).
"""
from array import array
import json
import math
import random
import signal
import sys

from .camera import FausseCamera
from .logique import FauxSport, OdometrieDerivee, PANNES
from .robot import BrasSimules, FauxG1, FSM_MARCHE

# Seuil de marche du faux G1 (vague 5, section 12.6 du plan) : le 27/10, le vrai G1 ne faisait
# aucun pas à 0,1 m/s et marchait à 0,2 m/s ; 0,15 est entre les deux (sur la norme de vx, vy).
# Le seuil de rotation est inconnu (à mesurer à la séance 2) ; 0,2 rad/s reste sous le minimum
# de rotation du pont (0,3). Le pont monte ses consignes au-dessus : la répétition marche, et une
# consigne trop petite qui passerait sans le pont ne ferait rien, comme sur le vrai robot.
SEUIL_MARCHE_M_S = 0.15
SEUIL_ROTATION_RAD_S = 0.2

SERVICES = ('sport', 'arm', 'voice')
PERIODE_LOWSTATE_S = 0.02
PERIODE_BATTERIE_S = 1.0

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
    from std_msgs.msg import Int32, String
    from unitree_api.msg import Response
    from unitree_api.msg import Request
    from unitree_hg.msg import BmsState, LowCmd, LowState

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
            fsm_depart = int(self.declare_parameter('fsm_depart', FSM_MARCHE).value)
            echelle_danses = float(self.declare_parameter('echelle_danses', 1.0).value)
            hors_marche = str(self.declare_parameter('hors_marche', 'ignorer').value)
            seuil_lin = float(self.declare_parameter('seuil_marche_m_s', SEUIL_MARCHE_M_S).value)
            seuil_rot = float(self.declare_parameter('seuil_rotation_rad_s',
                                                     SEUIL_ROTATION_RAD_S).value)

            # ValueError (réglage refusé, message en français) : le nœud ne démarre pas
            self.sport = FauxSport(seuil_lin=seuil_lin, seuil_rot=seuil_rot)
            self.sport.changer_panne(panne)
            self.robot = FauxG1(self.sport, fsm=fsm_depart, echelle_danses=echelle_danses,
                                hors_marche=hors_marche)
            self.bras = BrasSimules()
            self.LowState, self.BmsState = LowState, BmsState
            self.batterie = 87.0
            self.odometrie = OdometrieDerivee(echelle, lacet)
            self.file = []                  # [(échéance murale, requête)] si latence_s > 0
            self.perdues = 0
            self.mural = Clock(clock_type=ClockType.STEADY_TIME)
            self.Response, self.Twist, self.Odometry = Response, Twist, Odometry
            self.String = String

            fiable = QoSProfile(depth=50, reliability=ReliabilityPolicy.RELIABLE,
                                durability=DurabilityPolicy.VOLATILE)
            self.pubs_reponse = {s: self.create_publisher(Response, f'/api/{s}/response', fiable)
                                 for s in SERVICES}
            self.pub_reponse = self.pubs_reponse['sport']
            self.pub_vitesse = self.create_publisher(Twist, '/g1_jumeau/cmd_vel', 10)
            self.pub_pelvis = self.create_publisher(
                Odometry, '/state_estimator/odom_pelvis',
                QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE))
            self.pub_etat = self.create_publisher(String, '/g1_jumeau/etat', 10)
            for service in SERVICES:
                self.create_subscription(Request, f'/api/{service}/request',
                                         self._recepteur(service), fiable)
            # caméra de la tête (Vue du robot de l'onglet Pilotage) : une image de test par demande
            self.camera = FausseCamera()
            self.pub_video = self.create_publisher(Response, '/api/videohub/response', fiable)
            self.create_subscription(Request, '/api/videohub/request', self._sur_video, fiable)
            self.create_subscription(LowCmd, '/arm_sdk', self._sur_arm_sdk,
                                     QoSProfile(depth=50, reliability=ReliabilityPolicy.RELIABLE))
            self.pub_lowstate = self.create_publisher(LowState, '/lowstate',
                                                      qos_profile_sensor_data)
            self.pub_batterie = self.create_publisher(BmsState, '/lf/bmsstate',
                                                      qos_profile_sensor_data)
            self.create_timer(PERIODE_LOWSTATE_S, self._publier_lowstate, clock=self.mural)
            self.create_timer(PERIODE_BATTERIE_S, self._publier_batterie, clock=self.mural)
            self.create_subscription(Odometry, '/g1_jumeau/odom', self._sur_verite,
                                     qos_profile_sensor_data)
            self.create_subscription(String, '/g1_jumeau/panne', self._sur_panne,
                                     QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE))
            self.create_subscription(Int32, '/g1_jumeau/mode', self._sur_mode,
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
            self.get_logger().info(
                f'mode de départ {fsm_depart} ; 7105 hors marche : {hors_marche} ; seuil de '
                f'marche {seuil_lin:g} m/s et de rotation {seuil_rot:g} rad/s (sous le seuil : '
                'accepté sans bouger, comme le vrai G1)')

        # -------------------------------------------------------- requêtes

        def _recepteur(self, service):
            def recevoir(msg):
                self._sur_requete(msg, service)
            return recevoir

        def _sur_requete(self, msg, service='sport'):
            if self.perte > 0 and self.tirage.random() < self.perte:
                self.perdues += 1
                return
            if self.latence > 0:
                self.file.append((self._maintenant() + self.latence, (msg, service)))
            else:
                self._traiter(msg, service)

        def _maintenant(self):
            return self.sport.horloge()

        def _vider_file(self):
            t = self._maintenant()
            prets = [m for echeance, m in self.file if echeance <= t]
            self.file = [(e, m) for e, m in self.file if e > t]
            for msg, service in prets:
                self._traiter(msg, service)

        def _traiter(self, msg, service='sport'):
            identite = msg.header.identity
            reponse_robot = self.robot.traiter(service, identite.api_id, msg.parameter)
            if reponse_robot is None:
                return                        # panne muet : ni réponse, ni mouvement
            code, data = reponse_robot
            reponse = self.Response()
            reponse.header.identity.id = identite.id
            reponse.header.identity.api_id = identite.api_id
            reponse.header.status.code = int(code)
            reponse.data = str(data)
            self.pubs_reponse[service].publish(reponse)
            if code != 0:
                self.get_logger().warning(
                    f'requête {identite.id} ({service} {identite.api_id}) refusée : code {code}',
                    throttle_duration_sec=2.0)
            elif service != 'sport' or identite.api_id not in (7001, 7105):
                self.get_logger().info(f'{service} {identite.api_id} {msg.parameter[:120]} : 0')
            if service == 'sport':
                self._publier_vitesse()      # la nouvelle consigne part tout de suite

        def _sur_video(self, msg):
            if self.sport.panne == 'muet':
                return
            identite = msg.header.identity
            code, octets = self.camera.traiter(identite.api_id, msg.parameter)
            reponse = self.Response()
            reponse.header.identity.id = identite.id
            reponse.header.identity.api_id = identite.api_id
            reponse.header.status.code = int(code)
            reponse.binary = array('b', octets)
            self.pub_video.publish(reponse)

        # -------------------------------------------------------- bras, /lowstate, batterie

        def _sur_arm_sdk(self, msg):
            q = [m.q for m in msg.motor_cmd]
            kp = [m.kp for m in msg.motor_cmd]
            kd = [m.kd for m in msg.motor_cmd]
            self.robot.arm_sdk.recevoir(q, kp, kd)
            self.bras.ordonner(q[29], q)

        def _publier_lowstate(self):
            angles = self.bras.avancer(self._maintenant(), self.robot.arm_sdk.actif())
            msg = self.LowState()
            for i, q in enumerate(angles):
                msg.motor_state[i].q = float(q)
            msg.mode_machine = 5                 # G1 29 ddl (à vérifier sur le robot)
            self.pub_lowstate.publish(msg)

        def _publier_batterie(self):
            self.batterie = max(5.0, self.batterie - 1.0 / 600.0)      # 1 % toutes les 10 min
            self.pub_batterie.publish(self.BmsState(soc=int(self.batterie)))

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

        def _sur_mode(self, msg):
            try:
                self.robot.changer_mode(int(msg.data))
            except ValueError as erreur:
                self.get_logger().warning(f'/g1_jumeau/mode : {erreur}')
                return
            self.get_logger().info(f'mode changé (sujet d\'essai) : {self.robot.fsm}')
            self._publier_vitesse()
            self._publier_etat()

        def _publier_etat(self):
            vx, vy, wz = self.sport.consigne()
            etat = {'version': 1, 'panne': self.sport.panne,
                    'consigne': {'vx': vx, 'vy': vy, 'wz': wz},
                    'reste_s': round(self.sport.reste(), 3), 'requetes': self.sport.requetes,
                    'appliquees': self.sport.appliquees, 'reponses': self.sport.reponses,
                    'perdues': self.perdues, 'latence_s': self.latence, 'perte': self.perte,
                    'pannes_possibles': list(PANNES),
                    'seuils': {'marche_m_s': self.sport.seuil_lin,
                               'rotation_rad_s': self.sport.seuil_rot},
                    'sous_seuil': self.sport.sous_seuil, 'robot': self.robot.etat()}
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
