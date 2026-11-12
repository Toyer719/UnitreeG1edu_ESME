#!/usr/bin/env python3
"""Outils du critère 20, la sécurité en répétition (section 7 du plan, critère 20 ; section 10.3).

  critere_20_outils.py securite --api URL --lieu ID
      Chaîne de répétition réelle, lancée par l'Atelier (Gazebo --jumeau avec le faux G1, faux
      slam_operate, relais odom_vers_tf, pont, Nav2, guide). Un témoin compare en continu la vérité
      terrain (/g1_jumeau/odom) aux mouvements permis : hors d'une fenêtre où le test permet le
      mouvement, le robot ne doit jamais se déplacer de plus de 5 cm. Une fenêtre se ferme à
      l'instant où le robot doit être arrêté (événement + délai d'arrêt du contrat). Cas :
        A. pont sans repérage : /cmd_vel de 2 s, robot immobile, attente_reperage, aucun 7105 non nul ;
        B. guide avant le repérage : « Y aller » refusé (409), /guide/aller direct → echec avec message ;
        C. consignes absurdes (NaN, infini, 1e9, 1e308) par /cmd_vel et par les flèches de l'Atelier :
           jamais au-delà des plafonds (0,4 ; 0,25 ; 0,6), NaN et infini donnent un arrêt ;
        D. faux G1 muet en marche : arrêt en moins de 0,6 s, robot_muet en moins de 1,5 s ; au retour,
           pas de reprise sans /cmd_vel frais ;
        E. relocalisation perdue en marche : perdu, robot arrêté en moins de 4 s ;
        F. POST /api/guide/stop pendant « Y aller » : arrêt en moins de 0,3 s ; POST /api/robot/arret
           {verrou: true} : immobile 5 s malgré « Y aller » et /cmd_vel ;
        G. faux G1 arrêté par SIGTERM en marche : arrêt en moins de 0,6 s ; relancé, le robot reste
           immobile ;
        H. pont tué par SIGKILL en marche : arrêt en moins de 0,6 s (durée de la consigne) ; relancé,
           le robot reste immobile ;
        I. demandes absurdes à l'API : refus en français, jamais d'erreur 500.
      /pont/etat et /reperage/etat sont validés par leur schéma tout du long.

La vérité terrain est /g1_jumeau/odom (repère du monde Gazebo = map). Les délais sont en temps mural,
celui du pont et du faux G1. Code de sortie : 0 réussi, 1 échoué (les vérifications ratées sont
listées).
"""
import argparse
import json
import math
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))

from critere_18_outils import Echec, francais  # noqa: E402
from outils_pont_e2e import (Bilan, Temoin, _cmd_vel_en_fond, _nulle, _vitesses,  # noqa: E402
                             autres_requetes, format_lectures)

TOLERANCE_HORS_FENETRE_M = 0.05
PLAFONDS = (0.4, 0.25, 0.6)
MARGE_MESURE = 1.05            # vitesse mesurée : 5 % de marge sur les plafonds
# Phrases d'erreur de FastAPI ou de Python qui ne doivent jamais arriver jusqu'à l'utilisateur
ANGLAIS = ("Field required", "Input should", "Internal Server Error", "Not Found", "value is not",
           "Traceback", "Method Not Allowed", "JSON decode error")


def dire(texte):
    print(f"[critère 20] {texte}", flush=True)


# ---------------------------------------------------------------- API de l'Atelier

class Api:
    """Appels à l'API ; chaque réponse est notée pour la vérification finale (cas I)."""

    def __init__(self, base):
        self.base = base
        self.reponses = []

    def brut(self, methode, chemin, texte=None, delai=60):
        donnees = None if texte is None else texte.encode()
        r = urllib.request.Request(self.base + chemin, data=donnees, method=methode,
                                   headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(r, timeout=delai) as reponse:
                code, corps = reponse.status, reponse.read()
        except urllib.error.HTTPError as e:
            code, corps = e.code, e.read()
        try:
            donnees = json.loads(corps or b"null")
        except ValueError:
            donnees = {"detail": corps.decode("utf-8", "replace")}
        self.reponses.append((methode, chemin, texte, code, donnees))
        return code, donnees

    def __call__(self, methode, chemin, corps=None, delai=60):
        return self.brut(methode, chemin, None if corps is None else json.dumps(corps), delai)


def message_francais(reponse):
    """Un refus lisible : detail en français, sans trace ni phrase anglaise de FastAPI."""
    if not francais(reponse):
        return False
    detail = reponse["detail"]
    return not any(a in detail for a in ANGLAIS)


# ---------------------------------------------------------------- témoin

class Gardien(Temoin):
    """Le témoin du pont (requêtes, réponses, vérité, /pont/etat validé), plus /reperage/etat
    (validé), /guide/etat et les fenêtres où le mouvement est permis."""

    def __init__(self):
        super().__init__('e2e_critere_20')
        from rclpy.qos import QoSProfile, ReliabilityPolicy
        from std_msgs.msg import String
        self.String = String
        self.reperages, self.guide, self.fenetres = [], [], []
        n = self.noeud
        n.create_subscription(String, '/reperage/etat', self._reperage, 50)
        n.create_subscription(String, '/guide/etat', self._guide, 50)
        fiable = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE)
        self.pub_panne_g1 = n.create_publisher(String, '/g1_jumeau/panne', fiable)
        self.pub_panne_slam = n.create_publisher(String, '/faux_slam/panne', fiable)
        self.pub_aller = n.create_publisher(String, '/guide/aller', 10)

    def _reperage(self, m):
        try:
            etat = json.loads(m.data)
        except ValueError:
            self.non_conformes.append(('JSON illisible (/reperage/etat)', m.data[:200]))
            return
        if self.valider is not None:
            erreurs = self.valider('etat_reperage', etat)
            if erreurs:
                self.non_conformes.append((erreurs, etat))
        with self.verrou:
            self.reperages.append((time.monotonic(), etat))

    def _guide(self, m):
        try:
            etat = json.loads(m.data)
        except ValueError:
            return
        with self.verrou:
            self.guide.append((time.monotonic(), etat))

    def reperage(self):
        with self.verrou:
            return self.reperages[-1][1] if self.reperages else {}

    def etats_pont_entre(self, t0, t1=math.inf):
        with self.verrou:
            return [(t, e) for t, e in self.etats if t0 <= t < t1]

    def guide_depuis(self, t0):
        with self.verrou:
            return [e for t, e in self.guide if t >= t0]

    def attendre(self, condition, delai, pas=0.05):
        fin = time.monotonic() + delai
        while time.monotonic() < fin:
            try:
                if condition():
                    return True
            except (IndexError, KeyError):
                pass
            time.sleep(pas)
        return False

    def panne(self, editeur, texte):
        for _ in range(3):
            editeur.publish(self.String(data=texte))
            time.sleep(0.05)

    # ------------------------------------------------------------ fenêtres du mouvement permis

    def permettre(self, debut, fin):
        """Le mouvement est permis entre debut et fin (instants muraux)."""
        self.fenetres.append((debut, fin))

    def hors_fenetres(self, debut, fin):
        """[(a, b, déplacement maximal)] des intervalles interdits où le robot a bougé de plus de 5 cm."""
        coupures = sorted(self.fenetres)
        interdits, t = [], debut
        for a, b in coupures:
            if a > t:
                interdits.append((t, min(a, fin)))
            t = max(t, b)
        if t < fin:
            interdits.append((t, fin))
        fautes = []
        for a, b in interdits:
            v = self.verites_entre(a, b)
            if len(v) < 2:
                continue
            x0, y0 = v[0][2], v[0][3]
            pire = max(math.hypot(x - x0, y - y0) for _, _, x, y, _ in v)
            if pire > TOLERANCE_HORS_FENETRE_M:
                fautes.append((a, b, pire))
        return fautes, interdits

    def deplacement(self, t0, t1):
        v = self.verites_entre(t0, t1)
        if len(v) < 2:
            return 0.0
        return max(math.hypot(x - v[0][2], y - v[0][3]) for _, _, x, y, _ in v)

    def orienter_permis(self, cap_vise, delai=20.0):
        debut = time.monotonic()
        ok = self.orienter(cap_vise, delai)
        self.permettre(debut, time.monotonic())
        return ok

    def rouler_permis(self, consigne, duree, marge=0.7):
        """/cmd_vel permis à 20 Hz pendant duree secondes ; la fenêtre se ferme marge s après."""
        debut, dernier = self.cmd_vel_pendant(consigne, duree)
        self.permettre(debut, dernier + marge)
        time.sleep(marge + 0.3)
        return debut, dernier


def verifier_temoin():
    """Le témoin voit bien un déplacement hors fenêtre : essai sur une vérité fabriquée."""
    class Faux:
        fenetres = [(1.0, 2.0)]
        verites = []

        def verites_entre(self, a, b):
            return [v for v in self.verites if a <= v[0] < b]
    faux = Faux()
    # immobile, puis 0,3 m pendant la fenêtre (de 1 à 2 s), puis immobile : rien à signaler
    faux.verites = [(i / 10, i / 10, min(0.3, max(0.0, (i - 10) * 0.03)), 0.0, 0.0) for i in range(40)]
    if Gardien.hors_fenetres(faux, 0.0, 4.0)[0]:
        raise Echec("le témoin signale un mouvement permis")
    # 6 cm de plus à 3,5 s, hors de la fenêtre : signalé
    faux.verites.append((3.5, 3.5, 0.36, 0.0, 0.0))
    fautes = Gardien.hors_fenetres(faux, 0.0, 4.0)[0]
    if len(fautes) != 1 or abs(fautes[0][2] - 0.06) > 1e-9:
        raise Echec(f"le témoin ne voit pas un déplacement de 6 cm hors fenêtre ({fautes})")


# ---------------------------------------------------------------- processus de la répétition

def processus(fragment):
    """PID des processus vivants lancés avec nos lieux dont la ligne de commande contient fragment."""
    cible = f"ATELIER_LIEUX={os.environ.get('ATELIER_LIEUX', '')}".encode()
    trouves = []
    for d in Path("/proc").iterdir():
        if not d.name.isdigit() or int(d.name) == os.getpid():
            continue
        try:
            ligne = (d / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
            if fragment in ligne and cible in (d / "environ").read_bytes().split(b"\0"):
                if (d / "stat").read_text().split(") ")[-1].split()[0] != "Z":
                    trouves.append(int(d.name))
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
    return trouves


class Relances:
    """Processus relancés par le test (faux G1, pont) : arrêtés proprement (SIGINT) à la fin."""

    def __init__(self, dossier_journaux):
        self.dossier = Path(dossier_journaux)
        self.popen = []

    def lancer(self, nom, commande):
        journal = open(self.dossier / f"relance_{nom}.log", "w")
        p = subprocess.Popen(commande, stdout=journal, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                             start_new_session=True)
        self.popen.append((nom, p, journal))
        dire(f"   relancé : {nom} (processus {p.pid})")
        return p

    def arreter(self):
        for nom, p, journal in reversed(self.popen):
            for sig, attente in ((signal.SIGINT, 8.0), (signal.SIGTERM, 4.0), (signal.SIGKILL, 2.0)):
                if p.poll() is not None:
                    break
                try:
                    os.killpg(p.pid, sig)
                except ProcessLookupError:
                    break
                try:
                    p.wait(timeout=attente)
                except subprocess.TimeoutExpired:
                    continue
            journal.close()


# ---------------------------------------------------------------- les cas

def requetes_sous_plafonds(requetes):
    """Requêtes 7105 au-delà des plafonds ou non finies."""
    fautes = []
    for r in requetes:
        v = _vitesses(r)
        if v is None or not all(math.isfinite(c) for c in v) \
                or any(abs(c) > p + 1e-9 for c, p in zip(v, PLAFONDS)):
            fautes.append(r[3])
    return fautes


def securite(args):
    verifier_temoin()
    api = Api(args.api)
    g = Gardien()
    b = Bilan()
    relances = Relances(args.journaux)
    t_debut = time.monotonic()
    try:
        # ---------------------------------------------------------- démarrage de la répétition
        code, r = api("POST", "/api/simulation/demarrer", {"lieu": args.lieu, "etage": "rdc", "mode": "repetition"})
        if code != 200:
            raise Echec(f"POST /api/simulation/demarrer (repetition) : {code} {r}")
        dire(f"répétition lancée par l'Atelier : {', '.join(sorted(r['processus']))}")
        if not g.attendre(lambda: g.reperage() and g.verites and g.pub_cmd_vel.get_subscription_count() > 0
                          and g.dernier_etat().get('etat') == 'attente_reperage', 150, pas=0.2):
            raise Echec(f"la répétition ne démarre pas : repérage {g.reperage().get('etat')}, pont "
                        f"{g.dernier_etat().get('etat')}, vérité {'oui' if g.verites else 'non'}")
        t_debut = time.monotonic()
        dire(f"pont en attente du repérage, relais {g.reperage().get('etat')} ; le témoin surveille")

        # ---------------------------------------------------------- A. pont sans repérage
        dire("A. pont sans repérage : /cmd_vel de 2 s")
        debut, dernier = g.cmd_vel_pendant((0.3, 0.0, 0.0), 2.0)
        time.sleep(0.8)
        non_nuls = [r for r in g.requetes_entre(debut) if not _nulle(r)]
        etats = {e.get('etat') for _, e in g.etats_pont_entre(debut)}
        b.verifier(not non_nuls, 'aucun 7105 non nul sans repérage',
                   f'{len(non_nuls)} ordres 7105 non nuls sans repérage')
        b.verifier(etats == {'attente_reperage'}, 'pont en attente_reperage tout du long',
                   f'états du pont pendant le /cmd_vel : {sorted(etats)}')
        d = g.deplacement(debut, time.monotonic())
        b.verifier(d < TOLERANCE_HORS_FENETRE_M, f'robot immobile ({d * 100:.1f} cm)',
                   f'le robot a bougé de {d:.3f} m sans repérage')

        # ---------------------------------------------------------- B. guide avant le repérage
        dire("B. guide avant le repérage")
        code, r = api("POST", "/api/guide/aller", {"cible": "b204"})
        b.verifier(code == 409 and message_francais(r), f'« Y aller » refusé (409) : {r.get("detail", "")[:70]}…',
                   f'« Y aller » avant le repérage : {code} {r}')
        debut = time.monotonic()
        g.pub_aller.publish(g.String(data='b204'))
        vu = g.attendre(lambda: any(e.get('etat') == 'echec' and e.get('cible') == 'b204'
                                    for e in g.guide_depuis(debut)), 10)
        echec = next((e for e in g.guide_depuis(debut) if e.get('etat') == 'echec'), {})
        b.verifier(vu and 'repér' in echec.get('message', ''),
                   f'/guide/aller direct : echec, « {echec.get("message")} »',
                   f'/guide/aller avant le repérage : pas d\'echec avec message ({g.guide_depuis(debut)[-1:]})')
        time.sleep(1.0)
        d = g.deplacement(debut, time.monotonic())
        b.verifier(d < TOLERANCE_HORS_FENETRE_M, f'robot immobile ({d * 100:.1f} cm)',
                   f'le robot a bougé de {d:.3f} m après /guide/aller sans repérage')

        # ---------------------------------------------------------- repérage, robot tourné vers le nord
        code, r = api("POST", "/api/robot/reperer", {"lieu": args.lieu, "etage": "rdc"}, delai=40)
        if code != 200 or not r.get("repere"):
            raise Echec(f"POST /api/robot/reperer : {code} {r}")
        dire(f"repéré : {r.get('message')}")
        if not g.attendre(lambda: g.dernier_etat().get('etat') == 'pret', 10):
            raise Echec(f"le pont n'est pas prêt après le repérage : {g.dernier_etat()}")
        # le hall fait 9 m du sud au nord : les essais en marche se font vers le nord
        b.verifier(g.orienter_permis(math.pi / 2), 'robot tourné vers le nord par le pont',
                   'impossible de tourner le robot vers le nord')

        # ---------------------------------------------------------- C. consignes absurdes
        dire("C. consignes absurdes par /cmd_vel, puis par les flèches de l'Atelier")
        inf, nan = float('inf'), float('nan')
        absurdes = [((1e9, 0.0, 0.0), False), ((-1e9, 1e9, -1e9), False), ((1e9, -1e9, 1e9), False),
                    ((nan, 0.0, 0.0), True), ((inf, 0.0, 0.0), True), ((0.2, nan, 0.0), True),
                    ((0.0, 0.0, -inf), True), ((-1e308, 1e308, 1e308), False), ((1e308, -1e308, -1e308), False)]
        debut = time.monotonic()
        mesures, arrets_ko = [], []
        for consigne, est_arret in absurdes:
            t0, t1 = g.cmd_vel_pendant(consigne, 0.6)
            if est_arret:
                envoyees = g.requetes_entre(t0 + 0.05, t1 + 0.05)
                if not envoyees or not all(_nulle(r) for r in envoyees):
                    arrets_ko.append((consigne, [_vitesses(r) for r in envoyees][:3]))
            else:
                m = g.vitesse_robot(t0 + 0.2, t1)
                if m:
                    mesures.append(m)
        time.sleep(0.8)
        g.permettre(debut, time.monotonic())
        fautes = requetes_sous_plafonds(g.requetes_entre(debut))
        b.verifier(not fautes, f'{len(g.requetes_entre(debut))} ordres 7105, tous finis et sous les plafonds',
                   f'ordres au-delà des plafonds : {fautes[:3]}')
        b.verifier(not arrets_ko, 'NaN et infini donnent des arrêts', f'NaN ou infini : {arrets_ko[:2]}')
        pire = tuple(max(abs(m[i]) for m in mesures) for i in range(3)) if mesures else None
        b.verifier(pire is not None and all(v <= p * MARGE_MESURE for v, p in zip(pire, PLAFONDS)),
                   f'vitesses mesurées au plus : avant {pire[0]:.3f}, côté {pire[1]:.3f}, rotation {pire[2]:.3f}'
                   if pire else '', f'vitesses mesurées au-delà des plafonds : {pire}')
        # par les flèches de l'Atelier (téléopération de la répétition, homme mort de 0,5 s)
        debut = time.monotonic()
        for corps in ({"vx": 1e9, "vy": 0.0, "wz": 0.0}, {"vx": -1e9, "vy": -1e9, "wz": 1e9}):
            code, r = api("POST", "/api/simulation/teleop", corps)
            b.verifier(code == 200, f'flèches {corps} : envoyé {r.get("envoye")}', f'flèches {corps} : {code} {r}')
            time.sleep(1.2)
        api("POST", "/api/simulation/teleop", {"vx": 0.0, "vy": 0.0, "wz": 0.0})
        time.sleep(0.5)
        g.permettre(debut, time.monotonic())
        fautes = requetes_sous_plafonds(g.requetes_entre(debut))
        b.verifier(not fautes and any(not _nulle(r) for r in g.requetes_entre(debut)),
                   'flèches de l\'Atelier : ordres envoyés, sous les plafonds',
                   f'flèches : ordres au-delà des plafonds ou aucun ordre : {fautes[:3]}')
        for texte in ('{"vx": NaN, "vy": 0, "wz": 0}', '{"vx": 1e999, "vy": 0, "wz": 0}',
                      '{"vx": "vite", "vy": 0, "wz": 0}', 'pas du json'):
            code, r = api.brut("POST", "/api/simulation/teleop", texte)
            b.verifier(code in (400, 422) and message_francais(r), f'flèches {texte} : {code} « {r["detail"][:60]}… »',
                       f'flèches {texte} : {code} {r}')
        b.verifier(g.orienter_permis(math.pi / 2), 'robot de nouveau tourné vers le nord', 'robot pas tourné')

        # ---------------------------------------------------------- D. faux G1 muet en marche
        dire("D. faux G1 muet pendant la marche")
        debut = time.monotonic()
        fil = _cmd_vel_en_fond(g, (0.3, 0.0, 0.0))
        time.sleep(1.0)
        t_panne = time.monotonic()
        g.panne(g.pub_panne_g1, 'muet')
        g.permettre(debut, t_panne + 0.6)
        time.sleep(1.8)
        fil.arreter()
        arret = g.instant_arret(t_panne)
        b.verifier(arret is not None and arret - t_panne < 0.6,
                   f'arrêté {arret - t_panne if arret else 0:.2f} s après la panne (< 0,6 s)',
                   f'faux G1 muet : pas arrêté en 0,6 s ({arret and arret - t_panne})')
        muet = next((t for t, e in g.etats_pont_entre(t_panne) if e.get('etat') == 'robot_muet'), None)
        b.verifier(muet is not None and muet - t_panne < 1.5,
                   f'pont en robot_muet {muet - t_panne if muet else 0:.2f} s après la panne (< 1,5 s) : '
                   f'« {next(e for t, e in g.etats_pont_entre(t_panne) if e.get("etat") == "robot_muet")["message"]} »'
                   if muet else '', 'pas d\'état robot_muet en 1,5 s')
        time.sleep(0.5)
        t_retour = time.monotonic()
        g.panne(g.pub_panne_g1, 'aucune')
        time.sleep(2.5)
        non_nuls = [r for r in g.requetes_entre(t_retour) if not _nulle(r)]
        d = g.deplacement(t_retour, time.monotonic())
        b.verifier(not non_nuls and d < TOLERANCE_HORS_FENETRE_M,
                   f'faux G1 revenu : pas de reprise sans /cmd_vel frais ({d * 100:.1f} cm)',
                   f'faux G1 revenu : {len(non_nuls)} ordres non nuls, {d:.3f} m sans /cmd_vel frais')
        t0, _ = g.rouler_permis((-0.3, 0.0, 0.0), 1.0)
        b.verifier(any(not _nulle(r) for r in g.requetes_entre(t0)) and g.deplacement(t0, time.monotonic()) > 0.15,
                   'la marche reprend au /cmd_vel frais', 'pas de reprise au /cmd_vel frais après la panne')

        # ---------------------------------------------------------- E. relocalisation perdue en marche
        dire("E. relocalisation perdue pendant la marche")
        if not g.attendre(lambda: g.reperage().get('etat') == 'repere' and g.dernier_etat().get('etat') == 'pret', 5):
            raise Echec(f"pas prêt avant l'essai E : repérage {g.reperage().get('etat')}, pont {g.dernier_etat()}")
        debut = time.monotonic()
        fil = _cmd_vel_en_fond(g, (0.2, 0.0, 0.0))
        time.sleep(0.5)
        t_panne = time.monotonic()
        g.panne(g.pub_panne_slam, 'muet')
        g.permettre(debut, t_panne + 4.0)
        time.sleep(5.5)
        fil.arreter()
        perdu = next((t for t, e in g.reperages if t >= t_panne and e.get('etat') == 'perdu'), None)
        arret = g.instant_arret(t_panne + 2.0)
        b.verifier(perdu is not None, f'perdu {perdu - t_panne if perdu else 0:.1f} s après la coupure',
                   'relocalisation coupée : pas d\'état perdu')
        b.verifier(arret is not None and arret - t_panne < 4.0,
                   f'robot arrêté {arret - t_panne if arret else 0:.1f} s après la coupure (< 4 s), '
                   'malgré le /cmd_vel', f'relocalisation perdue : pas arrêté en 4 s ({arret and arret - t_panne})')
        g.panne(g.pub_panne_slam, 'aucune')
        b.verifier(g.attendre(lambda: g.reperage().get('etat') == 'repere', 8), 'relocalisation revenue : repéré',
                   'relocalisation revenue : pas repéré de nouveau')
        g.rouler_permis((-0.3, 0.0, 0.0), 2.0)

        # ---------------------------------------------------------- F. arrêt et verrou depuis l'Atelier
        dire("F. ARRÊT et verrou depuis l'Atelier, pendant « Y aller »")
        t_nav2 = time.monotonic()
        from lifecycle_msgs.srv import GetState
        client = g.noeud.create_client(GetState, '/bt_navigator/get_state')

        def nav2_actif():
            if not client.wait_for_service(timeout_sec=0.5):
                return False
            futur = client.call_async(GetState.Request())
            fin = time.monotonic() + 3.0
            while not futur.done() and time.monotonic() < fin:
                time.sleep(0.05)
            return bool(futur.done() and futur.result() and futur.result().current_state.label == 'active')
        if not g.attendre(nav2_actif, 120, pas=0.5):
            raise Echec("Nav2 n'est pas actif après le repérage")
        dire(f"   Nav2 actif ({time.monotonic() - t_nav2:.1f} s)")
        debut = time.monotonic()
        code, r = api("POST", "/api/guide/aller", {"cible": "b204"})
        b.verifier(code == 200, '« Y aller » b204 accepté une fois repéré', f'« Y aller » : {code} {r}')
        bouge = g.attendre(lambda: g.deplacement(debut, time.monotonic()) > 0.5, 40, pas=0.2)
        b.verifier(bouge, f'le robot part vers b204 ({g.deplacement(debut, time.monotonic()):.2f} m)',
                   'le robot ne part pas vers b204')
        time.sleep(1.0)
        t_stop = time.monotonic()
        code, r = api("POST", "/api/guide/stop")
        g.permettre(debut, t_stop + 0.3)
        b.verifier(code == 200, 'POST /api/guide/stop accepté', f'POST /api/guide/stop : {code} {r}')
        time.sleep(1.5)
        arret = g.instant_arret(t_stop)
        b.verifier(arret is not None and arret - t_stop < 0.3,
                   f'ARRÊT : robot arrêté {arret - t_stop if arret else 0:.2f} s après (< 0,3 s)',
                   f'ARRÊT : pas arrêté en 0,3 s ({arret and arret - t_stop})')
        code, r = api("POST", "/api/robot/arret", {"verrou": True})
        b.verifier(code == 200 and r.get("ecoute", 0) > 0, f'verrou posé ({r.get("ecoute")} pont à l\'écoute)',
                   f'POST /api/robot/arret verrou : {code} {r}')
        t_verrou = time.monotonic()
        code, r = api("POST", "/api/guide/aller", {"cible": "b204"})
        g.cmd_vel_pendant((0.3, 0.0, 0.0), 1.0)
        time.sleep(4.0)
        d = g.deplacement(t_verrou, time.monotonic())
        non_nuls = [r for r in g.requetes_entre(t_verrou) if not _nulle(r)]
        b.verifier(d < TOLERANCE_HORS_FENETRE_M and not non_nuls,
                   f'verrouillé : immobile 5 s malgré « Y aller » et /cmd_vel ({d * 100:.1f} cm, aucun 7105 non nul)',
                   f'verrouillé : {d:.3f} m, {len(non_nuls)} ordres non nuls')
        b.verifier(g.dernier_etat().get('etat') == 'arret_verrouille',
                   f'pont en arret_verrouille : « {g.dernier_etat().get("message")} »',
                   f'pont en {g.dernier_etat().get("etat")}')
        api("POST", "/api/guide/stop")
        time.sleep(0.5)
        t_libre = time.monotonic()
        code, r = api("POST", "/api/robot/arret", {"verrou": False})
        b.verifier(code == 200, 'verrou levé', f'POST /api/robot/arret déverrouillage : {code} {r}')
        time.sleep(2.0)
        d = g.deplacement(t_libre, time.monotonic())
        b.verifier(d < TOLERANCE_HORS_FENETRE_M, f'déverrouillé : rien ne repart seul ({d * 100:.1f} cm)',
                   f'déverrouillé : le robot est reparti seul ({d:.3f} m)')

        # ---------------------------------------------------------- G. faux G1 arrêté par SIGTERM
        dire("G. faux G1 arrêté par SIGTERM pendant la marche")
        b.verifier(g.orienter_permis(math.pi / 2), 'robot tourné vers le nord', 'robot pas tourné')
        pids = processus('lib/g1_jumeau/jumeau')
        if len(pids) != 1:
            raise Echec(f"faux G1 introuvable (processus : {pids})")
        debut = time.monotonic()
        fil = _cmd_vel_en_fond(g, (0.25, 0.0, 0.0))
        time.sleep(1.0)
        t_kill = time.monotonic()
        os.kill(pids[0], signal.SIGTERM)
        g.permettre(debut, t_kill + 0.6)
        time.sleep(1.2)
        fil.arreter()
        arret = g.instant_arret(t_kill)
        b.verifier(arret is not None and arret - t_kill < 0.6,
                   f'arrêté {arret - t_kill if arret else 0:.2f} s après le SIGTERM du faux G1 (< 0,6 s)',
                   f'faux G1 arrêté : pas d\'arrêt en 0,6 s ({arret and arret - t_kill})')
        time.sleep(1.0)
        relances.lancer('g1_jumeau', ['ros2', 'run', 'g1_jumeau', 'jumeau'])
        b.verifier(g.attendre(lambda: processus('lib/g1_jumeau/jumeau')
                              and g.dernier_etat().get('etat') == 'pret', 30, pas=0.2),
                   'faux G1 relancé : pont de nouveau prêt', f'faux G1 relancé : pont en {g.dernier_etat()}')
        t_relance = time.monotonic()
        time.sleep(3.0)
        d = g.deplacement(t_relance, time.monotonic())
        non_nuls = [r for r in g.requetes_entre(t_relance) if not _nulle(r)]
        b.verifier(d < TOLERANCE_HORS_FENETRE_M and not non_nuls,
                   f'faux G1 relancé : robot immobile ({d * 100:.1f} cm)',
                   f'faux G1 relancé : {d:.3f} m, {len(non_nuls)} ordres non nuls')
        t0, _ = g.rouler_permis((-0.25, 0.0, 0.0), 1.0)
        b.verifier(g.deplacement(t0, time.monotonic()) > 0.1, 'le faux G1 relancé obéit au /cmd_vel frais',
                   'le faux G1 relancé ne fait pas bouger le robot')

        # ---------------------------------------------------------- H. pont tué par SIGKILL
        dire("H. pont tué par SIGKILL pendant la marche")
        pids = processus('lib/g1_bridge/pont')
        if len(pids) != 1:
            raise Echec(f"pont introuvable (processus : {pids})")
        debut = time.monotonic()
        fil = _cmd_vel_en_fond(g, (0.25, 0.0, 0.0))
        time.sleep(1.0)
        t_kill = time.monotonic()
        os.kill(pids[0], signal.SIGKILL)
        g.permettre(debut, t_kill + 0.6)
        time.sleep(1.2)
        fil.arreter()
        arret = g.instant_arret(t_kill)
        b.verifier(arret is not None and arret - t_kill < 0.6,
                   f'arrêté {arret - t_kill if arret else 0:.2f} s après le SIGKILL du pont (< 0,6 s : la consigne '
                   'expire)', f'pont tué : pas d\'arrêt en 0,6 s ({arret and arret - t_kill})')
        time.sleep(1.0)
        reglages = subprocess.run(['ros2', 'pkg', 'prefix', 'g1_bridge'], capture_output=True, text=True).stdout.strip()
        relances.lancer('pont_g1', ['ros2', 'run', 'g1_bridge', 'pont', '--ros-args', '--params-file',
                                    f'{reglages}/share/g1_bridge/config/pont.yaml', '-r', '__node:=pont_g1'])
        t_relance = time.monotonic()
        b.verifier(g.attendre(lambda: any(e.get('etat') == 'pret' for _, e in g.etats_pont_entre(t_relance)), 30),
                   'pont relancé : prêt', f'pont relancé : {g.dernier_etat()}')
        time.sleep(3.0)
        d = g.deplacement(t_relance, time.monotonic())
        non_nuls = [r for r in g.requetes_entre(t_relance) if not _nulle(r)]
        b.verifier(d < TOLERANCE_HORS_FENETRE_M and not non_nuls,
                   f'pont relancé : robot immobile ({d * 100:.1f} cm, aucun 7105 non nul)',
                   f'pont relancé : {d:.3f} m, {len(non_nuls)} ordres non nuls')
        t0, _ = g.rouler_permis((-0.25, 0.0, 0.0), 1.0)
        b.verifier(g.deplacement(t0, time.monotonic()) > 0.1, 'le pont relancé obéit au /cmd_vel frais',
                   'le pont relancé ne fait pas bouger le robot')

        # ---------------------------------------------------------- I. demandes absurdes à l'API
        dire("I. demandes absurdes à l'API")
        absurdes = [
            ("POST", "/api/robot/reperer", {"lieu": args.lieu, "etage": "rdc", "x": 1.0}),
            ("POST", "/api/robot/reperer", {"lieu": args.lieu, "etage": "rdc", "x": 1.0, "y": 2.0, "cap": 100.0}),
            ("POST", "/api/robot/reperer", {"lieu": "inconnu", "etage": "rdc"}),
            ("POST", "/api/robot/reperer", {"lieu": args.lieu, "etage": "grenier"}),
            ("POST", "/api/robot/reperer", {"etage": "rdc"}),
            ("POST", "/api/robot/arret", {}),
            ("POST", "/api/robot/arret", {"verrou": "peut-être"}),
            ("POST", "/api/guide/aller", {"cible": "../../etc"}),
            ("POST", "/api/guide/aller", {"cible": "salle_qui_n_existe_pas"}),
            ("POST", "/api/guide/aller", {}),
            ("POST", "/api/simulation/demarrer", {"lieu": args.lieu, "etage": "rdc", "mode": "repetition"}),
            ("POST", "/api/simulation/demarrer", {"lieu": args.lieu, "etage": "rdc", "mode": "fusee"}),
            ("GET", "/api/robot/inconnu", None),
        ]
        for methode, chemin, corps in absurdes:
            code, r = api(methode, chemin, corps)
            b.verifier(400 <= code < 500 and message_francais(r),
                       f'{methode} {chemin} {json.dumps(corps, ensure_ascii=False) if corps is not None else ""} : '
                       f'{code} « {r["detail"][:70]} »', f'{methode} {chemin} {corps} : {code} {r}')
        code, r = api.brut("POST", "/api/robot/reperer",
                           json.dumps({"lieu": args.lieu, "etage": "rdc", "x": float('nan'), "y": 0.0, "cap": 0.0}))
        b.verifier(400 <= code < 500 and message_francais(r), f'repérage en NaN : {code} « {r["detail"][:60]} »',
                   f'repérage en NaN : {code} {r}')
        code, r = api("GET", "/api/robot/etat")
        b.verifier(code == 200 and r.get("repere") and r.get("pont") is not None,
                   f'GET /api/robot/etat : repéré, pont {r.get("pont", {}).get("etat")}', f'GET /api/robot/etat : {code} {r}')

        # ---------------------------------------------------------- bilans
        dire("bilans")
        t_fin = time.monotonic()
        fautes, interdits = g.hors_fenetres(t_debut, t_fin)
        duree_interdite = sum(b_ - a for a, b_ in interdits)
        b.verifier(not fautes,
                   f'témoin : jamais plus de 5 cm hors d\'une consigne permise ({len(interdits)} intervalles, '
                   f'{duree_interdite:.0f} s sur {t_fin - t_debut:.0f} s)',
                   'témoin : déplacements hors consigne permise : '
                   + '; '.join(f'{p:.3f} m entre {a - t_debut:.1f} s et {b_ - t_debut:.1f} s' for a, b_, p in fautes[:3]))
        fautes = requetes_sous_plafonds(g.requetes_entre(t_debut))
        b.verifier(not fautes, f'{len(g.requetes_entre(t_debut))} ordres 7105 en tout, tous sous les plafonds',
                   f'ordres 7105 au-delà des plafonds : {fautes[:3]}')
        autres = autres_requetes(g.requetes_entre(t_debut, api=None))
        b.verifier(not autres, 'aucun autre ordre que 7105 (et les lectures du mode 7001, vague 5) sur '
                   '/api/sport/request', f'autres ordres : {autres[:3]}')
        format_lectures(g.lectures_entre(t_debut), b)
        erreurs_500 = [(m, c, code) for m, c, _, code, _ in api.reponses if code >= 500 and code not in (502, 503, 504)]
        b.verifier(not erreurs_500, f'{len(api.reponses)} appels à l\'API, jamais d\'erreur 500',
                   f'erreurs 500 : {erreurs_500[:3]}')
        sans_francais = [(m, c, code, r) for m, c, _, code, r in api.reponses
                         if code >= 400 and not message_francais(r)]
        b.verifier(not sans_francais, 'tous les refus de l\'API ont un message en français',
                   f'refus sans message en français : {sans_francais[:3]}')
        b.verifier(not g.non_conformes and g.etats and g.reperages,
                   f'{len(g.etats)} /pont/etat et {len(g.reperages)} /reperage/etat, tous conformes au schéma',
                   f'messages non conformes : {g.non_conformes[:2]}')
        return b.code()
    finally:
        try:
            g.pub_verrou.publish(g.Bool(data=False))
        except Exception:      # noqa: BLE001 : fin du test
            pass
        relances.arreter()
        g.fermer()


def main(argv=None):
    p = argparse.ArgumentParser(prog="critere_20_outils.py", description=__doc__.split("\n")[0])
    sous = p.add_subparsers(dest="action", required=True)
    s = sous.add_parser("securite")
    s.add_argument("--api", required=True)
    s.add_argument("--lieu", required=True)
    s.add_argument("--journaux", default=".")
    args = p.parse_args(argv)
    try:
        return securite(args)
    except Echec as e:
        print(f"[critère 20] ÉCHEC : {e}", flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
