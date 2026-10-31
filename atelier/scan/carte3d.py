"""Enregistrement d'un scan (ros2 bag) → nuage 3D .pcd, réduit à une grille de 5 cm.

L'enregistrement contient le nuage du LiDAR (sensor_msgs/PointCloud2) et l'odométrie
(nav_msgs/Odometry) : /points et /odom en simulation, /unitree/slam_mapping/points et
/unitree/slam_mapping/odom sur le vrai robot. Chaque nuage est replacé dans le repère de
l'odométrie (repère map), à la position du robot au même instant, puis tous les nuages sont
fusionnés et réduits (un point par case de 5 cm, avec Open3D).

Une seule base de temps (vague 5, section 12.5 du plan, bogue n° 1 du scan du 27/10) : un nuage est
apparié à la pose de l'odométrie du même instant. Sur le vrai G1, les nuages ont un horodatage nul et
l'odométrie l'horloge du robot (138 s de retard sur le PC) : on compare alors les instants de
réception (enregistrés dans le bag), pas les horodatages. Base « message » si les deux sujets ont des
horodatages non nuls et le même décalage avec l'heure du bag (à ECART_HORLOGES_MAX près), sinon
« reception ». Un nuage déjà dans le repère de l'odométrie n'est jamais jeté faute de pose : la plus
proche sert.

Repère du nuage :
  - s'il est déjà celui de l'odométrie (ex. « odom », « map ») : utilisé tel quel ;
  - sinon, c'est celui du capteur : position du robot (odométrie) puis position du LiDAR sur
    le robot, lue dans /tf_static s'il a été enregistré, sinon --capteur (défaut : -0,004 0 1,245).

Les obstacles mobiles (piétons) sont retirés : une colonne de la carte que les rayons presque
horizontaux du LiDAR traversent bien plus souvent qu'ils ne s'y arrêtent n'est pas un mur. Les
rayons partent de la vraie origine du capteur (la pose appariée ; bogue n° 2), et seuls les points
de la colonne entre HAUTEURS_MOBILES au-dessus du plan du sol sont retirés : le sol et le plafond
restent (le nuage d'affichage n'a pas de trous). Enfin, le trajet du robot est dégagé : à moins de
RAYON_TRAJET de là où il est passé, il n'y a rien de fixe (son propre corps, les gens autour de lui au
départ, la personne qui le suit dans son sillage) ; c'est le « nettoyage le long du trajet » fait à la
main le 27/10 (section 12.5 du plan), sans toucher au sol ni au plafond.

Exemple :
    ros2 bag record -o ~/robot-g1/enregistrements/scan_rdc /points /odom /tf_static
    g1-carte-3d --lieu demo --etage rdc --enregistrement ~/robot-g1/enregistrements/scan_rdc
"""
import math
import os
import struct
from pathlib import Path

import numpy as np

from atelier.scan import sol as S

SUJETS_NUAGE = ("/unitree/slam_mapping/points", "/points")
SUJETS_ODOM = ("/unitree/slam_mapping/odom", "/odom")
CAPTEUR_DEFAUT = (-0.004, 0.0, 1.245)   # LiDAR du robot proxy (model.sdf de g1_sim) : 1,245 m au-dessus de base_link
REPERES_MONDE = ("odom", "map", "world", "camera_init")
ECART_TEMPS_MAX = 0.25               # s, écart maximal entre un nuage et la pose qui le place
ECART_HORLOGES_MAX = 0.5             # s : au-delà, nuages et odométrie n'ont pas la même horloge
ECART_RAYONS_MAX = 1.0               # s : un nuage déjà placé, sans pose plus proche, ne compte pas ses rayons
PART_IGNORES_MAX = 0.05              # au-delà de 5 % de nuages ignorés : un avertissement
BASES_DE_TEMPS = ("message", "reception")

# Retrait des obstacles mobiles (voir Colonnes)
BANDE_RAYONS = 0.3                   # m, rayons à moins de 0,3 m de la hauteur du capteur
MARGE_AVANT_IMPACT = 0.25            # m, on ne compte pas la traversée juste avant l'impact
PASSAGES_MIN = 3
RAPPORT_MOBILE = 3.0                 # mobile si traversée plus de 3 fois plus souvent que touchée
UN_NUAGE_SUR = 2                     # pour aller plus vite, la traversée est comptée sur 1 nuage sur 2
HAUTEURS_MOBILES = (0.08, 2.0)       # m au-dessus du sol : seuls ces points d'une colonne mobile sont retirés
RAYON_TRAJET = 0.30                  # m : là où le robot est passé (son corps : demi-diagonale du robot simulé
                                     # 0,26 m, plus un demi-pixel), rien de fixe (bande HAUTEURS_MOBILES)
PAS_TRAJET = 0.025                   # m : le trajet est échantillonné à ce pas pour le dégager


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
    """Horodatage d'un message en secondes, ou l'instant d'enregistrement s'il est nul."""
    t = entete.stamp.sec + entete.stamp.nanosec * 1e-9
    return t if t > 0 else instant_bag


def entete_cdr(donnees):
    """(horodatage en s, frame_id) d'un message sérialisé (CDR) qui commence par un std_msgs/Header,
    lu directement dans les octets (sans désérialiser le nuage entier)."""
    ordre = "<" if donnees[1] == 1 else ">"            # 00 01 : CDR petit-boutiste ; 00 00 : gros-boutiste
    sec, nanosec, longueur = struct.unpack_from(ordre + "iII", donnees, 4)
    frame = bytes(donnees[16:16 + max(0, longueur - 1)]).decode("utf-8", "replace")
    return sec + nanosec * 1e-9, frame


def lire_instants(dossier, sujet):
    """Horodatages et instants d'enregistrement (s) de tous les messages d'un sujet : deux tableaux."""
    lecteur, types = _ouvrir(dossier, [sujet])
    horodatages, receptions = [], []
    if sujet not in types:
        return np.zeros(0), np.zeros(0)
    classe = None
    while lecteur.has_next():
        nom, donnees, instant = lecteur.read_next()
        if nom != sujet:
            continue
        try:
            stamp, _ = entete_cdr(donnees)
        except (struct.error, IndexError):
            if classe is None:
                from rosidl_runtime_py.utilities import get_message
                classe = get_message(types[sujet])
            from rclpy.serialization import deserialize_message
            entete = deserialize_message(donnees, classe).header
            stamp = entete.stamp.sec + entete.stamp.nanosec * 1e-9
        horodatages.append(stamp)
        receptions.append(instant * 1e-9)
    return np.asarray(horodatages, dtype=float), np.asarray(receptions, dtype=float)


def choisir_base_de_temps(horodatages_nuage, receptions_nuage, horodatages_odom, receptions_odom,
                          ecart_max=ECART_HORLOGES_MAX):
    """« message » (les horodatages) ou « reception » (les instants d'enregistrement) : (base, raison).

    reception si un nuage ou une odométrie a un horodatage nul, ou si les deux sujets n'ont pas le même
    décalage avec l'heure du bag (médianes à plus de ecart_max s : deux horloges différentes)."""
    hn, rn = np.asarray(horodatages_nuage, dtype=float), np.asarray(receptions_nuage, dtype=float)
    ho, ro = np.asarray(horodatages_odom, dtype=float), np.asarray(receptions_odom, dtype=float)
    if len(hn) and (hn <= 0).any():
        return "reception", f"{int((hn <= 0).sum())} nuage(s) sur {len(hn)} ont un horodatage nul"
    if len(ho) and (ho <= 0).any():
        return "reception", f"{int((ho <= 0).sum())} odométrie(s) sur {len(ho)} ont un horodatage nul"
    if len(hn) and len(ho):
        decalage_nuage = float(np.median(rn - hn))
        decalage_odom = float(np.median(ro - ho))
        if abs(decalage_nuage - decalage_odom) > ecart_max:
            return "reception", (f"nuages et odométrie n'ont pas la même horloge (écart de "
                                 f"{decalage_odom - decalage_nuage:+.1f} s)")
    return "message", "nuages et odométrie ont la même horloge"


class Trajectoire:
    """Les poses de l'odométrie, interpolées à n'importe quel instant (dans la base de temps choisie)."""

    def __init__(self, instants, positions, quaternions, repere, repere_robot):
        ordre = np.argsort(instants, kind="stable")
        self.instants = np.asarray(instants, dtype=float)[ordre]
        self.positions = np.asarray(positions, dtype=float)[ordre]
        self.quaternions = np.asarray(quaternions, dtype=float)[ordre]
        self.repere = repere
        self.repere_robot = repere_robot

    def __len__(self):
        return len(self.instants)

    def proche(self, t):
        """(matrice 4 × 4 robot → monde, écart en s) de la pose de l'instant t : interpolée entre les deux
        mesures voisines (position), ou la mesure la plus proche si t est hors de la trajectoire."""
        i = int(np.searchsorted(self.instants, t))
        voisins = [j for j in (i - 1, i) if 0 <= j < len(self.instants)]
        proche = min(voisins, key=lambda j: abs(self.instants[j] - t))
        ecart = abs(float(self.instants[proche]) - t)
        if 0 < i < len(self.instants):
            t0, t1 = self.instants[i - 1], self.instants[i]
            f = 0.0 if t1 <= t0 else (t - t0) / (t1 - t0)
            position = (1 - f) * self.positions[i - 1] + f * self.positions[i]
        else:
            position = self.positions[proche]
        return transformation(position, self.quaternions[proche]), ecart

    def pose(self, t):
        """Matrice 4 × 4 robot → monde à l'instant t, ou None si t est loin de toute mesure."""
        pose, ecart = self.proche(t)
        return pose if ecart <= ECART_TEMPS_MAX else None


def lire_trajectoire(dossier, sujet_odom, base="message"):
    """Trajectoire de l'odométrie, datée par ses horodatages (base « message ») ou par les instants
    d'enregistrement (« reception »)."""
    if base not in BASES_DE_TEMPS:
        raise ValueError(f"base de temps inconnue : {base} ({', '.join(BASES_DE_TEMPS)})")
    instants, positions, quaternions = [], [], []
    repere = repere_robot = None
    for _, msg, instant in _messages(dossier, [sujet_odom]):
        p, q = msg.pose.pose.position, msg.pose.pose.orientation
        instants.append(instant if base == "reception" else _instant(msg.header, instant))
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
    return t, "option --capteur" if capteur is not None else "défaut (-0,004 0 1,245 : robot proxy)"


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

def _horodatage(entete):
    return entete.stamp.sec + entete.stamp.nanosec * 1e-9


def echantillonner_trajet(positions, pas=PAS_TRAJET):
    """Positions (N, 2+) du robot → points (M, 2) le long de son trajet, tous les « pas » mètres au plus."""
    p = np.asarray(positions, dtype=float)[:, :2]
    if len(p) < 2:
        return p.copy()
    morceaux = [p[:1]]
    for a, b in zip(p[:-1], p[1:]):
        n = int(math.ceil(math.hypot(*(b - a)) / pas))
        if n > 0:
            t = np.arange(1, n + 1)[:, None] / n
            morceaux.append(a + t * (b - a))
    return np.vstack(morceaux)


def pres_du_trajet(points, positions, rayon=RAYON_TRAJET, grille=0.05):
    """Masque des points (N, 3) à moins de « rayon » (en x, y, à une case de grille près) du trajet du robot."""
    points = np.asarray(points, dtype=float).reshape(-1, 3)
    trajet = echantillonner_trajet(positions)
    if len(points) == 0 or len(trajet) == 0:
        return np.zeros(len(points), dtype=bool)
    xmin, ymin = trajet.min(axis=0) - rayon - grille
    xmax, ymax = trajet.max(axis=0) + rayon + grille
    nx, ny = int(math.ceil((xmax - xmin) / grille)) + 1, int(math.ceil((ymax - ymin) / grille)) + 1
    masque = np.zeros((nx, ny), dtype=bool)
    k = int(math.ceil(rayon / grille))
    di, dj = np.meshgrid(np.arange(-k, k + 1), np.arange(-k, k + 1), indexing="ij")
    disque = np.hypot(di, dj) * grille <= rayon
    di, dj = di[disque], dj[disque]
    ci = np.floor((trajet[:, 0] - xmin) / grille).astype(np.int64)
    cj = np.floor((trajet[:, 1] - ymin) / grille).astype(np.int64)
    centres = np.unique(ci * ny + cj)
    ci, cj = centres // ny, centres % ny
    ii, jj = (ci[:, None] + di[None, :]).ravel(), (cj[:, None] + dj[None, :]).ravel()
    ok = (ii >= 0) & (ii < nx) & (jj >= 0) & (jj < ny)
    masque[ii[ok], jj[ok]] = True
    i = np.floor((points[:, 0] - xmin) / grille).astype(np.int64)
    j = np.floor((points[:, 1] - ymin) / grille).astype(np.int64)
    dedans = (i >= 0) & (i < nx) & (j >= 0) & (j < ny)
    resultat = np.zeros(len(points), dtype=bool)
    resultat[dedans] = masque[i[dedans], j[dedans]]
    return resultat


def assembler(enregistrement, sujet_nuage=None, sujet_odom=None, grille=0.05, capteur=None,
              portee=20.0, retirer_mobiles=True, afficher=None, base_de_temps=None, sol=None,
              degager_trajet=True):
    """Assemble l'enregistrement en un nuage (N, 3) dans le repère de l'odométrie, réduit à la grille.

    base_de_temps : « message », « reception », ou None (choisie seule, voir choisir_base_de_temps).
    sol : niveau du sol imposé (plan horizontal), sinon le plan du sol est trouvé (atelier.scan.sol).
    degager_trajet : retirer ce qui est à moins de RAYON_TRAJET du trajet du robot (sauf sol et plafond).
    Renvoie (points, infos) ; infos : sujets, recus, nuages (utilisés), ignores, base_de_temps,
    retires_mobiles (passants et trajet), retires_trajet, sol (dict de trouver_sol), avertissements...
    """
    dire = afficher or (lambda *_: None)
    types = sujets_enregistres(enregistrement)
    sujet_nuage = _choisir(types, sujet_nuage, SUJETS_NUAGE, "nuage", "sensor_msgs/msg/PointCloud2")
    sujet_odom = _choisir(types, sujet_odom, SUJETS_ODOM, "odométrie", "nav_msgs/msg/Odometry")
    dire(f"Nuage : {sujet_nuage} ; odométrie : {sujet_odom}")
    if base_de_temps is None:
        base_de_temps, raison = choisir_base_de_temps(*lire_instants(enregistrement, sujet_nuage),
                                                      *lire_instants(enregistrement, sujet_odom))
    elif base_de_temps not in BASES_DE_TEMPS:
        raise ErreurCarte3d(f"base de temps inconnue : {base_de_temps} ({', '.join(BASES_DE_TEMPS)})")
    else:
        raison = "imposée"
    dire(f"Base de temps : {'horodatages des messages' if base_de_temps == 'message' else 'instants de réception'} "
         f"({raison})")
    trajectoire = lire_trajectoire(enregistrement, sujet_odom, base_de_temps)
    liens = lire_tf_statique(enregistrement) if "/tf_static" in types else {}

    bornes = (trajectoire.positions[:, 0].min() - portee, trajectoire.positions[:, 1].min() - portee,
              trajectoire.positions[:, 0].max() + portee, trajectoire.positions[:, 1].max() + portee)
    colonnes = Colonnes(bornes, grille) if retirer_mobiles else None
    morceaux, en_attente, n_attente, bruts = [], [], 0, 0
    recus = utilises = ignores = vides = sans_pose = sans_rayons = 0
    ecarts = []
    capteur_robot, source_capteur = None, None
    repere_odom = (trajectoire.repere or "").lstrip("/")
    for numero, (_, msg, instant) in enumerate(_messages(enregistrement, [sujet_nuage])):
        recus += 1
        t = instant if base_de_temps == "reception" else _instant(msg.header, instant)
        points = points_du_nuage(msg)
        if len(points) == 0:
            vides += 1
            ignores += 1
            continue
        pose, ecart = trajectoire.proche(t)
        repere = msg.header.frame_id.lstrip("/")
        if repere in REPERES_MONDE or repere == repere_odom:
            monde = points                                    # déjà dans le repère de l'odométrie
            rayons = ecart <= ECART_RAYONS_MAX                # jamais jeté : la pose la plus proche sert
            if rayons:
                origine = pose[:3, 3]
                monde = monde[np.hypot(*(points[:, :2] - origine[:2]).T) <= portee]
            else:
                sans_rayons += 1
        else:
            if ecart > ECART_TEMPS_MAX:                       # dans le repère du capteur : il faut la pose
                sans_pose += 1
                ignores += 1
                continue
            if capteur_robot is None:
                capteur_robot, source_capteur = position_capteur(liens, repere, trajectoire.repere_robot, capteur)
                dire(f"Position du LiDAR sur le robot ({repere}) : {source_capteur}, "
                     f"hauteur {capteur_robot[2, 3]:.2f} m")
            loin = np.linalg.norm(points, axis=1) > portee
            capteur_monde = pose @ capteur_robot
            monde = points[~loin] @ capteur_monde[:3, :3].T + capteur_monde[:3, 3]
            origine = capteur_monde[:3, 3]
            rayons = True
        ecarts.append(ecart)
        if colonnes is not None and rayons:
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
                            f"({ignores} nuage(s) ignoré(s) sur {recus}) : enregistrez {sujet_odom} en même temps")
    if en_attente:
        morceaux.append(reduire(np.vstack(en_attente), grille))
    points = reduire(np.vstack(morceaux), grille)
    try:
        sol_trouve = S.trouver_sol(points, sol=sol)
    except S.ErreurSol as e:
        raise ErreurCarte3d(str(e)) from None
    retires = retires_trajet = 0
    h = S.hauteurs(points, sol_trouve["plan"])
    bande = (h >= HAUTEURS_MOBILES[0]) & (h <= HAUTEURS_MOBILES[1])
    a_retirer = np.zeros(len(points), dtype=bool)
    if colonnes is not None:
        a_retirer = colonnes.mobiles(points) & bande
    if degager_trajet:
        sur_le_trajet = pres_du_trajet(points, trajectoire.positions) & bande & ~a_retirer
        retires_trajet = int(sur_le_trajet.sum())
        a_retirer |= sur_le_trajet
    retires = int(a_retirer.sum())
    points = points[~a_retirer]
    avertissements = []
    if recus and ignores > PART_IGNORES_MAX * recus:
        avertissements.append(f"{ignores} nuage(s) sur {recus} ignoré(s) ({100 * ignores / recus:.0f} %) : "
                              + (f"{sans_pose} sans odométrie au même instant" if sans_pose else "")
                              + (", " if sans_pose and vides else "") + (f"{vides} vide(s)" if vides else "")
                              + ". Vérifiez que l'odométrie a été enregistrée pendant tout le scan.")
    if sans_rayons:
        avertissements.append(f"{sans_rayons} nuage(s) gardé(s) sans odométrie proche (à plus de "
                              f"{ECART_RAYONS_MAX:g} s) : leurs passants ne sont pas retirés")
    infos = {"sujet_nuage": sujet_nuage, "sujet_odom": sujet_odom, "recus": recus, "nuages": utilises,
             "ignores": ignores, "vides": vides, "sans_pose": sans_pose, "sans_rayons": sans_rayons,
             "base_de_temps": base_de_temps, "raison_base": raison,
             "ecart_pose_max_s": round(float(max(ecarts)), 3) if ecarts else None,
             "retires_mobiles": retires, "retires_trajet": retires_trajet, "capteur": source_capteur,
             "points_bruts": bruts, "points": len(points),
             "sol": sol_trouve, "avertissements": avertissements}
    dire(f"{utilises} nuage(s) assemblé(s) sur {recus}, {ignores} ignoré(s) ; {retires} point(s) d'obstacles "
         f"mobiles retiré(s), dont {retires_trajet} sur le trajet du robot ; sol : plan incliné de "
         f"{sol_trouve['inclinaison_deg']:.2f}° ({sol_trouve['methode']})")
    for a in avertissements:
        dire(f"Attention : {a}")
    return points, infos


def fabriquer_pcd(enregistrement, sortie, sujet_nuage=None, sujet_odom=None, grille=0.05, capteur=None,
                  portee=20.0, retirer_mobiles=True, afficher=None, base_de_temps=None, sol=None,
                  avec_points=False, degager_trajet=True):
    """Assemble l'enregistrement et écrit le .pcd. Renvoie les infos, avec « fichier » (et les points
    eux-mêmes sous « tableau » avec avec_points)."""
    points, infos = assembler(enregistrement, sujet_nuage, sujet_odom, grille, capteur, portee,
                              retirer_mobiles, afficher, base_de_temps, sol, degager_trajet)
    if len(points) == 0:
        raise ErreurCarte3d("le nuage assemblé est vide")
    ecrire_pcd(sortie, points)
    infos["fichier"] = str(sortie)
    if avec_points:
        infos["tableau"] = points
    return infos
