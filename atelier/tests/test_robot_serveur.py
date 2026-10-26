"""Tests de l'API du vrai robot et de la répétition (section 10.8 du plan), avec fastapi.testclient.

  - modes de POST /api/simulation/demarrer (simu, repetition, robot), avec les fausses commandes
    g1-* de l'agent Interface (et un faux g1-jetson) : commandes lancées, refus, arrêt ;
  - GET /api/robot/etat, POST /api/robot/reperer et /api/robot/arret ;
  - avec ROS 2 : test_robot_serveur_ros.py.
Domaine ROS : $ROS_DOMAIN_ID, 63 par défaut (agent Repérage). Rien n'est jamais envoyé au robot :
le mode robot est essayé avec ATELIER_INTERFACE_ROBOT=lo et un faux g1-jetson.
"""
import os

import pytest

os.environ.setdefault("ROS_DOMAIN_ID", "63")

from .test_serveur_communs import (attendre, client, faux_bin, journaux, lieux,  # noqa: E402,F401
                                   processus_vivant)

RDC = "/api/lieux/demo/etages/rdc"

FAUX_JETSON = r'''#!{python}
"""Faux g1-jetson des tests de l'Atelier (ne parle à aucun réseau)."""
import os, sys
with open(os.environ["FAUX_JOURNAL"], "a") as f:
    f.write("g1-jetson " + " ".join(sys.argv[1:]) + "\n")
if os.environ.get("FAUX_ECHEC") == "1":
    print("g1-jetson : le Jetson ne répond pas (ssh unitree@192.168.123.164)", flush=True)
    sys.exit(1)
print("g1-jetson : " + sys.argv[1] + " réussi", flush=True)
'''


def _erreur(r, statut):
    assert r.status_code == statut, (r.status_code, r.text)
    d = r.json()
    assert isinstance(d["detail"], str) and d["detail"]
    return d


def _generer(c):
    assert c.post(RDC + "/monde/generer").status_code == 200


def _demarrer(c, mode, **champs):
    return c.post("/api/simulation/demarrer", json={"lieu": "demo", "etage": "rdc", "mode": mode, **champs})


# ---------------------------------------------------------------- sans ROS 2

def test_etat_sans_navigation(client):
    e = client.get("/api/robot/etat?lieu=demo&etage=rdc").json()
    assert e["mode"] is None and e["repere"] is False and e["etat"] == "non_repere"
    # vague 4 (section 11.2) : on pose le robot sur le point principal du demo (la salle accueil,
    # principal implicite), qui est aussi le départ du robot et l'origine du repère d'Unitree figé
    assert e["marque"] == {"x": 2.5, "y": 10.0, "theta": 0.0}
    assert e["principal"] == {"salle": "accueil", "nom": "Accueil", "etage": "rdc", "x": 2.5, "y": 10.0, "theta": 0.0}
    assert e["pont"] is None and e["reperage"] is None and "Aucune navigation" in e["message"]
    # lieu inconnu : pas de marque, mais pas d'erreur
    assert client.get("/api/robot/etat?lieu=nulle_part&etage=rdc").json()["marque"] is None
    assert client.get("/api/robot/etat").json()["marque"] is None
    assert client.get("/api/robot/etat").json()["principal"] is None


def test_mode_inconnu_ou_sans_navigation(client, faux_bin):
    _generer(client)
    assert "inconnu" in _erreur(_demarrer(client, "vol"), 400)["detail"]
    assert "navigation" in _erreur(_demarrer(client, "repetition", navigation=False), 400)["detail"]
    assert not any(a.startswith(("g1-monde simuler", "g1-guide", "g1-slam")) for a in faux_bin.appels())


def test_repetition_lance_les_trois_roles(client, lieux, faux_bin):
    _generer(client)
    r = _demarrer(client, "repetition")
    assert r.status_code == 200, r.text
    e = r.json()
    assert e["simulation"]["mode"] == "repetition" and e["simulation"]["en_cours"]
    assert set(e["processus"]) == {"simulation", "faux_slam", "navigation"}
    assert attendre(lambda: len(faux_bin.pids()) == 5)        # 2 + 1 + 2 processus longs
    dossier = lieux / "demo"
    appels = faux_bin.appels()
    assert f"g1-monde simuler --lieu {dossier} --etage rdc --sans-fenetre --jumeau" in appels
    assert f"g1-slam faux-service --jumeau --lieu {dossier} --etage rdc --bruit 0.01" in appels
    assert f"g1-guide navigation --lieu {dossier} --etage rdc --simu --localisation unitree" in appels
    with client.websocket_connect("/ws/etat") as ws:
        m = ws.receive_json()
    assert m["mode"] == "repetition" and m["reperage"] is None and m["pont"] is None
    assert m["simulation"] == {"lieu": "demo", "etage": "rdc", "en_cours": True}
    assert m["robot"] is None                    # pas de position sur la carte avant le repérage
    e = client.get("/api/robot/etat").json()
    assert (e["mode"], e["lieu"], e["etage"], e["repere"]) == ("repetition", "demo", "rdc", False)
    assert "relais de position" in e["message"]
    # « Y aller » avant le repérage : 409
    assert "Repérez d'abord le robot" in _erreur(client.post("/api/guide/aller", json={"cible": "b204"}), 409)["detail"]
    # repérer sans ROS 2 : 503 ; pour un autre étage : 409 ; x seul : 400
    assert "ROS 2" in _erreur(client.post("/api/robot/reperer", json={"lieu": "demo", "etage": "rdc"}), 503)["detail"]
    _erreur(client.post("/api/robot/reperer", json={"lieu": "demo", "etage": "rdc", "x": 2.0}), 400)
    # téléopération permise en répétition (passe par /cmd_vel puis le pont) : ici 503, faute de ROS 2
    _erreur(client.post("/api/simulation/teleop", json={"vx": 0.2}), 503)
    pids = faux_bin.pids()
    r = client.post("/api/simulation/arreter")
    assert r.status_code == 200 and not r.json()["simulation"]["en_cours"]
    assert attendre(lambda: not any(processus_vivant(p) for p in pids), 10)
    assert client.get("/api/robot/etat").json()["mode"] is None


def test_reperer_refus(client, faux_bin):
    _generer(client)
    corps = {"lieu": "demo", "etage": "rdc"}
    assert "Aucune navigation" in _erreur(client.post("/api/robot/reperer", json=corps), 409)["detail"]
    assert client.post("/api/simulation/demarrer", json=corps).status_code == 200      # mode simu
    assert "Gazebo" in _erreur(client.post("/api/robot/reperer", json=corps), 409)["detail"]
    e = client.get("/api/robot/etat").json()
    assert e["mode"] == "simu" and e["localisation"] == "simu"
    client.post("/api/simulation/arreter")
    assert _demarrer(client, "repetition").status_code == 200
    _erreur(client.post("/api/robot/reperer", json={"lieu": "nulle_part", "etage": "rdc"}), 404)
    _erreur(client.post("/api/robot/reperer", json={"lieu": "demo", "etage": "r9"}), 404)
    for mauvais in ({"x": 1.0, "y": 2.0}, {"cap": 0.5}, {"x": 1.0, "y": 2.0, "cap": 9.0}):
        _erreur(client.post("/api/robot/reperer", json={**corps, **mauvais}), 400)
    _erreur(client.post("/api/robot/reperer", json={**corps, "x": "loin"}), 422)
    client.post("/api/simulation/arreter")


def test_arret_sans_ros(client):
    assert "ROS 2" in _erreur(client.post("/api/robot/arret", json={"verrou": True}), 503)["detail"]
    _erreur(client.post("/api/robot/arret", json={}), 422)


@pytest.fixture
def robot_branche(monkeypatch, faux_bin):
    """Le « câble » est lo (son carrier vaut 1), le terminal est « relié au robot », g1-jetson est faux."""
    monkeypatch.setenv("ATELIER_INTERFACE_ROBOT", "lo")
    monkeypatch.setenv("CYCLONEDDS_URI", '<CycloneDDS><Domain><General><Interfaces><NetworkInterface name="lo"/>'
                                         '</Interfaces></General></Domain></CycloneDDS>')
    monkeypatch.setenv("ROS_DOMAIN_ID", "0")
    monkeypatch.delenv("G1_SLAM_FAUX", raising=False)
    faux_bin.ecrire("g1-jetson", FAUX_JETSON)
    return faux_bin


def test_mode_robot(client, lieux, robot_branche):
    _generer(client)
    r = _demarrer(client, "robot")
    assert r.status_code == 200, r.text
    assert r.json()["simulation"]["mode"] == "robot" and r.json()["simulation"]["en_cours"]
    assert f"g1-jetson demarrer --lieu {lieux / 'demo'} --etage rdc" in robot_branche.appels()
    assert client.get("/api/robot/etat").json()["mode"] == "robot"
    with client.websocket_connect("/ws/etat") as ws:
        assert ws.receive_json()["mode"] == "robot"
    # une seconde fois : refusé ; flèches : refusées (le vrai robot se pilote à sa télécommande)
    _erreur(_demarrer(client, "repetition"), 409)
    assert "télécommande" in _erreur(client.post("/api/simulation/teleop", json={"vx": 0.2}), 409)["detail"]
    assert "Repérez" in _erreur(client.post("/api/guide/aller", json={"cible": "b204"}), 409)["detail"]
    r = client.post("/api/simulation/arreter")
    assert r.status_code == 200 and not r.json()["simulation"]["en_cours"]
    assert robot_branche.appels()[-1] == "g1-jetson arreter"
    assert client.get("/api/robot/etat").json()["mode"] is None


def test_mode_robot_refus(client, robot_branche, monkeypatch):
    _generer(client)
    monkeypatch.setenv("FAUX_ECHEC", "1")
    d = _erreur(_demarrer(client, "robot"), 502)
    assert "ne répond pas" in d["detail"] and "g1-jetson" in d["sortie"]
    monkeypatch.delenv("FAUX_ECHEC")
    monkeypatch.setenv("ROS_DOMAIN_ID", "63")
    assert "terminal relié au robot" in _erreur(_demarrer(client, "robot"), 409)["detail"]
    monkeypatch.setenv("ATELIER_INTERFACE_ROBOT", "port_absent0")
    assert "Robot non détecté" in _erreur(_demarrer(client, "robot"), 409)["detail"]
    monkeypatch.setenv("G1_SLAM_FAUX", "1")
    assert "interdit" in _erreur(_demarrer(client, "robot"), 409)["detail"]
    robot_branche.retirer("g1-jetson")
    monkeypatch.delenv("G1_SLAM_FAUX")
    monkeypatch.setenv("ATELIER_INTERFACE_ROBOT", "lo")
    monkeypatch.setenv("ROS_DOMAIN_ID", "0")
    assert "g1-jetson" in _erreur(_demarrer(client, "robot"), 503)["detail"]
    # seul le premier essai (échec du faux g1-jetson) a lancé la commande : les refus passent avant
    assert sum(a.startswith("g1-jetson demarrer") for a in robot_branche.appels()) == 1
