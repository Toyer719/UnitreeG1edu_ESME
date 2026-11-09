"""La borne visiteur (vague 6, section 13.5 du plan) : agent Borne et orchestrateur.

  GET  /borne                            la page de la borne (atelier/web/borne.html), pour une tablette ou un
                                         téléphone du même réseau (g1-atelier --hote 0.0.0.0)
  GET  /api/borne/etat                   ce que la borne montre : schéma etat_borne
  WS   /ws/borne[?jeton=…]               le même, 4 fois par seconde (jeton : le mode opérateur de ce client)
  POST /api/borne/appui                  le visiteur touche l'écran : /accueil/commande appui ; 200 {accepte},
                                         409 (occupé, pause, démo arrêtée)
  POST /api/borne/choisir {salle}        /accueil/choix (source borne), puis la réponse de la démo
                                         (/accueil/evenement, 2 s au plus) : 200 {accepte, visite} ; 409 (occupé,
                                         pause, démo arrêtée) ; 404 (salle inconnue) ; 422 (salle cachée, autre
                                         étage, l'accueil lui-même)
  POST /api/borne/annuler                retour à l'écran des salles (/accueil/commande annuler)
  POST /api/borne/operateur {code}       code opérateur (demo.yaml) : {jeton, expire_s} ; 403 mauvais code ; 409
                                         pas de code réglé ; 429 trop d'essais (5 par 5 min)
  POST /api/borne/operateur/{action}     pause, reprendre ou ramener, avec l'en-tête X-Jeton-Borne : {accepte,
                                         texte} ; 401 sans jeton valable ; 404 autre action
  GET  /api/borne/adresse                pour l'Atelier : {adresses: [http://IP:port/borne…], ecoute_reseau, port,
                                         locale, message} (« relancez avec g1-atelier --hote 0.0.0.0 » sinon)

Anti-rebond (ANTI_REBOND_S, 0,6 s) : deux appuis, deux choix ou deux annulations du même client à moins de
0,6 s comptent pour un (la réponse du premier est rendue, avec rebond: true) ; une demande pareille qui arrive
pendant que la première attend encore la démo l'attend aussi et rend sa réponse (Borne.reserver : cinq choix
envoyés ensemble ne publient qu'un /accueil/choix). Depuis la borne (un client qui
n'est pas ce PC), seules ces pages et ces routes sont permises (garde de main.py, chemin_permis_borne) : rien
d'autre, ni l'ARRÊT contourné, ni les réglages.
"""
import asyncio
import hmac
import os
import secrets
import socket
import threading
import time
from pathlib import Path

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

import atelier
from atelier.lieu import ErreurLieu, charger_fiche, charger_salles
from atelier.lieu import accueil as A

from ..communs import ErreurAtelier, dossier_du_lieu
from .demo import (MESSAGE_DEMO_ARRETEE, STATUT_REFUS, envoyer_et_attendre, etat_demo_frais, exiger_demo,
                   lieu_de_la_demo, nouvel_id, resultat_commande)

routeur = APIRouter(tags=["borne"])

PAGE_BORNE = Path(__file__).resolve().parents[2] / "web" / "borne.html"
PERIODE_WS_S = 0.25           # 4 fois par seconde
SON_FRAIS_S = 15.0            # une phrase plus vieille n'est plus jouée par une borne qui arrive
HOTES_TOUS = ("0.0.0.0", "::", "")
PREFIXES_IGNORES = ("lo", "docker", "br-", "veth", "virbr", "tun", "tap", "wg", "zt")
TEXTES_EN = {
    "hors_service": "The robot is getting ready. Please come back in a moment!",
    "salles": "Hello! Where would you like to go?",
    "suivez_moi": "Follow me!",
    "arrivee": "Here we are.",
    "retour": "I'm going back to the reception.",
    "occupe": "I'm busy. I'll be back in a moment!",
    "pause": "I'm taking a short break.",
}
DETAILS = {
    "fr": {"hors_service": "La visite guidée reprend bientôt.", "salles": "Touchez une salle : je vous y accompagne.",
           "en_route": "En route vers « {nom} ».", "reste": "Encore {d} m jusqu'à « {nom} ».",
           "arrivee": "Voici « {nom} ».",
           "retour": "À tout à l'heure !", "occupe": "Merci de patienter un peu.",
           "pause": "Un membre de l'équipe va s'occuper de moi."},
    "en": {"hors_service": "The guided tour starts again soon.", "salles": "Touch a room: I will take you there.",
           "en_route": "On our way to {nom}.", "reste": "{d} m left to {nom}.", "arrivee": "This is {nom}.",
           "retour": "See you soon!", "occupe": "Thank you for waiting a little.",
           "pause": "A member of the team will take care of me."},
}


class DemandeChoix(BaseModel):
    salle: str


class DemandeCode(BaseModel):
    code: str


MESSAGE_SANS_REPONSE_BORNE = "Le robot n'a pas répondu : réessayez dans un instant."


class Borne:
    """Ce que le serveur retient pour les bornes : jetons opérateur, essais de code, anti-rebond, fichiers lus."""

    def __init__(self, horloge=time.monotonic):
        self.horloge = horloge
        self.verrou = threading.Lock()
        self.jetons = {}          # jeton → (client, fin de validité)
        self.echecs = {}          # client → [instants des mauvais codes]
        self.reponses = {}        # (client, route) → (instant, statut, corps)
        self.en_cours = {}        # (client, route) → futur de la première demande qui attend la démo
        self.fichiers = {}        # dossier → (dates des fichiers, données lues)

    # ------------------------------------------------------------ anti-rebond

    def _retenir(self, client, route, statut, corps):
        self.reponses[(client, route)] = (self.horloge(), statut, corps)
        if len(self.reponses) > 500:
            self.reponses = dict(list(self.reponses.items())[-200:])

    def reserver(self, client, route):
        """L'anti-rebond, aussi pour des demandes simultanées (corrections de la vague 6, revue du code, défaut 4 : la
        réponse n'était retenue qu'après l'attente de la démo, jusqu'à 2 s, et cinq choix envoyés ensemble partaient
        tous). Rend ("reponse", (statut, corps)) si le même client a eu sa réponse il y a moins de ANTI_REBOND_S,
        ("attendre", futur) si sa première demande attend encore la démo (le futur rend (statut, corps, erreur)),
        sinon ("premier", futur) : la clé est prise jusqu'à finir(). Dans la boucle asyncio du serveur."""
        with self.verrou:
            deja = self.reponses.get((client, route))
            if deja is not None and self.horloge() - deja[0] < A.ANTI_REBOND_S:
                return "reponse", (deja[1], dict(deja[2], rebond=True))
            futur = self.en_cours.get((client, route))
            if futur is not None and not futur.done():
                return "attendre", futur
            futur = asyncio.get_running_loop().create_future()
            self.en_cours[(client, route)] = futur
            return "premier", futur

    def finir(self, client, route, futur, statut=None, corps=None, erreur=None):
        """La première demande a sa réponse (retenue pour l'anti-rebond) ou son erreur : les demandes pareilles qui
        l'attendaient la reçoivent, et la clé est libérée."""
        with self.verrou:
            if statut is not None:
                self._retenir(client, route, statut, corps)
            if self.en_cours.get((client, route)) is futur:
                del self.en_cours[(client, route)]
        if not futur.done():
            futur.set_result((statut, corps, erreur))

    # ------------------------------------------------------------ code opérateur

    def essais_bloques(self, client):
        """Secondes à attendre si ce client a donné ESSAIS_CODE_MAX mauvais codes en DUREE_BLOCAGE_CODE_S."""
        t = self.horloge()
        with self.verrou:
            recents = [x for x in self.echecs.get(client, []) if t - x < A.DUREE_BLOCAGE_CODE_S]
            self.echecs[client] = recents
        if len(recents) >= A.ESSAIS_CODE_MAX:
            return max(1, int(A.DUREE_BLOCAGE_CODE_S - (t - recents[0])))
        return 0

    def noter_echec(self, client):
        with self.verrou:
            self.echecs.setdefault(client, []).append(self.horloge())

    def nouveau_jeton(self, client):
        jeton = secrets.token_urlsafe(18)
        with self.verrou:
            t = self.horloge()
            self.jetons = {j: v for j, v in self.jetons.items() if v[1] > t}
            self.jetons[jeton] = (client, t + A.DUREE_JETON_OPERATEUR_S)
            self.echecs.pop(client, None)
        return jeton

    def jeton_valable(self, jeton, client):
        if not jeton:
            return False
        with self.verrou:
            v = self.jetons.get(jeton)
        return v is not None and v[0] == client and v[1] > self.horloge()

    # ------------------------------------------------------------ fichiers du lieu, relus s'ils changent

    def donnees_lieu(self, dossier):
        """{nom, salles, principal, noms_etages, reglages} du lieu, relu quand un de ses fichiers change."""
        dates = tuple((dossier / f).stat().st_mtime_ns if (dossier / f).exists() else None
                      for f in ("lieu.yaml", "salles.yaml", A.FICHIER_DEMO))
        with self.verrou:
            connu = self.fichiers.get(str(dossier))
        if connu is not None and connu[0] == dates:
            return connu[1]
        from atelier.lieu.principal import point_principal
        fiche = charger_fiche(dossier)
        salles = charger_salles(dossier)
        principal = point_principal(dossier)
        donnees = {"nom": fiche.nom, "salles": salles, "principal": principal.id if principal else None,
                   "etage_principal": principal.etage if principal else None,
                   "noms_etages": {e.id: e.nom for e in fiche.etages}, "reglages": A.reglages_demo(dossier)}
        with self.verrou:
            self.fichiers[str(dossier)] = (dates, donnees)
        return donnees


def _borne(request_ou_ws):
    app = request_ou_ws.app
    b = getattr(app.state, "borne", None)
    if b is None:
        b = app.state.borne = Borne()
    return b


def _client(request_ou_ws):
    c = request_ou_ws.client
    return c.host if c is not None else "inconnu"


def _etat(request_ou_ws):
    return request_ou_ws.app.state.atelier


# ---------------------------------------------------------------- l'état montré par la borne

def _langue(reglages):
    langue = ((reglages or {}).get("borne") or {}).get("langue") or "fr"
    return langue if langue in DETAILS else "fr"


def _texte(ecran, reglages, langue):
    titre = ((reglages or {}).get("borne") or {}).get("titre")
    if ecran == "salles" and titre and (langue == "fr" or titre != A.TEXTES_BORNE["salles"]):
        return titre
    return TEXTES_EN[ecran] if langue == "en" else A.TEXTES_BORNE[ecran]


def _detail(ecran, visite, langue):
    d = DETAILS[langue]
    nom = (visite or {}).get("nom") or (visite or {}).get("salle") or ""
    if ecran == "suivez_moi":
        reste = (visite or {}).get("reste_m")
        if isinstance(reste, (int, float)) and reste > 0.5 and nom:
            return d["reste"].replace("{d}", f"{reste:.0f}").replace("{nom}", nom)
        return d["en_route"].replace("{nom}", nom) if nom else None
    if ecran == "arrivee":
        return d["arrivee"].replace("{nom}", nom) if nom else None
    return d.get(ecran)


def _son(etat):
    if not etat.pont.actif:
        return None
    sons = etat.pont.historique("/voix/son")
    if not sons:
        return None
    s = sons[-1]
    if s.get("age_recu_s", SON_FRAIS_S + 1) > SON_FRAIS_S or not isinstance(s.get("id"), str):
        return None
    return {"id": s["id"], "texte": str(s.get("texte") or "")[:500], "duree_s": s.get("duree_s") or 0.0,
            "url": f"/api/voix/son/{s['id']}"}


def etat_de_la_borne(etat, borne, client=None, jeton=None):
    """Le message etat_borne : l'écran, ses textes, les salles de la borne, la visite, le son, l'opérateur."""
    demo = etat_demo_frais(etat)
    lieu_id, etage = lieu_de_la_demo(etat)
    donnees = None
    if lieu_id:
        try:
            donnees = borne.donnees_lieu(dossier_du_lieu(lieu_id))
        except (ErreurAtelier, ErreurLieu, OSError):
            donnees = None
    reglages = donnees["reglages"] if donnees else None
    langue = _langue(reglages)
    ecran = A.ecran_borne(demo)
    visite = None
    if demo is not None and isinstance(demo.get("visite"), dict):
        v = demo["visite"]
        visite = {"salle": v.get("salle"), "nom": v.get("nom") or v.get("salle"), "reste_m": v.get("reste_m")}
    salles = []
    if donnees:
        etage = etage or donnees["etage_principal"]
        salles = A.salles_de_la_borne(donnees["salles"], donnees["principal"], etage, donnees["noms_etages"])[:60]
    code = ((reglages or {}).get("borne") or {}).get("code_operateur")
    actif = borne.jeton_valable(jeton, client)
    plus = {}
    if actif:
        # le mode opérateur (ce client a le code) : où en est la démo, et ce que l'opérateur peut faire
        actions = (demo or {}).get("actions_possibles") or []
        plus["mode_operateur"] = {"message": (demo or {}).get("message") or MESSAGE_DEMO_ARRETEE,
                                  "actions": [a for a in A.ACTIONS_OPERATEUR_BORNE if a in actions]}
    return {
        **plus,
        "version": 1, "ecran": ecran, "texte": _texte(ecran, reglages, langue),
        "detail": _detail(ecran, visite, langue),
        "lieu": {"id": lieu_id, "nom": donnees["nom"]} if donnees else None,
        "salles": salles, "visite": visite if visite and visite.get("salle") else None,
        "demo": None if demo is None else {"etat": demo["etat"], "depuis_s": demo.get("depuis_s", 0.0),
                                           "age_s": demo.get("age_recu_s", 0.0)},
        "son": _son(etat),
        "operateur": {"possible": bool(code), "actif": actif},
        "langue": langue, "temps": A.maintenant_iso(),
    }


# ---------------------------------------------------------------- l'adresse de la borne (pour l'Atelier)

def _adresses_du_pc():
    """Adresses IPv4 du PC sur ses réseaux locaux (Wi-Fi d'abord), sans la boucle, Docker ni le câble du robot."""
    from .liaison import adresse_ipv4, interface_du_robot
    robot = interface_du_robot()
    trouvees = []
    try:
        interfaces = [nom for _, nom in socket.if_nameindex()]
    except OSError:
        interfaces = []
    for nom in interfaces:
        if nom == robot or nom.startswith(PREFIXES_IGNORES):
            continue
        ip = adresse_ipv4(nom)
        if not ip or ip.startswith(("127.", "169.254.", "192.168.123.")):
            continue
        trouvees.append((0 if nom.startswith("wl") else 1, nom, ip))
    return [ip for _, _, ip in sorted(trouvees)]


def adresses_borne(request):
    """{adresses, ecoute_reseau, port, locale, message} : où ouvrir la borne depuis une tablette."""
    hote = os.environ.get("ATELIER_HOTE") or "127.0.0.1"
    port = os.environ.get("ATELIER_PORT") or str(request.url.port or 8000)
    locale = f"http://127.0.0.1:{port}/borne"
    from ..main import client_local
    if client_local(hote):
        return {"adresses": [], "ecoute_reseau": False, "port": int(port), "locale": locale,
                "message": ("L'Atelier n'écoute que ce PC : pour une tablette ou un téléphone, relancez l'Atelier "
                            "avec g1-atelier --hote 0.0.0.0 (même réseau Wi-Fi que le PC).")}
    ips = _adresses_du_pc() if hote in HOTES_TOUS else [hote]
    adresses = [f"http://{ip}:{port}/borne" for ip in ips]
    message = ("Ouvrez cette adresse sur la tablette ou le téléphone, connecté au même réseau Wi-Fi que le PC."
               if adresses else "Le PC n'a pas d'adresse sur un réseau local : connectez-le au Wi-Fi.")
    return {"adresses": adresses, "ecoute_reseau": True, "port": int(port), "locale": locale, "message": message}


# ---------------------------------------------------------------- routes

@routeur.get("/borne", include_in_schema=False)
@routeur.get("/borne/", include_in_schema=False)
def page_borne():
    if not PAGE_BORNE.is_file():
        raise ErreurAtelier(404, "La page de la borne n'est pas encore installée (atelier/web/borne.html).")
    return FileResponse(PAGE_BORNE, media_type="text/html")


@routeur.get("/api/borne/etat")
def etat_borne(request: Request):
    return etat_de_la_borne(_etat(request), _borne(request), _client(request),
                            request.headers.get(A.ENTETE_JETON_BORNE))


@routeur.websocket("/ws/borne")
async def direct_borne(ws: WebSocket):
    await ws.accept()
    jeton = ws.query_params.get("jeton")
    client = _client(ws)
    try:
        while True:
            await ws.send_json(etat_de_la_borne(_etat(ws), _borne(ws), client, jeton))
            await asyncio.sleep(PERIODE_WS_S)
    except (WebSocketDisconnect, RuntimeError, ConnectionError):
        pass        # la page a été fermée


def _refus(reponse, defaut="Refusé."):
    """(statut, corps) d'un refus de la démo (événement choix_refuse ou commande_refusee)."""
    raison = reponse.get("raison")
    return STATUT_REFUS.get(raison, 409), {"detail": reponse.get("texte") or defaut, "accepte": False,
                                           "raison": raison}


async def _une_fois(request, route, faire):
    """Fait faire() (une coroutine qui rend (statut, corps)) une seule fois pour les demandes pareilles du même
    client (Borne.reserver) : une demande qui arrive pendant l'attente de la première, ou moins de ANTI_REBOND_S
    après sa réponse, rend la même réponse avec rebond: true (ou la même erreur)."""
    borne, client = _borne(request), _client(request)
    genre, valeur = borne.reserver(client, route)
    if genre == "reponse":
        return JSONResponse(valeur[1], status_code=valeur[0])
    if genre == "attendre":
        statut, corps, erreur = await valeur
        if erreur is not None:
            raise ErreurAtelier(erreur.statut, erreur.detail)
        return JSONResponse(dict(corps, rebond=True), status_code=statut)
    futur = valeur
    try:
        statut, corps = await faire()
    except ErreurAtelier as e:
        borne.finir(client, route, futur, erreur=e)
        raise
    except BaseException:
        borne.finir(client, route, futur, erreur=ErreurAtelier(503, MESSAGE_SANS_REPONSE_BORNE))
        raise
    borne.finir(client, route, futur, statut, corps)
    return JSONResponse(corps, status_code=statut)


async def _commande_borne(request, action, route):
    etat = _etat(request)

    async def faire():
        try:
            exiger_demo(etat)
        except ErreurAtelier as e:
            return e.statut, {"detail": e.detail, "accepte": False, "raison": "demo_arretee"}
        message = A.message_commande(action, "borne", nouvel_id(f"borne-{action}"))
        reponse = await envoyer_et_attendre(etat, "/accueil/commande", message)
        if reponse is None:
            raise ErreurAtelier(503, MESSAGE_SANS_REPONSE_BORNE)
        if reponse.get("code") == "commande_acceptee":
            return 200, {"accepte": True, "texte": reponse.get("texte")}
        return _refus(reponse)
    return await _une_fois(request, route, faire)


@routeur.post("/api/borne/appui")
async def appui(request: Request):
    return await _commande_borne(request, "appui", "appui")


@routeur.post("/api/borne/annuler")
async def annuler(request: Request):
    return await _commande_borne(request, "annuler", "annuler")


@routeur.post("/api/borne/choisir")
async def choisir(demande: DemandeChoix, request: Request):
    etat, borne = _etat(request), _borne(request)

    async def faire():
        try:
            demo = exiger_demo(etat)
        except ErreurAtelier as e:
            return e.statut, {"detail": e.detail, "accepte": False, "raison": "demo_arretee"}
        salle = demande.salle.strip()
        try:
            donnees = borne.donnees_lieu(dossier_du_lieu(demo.get("lieu")))
        except (ErreurAtelier, ErreurLieu, OSError):
            donnees = None
        if donnees is not None:
            refus = A.refus_choix(salle, donnees["salles"], donnees["principal"], demo.get("etage"))
            if refus is not None:
                return STATUT_REFUS[refus[0]], {"detail": refus[1], "accepte": False, "raison": refus[0]}
        if not atelier.MOTIF_ID.match(salle):
            return 404, {"detail": "Cette salle n'existe pas dans ce lieu.", "accepte": False,
                         "raison": "salle_inconnue"}
        message = A.message_choix(salle, "borne", nouvel_id("borne"))
        reponse = await envoyer_et_attendre(etat, "/accueil/choix", message)
        if reponse is None:
            raise ErreurAtelier(503, MESSAGE_SANS_REPONSE_BORNE)
        if reponse.get("code") == "choix_accepte":
            return 200, {"accepte": True, "visite": reponse.get("visite"), "salle": salle, "nom": reponse.get("nom"),
                         "texte": reponse.get("texte")}
        return _refus(reponse)
    return await _une_fois(request, "choisir", faire)


@routeur.post("/api/borne/operateur")
def operateur(demande: DemandeCode, request: Request):
    etat, borne, client = _etat(request), _borne(request), _client(request)
    lieu_id, _ = lieu_de_la_demo(etat)
    if not lieu_id:
        raise ErreurAtelier(409, "La démo ne tourne pas : il n'y a pas de mode opérateur.")
    try:
        donnees = borne.donnees_lieu(dossier_du_lieu(lieu_id))
    except (ErreurLieu, OSError):
        raise ErreurAtelier(409, "Les réglages de la démo sont illisibles : pas de mode opérateur.") from None
    code = (donnees["reglages"].get("borne") or {}).get("code_operateur")
    if not code:
        raise ErreurAtelier(409, "Aucun code opérateur n'est réglé : dans l'Atelier, Équipe › Démo › Réglages de la "
                                 "démo.")
    attente = borne.essais_bloques(client)
    if attente:
        raise ErreurAtelier(429, f"Trop de codes faux : réessayez dans {max(1, round(attente / 60))} min.")
    if not hmac.compare_digest(str(demande.code).strip().encode(), str(code).encode()):
        borne.noter_echec(client)
        if borne.essais_bloques(client):
            raise ErreurAtelier(429, "Trop de codes faux : réessayez dans 5 min.")
        raise ErreurAtelier(403, "Code faux.")
    return {"jeton": borne.nouveau_jeton(client), "expire_s": A.DUREE_JETON_OPERATEUR_S}


@routeur.post("/api/borne/operateur/{action}")
async def action_operateur(action: str, request: Request):
    etat, borne, client = _etat(request), _borne(request), _client(request)
    if action not in A.ACTIONS_OPERATEUR_BORNE:
        raise ErreurAtelier(404, f"Action « {action} » inconnue : {', '.join(A.ACTIONS_OPERATEUR_BORNE)}.")
    if not borne.jeton_valable(request.headers.get(A.ENTETE_JETON_BORNE), client):
        raise ErreurAtelier(401, "Mode opérateur fermé : donnez d'abord le code opérateur.")
    exiger_demo(etat)
    message = A.message_commande(action, "operateur", nouvel_id("operateur"))
    return resultat_commande(await envoyer_et_attendre(etat, "/accueil/commande", message))


@routeur.get("/api/borne/adresse")
def adresse(request: Request):
    return adresses_borne(request)


__all__ = ["Borne", "adresses_borne", "etat_de_la_borne", "routeur"]
