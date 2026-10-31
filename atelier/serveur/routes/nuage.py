"""Nuages 3D et maillage de la carte extrudée (vague 5, sections 12.4 et 12.5 du plan) : agent Scan.

Squelette livré par l'agent Contrats : chaque route répond 501 « Pas encore fait » tant que l'agent
Scan ne l'a pas écrite. Contrat (formats : atelier.lieu.nuage, schéma nuage) :

  GET /api/lieux/{id}/etages/{e}/nuage[?source=scan|unitree]
        le binaire cartes/<e>.nuage.bin (ou <e>_unitree.nuage.bin) : application/octet-stream,
        Float32 x y z petit-boutistes, avec les en-têtes HTTP X-Nuage-Points, X-Nuage-Grille,
        X-Nuage-Bornes, X-Nuage-Source, X-Nuage-Date, X-Nuage-Session (entetes_http_nuage) et un
        ETag ; 404 en français s'il n'y a pas de nuage (« faites un scan, puis Utiliser cette carte »).
  GET /api/lieux/{id}/etages/{e}/nuage/info[?source=scan|unitree]
        l'en-tête JSON (cartes/<e>.nuage.json), plus {url, octets, modifie}.
  GET /api/lieux/{id}/etages/{e}/monde/maillage
        mondes/<e>_carte.stl (model/stl) : la carte extrudée du champ carte_extrudee du monde ; 404 sinon.
  GET /api/scan/nuage?lieu=L[&session=S][&apercu=1]
        le binaire du nuage d'une session (même format et mêmes en-têtes) : nuage_affichage.bin quand
        la session est traitée ; pendant le scan, ou avec apercu=1, l'aperçu en direct apercu_nuage.bin.
  GET /api/scan/nuage/info?lieu=L[&session=S][&apercu=1]
        l'en-tête JSON correspondant.
"""
from fastapi import APIRouter

from ..communs import pas_encore_fait

routeur = APIRouter(tags=["nuage 3D"])


@routeur.get("/api/lieux/{id_lieu}/etages/{etage}/nuage")
def nuage_etage(id_lieu: str, etage: str):
    """Nuage d'affichage de l'étage, en binaire."""
    raise pas_encore_fait("le nuage 3D d'un étage", "Scan", "12.4")


@routeur.get("/api/lieux/{id_lieu}/etages/{etage}/nuage/info")
def info_nuage_etage(id_lieu: str, etage: str):
    """En-tête du nuage d'affichage de l'étage."""
    raise pas_encore_fait("l'en-tête du nuage 3D d'un étage", "Scan", "12.4")


@routeur.get("/api/lieux/{id_lieu}/etages/{etage}/monde/maillage")
def maillage(id_lieu: str, etage: str):
    """Maillage STL de la carte extrudée de l'étage."""
    raise pas_encore_fait("le maillage de la carte extrudée", "Scan", "12.5")


@routeur.get("/api/scan/nuage")
def nuage_session():
    """Nuage d'affichage d'une session de scan (ou son aperçu en direct), en binaire."""
    raise pas_encore_fait("le nuage 3D d'une session de scan", "Scan", "12.4")


@routeur.get("/api/scan/nuage/info")
def info_nuage_session():
    """En-tête du nuage d'affichage d'une session de scan."""
    raise pas_encore_fait("l'en-tête du nuage 3D d'une session de scan", "Scan", "12.4")
