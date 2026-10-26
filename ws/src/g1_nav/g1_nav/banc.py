"""
Banc de test du guide : N trajets entre salles tirées au sort, un CSV et un résumé.

  g1-banc --lieu demo --etage rdc --trajets 20 [--simu] [--lancer] [--graine 1]

Le banc parle au guide par ses sujets (/guide/aller, /guide/etat) et suit le robot par TF
(map → base_link). Il faut donc que la navigation tourne (g1-guide navigation ...), et en
simulation Gazebo (g1-monde simuler ...). --lancer démarre les deux lui-même, sans fenêtre,
et les arrête à la fin.

Une ligne du CSV par trajet : départ, arrivée, réussite (arrive à 0,3 m au plus de la pose de
la salle), durée, nombre d'arrêts (passages à « bloque »), distance minimale aux piétons
(centre à centre, positions calculées depuis monde.yaml et le temps simulé), détours.
Par défaut, le CSV va dans ~/robot-g1/journaux/.
"""
import csv
import datetime
from dataclasses import asdict, dataclass, fields
import json
import math
import os
from pathlib import Path
import random
import signal
import subprocess
import sys
import time

# Le robot doit s'arrêter à TOLERANCE_ARRIVEE_M au plus de la pose de la salle (critère 4)
TOLERANCE_ARRIVEE_M = 0.3
# Pause après l'arrêt d'un trajet trop long, avant le suivant (s)
PAUSE_APRES_STOP_S = 1.0
ETATS_FINAUX = ('arrive', 'echec')


@dataclass
class Resultat:
    """Une ligne du CSV : un trajet."""

    numero: int
    depart: str
    arrivee: str
    reussite: bool
    duree_s: float
    arrets: int
    distance_min_pietons_m: object     # float, ou '' sans piéton
    detours: int
    erreur_m: object                   # distance finale à la pose de la salle, ou ''
    etat_final: str


COLONNES = [f.name for f in fields(Resultat)]


def tirer_trajets(salles, n, depart, graine=None):
    """N trajets (départ, arrivée) : chaque arrivée est tirée parmi les autres salles."""
    if len(salles) < 2:
        raise ValueError('il faut au moins deux salles sur l\'étage pour faire des trajets')
    hasard = random.Random(graine)
    trajets = []
    for _ in range(n):
        arrivee = hasard.choice([s for s in salles if s != depart])
        trajets.append((depart, arrivee))
        depart = arrivee
    return trajets


def salle_proche(poses_salles, position):
    """Id de la salle la plus proche de la position (x, y, ...), ou None."""
    if position is None or not poses_salles:
        return None
    return min(poses_salles, key=lambda s: math.dist(poses_salles[s][:2], position[:2]))


class SuiviTrajet:
    """Suit un trajet à partir des états du guide et des positions du robot."""

    def __init__(self, cible, pose_cible, pietons=(), position_pieton=None):
        self.cible = cible
        self.pose_cible = pose_cible
        self.pietons = list(pietons)
        self.position_pieton = position_pieton
        self.arrets = 0
        self.detours = 0
        self.distance_min = math.inf
        self.etat = None
        self.position = None

    @property
    def fini(self):
        return self.etat in ETATS_FINAUX

    def noter(self, etat, position, t):
        """Prend en compte un état du guide (dict ou None), la position du robot et le temps."""
        if position is not None:
            self.position = position
            if self.position_pieton is not None:
                for pieton in self.pietons:
                    x, y, _ = self.position_pieton(pieton, t)
                    self.distance_min = min(self.distance_min, math.dist((x, y), position[:2]))
        # Les états d'un trajet précédent (autre cible) sont ignorés
        if etat is None or etat.get('cible') != self.cible:
            return
        nouveau = etat.get('etat')
        if nouveau != self.etat:
            if nouveau == 'bloque':
                self.arrets += 1
            elif nouveau == 'detour':
                self.detours += 1
        self.etat = nouveau

    def resultat(self, numero, depart, duree_s):
        """Ligne du CSV pour ce trajet."""
        erreur = None
        if self.position is not None and self.pose_cible is not None:
            erreur = math.dist(self.position[:2], self.pose_cible[:2])
        reussite = self.etat == 'arrive' and (erreur is None or erreur <= TOLERANCE_ARRIVEE_M)
        return Resultat(
            numero=numero, depart=depart, arrivee=self.cible, reussite=reussite,
            duree_s=round(duree_s, 1), arrets=self.arrets,
            distance_min_pietons_m=('' if math.isinf(self.distance_min)
                                    else round(self.distance_min, 2)),
            detours=self.detours, erreur_m='' if erreur is None else round(erreur, 3),
            etat_final=self.etat or 'sans_reponse')


def executer(client, trajets, poses_salles, pietons=(), position_pieton=None, delai_s=180.0,
             pas_s=0.2, journal=print):
    """
    Fait les trajets un par un et renvoie la liste des Resultat.

    client : objet avec aller(cible), stop(), etat() (dernier état du guide, dict ou None),
    position() ((x, y, theta) ou None), temps() (secondes, temps simulé) et attendre(s).
    """
    resultats = []
    for numero, (depart, arrivee) in enumerate(trajets, 1):
        depart = salle_proche(poses_salles, client.position()) or depart
        suivi = SuiviTrajet(arrivee, poses_salles.get(arrivee), pietons, position_pieton)
        t0 = client.temps()
        client.aller(arrivee)
        while not suivi.fini and client.temps() - t0 < delai_s:
            client.attendre(pas_s)
            suivi.noter(client.etat(), client.position(), client.temps())
        if not suivi.fini:
            client.stop()
            suivi.etat = 'delai_depasse'
        resultat = suivi.resultat(numero, depart, client.temps() - t0)
        resultats.append(resultat)
        journal(f'trajet {numero}/{len(trajets)} : {depart} → {arrivee} : '
                f'{"réussi" if resultat.reussite else "raté (" + resultat.etat_final + ")"}, '
                f'{resultat.duree_s:.0f} s, {resultat.arrets} arrêt(s), '
                f'{resultat.detours} détour(s)')
        if suivi.etat == 'delai_depasse':
            # /guide/stop et /guide/aller sont deux sujets : DDS ne garde pas leur ordre. Sans
            # cette pause, le guide pouvait recevoir le trajet suivant avant l'arrêt de celui-ci,
            # puis l'arrêter aussitôt (trajet « cdi → cdi » raté sans bouger, le 26/10).
            client.attendre(PAUSE_APRES_STOP_S)
    return resultats


def ecrire_csv(chemin, resultats):
    """Écrit le CSV, une ligne par trajet, avec l'en-tête COLONNES."""
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with open(chemin, 'w', newline='', encoding='utf-8') as f:
        ecrivain = csv.DictWriter(f, fieldnames=COLONNES)
        ecrivain.writeheader()
        for r in resultats:
            ligne = asdict(r)
            ligne['reussite'] = 'oui' if r.reussite else 'non'
            ecrivain.writerow(ligne)
    return chemin


def taux_reussite(resultats):
    """Part des trajets réussis, entre 0 et 1 (0 sans trajet)."""
    return sum(r.reussite for r in resultats) / len(resultats) if resultats else 0.0


def resume(resultats):
    """Résumé à afficher à l'écran."""
    if not resultats:
        return 'Aucun trajet.'
    reussis = [r for r in resultats if r.reussite]
    lignes = [f'Réussite : {len(reussis)} / {len(resultats)} trajets '
              f'({100 * taux_reussite(resultats):.0f} %)']
    if reussis:
        durees = [r.duree_s for r in reussis]
        lignes.append(f'Durée des trajets réussis : moyenne {sum(durees) / len(durees):.0f} s, '
                      f'maximum {max(durees):.0f} s')
    lignes.append(f'Arrêts (bloque) : {sum(r.arrets for r in resultats)} ; '
                  f'détours : {sum(r.detours for r in resultats)}')
    distances = [r.distance_min_pietons_m for r in resultats if r.distance_min_pietons_m != '']
    if distances:
        lignes.append(f'Distance minimale aux piétons : {min(distances):.2f} m')
    rates = [r for r in resultats if not r.reussite]
    for r in rates:
        lignes.append(f'  raté : trajet {r.numero} {r.depart} → {r.arrivee} ({r.etat_final}'
                      + (f', à {r.erreur_m} m' if r.erreur_m != '' else '') + ')')
    return '\n'.join(lignes)


# ---------------------------------------------------------------- client ROS 2


class ClientRos:
    """Parle au guide par ses sujets ROS 2 ; position du robot par TF map → base_link."""

    def __init__(self, simu):
        import rclpy
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.parameter import Parameter
        from std_msgs.msg import Empty, String
        import tf2_ros

        self.rclpy = rclpy
        self.noeud = rclpy.create_node(
            'banc', parameter_overrides=[Parameter('use_sim_time', Parameter.Type.BOOL, simu)])
        self.String, self.Empty = String, Empty
        self.pub_aller = self.noeud.create_publisher(String, '/guide/aller', 10)
        self.pub_stop = self.noeud.create_publisher(Empty, '/guide/stop', 10)
        self.noeud.create_subscription(String, '/guide/etat', self._sur_etat, 10)
        self.tampon_tf = tf2_ros.Buffer()
        self.ecoute_tf = tf2_ros.TransformListener(self.tampon_tf, self.noeud)
        self.executeur = SingleThreadedExecutor()
        self.executeur.add_node(self.noeud)
        self._etat = None

    def _sur_etat(self, msg):
        try:
            self._etat = json.loads(msg.data)
        except ValueError:
            pass

    def attendre(self, duree_s):
        fin = time.monotonic() + duree_s
        while True:
            reste = fin - time.monotonic()
            if reste <= 0:
                return
            self.executeur.spin_once(timeout_sec=reste)

    def attendre_guide(self, delai_s, nav2=True):
        """Attend le guide (il publie et écoute) et Nav2 actif. Renvoie None, ou le problème."""
        fin = time.monotonic() + delai_s
        while time.monotonic() < fin:
            self.attendre(0.5)
            if self._etat is not None and self.pub_aller.get_subscription_count() > 0:
                break
        else:
            return 'le guide ne publie pas /guide/etat'
        if nav2 and not self._nav2_actif(fin):
            return 'Nav2 n\'est pas actif (bt_navigator)'
        while self.position() is None and time.monotonic() < fin:
            self.attendre(0.5)
        return None if self.position() is not None else 'position du robot inconnue (TF)'

    def _nav2_actif(self, fin):
        from lifecycle_msgs.srv import GetState
        client = self.noeud.create_client(GetState, '/bt_navigator/get_state')
        while time.monotonic() < fin:
            if client.wait_for_service(timeout_sec=0.5):
                futur = client.call_async(GetState.Request())
                self.executeur.spin_until_future_complete(futur, timeout_sec=2.0)
                if futur.result() is not None and futur.result().current_state.label == 'active':
                    return True
            self.attendre(1.0)
        return False

    def aller(self, cible):
        self.pub_aller.publish(self.String(data=cible))

    def stop(self):
        self.pub_stop.publish(self.Empty())

    def etat(self):
        return self._etat

    def position(self):
        from atelier.lieu.conversions import quaternion_vers_cap
        from rclpy.time import Time
        try:
            t = self.tampon_tf.lookup_transform('map', 'base_link', Time())
        except Exception:
            return None
        return (t.transform.translation.x, t.transform.translation.y,
                quaternion_vers_cap(t.transform.rotation))

    def temps(self):
        return self.noeud.get_clock().now().nanoseconds * 1e-9

    def fermer(self):
        self.executeur.shutdown()
        self.noeud.destroy_node()


# ---------------------------------------------------------------- lancement de la simulation


def lancer(commande, journal_fichier):
    """Lance une commande dans son propre groupe de processus, sortie dans un journal."""
    sortie = open(journal_fichier, 'w', encoding='utf-8')
    return subprocess.Popen(commande, stdout=sortie, stderr=subprocess.STDOUT,
                            start_new_session=True)


def arreter(processus, delai_s=20.0):
    """Arrête un groupe de processus : Ctrl+C, puis SIGTERM, puis SIGKILL."""
    for sig, attente in ((signal.SIGINT, delai_s), (signal.SIGTERM, 5.0), (signal.SIGKILL, 5.0)):
        if processus.poll() is not None:
            break
        try:
            os.killpg(processus.pid, sig)
        except ProcessLookupError:
            break
        try:
            processus.wait(timeout=attente)
        except subprocess.TimeoutExpired:
            continue
    # Les enfants peuvent survivre au parent (Gazebo) : on vide le groupe
    try:
        os.killpg(processus.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def main(argv=None):
    import atelier
    from atelier.lieu import charger_monde, charger_salles, chemin_monde
    from g1_nav.commande import Analyseur

    p = Analyseur(
        prog='g1-banc', description='Banc de test du guide : N trajets entre salles tirées au '
                                    'sort, résultats en CSV.')
    p.add_argument('--lieu', required=True, help='dossier du lieu, ou id seul (ex. demo)')
    p.add_argument('--etage', required=True, help='id de l\'étage (ex. rdc)')
    p.add_argument('--trajets', type=int, default=20, help='nombre de trajets (défaut 20)')
    p.add_argument('--graine', type=int, default=None, help='graine du tirage, pour le refaire')
    p.add_argument('--delai', type=float, default=180.0,
                   help='durée maximale d\'un trajet, en secondes (défaut 180)')
    p.add_argument('--csv', default=None, help='fichier CSV (défaut : ~/robot-g1/journaux/)')
    p.add_argument('--simu', action='store_true', help='temps simulé (Gazebo)')
    p.add_argument('--lancer', action='store_true',
                   help='lance aussi la simulation sans fenêtre et la navigation, puis les arrête')
    p.add_argument('--moteur', default='nav2', choices=['nav2', 'unitree'],
                   help='moteur du guide (défaut nav2)')
    p.add_argument('--seuil', type=float, default=0.0,
                   help='réussite minimale en %% ; en dessous, code de sortie 1')
    args = p.parse_args(argv)

    dossier = atelier.chemin_lieu(args.lieu)
    salles = [s for s in charger_salles(dossier) if s.etage == args.etage]
    poses = {s.id: (s.pose.x, s.pose.y, s.pose.theta) for s in salles}
    pietons, position_pieton = [], None
    if chemin_monde(dossier, args.etage).is_file():
        pietons = charger_monde(dossier, args.etage).pietons
        try:
            from atelier.monde.pietons import position_pieton
        except ImportError:
            pietons = []
    horodatage = datetime.datetime.now().strftime('%Y-%m-%d_%Hh%M%S')
    journaux = atelier.dossier_journaux()
    chemin_csv = Path(args.csv) if args.csv else \
        journaux / f'banc_{dossier.name}_{args.etage}_{horodatage}.csv'

    processus = []
    if args.lancer:
        args.simu = True
        print(f'Lancement de la simulation et de la navigation (journaux dans {journaux})')
        processus.append(lancer(
            ['ros2', 'launch', 'g1_sim', 'simulation.launch.py', f'lieu:={dossier}',
             f'etage:={args.etage}', 'sans_fenetre:=true'],
            journaux / f'banc_{horodatage}_simulation.log'))
        time.sleep(5.0)
        processus.append(lancer(
            ['ros2', 'launch', 'g1_nav', 'navigation.launch.py', f'lieu:={dossier}',
             f'etage:={args.etage}', 'simu:=true', f'moteur:={args.moteur}'],
            journaux / f'banc_{horodatage}_navigation.log'))

    import rclpy
    rclpy.init()
    client = ClientRos(args.simu)
    try:
        probleme = client.attendre_guide(120.0 if args.lancer else 20.0, args.moteur == 'nav2')
        if probleme:
            print(f'g1-banc : {probleme}. Lancez d\'abord : g1-guide navigation '
                  f'--lieu {args.lieu} --etage {args.etage}' + (' --simu' if args.simu else ''),
                  file=sys.stderr)
            return 1
        depart = salle_proche(poses, client.position())
        trajets = tirer_trajets(sorted(poses), args.trajets, depart, args.graine)
        print(f'{len(trajets)} trajets, départ de « {depart} »'
              + (f', {len(pietons)} piéton(s)' if pietons else ''))
        resultats = executer(client, trajets, poses, pietons, position_pieton, args.delai)
        ecrire_csv(chemin_csv, resultats)
        print()
        print(resume(resultats))
        print(f'CSV : {chemin_csv}')
        return 0 if 100 * taux_reussite(resultats) >= args.seuil else 1
    except KeyboardInterrupt:
        client.stop()
        print('\nBanc interrompu.')
        return 130
    finally:
        client.fermer()
        rclpy.try_shutdown()
        for proc in reversed(processus):
            arreter(proc)


if __name__ == '__main__':
    sys.exit(main())
