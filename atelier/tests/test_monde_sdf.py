"""Tests du monde Gazebo généré (atelier.monde.sdf) et des trajectoires des piétons.

Les tests Gazebo lancent « ign gazebo -s -r --headless-rendering » (serveur seul, sans fenêtre),
dans une partition à eux (IGN_PARTITION), et tuent toujours le processus à la fin.
Ils sont sautés si la commande ign est absente.
"""
import math
import os
import re
import shutil
import signal
import subprocess
import time
import xml.etree.ElementTree as ET

import pytest

import atelier
from atelier import lieu as L
from atelier import monde as M
from atelier.lieu import Emprise, Monde, Objet, Pieton, Pose
from atelier.monde.pietons import DEMI_EPAISSEUR, DEMI_LARGEUR, NOM_MAILLAGE, texte_maillage

DEMO = atelier.RACINE / "lieux" / "demo"
IGN = shutil.which("ign")
sans_gazebo = pytest.mark.skipif(IGN is None, reason="Gazebo Fortress (commande ign) absent")


@pytest.fixture
def demo(tmp_path):
    """Dossier d'une copie du lieu demo, déjà généré."""
    dossier = L.copier_lieu(DEMO, tmp_path / "demo")
    M.generer(dossier, "rdc")
    return dossier


@pytest.fixture
def monde_demo(demo):
    return L.charger_monde(demo, "rdc")


@pytest.fixture
def arbre(demo):
    return ET.parse(L.chemin_sdf(demo, "rdc")).getroot()


def nombres(texte):
    return [float(v) for v in texte.split()]


# ---------------------------------------------------------------- structure du SDF

def test_entete_et_plugins(arbre):
    assert arbre.tag == "sdf" and arbre.get("version") == "1.9"
    monde = arbre.find("world")
    assert monde.get("name") == "rdc"
    plugins = {p.get("name").split("::")[-1]: p for p in monde.findall("plugin")}
    assert set(plugins) == {"Physics", "SceneBroadcaster", "UserCommands", "Sensors"}
    assert plugins["Sensors"].findtext("render_engine") == "ogre2"
    assert plugins["Sensors"].get("filename") == "ignition-gazebo-sensors-system"
    assert monde.find("light") is not None


def test_nombre_de_modeles_egal_aux_murs_et_objets(arbre, monde_demo):
    modeles = arbre.find("world").findall("model")
    assert len(modeles) == len(monde_demo.murs) + len(monde_demo.objets) + 1      # + le sol
    noms = [m.get("name") for m in modeles]
    assert sorted(noms) == sorted([e.id for e in (*monde_demo.murs, *monde_demo.objets)] + ["sol"])
    assert all(m.findtext("static") == "true" for m in modeles)
    assert "g1_proxy" not in noms        # le robot est ajouté par g1_sim


def test_un_actor_par_pieton(arbre, monde_demo):
    acteurs = arbre.find("world").findall("actor")
    assert [a.get("name") for a in acteurs] == [p.id for p in monde_demo.pietons]
    for acteur in acteurs:
        assert acteur.findtext("skin/filename") == NOM_MAILLAGE
        script = acteur.find("script")
        assert script.findtext("loop") == "true" and script.findtext("auto_start") == "true"
        assert len(script.findall("trajectory/waypoint")) >= 3


def test_maillage_du_pieton_ecrit_et_lisible(demo):
    chemin = L.chemin_sdf(demo, "rdc").parent / NOM_MAILLAGE
    assert chemin.read_text() == texte_maillage()
    racine = ET.fromstring(texte_maillage().split("\n", 2)[2])
    espace = "{http://www.collada.org/2005/11/COLLADASchema}"
    assert racine.find(f"{espace}library_controllers/{espace}controller/{espace}skin") is not None
    assert racine.find(f"{espace}library_animations/{espace}animation") is not None


def test_pas_de_maillage_sans_pieton(tmp_path):
    dossier = L.copier_lieu(DEMO, tmp_path / "demo")
    monde = L.charger_monde(dossier, "rdc")
    monde.pietons = []
    L.enregistrer_monde(dossier, "rdc", monde)
    (dossier / "mondes" / NOM_MAILLAGE).unlink(missing_ok=True)      # copié avec le demo déjà généré
    M.generer(dossier, "rdc")
    assert not (dossier / "mondes" / NOM_MAILLAGE).exists()
    assert ET.parse(L.chemin_sdf(dossier, "rdc")).getroot().find("world/actor") is None


def test_mur_oriente_le_long_du_segment(arbre, monde_demo):
    modeles = {m.get("name"): m for m in arbre.find("world").findall("model")}
    for mur in monde_demo.murs:
        x, y, z, roulis, tangage, lacet = nombres(modeles[mur.id].findtext("pose"))
        taille = nombres(modeles[mur.id].findtext("link/collision/geometry/box/size"))
        assert (x, y, z) == pytest.approx((*mur.centre, mur.hauteur / 2), abs=1e-6)
        assert (roulis, tangage) == (0, 0)
        assert math.cos(lacet - mur.cap) == pytest.approx(1, abs=1e-9)
        assert taille == pytest.approx([mur.longueur, mur.epaisseur, mur.hauteur], abs=1e-6)


def test_objets_de_chaque_type():
    monde = Monde(Emprise(0, 0, 10, 10), Pose(1, 1, 0), objets=[
        Objet.boite("caisse", (2, 2), (1.2, 0.6, 0.75), 0.5),
        Objet.cylindre("poteau", (4, 4), 0.2, 2.5),
        Objet.meuble("chaise", "chaise", (5, 5), 1.57),
        Objet.meuble("table", "table", (6, 6)),
        Objet.meuble("banc", "banc", (7, 7)),
        Objet.meuble("poubelle", "poubelle", (8, 8))])
    modeles = {m.get("name"): m for m in ET.fromstring(M.texte_sdf(monde, "essai").split("\n", 3)[3]).iter("model")}
    assert nombres(modeles["caisse"].findtext("pose")) == pytest.approx([2, 2, 0.375, 0, 0, 0.5])
    assert nombres(modeles["caisse"].findtext("link/visual/geometry/box/size")) == pytest.approx([1.2, 0.6, 0.75])
    assert modeles["poteau"].findtext("link/visual/geometry/cylinder/radius") == "0.2"
    assert modeles["poteau"].findtext("link/visual/geometry/cylinder/length") == "2.5"
    # Les meubles tiennent dans l'encombrement du contrat (longueur × largeur × hauteur)
    for nom in ("chaise", "table", "banc"):
        d = L.MODELES_MOBILIER[nom]
        xs, ys, zs = [], [], []
        for visuel in modeles[nom].iter("visual"):
            px, py, pz = nombres(visuel.findtext("pose"))[:3]
            lx, ly, lz = nombres(visuel.findtext("geometry/box/size"))
            xs += [px - lx / 2, px + lx / 2]
            ys += [py - ly / 2, py + ly / 2]
            zs += [pz - lz / 2, pz + lz / 2]
        assert (min(xs), max(xs)) == pytest.approx((-d["longueur"] / 2, d["longueur"] / 2), abs=1e-6), nom
        assert (min(ys), max(ys)) == pytest.approx((-d["largeur"] / 2, d["largeur"] / 2), abs=1e-6), nom
        assert (min(zs), max(zs)) == pytest.approx((0, d["hauteur"]), abs=1e-6), nom
        # chaque visuel a sa collision
        assert len(list(modeles[nom].iter("visual"))) == len(list(modeles[nom].iter("collision")))
    assert modeles["poubelle"].findtext("link/visual/geometry/cylinder/radius") == "0.25"


# ---------------------------------------------------------------- piétons

def test_trajectoire_aller_retour_vitesse_constante():
    p = Pieton("p", [(0, 0), (3, 0), (3, 4)], vitesse=0.5, aller_retour=True)
    points = M.points_de_passage(p)
    assert points[0] == (0.0, 0, 0, 0.0)
    assert points[-1][1:3] == (0, 0)
    assert M.duree_tour(p) == pytest.approx(2 * 7 / 0.5)
    for (t1, x1, y1, _), (t2, x2, y2, _) in zip(points, points[1:]):
        assert t2 > t1
        assert math.hypot(x2 - x1, y2 - y1) <= 0.5 + 1e-9
        assert math.hypot(x2 - x1, y2 - y1) / (t2 - t1) == pytest.approx(0.5)
    # au bout du trajet à mi-tour, puis demi-tour
    assert M.position_pieton(p, 14.0)[:2] == pytest.approx((3, 4))
    assert M.position_pieton(p, 3.0) == pytest.approx((1.5, 0, 0))
    assert M.position_pieton(p, 14.0 + 4.0) == pytest.approx((3, 2, -math.pi / 2))
    assert M.position_pieton(p, 28.0 + 3.0) == pytest.approx((1.5, 0, 0))     # tour suivant


def test_trajectoire_boucle():
    p = Pieton("p", [(0, 0), (4, 0), (4, 3)], vitesse=1.0, aller_retour=False)
    assert M.duree_tour(p) == pytest.approx(4 + 3 + 5)
    x, y, cap = M.position_pieton(p, 7 + 2.5)          # sur le retour direct en diagonale
    assert (x, y) == pytest.approx((2, 1.5))
    assert cap == pytest.approx(math.atan2(-3, -4))


def test_pieton_immobile():
    p = Pieton("p", [(2, 2), (2, 2)], vitesse=1.0, aller_retour=True)
    assert M.position_pieton(p, 12.3)[:2] == (2, 2)


def test_waypoints_du_sdf(arbre, monde_demo):
    for acteur, pieton in zip(arbre.find("world").findall("actor"), monde_demo.pietons):
        attendus = M.points_de_passage(pieton)
        points = acteur.findall("script/trajectory/waypoint")
        assert len(points) == len(attendus)
        for point, (t, x, y, cap) in zip(points, attendus):
            assert float(point.findtext("time")) == pytest.approx(t, abs=1e-5)
            assert nombres(point.findtext("pose")) == pytest.approx([x, y, 0, 0, 0, cap], abs=1e-5)


# ---------------------------------------------------------------- dans Gazebo

def lancer_gazebo(sdf, partition, iterations=None):
    """ign gazebo serveur seul et sans fenêtre, dans son propre groupe de processus."""
    env = dict(os.environ, IGN_PARTITION=partition, ROS_DOMAIN_ID="31")
    commande = [IGN, "gazebo", "-s", "-r", "--headless-rendering", "-v", "3"]
    if iterations:
        commande += ["--iterations", str(iterations)]
    return subprocess.Popen(commande + [str(sdf)], cwd=sdf.parent, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, start_new_session=True)


def arreter(processus):
    """Tue tout le groupe de processus de Gazebo, et renvoie ce qu'il a écrit."""
    if processus.poll() is None:
        os.killpg(processus.pid, signal.SIGINT)
        try:
            processus.wait(10)
        except subprocess.TimeoutExpired:
            os.killpg(processus.pid, signal.SIGKILL)
            processus.wait(5)
    return processus.stdout.read()


def erreurs_gazebo(sortie):
    return [ligne for ligne in sortie.splitlines() if "[Err]" in ligne or "[Wrn]" in ligne]


@sans_gazebo
def test_sdf_se_charge_dans_gazebo(demo):
    processus = lancer_gazebo(L.chemin_sdf(demo, "rdc"), f"atelier_monde_test_{os.getpid()}", iterations=50)
    try:
        processus.wait(60)
    except subprocess.TimeoutExpired:
        pass
    sortie = arreter(processus)
    assert processus.returncode == 0, sortie[-2000:]
    assert erreurs_gazebo(sortie) == []
    assert "Loading SDF world file" in sortie


CAPTEUR = """<model name="capteur_essai"><static>true</static><pose>{x} {y} 1.0 0 0 0</pose><link name="lien">
  <sensor name="lidar" type="gpu_lidar"><topic>{sujet}</topic><update_rate>10</update_rate><always_on>true</always_on>
    <lidar><scan><horizontal><samples>721</samples><resolution>1</resolution>
      <min_angle>-3.14159265</min_angle><max_angle>3.14159265</max_angle></horizontal>
      <vertical><samples>1</samples><resolution>1</resolution><min_angle>0</min_angle><max_angle>0</max_angle></vertical></scan>
    <range><min>0.1</min><max>30</max><resolution>0.01</resolution></range></lidar></sensor></link></model>
</world>"""


def lire_scans(sortie):
    """Messages LaserScan affichés par « ign topic -e » → liste de (temps, [distances])."""
    scans = []
    for bloc in sortie.split("header {")[1:]:
        stamp = re.search(r"stamp \{([^}]*)\}", bloc)
        sec = re.search(r"\bsec: (\d+)", stamp.group(1)) if stamp else None
        nsec = re.search(r"nsec: (\d+)", stamp.group(1)) if stamp else None
        t = (int(sec.group(1)) if sec else 0) + (int(nsec.group(1)) if nsec else 0) * 1e-9
        distances = [float(v) for v in re.findall(r"^ranges: (\S+)", bloc, re.M)]
        if distances:
            scans.append((t, distances))
    return scans


def distance_vers(distances, angle):
    """Plus courte distance mesurée à ±2° de l'angle donné (radians)."""
    n = len(distances)
    i = round((angle + math.pi) / (2 * math.pi) * (n - 1))
    return min(distances[(i + k) % n] for k in range(-4, 5))


@sans_gazebo
def test_lidar_voit_murs_et_pietons(demo, monde_demo):
    """Un gpu_lidar posé à l'accueil (2,5 ; 10) voit les murs à la bonne distance, et le piéton
    sud là où position_pieton le place à l'instant de la mesure : le maillage du piéton se
    charge dans le rendu ogre2 et suit sa trajectoire."""
    sdf = L.chemin_sdf(demo, "rdc")
    essai = sdf.with_name("essai_lidar.sdf")
    sujet = "/atelier_monde_test/lidar"
    essai.write_text(sdf.read_text().replace("</world>", CAPTEUR.format(x=2.5, y=10.0, sujet=sujet)))
    partition = f"atelier_monde_test_lidar_{os.getpid()}"
    processus = lancer_gazebo(essai, partition)
    try:
        env = dict(os.environ, IGN_PARTITION=partition)
        scans = []
        fin = time.time() + 60
        while time.time() < fin and not any(1.0 <= t <= 1.6 for t, _ in scans):
            lecture = subprocess.run([IGN, "topic", "-e", "-t", sujet, "-n", "3"], env=env, text=True,
                                     capture_output=True, timeout=30)
            scans += lire_scans(lecture.stdout)
            if any(t > 1.6 for t, _ in scans):
                break
    finally:
        sortie = arreter(processus)
    assert erreurs_gazebo(sortie) == []
    assert scans, "aucune mesure du LiDAR : le rendu sans fenêtre (EGL) fonctionne-t-il ?\n" + sortie[-2000:]
    # Murs : bloc_ouest à l'est (x = 4,925), banque d'accueil à l'ouest (x = 1,1), mur_nord_1 au nord
    t, distances = scans[-1]
    assert distance_vers(distances, 0) == pytest.approx(2.425, abs=0.05)
    assert distance_vers(distances, math.pi) == pytest.approx(1.4, abs=0.05)
    assert distance_vers(distances, math.pi / 2) == pytest.approx(4.425, abs=0.05)
    # Piéton sud, sur une mesure prise entre 1,0 et 1,6 s : il a quitté son point de départ (4 ; 7,8)
    # d'au moins 0,8 m, et il est encore en vue de l'accueil
    mesures = [(t, d) for t, d in scans if 1.0 <= t <= 1.6]
    assert mesures, f"pas de mesure entre 1,0 et 1,6 s (temps reçus : {[round(t, 2) for t, _ in scans]})"
    t, distances = mesures[0]
    pieton = next(p for p in monde_demo.pietons if p.id == "pieton_sud")
    x, y, _ = M.position_pieton(pieton, t)
    angle = math.atan2(y - 10.0, x - 2.5)
    attendue = math.hypot(x - 2.5, y - 10.0)
    mesuree = distance_vers(distances, angle)
    print(f"piéton sud à t = {t:.2f} s en ({x:.2f} ; {y:.2f}) : centre à {attendue:.2f} m, mesuré à {mesuree:.2f} m")
    assert attendue - DEMI_LARGEUR - 0.15 <= mesuree <= attendue - DEMI_EPAISSEUR + 0.15, (t, x, y, mesuree)
