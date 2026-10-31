"""ARRÊT global de l'Atelier (vague 5, section 12.4 du plan ; agent Coquille), sans ROS ni robot :
POST /api/arret, POST /api/arret/debloquer, GET /api/arret et le champ arret de /ws/etat.

Le pont ROS 2 du serveur est remplacé par un faux qui note ce qui est publié ; le nœud pilotage est
une petite application HTTP du test (ou une adresse où personne n'écoute).
"""
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from atelier.serveur.routes import arret as A

from .test_serveur_communs import client, faux_bin, journaux, lieux  # noqa: F401


class FauxPont:
    """Les méthodes du pont ROS 2 dont l'ARRÊT se sert, sans ROS."""

    def __init__(self, pont, ecoute=1, panne=None, lent=0.0):
        self.stops = 0
        self.verrous = []
        self.ecoute = ecoute
        self.panne = panne
        self.lent = lent
        pont.actif = True
        pont.erreur = None
        pont.stop = self.stop
        pont.bloquer = self.bloquer
        pont.dernier = lambda sujet: None

    def stop(self):
        time.sleep(self.lent)
        if self.panne:
            raise RuntimeError(self.panne)
        self.stops += 1
        return self.ecoute

    def bloquer(self, verrou):
        time.sleep(self.lent)
        if self.panne:
            raise RuntimeError(self.panne)
        self.verrous.append(verrou)
        return self.ecoute


class FausseTeleop:
    def __init__(self):
        self.consignes = []

    def envoyer(self, vx, vy, wz):
        self.consignes.append((vx, vy, wz))
        return 1


def _port_libre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def noeud_pilotage(monkeypatch):
    """Faux nœud pilotage : POST /arret répond 200 (ou attend « lent » secondes)."""
    recus = []
    reglages = {"lent": 0.0, "statut": 200}

    class Gestion(BaseHTTPRequestHandler):
        def do_POST(self):          # noqa: N802 : nom imposé par http.server
            corps = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            recus.append((self.path, json.loads(corps or b"{}")))
            time.sleep(reglages["lent"])
            texte = json.dumps({"detail": "ARRÊT : StopMove envoyé."}).encode()
            self.send_response(reglages["statut"])
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(texte)))
            self.end_headers()
            self.wfile.write(texte)

        def log_message(self, *args):
            pass

    serveur = ThreadingHTTPServer(("127.0.0.1", _port_libre()), Gestion)
    fil = threading.Thread(target=serveur.serve_forever, daemon=True)
    fil.start()
    monkeypatch.setenv("G1_PILOTAGE_URL", f"http://127.0.0.1:{serveur.server_address[1]}")
    monkeypatch.setenv("G1_PILOTAGE_JETON", "")
    yield {"recus": recus, "reglages": reglages}
    serveur.shutdown()
    serveur.server_close()


@pytest.fixture
def sans_pilotage(monkeypatch):
    """Personne n'écoute à l'adresse du nœud pilotage (refus de connexion immédiat)."""
    monkeypatch.setenv("G1_PILOTAGE_URL", f"http://127.0.0.1:{_port_libre()}")
    monkeypatch.setenv("G1_PILOTAGE_JETON", "")


def _etat(client):
    return client.app.state.atelier


def test_arret_sans_rien_qui_tourne(client, sans_pilotage):
    r = client.post("/api/arret", json={"mode": "simu"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["arrete"] is True and d["mode"] == "simu" and d["verrou"] is False
    assert set(d["parties"]) == {"guide", "teleop", "pilotage", "verrou"}
    assert all(p["ok"] is None and p["detail"] for p in d["parties"].values()), d["parties"]
    assert d["message"] == "ARRÊT : rien ne tournait." and d["duree_s"] < 1.0


def test_arret_en_simulation_sans_verrou(client, sans_pilotage):
    pont = FauxPont(_etat(client).pont)
    teleop = client.app.state.teleop = FausseTeleop()
    d = client.post("/api/arret", json={"mode": "simu"}).json()
    assert d["parties"]["guide"]["ok"] is True and pont.stops == 1
    assert d["parties"]["teleop"]["ok"] is True and teleop.consignes == [(0.0, 0.0, 0.0)]
    assert d["parties"]["verrou"]["ok"] is None and pont.verrous == []          # jamais de verrou en simulation
    assert d["verrou"] is False and client.get("/api/arret").json()["verrou"] is False
    assert d["message"] == "ARRÊT : robot arrêté."


@pytest.mark.parametrize("mode", ["reel", "repetition"])
def test_arret_en_reel_pose_le_verrou_puis_debloquer(client, sans_pilotage, mode):
    pont = FauxPont(_etat(client).pont)
    d = client.post("/api/arret", json={"mode": mode, "raison": "essai"}).json()
    assert d["mode"] == mode and d["verrou"] is True and d["raison"] == "essai"
    assert d["parties"]["verrou"]["ok"] is True and pont.verrous == [True] and pont.stops == 1
    assert "Débloquer" in d["message"]
    a = client.get("/api/arret").json()
    assert a["verrou"] is True and a["mode"] == mode and a["par"] == "arret" and a["depuis"]
    assert _etat(client).etat_direct()["arret"]["verrou"] is True              # aussi dans /ws/etat
    r = client.post("/api/arret/debloquer")
    assert r.status_code == 200 and r.json()["verrou"] is False and pont.verrous == [True, False]
    assert "repartira" in r.json()["message"]
    a = client.get("/api/arret").json()
    assert a["verrou"] is False and a["par"] == "debloquer"


def test_le_verrou_suit_la_navigation_qui_tourne(client, sans_pilotage, monkeypatch):
    """Sans mode dans la demande (ou en « simu »), une navigation de répétition ou du robot qui tourne
    donne quand même le verrou ; une navigation de simulation, jamais."""
    pont = FauxPont(_etat(client).pont)
    etat = _etat(client)
    monkeypatch.setattr(etat, "mode_navigation", lambda: "robot")
    d = client.post("/api/arret", json={"mode": "simu"}).json()
    assert d["verrou"] is True and pont.verrous == [True]
    d = client.post("/api/arret").json()
    assert d["mode"] == "reel" and d["verrou"] is True
    monkeypatch.setattr(etat, "mode_navigation", lambda: "simu")
    d = client.post("/api/arret").json()
    assert d["mode"] == "simu" and d["verrou"] is False and pont.verrous == [True, True]


def test_pilotage_qui_repond(client, noeud_pilotage):
    FauxPont(_etat(client).pont)
    d = client.post("/api/arret", json={"mode": "repetition"}).json()
    assert d["parties"]["pilotage"] == {"ok": True, "detail": "ARRÊT : StopMove envoyé."}
    assert noeud_pilotage["recus"] == [("/arret", {"par": "atelier"})]


def test_pilotage_qui_ne_repond_pas_a_temps(client, noeud_pilotage):
    """Un nœud pilotage bloqué ne retarde pas l'ARRÊT : réponse en moins de 1 s, partie en faute."""
    pont = FauxPont(_etat(client).pont)
    noeud_pilotage["reglages"]["lent"] = 3.0
    debut = time.monotonic()
    r = client.post("/api/arret", json={"mode": "repetition"})
    assert time.monotonic() - debut < 1.0
    d = r.json()
    assert r.status_code == 200 and d["parties"]["pilotage"]["ok"] is False
    assert d["parties"]["guide"]["ok"] is True and d["parties"]["verrou"]["ok"] is True and pont.verrous == [True]
    assert "pilotage n'a pas répondu" in d["message"] and "télécommande" in d["message"]
    assert "0,6 s" in d["parties"]["pilotage"]["detail"] or "0.6 s" in d["parties"]["pilotage"]["detail"]


def test_pilotage_arrete_alors_qu_il_tournait(client, sans_pilotage, monkeypatch):
    """Nœud pilotage arrêté après avoir tourné (/pilotage/etat reçu) : ok faux, avec un message."""
    pont = FauxPont(_etat(client).pont)
    _etat(client).pont.dernier = lambda sujet: {"maitre": "pilotage"} if sujet == "/pilotage/etat" else None
    d = client.post("/api/arret", json={"mode": "repetition"}).json()
    assert d["parties"]["pilotage"]["ok"] is False and "télécommande" in d["parties"]["pilotage"]["detail"]
    assert pont.stops == 1 and pont.verrous == [True]
    # un nœud jamais vu (ni lancé par l'Atelier, ni entendu) : sans objet, même avec le vrai robot
    _etat(client).pont.dernier = lambda sujet: None
    assert client.post("/api/arret", json={"mode": "reel"}).json()["parties"]["pilotage"]["ok"] is None
    assert client.post("/api/arret", json={"mode": "simu"}).json()["parties"]["pilotage"]["ok"] is None
    # lancé par l'Atelier (même arrêté depuis) : faute
    monkeypatch.setattr(_etat(client).gestionnaire, "etat", lambda: {"pilotage": {"en_cours": False}})
    assert client.post("/api/arret", json={"mode": "simu"}).json()["parties"]["pilotage"]["ok"] is False


def test_pont_en_panne_ou_lent(client, sans_pilotage):
    FauxPont(_etat(client).pont, panne="publication refusée")
    d = client.post("/api/arret", json={"mode": "reel"}).json()
    assert d["parties"]["guide"]["ok"] is False and d["parties"]["verrou"]["ok"] is False
    assert "publication refusée" in d["parties"]["guide"]["detail"]
    FauxPont(_etat(client).pont, lent=2.0)
    debut = time.monotonic()
    d = client.post("/api/arret", json={"mode": "reel"}).json()
    assert time.monotonic() - debut < 1.0
    assert d["parties"]["guide"]["ok"] is False and "pas de réponse" in d["parties"]["guide"]["detail"]


def test_sans_pont_ros(client, sans_pilotage):
    """Sans pont ROS 2 : le verrou est impossible (faute qui le dit), le déblocage répond 503."""
    d = client.post("/api/arret", json={"mode": "reel"}).json()
    assert d["parties"]["verrou"]["ok"] is False and "télécommande" in d["parties"]["verrou"]["detail"]
    assert d["verrou"] is False
    r = client.post("/api/arret/debloquer")
    assert r.status_code == 503 and "ROS 2" in r.json()["detail"]


def test_guide_par_la_commande_sans_pont(client, sans_pilotage, faux_bin, monkeypatch):
    """Sans pont ROS 2, une navigation lancée par l'Atelier reçoit g1-guide stop (sans attendre)."""
    monkeypatch.setattr(_etat(client).gestionnaire, "en_cours", lambda role: role == "navigation")
    d = client.post("/api/arret", json={"mode": "simu"}).json()
    assert d["parties"]["guide"]["ok"] is True and "g1-guide stop" in d["parties"]["guide"]["detail"]
    fin = time.monotonic() + 10
    while time.monotonic() < fin and "g1-guide stop" not in faux_bin.appels():
        time.sleep(0.1)
    assert "g1-guide stop" in faux_bin.appels()


@pytest.mark.parametrize("corps", ["pas du json", "[1, 2]", '{"mode": "danse"}', '{"mode": 3}', ""])
def test_demande_mal_formee_jamais_refusee(client, sans_pilotage, corps):
    FauxPont(_etat(client).pont)
    r = client.post("/api/arret", content=corps, headers={"Content-Type": "application/json"})
    assert r.status_code == 200, r.text
    assert r.json()["arrete"] is True and r.json()["mode"] is None


def test_bloquer_de_naviguer_met_a_jour_le_meme_etat(client):
    pont = FauxPont(_etat(client).pont)
    r = client.post("/api/robot/arret", json={"verrou": True})
    assert r.status_code == 200 and pont.verrous == [True]
    a = client.get("/api/arret").json()
    assert a["verrou"] is True and a["par"] == "bloquer"
    client.post("/api/robot/arret", json={"verrou": False})
    assert client.get("/api/arret").json() == {**a, "verrou": False, "par": "debloquer",
                                               "depuis": client.get("/api/arret").json()["depuis"]}


def test_message_et_mode():
    parties = {n: {"ok": True, "detail": ""} for n in A.PARTIES}
    assert A.message_arret(parties, True).startswith("ARRÊT : robot arrêté et bloqué")
    parties["pilotage"]["ok"] = False
    parties["guide"]["ok"] = False
    assert A.message_arret(parties, True) == ("ARRÊT envoyé, mais le guide et le pilotage n'ont pas répondu : "
                                              "gardez la télécommande en main.")

    class Etat:
        def __init__(self, navigation):
            self.navigation = navigation

        def mode_navigation(self):
            return self.navigation

    assert A.mode_de_la_demande({"mode": "simu"}, Etat(None)) == ("simu", False)
    assert A.mode_de_la_demande({}, Etat("repetition")) == ("repetition", True)
    assert A.mode_de_la_demande({"mode": "reel"}, Etat("simu")) == ("reel", True)
    assert A.mode_de_la_demande("nimporte", Etat(None)) == (None, False)
