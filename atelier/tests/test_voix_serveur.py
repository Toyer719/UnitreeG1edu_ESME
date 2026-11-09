"""Les routes /api/voix/* (vague 6, sections 13.6 et 13.8 du plan ; agent Voix), sans ROS : le pont ROS 2 du
serveur est remplacé par un faux (dernier /voix/etat, publications notées), g1-voix par une fausse commande.

État (voix et sorties), démarrer (lieu exigé, réglages vérifiés, arguments de g1-voix, avertissement en
simulation), arrêter, essayer (409 sans nœud voix, /robot/dire conforme, source atelier), commandes (schéma
commande_voix), le son d'une phrase (audio/wav, 404 pour un id faux ou absent, jamais un chemin), jamais d'erreur
500, et la garde de la borne qui laisse passer le son.
"""
import json
import os
import signal
import sys
import time

import numpy as np
import pytest

import atelier
from atelier.lieu import copier_lieu
from atelier.lieu import voix as V
from atelier.lieu.validation import valider_donnees
from atelier.voix.synthese import ecrire_wav

DEMO = atelier.RACINE / "lieux" / "demo"
FAUX_VOIX = r'''#!{python}
"""Faux g1-voix des tests du serveur : note ses arguments, puis attend (ou s'arrête si FAUX_VOIX_ECHEC)."""
import os, sys, time
with open(os.environ["FAUX_JOURNAL"], "a") as f:
    f.write("g1-voix " + " ".join(sys.argv[1:]) + "\n")
with open(os.environ["FAUX_JOURNAL"] + ".pids", "a") as f:
    f.write(f"{{os.getpid()}}\n")
if os.environ.get("FAUX_VOIX_ECHEC"):
    print("g1-voix : réglage refusé : essai", flush=True)
    sys.exit(2)
time.sleep(120)
'''


from atelier.serveur.pont_ros import PontRos  # noqa: E402


class FauxPont(PontRos):
    """Le pont ROS 2 du serveur, sans ROS : le dernier /voix/etat est donné par le test, les publications notées."""

    def __init__(self):
        super().__init__()
        self.actif = True
        self.etat_voix = None
        self.publies = []

    def dernier(self, sujet):
        return self.etat_voix if sujet == "/voix/etat" else None

    def publier_json(self, sujet, donnees):
        self.publies.append((sujet, donnees))
        return 1


@pytest.fixture
def banc(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from atelier.serveur.main import creer_app
    monkeypatch.setenv("ATELIER_LIEUX", str(tmp_path / "lieux"))
    monkeypatch.setenv("ATELIER_VOIX_SONS", str(tmp_path / "sons"))
    monkeypatch.setenv("ATELIER_INTERFACE_ROBOT", "interface_absente_voix")
    monkeypatch.delenv("ATELIER_HOTE", raising=False)
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "g1-voix").write_text(FAUX_VOIX.format(python=sys.executable))
    (bin_ / "g1-voix").chmod(0o755)
    journal = tmp_path / "appels.txt"
    monkeypatch.setenv("ATELIER_BIN", str(bin_))
    monkeypatch.setenv("FAUX_JOURNAL", str(journal))
    copier_lieu(DEMO, tmp_path / "lieux" / "demo")
    app = creer_app(ros=False)
    pont = FauxPont()
    app.state.atelier.pont = pont
    with TestClient(app) as client:
        client.pont, client.journal, client.etat = pont, journal, app.state.atelier
        yield client
    pids = journal.with_name("appels.txt.pids")
    for ligne in (pids.read_text().split() if pids.exists() else []):
        try:
            os.kill(int(ligne), signal.SIGKILL)
        except ProcessLookupError:
            pass


def etat_frais(**champs):
    d = dict(V.EXEMPLE_ETAT_VOIX, age_recu_s=0.4, perime=False)
    d.update(champs)
    return d


def test_etat_sans_noeud(banc):
    r = banc.get("/api/voix/etat")
    assert r.status_code == 200
    d = r.json()
    assert d["lancee"] is False and d["tourne"] is False and d["etat"] is None
    assert [s["id"] for s in d["sorties"]] == list(V.SORTIES_VOIX)
    assert "à vérifier" in d["sorties"][2]["libelle"] and all(s["aide"] for s in d["sorties"])
    assert {v["id"] for v in d["voix"]} == set(V.VOIX_PIPER) and d["voix_defaut"] == V.VOIX_DEFAUT
    banc.pont.etat_voix = etat_frais()
    d = banc.get("/api/voix/etat").json()
    assert d["tourne"] is True and d["etat"]["sortie"] == "robot"
    banc.pont.etat_voix = etat_frais(age_recu_s=8.0)
    assert banc.get("/api/voix/etat").json()["tourne"] is False


def test_demarrer_verifie_les_reglages(banc):
    for corps, statut in (({"lieu": "../x"}, 400), ({"lieu": "Demo"}, 400), ({"lieu": 3}, 400),
                          ({"lieu": "absent"}, 404), ({"lieu": "demo", "sortie": "pc"}, 422),
                          ({"lieu": "demo", "volume": 101}, 422), ({"lieu": "demo", "volume": "fort"}, 422),
                          ({"lieu": "demo", "voix": "fr_FR-x"}, 422), ({"lieu": "demo", "vitesse": 3}, 422)):
        r = banc.post("/api/voix/demarrer", json=corps)
        assert r.status_code == statut, (corps, r.text)
        assert r.json()["detail"]
    assert not banc.journal.exists()                  # rien n'a été lancé


def test_demarrer_puis_arreter(banc):
    r = banc.post("/api/voix/demarrer", json={"lieu": "demo", "sortie": "borne", "volume": 60,
                                              "voix": "fr_FR-tom-medium", "vitesse": 1.1})
    assert r.status_code == 200, r.text
    assert r.json()["lance"] is True and "avertissement" not in r.json()
    assert banc.journal.read_text().splitlines() == [
        "g1-voix --lieu demo --sortie borne --volume 60 --voix fr_FR-tom-medium --vitesse 1.1"]
    assert banc.get("/api/voix/etat").json()["lancee"] is True
    r = banc.post("/api/voix/arreter")
    assert r.status_code == 200 and r.json()["arrete"] is True
    assert banc.get("/api/voix/etat").json()["lancee"] is False
    r = banc.post("/api/voix/arreter")
    assert r.status_code == 200 and r.json()["arrete"] is False


def test_demarrer_sans_lieu_ni_reglages(banc):
    r = banc.post("/api/voix/demarrer", json={"mode": "repetition"})
    assert r.status_code == 200, r.text
    assert banc.journal.read_text().splitlines() == ["g1-voix "]
    banc.post("/api/voix/arreter")


def test_demarrer_sans_ros_rien_n_est_lance(banc):
    banc.pont.actif = False
    r = banc.post("/api/voix/demarrer", json={"lieu": "demo"})
    assert r.status_code == 503 and "ROS 2" in r.json()["detail"]
    assert not banc.journal.exists()


def test_demarrer_en_simulation_avertit(banc, monkeypatch):
    monkeypatch.setattr(banc.etat, "mode_navigation", lambda: "simu")
    r = banc.post("/api/voix/demarrer", json={"lieu": "demo"})
    assert r.status_code == 200 and "Borne" in r.json()["avertissement"]
    banc.post("/api/voix/arreter")


def test_demarrer_qui_echoue(banc, monkeypatch):
    monkeypatch.setenv("FAUX_VOIX_ECHEC", "1")
    r = banc.post("/api/voix/demarrer", json={"lieu": "demo"})
    assert r.status_code == 502 and "arrêtée au démarrage" in r.json()["detail"]
    assert "réglage refusé" in r.json()["sortie"]


def test_demarrer_sans_la_commande(banc):
    (banc.journal.parent / "bin" / "g1-voix").unlink()
    r = banc.post("/api/voix/demarrer", json={"lieu": "demo"})
    assert r.status_code == 503 and "g1-voix" in r.json()["detail"]


def test_essayer(banc):
    r = banc.post("/api/voix/essayer", json={"texte": "Bonjour !"})
    assert r.status_code == 409 and "Démarrer la voix" in r.json()["detail"]
    assert banc.pont.publies == []
    banc.pont.etat_voix = etat_frais(sortie="borne")
    r = banc.post("/api/voix/essayer", json={"texte": "  Bonjour, suivez-moi !  ",
                                             "voix": {"nom": "fr_FR-tom-medium", "vitesse": 1.2, "volume": 80}})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["envoye"] is True and d["sortie"] == "borne" and "Borne" in d["detail"]
    sujet, message = banc.pont.publies[-1]
    assert sujet == "/robot/dire" and valider_donnees("robot_dire", message) == []
    assert message["texte"] == "Bonjour, suivez-moi !" and message["source"] == "atelier"
    assert message["priorite"] == "haute" and message["voix"] == {"nom": "fr_FR-tom-medium", "vitesse": 1.2,
                                                                   "volume": 80}
    assert V.MOTIF_ID_SON.match(message["id"]) and d["id"] == message["id"] and d["url"] == V.URL_SON + d["id"]
    r = banc.post("/api/voix/essayer", json={"texte": "Normal.", "priorite": "normale"})
    assert r.status_code == 200 and banc.pont.publies[-1][1]["priorite"] == "normale"
    assert "voix" not in banc.pont.publies[-1][1]
    assert banc.post("/api/voix/essayer", json={"texte": "Un."}).json()["id"] != d["id"]


@pytest.mark.parametrize("corps", [
    {}, {"texte": ""}, {"texte": "   "}, {"texte": 12}, {"texte": "x" * 501}, {"texte": "a", "priorite": "max"},
    {"texte": "a", "voix": "tom"}, {"texte": "a", "voix": {"nom": "x"}}, {"texte": "a", "voix": {"vitesse": 9}},
    {"texte": "a", "voix": {"volume": -1}}, {"texte": "a", "voix": {"hauteur": 1}},
])
def test_essayer_refuse(banc, corps):
    banc.pont.etat_voix = etat_frais()
    r = banc.post("/api/voix/essayer", json=corps)
    assert r.status_code == 422 and r.json()["detail"]
    assert banc.pont.publies == []


def test_essayer_sans_pont(banc):
    banc.pont.actif = False
    r = banc.post("/api/voix/essayer", json={"texte": "Bonjour"})
    assert r.status_code == 503 and "ROS 2" in r.json()["detail"]


def test_commandes(banc):
    r = banc.post("/api/voix/commande", json={"action": "taire"})
    assert r.status_code == 409
    banc.pont.etat_voix = etat_frais()
    for corps, attendu in (({"action": "taire"}, "se tait"), ({"action": "volume", "volume": 60}, "60 %"),
                           ({"action": "sortie", "sortie": "robot_tts"}, "Sortie"),
                           ({"action": "voix", "voix": "fr_FR-tom-medium"}, "Voix")):
        r = banc.post("/api/voix/commande", json=corps)
        assert r.status_code == 200 and attendu in r.json()["detail"], r.text
        sujet, message = banc.pont.publies[-1]
        assert sujet == "/voix/commande" and valider_donnees("commande_voix", message) == []
        assert message["action"] == corps["action"] and message["version"] == 1 and message["id"]
    assert len(banc.pont.publies) == 4


@pytest.mark.parametrize("corps", [
    {}, {"action": "fort"}, {"action": "volume"}, {"action": "volume", "volume": 300},
    {"action": "sortie", "sortie": "pc"}, {"action": "voix", "voix": "fr_FR-inconnue"},
    {"action": "taire", "en_plus": 1},
])
def test_commandes_refusees(banc, corps):
    banc.pont.etat_voix = etat_frais()
    r = banc.post("/api/voix/commande", json=corps)
    assert r.status_code == 422 and r.json()["detail"]
    assert banc.pont.publies == []


def test_son_d_une_phrase(banc):
    for ident, statut in (("s-1", 404), ("S-1", 404), ("..", 404), ("a.wav", 404), ("x" * 70, 404)):
        r = banc.get(f"/api/voix/son/{ident}")
        assert r.status_code == statut and r.json()["detail"], ident
    assert banc.get("/api/voix/son/..%2F..%2Fetc%2Fpasswd").status_code == 404
    ecrire_wav(V.chemin_son("s-20261112-142031-0003"), (np.arange(2205) % 100 * 100).astype(np.int16), 22050)
    r = banc.get("/api/voix/son/s-20261112-142031-0003")
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
    assert r.content[:4] == b"RIFF" and r.content[8:12] == b"WAVE"


def test_jamais_d_erreur_500(banc):
    banc.pont.etat_voix = etat_frais()
    for methode, url, corps in (("post", "/api/voix/essayer", "pas du JSON"), ("post", "/api/voix/commande", "[1]"),
                                ("post", "/api/voix/demarrer", "null"), ("post", "/api/voix/essayer", "[]"),
                                ("get", "/api/voix/son/%00", None), ("post", "/api/voix/arreter", "x")):
        r = getattr(banc, methode)(url, content=corps) if corps is not None else getattr(banc, methode)(url)
        assert r.status_code < 500, (url, r.status_code, r.text)
        assert r.json()["detail"]


def test_la_borne_peut_lire_le_son(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from atelier.serveur.main import creer_app
    monkeypatch.setenv("ATELIER_LIEUX", str(tmp_path / "lieux"))
    monkeypatch.setenv("ATELIER_VOIX_SONS", str(tmp_path / "sons"))
    monkeypatch.setenv("ATELIER_HOTE", "0.0.0.0")
    copier_lieu(DEMO, tmp_path / "lieux" / "demo")
    ecrire_wav(V.chemin_son("essai-1"), np.zeros(100, dtype=np.int16), 16000)
    app = creer_app(ros=False)
    with TestClient(app, client=("192.168.0.50", 50000)) as tablette:
        assert tablette.get("/api/voix/son/essai-1").status_code == 200
        assert tablette.get("/api/voix/etat").status_code == 403
        assert tablette.post("/api/voix/essayer", json={"texte": "Bonjour"}).status_code == 403
        assert tablette.post("/api/voix/commande", json={"action": "taire"}).status_code == 403
