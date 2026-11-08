"""La démo d'accueil depuis l'Atelier (vague 6, section 13.4 du plan) : agent Borne et orchestrateur.

  GET  /api/demo/etat                    {lancee, etat: dernier /accueil/etat (ou null, ou périmé de plus de 3 s),
                                         voix: dernier /voix/etat, processus: {demo, voix}, borne: {adresses}}
  POST /api/demo/lancer {lieu, etage}    lance g1-accueil (rôle demo) et g1-voix (rôle voix, avec la sortie de
                                         demo.yaml) ; 409 si le guide ne tourne pas (ni simulation ni navigation),
                                         ou, en Réel et en répétition, si le robot n'est pas repéré
  POST /api/demo/arreter                 arrête la démo et la voix ; le robot n'est pas arrêté par cela (ARRÊT)
  POST /api/demo/commande {action}       /accueil/commande depuis l'Atelier (source atelier) : pause, reprendre,
                                         ramener, remise_a_zero ; réponse de la démo (2 s au plus)
  GET  /api/lieux/{id}/demo              demo.yaml complété par les défauts (atelier.lieu.accueil.reglages_demo)
  PUT  /api/lieux/{id}/demo              écrit demo.yaml (atelier.lieu.accueil.enregistrer_demo)

Squelette livré par l'agent Contrats : chaque route répond 501 tant que l'agent ne l'a pas écrite.
"""
from fastapi import APIRouter, Request

from ..communs import pas_encore_fait

routeur = APIRouter(tags=["démo"])


def _pas_encore_fait(quoi):
    return pas_encore_fait(quoi, "Borne et orchestrateur", "13.4")


@routeur.get("/api/demo/etat")
def etat_demo(request: Request):
    raise _pas_encore_fait("l'état de la démo")


@routeur.post("/api/demo/lancer")
async def lancer(request: Request):
    raise _pas_encore_fait("lancer la démo")


@routeur.post("/api/demo/arreter")
async def arreter(request: Request):
    raise _pas_encore_fait("arrêter la démo")


@routeur.post("/api/demo/commande")
async def commande(request: Request):
    raise _pas_encore_fait("les commandes de la démo")


@routeur.get("/api/lieux/{id_lieu}/demo")
def lire_reglages(id_lieu: str, request: Request):
    raise _pas_encore_fait("les réglages de la démo")


@routeur.put("/api/lieux/{id_lieu}/demo")
async def ecrire_reglages(id_lieu: str, request: Request):
    raise _pas_encore_fait("enregistrer les réglages de la démo")
