"""
Simulation Gazebo d'un étage d'un lieu de l'Atelier G1 (contrat : section 4.5 du plan).

  ros2 launch g1_sim simulation.launch.py lieu:=DOSSIER etage:=ID sans_fenetre:=true|false
      [monde:=FICHIER.sdf]

Ce que lance ce fichier :
  - Gazebo Fortress sur <lieu>/mondes/<etage>.sdf (ou sur monde:=FICHIER.sdf) ;
    sans_fenetre:=true : « ign gazebo -s -r --headless-rendering », serveur seul ;
  - le robot proxy g1_proxy (models/g1_proxy/model.sdf), posé à depart_robot,
    lu dans <lieu>/mondes/<etage>.monde.yaml ;
  - le pont ros_gz_bridge (config/pont_gz.yaml) : /cmd_vel, /odom, /tf, /clock et /points ;
  - robot_state_publisher : le repère fixe base_link → lidar.

Le repère map → odom n'est pas publié ici : c'est le lancement de g1_nav qui s'en charge
(identité en simulation, car le repère odom de Gazebo est le repère du monde, donc de la carte).
Les variables ROS_DOMAIN_ID et IGN_PARTITION de l'environnement sont respectées.
"""
import math
import os
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (DeclareLaunchArgument, EmitEvent, ExecuteProcess, LogInfo,
                            OpaqueFunction, RegisterEventHandler)
from launch.event_handlers import OnProcessExit
from launch.events import Shutdown
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

NOM_ROBOT = 'g1_proxy'

# Hauteur à laquelle le robot apparaît : 1 cm au-dessus du sol, pour ne pas le toucher au départ
Z_DEPART = 0.01


class ErreurSimulation(RuntimeError):
    """Erreur qui arrête le lancement ; son message dit à l'utilisateur quoi corriger."""

    def __init__(self, message):
        super().__init__(f'g1_sim : {message}')


def dossier_partage():
    """Dossier share/g1_sim installé (modèles, mondes de test, réglages du pont)."""
    return Path(get_package_share_directory('g1_sim'))


def chemin_lieu(texte):
    """Dossier du lieu, comme atelier.chemin_lieu ; repli si le paquet atelier est absent."""
    try:
        import atelier
        return atelier.chemin_lieu(texte)
    except ImportError:
        texte = str(texte).strip()
        if texte and '/' not in texte:
            racine = os.environ.get('ATELIER_LIEUX') or Path.home() / 'robot-g1' / 'lieux'
            return Path(racine).expanduser() / texte
        return Path(texte).expanduser().resolve()


def fichier_monde(dossier, etage, monde=''):
    """Monde .sdf à charger : monde:= s'il est donné, sinon <lieu>/mondes/<etage>.sdf."""
    if monde:
        sdf = Path(monde).expanduser().resolve()
        if not sdf.is_file():
            raise ErreurSimulation(f'le monde {sdf} n\'existe pas : vérifiez monde:=')
        return sdf
    sdf = Path(dossier) / 'mondes' / f'{etage}.sdf'
    if not sdf.is_file():
        raise ErreurSimulation(
            f'le monde {sdf} n\'existe pas. Fabriquez-le d\'abord avec : '
            f'g1-monde generer --lieu {dossier} --etage {etage}')
    return sdf


def nom_du_monde(sdf):
    """Nom du <world> d'un fichier SDF (il sert aux services Gazebo /world/<nom>/...)."""
    monde = ET.parse(sdf).getroot().find('world')
    if monde is None or not monde.get('name'):
        raise ErreurSimulation(f'{sdf} ne contient pas de <world name="...">')
    return monde.get('name')


def depart_robot(dossier, etage, sdf=None):
    """
    Pose de départ (x, y, theta) du robot, et d'où elle vient.

    Ordre : <lieu>/mondes/<etage>.monde.yaml (lu par atelier.lieu s'il est disponible,
    ce qui le valide), sinon le fichier <nom>.monde.yaml à côté du monde .sdf,
    sinon l'origine (0, 0, 0).
    """
    candidats = [Path(dossier) / 'mondes' / f'{etage}.monde.yaml']
    if sdf is not None:
        sdf = Path(sdf)
        candidats.append(sdf.with_name(sdf.stem + '.monde.yaml'))
    for chemin in candidats:
        if chemin.is_file():
            return _lire_depart(chemin), str(chemin)
    return (0.0, 0.0, 0.0), 'aucun monde.yaml trouvé : départ en (0, 0, 0)'


def _lire_depart(chemin):
    """depart_robot d'un fichier monde.yaml, en (x, y, theta)."""
    try:
        from atelier.lieu import fichiers
    except ImportError:
        fichiers = None
    if fichiers is not None:
        # Validation complète du fichier (schéma JSON), avec des messages en français
        try:
            donnees = fichiers.charger_fichier(chemin, 'monde')
        except Exception as erreur:  # ErreurLieu : on la montre telle quelle
            raise ErreurSimulation(str(erreur)) from erreur
    else:
        with open(chemin, encoding='utf-8') as f:
            donnees = yaml.safe_load(f) or {}
    depart = donnees.get('depart_robot')
    if not isinstance(depart, dict) or 'x' not in depart or 'y' not in depart:
        raise ErreurSimulation(f'{chemin} : il manque depart_robot (x, y, theta)')
    return float(depart['x']), float(depart['y']), float(depart.get('theta', 0.0))


def pose_lidar(modele_sdf):
    """Position (x, y, z, roulis, tangage, lacet) du LiDAR dans base_link, lue dans model.sdf."""
    racine = ET.parse(modele_sdf).getroot()
    for capteur in racine.iter('sensor'):
        if capteur.get('type') in ('gpu_lidar', 'gpu_ray', 'lidar'):
            pose = capteur.findtext('pose', default='0 0 0 0 0 0').split()
            return tuple(float(v) for v in pose)
    raise ErreurSimulation(f'{modele_sdf} : pas de capteur gpu_lidar')


def description_urdf(modele_sdf):
    """URDF minimal pour robot_state_publisher : base_link, lidar et la boîte du robot."""
    x, y, z, roulis, tangage, lacet = pose_lidar(modele_sdf)
    return f"""<?xml version="1.0"?>
<robot name="{NOM_ROBOT}">
  <link name="base_link">
    <visual>
      <origin xyz="0 0 0.65" rpy="0 0 0"/>
      <geometry><box size="0.45 0.30 1.30"/></geometry>
    </visual>
  </link>
  <link name="lidar"/>
  <joint name="base_link_vers_lidar" type="fixed">
    <parent link="base_link"/>
    <child link="lidar"/>
    <origin xyz="{x} {y} {z}" rpy="{roulis} {tangage} {lacet}"/>
  </joint>
</robot>
"""


def commande_gazebo(sdf, sans_fenetre):
    """Commande ign gazebo : serveur seul sans fenêtre, ou serveur et fenêtre."""
    if sans_fenetre:
        return ['ign', 'gazebo', '-s', '-r', '--headless-rendering', str(sdf)]
    return ['ign', 'gazebo', '-r', str(sdf)]


def _lancer(context):
    """Lit les arguments, vérifie les fichiers, puis renvoie les actions à lancer."""
    lieu = LaunchConfiguration('lieu').perform(context)
    etage = LaunchConfiguration('etage').perform(context)
    sans_fenetre = LaunchConfiguration('sans_fenetre').perform(context) == 'true'
    monde = LaunchConfiguration('monde').perform(context)

    partage = dossier_partage()
    modele = partage / 'models' / NOM_ROBOT / 'model.sdf'
    pont = partage / 'config' / 'pont_gz.yaml'

    dossier = chemin_lieu(lieu)
    sdf = fichier_monde(dossier, etage, monde)
    nom = nom_du_monde(sdf)
    (x, y, theta), origine = depart_robot(dossier, etage, sdf)

    gazebo = ExecuteProcess(cmd=commande_gazebo(sdf, sans_fenetre), output='screen',
                            name='gazebo')
    apparition = Node(
        package='ros_gz_sim', executable='create', name='apparition_g1_proxy', output='screen',
        arguments=['-file', str(modele), '-name', NOM_ROBOT,
                   '-x', f'{x}', '-y', f'{y}', '-z', f'{Z_DEPART}', '-Y', f'{theta}'])
    pont_gz = Node(
        package='ros_gz_bridge', executable='parameter_bridge', name='pont_gz', output='screen',
        parameters=[{'config_file': str(pont)}])
    etat_robot = Node(
        package='robot_state_publisher', executable='robot_state_publisher',
        name='robot_state_publisher', output='screen',
        parameters=[{'robot_description': description_urdf(modele), 'use_sim_time': True}])

    return [
        LogInfo(msg=f'g1_sim : monde {sdf} (« {nom} »)'),
        LogInfo(msg=f'g1_sim : robot en x={x:.2f} y={y:.2f} theta={theta:.2f} '
                    f'({math.degrees(theta):.0f}°), d\'après {origine}'),
        gazebo,
        apparition,
        pont_gz,
        etat_robot,
        # Gazebo fermé (fenêtre fermée, plantage) : on arrête tout le lancement
        RegisterEventHandler(OnProcessExit(
            target_action=gazebo,
            on_exit=[EmitEvent(event=Shutdown(reason='Gazebo s\'est arrêté'))])),
        # Robot qui n'a pas pu apparaître : inutile de continuer sans lui
        RegisterEventHandler(OnProcessExit(target_action=apparition, on_exit=_apparition_finie)),
    ]


def _apparition_finie(evenement, context):
    """Après « create » : rien si le robot est apparu, sinon arrêt avec un message."""
    if evenement.returncode == 0:
        return None
    raison = ('g1_sim : le robot g1_proxy n\'a pas pu apparaître dans Gazebo '
              f'(code {evenement.returncode}) ; voir les messages de create ci-dessus')
    return [LogInfo(msg=raison), EmitEvent(event=Shutdown(reason=raison))]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument(
            'lieu',
            description='Dossier du lieu. Un id seul (ex. demo) désigne ~/robot-g1/lieux/<id>.'),
        DeclareLaunchArgument('etage', description="Id de l'étage (ex. rdc)."),
        DeclareLaunchArgument(
            'sans_fenetre', default_value='false', choices=['true', 'false'],
            description='true : Gazebo en serveur seul, sans fenêtre (-s --headless-rendering).'),
        DeclareLaunchArgument(
            'monde', default_value='',
            description='Monde .sdf à charger. Vide : <lieu>/mondes/<etage>.sdf.'),
        OpaqueFunction(function=_lancer),
    ])
