"""Conversions pixel ↔ monde pour les cartes 2D, et angle ↔ quaternion.

C'est le seul endroit du projet où l'on passe des mètres aux pixels (contrat 4.1).

Repères :
  - monde : repère map, en mètres, x vers la droite (est), y vers le haut (nord) sur la carte ;
  - image : colonne (de gauche à droite) et ligne (de haut en bas), en pixels, à partir de 0.
    La ligne 0 de l'image est en haut : c'est le y MAXIMAL de la carte (axe y inversé).
  - origin de la carte : position du coin bas gauche de l'image, c'est-à-dire du bord gauche
    de la colonne 0 et du bord bas de la dernière ligne (hauteur - 1).

Un pixel couvre [x0, x0 + résolution[ × [y0, y0 + résolution[ : un point sur le bord gauche ou
bas d'un pixel lui appartient, un point sur le bord droit ou haut appartient au voisin. Le bord
droit et le bord haut de l'image sont donc juste en dehors de l'image (voir dans_image).

Les fonctions acceptent des nombres ou des tableaux numpy de même forme.
Un quaternion est un tuple (x, y, z, w), dans l'ordre de ROS (geometry_msgs/Quaternion).
"""
import math

import numpy as np

from .modeles import InfoCarte

# Tolérance en pixel : 0.15 / 0.05 vaut 2.9999999999999996 en flottant, et doit donner 3
TOLERANCE_PIXEL = 1e-6


def _verifier(info):
    if not isinstance(info, InfoCarte):
        raise TypeError("info doit être un InfoCarte (atelier.lieu.charger_info_carte ou info_carte_pour_emprise)")
    if info.hauteur is None or info.largeur is None:
        raise ValueError("taille de l'image inconnue : chargez l'info avec charger_info_carte, "
                         "ou renseignez largeur et hauteur (en pixels)")
    if info.origin[2] != 0:
        raise ValueError("carte tournée (origin avec un lacet non nul) : non gérée par l'Atelier")


def _sortie(*valeurs):
    """Nombres Python si les entrées étaient des nombres, tableaux numpy sinon."""
    if all(np.ndim(v) == 0 for v in valeurs):
        return tuple(v.item() if hasattr(v, "item") else v for v in valeurs)
    return valeurs


def monde_vers_pixel(x, y, info):
    """(x, y) en mètres → (colonne, ligne) entières du pixel qui contient ce point.

    Le résultat peut sortir de l'image (point hors carte) : vérifiez avec dans_image().
    """
    _verifier(info)
    x0, y0 = info.origin[0], info.origin[1]
    colonne = np.floor((np.asarray(x, dtype=float) - x0) / info.resolution + TOLERANCE_PIXEL).astype(int)
    rang_y = np.floor((np.asarray(y, dtype=float) - y0) / info.resolution + TOLERANCE_PIXEL).astype(int)
    ligne = info.hauteur - 1 - rang_y
    return _sortie(colonne, ligne)


def pixel_vers_monde(colonne, ligne, info):
    """(colonne, ligne) d'un pixel → (x, y) en mètres de son CENTRE.

    Des valeurs non entières sont permises : colonne 0.5 tombe sur le bord droit du pixel 0.
    """
    _verifier(info)
    x = info.origin[0] + (np.asarray(colonne, dtype=float) + 0.5) * info.resolution
    y = info.origin[1] + (info.hauteur - np.asarray(ligne, dtype=float) - 0.5) * info.resolution
    return _sortie(x, y)


def dans_image(colonne, ligne, info):
    """Vrai si le pixel (colonne, ligne) est dans l'image."""
    _verifier(info)
    resultat = ((np.asarray(colonne) >= 0) & (np.asarray(colonne) < info.largeur)
                & (np.asarray(ligne) >= 0) & (np.asarray(ligne) < info.hauteur))
    return bool(resultat) if np.ndim(resultat) == 0 else resultat


def bornes_carte(info):
    """(xmin, ymin, xmax, ymax) en mètres : les bords extérieurs de l'image.

    Pour Leaflet (CRS.Simple) : imageOverlay(png, [[ymin, xmin], [ymax, xmax]]).
    """
    _verifier(info)
    x0, y0 = info.origin[0], info.origin[1]
    return (x0, y0, x0 + info.largeur * info.resolution, y0 + info.hauteur * info.resolution)


def centres_pixels(info):
    """Tableaux (X, Y) de forme (hauteur, largeur) : coordonnées en mètres du centre de chaque
    pixel. X[ligne, colonne], Y[ligne, colonne] ; Y[0, :] est le y le plus grand."""
    _verifier(info)
    colonnes, lignes = np.meshgrid(np.arange(info.largeur), np.arange(info.hauteur))
    return pixel_vers_monde(colonnes, lignes, info)


def info_carte_pour_emprise(xmin, ymin, xmax, ymax, resolution=0.05, marge=1, image="carte.pgm"):
    """InfoCarte d'une carte qui couvre le rectangle donné (en mètres), plus une marge en pixels
    de chaque côté. Ex. emprise 30 × 20 m à 0,05 m, marge 1 : 602 × 402 pixels, origin [-0.05, -0.05, 0].
    """
    largeur = int(math.ceil((xmax - xmin) / resolution - TOLERANCE_PIXEL)) + 2 * marge
    hauteur = int(math.ceil((ymax - ymin) / resolution - TOLERANCE_PIXEL)) + 2 * marge
    origine = (float(xmin - marge * resolution), float(ymin - marge * resolution), 0.0)
    return InfoCarte(image=image, resolution=resolution, origin=origine, largeur=largeur, hauteur=hauteur)


def lire_info_carte(chemin_yaml):
    """Lit un .yaml de carte Nav2 (et la taille de son image .pgm) : voir fichiers.charger_info_carte."""
    from .fichiers import charger_info_carte
    return charger_info_carte(chemin_yaml)


# ---------------------------------------------------------------- angles

def normaliser_angle(theta):
    """Angle ramené dans [-π, π[."""
    return (theta + math.pi) % (2 * math.pi) - math.pi


def cap_vers_quaternion(theta):
    """Cap theta (radians, autour de z) → quaternion (x, y, z, w)."""
    return (0.0, 0.0, math.sin(theta / 2), math.cos(theta / 2))


def quaternion_vers_cap(q):
    """Quaternion → cap autour de z, en radians, dans ]-π, π].

    q : tuple ou liste (x, y, z, w), dictionnaire {x, y, z, w}, ou objet avec les attributs
    x, y, z, w (geometry_msgs/Quaternion). Il n'a pas besoin d'être normé.
    """
    if isinstance(q, dict):
        x, y, z, w = q["x"], q["y"], q["z"], q["w"]
    elif hasattr(q, "w"):
        x, y, z, w = q.x, q.y, q.z, q.w
    else:
        x, y, z, w = q
    norme = math.sqrt(x * x + y * y + z * z + w * w)
    if norme == 0:
        raise ValueError("quaternion nul : pas d'orientation")
    x, y, z, w = x / norme, y / norme, z / norme, w / norme
    return math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))


# ---------------------------------------------------------------- poses au sol (section 10 du plan)
#
# Une pose au sol est (x, y, theta) : position en mètres, cap en radians. Une pose « a » décrit un
# repère dans son repère parent. composer_poses(a, b) ramène dans le parent de a une pose b
# exprimée dans le repère a. Le repère de la carte d'Unitree est décrit, dans le repère map de
# l'étage, par la pose repere = atelier.lieu.repere_unitree(lieu, etage) :
#     pose_map = composer_poses(repere, pose_unitree)       (unitree_vers_carte)
#     pose_unitree = composer_poses(inverser_pose(repere), pose_map)   (carte_vers_unitree)
# Ces fonctions acceptent un tuple (x, y, theta), un dict {x, y, theta} ou un objet Pose, et
# renvoient un tuple de flottants, cap dans [-π, π[.

def _pose(p):
    if isinstance(p, dict):
        return float(p["x"]), float(p["y"]), float(p["theta"])
    if hasattr(p, "theta"):
        return float(p.x), float(p.y), float(p.theta)
    x, y, theta = p
    return float(x), float(y), float(theta)


def composer_poses(a, b):
    """a ∘ b : la pose b, exprimée dans le repère a, ramenée dans le repère parent de a."""
    ax, ay, at = _pose(a)
    bx, by, bt = _pose(b)
    c, s = math.cos(at), math.sin(at)
    return (ax + c * bx - s * by, ay + s * bx + c * by, normaliser_angle(at + bt))


def inverser_pose(a):
    """Pose inverse : composer_poses(a, inverser_pose(a)) vaut (0, 0, 0)."""
    ax, ay, at = _pose(a)
    c, s = math.cos(at), math.sin(at)
    return (-(c * ax + s * ay), -(-s * ax + c * ay), normaliser_angle(-at))


def unitree_vers_carte(pose_unitree, repere):
    """Pose dans le repère de la carte d'Unitree → pose dans le repère map de l'étage."""
    return composer_poses(repere, pose_unitree)


def carte_vers_unitree(pose_carte, repere):
    """Pose dans le repère map de l'étage → pose dans le repère de la carte d'Unitree (pour 1804)."""
    return composer_poses(inverser_pose(repere), pose_carte)
