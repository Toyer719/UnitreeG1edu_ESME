"""Routes du point principal (vague 4, section 11.2 du plan) : agent Point principal.

À écrire :
  GET  /api/lieux/{id}/principal
        {salle, nom, etage, x, y, theta, explicite, depart_synchro, repere_unitree, pose_unitree}
  PUT  /api/lieux/{id}/principal {salle?, x?, y?, theta?}
        atelier.lieu.principal.definir_principal : étiquette, pose et orientation ; accueil de lieu.yaml,
        nœud de même id et depart_robot synchronisés ; {enregistre, principal, rapport}.
Voir aussi routes/plan.py (PUT …/salles : 0 ou 2 principaux refusés) et routes/robot.py (pose par
défaut de POST /api/robot/reperer : atelier.lieu.principal.pose_de_reperage), du même agent.
"""
from fastapi import APIRouter

routeur = APIRouter(tags=["point principal"])
