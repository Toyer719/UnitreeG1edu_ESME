#!/usr/bin/env python3
"""Outils du critère 30, équipe (section 7 du plan, critère 30 ; section 11.6).

  outils_equipe_e2e.py fichiers --api URL --lieu ID
      les exemples de personnalites.yaml, dialogues.yaml et camera.yaml sont valides ; trois fautes
      de chacun sont refusées (422) avec des messages en français ; puis chaque exemple est écrit
      et relu par l'API sur la copie du demo, et trois phrases s'essaient (sans robot)
  outils_equipe_e2e.py bout-en-bout --api URL --lieu ID [--delai 240]
      le nœud dialogue tourne, avec la simulation et la navigation : « bonjour » (envoyé par
      l'Atelier, POST /api/equipe/visiteur) → une réponse, sans guidage ; une phrase inconnue → le
      repli ; « je cherche la salle b204 » sur /visiteur/texte → /robot/dire (en français,
      conforme) et /guide/aller en JSON vers b204 → arrive à moins de 0,3 m (vérité : /odom) ;
      les événements du guide relayés vers /robot/dire sont affichés
  outils_equipe_e2e.py restes --lieux DOSSIER [--sauf PID...]
      aucun processus lancé avec ces lieux (variable ATELIER_LIEUX) ne doit rester

Code de sortie : 0 réussi, 1 échoué (le message dit pourquoi).
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

PHRASE = "je cherche la salle b204"
DEMANDE = {"cible": "b204", "accompagner": True, "source": "dialogue"}
SALLE = (21.0, 13.0)          # pose de b204 dans le demo
MOTS_ANGLAIS = ("is not", "required property", "additional properties", "does not match", "is too", "expected")


class Echec(Exception):
    pass


def verifier(condition, message):
    if not condition:
        raise Echec(message)


def dire(texte):
    print(f"[critère 30] {texte}", flush=True)


def appel(api, methode, chemin, corps=None, delai=30):
    """(code HTTP, JSON) d'un appel à l'API de l'Atelier."""
    donnees = None if corps is None else json.dumps(corps).encode()
    r = urllib.request.Request(api + chemin, data=donnees, method=methode, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=delai) as reponse:
            return reponse.status, json.loads(reponse.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


def en_francais(messages, fichier):
    """Chaque message commence par le nom du fichier et ne contient pas de tournure anglaise."""
    for m in messages:
        verifier(isinstance(m, str) and m.startswith(fichier), f"message sans le nom du fichier : {m!r}")
        verifier(not any(a in m.lower() for a in MOTS_ANGLAIS), f"message en anglais : {m!r}")


# ---------------------------------------------------------------- fichiers

FAUTES = {
    "personnalites": [
        ("personnalité active inconnue", lambda d: d.update(active="joyeux")),
        ("LED à 999", lambda d: d["personnalites"][0]["led"].update(g=999)),
        ("vitesse au-delà du pont", lambda d: d["personnalites"][1].update(vitesse_max=1.0)),
    ],
    "dialogues": [
        ("guider sans {salle}", lambda d: d["regles"][0]["motifs"].append("je cherche")),
        ("action inconnue", lambda d: d["regles"][1].update(action="danser")),
        ("sans repli", lambda d: d.pop("repli")),
    ],
    "camera": [
        ("périphérique hors de /dev", lambda d: d["camera"].update(peripherique="video0")),
        ("confiance à 1,5", lambda d: d["detection"].update(confiance_min=1.5)),
        ("position sans lacet", lambda d: d["camera"]["position"].pop("lacet")),
    ],
}


def fichiers(args):
    from atelier.lieu import equipe as E
    code, infos = appel(args.api, "GET", "/api/equipe")
    verifier(code == 200, f"GET /api/equipe : {code}")
    for quoi, fichier in E.FICHIERS_EQUIPE.items():
        exemple = infos["fichiers"][quoi]["exemple"]
        verifier(E.valider_equipe(quoi, exemple) == [], f"l'exemple de {fichier} est refusé")
        code, _ = appel(args.api, "GET", f"/api/lieux/{args.lieu}/{quoi}")
        verifier(code == 404, f"{fichier} existe déjà dans la copie ({code})")
        for nom, faute in FAUTES[quoi]:
            d = json.loads(json.dumps(exemple))
            faute(d)
            code, r = appel(args.api, "PUT", f"/api/lieux/{args.lieu}/{quoi}", d)
            verifier(code == 422, f"{fichier}, {nom} : accepté ({code})")
            verifier(r["detail"] == f"{fichier} n'a pas été enregistré : corrigez les points ci-dessous.",
                     f"{fichier}, {nom} : phrase inattendue {r['detail']!r}")
            verifier(r.get("erreurs"), f"{fichier}, {nom} : refus sans erreur détaillée")
            en_francais(r["erreurs"], fichier)
            dire(f"{fichier}, {nom} : refusé — {r['erreurs'][0]}")
        code, r = appel(args.api, "PUT", f"/api/lieux/{args.lieu}/{quoi}", exemple)
        verifier(code == 200 and r["enregistre"] == [fichier], f"{fichier} : écriture refusée ({code}) {r}")
        code, relu = appel(args.api, "GET", f"/api/lieux/{args.lieu}/{quoi}")
        verifier(code == 200 and relu == exemple, f"{fichier} : relu différent de l'exemple")
        dire(f"{fichier} : exemple valide, écrit puis relu à l'identique ; rapport : "
             f"{len(r['rapport']['equipe']['erreurs'])} erreur(s), "
             f"{len(r['rapport']['equipe']['avertissements'])} avertissement(s)")
    for phrase, action, cible in (("bonjour", "dire", None), (PHRASE, "guider", "b204"),
                                  ("quelle heure est-il", "repli", None)):
        code, r = appel(args.api, "POST", f"/api/lieux/{args.lieu}/dialogues/essayer", {"texte": phrase})
        verifier(code == 200 and r["action"] == action and (r["guide"] or {}).get("cible") == cible,
                 f"essai de « {phrase} » : {r}")
        dire(f"essai sans robot : « {phrase} » → {action}, « {r['reponse']} »")
    return 0


# ---------------------------------------------------------------- bout en bout

class Temoin:
    """Nœud rclpy dans un fil : publie /visiteur/texte ; garde /robot/dire, /guide/aller,
    /guide/etat, /guide/evenement et la dernière pose de /odom."""

    def __init__(self):
        import rclpy
        from nav_msgs.msg import Odometry
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.qos import qos_profile_sensor_data
        from std_msgs.msg import String
        from atelier.lieu import quaternion_vers_cap
        rclpy.init()
        self.rclpy, self.String = rclpy, String
        self.noeud = rclpy.create_node("e2e_equipe")
        self.verrou = threading.Lock()
        self.recus = {s: [] for s in ("/robot/dire", "/guide/aller", "/guide/etat", "/guide/evenement")}
        self.odom = None
        for sujet in self.recus:
            self.noeud.create_subscription(String, sujet, self._recepteur(sujet), 50)

        def odom(m):
            p = m.pose.pose
            self.odom = (p.position.x, p.position.y, quaternion_vers_cap(p.orientation))
        self.noeud.create_subscription(Odometry, "/odom", odom, qos_profile_sensor_data)
        self.pub = self.noeud.create_publisher(String, "/visiteur/texte", 10)
        self.executeur = SingleThreadedExecutor()
        self.executeur.add_node(self.noeud)
        self._fin = threading.Event()
        self._fil = threading.Thread(target=self._tourner, daemon=True)
        self._fil.start()

    def _tourner(self):
        while not self._fin.is_set():
            self.executeur.spin_once(timeout_sec=0.05)

    def _recepteur(self, sujet):
        def recevoir(msg):
            try:
                d = json.loads(msg.data)
            except ValueError:
                d = msg.data
            with self.verrou:
                self.recus[sujet].append((time.monotonic(), d))
        return recevoir

    def messages(self, sujet, depuis=0.0):
        with self.verrou:
            return [d for t, d in self.recus[sujet] if t >= depuis]

    def attendre(self, condition, delai):
        fin = time.monotonic() + delai
        while time.monotonic() < fin:
            v = condition()
            if v:
                return v
            time.sleep(0.05)
        return None

    def publier(self, texte):
        self.pub.publish(self.String(data=texte))

    def fermer(self):
        self._fin.set()
        self._fil.join(timeout=3)
        self.executeur.shutdown()
        self.noeud.destroy_node()
        self.rclpy.try_shutdown()


def _reponse(t, depuis, delai=8.0):
    return t.attendre(lambda: [m for m in t.messages("/robot/dire", depuis)
                               if isinstance(m, dict) and m.get("source") == "dialogue"], delai)


def bout_en_bout(args):
    from atelier.lieu import equipe as E
    from atelier.lieu import valider_message
    t = Temoin()
    try:
        verifier(t.attendre(lambda: t.pub.get_subscription_count() > 0, 30),
                 "le nœud dialogue n'écoute pas /visiteur/texte en 30 s")
        time.sleep(1.0)
        dialogues = E.exemple_equipe("dialogues")
        # « bonjour », envoyé par l'Atelier comme la reconnaissance vocale : une réponse, sans guidage
        t0 = time.monotonic()
        code, r = appel(args.api, "POST", "/api/equipe/visiteur", {"texte": "Bonjour !"})
        verifier(code == 200 and r["ecoute"] >= 1, f"POST /api/equipe/visiteur : {code} {r}")
        rep = _reponse(t, t0)
        verifier(rep, "pas de réponse à « Bonjour ! » sur /robot/dire")
        verifier(rep[0]["texte"] == dialogues["regles"][1]["reponse"], f"réponse inattendue : {rep[0]}")
        dire(f"« Bonjour ! » (par l'Atelier) → « {rep[0]['texte']} »")
        # une phrase inconnue : le repli
        t1 = time.monotonic()
        t.publier("Quel temps fera-t-il demain ?")
        rep = _reponse(t, t1)
        verifier(rep and rep[0]["texte"] == dialogues["repli"], f"pas de repli : {rep}")
        dire(f"« Quel temps fera-t-il demain ? » → le repli « {rep[0]['texte']} »")
        time.sleep(1.5)
        verifier(t.messages("/guide/aller", t0) == [], "/guide/aller publié sans demande de guidage")
        # l'exemple du plan
        t2 = time.monotonic()
        t.publier(PHRASE)
        rep = _reponse(t, t2)
        verifier(rep, f"pas de réponse à « {PHRASE} »")
        verifier(rep[0]["texte"] == "Je vous emmène à Salle B204. Suivez-moi !" and rep[0].get("langue") == "fr",
                 f"réponse inattendue : {rep[0]}")
        aller = t.attendre(lambda: t.messages("/guide/aller", t2), 5.0)
        verifier(aller == [DEMANDE], f"/guide/aller inattendu : {aller}")
        dire(f"« {PHRASE} » → /robot/dire « {rep[0]['texte']} » et /guide/aller {json.dumps(aller[0])}")
        # le guide y va
        fin = t2 + args.delai
        vus = []
        arrive = None
        while time.monotonic() < fin:
            for e in t.messages("/guide/etat", t2):
                if isinstance(e, dict) and (not vus or vus[-1] != (e.get("etat"), e.get("cible"))):
                    vus.append((e.get("etat"), e.get("cible")))
            if vus and vus[-1] == ("arrive", "b204"):
                arrive = time.monotonic()
                break
            if vus and vus[-1][0] == "echec":
                break
            time.sleep(0.1)
        dire("états du guide : " + " → ".join(f"{e} ({c})" for e, c in vus))
        verifier(arrive is not None, f"le guide n'est pas arrivé à b204 en {args.delai:g} s")
        pose = t.odom
        verifier(pose is not None, "pas de /odom")
        d = math.hypot(pose[0] - SALLE[0], pose[1] - SALLE[1])
        dire(f"arrivé en {arrive - t2:.0f} s : robot en ({pose[0]:.2f} ; {pose[1]:.2f}), {d:.3f} m de b204")
        verifier(d <= 0.3, f"le robot est à {d:.2f} m de b204 (0,3 m au plus)")
        # les phrases dites : toutes conformes ; les événements du guide relayés (s'il en publie)
        time.sleep(1.0)
        dites = t.messages("/robot/dire", t0)
        for m in dites:
            verifier(isinstance(m, dict) and valider_message("robot_dire", m) == [], f"/robot/dire non conforme : {m}")
        evenements = [e.get("code") for e in t.messages("/guide/evenement", t2) if isinstance(e, dict)]
        relayes = [m.get("code") for m in dites if m.get("source") == "guide"]
        if evenements:
            dire(f"événements du guide : {', '.join(evenements)} ; relayés vers /robot/dire : {', '.join(relayes)}")
            attendus = [c for c in evenements if c != "depart"]
            verifier(all(c in relayes for c in attendus), f"événements non relayés : {attendus} / {relayes}")
        else:
            dire("le guide ne publie pas (encore) /guide/evenement : relais non vérifié ici (tests de g1_equipe)")
        dire(f"{len(dites)} phrases sur /robot/dire, toutes conformes au schéma robot_dire")
        return 0
    finally:
        t.fermer()


# ---------------------------------------------------------------- processus restants

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
    p = argparse.ArgumentParser(prog="outils_equipe_e2e.py", description=__doc__.split("\n")[0])
    sous = p.add_subparsers(dest="action", required=True)
    s = sous.add_parser("fichiers")
    s.add_argument("--api", required=True)
    s.add_argument("--lieu", required=True)
    s = sous.add_parser("bout-en-bout")
    s.add_argument("--api", required=True)
    s.add_argument("--lieu", required=True)
    s.add_argument("--delai", type=float, default=240.0)
    s = sous.add_parser("restes")
    s.add_argument("--lieux", required=True)
    s.add_argument("--sauf", nargs="*", default=[])
    args = p.parse_args(argv)
    action = {"fichiers": fichiers, "bout-en-bout": bout_en_bout, "restes": restes}[args.action]
    try:
        return action(args)
    except Echec as e:
        dire(f"ÉCHEC : {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
