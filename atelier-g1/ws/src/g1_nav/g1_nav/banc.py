"""
Banc de test du guide : trajets tirés au sort, ou ceux d'une scène, un CSV et un résumé.

  g1-banc --lieu demo --etage rdc --trajets 20 [--simu] [--lancer] [--graine 1]
  g1-banc --scene en_face [--reaction aucune|arret|ecart] [--csv F]

Le banc parle au guide par ses sujets (/guide/aller, /guide/etat) et suit le robot par TF
(map → base_link). Il faut donc que la navigation tourne (g1-guide navigation ...), et en
simulation Gazebo (g1-monde simuler ...). --lancer démarre les deux lui-même, sans fenêtre,
et les arrête à la fin.

--scene ID (vague 4, section 11.3 du plan) : copie le lieu de référence de la scène dans
~/robot-g1/journaux/banc_<scène>_<heure>/ (jamais lieux/demo lui-même), y applique la scène
(atelier.monde.scene : ses piétons, ses réglages du guide), lance la simulation et la
navigation sur la copie, fait ses trajets (chaque essai repart du départ : le robot y est
reposé dans Gazebo, et les piétons-corps reprennent la scène au début, par
/pietons/reinitialiser), puis vérifie ses seuils (mesures) : code de sortie 1 si l'un manque.

Une ligne du CSV par trajet. Colonnes de la vague 1 : départ, arrivée, réussite (arrive à
0,3 m au plus de la pose de la salle), durée, nombre d'arrêts (passages à « bloque »),
distance minimale aux piétons (centre à centre), détours, erreur finale, état final. Colonnes
de la vague 4 (atelier.lieu.passants.COLONNES_BANC_V4), mesurées 20 fois par seconde sur la
vérité terrain du robot (/odom en simulation, --verite sinon) et sur /pietons/etat (sans lui :
positions calculées depuis monde.yaml) : scène, distance minimale bord à bord, contacts (et qui
avançait vers l'autre : robot, piéton, aucun), temps arrêté près d'un piéton, attentes de
passage (état attente_passage du guide) et leur durée, longueur parcourue et longueur de
l'itinéraire direct.
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

from atelier.lieu.passants import (COLONNES_BANC_V4, DISTANCE_PRES_M, SuiviContacts, distance_bord,
                                   reglages_pieton)

# Le robot doit s'arrêter à TOLERANCE_ARRIVEE_M au plus de la pose de la salle (critère 4)
TOLERANCE_ARRIVEE_M = 0.3
# Pause après l'arrêt d'un trajet trop long, avant le suivant (s)
PAUSE_APRES_STOP_S = 1.0
ETATS_FINAUX = ('arrive', 'echec')
# Mesures : 20 par seconde au moins (contrat 11.3)
PAS_MESURE_S = 0.05
VITESSE_ARRET_M_S = 0.02        # robot « arrêté » sous cette vitesse (temps_arret_pres_s)
SAUT_MAX_M = 1.0                # déplacement plus grand entre deux mesures : robot reposé
PIETONS_FRAIS_S = 1.0           # /pietons/etat plus vieux : positions calculées depuis le monde
EXTRAPOLATION_MAX_S = 0.3       # positions des piétons prolongées par leur vitesse, au plus
DELAI_ETAT_PERIME_S = 5.0       # un état final d'avant le départ est ignoré au plus ce temps
NOM_ROBOT_GAZEBO = 'g1_proxy'


@dataclass
class Resultat:
    """Une ligne du CSV : un trajet (colonnes de la vague 1, puis celles de la vague 4)."""

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
    # vague 4 (section 11.3 du plan) : COLONNES_BANC_V4, dans cet ordre
    scene: str = ''
    distance_min_bord_m: object = ''   # float, ou '' sans piéton
    contacts: int = 0
    contacts_robot: int = 0
    contacts_pieton: int = 0
    contacts_aucun: int = 0
    temps_arret_pres_s: float = 0.0
    attentes_passage: int = 0
    duree_attente_passage_s: float = 0.0
    longueur_m: float = 0.0
    longueur_directe_m: object = ''    # float, ou '' si l'itinéraire est inconnu


COLONNES = [f.name for f in fields(Resultat)]
COLONNES_V1 = COLONNES[:COLONNES.index('scene')]
assert tuple(COLONNES[len(COLONNES_V1):]) == COLONNES_BANC_V4


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
    """Suit un trajet à partir des états du guide, des positions du robot et des piétons."""

    def __init__(self, cible, pose_cible, pietons=(), position_pieton=None, etat_avant=None,
                 scene='', longueur_directe=None):
        self.cible = cible
        self.pose_cible = pose_cible
        self.pietons = list(pietons)
        self.position_pieton = position_pieton
        self.scene = scene or ''
        self.longueur_directe = longueur_directe
        self.arrets = 0
        self.detours = 0
        self.distance_min = math.inf
        self.etat = None
        self.position = None
        # vague 4
        self.contacts = SuiviContacts()
        self.attentes_passage = 0
        self.duree_attente_passage = 0.0
        self.temps_arret_pres = 0.0
        self.longueur = 0.0
        self._t = None
        self._robot = None             # (x, y) de la mesure précédente
        self._pietons_avant = {}       # id → (t, x, y), pour leurs vitesses par différences
        # état final d'un trajet d'avant vers la même cible (robot reposé) : ignoré
        self._perime = None
        if etat_avant and etat_avant.get('etat') in ETATS_FINAUX:
            self._perime = (etat_avant.get('etat'), etat_avant.get('cible'))
        self._t_depart = None
        self.transitions = []          # [(t depuis le départ, état, (x, y) ou None)]
        self.dernier_detour = None     # heure murale (monotone) du dernier détour

    @property
    def fini(self):
        return self.etat in ETATS_FINAUX

    def _pietons_calcules(self, t):
        """Piétons calculés depuis le monde (sans /pietons/etat) : (id, x, y, vx, vy, rayon)."""
        resultat = []
        for pieton in self.pietons:
            x, y = self.position_pieton(pieton, t)[:2]
            avant = self._pietons_avant.get(pieton.id)
            vx = vy = 0.0
            if avant is not None and t > avant[0]:
                vx, vy = (x - avant[1]) / (t - avant[0]), (y - avant[2]) / (t - avant[0])
            self._pietons_avant[pieton.id] = (t, x, y)
            resultat.append((pieton.id, x, y, vx, vy, float(reglages_pieton(pieton)['rayon_m'])))
        return resultat

    def noter(self, etat, position, t, verite=None, pietons=None):
        """
        Prend en compte un état du guide (dict ou None), la position du robot et le temps.

        verite : (x, y, vx, vy) vrais du robot dans map (sinon : position, vitesses par
        différences) ; pietons : [(id, x, y, vx, vy, rayon_m)] mesurés (sinon : calculés
        depuis le monde, si position_pieton est donné).
        """
        if self._t_depart is None:
            self._t_depart = t
        dt = 0.0 if self._t is None else max(0.0, t - self._t)
        self._t = t
        if position is not None:
            self.position = position
        robot = None
        if verite is not None:
            robot = tuple(float(v) for v in verite[:4])
        elif position is not None:
            vx = vy = 0.0
            if self._robot is not None and dt > 0:
                vx, vy = (position[0] - self._robot[0]) / dt, (position[1] - self._robot[1]) / dt
            robot = (float(position[0]), float(position[1]), vx, vy)
        if robot is not None:
            if self._robot is not None:
                pas = math.dist(robot[:2], self._robot)
                if pas < SAUT_MAX_M:
                    self.longueur += pas
            self._robot = robot[:2]
            if pietons is None and self.position_pieton is not None and self.pietons:
                pietons = self._pietons_calcules(t)
            if pietons:
                self.contacts.noter(t, robot, pietons)
                proche = min(distance_bord(robot, p[1:3], p[5]) for p in pietons)
                for p in pietons:
                    self.distance_min = min(self.distance_min, math.dist(p[1:3], robot[:2]))
                if math.hypot(robot[2], robot[3]) < VITESSE_ARRET_M_S and proche < DISTANCE_PRES_M:
                    self.temps_arret_pres += dt
        # États d'un trajet précédent (autre cible, état final d'avant le départ) : ignorés
        if etat is None or etat.get('cible') != self.cible:
            return
        if self._perime is not None:
            meme = (etat.get('etat'), etat.get('cible')) == self._perime
            if meme and t - self._t_depart < DELAI_ETAT_PERIME_S:
                return
            self._perime = None
        nouveau = etat.get('etat')
        if nouveau == 'attente_passage' and self.etat == 'attente_passage':
            self.duree_attente_passage += dt
        if nouveau != self.etat:
            ou = None if self.position is None else (round(self.position[0], 2),
                                                     round(self.position[1], 2))
            self.transitions.append((round(t - self._t_depart, 1), nouveau, ou))
            if nouveau == 'bloque':
                self.arrets += 1
            elif nouveau == 'detour':
                self.detours += 1
                self.dernier_detour = time.monotonic()
            elif nouveau == 'attente_passage':
                self.attentes_passage += 1
        self.etat = nouveau

    def resultat(self, numero, depart, duree_s):
        """Ligne du CSV pour ce trajet."""
        erreur = None
        if self.position is not None and self.pose_cible is not None:
            erreur = math.dist(self.position[:2], self.pose_cible[:2])
        reussite = self.etat == 'arrive' and (erreur is None or erreur <= TOLERANCE_ARRIVEE_M)
        contacts = self.contacts.resume()
        bord = contacts['distance_min_bord_m']
        directe = self.longueur_directe
        return Resultat(
            numero=numero, depart=depart, arrivee=self.cible, reussite=reussite,
            duree_s=round(duree_s, 1), arrets=self.arrets,
            distance_min_pietons_m=('' if math.isinf(self.distance_min)
                                    else round(self.distance_min, 2)),
            detours=self.detours, erreur_m='' if erreur is None else round(erreur, 3),
            etat_final=self.etat or 'sans_reponse',
            scene=self.scene,
            distance_min_bord_m='' if bord is None else bord,
            contacts=contacts['contacts'], contacts_robot=contacts['contacts_robot'],
            contacts_pieton=contacts['contacts_pieton'], contacts_aucun=contacts['contacts_aucun'],
            temps_arret_pres_s=round(self.temps_arret_pres, 1),
            attentes_passage=self.attentes_passage,
            duree_attente_passage_s=round(self.duree_attente_passage, 1),
            longueur_m=round(self.longueur, 2),
            longueur_directe_m='' if directe is None else round(directe, 2))


def longueur_directe(routeur, depart, arrivee, position=None):
    """
    Longueur (m) de l'itinéraire du départ, sans détour.

    Du robot au nœud de départ, puis le plus court chemin du graphe jusqu'à l'arrivée. None si
    elle est inconnue.
    """
    if routeur is None:
        return None
    try:
        itineraire = routeur.itineraire(depart, arrivee)
    except (ValueError, KeyError):
        return None
    if not itineraire:
        return None
    longueur = routeur.longueur(itineraire)
    if position is not None and depart in routeur.noeuds:
        longueur += math.dist(position[:2], routeur.noeuds[depart])
    return longueur


def _afficher(message):
    print(message, flush=True)


def executer(client, trajets, poses_salles, pietons=(), position_pieton=None, delai_s=180.0,
             pas_s=PAS_MESURE_S, journal=_afficher, scene='', preparer=None, routeur=None):
    """
    Fait les trajets un par un et renvoie la liste des Resultat.

    client : objet avec aller(cible), stop(), etat() (dernier état du guide, dict ou None),
    position() ((x, y, theta) ou None), temps() (secondes, temps simulé) et attendre(s) ; et,
    s'il les a, verite() ((x, y, vx, vy) vrais du robot, ou None) et pietons_mesures() ([(id,
    x, y, vx, vy, rayon)] tirés de /pietons/etat, ou None). preparer(numero, depart, arrivee) :
    appelé avant chaque trajet (scène : robot reposé au départ, piétons remis au début).
    routeur : pour la longueur de l'itinéraire direct.
    """
    verite = getattr(client, 'verite', lambda: None)
    mesures = getattr(client, 'pietons_mesures', lambda: None)
    resultats = []
    for numero, (depart, arrivee) in enumerate(trajets, 1):
        if preparer is not None:
            preparer(numero, depart, arrivee)
        position = client.position()
        depart = salle_proche(poses_salles, position) or depart
        suivi = SuiviTrajet(arrivee, poses_salles.get(arrivee), pietons, position_pieton,
                            etat_avant=client.etat(), scene=scene,
                            longueur_directe=longueur_directe(routeur, depart, arrivee, position))
        t0 = client.temps()
        client.aller(arrivee)
        while not suivi.fini and client.temps() - t0 < delai_s:
            client.attendre(pas_s)
            suivi.noter(client.etat(), client.position(), client.temps(), verite(), mesures())
        if not suivi.fini:
            client.stop()
            suivi.etat = 'delai_depasse'
        resultat = suivi.resultat(numero, depart, client.temps() - t0)
        resultats.append(resultat)
        if preparer is not None and suivi.dernier_detour is not None:
            preparer.dernier_detour = suivi.dernier_detour
        contacts = (f', {resultat.contacts} contact(s) (robot : {resultat.contacts_robot})'
                    if resultat.contacts else '')
        bord = (f', {resultat.distance_min_bord_m:.2f} m bord à bord'
                if resultat.distance_min_bord_m != '' else '')
        journal(f'trajet {numero}/{len(trajets)} : {depart} → {arrivee} : '
                f'{"réussi" if resultat.reussite else "raté (" + resultat.etat_final + ")"}, '
                f'{resultat.duree_s:.0f} s, {resultat.arrets} arrêt(s), '
                f'{resultat.detours} détour(s){bord}{contacts}')
        if not resultat.reussite or resultat.detours:
            journal('    états : ' + ', '.join(
                f'{etat} à {t:.0f} s' + (f' en ({ou[0]:g} ; {ou[1]:g})' if ou else '')
                for t, etat, ou in suivi.transitions))
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


def lire_csv(chemin):
    """Lignes d'un CSV du banc (dicts de textes), pour l'interface et les critères."""
    with open(chemin, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def taux_reussite(resultats):
    """Part des trajets réussis, entre 0 et 1 (0 sans trajet)."""
    return sum(r.reussite for r in resultats) / len(resultats) if resultats else 0.0


def _nombres(resultats, cle):
    return [getattr(r, cle) for r in resultats if getattr(r, cle) != '']


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
    distances = _nombres(resultats, 'distance_min_pietons_m')
    if distances:
        lignes.append(f'Distance minimale aux piétons : {min(distances):.2f} m')
    bords = _nombres(resultats, 'distance_min_bord_m')
    if bords:
        lignes.append(f'Distance minimale bord à bord : {min(bords):.2f} m '
                      f'(moyenne des minima par trajet : {sum(bords) / len(bords):.2f} m)')
        lignes.append(f'Contacts : {sum(r.contacts for r in resultats)} (causés par le robot : '
                      f'{sum(r.contacts_robot for r in resultats)}, par le piéton : '
                      f'{sum(r.contacts_pieton for r in resultats)}, sans cause : '
                      f'{sum(r.contacts_aucun for r in resultats)})')
        arret = sum(r.temps_arret_pres_s for r in resultats)
        lignes.append(f'Temps arrêté près d\'un piéton : {arret:.0f} s')
    attentes = sum(r.attentes_passage for r in resultats)
    if attentes:
        duree = sum(r.duree_attente_passage_s for r in resultats)
        lignes.append(f'Attentes de passage : {attentes} ({duree:.0f} s)')
    longueurs = [r.longueur_m for r in reussis]
    directes = [r.longueur_directe_m for r in reussis if r.longueur_directe_m != '']
    if longueurs:
        texte = f'Longueur des trajets réussis : moyenne {sum(longueurs) / len(longueurs):.1f} m'
        if directes:
            texte += f' (itinéraire direct : {sum(directes) / len(directes):.1f} m)'
        lignes.append(texte)
    rates = [r for r in resultats if not r.reussite]
    for r in rates:
        lignes.append(f'  raté : trajet {r.numero} {r.depart} → {r.arrivee} ({r.etat_final}'
                      + (f', à {r.erreur_m} m' if r.erreur_m != '' else '') + ')')
    return '\n'.join(lignes)


def verifier_mesures(resultats, mesures):
    """Seuils d'une scène (champ mesures) : [(nom, réussi, texte en français)]."""
    verifs = []
    if not mesures:
        return verifs
    if 'reussite_min' in mesures:
        taux = taux_reussite(resultats)
        minimum = mesures['reussite_min']
        verifs.append(('reussite_min', taux >= minimum - 1e-9,
                       f'réussite {100 * taux:.0f} % (au moins {100 * minimum:.0f} %)'))
    if 'distance_bord_min_m' in mesures:
        bords = _nombres(resultats, 'distance_min_bord_m')
        mini = min(bords) if bords else None
        seuil = mesures['distance_bord_min_m']
        vue = 'inconnue' if mini is None else f'{mini:.2f} m'
        verifs.append(('distance_bord_min_m', mini is not None and mini >= seuil,
                       f'distance bord à bord minimale {vue} (au moins {seuil:.2f} m)'))
    if 'contacts_robot_max' in mesures:
        n = sum(r.contacts_robot for r in resultats)
        seuil = mesures['contacts_robot_max']
        verifs.append(('contacts_robot_max', n <= seuil,
                       f'{n} contact(s) causé(s) par le robot (au plus {seuil})'))
    if 'detours_max' in mesures:
        n = max((r.detours for r in resultats), default=0)
        verifs.append(('detours_max', n <= mesures['detours_max'],
                       f'au plus {n} détour(s) par trajet (au plus {mesures["detours_max"]})'))
    if 'duree_max_s' in mesures:
        n = max((r.duree_s for r in resultats), default=0.0)
        seuil = mesures['duree_max_s']
        verifs.append(('duree_max_s', n <= seuil,
                       f'trajet le plus long : {n:.0f} s (au plus {seuil:.0f} s)'))
    if 'longueur_max_m' in mesures:
        n = max((r.longueur_m for r in resultats), default=0.0)
        seuil = mesures['longueur_max_m']
        verifs.append(('longueur_max_m', n <= seuil,
                       f'trajet le plus long : {n:.1f} m parcourus (au plus {seuil:.0f} m)'))
    return verifs


# ---------------------------------------------------------------- client ROS 2


class ClientRos:
    """
    Client ROS 2 du banc.

    Parle au guide par ses sujets ROS 2 ; position du robot par TF map → base_link ; vérité
    terrain du robot (Odometry) et piétons (/pietons/etat) pour les mesures.
    """

    def __init__(self, simu, sujet_verite=None):
        import rclpy
        from nav_msgs.msg import Odometry
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.parameter import Parameter
        from rclpy.qos import qos_profile_sensor_data
        from std_msgs.msg import Empty, String
        import tf2_ros

        self.rclpy = rclpy
        # En simulation avec une vérité terrain, le temps simulé est celui de ses horodatages :
        # s'abonner à /clock (1000 messages par seconde) coûtait la moitié d'un cœur au banc
        self.horloge_verite = bool(simu and sujet_verite)
        sim = simu and not self.horloge_verite
        self.noeud = rclpy.create_node(
            'banc', parameter_overrides=[Parameter('use_sim_time', Parameter.Type.BOOL, sim)])
        self.String, self.Empty = String, Empty
        self.pub_aller = self.noeud.create_publisher(String, '/guide/aller', 10)
        self.pub_stop = self.noeud.create_publisher(Empty, '/guide/stop', 10)
        self.pub_reinit = self.noeud.create_publisher(Empty, '/pietons/reinitialiser', 10)
        self.noeud.create_subscription(String, '/guide/etat', self._sur_etat, 10)
        self.noeud.create_subscription(String, '/pietons/etat', self._sur_pietons, 10)
        if sujet_verite:
            self.noeud.create_subscription(Odometry, sujet_verite, self._sur_verite,
                                           qos_profile_sensor_data)
        self.tampon_tf = tf2_ros.Buffer()
        self.ecoute_tf = tf2_ros.TransformListener(self.tampon_tf, self.noeud)
        self.executeur = SingleThreadedExecutor()
        self.executeur.add_node(self.noeud)
        self._etat = None
        self._verite = None
        self._t_verite = None          # (horodatage, heure murale de réception)
        self._pietons = None           # (temps simulé de réception, message)
        self.debut_mur = time.monotonic()
        self.debut_sim = None

    def _sur_etat(self, msg):
        try:
            self._etat = json.loads(msg.data)
        except ValueError:
            pass

    def _sur_verite(self, msg):
        from atelier.lieu.conversions import quaternion_vers_cap
        p, v = msg.pose.pose, msg.twist.twist
        self._t_verite = (msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9, time.monotonic())
        cap = quaternion_vers_cap(p.orientation)
        c, s = math.cos(cap), math.sin(cap)
        self._verite = (p.position.x, p.position.y, c * v.linear.x - s * v.linear.y,
                        s * v.linear.x + c * v.linear.y)

    def _sur_pietons(self, msg):
        try:
            self._pietons = (self.temps(), json.loads(msg.data))
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
        if self.position() is None:
            return 'position du robot inconnue (TF)'
        while self.horloge_verite and self._t_verite is None and time.monotonic() < fin:
            self.attendre(0.5)
        if self.horloge_verite and self._t_verite is None:
            return 'pas de vérité terrain du robot (--verite)'
        return None

    def attendre_pietons(self, delai_s):
        """Attend /pietons/etat et l'écoute de /pietons/reinitialiser (nœud pietons)."""
        fin = time.monotonic() + delai_s
        while time.monotonic() < fin:
            if self._pietons is not None and self.pub_reinit.get_subscription_count() > 0:
                return True
            self.attendre(0.2)
        return False

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

    def verite(self):
        return self._verite

    def pietons_mesures(self):
        """
        Piétons de /pietons/etat s'il est frais (sinon None).

        Leurs positions sont prolongées par leur vitesse jusqu'à maintenant (0,3 s au plus).
        """
        if self._pietons is None:
            return None
        recu, message = self._pietons
        maintenant = self.temps()
        if maintenant - recu > PIETONS_FRAIS_S:
            return None
        dt = min(max(0.0, maintenant - recu), EXTRAPOLATION_MAX_S)
        try:
            return [(p['id'], p['x'] + p['vx'] * dt, p['y'] + p['vy'] * dt, p['vx'], p['vy'],
                     p['rayon_m']) for p in message.get('pietons', [])]
        except (KeyError, TypeError):
            return None

    def reinitialiser_pietons(self):
        self.pub_reinit.publish(self.Empty())

    def temps(self):
        if self.horloge_verite:
            # horodatage de la dernière vérité ; si elle se tait (simulation arrêtée), le temps
            # continue en heure murale (les délais des trajets restent bornés)
            if self._t_verite is None:
                t = 0.0
            else:
                stamp, recu = self._t_verite
                attente = time.monotonic() - recu
                t = stamp + (attente if attente > 1.0 else 0.0)
        else:
            t = self.noeud.get_clock().now().nanoseconds * 1e-9
        if self.debut_sim is None and t > 0:
            self.debut_sim, self.debut_mur = t, time.monotonic()
        return t

    def facteur_temps_reel(self):
        """Temps simulé / temps réel écoulés depuis la première horloge (None si inconnu)."""
        if self.debut_sim is None:
            return None
        mur = time.monotonic() - self.debut_mur
        return (self.temps() - self.debut_sim) / mur if mur > 1.0 else None

    def fermer(self):
        self.executeur.shutdown()
        self.noeud.destroy_node()


def placer_robot_gazebo(monde_gz, x, y, theta, nom=NOM_ROBOT_GAZEBO):
    """
    Repose le robot proxy dans Gazebo.

    Service set_pose du monde, par « ign service ». Renvoie None, ou le problème en français.
    """
    req = (f'name: "{nom}", position: {{x: {x:.4f}, y: {y:.4f}, z: 0.01}}, '
           f'orientation: {{z: {math.sin(theta / 2):.6f}, w: {math.cos(theta / 2):.6f}}}')
    try:
        sortie = subprocess.run(['ign', 'service', '-s', f'/world/{monde_gz}/set_pose',
                                 '--reqtype', 'ignition.msgs.Pose', '--reptype',
                                 'ignition.msgs.Boolean', '--timeout', '3000', '--req', req],
                                capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as erreur:
        return f'ign service impossible : {erreur}'
    if 'data: true' not in sortie.stdout:
        texte = (sortie.stdout + sortie.stderr).strip()[:200]
        return f'Gazebo n\'a pas reposé le robot : {texte}'
    return None


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


class Preparation:
    """
    Préparation de chaque essai d'une scène.

    Robot reposé au départ (Gazebo), piétons remis au début de la scène.
    """

    def __init__(self, client, poses, monde_gz, avec_pietons, journal=_afficher,
                 duree_blocage=None):
        from g1_nav.routeur import DUREE_BLOCAGE_S
        self.client = client
        self.poses = poses
        self.monde_gz = monde_gz
        self.avec_pietons = avec_pietons
        self.journal = journal
        self.duree_blocage = DUREE_BLOCAGE_S if duree_blocage is None else duree_blocage
        self.dernier_detour = None

    def __call__(self, numero, depart, arrivee):
        # Un détour a bloqué un couloir (routeur du guide, DUREE_BLOCAGE_S) : chaque essai doit
        # partir du même graphe, on attend la fin du blocage
        if self.dernier_detour is not None:
            reste = self.dernier_detour + self.duree_blocage + 1.0 - time.monotonic()
            if reste > 0:
                self.journal(f'trajet {numero} : attente de {reste:.0f} s, la fin du blocage du '
                             'couloir de l\'essai précédent')
                self.client.attendre(reste)
            self.dernier_detour = None
        pose = self.poses.get(depart)
        position = self.client.position()
        if pose is not None and (position is None or math.dist(position[:2], pose[:2]) > 0.3
                                 or abs(math.remainder(position[2] - pose[2], 2 * math.pi)) > 0.3):
            probleme = placer_robot_gazebo(self.monde_gz, *pose)
            if probleme:
                self.journal(f'trajet {numero} : {probleme}')
            fin = time.monotonic() + 5.0
            while time.monotonic() < fin:
                self.client.attendre(0.2)
                position = self.client.position()
                if position is not None and math.dist(position[:2], pose[:2]) < 0.2:
                    break
        if self.avec_pietons:
            self.client.reinitialiser_pietons()
        self.client.attendre(1.5)        # odométrie, TF et cartes de coûts au nouvel endroit


def main(argv=None):
    import atelier
    from atelier.lieu import ErreurLieu, charger_monde, charger_salles, chemin_monde
    from g1_nav.commande import Analyseur
    from g1_nav.routeur import Routeur

    p = Analyseur(
        prog='g1-banc', description='Banc de test du guide : N trajets entre salles tirées au '
                                    'sort, ou les trajets d\'une scène de passants, résultats '
                                    'en CSV.')
    p.add_argument('--lieu', default=None,
                   help='dossier du lieu, ou id seul (ex. demo) ; avec --scene : le lieu de '
                        'référence copié (défaut : celui de la scène)')
    p.add_argument('--etage', default=None,
                   help='id de l\'étage (ex. rdc ; avec --scene : celui de la scène)')
    p.add_argument('--trajets', type=int, default=20, help='nombre de trajets (défaut 20)')
    p.add_argument('--graine', type=int, default=None, help='graine du tirage, pour le refaire')
    p.add_argument('--delai', type=float, default=180.0,
                   help='durée maximale d\'un trajet, en secondes (défaut 180)')
    p.add_argument('--csv', default=None, help='fichier CSV (défaut : ~/robot-g1/journaux/)')
    p.add_argument('--simu', action='store_true', help='temps simulé (Gazebo)')
    p.add_argument('--lancer', action='store_true',
                   help='lance aussi la simulation sans fenêtre et la navigation, puis les '
                        'arrête')
    p.add_argument('--moteur', default='nav2', choices=['nav2', 'unitree'],
                   help='moteur du guide (défaut nav2)')
    p.add_argument('--seuil', type=float, default=0.0,
                   help='réussite minimale en %% ; en dessous, code de sortie 1')
    p.add_argument('--scene', default=None,
                   help='scène de passants (id de atelier/monde/scenes, ou fichier '
                        '.scene.yaml) : copie du lieu, simulation lancée, trajets et seuils')
    p.add_argument('--reaction', default=None, choices=['aucune', 'arret', 'ecart'],
                   help='avec --scene : réaction de tous les piétons de la scène (défaut : '
                        'la leur)')
    p.add_argument('--pietons', default='corps', choices=['corps', 'acteurs'],
                   help='avec --lancer : piétons crédibles (corps, défaut) ou <actor> de la '
                        'vague 1')
    p.add_argument('--travail', default=None,
                   help='dossier de la copie du lieu (--scene) et des journaux de --lancer '
                        '(défaut : ~/robot-g1/journaux)')
    p.add_argument('--verite', default=None,
                   help='sujet nav_msgs/Odometry de la vérité terrain du robot (défaut : '
                        '/odom en simulation, rien sinon ; répétition : /g1_jumeau/odom)')
    args = p.parse_args(argv)

    horodatage = datetime.datetime.now().strftime('%Y-%m-%d_%Hh%M%S')
    journaux = (Path(args.travail).expanduser().resolve() if args.travail
                else atelier.dossier_journaux())
    journaux.mkdir(parents=True, exist_ok=True)
    scene, mesures, nom_scene = None, {}, ''
    if args.scene:
        from atelier.monde.scene import charger_scene, copier_pour_scene, trajets_de_scene
        try:
            scene = charger_scene(args.scene)
            nom_scene = scene['id']
            travail = journaux / f'banc_{nom_scene}_{horodatage}'
            travail.mkdir(parents=True, exist_ok=True)
            reference = atelier.chemin_lieu(args.lieu) if args.lieu else None
            nom_copie = Path(reference).name if reference else scene['lieu']
            dossier = copier_pour_scene(scene, travail / nom_copie, reaction=args.reaction,
                                        reference=reference)
        except ErreurLieu as erreur:
            print(f'g1-banc : {erreur}', file=sys.stderr)
            return 1
        args.etage = scene['etage']
        args.lancer = True
        mesures = dict(scene.get('mesures') or {})
        if 'duree_max_s' in mesures:
            args.delai = max(args.delai, 1.2 * mesures['duree_max_s'])
        print(f'Scène « {nom_scene} » : {scene["nom"]}'
              + (f' (réaction de tous les piétons : {args.reaction})' if args.reaction else ''))
        print(f'Copie du lieu : {dossier}')
    else:
        if not args.lieu or not args.etage:
            p.error('il manque --lieu et --etage (ou --scene)')
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
    chemin_csv = Path(args.csv) if args.csv else \
        journaux / f'banc_{nom_scene or dossier.name}_{args.etage}_{horodatage}.csv'
    try:
        routeur = Routeur.depuis_lieu(dossier, args.etage)
    except Exception:  # noqa: BLE001 : sans graphe, pas de longueur directe
        routeur = None

    processus = []
    if args.lancer:
        args.simu = True
        print(f'Lancement de la simulation et de la navigation (journaux dans {journaux})')
        processus.append(lancer(
            ['ros2', 'launch', 'g1_sim', 'simulation.launch.py', f'lieu:={dossier}',
             f'etage:={args.etage}', 'sans_fenetre:=true', f'pietons:={args.pietons}'],
            journaux / f'banc_{horodatage}_simulation.log'))
        time.sleep(5.0)
        processus.append(lancer(
            ['ros2', 'launch', 'g1_nav', 'navigation.launch.py', f'lieu:={dossier}',
             f'etage:={args.etage}', 'simu:=true', f'moteur:={args.moteur}'],
            journaux / f'banc_{horodatage}_navigation.log'))

    import rclpy
    rclpy.init()
    client = ClientRos(args.simu, args.verite or ('/odom' if args.simu else None))
    try:
        probleme = client.attendre_guide(120.0 if args.lancer else 20.0, args.moteur == 'nav2')
        if probleme:
            print(f'g1-banc : {probleme}. Lancez d\'abord : g1-guide navigation '
                  f'--lieu {args.lieu} --etage {args.etage}' + (' --simu' if args.simu else ''),
                  file=sys.stderr)
            return 1
        avec_corps = any(reglages_pieton(x)['corps'] for x in pietons) and args.pietons == 'corps'
        if avec_corps and not client.attendre_pietons(30.0):
            print('g1-banc : /pietons/etat n\'arrive pas (nœud pietons de g1_sim) : positions '
                  'des piétons calculées depuis le monde', file=sys.stderr)
        depart = salle_proche(poses, client.position())
        if scene is not None:
            trajets = trajets_de_scene(scene, sorted(poses))
            preparer = Preparation(client, poses, args.etage, avec_corps)
        else:
            trajets = tirer_trajets(sorted(poses), args.trajets, depart, args.graine)
            preparer = None
        print(f'{len(trajets)} trajets, départ de « {trajets[0][0] if scene else depart} »'
              + (f', {len(pietons)} piéton(s)' if pietons else ''), flush=True)
        resultats = executer(client, trajets, poses, pietons, position_pieton, args.delai,
                             scene=nom_scene, preparer=preparer, routeur=routeur)
        ecrire_csv(chemin_csv, resultats)
        print()
        print(resume(resultats))
        rtf = client.facteur_temps_reel()
        if rtf is not None:
            print(f'Facteur temps réel de la simulation : {rtf:.2f}')
        verifs = verifier_mesures(resultats, mesures)
        for _, ok, texte in verifs:
            print(f'  seuil de la scène : {texte} : {"oui" if ok else "NON"}')
        print(f'CSV : {chemin_csv}')
        ok = 100 * taux_reussite(resultats) >= args.seuil and all(v[1] for v in verifs)
        return 0 if ok else 1
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
