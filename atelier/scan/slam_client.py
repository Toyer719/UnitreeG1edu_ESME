"""Client du service slam_operate du G1 : scan 3D, relocalisation et navigation d'Unitree.

Le service tourne dans le robot. On lui parle avec le SDK Python d'Unitree (unitree_sdk2py) :
un numéro de commande et un texte JSON {"data": {...}}. Pendant qu'il travaille, il publie
deux sujets DDS de type std_msgs String_ (texte JSON) : rt/slam_info (position, avancement) et
rt/slam_key_info (événements : arrivée d'une navigation...).

    1801  commencer un scan (cartographie)        1201  mettre la navigation en pause
    1802  terminer le scan, enregistrer la carte  1202  reprendre la navigation
    1804  se repérer sur une carte enregistrée    1901  arrêter le service
    1102  aller à une position, en ligne droite

ATTENTION : les formats JSON viennent d'un projet tiers (G1_Hackason, septembre 2026) et ne
sont pas encore vérifiés sur notre G1. Chaque format est isolé dans une fonction marquée
« À vérifier sur le robot » : c'est là, et seulement là, qu'il faudra corriger.

Exemple :
    from atelier.scan.slam_client import ClientSlam, connexion
    client = ClientSlam(*connexion(faux=True))     # faux service sur « lo » (g1-slam faux-service)
    rep = client.debut_scan()
    print(rep.ok, rep.message)
"""
import json
import math
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from atelier.lieu.conversions import cap_vers_quaternion, quaternion_vers_cap

# ---------------------------------------------------------------- constantes du service

NOM_SERVICE = "slam_operate"
VERSION_API = "1.0.0.1"
DELAI_APPEL = 10.0          # s, attente maximale d'une réponse du robot

API_DEBUT_SCAN = 1801
API_FIN_SCAN = 1802
API_RELOCALISER = 1804
API_ALLER = 1102
API_PAUSE = 1201
API_REPRENDRE = 1202
API_ARRETER = 1901

NOMS_API = {
    API_DEBUT_SCAN: "commencer le scan",
    API_FIN_SCAN: "terminer le scan",
    API_RELOCALISER: "se repérer sur la carte",
    API_ALLER: "aller à une position",
    API_PAUSE: "pause",
    API_REPRENDRE: "reprendre",
    API_ARRETER: "arrêter le service",
}

SUJET_INFO = "rt/slam_info"           # ROS 2 : /slam_info
SUJET_INFO_CLE = "rt/slam_key_info"   # ROS 2 : /slam_key_info

# À vérifier sur le robot : dossier où 1802 enregistre la carte, sur le PC1 du robot
DOSSIER_CARTES_ROBOT = "/home/unitree/"

INTERFACE_ROBOT = "eno2"      # port Ethernet du PC relié au robot (setup/robot.sh)
INTERFACE_FAUX = "lo"         # le faux service tourne sur le PC lui-même
DOMAINE_ROBOT = 0             # le robot publie sur le domaine DDS 0

# Codes d'erreur des appels (unitree_sdk2py/rpc/internal.py)
ERREURS_RPC = {
    3001: "erreur inconnue",
    3102: "envoi impossible",
    3103: "commande non enregistrée dans le client",
    3104: "pas de réponse du service (délai dépassé)",
    3105: "réponse à une autre commande",
    3106: "réponse illisible",
    3201: "le service n'a pas pu répondre",
    3202: "erreur interne du service",
    3203: "commande inconnue du service",
    3204: "paramètres refusés par le service",
    3205: "commande refusée (bail)",
}


# ---------------------------------------------------------------- formats JSON (à vérifier)

def adresse_carte(nom):
    """Chemin de la carte sur le robot, à partir d'un nom (« test1 » ou « test1.pcd »).

    À vérifier sur le robot : dossier d'enregistrement (DOSSIER_CARTES_ROBOT) et extension.
    """
    nom = str(nom).strip()
    if not nom:
        raise ValueError("nom de carte vide")
    if "/" in nom:
        return nom                       # chemin complet donné tel quel
    if not nom.endswith(".pcd"):
        nom += ".pcd"
    return DOSSIER_CARTES_ROBOT + nom


def nom_fichier_carte(nom):
    """Nom du .pcd tel qu'on le note dans lieu.yaml (carte_unitree), ex. « test1.pcd »."""
    return adresse_carte(nom).rsplit("/", 1)[-1]


def pose_unitree(x, y, theta, z=0.0):
    """Pose au format du service : {x, y, z, q_x, q_y, q_z, q_w}.

    À vérifier sur le robot : noms des champs et repère (celui de la carte du scan).
    """
    qx, qy, qz, qw = cap_vers_quaternion(theta)
    return {"x": float(x), "y": float(y), "z": float(z),
            "q_x": qx, "q_y": qy, "q_z": qz, "q_w": qw}


def parametres_debut_scan(type_slam="indoor"):
    """1801. À vérifier sur le robot : {"data": {"slam_type": "indoor"}}."""
    return {"data": {"slam_type": type_slam}}


def parametres_fin_scan(nom):
    """1802. À vérifier sur le robot : {"data": {"address": "/home/unitree/test1.pcd"}}."""
    return {"data": {"address": adresse_carte(nom)}}


def parametres_relocaliser(x, y, theta, nom, z=0.0):
    """1804. À vérifier sur le robot : {"data": {x, y, z, q_x, q_y, q_z, q_w, address}}.

    (x, y, theta) : où se trouve le robot sur la carte nom, au moment de l'appel.
    """
    donnees = pose_unitree(x, y, theta, z)
    donnees["address"] = adresse_carte(nom)
    return {"data": donnees}


def parametres_aller(x, y, theta, z=0.0, mode=1):
    """1102. À vérifier sur le robot : {"data": {"targetPose": {...}, "mode": 1}}.

    Le robot va en ligne droite vers la pose et s'arrête devant un obstacle (moins de 8 à 10 m).
    """
    return {"data": {"targetPose": pose_unitree(x, y, theta, z), "mode": mode}}


def parametres_vides():
    """1201, 1202 et 1901. À vérifier sur le robot : {"data": {}}."""
    return {"data": {}}


@dataclass
class Reponse:
    """Résultat d'un appel : ok, code RPC (0 = transmis), données JSON du service, message."""
    ok: bool
    code: int
    donnees: Optional[dict] = None
    message: str = ""
    texte: str = ""


def lire_reponse(code, texte):
    """Interprète la réponse d'un appel : (code RPC, texte JSON) → Reponse.

    À vérifier sur le robot : forme du JSON de réponse. On suppose
    {"succeed": bool, "errorCode": int, "info": "..."} ; un champ absent n'est pas une erreur.
    """
    if code != 0:
        return Reponse(False, code, None, f"erreur {code} : {ERREURS_RPC.get(code, 'voir la documentation Unitree')}",
                       texte or "")
    texte = texte or ""
    try:
        donnees = json.loads(texte) if texte.strip() else {}
    except ValueError:
        return Reponse(True, 0, None, "réponse reçue (texte non JSON)", texte)
    if not isinstance(donnees, dict):
        return Reponse(True, 0, {"valeur": donnees}, "réponse reçue", texte)
    info = str(donnees.get("info", "") or "")
    erreur = donnees.get("errorCode", 0)
    if donnees.get("succeed") is False or (isinstance(erreur, (int, float)) and erreur != 0):
        message = f"refusé par le service (errorCode {erreur})" + (f" : {info}" if info else "")
        return Reponse(False, 0, donnees, message, texte)
    return Reponse(True, 0, donnees, info or "OK", texte)


def _chercher_cle(objet, cle):
    """Première valeur de « cle » dans un JSON imbriqué (dictionnaires et listes), ou None."""
    if isinstance(objet, dict):
        if cle in objet:
            return objet[cle]
        objets = objet.values()
    elif isinstance(objet, list):
        objets = objet
    else:
        return None
    for valeur in objets:
        trouve = _chercher_cle(valeur, cle)
        if trouve is not None:
            return trouve
    return None


def _json(texte):
    try:
        donnees = json.loads(texte)
    except (TypeError, ValueError):
        return None
    return donnees if isinstance(donnees, (dict, list)) else None


def lire_pose(texte):
    """Position du robot dans un message de slam_info → (x, y, theta), ou None.

    À vérifier sur le robot : on suppose une pose {x, y, z, q_x, q_y, q_z, q_w}, de préférence
    sous la clé « currentPose » (ex. {"type": "pos_info", "data": {"currentPose": {...}}}).
    """
    donnees = _json(texte)
    if donnees is None:
        return None
    pose = _chercher_cle(donnees, "currentPose")
    if not isinstance(pose, dict):
        pose = _chercher_cle(donnees, "pose")
    if not isinstance(pose, dict):
        return None
    try:
        x, y = float(pose["x"]), float(pose["y"])
        q = (float(pose.get("q_x", 0.0)), float(pose.get("q_y", 0.0)),
             float(pose.get("q_z", 0.0)), float(pose.get("q_w", 1.0)))
    except (KeyError, TypeError, ValueError):
        return None
    if not all(math.isfinite(v) for v in (x, y) + q):
        return None
    theta = quaternion_vers_cap(q) if any(q) else 0.0
    return (x, y, theta)


def lire_arrivee(texte):
    """Valeur de is_arrived dans un message de slam_key_info : True, False, ou None (absent).

    À vérifier sur le robot : on suppose {"type": "task_result", "task_result": {"is_arrived": true}} ;
    la clé is_arrived est cherchée à n'importe quel niveau du JSON.
    """
    donnees = _json(texte)
    if donnees is None:
        return None
    valeur = _chercher_cle(donnees, "is_arrived")
    if isinstance(valeur, bool):
        return valeur
    if isinstance(valeur, (int, float)):
        return bool(valeur)
    if isinstance(valeur, str):
        return valeur.strip().lower() in ("true", "1", "yes", "oui")
    return None


# ---------------------------------------------------------------- connexion DDS

_DDS = None            # (domaine, interface) ouvert dans ce processus
_VERROU_DDS = threading.Lock()


# Configuration CycloneDDS du faux service : interface lo seule, sans trace dans /tmp/cdds.LOG.
# CycloneDDS y désactive lui-même le multicast (message « not multicast-capable », normal).
CONFIG_LO = """<?xml version="1.0" encoding="UTF-8" ?>
<CycloneDDS><Domain Id="any"><General>
  <Interfaces><NetworkInterface name="$__IF_NAME__$" priority="default" multicast="default"/></Interfaces>
</General></Domain></CycloneDDS>"""


def connexion(faux=False, interface=None):
    """(interface, domaine) à utiliser.

    faux : interface « lo » et domaine $ROS_DOMAIN_ID (0 par défaut), pour le faux service ;
    sinon : le robot, sur eno2 (ou interface) et le domaine 0.
    """
    if faux:
        return (interface or INTERFACE_FAUX, int(os.environ.get("ROS_DOMAIN_ID") or 0))
    return (interface or os.environ.get("G1_INTERFACE") or INTERFACE_ROBOT, DOMAINE_ROBOT)


def initialiser_dds(interface, domaine):
    """Ouvre DDS sur cette interface et ce domaine, une seule fois par processus (SDK Unitree).

    Lève RuntimeError si DDS est déjà ouvert ailleurs dans ce processus.
    """
    global _DDS
    with _VERROU_DDS:
        if _DDS is not None:
            if _DDS != (int(domaine), interface):
                raise RuntimeError(f"DDS est déjà ouvert sur « {_DDS[1]} », domaine {_DDS[0]} : "
                                   "un seul réseau par programme")
            return
        from unitree_sdk2py.core import channel
        if interface == INTERFACE_FAUX:
            # Sur lo : la configuration du SDK, sans la trace dans /tmp/cdds.LOG
            channel.ChannelConfigHasInterface = CONFIG_LO
        channel.ChannelFactoryInitialize(int(domaine), interface)
        _DDS = (int(domaine), interface)


def dds_ouvert():
    """(domaine, interface) déjà ouvert dans ce processus, ou None."""
    return _DDS


# ---------------------------------------------------------------- le client

@dataclass
class _Ecoute:
    """Dernier message reçu sur un sujet."""
    texte: Optional[str] = None
    instant: float = 0.0          # time.monotonic() de la réception
    nombre: int = 0
    historique: list = field(default_factory=list)   # (instant, texte), les plus récents


class ClientSlam:
    """Client du service slam_operate, avec l'écoute de slam_info et slam_key_info.

    interface, domaine : voir connexion(). delai : attente maximale d'une réponse, en s.
    Les méthodes d'appel renvoient une Reponse ; elles attendent la réponse du service.
    """

    TAILLE_HISTORIQUE = 50

    def __init__(self, interface=INTERFACE_ROBOT, domaine=DOMAINE_ROBOT, delai=DELAI_APPEL, ecouter=True):
        from unitree_sdk2py.core.channel import ChannelSubscriber
        from unitree_sdk2py.idl.std_msgs.msg.dds_ import String_
        from unitree_sdk2py.rpc.client import Client

        initialiser_dds(interface, domaine)
        self.interface = interface
        self.domaine = int(domaine)
        self._verrou = threading.Lock()
        self._appel = threading.Lock()          # un seul appel à la fois
        self._info = _Ecoute()
        self._cle = _Ecoute()
        self._pose = None                       # (x, y, theta) lue dans slam_info
        self._instant_pose = 0.0

        self._client = Client(NOM_SERVICE, False)
        self._client.SetTimeout(delai)
        self._client._SetApiVerson(VERSION_API)
        for api in NOMS_API:
            self._client._RegistApi(api, 0)

        self._abonnements = []
        if ecouter:
            for sujet, rappel in ((SUJET_INFO, self._recevoir_info), (SUJET_INFO_CLE, self._recevoir_cle)):
                abonnement = ChannelSubscriber(sujet, String_)
                abonnement.Init(rappel, 10)
                self._abonnements.append(abonnement)

    # ------------------------------------------------ appels

    def appeler(self, api, parametres):
        """Envoie une commande (numéro, dict de paramètres) et renvoie la Reponse."""
        texte = json.dumps(parametres)
        with self._appel:
            try:
                code, donnees = self._client._Call(api, texte)
            except Exception as e:    # le SDK peut lever en cas de souci réseau
                return Reponse(False, 3001, None, f"erreur pendant l'appel : {e}")
        return lire_reponse(code, donnees)

    def debut_scan(self, type_slam="indoor"):
        return self.appeler(API_DEBUT_SCAN, parametres_debut_scan(type_slam))

    def fin_scan(self, nom):
        return self.appeler(API_FIN_SCAN, parametres_fin_scan(nom))

    def relocaliser(self, x, y, theta, nom):
        return self.appeler(API_RELOCALISER, parametres_relocaliser(x, y, theta, nom))

    def aller(self, x, y, theta):
        return self.appeler(API_ALLER, parametres_aller(x, y, theta))

    def pause(self):
        return self.appeler(API_PAUSE, parametres_vides())

    def reprendre(self):
        return self.appeler(API_REPRENDRE, parametres_vides())

    def arreter(self):
        return self.appeler(API_ARRETER, parametres_vides())

    # ------------------------------------------------ écoute

    def _noter(self, ecoute, texte):
        ecoute.texte = texte
        ecoute.instant = time.monotonic()
        ecoute.nombre += 1
        ecoute.historique.append((ecoute.instant, texte))
        del ecoute.historique[:-self.TAILLE_HISTORIQUE]

    def _recevoir_info(self, msg):
        pose = lire_pose(msg.data)
        with self._verrou:
            self._noter(self._info, msg.data)
            if pose is not None:
                self._pose = pose
                self._instant_pose = self._info.instant

    def _recevoir_cle(self, msg):
        with self._verrou:
            self._noter(self._cle, msg.data)

    def pose(self):
        """Dernière position lue dans slam_info : ((x, y, theta), instant monotonic), ou (None, 0)."""
        with self._verrou:
            return self._pose, self._instant_pose

    def info(self):
        """Dernier texte de slam_info : (texte ou None, instant, nombre de messages reçus)."""
        with self._verrou:
            return self._info.texte, self._info.instant, self._info.nombre

    def info_cle(self):
        """Dernier texte de slam_key_info : (texte ou None, instant, nombre de messages reçus)."""
        with self._verrou:
            return self._cle.texte, self._cle.instant, self._cle.nombre

    def infos_cle_depuis(self, instant):
        """Messages de slam_key_info reçus après cet instant (monotonic) : [(instant, texte)]."""
        with self._verrou:
            return [(t, texte) for t, texte in self._cle.historique if t > instant]

    def fermer(self):
        """Arrête l'écoute des sujets."""
        for abonnement in self._abonnements:
            try:
                abonnement.Close()
            except Exception:
                pass
        self._abonnements = []


# ---------------------------------------------------------------- arrivée d'un 1102

class SuiviArrivee:
    """Dit si la navigation 1102 envoyée à l'instant « envoi » est arrivée, d'après slam_key_info.

    Un is_arrived resté vrai d'un tronçon précédent est ignoré. Un « vrai » reçu après l'envoi
    n'est accepté que :
      - si un « faux » a été reçu depuis l'envoi (le robot a pris en compte la nouvelle cible) ;
      - sinon, si le robot est à moins de « tolerance » mètres de la cible et immobile depuis
        IMMOBILE_S secondes (un vrai périmé arrive pendant que le robot repart) ;
      - sinon, si la pose est inconnue, s'il est arrivé au moins DELAI_SANS_POSE s après l'envoi.
    arrive(pose) est à appeler régulièrement (une dizaine de fois par seconde).
    """

    DELAI_SANS_POSE = 1.0
    IMMOBILE_S = 0.4
    IMMOBILE_M = 0.03

    def __init__(self, client, envoi, cible, tolerance=0.5):
        self.client = client
        self.envoi = envoi
        self.cible = cible
        self.tolerance = tolerance
        self._lu_jusqua = envoi
        self._vu_faux = False
        self._vrais = []          # instants des « vrai » reçus depuis l'envoi
        self._poses = []          # (instant, x, y) des dernières positions vues

    def _immobile(self, pose, maintenant):
        self._poses.append((maintenant, pose[0], pose[1]))
        while len(self._poses) > 2 and self._poses[1][0] <= maintenant - self.IMMOBILE_S:
            self._poses.pop(0)
        if self._poses[0][0] > maintenant - self.IMMOBILE_S:
            return False          # pas encore assez de recul
        return all(math.hypot(x - pose[0], y - pose[1]) <= self.IMMOBILE_M for _, x, y in self._poses)

    def arrive(self, pose=None):
        maintenant = time.monotonic()
        immobile = self._immobile(pose, maintenant) if pose is not None else False
        for instant, texte in self.client.infos_cle_depuis(self._lu_jusqua):
            self._lu_jusqua = max(self._lu_jusqua, instant)
            valeur = lire_arrivee(texte)
            if valeur is False:
                self._vu_faux = True
                self._vrais = []
            elif valeur:
                self._vrais.append(instant)
        if not self._vrais:
            return False
        if self._vu_faux:
            return True
        if pose is not None:
            pres = math.hypot(pose[0] - self.cible[0], pose[1] - self.cible[1]) <= self.tolerance
            return pres and immobile
        return self._vrais[-1] - self.envoi >= self.DELAI_SANS_POSE
