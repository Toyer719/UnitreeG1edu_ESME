"""
Simulation Gazebo d'un étage d'un lieu de l'Atelier G1 (contrat : section 4.5 du plan).

  ros2 launch g1_sim simulation.launch.py lieu:=DOSSIER etage:=ID sans_fenetre:=true|false
      [monde:=FICHIER.sdf]

Fichier provisoire de la phase 0 : il déclare les arguments du contrat, les affiche et s'arrête.
L'agent Simulation le remplace par le vrai lancement : Gazebo sur <lieu>/mondes/<etage>.sdf,
robot proxy à depart_robot, pont ros_gz et robot_state_publisher.
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
            'sans_fenetre', default_value='false', choices=['true', 'false'],
            description='true : Gazebo en serveur seul, sans fenêtre (-s --headless-rendering).'),
        DeclareLaunchArgument(
            'monde', default_value='',
            description='Monde .sdf à charger. Vide : <lieu>/mondes/<etage>.sdf.'),
        LogInfo(msg=[
            "g1_sim : lancement provisoire de la phase 0, rien n'est lancé. lieu=",
            LaunchConfiguration('lieu'), ' etage=', LaunchConfiguration('etage'),
            ' sans_fenetre=', LaunchConfiguration('sans_fenetre'),
            ' monde=', LaunchConfiguration('monde')]),
        Shutdown(reason='lancement provisoire de la phase 0'),
    ])
