"""Tests de la commande g1-monde (generer, simuler) sur une copie de lieux/demo.

simuler n'est testé qu'avec --afficher : le lancement g1_sim est écrit par l'agent Simulation.
"""
import os
import subprocess

import pytest

import atelier
from atelier import lieu as L

DEMO = atelier.RACINE / "lieux" / "demo"
BIN = atelier.RACINE / "bin"


def g1_monde(*args, nom="g1-monde", env=None):
    return subprocess.run([str(BIN / nom), *map(str, args)], capture_output=True, text=True, timeout=60,
                          env=env)


@pytest.fixture
def copie(tmp_path):
    return L.copier_lieu(DEMO, tmp_path / "demo")


def test_alias_gl_monde():
    assert os.path.islink(BIN / "gl-monde") and os.readlink(BIN / "gl-monde") == "g1-monde"
    assert os.access(BIN / "g1-monde", os.X_OK)


def test_generer(copie):
    for nom in ("rdc.sdf", "pieton.dae"):
        (copie / "mondes" / nom).unlink(missing_ok=True)
    resultat = g1_monde("generer", "--lieu", copie, "--etage", "rdc")
    assert resultat.returncode == 0, resultat.stdout + resultat.stderr
    for chemin in ("mondes/rdc.sdf", "mondes/pieton.dae", "cartes/rdc.pgm", "cartes/rdc.yaml",
                   "cartes/rdc_interdit.pgm", "cartes/rdc_interdit.yaml"):
        assert (copie / chemin).is_file(), chemin
    assert "18 murs, 12 objets, 2 piétons" in resultat.stdout
    assert "602 × 402 pixels de 0,05 m" in resultat.stdout
    assert "g1-monde simuler --lieu" in resultat.stdout
    assert L.valider_lieu(copie).erreurs == []


def test_generer_par_id_avec_atelier_lieux(copie):
    env = dict(os.environ, ATELIER_LIEUX=str(copie.parent))
    resultat = g1_monde("generer", "--lieu", "demo", "--etage", "rdc", nom="gl-monde", env=env)
    assert resultat.returncode == 0, resultat.stdout + resultat.stderr
    assert str(copie) in resultat.stdout
    assert (copie / "cartes" / "rdc.pgm").is_file()


def test_generer_etage_inconnu(copie):
    resultat = g1_monde("generer", "--lieu", copie, "--etage", "etage9")
    assert resultat.returncode == 1
    assert "pas d'étage « etage9 » (étages du lieu : rdc)" in resultat.stdout


def test_generer_lieu_inconnu(tmp_path):
    resultat = g1_monde("generer", "--lieu", tmp_path / "nulle_part", "--etage", "rdc")
    assert resultat.returncode == 1
    assert "n'existe pas" in resultat.stdout and "g1-lieu creer" in resultat.stdout


def test_generer_monde_invalide(copie):
    chemin = L.chemin_monde(copie, "rdc")
    chemin.write_text(chemin.read_text().replace("vitesse: 0.8", "vitesse: -0.8"))
    resultat = g1_monde("generer", "--lieu", copie, "--etage", "rdc")
    assert resultat.returncode == 1
    assert "Rien n'a été généré" in resultat.stdout and "rdc.monde.yaml" in resultat.stdout


def test_commande_mal_tapee():
    resultat = g1_monde("generer", "--lieu", "demo")
    assert resultat.returncode == 2
    assert "il manque : --etage" in resultat.stderr


def test_simuler_sans_sdf_propose_generer(copie):
    (copie / "mondes" / "rdc.sdf").unlink(missing_ok=True)
    resultat = g1_monde("simuler", "--lieu", copie, "--etage", "rdc", "--afficher")
    assert resultat.returncode == 1
    assert f"g1-monde generer --lieu {copie} --etage rdc" in resultat.stdout


def test_simuler_traduit_les_options(copie):
    assert g1_monde("generer", "--lieu", copie, "--etage", "rdc").returncode == 0
    resultat = g1_monde("simuler", "--lieu", copie, "--etage", "rdc", "--sans-fenetre", "--afficher")
    assert resultat.returncode == 0, resultat.stdout + resultat.stderr
    assert resultat.stdout.strip().splitlines()[-1] == (
        f"ros2 launch g1_sim simulation.launch.py lieu:={copie} etage:=rdc sans_fenetre:=true")
    resultat = g1_monde("simuler", "--lieu", copie, "--etage", "rdc", "--afficher")
    assert resultat.stdout.strip().endswith("sans_fenetre:=false")
    # vague 4 (section 11.3) : piétons crédibles (défaut de g1_sim) ou <actor> de la vague 1
    resultat = g1_monde("simuler", "--lieu", copie, "--etage", "rdc", "--pietons", "acteurs", "--afficher")
    assert resultat.stdout.strip().endswith("sans_fenetre:=false pietons:=acteurs")
    assert g1_monde("simuler", "--lieu", copie, "--etage", "rdc", "--pietons", "fantomes").returncode == 2


@pytest.mark.skipif(not os.path.isdir("/opt/ros/humble"), reason="ROS 2 Humble absent")
def test_simuler_sans_paquet_g1_sim(copie):
    """ROS 2 chargé, mais sans le paquet g1_sim (seul /opt/ros/humble) : message, pas de lancement."""
    assert g1_monde("generer", "--lieu", copie, "--etage", "rdc").returncode == 0
    env = dict(os.environ, ROS_DISTRO="humble", AMENT_PREFIX_PATH="/opt/ros/humble",
               PATH="/opt/ros/humble/bin:" + os.environ.get("PATH", ""),
               PYTHONPATH=":".join(["/opt/ros/humble/lib/python3.10/site-packages",
                                    "/opt/ros/humble/local/lib/python3.10/dist-packages"]))
    resultat = g1_monde("simuler", "--lieu", copie, "--etage", "rdc", "--sans-fenetre", env=env)
    assert resultat.returncode == 1, resultat.stdout + resultat.stderr
    assert "le paquet ROS 2 g1_sim est introuvable" in resultat.stdout


def test_simuler_avertit_si_le_monde_a_change(copie):
    assert g1_monde("generer", "--lieu", copie, "--etage", "rdc").returncode == 0
    # Le monde est modifié une minute après la génération
    plus_tard = L.chemin_sdf(copie, "rdc").stat().st_mtime + 60
    os.utime(L.chemin_monde(copie, "rdc"), (plus_tard, plus_tard))
    resultat = g1_monde("simuler", "--lieu", copie, "--etage", "rdc", "--afficher")
    assert resultat.returncode == 0
    assert "a changé depuis la dernière génération" in resultat.stdout
