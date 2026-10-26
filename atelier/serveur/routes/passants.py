"""Routes des passants (vague 4, section 11.3 du plan) : agent Passants.

À écrire, par exemple : GET /api/passants/scenes (atelier.monde.scene.lister_scenes), et le
résumé des contacts du dernier banc. Les positions des piétons dans /ws/etat viennent déjà de
/pietons/etat quand il est publié (atelier/serveur/etat.py, livré par l'intégrateur).
"""
from fastapi import APIRouter

routeur = APIRouter(tags=["passants"])
