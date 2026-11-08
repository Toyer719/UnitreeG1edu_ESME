"""Boîte noire et rapport de séance (vague 6, section 13.3 du plan) : agent Boîte noire.

  GET  /api/seance                       {seance: manifeste de la séance ouverte ou null, derniere: la dernière
                                         fermée ou null}
  POST /api/seance/demarrer {mode, lieu?, etage?, ouverture?}   ouvre la séance (reel ou repetition), ou rend
                                         celle qui est ouverte : {seance} ; en simulation : 409
  POST /api/seance/arreter {fermeture?}  « Terminer la séance » : {seance} (rapport en cours) ; 404 sans séance
  GET  /api/seances                      les séances, la plus récente d'abord : [{id, etat, mode, lieu, debut,
                                         duree_s, rapport}]
  GET  /api/seances/{id}                 seance.json
  GET  /api/seances/{id}/rapport         rapport.html (text/html) ; ?format=md|json
  POST /api/seances/{id}/rapport         refait le rapport
  GET  /api/seances/{id}/fichiers/{nom}  trajets.png, rapport.md, actions.jsonl, diagnostic_debut.json (liste
                                         blanche ; jamais un chemin)
  GET  /api/seances/{id}/export          le dossier en .zip (application/zip)

Squelette livré par l'agent Contrats : chaque route répond 501 tant que l'agent Boîte noire ne l'a pas écrite.
"""
from fastapi import APIRouter, Request

from ..communs import pas_encore_fait

routeur = APIRouter(tags=["séance"])


def _pas_encore_fait(quoi):
    return pas_encore_fait(quoi, "Boîte noire", "13.3")


@routeur.get("/api/seance")
def seance(request: Request):
    raise _pas_encore_fait("la séance en cours")


@routeur.post("/api/seance/demarrer")
async def demarrer(request: Request):
    raise _pas_encore_fait("ouvrir une séance")


@routeur.post("/api/seance/arreter")
async def arreter(request: Request):
    raise _pas_encore_fait("terminer la séance")


@routeur.get("/api/seances")
def seances(request: Request):
    raise _pas_encore_fait("la liste des séances")


@routeur.get("/api/seances/{ident}")
def une_seance(ident: str, request: Request):
    raise _pas_encore_fait("une séance")


@routeur.get("/api/seances/{ident}/rapport")
def rapport(ident: str, request: Request, format: str = "html"):
    raise _pas_encore_fait("le rapport de séance")


@routeur.post("/api/seances/{ident}/rapport")
async def refaire_rapport(ident: str, request: Request):
    raise _pas_encore_fait("refaire le rapport de séance")


@routeur.get("/api/seances/{ident}/fichiers/{nom}")
def fichier(ident: str, nom: str, request: Request):
    raise _pas_encore_fait("un fichier de séance")


@routeur.get("/api/seances/{ident}/export")
def exporter(ident: str, request: Request):
    raise _pas_encore_fait("l'export d'une séance")
