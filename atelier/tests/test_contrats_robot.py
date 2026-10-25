"""Tests des contrats de la vague 3, le vrai robot (agent Intégrateur, section 10 du plan).

  ~/robot-g1/.venv-projet/bin/python -m pytest ~/robot-g1/atelier/tests/test_contrats_robot.py -v

Vérifie que :
  - le champ facultatif repere_unitree d'un étage (lieu.yaml) est accepté, refusé quand il est mal
    écrit, et porté par la dataclass Etage ; un lieu sans ce champ ne change pas ;
  - atelier.lieu.repere_unitree suit la règle du contrat (champ, sinon scan → origine, monde →
    depart_robot), et la marque au sol est l'origine de la carte d'Unitree ;
  - les conversions de poses entre le repère map et celui d'Unitree sont exactes et réciproques ;
  - les messages JSON /pont/etat, /reperage/etat et /reperage/demander ont des schémas draft-07
    valides, des exemples conformes, et les mêmes verdicts dans atelier.lieu et dans jsonschema ;
  - les valeurs du contrat (limites, délais) sont celles de la section 10, et tout.sh compte 20 critères.
"""
import copy
import json
import math
import random
import re

import jsonschema
import pytest
import yaml

import atelier
from atelier import lieu as L
from atelier.lieu.validation import erreurs_schema
from atelier.tests.test_lieu_validation import MUTATIONS, _chemins, _muter

DOSSIER_SCHEMAS = atelier.RACINE / "atelier" / "lieu" / "schemas"
DEMO = atelier.RACINE / "lieux" / "demo"
PLAN = atelier.RACINE / "docs" / "plan-atelier-multi-agents.md"
TOUT = atelier.RACINE / "tests_e2e" / "tout.sh"


def schema(nom):
    return json.loads((DOSSIER_SCHEMAS / f"{nom}.schema.json").read_text(encoding="utf-8"))


def erreurs_js(nom, donnees):
    return [e.message for e in jsonschema.Draft7Validator(schema(nom)).iter_errors(donnees)]


def modifie(exemple, changement):
    donnees = copy.deepcopy(exemple)
    changement(donnees)
    return donnees


def fiche_demo():
    return yaml.safe_load((DEMO / "lieu.yaml").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- lieu.yaml : repere_unitree

def test_lieu_avec_repere_unitree_valide():
    d = fiche_demo()
    d["etages"][0]["repere_unitree"] = {"x": 3.0, "y": 9.0, "theta": 0.5}
    assert erreurs_js("lieu", d) == []
    assert L.valider_donnees("lieu", d) == []


@pytest.mark.parametrize("repere", [
    {"x": 3.0, "y": 9.0},                                  # theta manquant
    {"x": 3.0, "y": 9.0, "theta": 0.5, "z": 1.0},          # champ inconnu
    {"x": "3", "y": 9.0, "theta": 0.5},                    # texte
    {"x": 3.0, "y": 9.0, "theta": 7.0},                    # angle hors de [-2π, 2π]
    [3.0, 9.0, 0.5],                                       # liste au lieu d'une pose
    None,                                                  # null n'est pas permis : on retire le champ
])
def test_lieu_repere_unitree_mal_ecrit_refuse(repere):
    d = fiche_demo()
    d["etages"][0]["repere_unitree"] = repere
    assert erreurs_js("lieu", d), repere
    assert L.valider_donnees("lieu", d), repere


def test_etage_aller_retour():
    e = L.Etage("rdc", "Rez-de-chaussée", "scan", L.Pose(3.0, 9.0, 0.5))
    d = e.vers_dict()
    assert d == {"id": "rdc", "nom": "Rez-de-chaussée", "source_carte": "scan",
                 "repere_unitree": {"x": 3.0, "y": 9.0, "theta": 0.5}}
    assert L.Etage.depuis_dict(d) == e
    sans = L.Etage("rdc", "Rez-de-chaussée", "monde")
    assert sans.repere_unitree is None
    assert "repere_unitree" not in sans.vers_dict()
    assert L.Etage.depuis_dict(sans.vers_dict()) == sans


def test_lieu_demo_inchange_apres_enregistrement(tmp_path):
    """Un lieu sans repere_unitree se relit et se réécrit sans que ce champ apparaisse."""
    copie = L.copier_lieu(DEMO, tmp_path / "demo")
    fiche = L.charger_fiche(copie)
    assert all(e.repere_unitree is None for e in fiche.etages)
    L.enregistrer_fiche(fiche, copie)
    relu = yaml.safe_load((copie / "lieu.yaml").read_text(encoding="utf-8"))
    assert relu == fiche_demo()
    assert L.valider_lieu(copie).ok


def test_repere_unitree_enregistre_puis_relu(tmp_path):
    copie = L.copier_lieu(DEMO, tmp_path / "demo")
    fiche = L.charger_fiche(copie)
    fiche.etages[0].repere_unitree = L.Pose(3.0, 9.0, 0.5)
    L.enregistrer_fiche(fiche, copie)
    assert L.charger_fiche(copie).etages[0].repere_unitree == L.Pose(3.0, 9.0, 0.5)
    assert L.repere_unitree(copie, "rdc") == L.Pose(3.0, 9.0, 0.5)
    assert L.valider_lieu(copie).ok


# ---------------------------------------------------------------- règle du repère d'Unitree

def test_repere_unitree_monde_dessine_depart_robot():
    """Monde dessiné (demo) : l'origine de la carte d'Unitree est depart_robot, (2,5 ; 10 ; 0)."""
    depart = L.charger_monde(DEMO, "rdc").depart_robot
    assert L.repere_unitree(DEMO, "rdc") == L.Pose(depart.x, depart.y, depart.theta)
    assert L.repere_unitree(DEMO, "rdc") == L.Pose(2.5, 10.0, 0.0)
    assert L.marque_au_sol(DEMO, "rdc") == L.repere_unitree(DEMO, "rdc")


def test_repere_unitree_carte_du_scan_origine(tmp_path):
    copie = L.copier_lieu(DEMO, tmp_path / "demo")
    fiche = L.charger_fiche(copie)
    fiche.etages[0].source_carte = "scan"
    L.enregistrer_fiche(fiche, copie)
    assert L.repere_unitree(copie, "rdc") == L.Pose(0.0, 0.0, 0.0)


def test_repere_unitree_sans_monde_origine(tmp_path):
    copie = L.copier_lieu(DEMO, tmp_path / "demo")
    L.chemin_monde(copie, "rdc").unlink()
    assert L.repere_unitree(copie, "rdc") == L.Pose(0.0, 0.0, 0.0)


def test_repere_unitree_champ_prioritaire(tmp_path):
    copie = L.copier_lieu(DEMO, tmp_path / "demo")
    for source in ("monde", "scan"):
        fiche = L.charger_fiche(copie)
        fiche.etages[0].source_carte = source
        fiche.etages[0].repere_unitree = L.Pose(-1.0, 4.0, -2.0)
        L.enregistrer_fiche(fiche, copie)
        assert L.repere_unitree(copie, "rdc") == L.Pose(-1.0, 4.0, -2.0)


def test_repere_unitree_etage_inconnu():
    with pytest.raises(L.ErreurLieu, match="n'existe pas"):
        L.repere_unitree(DEMO, "etage9")


def test_carte_pour_reperage(tmp_path):
    assert L.carte_pour_reperage(DEMO) is None
    assert L.carte_pour_reperage(DEMO, repetition=True) == L.CARTE_REPETITION == "repetition.pcd"
    copie = L.copier_lieu(DEMO, tmp_path / "demo")
    fiche = L.charger_fiche(copie)
    fiche.carte_unitree = "rdc_2026-10-25_17h42.pcd"
    L.enregistrer_fiche(fiche, copie)
    assert L.carte_pour_reperage(copie) == "rdc_2026-10-25_17h42.pcd"
    assert L.carte_pour_reperage(copie, repetition=True) == "rdc_2026-10-25_17h42.pcd"


# ---------------------------------------------------------------- conversions de poses

def proche(a, b, tol=1e-9):
    return (abs(a[0] - b[0]) < tol and abs(a[1] - b[1]) < tol
            and abs(L.normaliser_angle(a[2] - b[2])) < tol)


def test_composer_cas_connu():
    # repère tourné d'un quart de tour, placé en (1, 2) : son axe x est l'axe y du parent
    assert proche(L.composer_poses((1.0, 2.0, math.pi / 2), (1.0, 0.0, 0.0)), (1.0, 3.0, math.pi / 2))
    assert proche(L.composer_poses((1.0, 2.0, math.pi / 2), (0.0, 1.0, 0.5)), (0.0, 2.0, math.pi / 2 + 0.5))
    assert proche(L.inverser_pose((1.0, 2.0, math.pi / 2)), (-2.0, 1.0, -math.pi / 2))


def test_types_de_poses_acceptes():
    attendu = L.composer_poses((1.0, 2.0, 0.3), (0.5, -1.0, 0.2))
    assert proche(L.composer_poses({"x": 1.0, "y": 2.0, "theta": 0.3}, L.Pose(0.5, -1.0, 0.2)), attendu)


def test_aller_retour_aleatoire():
    hasard = random.Random(3)
    for _ in range(500):
        repere = (hasard.uniform(-30, 30), hasard.uniform(-30, 30), hasard.uniform(-math.pi, math.pi))
        pose = (hasard.uniform(-30, 30), hasard.uniform(-30, 30), hasard.uniform(-math.pi, math.pi))
        u = L.carte_vers_unitree(pose, repere)
        assert proche(L.unitree_vers_carte(u, repere), pose, 1e-7)
        assert proche(L.composer_poses(repere, L.inverser_pose(repere)), (0.0, 0.0, 0.0), 1e-7)
        assert -math.pi <= u[2] < math.pi


def test_marque_au_sol_est_l_origine_unitree():
    """Le robot posé sur la marque est en (0, 0, 0) dans le repère d'Unitree."""
    repere = (3.0, 9.0, 0.5)
    assert proche(L.carte_vers_unitree(repere, repere), (0.0, 0.0, 0.0))
    marque = L.marque_au_sol(DEMO, "rdc")
    assert proche(L.pose_unitree_depuis_carte(marque, DEMO, "rdc"), (0.0, 0.0, 0.0))
    # le départ du robot proxy (2,5 ; 10) est donc en (0, 0) pour le faux service, et la salle b204
    # (21 ; 13 ; π/2) en (18,5 ; 3 ; π/2)
    assert proche(L.pose_unitree_depuis_carte((21.0, 13.0, math.pi / 2), DEMO, "rdc"), (18.5, 3.0, math.pi / 2))
    assert proche(L.pose_carte_depuis_unitree((18.5, 3.0, math.pi / 2), DEMO, "rdc"), (21.0, 13.0, math.pi / 2))


def test_decalage_avec_rotation_du_critere_18():
    """Variante B du critère 18 : repere_unitree (3 ; 9 ; 0,5), robot en (2,5 ; 10 ; 0) dans map."""
    u = L.carte_vers_unitree((2.5, 10.0, 0.0), (3.0, 9.0, 0.5))
    c, s = math.cos(0.5), math.sin(0.5)
    assert proche(u, (c * -0.5 + s * 1.0, -s * -0.5 + c * 1.0, -0.5))
    assert math.hypot(u[0], u[1]) > L.ECART_MAX_M or abs(u[2]) >= L.ECART_MAX_RAD


# ---------------------------------------------------------------- messages JSON du pont et du repérage

EXEMPLES = {"etat_pont": L.EXEMPLE_ETAT_PONT, "etat_reperage": L.EXEMPLE_ETAT_REPERAGE,
            "demande_reperage": L.EXEMPLE_DEMANDE_REPERAGE}


@pytest.mark.parametrize("nom", list(EXEMPLES) + ["lieu"])
def test_schema_draft07_valide(nom):
    s = schema(nom)
    assert s["$schema"] == "http://json-schema.org/draft-07/schema#"
    jsonschema.Draft7Validator.check_schema(s)


@pytest.mark.parametrize("nom", list(EXEMPLES))
def test_exemples_du_contrat_valides(nom):
    assert erreurs_js(nom, EXEMPLES[nom]) == []
    assert L.valider_message(nom, EXEMPLES[nom]) == []
    assert L.valider_donnees(nom, EXEMPLES[nom]) == []


def test_demande_sans_pose_valide():
    assert L.valider_message("demande_reperage", {"id": "atelier-2"}) == []


def test_tous_les_etats_sont_dans_les_schemas():
    assert tuple(schema("etat_pont")["properties"]["etat"]["enum"]) == L.ETATS_PONT
    assert tuple(schema("etat_reperage")["properties"]["etat"]["enum"]) == L.ETATS_REPERAGE


REFUS_SCHEMA = {
    "pont : état inconnu": ("etat_pont", lambda d: d.update(etat="marche")),
    "pont : sans consigne": ("etat_pont", lambda d: d.pop("consigne")),
    "pont : consigne sans wz": ("etat_pont", lambda d: d["consigne"].pop("wz")),
    "pont : envoyees négatif": ("etat_pont", lambda d: d.update(envoyees=-1)),
    "pont : envoyees décimal": ("etat_pont", lambda d: d.update(envoyees=1.5)),
    "pont : code texte": ("etat_pont", lambda d: d.update(code="0")),
    "pont : version 2": ("etat_pont", lambda d: d.update(version=2)),
    "pont : durée nulle": ("etat_pont", lambda d: d.update(duree_consigne_s=0)),
    "reperage : état inconnu": ("etat_reperage", lambda d: d.update(etat="ok")),
    "reperage : localisation simu": ("etat_reperage", lambda d: d.update(localisation="simu")),
    "reperage : pose sans theta": ("etat_reperage", lambda d: d["pose"].pop("theta")),
    "reperage : précision négative": ("etat_reperage", lambda d: d.update(precision_m=-0.1)),
    "reperage : sans repere_unitree": ("etat_reperage", lambda d: d.pop("repere_unitree")),
    "reperage : sauts décimal": ("etat_reperage", lambda d: d.update(sauts=0.5)),
    "demande : sans id": ("demande_reperage", lambda d: d.pop("id")),
    "demande : id vide": ("demande_reperage", lambda d: d.update(id="")),
    "demande : champ inconnu": ("demande_reperage", lambda d: d.update(cap=0.0)),
    "demande : x texte": ("demande_reperage", lambda d: d.update(x="2.5")),
}


@pytest.mark.parametrize("cas", list(REFUS_SCHEMA))
def test_schema_refuse(cas):
    nom, changement = REFUS_SCHEMA[cas]
    donnees = modifie(EXEMPLES[nom], changement)
    assert erreurs_js(nom, donnees), f"jsonschema aurait dû refuser : {cas}"
    assert L.valider_message(nom, donnees), f"atelier.lieu aurait dû refuser : {cas}"


REFUS_REGLES = {
    "en mouvement sans permission": ("etat_pont", lambda d: d.update(mouvement_permis=False), "mouvement_permis"),
    "attente du repérage et mouvement permis": ("etat_pont", lambda d: d.update(etat="attente_reperage"),
                                                "mouvement_permis"),
    "verrou sans arrêt verrouillé": ("etat_pont", lambda d: d.update(verrou=True), "verrou"),
    "consigne au-delà de la limite": ("etat_pont", lambda d: d["consigne"].update(vx=0.5), "dépasse la limite"),
    "plus de réponses que de requêtes": ("etat_pont", lambda d: d.update(reponses=413), "plus de réponses"),
    "repéré sans etat repere": ("etat_reperage", lambda d: d.update(etat="perdu"), "si et seulement si"),
    "etat repere sans repere": ("etat_reperage", lambda d: d.update(repere=False), "si et seulement si"),
    "repéré sans pose": ("etat_reperage", lambda d: d.update(pose=None), "sans pose"),
    "demande avec x seul": ("demande_reperage", lambda d: (d.pop("y"), d.pop("theta")), "vont ensemble"),
}


@pytest.mark.parametrize("cas", list(REFUS_REGLES))
def test_regles_refusent(cas):
    nom, changement, attendu = REFUS_REGLES[cas]
    messages = L.valider_message(nom, modifie(EXEMPLES[nom], changement))
    assert any(attendu in m for m in messages), messages


@pytest.mark.parametrize("nom", list(EXEMPLES))
def test_meme_verdict_que_jsonschema(nom):
    """Sur des centaines de variantes des exemples, atelier.lieu et jsonschema sont d'accord."""
    validateur = jsonschema.Draft7Validator(schema(nom))
    cas = [(c, m) for c in _chemins(EXEMPLES[nom]) for m in MUTATIONS]
    random.Random(4).shuffle(cas)
    desaccords = []
    for chemin, mutation in cas[:600]:
        variante = _muter(EXEMPLES[nom], chemin, mutation)
        nous = bool(erreurs_schema(nom, variante))
        eux = any(True for _ in validateur.iter_errors(variante))
        if nous != eux:
            desaccords.append((chemin, mutation, nous, eux))
    assert desaccords == []


# ---------------------------------------------------------------- valeurs du contrat

def test_valeurs_du_pont():
    assert L.LIMITES_PONT == {"vx": 0.4, "vy": 0.25, "wz": 0.6}
    assert L.API_SPORT_SET_VELOCITY == 7105 and L.API_RELOCALISER == 1804
    assert L.DUREE_CONSIGNE_S == 0.5 and L.DELAI_CMD_VEL_S == 0.3
    # sans /cmd_vel, l'arrêt part avant que la dernière consigne ait expiré
    assert L.DELAI_CMD_VEL_S + 1.0 / L.FREQUENCE_PONT_HZ <= L.DUREE_CONSIGNE_S
    assert L.LOCALISATIONS == ("simu", "unitree", "amcl", "externe")
    assert L.MODES_NAVIGATION == ("simu", "repetition", "robot")


def test_plan_section_10_et_vingt_criteres():
    plan = PLAN.read_text(encoding="utf-8")
    assert "## 10. Vrai robot : Jetson, pont, repérage" in plan
    for sujet in ("/api/sport/request", "/pont/etat", "/pont/arret", "/reperage/etat", "/reperage/demander",
                  "/g1_jumeau/cmd_vel", "/state_estimator/odom_pelvis", "/unitree/slam_relocation/odom"):
        assert sujet in plan, sujet
    for n in range(16, 21):
        assert re.search(rf"^{n}\. \*\*", plan, re.M), f"critère {n} absent de la section 7"
    tout = TOUT.read_text(encoding="utf-8")
    assert re.search(r"^TOUS=\(1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20\)$", tout, re.M)
