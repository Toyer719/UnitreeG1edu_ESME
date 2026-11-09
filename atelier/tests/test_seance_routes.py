"""Les routes de la boîte noire (vague 6, sections 13.3 et 13.8 du plan) : agent Boîte noire.

Avec l'application entière (creer_app, sans pont ROS 2) : ouvrir et terminer une séance, le journal des actions
rempli par la vraie accroche de main.py, la séance dans /ws/etat, la liste, le manifeste, le rapport (409 tant qu'il
s'écrit, puis html, md, json), le refaire, les fichiers de la liste blanche, l'export .zip ; refus en français, jamais
d'erreur 500.
"""
import io
import json
import time
import zipfile

import pytest

from atelier.lieu import copier_lieu, valider_donnees
from atelier.seance import manifeste as M
from .test_serveur_communs import DEMO


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from atelier.serveur.main import creer_app
    monkeypatch.setenv("ATELIER_LIEUX", str(tmp_path / "lieux"))
    monkeypatch.setenv("ATELIER_SEANCES", str(tmp_path / "seances"))
    monkeypatch.setenv("ATELIER_INTERFACE_ROBOT", "interface_absente_v6")
    monkeypatch.delenv("ATELIER_HOTE", raising=False)
    copier_lieu(DEMO, tmp_path / "lieux" / "demo")
    import atelier.diagnostic

    def pas_encore(*a, **k):
        raise NotImplementedError()
    monkeypatch.setattr(atelier.diagnostic, "diagnostiquer", pas_encore)
    app = creer_app(ros=False)
    with TestClient(app) as c:
        c.app_atelier = app
        c.racine = tmp_path
        yield c


def attendre(condition, delai=60.0):
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        if condition():
            return True
        time.sleep(0.2)
    return condition()


def _francais(r, statut):
    assert r.status_code == statut, (r.status_code, r.text[:300])
    assert isinstance(r.json()["detail"], str) and r.json()["detail"]


def test_ouvrir_noter_terminer_et_lire_le_rapport(client):
    assert client.get("/api/seance").json() == {"seance": None, "derniere": None}
    _francais(client.post("/api/seance/arreter", json={}), 404)
    r = client.post("/api/seance/demarrer", json={"mode": "repetition", "lieu": "demo", "etage": "rdc",
                                                  "ouverture": "auto"})
    assert r.status_code == 200, r.text
    m = r.json()["seance"]
    assert valider_donnees("seance", m) == [] and m["ouverture"] == "auto" and m["mode"] == "repetition"
    assert m["enregistrement"]["etat"] == "absent"            # l'Atelier tourne sans ROS 2
    assert client.post("/api/seance/demarrer", json={"mode": "reel"}).json()["seance"]["id"] == m["id"]
    with client.websocket_connect("/ws/etat") as ws:
        d = ws.receive_json()
    assert d["seance"]["id"] == m["id"] and d["seance"]["badge"] == "arrete" and d["seance"]["etat"] == "ouverte"
    # les actions passent par la vraie accroche de main.py
    assert client.post("/api/arret", json={"mode": "simu", "raison": "essai"}).status_code == 200
    client.put("/api/lieux/demo/salles", content="pas du JSON", headers={"Content-Type": "application/json"})
    client.post("/api/simulation/teleop", json={"vx": 0.1})            # les flèches : jamais dans le journal
    dossier = client.racine / "seances" / m["id"]
    assert attendre(lambda: len((dossier / "actions.jsonl").read_text(encoding="utf-8").splitlines()) >= 4, 10)
    lignes = [json.loads(x) for x in (dossier / "actions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [x["genre"] for x in lignes] == ["seance", "seance", "arret", "lieu"]
    assert lignes[0]["texte"] == "Ouvrir la séance (automatique)" and lignes[2]["texte"] == "ARRÊT"
    assert lignes[3]["statut"] == 422 and lignes[3]["texte"] == "Salles enregistrées"
    assert all(valider_donnees("action_seance", x) == [] for x in lignes)
    # la liste, le manifeste
    liste = client.get("/api/seances").json()
    assert liste[0]["id"] == m["id"] and liste[0]["etat"] == "ouverte"
    assert client.get(f"/api/seances/{m['id']}").json()["id"] == m["id"]
    _francais(client.get(f"/api/seances/{m['id']}/rapport"), 409)          # encore ouverte
    _francais(client.post(f"/api/seances/{m['id']}/rapport"), 409)
    # « Terminer la séance »
    r = client.post("/api/seance/arreter", json={})
    assert r.status_code == 200 and r.json()["seance"]["etat"] == "fermee"
    assert r.json()["seance"]["rapport"]["etat"] in ("en_cours", "pret")
    assert client.get("/api/seance").json()["seance"] is None
    assert client.get("/api/seance").json()["derniere"]["id"] == m["id"]
    assert attendre(lambda: client.get(f"/api/seances/{m['id']}").json()["rapport"]["etat"] == "pret", 90)
    page = client.get(f"/api/seances/{m['id']}/rapport")
    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
    assert "Rapport de séance du" in page.text and "ARRÊT" in page.text
    md = client.get(f"/api/seances/{m['id']}/rapport?format=md")
    assert md.status_code == 200 and md.headers["content-type"].startswith("text/markdown")
    assert client.get(f"/api/seances/{m['id']}/rapport?format=json").json()["seance"] == m["id"]
    _francais(client.get(f"/api/seances/{m['id']}/rapport?format=pdf"), 422)
    # refaire le rapport
    r = client.post(f"/api/seances/{m['id']}/rapport")
    assert r.status_code == 200 and r.json()["seance"]["rapport"]["etat"] == "en_cours"
    assert attendre(lambda: client.get(f"/api/seances/{m['id']}").json()["rapport"]["etat"] == "pret", 90)
    lignes = [json.loads(x) for x in (dossier / "actions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert lignes[-1]["texte"] == "Terminer la séance"


def test_fichiers_et_export(client):
    m = client.post("/api/seance/demarrer", json={"mode": "reel"}).json()["seance"]
    client.post("/api/seance/arreter")
    ident = m["id"]
    assert attendre(lambda: client.get(f"/api/seances/{ident}").json()["rapport"]["etat"] == "pret", 90)
    r = client.get(f"/api/seances/{ident}/fichiers/trajets.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content[:4] == b"\x89PNG"
    assert client.get(f"/api/seances/{ident}/fichiers/actions.jsonl").status_code == 200
    for nom in ("bag", "lieu", "rapport.exe", "%2E%2E", "metadata.yaml", ".seance.lock"):
        _francais(client.get(f"/api/seances/{ident}/fichiers/{nom}"), 404)
    _francais(client.get(f"/api/seances/{ident}/fichiers/diagnostic_debut.json"), 404)     # pas encore de diagnostic
    r = client.get(f"/api/seances/{ident}/export")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert f"seance_{ident}.zip" in r.headers["content-disposition"]
    noms = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert f"{ident}/seance.json" in noms and f"{ident}/actions.jsonl" in noms and f"{ident}/rapport.html" in noms
    assert not any(n.endswith(".seance.lock") for n in noms)


def test_identifiants_et_demandes_absurdes(client):
    for chemin in ("/api/seances/inconnue", "/api/seances/2026-11-12_14h03", "/api/seances/..%2F..%2Fetc",
                   "/api/seances/2026-11-12_14h03/rapport", "/api/seances/2026-11-12_14h03/export",
                   "/api/seances/2026-11-12_14h03/fichiers/seance.json"):
        _francais(client.get(chemin), 404)
    _francais(client.post("/api/seance/demarrer", json={"mode": "simu"}), 409)
    _francais(client.post("/api/seance/demarrer", json={"mode": "lune"}), 400)
    _francais(client.post("/api/seance/demarrer", json={"mode": "reel", "lieu": "inconnu"}), 404)
    _francais(client.post("/api/seance/demarrer", json={"mode": "reel", "lieu": "../x"}), 400)
    _francais(client.post("/api/seance/demarrer", json={"mode": 3}), 422)
    _francais(client.post("/api/seance/demarrer", content=b"{pas du json", headers={"Content-Type":
                                                                                    "application/json"}), 422)
    _francais(client.post("/api/seance/demarrer", json=[1, 2]), 422)
    _francais(client.post("/api/seance/arreter", json={"fermeture": "plantage"}), 422)
    _francais(client.post("/api/seances/2026-11-12_14h03/rapport"), 404)
    assert not (client.racine / "seances").exists() or not any((client.racine / "seances").iterdir())


def test_liste_de_plusieurs_seances(client):
    racine = client.racine / "seances"
    for ident, etat in (("2026-11-12_14h03", "fermee"), ("2026-11-12_14h03-2", "interrompue"),
                        ("2026-11-13_09h00", "fermee")):
        (racine / ident).mkdir(parents=True)
        m = M.nouveau_manifeste(ident, "reel", "demo", "rdc", "auto")
        m.update(etat=etat, fin=m["debut"], duree_s=0.0, fermeture="terminer" if etat == "fermee" else "plantage")
        M.ecrire_manifeste(racine / ident, m)
    (racine / "pas_une_seance").mkdir()
    liste = client.get("/api/seances").json()
    assert [s["id"] for s in liste] == ["2026-11-13_09h00", "2026-11-12_14h03-2", "2026-11-12_14h03"]
    assert set(liste[0]) >= {"id", "etat", "mode", "lieu", "debut", "duree_s", "rapport"}
    assert client.get("/api/seance").json()["derniere"]["id"] == "2026-11-13_09h00"


def test_fermeture_en_simulation(client, monkeypatch):
    """Corrections de la vague 6 (revue de l'interface, défaut 5) : l'espace rouvert en Simulation termine la séance
    (fermeture « simulation ») ; tant que la navigation du robot ou de la répétition tourne, 409 et elle continue."""
    _francais(client.post("/api/seance/arreter", json={"fermeture": "simulation"}), 404)
    r = client.post("/api/seance/demarrer", json={"mode": "repetition", "lieu": "demo", "ouverture": "auto"})
    assert r.status_code == 200, r.text
    ident = r.json()["seance"]["id"]
    etat = client.app_atelier.state.atelier
    for mode in ("repetition", "robot"):
        monkeypatch.setattr(etat, "mode_navigation", lambda m=mode: m)
        r = client.post("/api/seance/arreter", json={"fermeture": "simulation"})
        _francais(r, 409)
        assert "tourne encore" in r.json()["detail"]
        assert client.get("/api/seance").json()["seance"]["id"] == ident
    monkeypatch.setattr(etat, "mode_navigation", lambda: None)
    r = client.post("/api/seance/arreter", json={"fermeture": "simulation"})
    assert r.status_code == 200, r.text
    m = r.json()["seance"]
    assert m["fermeture"] == "simulation" and valider_donnees("seance", m) == []
    assert client.get("/api/seance").json()["seance"] is None
    assert attendre(lambda: M.lire_manifeste(client.racine / "seances" / ident)["rapport"]["etat"] != "en_cours", 90)
    rapport = client.get(f"/api/seances/{ident}/rapport", params={"format": "md"})
    assert rapport.status_code == 200 and "passage en Simulation" in rapport.text, rapport.text[-800:]
