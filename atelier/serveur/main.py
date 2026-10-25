"""Serveur web de l'Atelier G1 (FastAPI). Lancé par bin/g1-atelier :

  uvicorn atelier.serveur.main:app --port 8000

  /api/...     API REST en JSON (contrat 4.4 du plan), voir atelier/serveur/routes/
  /ws/etat     WebSocket, environ 10 messages par seconde : {robot, guide, pietons, processus}
  /            l'interface web (atelier/web), servie telle quelle

Variables d'environnement :
  ATELIER_LIEUX   dossier des lieux (défaut ~/robot-g1/lieux)
  ATELIER_BIN     dossier des commandes g1-* (défaut ~/robot-g1/bin)
  ATELIER_ROS     0 : pas de pont ROS 2 (tests de l'API sans ROS) ; défaut 1
"""
import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

import atelier
from atelier.lieu import ErreurLieu

from .communs import ErreurAtelier
from .etat import EtatServeur
from .processus import commande, dossier_bin
from .routes import lieux, monde, plan, scan, simulation

DOSSIER_WEB = Path(__file__).resolve().parent.parent / "web"
PERIODE_DIRECT = 0.1      # s entre deux messages du WebSocket (10 par seconde)
COMMANDES = ("g1-lieu", "g1-monde", "g1-guide", "g1-slam", "g1-scan")


def _champ(loc):
    """Nom lisible du champ en faute dans une erreur de FastAPI : ('body', 'lieu') → « lieu »."""
    morceaux = [str(m) for m in loc if m not in ("body", "query", "path")]
    return ".".join(morceaux) or "corps de la demande"


def _traduire(erreur):
    champ, genre = _champ(erreur.get("loc", ())), erreur.get("type", "")
    if genre == "missing":
        return f"il manque le champ « {champ} »"
    if genre.startswith("bool"):
        return f"« {champ} » doit valoir true ou false"
    if genre.startswith(("float", "int")):
        return f"« {champ} » doit être un nombre"
    if genre.startswith("string"):
        return f"« {champ} » doit être un texte"
    if genre == "json_invalid":
        return "le corps de la demande n'est pas du JSON valable"
    return f"« {champ} » : valeur refusée ({erreur.get('msg', genre)})"


def creer_app(ros=None):
    """Application FastAPI. ros : démarrer le pont ROS 2 (défaut : $ATELIER_ROS, sinon oui)."""
    if ros is None:
        ros = os.environ.get("ATELIER_ROS", "1") != "0"
    etat = EtatServeur(ros=ros)

    @asynccontextmanager
    async def cycle_de_vie(app):
        await run_in_threadpool(etat.demarrer)
        try:
            yield
        finally:
            # rien ne doit survivre au serveur : simulation, navigation, nœud ROS 2
            await run_in_threadpool(etat.arreter)

    app = FastAPI(title="Atelier G1", version=atelier.__version__, lifespan=cycle_de_vie,
                  description="Configuration des lieux du robot d'accueil G1.")
    app.state.atelier = etat

    @app.exception_handler(ErreurAtelier)
    async def _erreur_atelier(request: Request, e: ErreurAtelier):
        return JSONResponse(e.vers_dict(), status_code=e.statut)

    @app.exception_handler(ErreurLieu)
    async def _erreur_lieu(request: Request, e: ErreurLieu):
        return JSONResponse({"detail": "Fichier du lieu invalide : corrigez les points ci-dessous.",
                             "erreurs": e.erreurs}, status_code=422)

    @app.exception_handler(RequestValidationError)
    async def _demande_invalide(request: Request, e: RequestValidationError):
        erreurs = [_traduire(x) for x in e.errors()]
        return JSONResponse({"detail": "Demande incomplète ou mal formée : " + " ; ".join(erreurs) + ".",
                             "erreurs": erreurs}, status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, e: StarletteHTTPException):
        if e.status_code == 404:
            detail = f"Adresse inconnue : {request.url.path}"
        elif e.status_code == 405:
            detail = f"Méthode {request.method} non permise sur {request.url.path}"
        else:
            detail = str(e.detail)
        return JSONResponse({"detail": detail}, status_code=e.status_code)

    @app.middleware("http")
    async def _sans_cache(request: Request, suite):
        # l'interface évolue souvent : le navigateur redemande toujours les fichiers
        reponse = await suite(request)
        reponse.headers.setdefault("Cache-Control", "no-cache")
        return reponse

    for module in (lieux, monde, plan, simulation, scan):
        app.include_router(module.routeur)

    @app.get("/api/etat", tags=["serveur"])
    def etat_serveur():
        """Ajout au contrat : commandes g1-* présentes, liaison ROS 2, lieux."""
        pont = etat.pont.etat()
        return {"version": atelier.__version__, "lieux": str(atelier.dossier_lieux()),
                "bin": str(dossier_bin()),
                "commandes": {nom: commande(nom) is not None for nom in COMMANDES},
                "ros": {"actif": pont["actif"], "erreur": pont["erreur"],
                        "domaine": os.environ.get("ROS_DOMAIN_ID", "0")}}

    @app.websocket("/ws/etat")
    async def direct(ws: WebSocket):
        await ws.accept()
        try:
            while True:
                await ws.send_json(etat.etat_direct())
                await asyncio.sleep(PERIODE_DIRECT)
        except (WebSocketDisconnect, RuntimeError, ConnectionError):
            pass        # l'onglet a été fermé

    app.mount("/", StaticFiles(directory=DOSSIER_WEB, html=True), name="web")
    return app


app = creer_app()
