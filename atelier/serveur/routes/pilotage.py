"""Routes du pilotage (vague 4, section 11.5 du plan) : agent Pilotage et danses.

Le serveur de l'Atelier ne commande jamais le robot de lui-même : il relaie l'onglet Pilotage vers
l'API HTTP et WebSocket du nœud pilotage (paquet g1_pilotage), à l'adresse $G1_PILOTAGE_URL (défaut
http://127.0.0.1:8010 : la répétition sur le PC ; avec le robot, l'adresse du Jetson), avec le jeton
$G1_PILOTAGE_JETON (sinon celui écrit par « g1-jetson demarrer » dans opt/jetson/jeton_pilotage)
dans l'en-tête X-Jeton. Toutes les règles de sécurité sont dans le nœud (atelier.lieu.pilotage et
g1_pilotage.logique) : ce relais les reprend telles quelles, statut et message compris.

  GET  /api/pilotage/config            valeurs du contrat pour l'onglet (postures, gestes, limites…)
  GET  /api/pilotage/etat              état du nœud (503 s'il ne répond pas)
  POST /api/pilotage/demarrer|arreter  le nœud sur le PC (simulation, répétition) : rôle « pilotage »
  POST /api/pilotage/{maitre, posture, tache, geste, voix, volume, led, danse, requete, arret}
  GET  /api/pilotage/danses[?lire=1], /api/pilotage/gestes[?lire=1]
  GET  /api/pilotage/choregraphies, GET|PUT|DELETE /api/pilotage/choregraphies/{id}
  POST /api/pilotage/choregraphies/verifier {choregraphie}   POST …/{id}/jouer {zone_libre, vitesse?}
  GET  /api/pilotage/musique/{fichier}  fichiers de choregraphies/musique/ (jamais dans Git)
  GET  /api/pilotage/modele, /api/pilotage/modele/maillages/{nom}.STL   le G1 pour l'aperçu 3D
  WS   /ws/pilotage                    joystick : relayé vers /joystick du nœud (homme mort au nœud)

ARRÊT : si le nœud ne répond pas, le serveur publie quand même /guide/stop et le dit (503).
Dossier des chorégraphies : $ATELIER_CHOREGRAPHIES (tests), sinon ~/robot-g1/choregraphies.
"""
import asyncio
import json
import math
import os
import re
import time
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, Response

import atelier
from atelier.lieu import ErreurLieu
from atelier.lieu import pilotage as D
from atelier.lieu import robot as R
from atelier.lieu.fichiers import lire_yaml

from ..communs import ErreurAtelier

routeur = APIRouter(tags=["pilotage"])

URL_DEFAUT = f"http://127.0.0.1:{D.PORT_PILOTAGE}"
FICHIER_JETON = atelier.RACINE / "opt" / "jetson" / "jeton_pilotage"
DELAI_HTTP_S = 8.0               # posture ou geste : le nœud attend la réponse du robot (2 s)
DELAI_DEMARRAGE_S = 20.0         # le nœud lancé par l'Atelier répond à /etat
EXEMPLE_PROTEGE = "exemple_kpop"  # l'exemple du dépôt ne s'écrase pas depuis l'onglet
DESCRIPTION_G1 = atelier.RACINE / "third_party" / "unitree_rl_gym" / "resources" / "robots" / "g1_description"
URDF_G1 = DESCRIPTION_G1 / "g1_29dof_rev_1_0.urdf"
MAILLAGES_G1 = (atelier.RACINE / "ws" / "src" / "g1_sim" / "models" / "g1_proxy" / "meshes",
                DESCRIPTION_G1 / "meshes")
MOTIF_MAILLAGE = re.compile(r"^[A-Za-z0-9_]{1,80}\.STL$")
MOTIF_MUSIQUE = re.compile(r"^[^/\\]{1,120}\.(mp3|ogg|wav)$")
TYPES_MUSIQUE = {"mp3": "audio/mpeg", "ogg": "audio/ogg", "wav": "audio/wav"}
RELAIS = ("maitre", "posture", "tache", "geste", "voix", "volume", "led", "danse", "requete")


# ---------------------------------------------------------------- liaison avec le nœud

def url_noeud():
    return (os.environ.get("G1_PILOTAGE_URL") or URL_DEFAUT).rstrip("/")


def jeton():
    """Jeton du nœud : $G1_PILOTAGE_JETON, sinon celui écrit par g1-jetson demarrer, sinon vide."""
    j = os.environ.get("G1_PILOTAGE_JETON")
    if j is not None:
        return j.strip()
    try:
        return FICHIER_JETON.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def noeud_local():
    """Vrai si le nœud est sur cette machine (l'Atelier peut alors le lancer lui-même)."""
    return (urlparse(url_noeud()).hostname or "") in ("127.0.0.1", "localhost", "::1")


def _entetes():
    j = jeton()
    return {D.ENTETE_JETON: j} if j else {}


def _injoignable(erreur=None):
    """503 en français : le pilotage ne répond pas ; l'adresse et l'erreur sont dans les détails (sortie)."""
    mode = "Avec le robot, il démarre avec le conteneur du Jetson : vérifiez-le (g1-jetson etat) et le Wi-Fi."
    if noeud_local():
        mode = "En répétition : « Démarrer », au début du ruban de Piloter."
    detail = f"adresse du pilotage : {url_noeud()}" + ("" if erreur is None else f" ; {str(erreur)[:250]}")
    return ErreurAtelier(503, f"Le pilotage ne répond pas : il n'est pas démarré ? {mode}", sortie=detail)


async def appeler_noeud(methode, chemin, corps=None, delai=DELAI_HTTP_S, params=None):
    """(statut, corps JSON) de l'API du nœud ; ErreurAtelier 503 s'il ne répond pas."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=delai) as client:
            r = await client.request(methode, url_noeud() + chemin, json=corps, headers=_entetes(),
                                     params=params)
    except httpx.HTTPError as e:
        raise _injoignable(e) from None
    try:
        donnees = r.json()
    except ValueError:
        donnees = {"detail": f"Réponse illisible du nœud pilotage (HTTP {r.status_code})."}
    if not isinstance(donnees, dict):
        donnees = {"detail": "Réponse inattendue du nœud pilotage.", "valeur": donnees}
    if r.status_code == 401:
        donnees["detail"] = ("Le nœud pilotage refuse le jeton de l'Atelier : donnez le même G1_PILOTAGE_JETON "
                             "au serveur de l'Atelier et au conteneur.")
    return r.status_code, donnees


def _reponse(statut, donnees):
    return JSONResponse(donnees, status_code=statut)


async def _corps(request: Request):
    texte = await request.body()
    if not texte:
        return {}
    try:
        d = json.loads(texte, parse_constant=_refuser_non_fini)
    except ValueError as e:
        raise ErreurAtelier(400, "Le corps de la demande n'est pas du JSON valable"
                                 + (" (NaN et Infinity sont interdits)." if "fini" in str(e) else ".")) from None
    if not isinstance(d, dict):
        raise ErreurAtelier(400, "Le corps de la demande doit être un objet JSON.")
    return d


def _refuser_non_fini(constante):
    raise ValueError(f"nombre non fini : {constante}")


def _etat(request):
    return request.app.state.atelier


# ---------------------------------------------------------------- configuration de l'onglet

@routeur.get("/api/pilotage/config")
def config(request: Request):
    """Valeurs du contrat dont l'onglet a besoin (rien n'est demandé au robot)."""
    etat = _etat(request)
    refus_vitesse = None
    try:
        limites = D.limites_marche(os.environ.get("G1_VITESSE_MAX") or None)
    except ValueError as e:
        # G1_VITESSE_MAX refusée (ex. sous 0,2 m/s) : le nœud pilotage refusera de démarrer
        limites, refus_vitesse = dict(D.LIMITES_MARCHE), f"G1_VITESSE_MAX : {e}"
    return {
        "url": url_noeud(), "jeton": bool(jeton()), "local": noeud_local(),
        "noeud_lance": etat.gestionnaire.en_cours("pilotage"), "mode": etat.mode_navigation(),
        "postures": [{"fsm": n, "nom": nom, "confirmation": D.confirmation_requise("sport", 7101, {"data": n})}
                     for n, nom in D.POSTURES.items()],
        "gestes": [{"id": n, "nom": nom} for n, nom in D.GESTES_BRAS.items()],
        "taches": [{"id": n, "nom": nom} for n, nom in D.TACHES_LOCO.items()],
        "danses_interdites": list(D.DANSES_INTERDITES),
        "danses_essayees": {str(n): t for n, t in D.DANSES_ESSAYEES.items()},
        "danses_non_essayees": {str(n): t for n, t in D.DANSES_NON_ESSAYEES.items()},
        "confirmations": dict(D.TEXTES_CONFIRMATION),
        "limites_marche": limites, "vitesse_max_refusee": refus_vitesse,
        "vitesses_min": dict(R.VITESSES_MIN_PONT), "modes_marche": list(D.MODES_MARCHE),
        "periode_joystick_s": D.PERIODE_JOYSTICK_S,
        "delai_homme_mort_s": D.DELAI_HOMME_MORT_S,
        "articulations": [{"nom": nom, "indice": i, "bas": D.LIMITES_BRAS[nom][0], "haut": D.LIMITES_BRAS[nom][1]}
                          for nom, i in D.ARTICULATIONS_BRAS.items()],
        "vitesse_bras_max": D.VITESSE_BRAS_MAX, "rampe_min_s": D.RAMPE_MIN_S,
        "frequence_bras_hz": D.FREQUENCE_BRAS_HZ, "limites_pas": dict(D.LIMITES_PAS),
        "duree_pas_s": list(D.DUREE_PAS_S), "deplacement_max_m": D.DEPLACEMENT_MAX_M,
        "rotation_max_rad": D.ROTATION_MAX_RAD, "zone_libre_min_m": D.ZONE_LIBRE_MIN_M,
        "exemple": EXEMPLE_PROTEGE,
    }


# ---------------------------------------------------------------- état, démarrage du nœud

@routeur.get("/api/pilotage/etat")
async def etat_pilotage():
    statut, donnees = await appeler_noeud("GET", "/etat", delai=3.0)
    donnees["url"] = url_noeud()
    return _reponse(statut, donnees)


def _port_du_noeud():
    port = urlparse(url_noeud()).port
    return port or D.PORT_PILOTAGE


@routeur.post("/api/pilotage/demarrer")
async def demarrer(request: Request):
    """Lance le nœud pilotage sur le PC (simulation, répétition) ; 409 avec le robot ou un nœud distant."""
    etat = _etat(request)
    if etat.mode_navigation() == "robot":
        raise ErreurAtelier(409, "Avec le robot, le nœud pilotage tourne dans le conteneur du Jetson "
                                 "(G1_PILOTAGE=1, lancé par g1-jetson demarrer) : rien à démarrer ici.")
    if not noeud_local():
        raise ErreurAtelier(409, f"Le nœud pilotage est attendu à {url_noeud()} (G1_PILOTAGE_URL), pas sur "
                                 "ce PC : l'Atelier ne peut pas le lancer.")
    try:
        statut, donnees = await appeler_noeud("GET", "/etat", delai=1.0)
        if statut == 200:
            return {"deja": True, "detail": "Le nœud pilotage tourne déjà.", "etat": donnees}
    except ErreurAtelier:
        pass
    from ..processus import CommandeAbsente
    arguments = ["noeud", "--port", str(_port_du_noeud()), "--hote", "127.0.0.1"]
    try:
        await run_in_threadpool(etat.gestionnaire.lancer, "pilotage", "g1-pilotage", arguments,
                                {"url": url_noeud()})
    except CommandeAbsente as e:
        raise ErreurAtelier(503, str(e)) from None
    fin = time.monotonic() + DELAI_DEMARRAGE_S
    derniere = None
    while time.monotonic() < fin:
        if not etat.gestionnaire.en_cours("pilotage"):
            lignes = etat.gestionnaire.etat().get("pilotage", {}).get("dernieres_lignes", [])
            raise ErreurAtelier(502, "Le nœud pilotage s'est arrêté au démarrage : voir son message.",
                                sortie="\n".join(lignes))
        try:
            statut, donnees = await appeler_noeud("GET", "/etat", delai=1.0)
            if statut == 200:
                return {"deja": False, "detail": "Nœud pilotage démarré.", "etat": donnees}
            derniere = donnees.get("detail")
        except ErreurAtelier as e:
            derniere = e.detail
        await asyncio.sleep(0.3)
    await run_in_threadpool(etat.gestionnaire.arreter, "pilotage")
    raise ErreurAtelier(504, f"Le pilotage ne répond pas après {DELAI_DEMARRAGE_S:g} s : {derniere}")


@routeur.post("/api/pilotage/arreter")
async def arreter(request: Request):
    etat = _etat(request)
    if not etat.gestionnaire.en_cours("pilotage"):
        return {"arrete": False, "detail": "Le nœud pilotage n'a pas été lancé par l'Atelier."}
    await run_in_threadpool(etat.gestionnaire.arreter, "pilotage")
    return {"arrete": True, "detail": "Nœud pilotage arrêté : StopMove envoyé, le guide a la main."}


# ---------------------------------------------------------------- commandes relayées

def _relais(nom):
    async def relayer(request: Request):
        corps = await _corps(request)
        statut, donnees = await appeler_noeud("POST", f"/{nom}", corps)
        return _reponse(statut, donnees)
    relayer.__name__ = f"relayer_{nom}"
    relayer.__doc__ = f"Relaie POST /{nom} au nœud pilotage (règles et réponse du nœud)."
    return relayer


for _nom in RELAIS:
    routeur.add_api_route(f"/api/pilotage/{_nom}", _relais(_nom), methods=["POST"])


@routeur.post("/api/pilotage/arret")
async def arret(request: Request):
    """ARRÊT, toujours permis. Nœud injoignable : /guide/stop quand même, et 503 qui le dit."""
    try:
        statut, donnees = await appeler_noeud("POST", "/arret", {"par": "atelier"}, delai=3.0)
        return _reponse(statut, donnees)
    except ErreurAtelier as e:
        etat = _etat(request)
        envoye = False
        if etat.pont.actif:
            try:
                etat.pont.stop()
                envoye = True
            except RuntimeError:
                pass
        suite = (" L'arrêt a été envoyé au guide." if envoye else "")
        raise ErreurAtelier(503, "ARRÊT : le pilotage ne répond pas." + suite
                            + " Utilisez la télécommande pour arrêter le robot.", sortie=e.sortie) from None


@routeur.get("/api/pilotage/danses")
async def danses(lire: int = 0):
    statut, donnees = await appeler_noeud("GET", "/danses", params={"lire": str(int(bool(lire)))})
    return _reponse(statut, donnees)


@routeur.get("/api/pilotage/gestes")
async def gestes(lire: int = 0):
    try:
        statut, donnees = await appeler_noeud("GET", "/gestes", params={"lire": str(int(bool(lire)))})
        return _reponse(statut, donnees)
    except ErreurAtelier:
        return {"gestes": [{"id": n, "nom": nom} for n, nom in D.GESTES_BRAS.items()],
                "taches": [{"id": n, "nom": nom} for n, nom in D.TACHES_LOCO.items()], "robot": None,
                "detail": "Nœud pilotage injoignable : liste du contrat."}


# ---------------------------------------------------------------- chorégraphies

def dossier_choregraphies():
    return Path(os.environ.get("ATELIER_CHOREGRAPHIES") or D.DOSSIER_CHOREGRAPHIES).expanduser()


def _id_choregraphie(ident):
    if not isinstance(ident, str) or not atelier.MOTIF_ID.match(ident):
        raise ErreurAtelier(400, f"« {ident} » n'est pas un nom de chorégraphie valable : de 1 à 40 lettres "
                                 "minuscules sans accent, chiffres, « _ » ou « - » (ex. ma_danse).")
    return ident


def _avertissements(d, erreurs):
    """Avertissements d'une chorégraphie sans erreur (pas sous la vitesse minimale du vrai robot)."""
    if erreurs:
        return []
    try:
        limites = D.limites_marche(os.environ.get("G1_VITESSE_MAX") or None)
    except ValueError:
        limites = None
    try:
        return D.avertissements_choregraphie(d, limites)
    except (KeyError, TypeError, ValueError):
        return []


def _lire_choregraphie(ident):
    """(contenu, erreurs) d'un fichier ; 404 s'il n'existe pas ; 422 s'il n'est pas du YAML lisible."""
    chemin = D.chemin_choregraphie(_id_choregraphie(ident), dossier_choregraphies())
    if not chemin.is_file():
        raise ErreurAtelier(404, f"La chorégraphie « {ident} » n'existe pas.")
    try:
        contenu = lire_yaml(chemin.read_text(encoding="utf-8"), chemin.name)
    except ErreurLieu as e:
        raise ErreurAtelier(422, f"Le fichier {chemin.name} est illisible.", e.erreurs) from None
    if not isinstance(contenu, dict):
        raise ErreurAtelier(422, f"Le fichier {chemin.name} ne contient pas une chorégraphie.")
    return contenu, D.verifier_choregraphie(contenu)


def resume_choregraphie(d):
    """Mesures utiles à l'onglet : déplacement, rotation, vitesse des bras au plus fort."""
    try:
        distance, rotation = D.deplacement_pas(d)
    except (KeyError, TypeError, ValueError):
        distance = rotation = None
    vitesse = None
    try:
        bras = d.get("bras") or {}
        facteur = math.pi / 2 if bras.get("interpolation", "douce") == "douce" else 1.0
        for t0, q0, t1, q1 in D.segments_bras(d):
            if t1 > t0:
                for nom in D.ARTICULATIONS_BRAS:
                    v = facteur * abs(q1[nom] - q0[nom]) / (t1 - t0)
                    vitesse = v if vitesse is None else max(vitesse, v)
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        vitesse = None
    return {"deplacement_m": None if distance is None else round(distance, 3),
            "rotation_rad": None if rotation is None else round(rotation, 3),
            "vitesse_bras_max": None if vitesse is None else round(vitesse, 3)}


@routeur.get("/api/pilotage/choregraphies")
def lister():
    sortie = []
    for chemin in D.lister_choregraphies(dossier_choregraphies()):
        ident = chemin.name[: -len(D.SUFFIXE_CHOREGRAPHIE)]
        try:
            contenu, erreurs = _lire_choregraphie(ident)
        except ErreurAtelier as e:
            sortie.append({"id": ident, "nom": ident, "duree_s": None, "erreurs": [e.detail, *e.erreurs]})
            continue
        sortie.append({"id": ident, "nom": contenu.get("nom", ident), "duree_s": contenu.get("duree_s"),
                       "erreurs": erreurs, "avertissements": _avertissements(contenu, erreurs),
                       "protegee": ident == EXEMPLE_PROTEGE})
    return {"dossier": str(dossier_choregraphies()), "choregraphies": sortie}


@routeur.get("/api/pilotage/choregraphies/{ident}")
def lire(ident: str):
    contenu, erreurs = _lire_choregraphie(ident)
    return {"choregraphie": contenu, "erreurs": erreurs, "avertissements": _avertissements(contenu, erreurs),
            "resume": resume_choregraphie(contenu), "protegee": ident == EXEMPLE_PROTEGE}


@routeur.post("/api/pilotage/choregraphies/verifier")
async def verifier(request: Request):
    corps = await _corps(request)
    d = corps.get("choregraphie")
    if not isinstance(d, dict):
        raise ErreurAtelier(400, "« choregraphie » : le contenu de la chorégraphie (objet JSON).")
    erreurs = D.verifier_choregraphie(d)
    return {"erreurs": erreurs, "sure": not erreurs, "avertissements": _avertissements(d, erreurs),
            "resume": resume_choregraphie(d)}


def _ecrire_yaml(chemin, contenu):
    import yaml
    texte = ("# Chorégraphie du G1 (Atelier G1, onglet Pilotage). Format : "
             "atelier/lieu/schemas/choregraphie.schema.json\n"
             + yaml.safe_dump(contenu, allow_unicode=True, sort_keys=False, default_flow_style=None, width=110))
    temporaire = chemin.with_name(f".{chemin.name}.tmp")
    temporaire.write_text(texte, encoding="utf-8")
    os.replace(temporaire, chemin)


@routeur.put("/api/pilotage/choregraphies/{ident}")
async def ecrire(ident: str, request: Request):
    _id_choregraphie(ident)
    if ident == EXEMPLE_PROTEGE:
        raise ErreurAtelier(409, "L'exemple K-pop du dépôt est en lecture seule : enregistrez-le sous un autre "
                                 "nom (« Enregistrer sous »).")
    corps = await _corps(request)
    d = corps.get("choregraphie", corps)
    if not isinstance(d, dict):
        raise ErreurAtelier(400, "Il faut le contenu de la chorégraphie (objet JSON).")
    d = dict(d, id=ident)
    erreurs = D.verifier_choregraphie(d)
    if erreurs:
        raise ErreurAtelier(422, f"La chorégraphie « {ident} » n'a pas été enregistrée : corrigez les points "
                                 "ci-dessous.", erreurs)
    dossier = dossier_choregraphies()
    dossier.mkdir(parents=True, exist_ok=True)
    chemin = D.chemin_choregraphie(ident, dossier)
    await run_in_threadpool(_ecrire_yaml, chemin, d)
    return {"enregistre": [str(chemin)], "choregraphie": d, "avertissements": _avertissements(d, []),
            "resume": resume_choregraphie(d)}


@routeur.delete("/api/pilotage/choregraphies/{ident}")
def supprimer(ident: str):
    _id_choregraphie(ident)
    if ident == EXEMPLE_PROTEGE:
        raise ErreurAtelier(409, "L'exemple K-pop du dépôt ne se supprime pas depuis l'Atelier.")
    chemin = D.chemin_choregraphie(ident, dossier_choregraphies())
    if not chemin.is_file():
        raise ErreurAtelier(404, f"La chorégraphie « {ident} » n'existe pas.")
    chemin.unlink()
    return {"supprime": str(chemin)}


@routeur.post("/api/pilotage/choregraphies/{ident}/jouer")
async def jouer(ident: str, request: Request):
    """Vérifie la chorégraphie, puis l'envoie au nœud, qui la vérifie encore et la joue."""
    corps = await _corps(request)
    contenu, erreurs = _lire_choregraphie(ident)
    if erreurs:
        raise ErreurAtelier(422, f"Chorégraphie « {ident} » refusée avant de jouer : corrigez les points "
                                 "ci-dessous.", erreurs)
    zone_libre = corps.get("zone_libre", False)
    if not isinstance(zone_libre, bool):
        raise ErreurAtelier(400, "« zone_libre » doit valoir true ou false.")
    vitesse = corps.get("vitesse", 1.0)
    if isinstance(vitesse, bool) or not isinstance(vitesse, (int, float)) or not 0.25 <= vitesse <= 1.0:
        raise ErreurAtelier(400, "« vitesse » : la vitesse de lecture, de 0,25 (quatre fois plus lent) à 1 "
                                 "(comme prévu), jamais plus vite.")
    statut, donnees = await appeler_noeud("POST", "/choregraphie",
                                          {"choregraphie": contenu, "zone_libre": zone_libre, "vitesse": vitesse})
    return _reponse(statut, donnees)


@routeur.get("/api/pilotage/musique/{fichier}")
def musique(fichier: str):
    if not MOTIF_MUSIQUE.match(fichier) or fichier.startswith("."):
        raise ErreurAtelier(400, f"« {fichier} » n'est pas un nom de musique valable (.mp3, .ogg ou .wav).")
    dossier = dossier_choregraphies() / "musique"
    chemin = dossier / fichier
    if not chemin.is_file():
        raise ErreurAtelier(404, f"Musique « {fichier} » introuvable : copiez-la dans {dossier} "
                                 "(ce dossier n'est jamais dans Git).")
    return FileResponse(chemin, media_type=TYPES_MUSIQUE[fichier.rsplit(".", 1)[1]])


# ---------------------------------------------------------------- le G1 pour l'aperçu 3D

def _nombres(texte, n=3):
    try:
        valeurs = [float(v) for v in (texte or "").split()]
    except ValueError:
        valeurs = []
    return valeurs if len(valeurs) == n else [0.0] * n


@lru_cache(maxsize=2)
def modele_g1(chemin_urdf=str(URDF_G1)):
    """Le G1 de l'URDF g1_29dof_rev_1_0 : liens (maillages, couleurs) et articulations, en JSON."""
    racine = ET.parse(chemin_urdf).getroot()
    liens = {}
    for lien in racine.findall("link"):
        visuels = []
        for v in lien.findall("visual"):
            maillage = v.find("geometry/mesh")
            if maillage is None:
                continue
            origine = v.find("origin")
            couleur = v.find("material/color")
            visuels.append({"maillage": Path(maillage.get("filename", "")).name,
                            "xyz": _nombres(None if origine is None else origine.get("xyz")),
                            "rpy": _nombres(None if origine is None else origine.get("rpy")),
                            "couleur": _nombres(None if couleur is None else couleur.get("rgba"), 4)})
        liens[lien.get("name")] = visuels
    articulations = []
    enfants = set()
    for a in racine.findall("joint"):
        origine = a.find("origin")
        axe = a.find("axis")
        limite = a.find("limit")
        enfant = a.find("child").get("link")
        enfants.add(enfant)
        articulations.append({
            "nom": a.get("name"), "type": a.get("type"), "parent": a.find("parent").get("link"),
            "enfant": enfant, "xyz": _nombres(None if origine is None else origine.get("xyz")),
            "rpy": _nombres(None if origine is None else origine.get("rpy")),
            "axe": _nombres(None if axe is None else axe.get("xyz")) if axe is not None else [1.0, 0.0, 0.0],
            "bas": None if limite is None else float(limite.get("lower", 0)),
            "haut": None if limite is None else float(limite.get("upper", 0))})
    base = next((nom for nom in liens if nom not in enfants), "pelvis")
    return {"nom": racine.get("name"), "racine": base, "liens": liens, "articulations": articulations}


def dossier_maillages():
    for dossier in MAILLAGES_G1:
        if (dossier / "pelvis.STL").is_file():
            return dossier
    return None


@routeur.get("/api/pilotage/modele")
def modele():
    if not URDF_G1.is_file():
        raise ErreurAtelier(404, "Le modèle du G1 (third_party/unitree_rl_gym, URDF g1_29dof_rev_1_0) est absent : "
                                 "l'aperçu montre un G1 simplifié. Relancez setup/installer_utilisateur.sh.")
    m = dict(modele_g1())
    m["maillages"] = dossier_maillages() is not None
    return m


@routeur.get("/api/pilotage/modele/maillages/{nom}")
def maillage(nom: str):
    if not MOTIF_MAILLAGE.match(nom):
        raise ErreurAtelier(400, f"« {nom} » n'est pas un nom de maillage valable.")
    dossier = dossier_maillages()
    chemin = None if dossier is None else dossier / nom
    if chemin is None or not chemin.is_file():
        raise ErreurAtelier(404, f"Maillage « {nom} » introuvable.")
    return FileResponse(chemin, media_type="model/stl", headers={"Cache-Control": "max-age=86400"})


# ---------------------------------------------------------------- caméra de la tête (Vue du robot)

class CacheCamera:
    """Une seule demande d'image à la fois vers le nœud, partagée par toutes les pages (section 11.13)."""

    PARTAGE_S = 0.15                 # une image de moins de ce temps sert à toutes les pages

    def __init__(self):
        self.boucle = None
        self.verrou = None
        self.t = 0.0
        self.reponse = None          # (statut, octets, type, en-têtes)

    def _verrou(self):
        boucle = asyncio.get_running_loop()
        if self.boucle is not boucle:            # nouvelle boucle (tests) : nouveau verrou
            self.boucle, self.verrou = boucle, asyncio.Lock()
        return self.verrou

    async def lire(self):
        async with self._verrou():
            if self.reponse is not None and time.monotonic() - self.t < self.PARTAGE_S:
                return self.reponse
            self.reponse = await _demander_image()
            self.t = time.monotonic()
            return self.reponse


async def _demander_image():
    import httpx
    try:
        async with httpx.AsyncClient(timeout=D.CAMERA_DELAI_S + 2.0) as client:
            r = await client.get(url_noeud() + "/camera", headers=_entetes())
    except httpx.HTTPError as e:
        erreur = _injoignable(e)
        return 503, json.dumps({"detail": erreur.detail}).encode(), "application/json", {}
    if r.status_code == 404:
        detail = ("Le nœud pilotage ne connaît pas encore la caméra : arrêtez-le et redémarrez-le "
                  "(« Démarrer le pilotage », ou avec le robot : g1-jetson demarrer après la nouvelle image).")
        return 503, json.dumps({"detail": detail}).encode(), "application/json", {}
    entetes = {k: v for k, v in r.headers.items() if k.lower() in ("x-image-age-s", "x-image-numero")}
    return r.status_code, r.content, r.headers.get("content-type", "application/octet-stream"), entetes


CACHE_CAMERA = CacheCamera()


@routeur.get("/api/pilotage/camera")
async def camera():
    """Dernière image JPEG de la caméra de la tête, demandée au nœud pilotage (lecture seule)."""
    statut, contenu, genre, entetes = await CACHE_CAMERA.lire()
    entetes = dict(entetes, **{"Cache-Control": "no-store"})
    return Response(content=contenu, status_code=statut, media_type=genre.split(";")[0], headers=entetes)


# ---------------------------------------------------------------- joystick : WebSocket relayé

@routeur.websocket("/ws/pilotage")
async def ws_pilotage(ws: WebSocket):
    """Relais du joystick : page ↔ Atelier ↔ nœud. Une coupure d'un côté ferme l'autre (le nœud arrête
    alors le robot : StopMove). L'Atelier n'envoie jamais d'ordre de lui-même."""
    import websockets
    await ws.accept()
    url = "ws" + url_noeud()[len("http"):] + "/joystick"
    try:
        noeud = await websockets.connect(url, additional_headers=_entetes(), open_timeout=3.0,
                                         ping_interval=1.0, ping_timeout=3.0, close_timeout=1.0)
    except Exception as e:      # noqa: BLE001 : refus, port fermé, jeton… : on le dit à la page
        erreur = _injoignable(e)
        await _envoyer(ws, {"type": "refus", "detail": erreur.detail})
        await ws.close(code=1011)
        return

    async def vers_noeud():
        try:
            while True:
                message = await ws.receive_text()
                await noeud.send(message)
        except (WebSocketDisconnect, RuntimeError):
            pass

    async def vers_page():
        try:
            async for message in noeud:
                await ws.send_text(message if isinstance(message, str) else message.decode("utf-8", "replace"))
        except Exception:       # noqa: BLE001 : le nœud a coupé
            pass
        await _envoyer(ws, {"type": "refus", "detail": "Liaison avec le nœud pilotage coupée : robot arrêté."})

    taches = [asyncio.ensure_future(vers_noeud()), asyncio.ensure_future(vers_page())]
    try:
        await asyncio.wait(taches, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in taches:
            t.cancel()
        try:
            await noeud.close()             # le nœud envoie StopMove à la fermeture
        except Exception:       # noqa: BLE001
            pass
        try:
            await ws.close()
        except RuntimeError:
            pass


async def _envoyer(ws, message):
    try:
        await ws.send_text(json.dumps(message, ensure_ascii=False))
    except (RuntimeError, WebSocketDisconnect):
        pass
