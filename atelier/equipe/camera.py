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


def message_visiteurs(temps, personnes):
    """Message complet de /visiteurs/detectes. temps : horodatage ROS des mesures, en secondes.
    personnes : dicts {id, x, y, confiance?, regarde_robot?, …} dans base_link."""
    return {"version": 1, "source": "camera", "temps": round(max(float(temps), 0.0), 3),
            "personnes": [personne(p["id"], **{k: v for k, v in p.items() if k != "id"}) for p in personnes][:100]}


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


__all__ = ["CHAMP_DEFAUT_DEG", "DISTANCE_DEFAUT_M", "dans_le_champ", "message_visiteurs", "personne",
           "vers_base_link", "visibles_depuis_pietons"]
