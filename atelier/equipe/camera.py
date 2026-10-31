"""La caméra des visiteurs (vague 4, section 11.6 du plan), sans ROS : ce que voit une caméra
placée comme dans camera.yaml, et le message de /visiteurs/detectes (schéma personnes).

Sert à la fausse caméra du paquet g1_equipe (essais sans la See3CAM : elle « voit » les piétons de
Gazebo, ou une personne posée à la main) et montre à l'équipe le format attendu de son nœud :

    message_visiteurs(temps, [{"id": 1, "x": 1.5, "y": 0.2, "confiance": 0.9, "regarde_robot": True}])
    → {"version": 1, "source": "camera", "temps": 12.3, "personnes": [{"id": 1, "x": 1.5, "y": 0.2,
       "distance_m": 1.513, "angle_rad": 0.1326, "confiance": 0.9, "derriere": False, "regarde_robot": True}]}

Positions dans base_link (x vers l'avant du robot, y à sa gauche), en mètres ; angle depuis
l'avant, sens inverse des aiguilles d'une montre. La caméra est posée par camera.yaml
(position x, y, z, lacet dans base_link) ; son champ horizontal est centré sur son lacet.

Vague 5 (section 12.7 du plan) : des pixels aux mètres pour g1-visiteurs (YOLO pose sur l'image de
la See3CAM), en fonctions pures testées sans YOLO : focale_px, angle_image, distance_personne (par
la taille de la personne, du buste ou des épaules), position_dans_base_link, regarde_robot et
personnes_depuis_detections ; message_visiteurs ajoute l'image analysée (« image ») et les cadres
(« boite », en pixels).
"""
import math

CHAMP_DEFAUT_DEG = 90.0
DISTANCE_DEFAUT_M = 4.0


def _reglages(camera):
    """(x, y, lacet, demi-champ en rad, distance max) depuis le contenu de camera.yaml (ou None)."""
    cam = (camera or {}).get("camera") or {}
    det = (camera or {}).get("detection") or {}
    pos = cam.get("position") or {}
    champ = cam.get("champ_horizontal_deg") or CHAMP_DEFAUT_DEG
    return (float(pos.get("x", 0.0)), float(pos.get("y", 0.0)), float(pos.get("lacet", 0.0)),
            math.radians(min(champ, 359.0)) / 2.0, float(det.get("distance_max_m") or DISTANCE_DEFAUT_M))


def dans_le_champ(x, y, camera=None):
    """Vrai si le point (x, y) de base_link est dans le champ horizontal de la caméra et à
    distance_max_m au plus d'elle."""
    cx, cy, lacet, demi, portee = _reglages(camera)
    dx, dy = x - cx, y - cy
    distance = math.hypot(dx, dy)
    if distance > portee or distance < 1e-6:
        return False
    ecart = (math.atan2(dy, dx) - lacet + math.pi) % (2 * math.pi) - math.pi
    return abs(ecart) <= demi


def vers_base_link(x_map, y_map, robot):
    """Point de la carte (map) → base_link, robot = (x, y, theta) dans map."""
    rx, ry, theta = robot
    dx, dy = x_map - rx, y_map - ry
    c, s = math.cos(theta), math.sin(theta)
    return c * dx + s * dy, -s * dx + c * dy


def personne(ident, x, y, confiance=0.9, regarde_robot=None, **autres):
    """Une personne de /visiteurs/detectes (schéma personnes), position dans base_link."""
    p = {"id": int(ident), "x": round(float(x), 3), "y": round(float(y), 3),
         "distance_m": round(math.hypot(x, y), 3), "angle_rad": round(math.atan2(y, x), 4),
         "confiance": round(min(max(float(confiance), 0.0), 1.0), 3), "derriere": abs(math.atan2(y, x)) > math.pi / 2}
    if regarde_robot is not None:
        p["regarde_robot"] = bool(regarde_robot)
    p.update({k: v for k, v in autres.items() if v is not None})
    return p


def message_visiteurs(temps, personnes, image=None):
    """Message complet de /visiteurs/detectes. temps : horodatage ROS des mesures, en secondes.
    personnes : dicts {id, x, y, confiance?, regarde_robot?, boite?, …} dans base_link.
    image (vague 5, facultatif) : {largeur, hauteur, numero?, sujet?} de l'image analysée, pour
    placer les cadres « boite » (en pixels de cette image)."""
    message = {"version": 1, "source": "camera", "temps": round(max(float(temps), 0.0), 3),
               "personnes": [personne(p["id"], **{k: v for k, v in p.items() if k != "id"})
                             for p in personnes][:100]}
    if image:
        message["image"] = {k: v for k, v in image.items() if v is not None}
    return message


def visibles_depuis_pietons(pietons, robot, camera=None, confiance=0.9):
    """Personnes de /visiteurs/detectes tirées des piétons de Gazebo (/pietons/etat : positions dans
    map) et de la pose du robot (x, y, theta dans map) : ceux que la caméra verrait. L'id de suivi
    est le rang du piéton dans la liste (stable tant que le monde ne change pas) ; un piéton qui
    marche vers le robot (ou qui est arrêté) le regarde."""
    vus = []
    for rang, p in enumerate(pietons or []):
        try:
            xm, ym = float(p["x"]), float(p["y"])
        except (KeyError, TypeError, ValueError):
            continue
        x, y = vers_base_link(xm, ym, robot)
        if not dans_le_champ(x, y, camera):
            continue
        vx, vy = float(p.get("vx") or 0.0), float(p.get("vy") or 0.0)
        vers_robot = (robot[0] - xm) * vx + (robot[1] - ym) * vy
        vus.append({"id": rang, "x": x, "y": y, "confiance": confiance,
                    "regarde_robot": vers_robot >= 0.0 or math.hypot(vx, vy) < 0.05,
                    "x_map": round(xm, 3), "y_map": round(ym, 3), "pieton": p.get("id")})
    return vus


# ---------------------------------------------------------------- vague 5 : des pixels aux mètres

# Les distances d'une personne vue par la See3CAM (section 12.7 du plan), sans ROS ni YOLO :
# g1-visiteurs (outils/visiteurs.py) les applique à chaque personne détectée par YOLO pose.
# Caméra sténopé : un objet de hauteur H à la profondeur Z fait f·H/Z pixels (f : focale en pixels,
# la même en largeur et en hauteur). Points clés : les 17 de COCO (YOLO pose), [x, y, confiance].
TAILLE_PERSONNE_M = 1.70     # personne debout, du haut de la tête aux chevilles (detection.taille_personne_m)
BUSTE_M = 0.52               # milieu des épaules → milieu des hanches, adulte
EPAULES_M = 0.40             # d'une épaule à l'autre, adulte vu de face
SEUIL_POINT = 0.5            # confiance minimale d'un point clé
MARGE_BORD_PX = 2.0          # cadre qui touche le bord de l'image : la personne est coupée
ID_SANS_SUIVI = 100000       # personnes pas encore suivies (première image) : 100000 + rang
(NEZ, OEIL_G, OEIL_D, OREILLE_G, OREILLE_D, EPAULE_G, EPAULE_D, COUDE_G, COUDE_D, POIGNET_G, POIGNET_D,
 HANCHE_G, HANCHE_D, GENOU_G, GENOU_D, CHEVILLE_G, CHEVILLE_D) = range(17)
METHODES_DISTANCE = ("taille", "buste", "epaules", "boite")


def focale_px(largeur, champ_deg=CHAMP_DEFAUT_DEG):
    """Focale en pixels d'une image de « largeur » pixels qui voit « champ_deg » degrés de large :
    (largeur / 2) / tan(champ / 2). 640 pixels et 90° : 320."""
    champ = math.radians(min(max(float(champ_deg), 1.0), 179.0))
    return (float(largeur) / 2.0) / math.tan(champ / 2.0)


def angle_image(u, largeur, focale):
    """Direction horizontale (rad) de la colonne u de l'image, depuis l'axe de la caméra : positive
    vers la gauche (sens trigonométrique, comme base_link)."""
    return math.atan2(float(largeur) / 2.0 - float(u), float(focale))


def _point(points, i, seuil):
    """(x, y) du point clé i s'il est assez sûr, sinon None."""
    if points is None or i >= len(points):
        return None
    p = points[i]
    if len(p) < 2:
        return None
    if len(p) >= 3 and p[2] is not None and float(p[2]) < seuil:
        return None
    if p[0] is None or p[1] is None or (float(p[0]) <= 0.0 and float(p[1]) <= 0.0):
        return None          # YOLO met (0, 0) pour un point qu'il ne voit pas
    return float(p[0]), float(p[1])


def _milieu(a, b):
    return None if a is None or b is None else ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)


def distance_personne(boite, points, focale, taille_m=TAILLE_PERSONNE_M, correction=1.0,
                      seuil=SEUIL_POINT, hauteur_image=None):
    """Profondeur (m, le long de l'axe de la caméra) d'une personne, et la méthode employée.

    boite : [x_min, y_min, x_max, y_max] en pixels ; points : les 17 points clés [x, y, confiance]
    (ou None). Dans l'ordre :
      « taille »   la tête (nez ou un œil) et une cheville visibles, cadre entier : sa hauteur ;
      « buste »    épaules et hanches visibles : milieu des épaules → milieu des hanches (0,52 m) ;
      « epaules »  les deux épaules : leur écart (0,40 m ; trop loin si la personne est de profil) ;
      « boite »    sinon, la hauteur du cadre, comme une personne entière (trop loin si elle est coupée).
    correction : facteur mesuré sur le robot (repères au sol à 1, 2, 3 et 4 m). Renvoie (None,
    None) pour un cadre vide."""
    x0, y0, x1, y1 = (float(v) for v in boite)
    hauteur_px = y1 - y0
    if hauteur_px <= 0 or x1 <= x0 or focale <= 0:
        return None, None
    tete = _point(points, NEZ, seuil) or _point(points, OEIL_G, seuil) or _point(points, OEIL_D, seuil)
    cheville = _point(points, CHEVILLE_G, seuil) or _point(points, CHEVILLE_D, seuil)
    coupee = y0 <= MARGE_BORD_PX or (hauteur_image is not None and y1 >= float(hauteur_image) - MARGE_BORD_PX)
    if tete is not None and cheville is not None and not coupee:
        return focale * float(taille_m) / hauteur_px * float(correction), "taille"
    epaules = (_point(points, EPAULE_G, seuil), _point(points, EPAULE_D, seuil))
    hanches = _milieu(_point(points, HANCHE_G, seuil), _point(points, HANCHE_D, seuil))
    haut = _milieu(*epaules)
    if haut is not None and hanches is not None:
        buste_px = math.hypot(hanches[0] - haut[0], hanches[1] - haut[1])
        if buste_px >= 4.0:
            return focale * BUSTE_M / buste_px * float(correction), "buste"
    if epaules[0] is not None and epaules[1] is not None:
        largeur_px = math.hypot(epaules[0][0] - epaules[1][0], epaules[0][1] - epaules[1][1])
        if largeur_px >= 4.0:
            return focale * EPAULES_M / largeur_px * float(correction), "epaules"
    return focale * float(taille_m) / hauteur_px * float(correction), "boite"


def position_dans_base_link(profondeur, angle, camera=None):
    """(x, y) dans base_link d'une personne vue à « profondeur » (m, le long de l'axe de la caméra)
    et dans la direction « angle » (rad, positif vers la gauche), la caméra étant placée comme dans
    camera.yaml (position x, y et lacet ; tangage et roulis négligés)."""
    cx, cy, lacet, _, _ = _reglages(camera)
    avant = float(profondeur)
    gauche = avant * math.tan(float(angle))
    c, s = math.cos(lacet), math.sin(lacet)
    return cx + c * avant - s * gauche, cy + s * avant + c * gauche


def regarde_robot(points, seuil=SEUIL_POINT):
    """Vrai si la personne fait face à la caméra : le nez et les deux yeux visibles, le nez entre
    les deux yeux ; faux si le nez est hors des yeux, ou si seule une oreille ou la nuque se voient ;
    None si on ne peut pas savoir (pas de points clés)."""
    if not points:
        return None
    nez = _point(points, NEZ, seuil)
    gauche, droit = _point(points, OEIL_G, seuil), _point(points, OEIL_D, seuil)
    if nez is None or gauche is None or droit is None:
        return False
    bas, haut = sorted((gauche[0], droit[0]))
    marge = 0.15 * (haut - bas)
    return haut - bas > 1.0 and bas + marge <= nez[0] <= haut - marge


def personnes_depuis_detections(detections, camera, largeur, hauteur):
    """Personnes de /visiteurs/detectes (pour message_visiteurs) tirées des détections de YOLO.

    detections : [{id (numéro de suivi ByteTrack, ou None), boite [x_min, y_min, x_max, y_max]
    (pixels de l'image analysée, largeur × hauteur), confiance, points (17 × [x, y, c]) ou None}].
    camera : contenu de camera.yaml (champ_horizontal_deg, position, detection : confiance_min,
    distance_max_m, taille_personne_m, correction_distance), ou None (défauts). Les personnes moins
    sûres que confiance_min, ou plus loin que distance_max_m, sont écartées. Chacune garde sa
    « boite » (bornée à l'image), la méthode de la distance et regarde_robot."""
    cam = (camera or {}).get("camera") or {}
    det = (camera or {}).get("detection") or {}
    focale = focale_px(largeur, cam.get("champ_horizontal_deg") or CHAMP_DEFAUT_DEG)
    confiance_min = float(det.get("confiance_min", 0.5))
    portee = float(det.get("distance_max_m") or DISTANCE_DEFAUT_M)
    taille = float(det.get("taille_personne_m") or TAILLE_PERSONNE_M)
    correction = float(det.get("correction_distance") or 1.0)
    personnes = []
    for rang, d in enumerate(detections or []):
        confiance = float(d.get("confiance") or 0.0)
        if confiance < confiance_min:
            continue
        x0, y0, x1, y1 = (float(v) for v in d["boite"])
        boite = [round(min(max(x0, 0.0), largeur), 1), round(min(max(y0, 0.0), hauteur), 1),
                 round(min(max(x1, 0.0), largeur), 1), round(min(max(y1, 0.0), hauteur), 1)]
        if not (boite[0] < boite[2] and boite[1] < boite[3]):
            continue
        points = d.get("points")
        profondeur, methode = distance_personne(boite, points, focale, taille, correction,
                                                hauteur_image=hauteur)
        if profondeur is None:
            continue
        angle = angle_image((boite[0] + boite[2]) / 2.0, largeur, focale)
        x, y = position_dans_base_link(profondeur, angle, camera)
        if math.hypot(x, y) > portee:
            continue
        ident = d.get("id")
        suivi = ident is not None and int(ident) >= 0
        p = {"id": int(ident) if suivi else ID_SANS_SUIVI + rang, "x": x, "y": y, "confiance": confiance,
             "regarde_robot": regarde_robot(points), "boite": boite, "methode_distance": methode}
        if not suivi:
            p["suivi"] = False
        personnes.append(p)
    return personnes


__all__ = ["BUSTE_M", "CHAMP_DEFAUT_DEG", "DISTANCE_DEFAUT_M", "EPAULES_M", "ID_SANS_SUIVI", "METHODES_DISTANCE",
           "TAILLE_PERSONNE_M", "angle_image", "dans_le_champ", "distance_personne", "focale_px",
           "message_visiteurs", "personne", "personnes_depuis_detections", "position_dans_base_link",
           "regarde_robot", "vers_base_link", "visibles_depuis_pietons"]
