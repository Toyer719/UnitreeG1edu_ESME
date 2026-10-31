"""ARRÊT global de l'Atelier (vague 5, section 12.4 du plan) : agent Coquille.

Squelette livré par l'agent Contrats : chaque route répond 501 « Pas encore fait » tant que l'agent
Coquille ne l'a pas écrite. Contrat :

  POST /api/arret {mode?: simu|reel|repetition, raison?: texte}
        arrête tout, en parallèle, en moins de 1 s même si une partie ne répond pas :
          guide     /guide/stop (etat.pont.stop()) ;
          teleop    vitesse nulle sur /cmd_vel si la téléopération simulée a servi (app.state.teleop) ;
          pilotage  POST /arret du nœud pilotage (routes/pilotage.py, appeler_noeud, 0,6 s au plus),
                    seulement si le nœud pilotage tourne ou est joignable ;
          verrou    en mode reel ou repetition (champ mode, ou mode de la navigation qui tourne) :
                    /pont/arret true (etat.pont.bloquer(True)) ; jamais en simulation.
        Réponse 200 : {arrete, mode, verrou, duree_s, parties: {guide|teleop|pilotage|verrou:
        {ok: true|false|null, detail}}, message} ; ok null : partie sans objet (rien ne tournait).
  POST /api/arret/debloquer
        /pont/arret false : {verrou: false, ecoute, message} ; 503 sans pont ROS 2.
  GET  /api/arret
        {verrou, depuis, mode, par} : le dernier verrou posé par l'Atelier (aussi dans /ws/etat, champ arret).
"""
from fastapi import APIRouter

from ..communs import pas_encore_fait

routeur = APIRouter(tags=["arrêt"])


@routeur.post("/api/arret")
def arreter_tout():
    """ARRÊT : guide, téléopération, pilotage, et verrou du pont en mode réel ou répétition."""
    raise pas_encore_fait("l'ARRÊT global", "Coquille", "12.4")


@routeur.post("/api/arret/debloquer")
def debloquer():
    """Retire le verrou posé par l'ARRÊT (/pont/arret false)."""
    raise pas_encore_fait("le déblocage après l'ARRÊT", "Coquille", "12.4")


@routeur.get("/api/arret")
def lire_arret():
    """Le dernier verrou posé par l'ARRÊT de l'Atelier."""
    raise pas_encore_fait("l'état de l'ARRÊT", "Coquille", "12.4")
