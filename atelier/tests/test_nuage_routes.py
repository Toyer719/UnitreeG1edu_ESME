"""Tests des routes des nuages 3D et du maillage (vague 5, sections 12.4 et 12.5 du plan), sans ROS ni Gazebo :
GET /api/lieux/{id}/etages/{e}/nuage (+ /info, ?source=unitree), GET …/monde/maillage, GET /api/scan/nuage
(+ /info, ?apercu=1). TestClient sur des copies de lieux/demo (jamais lieux/demo).

  ~/robot-g1/.venv-projet/bin/python -m pytest ~/robot-g1/atelier/tests/test_nuage_routes.py -v
"""
import numpy as np
import pytest

import atelier
from atelier import lieu as L
from atelier import monde as M

from .outils_scan import SOL_PLAT, creer_session_exemple

DEMO = atelier.RACINE / "lieux" / "demo"


@pytest.fixture
def lieux(tmp_path, monkeypatch):
    monkeypatch.setenv("ATELIER_LIEUX", str(tmp_path))
    L.copier_lieu(DEMO, tmp_path / "demo")
    return tmp_path


@pytest.fixture
def client(lieux):
    from fastapi.testclient import TestClient
    from atelier.serveur.main import creer_app
    with TestClient(creer_app(ros=False)) as c:
        yield c


def _erreur(r, statut):
    assert r.status_code == statut, r.text
    d = r.json()
    assert isinstance(d["detail"], str) and d["detail"]
    return d["detail"]


def _nuage(lieux, source="scan", n=1000):
    pts = np.column_stack([np.linspace(0, 30, n), np.linspace(0, 20, n), np.linspace(0, 2.5, n)])
    entete = L.entete_nuage(pts, 0.05, SOL_PLAT, source, session="2026-10-27_14h22" if source == "scan" else None,
                            etage="rdc")
    L.ecrire_nuage(L.chemin_nuage(lieux / "demo", "rdc", source), pts, entete)
    return pts, entete


def test_nuage_d_un_etage(client, lieux):
    assert "faites un scan" in _erreur(client.get("/api/lieux/demo/etages/rdc/nuage"), 404)
    assert "faites un scan" in _erreur(client.get("/api/lieux/demo/etages/rdc/nuage/info"), 404)
    pts, entete = _nuage(lieux)
    r = client.get("/api/lieux/demo/etages/rdc/nuage")
    assert r.status_code == 200 and r.headers["content-type"] == "application/octet-stream"
    assert np.frombuffer(r.content, dtype="<f4").reshape(-1, 3) == pytest.approx(pts.astype(np.float32))
    for nom, valeur in L.entetes_http_nuage(entete).items():
        assert r.headers[nom] == valeur, nom
    assert r.headers["x-nuage-bornes"].count(",") == 5 and r.headers["etag"]
    # le navigateur l'a déjà : 304, sans le corps
    r2 = client.get("/api/lieux/demo/etages/rdc/nuage", headers={"If-None-Match": r.headers["etag"]})
    assert r2.status_code == 304 and r2.content == b""
    info = client.get("/api/lieux/demo/etages/rdc/nuage/info").json()
    assert info["points"] == 1000 and info["octets"] == 12000 and info["url"] == "/api/lieux/demo/etages/rdc/nuage"
    assert info["source"] == "scan" and info["sol"]["plan"] == [0.0, 0.0, 0.0] and info["modifie"] > 0
    # la carte d'Unitree
    assert "carte-unitree" in _erreur(client.get("/api/lieux/demo/etages/rdc/nuage?source=unitree"), 404)
    _nuage(lieux, "unitree", 50)
    r = client.get("/api/lieux/demo/etages/rdc/nuage?source=unitree")
    assert r.status_code == 200 and r.headers["x-nuage-source"] == "unitree" and len(r.content) == 600
    assert client.get("/api/lieux/demo/etages/rdc/nuage/info?source=unitree").json()["url"].endswith("source=unitree")
    # refus clairs
    assert "inconnue" in _erreur(client.get("/api/lieux/demo/etages/rdc/nuage?source=apercu"), 400)
    assert _erreur(client.get("/api/lieux/demo/etages/cave/nuage"), 404)
    assert _erreur(client.get("/api/lieux/ailleurs/etages/rdc/nuage"), 404)


def test_nuage_abime(client, lieux):
    _nuage(lieux)
    binaire, _ = L.fichiers_nuage(L.chemin_nuage(lieux / "demo", "rdc"))
    binaire.write_bytes(binaire.read_bytes()[:-12])            # un point de moins que l'en-tête
    assert "illisible" in _erreur(client.get("/api/lieux/demo/etages/rdc/nuage"), 422)


def test_maillage(client, lieux):
    assert "carte extrudée" in _erreur(client.get("/api/lieux/demo/etages/rdc/monde/maillage"), 404)
    # un monde dessiné : la réponse de generer reste celle d'avant la vague 5
    r = client.post("/api/lieux/demo/etages/rdc/monde/generer")
    assert r.status_code == 200 and set(r.json()["fichiers"]) == {"sdf", "carte", "interdit"}, r.text
    # un étage scanné : la carte du monde sert de carte du scan
    dossier = lieux / "demo"
    M.generer(dossier, "rdc")
    fiche = L.charger_fiche(dossier)
    fiche.etage("rdc").source_carte = "scan"
    L.enregistrer_fiche(fiche)
    r = client.post("/api/lieux/demo/etages/rdc/monde/generer")
    assert r.status_code == 200, r.text
    assert r.json()["fichiers"]["maillage"] is True
    r = client.get("/api/lieux/demo/etages/rdc/monde/maillage")
    assert r.status_code == 200 and r.headers["content-type"] == "model/stl" and r.headers["x-maillage-hauteur"] == "1.5"
    n = int.from_bytes(r.content[80:84], "little")
    assert len(r.content) == 84 + 50 * n and n > 100
    assert client.get("/api/lieux/demo/etages/rdc/monde").json()["carte_extrudee"]["fichier"] == "rdc_carte.stl"
    L.chemin_maillage(dossier, "rdc").unlink()
    assert "g1-monde generer" in _erreur(client.get("/api/lieux/demo/etages/rdc/monde/maillage"), 404)


def test_generer_un_etage_scanne_sans_monde(client, lieux):
    dossier = lieux / "demo"
    M.generer(dossier, "rdc")
    fiche = L.charger_fiche(dossier)
    fiche.etage("rdc").source_carte = "scan"
    L.enregistrer_fiche(fiche)
    L.chemin_monde(dossier, "rdc").unlink()
    r = client.post("/api/lieux/demo/etages/rdc/monde/generer")
    assert r.status_code == 200, r.text
    assert L.charger_monde(dossier, "rdc").carte_extrudee is not None
    # sans carte et sans monde : rien à faire
    L.chemin_carte(dossier, "rdc").unlink()
    L.chemin_monde(dossier, "rdc").unlink()
    assert "dessinez-le" in _erreur(client.post("/api/lieux/demo/etages/rdc/monde/generer"), 409)


def test_nuage_d_une_session(client, lieux):
    dossier = lieux / "demo"
    assert "Précisez le lieu" in _erreur(client.get("/api/scan/nuage"), 400)
    assert "Aucun scan" in _erreur(client.get("/api/scan/nuage?lieu=demo"), 404)
    # pendant le scan : l'aperçu en direct, même sans apercu=1
    en_cours = creer_session_exemple(dossier, "en_cours")
    r = client.get("/api/scan/nuage?lieu=demo")
    assert r.status_code == 200 and r.headers["x-nuage-source"] == "apercu" and r.headers["x-nuage-session"] == en_cours["id"]
    info = client.get("/api/scan/nuage/info?lieu=demo").json()
    assert info["apercu"] is True and info["url"].endswith("&apercu=1") and info["source"] == "apercu"
    L.maj_session(dossier, en_cours["id"], etat="echec", etape="enregistrement", message="essai")
    # terminée : le nuage traité ; apercu=1 : l'aperçu
    fini = creer_session_exemple(dossier, "termine")
    r = client.get(f"/api/scan/nuage?lieu=demo&session={fini['id']}")
    assert r.status_code == 200 and r.headers["x-nuage-source"] == "scan" and r.headers["x-nuage-grille"] == "0.05"
    assert int(r.headers["x-nuage-points"]) * 12 == len(r.content)
    r = client.get(f"/api/scan/nuage?lieu=demo&session={fini['id']}&apercu=1")
    assert r.headers["x-nuage-source"] == "apercu"
    info = client.get(f"/api/scan/nuage/info?lieu=demo&session={fini['id']}").json()
    assert info["apercu"] is False and info["session"] == fini["id"] and info["octets"] == 12 * info["points"]
    # sans nuage traité (session d'avant la vague 5, ou en traitement)
    for nom in ("nuage_affichage.bin", "nuage_affichage.json"):
        (L.dossier_session(dossier, fini["id"]) / nom).unlink()
    assert "--refaire" in _erreur(client.get(f"/api/scan/nuage?lieu=demo&session={fini['id']}"), 404)
    t = creer_session_exemple(dossier, "traitement")
    assert "fin du traitement" in _erreur(client.get(f"/api/scan/nuage?lieu=demo&session={t['id']}"), 404)
    # identifiants refusés
    assert "AAAA" in _erreur(client.get("/api/scan/nuage?lieu=demo&session=../../lieu"), 400)
    assert "n'existe pas" in _erreur(client.get("/api/scan/nuage/info?lieu=demo&session=2020-01-01_00h00"), 404)
