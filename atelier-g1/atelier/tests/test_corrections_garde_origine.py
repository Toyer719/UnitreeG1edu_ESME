"""Garde des origines (corrections de la vague 6, revue du code, défaut 1).

Une page d'un autre site, ouverte dans le navigateur du PC, envoyait des « requêtes simples » (POST text/plain ou sans
corps, mode no-cors) que le navigateur laisse partir sans vérification : elle lançait les actions « confirmées » du
diagnostic, faisait parler le robot, changeait son volume, arrêtait la démo ou la séance et retirait le verrou.
GardeOrigine (main.py) refuse une demande qui change quelque chose et un WebSocket venus d'une autre origine, et tout
nom d'hôte inconnu (rebinding DNS). L'ARRÊT passe toujours ; curl, g1-seance et la page de l'Atelier ne changent pas.

  ~/robot-g1/.venv-projet/bin/python -m pytest ~/robot-g1/atelier/tests/test_corrections_garde_origine.py -v
"""
import json

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from atelier.serveur.main import creer_app, hote_permis, origine_refusee

AUTRE_SITE = {"Content-Type": "text/plain;charset=UTF-8", "Origin": "https://site-quelconque.example",
              "Sec-Fetch-Site": "cross-site"}
# les demandes « simples » qu'un autre site pouvait envoyer (revue du code, essai_demande_croisee_liste.py)
DEMANDES = [("/api/robot/diagnostic/retablir-cable", '{"confirme": true}'),
            ("/api/robot/diagnostic/demarrer-services", '{"confirme": true}'),
            ("/api/voix/essayer", '{"texte": "Bonjour, je viens d un autre site", "priorite": "securite"}'),
            ("/api/voix/commande", '{"action": "volume", "volume": 100}'),
            ("/api/seance/arreter", ""), ("/api/seance/demarrer", '{"mode": "repetition"}'),
            ("/api/demo/arreter", ""), ("/api/demo/lancer", '{"lieu": "demo"}'),
            ("/api/arret/debloquer", ""), ("/api/robot/arret", '{"verrou": false}'),
            ("/api/borne/appui", ""), ("/api/borne/choisir", '{"salle": "b204"}'),
            ("/api/guide/aller", '{"cible": "b204"}')]


def _scope(methode="POST", chemin="/api/voix/essayer", type_="http", **entetes):
    return {"type": type_, "method": methode, "path": chemin,
            "headers": [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in entetes.items()]}


def test_hote_permis():
    noms = {"localhost", "pc-du-robot", "pc-du-robot.local"}
    for hote in ("127.0.0.1:8000", "127.0.0.1", "[::1]:8000", "192.168.0.12:8000", "localhost:8148", "LOCALHOST",
                 "pc-du-robot:8000", "pc-du-robot.local", "atelier.localhost:8000", "testserver", ""):
        assert hote_permis(hote, noms), hote
    for hote in ("site-quelconque.example", "evil.example:8000", "127.0.0.1.nip.io:8000", "pc-du-robot.evil"):
        assert not hote_permis(hote, noms), hote


def test_origine_refusee_fonction_pure():
    noms = {"localhost"}
    hote = {"Host": "127.0.0.1:8000"}
    # même origine, sans Origin (curl, g1-seance), ou GET : permis
    assert origine_refusee(_scope(Origin="http://127.0.0.1:8000", **hote), noms) is None
    assert origine_refusee(_scope(**{"Sec-Fetch-Site": "same-origin"}, **hote), noms) is None
    assert origine_refusee(_scope(**hote), noms) is None
    assert origine_refusee(_scope("GET", "/api/lieux", Origin="https://site-quelconque.example", **hote), noms) is None
    # autre site, origine null (page locale), même site sur un autre port : refusés
    assert origine_refusee(_scope(Origin="https://site-quelconque.example", **hote), noms)
    assert origine_refusee(_scope(Origin="null", **hote), noms)
    assert origine_refusee(_scope(Origin="http://127.0.0.1:3000", **hote), noms)
    assert origine_refusee(_scope(**{"Sec-Fetch-Site": "cross-site"}, **hote), noms)
    assert origine_refusee(_scope(**{"Sec-Fetch-Site": "same-site"}, **hote), noms)
    for methode in ("PUT", "PATCH", "DELETE"):
        assert origine_refusee(_scope(methode, Origin="null", **hote), noms), methode
    # WebSocket d'une autre origine : refusé ; de la même : permis
    assert origine_refusee(_scope("GET", "/ws/pilotage", "websocket", Origin="null", **hote), noms)
    assert origine_refusee(_scope("GET", "/ws/pilotage", "websocket", Origin="http://127.0.0.1:8000", **hote),
                           noms) is None
    # rebinding DNS : un nom inconnu, même avec un Origin cohérent, et même en GET
    assert origine_refusee(_scope("GET", "/api/lieux", Host="evil.example:8000"), noms)
    assert origine_refusee(_scope(Origin="http://evil.example:8000", Host="evil.example:8000"), noms)
    # l'ARRÊT passe toujours
    assert origine_refusee(_scope("POST", "/api/arret", Origin="null", Host="evil.example"), noms) is None
    assert origine_refusee({"type": "lifespan"}, noms) is None


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ATELIER_LIEUX", str(tmp_path))
    monkeypatch.delenv("ATELIER_HOTE", raising=False)
    monkeypatch.delenv("ATELIER_HOTES_PERMIS", raising=False)
    with TestClient(creer_app(ros=False)) as c:
        yield c


def test_autre_site_refuse(client):
    """Chaque demande « simple » d'un autre site répond 403 en français et n'atteint pas sa route."""
    for chemin, corps in DEMANDES:
        for entetes in (AUTRE_SITE, {"Content-Type": "text/plain", "Origin": "null"},
                        {"Sec-Fetch-Site": "cross-site"}):
            r = client.post(chemin, content=corps, headers=entetes)
            assert r.status_code == 403, (chemin, entetes, r.status_code, r.text)
            assert "ne vient pas de l'Atelier" in r.json()["detail"], r.text
    r = client.put("/api/lieux/demo/demo", content="{}", headers=AUTRE_SITE)
    assert r.status_code == 403


def test_page_de_l_atelier_et_outils_inchanges(client):
    """La même origine (la page de l'Atelier, la borne) et les outils sans Origin (curl, g1-seance) ne sont pas
    refusés par la garde (la route répond ce qu'elle répondait avant)."""
    for chemin, corps in DEMANDES:
        for entetes in ({"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin",
                         "Content-Type": "application/json"}, {"Content-Type": "application/json"}, {}):
            r = client.post(chemin, content=corps, headers=entetes)
            assert r.status_code != 403 or "ne vient pas de l'Atelier" not in r.text, (chemin, entetes, r.text)
            assert r.status_code != 500, (chemin, r.status_code, r.text)


def test_l_arret_passe_toujours(client):
    r = client.post("/api/arret", content=json.dumps({"mode": "simulation"}), headers=AUTRE_SITE)
    assert r.status_code != 403, r.text


def test_nom_d_hote_inconnu_refuse(client, monkeypatch):
    """Rebinding DNS : un autre nom qui pointerait sur ce PC ne lit ni n'écrit rien ; une adresse IP, localhost et un
    nom de ATELIER_HOTES_PERMIS passent."""
    r = client.get("/api/lieux", headers={"Host": "evil.example:8000"})
    assert r.status_code == 403 and "nom d'hôte inconnu" in r.json()["detail"]
    r = client.post("/api/arret/debloquer", headers={"Host": "evil.example:8000", "Origin": "http://evil.example:8000"})
    assert r.status_code == 403
    for hote in ("127.0.0.1:8000", "192.168.0.12:8000", "localhost:8000"):
        assert client.get("/api/lieux", headers={"Host": hote}).status_code == 200, hote
    monkeypatch.setenv("ATELIER_HOTES_PERMIS", "atelier-du-lycee.lan, autre.lan")
    with TestClient(creer_app(ros=False)) as c:
        assert c.get("/api/lieux", headers={"Host": "atelier-du-lycee.lan:8000"}).status_code == 200
        assert c.get("/api/lieux", headers={"Host": "evil.example"}).status_code == 403


def test_websocket_d_un_autre_site_refuse(client):
    with pytest.raises(WebSocketDisconnect) as e:
        with client.websocket_connect("/ws/etat", headers={"Origin": "https://site-quelconque.example"}) as ws:
            ws.receive_json()
    assert e.value.code == 4403
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/pilotage", headers={"Origin": "null"}) as ws:
            ws.receive_json()
    with client.websocket_connect("/ws/etat", headers={"Origin": "http://testserver"}) as ws:
        assert "processus" in ws.receive_json()
