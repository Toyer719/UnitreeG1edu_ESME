#!/usr/bin/env python3
"""Outils du critère 34, la vitesse minimale et le mode du robot (section 12.10 du plan, vague 5).

  outils_robot_e2e.py pont-modes
      contre Gazebo --jumeau (faux G1 avec son seuil de marche) et le pont avec ses défauts :
      1. sans le pont, un 7105 brut à 0,1 m/s (envoyé par le test) laisse le faux G1 immobile,
         comme le vrai G1 le 27/10 ;
      2. /cmd_vel vx 0,1 pendant 3 s : les 7105 portent (0,2 ; 0 ; 0), la vérité avance de
         0,6 ± 0,2 m ; /pont/etat : demande 0,1, consigne 0,2, minimums ;
      3. wz 0,15 seul : 7105 à (0 ; 0 ; 0,3), le robot tourne ; vx 0,03 : aucun 7105 non nul,
         robot immobile (moins de 2 cm) ;
      4. faux G1 assis (3, sujet d'essai /g1_jumeau/mode) : pas_en_marche en moins de 2 s,
         mode_robot.fsm 3, message avec « assis » ; /cmd_vel vx 0,3 pendant 3 s : aucun 7105 non
         nul, robot immobile ; « Démarrer » (7101 {"data": 500}, puis 501) : pret en moins de
         3 s sans mouvement, puis un /cmd_vel neuf : en_mouvement, le robot avance ; course
         (802) : pas_en_marche, message avec « course » ;
      5. tout du long : 7001 à 1 Hz (de 0,7 à 1,3 par seconde) au format « {} », chaque 7105 au
         format de 10.3, /pont/etat conforme (schéma et règles).
  outils_robot_e2e.py restes --lieux DOSSIER
      processus encore vivants lancés avec ATELIER_LIEUX=DOSSIER (code 1 s'il en reste).

La vérité terrain est /g1_jumeau/odom. Code de sortie : 0 réussi, 1 échoué.
"""
import argparse
import json
import math
import os
from pathlib import Path
import sys
import time

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))

from outils_pont_e2e import (Bilan, Temoin, _nulle, _vitesses, angle_normal,  # noqa: E402
                             autres_requetes, format_lectures, format_requetes)

SEUIL_IMMOBILE_M = 0.02


def dire(texte):
    print(f"[critère 34] {texte}", flush=True)


class Banc(Temoin):
    """Le témoin du pont, qui sait aussi changer le mode du faux G1 et lui parler directement."""

    def __init__(self):
        super().__init__('e2e_critere_34')
        from rclpy.qos import QoSProfile, ReliabilityPolicy
        from std_msgs.msg import Int32
        from unitree_api.msg import Request
        self.Int32, self.Request = Int32, Request
        fiable = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE)
        self.pub_mode = self.noeud.create_publisher(Int32, '/g1_jumeau/mode', fiable)
        self.pub_requete = self.noeud.create_publisher(Request, '/api/sport/request', fiable)
        self.prochain_id = time.monotonic_ns()

    def mode(self, fsm):
        """Le mode du faux G1 changé d'un coup, comme à la télécommande."""
        for _ in range(3):
            self.pub_mode.publish(self.Int32(data=int(fsm)))
            time.sleep(0.05)

    def requete(self, api_id, parametre):
        """Une requête au service sport, comme un autre programme (le pilotage, l'appli)."""
        self.prochain_id = max(time.monotonic_ns(), self.prochain_id + 1)
        r = self.Request()
        r.header.identity.id = self.prochain_id
        r.header.identity.api_id = int(api_id)
        r.parameter = parametre
        self.pub_requete.publish(r)
        return self.prochain_id

    def deplacement(self, t0, t1=math.inf):
        v = self.verites_entre(t0, t1)
        if len(v) < 2:
            return 0.0
        return max(math.hypot(x - v[0][2], y - v[0][3]) for _, _, x, y, _ in v)

    def rotation(self, t0, t1=math.inf):
        v = self.verites_entre(t0, t1)
        if len(v) < 2:
            return 0.0
        return abs(sum(angle_normal(b[4] - a[4]) for a, b in zip(v, v[1:])))

    def etats_entre(self, t0, t1=math.inf):
        with self.verrou:
            return [e for t, e in self.etats if t0 <= t < t1]

    def attendre_etat(self, nom, delai):
        """Instant où /pont/etat passe à nom (None après delai)."""
        fin = time.monotonic() + delai
        while time.monotonic() < fin:
            if self.dernier_etat().get('etat') == nom:
                return time.monotonic()
            time.sleep(0.02)
        return None


def non_nuls(requetes):
    return [r for r in requetes if not _nulle(r)]


def pont_modes(args):
    b = Bilan()
    t = Banc()
    try:
        if not t.attendre_pret(30):
            print('vérité terrain, /pont/etat ou pont absents')
            return 1
        etat = t.dernier_etat()
        fin = time.monotonic() + 10.0
        while (etat.get('etat') != 'pret' or (etat.get('mode_robot') or {}).get('fsm') != 501) \
                and time.monotonic() < fin:
            time.sleep(0.1)
            etat = t.dernier_etat()
        b.verifier(etat.get('etat') == 'pret' and etat['mode_robot']['fsm'] == 501,
                   'pont prêt, mode du faux G1 lu par 7001 : 501 (marche)',
                   f'pont pas prêt ou mode inconnu : {etat.get("etat")} {etat.get("mode_robot")}')

        dire('1. sans le pont : un 7105 brut à 0,1 m/s laisse le faux G1 immobile (seuil de marche)')
        t0 = time.monotonic()
        while time.monotonic() - t0 < 2.0:
            t.requete(7105, json.dumps({'velocity': [0.1, 0.0, 0.0], 'duration': 0.5}))
            time.sleep(0.1)
        time.sleep(0.5)
        d = t.deplacement(t0)
        b.verifier(d < SEUIL_IMMOBILE_M, f'7105 brut à 0,1 m/s pendant 2 s : {d * 100:.1f} cm (immobile, '
                   'comme le vrai G1 le 27/10)', f'le faux G1 a bougé de {d:.3f} m à 0,1 m/s')
        # les requêtes brutes du test (ses propres identifiants) restent hors des bilans du 5
        time.sleep(0.5)
        t_debut = time.monotonic()

        dire('2. /cmd_vel vx 0,1 pendant 3 s : le pont envoie 0,2 m/s')
        x0, y0, _ = t.pose()
        debut, dernier = t.cmd_vel_pendant((0.1, 0.0, 0.0), 3.0)
        time.sleep(1.5)
        x1, y1, _ = t.pose()
        distance = math.hypot(x1 - x0, y1 - y0)
        mouvement = non_nuls(t.requetes_entre(debut, dernier + 0.6))
        vitesses = {tuple(round(v, 6) for v in _vitesses(r)) for r in mouvement}
        b.verifier(mouvement and vitesses == {(0.2, 0.0, 0.0)},
                   f'{len(mouvement)} ordres 7105 non nuls, tous à (0,2 ; 0 ; 0)',
                   f'ordres envoyés : {sorted(vitesses)}')
        b.verifier(abs(distance - 0.6) <= 0.2, f'la vérité avance de {distance:.3f} m (0,6 ± 0,2)',
                   f'la vérité avance de {distance:.3f} m au lieu de 0,6 ± 0,2')
        marche = [e for e in t.etats_entre(debut + 0.3, dernier) if e.get('etat') == 'en_mouvement']
        ok = marche and all(e['demande']['vx'] == 0.1 and e['consigne']['vx'] == 0.2 for e in marche) \
            and marche[-1]['minimums'] == {'vitesse_min_lin': 0.2, 'vitesse_min_rot': 0.3,
                                           'zone_morte_lin': 0.05, 'zone_morte_rot': 0.1}
        b.verifier(ok, f'/pont/etat en marche : demande 0,1, consigne 0,2, minimums ({len(marche)} messages)',
                   f'/pont/etat en marche : {marche[-1:] if marche else "aucun en_mouvement"}')

        dire('3. wz 0,15 seul, puis vx 0,03')
        debut, dernier = t.cmd_vel_pendant((0.0, 0.0, 0.15), 2.0)
        time.sleep(1.0)
        mouvement = non_nuls(t.requetes_entre(debut, dernier + 0.6))
        vitesses = {tuple(round(v, 6) for v in _vitesses(r)) for r in mouvement}
        tourne = t.rotation(debut, dernier + 1.0)
        b.verifier(mouvement and vitesses == {(0.0, 0.0, 0.3)},
                   f'wz 0,15 seul : {len(mouvement)} ordres à (0 ; 0 ; 0,3)', f'wz 0,15 seul : {sorted(vitesses)}')
        b.verifier(tourne > 0.3, f'le robot a tourné de {math.degrees(tourne):.0f}°',
                   f'le robot n\'a tourné que de {math.degrees(tourne):.1f}°')
        debut, dernier = t.cmd_vel_pendant((0.03, 0.0, 0.0), 2.0)
        time.sleep(0.5)
        d = t.deplacement(debut + 0.6, dernier + 0.5)
        b.verifier(not non_nuls(t.requetes_entre(debut + 0.05, dernier + 0.5)) and d < SEUIL_IMMOBILE_M,
                   f'vx 0,03 (zone morte) : aucun 7105 non nul, robot immobile ({d * 100:.1f} cm)',
                   f'vx 0,03 : {len(non_nuls(t.requetes_entre(debut + 0.05)))} 7105 non nuls, {d:.3f} m')

        dire('4. faux G1 assis, « Démarrer », course')
        t_assis = time.monotonic()
        t.mode(3)
        t_etat = t.attendre_etat('pas_en_marche', 2.5)
        etat = t.dernier_etat()
        b.verifier(t_etat is not None and t_etat - t_assis < 2.0 and etat['mode_robot']['fsm'] == 3
                   and 'assis' in etat['message'],
                   f'assis : pas_en_marche en {(t_etat or t_assis) - t_assis:.2f} s, « {etat.get("message")} »',
                   f'assis : {etat.get("etat")} {etat.get("mode_robot")} ({etat.get("message")})')
        debut, dernier = t.cmd_vel_pendant((0.3, 0.0, 0.0), 3.0)
        time.sleep(0.5)
        d = t.deplacement(debut, dernier + 0.5)
        b.verifier(not non_nuls(t.requetes_entre(debut)) and d < SEUIL_IMMOBILE_M,
                   f'assis : /cmd_vel 0,3 pendant 3 s ignoré, aucun 7105 non nul, immobile ({d * 100:.1f} cm)',
                   f'assis : {len(non_nuls(t.requetes_entre(debut)))} 7105 non nuls, {d:.3f} m')
        t_demarrer = time.monotonic()
        t.requete(7101, json.dumps({'data': 500}))          # « Démarrer », comme le pilotage
        t_pret = t.attendre_etat('pret', 3.5)
        time.sleep(1.5)
        d = t.deplacement(t_demarrer)
        b.verifier(t_pret is not None and t_pret - t_demarrer < 3.0 and d < SEUIL_IMMOBILE_M
                   and not non_nuls(t.requetes_entre(t_demarrer)),
                   f'« Démarrer » : pret en {(t_pret or t_demarrer) - t_demarrer:.2f} s, sans mouvement '
                   f'({d * 100:.1f} cm)', f'« Démarrer » : {t.dernier_etat().get("etat")}, {d:.3f} m')
        b.verifier(t.dernier_etat()['mode_robot']['fsm'] == 501, 'mode 500 puis 501, lu par 7001',
                   f'mode après « Démarrer » : {t.dernier_etat()["mode_robot"]}')
        debut = time.monotonic()
        t.cmd_vel_pendant((0.3, 0.0, 0.0), 1.5)
        vus = {e.get('etat') for e in t.etats_entre(debut)}
        time.sleep(0.8)
        d = t.deplacement(debut)
        b.verifier('en_mouvement' in vus and d > 0.2, f'/cmd_vel neuf : en_mouvement, le robot avance de {d:.2f} m',
                   f'/cmd_vel neuf : états {vus}, {d:.3f} m')
        t.mode(802)
        t_etat = t.attendre_etat('pas_en_marche', 2.5)
        etat = t.dernier_etat()
        b.verifier(t_etat is not None and 'course' in etat['message'] and etat['mode_robot']['fsm'] == 802,
                   f'course (802) : pas_en_marche, « {etat.get("message")} »',
                   f'course : {etat.get("etat")} {etat.get("message")}')
        t.mode(501)
        b.verifier(t.attendre_etat('pret', 3.0) is not None, 'de retour en marche (501) : pret',
                   f'retour en 501 : {t.dernier_etat().get("etat")}')
        t_fin = time.monotonic()

        dire('5. lectures du mode, format des 7105, /pont/etat')
        format_lectures(t.lectures_entre(t_debut, t_fin), b, t_fin - t_debut)
        format_requetes(t.requetes_entre(t_debut, t_fin), b)
        toutes = t.requetes_entre(t_debut, t_fin, api=None)
        autres = [r for r in autres_requetes(toutes) if r[2] != 7101]      # le « Démarrer » du test
        b.verifier(not autres, 'sur /api/sport/request : 7105, 7001 et le 7101 du test, rien d\'autre',
                   f'autres requêtes : {autres[:3]}')
        b.conformite(t)
        return b.code()
    finally:
        try:
            t.mode(501)
        except Exception:       # noqa: BLE001 : fin du test
            pass
        t.fermer()


def restes(args):
    """Processus vivants lancés avec nos lieux (ATELIER_LIEUX), en dehors de celui-ci."""
    cible = f"ATELIER_LIEUX={args.lieux}".encode()
    trouves = []
    for d in Path("/proc").iterdir():
        if not d.name.isdigit() or int(d.name) in (os.getpid(), os.getppid()):
            continue
        try:
            if cible not in (d / "environ").read_bytes().split(b"\0"):
                continue
            if (d / "stat").read_text().split(") ")[-1].split()[0] == "Z":
                continue
            ligne = (d / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if any(m in ligne for m in ("ros2", "gazebo", "ign ", "lib/g1_", "g1-", "python")):
            trouves.append(f"{d.name} {ligne[:120]}")
    for ligne in trouves:
        print(f"reste : {ligne}")
    return 1 if trouves else 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="outils_robot_e2e.py", description=__doc__.split("\n")[0])
    sous = p.add_subparsers(dest="action", required=True)
    s = sous.add_parser("pont-modes")
    s.set_defaults(f=pont_modes)
    s = sous.add_parser("restes")
    s.add_argument("--lieux", required=True)
    s.set_defaults(f=restes)
    args = p.parse_args(argv)
    os.environ.setdefault('PYTHONUNBUFFERED', '1')
    return args.f(args)


if __name__ == "__main__":
    sys.exit(main())
