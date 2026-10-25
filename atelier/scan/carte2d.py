"""Nuage 3D du scan (.pcd) → carte 2D de navigation (.pgm + .yaml, format Nav2 de la section 4.1).

Étapes :
  1. trouver la hauteur du sol (un point bas du nuage, ou --sol) ;
  2. garder la tranche de 0,1 à 1,5 m au-dessus du sol, et la projeter sur une grille de 5 cm ;
  3. une case est occupée si au moins POINTS_MIN points y tombent ;
  4. nettoyer par une ouverture morphologique par aire : on retire les taches isolées de moins
     de AIRE_MIN cases. (Une ouverture classique, érosion puis dilatation, effacerait aussi les
     murs vus d'un seul côté, qui ne font qu'une case d'épaisseur dans un scan.)
  5. l'intérieur de l'emprise est libre (254), les cases occupées à 0, le reste inconnu (205).

L'emprise est celle du monde de l'étage s'il existe (la carte du scan a alors la même taille
et la même origine que celle du monde, et que le masque des zones), sinon celle du nuage.
Toutes les conversions mètres ↔ pixels passent par atelier.lieu.conversions.
"""
import math
from collections import deque
from pathlib import Path

import numpy as np

from atelier.lieu import (ErreurLieu, charger_carte, charger_fiche, charger_monde, chemin_carte, chemin_pcd,
                          dans_image, enregistrer_carte, enregistrer_fiche, info_carte_pour_emprise,
                          monde_vers_pixel, pixel_vers_monde)

TRANCHE = (0.1, 1.5)       # m au-dessus du sol
RESOLUTION = 0.05          # m par pixel
POINTS_MIN = 2             # points pour qu'une case soit occupée
AIRE_MIN = 4               # cases : une tache occupée plus petite est du bruit
LIBRE, INCONNU, OCCUPE = 254, 205, 0


class ErreurCarte2d(Exception):
    """Nuage vide, illisible ou sans rien dans la tranche ; le message dit quoi corriger."""


def estimer_sol(points):
    """Hauteur du sol : le 1er centile des z (le sol, ou le pied des murs s'il n'a pas été vu)."""
    if len(points) == 0:
        raise ErreurCarte2d("nuage vide")
    return float(np.percentile(points[:, 2], 1.0))


def projeter(points, info, sol, tranche=TRANCHE):
    """Nombre de points de la tranche par pixel : tableau (hauteur, largeur) d'entiers."""
    z = points[:, 2] - sol
    dans = points[(z >= tranche[0]) & (z <= tranche[1])]
    compte = np.zeros((info.hauteur, info.largeur), dtype=np.int32)
    if len(dans) == 0:
        return compte
    colonnes, lignes = monde_vers_pixel(dans[:, 0], dans[:, 1], info)
    ok = dans_image(colonnes, lignes, info)
    np.add.at(compte, (np.asarray(lignes)[ok], np.asarray(colonnes)[ok]), 1)
    return compte


def ouverture_par_aire(occupe, aire_min=AIRE_MIN):
    """Retire les composantes connexes (8 voisins) de moins de aire_min pixels."""
    occupe = np.asarray(occupe, dtype=bool)
    if aire_min <= 1:
        return occupe.copy()
    hauteur, largeur = occupe.shape
    vu = np.zeros_like(occupe)
    garde = np.zeros_like(occupe)
    for depart in zip(*np.nonzero(occupe)):
        if vu[depart]:
            continue
        composante, file = [], deque([depart])
        vu[depart] = True
        while file:
            l, c = file.popleft()
            composante.append((l, c))
            for dl in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    nl, nc = l + dl, c + dc
                    if 0 <= nl < hauteur and 0 <= nc < largeur and occupe[nl, nc] and not vu[nl, nc]:
                        vu[nl, nc] = True
                        file.append((nl, nc))
        if len(composante) >= aire_min:
            lignes, colonnes = zip(*composante)
            garde[list(lignes), list(colonnes)] = True
    return garde


def dilater(masque, rayon=1):
    """Dilatation par un carré de (2 rayon + 1) pixels de côté."""
    masque = np.asarray(masque, dtype=bool)
    if rayon <= 0:
        return masque.copy()
    resultat = masque.copy()
    h, w = masque.shape
    for dl in range(-rayon, rayon + 1):
        for dc in range(-rayon, rayon + 1):
            source = masque[max(0, -dl):h - max(0, dl), max(0, -dc):w - max(0, dc)]
            resultat[max(0, dl):h - max(0, -dl), max(0, dc):w - max(0, -dc)] |= source
    return resultat


def emprise_du_nuage(points, sol, tranche=TRANCHE):
    """(xmin, ymin, xmax, ymax) des points de la tranche, arrondi à la résolution."""
    z = points[:, 2] - sol
    dans = points[(z >= tranche[0]) & (z <= tranche[1])]
    if len(dans) == 0:
        raise ErreurCarte2d(f"aucun point entre {tranche[0]:g} et {tranche[1]:g} m au-dessus du sol "
                            f"(sol trouvé à {sol:.2f} m) : vérifiez le nuage, ou donnez --sol")
    xmin, ymin = np.floor(dans[:, :2].min(axis=0) / RESOLUTION) * RESOLUTION
    xmax, ymax = np.ceil(dans[:, :2].max(axis=0) / RESOLUTION) * RESOLUTION
    return float(xmin), float(ymin), float(xmax), float(ymax)


def fabriquer_carte(points, emprise=None, sol=None, tranche=TRANCHE, points_min=POINTS_MIN,
                    aire_min=AIRE_MIN, image="carte.pgm"):
    """Nuage (N, 3) → (InfoCarte, image uint8). emprise : (xmin, ymin, xmax, ymax), défaut : le nuage."""
    points = np.asarray(points, dtype=float).reshape(-1, 3)
    if len(points) == 0:
        raise ErreurCarte2d("nuage vide")
    sol = estimer_sol(points) if sol is None else float(sol)
    if emprise is None:
        emprise = emprise_du_nuage(points, sol, tranche)
    info = info_carte_pour_emprise(*emprise, resolution=RESOLUTION, marge=1, image=image)
    occupe = ouverture_par_aire(projeter(points, info, sol, tranche) >= points_min, aire_min)
    # Intérieur de l'emprise libre, marge inconnue, puis les obstacles
    x, y = pixel_vers_monde(*np.meshgrid(np.arange(info.largeur), np.arange(info.hauteur)), info)
    dedans = (x >= emprise[0]) & (x <= emprise[2]) & (y >= emprise[1]) & (y <= emprise[3])
    carte = np.full((info.hauteur, info.largeur), INCONNU, dtype=np.uint8)
    carte[dedans] = LIBRE
    carte[occupe] = OCCUPE
    return info, carte, sol


# ---------------------------------------------------------------- comparaison de deux cartes

def comparer(info_a, image_a, info_b, image_b, tolerance_px=1):
    """Compare la carte a (le scan) à la carte b (la référence), case par case, en mètres.

    recouvrement : part des pixels occupés de a qui tombent sur un pixel occupé de b, à
                   tolerance_px pixels près ;
    couverture   : part des pixels occupés de b qui ont un pixel occupé de a à moins de
                   tolerance_px pixels (le scan ne voit pas l'intérieur des murs ni les pièces
                   fermées : elle est plus basse).
    """
    def occupes(info, image):
        lignes, colonnes = np.nonzero(np.asarray(image) == OCCUPE)
        return pixel_vers_monde(colonnes, lignes, info)

    def part(info_source, image_source, info_cible, image_cible):
        x, y = occupes(info_source, image_source)
        if len(x) == 0:
            return 0.0, 0
        masque = dilater(np.asarray(image_cible) == OCCUPE, tolerance_px)
        colonnes, lignes = monde_vers_pixel(x, y, info_cible)
        ok = dans_image(colonnes, lignes, info_cible)
        touche = np.zeros(len(x), dtype=bool)
        touche[ok] = masque[np.asarray(lignes)[ok], np.asarray(colonnes)[ok]]
        return float(touche.mean()), len(x)

    recouvrement, n_a = part(info_a, image_a, info_b, image_b)
    couverture, n_b = part(info_b, image_b, info_a, image_a)
    return {"recouvrement": recouvrement, "couverture": couverture, "occupes_scan": n_a, "occupes_reference": n_b}


def comparer_fichiers(yaml_scan, yaml_reference, tolerance_px=1):
    info_a, image_a = charger_carte(yaml_scan)
    info_b, image_b = charger_carte(yaml_reference)
    return comparer(info_a, image_a, info_b, image_b, tolerance_px)


# ---------------------------------------------------------------- dans un lieu

def fabriquer_carte_lieu(lieu, etage, pcd=None, sortie=None, sol=None, afficher=None):
    """Lit cartes/<etage>.pcd (ou pcd) et écrit la carte : cartes/<etage>.yaml (ou sortie).

    Sans « sortie », la carte du lieu est remplacée et lieu.yaml passe à source_carte: scan.
    Renvoie {fichier, sol, occupes, largeur, hauteur}.
    """
    from atelier.scan.carte3d import ErreurCarte3d, lire_pcd
    dire = afficher or (lambda *_: None)
    fiche = charger_fiche(lieu)
    if fiche.etage(etage) is None:
        raise ErreurCarte2d(f"le lieu {fiche.dossier} n'a pas d'étage « {etage} » "
                            f"(étages : {', '.join(e.id for e in fiche.etages)})")
    pcd = Path(pcd) if pcd else chemin_pcd(lieu, etage)
    try:
        points = lire_pcd(pcd)
    except ErreurCarte3d as e:
        raise ErreurCarte2d(f"{e} ; fabriquez-le avec : g1-carte-3d --lieu L --etage {etage} "
                            "--enregistrement DOSSIER") from None
    emprise = None
    try:
        monde = charger_monde(lieu, etage)
        emprise = (monde.emprise.xmin, monde.emprise.ymin, monde.emprise.xmax, monde.emprise.ymax)
        dire(f"Emprise : celle du monde de l'étage ({monde.emprise.taille_x:g} × {monde.emprise.taille_y:g} m)")
    except ErreurLieu:
        dire("Emprise : celle du nuage (l'étage n'a pas de monde inventé)")
    sortie = Path(sortie) if sortie else chemin_carte(lieu, etage)
    info, carte, sol = fabriquer_carte(points, emprise, sol, image=sortie.stem + ".pgm")
    occupes = int((carte == OCCUPE).sum())
    if occupes == 0:
        raise ErreurCarte2d(f"aucun obstacle entre {TRANCHE[0]:g} et {TRANCHE[1]:g} m au-dessus du sol "
                            f"(sol à {sol:.2f} m) : vérifiez le nuage, ou donnez --sol")
    sortie.parent.mkdir(parents=True, exist_ok=True)
    enregistrer_carte(sortie, info, carte)
    dire(f"Sol à {sol:.2f} m ; tranche de {TRANCHE[0]:g} à {TRANCHE[1]:g} m ; {occupes} pixels occupés")
    dire(f"Carte écrite : {sortie} ({info.largeur} × {info.hauteur} pixels de {RESOLUTION * 100:g} cm)")
    if sortie.resolve() == chemin_carte(lieu, etage).resolve():
        etage_fiche = fiche.etage(etage)
        if etage_fiche.source_carte != "scan":
            etage_fiche.source_carte = "scan"
            enregistrer_fiche(fiche)
            dire(f"lieu.yaml : l'étage {etage} utilise maintenant la carte du scan (source_carte: scan)")
        dire(f"Suite : g1-monde generer --lieu {fiche.dossier} --etage {etage} (masque des zones interdites "
             "à la taille de cette carte)")
    return {"fichier": str(sortie), "sol": sol, "occupes": occupes, "largeur": info.largeur, "hauteur": info.hauteur}
