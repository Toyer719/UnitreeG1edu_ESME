"""La démo d'accueil depuis l'Atelier (vague 6, section 13.4 du plan) : agent Borne et orchestrateur.

  GET  /api/demo/etat                    {lancee, etat: dernier /accueil/etat (ou null s'il a plus de 3 s),
                                         voix: dernier /voix/etat, processus: {demo, voix}, borne: {adresses},
                                         lieu, etage, avertissements}
  POST /api/demo/lancer {lieu, etage?}   lance g1-accueil (rôle demo) et g1-voix (rôle voix, avec la sortie de
                                         demo.yaml ; en simulation, la sortie borne) ; 409 si le guide ne tourne
                                         pas (ni simulation ni navigation), si la simulation tourne sur un autre
                                         lieu ou étage, ou, en Réel et en répétition, si le robot n'est pas repéré
  POST /api/demo/arreter                 arrête la démo et la voix ; le robot n'est pas arrêté par cela (ARRÊT)
  POST /api/demo/commande {action}       /accueil/commande depuis l'Atelier (source atelier) : pause, reprendre,
                                         ramener, remise_a_zero ; la réponse de la démo (2 s au plus) : 200
                                         {accepte, texte}, 409 refusée (detail : la phrase de la démo) ou démo
                                         arrêtée, 503 sans pont ROS 2 ou sans réponse
  GET  /api/lieux/{id}/demo              demo.yaml complété par les défauts (atelier.lieu.accueil.reglages_demo)
  PUT  /api/lieux/{id}/demo              écrit demo.yaml (vérifié) : {enregistre, donnees, rapport} ; 422 sinon

Le nœud accueil (paquet g1_accueil) mène la démo ; le serveur ne fait que le lancer, l'arrêter et lui passer les
commandes (PontRos.publier_json), puis lire ses réponses (PontRos.historique("/accueil/evenement")). Les outils
communs aux routes de la borne (envoyer_et_attendre, etat_demo_frais) sont ici.
"""
import asyncio
import itertools
import time
from typing import Any, Optional

from fastapi import APIRouter, Body, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from atelier.lieu import ErreurLieu, valider_donnees
from atelier.lieu import accueil as A

from ..communs import (ErreurAtelier, dossier_du_lieu, erreur_validation, etage_du_lieu, exiger_point_principal,
                       rapport_du_lieu)
from ..processus import CommandeAbsente, commande

routeur = APIRouter(tags=["démo"])

ROLE_DEMO = "demo"
ROLE_VOIX = "voix"
ACTIONS_ATELIER = ("pause", "reprendre", "ramener", "remise_a_zero")
PAS_ATTENTE_S = 0.05
MESSAGE_DEMO_ARRETEE = "La démo ne tourne pas : lancez-la d'abord (Équipe › Démo › Lancer la démo)."
MESSAGE_SANS_REPONSE = ("La démo n'a pas répondu à temps : vérifiez qu'elle tourne encore (« Ce qui tourne »), "
                        "puis réessayez.")
MESSAGE_SANS_GUIDE = ("La démo a besoin du guide : lancez d'abord la simulation (Simuler › Lancer) ou la "
                      "navigation du robot (Naviguer › Lancer).")
# Corrections de la vague 6 (revue de l'interface, défaut 7) : en Simulation, sans faux visiteur (il vient avec une
# scène d'essai), le robot part seul vers la salle et l'accompagnement n'est pas essayé ; l'écran Démo le dit
SUJET_FAUX_VISITEUR = "/faux_visiteur/mode"
MESSAGE_SANS_FAUX_VISITEUR = ("Pas de faux visiteur dans cette simulation : le robot partira seul vers la salle, sans "
                              "personne à accompagner. Le faux visiteur vient avec la scène d'essai « Accompagnement "
                              "d'un visiteur » (Simuler › Avancé › Passants, scènes d'essai).")
STATUT_REFUS = {"occupe": 409, "pause": 409, "demo_arretee": 409, "action_impossible": 409,
                "salle_inconnue": 404, "salle_cachee": 422, "autre_etage": 422, "deja_la": 422}
_numeros = itertools.count(1)


class DemandeLancer(BaseModel):
    lieu: str
    etage: Optional[str] = None


class DemandeCommande(BaseModel):
    action: str


def _etat(request):
    return request.app.state.atelier


# ---------------------------------------------------------------- outils communs (démo et borne)

def nouvel_id(prefixe):
    """Identifiant d'une demande à la démo (champ id de /accueil/choix et /accueil/commande)."""
    return f"{prefixe}-{int(time.time()) % 1000000}-{next(_numeros)}"


def etat_demo_frais(etat):
    """Le dernier /accueil/etat s'il a moins de 3 s (DELAI_ETAT_PERIME_S), sinon None : la démo est arrêtée."""
    if not etat.pont.actif:
        return None
    d = etat.pont.dernier("/accueil/etat")
    if d is None or d.get("age_recu_s", A.DELAI_ETAT_PERIME_S + 1) > A.DELAI_ETAT_PERIME_S:
        return None
    return d


def sans_ros(etat):
    """La phrase d'une demande impossible sans le pont ROS 2 du serveur."""
    return "Pas de liaison avec ROS 2 : " + (etat.pont.erreur or "le pont ROS 2 du serveur n'est pas démarré") + "."


def reponse_de_la_demo(etat, ident):
    """L'événement de /accueil/evenement qui répond à la demande ident, ou None."""
    for e in reversed(etat.pont.historique("/accueil/evenement")):
        if e.get("id") == ident:
            return e
    return None


async def envoyer_et_attendre(etat, sujet, message, delai=A.DELAI_REPONSE_S):
    """Publie un choix ou une commande (avec son id) pour la démo et attend sa réponse (événement de même id).
    Renvoie l'événement, ou None sans réponse dans le délai. ErreurAtelier 503 sans pont ROS 2."""
    if not etat.pont.actif:
        raise ErreurAtelier(503, sans_ros(etat))
    try:
        etat.pont.publier_json(sujet, message)
    except RuntimeError as e:
        raise ErreurAtelier(503, f"La demande n'a pas pu partir : {e}.") from None
    fin = time.monotonic() + delai
    while True:
        reponse = reponse_de_la_demo(etat, message["id"])
        if reponse is not None or time.monotonic() >= fin:
            return reponse
        await asyncio.sleep(PAS_ATTENTE_S)


def exiger_demo(etat):
    """Le dernier /accueil/etat frais ; 503 sans pont ROS 2, 409 si la démo ne tourne pas."""
    if not etat.pont.actif:
        raise ErreurAtelier(503, sans_ros(etat))
    demo = etat_demo_frais(etat)
    if demo is None:
        raise ErreurAtelier(409, MESSAGE_DEMO_ARRETEE)
    return demo


def resultat_commande(reponse):
    """Réponse HTTP d'une commande à la démo : {accepte, texte, evenement} ; ErreurAtelier si refusée."""
    if reponse is None:
        raise ErreurAtelier(503, MESSAGE_SANS_REPONSE)
    if reponse.get("code") != "commande_acceptee":
        raise ErreurAtelier(STATUT_REFUS.get(reponse.get("raison"), 409), reponse.get("texte") or "Refusé.")
    return {"accepte": True, "texte": reponse.get("texte"), "evenement": _sans_age(reponse)}


def _sans_age(d):
    return {k: v for k, v in d.items() if k not in ("age_recu_s", "perime")}


def lieu_de_la_demo(etat):
    """(id du lieu, étage) de la démo : celle qui tourne, sinon la dernière lancée, sinon la simulation."""
    demo = etat_demo_frais(etat)
    if demo is not None:
        return demo.get("lieu"), demo.get("etage")
    p = etat.gestionnaire.processus.get(ROLE_DEMO)
    if p is not None and p.infos.get("lieu"):
        return p.infos["lieu"], p.infos.get("etage")
    if etat.simulation is not None:
        return etat.simulation.get("lieu"), etat.simulation.get("etage")
    return None, None


# ---------------------------------------------------------------- routes

def _processus(etat, role):
    p = etat.gestionnaire.processus.get(role)
    return None if p is None else p.etat()


def faux_visiteur_present(etat):
    """Vrai si un faux visiteur écoute /faux_visiteur/mode (nœud faux_visiteur de g1_nav, avec une scène d'essai),
    faux sinon, None si on ne peut pas le savoir (pas de pont ROS 2)."""
    infos = getattr(etat.pont, "infos_sujet", None)
    vu = infos(SUJET_FAUX_VISITEUR) if infos is not None and etat.pont.actif else None
    return None if vu is None else bool(vu.get("abonnes"))


def _avertissements(etat):
    """Ce qui ne va pas avec ce qui a été lancé (la voix qui s'est arrêtée, pas de faux visiteur en Simulation…), en
    français."""
    messages = []
    voix = etat.gestionnaire.processus.get(ROLE_VOIX)
    demo = etat.gestionnaire.processus.get(ROLE_DEMO)
    if demo is not None and not demo.en_cours and not demo.arret_demande:
        lignes = [x for x in demo.etat()["dernieres_lignes"] if x.strip()]
        messages.append("La démo s'est arrêtée seule" + (f" : {lignes[-1]}" if lignes else "") + ".")
    if voix is not None and not voix.en_cours and not voix.arret_demande:
        messages.append("La voix ne tourne pas (elle s'est arrêtée) : la démo continue en silence.")
    if (demo is not None and demo.en_cours and etat.mode_navigation() == "simu"
            and faux_visiteur_present(etat) is False):
        messages.append(MESSAGE_SANS_FAUX_VISITEUR)
    return messages


@routeur.get("/api/demo/etat")
def etat_demo(request: Request):
    from .borne import adresses_borne
    etat = _etat(request)
    demo = etat_demo_frais(etat)
    voix = etat.pont.dernier("/voix/etat") if etat.pont.actif else None
    lieu, etage = lieu_de_la_demo(etat)
    return {"lancee": etat.gestionnaire.en_cours(ROLE_DEMO), "etat": demo, "voix": voix,
            "processus": {ROLE_DEMO: _processus(etat, ROLE_DEMO), ROLE_VOIX: _processus(etat, ROLE_VOIX)},
            "borne": {"adresses": adresses_borne(request)["adresses"]}, "lieu": lieu, "etage": etage,
            "avertissements": _avertissements(etat), "ros": {"actif": etat.pont.actif, "erreur": etat.pont.erreur}}


def _verifier_guide(etat, lieu, etage):
    """409 si la démo ne peut pas tourner : pas de guide, autre lieu ou étage, robot pas repéré."""
    from .simulation import MESSAGE_REPERER, robot_repere
    mode = etat.mode_navigation()
    if mode is None:
        raise ErreurAtelier(409, MESSAGE_SANS_GUIDE)
    s = etat.simulation or {}
    if s.get("lieu") != lieu:
        raise ErreurAtelier(409, f"Le guide tourne sur le lieu « {s.get('lieu')} » : lancez la démo sur ce lieu, ou "
                                 "relancez la simulation sur celui-ci.")
    if s.get("etage") != etage:
        raise ErreurAtelier(409, f"Le guide tourne à l'étage « {s.get('etage')} » : lancez la démo sur cet étage.")
    if mode in ("repetition", "robot") and not robot_repere(etat):
        raise ErreurAtelier(409, MESSAGE_REPERER)
    return mode


@routeur.post("/api/demo/lancer")
async def lancer(demande: DemandeLancer, request: Request):
    etat = _etat(request)
    dossier = dossier_du_lieu(demande.lieu)
    principal = exiger_point_principal(dossier)
    etage = demande.etage or principal.etage
    etage_du_lieu(dossier, etage)
    mode = _verifier_guide(etat, demande.lieu, etage)
    if etat_demo_frais(etat) is not None and not etat.gestionnaire.en_cours(ROLE_DEMO):
        raise ErreurAtelier(409, "Une démo tourne déjà, lancée hors de l'Atelier (g1-accueil dans un terminal) : "
                                 "arrêtez-la d'abord là où elle a été lancée (Ctrl+C).")
    if commande("g1-accueil") is None:
        raise ErreurAtelier(503, "Impossible de lancer la démo : la commande g1-accueil n'est pas installée.")
    try:
        reglages = A.reglages_demo(dossier)
    except ErreurLieu as e:
        raise ErreurAtelier(422, "Le fichier demo.yaml est invalide : corrigez-le dans Équipe › Démo › Réglages de "
                                 "la démo.", e.erreurs) from None
    avertissements = []
    infos = {"lieu": demande.lieu, "etage": etage, "mode": mode}
    suivre_pont = "false" if mode == "simu" else "true"
    arguments = ["--lieu", str(dossier), "--etage", etage, "--", "--ros-args", "-p", f"suivre_pont:={suivre_pont}"]
    try:
        await run_in_threadpool(etat.gestionnaire.lancer, ROLE_DEMO, "g1-accueil", arguments, infos)
    except CommandeAbsente as e:
        raise ErreurAtelier(503, f"Impossible de lancer la démo : {e}.") from None
    voix = reglages.get("voix") or {}
    sortie = voix.get("sortie", "robot")
    if mode == "simu" and faux_visiteur_present(etat) is False:
        avertissements.append(MESSAGE_SANS_FAUX_VISITEUR)
    if mode == "simu" and sortie != "borne":
        sortie = "borne"
        avertissements.append("En simulation, il n'y a pas de haut-parleur du robot : la voix passe par la borne.")
    if commande("g1-voix") is None:
        avertissements.append("La voix n'est pas installée (g1-voix) : la démo tourne en silence.")
    else:
        arguments_voix = ["--lieu", str(dossier), "--sortie", sortie]
        if voix.get("volume") is not None:
            arguments_voix += ["--volume", str(int(voix["volume"]))]
        if voix.get("nom"):
            arguments_voix += ["--voix", str(voix["nom"])]
        try:
            await run_in_threadpool(etat.gestionnaire.lancer, ROLE_VOIX, "g1-voix", arguments_voix,
                                    dict(infos, sortie=sortie))
        except CommandeAbsente:
            avertissements.append("La voix n'a pas pu être lancée : la démo tourne en silence.")
    return {"lancee": True, "lieu": demande.lieu, "etage": etage, "mode": mode, "sortie_voix": sortie,
            "processus": {ROLE_DEMO: _processus(etat, ROLE_DEMO), ROLE_VOIX: _processus(etat, ROLE_VOIX)},
            "avertissements": avertissements,
            "message": "Démo lancée : le robot attend un visiteur à l'accueil (la borne suit)."}


@routeur.post("/api/demo/arreter")
async def arreter(request: Request):
    etat = _etat(request)
    etait = etat.gestionnaire.en_cours(ROLE_DEMO)
    for role in (ROLE_VOIX, ROLE_DEMO):
        await run_in_threadpool(etat.gestionnaire.arreter, role, 5.0)
    return {"lancee": False,
            "processus": {ROLE_DEMO: _processus(etat, ROLE_DEMO), ROLE_VOIX: _processus(etat, ROLE_VOIX)},
            "message": ("Démo arrêtée : la borne affiche que le robot se prépare. Le robot n'est pas arrêté par cela "
                        "(une visite en cours se finit) : pour l'arrêter, ARRÊT." if etait else
                        "La démo ne tournait pas.")}


@routeur.post("/api/demo/commande")
async def commander(demande: DemandeCommande, request: Request):
    etat = _etat(request)
    if demande.action not in ACTIONS_ATELIER:
        raise ErreurAtelier(400, f"Action « {demande.action} » inconnue : {', '.join(ACTIONS_ATELIER)}.")
    exiger_demo(etat)
    message = A.message_commande(demande.action, "atelier", nouvel_id("atelier"))
    return resultat_commande(await envoyer_et_attendre(etat, "/accueil/commande", message))


@routeur.get("/api/lieux/{id_lieu}/demo")
def lire_reglages(id_lieu: str):
    return A.reglages_demo(dossier_du_lieu(id_lieu))


@routeur.put("/api/lieux/{id_lieu}/demo")
def ecrire_reglages(id_lieu: str, donnees: Any = Body(...)):
    dossier = dossier_du_lieu(id_lieu)
    erreurs = valider_donnees("demo", donnees)
    if erreurs:
        raise erreur_validation(A.FICHIER_DEMO, erreurs)
    try:
        A.enregistrer_demo(dossier, donnees)
    except ErreurLieu as e:
        raise erreur_validation(A.FICHIER_DEMO, e.erreurs) from None
    return {"enregistre": [A.FICHIER_DEMO], "donnees": A.reglages_demo(dossier), "rapport": rapport_du_lieu(dossier)}
