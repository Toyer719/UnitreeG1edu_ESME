"""Tests des sessions de scan intégré (atelier.lieu.scans, section 9 du plan) : session.json,
reconnaissance.yaml, monde tiré du scan, état du scan et exemples pour les autres agents.

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
    assert s["progression"] == 58


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
    assert [L.progression_etape(e) for e in L.ETAPES] == [0, 0, 5, 10, 50, 65, 90, 100]
    assert L.progression_etape("carte_3d", 1.0) == 50 and L.progression_etape("reconnaissance", 0.5) == 78
    assert L.progression_etape("monde", 2.0) == 99
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
    assert s["fichiers"] == {"enregistrement": False, "apercu_png": True, "apercu_json": True, "nuage": False,
                             "carte": False, "reconnaissance": False, "monde": False, "rapport": False}
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


# ---------------------------------------------------------------- reconnaissance.yaml et monde tiré du scan

def _reconnaissance():
    r = L.nouvelle_reconnaissance("rdc", (0, 0, 10, 6), (1.0, 1.0, 0.0), session="2026-10-25_17h42", sol=0.02)
    r["murs"] = [
        {"id": "mur_1", "categorie": "mur", "de": [0.0, 3.0], "a": [4.0, 3.0], "epaisseur": 0.15, "hauteur": 2.5,
         "confiance": 0.9, "a_garder": True},
        {"id": "mur_2", "categorie": "mur", "de": [5.0, 3.0], "a": [10.0, 3.0], "epaisseur": 0.2, "hauteur": 2.4,
         "confiance": 0.8, "a_garder": True},
        {"id": "mur_3", "categorie": "mur", "de": [0.0, 0.0], "a": [10.0, 0.0], "epaisseur": 0.15, "hauteur": 2.5,
         "confiance": 0.3, "a_garder": False},
    ]
    r["passages"] = [{"id": "passage_1", "categorie": "passage", "de": [4.0, 3.0], "a": [5.0, 3.0],
                      "murs": ["mur_1", "mur_2"], "confiance": 0.7, "a_garder": True}]
    r["objets"] = [
        {"id": "table_1", "categorie": "table", "forme": "boite", "centre": [2.0, 1.5], "taille": [1.2, 0.8, 0.75],
         "cap": 0.0, "confiance": 0.65, "a_garder": True},
        {"id": "poteau_1", "categorie": "poteau", "forme": "cylindre", "centre": [7.0, 1.5], "rayon": 0.2,
         "hauteur": 2.5, "confiance": 0.95, "a_garder": True},
        {"id": "personne_1", "categorie": "personne", "forme": "cylindre", "centre": [8.5, 4.5], "rayon": 0.25,
         "hauteur": 1.7, "confiance": 0.6, "a_garder": L.a_garder_par_defaut("personne")},
        {"id": "objet_4", "categorie": "inconnu", "forme": "boite", "centre": [3.0, 4.5], "taille": [0.3, 0.3, 0.5],
         "cap": 0.3, "confiance": 0.2, "a_garder": False},
    ]
    return r


def test_reconnaissance_aller_retour(tmp_path):
    r = _reconnaissance()
    assert L.valider_reconnaissance(r) == []
    chemin = L.ecrire_reconnaissance(tmp_path, r)
    assert chemin == tmp_path / "reconnaissance.yaml"
    assert L.lire_reconnaissance(tmp_path) == r and L.lire_reconnaissance(chemin) == r
    assert chemin.read_text(encoding="utf-8").startswith("# Murs, passages et objets reconnus")


def test_reconnaissance_invalide_pas_ecrite(tmp_path):
    r = _reconnaissance()
    r["objets"][0]["confiance"] = 2
    with pytest.raises(ErreurLieu, match="confiance vaut 2 : il faut au plus 1"):
        L.ecrire_reconnaissance(tmp_path, r)
    assert not (tmp_path / "reconnaissance.yaml").exists()
    with pytest.raises(ErreurLieu, match="la reconnaissance n'a pas encore été faite"):
        L.lire_reconnaissance(tmp_path)


def test_a_garder_par_defaut():
    assert not L.a_garder_par_defaut("personne")
    assert all(L.a_garder_par_defaut(c) for c in L.CATEGORIES_OBJETS if c != "personne")


def test_monde_depuis_reconnaissance():
    r = _reconnaissance()
    monde = L.monde_depuis_reconnaissance(r)
    assert L.valider_donnees("monde", monde.vers_dict()) == []
    assert [m.id for m in monde.murs] == ["mur_1", "mur_2"]            # mur_3 retiré
    assert all(m.source == "scan" for m in monde.murs) and monde.murs[1].confiance == 0.8
    assert [o.id for o in monde.objets] == ["table_1", "poteau_1"]     # personne et inconnu retirés
    table, poteau = monde.objets
    assert (table.type, table.categorie, table.taille, table.source) == ("boite", "table", (1.2, 0.8, 0.75), "scan")
    assert (poteau.type, poteau.rayon, poteau.categorie_effective) == ("cylindre", 0.2, "poteau")
    assert monde.pietons == [] and (monde.emprise.xmax, monde.depart_robot.x) == (10, 1.0)


def test_passage_non_garde_bouche():
    r = _reconnaissance()
    r["passages"][0]["a_garder"] = False
    monde = L.monde_depuis_reconnaissance(r)
    bouche = monde.element("passage_1")
    assert (bouche.de, bouche.a, bouche.epaisseur, bouche.hauteur) == ((4.0, 3.0), (5.0, 3.0), 0.2, 2.5)
    from atelier.monde.carte import fabriquer_carte
    info, carte = fabriquer_carte(monde)
    colonne, ligne = L.monde_vers_pixel(4.5, 3.0, info)
    assert carte[ligne, colonne] == 0                                   # le trou est bouché sur la carte
    r["passages"][0]["a_garder"] = True
    info, carte = fabriquer_carte(L.monde_depuis_reconnaissance(r))
    assert carte[ligne, colonne] == 254


def test_personne_gardee_dans_le_monde_mais_pas_sur_la_carte():
    from atelier.monde.carte import fabriquer_carte
    r = _reconnaissance()
    _, sans = fabriquer_carte(L.monde_depuis_reconnaissance(r))
    r["objets"][2]["a_garder"] = True
    monde = L.monde_depuis_reconnaissance(r)
    assert monde.element("personne_1").categorie == "personne"
    _, avec = fabriquer_carte(monde)
    assert (sans == avec).all()


def test_monde_scan_aller_retour_du_demo():
    """Vérité terrain du demo → monde : les mêmes murs, et chaque objet au même endroit."""
    monde = L.charger_monde(DEMO, "rdc")
    retour = L.monde_depuis_reconnaissance(L.reconnaissance_depuis_monde(monde, "rdc"))
    assert [(m.id, m.de, m.a) for m in retour.murs] == [(m.id, m.de, m.a) for m in monde.murs]
    gardes = [o for o in monde.objets if o.sur_la_carte]
    assert [(o.id, o.centre, o.categorie) for o in retour.objets] == [(o.id, o.centre, o.categorie) for o in gardes]
    from atelier.monde.carte import fabriquer_carte
    _, carte_monde = fabriquer_carte(monde)
    _, carte_retour = fabriquer_carte(retour)
    assert (carte_monde == carte_retour).mean() > 0.999                # mêmes obstacles sur la carte


def test_ecrire_monde_scan(tmp_path):
    monde = L.ecrire_monde_scan(tmp_path, _reconnaissance())
    texte = (tmp_path / "monde_scan.monde.yaml").read_text(encoding="utf-8")
    assert texte.startswith("# Monde tiré du scan")
    assert L.Monde.depuis_dict(L.charger_fichier(tmp_path / "monde_scan.monde.yaml", "monde")) == monde


def test_changer_a_garder(demo):
    s = creer_session_exemple(demo, "termine")
    r = L.changer_a_garder(demo, s["id"], {"passage_1": False, "table_est": False, "personne_b204": True})
    assert r["resume"]["passages_gardes"] == 4
    ids_monde = {m["id"] for m in r["monde"]["murs"]} | {o["id"] for o in r["monde"]["objets"]}
    assert "passage_1" in ids_monde and "table_est" not in ids_monde and "personne_b204" in ids_monde
    relu = L.lire_reconnaissance(L.dossier_session(demo, s["id"]))
    assert next(o for o in relu["objets"] if o["id"] == "table_est")["a_garder"] is False
    monde = L.charger_fichier(L.chemin_session(demo, s["id"], "monde"), "monde")
    assert {o["id"] for o in monde["objets"]} == {o["id"] for o in r["monde"]["objets"]}


def test_changer_a_garder_refuse(demo):
    s = creer_session_exemple(demo, "termine")
    avant = L.chemin_session(demo, s["id"], "reconnaissance").read_text(encoding="utf-8")
    with pytest.raises(ErreurLieu, match="id inconnu.*armoire_9"):
        L.changer_a_garder(demo, s["id"], {"table_est": False, "armoire_9": True})
    with pytest.raises(ErreurLieu, match="true ou false"):
        L.changer_a_garder(demo, s["id"], {"table_est": "non"})
    assert L.chemin_session(demo, s["id"], "reconnaissance").read_text(encoding="utf-8") == avant
    en_cours = creer_session_exemple(demo, "traitement")
    with pytest.raises(ErreurLieu, match="attendez la fin du traitement"):
        L.changer_a_garder(demo, en_cours["id"], {"table_est": False})


def test_carte_sans_elements_retires():
    from atelier.monde.carte import fabriquer_carte
    r = _reconnaissance()
    r["objets"][2]["a_garder"] = True
    r["objets"][3]["a_garder"] = True
    # Carte « du scan » où tout est vu : murs et objets, personne comprise
    monde = L.monde_depuis_reconnaissance(dict(r, objets=[dict(o, categorie="inconnu") for o in r["objets"]]))
    info, carte = fabriquer_carte(monde)

    def occupe(x, y):
        colonne, ligne = L.monde_vers_pixel(x, y, info)
        return resultat[ligne, colonne] == 0
    resultat = L.carte_sans_elements_retires(info, carte, r)
    assert not occupe(8.5, 4.5)                                           # personne effacée, même gardée
    assert occupe(2.0, 1.5) and occupe(7.0, 1.5) and occupe(3.0, 4.5)     # objets gardés
    r["objets"][0]["a_garder"] = False
    resultat = L.carte_sans_elements_retires(info, carte, r)
    assert not occupe(2.0, 1.5) and occupe(2.0, 3.0)                      # table effacée, mur intact
    r["murs"][0]["a_garder"] = False
    resultat = L.carte_sans_elements_retires(info, carte, r)
    assert occupe(2.0, 3.0)                                               # un mur ne change jamais la carte
    assert (carte == fabriquer_carte(monde)[1]).all()                      # la carte donnée n'est pas modifiée


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
    if etat in ("traitement", "termine"):
        info, image = L.charger_carte(d / "carte.yaml")
        assert info.image == "carte.pgm" and image.shape == (402, 602)
    if etat == "termine":
        assert L.valider_reconnaissance(L.lire_reconnaissance(d)) == []
        L.charger_fichier(d / "monde_scan.monde.yaml", "monde")
        rapport = json.loads((d / "rapport.json").read_text(encoding="utf-8"))
        assert [e["etape"] for e in rapport["etapes"]] == list(L.ETAPES_TRAITEMENT)
