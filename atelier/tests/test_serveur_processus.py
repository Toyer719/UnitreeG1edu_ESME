"""Tests des processus lancés par le serveur (processus.py) et de la position des piétons (pietons.py)."""
import math
import sys
import time

import pytest

from atelier.lieu import Pieton
from atelier.serveur import pietons
from atelier.serveur.processus import (CommandeAbsente, Gestionnaire, Processus, commande, lancer_et_attendre,
                                      noeud_plante)

from .test_serveur_communs import attendre, journaux, processus_vivant  # noqa: F401

# Commande longue qui lance un enfant qui ignore Ctrl+C : seul SIGTERM l'arrête
TETU = r'''#!{python}
import os, signal, subprocess, sys, time
enfant = subprocess.Popen([sys.executable, "-c",
    "import signal, time; signal.signal(signal.SIGINT, signal.SIG_IGN); print('enfant prêt', flush=True); time.sleep(300)"])
print(f"pids {{os.getpid()}} {{enfant.pid}}", flush=True)
time.sleep(300)
'''


@pytest.fixture
def bin_test(tmp_path, monkeypatch):
    dossier = tmp_path / "bin"
    dossier.mkdir()
    monkeypatch.setenv("ATELIER_BIN", str(dossier))

    def ecrire(nom, texte):
        chemin = dossier / nom
        chemin.write_text(texte.format(python=sys.executable))
        chemin.chmod(0o755)
        return chemin
    ecrire("g1-tetu", TETU)
    ecrire("g1-court", "#!/bin/sh\necho \"bonjour $*\"\nexit 4\n")
    ecrire("g1-lent", "#!/bin/sh\necho debut\nsleep 30\n")
    (dossier / "g1-pas-executable").write_text("#!/bin/sh\n")
    return dossier


def test_commande_cherchee_dans_atelier_bin(bin_test):
    assert commande("g1-court") == bin_test / "g1-court"
    assert commande("g1-inconnue") is None
    assert commande("g1-pas-executable") is None
    with pytest.raises(CommandeAbsente, match="g1-inconnue"):
        lancer_et_attendre("g1-inconnue", [])


def test_commande_courte(bin_test):
    r = lancer_et_attendre("g1-court", ["a", "b"])
    assert r["code"] == 4 and r["sortie"].strip() == "bonjour a b"


def test_commande_courte_trop_longue_arretee(bin_test):
    debut = time.monotonic()
    r = lancer_et_attendre("g1-lent", [], delai=0.5)
    assert r["code"] is None and "arrêtée par l'Atelier" in r["sortie"] and "debut" in r["sortie"]
    assert time.monotonic() - debut < 5


def test_arret_du_groupe_entier_meme_un_enfant_tetu(bin_test, journaux):
    p = Processus("g1-tetu", ["--x"], journaux / "tetu.log", {"lieu": "demo"}).demarrer()
    assert attendre(lambda: any(l.startswith("pids") for l in p.etat()["dernieres_lignes"]))
    assert attendre(lambda: "enfant prêt" in p.etat()["dernieres_lignes"])
    pids = [int(x) for x in next(l for l in p.etat()["dernieres_lignes"] if l.startswith("pids")).split()[1:]]
    e = p.etat()
    assert e["en_cours"] and e["lieu"] == "demo" and e["commande"].endswith("g1-tetu --x")
    debut = time.monotonic()
    p.arreter(attente_sigint=0.5)        # SIGINT ignoré par l'enfant : SIGTERM ensuite
    assert time.monotonic() - debut < 5
    assert not p.en_cours
    assert attendre(lambda: not any(processus_vivant(x) for x in pids), 3)
    journal = (journaux / "tetu.log").read_text()
    assert "g1-tetu --x" in journal and "enfant prêt" in journal and "=== fin, code" in journal


def test_gestionnaire(bin_test, journaux):
    g = Gestionnaire()
    p1 = g.lancer("simulation", "g1-lent", [], {"lieu": "demo"})
    p2 = g.lancer("navigation", "g1-lent", [])
    assert g.en_cours("simulation") and g.en_cours("navigation")
    assert set(g.etat()) == {"simulation", "navigation"}
    assert len(list(journaux.glob("atelier_simulation_*.log"))) == 1
    # relancer un rôle arrête la commande précédente de ce rôle
    p3 = g.lancer("simulation", "g1-lent", [])
    assert not p1.en_cours and p3.en_cours
    g.arreter_tout(attente_sigint=2.0)
    assert not any(x.en_cours for x in (p1, p2, p3))
    assert g.etat()["simulation"]["arret_demande"]
    with pytest.raises(CommandeAbsente):
        g.lancer("scan", "g1-inconnue", [])


def test_commande_qui_finit_seule(bin_test, journaux):
    g = Gestionnaire()
    p = g.lancer("essai", "g1-court", ["x"])
    assert attendre(lambda: not p.en_cours)
    attendre(lambda: p.fin is not None)
    e = g.etat()["essai"]
    assert e["code"] == 4 and not e["arret_demande"] and e["dernieres_lignes"] == ["bonjour x"]
    g.arreter_tout()          # sans effet sur une commande finie


# Revue de la vague 5 : une répétition annoncée lancée alors que des nœuds de Nav2 avaient planté
PLANTE = r'''#!/bin/sh
echo "[INFO] [launch]: All log files can be found below /tmp"
echo "[ERROR] [bt_navigator-5]: process has died [pid 4123, exit code -6, cmd 'bt_navigator --ros-args']."
echo "[ERROR] [map_server-2]: process has died [pid 4124, exit code 1, cmd 'map_server']."
echo "[ERROR] [bt_navigator-5]: process has died [pid 4125, exit code -6, cmd 'bt_navigator']."
sleep 30
'''


def test_noeud_plante():
    assert noeud_plante("[ERROR] [bt_navigator-5]: process has died [pid 1, exit code -6, cmd 'x'].") == "bt_navigator"
    assert noeud_plante("[ERROR] [component_container_isolated-1]: process has died [pid 2]") == \
        "component_container_isolated"
    assert noeud_plante("[INFO] [bt_navigator-5]: process started with pid [4123]") is None
    assert noeud_plante("[ERROR] [guide]: lieu introuvable") is None


def test_noeuds_plantes_dans_l_etat(bin_test, journaux):
    """Les nœuds que ros2 launch dit plantés sont dans l'état (une fois chacun), la commande tournant encore ;
    ceux qui s'arrêtent après la demande d'arrêt ne comptent pas."""
    (bin_test / "g1-plante").write_text(PLANTE)
    (bin_test / "g1-plante").chmod(0o755)
    g = Gestionnaire()
    p = g.lancer("navigation", "g1-plante", [])
    assert attendre(lambda: len(p.etat()["plantages"]) == 2)
    e = g.etat()["navigation"]
    assert e["en_cours"] and e["plantages"] == ["bt_navigator", "map_server"]
    g.arreter_tout(attente_sigint=1.0)
    assert g.etat()["navigation"]["plantages"] == ["bt_navigator", "map_server"]
    q = Processus("g1-court", [], journaux / "court.log").demarrer()
    assert attendre(lambda: not q.en_cours)
    assert q.etat()["plantages"] == []


# ---------------------------------------------------------------- piétons

def test_pieton_aller_retour():
    p = Pieton("h1", [(0.0, 0.0), (10.0, 0.0)], vitesse=2.0, aller_retour=True)
    for calcul in (pietons.position_simple, pietons.position_pieton):
        assert calcul(p, 0.0)[:2] == pytest.approx((0.0, 0.0))
        assert calcul(p, 2.5)[:2] == pytest.approx((5.0, 0.0))
        x, y, theta = calcul(p, 7.5)          # au retour : 15 m parcourus
        assert (x, y) == pytest.approx((5.0, 0.0)) and abs(abs(theta) - math.pi) < 1e-6
        assert calcul(p, 10.0 + 1.0)[:2] == pytest.approx((2.0, 0.0))     # un tour = 10 s


def test_pieton_boucle():
    p = Pieton("h2", [(0.0, 0.0), (4.0, 0.0), (4.0, 3.0)], vitesse=1.0, aller_retour=False)
    for calcul in (pietons.position_simple, pietons.position_pieton):
        assert calcul(p, 5.0)[:2] == pytest.approx((4.0, 1.0))
        x, y, theta = calcul(p, 9.5)          # retour direct (3-4-5) : à mi-chemin du dernier côté
        assert (x, y) == pytest.approx((2.0, 1.5))
        assert theta == pytest.approx(math.atan2(-3, -4))


def test_calcul_de_l_agent_monde_et_calcul_simple_d_accord():
    """L'écran doit montrer les piétons où Gazebo les met : les deux calculs concordent."""
    if pietons._position_monde is None:
        pytest.skip("atelier.monde.pietons pas encore livré (agent Monde)")
    p = Pieton("h3", [(1.0, 1.0), (7.0, 1.0), (7.0, 5.0)], vitesse=0.8, aller_retour=True)
    for t in [0.0, 0.7, 3.3, 9.9, 12.5, 20.0, 31.4]:
        assert pietons.position_pieton(p, t)[:2] == pytest.approx(pietons.position_simple(p, t)[:2], abs=1e-6)


def test_positions_pietons_du_monde():
    class Monde:
        pietons = [Pieton("a", [(0, 0), (1, 0)], 1.0, True), Pieton("b", [(5, 5), (5, 6)], 0.5, False)]
    liste = pietons.positions_pietons(Monde(), 0.5)
    assert [p["id"] for p in liste] == ["a", "b"]
    assert (liste[0]["x"], liste[0]["y"]) == (0.5, 0.0)
    assert pietons.positions_pietons(None, 1.0) == [] and pietons.positions_pietons(Monde(), None) == []
