#!/usr/bin/env python3
"""Outils du critère 37, « Vérifier le robot » (vague 6, section 13.9 du plan) : agent Diagnostic.

  complement-robot
      un nœud qui complète le graphe du faux G1 comme le vrai robot : il publie /lf/sportmodestate et écoute
      /api/slam_operate/request (le service de cartographie) ; jusqu'à Ctrl+C ou SIGTERM ;
  critere-37 --api URL --faux FICHIER --cas DOSSIER [--sans-firefox]
      tout le critère, contre le faux G1 seul (services_arretes:=lidar_driver,unitree_slam) et l'Atelier lancé avec
      ATELIER_DIAGNOSTIC_FAUX=FICHIER ; chaque cas des vérifications système est un fichier de DOSSIER, copié dans
      FICHIER avant sa demande (le serveur le relit à chaque diagnostic). Code 0 réussi, 1 échoué, 77 en attente.

Jamais de son, de ssh, de ping ni de commande vers le vrai robot : le faux contexte répond à la place (et note
dans FICHIER.journal ce qui aurait été lancé), le ROS est celui du domaine du test (faux G1).
"""
import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

IDS_RESEAU_JETSON = {"cable", "adresse", "profil", "pc1", "jetson", "lidar", "jetson_ssh", "jetson_docker",
                     "jetson_image", "jetson_place", "jetson_horloge", "camera"}


class Echec(Exception):
    """Un point du critère qui ne passe pas (message en français)."""


def verifier(condition, message):
    if not condition:
        raise Echec(message)


def dire(texte):
    print(f"  {texte}", flush=True)


# ---------------------------------------------------------------- ROS 2

class Temoin:
    """Nœud du critère : change les services du faux G1 (/g1_jumeau/services), lit son état (/g1_jumeau/etat)."""

    def __init__(self):
        import rclpy
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.qos import QoSProfile, ReliabilityPolicy
        from std_msgs.msg import String
        self.rclpy = rclpy
        self.contexte = rclpy.Context()
        rclpy.init(context=self.contexte)
        self.noeud = rclpy.create_node("temoin_critere_37", context=self.contexte)
        self.String = String
        fiable = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE)
        self.pub_services = self.noeud.create_publisher(String, "/g1_jumeau/services", fiable)
        self.etat = None
        self.noeud.create_subscription(String, "/g1_jumeau/etat", self._recevoir, 10)
        self.executeur = SingleThreadedExecutor(context=self.contexte)
        self.executeur.add_node(self.noeud)
        self.fin = threading.Event()
        self.fil = threading.Thread(target=self._tourner, daemon=True)
        self.fil.start()

    def _tourner(self):
        while not self.fin.is_set() and self.contexte.ok():
            self.executeur.spin_once(timeout_sec=0.1)

    def _recevoir(self, msg):
        try:
            self.etat = (json.loads(msg.data), time.monotonic())
        except ValueError:
            pass

    def services(self, apres=None, delai=15.0):
        """Le champ services de /g1_jumeau/etat, reçu après l'instant apres (time.monotonic)."""
        fin = time.monotonic() + delai
        while time.monotonic() < fin:
            if self.etat is not None and (apres is None or self.etat[1] > apres):
                services = self.etat[0].get("robot", {}).get("services")
                verifier(isinstance(services, dict) and "switchs" in services,
                         "le faux G1 n'a pas encore le service robot_state de la vague 6 (g1_jumeau à recompiler)")
                return services
            time.sleep(0.1)
        raise Echec("pas de /g1_jumeau/etat : le faux G1 ne tourne pas")

    def changer(self, statuts):
        fin = time.monotonic() + 10
        while self.pub_services.get_subscription_count() < 1 and time.monotonic() < fin:
            time.sleep(0.05)
        self.pub_services.publish(self.String(data=json.dumps(statuts)))
        while time.monotonic() < fin:
            s = self.services(apres=time.monotonic() - 0.01)
            if all(s["services"].get(n) == v for n, v in statuts.items()):
                return s
        raise Echec(f"le faux G1 n'a pas pris les services {statuts}")

    def arreter(self):
        self.fin.set()
        self.fil.join(5)
        self.executeur.shutdown()
        self.noeud.destroy_node()
        self.rclpy.shutdown(context=self.contexte)


def complement_robot(_args):
    """Le reste du graphe du vrai robot autour du faux G1 : /lf/sportmodestate publié, slam_operate écouté."""
    import rclpy
    from rclpy.qos import QoSProfile, ReliabilityPolicy
    from unitree_api.msg import Request
    from unitree_go.msg import SportModeState
    rclpy.init()
    noeud = rclpy.create_node("complement_robot")
    pub = noeud.create_publisher(SportModeState, "/lf/sportmodestate", 10)
    noeud.create_subscription(Request, "/api/slam_operate/request", lambda m: None,
                              QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE))
    noeud.create_timer(0.5, lambda: pub.publish(SportModeState()))
    fin = threading.Event()
    signal.signal(signal.SIGTERM, lambda *a: fin.set())
    print("complément du robot prêt : /lf/sportmodestate publié, /api/slam_operate/request écouté", flush=True)
    try:
        while not fin.is_set() and rclpy.ok():
            rclpy.spin_once(noeud, timeout_sec=0.2)
    except KeyboardInterrupt:
        pass
    noeud.destroy_node()
    rclpy.try_shutdown()
    return 0


# ---------------------------------------------------------------- HTTP

def http(methode, url, corps=None, delai=30):
    """(statut, JSON) d'une demande à l'Atelier."""
    donnees = None if corps is None else json.dumps(corps).encode()
    req = urllib.request.Request(url, data=donnees, method=methode, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=delai) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


def diagnostic(api, mode):
    debut = time.monotonic()
    statut, d = http("GET", f"{api}/api/robot/diagnostic?mode={mode}")
    duree = time.monotonic() - debut
    verifier(statut == 200, f"GET /api/robot/diagnostic?mode={mode} : {statut} {d}")
    verifier(duree < 15.0, f"le diagnostic a pris {duree:.1f} s (15 s au plus)")
    from atelier.lieu import valider_donnees
    erreurs = valider_donnees("diagnostic", d)
    verifier(not erreurs, f"diagnostic non conforme au schéma : {erreurs}")
    return d, duree


def par_id(d):
    return {v["id"]: v for v in d["verifications"]}


def ids_etats(d):
    return [(v["id"], v["etat"]) for v in d["verifications"]]


# ---------------------------------------------------------------- les cas des vérifications système

def ecrire_cas(dossier):
    """Un fichier par cas : câble absent, connexion éteinte, tout bon."""
    from atelier.tests.test_diagnostic_communs import ecrire_faux, faux_systeme
    dossier = Path(dossier)
    dossier.mkdir(parents=True, exist_ok=True)
    cas = {"cable_absent": faux_systeme(cable=False, actif=False, adresse=None),
           "profil_inactif": faux_systeme(actif=False),
           "tout_bon": faux_systeme()}
    return {nom: ecrire_faux(dossier / f"{nom}.json", donnees) for nom, donnees in cas.items()}


def prendre_cas(cas, faux):
    shutil.copyfile(cas, faux)


def journal(faux):
    chemin = Path(str(faux) + ".journal")
    if not chemin.is_file():
        return []
    return [json.loads(x) for x in chemin.read_text(encoding="utf-8").splitlines() if x.strip()]


# ---------------------------------------------------------------- le critère

def partie_repetition(api, temoin):
    dire("1. répétition : services arrêtés vus par robot_state 1003")
    temoin.changer({"lidar_driver": 1, "unitree_slam": 1})
    d, duree = diagnostic(api, "repetition")
    v = par_id(d)
    verifier(v["services"]["etat"] == "probleme" and v["services"]["action"] == "demarrer-services",
             f"services : {v['services']}")
    apres = temoin.services(apres=time.monotonic())
    verifier(any(r["api"] == 1003 and r["parameter"] == "{}" for r in apres["requetes"]),
             f"le faux G1 n'a pas reçu 1003 avec {{}} : {apres['requetes']}")
    ignorees = {x["id"] for x in d["ignorees"]}
    verifier(IDS_RESEAU_JETSON <= ignorees, f"réseau et Jetson pas dans ignorees : {IDS_RESEAU_JETSON - ignorees}")
    dire(f"   OK en {duree:.1f} s : {v['services']['detail']} ; 1003 « {{}} » reçu ; "
         f"{len(ignorees)} vérifications sans objet ({', '.join(sorted(ignorees)[:3])}…)")
    return apres


def partie_action(api, temoin, avant):
    dire("2. « Démarrer les services de cartographie » : rien sans confirmation, puis la liste blanche seule")
    n = len(avant["switchs"])
    statut, r = http("POST", f"{api}/api/robot/diagnostic/demarrer-services", {"mode": "repetition"})
    verifier(statut == 409, f"sans « confirme » : {statut} au lieu de 409 ({r})")
    time.sleep(1.0)
    s = temoin.services(apres=time.monotonic())
    verifier(len(s["switchs"]) == n and s["appels"]["1001"] == avant["appels"]["1001"],
             f"un 1001 est parti sans confirmation : {s['switchs'][n:]}")
    dire(f"   sans confirmation : 409 « {r['detail'][:70]}… », aucun 1001")
    debut = time.monotonic()
    statut, r = http("POST", f"{api}/api/robot/diagnostic/demarrer-services", {"confirme": True, "mode": "repetition"},
                     delai=60)
    duree = time.monotonic() - debut
    verifier(statut == 200 and r.get("ok") is True, f"avec confirmation : {statut} {r}")
    s = temoin.services(apres=time.monotonic())
    nouveaux = [(x["name"], x["switch"]) for x in s["switchs"][n:]]
    verifier(nouveaux == [("lidar_driver", 1), ("unitree_slam", 1)], f"1001 reçus : {nouveaux}")
    verifier(s["nombre_interdits"] == 0 and s["interdits"] == [], f"interdits : {s['interdits']}")
    verifier(s["services"]["lidar_driver"] == 0 and s["services"]["unitree_slam"] == 0 and duree < 20.0,
             f"services pas actifs en 20 s : {s['services']} ({duree:.1f} s)")
    verifier(par_id(r["diagnostic"])["services"]["etat"] == "ok", "le diagnostic refait ne voit pas les services")
    d, _ = diagnostic(api, "repetition")
    verifier(par_id(d)["services"]["etat"] == "ok", f"services au diagnostic suivant : {par_id(d)['services']}")
    dire(f"   avec confirmation : exactement {nouveaux}, aucun interdit, actifs en {duree:.1f} s ; « {r['message']} »")


def partie_reel(api, faux, cas):
    dire("3. Réel avec les vérifications système simulées (rien vers le réseau du robot)")
    prendre_cas(cas["cable_absent"], faux)
    d, _ = diagnostic(api, "reel")
    v = par_id(d)["cable"]
    verifier(v["etat"] == "probleme" and v["conseil"], f"câble absent : {v}")
    dire(f"   câble absent : Problème, « {v['conseil']} »")
    prendre_cas(cas["profil_inactif"], faux)
    d, _ = diagnostic(api, "reel")
    v = par_id(d)["profil"]
    verifier(v["action"] == "retablir-cable", f"connexion éteinte : {v}")
    avant = len(journal(faux))
    statut, r = http("POST", f"{api}/api/robot/diagnostic/retablir-cable", {"confirme": True, "mode": "reel"})
    lancees = [x.get("commande") for x in journal(faux)[avant:] if x["genre"] == "commande"]
    verifier(statut == 200 and r.get("ok") is True, f"retablir-cable : {statut} {r}")
    verifier("nmcli connection up robot-g1" in lancees, f"commandes notées : {lancees}")
    dire(f"   connexion éteinte : action retablir-cable ; confirmée, elle « lance » {lancees[0]!r} (noté, rien de "
         "réel)")
    prendre_cas(cas["tout_bon"], faux)
    d, _ = diagnostic(api, "reel")
    verifier(d["etat"] == "ok", f"tout bon : état {d['etat']} ({[x for x in ids_etats(d) if x[1] != 'ok']})")
    dire(f"   tout bon : état ok ({d['resume']['ok']} vérifications, {d['message']})")
    reseau = [x for x in journal(faux) if x["genre"] in ("ping", "ssh")]
    verifier(all(x.get("adresse", "").startswith("192.168.123.") or x.get("hote") for x in reseau),
             "journal inattendu")
    return d


def partie_commande(api, faux, cas, route_tout_bon):
    dire("4. g1-diagnostic --json : mêmes vérifications que la route, code de sortie")
    env = dict(os.environ, ATELIER_DIAGNOSTIC_FAUX=str(faux))
    prendre_cas(cas["tout_bon"], faux)
    r = subprocess.run([str(RACINE / "bin" / "g1-diagnostic"), "--json"], capture_output=True, text=True,
                       timeout=60, env=env)
    verifier(r.stdout.strip().startswith("{"), f"g1-diagnostic --json : {r.stdout[-300:]} {r.stderr[-500:]}")
    d = json.loads(r.stdout)
    verifier(ids_etats(d) == ids_etats(route_tout_bon), f"tout bon : {ids_etats(d)} ≠ {ids_etats(route_tout_bon)}")
    verifier(r.returncode == 0, f"tout bon : code {r.returncode} au lieu de 0")
    prendre_cas(cas["cable_absent"], faux)
    route, _ = diagnostic(api, "reel")
    r = subprocess.run([str(RACINE / "bin" / "g1-diagnostic"), "--json"], capture_output=True, text=True,
                       timeout=60, env=env)
    d = json.loads(r.stdout)
    verifier(ids_etats(d) == ids_etats(route), f"câble absent : {ids_etats(d)} ≠ {ids_etats(route)}")
    verifier(r.returncode == 1, f"câble absent : code {r.returncode} au lieu de 1")
    dire(f"   mêmes ids et mêmes états que la route ({len(d['verifications'])}) ; code 0 tout bon, 1 câble absent")
    prendre_cas(cas["tout_bon"], faux)


def partie_firefox(api, temoin):
    dire("5. Firefox : accueil Réel avec « Répétition », la fenêtre, l'action confirmée dans la page, la barre")
    from atelier.tests import test_coque_communs as C
    from atelier.tests.test_serveur_navigateur import arreter_navigateur, demarrer_navigateur
    temoin.changer({"lidar_driver": 1, "unitree_slam": 1})
    gecko, nav = demarrer_navigateur()
    try:
        nav.taille(1366, 768)
        C.charger(nav, api + "/", C.ACCUEIL, "accueil")
        nav.js("localStorage.clear(); localStorage.setItem('atelier.lieu', 'demo');"
               "localStorage.setItem('atelier.mode', "
               "'reel'); localStorage.setItem('atelier.repetition', '1');")
        C.charger(nav, api + "/", "return !!document.querySelector('[data-role=zone-diagnostic-accueil] "
                                  "[data-role=verifier-robot]')", "bouton de l'accueil")
        nav.clic("[data-role=zone-diagnostic-accueil] [data-role=verifier-robot]")
        ligne = ("const v = document.querySelector('[data-role=diagnostic][data-occupe=non] "
                 "[data-verification=services]'); return v ? v.getAttribute('data-etat') : null")
        etat = nav.attendre(ligne, delai=20, message="fenêtre du diagnostic")
        verifier(etat == "probleme", f"services dans la fenêtre : {etat}")
        avant = len(temoin.services()["switchs"])
        nav.clic("[data-role=diagnostic] [data-action=demarrer-services]")
        nav.attendre("return !!document.querySelector('[data-role=confirmation]')", message="confirmation dans la page")
        verifier(len(temoin.services(apres=time.monotonic())["switchs"]) == avant, "un 1001 est parti avant « OK »")
        nav.clic("[data-role=confirmation] [data-role=confirmer]")
        nav.attendre(ligne.replace("return v ? v.getAttribute('data-etat') : null",
                                   "return v && v.getAttribute('data-etat') === 'ok'"), delai=40,
                     message="services démarrés dans la fenêtre")
        s = temoin.services(apres=time.monotonic())
        verifier([(x["name"], x["switch"]) for x in s["switchs"][avant:]] == [("lidar_driver", 1), ("unitree_slam", 1)],
                 f"1001 depuis Firefox : {s['switchs'][avant:]}")
        verifier(C.fenetres_natives(nav) == [], f"boîtes natives : {C.fenetres_natives(nav)}")
        dire("   accueil : services en Problème, confirmation dans la page, puis démarrés (deux 1001)")
        C.ouvrir_espace(nav, api, "repetition")
        nav.clic("[data-role=zone-diagnostic] [data-role=verifier-robot]")
        etat = nav.attendre(ligne, delai=20, message="fenêtre par la barre d'outils")
        verifier(etat == "ok", f"services par la barre d'outils : {etat}")
        erreurs = nav.js("return window.erreursAtelier")
        verifier(erreurs == [], f"window.erreursAtelier : {erreurs}")
        dire("   barre d'outils : la même fenêtre, services OK ; window.erreursAtelier vide")
    finally:
        arreter_navigateur(gecko, nav)


def critere_37(args):
    cas = ecrire_cas(args.cas)
    prendre_cas(cas["tout_bon"], args.faux)
    temoin = Temoin()
    try:
        avant = partie_repetition(args.api, temoin)
        partie_action(args.api, temoin, avant)
        route = partie_reel(args.api, args.faux, cas)
        partie_commande(args.api, args.faux, cas, route)
        if args.sans_firefox:
            dire("5. Firefox : sauté (--sans-firefox)")
        else:
            partie_firefox(args.api, temoin)
    except Echec as e:
        print(f"ÉCHEC : {e}", flush=True)
        return 1
    finally:
        temoin.arreter()
    return 0


def main(argv=None):
    a = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sous = a.add_subparsers(dest="commande", required=True)
    sous.add_parser("complement-robot")
    c = sous.add_parser("critere-37")
    c.add_argument("--api", required=True)
    c.add_argument("--faux", required=True)
    c.add_argument("--cas", required=True)
    c.add_argument("--sans-firefox", action="store_true")
    args = a.parse_args(argv)
    if args.commande == "complement-robot":
        return complement_robot(args)
    return critere_37(args)


if __name__ == "__main__":
    sys.exit(main())
