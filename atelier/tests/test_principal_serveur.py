"""Tests de l'API du point principal (vague 4, section 11.2 du plan), avec fastapi.testclient :
GET/PUT /api/lieux/{id}/principal, PUT …/salles (deux principaux, perte du principal), PUT /api/lieux/{id}
(accueil gardé), fiche du lieu, GET /api/robot/etat et refus de la simulation sans principal.

Sur une copie de lieux/demo ($ATELIER_LIEUX temporaire), sans ROS 2 ni Gazebo : les commandes g1-*
sont les fausses commandes de test_serveur_communs.
"""
import math

import yaml

from atelier.lieu import charger_fiche, charger_itineraires, charger_monde, charger_salles, enregistrer_salles

from .test_serveur_communs import client, faux_bin, journaux, lieux  # noqa: F401

DEMO = "/api/lieux/demo"


def _erreur(r, statut):
    """La réponse est une erreur au format de l'Atelier, en français, jamais une erreur 500."""
    assert r.status_code == statut, (r.status_code, r.text)
    d = r.json()
    assert isinstance(d["detail"], str) and d["detail"] and "Traceback" not in d["detail"]
    return d


def test_lire_le_principal(client):
    r = client.get(DEMO + "/principal")
    assert r.status_code == 200, r.text
    assert r.json() == {"salle": "accueil", "nom": "Accueil", "etage": "rdc", "x": 2.5, "y": 10.0, "theta": 0.0,
                        "explicite": False, "depart_synchro": True,
                        "repere_unitree": {"x": 2.5, "y": 10.0, "theta": 0.0},
                        "pose_unitree": {"x": 0.0, "y": 0.0, "theta": 0.0}}
    assert client.get(DEMO).json()["principal"] == {"salle": "accueil", "nom": "Accueil", "etage": "rdc", "x": 2.5,
                                                    "y": 10.0, "theta": 0.0, "explicite": False}
    _erreur(client.get("/api/lieux/inconnu/principal"), 404)


def test_tourner_puis_deplacer_le_principal(client, lieux):
    """Critère 21 : {theta: 1.5708} → salles.yaml, accueil de lieu.yaml et depart_robot valent 1,5708 ;
    GET le rend ; puis le principal déplacé en (2,5 ; 11,0 ; 1,5708)."""
    dossier = lieux / "demo"
    r = client.put(DEMO + "/principal", json={"theta": 1.5708})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["enregistre"] == ["salles.yaml", "lieu.yaml", "mondes/rdc.monde.yaml"]
    assert d["principal"]["theta"] == 1.5708 and d["principal"]["explicite"] and d["rapport"]["ok"]
    assert "avertissement" not in d
    assert charger_salles(dossier)[0].pose.theta == 1.5708 and charger_salles(dossier)[0].etiquettes == ["principal"]
    assert charger_fiche(dossier).accueil.theta == 1.5708
    assert charger_monde(dossier, "rdc").depart_robot.theta == 1.5708
    assert client.get(DEMO + "/principal").json()["theta"] == 1.5708
    r = client.put(DEMO + "/principal", json={"x": 2.5, "y": 11.0, "theta": 1.5708})
    assert r.status_code == 200 and r.json()["enregistre"] == ["salles.yaml", "itineraires.yaml", "lieu.yaml",
                                                                "mondes/rdc.monde.yaml"]
    p = client.get(DEMO + "/principal").json()
    assert (p["x"], p["y"], p["theta"], p["depart_synchro"]) == (2.5, 11.0, 1.5708, True)
    assert p["pose_unitree"] == {"x": 0.0, "y": 0.0, "theta": 0.0}      # repère d'Unitree = départ = principal
    n = charger_itineraires(dossier).noeuds["accueil"]
    assert (n.x, n.y) == (2.5, 11.0)
    a = charger_fiche(dossier).accueil
    assert (a.x, a.y, a.theta) == (2.5, 11.0, 1.5708)
    d = charger_monde(dossier, "rdc").depart_robot
    assert (d.x, d.y, d.theta) == (2.5, 11.0, 1.5708)
    # la pose de repérage par défaut suit
    e = client.get("/api/robot/etat?lieu=demo&etage=rdc").json()
    assert e["marque"] == {"x": 2.5, "y": 11.0, "theta": 1.5708} and e["principal"]["salle"] == "accueil"
    # rien à changer : rien n'est écrit
    assert client.put(DEMO + "/principal", json={"theta": 1.5708}).json()["enregistre"] == []


def test_choisir_une_autre_salle(client, lieux):
    r = client.put(DEMO + "/principal", json={"salle": "b204"})
    assert r.status_code == 200, r.text
    assert r.json()["principal"]["salle"] == "b204"
    salles = {s.id: s for s in charger_salles(lieux / "demo")}
    assert salles["b204"].etiquettes == ["principal"] and salles["accueil"].etiquettes == []
    a = charger_fiche(lieux / "demo").accueil
    assert (a.x, a.y, a.theta) == (21.0, 13.0, 1.5708)
    # PUT /api/lieux/{id} : accueil reste la copie du principal, même si la fiche envoyée dit autre chose
    fiche = client.get(DEMO).json()
    donnees = {k: fiche[k] for k in ("version", "nom", "langue", "accueil", "carte_unitree")}
    donnees["etages"] = [{k: e[k] for k in ("id", "nom", "source_carte")} for e in fiche["etages"]]
    donnees["accueil"] = {"etage": "rdc", "x": 1.0, "y": 1.0, "theta": 0.0}
    assert client.put(DEMO, json=donnees).status_code == 200
    a = charger_fiche(lieux / "demo").accueil
    assert (a.x, a.y, a.theta) == (21.0, 13.0, 1.5708)


def test_demandes_refusees_en_francais(client, lieux):
    avant = {f: (lieux / "demo" / f).read_bytes() for f in ("salles.yaml", "lieu.yaml", "itineraires.yaml")}
    assert "Rien à changer" in _erreur(client.put(DEMO + "/principal", json={}), 400)["detail"]
    assert "il manque : y" in _erreur(client.put(DEMO + "/principal", json={"x": 1.0}), 400)["detail"]
    assert "radians" in _erreur(client.put(DEMO + "/principal", json={"theta": 7.0}), 400)["detail"]
    assert "identifiant" in _erreur(client.put(DEMO + "/principal", json={"salle": "../x"}), 400)["detail"]
    d = _erreur(client.put(DEMO + "/principal", json={"salle": "grenier"}), 404)
    assert "n'existe pas" in d["detail"]
    _erreur(client.put(DEMO + "/principal", json={"x": "loin", "y": 1}), 422)
    d = _erreur(client.put(DEMO + "/principal", json={"x": 500.0, "y": 10.0}), 422)
    assert any("emprise" in m for m in d["erreurs"]), d
    _erreur(client.put("/api/lieux/inconnu/principal", json={"theta": 0.0}), 404)
    assert {f: (lieux / "demo" / f).read_bytes() for f in avant} == avant


def test_salles_deux_principaux_et_perte(client, lieux):
    """Critère 21 : deux principaux → 422 ; un lieu migré dont PUT …/salles perdrait le principal → 422."""
    salles = client.get(DEMO + "/salles").json()
    deux = [dict(s, etiquettes=["principal"]) if s["id"] in ("accueil", "b204") else s for s in salles]
    d = _erreur(client.put(DEMO + "/salles?synchroniser=true", json=deux), 422)
    assert any("un lieu n'a qu'un point principal" in m for m in d["erreurs"])
    # principal implicite : supprimer la salle accueil est refusé
    d = _erreur(client.put(DEMO + "/salles?synchroniser=true", json=[s for s in salles if s["id"] != "accueil"]), 422)
    assert "choisissez d'abord un autre point principal" in d["detail"]
    # lieu migré (principal explicite) : retirer l'étiquette, ou supprimer la salle, est refusé
    assert client.put(DEMO + "/principal", json={"salle": "accueil"}).status_code == 200
    salles = client.get(DEMO + "/salles").json()
    assert salles[0]["etiquettes"] == ["principal"]
    sans = [dict(s, etiquettes=[]) for s in salles]
    d = _erreur(client.put(DEMO + "/salles", json=sans), 422)
    assert "choisissez d'abord un autre point principal" in d["detail"] and "Accueil" in d["detail"]
    _erreur(client.put(DEMO + "/salles?synchroniser=true", json=salles[1:]), 422)
    assert charger_salles(lieux / "demo")[0].etiquettes == ["principal"]
    # donner l'étiquette à une autre salle : accepté, accueil et départ suivent (synchroniser)
    autre = [dict(s, etiquettes=["principal"] if s["id"] == "cdi" else []) for s in salles]
    r = client.put(DEMO + "/salles?synchroniser=true", json=autre)
    assert r.status_code == 200, r.text
    assert r.json()["enregistre"] == ["salles.yaml", "lieu.yaml", "mondes/rdc.monde.yaml"]
    assert r.json()["rapport"]["erreurs"] == []
    assert client.get(DEMO + "/principal").json()["salle"] == "cdi"
    d = charger_monde(lieux / "demo", "rdc").depart_robot
    assert (d.x, d.y, d.theta) == (23.0, 7.0, -1.5708)
    texte = yaml.safe_load((lieux / "demo" / "salles.yaml").read_text(encoding="utf-8"))
    assert [s["id"] for s in texte if s.get("etiquettes")] == ["cdi"]


def test_sans_principal(client, lieux, faux_bin):
    """Critère 21 : un lieu sans principal (ni étiquette ni salle accueil) : GET 404, la vérification
    le dit, la simulation est refusée (409)."""
    enregistrer_salles(lieux / "demo", [s for s in charger_salles(lieux / "demo") if s.id != "accueil"])
    assert "pas de point principal" in _erreur(client.get(DEMO + "/principal"), 404)["detail"]
    assert client.get(DEMO).json()["principal"] is None
    assert any("pas de point principal" in m for m in client.get(DEMO + "/verification").json()["erreurs"])
    assert client.get("/api/robot/etat?lieu=demo&etage=rdc").json()["principal"] is None
    d = _erreur(client.post("/api/simulation/demarrer", json={"lieu": "demo", "etage": "rdc"}), 409)
    assert "pas de point principal" in d["detail"]
    assert not any(a.startswith("g1-monde simuler") for a in faux_bin.appels())
    # sans principal, n'importe quelle liste peut le redonner
    salles = [s.vers_dict() for s in charger_salles(lieux / "demo")]
    salles[0]["etiquettes"] = ["principal"]
    assert client.put(DEMO + "/salles?synchroniser=true", json=salles).status_code == 200
    assert client.get(DEMO + "/principal").json()["salle"] == salles[0]["id"]


def test_principal_change_pendant_une_simulation(client, faux_bin):
    assert client.post(DEMO + "/etages/rdc/monde/generer").status_code == 200
    assert client.post("/api/simulation/demarrer", json={"lieu": "demo", "etage": "rdc"}).status_code == 200
    r = client.put(DEMO + "/principal", json={"theta": 0.5})
    assert r.status_code == 200 and "relancez-la" in r.json()["avertissement"]
    client.post("/api/simulation/arreter")


def test_angles_et_repere_tourne(client, lieux):
    from atelier.lieu import Pose, carte_vers_unitree, enregistrer_fiche
    fiche = charger_fiche(lieux / "demo")
    fiche.etages[0].repere_unitree = Pose(3.0, 9.0, 0.5)
    enregistrer_fiche(fiche)
    r = client.put(DEMO + "/principal", json={"theta": -3.5})          # ramené entre -π et π
    assert r.status_code == 200
    p = client.get(DEMO + "/principal").json()
    assert math.isclose(p["theta"], -3.5 + 2 * math.pi, abs_tol=1e-6)
    u = carte_vers_unitree((p["x"], p["y"], p["theta"]), (3.0, 9.0, 0.5))
    assert all(math.isclose(p["pose_unitree"][k], v, abs_tol=1e-6) for k, v in zip(("x", "y", "theta"), u))
