"""Contrat de la boîte noire (vague 6, section 13.3 du plan) : dossier d'une séance, sujets enregistrés, réglages.

Une séance s'ouvre quand on ouvre l'espace de travail en mode Réel (vrai robot ou répétition), et se ferme par
« Terminer la séance » ou à l'arrêt de l'Atelier. Tout ce qu'il faut pour comprendre ce qui s'est passé y est
gardé (dossier de la séance, ci-dessous), puis un rapport en français est écrit tout seul. Le code est celui de
l'agent Boîte noire (atelier/seance/) ; ce module ne contient que ce que plusieurs agents ont en commun.

Dossier : dossier_seances()/<AAAA-MM-JJ_HHhMM>/ (journaux/seances/ par défaut, jamais dans Git) :
    seance.json            manifeste (schéma seance), réécrit de façon atomique à chaque changement
    actions.jsonl          journal des actions : une ligne JSON par demande à l'Atelier (schéma action_seance)
    diagnostic_debut.json  le diagnostic à l'ouverture (schéma diagnostic) ; diagnostic_fin.json, facultatif ;
                           diagnostic_lancement.json : quand rien ne tournait à l'ouverture, le diagnostic pris
                           seul (lecture seule) une fois la répétition ou la navigation du robot lancée
    bag/                   l'enregistrement ROS 2 (rosbag2, stockage sqlite3) : metadata.yaml, bag_0.db3
    journaux/              serveur.log (le journal du serveur pendant la séance) et la fin des journaux des
                           commandes lancées par l'Atelier (atelier_<rôle>_*.log) ; journaux/jetson/ : le journal
                           du conteneur du Jetson, récupéré avant chaque « g1-jetson arreter » et à la fin
    lieu/                  copie des fichiers du lieu ouvert (lieu.yaml, salles, itinéraires, zones, carte de
                           l'étage) : le rapport dessine le trajet sur cette carte
    rapport.json, rapport.md, rapport.html, trajets.png   le rapport (à la fermeture, ou g1-seance rapport)
"""
import os
import re
from datetime import datetime
from pathlib import Path

import atelier

ETATS_SEANCE = ("ouverte", "fermee", "interrompue")
MODES_SEANCE = ("reel", "repetition")
OUVERTURES = ("auto", "manuel", "g1-seance")
FERMETURES = ("terminer", "arret_atelier", "g1-seance", "plantage",
              "simulation")      # corrections de la vague 6 : l'espace rouvert en Simulation termine la séance
ETATS_ENREGISTREMENT = ("demarrage", "en_cours", "arrete", "coupe", "absent", "erreur")
ETATS_RAPPORT = ("absent", "en_cours", "pret", "echec")
RAISONS_JOURNAL_JETSON = ("avant_arret", "fin", "manuel")

FORMAT_ID = "%Y-%m-%d_%Hh%M"         # + « -2 », « -3 »… si la minute est déjà prise (comme les scans)
MOTIF_ID_SEANCE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{2}h[0-9]{2}(-[0-9]{1,3})?$")
FICHIERS_SEANCE = {
    "manifeste": "seance.json", "actions": "actions.jsonl", "diagnostic_debut": "diagnostic_debut.json",
    "diagnostic_fin": "diagnostic_fin.json", "diagnostic_lancement": "diagnostic_lancement.json", "bag": "bag",
    "journaux": "journaux", "jetson": "journaux/jetson",
    "serveur": "journaux/serveur.log", "lieu": "lieu", "rapport_json": "rapport.json",
    "rapport_md": "rapport.md", "rapport_html": "rapport.html", "trajets": "trajets.png",
}

# Sujets enregistrés (rien d'autre) : sujet → fréquence maximale gardée dans le bag (Hz ; None : tout).
# Les types sont lus sur le graphe ROS 2 ; un sujet absent n'est pas une erreur (il apparaît s'il est publié).
SUJETS_SEANCE = {
    # navigation, pont et repérage
    "/cmd_vel": None, "/pont/etat": None, "/pont/arret": None, "/guide/etat": None, "/guide/evenement": None,
    "/guide/aller": None, "/guide/stop": None, "/reperage/etat": None, "/reperage/demander": None,
    "/speed_limit": None,
    # le robot (les sujets rapides à fréquence réduite)
    "/api/sport/request": None, "/api/sport/response": None, "/lf/sportmodestate": 10.0,
    "/state_estimator/odom_pelvis": 10.0, "/unitree/slam_relocation/odom": 10.0, "/odom": 10.0,
    "/lf/bmsstate": 1.0, "/api/arm/request": None, "/api/arm/response": None, "/api/voice/response": None,
    "/api/robot_state/request": None, "/api/robot_state/response": None,
    # répétition : la vérité terrain et l'état du faux G1
    "/g1_jumeau/odom": 10.0, "/g1_jumeau/etat": 1.0, "/g1_jumeau/panne": None, "/g1_jumeau/mode": None,
    "/faux_slam/panne": None,
    # pilotage, équipe, démo et voix
    "/pilotage/etat": 2.0, "/mouvement/maitre": None, "/visiteurs/detectes": 5.0, "/personnes/lidar": 2.0,
    "/personnalite/active": None, "/robot/dire": None, "/robot/geste": None, "/accueil/etat": 2.0,
    "/accueil/evenement": None, "/accueil/choix": None, "/accueil/commande": None, "/voix/etat": 2.0,
    "/voix/son": None, "/voix/commande": None, "/g1_jetson/etat": None, "/camera_poitrine/etat": None,
    # journaux de tous les nœuds (Nav2, pont, guide… y compris ceux du conteneur du Jetson)
    "/rosout": 50.0,
}
# Jamais enregistrés, même publiés sous un nom de la liste : nuages de points, images, son du robot
TYPES_JAMAIS = ("sensor_msgs/msg/PointCloud2", "sensor_msgs/msg/Image", "sensor_msgs/msg/CompressedImage")
SUJETS_JAMAIS = ("/api/voice/request",)      # les morceaux de son (96 ko) : la réponse suffit

REGLAGES_SEANCE = {
    "taille_max_mo": 1024,          # bag de la séance : au-delà, l'enregistrement s'arrête proprement (« coupe »)
    "place_libre_min_go": 2.0,      # place libre du disque sous laquelle l'enregistrement s'arrête
    "periode_controle_s": 5.0,      # contrôle de la taille et de la place libre
    "journal_max_mo": 20,           # fin d'un journal de commande copiée dans journaux/ (le reste est coupé)
    "cpu_max": 0.15,                # part d'un cœur que l'enregistrement ne doit pas dépasser (mesurée, 13.9)
    # corrections de la vague 6 (revue du code, défaut 9) : un client du réseau qui insiste ne remplit plus le disque
    "actions_max_mo": 50,           # actions.jsonl : au-delà, seuls l'ARRÊT, Bloquer, Débloquer et la séance
    "serveur_log_max_mo": 50,       # journaux/serveur.log de la séance : au-delà, plus rien (une ligne le dit)
    "resume_repetitions_s": 60,     # demandes refusées par une garde, rebonds de la borne, 429 : une ligne, puis
                                    # le nombre des suivantes du même client, par minute
}
VARIABLES_SEANCE = {
    "ATELIER_SEANCES": "dossier des séances (défaut : journaux/seances du projet)",
    "ATELIER_SEANCE_TAILLE_MAX_MO": "remplace taille_max_mo (essais)",
    "ATELIER_SEANCE_PLACE_MIN_GO": "remplace place_libre_min_go (essais : une valeur énorme coupe tout de suite)",
}

# Journal des actions : les demandes qui changent quelque chose, sous /api/ (accroche de main.py, 13.3)
METHODES_JOURNAL = ("POST", "PUT", "PATCH", "DELETE")
CHEMINS_IGNORES = ("/api/simulation/teleop",)   # flèches du robot simulé : 10 demandes par seconde
LIMITE_CORPS_OCTETS = 4096                      # corps de la demande et de la réponse gardés, au plus
GENRES_ACTION = ("arret", "bloquer", "debloquer", "y_aller", "stop", "reperer", "lancer", "arreter", "scan",
                 "pilotage", "choregraphie", "diagnostic", "seance", "demo", "borne", "voix", "lieu", "equipe",
                 "autre")


def dossier_seances():
    """Dossier des séances : $ATELIER_SEANCES, sinon ~/robot-g1/journaux/seances (créé au besoin)."""
    dossier = Path(os.environ.get("ATELIER_SEANCES") or atelier.dossier_journaux() / "seances").expanduser()
    dossier.mkdir(parents=True, exist_ok=True)
    return dossier


def id_seance(instant=None, existants=()):
    """Identifiant d'une séance ouverte à cet instant : AAAA-MM-JJ_HHhMM, ou -2, -3… si déjà pris."""
    base = (instant or datetime.now()).strftime(FORMAT_ID)
    if base not in existants:
        return base
    n = 2
    while f"{base}-{n}" in existants:
        n += 1
    return f"{base}-{n}"


def reglage(nom):
    """Valeur d'un réglage de REGLAGES_SEANCE, remplacée par sa variable d'environnement si elle existe."""
    variable = {"taille_max_mo": "ATELIER_SEANCE_TAILLE_MAX_MO",
                "place_libre_min_go": "ATELIER_SEANCE_PLACE_MIN_GO"}.get(nom)
    texte = os.environ.get(variable) if variable else None
    if texte:
        try:
            return float(texte)
        except ValueError:
            pass
    return REGLAGES_SEANCE[nom]


def action_journalisee(methode, chemin):
    """Vrai si une demande va dans actions.jsonl : POST, PUT, PATCH ou DELETE sous /api/, sauf les ignorées."""
    return (methode in METHODES_JOURNAL and chemin.startswith("/api/")
            and not any(chemin == c or chemin.startswith(c + "/") for c in CHEMINS_IGNORES))


def sujet_enregistre(sujet, type_ros=None):
    """Vrai si ce sujet (de ce type) va dans le bag d'une séance."""
    if sujet in SUJETS_JAMAIS or (type_ros is not None and type_ros in TYPES_JAMAIS):
        return False
    return sujet in SUJETS_SEANCE


EXEMPLE_SEANCE = {
    "version": 1, "id": "2026-11-12_14h03", "etat": "ouverte", "mode": "reel", "lieu": "seance", "etage": "rdc",
    "debut": "2026-11-12T14:03:02+01:00", "fin": None, "duree_s": None, "ouverture": "auto", "fermeture": None,
    "atelier": {"version": "0.1.0", "commit": "bc9ac58", "pid": 41234, "port": 8000},
    "enregistrement": {"etat": "en_cours", "pid": 41300, "octets": 1843200, "message": None,
                       "sujets": ["/guide/etat", "/pont/etat", "/api/sport/request", "/cmd_vel"]},
    "actions": 12, "diagnostic_debut": "diagnostic_debut.json",
    "jetson": [{"fichier": "journaux/jetson/conteneur_2026-11-12_14h40m12s_avant_arret.log",
                "t": "2026-11-12T14:40:12+01:00", "raison": "avant_arret", "octets": 532114, "ok": True}],
    "rapport": {"etat": "absent", "fichiers": [], "message": None, "date": None},
    "reglages": {"taille_max_mo": 1024, "place_libre_min_go": 2.0},
    "messages": [],
}
EXEMPLE_ACTION = {
    "version": 1, "t": "2026-11-12T14:05:41.218+01:00", "depuis_s": 159.2, "genre": "y_aller",
    "texte": "Y aller : b204", "methode": "POST", "chemin": "/api/guide/aller", "requete": {"cible": "b204"},
    "statut": 200, "reponse": {"cible": "b204", "abonnes": 1}, "duree_ms": 14.2, "mode": "reel", "client": "local",
    "source": "atelier",
}
