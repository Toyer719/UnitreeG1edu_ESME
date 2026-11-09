"""Le rapport de séance (vague 6, section 13.3 du plan) : agent Boîte noire.

La séance d'essai de test_seance_communs écrite dans un vrai bag (rosbag2_py, sqlite3), puis g1-seance rapport :
rapport.json, rapport.md, rapport.html (l'image dedans) et trajets.png ; le manifeste dit « pret » ; le bag d'un
Atelier qui a planté (sans metadata.yaml) est réindexé ; une séance sans bag a quand même son rapport ; toutes les
données insérées dans le HTML sont échappées ; la mise en forme en français.
"""
import json
import re
import time

import pytest

from atelier.lieu import valider_donnees
from atelier.seance import manifeste as M
from atelier.seance import rapport as R
from atelier.seance.lecture import charger, infos_bag, lire_messages, reindexer
from . import test_seance_communs as C
from .test_serveur_communs import DEMO

pytestmark = pytest.mark.skipif(not C.ros_disponible(), reason="ROS 2 (rclpy, rosbag2_py, unitree_api) non chargé")

T0 = time.time() - 3600.0


@pytest.fixture
def seance(tmp_path):
    return C.seance_essai(tmp_path, T0, demo=DEMO)


def test_lecture_du_bag(seance):
    bag = seance / "bag"
    infos = infos_bag(bag)
    assert infos["metadata"] and infos["messages"] > 3000
    assert infos["sujets"]["/guide/etat"]["type"] == "std_msgs/msg/String"
    assert infos["sujets"]["/g1_jumeau/odom"]["nombre"] == 1701
    d = charger(bag)
    assert d.erreur is None and d.illisibles == 0
    assert len(d.serie("json", "/guide/etat")) == 851 and d.batterie[0] == (pytest.approx(T0, abs=1e-3), 87)
    verrous = [(pytest.approx(T0 + t, abs=1e-3), v) for t, v in ((0.3, False), (85.05, True), (95.2, False))]
    assert d.serie("booleens", "/pont/arret") == verrous
    assert [x[1] for x in d.journal] == [40]          # seulement l'erreur (l'INFO est comptée, pas gardée)
    assert d.niveaux == {40: 1, 20: 1}
    temps = [t for _, _, t, _ in lire_messages(bag)]
    assert temps == sorted(temps)
    assert list(lire_messages(bag, {"/lf/bmsstate"}))[0][0] == "/lf/bmsstate"


def test_rapport_complet(seance):
    r = R.faire_rapport(seance)
    for nom in R.FICHIERS_RAPPORT:
        assert (seance / nom).is_file(), nom
    m = M.lire_manifeste(seance)
    assert m["rapport"]["etat"] == "pret" and set(m["rapport"]["fichiers"]) == set(R.FICHIERS_RAPPORT)
    assert valider_donnees("seance", m) == []
    sur_disque = json.loads((seance / "rapport.json").read_text(encoding="utf-8"))
    assert sur_disque["seance"] == m["id"] and sur_disque == json.loads(json.dumps(r))
    # le critère 38 : au moins deux trajets (arrivé, interrompu par l'ARRÊT), une distance non nulle, un arrêt
    # d'urgence, la batterie de début et de fin, l'anomalie « mouvement sans demande »
    assert [t["resultat"] for t in r["trajets"]] == ["arrive", "interrompu", "arrive"]
    assert r["trajets"][1]["cause"].startswith("ARRÊT")
    assert r["trajets"][0]["distance_m"] == pytest.approx(C.DISTANCE_B204, abs=0.3)
    assert any(a["genre"] == "arret_urgence" for a in r["anomalies"])
    assert any(a["genre"] == "mouvement_sans_demande" for a in r["anomalies"])
    assert r["batterie"] == {"debut": 87, "fin": 85}
    assert r["nom_lieu"] == "Lycée démo" and r["trajets"][0]["nom"] == "Salle B204"
    assert "rapport.html" in r["fichiers"] and "bag/metadata.yaml" in r["fichiers"]
    assert r["duree_rapport_s"] < 20
    png = (seance / "trajets.png").read_bytes()
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 20000


def test_html_et_markdown(seance):
    R.faire_rapport(seance)
    page = (seance / "rapport.html").read_text(encoding="utf-8")
    assert page.startswith("<!doctype html>") and '<html lang="fr">' in page
    assert "data:image/png;base64," in page                     # un seul fichier, l'image dedans
    for titre in ("En bref", "À regarder en premier", "Les trajets", "Le robot", "Erreurs", "Diagnostic du début",
                  "Chronologie", "Les fichiers de la séance"):
        assert f"<h2>{titre}</h2>" in page, titre
    assert "Salle B204" in page and "ARRÊT" in page and "87 → 85 %" in page
    assert "Le robot a bougé sans qu&#x27;on le lui demande" in page
    # aucun nom de sujet ROS dans les titres ni dans les cases « En bref »
    titres = re.findall(r"<h[12]>(.*?)</h[12]>", page) + re.findall(r'class="case-titre">(.*?)<', page)
    assert not any("/" in t and t.count("/") > 0 and t.startswith("/") for t in titres)
    assert not any(re.search(r"/(guide|pont|reperage|cmd_vel|odom)", t) for t in titres)
    md = (seance / "rapport.md").read_text(encoding="utf-8")
    assert md.startswith("# Rapport de séance du ") and "![Trajets du robot sur la carte](trajets.png)" in md
    assert "| 2 | Salle B204 → CDI | Interrompu (ARRÊT" in md


def test_les_donnees_sont_echappees_dans_le_html(tmp_path):
    r = {"seance": "2026-11-12_14h03", "debut": M.heure_iso(T0), "mode": "reel",
         "nom_lieu": "<script>alert(1)</script>",
         "trajets": [{"numero": 1, "depart": "<b>x</b>", "nom": "\"><img src=x onerror=alert(1)>", "cible": "x",
                      "resultat": "arrive", "cause": None, "debut": M.heure_iso(T0), "duree_s": 3, "distance_m": 1.0,
                      "arrets": [{"t": M.heure_iso(T0), "cause": "<i>c</i>"}]}],
         "anomalies": [{"t": None, "genre": "x", "gravite": "probleme", "texte": "<script>x</script>"}],
         "erreurs": [{"t": None, "source": "<u>s</u>", "texte": "<a>t</a>", "nombre": 1}],
         "chronologie": [{"t": M.heure_iso(T0), "depuis_s": 0, "genre": "action", "texte": "<svg onload=x>",
                          "gravite": "info"}], "fichiers": ["<f>"], "resume": {}, "etats_pont": {"<e>": 3.0}}
    page = R.texte_html(r)
    assert "<script>" not in page and "<img" not in page and "<svg" not in page and "<b>x" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page


def test_bag_d_un_atelier_qui_a_plante(tmp_path):
    seance = C.seance_essai(tmp_path, T0, etat="interrompue", sans_metadata=True, demo=DEMO)
    assert not (seance / "bag" / "metadata.yaml").exists()
    assert charger(seance / "bag").erreur is None                  # lisible même sans metadata.yaml
    r = R.faire_rapport(seance)
    assert (seance / "bag" / "metadata.yaml").is_file() and r["enregistrement"]["reindexe"]
    assert any(a["genre"] == "seance_interrompue" for a in r["anomalies"])
    assert reindexer(seance / "bag") is True


def test_seance_sans_bag_ni_lieu(tmp_path):
    seance = C.seance_essai(tmp_path, T0, avec_bag=False)
    r = R.faire_rapport(seance)
    assert r["trajets"] == [] and r["enregistrement"]["lecture"] == "pas d'enregistrement ROS 2 dans cette séance"
    assert (seance / "trajets.png").is_file() and (seance / "rapport.html").is_file()
    assert "Aucun trajet du guide" in (seance / "rapport.html").read_text(encoding="utf-8")
    assert M.lire_manifeste(seance)["rapport"]["etat"] == "pret"


def test_echec_du_rapport_dans_le_manifeste(tmp_path, monkeypatch):
    seance = C.seance_essai(tmp_path, T0, avec_bag=False)

    def casse(*a, **k):
        raise RuntimeError("analyse en panne")
    monkeypatch.setattr(R.A, "analyser", casse)
    with pytest.raises(RuntimeError):
        R.faire_rapport(seance)
    rapport = M.lire_manifeste(seance)["rapport"]
    assert rapport["etat"] == "echec" and "analyse en panne" in rapport["message"]


def test_mise_en_forme_en_francais():
    assert R.duree(3725) == "1 h 02 min" and R.duree(192) == "3 min 12 s" and R.duree(45.2) == "45 s"
    assert R.duree(None) == "—"
    assert R.nombre(12.5) == "12,5" and R.nombre(1234, 0) == "1 234" and R.nombre(None) == "—"
    assert R.taille(1843200) == "1,8 Mo" and R.taille(5300) == "5 ko" and R.taille(0) == "0 Mo"
    assert R.pluriel(1, "trajet") == "1 trajet" and R.pluriel(3, "trajet") == "3 trajets"
    assert R.date_longue("2026-11-12T14:03:05+01:00").endswith("12 novembre 2026, 14 h 03")
    assert R.heure_courte(None) == "—"
    assert "2 arrivé" in R.phrase_trajets({"resume": {"trajets": 3, "par_resultat": {"arrive": 2, "interrompu": 1}}})
