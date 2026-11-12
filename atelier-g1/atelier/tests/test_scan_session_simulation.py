"""Scans réels dans Gazebo, sans fenêtre ni robot : g1-scan de bout en bout (section 9.5 du plan).

  G1_SCAN_SIMULATION=1 ~/robot-g1/.venv-projet/bin/python -m pytest \\
      ~/robot-g1/atelier/tests/test_scan_session_simulation.py -v -s

Longs (5 à 10 min en tout) : sautés sans G1_SCAN_SIMULATION=1. Il faut ROS 2 chargé
(source ~/robot-g1/setup/env.sh) et g1_sim compilé. Domaine ROS et partition Gazebo : ceux de
l'environnement, 51 et scan_51 par défaut. Chaque test travaille sur une copie de lieux/demo.

  - scan simu avec --explorer : demarrer rend la main en moins de 3 s, l'aperçu (et le nuage en direct)
    se met à jour, la session finit « termine » seule, la carte recouvre celle du monde à 80 % au moins,
    aucun nuage ignoré, nuage d'affichage lisible, puis adopter donne un lieu valide et un monde maillé ;
  - répétition du mode robot : faux service (1801 puis 1802 avec carte_unitree), relais, bag des
    sujets /unitree/slam_mapping/*, téléopération, arreter --attendre, « termine ».
Après chaque test : aucun programme lancé par la session ne tourne encore.
"""
import json
import os
import re
import subprocess
import time
from pathlib import Path

import numpy as np
import pytest

import atelier
from atelier import lieu as L

pytestmark = pytest.mark.skipif(os.environ.get("G1_SCAN_SIMULATION") != "1",
                                reason="scans réels dans Gazebo (plusieurs minutes) : G1_SCAN_SIMULATION=1")
G1_SCAN = str(atelier.RACINE / "bin" / "g1-scan")
DEMO = atelier.RACINE / "lieux" / "demo"


@pytest.fixture
def env(tmp_path):
    pytest.importorskip("rclpy", reason="ROS 2 n'est pas chargé : source ~/robot-g1/setup/env.sh")
    lieux = tmp_path / "lieux"
    lieux.mkdir()
    L.copier_lieu(DEMO, lieux / "essai")
    e = dict(os.environ, ATELIER_LIEUX=str(lieux), G1_SLAM_FAUX="1", ROS_LOCALHOST_ONLY="0")
    e.setdefault("ROS_DOMAIN_ID", "51")
    e.setdefault("IGN_PARTITION", "scan_51")
    for variable in ("DISPLAY", "WAYLAND_DISPLAY", "G1_SCAN_BIN"):
        e.pop(variable, None)
    yield e, lieux / "essai"
    # Filet : si un test échoue en route, on arrête la session pour ne rien laisser tourner
    subprocess.run([G1_SCAN, "arreter", "--lieu", str(lieux / "essai"), "--sans-traitement"], env=e,
                   capture_output=True, timeout=120)


def g1_scan(env, *arguments, delai=120):
    r = subprocess.run([G1_SCAN, *map(str, arguments)], env=env, capture_output=True, text=True, timeout=delai)
    return r.returncode, r.stdout + r.stderr


def attendre_fin(lieu, ident, delai, suivre=None):
    """Relit session.json jusqu'à termine ou echec ; suivre(session) est appelé à chaque lecture."""
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        s = L.lire_session(lieu, ident)
        if suivre:
            suivre(s)
        if s["etat"] in ("termine", "echec"):
            return s
        assert not L.session_interrompue(s), f"processus de la session mort : {s}"
        time.sleep(1.0)
    raise AssertionError(f"session {ident} pas finie en {delai} s : {L.lire_session(lieu, ident)}")


def verifier_rien_ne_tourne(lieu, ident, env):
    """Les programmes de .processus.json et Gazebo de ce lieu sont tous arrêtés."""
    dossier = L.dossier_session(lieu, ident)
    donnees = json.loads((dossier / ".processus.json").read_text())
    assert donnees["programmes"], "aucun programme noté"
    for p in donnees["programmes"]:
        assert p["arrete"], p
        try:
            os.killpg(p["pid"], 0)
            vivant = True
        except ProcessLookupError:
            vivant = False
        assert not vivant, f"le groupe {p['nom']} ({p['pid']}) tourne encore"
    session = L.lire_session(lieu, ident)
    assert L.processus_vivant(session) is False
    restes = subprocess.run(["pgrep", "-f", str(lieu)], capture_output=True, text=True).stdout.split()
    assert not restes, f"processus restants pour {lieu} : {restes}"


def test_scan_simu_avec_exploration(env):
    e, lieu = env
    debut = time.monotonic()
    code, sortie = g1_scan(e, "demarrer", "--lieu", "essai", "--etage", "rdc", "--mode", "simu", "--explorer",
                           "--json")
    duree = time.monotonic() - debut
    assert code == 0, sortie
    assert duree < 3.0, f"demarrer a mis {duree:.1f} s"
    etat = json.loads(sortie)
    ident = etat["session"]["id"]
    assert etat["actif"] and etat["session"]["mode"] == "simu" and etat["session"]["explorer"]
    print(f"\ndemarrer : {duree:.2f} s, session {ident}")

    apercus, distances = set(), []

    def suivre(s):
        if s["etat"] == "en_cours" and s["etape"] == "enregistrement":
            chemin = L.chemin_session(lieu, ident, "apercu_json")
            try:
                apercus.add(json.loads(chemin.read_text())["maj"])
            except (OSError, ValueError):
                pass
            distances.append(s["statistiques"]["distance_m"])
    s = attendre_fin(lieu, ident, 20 * 60, suivre)
    print(f"fin : {s['etat']} en {time.monotonic() - debut:.0f} s ; {s['message']}")
    assert s["etat"] == "termine", s["message"]
    assert len(apercus) >= 5, f"aperçu mis à jour {len(apercus)} fois seulement"
    assert distances and distances[-1] > 40 and distances == sorted(distances)
    dossier = L.dossier_session(lieu, ident)
    from atelier.scan.carte2d import comparer_fichiers
    c = comparer_fichiers(dossier / "carte.yaml", lieu / "cartes" / "rdc.yaml")
    print(f"recouvrement {c['recouvrement'] * 100:.1f} %, couverture {c['couverture'] * 100:.1f} %")
    assert c["recouvrement"] >= 0.80
    rapport = json.loads((dossier / "rapport.json").read_text())
    assert rapport["comparaison"]["recouvrement"] == pytest.approx(c["recouvrement"], abs=1e-3)
    assert rapport["repere"]["capteur"] == "tf_static" and rapport["repere"]["deja_dans_le_monde"] is False
    assert rapport["nuages"]["ignores"] <= 0.01 * rapport["nuages"]["recus"] and rapport["base_de_temps"] == "message"
    points, entete = L.lire_nuage(L.chemin_nuage_session(dossier))
    # Le sol du nuage d'affichage est à z = 0 (le plan est soustrait). Dans le repère de l'odométrie simulée, il
    # est vers −0,06 m (odométrie plane, z = 0, alors que le corps du robot proxy repose un peu au-dessus du
    # sol) : seul compte qu'il soit plat et retiré.
    h = points[:, 2].astype(float)
    sol_vu = float(np.median(h[np.abs(h) < 0.1]))
    assert entete["points"] > 50000 and abs(sol_vu) <= 0.02 and entete["sol"]["inclinaison_deg"] < 0.1, entete["sol"]
    assert abs(entete["sol"]["plan"][2]) < 0.1
    assert not (dossier / "reconnaissance.yaml").exists()
    assert L.lire_nuage(L.chemin_nuage_session(dossier, apercu=True))[1]["source"] == "apercu"
    verifier_rien_ne_tourne(lieu, ident, e)

    # « Utiliser cette carte » : lieu valide, monde maillé, ancien monde gardé, masque à la taille de la carte
    code, sortie = g1_scan(e, "adopter", "--lieu", "essai", "--session", ident)
    assert code == 0, sortie
    rapport_lieu = L.valider_lieu(lieu)
    print(rapport_lieu.texte())
    assert not rapport_lieu.erreurs
    assert L.charger_fiche(lieu).etage("rdc").source_carte == "scan"
    assert L.charger_monde(lieu, "rdc").carte_extrudee is not None and L.chemin_maillage(lieu, "rdc").is_file()


def publier_vitesse(env, vx, duree):
    """Téléopération : publie /cmd_vel pendant duree secondes, puis une vitesse nulle."""
    script = ("import rclpy, time\nfrom geometry_msgs.msg import Twist\nrclpy.init()\n"
              "n = rclpy.create_node('essai_teleop')\np = n.create_publisher(Twist, '/cmd_vel', 10)\n"
              f"time.sleep(1.5)\nfin = time.time() + {duree}\nm = Twist()\nm.linear.x = {vx}\n"
              "while time.time() < fin:\n    p.publish(m); time.sleep(0.1)\n"
              "for _ in range(5):\n    p.publish(Twist()); time.sleep(0.05)\n")
    subprocess.run([str(atelier.RACINE / ".venv-projet" / "bin" / "python"), "-c", script], env=env, check=True,
                   timeout=duree + 30)


def test_repetition_du_mode_robot(env):
    e, lieu = env
    debut = time.monotonic()
    code, sortie = g1_scan(e, "demarrer", "--lieu", "essai", "--etage", "rdc", "--mode", "robot", "--repetition")
    assert code == 0, sortie
    assert time.monotonic() - debut < 3.0
    ident = re.search(r"^session: (\S+)$", sortie, re.M).group(1)
    s = L.lire_session(lieu, ident)
    assert s["sujets"]["nuage"] == "/unitree/slam_mapping/points" and s["carte_unitree"] == f"rdc_{ident}.pcd"
    fin = time.monotonic() + 180
    while time.monotonic() < fin:
        s = L.lire_session(lieu, ident)
        if s["etape"] == "enregistrement" and s["statistiques"].get("nuages", 0) > 20:
            break
        assert s["etat"] == "en_cours", s["message"]
        time.sleep(1.0)
    else:
        raise AssertionError(f"pas d'enregistrement : {s}")
    assert "Répétition" in s["message"]
    publier_vitesse(e, 0.3, 6.0)                     # le robot simulé avance dans le hall
    code, sortie = g1_scan(e, "arreter", "--lieu", "essai", "--attendre", delai=600)
    print(sortie)
    assert code == 0, sortie
    s = L.lire_session(lieu, ident)
    assert s["etat"] == "termine" and s["statistiques"]["distance_m"] > 1.0
    # Le faux service a reçu 1801 puis 1802, avec le nom de la carte de la session
    journal = Path(s["journal"]).with_suffix("").as_posix() + ".faux_slam.log"
    texte = Path(journal).read_text(encoding="utf-8", errors="replace")
    debut_scan, fin_scan = texte.find("1801 ("), texte.find("1802 (")
    assert 0 <= debut_scan < fin_scan, texte[-2000:]
    assert f"/home/unitree/{s['carte_unitree']}" in texte[fin_scan:]
    # Le bag contient les sujets du vrai robot
    dossier = L.dossier_session(lieu, ident)
    from atelier.scan.carte3d import sujets_enregistres
    from atelier.scan.session import _nombre_de_messages
    sujets = sujets_enregistres(dossier / "enregistrement")
    for sujet in ("/unitree/slam_mapping/points", "/unitree/slam_mapping/odom"):
        assert sujet in sujets and _nombre_de_messages(dossier / "enregistrement", sujet) > 20, sujets
    assert "/points" not in sujets
    rapport = json.loads((dossier / "rapport.json").read_text())
    assert rapport["repere"]["nuage"] == "lidar" and rapport["repere"]["odom"] == "odom"
    print(f"rapport : {rapport['carte']}, comparaison {rapport['comparaison']}, avertissements "
          f"{rapport['avertissements']}")
    verifier_rien_ne_tourne(lieu, ident, e)


def test_arreter_sans_traitement_puis_traiter(env):
    """Simu sans exploration : « Fin » sans traitement, puis g1-scan traiter au premier plan."""
    e, lieu = env
    code, sortie = g1_scan(e, "demarrer", "--lieu", "essai", "--etage", "rdc", "--mode", "simu")
    assert code == 0, sortie
    ident = re.search(r"^session: (\S+)$", sortie, re.M).group(1)
    code, sortie = g1_scan(e, "demarrer", "--lieu", "essai", "--etage", "rdc", "--mode", "simu")
    assert code == 1 and "déjà en cours" in sortie                     # double démarrage refusé
    fin = time.monotonic() + 120
    while time.monotonic() < fin:
        s = L.lire_session(lieu, ident)
        if s["etape"] == "enregistrement" and s["statistiques"].get("nuages", 0) > 50:
            break
        time.sleep(1.0)
    assert s["etape"] == "enregistrement", s
    code, sortie = g1_scan(e, "arreter", "--lieu", "essai", "--sans-traitement")
    assert code == 0 and "sans traitement" in sortie, sortie
    fin = time.monotonic() + 60                       # le processus finit d'arrêter la simulation
    while L.processus_vivant(L.lire_session(lieu, ident)) and time.monotonic() < fin:
        time.sleep(0.5)
    s = L.lire_session(lieu, ident)
    assert (s["etat"], s["etape"]) == ("arret_en_cours", "arret") and s["fin"] and "g1-scan traiter" in s["message"]
    assert L.session_interrompue(s) and L.session_active(lieu) is None      # ne bloque pas un nouveau scan
    assert L.fichiers_presents(lieu, ident)["enregistrement"]
    verifier_rien_ne_tourne(lieu, ident, e)
    code, sortie = g1_scan(e, "traiter", "--lieu", "essai", "--session", ident, delai=600)
    assert code == 0, sortie
    s = L.lire_session(lieu, ident)
    assert s["etat"] == "termine" and L.fichiers_presents(lieu, ident)["carte"]
