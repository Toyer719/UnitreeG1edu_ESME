"""Scènes d'essai des passants (vague 4, section 11.3 du plan) : agent Passants.

Une scène (schéma scene, fichiers atelier/monde/scenes/<id>.scene.yaml) s'applique à une COPIE d'un
lieu de référence : ses piétons remplacent (ou complètent, ajouter: true) ceux du monde de l'étage,
ses réglages du guide vont dans la section guide de lieu.yaml, puis le monde est regénéré (.sdf,
carte, masque). g1-banc --scene ID fait ses trajets et vérifie ses seuils (mesures).

    scene = charger_scene("en_face")                 # id ou chemin ; ErreurLieu si elle est fausse
    copie = copier_pour_scene(scene, "/tmp/essai")   # copie du lieu de référence, scène appliquée
    appliquer_scene(copie, scene, reaction="ecart")  # (déjà fait par copier_pour_scene)
    trajets_de_scene(scene, salles)                  # [(départ, arrivée)], essais compris

La référence (lieux/demo, ou le lieu de la scène lui-même) n'est jamais modifiée : appliquer_scene
refuse d'écrire dans le dossier du lieu de référence.
"""
import random
from pathlib import Path

import atelier
from atelier.lieu import (ErreurLieu, Pieton, charger_fiche, charger_fichier, charger_monde, copier_lieu,
                          dossier_lieu, enregistrer_fiche, enregistrer_monde)
from atelier.lieu.passants import REACTIONS

DOSSIER_SCENES = Path(__file__).resolve().parent / "scenes"
SUFFIXE_SCENE = ".scene.yaml"
REFERENCE_DEPOT = Path(__file__).resolve().parents[2] / "lieux" / "demo"   # lieux/demo du dépôt


def lister_scenes(dossier=None):
    """Chemins des scènes du dossier (défaut : atelier/monde/scenes)."""
    racine = Path(dossier or DOSSIER_SCENES)
    return sorted(racine.glob(f"*{SUFFIXE_SCENE}")) if racine.is_dir() else []


def chemin_scene(ident):
    """Fichier d'une scène : chemin donné, ou atelier/monde/scenes/<id>.scene.yaml."""
    texte = str(ident).strip()
    if texte.endswith(SUFFIXE_SCENE) or "/" in texte:
        return Path(texte).expanduser().resolve()
    return DOSSIER_SCENES / f"{texte}{SUFFIXE_SCENE}"


def charger_scene(ident):
    """Lit et vérifie une scène (id ou chemin) ; ErreurLieu si elle est fausse."""
    chemin = chemin_scene(ident)
    if not chemin.is_file():
        connues = ", ".join(p.name[:-len(SUFFIXE_SCENE)] for p in lister_scenes())
        raise ErreurLieu(f"scène « {ident} » introuvable ({chemin}) ; scènes connues : {connues or 'aucune'}")
    scene = charger_fichier(chemin, "scene", fichier=chemin.name)
    attendu = chemin.name[:-len(SUFFIXE_SCENE)] if chemin.name.endswith(SUFFIXE_SCENE) else None
    if attendu is not None and scene["id"] != attendu:
        raise ErreurLieu(f"{chemin.name} : l'id de la scène est « {scene['id']} », il doit être le nom du "
                         f"fichier sans {SUFFIXE_SCENE} (« {attendu} »)")
    return scene


def _meme_dossier(a, b):
    try:
        return Path(a).resolve() == Path(b).resolve()
    except OSError:
        return False


def est_reference(lieu, scene):
    """Vrai si lieu est le lieu de référence de la scène (ou lieux/demo du dépôt) : on n'y écrit pas."""
    dossier = dossier_lieu(lieu)
    return _meme_dossier(dossier, atelier.chemin_lieu(scene["lieu"])) or _meme_dossier(dossier, REFERENCE_DEPOT)


def pietons_de_scene(scene, reaction=None):
    """Piétons de la scène (Pieton) ; reaction : si donnée, elle remplace celle de chacun."""
    if reaction is not None and reaction not in REACTIONS:
        raise ErreurLieu(f"réaction « {reaction} » inconnue : {', '.join(REACTIONS)}")
    pietons = []
    for d in scene["pietons"]:
        d = dict(d)
        if reaction is not None and d.get("pilote", "trajet") != "externe":
            d["reaction"] = reaction
        pietons.append(Pieton.depuis_dict(d))
    return pietons


def appliquer_scene(lieu, scene, reaction=None):
    """Applique la scène à une copie de lieu (jamais à lieux/demo) : piétons, réglages du guide,
    puis atelier.monde.generer. Renvoie le Monde écrit. reaction : remplace celle de chaque piéton
    (ex. « ecart » pour rejouer une scène « pire cas » avec des piétons qui s'écartent)."""
    from . import generer
    if isinstance(scene, (str, Path)):
        scene = charger_scene(scene)
    dossier = dossier_lieu(lieu)
    if est_reference(dossier, scene):
        raise ErreurLieu(f"{dossier} est le lieu de référence de la scène « {scene['id']} » : une scène ne "
                         "s'applique qu'à une copie (copier_pour_scene, ou g1-banc --scene)")
    nouveaux = pietons_de_scene(scene, reaction)
    etage = scene["etage"]
    monde = charger_monde(dossier, etage)
    gardes = [p for p in monde.pietons if p.id not in {n.id for n in nouveaux}] if scene.get("ajouter") else []
    monde.pietons = gardes + nouveaux
    pris = {m.id for m in monde.murs} | {o.id for o in monde.objets}
    doublons = sorted(p.id for p in monde.pietons if p.id in pris)
    if doublons:
        raise ErreurLieu(f"scène « {scene['id']} » : l'id {', '.join(doublons)} est déjà celui d'un mur ou d'un objet "
                         "du monde ; renommez le piéton")
    enregistrer_monde(dossier, etage, monde)
    reglages = scene.get("reglages_guide")
    if reglages:
        fiche = charger_fiche(dossier)
        fiche.guide = dict(fiche.guide or {}, **reglages)
        enregistrer_fiche(fiche, dossier)
    generer(dossier, etage)
    return monde


def copier_pour_scene(scene, destination, reaction=None, reference=None):
    """Copie le lieu de référence de la scène (reference : un autre lieu, si donné) dans destination
    (qui ne doit pas exister), puis y applique la scène. Renvoie le dossier de la copie."""
    if isinstance(scene, (str, Path)):
        scene = charger_scene(scene)
    source = dossier_lieu(reference or scene["lieu"])
    copie = copier_lieu(source, destination)
    for pcd in (copie / "cartes").glob("*.pcd"):        # nuages du scan : inutiles à la simulation
        pcd.unlink()
    appliquer_scene(copie, scene, reaction)
    return copie


def trajets_de_scene(scene, salles=None):
    """Trajets [(départ, arrivée)] de la scène, chacun répété essais fois (l'un après l'autre), puis
    hasard trajets tirés au sort entre les salles (graine : graine, 1 par défaut ; chaque trajet
    part de l'arrivée du précédent). salles : ids des salles de l'étage (pour hasard)."""
    essais = int(scene.get("essais", 1))
    trajets = [tuple(t) for t in scene["trajets"] for _ in range(essais)]
    n = int(scene.get("hasard") or 0)
    if n:
        salles = sorted(salles or [])
        if len(salles) < 2:
            raise ErreurLieu(f"scène « {scene['id']} » : hasard demande au moins deux salles sur l'étage")
        hasard = random.Random(int(scene.get("graine", 1)))
        depart = trajets[-1][1] if trajets else salles[0]
        for _ in range(n):
            arrivee = hasard.choice([s for s in salles if s != depart])
            trajets.append((depart, arrivee))
            depart = arrivee
    return trajets


def resume_scene(scene):
    """Description courte d'une scène, pour l'interface : {id, nom, description, lieu, etage,
    pietons, trajets, essais, hasard, mesures}."""
    return {"id": scene["id"], "nom": scene["nom"], "description": scene.get("description", ""),
            "lieu": scene["lieu"], "etage": scene["etage"], "pietons": len(scene["pietons"]),
            "reactions": sorted({p.get("reaction", "ecart") for p in scene["pietons"]}),
            "trajets": [list(t) for t in scene["trajets"]], "essais": int(scene.get("essais", 1)),
            "hasard": scene.get("hasard"), "mesures": dict(scene.get("mesures") or {}),
            "commande": f"g1-banc --scene {scene['id']}"}
