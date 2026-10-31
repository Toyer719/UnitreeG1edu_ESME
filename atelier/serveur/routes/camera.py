"""Flux de la caméra de poitrine (See3CAM) dans l'Atelier (vague 5, section 12.7 du plan) : agent Caméra.

Squelette livré par l'agent Contrats : chaque route répond 501 « Pas encore fait » tant que l'agent
Caméra ne l'a pas écrite. Les images viennent du pont ROS 2 du serveur (atelier/serveur/pont_ros.py),
abonné aux sujets de atelier.lieu.equipe.SUJETS_IMAGES (sensor_msgs/CompressedImage, JPEG). Contrat :

  GET /api/camera/image?source=poitrine|visiteurs
        la dernière image (image/jpeg), avec X-Image-Numero, X-Image-Age-S, X-Image-Largeur et
        X-Image-Hauteur ; 503 en français si aucune image depuis 2 s (caméra absente, nœud arrêté).
  GET /api/camera/flux?source=poitrine|visiteurs[&ips=10][&images=N]
        flux MJPEG : multipart/x-mixed-replace; boundary=image-g1 ; chaque partie : Content-Type
        image/jpeg, Content-Length, X-Image-Numero ; chaque image nouvelle une seule fois, au plus ips
        par seconde (10 par défaut, 15 au plus) ; images=N : fin après N images (tests) ; fin quand la
        page se ferme. Une balise <img src="/api/camera/flux?source=poitrine"> l'affiche telle quelle.
  GET /api/camera/etat
        {ros: {actif}, sources: {poitrine|visiteurs: {recue, numero, age_s, largeur, hauteur, octets,
         ips}}, noeud: dernier /camera_poitrine/etat (schéma etat_camera) ou null,
         visiteurs: {age_s, nombre} ou null}.
"""
from fastapi import APIRouter

from ..communs import pas_encore_fait

routeur = APIRouter(tags=["caméra"])


@routeur.get("/api/camera/image")
def image():
    """Dernière image de la caméra (JPEG)."""
    raise pas_encore_fait("l'image de la caméra", "Caméra", "12.7")


@routeur.get("/api/camera/flux")
def flux():
    """Flux MJPEG de la caméra."""
    raise pas_encore_fait("le flux de la caméra", "Caméra", "12.7")


@routeur.get("/api/camera/etat")
def etat_camera():
    """État de la caméra et des visiteurs vus."""
    raise pas_encore_fait("l'état de la caméra", "Caméra", "12.7")
