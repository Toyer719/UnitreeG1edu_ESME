"""Tests de l'API du serveur (contrat 4.4) avec fastapi.testclient, sur une copie de lieux/demo.

Ni ROS 2, ni Gazebo, ni robot : les commandes g1-* sont de fausses commandes (test_serveur_communs).
"""
import pytest

from atelier.lieu import charger_fiche, charger_itineraires, charger_monde, charger_salles, charger_zones

from .test_serveur_communs import (attendre, client, faux_bin, journaux, lieux, lire_png,  # noqa: F401
                                   processus_vivant)

DEMO = "/api/lieux/demo"
RDC = DEMO + "/etages/rdc"


def _erreur(r, statut):
    """La réponse est une erreur au format de l'Atelier, en français."""
    assert r.status_code == statut, r.text
    d = r.json()
    assert isinstance(d["detail"], str) and d["detail"]
    return d


# ---------------------------------------------------------------- lieux

def test_liste_et_fiche_du_lieu(client):
    r = client.get("/api/lieux")
    assert r.status_code == 200
    assert [l["id"] for l in r.json()] == ["demo"]
    assert r.json()[0]["nom"] == "Lycée démo"
    fiche = client.get(DEMO).json()
    assert fiche["id"] == "demo" and fiche["accueil"]["etage"] == "rdc"
    etage = fiche["etages"][0]
    assert etage["id"] == "rdc" and etage["a_monde"] and not etage["a_carte"] and not etage["a_sdf"]
    assert fiche["compte"] == {"salles": 6, "noeuds": 13, "zones": 2}


def test_lieu_ou_etage_inconnu(client):
    assert "n'existe pas" in _erreur(client.get("/api/lieux/inconnu"), 404)["detail"]
    assert "étages : rdc" in _erreur(client.get(DEMO + "/etages/r9/monde"), 404)["detail"]
    # un id mal formé ne peut pas sortir du dossier des lieux
    assert "identifiant" in _erreur(client.get("/api/lieux/..%2E"), 400)["detail"]
    assert "identifiant" in _erreur(client.get("/api/lieux/Demo"), 400)["detail"]
    assert "Adresse inconnue" in _erreur(client.get("/api/rien"), 404)["detail"]


def test_creer_un_lieu(client, lieux):
    r = client.post("/api/lieux", json={"id": "essai", "nom": "Lycée d'essai", "largeur": 12, "profondeur": 8})
    assert r.status_code == 201, r.text
    assert r.json()["etages"][0]["a_monde"]
    assert [l["id"] for l in client.get("/api/lieux").json()] == ["demo", "essai"]
    monde = client.get("/api/lieux/essai/etages/rdc/monde").json()
    assert monde["emprise"] == {"min": [0.0, 0.0], "max": [12.0, 8.0]}
    assert len(monde["murs"]) == 4
    assert (lieux / "essai" / "lieu.yaml").is_file()
    # deux fois le même : refusé, avec un conseil
    assert "existe déjà" in _erreur(client.post("/api/lieux", json={"id": "essai", "nom": "X"}), 409)["detail"]
    assert "identifiant" in _erreur(client.post("/api/lieux", json={"id": "Mon Lieu", "nom": "X"}), 400)["detail"]
    assert "nom" in _erreur(client.post("/api/lieux", json={"id": "vide", "nom": "  "}), 400)["detail"]
    d = _erreur(client.post("/api/lieux", json={"nom": "Sans id"}), 422)
    assert d["erreurs"] == ["il manque le champ « id »"]
    d = _erreur(client.post("/api/lieux", json={"id": "petit", "nom": "Petit", "largeur": 1}), 400)
    assert "trop petit" in d["detail"]


def test_fiche_du_lieu_ajout_d_etage(client, lieux):
    fiche = client.get(DEMO).json()
    donnees = {k: fiche[k] for k in ("version", "nom", "langue", "accueil", "carte_unitree")}
    donnees["etages"] = [{k: e[k] for k in ("id", "nom", "source_carte")} for e in fiche["etages"]]
    donnees["etages"].append({"id": "etage1", "nom": "Premier étage", "source_carte": "scan"})
    r = client.put(DEMO, json=donnees)
    assert r.status_code == 200, r.text
    assert "lieu.yaml" in r.json()["enregistre"] and "rapport" in r.json()
    assert [e.id for e in charger_fiche(lieux / "demo").etages] == ["rdc", "etage1"]
    # un étage sans monde : 404 qui dit quoi faire
    assert "Simulation › Dessiner" in _erreur(client.get(DEMO + "/etages/etage1/monde"), 404)["detail"]
    # fiche invalide : rien n'est écrit
    donnees["accueil"]["etage"] = "cave"
    d = _erreur(client.put(DEMO, json=donnees), 422)
    assert any("cave" in m for m in d["erreurs"])
    assert charger_fiche(lieux / "demo").accueil.etage == "rdc"


def test_verification_du_lieu(client):
    r = client.get(DEMO + "/verification").json()
    assert r["ok"] is True and r["erreurs"] == []
    assert any("carte" in m for m in r["avertissements"])


# ---------------------------------------------------------------- monde

def test_monde_aller_retour(client, lieux):
    monde = client.get(RDC + "/monde").json()
    assert len(monde["murs"]) == 18 and len(monde["objets"]) == 12 and len(monde["pietons"]) == 2
    monde["murs"].append({"id": "nouveau_mur", "de": [1.0, 2.0], "a": [3.5, 2.0], "epaisseur": 0.15, "hauteur": 2.5})
    monde["objets"].append({"id": "table_9", "type": "modele", "modele": "table", "centre": [3.0, 3.0], "cap": 0.5})
    monde["pietons"].append({"id": "pieton_3", "trajet": [[1, 1], [4, 1]], "vitesse": 0.7, "aller_retour": False})
    r = client.put(RDC + "/monde", json=monde)
    assert r.status_code == 200, r.text
    assert r.json()["enregistre"] == ["mondes/rdc.monde.yaml"]
    relu = client.get(RDC + "/monde").json()
    assert relu["murs"][-1]["id"] == "nouveau_mur" and relu["murs"][-1]["a"] == [3.5, 2.0]
    m = charger_monde(lieux / "demo", "rdc")
    assert m.element("table_9").cap == 0.5 and m.element("pieton_3").aller_retour is False


def test_monde_invalide_refuse_sans_rien_ecrire(client, lieux):
    avant = (lieux / "demo" / "mondes" / "rdc.monde.yaml").read_text()
    monde = client.get(RDC + "/monde").json()
    monde["murs"][0]["epaisseur"] = -1
    monde["objets"].append({"id": "ext_sud", "type": "cylindre", "centre": [2, 2], "rayon": 0.2, "hauteur": 1})
    d = _erreur(client.put(RDC + "/monde", json=monde), 422)
    assert "corrigez" in d["detail"]
    assert any("epaisseur" in m and "ext_sud" in m for m in d["erreurs"]), d["erreurs"]
    assert (lieux / "demo" / "mondes" / "rdc.monde.yaml").read_text() == avant
    monde = client.get(RDC + "/monde").json()
    monde["murs"].append({"id": "dehors", "de": [1, 1], "a": [40, 1], "epaisseur": 0.15, "hauteur": 2.5})
    d = _erreur(client.put(RDC + "/monde", json=monde), 422)
    assert any("emprise" in m for m in d["erreurs"])
    assert _erreur(client.put(RDC + "/monde", json=[1, 2]), 422)["erreurs"]


# ---------------------------------------------------------------- salles, itinéraires, zones

def test_salles_aller_retour(client, lieux):
    salles = client.get(DEMO + "/salles").json()
    assert [s["id"] for s in salles][:2] == ["accueil", "vie_scolaire"]
    salles.append({"id": "labo", "nom": "Labo", "etage": "rdc", "pose": {"x": 12.0, "y": 13.0, "theta": 1.5708},
                   "alias": [], "phrase_arrivee": ""})
    r = client.put(DEMO + "/salles", json=salles)
    assert r.status_code == 200 and r.json()["enregistre"] == ["salles.yaml"]
    assert charger_salles(lieux / "demo")[-1].id == "labo"
    # sans synchroniser, la règle salle ↔ nœud est signalée par le rapport
    assert any("labo" in m for m in r.json()["rapport"]["erreurs"])
    assert "labo" not in charger_itineraires(lieux / "demo").noeuds


def test_salles_synchronisees_avec_noeuds_et_accueil(client, lieux):
    salles = client.get(DEMO + "/salles").json()
    salles.append({"id": "labo", "nom": "Labo", "etage": "rdc", "pose": {"x": 12.0, "y": 13.0, "theta": 0.0}})
    salles[0]["pose"] = {"x": 3.0, "y": 10.0, "theta": 0.3}          # l'accueil bouge
    r = client.put(DEMO + "/salles?synchroniser=true", json=salles)
    assert r.status_code == 200, r.text
    # vague 4 (section 11.2) : le point principal (implicite : la salle accueil) recopie aussi sa pose
    # dans depart_robot du monde de son étage
    assert r.json()["enregistre"] == ["salles.yaml", "itineraires.yaml", "lieu.yaml", "mondes/rdc.monde.yaml"]
    itin = charger_itineraires(lieux / "demo")
    assert (itin.noeuds["labo"].x, itin.noeuds["labo"].y) == (12.0, 13.0)
    assert (itin.noeuds["accueil"].x, itin.noeuds["accueil"].y) == (3.0, 10.0)
    accueil = charger_fiche(lieux / "demo").accueil
    assert (accueil.x, accueil.y, accueil.theta) == (3.0, 10.0, 0.3)
    depart = charger_monde(lieux / "demo", "rdc").depart_robot
    assert (depart.x, depart.y, depart.theta) == (3.0, 10.0, 0.3)
    assert "etiquettes" not in (lieux / "demo" / "salles.yaml").read_text(encoding="utf-8")   # reste implicite
    assert not any("labo" in m and "nœud" in m for m in r.json()["rapport"]["erreurs"])
    # rien à changer : seul salles.yaml est écrit
    r = client.put(DEMO + "/salles?synchroniser=true", json=salles)
    assert r.json()["enregistre"] == ["salles.yaml"]


def test_salles_invalides(client, lieux):
    salles = client.get(DEMO + "/salles").json()
    del salles[1]["pose"]["theta"]
    salles.append(dict(salles[2]))         # id en double
    d = _erreur(client.put(DEMO + "/salles", json=salles), 422)
    assert any("theta" in m for m in d["erreurs"]), d["erreurs"]
    assert len(charger_salles(lieux / "demo")) == 6


def test_itineraires_aller_retour(client, lieux):
    itin = client.get(DEMO + "/itineraires").json()
    assert len(itin["noeuds"]) == 13 and ["accueil", "hall_sud"] in itin["couloirs"]
    itin["noeuds"]["n_1"] = {"etage": "rdc", "x": 2.5, "y": 8.5}
    itin["couloirs"].append(["hall_sud", "n_1"])
    r = client.put(DEMO + "/itineraires", json=itin)
    assert r.status_code == 200, r.text
    assert charger_itineraires(lieux / "demo").voisins("n_1") == ["hall_sud"]
    itin["couloirs"].append(["n_1", "inconnu"])
    d = _erreur(client.put(DEMO + "/itineraires", json=itin), 422)
    assert any("inconnu" in m for m in d["erreurs"])


def test_itineraires_couloir_trop_long_signale(client):
    itin = client.get(DEMO + "/itineraires").json()
    itin["couloirs"].append(["hall_sud", "infirmerie"])          # 12,5 m
    r = client.put(DEMO + "/itineraires", json=itin)
    assert r.status_code == 200
    assert any("8 m" in m or "8 m" in m.replace(" ", " ") for m in r.json()["rapport"]["erreurs"]), r.json()["rapport"]


def test_zones_aller_retour(client, lieux):
    zones = client.get(DEMO + "/zones").json()
    assert len(zones["interdites"]) == 1 and len(zones["lentes"]) == 1
    zones["lentes"].append({"etage": "rdc", "polygone": [[10, 6], [12, 6], [12, 8]], "nom": "", "vitesse_max": 0.3})
    zones["interdites"].append({"etage": "rdc", "polygone": [[20, 1], [21, 1], [21, 2], [20, 2]]})
    r = client.put(DEMO + "/zones", json=zones)
    assert r.status_code == 200, r.text
    z = charger_zones(lieux / "demo")
    assert len(z.lentes) == 2 and z.lentes[1].vitesse_max == 0.3 and len(z.interdites) == 2
    zones["interdites"].append({"etage": "rdc", "polygone": [[1, 1], [2, 2]]})
    assert _erreur(client.put(DEMO + "/zones", json=zones), 422)["erreurs"]


# ---------------------------------------------------------------- carte

def test_carte_absente(client):
    assert "Simulation › Dessiner" in _erreur(client.get(RDC + "/carte.png"), 404)["detail"]
    assert "Simulation › Dessiner" in _erreur(client.get(RDC + "/carte.yaml"), 404)["detail"]


def test_fabriquer_la_carte_avec_g1_monde(client, lieux, faux_bin):
    r = client.post(RDC + "/monde/generer")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] and d["fichiers"] == {"sdf": True, "carte": True, "interdit": True}
    assert "carte fabriquée" in d["sortie"]
    assert faux_bin.appels() == [f"g1-monde generer --lieu {lieux / 'demo'} --etage rdc"]
    info = client.get(RDC + "/carte.yaml").json()
    assert (info["largeur"], info["hauteur"]) == (602, 402)
    assert info["bornes"]["xmin"] == pytest.approx(-0.05) and info["bornes"]["ymax"] == pytest.approx(20.05)
    assert info["resolution"] == 0.05 and info["image"] == "rdc.pgm"
    r = client.get(RDC + "/carte.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    image = lire_png(r.content)
    assert image.shape == (402, 602)
    assert (image[0, 1:] == 0).all() and (image[1:, 0] == 205).all() and image[200, 300] == 254
    assert client.get(DEMO).json()["etages"][0]["a_carte"]


def test_fabriquer_la_carte_erreurs(client, lieux, faux_bin, monkeypatch):
    monkeypatch.setenv("FAUX_ECHEC", "1")
    d = _erreur(client.post(RDC + "/monde/generer"), 422)
    assert "code de sortie 3" in d["detail"] and "sort de l'emprise" in d["sortie"]
    monkeypatch.delenv("FAUX_ECHEC")
    faux_bin.retirer("g1-monde")
    assert "g1-monde" in _erreur(client.post(RDC + "/monde/generer"), 503)["detail"]
    (lieux / "demo" / "mondes" / "rdc.monde.yaml").unlink()
    assert "dessinez-le" in _erreur(client.post(RDC + "/monde/generer"), 409)["detail"]


def test_fabriquer_la_carte_avec_le_vrai_g1_monde(lieux, journaux, monkeypatch):
    """Avec la vraie commande de l'agent Monde, si elle est déjà installée."""
    import atelier
    from atelier.serveur.processus import commande
    monkeypatch.delenv("ATELIER_BIN", raising=False)
    if commande("g1-monde") is None:
        pytest.skip(f"g1-monde n'est pas encore dans {atelier.RACINE / 'bin'} (agent Monde)")
    from fastapi.testclient import TestClient
    from atelier.serveur.main import creer_app
    with TestClient(creer_app(ros=False)) as c:
        r = c.post(RDC + "/monde/generer")
        assert r.status_code == 200, r.text
        assert r.json()["fichiers"]["carte"] and r.json()["fichiers"]["sdf"]
        info = c.get(RDC + "/carte.yaml").json()
        image = lire_png(c.get(RDC + "/carte.png").content)
        assert image.shape == (info["hauteur"], info["largeur"])
        assert (image == 0).any() and (image == 254).any()    # des murs et de l'espace libre


# ---------------------------------------------------------------- simulation et guide

def _generer(client):
    assert client.post(RDC + "/monde/generer").status_code == 200


def test_simulation_demarrer_et_arreter(client, lieux, faux_bin):
    d = _erreur(client.post("/api/simulation/demarrer", json={"lieu": "demo", "etage": "rdc"}), 409)
    assert "Dessiner" in d["detail"] and "Refaire la carte" in d["detail"]      # vocabulaire du ruban (vague 5)
    _generer(client)
    r = client.post("/api/simulation/demarrer", json={"lieu": "demo", "etage": "rdc"})
    assert r.status_code == 200, r.text
    e = r.json()
    assert e["simulation"]["en_cours"] and e["simulation"]["avertissements"] == []
    assert e["processus"]["simulation"]["en_cours"] and e["processus"]["navigation"]["en_cours"]
    assert attendre(lambda: len(faux_bin.pids()) == 4)
    appels = faux_bin.appels()
    dossier = lieux / "demo"
    assert f"g1-monde simuler --lieu {dossier} --etage rdc --sans-fenetre" in appels
    assert f"g1-guide navigation --lieu {dossier} --etage rdc --simu" in appels
    # une deuxième simulation est refusée
    assert "tourne déjà" in _erreur(client.post("/api/simulation/demarrer", json={"lieu": "demo", "etage": "rdc"}), 409)["detail"]
    # le WebSocket montre les processus et les deux piétons du demo
    with client.websocket_connect("/ws/etat") as ws:
        m = ws.receive_json()
    assert m["simulation"] == {"lieu": "demo", "etage": "rdc", "en_cours": True}
    assert [p["id"] for p in m["pietons"]] == ["pieton_sud", "pieton_nord"]
    assert m["processus"]["simulation"]["en_cours"]
    # journal de chaque commande
    assert attendre(lambda: "simulation lancée" in open(e["processus"]["simulation"]["journal"]).read())
    # arrêt : tout le groupe de chaque commande disparaît, enfants compris
    pids = faux_bin.pids()
    assert all(processus_vivant(p) for p in pids)
    r = client.post("/api/simulation/arreter")
    assert r.status_code == 200
    assert not r.json()["simulation"]["en_cours"]
    assert not r.json()["processus"]["navigation"]["en_cours"]
    assert attendre(lambda: not any(processus_vivant(p) for p in pids), 5)
    etat = client.get("/api/simulation/etat").json()
    assert etat["processus"]["simulation"]["arret_demande"]


def test_simulation_sans_g1_guide(client, faux_bin):
    _generer(client)
    faux_bin.retirer("g1-guide")
    e = client.post("/api/simulation/demarrer", json={"lieu": "demo", "etage": "rdc"}).json()
    assert "navigation" not in e["processus"]
    assert "g1-guide" in e["simulation"]["avertissements"][0]
    client.post("/api/simulation/arreter")


def test_simulation_demande_incomplete(client):
    d = _erreur(client.post("/api/simulation/demarrer", json={"lieu": "demo"}), 422)
    assert d["erreurs"] == ["il manque le champ « etage »"]
    _erreur(client.post("/api/simulation/demarrer", json={"lieu": "nulle_part", "etage": "rdc"}), 404)


def test_guide_sans_ros(client, faux_bin):
    d = _erreur(client.post("/api/guide/aller", json={"cible": "b204"}), 503)
    assert "ROS 2" in d["detail"]
    _erreur(client.post("/api/guide/aller", json={"cible": "B 204"}), 400)
    # l'arrêt passe alors par la commande g1-guide stop
    r = client.post("/api/guide/stop")
    assert r.status_code == 200 and r.json()["par"] == "g1-guide stop"
    assert faux_bin.appels() == ["g1-guide stop"]


def test_guide_cible_inconnue_du_lieu_simule(client):
    _generer(client)
    client.post("/api/simulation/demarrer", json={"lieu": "demo", "etage": "rdc"})
    d = _erreur(client.post("/api/guide/aller", json={"cible": "piscine"}), 404)
    assert "piscine" in d["detail"]
    # une salle connue passe la vérification (puis 503 : pas de ROS 2 dans ce test)
    _erreur(client.post("/api/guide/aller", json={"cible": "b204"}), 503)
    _erreur(client.post("/api/guide/aller", json={"cible": "couloir_nord_1"}), 503)
    client.post("/api/simulation/arreter")


# Scan intégré (vague 2) : atelier/tests/test_serveur_scan*.py


# ---------------------------------------------------------------- état, WebSocket, fichiers web

def test_etat_du_serveur(client, lieux):
    e = client.get("/api/etat").json()
    assert e["commandes"] == {"g1-lieu": False, "g1-monde": True, "g1-guide": True, "g1-slam": True,
                             "g1-scan": False}
    assert e["ros"]["actif"] is False and e["lieux"] == str(lieux)


def test_websocket_etat(client):
    with client.websocket_connect("/ws/etat") as ws:
        messages = [ws.receive_json() for _ in range(3)]
    for m in messages:
        assert {"robot", "guide", "pietons", "processus"} <= set(m)
        assert m["robot"] is None and m["pietons"] == [] and m["simulation"] is None


def test_fichiers_web_servis(client):
    r = client.get("/")
    assert r.status_code == 200 and "Atelier G1" in r.text and 'type="importmap"' in r.text
    for chemin, genre in (("/js/app.js", "javascript"), ("/css/atelier.css", "css"),
                          ("/vendor/leaflet/leaflet.js", "javascript"), ("/vendor/three/three.module.js", "javascript"),
                          ("/vendor/three/OrbitControls.js", "javascript")):
        r = client.get(chemin)
        assert r.status_code == 200 and genre in r.headers["content-type"], chemin
    assert client.get("/js/rien.js").status_code == 404


def test_png_gris_aller_retour():
    import numpy as np
    from atelier.serveur.communs import png_gris
    image = (np.arange(35 * 17) % 256).astype(np.uint8).reshape(17, 35)
    assert (lire_png(png_gris(image)) == image).all()
    image16 = np.array([[0, 1000], [500, 2000]], dtype=np.uint16)
    assert lire_png(png_gris(image16)).tolist() == [[0, 127], [63, 255]]
