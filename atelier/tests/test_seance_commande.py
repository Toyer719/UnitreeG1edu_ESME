"""La commande g1-seance (vague 6, section 13.3 du plan) : agent Boîte noire.

bin/g1-seance lancée pour de vrai (environnement ROS 2 du projet) sur un $ATELIER_SEANCES de test : liste (texte et
JSON), rapport (par id, « derniere » ou chemin), exporter (.zip avec et sans le bag), demarrer / arreter / etat
sans Atelier (code 1 et la phrase qui dit quoi faire), puis contre un Atelier de test (TestClient → vrai serveur
uvicorn sur un port libre), enregistrer quand la place manque, et l'aide.
"""
import json
import os
import socket
import subprocess
import time
import zipfile

import pytest

import atelier
from atelier.seance import manifeste as M
from . import test_seance_communs as C
from .test_serveur_communs import DEMO

G1_SEANCE = atelier.RACINE / "bin" / "g1-seance"
T0 = time.time() - 7200


def g1_seance(*arguments, env=None, delai=120):
    environnement = dict(os.environ)
    environnement.update(env or {})
    r = subprocess.run([str(G1_SEANCE), *map(str, arguments)], capture_output=True, text=True, timeout=delai,
                       env=environnement, cwd=environnement.get("CWD_ESSAI") or None)
    return r.returncode, r.stdout + r.stderr


@pytest.fixture
def seances(tmp_path, monkeypatch):
    monkeypatch.setenv("ATELIER_SEANCES", str(tmp_path / "seances"))
    (tmp_path / "seances").mkdir()
    return tmp_path / "seances"


def _port_libre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_aide_et_liste_vide(seances):
    code, sortie = g1_seance()
    assert code == 2 and "g1-seance" in sortie and "rapport" in sortie
    code, sortie = g1_seance("liste")
    assert code == 0 and "Aucune séance" in sortie
    code, sortie = g1_seance("liste", "--json")
    assert code == 0 and json.loads(sortie) == []


@pytest.mark.skipif(not C.ros_disponible(), reason="ROS 2 non chargé")
def test_rapport_liste_et_export(seances, tmp_path):
    dossier = C.seance_essai(seances, T0, demo=DEMO)
    code, sortie = g1_seance("rapport", dossier.name)
    assert code == 0 and "3 trajets" in sortie and (dossier / "rapport.html").is_file(), sortie
    code, sortie = g1_seance("rapport", "derniere")
    assert code == 0, sortie
    code, sortie = g1_seance("rapport", str(dossier))
    assert code == 0, sortie
    code, sortie = g1_seance("liste")
    assert code == 0 and dossier.name in sortie and "Répétition sans robot" in sortie and "rapport prêt" in sortie
    (liste,) = json.loads(g1_seance("liste", "--json")[1])
    assert liste["id"] == dossier.name and liste["rapport"] == "pret" and liste["actions"] == 8
    code, sortie = g1_seance("exporter", dossier.name, "--sortie", tmp_path / "s.zip")
    assert code == 0 and "Séance exportée" in sortie
    noms = zipfile.ZipFile(tmp_path / "s.zip").namelist()
    for nom in ("seance.json", "actions.jsonl", "rapport.html", "rapport.md", "rapport.json", "trajets.png",
                "bag/metadata.yaml", "bag/bag_0.db3", "lieu/salles.yaml"):
        assert f"{dossier.name}/{nom}" in noms, nom
    code, _ = g1_seance("exporter", "derniere", "--sortie", tmp_path / "petit.zip", "--sans-bag")
    assert code == 0 and not any("/bag/" in n for n in zipfile.ZipFile(tmp_path / "petit.zip").namelist())
    # sans --sortie : seance_<id>.zip dans le dossier courant
    code, _ = g1_seance("exporter", dossier.name, env={"CWD_ESSAI": str(tmp_path)})
    assert code == 0 and (tmp_path / f"seance_{dossier.name}.zip").is_file()


def test_seance_inconnue_et_sans_atelier(seances):
    code, sortie = g1_seance("rapport", "2026-01-01_00h00")
    assert code == 1 and "séance introuvable" in sortie
    code, sortie = g1_seance("exporter", "derniere")
    assert code == 1 and "aucune séance" in sortie
    api = f"http://127.0.0.1:{_port_libre()}"
    for commande in ("demarrer", "arreter", "etat"):
        code, sortie = g1_seance(commande, "--api", api)
        assert code == 1 and "L'Atelier ne répond pas" in sortie and "g1-atelier" in sortie, (commande, sortie)


def test_contre_un_atelier(seances, tmp_path):
    from atelier.lieu import copier_lieu
    copier_lieu(DEMO, tmp_path / "lieux" / "demo")
    port = _port_libre()
    env = dict(os.environ, ATELIER_LIEUX=str(tmp_path / "lieux"), ATELIER_ROS="0", ATELIER_PORT=str(port),
               PYTHONPATH=str(atelier.RACINE))
    serveur = subprocess.Popen([str(atelier.RACINE / ".venv-projet" / "bin" / "python"), "-m", "uvicorn",
                                "atelier.serveur.main:app", "--port", str(port), "--log-level", "warning"],
                               cwd=str(atelier.RACINE), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               start_new_session=True)
    try:
        api = f"http://127.0.0.1:{port}"
        fin = time.monotonic() + 30
        while g1_seance("etat", "--api", api)[0] != 0 and time.monotonic() < fin:
            time.sleep(0.3)
        code, sortie = g1_seance("etat", "--api", api)
        assert code == 0 and "Séance ouverte : aucune" in sortie
        code, sortie = g1_seance("demarrer", "--mode", "repetition", "--lieu", "demo", "--api", api)
        assert code == 0 and "Séance ouverte" in sortie, sortie
        (ident,) = [d.name for d in seances.iterdir()]
        assert M.lire_manifeste(seances / ident)["ouverture"] == "g1-seance"
        code, sortie = g1_seance("demarrer", "--mode", "simu", "--api", api)
        assert code == 2                                            # « simu » n'est pas un choix de la commande
        code, sortie = g1_seance("arreter", "--api", api)
        assert code == 0 and "Séance terminée" in sortie
        m = M.lire_manifeste(seances / ident)
        assert m["fermeture"] == "g1-seance" and m["etat"] == "fermee"
        lignes = [json.loads(x) for x in (seances / ident / "actions.jsonl").read_text(encoding="utf-8").splitlines()]
        assert lignes[0]["source"] == "g1-seance" and lignes[-1]["texte"] == "Terminer la séance"
        code, sortie = g1_seance("arreter", "--api", api)
        assert code == 1 and "Aucune séance ouverte" in sortie
    finally:
        os.killpg(serveur.pid, 15)
        serveur.wait(timeout=20)


@pytest.mark.skipif(not C.ros_disponible(), reason="ROS 2 non chargé")
def test_enregistrer_sans_place(tmp_path):
    code, sortie = g1_seance("enregistrer", "--dossier", tmp_path / "s", "--place-min-go", "1000000")
    assert code == 0 and "Enregistrement arrêté" in sortie
    assert json.loads((tmp_path / "s" / "enregistrement.json").read_text())["etat"] == "coupe"
