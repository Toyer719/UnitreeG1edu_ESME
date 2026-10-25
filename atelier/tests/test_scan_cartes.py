"""Tests de carte3d.py et carte2d.py (agent Scan), sans Gazebo ni robot.

Le nuage synthétique est fabriqué à partir de lieux/demo/mondes/rdc.monde.yaml : des points sur
les faces des murs et des objets, un peu de sol et un peu de bruit. Sa carte 2D est comparée à
celle que l'agent Monde trace depuis le même monde (atelier.monde.carte), ou, si ce module
n'existe pas, à un tracé simple fait ici.
"""
import math

import numpy as np
import pytest

from atelier import RACINE
from atelier.lieu import (MODELES_MOBILIER, charger_carte, charger_fiche, charger_monde, chemin_carte,
                          chemin_pcd, copier_lieu, info_carte_pour_emprise, monde_vers_pixel, pixel_vers_monde)
from atelier.scan import carte2d, carte3d

LIEU_DEMO = RACINE / "lieux" / "demo"


# ---------------------------------------------------------------- nuage synthétique

def _face(a, b, z0, z1, pas):
    """Points d'un rectangle vertical de a à b (2D), de z0 à z1."""
    longueur = math.dist(a, b)
    n = max(2, int(math.ceil(longueur / pas)) + 1)
    m = max(2, int(math.ceil((z1 - z0) / pas)) + 1)
    t, z = np.meshgrid(np.linspace(0, 1, n), np.linspace(z0, z1, m))
    x = a[0] + t * (b[0] - a[0])
    y = a[1] + t * (b[1] - a[1])
    return np.column_stack([x.ravel(), y.ravel(), z.ravel()])


def _dessus(coins, z, pas):
    """Points d'un rectangle horizontal (4 coins dans l'ordre) à la hauteur z."""
    a, b, _, d = [np.asarray(c, dtype=float) for c in coins]
    n = max(2, int(math.ceil(np.linalg.norm(b - a) / pas)) + 1)
    m = max(2, int(math.ceil(np.linalg.norm(d - a) / pas)) + 1)
    u, v = np.meshgrid(np.linspace(0, 1, n), np.linspace(0, 1, m))
    p = a + u.ravel()[:, None] * (b - a) + v.ravel()[:, None] * (d - a)
    return np.column_stack([p, np.full(len(p), z)])


def _boite(coins, hauteur, pas):
    morceaux = [_face(coins[i], coins[(i + 1) % 4], 0.0, hauteur, pas) for i in range(4)]
    morceaux.append(_dessus(coins, hauteur, pas))
    return np.vstack(morceaux)


def _cylindre(centre, rayon, hauteur, pas):
    n = max(8, int(2 * math.pi * rayon / pas))
    angles = np.linspace(0, 2 * math.pi, n, endpoint=False)
    z = np.arange(0.0, hauteur + 1e-9, pas)
    a, zz = np.meshgrid(angles, z)
    morceaux = [np.column_stack([centre[0] + rayon * np.cos(a.ravel()), centre[1] + rayon * np.sin(a.ravel()),
                                 zz.ravel()])]
    r, a = np.meshgrid(np.arange(0.0, rayon, pas), angles)
    morceaux.append(np.column_stack([centre[0] + r.ravel() * np.cos(a.ravel()),
                                     centre[1] + r.ravel() * np.sin(a.ravel()), np.full(r.size, hauteur)]))
    return np.vstack(morceaux)


def nuage_synthetique(monde, pas=0.025, sol=0.0, bruit=0, graine=1):
    """Points (N, 3) sur les murs et les objets du monde, du sol tous les 0,25 m, et « bruit »
    points isolés au hasard. sol : hauteur du sol dans le repère du nuage."""
    morceaux = [_boite(m.coins(), m.hauteur, pas) for m in monde.murs]
    for o in monde.objets:
        empreinte = o.empreinte()
        if empreinte[0] == "cercle":
            morceaux.append(_cylindre(empreinte[1], empreinte[2], o.hauteur_totale(), pas))
        else:
            morceaux.append(_boite(empreinte[1], o.hauteur_totale(), pas))
    e = monde.emprise
    x, y = np.meshgrid(np.arange(e.xmin, e.xmax, 0.25), np.arange(e.ymin, e.ymax, 0.25))
    morceaux.append(np.column_stack([x.ravel(), y.ravel(), np.zeros(x.size)]))
    if bruit:
        alea = np.random.default_rng(graine)
        morceaux.append(np.column_stack([alea.uniform(e.xmin + 1, e.xmax - 1, bruit),
                                         alea.uniform(e.ymin + 1, e.ymax - 1, bruit),
                                         alea.uniform(0.3, 1.2, bruit)]))
    points = np.vstack(morceaux)
    points[:, 2] += sol
    return points


def carte_reference(monde):
    """Carte du monde par l'agent Monde (atelier.monde.carte), sinon par un tracé simple ici."""
    try:
        from atelier.monde.carte import fabriquer_carte
        return fabriquer_carte(monde)
    except ImportError:
        pass
    e = monde.emprise
    info = info_carte_pour_emprise(e.xmin, e.ymin, e.xmax, e.ymax)
    X, Y = pixel_vers_monde(*np.meshgrid(np.arange(info.largeur), np.arange(info.hauteur)), info)
    carte = np.full((info.hauteur, info.largeur), 205, dtype=np.uint8)
    carte[(X > e.xmin) & (X < e.xmax) & (Y > e.ymin) & (Y < e.ymax)] = 254
    for forme in [("polygone", m.coins()) for m in monde.murs] + [o.empreinte() for o in monde.objets]:
        if forme[0] == "cercle":
            dedans = np.hypot(X - forme[1][0], Y - forme[1][1]) <= forme[2] + 0.025
        else:
            # Rectangle (convexe) agrandi d'un demi-pixel : du bon côté de chaque bord
            coins = np.asarray(forme[1])
            sens = np.sign(np.cross(coins[1] - coins[0], coins[2] - coins[1])) or 1.0
            dedans = np.ones(X.shape, dtype=bool)
            for a, b in zip(coins, np.roll(coins, -1, axis=0)):
                n = np.array([b[1] - a[1], a[0] - b[0]]) * sens / np.hypot(*(b - a))
                dedans &= (X - a[0]) * n[0] + (Y - a[1]) * n[1] <= 0.025
        carte[dedans] = 0
    return info, carte


@pytest.fixture(scope="module")
def monde_demo():
    return charger_monde(LIEU_DEMO, "rdc")


# ---------------------------------------------------------------- carte2d

def test_outils_morphologiques():
    occupe = np.zeros((10, 12), dtype=bool)
    occupe[2, 1:11] = True            # un mur fin, d'un pixel d'épaisseur
    occupe[7, 3] = True               # une tache isolée
    occupe[7:9, 8:10] = True          # une tache de 4 pixels
    nettoye = carte2d.ouverture_par_aire(occupe, 4)
    assert nettoye[2, 1:11].all()     # le mur fin reste (une ouverture classique l'effacerait)
    assert not nettoye[7, 3]
    assert nettoye[7:9, 8:10].all()
    assert carte2d.ouverture_par_aire(occupe, 5)[7:9, 8:10].sum() == 0
    d = carte2d.dilater(occupe, 1)
    assert d[1, 0] and d[3, 11] and d[6, 2] and not d[5, 5]


def test_estimer_sol():
    alea = np.random.default_rng(0)
    murs = np.column_stack([alea.uniform(0, 10, 5000), alea.uniform(0, 10, 5000), alea.uniform(-1.2, 1.3, 5000)])
    sol = np.column_stack([alea.uniform(0, 10, 3000), alea.uniform(0, 10, 3000), np.full(3000, -1.2)])
    assert carte2d.estimer_sol(np.vstack([murs, sol])) == pytest.approx(-1.2, abs=0.01)
    assert carte2d.estimer_sol(murs) == pytest.approx(-1.2, abs=0.05)    # sol pas vu : pied des murs


@pytest.mark.parametrize("sol", [0.0, -1.2])
def test_carte_du_nuage_synthetique(monde_demo, sol):
    """Le nuage des murs et objets donne la carte du monde : au moins 80 % de recouvrement."""
    points = nuage_synthetique(monde_demo, sol=sol, bruit=300)
    e = monde_demo.emprise
    info, carte, sol_trouve = carte2d.fabriquer_carte(points, (e.xmin, e.ymin, e.xmax, e.ymax))
    assert sol_trouve == pytest.approx(sol, abs=0.05)
    info_ref, carte_ref = carte_reference(monde_demo)
    assert (info.largeur, info.hauteur, info.origin) == (info_ref.largeur, info_ref.hauteur, info_ref.origin)
    assert set(np.unique(carte)) <= {0, 205, 254}
    r = carte2d.comparer(info, carte, info_ref, carte_ref)
    assert r["recouvrement"] >= 0.95, r
    assert r["couverture"] >= 0.80, r
    # Le bruit isolé est retiré, et le milieu du couloir sud est libre
    c, l = monde_vers_pixel(15.0, 7.0, info)
    assert carte[l, c] == 254
    c, l = monde_vers_pixel(10.0, 5.5, info)          # un mur
    assert carte[l, c] == 0
    c, l = monde_vers_pixel(-0.2, 10.0, info)         # hors de l'image : rien à tester
    assert c < 0


def test_carte_sans_emprise_et_erreurs(monde_demo):
    points = nuage_synthetique(monde_demo, pas=0.05)
    info, carte, _ = carte2d.fabriquer_carte(points)
    xmin, ymin = info.origin[0], info.origin[1]
    assert -0.3 < xmin < 0.0 and -0.3 < ymin < 0.0           # le mur extérieur déborde de 0,1 m
    with pytest.raises(carte2d.ErreurCarte2d):
        carte2d.fabriquer_carte(np.zeros((0, 3)))
    with pytest.raises(carte2d.ErreurCarte2d):
        carte2d.fabriquer_carte(np.array([[0.0, 0.0, 0.0], [1.0, 1.0, 0.0], [0.0, 0.0, 5.0]]), sol=0.0)


def test_carte2d_dans_un_lieu(tmp_path, monde_demo):
    lieu = copier_lieu(LIEU_DEMO, tmp_path / "essai")
    carte3d.ecrire_pcd(chemin_pcd(lieu, "rdc"), nuage_synthetique(monde_demo, pas=0.04, sol=-1.2))
    avant = chemin_carte(lieu, "rdc").read_bytes() if chemin_carte(lieu, "rdc").exists() else None
    # Vers un autre fichier : le lieu n'est pas touché
    autre = tmp_path / "scan.yaml"
    r = carte2d.fabriquer_carte_lieu(lieu, "rdc", sortie=autre)
    assert autre.is_file() and (tmp_path / "scan.pgm").is_file() and r["occupes"] > 1000
    apres = chemin_carte(lieu, "rdc").read_bytes() if chemin_carte(lieu, "rdc").exists() else None
    assert apres == avant
    assert charger_fiche(lieu).etage("rdc").source_carte == "monde"
    # Dans le lieu : cartes/rdc.yaml, et l'étage passe à source_carte: scan
    r = carte2d.fabriquer_carte_lieu(lieu, "rdc")
    info, image = charger_carte(chemin_carte(lieu, "rdc"))
    assert info.image == "rdc.pgm" and info.resolution == 0.05 and image.shape == (402, 602)
    assert charger_fiche(lieu).etage("rdc").source_carte == "scan"
    assert carte2d.comparer_fichiers(chemin_carte(lieu, "rdc"), autre)["recouvrement"] == 1.0
    with pytest.raises(carte2d.ErreurCarte2d):
        carte2d.fabriquer_carte_lieu(lieu, "etage_inconnu")


def test_commande_g1_carte_2d(tmp_path, monde_demo):
    import os
    import subprocess
    lieu = copier_lieu(LIEU_DEMO, tmp_path / "lieux" / "essai")
    env = dict(os.environ, ATELIER_LIEUX=str(tmp_path / "lieux"))
    commande = [str(RACINE / "bin" / "g1-carte-2d"), "--lieu", "essai", "--etage", "rdc"]
    r = subprocess.run(commande, env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 1 and "g1-carte-3d" in r.stdout          # pas encore de nuage
    carte3d.ecrire_pcd(chemin_pcd(lieu, "rdc"), nuage_synthetique(monde_demo, pas=0.04))
    info_ref, carte_ref = carte_reference(monde_demo)
    from atelier.lieu import enregistrer_carte
    enregistrer_carte(tmp_path / "ref.yaml", info_ref, carte_ref)
    r = subprocess.run(commande + ["--comparer", str(tmp_path / "ref.yaml")], env=env, capture_output=True,
                       text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Recouvrement" in r.stdout and "source_carte: scan" in r.stdout
    assert chemin_carte(lieu, "rdc").is_file()


# ---------------------------------------------------------------- carte3d : un faux ros2 bag

def _visibles(points, origine, murs):
    """Points dont la ligne de vue (en 2D) depuis origine ne coupe aucun mur (axe du mur)."""
    p = points[:, :2]
    cache = np.zeros(len(points), dtype=bool)
    o = np.asarray(origine[:2])
    for m in murs:
        a, b = np.asarray(m.de), np.asarray(m.a)

        def cote(u, v, w):
            return (v[..., 0] - u[..., 0]) * (w[..., 1] - u[..., 1]) - (v[..., 1] - u[..., 1]) * (w[..., 0] - u[..., 0])
        d1 = cote(a[None], b[None], o[None]) * cote(a[None], b[None], p)
        d2 = cote(o[None], p, a[None]) * cote(o[None], p, b[None])
        cache |= (d1 < 0) & (d2 < 0)
    return points[~cache]


def ecrire_faux_bag(dossier, monde, poses, pieton=None, frequence=5.0, portee=8.0):
    """ros2 bag avec /points (repère lidar, 1,2 m au-dessus du robot), /odom et /tf_static.

    Chaque nuage contient les points du nuage synthétique visibles depuis le LiDAR. pieton :
    fonction t → (x, y) d'un piéton (cylindre de points) qui marche pendant l'enregistrement.
    """
    import rosbag2_py
    from builtin_interfaces.msg import Time
    from geometry_msgs.msg import TransformStamped
    from nav_msgs.msg import Odometry
    from rclpy.serialization import serialize_message
    from sensor_msgs.msg import PointCloud2, PointField
    from tf2_msgs.msg import TFMessage

    tous = nuage_synthetique(monde, pas=0.05)
    ecrivain = rosbag2_py.SequentialWriter()
    ecrivain.open(rosbag2_py.StorageOptions(uri=str(dossier), storage_id="sqlite3"),
                  rosbag2_py.ConverterOptions("cdr", "cdr"))
    for nom, type_ in (("/points", "sensor_msgs/msg/PointCloud2"), ("/odom", "nav_msgs/msg/Odometry"),
                       ("/tf_static", "tf2_msgs/msg/TFMessage")):
        ecrivain.create_topic(rosbag2_py.TopicMetadata(name=nom, type=type_, serialization_format="cdr"))

    def instant(t):
        return Time(sec=int(t), nanosec=int((t % 1) * 1e9))

    tf = TransformStamped()
    tf.header.frame_id, tf.child_frame_id = "base_link", "lidar"
    tf.transform.translation.z = 1.2
    tf.transform.rotation.w = 1.0
    ecrivain.write("/tf_static", serialize_message(TFMessage(transforms=[tf])), int(1e9))
    t0 = 1000.0
    for k, (x, y, theta) in enumerate(poses):
        t = t0 + k / frequence
        for dt in (-0.1, 0.0, 0.1):       # odométrie plus fréquente que le nuage
            o = Odometry()
            o.header.frame_id, o.child_frame_id = "odom", "base_link"
            o.header.stamp = instant(t + dt)
            o.pose.pose.position.x, o.pose.pose.position.y = x + dt * 0.0, y
            o.pose.pose.orientation.z, o.pose.pose.orientation.w = math.sin(theta / 2), math.cos(theta / 2)
            ecrivain.write("/odom", serialize_message(o), int((t + dt) * 1e9))
        proches = tous[np.hypot(tous[:, 0] - x, tous[:, 1] - y) < portee]
        visibles = _visibles(proches, (x, y), monde.murs)
        if pieton is not None:
            px, py = pieton(t - t0)
            a = np.linspace(0, 2 * math.pi, 24, endpoint=False)
            z = np.arange(0.05, 1.75, 0.05)
            aa, zz = np.meshgrid(a, z)
            corps = np.column_stack([px + 0.2 * np.cos(aa.ravel()), py + 0.2 * np.sin(aa.ravel()), zz.ravel()])
            visibles = np.vstack([visibles, corps])
        # Monde → repère du LiDAR (robot en x, y, theta ; LiDAR 1,2 m plus haut)
        c, s = math.cos(theta), math.sin(theta)
        d = visibles - np.array([x, y, 1.2])
        local = np.column_stack([c * d[:, 0] + s * d[:, 1], -s * d[:, 0] + c * d[:, 1], d[:, 2]]).astype(np.float32)
        nuage = PointCloud2()
        nuage.header.frame_id, nuage.header.stamp = "lidar", instant(t)
        nuage.height, nuage.width = 1, len(local)
        nuage.fields = [PointField(name=n, offset=4 * i, datatype=PointField.FLOAT32, count=1)
                        for i, n in enumerate("xyz")]
        nuage.point_step, nuage.row_step = 12, 12 * len(local)
        nuage.is_bigendian, nuage.is_dense = False, True
        nuage.data = local.tobytes()
        ecrivain.write("/points", serialize_message(nuage), int(t * 1e9))
    del ecrivain


def parcours_couloirs():
    """Le robot parcourt le couloir nord puis le couloir sud du demo, par le hall (0,75 m/s à 5 Hz)."""
    poses = []
    for (xa, ya), (xb, yb) in (((2.5, 10.0), (2.5, 13.0)), ((2.5, 13.0), (27.5, 13.0)),
                               ((27.5, 13.0), (27.5, 7.0)), ((27.5, 7.0), (2.5, 7.0))):
        n = int(math.dist((xa, ya), (xb, yb)) / 0.15)
        cap = math.atan2(yb - ya, xb - xa)
        poses += [(xa + (xb - xa) * k / n, ya + (yb - ya) * k / n, cap) for k in range(n)]
    return poses


@pytest.fixture(scope="module")
def faux_bag(tmp_path_factory, monde_demo):
    pytest.importorskip("rosbag2_py")
    dossier = tmp_path_factory.mktemp("bag") / "scan"
    # Un piéton fait l'aller-retour dans le couloir nord pendant l'enregistrement
    def pieton(t):
        u = (t * 1.0) % 36.0
        return (6.0 + (u if u < 18 else 36 - u), 13.8)
    ecrire_faux_bag(dossier, monde_demo, parcours_couloirs(), pieton=pieton)
    return dossier


def test_carte3d_puis_carte2d(tmp_path, faux_bag, monde_demo):
    sortie = tmp_path / "rdc.pcd"
    infos = carte3d.fabriquer_pcd(faux_bag, sortie)
    assert infos["sujet_nuage"] == "/points" and infos["sujet_odom"] == "/odom"
    assert infos["capteur"] == "tf_static" and infos["nuages"] > 350 and infos["ignores"] == 0
    points = carte3d.lire_pcd(sortie)
    assert len(points) == infos["points"] > 10000
    # Grille de 5 cm : bien moins de points que dans les nuages bruts, et une seconde réduction
    # à la même grille n'en enlève presque plus
    assert len(points) < infos["points_bruts"] / 5
    assert len(carte3d.reduire(points, 0.05)) > 0.7 * len(points)
    # Les points sont revenus dans le repère du monde : au pied des murs, z ≈ 0
    assert np.percentile(points[:, 2], 1) == pytest.approx(0.0, abs=0.1)
    # Le piéton est retiré : rien d'occupé le long de son trajet, loin des murs
    assert infos["retires_mobiles"] > 0
    e = monde_demo.emprise
    info, carte, _ = carte2d.fabriquer_carte(points, (e.xmin, e.ymin, e.xmax, e.ymax))
    for x in np.arange(10.0, 20.0, 0.5):
        c, l = monde_vers_pixel(x, 13.8, info)
        assert carte[l, c] == 254, f"trace du piéton en ({x}, 13.8)"
    info_ref, carte_ref = carte_reference(monde_demo)
    r = carte2d.comparer(info, carte, info_ref, carte_ref)
    assert r["recouvrement"] >= 0.80, r


def test_carte3d_sans_retirer_les_mobiles(tmp_path, faux_bag, monde_demo):
    points, infos = carte3d.assembler(faux_bag, retirer_mobiles=False)
    assert infos["retires_mobiles"] == 0
    e = monde_demo.emprise
    info, carte, _ = carte2d.fabriquer_carte(points, (e.xmin, e.ymin, e.xmax, e.ymax))
    traces = sum(carte[monde_vers_pixel(x, 13.8, info)[1], monde_vers_pixel(x, 13.8, info)[0]] == 0
                 for x in np.arange(10.0, 20.0, 0.5))
    assert traces >= 5                     # sans le filtre, le piéton laisse une trace


def test_carte3d_erreurs(tmp_path, faux_bag):
    with pytest.raises(carte3d.ErreurCarte3d, match="metadata.yaml"):
        carte3d.fabriquer_pcd(tmp_path, tmp_path / "x.pcd")
    with pytest.raises(carte3d.ErreurCarte3d, match="/inconnu"):
        carte3d.fabriquer_pcd(faux_bag, tmp_path / "x.pcd", sujet_nuage="/inconnu")


def test_commande_g1_carte_3d(tmp_path, faux_bag):
    import os
    import subprocess
    lieu = copier_lieu(LIEU_DEMO, tmp_path / "lieux" / "essai")
    env = dict(os.environ, ATELIER_LIEUX=str(tmp_path / "lieux"))
    r = subprocess.run([str(RACINE / "bin" / "g1-carte-3d"), "--lieu", "essai", "--etage", "rdc",
                        "--enregistrement", str(faux_bag)], env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    assert chemin_pcd(lieu, "rdc").is_file() and "g1-carte-2d" in r.stdout
