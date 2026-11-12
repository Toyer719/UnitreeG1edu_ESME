"""Liaison avec le robot pour l'accueil en mode Réel (vague 5, section 12.4 du plan ; agent Coquille) :
GET /api/robot/liaison, sans robot. Les pings visent 127.0.0.1 par l'interface lo (jamais
192.168.123.x pendant les essais : ATELIER_PC1, ATELIER_JETSON, ATELIER_INTERFACE_ROBOT)."""
import os
import shutil
import time

import pytest

from atelier.serveur.routes import liaison as L

from .test_serveur_communs import client, faux_bin, journaux, lieux  # noqa: F401

URI_ROBOT = ('<CycloneDDS><Domain><General><Interfaces><NetworkInterface name="lo" priority="default" '
             'multicast="default" /></Interfaces></General></Domain></CycloneDDS>')


@pytest.fixture
def local(monkeypatch):
    monkeypatch.setenv("ATELIER_INTERFACE_ROBOT", "lo")
    monkeypatch.setenv("ATELIER_PC1", "127.0.0.1")
    monkeypatch.setenv("ATELIER_JETSON", "127.0.0.1")


@pytest.mark.skipif(shutil.which("ping") is None, reason="ping absent")
def test_robot_relie_par_lo(client, local, monkeypatch):
    monkeypatch.setenv("ROS_DOMAIN_ID", "0")
    monkeypatch.setenv("CYCLONEDDS_URI", URI_ROBOT)
    debut = time.monotonic()
    r = client.get("/api/robot/liaison")
    assert time.monotonic() - debut < 1.5
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["interface"] == "lo" and d["cable"] is True and d["adresse_pc"] == "127.0.0.1"
    assert d["pc1"]["adresse"] == "127.0.0.1" and d["pc1"]["repond"] is True and d["pc1"]["ms"] >= 0
    assert d["jetson"]["repond"] is True
    assert d["ros"] == {"domaine": "0", "cyclonedds": "lo", "actif": False}
    assert d["pret"] is True and d["message"].startswith("Robot relié") and d["duree_s"] <= 1.5


@pytest.mark.skipif(shutil.which("ping") is None, reason="ping absent")
def test_domaine_du_terminal(client, local, monkeypatch):
    """Câble et robot là, mais l'Atelier n'a pas été lancé après robot.sh (domaine ≠ 0) : pas prêt."""
    monkeypatch.setenv("ROS_DOMAIN_ID", "101")
    monkeypatch.delenv("CYCLONEDDS_URI", raising=False)
    d = client.get("/api/robot/liaison").json()
    assert d["cable"] is True and d["pc1"]["repond"] is True and d["pret"] is False
    assert d["ros"]["domaine"] == "101" and d["ros"]["cyclonedds"] is None
    assert "robot.sh" in d["message"]


def test_sans_cable_aucun_ping(client, monkeypatch):
    """Interface absente : pas de câble, et aucun ping (repond null)."""
    monkeypatch.setenv("ATELIER_INTERFACE_ROBOT", "absente0")
    monkeypatch.setenv("ATELIER_PC1", "127.0.0.1")

    async def interdit(adresse):
        raise AssertionError(f"ping envoyé vers {adresse} sans câble")

    monkeypatch.setattr(L, "ping", interdit)
    d = client.get("/api/robot/liaison").json()
    assert d["cable"] is False and d["adresse_pc"] is None and d["pret"] is False
    assert d["pc1"] == {"adresse": "127.0.0.1", "repond": None, "ms": None}
    assert d["jetson"]["repond"] is None
    assert "branchez le câble" in d["message"] and "Répétition sans robot" in d["message"]


def _faux_ping(dossier, monkeypatch, script):
    """Un faux « ping » en tête du PATH (le vrai réseau n'intervient pas : une adresse « jamais routée » peut
    répondre sur certains réseaux, constaté le 31/10 avec 192.0.2.1)."""
    dossier.mkdir(exist_ok=True)
    faux = dossier / "ping"
    faux.write_text("#!/bin/sh\n" + script + "\n")
    faux.chmod(0o755)
    monkeypatch.setenv("PATH", f"{dossier}:{os.environ.get('PATH', '')}")


def test_robot_qui_ne_repond_pas(client, local, monkeypatch, tmp_path):
    """Le ping rend la main sans réponse (code 1) : PC1 et Jetson ne répondent pas, pas prêt."""
    _faux_ping(tmp_path / "bin", monkeypatch, "exit 1")
    debut = time.monotonic()
    d = client.get("/api/robot/liaison").json()
    assert time.monotonic() - debut < 1.6
    assert d["pc1"]["repond"] is False and d["jetson"]["repond"] is False and d["pret"] is False
    assert "ne répond pas" in d["message"]


def test_ping_bloque_garde_fou(client, local, monkeypatch, tmp_path):
    """Un ping qui ne rend jamais la main : arrêté par le garde-fou, réponse en 1,5 s au plus."""
    _faux_ping(tmp_path / "bin", monkeypatch, "exec sleep 5")
    debut = time.monotonic()
    d = client.get("/api/robot/liaison").json()
    assert time.monotonic() - debut < 1.6
    assert d["pc1"]["repond"] is False and d["duree_s"] <= 1.5


def test_ping_absent(client, local, monkeypatch, tmp_path):
    """Sans la commande ping : pas de réponse, et l'erreur le dit (jamais d'erreur 500)."""
    vide = tmp_path / "vide"
    vide.mkdir()
    monkeypatch.setenv("PATH", str(vide))
    r = client.get("/api/robot/liaison")
    assert r.status_code == 200
    assert r.json()["pc1"]["repond"] is False and "ping" in r.json()["pc1"]["erreur"]


def test_interface_de_cyclonedds_et_adresse():
    assert L.interface_cyclonedds(URI_ROBOT) == "lo"
    assert L.interface_cyclonedds('<NetworkInterfaceAddress>eno2</NetworkInterfaceAddress>') == "eno2"
    assert L.interface_cyclonedds("") is None
    assert L.adresse_ipv4("lo") == "127.0.0.1"
    assert L.adresse_ipv4("absente0") is None
    assert L.cable_present("absente0") is False


def test_messages():
    pc1 = {"adresse": "192.168.123.161", "repond": True, "ms": 0.4}
    jetson = {"adresse": "192.168.123.164", "repond": False, "ms": None}
    texte = L.message_liaison("eno2", True, pc1, jetson, "0", "eno2")
    assert texte.startswith("Robot relié : il répond en 0,4 ms.") and "Jetson ne répond pas" in texte
    assert "robot.sh" in L.message_liaison("eno2", True, pc1, jetson, "0", "wlp3s0")
