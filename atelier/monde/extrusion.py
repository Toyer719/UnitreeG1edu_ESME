"""Carte 2D d'un étage scanné → un seul maillage STL pour Gazebo (vague 5, section 12.5 du plan, décision S3).

On ne reconnaît plus les murs ni les meubles : chaque pixel occupé de la carte du scan devient un bloc
fixe de « hauteur » mètres (1,5 m par défaut, au-dessus du LiDAR du robot simulé à 1,245 m). La carte
de Nav2 reste la référence et le monde de simulation en découle : ils ne peuvent pas se contredire,
quels que soient les meubles, et le LiDAR simulé voit ce que le vrai a vu.

  1. nettoyer : les taches de moins de AIRE_MIN pixels sont retirées, puis une fermeture 3 × 3 bouche
     les trous d'un pixel (beaucoup moins de blocs) ;
  2. rectangles : les pixels occupés, ligne par ligne, en plages ; une plage identique sur la ligne
     suivante agrandit le même rectangle (décomposition gloutonne, exacte : l'union des rectangles est
     exactement l'ensemble des pixels occupés) ;
  3. chaque rectangle devient une boîte fermée (12 triangles) de 0 à « hauteur » ; toutes les boîtes
     forment un seul STL binaire, en mètres, dans le repère map (le modèle Gazebo est posé en 0).

Essai du rapport (scan du 27/10, 1 617 boîtes) : un seul maillage tourne à 1,0 fois le temps réel,
contre 0,59 en boîtes séparées ; le contact avec le robot marche.

    maillage = maillage_carte(info, image, hauteur=1.5)        # {sommets, faces, boites, pixels}
    ecrire_stl(chemin, maillage["sommets"], maillage["faces"])
    ecrire_maillage_carte(lieu, etage, hauteur=1.5)            # mondes/<etage>_carte.stl

Toutes les conversions pixel ↔ mètres passent par atelier.lieu.conversions. Seulement numpy (OpenCV
si présent, pour les taches) : ce module tourne aussi avec le Python du système (g1_sim).
"""
import struct
from collections import deque

import numpy as np

from atelier.lieu import (HAUTEUR_CARTE_EXTRUDEE, ErreurLieu, charger_carte, chemin_carte, chemin_maillage,
                          ecrire_atomique, pixel_vers_monde)

AIRE_MIN = 4               # pixels : une tache occupée plus petite est du bruit (comme la carte du scan)
FERMETURE = 1              # rayon (en pixels) de la fermeture qui bouche les petits trous
HAUTEUR_MIN = 0.3          # m : plus bas, le LiDAR du robot simulé ne verrait pas les obstacles
TRIANGLES_PAR_BOITE = 12
ENTETE_STL = b"Atelier G1 : carte 2D extrudee (atelier.monde.extrusion)"
TYPE_TRIANGLE = np.dtype([("normale", "<f4", (3,)), ("a", "<f4", (3,)), ("b", "<f4", (3,)), ("c", "<f4", (3,)),
                          ("attribut", "<u2")])

# Les 12 triangles d'une boîte (sommets 0 à 3 en bas, 4 à 7 en haut), normales vers l'extérieur
FACES_BOITE = np.array([(0, 2, 1), (0, 3, 2),          # dessous
                        (4, 5, 6), (4, 6, 7),          # dessus
                        (0, 1, 5), (0, 5, 4),          # côté y min
                        (1, 2, 6), (1, 6, 5),          # côté x max
                        (2, 3, 7), (2, 7, 6),          # côté y max
                        (3, 0, 4), (3, 4, 7)])         # côté x min


# ---------------------------------------------------------------- nettoyage de la carte

def _decaler_ou(masque, rayon):
    """Dilatation par un carré de (2 rayon + 1) pixels."""
    h, w = masque.shape
    resultat = masque.copy()
    for dl in range(-rayon, rayon + 1):
        for dc in range(-rayon, rayon + 1):
            resultat[max(0, dl):h - max(0, -dl), max(0, dc):w - max(0, -dc)] |= \
                masque[max(0, -dl):h - max(0, dl), max(0, -dc):w - max(0, dc)]
    return resultat


def fermer(occupe, rayon=FERMETURE):
    """Fermeture morphologique (dilatation puis érosion) par un carré de (2 rayon + 1) pixels : bouche les
    trous et les fentes de moins de 2 rayon + 1 pixels, sans grossir les obstacles."""
    occupe = np.asarray(occupe, dtype=bool)
    if rayon <= 0:
        return occupe.copy()
    # marge : une érosion ne doit pas ronger les obstacles posés au bord de l'image
    grand = np.pad(occupe, rayon, mode="edge")
    dilate = _decaler_ou(grand, rayon)
    erode = ~_decaler_ou(~dilate, rayon)
    return erode[rayon:-rayon, rayon:-rayon]


def sans_petites_taches(occupe, aire_min=AIRE_MIN):
    """Retire les taches (8 voisins) de moins de aire_min pixels."""
    occupe = np.asarray(occupe, dtype=bool)
    if aire_min <= 1 or not occupe.any():
        return occupe.copy()
    try:
        import cv2
    except ImportError:
        cv2 = None
    if cv2 is not None:
        _, etiquettes, stats, _ = cv2.connectedComponentsWithStats(occupe.astype(np.uint8), connectivity=8)
        grandes = stats[:, cv2.CC_STAT_AREA] >= aire_min
        grandes[0] = False
        return grandes[etiquettes] & occupe
    hauteur, largeur = occupe.shape
    vu = np.zeros_like(occupe)
    garde = np.zeros_like(occupe)
    for depart in zip(*np.nonzero(occupe)):
        if vu[depart]:
            continue
        tache, file = [], deque([depart])
        vu[depart] = True
        while file:
            ligne, colonne = file.popleft()
            tache.append((ligne, colonne))
            for dl in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    nl, nc = ligne + dl, colonne + dc
                    if 0 <= nl < hauteur and 0 <= nc < largeur and occupe[nl, nc] and not vu[nl, nc]:
                        vu[nl, nc] = True
                        file.append((nl, nc))
        if len(tache) >= aire_min:
            lignes, colonnes = zip(*tache)
            garde[list(lignes), list(colonnes)] = True
    return garde


def nettoyer(occupe, aire_min=AIRE_MIN, fermeture=FERMETURE):
    """Pixels occupés à extruder : sans les petites taches, puis fermés."""
    return fermer(sans_petites_taches(occupe, aire_min), fermeture)


# ---------------------------------------------------------------- rectangles

def plages(ligne):
    """Plages de pixels vrais consécutifs d'une ligne : liste de (début, fin) inclus."""
    d = np.diff(np.concatenate(([0], np.asarray(ligne, dtype=np.int8), [0])))
    debuts = np.nonzero(d == 1)[0]
    fins = np.nonzero(d == -1)[0] - 1
    return list(zip(debuts.tolist(), fins.tolist()))


def rectangles(occupe):
    """Décomposition gloutonne des pixels occupés (tableau (lignes, colonnes) de booléens) en rectangles
    (colonne0, ligne0, colonne1, ligne1), bornes incluses : les plages de chaque ligne, une plage
    identique sur la ligne suivante prolongeant le même rectangle. L'union est exactement l'ensemble
    des pixels occupés, sans recouvrement."""
    occupe = np.asarray(occupe, dtype=bool)
    ouverts = {}                 # (colonne0, colonne1) → ligne du haut
    resultat = []
    for ligne in range(occupe.shape[0]):
        suivants = {}
        for plage in plages(occupe[ligne]):
            suivants[plage] = ouverts.pop(plage, ligne)
        for (c0, c1), l0 in ouverts.items():
            resultat.append((c0, l0, c1, ligne - 1))
        ouverts = suivants
    for (c0, c1), l0 in ouverts.items():
        resultat.append((c0, l0, c1, occupe.shape[0] - 1))
    return resultat


# ---------------------------------------------------------------- maillage

def boites_metres(rects, info):
    """Rectangles de pixels → boîtes au sol en mètres : tableau (n, 4) de (xmin, ymin, xmax, ymax).
    La ligne 0 de l'image est le y maximal (atelier.lieu.conversions)."""
    if not rects:
        return np.zeros((0, 4))
    r = np.asarray(rects, dtype=np.int64)
    x0, y_haut = pixel_vers_monde(r[:, 0], r[:, 1], info)        # centre du pixel en haut à gauche
    x1, y_bas = pixel_vers_monde(r[:, 2], r[:, 3], info)         # centre du pixel en bas à droite
    demi = info.resolution / 2
    return np.column_stack([np.asarray(x0) - demi, np.asarray(y_bas) - demi,
                            np.asarray(x1) + demi, np.asarray(y_haut) + demi])


def maillage_boites(boites, hauteur):
    """Boîtes (n, 4) (xmin, ymin, xmax, ymax), de z = 0 à hauteur → (sommets (8n, 3), faces (12n, 3))."""
    boites = np.asarray(boites, dtype=float).reshape(-1, 4)
    n = len(boites)
    x0, y0, x1, y1 = boites.T
    zeros, h = np.zeros(n), np.full(n, float(hauteur))
    coins = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    sommets = np.stack([np.column_stack([x, y, z]) for z in (zeros, h) for x, y in coins], axis=1)
    faces = (np.arange(n)[:, None, None] * 8 + FACES_BOITE[None, :, :]).reshape(-1, 3)
    return sommets.reshape(-1, 3), faces


def maillage_carte(info, image, hauteur=HAUTEUR_CARTE_EXTRUDEE, aire_min=AIRE_MIN, fermeture=FERMETURE):
    """Carte 2D (InfoCarte, image : 0 occupé) → {sommets, faces, boites (nombre), pixels (occupés de la
    carte), pixels_extrudes}. ErreurLieu si la hauteur est trop basse."""
    if not hauteur >= HAUTEUR_MIN:
        raise ErreurLieu(f"hauteur de la carte extrudée : {hauteur} m ; il faut au moins {HAUTEUR_MIN:g} m "
                         "(1,5 m par défaut, au-dessus du LiDAR du robot simulé)")
    occupe = np.asarray(image) == 0
    propre = nettoyer(occupe, aire_min, fermeture)
    rects = rectangles(propre)
    sommets, faces = maillage_boites(boites_metres(rects, info), hauteur)
    return {"sommets": sommets, "faces": faces, "boites": len(rects), "pixels": int(occupe.sum()),
            "pixels_extrudes": int(propre.sum())}


# ---------------------------------------------------------------- STL binaire

def triangles_stl(sommets, faces):
    """Tableau structuré TYPE_TRIANGLE (normale unitaire, trois sommets) des faces."""
    sommets = np.asarray(sommets, dtype=float)
    faces = np.asarray(faces, dtype=np.int64).reshape(-1, 3)
    a, b, c = sommets[faces[:, 0]], sommets[faces[:, 1]], sommets[faces[:, 2]]
    normales = np.cross(b - a, c - a)
    normes = np.linalg.norm(normales, axis=1)
    normales[normes > 0] /= normes[normes > 0, None]
    triangles = np.zeros(len(faces), dtype=TYPE_TRIANGLE)
    triangles["normale"], triangles["a"], triangles["b"], triangles["c"] = normales, a, b, c
    return triangles


def octets_stl(sommets, faces, entete=ENTETE_STL):
    """Contenu d'un STL binaire : 80 octets d'en-tête, le nombre de triangles, puis 50 octets par triangle."""
    triangles = triangles_stl(sommets, faces)
    return entete[:80].ljust(80, b" ") + struct.pack("<I", len(triangles)) + triangles.tobytes()


def ecrire_stl(chemin, sommets, faces, entete=ENTETE_STL):
    """Écrit le STL binaire de façon atomique. Renvoie le nombre de triangles."""
    contenu = octets_stl(sommets, faces, entete)
    ecrire_atomique(chemin, contenu)
    return (len(contenu) - 84) // TYPE_TRIANGLE.itemsize


def lire_stl(chemin):
    """STL binaire → tableau structuré TYPE_TRIANGLE. ErreurLieu s'il est tronqué ou n'est pas binaire."""
    donnees = open(chemin, "rb").read()
    if len(donnees) < 84:
        raise ErreurLieu(f"{chemin} : fichier STL trop court ({len(donnees)} octets)")
    n = struct.unpack_from("<I", donnees, 80)[0]
    if len(donnees) != 84 + n * TYPE_TRIANGLE.itemsize:
        raise ErreurLieu(f"{chemin} : STL binaire tronqué ou invalide ({len(donnees)} octets pour {n} triangles)")
    return np.frombuffer(donnees, dtype=TYPE_TRIANGLE, offset=84, count=n)


# ---------------------------------------------------------------- dans un lieu

def ecrire_maillage_carte(lieu, etage, hauteur=HAUTEUR_CARTE_EXTRUDEE):
    """Écrit mondes/<etage>_carte.stl depuis cartes/<etage>.yaml. Renvoie {fichier, triangles, boites,
    pixels, pixels_extrudes, hauteur, octets}. ErreurLieu si la carte manque ou n'a aucun obstacle."""
    carte = chemin_carte(lieu, etage)
    if not carte.is_file():
        raise ErreurLieu(f"cartes/{etage}.yaml n'existe pas : pas de carte à extruder (faites d'abord un scan, "
                         "puis « Utiliser cette carte »)")
    info, image = charger_carte(carte)
    m = maillage_carte(info, image, hauteur)
    if m["boites"] == 0:
        raise ErreurLieu(f"cartes/{etage}.pgm n'a aucun obstacle : rien à extruder pour la simulation")
    stl = chemin_maillage(lieu, etage)
    stl.parent.mkdir(parents=True, exist_ok=True)
    n = ecrire_stl(stl, m["sommets"], m["faces"])
    return {"fichier": stl, "triangles": n, "boites": m["boites"], "pixels": m["pixels"],
            "pixels_extrudes": m["pixels_extrudes"], "hauteur": float(hauteur), "octets": stl.stat().st_size}
