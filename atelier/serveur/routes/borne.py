"""La borne visiteur (vague 6, section 13.5 du plan) : agent Borne et orchestrateur.

  GET  /borne                            la page de la borne (atelier/web/borne.html), pour une tablette ou un
                                         téléphone du même réseau (g1-atelier --hote 0.0.0.0)
  GET  /api/borne/etat                   ce que la borne montre : schéma etat_borne
  WS   /ws/borne                         le même, 4 fois par seconde et à chaque changement
  POST /api/borne/appui                  le visiteur touche l'écran : /accueil/commande appui
  POST /api/borne/choisir {salle}        /accueil/choix (source borne), puis la réponse de la démo
                                         (/accueil/evenement, 2 s au plus) : 200 {accepte, visite} ; 409 (occupé,
                                         pause, démo arrêtée) ; 404 (salle inconnue) ; 422 (salle cachée, autre étage)
  POST /api/borne/annuler                retour à l'écran des salles (/accueil/commande annuler)
  POST /api/borne/operateur {code}       code opérateur (demo.yaml) : {jeton, expire_s} ; 403 mauvais code ; 409
                                         pas de code réglé ; 429 trop d'essais (5 par 5 min)
  POST /api/borne/operateur/{action}     pause, reprendre ou ramener, avec l'en-tête X-Jeton-Borne ; 401 sans jeton
  GET  /api/borne/adresse                pour l'Atelier : {adresses: [http://IP:port/borne…], ecoute_reseau, port,
                                         message} (« relancez avec g1-atelier --hote 0.0.0.0 » sinon)

Depuis la borne (un client qui n'est pas ce PC), seules ces pages et ces routes sont permises (garde de main.py,
atelier.lieu.accueil.chemin_permis_borne) : rien d'autre, ni l'ARRÊT contourné, ni les réglages.

Squelette livré par l'agent Contrats : les routes répondent 501 tant que l'agent ne les a pas écrites ; /borne
sert déjà la page (squelette).
"""
from pathlib import Path

from fastapi import APIRouter, Request, WebSocket
from fastapi.responses import FileResponse

from ..communs import ErreurAtelier, pas_encore_fait

routeur = APIRouter(tags=["borne"])

PAGE_BORNE = Path(__file__).resolve().parents[2] / "web" / "borne.html"


def _pas_encore_fait(quoi):
    return pas_encore_fait(quoi, "Borne et orchestrateur", "13.5")


@routeur.get("/borne", include_in_schema=False)
@routeur.get("/borne/", include_in_schema=False)
def page_borne():
    if not PAGE_BORNE.is_file():
        raise ErreurAtelier(404, "La page de la borne n'est pas encore installée (atelier/web/borne.html).")
    return FileResponse(PAGE_BORNE, media_type="text/html")


@routeur.get("/api/borne/etat")
def etat_borne(request: Request):
    raise _pas_encore_fait("l'état de la borne")


@routeur.websocket("/ws/borne")
async def direct_borne(ws: WebSocket):
    await ws.accept()
    await ws.send_json({"detail": _pas_encore_fait("l'état de la borne en direct").detail})
    await ws.close()


@routeur.post("/api/borne/appui")
async def appui(request: Request):
    raise _pas_encore_fait("l'appui sur la borne")


@routeur.post("/api/borne/choisir")
async def choisir(request: Request):
    raise _pas_encore_fait("le choix d'une salle")


@routeur.post("/api/borne/annuler")
async def annuler(request: Request):
    raise _pas_encore_fait("l'annulation à la borne")


@routeur.post("/api/borne/operateur")
async def operateur(request: Request):
    raise _pas_encore_fait("le code opérateur")


@routeur.post("/api/borne/operateur/{action}")
async def action_operateur(action: str, request: Request):
    raise _pas_encore_fait("le mode opérateur")


@routeur.get("/api/borne/adresse")
def adresse(request: Request):
    raise _pas_encore_fait("l'adresse de la borne")
