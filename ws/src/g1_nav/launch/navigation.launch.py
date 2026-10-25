"""
Navigation du guide sur la carte d'un étage d'un lieu (contrat : section 4.5 du plan).

  ros2 launch g1_nav navigation.launch.py lieu:=DOSSIER etage:=ID simu:=true|false
      moteur:=nav2|unitree

Ce que lance ce fichier :
  - map_server sur <lieu>/cartes/<etage>.yaml (repère map) ;
  - le repère map → odom : fixe (identité) en simulation, car l'odom de Gazebo est le repère
    du monde ; sur le vrai robot, odom_vers_tf relaie /unitree/slam_relocation/odom ;
  - moteur:=nav2 : Nav2 (Smac 2D, MPPI Omni, Collision Monitor) avec config/nav2_g1_simu.yaml
    ou nav2_g1_reel.yaml, et le filtre Keepout sur <lieu>/cartes/<etage>_interdit.yaml ;
    moteur:=unitree : pas de Nav2, le guide passe par la commande 1102 du robot ;
  - le guide (g1_nav/guide.py) : /guide/aller, /guide/stop, /guide/etat.

Les variables ROS_DOMAIN_ID et IGN_PARTITION de l'environnement sont respectées.
"""
import os
import tempfile
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, LogInfo, OpaqueFunction, SetEnvironmentVariable
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

# Nœuds de Nav2 gérés par le lifecycle_manager de la navigation, dans l'ordre de démarrage
NOEUDS_NAV2 = ['controller_server', 'smoother_server', 'planner_server', 'behavior_server',
               'bt_navigator', 'velocity_smoother', 'collision_monitor']


class ErreurNavigation(RuntimeError):
    """Erreur qui arrête le lancement ; son message dit à l'utilisateur quoi corriger."""

    def __init__(self, message):
        super().__init__(f'g1_nav : {message}')


def chemin_lieu(texte):
    """Dossier du lieu (atelier.chemin_lieu) ; repli si le paquet atelier est absent."""
    try:
        import atelier
        return atelier.chemin_lieu(texte)
    except ImportError:
        texte = str(texte).strip()
        if texte and '/' not in texte:
            racine = os.environ.get('ATELIER_LIEUX') or Path.home() / 'robot-g1' / 'lieux'
            return Path(racine).expanduser() / texte
        return Path(texte).expanduser().resolve()


def fichiers_du_lieu(lieu, etage):
    """Dossier du lieu, carte et masque Keepout de l'étage. ErreurNavigation si la carte manque."""
    dossier = chemin_lieu(lieu)
    if not (dossier / 'lieu.yaml').is_file():
        raise ErreurNavigation(
            f'le lieu {dossier} n\'existe pas (pas de lieu.yaml) : vérifiez lieu:=')
    carte = dossier / 'cartes' / f'{etage}.yaml'
    if not carte.is_file():
        raise ErreurNavigation(
            f'la carte {carte} n\'existe pas. Fabriquez-la d\'abord avec : '
            f'g1-monde generer --lieu {dossier} --etage {etage}')
    masque = dossier / 'cartes' / f'{etage}_interdit.yaml'
    return dossier, carte, masque


def masque_vide(carte):
    """Masque Keepout tout libre, de la taille de la carte, dans un dossier temporaire."""
    import numpy as np
    from atelier.lieu import charger_info_carte, enregistrer_carte, InfoCarte

    info = charger_info_carte(carte)
    dossier = Path(tempfile.mkdtemp(prefix='g1_nav_masque_'))
    masque = InfoCarte(image='masque_vide.pgm', resolution=info.resolution,
                       origin=tuple(info.origin), largeur=info.largeur, hauteur=info.hauteur)
    chemin = dossier / 'masque_vide.yaml'
    enregistrer_carte(chemin, masque, np.full((info.hauteur, info.largeur), 254, np.uint8))
    return chemin


def noeuds_nav2(reglages, simu, arbre):
    """Nœuds de Nav2 : planificateur, contrôleur, secours, bt_navigator, vitesses, sécurité."""
    params = [reglages, {'use_sim_time': simu}]
    vers_lisseur = [('cmd_vel', 'cmd_vel_nav')]

    def noeud(paquet, executable, remap=(), autres=None):
        return Node(package=paquet, executable=executable, name=executable, output='screen',
                    parameters=params + ([autres] if autres else []), remappings=list(remap))

    return [
        noeud('nav2_controller', 'controller_server', vers_lisseur),
        noeud('nav2_smoother', 'smoother_server'),
        noeud('nav2_planner', 'planner_server'),
        noeud('nav2_behaviors', 'behavior_server', vers_lisseur),
        # Arbre du guide : nœud passé à 1,5 m, chemin recalculé chaque seconde
        noeud('nav2_bt_navigator', 'bt_navigator',
              autres={'default_nav_through_poses_bt_xml': arbre}),
        # cmd_vel_nav → velocity_smoother → cmd_vel_smoothed → collision_monitor → cmd_vel
        noeud('nav2_velocity_smoother', 'velocity_smoother', vers_lisseur),
        noeud('nav2_collision_monitor', 'collision_monitor'),
        Node(package='nav2_lifecycle_manager', executable='lifecycle_manager',
             name='lifecycle_manager_navigation', output='screen',
             parameters=[{'use_sim_time': simu, 'autostart': True,
                          'node_names': NOEUDS_NAV2}]),
    ]


def _lancer(context):
    """Lit les arguments, vérifie les fichiers du lieu, puis renvoie les actions à lancer."""
    lieu = LaunchConfiguration('lieu').perform(context)
    etage = LaunchConfiguration('etage').perform(context)
    simu = LaunchConfiguration('simu').perform(context) == 'true'
    moteur = LaunchConfiguration('moteur').perform(context)

    partage = Path(get_package_share_directory('g1_nav'))
    reglages = str(partage / 'config' / ('nav2_g1_simu.yaml' if simu else 'nav2_g1_reel.yaml'))
    dossier, carte, masque = fichiers_du_lieu(lieu, etage)
    actions = [
        SetEnvironmentVariable('RCUTILS_LOGGING_BUFFERED_STREAM', '1'),
        LogInfo(msg=f'g1_nav : lieu {dossier}, étage {etage}, carte {carte}'),
        LogInfo(msg=f'g1_nav : {"simulation" if simu else "vrai robot"}, moteur {moteur}'
                    + (f', réglages {reglages}' if moteur == 'nav2' else '')),
    ]
    params = [reglages, {'use_sim_time': simu}]

    # Carte du lieu, et pour Nav2 le masque des zones interdites
    actions.append(Node(package='nav2_map_server', executable='map_server', name='map_server',
                        output='screen', parameters=params + [{'yaml_filename': str(carte)}]))
    noeuds_carte = ['map_server']
    if moteur == 'nav2':
        if not masque.is_file():
            actions.append(LogInfo(msg=f'g1_nav : pas de masque {masque} : aucune zone interdite. '
                                       f'Pour le fabriquer : g1-monde generer --lieu {dossier} '
                                       f'--etage {etage}'))
            masque = masque_vide(carte)
        actions += [
            Node(package='nav2_map_server', executable='map_server', name='filter_mask_server',
                 output='screen', parameters=params + [{'yaml_filename': str(masque)}]),
            Node(package='nav2_map_server', executable='costmap_filter_info_server',
                 name='costmap_filter_info_server', output='screen', parameters=params),
        ]
        noeuds_carte += ['filter_mask_server', 'costmap_filter_info_server']
    actions.append(Node(package='nav2_lifecycle_manager', executable='lifecycle_manager',
                        name='lifecycle_manager_carte', output='screen',
                        parameters=[{'use_sim_time': simu, 'autostart': True,
                                     'node_names': noeuds_carte}]))

    # map → odom : identité. Sur le vrai robot, odom → base_link vient de la relocalisation
    actions.append(Node(package='tf2_ros', executable='static_transform_publisher',
                        name='repere_map_odom', output='screen',
                        arguments=['--frame-id', 'map', '--child-frame-id', 'odom'],
                        parameters=[{'use_sim_time': simu}]))
    if not simu:
        actions.append(Node(package='g1_nav', executable='odom_vers_tf', name='odom_vers_tf',
                            output='screen'))

    if moteur == 'nav2':
        actions += noeuds_nav2(reglages, simu,
                               str(partage / 'config' / 'naviguer_par_poses.xml'))

    # Pas de name= : il renommerait aussi le nœud de nav2_simple_commander du même processus
    actions.append(Node(package='g1_nav', executable='guide', output='screen',
                        parameters=[{'lieu': str(dossier), 'etage': etage, 'moteur': moteur,
                                     'use_sim_time': simu}]))
    return actions


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument(
            'lieu',
            description='Dossier du lieu. Un id seul (ex. demo) désigne ~/robot-g1/lieux/<id>.'),
        DeclareLaunchArgument('etage', description="Id de l'étage (ex. rdc)."),
        DeclareLaunchArgument(
            'simu', default_value='false', choices=['true', 'false'],
            description='true : simulation Gazebo (temps simulé, repère map → odom fixe). '
                        'false : vrai robot (relais de /unitree/slam_relocation/odom).'),
        DeclareLaunchArgument(
            'moteur', default_value='nav2', choices=['nav2', 'unitree', 'factice'],
            description='nav2 : MoteurNav2 (Nav2 lancé). '
                        'unitree : MoteurUnitree (commande 1102, Nav2 non lancé). '
                        'factice : moteur sans robot, pour les essais.'),
        OpaqueFunction(function=_lancer),
    ])
