"""La voix du robot depuis l'Atelier (vague 6, section 13.6 du plan) : agent Voix.

  GET  /api/voix/etat                    {lancee, etat: dernier /voix/etat (ou null), voix: les voix Piper
                                         présentes, sorties: SORTIES_VOIX}
  POST /api/voix/demarrer {lieu?, sortie?, volume?}   g1-voix (rôle voix)
  POST /api/voix/arreter                 arrête le nœud voix (STOP_PLAY d'abord)
  POST /api/voix/essayer {texte, priorite?}   /robot/dire (source atelier) ; 409 si le nœud voix ne tourne pas
  POST /api/voix/commande {action, …}    /voix/commande (schéma commande_voix) : taire, volume, sortie, voix
  GET  /api/voix/son/{id}                le WAV d'une phrase (sortie borne), audio/wav ; 404 sinon ; permis depuis
                                         la borne

Squelette livré par l'agent Contrats : chaque route répond 501 tant que l'agent Voix ne l'a pas écrite.
"""
from fastapi import APIRouter, Request

from ..communs import pas_encore_fait

routeur = APIRouter(tags=["voix"])


def _pas_encore_fait(quoi):
    return pas_encore_fait(quoi, "Voix", "13.6")


@routeur.get("/api/voix/etat")
def etat_voix(request: Request):
    raise _pas_encore_fait("l'état de la voix")


@routeur.post("/api/voix/demarrer")
async def demarrer(request: Request):
    raise _pas_encore_fait("démarrer la voix")


@routeur.post("/api/voix/arreter")
async def arreter(request: Request):
    raise _pas_encore_fait("arrêter la voix")


@routeur.post("/api/voix/essayer")
async def essayer(request: Request):
    raise _pas_encore_fait("essayer une phrase")


@routeur.post("/api/voix/commande")
async def commande(request: Request):
    raise _pas_encore_fait("les commandes de la voix")


@routeur.get("/api/voix/son/{ident}")
def son(ident: str, request: Request):
    raise _pas_encore_fait("le son d'une phrase")
