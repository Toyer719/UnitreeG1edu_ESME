"""Routes du point principal (vague 4, section 11.2 du plan) : agent Point principal.

  GET  /api/lieux/{id}/principal
        {salle, nom, etage, x, y, theta, explicite, depart_synchro, repere_unitree, pose_unitree}
        (pose_unitree : la pose que recevra 1804 quand le robot est posé sur le point principal) ;
        404 si le lieu n'a pas de point principal.
  PUT  /api/lieux/{id}/principal {salle?, x?, y?, theta?}
        atelier.lieu.principal.definir_principal : étiquette, pose et orientation ; accueil de lieu.yaml,
        nœud de même id et depart_robot synchronisés, tout ou rien ; {enregistre, principal, rapport}
        (plus changements, et avertissement si une navigation tourne sur ce lieu).
        x et y vont ensemble (400) ; 404 pour une salle inconnue ; 422 si un fichier serait invalide.
Voir aussi routes/plan.py (PUT …/salles : 0 ou 2 principaux refusés) et routes/robot.py (pose par
défaut de POST /api/robot/reperer : atelier.lieu.principal.pose_de_reperage), du même agent.
"""
import math
from typing import Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel

from atelier.lieu import ErreurLieu
from atelier.lieu.principal import SalleInconnue, decrire_principal, definir_principal

from ..communs import ErreurAtelier, dossier_du_lieu, verifier_id

routeur = APIRouter(prefix="/api/lieux/{id_lieu}", tags=["point principal"])

SANS_PRINCIPAL = ("Ce lieu n'a pas de point principal (l'accueil, où le robot démarre et revient après chaque "
                  "visite) : dans l'onglet Salles, faites d'une salle le point principal.")


class DemandePrincipal(BaseModel):
    salle: Optional[str] = None     # id de la salle qui devient le point principal
    x: Optional[float] = None       # m, repère map de l'étage de la salle (avec y)
    y: Optional[float] = None
    theta: Optional[float] = None   # rad, sens inverse des aiguilles d'une montre (0 : vers x)


def _lire(dossier):
    try:
        return decrire_principal(dossier)
    except ErreurLieu as e:
        raise ErreurAtelier(422, "Les fichiers du lieu sont invalides : corrigez les points ci-dessous.",
                            e.erreurs) from None


@routeur.get("/principal")
def lire_principal(id_lieu: str):
    principal = _lire(dossier_du_lieu(id_lieu))
    if principal is None:
        raise ErreurAtelier(404, SANS_PRINCIPAL)
    return principal


def _verifier(demande):
    """400 pour une demande vide, incomplète ou absurde (avant de toucher aux fichiers)."""
    if demande.salle is None and demande.x is None and demande.y is None and demande.theta is None:
        raise ErreurAtelier(400, "Rien à changer : donnez la salle qui devient le point principal (salle), sa "
                                 "position (x et y, en mètres) ou son orientation (theta, en radians).")
    if (demande.x is None) != (demande.y is None):
        manque = "y" if demande.y is None else "x"
        raise ErreurAtelier(400, f"x et y vont ensemble (il manque : {manque}).")
    for nom in ("x", "y", "theta"):
        v = getattr(demande, nom)
        if v is not None and not math.isfinite(v):
            raise ErreurAtelier(400, f"« {nom} » doit être un nombre fini, pas {v}.")
    if demande.theta is not None and abs(demande.theta) > 2 * math.pi + 1e-9:
        raise ErreurAtelier(400, "theta est en radians, entre -2π et 2π (par exemple 1.5708 pour un quart de tour).")
    if demande.salle is not None:
        verifier_id(demande.salle, "identifiant de salle")


@routeur.put("/principal")
def ecrire_principal(id_lieu: str, demande: DemandePrincipal, request: Request):
    dossier = dossier_du_lieu(id_lieu)
    _verifier(demande)
    try:
        r = definir_principal(dossier, salle=demande.salle, x=demande.x, y=demande.y, theta=demande.theta)
    except SalleInconnue as e:
        raise ErreurAtelier(404, f"La salle « {demande.salle} » n'existe pas dans ce lieu : placez-la d'abord dans "
                                 "l'onglet Salles.", e.erreurs) from None
    except ErreurLieu as e:
        raise ErreurAtelier(422, "Le point principal n'a pas été enregistré : corrigez les points ci-dessous.",
                            e.erreurs) from None
    etat = request.app.state.atelier
    s = etat.simulation
    tourne = etat.mode_navigation() is not None or etat.simulation_en_cours()
    if r["enregistre"] and s is not None and s.get("lieu") == id_lieu and tourne:
        r["avertissement"] = ("Une simulation ou une navigation tourne sur ce lieu : elle garde l'ancien point "
                              "principal (départ du robot, retour du guide). Arrêtez-la puis relancez-la pour partir "
                              "du nouveau ; « Repérer le robot », lui, vise déjà le nouveau.")
    return r
