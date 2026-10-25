"""Tests de la validation d'un fichier de lieu (atelier.lieu.validation) : messages en français,
règles propres à chaque fichier, et accord du moteur de schéma avec le paquet jsonschema.

  ~/robot-g1/.venv-projet/bin/python -m pytest ~/robot-g1/atelier/tests/test_lieu_validation.py -v
"""
import copy
import math
import random

import pytest
import yaml

import atelier
from atelier.lieu import valider_donnees
from atelier.lieu.validation import TYPES_FICHIERS, charger_schema, erreurs_schema

DEMO = atelier.RACINE / "lieux" / "demo"
FICHIERS = {"lieu": "lieu.yaml", "salles": "salles.yaml", "itineraires": "itineraires.yaml",
            "zones": "zones.yaml", "monde": "mondes/rdc.monde.yaml"}
CARTE = {"image": "rdc.pgm", "resolution": 0.05, "origin": [-0.05, -0.05, 0.0], "negate": 0,
         "occupied_thresh": 0.65, "free_thresh": 0.196}


def lire(nom):
    if nom == "carte":
        return copy.deepcopy(CARTE)
    return yaml.safe_load((DEMO / FICHIERS[nom]).read_text(encoding="utf-8"))


def modifie(nom, changement):
    donnees = lire(nom)
    changement(donnees)
    return donnees


@pytest.mark.parametrize("nom", list(FICHIERS) + ["carte"])
def test_le_demo_est_valide(nom):
    assert valider_donnees(nom, lire(nom)) == []


# Chaque cas : (fichier, modification, message attendu en entier)
MESSAGES = {
    "theta manquant": ("salles", lambda d: d[5]["pose"].pop("theta"),
                       "salles.yaml, salle « b204 » : il manque theta dans pose"),
    "virgule décimale": ("salles", lambda d: d[1]["pose"].update(x="1,5"),
                         "salles.yaml, salle « vie_scolaire » : pose.x doit être un nombre, pas « 1,5 » "
                         "(utilisez un point pour les décimales : 1.5)"),
    "nombre entre guillemets": ("salles", lambda d: d[1]["pose"].update(y="7"),
                                "salles.yaml, salle « vie_scolaire » : pose.y doit être un nombre, pas « 7 » "
                                "(enlevez les guillemets autour du nombre)"),
    "id lu comme booléen": ("salles", lambda d: d[2].update(id=True),
                            "salles.yaml, salle n°3 (« Infirmerie ») : id doit être un texte, pas true (YAML lit "
                            "yes, no, on, off, true et false comme oui ou non : mettez la valeur entre guillemets, "
                            "ou choisissez-en une autre)"),
    "angle en degrés": ("salles", lambda d: d[4]["pose"].update(theta=90),
                        "salles.yaml, salle « amphi » : pose.theta vaut 90 : il faut au plus 6.2832 "
                        "(angle en radians : 90° = 1.5708, 180° = 3.1416)"),
    "alias en double": ("salles", lambda d: d[3].update(alias=["cdi", "cdi"]),
                        "salles.yaml, salle « cdi » : alias contient des doublons : « cdi » ; gardez-en un seul"),
    "nom vide": ("salles", lambda d: d[0].update(nom=""), "salles.yaml, salle « accueil » : nom ne doit pas être vide"),
    "id de salle en double": ("salles", lambda d: d.append(copy.deepcopy(d[1])),
                              "salles.yaml : la salle « vie_scolaire » apparaît 2 fois ; chaque salle doit avoir "
                              "un id différent"),
    "fichier qui n'est pas une liste": ("salles", lambda d: (d.clear(), d.append({"a": 1})) and None,
                                        "salles.yaml, salle n°1 : il manque id"),
    "champ mal orthographié": ("monde", lambda d: d.update(mur=d.pop("murs")),
                               "monde.yaml : champ inconnu « mur » (vouliez-vous écrire « murs » ?) ; champs permis : "
                               "version, emprise, murs, objets, pietons, depart_robot"),
    "point à 3 valeurs": ("monde", lambda d: d["murs"][0].update(de=[0, 0, 0]),
                          "monde.yaml, mur « ext_sud » : de doit avoir exactement 2 valeurs [x, y], pas 3"),
    "épaisseur nulle": ("monde", lambda d: d["murs"][1].update(epaisseur=0),
                        "monde.yaml, mur « ext_est » : epaisseur vaut 0 : il faut plus de 0"),
    "boîte avec un rayon": ("monde", lambda d: d["objets"][0].update(rayon=0.3),
                            "monde.yaml, objet « banque_accueil » : champ « rayon » non permis quand type vaut boite ; "
                            "champs permis : id, type, centre, taille, cap, categorie, source, confiance"),
    "cylindre sans rayon": ("monde", lambda d: d["objets"][3].pop("rayon"),
                            "monde.yaml, objet « poteau_1 » : il manque rayon (obligatoire quand type vaut cylindre)"),
    "modèle inconnu": ("monde", lambda d: d["objets"][1].update(modele="armoire"),
                       "monde.yaml, objet « banc_hall » : modele vaut « armoire » ; valeurs possibles : chaise, table, "
                       "banc, poubelle"),
    "piéton à un point": ("monde", lambda d: d["pietons"][0].update(trajet=[[1, 1]]),
                          "monde.yaml, piéton « pieton_sud » : trajet doit avoir au moins 2 points, pas 1"),
    "aller_retour en texte": ("monde", lambda d: d["pietons"][1].update(aller_retour="oui"),
                              "monde.yaml, piéton « pieton_nord » : aller_retour doit être true ou false, pas « oui »"),
    "version 2": ("monde", lambda d: d.update(version=2), "monde.yaml : version doit valoir 1, pas 2"),
    "valeur vide": ("monde", lambda d: d["depart_robot"].update(x=None),
                    "monde.yaml : depart_robot.x est vide : il faut un nombre"),
    "nombre infini": ("monde", lambda d: d["depart_robot"].update(y=math.inf),
                      "monde.yaml : depart_robot.y doit être un nombre fini, pas inf"),
    "id de monde en double": ("monde", lambda d: d["objets"][0].update(id="ext_sud"),
                              "monde.yaml : l'id « ext_sud » est utilisé 2 fois ; chaque mur, objet et piéton doit "
                              "avoir un id différent (il devient un nom de modèle Gazebo)"),
    "id réservé": ("monde", lambda d: d["murs"][1].update(id="sol"),
                   "monde.yaml, mur « sol » : l'id « sol » est réservé (déjà pris dans le monde Gazebo) ; "
                   "choisissez-en un autre"),
    "mur hors emprise": ("monde", lambda d: d["murs"][2].update(a=[31, 20]),
                         "monde.yaml, mur « ext_nord » : le bout a [31, 20] sort de l'emprise (x de 0 à 30, y de 0 à "
                         "20) ; déplacez-le ou agrandissez l'emprise"),
    "mur de longueur nulle": ("monde", lambda d: d["murs"][3].update(a=[0.0, 20.0]),
                              "monde.yaml, mur « ext_ouest » : ses deux bouts sont au même endroit [0, 20] ; un mur "
                              "doit avoir une longueur"),
    "emprise retournée": ("monde", lambda d: d["emprise"].update(max=[-1, 20]),
                          "monde.yaml, emprise : en x, max (-1) doit être plus grand que min (0)"),
    "objet hors emprise": ("monde", lambda d: d["objets"][2].update(centre=[4.5, 21]),
                           "monde.yaml, objet « poubelle_hall » : le centre [4.5, 21] sort de l'emprise (x de 0 à 30, "
                           "y de 0 à 20) ; déplacez-le ou agrandissez l'emprise"),
    "piéton immobile": ("monde", lambda d: d["pietons"][1].update(trajet=[[6, 13.8], [6, 13.8], [8, 13.8]]),
                        "monde.yaml, piéton « pieton_nord » : les points n°1 et n°2 du trajet sont identiques ; "
                        "retirez l'un des deux"),
    "départ hors emprise": ("monde", lambda d: d["depart_robot"].update(x=-2),
                            "monde.yaml, depart_robot : [-2, 10] sort de l'emprise (x de 0 à 30, y de 0 à 20)"),
    "couloir en boucle": ("itineraires", lambda d: d["couloirs"].append(["amphi", "amphi"]),
                          "itineraires.yaml, couloir n°14 [\"amphi\", \"amphi\"] : un couloir doit relier deux nœuds "
                          "différents"),
    "couloir à 3 nœuds": ("itineraires", lambda d: d["couloirs"].append(["amphi", "cdi", "b204"]),
                          "itineraires.yaml, couloir n°14 [\"amphi\", \"cdi\", \"b204\"] : un couloir relie exactement "
                          "2 nœuds, [nœud1, nœud2], pas 3"),
    "nœud inconnu": ("itineraires", lambda d: d["couloirs"].append(["amphi", "b2o4"]),
                     "itineraires.yaml, couloir n°14 [\"amphi\", \"b2o4\"] : le nœud « b2o4 » n'existe pas (vouliez-"
                     "vous écrire « b204 » ?)"),
    "id de nœud en majuscules": ("itineraires", lambda d: d["noeuds"].update(Hall={"etage": "rdc", "x": 1, "y": 1}),
                                 "itineraires.yaml : l'id « Hall » dans noeuds n'est pas valable : lettres minuscules "
                                 "sans accent, chiffres, _ et -, 40 caractères au plus, en commençant par une lettre "
                                 "ou un chiffre (ex. salle_b204)"),
    "nœud avec theta": ("itineraires", lambda d: d["noeuds"]["amphi"].update(theta=0.0),
                        "itineraires.yaml, nœud « amphi » : champ inconnu « theta » ; champs permis : etage, x, y"),
    "polygone fermé deux fois": ("zones", lambda d: d["interdites"][0]["polygone"].append([0.2, 12.2]),
                                 "zones.yaml, zone interdite n°1 (« Escalier ») : le dernier sommet répète le "
                                 "premier ; retirez-le (le contour se ferme tout seul)"),
    "polygone en 8": ("zones", lambda d: d["interdites"][0].update(polygone=[[0, 0], [1, 1], [1, 0], [0, 1]]),
                      "zones.yaml, zone interdite n°1 (« Escalier ») : le contour se croise (forme en 8) ; remettez "
                      "les sommets dans l'ordre du contour"),
    "polygone plat": ("zones", lambda d: d["lentes"][0].update(polygone=[[0, 0], [1, 1], [2, 2]]),
                      "zones.yaml, zone lente n°1 (« Hall d'accueil ») : le polygone n'a pas de surface "
                      "(sommets alignés)"),
    "polygone à 2 sommets": ("zones", lambda d: d["interdites"][0].update(polygone=[[0, 0], [1, 1]]),
                             "zones.yaml, zone interdite n°1 (« Escalier ») : polygone doit avoir au moins 3 sommets, "
                             "pas 2"),
    "liste lentes manquante": ("zones", lambda d: d.pop("lentes"),
                               "zones.yaml : il manque lentes ; s'il n'y en a pas, écrivez « lentes: [] »"),
    "accueil manquant": ("lieu", lambda d: d.pop("accueil"), "lieu.yaml : il manque accueil"),
    "langue en majuscules": ("lieu", lambda d: d.update(langue="FR"),
                             "lieu.yaml : langue doit être un code de langue en deux lettres minuscules (ex. fr), "
                             "pas « FR »"),
    "source de carte inconnue": ("lieu", lambda d: d["etages"][0].update(source_carte="plan"),
                                 "lieu.yaml, étage « rdc » : source_carte vaut « plan » ; valeurs possibles : "
                                 "monde, scan"),
    "carte_unitree sans .pcd": ("lieu", lambda d: d.update(carte_unitree="test1"),
                                "lieu.yaml : carte_unitree doit être un nom de fichier .pcd sans dossier (ex. "
                                "test1.pcd), ou null"),
    "étage en double": ("lieu", lambda d: d["etages"].append(dict(d["etages"][0])),
                        "lieu.yaml : l'étage « rdc » apparaît 2 fois ; chaque étage doit avoir un id différent"),
    "accueil sur un étage inconnu": ("lieu", lambda d: d["accueil"].update(etage="r1"),
                                     "lieu.yaml, accueil : l'étage « r1 » n'existe pas ; étages du lieu : rdc"),
    "image dans un dossier": ("carte", lambda d: d.update(image="cartes/rdc.pgm"),
                              "carte.yaml : image doit être un nom de fichier .pgm, sans dossier (ex. rdc.pgm), "
                              "pas « cartes/rdc.pgm »"),
    "origin à 2 valeurs": ("carte", lambda d: d.update(origin=[0, 0]),
                           "carte.yaml : origin doit avoir exactement 3 valeurs [x, y, lacet], pas 2"),
    "carte tournée": ("carte", lambda d: d.update(origin=[0, 0, 0.5]),
                      "carte.yaml, origin : le lacet (3e valeur) doit valoir 0.0 ; l'Atelier ne gère pas les "
                      "cartes tournées"),
}


@pytest.mark.parametrize("cas", list(MESSAGES))
def test_message_en_francais(cas):
    nom, changement, attendu = MESSAGES[cas]
    assert attendu in valider_donnees(nom, modifie(nom, changement))


def test_nom_de_fichier_dans_les_messages():
    donnees = modifie("monde", lambda d: d["murs"][1].update(epaisseur=0))
    assert valider_donnees("monde", donnees, "mondes/rdc.monde.yaml") == [
        "mondes/rdc.monde.yaml, mur « ext_est » : epaisseur vaut 0 : il faut plus de 0"]


def test_fichier_du_mauvais_type():
    assert valider_donnees("salles", {"a": 1}) == [
        "salles.yaml : le fichier doit contenir une liste [ … ], pas {\"a\": 1}"]


def test_mot_cle_inconnu_refuse():
    from atelier.lieu.validation import _valider
    with pytest.raises(ValueError, match="non pris en charge"):
        _valider(1, {"multipleOf": 2}, {}, (), [])


# ---------------------------------------------------------------- accord avec jsonschema

def _chemins(donnees, chemin=()):
    """Tous les chemins vers une valeur des données."""
    yield chemin
    if isinstance(donnees, dict):
        for k, v in donnees.items():
            yield from _chemins(v, chemin + (k,))
    elif isinstance(donnees, list):
        for i, v in enumerate(donnees):
            yield from _chemins(v, chemin + (i,))


MUTATIONS = ["supprimer", None, "texte", -1e9, 1e9, 0, True, [], {}, [1.0, 2.0], "champ_en_trop", "rdc", 7]


def _muter(donnees, chemin, mutation):
    copie = copy.deepcopy(donnees)
    if not chemin:
        return mutation if mutation not in ("supprimer", "champ_en_trop") else copie
    parent = copie
    for p in chemin[:-1]:
        parent = parent[p]
    dernier = chemin[-1]
    if mutation == "supprimer":
        del parent[dernier]
    elif mutation == "champ_en_trop":
        if isinstance(parent[dernier], dict):
            parent[dernier]["zzz"] = 1
        else:
            parent[dernier] = {"zzz": 1}
    else:
        parent[dernier] = copy.deepcopy(mutation)
    return copie


@pytest.mark.parametrize("nom", list(FICHIERS) + ["carte"])
def test_meme_verdict_que_jsonschema(nom):
    """Sur des centaines de variantes du demo, notre moteur et jsonschema acceptent et refusent les mêmes."""
    jsonschema = pytest.importorskip("jsonschema")
    validateur = jsonschema.Draft7Validator(charger_schema(nom))
    donnees = lire(nom)
    cas = [(c, m) for c in _chemins(donnees) for m in MUTATIONS]
    random.Random(0).shuffle(cas)
    desaccords = []
    for chemin, mutation in cas[:600]:
        variante = _muter(donnees, chemin, mutation)
        nous = bool(erreurs_schema(nom, variante))
        eux = any(True for _ in validateur.iter_errors(variante))
        if nous != eux:
            desaccords.append((chemin, mutation, nous, eux))
    assert desaccords == []


def test_tous_les_schemas_sont_pris_en_charge():
    for nom in TYPES_FICHIERS:
        erreurs_schema(nom, {})    # ne lève pas « mot-clé non pris en charge »
