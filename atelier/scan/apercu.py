"""Aperçu en direct d'un scan : la carte qui se construit, vue de dessus et en 3D (sections 9.2 et 12.5).

Le nœud écoute directement le nuage et l'odométrie de la session (pas le bag en cours
d'écriture). Il accumule les points sur une grille de 5 cm (une case 3D compte le nombre de
nuages qui l'ont touchée) et la trajectoire du robot. Toutes les 2 s (PERIODE_APERCU), il réécrit
ensemble, chacun de façon atomique :
  - apercu.png : vue de dessus, même convention qu'une carte (ligne 0 = y maximal), fond gris
    205 (inconnu), obstacles vus en noir, trajectoire en bleu et robot en rouge ;
  - apercu.json : points décimés de la tranche 0,1–1,5 m au-dessus du sol estimé, trajectoire,
    dernière pose du robot et statistiques (format de la section 9.2) ;
  - apercu_nuage.bin et .json (vague 5, section 12.5) : le nuage en direct de l'écran de scan, toutes
    hauteurs, une case de 10 cm par point (APERCU_NUAGE_POINTS_MAX points au plus), z = hauteur
    au-dessus du plan du sol (atelier.lieu.nuage, source apercu) ;
puis il met à jour les statistiques de session.json (atelier.lieu.maj_session).

Le sol est un plan (atelier.scan.sol, RANSAC à graine fixe), recalculé toutes les PERIODE_SOL secondes
au plus quand le nuage a grandi : sur le vrai G1 il est incliné, et un seul niveau noircissait la
moitié de l'aperçu (le « damier »).

Repère : celui de l'odométrie. Un nuage déjà dans ce repère (même frame_id que l'odométrie, ou
odom, map, world, camera_init) est pris tel quel. Sinon, il est placé avec la pose du robot au
même instant et la position du capteur sur le robot : /tf_static, sinon le LiDAR du robot proxy.

Une colonne de 5 cm est un obstacle si au moins deux cases 3D de sa colonne sont dans la tranche,
comme dans la carte 2D finale (atelier.scan.carte2d), si au moins trois nuages l'ont touchée, et si
sa tache fait au moins 4 pixels : la plupart des points fantômes du LiDAR simulé (le long des
rayons, au bord des murs) ne s'affichent pas. Les piétons, eux, laissent une traînée dans
l'aperçu ; la carte 3D finale les retire.

Lancé par le processus de la session (g1-scan) :
    python -m atelier.scan.apercu --lieu L --session S --nuage /points --odom /odom [--arret-cmd-vel]
--arret-cmd-vel : publie une vitesse nulle sur /cmd_vel en s'arrêtant (robot simulé).
"""
import argparse
import json
import math
import signal
import sys
import time
from collections import deque
from pathlib import Path

import numpy as np

from atelier.lieu import (APERCU_NUAGE, APERCU_POINTS_MAX, APERCU_TRAJECTOIRE_MAX, FICHIERS_SESSION, PERIODE_APERCU,
                          ErreurLieu, dossier_session, ecrire_atomique, ecrire_nuage, entete_nuage, maj_session)
from atelier.lieu.nuage import APERCU_NUAGE_POINTS_MAX, GRILLE_APERCU
from atelier.lieu.scans import instant
from atelier.scan import sol as S

RESOLUTION = 0.05            # m, grille de l'accumulation et de l'image
RESOLUTION_Z = 0.05          # m, hauteur des cases 3D (comme la grille de la carte 3D)
RESOLUTION_GRANDE = 0.1      # m, si un côté de l'image dépasse COTE_MAX pixels
COTE_MAX = 2000              # pixels
TRANCHE = (0.1, 1.5)         # m au-dessus du sol, comme la carte 2D
CASES_MIN = 2                # cases 3D d'une colonne dans la tranche pour un obstacle (carte2d.POINTS_MIN)
IMPACTS_MIN = 3              # nuages qui touchent la colonne : un point fantôme isolé n'est pas un obstacle
AIRE_MIN = 4                 # pixels : une tache d'obstacles plus petite est du bruit (carte2d.AIRE_MIN)
POINTS_SOL_MIN = 500         # cases 3D avant d'estimer le sol
PERIODE_SOL = 10.0           # s : le plan du sol est recalculé au plus aussi souvent…
CROISSANCE_SOL = 1.2         # … et seulement si le nombre de cases a grandi de 20 %
PAS_TRAJECTOIRE = 0.05       # m : un point de trajectoire au moins tous les 0,1 m
DEPLACEMENT_MIN = 0.02       # m : en dessous, un déplacement de l'odométrie est du bruit
ECART_ODOM_MAX = 0.5         # s : au-delà, on prend la dernière pose connue
CAPTEUR_PROXY = (-0.004, 0.0, 1.245)   # LiDAR du robot proxy g1_proxy (model.sdf), si /tf_static manque
REPERES_MONDE = ("odom", "map", "world", "camera_init")

GRIS, NOIR = 205, 0
BLEU = (255, 120, 0)         # BGR (OpenCV) : la trajectoire
ROUGE = (40, 40, 230)        # BGR : le robot

# Clés des cases 3D : i et j sur 21 bits, k sur 12 bits, dans un entier de 64 bits
_DEC = 1 << 20
_DEC_Z = 1 << 11
_MASQUE_J = (1 << 21) - 1
_MASQUE_K = (1 << 12) - 1


def cles_cases(points, resolution=RESOLUTION, resolution_z=RESOLUTION_Z):
    """Points (N, 3) en mètres → clés uniques des cases 3D qui les contiennent (resolution × resolution
    × resolution_z mètres)."""
    points = np.asarray(points, dtype=float).reshape(-1, 3)
    if len(points) == 0:
        return np.zeros(0, dtype=np.int64)
    ijk = np.floor(points / (resolution, resolution, resolution_z)).astype(np.int64)
    ok = (np.abs(ijk[:, 0]) < _DEC) & (np.abs(ijk[:, 1]) < _DEC) & (np.abs(ijk[:, 2]) < _DEC_Z)
    ijk = ijk[ok]
    return np.unique(((ijk[:, 0] + _DEC) << 33) | ((ijk[:, 1] + _DEC) << 12) | (ijk[:, 2] + _DEC_Z))


def indices_cases(cles):
    """Clés → tableaux (i, j, k) des cases 3D."""
    cles = np.asarray(cles, dtype=np.int64)
    return (cles >> 33) - _DEC, ((cles >> 12) & _MASQUE_J) - _DEC, (cles & _MASQUE_K) - _DEC_Z


def _cap(qx, qy, qz, qw):
    return math.atan2(2 * (qw * qz + qx * qy), 1 - 2 * (qy * qy + qz * qz))


def position_lidar_proxy():
    """Position (x, y, z) du LiDAR du robot proxy sur base_link, lue dans le model.sdf de g1_sim
    (capteur « lidar ») ; CAPTEUR_PROXY si le fichier manque ou est illisible."""
    import xml.etree.ElementTree as ET
    from atelier import RACINE
    chemin = RACINE / "ws" / "src" / "g1_sim" / "models" / "g1_proxy" / "model.sdf"
    try:
        capteur = ET.parse(chemin).getroot().find(".//sensor[@name='lidar']")
        valeurs = [float(v) for v in capteur.find("pose").text.split()]
        return tuple(valeurs[:3])
    except (OSError, ET.ParseError, AttributeError, ValueError):
        return CAPTEUR_PROXY


def _sans_petites_taches(colonnes, aire_min=AIRE_MIN):
    """Pour des colonnes (clés (i, j) triées), vrai si elles sont dans une tache de 8-voisins d'au
    moins aire_min colonnes (ouverture par aire, comme atelier.scan.carte2d)."""
    import cv2
    if len(colonnes) == 0 or aire_min <= 1:
        return np.ones(len(colonnes), dtype=bool)
    i, j = (colonnes >> 22) - _DEC, (colonnes & ((1 << 22) - 1)) - _DEC
    i0, j0 = i.min(), j.min()
    masque = np.zeros((int(j.max() - j0) + 1, int(i.max() - i0) + 1), dtype=np.uint8)
    masque[j - j0, i - i0] = 1
    _, etiquettes, stats, _ = cv2.connectedComponentsWithStats(masque, connectivity=8)
    return stats[etiquettes[j - j0, i - i0], cv2.CC_STAT_AREA] >= aire_min


class Accumulateur:
    """Ce que le scan a vu jusqu'ici : cases 3D occupées, trajectoire, statistiques. Sans ROS."""

    def __init__(self, resolution=RESOLUTION, resolution_z=RESOLUTION_Z):
        self.resolution, self.resolution_z = resolution, resolution_z
        self.cles = np.zeros(0, dtype=np.int64)          # cases 3D vues (triées, uniques)
        self.impacts = np.zeros(0, dtype=np.int64)       # nombre de nuages qui ont touché chaque case
        self._attente = []
        self.trajectoire = []            # [x, y, theta]
        self.robot = None                # dernière pose (x, y, theta)
        self.points = 0                  # points reçus (avant réduction)
        self.nuages = 0
        self.distance = 0.0
        self._dernier_compte = None      # dernière position comptée dans la distance
        self.debut = time.monotonic()
        self._plan, self._cases_du_plan, self._instant_plan = None, 0, 0.0

    # ------------------------------------------------ entrées
    def ajouter_nuage(self, points_monde):
        """Un nuage déjà placé dans le repère de l'odométrie (N, 3)."""
        points_monde = np.asarray(points_monde, dtype=float).reshape(-1, 3)
        self.nuages += 1
        self.points += len(points_monde)
        if len(points_monde):
            self._attente.append(cles_cases(points_monde, self.resolution, self.resolution_z))

    def ajouter_pose(self, x, y, theta):
        self.robot = (float(x), float(y), float(theta))
        if self._dernier_compte is None:
            self._dernier_compte = (x, y)
        else:
            d = math.hypot(x - self._dernier_compte[0], y - self._dernier_compte[1])
            if d >= DEPLACEMENT_MIN:
                self.distance += d
                self._dernier_compte = (x, y)
        if (not self.trajectoire
                or math.hypot(x - self.trajectoire[-1][0], y - self.trajectoire[-1][1]) >= PAS_TRAJECTOIRE):
            self.trajectoire.append([float(x), float(y), float(theta)])

    def _fusionner(self):
        if self._attente:
            cles, inverse = np.unique(np.concatenate([self.cles] + self._attente), return_inverse=True)
            poids = np.concatenate([self.impacts] + [np.ones(len(a), dtype=np.int64) for a in self._attente])
            self.cles, self.impacts = cles, np.bincount(inverse, weights=poids).astype(np.int64)
            self._attente = []

    # ------------------------------------------------ calculs
    def statistiques(self):
        return {"duree_s": round(time.monotonic() - self.debut, 1), "points": int(self.points),
                "distance_m": round(self.distance, 2), "nuages": int(self.nuages)}

    def plan_sol(self):
        """Plan du sol [a, b, c] (z = a·x + b·y + c) des cases 3D, ou None tant qu'il y en a trop peu.
        Recalculé au plus toutes les PERIODE_SOL secondes, quand le nuage a grandi de 20 %."""
        self._fusionner()
        n = len(self.cles)
        if n < POINTS_SOL_MIN:
            return None
        maintenant = time.monotonic()
        if (self._plan is None or (n >= CROISSANCE_SOL * self._cases_du_plan
                                   and maintenant - self._instant_plan >= PERIODE_SOL)):
            i, j, k = indices_cases(self.cles)
            centres = np.column_stack([(i + 0.5) * self.resolution, (j + 0.5) * self.resolution,
                                       (k + 0.5) * self.resolution_z])
            self._plan = S.trouver_sol(centres)["plan"]
            self._cases_du_plan, self._instant_plan = n, maintenant
        return self._plan

    def sol(self):
        """Hauteur du sol au milieu de ce qui a été vu (pour apercu.json), ou None."""
        plan = self.plan_sol()
        if plan is None:
            return None
        i, j, _ = indices_cases(self.cles)
        return float(S.niveau(plan, (np.median(i) + 0.5) * self.resolution, (np.median(j) + 0.5) * self.resolution))

    def tranche(self, plan, obstacles_seulement=False):
        """(i, j, k) des cases 3D de la tranche 0,1–1,5 m au-dessus du plan du sol (plan None : rien) ;
        obstacles_seulement : seulement celles des colonnes retenues comme obstacles. plan : [a, b, c],
        ou un niveau (nombre) pour un sol horizontal."""
        self._fusionner()
        vide = np.zeros(0, dtype=np.int64)
        if plan is None or len(self.cles) == 0:
            return vide, vide, vide
        if np.ndim(plan) == 0:
            plan = S.plan_plat(plan)
        i, j, k = indices_cases(self.cles)
        # Le bas de la case doit être dans la tranche : une case qui contient le sol n'y entre pas
        bas = k * self.resolution_z - S.niveau(plan, (i + 0.5) * self.resolution, (j + 0.5) * self.resolution)
        dans = (bas >= TRANCHE[0] - 1e-9) & (bas + 0.5 * self.resolution_z <= TRANCHE[1])
        i, j, k, impacts = i[dans], j[dans], k[dans], self.impacts[dans]
        if obstacles_seulement and len(i):
            colonnes, inverse, compte = np.unique(((i + _DEC) << 22) | (j + _DEC), return_inverse=True,
                                                  return_counts=True)
            total = np.bincount(inverse, weights=impacts)
            retenues = (compte >= CASES_MIN) & (total >= IMPACTS_MIN)
            retenues[retenues] = _sans_petites_taches(colonnes[retenues])
            garde = retenues[inverse]
            i, j, k = i[garde], j[garde], k[garde]
        return i, j, k

    def obstacles(self, plan):
        """(i, j) des colonnes de 5 cm retenues comme obstacles : au moins CASES_MIN cases 3D dans la
        tranche, touchées en tout par au moins IMPACTS_MIN nuages, dans une tache d'au moins AIRE_MIN
        pixels. Un mur est vu par des centaines de nuages ; un point fantôme du LiDAR simulé (au bord
        d'un mur, le long d'un rayon) par quelques-uns, et en petits morceaux. plan : le plan du sol."""
        i, j, _ = self.tranche(plan, obstacles_seulement=True)
        if len(i) == 0:
            return i, j
        colonnes = np.unique(((i + _DEC) << 22) | (j + _DEC))
        return (colonnes >> 22) - _DEC, (colonnes & ((1 << 22) - 1)) - _DEC

    # ------------------------------------------------ sorties
    def vue(self):
        """Vue de dessus : (image BGR (hauteur, largeur, 3) uint8, infos) ; infos : resolution,
        bornes {xmin, ymin, xmax, ymax}, largeur, hauteur, sol."""
        import cv2
        plan = self.plan_sol()
        sol = self.sol()
        i, j = self.obstacles(plan)
        res = self.resolution
        xs = [self.trajectoire[n][0] for n in range(len(self.trajectoire))]
        ys = [self.trajectoire[n][1] for n in range(len(self.trajectoire))]
        if self.robot is not None:
            xs.append(self.robot[0])
            ys.append(self.robot[1])
        ti = np.floor(np.asarray(xs) / res).astype(np.int64) if xs else np.zeros(0, dtype=np.int64)
        tj = np.floor(np.asarray(ys) / res).astype(np.int64) if ys else np.zeros(0, dtype=np.int64)
        tout_i, tout_j = np.concatenate([i, ti]), np.concatenate([j, tj])
        if len(tout_i) == 0:                         # rien vu : 10 × 10 m autour de l'origine
            tout_i = np.array([-int(5 / res), int(5 / res)])
            tout_j = tout_i.copy()
        imin, imax = int(tout_i.min()) - 1, int(tout_i.max()) + 1
        jmin, jmax = int(tout_j.min()) - 1, int(tout_j.max()) + 1
        if max(imax - imin + 1, jmax - jmin + 1) > COTE_MAX:   # grande image : cases de 10 cm
            facteur = int(round(RESOLUTION_GRANDE / res))
            res = res * facteur
            i, j = i // facteur, j // facteur
            imin, imax, jmin, jmax = imin // facteur, imax // facteur, jmin // facteur, jmax // facteur
        largeur, hauteur = imax - imin + 1, jmax - jmin + 1
        image = np.full((hauteur, largeur, 3), GRIS, dtype=np.uint8)
        image[jmax - j, i - imin] = NOIR
        xmin, ymax = imin * res, (jmax + 1) * res

        def pixel(x, y):
            return int(math.floor((x - xmin) / res)), int(math.floor((ymax - y) / res))
        if len(self.trajectoire) > 1:
            ligne = np.array([pixel(x, y) for x, y, _ in self.trajectoire], dtype=np.int32)
            cv2.polylines(image, [ligne.reshape(-1, 1, 2)], False, BLEU, 1, lineType=cv2.LINE_8)
        if self.robot is not None:
            x, y, theta = self.robot
            c = pixel(x, y)
            rayon = max(2, int(round(0.25 / res)))
            cv2.circle(image, c, rayon, ROUGE, -1, lineType=cv2.LINE_AA)
            bout = pixel(x + 2.2 * rayon * res * math.cos(theta), y + 2.2 * rayon * res * math.sin(theta))
            cv2.line(image, c, bout, ROUGE, 1, lineType=cv2.LINE_AA)
        infos = {"resolution": round(res, 4),
                 "bornes": {"xmin": round(xmin, 3), "ymin": round(jmin * res, 3),
                            "xmax": round((imax + 1) * res, 3), "ymax": round(ymax, 3)},
                 "largeur": int(largeur), "hauteur": int(hauteur), "sol": None if sol is None else round(sol, 3),
                 "plan_sol": None if plan is None else [round(float(v), 6) for v in plan]}
        return image, infos

    def donnees_json(self, session, infos, repere="odom", graine=0):
        """Contenu de apercu.json (section 9.2), plus plan_sol (vague 5)."""
        i, j, k = self.tranche(infos.get("plan_sol", infos["sol"]), obstacles_seulement=True)
        points = np.column_stack([(i + 0.5) * self.resolution, (j + 0.5) * self.resolution,
                                  (k + 0.5) * self.resolution_z]) if len(i) else np.zeros((0, 3))
        if len(points) > APERCU_POINTS_MAX:
            choix = np.random.default_rng(graine).choice(len(points), APERCU_POINTS_MAX, replace=False)
            points = points[np.sort(choix)]
        trajectoire = self.trajectoire
        if len(trajectoire) > APERCU_TRAJECTOIRE_MAX:
            garde = np.linspace(0, len(trajectoire) - 1, APERCU_TRAJECTOIRE_MAX).astype(int)
            trajectoire = [trajectoire[n] for n in garde]
        robot = None
        if self.robot is not None:
            robot = {"x": round(self.robot[0], 3), "y": round(self.robot[1], 3), "theta": round(self.robot[2], 3)}
        return {"version": 1, "session": session, "maj": instant(), "repere": repere,
                "resolution": infos["resolution"], "bornes": infos["bornes"],
                "largeur": infos["largeur"], "hauteur": infos["hauteur"], "sol": infos["sol"],
                "plan_sol": infos.get("plan_sol"),
                "points": np.round(points, 2).tolist(),
                "trajectoire": [[round(x, 3), round(y, 3), round(t, 3)] for x, y, t in trajectoire],
                "robot": robot, "statistiques": self.statistiques()}

    def nuage_apercu(self, grille=GRILLE_APERCU, points_max=APERCU_NUAGE_POINTS_MAX, graine=0):
        """Nuage en direct de l'écran de scan : (points float32 (n, 3), plan du sol). Une case de « grille »
        mètres par point (centre), toutes hauteurs, z = hauteur au-dessus du plan du sol (sans plan : au-dessus
        du 1er centile) ; au plus points_max points, tirés au hasard à graine fixe."""
        self._fusionner()
        if len(self.cles) == 0:
            return np.zeros((0, 3), dtype=np.float32), None
        i, j, k = indices_cases(self.cles)
        f = max(1, int(round(grille / self.resolution)))
        fz = max(1, int(round(grille / self.resolution_z)))
        gros = np.unique(np.column_stack([i // f, j // f, k // fz]), axis=0)
        points = np.column_stack([(gros[:, 0] + 0.5) * f * self.resolution, (gros[:, 1] + 0.5) * f * self.resolution,
                                  (gros[:, 2] + 0.5) * fz * self.resolution_z])
        plan = self.plan_sol()
        if plan is None:
            plan = S.plan_plat(float(np.percentile(points[:, 2], 1.0)))
        points[:, 2] = S.hauteurs(points, plan)
        if len(points) > points_max:
            choix = np.random.default_rng(graine).choice(len(points), points_max, replace=False)
            points = points[np.sort(choix)]
        return points.astype(np.float32), plan

    def ecrire(self, dossier, session, repere="odom"):
        """Réécrit apercu.png, apercu.json puis apercu_nuage (.bin et .json) dans le dossier de la session.
        Renvoie le JSON de apercu.json."""
        import cv2
        image, infos = self.vue()
        ok, png = cv2.imencode(".png", image)
        if not ok:
            raise RuntimeError("encodage PNG impossible")
        donnees = self.donnees_json(session, infos, repere)
        dossier = Path(dossier)
        ecrire_atomique(dossier / FICHIERS_SESSION["apercu_png"], png.tobytes())
        ecrire_atomique(dossier / FICHIERS_SESSION["apercu_json"], json.dumps(donnees, ensure_ascii=False) + "\n")
        points, plan = self.nuage_apercu()
        sol = plan or [0.0, 0.0, 0.0]
        entete = entete_nuage(points, GRILLE_APERCU, sol, "apercu", session=session, statistiques=self.statistiques(),
                              robot=donnees["robot"])
        ecrire_nuage(dossier / APERCU_NUAGE, points, entete)
        return donnees


# ---------------------------------------------------------------- placement des nuages

class Placement:
    """Place un nuage dans le repère de l'odométrie : poses de l'odométrie (tampon), /tf_static.

    Une seule base de temps (bogue n° 1 du scan du 27/10) : un nuage à horodatage nul (vrai G1) est
    apparié à la pose reçue au même moment (instant de réception), pas à son horodatage."""

    def __init__(self, capteur=None):
        self.poses = deque(maxlen=400)       # (horodatage, instant de réception, matrice 4 × 4 robot → odom)
        self.repere_odom = None
        self.repere_robot = None
        self.liens = {}                      # /tf_static : enfant → (parent, matrice)
        self.capteur_defaut = capteur or position_lidar_proxy()
        self.source_capteur = None

    def ajouter_odom(self, t, position, quaternion, repere, repere_robot, reception=None):
        from atelier.scan.carte3d import transformation
        self.poses.append((t, time.time() if reception is None else reception, transformation(position, quaternion)))
        self.repere_odom, self.repere_robot = repere.lstrip("/"), (repere_robot or "base_link").lstrip("/")

    def ajouter_tf(self, enfant, parent, matrice):
        self.liens[enfant.lstrip("/")] = (parent.lstrip("/"), matrice)

    def pose(self, t, reception=None):
        """Pose du robot la plus proche de l'instant t (horodatage), ou de l'instant de réception si t est
        nul ; la dernière si t est loin de tout."""
        if not self.poses:
            return None
        if t <= 0 and reception is not None:
            meilleur = min(self.poses, key=lambda p: abs(p[1] - reception))
            return meilleur[2]
        meilleur = min(self.poses, key=lambda p: abs(p[0] - t))
        return meilleur[2] if abs(meilleur[0] - t) <= ECART_ODOM_MAX else self.poses[-1][2]

    def deja_dans_le_monde(self, repere):
        repere = repere.lstrip("/")
        return repere in REPERES_MONDE or (self.repere_odom is not None and repere == self.repere_odom)

    def placer(self, points, repere, t, reception=None):
        """Points du nuage (N, 3) → repère de l'odométrie, ou None si la pose est inconnue."""
        if self.deja_dans_le_monde(repere):
            return points
        pose = self.pose(t, reception)
        if pose is None:
            return None
        from atelier.scan.carte3d import position_capteur
        capteur, self.source_capteur = position_capteur(self.liens, repere, self.repere_robot, self.capteur_defaut)
        m = pose @ capteur
        # Calcul terme à terme, sans produit matriciel : numpy n'appelle pas OpenBLAS et ses fils
        x, y, z = points[:, 0], points[:, 1], points[:, 2]
        return np.column_stack([m[0, 0] * x + m[0, 1] * y + m[0, 2] * z + m[0, 3],
                                m[1, 0] * x + m[1, 1] * y + m[1, 2] * z + m[1, 3],
                                m[2, 0] * x + m[2, 1] * y + m[2, 2] * z + m[2, 3]])


# ---------------------------------------------------------------- le nœud ROS 2

def _instant(entete):
    return entete.stamp.sec + entete.stamp.nanosec * 1e-9


def principal(argv=None):
    p = argparse.ArgumentParser(prog="apercu", description="Aperçu en direct d'une session de scan.")
    p.add_argument("--lieu", required=True)
    p.add_argument("--session", required=True)
    p.add_argument("--nuage", default="/points")
    p.add_argument("--odom", default="/odom")
    p.add_argument("--periode", type=float, default=PERIODE_APERCU)
    p.add_argument("--arret-cmd-vel", action="store_true", help="vitesse nulle sur /cmd_vel à l'arrêt")
    args = p.parse_args(argv)

    import rclpy
    from geometry_msgs.msg import Twist
    from nav_msgs.msg import Odometry
    from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy, qos_profile_sensor_data
    from rclpy.signals import SignalHandlerOptions
    from sensor_msgs.msg import PointCloud2
    from tf2_msgs.msg import TFMessage

    from atelier.scan.carte3d import ErreurCarte3d, points_du_nuage, transformation

    dossier = dossier_session(args.lieu, args.session)
    accu, placement = Accumulateur(), Placement()
    arret = []
    signal.signal(signal.SIGINT, lambda *_: arret.append(1))
    signal.signal(signal.SIGTERM, lambda *_: arret.append(1))
    rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
    noeud = rclpy.create_node("g1_scan_apercu")
    sans_pose = [0]

    def sur_odom(msg):
        p, q = msg.pose.pose.position, msg.pose.pose.orientation
        placement.ajouter_odom(_instant(msg.header), (p.x, p.y, p.z), (q.x, q.y, q.z, q.w),
                               msg.header.frame_id, msg.child_frame_id, reception=time.time())
        accu.ajouter_pose(p.x, p.y, _cap(q.x, q.y, q.z, q.w))

    def sur_nuage(msg):
        try:
            points = points_du_nuage(msg)
        except ErreurCarte3d:
            return
        monde = placement.placer(points, msg.header.frame_id, _instant(msg.header), reception=time.time())
        if monde is None:
            sans_pose[0] += 1            # pas encore d'odométrie : compté, mais pas placé
            accu.nuages += 1
            accu.points += len(points)
            return
        accu.ajouter_nuage(monde)

    def sur_tf(msg):
        for tf in msg.transforms:
            t, q = tf.transform.translation, tf.transform.rotation
            placement.ajouter_tf(tf.child_frame_id, tf.header.frame_id,
                                 transformation((t.x, t.y, t.z), (q.x, q.y, q.z, q.w)))

    qos_statique = QoSProfile(depth=100, durability=DurabilityPolicy.TRANSIENT_LOCAL,
                              reliability=ReliabilityPolicy.RELIABLE)
    noeud.create_subscription(Odometry, args.odom, sur_odom, qos_profile_sensor_data)
    noeud.create_subscription(PointCloud2, args.nuage, sur_nuage, qos_profile_sensor_data)
    noeud.create_subscription(TFMessage, "/tf_static", sur_tf, qos_statique)
    pub_cmd = noeud.create_publisher(Twist, "/cmd_vel", 10) if args.arret_cmd_vel else None

    def ecrire():
        try:
            accu.ecrire(dossier, args.session, placement.repere_odom or "odom")
        except Exception as e:          # un aperçu raté ne doit pas arrêter le scan
            print(f"Aperçu non écrit : {e}", flush=True)
        try:
            maj_session(args.lieu, args.session, statistiques=accu.statistiques())
        except ErreurLieu as e:
            print(f"Statistiques non écrites dans session.json : {e}", flush=True)

    print(f"Aperçu : écoute de {args.nuage} et {args.odom}, écrit toutes les {args.periode:g} s dans {dossier}",
          flush=True)
    prochaine = time.monotonic() + args.periode
    annonce = False
    try:
        while not arret and rclpy.ok():
            rclpy.spin_once(noeud, timeout_sec=0.1)
            if time.monotonic() >= prochaine:
                prochaine = time.monotonic() + args.periode
                ecrire()
                if not annonce and accu.nuages:
                    annonce = True
                    print(f"Premiers nuages reçus ; capteur : {placement.source_capteur or 'repère du monde'}",
                          flush=True)
    finally:
        if pub_cmd is not None:
            for _ in range(5):          # VelocityControl garde la dernière consigne
                pub_cmd.publish(Twist())
                time.sleep(0.05)
        ecrire()
        print(f"Aperçu arrêté : {accu.nuages} nuages, {accu.points} points, {accu.distance:.1f} m parcourus"
              + (f" ({sans_pose[0]} nuages reçus avant l'odométrie)" if sans_pose[0] else ""), flush=True)
        noeud.destroy_node()
        rclpy.try_shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(principal())
