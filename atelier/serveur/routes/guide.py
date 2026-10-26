"""Routes du comportement du guide (vague 4, section 11.4 du plan) : agent Comportement du guide.

À écrire, par exemple :
  GET/PUT /api/lieux/{id}/guide   section guide de lieu.yaml (délais : atelier.lieu.comportement)
  GET     /api/guide/evenements   derniers /guide/evenement (aussi dans /ws/etat : evenements)
Voir aussi routes/simulation.py (POST /api/guide/aller avec accompagner et retour), du même agent.
"""
from fastapi import APIRouter

routeur = APIRouter(tags=["guide"])
