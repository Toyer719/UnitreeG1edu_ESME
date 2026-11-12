"""Masque Keepout des zones interdites d'un étage (cartes/<etage>_interdit.pgm + .yaml).

Le masque a exactement la taille, la résolution et l'origine de la carte de l'étage (contrat 4.1),
qu'elle vienne du monde inventé ou du scan. Pixels : 0 dans une zone interdite (Nav2 en fait
un obstacle infranchissable), 254 partout ailleurs. Un pixel est dans la zone si son centre est
à l'intérieur du polygone (règle pair-impair).

Un étage sans zone interdite reçoit quand même un masque, tout libre : la navigation peut
toujours charger le même fichier.
"""
import numpy as np

from atelier.lieu import (InfoCarte, charger_info_carte, charger_zones, chemin_carte, chemin_interdit,
                          enregistrer_carte)

from .carte import LIBRE, OCCUPE, fenetre_pixels


def pixels_polygone(info, polygone):
    """Masque (lignes, colonnes, booléens) des pixels dont le centre est dans le polygone."""
    sommets = np.asarray(polygone, dtype=float)
    fen = fenetre_pixels(info, *sommets.min(axis=0), *sommets.max(axis=0))
    if fen is None:
        return None
    lignes, colonnes, X, Y = fen
    dedans = np.zeros(X.shape, dtype=bool)
    for (x1, y1), (x2, y2) in zip(sommets, np.roll(sommets, -1, axis=0)):
        if y1 == y2:
            continue          # côté horizontal : ne croise jamais la demi-droite
        croise = (y1 > Y) != (y2 > Y)
        x_croisement = x1 + (Y - y1) * (x2 - x1) / (y2 - y1)
        dedans ^= croise & (X < x_croisement)
    return lignes, colonnes, dedans


def info_masque(info_carte, image):
    """InfoCarte du masque : même résolution, origine et taille que la carte, autre image."""
    return InfoCarte(image=image, resolution=info_carte.resolution, origin=tuple(info_carte.origin),
                     largeur=info_carte.largeur, hauteur=info_carte.hauteur)


def fabriquer_masque_interdit(zones, etage, info_carte, image="interdit.pgm"):
    """Zones → (InfoCarte, image numpy uint8) du masque Keepout de l'étage, aligné sur info_carte."""
    info = info_masque(info_carte, image)
    masque = np.full((info.hauteur, info.largeur), LIBRE, dtype=np.uint8)
    for zone in zones.interdites:
        if zone.etage != etage:
            continue
        resultat = pixels_polygone(info, zone.polygone)
        if resultat is not None:
            lignes, colonnes, dedans = resultat
            masque[lignes, colonnes][dedans] = OCCUPE
    return info, masque


def ecrire_masque_interdit(lieu, etage, zones=None, info_carte=None):
    """Écrit cartes/<etage>_interdit.pgm et .yaml. La carte de l'étage doit déjà exister (son
    .yaml donne la taille et l'origine), sauf si info_carte est donné.
    Renvoie (chemin du .yaml, nombre de zones interdites de l'étage)."""
    if zones is None:
        zones = charger_zones(lieu)
    if info_carte is None:
        info_carte = charger_info_carte(chemin_carte(lieu, etage))
    chemin = chemin_interdit(lieu, etage)
    info, masque = fabriquer_masque_interdit(zones, etage, info_carte, image=f"{etage}_interdit.pgm")
    enregistrer_carte(chemin, info, masque)
    return chemin, sum(1 for z in zones.interdites if z.etage == etage)
