"""Flux de la caméra de poitrine (See3CAM) dans l'Atelier (vague 5, section 12.7 du plan) : agent Caméra.

Les images viennent du pont ROS 2 du serveur (atelier/serveur/pont_ros.py), abonné aux sujets de
atelier.lieu.equipe.SUJETS_IMAGES (sensor_msgs/CompressedImage, JPEG) ; il garde la dernière de
chacun. Contrat (section 12.4) :

  GET /api/camera/image?source=poitrine|visiteurs
        la dernière image (image/jpeg), avec X-Image-Numero, X-Image-Age-S, X-Image-Largeur et
        X-Image-Hauteur ; 503 en français si aucune image depuis 2 s (caméra absente, nœud arrêté).
  GET /api/camera/flux?source=poitrine|visiteurs[&ips=10][&images=N]
        flux MJPEG : multipart/x-mixed-replace; boundary=image-g1 ; chaque partie : Content-Type
        image/jpeg, Content-Length, X-Image-Numero ; chaque image nouvelle une seule fois, au plus ips
        par seconde (10 par défaut, 15 au plus) ; la dernière image d'abord si elle a moins de 2 s ;
        images=N : fin après N images (tests) ; fin quand la page se ferme. Une balise
        <img src="/api/camera/flux?source=poitrine"> l'affiche telle quelle. 503 sans ROS 2.
  GET /api/camera/etat
        {ros: {actif, erreur}, sources: {poitrine|visiteurs: {recue, numero, age_s, largeur, hauteur,
         octets, ips}}, noeud: dernier /camera_poitrine/etat (schéma etat_camera) ou null,
         visiteurs: {age_s, nombre} ou null, messages: {poitrine|visiteurs: phrase ou null},
         flux_ouverts}. messages dit en français pourquoi une source n'a pas d'image, et quoi faire.

Ces routes ne commandent rien : elles montrent ce que la caméra publie.
"""
import asyncio
import time
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import Response, StreamingResponse

from atelier.equipe.images import FRONTIERE, SOURCES_IMAGES, Cadence, entetes_image, partie_mjpeg
from atelier.lieu.equipe import SUJET_ETAT_CAMERA

from ..communs import ErreurAtelier

routeur = APIRouter(tags=["caméra"])

AGE_MAX_S = 2.0           # une image plus vieille ne compte plus (503, et pas envoyée au début d'un flux)
IPS_DEFAUT = 10.0
IPS_MAX = 15.0
PAS_S = 0.02              # le flux regarde s'il y a une image nouvelle toutes les 20 ms
DECONNEXION_S = 0.5       # et si la page est fermée toutes les 0,5 s
SUJET_VISITEURS = "/visiteurs/detectes"
_flux = {"ouverts": 0}    # flux MJPEG en cours (état, tests : la page fermée les arrête)


def _pont(request):
    return request.app.state.atelier.pont


def _sujet(source):
    if source not in SOURCES_IMAGES:
        raise ErreurAtelier(400, f"Source « {source} » inconnue : {' ou '.join(SOURCES_IMAGES)}.")
    return SOURCES_IMAGES[source]


def pourquoi_pas_d_image_detail(pont, source, image, maintenant=None):
    """(phrase courte, détail technique) qui disent pourquoi une source n'a pas d'image récente, et quoi
    faire ; (None, None) si elle en a une. La phrase s'affiche (vague 5, I10 : ni nœud, ni sujet, ni
    commande) ; le détail technique va dans l'infobulle et les détails des erreurs."""
    maintenant = time.monotonic() if maintenant is None else maintenant
    if not pont.actif:
        return ("Pas d'image : l'Atelier n'est pas relié à ROS 2.", pont.erreur or "pont ROS 2 du serveur arrêté")
    if getattr(pont, "erreur_images", None):
        return "Pas d'image : " + pont.erreur_images + ".", None
    if image is not None and image.age(maintenant) <= AGE_MAX_S:
        return None, None
    noeud = pont.dernier(SUJET_ETAT_CAMERA) if source == "poitrine" else None
    if noeud and not noeud.get("perime") and noeud.get("erreur"):
        return f"Pas d'image : {noeud['erreur']}.", "message du nœud camera_usb (/camera_poitrine/etat)"
    if image is not None:
        if source == "poitrine":
            return (f"Pas d'image depuis {image.age(maintenant):.0f} s : la caméra s'est arrêtée (débranchée ?).",
                    "le nœud camera_usb ne publie plus /camera_poitrine/image/compressed")
        return (f"Pas d'image des visiteurs depuis {image.age(maintenant):.0f} s.",
                "g1-visiteurs ne publie plus ses images")
    if source == "poitrine":
        return ("Pas d'image : la caméra de poitrine n'envoie rien. Est-elle branchée au robot, et le robot lancé ?",
                "le nœud de la caméra (camera_usb) ne publie pas. Sur le robot : g1-jetson demarrer, la See3CAM "
                "branchée sur le Jetson ; sur ce PC : ros2 run g1_equipe camera_usb. Même ROS_DOMAIN_ID que "
                "l'Atelier ?")
    return ("Pas d'image des visiteurs : la détection des visiteurs ne tourne pas.",
            "lancez g1-visiteurs --image (cadres dessinés sur l'image)")


def pourquoi_pas_d_image(pont, source, image, maintenant=None):
    """La phrase courte de pourquoi_pas_d_image_detail, ou None si la source a une image récente."""
    return pourquoi_pas_d_image_detail(pont, source, image, maintenant)[0]


def _sans_image(pont, source, image, maintenant=None):
    """ErreurAtelier 503 : la phrase courte, et le détail technique dans « sortie » (le journal)."""
    message, detail = pourquoi_pas_d_image_detail(pont, source, image, maintenant)
    return ErreurAtelier(503, message, sortie=detail)


@routeur.get("/api/camera/image")
def image(request: Request, source: str = "poitrine"):
    """Dernière image de la caméra (JPEG) ; 503 en français sans image depuis 2 s."""
    sujet = _sujet(source)
    pont = _pont(request)
    derniere = pont.derniere_image(sujet) if pont.actif else None
    maintenant = time.monotonic()
    message = pourquoi_pas_d_image(pont, source, derniere, maintenant)
    if message:
        raise _sans_image(pont, source, derniere, maintenant)
    return Response(content=derniere.octets, media_type="image/jpeg", headers=entetes_image(derniere, maintenant))


@routeur.get("/api/camera/flux")
async def flux(request: Request, source: str = "poitrine", ips: float = IPS_DEFAUT, images: Optional[int] = None):
    """Flux MJPEG de la caméra : chaque image nouvelle une fois, au plus ips par seconde."""
    sujet = _sujet(source)
    if not ips > 0:
        raise ErreurAtelier(400, f"ips={ips:g} : il faut un nombre d'images par seconde plus grand que 0 "
                                 f"({IPS_MAX:g} au plus).")
    if images is not None and images < 1:
        raise ErreurAtelier(400, f"images={images} : il faut au moins 1 (ou rien : flux sans fin).")
    pont = _pont(request)
    if not pont.actif:
        raise _sans_image(pont, source, None)
    frequence = min(float(ips), IPS_MAX)

    async def generer():
        _flux["ouverts"] += 1
        envoyees, dernier = 0, 0
        cadence = Cadence(frequence)     # au plus « ips » images par seconde, sans en perdre à 10 Hz
        surveillance = time.monotonic() + DECONNEXION_S
        try:
            while True:
                maintenant = time.monotonic()
                if maintenant >= surveillance:
                    if await request.is_disconnected():
                        return
                    surveillance = maintenant + DECONNEXION_S
                image = pont.derniere_image(sujet)
                if (image is not None and image.numero != dernier
                        and (dernier or image.age(maintenant) <= AGE_MAX_S) and cadence.garder(maintenant)):
                    yield partie_mjpeg(image)
                    dernier = image.numero
                    envoyees += 1
                    if images is not None and envoyees >= images:
                        return
                    continue
                await asyncio.sleep(PAS_S)
        finally:
            _flux["ouverts"] -= 1

    return StreamingResponse(generer(), media_type=f"multipart/x-mixed-replace; boundary={FRONTIERE}",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@routeur.get("/api/camera/etat")
def etat_camera(request: Request):
    """État de la caméra : images reçues par le pont ROS 2, dernier état du nœud, visiteurs vus."""
    pont = _pont(request)
    actif = bool(pont.actif)
    maintenant = time.monotonic()
    sources, messages, details = {}, {}, {}
    for source, sujet in SOURCES_IMAGES.items():
        images = pont.images.get(sujet)
        sources[source] = images.etat(maintenant) if images is not None else {
            "recue": False, "numero": 0, "age_s": None, "largeur": None, "hauteur": None, "octets": None, "ips": 0.0}
        messages[source], details[source] = pourquoi_pas_d_image_detail(
            pont, source, pont.derniere_image(sujet) if actif else None, maintenant)
    visiteurs = pont.dernier(SUJET_VISITEURS) if actif else None
    return {"ros": {"actif": actif, "erreur": pont.erreur},
            "sources": sources,
            "noeud": pont.dernier(SUJET_ETAT_CAMERA) if actif else None,
            "visiteurs": None if visiteurs is None else {
                "age_s": visiteurs.get("age_recu_s"), "nombre": len(visiteurs.get("personnes") or []),
                "perime": visiteurs.get("perime")},
            "messages": messages,
            "details": details,
            "flux_ouverts": _flux["ouverts"]}
