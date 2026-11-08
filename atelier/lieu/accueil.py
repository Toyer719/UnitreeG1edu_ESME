"""Contrat de la démo d'accueil et de la borne (vague 6, sections 13.4 et 13.5 du plan).

La démo : un visiteur s'approche du robot (ou touche la borne), le robot le salue, le visiteur choisit une salle
sur la borne (ou plus tard en parlant au chatbot de l'équipe), le robot l'y accompagne, annonce l'arrivée, puis
revient seul à l'accueil. Le nœud « accueil » (paquet g1_accueil) mène cette machine d'états ; la borne est une
page de l'Atelier (/borne) pour une tablette ou un téléphone du même réseau. Le code est celui de l'agent Borne et
orchestrateur ; ce module ne contient que ce qui est partagé (nœud, serveur, borne, chatbot, boîte noire) :

  - les états de la démo (ETATS_DEMO) et ce que la borne montre pour chacun (ecran_borne) ;
  - les sujets ROS 2 (SUJETS_ACCUEIL) et les messages d'entrée (message_choix, message_commande) ;
  - les salles proposées par la borne (salles_de_la_borne, refus_choix) : jamais le point principal, jamais une
    salle qui porte l'étiquette « hors_borne » ;
  - le fichier facultatif du lieu demo.yaml (schéma demo) : charger_demo, enregistrer_demo, reglages_demo.

Règle de sécurité (vague 5, section 12.15) : après un arrêt, un blocage ou une panne, la démo se met en PAUSE et
ne repart jamais seule ; il faut « Reprendre » (et, si le robot n'est pas à l'accueil, « Ramener à l'accueil »).
Ce module ne dépend que de la bibliothèque standard et d'atelier.lieu (Python du système compris).
"""
import copy
from datetime import datetime

from .fichiers import ErreurLieu, charger_fichier, dossier_lieu, ecrire_yaml
from .validation import valider_donnees

# ---------------------------------------------------------------- états de la démo (nœud accueil)

ETATS_DEMO = ("demarrage", "attente", "salutation", "choix", "depart", "accompagnement", "arrivee", "retour",
              "occupe", "pause")
ETATS_CHOIX_POSSIBLE = ("attente", "salutation", "choix")          # un choix de salle y est accepté
ETATS_VISITE = ("depart", "accompagnement", "arrivee")             # une visite de la démo est en cours
RAISONS_PAUSE = ("arret", "verrou", "pas_en_marche", "robot_muet", "refus", "pont_absent", "echec", "perdu",
                 "pilotage", "guide_absent", "operateur")
CODES_EVENEMENT_DEMO = ("demarree", "visiteur", "salutation", "choix_accepte", "choix_refuse", "depart", "arrivee",
                        "retour", "retour_arrive", "visite_abandonnee", "visite_echouee", "delai_choix", "occupe",
                        "libre", "pause", "reprise", "commande_acceptee", "commande_refusee", "arretee")
RAISONS_REFUS = ("occupe", "pause", "salle_inconnue", "salle_cachee", "autre_etage", "deja_la", "demo_arretee",
                 "action_impossible")
ACTIONS_COMMANDE = ("appui", "annuler", "pause", "reprendre", "ramener", "remise_a_zero")
ACTIONS_OPERATEUR_BORNE = ("pause", "reprendre", "ramener")        # les seules que la borne permet (code opérateur)
SOURCES_ACCUEIL = ("borne", "dialogue", "atelier", "operateur", "test")
SOURCES_VISITEURS = ("auto", "camera", "lidar", "borne")

NOEUD_ACCUEIL = "accueil"                       # nom du nœud ROS 2 (paquet g1_accueil, exécutable accueil)
SUJETS_ACCUEIL = {                              # sujet → (type, schéma, sens vu du nœud accueil)
    "/accueil/etat": ("std_msgs/String", "etat_demo", "sortie"),
    "/accueil/evenement": ("std_msgs/String", "evenement_demo", "sortie"),
    "/accueil/choix": ("std_msgs/String", "choix_accueil", "entree"),
    "/accueil/commande": ("std_msgs/String", "commande_accueil", "entree"),
}
PERIODE_ETAT_S = 0.5                            # /accueil/etat : 2 fois par seconde, et à chaque changement
DELAI_ETAT_PERIME_S = 3.0                       # plus vieux : la démo est tenue pour arrêtée (serveur, borne)
DELAI_REPONSE_S = 2.0                           # choix ou commande → événement acceptée / refusée, au plus
REGLAGES_DEMO = {                               # valeurs par défaut (demo.yaml, puis paramètres du nœud)
    "source_visiteurs": "auto", "distance_visiteur_m": 1.5, "presence_s": 1.0, "delai_choix_s": 45.0,
    "delai_depart_s": 10.0, "delai_entre_visiteurs_s": 8.0, "accompagner": True, "retour": True,
    "relayer_evenements": True, "saluer_geste": True, "suivre_pont": True, "distance_principal_m": 0.5,
}

# ---------------------------------------------------------------- borne

ECRANS_BORNE = ("hors_service", "salles", "suivez_moi", "arrivee", "retour", "occupe", "pause")
ECRAN_DE_L_ETAT = {"demarrage": "hors_service", "attente": "salles", "salutation": "salles", "choix": "salles",
                   "depart": "suivez_moi", "accompagnement": "suivez_moi", "arrivee": "arrivee", "retour": "retour",
                   "occupe": "occupe", "pause": "pause"}
TEXTES_BORNE = {                                # phrase principale de chaque écran (demo.yaml peut changer « salles »)
    "hors_service": "Le robot se prépare. Revenez dans un instant !",
    "salles": "Bonjour ! Où voulez-vous aller ?",
    "suivez_moi": "Suivez-moi !",
    "arrivee": "Nous sommes arrivés.",
    "retour": "Je retourne à l'accueil.",
    "occupe": "Je suis occupé. Je reviens dans un instant !",
    "pause": "Je fais une petite pause.",
}
ETIQUETTE_HORS_BORNE = "hors_borne"             # étiquette d'une salle (salles.yaml) que la borne ne propose pas
PICTOGRAMMES_BORNE = ("toilettes", "sortie", "cafeteria", "cdi", "infirmerie", "secretariat", "ascenseur", "labo",
                      "gymnase", "amphi")       # étiquettes qui donnent un petit dessin à la carte de la salle
ENTETE_JETON_BORNE = "X-Jeton-Borne"            # mode opérateur : jeton rendu par POST /api/borne/operateur
DUREE_JETON_OPERATEUR_S = 300.0
ESSAIS_CODE_MAX = 5                             # mauvais codes permis par fenêtre de DUREE_BLOCAGE_CODE_S
DUREE_BLOCAGE_CODE_S = 300.0
ANTI_REBOND_S = 0.6                             # deux appuis plus proches comptent pour un (page et serveur)
# Chemins permis à un client qui n'est pas ce PC, quand l'Atelier écoute le réseau (main.py, section 13.5)
CHEMINS_BORNE = ("/borne", "/borne/")
PREFIXES_BORNE = ("/js/borne/", "/api/borne/", "/ws/borne", "/api/voix/son/")
FICHIERS_BORNE = ("/borne.html", "/css/theme.css", "/css/borne.css", "/favicon.ico")


def ecran_borne(etat_demo):
    """Écran de la borne pour un message de /accueil/etat (None, ou démo arrêtée : hors_service)."""
    if not isinstance(etat_demo, dict):
        return "hors_service"
    return ECRAN_DE_L_ETAT.get(etat_demo.get("etat"), "hors_service")


def chemin_permis_borne(chemin):
    """Vrai si un client distant (la tablette de la borne) peut demander ce chemin."""
    return chemin in CHEMINS_BORNE or chemin in FICHIERS_BORNE or chemin.startswith(PREFIXES_BORNE)


def _champ(salle, nom, defaut=None):
    return salle.get(nom, defaut) if isinstance(salle, dict) else getattr(salle, nom, defaut)


def salles_de_la_borne(salles, id_principal, etage=None, noms_etages=None):
    """Salles que la borne propose, dans l'ordre de salles.yaml : ni le point principal, ni celles qui portent
    l'étiquette hors_borne. salles : objets Salle ou dicts de salles.yaml ; etage : l'étage de la démo (une salle
    d'un autre étage est montrée, mais pas accessible) ; noms_etages : {id: nom}. Renvoie des dicts
    {id, nom, etage, nom_etage, etiquettes, accessible, pictogramme}."""
    noms_etages = noms_etages or {}
    proposees = []
    for s in salles:
        etiquettes = list(_champ(s, "etiquettes", []) or [])
        if _champ(s, "id") == id_principal or ETIQUETTE_HORS_BORNE in etiquettes:
            continue
        etage_salle = _champ(s, "etage")
        proposees.append({
            "id": _champ(s, "id"), "nom": _champ(s, "nom"), "etage": etage_salle,
            "nom_etage": noms_etages.get(etage_salle, etage_salle), "etiquettes": etiquettes,
            "accessible": etage is None or etage_salle == etage,
            "pictogramme": next((e for e in etiquettes if e in PICTOGRAMMES_BORNE), None)})
    return proposees


def refus_choix(id_salle, salles, id_principal, etage=None):
    """None si la salle peut être choisie à la borne, sinon (raison, phrase) : raison de RAISONS_REFUS.
    salles : toutes les salles du lieu (objets Salle ou dicts)."""
    toutes = {_champ(s, "id"): s for s in salles}
    if id_salle == id_principal:
        return "deja_la", "Nous sommes déjà à l'accueil."
    if id_salle not in toutes:
        return "salle_inconnue", "Cette salle n'existe pas dans ce lieu."
    salle = toutes[id_salle]
    if ETIQUETTE_HORS_BORNE in (_champ(salle, "etiquettes", []) or []):
        return "salle_cachee", "Cette salle n'est pas proposée par la borne."
    if etage is not None and _champ(salle, "etage") != etage:
        return "autre_etage", f"« {_champ(salle, 'nom')} » est à un autre étage : demandez à l'accueil."
    return None


def maintenant_iso():
    """Heure locale ISO 8601 avec décalage, à la seconde."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def message_choix(salle, source, ident=None, texte=None, accompagner=None):
    """Message de /accueil/choix (schéma choix_accueil) : la salle choisie, par la borne ou le chatbot."""
    if source not in SOURCES_ACCUEIL:
        raise ValueError(f"source inconnue : {source} ({', '.join(SOURCES_ACCUEIL)})")
    message = {"version": 1, "salle": str(salle), "source": source}
    if ident is not None:
        message["id"] = str(ident)
    if texte:
        message["texte"] = str(texte)[:300]
    if accompagner is not None:
        message["accompagner"] = bool(accompagner)
    return message


def message_commande(action, source, ident=None):
    """Message de /accueil/commande (schéma commande_accueil)."""
    if action not in ACTIONS_COMMANDE:
        raise ValueError(f"action inconnue : {action} ({', '.join(ACTIONS_COMMANDE)})")
    if source not in SOURCES_ACCUEIL:
        raise ValueError(f"source inconnue : {source} ({', '.join(SOURCES_ACCUEIL)})")
    message = {"version": 1, "action": action, "source": source}
    if ident is not None:
        message["id"] = str(ident)
    return message


# ---------------------------------------------------------------- demo.yaml (fichier facultatif du lieu)

FICHIER_DEMO = "demo.yaml"
ENTETE_DEMO = ("Réglages de la démo d'accueil (Atelier G1, section 13.4 du plan), écrits par Équipe › Démo.\n"
               "# code_operateur n'est pas un mot de passe : il évite qu'un visiteur mette la démo en pause.")
DEMO_DEFAUT = {
    "version": 1,
    "voix": {"sortie": "robot", "volume": 70, "nom": "fr_FR-siwis-medium", "vitesse": 1.0},
    "visiteurs": {"source": "auto", "distance_m": 1.5, "presence_s": 1.0},
    "delais": {"choix_s": 45.0, "depart_s": 10.0, "entre_visiteurs_s": 8.0},
    "accompagner": True, "retour": True,
    "borne": {"langue": "fr", "titre": TEXTES_BORNE["salles"]},
}


def chemin_demo(lieu):
    """lieux/<id>/demo.yaml."""
    return dossier_lieu(lieu) / FICHIER_DEMO


def charger_demo(lieu):
    """Contenu de demo.yaml, vérifié ; None s'il n'existe pas. ErreurLieu s'il est faux."""
    chemin = chemin_demo(lieu)
    if not chemin.is_file():
        return None
    return charger_fichier(chemin, "demo")


def _fusionner(defaut, donnees):
    resultat = copy.deepcopy(defaut)
    for cle, valeur in (donnees or {}).items():
        if isinstance(valeur, dict) and isinstance(resultat.get(cle), dict):
            resultat[cle] = _fusionner(resultat[cle], valeur)
        else:
            resultat[cle] = copy.deepcopy(valeur)
    return resultat


def reglages_demo(lieu):
    """Réglages complets de la démo : demo.yaml du lieu, complété par DEMO_DEFAUT (sans fichier : les défauts)."""
    return _fusionner(DEMO_DEFAUT, charger_demo(lieu))


def enregistrer_demo(lieu, donnees):
    """Écrit demo.yaml (atomique) après l'avoir vérifié ; ErreurLieu sinon. Renvoie le chemin."""
    erreurs = valider_donnees("demo", donnees)
    if erreurs:
        raise ErreurLieu(erreurs)
    chemin = chemin_demo(lieu)
    ecrire_yaml(chemin, donnees, ENTETE_DEMO)
    return chemin


# ---------------------------------------------------------------- exemples (tests et documentation)

EXEMPLE_DEMO = {
    "version": 1, "personnalite": "accueillant",
    "voix": {"sortie": "borne", "volume": 80, "nom": "fr_FR-siwis-medium", "vitesse": 1.0},
    "visiteurs": {"source": "lidar", "distance_m": 1.5, "presence_s": 1.0},
    "delais": {"choix_s": 45.0, "depart_s": 10.0, "entre_visiteurs_s": 8.0},
    "accompagner": True, "retour": True,
    "borne": {"code_operateur": "4826", "langue": "fr", "titre": "Bonjour ! Où voulez-vous aller ?"},
}
EXEMPLE_ETAT_DEMO = {
    "version": 1, "etat": "accompagnement", "depuis_s": 12.4, "lieu": "demo", "etage": "rdc",
    "message": "Visite vers « Salle B204 » : le robot accompagne le visiteur.", "texte_borne": "Suivez-moi !",
    "raison": None,
    "visite": {"id": "v3", "salle": "b204", "nom": "Salle B204", "source": "borne",
               "debut": "2026-11-12T14:20:31+01:00", "reste_m": 14.2, "accompagner": True},
    "visiteur": {"vu": True, "source": "lidar", "distance_m": 1.3, "id": 7},
    "guide": {"etat": "en_route", "mission": "visite", "cible": "b204", "age_s": 0.2},
    "au_principal": False, "reprise_possible": False, "actions_possibles": ["pause"],
    "source_visiteurs": "lidar", "personnalite": "accueillant",
    "statistiques": {"visiteurs": 3, "demandes": 3, "visites_reussies": 2, "visites_abandonnees": 0, "echecs": 0,
                     "pauses": 0, "refus_occupe": 1, "duree_moyenne_s": 96.5, "depuis": "2026-11-12T14:01:00+01:00"},
    "temps": "2026-11-12T14:20:44+01:00",
}
EXEMPLE_EVENEMENT_DEMO = {"version": 1, "code": "choix_accepte", "texte": "Visite vers « Salle B204 » acceptée.",
                          "temps": "2026-11-12T14:20:31+01:00", "id": "borne-17", "salle": "b204",
                          "nom": "Salle B204", "source": "borne", "visite": "v3"}
EXEMPLE_CHOIX = {"version": 1, "id": "borne-17", "salle": "b204", "source": "borne"}
EXEMPLE_COMMANDE = {"version": 1, "id": "op-2", "action": "pause", "source": "operateur"}
EXEMPLE_ETAT_BORNE = {
    "version": 1, "ecran": "suivez_moi", "texte": "Suivez-moi !", "detail": "Encore 14 m jusqu'à Salle B204.",
    "lieu": {"id": "demo", "nom": "Lycée démo"},
    "salles": [{"id": "b204", "nom": "Salle B204", "etage": "rdc", "nom_etage": "Rez-de-chaussée",
                "etiquettes": [], "accessible": True, "pictogramme": None},
               {"id": "toilettes", "nom": "Toilettes", "etage": "rdc", "nom_etage": "Rez-de-chaussée",
                "etiquettes": ["toilettes"], "accessible": True, "pictogramme": "toilettes"}],
    "visite": {"salle": "b204", "nom": "Salle B204", "reste_m": 14.2},
    "demo": {"etat": "accompagnement", "depuis_s": 12.4, "age_s": 0.3},
    "son": {"id": "s-20261112-142031-0003", "texte": "Suivez-moi !", "duree_s": 1.1,
            "url": "/api/voix/son/s-20261112-142031-0003"},
    "operateur": {"possible": True, "actif": False}, "langue": "fr", "temps": "2026-11-12T14:20:44+01:00",
}
