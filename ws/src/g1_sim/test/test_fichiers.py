"""
Tests rapides de g1_sim, sans Gazebo.

Modèle du robot, réglages du pont, monde de test et fonctions du lancement (choix du monde,
pose de départ, URDF, commande Gazebo).
"""
import importlib.util
import math
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml

PAQUET = Path(__file__).resolve().parent.parent
MODELE = PAQUET / 'models' / 'g1_proxy' / 'model.sdf'
PONT = PAQUET / 'config' / 'pont_gz.yaml'
LANCEMENT = PAQUET / 'launch' / 'simulation.launch.py'
COULOIR = PAQUET / 'worlds' / 'couloir.sdf'


@pytest.fixture(scope='module')
def lancement():
    """Le fichier de lancement, importé comme un module Python."""
    spec = importlib.util.spec_from_file_location('simulation_launch', LANCEMENT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope='module')
def modele():
    return ET.parse(MODELE).getroot().find('model')


def _plugin(modele, nom):
    for plugin in modele.findall('plugin'):
        if plugin.get('name') == nom:
            return plugin
    raise AssertionError(f'plugin {nom} absent de model.sdf')


# ---------------------------------------------------------------- modèle du robot

@pytest.mark.skipif(shutil.which('ign') is None, reason='Gazebo (ign) absent')
@pytest.mark.parametrize('fichier', [MODELE, COULOIR])
def test_sdf_valide(fichier):
    """Le fichier est un SDF valide pour Fortress (ign sdf -k)."""
    resultat = subprocess.run(['ign', 'sdf', '-k', str(fichier)], capture_output=True, text=True)
    sortie = resultat.stdout + resultat.stderr
    assert resultat.returncode == 0 and 'Valid' in resultat.stdout, sortie


def test_taille_et_masse(modele):
    """Boîte de collision aux dimensions du G1 debout (1,32 × 0,45 × 0,20 m), au sol, 35 kg."""
    lien = modele.find('link')
    assert lien.get('name') == 'base_link'
    taille = [float(v) for v in lien.findtext('collision/geometry/box/size').split()]
    profondeur, largeur, hauteur = taille
    assert 1.28 < hauteur < 1.34 and 0.40 < largeur < 0.50 and 0.15 < profondeur < 0.25, taille
    pose = [float(v) for v in lien.findtext('collision/pose').split()]
    assert pose[2] - hauteur / 2 == pytest.approx(0.0, abs=0.005)   # le dessous est au sol
    assert float(lien.findtext('inertial/mass')) == pytest.approx(35.0)
    assert float(lien.findtext('inertial/pose').split()[2]) < hauteur / 2


def test_maillages_du_g1(modele):
    """L'apparence vient des maillages officiels du G1, tous présents et invisibles au LiDAR."""
    visuels = modele.findall('link/visual')
    assert len(visuels) >= 30
    for v in visuels:
        uri = v.findtext('geometry/mesh/uri')
        assert uri and (MODELE.parent / uri).is_file(), f'{v.get("name")} : {uri} introuvable'
        assert v.findtext('visibility_flags') == '2', v.get('name')


def test_plugins(modele):
    """Plugins VelocityControl (vx, vy, wz) et OdometryPublisher (odom → base_link, 2D)."""
    vitesse = _plugin(modele, 'ignition::gazebo::systems::VelocityControl')
    assert vitesse.get('filename') == 'ignition-gazebo-velocity-control-system'
    odometrie = _plugin(modele, 'ignition::gazebo::systems::OdometryPublisher')
    assert odometrie.get('filename') == 'ignition-gazebo-odometry-publisher-system'
    assert odometrie.findtext('odom_frame') == 'odom'
    assert odometrie.findtext('robot_base_frame') == 'base_link'
    assert odometrie.findtext('dimensions') == '2'


def test_lidar(modele):
    """gpu_lidar à la place du MID-360 : 360 × 16 points, −7° à +52°, 0,1 à 40 m, 10 Hz."""
    capteur = modele.find("link/sensor[@type='gpu_lidar']")
    assert capteur is not None
    x, y, z, roulis, tangage, lacet = [float(v) for v in capteur.findtext('pose').split()]
    assert abs(x) < 0.02 and abs(y) < 0.02 and 1.20 < z < 1.28   # dans la tête du G1
    assert (roulis, tangage, lacet) == pytest.approx((0, 0, 0))
    assert float(capteur.findtext('update_rate')) == 10
    assert capteur.findtext('ignition_frame_id') == 'lidar'
    h = capteur.find('lidar/scan/horizontal')
    v = capteur.find('lidar/scan/vertical')
    assert int(h.findtext('samples')) == 360
    # 360 échantillons sur 360° : un tous les 1°, sans doubler le point à ±180°
    ecart = float(h.findtext('max_angle')) - float(h.findtext('min_angle'))
    assert ecart == pytest.approx(2 * math.pi * 359 / 360, abs=1e-6)
    assert int(v.findtext('samples')) == 16
    assert math.degrees(float(v.findtext('min_angle'))) == pytest.approx(-7.0, abs=1e-4)
    assert math.degrees(float(v.findtext('max_angle'))) == pytest.approx(52.0, abs=1e-4)
    assert float(capteur.findtext('lidar/range/min')) == pytest.approx(0.1)
    assert float(capteur.findtext('lidar/range/max')) == pytest.approx(40.0)


# ---------------------------------------------------------------- pont ros_gz_bridge

def test_pont_sujets_du_contrat(modele):
    """pont_gz.yaml relie les 5 sujets du contrat aux sujets Gazebo du modèle."""
    regles = {r['ros_topic_name']: r for r in yaml.safe_load(PONT.read_text())}
    assert set(regles) == {'/cmd_vel', '/odom', '/tf', '/clock', '/points'}
    attendu = {
        '/cmd_vel': ('geometry_msgs/msg/Twist', 'ignition.msgs.Twist', 'ROS_TO_GZ'),
        '/odom': ('nav_msgs/msg/Odometry', 'ignition.msgs.Odometry', 'GZ_TO_ROS'),
        '/tf': ('tf2_msgs/msg/TFMessage', 'ignition.msgs.Pose_V', 'GZ_TO_ROS'),
        '/clock': ('rosgraph_msgs/msg/Clock', 'ignition.msgs.Clock', 'GZ_TO_ROS'),
        '/points': ('sensor_msgs/msg/PointCloud2', 'ignition.msgs.PointCloudPacked', 'GZ_TO_ROS'),
    }
    for sujet, (type_ros, type_gz, sens) in attendu.items():
        r = regles[sujet]
        assert (r['ros_type_name'], r['gz_type_name'], r['direction']) == (type_ros, type_gz, sens)
    # Les sujets Gazebo sont bien ceux que publie ou écoute le modèle
    vitesse = _plugin(modele, 'ignition::gazebo::systems::VelocityControl')
    odometrie = _plugin(modele, 'ignition::gazebo::systems::OdometryPublisher')
    lidar = modele.find("link/sensor[@type='gpu_lidar']")
    assert regles['/cmd_vel']['gz_topic_name'] == vitesse.findtext('topic')
    assert regles['/odom']['gz_topic_name'] == odometrie.findtext('odom_topic')
    assert regles['/tf']['gz_topic_name'] == odometrie.findtext('tf_topic')
    assert regles['/points']['gz_topic_name'] == lidar.findtext('topic') + '/points'


# ---------------------------------------------------------------- fonctions du lancement

def test_monde_du_lieu(lancement, tmp_path):
    """Sans monde:=, le lancement prend <lieu>/mondes/<etage>.sdf ; absent : erreur claire."""
    with pytest.raises(lancement.ErreurSimulation, match='g1-monde generer'):
        lancement.fichier_monde(tmp_path, 'rdc')
    (tmp_path / 'mondes').mkdir()
    shutil.copy(COULOIR, tmp_path / 'mondes' / 'rdc.sdf')
    assert lancement.fichier_monde(tmp_path, 'rdc') == tmp_path / 'mondes' / 'rdc.sdf'
    # monde:= l'emporte, et doit exister
    assert lancement.fichier_monde(tmp_path, 'rdc', str(COULOIR)) == COULOIR
    with pytest.raises(lancement.ErreurSimulation, match="n'existe pas"):
        lancement.fichier_monde(tmp_path, 'rdc', str(tmp_path / 'absent.sdf'))
    assert lancement.nom_du_monde(COULOIR) == 'couloir'


def test_depart_robot(lancement, tmp_path):
    """depart_robot : d'abord <lieu>/mondes/<etage>.monde.yaml, puis <monde>.monde.yaml, puis 0."""
    # Rien : origine
    (x, y, theta), origine = lancement.depart_robot(tmp_path, 'rdc')
    assert (x, y, theta) == (0.0, 0.0, 0.0) and 'aucun' in origine
    # Le monde.yaml posé à côté du .sdf de monde:= (cas du couloir de test)
    assert lancement.depart_robot(tmp_path, 'rdc', COULOIR)[0] == (1.0, 0.0, 0.0)
    # Le monde.yaml du lieu passe avant
    (tmp_path / 'mondes').mkdir()
    texte = (PAQUET / 'worlds' / 'couloir.monde.yaml').read_text()
    texte = texte.replace('depart_robot: {x: 1.0, y: 0.0, theta: 0.0}',
                          'depart_robot: {x: 2.5, y: -0.5, theta: 1.57}')
    (tmp_path / 'mondes' / 'rdc.monde.yaml').write_text(texte)
    assert lancement.depart_robot(tmp_path, 'rdc', COULOIR)[0] == (2.5, -0.5, 1.57)


def test_depart_robot_invalide(lancement, tmp_path):
    """Un monde.yaml sans depart_robot arrête le lancement, avec le nom du fichier."""
    (tmp_path / 'mondes').mkdir()
    (tmp_path / 'mondes' / 'rdc.monde.yaml').write_text(
        'version: 1\nemprise: {min: [0, 0], max: [5, 5]}\n')
    with pytest.raises(lancement.ErreurSimulation, match='rdc.monde.yaml'):
        lancement.depart_robot(tmp_path, 'rdc')


def test_depart_robot_demo(lancement):
    """Lieu demo, désigné par son id : le robot part de l'accueil (2,5 ; 10)."""
    pytest.importorskip('atelier.lieu')
    dossier = lancement.chemin_lieu('demo')
    if not (dossier / 'mondes' / 'rdc.monde.yaml').is_file():
        pytest.skip('lieu demo absent')
    assert lancement.depart_robot(dossier, 'rdc')[0] == (2.5, 10.0, 0.0)


def test_urdf(lancement):
    """L'URDF de robot_state_publisher reprend la position du LiDAR de model.sdf."""
    racine = ET.fromstring(lancement.description_urdf(MODELE).split('?>', 1)[1])
    joint = racine.find('joint')
    assert joint.get('type') == 'fixed'
    assert joint.find('parent').get('link') == 'base_link'
    assert joint.find('child').get('link') == 'lidar'
    xyz = [float(v) for v in joint.find('origin').get('xyz').split()]
    capteur = ET.parse(MODELE).getroot().find("model/link/sensor[@type='gpu_lidar']")
    assert xyz == pytest.approx([float(v) for v in capteur.findtext('pose').split()[:3]])


def test_commande_gazebo(lancement):
    """sans_fenetre:=true : serveur seul, sans fenêtre ; sinon serveur et fenêtre."""
    assert lancement.commande_gazebo('m.sdf', True) == [
        'ign', 'gazebo', '-s', '-r', '--headless-rendering', 'm.sdf']
    assert lancement.commande_gazebo('m.sdf', False) == ['ign', 'gazebo', '-r', 'm.sdf']


def test_arguments_du_contrat(lancement):
    """Les 4 arguments de la section 4.5, avec leurs valeurs par défaut."""
    from launch.actions import DeclareLaunchArgument
    arguments = {a.name: a for a in lancement.generate_launch_description().entities
                 if isinstance(a, DeclareLaunchArgument)}
    assert set(arguments) == {'lieu', 'etage', 'sans_fenetre', 'monde'}
    assert arguments['lieu'].default_value is None
    assert arguments['etage'].default_value is None
    assert arguments['sans_fenetre'].default_value[0].text == 'false'
    assert arguments['monde'].default_value[0].text == ''


@pytest.mark.skipif(shutil.which('ros2') is None, reason='ROS 2 non chargé')
def test_lancement_sans_monde(tmp_path):
    """Lieu sans monde : ros2 launch s'arrête aussitôt, avec un code d'erreur et la solution."""
    resultat = subprocess.run(
        ['ros2', 'launch', 'g1_sim', 'simulation.launch.py', f'lieu:={tmp_path}', 'etage:=rdc',
         'sans_fenetre:=true'], capture_output=True, text=True, timeout=60)
    assert resultat.returncode != 0
    assert 'g1-monde generer' in resultat.stdout + resultat.stderr
