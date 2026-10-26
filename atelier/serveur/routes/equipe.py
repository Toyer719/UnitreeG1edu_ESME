"""Routes de l'équipe (vague 4, section 11.6 du plan) : agent Équipe.

À écrire : GET/PUT /api/lieux/{id}/personnalites, …/dialogues, …/camera (atelier.lieu.equipe), et
l'essai d'une phrase du chatbot (réponse et action, sans robot). Publications ROS 2 possibles par
le pont du serveur : etat.pont.publier_json(sujet, donnees) sur les sujets de PUBLICATIONS_JSON
(atelier/serveur/pont_ros.py, livré par l'intégrateur).
"""
from fastapi import APIRouter

routeur = APIRouter(tags=["équipe"])
