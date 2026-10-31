"""Liaison avec le robot, pour l'écran d'accueil en mode Réel (vague 5, section 12.4 du plan) : agent Coquille.

Squelette livré par l'agent Contrats : répond 501 « Pas encore fait » tant que l'agent Coquille ne
l'a pas écrite. Contrat :

  GET /api/robot/liaison
        {interface, cable, adresse_pc, pc1: {adresse, repond, ms}, jetson: {adresse, repond, ms},
         ros: {domaine, cyclonedds, actif}, pret, message, duree_s}
        cable : /sys/class/net/<interface>/carrier (ATELIER_INTERFACE_ROBOT, eno2 par défaut) ;
        pc1 (ATELIER_PC1, 192.168.123.161) et jetson (ATELIER_JETSON, 192.168.123.164) : un ping
        (ping -c 1 -W 1), les deux en parallèle, seulement si le câble est branché (sinon repond null) ;
        ros : ROS_DOMAIN_ID du serveur, interface de CYCLONEDDS_URI (setup/robot.sh), pont ROS 2 actif ;
        réponse en 1,5 s au plus ; pret : câble, PC1 qui répond et domaine 0 ; message en français
        qui dit quoi faire. Rien n'est envoyé au robot à part ces deux pings.
"""
from fastapi import APIRouter

from ..communs import pas_encore_fait

routeur = APIRouter(tags=["robot"])


@routeur.get("/api/robot/liaison")
def liaison():
    """Câble, PC1 et Jetson joignables, domaine ROS : les vérifications de l'accueil en mode Réel."""
    raise pas_encore_fait("la liaison avec le robot", "Coquille", "12.4")
