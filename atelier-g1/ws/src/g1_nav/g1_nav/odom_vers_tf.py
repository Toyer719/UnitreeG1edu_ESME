"""
Relais de position et repérage du robot (section 10.5 du plan) : nœud odom_vers_tf.

Il fait le lien entre ce que publie le G1 (ou le faux G1 de la répétition) et ce qu'attend Nav2 :

  entrées  /state_estimator/odom_pelvis   odométrie locale du robot (paramètre odometrie)
           /unitree/slam_relocation/odom  relocalisation d'Unitree, après 1804 (relocalisation)
           /unitree/slam_relocation/points  nuage d'Unitree, dans le repère de sa carte (nuage)
           /reperage/demander             demande de repérage (JSON, schéma demande_reperage)
           /api/slam_operate/response     réponses du service slam_operate
  sorties  TF odom → base_link et /odom   odométrie locale ramenée au sol
           TF map → odom                  correction de la relocalisation, 20 Hz, une fois repéré
           TF map → carte_unitree         statique : origine de la carte d'Unitree (pour RViz)
           /points                        le nuage, ramené dans le repère lidar (10 Hz au plus)
           /reperage/etat                 état du repérage (JSON, schéma etat_reperage), 5 Hz
           /api/slam_operate/request      commande 1804 (unitree_api/Request)

Avec localisation:=amcl (secours, notre carte et le LiDAR), le repérage publie /initialpose et
suit /amcl_pose ; AMCL publie lui-même map → odom, et le relais garde odom → base_link, /odom et
/points (nuage du capteur recopié dans le repère lidar). Pendant le repérage, le robot ne bouge
pas (le pont l'en empêche) : le relais demande donc à AMCL des mises à jour sans mouvement
(/request_nomotion_update, FREQUENCE_AMCL_HZ), pour que son nuage de particules se resserre.

La logique (repères, délais, échecs) est dans reperage.py, sans ROS. Paramètres principaux :
localisation (unitree ou amcl), repere_unitree [x, y, theta], carte (nom du .pcd pour 1804),
horodatage (local : l'heure du relais, ou message), points_repere (auto, carte ou capteur),
pose_suivi [x, y, theta], pose_capteur [x, y, z, roulis, tangage, lacet], z_carte_unitree.

  ros2 run g1_nav odom_vers_tf --ros-args -p repere_unitree:=[2.5,10.0,0.0] -p carte:=rdc.pcd
"""
import json
import math
import signal
import sys
import time

from g1_nav import nuages
from g1_nav.reperage import pose_au_sol, Reperage, ReperageAmcl

try:
    import rclpy
    from rclpy.node import Node
except ImportError:      # conversion seule, sans ROS (tests)
    rclpy = None
    Node = object

# Nuage d'Unitree : frame_id qui désignent le repère de sa carte (avec points_repere:=auto)
REPERES_CARTE = ('map', 'odom', 'world', 'camera_init')
FREQUENCE_TF_HZ = 20.0
FREQUENCE_ETAT_HZ = 5.0
FREQUENCE_NUAGE_MAX_HZ = 10.0
FREQUENCE_AMCL_HZ = 4.0          # mises à jour d'AMCL sans mouvement, pendant le repérage
# base_link → lidar du robot proxy (model.sdf de g1_proxy), si /tf_static ne le donne pas
POSE_LIDAR_DEFAUT = [-0.004, 0.0, 1.245]


def odom_vers_transformation(odom, transformation, repere_odom='odom', repere_robot='base_link'):
    """Pose d'un nav_msgs/Odometry → geometry_msgs/TransformStamped, ramenée au sol."""
    transformation.header.stamp = odom.header.stamp
    transformation.header.frame_id = repere_odom
    transformation.child_frame_id = repere_robot
    p = odom.pose.pose.position
    x, y, cap = pose_au_sol(p.x, p.y, odom.pose.pose.orientation)
    remplir_transformation(transformation, (x, y, cap))
    return transformation


def remplir_transformation(transformation, pose, z=0.0):
    """Pose au sol (x, y, cap) → champ transform d'un TransformStamped."""
    t = transformation.transform
    t.translation.x, t.translation.y, t.translation.z = float(pose[0]), float(pose[1]), float(z)
    t.rotation.x, t.rotation.y = 0.0, 0.0
    t.rotation.z, t.rotation.w = math.sin(pose[2] / 2), math.cos(pose[2] / 2)
    return transformation


def secondes(horodatage):
    """Convertit un builtin_interfaces/Time : float, ou None s'il est nul."""
    s = horodatage.sec + horodatage.nanosec * 1e-9
    return s if s > 0.0 else None


class OdomVersTf(Node):
    """Relais odométrie → TF et /odom, correction map → odom, nuage → /points, repérage."""

    def __init__(self):
        super().__init__('odom_vers_tf')
        from geometry_msgs.msg import PoseWithCovarianceStamped, TransformStamped
        from nav_msgs.msg import Odometry
        from rclpy.clock import Clock, ClockType
        from rclpy.qos import (DurabilityPolicy, QoSProfile, ReliabilityPolicy,
                               qos_profile_sensor_data)
        from sensor_msgs.msg import PointCloud2
        from std_msgs.msg import String
        from tf2_msgs.msg import TFMessage
        import tf2_ros

        p = self.declare_parameter
        self.localisation = p('localisation', 'unitree').value
        if self.localisation not in ('unitree', 'amcl'):
            raise ValueError(f'localisation « {self.localisation} » inconnue : unitree ou amcl')
        sujet_reloc = p('relocalisation', '/unitree/slam_relocation/odom').value
        sujet_odom = p('odometrie', '/state_estimator/odom_pelvis').value
        sujet_nuage = p('nuage', '/unitree/slam_relocation/points').value
        repere = [float(v) for v in p('repere_unitree', [0.0, 0.0, 0.0]).value]
        carte = p('carte', '').value or None
        self.lieu = p('lieu', '').value
        self.etage = p('etage', '').value
        self.horodatage = p('horodatage', 'local').value
        self.points_repere = p('points_repere', 'auto').value
        pose_suivi = [float(v) for v in p('pose_suivi', [0.0, 0.0, 0.0]).value]
        pose_capteur = [float(v) for v in p('pose_capteur', [0.0] * 6).value]
        self.z_carte_unitree = float(p('z_carte_unitree', 0.0).value)
        self.pose_lidar = [float(v) for v in p('pose_lidar', POSE_LIDAR_DEFAUT).value]
        self.repere_carte = p('repere_carte', 'map').value
        self.repere_odom = p('repere_odom', 'odom').value
        self.repere_robot = p('repere_robot', 'base_link').value
        self.repere_lidar = p('repere_lidar', 'lidar').value
        self.repere_carte_unitree = p('repere_carte_unitree', 'carte_unitree').value
        sujet_requete = p('sujet_requete', '/api/slam_operate/request').value
        sujet_reponse = p('sujet_reponse', '/api/slam_operate/response').value
        if self.horodatage not in ('local', 'message'):
            raise ValueError(f'horodatage « {self.horodatage} » inconnu : local ou message')
        if self.points_repere not in ('auto', 'carte', 'capteur'):
            raise ValueError(f'points_repere « {self.points_repere} » inconnu : auto, carte '
                             'ou capteur')
        if len(repere) != 3 or len(pose_suivi) != 3 or len(pose_capteur) != 6:
            raise ValueError('repere_unitree et pose_suivi : [x, y, theta] ; pose_capteur : '
                             '[x, y, z, roulis, tangage, lacet]')

        self.TransformStamped, self.String, self.Odometry = TransformStamped, String, Odometry
        self.PoseWithCovarianceStamped = PoseWithCovarianceStamped
        self.m_capteur = nuages.matrice(*pose_capteur)
        self.m_base_lidar = nuages.matrice(*self.pose_lidar[:3])
        self.lidar_par_tf = False
        self.repere_reloc = 'map'
        self._dernier_nuage = 0.0
        self._derniere_odom = None          # (pose au sol, msg) de la dernière odométrie locale
        self._stamps = {}                   # dernier horodatage envoyé, par transformation
        self._publie_changements = -1
        if self.localisation == 'unitree':
            self.reperage = Reperage(repere, carte, pose_suivi)
        else:
            self.reperage = ReperageAmcl(repere)

        self.diffuseur = tf2_ros.TransformBroadcaster(self)
        self.diffuseur_statique = tf2_ros.StaticTransformBroadcaster(self)
        self.pub_odom = self.create_publisher(Odometry, '/odom', 10)
        self.pub_points = self.create_publisher(PointCloud2, '/points', qos_profile_sensor_data)
        self.pub_etat = self.create_publisher(String, '/reperage/etat', 10)
        capteur = qos_profile_sensor_data
        self.create_subscription(Odometry, sujet_odom, self._sur_odometrie, capteur)
        self.create_subscription(PointCloud2, sujet_nuage, self._sur_nuage, capteur)
        self.create_subscription(String, '/reperage/demander', self._sur_demande, 10)
        statique = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE,
                              durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.create_subscription(TFMessage, '/tf_static', self._sur_tf_statique, statique)
        if self.localisation == 'unitree':
            try:
                from unitree_api.msg import Request, Response
            except ImportError:
                raise RuntimeError('les messages unitree_api sont introuvables : chargez '
                                   '~/robot-g1/setup/env.sh (ou l\'image g1-jetson)') from None
            self.Request = Request
            requetes = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE,
                                  durability=DurabilityPolicy.VOLATILE)
            self.pub_requete = self.create_publisher(Request, sujet_requete, requetes)
            self.create_subscription(Response, sujet_reponse, self._sur_reponse, capteur)
            self.create_subscription(Odometry, sujet_reloc, self._sur_relocalisation, capteur)
            self._publier_carte_unitree(repere)
        else:
            from std_srvs.srv import Empty
            self.pub_initiale = self.create_publisher(PoseWithCovarianceStamped,
                                                      '/initialpose', 10)
            self.create_subscription(PoseWithCovarianceStamped, '/amcl_pose', self._sur_amcl, 10)
            self.client_amcl = self.create_client(Empty, '/request_nomotion_update')
            self.DemandeVide = Empty.Request
        # Horloge murale : les délais du repérage ne dépendent pas du temps simulé
        mural = Clock(clock_type=ClockType.STEADY_TIME)
        self.create_timer(1.0 / FREQUENCE_TF_HZ, self._sur_minuterie, clock=mural)
        self.create_timer(1.0 / FREQUENCE_ETAT_HZ, self._publier_etat, clock=mural)
        if self.localisation == 'amcl':
            self.create_timer(1.0 / FREQUENCE_AMCL_HZ, self._affiner_amcl, clock=mural)
        self.get_logger().info(
            f'relais prêt : localisation {self.localisation}, odométrie {sujet_odom}, '
            + (f'relocalisation {sujet_reloc}, carte {carte or "aucune"}, '
               if self.localisation == 'unitree' else '')
            + f'nuage {sujet_nuage} → /points, repère d\'Unitree ({repere[0]:g} ; {repere[1]:g} ; '
              f'{repere[2]:g}). En attente de « Repérer le robot » (/reperage/demander).')

    # ------------------------------------------------------------ horodatage

    def _heure(self, msg_stamp, cle=None):
        """
        Horodatage à mettre : l'heure du relais (local) ou celle du message.

        Avec cle : None si l'heure n'a pas avancé depuis le dernier envoi de cette transformation
        (tf2 refuse les horodatages répétés).
        """
        local = self.horodatage == 'local' or msg_stamp is None
        stamp = self.get_clock().now().to_msg() if local else msg_stamp
        if cle is not None:
            valeur = (stamp.sec, stamp.nanosec)
            if self._stamps.get(cle) is not None and valeur <= self._stamps[cle]:
                return None
            self._stamps[cle] = valeur
        return stamp

    # ------------------------------------------------------------ réception

    def _sur_odometrie(self, msg):
        p = msg.pose.pose.position
        pose = pose_au_sol(p.x, p.y, msg.pose.pose.orientation)
        self._derniere_odom = pose
        self.reperage.sur_odometrie(pose, secondes(msg.header.stamp))
        stamp = self._heure(msg.header.stamp)
        sortie = self.Odometry()
        sortie.header.stamp = stamp
        sortie.header.frame_id = self.repere_odom
        sortie.child_frame_id = self.repere_robot
        q = sortie.pose.pose.orientation
        sortie.pose.pose.position.x, sortie.pose.pose.position.y = pose[0], pose[1]
        q.z, q.w = math.sin(pose[2] / 2), math.cos(pose[2] / 2)
        sortie.pose.covariance = msg.pose.covariance
        sortie.twist = msg.twist
        self.pub_odom.publish(sortie)
        stamp_tf = self._heure(msg.header.stamp, 'odom')
        if stamp_tf is not None:
            t = self.TransformStamped()
            t.header.stamp = stamp_tf
            t.header.frame_id, t.child_frame_id = self.repere_odom, self.repere_robot
            self.diffuseur.sendTransform(remplir_transformation(t, pose))

    def _sur_relocalisation(self, msg):
        p = msg.pose.pose.position
        try:
            pose = pose_au_sol(p.x, p.y, msg.pose.pose.orientation)
        except ValueError:            # quaternion nul : message inutilisable
            return
        if not all(math.isfinite(v) for v in pose):
            return
        self.repere_reloc = msg.header.frame_id or self.repere_reloc
        avant = self.reperage.changements
        self.reperage.sur_relocalisation(pose, secondes(msg.header.stamp),
                                         list(msg.pose.covariance))
        if self.reperage.changements != avant:
            self._publier_etat()

    def _sur_amcl(self, msg):
        p = msg.pose.pose.position
        pose = pose_au_sol(p.x, p.y, msg.pose.pose.orientation)
        avant = self.reperage.changements
        self.reperage.sur_pose_amcl(pose, list(msg.pose.covariance))
        if self.reperage.changements != avant:
            self._publier_etat()

    def _affiner_amcl(self):
        """Pendant le repérage par AMCL : une mise à jour du filtre sans mouvement du robot."""
        if self.reperage.etat()['etat'] == 'en_cours' and self.client_amcl.service_is_ready():
            self.client_amcl.call_async(self.DemandeVide())

    def _sur_demande(self, msg):
        try:
            demande = json.loads(msg.data)
        except ValueError:
            demande = None
        if not isinstance(demande, dict):
            demande = {'texte': msg.data}
        requete = self.reperage.demander(demande)
        if requete is not None and self.localisation == 'unitree':
            from atelier.scan.slam_client import remplir_requete_ros
            self.pub_requete.publish(remplir_requete_ros(self.Request(), requete['api_id'],
                                                         requete['parameter'], requete['id']))
            u = requete['pose_unitree']
            self.get_logger().info(f'repérage demandé ({demande.get("id")}) : 1804 envoyée, '
                                   f'pose ({u[0]:.2f} ; {u[1]:.2f} ; {u[2]:.2f}) dans le '
                                   'repère d\'Unitree')
        elif requete is not None:
            m = self.PoseWithCovarianceStamped()
            m.header.stamp = self.get_clock().now().to_msg()
            m.header.frame_id = self.repere_carte
            x, y, theta = requete['pose']
            m.pose.pose.position.x, m.pose.pose.position.y = x, y
            q = m.pose.pose.orientation
            q.z, q.w = math.sin(theta / 2), math.cos(theta / 2)
            m.pose.covariance = [float(v) for v in requete['covariance']]
            self.pub_initiale.publish(m)
            self.get_logger().info(f'repérage demandé ({demande.get("id")}) : pose initiale '
                                   f'd\'AMCL ({x:.2f} ; {y:.2f} ; {theta:.2f})')
        self._publier_etat()

    def _sur_reponse(self, msg):
        if self.reperage.sur_reponse(msg.header.identity.id, msg.header.status.code, msg.data):
            self.get_logger().info('réponse de slam_operate à 1804 : code '
                                   f'{msg.header.status.code}, {msg.data[:200]}')
            self._publier_etat()

    def _sur_tf_statique(self, msg):
        for t in msg.transforms:
            if t.header.frame_id == self.repere_robot and t.child_frame_id == self.repere_lidar:
                tr, q = t.transform.translation, t.transform.rotation
                self.m_base_lidar = nuages.matrice_quaternion((tr.x, tr.y, tr.z),
                                                              (q.x, q.y, q.z, q.w))
                if not self.lidar_par_tf:
                    self.get_logger().info(f'{self.repere_robot} → {self.repere_lidar} lu sur '
                                           f'/tf_static : ({tr.x:.3f} ; {tr.y:.3f} ; '
                                           f'{tr.z:.3f})')
                self.lidar_par_tf = True

    def _sur_nuage(self, msg):
        maintenant = time.monotonic()
        if maintenant - self._dernier_nuage < 1.0 / FREQUENCE_NUAGE_MAX_HZ - 0.005:
            return
        dans_la_carte = self.points_repere == 'carte' or (
            self.points_repere == 'auto'
            and msg.header.frame_id in REPERES_CARTE + (self.repere_reloc,))
        try:
            points = nuages.lire_xyz(msg)
        except ValueError:
            return
        if dans_la_carte:
            correction = self.reperage.map_odom()
            if correction is None or self._derniere_odom is None:
                return                    # pas encore repéré : on ne sait pas où est le robot
            m_carte_lidar = (nuages.matrice_sol(correction)
                             @ nuages.matrice_sol(self._derniere_odom) @ self.m_base_lidar)
            m_carte_unitree = nuages.matrice_sol(self.reperage.repere, self.z_carte_unitree)
            points = nuages.appliquer(nuages.inverser(m_carte_lidar) @ m_carte_unitree, points)
        else:
            points = nuages.appliquer(self.m_capteur, points)
        self._dernier_nuage = maintenant
        self.pub_points.publish(nuages.creer_nuage(points, self.repere_lidar,
                                                   self._heure(msg.header.stamp)))

    # ------------------------------------------------------------ publications

    def _publier_carte_unitree(self, repere):
        t = self.TransformStamped()
        t.header.stamp = self.get_clock().now().to_msg()
        t.header.frame_id, t.child_frame_id = self.repere_carte, self.repere_carte_unitree
        self.diffuseur_statique.sendTransform(
            remplir_transformation(t, repere, self.z_carte_unitree))

    def _sur_minuterie(self):
        self.reperage.pas()
        correction = self.reperage.map_odom()
        if correction is not None:
            stamp = self._heure(None, 'map_odom')
            if stamp is not None:
                t = self.TransformStamped()
                t.header.stamp = stamp
                t.header.frame_id, t.child_frame_id = self.repere_carte, self.repere_odom
                self.diffuseur.sendTransform(remplir_transformation(t, correction))
        if self.reperage.changements != self._publie_changements:
            self._publier_etat()

    def _publier_etat(self):
        self._publie_changements = self.reperage.changements
        texte = json.dumps(self.reperage.etat(), ensure_ascii=False)
        self.pub_etat.publish(self.String(data=texte))


def main(args=None):
    from rclpy.executors import ExternalShutdownException

    rclpy.init(args=args)
    try:
        noeud = OdomVersTf()
    except Exception as e:     # paramètre faux, messages absents : message clair, sans trace
        print(f'odom_vers_tf : {e}', file=sys.stderr)
        rclpy.try_shutdown()
        return 1
    try:
        rclpy.spin(noeud)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        signal.signal(signal.SIGINT, signal.SIG_IGN)     # un second Ctrl+C ne coupe pas l'arrêt
        noeud.destroy_node()
        rclpy.try_shutdown()
    return 0


if __name__ == '__main__':
    sys.exit(main())
