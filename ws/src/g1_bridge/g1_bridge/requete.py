"""
Format des ordres de marche du G1 : unitree_api/msg/Request sur /api/sport/request.

Rempli exactement comme LocoClient::SetVelocity de unitree_ros2 (g1_loco_client.hpp et
base_client.hpp) et LocoClient.SetVelocity du SDK Python (unitree_sdk2py/g1/loco), section 10.3
du plan :
  - header.identity.id : time.monotonic_ns() (GetSystemUptimeInNanoseconds du C++),
    strictement croissant ;
  - header.identity.api_id : 7105 (SetVelocity) ; header.lease.id : 0 ;
    header.policy.priority : 0 ; header.policy.noreply : false ;
  - parameter : json.dumps({"velocity": [vx, vy, wz], "duration": d}), en flottants : c'est le
    texte du SDK Python, octet pour octet (nlohmann, en C++, trie les clés et écrit les
    float en double, mais les deux se lisent pareil) ;
  - binary : vide.
L'arrêt est {"velocity": [0.0, 0.0, 0.0], "duration": 1.0} : StopMove du SDK.

Ce module ne dépend pas de ROS : remplir_requete accepte tout objet qui a les champs de
unitree_api/msg/Request (le vrai message, ou un faux dans les tests).
"""
import json
import threading
import time

# Service de marche du G1 (« sport ») et ordre SetVelocity
SUJET_REQUETE = '/api/sport/request'
SUJET_REPONSE = '/api/sport/response'
API_SET_VELOCITY = 7105

# Durée d'un arrêt : StopMove du SDK appelle SetVelocity(0, 0, 0) avec sa durée par défaut, 1 s
DUREE_ARRET_S = 1.0


def parametre_vitesse(vx, vy, wz, duree):
    """Texte JSON du champ parameter d'un 7105, identique à LocoClient.SetVelocity du SDK."""
    p = {}
    p['velocity'] = [float(vx), float(vy), float(wz)]
    p['duration'] = float(duree)
    return json.dumps(p)


def parametre_arret(duree=DUREE_ARRET_S):
    """Texte JSON d'un arrêt : vitesses nulles pendant duree (1 s, comme StopMove)."""
    return parametre_vitesse(0.0, 0.0, 0.0, duree)


def remplir_requete(requete, identifiant, parametre, api_id=API_SET_VELOCITY):
    """Remplit un unitree_api/msg/Request comme le client C++ et le SDK Python ; le renvoie."""
    entete = requete.header
    entete.identity.id = int(identifiant)
    entete.identity.api_id = int(api_id)
    entete.lease.id = 0
    entete.policy.priority = 0
    entete.policy.noreply = False
    requete.parameter = str(parametre)
    requete.binary = []
    return requete


class Identifiants:
    """identity.id des requêtes : time.monotonic_ns(), strictement croissant, même entre fils."""

    def __init__(self, horloge_ns=time.monotonic_ns):
        self._horloge_ns = horloge_ns
        self._dernier = 0
        self._verrou = threading.Lock()

    def __call__(self):
        with self._verrou:
            self._dernier = max(int(self._horloge_ns()), self._dernier + 1)
            return self._dernier
