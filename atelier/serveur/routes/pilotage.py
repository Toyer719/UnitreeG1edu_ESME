"""Routes du pilotage (vague 4, section 11.5 du plan) : agent Pilotage et danses.

À écrire : /api/pilotage/* (état, verrou, posture, marche, gestes, voix, LED, danses, chorégraphies,
arrêt) et le WebSocket /ws/pilotage (joystick avec homme mort), relayés vers l'API HTTP et WebSocket
du nœud pilotage (paquet g1_pilotage) à l'adresse $G1_PILOTAGE_URL (défaut http://127.0.0.1:8010),
avec le jeton $G1_PILOTAGE_JETON dans l'en-tête X-Jeton. Règles de sécurité :
atelier.lieu.pilotage (refus_commande, confirmation_requise).
"""
from fastapi import APIRouter

routeur = APIRouter(tags=["pilotage"])
