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
import math

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
              "robot_muet", "refus", "pilotage",     # pilotage : vague 4 (section 11.5), verrou des mouvements
              "pas_en_marche")                       # vague 5 (section 12.6) : le mode lu (7001) n'est pas la marche
# Ordre de priorité des états du pont (le premier qui vaut l'emporte), vague 5 (section 12.6)
PRIORITE_ETATS_PONT = ("arret_verrouille", "robot_muet", "pas_en_marche", "refus", "pilotage", "attente_reperage",
                       "arret", "demarrage", "en_mouvement", "pret")
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


# ---------------------------------------------------------------- vague 5 (section 12.6 du plan)

# Vitesse minimale de marche du pont (règle 11). Le 27/10, le vrai G1 acceptait 7105 à 0,1 m/s sans
# faire un pas, et marchait à 0,2 m/s : sous un seuil (sur la norme de vx, vy), il reste sur place.
# Paramètres ROS du pont : vitesse_min_lin, vitesse_min_rot, zone_morte_lin, zone_morte_rot (0 : désactivé).
VITESSES_MIN_PONT = {"lin": 0.20, "rot": 0.30}     # m/s (mesuré le 27/10), rad/s (à mesurer à la séance 2)
ZONES_MORTES_PONT = {"lin": 0.05, "rot": 0.10}     # sous ces valeurs, la composante vaut 0
VITESSE_MIN_LIN_MAX = 0.30      # un réglage plus haut est refusé (une faute de frappe ne fait pas courir le robot)
VITESSE_MIN_ROT_MAX = 0.50
VITESSE_MAX_MIN = 0.20          # G1_VITESSE_MAX, --vitesse-max et vitesse_max:= refusés en dessous
MESSAGE_VITESSE_MAX_BASSE = "le robot ne marche pas sous 0,2 m/s"
# Lecture du mode du robot par le pont (règle 12)
API_SPORT_GET_FSM_ID = 7001     # GetFsmId : réponse {"data": N}
PERIODE_LECTURE_MODE_S = 1.0    # une lecture par seconde
DELAI_MODE_PERIME_S = 3.0       # un mode lu il y a plus longtemps est inconnu (il ne bloque rien)

# Le pont publie ces champs depuis la vague 5 : l'exemple complet les a aussi (le test du paquet
# g1_bridge veut les mêmes champs que Pont().etat()). Robot en marche (501), lu il y a 0,4 s.
EXEMPLE_ETAT_PONT.update(
    demande={"vx": 0.3, "vy": 0.0, "wz": 0.1},
    minimums={"vitesse_min_lin": VITESSES_MIN_PONT["lin"], "vitesse_min_rot": VITESSES_MIN_PONT["rot"],
              "zone_morte_lin": ZONES_MORTES_PONT["lin"], "zone_morte_rot": ZONES_MORTES_PONT["rot"]},
    mode_robot={"fsm": 501, "nom": "marche", "en_marche": True, "age_s": 0.4, "modes_marche": [500, 501, 801],
                "lectures": 412})

# /pont/etat de la vague 5 : les champs facultatifs demande, minimums et mode_robot, avec l'état
# pas_en_marche
EXEMPLE_ETAT_PONT_V5 = dict(
    EXEMPLE_ETAT_PONT, etat="pas_en_marche", mouvement_permis=False,
    message="Le robot est assis (mode 3) : il ignore les ordres de marche. Mettez-le debout puis en marche "
            "avec la télécommande (ou « Démarrer » dans Piloter).",
    consigne={"vx": 0.0, "vy": 0.0, "wz": 0.0}, demande={"vx": 0.1, "vy": 0.0, "wz": 0.0},
    minimums={"vitesse_min_lin": VITESSES_MIN_PONT["lin"], "vitesse_min_rot": VITESSES_MIN_PONT["rot"],
              "zone_morte_lin": ZONES_MORTES_PONT["lin"], "zone_morte_rot": ZONES_MORTES_PONT["rot"]},
    mode_robot={"fsm": 3, "nom": "assis", "en_marche": False, "age_s": 0.4, "modes_marche": [500, 501, 801],
                "lectures": 37})


def vitesse_effective(vx, vy, wz, plafonds=None, minimums=None, zones=None):
    """Consigne déjà plafonnée → consigne envoyée au robot (règle 11 du pont, section 12.6 du plan).

    1. Le robot marche déjà franchement (norme de (vx, vy) ≥ minimum linéaire, ou |wz| ≥ minimum de
       rotation) : la consigne passe telle quelle, petites corrections de cap ou de côté comprises.
    2. Sinon, toute la consigne est petite : zones mortes (norme de (vx, vy) sous la zone linéaire →
       (vx, vy) = 0 ; |wz| sous la zone de rotation → wz = 0). Tout à 0 : un arrêt.
    3. Puis l'intention dominante (norme / minimum linéaire comparée à |wz| / minimum de rotation) :
       marche : (vx, vy) porté à la norme du minimum, même direction (borné pour qu'aucune composante
       ne dépasse son plafond), wz gardé ; rotation : (0, 0, ±minimum de rotation), borné par wz_max.
    Un minimum (ou une zone) à 0 est désactivé : avec un minimum à 0, l'axe compte comme franc dès
    qu'il n'est pas nul. Une valeur non finie donne un arrêt.
    plafonds : {"vx", "vy", "wz"} (LIMITES_PONT) ; minimums, zones : {"lin", "rot"}. Renvoie (vx, vy, wz).

    Le pont (g1_bridge, qui tourne sans atelier) en a une copie exacte ; le joystick du pilotage
    (g1_pilotage) appelle celle-ci. Cas de référence : EXEMPLES_VITESSE_MIN.
    """
    p = LIMITES_PONT if plafonds is None else plafonds
    m = VITESSES_MIN_PONT if minimums is None else minimums
    z = ZONES_MORTES_PONT if zones is None else zones
    if not all(math.isfinite(v) for v in (vx, vy, wz)):
        return (0.0, 0.0, 0.0)
    smin, wmin = m["lin"], m["rot"]
    n, a = math.hypot(vx, vy), abs(wz)
    if (smin > 0 and n >= smin) or (wmin > 0 and a >= wmin):
        return (vx, vy, wz)
    if n < z["lin"]:
        vx = vy = n = 0.0
    if a < z["rot"]:
        wz = a = 0.0
    lin_petit = 0.0 < n < smin
    rot_petit = 0.0 < a < wmin
    if (n > 0.0 and not lin_petit) or (a > 0.0 and not rot_petit) or not (lin_petit or rot_petit):
        return (vx, vy, wz)        # minimum désactivé sur cet axe, ou consigne nulle
    if lin_petit and (not rot_petit or n / smin >= a / wmin):
        k = smin / n
        if vx:
            k = min(k, p["vx"] / abs(vx))
        if vy:
            k = min(k, p["vy"] / abs(vy))
        return (vx * k, vy * k, wz)
    return (0.0, 0.0, math.copysign(min(wmin, p["wz"]), wz))


# Cas de référence de vitesse_effective, avec les valeurs par défaut (et les plafonds de G1_VITESSE_MAX
# 0.2 pour le dernier) : (entrée, sortie attendue, plafonds). Le pont et le pilotage s'y conforment.
PLAFONDS_VITESSE_MAX_0_2 = {"vx": 0.2, "vy": 0.125, "wz": 0.3}
EXEMPLES_VITESSE_MIN = (
    ((0.1, 0.0, 0.0), (0.2, 0.0, 0.0), None),            # marche montée au minimum
    ((0.0, 0.1, 0.0), (0.0, 0.2, 0.0), None),            # pas de côté (vy_max 0,25 ≥ 0,2)
    ((0.1, 0.1, 0.0), (0.141421, 0.141421, 0.0), None),  # norme 0,2, direction gardée
    ((0.15, 0.02, 0.0), (0.198246, 0.026433, 0.0), None),  # × 1,32
    ((0.3, 0.05, 0.05), (0.3, 0.05, 0.05), None),        # marche franche : telle quelle
    ((0.1, 0.0, 0.4), (0.1, 0.0, 0.4), None),            # |wz| ≥ 0,3 : telle quelle
    ((0.15, 0.0, 0.1), (0.2, 0.0, 0.1), None),           # la marche domine (0,75 > 0,33)
    ((0.08, 0.0, 0.2), (0.0, 0.0, 0.3), None),           # la rotation domine (0,67 > 0,4)
    ((0.0, 0.0, 0.15), (0.0, 0.0, 0.3), None),           # rotation sur place
    ((0.0, 0.0, -0.15), (0.0, 0.0, -0.3), None),
    ((0.03, 0.0, 0.0), (0.0, 0.0, 0.0), None),           # zone morte linéaire : arrêt
    ((0.0, 0.0, 0.08), (0.0, 0.0, 0.0), None),           # zone morte de rotation : arrêt
    ((0.1, 0.0, 0.05), (0.2, 0.0, 0.0), None),           # wz dans la zone morte, marche montée
    ((-0.1, 0.0, 0.0), (-0.2, 0.0, 0.0), None),          # marche arrière montée (Nav2 n'en envoie plus)
    ((0.0, 0.1, 0.0), (0.0, 0.125, 0.0), PLAFONDS_VITESSE_MAX_0_2),   # borné par vy_max
    ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), None),
)


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
