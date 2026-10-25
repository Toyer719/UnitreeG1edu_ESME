"""Géométrie plane simple, en mètres : points, segments, rectangles et polygones.

Un point est un couple (x, y). Ces fonctions servent à vérifier un lieu (couloir qui traverse
un mur, salle dans une zone interdite...) ; elles n'ont besoin que du module math.
"""
import math


def dist_point_segment(p, a, b):
    """Distance du point p au segment [a, b]."""
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / l2))
    return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy))


def _orient(p, q, r):
    return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])


def segments_se_coupent(a, b, c, d):
    """Vrai si les segments [a, b] et [c, d] se croisent franchement (pas seulement se touchent)."""
    o1, o2, o3, o4 = _orient(a, b, c), _orient(a, b, d), _orient(c, d, a), _orient(c, d, b)
    return o1 * o2 < 0 and o3 * o4 < 0


def dist_segments(a, b, c, d):
    """Distance entre les segments [a, b] et [c, d] (0 s'ils se croisent)."""
    if segments_se_coupent(a, b, c, d):
        return 0.0
    return min(dist_point_segment(a, c, d), dist_point_segment(b, c, d),
               dist_point_segment(c, a, b), dist_point_segment(d, a, b))


def aretes(polygone):
    """Côtés du polygone, le dernier sommet relié au premier."""
    sommets = [tuple(p) for p in polygone]
    return list(zip(sommets, sommets[1:] + sommets[:1]))


def point_dans_polygone(p, polygone):
    """Vrai si p est à l'intérieur du polygone (règle pair-impair)."""
    x, y = p
    dedans = False
    for (x1, y1), (x2, y2) in aretes(polygone):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            dedans = not dedans
    return dedans


def dist_segment_polygone(a, b, polygone):
    """Distance du segment [a, b] au polygone plein (0 s'il le touche ou y entre)."""
    if point_dans_polygone(a, polygone) or point_dans_polygone(b, polygone):
        return 0.0
    return min(dist_segments(a, b, c, d) for c, d in aretes(polygone))


def aire_polygone(polygone):
    """Aire du polygone, en m² (toujours positive)."""
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in aretes(polygone))) / 2


def polygone_croise(polygone):
    """Vrai si deux côtés non voisins du polygone se croisent (contour en « 8 »)."""
    cotes = aretes(polygone)
    n = len(cotes)
    for i in range(n):
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue   # côtés voisins par le premier sommet
            if segments_se_coupent(*cotes[i], *cotes[j]):
                return True
    return False


def rectangle(centre, longueur, largeur, cap):
    """Les 4 coins d'un rectangle centré sur centre, de longueur le long du cap (radians)."""
    c, s = math.cos(cap), math.sin(cap)
    return [(centre[0] + c * u - s * v, centre[1] + s * u + c * v)
            for u, v in ((longueur / 2, largeur / 2), (-longueur / 2, largeur / 2),
                         (-longueur / 2, -largeur / 2), (longueur / 2, -largeur / 2))]


# ---------------------------------------------------------------- murs alignés et passages (section 9.4)

PASSAGE_MIN = 0.7                        # m : un passage (une porte) est un trou de 0,7 à 1,6 m
PASSAGE_MAX = 1.6                        # m   entre les bouts de deux murs alignés
ALIGNEMENT_ANGLE = math.radians(5.0)     # rad : écart de direction maximal de deux murs alignés
ALIGNEMENT_ECART = 0.10                  # m : écart maximal d'un bout d'un mur à la droite de l'autre


def dist_point_droite(p, a, b):
    """Distance du point p à la droite (a, b) ; à a si a et b sont confondus."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    longueur = math.hypot(dx, dy)
    if longueur == 0:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    return abs(dx * (p[1] - a[1]) - dy * (p[0] - a[0])) / longueur


def murs_alignes(de1, a1, de2, a2, angle_max=ALIGNEMENT_ANGLE, ecart_max=ALIGNEMENT_ECART):
    """Vrai si les segments [de1, a1] et [de2, a2] sont sur une même droite : directions égales à
    angle_max près (quel que soit le sens), et chaque bout de l'un à moins de ecart_max de la
    droite de l'autre."""
    c1 = math.atan2(a1[1] - de1[1], a1[0] - de1[0])
    c2 = math.atan2(a2[1] - de2[1], a2[0] - de2[0])
    ecart = abs((c1 - c2 + math.pi / 2) % math.pi - math.pi / 2)
    if ecart > angle_max:
        return False
    return (all(dist_point_droite(p, de1, a1) <= ecart_max for p in (de2, a2))
            and all(dist_point_droite(p, de2, a2) <= ecart_max for p in (de1, a1)))


def trou_entre(de1, a1, de2, a2):
    """Trou entre deux murs alignés : (largeur, p, q), p bout du premier et q bout du second qui
    bordent le trou. None si les deux murs se chevauchent ou se touchent le long de leur droite."""
    dx, dy = a1[0] - de1[0], a1[1] - de1[1]
    longueur = math.hypot(dx, dy)
    if longueur == 0:
        return None
    ux, uy = dx / longueur, dy / longueur

    def abscisse(p):
        return (p[0] - de1[0]) * ux + (p[1] - de1[1]) * uy
    i1 = sorted(((abscisse(p), tuple(p)) for p in (de1, a1)))
    i2 = sorted(((abscisse(p), tuple(p)) for p in (de2, a2)))
    if i2[0][0] >= i1[1][0]:             # le second mur est après le premier
        p, q = i1[1][1], i2[0][1]
    elif i1[0][0] >= i2[1][0]:           # le second mur est avant le premier
        p, q = i1[0][1], i2[1][1]
    else:
        return None
    largeur = math.hypot(q[0] - p[0], q[1] - p[1])
    return (largeur, p, q) if largeur > 0 else None


def est_passage(de1, a1, de2, a2, tolerance=1e-6):
    """Vrai si les deux murs sont alignés et laissent entre eux un trou de PASSAGE_MIN à PASSAGE_MAX."""
    if not murs_alignes(de1, a1, de2, a2):
        return False
    trou = trou_entre(de1, a1, de2, a2)
    return trou is not None and PASSAGE_MIN - tolerance <= trou[0] <= PASSAGE_MAX + tolerance
