"""Diagnostic « Vérifier le robot » (vague 6, section 13.2 du plan) : agent Diagnostic.

  GET  /api/robot/diagnostic?mode=reel|repetition[&rapide=1]
        toutes les vérifications (atelier.diagnostic.diagnostiquer), en 15 s au plus : schéma diagnostic ;
        mode absent : celui de la navigation qui tourne, sinon reel ; rapide : sans ssh vers le Jetson.
  GET  /api/robot/diagnostic/dernier
        le dernier résultat (aussi gardé par la séance ouverte) ; 404 s'il n'y en a pas encore.
  POST /api/robot/diagnostic/{action} {confirme: true, services?: [...], mode?}
        une action de atelier.lieu.diagnostic.ACTIONS_DIAGNOSTIC, seulement sur un clic confirmé : sans
        « confirme » : 409 ; action inconnue : 404 ; service hors de SERVICES_CARTOGRAPHIE : 403 ; en simulation
        (pas de robot) : 409. Réponse {action, ok, message, diagnostic?}.

Squelette livré par l'agent Contrats : chaque route répond 501 tant que l'agent Diagnostic ne l'a pas écrite.
Jamais d'erreur 500 ; messages en français, {detail, …}.
"""
from fastapi import APIRouter, Request

from ..communs import pas_encore_fait

routeur = APIRouter(tags=["diagnostic"])


@routeur.get("/api/robot/diagnostic")
def diagnostic(request: Request, mode: str = None, rapide: bool = False):
    raise pas_encore_fait("le diagnostic du robot", "Diagnostic", "13.2")


@routeur.get("/api/robot/diagnostic/dernier")
def dernier(request: Request):
    raise pas_encore_fait("le dernier diagnostic", "Diagnostic", "13.2")


@routeur.post("/api/robot/diagnostic/{action}")
async def action(action: str, request: Request):
    raise pas_encore_fait("les actions du diagnostic", "Diagnostic", "13.2")
