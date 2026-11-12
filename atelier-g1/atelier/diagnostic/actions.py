"""Les actions du diagnostic (vague 6, section 13.2 du plan) : agent Diagnostic.

Seulement sur un clic, après la confirmation dans la page (ou la réponse « oui » de g1-diagnostic), jamais
automatiques ; liste blanche stricte (atelier.lieu.diagnostic.ACTIONS_DIAGNOSTIC) :
  demarrer-services   « Démarrer les services de cartographie » : 1003 (la liste), puis 1001 {"name", "switch": 1}
                      pour chaque service ARRÊTÉ de SERVICES_CARTOGRAPHIE (lidar_driver, unitree_slam) que le robot
                      connaît, puis 1003 toutes les secondes jusqu'à ce qu'ils soient actifs (DELAI_SERVICES_S) ;
                      jamais switch 0, jamais un autre service (ServiceInterdit) ; le robot ne bouge pas ;
  retablir-cable      « Rétablir la connexion du câble » : nmcli connection up robot-g1 (15 s au plus) ;
  cable-automatique   « La rétablir seule à chaque branchement » : nmcli connection modify robot-g1
                      connection.autoconnect yes (le Wi-Fi garde Internet : robot.sh a mis ipv4.never-default).
Jamais sudo ; pendant les essais (G1_SLAM_FAUX=1), les deux actions du câble ne partent pas ; avec le faux contexte
(ATELIER_DIAGNOSTIC_FAUX), la commande est seulement notée dans <fichier>.journal.
"""
import time

from atelier.lieu.diagnostic import (ACTIONS_DIAGNOSTIC, COMMANDES_ACTIONS, DELAI_APPEL_S, DELAI_SERVICES_S,
                                     PROFIL_RESEAU, SERVICES_CARTOGRAPHIE, STATUT_ACTIF, accord_services,
                                     lire_liste_services, lire_reponse_switch, majuscule, noms_services,
                                     parametre_service_list, parametre_service_switch)

from .contexte import EssaisInterdits
from .verdicts import liste_noms, nombre

DELAI_NMCLI_ACTION_S = 15.0
DELAI_APPEL_NOEUD_NEUF_S = 3.5
PERIODE_SERVICES_S = 1.0


class ActionInconnue(ValueError):
    """Action hors de ACTIONS_DIAGNOSTIC (la route répond 404)."""


class ServiceInterdit(ValueError):
    """Service hors de SERVICES_CARTOGRAPHIE (la route répond 403) : rien n'est envoyé."""


class ActionImpossible(ValueError):
    """Action sans objet dans ce mode (la route répond 409) : rien n'est envoyé."""


def services_demandes(services):
    """Les services à démarrer : tous ceux de la liste blanche (None), ou un sous-ensemble ; ServiceInterdit
    sinon (en français), avant tout envoi."""
    if services is None:
        return list(SERVICES_CARTOGRAPHIE)
    if isinstance(services, str) or not isinstance(services, (list, tuple)) \
            or not all(isinstance(s, str) for s in services):
        raise ServiceInterdit(f"« services » doit être une liste de noms : l'Atelier ne démarre que "
                              f"{liste_noms(SERVICES_CARTOGRAPHIE)} (tout autre service est interdit)")
    interdits = [s for s in services if s not in SERVICES_CARTOGRAPHIE]
    if interdits:
        raise ServiceInterdit(f"service {liste_noms(f'« {s} »' for s in interdits)} interdit : l'Atelier ne démarre "
                              f"que {liste_noms(SERVICES_CARTOGRAPHIE)}")
    return [s for s in SERVICES_CARTOGRAPHIE if s in services]


def verifier_action(action, mode):
    """ActionInconnue ou ActionImpossible avant tout envoi (mode : reel, repetition ou simu)."""
    if action not in ACTIONS_DIAGNOSTIC:
        raise ActionInconnue(f"action « {action} » inconnue (actions possibles : {', '.join(ACTIONS_DIAGNOSTIC)})")
    if mode == "simu":
        raise ActionImpossible("En simulation, il n'y a pas de robot : rien n'est envoyé.")
    if mode == "repetition" and action != "demarrer-services":
        raise ActionImpossible("En répétition, le câble du robot ne sert pas : rien n'est changé.")
    if mode not in ("reel", "repetition"):
        raise ActionImpossible(f"Mode « {mode} » inconnu : reel ou repetition.")


def _liste(pont, delai=DELAI_APPEL_S):
    """(services, None) d'après robot_state 1003, ou (None, phrase qui dit pourquoi)."""
    try:
        code, data = pont.appeler_unitree("robot_state", 1003, parametre_service_list(), delai)
    except TimeoutError:
        return None, "le robot ne répond pas quand on lui demande ses services"
    except (RuntimeError, PermissionError) as e:
        return None, str(e)
    if code != 0:
        return None, f"le robot refuse de donner la liste de ses services (code {code})"
    try:
        return lire_liste_services(data), None
    except ValueError as e:
        return None, f"liste des services illisible ({e})"


def demarrer_services(pont, services=None, delai=DELAI_SERVICES_S, horloge=time.monotonic, dormir=time.sleep,
                      delai_appel=DELAI_APPEL_S):
    """« Démarrer les services de cartographie » : {ok, message, services, envoyes, duree_s}. N'envoie de 1001 que
    {"name": n, "switch": 1} pour un service arrêté de la liste blanche que le robot connaît."""
    demandes = services_demandes(services)          # ServiceInterdit avant tout envoi
    debut = horloge()
    if not demandes:
        return {"ok": True, "message": "Aucun service demandé : rien n'a été envoyé.", "services": {}, "envoyes": [],
                "duree_s": 0.0}
    if pont is None or not getattr(pont, "actif", False):
        return {"ok": False, "message": "Rien n'a été envoyé : ROS 2 n'est pas actif dans l'Atelier.",
                "services": {}, "envoyes": [], "duree_s": 0.0}
    liste, pourquoi = _liste(pont, delai_appel)
    if liste is None:
        return {"ok": False, "message": f"Rien n'a été envoyé : {pourquoi}. Vérifiez qu'il est relié, puis réessayez.",
                "services": {}, "envoyes": [], "duree_s": round(horloge() - debut, 2)}
    statuts = {s["name"]: s["status"] for s in liste}
    absents = [n for n in demandes if n not in statuts]
    a_demarrer = [n for n in demandes if n in statuts and statuts[n] != STATUT_ACTIF]
    envoyes, refus = [], []
    for nom in a_demarrer:
        try:
            code, data = pont.appeler_unitree("robot_state", 1001, parametre_service_switch(nom), delai_appel)
        except TimeoutError:
            envoyes.append({"name": nom, "ok": False, "raison": "pas de réponse"})
            refus.append(f"{nom} (pas de réponse)")
            continue
        if code != 0:
            envoyes.append({"name": nom, "ok": False, "code": code})
            refus.append(f"{nom} (code {code})")
            continue
        reussi, statut, raison = lire_reponse_switch(data)
        envoyes.append({"name": nom, "ok": reussi, "status": statut})
        if not reussi:
            refus.append(f"{nom} ({raison})")
    attendus = [e["name"] for e in envoyes if e["ok"]]
    # le statut rendu juste après 1001 n'est pas connu sur le vrai robot : on relit la liste
    while attendus:
        liste_bis, _ = _liste(pont, delai_appel)
        if liste_bis is not None:
            statuts = {s["name"]: s["status"] for s in liste_bis}
            if all(statuts.get(n) == STATUT_ACTIF for n in attendus):
                break
        if horloge() - debut >= delai:
            break
        dormir(PERIODE_SERVICES_S)
    duree = horloge() - debut
    actifs = [n for n in demandes if statuts.get(n) == STATUT_ACTIF]
    pas_actifs = [n for n in attendus if statuts.get(n) != STATUT_ACTIF]
    resultat = {"services": {n: statuts.get(n) for n in demandes}, "envoyes": envoyes, "duree_s": round(duree, 2)}
    if not a_demarrer and not absents:
        deja = (f"{'sont' if len(demandes) > 1 else 'est'} déjà "
                f"{accord_services(demandes, 'actif', 'active', 'actifs')}")
        return dict(resultat, ok=True, message=f"{majuscule(_les_services(demandes))} {deja} : rien n'a été envoyé.")
    morceaux = []
    if refus:          # en cas d'échec, les noms de l'appli Unitree aident à chercher (Services)
        morceaux.append(f"le robot a refusé de démarrer {noms_services(refus, technique=True)}")
    if pas_actifs:
        verbe = "ne sont" if len(pas_actifs) > 1 else "n'est"
        morceaux.append(f"{noms_services(pas_actifs, technique=True)} {verbe} pas encore "
                        f"{accord_services(pas_actifs, 'actif', 'active', 'actifs')} après {nombre(duree, 0)} s")
    if absents:
        morceaux.append(f"le robot n'a pas de service {liste_noms(f'« {n} »' for n in absents)}")
    if morceaux:
        texte = " ; ".join(morceaux)
        return dict(resultat, ok=False, message=(texte[0].upper() + texte[1:] + ". Regardez dans l'appli Unitree "
                                                 "Explore (Services), ou réessayez."))
    demarres = [n for n in a_demarrer if n in actifs]
    return dict(resultat, ok=True, message=(f"{majuscule(_les_services(demarres))} "
                                            f"{'ont' if len(demarres) > 1 else 'a'} démarré en {nombre(duree, 0)} s : "
                                            "le scan et le repérage peuvent marcher."))


def _les_services(noms):
    """« les services de cartographie » s'il s'agit des deux, sinon leurs noms en français (corrections de la vague
    6, revue de l'interface, défaut 16 : « lidar_driver et unitree_slam démarrés en 2 s » à l'écran)."""
    noms = list(noms)
    return "les services de cartographie" if sorted(noms) == sorted(SERVICES_CARTOGRAPHIE) else noms_services(noms)


def action_cable(action, contexte):
    """Les deux actions du câble par nmcli (jamais sudo) : {ok, message, commande}."""
    mots = list(COMMANDES_ACTIONS[action])
    commande = " ".join(mots)
    try:
        r = contexte.commande(mots, delai=DELAI_NMCLI_ACTION_S)
    except EssaisInterdits:
        return {"ok": False, "commande": commande,
                "message": "Pas pendant les essais : la connexion du câble n'a pas été touchée."}
    erreur = (r.erreur or r.sortie or "").strip().splitlines()
    fin = erreur[-1] if erreur else f"code {r.code}"
    if r.code == 0:
        if action == "retablir-cable":
            message = f"Connexion « {PROFIL_RESEAU} » rallumée : le PC reparle au robot par le câble."
        else:
            message = (f"La connexion « {PROFIL_RESEAU} » se rallumera seule à chaque branchement du câble ; le Wi-Fi "
                       "garde Internet.")
        return {"ok": True, "commande": commande, "message": message}
    if r.code == 127:
        message = "NetworkManager (nmcli) est introuvable sur ce PC : rien n'a été changé."
    elif "no such connection" in fin.lower() or "unknown connection" in fin.lower():
        message = (f"La connexion « {PROFIL_RESEAU} » n'existe pas : lancez une fois « source "
                   "~/robot-g1/setup/robot.sh » dans un terminal.")
    elif "not authorized" in fin.lower() or "insufficient privileges" in fin.lower():
        message = f"NetworkManager refuse sans mot de passe : dans un terminal, tapez « {commande} »."
    else:
        message = f"La commande a échoué ({fin[:160]}) : dans un terminal, essayez « {commande} »."
    return {"ok": False, "commande": commande, "message": message, "code": r.code}


def faire_action(action, mode="reel", pont=None, contexte=None, services=None):
    """Une action de ACTIONS_DIAGNOSTIC, déjà confirmée par l'utilisateur : {action, ok, message, …}.
    ActionInconnue, ActionImpossible ou ServiceInterdit (en français) avant tout envoi."""
    verifier_action(action, mode)
    if action == "demarrer-services":
        demandes = services_demandes(services)
        propre = None
        if pont is None:
            from . import demarrer_pont
            propre = pont = demarrer_pont()
        try:
            # un nœud neuf (g1-diagnostic) attend un peu plus la découverte du robot
            r = demarrer_services(pont, demandes, delai_appel=DELAI_APPEL_NOEUD_NEUF_S if propre else DELAI_APPEL_S)
        finally:
            if propre is not None:
                propre.arreter()
        return dict(r, action=action)
    if contexte is None:
        from .contexte import contexte_par_defaut
        contexte = contexte_par_defaut()
    return dict(action_cable(action, contexte), action=action)
