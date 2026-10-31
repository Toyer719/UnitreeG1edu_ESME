"""Démarrage réel de l'Atelier : bin/g1-atelier lance uvicorn, curl interroge quelques routes,
puis Ctrl+C (SIGINT) arrête le serveur, et avec lui la simulation qu'il a lancée.

Lieux : copie temporaire de demo. Commandes g1-* : les fausses de test_serveur_communs.
Domaine ROS : celui de l'environnement, 34 par défaut. Les journaux des commandes lancées vont
dans ~/robot-g1/journaux (atelier_simulation_*.log), comme en vrai.
"""
import json
import os
import shutil
import signal
import socket
import subprocess
import time

import pytest

import atelier

from .test_serveur_communs import attendre, faux_bin, journaux, lieux, processus_vivant  # noqa: F401

G1_ATELIER = atelier.RACINE / "bin" / "g1-atelier"

pytestmark = pytest.mark.skipif(shutil.which("curl") is None, reason="curl absent")


def _port_libre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _curl(*arguments):
    """(code HTTP, corps) d'un appel curl."""
    r = subprocess.run(["curl", "-s", "-m", "20", "-w", "\n%{http_code}", *arguments],
                       capture_output=True, text=True, timeout=30)
    corps, _, code = r.stdout.rpartition("\n")
    return int(code or 0), corps


@pytest.fixture
def serveur(lieux, faux_bin):
    port = _port_libre()
    env = dict(os.environ)
    env.setdefault("ROS_DOMAIN_ID", "34")
    p = subprocess.Popen([str(G1_ATELIER), "--sans-navigateur", "--port", str(port)], env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
    base = f"http://127.0.0.1:{port}"
    try:
        pret = attendre(lambda: p.poll() is None and _curl(base + "/api/etat")[0] == 200, 30, 0.25)
        if not pret:
            sortie = p.stdout.read().decode() if p.poll() is not None else "(toujours lancé)"
            pytest.fail(f"le serveur ne répond pas sur {base} : {sortie}")
        yield p, base
    finally:
        if p.poll() is None:
            os.killpg(p.pid, signal.SIGKILL)
            p.wait()


def test_g1_atelier_demarre_repond_et_s_arrete(serveur, faux_bin):
    p, base = serveur
    code, corps = _curl(base + "/api/etat")
    assert code == 200 and json.loads(corps)["commandes"]["g1-monde"]
    code, corps = _curl(base + "/")
    assert code == 200 and "<title>Atelier G1</title>" in corps
    for chemin in ("/js/app.js", "/vendor/leaflet/leaflet.js", "/vendor/three/three.module.js"):
        assert _curl("-o", "/dev/null", base + chemin)[0] == 200, chemin
    code, corps = _curl(base + "/api/lieux")
    assert code == 200 and json.loads(corps)[0]["id"] == "demo"
    code, corps = _curl(base + "/api/lieux/demo/etages/rdc/monde")
    assert code == 200 and len(json.loads(corps)["murs"]) == 18
    code, corps = _curl(base + "/api/lieux/demo/etages/rdc/carte.png")
    assert code == 404 and "Simulation › Dessiner" in json.loads(corps)["detail"]
    code, _ = _curl("-X", "POST", base + "/api/lieux/demo/etages/rdc/monde/generer")
    assert code == 200
    r = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code} %{content_type}",
                        base + "/api/lieux/demo/etages/rdc/carte.png"], capture_output=True, text=True, timeout=30)
    assert r.stdout == "200 image/png"
    code, corps = _curl("-X", "POST", "-H", "Content-Type: application/json",
                        "-d", '{"lieu": "demo", "etage": "rdc"}', base + "/api/simulation/demarrer")
    assert code == 200, corps
    assert attendre(lambda: len(faux_bin.pids()) == 4)
    pids = faux_bin.pids()
    assert all(processus_vivant(x) for x in pids)
    # Ctrl+C : le serveur s'arrête proprement et arrête la simulation et la navigation
    debut = time.monotonic()
    os.kill(p.pid, signal.SIGINT)
    p.wait(timeout=30)
    assert time.monotonic() - debut < 20
    assert attendre(lambda: not any(processus_vivant(x) for x in pids), 5), "des processus ont survécu au serveur"
    try:
        os.killpg(p.pid, 0)
        reste = True
    except ProcessLookupError:
        reste = False
    assert not reste, "il reste des processus dans le groupe du serveur"


def test_g1_atelier_options():
    r = subprocess.run([str(G1_ATELIER), "--help"], capture_output=True, text=True, timeout=10)
    assert r.returncode == 0 and "--sans-navigateur" in r.stdout
    r = subprocess.run([str(G1_ATELIER), "--port", "abc"], capture_output=True, text=True, timeout=10)
    assert r.returncode == 2 and "nombre" in r.stderr
    r = subprocess.run([str(G1_ATELIER), "--inconnue"], capture_output=True, text=True, timeout=10)
    assert r.returncode == 2 and "inconnue" in r.stderr
    alias = atelier.RACINE / "bin" / "gl-atelier"
    assert alias.is_symlink() and os.readlink(alias) == "g1-atelier"


def test_g1_atelier_refuse_un_port_pris(serveur):
    _, base = serveur
    port = base.rsplit(":", 1)[1]
    r = subprocess.run([str(G1_ATELIER), "--sans-navigateur", "--port", port], capture_output=True, text=True,
                       timeout=30)
    assert r.returncode == 1 and "déjà pris" in r.stderr
