"""ARRÊT global de l'Atelier (vague 5, section 12.4 du plan) : agent Coquille.

  POST /api/arret {mode?: simu|reel|repetition, raison?: texte}
        arrête tout, en parallèle, en moins de 1 s même si une partie ne répond pas :
          guide     /guide/stop (etat.pont.stop()) ; sans pont ROS 2 mais avec une navigation lancée
                    par l'Atelier : g1-guide stop, lancé sans l'attendre ;
          teleop    vitesse nulle sur /cmd_vel si la téléopération simulée a servi (app.state.teleop) ;
          pilotage  POST /arret du nœud pilotage (adresse et jeton de routes/pilotage.py), 0,6 s au plus ;
                    personne à son adresse : sans objet (ok null), sauf s'il a tourné (lancé par
                    l'Atelier, ou /pilotage/etat reçu) ; pas de réponse à temps : faute (ok faux) ;
          verrou    en mode reel ou repetition (champ mode, ou mode de la navigation qui tourne) :
                    /pont/arret true (etat.pont.bloquer(True)) ; jamais en simulation (le verrou est
                    transient_local : il bloquerait la répétition suivante).
        Réponse toujours 200 (on ne refuse jamais un ARRÊT, même mal formé) : {arrete, mode, verrou,
        duree_s, parties: {guide|teleop|pilotage|verrou: {ok: true|false|null, detail}}, message} ;
        ok null : partie sans objet (rien ne tournait).
  POST /api/arret/debloquer
        /pont/arret false : {verrou: false, ecoute, message} ; 503 sans pont ROS 2.
  GET  /api/arret
        {verrou, depuis, mode, par} : le dernier verrou posé par l'Atelier (aussi dans /ws/etat, champ
        arret). par : arret (ce bouton), bloquer (« Bloquer » de Naviguer) ou debloquer.

L'ARRÊT n'arrête pas un scan (« Fin » le fait) ; en répétition, l'exploration d'un scan passe par le
pont, que le verrou arrête. POST /api/robot/arret {verrou} (vague 3) reste et met à jour le même état.
"""
import asyncio
import json
import threading
import time
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool

from ..communs import ErreurAtelier
from ..processus import CommandeAbsente, commande, lancer_et_attendre

routeur = APIRouter(tags=["arrêt"])

MODES = ("simu", "reel", "repetition")
DELAI_PARTIE_S = 0.5          # guide, téléopération, verrou : des publications locales
DELAI_PILOTAGE_S = 0.6        # le nœud pilotage (HTTP) : au-delà, on n'attend plus
DELAI_TOTAL_S = 0.9           # garde-fou : la réponse part avant 1 s quoi qu'il arrive
PARTIES = ("guide", "teleop", "pilotage", "verrou")


def maintenant_iso():
    """Heure locale, au format ISO 8601 à la seconde (ex. 2026-10-31T05:40:12+01:00)."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def noter_verrou(etat, verrou, mode, par):
    """Retient le dernier verrou posé ou retiré par l'Atelier (GET /api/arret, champ arret de /ws/etat)."""
    etat.arret = {"verrou": bool(verrou), "depuis": maintenant_iso(), "mode": mode, "par": par}


def mode_de_la_demande(corps, etat):
    """(mode affiché, avec_verrou) : le mode demandé (simu, reel, repetition), sinon celui de la navigation
    qui tourne (robot → reel). Le verrou se pose en Réel et en répétition, ou si la navigation qui tourne
    est celle du robot ou de la répétition, quel que soit le mode demandé."""
    demande = corps.get("mode") if isinstance(corps, dict) else None
    demande = demande if demande in MODES else None
    navigation = etat.mode_navigation()         # simu, repetition, robot ou None
    mode = demande or {"robot": "reel"}.get(navigation, navigation)
    avec_verrou = demande in ("reel", "repetition") or navigation in ("repetition", "robot")
    return mode, avec_verrou


async def _lire_corps(request):
    """Le corps JSON de la demande, ou {} s'il est vide ou illisible : un ARRÊT n'est jamais refusé."""
    try:
        texte = await request.body()
        corps = json.loads(texte) if texte else {}
    except (ValueError, UnicodeDecodeError):
        return {}
    return corps if isinstance(corps, dict) else {}


def _resultat(ok, detail):
    return {"ok": ok, "detail": detail}


# ---------------------------------------------------------------- les quatre parties

def _guide(etat):
    """/guide/stop par le pont ROS 2 ; à défaut, g1-guide stop (sans l'attendre) si une navigation tourne."""
    navigation = etat.gestionnaire.en_cours("navigation") or etat.mode_navigation() == "robot"
    if etat.pont.actif:
        try:
            ecoute = etat.pont.stop()
        except RuntimeError as e:
            return _resultat(False, f"/guide/stop n'a pas pu partir : {e}")
        if ecoute:
            return _resultat(True, "arrêt envoyé au guide (/guide/stop)")
        if navigation:
            return _resultat(True, "/guide/stop envoyé ; le guide ne l'écoute pas encore (il démarre)")
        return _resultat(None, "aucun guide ne tourne")
    if navigation and commande("g1-guide") is not None:
        def envoyer():
            try:
                lancer_et_attendre("g1-guide", ["stop"], 15.0)
            except CommandeAbsente:
                pass
        threading.Thread(target=envoyer, name="g1-guide stop", daemon=True).start()
        return _resultat(True, "pas de pont ROS 2 : arrêt envoyé par la commande g1-guide stop")
    if navigation:
        return _resultat(False, "pas de pont ROS 2 ni de commande g1-guide : arrêtez la simulation")
    return _resultat(None, "pas de pont ROS 2, et aucune navigation lancée par l'Atelier")


def _teleop(app):
    """Vitesse nulle sur /cmd_vel si la téléopération simulée (flèches du scan simulé) a servi."""
    teleop = getattr(app.state, "teleop", None)
    if teleop is None:
        return _resultat(None, "la téléopération n'a pas servi")
    try:
        teleop.envoyer(0.0, 0.0, 0.0)
    except Exception as e:      # noqa: BLE001 : pont arrêté entre-temps ; l'ARRÊT continue
        return _resultat(False, f"vitesse nulle non publiée : {e}")
    return _resultat(True, "vitesse nulle publiée sur /cmd_vel")


def _pilotage_attendu(etat):
    """Vrai si le nœud pilotage devrait répondre : lancé par l'Atelier, ou entendu sur /pilotage/etat
    (sur le PC comme dans le conteneur du Jetson). Sinon, un nœud injoignable est « sans objet »."""
    if "pilotage" in etat.gestionnaire.etat():
        return True
    try:
        return etat.pont.dernier("/pilotage/etat") is not None
    except Exception:       # noqa: BLE001 : pont sans ce sujet (tests)
        return False


async def _pilotage(etat):
    """POST /arret au nœud pilotage (StopMove, chorégraphie, bras relâchés), 0,6 s au plus.
    Personne à l'adresse du nœud : sans objet, sauf s'il a tourné ; pas de réponse à temps : faute."""
    import httpx
    from atelier.lieu import pilotage as D
    from .pilotage import jeton, url_noeud
    cle = jeton()
    try:
        async with httpx.AsyncClient(timeout=DELAI_PILOTAGE_S) as client:
            r = await client.post(url_noeud() + "/arret", json={"par": "atelier"},
                                  headers={D.ENTETE_JETON: cle} if cle else {})
    except httpx.ConnectError:
        if _pilotage_attendu(etat):
            return _resultat(False, "le nœud pilotage ne répond plus : utilisez la télécommande pour arrêter le robot")
        return _resultat(None, "le nœud pilotage ne tourne pas")
    except httpx.HTTPError:
        return _resultat(False, f"le nœud pilotage ne répond pas en {DELAI_PILOTAGE_S:g} s : utilisez la "
                                "télécommande pour arrêter le robot")
    try:
        donnees = r.json()
    except ValueError:
        donnees = {}
    detail = donnees.get("detail") if isinstance(donnees, dict) else None
    if 200 <= r.status_code < 300:
        return _resultat(True, detail or "ARRÊT reçu par le nœud pilotage")
    return _resultat(False, f"le nœud pilotage a répondu {r.status_code}" + (f" : {detail}" if detail else ""))


def _verrou(etat, mode):
    """/pont/arret true : le pont garde le robot immobile jusqu'à « Débloquer »."""
    if not etat.pont.actif:
        return _resultat(False, "pas de pont ROS 2 : le robot n'a pas pu être bloqué ; utilisez la télécommande")
    try:
        ecoute = etat.pont.bloquer(True)
    except RuntimeError as e:
        return _resultat(False, f"/pont/arret n'a pas pu partir : {e}")
    noter_verrou(etat, True, mode, "arret")
    if ecoute:
        return _resultat(True, "robot bloqué (/pont/arret) jusqu'à « Débloquer »")
    return _resultat(True, "verrou posé : aucun pont ne l'écoute encore, il s'appliquera dès qu'il démarrera")


async def _avec_delai(coroutine, delai, partie):
    try:
        return await asyncio.wait_for(coroutine, delai)
    except asyncio.TimeoutError:
        return _resultat(False, f"pas de réponse en {delai:g} s")
    except Exception as e:      # noqa: BLE001 : jamais d'erreur 500 sur un ARRÊT
        return _resultat(False, f"{partie} : {e}")


def message_arret(parties, verrou):
    """Phrase courte pour l'utilisateur, d'après le résultat des parties."""
    fautes = [nom for nom in PARTIES if parties[nom]["ok"] is False]
    textes = {"guide": "le guide", "teleop": "la téléopération", "pilotage": "le nœud pilotage",
              "verrou": "le verrou du pont"}
    if fautes:
        sujet = " et ".join(textes[n] for n in fautes)
        verbe = "n'a pas répondu" if len(fautes) == 1 else "n'ont pas répondu"
        return f"ARRÊT envoyé, mais {sujet} {verbe} : gardez la télécommande en main."
    if verrou:
        return "ARRÊT : robot arrêté et bloqué. « Débloquer » le laisse repartir."
    if all(parties[n]["ok"] is None for n in PARTIES):
        return "ARRÊT : rien ne tournait."
    return "ARRÊT : robot arrêté."


# ---------------------------------------------------------------- routes

@routeur.post("/api/arret")
async def arreter_tout(request: Request):
    """ARRÊT : guide, téléopération, pilotage, et verrou du pont en mode réel ou répétition."""
    debut = time.monotonic()
    etat = request.app.state.atelier
    corps = await _lire_corps(request)
    mode, avec_verrou = mode_de_la_demande(corps, etat)
    taches = {
        "guide": _avec_delai(run_in_threadpool(_guide, etat), DELAI_PARTIE_S, "guide"),
        "teleop": _avec_delai(run_in_threadpool(_teleop, request.app), DELAI_PARTIE_S, "téléopération"),
        "pilotage": _avec_delai(_pilotage(etat), DELAI_PILOTAGE_S + 0.1, "pilotage"),
    }
    if avec_verrou:
        taches["verrou"] = _avec_delai(run_in_threadpool(_verrou, etat, mode), DELAI_PARTIE_S, "verrou")
    noms = list(taches)
    try:
        resultats = await asyncio.wait_for(asyncio.gather(*taches.values()), DELAI_TOTAL_S)
    except asyncio.TimeoutError:      # ne devrait pas arriver : chaque partie a son propre délai
        resultats = [_resultat(False, "pas de réponse à temps") for _ in noms]
    parties = dict(zip(noms, resultats))
    if not avec_verrou:
        parties["verrou"] = _resultat(None, "simulation : pas de verrou (le robot simulé est seulement arrêté)")
    verrou = parties["verrou"]["ok"] is True
    raison = corps.get("raison")
    reponse = {"arrete": True, "mode": mode, "verrou": verrou, "duree_s": round(time.monotonic() - debut, 3),
               "parties": {nom: parties[nom] for nom in PARTIES}, "message": message_arret(parties, verrou)}
    if isinstance(raison, str) and raison.strip():
        reponse["raison"] = raison.strip()[:200]
    return reponse


@routeur.post("/api/arret/debloquer")
def debloquer(request: Request):
    """Retire le verrou posé par l'ARRÊT (/pont/arret false)."""
    etat = request.app.state.atelier
    if not etat.pont.actif:
        raise ErreurAtelier(503, "Pas de liaison avec ROS 2 : "
                            + (etat.pont.erreur or "le pont ROS 2 du serveur n'est pas démarré")
                            + ". Le verrou ne peut pas être retiré d'ici.")
    try:
        ecoute = etat.pont.bloquer(False)
    except RuntimeError as e:
        raise ErreurAtelier(503, f"Le déblocage n'a pas pu partir : {e}.") from None
    mode = etat.arret.get("mode") if isinstance(getattr(etat, "arret", None), dict) else None
    noter_verrou(etat, False, mode, "debloquer")
    return {"verrou": False, "ecoute": ecoute,
            "message": "Robot débloqué : il repartira à la prochaine consigne."
            + ("" if ecoute else " (Aucun pont n'écoute pour l'instant.)")}


@routeur.get("/api/arret")
def lire_arret(request: Request):
    """Le dernier verrou posé par l'ARRÊT de l'Atelier."""
    return dict(request.app.state.atelier.arret)
