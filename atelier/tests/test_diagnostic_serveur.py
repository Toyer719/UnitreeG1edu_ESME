"""Les routes du diagnostic (vague 6, section 13.2 et 13.8 du plan) : agent Diagnostic.

TestClient sur l'application, sans ROS : le pont du serveur est remplacé par le faux pont des tests (le vrai service
robot_state du faux G1), les vérifications système par le faux contexte (ATELIER_DIAGNOSTIC_FAUX).

- GET /api/robot/diagnostic : conforme au schéma, mode de la demande ou de la navigation, 409 en simulation, 400 et
  422 en français, jamais 500 ; GET …/dernier ;
- POST /api/robot/diagnostic/{action} : 404 inconnue, 409 sans « confirme » (et rien n'est envoyé), 403 service
  interdit, 409 en simulation ou le câble en répétition, 409 si la même action tourne déjà ; avec « confirme » :
  exactement les 1001 de la liste blanche, le diagnostic refait ; le câble : la commande notée, jamais lancée ;
- deux demandes pareilles en même temps : un seul diagnostic ; un vrai serveur (g1-atelier) : l'ARRÊT répond en
  moins d'une seconde pendant un diagnostic lent (jamais bloquant).
"""
import json
import threading
import time
import urllib.request

import pytest
from fastapi.testclient import TestClient

import atelier
from atelier.lieu import copier_lieu, valider_donnees
from atelier.serveur.main import creer_app
from atelier.serveur.routes.diagnostic import MemoireDiagnostic, memoire

from .test_diagnostic_communs import FauxPont, GRAPHE_FAUX_G1, ecrire_faux, faux_systeme, lire_journal, par_id
from .test_serveur_communs import faux_bin, journaux, lieux  # noqa: F401
from .test_serveur_demarrage import serveur  # noqa: F401

DEMO = atelier.RACINE / "lieux" / "demo"


@pytest.fixture
def faux(tmp_path, monkeypatch):
    chemin = ecrire_faux(tmp_path / "faux.json", faux_systeme())
    monkeypatch.setenv("ATELIER_DIAGNOSTIC_FAUX", str(chemin))
    return chemin


@pytest.fixture
def client(tmp_path, monkeypatch, faux):
    monkeypatch.setenv("ATELIER_LIEUX", str(tmp_path / "lieux"))
    monkeypatch.delenv("ATELIER_HOTE", raising=False)
    copier_lieu(DEMO, tmp_path / "lieux" / "demo")
    app = creer_app(ros=False)
    with TestClient(app) as c:
        c.etat = app.state.atelier
        c.etat.pont = FauxPont(graphe=GRAPHE_FAUX_G1, arretes=("lidar_driver", "unitree_slam"), delai_demarrage_s=0.2)
        c.faux = faux
        yield c


def test_diagnostic_en_repetition(client):
    r = client.get("/api/robot/diagnostic?mode=repetition")
    assert r.status_code == 200, r.text
    d = r.json()
    assert valider_donnees("diagnostic", d) == [] and d["mode"] == "repetition" and d["source"] == "atelier"
    v = par_id(d)["services"]
    assert v["etat"] == "probleme" and v["action"] == "demarrer-services" and d["actions"] == ["demarrer-services"]
    assert ("robot_state", 1003, "{}") in client.etat.pont.appels
    assert {x["id"] for x in d["ignorees"]} >= {"cable", "pc1", "jetson", "jetson_ssh"}
    assert lire_journal(client.faux) == []          # rien du réseau du robot en répétition


def test_diagnostic_reel_par_defaut_et_rapide(client):
    client.etat.pont = FauxPont()
    d = client.get("/api/robot/diagnostic").json()
    assert d["mode"] == "reel" and d["etat"] == "ok" and d["faux"] is True and len(d["verifications"]) == 17
    d = client.get("/api/robot/diagnostic?mode=reel&rapide=1").json()
    assert "jetson_ssh" in {x["id"] for x in d["ignorees"]}
    assert [x["genre"] for x in lire_journal(client.faux)].count("ssh") == 1       # le seul : celui du premier


def test_mode_de_la_navigation_qui_tourne(client, monkeypatch):
    monkeypatch.setattr(client.etat, "mode_navigation", lambda: "repetition")
    assert client.get("/api/robot/diagnostic").json()["mode"] == "repetition"
    monkeypatch.setattr(client.etat, "mode_navigation", lambda: "robot")
    client.etat.pont = FauxPont()
    assert client.get("/api/robot/diagnostic").json()["mode"] == "reel"


def test_demandes_refusees_en_francais(client):
    r = client.get("/api/robot/diagnostic?mode=simu")
    assert r.status_code == 409 and "simulation" in r.json()["detail"]
    r = client.get("/api/robot/diagnostic?mode=lune")
    assert r.status_code == 400 and "inconnu" in r.json()["detail"]
    r = client.get("/api/robot/diagnostic?rapide=peut-etre")
    assert r.status_code == 422 and "rapide" in r.json()["detail"]
    r = client.get("/api/robot/diagnostic/dernier")
    assert r.status_code == 404 and "Vérifier le robot" in r.json()["detail"]


def test_le_dernier_diagnostic(client):
    client.get("/api/robot/diagnostic?mode=repetition")
    d = client.get("/api/robot/diagnostic/dernier").json()
    assert d["mode"] == "repetition"
    assert client.get("/api/robot/diagnostic/dernier?mode=repetition").json()["date"] == d["date"]
    assert client.get("/api/robot/diagnostic/dernier?mode=reel").status_code == 404


def test_actions_refusees_sans_rien_envoyer(client):
    pont = client.etat.pont
    r = client.post("/api/robot/diagnostic/eteindre", json={"confirme": True})
    assert r.status_code == 404 and "Rien n'a été envoyé" in r.json()["detail"]
    for corps in ({}, {"confirme": False}, {"confirme": "true"}, {"confirme": 1}, {"mode": "repetition"}):
        r = client.post("/api/robot/diagnostic/demarrer-services", json=corps)
        assert r.status_code == 409 and "confirmation" in r.json()["detail"], corps
    r = client.post("/api/robot/diagnostic/demarrer-services", content=b"pas du json",
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 409
    r = client.post("/api/robot/diagnostic/demarrer-services", json=["confirme"])
    assert r.status_code == 409
    for services in (["ai_sport"], ["lidar_driver", "motion_switcher"], "unitree_slam", [True]):
        r = client.post("/api/robot/diagnostic/demarrer-services",
                        json={"confirme": True, "mode": "repetition", "services": services})
        assert r.status_code == 403 and "interdit" in r.json()["detail"], services
    r = client.post("/api/robot/diagnostic/demarrer-services", json={"confirme": True, "mode": "simu"})
    assert r.status_code == 409 and "simulation" in r.json()["detail"]
    r = client.post("/api/robot/diagnostic/retablir-cable", json={"confirme": True, "mode": "repetition"})
    assert r.status_code == 409 and "répétition" in r.json()["detail"]
    assert pont.appels == [] and lire_journal(client.faux) == []


def test_demarrer_les_services_confirme(client):
    pont = client.etat.pont
    r = client.post("/api/robot/diagnostic/demarrer-services", json={"confirme": True, "mode": "repetition"})
    assert r.status_code == 200, r.text
    reponse = r.json()
    assert reponse["action"] == "demarrer-services" and reponse["ok"] is True and "démarrés" in reponse["message"]
    assert pont.switchs() == [{"name": "lidar_driver", "switch": 1}, {"name": "unitree_slam", "switch": 1}]
    assert pont.robot_state.nombre_interdits == 0
    d = reponse["diagnostic"]
    assert valider_donnees("diagnostic", d) == [] and par_id(d)["services"]["etat"] == "ok"
    assert client.get("/api/robot/diagnostic/dernier?mode=repetition").json()["date"] == d["date"]


def test_demarrer_les_services_en_simulation_quand_rien_n_est_dit(client, monkeypatch):
    monkeypatch.setattr(client.etat, "mode_navigation", lambda: "simu")
    r = client.post("/api/robot/diagnostic/demarrer-services", json={"confirme": True})
    assert r.status_code == 409 and client.etat.pont.appels == []


def test_actions_du_cable(client):
    client.etat.pont = FauxPont()
    r = client.post("/api/robot/diagnostic/retablir-cable", json={"confirme": True})
    assert r.status_code == 200 and r.json()["ok"] is True and r.json()["diagnostic"]["mode"] == "reel"
    r = client.post("/api/robot/diagnostic/cable-automatique", json={"confirme": True, "mode": "reel"})
    assert r.status_code == 200 and r.json()["ok"] is True
    commandes = [x["commande"] for x in lire_journal(client.faux) if x["genre"] == "commande"]
    assert "nmcli connection up robot-g1" in commandes
    assert "nmcli connection modify robot-g1 connection.autoconnect yes" in commandes


def test_une_action_a_la_fois(client):
    m = memoire(client.app)
    with m.action("demarrer-services"):
        r = client.post("/api/robot/diagnostic/demarrer-services", json={"confirme": True, "mode": "repetition"})
    assert r.status_code == 409 and "déjà en cours" in r.json()["detail"] and client.etat.pont.appels == []


def test_jamais_d_erreur_500(client, monkeypatch):
    class PontCasse(FauxPont):
        def infos_sujet(self, sujet):
            raise RuntimeError("graphe cassé")

        def appeler_unitree(self, *a, **k):
            raise ZeroDivisionError("bogue")
    client.etat.pont = PontCasse()
    r = client.get("/api/robot/diagnostic?mode=repetition")
    assert r.status_code == 200 and par_id(r.json())["services"]["etat"] == "inconnu"
    r = client.post("/api/robot/diagnostic/demarrer-services", json={"confirme": True, "mode": "repetition"})
    assert r.status_code == 503 and "échoué" in r.json()["detail"]
    monkeypatch.setenv("ATELIER_DIAGNOSTIC_FAUX", str(client.faux.parent / "absent.json"))
    r = client.get("/api/robot/diagnostic?mode=reel")
    assert r.status_code == 400 and "illisible" in r.json()["detail"]


def test_deux_demandes_pareilles_un_seul_diagnostic():
    m = MemoireDiagnostic()
    faits = []

    def faire():
        faits.append(1)
        time.sleep(0.4)
        return {"mode": "reel", "numero": len(faits)}
    resultats = []
    fils = [threading.Thread(target=lambda: resultats.append(m.diagnostic(("reel", False), faire))) for _ in range(3)]
    for f in fils:
        f.start()
    for f in fils:
        f.join()
    assert faits == [1] and [r["numero"] for r in resultats] == [1, 1, 1] and m.dernier("reel")["numero"] == 1
    assert m.diagnostic(("reel", False), faire)["numero"] == 2          # fini : le suivant en refait un


@pytest.fixture
def faux_lent(tmp_path, monkeypatch):
    """Vérifications système lentes (pings de 2 s) et un serveur sans ROS."""
    chemin = ecrire_faux(tmp_path / "lent.json", faux_systeme(delais={"ping": 2.0}))
    monkeypatch.setenv("ATELIER_DIAGNOSTIC_FAUX", str(chemin))
    monkeypatch.setenv("ATELIER_ROS", "0")
    return chemin


def _post(url, corps):
    req = urllib.request.Request(url, data=json.dumps(corps).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, json.loads(r.read())


def test_jamais_bloquant_l_arret_repond_pendant_un_diagnostic(faux_lent, serveur, lieux):  # noqa: F811
    _, base = serveur
    resultat = {}

    def diagnostiquer():
        debut = time.monotonic()
        with urllib.request.urlopen(base + "/api/robot/diagnostic?mode=reel", timeout=30) as r:
            resultat["d"] = json.loads(r.read())
        resultat["duree"] = time.monotonic() - debut
    fil = threading.Thread(target=diagnostiquer)
    fil.start()
    time.sleep(0.5)                              # le diagnostic attend ses pings
    debut = time.monotonic()
    statut, arret = _post(base + "/api/arret", {"mode": "simu", "raison": "essai du diagnostic"})
    duree_arret = time.monotonic() - debut
    with urllib.request.urlopen(base + "/api/etat", timeout=5) as r:
        assert r.status == 200
    fil.join(30)
    assert statut == 200 and arret["arrete"] is True and duree_arret < 1.0, duree_arret
    assert 1.9 <= resultat["duree"] < 10.0, resultat
    d = resultat["d"]
    assert valider_donnees("diagnostic", d) == [] and par_id(d)["ros"]["etat"] == "probleme"     # sans ROS
    assert par_id(d)["pc1"]["etat"] == "ok" and d["duree_s"] < 9.5
