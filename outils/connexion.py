"""Connexion au G1 (ou au simulateur) et vérification qu'il répond."""
import time

from unitree_sdk2py.core.channel import ChannelFactoryInitialize, ChannelSubscriber
from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowState_

DELAI_CONNEXION = 5.0  # s

# Codes d'erreur des appels au robot (unitree_sdk2py/rpc/internal.py)
ERREURS = {
    3102: "envoi impossible",
    3103: "fonction non disponible sur ce robot",
    3104: "pas de réponse du robot",
}


def expliquer(code):
    if code == 0:
        return "OK"
    return f"erreur {code} ({ERREURS.get(code, 'voir la documentation Unitree')})"


class Lecteur:
    def __init__(self):
        self.dernier = None
        self.nb = 0

    def recevoir(self, msg: LowState_):
        self.dernier = msg
        self.nb += 1


def connecter(interface):
    """Ouvre la connexion DDS et attend l'état du robot. Renvoie le Lecteur, ou None."""
    ChannelFactoryInitialize(0, interface)
    lecteur = Lecteur()
    abonnement = ChannelSubscriber("rt/lowstate", LowState_)
    abonnement.Init(lecteur.recevoir, 10)
    lecteur.abonnement = abonnement

    debut = time.time()
    while lecteur.dernier is None:
        if time.time() - debut > DELAI_CONNEXION:
            print(f"Aucune donnée du robot sur « {interface} » après {DELAI_CONNEXION:.0f} s.")
            if interface == "lo":
                print("Le simulateur est-il lancé ? (g1-sim dans un autre terminal)")
            else:
                print("Robot allumé ? Câble branché ? Avez-vous lancé : source ~/robot-g1/setup/robot.sh")
            return None
        time.sleep(0.1)
    return lecteur
