"""Tests de carte3d.py, carte2d.py et sol.py (agent Scan), sans Gazebo ni robot.

Le nuage synthétique est fabriqué à partir de lieux/demo/mondes/rdc.monde.yaml : des points sur
les faces des murs et des objets, un peu de sol et un peu de bruit. Sa carte 2D est comparée à
celle que l'agent Monde trace depuis le même monde (atelier.monde.carte), ou, si ce module
n'existe pas, à un tracé simple fait ici.

Vague 5 (section 12.5 du plan) : les trois bogues du scan du 27/10 sont reproduits ici, dans un faux
bag « comme le G1 » (nuages déjà dans le repère map et à horodatage nul, odométrie à l'horloge du
robot, décalée de −138 s ; sol penché de 0,58° et 1,27 m sous l'origine) :
  1. l'horloge : avant, tous les nuages étaient appariés par leur horodatage nul (instant du bag)
     aux horodatages de l'odométrie, et jetés ou mal placés ;
  2. l'origine des rayons : avec une pose fausse, le retrait des passants ne marche plus ;
  3. le sol en un seul niveau : sur un sol penché, le sol entre dans la tranche (le « damier »).
"""
import math

import numpy as np
import pytest

from atelier import RACINE
from atelier.lieu import (MODELES_MOBILIER, charger_carte, charger_fiche, charger_monde, chemin_carte,
                          chemin_pcd, copier_lieu, info_carte_pour_emprise, monde_vers_pixel, pixel_vers_monde)
from atelier.scan import carte2d, carte3d
from atelier.scan import sol as S

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


def nuage_synthetique(monde, pas=0.025, sol=0.0, bruit=0, graine=1, pas_sol=0.25):
    """Points (N, 3) sur les murs et les objets du monde, du sol tous les pas_sol mètres, et « bruit »
    points isolés au hasard. sol : hauteur du sol dans le repère du nuage."""
    morceaux = [_boite(m.coins(), m.hauteur, pas) for m in monde.murs]
    for o in monde.objets:
        empreinte = o.empreinte()
        if empreinte[0] == "cercle":
            morceaux.append(_cylindre(empreinte[1], empreinte[2], o.hauteur_totale(), pas))
        else:
            morceaux.append(_boite(empreinte[1], o.hauteur_totale(), pas))
    e = monde.emprise
    x, y = np.meshgrid(np.arange(e.xmin, e.xmax, pas_sol), np.arange(e.ymin, e.ymax, pas_sol))
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


# ---------------------------------------------------------------- sol en plan (bogue n° 3)

PLAN_DU_27_10 = [0.0009, -0.0101, -1.271]        # plan du sol mesuré sur le scan du 27/10 : 0,58°


def incliner(points, plan=PLAN_DU_27_10):
    """Le nuage d'un sol plat (z = 0) posé sur un sol penché : z + a·x + b·y + c (x, y inchangés, comme
    le repère map du vrai G1 : on ajoute le plan, sans tourner)."""
    p = np.asarray(points, dtype=float).copy()
    p[:, 2] += plan[0] * p[:, 0] + plan[1] * p[:, 1] + plan[2]
    return p


def test_trouver_sol_plan_incline():
    alea = np.random.default_rng(3)
    sol = np.column_stack([alea.uniform(-6, 7, 20000), alea.uniform(-16, 4, 20000), alea.normal(0, 0.01, 20000)])
    meubles = np.column_stack([alea.uniform(-6, 7, 8000), alea.uniform(-16, 4, 8000), alea.uniform(0.3, 2.8, 8000)])
    trouve = S.trouver_sol(incliner(np.vstack([sol, meubles])))
    assert trouve["methode"] == "ransac" and trouve["points"] > 15000
    assert trouve["plan"] == pytest.approx(PLAN_DU_27_10, abs=2e-3)
    assert trouve["inclinaison_deg"] == pytest.approx(0.58, abs=0.03)
    assert S.trouver_sol(incliner(np.vstack([sol, meubles]))) == trouve          # graine fixe : même résultat
    h = S.hauteurs(incliner(sol), trouve["plan"])
    assert np.percentile(np.abs(h), 95) < 0.03                                    # le sol revient à z = 0
    assert S.trouver_sol(meubles, sol=-1.2)["plan"] == [0.0, 0.0, -1.2]           # niveau imposé
    sans_sol = S.trouver_sol(meubles[:50])                                        # trop peu de points
    assert sans_sol["methode"] == "centile" and sans_sol["inclinaison_deg"] == 0.0
    assert "raison" not in trouve
    with pytest.raises(S.ErreurSol):
        S.trouver_sol(np.zeros((0, 3)))


def test_sol_trop_penche_pris_a_plat():
    """Revue de la vague 5 : un scan court qui a vu peu de sol a donné un plan penché de 6,8° (hauteurs
    fausses de plusieurs dizaines de centimètres). Au-delà de 3°, le sol est pris à plat au plus bas des points
    (1er centile, comme un sol pas vu), et « raison » le dit ; un sol penché de 0,58° (le vrai G1) reste en plan."""
    alea = np.random.default_rng(5)
    sol = np.column_stack([alea.uniform(0, 2, 1200), alea.uniform(0, 1.5, 1200), alea.normal(0, 0.005, 1200)])
    penche = incliner(sol, [0.12, -0.02, 0.83])                                   # 6,9° : un sol mal vu
    trouve = S.trouver_sol(penche)
    assert trouve["methode"] == "centile" and trouve["inclinaison_deg"] == 0.0
    assert "penché de 6.9°" in trouve["raison"] and "pris à plat" in trouve["raison"]
    assert trouve["plan"][2] == pytest.approx(float(np.percentile(penche[:, 2], 1.0)), abs=1e-6)
    assert S.trouver_sol(incliner(sol))["methode"] == "ransac"                   # 0,58° : gardé
    assert S.trouver_sol(penche, inclinaison_acceptee=10.0)["methode"] == "ransac"


def test_bogue_sol_incline_damier(monde_demo):
    """Bogue n° 3 : sol penché de 0,58° (1 cm par mètre en y) et 1,27 m sous l'origine, comme le vrai G1.
    Avec un seul niveau (le 1er centile), le haut du sol entre dans la tranche 0,1–1,5 m : le damier.
    Avec le plan du sol, la carte est celle du monde. (Sol vu tous les 2,5 cm : plusieurs points par pixel de
    5 cm, comme le sol du vrai scan, où une case de la carte est occupée dès 2 points.)"""
    points = incliner(nuage_synthetique(monde_demo, pas=0.05, pas_sol=0.025))
    e = monde_demo.emprise
    emprise = (e.xmin, e.ymin, e.xmax, e.ymax)
    info_ref, carte_ref = carte_reference(monde_demo)
    info, carte, sol = carte2d.fabriquer_carte(points, emprise)
    assert sol["methode"] == "ransac" and 0.5 <= sol["inclinaison_deg"] <= 0.7
    bonne = carte2d.comparer(info, carte, info_ref, carte_ref)
    assert bonne["recouvrement"] >= 0.95, bonne
    # l'ancienne façon : un seul niveau
    info, ancienne, _ = carte2d.fabriquer_carte(points, emprise, sol=carte2d.estimer_sol(points))
    damier = carte2d.comparer(info, ancienne, info_ref, carte_ref)
    assert damier["recouvrement"] < 0.6 and (ancienne == 0).sum() > 3 * (carte == 0).sum(), damier


@pytest.mark.parametrize("sol", [0.0, -1.2])
def test_carte_du_nuage_synthetique(monde_demo, sol):
    """Le nuage des murs et objets donne la carte du monde : au moins 80 % de recouvrement."""
    points = nuage_synthetique(monde_demo, sol=sol, bruit=300)
    e = monde_demo.emprise
    info, carte, sol_trouve = carte2d.fabriquer_carte(points, (e.xmin, e.ymin, e.xmax, e.ymax))
    assert sol_trouve["niveau"] == pytest.approx(sol, abs=0.05) and sol_trouve["inclinaison_deg"] < 0.1
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


def ecrire_faux_bag(dossier, monde, poses, pieton=None, frequence=5.0, portee=8.0, comme_le_g1=False,
                    decalage_odom=0.0, plan_sol=None):
    """ros2 bag avec /points (repère lidar, 1,2 m au-dessus du robot), /odom et /tf_static.

    Chaque nuage contient les points du nuage synthétique visibles depuis le LiDAR. pieton :
    fonction t → (x, y) d'un piéton (cylindre de points) qui marche pendant l'enregistrement.

    comme_le_g1 (vague 5, scan du 27/10) : les nuages sont déjà placés dans le repère « map » et ont un
    horodatage nul ; l'odométrie (map → base_link) donne la position du LiDAR. decalage_odom : secondes
    ajoutées aux horodatages de l'odométrie (horloge du robot : −138 s le 27/10), l'heure du bag restant
    celle du PC. plan_sol : le sol devient ce plan [a, b, c] (z + a·x + b·y + c, sans tourner).
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

    def sol(points):
        return points if plan_sol is None else incliner(points, plan_sol)

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
            o.header.frame_id, o.child_frame_id = ("map" if comme_le_g1 else "odom"), "base_link"
            o.header.stamp = instant(t + dt + decalage_odom)
            position = sol(np.array([[x, y, 1.2 if comme_le_g1 else 0.0]]))[0]
            o.pose.pose.position.x, o.pose.pose.position.y, o.pose.pose.position.z = (float(v) for v in position)
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
        nuage = PointCloud2()
        if comme_le_g1:                   # déjà dans map, horodatage nul (Time() vaut 0)
            local = sol(visibles).astype(np.float32)
            nuage.header.frame_id = "map"
        else:                             # monde → repère du LiDAR (robot en x, y, theta ; LiDAR 1,2 m plus haut)
            c, s = math.cos(theta), math.sin(theta)
            d = visibles - np.array([x, y, 1.2])
            local = np.column_stack([c * d[:, 0] + s * d[:, 1], -s * d[:, 0] + c * d[:, 1], d[:, 2]]).astype(np.float32)
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
    assert infos["base_de_temps"] == "message" and infos["recus"] == infos["nuages"]
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


# ---------------------------------------------------------------- bogues n° 1 et 2 : comme le scan du 27/10

def pieton_nord(t):
    u = (t * 1.0) % 36.0
    return (6.0 + (u if u < 18 else 36 - u), 13.8)


@pytest.fixture(scope="module")
def bag_g1(tmp_path_factory, monde_demo):
    """Le faux bag « comme le G1 » : nuages dans map à horodatage nul, odométrie décalée de −138 s, sol
    penché de 0,58° et 1,27 m sous l'origine, un piéton dans le couloir nord."""
    pytest.importorskip("rosbag2_py")
    dossier = tmp_path_factory.mktemp("bag_g1") / "scan"
    ecrire_faux_bag(dossier, monde_demo, parcours_couloirs(), pieton=pieton_nord, comme_le_g1=True,
                    decalage_odom=-138.0, plan_sol=PLAN_DU_27_10)
    return dossier


def test_base_de_temps():
    hn, rn = np.zeros(10), np.arange(10.0) + 1000.0          # nuages : horodatage nul
    ho, ro = np.arange(10.0) + 862.0, np.arange(10.0) + 1000.0
    assert carte3d.choisir_base_de_temps(hn, rn, ho, ro)[0] == "reception"
    assert carte3d.choisir_base_de_temps(ro - 5, rn, ho, ro)[0] == "reception"        # 133 s d'écart
    assert carte3d.choisir_base_de_temps(ro - 0.03, rn, ro - 0.02, ro)[0] == "message"   # même horloge
    assert carte3d.choisir_base_de_temps(ro - 1.0, rn, ro - 0.2, ro)[0] == "reception"   # 0,8 s d'écart
    assert carte3d.choisir_base_de_temps(np.zeros(0), np.zeros(0), ho, ro)[0] == "message"


def test_entete_cdr():
    from rclpy.serialization import serialize_message
    from sensor_msgs.msg import PointCloud2
    msg = PointCloud2()
    msg.header.frame_id = "map"
    msg.header.stamp.sec, msg.header.stamp.nanosec = 1793, 500000000
    assert carte3d.entete_cdr(serialize_message(msg)) == (1793.5, "map")


def test_bogue_horloge_nuages_comme_le_g1(bag_g1, monde_demo):
    """Bogue n° 1 : aucun nuage n'est jeté, chacun a la pose reçue au même instant (à 0,1 s près), et la
    carte est celle du monde. Avant : appariés par horodatage, tous les nuages tombaient hors de la
    trajectoire (138 s d'écart)."""
    points, infos = carte3d.assembler(bag_g1)
    assert infos["base_de_temps"] == "reception" and "horodatage nul" in infos["raison_base"]
    assert infos["recus"] == len(parcours_couloirs()) == infos["nuages"] and infos["ignores"] == 0
    assert infos["ecart_pose_max_s"] <= 0.1 and infos["sans_rayons"] == 0 and infos["avertissements"] == []
    assert 0.5 <= infos["sol"]["inclinaison_deg"] <= 0.7
    e = monde_demo.emprise
    info, carte, _ = carte2d.fabriquer_carte(points, (e.xmin, e.ymin, e.xmax, e.ymax), plan=infos["sol"])
    info_ref, carte_ref = carte_reference(monde_demo)
    r = carte2d.comparer(info, carte, info_ref, carte_ref)
    assert r["recouvrement"] >= 0.80, r
    # Bogue n° 2 : avec la bonne origine des rayons, le piéton du couloir nord est retiré
    assert infos["retires_mobiles"] > 0
    for x in np.arange(10.0, 20.0, 0.5):
        c, l = monde_vers_pixel(x, 13.8, info)
        assert carte[l, c] == 254, f"trace du piéton en ({x}, 13.8)"


def test_bogue_horloge_ancienne_facon(bag_g1, monde_demo):
    """L'ancienne façon (horodatages, base « message » imposée) : aucune pose à moins de 1 s de chaque nuage.
    Les nuages sont gardés (ils sont déjà dans map), mais sans rayons : le piéton laisse sa trace."""
    points, infos = carte3d.assembler(bag_g1, base_de_temps="message")
    assert infos["sans_rayons"] == infos["recus"] and infos["ignores"] == 0
    assert any("passants ne sont pas retirés" in a for a in infos["avertissements"])
    e = monde_demo.emprise
    info, carte, _ = carte2d.fabriquer_carte(points, (e.xmin, e.ymin, e.xmax, e.ymax), plan=infos["sol"])
    traces = sum(carte[monde_vers_pixel(x, 13.8, info)[1], monde_vers_pixel(x, 13.8, info)[0]] == 0
                 for x in np.arange(10.0, 20.0, 0.5))
    assert traces >= 5


def test_bogue_horloge_nuages_dans_le_capteur(tmp_path, monde_demo):
    """Nuages dans le repère du capteur, horodatage nul, odométrie décalée : sans la base « reception »,
    aucun ne pourrait être placé (refus clair) ; avec, tous le sont."""
    pytest.importorskip("rosbag2_py")
    poses = parcours_couloirs()[:120]
    ecrire_faux_bag(tmp_path / "scan", monde_demo, poses, decalage_odom=-138.0)
    # horodatages des nuages remis à zéro dans ce bag : on réécrit seulement les nuages
    import rosbag2_py
    from rclpy.serialization import deserialize_message, serialize_message
    from sensor_msgs.msg import PointCloud2
    lecteur = rosbag2_py.SequentialReader()
    lecteur.open(rosbag2_py.StorageOptions(uri=str(tmp_path / "scan"), storage_id="sqlite3"),
                 rosbag2_py.ConverterOptions("cdr", "cdr"))
    sujets = lecteur.get_all_topics_and_types()
    ecrivain = rosbag2_py.SequentialWriter()
    ecrivain.open(rosbag2_py.StorageOptions(uri=str(tmp_path / "scan0"), storage_id="sqlite3"),
                  rosbag2_py.ConverterOptions("cdr", "cdr"))
    for s in sujets:
        ecrivain.create_topic(rosbag2_py.TopicMetadata(name=s.name, type=s.type, serialization_format="cdr"))
    while lecteur.has_next():
        sujet, donnees, instant = lecteur.read_next()
        if sujet == "/points":
            msg = deserialize_message(donnees, PointCloud2)
            msg.header.stamp.sec = msg.header.stamp.nanosec = 0
            donnees = serialize_message(msg)
        ecrivain.write(sujet, donnees, instant)
    del ecrivain, lecteur
    with pytest.raises(carte3d.ErreurCarte3d, match="aucun nuage"):
        carte3d.assembler(tmp_path / "scan0", base_de_temps="message")
    points, infos = carte3d.assembler(tmp_path / "scan0")
    assert infos["base_de_temps"] == "reception" and infos["ignores"] == 0 and infos["nuages"] == len(poses)
    # même nuage qu'avec les bons horodatages
    reference, _ = carte3d.assembler(tmp_path / "scan")
    assert abs(len(points) - len(reference)) <= 0.01 * len(reference)


def test_mobiles_retires_sans_trouer_le_sol(bag_g1):
    """Retrait des passants moins agressif : le sol et le plafond des colonnes mobiles restent."""
    tous, _ = carte3d.assembler(bag_g1, retirer_mobiles=False)
    garde, infos = carte3d.assembler(bag_g1)
    sol = infos["sol"]["plan"]
    h_tous, h_garde = S.hauteurs(tous, sol), S.hauteurs(garde, sol)
    assert (np.abs(h_garde) < 0.05).sum() == (np.abs(h_tous) < 0.05).sum()      # aucun point du sol retiré
    assert len(tous) - len(garde) == infos["retires_mobiles"] > 0
    gardes = set(map(tuple, np.round(garde, 4)))
    retires = np.array([p for p in map(tuple, np.round(tous, 4)) if p not in gardes])
    h = S.hauteurs(retires, sol)
    assert h.min() >= carte3d.HAUTEURS_MOBILES[0] and h.max() <= carte3d.HAUTEURS_MOBILES[1]


def test_nuage_affichage(tmp_path, bag_g1):
    from atelier import lieu as L
    from atelier.scan import affichage
    points, infos = carte3d.assembler(bag_g1)
    base = tmp_path / "nuage_affichage"
    entete = affichage.ecrire_nuage_affichage(base, points, infos["sol"], "scan", session="2026-10-27_14h22",
                                              etage="rdc", mobiles_retires=infos["retires_mobiles"])
    relus, relu = L.lire_nuage(base)
    assert relu == entete and len(relus) == len(points) == entete["points"]
    assert np.array_equal(relus[:, :2], points[:, :2].astype(np.float32))           # x, y : repère map, tels quels
    h = relus[:, 2]
    assert abs(float(np.median(h[np.abs(h) < 0.1]))) < 0.02                       # sol à z = 0
    assert entete["sol"]["plan"] == infos["sol"]["plan"] and entete["sol"]["methode"] == "ransac"
    assert 0.5 <= entete["sol"]["inclinaison_deg"] <= 0.7 and entete["mobiles_retires"] == infos["retires_mobiles"]
    plus_gros = affichage.points_affichage(points, infos["sol"]["plan"], grille=0.1)
    assert len(plus_gros) < len(points) / 2


def test_commande_g1_carte_3d(tmp_path, faux_bag):
    import os
    import subprocess
    lieu = copier_lieu(LIEU_DEMO, tmp_path / "lieux" / "essai")
    env = dict(os.environ, ATELIER_LIEUX=str(tmp_path / "lieux"))
    r = subprocess.run([str(RACINE / "bin" / "g1-carte-3d"), "--lieu", "essai", "--etage", "rdc",
                        "--enregistrement", str(faux_bag)], env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    assert chemin_pcd(lieu, "rdc").is_file() and "g1-carte-2d" in r.stdout
