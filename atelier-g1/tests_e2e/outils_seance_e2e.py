#!/usr/bin/env python3
"""Outils du critère 38, la boîte noire et le rapport de séance (section 13.9 du plan) : agent Boîte noire.

  outils_seance_e2e.py principal --api URL --lieu ID --seances DOSSIER
      1. POST /api/seance/demarrer {mode: repetition, ouverture: auto} : dossier, seance.json conforme (ouverte),
         lieu/, l'enregistreur en route ; /ws/etat a seance ; Firefox sans fenêtre : le badge [data-role=seance] ;
      2. répétition par l'Atelier (Gazebo --jumeau, faux slam_operate, navigation), repérage, Nav2 actif ;
      3. « Y aller » b204 (arrivée ; l'enregistreur mesuré pendant le trajet : moins de 15 % d'un cœur), un
         second « Y aller » (CDI), ARRÊT en route (réponse en moins de 1 s), « Débloquer », « Y aller » accueil ;
      4. un /cmd_vel publié par l'outil hors de toute demande (5 s, le pont débloqué) ;
      5. POST /api/seance/arreter : fermee ; le bag (ros2 bag info) a /guide/etat, /pont/etat, /reperage/etat,
         /api/sport/request, /cmd_vel, aucun nuage ni image, /state_estimator/odom_pelvis à 10 Hz au plus ; chaque
         demande est une ligne conforme de actions.jsonl ; en moins de 60 s, rapport.json, rapport.md, rapport.html
         et trajets.png : deux trajets au moins (arrivé, et interrompu par l'ARRÊT), une distance non nulle, un
         arrêt d'urgence, la batterie de début et de fin, l'anomalie « mouvement sans demande » ;
      6. POST /api/simulation/arreter.
  outils_seance_e2e.py jetson --seances DOSSIER --bin DOSSIER --trace FICHIER
      l'arrêt de la navigation du robot appelle « g1-jetson journal » avant « g1-jetson arreter » : le fichier est
      dans journaux/jetson/ et dans le manifeste (Atelier dans ce processus, faux g1-jetson de ATELIER_BIN : le
      mode robot ne démarre pas pendant les essais, G1_SLAM_FAUX=1, il est donc posé à la main).
  outils_seance_e2e.py garde-fou --api URL --seances DOSSIER
      Atelier lancé avec ATELIER_SEANCE_PLACE_MIN_GO énorme : l'enregistrement s'arrête proprement (coupe, message),
      la séance reste ouverte (badge « coupe ») et les actions continuent ; puis « Terminer la séance ».
  outils_seance_e2e.py plantage-avant --api URL --seances DOSSIER
      ouvre une séance et publie quelques sujets ; écrit l'id de la séance sur la sortie (dernière ligne).
  outils_seance_e2e.py plantage-apres --api URL --seances DOSSIER --seance ID
      après le SIGKILL de l'Atelier et sa relance : l'enregistreur a fermé son bag seul, la séance est
      « interrompue », son bag se lit (ros2 bag info), son rapport existe ; aucune séance nouvelle n'est ouverte.
  outils_seance_e2e.py exporter --seances DOSSIER --seance ID --sortie F.zip
      g1-seance exporter : un .zip avec seance.json, actions.jsonl, rapport.*, bag/ ; g1-seance liste la montre.
  outils_seance_e2e.py restes --seances DOSSIER
      aucun enregistreur ni rapport de la boîte noire ne doit rester (code 1 sinon).
Code de sortie : 0 réussi, 1 échoué (le message dit pourquoi), 77 en attente (une pièce manque).
"""
import argparse
import json
import math
import os
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ICI = Path(__file__).resolve().parent
RACINE = ICI.parent
sys.path.insert(0, str(ICI))
sys.path.insert(0, str(RACINE))

from critere_18_outils import Echec, Ecoute, appel, attendre_relais, demarrer, reperer, verifier  # noqa: E402

EN_ATTENTE = 77
DELAI_TRAJET_S = 240.0
CPU_MAX = 0.15
SUJETS_ATTENDUS = ("/guide/etat", "/pont/etat", "/reperage/etat", "/api/sport/request", "/cmd_vel")
CODES = []


def dire(texte):
    print(f"[critère 38] {texte}", flush=True)


def api(a, methode, chemin, corps=None, delai=90):
    code, r = appel(a, methode, chemin, corps, delai=delai)
    CODES.append((methode, chemin, code))
    verifier(code != 500, f"{methode} {chemin} : erreur 500 {r}")
    return code, r


def attendre(condition, delai, pas=0.2):
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        try:
            if condition():
                return True
        except Exception:      # noqa: BLE001 : pas encore de données
            pass
        time.sleep(pas)
    try:
        return bool(condition())
    except Exception:      # noqa: BLE001
        return False


def manifeste(seances, ident):
    return json.loads((Path(seances) / ident / "seance.json").read_text(encoding="utf-8"))


def actions(seances, ident):
    chemin = Path(seances) / ident / "actions.jsonl"
    return [json.loads(x) for x in chemin.read_text(encoding="utf-8").splitlines()] if chemin.is_file() else []


def cpu_processus(pid):
    """Secondes de processeur (utilisateur + système) consommées par un processus."""
    champs = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[-1].split()
    return (int(champs[11]) + int(champs[12])) / os.sysconf("SC_CLK_TCK")


def ws_etat(a):
    """Un message de /ws/etat."""
    from websockets.sync.client import connect
    with connect(a.replace("http://", "ws://") + "/ws/etat", open_timeout=10) as ws:
        return json.loads(ws.recv(timeout=10))


def attendre_rapport(a, ident, delai=60.0):
    debut = time.monotonic()
    ok = attendre(lambda: api(a, "GET", f"/api/seances/{ident}")[1]["rapport"]["etat"] in ("pret", "echec"), delai, 0.5)
    m = api(a, "GET", f"/api/seances/{ident}")[1]
    verifier(ok and m["rapport"]["etat"] == "pret", f"rapport pas prêt en {delai:.0f} s : {m['rapport']}")
    return time.monotonic() - debut


def verifier_bag(dossier_bag):
    """ros2 bag info lisible ; les sujets attendus ; aucun nuage ni image ; l'odométrie du robot à 10 Hz au plus."""
    from atelier.lieu.seance import TYPES_JAMAIS
    from atelier.seance.lecture import infos_bag
    r = subprocess.run(["ros2", "bag", "info", str(dossier_bag)], capture_output=True, text=True, timeout=120)
    verifier(r.returncode == 0, f"ros2 bag info {dossier_bag} : code {r.returncode} {r.stderr[-300:]}")
    infos = infos_bag(dossier_bag)
    sujets = infos["sujets"]
    manque = [s for s in SUJETS_ATTENDUS if not sujets.get(s, {}).get("nombre")]
    verifier(not manque, f"sujets absents du bag : {manque} (présents : {sorted(sujets)})")
    interdits = {s: v["type"] for s, v in sujets.items() if v["type"] in TYPES_JAMAIS}
    verifier(not interdits, f"nuages ou images dans le bag : {interdits}")
    verifier(all(s in r.stdout for s in SUJETS_ATTENDUS), "ros2 bag info ne liste pas tous les sujets attendus")
    pelvis = sujets.get("/state_estimator/odom_pelvis")
    verifier(pelvis and pelvis["nombre"] > 10, f"pas d'odométrie du robot dans le bag : {pelvis}")
    frequence = pelvis["nombre"] / max(1e-6, pelvis["fin"] - pelvis["debut"])
    verifier(frequence <= 10.0, f"/state_estimator/odom_pelvis à {frequence:.2f} Hz dans le bag (10 Hz au plus)")
    dire(f"bag : {infos['messages']} messages, {infos['octets'] / 1e6:.1f} Mo, {len(sujets)} sujets ; odométrie du "
         f"robot à {frequence:.2f} Hz ; aucun nuage ni image ; ros2 bag info le lit")
    return infos


# ---------------------------------------------------------------- 1 à 6 : la séance principale

def firefox_badge(a, lieu):
    """Le badge de la séance dans la barre d'outils, en Réel (répétition)."""
    import pytest
    from atelier.tests import test_coque_communs as C
    from atelier.tests.test_serveur_navigateur import arreter_navigateur, demarrer_navigateur
    try:
        gecko, nav = demarrer_navigateur()
    except pytest.skip.Exception as e:
        raise PasPossible(f"Firefox sans fenêtre indisponible ({e})") from None
    try:
        nav.taille(1600, 900)
        C.ouvrir_espace(nav, a, "repetition", lieu=lieu)
        etat = nav.attendre("const b = document.querySelector('[data-role=seance]');"
                            "return b && !b.hidden ? b.getAttribute('data-etat') : null", delai=20,
                            message="badge de la séance")
        texte = nav.js("return document.querySelector('[data-role=seance]').textContent")
        verifier(etat == "enregistrement" and "Enregistrement" in texte, f"badge : {etat} « {texte} »")
        verifier(nav.js("return window.erreursAtelier || []") == [], "erreurs dans la page")
        dire(f"Firefox : badge « {texte.strip()} » (data-etat={etat}) dans la barre d'outils, en répétition")
    finally:
        arreter_navigateur(gecko, nav)


class PasPossible(Exception):
    pass


def principal(args):
    from atelier.lieu import valider_donnees
    from critere_19_outils import Observateur, aller
    seances = Path(args.seances)
    # 1. la séance
    code, r = api(args.api, "POST", "/api/seance/demarrer", {"mode": "repetition", "lieu": args.lieu, "etage": "rdc",
                                                             "ouverture": "auto"})
    verifier(code == 200, f"POST /api/seance/demarrer : {code} {r}")
    m = r["seance"]
    ident = m["id"]
    dossier = seances / ident
    verifier(dossier.is_dir() and (dossier / "seance.json").is_file(), f"pas de dossier de séance {dossier}")
    verifier(valider_donnees("seance", manifeste(seances, ident)) == [], "seance.json non conforme")
    verifier(m["etat"] == "ouverte" and (dossier / "lieu" / "salles.yaml").is_file(), f"séance : {m}")
    verifier(attendre(lambda: manifeste(seances, ident)["enregistrement"]["etat"] == "en_cours", 30),
             f"l'enregistreur ne tourne pas : {manifeste(seances, ident)['enregistrement']}")
    pid = manifeste(seances, ident)["enregistrement"]["pid"]
    verifier(pid and Path(f"/proc/{pid}").exists(), f"processus de l'enregistreur introuvable ({pid})")
    d = ws_etat(args.api)
    verifier(d.get("seance") and d["seance"]["id"] == ident and d["seance"]["badge"] == "enregistrement",
             f"/ws/etat : seance = {d.get('seance')}")
    dire(f"séance {ident} ouverte : seance.json conforme, lieu/ copié, enregistreur en route (pid {pid}), "
         "/ws/etat a la séance")
    firefox_badge(args.api, args.lieu)
    # 2. la répétition, le repérage, Nav2
    ecoute = Ecoute()
    obs = Observateur()
    try:
        demarrer(args.api, args.lieu)
        attendre_relais(args.api, ecoute, args.lieu)
        verifier(obs.attendre_pret(30), "pas de vérité terrain ou de /pont/etat")
        code, r, duree = reperer(args.api, {"lieu": args.lieu, "etage": "rdc"})
        verifier(code == 200 and r.get("repere"), f"POST /api/robot/reperer : {code} {r}")
        verifier(attendre(obs.nav2_actif, 120, 0.5), "Nav2 (bt_navigator) n'est pas actif")
        dire(f"répétition lancée, robot repéré en {duree:.1f} s, Nav2 actif")
        # 3. « Y aller » b204, avec la mesure du processeur de l'enregistreur pendant le trajet
        cpu0, t0 = cpu_processus(pid), time.monotonic()
        duree_b204, ecart, _, _ = aller(args.api, obs, args.lieu, "b204", DELAI_TRAJET_S)
        cpu = (cpu_processus(pid) - cpu0) / (time.monotonic() - t0)
        dire(f"b204 atteinte en {duree_b204:.0f} s ; enregistreur : {cpu * 100:.1f} % d'un cœur pendant le trajet")
        verifier(cpu < CPU_MAX, f"l'enregistreur prend {cpu * 100:.1f} % d'un cœur pendant le trajet "
                                f"({CPU_MAX * 100:.0f} % au plus)")
        # un second « Y aller », puis l'ARRÊT en route
        x0, y0, _ = obs.pose()
        code, r = api(args.api, "POST", "/api/guide/aller", {"cible": "cdi"})
        verifier(code == 200, f"POST /api/guide/aller cdi : {code} {r}")
        verifier(attendre(lambda: math.dist(obs.pose()[:2], (x0, y0)) > 1.0, 90),
                 "le robot ne part pas vers le CDI")
        t = time.monotonic()
        code, r = api(args.api, "POST", "/api/arret", {"mode": "repetition", "raison": "critère 38"}, delai=5)
        reponse = time.monotonic() - t
        verifier(code == 200 and r.get("verrou") is True, f"POST /api/arret : {code} {r}")
        verifier(reponse < 1.0, f"POST /api/arret a répondu en {reponse:.2f} s pendant le trajet (moins de 1 s)")
        verifier(attendre(lambda: obs.guide_depuis(t)[-1]["etat"] == "attente", 10), "le guide ne s'arrête pas")
        dire(f"ARRÊT en route vers le CDI : réponse en {reponse:.2f} s, guide en attente, robot bloqué")
        time.sleep(2.0)
        code, r = api(args.api, "POST", "/api/arret/debloquer", {})
        verifier(code == 200 and r.get("verrou") is False, f"POST /api/arret/debloquer : {code} {r}")
        time.sleep(1.0)
        aller(args.api, obs, args.lieu, "accueil", DELAI_TRAJET_S)
        # 4. un /cmd_vel hors de toute demande
        time.sleep(2.0)
        xa, ya, _ = obs.pose()
        obs.cmd_vel_pendant((0.25, 0.0, 0.0), 5.0)
        time.sleep(2.0)
        bouge = math.dist(obs.pose()[:2], (xa, ya))
        verifier(bouge > 0.5, f"le /cmd_vel du test n'a fait bouger le robot que de {bouge:.2f} m")
        dire(f"/cmd_vel publié par le test pendant 5 s, hors de toute demande : le robot a fait {bouge:.2f} m")
    finally:
        ecoute.fermer()
        obs.fermer()
    # 5. « Terminer la séance », le bag, le journal des actions, le rapport
    code, r = api(args.api, "POST", "/api/seance/arreter", {})
    verifier(code == 200 and r["seance"]["etat"] == "fermee", f"POST /api/seance/arreter : {code} {r}")
    m = manifeste(seances, ident)
    verifier(valider_donnees("seance", m) == [] and m["enregistrement"]["etat"] == "arrete",
             f"manifeste après la fermeture : {m['enregistrement']}")
    verifier(not Path(f"/proc/{pid}").exists(), "l'enregistreur tourne encore après « Terminer la séance »")
    verifier_bag(dossier / "bag")
    lignes = actions(seances, ident)
    fautes = [x for x in lignes if valider_donnees("action_seance", x)]
    verifier(not fautes, f"lignes non conformes dans actions.jsonl : {fautes[:2]}")
    genres = [x["genre"] for x in lignes]
    for g in ("seance", "lancer", "reperer", "y_aller", "arret", "debloquer"):
        verifier(g in genres, f"genre « {g} » absent du journal des actions ({genres})")
    verifier(genres.count("y_aller") == 3, f"trois « Y aller » attendus dans le journal : {genres}")
    dire(f"journal des actions : {len(lignes)} lignes conformes ({', '.join(dict.fromkeys(genres))})")
    duree = attendre_rapport(args.api, ident, 60.0)
    for nom in ("rapport.json", "rapport.md", "rapport.html", "trajets.png"):
        verifier((dossier / nom).is_file(), f"{nom} absent")
    rapport = json.loads((dossier / "rapport.json").read_text(encoding="utf-8"))
    trajets = rapport["trajets"]
    resultats = [t["resultat"] for t in trajets]
    verifier(len(trajets) >= 2 and "arrive" in resultats, f"trajets : {resultats}")
    interrompus = [t for t in trajets if t["resultat"] == "interrompu" and (t.get("cause") or "").startswith("ARRÊT")]
    vus = [(t["nom"], t["resultat"], t["cause"]) for t in trajets]
    verifier(interrompus, f"pas de trajet interrompu par l'ARRÊT : {vus}")
    verifier(sum(t["distance_m"] for t in trajets) > 5.0, "distance des trajets nulle")
    genres_a = [a["genre"] for a in rapport["anomalies"]]
    verifier("arret_urgence" in genres_a, f"pas d'arrêt d'urgence dans les anomalies : {genres_a}")
    verifier("mouvement_sans_demande" in genres_a, f"le mouvement sans demande n'est pas vu : {genres_a}")
    b = rapport["batterie"]
    verifier(b["debut"] is not None and b["fin"] is not None, f"batterie : {b}")
    import urllib.request
    with urllib.request.urlopen(f"{args.api}/api/seances/{ident}/rapport", timeout=30) as reponse:
        page = reponse.read().decode("utf-8")
        verifier(reponse.status == 200 and reponse.headers["content-type"].startswith("text/html")
                 and "Rapport de séance du" in page, f"GET /api/seances/{ident}/rapport : {reponse.status}")
    dire(f"rapport prêt en {duree:.0f} s : {len(trajets)} trajets ({', '.join(resultats)}), "
         f"{sum(t['distance_m'] for t in trajets):.1f} m, batterie {b['debut']} → {b['fin']} %, anomalies "
         f"{', '.join(dict.fromkeys(genres_a))}")
    # 6. fin de la répétition
    code, _ = api(args.api, "POST", "/api/simulation/arreter")
    verifier(code == 200, "POST /api/simulation/arreter refusé")
    print(f"SEANCE {ident}", flush=True)
    return 0


# ---------------------------------------------------------------- le journal du Jetson

def jetson(args):
    os.environ["ATELIER_BIN"] = args.bin
    os.environ["ATELIER_SEANCES"] = args.seances
    from fastapi.testclient import TestClient
    from atelier.serveur.main import creer_app
    app = creer_app(ros=False)
    with TestClient(app) as c:
        code = c.post("/api/seance/demarrer", json={"mode": "reel", "ouverture": "manuel"})
        verifier(code.status_code == 200, f"POST /api/seance/demarrer : {code.status_code} {code.text[:200]}")
        ident = code.json()["seance"]["id"]
        # la navigation du robot « tourne » (le mode robot ne démarre pas pendant les essais : G1_SLAM_FAUX=1)
        app.state.atelier.simulation = {"lieu": None, "etage": None, "dossier": "", "monde": None,
                                        "debut": time.time(), "mode": "robot", "en_cours": True, "avertissements": []}
        r = c.post("/api/simulation/arreter")
        verifier(r.status_code == 200, f"POST /api/simulation/arreter : {r.status_code} {r.text[:200]}")
        trace = Path(args.trace).read_text(encoding="utf-8").splitlines()
        verifier(trace[:2] == ["journal --lignes 100000", "arreter"], f"appels de g1-jetson : {trace}")
        m = manifeste(args.seances, ident)
        (j,) = m["jetson"]
        fichier = Path(args.seances) / ident / j["fichier"]
        verifier(j["raison"] == "avant_arret" and j["ok"] and fichier.is_file()
                 and j["fichier"].startswith("journaux/jetson/"), f"journal du Jetson : {j}")
        verifier("journal du conteneur" in fichier.read_text(encoding="utf-8"), "journal du conteneur vide")
        c.post("/api/seance/arreter")
    dire(f"arrêt de la navigation du robot : « g1-jetson journal » puis « g1-jetson arreter » ; {j['fichier']} "
         f"({j['octets']} octets) dans le manifeste")
    return 0


# ---------------------------------------------------------------- le garde-fou de la place libre

def garde_fou(args):
    code, r = api(args.api, "POST", "/api/seance/demarrer", {"mode": "repetition", "ouverture": "auto"})
    verifier(code == 200, f"POST /api/seance/demarrer : {code} {r}")
    ident = r["seance"]["id"]
    verifier(attendre(lambda: manifeste(args.seances, ident)["enregistrement"]["etat"] == "coupe", 30),
             f"l'enregistrement ne s'arrête pas : {manifeste(args.seances, ident)['enregistrement']}")
    e = manifeste(args.seances, ident)["enregistrement"]
    verifier((e.get("message") or "").startswith("Enregistrement arrêté : il ne reste que"), f"message : {e}")
    seance = api(args.api, "GET", "/api/seance")[1]["seance"]
    verifier(seance and seance["id"] == ident and seance["etat"] == "ouverte",
             f"la séance n'est plus ouverte : {seance}")
    verifier(ws_etat(args.api)["seance"]["badge"] == "coupe", "le badge ne dit pas « coupe »")
    avant = len(actions(args.seances, ident))
    api(args.api, "POST", "/api/arret", {"mode": "simu", "raison": "critère 38, garde-fou"})
    verifier(attendre(lambda: len(actions(args.seances, ident)) > avant, 10), "l'action n'est pas notée")
    verifier(actions(args.seances, ident)[-1]["genre"] == "arret", "dernière action : pas l'ARRÊT")
    code, r = api(args.api, "POST", "/api/seance/arreter", {})
    verifier(code == 200 and r["seance"]["enregistrement"]["etat"] == "coupe", f"fermeture : {r}")
    dire(f"place libre trop faible : enregistrement coupé proprement (« {e['message'][:70]}… »), séance restée "
         "ouverte, actions notées, puis terminée")
    return 0


# ---------------------------------------------------------------- le plantage

def plantage_avant(args):
    import rclpy
    from nav_msgs.msg import Odometry
    from std_msgs.msg import String
    code, r = api(args.api, "POST", "/api/seance/demarrer", {"mode": "repetition", "ouverture": "auto"})
    verifier(code == 200, f"POST /api/seance/demarrer : {code} {r}")
    ident = r["seance"]["id"]
    verifier(attendre(lambda: manifeste(args.seances, ident)["enregistrement"]["etat"] == "en_cours", 30),
             "l'enregistreur ne tourne pas")
    contexte = rclpy.Context()
    rclpy.init(context=contexte)
    noeud = rclpy.create_node("e2e_critere_38_plantage", context=contexte)
    guide = noeud.create_publisher(String, "/guide/etat", 10)
    odom = noeud.create_publisher(Odometry, "/odom", 10)
    try:
        fin = time.monotonic() + 6.0
        i = 0
        while time.monotonic() < fin:
            m = Odometry()
            m.pose.pose.position.x = 0.02 * i
            m.pose.pose.orientation.w = 1.0
            odom.publish(m)
            if i % 10 == 0:
                guide.publish(String(data=json.dumps({"etat": "attente", "cible": None, "reste_m": None,
                                                      "itineraire": []})))
            i += 1
            time.sleep(0.02)
        verifier(attendre(lambda: (json.loads((Path(args.seances) / ident / "enregistrement.json").read_text())
                                   .get("messages") or 0) > 5, 10), "rien n'est enregistré")
    finally:
        noeud.destroy_node()
        rclpy.try_shutdown(context=contexte)
    dire(f"séance {ident} ouverte, sujets enregistrés : l'Atelier va être tué (SIGKILL)")
    print(f"SEANCE {ident}", flush=True)
    return 0


def plantage_attente_enregistreur(args):
    """Juste après le SIGKILL de l'Atelier : l'enregistreur orphelin ferme son bag et s'arrête seul."""
    etat = json.loads((Path(args.seances) / args.seance / "enregistrement.json").read_text())
    pid = etat["pid"]
    verifier(attendre(lambda: not Path(f"/proc/{pid}").exists(), 10),
             f"l'enregistreur (pid {pid}) tourne encore 10 s après la mort de l'Atelier")
    etat = json.loads((Path(args.seances) / args.seance / "enregistrement.json").read_text())
    verifier(etat["etat"] == "arrete" and "sans fermer la séance" in (etat.get("message") or ""),
             f"état de l'enregistreur : {etat}")
    verifier((Path(args.seances) / args.seance / "bag" / "metadata.yaml").is_file(), "bag non fermé (pas de metadata)")
    dire("l'Atelier tué : l'enregistreur a fermé son bag proprement et s'est arrêté seul")
    return 0


def plantage_apres(args):
    ident = args.seance
    verifier(attendre(lambda: manifeste(args.seances, ident)["etat"] == "interrompue", 60),
             f"la séance n'est pas « interrompue » : {manifeste(args.seances, ident)['etat']}")
    duree = attendre_rapport(args.api, ident, 90.0)
    m = manifeste(args.seances, ident)
    from atelier.lieu import valider_donnees
    verifier(m["fermeture"] == "plantage" and valider_donnees("seance", m) == [], f"manifeste : {m}")
    from atelier.seance.lecture import infos_bag
    infos = infos_bag(Path(args.seances) / ident / "bag")
    verifier(infos["messages"] > 5 and infos["metadata"], f"bag : {infos}")
    r = subprocess.run(["ros2", "bag", "info", str(Path(args.seances) / ident / "bag")], capture_output=True,
                       text=True, timeout=120)
    verifier(r.returncode == 0 and "/odom" in r.stdout, "ros2 bag info ne lit pas le bag de la séance interrompue")
    rapport = json.loads((Path(args.seances) / ident / "rapport.json").read_text(encoding="utf-8"))
    verifier(any(a["genre"] == "seance_interrompue" for a in rapport["anomalies"]),
             "le rapport ne dit pas que la séance a été interrompue")
    seance = api(args.api, "GET", "/api/seance")[1]
    verifier(seance["seance"] is None, f"une séance s'est ouverte seule au redémarrage : {seance['seance']}")
    liste = api(args.api, "GET", "/api/seances")[1]
    verifier(any(s["id"] == ident and s["etat"] == "interrompue" for s in liste), "la liste ne la montre pas")
    dire(f"Atelier relancé : séance {ident} interrompue, bag lisible ({infos['messages']} messages), rapport en "
         f"{duree:.0f} s ; aucune séance nouvelle")
    return 0


# ---------------------------------------------------------------- export et restes

def exporter(args):
    g1 = str(RACINE / "bin" / "g1-seance")
    env = dict(os.environ, ATELIER_SEANCES=args.seances)
    r = subprocess.run([g1, "exporter", args.seance, "--sortie", args.sortie], capture_output=True, text=True,
                       timeout=300, env=env)
    verifier(r.returncode == 0, f"g1-seance exporter : {r.stdout}{r.stderr}")
    noms = zipfile.ZipFile(args.sortie).namelist()
    for nom in ("seance.json", "actions.jsonl", "rapport.json", "rapport.md", "rapport.html", "trajets.png",
                "bag/metadata.yaml"):
        verifier(f"{args.seance}/{nom}" in noms, f"{nom} absent du .zip ({len(noms)} fichiers)")
    verifier(any(n.startswith(f"{args.seance}/bag/") and n.endswith(".db3") for n in noms), "bag absent du .zip")
    r = subprocess.run([g1, "liste"], capture_output=True, text=True, timeout=120, env=env)
    verifier(r.returncode == 0 and args.seance in r.stdout, f"g1-seance liste : {r.stdout}{r.stderr}")
    dire(f"g1-seance exporter : {Path(args.sortie).name} ({os.path.getsize(args.sortie) / 1e6:.1f} Mo, "
         f"{len(noms)} fichiers) ; g1-seance liste la montre")
    return 0


def restes(args):
    trouves = []
    for d in Path("/proc").iterdir():
        if not d.name.isdigit() or int(d.name) == os.getpid():
            continue
        try:
            ligne = (d / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
        except OSError:
            continue
        if "atelier.seance" in ligne and args.seances in ligne:
            trouves.append(f"{d.name} {ligne[:160]}")
    if trouves:
        print("Processus de la boîte noire restants :\n  " + "\n  ".join(trouves))
        return 1
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="outils_seance_e2e.py", description=__doc__.split("\n")[0])
    sous = p.add_subparsers(dest="action", required=True)
    s = sous.add_parser("principal")
    s.add_argument("--api", required=True)
    s.add_argument("--lieu", required=True)
    s.add_argument("--seances", required=True)
    s = sous.add_parser("jetson")
    s.add_argument("--seances", required=True)
    s.add_argument("--bin", required=True)
    s.add_argument("--trace", required=True)
    for nom in ("garde-fou", "plantage-avant"):
        s = sous.add_parser(nom)
        s.add_argument("--api", required=True)
        s.add_argument("--seances", required=True)
    s = sous.add_parser("plantage-enregistreur")
    s.add_argument("--seances", required=True)
    s.add_argument("--seance", required=True)
    s = sous.add_parser("plantage-apres")
    s.add_argument("--api", required=True)
    s.add_argument("--seances", required=True)
    s.add_argument("--seance", required=True)
    s = sous.add_parser("exporter")
    s.add_argument("--seances", required=True)
    s.add_argument("--seance", required=True)
    s.add_argument("--sortie", required=True)
    s = sous.add_parser("restes")
    s.add_argument("--seances", required=True)
    args = p.parse_args(argv)
    actions_ = {"principal": principal, "jetson": jetson, "garde-fou": garde_fou, "plantage-avant": plantage_avant,
                "plantage-enregistreur": plantage_attente_enregistreur, "plantage-apres": plantage_apres,
                "exporter": exporter, "restes": restes}
    try:
        code = actions_[args.action](args)
    except PasPossible as e:
        print(f"[critère 38] EN ATTENTE : {e}", flush=True)
        return EN_ATTENTE
    except Echec as e:
        print(f"[critère 38] ÉCHEC : {e}", flush=True)
        return 1
    erreurs = [c for c in CODES if c[2] == 500]
    if erreurs:
        print(f"[critère 38] ÉCHEC : erreurs 500 : {erreurs}", flush=True)
        return 1
    return code


if __name__ == "__main__":
    sys.exit(main())
