#!/usr/bin/env python3
"""Outils des critères 22, 26 et 27 : le comportement du guide (sections 7 et 11.4 du plan).

  outils_guide_e2e.py preparer --lieu ID [--guide JSON] [--scene ID]
      réglages du guide (section guide de lieu.yaml) et scène des passants, sur une COPIE du demo ;
  outils_guide_e2e.py retour --api URL --lieu ID              (critère 22, simulation)
      b204, puis retour seul au point principal (0,3 m, 10°) ; puis b204 sans retour ;
  outils_guide_e2e.py accompagnement --api URL --lieu ID      (critère 26, simulation + scène)
      le faux visiteur suit, traîne (ralenti, attente), revient (reprise, arrivée), puis part
      (abandon, retour) ;
  outils_guide_e2e.py perdu --api URL --lieu ID               (critère 27, répétition)
      relocalisation coupée en route : perdu, puis reprise (A) ou échec sans retour (B) ;
  outils_guide_e2e.py restes --lieux DOSSIER [--sauf PID...]
      code 1 si un processus lancé avec ces lieux tourne encore.

Vérité terrain : /odom en simulation, /g1_jumeau/odom en répétition. Tous les /guide/etat et
/guide/evenement reçus sont vérifiés par leur schéma (atelier.lieu.valider_message). Code de
sortie : 0 réussi, 1 échoué (le message dit pourquoi), 77 une pièce d'un autre agent manque.
"""
import argparse
import json
import math
import os
from pathlib import Path
import sys
import threading
import time
import urllib.error
import urllib.request

PREFIXE = 'guide'
TOLERANCE_M = 0.3
TOLERANCE_RAD = math.radians(10)


class Echec(Exception):
    pass


class EnAttente(Exception):
    """Une pièce d'un autre agent manque (code 77)."""


def verifier(condition, message):
    if not condition:
        raise Echec(message)


def dire(texte):
    print(f'[{PREFIXE}] {texte}', flush=True)


def ecart(a, b):
    """(distance, écart d'angle) entre deux poses (x, y, theta)."""
    return (math.hypot(a[0] - b[0], a[1] - b[1]),
            abs((a[2] - b[2] + math.pi) % (2 * math.pi) - math.pi))


def appel(api, methode, chemin, corps=None, delai=60):
    """(code HTTP, JSON) d'un appel à l'API de l'Atelier."""
    donnees = None if corps is None else json.dumps(corps).encode()
    r = urllib.request.Request(api + chemin, data=donnees, method=methode,
                               headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(r, timeout=delai) as reponse:
            return reponse.status, json.loads(reponse.read() or b'null')
    except urllib.error.HTTPError as e:
        texte = e.read().decode('utf-8', 'replace')
        try:
            return e.code, json.loads(texte)
        except ValueError:
            return e.code, {'detail': texte}


def pose_salle(lieu, salle):
    from atelier import chemin_lieu
    from atelier.lieu import charger_salles
    s = [s for s in charger_salles(chemin_lieu(lieu)) if s.id == salle]
    verifier(s, f'salle {salle} absente du lieu {lieu}')
    return (s[0].pose.x, s[0].pose.y, s[0].pose.theta), s[0]


def principal(lieu):
    from atelier import chemin_lieu
    from atelier.lieu.principal import point_principal
    s = point_principal(chemin_lieu(lieu))
    verifier(s is not None, f'le lieu {lieu} n\'a pas de point principal')
    return (s.pose.x, s.pose.y, s.pose.theta), s


# ---------------------------------------------------------------- écoute ROS 2

class Observateur:
    """Écoute le guide, ses événements, la vérité terrain, /speed_limit, les personnes, les piétons."""

    def __init__(self, verite='/odom'):
        import rclpy
        from nav_msgs.msg import Odometry
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.qos import qos_profile_sensor_data
        from std_msgs.msg import String
        from atelier.lieu import valider_message
        self.rclpy, self.String, self.valider = rclpy, String, valider_message
        self.contexte = rclpy.Context()
        rclpy.init(context=self.contexte)
        self.noeud = rclpy.create_node('e2e_guide_comportement', context=self.contexte)
        self.verrou = threading.Lock()
        self.etats, self.evenements, self.verites, self.limites = [], [], [], []
        self.non_conformes = []
        self.derniers = {}
        n = self.noeud
        n.create_subscription(String, '/guide/etat', self._etat, 50)
        n.create_subscription(String, '/guide/evenement', self._evenement, 50)
        n.create_subscription(Odometry, verite, self._verite, qos_profile_sensor_data)
        for sujet in ('/personnes/lidar', '/pietons/etat', '/faux_visiteur/etat', '/reperage/etat'):
            n.create_subscription(String, sujet, self._json(sujet), 10)
        try:
            from nav2_msgs.msg import SpeedLimit
            n.create_subscription(SpeedLimit, '/speed_limit', self._limite, 10)
        except ImportError:
            pass
        self.pub_panne = n.create_publisher(String, '/faux_slam/panne', 10)
        self.pub_mode = n.create_publisher(String, '/faux_visiteur/mode', 10)
        self.executeur = SingleThreadedExecutor(context=self.contexte)
        self.executeur.add_node(n)
        self._fin = threading.Event()
        self._fil = threading.Thread(target=self._tourner, daemon=True)
        self._fil.start()

    def _tourner(self):
        while not self._fin.is_set():
            try:
                self.executeur.spin_once(timeout_sec=0.05)
            except Exception:      # noqa: BLE001 : arrêt
                break

    def _lire(self, texte, schema):
        try:
            d = json.loads(texte)
        except ValueError:
            self.non_conformes.append(f'{schema} : JSON illisible : {texte[:100]}')
            return None
        erreurs = self.valider(schema, d)
        if erreurs:
            self.non_conformes.append(f'{schema} : {"; ".join(erreurs)} ({texte[:200]})')
        return d

    def _etat(self, m):
        d = self._lire(m.data, 'etat_guide')
        if d is not None:
            with self.verrou:
                self.etats.append((time.monotonic(), d))

    def _evenement(self, m):
        d = self._lire(m.data, 'evenement_guide')
        if d is not None:
            with self.verrou:
                self.evenements.append((time.monotonic(), d))
            dire(f'   événement {d.get("code")} : « {d.get("texte")} »')

    def _verite(self, m):
        from atelier.lieu import quaternion_vers_cap
        p = m.pose.pose
        with self.verrou:
            self.verites.append((time.monotonic(), p.position.x, p.position.y,
                                 quaternion_vers_cap(p.orientation)))
            del self.verites[:-40000]

    def _limite(self, m):
        with self.verrou:
            self.limites.append((time.monotonic(), bool(m.percentage), float(m.speed_limit)))

    def _json(self, sujet):
        def recevoir(m):
            try:
                d = json.loads(m.data)
            except ValueError:
                return
            with self.verrou:
                self.derniers[sujet] = (time.monotonic(), d)
        return recevoir

    # ------------------------------------------------------------ lectures

    def dernier(self, sujet, frais_s=2.0):
        with self.verrou:
            recu = self.derniers.get(sujet)
        if recu is None or time.monotonic() - recu[0] > frais_s:
            return None
        return recu[1]

    def etat(self):
        with self.verrou:
            return self.etats[-1][1] if self.etats else None

    def etats_depuis(self, t0):
        with self.verrou:
            return [(t, e) for t, e in self.etats if t >= t0]

    def evenements_depuis(self, t0):
        with self.verrou:
            return [(t, e) for t, e in self.evenements if t >= t0]

    def codes_depuis(self, t0):
        return [e['code'] for t, e in self.evenements_depuis(t0)]

    def pose(self):
        with self.verrou:
            return self.verites[-1][1:] if self.verites else None

    def poses_entre(self, t0, t1):
        with self.verrou:
            return [v for v in self.verites if t0 <= v[0] <= t1]

    def deplacement(self, t0, t1):
        """Plus grand écart à la position de t0, entre t0 et t1 (m)."""
        poses = self.poses_entre(t0, t1)
        if not poses:
            return 0.0
        x0, y0 = poses[0][1], poses[0][2]
        return max(math.hypot(x - x0, y - y0) for _, x, y, _ in poses)

    def vitesse(self, t0, t1):
        """Vitesse moyenne (chemin parcouru / durée), entre t0 et t1 (m/s)."""
        poses = self.poses_entre(t0, t1)
        if len(poses) < 2:
            return 0.0
        chemin = sum(math.hypot(b[1] - a[1], b[2] - a[2]) for a, b in zip(poses, poses[1:]))
        return chemin / max(1e-6, poses[-1][0] - poses[0][0])

    def attendre(self, condition, delai, pas=0.1):
        fin = time.monotonic() + delai
        while time.monotonic() < fin:
            try:
                if condition():
                    return True
            except Exception:      # noqa: BLE001 : pas encore de données
                pass
            time.sleep(pas)
        return False

    def attendre_etat(self, etats, depuis, delai, cible=None, sauf=('echec',)):
        """Instant et état du premier /guide/etat dans etats après depuis ; Echec si sauf vient avant."""
        etats = (etats,) if isinstance(etats, str) else tuple(etats)
        fin = time.monotonic() + delai
        while time.monotonic() < fin:
            for t, e in self.etats_depuis(depuis):
                if e['etat'] in etats and (cible is None or e.get('cible') == cible):
                    return t, e
                if e['etat'] in sauf and e['etat'] not in etats:
                    raise Echec(f'le guide est passé à {e["etat"]} : {e.get("message", e)}')
            time.sleep(0.1)
        vus = self.suite_depuis(depuis)
        raise Echec(f'pas d\'état {"/".join(etats)} en {delai:.0f} s (états vus : {" → ".join(vus)})')

    def attendre_evenement(self, code, depuis, delai):
        fin = time.monotonic() + delai
        while time.monotonic() < fin:
            for t, e in self.evenements_depuis(depuis):
                if e['code'] == code:
                    return t, e
            time.sleep(0.1)
        raise Echec(f'pas d\'événement {code} en {delai:.0f} s (reçus : '
                    f'{", ".join(self.codes_depuis(depuis)) or "aucun"})')

    def suite_depuis(self, t0):
        vus = []
        for _, e in self.etats_depuis(t0):
            if not vus or vus[-1] != e['etat']:
                vus.append(e['etat'])
        return vus

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

    def panne(self, texte):
        for _ in range(3):
            self.pub_panne.publish(self.String(data=texte))
            time.sleep(0.1)

    def mode_visiteur(self, mode):
        for _ in range(3):
            self.pub_mode.publish(self.String(data=mode))
            time.sleep(0.1)

    def fermer(self):
        self._fin.set()
        self._fil.join(timeout=3)
        self.executeur.shutdown()
        self.noeud.destroy_node()
        self.rclpy.try_shutdown(context=self.contexte)


# ---------------------------------------------------------------- étapes communes

def demarrer(api, lieu, mode='simu'):
    code, r = appel(api, 'POST', '/api/simulation/demarrer', {'lieu': lieu, 'etage': 'rdc', 'mode': mode})
    verifier(code == 200, f'POST /api/simulation/demarrer ({mode}) : {code} {r}')
    dire(f'{mode} lancée : {", ".join(sorted(r["processus"]))}')


def attendre_nav2(obs, delai=180):
    debut = time.monotonic()
    verifier(obs.attendre(lambda: obs.etat() is not None, 120), 'le guide ne publie pas /guide/etat')
    verifier(obs.attendre(lambda: obs.pose() is not None, 60), 'pas de vérité terrain')
    verifier(obs.attendre(obs.nav2_actif, delai, pas=0.5), f'Nav2 n\'est pas actif en {delai} s')
    dire(f'Nav2 actif ({time.monotonic() - debut:.0f} s)')


def aller(api, corps):
    code, r = appel(api, 'POST', '/api/guide/aller', corps)
    verifier(code == 200 and r.get('ecoute', 0) > 0, f'POST /api/guide/aller {corps} : {code} {r}')
    return time.monotonic()


def verifier_arrivee(obs, pose_voulue, quoi, angle=False):
    time.sleep(1.5)
    pose = obs.pose()
    d, a = ecart(pose, pose_voulue)
    dire(f'{quoi} : robot à {d:.3f} m et {math.degrees(a):.1f}° (vérité terrain)')
    verifier(d < TOLERANCE_M, f'{quoi} : robot à {d:.3f} m (au plus {TOLERANCE_M} m)')
    if angle:
        verifier(a <= TOLERANCE_RAD, f'{quoi} : robot tourné de {math.degrees(a):.1f}° par rapport à la '
                                     'flèche (au plus 10°)')
    return d, a


def verifier_textes(obs, depuis, lieu):
    """Chaque événement : texte attendu (par défaut, ou phrase d'arrivée de la salle), en français."""
    from atelier import chemin_lieu
    from atelier.lieu import charger_salles
    from atelier.lieu.comportement import texte_evenement
    salles = {s.id: s for s in charger_salles(chemin_lieu(lieu))}
    for _, e in obs.evenements_depuis(depuis):
        salle = salles.get(e.get('salle'))
        nom = salle.nom if salle else None
        attendus = {texte_evenement(e['code'], nom)}
        if e['code'] == 'arrivee' and salle and salle.phrase_arrivee:
            attendus.add(salle.phrase_arrivee)
        verifier(e['texte'] in attendus, f'événement {e["code"]} : texte inattendu « {e["texte"]} »')
    verifier(not obs.non_conformes, f'messages non conformes : {obs.non_conformes[:3]}')


def sous_suite(codes, attendus):
    reste = iter(codes)
    return all(any(c == a for c in reste) for a in attendus)


# ---------------------------------------------------------------- préparation de la copie

def preparer(args):
    from atelier import chemin_lieu
    from atelier.lieu import charger_fiche, enregistrer_fiche
    dossier = chemin_lieu(args.lieu)
    reference = Path(__file__).resolve().parent.parent / 'lieux' / 'demo'
    verifier(dossier.resolve() != reference.resolve(), 'jamais dans lieux/demo : travaillez sur une copie')
    if args.scene:
        from atelier.monde import scene as scenes
        try:
            scenes.appliquer_scene(dossier, args.scene)
            dire(f'scène « {args.scene} » appliquée par atelier.monde.scene')
        except NotImplementedError:
            _appliquer_scene_ici(dossier, scenes.charger_scene(args.scene)
                                 if hasattr(scenes, 'charger_scene') else None, args.scene)
    if args.guide:
        fiche = charger_fiche(dossier)
        fiche.guide = dict(fiche.guide or {}, **json.loads(args.guide))
        enregistrer_fiche(fiche, dossier)
    dire(f'réglages du guide de la copie : {charger_fiche(dossier).guide}')
    return 0


def _appliquer_scene_ici(dossier, scene, ident):
    """Repli si atelier.monde.scene n'est pas encore écrit : piétons et réglages du guide."""
    import yaml
    from atelier.lieu import Pieton, charger_fiche, charger_monde, enregistrer_fiche, enregistrer_monde
    if not isinstance(scene, dict):
        racine = Path(__file__).resolve().parent.parent
        scene = yaml.safe_load((racine / 'atelier' / 'monde' / 'scenes' / f'{ident}.scene.yaml')
                               .read_text(encoding='utf-8'))
    monde = charger_monde(dossier, scene['etage'])
    nouveaux = [Pieton.depuis_dict(p) for p in scene['pietons']]
    monde.pietons = (monde.pietons if scene.get('ajouter') else []) + nouveaux
    enregistrer_monde(dossier, scene['etage'], monde)
    if scene.get('reglages_guide'):
        fiche = charger_fiche(dossier)
        fiche.guide = dict(fiche.guide or {}, **scene['reglages_guide'])
        enregistrer_fiche(fiche, dossier)
    dire(f'scène « {ident} » appliquée (repli de l\'outil)')


# ---------------------------------------------------------------- critère 22 : retour

def retour(args):
    obs = Observateur('/odom')
    try:
        demarrer(args.api, args.lieu)
        attendre_nav2(obs)
        pose_b204, _ = pose_salle(args.lieu, 'b204')
        pose_p, salle_p = principal(args.lieu)
        # 1. la visite
        t0 = aller(args.api, {'cible': 'b204'})
        t_arrive, _ = obs.attendre_etat('arrive', t0, 180, cible='b204')
        dire(f'arrivé à b204 en {t_arrive - t0:.0f} s')
        verifier_arrivee(obs, pose_b204, 'arrivée à b204')
        # 2. le retour, seul
        t_retour, e = obs.attendre_etat('retour', t_arrive, 60)
        verifier(e['cible'] == salle_p.id and e.get('mission') == 'retour',
                 f'retour vers {e["cible"]} (mission {e.get("mission")}), et non vers le principal')
        dire(f'retour vers « {salle_p.id} » {t_retour - t_arrive:.1f} s après l\'arrivée')
        t_attente, _ = obs.attendre_etat('attente', t_retour, 120 - (t_retour - t_arrive))
        dire(f'attente au point principal {t_attente - t_arrive:.0f} s après l\'arrivée à b204 '
             f'(états : {" → ".join(obs.suite_depuis(t0))})')
        verifier(t_attente - t_arrive < 120, 'retour et attente en plus de 120 s')
        verifier_arrivee(obs, pose_p, 'retour au point principal', angle=True)
        obs.attendre(lambda: 'retour_arrive' in obs.codes_depuis(t0), 3)
        codes = obs.codes_depuis(t0)
        verifier(sous_suite(codes, ['arrivee', 'retour', 'retour_arrive']),
                 f'événements attendus : arrivee, retour, retour_arrive ; reçus : {codes}')
        verifier_textes(obs, t0, args.lieu)
        dire(f'événements : {", ".join(codes)}, en français et conformes')
        # 3. sans retour
        t1 = aller(args.api, {'cible': 'b204', 'retour': False})
        t_arrive2, _ = obs.attendre_etat('arrive', t1, 180, cible='b204')
        dire(f'arrivé à b204 (« retour »: false) en {t_arrive2 - t1:.0f} s')
        time.sleep(20.5)
        d = obs.deplacement(t_arrive2, t_arrive2 + 20)
        vus = obs.suite_depuis(t_arrive2)
        dire(f'20 s après l\'arrivée : {d * 100:.1f} cm parcourus, états {" → ".join(vus)}')
        verifier(d < 0.1, f'le robot a bougé de {d:.3f} m après l\'arrivée (au plus 0,1 m)')
        verifier('retour' not in vus, 'retour automatique malgré « retour »: false')
        verifier(not obs.non_conformes, f'messages non conformes : {obs.non_conformes[:3]}')
        dire(f'{len(obs.etats)} /guide/etat et {len(obs.evenements)} /guide/evenement, tous conformes')
        return 0
    finally:
        obs.fermer()


# ---------------------------------------------------------------- critère 26 : accompagnement

def _visiteur_derriere(obs):
    p = obs.dernier('/personnes/lidar')
    return p is not None and any(q['distance_m'] < 2.5 for q in p['personnes'])


def accompagnement(args):
    obs = Observateur('/odom')
    try:
        demarrer(args.api, args.lieu)
        if not obs.attendre(lambda: any(p.get('id') == 'visiteur' for p in
                                        (obs.dernier('/pietons/etat') or {}).get('pietons', [])), 90):
            raise EnAttente('le nœud pietons de g1_sim (agent Passants) ne publie pas le visiteur sur '
                            '/pietons/etat')
        attendre_nav2(obs)
        verifier(obs.attendre(lambda: obs.dernier('/faux_visiteur/etat') is not None, 30),
                 'le faux visiteur ne publie pas /faux_visiteur/etat')
        verifier(obs.attendre(lambda: _visiteur_derriere(obs), 30),
                 f'le détecteur de personnes ne voit pas le visiteur derrière le robot '
                 f'({obs.dernier("/personnes/lidar")})')
        pose_b204, _ = pose_salle(args.lieu, 'b204')
        pose_p, _ = principal(args.lieu)
        obs.mode_visiteur('suivre')
        # ---- essai 1 : suivre, traîner, revenir
        t0 = aller(args.api, {'cible': 'b204', 'accompagner': True, 'retour': True})
        t_dep, e = obs.attendre_evenement('depart', t0, 6)
        verifier('seul' not in obs.codes_depuis(t0), 'événement « seul » : le visiteur n\'a pas été vu')
        dire('départ accompagné (événement depart)')
        # suivre : vitesse normale dans le couloir nord, sans ralenti
        verifier(obs.attendre(lambda: obs.pose()[0] > 5.0 and obs.pose()[1] > 12.0, 90),
                 'le robot n\'atteint pas le couloir nord')
        t_mesure = time.monotonic()
        time.sleep(5.0)
        v_suivre = obs.vitesse(t_mesure, t_mesure + 5.0)
        limites = [l for l in obs.limites if l[0] >= t0 and l[2] < 99.9]
        dire(f'visiteur qui suit : robot à {v_suivre:.2f} m/s, distance '
             f'{obs.dernier("/faux_visiteur/etat")["distance_m"]} m, sans limite de vitesse')
        verifier(not limites and 'ralentir' not in obs.codes_depuis(t0),
                 f'le robot ralentit alors que le visiteur suit : {limites[:2]}')
        verifier(v_suivre > 0.15, f'le robot n\'avance pas en suivre ({v_suivre:.2f} m/s)')
        # traîner : ralenti, puis attente
        t_tr = time.monotonic()
        obs.mode_visiteur('trainer')
        t_lent, _ = obs.attendre_evenement('ralentir', t_tr, 30)
        verifier(obs.attendre(lambda: any(l[0] >= t_tr and l[1] and l[2] < 99 for l in obs.limites), 3),
                 'pas de /speed_limit en pourcentage après « ralentir »')
        limite = next(l for l in obs.limites if l[0] >= t_tr and l[1] and l[2] < 99)
        # La vitesse d'avant : celle des 2 s qui précèdent le ralenti. Pendant le suivi à 1,2 m, le
        # Collision Monitor (cercle « ralentir » de 1 m) freine déjà le robot ; quand le visiteur
        # traîne, il le relâche, et le robot accélère avant que le guide ne ralentisse.
        v_avant = obs.vitesse(t_lent - 2.0, t_lent)
        time.sleep(3.0)
        v_trainer = obs.vitesse(t_lent + 1.5, t_lent + 3.0)
        dire(f'visiteur qui traîne : /speed_limit {limite[2]:.0f} %, robot à {v_trainer:.2f} m/s, soit '
             f'{100 * v_trainer / max(v_avant, 1e-6):.0f} % des {v_avant:.2f} m/s d\'avant le ralenti '
             f'(pendant le suivi : {v_suivre:.2f} m/s)')
        verifier(v_trainer <= 0.6 * v_avant, f'robot à {v_trainer:.2f} m/s en ralenti, plus de 60 % de '
                                             f'{v_avant:.2f} m/s')
        t_att, _ = obs.attendre_etat('attente_visiteur', t_tr, 60)
        distance = obs.dernier('/faux_visiteur/etat')['distance_m']
        time.sleep(2.0)
        v_arret = obs.vitesse(t_att + 1.0, t_att + 2.0)
        dire(f'attente_visiteur (visiteur à {distance} m) : robot à {v_arret * 100:.1f} cm/s')
        verifier(v_arret < 0.02, f'robot pas arrêté pendant l\'attente du visiteur ({v_arret:.3f} m/s)')
        verifier(distance > 3.0, f'attente_visiteur alors que le visiteur est à {distance} m')
        # revenir : reprise, arrivée
        t_rev = time.monotonic()
        obs.mode_visiteur('suivre')
        obs.attendre_evenement('visiteur_retrouve', t_rev, 40)
        obs.attendre_etat(('en_route', 'detour'), t_rev, 10)
        dire('visiteur revenu : visiteur_retrouve, reprise')
        t_arr, _ = obs.attendre_etat('arrive', t_rev, 180, cible='b204')
        verifier_arrivee(obs, pose_b204, 'arrivée à b204 avec le visiteur')
        t_fin, _ = obs.attendre_etat('attente', t_arr, 150)
        verifier_arrivee(obs, pose_p, 'retour au point principal', angle=True)
        # ---- essai 2 : le visiteur part
        verifier(obs.attendre(lambda: _visiteur_derriere(obs), 60),
                 'le visiteur n\'est pas revenu près du robot avant le second essai')
        t2 = aller(args.api, {'cible': 'b204', 'accompagner': True})
        obs.attendre_evenement('depart', t2, 6)
        depart = obs.pose()
        verifier(obs.attendre(lambda: math.dist(obs.pose()[:2], depart[:2]) > 1.5, 60),
                 'le robot ne part pas (second essai)')
        t_part = time.monotonic()
        obs.mode_visiteur('partir')
        t_att2, _ = obs.attendre_etat('attente_visiteur', t_part, 40)
        t_perdu, _ = obs.attendre_evenement('visiteur_perdu', t_att2, 30)
        dire(f'le visiteur part : attente_visiteur, puis visiteur_perdu {t_perdu - t_att2:.1f} s après')
        verifier(abs((t_perdu - t_att2) - 10.0) <= 2.0,
                 f'visiteur_perdu {t_perdu - t_att2:.1f} s après attente_visiteur (10 ± 2 s attendus)')
        t_ret, _ = obs.attendre_etat('retour', t_perdu, 30, sauf=())
        t_fin2, _ = obs.attendre_etat('attente', t_ret, 150)
        verifier_arrivee(obs, pose_p, 'retour au point principal après l\'abandon', angle=True)
        codes = obs.codes_depuis(t0)
        verifier(sous_suite(codes, ['depart', 'ralentir', 'attente_visiteur', 'visiteur_retrouve',
                                    'arrivee', 'retour', 'retour_arrive', 'depart', 'attente_visiteur',
                                    'visiteur_perdu', 'retour', 'retour_arrive']),
                 f'suite d\'événements inattendue : {codes}')
        verifier_textes(obs, t0, args.lieu)
        dire(f'événements : {", ".join(codes)} ; tous en français et conformes')
        return 0
    finally:
        obs.mode_visiteur('arreter')
        obs.fermer()


# ---------------------------------------------------------------- critère 27 : perdu en route

def _reperer(api, lieu):
    code, r = appel(api, 'POST', '/api/robot/reperer', {'lieu': lieu, 'etage': 'rdc'}, delai=40)
    verifier(code == 200 and r.get('repere'), f'POST /api/robot/reperer : {code} {r}')
    dire(f'robot repéré : {r.get("message")}')


def _couper_en_route(obs, t_depart, quoi):
    """Attend que le robot roule, coupe la relocalisation ; renvoie (t_panne, t_perdu)."""
    depart = obs.pose()
    verifier(obs.attendre(lambda: math.dist(obs.pose()[:2], depart[:2]) > 1.0, 90),
             f'{quoi} : le robot ne part pas')
    t_panne = time.monotonic()
    obs.panne('muet')
    t_perdu, e = obs.attendre_etat('perdu', t_panne, 4.0, sauf=())
    dire(f'{quoi} : relocalisation coupée, perdu {t_perdu - t_panne:.1f} s après : « {e.get("message")} »')
    obs.attendre_evenement('perdu', t_panne, 2)
    time.sleep(3.2)
    d = obs.deplacement(t_perdu, t_perdu + 3.0)
    dire(f'{quoi} : {d * 100:.1f} cm parcourus dans les 3 s après perdu')
    verifier(d < 0.05, f'{quoi} : le robot a bougé de {d:.3f} m en 3 s après perdu (moins de 5 cm)')
    return t_panne, t_perdu


def perdu(args):
    obs = Observateur('/g1_jumeau/odom')
    try:
        demarrer(args.api, args.lieu, mode='repetition')
        verifier(obs.attendre(lambda: obs.dernier('/reperage/etat') is not None, 120),
                 'pas de /reperage/etat : le relais odom_vers_tf ne tourne pas')
        verifier(obs.attendre(lambda: obs.pose() is not None, 60), 'pas de vérité terrain /g1_jumeau/odom')
        time.sleep(2.0)
        _reperer(args.api, args.lieu)
        attendre_nav2(obs)
        pose_b204, _ = pose_salle(args.lieu, 'b204')
        # ---- cas A : la relocalisation revient après 5 s
        t0 = aller(args.api, {'cible': 'b204'})
        t_panne, t_perdu = _couper_en_route(obs, t0, 'cas A')
        time.sleep(max(0.0, t_panne + 5.0 - time.monotonic()))
        t_leve = time.monotonic()
        obs.panne('aucune')
        t_ret, _ = obs.attendre_evenement('retrouve', t_leve, 15)
        obs.attendre_etat(('en_route', 'detour', 'bloque'), t_leve, 10)
        dire(f'cas A : relocalisation revenue, retrouve {t_ret - t_leve:.1f} s après, reprise')
        t_arr, _ = obs.attendre_etat('arrive', t_leve, 180, cible='b204')
        verifier_arrivee(obs, pose_b204, 'cas A : arrivée à b204')
        # ---- cas B : la panne reste
        t1 = aller(args.api, {'cible': 'accueil'})
        t_panne2, t_perdu2 = _couper_en_route(obs, t1, 'cas B')
        t_echec, e = obs.attendre_etat('echec', t_perdu2, 30)
        duree = t_echec - t_perdu2
        dire(f'cas B : echec {duree:.1f} s après perdu : « {e.get("message")} »')
        verifier(abs(duree - 15.0) <= 2.0, f'echec {duree:.1f} s après perdu (15 ± 2 s attendus)')
        message = e.get('message', '')
        verifier('Repérer le robot' in message and 'point principal' in message,
                 f'le message ne dit pas quoi faire : « {message} »')
        obs.attendre_evenement('echec', t_perdu2, 3)
        time.sleep(10.0)
        d = obs.deplacement(t_perdu2, time.monotonic())
        vus = obs.suite_depuis(t_echec)
        dire(f'cas B : {d * 100:.1f} cm parcourus depuis perdu ; états ensuite : {" → ".join(vus)}')
        verifier(d < 0.05, f'cas B : le robot a bougé de {d:.3f} m (immobile attendu)')
        verifier('retour' not in vus, 'cas B : retour automatique alors que le robot est perdu')
        obs.panne('aucune')
        verifier_textes(obs, t0, args.lieu)
        codes = obs.codes_depuis(t0)
        verifier(sous_suite(codes, ['depart', 'perdu', 'retrouve', 'arrivee', 'depart', 'perdu', 'echec']),
                 f'suite d\'événements inattendue : {codes}')
        dire(f'événements : {", ".join(codes)} ; tous en français et conformes')
        return 0
    finally:
        try:
            obs.panne('aucune')
        except Exception:      # noqa: BLE001
            pass
        obs.fermer()


# ---------------------------------------------------------------- processus restants

def restes(args):
    cible = f'ATELIER_LIEUX={args.lieux}'.encode()
    trouves = []
    exclus = {os.getpid(), os.getppid()} | {int(p) for p in args.sauf}
    for d in Path('/proc').iterdir():
        if not d.name.isdigit() or int(d.name) in exclus:
            continue
        try:
            if cible in (d / 'environ').read_bytes().split(b'\0'):
                ligne = (d / 'cmdline').read_bytes().replace(b'\0', b' ').decode(errors='replace').strip()
                etat = (d / 'stat').read_text().split(') ')[-1].split()[0]
                if etat != 'Z':
                    trouves.append(f'{d.name} {ligne[:150]}')
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
    if trouves:
        print('Processus restants :\n  ' + '\n  '.join(trouves))
        return 1
    print('Aucun processus restant.')
    return 0


def main(argv=None):
    global PREFIXE
    p = argparse.ArgumentParser(prog='outils_guide_e2e.py', description=__doc__.split('\n')[0])
    sous = p.add_subparsers(dest='action', required=True)
    s = sous.add_parser('preparer')
    s.add_argument('--lieu', required=True)
    s.add_argument('--guide')
    s.add_argument('--scene')
    for nom in ('retour', 'accompagnement', 'perdu'):
        s = sous.add_parser(nom)
        s.add_argument('--api', required=True)
        s.add_argument('--lieu', required=True)
    s = sous.add_parser('restes')
    s.add_argument('--lieux', required=True)
    s.add_argument('--sauf', nargs='*', default=[])
    args = p.parse_args(argv)
    PREFIXE = {'retour': 'critère 22', 'accompagnement': 'critère 26', 'perdu': 'critère 27'}.get(
        args.action, 'guide')
    fonction = {'preparer': preparer, 'retour': retour, 'accompagnement': accompagnement,
                'perdu': perdu, 'restes': restes}[args.action]
    try:
        return fonction(args)
    except EnAttente as e:
        print(f'[{PREFIXE}] EN ATTENTE : {e}', flush=True)
        return 77
    except Echec as e:
        print(f'[{PREFIXE}] ÉCHEC : {e}', flush=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
