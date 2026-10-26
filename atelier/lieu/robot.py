"""Le vrai robot (vague 3, section 10 du plan) : repère de la carte d'Unitree, marque au sol,
valeurs du contrat du pont et du repérage, et messages JSON de /pont/etat et /reperage/*.

Repère de la carte d'Unitree
----------------------------
La relocalisation d'Unitree (commande 1804, puis /unitree/slam_relocation/odom) donne la pose du
robot dans le repère de SA carte : le nuage .pcd enregistré par 1802, dont l'origine est le point
de départ du scan. repere_unitree(lieu, etage) est la pose de cette origine dans le repère map de
l'étage (celui de cartes/<etage>.yaml, des salles et des nœuds) :

    pose_map     = unitree_vers_carte(pose_unitree, repere)   (= composer_poses(repere, pose_unitree))
    pose_unitree = carte_vers_unitree(pose_map, repere)       (pour la pose initiale de 1804)

Valeur : le champ facultatif repere_unitree de l'étage dans lieu.yaml s'il existe ; sinon
  - source_carte: scan  → (0, 0, 0) : la carte de l'étage vient d'un scan, elle est dans son repère ;
  - source_carte: monde → depart_robot du monde de l'étage : un scan commencerait là, et c'est là
    que le robot proxy apparaît dans Gazebo ; (0, 0, 0) si l'étage n'a pas de monde.
La marque au sol, où l'on pose le robot avant « Repérer le robot », est l'origine de ce repère :
marque_au_sol(lieu, etage) vaut repere_unitree(lieu, etage).

Le relais (g1_nav/odom_vers_tf.py), le faux service slam_operate en répétition et le serveur de
l'Atelier passent tous par ces fonctions : il n'y a qu'une seule façon de passer d'un repère à l'autre.

Messages JSON (std_msgs/String) : schémas etat_pont, etat_reperage, demande_reperage dans
atelier/lieu/schemas ; valider_message(type, donnees) renvoie la liste des erreurs (vide : conforme).
Elle connaît aussi les messages de la vague 4 (section 11 du plan, TYPES_MESSAGES).
"""
from .conversions import carte_vers_unitree, unitree_vers_carte
from .fichiers import ErreurLieu, chemin_monde, charger_fiche, charger_monde
from .modeles import Pose
from .validation import TYPES_MESSAGES, valider_donnees

# ---------------------------------------------------------------- valeurs du contrat (section 10)

# Pont /cmd_vel → /api/sport/request (paquet g1_bridge, nœud pont_g1) : config/pont.yaml les reprend
API_SPORT_SET_VELOCITY = 7105
LIMITES_PONT = {"vx": 0.4, "vy": 0.25, "wz": 0.6}     # m/s, m/s, rad/s, plafond de chaque composante
DUREE_CONSIGNE_S = 0.5          # champ duration de chaque 7105 non nul : le robot s'arrête seul après
DUREE_ARRET_S = 1.0             # duration d'un arrêt (velocity [0, 0, 0]), comme StopMove du SDK
DELAI_CMD_VEL_S = 0.3           # sans /cmd_vel depuis ce temps : un arrêt, puis plus rien
FREQUENCE_PONT_HZ = 10.0        # envoi de la consigne en cours
GARDE_APRES_STOP_S = 1.0        # après /guide/stop : /cmd_vel ignoré pendant ce temps
DELAI_REPERAGE_PERIME_S = 1.0   # /reperage/etat plus vieux : le pont le considère comme non repéré
DELAI_ROBOT_MUET_S = 1.0        # aucune réponse depuis ce temps (requêtes envoyées) : robot_muet

# Repérage (paquet g1_nav, nœud odom_vers_tf) et faux service slam_operate en répétition
API_RELOCALISER = 1804
CARTE_REPETITION = "repetition.pcd"     # carte connue du faux service quand le lieu n'a pas de carte_unitree
DELAI_REPERAGE_S = 15.0         # 1804 envoyée → relocalisation reçue, au plus
DELAI_PERDU_S = 3.0             # plus de relocalisation depuis ce temps : etat perdu
ECART_MAX_M = 1.0               # pose trouvée / pose annoncée : au-delà, echec (le faux service refuse aussi)
ECART_MAX_RAD = 0.5
SAUT_M = 0.5                    # correction de map → odom comptée comme un saut
SAUT_RAD = 0.3

# Faux G1 (paquet g1_jumeau) : dérive de son odométrie /state_estimator/odom_pelvis
DERIVE_ECHELLE = 0.02           # les déplacements sont comptés 2 % trop longs
DERIVE_LACET_PAR_M = 0.01       # rad de lacet ajoutés par mètre parcouru
HAUTEUR_PELVIS = 0.75           # m, z de odom_pelvis (le relais projette au sol)

ETATS_PONT = ("demarrage", "attente_reperage", "pret", "en_mouvement", "arret", "arret_verrouille",
              "robot_muet", "refus", "pilotage")     # pilotage : vague 4 (section 11.5), verrou des mouvements
ETATS_REPERAGE = ("non_repere", "en_cours", "repere", "perdu", "echec")
LOCALISATIONS = ("simu", "unitree", "amcl", "externe")     # argument localisation de navigation.launch.py
MODES_NAVIGATION = ("simu", "repetition", "robot")          # champ mode de POST /api/simulation/demarrer

# Exemples complets, conformes aux schémas (tests et documentation)
EXEMPLE_ETAT_PONT = {
    "version": 1, "etat": "en_mouvement", "message": "Le robot suit la navigation.",
    "mouvement_permis": True, "reperage": True, "exiger_reperage": True, "verrou": False,
    "consigne": {"vx": 0.3, "vy": 0.0, "wz": 0.1}, "limites": dict(LIMITES_PONT),
    "duree_consigne_s": DUREE_CONSIGNE_S, "age_cmd_vel_s": 0.04, "envoyees": 412, "reponses": 410,
    "age_reponse_s": 0.07, "code": 0}
EXEMPLE_ETAT_REPERAGE = {
    "version": 1, "etat": "repere", "repere": True, "localisation": "unitree",
    "message": "Robot repéré sur la carte (précision 2 cm).",
    "pose": {"x": 2.51, "y": 10.02, "theta": 0.01}, "precision_m": 0.02, "age_s": 0.08,
    "demande": "atelier-1", "carte": CARTE_REPETITION,
    "repere_unitree": {"x": 2.5, "y": 10.0, "theta": 0.0}, "sauts": 0}
EXEMPLE_DEMANDE_REPERAGE = {"id": "atelier-1", "x": 2.5, "y": 10.0, "theta": 0.0}


def valider_message(type_message, donnees):
    """Erreurs d'un message JSON (std_msgs/String) : etat_pont, etat_reperage, demande_reperage
    (section 10), ou un message de la vague 4 (section 11 : TYPES_MESSAGES de validation.py)."""
    if type_message not in TYPES_MESSAGES:
        raise ValueError(f"type de message inconnu : {type_message} (types : {', '.join(TYPES_MESSAGES)})")
    return valider_donnees(type_message, donnees)


# ---------------------------------------------------------------- repère d'Unitree et marque au sol

def _etage(fiche, etage):
    for e in fiche.etages:
        if e.id == etage:
            return e
    raise ErreurLieu(f"lieu.yaml : l'étage « {etage} » n'existe pas ; étages du lieu : "
                     f"{', '.join(e.id for e in fiche.etages)}")


def repere_unitree(lieu, etage):
    """Pose (Pose) de l'origine de la carte d'Unitree dans le repère map de l'étage (voir l'en-tête)."""
    fiche = charger_fiche(lieu)
    e = _etage(fiche, etage)
    if e.repere_unitree is not None:
        return Pose(e.repere_unitree.x, e.repere_unitree.y, e.repere_unitree.theta)
    if e.source_carte == "scan" or not chemin_monde(lieu, etage).is_file():
        return Pose(0.0, 0.0, 0.0)
    depart = charger_monde(lieu, etage).depart_robot
    return Pose(depart.x, depart.y, depart.theta)


def marque_au_sol(lieu, etage):
    """Pose de la marque au sol dans le repère map : l'origine de la carte d'Unitree."""
    return repere_unitree(lieu, etage)


def carte_pour_reperage(lieu, repetition=False):
    """Nom du .pcd à donner à 1804 : carte_unitree du lieu ; en répétition sans carte_unitree,
    CARTE_REPETITION ; None sinon (le lieu n'a pas encore été scanné avec le robot)."""
    carte = charger_fiche(lieu).carte_unitree
    if carte:
        return carte
    return CARTE_REPETITION if repetition else None


def pose_unitree_depuis_carte(pose_carte, lieu, etage):
    """Pose (x, y, theta) du repère map → repère de la carte d'Unitree, pour cet étage."""
    return carte_vers_unitree(pose_carte, repere_unitree(lieu, etage))


def pose_carte_depuis_unitree(pose_unitree, lieu, etage):
    """Pose (x, y, theta) du repère de la carte d'Unitree → repère map, pour cet étage."""
    return unitree_vers_carte(pose_unitree, repere_unitree(lieu, etage))
