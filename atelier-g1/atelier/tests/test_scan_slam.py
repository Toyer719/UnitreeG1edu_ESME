"""Tests du client slam_operate, du faux service et de g1-slam (agent Scan), sans robot.

Le faux service et le client tournent dans ce processus, sur l'interface lo, dans un domaine
DDS propre au processus (faux_slam.domaine_essai). Rien ne passe par eno2.
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

import pytest

from atelier import RACINE
from atelier.lieu import charger_fiche, copier_lieu
from atelier.scan import slam_client as sc
from atelier.scan.faux_slam import FauxSlam, faux_partage

LIEU_DEMO = RACINE / "lieux" / "demo"


# ---------------------------------------------------------------- formats JSON

def test_formats_des_commandes():
    assert sc.parametres_debut_scan() == {"data": {"slam_type": "indoor"}}
    assert sc.parametres_fin_scan("rdc") == {"data": {"address": "/home/unitree/rdc.pcd"}}
    assert sc.parametres_fin_scan("test1.pcd")["data"]["address"] == "/home/unitree/test1.pcd"
    assert sc.parametres_fin_scan("/data/x.pcd")["data"]["address"] == "/data/x.pcd"
    assert sc.nom_fichier_carte("rdc") == "rdc.pcd"
    r = sc.parametres_relocaliser(1.0, 2.0, math.pi / 2, "rdc")["data"]
    assert set(r) == {"x", "y", "z", "q_x", "q_y", "q_z", "q_w", "address"}
    assert r["address"] == "/home/unitree/rdc.pcd"
    assert r["q_z"] == pytest.approx(math.sin(math.pi / 4)) and r["q_w"] == pytest.approx(math.cos(math.pi / 4))
    a = sc.parametres_aller(3.0, -1.0, 0.0)
    assert a["data"]["mode"] == 1
    assert a["data"]["targetPose"] == {"x": 3.0, "y": -1.0, "z": 0.0, "q_x": 0.0, "q_y": 0.0, "q_z": 0.0, "q_w": 1.0}
    assert sc.parametres_vides() == {"data": {}}
    with pytest.raises(ValueError):
        sc.adresse_carte("  ")
    # Tout se transforme en JSON
    json.dumps(sc.parametres_relocaliser(0, 0, 0, "a"))


def test_lire_reponse():
    r = sc.lire_reponse(0, '{"succeed": true, "errorCode": 0, "info": "ok"}')
    assert r.ok and r.message == "ok"
    r = sc.lire_reponse(0, '{"succeed": false, "errorCode": 3, "info": "trop loin"}')
    assert not r.ok and "errorCode 3" in r.message and "trop loin" in r.message
    r = sc.lire_reponse(0, '{"errorCode": 5}')
    assert not r.ok
    assert sc.lire_reponse(0, "").ok                      # réponse vide : transmis, pas d'erreur connue
    assert sc.lire_reponse(0, "pas du json").ok
    r = sc.lire_reponse(3104, None)
    assert not r.ok and r.code == 3104 and "pas de réponse" in r.message


def test_lire_pose_et_arrivee():
    texte = json.dumps({"type": "pos_info", "data": {"currentPose": sc.pose_unitree(1.5, -2.0, 1.0)}})
    x, y, theta = sc.lire_pose(texte)
    assert (x, y) == (1.5, -2.0) and theta == pytest.approx(1.0)
    assert sc.lire_pose(json.dumps({"pose": {"x": 1, "y": 2}})) == (1.0, 2.0, 0.0)
    assert sc.lire_pose("{}") is None and sc.lire_pose("n'importe quoi") is None
    assert sc.lire_pose(json.dumps({"currentPose": {"x": "a", "y": 0}})) is None

    assert sc.lire_arrivee(json.dumps({"type": "task_result", "task_result": {"is_arrived": True}})) is True
    assert sc.lire_arrivee(json.dumps({"data": [{"is_arrived": False}]})) is False
    assert sc.lire_arrivee(json.dumps({"is_arrived": 1})) is True
    assert sc.lire_arrivee(json.dumps({"is_arrived": "true"})) is True
    assert sc.lire_arrivee(json.dumps({"autre": 1})) is None
    assert sc.lire_arrivee("{") is None


def test_connexion():
    assert sc.connexion(faux=False) == ("eno2", 0) or os.environ.get("G1_INTERFACE")
    interface, _ = sc.connexion(faux=True)
    assert interface == "lo"


# ---------------------------------------------------------------- client et faux service, dans ce processus

@pytest.fixture(scope="module")
def client():
    faux_partage()                     # ouvre DDS sur lo, dans le domaine de ce processus
    domaine, interface = sc.dds_ouvert()
    assert interface == "lo"
    c = sc.ClientSlam(interface, domaine, delai=3.0)
    yield c
    c.fermer()


@pytest.fixture
def faux():
    return faux_partage(depart=(0.0, 0.0, 0.0), relocalise=False, vitesse=3.0, rotation=6.0)


def attendre(condition, delai=5.0):
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        if condition():
            return True
        time.sleep(0.05)
    return condition()


def test_deroule_complet(faux, client):
    # Pas de navigation avant d'être repéré, pas de fin de scan avant le début
    r = client.aller(1.0, 0.0, 0.0)
    assert not r.ok and r.donnees["errorCode"] == 1
    assert not client.fin_scan("rdc").ok
    # 1801 → 1802 → 1804 → 1102
    assert client.debut_scan().ok
    assert not client.debut_scan().ok                      # déjà en cours
    assert client.fin_scan("rdc").ok
    assert not client.relocaliser(0.0, 0.0, 0.0, "inconnue").ok
    assert client.relocaliser(0.5, 0.5, 0.0, "rdc").ok
    debut = time.monotonic()
    assert client.aller(2.0, 1.5, math.pi / 2).ok
    suivi = sc.SuiviArrivee(client, debut, (2.0, 1.5))
    assert attendre(lambda: suivi.arrive(client.pose()[0]), 8.0)
    x, y, theta = faux.position()
    assert math.hypot(x - 2.0, y - 1.5) < 0.06 and theta == pytest.approx(math.pi / 2, abs=0.06)
    # La position publiée sur slam_info est celle du faux robot
    assert attendre(lambda: client.pose()[0] is not None and math.hypot(client.pose()[0][0] - 2.0,
                                                                        client.pose()[0][1] - 1.5) < 0.1)
    apis = [e["api"] for e in faux.journal]
    assert apis == [1102, 1802, 1801, 1801, 1802, 1804, 1804, 1102]
    assert client.arreter().ok


def test_trop_loin_et_parametres(faux, client):
    faux.reinitialiser((0.0, 0.0, 0.0), relocalise=True, portee_max=8.0)
    r = client.aller(9.0, 0.0, 0.0)
    assert not r.ok and r.donnees["errorCode"] == 3
    r = client.appeler(sc.API_ALLER, {"data": {"mode": 1}})
    assert not r.ok and r.donnees["errorCode"] == 2
    assert client.aller(7.5, 0.0, 0.0).ok


def test_pause_et_reprise(faux, client):
    faux.reinitialiser((0.0, 0.0, 0.0), relocalise=True, vitesse=1.0)
    assert client.aller(5.0, 0.0, 0.0).ok
    time.sleep(0.5)
    assert client.pause().ok
    time.sleep(0.2)
    x1 = faux.position()[0]
    time.sleep(0.5)
    assert faux.position()[0] == pytest.approx(x1)          # le robot ne bouge plus
    assert 0.1 < x1 < 2.0
    assert client.reprendre().ok
    assert attendre(lambda: faux.position()[0] > x1 + 0.2, 3.0)


def test_arrivee_perimee_ignoree(faux, client):
    """Un is_arrived resté vrai du trajet précédent ne fait pas croire à l'arrivée du suivant."""
    faux.reinitialiser((0.0, 0.0, 0.0), relocalise=True, vitesse=1.0, delai_perime=0.8)
    debut = time.monotonic()
    assert client.aller(0.5, 0.0, 0.0).ok
    suivi = sc.SuiviArrivee(client, debut, (0.5, 0.0))
    assert attendre(lambda: suivi.arrive(client.pose()[0]), 5.0)
    # Nouveau trajet : pendant 0,8 s le faux service republie l'ancienne arrivée (vrai)
    debut = time.monotonic()
    assert client.aller(2.5, 0.0, 0.0).ok
    suivi_sans_pose = sc.SuiviArrivee(client, debut, (2.5, 0.0))
    time.sleep(0.7)
    assert any(sc.lire_arrivee(t) for _, t in client.infos_cle_depuis(debut))   # vrai périmé bien reçu
    assert not suivi_sans_pose.arrive(None)
    assert attendre(lambda: suivi_sans_pose.arrive(None), 6.0)
    assert faux.position()[0] == pytest.approx(2.5, abs=0.06)


# ---------------------------------------------------------------- g1-slam en ligne de commande

def _env_commande(tmp_path):
    env = dict(os.environ)
    env["ROS_DOMAIN_ID"] = str(100 + os.getpid() % 50)      # pas le domaine des autres tests
    env["ROS_LOCALHOST_ONLY"] = "1"
    env["ATELIER_LIEUX"] = str(tmp_path / "lieux")
    env.pop("G1_INTERFACE", None)
    return env


def test_commande_g1_slam(tmp_path):
    env = _env_commande(tmp_path)
    copier_lieu(LIEU_DEMO, tmp_path / "lieux" / "essai")
    g1_slam = str(RACINE / "bin" / "g1-slam")
    faux = subprocess.Popen([g1_slam, "faux-service", "--lieu", "essai"], env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, start_new_session=True)
    try:
        time.sleep(2.0)

        def lancer(*args):
            r = subprocess.run([g1_slam, *args], env=env, capture_output=True, text=True, timeout=30)
            return r.returncode, r.stdout + r.stderr

        code, sortie = lancer("aller", "3", "10", "--faux")
        assert code == 1 and "1804" in sortie, sortie
        code, sortie = lancer("scan-debut", "--faux")
        assert code == 0, sortie
        code, sortie = lancer("scan-fin", "--nom", "rdc", "--lieu", "essai", "--faux")
        assert code == 0 and "carte_unitree: rdc.pcd" in sortie, sortie
        assert charger_fiche(tmp_path / "lieux" / "essai").carte_unitree == "rdc.pcd"
        code, sortie = lancer("relocaliser", "--lieu", "essai", "--x", "2.5", "--y", "10", "--faux")
        assert code == 0, sortie
        code, sortie = lancer("aller", "3.5", "10", "0", "--attendre", "15", "--faux")
        assert code == 0 and "Arrivé" in sortie, sortie
        code, sortie = lancer("etat", "--duree", "1", "--faux")
        assert code == 0 and "x = 3.5" in sortie, sortie
        code, sortie = lancer("pause", "--faux")
        assert code == 0, sortie
        code, sortie = lancer("arreter", "--faux")
        assert code == 0, sortie
        code, sortie = lancer("scan-fin", "--faux")
        assert code == 2 and "--nom" in sortie
    finally:
        os.killpg(faux.pid, signal.SIGINT)
        try:
            faux.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(faux.pid, signal.SIGKILL)
    sortie = faux.stdout.read()
    assert "Faux service slam_operate prêt" in sortie and "(2.5, 10.0, 0.0)" in sortie


def test_commande_sans_faux_service(tmp_path):
    """Sans faux service, --faux dit quoi faire (et ne touche pas eno2)."""
    env = _env_commande(tmp_path)
    # domaine sans faux service : surtout pas celui du faux service de ce processus (faux_partage)
    from atelier.scan.faux_slam import domaine_essai
    domaine = 200 + os.getpid() % 30
    env["ROS_DOMAIN_ID"] = str(domaine + 1 if domaine == domaine_essai() else domaine)
    r = subprocess.run([str(RACINE / "bin" / "g1-slam"), "pause", "--faux"], env=env, capture_output=True,
                       text=True, timeout=30)
    assert r.returncode == 1
    assert "g1-slam faux-service" in r.stdout
