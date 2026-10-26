"""
Navigation du guide sur la carte d'un étage d'un lieu (contrats : sections 4.5 et 10.7 du plan).

  ros2 launch g1_nav navigation.launch.py lieu:=DOSSIER etage:=ID simu:=true|false
      moteur:=nav2|unitree|factice [localisation:=simu|unitree|amcl|externe]
      [pont:=auto|true|false] [nuage:=SUJET] [vitesse_max:=M_PAR_S] [personnes:=true|false]

Ce que lance ce fichier :
  - map_server sur <lieu>/cartes/<etage>.yaml (repère map) ;
  - la localisation (localisation:=, vide par défaut : simu si simu:=true, unitree sinon) :
      simu     map → odom fixe (identité) : l'odom de Gazebo est le repère du monde ;
      unitree  le relais odom_vers_tf : odom → base_link depuis /state_estimator/odom_pelvis, et
               map → odom tiré de la relocalisation d'Unitree (1804, « Repérer le robot ») ;
      amcl     secours : odom_vers_tf (odom → base_link, /points), pointcloud_to_laserscan
               (/points → /scan, tranche de 0,1 à 1,5 m) et nav2_amcl (config/amcl_g1.yaml) ;
      externe  rien : un autre programme fournit map → odom → base_link et /reperage/etat ;
    sur le vrai robot (simu:=false), avec unitree ou amcl : aussi base_link → lidar (fixe) ;
  - moteur:=nav2 : Nav2 (Smac 2D, MPPI Omni, Collision Monitor), avec config/nav2_g1_simu.yaml
    (localisation simu) ou nav2_g1_reel.yaml (toutes les autres, même en répétition : vitesses du
    robot), et le filtre Keepout sur <lieu>/cartes/<etage>_interdit.yaml ;
    moteur:=unitree : pas de Nav2, le guide passe par la commande 1102 du robot ;
  - le pont g1_bridge (pont:=auto : avec Nav2, sauf en localisation simu) : /cmd_vel → ordres de
    marche 7105 du robot, avec ses sécurités (section 10.3) ; vitesse_max:=0.2 (m/s, premiers
    essais) abaisse ses plafonds dans la même proportion (0,2 ; 0,125 ; 0,3), vide : ceux du
    contrat (0,4 ; 0,25 ; 0,6) ;
  - le guide (g1_nav/guide.py) : /guide/aller, /guide/stop, /guide/etat, /guide/evenement ;
  - personnes:=true (défaut, vague 4, section 11.4) : le détecteur de personnes au LiDAR
    (g1_nav/personnes.py, /points → /personnes/lidar), qui sert au guide pour accompagner le
    visiteur et attendre un passant qui bouche le passage ; personnes:=false : ni l'un ni l'autre.

use_sim_time vaut simu. Les variables ROS_DOMAIN_ID et IGN_PARTITION de l'environnement sont
respectées.
"""
import math
import os
import sys
import tempfile
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (DeclareLaunchArgument, ExecuteProcess, LogInfo, OpaqueFunction,
                            SetEnvironmentVariable)
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

# Nœuds de Nav2 gérés par le lifecycle_manager de la navigation, dans l'ordre de démarrage
NOEUDS_NAV2 = ['controller_server', 'smoother_server', 'planner_server', 'behavior_server',
               'bt_navigator', 'velocity_smoother', 'collision_monitor']
LOCALISATIONS = ('simu', 'unitree', 'amcl', 'externe')
# LiDAR du robot dans base_link (x, y, z), comme le robot proxy de g1_sim. Sur le vrai G1 : à
# vérifier (montage du MID-360, section 10.9 du plan)
POSE_LIDAR = (-0.004, 0.0, 1.245)
# Nuage pour amcl, selon le cas (le nuage d'Unitree est dans le repère de sa carte, sans
# relocalisation il ne se place pas) : répétition, le LiDAR du robot proxy ; robot, à déterminer
NUAGE_AMCL_REPETITION = '/g1_jumeau/points'
NUAGE_AMCL_ROBOT = '/unitree/slam_relocation/points'


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


def partage(paquet):
    """Dossier share d'un paquet ROS 2 ; None s'il n'est pas compilé."""
    from ament_index_python.packages import PackageNotFoundError
    try:
        return Path(get_package_share_directory(paquet))
    except PackageNotFoundError:
        return None


def fichier_config(partage_g1_nav, nom):
    """Réglage de config/ : celui installé, sinon celui des sources (pas encore recompilé)."""
    installe = Path(partage_g1_nav) / 'config' / nom
    if installe.is_file():
        return installe
    return Path(__file__).resolve().parent.parent / 'config' / nom


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


def choisir_localisation(texte, simu):
    """Localisation demandée (vide : simu si simu:=true, unitree sinon), vérifiée."""
    localisation = texte.strip() or ('simu' if simu else 'unitree')
    if localisation not in LOCALISATIONS:
        raise ErreurNavigation(f'localisation:={localisation} inconnue : '
                               f'{", ".join(LOCALISATIONS)}')
    if localisation == 'simu' and not simu:
        raise ErreurNavigation('localisation:=simu demande simu:=true (Gazebo fournit la '
                               'position). Sur le vrai robot : localisation:=unitree, ou amcl '
                               'en secours.')
    return localisation


def choisir_pont(texte, localisation, moteur):
    """pont:=auto : avec Nav2, sauf en localisation simu (Gazebo reçoit /cmd_vel directement)."""
    if texte not in ('auto', 'true', 'false'):
        raise ErreurNavigation(f'pont:={texte} inconnu : auto, true ou false')
    if texte == 'auto':
        return localisation != 'simu' and moteur == 'nav2'
    return texte == 'true'


def noeuds_localisation(localisation, simu, dossier, etage, partage_g1_nav, nuage=''):
    """Actions de la localisation (section 10.5) : relais, repères fixes, AMCL."""
    from atelier.lieu import carte_pour_reperage, repere_unitree

    temps = {'use_sim_time': simu}
    actions = []
    if localisation == 'simu':
        # map → odom : identité (l'odom de Gazebo est le repère du monde, donc de la carte)
        return [Node(package='tf2_ros', executable='static_transform_publisher',
                     name='repere_map_odom', output='screen',
                     arguments=['--frame-id', 'map', '--child-frame-id', 'odom'],
                     parameters=[temps])]
    if localisation == 'externe':
        return [LogInfo(msg='g1_nav : localisation externe : un autre programme doit fournir '
                            'map → odom → base_link et /reperage/etat')]
    repere = repere_unitree(dossier, etage)
    repere = [float(repere.x), float(repere.y), float(repere.theta)]
    relais = {'localisation': localisation, 'lieu': str(dossier), 'etage': etage,
              'repere_unitree': repere, 'use_sim_time': simu}
    if localisation == 'unitree':
        carte = carte_pour_reperage(dossier, repetition=simu)
        relais.update(carte=carte or '', nuage=nuage or '/unitree/slam_relocation/points')
        if not carte:
            actions.append(LogInfo(msg='g1_nav : ce lieu n\'a pas de carte_unitree (scan du '
                                       'robot) : « Repérer le robot » échouera. Faites d\'abord '
                                       'un scan avec le robot (onglet Scan), ou essayez '
                                       'localisation:=amcl.'))
        actions.append(LogInfo(msg=f'g1_nav : repérage par la relocalisation d\'Unitree, carte '
                                   f'{carte or "aucune"}, repère d\'Unitree ({repere[0]:g} ; '
                                   f'{repere[1]:g} ; {repere[2]:g})'))
    else:
        source = nuage or (NUAGE_AMCL_REPETITION if simu else NUAGE_AMCL_ROBOT)
        relais.update(nuage=source, points_repere='capteur' if simu or nuage else 'auto')
        if not simu and not nuage:
            actions.append(LogInfo(msg='g1_nav : amcl sur le vrai robot : la source du nuage est '
                                       'à déterminer (section 10.9 du plan) ; donnez-la avec '
                                       'nuage:='))
    actions.append(Node(package='g1_nav', executable='odom_vers_tf', name='odom_vers_tf',
                        output='screen', parameters=[relais]))
    if not simu:
        # Sur le robot, rien d'autre ne publie base_link → lidar (à vérifier : montage du MID-360)
        x, y, z = POSE_LIDAR
        actions.append(Node(package='tf2_ros', executable='static_transform_publisher',
                            name='repere_base_lidar', output='screen',
                            arguments=['--x', str(x), '--y', str(y), '--z', str(z),
                                       '--frame-id', 'base_link', '--child-frame-id', 'lidar']))
    if localisation == 'amcl':
        actions += [
            # /points (repère lidar) → /scan : tranche de 0,1 à 1,5 m au-dessus du sol
            Node(package='pointcloud_to_laserscan', executable='pointcloud_to_laserscan_node',
                 name='nuage_vers_scan', output='screen',
                 remappings=[('cloud_in', '/points'), ('scan', '/scan')],
                 parameters=[{'use_sim_time': simu, 'target_frame': 'base_link',
                              'transform_tolerance': 0.1, 'min_height': 0.1, 'max_height': 1.5,
                              'angle_min': -math.pi, 'angle_max': math.pi,
                              'angle_increment': math.pi / 180.0, 'scan_time': 0.1,
                              'range_min': 0.2, 'range_max': 20.0, 'use_inf': True}]),
            Node(package='nav2_amcl', executable='amcl', name='amcl', output='screen',
                 parameters=[str(fichier_config(partage_g1_nav, 'amcl_g1.yaml')), temps]),
            Node(package='nav2_lifecycle_manager', executable='lifecycle_manager',
                 name='lifecycle_manager_localisation', output='screen',
                 parameters=[{'use_sim_time': simu, 'autostart': True, 'node_names': ['amcl']}]),
        ]
    return actions


def plafonds_pont(texte):
    """
    vitesse_max:= (m/s) : plafonds du pont abaissés dans la même proportion, ou None (vide).

    Pour les premiers essais sur le robot : 0.2 donne (vx 0,2 ; vy 0,125 ; wz 0,3). Le pont
    n'accepte jamais plus que les plafonds du contrat (atelier.lieu.LIMITES_PONT).
    """
    from atelier.lieu import LIMITES_PONT

    texte = (texte or '').strip()
    if not texte:
        return None
    try:
        vitesse = float(texte.replace(',', '.'))
    except ValueError:
        vitesse = math.nan
    vx = LIMITES_PONT['vx']
    if not math.isfinite(vitesse) or not 0.0 < vitesse <= vx:
        raise ErreurNavigation(f'vitesse_max:={texte} : il faut une vitesse en m/s, plus grande '
                               f'que 0 et au plus {vx} (plafond du pont), par exemple 0.2')
    part = vitesse / vx
    return {'vx_max': round(vitesse, 3), 'vy_max': round(LIMITES_PONT['vy'] * part, 3),
            'wz_max': round(LIMITES_PONT['wz'] * part, 3)}


def _valeur_parametre(valeur):
    """Valeur d'un paramètre ROS en ligne de commande (-p nom:=valeur)."""
    if isinstance(valeur, bool):
        return 'true' if valeur else 'false'
    return str(valeur)


def noeud_g1_nav(executable, module, nom, parametres):
    """
    Nœud de g1_nav (vague 4 : detecteur_personnes, faux_visiteur).

    Si l'exécutable n'est pas encore installé (g1_nav compilé avant son ajout : ws/install d'avant
    la vague 4), il est lancé par python3 -m, avec les mêmes paramètres.
    """
    from ament_index_python.packages import get_package_prefix, PackageNotFoundError
    try:
        installe = (Path(get_package_prefix('g1_nav')) / 'lib' / 'g1_nav' / executable).is_file()
    except PackageNotFoundError:
        installe = False
    if installe:
        return Node(package='g1_nav', executable=executable, name=nom, output='screen',
                    parameters=[parametres])
    commande = [sys.executable, '-m', module, '--ros-args', '-r', f'__node:={nom}']
    for cle, valeur in parametres.items():
        commande += ['-p', f'{cle}:={_valeur_parametre(valeur)}']
    return ExecuteProcess(cmd=commande, name=nom, output='screen')


def vitesse_max_nav2(reglages):
    """vx_max du contrôleur de Nav2 (FollowPath) dans le fichier de réglages, ou 0 si illisible."""
    import yaml
    try:
        with open(reglages, encoding='utf-8') as f:
            d = yaml.safe_load(f)
        return float(d['controller_server']['ros__parameters']['FollowPath']['vx_max'])
    except (OSError, KeyError, TypeError, ValueError, yaml.YAMLError):
        return 0.0


def noeud_pont(simu, plafonds=None):
    """Le pont /cmd_vel → /api/sport/request (paquet g1_bridge, section 10.3)."""
    dossier = partage('g1_bridge')
    if dossier is None:
        raise ErreurNavigation(
            'le paquet g1_bridge (pont vers la marche du robot) n\'est pas compilé : '
            'cd ~/robot-g1/ws && colcon build --symlink-install --packages-select g1_bridge, '
            'ou relancez avec pont:=false (aucune vitesse n\'ira alors au robot)')
    reglages = dossier / 'config' / 'pont.yaml'
    parametres = [str(reglages)] if reglages.is_file() else []
    if plafonds:
        parametres.append(dict(plafonds))
    # Pas de use_sim_time : les délais du pont comptent toujours en temps mural (section 10.3)
    return Node(package='g1_bridge', executable='pont', name='pont_g1', output='screen',
                parameters=parametres)


def _lancer(context):
    """Lit les arguments, vérifie les fichiers du lieu, puis renvoie les actions à lancer."""
    lieu = LaunchConfiguration('lieu').perform(context)
    etage = LaunchConfiguration('etage').perform(context)
    simu = LaunchConfiguration('simu').perform(context) == 'true'
    moteur = LaunchConfiguration('moteur').perform(context)
    localisation = choisir_localisation(LaunchConfiguration('localisation').perform(context), simu)
    pont = choisir_pont(LaunchConfiguration('pont').perform(context), localisation, moteur)
    nuage = LaunchConfiguration('nuage').perform(context).strip()
    plafonds = plafonds_pont(LaunchConfiguration('vitesse_max').perform(context))
    personnes = LaunchConfiguration('personnes', default='true').perform(context) != 'false'

    partage_g1_nav = Path(get_package_share_directory('g1_nav'))
    nom_reglages = 'nav2_g1_simu.yaml' if localisation == 'simu' else 'nav2_g1_reel.yaml'
    reglages = str(fichier_config(partage_g1_nav, nom_reglages))
    dossier, carte, masque = fichiers_du_lieu(lieu, etage)
    actions = [
        SetEnvironmentVariable('RCUTILS_LOGGING_BUFFERED_STREAM', '1'),
        LogInfo(msg=f'g1_nav : lieu {dossier}, étage {etage}, carte {carte}'),
        LogInfo(msg=f'g1_nav : {"temps simulé" if simu else "vrai robot"}, localisation '
                    f'{localisation}, moteur {moteur}, pont {"oui" if pont else "non"}'
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

    actions += noeuds_localisation(localisation, simu, dossier, etage, partage_g1_nav, nuage)
    if pont:
        if plafonds:
            actions.append(LogInfo(msg=f'g1_nav : vitesse réduite, plafonds du pont : vx '
                                       f'{plafonds["vx_max"]} m/s, vy {plafonds["vy_max"]} m/s, '
                                       f'wz {plafonds["wz_max"]} rad/s'))
        actions.append(noeud_pont(simu, plafonds))
    elif plafonds:
        actions.append(LogInfo(msg='g1_nav : vitesse_max ignorée : pas de pont dans ce lancement'))

    if moteur == 'nav2':
        actions += noeuds_nav2(reglages, simu,
                               str(fichier_config(partage_g1_nav, 'naviguer_par_poses.xml')))

    # Vague 4 (section 11.4) : le détecteur de personnes au LiDAR, pour le guide
    parametres_guide = {'lieu': str(dossier), 'etage': etage, 'moteur': moteur,
                        'use_sim_time': simu}
    if moteur == 'nav2':     # le ralenti pour le visiteur se calcule sur la vitesse réelle
        parametres_guide['vitesse_max_nav2'] = vitesse_max_nav2(reglages)
    if personnes:
        actions.append(noeud_g1_nav('detecteur_personnes', 'g1_nav.personnes',
                                    'detecteur_personnes',
                                    {'lieu': str(dossier), 'etage': etage, 'use_sim_time': simu}))
    else:
        actions.append(LogInfo(msg='g1_nav : personnes:=false : pas de détecteur de personnes ; '
                                   'le guide n\'accompagne pas le visiteur et n\'attend pas les '
                                   'passants'))
        parametres_guide.update(accompagnement=False, passants=False)

    # Pas de name= : il renommerait aussi le nœud de nav2_simple_commander du même processus
    actions.append(Node(package='g1_nav', executable='guide', output='screen',
                        parameters=[parametres_guide]))
    return actions


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument(
            'lieu',
            description='Dossier du lieu. Un id seul (ex. demo) désigne ~/robot-g1/lieux/<id>.'),
        DeclareLaunchArgument('etage', description="Id de l'étage (ex. rdc)."),
        DeclareLaunchArgument(
            'simu', default_value='false', choices=['true', 'false'],
            description='true : temps simulé (Gazebo : simulation ou répétition). '
                        'false : vrai robot.'),
        DeclareLaunchArgument(
            'moteur', default_value='nav2', choices=['nav2', 'unitree', 'factice'],
            description='nav2 : MoteurNav2 (Nav2 lancé). '
                        'unitree : MoteurUnitree (commande 1102, Nav2 non lancé). '
                        'factice : moteur sans robot, pour les essais.'),
        DeclareLaunchArgument(
            'localisation', default_value='',
            description='simu : map → odom fixe (Gazebo). unitree : relocalisation d\'Unitree '
                        '(1804) et relais odom_vers_tf. amcl : secours, notre carte et le LiDAR. '
                        'externe : fournie par un autre programme. Vide : simu si simu:=true, '
                        'unitree sinon.'),
        DeclareLaunchArgument(
            'pont', default_value='auto', choices=['auto', 'true', 'false'],
            description='Pont /cmd_vel → ordres de marche 7105 (g1_bridge). auto : avec Nav2, '
                        'sauf en localisation simu.'),
        DeclareLaunchArgument(
            'nuage', default_value='',
            description='Sujet du nuage donné au relais (vide : /unitree/slam_relocation/points ; '
                        'amcl en répétition : /g1_jumeau/points).'),
        DeclareLaunchArgument(
            'personnes', default_value='true', choices=['true', 'false'],
            description='Détecteur de personnes au LiDAR (/personnes/lidar), pour que le guide '
                        'accompagne le visiteur et attende un passant qui bouche le passage.'),
        DeclareLaunchArgument(
            'vitesse_max', default_value='',
            description='Vitesse maximale en m/s pour les premiers essais (ex. 0.2) : les '
                        'plafonds du pont baissent dans la même proportion. Vide : 0,4 / 0,25 '
                        '/ 0,6.'),
        OpaqueFunction(function=_lancer),
    ])
