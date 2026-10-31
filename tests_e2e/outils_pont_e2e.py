#!/usr/bin/env python3
"""Outils ROS 2 des critères du pont et du faux G1 (critère 17, section 10 du plan).

  relais-simple [--lieu L --etage E] [--sans-map-odom]
      le relais simple de la répétition (localisation:=externe) : TF map → odom (identité),
      odom → base_link et /odom tirés de la vérité terrain /g1_jumeau/odom, /points recopié de
      /g1_jumeau/points, /reperage/etat repéré (5 Hz) ; écoute /relais_simple/commande
  commande perdre|retrouver
      le relais simple publie alors un repérage perdu (repere faux), ou de nouveau repéré
  attendre-nav2 [--delai 90]
      attend que bt_navigator soit actif (Nav2 prêt)
  liens
      aucun lien direct entre /cmd_vel et Gazebo : ros_gz_bridge (pont_gz) n'écoute pas /cmd_vel,
      seul g1_jumeau publie /g1_jumeau/cmd_vel
  navigation --lieu L --cible ID [--delai 240]
      lance « g1-guide aller ID » et mesure : le robot avance d'au moins 1 m et arrive à moins
      de 0,3 m (vérité terrain) ; requêtes 7105 au bon format, identity.id croissants, au moins
      8 par seconde en marche, chacune avec sa réponse ; vague 5 : les seules autres requêtes
      sont les lectures du mode du pont (7001, « {} », une par seconde) ; /pont/etat conforme
  essais-directs
      /cmd_vel du test : 0,9 m en 3 s et arrêt moins de 0,6 s après ; plafonds et NaN ;
      /guide/stop (arrêt en moins de 0,3 s, garde de 1 s) ; /pont/arret (arrêt en moins de 0,3 s,
      immobile 3 s, reprise seulement au /cmd_vel suivant) ; /pont/etat conforme

La vérité terrain de la répétition est /g1_jumeau/odom (repère du monde Gazebo = map), jamais
/odom. Les mesures de temps sont en temps mural (celui du pont et du faux G1). Codes de sortie :
0 réussi, 1 échoué.

Vague 5 (section 12.6 du plan) : le pont lit aussi le mode du robot (7001) une fois par seconde
sur /api/sport/request. Temoin.requetes_entre ne rend que les ordres de marche 7105 (api=None :
toutes), Temoin.lectures_entre les lectures 7001 ; orienter tourne au-dessus de la rotation
minimale du pont (0,3 rad/s).
"""
import argparse
import json
import math
import os
import subprocess
import sys
import threading
import time

ARRET = '{"velocity": [0.0, 0.0, 0.0], "duration": 1.0}'
SEUIL_ARRET = 0.02          # m/s : en dessous, le robot est arrêté
API_MARCHE = 7105           # SetVelocity : les ordres de marche
API_MODE = 7001             # GetFsmId : la lecture du mode par le pont (vague 5)
# orienter : rotation au-dessus du minimum du pont (sinon il la monte à 0,3 rad/s lui-même),
# arrêt sous ECART_ARRET_RAD, réussite sous ECART_REUSSI_RAD
ROTATION_MIN = 0.3
ECART_ARRET_RAD = 0.05
ECART_REUSSI_RAD = 0.1


# ---------------------------------------------------------------- ROS 2

def _ros():
    import rclpy
    from rclpy.executors import SingleThreadedExecutor
    return rclpy, SingleThreadedExecutor


class Noeud:
    """Un nœud rclpy qui tourne dans un fil de fond."""

    def __init__(self, nom):
        rclpy, Executeur = _ros()
        if not rclpy.ok():
            rclpy.init()
        self.rclpy = rclpy
        self.noeud = rclpy.create_node(nom)
        self.executeur = Executeur()
        self.executeur.add_node(self.noeud)
        self.fil = threading.Thread(target=self._tourner, daemon=True)
        self.fil.start()

    def _tourner(self):
        try:
            self.executeur.spin()
        except Exception:
            pass

    def fermer(self):
        self.executeur.shutdown(timeout_sec=2.0)
        self.fil.join(timeout=2.0)
        self.noeud.destroy_node()
        self.rclpy.try_shutdown()


def cap(q):
    return math.atan2(2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y * q.y + q.z * q.z))


def angle_normal(a):
    return (a + math.pi) % (2.0 * math.pi) - math.pi


def qos_verrou():
    from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
    return QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                      durability=DurabilityPolicy.TRANSIENT_LOCAL)


# ---------------------------------------------------------------- relais simple

def relais_simple(args):
    """TF et /odom tirés de la vérité terrain, /points recopié, /reperage/etat repéré."""
    import tf2_ros
    from geometry_msgs.msg import TransformStamped
    from nav_msgs.msg import Odometry
    from rclpy.qos import QoSProfile, ReliabilityPolicy, qos_profile_sensor_data
    from sensor_msgs.msg import PointCloud2
    from std_msgs.msg import String

    repere = {'x': 0.0, 'y': 0.0, 'theta': 0.0}
    if args.lieu:
        try:
            from atelier.lieu import repere_unitree
            r = repere_unitree(args.lieu, args.etage)
            repere = {'x': r.x, 'y': r.y, 'theta': r.theta}
        except Exception as erreur:
            print(f"relais simple : repère d'Unitree illisible ({erreur}) : (0, 0, 0)", flush=True)

    n = Noeud('relais_simple')
    noeud = n.noeud
    diffuseur = tf2_ros.TransformBroadcaster(noeud)
    statique = tf2_ros.StaticTransformBroadcaster(noeud)
    pub_odom = noeud.create_publisher(Odometry, '/odom', 10)
    pub_points = noeud.create_publisher(PointCloud2, '/points',
                                        QoSProfile(depth=5, reliability=ReliabilityPolicy.RELIABLE))
    pub_reperage = noeud.create_publisher(String, '/reperage/etat', 10)
    etat = {'repere': True, 'pose': None, 'stamp': None, 't': None}

    if not args.sans_map_odom:
        t = TransformStamped()
        t.header.stamp = noeud.get_clock().now().to_msg()
        t.header.frame_id, t.child_frame_id = 'map', 'odom'
        t.transform.rotation.w = 1.0
        statique.sendTransform(t)

    def sur_verite(m):
        t = TransformStamped()
        t.header.stamp = m.header.stamp
        t.header.frame_id, t.child_frame_id = 'odom', 'base_link'
        p, q = m.pose.pose.position, m.pose.pose.orientation
        t.transform.translation.x, t.transform.translation.y = p.x, p.y
        t.transform.rotation = q
        diffuseur.sendTransform(t)
        o = Odometry()
        o.header.stamp = m.header.stamp
        o.header.frame_id, o.child_frame_id = 'odom', 'base_link'
        o.pose.pose.position.x, o.pose.pose.position.y = p.x, p.y
        o.pose.pose.orientation = q
        o.twist = m.twist
        pub_odom.publish(o)
        etat['pose'] = {'x': round(p.x, 4), 'y': round(p.y, 4), 'theta': round(cap(q), 4)}
        etat['t'] = time.monotonic()

    def sur_nuage(m):
        pub_points.publish(m)

    def sur_commande(m):
        texte = m.data.strip()
        if texte in ('perdre', 'retrouver'):
            etat['repere'] = texte == 'retrouver'
            print(f'relais simple : {texte}', flush=True)
            publier_reperage()

    def publier_reperage():
        repere_ok = etat['repere'] and etat['pose'] is not None
        message = {
            'version': 1, 'etat': 'repere' if repere_ok else ('perdu' if etat['pose'] else
                                                              'non_repere'),
            'repere': repere_ok, 'localisation': 'unitree',
            'message': ('Relais simple du test : position tirée de la vérité terrain de Gazebo.'
                        if repere_ok else 'Relais simple du test : repérage perdu (essai).'),
            'pose': etat['pose'], 'precision_m': 0.0,
            'age_s': None if etat['t'] is None else round(time.monotonic() - etat['t'], 3),
            'demande': None, 'carte': None, 'repere_unitree': repere, 'sauts': 0,
            'relais': 'simple'}
        pub_reperage.publish(String(data=json.dumps(message)))

    noeud.create_subscription(Odometry, '/g1_jumeau/odom', sur_verite, qos_profile_sensor_data)
    noeud.create_subscription(PointCloud2, '/g1_jumeau/points', sur_nuage, qos_profile_sensor_data)
    noeud.create_subscription(String, '/relais_simple/commande', sur_commande, 10)
    noeud.create_timer(0.2, publier_reperage)
    print('relais simple prêt : /g1_jumeau/odom → TF et /odom, /g1_jumeau/points → /points, '
          f'/reperage/etat ; map → odom {"non publié" if args.sans_map_odom else "identité"}',
          flush=True)
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        n.fermer()
    return 0


def commande(args):
    from std_msgs.msg import String
    n = Noeud('commande_relais_simple')
    try:
        pub = n.noeud.create_publisher(String, '/relais_simple/commande', 10)
        fin = time.monotonic() + 5.0
        while pub.get_subscription_count() == 0 and time.monotonic() < fin:
            time.sleep(0.1)
        if pub.get_subscription_count() == 0:
            print('le relais simple ne répond pas')
            return 1
        pub.publish(String(data=args.ordre))
        time.sleep(0.3)
        return 0
    finally:
        n.fermer()


def attendre_nav2(args):
    from lifecycle_msgs.srv import GetState
    n = Noeud('e2e_attente_nav2')
    try:
        client = n.noeud.create_client(GetState, '/bt_navigator/get_state')
        fin = time.monotonic() + args.delai
        while time.monotonic() < fin:
            if client.wait_for_service(timeout_sec=1.0):
                futur = client.call_async(GetState.Request())
                limite = time.monotonic() + 3.0
                while not futur.done() and time.monotonic() < limite:
                    time.sleep(0.05)
                if futur.done() and futur.result() and futur.result().current_state.label == 'active':
                    print('Nav2 actif (bt_navigator)')
                    return 0
            time.sleep(0.5)
        print(f"Nav2 n'est pas actif après {args.delai:g} s")
        return 1
    finally:
        n.fermer()


def liens(args):
    """Aucun lien direct /cmd_vel → Gazebo ; seul g1_jumeau publie /g1_jumeau/cmd_vel."""
    n = Noeud('e2e_liens')
    try:
        noeud = n.noeud
        time.sleep(2.0)                       # découverte
        abonnes = sorted({i.node_name for i in noeud.get_subscriptions_info_by_topic('/cmd_vel')})
        editeurs = sorted({i.node_name
                           for i in noeud.get_publishers_info_by_topic('/g1_jumeau/cmd_vel')})
        lecteurs_gz = sorted({i.node_name
                              for i in noeud.get_subscriptions_info_by_topic('/g1_jumeau/cmd_vel')})
        print(f'abonnés à /cmd_vel : {abonnes}')
        print(f'éditeurs de /g1_jumeau/cmd_vel : {editeurs} ; lecteurs : {lecteurs_gz}')
        erreurs = []
        if 'pont_gz' in abonnes:
            erreurs.append('ros_gz_bridge (pont_gz) est abonné à /cmd_vel : lien direct vers Gazebo')
        if 'pont_g1' not in abonnes:
            erreurs.append("le pont (pont_g1) n'écoute pas /cmd_vel")
        if editeurs != ['g1_jumeau']:
            erreurs.append(f'/g1_jumeau/cmd_vel doit être publié par g1_jumeau seul, pas {editeurs}')
        if 'pont_gz' not in lecteurs_gz:
            erreurs.append("ros_gz_bridge n'écoute pas /g1_jumeau/cmd_vel")
        for e in erreurs:
            print(f'ERREUR : {e}')
        return 1 if erreurs else 0
    finally:
        n.fermer()


# ---------------------------------------------------------------- témoin

class Temoin(Noeud):
    """Écoute les requêtes, les réponses, la vérité terrain et /pont/etat (validé)."""

    def __init__(self, nom='e2e_temoin_pont'):
        super().__init__(nom)
        from geometry_msgs.msg import Twist
        from nav_msgs.msg import Odometry
        from rclpy.qos import qos_profile_sensor_data
        from std_msgs.msg import Bool, Empty, String
        from unitree_api.msg import Request, Response
        try:
            from atelier.lieu import valider_message
        except ImportError:
            valider_message = None
        self.valider = valider_message
        self.verrou = threading.Lock()
        self.requetes, self.reponses, self.verites, self.etats = [], [], [], []
        self.non_conformes = []
        self.Twist, self.Bool, self.Empty = Twist, Bool, Empty
        n = self.noeud
        n.create_subscription(Request, '/api/sport/request', self._requete, qos_profile_sensor_data)
        n.create_subscription(Response, '/api/sport/response', self._reponse,
                              qos_profile_sensor_data)
        n.create_subscription(Odometry, '/g1_jumeau/odom', self._verite, qos_profile_sensor_data)
        n.create_subscription(String, '/pont/etat', self._etat, 50)
        self.pub_cmd_vel = n.create_publisher(Twist, '/cmd_vel', 10)
        self.pub_stop = n.create_publisher(Empty, '/guide/stop', 10)
        self.pub_verrou = n.create_publisher(Bool, '/pont/arret', qos_verrou())

    def _requete(self, m):
        try:
            p = json.loads(m.parameter)
        except ValueError:
            p = None
        with self.verrou:
            self.requetes.append((time.monotonic(), m.header.identity.id,
                                  m.header.identity.api_id, m.parameter, p))

    def _reponse(self, m):
        with self.verrou:
            self.reponses.append((time.monotonic(), m.header.identity.id,
                                  m.header.status.code))

    def _verite(self, m):
        p = m.pose.pose
        with self.verrou:
            self.verites.append((time.monotonic(), m.header.stamp.sec + m.header.stamp.nanosec * 1e-9,
                                 p.position.x, p.position.y, cap(p.orientation)))
            del self.verites[:-30000]

    def _etat(self, m):
        try:
            etat = json.loads(m.data)
        except ValueError:
            self.non_conformes.append(('JSON illisible', m.data[:200]))
            return
        if self.valider is not None:
            erreurs = self.valider('etat_pont', etat)
            if erreurs:
                self.non_conformes.append((erreurs, etat))
        with self.verrou:
            self.etats.append((time.monotonic(), etat))

    # ------------------------------------------------------------ lecture

    def attendre_pret(self, delai=15.0):
        fin = time.monotonic() + delai
        while time.monotonic() < fin:
            if self.verites and self.etats and self.pub_cmd_vel.get_subscription_count() > 0:
                return True
            time.sleep(0.1)
        return False

    def pose(self):
        with self.verrou:
            _, _, x, y, c = self.verites[-1]
        return x, y, c

    def requetes_entre(self, t0, t1=math.inf, api=API_MARCHE):
        """Requêtes vues entre t0 et t1 : les 7105 (défaut), celles de cet api_id, ou toutes."""
        with self.verrou:
            return [r for r in self.requetes if t0 <= r[0] < t1 and (api is None or r[2] == api)]

    def lectures_entre(self, t0, t1=math.inf):
        """Lectures du mode (7001) vues entre t0 et t1."""
        return self.requetes_entre(t0, t1, api=API_MODE)

    def verites_entre(self, t0, t1=math.inf):
        with self.verrou:
            return [v for v in self.verites if t0 <= v[0] < t1]

    def dernier_etat(self):
        with self.verrou:
            return self.etats[-1][1] if self.etats else {}

    def vitesse_robot(self, t0, t1, pas=0.05):
        """(avant, côté, rotation) moyens entre t0 et t1, chaque morceau de pas secondes (temps
        simulé) étant exprimé dans le repère du robot à son milieu : juste même quand il tourne."""
        v = self.verites_entre(t0, t1)
        somme, duree = [0.0, 0.0, 0.0], 0.0
        i = 0
        while i < len(v) - 1:
            j = i + 1
            while j < len(v) - 1 and v[j][1] - v[i][1] < pas:
                j += 1
            dt = v[j][1] - v[i][1]
            if dt <= 0:
                break
            dx, dy = v[j][2] - v[i][2], v[j][3] - v[i][3]
            dcap = angle_normal(v[j][4] - v[i][4])
            milieu = v[i][4] + dcap / 2.0
            somme[0] += math.cos(milieu) * dx + math.sin(milieu) * dy
            somme[1] += -math.sin(milieu) * dx + math.cos(milieu) * dy
            somme[2] += dcap
            duree += dt
            i = j
        if duree < 0.2:
            return None
        return tuple(c / duree for c in somme)

    def instant_arret(self, t_ref, seuil=SEUIL_ARRET, tenue=0.3):
        """Premier instant mural après t_ref où la vitesse (sur 0,1 s) reste sous seuil."""
        v = self.verites_entre(t_ref - 0.3)
        vitesses = []
        j = 0
        for i, (t, s, x, y, _) in enumerate(v):
            j = max(j, i)
            while j + 1 < len(v) and v[j][1] - s < 0.1:
                j += 1
            if v[j][1] - s >= 0.099:
                vitesses.append((t, math.hypot(v[j][2] - x, v[j][3] - y) / (v[j][1] - s)))
        for k, (t, w) in enumerate(vitesses):
            if t < t_ref or w >= seuil:
                continue
            suite = [u for (tt, u) in vitesses[k:] if tt <= t + tenue]
            if all(u < seuil for u in suite) and vitesses[-1][0] >= t + tenue:
                return t
        return None

    # ------------------------------------------------------------ commandes

    def cmd_vel(self, vx, vy, wz):
        t = self.Twist()
        t.linear.x, t.linear.y, t.angular.z = float(vx), float(vy), float(wz)
        self.pub_cmd_vel.publish(t)

    def cmd_vel_pendant(self, consigne, duree, frequence=20.0):
        """/cmd_vel à 20 Hz pendant duree ; renvoie (instant du premier, instant du dernier)."""
        debut = time.monotonic()
        dernier = debut
        while time.monotonic() - debut < duree:
            self.cmd_vel(*consigne)
            dernier = time.monotonic()
            time.sleep(1.0 / frequence)
        return debut, dernier

    def orienter(self, cap_vise=0.0, delai=20.0):
        """
        Tourne le robot (par /cmd_vel, donc par le pont) vers cap_vise ; puis l'arrête.

        Vague 5 : la rotation reste au-dessus du minimum du pont (0,3 rad/s ; en dessous, il la
        monterait lui-même, et le régulateur ne convergerait plus) ; arrêt sous 0,05 rad, réussite
        sous 0,1 rad.
        """
        fin = time.monotonic() + delai
        while time.monotonic() < fin:
            ecart = angle_normal(cap_vise - self.pose()[2])
            if abs(ecart) < ECART_ARRET_RAD:
                break
            self.cmd_vel(0.0, 0.0, math.copysign(max(ROTATION_MIN, min(0.5, 1.5 * abs(ecart))),
                                                 ecart))
            time.sleep(0.05)
        self.cmd_vel(0.0, 0.0, 0.0)
        time.sleep(1.0)
        return abs(angle_normal(cap_vise - self.pose()[2])) < ECART_REUSSI_RAD


def _vitesses(requete):
    p = requete[4]
    return tuple(p['velocity']) if isinstance(p, dict) and 'velocity' in p else None


def _nulle(requete):
    v = _vitesses(requete)
    return v is not None and all(c == 0.0 for c in v)


class Bilan:
    def __init__(self):
        self.erreurs = []

    def verifier(self, condition, texte_ok, texte_erreur):
        if condition:
            print(f'  ok : {texte_ok}', flush=True)
        else:
            print(f'  ERREUR : {texte_erreur}', flush=True)
            self.erreurs.append(texte_erreur)
        return condition

    def conformite(self, temoin):
        n = len(temoin.etats)
        self.verifier(n > 0 and not temoin.non_conformes,
                      f'/pont/etat conforme au schéma etat_pont ({n} messages)',
                      f'/pont/etat non conforme : {temoin.non_conformes[:2]} ({n} messages)')

    def code(self):
        if self.erreurs:
            print(f'{len(self.erreurs)} vérification(s) échouée(s)')
        return 1 if self.erreurs else 0


def format_lectures(lectures, bilan, duree=None):
    """
    Lectures du mode du pont (vague 5) : api_id 7001, parameter « {} », une par seconde.

    duree : la durée d'observation (s) ; le rythme est alors vérifié (de 0,7 à 1,3 par seconde).
    """
    mauvaises = [r[3] for r in lectures if r[2] != API_MODE or r[3] != '{}']
    bilan.verifier(lectures and not mauvaises, f'{len(lectures)} lectures du mode 7001 au format '
                   '« {} »', f'lectures du mode absentes ou mal formées : {mauvaises[:3]} '
                   f'({len(lectures)} lectures)')
    if duree and lectures:
        frequence = len(lectures) / duree
        bilan.verifier(0.7 <= frequence <= 1.3, f'{frequence:.2f} lecture du mode par seconde '
                       '(de 0,7 à 1,3)', f'{frequence:.2f} lecture du mode par seconde au lieu '
                       'de 1')


def autres_requetes(requetes):
    """Requêtes de /api/sport/request qui ne sont ni des 7105 ni des lectures du mode 7001."""
    return [r for r in requetes if r[2] not in (API_MARCHE, API_MODE)]


def format_requetes(requetes, bilan):
    """api_id 7105, parameter {velocity: [3 nombres], duration: 0,5 (1,0 pour un arrêt)}."""
    mauvaises = []
    for r in requetes:
        _, _, api, texte, p = r
        ok = (api == 7105 and isinstance(p, dict) and set(p) == {'velocity', 'duration'}
              and isinstance(p['velocity'], list) and len(p['velocity']) == 3
              and all(isinstance(v, float) and math.isfinite(v) for v in p['velocity'])
              and p['duration'] == (1.0 if _nulle(r) else 0.5))
        if not ok:
            mauvaises.append(texte)
    bilan.verifier(requetes and not mauvaises,
                   f'{len(requetes)} requêtes 7105 au format {{velocity: [3 nombres], '
                   f'duration: 0,5}} (1,0 pour un arrêt)',
                   f'requêtes mal formées : {mauvaises[:3]}')
    ids = [r[1] for r in requetes]
    bilan.verifier(all(b > a for a, b in zip(ids, ids[1:])), 'identity.id strictement croissants',
                   'identity.id non croissants')


# ---------------------------------------------------------------- navigation par Nav2

def navigation(args):
    """g1-guide aller CIBLE : Nav2 → pont → faux G1 → Gazebo."""
    import yaml
    from atelier import chemin_lieu
    noeuds = yaml.safe_load((chemin_lieu(args.lieu) / 'itineraires.yaml').read_text())['noeuds']
    if args.cible not in noeuds:
        print(f'nœud {args.cible} inconnu')
        return 1
    cx, cy = float(noeuds[args.cible]['x']), float(noeuds[args.cible]['y'])
    temoin = Temoin('e2e_temoin_navigation')
    bilan = Bilan()
    try:
        if not temoin.attendre_pret():
            print('vérité terrain, /pont/etat ou pont absents')
            return 1
        x0, y0, _ = temoin.pose()
        print(f'départ : ({x0:.2f} ; {y0:.2f}) ; cible {args.cible} : ({cx:.2f} ; {cy:.2f})',
              flush=True)
        debut = time.monotonic()
        try:
            sortie = subprocess.run(['g1-guide', 'aller', args.cible], capture_output=True,
                                    text=True, timeout=args.delai)
            code, texte = sortie.returncode, sortie.stdout + sortie.stderr
        except subprocess.TimeoutExpired as e:
            code, texte = 124, f'délai dépassé ({args.delai:g} s) : {e.stdout or ""}'
        fin = time.monotonic()
        print('g1-guide aller : ' + ' | '.join(ligne for ligne in texte.splitlines()
                                               if ligne.strip())[-600:],
              flush=True)
        time.sleep(1.5)
        x1, y1, _ = temoin.pose()
        avance = math.hypot(x1 - x0, y1 - y0)
        ecart = math.hypot(x1 - cx, y1 - cy)
        bilan.verifier(code == 0, f'guide arrivé à {args.cible} en {fin - debut:.0f} s',
                       f'g1-guide aller {args.cible} : code {code}')
        bilan.verifier(avance >= 1.0, f'le robot proxy a avancé de {avance:.2f} m (≥ 1 m)',
                       f'le robot proxy n\'a avancé que de {avance:.2f} m')
        bilan.verifier(ecart < 0.3, f'arrivé à {ecart:.3f} m de {args.cible} (< 0,3 m)',
                       f'arrivé à {ecart:.3f} m de {args.cible} (≥ 0,3 m)')
        requetes = temoin.requetes_entre(debut, fin + 1.0)
        format_requetes(requetes, bilan)
        toutes = temoin.requetes_entre(debut, fin + 1.0, api=None)
        bilan.verifier(not autres_requetes(toutes), 'sur /api/sport/request : des 7105 et les '
                       'lectures du mode 7001, rien d\'autre',
                       f'autres requêtes : {autres_requetes(toutes)[:3]}')
        format_lectures(temoin.lectures_entre(debut, fin), bilan, fin - debut)
        mouvement = [r for r in requetes if not _nulle(r)]
        if mouvement:
            t0, t1 = mouvement[0][0], mouvement[-1][0]
            pendant = [r for r in requetes if t0 <= r[0] <= t1]
            frequence = (len(pendant) - 1) / max(1e-6, t1 - t0)
            ecarts = [b[0] - a[0] for a, b in zip(pendant, pendant[1:])]
            bilan.verifier(frequence >= 8.0,
                           f'{frequence:.1f} requêtes par seconde en marche (≥ 8 ; plus grand '
                           f'écart {max(ecarts, default=0):.2f} s, {len(pendant)} requêtes en '
                           f'{t1 - t0:.1f} s)',
                           f'seulement {frequence:.1f} requêtes par seconde en marche')
        else:
            bilan.verifier(False, '', 'aucune requête de mouvement pendant la navigation')
        repondues = {i for _, i, c in temoin.reponses if c == 0}
        sans = [r[1] for r in requetes if r[1] not in repondues]
        bilan.verifier(not sans, f'chaque requête a sa réponse (code 0), {len(requetes)} en tout',
                       f'{len(sans)} requêtes sans réponse de code 0')
        bilan.conformite(temoin)
        return bilan.code()
    finally:
        temoin.fermer()


# ---------------------------------------------------------------- essais par /cmd_vel

def essais_directs(args):
    temoin = Temoin('e2e_temoin_essais')
    bilan = Bilan()
    t = temoin
    try:
        if not t.attendre_pret():
            print('vérité terrain, /pont/etat ou pont absents')
            return 1
        etat = t.dernier_etat()
        bilan.verifier(etat.get('etat') == 'pret', 'pont prêt avant les essais',
                       f'pont pas prêt : {etat.get("etat")} ({etat.get("message")})')
        # Robot tourné vers l'est (le long du couloir sud), par /cmd_vel, donc par le pont
        bilan.verifier(t.orienter(0.0), 'robot tourné vers l\'est par le pont',
                       'impossible de tourner le robot vers l\'est')

        print('— /cmd_vel vx 0,3 pendant 3 s', flush=True)
        x0, y0, _ = t.pose()
        debut, dernier = t.cmd_vel_pendant((0.3, 0.0, 0.0), 3.0)
        time.sleep(2.0)
        x1, y1, _ = t.pose()
        distance = math.hypot(x1 - x0, y1 - y0)
        arret = t.instant_arret(dernier)
        bilan.verifier(abs(distance - 0.9) <= 0.2, f'{distance:.3f} m parcourus (0,9 ± 0,2 m)',
                       f'{distance:.3f} m parcourus au lieu de 0,9 ± 0,2 m')
        bilan.verifier(arret is not None and arret - dernier < 0.6,
                       f'arrêté {arret - dernier if arret else 0:.2f} s après le dernier /cmd_vel '
                       f'(< 0,6 s)', f'pas arrêté moins de 0,6 s après le dernier /cmd_vel '
                       f'({arret and arret - dernier})')
        apres = t.requetes_entre(dernier)
        bilan.verifier(any(r[3] == ARRET for r in apres), 'un 7105 [0, 0, 0] est parti',
                       'aucun 7105 [0, 0, 0] après le dernier /cmd_vel')

        print('— consigne (1,0 ; 0,6 ; 2,0) puis NaN', flush=True)
        debut, dernier = t.cmd_vel_pendant((1.0, 0.6, 2.0), 1.0)
        t_nan, _ = t.cmd_vel_pendant((float('nan'), 0.0, 0.0), 1.0)
        time.sleep(1.0)
        envoyees = {_vitesses(r) for r in t.requetes_entre(debut + 0.05, t_nan)}
        envoyees.discard((0.0, 0.0, 0.0))
        bilan.verifier(envoyees == {(0.4, 0.25, 0.6)},
                       'requêtes plafonnées à (0,4 ; 0,25 ; 0,6)',
                       f'requêtes envoyées : {sorted(envoyees)}')
        mesure = t.vitesse_robot(debut + 0.3, t_nan)
        if mesure:
            avant, cote, rotation = mesure
            bilan.verifier(abs(avant) <= 0.42 and abs(cote) <= 0.27 and abs(rotation) <= 0.62,
                           f'vitesse mesurée dans le repère du robot : avant {avant:.3f} m/s '
                           f'(≤ 0,42), côté {cote:.3f} m/s (≤ 0,27), rotation {rotation:.3f} '
                           f'rad/s (≤ 0,62) ; norme {math.hypot(avant, cote):.3f} m/s',
                           f'vitesse mesurée au-delà des plafonds : {mesure}')
        else:
            bilan.verifier(False, '', 'pas de vérité terrain pendant la consigne plafonnée')
        apres_nan = t.requetes_entre(t_nan + 0.02, t_nan + 1.0)
        arret = t.instant_arret(t_nan)
        bilan.verifier(apres_nan and all(_nulle(r) for r in apres_nan)
                       and arret is not None and arret - t_nan < 0.3,
                       f'NaN : que des arrêts ({len(apres_nan)} requêtes), robot arrêté '
                       f'{arret - t_nan if arret else 0:.2f} s après',
                       f'NaN : requêtes {[_vitesses(r) for r in apres_nan][:3]}, arrêt {arret}')
        t.orienter(0.0)

        print('— /guide/stop en marche', flush=True)
        fil = _cmd_vel_en_fond(t, (0.3, 0.0, 0.0))
        time.sleep(1.0)
        t_stop = time.monotonic()
        t.pub_stop.publish(t.Empty())
        time.sleep(1.6)
        fil.arreter()
        time.sleep(1.0)
        arret = t.instant_arret(t_stop)
        bilan.verifier(arret is not None and arret - t_stop < 0.3,
                       f'arrêté {arret - t_stop if arret else 0:.2f} s après /guide/stop (< 0,3 s)',
                       f'pas arrêté moins de 0,3 s après /guide/stop ({arret and arret - t_stop})')
        pendant = t.requetes_entre(t_stop + 0.02, t_stop + 0.95)
        bilan.verifier(all(_nulle(r) for r in pendant),
                       '/cmd_vel ignoré pendant 1 s (aucun 7105 non nul)',
                       f'7105 non nuls pendant la garde : {[_vitesses(r) for r in pendant][:3]}')
        reprise = [r[0] - t_stop for r in t.requetes_entre(t_stop) if not _nulle(r)]
        bilan.verifier(reprise and 1.0 <= reprise[0] <= 1.25,
                       f'la marche reprend {reprise[0] if reprise else 0:.2f} s après /guide/stop',
                       f'reprise après la garde : {reprise[:1]}')

        print('— /pont/arret true puis false', flush=True)
        t.orienter(0.0)
        fil = _cmd_vel_en_fond(t, (0.3, 0.0, 0.0))
        time.sleep(1.0)
        t_verrou = time.monotonic()
        t.pub_verrou.publish(t.Bool(data=True))
        time.sleep(3.5)
        fil.arreter()
        arret = t.instant_arret(t_verrou, tenue=2.5)
        bilan.verifier(arret is not None and arret - t_verrou < 0.3,
                       f'arrêté {arret - t_verrou if arret else 0:.2f} s après /pont/arret true '
                       f'(< 0,3 s), puis immobile 3 s malgré /cmd_vel',
                       f'verrou : arrêt {arret and arret - t_verrou}')
        v = t.verites_entre(t_verrou + 0.4, t_verrou + 3.4)
        deplacement = math.hypot(v[-1][2] - v[0][2], v[-1][3] - v[0][3]) if v else math.inf
        bilan.verifier(deplacement < 0.02, f'déplacement pendant le verrou : {deplacement:.3f} m',
                       f'le robot a bougé de {deplacement:.3f} m pendant le verrou')
        bilan.verifier(all(_nulle(r) for r in t.requetes_entre(t_verrou + 0.02)),
                       'aucun 7105 non nul pendant le verrou', '7105 non nul pendant le verrou')
        bilan.verifier(t.dernier_etat().get('etat') == 'arret_verrouille',
                       'état arret_verrouille', f'état {t.dernier_etat().get("etat")}')
        time.sleep(0.5)
        t_libre = time.monotonic()
        t.pub_verrou.publish(t.Bool(data=False))
        time.sleep(1.5)
        bilan.verifier(not [r for r in t.requetes_entre(t_libre) if not _nulle(r)]
                       and t.instant_arret(t_libre - 0.2, tenue=1.0) is not None,
                       'déverrouillé : rien ne repart sans /cmd_vel neuf',
                       'le robot est reparti sans /cmd_vel neuf')
        debut, dernier = t.cmd_vel_pendant((0.2, 0.0, 0.0), 0.8)
        time.sleep(1.0)
        bilan.verifier(any(not _nulle(r) for r in t.requetes_entre(debut)),
                       'la marche reprend au /cmd_vel suivant', 'pas de reprise au /cmd_vel suivant')
        bilan.conformite(t)
        return bilan.code()
    finally:
        try:
            t.pub_verrou.publish(t.Bool(data=False))
            time.sleep(0.2)
        except Exception:
            pass
        t.fermer()


class _cmd_vel_en_fond:
    """Publie /cmd_vel à 20 Hz dans un fil, jusqu'à arreter()."""

    def __init__(self, temoin, consigne):
        self.actif = True
        self.fil = threading.Thread(target=self._boucle, args=(temoin, consigne), daemon=True)
        self.fil.start()

    def _boucle(self, temoin, consigne):
        while self.actif:
            temoin.cmd_vel(*consigne)
            time.sleep(0.05)

    def arreter(self):
        self.actif = False
        self.fil.join(timeout=1.0)


def main():
    p = argparse.ArgumentParser(description='Outils du critère 17 (pont et faux G1).')
    sous = p.add_subparsers(dest='action', required=True)
    s = sous.add_parser('relais-simple')
    s.add_argument('--lieu')
    s.add_argument('--etage', default='rdc')
    s.add_argument('--sans-map-odom', action='store_true')
    s.set_defaults(f=relais_simple)
    s = sous.add_parser('commande')
    s.add_argument('ordre', choices=['perdre', 'retrouver'])
    s.set_defaults(f=commande)
    s = sous.add_parser('attendre-nav2')
    s.add_argument('--delai', type=float, default=90.0)
    s.set_defaults(f=attendre_nav2)
    s = sous.add_parser('liens')
    s.set_defaults(f=liens)
    s = sous.add_parser('navigation')
    s.add_argument('--lieu', required=True)
    s.add_argument('--cible', required=True)
    s.add_argument('--delai', type=float, default=240.0)
    s.set_defaults(f=navigation)
    s = sous.add_parser('essais-directs')
    s.set_defaults(f=essais_directs)
    args = p.parse_args()
    os.environ.setdefault('PYTHONUNBUFFERED', '1')
    return args.f(args)


if __name__ == '__main__':
    sys.exit(main())
