#!/usr/bin/env python3
"""Outils des critères 28 et 29, le pilotage contre le faux G1 (section 7 du plan, critères 28 et 29 ;
section 11.5).

  outils_pilotage_e2e.py critere-28 --api URL --lieu ID
      répétition lancée par l'Atelier (Gazebo --jumeau, faux slam_operate, navigation), repérage,
      nœud pilotage lancé par l'Atelier (POST /api/pilotage/demarrer, port libre, jeton) ; puis :
      verrou avec le guide (prise refusée en visite, forcée, /guide/aller refusé, pont en état
      pilotage, robot immobile, main rendue : le guide repart) ; postures 500, 706, 3 (mode du faux
      G1, lu par 7001), 1 et 0 seulement avec la case « portique » et la confirmation double ;
      joystick par le WebSocket de l'Atelier (0,6 m en 2 s à 0,3 m/s, arrêt 0,6 s au plus après le
      dernier ordre ou la coupure, plafonds) ; gestes (26, 7401, 99, 7404) ; voix, volume, LED ;
      interdits (403, rien n'arrive au faux G1) ; demandes absurdes (jamais 500, refus en français).
  outils_pilotage_e2e.py critere-29 --api URL --lieu ID --choregraphies DOSSIER
      même montage ; danses du robot (liste 7100, 401, 402, 403 interdites, zone libre, 7101
      550604, joystick refusé pendant la danse, ARRÊT : StopMove et rien d'autre, retour en 801) ;
      chorégraphie exemple_kpop (rt/arm_sdk à 50 Hz, rampes, limites, vitesses, taille et jambes
      jamais pilotées, pas plafonnés et robot à 1 m au plus de son départ, LED et paroles à leur
      temps) ; ARRÊT au milieu (poids à 0 en moins de 1,5 s) ; chorégraphie fausse refusée.

La vérité terrain est /g1_jumeau/odom. Code de sortie : 0 réussi, 1 échoué, 77 : une pièce d'un autre
agent manque (le message dit laquelle), après que tout le reste a réussi.
"""
import argparse
import json
import math
import sys
import threading
import time
from pathlib import Path

ICI = Path(__file__).resolve().parent
RACINE = ICI.parent
sys.path.insert(0, str(ICI))
sys.path.insert(0, str(RACINE))

from critere_18_outils import (Echec, Ecoute, appel, attendre_relais, demarrer, francais,  # noqa: E402
                               reperer, verifier)
from outils_pont_e2e import Temoin, qos_verrou  # noqa: E402

PREFIXE = "pilotage"
SEUIL_ARRET = 0.02            # m/s : robot arrêté
ARRET_MAX_S = 0.6
EN_ATTENTE = 77


def dire(texte):
    print(f"[{PREFIXE}] {texte}", flush=True)


class Attente(Exception):
    """Une pièce d'un autre agent manque : le critère répond « en attente » (77)."""


class Observateur(Temoin):
    """Le témoin du pont (requêtes sport, vérité, /pont/etat), plus le faux G1, le verrou, le guide,
    les services arm et voice, /arm_sdk, /robot/dire et /pilotage/etat (validé)."""

    def __init__(self):
        super().__init__('e2e_pilotage')
        from rclpy.qos import qos_profile_sensor_data
        from std_msgs.msg import Empty, String
        from unitree_api.msg import Request
        from unitree_hg.msg import LowCmd
        n = self.noeud
        self.jumeau = None
        self.maitres, self.guides, self.evenements, self.paroles = [], [], [], []
        self.arm_sdk, self.autres_requetes, self.etats_pilotage, self.pilotage_non_conformes = [], [], [], []
        self.stops = []
        n.create_subscription(String, '/g1_jumeau/etat', self._jumeau, 10)
        n.create_subscription(String, '/mouvement/maitre', self._maitre, qos_verrou())
        n.create_subscription(String, '/guide/etat', self._guide, 50)
        n.create_subscription(String, '/guide/evenement', self._evenement, 50)
        n.create_subscription(String, '/robot/dire', self._parole, 50)
        n.create_subscription(String, '/pilotage/etat', self._pilotage, 50)
        n.create_subscription(Empty, '/guide/stop', lambda m: self.stops.append(time.monotonic()), 50)
        n.create_subscription(LowCmd, '/arm_sdk', self._bras, qos_profile_sensor_data)
        for service in ('arm', 'voice'):
            n.create_subscription(Request, f'/api/{service}/request',
                                  lambda m, s=service: self._autre(s, m), qos_profile_sensor_data)

    @staticmethod
    def _json(m):
        try:
            d = json.loads(m.data)
        except ValueError:
            return None
        return d if isinstance(d, dict) else None

    def _jumeau(self, m):
        d = self._json(m)
        if d is not None:
            self.jumeau = (time.monotonic(), d)

    def _maitre(self, m):
        d = self._json(m)
        if d is not None:
            with self.verrou:
                self.maitres.append((time.monotonic(), d))

    def _guide(self, m):
        d = self._json(m)
        if d is not None:
            with self.verrou:
                self.guides.append((time.monotonic(), d))
                del self.guides[:-3000]

    def _evenement(self, m):
        d = self._json(m)
        if d is not None:
            with self.verrou:
                self.evenements.append((time.monotonic(), d))

    def _parole(self, m):
        d = self._json(m)
        if d is not None:
            with self.verrou:
                self.paroles.append((time.monotonic(), d))

    def _pilotage(self, m):
        d = self._json(m)
        if d is None:
            return
        if self.valider is not None:
            erreurs = self.valider('etat_pilotage', d)
            if erreurs:
                self.pilotage_non_conformes.append((erreurs, d))
        with self.verrou:
            self.etats_pilotage.append((time.monotonic(), d))
            del self.etats_pilotage[:-2000]

    def _bras(self, m):
        with self.verrou:
            self.arm_sdk.append((time.monotonic(), m.motor_cmd[29].q))

    def _autre(self, service, m):
        with self.verrou:
            self.autres_requetes.append((time.monotonic(), service, m.header.identity.api_id, m.parameter))

    # ------------------------------------------------------------ lecture

    def robot(self):
        """Dernier état du faux G1 étendu (/g1_jumeau/etat, champ robot)."""
        return (self.jumeau or (0, {}))[1].get('robot') or {}

    def attendre(self, condition, delai, message):
        fin = time.monotonic() + delai
        while time.monotonic() < fin:
            try:
                if condition():
                    return
            except (KeyError, IndexError, TypeError):
                pass
            time.sleep(0.05)
        raise Echec(message)

    def guide(self):
        with self.verrou:
            return self.guides[-1][1] if self.guides else {}

    def maitre(self):
        with self.verrou:
            return self.maitres[-1][1]['maitre'] if self.maitres else None

    def requetes_sport(self, t0, t1=math.inf):
        """[(t, api_id, parameter dict)] des requêtes sport (pont et pilotage)."""
        return [(r[0], r[2], r[4]) for r in self.requetes_entre(t0, t1)]

    def deplacement(self, t0, t1=math.inf):
        v = self.verites_entre(t0, t1)
        if not v:
            return 0.0
        x0, y0 = v[0][2], v[0][3]
        return max(math.hypot(x - x0, y - y0) for _, _, x, y, _ in v)


def api(args):
    return args.api


def post(a, chemin, corps=None, delai=30):
    return appel(a, "POST", chemin, {} if corps is None else corps, delai=delai)


def preparer(args, obs, ecoute):
    """Répétition, repérage, Nav2, puis le nœud pilotage lancé par l'Atelier."""
    debut = time.monotonic()
    demarrer(args.api, args.lieu)
    attendre_relais(args.api, ecoute, args.lieu)
    verifier(obs.attendre_pret(30), "pas de vérité terrain ou de /pont/etat")
    code, r, duree = reperer(args.api, {"lieu": args.lieu, "etage": "rdc"})
    verifier(code == 200 and r.get("repere"), f"POST /api/robot/reperer : {code} {r}")
    dire(f"répétition prête et robot repéré en {time.monotonic() - debut:.0f} s")
    code, r = post(args.api, "/api/pilotage/demarrer", delai=60)
    verifier(code == 200, f"POST /api/pilotage/demarrer : {code} {r}")
    obs.attendre(lambda: obs.jumeau is not None and obs.robot().get('fsm') == 801, 20,
                 "le faux G1 étendu ne publie pas son mode (robot.fsm de /g1_jumeau/etat)")
    code, etat = appel(args.api, "GET", "/api/pilotage/etat")
    verifier(code == 200 and etat["robot_repond"] and etat["maitre"] == "guide",
             f"état du pilotage au départ : {code} {etat}")
    obs.attendre(lambda: obs.maitre() == 'guide', 10, "/mouvement/maitre « guide » pas reçu au démarrage du nœud")
    dire(f"nœud pilotage démarré par l'Atelier : {etat['message']} (mode {etat['fsm']}, robot relié)")


def prendre(args, obs, forcer=False):
    code, r = post(args.api, "/api/pilotage/maitre", {"maitre": "pilotage", "forcer": forcer}, delai=20)
    verifier(code == 200 and r.get("maitre") == "pilotage", f"prendre la main : {code} {r}")
    obs.attendre(lambda: obs.maitre() == 'pilotage', 3, "/mouvement/maitre « pilotage » pas reçu")
    obs.attendre(lambda: obs.dernier_etat().get('etat') == 'pilotage', 3, "le pont n'est pas en état pilotage")


def rendre(args, obs):
    code, r = post(args.api, "/api/pilotage/maitre", {"maitre": "guide"})
    verifier(code == 200 and r.get("maitre") == "guide", f"rendre la main : {code} {r}")
    obs.attendre(lambda: obs.maitre() == 'guide', 3, "/mouvement/maitre « guide » pas reçu")


def posture(args, obs, fsm, attendu=None, delai=6):
    code, r = post(args.api, "/api/pilotage/posture", {"fsm": fsm})
    verifier(code == 200, f"posture {fsm} : {code} {r}")
    attendu = fsm if attendu is None else attendu
    obs.attendre(lambda: obs.robot().get('fsm') == attendu, delai, f"posture {fsm} : le faux G1 n'est pas en mode {attendu}")

    def lu():
        return appel(args.api, "GET", "/api/pilotage/etat")[1].get('fsm') == attendu
    obs.attendre(lu, 4, f"posture {fsm} : 7001 ne lit pas le mode {attendu}")


class Joystick:
    """Le joystick de la page : WebSocket /ws/pilotage de l'Atelier, un ordre toutes les 0,1 s."""

    def __init__(self, a):
        from websockets.sync.client import connect
        self.ws = connect(a.replace("http", "ws", 1) + "/ws/pilotage", open_timeout=10)
        self.messages = []
        self.fil = threading.Thread(target=self._lire, daemon=True)
        self.fil.start()
        # comme la page : on attend que la chaîne page → Atelier → nœud soit ouverte (« bienvenue »)
        fin = time.monotonic() + 5.0
        while time.monotonic() < fin and not [m for _, m in self.messages if m.get('type') == 'bienvenue']:
            time.sleep(0.05)

    def _lire(self):
        try:
            for m in self.ws:
                try:
                    self.messages.append((time.monotonic(), json.loads(m)))
                except ValueError:
                    pass
        except Exception:       # noqa: BLE001 : fermée
            pass

    def tenir(self, vx, vy, wz, duree):
        """Ordres toutes les 0,1 s pendant duree ; renvoie (premier, dernier) instants."""
        debut = time.monotonic()
        dernier = debut
        while time.monotonic() - debut < duree:
            self.ws.send(json.dumps({"vx": vx, "vy": vy, "wz": wz}))
            dernier = time.monotonic()
            time.sleep(0.1)
        return debut, dernier

    def refus(self, depuis):
        return [m for t, m in self.messages if t >= depuis and m.get('type') == 'refus']

    def fermer(self):
        try:
            self.ws.close()
        except Exception:       # noqa: BLE001
            pass


def arret_apres(obs, t_ref, quoi):
    time.sleep(1.5)
    t = obs.instant_arret(t_ref, seuil=SEUIL_ARRET)
    verifier(t is not None, f"{quoi} : le robot ne s'arrête pas")
    verifier(t - t_ref <= ARRET_MAX_S, f"{quoi} : arrêté {t - t_ref:.2f} s après ({ARRET_MAX_S} s au plus)")
    return t - t_ref


ABSURDES = [
    ("/api/pilotage/posture", {"fsm": "debout"}), ("/api/pilotage/posture", {}),
    ("/api/pilotage/posture", {"fsm": 1e308}), ("/api/pilotage/led", {"r": -1, "g": 0, "b": 0}),
    ("/api/pilotage/led", {"r": "rouge"}), ("/api/pilotage/volume", {"volume": 1000}),
    ("/api/pilotage/voix", {"texte": ""}), ("/api/pilotage/danse", {"id": None}),
    ("/api/pilotage/geste", {"action": [26]}), ("/api/pilotage/requete", {"service": "moteurs", "api_id": 1}),
    ("/api/pilotage/requete", {"service": "sport", "api_id": 7105,
                               "parametre": {"velocity": [1e9, 0, 0], "duration": 0.5}}),
    ("/api/pilotage/requete", {"service": "sport", "api_id": 7105,
                               "parametre": {"velocity": [float("nan"), 0, 0], "duration": 0.5}}),
    ("/api/pilotage/maitre", {"maitre": "personne"}), ("/api/pilotage/choregraphies/..%2F..%2Fetc/jouer", {}),
    ("/api/pilotage/choregraphies/inconnue/jouer", {"zone_libre": True}),
]


# ---------------------------------------------------------------- critère 28

def verrou_avec_le_guide(args, obs):
    """Guide en visite : prise refusée (409), forcée ; /guide/aller refusé ; main rendue."""
    a = args.api
    rendre(args, obs)
    code, r = post(a, "/api/guide/aller", {"cible": "b204"})
    verifier(code == 200, f"/api/guide/aller b204 : {code} {r}")
    obs.attendre(lambda: obs.guide().get('etat') in ('en_route', 'bloque', 'detour', 'attente_passage'), 60,
                 f"le guide ne part pas vers b204 (état {obs.guide().get('etat')})")
    obs.attendre(lambda: obs.vitesse_robot(time.monotonic() - 1.0, time.monotonic()) is not None
                 and abs(obs.vitesse_robot(time.monotonic() - 1.0, time.monotonic())[0]) > 0.1, 60,
                 "le robot ne bouge pas avec le guide")
    code, r = post(a, "/api/pilotage/maitre", {"maitre": "pilotage"})
    verifier(code == 409 and francais(r) and "mission" in r["detail"], f"prendre la main en visite : {code} {r} (409)")
    dire(f"prendre la main pendant la visite : 409 « {r['detail'][:70]}… »")
    t_force = time.monotonic()
    prendre(args, obs, forcer=True)
    verifier([t for t in obs.stops if t >= t_force], "forcer n'a pas envoyé /guide/stop")
    t_arret = obs.instant_arret(t_force, seuil=SEUIL_ARRET)
    verifier(t_arret is not None and t_arret - t_force < 2.0, "le robot ne s'arrête pas quand on force la main")
    dire(f"main prise de force : /guide/stop, robot arrêté {t_arret - t_force:.2f} s après, pont en état pilotage")
    # le guide refuse /guide/aller (agent C) ; le robot reste immobile quoi qu'il arrive (pont)
    t0 = time.monotonic()
    code, r = post(a, "/api/guide/aller", {"cible": "b204"})
    time.sleep(4.0)
    bouge = obs.deplacement(t0 + 0.2)
    verifier(bouge < 0.05, f"le robot a bougé de {bouge:.2f} m alors que le pilotage a la main")
    verifier(obs.dernier_etat().get('etat') == 'pilotage', f"pont : {obs.dernier_etat().get('etat')} (pilotage attendu)")
    with obs.verrou:
        etats = [g.get('etat') for t, g in obs.guides if t >= t0]
        evenements = [e.get('code') for t, e in obs.evenements if t >= t0]
    refuse = code != 200 or ('echec' in etats and 'pilotage' in evenements)
    dire(f"/guide/aller pendant le pilotage : HTTP {code}, états {sorted(set(etats))}, événements {evenements} ; "
         f"robot immobile ({bouge * 100:.1f} cm en 4 s), pont en état pilotage")
    code, r = post(a, "/api/pilotage/arret")
    verifier(code == 200, f"ARRÊT avec le pilotage : {code} {r}")
    rendre(args, obs)
    obs.attendre(lambda: obs.dernier_etat().get('etat') != 'pilotage', 3, "le pont reste en état pilotage après « rendre »")
    t1 = time.monotonic()
    code, r = post(a, "/api/guide/aller", {"cible": "accueil"})
    verifier(code == 200, f"/api/guide/aller accueil après « rendre la main » : {code} {r}")
    obs.attendre(lambda: obs.guide().get('etat') == 'arrive' and obs.guides[-1][0] > t1 + 1, 240,
                 f"le guide ne repart pas après « rendre la main » (état {obs.guide().get('etat')})")
    dire(f"main rendue : le guide repart à la demande suivante et revient à l'accueil ({time.monotonic() - t1:.0f} s)")
    code, r = post(a, "/api/pilotage/arret")
    verifier(code == 200, f"ARRÊT sans la main : {code} {r}")
    dire("ARRÊT permis avec le guide comme maître : 200")
    time.sleep(1.0)
    return refuse


def postures(args, obs):
    a = args.api
    code, r = post(a, "/api/pilotage/posture", {"fsm": 500})
    verifier(code == 409 and "main" in r["detail"], f"posture sans la main : {code} {r} (409)")
    prendre(args, obs)
    posture(args, obs, 500, attendu=801)
    posture(args, obs, 706)
    posture(args, obs, 706, attendu=801)
    posture(args, obs, 3)
    dire("postures 500 (puis 801), 706, 706 (debout) et 3 acceptées : mode du faux G1 changé, lu par 7001")
    for fsm in (1, 0):
        t0 = time.monotonic()
        code, r = post(a, "/api/pilotage/posture", {"fsm": fsm})
        verifier(code == 428 and r.get("confirmation") == "portique" and not r.get("jeton"),
                 f"posture {fsm} sans la case portique : {code} {r}")
        code, r = post(a, "/api/pilotage/posture", {"fsm": fsm, "portique": True})
        verifier(code == 428 and r.get("jeton"), f"posture {fsm} : premier appel {code} {r} (428 et un jeton)")
        code, faux = post(a, "/api/pilotage/posture", {"fsm": fsm, "portique": True, "jeton": "faux"})
        verifier(code == 428, f"posture {fsm} avec un faux jeton : {code} {faux}")
        envoyes = [p for _, api_id, p in obs.requetes_sport(t0) if api_id == 7101]
        verifier(not envoyes, f"posture {fsm} envoyée sans la confirmation double : {envoyes}")
        code, r = post(a, "/api/pilotage/posture", {"fsm": fsm, "portique": True, "jeton": r["jeton"]})
        verifier(code == 200, f"posture {fsm} confirmée : {code} {r}")
        obs.attendre(lambda f=fsm: obs.robot().get('fsm') == f, 4, f"posture {fsm} confirmée : faux G1 pas en mode {fsm}")
    dire("postures 1 et 0 : refusées sans la case « portique » ni la confirmation double, acceptées avec")
    posture(args, obs, 702, attendu=801, delai=8)
    dire("posture 702 (se relever) : le faux G1 revient en 801")


def joystick(args, obs):
    a = args.api
    time.sleep(1.0)
    j = Joystick(a)
    try:
        time.sleep(0.5)
        x0 = obs.pose()
        premier, dernier = j.tenir(0.3, 0.0, 0.0, 2.0)
        j.ws.send(json.dumps({"lacher": True}))
        delai = arret_apres(obs, dernier, "joystick lâché")
        x1 = obs.pose()
        d = math.hypot(x1[0] - x0[0], x1[1] - x0[1])
        verifier(0.4 <= d <= 0.8, f"joystick vx 0,3 pendant 2 s : {d:.2f} m (0,6 ± 0,2 attendu)")
        dire(f"joystick par l'Atelier : vx 0,3 pendant 2 s → {d:.2f} m, arrêté {delai:.2f} s après le dernier ordre")
        # homme mort : plus d'ordre (sans « lâcher »)
        premier, dernier = j.tenir(0.3, 0.0, 0.0, 1.0)
        delai = arret_apres(obs, dernier, "homme mort")
        dire(f"homme mort : arrêté {delai:.2f} s après le dernier ordre, sans « lâcher »")
        # plafonds
        t0 = time.monotonic()
        premier, dernier = j.tenir(1.0, 0.0, 0.0, 1.5)
        j.ws.send(json.dumps({"lacher": True}))
        arret_apres(obs, dernier, "plafonds")
        ordres = [p for _, api_id, p in obs.requetes_sport(t0) if api_id == 7105 and p and p['velocity'][0] > 0]
        verifier(ordres and max(p['velocity'][0] for p in ordres) <= 0.4 + 1e-9,
                 f"plafond : vx demandé 1,0, envoyé {max((p['velocity'][0] for p in ordres), default=None)}")
        vitesse = obs.vitesse_robot(premier + 0.5, dernier)
        verifier(vitesse is not None and vitesse[0] <= 0.42, f"vitesse mesurée {vitesse} (0,42 m/s au plus)")
        dire(f"plafonds : 1,0 m/s demandé → 7105 à {max(p['velocity'][0] for p in ordres):.2f}, "
             f"vitesse mesurée {vitesse[0]:.2f} m/s")
    finally:
        j.fermer()
    # WebSocket coupé en marche
    j = Joystick(a)
    try:
        time.sleep(0.3)
        j.tenir(-0.3, 0.0, 0.0, 1.0)
        coupure = time.monotonic()
    finally:
        j.fermer()
    delai = arret_apres(obs, coupure, "WebSocket coupé")
    dire(f"WebSocket coupé en marche : arrêté {delai:.2f} s après la coupure")


def gestes_voix(args, obs):
    a = args.api
    code, r = post(a, "/api/pilotage/geste", {"action": 26})
    verifier(code == 200 and r.get("code") == 0, f"geste 26 : {code} {r}")
    code, r = post(a, "/api/pilotage/geste", {"action": 20})
    verifier(code == 409 and r.get("code") == 7401 and "relâchez" in r["detail"], f"geste pendant que les bras tiennent : {code} {r}")
    dire(f"geste 26 accepté ; un autre geste pendant qu'il tient : 409 « {r['detail'][:60]}… » (7401)")
    code, r = post(a, "/api/pilotage/geste", {"action": 99})
    verifier(code == 200 and not obs.robot().get('bras_tenus'), f"geste 99 : {code} {r}")
    posture(args, obs, 3)
    code, r = post(a, "/api/pilotage/geste", {"action": 26})
    verifier(code == 409 and r.get("code") == 7404 and "debout" in r["detail"], f"geste assis : {code} {r}")
    dire(f"99 relâche ; geste en posture assise : 409 « {r['detail'][:60]}… » (7404)")
    posture(args, obs, 500, attendu=801)
    texte = "Bonjour, je suis le robot d'accueil."
    for chemin, corps in (("/api/pilotage/voix", {"texte": texte}), ("/api/pilotage/volume", {"volume": 55}),
                          ("/api/pilotage/led", {"r": 12, "g": 34, "b": 56})):
        code, r = post(a, chemin, corps)
        verifier(code == 200, f"{chemin} : {code} {r}")
    obs.attendre(lambda: obs.robot()['voix']['tts']['text'] == texte and obs.robot()['voix']['volume'] == 55
                 and obs.robot()['voix']['led'] == {'R': 12, 'G': 34, 'B': 56}, 3,
                 f"voix, volume ou LED pas reçus par le faux G1 : {obs.robot().get('voix')}")
    with obs.verrou:
        voix = [(api_id, json.loads(p)) for _, s, api_id, p in obs.autres_requetes if s == 'voice']
    verifier((1006, {"volume": 55}) in voix and (1010, {"R": 12, "G": 34, "B": 56}) in voix,
             f"paramètres de voice : {voix[-4:]}")
    dire("voix (1001), volume (1006 {volume: 55}) et LED (1010 {R, G, B}) reçus par le faux G1")


def interdits(args, obs):
    a = args.api
    t0 = time.monotonic()
    avant = obs.robot().get('nombre_interdits')
    refus = []
    for corps in ({"service": "sport", "api_id": 7104, "parametre": {"data": 1}},
                  {"service": "sport", "api_id": 7110, "parametre": {}}):
        code, r = post(a, "/api/pilotage/requete", corps)
        verifier(code == 403 and francais(r), f"{corps['api_id']} : {code} {r} (403)")
        refus.append(str(corps['api_id']))
    for fsm in (2, 4, 801):
        code, r = post(a, "/api/pilotage/posture", {"fsm": fsm})
        verifier(code == 403 and francais(r), f"posture {fsm} : {code} {r} (403)")
        refus.append(f"posture {fsm}")
    time.sleep(1.0)
    interdites = [(api_id, p) for _, api_id, p in obs.requetes_sport(t0)
                  if api_id in (7104, 7110) or (api_id == 7101 and p and p.get('data') in (2, 4, 801))]
    verifier(not interdites, f"des commandes interdites sont arrivées au faux G1 : {interdites}")
    verifier(obs.robot().get('nombre_interdits') == avant, "le faux G1 a compté des commandes interdites")
    dire(f"interdits refusés (403), aucune requête au faux G1 : {', '.join(refus)}")
    codes = []
    for chemin, corps in ABSURDES:
        code, r = appel(a, "POST", chemin, corps)
        verifier(code != 500 and 400 <= code < 500 and francais(r), f"{chemin} {corps} : {code} {r}")
        codes.append(code)
    dire(f"{len(ABSURDES)} demandes absurdes : jamais d'erreur 500, refus en français ({sorted(set(codes))})")


def critere_28(args):
    ecoute = Ecoute()
    obs = Observateur()
    try:
        preparer(args, obs, ecoute)
        t_nav2 = time.monotonic()
        while not _nav2_actif(obs):
            verifier(time.monotonic() - t_nav2 < 120, "Nav2 n'est pas actif 120 s après le repérage")
            time.sleep(0.5)
        dire(f"Nav2 actif {time.monotonic() - t_nav2:.1f} s après le démarrage du pilotage")
        guide_refuse = verrou_avec_le_guide(args, obs)
        postures(args, obs)
        joystick(args, obs)
        gestes_voix(args, obs)
        interdits(args, obs)
        verifier(not obs.non_conformes, f"/pont/etat non conforme : {obs.non_conformes[:2]}")
        verifier(not obs.pilotage_non_conformes, f"/pilotage/etat non conforme : {obs.pilotage_non_conformes[:2]}")
        dire(f"{len(obs.etats)} /pont/etat et {len(obs.etats_pilotage)} /pilotage/etat, tous conformes")
        code, r = post(args.api, "/api/pilotage/arreter", delai=30)
        verifier(code == 200 and r.get("arrete"), f"POST /api/pilotage/arreter : {code} {r}")
        obs.attendre(lambda: obs.maitre() == 'guide', 5, "le nœud arrêté n'a pas rendu la main au guide")
        if not guide_refuse:
            raise Attente("le guide accepte encore /guide/aller pendant le pilotage (refus, échec et événement "
                          "« pilotage » : agent Comportement du guide) ; le pont a gardé le robot immobile")
        return 0
    finally:
        obs.fermer()
        ecoute.fermer()


def _nav2_actif(obs):
    from critere_19_outils import Observateur as O19
    return O19.nav2_actif(obs)


# ---------------------------------------------------------------- critère 29

def danses(args, obs):
    a = args.api
    prendre(args, obs)
    t0 = time.monotonic()
    code, r = appel(a, "GET", "/api/pilotage/danses?lire=1")
    verifier(code == 200, f"lire la liste des danses : {code} {r}")
    liste = {d["id"]: d for d in r["danses"]}
    verifier({401, 402, 403, 602, 603, 604, 574} <= set(liste), f"liste des danses : {sorted(liste)}")
    verifier({n for n, d in liste.items() if d["interdite"]} == {401, 402, 403}, "401, 402 et 403 pas marquées interdites")
    verifier([p for _, api_id, p in obs.requetes_sport(t0) if api_id == 7100] == [{"fsm_id": 550, "api_id": 1}],
             "la liste n'a pas été demandée par 7100 {fsm_id: 550, api_id: 1}")
    dire(f"liste lue (7100) : {len(liste)} danses, 401, 402 et 403 marquées interdites")
    t1 = time.monotonic()
    code, r = post(a, "/api/pilotage/danse", {"id": 604})
    verifier(code == 428 and r.get("confirmation") == "zone_libre", f"danse 604 sans zone libre : {code} {r}")
    for n in (401, 402, 403):
        code, r = post(a, "/api/pilotage/danse", {"id": n, "zone_libre": True})
        verifier(code == 403 and francais(r), f"danse {n} : {code} {r} (403)")
    time.sleep(0.5)
    envoyes = [p for _, api_id, p in obs.requetes_sport(t1) if api_id == 7101]
    verifier(not envoyes, f"danse envoyée malgré le refus : {envoyes}")
    dire("danse 604 sans « zone libre » : 428 ; 401, 402 et 403 refusées même confirmées (403), rien d'envoyé")
    t2 = time.monotonic()
    code, r = post(a, "/api/pilotage/danse", {"id": 604, "zone_libre": True})
    verifier(code == 200, f"danse 604 : {code} {r}")
    verifier([p for _, api_id, p in obs.requetes_sport(t2) if api_id == 7101] == [{"data": 550604}],
             "7101 {data: 550604} pas reçu")
    obs.attendre(lambda: obs.robot().get('fsm') == 550604, 3, "le faux G1 ne danse pas")
    j = Joystick(a)
    try:
        time.sleep(0.3)
        t3 = time.monotonic()
        j.tenir(0.3, 0.0, 0.0, 0.6)
        time.sleep(0.3)
        verifier(j.refus(t3), "le joystick n'est pas refusé pendant la danse")
        verifier(not [p for _, api_id, p in obs.requetes_sport(t3) if api_id == 7105 and p and any(p['velocity'])],
                 "un ordre de marche est parti pendant la danse")
    finally:
        j.fermer()
    code, r = post(a, "/api/pilotage/geste", {"action": 26})
    verifier(code == 409, f"geste pendant la danse : {code} {r}")
    t4 = time.monotonic()
    code, r = post(a, "/api/pilotage/arret")
    verifier(code == 200 and r.get("danse"), f"ARRÊT pendant la danse : {code} {r}")
    time.sleep(1.0)
    apres = [(api_id, p) for _, api_id, p in obs.requetes_sport(t4) if api_id != 7001]
    with obs.verrou:
        autres = [x for x in obs.autres_requetes if x[0] >= t4]
    verifier(apres == [(7105, {"velocity": [0.0, 0.0, 0.0], "duration": 1.0})] and not autres,
             f"ARRÊT pendant la danse : {apres} {autres} (StopMove seulement)")
    dire("pendant la danse : joystick et gestes refusés ; ARRÊT : StopMove et rien d'autre")
    obs.attendre(lambda: obs.robot().get('fsm') == 801, 25, "le faux G1 ne revient pas en 801 après la danse")

    def finie():
        e = appel(a, "GET", "/api/pilotage/etat")[1]
        return e.get("danse") is None and e.get("fsm") == 801
    obs.attendre(finie, 15, "le pilotage ne voit pas la fin de la danse")
    dire(f"danse 604 finie en {time.monotonic() - t2:.1f} s : retour en mode 801")


def choregraphie(args, obs):
    a = args.api
    import yaml
    from atelier.lieu import pilotage as D
    d = yaml.safe_load((Path(args.choregraphies) / "exemple_kpop.choregraphie.yaml").read_text(encoding="utf-8"))
    time.sleep(1.2)
    depart = obs.pose()
    code, r = post(a, "/api/pilotage/choregraphies/exemple_kpop/jouer", {})
    verifier(code == 428, f"chorégraphie sans zone libre : {code} {r}")
    t0 = time.monotonic()
    code, r = post(a, "/api/pilotage/choregraphies/exemple_kpop/jouer", {"zone_libre": True})
    verifier(code == 200 and r.get("debut_mur"), f"jouer exemple_kpop : {code} {r}")
    debut = time.monotonic() - (time.time() - r["debut_mur"])          # départ, en temps monotone
    fin = debut + d["duree_s"]
    while time.monotonic() < fin + 2.5:
        time.sleep(0.5)
    arm = obs.robot()["arm_sdk"]
    session = arm["sessions"][-1]
    verifier(arm["ecarts"] == {k: 0 for k in arm["ecarts"]}, f"rt/arm_sdk : écarts {arm['ecarts']} {arm['exemples'][:3]}")
    verifier(abs(session["frequence_hz"] - 50.0) <= 5.0, f"rt/arm_sdk à {session['frequence_hz']} Hz (50 ± 10 %)")
    verifier(session["rampe_montee_s"] >= 1.0 and session["rampe_descente_s"] >= 1.0,
             f"rampes du poids : {session['rampe_montee_s']} s et {session['rampe_descente_s']} s (1 s au moins)")
    verifier(abs(session["duree_s"] - d["duree_s"]) < 0.6, f"session arm_sdk de {session['duree_s']} s")
    with obs.verrou:
        recus = [t for t, _ in obs.arm_sdk if debut - 1 <= t <= fin + 1]
    frequence = (len(recus) - 1) / (recus[-1] - recus[0])
    verifier(abs(frequence - 50.0) <= 5.0, f"/arm_sdk vu à {frequence:.1f} Hz par le test")
    dire(f"rt/arm_sdk : {session['messages']} ordres à {session['frequence_hz']:.1f} Hz, rampes de "
         f"{session['rampe_montee_s']:.2f} et {session['rampe_descente_s']:.2f} s, aucun écart (limites, vitesses, "
         "taille et jambes jamais pilotées)")
    pas = [p for t, api_id, p in obs.requetes_sport(t0, fin + 1) if api_id == 7105 and p and any(p['velocity'])]
    verifier(pas, "aucun pas de marche pendant la chorégraphie")
    for p in pas:
        vx, vy, wz = p["velocity"]
        verifier(abs(vx) <= D.LIMITES_PAS["vx"] and abs(vy) <= D.LIMITES_PAS["vy"] and abs(wz) <= D.LIMITES_PAS["wz"]
                 and p["duration"] <= 0.5, f"pas hors limites : {p}")
    loin = max(math.hypot(x - depart[0], y - depart[1]) for _, _, x, y, _ in obs.verites_entre(debut, fin + 1))
    verifier(loin <= D.DEPLACEMENT_MAX_M, f"le robot s'est éloigné de {loin:.2f} m de son départ (1 m au plus)")
    dire(f"pas : {len(pas)} ordres 7105 sous les plafonds, robot à {loin:.2f} m au plus de son départ (vérité)")
    leds = [e for e in obs.robot()["voix"]["led_historique"] if debut - 0.5 <= e["t"] <= fin + 0.5]
    verifier(len(leds) == len(d["led"]), f"{len(leds)} couleurs reçues pour {len(d['led'])} prévues")
    for e, prevu in zip(leds, d["led"]):
        verifier((e["R"], e["G"], e["B"]) == (prevu["r"], prevu["g"], prevu["b"]) and abs(e["t"] - debut - prevu["t"]) <= 0.2,
                 f"LED {prevu} reçue {e} ({e['t'] - debut:.2f} s)")
    with obs.verrou:
        paroles = [(t, m) for t, m in obs.paroles if debut - 0.5 <= t <= fin + 0.5]
    verifier([m["texte"] for _, m in paroles] == [p["texte"] for p in d["paroles"]], f"paroles : {paroles}")
    for (t, m), prevu in zip(paroles, d["paroles"]):
        verifier(abs(t - debut - prevu["t"]) <= 0.2 and m.get("source") == "choregraphie", f"parole {prevu} à {t - debut:.2f} s")
    ecart_max = max([abs(e["t"] - debut - p["t"]) for e, p in zip(leds, d["led"])]
                    + [abs(t - debut - p["t"]) for (t, _), p in zip(paroles, d["paroles"])])
    dire(f"LED ({len(leds)}) et paroles ({len(paroles)}, sur /robot/dire) à leur temps, à {ecart_max:.2f} s au plus")
    # ARRÊT au milieu
    time.sleep(1.5)
    code, r = post(a, "/api/pilotage/choregraphies/exemple_kpop/jouer", {"zone_libre": True})
    verifier(code == 200, f"rejouer exemple_kpop : {code} {r}")
    debut = time.monotonic() - (time.time() - r["debut_mur"])
    time.sleep(max(0.0, debut + 10.5 - time.monotonic()))
    t_arret = time.monotonic()
    code, r = post(a, "/api/pilotage/arret")
    verifier(code == 200, f"ARRÊT pendant la chorégraphie : {code} {r}")
    time.sleep(2.5)
    with obs.verrou:
        poids = [(t, q) for t, q in obs.arm_sdk if t >= t_arret]
    zero = next((t for t, q in poids if q <= 1e-6), None)
    verifier(zero is not None and zero - t_arret <= 1.5, f"poids des bras pas à 0 en 1,5 s après l'ARRÊT ({zero})")
    stop = [p for _, api_id, p in obs.requetes_sport(t_arret) if api_id == 7105 and p and not any(p['velocity'])]
    verifier(stop, "pas de StopMove à l'ARRÊT")
    with obs.verrou:
        apres = [t for t, _ in obs.arm_sdk if t > zero + 0.1]
    verifier(not apres, "rt/arm_sdk publié encore après la descente du poids")
    dire(f"ARRÊT au milieu : poids des bras à 0 en {zero - t_arret:.2f} s, StopMove, plus rien sur rt/arm_sdk")
    # chorégraphie hors limites
    mauvaise = dict(d, id="mauvaise", nom="Hors limites")
    mauvaise["bras"] = dict(d["bras"], poses=[dict(p) for p in d["bras"]["poses"]])
    mauvaise["bras"]["poses"][3] = dict(mauvaise["bras"]["poses"][3], q=dict(mauvaise["bras"]["poses"][3]["q"], left_elbow=2.9))
    mauvaise["pas"] = [{"t": t, "vx": 0.3, "vy": 0.0, "wz": 0.0, "duree_s": 2.0} for t in (0.0, 2.0)] + d["pas"]
    (Path(args.choregraphies) / "mauvaise.choregraphie.yaml").write_text(yaml.safe_dump(mauvaise, allow_unicode=True),
                                                                         encoding="utf-8")
    time.sleep(1.0)
    t5 = time.monotonic()
    code, r = post(a, "/api/pilotage/choregraphies/mauvaise/jouer", {"zone_libre": True})
    verifier(code == 422 and len(r.get("erreurs", [])) >= 2 and francais(r)
             and any("limites" in e for e in r["erreurs"]) and any("départ" in e for e in r["erreurs"]),
             f"chorégraphie hors limites : {code} {r}")
    time.sleep(1.0)
    with obs.verrou:
        verifier(not [t for t, _ in obs.arm_sdk if t >= t5], "rt/arm_sdk publié pour une chorégraphie refusée")
    dire(f"chorégraphie hors limites refusée avant de jouer (422), {len(r['erreurs'])} erreurs en français, "
         f"ex. « {r['erreurs'][0][:70]}… »")


def critere_29(args):
    ecoute = Ecoute()
    obs = Observateur()
    try:
        preparer(args, obs, ecoute)
        danses(args, obs)
        choregraphie(args, obs)
        verifier(not obs.non_conformes, f"/pont/etat non conforme : {obs.non_conformes[:2]}")
        verifier(not obs.pilotage_non_conformes, f"/pilotage/etat non conforme : {obs.pilotage_non_conformes[:2]}")
        code, r = post(args.api, "/api/pilotage/arreter", delai=30)
        verifier(code == 200, f"POST /api/pilotage/arreter : {code} {r}")
        return 0
    finally:
        obs.fermer()
        ecoute.fermer()


def main(argv=None):
    p = argparse.ArgumentParser(prog="outils_pilotage_e2e.py", description=__doc__.split("\n")[0])
    sous = p.add_subparsers(dest="action", required=True)
    for nom in ("critere-28", "critere-29"):
        s = sous.add_parser(nom)
        s.add_argument("--api", required=True)
        s.add_argument("--lieu", required=True)
        s.add_argument("--choregraphies", default=str(RACINE / "choregraphies"))
    args = p.parse_args(argv)
    global PREFIXE
    PREFIXE = "critère " + args.action.split("-")[1]
    try:
        return {"critere-28": critere_28, "critere-29": critere_29}[args.action](args)
    except Echec as e:
        print(f"[{PREFIXE}] ÉCHEC : {e}", flush=True)
        return 1
    except Attente as e:
        print(f"[{PREFIXE}] EN ATTENTE : {e}", flush=True)
        return EN_ATTENTE


if __name__ == "__main__":
    sys.exit(main())
