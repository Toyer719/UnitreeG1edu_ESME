"""Routes des points placés sur la carte : salles, itinéraires et zones.

  GET/PUT /api/lieux/{id}/salles          salles.yaml (liste)
  GET/PUT /api/lieux/{id}/itineraires     itineraires.yaml ({noeuds, couloirs})
  GET/PUT /api/lieux/{id}/zones           zones.yaml ({interdites, lentes})

PUT …/salles?synchroniser=true (ajout au contrat, utilisé par l'interface) : en plus, chaque
salle reçoit dans itineraires.yaml un nœud de même id à la même position, et la salle
« accueil » recopie sa pose dans l'accueil de lieu.yaml (règles de la section 4.1).
Chaque PUT renvoie la liste des fichiers écrits et le rapport de vérification du lieu.
"""
import math
from typing import Any

from fastapi import APIRouter, Body

from atelier.lieu import (ErreurLieu, Itineraires, Noeud, PoseEtage, Salle, Zones, charger_itineraires,
                          charger_salles, charger_zones, enregistrer_fiche, enregistrer_itineraires,
                          enregistrer_salles, enregistrer_zones, valider_donnees)

from ..communs import ErreurAtelier, dossier_du_lieu, erreur_validation, fiche_du_lieu, rapport_du_lieu

routeur = APIRouter(prefix="/api/lieux/{id_lieu}", tags=["salles, itinéraires, zones"])

TOLERANCE = 1e-3     # m ou rad : en deçà, une position est considérée comme inchangée


def _lire(fichier, lecture, dossier):
    try:
        return lecture(dossier)
    except ErreurLieu as e:
        raise ErreurAtelier(422, f"Le fichier {fichier} est invalide : corrigez les points ci-dessous.",
                            e.erreurs) from None


def _valider(type_fichier, fichier, donnees):
    erreurs = valider_donnees(type_fichier, donnees, fichier)
    if erreurs:
        raise erreur_validation(fichier, erreurs)


# ---------------------------------------------------------------- salles

@routeur.get("/salles")
def lire_salles(id_lieu: str):
    dossier = dossier_du_lieu(id_lieu)
    return [s.vers_dict() for s in _lire("salles.yaml", charger_salles, dossier)]


def _proche(a, b):
    return abs(a - b) <= TOLERANCE


def synchroniser_salles(dossier, salles):
    """Nœud de même id pour chaque salle, et accueil de lieu.yaml = pose de la salle « accueil ».
    Renvoie la liste des fichiers modifiés en plus de salles.yaml."""
    modifies = []
    itineraires = _lire("itineraires.yaml", charger_itineraires, dossier)
    change = False
    for s in salles:
        n = itineraires.noeuds.get(s.id)
        if n is None or n.etage != s.etage or not (_proche(n.x, s.pose.x) and _proche(n.y, s.pose.y)):
            itineraires.noeuds[s.id] = Noeud(s.etage, s.pose.x, s.pose.y)
            change = True
    if change:
        try:
            enregistrer_itineraires(dossier, itineraires)
        except ErreurLieu as e:
            raise erreur_validation("itineraires.yaml", e.erreurs) from None
        modifies.append("itineraires.yaml")
    accueil = next((s for s in salles if s.id == "accueil"), None)
    if accueil is not None:
        fiche = fiche_du_lieu(dossier)
        a = fiche.accueil
        if (a.etage != accueil.etage or not _proche(a.x, accueil.pose.x) or not _proche(a.y, accueil.pose.y)
                or not _proche(math.remainder(a.theta - accueil.pose.theta, 2 * math.pi), 0.0)):
            fiche.accueil = PoseEtage(accueil.etage, accueil.pose.x, accueil.pose.y, accueil.pose.theta)
            try:
                enregistrer_fiche(fiche, dossier)
            except ErreurLieu as e:
                raise erreur_validation("lieu.yaml", e.erreurs) from None
            modifies.append("lieu.yaml")
    return modifies


@routeur.put("/salles")
def ecrire_salles(id_lieu: str, donnees: Any = Body(...), synchroniser: bool = False):
    dossier = dossier_du_lieu(id_lieu)
    _valider("salles", "salles.yaml", donnees)
    salles = [Salle.depuis_dict(s) for s in donnees]
    try:
        enregistrer_salles(dossier, salles)
    except ErreurLieu as e:
        raise erreur_validation("salles.yaml", e.erreurs) from None
    ecrits = ["salles.yaml"]
    if synchroniser:
        ecrits += synchroniser_salles(dossier, salles)
    return {"enregistre": ecrits, "rapport": rapport_du_lieu(dossier)}


# ---------------------------------------------------------------- itinéraires

@routeur.get("/itineraires")
def lire_itineraires(id_lieu: str):
    dossier = dossier_du_lieu(id_lieu)
    return _lire("itineraires.yaml", charger_itineraires, dossier).vers_dict()


@routeur.put("/itineraires")
def ecrire_itineraires(id_lieu: str, donnees: Any = Body(...)):
    dossier = dossier_du_lieu(id_lieu)
    _valider("itineraires", "itineraires.yaml", donnees)
    try:
        enregistrer_itineraires(dossier, Itineraires.depuis_dict(donnees))
    except ErreurLieu as e:
        raise erreur_validation("itineraires.yaml", e.erreurs) from None
    return {"enregistre": ["itineraires.yaml"], "rapport": rapport_du_lieu(dossier)}


# ---------------------------------------------------------------- zones

@routeur.get("/zones")
def lire_zones(id_lieu: str):
    dossier = dossier_du_lieu(id_lieu)
    return _lire("zones.yaml", charger_zones, dossier).vers_dict()


@routeur.put("/zones")
def ecrire_zones(id_lieu: str, donnees: Any = Body(...)):
    dossier = dossier_du_lieu(id_lieu)
    _valider("zones", "zones.yaml", donnees)
    try:
        enregistrer_zones(dossier, Zones.depuis_dict(donnees))
    except ErreurLieu as e:
        raise erreur_validation("zones.yaml", e.erreurs) from None
    return {"enregistre": ["zones.yaml"], "rapport": rapport_du_lieu(dossier)}
