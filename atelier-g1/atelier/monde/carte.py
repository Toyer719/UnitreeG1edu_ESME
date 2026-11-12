"""Carte 2D Nav2 d'un étage, tracée directement depuis son monde inventé (sans scan).

On regarde le monde de dessus, dans la tranche de 0,1 à 1,5 m de haut (celle où le robot peut
se cogner) : chaque mur et chaque objet qui coupe cette tranche devient occupé (0). L'intérieur
de l'emprise est libre (254) ; la marge d'un pixel autour de l'emprise est inconnue (205), sauf
là où un mur la recouvre. Les piétons ne vont pas sur la carte : ce sont des obstacles mobiles,
que le LiDAR verra. Un objet de catégorie personne (reconnu dans un scan, section 9.4 du plan)
n'y va pas non plus : il reste dans le monde Gazebo, mais jamais sur la carte.

Un pixel est occupé dès que l'empreinte au sol de l'objet le recouvre, même en partie ; un
recouvrement de moins de 1 mm ne compte pas (bords posés sur la grille, angles arrondis comme
1.5708). Un mur de 0,15 m tombe donc sur 3 ou 4 pixels, et un mur en biais ne laisse aucun trou
entre deux pixels en diagonale.

Toutes les conversions mètres ↔ pixels passent par atelier.lieu (contrat 4.1).
"""
import numpy as np

from atelier.lieu import (charger_monde, chemin_carte, enregistrer_carte, info_carte_pour_emprise,
                          monde_vers_pixel, pixel_vers_monde)

# Valeurs des pixels (contrat 4.1)
OCCUPE, LIBRE, INCONNU = 0, 254, 205
RESOLUTION = 0.05          # m par pixel
MARGE = 1                  # pixels autour de l'emprise
TRANCHE = (0.1, 1.5)       # m : hauteurs où un obstacle gêne le robot
EPS = 1e-3                 # m : un recouvrement plus petit ne compte pas


def coupe_tranche(hauteur, tranche=TRANCHE):
    """Vrai si un obstacle posé au sol, de cette hauteur, coupe la tranche."""
    return hauteur > tranche[0]


def fenetre_pixels(info, xmin, ymin, xmax, ymax):
    """Lignes et colonnes de l'image qui recouvrent le rectangle donné, ou None s'il est dehors.
    Renvoie (lignes, colonnes, X, Y) : tranches numpy et centres des pixels, en mètres."""
    c0, l1 = monde_vers_pixel(xmin, ymin, info)      # coin bas gauche : la ligne la plus basse
    c1, l0 = monde_vers_pixel(xmax, ymax, info)
    c0, l0 = max(c0 - 1, 0), max(l0 - 1, 0)
    c1, l1 = min(c1 + 1, info.largeur - 1), min(l1 + 1, info.hauteur - 1)
    if c0 > c1 or l0 > l1:
        return None
    colonnes, lignes = np.meshgrid(np.arange(c0, c1 + 1), np.arange(l0, l1 + 1))
    X, Y = pixel_vers_monde(colonnes, lignes, info)
    return slice(l0, l1 + 1), slice(c0, c1 + 1), X, Y


def pixels_polygone_convexe(info, coins):
    """Masque (lignes, colonnes, booléens) des pixels que le polygone convexe recouvre en partie.
    Test des axes séparateurs entre chaque pixel carré et le polygone."""
    coins = np.asarray(coins, dtype=float)
    fen = fenetre_pixels(info, *coins.min(axis=0), *coins.max(axis=0))
    if fen is None:
        return None
    lignes, colonnes, X, Y = fen
    h = info.resolution / 2
    # Axes x et y : boîte englobante du polygone
    dedans = ((X + h > coins[:, 0].min() + EPS) & (X - h < coins[:, 0].max() - EPS)
              & (Y + h > coins[:, 1].min() + EPS) & (Y - h < coins[:, 1].max() - EPS))
    # Normales aux côtés du polygone
    for a, b in zip(coins, np.roll(coins, -1, axis=0)):
        n = np.array([a[1] - b[1], b[0] - a[0]])
        if not n.any():
            continue
        n /= np.hypot(*n)
        proj = coins @ n
        centre = X * n[0] + Y * n[1]
        rayon = h * (abs(n[0]) + abs(n[1]))
        dedans &= (centre + rayon > proj.min() + EPS) & (centre - rayon < proj.max() - EPS)
    return lignes, colonnes, dedans


def pixels_cercle(info, centre, rayon):
    """Masque (lignes, colonnes, booléens) des pixels que le disque recouvre en partie."""
    cx, cy = centre
    fen = fenetre_pixels(info, cx - rayon, cy - rayon, cx + rayon, cy + rayon)
    if fen is None:
        return None
    lignes, colonnes, X, Y = fen
    h = info.resolution / 2
    dx = np.maximum(np.abs(X - cx) - h, 0.0)
    dy = np.maximum(np.abs(Y - cy) - h, 0.0)
    return lignes, colonnes, dx * dx + dy * dy < max(rayon - EPS, 0.0) ** 2


def _marquer(image, zone, valeur):
    if zone is not None:
        lignes, colonnes, dedans = zone
        image[lignes, colonnes][dedans] = valeur


def obstacles(monde, tranche=TRANCHE):
    """Murs et objets du monde qui coupent la tranche : liste de (id, empreinte), avec empreinte
    ("polygone", [coins]) ou ("cercle", centre, rayon). Les personnes (Objet.sur_la_carte faux)
    n'y sont jamais."""
    liste = [(m.id, ("polygone", m.coins())) for m in monde.murs if coupe_tranche(m.hauteur, tranche)]
    liste += [(o.id, o.empreinte()) for o in monde.objets
              if o.sur_la_carte and coupe_tranche(o.hauteur_totale(), tranche)]
    return liste


def fabriquer_carte(monde, image="carte.pgm", resolution=RESOLUTION, tranche=TRANCHE):
    """Monde → (InfoCarte, image numpy uint8 (hauteur, largeur)). image[0] : ligne du y maximal.

    Carte de l'emprise plus une marge d'un pixel ; image : nom du .pgm écrit dans le .yaml.
    """
    e = monde.emprise
    info = info_carte_pour_emprise(e.xmin, e.ymin, e.xmax, e.ymax, resolution, MARGE, image)
    carte = np.full((info.hauteur, info.largeur), INCONNU, dtype=np.uint8)

    # Intérieur de l'emprise : les pixels dont le centre est dans le rectangle
    colonnes, lignes = np.meshgrid(np.arange(info.largeur), np.arange(info.hauteur))
    X, Y = pixel_vers_monde(colonnes, lignes, info)
    carte[(X > e.xmin) & (X < e.xmax) & (Y > e.ymin) & (Y < e.ymax)] = LIBRE

    for _, empreinte in obstacles(monde, tranche):
        if empreinte[0] == "cercle":
            _marquer(carte, pixels_cercle(info, empreinte[1], empreinte[2]), OCCUPE)
        else:
            _marquer(carte, pixels_polygone_convexe(info, empreinte[1]), OCCUPE)
    return info, carte


def ecrire_carte(lieu, etage, monde=None):
    """Écrit cartes/<etage>.pgm et cartes/<etage>.yaml depuis le monde de l'étage.
    monde : Monde déjà chargé (sinon, lu dans mondes/<etage>.monde.yaml). Renvoie (chemin du .yaml, InfoCarte)."""
    if monde is None:
        monde = charger_monde(lieu, etage)
    chemin = chemin_carte(lieu, etage)
    info, image = fabriquer_carte(monde, image=f"{etage}.pgm")
    enregistrer_carte(chemin, info, image)
    return chemin, info
