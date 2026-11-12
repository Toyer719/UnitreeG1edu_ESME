"""Tests des routes du scan intégré (sections 9.7 et 12.4 du plan) et de la téléopération, sans ROS 2.
Vague 5 : plus de revue de la reconnaissance ; le nuage 3D d'une session (GET /api/scan/nuage) et
l'adoption qui donne à l'étage sa carte, son nuage et sa carte extrudée.

fastapi.testclient sur une copie complète de lieux/demo ; g1-scan est le faux de
test_serveur_scan_communs (sessions réelles écrites par atelier.lieu, processus détachés réels),
ou des sessions d'exemple (atelier/tests/outils_scan.py). Ni Gazebo, ni robot, ni réseau.
"""
import json
import math
import os
import time

import pytest

from atelier import lieu as L

from .outils_scan import creer_session_exemple
from .test_serveur_communs import lire_png
from .test_serveur_scan_communs import (attendre, attendre_etat, client_scan, faux_bin, faux_scan,  # noqa: F401
                                        journaux, lieux_scan, processus_vivant)


def _erreur(r, statut):
    """La réponse est une erreur au format de l'Atelier, en français."""
    assert r.status_code == statut, r.text
    d = r.json()
    assert isinstance(d["detail"], str) and d["detail"]
    return d


def _appels(faux, sous_commande=None):
    """Appels du faux g1-scan venus du serveur (sans les processus de session qu'il lance lui-même)."""
    appels = [a for a in faux.appels() if a.startswith("g1-scan ") and not a.startswith("g1-scan _session")]
    if sous_commande:
        appels = [a for a in appels if a.split()[1] == sous_commande]
    return appels


def _demarrer(client, **champs):
    corps = {"lieu": "demo", "etage": "rdc", "mode": "simu", **champs}
    return client.post("/api/scan/demarrer", json=corps)


def _pid_session(lieux, ident):
    return L.lire_session(lieux / "demo", ident)["processus"]["pid"]


# ---------------------------------------------------------------- le parcours complet

def test_scan_simu_de_bout_en_bout(client_scan, lieux_scan, faux_scan):
    c, dossier = client_scan, lieux_scan / "demo"
    debut = time.monotonic()
    r = _demarrer(c, nom="Essai du couloir")
    assert r.status_code == 200, r.text
    assert time.monotonic() - debut < 5
    e = r.json()
    s = e["session"]
    assert e["actif"] and e["lieu"] == "demo" and s["etat"] == "en_cours" and s["mode"] == "simu"
    assert s["nom"] == "Essai du couloir" and s["vivant"] is True and "session: " + s["id"] in r.json()["sortie"]
    assert _appels(faux_scan) == [f"g1-scan demarrer --lieu {dossier} --etage rdc --mode simu --nom Essai du couloir"]
    ident = s["id"]
    pid = _pid_session(lieux_scan, ident)

    # l'état sans lieu : celui du dernier scan démarré par le serveur
    assert c.get("/api/scan/etat").json()["session"]["id"] == ident
    # l'aperçu en direct : PNG et JSON, jamais en cache, qui avancent
    assert attendre(lambda: c.get("/api/scan/apercu.json?lieu=demo").status_code == 200, 10)
    r = c.get("/api/scan/apercu.json?lieu=demo")
    assert r.headers["cache-control"] == "no-store" and r.headers["content-type"].startswith("application/json")
    a1 = r.json()
    assert a1["session"] == ident and a1["points"] and a1["robot"] and set(a1["bornes"]) == {"xmin", "ymin", "xmax", "ymax"}
    r = c.get(f"/api/scan/apercu.png?lieu=demo&session={ident}")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.headers["cache-control"] == "no-store"
    image = lire_png(r.content)
    assert image.shape == (a1["hauteur"], a1["largeur"]) and (image == 0).any()
    assert attendre(lambda: c.get("/api/scan/apercu.json?lieu=demo").json()["statistiques"]["distance_m"]
                    > a1["statistiques"]["distance_m"], 10), "l'aperçu n'avance pas"
    # le scan est rangé parmi les processus du serveur (« Ce qui tourne »)
    p = c.get("/api/simulation/etat").json()["processus"]["scan"]
    assert p["en_cours"] and p["session"] == ident and p["pid"] == pid

    # « Fin » : la réponse arrive quand l'enregistrement est fermé, le traitement continue
    r = c.post("/api/scan/arreter", json={"lieu": "demo"})
    assert r.status_code == 200, r.text
    assert r.json()["session"]["fin"] is not None and r.json()["session"]["etat"] in ("traitement", "termine")
    assert _appels(faux_scan, "arreter") == [f"g1-scan arreter --lieu {dossier} --session {ident}"]
    vus = set()

    def suivre():
        s = c.get("/api/scan/etat?lieu=demo").json()["session"]
        vus.add((s["etat"], s["etape"]))
        return s["etat"] == "termine"
    assert attendre(suivre, 20, 0.05)
    assert ("traitement", "nuage") in vus or ("traitement", "carte_2d") in vus, vus
    assert not any(etape in ("reconnaissance", "monde") for _, etape in vus)
    e = c.get("/api/scan/etat?lieu=demo").json()
    assert not e["actif"] and e["session"]["progression"] == 100
    assert all(e["session"]["fichiers"].values()), e["session"]["fichiers"]
    assert attendre(lambda: not processus_vivant(pid), 10), "le processus de la session a survécu"
    p = c.get("/api/simulation/etat").json()["processus"]["scan"]
    assert not p["en_cours"] and p["code"] == 0

    # historique
    liste = c.get("/api/scan/sessions?lieu=demo").json()
    assert [x["id"] for x in liste] == [ident] and liste[0]["fichiers"]["nuage_affichage"]
    assert liste[0]["interrompue"] is False

    # résultat : carte 2D, nuage 3D, rapport ; plus de reconnaissance ni de monde du scan
    base = f"/api/scan/sessions/{ident}"
    info = c.get(base + "/carte.yaml?lieu=demo").json()
    assert info["image"] == "carte.pgm" and info["bornes"]["xmax"] > 29
    carte = lire_png(c.get(base + "/carte.png?lieu=demo").content)
    assert carte.shape == (info["hauteur"], info["largeur"])
    r = c.get(f"/api/scan/nuage?lieu=demo&session={ident}")
    assert r.status_code == 200 and r.headers["content-type"] == "application/octet-stream"
    assert int(r.headers["x-nuage-points"]) * 12 == len(r.content) > 0 and r.headers["x-nuage-source"] == "scan"
    assert c.get(base + "/rapport?lieu=demo").json()["comparaison"]["recouvrement"] == pytest.approx(0.987)
    for retiree in ("/reconnaissance?lieu=demo", "/monde?lieu=demo"):
        assert c.get(base + retiree).status_code == 404
    assert c.put(base + "/reconnaissance?lieu=demo", json={"a_garder": {}}).status_code in (404, 405)

    # « Utiliser cette carte » : la carte, le nuage, et le monde de simulation tiré de la carte
    ancien = L.chemin_monde(dossier, "rdc").read_text()
    r = c.post(base + "/adopter?lieu=demo", json={"monde": True})          # monde : accepté, sans effet
    assert r.status_code == 200, r.text
    assert r.json()["adopte"] is True and "adopté" in r.json()["sortie"]
    assert _appels(faux_scan, "adopter") == [f"g1-scan adopter --lieu {dossier} --session {ident}"]
    assert L.charger_fiche(dossier).etage("rdc").source_carte == "scan"
    nouveau = L.charger_monde(dossier, "rdc")
    assert nouveau.murs == [] and nouveau.objets == [] and nouveau.carte_extrudee is not None
    assert (dossier / "scans" / ident / "monde_remplace.monde.yaml").read_text() == ancien
    assert c.get("/api/scan/etat?lieu=demo").json()["session"]["adoption"]["monde"] is True
    r = c.get("/api/lieux/demo/etages/rdc/nuage")
    assert r.status_code == 200 and r.headers["x-nuage-session"] == ident
    r = c.get("/api/lieux/demo/etages/rdc/monde/maillage")
    assert r.status_code == 200 and r.headers["content-type"] == "model/stl" and len(r.content) > 84


def test_exploration_finit_seule(client_scan, lieux_scan, faux_scan, monkeypatch):
    monkeypatch.setenv("FAUX_SCAN_TOURS", "6")
    r = _demarrer(c := client_scan, explorer=True)
    assert r.status_code == 200, r.text
    assert _appels(faux_scan)[0].endswith("--mode simu --explorer")
    e = attendre_etat(c, ("termine",), 30)
    assert e["session"]["explorer"] is True
    assert _appels(faux_scan, "arreter") == []          # personne n'a cliqué sur « Fin »


# ---------------------------------------------------------------- mode robot et répétition

def test_mode_robot_sans_cable(client_scan, faux_scan, monkeypatch):
    monkeypatch.setenv("ATELIER_INTERFACE_ROBOT", "absente0")
    d = _erreur(_demarrer(client_scan, mode="robot"), 409)
    assert d["detail"].startswith("Robot non détecté : branchez le câble") and "robot.sh" in d["detail"]
    assert "absente0" in d["detail"] and "Répétition sans robot" in d["detail"]
    assert _appels(faux_scan) == []                     # rien n'a été lancé


def test_mode_robot_avec_cable(client_scan, lieux_scan, faux_scan, monkeypatch):
    monkeypatch.setenv("ATELIER_INTERFACE_ROBOT", "lo")     # « câble branché » : lo a toujours un porteur
    r = _demarrer(client_scan, mode="robot")
    assert r.status_code == 200, r.text
    s = r.json()["session"]
    assert s["mode"] == "robot" and not s["repetition"] and s["carte_unitree"] == f"rdc_{s['id']}.pcd"
    assert s["sujets"]["nuage"] == "/unitree/slam_mapping/points"
    # le vrai robot ne se pilote pas depuis l'Atelier : pas de téléopération
    d = _erreur(client_scan.post("/api/simulation/teleop", json={"vx": 0.2}), 409)
    assert "télécommande" in d["detail"]
    client_scan.post("/api/scan/arreter", json={"lieu": "demo", "session": s["id"]})
    attendre_etat(client_scan, ("termine",))


def test_repetition_sans_robot(client_scan, faux_scan, monkeypatch):
    monkeypatch.setenv("ATELIER_INTERFACE_ROBOT", "absente0")   # pas de câble : la répétition n'en a pas besoin
    r = _demarrer(client_scan, mode="robot", repetition=True, explorer=True)
    assert r.status_code == 200, r.text
    assert _appels(faux_scan)[0].endswith("--mode robot --repetition --explorer")
    s = r.json()["session"]
    assert s["repetition"] and s["sujets"]["odom"] == "/unitree/slam_mapping/odom"
    # robot simulé : la téléopération passe le premier contrôle (puis 503 : pas de ROS 2 dans ce test)
    d = _erreur(client_scan.post("/api/simulation/teleop", json={"vx": 0.2}), 503)
    assert "ROS 2" in d["detail"]
    client_scan.post("/api/scan/arreter", json={"lieu": "demo"})
    attendre_etat(client_scan, ("termine",))


# ---------------------------------------------------------------- refus avant de lancer g1-scan

def test_demarrer_refuse_ce_qui_ne_peut_pas_marcher(client_scan, lieux_scan, faux_scan):
    c = client_scan
    assert "inconnu" in _erreur(_demarrer(c, mode="drone"), 400)["detail"]
    assert "Répétition" in _erreur(_demarrer(c, repetition=True), 400)["detail"]
    assert "télécommande" in _erreur(_demarrer(c, mode="robot", explorer=True), 400)["detail"]
    assert "n'existe pas" in _erreur(_demarrer(c, lieu="ailleurs"), 404)["detail"]
    assert "étages : rdc" in _erreur(_demarrer(c, etage="cave"), 404)["detail"]
    assert "true ou false" in _erreur(_demarrer(c, explorer="oui"), 422)["detail"]
    d = _erreur(c.post("/api/scan/demarrer", json={"lieu": "demo", "etage": "rdc"}), 422)
    assert d["erreurs"] == ["il manque le champ « mode »"]
    assert "100 caractères" in _erreur(_demarrer(c, nom="x" * 101), 400)["detail"]
    # pas de monde Gazebo : le robot simulé n'a rien à scanner
    sdf = L.chemin_sdf(lieux_scan / "demo", "rdc")
    sdf.rename(sdf.with_suffix(".sdf.bak"))
    assert "Simulation › Dessiner" in _erreur(_demarrer(c), 409)["detail"]
    sdf.with_suffix(".sdf.bak").rename(sdf)
    # exploration sans couloir
    itin = lieux_scan / "demo" / "itineraires.yaml"
    sauvegarde = itin.read_text()
    donnees = c.get("/api/lieux/demo/itineraires").json()
    donnees["couloirs"] = []
    assert c.put("/api/lieux/demo/itineraires", json=donnees).status_code == 200
    assert "itinéraires (Placer)" in _erreur(_demarrer(c, explorer=True), 409)["detail"]
    itin.write_text(sauvegarde)
    assert _appels(faux_scan) == []
    # un scan déjà en cours dans le lieu
    s = creer_session_exemple(lieux_scan / "demo", "en_cours")
    d = _erreur(_demarrer(c), 409)
    assert "déjà en cours" in d["detail"] and "Fin" in d["detail"] and s["nom"] in d["detail"]


def test_simulation_d_un_autre_lieu(client_scan, lieux_scan, faux_scan):
    c = client_scan
    assert c.post("/api/lieux", json={"id": "annexe", "nom": "Annexe"}).status_code == 201
    assert c.post("/api/lieux/annexe/etages/rdc/monde/generer").status_code == 200
    assert c.post("/api/simulation/demarrer", json={"lieu": "annexe", "etage": "rdc"}).status_code == 200
    d = _erreur(_demarrer(c), 409)
    assert "arrêtez la simulation" in d["detail"] and "annexe" in d["detail"]
    c.post("/api/simulation/arreter")
    assert _demarrer(c).status_code == 200
    c.post("/api/scan/arreter", json={"lieu": "demo"})
    attendre_etat(c, ("termine",))


def test_g1_scan_absent_ou_en_echec(client_scan, faux_scan, monkeypatch):
    monkeypatch.setenv("FAUX_SCAN_ECHEC", "demarrer")
    d = _erreur(_demarrer(client_scan), 502)
    assert "le faux g1-scan échoue exprès" in d["detail"] and "préparation" in d["sortie"]
    faux_scan.retirer("g1-scan")
    d = _erreur(_demarrer(client_scan), 503)
    assert "g1-scan" in d["detail"] and "pas encore installée" in d["detail"]


# ---------------------------------------------------------------- état, aperçu, sessions

def test_etat_et_apercu_sans_scan(client_scan, lieux_scan):
    c = client_scan
    assert "Précisez le lieu" in _erreur(c.get("/api/scan/etat"), 400)["detail"]
    e = c.get("/api/scan/etat?lieu=demo").json()
    assert e == {"version": 1, "lieu": "demo", "dossier_lieu": str(lieux_scan / "demo"), "sessions": 0,
                 "actif": False, "session": None}
    assert "Aucun scan" in _erreur(c.get("/api/scan/apercu.json?lieu=demo"), 404)["detail"]
    assert "Aucun scan" in _erreur(c.post("/api/scan/arreter", json={"lieu": "demo"}), 404)["detail"]
    assert c.get("/api/scan/sessions?lieu=demo").json() == []
    # une session qui vient d'être créée : pas encore d'aperçu
    s = L.creer_session(lieux_scan / "demo", "rdc", "simu")
    assert "quelques secondes" in _erreur(c.get("/api/scan/apercu.png?lieu=demo"), 404)["detail"]
    assert c.get("/api/scan/etat?lieu=demo").json()["session"]["id"] == s["id"]
    # identifiants de session refusés ou inconnus
    assert "AAAA-MM-JJ_HHhMM" in _erreur(c.get("/api/scan/etat?lieu=demo&session=../../x"), 400)["detail"]
    assert "n'existe pas" in _erreur(c.get("/api/scan/etat?lieu=demo&session=2020-01-01_10h00"), 404)["detail"]
    assert "AAAA" in _erreur(c.get("/api/scan/sessions/lieu.yaml/carte.png?lieu=demo"), 400)["detail"]
    assert "Adresse inconnue" in _erreur(c.get("/api/scan/sessions/..%2F..%2Fx/carte.png?lieu=demo"), 404)["detail"]
    assert _erreur(c.get("/api/scan/sessions?lieu=..%2Fdemo"), 400)


def test_liste_des_sessions(client_scan, lieux_scan):
    dossier = lieux_scan / "demo"
    a = creer_session_exemple(dossier, "termine")
    b = creer_session_exemple(dossier, "echec")
    illisible = dossier / "scans" / "2026-01-02_09h00"
    illisible.mkdir()
    (illisible / "session.json").write_text("{pas du json")
    liste = client_scan.get("/api/scan/sessions?lieu=demo").json()
    assert [s["id"] for s in liste] == [b["id"], a["id"], "2026-01-02_09h00"]
    assert liste[0]["etat"] == "echec" and "LiDAR" in liste[0]["message"]
    assert liste[1]["fichiers"]["nuage_affichage"] and liste[1]["interrompue"] is False
    assert liste[2]["illisible"] is True and liste[2]["erreurs"] and liste[2]["fichiers"]["carte"] is False
    # l'état d'une session choisie dans l'historique
    e = client_scan.get(f"/api/scan/etat?lieu=demo&session={a['id']}").json()
    assert e["session"]["id"] == a["id"] and e["session"]["etat"] == "termine"
    assert "illisible" in _erreur(client_scan.get("/api/scan/sessions/2026-01-02_09h00/rapport?lieu=demo"),
                                  422)["detail"]


def test_arreter_une_session_interrompue(client_scan, lieux_scan, faux_scan):
    """Processus de la session mort sans enregistrement : g1-scan arreter la passe en échec."""
    dossier = lieux_scan / "demo"
    s = L.creer_session(dossier, "rdc", "simu")
    L.maj_session(dossier, s["id"], etape="enregistrement", processus={"pid": 999999, "debut": 1, "hote": os.uname().nodename})
    e = client_scan.get("/api/scan/etat?lieu=demo").json()
    assert e["session"]["interrompue"] is True and e["actif"] is False
    r = client_scan.post("/api/scan/arreter", json={"lieu": "demo"})
    assert r.status_code == 200, r.text
    assert r.json()["session"]["etat"] == "echec" and "recommencez" in r.json()["session"]["message"]


# ---------------------------------------------------------------- adoption : refus

def test_adoption_refusee(client_scan, lieux_scan, faux_scan, monkeypatch):
    c, dossier = client_scan, lieux_scan / "demo"
    t = creer_session_exemple(dossier, "traitement")
    base = f"/api/scan/sessions/{t['id']}"
    assert "attendez" in _erreur(c.post(base + "/adopter?lieu=demo", json={}), 409)["detail"]
    assert c.get(base + "/carte.yaml?lieu=demo").status_code == 200        # la carte est déjà là
    assert "rapport" in _erreur(c.get(base + "/rapport?lieu=demo"), 404)["detail"]
    e = creer_session_exemple(dossier, "echec")
    d = _erreur(c.post(f"/api/scan/sessions/{e['id']}/adopter?lieu=demo", json={"monde": False}), 409)
    assert "échoué" in d["detail"] and "nouveau scan" in d["detail"]
    assert "carte 2D de ce scan" in _erreur(c.get(f"/api/scan/sessions/{e['id']}/carte.png?lieu=demo"), 404)["detail"]
    assert "true ou false" in _erreur(c.post(f"/api/scan/sessions/{e['id']}/adopter?lieu=demo",
                                             json={"monde": "oui"}), 422)["detail"]
    # adoption : g1-scan échoue
    f = creer_session_exemple(dossier, "termine")
    monkeypatch.setenv("FAUX_SCAN_ECHEC", "adopter")
    d = _erreur(c.post(f"/api/scan/sessions/{f['id']}/adopter?lieu=demo", json={}), 502)
    monkeypatch.delenv("FAUX_SCAN_ECHEC")
    assert "adopter le scan" in d["detail"] and d["sortie"]
    r = c.post(f"/api/scan/sessions/{f['id']}/adopter?lieu=demo", json={})
    assert r.status_code == 200 and r.json()["monde"] is True and r.json()["rapport"]["ok"] in (True, False)
    assert L.charger_fiche(dossier).etage("rdc").source_carte == "scan"
    assert r.json()["avertissements"] == []                                 # simulation : même repère


def test_adoption_robot_previent_du_repere(client_scan, lieux_scan, faux_scan):
    s = creer_session_exemple(lieux_scan / "demo", "termine", mode="robot")
    r = client_scan.post(f"/api/scan/sessions/{s['id']}/adopter?lieu=demo", json={})
    assert r.status_code == 200, r.text
    assert any("Replacez les salles" in a for a in r.json()["avertissements"])


# ---------------------------------------------------------------- avec le serveur

def test_le_scan_s_arrete_avec_le_serveur(lieux_scan, faux_scan):
    """Un scan démarré par l'Atelier, encore en enregistrement quand le serveur s'arrête : le serveur
    demande sa fin (g1-scan arreter) ; le traitement finit seul, et aucun processus ne reste."""
    from fastapi.testclient import TestClient
    from atelier.serveur.main import creer_app
    with TestClient(creer_app(ros=False)) as c:
        r = _demarrer(c)
        assert r.status_code == 200, r.text
        ident = r.json()["session"]["id"]
        pid = _pid_session(lieux_scan, ident)
        assert processus_vivant(pid)
    assert _appels(faux_scan, "arreter") == [f"g1-scan arreter --lieu {lieux_scan / 'demo'} --session {ident}"]
    assert attendre(lambda: L.lire_session(lieux_scan / "demo", ident)["etat"] == "termine", 20)
    assert attendre(lambda: not processus_vivant(pid), 10), "le processus de la session a survécu au serveur"


def test_scan_fini_ou_d_ailleurs_non_arrete_par_le_serveur(lieux_scan, faux_scan):
    """Une session que le serveur n'a pas démarrée (ligne de commande) n'est pas arrêtée avec lui."""
    from fastapi.testclient import TestClient
    from atelier.serveur.main import creer_app
    s = creer_session_exemple(lieux_scan / "demo", "en_cours")
    with TestClient(creer_app(ros=False)) as c:
        assert c.get("/api/scan/etat?lieu=demo").json()["actif"]
    assert _appels(faux_scan) == []
    assert L.lire_session(lieux_scan / "demo", s["id"])["etat"] == "en_cours"


# ---------------------------------------------------------------- téléopération sans ROS 2

def test_teleop_refusee_sans_robot_simule(client_scan, lieux_scan):
    c = client_scan
    d = _erreur(c.post("/api/simulation/teleop", json={"vx": 0.3}), 409)
    assert "simulation" in d["detail"] and "télécommande" in d["detail"]
    # un scan en mode robot (vrai G1) ne se téléopère pas
    creer_session_exemple(lieux_scan / "demo", "en_cours", mode="robot")
    c.get("/api/scan/etat?lieu=demo")
    _erreur(c.post("/api/simulation/teleop", json={"vx": 0.3}), 409)
    # valeurs refusées
    assert "nombre" in _erreur(c.post("/api/simulation/teleop", json={"vx": "vite"}), 422)["detail"]
    r = c.post("/api/simulation/teleop", content=b'{"vx": NaN}', headers={"Content-Type": "application/json"})
    assert "fini" in _erreur(r, 400)["detail"]


def test_teleop_avec_un_scan_simule_ou_la_simulation(client_scan, lieux_scan):
    c = client_scan
    s = creer_session_exemple(lieux_scan / "demo", "en_cours", mode="simu")
    c.get("/api/scan/etat?lieu=demo")                      # l'onglet Scan regarde ce lieu
    assert "ROS 2" in _erreur(c.post("/api/simulation/teleop", json={"vx": 0.3}), 503)["detail"]
    L.maj_session(lieux_scan / "demo", s["id"], etat="echec", message="arrêté (test)", fin=L.scans.instant())
    time.sleep(1.1)                                        # la réponse positive est gardée 1 s
    _erreur(c.post("/api/simulation/teleop", json={"vx": 0.3}), 409)
    # la simulation de l'Atelier suffit aussi
    assert c.post("/api/simulation/demarrer", json={"lieu": "demo", "etage": "rdc", "navigation": False}).status_code == 200
    _erreur(c.post("/api/simulation/teleop", json={"wz": -0.5}), 503)
    c.post("/api/simulation/arreter")


def test_limites_teleop_du_contrat():
    from atelier.serveur.routes.simulation import HOMME_MORT_S, LIMITES_TELEOP
    assert LIMITES_TELEOP == {"vx": 0.5, "vy": 0.25, "wz": 0.8} and HOMME_MORT_S == 0.5
    assert all(math.isfinite(v) for v in LIMITES_TELEOP.values())


def test_les_anciennes_routes_du_scan_sont_retirees(client_scan):
    """Contrat 9.7 : /api/scan/debut, /fin et /faux-service/arreter n'existent plus."""
    for route in ("/api/scan/debut", "/api/scan/fin", "/api/scan/faux-service/arreter"):
        assert client_scan.post(route, json={}).status_code in (404, 405), route
    assert json.dumps(client_scan.get("/api/scan/etat?lieu=demo").json()).count("g1_slam") == 0
