"""Tests de la carte extrudée (atelier.monde.extrusion, vague 5, section 12.5 du plan) : décomposition en
rectangles, maillage STL, monde maillé d'un étage scanné (generer), SDF et monde simulé, et, si Gazebo
Fortress est là, chargement du maillage (le LiDAR le voit, un objet tombé dessus y reste).

  ~/robot-g1/.venv-projet/bin/python -m pytest ~/robot-g1/atelier/tests/test_monde_extrusion.py -v

Les tests travaillent sur des copies de lieux/demo (jamais lieux/demo).
"""
import os
import re
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET

import numpy as np
import pytest
import yaml

import atelier
from atelier import lieu as L
from atelier import monde as M
from atelier.monde import extrusion as X
from atelier.monde.sdf import sdf_simulation, texte_sdf, uri_absolue

DEMO = atelier.RACINE / "lieux" / "demo"
IGN = shutil.which("ign")
sans_gazebo = pytest.mark.skipif(IGN is None, reason="Gazebo Fortress (commande ign) absent")


def couvrir(rects, forme):
    """Nombre de rectangles qui couvrent chaque pixel."""
    compte = np.zeros(forme, dtype=int)
    for c0, l0, c1, l1 in rects:
        compte[l0:l1 + 1, c0:c1 + 1] += 1
    return compte


# ---------------------------------------------------------------- rectangles et nettoyage

@pytest.mark.parametrize("graine", range(5))
def test_rectangles_exacts_sans_recouvrement(graine):
    alea = np.random.default_rng(graine)
    occupe = alea.random((60, 80)) < 0.35
    occupe[10:30, 5:40] = True                    # un grand bloc : peu de rectangles
    rects = X.rectangles(occupe)
    compte = couvrir(rects, occupe.shape)
    assert ((compte == 1) == occupe).all() and compte.max() == 1
    assert all(c0 <= c1 and l0 <= l1 for c0, l0, c1, l1 in rects)


def test_rectangles_d_un_mur_et_d_une_ligne():
    occupe = np.zeros((10, 12), dtype=bool)
    occupe[2:8, 3:5] = True                       # un mur vertical de 2 pixels : un seul rectangle
    assert X.rectangles(occupe) == [(3, 2, 4, 7)]
    occupe[0, :] = True
    assert len(X.rectangles(occupe)) == 2
    assert X.rectangles(np.zeros((4, 4), dtype=bool)) == []
    assert X.plages([0, 1, 1, 0, 1]) == [(1, 2), (4, 4)]


def test_fermer_et_petites_taches():
    occupe = np.zeros((20, 20), dtype=bool)
    occupe[5:15, 5] = True
    occupe[5:15, 7] = True                        # deux traits séparés d'un pixel : la fermeture les joint
    occupe[18, 18] = True                         # une tache isolée
    ferme = X.fermer(occupe)
    assert ferme[5:15, 5:8].all() and (ferme | ~occupe).all()      # fermé contient l'original
    assert ferme.sum() < occupe.sum() + 15                         # sans grossir le reste
    propre = X.nettoyer(occupe)
    assert not propre[18, 18] and propre[5:15, 5:8].all()
    assert X.fermer(np.ones((4, 4), dtype=bool)).all()             # rien de rongé au bord de l'image
    assert X.sans_petites_taches(occupe, 1).sum() == occupe.sum()


# ---------------------------------------------------------------- maillage et STL

def test_boite_d_un_pixel_en_metres():
    info = L.InfoCarte(image="c.pgm", resolution=0.05, origin=(-1.0, 2.0, 0.0), largeur=40, hauteur=20)
    boites = X.boites_metres([(3, 4, 3, 4)], info)
    cx, cy = L.pixel_vers_monde(3, 4, info)
    assert boites[0] == pytest.approx([cx - 0.025, cy - 0.025, cx + 0.025, cy + 0.025])
    assert boites[0][1] == pytest.approx(2.0 + (20 - 5) * 0.05)            # ligne 0 = y maximal


def test_maillage_et_stl(tmp_path):
    info = L.InfoCarte(image="c.pgm", resolution=0.05, origin=(0.0, 0.0, 0.0), largeur=100, hauteur=60)
    image = np.full((60, 100), 254, dtype=np.uint8)
    image[10:12, 10:90] = 0                       # un mur de 4 m
    image[20:40, 50:52] = 0                       # un autre, d'un mètre
    m = X.maillage_carte(info, image, hauteur=1.5)
    assert m["boites"] == 2 and m["pixels"] == 200
    assert len(m["faces"]) == X.TRIANGLES_PAR_BOITE * m["boites"]
    n = X.ecrire_stl(tmp_path / "carte.stl", m["sommets"], m["faces"])
    assert n == 24 and (tmp_path / "carte.stl").stat().st_size == 84 + 50 * 24
    triangles = X.lire_stl(tmp_path / "carte.stl")
    sommets = np.concatenate([triangles["a"], triangles["b"], triangles["c"]])
    assert sommets[:, 2].min() == 0.0 and sommets[:, 2].max() == pytest.approx(1.5)
    assert np.linalg.norm(triangles["normale"], axis=1) == pytest.approx(np.ones(24))
    # le mur de 4 m : de x = 0,5 à 4,5 m, y de 2,4 à 2,5 m (lignes 10 et 11 sous y max = 3 m)
    xs, ys = sommets[:, 0], sommets[:, 1]
    assert xs.min() == pytest.approx(0.5) and xs.max() == pytest.approx(4.5)
    assert ys.max() == pytest.approx(2.5)
    # chaque boîte est fermée : chaque arête est partagée par deux triangles
    aretes = {}
    for t in triangles:
        coins = [tuple(np.round(t[k], 6)) for k in ("a", "b", "c")]
        for i in range(3):
            cle = tuple(sorted((coins[i], coins[(i + 1) % 3])))
            aretes[cle] = aretes.get(cle, 0) + 1
    assert set(aretes.values()) == {2}
    with pytest.raises(L.ErreurLieu, match="au moins"):
        X.maillage_carte(info, image, hauteur=0.1)
    (tmp_path / "court.stl").write_bytes(b"x" * 90)
    with pytest.raises(L.ErreurLieu, match="tronqué|trop court"):
        X.lire_stl(tmp_path / "court.stl")


# ---------------------------------------------------------------- étage scanné : generer, monde, SDF

@pytest.fixture
def scanne(tmp_path):
    """Copie du demo dont l'étage rdc utilise une carte « du scan » (celle du monde) et n'a plus de monde."""
    dossier = L.copier_lieu(DEMO, tmp_path / "demo")
    M.generer(dossier, "rdc")
    fiche = L.charger_fiche(dossier)
    fiche.etage("rdc").source_carte = "scan"
    L.enregistrer_fiche(fiche)
    L.chemin_monde(dossier, "rdc").unlink()
    L.chemin_sdf(dossier, "rdc").unlink()
    return dossier


def test_generer_un_etage_scanne_sans_monde(scanne):
    carte_avant = L.chemin_carte(scanne, "rdc").read_bytes()
    r = M.generer(scanne, "rdc")
    assert r.maillage == L.chemin_maillage(scanne, "rdc") and r.maillage.is_file() and r.triangles > 100
    assert L.chemin_carte(scanne, "rdc").read_bytes() == carte_avant              # la carte du scan reste
    monde = L.charger_monde(scanne, "rdc")
    assert monde.carte_extrudee == L.CarteExtrudee("rdc_carte.stl", 1.5)
    assert monde.murs == [] and monde.objets == [] and monde.pietons == []
    principal = L.pose_principale(scanne)
    assert (monde.depart_robot.x, monde.depart_robot.y) == pytest.approx((principal.x, principal.y))
    xmin, ymin, xmax, ymax = L.bornes_carte(L.charger_info_carte(L.chemin_carte(scanne, "rdc")))
    assert monde.emprise.xmin <= xmin + 1e-3 and monde.emprise.xmax >= xmax - 1e-3
    assert any("monde minimal" in m for m in r.remarques) and "carte extrudée" in r.texte()
    sdf = ET.parse(L.chemin_sdf(scanne, "rdc")).getroot().find("world")
    modeles = [m.get("name") for m in sdf.findall("model")]
    assert modeles == ["sol", L.MODELE_CARTE_EXTRUDEE]
    uris = [u.text for u in sdf.iter("uri")]
    assert uris == ["rdc_carte.stl", "rdc_carte.stl"]                             # relative au .sdf
    rapport = L.valider_lieu(scanne)
    assert rapport.erreurs == [] and not any("carte_extrudee" in a for a in rapport.avertissements)
    # le maillage couvre les obstacles de la carte : chaque pixel occupé est sous une boîte
    triangles = X.lire_stl(r.maillage)
    assert len(triangles) == r.triangles


def test_generer_garde_le_monde_et_la_hauteur(scanne):
    M.generer(scanne, "rdc")
    monde = L.charger_monde(scanne, "rdc")
    monde.pietons = [L.Pieton("passant", [(3.0, 7.0), (10.0, 7.0)], 1.0, True)]
    L.enregistrer_monde(scanne, "rdc", monde)
    r = M.generer(scanne, "rdc", hauteur_carte=2.0)
    monde = L.charger_monde(scanne, "rdc")
    assert monde.carte_extrudee.hauteur == 2.0 and [p.id for p in monde.pietons] == ["passant"]
    sommets = X.lire_stl(r.maillage)["c"]
    assert sommets[:, 2].max() == pytest.approx(2.0)
    M.generer(scanne, "rdc")                                                       # la hauteur reste celle du monde
    assert L.charger_monde(scanne, "rdc").carte_extrudee.hauteur == 2.0
    with pytest.raises(L.ErreurLieu):
        M.generer(scanne, "inconnu")


def test_sdf_d_un_monde_dessine_inchange(tmp_path):
    """Un monde dessiné, sans carte_extrudee, donne le même .sdf qu'avant la vague 5, octet pour octet."""
    monde = L.charger_monde(DEMO, "rdc")
    assert monde.carte_extrudee is None
    texte = texte_sdf(monde, nom="rdc", source="rdc.monde.yaml")
    assert "carte_du_scan" not in texte and "<mesh>" not in texte
    reference = DEMO / "mondes" / "rdc.sdf"
    if reference.is_file():
        assert texte == reference.read_text(encoding="utf-8")


def test_monde_simule_rend_l_uri_absolue(scanne):
    M.generer(scanne, "rdc")
    monde = L.charger_monde(scanne, "rdc")
    monde.pietons = [L.Pieton("passant", [(3.0, 7.0), (10.0, 7.0)], 1.0, True)]
    L.enregistrer_monde(scanne, "rdc", monde)
    M.generer(scanne, "rdc")
    sdf = L.chemin_sdf(scanne, "rdc")
    texte, ids = sdf_simulation(sdf.read_text(encoding="utf-8"), monde, sdf.parent)
    assert ids == ["passant"]
    uris = [u.text for u in ET.fromstring(texte.split("\n", 2)[2]).iter("uri")]
    assert uris == [str(sdf.parent / "rdc_carte.stl")] * 2
    assert uri_absolue("model://x/y.stl", "/d") == "model://x/y.stl"
    assert uri_absolue("/abs/y.stl", "/d") == "/abs/y.stl" and uri_absolue("y.stl", "/d") == "/d/y.stl"


def test_carte_sans_obstacle(scanne):
    info, image = L.charger_carte(L.chemin_carte(scanne, "rdc"))
    image[image == 0] = 254
    L.enregistrer_carte(L.chemin_carte(scanne, "rdc"), info, image)
    r = M.generer(scanne, "rdc")
    assert r.maillage is None and any("rien à extruder" in m for m in r.remarques)


def test_commande_generer_hauteur(scanne):
    env = dict(os.environ, ATELIER_LIEUX=str(scanne.parent))
    r = subprocess.run([str(atelier.RACINE / "bin" / "g1-monde"), "generer", "--lieu", "demo", "--etage", "rdc",
                        "--hauteur-carte", "1.8"], env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "carte extrudée" in r.stdout
    assert yaml.safe_load(L.chemin_monde(scanne, "rdc").read_text())["carte_extrudee"] == \
        {"fichier": "rdc_carte.stl", "hauteur": 1.8}


# ---------------------------------------------------------------- dans Gazebo (sans fenêtre)

CAPTEUR = """<model name="capteur_essai"><static>true</static><pose>{x} {y} 1.0 0 0 0</pose><link name="lien">
  <sensor name="lidar" type="gpu_lidar"><topic>{sujet}</topic><update_rate>10</update_rate><always_on>true</always_on>
    <lidar><scan><horizontal><samples>721</samples><resolution>1</resolution>
      <min_angle>-3.14159265</min_angle><max_angle>3.14159265</max_angle></horizontal>
      <vertical><samples>1</samples><resolution>1</resolution><min_angle>0</min_angle><max_angle>0</max_angle></vertical></scan>
    <range><min>0.1</min><max>30</max><resolution>0.01</resolution></range></lidar></sensor></link></model>
<model name="boite_essai"><pose>{bx} {by} 2.5 0 0 0</pose><link name="corps"><inertial><mass>5</mass></inertial>
  <collision name="c"><geometry><box><size>0.3 0.3 0.3</size></box></geometry></collision>
  <visual name="v"><geometry><box><size>0.3 0.3 0.3</size></box></geometry></visual></link></model>
</world>"""


@sans_gazebo
def test_maillage_dans_gazebo(scanne):
    """Le monde maillé se charge sans erreur ; un gpu_lidar posé à l'accueil (2,5 ; 10) voit le bloc de l'est
    du hall à la bonne distance (le visuel du maillage est rendu) ; une boîte tombée sur un mur du maillage y
    reste à 1,5 m + 0,15 m (la collision du maillage marche)."""
    from atelier.tests.test_monde_sdf import arreter, distance_vers, erreurs_gazebo, lancer_gazebo, lire_scans
    M.generer(scanne, "rdc")
    sdf = L.chemin_sdf(scanne, "rdc")
    # une boîte au-dessus d'un mur du demo (mur ouest du couloir, bloc_ouest vers x = 4,925)
    info, image = L.charger_carte(L.chemin_carte(scanne, "rdc"))
    c, ligne = L.monde_vers_pixel(5.0, 10.0, info)
    assert image[ligne, c] == 0, "le point choisi pour la boîte devrait être un mur de la carte"
    essai = sdf.with_name("essai.sdf")
    sujet = "/atelier_extrusion_test/lidar"
    essai.write_text(sdf.read_text().replace("</world>", CAPTEUR.format(x=2.5, y=10.0, sujet=sujet, bx=5.0, by=10.0)))
    partition = f"v5_scan_extrusion_{os.getpid()}"
    processus = lancer_gazebo(essai, partition)
    try:
        env = dict(os.environ, IGN_PARTITION=partition)
        scans = []
        fin = time.time() + 60
        while time.time() < fin and not scans:
            lecture = subprocess.run([IGN, "topic", "-e", "-t", sujet, "-n", "2"], env=env, text=True,
                                     capture_output=True, timeout=30)
            scans += lire_scans(lecture.stdout)
        time.sleep(2.0)                                           # la boîte a fini de tomber
        pose = subprocess.run([IGN, "model", "-m", "boite_essai", "-p"], env=env, text=True, capture_output=True,
                              timeout=30).stdout
    finally:
        sortie = arreter(processus)
    assert erreurs_gazebo(sortie) == [], sortie[-2000:]
    assert scans, "aucune mesure du LiDAR : le rendu sans fenêtre (EGL) fonctionne-t-il ?\n" + sortie[-2000:]
    _, distances = scans[-1]
    assert distance_vers(distances, 0) == pytest.approx(2.425, abs=0.08)        # bloc_ouest, côté hall
    xyz = re.findall(r"\[(-?[\d.]+) (-?[\d.]+) (-?[\d.]+)\]", pose)
    assert xyz and float(xyz[0][2]) == pytest.approx(1.65, abs=0.03), pose
