#!/usr/bin/env python3
"""Ouvre RViz sur le nuage de points du LiDAR, quel que soit le programme qui le publie.

  g1-nuage                 cherche un nuage sur le réseau du robot et l'affiche
  g1-nuage --liste         affiche seulement les nuages trouvés
  g1-nuage --sujet /nom    affiche ce nuage-là

Lancer d'abord : source ~/robot-g1/setup/robot.sh
"""
import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import rclpy
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import PointCloud2

# Configuration RViz fournie par Livox, adaptée au nuage trouvé
MODELE_RVIZ = Path.home() / "robot-g1/ws/src/livox_ros_driver2/config/display_point_cloud_ROS2.rviz"
TYPE_NUAGE = "sensor_msgs/msg/PointCloud2"
COMMANDE_PILOTE = "ros2 launch livox_ros_driver2 rviz_MID360_launch.py"


def chercher_nuages(noeud, duree=5.0):
    fin = time.time() + duree
    while time.time() < fin:
        rclpy.spin_once(noeud, timeout_sec=0.2)
    return sorted(nom for nom, types in noeud.get_topic_names_and_types() if TYPE_NUAGE in types)


def lire_un_message(noeud, sujet, duree=5.0):
    recu = {}
    abonnement = noeud.create_subscription(PointCloud2, sujet, lambda m: recu.setdefault("msg", m),
                                           qos_profile_sensor_data)
    fin = time.time() + duree
    while "msg" not in recu and time.time() < fin:
        rclpy.spin_once(noeud, timeout_sec=0.2)
    noeud.destroy_subscription(abonnement)
    return recu.get("msg")


def preferer(sujets):
    for mot in ("livox", "lidar", "cloud"):
        for s in sujets:
            if mot in s.lower():
                return s
    return sujets[0]


def config_rviz(sujet, repere):
    texte = MODELE_RVIZ.read_text()
    for avant, apres in (("Color Transformer: Intensity", "Color Transformer: AxisColor"),
                         ("Topic: /livox/lidar", f"Topic: {sujet}"),
                         ("Fixed Frame: livox_frame", f"Fixed Frame: {repere}"),
                         ("Unreliable: false", "Unreliable: true"),
                         ("Style: Flat Squares", "Style: Points")):
        texte = texte.replace(avant, apres, 1)
    f = tempfile.NamedTemporaryFile("w", suffix=".rviz", prefix="g1-nuage-", delete=False)
    f.write(texte)
    f.close()
    return f.name


def main():
    p = argparse.ArgumentParser(description="Afficher le nuage de points du LiDAR dans RViz.")
    p.add_argument("--liste", action="store_true", help="afficher seulement les nuages trouvés")
    p.add_argument("--sujet", help="nom du nuage à afficher (sinon : choix automatique)")
    args = p.parse_args()

    if not os.environ.get("CYCLONEDDS_URI"):
        print("Attention : robot.sh n'a pas été lancé dans ce terminal, le robot risque de ne pas être vu.")
    rclpy.init()
    noeud = rclpy.create_node("g1_nuage")
    print("Recherche des nuages de points (5 s)…")
    sujets = chercher_nuages(noeud)
    if not sujets:
        print("Aucun nuage de points n'est publié sur le réseau.")
        print(f"Lancez le pilote LiDAR du PC à la place : {COMMANDE_PILOTE}")
        return 1
    print("Nuages trouvés : " + ", ".join(sujets))
    sujet = args.sujet or preferer(sujets)
    msg = lire_un_message(noeud, sujet)
    noeud.destroy_node()
    rclpy.shutdown()
    if msg is None:
        print(f"« {sujet} » existe mais n'a rien envoyé en 5 s.")
        return 1
    print(f"{sujet} : {msg.width * msg.height} points par message, repère « {msg.header.frame_id} ».")
    if args.liste:
        return 0
    return subprocess.call(["rviz2", "-d", config_rviz(sujet, msg.header.frame_id)])


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
