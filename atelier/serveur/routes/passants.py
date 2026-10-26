"""Routes des passants (vague 4, section 11.3 du plan) : agent Passants.

  GET /api/passants/scenes              les scènes d'essai (atelier/monde/scenes), résumées :
                                        {scenes: [{id, nom, description, lieu, etage, pietons,
                                        reactions, trajets, essais, hasard, mesures, commande}],
                                        erreurs: [{fichier, detail}]}
  GET /api/passants/scenes/{id}         une scène entière (le fichier), et son résumé ; 404 sinon
  GET /api/passants/bancs               les derniers bancs (CSV de g1-banc dans ~/robot-g1/journaux),
                                        résumés : trajets, réussis, contacts (et leur cause),
                                        distance bord à bord minimale ; le plus récent d'abord
  GET /api/passants/bancs/{nom}         les lignes d'un CSV de banc ; 404 sinon
  GET /api/passants/etat                le dernier /pietons/etat reçu (piétons crédibles de la
                                        simulation) et son âge, ou null

Les positions des piétons dans /ws/etat viennent déjà de /pietons/etat quand il est publié
(atelier/serveur/etat.py). Les scènes se lancent en ligne de commande : g1-banc --scene ID.
"""
import csv
import re
from datetime import datetime

from fastapi import APIRouter, Request

import atelier
from atelier.lieu import ErreurLieu
from atelier.monde.scene import SUFFIXE_SCENE, charger_scene, lister_scenes, resume_scene

from ..communs import ErreurAtelier

routeur = APIRouter(tags=["passants"])

MOTIF_BANC = re.compile(r"^banc_[A-Za-z0-9_.-]{1,120}\.csv$")
BANCS_MAX = 20


def _nombre(texte):
    try:
        return float(texte)
    except (TypeError, ValueError):
        return None


@routeur.get("/api/passants/scenes")
def scenes():
    """Les scènes d'essai des passants, résumées ; les fichiers faux sont listés à part."""
    resultat, erreurs = [], []
    for chemin in lister_scenes():
        try:
            resultat.append(resume_scene(charger_scene(chemin)))
        except ErreurLieu as e:
            erreurs.append({"fichier": chemin.name, "detail": str(e)})
    return {"scenes": resultat, "erreurs": erreurs}


@routeur.get("/api/passants/scenes/{ident}")
def scene(ident: str):
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,39}", ident):
        raise ErreurAtelier(404, f"Scène inconnue : « {ident} »")
    try:
        donnees = charger_scene(ident)
    except ErreurLieu as e:
        raise ErreurAtelier(404, str(e)) from None
    return {"scene": donnees, "resume": resume_scene(donnees), "fichier": f"{ident}{SUFFIXE_SCENE}"}


def _fichiers_bancs():
    dossier = atelier.dossier_journaux()
    fichiers = [f for f in dossier.glob("banc_*.csv") if MOTIF_BANC.match(f.name)]
    return sorted(fichiers, key=lambda f: f.stat().st_mtime, reverse=True)


def resume_banc(chemin):
    """Résumé d'un CSV de g1-banc (colonnes de la vague 1, et de la vague 4 s'il les a)."""
    with open(chemin, newline="", encoding="utf-8") as f:
        lignes = list(csv.DictReader(f))
    bords = [b for b in (_nombre(ligne.get("distance_min_bord_m")) for ligne in lignes) if b is not None]

    def somme(cle):
        return int(sum(_nombre(ligne.get(cle)) or 0 for ligne in lignes))

    scenes_vues = sorted({ligne.get("scene") for ligne in lignes if ligne.get("scene")})
    return {"nom": chemin.name, "date": datetime.fromtimestamp(chemin.stat().st_mtime).isoformat(timespec="seconds"),
            "scene": scenes_vues[0] if len(scenes_vues) == 1 else (", ".join(scenes_vues) or None),
            "trajets": len(lignes), "reussis": sum(1 for ligne in lignes if ligne.get("reussite") == "oui"),
            "detours": somme("detours"), "contacts": somme("contacts"), "contacts_robot": somme("contacts_robot"),
            "contacts_pieton": somme("contacts_pieton"), "contacts_aucun": somme("contacts_aucun"),
            "distance_min_bord_m": min(bords) if bords else None, "vague4": "contacts" in (lignes[0] if lignes else {})}


@routeur.get("/api/passants/bancs")
def bancs():
    resultat = []
    for chemin in _fichiers_bancs()[:BANCS_MAX]:
        try:
            resultat.append(resume_banc(chemin))
        except (OSError, csv.Error, UnicodeDecodeError):
            continue
    return {"bancs": resultat, "dossier": str(atelier.dossier_journaux())}


@routeur.get("/api/passants/bancs/{nom}")
def banc(nom: str):
    if not MOTIF_BANC.match(nom):
        raise ErreurAtelier(404, f"Banc inconnu : « {nom} »")
    chemin = atelier.dossier_journaux() / nom
    if not chemin.is_file():
        raise ErreurAtelier(404, f"Banc inconnu : « {nom} »")
    with open(chemin, newline="", encoding="utf-8") as f:
        lignes = list(csv.DictReader(f))
    return {"nom": nom, "resume": resume_banc(chemin), "lignes": lignes}


@routeur.get("/api/passants/etat")
def etat_pietons(request: Request):
    """Dernier /pietons/etat reçu par le pont ROS 2 du serveur (null sans simulation)."""
    etat = getattr(request.app.state, "atelier", None)
    try:
        recu = etat.pont.dernier("/pietons/etat") if etat is not None else None
    except Exception:  # noqa: BLE001 : pont absent ou arrêté
        recu = None
    return {"etat": recu}
