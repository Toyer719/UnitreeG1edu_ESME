"""Le pilotage du G1 depuis l'Atelier (vague 4, section 11.5 du plan) : commandes, refus, danses,
gestes, bras par rt/arm_sdk et chorégraphies.

Chemin des commandes : navigateur → serveur de l'Atelier (/api/pilotage, /ws/pilotage) → nœud
pilotage dans le conteneur du Jetson (paquet g1_pilotage, petite API HTTP et WebSocket, port
PORT_PILOTAGE) → services d'Unitree en ROS 2 sur le réseau interne : unitree_api/Request sur
/api/sport/request, /api/arm/request et /api/voice/request (réponses sur …/response), et
unitree_hg/LowCmd sur /arm_sdk (rt/arm_sdk). Ce module est importé par le conteneur (atelier.lieu y
est copié) : il ne dépend que de PyYAML.

Sécurité (contrat) :
  - refus_commande(service, api_id, donnees) dit si une requête est interdite : seules les
    commandes des listes ci-dessous passent ; jamais de mode debug, de couple moteur à moteur
    (rt/lowcmd), de passage en commande utilisateur (7110) ni de politique corps entier ;
  - confirmation_requise(service, api_id, donnees) : « portique » pour amortir (1) et couple nul (0)
    (le robot s'affaisse : confirmation double et case « robot au portique ») ; « zone_libre » pour
    une danse (les pieds bougent : 2 à 3 m libres) ;
  - les danses 401, 402 et 403 sont toujours refusées (le robot se couche par terre, ou inconnu) ;
  - la marche au joystick est plafonnée (LIMITES_MARCHE), chaque ordre ne vaut que DUREE_ORDRE_S,
    et sans ordre depuis DELAI_HOMME_MORT_S le nœud pilotage arrête le robot ;
  - les bras d'une chorégraphie restent dans LIMITES_BRAS, à VITESSE_BRAS_MAX au plus, avec des
    rampes du poids de RAMPE_MIN_S au moins ; les pas restent sous LIMITES_PAS et le robot à
    DEPLACEMENT_MAX_M au plus de son départ (verifier_choregraphie).

Danses du robot (source communautaire non officielle, github sondos-myi/g1-robot-moves, micrologiciel
1.5.6 ; confirmée en partie par GetMimicMotion du SDK C++ d'Unitree) : liste par 7100
{"fsm_id": 550, "api_id": 1}, lecture par 7101 {"data": 550000 + n}, départ debout immobile (801),
retour seul en 801. À VÉRIFIER SUR LE ROBOT.

Fichier de l'agent Pilotage et danses (vague 4). Les fonctions et valeurs marquées « contrat » sont
livrées et testées par l'intégrateur (atelier/tests/test_contrats_vague4.py) : elles gardent leur
nom, leurs arguments et leur comportement ; une valeur ne s'assouplit qu'avec l'intégrateur.
"""
import json
import math
from pathlib import Path

import atelier

from .fichiers import ErreurLieu, lire_yaml
from .robot import LIMITES_PONT

# ---------------------------------------------------------------- services et api (SDK d'Unitree)

SERVICES = {"sport": "/api/sport", "arm": "/api/arm", "voice": "/api/voice"}   # + /request, /response
SUJET_ARM_SDK = "/arm_sdk"                  # unitree_hg/LowCmd (rt/arm_sdk)
SUJET_LOWSTATE = "/lowstate"                # unitree_hg/LowState (rt/lowstate) : angles mesurés
SUJET_MAITRE = "/mouvement/maitre"          # verrou des mouvements (schéma maitre_mouvement)
SUJET_ETAT = "/pilotage/etat"               # schéma etat_pilotage
PORT_PILOTAGE = 8010                        # API HTTP et WebSocket du nœud pilotage
ENTETE_JETON = "X-Jeton"                    # jeton partagé (G1_PILOTAGE_JETON) sur le Wi-Fi
# Caméra de la tête (Vue du robot de l'onglet Pilotage, section 11.13) : le service videohub du
# SDK d'Unitree (unitree_sdk2py/go2/video/video_client.py, GetImageSample, api 1001) rend une image
# JPEG dans le champ binary de la réponse. Demandée image par image, seulement quand une page la
# regarde (jamais le flux H264 de /frontvideostream) : à vérifier sur le robot.
SERVICE_VIDEO = "/api/videohub"             # + /request, /response (unitree_api/Request, Response)
API_VIDEO = {"get_image_sample": 1001}
CAMERA_ECART_MIN_S = 0.2                    # au plus 5 demandes par seconde au robot, toutes pages comprises
CAMERA_DELAI_S = 1.0                        # attente d'une image par le nœud
CAMERA_PERIODE_PAGE_S = 0.35                # une page demande une image au plus toutes les 0,35 s

API_SPORT = {"get_fsm_id": 7001, "get_fsm_mode": 7002, "get_balance_mode": 7003, "get_swing_height": 7004,
             "get_stand_height": 7005, "get_phase": 7006, "fsm_api": 7100, "set_fsm_id": 7101,
             "set_balance_mode": 7102, "set_swing_height": 7103, "set_stand_height": 7104, "set_velocity": 7105,
             "set_task_id": 7106, "set_speed_mode": 7107, "switch_to_user_ctrl": 7110,
             "switch_to_internal_ctrl": 7111}
API_ARM = {"execute_action": 7106, "get_action_list": 7107, "execute_custom_action": 7108,
           "stop_custom_action": 7113}
API_VOICE = {"tts": 1001, "asr": 1002, "start_play": 1003, "stop_play": 1004, "get_volume": 1005,
             "set_volume": 1006, "set_rgb_led": 1010}

# Postures (7101 SetFsmId) permises. 0 et 1 : confirmation « portique ».
POSTURES = {500: "Démarrer (prêt à marcher)", 706: "Accroupi ↔ debout", 702: "Se lever (depuis couché)",
            3: "S'asseoir", 1: "Amortir (le robot s'affaisse s'il n'est pas tenu)", 0: "Couple nul (moteurs relâchés)"}
POSTURES_PORTIQUE = (0, 1)
FSM_MARCHE = 801                            # mode marche lu après « démarrer » (départ et fin d'une danse)
FSM_GESTES = (500, 501, 801)                # gestes d'Unitree permis dans ces modes (sinon 7404)

# Danses du robot : 7101 {"data": DANSE_PREFIXE + n}
DANSE_PREFIXE = 550000
DANSE_LISTE = {"fsm_id": 550, "api_id": 1}  # paramètre de 7100 qui rend la liste
DANSES_INTERDITES = (401, 402, 403)         # 401, 402 : le robot se couche par terre ; 403 : inconnu
DANSES_ESSAYEES = {602: "popping court", 603: "capture", 604: "danse robot (environ 18 s)"}
DANSES_NON_ESSAYEES = {502: "?", 503: "?", 504: "?", 605: "?", 574: "accueil (environ 42 s)"}
FSM_ARRET_DANSE = None      # aucun ordre connu n'interrompt une danse : ARRÊT envoie StopMove, la télécommande reste l'arrêt d'urgence (à vérifier)

# Gestes des bras d'Unitree (service arm, 7106 {"action_id": n})
GESTES_BRAS = {99: "Relâcher les bras", 11: "Bisou des deux mains", 12: "Bisou", 13: "Bisou main droite (à vérifier)",
               15: "Mains en l'air", 17: "Applaudir", 18: "Tape-m'en cinq", 19: "Câlin", 20: "Cœur",
               21: "Cœur main droite", 22: "Refuser", 23: "Main droite levée", 24: "X-ray",
               25: "Saluer près du visage", 26: "Grand salut", 27: "Serrer la main"}
GESTE_RELACHER = 99
# Tâches de la marche (service sport, 7106 SetTaskId)
TACHES_LOCO = {0: "Saluer", 1: "Saluer en se tournant", 2: "Serrer la main (tendre)", 3: "Serrer la main (finir)"}

# Codes de refus connus, en français
CODES_REFUS = {
    7301: "Le robot n'est pas en mode marche : démarrez-le (posture « Démarrer ») ou utilisez la télécommande.",
    7302: "Mode (fsm) inconnu du robot.",
    7303: "Tâche inconnue du robot.",
    7400: "Les bras sont déjà pilotés par rt/arm_sdk (une chorégraphie tourne) : arrêtez-la d'abord.",
    7401: "Les bras tiennent encore le geste précédent : relâchez-les (geste 99) ou refaites le même geste.",
    7402: "Geste inconnu du robot.",
    7404: "Le robot doit être debout en mode marche (500, 501 ou 801) pour faire un geste.",
    3203: "Le robot ne connaît pas cette commande.",
    3204: "Le robot a refusé les paramètres de la commande.",
    3104: "Le robot n'a pas répondu à temps.",
}

# ---------------------------------------------------------------- marche au joystick (homme mort)

LIMITES_MARCHE = dict(LIMITES_PONT)         # m/s, m/s, rad/s : comme le pont (G1_VITESSE_MAX les baisse)
DUREE_ORDRE_S = 0.5                         # duration de chaque 7105 du joystick
PERIODE_JOYSTICK_S = 0.1                    # la page renvoie l'ordre 10 fois par seconde
DELAI_HOMME_MORT_S = 0.5                    # sans ordre depuis ce temps : StopMove
ARRET_MAX_S = 0.6                           # robot arrêté au plus tard après le dernier ordre (critère 28)
DELAI_CONFIRMATION_S = 10.0                 # le second appel d'une confirmation double doit venir avant

# ---------------------------------------------------------------- bras par rt/arm_sdk

# G1 29 ddl : index des moteurs (unitree_ros2 example g1.hpp, G1Arm7JointIndex)
ARTICULATIONS_BRAS = {
    "left_shoulder_pitch": 15, "left_shoulder_roll": 16, "left_shoulder_yaw": 17, "left_elbow": 18,
    "left_wrist_roll": 19, "left_wrist_pitch": 20, "left_wrist_yaw": 21,
    "right_shoulder_pitch": 22, "right_shoulder_roll": 23, "right_shoulder_yaw": 24, "right_elbow": 25,
    "right_wrist_roll": 26, "right_wrist_pitch": 27, "right_wrist_yaw": 28}
ARTICULATIONS_TAILLE = {"waist_yaw": 12, "waist_roll": 13, "waist_pitch": 14}   # tenues, jamais pilotées
INDICE_POIDS = 29                           # motor_cmd[29].q : poids d'arm_sdk, de 0 à 1 (kNotUsedJoint)
# Limites de l'URDF g1_29dof_rev_1_0 (third_party/unitree_rl_gym/resources/robots/g1_description), rad
LIMITES_URDF = {
    "left_shoulder_pitch": (-3.0892, 2.6704), "left_shoulder_roll": (-1.5882, 2.2515),
    "left_shoulder_yaw": (-2.618, 2.618), "left_elbow": (-1.0472, 2.0944),
    "left_wrist_roll": (-1.972222054, 1.972222054), "left_wrist_pitch": (-1.614429558, 1.614429558),
    "left_wrist_yaw": (-1.614429558, 1.614429558),
    "right_shoulder_pitch": (-3.0892, 2.6704), "right_shoulder_roll": (-2.2515, 1.5882),
    "right_shoulder_yaw": (-2.618, 2.618), "right_elbow": (-1.0472, 2.0944),
    "right_wrist_roll": (-1.972222054, 1.972222054), "right_wrist_pitch": (-1.614429558, 1.614429558),
    "right_wrist_yaw": (-1.614429558, 1.614429558)}
MARGE_BRAS = 0.05                           # rad pris sur chaque bout de l'URDF
LIMITES_BRAS = {nom: (bas + MARGE_BRAS, haut - MARGE_BRAS) for nom, (bas, haut) in LIMITES_URDF.items()}
REPOS_BRAS = {nom: 0.0 for nom in ARTICULATIONS_BRAS}   # pose de départ et de fin (init_pos de l'exemple)
VITESSE_BRAS_MAX = 1.5                      # rad/s par articulation, au plus fort de l'interpolation
RAMPE_MIN_S = 1.0                           # rampes du poids d'arm_sdk, au début et à la fin
FREQUENCE_BRAS_HZ = 50.0                    # LowCmd envoyés (control_dt 0,02 s de l'exemple)
GAINS_BRAS = {"kp": 60.0, "kd": 1.5}        # g1_arm_sdk_dds_example.cpp
GAINS_TAILLE = {"kp": 240.0, "kd": 6.0}     # ×4, comme l'exemple pour la taille

# ---------------------------------------------------------------- chorégraphies

LIMITES_PAS = {"vx": 0.3, "vy": 0.2, "wz": 0.6}
DUREE_PAS_S = (0.2, 2.0)
DEPLACEMENT_MAX_M = 1.0                     # le robot reste à 1 m au plus de son point de départ
ROTATION_MAX_RAD = 2 * math.pi              # rotation cumulée au plus, en valeur absolue
ZONE_LIBRE_MIN_M = 2.0
DOSSIER_CHOREGRAPHIES = atelier.RACINE / "choregraphies"
DOSSIER_MUSIQUE = DOSSIER_CHOREGRAPHIES / "musique"          # ignoré par Git : jamais de musique protégée
SUFFIXE_CHOREGRAPHIE = ".choregraphie.yaml"

EXEMPLE_MAITRE = {"version": 1, "maitre": "pilotage", "par": "atelier", "depuis": "2026-10-26T10:00:00+01:00",
                  "message": "Le robot est piloté depuis l'onglet Pilotage : le guide attend."}
EXEMPLE_ETAT_PILOTAGE = {"version": 1, "maitre": "pilotage", "robot_repond": True, "fsm": 801, "activite": "marche",
                         "message": "Marche au joystick.", "consigne": {"vx": 0.2, "vy": 0.0, "wz": 0.0},
                         "age_ordre_s": 0.04, "danse": None, "choregraphie": None, "bras_tenus": False,
                         "dernier_refus": None}


# ---------------------------------------------------------------- paramètres des requêtes (contrat)

def parametre_fsm(fsm):
    """Contrat. parameter de 7101 SetFsmId (texte JSON, comme le SDK)."""
    return json.dumps({"data": int(fsm)})


def parametre_vitesse(vx, vy, wz, duree=DUREE_ORDRE_S):
    """Contrat. parameter de 7105 SetVelocity, comme le pont (g1_bridge.requete)."""
    return json.dumps({"velocity": [float(vx), float(vy), float(wz)], "duration": float(duree)})


def parametre_tache(tache):
    """Contrat. parameter de 7106 SetTaskId (service sport)."""
    return json.dumps({"data": int(tache)})


def parametre_geste(action):
    """Contrat. parameter de 7106 du service arm. Format du SDK C++ ({"action_id": n}) ; le SDK
    Python écrit {"data": n} : lequel le robot accepte est à vérifier."""
    return json.dumps({"action_id": int(action)})


def parametre_tts(texte, index=0, voix=0):
    """Contrat. parameter de 1001 TtsMaker (service voice)."""
    return json.dumps({"index": int(index), "speaker_id": int(voix), "text": str(texte)}, ensure_ascii=False)


def parametre_led(r, g, b):
    """Contrat. parameter de 1010 (LED), de 0 à 255."""
    return json.dumps({"R": int(r), "G": int(g), "B": int(b)})


def parametre_volume(volume):
    """Contrat. parameter de 1006 SetVolume, de 0 à 100."""
    return json.dumps({"volume": int(volume)})


def parametre_liste_danses():
    """Contrat. parameter de 7100 qui rend la liste des danses du robot."""
    return json.dumps(DANSE_LISTE)


def lire_liste_danses(texte):
    """Contrat. Liste des danses du robot, depuis la réponse de 7100 : {n: {"nom", "duree_s"}}.
    Accepte le format du SDK C++ ({"fsm_id": 550, "api_id": 1, "motion": {"604": {"name",
    "duration"}}}) et celui de la source communautaire ({"604": {"name", "duration"}}). Les danses
    interdites y restent (marquées par danse_interdite) : c'est à l'interface de les griser."""
    donnees = json.loads(texte) if isinstance(texte, str) else texte
    if not isinstance(donnees, dict):
        raise ValueError("liste des danses : il faut un objet JSON")
    mouvements = donnees.get("motion", donnees)
    liste = {}
    for cle, valeur in mouvements.items():
        if not str(cle).isdigit() or not isinstance(valeur, dict):
            continue
        duree = valeur.get("duration")
        liste[int(cle)] = {"nom": str(valeur.get("name", "")),
                           "duree_s": float(duree) if isinstance(duree, (int, float)) else None}
    return liste


# ---------------------------------------------------------------- refus et confirmations (contrat)

def danse_interdite(n):
    """Contrat. Vrai pour une danse interdite (401, 402, 403)."""
    return int(n) in DANSES_INTERDITES


def _lire(donnees):
    if isinstance(donnees, str):
        try:
            donnees = json.loads(donnees) if donnees else {}
        except ValueError:
            return None
    return donnees if isinstance(donnees, dict) else None


def _nombre_fini(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def refus_commande(service, api_id, donnees=None):
    """Contrat. None si la requête est permise, sinon la raison du refus, en français.

    service : sport, arm ou voice ; donnees : le parameter (texte JSON ou dict). Les confirmations
    (portique, zone libre) ne sont pas vérifiées ici : voir confirmation_requise."""
    d = _lire(donnees)
    if d is None:
        return "paramètres illisibles (JSON attendu)"
    if service == "sport":
        if api_id in (7001, 7002, 7003, 7004, 7005, 7006):
            return None
        if api_id == 7100:
            return None if d == DANSE_LISTE else "seule la liste des danses ({\"fsm_id\": 550, \"api_id\": 1}) est permise"
        if api_id == 7101:
            fsm = d.get("data")
            if isinstance(fsm, bool) or not isinstance(fsm, int):
                return "posture : data doit être un nombre entier"
            if fsm in POSTURES:
                return None
            if DANSE_PREFIXE < fsm < DANSE_PREFIXE + 1000:
                n = fsm - DANSE_PREFIXE
                if danse_interdite(n):
                    return f"la danse {n} est interdite (le robot peut se coucher par terre)"
                return None
            return (f"posture {fsm} interdite : seules {', '.join(map(str, POSTURES))} et les danses "
                    f"{DANSE_PREFIXE} + n sont permises")
        if api_id == 7105:
            v, duree = d.get("velocity"), d.get("duration")
            if not isinstance(v, list) or len(v) != 3 or not all(_nombre_fini(x) for x in v) or not _nombre_fini(duree):
                return "marche : velocity [vx, vy, wz] et duration, des nombres finis"
            if all(abs(x) < 1e-9 for x in v):
                return None if 0 < duree <= 1.0 else "arrêt : duration de 0 à 1 s"
            for x, axe in zip(v, ("vx", "vy", "wz")):
                if abs(x) > LIMITES_MARCHE[axe] + 1e-9:
                    return f"marche : {axe} = {x} dépasse le plafond {LIMITES_MARCHE[axe]}"
            return None if 0 < duree <= DUREE_ORDRE_S + 1e-9 else f"marche : duration de {DUREE_ORDRE_S} s au plus"
        if api_id == 7106:
            return None if d.get("data") in TACHES_LOCO else "tâche inconnue (0, 1 : saluer ; 2, 3 : serrer la main)"
        return f"commande {api_id} du service sport interdite depuis l'Atelier"
    if service == "arm":
        if api_id in (7107, 7113):
            return None
        if api_id == 7106:
            action = d.get("action_id", d.get("data"))
            return None if action in GESTES_BRAS else f"geste {action} inconnu ou interdit"
        if api_id == 7108:
            nom = d.get("action_name")
            return None if isinstance(nom, str) and 0 < len(nom) <= 60 else "geste appris : action_name attendu"
        return f"commande {api_id} du service arm interdite depuis l'Atelier"
    if service == "voice":
        if api_id in (1004, 1005):
            return None
        if api_id == 1001:
            texte = d.get("text")
            return None if isinstance(texte, str) and 0 < len(texte) <= 500 else "parole : text de 1 à 500 caractères"
        if api_id == 1006:
            vol = d.get("volume")
            return None if isinstance(vol, int) and not isinstance(vol, bool) and 0 <= vol <= 100 else "volume de 0 à 100"
        if api_id == 1010:
            ok = all(isinstance(d.get(c), int) and not isinstance(d.get(c), bool) and 0 <= d.get(c) <= 255
                     for c in "RGB")
            return None if ok else "LED : R, G et B de 0 à 255"
        return f"commande {api_id} du service voice interdite depuis l'Atelier"
    return f"service « {service} » inconnu (sport, arm ou voice)"


def confirmation_requise(service, api_id, donnees=None):
    """Contrat. « portique » (amortir, couple nul), « zone_libre » (danse), ou None."""
    d = _lire(donnees) or {}
    if service == "sport" and api_id == 7101:
        fsm = d.get("data")
        if fsm in POSTURES_PORTIQUE:
            return "portique"
        if isinstance(fsm, int) and DANSE_PREFIXE < fsm < DANSE_PREFIXE + 1000:
            return "zone_libre"
    return None


def message_refus(code):
    """Contrat. Message en français d'un code de refus du robot."""
    return CODES_REFUS.get(int(code), f"Le robot a refusé (code {code}).")


# ---------------------------------------------------------------- chorégraphies (contrat)

def _poses_completes(d):
    """Poses des bras avec toutes les articulations (une absente garde la valeur précédente)."""
    courant = dict(REPOS_BRAS)
    sortie = []
    for p in (d.get("bras") or {}).get("poses", []):
        courant = dict(courant, **p["q"])
        sortie.append((p["t"], dict(courant)))
    return sortie


def segments_bras(d):
    """Contrat. Segments [(t0, q0, t1, q1)] des bras : du repos (fin de la rampe) à la première pose,
    de pose en pose, puis de la dernière pose au repos (début de la rampe de fin). [] sans bras."""
    bras = d.get("bras")
    if not bras or not bras.get("poses"):
        return []
    rampe = bras.get("rampe_s", RAMPE_MIN_S)
    cles = [(rampe, dict(REPOS_BRAS))] + _poses_completes(d) + [(d["duree_s"] - rampe, dict(REPOS_BRAS))]
    return [(t0, q0, t1, q1) for (t0, q0), (t1, q1) in zip(cles, cles[1:])]


def poses_bras(d, t):
    """Contrat. (poids d'arm_sdk, {articulation: angle}) à l'instant t de la chorégraphie d.
    Hors du segment des bras : le repos ; poids 0 → 1 pendant la rampe du début, 1 → 0 à la fin."""
    bras = d.get("bras")
    if not bras or not bras.get("poses"):
        return 0.0, dict(REPOS_BRAS)
    rampe, fin = bras.get("rampe_s", RAMPE_MIN_S), d["duree_s"]
    poids = max(0.0, min(1.0, t / rampe, (fin - t) / rampe))
    douce = bras.get("interpolation", "douce") == "douce"
    for t0, q0, t1, q1 in segments_bras(d):
        if t0 <= t <= t1:
            k = 0.0 if t1 <= t0 else (t - t0) / (t1 - t0)
            if douce:
                k = (1 - math.cos(math.pi * k)) / 2
            return poids, {n: q0[n] + (q1[n] - q0[n]) * k for n in ARTICULATIONS_BRAS}
    return poids, dict(REPOS_BRAS)


def deplacement_pas(d, pas_s=0.05):
    """Contrat. (distance maximale au départ en m, rotation cumulée en rad) des pas de d, intégrés
    dans le repère du robot (le robot part de (0, 0, 0))."""
    x = y = cap = 0.0
    distance_max = rotation = 0.0
    for p in sorted(d.get("pas") or [], key=lambda q: q["t"]):
        n = max(1, int(math.ceil(p["duree_s"] / pas_s)))
        dt = p["duree_s"] / n
        for _ in range(n):
            x += (p["vx"] * math.cos(cap) - p["vy"] * math.sin(cap)) * dt
            y += (p["vx"] * math.sin(cap) + p["vy"] * math.cos(cap)) * dt
            cap += p["wz"] * dt
            rotation += abs(p["wz"]) * dt
            distance_max = max(distance_max, math.hypot(x, y))
    return distance_max, rotation


def regles_choregraphie(d, fichier="chorégraphie"):
    """Contrat. Règles d'une chorégraphie que le schéma ne peut pas dire (le schéma est déjà passé)."""
    messages = []
    ou = f"{fichier} « {d['id']} »"
    duree = d["duree_s"]
    bras = d.get("bras")
    if bras and bras.get("poses"):
        rampe = bras.get("rampe_s", RAMPE_MIN_S)
        poses = bras["poses"]
        if 2 * rampe >= duree:
            messages.append(f"{ou} : les deux rampes des bras ({rampe:g} s chacune) ne tiennent pas dans {duree:g} s")
        temps = [p["t"] for p in poses]
        if any(b <= a for a, b in zip(temps, temps[1:])):
            messages.append(f"{ou}, bras : les temps des poses doivent croître strictement")
        if temps[0] < rampe or temps[-1] > duree - rampe:
            messages.append(f"{ou}, bras : les poses vont de {rampe:g} s (fin de la rampe) à {duree - rampe:g} s "
                            f"(début de la rampe de fin), pas de {temps[0]:g} à {temps[-1]:g} s")
        for p in poses:
            for nom, q in p["q"].items():
                bas, haut = LIMITES_BRAS[nom]
                if not bas <= q <= haut:
                    messages.append(f"{ou}, pose à {p['t']:g} s : {nom} = {q:g} rad sort des limites "
                                    f"[{bas:.3f}, {haut:.3f}] (URDF moins {MARGE_BRAS} rad)")
        facteur = math.pi / 2 if bras.get("interpolation", "douce") == "douce" else 1.0
        if not any(b <= a for a, b in zip(temps, temps[1:])):
            for t0, q0, t1, q1 in segments_bras(d):
                if t1 <= t0:
                    # segment de durée nulle (première pose à la fin de la rampe, ou dernière au
                    # début de la rampe de fin) : les bras sauteraient d'un coup s'il change
                    saut = [n for n in ARTICULATIONS_BRAS if abs(q1[n] - q0[n]) > 1e-9]
                    if saut:
                        messages.append(f"{ou}, bras à {t0:g} s : {saut[0]} sauterait d'un coup de {q0[saut[0]]:g} à "
                                        f"{q1[saut[0]]:g} rad (pose collée à une rampe) ; laissez du temps entre la "
                                        "rampe et la pose")
                    continue
                for nom in ARTICULATIONS_BRAS:
                    v = facteur * abs(q1[nom] - q0[nom]) / (t1 - t0)
                    if v > VITESSE_BRAS_MAX + 1e-9:
                        messages.append(f"{ou}, bras de {t0:g} à {t1:g} s : {nom} irait à {v:.2f} rad/s, "
                                        f"plus que {VITESSE_BRAS_MAX} ; espacez les poses")
                        break
        if d.get("gestes"):
            messages.append(f"{ou} : des gestes d'Unitree et des poses des bras ne vont pas ensemble "
                            "(rt/arm_sdk occupé, code 7400) ; gardez l'un ou l'autre")
    fins = []
    for p in sorted(d.get("pas") or [], key=lambda q: q["t"]):
        if fins and p["t"] < fins[-1] - 1e-9:
            messages.append(f"{ou}, pas à {p['t']:g} s : il commence avant la fin du pas précédent ({fins[-1]:g} s)")
        fins.append(p["t"] + p["duree_s"])
        if fins[-1] > duree + 1e-9:
            messages.append(f"{ou}, pas à {p['t']:g} s : il finit après la fin de la chorégraphie ({duree:g} s)")
    distance, rotation = deplacement_pas(d)
    if distance > DEPLACEMENT_MAX_M + 1e-6:
        messages.append(f"{ou} : les pas éloignent le robot de {distance:.2f} m de son départ, "
                        f"{DEPLACEMENT_MAX_M} m au plus")
    if rotation > ROTATION_MAX_RAD + 1e-6:
        messages.append(f"{ou} : les pas font tourner le robot de {rotation:.2f} rad en tout, "
                        f"{ROTATION_MAX_RAD:.2f} au plus")
    for cle in ("gestes", "led", "paroles"):
        for e in d.get(cle) or []:
            if e["t"] > duree + 1e-9:
                messages.append(f"{ou}, {cle} à {e['t']:g} s : après la fin ({duree:g} s)")
    for p in (bras or {}).get("poses", []):
        if p["t"] > duree + 1e-9:
            messages.append(f"{ou}, pose à {p['t']:g} s : après la fin ({duree:g} s)")
    return messages


def verifier_choregraphie(d):
    """Contrat. Erreurs d'une chorégraphie (schéma, puis règles), en français ; [] si elle est sûre."""
    from .validation import valider_donnees
    return valider_donnees("choregraphie", d)


def chemin_choregraphie(ident, dossier=None):
    """Contrat. Chemin du fichier d'une chorégraphie (id, ou chemin d'un .choregraphie.yaml)."""
    texte = str(ident)
    if texte.endswith(SUFFIXE_CHOREGRAPHIE) or "/" in texte:
        return Path(texte).expanduser()
    return Path(dossier or DOSSIER_CHOREGRAPHIES) / f"{texte}{SUFFIXE_CHOREGRAPHIE}"


def charger_choregraphie(ident, dossier=None):
    """Contrat. Lit et vérifie une chorégraphie ; ErreurLieu (messages en français) si elle est fausse."""
    chemin = chemin_choregraphie(ident, dossier)
    if not chemin.is_file():
        raise ErreurLieu(f"chorégraphie introuvable : {chemin}")
    donnees = lire_yaml(chemin.read_text(encoding="utf-8"), chemin.name)
    erreurs = verifier_choregraphie(donnees)
    if erreurs:
        raise ErreurLieu(erreurs)
    return donnees


def lister_choregraphies(dossier=None):
    """Contrat. Chemins des fichiers .choregraphie.yaml du dossier (défaut ~/robot-g1/choregraphies)."""
    racine = Path(dossier or DOSSIER_CHOREGRAPHIES)
    return sorted(racine.glob(f"*{SUFFIXE_CHOREGRAPHIE}")) if racine.is_dir() else []


# ---------------------------------------------------------------- outils de l'agent Pilotage (hors contrat)
# Partagés par le nœud pilotage (g1_pilotage), le faux G1 (g1_jumeau), le serveur et l'onglet Pilotage.

ACTIVITES = ("repos", "marche", "posture", "geste", "danse", "choregraphie", "arret")
MAITRES = ("guide", "pilotage")
DUREE_DANSE_INCONNUE_S = 60.0       # danse sans durée dans la liste du robot : fin attendue au plus tard
ARRET_BRAS_S = 1.0                  # ARRÊT pendant une chorégraphie : poids d'arm_sdk ramené à 0 en 1 s
INDICES_JAMBES = tuple(range(12))   # jamais écrites par le pilotage
TEXTES_CONFIRMATION = {
    "portique": ("Le robot va s'affaisser (amortir) ou relâcher ses moteurs (couple nul) : il doit être tenu "
                 "au portique. Cochez « robot au portique », puis confirmez une seconde fois dans les 10 s."),
    "zone_libre": ("Les pieds du robot vont bouger : dégagez une zone libre de 2 à 3 m autour de lui, gardez "
                   "la télécommande en main (c'est l'arrêt d'urgence), puis confirmez."),
}


def limites_marche(vitesse_max=None):
    """Plafonds de la marche (vx, vy, wz). vitesse_max (m/s, G1_VITESSE_MAX) les baisse dans la même
    proportion, comme le pont (navigation.launch.py vitesse_max:=) ; jamais au-dessus du contrat.
    ValueError pour une valeur absurde (non finie, nulle, négative ou plus que 0,4)."""
    if vitesse_max in (None, ""):
        return dict(LIMITES_MARCHE)
    try:
        v = float(vitesse_max)
    except (TypeError, ValueError):
        raise ValueError(f"vitesse maximale illisible : {vitesse_max!r} (ex. 0.2)") from None
    if not math.isfinite(v) or v <= 0 or v > LIMITES_MARCHE["vx"] + 1e-9:
        raise ValueError(f"vitesse maximale {vitesse_max} : il faut plus de 0 et au plus {LIMITES_MARCHE['vx']} m/s")
    k = v / LIMITES_MARCHE["vx"]
    return {axe: round(m * k, 6) for axe, m in LIMITES_MARCHE.items()}


def plafonner_marche(vx, vy, wz, limites=None):
    """(vx, vy, wz) ramenés sous les plafonds, avec leur signe ; une valeur non finie ou illisible
    donne un arrêt (0, 0, 0), comme le pont."""
    limites = limites or LIMITES_MARCHE
    sortie = []
    for v, axe in zip((vx, vy, wz), ("vx", "vy", "wz")):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            return (0.0, 0.0, 0.0)
        sortie.append(max(-limites[axe], min(limites[axe], float(v))))
    return tuple(sortie)


def lire_fsm(texte):
    """fsm_id de la réponse de 7001 GetFsmId ({"data": n}, comme le SDK) ; None si illisible."""
    d = _lire(texte)
    if d is None:
        return None
    v = d.get("data")
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def danses_pour_l_interface(liste):
    """Liste des danses lue dans le robot ({n: {nom, duree_s}}) → [{id, nom, duree_s, interdite, essayee,
    remarque}], dans l'ordre des numéros. Les interdites restent dans la liste (grisées par l'onglet)."""
    sortie = []
    for n in sorted(liste):
        info = liste[n]
        interdite = danse_interdite(n)
        if interdite:
            remarque = "interdite : le robot peut se coucher par terre" if n in (401, 402) else "interdite (inconnue)"
        elif n in DANSES_ESSAYEES:
            remarque = f"essayée par la communauté : {DANSES_ESSAYEES[n]}"
        elif n in DANSES_NON_ESSAYEES:
            remarque = f"jamais essayée : {DANSES_NON_ESSAYEES[n]} (au portique d'abord)"
        else:
            remarque = "inconnue de la communauté : au portique d'abord"
        sortie.append({"id": int(n), "nom": info.get("nom", ""), "duree_s": info.get("duree_s"),
                       "interdite": interdite, "essayee": n in DANSES_ESSAYEES, "remarque": remarque})
    return sortie


def evenements_choregraphie(d):
    """Événements ponctuels d'une chorégraphie, triés par temps : [(t, genre, donnees)], genre parmi
    pas_debut, pas_fin, geste, led, parole. Les poses des bras se suivent à part (poses_bras)."""
    evenements = []
    for p in d.get("pas") or []:
        evenements.append((p["t"], "pas_debut", p))
        evenements.append((p["t"] + p["duree_s"], "pas_fin", p))
    for g in d.get("gestes") or []:
        evenements.append((g["t"], "geste", g))
    for e in d.get("led") or []:
        evenements.append((e["t"], "led", e))
    for e in d.get("paroles") or []:
        evenements.append((e["t"], "parole", e))
    ordre = {"pas_fin": 0, "pas_debut": 1, "geste": 2, "led": 3, "parole": 4}
    return sorted(evenements, key=lambda e: (e[0], ordre[e[1]]))


def pas_en_cours(d, t):
    """Le pas de la chorégraphie actif à l'instant t (dict), ou None."""
    for p in d.get("pas") or []:
        if p["t"] <= t < p["t"] + p["duree_s"]:
            return p
    return None
