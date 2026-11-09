#!/usr/bin/env python3
"""Outils des critères 41 (démo complète en simulation) et 42 (sécurité de la démo), section 13.9 du plan : agent
Borne et orchestrateur.

  outils_demo_e2e.py preparer --lieu ID [--sortie borne]
      sur la COPIE du demo : demo.yaml (sortie de la voix), les personnalités d'exemple (la salutation) ;
  outils_demo_e2e.py critere-41 --api URL --lieu ID
      simulation (scène accompagnement, faux visiteur lancé par le script), POST /api/demo/lancer : attente en moins
      de 30 s ; trois visiteurs de suite (b204, cdi, amphi) : visiteur vu au LiDAR (sinon un appui sur la borne) →
      salutation de la personnalité sur /robot/dire → POST /api/borne/choisir → accompagnement (/guide/aller avec
      accompagner et source accueil) → arrivée à moins de 0,3 m (vérité /odom) → retour → attente au principal
      (0,3 m) ; la borne suit (GET /api/borne/etat) ; statistiques : 3 visiteurs, 3 visites réussies ; messages
      conformes ; moins de 15 min ; POST /api/demo/arreter : plus de nœud accueil ni voix ;
  outils_demo_e2e.py critere-42 --api URL --lieu ID
      répétition (pont et faux G1), repérage, démo ; une visite à chaque cas : ARRÊT en route (pause, raison arret,
      en moins de 2 s ; « Débloquer » : aucun mouvement pendant 15 s, toujours en pause ; un choix à la borne refusé,
      la borne dit pause ; « Reprendre » loin de l'accueil refusé, « Ramener à l'accueil » : le robot revient, puis
      attente) ; « Bloquer » (verrou) ; faux G1 assis puis remis en marche (pas_en_marche) ; pont tué (pont_absent, en
      moins de 6 s, relancé) ; pilotage qui prend la main (pilotage) : chaque fois pause, 15 s sans mouvement après
      la levée (vérité /g1_jumeau/odom à moins de 5 cm, aucun 7105 non nul), puis « Ramener » ; jamais de /guide/aller
      de la source accueil pendant une pause (sauf « Ramener », la demande explicite) ; jamais d'erreur 500.
Code de sortie : 0 réussi, 1 échoué (le message dit pourquoi), 77 en attente (une pièce manque).
"""
import argparse
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

ICI = Path(__file__).resolve().parent
RACINE = ICI.parent
sys.path.insert(0, str(ICI))
sys.path.insert(0, str(RACINE))

EN_ATTENTE = 77
PREFIXE = 'demo'
TOLERANCE_M = 0.3
IMMOBILE_M = 0.05
SANS_REPRISE_S = 15.0
SALLES_41 = ('b204', 'cdi', 'amphi')
CODES_HTTP = []


class Echec(Exception):
    pass


class EnAttente(Exception):
    pass


def dire(texte):
    print(f'[{PREFIXE}] {texte}', flush=True)


def ok(texte):
    print(f'[{PREFIXE}] ok : {texte}', flush=True)


def verifier(condition, message):
    if not condition:
        raise Echec(message)


def appel(api, methode, chemin, corps=None, delai=60):
    donnees = None if corps is None else json.dumps(corps).encode()
    r = urllib.request.Request(api + chemin, data=donnees, method=methode, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(r, timeout=delai) as reponse:
            code, texte = reponse.status, reponse.read()
    except urllib.error.HTTPError as e:
        code, texte = e.code, e.read()
    CODES_HTTP.append((methode, chemin, code))
    try:
        return code, json.loads(texte or b'null')
    except ValueError:
        return code, {'detail': texte.decode('utf-8', 'replace')}


def lieu_et_salles(lieu):
    from atelier import chemin_lieu
    from atelier.lieu import charger_salles
    from atelier.lieu.principal import point_principal
    dossier = chemin_lieu(lieu)
    return dossier, {s.id: s for s in charger_salles(dossier)}, point_principal(dossier)


def preparer(args):
    from atelier import chemin_lieu
    from atelier.lieu import accueil as A
    from atelier.lieu import equipe as E
    dossier = chemin_lieu(args.lieu)
    verifier(dossier.resolve() != (RACINE / 'lieux' / 'demo').resolve(), 'jamais dans lieux/demo : une copie')
    A.enregistrer_demo(dossier, {'version': 1, 'voix': {'sortie': args.sortie}, 'borne': {'code_operateur': '4826'}})
    E.enregistrer_equipe(dossier, 'personnalites', E.exemple_equipe('personnalites'))
    dire(f'copie préparée : demo.yaml (voix {args.sortie}), personnalités d\'exemple')
    return 0


# ---------------------------------------------------------------- observateur ROS 2

class Observateur:
    """La démo, le guide, la voix et la vérité terrain ; vérifie chaque message de la démo par son schéma."""

    SCHEMAS = {'/accueil/etat': 'etat_demo', '/accueil/evenement': 'evenement_demo', '/robot/dire': 'robot_dire'}

    def __init__(self, verite):
        import rclpy
        from nav_msgs.msg import Odometry
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy, qos_profile_sensor_data
        from std_msgs.msg import Int32, String
        from atelier.lieu import valider_message
        self.rclpy, self.String, self.Int32, self.valider = rclpy, String, Int32, valider_message
        self.contexte = rclpy.Context()
        rclpy.init(context=self.contexte)
        self.noeud = rclpy.create_node('e2e_demo_observateur', context=self.contexte)
        self.verrou = threading.Lock()
        self.recus = []
        self.verites = []
        self.requetes = []           # (instant, api_id, parametre) de /api/sport/request
        self.non_conformes = []
        self.aller_en_pause = []
        n = self.noeud
        fiable = QoSProfile(depth=50, reliability=ReliabilityPolicy.RELIABLE)
        for sujet in ('/accueil/etat', '/accueil/evenement', '/robot/dire', '/guide/aller', '/guide/etat',
                      '/guide/evenement', '/pont/etat', '/voix/etat', '/personnes/lidar'):
            n.create_subscription(String, sujet, self._recepteur(sujet), fiable)
        n.create_subscription(Odometry, verite, self._verite, qos_profile_sensor_data)
        try:
            from unitree_api.msg import Request
            n.create_subscription(Request, '/api/sport/request', self._requete, fiable)
        except ImportError:
            pass
        verrou = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                            durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.pub_maitre = n.create_publisher(String, '/mouvement/maitre', verrou)
        self.pub_mode = n.create_publisher(Int32, '/g1_jumeau/mode', QoSProfile(depth=10,
                                                                               reliability=ReliabilityPolicy.RELIABLE))
        self.pub_visiteur = n.create_publisher(String, '/faux_visiteur/mode', 10)
        self.executeur = SingleThreadedExecutor(context=self.contexte)
        self.executeur.add_node(n)
        self._fin = threading.Event()
        self._fil = threading.Thread(target=self._tourner, daemon=True)
        self._fil.start()

    def _tourner(self):
        while not self._fin.is_set() and self.contexte.ok():
            self.executeur.spin_once(timeout_sec=0.05)

    def _recepteur(self, sujet):
        def recevoir(m):
            try:
                d = json.loads(m.data)
            except ValueError:
                d = {'brut': m.data}
            schema = self.SCHEMAS.get(sujet)
            if schema and self.valider(schema, d):
                self.non_conformes.append((sujet, self.valider(schema, d)[:2]))
            t = time.monotonic()
            with self.verrou:
                if sujet == '/guide/aller' and d.get('source') == 'accueil':
                    etat = self._dernier_locked('/accueil/etat')
                    explicite = d.get('cible') == 'principal' and str(d.get('id', '')).startswith('ramener-')
                    if etat and etat.get('etat') == 'pause' and not explicite:
                        self.aller_en_pause.append(d)
                self.recus.append((t, sujet, d))
        return recevoir

    def _verite(self, m):
        p = m.pose.pose.position
        with self.verrou:
            self.verites.append((time.monotonic(), p.x, p.y))
            del self.verites[:-30000]

    def _requete(self, m):
        try:
            parametre = json.loads(m.parameter) if m.parameter else {}
        except ValueError:
            parametre = {}
        with self.verrou:
            self.requetes.append((time.monotonic(), m.header.identity.api_id, parametre))
            del self.requetes[:-20000]

    def _dernier_locked(self, sujet):
        for t, s, d in reversed(self.recus):
            if s == sujet:
                return d
        return None

    def dernier(self, sujet):
        with self.verrou:
            return self._dernier_locked(sujet)

    def messages(self, sujet, depuis=0.0):
        with self.verrou:
            return [(t, d) for t, s, d in self.recus if s == sujet and t >= depuis]

    def demo(self):
        return self.dernier('/accueil/etat') or {}

    def evenements(self, code, depuis=0.0):
        return [d for _, d in self.messages('/accueil/evenement', depuis) if d.get('code') == code]

    def pose(self):
        with self.verrou:
            return self.verites[-1][1:] if self.verites else None

    def deplacement(self, t0, t1=math.inf):
        with self.verrou:
            v = [x for x in self.verites if t0 <= x[0] <= t1]
        if not v:
            return 0.0
        return max(math.hypot(x[1] - v[0][1], x[2] - v[0][2]) for x in v)

    def vitesse(self, duree=0.5):
        t = time.monotonic()
        with self.verrou:
            v = [x for x in self.verites if x[0] >= t - duree]
        if len(v) < 2 or v[-1][0] - v[0][0] < 0.2:
            return 0.0
        return math.hypot(v[-1][1] - v[0][1], v[-1][2] - v[0][2]) / (v[-1][0] - v[0][0])

    def ordres_non_nuls(self, t0):
        with self.verrou:
            return [p for t, a, p in self.requetes if t >= t0 and a == 7105
                    and any(abs(x) > 1e-6 for x in (p.get('velocity') or [0, 0, 0]))]

    def attendre(self, condition, delai, message, pas=0.1):
        fin = time.monotonic() + delai
        while time.monotonic() < fin:
            v = condition()
            if v:
                return v
            time.sleep(pas)
        d = self.demo()
        raise Echec(f'{message} (démo : {d.get("etat")}, {d.get("message")} ; guide : '
                    f'{(self.dernier("/guide/etat") or {}).get("etat")})')

    def attendre_demo(self, etats, delai, message=None):
        etats = (etats,) if isinstance(etats, str) else tuple(etats)
        return self.attendre(lambda: self.demo() if self.demo().get('etat') in etats else None, delai,
                             message or f'la démo ne passe pas à {"/".join(etats)}')

    def maitre(self, maitre):
        from datetime import datetime
        m = {'version': 1, 'maitre': maitre, 'par': 'e2e', 'message': 'essai',
             'depuis': datetime.now().astimezone().isoformat(timespec='seconds')}
        self.pub_maitre.publish(self.String(data=json.dumps(m)))

    def mode_g1(self, fsm):
        for _ in range(3):
            self.pub_mode.publish(self.Int32(data=int(fsm)))
            time.sleep(0.05)

    def visiteur(self, mode):
        self.pub_visiteur.publish(self.String(data=mode))

    def nav2_actif(self):
        from lifecycle_msgs.srv import GetState
        if not hasattr(self, '_client_nav2'):
            self._client_nav2 = self.noeud.create_client(GetState, '/bt_navigator/get_state')
        if not self._client_nav2.wait_for_service(timeout_sec=0.5):
            return False
        futur = self._client_nav2.call_async(GetState.Request())
        fin = time.monotonic() + 3.0
        while not futur.done() and time.monotonic() < fin:
            time.sleep(0.05)
        return bool(futur.done() and futur.result() and futur.result().current_state.label == 'active')

    def fermer(self):
        self._fin.set()
        self._fil.join(timeout=2.0)
        self.executeur.shutdown()
        self.noeud.destroy_node()
        self.rclpy.try_shutdown(context=self.contexte)


def processus_de_la_demo():
    """Nœuds accueil et voix encore vivants, lancés avec nos lieux."""
    from critere_20_outils import processus
    return processus('lib/g1_accueil/accueil') + processus('atelier.voix')


def lancer_demo(api, obs, lieu):
    t = time.monotonic()
    code, r = appel(api, 'POST', '/api/demo/lancer', {'lieu': lieu, 'etage': 'rdc'})
    verifier(code == 200, f'POST /api/demo/lancer : {code} {r}')
    for a in r.get('avertissements') or []:
        dire(f'avertissement : {a}')
    obs.attendre_demo('attente', 30, 'la démo n\'est pas en attente 30 s après « Lancer la démo »')
    ok(f'démo lancée, en attente {time.monotonic() - t:.1f} s après (voix : sortie {r.get("sortie_voix")})')


def arreter_demo(api, obs):
    t = time.monotonic()
    code, r = appel(api, 'POST', '/api/demo/arreter', {})
    verifier(code == 200 and r.get('lancee') is False, f'POST /api/demo/arreter : {code} {r}')
    time.sleep(2.0)
    restes = processus_de_la_demo()
    verifier(not restes, f'après « Arrêter la démo », des nœuds restent : {restes}')
    arretee = obs.evenements('arretee', t)
    ok(f'« Arrêter la démo » : plus de nœud accueil ni voix (événement arretee : {bool(arretee)})')


def borne(api):
    code, e = appel(api, 'GET', '/api/borne/etat')
    verifier(code == 200, f'GET /api/borne/etat : {code}')
    return e


# ---------------------------------------------------------------- critère 41 : trois visiteurs de suite

def un_visiteur(api, obs, numero, salle, salles, principal, salutation):
    t0 = time.monotonic()
    # le visiteur, vu au LiDAR (devant le robot, à 1,5 m au plus) ; sinon il touche la borne
    vu = obs.attendre(lambda: obs.evenements('salutation', t0), 20, 'pas de salutation') \
        if _attendre_sans_echec(lambda: obs.evenements('visiteur', t0), 14) else None
    comment = 'vu au LiDAR'
    if not vu:
        personnes = (obs.dernier('/personnes/lidar') or {}).get('personnes') or []
        dire(f'visiteur {numero} : personne devant le robot à 1,5 m au plus (LiDAR : '
             + ', '.join(f'n° {q.get("id")} à {q.get("distance_m", 0):.1f} m, {math.degrees(q.get("angle_rad", 0)):.0f}°'
                         for q in personnes) + ') : il touche la borne')
        code, r = appel(api, 'POST', '/api/borne/appui', {})
        verifier(code == 200 and r.get('accepte'), f'POST /api/borne/appui : {code} {r}')
        obs.attendre(lambda: obs.evenements('salutation', t0), 5, 'pas de salutation après l\'appui')
        comment = 'appui sur la borne'
    dits = [d for _, d in obs.messages('/robot/dire', t0) if d.get('source') == 'accueil']
    verifier(any(d['texte'] == salutation for d in dits), f'visiteur {numero} : salutation absente de /robot/dire ({dits})')
    obs.attendre_demo(('choix', 'salutation'), 5)
    t1 = time.monotonic()
    code, r = appel(api, 'POST', '/api/borne/choisir', {'salle': salle})
    verifier(code == 200 and r.get('accepte'), f'POST /api/borne/choisir {salle} : {code} {r}')
    aller = obs.attendre(lambda: obs.messages('/guide/aller', t1), 5, 'pas de /guide/aller')[0][1]
    verifier(aller.get('cible') == salle and aller.get('accompagner') is True and aller.get('source') == 'accueil',
             f'/guide/aller {aller}')
    obs.attendre_demo('accompagnement', 30)
    ecran = borne(api)['ecran']
    verifier(ecran == 'suivez_moi', f'la borne montre {ecran} pendant l\'accompagnement')
    obs.attendre_demo('arrivee', 240, f'visiteur {numero} : pas d\'arrivée à {salle}')
    t_arrivee = time.monotonic()
    time.sleep(1.0)
    s = salles[salle].pose
    d = math.hypot(obs.pose()[0] - s.x, obs.pose()[1] - s.y)
    verifier(d < TOLERANCE_M, f'visiteur {numero} : arrivé à {d:.2f} m de {salle} (0,3 m au plus)')
    verifier(borne(api)['ecran'] == 'arrivee', 'la borne ne montre pas l\'arrivée')
    obs.attendre_demo('retour', 60, f'visiteur {numero} : pas de retour')
    verifier(borne(api)['ecran'] == 'retour', 'la borne ne montre pas le retour')
    obs.attendre_demo('attente', 240, f'visiteur {numero} : pas de retour en attente')
    time.sleep(1.0)
    p = principal.pose
    dp = math.hypot(obs.pose()[0] - p.x, obs.pose()[1] - p.y)
    verifier(dp < TOLERANCE_M, f'visiteur {numero} : de retour à {dp:.2f} m du principal (0,3 m au plus)')
    verifier(borne(api)['ecran'] == 'salles', 'la borne ne montre pas les salles au retour')
    ok(f'visiteur {numero} ({comment}) : salutation « {salutation[:40]}… », {salle} (accompagné), arrivé à {d:.2f} m '
       f'en {t_arrivee - t1:.0f} s, retour au principal à {dp:.2f} m ({time.monotonic() - t0:.0f} s en tout)')
    return comment


def _attendre_sans_echec(condition, delai):
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        if condition():
            return True
        time.sleep(0.1)
    return False


def critere_41(args):
    from atelier.lieu import equipe as E
    debut = time.monotonic()
    dossier, salles, principal = lieu_et_salles(args.lieu)
    salutation = E.personnalite_active(E.charger_equipe(dossier, 'personnalites'))['salutation']
    obs = Observateur('/odom')
    try:
        code, r = appel(args.api, 'POST', '/api/simulation/demarrer', {'lieu': args.lieu, 'etage': 'rdc'})
        verifier(code == 200, f'POST /api/simulation/demarrer : {code} {r}')
        obs.attendre(lambda: obs.pose() is not None and obs.dernier('/guide/etat'), 120, 'ni /odom ni /guide/etat')
        obs.attendre(obs.nav2_actif, 180, 'Nav2 n\'est pas actif', pas=0.5)
        ok(f'simulation lancée, Nav2 actif ({time.monotonic() - debut:.0f} s)')
        obs.visiteur('suivre')
        lancer_demo(args.api, obs, args.lieu)
        comments = [un_visiteur(args.api, obs, i + 1, s, salles, principal, salutation) for i, s in enumerate(SALLES_41)]
        stats = obs.demo()['statistiques']
        verifier(stats['visiteurs'] == 3 and stats['visites_reussies'] == 3,
                 f'statistiques : {stats} (3 visiteurs et 3 visites réussies attendus)')
        ok(f'statistiques : {stats["visiteurs"]} visiteurs, {stats["visites_reussies"]} visites réussies, durée moyenne '
           f'{stats.get("duree_moyenne_s")} s ; visiteurs : {", ".join(comments)}')
        verifier(not obs.non_conformes, f'messages non conformes : {obs.non_conformes[:3]}')
        ok(f'{len(obs.messages("/accueil/etat"))} /accueil/etat et {len(obs.messages("/accueil/evenement"))} '
           '/accueil/evenement, tous conformes')
        duree = time.monotonic() - debut
        verifier(duree < 15 * 60, f'{duree / 60:.1f} min (moins de 15 attendues)')
        arreter_demo(args.api, obs)
        cinq_cents = [x for x in CODES_HTTP if x[2] >= 500]
        verifier(not cinq_cents, f'erreurs 500 : {cinq_cents}')
        ok(f'démo complète en {duree / 60:.1f} min, jamais d\'erreur 500')
        appel(args.api, 'POST', '/api/simulation/arreter', {})
        return 0
    finally:
        obs.fermer()


# ---------------------------------------------------------------- critère 42 : la sécurité de la démo

def une_visite_en_route(api, obs, salles, principal):
    """Un visiteur (appui), un choix (la salle la plus loin), le robot qui roule, à 1,5 m au moins de l'accueil
    (plus près, il est encore « à l'accueil » pour la démo : distance_principal_m, 0,5 m)."""
    t0 = time.monotonic()
    obs.attendre_demo('attente', 60)
    code, r = appel(api, 'POST', '/api/borne/appui', {})
    verifier(code == 200, f'POST /api/borne/appui : {code} {r}')
    x, y = obs.pose()
    salle = max(('b204', 'cdi', 'infirmerie', 'amphi'), key=lambda s: math.hypot(salles[s].pose.x - x,
                                                                                    salles[s].pose.y - y))
    code, r = appel(api, 'POST', '/api/borne/choisir', {'salle': salle})
    verifier(code == 200 and r.get('accepte'), f'POST /api/borne/choisir {salle} : {code} {r}')
    p = principal.pose
    obs.attendre(lambda: obs.vitesse() > 0.15 and math.hypot(obs.pose()[0] - p.x, obs.pose()[1] - p.y) > 1.5, 90,
                 f'le robot ne roule pas vers {salle}')
    obs.attendre_demo('accompagnement', 10)
    return salle, t0


def sans_reprise(obs, t_libre, quoi):
    """Après la levée : 15 s sans mouvement (vérité à moins de 5 cm), aucun 7105 non nul, toujours en pause."""
    fin = t_libre + SANS_REPRISE_S
    while time.monotonic() < fin:
        verifier(obs.deplacement(t_libre) < IMMOBILE_M,
                 f'{quoi} : LE ROBOT REPART SEUL ({obs.deplacement(t_libre):.2f} m)')
        verifier(obs.demo().get('etat') == 'pause', f'{quoi} : la démo n\'est plus en pause ({obs.demo().get("etat")})')
        time.sleep(0.2)
    non_nuls = obs.ordres_non_nuls(t_libre)
    verifier(not non_nuls, f'{quoi} : {len(non_nuls)} ordres de marche non nuls après la levée')
    return obs.deplacement(t_libre)


def ramener(api, obs, principal, quoi):
    """« Reprendre » loin de l'accueil refusé, puis « Ramener à l'accueil » : le robot revient, la démo attend."""
    code, r = appel(api, 'POST', '/api/demo/commande', {'action': 'reprendre'})
    verifier(code == 409 and 'Ramenez' in (r or {}).get('detail', ''), f'{quoi} : « Reprendre » loin de l\'accueil : '
                                                                       f'{code} {r}')
    code, r = appel(api, 'POST', '/api/demo/commande', {'action': 'ramener'})
    verifier(code == 200, f'{quoi} : « Ramener à l\'accueil » : {code} {r}')
    obs.attendre_demo('attente', 180, f'{quoi} : le robot n\'est pas revenu à l\'accueil')
    p = principal.pose
    d = math.hypot(obs.pose()[0] - p.x, obs.pose()[1] - p.y)
    verifier(d < 0.5, f'{quoi} : de retour à {d:.2f} m de l\'accueil')
    return d


def attendre_pause(obs, t, raisons, delai, quoi):
    e = obs.attendre(lambda: obs.demo() if obs.demo().get('etat') == 'pause' else None, delai,
                     f'{quoi} : pas de pause en {delai} s')
    duree = time.monotonic() - t
    verifier(e.get('raison') in raisons, f'{quoi} : pause pour « {e.get("raison")} » ({"/".join(raisons)} attendu)')
    return e, duree


def critere_42(args):
    from critere_18_outils import reperer
    from critere_20_outils import Relances, processus
    dossier, salles, principal = lieu_et_salles(args.lieu)
    obs = Observateur('/g1_jumeau/odom')
    relances = Relances(Path(args.journaux))
    try:
        code, r = appel(args.api, 'POST', '/api/simulation/demarrer', {'lieu': args.lieu, 'etage': 'rdc',
                                                                      'mode': 'repetition'})
        verifier(code == 200, f'POST /api/simulation/demarrer (répétition) : {code} {r}')
        obs.attendre(lambda: obs.pose() is not None, 120, 'pas de vérité terrain /g1_jumeau/odom')

        def repere():
            c, e = appel(args.api, 'GET', '/api/robot/etat')
            return c == 200 and e.get('reperage') is not None and not e['reperage'].get('perime')
        obs.attendre(repere, 120, 'le relais du repérage ne répond pas', pas=0.5)
        code, r, _ = reperer(args.api, {'lieu': args.lieu, 'etage': 'rdc'})
        verifier(code == 200 and r.get('repere'), f'POST /api/robot/reperer : {code} {r}')
        obs.attendre(obs.nav2_actif, 180, 'Nav2 n\'est pas actif', pas=0.5)
        ok('répétition lancée, robot repéré, Nav2 actif')
        lancer_demo(args.api, obs, args.lieu)

        # A. ARRÊT en route
        salle, _ = une_visite_en_route(args.api, obs, salles, principal)
        t = time.monotonic()
        code, r = appel(args.api, 'POST', '/api/arret', {'mode': 'repetition'})
        verifier(code == 200 and r.get('verrou'), f'POST /api/arret : {code} {r}')
        e, duree = attendre_pause(obs, t, ('arret', 'verrou'), 2.0, 'ARRÊT en route')
        raison_arret = e['raison']
        time.sleep(2.0)
        t_libre = time.monotonic()
        code, r = appel(args.api, 'POST', '/api/arret/debloquer', {})
        verifier(code == 200, f'POST /api/arret/debloquer : {code} {r}')
        code, r = appel(args.api, 'POST', '/api/borne/choisir', {'salle': 'cdi'})
        verifier(code == 409 and r.get('raison') == 'pause', f'un choix à la borne pendant la pause : {code} {r}')
        verifier(borne(args.api)['ecran'] == 'pause', 'la borne ne dit pas « pause »')
        bouge = sans_reprise(obs, t_libre, 'ARRÊT puis « Débloquer »')
        d = ramener(args.api, obs, principal, 'ARRÊT')
        ok(f'ARRÊT en route vers {salle} : pause (raison {raison_arret}) en {duree:.2f} s ; « Débloquer » : '
           f'{bouge * 100:.1f} cm en 15 s, toujours en pause ; choix refusé, la borne dit « pause » ; « Reprendre » '
           f'refusé loin de l\'accueil ; « Ramener » : revenu à {d:.2f} m, attente')

        # B. « Bloquer » en route
        salle, _ = une_visite_en_route(args.api, obs, salles, principal)
        t = time.monotonic()
        code, r = appel(args.api, 'POST', '/api/robot/arret', {'verrou': True})
        verifier(code == 200, f'« Bloquer » : {code} {r}')
        e, duree = attendre_pause(obs, t, ('verrou', 'arret'), 2.0, '« Bloquer » en route')
        raison_bloquer = e['raison']
        time.sleep(2.0)
        t_libre = time.monotonic()
        code, r = appel(args.api, 'POST', '/api/robot/arret', {'verrou': False})
        verifier(code == 200, f'« Débloquer » : {code} {r}')
        bouge = sans_reprise(obs, t_libre, '« Bloquer » puis « Débloquer »')
        d = ramener(args.api, obs, principal, '« Bloquer »')
        ok(f'« Bloquer » en route vers {salle} : pause (raison {raison_bloquer}) en {duree:.2f} s ; « Débloquer » : '
           f'{bouge * 100:.1f} cm en 15 s ; « Ramener » : {d:.2f} m')

        # C. faux G1 assis en route, puis remis en marche
        salle, _ = une_visite_en_route(args.api, obs, salles, principal)
        t = time.monotonic()
        obs.mode_g1(3)
        e, duree = attendre_pause(obs, t, ('pas_en_marche',), 3.0, 'faux G1 assis en route')
        time.sleep(2.0)
        t_libre = time.monotonic()
        obs.mode_g1(501)
        bouge = sans_reprise(obs, t_libre, 'faux G1 remis en marche')
        d = ramener(args.api, obs, principal, 'faux G1 assis')
        ok(f'faux G1 assis en route vers {salle} : pause (pas_en_marche) en {duree:.2f} s ; remis en marche : '
           f'{bouge * 100:.1f} cm en 15 s ; « Ramener » : {d:.2f} m')

        # D. pont tué en route, puis relancé
        salle, _ = une_visite_en_route(args.api, obs, salles, principal)
        pids = processus('lib/g1_bridge/pont')
        verifier(len(pids) == 1, f'pont introuvable ({pids})')
        t = time.monotonic()
        os.kill(pids[0], signal.SIGKILL)
        e, duree = attendre_pause(obs, t, ('pont_absent',), 6.0, 'pont tué en route')
        prefixe = subprocess.run(['ros2', 'pkg', 'prefix', 'g1_bridge'], capture_output=True, text=True).stdout.strip()
        relances.lancer('pont_g1', ['ros2', 'run', 'g1_bridge', 'pont', '--ros-args', '--params-file',
                                    f'{prefixe}/share/g1_bridge/config/pont.yaml', '-r', '__node:=pont_g1'])
        t_libre = time.monotonic()
        obs.attendre(lambda: (obs.dernier('/pont/etat') or {}).get('etat') == 'pret', 30, 'le pont relancé n\'est pas prêt')
        bouge = sans_reprise(obs, t_libre, 'pont relancé')
        d = ramener(args.api, obs, principal, 'pont tué')
        ok(f'pont tué en route vers {salle} : pause (pont_absent) en {duree:.2f} s ; relancé : {bouge * 100:.1f} cm en '
           f'15 s ; « Ramener » : {d:.2f} m')

        # E. le pilotage prend la main en route
        salle, _ = une_visite_en_route(args.api, obs, salles, principal)
        t = time.monotonic()
        obs.maitre('pilotage')
        e, duree = attendre_pause(obs, t, ('pilotage',), 3.0, 'pilotage en route')
        time.sleep(2.0)
        t_libre = time.monotonic()
        obs.maitre('guide')
        bouge = sans_reprise(obs, t_libre, 'main rendue au guide')
        d = ramener(args.api, obs, principal, 'pilotage')
        ok(f'pilotage en route vers {salle} : pause (pilotage) en {duree:.2f} s ; main rendue : {bouge * 100:.1f} cm '
           f'en 15 s ; « Ramener » : {d:.2f} m')

        verifier(not obs.aller_en_pause, f'/guide/aller de la démo pendant une pause : {obs.aller_en_pause}')
        n_aller = len([1 for _, x in obs.messages('/guide/aller') if x.get('source') == 'accueil'])
        ok(f'{n_aller} /guide/aller de la démo, aucun pendant une pause (hors « Ramener », demande explicite)')
        verifier(not obs.non_conformes, f'messages non conformes : {obs.non_conformes[:3]}')
        arreter_demo(args.api, obs)
        cinq_cents = [x for x in CODES_HTTP if x[2] >= 500]
        verifier(not cinq_cents, f'erreurs 500 : {cinq_cents}')
        ok(f'jamais d\'erreur 500 ; raisons vues : ARRÊT → {raison_arret}, « Bloquer » → {raison_bloquer}')
        appel(args.api, 'POST', '/api/simulation/arreter', {})
        return 0
    finally:
        relances.arreter()
        obs.fermer()


def main(argv=None):
    p = argparse.ArgumentParser(prog='outils_demo_e2e.py', description=__doc__.split('\n')[0])
    sous = p.add_subparsers(dest='commande', required=True)
    s = sous.add_parser('preparer')
    s.add_argument('--lieu', required=True)
    s.add_argument('--sortie', default='borne')
    for nom in ('critere-41', 'critere-42'):
        s = sous.add_parser(nom)
        s.add_argument('--api', required=True)
        s.add_argument('--lieu', required=True)
        s.add_argument('--journaux', default='.')
    args = p.parse_args(argv)
    try:
        return {'preparer': preparer, 'critere-41': critere_41, 'critere-42': critere_42}[args.commande](args)
    except EnAttente as e:
        dire(f'EN ATTENTE : {e}')
        return EN_ATTENTE
    except Echec as e:
        dire(f'ÉCHEC : {e}')
        return 1


if __name__ == '__main__':
    sys.exit(main())
