"""Le comportement du guide (vague 4, section 11.4 du plan) : états, événements, délais, demandes.

  - /guide/etat : états de la vague 1 (attente, en_route, bloque, detour, arrive, echec) et de la
    vague 4 (retour, attente_passage, attente_visiteur, perdu) ; champs mission, accompagner,
    visiteur et depuis_s en plus (schéma etat_guide, compatible avec les messages d'avant) ; champ
    facultatif immobilise (RAISONS_IMMOBILE, correction du 01/11/2026, section 12.15 du plan) ;
  - /guide/evenement : messages au visiteur {version, code, texte, salle?, ...} (schéma
    evenement_guide), que la partie voix de l'équipe dit ; codes et textes par défaut :
    CODES_EVENEMENT, et evenement(code, ...) fabrique un message conforme ;
  - /guide/aller : l'id simple d'avant, ou du JSON {cible, accompagner?, retour?, source?} (schéma
    demande_guide) ; lire_demande_aller(texte) lit les deux ;
  - délais et distances : DELAIS_GUIDE, réglables par lieu (section guide de lieu.yaml,
    reglages_guide) ou par paramètre ROS du nœud guide.

Fichier de l'agent Comportement du guide (vague 4). Les fonctions et valeurs marquées « contrat »
sont livrées et testées par l'intégrateur (atelier/tests/test_contrats_vague4.py) : elles gardent
leur nom, leurs arguments et leur comportement.
"""
import json
from datetime import datetime

from .fichiers import charger_fiche
from .modeles import Lieu

# ---------------------------------------------------------------- valeurs du contrat

ETATS_GUIDE_V1 = ("attente", "en_route", "bloque", "detour", "arrive", "echec")
ETATS_GUIDE = ETATS_GUIDE_V1 + ("retour", "attente_passage", "attente_visiteur", "perdu")
ETATS_FINAUX_VISITE = ("arrive", "echec")          # fin d'une visite (le retour vient après)
ETATS_EN_MISSION = ("en_route", "retour", "bloque", "detour", "attente_passage", "attente_visiteur", "perdu")
MISSIONS = ("visite", "retour")

# Textes par défaut des événements ; {nom} : nom de la salle visée (salles.yaml)
CODES_EVENEMENT = {
    "depart": "Suivez-moi, je vous emmène à {nom}.",
    "seul": "Je ne vous vois pas derrière moi : je pars vers {nom}, suivez-moi.",
    "ralentir": "Je ralentis pour vous attendre.",
    "attente_visiteur": "Je vous attends.",
    "visiteur_retrouve": "Vous voilà ! Continuons.",
    "visiteur_perdu": "Je ne vous vois plus. Je retourne à l'accueil.",
    "passant_gene": "Pardon, puis-je passer ?",
    "passage_libre": "Merci !",
    "detour": "Le passage est encombré : je prends un autre chemin.",
    "arrivee": "Nous sommes arrivés : voici {nom}.",
    "retour": "Je retourne à l'accueil.",
    "retour_arrive": "Je suis de retour à l'accueil.",
    "perdu": "Je me suis un peu perdu : un instant, s'il vous plaît.",
    "retrouve": "C'est bon, je sais de nouveau où je suis.",
    "echec": "Désolé, je ne peux pas vous y emmener. Demandez de l'aide à l'accueil.",
    "arret": "Je m'arrête.",
    "pilotage": "Je suis piloté à la main pour le moment.",
    # correction du 01/11/2026 (section 12.15) : robot bloqué, pas en mode marche, muet ou qui refuse
    # de marcher : le trajet est annulé (ou « Y aller » refusé), champ raison (RAISONS_IMMOBILE)
    "immobilise": "Je ne peux pas bouger pour le moment.",
}
# Ce qui immobilise le robot (événement immobilise, champ raison ; champ immobilise de /guide/etat) :
# verrou du pont (/pont/arret : Bloquer, ARRÊT, ligne de commande), mode du robot qui n'est pas la marche
# (pas_en_marche), robot qui ne répond plus (robot_muet) ou qui refuse de marcher (refus)
RAISONS_IMMOBILE = ("verrou", "pas_en_marche", "robot_muet", "refus")

# Délais et distances par défaut (section guide de lieu.yaml, schéma lieu)
DELAIS_GUIDE = {
    "retour_auto": True,            # retour seul au point principal après chaque visite
    "delai_avant_retour_s": 15.0,   # temps passé à destination avant le retour
    "delai_visiteur_s": 30.0,       # attente du visiteur qui ne suit plus, avant d'abandonner
    "distance_ralentir_m": 2.0,     # visiteur plus loin : le robot ralentit
    "distance_attendre_m": 3.5,     # visiteur plus loin (ou plus vu depuis 2 s) : le robot l'attend
    "ralenti": 0.5,                 # fraction de la vitesse quand le visiteur traîne (/speed_limit)
    "delai_perdu_s": 30.0,          # robot perdu : attente avant l'échec
    "delai_passant_s": 20.0,        # passant qui bouche : attente avant de déclarer le couloir bloqué
}
DELAI_VISITEUR_DEPART_S = 3.0       # au départ : le visiteur doit être vu dans ce temps (sinon « seul »)
DISTANCE_VISITEUR_DEPART_M = 2.5    # au départ : personne vue à moins de cela du robot
DELAI_VISITEUR_INVISIBLE_S = 2.0    # plus vu depuis ce temps : le robot l'attend
TOLERANCE_RETOUR_M = 0.3            # retour au point principal : position
TOLERANCE_RETOUR_RAD = 0.1745       # et orientation (10°)

SUJET_EVENEMENT = "/guide/evenement"
SUJET_PERSONNES = "/personnes/lidar"          # détecteur de personnes au LiDAR (nœud detecteur_personnes)
SUJET_FAUX_VISITEUR = "/faux_visiteur/mode"   # std_msgs/String, simulation seulement
SUJET_LIMITE_VITESSE = "/speed_limit"         # nav2_msgs/SpeedLimit, en pourcentage : au guide seul
MODES_FAUX_VISITEUR = ("suivre", "trainer", "partir", "arreter")

EXEMPLE_ETAT_GUIDE = {
    "version": 1, "etat": "attente_visiteur", "cible": "b204", "reste_m": 9.4,
    "itineraire": ["accueil", "hall_nord", "amphi", "couloir_nord_1", "b204"],
    "message": "Le visiteur ne suit plus : le robot l'attend (30 s au plus).",
    "mission": "visite", "accompagner": True, "visiteur": {"vu": False, "distance_m": None, "age_s": 2.4},
    "depuis_s": 1.2}
EXEMPLE_EVENEMENT = {"version": 1, "code": "depart", "texte": "Suivez-moi, je vous emmène à Salle B204.",
                     "salle": "b204", "nom": "Salle B204", "mission": "visite",
                     "temps": "2026-10-26T10:00:00+01:00"}
EXEMPLE_DEMANDE_ALLER = {"cible": "b204", "accompagner": True, "source": "dialogue"}
EXEMPLE_PERSONNES = {
    "version": 1, "source": "lidar", "temps": 812.4,
    "personnes": [{"id": 3, "x": -1.1, "y": 0.2, "distance_m": 1.12, "angle_rad": 2.96, "confiance": 0.8,
                   "vx": 0.4, "vy": 0.0, "x_map": 1.4, "y_map": 10.2, "rayon_m": 0.24, "derriere": True}]}


# ---------------------------------------------------------------- contrat (livré par l'intégrateur)

def reglages_guide(lieu=None, **parametres):
    """Contrat. Délais et distances du guide : DELAIS_GUIDE, puis la section guide de lieu.yaml
    (lieu : Lieu, id, dossier ou None), puis les paramètres donnés (ceux du nœud ROS, None ignoré)."""
    reglages = dict(DELAIS_GUIDE)
    if lieu is not None:
        fiche = lieu if isinstance(lieu, Lieu) else charger_fiche(lieu)
        reglages.update(fiche.guide or {})
    reglages.update({k: v for k, v in parametres.items() if v is not None and k in DELAIS_GUIDE})
    return reglages


def lire_demande_aller(texte):
    """Contrat. Lit /guide/aller : un id simple (« b204 », format d'avant) ou du JSON (schéma
    demande_guide). Renvoie {cible, accompagner, retour, source} ; un id simple donne une visite sans
    accompagnement (accompagner False), retour None (réglage du lieu). ValueError (en français) si
    le JSON est faux."""
    from .validation import valider_donnees
    texte = str(texte).strip()
    if not texte.startswith("{"):
        return {"cible": texte, "accompagner": False, "retour": None, "source": None}
    try:
        donnees = json.loads(texte)
    except ValueError as e:
        raise ValueError(f"/guide/aller : JSON illisible ({e})") from None
    erreurs = valider_donnees("demande_guide", donnees)
    if erreurs:
        raise ValueError("; ".join(erreurs))
    return {"cible": donnees["cible"], "accompagner": donnees.get("accompagner", True),
            "retour": donnees.get("retour"), "source": donnees.get("source")}


def texte_evenement(code, nom=None, phrases=None):
    """Contrat. Texte d'un événement : celui de phrases (ex. d'une personnalité) s'il y est, sinon
    CODES_EVENEMENT ; {nom} remplacé par nom (ou « la destination »). KeyError si le code est inconnu."""
    modele = (phrases or {}).get(code) or CODES_EVENEMENT[code]
    return modele.replace("{nom}", nom or "la destination")


def evenement(code, salle=None, nom=None, texte=None, mission=None, phrases=None):
    """Contrat. Message /guide/evenement conforme au schéma evenement_guide. texte : celui à dire,
    sinon texte_evenement(code, nom, phrases)."""
    if code not in CODES_EVENEMENT:
        raise KeyError(f"code d'événement inconnu : {code} (codes : {', '.join(CODES_EVENEMENT)})")
    message = {"version": 1, "code": code, "texte": texte or texte_evenement(code, nom, phrases),
               "salle": salle, "mission": mission, "temps": datetime.now().astimezone().isoformat(timespec="seconds")}
    if nom:
        message["nom"] = nom
    return message


__all__ = ["CODES_EVENEMENT", "DELAIS_GUIDE", "DELAI_VISITEUR_DEPART_S", "DELAI_VISITEUR_INVISIBLE_S",
           "DISTANCE_VISITEUR_DEPART_M", "ETATS_EN_MISSION", "ETATS_FINAUX_VISITE", "ETATS_GUIDE", "ETATS_GUIDE_V1",
           "EXEMPLE_DEMANDE_ALLER", "EXEMPLE_ETAT_GUIDE", "EXEMPLE_EVENEMENT", "EXEMPLE_PERSONNES", "MISSIONS",
           "MODES_FAUX_VISITEUR", "RAISONS_IMMOBILE", "SUJET_EVENEMENT", "SUJET_FAUX_VISITEUR",
           "SUJET_LIMITE_VITESSE", "SUJET_PERSONNES", "TOLERANCE_RETOUR_M", "TOLERANCE_RETOUR_RAD", "evenement",
           "lire_demande_aller", "reglages_guide", "texte_evenement"]
