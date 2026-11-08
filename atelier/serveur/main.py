"""Serveur web de l'Atelier G1 (FastAPI). Lancé par bin/g1-atelier :

  uvicorn atelier.serveur.main:app --port 8000

  /api/...     API REST en JSON (contrat 4.4 du plan), voir atelier/serveur/routes/
  /ws/etat     WebSocket, environ 10 messages par seconde : {robot, guide, pietons, processus,
               mode, reperage, pont} ; vague 4 (section 11) : evenements, maitre, personnes, visiteurs ;
               vague 5 (section 12.4) : arret ; vague 6 (section 13) : seance, demo, voix
  /borne       vague 6 (section 13.5) : la page de la borne visiteur (tablette ou téléphone du même réseau)
  /            l'interface web (atelier/web), servie telle quelle

Vague 6 (section 13 du plan), deux accroches autour de toutes les demandes :
  JournalDesActions  après la réponse à chaque POST, PUT, PATCH ou DELETE sous /api/ (sauf les flèches de la
                     téléopération), etat.seance.noter_action(action) : le journal des actions de la boîte noire.
                     La réponse n'est jamais changée ni retardée ; une erreur de la boîte noire est avalée.
  GardeBorne         quand l'Atelier écoute le réseau (g1-atelier --hote 0.0.0.0 : ATELIER_HOTE), un client qui
                     n'est pas ce PC n'a droit qu'à la borne (atelier.lieu.accueil.chemin_permis_borne) ; le reste
                     répond 403. ATELIER_DISTANT=complet (g1-atelier --distant-complet) rend tout l'Atelier.

Variables d'environnement :
  ATELIER_LIEUX   dossier des lieux (défaut ~/robot-g1/lieux)
  ATELIER_BIN     dossier des commandes g1-* (défaut ~/robot-g1/bin)
  ATELIER_ROS     0 : pas de pont ROS 2 (tests de l'API sans ROS) ; défaut 1
  ATELIER_HOTE    adresse d'écoute du serveur (g1-atelier la met ; défaut : 127.0.0.1, ce PC seulement)
  ATELIER_PORT    port du serveur (g1-atelier le met ; pour l'adresse de la borne)
  ATELIER_DISTANT complet : tout l'Atelier depuis le réseau ; sinon la borne seulement (vague 6)
"""
import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

import atelier
from atelier.lieu import ErreurLieu
from atelier.lieu.accueil import chemin_permis_borne
from atelier.lieu.seance import LIMITE_CORPS_OCTETS, action_journalisee

from .communs import ErreurAtelier
from .etat import EtatServeur
from .processus import commande, dossier_bin
from .routes import lieux, monde, plan, robot, scan, simulation
# vague 4 (section 11 du plan) : une route par agent (point principal, passants, guide, pilotage, équipe)
from .routes import equipe, guide, passants, pilotage, principal
# vague 5 (section 12 du plan) : ARRÊT et liaison (Coquille), nuages 3D (Scan), flux de la caméra (Caméra)
from .routes import arret, camera, liaison, nuage
# vague 6 (section 13 du plan) : diagnostic, boîte noire, borne et démo, voix (un fichier par agent)
from .routes import borne, demo, diagnostic, seance, voix

DOSSIER_WEB = Path(__file__).resolve().parent.parent / "web"
PERIODE_DIRECT = 0.1      # s entre deux messages du WebSocket (10 par seconde)
COMMANDES = ("g1-lieu", "g1-monde", "g1-guide", "g1-slam", "g1-scan")
HOTES_LOCAUX = ("127.0.0.1", "::1", "localhost", "testclient")    # testclient : TestClient de Starlette (tests)
JOURNAL = logging.getLogger("atelier.serveur")


def client_local(hote):
    """Vrai si la demande vient de ce PC (boucle locale)."""
    hote = str(hote or "")
    return hote in HOTES_LOCAUX or hote.startswith(("127.", "::ffff:127."))


def ecoute_reseau():
    """Vrai si le serveur écoute sur une autre adresse que la boucle locale (ATELIER_HOTE, mis par g1-atelier)."""
    hote = os.environ.get("ATELIER_HOTE") or "127.0.0.1"
    return not client_local(hote)


def _lire_corps(octets, tronque):
    """Corps gardé dans le journal : le JSON lu s'il est entier et lisible, sinon le texte (coupé)."""
    if not octets:
        return None
    if not tronque:
        try:
            return json.loads(octets)
        except ValueError:
            pass
    texte = octets.decode("utf-8", "replace")
    return texte + (" […]" if tronque else "")


class JournalDesActions:
    """Accroche du journal des actions de la boîte noire (vague 6, section 13.3 du plan), en ASGI pur : la demande
    et la réponse passent telles quelles ; une copie de leurs premiers octets (LIMITE_CORPS_OCTETS) est donnée à
    etat.seance.noter_action APRÈS la réponse. Une erreur de la boîte noire ne gêne jamais une demande."""

    def __init__(self, app, etat):
        self.app = app
        self.etat = etat

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not action_journalisee(scope.get("method", ""), scope.get("path", "")):
            await self.app(scope, receive, send)
            return
        debut = time.monotonic()
        heure = datetime.now().astimezone().isoformat(timespec="milliseconds")
        requete, reponse = bytearray(), bytearray()
        vu = {"requete": 0, "reponse": 0, "statut": None}

        async def recevoir():
            message = await receive()
            if message.get("type") == "http.request":
                corps = message.get("body", b"")
                vu["requete"] += len(corps)
                requete.extend(corps[:max(0, LIMITE_CORPS_OCTETS - len(requete))])
            return message

        async def envoyer(message):
            if message.get("type") == "http.response.start":
                vu["statut"] = message.get("status")
            elif message.get("type") == "http.response.body":
                corps = message.get("body", b"")
                vu["reponse"] += len(corps)
                reponse.extend(corps[:max(0, LIMITE_CORPS_OCTETS - len(reponse))])
            await send(message)

        try:
            await self.app(scope, recevoir, envoyer)
        finally:
            self._noter(scope, heure, debut, requete, reponse, vu)

    def _noter(self, scope, heure, debut, requete, reponse, vu):
        try:
            hote = (scope.get("client") or ("", 0))[0]
            chemin = scope.get("path", "")
            local = client_local(hote)
            action = {"t": heure, "methode": scope.get("method"), "chemin": chemin,
                      "requete": _lire_corps(bytes(requete), vu["requete"] > len(requete)),
                      "statut": vu["statut"], "reponse": _lire_corps(bytes(reponse), vu["reponse"] > len(reponse)),
                      "duree_ms": round((time.monotonic() - debut) * 1000.0, 1),
                      "client": "local" if local else ("borne" if chemin_permis_borne(chemin) else "distant")}
            self.etat.seance.noter_action(action)
        except Exception:       # noqa: BLE001 : la boîte noire ne doit jamais gêner une demande
            JOURNAL.exception("journal des actions : action non notée")


class GardeBorne:
    """Garde de la borne (vague 6, section 13.5 du plan), en ASGI pur : quand l'Atelier écoute le réseau, un client
    qui n'est pas ce PC n'a droit qu'aux pages et aux routes de la borne ; tout le reste répond 403 (et un
    WebSocket est refusé). Inactive si l'Atelier n'écoute que ce PC, ou avec ATELIER_DISTANT=complet."""

    MESSAGE = ("Depuis cette tablette, seule la borne est permise (adresse /borne). L'Atelier complet s'utilise sur "
               "le PC du robot (ou relancez-le avec g1-atelier --distant-complet).")

    def __init__(self, app, active=None):
        self.app = app
        self.active = (ecoute_reseau() and os.environ.get("ATELIER_DISTANT") != "complet") if active is None \
            else bool(active)

    async def __call__(self, scope, receive, send):
        if not self.active or scope["type"] not in ("http", "websocket") \
                or client_local((scope.get("client") or ("", 0))[0]) or chemin_permis_borne(scope.get("path", "")):
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 4403})
            return
        corps = json.dumps({"detail": self.MESSAGE}, ensure_ascii=False).encode("utf-8")
        await send({"type": "http.response.start", "status": 403,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(corps)).encode()),
                                (b"cache-control", b"no-cache")]})
        await send({"type": "http.response.body", "body": corps})


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

    for module in (lieux, monde, plan, simulation, scan, robot, principal, passants, guide, pilotage, equipe,
                   arret, liaison, nuage, camera, diagnostic, seance, borne, demo, voix):
        app.include_router(module.routeur)
    # vague 6 (section 13) : la garde de la borne, puis le journal des actions autour de tout (une demande refusée
    # par la garde est notée aussi, client « distant »)
    app.add_middleware(GardeBorne)
    app.add_middleware(JournalDesActions, etat=etat)

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
