"""Reconnaissance des murs, des passages et des objets dans le scan d'un étage (section 9.6 du plan).

    from atelier.scan.reconnaissance import reconnaitre
    resultat = reconnaitre(chemin_pcd, chemin_carte_yaml, dossier_sortie, parametres=None)

Entrées : le nuage .pcd de la session (repère de l'odométrie, obstacles mobiles déjà retirés par
atelier.scan.carte3d) et sa carte 2D (.yaml Nav2, avec son .pgm à côté). Sorties, dans
dossier_sortie et nulle part ailleurs : reconnaissance.yaml (atelier.lieu.ecrire_reconnaissance)
et monde_scan.monde.yaml (atelier.lieu.ecrire_monde_scan). Les deux sont validés avant d'être
écrits : en cas d'erreur, aucun fichier n'est écrit à moitié.

Étapes :
  1. Sol : plan presque horizontal trouvé par RANSAC parmi les points bas, puis affiné par moindres
     carrés. Les hauteurs sont mesurées depuis ce plan, et ses points sont retirés. Un plafond (plan
     horizontal haut et étendu) est retiré de la même façon s'il existe. (Le RANSAC est écrit avec
     numpy et une graine fixe : celui d'Open3D, parallèle, ne rend pas toujours le même plan.)
  2. Murs : les points de la tranche des murs (1,3 à 1,9 m : au-dessus des meubles bas, sous les
     linteaux des portes) sont posés sur la grille de la carte. OpenCV (HoughLinesP) y propose des
     segments ; chacun est réajusté sur les points (moindres carrés), puis coupé là où les points
     manquent. Les morceaux alignés (5°, 0,10 m), et les deux faces d'un même mur, sont fusionnés.
     Épaisseur et hauteur sont mesurées sur les points.
  3. Passages (règle 9.4) : un trou de 0,7 à 1,6 m entre deux murs alignés. Un trou plus petit est
     bouché (les deux murs n'en font qu'un) ; un trou plus grand est une ouverture, sans passage.
  4. Objets : les points restants (ni sol, ni plafond, ni murs) sont regroupés vus de dessus par
     DBSCAN (Open3D). Seuls les points à plus de 0,35 m relient deux objets (les pieds et les traces
     au sol ne collent pas une chaise à sa table) ; les petits morceaux d'un objet clairsemé sont
     rattachés au groupe voisin ; les traces (groupes trop clairsemés, colonnes sans volume, groupes
     qui flottent) et les restes de murs (tranche d'un mur à une porte) sont écartés. Chaque groupe
     reçoit une boîte orientée ou un cylindre, et une catégorie par des règles simples : hauteur,
     emprise, hauteur du plateau, remplissage sous le plateau, rondeur, finesse (scores_categories).
     Une personne est reconnue, mais jamais gardée d'office (a_garder faux).

Tous les réglages sont dans PARAMETRES, chacun avec son rôle ; « parametres » en remplace.
Même résultat à chaque appel avec les mêmes entrées (graine fixe du RANSAC).

Mise au point :
    python -m atelier.scan.reconnaissance NUAGE.pcd CARTE.yaml DOSSIER [--parametre cle=valeur ...]
"""
import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

from atelier import MOTIF_ID
from atelier import lieu as L
from atelier.lieu.geometrie import PASSAGE_MAX, PASSAGE_MIN

# ---------------------------------------------------------------- réglages

PARAMETRES = {
    "graine": 0,                       # graine du hasard (RANSAC du sol et du plafond) : résultat reproductible
    "grille": 0.05,                    # m : pas du nuage (carte3d le réduit à 5 cm)
    # Sol et plafond
    "sol_bande": 0.4,                  # m : sol cherché parmi les points à moins de 0,4 m au-dessus du 1er centile
    "sol_distance": 0.03,              # m : écart maximal d'un point au plan (RANSAC)
    "sol_iterations": 1000,            # tirages du RANSAC
    "sol_echantillon": 20000,          # points au plus pour compter les points d'un plan (tirés à graine fixe)
    "sol_inclinaison_max": 10.0,       # degrés : un plan plus incliné n'est pas le sol
    "sol_points_min": 100,             # points du plan au moins ; sinon le sol est le 1er centile des z
    "sol_retrait": 0.06,               # m : un point à moins de 6 cm au-dessus du sol est du sol
    "plafond_hauteur_min": 2.0,        # m au-dessus du sol : un plafond est plus haut
    "plafond_aire_min": 4.0,           # m² couverts d'un seul tenant (le haut des murs n'est qu'une bande)
    # Murs
    "mur_tranche": [1.3, 1.9],         # m au-dessus du sol : points des murs (meubles bas dessous, linteaux dessus)
    "mur_tolerance": 0.06,             # m : écart maximal d'un point à la droite de son mur
    "mur_longueur_min": 0.5,           # m : mur le plus court
    "mur_points_par_m": 8.0,           # points de la tranche par mètre de mur, au moins
    "mur_points_min": 20,              # points de la tranche d'un mur, au moins
    "mur_trou_continuite": 0.3,        # m : un trou plus long coupe un morceau (avant la fusion)
    "mur_angle_fusion": 5.0,           # degrés : deux morceaux alignés (règle 9.4)
    "mur_ecart_fusion": 0.10,          # m : écart maximal entre deux morceaux alignés (règle 9.4)
    "mur_epaisseur_max": 0.35,         # m : deux faces parallèles plus proches sont un même mur
    "mur_epaisseur_vue_min": 0.10,     # m : en dessous, une seule face a été vue
    "mur_epaisseur_defaut": 0.15,      # m : épaisseur donnée à un mur vu d'un seul côté
    "mur_hauteur_defaut": 2.5,         # m : hauteur d'un mur dont on n'a vu aucun point au-dessus de la tranche
    "mur_hauteur_min": 1.8,            # m : un mur court plus bas est un objet (ex. une personne vue de face)...
    "mur_longueur_basse": 2.0,         # m : ... sauf s'il est au moins aussi long (cloison basse)
    "mur_extension_bouts": 0.02,       # m : les points sont des centres de cases ; le bout est un peu plus loin
    "hough_pas_angle": 1.0,            # degrés : pas des directions essayées par HoughLinesP
    "hough_seuil": 10,                 # votes minimaux d'un segment de Hough
    "hough_trou_px": 3,                # pixels : trou franchi par un segment de Hough
    # Passages
    "passage_vue_profondeur": 3.0,     # m : on cherche des points vus à travers le trou, jusqu'à 3 m derrière
    "passage_marge_mur": 0.2,          # m : un autre mur aussi près du trou (coin mal vu) : pas de passage
    # Objets
    "objet_hauteur_max": 3.0,          # m : plus haut (sans plafond), ce n'est plus un objet posé
    "objet_marge_mur": 0.06,           # m : un point plus près d'un mur appartient au mur
    "objet_voisins_rayon": 0.1,        # m : pour relier deux objets ou mesurer une hauteur, un point doit avoir
    "objet_voisins_min": 2,            # des voisins aussi près, au moins 2 (sinon : point isolé, ex. fantôme)
    "dbscan_eps": 0.12,                # m : voisinage du regroupement
    "dbscan_echelle_z": 0.0,           # poids des hauteurs (0 : regroupement vu de dessus, un objet par emprise)
    "dbscan_points_min": 4,            # voisins pour un cœur de groupe
    "fragment_points_max": 40,         # un groupe plus petit...
    "fragment_distance": 0.25,         # ... aussi près d'un autre groupe en est un morceau (objet vu par bouts)
    "objet_points_min": 15,            # points pour qu'un groupe soit un objet (moins : pas assez sûr)
    "objet_bas": 0.2,                  # m : les points plus bas (sol mal recalé) ne font pas partie des objets
    "objet_bas_liaison": 0.35,         # m : seuls les points plus hauts relient les objets ; les plus bas (pieds,
                                       #     traces au sol) sont ensuite rattachés au groupe le plus proche
    "objet_saut_vertical": 0.45,       # m : un vide plus haut sépare deux choses empilées (on garde la principale)
    "objet_densite_min": 0.2,          # points par case de 5 cm de sa plus grande face ; en dessous : une trace
    "objet_bas_max": 1.2,              # m : un groupe qui ne descend pas plus bas flotte (trace), il n'est pas posé
    "colonne_largeur_max": 0.2,        # m : une colonne de points plus fine...
    "colonne_points_max": 50,          # ... et avec moins de points n'a pas de volume : une trace
    "objet_hauteur_min": 0.2,          # m : un groupe plus bas est un reste du sol
    "objet_reste_mur": 0.25,           # m : un groupe mince et parallèle à un mur, plus près, en est un reste
    "objet_bout_mur": 0.3,             # m : un petit groupe presque aussi haut qu'un mur, aussi près, en fait partie
    # Catégories : intervalles [bas, haut] en mètres (règles de classer)
    "table_plateau": [0.65, 0.85],     # hauteur du plateau d'une table
    "table_profondeur_min": 0.35,      # m : le LiDAR, plus haut, voit le plateau en profondeur
    "chaise_hauteur": [0.75, 1.05],    # haut du dossier d'une chaise
    "chaise_emprise_max": 0.75,        # m : plus grand côté d'une chaise
    "chaise_assise": [0.4, 0.7],       # assise vue sans son dossier (caché, ou trop haut pour le LiDAR)
    "banc_hauteur": [0.35, 0.6],       # assise longue et basse
    "banc_longueur_min": 0.9,
    "banc_profondeur_min": 0.2,        # m : profondeur de l'assise vue (une face mince n'est pas un banc)
    "poubelle_hauteur": [0.45, 0.95],  # petit cylindre bas et plein
    "poubelle_emprise_max": 0.65,
    "poteau_hauteur_min": 1.95,        # colonne mince et haute
    "poteau_emprise_max": 0.6,
    "poteau_finesse_min": 3.0,         # hauteur / plus grand côté
    "personne_hauteur": [1.5, 1.95],   # personne debout
    "personne_emprise": [0.25, 0.75],  # plus grand côté vu de dessus
    "meuble_emprise_min": 0.8,         # bloc plein : armoire, bureau plein, banque d'accueil
    "meuble_hauteur_haut": 1.0,        # au-dessus : un bloc large est un meuble, plein ou non
    "meuble_hauteur_min": 0.5,         # bloc bas : seulement s'il est plein
    "remplissage_plein": 0.5,          # part des cases occupées sous le plateau au-delà de laquelle c'est plein
    "categorie_score_min": 0.35,       # score sous lequel l'objet reste « inconnu »
}

# Clés reconnues en plus des réglages (section 9.6)
CLES_GENERALES = ("depart_robot", "session", "etage", "sol")

LIBRE, INCONNU, OCCUPE = 254, 205, 0


class ErreurReconnaissance(Exception):
    """La reconnaissance n'a pas pu se faire ; le message (en français) dit quoi faire."""


# ---------------------------------------------------------------- petits outils

def _o3d():
    import open3d as o3d
    o3d.utility.set_verbosity_level(o3d.utility.VerbosityLevel.Error)
    return o3d


def _r(v, decimales=3):
    return round(float(v), decimales)


def appartenance(x, bas, haut, souplesse):
    """1 si bas <= x <= haut ; décroît linéairement jusqu'à 0 à « souplesse » des bornes."""
    if x < bas:
        return max(0.0, 1.0 - (bas - x) / souplesse) if souplesse > 0 else 0.0
    if x > haut:
        return max(0.0, 1.0 - (x - haut) / souplesse) if souplesse > 0 else 0.0
    return 1.0


def _reglages(parametres):
    """PARAMETRES complétés par ceux de l'appel ; ErreurReconnaissance pour une clé inconnue."""
    p = {cle: (list(v) if isinstance(v, (list, tuple)) else v) for cle, v in PARAMETRES.items()}
    generaux = {}
    for cle, valeur in (parametres or {}).items():
        if cle in CLES_GENERALES:
            generaux[cle] = valeur
        elif cle in PARAMETRES:
            defaut = PARAMETRES[cle]
            if isinstance(defaut, list):
                if not (isinstance(valeur, (list, tuple)) and len(valeur) == len(defaut)):
                    raise ErreurReconnaissance(f"paramètre {cle} : attendu une liste de {len(defaut)} nombres, "
                                               f"reçu {valeur!r}")
                valeur = [float(v) for v in valeur]
            elif isinstance(defaut, int) and not isinstance(defaut, bool):
                valeur = int(valeur)
            else:
                valeur = float(valeur)
            p[cle] = valeur
        else:
            raise ErreurReconnaissance(f"paramètre inconnu : {cle} (réglages possibles : voir PARAMETRES dans "
                                       "atelier/scan/reconnaissance.py ; clés générales : "
                                       f"{', '.join(CLES_GENERALES)})")
    return p, generaux


# ---------------------------------------------------------------- 1. sol et plafond

def _plan_horizontal(points, distance, iterations, inclinaison_max, graine, echantillon_max=20000):
    """RANSAC d'un plan presque horizontal (normale à moins de inclinaison_max degrés de z) : tirages
    de 3 points à graine fixe, le plan qui a le plus de points à moins de « distance » gagne, puis
    deux ajustements par moindres carrés sur ses points. Renvoie ((a, b, c, d), indices des points du
    plan) avec c > 0 et une normale unitaire ; ou None."""
    n = len(points)
    if n < 3:
        return None
    rng = np.random.default_rng(int(graine))
    echantillon = points if n <= echantillon_max else points[np.sort(rng.choice(n, echantillon_max, replace=False))]
    triplets = rng.integers(0, len(echantillon), size=(int(iterations), 3))
    p0, p1, p2 = (echantillon[triplets[:, k]] for k in range(3))
    normales = np.cross(p1 - p0, p2 - p0)
    normes = np.linalg.norm(normales, axis=1)
    ok = normes > 1e-9
    normales[ok] /= normes[ok, None]
    ok &= np.abs(normales[:, 2]) >= math.cos(math.radians(inclinaison_max))
    if not ok.any():
        return None
    normales, d = normales[ok], -(normales[ok] * p0[ok]).sum(axis=1)
    meilleur, compte_max = None, -1
    for debut in range(0, len(normales), 100):
        comptes = (np.abs(echantillon @ normales[debut:debut + 100].T + d[debut:debut + 100]) <= distance).sum(axis=0)
        k = int(np.argmax(comptes))
        if comptes[k] > compte_max:
            meilleur, compte_max = debut + k, int(comptes[k])
    normale, decalage = normales[meilleur], d[meilleur]
    for _ in range(2):                                    # moindres carrés sur les points du plan
        dedans = np.nonzero(np.abs(points @ normale + decalage) <= distance)[0]
        if len(dedans) < 3:
            return None
        centre = points[dedans].mean(axis=0)
        _, _, vt = np.linalg.svd(points[dedans] - centre, full_matrices=False)
        normale = vt[-1] / np.linalg.norm(vt[-1])
        if normale[2] < 0:
            normale = -normale
        decalage = -float(normale @ centre)
    if math.degrees(math.acos(min(1.0, float(normale[2])))) > inclinaison_max:
        return None
    dedans = np.nonzero(np.abs(points @ normale + decalage) <= distance)[0]
    a, b, c = (float(v) for v in normale)
    return (a, b, c, float(decalage)), dedans


def trouver_sol(points, p, sol_impose=None):
    """Plan du sol. Renvoie {plan: (a, b, c, d), sol: hauteur au centre du nuage, methode, points}.

    Avec sol_impose : plan z = sol_impose. Sinon RANSAC parmi les points bas ; s'il ne trouve pas de
    plan horizontal assez grand, le sol est le 1er centile des z (comme atelier.scan.carte2d).
    """
    if sol_impose is not None:
        return {"plan": (0.0, 0.0, 1.0, -float(sol_impose)), "sol": float(sol_impose), "methode": "impose",
                "points": 0}
    z = points[:, 2]
    bas = float(np.percentile(z, 1.0))
    candidats = np.nonzero(z <= bas + p["sol_bande"])[0]
    trouve = _plan_horizontal(points[candidats], p["sol_distance"], p["sol_iterations"],
                              p["sol_inclinaison_max"], p["graine"], p["sol_echantillon"])
    if trouve is not None and len(trouve[1]) >= p["sol_points_min"]:
        (a, b, c, d), dedans = trouve
        cx, cy = (float(v) for v in np.median(points[:, :2], axis=0))
        sol = -(a * cx + b * cy + d) / c
        return {"plan": (a, b, c, d), "sol": sol, "methode": "ransac", "points": int(len(dedans))}
    return {"plan": (0.0, 0.0, 1.0, -bas), "sol": bas, "methode": "centile", "points": 0}


def hauteurs(points, plan):
    """Hauteur de chaque point au-dessus du plan du sol (distance signée)."""
    a, b, c, d = plan
    return points @ np.array([a, b, c]) + d


def trouver_plafond(points, h, p):
    """Hauteur du plafond au-dessus du sol, ou None. Un plafond est un plan horizontal, plus haut que
    plafond_hauteur_min, qui couvre au moins plafond_aire_min m² d'un seul tenant (le haut des murs
    forme aussi un « plan » horizontal, mais seulement en bandes minces)."""
    import cv2
    hauts = np.nonzero(h >= p["plafond_hauteur_min"])[0]
    if len(hauts) < 200:
        return None
    trouve = _plan_horizontal(points[hauts], p["sol_distance"], p["sol_iterations"],
                              p["sol_inclinaison_max"], p["graine"] + 1, p["sol_echantillon"])
    if trouve is None:
        return None
    _, dedans = trouve
    dedans = hauts[dedans]                                     # indices dans le nuage entier
    xy = points[dedans, :2]
    pas = 0.2
    i = np.floor((xy - xy.min(axis=0)) / pas).astype(int)
    grille = np.zeros(tuple(i.max(axis=0) + 3), dtype=np.uint8)
    grille[i[:, 0] + 1, i[:, 1] + 1] = 1
    erode = cv2.erode(grille, np.ones((3, 3), np.uint8))
    if erode.sum() * pas * pas < p["plafond_aire_min"]:
        return None
    return float(np.median(h[dedans]))


# ---------------------------------------------------------------- 2. murs

class Mur:
    """Mur reconnu : droite (centre c, direction unitaire u), bouts t0 < t1 le long de u, épaisseur,
    hauteur, nombre de points et confiance. Les bouts « de » et « a » s'en déduisent."""

    def __init__(self, c, u, t0, t1, epaisseur, deux_faces, points):
        self.c, self.u = np.asarray(c, dtype=float), np.asarray(u, dtype=float)
        self.n = np.array([-self.u[1], self.u[0]])
        self.t0, self.t1 = float(t0), float(t1)
        self.epaisseur, self.deux_faces, self.points = float(epaisseur), bool(deux_faces), int(points)
        self.hauteur, self.confiance, self.couverture, self.id = 2.5, 0.5, 1.0, None

    @property
    def de(self):
        return self.c + self.t0 * self.u

    @property
    def a(self):
        return self.c + self.t1 * self.u

    @property
    def longueur(self):
        return self.t1 - self.t0

    def coordonnees(self, xy):
        """(t le long du mur, s de côté) de points (N, 2)."""
        d = xy - self.c
        return d @ self.u, d @ self.n


def _direction(points):
    """Centre et direction principale (moindres carrés totaux) de points (N, 2) ; u tourné vers x > 0."""
    c = points.mean(axis=0)
    if len(points) < 2:
        return c, np.array([1.0, 0.0])
    valeurs, vecteurs = np.linalg.eigh(np.cov((points - c).T))
    u = vecteurs[:, int(np.argmax(valeurs))]
    if u[0] < -1e-9 or (abs(u[0]) <= 1e-9 and u[1] < 0):
        u = -u
    return c, u / np.linalg.norm(u)


def _troncons(t, trou):
    """Coupe des abscisses triées là où l'écart dépasse « trou » : liste de (début, fin) en indices."""
    if len(t) == 0:
        return []
    coupures = np.nonzero(np.diff(t) > trou)[0]
    debuts = np.concatenate([[0], coupures + 1])
    fins = np.concatenate([coupures, [len(t) - 1]])
    return list(zip(debuts, fins))


def _segments_hough(xy, info, p):
    """Segments proposés par cv2.HoughLinesP sur l'image des points de la tranche des murs,
    en mètres, du plus long au plus court."""
    import cv2
    image = np.zeros((info.hauteur, info.largeur), dtype=np.uint8)
    colonnes, lignes = L.monde_vers_pixel(xy[:, 0], xy[:, 1], info)
    image[np.asarray(lignes), np.asarray(colonnes)] = 255
    longueur_px = max(2, int(round(p["mur_longueur_min"] / info.resolution)))
    trouves = cv2.HoughLinesP(image, 1, math.radians(p["hough_pas_angle"]), int(p["hough_seuil"]),
                              minLineLength=longueur_px, maxLineGap=int(p["hough_trou_px"]))
    if trouves is None:
        return []
    segments = []
    for c1, l1, c2, l2 in trouves[:, 0, :]:
        x1, y1 = L.pixel_vers_monde(c1, l1, info)
        x2, y2 = L.pixel_vers_monde(c2, l2, info)
        segments.append((np.array([x1, y1], dtype=float), np.array([x2, y2], dtype=float)))
    segments.sort(key=lambda s: (-np.linalg.norm(s[1] - s[0]), s[0][0], s[0][1], s[1][0], s[1][1]))
    return segments


def _morceaux(xy, info, p):
    """Morceaux de murs : chaque segment de Hough (du plus long au plus court) prend les points libres
    proches de sa droite, la réajuste, et garde les tronçons continus qui le recouvrent.
    Renvoie une liste de (c, u, indices des points)."""
    tolerance = p["mur_tolerance"]
    libres = np.ones(len(xy), dtype=bool)
    morceaux = []
    for a, b in _segments_hough(xy, info, p):
        if libres.sum() < 2:
            break
        u = (b - a) / (np.linalg.norm(b - a) or 1.0)
        c = (a + b) / 2
        demi = np.linalg.norm(b - a) / 2
        for _ in range(2):                                   # ajustement, puis second passage
            idx = np.nonzero(libres)[0]
            d = xy[idx] - c
            s, t = d @ np.array([-u[1], u[0]]), d @ u
            proches = np.abs(s) <= tolerance
            idx, t = idx[proches], t[proches]
            if len(idx) < 2:
                break
            ordre = np.argsort(t)
            idx, t = idx[ordre], t[ordre]
            garde = []
            for i0, i1 in _troncons(t, p["mur_trou_continuite"]):
                if t[i1] >= -demi and t[i0] <= demi:           # recouvre le segment de Hough
                    garde.append(idx[i0:i1 + 1])
            if not garde:
                idx = np.array([], dtype=int)
                break
            idx = np.concatenate(garde)
            c_nouveau, u_nouveau = _direction(xy[idx])
            # le segment de Hough, ramené sur la nouvelle droite
            ta, tb = (a - c_nouveau) @ u_nouveau, (b - c_nouveau) @ u_nouveau
            c = c_nouveau + (ta + tb) / 2 * u_nouveau
            demi = abs(tb - ta) / 2
            u = u_nouveau
        if len(idx) < max(2, p["mur_points_min"]):
            continue
        t = (xy[idx] - c) @ u
        longueur = t.max() - t.min()
        if longueur < p["mur_longueur_min"] or len(idx) < p["mur_points_par_m"] * longueur:
            continue
        libres[idx] = False
        morceaux.append((c, u, idx))
    return morceaux


def _regrouper(morceaux, xy, p):
    """Groupes de morceaux qui forment un même alignement de murs : alignés (5°, 0,10 m), ou deux
    faces parallèles d'un même mur (moins de mur_epaisseur_max d'écart, et qui se recouvrent)."""
    n = len(morceaux)
    parent = list(range(n))

    def racine(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    bouts = []
    for c, u, idx in morceaux:
        t = (xy[idx] - c) @ u
        bouts.append((c + t.min() * u, c + t.max() * u))
    angle_max = math.radians(p["mur_angle_fusion"])
    for i in range(n):
        ci, ui, _ = morceaux[i]
        ni = np.array([-ui[1], ui[0]])
        for j in range(i + 1, n):
            cj, uj, _ = morceaux[j]
            nj = np.array([-uj[1], uj[0]])
            ecart_angle = math.acos(min(1.0, abs(float(ui @ uj))))
            if ecart_angle > angle_max:
                continue
            ecart = max(max(abs((q - ci) @ ni) for q in bouts[j]), max(abs((q - cj) @ nj) for q in bouts[i]))
            if ecart <= p["mur_ecart_fusion"]:
                parent[racine(i)] = racine(j)
                continue
            if ecart <= p["mur_epaisseur_max"]:
                ti = sorted(float((q - ci) @ ui) for q in bouts[i])
                tj = sorted(float((q - ci) @ ui) for q in bouts[j])
                if min(ti[1], tj[1]) - max(ti[0], tj[0]) >= 0.2:
                    parent[racine(i)] = racine(j)
    groupes = {}
    for i in range(n):
        groupes.setdefault(racine(i), []).append(i)
    return [sorted(g) for _, g in sorted(groupes.items(), key=lambda e: min(e[1]))]


def _murs_d_un_groupe(xy, idx, p):
    """Murs d'un alignement : droite commune, épaisseur, tronçons séparés par des trous d'au moins
    PASSAGE_MIN (un trou plus petit est bouché : règle 9.4). Renvoie la liste des Mur, dans l'ordre."""
    c, u = _direction(xy[idx])
    n = np.array([-u[1], u[0]])
    d = xy[idx] - c
    t, s = d @ u, d @ n
    bas, haut = np.percentile(s, [2, 98])
    if haut - bas >= p["mur_epaisseur_vue_min"]:
        epaisseur, deux_faces, decalage = min(haut - bas, p["mur_epaisseur_max"]), True, (bas + haut) / 2
    else:
        epaisseur, deux_faces, decalage = p["mur_epaisseur_defaut"], False, float(np.median(s))
    c = c + decalage * n
    ordre = np.argsort(t)
    t = t[ordre]
    ext = p["mur_extension_bouts"]
    murs = []
    for i0, i1 in _troncons(t, PASSAGE_MIN - 1e-6 + 2 * ext):
        t0, t1 = t[i0] - ext, t[i1] + ext
        nombre = i1 - i0 + 1
        mur = Mur(c, u, t0, t1, epaisseur, deux_faces, nombre)
        # part des cases de 10 cm le long du mur qui ont des points
        cases = np.unique(np.floor((t[i0:i1 + 1] - t0) / 0.1).astype(int))
        mur.couverture = min(1.0, len(cases) / max(1.0, math.ceil((t1 - t0) / 0.1)))
        mur.garde = (mur.longueur >= p["mur_longueur_min"] and nombre >= p["mur_points_min"]
                     and nombre >= p["mur_points_par_m"] * mur.longueur)
        murs.append(mur)
    return murs


def extraire_murs(xy_tranche, info, p):
    """Murs (liste de Mur) et paires de murs voisins d'un même alignement (pour les passages)."""
    if len(xy_tranche) < 2:
        return [], []
    morceaux = _morceaux(xy_tranche, info, p)
    murs, voisins = [], []
    for groupe in _regrouper(morceaux, xy_tranche, p):
        idx = np.concatenate([morceaux[i][2] for i in groupe])
        alignement = _murs_d_un_groupe(xy_tranche, idx, p)
        # paires de murs gardés consécutifs, sans morceau écarté entre eux
        for m1, m2 in zip(alignement, alignement[1:]):
            if m1.garde and m2.garde:
                voisins.append((m1, m2))
        murs.extend(m for m in alignement if m.garde)
    return murs, voisins


def mesurer_murs(murs, points, h, p, plafond=None):
    """Hauteur et confiance de chaque mur, d'après tous les points proches (toutes hauteurs).
    Renvoie le masque des points qui appartiennent à un mur (pour la suite : les objets)."""
    au_mur = np.zeros(len(points), dtype=bool)
    xy = points[:, :2]
    plus_haut = plafond if plafond is not None else p["objet_hauteur_max"]
    for m in murs:
        t, s = m.coordonnees(xy)
        demi = m.epaisseur / 2 if m.deux_faces else 0.03
        proche = (np.abs(s) <= demi + p["objet_marge_mur"]) & (t >= m.t0 - 0.05) & (t <= m.t1 + 0.05)
        au_mur |= proche
        hauts = h[proche & (h > p["sol_retrait"]) & (h <= plus_haut)]
        if plafond is not None:
            m.hauteur = plafond
        elif len(hauts):
            m.hauteur = float(np.percentile(hauts, 98))
        else:
            m.hauteur = p["mur_hauteur_defaut"]
        m.hauteur = min(10.0, max(0.3, m.hauteur))
        c_long = min(1.0, max(0.0, (m.longueur - p["mur_longueur_min"]) / 1.5))
        c_haut = min(1.0, max(0.0, (m.hauteur - 1.5) / 0.5))
        m.confiance = 0.3 + 0.25 * c_long + 0.25 * m.couverture + 0.2 * c_haut
    return au_mur


# ---------------------------------------------------------------- 3. passages

def trouver_passages(voisins, murs, points, h, p):
    """Passages : trous de PASSAGE_MIN à PASSAGE_MAX entre deux murs voisins d'un même alignement.
    Un trou qu'un autre mur touche n'en est pas un : c'est un coin mal vu (le bout d'un mur de pièce
    caché par la cloison qui le rejoint). Renvoie une liste de (m1, m2, de, a, confiance, infos)."""
    from atelier.lieu.geometrie import dist_segments
    passages = []
    xy = points[:, :2]
    for m1, m2 in voisins:
        largeur = m2.t0 - m1.t1
        if not PASSAGE_MIN - 1e-6 <= largeur <= PASSAGE_MAX + 1e-6:
            continue
        de, a = m1.a, m2.de
        if any(dist_segments(tuple(de), tuple(a), tuple(m.de), tuple(m.a)) <= p["passage_marge_mur"]
               for m in murs if m is not m1 and m is not m2):
            continue
        t, s = m1.coordonnees(xy)
        dans_trou = (t > m1.t1 + 0.05) & (t < m2.t0 - 0.05)
        demi = m1.epaisseur / 2 if m1.deux_faces else 0.03
        sur_la_ligne = dans_trou & (np.abs(s) <= demi + 0.05)
        bas = int((sur_la_ligne & (h > 0.1) & (h < 1.9)).sum())        # quelque chose dans l'embrasure
        linteau = int((sur_la_ligne & (h >= 1.9)).sum())
        loin = p["passage_vue_profondeur"]
        derriere = int((dans_trou & (s > demi + 0.15) & (s < loin) & (h > 0.1)).sum())
        devant = int((dans_trou & (s < -demi - 0.15) & (s > -loin) & (h > 0.1)).sum())
        confiance = 0.6
        if derriere > 0 and devant > 0:
            confiance += 0.25                                  # on a vu à travers, des deux côtés
        elif derriere > 0 or devant > 0:
            confiance += 0.15
        if linteau > 3 and bas <= 3:
            confiance += 0.1                                   # un linteau, rien dessous : une porte
        if bas > 3:
            confiance -= 0.25                                  # quelque chose dans l'embrasure
        confiance = min(0.95, max(0.2, confiance)) * min(m1.confiance, m2.confiance) ** 0.25
        infos = {"largeur": _r(largeur), "points_embrasure": bas, "points_linteau": linteau,
                 "points_vus_a_travers": derriere + devant}
        passages.append((m1, m2, de, a, confiance, infos))
    return passages


# ---------------------------------------------------------------- 4. objets

def points_entoures(points, p):
    """Masque des points qui ont au moins objet_voisins_min voisins à objet_voisins_rayon (3D)."""
    if len(points) == 0:
        return np.zeros(0, dtype=bool)
    o3d = _o3d()
    nuage = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(points))
    _, gardes = nuage.remove_radius_outlier(nb_points=int(p["objet_voisins_min"]) + 1,
                                            radius=p["objet_voisins_rayon"])
    masque = np.zeros(len(points), dtype=bool)
    masque[np.asarray(gardes, dtype=int)] = True
    return masque


def regrouper_objets(points, p, h=None, entoures=None):
    """Groupes de points vus de dessus (DBSCAN d'Open3D ; dbscan_echelle_z : poids des hauteurs).
    Avec h (hauteurs des points), seuls les points au-dessus de objet_bas_liaison sont regroupés, et
    avec entoures (masque de points_entoures), seulement ceux qui ont des voisins. Les autres (pieds,
    traces au sol, points isolés) rejoignent ensuite le groupe le plus proche à moins de dbscan_eps,
    s'il y en a un : ils ne collent plus une chaise à la table voisine.
    Renvoie une liste de tableaux d'indices."""
    if len(points) < p["dbscan_points_min"]:
        return []
    o3d = _o3d()
    liants = np.ones(len(points), dtype=bool)
    if h is not None:
        liants &= h >= p["objet_bas_liaison"]
    if entoures is not None:
        liants &= entoures
    hauts = np.nonzero(liants)[0]
    if len(hauts) < p["dbscan_points_min"]:
        return []
    echelle = np.array([1.0, 1.0, p["dbscan_echelle_z"]])
    nuage = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(points[hauts] * echelle))
    etiquettes = np.full(len(points), -1, dtype=int)
    etiquettes[hauts] = np.asarray(nuage.cluster_dbscan(eps=p["dbscan_eps"], min_points=int(p["dbscan_points_min"]),
                                                        print_progress=False))
    bas = np.setdiff1d(np.arange(len(points)), hauts)
    if len(bas) and (etiquettes >= 0).any():
        avec = np.nonzero(etiquettes >= 0)[0]
        arbre = o3d.geometry.KDTreeFlann(o3d.geometry.PointCloud(
            o3d.utility.Vector3dVector(np.column_stack([points[avec, :2], np.zeros(len(avec))]))))
        for i in bas:
            k, voisins, d2 = arbre.search_knn_vector_3d(np.array([points[i, 0], points[i, 1], 0.0]), 1)
            if k and d2[0] <= p["dbscan_eps"] ** 2:
                etiquettes[i] = etiquettes[avec[voisins[0]]]
    groupes = [np.nonzero(etiquettes == e)[0] for e in range(etiquettes.max() + 1 if len(etiquettes) else 0)]
    groupes = _fusionner_fragments(groupes, points[:, :2], p)
    groupes = [g for g in groupes if len(g) >= p["objet_points_min"]]
    # ordre stable : de bas en haut, puis de gauche à droite (pour des ids reproductibles)
    groupes.sort(key=lambda g: (round(float(points[g, 1].mean()), 3), round(float(points[g, 0].mean()), 3)))
    return groupes


def _fusionner_fragments(groupes, xy, p):
    """Un petit groupe (moins de fragment_points_max points) à moins de fragment_distance d'un autre
    groupe lui est rattaché : un objet clairsemé, vu par bouts, ne fait qu'un objet. Les plus petits
    d'abord, chacun vers le groupe le plus proche."""
    groupes = [np.asarray(g) for g in groupes]
    vivants = list(range(len(groupes)))
    ordre = sorted(vivants, key=lambda i: (len(groupes[i]), round(float(xy[groupes[i], 1].mean()), 3),
                                           round(float(xy[groupes[i], 0].mean()), 3)))
    for i in ordre:
        if len(groupes[i]) == 0 or len(groupes[i]) >= p["fragment_points_max"]:
            continue
        a = xy[groupes[i]]
        bas, haut = a.min(axis=0) - p["fragment_distance"], a.max(axis=0) + p["fragment_distance"]
        meilleur, distance_min = None, p["fragment_distance"]
        for j in vivants:
            if j == i or len(groupes[j]) == 0:
                continue
            b = xy[groupes[j]]
            b = b[((b >= bas) & (b <= haut)).all(axis=1)]
            if len(b) == 0:
                continue
            d = float(np.sqrt(((a[:, None, :] - b[None, :, :]) ** 2).sum(axis=2)).min())
            if d <= distance_min:
                meilleur, distance_min = j, d
        if meilleur is not None:
            groupes[meilleur] = np.concatenate([groupes[meilleur], groupes[i]])
            groupes[i] = groupes[i][:0]
    return [g for g in groupes if len(g)]


def _partie_principale(idx, h, p):
    """Indices de la partie principale d'un groupe en hauteur : les hauteurs triées sont coupées là
    où un vide dépasse objet_saut_vertical ; on garde le morceau qui a le plus de points (ce qui
    flotte au-dessus d'une chaise, par exemple, n'en fait pas partie)."""
    ordre = np.argsort(h[idx], kind="stable")
    hs = h[idx][ordre]
    morceaux = _troncons(hs, p["objet_saut_vertical"])
    if len(morceaux) <= 1:
        return idx
    i0, i1 = max(morceaux, key=lambda m: (m[1] - m[0], -m[0]))
    return np.sort(idx[ordre[i0:i1 + 1]])


def _cercle(xy):
    """Cercle des moindres carrés (méthode de Kåsa) : (centre, rayon, écart quadratique), ou None."""
    if len(xy) < 5:
        return None
    m = xy.mean(axis=0)
    d = xy - m
    A = np.column_stack([d, np.ones(len(d))])
    b = -(d ** 2).sum(axis=1)
    try:
        (ka, kb, kc), *_ = np.linalg.lstsq(A, b, rcond=None)
    except np.linalg.LinAlgError:
        return None
    centre = np.array([-ka / 2, -kb / 2])
    r2 = centre @ centre - kc
    if r2 <= 0:
        return None
    rayon = math.sqrt(r2)
    ecart = float(np.sqrt(np.mean((np.hypot(*(d - centre).T) - rayon) ** 2)))
    return centre + m, rayon, ecart


def decrire_objet(pts, h, grille=0.05, entoure=None):
    """Mesures d'un groupe de points (N, 3) de hauteurs h : hauteur, emprise orientée, plateau,
    remplissage sous le plateau, rondeur, finesse, densité. entoure : masque des points qui ont des
    voisins (points_entoures) ; la hauteur n'est mesurée que sur eux (un point isolé ne compte pas)."""
    import cv2
    xy = pts[:, :2]
    rect = cv2.minAreaRect(xy.astype(np.float32))
    coins = cv2.boxPoints(rect).astype(float)
    cotes = [coins[1] - coins[0], coins[2] - coins[1]]
    longs = [float(np.linalg.norm(v)) for v in cotes]
    k = int(np.argmax(longs))
    u = cotes[k] / (longs[k] or 1.0)
    cap = math.atan2(u[1], u[0])
    if cap > math.pi / 2:
        cap -= math.pi
    elif cap <= -math.pi / 2:
        cap += math.pi
    u = np.array([math.cos(cap), math.sin(cap)])
    v = np.array([-u[1], u[0]])
    centre = coins.mean(axis=0)
    longueur = max(longs) + grille                     # les points sont des centres de cases de « grille »
    largeur = min(longs) + grille
    h_sur = h[entoure] if entoure is not None and np.count_nonzero(entoure) >= 5 else h
    haut = float(np.percentile(h_sur, 99))
    # plateau : la tranche de 5 cm qui a le plus de points, au-dessus de 0,25 m
    plateau, part_plateau = None, 0.0
    bins = np.arange(0.25, max(haut, 0.3) + 0.05, 0.05)
    if len(bins) > 1:
        compte, bords = np.histogram(h, bins=bins)
        if compte.max() > 0:
            i = int(np.argmax(compte[::-1]))
            i = len(compte) - 1 - i                          # le plus haut en cas d'égalité
            plateau = float((bords[i] + bords[i + 1]) / 2)
            part_plateau = float(compte[i] / len(h))
    # remplissage sous le plateau, sur la hauteur vue : part des cases de 5 cm occupées le long des côtés,
    # tranche de 5 cm par tranche de 5 cm, du bas vu jusque sous le plateau (une face pleine n'est pas
    # le chant de 4 cm d'un plateau de table) ; None si rien n'a été vu sous le plateau
    sommet = (plateau if plateau is not None else haut) - 0.075
    bas = float(np.percentile(h, 1))
    tu, tv = (xy - centre) @ u, (xy - centre) @ v
    couches = []
    for z0 in np.arange(bas, sommet - 0.05 + 1e-9, 0.05):
        dans = (h >= z0) & (h < z0 + 0.05)
        fractions = []
        for t, etendue in ((tu, longueur), (tv, largeur)):
            if etendue >= 0.25:
                cases = np.unique(np.floor((t[dans] + etendue / 2) / grille).astype(int))
                fractions.append(min(1.0, len(cases) / max(1.0, etendue / grille)))
        couches.append(max(fractions) if fractions else float(dans.any()))
    remplissage = float(np.mean(couches)) if couches else None
    cotes_seuls = h < haut - 0.1                         # le dessus d'un cylindre plein n'est pas sur le cercle
    cercle = _cercle(xy[cotes_seuls] if cotes_seuls.sum() >= 10 else xy)
    rondeur, centre_cercle, rayon = 0.0, None, None
    if cercle is not None:
        centre_cercle, rayon, ecart = cercle
        xy_c = xy[cotes_seuls] if cotes_seuls.sum() >= 10 else xy
        angles = np.arctan2(xy_c[:, 1] - centre_cercle[1], xy_c[:, 0] - centre_cercle[0])
        arc = len(np.unique(np.floor((angles + math.pi) / (math.pi / 12)).astype(int))) * 15.0   # degrés vus
        # un cercle plus grand que l'emprise (arc presque plat, moins de 90° vus) n'est pas crédible
        if (0.05 <= rayon <= 0.7 and 2 * rayon <= max(longs) + grille + 0.15
                and np.linalg.norm(centre_cercle - xy_c.mean(axis=0)) <= rayon + 0.1):
            rondeur = (appartenance(ecart, 0.0, 0.015, 0.03) * appartenance(arc, 90.0, 360.0, 60.0)
                       * appartenance(rayon, 0.08, 0.5, 0.15))
    # densité : points par case de 5 cm de la plus grande face (côté, ou dessus vu d'en haut)
    haut_brut = float(np.percentile(h, 99))
    face = max(longueur * max(haut_brut - bas, grille), longueur * largeur) / (grille * grille)
    return {"points": int(len(pts)), "centre": centre, "cap": cap, "longueur": longueur, "largeur": largeur,
            "hauteur": haut, "bas": bas, "plateau": plateau, "part_plateau": part_plateau,
            "densite": len(pts) / max(1.0, face),
            "remplissage": remplissage, "rondeur": rondeur,
            "centre_cercle": centre_cercle, "rayon": rayon, "finesse": haut / max(longueur, 0.05)}


def scores_categories(f, p):
    """Score de 0 à 1 de chaque catégorie pour un objet décrit par decrire_objet (règles simples)."""
    h, longueur, largeur = f["hauteur"], f["longueur"], f["largeur"]
    plateau = f["plateau"] if f["plateau"] is not None else h
    # plein : 1 pour un bloc plein, 0 pour un plateau sur pieds ; 0,5 si on n'a rien vu sous le plateau
    plein = 0.5 if f["remplissage"] is None else appartenance(f["remplissage"], p["remplissage_plein"], 1.0, 0.25)
    if largeur <= 0.25 and longueur >= 0.8 and h - f["bas"] >= 0.15:
        plein = max(plein, 0.8)        # face mince, longue et haute : un bloc vu de face, pas le chant d'un plateau
    a = appartenance
    s = {}
    s["personne"] = (a(h, *p["personne_hauteur"], 0.1) * a(longueur, *p["personne_emprise"], 0.15)
                     * a(largeur, 0.0, p["personne_emprise"][1], 0.15))
    s["poteau"] = (a(h, p["poteau_hauteur_min"], 99.0, 0.1) * a(longueur, 0.0, p["poteau_emprise_max"], 0.15)
                   * a(f["finesse"], p["poteau_finesse_min"], 999.0, 1.0))
    s["table"] = (a(plateau, *p["table_plateau"], 0.07) * a(h - plateau, -1.0, 0.1, 0.15)
                  * a(longueur, 0.6, 4.0, 0.25) * a(largeur, p["table_profondeur_min"], 99.0, 0.15)
                  * (1.0 - 0.8 * plein))
    s["chaise"] = max(a(h, *p["chaise_hauteur"], 0.08) * a(longueur, 0.2, p["chaise_emprise_max"], 0.15)
                      * (1.0 - 0.6 * f["rondeur"]) * (1.0 - 0.4 * plein),
                      # assise seule (dossier caché) : basse, petite, ni ronde ni pleine ; moins sûr
                      0.7 * a(h, *p["chaise_assise"], 0.08) * a(longueur, 0.25, p["chaise_emprise_max"] - 0.1, 0.15)
                      * (1.0 - 0.5 * f["rondeur"]) * (1.0 - 0.6 * plein))
    s["poubelle"] = (a(h, *p["poubelle_hauteur"], 0.08) * a(longueur, 0.2, p["poubelle_emprise_max"], 0.1)
                     * max(f["rondeur"], 0.2) * plein)
    s["banc"] = (a(h, *p["banc_hauteur"], 0.05) * a(longueur, p["banc_longueur_min"], 4.0, 0.25)
                 * a(largeur, p["banc_profondeur_min"], 2.0, 0.1))     # une assise a de la profondeur
    large = a(longueur, p["meuble_emprise_min"], 8.0, 0.25)
    s["meuble"] = max(a(h, p["meuble_hauteur_haut"], 3.0, 0.15) * large,
                      a(h, p["meuble_hauteur_min"], 3.0, 0.1) * large * plein)
    return s


def classer(f, p):
    """(catégorie, confiance, scores). Meilleur score ; « inconnu » s'il est sous categorie_score_min.
    La confiance baisse quand une autre catégorie est presque aussi probable, et pour un groupe
    de peu de points."""
    scores = scores_categories(f, p)
    ordre = sorted(scores.items(), key=lambda e: (-e[1], e[0]))
    (meilleure, score), (_, second) = ordre[0], ordre[1]
    nombre = min(1.0, f["points"] / 60.0)
    if score < p["categorie_score_min"]:
        return "inconnu", round(0.2 + 0.2 * nombre, 2), scores
    confiance = score * (1.0 - 0.5 * second / score) * (0.6 + 0.4 * nombre)
    return meilleure, round(min(0.98, max(0.05, 0.15 + 0.85 * confiance)), 2), scores


def forme_objet(f, categorie, grille=0.05):
    """Forme mesurée d'un objet : cylindre (poteau, poubelle, personne) ou boîte orientée."""
    if categorie in ("poteau", "poubelle", "personne"):
        if f["centre_cercle"] is not None and f["rondeur"] > 0:
            centre, rayon = f["centre_cercle"], f["rayon"]
        else:
            centre, rayon = f["centre"], max(f["longueur"], f["largeur"]) / 2
        return {"forme": "cylindre", "centre": centre, "rayon": min(5.0, max(0.03, rayon + grille / 2)),
                "hauteur": min(10.0, max(0.05, f["hauteur"]))}
    return {"forme": "boite", "centre": f["centre"],
            "taille": [min(20.0, max(0.05, f["longueur"])), min(20.0, max(0.05, f["largeur"])),
                       min(10.0, max(0.05, f["hauteur"]))],
            "cap": f["cap"]}


def _reste_de_mur(f, murs, xy, p):
    """Vrai si le groupe est un reste de mur : mince, parallèle à un mur et tout près de lui ; ou
    petit, presque aussi haut que le mur et contre lui (la tranche d'un mur au bord d'une porte ou
    d'un trou bouché, un pilastre)."""
    from atelier.lieu.geometrie import dist_point_segment
    for m in murs:
        if (f["longueur"] <= 0.35 and f["hauteur"] >= 0.8 * m.hauteur
                and dist_point_segment(tuple(f["centre"]), tuple(m.de), tuple(m.a)) <= p["objet_bout_mur"]):
            return True
    if f["largeur"] > 0.15 or f["longueur"] < 0.1:
        return False
    u = np.array([math.cos(f["cap"]), math.sin(f["cap"])])
    for m in murs:
        if math.degrees(math.acos(min(1.0, abs(float(u @ m.u))))) > 15:
            continue
        t, s = m.coordonnees(xy)
        if (np.mean(np.abs(s) <= p["objet_reste_mur"]) >= 0.8
                and np.mean((t >= m.t0 - 0.3) & (t <= m.t1 + 0.3)) >= 0.8):
            return True
    return False


# ---------------------------------------------------------------- emprise et départ du robot

def emprise_de_la_carte(info, image):
    """(xmin, ymin, xmax, ymax) : les bords des pixels connus (libres ou occupés) de la carte."""
    lignes, colonnes = np.nonzero(np.asarray(image) != INCONNU)
    if len(lignes) == 0:
        return L.bornes_carte(info)
    x0, y0 = L.pixel_vers_monde(colonnes.min(), lignes.max(), info)
    x1, y1 = L.pixel_vers_monde(colonnes.max(), lignes.min(), info)
    demi = info.resolution / 2
    return (float(x0) - demi, float(y0) - demi, float(x1) + demi, float(y1) + demi)


def depart_par_defaut(info, image, emprise):
    """Point libre de la carte près du centre de l'emprise, à au moins 0,5 m des obstacles si
    possible (sinon le plus dégagé) : (x, y, 0.0)."""
    import cv2
    image = np.asarray(image)
    libre = (image == LIBRE).astype(np.uint8)
    if not libre.any():
        return ((emprise[0] + emprise[2]) / 2, (emprise[1] + emprise[3]) / 2, 0.0)
    distance = cv2.distanceTransform(np.where(image == OCCUPE, 0, 1).astype(np.uint8), cv2.DIST_L2, 5)
    distance = distance * info.resolution * libre
    seuil = min(0.5, float(distance.max()) * 0.8)
    lignes, colonnes = np.nonzero(distance >= seuil)
    x, y = L.pixel_vers_monde(colonnes, lignes, info)
    cx, cy = (emprise[0] + emprise[2]) / 2, (emprise[1] + emprise[3]) / 2
    i = int(np.argmin((np.asarray(x) - cx) ** 2 + (np.asarray(y) - cy) ** 2))
    return (float(np.asarray(x)[i]), float(np.asarray(y)[i]), 0.0)


# ---------------------------------------------------------------- tout ensemble

def _charger(chemin_pcd, chemin_carte):
    from atelier.scan.carte3d import ErreurCarte3d, lire_pcd
    chemin_pcd, chemin_carte = Path(chemin_pcd), Path(chemin_carte)
    if not chemin_pcd.is_file():
        raise ErreurReconnaissance(f"nuage introuvable : {chemin_pcd} ; fabriquez-le d'abord (g1-scan traiter, "
                                   "ou g1-carte-3d)")
    try:
        points = np.asarray(lire_pcd(chemin_pcd), dtype=float).reshape(-1, 3)
    except (ErreurCarte3d, OSError, RuntimeError) as e:
        raise ErreurReconnaissance(f"nuage illisible ({chemin_pcd}) : {e} ; refaites la carte 3D") from None
    points = points[np.isfinite(points).all(axis=1)]
    if len(points) < 100:
        raise ErreurReconnaissance(f"nuage presque vide ({len(points)} points, {chemin_pcd}) : le scan n'a rien "
                                   "enregistré d'utile ; recommencez le scan en faisant le tour de l'étage")
    if not chemin_carte.is_file():
        raise ErreurReconnaissance(f"carte introuvable : {chemin_carte} ; fabriquez-la d'abord (g1-scan traiter, "
                                   "ou g1-carte-2d --sortie)")
    try:
        info, image = L.charger_carte(chemin_carte)
    except L.ErreurLieu as e:
        detail = "; ".join(e.erreurs) if getattr(e, "erreurs", None) else str(e)
        raise ErreurReconnaissance(f"carte illisible ({chemin_carte}) : {detail} ; refaites la carte 2D") from None
    return points, info, np.asarray(image)


def _session_par_defaut(dossier):
    nom = Path(dossier).name
    return nom if L.scans.MOTIF_SESSION.match(nom) else None


def _ids(prefixe, compteur, pris):
    while True:
        compteur[prefixe] = compteur.get(prefixe, 0) + 1
        identifiant = f"{prefixe}_{compteur[prefixe]}"
        if identifiant not in pris and identifiant not in ("sol", "g1_proxy"):
            pris.add(identifiant)
            return identifiant


def analyser(points, info, image, p, generaux=None, progression=None):
    """Toute la reconnaissance, en mémoire : renvoie (donnees de reconnaissance.yaml, avertissements,
    details). Rien n'est écrit."""
    generaux = generaux or {}
    avancer = progression or (lambda *_: None)
    avertissements = []
    # 1. sol et plafond
    avancer(0.05, "sol")
    sol = trouver_sol(points, p, generaux.get("sol"))
    if sol["methode"] == "centile":
        avertissements.append("sol : aucun plan horizontal assez grand trouvé par RANSAC ; hauteur du sol prise au "
                              f"1er centile des points ({sol['sol']:.2f} m)")
    h = hauteurs(points, sol["plan"])
    plafond = trouver_plafond(points, h, p)
    garde = h > p["sol_retrait"]
    garde &= h < (plafond - 0.08 if plafond is not None else p["objet_hauteur_max"])
    # 2. murs, sur les points de la tranche qui tombent dans la carte
    avancer(0.2, "murs")
    colonnes, lignes = L.monde_vers_pixel(points[:, 0], points[:, 1], info)
    dans_carte = np.asarray(L.dans_image(colonnes, lignes, info), dtype=bool)
    tranche = garde & dans_carte & (h >= p["mur_tranche"][0]) & (h <= p["mur_tranche"][1])
    murs, voisins = extraire_murs(points[tranche, :2], info, p)
    mesurer_murs(murs, points, h, p, plafond)
    bas_et_courts = [m for m in murs if m.hauteur < p["mur_hauteur_min"] and m.longueur < p["mur_longueur_basse"]]
    if bas_et_courts:                                          # leurs points sont rendus aux objets
        murs = [m for m in murs if m not in bas_et_courts]
        voisins = [(m1, m2) for m1, m2 in voisins if m1 in murs and m2 in murs]
    au_mur = mesurer_murs(murs, points, h, p, plafond)
    if not murs:
        avertissements.append("aucun mur reconnu : le nuage n'a presque pas de points entre "
                              f"{p['mur_tranche'][0]:g} et {p['mur_tranche'][1]:g} m au-dessus du sol "
                              f"(sol à {sol['sol']:.2f} m) ; vérifiez le scan")
    # 3. passages
    avancer(0.5, "passages")
    passages = trouver_passages(voisins, murs, points, h, p)
    # 4. objets
    avancer(0.6, "objets")
    reste = np.nonzero(garde & dans_carte & ~au_mur & (h >= p["objet_bas"]))[0]
    entoure = np.zeros(len(points), dtype=bool)
    entoure[reste] = points_entoures(points[reste], p)
    groupes = regrouper_objets(points[reste], p, h[reste], entoure[reste])
    objets, ignores, groupes_decrits = [], {"bas": 0, "reste_de_mur": 0, "trace": 0, "petit": 0}, []
    for g in groupes:
        idx = _partie_principale(reste[g], h, p)
        if len(idx) < p["objet_points_min"]:
            ignores["petit"] += 1
            continue
        f = decrire_objet(points[idx], h[idx], p["grille"], entoure[idx])
        raison = None
        if f["hauteur"] < p["objet_hauteur_min"]:
            raison = "bas"
        elif _reste_de_mur(f, murs, points[idx, :2], p):
            raison = "reste_de_mur"
        elif (f["densite"] < p["objet_densite_min"] or f["bas"] > p["objet_bas_max"]
              or (f["longueur"] <= p["colonne_largeur_max"] and f["points"] < p["colonne_points_max"])):
            raison = "trace"
        if raison:
            ignores[raison] += 1
            groupes_decrits.append((f, raison))
            continue
        categorie, confiance, scores = classer(f, p)
        objets.append((f, categorie, confiance, scores))
        groupes_decrits.append((f, categorie))
    # emprise : celle de la carte, agrandie pour contenir tout ce qui a été reconnu
    avancer(0.9, "monde")
    xmin, ymin, xmax, ymax = emprise_de_la_carte(info, image)
    depart = generaux.get("depart_robot")
    if isinstance(depart, dict):
        depart = (depart["x"], depart["y"], depart.get("theta", 0.0))
    if depart is not None:
        dx, dy, dtheta = (float(v) for v in depart)
    else:
        dx, dy, dtheta = depart_par_defaut(info, image, (xmin, ymin, xmax, ymax))
    a_contenir = [(dx, dy)] + [tuple(q) for m in murs for q in (m.de, m.a)]
    a_contenir += [tuple(f["centre_cercle"] if f["centre_cercle"] is not None else f["centre"])
                   for f, *_ in objets] + [tuple(f["centre"]) for f, *_ in objets]
    for x, y in a_contenir:
        xmin, ymin, xmax, ymax = min(xmin, x), min(ymin, y), max(xmax, x), max(ymax, y)
    emprise = (math.floor(xmin * 100) / 100, math.floor(ymin * 100) / 100,
               math.ceil(xmax * 100) / 100, math.ceil(ymax * 100) / 100)
    parametres_ecrits = {cle: v for cle, v in p.items()}
    donnees = L.nouvelle_reconnaissance(generaux.get("etage", "rdc"), emprise,
                                        (_r(dx), _r(dy), _r(dtheta, 4)), session=generaux.get("session"),
                                        sol=_r(sol["sol"]), parametres=parametres_ecrits)
    pris, compteur = set(), {}
    for m in sorted(murs, key=lambda m: (round(min(m.de[1], m.a[1]), 2), round(min(m.de[0], m.a[0]), 2))):
        m.id = _ids("mur", compteur, pris)
        donnees["murs"].append({"id": m.id, "categorie": "mur", "de": [_r(m.de[0]), _r(m.de[1])],
                                "a": [_r(m.a[0]), _r(m.a[1])], "epaisseur": _r(min(1.0, max(0.02, m.epaisseur))),
                                "hauteur": _r(m.hauteur), "confiance": _r(m.confiance, 2),
                                "a_garder": L.a_garder_par_defaut("mur"),
                                "infos": {"points": m.points, "longueur": _r(m.longueur),
                                          "deux_faces": m.deux_faces, "couverture": _r(m.couverture, 2)}})
    for m1, m2, de, a, confiance, infos in passages:
        donnees["passages"].append({"id": _ids("passage", compteur, pris), "categorie": "passage",
                                    "de": [_r(de[0]), _r(de[1])], "a": [_r(a[0]), _r(a[1])], "murs": [m1.id, m2.id],
                                    "confiance": _r(confiance, 2), "a_garder": L.a_garder_par_defaut("passage"),
                                    "infos": infos})
    for f, categorie, confiance, scores in objets:
        forme = forme_objet(f, categorie, p["grille"])
        element = {"id": _ids(categorie, compteur, pris), "categorie": categorie, "forme": forme["forme"],
                   "centre": [_r(forme["centre"][0]), _r(forme["centre"][1])]}
        if forme["forme"] == "boite":
            element.update(taille=[_r(v) for v in forme["taille"]], cap=_r(forme["cap"], 4))
        else:
            element.update(rayon=_r(forme["rayon"]), hauteur=_r(forme["hauteur"]))
        meilleurs = sorted(scores.items(), key=lambda e: -e[1])[:3]
        element.update(confiance=confiance, a_garder=L.a_garder_par_defaut(categorie),
                       infos={"points": f["points"], "hauteur_mesuree": _r(f["hauteur"]),
                              "plateau": None if f["plateau"] is None else _r(f["plateau"]),
                              "remplissage": None if f["remplissage"] is None else _r(f["remplissage"], 2),
                              "rondeur": _r(f["rondeur"], 2),
                              "scores": {c: _r(v, 2) for c, v in meilleurs}})
        donnees["objets"].append(element)
    details = {"sol": sol, "plafond": plafond, "ignores": ignores, "points": int(len(points)),
               "points_tranche_murs": int(tranche.sum()), "groupes": groupes_decrits}
    return donnees, avertissements, details


def reconnaitre(chemin_pcd, chemin_carte_yaml, dossier_sortie, parametres=None, progression=None):
    """Reconnaît murs, passages et objets d'un scan et écrit, dans dossier_sortie,
    reconnaissance.yaml et monde_scan.monde.yaml (section 9.6 du plan).

    parametres : dict facultatif. Clés générales : depart_robot (x, y, theta), session, etage
    (« rdc » par défaut), sol (hauteur imposée) ; les autres sont des réglages de PARAMETRES.
    progression : fonction facultative appelée avec (fraction de 0 à 1, étape).
    Renvoie {fichier, monde, resume, duree_s, avertissements}.
    ErreurReconnaissance (message qui dit quoi faire) si c'est impossible ; rien n'est alors écrit.
    """
    debut = time.monotonic()
    p, generaux = _reglages(parametres)
    dossier = Path(dossier_sortie)
    generaux.setdefault("session", _session_par_defaut(dossier))
    generaux.setdefault("etage", "rdc")
    if not MOTIF_ID.match(str(generaux["etage"])):
        raise ErreurReconnaissance(f"étage « {generaux['etage']} » : identifiant invalide (lettres minuscules "
                                   "sans accent, chiffres, _ et -, ex. rdc)")
    points, info, image = _charger(chemin_pcd, chemin_carte_yaml)
    try:
        donnees, avertissements, _ = analyser(points, info, image, p, generaux, progression)
    except ErreurReconnaissance:
        raise
    except Exception as e:                                     # erreur imprévue : message clair, rien d'écrit
        raise ErreurReconnaissance(f"la reconnaissance a échoué ({type(e).__name__} : {e}) ; la carte 2D reste "
                                   "utilisable : adoptez-la sans le monde, ou refaites le traitement "
                                   "(g1-scan traiter)") from e
    conseil = ("défaut de la reconnaissance, à signaler avec le dossier de la session ; en attendant, la carte "
               "2D reste utilisable : adoptez-la sans le monde")
    erreurs = L.valider_reconnaissance(donnees)
    if erreurs:
        raise ErreurReconnaissance(f"reconnaissance invalide ({' ; '.join(erreurs[:5])}) : {conseil}")
    monde = L.monde_depuis_reconnaissance(donnees)
    erreurs = L.valider_donnees("monde", monde.vers_dict(), "monde_scan.monde.yaml")
    if erreurs:
        raise ErreurReconnaissance(f"monde tiré du scan invalide ({' ; '.join(erreurs[:5])}) : {conseil}")
    try:
        dossier.mkdir(parents=True, exist_ok=True)
        fichier = L.ecrire_reconnaissance(dossier / L.FICHIERS_SESSION["reconnaissance"], donnees)
        L.ecrire_monde_scan(dossier / L.FICHIERS_SESSION["monde"], donnees)
    except (L.ErreurLieu, OSError) as e:
        raise ErreurReconnaissance(f"écriture impossible dans {dossier} : {e} ; vérifiez le dossier "
                                   "(droits, place libre)") from None
    if progression:
        progression(1.0, "fini")
    return {"fichier": str(fichier), "monde": str(dossier / L.FICHIERS_SESSION["monde"]),
            "resume": L.resume_reconnaissance(donnees), "duree_s": round(time.monotonic() - debut, 2),
            "avertissements": avertissements}


# ---------------------------------------------------------------- ligne de commande (mise au point)

def _valeur(texte):
    try:
        return json.loads(texte)
    except json.JSONDecodeError:
        return texte


def main(argv=None):
    analyseur = argparse.ArgumentParser(
        prog="python -m atelier.scan.reconnaissance",
        description="Reconnaît murs, passages et objets d'un scan ; écrit reconnaissance.yaml et "
                    "monde_scan.monde.yaml dans DOSSIER.")
    analyseur.add_argument("nuage", help="nuage 3D .pcd du scan")
    analyseur.add_argument("carte", help="carte 2D .yaml du scan (son .pgm à côté)")
    analyseur.add_argument("dossier", help="dossier où écrire (en général : le dossier de la session)")
    analyseur.add_argument("--etage", help="étage (défaut : rdc)")
    analyseur.add_argument("--session", help="identifiant de session (défaut : le nom du dossier s'il en a la forme)")
    analyseur.add_argument("--depart", nargs=3, type=float, metavar=("X", "Y", "THETA"),
                           help="pose de départ du robot (défaut : un point libre près du centre)")
    analyseur.add_argument("--sol", type=float, help="hauteur du sol imposée (défaut : trouvée par RANSAC)")
    analyseur.add_argument("--parametre", action="append", default=[], metavar="CLE=VALEUR",
                           help="réglage de PARAMETRES, ex. --parametre dbscan_eps=0.15 (valeur en JSON)")
    analyseur.add_argument("--json", action="store_true", help="affiche le résultat en JSON")
    args = analyseur.parse_args(argv)
    parametres = {}
    for texte in args.parametre:
        if "=" not in texte:
            analyseur.error(f"--parametre {texte} : écrivez CLE=VALEUR")
        cle, valeur = texte.split("=", 1)
        parametres[cle.strip()] = _valeur(valeur)
    for cle in ("etage", "session", "sol"):
        if getattr(args, cle) is not None:
            parametres[cle] = getattr(args, cle)
    if args.depart:
        parametres["depart_robot"] = args.depart
    try:
        resultat = reconnaitre(args.nuage, args.carte, args.dossier, parametres)
    except ErreurReconnaissance as e:
        print(f"Erreur : {e}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(resultat, ensure_ascii=False, indent=2))
        return 0
    r = resultat["resume"]
    print(f"Reconnaissance écrite : {resultat['fichier']} ({resultat['duree_s']:.1f} s)")
    print(f"Monde tiré du scan : {resultat['monde']}")
    print(f"Murs : {r['murs']} ; passages : {r['passages']} ; objets : "
          + (", ".join(f"{c} {n}" for c, n in sorted(r["objets"].items())) or "aucun"))
    for a in resultat["avertissements"]:
        print(f"Attention : {a}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
