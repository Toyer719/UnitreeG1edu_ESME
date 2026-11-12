"""Nuage 3D du scan (.pcd) → carte 2D de navigation (.pgm + .yaml, format Nav2 de la section 4.1).

Étapes :
  1. trouver le plan du sol (atelier.scan.sol : RANSAC à graine fixe ; ou --sol, un niveau imposé).
     Le sol du vrai G1 est un plan incliné dans le repère map (0,58° le 27/10) : on travaille en
     hauteur au-dessus de ce plan (section 12.5 du plan), sans tourner le nuage ;
  2. garder la tranche de 0,1 à 1,5 m au-dessus du sol, et la projeter sur une grille de 5 cm ;
  3. une case est occupée si au moins POINTS_MIN points y tombent ;
  4. nettoyer par une ouverture morphologique par aire : on retire les taches isolées de moins
     de AIRE_MIN cases. (Une ouverture classique, érosion puis dilatation, effacerait aussi les
     murs vus d'un seul côté, qui ne font qu'une case d'épaisseur dans un scan.)
  5. l'intérieur de l'emprise est libre (254), les cases occupées à 0, le reste inconnu (205).

L'emprise est celle du monde de l'étage s'il existe (la carte du scan a alors la même taille
et la même origine que celle du monde, et que le masque des zones), sinon celle des obstacles
du nuage, sans les points isolés (taches de moins de AIRE_MIN cases).
Toutes les conversions mètres ↔ pixels passent par atelier.lieu.conversions.
"""
import math
from collections import deque
from pathlib import Path

import numpy as np

from atelier.lieu import (ErreurLieu, charger_carte, charger_fiche, charger_monde, chemin_carte, chemin_pcd,
                          dans_image, enregistrer_carte, enregistrer_fiche, info_carte_pour_emprise,
                          monde_vers_pixel, pixel_vers_monde)
from atelier.scan import sol as S

TRANCHE = (0.1, 1.5)       # m au-dessus du sol
RESOLUTION = 0.05          # m par pixel
POINTS_MIN = 2             # points pour qu'une case soit occupée
AIRE_MIN = 4               # cases : une tache occupée plus petite est du bruit
LIBRE, INCONNU, OCCUPE = 254, 205, 0


class ErreurCarte2d(Exception):
    """Nuage vide, illisible ou sans rien dans la tranche ; le message dit quoi corriger."""


def estimer_sol(points):
    """Ancienne estimation, gardée pour comparer : un seul niveau, le 1er centile des z (le sol, ou le
    pied des murs s'il n'a pas été vu). Fausse sur un sol penché : voyez trouver_sol."""
    if len(points) == 0:
        raise ErreurCarte2d("nuage vide")
    return float(np.percentile(points[:, 2], 1.0))


def trouver_sol(points, sol=None):
    """Plan du sol du nuage (atelier.scan.sol.trouver_sol) ; sol : niveau imposé. ErreurCarte2d si vide."""
    try:
        return S.trouver_sol(points, sol=sol)
    except S.ErreurSol as e:
        raise ErreurCarte2d(str(e)) from None


def _plan(sol):
    """Plan [a, b, c] depuis un niveau (nombre), un plan, ou le dict de trouver_sol."""
    if isinstance(sol, dict):
        return [float(v) for v in sol["plan"]]
    if np.ndim(sol) == 0:
        return S.plan_plat(sol)
    return [float(v) for v in sol]


def dans_la_tranche(points, plan, tranche=TRANCHE):
    """Points (N, 3) dont la hauteur au-dessus du plan du sol est dans la tranche."""
    points = np.asarray(points, dtype=float).reshape(-1, 3)
    h = S.hauteurs(points, _plan(plan))
    return points[(h >= tranche[0]) & (h <= tranche[1])]


def compter_par_pixel(points, info):
    """Nombre de points (N, 2 ou 3) qui tombent dans chaque pixel : tableau (hauteur, largeur) d'entiers."""
    compte = np.zeros((info.hauteur, info.largeur), dtype=np.int32)
    points = np.asarray(points, dtype=float)
    if len(points) == 0:
        return compte
    colonnes, lignes = monde_vers_pixel(points[:, 0], points[:, 1], info)
    ok = dans_image(colonnes, lignes, info)
    np.add.at(compte, (np.asarray(lignes)[ok], np.asarray(colonnes)[ok]), 1)
    return compte


def projeter(points, info, plan, tranche=TRANCHE):
    """Nombre de points de la tranche par pixel : tableau (hauteur, largeur) d'entiers. plan : le plan du
    sol [a, b, c] (ou un niveau, ou le dict de trouver_sol)."""
    return compter_par_pixel(dans_la_tranche(points, plan, tranche), info)


def ouverture_par_aire(occupe, aire_min=AIRE_MIN):
    """Retire les composantes connexes (8 voisins) de moins de aire_min pixels."""
    occupe = np.asarray(occupe, dtype=bool)
    if aire_min <= 1 or not occupe.any():
        return occupe.copy()
    try:
        import cv2
    except ImportError:
        return _ouverture_par_aire_lente(occupe, aire_min)
    _, etiquettes, stats, _ = cv2.connectedComponentsWithStats(occupe.astype(np.uint8), connectivity=8)
    grandes = stats[:, cv2.CC_STAT_AREA] >= aire_min
    grandes[0] = False                       # le fond
    return grandes[etiquettes] & occupe


def _ouverture_par_aire_lente(occupe, aire_min):
    """Même calcul sans OpenCV (Python du système) : parcours en largeur de chaque tache."""
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


def _arrondir_emprise(xmin, ymin, xmax, ymax):
    xmin, ymin = (math.floor(v / RESOLUTION) * RESOLUTION for v in (xmin, ymin))
    xmax, ymax = (math.ceil(v / RESOLUTION) * RESOLUTION for v in (xmax, ymax))
    return float(xmin), float(ymin), float(xmax), float(ymax)


def emprise_du_nuage(points, plan, tranche=TRANCHE, points_min=POINTS_MIN, aire_min=AIRE_MIN):
    """(xmin, ymin, xmax, ymax) des obstacles du nuage, arrondi à la résolution : les points de la tranche,
    sans les points isolés (pixels qui ne font pas une tache d'au moins aire_min cases, comme sur la carte)."""
    dans = dans_la_tranche(points, plan, tranche)
    if len(dans) == 0:
        p = _plan(plan)
        raise ErreurCarte2d(f"aucun point entre {tranche[0]:g} et {tranche[1]:g} m au-dessus du sol "
                            f"(sol vers {p[2]:.2f} m) : vérifiez le nuage, ou donnez --sol")
    brute = _arrondir_emprise(*dans[:, :2].min(axis=0), *dans[:, :2].max(axis=0))
    info = info_carte_pour_emprise(*brute, resolution=RESOLUTION, marge=1)
    occupe = ouverture_par_aire(compter_par_pixel(dans, info) >= points_min, aire_min)
    if not occupe.any():
        return brute
    lignes, colonnes = np.nonzero(occupe)
    x, y = pixel_vers_monde(colonnes, lignes, info)
    demi = RESOLUTION / 2
    return _arrondir_emprise(float(np.min(x)) - demi, float(np.min(y)) - demi, float(np.max(x)) + demi,
                             float(np.max(y)) + demi)


def fabriquer_carte(points, emprise=None, sol=None, tranche=TRANCHE, points_min=POINTS_MIN,
                    aire_min=AIRE_MIN, image="carte.pgm", plan=None):
    """Nuage (N, 3) → (InfoCarte, image uint8, sol). emprise : (xmin, ymin, xmax, ymax), défaut : celle des
    obstacles du nuage. sol : niveau imposé (plan horizontal) ; plan : plan du sol déjà trouvé ([a, b, c]
    ou le dict de trouver_sol) ; sinon trouvé ici. Le sol rendu est le dict de atelier.scan.sol.trouver_sol."""
    points = np.asarray(points, dtype=float).reshape(-1, 3)
    if len(points) == 0:
        raise ErreurCarte2d("nuage vide")
    if plan is not None and sol is None:
        p = _plan(plan)
        sol_trouve = dict(plan) if isinstance(plan, dict) else {
            "plan": p, "inclinaison_deg": round(S.inclinaison_deg(p), 3), "methode": "donne", "points": 0,
            "niveau": round(float(S.niveau(p, *np.median(points[:, :2], axis=0))), 3)}
    else:
        sol_trouve = trouver_sol(points, sol)
    p = _plan(sol_trouve)
    if emprise is None:
        emprise = emprise_du_nuage(points, p, tranche, points_min, aire_min)
    info = info_carte_pour_emprise(*emprise, resolution=RESOLUTION, marge=1, image=image)
    occupe = ouverture_par_aire(projeter(points, info, p, tranche) >= points_min, aire_min)
    # Intérieur de l'emprise libre, marge inconnue, puis les obstacles
    x, y = pixel_vers_monde(*np.meshgrid(np.arange(info.largeur), np.arange(info.hauteur)), info)
    dedans = (x >= emprise[0]) & (x <= emprise[2]) & (y >= emprise[1]) & (y <= emprise[3])
    carte = np.full((info.hauteur, info.largeur), INCONNU, dtype=np.uint8)
    carte[dedans] = LIBRE
    carte[occupe] = OCCUPE
    return info, carte, sol_trouve


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

def texte_sol(sol):
    """Phrase courte sur le sol trouvé : « plan incliné de 0,58° (vers −1,27 m), trouvé par RANSAC »."""
    methode = {"ransac": "trouvé par RANSAC", "centile": "pas de plan trouvé : 1er centile des hauteurs",
               "impose": "niveau imposé", "donne": "plan déjà trouvé"}.get(sol.get("methode"), sol.get("methode"))
    pente = f"plan incliné de {sol['inclinaison_deg']:.2f}°" if sol["inclinaison_deg"] >= 0.005 else "plan horizontal"
    return f"{pente} (vers {sol['niveau']:.2f} m), {methode}"


def fabriquer_carte_lieu(lieu, etage, pcd=None, sortie=None, sol=None, afficher=None, plan=None):
    """Lit cartes/<etage>.pcd (ou pcd) et écrit la carte : cartes/<etage>.yaml (ou sortie).

    Sans « sortie », la carte du lieu est remplacée et lieu.yaml passe à source_carte: scan.
    sol : niveau imposé ; plan : plan du sol déjà trouvé (carte 3D), sinon trouvé ici.
    Renvoie {fichier, sol (dict de atelier.scan.sol.trouver_sol), occupes, largeur, hauteur}.
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
    info, carte, sol = fabriquer_carte(points, emprise, sol, image=sortie.stem + ".pgm", plan=plan)
    occupes = int((carte == OCCUPE).sum())
    if occupes == 0:
        raise ErreurCarte2d(f"aucun obstacle entre {TRANCHE[0]:g} et {TRANCHE[1]:g} m au-dessus du sol "
                            f"(sol : {texte_sol(sol)}) : vérifiez le nuage, ou donnez --sol")
    sortie.parent.mkdir(parents=True, exist_ok=True)
    enregistrer_carte(sortie, info, carte)
    dire(f"Sol : {texte_sol(sol)} ; tranche de {TRANCHE[0]:g} à {TRANCHE[1]:g} m au-dessus ; {occupes} pixels occupés")
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
