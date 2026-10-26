"""
Détecteur de personnes au LiDAR (nœud detecteur_personnes).

Squelette livré par l'intégrateur, à écrire par l'agent Comportement du guide.

Contrat (section 11.4 du plan) : entrée /points (sensor_msgs/PointCloud2, repère lidar, base_link
par TF) ; sortie /personnes/lidar (std_msgs/String JSON, schéma personnes, source lidar, 10 Hz) :
groupes de points de la taille d'une personne, suivis d'un message à l'autre (id), avec leur
vitesse ; il voit aussi derrière le robot (accompagnement du visiteur, passant qui bouche le
passage). Lancé par navigation.launch.py (argument personnes).

Tant qu'il n'est pas écrit, il ne publie rien et sort avec le code 1.
"""
import sys


def main(args=None):
    """Point d'entrée de ros2 run g1_nav detecteur_personnes."""
    print('detecteur_personnes : pas encore écrit (vague 4, agent Comportement du guide, '
          'section 11.4 du plan)', file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())
