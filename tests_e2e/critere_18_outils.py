#!/usr/bin/env python3
"""Outils du critère 18, repérage en répétition (section 7 du plan, critère 18 ; section 10).

  critere_18_outils.py variante-a --api URL --lieu ID
      repère d'Unitree figé de la répétition (départ du robot) : avant le repérage (non repéré,
      pas de map → odom, « Y aller » refusé), « Repérer le robot » sans pose, depuis le point
      principal (vague 4, section 11.2 : sa pose part dans /reperage/demander ; 1804 avec la pose
      (0, 0, 0) et repetition.pcd), map → base_link contre la vérité terrain, 2 m puis un quart de
      tour par /cmd_vel (donc par le pont et le faux G1) malgré la dérive, puis la relocalisation
      coupée (/faux_slam/panne muet) : perdu, puis repéré quand elle reprend
  critere_18_outils.py variante-b --api URL --lieu ID
      repère d'Unitree tourné (3 ; 9 ; 0,5) : repérage refusé avec une pose fausse donnée exprès,
      l'origine d'Unitree (502, sans map → odom) ; puis « Repérer le robot » sans pose réussit, car le
      robot est bien sur le point principal (2,5 ; 10 ; 0), avec la pose convertie dans 1804
  critere_18_outils.py restes --lieux DOSSIER
      aucun processus lancé avec ces lieux ne doit rester (code 1 sinon, avec la liste)

La vérité terrain est /g1_jumeau/odom (repère du monde Gazebo = map), jamais /odom (odométrie
du relais). Tous les /reperage/etat reçus sont validés par le schéma etat_reperage. Code de
sortie : 0 réussi, 1 échoué (le message dit pourquoi).
"""
import argparse
import json
import math
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "ws" / "src" / "g1_nav"))

MARQUE = (2.5, 10.0, 0.0)          # le point principal du demo (la salle accueil), où le robot apparaît
REPERE_B = (3.0, 9.0, 0.5)
TOLERANCE_M = 0.1
TOLERANCE_RAD = 0.05


class Echec(Exception):
    pass


def verifier(condition, message):
    if not condition:
        raise Echec(message)


PREFIXE = "critère 18"      # le critère 21 réutilise ces outils sous son nom


def dire(texte):
    print(f"[{PREFIXE}] {texte}", flush=True)


def ecart(a, b):
    return (math.hypot(a[0] - b[0], a[1] - b[1]), abs((a[2] - b[2] + math.pi) % (2 * math.pi) - math.pi))


# ---------------------------------------------------------------- API de l'Atelier

def appel(api, methode, chemin, corps=None, delai=60):
    """(code HTTP, JSON) d'un appel à l'API."""
    donnees = None if corps is None else json.dumps(corps).encode()
    r = urllib.request.Request(api + chemin, data=donnees, method=methode,
                               headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=delai) as reponse:
            return reponse.status, json.loads(reponse.read() or b"null")
    except urllib.error.HTTPError as e:
        texte = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(texte)
        except ValueError:
            return e.code, {"detail": texte}


def francais(reponse):
    """Une réponse d'erreur : un detail en français, sans trace Python."""
    detail = (reponse or {}).get("detail", "")
    return isinstance(detail, str) and detail and "Traceback" not in detail


# ---------------------------------------------------------------- écoute ROS 2

class Ecoute:
    """/reperage/etat (validé), /g1_jumeau/odom (vérité), TF, requêtes slam_operate ; /cmd_vel."""

    def __init__(self, avant_fil=None):
        """avant_fil : fonction appelée avec l'écoute avant le démarrage du fil (abonnements en plus)."""
        import rclpy
        import tf2_ros
        from geometry_msgs.msg import Twist
        from nav_msgs.msg import Odometry
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.qos import qos_profile_sensor_data
        from std_msgs.msg import String
        from unitree_api.msg import Request
        from atelier.lieu import valider_message
        self.valider = valider_message
        self.rclpy, self.String, self.Twist = rclpy, String, Twist
        self.contexte = rclpy.Context()
        rclpy.init(context=self.contexte)
        self.noeud = rclpy.create_node("critere_18", context=self.contexte)
        self.tampon = tf2_ros.Buffer()
        self.ecoute_tf = tf2_ros.TransformListener(self.tampon, self.noeud)
        self.etats, self.non_conformes, self.requetes = [], [], []
        self.verite = None
        self._verrou = threading.Lock()
        self.noeud.create_subscription(String, "/reperage/etat", self._sur_etat, 10)
        self.noeud.create_subscription(Odometry, "/g1_jumeau/odom", self._sur_verite, qos_profile_sensor_data)
        self.noeud.create_subscription(Request, "/api/slam_operate/request", self._sur_requete, 10)
        self.pub_vitesse = self.noeud.create_publisher(Twist, "/cmd_vel", 10)
        self.pub_panne = self.noeud.create_publisher(String, "/faux_slam/panne", 10)
        if avant_fil is not None:
            avant_fil(self)
        self.executeur = SingleThreadedExecutor(context=self.contexte)
        self.executeur.add_node(self.noeud)
        self._fin = threading.Event()
        self._fil = threading.Thread(target=self._tourner, daemon=True)
        self._fil.start()

    def _tourner(self):
        while not self._fin.is_set():
            try:
                self.executeur.spin_once(timeout_sec=0.05)
            except Exception:      # noqa: BLE001 : arrêt
                break

    def _sur_etat(self, msg):
        try:
            d = json.loads(msg.data)
        except ValueError:
            self.non_conformes.append(f"JSON illisible : {msg.data[:100]}")
            return
        erreurs = self.valider("etat_reperage", d)
        with self._verrou:
            self.etats.append(d)
            if erreurs:
                self.non_conformes.append("; ".join(erreurs))

    def _sur_verite(self, msg):
        from atelier.lieu import quaternion_vers_cap
        p = msg.pose.pose
        self.verite = (p.position.x, p.position.y, quaternion_vers_cap(p.orientation))

    def _sur_requete(self, msg):
        with self._verrou:
            self.requetes.append((msg.header.identity.api_id, msg.parameter))

    def dernier(self):
        with self._verrou:
            return self.etats[-1] if self.etats else None

    def attendre(self, condition, delai):
        fin = time.monotonic() + delai
        while time.monotonic() < fin:
            try:
                if condition():
                    return True
            except Exception:      # noqa: BLE001 : pas encore de données
                pass
            time.sleep(0.05)
        return False

    def tf(self, parent, enfant):
        from rclpy.time import Time
        from atelier.lieu import quaternion_vers_cap
        try:
            t = self.tampon.lookup_transform(parent, enfant, Time())
        except Exception:      # noqa: BLE001
            return None
        return (t.transform.translation.x, t.transform.translation.y, quaternion_vers_cap(t.transform.rotation))

    def rouler(self, vx=0.0, wz=0.0, duree=1.0):
        """/cmd_vel à 10 Hz pendant duree secondes, puis rien (le pont arrête le robot)."""
        m = self.Twist()
        m.linear.x, m.angular.z = float(vx), float(wz)
        fin = time.monotonic() + duree
        while time.monotonic() < fin:
            self.pub_vitesse.publish(m)
            time.sleep(0.1)

    def panne(self, texte):
        for _ in range(3):
            self.pub_panne.publish(self.String(data=texte))
            time.sleep(0.1)

    def fermer(self):
        self._fin.set()
        self._fil.join(timeout=3)
        self.executeur.shutdown()
        self.noeud.destroy_node()
        self.rclpy.try_shutdown(context=self.contexte)


def verifier_tf_et_verite(ecoute, quoi):
    """map → base_link à moins de 0,1 m et 0,05 rad de la vérité terrain."""
    verifier(ecoute.attendre(lambda: ecoute.tf("map", "base_link") is not None and ecoute.verite, 10),
             f"{quoi} : pas de TF map → base_link ou pas de vérité terrain /g1_jumeau/odom")
    time.sleep(0.5)
    d, a = ecart(ecoute.tf("map", "base_link"), ecoute.verite)
    dire(f"{quoi} : map → base_link à {d * 100:.1f} cm et {math.degrees(a):.1f}° de la vérité terrain")
    verifier(d < TOLERANCE_M and a < TOLERANCE_RAD,
             f"{quoi} : map → base_link à {d:.3f} m et {a:.3f} rad de la vérité (max {TOLERANCE_M} m, "
             f"{TOLERANCE_RAD} rad)")
    return d, a


def requete_1804(ecoute, avant):
    """Paramètres (data) de la première commande 1804 reçue après l'indice avant."""
    nouvelles = [p for api, p in ecoute.requetes[avant:] if api == 1804]
    verifier(nouvelles, "aucune commande 1804 sur /api/slam_operate/request")
    return json.loads(nouvelles[0])["data"]


def attendre_relais(api, ecoute, lieu, delai=120):
    """La répétition démarre : le relais publie /reperage/etat et l'API le voit."""
    verifier(ecoute.attendre(lambda: ecoute.dernier() is not None, delai),
             f"pas de /reperage/etat en {delai} s : le relais odom_vers_tf ne tourne pas")
    verifier(ecoute.attendre(lambda: ecoute.verite is not None, 30), "pas de vérité terrain /g1_jumeau/odom")

    def vu():
        _, e = appel(api, "GET", "/api/robot/etat")
        return e["mode"] == "repetition" and e["reperage"] is not None and not e["reperage"].get("perime")
    verifier(ecoute.attendre(vu, 30), "l'Atelier ne voit pas le repérage (GET /api/robot/etat)")


def demarrer(api, lieu):
    code, r = appel(api, "POST", "/api/simulation/demarrer", {"lieu": lieu, "etage": "rdc", "mode": "repetition"})
    verifier(code == 200, f"POST /api/simulation/demarrer (repetition) : {code} {r}")
    dire(f"répétition lancée : {', '.join(sorted(r['processus']))}")


def reperer(api, corps):
    debut = time.monotonic()
    code, r = appel(api, "POST", "/api/robot/reperer", corps, delai=40)
    return code, r, time.monotonic() - debut


# ---------------------------------------------------------------- variantes

def variante_a(args):
    ecoute = Ecoute()
    try:
        demarrer(args.api, args.lieu)
        attendre_relais(args.api, ecoute, args.lieu)
        # avant le repérage
        _, e = appel(args.api, "GET", "/api/robot/etat")
        verifier(not e["repere"] and e["etat"] == "non_repere", f"avant le repérage, l'état devrait être non repéré : {e}")
        verifier(e["marque"] == {"x": 2.5, "y": 10.0, "theta": 0.0}, f"pose de repérage : {e['marque']}")
        verifier((e["principal"] or {}).get("salle") == "accueil", f"point principal : {e['principal']}")
        verifier(ecoute.tf("map", "odom") is None, "TF map → odom publié avant le repérage")
        code, r = appel(args.api, "POST", "/api/guide/aller", {"cible": "b204"})
        verifier(code == 409 and francais(r), f"« Y aller » avant le repérage : {code} {r} (409 attendu)")
        dire(f"avant le repérage : non repéré, pas de map → odom, « Y aller » refusé ({r['detail'][:60]}…)")
        # repérage sans pose : depuis le point principal (vague 4), qui est aussi l'origine du repère figé
        avant = len(ecoute.requetes)
        code, r, duree = reperer(args.api, {"lieu": args.lieu, "etage": "rdc"})
        verifier(code == 200, f"POST /api/robot/reperer : {code} {r}")
        verifier(duree < 20.0, f"repérage en {duree:.1f} s (moins de 20 s attendu)")
        verifier(r["repere"] and r["precision_m"] is not None, f"repéré sans précision : {r}")
        dire(f"repéré en {duree:.2f} s : {r['message']}")
        d = requete_1804(ecoute, avant)
        verifier((d["x"], d["y"], d["q_z"], d["q_w"]) == (0.0, 0.0, 0.0, 1.0),
                 f"1804 : pose ({d['x']}, {d['y']}, q_z {d['q_z']}) au lieu de (0, 0, 0)")
        verifier(d["address"].endswith("repetition.pcd"), f"1804 : address {d['address']}")
        dire(f"1804 reçue par le faux service : pose (0, 0, 0), address {d['address']}")
        verifier_tf_et_verite(ecoute, "au point principal")
        correction_avant = ecoute.tf("map", "odom")
        # 2 m tout droit (vers x = 4,5), puis un quart de tour à gauche, par /cmd_vel → pont → faux G1
        depart = ecoute.verite
        ecoute.rouler(vx=0.3, duree=2.0 / 0.3)
        time.sleep(1.0)
        ecoute.rouler(wz=0.5, duree=(math.pi / 2) / 0.5)
        time.sleep(1.5)
        arrivee = ecoute.verite
        parcouru = math.hypot(arrivee[0] - depart[0], arrivee[1] - depart[1])
        tourne = abs((arrivee[2] - depart[2] + math.pi) % (2 * math.pi) - math.pi)
        dire(f"robot déplacé de {parcouru:.2f} m et tourné de {math.degrees(tourne):.0f}° (vérité terrain)")
        verifier(1.6 < parcouru < 2.4 and abs(tourne - math.pi / 2) < 0.3,
                 f"le robot n'a pas fait 2 m et 90° : {parcouru:.2f} m, {math.degrees(tourne):.0f}° "
                 "(pont ou faux G1 absents ?)")
        verifier_tf_et_verite(ecoute, "après 2 m et 90°")
        correction = ecoute.tf("map", "odom")
        change = ecart(correction, correction_avant)[0]
        dire(f"map → odom a changé de {change * 100:.1f} cm (l'odométrie du faux G1 dérive)")
        verifier(change > 0.02, f"map → odom n'a changé que de {change:.3f} m : la dérive n'est pas corrigée")
        # relocalisation coupée
        ecoute.panne("muet")
        debut = time.monotonic()
        verifier(ecoute.attendre(lambda: ecoute.dernier()["etat"] == "perdu", 6),
                 f"relocalisation coupée : pas d'état perdu ({ecoute.dernier()})")
        delai = time.monotonic() - debut
        verifier(delai < 4.0, f"perdu en {delai:.1f} s (moins de 4 s attendu)")
        _, e = appel(args.api, "GET", "/api/robot/etat")
        verifier(e["etat"] == "perdu" and not e["repere"], f"GET /api/robot/etat pendant la perte : {e}")
        dire(f"relocalisation coupée : perdu en {delai:.1f} s ({e['message'][:60]}…)")
        ecoute.panne("aucune")
        verifier(ecoute.attendre(lambda: ecoute.dernier()["etat"] == "repere", 6),
                 "relocalisation revenue : l'état ne revient pas à repéré")
        dire("relocalisation revenue : repéré de nouveau")
        verifier(not ecoute.non_conformes, f"/reperage/etat non conforme : {ecoute.non_conformes[:3]}")
        dire(f"{len(ecoute.etats)} messages /reperage/etat, tous conformes au schéma")
        return 0
    finally:
        ecoute.fermer()


def variante_b(args):
    from atelier.lieu import carte_vers_unitree, quaternion_vers_cap
    ecoute = Ecoute()
    try:
        demarrer(args.api, args.lieu)
        attendre_relais(args.api, ecoute, args.lieu)
        _, e = appel(args.api, "GET", "/api/robot/etat")
        # vague 4 (section 11.2) : la pose de repérage par défaut est le point principal, pas l'origine d'Unitree
        verifier(e["marque"] == {"x": 2.5, "y": 10.0, "theta": 0.0}, f"pose de repérage : {e['marque']}")
        # une pose fausse donnée exprès (l'origine d'Unitree, à 1,1 m du robot) : refusée
        code, r, _ = reperer(args.api, {"lieu": args.lieu, "etage": "rdc", "x": REPERE_B[0], "y": REPERE_B[1],
                                        "cap": REPERE_B[2]})
        verifier(code == 502 and francais(r), f"repérage à une pose fausse : {code} {r} (502 attendu)")
        dire(f"repérage à une pose fausse refusé (502) : {r['detail']}")
        time.sleep(1.0)
        verifier(ecoute.tf("map", "odom") is None, "map → odom publié après un repérage refusé")
        # sans pose : le robot est bien sur le point principal (2,5 ; 10 ; 0)
        avant = len(ecoute.requetes)
        code, r, duree = reperer(args.api, {"lieu": args.lieu, "etage": "rdc"})
        verifier(code == 200 and r["repere"], f"repérage depuis le point principal : {code} {r}")
        d = requete_1804(ecoute, avant)
        u = carte_vers_unitree(MARQUE, REPERE_B)
        cap = quaternion_vers_cap((d["q_x"], d["q_y"], d["q_z"], d["q_w"]))
        verifier(math.hypot(d["x"] - u[0], d["y"] - u[1]) < 1e-6 and abs(cap - u[2]) < 1e-6,
                 f"1804 : pose ({d['x']:.4f}, {d['y']:.4f}, {cap:.4f}) au lieu de {tuple(round(v, 4) for v in u)}")
        dire(f"repéré en {duree:.2f} s ; 1804 avec la pose convertie ({u[0]:.3f} ; {u[1]:.3f} ; {u[2]:.3f})")
        verifier_tf_et_verite(ecoute, "variante B")
        verifier(not ecoute.non_conformes, f"/reperage/etat non conforme : {ecoute.non_conformes[:3]}")
        return 0
    finally:
        ecoute.fermer()


def restes(args):
    """Processus encore vivants lancés avec ces lieux (variable ATELIER_LIEUX), sauf ce programme."""
    cible = f"ATELIER_LIEUX={args.lieux}".encode()
    trouves = []
    exclus = {os.getpid(), os.getppid()} | {int(p) for p in args.sauf}
    for d in Path("/proc").iterdir():
        if not d.name.isdigit() or int(d.name) in exclus:
            continue
        try:
            if cible in (d / "environ").read_bytes().split(b"\0"):
                ligne = (d / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace").strip()
                etat = (d / "stat").read_text().split(") ")[-1].split()[0]
                if etat != "Z":
                    trouves.append(f"{d.name} {ligne[:150]}")
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
    if trouves:
        print("Processus restants :\n  " + "\n  ".join(trouves))
        return 1
    print("Aucun processus restant.")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="critere_18_outils.py", description=__doc__.split("\n")[0])
    sous = p.add_subparsers(dest="action", required=True)
    for nom in ("variante-a", "variante-b"):
        s = sous.add_parser(nom)
        s.add_argument("--api", required=True)
        s.add_argument("--lieu", required=True)
    s = sous.add_parser("restes")
    s.add_argument("--lieux", required=True)
    s.add_argument("--sauf", nargs="*", default=[])
    args = p.parse_args(argv)
    try:
        return {"variante-a": variante_a, "variante-b": variante_b, "restes": restes}[args.action](args)
    except Echec as e:
        print(f"[critère 18] ÉCHEC : {e}", flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
