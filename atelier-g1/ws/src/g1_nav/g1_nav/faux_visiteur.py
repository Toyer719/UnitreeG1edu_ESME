r"""
Faux visiteur de la simulation (nœud faux_visiteur, section 11.4 du plan).

Il conduit le piéton « pilote: externe » de la scène (le visiteur) par /pietons/consigne (schéma
pietons_consigne, une consigne de vitesse valable 0,5 s, mécanisme de l'agent Passants, 11.3), en
lisant sa position sur /pietons/etat et celle du robot sur la vérité terrain (/odom en simulation,
/g1_jumeau/odom en répétition). Le corps du piéton, sa collision et sa visibilité au LiDAR sont
ceux des piétons crédibles : le détecteur de personnes le voit comme un vrai visiteur.

Modes, sur /faux_visiteur/mode (std_msgs/String) :
  suivre   il suit le robot à distance_suivi_m (1,2 m) derrière lui, à sa vitesse, en marchant
           sur la trace du robot (le chemin du robot est libre : il ne coupe pas les coins) ;
           quand le robot revient vers lui (demi-tour, retour au point principal), il fait un pas
           de côté (ecart_m) pour le laisser passer, puis le suit de nouveau ;
  trainer  il avance sur la trace à 0,15 m/s : il se laisse distancer ;
  partir   il s'éloigne du robot à 1,0 m/s (avec la carte du lieu : par l'espace libre), jusqu'à
           distance_partir_max_m, puis s'arrête : il sort de la vue du robot ;
  arreter  il s'arrête.
État, pour les essais : /faux_visiteur/etat (std_msgs/String JSON, 2 Hz) {version, mode, visiteur,
robot, distance_m, consigne}.

  ros2 run g1_nav faux_visiteur --ros-args -p visiteur:=visiteur -p verite:=/odom \\
      -p lieu:=demo -p etage:=rdc -p use_sim_time:=true

La logique (FauxVisiteur) n'utilise pas ROS : elle se teste seule.
"""
import json
import math
import sys

MODES = ('suivre', 'trainer', 'partir', 'arreter')
REGLAGES_VISITEUR = {
    'distance_suivi_m': 1.2,        # centre à centre, derrière le robot
    'vitesse_trainer': 0.15,        # m/s
    'vitesse_partir': 1.0,          # m/s
    'vitesse_max': 1.5,             # m/s (plafond de /pietons/consigne)
    'gain': 1.0,                    # suivre : vitesse du robot + gain × (écart à la distance)
    'distance_partir_max_m': 15.0,  # partir : au-delà, il s'arrête
    'longueur_trace_m': 40.0,       # trace du robot gardée
    'rayon_m': 0.3,                 # partir : marge aux murs de la carte
    'ecart_m': 1.0,                 # pas de côté : écart à la ligne du robot qui vient vers lui
    'vitesse_ecart': 0.6,           # m/s
}
PAS_TRACE_M = 0.1                   # un point de trace tous les 10 cm du robot
ATTEINT_M = 0.2                     # point de trace atteint
VITESSE_ROBOT_MIN = 0.05            # m/s : en dessous, le robot est arrêté (pas de direction)
DISTANCE_CROISEMENT_M = 2.5         # le robot qui vient vers le visiteur à moins de cela
RECENT_M = 0.5                      # trace : parmi les points à RECENT_M du plus proche, le récent


class FauxVisiteur:
    """Calcule la vitesse du visiteur selon le mode, la position du robot et sa trace."""

    def __init__(self, carte=None, mode='suivre', **reglages):
        """Prépare le visiteur ; carte : CarteStatique (personnes.py) pour « partir », ou None."""
        self.r = dict(REGLAGES_VISITEUR, **{k: v for k, v in reglages.items() if v is not None})
        self.carte = carte
        self.mode = mode if mode in MODES else 'arreter'
        self.trace = []                # positions successives du robot (x, y)
        self.indice = None             # point de la trace vers lequel marche le visiteur

    def changer_mode(self, mode):
        """Change de mode ; False si le mode est inconnu."""
        mode = str(mode).strip()
        if mode not in MODES:
            return False
        if mode != self.mode and mode in ('suivre', 'trainer'):
            self.indice = None         # il repart du point de la trace le plus proche de lui
        self.mode = mode
        return True

    def noter_robot(self, x, y):
        """Ajoute la position du robot à sa trace (un point tous les PAS_TRACE_M)."""
        if not self.trace or math.dist(self.trace[-1], (x, y)) >= PAS_TRACE_M:
            self.trace.append((float(x), float(y)))
        # trace bornée : on retire le début
        longueur, i = 0.0, len(self.trace) - 1
        while i > 0 and longueur < self.r['longueur_trace_m']:
            longueur += math.dist(self.trace[i], self.trace[i - 1])
            i -= 1
        if i > 0:
            del self.trace[:i]
            self.indice = None if self.indice is None else max(0, self.indice - i)

    def _chemin(self, visiteur, robot):
        """(point visé, longueur du chemin jusqu'au robot) en suivant la trace."""
        if not self.trace:
            return robot, math.dist(visiteur, robot)
        if self.indice is None or self.indice >= len(self.trace):
            # le plus récent parmi les points les plus proches (le robot a pu repasser par là)
            distances = [math.dist(visiteur, p) for p in self.trace]
            proche = min(distances)
            self.indice = max(i for i, d in enumerate(distances) if d <= proche + RECENT_M)
        while self.indice < len(self.trace) - 1 and \
                math.dist(visiteur, self.trace[self.indice]) < ATTEINT_M:
            self.indice += 1
        points = [visiteur] + self.trace[self.indice:] + [robot]
        longueur = sum(math.dist(a, b) for a, b in zip(points, points[1:]))
        vise = self.trace[self.indice]
        if math.dist(visiteur, vise) < ATTEINT_M:
            vise = robot
        return vise, longueur

    def consigne(self, visiteur, robot, vitesse_robot=0.0, deplacement_robot=None):
        """
        Vitesse (vx, vy) du visiteur dans map.

        visiteur, robot : (x, y) ; vitesse_robot : vitesse du robot (m/s) ; deplacement_robot :
        sa vitesse (vx, vy) dans map, pour savoir s'il vient vers le visiteur (pas de côté).
        """
        visiteur, robot = tuple(visiteur[:2]), tuple(robot[:2])
        if self.mode == 'arreter':
            return 0.0, 0.0
        if self.mode == 'partir':
            return self._partir(visiteur, robot)
        cote = self._pas_de_cote(visiteur, robot, deplacement_robot)
        if cote is not None:
            self.indice = None          # ensuite, il reprendra la trace au plus près
            return cote
        vise, longueur = self._chemin(visiteur, robot)
        voulu = self.r['distance_suivi_m']
        if longueur <= voulu or math.dist(visiteur, robot) < voulu - 0.2:
            return 0.0, 0.0
        if self.mode == 'trainer':
            vitesse = self.r['vitesse_trainer']
        else:
            vitesse = abs(vitesse_robot) + self.r['gain'] * (longueur - voulu)
        vitesse = max(0.0, min(self.r['vitesse_max'], vitesse))
        return _vers(visiteur, vise, vitesse)

    def _pas_de_cote(self, visiteur, robot, deplacement):
        """
        Pas de côté quand le robot vient vers le visiteur.

        Renvoie la vitesse du pas de côté, (0, 0) quand il est assez loin de la ligne du robot, ou
        None si le robot ne vient pas vers lui.
        """
        if deplacement is None:
            return None
        v = math.hypot(*deplacement)
        if v < VITESSE_ROBOT_MIN:
            return None
        ux, uy = deplacement[0] / v, deplacement[1] / v
        wx, wy = visiteur[0] - robot[0], visiteur[1] - robot[1]
        devant = wx * ux + wy * uy
        if devant <= 0 or math.hypot(wx, wy) > DISTANCE_CROISEMENT_M:
            return None
        lateral = ux * wy - uy * wx               # > 0 : le visiteur est à gauche du robot
        if abs(lateral) >= self.r['ecart_m']:
            return 0.0, 0.0                       # il attend sur le côté que le robot passe
        cotes = (1.0, -1.0) if lateral >= 0 else (-1.0, 1.0)
        for signe in cotes:
            nx, ny = -uy * signe, ux * signe          # perpendiculaire, du côté choisi
            cap = math.atan2(ny, nx)
            if self.carte is None or self._libre(visiteur, cap, longueur=0.0):
                return self.r['vitesse_ecart'] * nx, self.r['vitesse_ecart'] * ny
        return 0.0, 0.0

    def _partir(self, visiteur, robot):
        if math.dist(visiteur, robot) >= self.r['distance_partir_max_m']:
            return 0.0, 0.0
        dx, dy = visiteur[0] - robot[0], visiteur[1] - robot[1]
        loin = math.atan2(dy, dx) if math.hypot(dx, dy) > 1e-6 else 0.0
        if self.carte is None:
            return _vers(visiteur, (visiteur[0] + math.cos(loin), visiteur[1] + math.sin(loin)),
                         self.r['vitesse_partir'])
        # La direction libre la plus proche de « droit devant, loin du robot »
        for ecart in (0, 15, -15, 30, -30, 45, -45, 60, -60, 75, -75, 90, -90):
            cap = loin + math.radians(ecart)
            if self._libre(visiteur, cap):
                return (self.r['vitesse_partir'] * math.cos(cap),
                        self.r['vitesse_partir'] * math.sin(cap))
        return 0.0, 0.0

    def _libre(self, depart, cap, longueur=0.6):
        """Vrai si les longueur m devant (plus le rayon du corps) sont libres sur la carte."""
        import numpy as np
        c, s = math.cos(cap), math.sin(cap)
        pas = np.arange(0.05, longueur + self.r['rayon_m'] + 1e-9, 0.05)
        points = np.column_stack([depart[0] + c * pas, depart[1] + s * pas])
        return not self.carte.occupes(points, dehors=True).any()


def _vers(depuis, vers, vitesse):
    dx, dy = vers[0] - depuis[0], vers[1] - depuis[1]
    n = math.hypot(dx, dy)
    if n < 1e-6:
        return 0.0, 0.0
    return vitesse * dx / n, vitesse * dy / n


def message_consigne(ident, vx, vy):
    """Message /pietons/consigne (schéma pietons_consigne)."""
    plafond = REGLAGES_VISITEUR['vitesse_max']
    vx = max(-plafond, min(plafond, float(vx)))
    vy = max(-plafond, min(plafond, float(vy)))
    message = {'version': 1, 'id': ident, 'vx': round(vx, 3), 'vy': round(vy, 3)}
    if math.hypot(vx, vy) > 0.05:
        message['theta'] = round(math.atan2(vy, vx), 4)
    return message


# ---------------------------------------------------------------- nœud ROS 2

def main(args=None):
    """Point d'entrée de ros2 run g1_nav faux_visiteur."""
    import time

    import rclpy
    from rclpy.executors import ExternalShutdownException
    from rclpy.node import Node
    from rclpy.qos import qos_profile_sensor_data
    from nav_msgs.msg import Odometry
    from std_msgs.msg import String

    class NoeudFauxVisiteur(Node):
        def __init__(self):
            super().__init__('faux_visiteur')
            from rcl_interfaces.msg import ParameterDescriptor
            from atelier.lieu.comportement import SUJET_FAUX_VISITEUR
            from atelier.lieu.passants import DUREE_CONSIGNE_S, SUJET_CONSIGNE, SUJET_ETAT
            libre = ParameterDescriptor(dynamic_typing=True)
            self.ident = self.declare_parameter('visiteur', 'visiteur').value
            verite = self.declare_parameter('verite', '/odom').value
            mode = self.declare_parameter('mode', 'suivre').value
            lieu = self.declare_parameter('lieu', '').value
            etage = self.declare_parameter('etage', '').value
            frequence = float(self.declare_parameter('frequence', 10.0, libre).value)
            reglages = {nom: float(self.declare_parameter(nom, defaut, libre).value)
                        for nom, defaut in REGLAGES_VISITEUR.items()}
            carte = None
            if lieu and etage:
                from g1_nav.personnes import CarteStatique
                try:
                    carte = CarteStatique.depuis_lieu(lieu, etage, 0.05)
                except Exception as e:     # noqa: BLE001
                    self.get_logger().warn(f'carte illisible ({e}) : « partir » ira tout droit')
            self.logique = FauxVisiteur(carte, mode, **reglages)
            self.duree_consigne = DUREE_CONSIGNE_S
            self.visiteur = None           # (x, y, instant de réception)
            self.robot = None              # (x, y, vitesse, instant de réception)
            self.passe = []                # (instant, x, y) du robot sur la dernière demi-seconde
            self.consigne = (0.0, 0.0)
            self.absent_signale = False
            self.pub = self.create_publisher(String, SUJET_CONSIGNE, 10)
            self.pub_etat = self.create_publisher(String, '/faux_visiteur/etat', 10)
            self.create_subscription(String, SUJET_ETAT, self.sur_pietons, 10)
            self.create_subscription(Odometry, verite, self.sur_robot, qos_profile_sensor_data)
            self.create_subscription(String, SUJET_FAUX_VISITEUR, self.sur_mode, 10)
            self.create_timer(1.0 / frequence, self.pas)
            self.create_timer(0.5, self.publier_etat)
            self.get_logger().info(f'faux visiteur prêt : piéton « {self.ident} », vérité '
                                   f'{verite}, mode {self.logique.mode}')

        def sur_pietons(self, msg):
            try:
                donnees = json.loads(msg.data)
                pieton = next(p for p in donnees.get('pietons', []) if p.get('id') == self.ident)
                self.visiteur = (float(pieton['x']), float(pieton['y']), time.monotonic())
            except StopIteration:
                if not self.absent_signale:
                    self.absent_signale = True
                    self.get_logger().warn(f'le piéton « {self.ident} » n\'est pas dans '
                                           '/pietons/etat : la scène a-t-elle un piéton '
                                           '« pilote: externe » de cet id ?')
            except (ValueError, KeyError, TypeError, AttributeError):
                pass

        def sur_robot(self, msg):
            p, v = msg.pose.pose.position, msg.twist.twist.linear
            maintenant = time.monotonic()
            self.robot = (p.x, p.y, math.hypot(v.x, v.y), maintenant)
            self.logique.noter_robot(p.x, p.y)
            self.passe.append((maintenant, p.x, p.y))
            while self.passe and self.passe[0][0] < maintenant - 0.5:
                self.passe.pop(0)

        def deplacement_robot(self):
            """Vitesse (vx, vy) du robot dans map sur la dernière demi-seconde, ou None."""
            if len(self.passe) < 2 or self.passe[-1][0] - self.passe[0][0] < 0.2:
                return None
            (t0, x0, y0), (t1, x1, y1) = self.passe[0], self.passe[-1]
            return (x1 - x0) / (t1 - t0), (y1 - y0) / (t1 - t0)

        def sur_mode(self, msg):
            if self.logique.changer_mode(msg.data):
                self.get_logger().info(f'mode : {self.logique.mode}')
            else:
                self.get_logger().warn(f'mode inconnu : « {msg.data} » ({", ".join(MODES)})')

        def pas(self):
            maintenant = time.monotonic()
            if self.visiteur is None or self.robot is None \
                    or maintenant - self.visiteur[2] > 1.0 or maintenant - self.robot[3] > 1.0:
                return                     # sans nouvelles : la dernière consigne expire seule
            self.consigne = self.logique.consigne(self.visiteur[:2], self.robot[:2], self.robot[2],
                                                  self.deplacement_robot())
            self.pub.publish(String(data=json.dumps(message_consigne(self.ident, *self.consigne))))

        def publier_etat(self):
            vx, vy = self.consigne
            etat = {'version': 1, 'mode': self.logique.mode, 'visiteur': None, 'robot': None,
                    'distance_m': None, 'consigne': {'vx': round(vx, 3), 'vy': round(vy, 3)}}
            if self.visiteur is not None:
                etat['visiteur'] = {'x': round(self.visiteur[0], 3),
                                    'y': round(self.visiteur[1], 3)}
            if self.robot is not None:
                etat['robot'] = {'x': round(self.robot[0], 3), 'y': round(self.robot[1], 3)}
            if self.visiteur is not None and self.robot is not None:
                etat['distance_m'] = round(math.dist(self.visiteur[:2], self.robot[:2]), 3)
            self.pub_etat.publish(String(data=json.dumps(etat)))

        def arreter(self):
            """En quittant : une consigne nulle (le piéton s'arrête de toute façon après 0,5 s)."""
            try:
                self.pub.publish(String(data=json.dumps(message_consigne(self.ident, 0.0, 0.0))))
            except Exception:      # noqa: BLE001 : contexte déjà fermé
                pass

    rclpy.init(args=args)
    try:
        noeud = NoeudFauxVisiteur()
    except Exception as e:     # noqa: BLE001 : message clair, sans trace
        print(f'faux_visiteur : {e}', file=sys.stderr)
        rclpy.try_shutdown()
        return 1
    try:
        rclpy.spin(noeud)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        noeud.arreter()
        noeud.destroy_node()
        rclpy.try_shutdown()
    return 0


if __name__ == '__main__':
    sys.exit(main())
