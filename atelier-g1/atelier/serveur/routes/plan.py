"""Routes des points placés sur la carte : salles, itinéraires et zones.

  GET/PUT /api/lieux/{id}/salles          salles.yaml (liste)
  GET/PUT /api/lieux/{id}/itineraires     itineraires.yaml ({noeuds, couloirs})
  GET/PUT /api/lieux/{id}/zones           zones.yaml ({interdites, lentes})

PUT …/salles?synchroniser=true (ajout au contrat, utilisé par l'interface) : en plus, chaque
salle reçoit dans itineraires.yaml un nœud de même id à la même position, et le point principal
(vague 4, section 11.2 : la salle étiquetée « principal », à défaut la salle « accueil ») recopie sa
pose dans l'accueil de lieu.yaml et dans depart_robot du monde de son étage, tout ou rien
(atelier.lieu.principal.ecrire_salles). PUT …/salles refuse (422) une liste à deux principaux, et
une liste qui perd le point principal du lieu (« choisissez d'abord un autre point principal »).
Chaque PUT renvoie la liste des fichiers écrits et le rapport de vérification du lieu.
"""
from typing import Any

from fastapi import APIRouter, Body

from atelier.lieu import (ErreurLieu, Itineraires, Salle, Zones, charger_itineraires, charger_salles, charger_zones,
                          enregistrer_itineraires, enregistrer_zones, principal, valider_donnees)

from ..communs import ErreurAtelier, dossier_du_lieu, erreur_validation, rapport_du_lieu

routeur = APIRouter(prefix="/api/lieux/{id_lieu}", tags=["salles, itinéraires, zones"])


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


@routeur.put("/salles")
def ecrire_salles(id_lieu: str, donnees: Any = Body(...), synchroniser: bool = False):
    dossier = dossier_du_lieu(id_lieu)
    _valider("salles", "salles.yaml", donnees)
    try:
        ecrits = principal.ecrire_salles(dossier, [Salle.depuis_dict(s) for s in donnees], synchroniser)
    except principal.PerteDuPrincipal as e:
        raison = e.erreurs[0].split(" : ", 1)[-1]          # sans le « salles.yaml : » du début
        raise ErreurAtelier(422, f"salles.yaml n'a pas été enregistré : {raison}.", e.erreurs) from None
    except ErreurLieu as e:
        raise ErreurAtelier(422, "Les salles n'ont pas été enregistrées : corrigez les points ci-dessous.",
                            e.erreurs) from None
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
