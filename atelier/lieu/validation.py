"""Validation des fichiers d'un lieu, avec des messages en français qui disent quoi corriger.

Deux niveaux, pour un fichier seul :
  1. son schéma JSON (atelier/lieu/schemas/<type>.schema.json, draft-07) ;
  2. les règles de ce fichier que le schéma ne peut pas exprimer (ids uniques, murs de longueur
     nulle, polygone qui répète son premier sommet...).
Les règles entre fichiers (salle ↔ nœud, couloirs de 8 m au plus...) sont dans verification.py.

Le moteur de schéma est écrit ici, sans le paquet jsonschema : le Python du système, celui des
nœuds ROS 2, ne l'a pas. Il couvre les mots-clés draft-07 utilisés par nos schémas, et refuse
les autres (un test le compare à jsonschema).

  valider_donnees("salles", donnees, "salles.yaml")  → liste de messages, vide si tout va bien
"""
import difflib
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

from . import geometrie
from .modeles import ETIQUETTE_PRINCIPAL

DOSSIER_SCHEMAS = Path(__file__).resolve().parent / "schemas"
TYPES_FICHIERS = ("lieu", "monde", "salles", "itineraires", "zones", "carte", "session_scan", "reconnaissance",
                  "etat_pont", "etat_reperage", "demande_reperage",
                  # vague 4 (section 11 du plan) : fichiers du lieu pour l'équipe, scènes de passants,
                  # chorégraphies, puis messages JSON (std_msgs/String) des nouveaux sujets
                  "personnalites", "dialogues", "camera", "scene", "choregraphie",
                  "etat_guide", "evenement_guide", "demande_guide", "pietons_etat", "pietons_consigne",
                  "personnes", "maitre_mouvement", "etat_pilotage", "robot_dire", "personnalite_active")
# Les messages ne sont pas des fichiers : ce sont les messages JSON (std_msgs/String) du pont, du
# repérage (section 10 du plan) et des sujets de la vague 4 ; le nom affiché est celui du sujet ROS 2.
NOMS_FICHIERS = {"lieu": "lieu.yaml", "monde": "monde.yaml", "salles": "salles.yaml",
                 "itineraires": "itineraires.yaml", "zones": "zones.yaml", "carte": "carte.yaml",
                 "session_scan": "session.json", "reconnaissance": "reconnaissance.yaml",
                 "etat_pont": "/pont/etat", "etat_reperage": "/reperage/etat",
                 "demande_reperage": "/reperage/demander",
                 "personnalites": "personnalites.yaml", "dialogues": "dialogues.yaml", "camera": "camera.yaml",
                 "scene": "scène", "choregraphie": "chorégraphie",
                 "etat_guide": "/guide/etat", "evenement_guide": "/guide/evenement", "demande_guide": "/guide/aller",
                 "pietons_etat": "/pietons/etat", "pietons_consigne": "/pietons/consigne",
                 "personnes": "/personnes/lidar", "maitre_mouvement": "/mouvement/maitre",
                 "etat_pilotage": "/pilotage/etat", "robot_dire": "/robot/dire",
                 "personnalite_active": "/personnalite/active"}
TYPES_MESSAGES = ("etat_pont", "etat_reperage", "demande_reperage", "etat_guide", "evenement_guide",
                  "demande_guide", "pietons_etat", "pietons_consigne", "personnes", "maitre_mouvement",
                  "etat_pilotage", "robot_dire", "personnalite_active")
IDS_RESERVES = ("sol", "g1_proxy")                 # noms de modèles Gazebo déjà pris
IDS_BOOLEENS = ("yes", "no", "on", "off", "y", "n", "true", "false")
REGLE_ID = ("lettres minuscules sans accent, chiffres, _ et -, 40 caractères au plus, "
            "en commençant par une lettre ou un chiffre (ex. salle_b204)")
INDICE_BOOLEEN = ("YAML lit yes, no, on, off, true et false comme oui ou non : "
                  "mettez la valeur entre guillemets, ou choisissez-en une autre")


@lru_cache(maxsize=None)
def charger_schema(type_fichier):
    """Schéma JSON d'un type de fichier : lieu, monde, salles, itineraires, zones, carte,
    session_scan (scans/<session>/session.json) ou reconnaissance (scans/<session>/reconnaissance.yaml)."""
    if type_fichier not in TYPES_FICHIERS:
        raise ValueError(f"type de fichier inconnu : {type_fichier} (attendu : {', '.join(TYPES_FICHIERS)})")
    return json.loads((DOSSIER_SCHEMAS / f"{type_fichier}.schema.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- moteur de schéma (draft-07)

MOTS_IGNORES = {"$schema", "$id", "$comment", "title", "description", "definitions", "default", "examples"}
MOTS_CONNUS = {"$ref", "type", "enum", "const", "pattern", "minLength", "maxLength", "minimum", "maximum",
               "exclusiveMinimum", "exclusiveMaximum", "minItems", "maxItems", "uniqueItems", "items",
               "required", "properties", "additionalProperties", "propertyNames", "allOf", "anyOf",
               "oneOf", "if", "then", "else"}


@dataclass
class ErreurSchema:
    """Une erreur de schéma, avant traduction en français."""
    chemin: tuple                  # où, dans les données : ("salles", 1, "pose")...
    mot_cle: str                   # mot-clé du schéma qui refuse : required, type, pattern...
    attendu: object                # valeur de ce mot-clé dans le schéma
    valeur: object                 # valeur trouvée dans les données
    schema: dict                   # sous-schéma en cause
    nom_champ: Optional[str] = None     # champ manquant, inconnu, ou nom de champ refusé
    sur_nom: bool = False               # erreur sur le nom d'un champ (propertyNames)
    condition: Optional[dict] = None    # schéma « if » quand l'erreur vient d'un « then »


def _est_nombre(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _a_le_type(v, t):
    if isinstance(t, list):
        return any(_a_le_type(v, u) for u in t)
    return {"null": v is None,
            "boolean": isinstance(v, bool),
            "integer": _est_nombre(v) and (isinstance(v, int) or float(v).is_integer()),
            "number": _est_nombre(v),
            "string": isinstance(v, str),
            "array": isinstance(v, (list, tuple)),
            "object": isinstance(v, dict)}[t]


def _egal(a, b):
    """Égalité au sens JSON : true n'est pas 1, et 1 vaut 1.0."""
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_egal(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_egal(a[k], b[k]) for k in a)
    return a == b


def _resoudre(racine, ref):
    if not ref.startswith("#"):
        raise ValueError(f"référence de schéma non prise en charge : {ref}")
    noeud = racine
    for partie in [p for p in ref[1:].split("/") if p]:
        noeud = noeud[partie.replace("~1", "/").replace("~0", "~")]
    return noeud


def _est_valide(v, schema, racine):
    sortie = []
    _valider(v, schema, racine, (), sortie)
    return not sortie


def _valider(v, s, racine, chemin, sortie, condition=None):
    if s is True:
        return
    if s is False:
        sortie.append(ErreurSchema(chemin, "false", False, v, {}, condition=condition))
        return
    if "$ref" in s:      # draft-07 : les autres mots-clés à côté de $ref sont ignorés
        _valider(v, _resoudre(racine, s["$ref"]), racine, chemin, sortie, condition)
        return
    inconnus = set(s) - MOTS_CONNUS - MOTS_IGNORES
    if inconnus:
        raise ValueError(f"mot-clé de schéma non pris en charge par atelier.lieu : {sorted(inconnus)}")

    def erreur(mot, **autres):
        sortie.append(ErreurSchema(chemin, mot, s.get(mot), v, s, condition=condition, **autres))

    if "type" in s and not _a_le_type(v, s["type"]):
        erreur("type")
        return          # inutile d'aller plus loin : le reste suppose le bon type
    if "enum" in s and not any(_egal(v, e) for e in s["enum"]):
        erreur("enum")
    if "const" in s and not _egal(v, s["const"]):
        erreur("const")
    if isinstance(v, str):
        if "pattern" in s and not re.search(s["pattern"], v):
            erreur("pattern")
        if "minLength" in s and len(v) < s["minLength"]:
            erreur("minLength")
        if "maxLength" in s and len(v) > s["maxLength"]:
            erreur("maxLength")
    if _est_nombre(v):
        if not math.isfinite(v):
            erreur("fini")
        for mot, refuse in (("minimum", lambda x, b: x < b), ("maximum", lambda x, b: x > b),
                            ("exclusiveMinimum", lambda x, b: x <= b),
                            ("exclusiveMaximum", lambda x, b: x >= b)):
            if mot in s and refuse(v, s[mot]):
                erreur(mot)
    if isinstance(v, (list, tuple)):
        if "minItems" in s and len(v) < s["minItems"]:
            erreur("minItems")
        if "maxItems" in s and len(v) > s["maxItems"]:
            erreur("maxItems")
        if s.get("uniqueItems") and any(_egal(v[i], v[j]) for i in range(len(v)) for j in range(i)):
            erreur("uniqueItems")
        if "items" in s:
            if isinstance(s["items"], list):
                for i, (x, sous) in enumerate(zip(v, s["items"])):
                    _valider(x, sous, racine, chemin + (i,), sortie, condition)
            else:
                for i, x in enumerate(v):
                    _valider(x, s["items"], racine, chemin + (i,), sortie, condition)
    if isinstance(v, dict):
        for nom in s.get("required", []):
            if nom not in v:
                erreur("required", nom_champ=nom)
        proprietes = s.get("properties", {})
        for nom, sous in proprietes.items():
            if nom in v:
                _valider(v[nom], sous, racine, chemin + (nom,), sortie, condition)
        if "additionalProperties" in s:
            autres = s["additionalProperties"]
            for nom in [k for k in v if k not in proprietes]:
                if autres is False:
                    erreur("additionalProperties", nom_champ=nom)
                elif isinstance(autres, dict):
                    _valider(v[nom], autres, racine, chemin + (nom,), sortie, condition)
        if "propertyNames" in s:
            for nom in v:
                sous_erreurs = []
                _valider(nom, s["propertyNames"], racine, chemin, sous_erreurs, condition)
                for e in sous_erreurs:
                    e.nom_champ, e.sur_nom = nom, True
                sortie.extend(sous_erreurs)
    for sous in s.get("allOf", []):
        _valider(v, sous, racine, chemin, sortie, condition)
    if "anyOf" in s and not any(_est_valide(v, sous, racine) for sous in s["anyOf"]):
        erreur("anyOf")
    if "oneOf" in s and sum(_est_valide(v, sous, racine) for sous in s["oneOf"]) != 1:
        erreur("oneOf")
    if "if" in s:
        if _est_valide(v, s["if"], racine):
            if "then" in s:
                _valider(v, s["then"], racine, chemin, sortie, s["if"])
        elif "else" in s:
            _valider(v, s["else"], racine, chemin, sortie, condition)


def erreurs_schema(type_fichier, donnees):
    """Erreurs brutes (ErreurSchema) des données face au schéma du type de fichier."""
    schema = charger_schema(type_fichier)
    sortie = []
    _valider(donnees, schema, schema, (), sortie)
    return sortie


# ---------------------------------------------------------------- traduction en français

TYPES_FR = {"number": "un nombre", "integer": "un nombre entier", "string": "un texte",
            "array": "une liste [ … ]", "object": "un ensemble de champs { … }",
            "boolean": "true ou false", "null": "null"}
MOTS_ELEMENTS = {"murs": "mur", "objets": "objet", "pietons": "piéton", "etages": "étage",
                 "interdites": "zone interdite", "lentes": "zone lente", "passages": "passage",
                 "personnalites": "personnalité", "regles": "règle", "pas": "pas", "gestes": "geste",
                 "led": "couleur", "paroles": "parole"}
UNITES = {"polygone": "sommet", "trajet": "point", "alias": "alias", "etages": "étage",
          "taille": "valeur", "origin": "valeur", "centre": "coordonnée", "de": "coordonnée",
          "a": "coordonnée", "min": "coordonnée", "max": "coordonnée"}
FORMES = {"de": "[x, y]", "a": "[x, y]", "centre": "[x, y]", "min": "[x, y]", "max": "[x, y]",
          "origin": "[x, y, lacet]", "taille": "[longueur, largeur, hauteur]"}


def nombre(v):
    """Nombre lisible : 2.5, 30, 0.196."""
    return f"{v:.10g}" if isinstance(v, float) else str(v)


def montrer(v):
    """Valeur telle qu'on la montre dans un message."""
    if v is None:
        return "une valeur vide"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        return f"« {v} »"
    if _est_nombre(v):
        return nombre(v)
    texte = json.dumps(v, ensure_ascii=False, default=str)
    return texte if len(texte) <= 60 else texte[:57] + "…"


def _nomme(mot, element, rang):
    if isinstance(element, dict):
        if isinstance(element.get("id"), str) and element["id"]:
            return f"{mot} « {element['id']} »"
        if isinstance(element.get("nom"), str) and element["nom"]:
            return f"{mot} n°{rang + 1} (« {element['nom']} »)"
    return f"{mot} n°{rang + 1}"


def _element(type_fichier, donnees, chemin):
    """Description de l'élément en cause (« salle « b204 » ») et reste du chemin."""
    c = list(chemin)
    try:
        if type_fichier == "salles" and c and isinstance(c[0], int):
            return _nomme("salle", donnees[c[0]], c[0]), c[1:]
        if len(c) >= 2 and isinstance(c[1], int) and c[0] in MOTS_ELEMENTS:
            return _nomme(MOTS_ELEMENTS[c[0]], donnees[c[0]][c[1]], c[1]), c[2:]
        if type_fichier == "itineraires" and len(c) >= 2 and c[0] == "noeuds":
            return f"nœud « {c[1]} »", c[2:]
        if type_fichier == "itineraires" and len(c) >= 2 and c[0] == "couloirs":
            couloir = donnees["couloirs"][c[1]]
            texte = f" {montrer(couloir)}" if isinstance(couloir, list) else ""
            return f"couloir n°{c[1] + 1}{texte}", c[2:]
    except (IndexError, KeyError, TypeError):
        pass
    return "", c


def _champ(reste, type_fichier=""):
    """Nom lisible du champ : « pose.theta », « polygone, sommet n°3 »."""
    morceaux, precedent = [], None
    for p in reste:
        if isinstance(p, int):
            unite = UNITES.get(precedent, "nœud" if type_fichier == "itineraires" else "élément")
            morceaux.append(f", {unite} n°{p + 1}")
        else:
            morceaux.append(("." if morceaux else "") + str(p))
        precedent = p
    return "".join(morceaux).lstrip(", ")


def _condition(e):
    """« quand type vaut boite » pour une erreur venue d'un if/then."""
    if not e.condition:
        return ""
    for nom, sous in e.condition.get("properties", {}).items():
        if isinstance(sous, dict) and "const" in sous:
            return f" quand {nom} vaut {sous['const']}"
    return ""


def _indice_type(v, attendu):
    types = attendu if isinstance(attendu, list) else [attendu]
    if isinstance(v, bool) and "boolean" not in types:
        return INDICE_BOOLEEN
    if isinstance(v, str) and ("number" in types or "integer" in types):
        if re.fullmatch(r"\s*-?\d+,\d+\s*", v):
            return f"utilisez un point pour les décimales : {v.strip().replace(',', '.')}"
        try:
            float(v)
            return "enlevez les guillemets autour du nombre"
        except ValueError:
            return ""
    if _est_nombre(v) and "string" in types:
        return "mettez-le entre guillemets"
    return ""


def _texte(e, champ, type_fichier):
    """Le problème et la correction, en français, sans la position."""
    v, n = e.valeur, e.attendu
    dans = f" dans {champ}" if champ else ""
    sujet = champ or "la valeur"
    nom_dernier = next((p for p in reversed(e.chemin) if isinstance(p, str)), "")

    if e.sur_nom:
        if e.mot_cle == "enum":
            return (f"champ « {e.nom_champ} » non permis{dans}{_condition(e)} ; "
                    f"champs permis : {', '.join(map(str, n))}")
        if e.mot_cle == "type":
            return f"l'id {montrer(e.nom_champ)}{dans} ne peut pas servir d'identifiant : {INDICE_BOOLEEN}"
        if e.mot_cle == "pattern":
            return f"l'id « {e.nom_champ} »{dans} n'est pas valable : {REGLE_ID}"
        return f"nom de champ « {e.nom_champ} » refusé{dans}"

    if e.mot_cle == "required":
        texte = f"il manque {e.nom_champ}{dans}"
        if _condition(e):
            texte += f" (obligatoire{_condition(e)})"
        sous = e.schema.get("properties", {}).get(e.nom_champ, {})
        if isinstance(sous, dict) and sous.get("type") == "array":
            texte += f" ; s'il n'y en a pas, écrivez « {e.nom_champ}: [] »"
        return texte
    if e.mot_cle == "additionalProperties":
        permis = list(e.schema.get("properties", {}))
        texte = f"champ inconnu « {e.nom_champ} »{dans}"
        proche = difflib.get_close_matches(str(e.nom_champ), permis, n=1, cutoff=0.75)
        if proche:
            texte += f" (vouliez-vous écrire « {proche[0]} » ?)"
        if permis:
            texte += f" ; champs permis : {', '.join(permis)}"
        return texte
    if e.mot_cle == "type":
        types = n if isinstance(n, list) else [n]
        attendu = " ou ".join(TYPES_FR.get(t, t) for t in types)
        if v is None:
            texte = f"{sujet} est vide : il faut {attendu}"
        elif not champ and not e.chemin:
            texte = f"le fichier doit contenir {attendu}, pas {montrer(v)}"
        else:
            texte = f"{sujet} doit être {attendu}, pas {montrer(v)}"
        indice = _indice_type(v, n)
        return f"{texte} ({indice})" if indice else texte
    if e.mot_cle == "enum":
        return f"{sujet} vaut {montrer(v)} ; valeurs possibles : {', '.join(map(str, n))}"
    if e.mot_cle == "const":
        return f"{sujet} doit valoir {montrer(n)}, pas {montrer(v)}"
    if e.mot_cle == "pattern":
        if n == r"^[a-z0-9][a-z0-9_-]{0,39}$":
            if champ:
                return f"{champ} vaut {montrer(v)}, qui n'est pas un identifiant valable : {REGLE_ID}"
            return f"{montrer(v)} n'est pas un identifiant valable : {REGLE_ID}"
        if n.endswith(r"\.pgm$"):
            return f"{sujet} doit être un nom de fichier .pgm, sans dossier (ex. rdc.pgm), pas {montrer(v)}"
        if n.endswith(r"\.pcd$"):
            return f"{sujet} doit être un nom de fichier .pcd sans dossier (ex. test1.pcd), ou null"
        if n == "^[a-z]{2}$":
            return f"{sujet} doit être un code de langue en deux lettres minuscules (ex. fr), pas {montrer(v)}"
        if n.startswith("^[0-9]{4}-[0-9]{2}-[0-9]{2}T"):
            return (f"{sujet} doit être une date et une heure ISO 8601 avec le décalage horaire "
                    f"(ex. 2026-10-25T17:42:05+01:00), pas {montrer(v)}")
        if n.startswith("^[0-9]{4}-[0-9]{2}-[0-9]{2}_"):
            return (f"{sujet} doit être un identifiant de session AAAA-MM-JJ_HHhMM (ex. 2026-10-25_17h42), "
                    f"pas {montrer(v)}")
        if n.startswith("^(/[A-Za-z_]"):
            return f"{sujet} doit être un nom complet de sujet ROS 2 (ex. /points), pas {montrer(v)}"
        return f"{sujet} vaut {montrer(v)}, qui n'a pas la forme attendue ({n})"
    if e.mot_cle == "minLength":
        return f"{sujet} ne doit pas être vide" if n == 1 else f"{sujet} doit faire au moins {n} caractères"
    if e.mot_cle == "maxLength":
        return f"{sujet} est trop long : {len(v)} caractères, {n} au plus"
    if e.mot_cle in ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"):
        borne = {"minimum": "au moins", "maximum": "au plus",
                 "exclusiveMinimum": "plus de", "exclusiveMaximum": "moins de"}[e.mot_cle]
        texte = f"{sujet} vaut {nombre(v)} : il faut {borne} {nombre(n)}"
        if abs(abs(n) - 6.2832) < 1e-9:
            texte += " (angle en radians : 90° = 1.5708, 180° = 3.1416)"
        return texte
    if e.mot_cle in ("minItems", "maxItems"):
        mini, maxi = e.schema.get("minItems"), e.schema.get("maxItems")
        if mini == maxi and type_fichier == "itineraires" and not champ:
            return f"un couloir relie exactement 2 nœuds, [nœud1, nœud2], pas {len(v)}"
        if mini == maxi:
            forme = FORMES.get(nom_dernier, "[x, y]" if mini == 2 else "")
            return f"{sujet} doit avoir exactement {mini} valeurs{' ' + forme if forme else ''}, pas {len(v)}"
        unite = {"polygone": "sommets", "trajet": "points", "etages": "étage(s)"}.get(nom_dernier, "éléments")
        if e.mot_cle == "minItems":
            return f"{sujet} doit avoir au moins {mini} {unite}, pas {len(v)}"
        return f"{sujet} doit avoir au plus {maxi} {unite}, pas {len(v)}"
    if e.mot_cle == "uniqueItems":
        if type_fichier == "itineraires" and not champ:
            return "un couloir doit relier deux nœuds différents"
        doubles = []
        for i, x in enumerate(v):
            if any(_egal(x, y) for y in v[:i]) and not any(_egal(x, y) for y in doubles):
                doubles.append(x)
        return f"{sujet} contient des doublons : {', '.join(map(montrer, doubles))} ; gardez-en un seul"
    if e.mot_cle == "fini":
        return f"{sujet} doit être un nombre fini, pas {montrer(v)}"
    if e.mot_cle == "false":
        return f"{sujet} n'est pas permis"
    if e.mot_cle == "anyOf":
        return (f"{sujet} vaut {montrer(v)}, qui n'est pas permis ici "
                f"(voir la description de ce champ dans atelier/lieu/schemas/{type_fichier}.schema.json)")
    return f"{sujet} : valeur refusée par le schéma ({e.mot_cle})"


def traduire(erreur, type_fichier, donnees, fichier=None):
    """Message complet en français : « salles.yaml, salle « b204 » : il manque theta dans pose »."""
    fichier = fichier or NOMS_FICHIERS[type_fichier]
    element, reste = _element(type_fichier, donnees, erreur.chemin)
    texte = _texte(erreur, _champ(reste, type_fichier), type_fichier)
    return f"{fichier}, {element} : {texte}" if element else f"{fichier} : {texte}"


# ---------------------------------------------------------------- règles propres à chaque fichier

def _doublons(valeurs):
    return [v for v, k in Counter(valeurs).items() if k > 1]


def _point_texte(p):
    return f"[{nombre(p[0])}, {nombre(p[1])}]"


def regles_lieu(d, fichier="lieu.yaml"):
    messages = []
    ids = [e["id"] for e in d["etages"]]
    for i in _doublons(ids):
        messages.append(f"{fichier} : l'étage « {i} » apparaît {ids.count(i)} fois ; "
                        "chaque étage doit avoir un id différent")
    if d["accueil"]["etage"] not in ids:
        messages.append(f"{fichier}, accueil : l'étage « {d['accueil']['etage']} » n'existe pas ; "
                        f"étages du lieu : {', '.join(dict.fromkeys(ids))}")
    return messages


def regles_salles(d, fichier="salles.yaml"):
    ids = [s["id"] for s in d]
    messages = [f"{fichier} : la salle « {i} » apparaît {ids.count(i)} fois ; chaque salle doit avoir un id différent"
                for i in _doublons(ids)]
    # vague 4 (section 11.2) : un seul point principal par lieu
    principales = [s["id"] for s in d if ETIQUETTE_PRINCIPAL in s.get("etiquettes", [])]
    if len(principales) > 1:
        messages.append(f"{fichier} : {len(principales)} salles portent l'étiquette « {ETIQUETTE_PRINCIPAL} » "
                        f"({', '.join(principales)}) ; un lieu n'a qu'un point principal : retirez-la des autres")
    return messages


def regles_itineraires(d, fichier="itineraires.yaml"):
    messages = []
    noeuds = list(d["noeuds"])
    for i, couloir in enumerate(d["couloirs"]):
        for id_noeud in couloir:
            if id_noeud not in d["noeuds"]:
                proche = difflib.get_close_matches(id_noeud, noeuds, n=1, cutoff=0.6)
                conseil = f"vouliez-vous écrire « {proche[0]} » ?" if proche else "ajoutez-le dans noeuds"
                messages.append(f"{fichier}, couloir n°{i + 1} {montrer(couloir)} : "
                                f"le nœud « {id_noeud} » n'existe pas ({conseil})")
    return messages


def _regles_polygone(polygone, ou):
    pts = [tuple(p) for p in polygone]
    if len(pts) >= 2 and pts[0] == pts[-1]:
        return [f"{ou} : le dernier sommet répète le premier ; retirez-le (le contour se ferme tout seul)"]
    for i in range(len(pts) - 1):
        if pts[i] == pts[i + 1]:
            return [f"{ou} : les sommets n°{i + 1} et n°{i + 2} sont identiques ; retirez l'un des deux"]
    if geometrie.polygone_croise(pts):
        return [f"{ou} : le contour se croise (forme en 8) ; remettez les sommets dans l'ordre du contour"]
    if geometrie.aire_polygone(pts) < 1e-6:
        return [f"{ou} : le polygone n'a pas de surface (sommets alignés)"]
    return []


def regles_zones(d, fichier="zones.yaml"):
    messages = []
    for cle in ("interdites", "lentes"):
        for i, z in enumerate(d[cle]):
            messages += _regles_polygone(z["polygone"], f"{fichier}, {_nomme(MOTS_ELEMENTS[cle], z, i)}")
    return messages


def regles_monde(d, fichier="monde.yaml"):
    messages = []
    elements = [(MOTS_ELEMENTS[cle], e) for cle in ("murs", "objets", "pietons") for e in d.get(cle, [])]
    ids = [e["id"] for _, e in elements]
    for i in _doublons(ids):
        messages.append(f"{fichier} : l'id « {i} » est utilisé {ids.count(i)} fois ; chaque mur, "
                        "objet et piéton doit avoir un id différent (il devient un nom de modèle Gazebo)")
    for mot, e in elements:
        if e["id"] in IDS_RESERVES:
            messages.append(f"{fichier}, {mot} « {e['id']} » : l'id « {e['id']} » est réservé "
                            "(déjà pris dans le monde Gazebo) ; choisissez-en un autre")

    (xmin, ymin), (xmax, ymax) = d["emprise"]["min"], d["emprise"]["max"]
    emprise_ok = True
    for axe, bas, haut in (("x", xmin, xmax), ("y", ymin, ymax)):
        if haut <= bas:
            emprise_ok = False
            messages.append(f"{fichier}, emprise : en {axe}, max ({nombre(haut)}) doit être plus grand "
                            f"que min ({nombre(bas)})")

    def hors(p):
        return not (xmin - 1e-9 <= p[0] <= xmax + 1e-9 and ymin - 1e-9 <= p[1] <= ymax + 1e-9)
    limites = f"x de {nombre(xmin)} à {nombre(xmax)}, y de {nombre(ymin)} à {nombre(ymax)}"

    for m in d.get("murs", []):
        if math.isclose(m["de"][0], m["a"][0], abs_tol=1e-9) and math.isclose(m["de"][1], m["a"][1], abs_tol=1e-9):
            messages.append(f"{fichier}, mur « {m['id']} » : ses deux bouts sont au même endroit "
                            f"{_point_texte(m['de'])} ; un mur doit avoir une longueur")
        for bout in ("de", "a"):
            if emprise_ok and hors(m[bout]):
                messages.append(f"{fichier}, mur « {m['id']} » : le bout {bout} {_point_texte(m[bout])} sort "
                                f"de l'emprise ({limites}) ; déplacez-le ou agrandissez l'emprise")
    for o in d.get("objets", []):
        if emprise_ok and hors(o["centre"]):
            messages.append(f"{fichier}, objet « {o['id']} » : le centre {_point_texte(o['centre'])} sort "
                            f"de l'emprise ({limites}) ; déplacez-le ou agrandissez l'emprise")
    for p in d.get("pietons", []):
        trajet = p["trajet"]
        for i, point in enumerate(trajet):
            if emprise_ok and hors(point):
                messages.append(f"{fichier}, piéton « {p['id']} » : le point n°{i + 1} {_point_texte(point)} "
                                f"du trajet sort de l'emprise ({limites})")
        for i in range(len(trajet) - 1):
            if list(trajet[i]) == list(trajet[i + 1]):
                messages.append(f"{fichier}, piéton « {p['id']} » : les points n°{i + 1} et n°{i + 2} du "
                                "trajet sont identiques ; retirez l'un des deux")
        if not p["aller_retour"] and len(trajet) > 2 and list(trajet[0]) == list(trajet[-1]):
            messages.append(f"{fichier}, piéton « {p['id']} » : le dernier point répète le premier ; "
                            "retirez-le (avec aller_retour: false, le piéton revient seul au départ)")
        # vague 4 (section 11.3) : pauses sur des points du trajet, une au plus par point
        points_pauses = [q["point"] for q in p.get("pauses", [])]
        for rang in points_pauses:
            if rang >= len(trajet):
                messages.append(f"{fichier}, piéton « {p['id']} » : une pause est au point n°{rang}, mais le trajet "
                                f"n'a que {len(trajet)} points (numérotés de 0 à {len(trajet) - 1})")
        for rang in _doublons(points_pauses):
            messages.append(f"{fichier}, piéton « {p['id']} » : deux pauses au point n°{rang} ; gardez-en une seule")
    depart = d["depart_robot"]
    if emprise_ok and hors((depart["x"], depart["y"])):
        messages.append(f"{fichier}, depart_robot : {_point_texte((depart['x'], depart['y']))} sort de "
                        f"l'emprise ({limites})")
    return messages


def regles_carte(d, fichier="carte.yaml"):
    if d["origin"][2] != 0:
        return [f"{fichier}, origin : le lacet (3e valeur) doit valoir 0.0 ; "
                "l'Atelier ne gère pas les cartes tournées"]
    return []


ETATS_ETAPES = {"en_cours": ("preparation", "enregistrement"), "arret_en_cours": ("arret",),
                "traitement": ("carte_3d", "carte_2d", "reconnaissance", "monde"), "termine": ("fini",),
                "echec": ("preparation", "enregistrement", "arret", "carte_3d", "carte_2d", "reconnaissance",
                          "monde")}


def _instant(texte):
    from datetime import datetime
    try:
        return datetime.fromisoformat(texte)
    except (TypeError, ValueError):
        return None


def regles_session_scan(d, fichier="session.json"):
    messages = []
    etat, etape = d["etat"], d["etape"]
    if etape not in ETATS_ETAPES[etat]:
        messages.append(f"{fichier} : l'étape « {etape} » ne va pas avec l'état « {etat} » ; étapes possibles : "
                        f"{', '.join(ETATS_ETAPES[etat])}")
    if etat == "termine" and d["progression"] != 100:
        messages.append(f"{fichier} : une session terminée a une progression de 100, pas {d['progression']}")
    if etat == "en_cours" and d["fin"] is not None:
        messages.append(f"{fichier} : une session en cours n'a pas encore de fin (fin: null)")
    if etat in ("traitement", "termine") and d["fin"] is None:
        messages.append(f"{fichier} : l'état « {etat} » suppose un enregistrement fini ; il manque l'heure de fin")
    debut, fin = _instant(d["debut"]), _instant(d["fin"]) if d["fin"] else None
    if debut is not None and fin is not None and fin < debut:
        messages.append(f"{fichier} : la fin ({d['fin']}) est avant le début ({d['debut']})")
    if d["mode"] == "simu" and d["repetition"]:
        messages.append(f"{fichier} : repetition ne s'emploie qu'en mode robot (en simu, mettez repetition: false)")
    if d["explorer"] and not (d["mode"] == "simu" or d["repetition"]):
        messages.append(f"{fichier} : explorer ne s'emploie qu'avec le robot simulé (mode simu, ou robot en "
                        "répétition) : le vrai robot se conduit à la télécommande")
    if d.get("carte_unitree") and d["mode"] != "robot":
        messages.append(f"{fichier} : carte_unitree n'a de sens qu'en mode robot (mettez null)")
    if d.get("adoption") and etat != "termine":
        messages.append(f"{fichier} : seule une session terminée peut avoir été adoptée")
    return messages


def regles_reconnaissance(d, fichier="reconnaissance.yaml"):
    messages = []
    elements = [(MOTS_ELEMENTS[cle], e) for cle in ("murs", "passages", "objets") for e in d[cle]]
    ids = [e["id"] for _, e in elements]
    for i in _doublons(ids):
        messages.append(f"{fichier} : l'id « {i} » est utilisé {ids.count(i)} fois ; chaque mur, passage et "
                        "objet doit avoir un id différent (il devient un nom de modèle Gazebo)")
    for mot, e in elements:
        if e["id"] in IDS_RESERVES:
            messages.append(f"{fichier}, {mot} « {e['id']} » : l'id « {e['id']} » est réservé "
                            "(déjà pris dans le monde Gazebo) ; choisissez-en un autre")
    murs = {m["id"]: m for m in d["murs"]}
    for m in d["murs"]:
        if (math.isclose(m["de"][0], m["a"][0], abs_tol=1e-9)
                and math.isclose(m["de"][1], m["a"][1], abs_tol=1e-9)):
            messages.append(f"{fichier}, mur « {m['id']} » : ses deux bouts sont au même endroit "
                            f"{_point_texte(m['de'])} ; un mur doit avoir une longueur")
    for p in d["passages"]:
        ou = f"{fichier}, passage « {p['id']} »"
        inconnus = [i for i in p["murs"] if i not in murs]
        if inconnus:
            messages.append(f"{ou} : le mur « {inconnus[0]} » n'existe pas dans murs")
            continue
        largeur = math.dist(p["de"], p["a"])
        if not geometrie.PASSAGE_MIN - 1e-6 <= largeur <= geometrie.PASSAGE_MAX + 1e-6:
            messages.append(f"{ou} : largeur de {nombre(round(largeur, 3))} m ; un passage est un trou de "
                            f"{nombre(geometrie.PASSAGE_MIN)} à {nombre(geometrie.PASSAGE_MAX)} m")
        m1, m2 = (murs[i] for i in p["murs"])
        if not geometrie.murs_alignes(m1["de"], m1["a"], m2["de"], m2["a"]):
            messages.append(f"{ou} : les murs « {m1['id']} » et « {m2['id']} » ne sont pas alignés ; un passage "
                            "est un trou entre deux murs alignés")
            continue
        trou = geometrie.trou_entre(m1["de"], m1["a"], m2["de"], m2["a"])
        bouts = {tuple(p["de"]), tuple(p["a"])}
        if trou is None or not all(min(math.dist(b, q) for b in bouts) <= 0.15 for q in trou[1:]):
            messages.append(f"{ou} : de et a doivent être les bouts des murs « {m1['id']} » et « {m2['id']} » "
                            "qui bordent le trou (à 0,15 m près)")
    (xmin, ymin), (xmax, ymax) = d["emprise"]["min"], d["emprise"]["max"]
    if xmax <= xmin or ymax <= ymin:
        messages.append(f"{fichier}, emprise : max doit être plus grand que min, en x comme en y")
        return messages
    limites = f"x de {nombre(xmin)} à {nombre(xmax)}, y de {nombre(ymin)} à {nombre(ymax)}"

    def hors(q):
        return not (xmin - 1e-9 <= q[0] <= xmax + 1e-9 and ymin - 1e-9 <= q[1] <= ymax + 1e-9)
    points = [(f"mur « {m['id']} », bout {b}", m[b]) for m in d["murs"] for b in ("de", "a")]
    points += [(f"passage « {p['id']} », bout {b}", p[b]) for p in d["passages"] for b in ("de", "a")]
    points += [(f"objet « {o['id']} », centre", o["centre"]) for o in d["objets"]]
    points += [("depart_robot", (d["depart_robot"]["x"], d["depart_robot"]["y"]))]
    for ou, q in points:
        if hors(q):
            messages.append(f"{fichier}, {ou} {_point_texte(q)} : sort de l'emprise ({limites}) ; "
                            "agrandissez l'emprise")
    return messages


def regles_etat_pont(d, fichier="/pont/etat"):
    messages = []
    if d["etat"] == "en_mouvement" and not d["mouvement_permis"]:
        messages.append(f"{fichier} : etat en_mouvement alors que mouvement_permis est faux")
    if d["etat"] in ("attente_reperage", "arret", "arret_verrouille", "pilotage") and d["mouvement_permis"]:
        messages.append(f"{fichier} : etat {d['etat']} alors que mouvement_permis est vrai")
    if d["verrou"] != (d["etat"] == "arret_verrouille"):
        messages.append(f"{fichier} : verrou doit être vrai si et seulement si etat vaut arret_verrouille")
    for axe in ("vx", "vy", "wz"):
        if abs(d["consigne"][axe]) > d["limites"][axe] + 1e-6:
            messages.append(f"{fichier} : consigne {axe} = {d['consigne'][axe]} dépasse la limite "
                            f"{d['limites'][axe]}")
    if d["reponses"] > d["envoyees"]:
        messages.append(f"{fichier} : plus de réponses ({d['reponses']}) que de requêtes ({d['envoyees']})")
    return messages


def regles_etat_reperage(d, fichier="/reperage/etat"):
    messages = []
    if d["repere"] != (d["etat"] == "repere"):
        messages.append(f"{fichier} : repere doit être vrai si et seulement si etat vaut repere "
                        f"(etat {d['etat']}, repere {d['repere']})")
    if d["etat"] == "repere" and d["pose"] is None:
        messages.append(f"{fichier} : etat repere sans pose")
    return messages


def regles_demande_reperage(d, fichier="/reperage/demander"):
    donnes = [c for c in ("x", "y", "theta") if c in d]
    if donnes and len(donnes) != 3:
        manque = [c for c in ("x", "y", "theta") if c not in d]
        return [f"{fichier} : x, y et theta vont ensemble ; il manque {', '.join(manque)} "
                "(sans aucun des trois : le robot est sur la marque au sol)"]
    return []


# ---------------------------------------------------------------- vague 4 (section 11 du plan)

def _ids_uniques(elements, fichier, mot):
    ids = [e["id"] for e in elements]
    return [f"{fichier} : {mot} « {i} » apparaît {ids.count(i)} fois ; chaque id doit être différent"
            for i in _doublons(ids)]


def regles_lieu_v4(d, fichier="lieu.yaml"):
    messages = regles_lieu(d, fichier)
    guide = d.get("guide") or {}
    ralentir = guide.get("distance_ralentir_m", 2.0)
    attendre = guide.get("distance_attendre_m", 3.5)
    if attendre <= ralentir:
        messages.append(f"{fichier}, guide : distance_attendre_m ({nombre(attendre)}) doit être plus grande que "
                        f"distance_ralentir_m ({nombre(ralentir)}) : le robot ralentit d'abord, puis s'arrête")
    return messages


def regles_personnalites(d, fichier="personnalites.yaml"):
    messages = _ids_uniques(d["personnalites"], fichier, "la personnalité")
    ids = [p["id"] for p in d["personnalites"]]
    if d["active"] not in ids:
        messages.append(f"{fichier} : la personnalité active « {d['active']} » n'existe pas ; personnalités : "
                        f"{', '.join(ids)}")
    return messages


def regles_dialogues(d, fichier="dialogues.yaml"):
    messages = _ids_uniques(d["regles"], fichier, "la règle")
    for r in d["regles"]:
        ou = f"{fichier}, règle « {r['id']} »"
        if r["action"] == "guider":
            sans = [m for m in r["motifs"] if "{salle}" not in m]
            if sans:
                messages.append(f"{ou} : l'action guider a besoin de {{salle}} dans chaque motif (pas dans "
                                f"« {sans[0]} »)")
        if r["action"] == "personnalite" and "personnalite" not in r:
            messages.append(f"{ou} : l'action personnalite a besoin du champ personnalite (l'id à activer)")
        if r["action"] != "personnalite" and "personnalite" in r:
            messages.append(f"{ou} : le champ personnalite ne sert qu'avec l'action personnalite")
    return messages


def regles_scene(d, fichier="scène"):
    messages = []
    if not d["trajets"] and not d.get("hasard"):
        messages.append(f"{fichier} « {d['id']} » : il faut des trajets, ou hasard (un nombre de trajets tirés au sort)")
    # les piétons de la scène ont le format de monde.yaml, et ses règles
    monde = {"version": 1, "emprise": {"min": [-1e6, -1e6], "max": [1e6, 1e6]}, "pietons": d["pietons"],
             "depart_robot": {"x": 0.0, "y": 0.0, "theta": 0.0}}
    messages += [m.replace("monde.yaml", f"{fichier} « {d['id']} »", 1)
                 for m in valider_donnees("monde", monde, "monde.yaml")]
    ids = {p.get("id") for p in d["pietons"] if isinstance(p, dict)}
    if d.get("visiteur") and d["visiteur"] not in ids:
        messages.append(f"{fichier} « {d['id']} » : le visiteur « {d['visiteur']} » n'est pas un des piétons de la scène")
    for p in d["pietons"]:
        if isinstance(p, dict) and d.get("visiteur") == p.get("id") and p.get("pilote") != "externe":
            messages.append(f"{fichier} « {d['id']} », piéton « {p['id']} » : le visiteur doit avoir pilote: externe")
    return messages


def regles_choregraphie(d, fichier="chorégraphie"):
    from .pilotage import regles_choregraphie as regles     # import ici : pilotage importe ce module
    return regles(d, fichier)


def regles_pietons_etat(d, fichier="/pietons/etat"):
    return _ids_uniques(d["pietons"], fichier, "le piéton")


def _sans_regle(d, fichier=""):
    return []


REGLES = {"lieu": regles_lieu_v4, "monde": regles_monde, "salles": regles_salles,
          "itineraires": regles_itineraires, "zones": regles_zones, "carte": regles_carte,
          "session_scan": regles_session_scan, "reconnaissance": regles_reconnaissance,
          "etat_pont": regles_etat_pont, "etat_reperage": regles_etat_reperage,
          "demande_reperage": regles_demande_reperage,
          "personnalites": regles_personnalites, "dialogues": regles_dialogues, "camera": _sans_regle,
          "scene": regles_scene, "choregraphie": regles_choregraphie,
          "etat_guide": _sans_regle, "evenement_guide": _sans_regle, "demande_guide": _sans_regle,
          "pietons_etat": regles_pietons_etat, "pietons_consigne": _sans_regle, "personnes": _sans_regle,
          "maitre_mouvement": _sans_regle, "etat_pilotage": _sans_regle, "robot_dire": _sans_regle,
          "personnalite_active": _sans_regle}


def valider_donnees(type_fichier, donnees, fichier=None):
    """Erreurs d'un fichier (déjà lu), en français : schéma, puis règles propres au fichier.

    type_fichier : lieu, monde, salles, itineraires, zones, carte, session_scan, reconnaissance,
    ou un message du vrai robot : etat_pont, etat_reperage, demande_reperage (section 10 du plan) ;
    vague 4 (section 11) : personnalites, dialogues, camera, scene, choregraphie, et les messages de
    TYPES_MESSAGES.
    fichier : nom affiché au début de chaque message (par défaut : salles.yaml, monde.yaml...).
    Renvoie une liste vide si tout va bien.
    """
    fichier = fichier or NOMS_FICHIERS[type_fichier]
    brutes = erreurs_schema(type_fichier, donnees)
    if brutes:
        messages = [traduire(e, type_fichier, donnees, fichier) for e in brutes]
        return list(dict.fromkeys(messages))      # sans doublon, dans l'ordre
    return REGLES[type_fichier](donnees, fichier)
