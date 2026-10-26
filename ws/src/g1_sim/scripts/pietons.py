#!/usr/bin/env python3
"""
Nœud pietons de g1_sim : conduit les piétons crédibles de la simulation (section 11.3 du plan).

Lancé par simulation.launch.py (pietons:=corps, le défaut), à côté de Gazebo et d'un pont
ros_gz_bridge propre aux piétons. Chaque piéton qui a un corps (corps: true, le défaut) est dans
Gazebo un cylindre solide (atelier.monde.sdf.modele_corps), que ce nœud déplace 20 fois par seconde
en lui donnant sa vitesse (plugin VelocityControl). La logique (horaire, réaction au robot,
consigne externe, murs) est celle d'atelier.monde.foule, sans ROS.

  Sujets écoutés : /pietons/corps/<id>/odom (position vraie de chaque corps, Gazebo),
                   <sujet_robot> (position vraie du robot : /odom, /g1_jumeau/odom en répétition),
                   /pietons/consigne (std_msgs/String JSON : {id, vx, vy, theta?} d'un piéton
                   « pilote: externe », valable 0,5 s), /pietons/reinitialiser (std_msgs/Empty :
                   tous les piétons-corps reviennent à trajet[0] et la scène repart de zéro)
  Sujets publiés : /pietons/corps/<id>/cmd_vel (vers Gazebo), /pietons/etat (std_msgs/String JSON,
                   schéma pietons_etat, 10 Hz : positions et vitesses vraies, repère map)
  Service appelé : /world/<monde>/set_pose (réinitialisation, par le pont des piétons)

Paramètres : monde (fichier .monde.yaml), monde_gz (nom du monde Gazebo), sujet_robot, corps
(ids des piétons-corps séparés par des virgules ; vide : tous ceux du monde qui ont un corps).

Le temps simulé est celui des odométries de Gazebo (horodatage des messages), et non /clock :
s'abonner à /clock (1000 messages par seconde) coûtait la moitié d'un cœur à ce nœud Python. Les
minuteries du nœud (20 Hz et 10 Hz) sont en temps mural ; use_sim_time reste faux.
"""
import json
import math
import signal
import sys
import threading

import rclpy
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from rclpy.executors import ExternalShutdownException, SingleThreadedExecutor
from rclpy.qos import qos_profile_sensor_data
from rclpy.signals import SignalHandlerOptions
from std_msgs.msg import Empty, String

from atelier.lieu import Monde, charger_fichier
from atelier.lieu.passants import FREQUENCE_ETAT_HZ, SUJET_CONSIGNE, SUJET_ETAT
from atelier.monde.foule import Foule, lire_consigne, vitesse_dans_la_carte, vitesse_dans_le_corps
from atelier.monde.sdf import SOL_CORPS, sujets_ros_corps

FREQUENCE_PAS_HZ = 20.0          # les corps sont déplacés 20 fois par seconde (contrat 11.3)
GAIN_LACET = 2.0                 # 1/s : le corps (cylindre) est gardé tourné vers +x
SUJET_REINITIALISER = '/pietons/reinitialiser'


def lacet(q):
    return math.atan2(2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y * q.y + q.z * q.z))


class NoeudPietons:
    """Le nœud ROS 2 autour d'atelier.monde.foule.Foule."""

    def __init__(self, noeud):
        self.noeud = noeud
        p = noeud.declare_parameter
        chemin = p('monde', '').value
        self.monde_gz = p('monde_gz', '').value
        sujet_robot = p('sujet_robot', '/odom').value
        corps = [c.strip() for c in p('corps', '').value.split(',') if c.strip()]
        if not chemin:
            raise RuntimeError('paramètre monde vide : donnez le fichier .monde.yaml')
        monde = Monde.depuis_dict(charger_fichier(chemin, 'monde'))
        self.foule = Foule(monde, corps=corps or None)
        self.verrou = threading.Lock()
        self.mesures = {}            # id → (x, y, vx, vy, lacet) vrais
        self.robot = None            # (x, y, vx, vy) vrais
        self.t_debut_scene = None    # temps simulé du début de la scène (0, ou réinitialisation)
        self.t_precedent = None
        self.reinitialiser_demande = False
        self.horloge_sim = 0.0       # temps simulé : horodatage des odométries de Gazebo
        self.pubs = {}
        for ident in self.foule.passants:
            sujets = sujets_ros_corps(ident)
            self.pubs[ident] = noeud.create_publisher(Twist, sujets['cmd_vel'], 10)
            noeud.create_subscription(Odometry, sujets['odometrie'],
                                      lambda m, i=ident: self._sur_odometrie(i, m),
                                      qos_profile_sensor_data)
        noeud.create_subscription(Odometry, sujet_robot, self._sur_robot, qos_profile_sensor_data)
        noeud.create_subscription(String, SUJET_CONSIGNE, self._sur_consigne, 10)
        noeud.create_subscription(Empty, SUJET_REINITIALISER, self._sur_reinitialiser, 10)
        self.pub_etat = noeud.create_publisher(String, SUJET_ETAT, 10)
        self.client_pose = None
        if self.monde_gz and self.foule.passants:
            from ros_gz_interfaces.srv import SetEntityPose
            self.SetEntityPose = SetEntityPose
            self.client_pose = noeud.create_client(SetEntityPose,
                                                   f'/world/{self.monde_gz}/set_pose')
        noeud.create_timer(1.0 / FREQUENCE_PAS_HZ, self._pas)
        noeud.create_timer(1.0 / FREQUENCE_ETAT_HZ, self._publier_etat)
        noeud.get_logger().info(
            f'pietons : {len(self.foule.passants)} piéton(s)-corps conduits '
            f'({", ".join(self.foule.passants) or "aucun"}), {len(self.foule.acteurs)} <actor>, '
            f'robot sur {sujet_robot}')

    # ------------------------------------------------------------ entrées

    def _horloge(self, entete):
        """Temps simulé : le plus récent horodatage des odométries de Gazebo."""
        t = entete.stamp.sec + entete.stamp.nanosec * 1e-9
        if t > self.horloge_sim:
            self.horloge_sim = t

    def _sur_odometrie(self, ident, m):
        self._horloge(m.header)
        p, t = m.pose.pose, m.twist.twist
        psi = lacet(p.orientation)
        vx, vy = vitesse_dans_la_carte(t.linear.x, t.linear.y, psi)
        with self.verrou:
            self.mesures[ident] = (p.position.x, p.position.y, vx, vy, psi)

    def _sur_robot(self, m):
        self._horloge(m.header)
        p, t = m.pose.pose, m.twist.twist
        vx, vy = vitesse_dans_la_carte(t.linear.x, t.linear.y, lacet(p.orientation))
        with self.verrou:
            self.robot = (p.position.x, p.position.y, vx, vy)

    def _sur_consigne(self, msg):
        try:
            ident, vx, vy, theta = lire_consigne(msg.data)
            with self.verrou:
                self.foule.consigner(ident, vx, vy, theta, self._t_scene())
        except ValueError as erreur:
            self.noeud.get_logger().warning(f'consigne refusée : {erreur}',
                                            throttle_duration_sec=2.0)

    def _sur_reinitialiser(self, _msg):
        self.reinitialiser_demande = True

    # ------------------------------------------------------------ temps

    def _t_sim(self):
        return self.horloge_sim

    def _t_scene(self):
        if self.t_debut_scene is None:
            return 0.0
        return max(0.0, self._t_sim() - self.t_debut_scene)

    # ------------------------------------------------------------ un pas

    def _pas(self):
        t_sim = self._t_sim()
        if t_sim <= 0.0:
            return                       # pas encore d'horloge de Gazebo
        if self.t_debut_scene is None:
            self.t_debut_scene = 0.0     # première scène : au temps simulé 0, comme les <actor>
        if self.reinitialiser_demande:
            self.reinitialiser_demande = False
            self._reinitialiser(t_sim)
        dt = 0.0 if self.t_precedent is None else max(0.0, t_sim - self.t_precedent)
        if self.t_precedent is not None and dt <= 0.0:
            return                       # l'horloge n'a pas avancé (simulation en pause)
        self.t_precedent = t_sim
        with self.verrou:
            positions = {i: m[:2] for i, m in self.mesures.items()}
            lacets = {i: m[4] for i, m in self.mesures.items()}
            commandes = self.foule.pas(t_sim - self.t_debut_scene, min(dt, 0.2), positions,
                                       self.robot)
        for ident, c in commandes.items():
            psi = lacets.get(ident, 0.0)
            vx, vy = vitesse_dans_le_corps(c.vx, c.vy, psi)
            msg = Twist()
            msg.linear.x, msg.linear.y = float(vx), float(vy)
            msg.angular.z = float(-GAIN_LACET * psi)
            self.pubs[ident].publish(msg)

    def _reinitialiser(self, t_sim):
        """Tous les piétons-corps à trajet[0], arrêtés ; la scène repart de zéro."""
        with self.verrou:
            self.foule.reinitialiser()
            self.t_debut_scene = t_sim
        for ident, pub in self.pubs.items():
            pub.publish(Twist())
        if self.client_pose is None:
            return
        for ident, passant in self.foule.passants.items():
            x, y = passant.pieton.trajet[0]
            req = self.SetEntityPose.Request()
            req.entity.name = ident
            req.pose.position.x, req.pose.position.y = float(x), float(y)
            req.pose.position.z = SOL_CORPS
            req.pose.orientation.w = 1.0
            self.client_pose.call_async(req)
        self.noeud.get_logger().info(f'pietons : scène réinitialisée (temps simulé {t_sim:.1f} s)')

    def _publier_etat(self):
        t_sim = self._t_sim()
        if t_sim <= 0.0:
            return
        with self.verrou:
            mesures = {i: m[:4] for i, m in self.mesures.items()}
            message = self.foule.message_etat(t_sim, self._t_scene(), mesures)
        self.pub_etat.publish(String(data=json.dumps(message, ensure_ascii=False)))

    def arreter(self):
        """Corps arrêtés (VelocityControl garde la dernière consigne de Gazebo)."""
        for pub in self.pubs.values():
            try:
                pub.publish(Twist())
            except Exception:  # noqa: BLE001 : on quitte de toute façon
                pass


def main(args=None):
    rclpy.init(args=args, signal_handler_options=SignalHandlerOptions.NO)
    noeud = rclpy.create_node('pietons')
    pietons = NoeudPietons(noeud)
    executeur = SingleThreadedExecutor()
    executeur.add_node(noeud)
    fin = threading.Event()

    def quitter(*_):
        fin.set()

    signal.signal(signal.SIGINT, quitter)
    signal.signal(signal.SIGTERM, quitter)
    try:
        while not fin.is_set() and rclpy.ok():
            executeur.spin_once(timeout_sec=0.1)
    except ExternalShutdownException:
        pass
    finally:
        pietons.arreter()
        # laisse partir les consignes nulles avant de quitter
        for _ in range(3):
            executeur.spin_once(timeout_sec=0.05)
        noeud.destroy_node()
        rclpy.try_shutdown()
    return 0


if __name__ == '__main__':
    sys.exit(main())
