"""Routes du comportement du guide (vague 4, section 11.4 du plan) : agent Comportement du guide.

  GET  /api/lieux/{id}/guide     section guide de lieu.yaml : {guide, reglages, defauts, principal}
                                 (reglages : les valeurs en vigueur, défauts compris)
  PUT  /api/lieux/{id}/guide     {retour_auto?, delai_avant_retour_s?, ...} : la section guide (un
                                 champ absent ou null reprend sa valeur par défaut ; {} retire la
                                 section) ; réponse {enregistre, guide, reglages, rapport} ; 422 si un
                                 champ est faux (en français)
  GET  /api/guide/evenements     derniers messages /guide/evenement (aussi dans /ws/etat : evenements)
  POST /api/guide/visiteur {mode}   simulation seulement : mode du faux visiteur (/faux_visiteur/mode :
                                 suivre, trainer, partir, arreter)
Voir aussi routes/simulation.py (POST /api/guide/aller avec accompagner et retour), du même agent.
"""
from typing import Any

from fastapi import APIRouter, Body, Request
from pydantic import BaseModel

from atelier.lieu import ErreurLieu, enregistrer_fiche, valider_donnees
from atelier.lieu.comportement import (CODES_EVENEMENT, DELAIS_GUIDE, MODES_FAUX_VISITEUR, SUJET_EVENEMENT,
                                       SUJET_FAUX_VISITEUR, reglages_guide)

from ..communs import (ErreurAtelier, dossier_du_lieu, erreur_validation, fiche_du_lieu, rapport_du_lieu)

routeur = APIRouter(tags=["guide"])


class DemandeVisiteur(BaseModel):
    mode: str


def _principal(dossier):
    from atelier.lieu.principal import point_principal
    try:
        s = point_principal(dossier)
    except ErreurLieu:
        return None
    return None if s is None else {"salle": s.id, "nom": s.nom, "etage": s.etage}


def _reponse(dossier, fiche):
    return {"guide": dict(fiche.guide or {}), "reglages": reglages_guide(fiche), "defauts": dict(DELAIS_GUIDE),
            "principal": _principal(dossier)}


@routeur.get("/api/lieux/{id_lieu}/guide")
def lire_guide(id_lieu: str):
    dossier = dossier_du_lieu(id_lieu)
    return _reponse(dossier, fiche_du_lieu(dossier))


@routeur.put("/api/lieux/{id_lieu}/guide")
def ecrire_guide(id_lieu: str, donnees: Any = Body(...)):
    dossier = dossier_du_lieu(id_lieu)
    if not isinstance(donnees, dict):
        raise ErreurAtelier(422, "Les réglages du guide sont un objet JSON, par exemple "
                                 "{\"delai_avant_retour_s\": 10}.")
    inconnus = sorted(set(donnees) - set(DELAIS_GUIDE))
    if inconnus:
        raise erreur_validation("lieu.yaml", [f"lieu.yaml : guide : réglage inconnu « {c} » (réglages : "
                                              f"{', '.join(DELAIS_GUIDE)})" for c in inconnus])
    fiche = fiche_du_lieu(dossier)
    section = {c: v for c, v in donnees.items() if v is not None}
    fiche.guide = section or None
    erreurs = valider_donnees("lieu", fiche.vers_dict(), "lieu.yaml")
    if erreurs:
        raise erreur_validation("lieu.yaml", erreurs)
    try:
        enregistrer_fiche(fiche, dossier)
    except ErreurLieu as e:
        raise erreur_validation("lieu.yaml", e.erreurs) from None
    reponse = _reponse(dossier, fiche_du_lieu(dossier))
    reponse.update(enregistre=["lieu.yaml"], rapport=rapport_du_lieu(dossier))
    reponse["note"] = ("Les nouveaux réglages valent au prochain lancement de la navigation (simulation, "
                       "répétition ou robot).")
    return reponse


@routeur.get("/api/guide/evenements")
def evenements(request: Request):
    etat = request.app.state.atelier
    return {"evenements": etat.pont.historique(SUJET_EVENEMENT) if etat.pont.actif else [],
            "codes": dict(CODES_EVENEMENT)}


def _publieur_mode(etat):
    """Publieur de /faux_visiteur/mode sur le nœud du pont ROS 2 du serveur (refait s'il a redémarré)."""
    noeud = etat.pont._noeud
    cache = getattr(etat, "_pub_faux_visiteur", None)
    if cache is None or cache[0] is not noeud:
        from std_msgs.msg import String
        cache = (noeud, noeud.create_publisher(String, SUJET_FAUX_VISITEUR, 10), String)
        etat._pub_faux_visiteur = cache
    return cache[1], cache[2]


@routeur.post("/api/guide/visiteur")
def mode_visiteur(demande: DemandeVisiteur, request: Request):
    etat = request.app.state.atelier
    mode = demande.mode.strip()
    if mode not in MODES_FAUX_VISITEUR:
        raise ErreurAtelier(400, f"Mode du faux visiteur inconnu : « {mode} » ({', '.join(MODES_FAUX_VISITEUR)}).")
    if not etat.simulation_en_cours() or etat.mode() != "simu":
        raise ErreurAtelier(409, "Le faux visiteur n'existe qu'en simulation : lancez la simulation (mode "
                                 "« Simulation ») avec une scène d'accompagnement.")
    if not etat.pont.actif or etat.pont._noeud is None:
        raise ErreurAtelier(503, "Pas de liaison avec ROS 2 : "
                            + (etat.pont.erreur or "le pont ROS 2 du serveur n'est pas démarré") + ".")
    pub, String = _publieur_mode(etat)
    pub.publish(String(data=mode))
    reponse = {"envoye": mode, "ecoute": pub.get_subscription_count()}
    if reponse["ecoute"] == 0:
        reponse["avertissement"] = ("Aucun faux visiteur dans cette simulation : il vient avec une scène "
                                    "d'accompagnement (Simuler › Avancé › Passants, scènes d'essai).")
    return reponse
