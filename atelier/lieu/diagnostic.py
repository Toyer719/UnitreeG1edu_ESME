"""Contrat du diagnostic « Vérifier le robot » (vague 6, section 13.2 du plan) : valeurs, formats et outils purs.

Le diagnostic contrôle tout d'un coup ce qui fait perdre du temps au début d'une séance avec le robot : câble,
adresse du PC, connexion « robot-g1 », réglages ROS, PC1, Jetson et LiDAR qui répondent, sujets du robot,
services de cartographie (robot_state), mode, batterie, Jetson (clé SSH, Docker, image, place, heure),
caméra. Chaque vérification dit OK, Attention, Problème ou Inconnu, avec UNE phrase qui dit quoi faire.

Le résultat suit le schéma « diagnostic » (atelier/lieu/schemas/diagnostic.schema.json) : il sort de
GET /api/robot/diagnostic, de g1-diagnostic --json et de diagnostic_debut.json d'une séance. Le code des
vérifications est celui de l'agent Diagnostic (atelier/diagnostic/) ; ce module ne contient que ce que
plusieurs agents doivent avoir en commun.

Services du robot (robot_state, SDK d'Unitree : unitree_sdk2py/go2/robot_state/ et
unitree_sdk2/include/unitree/robot/go2/robot_state/) : sujets /api/robot_state/request et /response
(unitree_api/Request, Response), version 1.0.0.1 :
  1003 ServiceList    parameter « {} » ; data : [{"name": "lidar_driver", "status": 1, "protect": 0}, …]
                      (ServiceStateData du SDK C++ : status et protect entiers ; sur ce G1 : status 0 = actif,
                      1 = arrêté) ;
  1001 ServiceSwitch  parameter {"name": "lidar_driver", "switch": 1} ; data {"name": …, "status": s}
                      (ServiceSwitchData) : 0 ou 1 réussi, 5 service protégé (erreur 5202 du SDK), autre valeur :
                      échec (5201).
L'Atelier ne démarre que les services de SERVICES_CARTOGRAPHIE et n'en arrête jamais aucun (switch toujours 1).
"""
import json
import re

# ---------------------------------------------------------------- états et vérifications

ETATS_VERIFICATION = ("ok", "attention", "probleme", "inconnu")
# Gravité, pour l'état global (le pire) : un « inconnu » (rien pu vérifier) pèse moins qu'une attention
GRAVITE = {"ok": 0, "inconnu": 1, "attention": 2, "probleme": 3}
GROUPES_DIAGNOSTIC = {"reseau": "Câble et réseau", "robot": "Robot", "jetson": "Jetson"}

# Vérifications connues (id → groupe, titre affiché). L'agent Diagnostic peut en ajouter (même forme d'id).
VERIFICATIONS = {
    "cable": ("reseau", "Câble du robot"),
    "adresse": ("reseau", "Adresse du PC sur le câble"),
    "profil": ("reseau", "Connexion « robot-g1 »"),
    "ros": ("reseau", "Réglages ROS de l'Atelier"),
    "pc1": ("reseau", "Ordinateur de marche (PC1)"),
    "jetson": ("reseau", "Jetson"),
    "lidar": ("reseau", "LiDAR"),
    "sujets": ("robot", "Le robot parle au PC"),
    "services": ("robot", "Services de cartographie"),
    "mode": ("robot", "Mode du robot"),
    "batterie": ("robot", "Batterie"),
    "jetson_ssh": ("jetson", "Clé SSH du Jetson"),
    "jetson_docker": ("jetson", "Docker sur le Jetson"),
    "jetson_image": ("jetson", "Image du conteneur"),
    "jetson_place": ("jetson", "Place libre sur le Jetson"),
    "jetson_horloge": ("jetson", "Heure du Jetson"),
    "camera": ("jetson", "Caméra de poitrine"),
}
# En répétition (faux G1, sans robot), seules celles-ci ont un sens ; les autres vont dans « ignorees »
VERIFICATIONS_REPETITION = ("ros", "sujets", "services", "mode", "batterie")
MOTIF_ID_VERIFICATION = re.compile(r"^[a-z][a-z0-9_]{0,39}$")

# ---------------------------------------------------------------- actions (liste blanche)

# Seulement sur un clic, avec confirmation (champ « confirme » de la demande), jamais automatiques.
ACTIONS_DIAGNOSTIC = {
    "demarrer-services": {
        "libelle": "Démarrer les services de cartographie",
        "confirmation": ("Démarrer lidar_driver et unitree_slam sur le robot ? Ils servent au scan et au "
                         "repérage. Le robot ne bouge pas."),
        "verification": "services"},
    "retablir-cable": {
        "libelle": "Rétablir la connexion du câble",
        "confirmation": "Rallumer la connexion « robot-g1 » du câble Ethernet ? Le Wi-Fi n'est pas touché.",
        "verification": "profil"},
    "cable-automatique": {
        "libelle": "La rétablir seule à chaque branchement",
        "confirmation": ("Rallumer seule la connexion « robot-g1 » à chaque branchement du câble ? Le PC "
                         "garde Internet par le Wi-Fi. On peut revenir en arrière avec robot.sh."),
        "verification": "profil"},
}
SERVICES_CARTOGRAPHIE = ("lidar_driver", "unitree_slam")     # les seuls que l'Atelier démarre
SERVICE_ROBOT_STATE = "robot_state"                         # /api/robot_state/request et /response
SUJET_ROBOT_STATE = "/api/robot_state"
VERSION_API_ROBOT_STATE = "1.0.0.1"
API_ROBOT_STATE = {"service_switch": 1001, "report_freq": 1002, "service_list": 1003}
STATUT_ACTIF = 0                # status d'un service dans la liste 1003 (ce G1 : 0 actif, 1 arrêté)
STATUT_ARRETE = 1
STATUT_PROTEGE = 5              # réponse de 1001 : service protégé
ERREUR_SWITCH = 5201            # codes du SDK (robot_state_api.py)
ERREUR_PROTEGE = 5202
# Appels au robot permis au serveur et à g1-diagnostic (PontRos.appeler_unitree) : rien d'autre ne part
APPELS_UNITREE_PERMIS = frozenset({("robot_state", 1003), ("robot_state", 1001), ("sport", 7001)})

# Connexion NetworkManager du câble (setup/robot.sh) et commandes des deux actions du câble
PROFIL_RESEAU = "robot-g1"
COMMANDES_ACTIONS = {
    "retablir-cable": ("nmcli", "connection", "up", PROFIL_RESEAU),
    "cable-automatique": ("nmcli", "connection", "modify", PROFIL_RESEAU, "connection.autoconnect", "yes"),
}
ADRESSES_ROBOT = {"pc": "192.168.123.99", "pc1": "192.168.123.161", "jetson": "192.168.123.164",
                  "lidar": "192.168.123.120"}
# Sujets que le robot publie toujours, puis ceux du SLAM (présents si unitree_slam tourne)
SUJETS_ROBOT = ("/api/sport/request", "/lf/sportmodestate", "/state_estimator/odom_pelvis")
SUJETS_SLAM = ("/api/slam_operate/request",)

# Délais (secondes)
DELAI_DIAGNOSTIC_S = 15.0       # tout le diagnostic, au plus
DELAI_APPEL_S = 2.0             # une requête robot_state ou 7001
DELAI_SERVICES_S = 20.0         # « Démarrer les services » : jusqu'à ce que la liste les dise actifs
BATTERIE_ATTENTION = 30         # % : en dessous, Attention ; sous BATTERIE_PROBLEME, Problème
BATTERIE_PROBLEME = 15
PLACE_JETSON_MIN_GO = 5.0       # place libre sur le Jetson sous laquelle on prévient
ECART_HORLOGE_MAX_S = 2.0       # écart d'horloge PC / Jetson toléré

# Tests : un fichier JSON de résultats simulés des vérifications système (section 13.2)
VARIABLE_FAUX = "ATELIER_DIAGNOSTIC_FAUX"


# ---------------------------------------------------------------- requêtes et réponses de robot_state

def parametre_service_list():
    """parameter de 1003 ServiceList."""
    return "{}"


def parametre_service_switch(nom):
    """parameter de 1001 ServiceSwitch pour DÉMARRER un service de la liste blanche (switch toujours 1).
    ValueError pour tout autre service : l'Atelier n'en démarre pas d'autre, et n'en arrête jamais."""
    if nom not in SERVICES_CARTOGRAPHIE:
        raise ValueError(f"service « {nom} » interdit : l'Atelier ne démarre que "
                         f"{' et '.join(SERVICES_CARTOGRAPHIE)}")
    return json.dumps({"name": nom, "switch": 1})


def _json(data):
    if isinstance(data, (list, dict)):
        return data
    try:
        return json.loads(data)
    except (TypeError, ValueError):
        raise ValueError(f"réponse illisible (JSON attendu) : {str(data)[:80]!r}") from None


def lire_liste_services(data):
    """Liste des services de la réponse de 1003 : [{"name", "status", "protect"}] (protect lu en booléen : le SDK
    C++ l'écrit en entier, 0 ou 1). ValueError si elle est mal formée (format du SDK ; à vérifier sur le vrai G1,
    section 13.10)."""
    d = _json(data)
    if not isinstance(d, list):
        raise ValueError("liste des services : une liste JSON attendue")
    services = []
    for s in d:
        if not isinstance(s, dict) or not isinstance(s.get("name"), str) or isinstance(s.get("status"), bool) \
                or not isinstance(s.get("status"), int):
            raise ValueError(f"liste des services : élément mal formé {str(s)[:80]}")
        services.append({"name": s["name"], "status": s["status"], "protect": bool(s.get("protect", False))})
    return services


def lire_reponse_switch(data):
    """(réussi, status, raison) d'après data de la réponse de 1001, comme le SDK : status 0 ou 1 réussi,
    5 protégé, autre valeur échec. raison : None, ou une phrase en français."""
    d = _json(data)
    statut = d.get("status") if isinstance(d, dict) else None
    if isinstance(statut, bool) or not isinstance(statut, int):
        return False, None, "réponse du robot sans « status »"
    if statut in (STATUT_ACTIF, STATUT_ARRETE):
        return True, statut, None
    if statut == STATUT_PROTEGE:
        return False, statut, "service protégé : le robot refuse de le changer"
    return False, statut, f"le robot n'a pas pu changer le service (status {statut})"


def services_arretes(services, noms=SERVICES_CARTOGRAPHIE):
    """Noms des services de « noms » qui ne sont pas actifs (absents de la liste compris), dans l'ordre."""
    statuts = {s["name"]: s["status"] for s in services}
    return [n for n in noms if statuts.get(n) != STATUT_ACTIF]


# ---------------------------------------------------------------- résultat d'un diagnostic

def verification(ident, etat, detail, conseil=None, action=None, titre=None, groupe=None, technique=None,
                 duree_s=None, donnees=None):
    """Une vérification au format du schéma. titre et groupe : ceux de VERIFICATIONS par défaut. ValueError si
    l'état, l'action ou l'id sont hors contrat, ou s'il manque le conseil d'un état qui n'est pas ok."""
    if not MOTIF_ID_VERIFICATION.match(str(ident)):
        raise ValueError(f"id de vérification mal formé : {ident!r}")
    if etat not in ETATS_VERIFICATION:
        raise ValueError(f"état « {etat} » inconnu ({', '.join(ETATS_VERIFICATION)})")
    if action is not None and action not in ACTIONS_DIAGNOSTIC:
        raise ValueError(f"action « {action} » inconnue ({', '.join(ACTIONS_DIAGNOSTIC)})")
    if etat != "ok" and not conseil:
        raise ValueError(f"vérification « {ident} » ({etat}) : il faut une phrase qui dit quoi faire")
    defaut = VERIFICATIONS.get(ident, ("robot", ident))
    v = {"id": ident, "groupe": groupe or defaut[0], "titre": titre or defaut[1], "etat": etat,
         "detail": str(detail), "conseil": conseil or None, "action": action}
    if technique is not None:
        v["technique"] = str(technique)[:500]
    if duree_s is not None:
        v["duree_s"] = round(float(duree_s), 3)
    if donnees is not None:
        v["donnees"] = donnees
    return v


def etat_global(verifications):
    """Le pire état des vérifications (ok si la liste est vide)."""
    return max((v["etat"] for v in verifications), key=GRAVITE.__getitem__, default="ok")


def resume(verifications):
    """{ok, attention, probleme, inconnu} : le nombre de vérifications dans chaque état."""
    compte = {e: 0 for e in ETATS_VERIFICATION}
    for v in verifications:
        compte[v["etat"]] += 1
    return compte


def message_global(verifications):
    """Une phrase : tout va bien, ou le conseil de la vérification la plus grave (la première à gravité égale)."""
    pires = [v for v in verifications if v["etat"] in ("probleme", "attention")]
    if not pires:
        inconnus = sum(1 for v in verifications if v["etat"] == "inconnu")
        if inconnus:
            return f"Tout ce qui a pu être vérifié va bien ({inconnus} vérification(s) impossible(s) pour le moment)."
        return "Tout va bien : le robot est prêt."
    pire = max(pires, key=lambda v: GRAVITE[v["etat"]])
    nombre = len(pires)
    debut = "Un point à régler" if nombre == 1 else f"{nombre} points à régler"
    return f"{debut} : {pire['titre']}. {pire['conseil']}"


def diagnostic(verifications, mode, date, duree_s, ignorees=(), source=None, faux=None):
    """Le résultat complet (schéma diagnostic) à partir des vérifications faites."""
    d = {"version": 1, "date": date, "mode": mode, "duree_s": round(float(duree_s), 3),
         "etat": etat_global(verifications), "resume": resume(verifications),
         "message": message_global(verifications), "verifications": list(verifications),
         "ignorees": [dict(x) for x in ignorees],
         "actions": sorted({v["action"] for v in verifications if v.get("action")})}
    if source is not None:
        d["source"] = source
    if faux is not None:
        d["faux"] = bool(faux)
    return d


def code_de_sortie(resultat):
    """Code de sortie de g1-diagnostic : 0 si rien n'est en Attention ni en Problème, 1 sinon."""
    return 0 if resultat["etat"] in ("ok", "inconnu") else 1


EXEMPLE_DIAGNOSTIC = diagnostic([
    verification("cable", "ok", "Câble branché sur eno2.", technique="interface eno2, porteuse 1", duree_s=0.002),
    verification("adresse", "ok", "Le PC a l'adresse 192.168.123.99 sur le câble.", duree_s=0.001),
    verification("profil", "attention", "La connexion « robot-g1 » ne se rallume pas seule au branchement.",
                 conseil="Cliquez sur « La rétablir seule à chaque branchement » pour ne plus avoir à lancer robot.sh.",
                 action="cable-automatique", technique="nmcli : connection.autoconnect no", duree_s=0.08),
    verification("pc1", "ok", "Le PC1 répond en 0,6 ms.", duree_s=0.01),
    verification("sujets", "ok", "Le PC voit les sujets du robot (marche, odométrie).", duree_s=0.02),
    verification("services", "probleme", "lidar_driver et unitree_slam sont arrêtés.",
                 conseil="Cliquez sur « Démarrer les services de cartographie » : sans eux, ni scan ni repérage.",
                 action="demarrer-services", technique="robot_state 1003 : lidar_driver 1, unitree_slam 1",
                 duree_s=0.41, donnees={"services": [{"name": "lidar_driver", "status": 1, "protect": False},
                                                     {"name": "unitree_slam", "status": 1, "protect": False}]}),
    verification("batterie", "inconnu", "Pas encore de nouvelles de la batterie.",
                 conseil="Attendez quelques secondes, puis « Vérifier à nouveau ».", duree_s=2.0),
], mode="reel", date="2026-11-12T14:03:05+01:00", duree_s=4.2,
    ignorees=[{"id": "camera", "raison": "le conteneur du Jetson ne tourne pas"}], source="atelier")
