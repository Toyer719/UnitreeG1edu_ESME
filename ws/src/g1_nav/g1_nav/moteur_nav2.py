"""
MoteurNav2 : le Moteur du guide qui passe par Nav2 (interface : moteurs.py, section 4.6).

Il envoie toutes les poses d'un coup à Nav2 avec nav2_simple_commander (goThroughPoses,
action navigate_through_poses de bt_navigator). Nav2 planifie (Smac 2D), suit le chemin
(MPPI) et évite les obstacles proches ; le guide surveille le progrès et décide des détours.

reste_m se calcule avec le retour de Nav2 : de la position du robot (current_pose) à la
dernière pose, en ligne droite par les poses que Nav2 n'a pas encore passées
(number_of_poses_remaining ; une pose est passée à 1,5 m, voir config/naviguer_par_poses.xml).

Il faut que rclpy soit initialisé avant de créer le moteur : MoteurNav2 crée son propre
nœud (BasicNavigator), qu'il fait tourner lui-même dans ses méthodes.
"""
import math

from atelier.lieu.conversions import cap_vers_quaternion
from g1_nav.moteurs import etat_repos, Moteur, SuiviProgres, verifier_poses

# Attente maximale du serveur d'action de Nav2 et de la réponse à une annulation, en secondes
DELAI_SERVEUR_S = 0.5
DELAI_ANNULATION_S = 0.5


class MoteurNav2(Moteur):
    """Moteur qui passe par Nav2 : goThroughPoses de nav2_simple_commander."""

    def __init__(self, navigateur=None, repere='map', attendre=None):
        """
        Prépare le moteur.

        navigateur : un BasicNavigator (créé ici par défaut) ; les tests passent un faux ;
        repere     : repère des poses (map) ;
        attendre   : fonction (futur, délai_s) qui fait tourner le navigateur jusqu'au futur
                     ou au délai ; par défaut rclpy.spin_until_future_complete.
        """
        if navigateur is None:
            from nav2_simple_commander.robot_navigator import BasicNavigator
            navigateur = BasicNavigator(node_name='guide_nav2')
        self.nav = navigateur
        self.repere = repere
        self._attendre = attendre or self._attendre_rclpy
        self._suivi = SuiviProgres()
        self._etat = etat_repos()
        self._poses = []
        self._en_tache = False

    # ------------------------------------------------------------ interface Moteur

    def demarrer(self, poses):
        poses = verifier_poses(poses)
        if not self.nav.nav_through_poses_client.wait_for_server(timeout_sec=DELAI_SERVEUR_S):
            self.nav.error('Nav2 ne répond pas (navigate_through_poses) : est-il lancé ?')
            return self._refuser()
        self.nav.feedback = None      # oublie le retour d'un déplacement précédent
        if not self.nav.goThroughPoses([self._pose_stampee(p) for p in poses]):
            return self._refuser()
        self._poses = poses
        self._en_tache = True
        self._suivi.effacer()
        self._etat = dict(etat_repos(), en_cours=True)
        return True

    def annuler(self):
        if self._en_tache and self.nav.goal_handle is not None:
            futur = self.nav.goal_handle.cancel_goal_async()
            self._attendre(futur, DELAI_ANNULATION_S)
            # On attend aussi la fin du but annulé : un nouveau but envoyé pendant que
            # bt_navigator s'arrête serait abandonné par Nav2 (vu dans Gazebo)
            if self.nav.result_future is not None:
                self._attendre(self.nav.result_future, DELAI_ANNULATION_S)
        self.nav.result_future = None
        self._en_tache = False
        self._etat = etat_repos()

    def etat(self):
        if not self._en_tache:
            return dict(self._etat)
        if self.nav.isTaskComplete():
            from nav2_simple_commander.robot_navigator import TaskResult
            self._en_tache = False
            if self.nav.getResult() == TaskResult.SUCCEEDED:
                self._etat = dict(etat_repos(), arrive=True, reste_m=0.0)
            else:
                self._etat = dict(etat_repos(), echec=True)
            return dict(self._etat)
        reste = self._reste(self.nav.getFeedback())
        self._suivi.noter(reste)
        self._etat.update(reste_m=reste, progresse=self._suivi.progresse())
        return dict(self._etat)

    # ------------------------------------------------------------ interne

    def _refuser(self):
        self._en_tache = False
        self._etat = dict(etat_repos(), echec=True)
        return False

    def _pose_stampee(self, pose):
        """(x, y, theta) → PoseStamped dans le repère map, à l'instant 0 (le plus récent)."""
        from geometry_msgs.msg import PoseStamped
        x, y, theta = pose
        msg = PoseStamped()
        msg.header.frame_id = self.repere
        msg.pose.position.x, msg.pose.position.y = float(x), float(y)
        q = msg.pose.orientation
        q.x, q.y, q.z, q.w = cap_vers_quaternion(theta)
        return msg

    def _reste(self, retour):
        """
        Distance restante : de la position du robot aux poses restantes, en ligne droite.

        Les couloirs sont droits (section 4.1) : cette distance baisse régulièrement quand le
        robot avance. Celle de Nav2 (distance_remaining) suit le chemin planifié, qui change à
        chaque nouveau calcul : elle peut remonter alors que le robot avance bien.
        """
        if retour is None:
            return None
        n = max(1, int(retour.number_of_poses_remaining))
        restantes = self._poses[-n:]
        p = retour.current_pose.pose.position
        points = [(p.x, p.y)] + [(x, y) for x, y, _ in restantes]
        return sum(math.dist(a, b) for a, b in zip(points, points[1:]))

    def _attendre_rclpy(self, futur, delai_s):
        import rclpy
        rclpy.spin_until_future_complete(self.nav, futur, timeout_sec=delai_s)
