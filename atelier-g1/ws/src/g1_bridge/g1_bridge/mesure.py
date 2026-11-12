"""
Mesures du pont et du robot pour la séance 2 (vague 5, section 12.12 du plan).

  python3 -m g1_bridge.mesure marche [--vx 0.2] [--vy 0.0] [--duree 2]
  python3 -m g1_bridge.mesure rotation [--wz 0.3] [--duree 3]
  python3 -m g1_bridge.mesure cap [--pendant 20]

marche et rotation : un échelon de vitesse sur /cmd_vel, donc toujours à travers le pont (plafonds,
vitesse minimale, verrou, repérage), puis plus rien : le pont arrête le robot 0,3 s après. La
mesure lit l'odométrie du robot (/state_estimator/odom_pelvis, comme le relais) et les requêtes
du pont (/api/sport/request) ; elle affiche, en français :
  - le retard : du premier 7105 non nul à l'instant où le robot atteint la moitié de la vitesse ;
  - la montée : de 10 % à 90 % de la vitesse atteinte ;
  - la vitesse atteinte (moyenne sur la seconde moitié de l'échelon) ;
  - l'arrêt : du dernier /cmd_vel à l'instant où le robot est arrêté ;
  - le dépassement : la distance (ou l'angle) parcourue après l'arrêt du dernier 7105 non nul.
cap : n'envoie rien ; suit le cap pendant un essai fait à côté (par exemple une rotation de 90°
par l'action Spin de Nav2) et affiche l'angle tourné, et le dépassement par rapport à --angle.

Sécurité : rien n'est envoyé si /pont/etat n'est pas « pret » (robot repéré, ou pont lancé avec
exiger_reperage:=false au portique) ; vitesses plafonnées à 0,3 m/s et 0,6 rad/s, échelon de 5 s
au plus ; Ctrl+C : /cmd_vel à zéro tout de suite. Télécommande en main.

Les calculs (analyser, vitesses) sont sans ROS, testés par test/test_mesure.py.
"""
import argparse
import math
import sys
import threading
import time

VITESSE_LIN_MAX = 0.3       # m/s : une mesure ne demande jamais plus
VITESSE_ROT_MAX = 0.6       # rad/s
DUREE_MAX_S = 5.0
APRES_S = 3.0               # observation après le dernier /cmd_vel
SEUIL_ARRETE = 0.1          # part de la vitesse atteinte sous laquelle le robot est arrêté
FENETRE_VITESSE_S = 0.1     # vitesse calculée sur cette fenêtre de l'odométrie


def angle_normal(a):
    return (a + math.pi) % (2.0 * math.pi) - math.pi


def vitesses(poses, fenetre=FENETRE_VITESSE_S):
    """
    Poses [(t, x, y, cap)] → [(t, vitesse linéaire, vitesse de rotation)].

    Chaque vitesse est une différence sur fenetre secondes (au moins deux poses), datée au milieu.
    """
    sortie = []
    j = 0
    for i in range(len(poses)):
        while j < len(poses) and poses[j][0] - poses[i][0] < fenetre:
            j += 1
        if j >= len(poses):
            break
        (t0, x0, y0, c0), (t1, x1, y1, c1) = poses[i], poses[j]
        dt = t1 - t0
        if dt <= 0:
            continue
        sortie.append(((t0 + t1) / 2.0, math.hypot(x1 - x0, y1 - y0) / dt,
                       angle_normal(c1 - c0) / dt))
    return sortie


def parcouru(poses, t0, rotation=False):
    """Distance (ou angle absolu) parcourue depuis t0, d'après les poses."""
    suite = [p for p in poses if p[0] >= t0]
    if len(suite) < 2:
        return 0.0
    if rotation:
        return abs(sum(angle_normal(b[3] - a[3]) for a, b in zip(suite, suite[1:])))
    return sum(math.hypot(b[1] - a[1], b[2] - a[2]) for a, b in zip(suite, suite[1:]))


def premier(echantillons, t0, condition):
    """Premier instant après t0 où condition(valeur) est vraie, ou None."""
    for t, v in echantillons:
        if t >= t0 and condition(v):
            return t
    return None


def analyser(poses, t_ordre, t_fin_ordre, t_dernier_envoi, rotation=False):
    """
    Échelon mesuré → dict des mesures (secondes, m/s ou rad/s, m ou rad), None si inconnu.

    poses : odométrie [(t, x, y, cap)] ; t_ordre : premier 7105 non nul ; t_fin_ordre : dernier
    /cmd_vel ; t_dernier_envoi : dernier 7105 non nul. rotation : mesures sur le cap.
    """
    v = vitesses(poses)
    serie = [(t, abs(w) if rotation else lin) for t, lin, w in v]
    pendant = [x for t, x in serie if t_ordre + (t_fin_ordre - t_ordre) / 2.0 <= t <= t_fin_ordre]
    atteinte = sum(pendant) / len(pendant) if pendant else None
    mesures = {'vitesse': atteinte, 'retard_s': None, 'montee_s': None, 'arret_s': None,
               'depassement': None, 'parcouru': parcouru(poses, t_ordre, rotation)}
    if not atteinte or atteinte <= 0:
        return mesures
    t_moitie = premier(serie, t_ordre, lambda x: x >= 0.5 * atteinte)
    t_10 = premier(serie, t_ordre, lambda x: x >= 0.1 * atteinte)
    t_90 = premier(serie, t_ordre, lambda x: x >= 0.9 * atteinte)
    if t_moitie is not None:
        mesures['retard_s'] = t_moitie - t_ordre
    if t_10 is not None and t_90 is not None:
        mesures['montee_s'] = t_90 - t_10
    t_arrete = premier(serie, t_fin_ordre, lambda x: x < SEUIL_ARRETE * atteinte)
    if t_arrete is not None:
        mesures['arret_s'] = t_arrete - t_fin_ordre
    if t_dernier_envoi is not None:
        mesures['depassement'] = parcouru(poses, t_dernier_envoi, rotation)
    return mesures


def texte_mesures(m, rotation=False, consigne=None):
    """Les mesures en français, une par ligne."""
    unite, unite_d = ('rad/s', 'rad') if rotation else ('m/s', 'm')

    def f(x, unite, chiffres=3):
        """Valeur et unité (« 0,20 m/s »), ou « inconnu » (le robot n'a pas bougé)."""
        if x is None:
            return 'inconnu'
        return f'{x:.{chiffres}f}'.replace('.', ',') + f' {unite}'

    def degres(x):
        return '' if not rotation or x is None else f' ({f(math.degrees(x), "°", 1)})'.replace(
            ' °', '°')
    lignes = []
    if consigne is not None:
        lignes.append(f'consigne demandée : {f(consigne, unite, 2)}')
    lignes += [f'vitesse atteinte : {f(m["vitesse"], unite)}',
               f'retard (premier ordre → moitié de la vitesse) : {f(m["retard_s"], "s", 2)}',
               f'montée (10 % → 90 %) : {f(m["montee_s"], "s", 2)}',
               f'arrêt (dernier /cmd_vel → arrêté) : {f(m["arret_s"], "s", 2)}',
               f'dépassement après le dernier ordre : {f(m["depassement"], unite_d)}'
               + degres(m['depassement']),
               f'parcouru en tout : {f(m["parcouru"], unite_d)}' + degres(m['parcouru'])]
    return '\n'.join(lignes)


# ---------------------------------------------------------------- avec ROS

class Mesureur:
    """Nœud rclpy dans un fil : odométrie, requêtes du pont, /pont/etat ; publie /cmd_vel."""

    def __init__(self):
        import json
        import rclpy
        from geometry_msgs.msg import Twist
        from nav_msgs.msg import Odometry
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.qos import qos_profile_sensor_data
        from std_msgs.msg import String
        from unitree_api.msg import Request
        self.json, self.Twist, self.rclpy = json, Twist, rclpy
        rclpy.init()
        self.noeud = rclpy.create_node('g1_mesure')
        self.verrou = threading.Lock()
        self.poses, self.envois, self.etat = [], [], {}
        n = self.noeud
        n.create_subscription(Odometry, '/state_estimator/odom_pelvis', self._odom,
                              qos_profile_sensor_data)
        n.create_subscription(Request, '/api/sport/request', self._requete,
                              qos_profile_sensor_data)
        n.create_subscription(String, '/pont/etat', self._etat, 10)
        self.pub = n.create_publisher(Twist, '/cmd_vel', 10)
        self.executeur = SingleThreadedExecutor()
        self.executeur.add_node(n)
        self.fil = threading.Thread(target=self._tourner, daemon=True)
        self.fil.start()

    def _tourner(self):
        try:
            self.executeur.spin()
        except Exception:       # noqa: B902 (fin de la mesure)
            pass

    def _odom(self, m):
        p, q = m.pose.pose.position, m.pose.pose.orientation
        cap = math.atan2(2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y * q.y + q.z * q.z))
        with self.verrou:
            self.poses.append((time.monotonic(), p.x, p.y, cap))

    def _requete(self, m):
        if m.header.identity.api_id != 7105:
            return
        try:
            v = self.json.loads(m.parameter)['velocity']
        except (ValueError, KeyError, TypeError):
            return
        with self.verrou:
            self.envois.append((time.monotonic(), tuple(v)))

    def _etat(self, m):
        try:
            self.etat = self.json.loads(m.data)
        except ValueError:
            pass

    def cmd_vel(self, vx, vy, wz):
        t = self.Twist()
        t.linear.x, t.linear.y, t.angular.z = float(vx), float(vy), float(wz)
        self.pub.publish(t)

    def attendre(self, condition, delai):
        fin = time.monotonic() + delai
        while time.monotonic() < fin:
            if condition():
                return True
            time.sleep(0.05)
        return False

    def fermer(self):
        self.executeur.shutdown(timeout_sec=2.0)
        self.fil.join(timeout=2.0)
        self.noeud.destroy_node()
        self.rclpy.try_shutdown()


def echelon(args, rotation):
    consigne = (0.0, 0.0, args.wz) if rotation else (args.vx, args.vy, 0.0)
    if math.hypot(consigne[0], consigne[1]) > VITESSE_LIN_MAX + 1e-9 \
            or abs(consigne[2]) > VITESSE_ROT_MAX + 1e-9 or not 0 < args.duree <= DUREE_MAX_S:
        print(f'mesure refusée : au plus {VITESSE_LIN_MAX:g} m/s, {VITESSE_ROT_MAX:g} rad/s et '
              f'{DUREE_MAX_S:g} s (durée plus grande que 0)'.replace('.', ','), file=sys.stderr)
        return 2
    m = Mesureur()
    try:
        if not m.attendre(lambda: m.poses and m.etat, 10.0):
            print('pas d\'odométrie (/state_estimator/odom_pelvis) ou pas de /pont/etat : le pont '
                  'et le robot sont-ils lancés (même ROS_DOMAIN_ID) ?', file=sys.stderr)
            return 1
        if not m.attendre(lambda: m.etat.get('etat') == 'pret', 5.0):
            print(f'le pont n\'est pas prêt ({m.etat.get("etat")} : {m.etat.get("message")}) : '
                  'rien n\'est envoyé', file=sys.stderr)
            return 1
        print(f'échelon {consigne} pendant {args.duree:g} s, par le pont (Ctrl+C : arrêt)',
              flush=True)
        debut = time.monotonic()
        dernier = debut
        try:
            while time.monotonic() - debut < args.duree:
                m.cmd_vel(*consigne)
                dernier = time.monotonic()
                time.sleep(0.05)
        finally:
            for _ in range(3):
                m.cmd_vel(0.0, 0.0, 0.0)
        time.sleep(APRES_S)
        with m.verrou:
            poses, envois = list(m.poses), list(m.envois)
        non_nuls = [t for t, v in envois if t >= debut and any(abs(c) > 1e-9 for c in v)]
        if not non_nuls:
            print('aucun 7105 non nul n\'est parti : le pont a-t-il ignoré /cmd_vel ? '
                  f'({m.etat.get("etat")} : {m.etat.get("message")})', file=sys.stderr)
            return 1
        envoye = [v for t, v in envois if t >= debut and any(abs(c) > 1e-9 for c in v)][0]
        mesures = analyser(poses, non_nuls[0], dernier, non_nuls[-1], rotation)
        print(texte_mesures(mesures, rotation, consigne[2] if rotation else
                            math.hypot(consigne[0], consigne[1])))
        print(f'7105 envoyé par le pont : {tuple(round(c, 3) for c in envoye)}')
        return 0
    finally:
        m.fermer()


def cap(args):
    m = Mesureur()
    try:
        if not m.attendre(lambda: m.poses, 10.0):
            print('pas d\'odométrie (/state_estimator/odom_pelvis)', file=sys.stderr)
            return 1
        debut = time.monotonic()
        cap0 = m.poses[-1][3]
        print(f'cap suivi pendant {args.pendant:g} s : lancez la rotation maintenant', flush=True)
        time.sleep(args.pendant)
        with m.verrou:
            poses = [p for p in m.poses if p[0] >= debut]
        tourne = sum(angle_normal(b[3] - a[3]) for a, b in zip(poses, poses[1:]))
        print(f'angle tourné : {math.degrees(tourne):.1f}° ({tourne:.3f} rad) ; cap final '
              f'{math.degrees(angle_normal(poses[-1][3])):.1f}° (départ '
              f'{math.degrees(angle_normal(cap0)):.1f}°)'.replace('.', ','))
        if args.angle is not None:
            ecart = abs(tourne) - math.radians(abs(args.angle))
            print(f'dépassement par rapport à {args.angle:g}° : {math.degrees(ecart):+.1f}° '
                  f'({ecart:+.3f} rad) : réglage anticipation_rotation_rad du guide'
                  .replace('.', ','))
        return 0
    finally:
        m.fermer()


TRADUCTIONS = [('usage:', 'usage :'), ('positional arguments', 'arguments'),
               ('options:', 'options :'),
               ('show this help message and exit', 'affiche cette aide'),
               ('the following arguments are required:', 'il manque :'),
               ('invalid choice:', 'choix inconnu :'), ('choose from', 'possibles :'),
               ('invalid float value:', 'nombre attendu :'), ('error:', 'erreur :')]


class Analyseur(argparse.ArgumentParser):
    """ArgumentParser qui parle français."""

    def format_help(self):
        texte = super().format_help()
        for anglais, francais in TRADUCTIONS:
            texte = texte.replace(anglais, francais)
        return texte

    def error(self, message):
        for anglais, francais in TRADUCTIONS:
            message = message.replace(anglais, francais)
        self.print_usage(sys.stderr)
        self.exit(2, f'mesure : {message}\n')


def main(argv=None):
    p = Analyseur(prog='python3 -m g1_bridge.mesure',
                  description='Mesures du pont et du robot (séance 2).')
    sous = p.add_subparsers(dest='action', required=True, parser_class=Analyseur)
    s = sous.add_parser('marche', help='échelon de marche par /cmd_vel')
    s.add_argument('--vx', type=float, default=0.2, help='vitesse en avant, m/s (défaut 0.2)')
    s.add_argument('--vy', type=float, default=0.0,
                   help='vitesse de côté, m/s, positive à gauche (défaut 0)')
    s.add_argument('--duree', type=float, default=2.0, help='durée de l\'échelon, s (défaut 2)')
    s = sous.add_parser('rotation', help='échelon de rotation par /cmd_vel')
    s.add_argument('--wz', type=float, default=0.3,
                   help='vitesse de rotation, rad/s, positive à gauche (défaut 0.3)')
    s.add_argument('--duree', type=float, default=3.0, help='durée de l\'échelon, s (défaut 3)')
    s = sous.add_parser('cap', help='suit le cap pendant un essai fait à côté')
    s.add_argument('--pendant', type=float, default=20.0,
                   help='durée du suivi du cap, s (défaut 20)')
    s.add_argument('--angle', type=float, help='angle demandé (degrés) : affiche le dépassement')
    args = p.parse_args(argv)
    if args.action == 'cap':
        return cap(args)
    return echelon(args, rotation=args.action == 'rotation')


if __name__ == '__main__':
    sys.exit(main())
