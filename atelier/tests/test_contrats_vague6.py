"""Tests des contrats de la vague 6 (agent Contrats, section 13 du plan).

  ~/robot-g1/.venv-projet/bin/python -m pytest ~/robot-g1/atelier/tests/test_contrats_vague6.py -v

Vérifie que :
  - les schémas nouveaux (diagnostic, seance, action_seance, demo, etat_borne, requete_voix, etat_demo,
    evenement_demo, choix_accueil, commande_accueil, etat_voix, son_voix, commande_voix) et robot_dire changé sont
    des schémas draft-07 valides, que leurs exemples sont conformes, qu'atelier.lieu et jsonschema rendent le même
    verdict sur des centaines de variantes, que leurs énumérations sont celles des modules de contrat, et que les
    règles refusent ce qu'elles doivent ;
  - les fonctions de atelier.lieu.diagnostic, seance, accueil et voix suivent le contrat (liste blanche des services,
    salles de la borne, chemins permis depuis la borne, morceaux de PCM, demo.yaml…) ;
  - le serveur a ses routes (jamais d'erreur 500), l'accroche du journal des actions (la réponse ne change pas, une
    erreur de la boîte noire ne gêne rien), la garde de la borne, les champs de /ws/etat, les appels de la séance au
    démarrage, à l'arrêt et avant g1-jetson arreter, la liste blanche de PontRos.appeler_unitree ;
  - l'interface a ses modules, ses exports, ses commandes du ruban et leurs points d'accroche, la page de la borne ;
  - le faux G1 garde son service voice d'avant et reçoit robot_state ; g1_accueil et les commandes existent ;
  - la section 13 du plan est là, avec les critères 37 à 42 ; tout.sh en compte 42 ; aucun fichier de la table 13.11
    n'a deux propriétaires.
"""
import asyncio
import copy
import json
import os
import random
import re
import stat
import sys
from pathlib import Path

import jsonschema
import pytest
import yaml

import atelier
from atelier import lieu as L
from atelier.lieu import accueil as A
from atelier.lieu import diagnostic as G
from atelier.lieu import equipe as E
from atelier.lieu import seance as S
from atelier.lieu import voix as V
from atelier.lieu.validation import erreurs_schema
from atelier.tests.test_contrats_vague5 import _exports, _revendications, _se_recouvrent
from atelier.tests.test_lieu_validation import MUTATIONS, _chemins, _muter

RACINE = atelier.RACINE
DOSSIER_SCHEMAS = RACINE / "atelier" / "lieu" / "schemas"
DEMO = RACINE / "lieux" / "demo"
WEB = RACINE / "atelier" / "web"
PLAN = RACINE / "docs" / "plan-atelier-multi-agents.md"
TOUT = RACINE / "tests_e2e" / "tout.sh"
JUMEAU = RACINE / "ws" / "src" / "g1_jumeau"
ACCUEIL = RACINE / "ws" / "src" / "g1_accueil"

NOUVEAUX = ("diagnostic", "seance", "action_seance", "demo", "etat_borne", "requete_voix", "etat_demo",
            "evenement_demo", "choix_accueil", "commande_accueil", "etat_voix", "son_voix", "commande_voix")
MESSAGES = ("etat_demo", "evenement_demo", "choix_accueil", "commande_accueil", "etat_voix", "son_voix",
            "commande_voix")
CHANGES = ("robot_dire",)


def schema(nom):
    return json.loads((DOSSIER_SCHEMAS / f"{nom}.schema.json").read_text(encoding="utf-8"))


def erreurs_js(nom, donnees):
    return [e.message for e in jsonschema.Draft7Validator(schema(nom)).iter_errors(donnees)]


def modifie(exemple, changement):
    donnees = copy.deepcopy(exemple)
    changement(donnees)
    return donnees


def exemples():
    """Un exemple conforme de chaque schéma nouveau ou changé."""
    return {"diagnostic": G.EXEMPLE_DIAGNOSTIC, "seance": S.EXEMPLE_SEANCE, "action_seance": S.EXEMPLE_ACTION,
            "demo": A.EXEMPLE_DEMO, "etat_borne": A.EXEMPLE_ETAT_BORNE, "requete_voix": V.EXEMPLE_REQUETE_LECTURE,
            "etat_demo": A.EXEMPLE_ETAT_DEMO, "evenement_demo": A.EXEMPLE_EVENEMENT_DEMO,
            "choix_accueil": A.EXEMPLE_CHOIX, "commande_accueil": A.EXEMPLE_COMMANDE,
            "etat_voix": V.EXEMPLE_ETAT_VOIX, "son_voix": V.EXEMPLE_SON_VOIX, "commande_voix": V.EXEMPLE_COMMANDE_VOIX,
            "robot_dire": dict(E.EXEMPLE_ROBOT_DIRE, source="accueil", priorite="securite", id="s-20261112-0001")}


@pytest.fixture
def demo(tmp_path):
    return L.copier_lieu(DEMO, tmp_path / "demo")


# ---------------------------------------------------------------- schémas, exemples et règles

@pytest.mark.parametrize("nom", NOUVEAUX + CHANGES)
def test_schema_draft07_valide(nom):
    s = schema(nom)
    assert s["$schema"] == "http://json-schema.org/draft-07/schema#"
    jsonschema.Draft7Validator.check_schema(s)
    assert nom in L.TYPES_FICHIERS
    erreurs_schema(nom, {})         # aucun mot-clé que notre moteur ne connaît pas


def test_types_des_messages():
    assert set(MESSAGES) <= set(L.TYPES_MESSAGES)
    assert not {"diagnostic", "seance", "demo", "etat_borne", "requete_voix"} & set(L.TYPES_MESSAGES)
    for nom in MESSAGES:
        assert L.valider_message(nom, exemples()[nom]) == []


@pytest.mark.parametrize("nom", NOUVEAUX + CHANGES)
def test_exemples_conformes(nom):
    d = exemples()[nom]
    assert erreurs_js(nom, d) == []
    assert L.valider_donnees(nom, d) == []


@pytest.mark.parametrize("nom", NOUVEAUX + CHANGES)
def test_meme_verdict_que_jsonschema(nom):
    """Sur des centaines de variantes des exemples, atelier.lieu et jsonschema sont d'accord."""
    exemple = exemples()[nom]
    validateur = jsonschema.Draft7Validator(schema(nom))
    cas = [(c, m) for c in _chemins(exemple) for m in MUTATIONS]
    random.Random(6).shuffle(cas)
    desaccords = []
    for chemin, mutation in cas[:500]:
        variante = _muter(exemple, chemin, mutation)
        nous = bool(erreurs_schema(nom, variante))
        eux = any(True for _ in validateur.iter_errors(variante))
        if nous != eux:
            desaccords.append((chemin, mutation, nous, eux))
    assert desaccords == []


def test_enumerations_des_schemas_et_des_modules():
    """Les valeurs possibles des schémas sont celles des modules de contrat (un seul endroit pour chacune)."""
    def enum(s, *chemin):
        for c in chemin:
            s = s[c]
        return tuple(x for x in s["enum"] if x is not None)
    d = schema("diagnostic")
    assert enum(d, "definitions", "etat") == G.ETATS_VERIFICATION
    assert enum(d, "properties", "verifications", "items", "properties", "action") == tuple(G.ACTIONS_DIAGNOSTIC)
    assert enum(d, "properties", "verifications", "items", "properties", "groupe") == tuple(G.GROUPES_DIAGNOSTIC)
    assert tuple(d["properties"]["resume"]["required"]) == G.ETATS_VERIFICATION
    s = schema("seance")
    assert enum(s, "properties", "etat") == S.ETATS_SEANCE and enum(s, "properties", "mode") == S.MODES_SEANCE
    assert enum(s, "properties", "ouverture") == S.OUVERTURES and enum(s, "properties", "fermeture") == S.FERMETURES
    assert enum(s, "properties", "enregistrement", "properties", "etat") == S.ETATS_ENREGISTREMENT
    assert enum(s, "properties", "rapport", "properties", "etat") == S.ETATS_RAPPORT
    assert enum(s, "properties", "jetson", "items", "properties", "raison") == S.RAISONS_JOURNAL_JETSON
    a = schema("action_seance")
    assert enum(a, "properties", "genre") == S.GENRES_ACTION
    assert enum(a, "properties", "methode") == S.METHODES_JOURNAL
    e = schema("etat_demo")
    assert enum(e, "properties", "etat") == A.ETATS_DEMO and enum(e, "properties", "raison") == A.RAISONS_PAUSE
    assert enum(e, "properties", "actions_possibles", "items") == A.ACTIONS_COMMANDE
    assert enum(e, "properties", "source_visiteurs") == A.SOURCES_VISITEURS
    v = schema("evenement_demo")
    assert enum(v, "properties", "code") == A.CODES_EVENEMENT_DEMO
    assert enum(v, "properties", "raison") == A.RAISONS_PAUSE + A.RAISONS_REFUS
    assert enum(schema("choix_accueil"), "properties", "source") == A.SOURCES_ACCUEIL
    assert enum(schema("commande_accueil"), "properties", "action") == A.ACTIONS_COMMANDE
    assert enum(schema("etat_borne"), "properties", "ecran") == A.ECRANS_BORNE
    assert set(A.ECRAN_DE_L_ETAT) == set(A.ETATS_DEMO) and set(A.ECRAN_DE_L_ETAT.values()) <= set(A.ECRANS_BORNE)
    assert set(A.TEXTES_BORNE) == set(A.ECRANS_BORNE)
    assert enum(schema("demo"), "properties", "voix", "properties", "sortie") == V.SORTIES_VOIX
    assert enum(schema("etat_voix"), "properties", "sortie") == V.SORTIES_VOIX
    assert enum(schema("son_voix"), "properties", "priorite") == V.PRIORITES_VOIX
    assert enum(schema("commande_voix"), "properties", "action") == V.ACTIONS_VOIX
    assert enum(schema("requete_voix"), "properties", "api_id") == V.APIS_NOEUD_VOIX
    r = schema("robot_dire")["properties"]
    assert tuple(r["source"]["enum"]) == E.SOURCES_DIRE and "accueil" in E.SOURCES_DIRE
    assert tuple(r["priorite"]["enum"]) == E.PRIORITES_DIRE == V.PRIORITES_VOIX
    assert set(V.RANG_PRIORITE) == set(V.PRIORITES_VOIX)
    assert re.compile(schema("son_voix")["properties"]["id"]["pattern"]).pattern == V.MOTIF_ID_SON.pattern
    assert re.compile(schema("seance")["properties"]["id"]["pattern"]).pattern == S.MOTIF_ID_SEANCE.pattern


def test_anciens_messages_toujours_conformes():
    ancien = {"version": 1, "texte": "Bonjour !", "source": "dialogue", "priorite": "haute", "langue": "fr"}
    assert L.valider_message("robot_dire", ancien) == []
    assert L.valider_message("robot_dire", E.message_robot_dire("Je fais une pause.", "accueil", priorite="securite")) == []
    assert L.valider_message("robot_dire", dict(ancien, id="../x")) != []


REFUS = {
    "diagnostic : id en double": ("diagnostic", lambda d: d["verifications"].append(dict(d["verifications"][0]))),
    "diagnostic : resume faux": ("diagnostic", lambda d: d["resume"].update(ok=99)),
    "diagnostic : état global faux": ("diagnostic", lambda d: d.update(etat="ok")),
    "diagnostic : conseil manquant": ("diagnostic", lambda d: d["verifications"][2].update(conseil=None)),
    "diagnostic : actions fausses": ("diagnostic", lambda d: d.update(actions=["retablir-cable"])),
    "diagnostic : action inconnue": ("diagnostic", lambda d: d["verifications"][0].update(action="eteindre")),
    "diagnostic : état inconnu": ("diagnostic", lambda d: d["verifications"][0].update(etat="bien")),
    "diagnostic : mode simu": ("diagnostic", lambda d: d.update(mode="simu")),
    "séance : ouverte avec une fin": ("seance", lambda d: d.update(fin="2026-11-12T15:00:00+01:00")),
    "séance : fermée sans fin": ("seance", lambda d: d.update(etat="fermee", fermeture="terminer")),
    "séance : fermée sans raison": ("seance", lambda d: d.update(etat="fermee", fin="2026-11-12T15:00:00+01:00")),
    "séance : fin avant le début": ("seance", lambda d: d.update(etat="fermee", fermeture="terminer",
                                                                  fin="2026-11-12T13:00:00+01:00")),
    "séance : id mal formé": ("seance", lambda d: d.update(id="../autre")),
    "séance : enregistrement inconnu": ("seance", lambda d: d["enregistrement"].update(etat="pause")),
    "action : genre inconnu": ("action_seance", lambda d: d.update(genre="danser")),
    "action : chemin hors de l'API": ("action_seance", lambda d: d.update(chemin="/borne")),
    "action : méthode GET": ("action_seance", lambda d: d.update(methode="GET")),
    "démo : pause sans raison": ("etat_demo", lambda d: d.update(etat="pause", raison=None)),
    "démo : raison hors pause": ("etat_demo", lambda d: d.update(raison="verrou")),
    "démo : accompagnement sans visite": ("etat_demo", lambda d: d.update(visite=None)),
    "démo : état inconnu": ("etat_demo", lambda d: d.update(etat="danse")),
    "démo : statistiques incomplètes": ("etat_demo", lambda d: d["statistiques"].pop("visiteurs")),
    "événement : code inconnu": ("evenement_demo", lambda d: d.update(code="bonjour")),
    "choix : salle mal formée": ("choix_accueil", lambda d: d.update(salle="B 204")),
    "choix : source inconnue": ("choix_accueil", lambda d: d.update(source="internet")),
    "choix : champ en trop": ("choix_accueil", lambda d: d.update(vitesse=2)),
    "commande : action inconnue": ("commande_accueil", lambda d: d.update(action="debloquer")),
    "borne : écran inconnu": ("etat_borne", lambda d: d.update(ecran="reglages")),
    "borne : son hors de /api/voix/son": ("etat_borne", lambda d: d["son"].update(url="/api/arret")),
    "demo.yaml : code de 3 chiffres": ("demo", lambda d: d["borne"].update(code_operateur="123")),
    "demo.yaml : code avec des lettres": ("demo", lambda d: d["borne"].update(code_operateur="12ab")),
    "demo.yaml : sortie inconnue": ("demo", lambda d: d["voix"].update(sortie="pc")),
    "demo.yaml : champ inconnu": ("demo", lambda d: d.update(danse=True)),
    "voix : sortie inconnue": ("etat_voix", lambda d: d.update(sortie="pc")),
    "son : url ailleurs": ("son_voix", lambda d: d.update(url="/etc/passwd")),
    "commande de la voix : volume sans valeur": ("commande_voix", lambda d: d.update(action="volume", volume=None)),
    "commande de la voix : sortie sans valeur": ("commande_voix", lambda d: d.update(action="sortie")),
    "requête : 1003 impaire": ("requete_voix", lambda d: d.update(octets=35201)),
    "requête : 1003 trop grande": ("requete_voix", lambda d: d.update(octets=96002)),
    "requête : 1003 vide": ("requete_voix", lambda d: d.update(octets=0)),
    "requête : 1003 sans stream_id": ("requete_voix", lambda d: d["parametre"].pop("stream_id")),
    "requête : LED par la voix": ("requete_voix", lambda d: d.update(api_id=1010)),
}


@pytest.mark.parametrize("cas", sorted(REFUS))
def test_les_regles_refusent(cas):
    nom, changement = REFUS[cas]
    variante = modifie(exemples()[nom], changement)
    variante = {k: v for k, v in variante.items() if v is not None or k not in ("volume",)}
    assert L.valider_donnees(nom, variante) != [], cas


def test_requetes_de_la_voix():
    pcm = bytes(range(256)) * 375                    # 96 000 octets
    assert V.erreurs_requete_voix(1003, V.parametre_lecture("s-1"), pcm) == []
    assert V.erreurs_requete_voix(1003, V.parametre_lecture("s-1"), pcm + b"\x00\x00") != []
    assert V.erreurs_requete_voix(1003, V.parametre_lecture("s-1"), b"\x00") != []
    assert V.erreurs_requete_voix(1004, V.parametre_arret()) == []
    assert V.erreurs_requete_voix(1004, V.parametre_arret(), b"\x00\x00") != []
    assert V.erreurs_requete_voix(1001, V.parametre_tts("Bonjour", 2, V.LOCUTEURS_TTS["en"])) == []
    assert V.erreurs_requete_voix(1005, V.parametre_lire_volume()) == []
    assert V.erreurs_requete_voix(1006, V.parametre_volume(60)) == []
    assert V.erreurs_requete_voix(1006, json.dumps({"volume": 101})) != []
    assert V.erreurs_requete_voix(1002, "{}") != [] and V.erreurs_requete_voix(1010, json.dumps({"R": 1})) != []
    assert V.erreurs_requete_voix(1003, "pas du JSON", b"\x00\x00") != []
    assert json.loads(V.parametre_lecture("s-2")) == {"app_name": V.APP_VOIX, "stream_id": "s-2"}
    assert json.loads(V.parametre_arret()) == {"app_name": "atelier"}


# ---------------------------------------------------------------- fonctions des modules de contrat

def test_liste_blanche_des_services():
    assert G.SERVICES_CARTOGRAPHIE == ("lidar_driver", "unitree_slam")
    for nom in G.SERVICES_CARTOGRAPHIE:
        assert json.loads(G.parametre_service_switch(nom)) == {"name": nom, "switch": 1}
    for interdit in ("ai_sport", "motion_switcher", "voice", "", "lidar_driver ", None):
        with pytest.raises(ValueError):
            G.parametre_service_switch(interdit)
    assert G.parametre_service_list() == "{}"
    assert G.API_ROBOT_STATE == {"service_switch": 1001, "report_freq": 1002, "service_list": 1003}
    assert G.APPELS_UNITREE_PERMIS == {("robot_state", 1003), ("robot_state", 1001), ("sport", 7001)}
    assert set(G.ACTIONS_DIAGNOSTIC) == {"demarrer-services", "retablir-cable", "cable-automatique"}
    assert set(G.COMMANDES_ACTIONS) == {"retablir-cable", "cable-automatique"}
    assert G.COMMANDES_ACTIONS["retablir-cable"] == ("nmcli", "connection", "up", "robot-g1")
    assert all(a["confirmation"].strip() and a["libelle"] for a in G.ACTIONS_DIAGNOSTIC.values())
    assert set(G.VERIFICATIONS_REPETITION) <= set(G.VERIFICATIONS)
    assert all(g in G.GROUPES_DIAGNOSTIC for g, _ in G.VERIFICATIONS.values())


def test_reponses_de_robot_state():
    liste = json.dumps([{"name": "lidar_driver", "status": 1, "protect": False},
                        {"name": "unitree_slam", "status": 0, "protect": False},
                        {"name": "ai_sport", "status": 0, "protect": True}])
    services = G.lire_liste_services(liste)
    assert [s["name"] for s in services] == ["lidar_driver", "unitree_slam", "ai_sport"]
    assert G.services_arretes(services) == ["lidar_driver"]
    assert G.services_arretes([]) == ["lidar_driver", "unitree_slam"]        # absents : pas actifs
    for faux in ("pas du json", "{}", json.dumps([{"name": "x"}]), json.dumps([{"name": "x", "status": True}])):
        with pytest.raises(ValueError):
            G.lire_liste_services(faux)
    assert [s["protect"] for s in G.lire_liste_services('[{"name": "ai_sport", "status": 0, "protect": 1}]')] == [True]
    assert G.lire_reponse_switch('{"name": "lidar_driver", "status": 0}') == (True, 0, None)
    assert G.lire_reponse_switch('{"status": 0}') == (True, 0, None)
    assert G.lire_reponse_switch('{"status": 1}')[0] is True
    ok, statut, raison = G.lire_reponse_switch('{"status": 5}')
    assert not ok and statut == 5 and "protégé" in raison
    assert G.lire_reponse_switch('{"status": 2}')[0] is False and G.lire_reponse_switch("{}")[0] is False


def test_fabrique_du_diagnostic():
    with pytest.raises(ValueError):
        G.verification("cable", "probleme", "Câble absent.")            # pas de conseil
    with pytest.raises(ValueError):
        G.verification("cable", "bien", "?")
    with pytest.raises(ValueError):
        G.verification("cable", "ok", "Câble.", action="eteindre")
    with pytest.raises(ValueError):
        G.verification("Câble", "ok", "Câble.")
    v = G.verification("services", "attention", "Un service démarre.", conseil="Attendez 10 s.", action="demarrer-services")
    assert v["titre"] == "Services de cartographie" and v["groupe"] == "robot"
    bon = G.diagnostic([G.verification("ros", "ok", "ROS 2 vu.")], "repetition", "2026-11-12T14:03:05+01:00", 0.2)
    assert L.valider_donnees("diagnostic", bon) == [] and G.code_de_sortie(bon) == 0 and bon["etat"] == "ok"
    assert "prêt" in bon["message"]
    inconnu = G.diagnostic([G.verification("batterie", "inconnu", "Rien.", conseil="Attendez.")], "reel",
                           "2026-11-12T14:03:05+01:00", 0.2)
    assert inconnu["etat"] == "inconnu" and G.code_de_sortie(inconnu) == 0
    mauvais = G.diagnostic([v, G.verification("cable", "probleme", "Câble absent.", conseil="Branchez-le.")], "reel",
                           "2026-11-12T14:03:05+01:00", 1.0)
    assert mauvais["etat"] == "probleme" and G.code_de_sortie(mauvais) == 1 and mauvais["actions"] == ["demarrer-services"]
    assert mauvais["message"].startswith("2 points à régler : Câble du robot. Branchez-le.")
    assert L.valider_donnees("diagnostic", mauvais) == []


def test_dossier_et_reglages_des_seances(tmp_path, monkeypatch):
    monkeypatch.setenv("ATELIER_SEANCES", str(tmp_path / "seances"))
    assert S.dossier_seances() == tmp_path / "seances" and (tmp_path / "seances").is_dir()
    from datetime import datetime
    instant = datetime(2026, 11, 12, 14, 3)
    assert S.id_seance(instant) == "2026-11-12_14h03"
    assert S.id_seance(instant, {"2026-11-12_14h03"}) == "2026-11-12_14h03-2"
    assert S.id_seance(instant, {"2026-11-12_14h03", "2026-11-12_14h03-2"}) == "2026-11-12_14h03-3"
    assert all(S.MOTIF_ID_SEANCE.match(x) for x in ("2026-11-12_14h03", "2026-11-12_14h03-12"))
    assert S.reglage("place_libre_min_go") == 2.0 and S.reglage("taille_max_mo") == 1024
    monkeypatch.setenv("ATELIER_SEANCE_PLACE_MIN_GO", "5000")
    assert S.reglage("place_libre_min_go") == 5000.0
    assert S.action_journalisee("POST", "/api/arret") and S.action_journalisee("PUT", "/api/lieux/demo/salles")
    assert not S.action_journalisee("GET", "/api/arret") and not S.action_journalisee("POST", "/borne")
    assert not S.action_journalisee("POST", "/api/simulation/teleop")
    assert S.sujet_enregistre("/guide/etat") and S.sujet_enregistre("/cmd_vel", "geometry_msgs/msg/Twist")
    assert not S.sujet_enregistre("/points") and not S.sujet_enregistre("/api/voice/request")
    assert not S.sujet_enregistre("/odom", "sensor_msgs/msg/PointCloud2")
    for sujet, frequence in S.SUJETS_SEANCE.items():
        assert sujet.startswith("/") and (frequence is None or 0 < frequence <= 50), sujet
    assert S.SUJETS_SEANCE["/state_estimator/odom_pelvis"] == 10.0 and S.SUJETS_SEANCE["/lf/bmsstate"] == 1.0
    assert not any(s in S.SUJETS_SEANCE for s in ("/points", "/unitree/slam_relocation/points", "/tf"))
    for sujet in list(A.SUJETS_ACCUEIL) + list(V.SUJETS_VOIX):
        assert sujet in S.SUJETS_SEANCE, sujet
    assert S.FICHIERS_SEANCE["manifeste"] == "seance.json" and S.FICHIERS_SEANCE["actions"] == "actions.jsonl"


def test_salles_de_la_borne(demo):
    salles = L.charger_salles(demo)
    principal = L.principal.point_principal(demo).id
    proposees = A.salles_de_la_borne(salles, principal, "rdc", {"rdc": "Rez-de-chaussée"})
    ids = [s["id"] for s in proposees]
    assert principal not in ids and ids == [s.id for s in salles if s.id != principal]
    assert all(s["accessible"] and s["nom_etage"] == "Rez-de-chaussée" for s in proposees)
    cachee = salles[1] if salles[0].id == principal else salles[0]
    cachee.etiquettes = ["hors_borne"]
    salles[2].etiquettes = ["toilettes"]
    salles[3].etage = "etage1"
    proposees = {s["id"]: s for s in A.salles_de_la_borne(salles, principal, "rdc")}
    assert cachee.id not in proposees
    assert proposees[salles[2].id]["pictogramme"] == "toilettes"
    assert proposees[salles[3].id]["accessible"] is False
    assert A.refus_choix(principal, salles, principal, "rdc")[0] == "deja_la"
    assert A.refus_choix("inconnue", salles, principal, "rdc")[0] == "salle_inconnue"
    assert A.refus_choix(cachee.id, salles, principal, "rdc")[0] == "salle_cachee"
    assert A.refus_choix(salles[3].id, salles, principal, "rdc")[0] == "autre_etage"
    assert A.refus_choix(salles[2].id, salles, principal, "rdc") is None
    borne = dict(A.EXEMPLE_ETAT_BORNE, salles=list(proposees.values()))
    assert L.valider_donnees("etat_borne", borne) == []


def test_ecrans_messages_et_chemins_de_la_borne():
    assert A.ecran_borne(None) == "hors_service" and A.ecran_borne({"etat": "inconnu"}) == "hors_service"
    assert A.ecran_borne({"etat": "pause"}) == "pause" and A.ecran_borne(A.EXEMPLE_ETAT_DEMO) == "suivez_moi"
    for etat in A.ETATS_CHOIX_POSSIBLE:
        assert A.ecran_borne({"etat": etat}) == "salles"
    assert L.valider_message("choix_accueil", A.message_choix("b204", "borne", "borne-1")) == []
    assert L.valider_message("choix_accueil", A.message_choix("b204", "dialogue", texte="la b204", accompagner=False)) == []
    assert L.valider_message("commande_accueil", A.message_commande("pause", "operateur", "op-1")) == []
    for faux in (lambda: A.message_choix("b204", "internet"), lambda: A.message_commande("debloquer", "borne"),
                 lambda: A.message_commande("pause", "inconnu")):
        with pytest.raises(ValueError):
            faux()
    for chemin in ("/borne", "/borne/", "/borne.html", "/css/theme.css", "/css/borne.css", "/js/borne/borne.js",
                   "/api/borne/etat", "/api/borne/choisir", "/ws/borne", "/api/voix/son/s-1"):
        assert A.chemin_permis_borne(chemin), chemin
    for chemin in ("/", "/index.html", "/api/arret", "/api/arret/debloquer", "/api/guide/aller", "/api/lieux",
                   "/ws/etat", "/ws/pilotage", "/js/app.js", "/js/coque/coque.js", "/css/atelier.css",
                   "/api/voix/essayer", "/api/demo/lancer", "/bornes", "/js/borne2/x.js"):
        assert not A.chemin_permis_borne(chemin), chemin
    assert set(A.ACTIONS_OPERATEUR_BORNE) <= set(A.ACTIONS_COMMANDE) and "reprendre" in A.ACTIONS_OPERATEUR_BORNE
    assert set(A.REGLAGES_DEMO["source_visiteurs"].split()) <= set(A.SOURCES_VISITEURS)


def test_demo_yaml(demo):
    assert A.charger_demo(demo) is None
    reglages = A.reglages_demo(demo)
    assert reglages == A.DEMO_DEFAUT and L.valider_donnees("demo", reglages) == []
    A.enregistrer_demo(demo, {"version": 1, "voix": {"sortie": "borne"}, "borne": {"code_operateur": "4826"}})
    assert A.charger_demo(demo)["voix"] == {"sortie": "borne"}
    complet = A.reglages_demo(demo)
    assert complet["voix"]["sortie"] == "borne" and complet["voix"]["volume"] == 70
    assert complet["borne"]["code_operateur"] == "4826" and complet["borne"]["titre"] == A.TEXTES_BORNE["salles"]
    assert "pas un mot de passe" in (demo / "demo.yaml").read_text(encoding="utf-8")
    with pytest.raises(L.ErreurLieu):
        A.enregistrer_demo(demo, {"version": 1, "borne": {"code_operateur": "12"}})
    assert L.valider_lieu(demo).ok
    A.enregistrer_demo(demo, {"version": 1, "personnalite": "fantome"})
    E.enregistrer_equipe(demo, "personnalites", E.exemple_equipe("personnalites"))
    r = L.valider_lieu(demo)
    assert r.ok and any("fantome" in m for m in r.avertissements), r.avertissements
    (demo / "demo.yaml").write_text("version: 1\nvoix: {sortie: pc}\n", encoding="utf-8")
    r = L.valider_lieu(demo)
    assert not r.ok and any("demo.yaml" in m for m in r.erreurs)


def test_morceaux_et_sons(tmp_path, monkeypatch):
    pcm = bytes(200002)
    morceaux = V.morceaux_pcm(pcm)
    assert [len(m) for m in morceaux] == [96000, 96000, 8002] and b"".join(morceaux) == pcm
    assert V.morceaux_pcm(b"") == []
    for faux in (lambda: V.morceaux_pcm(b"\x00"), lambda: V.morceaux_pcm(pcm, 96002), lambda: V.morceaux_pcm(pcm, 3)):
        with pytest.raises(ValueError):
            faux()
    assert V.duree_pcm_s(96000) == 3.0 and V.OCTETS_PAR_SECONDE == 32000
    monkeypatch.setenv("ATELIER_VOIX_SONS", str(tmp_path / "sons"))
    assert V.chemin_son("s-1") == tmp_path / "sons" / "s-1.wav"
    for faux in ("../x", "S-1", "", None, "a/b"):
        with pytest.raises(ValueError):
            V.chemin_son(faux)
    assert set(V.VOIX_PIPER) == {"fr_FR-siwis-medium", "fr_FR-tom-medium"} and V.VOIX_DEFAUT in V.VOIX_PIPER
    assert V.APIS_NOEUD_VOIX == (1001, 1003, 1004, 1005, 1006) and 1010 not in V.APIS_NOEUD_VOIX


def test_sujets_de_l_equipe_de_la_vague_6():
    for sujet, (type_ros, schema_json, _) in A.SUJETS_ACCUEIL.items():
        assert E.SUJETS_EQUIPE[sujet][:2] == (type_ros, schema_json)
    for sujet in ("/voix/etat", "/voix/son", "/voix/commande"):
        assert E.SUJETS_EQUIPE[sujet][:2] == V.SUJETS_VOIX[sujet][:2]


# ---------------------------------------------------------------- serveur

@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from atelier.serveur.main import creer_app
    monkeypatch.setenv("ATELIER_LIEUX", str(tmp_path / "lieux"))
    monkeypatch.setenv("ATELIER_INTERFACE_ROBOT", "interface_absente_v6")
    monkeypatch.delenv("ATELIER_HOTE", raising=False)
    L.copier_lieu(DEMO, tmp_path / "lieux" / "demo")
    app = creer_app(ros=False)
    with TestClient(app) as c:
        c.app_atelier = app
        yield c


ROUTES_V6 = [("get", "/api/robot/diagnostic"), ("get", "/api/robot/diagnostic?mode=repetition&rapide=1"),
             ("get", "/api/robot/diagnostic/dernier"), ("post", "/api/robot/diagnostic/demarrer-services"),
             ("post", "/api/robot/diagnostic/eteindre"), ("get", "/api/seance"), ("post", "/api/seance/demarrer"),
             ("post", "/api/seance/arreter"), ("get", "/api/seances"), ("get", "/api/seances/2026-11-12_14h03"),
             ("get", "/api/seances/2026-11-12_14h03/rapport"), ("post", "/api/seances/2026-11-12_14h03/rapport"),
             ("get", "/api/seances/2026-11-12_14h03/fichiers/trajets.png"),
             ("get", "/api/seances/2026-11-12_14h03/export"), ("get", "/api/borne/etat"), ("post", "/api/borne/appui"),
             ("post", "/api/borne/choisir"), ("post", "/api/borne/annuler"), ("post", "/api/borne/operateur"),
             ("post", "/api/borne/operateur/pause"), ("get", "/api/borne/adresse"), ("get", "/api/demo/etat"),
             ("post", "/api/demo/lancer"), ("post", "/api/demo/arreter"), ("post", "/api/demo/commande"),
             ("get", "/api/lieux/demo/demo"), ("put", "/api/lieux/demo/demo"), ("get", "/api/voix/etat"),
             ("post", "/api/voix/demarrer"), ("post", "/api/voix/arreter"), ("post", "/api/voix/essayer"),
             ("post", "/api/voix/commande"), ("get", "/api/voix/son/s-1")]


def test_routes_de_la_vague_6_jamais_d_erreur_500(client):
    from atelier.serveur.communs import pas_encore_fait
    assert pas_encore_fait("un essai", "Diagnostic", "13.2").detail.startswith("Pas encore fait : un essai (vague 6")
    assert "(vague 5" in pas_encore_fait("un essai", "Scan", "12.4").detail
    for methode, url in ROUTES_V6:
        r = getattr(client, methode)(url, **({"json": {"mode": "repetition"}} if methode in ("post", "put") else {}))
        assert r.status_code < 500 or r.status_code in (501, 503), (url, r.status_code, r.text[:300])
        if r.status_code >= 400:
            assert r.json()["detail"], url
    r = client.get("/borne")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html") and 'data-role="borne"' in r.text
    with client.websocket_connect("/ws/borne") as ws:
        assert ws.receive_json()["detail"]
    with client.websocket_connect("/ws/etat") as ws:
        d = ws.receive_json()
    assert {"seance", "demo", "voix"} <= set(d) and d["seance"] is None and d["demo"] is None


def test_journal_des_actions(client):
    notes = []
    etat = client.app_atelier.state.atelier
    etat.seance.noter_action = notes.append
    sans_journal = client.post("/api/arret", json={"mode": "simu", "raison": "essai"})
    assert sans_journal.status_code == 200
    client.get("/api/arret")
    client.post("/api/simulation/teleop", json={"vx": 0.1, "vy": 0, "wz": 0})
    client.put("/api/lieux/demo/salles", content="pas du JSON", headers={"Content-Type": "application/json"})
    assert [(n["methode"], n["chemin"]) for n in notes] == [("POST", "/api/arret"), ("PUT", "/api/lieux/demo/salles")]
    arret = notes[0]
    assert arret["requete"] == {"mode": "simu", "raison": "essai"} and arret["statut"] == 200
    assert arret["reponse"]["arrete"] is True and arret["client"] == "local" and arret["duree_ms"] >= 0
    assert re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}[+-]\d\d:\d\d$", arret["t"])
    assert notes[1]["statut"] == 422 and notes[1]["requete"] == "pas du JSON"
    ligne = {"version": 1, "genre": "arret", "texte": "ARRÊT", "mode": "simu", "source": "atelier",
             **{k: arret[k] for k in ("t", "methode", "chemin", "requete", "statut", "reponse", "duree_ms", "client")}}
    assert L.valider_donnees("action_seance", ligne) == []

    def casse(action):
        raise RuntimeError("boîte noire en panne")
    etat.seance.noter_action = casse
    r = client.post("/api/arret", json={"mode": "simu"})
    assert r.status_code == 200 and r.json()["arrete"] is True
    gros = client.post("/api/robot/diagnostic/demarrer-services", content=b'{"x": "' + b"a" * 10000 + b'"}',
                       headers={"Content-Type": "application/json"})
    assert gros.status_code == 501


def test_journal_coupe_les_gros_corps():
    from atelier.serveur.main import JournalDesActions

    class Seance:
        def __init__(self):
            self.notes = []

        def noter_action(self, action):
            self.notes.append(action)

    class Etat:
        seance = Seance()

    async def application(scope, receive, send):
        corps = (await receive())["body"]
        await send({"type": "http.response.start", "status": 201, "headers": []})
        await send({"type": "http.response.body", "body": corps * 3})

    envoye = []

    async def recevoir():
        return {"type": "http.request", "body": b"x" * 10000, "more_body": False}

    async def envoyer(message):
        envoye.append(message)

    accroche = JournalDesActions(application, Etat())
    asyncio.run(accroche({"type": "http", "method": "POST", "path": "/api/essai", "client": ("127.0.0.1", 1)},
                         recevoir, envoyer))
    assert envoye[1]["body"] == b"x" * 30000                 # la réponse passe telle quelle
    note = Etat.seance.notes[0]
    assert note["statut"] == 201 and note["requete"].endswith(" […]") and len(note["requete"]) < 4200
    assert note["reponse"].endswith(" […]")


def test_garde_de_la_borne(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from atelier.serveur.main import client_local, creer_app, ecoute_reseau
    assert client_local("127.0.0.1") and client_local("::1") and client_local("::ffff:127.0.0.1")
    assert client_local("testclient") and not client_local("192.168.0.12")
    monkeypatch.setenv("ATELIER_LIEUX", str(tmp_path))
    monkeypatch.delenv("ATELIER_HOTE", raising=False)
    assert not ecoute_reseau()
    with TestClient(creer_app(ros=False), client=("192.168.1.20", 50000)) as c:
        assert c.get("/api/lieux").status_code == 200                   # n'écoute que ce PC : pas de garde
    monkeypatch.setenv("ATELIER_HOTE", "0.0.0.0")
    assert ecoute_reseau()
    app = creer_app(ros=False)
    with TestClient(app, client=("192.168.1.20", 50000)) as c:
        for chemin in ("/borne", "/css/theme.css", "/api/borne/etat"):
            assert c.get(chemin).status_code != 403, chemin
        for methode, chemin in (("get", "/"), ("get", "/api/lieux"), ("post", "/api/arret/debloquer"),
                                ("post", "/api/guide/aller"), ("get", "/index.html"), ("post", "/api/demo/lancer")):
            r = getattr(c, methode)(chemin)
            assert r.status_code == 403 and "borne" in r.json()["detail"], chemin
        from starlette.websockets import WebSocketDisconnect
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect("/ws/etat") as ws:
                ws.receive_json()
    with TestClient(app) as c:                                            # ce PC : tout l'Atelier
        assert c.get("/api/lieux").status_code == 200
    monkeypatch.setenv("ATELIER_DISTANT", "complet")
    with TestClient(creer_app(ros=False), client=("192.168.1.20", 50000)) as c:
        assert c.get("/api/lieux").status_code == 200
    texte = (RACINE / "bin" / "g1-atelier").read_text(encoding="utf-8")
    assert "--distant-complet" in texte and 'export ATELIER_HOTE="$HOTE" ATELIER_PORT="$PORT"' in texte


def test_appels_de_la_seance_par_le_serveur(tmp_path, monkeypatch):
    from atelier.seance import GestionnaireSeance
    from atelier.serveur.etat import EtatServeur
    etat = EtatServeur(ros=False)
    assert isinstance(etat.seance, GestionnaireSeance) and etat.seance.etat() is None and etat.seance_direct() is None
    ordre = []
    etat.seance.demarrage_serveur = lambda: ordre.append("demarrage")
    etat.seance.fermer = lambda fermeture: ordre.append(("fermer", fermeture))
    etat.gestionnaire.arreter_tout = lambda *a: ordre.append("processus")
    etat.demarrer()
    etat.arreter()
    assert ordre == ["demarrage", ("fermer", "arret_atelier"), "processus"]

    def casse(*a):
        raise RuntimeError("panne")
    etat.seance.demarrage_serveur = etat.seance.fermer = etat.seance.etat = casse
    etat.demarrer()
    etat.arreter()
    assert etat.seance_direct() is None and etat.etat_direct()["seance"] is None
    with pytest.raises(NotImplementedError):
        GestionnaireSeance().demarrer("reel")
    assert GestionnaireSeance().noter_action({"chemin": "/api/arret"}) is None


def test_journal_du_jetson_avant_g1_jetson_arreter(tmp_path, monkeypatch):
    """L'arrêt de la navigation du robot appelle la boîte noire avant g1-jetson arreter (accroche de 13.3)."""
    from fastapi.testclient import TestClient
    from atelier.serveur.main import creer_app
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    trace = tmp_path / "trace.txt"
    faux = bin_ / "g1-jetson"
    faux.write_text(f'#!/bin/sh\necho "g1-jetson $*" >> {trace}\n', encoding="utf-8")
    faux.chmod(faux.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("ATELIER_BIN", str(bin_))
    monkeypatch.setenv("ATELIER_LIEUX", str(tmp_path / "lieux"))
    app = creer_app(ros=False)
    with TestClient(app) as c:
        etat = app.state.atelier
        etat.simulation = {"lieu": "demo", "etage": "rdc", "dossier": "", "monde": None, "debut": 0.0,
                           "mode": "robot", "en_cours": True, "avertissements": []}
        etat.seance.avant_arret_jetson = lambda local=False: trace.open("a").write(f"journal local={local}\n")
        assert c.post("/api/simulation/arreter").status_code == 200
    assert trace.read_text(encoding="utf-8").splitlines() == ["journal local=False", "g1-jetson arreter"]


def test_pont_ros_de_la_vague_6():
    from atelier.serveur.pont_ros import PUBLICATIONS_JSON, SUJETS_JSON, PontRos
    assert {"/accueil/etat", "/accueil/evenement", "/voix/etat", "/voix/son"} <= set(SUJETS_JSON)
    assert SUJETS_JSON["/accueil/evenement"][0] >= 50
    assert {"/accueil/choix", "/accueil/commande", "/voix/commande"} <= set(PUBLICATIONS_JSON)
    pont = PontRos()
    assert pont.sujets() == {} and pont.infos_sujet("/api/sport/request") is None
    for service, api in (("sport", 7105), ("sport", 7101), ("robot_state", 1002), ("voice", 1003), ("arm", 7106)):
        with pytest.raises(PermissionError):
            pont.appeler_unitree(service, api, "{}")
    with pytest.raises(RuntimeError):
        pont.appeler_unitree("robot_state", 1003)            # permis, mais pas de pont ROS 2
    with pytest.raises(RuntimeError):
        pont.attendre_message("/lf/bmsstate", "unitree_hg/msg/BmsState")


# ---------------------------------------------------------------- interface web

EXPORTS_V6 = {
    "coque/diagnostic.js": {"ETATS_VERIFICATION", "monterDiagnosticAccueil", "monterDiagnosticBarre",
                            "ouvrirDiagnostic", "executer"},
    "coque/seance.js": {"surEspace", "monterSeanceBarre", "executer"},
    "coque/coque.js": {"outilsCoque", "ouvrirCommande"},
    "ecrans/demo.js": {"ouvrir"},
    "borne/borne.js": {"demarrerBorne", "ECRANS_BORNE"},
}


@pytest.mark.parametrize("module", sorted(EXPORTS_V6))
def test_modules_et_exports(module):
    chemin = WEB / "js" / module
    assert chemin.is_file()
    assert EXPORTS_V6[module] <= _exports(chemin), EXPORTS_V6[module] - _exports(chemin)


def test_registre_et_points_d_accroche():
    from atelier.tests.test_coque import _registre, _table
    commandes = {x["id"]: x for x in _registre()[0]}
    attendu = {"robot.verifier": (["reel"], "naviguer", "diagnostic"), "seance.terminer": (["reel"], "naviguer", "seance"),
               "seance.rapport": (["reel"], "naviguer", "seance"), "demo.lancer": (["simu", "reel"], "equipe", None),
               "demo.arreter": (["simu", "reel"], "equipe", None), "demo.borne": (["simu", "reel"], "equipe", None),
               "demo.reglages": (["simu", "reel"], "equipe", None)}
    for ident, (modes, onglet, module) in attendu.items():
        x = commandes[ident]
        assert (x["modes"], x["onglet"], x.get("module")) == (modes, onglet, module), ident
        assert x["ecran"] == (None if module else "demo"), ident
    assert commandes["seance.terminer"]["avance"] and commandes["demo.reglages"]["avance"]
    assert not commandes["robot.verifier"]["avance"] and commandes["robot.verifier"]["groupe"] == "robot"
    coque = WEB / "js" / "coque" / "coque.js"
    assert _table(coque, "MODULES_COQUE") == {"diagnostic": {"fichier": "diagnostic.js", "titre": "Vérifier le robot"},
                                              "seance": {"fichier": "seance.js", "titre": "Séance"}}
    assert _table(coque, "ECRANS")["demo"]["vues"] == ["3d", "plan", "camera"]
    texte = coque.read_text(encoding="utf-8")
    for repere in ("'zone-diagnostic'", "'zone-seance'", "seanceSurEspace(outilsCoque())", "monterDiagnosticBarre",
                   "monterSeanceBarre", "if (cmd.module)"):
        assert repere in texte, repere
    accueil = (WEB / "js" / "coque" / "accueil.js").read_text(encoding="utf-8")
    assert "'zone-diagnostic-accueil'" in accueil and "monterDiagnosticAccueil(zone" in accueil
    index = (WEB / "index.html").read_text(encoding="utf-8")
    for css in ("diagnostic", "seance", "demo"):
        assert f'href="css/{css}.css"' in index and (WEB / "css" / f"{css}.css").is_file()
    assert (WEB / "css" / "borne.css").is_file() and 'href="css/borne.css"' not in index


def test_feuilles_de_la_vague_6_avec_les_seuls_jetons_du_theme():
    """Les feuilles des agents de la vague 6 n'écrivent aucune couleur en dur, ni 100vh, ni un jeton inconnu."""
    definis = set(re.findall(r"--([a-z0-9-]+)\s*:", (WEB / "css" / "theme.css").read_text(encoding="utf-8")))
    problemes = []
    for nom in ("diagnostic", "seance", "demo", "borne"):
        texte = re.sub(r"/\*.*?\*/", "", (WEB / "css" / f"{nom}.css").read_text(encoding="utf-8"), flags=re.S)
        locaux = set(re.findall(r"--([a-z0-9-]+)\s*:", texte))
        problemes += [f"{nom}.css : couleur en dur {c}" for c in re.findall(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", texte)]
        problemes += [f"{nom}.css : 100vh" for _ in re.findall(r"\b100d?vh\b", texte)]
        problemes += [f"{nom}.css : jeton --{j} inconnu" for j in re.findall(r"var\(--([a-z0-9-]+)\)", texte)
                      if j not in definis | locaux]
    assert problemes == []


def test_page_de_la_borne_ne_charge_que_ce_qui_est_permis():
    page = (WEB / "borne.html").read_text(encoding="utf-8")
    liens = re.findall(r'(?:src|href)="([^"]+)"', page)
    assert liens and all(A.chemin_permis_borne(x) for x in liens), liens
    assert "window.erreursBorne" in page and 'data-role="borne"' in page
    for module in (WEB / "js" / "borne").glob("*.js"):
        sources = re.findall(r"""(?:from\s+|import\(\s*)['"]([^'"]+)['"]""", module.read_text(encoding="utf-8"))
        assert all(s.startswith("./") and ".." not in s for s in sources), (module.name, sources)


# ---------------------------------------------------------------- faux G1, g1_accueil, commandes

def _faux_g1():
    sys.path.insert(0, str(JUMEAU))
    try:
        from g1_jumeau.logique import FauxSport
        from g1_jumeau.robot import FauxG1
    finally:
        sys.path.remove(str(JUMEAU))
    return FauxG1(FauxSport(horloge=lambda: 10.0), services_arretes=("lidar_driver",))


def test_faux_g1_voix_d_avant_et_robot_state():
    g1 = _faux_g1()
    assert g1.traiter("voice", 1001, json.dumps({"index": 1, "speaker_id": 0, "text": "Bonjour"})) == (0, "")
    assert g1.traiter("voice", 1006, json.dumps({"volume": 55})) == (0, "")
    assert json.loads(g1.traiter("voice", 1005, "{}")[1]) == {"volume": 55}
    assert g1.traiter("voice", 1010, json.dumps({"R": 1, "G": 2, "B": 3})) == (0, "")
    assert g1.traiter("voice", 1003, V.parametre_lecture("s-1"), b"\x00\x00" * 10) == (0, "")
    assert g1.led == {"R": 1, "G": 2, "B": 3} and g1.tts["text"] == "Bonjour" and g1.volume == 55
    voix = g1.etat()["voix"]
    assert {"tts", "tts_nombre", "volume", "led", "led_historique"} <= set(voix)
    assert g1.traiter("robot_state", 1003, "{}")[0] in (0, 3203)
    assert "services" in g1.etat() and g1.requetes["robot_state"] == 1
    assert g1.etat_robot.arretes == ("lidar_driver",)
    g1.sport.changer_panne("muet")
    assert g1.traiter("robot_state", 1003, "{}") is None and g1.traiter("voice", 1003, "{}", b"\x00\x00") is None
    noeud = (JUMEAU / "g1_jumeau" / "jumeau.py").read_text(encoding="utf-8")
    for repere in ("'robot_state'", "'services_arretes'", "G1_JUMEAU_SERVICES_ARRETES", "/g1_jumeau/services",
                   "bytes(msg.binary)"):
        assert repere in noeud, repere
    for fichier in ("audio.py", "etat_robot.py"):
        assert (JUMEAU / "g1_jumeau" / fichier).is_file()


def test_paquet_g1_accueil_et_commandes():
    assert "'accueil = g1_accueil.noeud:main'" in (ACCUEIL / "setup.py").read_text(encoding="utf-8")
    assert "<name>g1_accueil</name>" in (ACCUEIL / "package.xml").read_text(encoding="utf-8")
    for f in ("resource/g1_accueil", "setup.cfg", "g1_accueil/__init__.py", "g1_accueil/noeud.py",
              "g1_accueil/logique.py", "test/test_flake8.py", "test/test_pep257.py", "LISEZMOI.md"):
        assert (ACCUEIL / f).exists(), f
    for nom in ("g1-diagnostic", "g1-seance", "g1-accueil", "g1-voix"):
        chemin = RACINE / "bin" / nom
        assert chemin.is_file() and os.access(chemin, os.X_OK), nom
        alias = RACINE / "bin" / nom.replace("g1-", "gl-", 1)
        assert alias.is_symlink() and os.readlink(alias) == nom, alias
    for module in ("diagnostic", "seance", "voix"):
        assert f"-m atelier.{module}" in (RACINE / "bin" / f"g1-{module}").read_text(encoding="utf-8")
    with pytest.raises(NotImplementedError):
        from atelier.diagnostic import diagnostiquer
        diagnostiquer()
    assert "g1_accueil" in (RACINE / "tests_e2e" / "commun.sh").read_text(encoding="utf-8")


# ---------------------------------------------------------------- plan, recette et propriétaires

def _section_13():
    plan = PLAN.read_text(encoding="utf-8")
    titre = "## 13. Diagnostic, boîte noire et démo d'accueil (vague 6)"
    assert titre in plan
    return plan, plan[plan.index(titre):]


def test_plan_section_13():
    plan, s13 = _section_13()
    for titre in ("### 13.1 Les décisions et qui les réalise", "### 13.2 Le diagnostic (agent Diagnostic)",
                  "### 13.3 La boîte noire et le rapport de séance (agent Boîte noire)",
                  "### 13.4 La démo d'accueil : le nœud accueil (agent Borne et orchestrateur)",
                  "### 13.5 La borne visiteur (agent Borne et orchestrateur)", "### 13.6 La voix du robot (agent Voix)",
                  "### 13.7 L'interface", "### 13.8 Les routes nouvelles", "### 13.9 Critères de recette 37 à 42",
                  "### 13.10 Ce qui reste à vérifier sur le robot", "### 13.11 Les agents de la vague 6",
                  "### 13.12 Dépendances entre agents"):
        assert titre in s13, titre
    for mot in ("ServiceList", "ServiceSwitch", "/api/robot_state/request", "status 0 = actif", "lidar_driver",
                "unitree_slam", "ATELIER_DIAGNOSTIC_FAUX", "g1-diagnostic", "nmcli connection up robot-g1",
                "seance.json", "actions.jsonl", "SUJETS_SEANCE", "place_libre_min_go", "ros2 bag reindex",
                "avant_arret_jetson", "g1-seance", "rapport.json", "trajets.png", "mouvement sans demande",
                "/accueil/etat", "/accueil/choix", "/accueil/commande", "/accueil/evenement", "source: dialogue",
                "pause", "reprendre", "ramener", "hors_borne", "code_operateur", "X-Jeton-Borne", "GardeBorne",
                "--distant-complet", "/borne", "/ws/borne", "1003 START_PLAY", "1004 STOP_PLAY", "96 000 octets",
                "16 000 Hz", "robot_tts", "/voix/son", "securite", "robot.verifier", "zone-diagnostic-accueil",
                "outilsCoque", "surEspace", "390 × 844", "1024 × 768", "N / 42"):
        assert mot in s13, mot
    for n in range(37, 43):
        assert re.search(rf"^{n}\. \*\*", s13, re.M), f"critère {n} absent de la section 13"
    assert "section 13 en entier" in plan[:plan.index("## 1. Le but")]


def test_exemples_du_plan_conformes():
    """Les exemples JSON de la section 13 sont conformes à un des schémas de la vague 6."""
    _, s13 = _section_13()
    blocs = [json.loads(b) for b in re.findall(r"```json\n(.*?)```", s13, re.S)]
    assert blocs
    for b in blocs:
        assert any(L.valider_donnees(nom, b) == [] for nom in NOUVEAUX), b


def test_tout_sh_compte_42_criteres():
    tout = TOUT.read_text(encoding="utf-8")
    assert re.search(r"^TOUS=\(" + " ".join(str(n) for n in range(1, 43)) + r"\)$", tout, re.M)
    assert "N / 42" in tout
    for n in range(37, 43):
        assert re.search(rf"\[{n}\]=\d+", tout), f"délai du critère {n}"
    lisez = (RACINE / "tests_e2e" / "LISEZMOI.md").read_text(encoding="utf-8")
    for n in range(37, 43):
        assert re.search(rf"`critere_{n}_[a-z_]+\.sh`", lisez), n


def test_table_des_proprietaires_sans_recouvrement():
    """Aucun chemin (dossier, fichier ou motif) de la table 13.11 n'est à deux agents."""
    _, s13 = _section_13()
    table = s13[s13.index("### 13.11"):s13.index("### 13.12")]
    lignes = [x for x in table.splitlines() if x.startswith("| ") and not x.startswith("| Agent") and "---" not in x]
    assert len(lignes) == 5
    agents = {}
    for ligne in lignes:
        cellules = ligne.split(" | ")
        agents[cellules[0].strip("| ").strip()] = (_revendications(cellules[2]), cellules[1])
    for agent, domaine in (("Diagnostic", 141), ("Boîte noire", 142), ("Borne et orchestrateur", 143), ("Voix", 144)):
        assert str(domaine) in agents[agent][1] and "`v6_" in agents[agent][1] and str(8000 + domaine) in agents[agent][1]
    conflits = []
    noms = sorted(agents)
    for i, a in enumerate(noms):
        (chemins_a, sauf_a), _ = agents[a]
        for b in noms[i + 1:]:
            (chemins_b, sauf_b), _ = agents[b]
            for x in chemins_a:
                for y in chemins_b:
                    if _se_recouvrent(x, y) and y not in sauf_a and x not in sauf_b:
                        conflits.append((a, x, b, y))
    assert conflits == []
    proprietaire = {c: n for n, ((chemins, _), _) in agents.items() for c in chemins}
    for chemin, agent in (("atelier/diagnostic/", "Diagnostic"), ("atelier/web/js/coque/diagnostic.js", "Diagnostic"),
                          ("ws/src/g1_jumeau/g1_jumeau/etat_robot.py", "Diagnostic"), ("atelier/seance/", "Boîte noire"),
                          ("atelier/web/js/coque/seance.js", "Boîte noire"), ("ws/src/g1_accueil/", "Borne"),
                          ("atelier/web/js/borne/", "Borne"), ("atelier/web/js/ecrans/demo.js", "Borne"),
                          ("atelier/serveur/routes/borne.py", "Borne"), ("atelier/voix/", "Voix"),
                          ("ws/src/g1_jumeau/g1_jumeau/audio.py", "Voix"), ("atelier/serveur/main.py", "Contrats"),
                          ("atelier/web/js/coque/ruban.js", "Contrats"), ("tests_e2e/tout.sh", "Contrats"),
                          ("ws/src/g1_jumeau/g1_jumeau/jumeau.py", "Contrats"), ("atelier/lieu/", "Contrats")):
        assert proprietaire[chemin].startswith(agent), (chemin, proprietaire[chemin])
    # les fichiers livrés par les contrats existent tous
    for (chemins, _), _ in agents.values():
        for c in chemins:
            if not any(x in c for x in "*?[") and "critere_" not in c and "outils_" not in c and "test_" not in c:
                assert (RACINE / c.rstrip("/")).exists() or c.startswith("docs/word"), c


def test_lieux_existants_toujours_valides():
    for nom in ("demo", "seance", "bomboclat", "demo_scan"):
        dossier = RACINE / "lieux" / nom
        if not (dossier / "lieu.yaml").is_file():
            continue
        r = L.valider_lieu(dossier)
        assert not [m for m in r.erreurs if "demo.yaml" in m], nom
    assert L.valider_lieu(DEMO).ok
