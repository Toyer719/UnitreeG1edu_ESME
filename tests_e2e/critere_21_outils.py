#!/usr/bin/env python3
"""Outils du critère 21, le point principal (section 7 du plan, critère 21 ; section 11.2).

  critere_21_outils.py donnees --api URL --lieux DOSSIER --reference DOSSIER
      sur deux copies du demo (« sans » et « essai », dans DOSSIER) : un lieu sans point principal
      (g1-lieu valider en erreur, simulation refusée 409) ; deux principaux refusés (422) ;
      g1-lieu migrer (sauvegarde identique aux fichiers d'avant, étiquette posée, aucune erreur, second
      passage sans effet) ; la référence lieux/demo refusée et inchangée (empreintes) ; un lieu migré
      dont PUT …/salles perdrait le principal (422) ; PUT …/principal {theta: 1.5708} (salles.yaml,
      accueil, depart_robot), GET, puis le principal déplacé en (2,5 ; 11,0 ; 1,5708)
  critere_21_outils.py depart-simulation --api URL --lieu ID
      la simulation (mode simu, sans navigation) part du point principal : la première pose de /odom
      est à moins de 0,05 m et 0,05 rad de lui
  critere_21_outils.py reperage --api URL --lieu ID
      répétition : « Repérer le robot » sans pose → /reperage/demander porte x, y et theta du point
      principal ; 1804 reçoit carte_vers_unitree(principal, repere_unitree) ; robot repéré ; TF
      map → base_link à moins de 0,1 m (et 0,05 rad) de la vérité /g1_jumeau/odom
  critere_21_outils.py restes --lieux DOSSIER [--sauf PID…]
      aucun processus lancé avec ces lieux ne doit rester (code 1 sinon)

Code de sortie : 0 réussi, 1 échoué (le message dit pourquoi). Jamais le vrai robot (G1_SLAM_FAUX=1).
"""
import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import critere_18_outils  # noqa: E402
from critere_18_outils import (Echec, Ecoute, appel, attendre_relais, francais, requete_1804,  # noqa: E402
                               restes, verifier, verifier_tf_et_verite)

critere_18_outils.PREFIXE = "critère 21"

TOLERANCE_DEPART_M = 0.05
TOLERANCE_DEPART_RAD = 0.05
PRINCIPAL_DEPLACE = (2.5, 11.0, 1.5708)


def dire(texte):
    print(f"[critère 21] {texte}", flush=True)


def empreintes(dossier):
    dossier = Path(dossier)
    return {str(f.relative_to(dossier)): hashlib.sha256(f.read_bytes()).hexdigest()
            for f in sorted(dossier.rglob("*")) if f.is_file() and "__pycache__" not in f.parts}


def g1_lieu(*arguments):
    r = subprocess.run([str(RACINE / "bin" / "g1-lieu"), *arguments], capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout + r.stderr


def ecart(a, b):
    return (math.hypot(a[0] - b[0], a[1] - b[1]), abs((a[2] - b[2] + math.pi) % (2 * math.pi) - math.pi))


# ---------------------------------------------------------------- A. les données et l'API

def donnees(args):
    import yaml
    from atelier.lieu import charger_fiche, charger_monde, charger_salles, enregistrer_salles
    lieux = Path(args.lieux)
    # 1. un lieu sans point principal (ni étiquette ni salle accueil)
    sans = lieux / "sans"
    enregistrer_salles(sans, [s for s in charger_salles(sans) if s.id != "accueil"])
    code, sortie = g1_lieu("valider", "--lieu", "sans")
    verifier(code == 1 and "pas de point principal" in sortie,
             f"g1-lieu valider d'un lieu sans principal : {code} {sortie}")
    dire("lieu sans point principal : g1-lieu valider en erreur (« pas de point principal »)")
    code, r = appel(args.api, "POST", "/api/simulation/demarrer", {"lieu": "sans", "etage": "rdc"})
    verifier(code == 409 and francais(r) and "point principal" in r["detail"],
             f"simulation d'un lieu sans principal : {code} {r} (409 attendu)")
    dire(f"simulation refusée (409) : {r['detail'][:70]}…")
    # 2. deux principaux : 422
    essai = lieux / "essai"
    _, salles = appel(args.api, "GET", "/api/lieux/essai/salles")
    deux = [dict(s, etiquettes=["principal"]) if s["id"] in ("accueil", "b204") else s for s in salles]
    code, r = appel(args.api, "PUT", "/api/lieux/essai/salles?synchroniser=true", deux)
    verifier(code == 422 and any("un lieu n'a qu'un point principal" in m for m in r.get("erreurs", [])),
             f"PUT …/salles à deux principaux : {code} {r} (422 attendu)")
    dire("deux principaux : PUT …/salles refusé (422)")
    # 3. g1-lieu migrer, sur la copie
    avant = empreintes(essai)
    code, sortie = g1_lieu("migrer", "--lieu", "essai")
    verifier(code == 0 and "Lieu migré" in sortie, f"g1-lieu migrer : {code} {sortie}")
    sauvegardes = sorted((essai / "sauvegardes").iterdir())
    verifier(len(sauvegardes) == 1 and sauvegardes[0].name.endswith("_migration"), f"sauvegarde : {sauvegardes}")
    copies = empreintes(sauvegardes[0])
    for nom in ("lieu.yaml", "salles.yaml", "itineraires.yaml", "mondes/rdc.monde.yaml"):
        verifier(copies.get(nom) == avant[nom], f"la sauvegarde n'a pas {nom} à l'identique")
    verifier(charger_salles(essai)[0].etiquettes == ["principal"], "étiquette « principal » absente après migration")
    code, sortie = g1_lieu("valider", "--lieu", "essai")
    verifier(code == 0 and "Aucune erreur." in sortie, f"g1-lieu valider après migration : {sortie}")
    apres = empreintes(essai)
    code, sortie = g1_lieu("migrer", "--lieu", "essai")
    verifier(code == 0 and "Rien à changer" in sortie and empreintes(essai) == apres,
             f"second passage de g1-lieu migrer : {code} {sortie}")
    dire(f"g1-lieu migrer : sauvegarde {sauvegardes[0].name} identique, étiquette posée, aucune erreur, "
         "second passage sans effet")
    reference = Path(args.reference)
    avant_ref = empreintes(reference)
    code, sortie = g1_lieu("migrer", "--lieu", str(reference))
    verifier(code == 1 and "référence des tests" in sortie, f"g1-lieu migrer de lieux/demo : {code} {sortie}")
    verifier(empreintes(reference) == avant_ref, "lieux/demo a changé !")
    dire(f"g1-lieu migrer --lieu {reference} refusé ; lieux/demo inchangé ({len(avant_ref)} empreintes)")
    # 4. lieu migré : PUT …/salles qui perdrait le principal → 422
    _, salles = appel(args.api, "GET", "/api/lieux/essai/salles")
    for liste, quoi in (([dict(s, etiquettes=[]) for s in salles], "étiquette retirée"),
                        ([s for s in salles if s["id"] != "accueil"], "salle supprimée")):
        code, r = appel(args.api, "PUT", "/api/lieux/essai/salles?synchroniser=true", liste)
        verifier(code == 422 and "choisissez d'abord un autre point principal" in r.get("detail", ""),
                 f"PUT …/salles qui perd le principal ({quoi}) : {code} {r} (422 attendu)")
    verifier(empreintes(essai) == apres, "un PUT …/salles refusé a écrit quelque chose")
    dire("lieu migré : PUT …/salles qui perd le principal refusé (422), rien d'écrit")
    # 5. PUT …/principal {theta: 1.5708}, GET, puis le principal déplacé
    code, r = appel(args.api, "PUT", "/api/lieux/essai/principal", {"theta": 1.5708})
    verifier(code == 200, f"PUT …/principal {{theta}} : {code} {r}")
    s = next(x for x in yaml.safe_load((essai / "salles.yaml").read_text(encoding="utf-8")) if x["id"] == "accueil")
    valeurs = (s["pose"]["theta"], charger_fiche(essai).accueil.theta, charger_monde(essai, "rdc").depart_robot.theta)
    verifier(valeurs == (1.5708, 1.5708, 1.5708), f"salles.yaml, accueil, depart_robot : {valeurs} (1,5708 attendu)")
    _, p = appel(args.api, "GET", "/api/lieux/essai/principal")
    verifier(p["theta"] == 1.5708 and p["explicite"] and p["depart_synchro"], f"GET …/principal : {p}")
    dire("PUT …/principal {theta: 1.5708} : salles.yaml, accueil de lieu.yaml et depart_robot à 1,5708 ; GET le rend")
    x, y, theta = PRINCIPAL_DEPLACE
    code, r = appel(args.api, "PUT", "/api/lieux/essai/principal", {"x": x, "y": y, "theta": theta})
    verifier(code == 200 and r["rapport"]["erreurs"] == [], f"PUT …/principal déplacé : {code} {r}")
    _, p = appel(args.api, "GET", "/api/lieux/essai/principal")
    verifier((p["x"], p["y"], p["theta"]) == PRINCIPAL_DEPLACE, f"principal déplacé : {p}")
    d = charger_monde(essai, "rdc").depart_robot
    a = charger_fiche(essai).accueil
    verifier((d.x, d.y, d.theta) == (a.x, a.y, a.theta) == PRINCIPAL_DEPLACE, f"depart_robot {d}, accueil {a}")
    _, e = appel(args.api, "GET", "/api/robot/etat?lieu=essai&etage=rdc")
    verifier(e["marque"] == {"x": x, "y": y, "theta": theta}, f"pose de repérage par défaut : {e['marque']}")
    dire(f"point principal déplacé en ({x} ; {y} ; {theta}) : nœud, accueil, départ et pose de repérage suivent")
    return 0


# ---------------------------------------------------------------- B. la simulation part du principal

def depart_simulation(args):
    import rclpy
    from nav_msgs.msg import Odometry
    from rclpy.executors import SingleThreadedExecutor
    from rclpy.qos import qos_profile_sensor_data
    from atelier.lieu import quaternion_vers_cap
    _, p = appel(args.api, "GET", f"/api/lieux/{args.lieu}/principal")
    principal = (p["x"], p["y"], p["theta"])
    contexte = rclpy.Context()
    rclpy.init(context=contexte)
    noeud = rclpy.create_node("critere_21", context=contexte)
    premiere = []

    def sur_odom(msg):
        if not premiere:
            q = msg.pose.pose
            premiere.append((q.position.x, q.position.y, quaternion_vers_cap(q.orientation)))

    noeud.create_subscription(Odometry, "/odom", sur_odom, qos_profile_sensor_data)
    executeur = SingleThreadedExecutor(context=contexte)
    executeur.add_node(noeud)
    fin = threading.Event()

    def tourner():
        while not fin.is_set():
            try:
                executeur.spin_once(timeout_sec=0.05)
            except Exception:      # noqa: BLE001 : arrêt
                break

    fil = threading.Thread(target=tourner, daemon=True)
    fil.start()
    try:
        code, r = appel(args.api, "POST", "/api/simulation/demarrer",
                        {"lieu": args.lieu, "etage": "rdc", "navigation": False})
        verifier(code == 200, f"POST /api/simulation/demarrer (simu) : {code} {r}")
        debut = time.monotonic()
        while not premiere and time.monotonic() - debut < 90:
            time.sleep(0.1)
        verifier(premiere, "pas de /odom en 90 s : la simulation ne démarre pas")
        d, a = ecart(premiere[0], principal)
        dire(f"première pose de /odom ({premiere[0][0]:.3f} ; {premiere[0][1]:.3f} ; {premiere[0][2]:.3f}) en "
             f"{time.monotonic() - debut:.1f} s : à {d * 100:.1f} cm et {math.degrees(a):.1f}° du point principal "
             f"{principal}")
        verifier(d < TOLERANCE_DEPART_M and a < TOLERANCE_DEPART_RAD,
                 f"la simulation ne part pas du point principal : à {d:.3f} m et {a:.3f} rad "
                 f"(max {TOLERANCE_DEPART_M} m, {TOLERANCE_DEPART_RAD} rad)")
        code, r = appel(args.api, "POST", "/api/simulation/arreter")
        verifier(code == 200, f"POST /api/simulation/arreter : {code} {r}")
        return 0
    finally:
        fin.set()
        fil.join(timeout=3)
        executeur.shutdown()
        noeud.destroy_node()
        rclpy.try_shutdown(context=contexte)


# ---------------------------------------------------------------- C. le repérage part du principal

def reperage(args):
    from std_msgs.msg import String
    from atelier.lieu import carte_vers_unitree, quaternion_vers_cap
    demandes = []

    def abonner(ecoute):
        ecoute.noeud.create_subscription(String, "/reperage/demander",
                                         lambda m: demandes.append(json.loads(m.data)), 10)

    _, p = appel(args.api, "GET", f"/api/lieux/{args.lieu}/principal")
    principal = (p["x"], p["y"], p["theta"])
    repere = (p["repere_unitree"]["x"], p["repere_unitree"]["y"], p["repere_unitree"]["theta"])
    ecoute = Ecoute(avant_fil=abonner)
    try:
        corps = {"lieu": args.lieu, "etage": "rdc", "mode": "repetition"}
        code, r = appel(args.api, "POST", "/api/simulation/demarrer", corps)
        verifier(code == 200, f"POST /api/simulation/demarrer (repetition) : {code} {r}")
        attendre_relais(args.api, ecoute, args.lieu)
        _, e = appel(args.api, "GET", "/api/robot/etat")
        verifier(e["marque"] == {"x": principal[0], "y": principal[1], "theta": principal[2]},
                 f"pose de repérage par défaut : {e['marque']} (le principal {principal} attendu)")
        avant = len(ecoute.requetes)
        debut = time.monotonic()
        code, r = appel(args.api, "POST", "/api/robot/reperer", {"lieu": args.lieu, "etage": "rdc"}, delai=40)
        duree = time.monotonic() - debut
        verifier(code == 200 and r["repere"], f"POST /api/robot/reperer sans pose : {code} {r}")
        verifier(demandes, "aucune demande sur /reperage/demander")
        d = demandes[-1]
        verifier({"id", "x", "y", "theta"} <= set(d) and ecart((d["x"], d["y"], d["theta"]), principal)[0] < 1e-6
                 and ecart((d["x"], d["y"], d["theta"]), principal)[1] < 1e-6,
                 f"/reperage/demander : {d} (la pose du principal {principal} attendue)")
        dire(f"repéré en {duree:.2f} s : /reperage/demander porte la pose du principal "
             f"({d['x']} ; {d['y']} ; {d['theta']})")
        donnees_1804 = requete_1804(ecoute, avant)
        u = carte_vers_unitree(principal, repere)
        cap = quaternion_vers_cap((donnees_1804["q_x"], donnees_1804["q_y"], donnees_1804["q_z"], donnees_1804["q_w"]))
        verifier(math.hypot(donnees_1804["x"] - u[0], donnees_1804["y"] - u[1]) < 1e-6
                 and abs((cap - u[2] + math.pi) % (2 * math.pi) - math.pi) < 1e-6,
                 f"1804 : ({donnees_1804['x']:.4f} ; {donnees_1804['y']:.4f} ; {cap:.4f}) au lieu de "
                 f"carte_vers_unitree(principal, repere_unitree) = {tuple(round(v, 4) for v in u)}")
        verifier(math.hypot(u[0] - p["pose_unitree"]["x"], u[1] - p["pose_unitree"]["y"]) < 1e-4,
                 f"pose_unitree de GET …/principal ({p['pose_unitree']}) différente de {u}")
        dire(f"1804 reçue par le faux service : ({u[0]:.3f} ; {u[1]:.3f} ; {u[2]:.3f}) = carte_vers_unitree(principal, "
             f"repere_unitree {repere})")
        verifier_tf_et_verite(ecoute, "au point principal")
        verifier(not ecoute.non_conformes, f"/reperage/etat non conforme : {ecoute.non_conformes[:3]}")
        return 0
    finally:
        ecoute.fermer()


def main(argv=None):
    p = argparse.ArgumentParser(prog="critere_21_outils.py", description=__doc__.split("\n")[0])
    sous = p.add_subparsers(dest="action", required=True)
    s = sous.add_parser("donnees")
    s.add_argument("--api", required=True)
    s.add_argument("--lieux", required=True)
    s.add_argument("--reference", required=True)
    for nom in ("depart-simulation", "reperage"):
        s = sous.add_parser(nom)
        s.add_argument("--api", required=True)
        s.add_argument("--lieu", required=True)
    s = sous.add_parser("restes")
    s.add_argument("--lieux", required=True)
    s.add_argument("--sauf", nargs="*", default=[])
    args = p.parse_args(argv)
    try:
        return {"donnees": donnees, "depart-simulation": depart_simulation, "reperage": reperage,
                "restes": restes}[args.action](args)
    except Echec as e:
        print(f"[critère 21] ÉCHEC : {e}", flush=True)
        return 1


if __name__ == "__main__":
    os.environ.setdefault("G1_SLAM_FAUX", "1")
    sys.exit(main())
