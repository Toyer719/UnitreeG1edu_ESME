"""Outils communs aux tests de l'écran de scan (vague 2, puis vague 5, section 12.5 du plan) : un faux g1-scan.

Pas de test ici : des fixtures, et les fonctions qu'appelle le faux g1-scan.
  lieux_scan  copie complète de lieux/demo (carte et .sdf compris) dans $ATELIER_LIEUX temporaire
  faux_scan   les fausses commandes de test_serveur_communs, plus un faux g1-scan ($ATELIER_BIN)
  client_scan TestClient de l'application, sans pont ROS 2

Le faux g1-scan suit le contrat 9.5 sans ROS, sans Gazebo ni robot :
  demarrer   crée la session (atelier.lieu.creer_session) et lance, détaché et dans son propre
             groupe, le « processus de la session » : il note son pid dans session.json, réécrit
             apercu.png, apercu.json et le nuage en direct apercu_nuage (le robot avance sur le tour
             des couloirs) et les statistiques toutes les FAUX_SCAN_PAS secondes, jusqu'à SIGINT ou
             SIGTERM (ou la fin du tour avec --explorer) ; puis arrêt (enregistrement/metadata.yaml),
             et traitement (vague 5) : nuage, carte (le monde de l'étage tramé par atelier.monde), nuage
             d'affichage, rapport ; état termine. Dernière ligne : « session: <id> ».
  arreter    SIGINT au groupe du processus, attend la fin de l'enregistrement (30 s au plus) ;
             session interrompue : traitement s'il y a un enregistrement, sinon echec.
  adopter    la vraie adoption (atelier.scan.session.adopter : carte, nuage, carte extrudée), sans ROS.
  etat       atelier.lieu.etat_scan en JSON.
Variables : FAUX_JOURNAL (appels), FAUX_SCAN_ECHEC=demarrer|arreter|adopter (la sous-commande
échoue), FAUX_SCAN_ECHEC_TRAITEMENT=carte_3d|nuage, FAUX_SCAN_PAS (0,2 s),
FAUX_SCAN_ETAPE_S (0,2 s par étape du traitement), FAUX_SCAN_TOURS (20 pas pour tout le tour).
"""
import json
import math
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest

from atelier import lieu as L
from atelier.lieu import copier_lieu

from .outils_scan import SOL_PLAT, ecrire_pcd_ascii, ecrire_png_gris
from .test_serveur_communs import DEMO, FauxBin, attendre, faux_bin, journaux, processus_vivant  # noqa: F401

FAUX_SCAN = r'''#!{python}
"""Faux g1-scan des tests de l'onglet Scan (voir atelier/tests/test_serveur_scan_communs.py)."""
import os, sys
with open(os.environ["FAUX_JOURNAL"], "a") as f:
    f.write("g1-scan " + " ".join(sys.argv[1:]) + "\n")
from atelier.tests.test_serveur_scan_communs import faux_g1_scan
sys.exit(faux_g1_scan(sys.argv[1:], __file__))
'''


# ---------------------------------------------------------------- le faux g1-scan

def _option(args, nom, defaut=None):
    return args[args.index(nom) + 1] if nom in args else defaut


def _env(nom, defaut):
    return float(os.environ.get(nom) or defaut)


def _noter_pid(pid):
    with open(os.environ["FAUX_JOURNAL"] + ".pids", "a") as f:
        f.write(f"{pid}\n")


def faux_g1_scan(args, script):
    """Corps du faux g1-scan. Renvoie le code de sortie (0 réussi, 1 échec, 2 mal tapée)."""
    if not args:
        print("erreur : sous-commande manquante (demarrer, arreter, traiter, etat, adopter)")
        return 2
    commande = args[0]
    if os.environ.get("FAUX_SCAN_ECHEC") == commande:
        print(f"faux g1-scan {commande} : préparation…")
        print("erreur : le faux g1-scan échoue exprès : relancez sans FAUX_SCAN_ECHEC", flush=True)
        return 1
    lieu = _option(args, "--lieu")
    try:
        if commande == "demarrer":
            return _demarrer(args, lieu, script)
        if commande == "_session":
            _processus_session(lieu, _option(args, "--session"))
            return 0
        if commande == "arreter":
            return _arreter(lieu, _option(args, "--session"), script)
        if commande == "traiter":
            _traiter(lieu, _option(args, "--session"))
            return 0
        if commande == "adopter":
            return _adopter(lieu, _option(args, "--session"))
        if commande == "etat":
            print(json.dumps(L.etat_scan(lieu, _option(args, "--session")), ensure_ascii=False))
            return 0
    except L.ErreurLieu as e:
        print("erreur : " + " ; ".join(e.erreurs), flush=True)
        return 1
    print(f"erreur : sous-commande inconnue « {commande} »")
    return 2


def _demarrer(args, lieu, script):
    s = L.creer_session(lieu, _option(args, "--etage"), _option(args, "--mode"), nom=_option(args, "--nom"),
                        repetition="--repetition" in args, explorer="--explorer" in args)
    journal = Path(os.environ["FAUX_JOURNAL"]).parent / f"scan_{s['id']}.log"
    with open(journal, "a") as sortie:
        p = subprocess.Popen([sys.executable, script, "_session", "--lieu", str(lieu), "--session", s["id"]],
                             stdout=sortie, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                             start_new_session=True)
    _noter_pid(p.pid)
    L.maj_session(lieu, s["id"], journal=str(journal))
    # le processus de la session note lui-même son pid : on l'attend (3 s au plus, comme le contrat)
    attendre(lambda: L.lire_session(lieu, s["id"])["processus"] is not None, 3.0)
    print(f"Scan démarré en mode {s['mode']} ; journal : {journal}")
    print(f"session: {s['id']}", flush=True)
    return 0


def _vue(info, image, vus):
    vue = np.full(image.shape, 205, dtype=np.uint8)
    vue[vus] = 0
    return vue


def _ecrire_apercu(lieu, s, info, image, vus, trajectoire, stats):
    dossier = L.dossier_session(lieu, s["id"])
    ecrire_png_gris(dossier / L.FICHIERS_SESSION["apercu_png"], _vue(info, image, vus))
    lignes, colonnes = np.nonzero(vus)
    x, y = L.pixel_vers_monde(colonnes, lignes, info)
    pas = max(1, math.ceil(len(lignes) / L.APERCU_POINTS_MAX))
    points = [[round(float(a), 2), round(float(b), 2), round(0.2 + (i % 7) * 0.2, 2)]
              for i, (a, b) in enumerate(zip(np.asarray(x)[::pas], np.asarray(y)[::pas]))]
    xmin, ymin, xmax, ymax = L.bornes_carte(info)
    robot = trajectoire[-1]
    apercu = {"version": 1, "session": s["id"], "maj": L.scans.instant(), "repere": "odom",
              "resolution": info.resolution, "bornes": {"xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax},
              "largeur": info.largeur, "hauteur": info.hauteur, "sol": 0.0,
              "points": points[:L.APERCU_POINTS_MAX], "trajectoire": trajectoire[-L.APERCU_TRAJECTOIRE_MAX:],
              "robot": {"x": robot[0], "y": robot[1], "theta": robot[2]}, "statistiques": stats}
    L.ecrire_atomique(dossier / L.FICHIERS_SESSION["apercu_json"], json.dumps(apercu, ensure_ascii=False) + "\n")
    direct = np.array([[p[0], p[1], h] for p in points for h in (p[2], p[2] + 0.5)], dtype=float).reshape(-1, 3)
    L.ecrire_nuage(L.chemin_nuage_session(dossier, apercu=True), direct,
                   L.entete_nuage(direct, 0.1, SOL_PLAT, "apercu", session=s["id"], statistiques=stats))


def _carte_du_monde(lieu, etage):
    from atelier.monde import fabriquer_carte
    monde = L.charger_monde(lieu, etage)
    info, image = fabriquer_carte(monde, image=L.FICHIERS_SESSION["carte_image"])
    return monde, info, image


def _processus_session(lieu, session):
    arret = []
    signal.signal(signal.SIGINT, lambda *_: arret.append(1))
    signal.signal(signal.SIGTERM, lambda *_: arret.append(1))
    s = L.maj_session(lieu, session, etape="enregistrement", processus=L.infos_processus(),
                      message="Scan en cours : promenez le robot dans tout l'étage, puis « Fin ».")
    _, info, image = _carte_du_monde(lieu, s["etage"])
    from .outils_scan import _trajectoire
    tour = _trajectoire(lieu, s["etage"])
    X, Y = L.centres_pixels(info)
    occupe = image == 0
    vus = np.zeros(image.shape, dtype=bool)
    pas, tours = _env("FAUX_SCAN_PAS", 0.2), int(_env("FAUX_SCAN_TOURS", 20))
    debut, i = time.monotonic(), 0
    print(f"faux processus de la session {session} : enregistrement", flush=True)
    while not arret:
        i += 1
        k = min(len(tour), max(1, i * len(tour) // tours))
        trajectoire = tour[:k]
        x, y = trajectoire[-1][:2]
        vus |= occupe & (np.hypot(X - x, Y - y) < 6.0)
        distance = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(trajectoire, trajectoire[1:]))
        stats = {"duree_s": round(time.monotonic() - debut, 1), "points": int(vus.sum()) * 40,
                 "distance_m": round(distance, 2), "nuages": i * 2}
        _ecrire_apercu(lieu, s, info, image, vus, trajectoire, stats)
        L.maj_session(lieu, session, statistiques=stats)
        if s["explorer"] and k >= len(tour):
            print("tour des couloirs fini : le scan se termine de lui-même", flush=True)
            break
        time.sleep(pas)
    L.maj_session(lieu, session, etat="arret_en_cours", etape="arret",
                  message="Arrêt du scan : fermeture de l'enregistrement…")
    enregistrement = L.dossier_session(lieu, session) / L.FICHIERS_SESSION["enregistrement"]
    enregistrement.mkdir(exist_ok=True)
    (enregistrement / "metadata.yaml").write_text("rosbag2_bagfile_information: {version: 5}\n")
    time.sleep(pas)
    L.maj_session(lieu, session, fin=L.scans.instant())
    _traiter(lieu, session)


def _traiter(lieu, session):
    s = L.lire_session(lieu, session)
    dossier = L.dossier_session(lieu, session)
    duree = _env("FAUX_SCAN_ETAPE_S", 0.2)
    echec = os.environ.get("FAUX_SCAN_ECHEC_TRAITEMENT")
    monde, info, image = _carte_du_monde(lieu, s["etage"])
    etapes = []
    fin = s["fin"] or L.scans.instant()

    def etape(nom, message):
        for f in (0.0, 0.5):
            L.maj_session(lieu, session, etat="traitement", etape=nom, progression=L.progression_etape(nom, f),
                          message=message, fin=fin)
            time.sleep(duree / 2)
        etapes.append({"etape": nom, "ok": True, "duree_s": duree, "message": ""})

    etape("carte_3d", "Fabrication de la carte 3D (nuage de points)…")
    if echec == "carte_3d":
        L.maj_session(lieu, session, etat="echec", message="La carte 3D n'a pas pu être fabriquée : "
                      "l'enregistrement ne contient aucun nuage de points. Vérifiez que le LiDAR publie, "
                      "puis refaites le scan.")
        return
    lignes, colonnes = np.nonzero(image == 0)
    x, y = L.pixel_vers_monde(colonnes, lignes, info)
    nuage = np.column_stack([np.repeat(x, 3), np.repeat(y, 3), np.tile([0.3, 0.8, 1.3], len(lignes))])
    ecrire_pcd_ascii(dossier / L.FICHIERS_SESSION["nuage"], nuage[::4])
    etape("carte_2d", "Fabrication de la carte 2D…")
    L.enregistrer_carte(dossier / L.FICHIERS_SESSION["carte"], info, image)
    etape("nuage", "Nuage de la carte 3D…")
    avertissements, affichage = [], None
    if echec == "nuage":
        avertissements.append("Nuage de la carte 3D non écrit (essai) ; la carte 2D est prête.")
    else:
        entete = L.ecrire_nuage(L.chemin_nuage_session(dossier), nuage,
                                L.entete_nuage(nuage, 0.05, SOL_PLAT, "scan", session=session, etage=s["etage"],
                                               mobiles_retires=0))
        affichage = {"fichier": "nuage_affichage.bin", "points": entete["points"], "grille": 0.05}
    rapport = {"version": 1, "session": session, "termine": L.scans.instant(), "duree_traitement_s": 3 * duree,
               "etapes": etapes, "nuages": {"recus": 10, "utilises": 10, "ignores": 0}, "base_de_temps": "message",
               "mobiles_retires": 0, "sol": dict(SOL_PLAT, points=100),
               "nuage": {"fichier": "nuage.pcd", "points": int(len(nuage[::4])), "nuages": 10, "retires_mobiles": 0},
               "carte": {"fichier": "carte.yaml", "largeur": info.largeur, "hauteur": info.hauteur,
                         "resolution": info.resolution, "occupes": int((image == 0).sum())},
               "affichage": affichage,
               "comparaison": {"reference": f"cartes/{s['etage']}.yaml", "recouvrement": 0.987, "couverture": 0.66},
               "repere": None, "avertissements": avertissements}
    L.ecrire_atomique(dossier / L.FICHIERS_SESSION["rapport"], json.dumps(rapport, ensure_ascii=False) + "\n")
    message = "Scan terminé : la carte 2D et le nuage 3D sont prêts. Regardez-les, puis « Utiliser cette carte »."
    if avertissements:
        message = "Scan terminé : la carte 2D est prête. " + avertissements[0]
    L.maj_session(lieu, session, etat="termine", etape="fini", progression=100, message=message)
    print(f"traitement de la session {session} fini", flush=True)


def _arreter(lieu, session, script):
    s = L.lire_session(lieu, session) if session else L.etat_scan(lieu)["session"]
    if s is None:
        print("erreur : aucun scan dans ce lieu")
        return 1
    session = s["id"]
    if s["etat"] not in L.ETATS_ACTIFS:
        print(f"Le scan {session} est déjà fini ({s['etat']}) : rien à faire.")
        return 0
    if L.session_interrompue(s):
        if L.fichiers_presents(lieu, session)["enregistrement"]:
            subprocess.Popen([sys.executable, script, "traiter", "--lieu", str(lieu), "--session", session],
                             stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, start_new_session=True)
            print(f"Scan {session} interrompu : traitement relancé.")
        else:
            L.maj_session(lieu, session, etat="echec", message="Le scan s'est arrêté sans enregistrement : "
                          "recommencez.")
            print(f"Scan {session} interrompu, sans enregistrement : échec.")
        return 0
    if s["etat"] == "en_cours":
        os.killpg(s["processus"]["pid"], signal.SIGINT)
    if not attendre(lambda: L.lire_session(lieu, session)["fin"] is not None, 30.0):
        print("erreur : l'enregistrement ne s'est pas fermé en 30 s : regardez le journal de la session")
        return 1
    print(f"Enregistrement du scan {session} fermé : le traitement continue (g1-scan etat --lieu {lieu}).")
    return 0


def _adopter(lieu, session):
    """La vraie adoption (sans ROS) : carte, nuage 3D, carte extrudée et monde de simulation."""
    from atelier.scan.session import ErreurScan, adopter
    try:
        messages, rapport = adopter(lieu, session)
    except ErreurScan as e:
        print(f"erreur : {e}")
        return 1
    for m in messages:
        print(m)
    print(f"Scan {session} adopté. Vérification du lieu :\n{rapport.texte()}")
    return 0


# ---------------------------------------------------------------- fixtures

@pytest.fixture
def lieux_scan(tmp_path, monkeypatch, journaux):
    """$ATELIER_LIEUX temporaire avec une copie complète de lieux/demo (carte et monde Gazebo compris)."""
    dossier = tmp_path / "lieux"
    dossier.mkdir()
    copier_lieu(DEMO, dossier / "demo")
    shutil.rmtree(dossier / "demo" / "scans", ignore_errors=True)
    monkeypatch.setenv("ATELIER_LIEUX", str(dossier))
    return dossier


@pytest.fixture
def faux_scan(faux_bin, monkeypatch):
    """Les fausses commandes g1-* de test_serveur_communs, plus le faux g1-scan."""
    faux_bin.ecrire("g1-scan", FAUX_SCAN)
    for nom in ("FAUX_SCAN_ECHEC", "FAUX_SCAN_ECHEC_TRAITEMENT", "FAUX_SCAN_TOURS", "FAUX_SCAN_PAS",
                "FAUX_SCAN_ETAPE_S", "ATELIER_INTERFACE_ROBOT"):
        monkeypatch.delenv(nom, raising=False)
    yield faux_bin
    # filet de sécurité : les groupes des faux processus de session, puis on vérifie qu'ils sont partis
    for pid in faux_bin.pids():
        try:
            os.killpg(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


@pytest.fixture
def client_scan(lieux_scan, faux_scan):
    from fastapi.testclient import TestClient
    from atelier.serveur.main import creer_app
    with TestClient(creer_app(ros=False)) as c:
        yield c


def attendre_etat(client, etats, delai=20.0, lieu="demo", session=None):
    """Interroge GET /api/scan/etat jusqu'à ce que la session soit dans l'un des états donnés."""
    url = f"/api/scan/etat?lieu={lieu}" + (f"&session={session}" if session else "")
    dernier = {}

    def condition():
        dernier["e"] = client.get(url).json()
        s = dernier["e"].get("session")
        return s is not None and s["etat"] in etats
    assert attendre(condition, delai, 0.1), f"état attendu {etats}, dernier : {dernier.get('e')}"
    return dernier["e"]
