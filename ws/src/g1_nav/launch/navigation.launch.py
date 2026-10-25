"""
Navigation du guide sur la carte d'un étage d'un lieu (contrat : section 4.5 du plan).

  ros2 launch g1_nav navigation.launch.py lieu:=DOSSIER etage:=ID simu:=true|false
      moteur:=nav2|unitree

Fichier provisoire de la phase 0 : il déclare les arguments du contrat, les affiche et s'arrête.
L'agent Navigation le remplace par le vrai lancement : carte <lieu>/cartes/<etage>.yaml,
masque <lieu>/cartes/<etage>_interdit.yaml, Nav2 (moteur nav2), routeur et guide.
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, LogInfo, Shutdown
from launch.substitutions import LaunchConfiguration


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
            'moteur', default_value='nav2', choices=['nav2', 'unitree'],
            description='nav2 : MoteurNav2 (Nav2 lancé). '
                        'unitree : MoteurUnitree (commande 1102, Nav2 non lancé).'),
        LogInfo(msg=[
            "g1_nav : lancement provisoire de la phase 0, rien n'est lancé. lieu=",
            LaunchConfiguration('lieu'), ' etage=', LaunchConfiguration('etage'),
            ' simu=', LaunchConfiguration('simu'), ' moteur=', LaunchConfiguration('moteur')]),
        Shutdown(reason='lancement provisoire de la phase 0'),
    ])
