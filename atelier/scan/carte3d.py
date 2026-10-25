"""Enregistrement d'un scan (ros2 bag) → nuage 3D .pcd, réduit à une grille de 5 cm.

L'enregistrement contient le nuage du LiDAR (sensor_msgs/PointCloud2) et l'odométrie
(nav_msgs/Odometry) : /points et /odom en simulation, /unitree/slam_mapping/points et
/unitree/slam_mapping/odom sur le vrai robot. Chaque nuage est replacé dans le repère de
l'odométrie (repère map), à la position du robot au même instant, puis tous les nuages sont
fusionnés et réduits (un point par case de 5 cm, avec Open3D).

Repère du nuage :
  - s'il est déjà celui de l'odométrie (ex. « odom », « map ») : utilisé tel quel ;
  - sinon, c'est celui du capteur : position du robot (odométrie) puis position du LiDAR sur
    le robot, lue dans /tf_static s'il a été enregistré, sinon --capteur (défaut : 0 0 1,2).

Les obstacles mobiles (piétons) sont retirés : une colonne de la carte que les rayons presque
horizontaux du LiDAR traversent bien plus souvent qu'ils ne s'y arrêtent n'est pas un mur.

Exemple :
    ros2 bag record -o ~/robot-g1/enregistrements/scan_rdc /points /odom /tf_static
    g1-carte-3d --lieu demo --etage rdc --enregistrement ~/robot-g1/enregistrements/scan_rdc
"""
import math
import os
from pathlib import Path

import numpy as np

SUJETS_NUAGE = ("/unitree/slam_mapping/points", "/points")
SUJETS_ODOM = ("/unitree/slam_mapping/odom", "/odom")
CAPTEUR_DEFAUT = (0.0, 0.0, 1.2)     # LiDAR du robot proxy : 1,2 m au-dessus de base_link
REPERES_MONDE = ("odom", "map", "world", "camera_init")
ECART_TEMPS_MAX = 0.25               # s, écart maximal entre un nuage et l'odométrie la plus proche

# Retrait des obstacles mobiles (voir Colonnes)
BANDE_RAYONS = 0.3                   # m, rayons à moins de 0,3 m de la hauteur du capteur
MARGE_AVANT_IMPACT = 0.25            # m, on ne compte pas la traversée juste avant l'impact
PASSAGES_MIN = 3
RAPPORT_MOBILE = 3.0                 # mobile si traversée plus de 3 fois plus souvent que touchée
UN_NUAGE_SUR = 2                     # pour aller plus vite, la traversée est comptée sur 1 nuage sur 2


class ErreurCarte3d(Exception):
    """Enregistrement illisible ou incomplet ; le message dit quoi corriger."""


# ---------------------------------------------------------------- petits calculs

def matrice_rotation(qx, qy, qz, qw):
    """Quaternion (x, y, z, w) → matrice de rotation 3 × 3."""
    n = math.sqrt(qx * qx + qy * qy + qz * qz + qw * qw) or 1.0
    x, y, z, w = qx / n, qy / n, qz / n, qw / n
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def transformation(translation, quaternion):
    """Matrice homogène 4 × 4 depuis une translation (x, y, z) et un quaternion (x, y, z, w)."""
    t = np.eye(4)
    t[:3, :3] = matrice_rotation(*quaternion)
    t[:3, 3] = translation
    return t


def reduire(points, grille):
    """Un point par case de « grille » mètres (moyenne des points de la case), avec Open3D."""
    import open3d as o3d
    if len(points) == 0:
        return np.zeros((0, 3))
    nuage = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(np.asarray(points, dtype=float)))
    return np.asarray(nuage.voxel_down_sample(grille).points)


def ecrire_pcd(chemin, points):
    """Écrit un nuage .pcd (binaire) avec Open3D, par un fichier temporaire puis un renommage."""
    import open3d as o3d
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    temporaire = chemin.with_name(f".{chemin.stem}.{os.getpid()}.tmp.pcd")
    nuage = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(np.asarray(points, dtype=float)))
    if not o3d.io.write_point_cloud(str(temporaire), nuage, write_ascii=False):
        raise ErreurCarte3d(f"écriture impossible : {chemin}")
    os.replace(temporaire, chemin)


def lire_pcd(chemin):
    """Lit un nuage .pcd → tableau numpy (N, 3)."""
    import open3d as o3d
    chemin = Path(chemin)
    if not chemin.is_file():
        raise ErreurCarte3d(f"nuage introuvable : {chemin}")
    return np.asarray(o3d.io.read_point_cloud(str(chemin)).points)


# ---------------------------------------------------------------- lecture du ros2 bag

def _ouvrir(dossier, sujets):
    """Lecteur rosbag2 limité à ces sujets ; renvoie (lecteur, {sujet: type})."""
    import rosbag2_py
    import yaml
    dossier = Path(dossier).expanduser()
    meta = dossier / "metadata.yaml"
    if not meta.is_file():
        raise ErreurCarte3d(f"{dossier} n'est pas un enregistrement ros2 bag (pas de metadata.yaml). "
                            "Enregistrez avec : ros2 bag record -o DOSSIER /points /odom /tf_static")
    with open(meta) as f:
        infos = yaml.safe_load(f).get("rosbag2_bagfile_information", {})
    stockage = infos.get("storage_identifier", "sqlite3")
    lecteur = rosbag2_py.SequentialReader()
    lecteur.open(rosbag2_py.StorageOptions(uri=str(dossier), storage_id=stockage),
                 rosbag2_py.ConverterOptions(input_serialization_format="cdr", output_serialization_format="cdr"))
    types = {t.name: t.type for t in lecteur.get_all_topics_and_types()}
    presents = [s for s in sujets if s in types]
    if presents:
        lecteur.set_filter(rosbag2_py.StorageFilter(topics=presents))
    return lecteur, types


def _messages(dossier, sujets):
    """Parcourt les messages de ces sujets : (sujet, message, instant d'enregistrement en s)."""
    from rclpy.serialization import deserialize_message
    from rosidl_runtime_py.utilities import get_message
    lecteur, types = _ouvrir(dossier, sujets)
    classes = {s: get_message(types[s]) for s in sujets if s in types}
    if not classes:
        return
    while lecteur.has_next():
        sujet, donnees, instant = lecteur.read_next()
        if sujet in classes:
            yield sujet, deserialize_message(donnees, classes[sujet]), instant * 1e-9


def sujets_enregistres(dossier):
    """{sujet: type} de l'enregistrement."""
    return _ouvrir(dossier, [])[1]


def _choisir(types, demande, candidats, nature, type_attendu):
    if demande:
        if demande not in types:
            raise ErreurCarte3d(f"le sujet {demande} n'est pas dans l'enregistrement "
                                f"(sujets présents : {', '.join(sorted(types)) or 'aucun'})")
        return demande
    for sujet in candidats:
        if sujet in types:
            return sujet
    autres = [s for s, t in types.items() if t == type_attendu]
    if len(autres) == 1:
        return autres[0]
    raise ErreurCarte3d(f"pas de sujet de {nature} dans l'enregistrement : précisez-le "
                        f"(sujets de type {type_attendu} : {', '.join(autres) or 'aucun'})")


def _instant(entete, instant_bag):
    t = entete.stamp.sec + entete.stamp.nanosec * 1e-9
    return t if t > 0 else instant_bag


class Trajectoire:
    """Les poses de l'odométrie, interpolées à n'importe quel instant."""

    def __init__(self, instants, positions, quaternions, repere, repere_robot):
        ordre = np.argsort(instants)
        self.instants = np.asarray(instants)[ordre]
        self.positions = np.asarray(positions)[ordre]
        self.quaternions = np.asarray(quaternions)[ordre]
        self.repere = repere
        self.repere_robot = repere_robot

    def __len__(self):
        return len(self.instants)

    def pose(self, t):
        """Matrice 4 × 4 robot → monde à l'instant t, ou None si t est loin de toute mesure."""
        i = int(np.searchsorted(self.instants, t))
        voisins = [j for j in (i - 1, i) if 0 <= j < len(self.instants)]
        proche = min(voisins, key=lambda j: abs(self.instants[j] - t))
        if abs(self.instants[proche] - t) > ECART_TEMPS_MAX:
            return None
        if 0 < i < len(self.instants):
            t0, t1 = self.instants[i - 1], self.instants[i]
            f = 0.0 if t1 <= t0 else (t - t0) / (t1 - t0)
            position = (1 - f) * self.positions[i - 1] + f * self.positions[i]
        else:
            position = self.positions[proche]
        return transformation(position, self.quaternions[proche])


def lire_trajectoire(dossier, sujet_odom):
    instants, positions, quaternions = [], [], []
    repere = repere_robot = None
    for _, msg, instant in _messages(dossier, [sujet_odom]):
        p, q = msg.pose.pose.position, msg.pose.pose.orientation
        instants.append(_instant(msg.header, instant))
        positions.append((p.x, p.y, p.z))
        quaternions.append((q.x, q.y, q.z, q.w))
        repere, repere_robot = msg.header.frame_id, msg.child_frame_id
    if not instants:
        raise ErreurCarte3d(f"aucun message sur {sujet_odom} dans l'enregistrement")
    return Trajectoire(instants, positions, quaternions, repere, repere_robot)


def lire_tf_statique(dossier):
    """{repère enfant: (repère parent, matrice 4 × 4 enfant → parent)} depuis /tf_static."""
    liens = {}
    for _, msg, _ in _messages(dossier, ["/tf_static"]):
        for tf in msg.transforms:
            t, q = tf.transform.translation, tf.transform.rotation
            liens[tf.child_frame_id.lstrip("/")] = (tf.header.frame_id.lstrip("/"),
                                                    transformation((t.x, t.y, t.z), (q.x, q.y, q.z, q.w)))
    return liens


def position_capteur(liens, repere_capteur, repere_robot, capteur=None):
    """Matrice capteur → robot : chaîne de /tf_static, sinon la translation « capteur »."""
    repere, matrice = repere_capteur.lstrip("/"), np.eye(4)
    cible = (repere_robot or "base_link").lstrip("/")
    for _ in range(20):
        if repere == cible:
            return matrice, "tf_static"
        if repere not in liens:
            break
        parent, m = liens[repere]
        matrice = m @ matrice
        repere = parent
    t = np.eye(4)
    t[:3, 3] = capteur if capteur is not None else CAPTEUR_DEFAUT
    return t, "option --capteur" if capteur is not None else "défaut (0 0 1,2 : robot proxy)"


# Types des champs de PointCloud2 (sensor_msgs/PointField) → types numpy
TYPES_CHAMPS = {1: "i1", 2: "u1", 3: "i2", 4: "u2", 5: "i4", 6: "u4", 7: "f4", 8: "f8"}


def points_du_nuage(msg):
    """PointCloud2 → tableau (N, 3) des points finis (x, y, z).

    Lu directement dans les octets du message : les autres champs (intensité, anneau...) peuvent
    être d'un autre type, ce que read_points_numpy de Humble refuse.
    """
    champs = {f.name: f for f in msg.fields}
    if not all(n in champs for n in "xyz"):
        raise ErreurCarte3d("le nuage n'a pas de champs x, y et z")
    ordre = ">" if msg.is_bigendian else "<"
    type_point = np.dtype({"names": list("xyz"),
                           "formats": [ordre + TYPES_CHAMPS[champs[n].datatype] for n in "xyz"],
                           "offsets": [champs[n].offset for n in "xyz"], "itemsize": msg.point_step})
    donnees = np.frombuffer(bytes(msg.data), dtype=np.uint8)
    lignes = [donnees[i * msg.row_step:i * msg.row_step + msg.width * msg.point_step]
              for i in range(msg.height)] if msg.height > 1 else [donnees[:msg.width * msg.point_step]]
    brut = np.concatenate(lignes).view(type_point) if lignes else np.zeros(0, dtype=type_point)
    points = np.column_stack([brut["x"], brut["y"], brut["z"]]).astype(float)
    return points[np.isfinite(points).all(axis=1)]


# ---------------------------------------------------------------- obstacles mobiles

class Colonnes:
    """Compte, pour chaque colonne de la carte (case de 2D), les nuages où les rayons presque
    horizontaux s'y arrêtent (touchée) et ceux où ils la traversent (passée).

    Un mur est souvent touché et presque jamais traversé. Le passage d'un piéton est touché
    quelques fois, puis traversé souvent quand il est parti : sa colonne est déclarée mobile.
    Une table, plus basse que le capteur, n'est jamais touchée par ces rayons : elle reste.
    """

    def __init__(self, bornes, grille):
        self.xmin, self.ymin = bornes[0], bornes[1]
        self.grille = grille
        self.nx = int(math.ceil((bornes[2] - bornes[0]) / grille)) + 1
        self.ny = int(math.ceil((bornes[3] - bornes[1]) / grille)) + 1
        self.touchee = np.zeros((self.nx, self.ny), dtype=np.int32)
        self.passee = np.zeros((self.nx, self.ny), dtype=np.int32)

    def _cases(self, xy):
        i = np.floor((xy[:, 0] - self.xmin) / self.grille).astype(np.int64)
        j = np.floor((xy[:, 1] - self.ymin) / self.grille).astype(np.int64)
        ok = (i >= 0) & (i < self.nx) & (j >= 0) & (j < self.ny)
        return np.unique(i[ok] * self.ny + j[ok])

    def ajouter(self, origine, points, compter_passages=True, rayons_max=2000):
        d = points[:, :2] - origine[:2]
        distance = np.hypot(d[:, 0], d[:, 1])
        bande = (np.abs(points[:, 2] - origine[2]) < BANDE_RAYONS) & (distance > 0.5)
        if not bande.any():
            return
        p, d, distance = points[bande], d[bande], distance[bande]
        if len(p) > rayons_max:
            choix = np.linspace(0, len(p) - 1, rayons_max).astype(int)
            p, d, distance = p[choix], d[choix], distance[choix]
        self.touchee.flat[self._cases(p[:, :2])] += 1
        if not compter_passages:
            return
        pas = np.arange(0.3, distance.max(), self.grille)
        u = d / distance[:, None]
        garde = pas[None, :] < (distance[:, None] - MARGE_AVANT_IMPACT)
        xy = origine[:2] + u[:, None, :] * pas[None, :, None]
        self.passee.flat[self._cases(xy[garde])] += UN_NUAGE_SUR

    def mobiles(self, points):
        """Masque des points (N, 3) qui tombent dans une colonne mobile."""
        i = np.floor((points[:, 0] - self.xmin) / self.grille).astype(np.int64)
        j = np.floor((points[:, 1] - self.ymin) / self.grille).astype(np.int64)
        ok = (i >= 0) & (i < self.nx) & (j >= 0) & (j < self.ny)
        touchee = np.zeros(len(points), dtype=np.int64)
        passee = np.zeros(len(points), dtype=np.int64)
        touchee[ok] = self.touchee[i[ok], j[ok]]
        passee[ok] = self.passee[i[ok], j[ok]]
        return (touchee > 0) & (passee >= PASSAGES_MIN) & (passee > RAPPORT_MOBILE * touchee)


# ---------------------------------------------------------------- assemblage

def assembler(enregistrement, sujet_nuage=None, sujet_odom=None, grille=0.05, capteur=None,
              portee=20.0, retirer_mobiles=True, afficher=None):
    """Assemble l'enregistrement en un nuage (N, 3) dans le repère de l'odométrie, réduit à la grille.

    Renvoie (points, infos) ; infos : sujets, nombre de nuages utilisés, points retirés...
    """
    dire = afficher or (lambda *_: None)
    types = sujets_enregistres(enregistrement)
    sujet_nuage = _choisir(types, sujet_nuage, SUJETS_NUAGE, "nuage", "sensor_msgs/msg/PointCloud2")
    sujet_odom = _choisir(types, sujet_odom, SUJETS_ODOM, "odométrie", "nav_msgs/msg/Odometry")
    dire(f"Nuage : {sujet_nuage} ; odométrie : {sujet_odom}")
    trajectoire = lire_trajectoire(enregistrement, sujet_odom)
    liens = lire_tf_statique(enregistrement) if "/tf_static" in types else {}

    bornes = (trajectoire.positions[:, 0].min() - portee, trajectoire.positions[:, 1].min() - portee,
              trajectoire.positions[:, 0].max() + portee, trajectoire.positions[:, 1].max() + portee)
    colonnes = Colonnes(bornes, grille) if retirer_mobiles else None
    morceaux, en_attente, n_attente, bruts = [], [], 0, 0
    utilises = ignores = 0
    capteur_robot, source_capteur = None, None
    for numero, (_, msg, instant) in enumerate(_messages(enregistrement, [sujet_nuage])):
        pose = trajectoire.pose(_instant(msg.header, instant))
        points = points_du_nuage(msg)
        if pose is None or len(points) == 0:
            ignores += 1
            continue
        repere = msg.header.frame_id.lstrip("/")
        if repere in REPERES_MONDE or repere == (trajectoire.repere or "").lstrip("/"):
            monde = points                                    # déjà dans le repère de l'odométrie
            origine = pose[:3, 3]
            loin = np.hypot(*(points[:, :2] - origine[:2]).T) > portee
        else:
            if capteur_robot is None:
                capteur_robot, source_capteur = position_capteur(liens, repere, trajectoire.repere_robot, capteur)
                dire(f"Position du LiDAR sur le robot ({repere}) : {source_capteur}, "
                     f"hauteur {capteur_robot[2, 3]:.2f} m")
            loin = np.linalg.norm(points, axis=1) > portee
            capteur_monde = pose @ capteur_robot
            monde = points @ capteur_monde[:3, :3].T + capteur_monde[:3, 3]
            origine = capteur_monde[:3, 3]
        monde = monde[~loin]
        if colonnes is not None:
            colonnes.ajouter(origine, monde, compter_passages=numero % UN_NUAGE_SUR == 0)
        en_attente.append(monde)
        n_attente += len(monde)
        bruts += len(monde)
        utilises += 1
        if n_attente > 2_000_000:                             # réduire en route, pour la mémoire
            morceaux.append(reduire(np.vstack(en_attente), grille))
            en_attente, n_attente = [], 0
    if utilises == 0:
        raise ErreurCarte3d(f"aucun nuage de {sujet_nuage} n'a d'odométrie au même instant "
                            f"({ignores} nuage(s) ignoré(s)) : enregistrez {sujet_odom} en même temps")
    if en_attente:
        morceaux.append(reduire(np.vstack(en_attente), grille))
    points = reduire(np.vstack(morceaux), grille)
    retires = 0
    if colonnes is not None:
        mobiles = colonnes.mobiles(points)
        retires = int(mobiles.sum())
        points = points[~mobiles]
    infos = {"sujet_nuage": sujet_nuage, "sujet_odom": sujet_odom, "nuages": utilises, "ignores": ignores,
             "retires_mobiles": retires, "capteur": source_capteur, "points_bruts": bruts, "points": len(points)}
    dire(f"{utilises} nuage(s) assemblé(s), {ignores} ignoré(s) ; {retires} point(s) d'obstacles mobiles retiré(s)")
    return points, infos


def fabriquer_pcd(enregistrement, sortie, sujet_nuage=None, sujet_odom=None, grille=0.05, capteur=None,
                  portee=20.0, retirer_mobiles=True, afficher=None):
    """Assemble l'enregistrement et écrit le .pcd. Renvoie les infos, avec « fichier »."""
    points, infos = assembler(enregistrement, sujet_nuage, sujet_odom, grille, capteur, portee,
                              retirer_mobiles, afficher)
    if len(points) == 0:
        raise ErreurCarte3d("le nuage assemblé est vide")
    ecrire_pcd(sortie, points)
    infos["fichier"] = str(sortie)
    return infos
