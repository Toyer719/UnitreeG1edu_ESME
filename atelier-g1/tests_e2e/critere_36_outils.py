#!/usr/bin/env python3
"""Outils du critère 36, l'ARRÊT global (section 12.10 du plan) : agent Coquille.

  critere_36_outils.py critere-36 --api URL --lieu ID
      1. simulation (POST /api/simulation/demarrer, mode simu) : téléopération à 0,3 m/s
         (POST /api/simulation/teleop) ; POST /api/arret {mode: simu} répond en moins de 1 s, le robot
         s'arrête (vérité /odom, moins de 2 cm/s) en moins de 1 s, sans verrou (verrou faux, rien de
         publié sur /pont/arret) ;
      2. répétition (Gazebo --jumeau, faux slam_operate, navigation), repérage, Nav2 ; « Y aller » vers
         b204 ; quand le robot roule (plus de 0,15 m/s, vérité /g1_jumeau/odom) : POST /api/arret
         {mode: repetition} en moins de 1 s (200, parties.guide.ok et parties.verrou.ok vrais), robot
         arrêté moins de 1 s après la demande, /guide/etat quitte en_route, /pont/etat passe à
         arret_verrouille en moins de 1 s ;
      3. verrou posé : un nouveau « Y aller » laisse le robot immobile (moins de 5 cm) pendant 5 s, et le
         guide le refuse (echec, immobilise verrou) ; GET /api/arret dit verrou vrai ;
         POST /api/arret/debloquer : rien ne repart pendant 5 s ; puis « Y aller » : le robot repart
         (0,3 m au moins) ;
      3 bis. un déblocage ne relance jamais l'ancien trajet (correction du 01/11/2026, section 12.15) :
         en route, « Bloquer » (POST /api/robot/arret {verrou: true}, qui envoie aussi /guide/stop) :
         robot arrêté en moins de 1 s, guide en attente avec immobilise verrou (ni bloque, ni détour,
         ni échec, ni retour pendant 5 s), puis « Débloquer » : AUCUN mouvement pendant 15 s (moins de
         5 cm, aucun 7105 non nul), guide en attente sans immobilise, « Robot débloqué : il attend un
         nouveau « Y aller » » ; même chose avec le verrou en ligne de commande (/pont/arret,
         transient_local) et avec le faux G1 assis puis remis en marche (pas_en_marche) ; puis un
         nouveau « Y aller » repart ;
      4. Firefox sans fenêtre, robot en route : le clic sur [data-role=arret] et la touche Échap envoient
         POST /api/arret ; le bouton passe à « Débloquer » (data-etat=bloque) ; pendant le blocage, les
         boutons « Y aller » de Naviguer et la commande du ruban sont grisés, et le panneau dit « Robot
         bloqué » (relecture du 01/11/2026) ;
      4 bis. arrivé à une salle proche, retour automatique prévu, le menu « Y aller » du ruban ouvert : Échap
         envoie POST /api/arret (le retour prévu compte comme un robot qui peut repartir), et rien ne part
         pendant 15 s après « Débloquer » (relecture du 01/11/2026) ;
      5. nœud pilotage (POST /api/pilotage/demarrer), main prise, joystick à vx 0,3 par /ws/pilotage :
         « Bloquer » arrête aussi le joystick (le pilotage parle directement au robot), qui reste refusé
         pendant le blocage et après « Débloquer » tant qu'il n'est pas lâché ;
         POST /api/arret → StopMove (7105 [0, 0, 0] d'une seconde) reçu par le faux G1 en moins de 1 s,
         robot arrêté ; nœud pilotage arrêté : POST /api/arret répond quand même en moins de 1 s,
         parties.pilotage.ok faux avec un message, le reste arrêté (guide, verrou) ;
      6. jamais d'erreur 500 (toutes les réponses de l'API notées).
Code de sortie : 0 réussi, 1 échoué (le message dit pourquoi), 77 en attente (une pièce manque).
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

from critere_18_outils import (Echec, Ecoute, appel, attendre_relais, demarrer,  # noqa: E402
                               reperer, verifier)
from outils_pilotage_e2e import Observateur  # noqa: E402
from outils_pont_e2e import Noeud, qos_verrou  # noqa: E402

EN_ATTENTE = 77
SEUIL_ROULE = 0.15            # m/s : le robot roule
SEUIL_ARRET = 0.02            # m/s : le robot est arrêté
DELAI_REPONSE_S = 1.0
DELAI_ARRET_S = 1.0
STOP_MOVE = {"velocity": [0.0, 0.0, 0.0], "duration": 1.0}
CODES = []                    # (méthode, chemin, code) de chaque appel à l'API
# Section 12.15 : après un déblocage, rien ne doit repartir pendant ce temps (sans nouvelle demande)
SANS_REPRISE_S = 15.0
SANS_REPRISE_COURT_S = 8.0
IMMOBILE_M = 0.05
# Salles du demo (salles.yaml) : la plus loin du robot sert de but, pour qu'il roule assez longtemps
SALLES_DEMO = {"accueil": (2.5, 10.0), "vie_scolaire": (7.0, 7.0), "infirmerie": (15.0, 7.0), "cdi": (23.0, 7.0),
               "amphi": (9.0, 13.0), "b204": (21.0, 13.0)}
ETATS_EN_MISSION = ("en_route", "retour", "bloque", "detour", "attente_passage", "attente_visiteur", "perdu")


def dire(texte):
    print("   " + texte, flush=True)


def ok(texte):
    print("ok : " + texte, flush=True)


def api(a, methode, chemin, corps=None, delai=60):
    code, r = appel(a, methode, chemin, corps, delai=delai)
    CODES.append((methode, chemin, code))
    verifier(code != 500, f"{methode} {chemin} : erreur 500 {r}")
    return code, r


def arret(a, mode):
    """POST /api/arret {mode} ; renvoie (instant de la demande, durée, réponse)."""
    t = time.monotonic()
    code, r = api(a, "POST", "/api/arret", {"mode": mode, "raison": "critère 36"}, delai=5)
    duree = time.monotonic() - t
    verifier(code == 200, f"POST /api/arret {mode} : {code} {r}")
    verifier(duree < DELAI_REPONSE_S, f"POST /api/arret {mode} : réponse en {duree:.2f} s (moins de 1 s)")
    return t, duree, r


def parties(r):
    return ", ".join(f"{k} {v['ok']}" for k, v in r["parties"].items())


# ---------------------------------------------------------------- vérité de la simulation (/odom)

class Simu(Noeud):
    """/odom (vérité de la simulation) et /pont/arret (le verrou : rien ne doit y passer en simulation)."""

    def __init__(self):
        super().__init__("e2e_critere_36_simu")
        from nav_msgs.msg import Odometry
        from rclpy.qos import qos_profile_sensor_data
        from std_msgs.msg import Bool
        self.verrou_fil = threading.Lock()
        self.odom = []
        self.verrous = []
        self.noeud.create_subscription(Odometry, "/odom", self._odom, qos_profile_sensor_data)
        self.noeud.create_subscription(Bool, "/pont/arret", self._verrou, qos_verrou())

    def _odom(self, m):
        p = m.pose.pose.position
        with self.verrou_fil:
            self.odom.append((time.monotonic(), m.header.stamp.sec + m.header.stamp.nanosec * 1e-9, p.x, p.y))
            del self.odom[:-20000]

    def _verrou(self, m):
        with self.verrou_fil:
            self.verrous.append((time.monotonic(), bool(m.data)))

    def vitesse(self, depuis=0.3):
        """Vitesse (m/s) sur les dernières depuis secondes de temps simulé, ou None."""
        with self.verrou_fil:
            v = list(self.odom[-400:])
        if len(v) < 2:
            return None
        fin = v[-1]
        debut = next((x for x in v if fin[1] - x[1] <= depuis), v[0])
        dt = fin[1] - debut[1]
        return math.hypot(fin[2] - debut[2], fin[3] - debut[3]) / dt if dt > 0.05 else None

    def instant_arret(self, t_ref, tenue=0.3):
        """Premier instant mural après t_ref où la vitesse (sur 0,1 s simulée) reste sous le seuil."""
        with self.verrou_fil:
            v = [x for x in self.odom if x[0] >= t_ref - 0.3]
        vitesses = []
        j = 0
        for i, (t, s, x, y) in enumerate(v):
            j = max(j, i)
            while j + 1 < len(v) and v[j][1] - s < 0.1:
                j += 1
            if v[j][1] - s >= 0.099:
                vitesses.append((t, math.hypot(v[j][2] - x, v[j][3] - y) / (v[j][1] - s)))
        for k, (t, w) in enumerate(vitesses):
            if t < t_ref or w >= SEUIL_ARRET:
                continue
            suite = [u for (tt, u) in vitesses[k:] if tt <= t + tenue]
            if all(u < SEUIL_ARRET for u in suite) and vitesses[-1][0] >= t + tenue:
                return t
        return None


class Observateur36(Observateur):
    """L'observateur du pilotage, plus le mode du faux G1 (/g1_jumeau/mode, sujet d'essai)."""

    def __init__(self):
        super().__init__()
        from rclpy.qos import QoSProfile, ReliabilityPolicy
        from std_msgs.msg import Int32
        self.Int32 = Int32
        self.pub_mode = self.noeud.create_publisher(Int32, "/g1_jumeau/mode",
                                                    QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE))

    def mode(self, fsm):
        """Le mode du faux G1 changé d'un coup, comme à la télécommande."""
        for _ in range(3):
            self.pub_mode.publish(self.Int32(data=int(fsm)))
            time.sleep(0.05)

    def guides_depuis(self, t0):
        with self.verrou:
            return [e for tt, e in self.guides if tt >= t0]

    def codes_depuis(self, t0):
        with self.verrou:
            return [e for tt, e in self.evenements if tt >= t0]

    def ordres_non_nuls(self, t0, t1=math.inf):
        """7105 non nuls vus sur /api/sport/request entre t0 et t1 (pont ou pilotage)."""
        return [p for tt, api_id, p in self.requetes_sport(t0, t1)
                if api_id == 7105 and p and any(abs(v) > 1e-6 for v in p.get("velocity", [0, 0, 0]))]

    def salle_lointaine(self):
        x, y, _ = self.pose()
        return max(SALLES_DEMO, key=lambda s: math.dist((x, y), SALLES_DEMO[s]))


def attendre(condition, delai, message, pas=0.05):
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        try:
            v = condition()
        except (KeyError, IndexError, TypeError):
            v = None
        if v:
            return v
        time.sleep(pas)
    raise Echec(message)


def partie_simulation(a, lieu):
    simu = Simu()
    try:
        code, r = api(a, "POST", "/api/simulation/demarrer", {"lieu": lieu, "etage": "rdc", "mode": "simu"}, delai=90)
        verifier(code == 200, f"POST /api/simulation/demarrer (simu) : {code} {r}")
        attendre(lambda: simu.vitesse() is not None, 90, "la simulation ne publie pas /odom")
        dire("simulation lancée, /odom reçu")
        verrous_avant = len(simu.verrous)
        fin = time.monotonic() + 8.0
        vitesse = 0.0
        while time.monotonic() < fin:
            code, r = api(a, "POST", "/api/simulation/teleop", {"vx": 0.3, "vy": 0.0, "wz": 0.0}, delai=5)
            verifier(code == 200, f"POST /api/simulation/teleop : {code} {r}")
            time.sleep(0.2)
            vitesse = simu.vitesse() or 0.0
            if vitesse > 0.2:
                break
        verifier(vitesse > 0.2, f"la téléopération ne fait pas rouler le robot simulé ({vitesse:.2f} m/s)")
        t, duree, r = arret(a, "simu")
        verifier(r["mode"] == "simu" and r["verrou"] is False, f"ARRÊT en simulation : verrou ou mode faux : {r}")
        verifier(r["parties"]["verrou"]["ok"] is None, f"ARRÊT en simulation : un verrou ? {r['parties']['verrou']}")
        verifier(r["parties"]["teleop"]["ok"] is True, f"ARRÊT en simulation : téléopération {r['parties']['teleop']}")
        time.sleep(2.0)
        t_arret = simu.instant_arret(t)
        verifier(t_arret is not None, "simulation : le robot ne s'arrête pas après l'ARRÊT (/odom)")
        verifier(t_arret - t <= DELAI_ARRET_S, f"simulation : robot arrêté {t_arret - t:.2f} s après la demande (1 s au plus)")
        nouveaux = [v for tt, v in simu.verrous[verrous_avant:] if tt >= t - 0.1]
        verifier(not nouveaux, f"simulation : /pont/arret publié par l'ARRÊT ({nouveaux})")
        ok(f"simulation : téléopération à {vitesse:.2f} m/s, POST /api/arret {{mode: simu}} en {duree:.2f} s "
           f"({parties(r)}), robot arrêté {t_arret - t:.2f} s après (/odom), sans verrou ni /pont/arret")
    finally:
        simu.fermer()
        code, r = appel(a, "POST", "/api/simulation/arreter")
        CODES.append(("POST", "/api/simulation/arreter", code))
    attendre(lambda: not appel(a, "GET", "/api/simulation/etat")[1].get("en_cours"), 60,
             "la simulation ne s'arrête pas", pas=0.5)
    time.sleep(3.0)


# ---------------------------------------------------------------- répétition

def vitesse_verite(obs, depuis=0.4):
    t = time.monotonic()
    v = obs.vitesse_robot(t - depuis, t)
    return math.hypot(v[0], v[1]) if v else 0.0


def aller(a, cible="b204"):
    code, r = api(a, "POST", "/api/guide/aller", {"cible": cible}, delai=10)
    verifier(code == 200, f"POST /api/guide/aller {cible} : {code} {r}")


def attendre_roule(obs, delai=60.0, quoi="le robot"):
    return attendre(lambda: vitesse_verite(obs) > SEUIL_ROULE, delai,
                    f"{quoi} ne roule pas à plus de {SEUIL_ROULE} m/s en {delai:.0f} s (vérité /g1_jumeau/odom)", pas=0.1)


def arret_mesure(obs, t, quoi):
    time.sleep(1.8)
    t_arret = obs.instant_arret(t, seuil=SEUIL_ARRET)
    verifier(t_arret is not None, f"{quoi} : le robot ne s'arrête pas")
    verifier(t_arret - t <= DELAI_ARRET_S, f"{quoi} : robot arrêté {t_arret - t:.2f} s après la demande (1 s au plus)")
    return t_arret - t


def debloquer(a):
    code, r = api(a, "POST", "/api/arret/debloquer", {})
    verifier(code == 200 and r.get("verrou") is False, f"POST /api/arret/debloquer : {code} {r}")


def nav2_actif(obs):
    """bt_navigator actif (Nav2 prêt) ? Par son service de cycle de vie, comme au critère 19."""
    from lifecycle_msgs.srv import GetState
    if not hasattr(obs, "_client_nav2"):
        obs._client_nav2 = obs.noeud.create_client(GetState, "/bt_navigator/get_state")
    if not obs._client_nav2.wait_for_service(timeout_sec=0.5):
        return False
    futur = obs._client_nav2.call_async(GetState.Request())
    fin = time.monotonic() + 3.0
    while not futur.done() and time.monotonic() < fin:
        time.sleep(0.05)
    return bool(futur.done() and futur.result() and futur.result().current_state.label == "active")


def preparer_repetition(a, lieu, obs, ecoute):
    debut = time.monotonic()
    demarrer(a, lieu)
    attendre_relais(a, ecoute, lieu)
    verifier(obs.attendre_pret(30), "pas de vérité terrain ou de /pont/etat")
    code, r, duree = reperer(a, {"lieu": lieu, "etage": "rdc"})
    CODES.append(("POST", "/api/robot/reperer", code))
    verifier(code == 200 and r.get("repere"), f"POST /api/robot/reperer : {code} {r}")

    attendre(lambda: nav2_actif(obs), 120, "Nav2 n'est pas prêt 120 s après le repérage", pas=0.5)
    ok(f"répétition prête, robot repéré, Nav2 prêt en {time.monotonic() - debut:.0f} s")


def partie_guide(a, obs):
    aller(a)
    attendre_roule(obs, quoi="le robot (« Y aller » b204)")
    vitesse = vitesse_verite(obs)
    guide_avant = obs.guide().get("etat")
    t, duree, r = arret(a, "repetition")
    verifier(r["parties"]["guide"]["ok"] is True and r["parties"]["verrou"]["ok"] is True and r["verrou"] is True,
             f"ARRÊT en répétition : guide ou verrou pas faits : {r['parties']}")
    retard = arret_mesure(obs, t, "répétition, guide en route")
    etats_pont = [(tt, e.get("etat")) for tt, e in list(obs.etats) if tt >= t]
    verrouille = next((tt for tt, e in etats_pont if e == "arret_verrouille"), None)
    verifier(verrouille is not None and verrouille - t <= 1.0,
             f"/pont/etat ne passe pas à arret_verrouille en moins de 1 s (vus : {sorted({e for _, e in etats_pont})})")
    attendre(lambda: obs.guide().get("etat") != "en_route", 3.0, "/guide/etat reste en_route après l'ARRÊT")
    ok(f"guide en route ({guide_avant}, {vitesse:.2f} m/s) : POST /api/arret en {duree:.2f} s ({parties(r)}), "
       f"robot arrêté {retard:.2f} s après, /pont/etat arret_verrouille {verrouille - t:.2f} s après, "
       f"guide « {obs.guide().get('etat')} »")

    # verrou posé : un nouveau « Y aller » ne fait pas bouger le robot, et le guide le refuse (section 12.15 :
    # la demande n'est pas gardée pour le déblocage)
    t0 = time.monotonic()
    aller(a)
    time.sleep(5.0)
    bouge = obs.deplacement(t0)
    verifier(bouge < 0.05, f"verrou posé : le robot a bougé de {bouge:.3f} m en 5 s (moins de 5 cm)")
    g = obs.guide()
    verifier(g.get("etat") == "echec" and g.get("immobilise") == "verrou" and "Débloquer" in g.get("message", ""),
             f"verrou posé : le guide ne refuse pas « Y aller » ({g})")
    code, e = api(a, "GET", "/api/arret")
    verifier(code == 200 and e.get("verrou") is True, f"GET /api/arret : {code} {e} (verrou vrai attendu)")
    ok(f"verrou posé : « Y aller » refusé par le guide (« {g.get('message')} »), robot immobile "
       f"({bouge * 100:.1f} cm en 5 s), GET /api/arret {e}")

    # débloquer : rien ne repart ; puis « Y aller » : le robot repart
    t0 = time.monotonic()
    debloquer(a)
    time.sleep(5.0)
    bouge = obs.deplacement(t0)
    verifier(bouge < IMMOBILE_M and not obs.ordres_non_nuls(t0),
             f"après « Débloquer », le robot est reparti seul ({bouge:.2f} m en 5 s)")
    ok(f"« Débloquer » : rien ne repart ({bouge * 100:.1f} cm en 5 s, aucun 7105 non nul)")
    t0 = time.monotonic()
    aller(a)
    attendre(lambda: obs.deplacement(t0) >= 0.3, 40, "après « Débloquer », le robot ne repart pas (0,3 m au moins)", pas=0.2)
    ok(f"« Débloquer » puis « Y aller » : le robot repart ({obs.deplacement(t0):.2f} m)")


def bloquer_robot(a, verrou):
    """« Bloquer » ou « Débloquer » de Naviguer (POST /api/robot/arret {verrou})."""
    code, r = api(a, "POST", "/api/robot/arret", {"verrou": verrou})
    verifier(code == 200 and r.get("verrou") is verrou, f"POST /api/robot/arret {{verrou: {verrou}}} : {code} {r}")
    return r


def sans_reprise(obs, t_libre, duree, quoi):
    """Après la levée (t_libre) : aucun mouvement pendant duree, aucun 7105 non nul, guide au repos."""
    fin = t_libre + duree
    while time.monotonic() < fin:
        verifier(obs.deplacement(t_libre) < IMMOBILE_M,
                 f"{quoi} : LE ROBOT REPART SEUL ({obs.deplacement(t_libre):.2f} m, "
                 f"{time.monotonic() - t_libre:.1f} s après la levée)")
        time.sleep(0.2)
    bouge = obs.deplacement(t_libre)
    non_nuls = obs.ordres_non_nuls(t_libre)
    verifier(bouge < IMMOBILE_M and not non_nuls,
             f"{quoi} : le robot a bougé de {bouge:.3f} m ou a reçu {len(non_nuls)} ordres non nuls en {duree:.0f} s")
    # au repos : attente (ou echec d'un « Y aller » refusé, le temps que le pont voie la levée), jamais en mission
    etats = {e.get("etat") for e in obs.guides_depuis(t_libre)}
    verifier(not etats & set(ETATS_EN_MISSION), f"{quoi} : le guide est reparti en mission ({sorted(etats)})")
    g = obs.guide()
    verifier(g.get("etat") == "attente" and "immobilise" not in g, f"{quoi} : guide pas au repos à la fin ({g})")
    return bouge


def partie_deblocage(a, obs):
    """Section 12.15 : aucun déblocage ne relance l'ancien trajet ; un nouveau « Y aller » marche."""
    # « Bloquer » en route, puis « Débloquer » : aucun mouvement pendant 15 s
    cible = obs.salle_lointaine()
    aller(a, cible)
    attendre_roule(obs, quoi=f"le robot (« Y aller » {cible})")
    vitesse = vitesse_verite(obs)
    t = time.monotonic()
    r = bloquer_robot(a, True)
    verifier("trajet en cours est annulé" in (r.get("message") or ""), f"« Bloquer » : message {r.get('message')!r}")
    # relecture du 01/11/2026 : le champ guide compte les guides (le pont, qui écoute aussi /guide/stop, ne compte
    # plus), et /guide/stop doit vraiment partir (l'observateur du test l'écoute)
    verifier((r.get("guide") or 0) >= 1, f"« Bloquer » : aucun guide n'écoute /guide/stop ({r.get('guide')})")
    attendre(lambda: any(s >= t for s in list(obs.stops)), 2.0, "« Bloquer » n'a pas publié /guide/stop")
    retard = arret_mesure(obs, t, "« Bloquer » en route")
    attendre(lambda: obs.guide().get("etat") == "attente" and obs.guide().get("immobilise") == "verrou", 2.0,
             f"après « Bloquer », le guide ne dit pas qu'il est bloqué ({obs.guide()})")
    message = obs.guide().get("message", "")
    verifier(message.startswith("Robot bloqué") and "Débloquer" in message, f"message du guide bloqué : {message!r}")
    codes = [e.get("code") for e in obs.codes_depuis(t)]
    verifier("immobilise" in codes or "arret" in codes, f"aucun événement pour la voix après « Bloquer » ({codes})")
    time.sleep(5.0)
    pendant = {e.get("etat") for e in obs.guides_depuis(t + 1.0)}
    verifier(not pendant & set(ETATS_EN_MISSION + ("echec",)),
             f"pendant le blocage, le guide continue son trajet ({sorted(pendant)})")
    verifier(obs.guide().get("retour_dans_s") is None, "pendant le blocage, un retour automatique est prévu")
    t_libre = time.monotonic()
    r = bloquer_robot(a, False)
    verifier("nouveau « Y aller »" in (r.get("message") or ""), f"« Débloquer » : message {r.get('message')!r}")
    bouge = sans_reprise(obs, t_libre, SANS_REPRISE_S, "« Bloquer » puis « Débloquer »")
    g = obs.guide()
    verifier(g.get("etat") == "attente" and "immobilise" not in g
             and g.get("message") == "Robot débloqué : il attend un nouveau « Y aller ».", f"guide après « Débloquer » : {g}")
    ok(f"« Bloquer » en route ({cible}, {vitesse:.2f} m/s) : robot arrêté {retard:.2f} s après, guide « {message} » ; "
       f"« Débloquer » : {bouge * 100:.1f} cm en {SANS_REPRISE_S:.0f} s, aucun 7105 non nul, guide « {g.get('message')} »")

    # le verrou en ligne de commande (/pont/arret, transient_local) : pareil
    cible = obs.salle_lointaine()
    aller(a, cible)
    attendre_roule(obs, quoi=f"le robot (« Y aller » {cible}, verrou en ligne de commande)")
    t = time.monotonic()
    obs.pub_verrou.publish(obs.Bool(data=True))
    try:
        retard = arret_mesure(obs, t, "verrou en ligne de commande")
        attendre(lambda: obs.guide().get("immobilise") == "verrou", 2.0, "verrou en ligne de commande : le guide l'ignore")
        time.sleep(3.0)
    finally:
        t_libre = time.monotonic()
        obs.pub_verrou.publish(obs.Bool(data=False))
    bouge = sans_reprise(obs, t_libre, SANS_REPRISE_COURT_S, "verrou en ligne de commande levé")
    ok(f"verrou en ligne de commande en route ({cible}) : arrêté {retard:.2f} s après ; levé : {bouge * 100:.1f} cm "
       f"en {SANS_REPRISE_COURT_S:.0f} s")

    # le faux G1 assis en route (pas_en_marche), puis remis en marche : rien ne repart
    cible = obs.salle_lointaine()
    aller(a, cible)
    attendre_roule(obs, quoi=f"le robot (« Y aller » {cible}, faux G1 assis)")
    t = time.monotonic()
    obs.mode(3)
    try:
        attendre(lambda: obs.guide().get("immobilise") == "pas_en_marche", 3.0,
                 f"faux G1 assis : le guide n'annule pas le trajet ({obs.guide()})")
        time.sleep(3.0)
        code, r = api(a, "POST", "/api/guide/aller", {"cible": cible})
        verifier(code == 200 and r.get("immobilise") == "pas_en_marche", f"« Y aller » pendant pas_en_marche : {code} {r}")
        attendre(lambda: obs.guide().get("etat") == "echec", 3.0, "« Y aller » pendant pas_en_marche : pas refusé")
    finally:
        t_libre = time.monotonic()
        obs.mode(501)
    attendre(lambda: obs.dernier_etat().get("etat") == "pret", 5.0, "faux G1 remis en marche : le pont n'est pas prêt")
    bouge = sans_reprise(obs, t_libre, SANS_REPRISE_COURT_S, "faux G1 remis en marche")
    ok(f"faux G1 assis en route ({cible}) : trajet annulé, « Y aller » refusé ; remis en marche : "
       f"{bouge * 100:.1f} cm en {SANS_REPRISE_COURT_S:.0f} s, guide « {obs.guide().get('message')} »")

    # un nouveau « Y aller » marche
    cible = obs.salle_lointaine()
    t0 = time.monotonic()
    aller(a, cible)
    attendre(lambda: obs.deplacement(t0) >= 0.3, 40, f"nouveau « Y aller » {cible} : le robot ne repart pas", pas=0.2)
    ok(f"nouveau « Y aller » {cible} : le robot repart ({obs.deplacement(t0):.2f} m)")


# Relecture du 01/11/2026 : pendant le blocage, « Y aller » est grisé dans Naviguer (boutons du panneau et
# commande du ruban), et le titre de l'état du guide le dit
Y_ALLER_GRISE = """const b = Array.from(document.querySelectorAll('[data-role=salles] button'));
const r = document.querySelector('[data-commande="navigation.y-aller"]');
const t = document.querySelector('[data-role=guide]');
if (!b.length || !b.every((x) => x.disabled) || !r || !r.disabled || !t) return null;
return [b.length, b[0].title, r.title, t.textContent];"""
ECHAP = ("document.body.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true, "
         "cancelable: true}))")


def partie_navigateur(a, lieu, obs):
    """Robot en route : ARRÊT par le bouton de la page, puis Échap (outils_coque_e2e) ; pendant le blocage,
    « Y aller » grisé dans Naviguer, et le panneau le dit."""
    import outils_coque_e2e as N
    from atelier.tests import test_coque_communs as C
    attendre_roule(obs, quoi="le robot (avant le clic sur ARRÊT)")
    with N.Firefox() as nav:
        nav.taille(1366, 768)
        vu = C.parcours_arret(nav, a, "repetition", lieu=lieu, verrou=True)
        nav.onglet("naviguer")
        C.attendre_pret(nav)
        grise = nav.attendre(Y_ALLER_GRISE, delai=10.0, message="« Y aller » grisé pendant le blocage")
        verifier(grise[1].startswith("Robot bloqué") and grise[2].startswith("Robot bloqué")
                 and grise[3].startswith("Robot bloqué"), f"« Y aller » grisé, mais les textes : {grise}")
        vu.append(f"pendant le blocage : {grise[0]} boutons « Y aller » et la commande du ruban grisés "
                  f"(« {grise[1]} »), panneau « {grise[3]} »")
        erreurs = nav.js("return window.erreursAtelier || []")
    verifier(not erreurs, f"erreurs JavaScript dans la page : {erreurs[:4]}")
    for phrase in vu:
        ok("navigateur : " + phrase)
    time.sleep(1.0)
    verifier(vitesse_verite(obs) < SEUIL_ARRET, "navigateur : le robot roule encore après l'ARRÊT de la page")
    debloquer(a)


def salle_proche(obs, minimum=3.0):
    """La salle la plus proche du robot, à plus de minimum mètres (une arrivée rapide)."""
    x, y, _ = obs.pose()
    loin = {s: p for s, p in SALLES_DEMO.items() if math.dist((x, y), p) >= minimum and s != "accueil"}
    return min(loin, key=lambda s: math.dist((x, y), loin[s]))


def partie_echap_retour(a, lieu, obs):
    """Relecture du 01/11/2026 : arrivé, retour automatique prévu, un menu ouvert : Échap fermait seulement le
    menu et le robot partait seul 13 s plus tard. Échap doit envoyer l'ARRÊT ; rien ne part ensuite."""
    import outils_coque_e2e as N
    from atelier.tests import test_coque_communs as C
    cible = salle_proche(obs)
    with N.Firefox() as nav:
        nav.taille(1366, 768)
        C.ouvrir_espace(nav, a, "repetition", lieu=lieu)
        nav.onglet("naviguer")
        C.attendre_pret(nav)
        aller(a, cible)
        attendre(lambda: obs.guide().get("etat") == "arrive" and obs.guide().get("cible") == cible
                 and obs.guide().get("retour_dans_s") is not None, 150, f"Échap : pas d'arrivée à {cible} en 150 s")
        reste = obs.guide().get("retour_dans_s")
        nav.commande("navigation.y-aller")          # le menu « Y aller » du ruban, ouvert pour la salle suivante
        nav.attendre("return !!document.querySelector('.menu-ruban')", delai=5.0, message="menu « Y aller » ouvert")
        avant = len(C.requetes(nav, "POST", "/api/arret"))
        t = time.monotonic()
        nav.js(ECHAP)
        r = nav.attendre(C.DERNIER_ARRET, avant, "/api/arret", delai=3.0,
                         message="Échap, menu ouvert, retour prévu : pas d'ARRÊT")
        erreurs = nav.js("return window.erreursAtelier || []")
    verifier(not erreurs, f"erreurs JavaScript dans la page : {erreurs[:4]}")
    verifier((r.get("corps") or {}).get("mode") == "repetition", f"Échap : corps de l'ARRÊT {r.get('corps')}")
    attendre(lambda: obs.guide().get("retour_dans_s") is None, 2.0, "après Échap, le retour automatique est encore prévu")
    debloquer(a)
    t_libre = time.monotonic()
    bouge = sans_reprise(obs, t_libre, SANS_REPRISE_S, "Échap pendant l'attente du retour, puis « Débloquer »")
    verifier("retour" not in [e.get("code") for e in obs.codes_depuis(t)], "le retour automatique est parti après Échap")
    ok(f"Échap avec le menu « Y aller » ouvert, arrivé à {cible} (retour prévu dans {reste:.0f} s) : POST /api/arret ; "
       f"après « Débloquer », {bouge * 100:.1f} cm en {SANS_REPRISE_S:.0f} s, pas de retour")


class Joystick:
    """Le joystick de la page : /ws/pilotage de l'Atelier, un ordre toutes les 0,1 s, lâché à l'ARRÊT."""

    def __init__(self, a):
        from websockets.sync.client import connect
        self.ws = connect(a.replace("http", "ws", 1) + "/ws/pilotage", open_timeout=10)
        self.tenu = threading.Event()
        self.fin = threading.Event()
        self.refus = []
        self.fil = threading.Thread(target=self._envoyer, daemon=True)
        self.lecteur = threading.Thread(target=self._lire, daemon=True)
        self.lecteur.start()
        time.sleep(0.5)
        self.fil.start()

    def _lire(self):
        try:
            for m in self.ws:
                try:
                    d = json.loads(m)
                except ValueError:
                    continue
                if d.get("type") == "refus":
                    self.refus.append((time.monotonic(), d))
        except Exception:       # noqa: BLE001 : fermée
            pass

    def _envoyer(self):
        while not self.fin.is_set():
            if self.tenu.is_set():
                try:
                    self.ws.send(json.dumps({"vx": 0.3, "vy": 0.0, "wz": 0.0}))
                except Exception:       # noqa: BLE001 : fermée
                    return
            time.sleep(0.1)

    def lacher(self):
        """Comme la page à l'ARRÊT : plus d'ordre, et « lâché »."""
        self.tenu.clear()
        try:
            self.ws.send(json.dumps({"lacher": True}))
        except Exception:       # noqa: BLE001
            pass

    def fermer(self):
        self.fin.set()
        self.tenu.clear()
        try:
            self.ws.close()
        except Exception:       # noqa: BLE001
            pass


def partie_pilotage(a, obs):
    # arrêter le guide (l'ARRÊT de la partie précédente) et débloquer avant de piloter
    t, _, r = arret(a, "repetition")
    time.sleep(1.0)
    debloquer(a)
    code, r = api(a, "POST", "/api/pilotage/demarrer", {}, delai=60)
    verifier(code == 200, f"POST /api/pilotage/demarrer : {code} {r}")

    def pret():
        code, e = appel(a, "GET", "/api/pilotage/etat")
        return code == 200 and e.get("robot_repond")
    attendre(pret, 30, "le nœud pilotage ne répond pas (GET /api/pilotage/etat)", pas=0.3)
    code, r = api(a, "POST", "/api/pilotage/maitre", {"maitre": "pilotage", "forcer": True}, delai=20)
    verifier(code == 200 and r.get("maitre") == "pilotage", f"prendre la main : {code} {r}")
    obs.attendre(lambda: obs.maitre() == "pilotage", 5, "/mouvement/maitre « pilotage » pas reçu")
    manette = Joystick(a)
    try:
        # section 12.15 : « Bloquer » arrête aussi le joystick tenu (le pilotage parle directement au robot) ;
        # débloqué, le manche toujours tenu ne relance pas le robot : il faut le lâcher, puis le reprendre
        manette.tenu.set()
        attendre_roule(obs, delai=10.0, quoi="le robot au joystick (vx 0,3), avant « Bloquer »")
        t = time.monotonic()
        bloquer_robot(a, True)
        retard = arret_mesure(obs, t, "« Bloquer » pendant le joystick")
        time.sleep(1.0)
        refus_bloque = [d for tt, d in manette.refus if tt >= t]
        verifier(refus_bloque, "joystick tenu pendant le blocage : aucun refus")
        t_libre = time.monotonic()
        bloquer_robot(a, False)
        time.sleep(3.0)
        bouge = obs.deplacement(t_libre)
        verifier(bouge < IMMOBILE_M, f"« Débloquer », joystick toujours tenu : le robot repart seul ({bouge:.2f} m)")
        manette.lacher()
        time.sleep(0.5)
        t_repris = time.monotonic()
        manette.tenu.set()
        attendre_roule(obs, delai=10.0, quoi="le robot au joystick repris après « Débloquer »")
        ok(f"joystick tenu, « Bloquer » : arrêté {retard:.2f} s après, joystick refusé "
           f"(« {str(refus_bloque[0].get('detail', refus_bloque[0]))[:80]} ») ; « Débloquer » manche tenu : "
           f"{bouge * 100:.1f} cm en 3 s ; lâché puis repris : il repart")
        vitesse = vitesse_verite(obs)
        # plus d'ordre, sans « lâché » : le StopMove qui suit vient de l'ARRÊT (l'homme mort du nœud
        # n'agirait qu'après 0,5 s)
        manette.tenu.clear()
        t, duree, r = arret(a, "repetition")
    finally:
        manette.fermer()
    verifier(r["parties"]["pilotage"]["ok"] is True, f"ARRÊT : le nœud pilotage n'a pas répondu : {r['parties']['pilotage']}")
    time.sleep(1.5)
    stops = [(tt, p) for tt, api_id, p in obs.requetes_sport(t, t + 1.0) if api_id == 7105 and p == STOP_MOVE]
    verifier(stops, "aucun StopMove (7105 [0, 0, 0] d'une seconde) reçu par le faux G1 dans la seconde")
    verifier(stops[0][0] - t < 0.45, f"le premier StopMove arrive {stops[0][0] - t:.2f} s après l'ARRÊT : celui de "
             "l'homme mort, pas celui de l'ARRÊT")
    with obs.verrou:
        activites = [e.get("activite") for tt, e in obs.etats_pilotage if t <= tt <= t + 1.5]
    retard = arret_mesure(obs, t, "pilotage au joystick")
    # après l'ARRÊT, le nœud ignore le joystick jusqu'à ce qu'il soit lâché (un ordre parti juste avant
    # l'ARRÊT peut être refusé) : seuls comptent les refus d'avant
    avant = [d for tt, d in manette.refus if t_repris <= tt < t]
    verifier(not avant, f"refus du joystick avant l'ARRÊT : {avant[:2]}")
    ok(f"pilotage au joystick ({vitesse:.2f} m/s) : POST /api/arret en {duree:.2f} s ({parties(r)}), StopMove "
       f"{stops[0][0] - t:.2f} s après, robot arrêté {retard:.2f} s après ; activités du nœud : "
       f"{', '.join(sorted({str(x) for x in activites})) or 'aucun /pilotage/etat'}")
    debloquer(a)
    code, r = api(a, "POST", "/api/pilotage/maitre", {"maitre": "guide"})
    verifier(code == 200, f"rendre la main : {code} {r}")

    # nœud pilotage arrêté : l'ARRÊT répond quand même, et dit que le pilotage n'a pas répondu
    code, r = api(a, "POST", "/api/pilotage/arreter", {}, delai=30)
    verifier(code == 200, f"POST /api/pilotage/arreter : {code} {r}")
    attendre(lambda: appel(a, "GET", "/api/pilotage/etat")[1].get("robot_repond") is not True, 15,
             "le nœud pilotage répond encore après son arrêt", pas=0.3)
    t0 = time.monotonic()
    t, duree, r = arret(a, "repetition")
    pilotage = r["parties"]["pilotage"]
    verifier(pilotage["ok"] is False and pilotage.get("detail"), f"nœud pilotage arrêté : partie pilotage {pilotage}")
    verifier(r["parties"]["guide"]["ok"] is True and r["parties"]["verrou"]["ok"] is True,
             f"nœud pilotage arrêté : le reste n'est pas arrêté : {r['parties']}")
    time.sleep(1.0)
    verifier(obs.deplacement(t0) < 0.05, "nœud pilotage arrêté : le robot bouge")
    ok(f"nœud pilotage arrêté : POST /api/arret en {duree:.2f} s, pilotage faux « {pilotage['detail']} », "
       f"guide et verrou faits")
    debloquer(a)


def critere_36(args):
    a = args.api
    partie_simulation(a, args.lieu)
    obs = Observateur36()
    ecoute = Ecoute()
    try:
        preparer_repetition(a, args.lieu, obs, ecoute)
        partie_guide(a, obs)
        partie_deblocage(a, obs)
        partie_navigateur(a, args.lieu, obs)
        partie_echap_retour(a, args.lieu, obs)
        partie_pilotage(a, obs)
        verifier(not obs.non_conformes, f"/pont/etat non conforme : {obs.non_conformes[:2]}")
    finally:
        obs.fermer()
        ecoute.fermer()
    cinq_cents = [c for c in CODES if c[2] == 500]
    verifier(not cinq_cents, f"erreurs 500 : {cinq_cents}")
    ok(f"{len(CODES)} appels à l'API, jamais d'erreur 500")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="critere_36_outils.py", description=__doc__.split("\n")[0])
    sous = p.add_subparsers(dest="action", required=True)
    s = sous.add_parser("critere-36")
    s.add_argument("--api", required=True)
    s.add_argument("--lieu", required=True)
    args = p.parse_args(argv)
    try:
        return critere_36(args)
    except Echec as e:
        print(f"[critère 36] ÉCHEC : {e}", flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
