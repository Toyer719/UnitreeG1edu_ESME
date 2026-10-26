"""Routes des lieux : liste, création, fiche (lieu.yaml) et vérification.

  GET  /api/lieux                      liste des lieux de $ATELIER_LIEUX
  POST /api/lieux                      {id, nom, largeur?, profondeur?, etage?, nom_etage?} : crée un lieu
  GET  /api/lieux/{id}                 fiche du lieu, avec ce qui existe pour chaque étage, et son point
                                       principal (vague 4 : {salle, nom, etage, x, y, theta, explicite} ou null)
  PUT  /api/lieux/{id}                 réécrit lieu.yaml (ajout au contrat : étages, accueil) ; vague 4 :
                                       accueil reste la copie du point principal (section 11.2 du plan)
  GET  /api/lieux/{id}/verification    règles entre fichiers (comme g1-lieu valider)
"""
from typing import Any

from fastapi import APIRouter, Body
from pydantic import BaseModel

import atelier
from atelier.lieu import (ErreurLieu, Lieu, PoseEtage, chemin_carte, chemin_interdit, chemin_monde, chemin_sdf,
                          charger_fiche, charger_itineraires, charger_salles, charger_zones, creer_lieu,
                          enregistrer_fiche, lister_lieux, point_principal, principal_explicite, valider_donnees)

from ..communs import (ErreurAtelier, dossier_du_lieu, erreur_validation, fiche_du_lieu, rapport_du_lieu,
                       verifier_id)

routeur = APIRouter(prefix="/api/lieux", tags=["lieux"])


class NouveauLieu(BaseModel):
    id: str
    nom: str
    largeur: float = 20.0
    profondeur: float = 15.0
    etage: str = "rdc"
    nom_etage: str = "Rez-de-chaussée"


def _resume(dossier):
    """Ce que la liste des lieux affiche ; un lieu illisible y figure avec son erreur."""
    try:
        fiche = charger_fiche(dossier)
    except ErreurLieu as e:
        return {"id": dossier.name, "nom": dossier.name, "etages": [], "erreur": "; ".join(e.erreurs)}
    return {"id": dossier.name, "nom": fiche.nom,
            "etages": [e.vers_dict() for e in fiche.etages]}


def _detail(dossier):
    """Fiche complète : lieu.yaml, et pour chaque étage les fichiers déjà présents."""
    fiche = fiche_du_lieu(dossier)
    etages = []
    for e in fiche.etages:
        etages.append(dict(e.vers_dict(),
                           a_monde=chemin_monde(dossier, e.id).is_file(),
                           a_sdf=chemin_sdf(dossier, e.id).is_file(),
                           a_carte=chemin_carte(dossier, e.id).is_file(),
                           a_interdit=chemin_interdit(dossier, e.id).is_file()))
    compte = {}
    for nom, lire, mesurer in (("salles", charger_salles, len),
                               ("noeuds", charger_itineraires, lambda i: len(i.noeuds)),
                               ("zones", charger_zones, lambda z: len(z.interdites) + len(z.lentes))):
        try:
            compte[nom] = mesurer(lire(dossier))
        except ErreurLieu:
            compte[nom] = None          # fichier invalide : la vérification le dira
    return dict(fiche.vers_dict(), id=dossier.name, dossier=str(dossier), etages=etages, compte=compte,
                principal=_principal(dossier))


def _principal(dossier):
    """Le point principal du lieu (vague 4, section 11.2), ou None (aucun, ou salles.yaml invalide)."""
    try:
        s = point_principal(dossier)
        if s is None:
            return None
        return {"salle": s.id, "nom": s.nom, "etage": s.etage, "x": s.pose.x, "y": s.pose.y,
                "theta": s.pose.theta, "explicite": principal_explicite(dossier)}
    except ErreurLieu:
        return None


@routeur.get("")
def liste_lieux():
    return [_resume(d) for d in lister_lieux()]


@routeur.post("", status_code=201)
def nouveau_lieu(demande: NouveauLieu):
    verifier_id(demande.id, "identifiant de lieu")
    verifier_id(demande.etage, "identifiant d'étage")
    if not demande.nom.strip():
        raise ErreurAtelier(400, "Donnez un nom au lieu (ex. « Lycée Victor Hugo »).")
    dossier = atelier.chemin_lieu(demande.id)
    if dossier.exists() and any(dossier.iterdir()):
        raise ErreurAtelier(409, f"Le lieu « {demande.id} » existe déjà : choisissez un autre identifiant.")
    try:
        creer_lieu(demande.id, demande.nom.strip(), etage=demande.etage, nom_etage=demande.nom_etage,
                   largeur=demande.largeur, profondeur=demande.profondeur)
    except ErreurLieu as e:
        raise ErreurAtelier(400, "Le lieu n'a pas été créé : " + "; ".join(e.erreurs), e.erreurs) from None
    return _detail(dossier)


@routeur.get("/{id_lieu}")
def lire_lieu(id_lieu: str):
    return _detail(dossier_du_lieu(id_lieu))


@routeur.put("/{id_lieu}")
def ecrire_lieu(id_lieu: str, donnees: Any = Body(...)):
    dossier = dossier_du_lieu(id_lieu)
    erreurs = valider_donnees("lieu", donnees, "lieu.yaml")
    if erreurs:
        raise erreur_validation("lieu.yaml", erreurs)
    fiche = Lieu.depuis_dict(donnees, dossier)
    # vague 4 (section 11.2) : accueil est la copie de la pose du point principal (onglet Salles)
    principal = _principal(dossier)
    if principal is not None and fiche.etage(principal["etage"]) is not None:
        fiche.accueil = PoseEtage(principal["etage"], principal["x"], principal["y"], principal["theta"])
    try:
        enregistrer_fiche(fiche, dossier)
    except ErreurLieu as e:
        raise erreur_validation("lieu.yaml", e.erreurs) from None
    return {"enregistre": ["lieu.yaml"], "lieu": _detail(dossier), "rapport": rapport_du_lieu(dossier)}


@routeur.get("/{id_lieu}/verification")
def verifier_lieu(id_lieu: str):
    return rapport_du_lieu(dossier_du_lieu(id_lieu))
