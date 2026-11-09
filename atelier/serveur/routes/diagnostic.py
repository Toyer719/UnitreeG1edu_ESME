"""Diagnostic « Vérifier le robot » (vague 6, section 13.2 du plan) : agent Diagnostic.

  GET  /api/robot/diagnostic?mode=reel|repetition[&rapide=1]
        toutes les vérifications (atelier.diagnostic.diagnostiquer), en moins de 10 s (15 s au plus) : schéma
        diagnostic ; mode absent : celui de la navigation qui tourne (robot → reel, repetition), sinon reel ;
        simu : 409 (pas de robot en simulation) ; rapide : sans ssh vers le Jetson. Le diagnostic tourne hors de la
        boucle du serveur (jamais bloquant : l'ARRÊT répond toujours) ; deux demandes pareilles en même temps
        attendent le même diagnostic (aucun ping ni ssh en double).
  GET  /api/robot/diagnostic/dernier[?mode=reel|repetition]
        le dernier résultat (du mode, ou le plus récent) ; 404 s'il n'y en a pas encore.
  POST /api/robot/diagnostic/{action} {confirme: true, services?: [...], mode?, rapide?}
        une action de atelier.lieu.diagnostic.ACTIONS_DIAGNOSTIC, seulement sur un clic confirmé : action inconnue :
        404 ; sans « confirme » (vrai) : 409 et rien ne part ; service hors de SERVICES_CARTOGRAPHIE : 403 ; en
        simulation (pas de robot), ou le câble en répétition : 409 ; la même action déjà en cours : 409. Réponse
        {action, ok, message, …, diagnostic} (le diagnostic refait après l'action) ; ok faux (et 200) quand le robot
        n'a pas répondu ou a refusé.

Jamais d'erreur 500 ; messages en français, {detail, …}. Le faux contexte des tests : ATELIER_DIAGNOSTIC_FAUX
(atelier.diagnostic.contexte), lu à chaque diagnostic.
"""
import json
import logging
import threading
from concurrent.futures import Future
from contextlib import contextmanager

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool

from atelier.diagnostic import (ActionImpossible, ActionInconnue, ServiceInterdit, contexte_par_defaut,
                                diagnostiquer, faire_action, normaliser_mode, services_demandes, verifier_action)
from atelier.lieu.diagnostic import ACTIONS_DIAGNOSTIC, DELAI_DIAGNOSTIC_S

from ..communs import ErreurAtelier

routeur = APIRouter(tags=["diagnostic"])
JOURNAL = logging.getLogger("atelier.serveur")
ATTENTE_PARTAGEE_S = DELAI_DIAGNOSTIC_S + 5.0     # une demande qui attend le diagnostic d'une autre


class MemoireDiagnostic:
    """Ce que le serveur garde du diagnostic : le dernier résultat de chaque mode, les diagnostics en cours (une
    demande pareille attend le même), les actions en cours (une seule fois chacune)."""

    def __init__(self):
        self.verrou = threading.Lock()
        self.derniers = {}            # mode → résultat
        self.plus_recent = None
        self.en_cours = {}            # (mode, rapide) → Future
        self.actions = set()

    def noter(self, resultat):
        with self.verrou:
            self.derniers[resultat["mode"]] = resultat
            self.plus_recent = resultat

    def dernier(self, mode=None):
        with self.verrou:
            return self.derniers.get(mode) if mode else self.plus_recent

    def diagnostic(self, cle, faire):
        """Le diagnostic de cette clé : celui qui tourne déjà, sinon un nouveau (faire())."""
        with self.verrou:
            futur = self.en_cours.get(cle)
            a_faire = futur is None
            if a_faire:
                futur = self.en_cours[cle] = Future()
        if not a_faire:
            return futur.result(timeout=ATTENTE_PARTAGEE_S)
        try:
            resultat = faire()
        except BaseException as e:
            futur.set_exception(e)
            raise
        else:
            futur.set_result(resultat)
            self.noter(resultat)
            return resultat
        finally:
            with self.verrou:
                self.en_cours.pop(cle, None)

    @contextmanager
    def action(self, nom):
        with self.verrou:
            if nom in self.actions:
                raise ErreurAtelier(409, f"« {ACTIONS_DIAGNOSTIC[nom]['libelle']} » est déjà en cours : attendez la "
                                         "fin, puis vérifiez à nouveau.")
            self.actions.add(nom)
        try:
            yield
        finally:
            with self.verrou:
                self.actions.discard(nom)


_CREATION = threading.Lock()


def memoire(app):
    """La mémoire du diagnostic de cette application (créée au premier appel)."""
    with _CREATION:
        m = getattr(app.state, "diagnostic", None)
        if m is None:
            m = app.state.diagnostic = MemoireDiagnostic()
        return m


def mode_de_la_demande(etat, mode):
    """reel ou repetition, d'après la demande, sinon la navigation qui tourne (robot → reel), sinon reel.
    409 en simulation, 400 pour un mode inconnu."""
    if mode in (None, ""):
        en_cours = etat.mode_navigation() if hasattr(etat, "mode_navigation") else None
        return "repetition" if en_cours == "repetition" else "reel"
    if str(mode).strip().lower() == "simu":
        raise ErreurAtelier(409, "En simulation, il n'y a pas de robot à vérifier : passez en Réel (ou en répétition "
                                 "sans robot) depuis l'accueil.")
    try:
        return normaliser_mode(mode)
    except ValueError:
        raise ErreurAtelier(400, f"Mode « {mode} » inconnu : reel (le vrai robot) ou repetition (le faux "
                                 "G1).") from None


def _diagnostic(app, mode, rapide):
    """Le diagnostic (dans un fil du serveur), partagé avec une demande pareille en cours."""
    etat = app.state.atelier

    def faire():
        return diagnostiquer(mode, pont=etat.pont, contexte=contexte_par_defaut(), source="atelier", rapide=rapide)
    return memoire(app).diagnostic((mode, bool(rapide)), faire)


async def diagnostic_protege(app, mode, rapide):
    """Le diagnostic, ou une erreur en français (jamais 500)."""
    try:
        return await run_in_threadpool(_diagnostic, app, mode, rapide)
    except ValueError as e:                     # faux contexte illisible, mode hors contrat
        raise ErreurAtelier(400, f"Diagnostic impossible : {e}.") from None
    except ErreurAtelier:
        raise
    except Exception as e:      # noqa: BLE001 : jamais d'erreur 500, le message va à l'utilisateur
        JOURNAL.exception("diagnostic : erreur inattendue")
        raise ErreurAtelier(503, f"Le diagnostic a échoué ({type(e).__name__} : {e}). Réessayez ; si cela "
                                 "recommence, notez ce message pour l'équipe.") from None


@routeur.get("/api/robot/diagnostic")
async def diagnostic(request: Request, mode: str = None, rapide: bool = False):
    """Toutes les vérifications du robot (schéma diagnostic)."""
    m = mode_de_la_demande(request.app.state.atelier, mode)
    return await diagnostic_protege(request.app, m, rapide)


@routeur.get("/api/robot/diagnostic/dernier")
def dernier(request: Request, mode: str = None):
    """Le dernier diagnostic (du mode demandé, sinon le plus récent)."""
    m = None
    if mode not in (None, ""):
        m = mode_de_la_demande(request.app.state.atelier, mode)
    resultat = memoire(request.app).dernier(m)
    if resultat is None:
        raise ErreurAtelier(404, "Aucun diagnostic pour le moment : cliquez sur « Vérifier le robot ».")
    return resultat


async def _corps(request):
    """Le corps JSON de la demande (un objet), ou {} s'il est vide ou illisible."""
    try:
        brut = await request.body()
        donnees = json.loads(brut) if brut else {}
    except (ValueError, UnicodeDecodeError):
        return {}
    return donnees if isinstance(donnees, dict) else {}


@routeur.post("/api/robot/diagnostic/{action}")
async def action(action: str, request: Request):
    """Une action du diagnostic, après la confirmation dans la page."""
    if action not in ACTIONS_DIAGNOSTIC:
        raise ErreurAtelier(404, f"Action « {action} » inconnue : les actions possibles sont "
                                 f"{', '.join(ACTIONS_DIAGNOSTIC)}. Rien n'a été envoyé.")
    corps = await _corps(request)
    libelle = ACTIONS_DIAGNOSTIC[action]["libelle"]
    if corps.get("confirme") is not True:
        raise ErreurAtelier(409, f"Rien n'a été envoyé : « {libelle} » demande une confirmation (cliquez sur le "
                                 "bouton, puis confirmez).")
    etat = request.app.state.atelier
    mode = corps.get("mode")
    en_cours = etat.mode_navigation() if hasattr(etat, "mode_navigation") else None
    if (mode in (None, "") and en_cours == "simu") or (isinstance(mode, str) and mode.strip().lower() == "simu"):
        mode = "simu"                       # pas de robot en simulation : 409 plus bas, rien n'est envoyé
    else:
        mode = mode_de_la_demande(etat, mode)
    try:
        verifier_action(action, mode)
        services = services_demandes(corps.get("services")) if action == "demarrer-services" else None
    except ActionInconnue as e:
        raise ErreurAtelier(404, f"{e}. Rien n'a été envoyé.") from None
    except ServiceInterdit as e:
        raise ErreurAtelier(403, f"Rien n'a été envoyé : {e}.") from None
    except ActionImpossible as e:
        raise ErreurAtelier(409, str(e)) from None
    with memoire(request.app).action(action):
        JOURNAL.info("diagnostic : action %s confirmée (mode %s)", action, mode)
        try:
            resultat = await run_in_threadpool(faire_action, action, mode, etat.pont, contexte_par_defaut(),
                                               services)
        except ValueError as e:
            raise ErreurAtelier(400, f"Action impossible : {e}.") from None
        except Exception as e:      # noqa: BLE001 : jamais d'erreur 500
            JOURNAL.exception("diagnostic : action %s", action)
            raise ErreurAtelier(503, f"L'action a échoué ({type(e).__name__} : {e}).") from None
    JOURNAL.info("diagnostic : %s → %s", action, resultat.get("message"))
    try:
        resultat["diagnostic"] = await diagnostic_protege(request.app, mode, bool(corps.get("rapide")))
    except ErreurAtelier as e:
        resultat["diagnostic"] = None
        resultat["erreur_diagnostic"] = e.detail
    return resultat
