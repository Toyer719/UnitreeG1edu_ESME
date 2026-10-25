"""Exploration automatique d'un étage par le robot simulé, pendant un scan (section 9.5 du plan).

Le robot fait seul un tour qui passe par tous les couloirs de itineraires.yaml de l'étage : il
part du nœud le plus proche et y revient. Le tour est un circuit qui emprunte chaque couloir au
moins une fois (problème du postier chinois : les couloirs des nœuds de degré impair sont doublés
au plus court, puis circuit eulérien). À la fin du tour, le robot s'arrête et le programme se
termine : g1-scan arrête alors le scan de lui-même, comme avec « Fin ».

Deux façons de conduire le robot (--pilote) :
  - direct (défaut, contrat 9.5) : ligne droite de nœud en nœud, par /cmd_vel et /odom, à
    0,4 m/s au plus ; arrêt devant un obstacle vu dans /points à moins de 0,6 m (on attend qu'il
    parte : un piéton passe). Après 30 s d'attente, le couloir est déclaré bloqué : le robot
    revient au nœud d'où il venait et finit le tour par les autres couloirs ;
  - guide : /guide/aller nœud après nœud, en attendant « arrive » sur /guide/etat (Nav2
    contourne les obstacles). Lance g1-guide navigation --simu si le guide ne tourne pas.

Seulement avec le robot simulé (mode simu, ou robot en répétition) : jamais sur le vrai G1.

    python -m atelier.scan.exploration --lieu L --etage E [--session S] [--pilote direct|guide]
Codes de sortie : 0 tour fini (ou arrêt demandé), 1 échec (pas d'odométrie, robot coincé...).
"""
import argparse
import heapq
import json
import math
import os
import signal
import subprocess
import sys
import threading
import time
from collections import deque

VITESSE_MAX = 0.4            # m/s
ROTATION_MAX = 0.8           # rad/s
DISTANCE_ARRET = 0.6         # m, devant le robot (depuis sa face avant)
DEMI_PROFONDEUR = 0.11       # m, du centre du robot proxy à sa face avant (corps de 0,208 m)
DEMI_LARGEUR = 0.30          # m, demi-largeur du couloir surveillé (robot de 0,477 m, plus une marge)
TRANCHE_OBSTACLE = (0.1, 1.5)   # m au-dessus du sol, comme la carte 2D
MEMOIRE_POINTS = 2.5         # s : les points vus récemment comptent encore (le LiDAR ne voit pas au ras du robot)
TOLERANCE = 0.10             # m, arrivée sur un nœud
CAP_AVANT_DEPART = 0.35      # rad : au-delà, le robot tourne sur place avant d'avancer
ATTENTE_BLOQUE = 30.0        # s devant un obstacle avant de déclarer le couloir bloqué
ODOM_PERDUE = 10.0           # s sans /odom : échec
FREQUENCE = 20.0             # Hz, boucle de conduite
ATTENTE_GUIDE = 90.0         # s pour que le guide (Nav2) publie son état


def _angle(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


# ================================================================ le tour (sans ROS)

def graphe_etage(itineraires, etage):
    """Nœuds {id: (x, y)} et couloirs [(a, b)] de l'étage (couloirs en double retirés)."""
    noeuds = {i: (n.x, n.y) for i, n in itineraires.noeuds.items() if n.etage == etage}
    aretes, vues = [], set()
    for a, b in itineraires.couloirs:
        cle = frozenset((a, b))
        if a in noeuds and b in noeuds and a != b and cle not in vues:
            vues.add(cle)
            aretes.append((a, b))
    return noeuds, aretes


def _longueur(noeuds, a, b):
    return math.hypot(noeuds[b][0] - noeuds[a][0], noeuds[b][1] - noeuds[a][1])


def _voisins(noeuds, aretes, interdites=()):
    voisins = {i: [] for i in noeuds}
    for a, b in aretes:
        if frozenset((a, b)) in interdites:
            continue
        d = _longueur(noeuds, a, b)
        voisins[a].append((b, d))
        voisins[b].append((a, d))
    return voisins


def plus_courts_chemins(noeuds, aretes, depart, interdites=()):
    """Dijkstra : ({nœud: distance}, {nœud: précédent}) depuis depart, sans les couloirs interdits."""
    voisins = _voisins(noeuds, aretes, interdites)
    distance, precedent = {depart: 0.0}, {}
    file = [(0.0, depart)]
    while file:
        d, n = heapq.heappop(file)
        if d > distance.get(n, math.inf):
            continue
        for m, l in voisins[n]:
            if d + l < distance.get(m, math.inf):
                distance[m], precedent[m] = d + l, n
                heapq.heappush(file, (d + l, m))
    return distance, precedent


def chemin(precedent, depart, arrivee):
    """Suite de nœuds de depart à arrivee, d'après les précédents de plus_courts_chemins."""
    suite = [arrivee]
    while suite[-1] != depart:
        suite.append(precedent[suite[-1]])
    return suite[::-1]


def composante(noeuds, aretes, depart):
    return set(plus_courts_chemins(noeuds, aretes, depart)[0])


def _appariement(impairs, distances):
    """Appariement parfait de poids minimal des nœuds impairs (exact jusqu'à 16, glouton au-delà)."""
    if len(impairs) > 16:
        reste, paires = list(impairs), []
        while reste:
            a = reste.pop(0)
            b = min(reste, key=lambda m: distances[a][m])
            reste.remove(b)
            paires.append((a, b))
        return paires
    memo = {}

    def meilleur(masque):
        if masque == 0:
            return 0.0, ()
        if masque in memo:
            return memo[masque]
        i = (masque & -masque).bit_length() - 1
        resultat = (math.inf, ())
        for j in range(i + 1, len(impairs)):
            if masque & (1 << j):
                cout, paires = meilleur(masque & ~(1 << i) & ~(1 << j))
                cout += distances[impairs[i]][impairs[j]]
                if cout < resultat[0]:
                    resultat = (cout, ((impairs[i], impairs[j]),) + paires)
        memo[masque] = resultat
        return resultat
    return list(meilleur((1 << len(impairs)) - 1)[1])


def tour_des_couloirs(noeuds, aretes, depart):
    """Circuit fermé depuis depart qui emprunte chaque couloir de sa composante au moins une fois.
    Renvoie la suite des nœuds visités [depart, ..., depart] (juste [depart] sans couloir)."""
    dedans = composante(noeuds, aretes, depart)
    multi = [(a, b) for a, b in aretes if a in dedans and b in dedans]
    if not multi:
        return [depart]
    degre = {n: 0 for n in dedans}
    for a, b in multi:
        degre[a] += 1
        degre[b] += 1
    impairs = sorted(n for n, d in degre.items() if d % 2)
    if impairs:
        calculs = {n: plus_courts_chemins(noeuds, multi, n) for n in impairs}
        distances = {n: calculs[n][0] for n in impairs}
        for a, b in _appariement(impairs, distances):      # couloirs doublés : chemin le plus court
            suite = chemin(calculs[a][1], a, b)
            multi += list(zip(suite, suite[1:]))
    # Hierholzer
    incidentes = {n: [] for n in dedans}
    for k, (a, b) in enumerate(multi):
        incidentes[a].append(k)
        incidentes[b].append(k)
    utilisee = [False] * len(multi)
    pile, circuit = [depart], []
    while pile:
        n = pile[-1]
        while incidentes[n] and utilisee[incidentes[n][-1]]:
            incidentes[n].pop()
        if incidentes[n]:
            k = incidentes[n].pop()
            utilisee[k] = True
            a, b = multi[k]
            pile.append(b if a == n else a)
        else:
            circuit.append(pile.pop())
    return circuit[::-1]


def noeud_proche(noeuds, x, y):
    return min(noeuds, key=lambda i: math.hypot(noeuds[i][0] - x, noeuds[i][1] - y))


class Tournee:
    """Suit le tour : quel nœud viser ensuite, couloirs parcourus et bloqués.

    Tant que rien n'est bloqué, on suit le circuit calculé d'avance. Après un couloir bloqué,
    on choisit à chaque nœud le couloir non parcouru le plus proche (par les couloirs libres),
    puis on revient au départ.
    """

    def __init__(self, noeuds, aretes, depart):
        self.noeuds, self.aretes, self.depart = noeuds, list(aretes), depart
        dedans = composante(noeuds, aretes, depart)
        self.a_parcourir = {frozenset(e) for e in aretes if e[0] in dedans and e[1] in dedans}
        self.hors_composante = len({frozenset(e) for e in aretes}) - len(self.a_parcourir)
        self.parcourus, self.bloques, self.injoignables = set(), set(), set()
        self.plan = deque(tour_des_couloirs(noeuds, aretes, depart)[1:])
        self.glouton = False
        self.etapes_prevues = len(self.plan)

    @property
    def restants(self):
        return self.a_parcourir - self.parcourus - self.bloques - self.injoignables

    def prochain(self, courant):
        """Prochain nœud à viser depuis le nœud courant, ou None : le tour est fini."""
        if not self.glouton:
            return self.plan[0] if self.plan else None
        interdits = self.bloques
        distance, precedent = plus_courts_chemins(self.noeuds, self.aretes, courant, interdits)
        while True:
            restants = self.restants
            if not restants:
                if courant == self.depart or self.depart not in distance:
                    return None
                return chemin(precedent, courant, self.depart)[1]
            incidents = [e for e in restants if courant in e]
            if incidents:
                autre = min((next(iter(e - {courant})) for e in incidents),
                            key=lambda m: _longueur(self.noeuds, courant, m))
                return autre
            joignables = [(min(distance.get(n, math.inf) for n in e), e) for e in restants]
            d, e = min(joignables, key=lambda t: t[0])
            if math.isinf(d):
                self.injoignables |= {e for d, e in joignables if math.isinf(d)}
                continue
            but = min(e, key=lambda n: distance.get(n, math.inf))
            return chemin(precedent, courant, but)[1]

    def arrive(self, de, a):
        self.parcourus.add(frozenset((de, a)))
        if not self.glouton and self.plan and self.plan[0] == a:
            self.plan.popleft()

    def bloque(self, de, a):
        self.bloques.add(frozenset((de, a)))
        self.glouton = True


# ================================================================ conduite (ROS 2)

class PiloteDirect:
    """Conduit le robot proxy en ligne droite par /cmd_vel, en surveillant /points."""

    def __init__(self, noeud, vitesse=VITESSE_MAX, distance_arret=DISTANCE_ARRET):
        from geometry_msgs.msg import Twist
        from nav_msgs.msg import Odometry
        from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy, qos_profile_sensor_data
        from sensor_msgs.msg import PointCloud2
        from tf2_msgs.msg import TFMessage

        from atelier.scan.apercu import Placement
        self._Twist = Twist
        self.vitesse, self.distance_arret = vitesse, distance_arret
        self._verrou = threading.Lock()
        self._placement = Placement()
        self._pose, self._instant_pose, self._sol = None, 0.0, 0.0
        self._points = deque()                    # (instant, points (N, 3) proches, dans le repère odom)
        self._cmd = noeud.create_publisher(Twist, "/cmd_vel", 10)
        noeud.create_subscription(Odometry, "/odom", self._sur_odom, qos_profile_sensor_data)
        noeud.create_subscription(PointCloud2, "/points", self._sur_points, qos_profile_sensor_data)
        statique = QoSProfile(depth=100, durability=DurabilityPolicy.TRANSIENT_LOCAL,
                              reliability=ReliabilityPolicy.RELIABLE)
        noeud.create_subscription(TFMessage, "/tf_static", self._sur_tf, statique)

    def _sur_odom(self, msg):
        p, q = msg.pose.pose.position, msg.pose.pose.orientation
        t = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
        cap = math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))
        with self._verrou:
            self._placement.ajouter_odom(t, (p.x, p.y, p.z), (q.x, q.y, q.z, q.w), msg.header.frame_id,
                                         msg.child_frame_id)
            self._pose, self._instant_pose, self._sol = (p.x, p.y, cap), time.monotonic(), p.z

    def _sur_tf(self, msg):
        from atelier.scan.carte3d import transformation
        with self._verrou:
            for tf in msg.transforms:
                t, q = tf.transform.translation, tf.transform.rotation
                self._placement.ajouter_tf(tf.child_frame_id, tf.header.frame_id,
                                           transformation((t.x, t.y, t.z), (q.x, q.y, q.z, q.w)))

    def _sur_points(self, msg):
        import numpy as np

        from atelier.scan.carte3d import ErreurCarte3d, points_du_nuage
        try:
            points = points_du_nuage(msg)
        except ErreurCarte3d:
            return
        t = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
        with self._verrou:
            monde = self._placement.placer(points, msg.header.frame_id, t)
            if monde is None or self._pose is None:
                return
            x, y, _ = self._pose
            z = monde[:, 2] - self._sol
            proches = ((np.abs(monde[:, 0] - x) < 1.5) & (np.abs(monde[:, 1] - y) < 1.5)
                       & (z > TRANCHE_OBSTACLE[0]) & (z < TRANCHE_OBSTACLE[1]))
            maintenant = time.monotonic()
            self._points.append((maintenant, monde[proches, :2]))
            while self._points and self._points[0][0] < maintenant - MEMOIRE_POINTS:
                self._points.popleft()

    def pose(self):
        with self._verrou:
            return self._pose, self._instant_pose

    def obstacle(self, direction, reste):
        """Vrai si un point récent est dans le couloir surveillé devant le robot (avant la cible)."""
        import numpy as np
        with self._verrou:
            if self._pose is None or not self._points:
                return False
            points = np.vstack([p for _, p in self._points])
            x, y, _ = self._pose
        if len(points) == 0:
            return False
        ux, uy = math.cos(direction), math.sin(direction)
        dx, dy = points[:, 0] - x, points[:, 1] - y
        devant = dx * ux + dy * uy
        cote = np.abs(dx * uy - dy * ux)
        limite = min(DEMI_PROFONDEUR + self.distance_arret, reste + 0.3)
        return bool(((devant > 0.0) & (devant < limite) & (cote < DEMI_LARGEUR)).any())

    def commander(self, vx=0.0, wz=0.0):
        msg = self._Twist()
        msg.linear.x, msg.angular.z = float(vx), float(wz)
        self._cmd.publish(msg)

    def arreter(self):
        for _ in range(5):              # VelocityControl garde la dernière consigne
            self.commander()
            time.sleep(0.04)

    def preparer(self, arret, dire):
        """Attend la première odométrie (ODOM_PERDUE secondes au plus)."""
        fin = time.monotonic() + 3 * ODOM_PERDUE
        while not arret and time.monotonic() < fin:
            if self.pose()[0] is not None:
                return True
            time.sleep(0.1)
        dire("Pas d'odométrie sur /odom : la simulation tourne-t-elle (même ROS_DOMAIN_ID) ?")
        return False

    def aller(self, id_noeud, cible, arret):
        """Va en ligne droite jusqu'à cible (x, y). Renvoie arrive, bloque, perdu ou arret."""
        pose, _ = self.pose()
        distance0 = math.hypot(cible[0] - pose[0], cible[1] - pose[1]) if pose else 10.0
        delai = 3.0 * distance0 / self.vitesse + 60.0
        debut, bloque_depuis = time.monotonic(), None
        try:
            while not arret:
                maintenant = time.monotonic()
                pose, recu = self.pose()
                if pose is None or maintenant - recu > ODOM_PERDUE:
                    return "perdu"
                dx, dy = cible[0] - pose[0], cible[1] - pose[1]
                reste = math.hypot(dx, dy)
                if reste < TOLERANCE:
                    return "arrive"
                direction = math.atan2(dy, dx)
                ecart = _angle(direction - pose[2])
                if abs(ecart) > CAP_AVANT_DEPART:          # tourner sur place vers la cible
                    self.commander(0.0, max(-ROTATION_MAX, min(ROTATION_MAX, 1.5 * ecart)))
                elif self.obstacle(direction, reste):
                    self.commander()
                    bloque_depuis = bloque_depuis or maintenant
                    if maintenant - bloque_depuis > ATTENTE_BLOQUE:
                        return "bloque"
                else:
                    bloque_depuis = None
                    vx = min(self.vitesse, max(0.08, 0.8 * reste))
                    self.commander(vx, max(-0.6, min(0.6, 2.0 * ecart)))
                if maintenant - debut > delai:
                    return "bloque"
                time.sleep(1.0 / FREQUENCE)
            return "arret"
        finally:
            self.arreter()

    def fermer(self):
        self.arreter()


class PiloteGuide:
    """Envoie le robot de nœud en nœud par le guide (/guide/aller, /guide/etat) et Nav2."""

    def __init__(self, noeud, lieu, etage, journal=None):
        from nav_msgs.msg import Odometry
        from rclpy.qos import qos_profile_sensor_data
        from std_msgs.msg import Empty, String
        self._String, self._Empty = String, Empty
        self.lieu, self.etage, self.journal = lieu, etage, journal
        self._verrou = threading.Lock()
        self._etat, self._instant_etat = None, 0.0
        self._pose, self._instant_pose = None, 0.0
        self._aller = noeud.create_publisher(String, "/guide/aller", 10)
        self._stop = noeud.create_publisher(Empty, "/guide/stop", 10)
        noeud.create_subscription(String, "/guide/etat", self._sur_etat, 10)
        noeud.create_subscription(Odometry, "/odom", self._sur_odom, qos_profile_sensor_data)
        self._lance = None

    def _sur_etat(self, msg):
        try:
            etat = json.loads(msg.data)
        except ValueError:
            return
        with self._verrou:
            self._etat, self._instant_etat = etat, time.monotonic()

    def _sur_odom(self, msg):
        p, q = msg.pose.pose.position, msg.pose.pose.orientation
        cap = math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))
        with self._verrou:
            self._pose, self._instant_pose = (p.x, p.y, cap), time.monotonic()

    def pose(self):
        with self._verrou:
            return self._pose, self._instant_pose

    def etat(self):
        with self._verrou:
            return self._etat, self._instant_etat

    def preparer(self, arret, dire):
        fin = time.monotonic() + 4.0
        while not arret and time.monotonic() < fin and self.etat()[0] is None:
            time.sleep(0.1)
        if self.etat()[0] is None and not arret:
            from atelier import RACINE
            commande = [str(RACINE / "bin" / "g1-guide"), "navigation", "--lieu", str(self.lieu),
                        "--etage", self.etage, "--simu"]
            dire("Le guide ne tourne pas : lancement de " + " ".join(commande))
            sortie = open(self.journal, "ab") if self.journal else subprocess.DEVNULL
            from atelier.scan.session import _mort_du_parent       # SIGTERM au guide si l'exploration meurt
            self._lance = subprocess.Popen(commande, stdout=sortie, stderr=subprocess.STDOUT,
                                           stdin=subprocess.DEVNULL, start_new_session=True,
                                           preexec_fn=_mort_du_parent)
            fin = time.monotonic() + ATTENTE_GUIDE
            while not arret and time.monotonic() < fin and self.etat()[0] is None:
                if self._lance.poll() is not None:
                    break
                time.sleep(0.2)
        while not arret and self.pose()[0] is None and time.monotonic() < fin + ODOM_PERDUE:
            time.sleep(0.1)
        if self.etat()[0] is None or self.pose()[0] is None:
            dire("Le guide ne publie pas /guide/etat, ou pas d'odométrie : voir le journal du guide.")
            return False
        return True

    def aller(self, id_noeud, cible, arret, delai=240.0, essais=6):
        """Envoie le robot vers le nœud ; renvoie arrive, bloque ou arret."""
        for essai in range(essais):
            envoi = time.monotonic()
            self._aller.publish(self._String(data=id_noeud))
            while not arret:
                etat, quand = self.etat()
                if etat and quand > envoi + 0.3 and etat.get("cible") == id_noeud:
                    if etat.get("etat") == "arrive":
                        return "arrive"
                    if etat.get("etat") == "echec":
                        break
                if time.monotonic() - envoi > delai:
                    self._stop.publish(self._Empty())
                    return "bloque"
                time.sleep(0.1)
            if arret:
                break
            time.sleep(3.0)                     # Nav2 démarre peut-être encore : on réessaie
        if arret:
            self._stop.publish(self._Empty())
            return "arret"
        return "bloque"

    def fermer(self):
        try:
            self._stop.publish(self._Empty())
        except Exception:
            pass
        if self._lance is not None and self._lance.poll() is None:
            for sig, attente in ((signal.SIGINT, 15), (signal.SIGTERM, 5), (signal.SIGKILL, 2)):
                try:
                    os.killpg(self._lance.pid, sig)
                except ProcessLookupError:
                    break
                try:
                    self._lance.wait(attente)
                    break
                except subprocess.TimeoutExpired:
                    continue


def explorer(lieu, etage, pilote, arret, dire=print, noter=None):
    """Fait le tour des couloirs. noter(message) : progression pour l'utilisateur. Renvoie 0 ou 1."""
    from atelier.lieu import charger_itineraires
    noeuds, aretes = graphe_etage(charger_itineraires(lieu), etage)
    if len(noeuds) < 2 or not aretes:
        dire(f"L'étage {etage} n'a pas deux nœuds reliés dans itineraires.yaml : rien à explorer.")
        return 1
    if not pilote.preparer(arret, dire):
        return 1
    pose, _ = pilote.pose()
    depart = noeud_proche(noeuds, pose[0], pose[1])
    tournee = Tournee(noeuds, aretes, depart)
    longueur = sum(_longueur(noeuds, *tuple(e)) for e in tournee.a_parcourir)
    dire(f"Tour de {len(tournee.a_parcourir)} couloirs ({longueur:.0f} m), depuis le nœud {depart} : "
         + " → ".join([depart] + list(tournee.plan)))
    if tournee.hors_composante:
        dire(f"Attention : {tournee.hors_composante} couloir(s) ne sont pas reliés au nœud {depart} : "
             "ils ne seront pas parcourus.")
    debut = time.monotonic()
    if math.hypot(noeuds[depart][0] - pose[0], noeuds[depart][1] - pose[1]) > TOLERANCE:
        dire(f"Vers le nœud de départ {depart}")
        resultat = pilote.aller(depart, noeuds[depart], arret)
        if resultat in ("perdu", "bloque"):
            dire(f"Impossible de rejoindre le nœud {depart} ({resultat}).")
            return 1
    courant, etape = depart, 0
    while not arret:
        suivant = tournee.prochain(courant)
        if suivant is None:
            break
        etape += 1
        message = (f"Exploration : couloir {len(tournee.parcourus) + 1} sur {len(tournee.a_parcourir)}, "
                   f"de « {courant} » vers « {suivant} »")
        dire(message)
        if noter:
            noter(message + ".")
        resultat = pilote.aller(suivant, noeuds[suivant], arret)
        if resultat == "arrive":
            tournee.arrive(courant, suivant)
            courant = suivant
        elif resultat == "bloque":
            dire(f"Couloir {courant} → {suivant} bloqué : retour à {courant} ; le tour continue par les autres "
                 "couloirs.")
            tournee.bloque(courant, suivant)
            if pilote.aller(courant, noeuds[courant], arret) not in ("arrive", "arret"):
                dire(f"Le robot ne peut pas revenir au nœud {courant} : exploration abandonnée.")
                return 1
        elif resultat == "perdu":
            dire("Odométrie perdue : exploration abandonnée.")
            return 1
    if arret:
        dire("Exploration arrêtée à la demande.")
        return 0
    duree = time.monotonic() - debut
    bilan = (f"Tour terminé en {duree:.0f} s : {len(tournee.parcourus)} couloir(s) parcouru(s) sur "
             f"{len(tournee.a_parcourir)}")
    if tournee.bloques:
        bilan += f", {len(tournee.bloques)} bloqué(s) : " + ", ".join(" – ".join(sorted(e)) for e in tournee.bloques)
    if tournee.injoignables:
        bilan += f", {len(tournee.injoignables)} injoignable(s)"
    dire(bilan + ".")
    return 0


def principal(argv=None):
    p = argparse.ArgumentParser(prog="exploration", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--lieu", required=True)
    p.add_argument("--etage", required=True)
    p.add_argument("--session", help="session de scan dont on met à jour le message (progression)")
    p.add_argument("--pilote", choices=["direct", "guide"], default="direct")
    p.add_argument("--vitesse", type=float, default=VITESSE_MAX, help="m/s (défaut 0,4)")
    p.add_argument("--distance-arret", type=float, default=DISTANCE_ARRET, help="m (défaut 0,6)")
    p.add_argument("--journal-guide", help="journal de g1-guide navigation, s'il faut le lancer")
    args = p.parse_args(argv)
    if args.vitesse <= 0 or args.vitesse > VITESSE_MAX:
        print(f"Vitesse de {args.vitesse:g} m/s refusée : entre 0 et {VITESSE_MAX:g} m/s.")
        return 2

    import rclpy
    from rclpy.executors import SingleThreadedExecutor
    from rclpy.signals import SignalHandlerOptions

    arret = []
    signal.signal(signal.SIGINT, lambda *_: arret.append(1))
    signal.signal(signal.SIGTERM, lambda *_: arret.append(1))

    def dire(texte):
        print(f"{time.strftime('%H:%M:%S')} {texte}", flush=True)

    def noter(message):
        if not args.session:
            return
        from atelier.lieu import ErreurLieu, maj_session
        try:
            maj_session(args.lieu, args.session, message=message)
        except ErreurLieu:
            pass

    rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
    noeud = rclpy.create_node("g1_scan_exploration")
    executeur = SingleThreadedExecutor()
    executeur.add_node(noeud)

    def tourner():
        try:
            executeur.spin()
        except Exception:            # arrêt de rclpy pendant l'attente : normal
            pass
    fil = threading.Thread(target=tourner, daemon=True)
    if args.pilote == "direct":
        pilote = PiloteDirect(noeud, args.vitesse, args.distance_arret)
    else:
        pilote = PiloteGuide(noeud, args.lieu, args.etage, args.journal_guide)
    fil.start()
    try:
        return explorer(args.lieu, args.etage, pilote, arret, dire, noter)
    finally:
        pilote.fermer()
        executeur.shutdown(timeout_sec=2.0)
        fil.join(timeout=2.0)
        noeud.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    sys.exit(principal())
