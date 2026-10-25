"""Tests des contrats du scan intégré (agent Intégrateur, section 9 du plan).

  ~/robot-g1/.venv-projet/bin/python -m pytest ~/robot-g1/atelier/tests/test_contrats_scan.py -v

Vérifie que :
  - session_scan.schema.json et reconnaissance.schema.json sont des schémas draft-07 valides,
    que leurs exemples passent, que les erreurs courantes sont refusées, et que le validateur de
    atelier.lieu dit la même chose que jsonschema ;
  - le schéma du monde accepte les champs facultatifs categorie, source et confiance, refuse les
    valeurs inconnues, et qu'un monde sans ces champs reste valide ;
  - le lieu demo sert de référence à la reconnaissance : chaque catégorie y est présente, et ses
    passages suivent la règle (trou de 0,7 à 1,6 m entre deux murs alignés).
"""
import copy
import json
import random

import pytest
import yaml

import atelier
from atelier import lieu as L
from atelier.lieu.validation import erreurs_schema
from atelier.tests.test_lieu_validation import MUTATIONS, _chemins, _muter

jsonschema = pytest.importorskip("jsonschema")

DOSSIER_SCHEMAS = atelier.RACINE / "atelier" / "lieu" / "schemas"
DEMO = atelier.RACINE / "lieux" / "demo"

# Exemples du contrat (section 9.2 et 9.3 du plan) : tenus à jour avec le plan
EXEMPLE_SESSION = {
    "version": 1, "id": "2026-10-25_17h42", "lieu": "demo", "etage": "rdc",
    "nom": "Scan rdc du 25/10/2026 à 17h42", "mode": "robot", "repetition": True, "explorer": False,
    "debut": "2026-10-25T17:42:05+01:00", "fin": "2026-10-25T17:55:40+01:00", "maj": "2026-10-25T17:56:12+01:00",
    "etat": "traitement", "etape": "carte_2d", "progression": 57,
    "message": "Fabrication de la carte 2D…",
    "sujets": {"nuage": "/unitree/slam_mapping/points", "odom": "/unitree/slam_mapping/odom",
               "autres": ["/tf_static"]},
    "statistiques": {"duree_s": 815.2, "points": 4718592, "distance_m": 96.4, "nuages": 8152},
    "processus": {"pid": 41234, "debut": 9876543, "hote": "pc-g1"},
    "journal": "/home/joonho/robot-g1/journaux/scan_2026-10-25_17h42.log",
    "carte_unitree": "rdc_2026-10-25_17h42.pcd",
    "adoption": None,
}
EXEMPLE_RECONNAISSANCE = {
    "version": 1, "session": "2026-10-25_17h42", "etage": "rdc",
    "emprise": {"min": [0.0, 0.0], "max": [30.0, 20.0]},
    "depart_robot": {"x": 2.5, "y": 10.0, "theta": 0.0},
    "sol": 0.01, "parametres": {"tranche": [0.1, 1.5]},
    "murs": [
        {"id": "mur_1", "categorie": "mur", "de": [0.0, 5.5], "a": [6.4, 5.5], "epaisseur": 0.15, "hauteur": 2.5,
         "confiance": 0.95, "a_garder": True},
        {"id": "mur_2", "categorie": "mur", "de": [7.6, 5.5], "a": [14.4, 5.5], "epaisseur": 0.15, "hauteur": 2.5,
         "confiance": 0.9, "a_garder": True, "infos": {"points": 5321}},
    ],
    "passages": [
        {"id": "passage_1", "categorie": "passage", "de": [6.4, 5.5], "a": [7.6, 5.5], "murs": ["mur_1", "mur_2"],
         "confiance": 0.85, "a_garder": True},
    ],
    "objets": [
        {"id": "objet_1", "categorie": "table", "forme": "boite", "centre": [29.2, 6.1], "taille": [1.2, 0.8, 0.75],
         "cap": 0.0, "confiance": 0.7, "a_garder": True},
        {"id": "objet_2", "categorie": "poteau", "forme": "cylindre", "centre": [26.0, 10.0], "rayon": 0.2,
         "hauteur": 2.5, "confiance": 0.92, "a_garder": True},
        {"id": "objet_3", "categorie": "personne", "forme": "cylindre", "centre": [21.0, 16.5], "rayon": 0.25,
         "hauteur": 1.7, "confiance": 0.6, "a_garder": False},
    ],
}


def schema(nom):
    return json.loads((DOSSIER_SCHEMAS / f"{nom}.schema.json").read_text(encoding="utf-8"))


def erreurs_js(nom, donnees):
    return [e.message for e in jsonschema.Draft7Validator(schema(nom)).iter_errors(donnees)]


def modifie(exemple, changement):
    donnees = copy.deepcopy(exemple)
    changement(donnees)
    return donnees


# ---------------------------------------------------------------- schémas de la session et de la reconnaissance

@pytest.mark.parametrize("nom", ["session_scan", "reconnaissance", "monde"])
def test_schema_draft07_valide(nom):
    s = schema(nom)
    assert s["$schema"] == "http://json-schema.org/draft-07/schema#"
    jsonschema.Draft7Validator.check_schema(s)


@pytest.mark.parametrize("nom, exemple", [("session_scan", EXEMPLE_SESSION),
                                          ("reconnaissance", EXEMPLE_RECONNAISSANCE)])
def test_exemples_du_contrat_valides(nom, exemple):
    assert erreurs_js(nom, exemple) == []
    assert L.valider_donnees(nom, exemple) == []


REFUS_SCHEMA = {
    "session : mode inconnu": ("session_scan", EXEMPLE_SESSION, lambda d: d.update(mode="drone")),
    "session : état inconnu": ("session_scan", EXEMPLE_SESSION, lambda d: d.update(etat="fini")),
    "session : progression 101": ("session_scan", EXEMPLE_SESSION, lambda d: d.update(progression=101)),
    "session : progression décimale": ("session_scan", EXEMPLE_SESSION, lambda d: d.update(progression=57.5)),
    "session : id sans heure": ("session_scan", EXEMPLE_SESSION, lambda d: d.update(id="2026-10-25")),
    "session : heure sans décalage": ("session_scan", EXEMPLE_SESSION, lambda d: d.update(debut="2026-10-25T17:42:05")),
    "session : sans statistiques": ("session_scan", EXEMPLE_SESSION, lambda d: d.pop("statistiques")),
    "session : distance négative": ("session_scan", EXEMPLE_SESSION,
                                    lambda d: d["statistiques"].update(distance_m=-1)),
    "session : sujet sans /": ("session_scan", EXEMPLE_SESSION, lambda d: d["sujets"].update(nuage="points")),
    "session : champ inconnu": ("session_scan", EXEMPLE_SESSION, lambda d: d.update(etat_robot="ok")),
    "session : carte_unitree sans .pcd": ("session_scan", EXEMPLE_SESSION, lambda d: d.update(carte_unitree="rdc")),
    "reco : mur sans a_garder": ("reconnaissance", EXEMPLE_RECONNAISSANCE, lambda d: d["murs"][0].pop("a_garder")),
    "reco : mur de catégorie table": ("reconnaissance", EXEMPLE_RECONNAISSANCE,
                                      lambda d: d["murs"][0].update(categorie="table")),
    "reco : confiance 1,5": ("reconnaissance", EXEMPLE_RECONNAISSANCE, lambda d: d["objets"][0].update(confiance=1.5)),
    "reco : catégorie inconnue": ("reconnaissance", EXEMPLE_RECONNAISSANCE,
                                  lambda d: d["objets"][0].update(categorie="armoire")),
    "reco : boîte sans taille": ("reconnaissance", EXEMPLE_RECONNAISSANCE, lambda d: d["objets"][0].pop("taille")),
    "reco : cylindre avec cap": ("reconnaissance", EXEMPLE_RECONNAISSANCE, lambda d: d["objets"][1].update(cap=0.0)),
    "reco : forme modele": ("reconnaissance", EXEMPLE_RECONNAISSANCE, lambda d: d["objets"][0].update(forme="modele")),
    "reco : passage à un mur": ("reconnaissance", EXEMPLE_RECONNAISSANCE,
                                lambda d: d["passages"][0].update(murs=["mur_1"])),
    "reco : sans liste passages": ("reconnaissance", EXEMPLE_RECONNAISSANCE, lambda d: d.pop("passages")),
    "reco : a_garder « oui »": ("reconnaissance", EXEMPLE_RECONNAISSANCE,
                                lambda d: d["objets"][2].update(a_garder="oui")),
}


@pytest.mark.parametrize("cas", list(REFUS_SCHEMA))
def test_schema_refuse(cas):
    nom, exemple, changement = REFUS_SCHEMA[cas]
    donnees = modifie(exemple, changement)
    assert erreurs_js(nom, donnees), f"jsonschema aurait dû refuser : {cas}"
    assert L.valider_donnees(nom, donnees), f"atelier.lieu aurait dû refuser : {cas}"


# Règles que le schéma ne peut pas dire (atelier.lieu.validation) : le message attendu, en partie
REFUS_REGLES = {
    "session terminée à 57 %": ("session_scan", EXEMPLE_SESSION, lambda d: d.update(etat="termine", etape="fini"),
                                "progression de 100"),
    "étape qui ne va pas avec l'état": ("session_scan", EXEMPLE_SESSION, lambda d: d.update(etat="en_cours", fin=None),
                                        "ne va pas avec l'état"),
    "fin avant le début": ("session_scan", EXEMPLE_SESSION, lambda d: d.update(fin="2026-10-25T17:00:00+01:00"),
                           "avant le début"),
    "répétition en simu": ("session_scan", EXEMPLE_SESSION, lambda d: d.update(mode="simu", carte_unitree=None),
                           "repetition ne s'emploie qu'en mode robot"),
    "explorer avec le vrai robot": ("session_scan", EXEMPLE_SESSION, lambda d: d.update(repetition=False, explorer=True),
                                    "télécommande"),
    "adoptée avant la fin": ("session_scan", EXEMPLE_SESSION,
                             lambda d: d.update(adoption={"quand": "2026-10-25T18:00:00+01:00", "monde": False}),
                             "seule une session terminée"),
    "id en double": ("reconnaissance", EXEMPLE_RECONNAISSANCE, lambda d: d["objets"][0].update(id="mur_1"),
                     "utilisé 2 fois"),
    "id réservé": ("reconnaissance", EXEMPLE_RECONNAISSANCE, lambda d: d["objets"][0].update(id="sol"), "réservé"),
    "passage trop étroit": ("reconnaissance", EXEMPLE_RECONNAISSANCE,
                            lambda d: (d["murs"][1].update(de=[6.9, 5.5]), d["passages"][0].update(a=[6.9, 5.5])),
                            "un passage est un trou de 0.7 à 1.6 m"),
    "passage trop large": ("reconnaissance", EXEMPLE_RECONNAISSANCE,
                           lambda d: (d["murs"][1].update(de=[8.4, 5.5]), d["passages"][0].update(a=[8.4, 5.5])),
                           "un passage est un trou de 0.7 à 1.6 m"),
    "passage entre murs non alignés": ("reconnaissance", EXEMPLE_RECONNAISSANCE,
                                       lambda d: d["murs"][1].update(de=[7.6, 5.5], a=[7.6, 12.0]),
                                       "ne sont pas alignés"),
    "passage vers un mur inconnu": ("reconnaissance", EXEMPLE_RECONNAISSANCE,
                                    lambda d: d["passages"][0].update(murs=["mur_1", "mur_9"]), "n'existe pas"),
    "passage loin de ses murs": ("reconnaissance", EXEMPLE_RECONNAISSANCE,
                                 lambda d: d["passages"][0].update(de=[6.0, 5.5], a=[7.0, 5.5]), "qui bordent le trou"),
    "objet hors de l'emprise": ("reconnaissance", EXEMPLE_RECONNAISSANCE,
                                lambda d: d["objets"][1].update(centre=[31.0, 10.0]), "sort de l'emprise"),
    "mur de longueur nulle": ("reconnaissance", EXEMPLE_RECONNAISSANCE,
                              lambda d: d["murs"][0].update(a=[0.0, 5.5]), "même endroit"),
}


@pytest.mark.parametrize("cas", list(REFUS_REGLES))
def test_regles_refusent(cas):
    nom, exemple, changement, attendu = REFUS_REGLES[cas]
    donnees = modifie(exemple, changement)
    messages = L.valider_donnees(nom, donnees)
    assert any(attendu in m for m in messages), messages


@pytest.mark.parametrize("nom, exemple", [("session_scan", EXEMPLE_SESSION),
                                          ("reconnaissance", EXEMPLE_RECONNAISSANCE)])
def test_meme_verdict_que_jsonschema(nom, exemple):
    """Sur des centaines de variantes des exemples, atelier.lieu et jsonschema sont d'accord."""
    validateur = jsonschema.Draft7Validator(schema(nom))
    cas = [(c, m) for c in _chemins(exemple) for m in MUTATIONS]
    random.Random(1).shuffle(cas)
    desaccords = []
    for chemin, mutation in cas[:600]:
        variante = _muter(exemple, chemin, mutation)
        nous = bool(erreurs_schema(nom, variante))
        eux = any(True for _ in validateur.iter_errors(variante))
        if nous != eux:
            desaccords.append((chemin, mutation, nous, eux))
    assert desaccords == []


# ---------------------------------------------------------------- monde : champs facultatifs du scan

def monde_demo():
    return yaml.safe_load((DEMO / "mondes" / "rdc.monde.yaml").read_text(encoding="utf-8"))


def test_un_monde_sans_les_nouveaux_champs_reste_valide():
    monde = monde_demo()
    for o in monde["objets"]:
        o.pop("categorie", None)
    assert erreurs_js("monde", monde) == [] and L.valider_donnees("monde", monde) == []
    # monde de la phase 1, tel qu'écrit par creer_lieu
    vieux = {"version": 1, "emprise": {"min": [0, 0], "max": [5, 5]}, "depart_robot": {"x": 1, "y": 1, "theta": 0},
             "murs": [{"id": "m1", "de": [0, 0], "a": [5, 0], "epaisseur": 0.15, "hauteur": 2.5}],
             "objets": [{"id": "c1", "type": "modele", "modele": "chaise", "centre": [2, 2], "cap": 0.0}]}
    assert erreurs_js("monde", vieux) == [] and L.valider_donnees("monde", vieux) == []


def test_un_monde_tire_du_scan_est_valide():
    monde = monde_demo()
    monde["murs"][0].update(source="scan", confiance=0.93)
    monde["objets"][0].update(source="dessin")
    monde["objets"][3].update(source="scan", confiance=1)
    monde["objets"][5].update(categorie="meuble", source="scan", confiance=0.0)
    assert erreurs_js("monde", monde) == [] and L.valider_donnees("monde", monde) == []


REFUS_MONDE = {
    "catégorie inconnue": lambda d: d["objets"][0].update(categorie="armoire"),
    "catégorie mur pour un objet": lambda d: d["objets"][0].update(categorie="mur"),
    "source inconnue": lambda d: d["objets"][3].update(source="lidar"),
    "confiance au-dessus de 1": lambda d: d["objets"][1].update(confiance=1.2),
    "confiance négative": lambda d: d["murs"][0].update(confiance=-0.1),
    "catégorie sur un mur": lambda d: d["murs"][0].update(categorie="mur"),
    "catégorie sur un piéton": lambda d: d["pietons"][0].update(categorie="personne"),
    "a_garder dans le monde": lambda d: d["objets"][0].update(a_garder=True),
}


@pytest.mark.parametrize("cas", list(REFUS_MONDE))
def test_monde_refuse(cas):
    monde = monde_demo()
    REFUS_MONDE[cas](monde)
    assert erreurs_js("monde", monde), cas
    assert L.valider_donnees("monde", monde), cas


def test_dataclasses_aller_retour_avec_les_champs_facultatifs():
    mur = L.Mur("m1", (0.0, 0.0), (3.0, 0.0), 0.15, 2.5, source="scan", confiance=0.9)
    assert L.Mur.depuis_dict(mur.vers_dict()) == mur
    assert mur.vers_dict()["source"] == "scan"
    assert "source" not in L.Mur("m2", (0, 0), (1, 0)).vers_dict()       # absents : non écrits
    table = L.Objet.boite("t1", (1, 2), (1.2, 0.8, 0.75), 0.0, categorie="table", source="scan", confiance=0.7)
    assert L.Objet.depuis_dict(table.vers_dict()) == table
    poteau = L.Objet.cylindre("p1", (3, 3), 0.2, 2.5)
    assert set(poteau.vers_dict()) == {"id", "type", "centre", "rayon", "hauteur"}
    assert L.Objet.depuis_dict(poteau.vers_dict()) == poteau


def test_categorie_effective_et_personne_hors_carte():
    assert L.Objet.cylindre("p", (0, 0), 0.2, 2.5).categorie_effective == "poteau"
    assert L.Objet.boite("b", (0, 0), (1, 1, 1)).categorie_effective == "meuble"
    assert L.Objet.meuble("c", "chaise", (0, 0)).categorie_effective == "chaise"
    assert L.Objet.boite("t", (0, 0), (1, 1, 1), categorie="table").categorie_effective == "table"
    personne = L.Objet.cylindre("h", (0, 0), 0.25, 1.7, categorie="personne")
    assert not personne.sur_la_carte and L.Objet.cylindre("p", (0, 0), 0.2, 2.5).sur_la_carte
    assert L.CATEGORIES_OBJETS == ("table", "chaise", "banc", "poteau", "meuble", "poubelle", "personne", "inconnu")
    # mêmes catégories dans les deux schémas
    assert schema("monde")["definitions"]["categorie_objet"]["enum"] == list(L.CATEGORIES_OBJETS)
    assert (schema("reconnaissance")["definitions"]["objet"]["properties"]["categorie"]["enum"]
            == list(L.CATEGORIES_OBJETS))


def test_une_personne_n_est_jamais_sur_la_carte(tmp_path):
    from atelier.monde.carte import fabriquer_carte
    monde = L.Monde(L.Emprise(0, 0, 4, 4), L.Pose(0.5, 0.5, 0.0))
    _, vide = fabriquer_carte(monde)
    monde.objets.append(L.Objet.cylindre("h1", (2.0, 2.0), 0.25, 1.7, categorie="personne"))
    _, avec_personne = fabriquer_carte(monde)
    assert (vide == avec_personne).all()
    monde.objets.append(L.Objet.cylindre("p1", (3.0, 3.0), 0.25, 1.7))
    _, avec_poteau = fabriquer_carte(monde)
    assert (avec_poteau == 0).sum() > (vide == 0).sum()


# ---------------------------------------------------------------- le lieu de référence (lieux/demo)

def test_demo_reference_toutes_les_categories():
    monde = L.charger_monde(DEMO, "rdc")
    categories = {o.categorie_effective for o in monde.objets}
    assert set(L.CATEGORIES_OBJETS) - {"inconnu"} <= categories
    # la catégorie écrite est celle qu'on déduirait de la forme, sauf pour la personne
    for o in monde.objets:
        assert o.categorie is not None, f"{o.id} : la vérité terrain dit sa catégorie"
        deduite = L.Objet(o.id, o.type, o.centre, o.cap, o.taille, o.rayon, o.hauteur, o.modele).categorie_effective
        assert o.categorie == deduite or o.categorie == "personne", o.id
    assert len(monde.pietons) == 2          # des personnes qui marchent aussi


def test_demo_reference_passages():
    monde = L.charger_monde(DEMO, "rdc")
    passages = L.passages_du_monde(monde)
    assert len(passages) == 5
    for p in passages:
        assert p["largeur"] == pytest.approx(1.2)
        m1, m2 = (monde.element(i) for i in p["murs"])
        assert L.est_passage(m1.de, m1.a, m2.de, m2.a)


def test_demo_reference_au_format_reconnaissance():
    monde = L.charger_monde(DEMO, "rdc")
    verite = L.reconnaissance_depuis_monde(monde, "rdc")
    assert L.valider_reconnaissance(verite) == []
    resume = L.resume_reconnaissance(verite)
    assert resume["murs"] == 18 and resume["passages"] == 5
    assert resume["objets"] == {"meuble": 2, "banc": 1, "poubelle": 1, "poteau": 2, "table": 2, "chaise": 3,
                                "personne": 1}
    assert "personne" not in resume["objets_gardes"]           # a_garder faux par défaut


def test_regle_des_passages():
    assert (L.PASSAGE_MIN, L.PASSAGE_MAX) == (0.7, 1.6)
    mur = ((0.0, 0.0), (5.0, 0.0))
    for ecart, attendu in ((0.69, False), (0.7, True), (1.2, True), (1.6, True), (1.61, False)):
        assert L.est_passage(*mur, (5.0 + ecart, 0.0), (9.0, 0.0)) is attendu, ecart
    assert not L.est_passage(*mur, (6.0, 0.0), (6.0, 4.0))              # perpendiculaire
    assert not L.est_passage(*mur, (6.0, 0.3), (9.0, 0.3))              # parallèle, décalé de 0,3 m
    assert L.est_passage(*mur, (6.0, 0.05), (9.0, 0.05))                # décalé de 5 cm : aligné
    assert L.est_passage(*mur, (9.0, 0.0), (6.0, 0.0))                  # dans l'autre sens
    assert L.trou_entre(*mur, (4.0, 0.0), (9.0, 0.0)) is None           # chevauchement
