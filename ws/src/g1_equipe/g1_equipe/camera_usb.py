"""
Nœud camera_poitrine (exécutable camera_usb) : la caméra de poitrine See3CAM.

Squelette livré par l'agent Contrats, à écrire par l'agent Caméra.

Contrat (section 12.7 du plan) : lit la caméra USB (v4l2-ctl, YUYV 1280 × 720), règle l'exposition
au démarrage (auto par défaut), et publie des JPEG (Pillow, sans OpenCV) sur
/camera_poitrine/image/compressed (sensor_msgs/CompressedImage, 10 Hz, 640 pixels de large, qualité
70, QoS des capteurs) et son état en JSON sur /camera_poitrine/etat (schéma etat_camera, 1 Hz).
Paramètres : source (v4l2, mire ou fichier), peripherique, lieu (camera.yaml), largeur, hauteur,
ips, frequence_hz, largeur_publiee, qualite_jpeg, exposition, fichier.

Tant qu'il n'est pas écrit, il ne publie rien et sort avec le code 1.
"""
import sys


def main(args=None):
    """Point d'entrée de ros2 run g1_equipe camera_usb."""
    print('camera_usb : le nœud de la caméra de poitrine n\'est pas encore écrit (vague 5, agent '
          'Caméra, section 12.7 du plan)', file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())
