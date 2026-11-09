"""Boîte noire et rapport de séance (vague 6, section 13.3 du plan) : agent Boîte noire.

  GET  /api/seance                       {seance: manifeste de la séance ouverte ou null, derniere: la dernière
                                         fermée ou null}
  POST /api/seance/demarrer {mode, lieu?, etage?, ouverture?}   ouvre la séance (reel ou repetition), ou rend
                                         celle qui est ouverte : {seance, nouvelle} (nouvelle : elle vient
                                         d'être ouverte) ; en simulation : 409
  POST /api/seance/arreter {fermeture?}  « Terminer la séance » : {seance} (rapport en cours) ; 404 sans séance ;
                                         fermeture simulation (l'espace rouvert en Simulation) : 409 tant que la
                                         navigation du robot ou de la répétition tourne
  GET  /api/seances                      les séances, la plus récente d'abord : [{id, etat, mode, lieu, etage, debut,
                                         fin, duree_s, actions, rapport, enregistrement}]
  GET  /api/seances/{id}                 seance.json
  GET  /api/seances/{id}/rapport         rapport.html (text/html) ; ?format=md|json ; 409 s'il s'écrit encore
  POST /api/seances/{id}/rapport         refait le rapport (en arrière-plan) : {seance} ; 409 si la séance est
                                         ouverte
  GET  /api/seances/{id}/fichiers/{nom}  un fichier de la liste blanche FICHIERS_PERMIS (jamais un chemin)
  GET  /api/seances/{id}/export          le dossier en .zip (application/zip) ; ?sans_bag=1 : sans l'enregistrement

Les routes lentes (ouvrir, fermer, exporter) passent dans un fil (run_in_threadpool) : l'ARRÊT et /ws/etat ne les
attendent jamais. Erreurs en français, {detail}, jamais d'erreur 500.
"""
import json
import os
import tempfile

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from starlette.background import BackgroundTask

from atelier.lieu.seance import MOTIF_ID_SEANCE, dossier_seances
from atelier.seance import manifeste as M

from ..communs import ErreurAtelier

routeur = APIRouter(tags=["séance"])

# Fichiers d'une séance servis un par un (nom → type) : jamais un chemin, jamais le bag (il est dans l'export)
FICHIERS_PERMIS = {"trajets.png": "image/png", "rapport.md": "text/markdown; charset=utf-8",
                   "rapport.json": "application/json", "rapport.html": "text/html; charset=utf-8",
                   "actions.jsonl": "application/x-ndjson", "seance.json": "application/json",
                   "diagnostic_debut.json": "application/json", "diagnostic_fin.json": "application/json",
                   "diagnostic_lancement.json": "application/json",
                   "enregistrement.json": "application/json"}
FORMATS_RAPPORT = {"html": ("rapport.html", "text/html; charset=utf-8"),
                   "md": ("rapport.md", "text/markdown; charset=utf-8"),
                   "json": ("rapport.json", "application/json")}


def _seance(request):
    return request.app.state.atelier.seance


async def _corps(request):
    """Le corps JSON de la demande (un dict), ou {} s'il est vide ; 422 en français s'il est illisible."""
    octets = await request.body()
    if not octets.strip():
        return {}
    try:
        donnees = json.loads(octets)
    except ValueError:
        raise ErreurAtelier(422, "Le corps de la demande n'est pas du JSON valable.") from None
    if not isinstance(donnees, dict):
        raise ErreurAtelier(422, "Le corps de la demande doit être un objet JSON ({…}).")
    return donnees


MESSAGE_NAVIGATION_EN_COURS = ("La navigation du robot (ou de la répétition) tourne encore : la séance continue "
                               "d'enregistrer. Arrêtez-la d'abord (Naviguer › Arrêter), ou terminez la séance.")


def _texte(donnees, nom):
    valeur = donnees.get(nom)
    if valeur is not None and not isinstance(valeur, str):
        raise ErreurAtelier(422, f"« {nom} » doit être un texte.")
    return valeur or None


def dossier_seance(ident):
    """Le dossier d'une séance d'après son id ; 404 en français sinon (jamais un chemin)."""
    if not isinstance(ident, str) or not MOTIF_ID_SEANCE.match(ident):
        raise ErreurAtelier(404, f"Séance inconnue : « {ident} » (un identifiant ressemble à 2026-11-12_14h03).")
    dossier = dossier_seances() / ident
    if not dossier.is_dir():
        raise ErreurAtelier(404, f"Séance inconnue : « {ident} ». La liste des séances : GET /api/seances "
                                 "(ou g1-seance liste).")
    return dossier


@routeur.get("/api/seance")
def seance(request: Request):
    s = _seance(request)
    return {"seance": s.manifeste_ouvert(), "derniere": s.derniere()}


@routeur.post("/api/seance/demarrer")
async def demarrer(request: Request):
    d = await _corps(request)
    ouverture = _texte(d, "ouverture") or "manuel"
    avant = _seance(request).etat()
    m = await run_in_threadpool(_seance(request).demarrer, _texte(d, "mode"), _texte(d, "lieu"),
                                _texte(d, "etage"), ouverture)
    # nouvelle : cette demande a ouvert la séance (sinon, celle qui était déjà ouverte est rendue telle quelle ; la
    # boîte noire n'écrit pas ce « rien » dans le journal des actions : corrections de la vague 6)
    return {"seance": m, "nouvelle": avant is None or avant.get("id") != (m or {}).get("id")}


@routeur.post("/api/seance/arreter")
async def arreter(request: Request):
    d = await _corps(request)
    fermeture = _texte(d, "fermeture") or "terminer"
    if fermeture not in ("terminer", "g1-seance", "simulation"):
        raise ErreurAtelier(422, "« fermeture » vaut terminer (bouton « Terminer la séance »), g1-seance ou "
                                 "simulation (l'espace rouvert en Simulation).")
    if fermeture == "simulation":
        # corrections de la vague 6 : une séance correspond au mode Réel ; rouvrir l'espace en Simulation la termine,
        # sauf si la navigation du robot (ou de la répétition) tourne encore : elle continue d'enregistrer
        mode = request.app.state.atelier.mode_navigation()
        if mode in ("robot", "repetition"):
            raise ErreurAtelier(409, MESSAGE_NAVIGATION_EN_COURS)
    m = await run_in_threadpool(_seance(request).arreter, fermeture)
    if m is None:
        raise ErreurAtelier(404, "Aucune séance ouverte : elle s'ouvre seule quand on ouvre l'espace de travail en "
                                 "Réel (ou avec g1-seance demarrer).")
    return {"seance": m}


@routeur.get("/api/seances")
def seances(request: Request):
    liste = []
    for _, dossier in M.liste_seances():
        m = M.lire_manifeste(dossier)
        if m is not None:
            liste.append(M.resume(m))
    return liste


@routeur.get("/api/seances/{ident}")
def une_seance(ident: str, request: Request):
    dossier = dossier_seance(ident)
    m = M.lire_manifeste(dossier)
    if m is None:
        raise ErreurAtelier(404, f"La séance « {ident} » n'a pas de seance.json lisible (dossier abîmé ?).")
    return m


@routeur.get("/api/seances/{ident}/rapport")
def rapport(ident: str, request: Request, format: str = "html"):
    dossier = dossier_seance(ident)
    if format not in FORMATS_RAPPORT:
        raise ErreurAtelier(422, "« format » vaut html, md ou json.")
    nom, type_ = FORMATS_RAPPORT[format]
    chemin = dossier / nom
    if not chemin.is_file():
        m = M.lire_manifeste(dossier) or {}
        etat = (m.get("rapport") or {}).get("etat")
        if m.get("etat") == "ouverte":
            raise ErreurAtelier(409, "La séance est encore ouverte : son rapport s'écrira tout seul quand elle sera "
                                     "terminée (« Terminer la séance »).")
        if etat == "en_cours":
            raise ErreurAtelier(409, "Le rapport s'écrit encore (une minute au plus) : réessayez dans un instant.")
        raise ErreurAtelier(404, "Pas encore de rapport pour cette séance : « Rapport de séance » › Refaire (ou "
                                 f"g1-seance rapport {ident}).")
    if format == "html":
        return HTMLResponse(chemin.read_text(encoding="utf-8"))
    if format == "md":
        return PlainTextResponse(chemin.read_text(encoding="utf-8"), media_type=type_)
    return FileResponse(chemin, media_type=type_)


@routeur.post("/api/seances/{ident}/rapport")
async def refaire_rapport(ident: str, request: Request):
    dossier = dossier_seance(ident)
    m = M.lire_manifeste(dossier) or {}
    if m.get("etat") == "ouverte":
        raise ErreurAtelier(409, "La séance est encore ouverte : terminez-la d'abord (son rapport s'écrit alors tout "
                                 "seul).")

    def lancer():
        M.modifier_manifeste(dossier, lambda x: x.__setitem__(
            "rapport", {"etat": "en_cours", "fichiers": [], "message": None, "date": None}))
        _seance(request).lancer_rapport(dossier)
        return M.lire_manifeste(dossier)
    return {"seance": await run_in_threadpool(lancer)}


@routeur.get("/api/seances/{ident}/fichiers/{nom}")
def fichier(ident: str, nom: str, request: Request):
    dossier = dossier_seance(ident)
    if nom not in FICHIERS_PERMIS:
        permis = ", ".join(sorted(FICHIERS_PERMIS))
        raise ErreurAtelier(404, f"Fichier non servi : « {nom} ». Fichiers permis : {permis} (tout le dossier : "
                                 "…/export).")
    chemin = dossier / nom
    if not chemin.is_file():
        raise ErreurAtelier(404, f"La séance « {ident} » n'a pas (encore) de {nom}.")
    return FileResponse(chemin, media_type=FICHIERS_PERMIS[nom])


@routeur.get("/api/seances/{ident}/export")
async def exporter(ident: str, request: Request, sans_bag: int = 0):
    from atelier.seance.export import exporter as exporter_seance
    dossier = dossier_seance(ident)
    fd, chemin = tempfile.mkstemp(prefix=f"seance_{ident}_", suffix=".zip")
    os.close(fd)
    try:
        await run_in_threadpool(exporter_seance, dossier, chemin, bool(sans_bag))
    except OSError as e:
        os.unlink(chemin)
        raise ErreurAtelier(503, f"Export impossible : {e}.") from None
    return FileResponse(chemin, media_type="application/zip", filename=f"seance_{ident}.zip",
                        background=BackgroundTask(os.unlink, chemin))
