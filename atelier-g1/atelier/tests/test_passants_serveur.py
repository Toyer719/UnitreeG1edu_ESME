"""Routes des passants (/api/passants/*) et panneau de l'onglet Simulation, sans ROS."""
import csv

import pytest
from fastapi.testclient import TestClient

import atelier
from atelier import RACINE
from atelier.lieu.passants import COLONNES_BANC_V4
from atelier.serveur.main import creer_app

PANNEAU = RACINE / "atelier" / "web" / "js" / "panneaux" / "passants.js"


@pytest.fixture
def client():
    with TestClient(creer_app(ros=False)) as c:
        yield c


def test_scenes(client):
    r = client.get("/api/passants/scenes")
    assert r.status_code == 200
    scenes = {s["id"]: s for s in r.json()["scenes"]}
    assert {"immobile_couloir", "en_face", "coupe_route", "groupe_couloir", "groupe_reste", "foule"} <= set(scenes)
    assert r.json()["erreurs"] == []
    s = scenes["immobile_couloir"]
    assert s["commande"] == "g1-banc --scene immobile_couloir" and s["essais"] == 5
    assert s["reactions"] == ["aucune"] and s["mesures"]["distance_bord_min_m"] == 0.2
    r = client.get("/api/passants/scenes/en_face")
    assert r.status_code == 200 and r.json()["scene"]["id"] == "en_face"
    for faux in ("inconnue", "..%2F..%2Fetc", "A"):
        r = client.get(f"/api/passants/scenes/{faux}")
        assert r.status_code == 404 and ("scène" in r.json()["detail"].lower() or "inconnue" in r.json()["detail"])


def test_bancs(client, tmp_path, monkeypatch):
    monkeypatch.setattr(atelier, "dossier_journaux", lambda: tmp_path)
    assert client.get("/api/passants/bancs").json()["bancs"] == []
    colonnes = ["numero", "depart", "arrivee", "reussite", "duree_s", "arrets", "distance_min_pietons_m",
                "detours", "erreur_m", "etat_final"] + list(COLONNES_BANC_V4)
    lignes = [dict(zip(colonnes, ["1", "accueil", "b204", "oui", "60", "0", "0.9", "0", "0.1", "arrive",
                                  "en_face", "0.31", "1", "0", "1", "0", "2", "0", "0", "22", "21.5"])),
              dict(zip(colonnes, ["2", "accueil", "b204", "non", "190", "1", "0.8", "1", "4", "delai_depasse",
                                  "en_face", "0.12", "1", "1", "0", "0", "0", "0", "0", "30", "21.5"]))]
    with open(tmp_path / "banc_en_face_rdc_essai.csv", "w", newline="", encoding="utf-8") as f:
        ecrivain = csv.DictWriter(f, fieldnames=colonnes)
        ecrivain.writeheader()
        ecrivain.writerows(lignes)
    (tmp_path / "autre.csv").write_text("x\n", encoding="utf-8")
    r = client.get("/api/passants/bancs").json()
    assert len(r["bancs"]) == 1
    b = r["bancs"][0]
    assert (b["scene"], b["trajets"], b["reussis"], b["contacts"], b["contacts_robot"], b["contacts_pieton"],
            b["distance_min_bord_m"], b["vague4"]) == ("en_face", 2, 1, 2, 1, 1, 0.12, True)
    r = client.get("/api/passants/bancs/banc_en_face_rdc_essai.csv")
    assert r.status_code == 200 and len(r.json()["lignes"]) == 2
    for faux in ("autre.csv", "banc_absent.csv", "banc_x.txt"):
        assert client.get(f"/api/passants/bancs/{faux}").status_code == 404


def test_etat_sans_simulation(client):
    assert client.get("/api/passants/etat").json() == {"etat": None}


def test_panneau_passants():
    texte = PANNEAU.read_text(encoding="utf-8")
    assert "export function monter(element, outils)" in texte and "fermer:" in texte
    assert "/api/passants/scenes" in texte and "/api/passants/bancs" in texte and "abonner(" in texte
    esprima = pytest.importorskip("esprima")
    esprima.parseModule(texte)
