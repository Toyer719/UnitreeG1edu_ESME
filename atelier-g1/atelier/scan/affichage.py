"""Nuage d'affichage de la carte 3D (vague 5, section 12.5 du plan) : du nuage traité au fichier .bin + .json.

Le format (Float32 x y z, en-tête JSON, emplacements) est celui de atelier.lieu.nuage. Ici, on fabrique
les points : x et y du repère map, tels quels ; z = hauteur au-dessus du plan du sol (soustrait, pas
tourné), sol et plafond compris (la page coupe le plafond), mobiles déjà retirés par la carte 3D.

    points = points_affichage(nuage, plan, grille=0.05)
    ecrire_nuage_affichage(base, nuage, sol, source="scan", session=..., etage=...)
    nuage_du_monde(monde, pas=0.05)       # points sur les murs et objets d'un monde (essais, faux service)

Seulement numpy (et atelier.lieu) : pas d'Open3D, pour tourner aussi dans l'aperçu en direct.
"""
import math

import numpy as np

from atelier.lieu import ecrire_nuage, entete_nuage
from atelier.lieu.nuage import GRILLE_NUAGE, NUAGE_POINTS_MAX
from atelier.scan import sol as S


def reduire_grille(points, grille):
    """Un point par voxel de « grille » mètres : la moyenne des points du voxel (numpy seul)."""
    points = np.asarray(points, dtype=float).reshape(-1, 3)
    if len(points) == 0 or grille <= 0:
        return points.copy()
    cles = np.floor(points / grille).astype(np.int64)
    _, inverse, compte = np.unique(cles, axis=0, return_inverse=True, return_counts=True)
    inverse = inverse.reshape(-1)
    somme = np.zeros((len(compte), 3))
    for k in range(3):
        somme[:, k] = np.bincount(inverse, weights=points[:, k], minlength=len(compte))
    return somme / compte[:, None]


def points_affichage(points, plan, grille=None):
    """Points (N, 3) du repère map → points d'affichage float32 : x, y inchangés, z = hauteur au-dessus du
    plan du sol [a, b, c]. grille : réduire encore à cette grille (None : telle quelle)."""
    points = np.asarray(points, dtype=float).reshape(-1, 3)
    if grille:
        points = reduire_grille(points, grille)
    resultat = np.column_stack([points[:, 0], points[:, 1], S.hauteurs(points, plan)])
    return resultat[np.isfinite(resultat).all(axis=1)].astype(np.float32)


def ecrire_nuage_affichage(base, points, sol, source="scan", session=None, etage=None, grille=GRILLE_NUAGE,
                           reduire=False, **autres):
    """Écrit <base>.bin et <base>.json (atelier.lieu.ecrire_nuage) depuis le nuage traité (repère map) et
    son sol (dict de atelier.scan.sol.trouver_sol). reduire : réduire d'abord à la grille (le nuage
    d'une session l'est déjà). Au-delà de NUAGE_POINTS_MAX, la grille grandit. Renvoie l'en-tête."""
    p = points_affichage(points, sol["plan"], grille if reduire else None)
    while len(p) > NUAGE_POINTS_MAX:
        grille = round(grille * 1.5, 3)
        p = points_affichage(p, [0.0, 0.0, 0.0], grille)       # z est déjà la hauteur au-dessus du sol
    entete = entete_nuage(p, grille, S.resume_sol(sol), source, session=session, etage=etage, **autres)
    return ecrire_nuage(base, p, entete)


def _face(a, b, z0, z1, pas):
    """Points d'un rectangle vertical de a à b (2D), de z0 à z1, tous les « pas » mètres."""
    n = max(2, int(math.ceil(math.dist(a, b) / pas)) + 1)
    m = max(2, int(math.ceil((z1 - z0) / pas)) + 1)
    t, z = np.meshgrid(np.linspace(0, 1, n), np.linspace(z0, z1, m))
    return np.column_stack([(a[0] + t * (b[0] - a[0])).ravel(), (a[1] + t * (b[1] - a[1])).ravel(), z.ravel()])


def _dessus(coins, z, pas):
    a, b, _, d = [np.asarray(c, dtype=float) for c in coins]
    n = max(2, int(math.ceil(np.linalg.norm(b - a) / pas)) + 1)
    m = max(2, int(math.ceil(np.linalg.norm(d - a) / pas)) + 1)
    u, v = np.meshgrid(np.linspace(0, 1, n), np.linspace(0, 1, m))
    q = a + u.ravel()[:, None] * (b - a) + v.ravel()[:, None] * (d - a)
    return np.column_stack([q, np.full(len(q), z)])


def _cylindre(centre, rayon, hauteur, pas):
    n = max(8, int(2 * math.pi * rayon / pas))
    angles, z = np.meshgrid(np.linspace(0, 2 * math.pi, n, endpoint=False), np.arange(0.0, hauteur + 1e-9, pas))
    return np.column_stack([centre[0] + rayon * np.cos(angles.ravel()), centre[1] + rayon * np.sin(angles.ravel()),
                            z.ravel()])


def nuage_du_monde(monde, pas=0.05, sol_pas=0.25):
    """Points (N, 3), repère map, sur les faces des murs et des objets d'un monde (atelier.lieu.Monde),
    plus le sol tous les sol_pas mètres dans l'emprise (0 : sans sol). Sans masquage : un nuage « tout
    vu », pour les essais (carte d'Unitree du faux service, nuage d'étage de test)."""
    morceaux = []
    for m in monde.murs:
        coins = m.coins()
        morceaux += [_face(coins[k], coins[(k + 1) % 4], 0.0, m.hauteur, pas) for k in range(4)]
        morceaux.append(_dessus(coins, m.hauteur, pas))
    for o in monde.objets:
        empreinte, hauteur = o.empreinte(), o.hauteur_totale()
        if empreinte[0] == "cercle":
            morceaux.append(_cylindre(empreinte[1], empreinte[2], hauteur, pas))
        else:
            coins = empreinte[1]
            morceaux += [_face(coins[k], coins[(k + 1) % 4], 0.0, hauteur, pas) for k in range(4)]
            morceaux.append(_dessus(coins, hauteur, pas))
    if sol_pas:
        e = monde.emprise
        x, y = np.meshgrid(np.arange(e.xmin, e.xmax, sol_pas), np.arange(e.ymin, e.ymax, sol_pas))
        morceaux.append(np.column_stack([x.ravel(), y.ravel(), np.zeros(x.size)]))
    return np.vstack(morceaux) if morceaux else np.zeros((0, 3))
