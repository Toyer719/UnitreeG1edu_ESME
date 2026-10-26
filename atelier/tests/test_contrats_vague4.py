"""Tests des contrats de la vague 4 (agent Intégrateur, section 11 du plan).

  ~/robot-g1/.venv-projet/bin/python -m pytest ~/robot-g1/atelier/tests/test_contrats_vague4.py -v

Vérifie que :
  - les nouveaux schémas (fichiers de l'équipe, scènes, chorégraphies, messages JSON) sont des
    schémas draft-07 valides, que leurs exemples sont conformes, et qu'atelier.lieu et jsonschema
    rendent le même verdict sur des centaines de variantes ;
  - A : la règle « un seul point principal par lieu, obligatoire », le principal implicite des
    lieux d'avant, les fonctions de atelier.lieu.principal ; les lieux existants ne changent pas ;
  - B : les champs du piéton crédible, la distance bord à bord et la cause d'un contact ;
  - C : états, événements, délais et demandes du guide ;
  - D : commandes permises et interdites, danses, limites des bras, chorégraphie d'exemple ;
  - E : les trois fichiers de l'équipe ;
  - les squelettes partagés (onglets, routes, paquets, nœuds) existent, la section 11 du plan est
    là, les critères 21 à 30 sont dans la section 7 et tout.sh en compte 30 ; aucun fichier de la
    table 11.7 n'a deux propriétaires.
"""
import copy
import json
import math
import random
import re
import xml.etree.ElementTree as ET

import jsonschema
import pytest
import yaml

import atelier
from atelier import lieu as L
from atelier.lieu import comportement as C
from atelier.lieu import equipe as E
from atelier.lieu import passants as B
from atelier.lieu import pilotage as D
from atelier.lieu import principal as A
from atelier.lieu.validation import erreurs_schema
from atelier.tests.test_lieu_validation import MUTATIONS, _chemins, _muter

RACINE = atelier.RACINE
DOSSIER_SCHEMAS = RACINE / "atelier" / "lieu" / "schemas"
DEMO = RACINE / "lieux" / "demo"
PLAN = RACINE / "docs" / "plan-atelier-multi-agents.md"
TOUT = RACINE / "tests_e2e" / "tout.sh"
URDF = (RACINE / "third_party" / "unitree_rl_gym" / "resources" / "robots" / "g1_description"
        / "g1_29dof_rev_1_0.urdf")

NOUVEAUX_FICHIERS = ("personnalites", "dialogues", "camera", "scene", "choregraphie")
NOUVEAUX_MESSAGES = ("etat_guide", "evenement_guide", "demande_guide", "pietons_etat", "pietons_consigne",
                     "personnes", "maitre_mouvement", "etat_pilotage", "robot_dire", "personnalite_active",
                     "robot_geste")

EXEMPLE_SCENE = {
    "version": 1, "id": "immobile_couloir", "nom": "Passant immobile au milieu du couloir nord", "lieu": "demo",
    "etage": "rdc",
    "pietons": [{"id": "passant", "trajet": [[12.0, 13.0], [12.5, 13.0]], "vitesse": 1.0, "aller_retour": True,
                 "reaction": "aucune", "pauses": [{"point": 0, "duree_s": 3600}]}],
    "trajets": [["accueil", "b204"]], "essais": 5,
    "mesures": {"reussite_min": 1.0, "distance_bord_min_m": 0.2, "contacts_robot_max": 0, "detours_max": 0,
                "duree_max_s": 180}}


def schema(nom):
    return json.loads((DOSSIER_SCHEMAS / f"{nom}.schema.json").read_text(encoding="utf-8"))


def erreurs_js(nom, donnees):
    return [e.message for e in jsonschema.Draft7Validator(schema(nom)).iter_errors(donnees)]


def modifie(exemple, changement):
    donnees = copy.deepcopy(exemple)
    changement(donnees)
    return donnees


def exemples():
    """Un exemple conforme de chaque nouveau type."""
    return {
        "personnalites": E.exemple_equipe("personnalites"), "dialogues": E.exemple_equipe("dialogues"),
        "camera": E.exemple_equipe("camera"), "scene": EXEMPLE_SCENE,
        "choregraphie": D.charger_choregraphie("exemple_kpop"),
        "etat_guide": C.EXEMPLE_ETAT_GUIDE, "evenement_guide": C.EXEMPLE_EVENEMENT,
        "demande_guide": C.EXEMPLE_DEMANDE_ALLER, "pietons_etat": B.EXEMPLE_PIETONS_ETAT,
        "pietons_consigne": B.EXEMPLE_CONSIGNE, "personnes": C.EXEMPLE_PERSONNES,
        "maitre_mouvement": D.EXEMPLE_MAITRE, "etat_pilotage": D.EXEMPLE_ETAT_PILOTAGE,
        "robot_dire": E.EXEMPLE_ROBOT_DIRE, "personnalite_active": E.EXEMPLE_PERSONNALITE_ACTIVE,
        "robot_geste": E.message_robot_geste(26, "personnalite", raison="salutation")}


@pytest.fixture
def demo(tmp_path):
    return L.charger_lieu(L.copier_lieu(DEMO, tmp_path / "demo"))


# ---------------------------------------------------------------- schémas et exemples

@pytest.mark.parametrize("nom", NOUVEAUX_FICHIERS + NOUVEAUX_MESSAGES + ("salles", "lieu", "monde", "etat_pont"))
def test_schema_draft07_valide(nom):
    s = schema(nom)
    assert s["$schema"] == "http://json-schema.org/draft-07/schema#"
    jsonschema.Draft7Validator.check_schema(s)
    assert nom in L.TYPES_FICHIERS


@pytest.mark.parametrize("nom", NOUVEAUX_FICHIERS + NOUVEAUX_MESSAGES)
def test_exemples_conformes(nom):
    d = exemples()[nom]
    assert erreurs_js(nom, d) == []
    assert L.valider_donnees(nom, d) == []


@pytest.mark.parametrize("nom", NOUVEAUX_MESSAGES)
def test_valider_message_connait_les_messages(nom):
    assert nom in L.TYPES_MESSAGES
    assert L.valider_message(nom, exemples()[nom]) == []


@pytest.mark.parametrize("nom", NOUVEAUX_FICHIERS + NOUVEAUX_MESSAGES)
def test_meme_verdict_que_jsonschema(nom):
    """Sur des centaines de variantes des exemples, atelier.lieu et jsonschema sont d'accord."""
    exemple = exemples()[nom]
    validateur = jsonschema.Draft7Validator(schema(nom))
    cas = [(c, m) for c in _chemins(exemple) for m in MUTATIONS]
    random.Random(4).shuffle(cas)
    desaccords = []
    for chemin, mutation in cas[:500]:
        variante = _muter(exemple, chemin, mutation)
        nous = bool(erreurs_schema(nom, variante))
        eux = any(True for _ in validateur.iter_errors(variante))
        if nous != eux:
            desaccords.append((chemin, mutation, nous, eux))
    assert desaccords == []


REFUS_SCHEMA = {
    "personnalité sans salutation": ("personnalites", lambda d: d["personnalites"][0].pop("salutation")),
    "phrase d'un code inconnu": ("personnalites", lambda d: d["personnalites"][0]["phrases"].update(bonjour="x")),
    "LED à 300": ("personnalites", lambda d: d["personnalites"][0]["led"].update(r=300)),
    "vitesse au-delà du pont": ("personnalites", lambda d: d["personnalites"][1].update(vitesse_max=0.5)),
    "geste 99 pour saluer": ("personnalites", lambda d: d["personnalites"][0].update(geste_salut=99)),
    "règle sans motif": ("dialogues", lambda d: d["regles"][0].update(motifs=[])),
    "action inconnue": ("dialogues", lambda d: d["regles"][0].update(action="danser")),
    "sans repli": ("dialogues", lambda d: d.pop("repli")),
    "périphérique hors de /dev": ("camera", lambda d: d["camera"].update(peripherique="video0")),
    "confiance à 2": ("camera", lambda d: d["detection"].update(confiance_min=2)),
    "scène sans trajets": ("scene", lambda d: d.pop("trajets")),
    "trajet à trois points": ("scene", lambda d: d["trajets"].append(["a", "b", "c"])),
    "chorégraphie sans zone libre": ("choregraphie", lambda d: d.pop("zone_libre_m")),
    "zone libre de 1 m": ("choregraphie", lambda d: d.update(zone_libre_m=1.0)),
    "articulation inconnue": ("choregraphie", lambda d: d["bras"]["poses"][0]["q"].update(left_knee=0.1)),
    "pas trop rapide": ("choregraphie", lambda d: d["pas"][0].update(vy=0.5)),
    "musique dans un dossier": ("choregraphie", lambda d: d["musique"].update(fichier="../chanson.mp3")),
    "geste 5": ("choregraphie", lambda d: d.update(gestes=[{"t": 1.0, "action": 5}])),
    "guide : état inconnu": ("etat_guide", lambda d: d.update(etat="danse")),
    "guide : mission inconnue": ("etat_guide", lambda d: d.update(mission="promenade")),
    "événement : code inconnu": ("evenement_guide", lambda d: d.update(code="chanter")),
    "événement : texte vide": ("evenement_guide", lambda d: d.update(texte="")),
    "demande : cible avec espace": ("demande_guide", lambda d: d.update(cible="salle b204")),
    "demande : champ inconnu": ("demande_guide", lambda d: d.update(vitesse=1.0)),
    "piétons : état inconnu": ("pietons_etat", lambda d: d["pietons"][0].update(etat="court")),
    "consigne trop rapide": ("pietons_consigne", lambda d: d.update(vx=2.0)),
    "personnes : source inconnue": ("personnes", lambda d: d.update(source="radar")),
    "personnes : confiance négative": ("personnes", lambda d: d["personnes"][0].update(confiance=-0.1)),
    "maître inconnu": ("maitre_mouvement", lambda d: d.update(maitre="atelier")),
    "pilotage : activité inconnue": ("etat_pilotage", lambda d: d.update(activite="saut")),
    "dire : texte vide": ("robot_dire", lambda d: d.update(texte="")),
    "personnalité active sans nom": ("personnalite_active", lambda d: d.pop("nom")),
}


@pytest.mark.parametrize("cas", list(REFUS_SCHEMA))
def test_schema_refuse(cas):
    nom, changement = REFUS_SCHEMA[cas]
    donnees = modifie(exemples()[nom], changement)
    assert erreurs_js(nom, donnees), f"jsonschema aurait dû refuser : {cas}"
    assert L.valider_donnees(nom, donnees), f"atelier.lieu aurait dû refuser : {cas}"


def test_etat_pont_pilotage():
    d = dict(L.EXEMPLE_ETAT_PONT, etat="pilotage", mouvement_permis=False, consigne={"vx": 0.0, "vy": 0.0, "wz": 0.0})
    assert L.valider_message("etat_pont", d) == [] and erreurs_js("etat_pont", d) == []
    assert any("mouvement_permis" in m for m in L.valider_message("etat_pont", dict(d, mouvement_permis=True)))
    assert tuple(schema("etat_pont")["properties"]["etat"]["enum"]) == L.ETATS_PONT
    assert L.ETATS_PONT[-1] == "pilotage"


def test_les_enumerations_des_schemas_suivent_les_modules():
    assert tuple(schema("etat_guide")["properties"]["etat"]["enum"]) == C.ETATS_GUIDE
    codes = list(C.CODES_EVENEMENT)
    assert schema("evenement_guide")["properties"]["code"]["enum"] == codes
    phrases = schema("personnalites")["definitions"]["personnalite"]["properties"]["phrases"]
    assert phrases["propertyNames"]["enum"] == codes
    q = schema("choregraphie")["properties"]["bras"]["properties"]["poses"]["items"]["properties"]["q"]
    assert q["propertyNames"]["enum"] == list(D.ARTICULATIONS_BRAS)
    gestes = schema("choregraphie")["properties"]["gestes"]["items"]["properties"]["action"]["enum"]
    assert sorted(gestes) == sorted(D.GESTES_BRAS)
    salut = schema("personnalites")["definitions"]["personnalite"]["properties"]["geste_salut"]["enum"]
    assert sorted(salut) == sorted(set(D.GESTES_BRAS) - {D.GESTE_RELACHER})
    pas = schema("choregraphie")["properties"]["pas"]["items"]["properties"]
    assert {a: pas[a]["maximum"] for a in ("vx", "vy", "wz")} == D.LIMITES_PAS
    assert (pas["duree_s"]["minimum"], pas["duree_s"]["maximum"]) == D.DUREE_PAS_S
    pieton = schema("monde")["definitions"]["pieton"]["properties"]
    assert tuple(pieton["reaction"]["enum"]) == B.REACTIONS and tuple(pieton["pilote"]["enum"]) == B.PILOTES
    assert tuple(schema("pietons_etat")["properties"]["pietons"]["items"]["properties"]["etat"]["enum"]) == \
        B.ETATS_PIETON
    guide = schema("lieu")["properties"]["guide"]["properties"]
    assert set(guide) == set(C.DELAIS_GUIDE)
    assert tuple(schema("dialogues")["definitions"]["regle"]["properties"]["action"]["enum"]) == E.ACTIONS_DIALOGUE


# ---------------------------------------------------------------- A. point principal

def test_les_lieux_existants_restent_valides_et_inchanges(tmp_path):
    """Le demo (référence) : aucun avertissement de plus, et enregistré tel quel, salles.yaml n'a pas
    d'étiquette (le format implicite reste)."""
    rapport = L.valider_lieu(DEMO)
    assert rapport.erreurs == [] and rapport.avertissements == []
    copie = L.copier_lieu(DEMO, tmp_path / "demo")
    L.enregistrer_lieu(L.charger_lieu(copie))
    assert "etiquettes" not in (copie / "salles.yaml").read_text(encoding="utf-8")
    assert "guide" not in yaml.safe_load((copie / "lieu.yaml").read_text(encoding="utf-8"))
    monde = yaml.safe_load((copie / "mondes" / "rdc.monde.yaml").read_text(encoding="utf-8"))
    assert all(set(p) == {"id", "trajet", "vitesse", "aller_retour"} for p in monde["pietons"])
    for lieu in ("demo_scan", "bomboclat"):
        if (RACINE / "lieux" / lieu / "lieu.yaml").is_file():
            L.charger_lieu(RACINE / "lieux" / lieu)        # se lit toujours


def test_principal_implicite_du_demo():
    assert not A.principal_explicite(DEMO)
    p = A.point_principal(DEMO)
    assert p.id == "accueil" and A.accueil_conforme(DEMO)
    assert A.pose_principale(DEMO) == L.PoseEtage("rdc", 2.5, 10.0, 0.0)
    assert A.pose_de_reperage(DEMO, "rdc") == L.Pose(2.5, 10.0, 0.0)
    assert A.depart_simulation(DEMO, "rdc") == L.Pose(2.5, 10.0, 0.0)


def test_principal_explicite_sur_une_autre_salle(demo):
    b204 = demo.salle("b204")
    b204.etiquettes = [L.ETIQUETTE_PRINCIPAL, "salle_de_classe"]
    assert A.point_principal(demo) is b204 and A.principal_explicite(demo)
    # accueil de lieu.yaml n'a pas suivi : erreur de la vérification
    assert any("car c'est le point principal" in m for m in L.verifier_lieu(demo).erreurs)
    demo.accueil = L.PoseEtage("rdc", b204.pose.x, b204.pose.y, b204.pose.theta)
    rapport = L.verifier_lieu(demo)
    assert rapport.erreurs == []
    # depart_robot n'est pas sur le principal : un avertissement
    assert any("depart_robot" in m and "point principal" in m for m in rapport.avertissements)
    demo.mondes["rdc"].depart_robot = L.Pose(b204.pose.x, b204.pose.y, b204.pose.theta)
    assert not any("depart_robot" in m for m in L.verifier_lieu(demo).avertissements)
    assert A.pose_de_reperage(demo, "rdc") == L.Pose(21.0, 13.0, 1.5708)


def test_sans_principal_erreur(demo):
    demo.salles = [s for s in demo.salles if s.id != "accueil"]
    assert any("pas de point principal" in m for m in L.verifier_lieu(demo).erreurs)
    assert A.point_principal(demo) is None and A.pose_de_reperage(demo, "rdc") == L.marque_au_sol(demo.dossier, "rdc")


def test_deux_principaux_refuses(demo):
    for s in demo.salles[:2]:
        s.etiquettes = [L.ETIQUETTE_PRINCIPAL]
    donnees = [s.vers_dict() for s in demo.salles]
    assert any("un lieu n'a qu'un point principal" in m for m in L.valider_donnees("salles", donnees))
    assert A.point_principal(demo) is None
    assert any("2 salles portent l'étiquette" in m for m in L.verifier_lieu(demo).erreurs)
    with pytest.raises(L.ErreurLieu):
        L.enregistrer_salles(demo.dossier, demo.salles)


def test_etiquettes_aller_retour_et_doublon():
    s = L.Salle("hall", "Hall", "rdc", L.Pose(1.0, 2.0, 0.5), etiquettes=["principal", "sortie"])
    d = s.vers_dict()
    assert d["etiquettes"] == ["principal", "sortie"] and L.Salle.depuis_dict(d) == s and s.principale
    assert "etiquettes" not in L.Salle("b", "B", "rdc", L.Pose(0, 0, 0)).vers_dict()
    assert L.valider_donnees("salles", [dict(d, etiquettes=["principal", "principal"])])
    assert L.valider_donnees("salles", [dict(d, etiquettes=["Principal"])])


def test_un_lieu_neuf_a_son_principal(tmp_path):
    lieu = L.creer_lieu(tmp_path / "neuf", "Lieu neuf")
    assert A.principal_explicite(lieu) and A.point_principal(lieu).id == "accueil"
    rapport = L.valider_lieu(tmp_path / "neuf")
    assert rapport.erreurs == [] and not any("point principal" in m for m in rapport.avertissements)


# ---------------------------------------------------------------- B. passants

def test_pieton_credible_aller_retour_et_defauts():
    p = L.Pieton("h1", [(1.0, 1.0), (5.0, 1.0)], 0.8, False, reaction="arret", distance_reaction_m=1.2, corps=True,
                 rayon_m=0.3, pauses=[{"point": 1, "duree_s": 5.0}], depart_s=2.0, repeter=False, pilote="trajet")
    d = p.vers_dict()
    assert L.Pieton.depuis_dict(d) == p
    monde = {"version": 1, "emprise": {"min": [0, 0], "max": [10, 10]}, "pietons": [d],
             "depart_robot": {"x": 0.5, "y": 0.5, "theta": 0.0}}
    assert L.valider_donnees("monde", monde) == [] and erreurs_js("monde", monde) == []
    vieux = L.Pieton("h2", [(1.0, 1.0), (5.0, 1.0)])
    assert set(vieux.vers_dict()) == {"id", "trajet", "vitesse", "aller_retour"}
    assert B.reglages_pieton(vieux) == B.DEFAUTS_PIETON
    assert B.reglages_pieton(d)["reaction"] == "arret" and B.reglages_pieton(d)["pauses"] == [{"point": 1, "duree_s": 5.0}]


def test_pauses_hors_du_trajet_refusees():
    def monde(pauses):
        return {"version": 1, "emprise": {"min": [0, 0], "max": [10, 10]},
                "pietons": [{"id": "h", "trajet": [[1, 1], [2, 1]], "vitesse": 1.0, "aller_retour": True,
                             "pauses": pauses}], "depart_robot": {"x": 0.5, "y": 0.5, "theta": 0.0}}
    assert any("n'a que 2 points" in m for m in L.valider_donnees("monde", monde([{"point": 2, "duree_s": 1}])))
    assert any("deux pauses" in m for m in L.valider_donnees("monde", monde([{"point": 0, "duree_s": 1}] * 2)))
    assert L.valider_donnees("monde", monde([{"point": 1, "duree_s": 1}])) == []


def test_scene_regles():
    assert L.valider_donnees("scene", EXEMPLE_SCENE) == []
    sans = modifie(EXEMPLE_SCENE, lambda d: d.update(trajets=[]))
    assert any("il faut des trajets" in m for m in L.valider_donnees("scene", sans))
    assert L.valider_donnees("scene", dict(sans, hasard=20)) == []
    faux = modifie(EXEMPLE_SCENE, lambda d: d["pietons"][0]["pauses"].append({"point": 5, "duree_s": 1}))
    assert any("n'a que 2 points" in m for m in L.valider_donnees("scene", faux))
    visiteur = modifie(EXEMPLE_SCENE, lambda d: d.update(visiteur="passant"))
    assert any("pilote: externe" in m for m in L.valider_donnees("scene", visiteur))
    visiteur["pietons"][0]["pilote"] = "externe"
    assert L.valider_donnees("scene", visiteur) == []
    assert any("n'est pas un des piétons" in m for m in L.valider_donnees("scene", dict(visiteur, visiteur="x")))


def test_distance_bord_et_cause_du_contact():
    assert B.distance_bord((0, 0), (1.0, 0)) == pytest.approx(1.0 - 0.26 - 0.25)
    assert B.distance_bord((0, 0, 1.2), (0.3, 0.4), 0.3) == pytest.approx(0.5 - 0.26 - 0.3)
    # le robot avance vers le piéton : en cause, même si le piéton avance aussi
    assert B.cause_contact((0, 0), (0.3, 0), (0.5, 0), (0, 0)) == "robot"
    assert B.cause_contact((0, 0), (0.3, 0), (0.5, 0), (-1.0, 0)) == "robot"
    # le piéton fonce sur le robot arrêté, ou qui recule
    assert B.cause_contact((0, 0), (0, 0), (0.5, 0), (-1.0, 0)) == "pieton"
    assert B.cause_contact((0, 0), (-0.2, 0), (0.5, 0), (-1.0, 0)) == "pieton"
    # tous deux arrêtés, ou qui passent côte à côte
    assert B.cause_contact((0, 0), (0, 0), (0.5, 0), (0, 0)) == "aucun"
    assert B.cause_contact((0, 0), (0, 0.3), (0.5, 0), (0, -0.3)) == "aucun"


def test_suivi_des_contacts_avec_hysteresis():
    suivi = B.SuiviContacts()
    t = 0.0
    # le robot avance vers un piéton immobile en (2, 0), le touche, recule un peu, revient
    for x in [0.0, 0.5, 1.0, 1.3, 1.46, 1.47, 1.45, 1.40, 1.46, 1.2, 1.0, 1.47]:
        vx = 0.3 if x >= 1.4 else -0.3
        suivi.noter(t, (x, 0.0, vx, 0.0), [("p", 2.0, 0.0, 0.0, 0.0, 0.25)])
        t += 0.05
    r = suivi.resume()
    assert r["contacts"] == 2 and r["contacts_robot"] == 2 and r["contacts_pieton"] == 0
    assert r["distance_min_bord_m"] == pytest.approx(2.0 - 1.47 - 0.51, abs=1e-3)
    assert suivi.contacts[0]["fin"] is not None and suivi.contacts[1]["fin"] is None
    assert B.COLONNES_BANC_V4[0] == "scene" and "contacts_robot" in B.COLONNES_BANC_V4


# ---------------------------------------------------------------- C. comportement du guide

def test_demande_aller():
    assert C.lire_demande_aller(" b204 ") == {"cible": "b204", "accompagner": False, "retour": None, "source": None}
    assert C.lire_demande_aller('{"cible": "b204"}')["accompagner"] is True
    d = C.lire_demande_aller(json.dumps({"cible": "principal", "accompagner": False, "retour": False,
                                         "source": "dialogue"}))
    assert d == {"cible": "principal", "accompagner": False, "retour": False, "source": "dialogue"}
    for faux in ('{"cible": 3}', '{"cible": "b204", "vite": true}', "{pas du json"):
        with pytest.raises(ValueError):
            C.lire_demande_aller(faux)


def test_evenements():
    e = C.evenement("depart", salle="b204", nom="Salle B204", mission="visite")
    assert L.valider_message("evenement_guide", e) == [] and e["texte"] == "Suivez-moi, je vous emmène à Salle B204."
    phrases = E.exemple_equipe("personnalites")["personnalites"][0]["phrases"]
    assert C.texte_evenement("arrivee", "le CDI", phrases) == "Et voilà : le CDI. Bonne journée !"
    assert C.texte_evenement("ralentir") == "Je ralentis pour vous attendre."
    for code in C.CODES_EVENEMENT:
        assert L.valider_message("evenement_guide", C.evenement(code, nom="b204")) == [], code
    with pytest.raises(KeyError):
        C.evenement("chanter")


def test_reglages_du_guide(tmp_path):
    assert C.reglages_guide() == C.DELAIS_GUIDE
    copie = L.copier_lieu(DEMO, tmp_path / "demo")
    fiche = L.charger_fiche(copie)
    fiche.guide = {"delai_perdu_s": 15, "retour_auto": False}
    L.enregistrer_fiche(fiche)
    relu = L.charger_fiche(copie)
    assert relu.guide == {"delai_perdu_s": 15, "retour_auto": False}
    r = C.reglages_guide(copie, delai_visiteur_s=10, inconnu=1, delai_perdu_s=None)
    assert r["delai_perdu_s"] == 15 and r["retour_auto"] is False and r["delai_visiteur_s"] == 10 and "inconnu" not in r
    d = relu.vers_dict()
    d["guide"] = {"distance_ralentir_m": 3.0, "distance_attendre_m": 2.5}
    assert any("plus grande que distance_ralentir_m" in m for m in L.valider_donnees("lieu", d))
    d["guide"] = {"delai_inconnu": 1}
    assert L.valider_donnees("lieu", d) and erreurs_js("lieu", d)


def test_etats_du_guide_compatibles():
    assert C.ETATS_GUIDE[:6] == ("attente", "en_route", "bloque", "detour", "arrive", "echec")
    ancien = {"etat": "arrive", "cible": "b204", "reste_m": 0.0, "itineraire": ["accueil", "b204"]}
    assert L.valider_message("etat_guide", ancien) == []
    assert L.valider_message("etat_guide", dict(ancien, message="arrivé")) == []
    assert set(C.ETATS_EN_MISSION) < set(C.ETATS_GUIDE) and set(C.ETATS_FINAUX_VISITE) < set(C.ETATS_GUIDE)


# ---------------------------------------------------------------- D. pilotage

PERMIS = [("sport", 7001, {}), ("sport", 7101, {"data": 500}), ("sport", 7101, {"data": 706}),
          ("sport", 7101, {"data": 702}), ("sport", 7101, {"data": 3}), ("sport", 7101, {"data": 1}),
          ("sport", 7101, {"data": 0}), ("sport", 7101, {"data": 550604}), ("sport", 7101, {"data": 550574}),
          ("sport", 7105, {"velocity": [0.4, -0.25, 0.6], "duration": 0.5}),
          ("sport", 7105, {"velocity": [0.0, 0.0, 0.0], "duration": 1.0}), ("sport", 7106, {"data": 2}),
          ("sport", 7100, {"fsm_id": 550, "api_id": 1}), ("arm", 7106, {"action_id": 26}),
          ("arm", 7106, {"action_id": 99}), ("arm", 7107, {}), ("arm", 7108, {"action_name": "salut_appris"}),
          ("voice", 1001, {"index": 0, "speaker_id": 0, "text": "Bonjour"}), ("voice", 1006, {"volume": 80}),
          ("voice", 1010, {"R": 255, "G": 0, "B": 128})]
INTERDITS = [("sport", 7101, {"data": 550401}), ("sport", 7101, {"data": 550402}), ("sport", 7101, {"data": 550403}),
             ("sport", 7101, {"data": 2}), ("sport", 7101, {"data": 4}), ("sport", 7101, {"data": 801}),
             ("sport", 7101, {"data": 1.0}), ("sport", 7104, {"data": 1}), ("sport", 7110, {}), ("sport", 7111, {}),
             ("sport", 7102, {"data": 1}), ("sport", 7107, {"data": 1}),
             ("sport", 7105, {"velocity": [0.5, 0.0, 0.0], "duration": 0.5}),
             ("sport", 7105, {"velocity": [0.2, 0.0, 0.0], "duration": 2.0}),
             ("sport", 7105, {"velocity": [float("nan"), 0.0, 0.0], "duration": 0.5}),
             ("sport", 7105, {"velocity": [0.2, 0.0], "duration": 0.5}), ("sport", 7106, {"data": 7}),
             ("sport", 7100, {"fsm_id": 550, "api_id": 2}), ("arm", 7106, {"action_id": 5}), ("arm", 7110, {}),
             ("voice", 1006, {"volume": 101}), ("voice", 1010, {"R": 256, "G": 0, "B": 0}), ("voice", 1002, {}),
             ("moteurs", 1, {}), ("sport", 7101, "{pas du json")]


@pytest.mark.parametrize("service,api,donnees", PERMIS)
def test_commandes_permises(service, api, donnees):
    assert D.refus_commande(service, api, json.dumps(donnees)) is None
    assert D.refus_commande(service, api, donnees) is None


@pytest.mark.parametrize("service,api,donnees", INTERDITS)
def test_commandes_interdites(service, api, donnees):
    raison = D.refus_commande(service, api, donnees)
    assert isinstance(raison, str) and raison


def test_confirmations():
    assert D.confirmation_requise("sport", 7101, {"data": 1}) == "portique"
    assert D.confirmation_requise("sport", 7101, '{"data": 0}') == "portique"
    assert D.confirmation_requise("sport", 7101, {"data": 550604}) == "zone_libre"
    assert D.confirmation_requise("sport", 7101, {"data": 500}) is None
    assert D.confirmation_requise("sport", 7105, {"velocity": [0, 0, 0], "duration": 1}) is None
    assert D.DANSES_INTERDITES == (401, 402, 403) and all(D.danse_interdite(n) for n in (401, 402, 403))
    assert D.FSM_ARRET_DANSE is None


def test_parametres_comme_le_sdk():
    assert json.loads(D.parametre_fsm(550604)) == {"data": 550604}
    assert json.loads(D.parametre_liste_danses()) == {"fsm_id": 550, "api_id": 1}
    assert json.loads(D.parametre_geste(26)) == {"action_id": 26}
    assert json.loads(D.parametre_vitesse(0.2, 0, 0)) == {"velocity": [0.2, 0.0, 0.0], "duration": 0.5}
    assert json.loads(D.parametre_led(1, 2, 3)) == {"R": 1, "G": 2, "B": 3}
    assert json.loads(D.parametre_tts("Bonjour é")) == {"index": 0, "speaker_id": 0, "text": "Bonjour é"}
    assert D.LIMITES_MARCHE == L.LIMITES_PONT and D.DELAI_HOMME_MORT_S + 0.1 <= D.ARRET_MAX_S
    assert D.message_refus(7401).startswith("Les bras tiennent")


def test_liste_des_danses_deux_formats():
    officiel = {"fsm_id": 550, "api_id": 1, "motion": {"604": {"name": "robot_dance", "duration": 18.2},
                                                       "401": {"name": "lie", "duration": 5}}}
    assert D.lire_liste_danses(json.dumps(officiel)) == {604: {"nom": "robot_dance", "duree_s": 18.2},
                                                         401: {"nom": "lie", "duree_s": 5.0}}
    communaute = {"602": {"name": "popping", "duration": 9.0}, "info": "x"}
    assert D.lire_liste_danses(communaute) == {602: {"nom": "popping", "duree_s": 9.0}}


@pytest.mark.skipif(not URDF.is_file(), reason="URDF du G1 absent (third_party)")
def test_limites_des_bras_celles_de_l_urdf():
    racine = ET.parse(URDF).getroot()
    urdf = {j.get("name").removesuffix("_joint"): (float(j.find("limit").get("lower")),
                                                   float(j.find("limit").get("upper")))
            for j in racine.findall("joint") if j.get("type") != "fixed"}
    for nom, (bas, haut) in D.LIMITES_URDF.items():
        assert urdf[nom] == pytest.approx((bas, haut)), nom
        b, h = D.LIMITES_BRAS[nom]
        assert bas < b < h < haut
    assert sorted(D.ARTICULATIONS_BRAS.values()) == list(range(15, 29)) and D.INDICE_POIDS == 29
    assert set(D.ARTICULATIONS_TAILLE.values()) == {12, 13, 14}


def test_choregraphie_d_exemple_sure():
    d = D.charger_choregraphie("exemple_kpop")
    assert D.verifier_choregraphie(d) == []
    assert d["musique"]["fichier"] is None and d["musique"]["battement"]["bpm"] == 120   # aucune musique protégée
    rampe, fin = d["bras"]["rampe_s"], d["duree_s"]
    assert D.poses_bras(d, 0.0)[0] == 0.0 and D.poses_bras(d, rampe)[0] == 1.0 and D.poses_bras(d, fin)[0] == 0.0
    assert D.poses_bras(d, rampe / 2)[0] == pytest.approx(0.5)
    poids, q = D.poses_bras(d, d["bras"]["poses"][0]["t"])
    assert q["left_elbow"] == pytest.approx(0.8) and q["right_shoulder_pitch"] == pytest.approx(-0.5)
    vitesses = []
    for t0, q0, t1, q1 in D.segments_bras(d):
        vitesses += [math.pi / 2 * abs(q1[n] - q0[n]) / (t1 - t0) for n in D.ARTICULATIONS_BRAS]
    assert max(vitesses) <= D.VITESSE_BRAS_MAX
    distance, rotation = D.deplacement_pas(d)
    assert distance <= D.DEPLACEMENT_MAX_M and rotation <= D.ROTATION_MAX_RAD
    assert [c.name for c in D.lister_choregraphies()] == ["exemple_kpop.choregraphie.yaml"]


REFUS_CHOREGRAPHIE = {
    "bras trop rapides": (lambda d: d["bras"]["poses"][0]["q"].update(left_shoulder_pitch=-2.0), "rad/s"),
    "angle hors des limites": (lambda d: d["bras"]["poses"][5]["q"].update(left_elbow=2.1), "sort des limites"),
    "pose pendant la rampe": (lambda d: d["bras"]["poses"][0].update(t=1.0), "fin de la rampe"),
    "temps qui reculent": (lambda d: d["bras"]["poses"][3].update(t=2.0), "croître"),
    "pas qui se chevauchent": (lambda d: d["pas"][1].update(t=10.5), "avant la fin du pas précédent"),
    "trop loin du départ": (lambda d: d["pas"].extend([{"t": t, "vx": 0.3, "vy": 0.0, "wz": 0.0, "duree_s": 2.0}
                                                       for t in (0.0, 2.0)]), "de son départ"),
    "gestes avec les bras": (lambda d: d.update(gestes=[{"t": 3.0, "action": 26}]), "7400"),
    "LED après la fin": (lambda d: d["led"].append({"t": 30.0, "r": 0, "g": 0, "b": 0}), "après la fin"),
    "rampes trop longues": (lambda d: (d["bras"].update(rampe_s=10.0), d.update(duree_s=19.0)), "rampes"),
    # assemblage : première pose collée à la fin de la rampe, ou dernière au début de la rampe de fin
    "pose collée à la rampe": (lambda d: d["bras"]["poses"][0].update(t=d["bras"]["rampe_s"]), "d'un coup"),
    "pose collée à la rampe de fin": (lambda d: d["bras"]["poses"][-1].update(t=d["duree_s"] - d["bras"]["rampe_s"]),
                                      "d'un coup"),
}


@pytest.mark.parametrize("cas", list(REFUS_CHOREGRAPHIE))
def test_choregraphie_hors_limites_refusee(cas):
    changement, attendu = REFUS_CHOREGRAPHIE[cas]
    d = modifie(D.charger_choregraphie("exemple_kpop"), changement)
    erreurs = D.verifier_choregraphie(d)
    assert any(attendu in m for m in erreurs), erreurs


# ---------------------------------------------------------------- E. équipe

def test_fichiers_de_l_equipe_ecrits_et_relus(tmp_path):
    copie = L.copier_lieu(DEMO, tmp_path / "demo")
    for quoi in E.FICHIERS_EQUIPE:
        assert E.charger_equipe(copie, quoi) is None
        chemin = E.enregistrer_equipe(copie, quoi, E.exemple_equipe(quoi))
        assert chemin == copie / E.FICHIERS_EQUIPE[quoi] and chemin.read_text(encoding="utf-8").startswith("# ")
        assert E.charger_equipe(copie, quoi) == E.exemple_equipe(quoi)
    with pytest.raises(L.ErreurLieu):
        E.enregistrer_equipe(copie, "dialogues", {"version": 1})
    with pytest.raises(ValueError):
        E.chemin_equipe(copie, "musique")
    assert L.valider_lieu(copie).erreurs == []


REFUS_EQUIPE = {
    "personnalité active inconnue": ("personnalites", lambda d: d.update(active="joyeux"), "n'existe pas"),
    "deux personnalités de même id": ("personnalites", lambda d: d["personnalites"][1].update(id="accueillant"),
                                      "apparaît 2 fois"),
    "guider sans {salle}": ("dialogues", lambda d: d["regles"][0]["motifs"].append("je cherche"), "{salle}"),
    "personnalite sans id": ("dialogues", lambda d: d["regles"][3].pop("personnalite"), "besoin du champ"),
    "personnalite hors de son action": ("dialogues", lambda d: d["regles"][1].update(personnalite="discret"),
                                        "ne sert qu'avec"),
    "deux règles de même id": ("dialogues", lambda d: d["regles"][1].update(id="merci"), "apparaît 2 fois"),
}


@pytest.mark.parametrize("cas", list(REFUS_EQUIPE))
def test_regles_de_l_equipe(cas):
    quoi, changement, attendu = REFUS_EQUIPE[cas]
    erreurs = E.valider_equipe(quoi, modifie(E.exemple_equipe(quoi), changement))
    assert any(attendu in m for m in erreurs), erreurs


# ---------------------------------------------------------------- assemblage de la vague 4 : équipe

def test_regle_geste_des_dialogues():
    d = E.exemple_equipe("dialogues")
    d["regles"].insert(0, {"id": "coucou", "motifs": ["coucou"], "action": "geste", "reponse": "Coucou !",
                           "geste": 25})
    assert L.valider_donnees("dialogues", d) == [] and erreurs_js("dialogues", d) == []
    sans = modifie(d, lambda x: x["regles"][0].pop("geste"))
    assert any("besoin du champ geste" in m for m in L.valider_donnees("dialogues", sans))
    mal_place = modifie(d, lambda x: x["regles"][1].update(geste=26))
    assert any("ne sert qu'avec l'action geste" in m for m in L.valider_donnees("dialogues", mal_place))
    interdit = modifie(d, lambda x: x["regles"][0].update(geste=99))
    assert L.valider_donnees("dialogues", interdit) and erreurs_js("dialogues", interdit)
    from atelier.equipe.dialogue import Chatbot, decider
    bot = Chatbot(d, L.charger_salles(DEMO))
    r = bot.repondre("Coucou")
    assert r["action"] == "geste" and r["geste"] == 25
    assert decider(bot, r)["geste"] == 25
    assert decider(bot, r, maitre={"maitre": "pilotage"})["geste"] is None
    en_visite = decider(bot, r, etat_guide={"etat": "en_route", "cible": "b204"})
    assert en_visite["geste"] is None and en_visite["dire"] == "Coucou !"


def test_voix_nommee_d_une_personnalite():
    p = E.exemple_equipe("personnalites")
    p["personnalites"][0]["voix"]["nom"] = "fr_FR-siwis-medium"
    assert L.valider_donnees("personnalites", p) == [] and erreurs_js("personnalites", p) == []
    message = E.message_robot_dire("Bonjour", "dialogue", personnalite=p["personnalites"][0])
    assert message["voix"]["nom"] == "fr_FR-siwis-medium" and L.valider_message("robot_dire", message) == []
    faux = modifie(p, lambda x: x["personnalites"][0]["voix"].update(nom="voix avec espaces"))
    assert L.valider_donnees("personnalites", faux) and erreurs_js("personnalites", faux)


def test_exemple_camera_tangage_vers_le_haut():
    c = E.exemple_equipe("camera")
    assert c["camera"]["modele"] == "See3CAM_11CUG" and c["camera"]["position"]["tangage"] < 0
    assert "vers le bas" in schema("camera")["properties"]["camera"]["properties"]["position"]["properties"][
        "tangage"]["description"]


def test_valider_lieu_couvre_les_fichiers_de_l_equipe(tmp_path):
    copie = L.copier_lieu(DEMO, tmp_path / "demo")
    assert L.valider_lieu(copie).ok
    d = E.exemple_equipe("dialogues")
    d["regles"].append({"id": "mode_fantome", "motifs": ["mode fantome"], "action": "personnalite",
                        "reponse": "D'accord.", "personnalite": "fantome"})
    (copie / E.FICHIERS_EQUIPE["dialogues"]).write_text(yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")
    E.enregistrer_equipe(copie, "personnalites", E.exemple_equipe("personnalites"))
    r = L.valider_lieu(copie)
    assert not r.ok and any("fantome" in m for m in r.erreurs), r.erreurs
    (copie / E.FICHIERS_EQUIPE["camera"]).write_text("version: 1\ncamera: 3\n", encoding="utf-8")
    assert any("camera.yaml" in m for m in L.valider_lieu(copie).erreurs)


def test_sujets_de_l_equipe_ont_un_schema():
    for sujet, (type_ros, schema_json, qui) in E.SUJETS_EQUIPE.items():
        assert sujet.startswith("/") and type_ros == "std_msgs/String" and qui
        assert schema_json is None or schema_json in L.TYPES_MESSAGES


# ---------------------------------------------------------------- squelettes partagés

def test_onglets_et_styles_de_la_vague_4():
    web = RACINE / "atelier" / "web"
    app = (web / "js" / "app.js").read_text(encoding="utf-8")
    index = (web / "index.html").read_text(encoding="utf-8")
    for ecran, texte in (("pilotage", "Pilotage"), ("personnalites", "Personnalités"), ("dialogues", "Dialogues"),
                         ("camera", "Caméra")):
        assert (web / "js" / "ecrans" / f"{ecran}.js").is_file()
        assert f"import * as {ecran} from './ecrans/{ecran}.js';" in app
        assert f"{{ id: '{ecran}', texte: '{texte}', module: {ecran}" in app
    for css in ("principal", "passants", "guide", "pilotage", "equipe"):
        assert (web / "css" / f"{css}.css").is_file() and f'href="css/{css}.css"' in index
    simulation = (web / "js" / "ecrans" / "simulation.js").read_text(encoding="utf-8")
    for panneau in ("guide", "passants"):
        assert (web / "js" / "panneaux" / f"{panneau}.js").is_file()
        assert f"from '../panneaux/{panneau}.js'" in simulation


def test_routes_enregistrees_et_ws_etat():
    from atelier.serveur import main
    from atelier.serveur.etat import EtatServeur
    from atelier.serveur.pont_ros import PUBLICATIONS_JSON, SUJETS_JSON
    texte = (RACINE / "atelier" / "serveur" / "main.py").read_text(encoding="utf-8")
    for route in ("principal", "passants", "guide", "pilotage", "equipe"):
        assert (RACINE / "atelier" / "serveur" / "routes" / f"{route}.py").is_file()
        assert route in texte
    assert main.creer_app(ros=False) is not None
    d = EtatServeur(ros=False).etat_direct()
    assert {"evenements", "maitre", "personnes", "visiteurs", "pietons"} <= set(d)
    assert d["evenements"] == [] and d["maitre"] is None
    assert {"/guide/evenement", "/pietons/etat", "/mouvement/maitre", "/personnes/lidar"} <= set(SUJETS_JSON)
    assert set(PUBLICATIONS_JSON) <= set(E.SUJETS_EQUIPE) | {"/robot/dire"}


def test_simulation_refusee_sans_point_principal(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from atelier.serveur.main import creer_app
    monkeypatch.setenv("ATELIER_LIEUX", str(tmp_path))
    copie = L.copier_lieu(DEMO, tmp_path / "demo")
    L.enregistrer_salles(copie, [s for s in L.charger_salles(copie) if s.id != "accueil"])
    with TestClient(creer_app(ros=False)) as client:
        r = client.post("/api/simulation/demarrer", json={"lieu": "demo", "etage": "rdc"})
    assert r.status_code == 409 and "pas de point principal" in r.json()["detail"]


def test_paquets_et_noeuds_declares():
    ws = RACINE / "ws" / "src"
    for paquet, executable in (("g1_pilotage", "pilote = g1_pilotage.pilote:main"),
                               ("g1_equipe", "dialogue = g1_equipe.dialogue:main")):
        assert ET.parse(ws / paquet / "package.xml").getroot().findtext("name") == paquet
        assert executable in (ws / paquet / "setup.py").read_text(encoding="utf-8")
    setup = (ws / "g1_nav" / "setup.py").read_text(encoding="utf-8")
    for module in ("personnes", "faux_visiteur"):
        assert (ws / "g1_nav" / "g1_nav" / f"{module}.py").is_file() and f"g1_nav.{module}:main" in setup
    depend = [d.text for d in ET.parse(ws / "g1_pilotage" / "package.xml").getroot().findall("depend")]
    assert {"unitree_api", "unitree_hg", "rclpy"} <= set(depend)
    assert (RACINE / "atelier" / "monde" / "scene.py").is_file() and (RACINE / "atelier" / "equipe").is_dir()
    gitignore = (RACINE / ".gitignore").read_text(encoding="utf-8")
    assert "choregraphies/musique/*" in gitignore


# ---------------------------------------------------------------- plan et recette

def _section_11():
    plan = PLAN.read_text(encoding="utf-8")
    assert "## 11. Accueil, passants, pilotage et équipe (vague 4)" in plan
    return plan, plan[plan.index("## 11. Accueil"):]


def test_plan_section_11():
    plan, s11 = _section_11()
    for titre in ("### 11.2 A. Le point principal", "### 11.3 B. Les passants", "### 11.4 C. Le comportement du guide",
                  "### 11.5 D. Le pilotage", "### 11.6 E. L'équipe", "### 11.7 Les agents de la vague 4",
                  "### 11.11 Ce qui reste à vérifier sur le robot"):
        assert titre in s11, titre
    for mot in ("etiquettes: [principal]", "/guide/evenement", "/pietons/etat", "/pietons/consigne",
                "/personnes/lidar", "/mouvement/maitre", "/arm_sdk", "550604", "401, 402, 403", "8010",
                "personnalites.yaml", "dialogues.yaml", "camera.yaml", "docs/integration-equipe.md",
                "je cherche la salle b204", "attente_passage", "attente_visiteur", "perdu", "retour"):
        assert mot in s11, mot
    for code in C.CODES_EVENEMENT:
        assert f"`{code}`" in s11, code
    for n in range(21, 31):
        assert re.search(rf"^{n}\. \*\*", plan, re.M), f"critère {n} absent de la section 7"
    tout = TOUT.read_text(encoding="utf-8")
    assert re.search(r"^TOUS=\((\d+ ){29}30\)$", tout, re.M)
    assert "N / 30" in tout
    for n in range(21, 31):
        assert re.search(rf"\[{n}\]=\d+", tout), f"délai du critère {n}"


def test_table_des_proprietaires_sans_doublon():
    """Un chemin cité dans une ligne de la table 11.7 ne l'est dans aucune autre."""
    _, s11 = _section_11()
    table = s11[s11.index("### 11.7"):s11.index("### 11.8")]
    lignes = [l for l in table.splitlines() if l.startswith("| ") and not l.startswith("| Agent") and "---" not in l]
    assert len(lignes) == 6
    vus = {}
    doublons = []
    for ligne in lignes:
        agent = ligne.split("|")[1].strip()
        possede = ligne.split("|")[3]
        for chemin in set(re.findall(r"`([^`]+)`", possede)):
            if "/" not in chemin and "." not in chemin:
                continue
            if chemin in vus and vus[chemin] != agent:
                doublons.append((chemin, vus[chemin], agent))
            vus.setdefault(chemin, agent)
    assert doublons == []
