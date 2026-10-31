"""Tests des sessions de scan intégré (atelier.lieu.scans, sections 9 et 12.5 du plan) : session.json,
état du scan, fichiers présents, rangement des résultats d'avant (--refaire) et exemples pour les tests.

  ~/robot-g1/.venv-projet/bin/python -m pytest ~/robot-g1/atelier/tests/test_lieu_scans.py -v

Les tests travaillent sur une copie de lieux/demo dans un dossier temporaire.
"""
import json
import multiprocessing
import subprocess
import sys
from datetime import datetime, timedelta

import pytest

import atelier
from atelier import lieu as L
from atelier.lieu import ErreurLieu
from atelier.tests.outils_scan import creer_session_exemple

DEMO = atelier.RACINE / "lieux" / "demo"
QUAND = datetime(2026, 10, 25, 17, 42, 5)


@pytest.fixture
def demo(tmp_path):
    return L.copier_lieu(DEMO, tmp_path / "demo")


# ---------------------------------------------------------------- création d'une session

def test_creer_session_simu(demo):
    s = L.creer_session(demo, "rdc", "simu", explorer=True, quand=QUAND)
    assert s["id"] == "2026-10-25_17h42"
    assert (demo / "scans" / s["id"] / "session.json").is_file()
    assert (s["etat"], s["etape"], s["progression"], s["fin"]) == ("en_cours", "preparation", 0, None)
    assert s["sujets"] == {"nuage": "/points", "odom": "/odom", "autres": ["/tf_static"]}
    assert s["nom"] == "Scan rdc du 25/10/2026 à 17h42" and s["lieu"] == "demo"
    assert s["carte_unitree"] is None and s["processus"] is None
    assert s["debut"].startswith("2026-10-25T17:42:05") and L.lire_session(demo, s["id"]) == s


def test_creer_session_robot_et_repetition(demo):
    s = L.creer_session(demo, "rdc", "robot", nom="Premier vrai scan", quand=QUAND)
    assert s["sujets"]["nuage"] == "/unitree/slam_mapping/points"
    assert s["sujets"]["odom"] == "/unitree/slam_mapping/odom"
    assert s["carte_unitree"] == "rdc_2026-10-25_17h42.pcd" and s["nom"] == "Premier vrai scan"
    L.maj_session(demo, s["id"], etat="echec", etape="enregistrement", message="essai")
    r = L.creer_session(demo, "rdc", "robot", repetition=True, explorer=True, quand=QUAND)
    assert r["id"] == "2026-10-25_17h42-2" and r["repetition"] and r["explorer"]


@pytest.mark.parametrize("arguments, message", [
    (("rdc", "drone"), "mode de scan « drone » inconnu"),
    (("etage9", "simu"), "pas d'étage « etage9 »"),
])
def test_creer_session_refuse(demo, arguments, message):
    with pytest.raises(ErreurLieu, match=message):
        L.creer_session(demo, *arguments)
    assert not (demo / "scans").exists() or not any((demo / "scans").iterdir())


def test_creer_session_options_incompatibles(demo):
    with pytest.raises(ErreurLieu, match="qu'en mode robot"):
        L.creer_session(demo, "rdc", "simu", repetition=True)
    with pytest.raises(ErreurLieu, match="télécommande"):
        L.creer_session(demo, "rdc", "robot", explorer=True)


def test_un_seul_scan_actif_par_lieu(demo):
    s = L.creer_session(demo, "rdc", "simu")
    L.maj_session(demo, s["id"], processus=L.infos_processus())
    with pytest.raises(ErreurLieu, match="un scan est déjà en cours.*g1-scan arreter"):
        L.creer_session(demo, "rdc", "simu")
    L.maj_session(demo, s["id"], etat="echec", message="arrêté pour le test")
    assert L.creer_session(demo, "rdc", "simu")["etat"] == "en_cours"


def test_un_scan_interrompu_ne_bloque_pas(demo):
    s = L.creer_session(demo, "rdc", "simu")
    L.maj_session(demo, s["id"], processus=_processus_fini())
    assert L.session_interrompue(L.lire_session(demo, s["id"]))
    assert L.session_active(demo) is None
    L.creer_session(demo, "rdc", "simu")


def test_suffixes_de_la_meme_minute(demo):
    ids = [L.creer_session(demo, "rdc", "simu", quand=QUAND, refuser_si_active=False)["id"] for _ in range(11)]
    assert ids[:3] == ["2026-10-25_17h42", "2026-10-25_17h42-2", "2026-10-25_17h42-3"]
    assert ids[-1] == "2026-10-25_17h42-11"
    assert [s["id"] for s in L.lister_sessions(demo)] == list(reversed(ids))     # 17h42-11 en premier


# ---------------------------------------------------------------- lecture, écriture, verrou

def test_identifiants_de_session_refuses(demo):
    for mauvais in ("../demo", "2026-10-25", "x", "2026-10-25_17h42/../../lieu.yaml"):
        with pytest.raises(ErreurLieu, match="AAAA-MM-JJ_HHhMM"):
            L.dossier_session(demo, mauvais)


def test_lire_session_absente_ou_abimee(demo):
    with pytest.raises(ErreurLieu, match="n'existe pas"):
        L.lire_session(demo, "2026-10-25_17h42")
    s = L.creer_session(demo, "rdc", "simu")
    chemin = L.chemin_session(demo, s["id"])
    chemin.write_text("{pas du json", encoding="utf-8")
    with pytest.raises(ErreurLieu, match="JSON illisible"):
        L.lire_session(demo, s["id"])
    chemin.write_text(json.dumps(dict(s, progression=150)), encoding="utf-8")
    with pytest.raises(ErreurLieu, match=r"scans/.*/session.json : progression vaut 150 : il faut au plus 100"):
        L.lire_session(demo, s["id"])


def test_ecriture_atomique_et_validee(demo):
    s = L.creer_session(demo, "rdc", "simu")
    avant = L.chemin_session(demo, s["id"]).read_text(encoding="utf-8")
    with pytest.raises(ErreurLieu):
        L.maj_session(demo, s["id"], etat="termine")          # progression 0, pas d'heure de fin
    assert L.chemin_session(demo, s["id"]).read_text(encoding="utf-8") == avant
    assert not list(L.dossier_session(demo, s["id"]).glob("*.tmp"))


def test_maj_session(demo):
    s = L.creer_session(demo, "rdc", "simu")
    s = L.maj_session(demo, s["id"], etape="enregistrement", statistiques={"points": 1000})
    assert s["statistiques"] == {"duree_s": 0.0, "points": 1000, "distance_m": 0.0, "nuages": 0}
    s = L.maj_session(demo, s["id"], statistiques={"distance_m": 3.5, "duree_s": 12.0})
    assert s["statistiques"]["points"] == 1000 and s["statistiques"]["distance_m"] == 3.5
    s = L.maj_session(demo, s["id"], etat="traitement", etape="carte_3d", fin=L.scans.instant())
    assert s["progression"] == 10                            # début de l'étape carte_3d
    s = L.maj_session(demo, s["id"], etape="carte_2d", progression=L.progression_etape("carte_2d", 0.5))
    assert s["progression"] == 78                            # carte_2d : de 70 à 85 (vague 5)


def _incrementer(dossier, session):
    with L.verrou_session(dossier, session):
        s = L.lire_session(dossier, session)
        s["statistiques"]["points"] += 1
        L.ecrire_session(dossier, s)


def _travailleur(dossier, session, n):
    for _ in range(n):
        _incrementer(dossier, session)


def test_verrou_entre_processus(demo):
    """Quatre processus qui lisent-modifient-écrivent en même temps ne perdent aucune mise à jour."""
    s = L.creer_session(demo, "rdc", "simu")
    contexte = multiprocessing.get_context("spawn")
    travailleurs = [contexte.Process(target=_travailleur, args=(str(demo), s["id"], 25)) for _ in range(4)]
    for t in travailleurs:
        t.start()
    for t in travailleurs:
        t.join(60)
        assert t.exitcode == 0
    assert L.lire_session(demo, s["id"])["statistiques"]["points"] == 100


def test_progression_etape():
    assert [L.progression_etape(e) for e in L.ETAPES] == [0, 0, 5, 10, 70, 85, 100]
    assert L.progression_etape("carte_3d", 1.0) == 70 and L.progression_etape("carte_2d", 0.5) == 78
    assert L.progression_etape("nuage", 2.0) == 99
    assert L.progression_etape("reconnaissance") == 85          # étape d'une session d'avant la vague 5
    with pytest.raises(ValueError):
        L.progression_etape("lavage")


# ---------------------------------------------------------------- processus et interruption

def _processus_fini():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    infos = L.infos_processus(p.pid)
    p.wait()
    return infos


def test_processus_vivant(demo):
    s = L.creer_session(demo, "rdc", "simu")
    assert L.processus_vivant(s) is None
    s = L.maj_session(demo, s["id"], processus=L.infos_processus())
    assert L.processus_vivant(s) is True and not L.session_interrompue(s)
    s = L.maj_session(demo, s["id"], processus=_processus_fini())
    assert L.processus_vivant(s) is False and L.session_interrompue(s)
    ailleurs = dict(s["processus"], hote="autre-machine")
    assert L.processus_vivant(dict(s, processus=ailleurs)) is None


def test_pid_repris_par_un_autre_processus(demo):
    s = L.creer_session(demo, "rdc", "simu")
    infos = L.infos_processus()
    s = L.maj_session(demo, s["id"], processus=dict(infos, debut=infos["debut"] + 1))
    assert L.processus_vivant(s) is False


def test_session_muette_interrompue(demo):
    s = L.creer_session(demo, "rdc", "simu")
    assert not L.session_interrompue(s)                       # vient d'être écrite
    vieille = (datetime.now() - timedelta(seconds=L.scans.SILENCE_MAX + 5)).astimezone()
    assert L.session_interrompue(dict(s, maj=vieille.replace(microsecond=0).isoformat()))
    assert not L.session_interrompue(dict(s, etat="echec", maj="2020-01-01T00:00:00+01:00"))


# ---------------------------------------------------------------- état du scan (g1-scan etat --json, GET /api/scan/etat)

CLES_ETAT = {"version", "lieu", "dossier_lieu", "sessions", "actif", "session"}


def test_etat_sans_session(demo):
    e = L.etat_scan(demo)
    assert set(e) == CLES_ETAT
    assert (e["lieu"], e["sessions"], e["actif"], e["session"]) == ("demo", 0, False, None)
    json.dumps(e)


def test_etat_choisit_la_session_active(demo):
    vieille = creer_session_exemple(demo, "termine")
    active = creer_session_exemple(demo, "en_cours")
    creer_session_exemple(demo, "echec")                     # la plus récente, mais pas active
    e = L.etat_scan(demo)
    assert e["actif"] and e["sessions"] == 3 and e["session"]["id"] == active["id"]
    s = e["session"]
    assert s["vivant"] is True and s["interrompue"] is False and s["dossier"] == active["dossier"]
    assert s["fichiers"] == {"enregistrement": False, "apercu_png": True, "apercu_json": True, "apercu_nuage": True,
                             "nuage": False, "carte": False, "nuage_affichage": False, "rapport": False}
    e = L.etat_scan(demo, vieille["id"])
    assert not e["actif"] and all(v for k, v in e["session"]["fichiers"].items() if k != "enregistrement")
    json.dumps(e)


def test_etat_sinon_la_plus_recente(demo):
    creer_session_exemple(demo, "termine")
    derniere = creer_session_exemple(demo, "echec")
    assert L.etat_scan(demo)["session"]["id"] == derniere["id"]


def test_etat_erreurs(demo, tmp_path):
    with pytest.raises(ErreurLieu, match="n'existe pas"):
        L.etat_scan(demo, "2030-01-01_00h00")
    with pytest.raises(ErreurLieu, match="pas de lieu.yaml"):
        L.etat_scan(tmp_path / "rien")


def test_sessions_illisibles(demo):
    bonne = creer_session_exemple(demo, "termine")
    (demo / "scans" / "2030-01-01_00h00").mkdir()
    (demo / "scans" / "pas-une-session").mkdir()
    assert [s["id"] for s in L.lister_sessions(demo)] == [bonne["id"]]
    toutes = L.lister_sessions(demo, avec_illisibles=True)
    assert toutes[0]["id"] == "2030-01-01_00h00" and toutes[0]["illisible"] and toutes[0]["erreurs"]
    assert len(toutes) == 2


# ---------------------------------------------------------------- g1-scan traiter --refaire : rien n'est effacé

def test_ranger_resultats(demo):
    s = creer_session_exemple(demo, "termine")
    d = L.dossier_session(demo, s["id"])
    (d / "reconnaissance.yaml").write_text("ancienne reconnaissance\n")      # session d'avant la vague 5
    avant = {nom: (d / nom).read_bytes() for nom in L.scans.RESULTATS_TRAITEMENT if (d / nom).is_file()}
    assert {"nuage.pcd", "carte.yaml", "carte.pgm", "nuage_affichage.bin", "nuage_affichage.json", "rapport.json",
            "reconnaissance.yaml"} == set(avant)
    quand = datetime(2026, 10, 31, 3, 10)
    ancien = L.ranger_resultats(demo, s["id"], quand)
    assert ancien == d / "ancien_2026-10-31_03h10"
    assert {f.name: f.read_bytes() for f in ancien.iterdir()} == avant          # déplacés, à l'identique
    assert not any((d / nom).exists() for nom in avant)
    assert (d / "session.json").is_file() and (d / "apercu.json").is_file()     # le reste ne bouge pas
    assert L.ranger_resultats(demo, s["id"], quand) is None                     # plus rien à ranger
    (d / "carte.yaml").write_text("x")
    assert L.ranger_resultats(demo, s["id"], quand).name == "ancien_2026-10-31_03h10-2"   # même minute
    assert [x.name for x in L.anciens_resultats(demo, s["id"])] == ["ancien_2026-10-31_03h10",
                                                                     "ancien_2026-10-31_03h10-2"]
    assert L.fichiers_presents(demo, s["id"])["carte"] is False


# ---------------------------------------------------------------- sessions d'exemple (pour les autres agents)

@pytest.mark.parametrize("etat", ["en_cours", "traitement", "termine", "echec"])
def test_sessions_d_exemple_conformes(demo, etat):
    s = creer_session_exemple(demo, etat)
    relue = L.lire_session(demo, s["id"])
    assert relue["etat"] == etat
    d = L.dossier_session(demo, s["id"])
    apercu = json.loads((d / "apercu.json").read_text(encoding="utf-8"))
    assert len(apercu["points"]) <= L.APERCU_POINTS_MAX and apercu["trajectoire"]
    assert (d / "apercu.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    points, entete = L.lire_nuage(L.chemin_nuage_session(d, apercu=True))
    assert entete["source"] == "apercu" and len(points) == entete["points"] > 100
    if etat in ("traitement", "termine"):
        info, image = L.charger_carte(d / "carte.yaml")
        assert info.image == "carte.pgm" and image.shape == (402, 602)
    if etat == "termine":
        points, entete = L.lire_nuage(L.chemin_nuage_session(d))
        assert entete["source"] == "scan" and entete["session"] == s["id"] and entete["grille"] == 0.05
        rapport = json.loads((d / "rapport.json").read_text(encoding="utf-8"))
        assert [e["etape"] for e in rapport["etapes"]] == list(L.ETAPES_TRAITEMENT)
        assert rapport["nuages"]["ignores"] == 0 and "reconnaissance" not in rapport
        assert not (d / "reconnaissance.yaml").exists() and not (d / "monde_scan.monde.yaml").exists()
