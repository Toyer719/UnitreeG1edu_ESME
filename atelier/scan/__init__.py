"""Scan du vrai bâtiment : client slam_operate, faux service, cartes 3D et 2D (agent Scan).

Modules (tout s'importe depuis le module, ex. from atelier.scan.carte2d import fabriquer_carte) :

  slam_client   client du service slam_operate du G1 (SDK Unitree) : 1801 scan, 1802 fin du scan,
                1804 relocalisation, 1102 aller, 1201/1202 pause/reprise, 1901 arrêt ; écoute de
                rt/slam_info (position) et rt/slam_key_info (is_arrived).
                ClientSlam(*connexion(faux)), SuiviArrivee, formats JSON « à vérifier sur le robot ».
  faux_slam     faux service slam_operate sur lo (mêmes commandes, déroulé vérifié) ;
                robot imaginaire, ou robot proxy de Gazebo (DeplacementGazebo) ; faux_partage()
                pour les tests (un seul serveur par processus).
  carte3d       ros2 bag (nuage + odométrie, /tf_static) → nuage .pcd réduit à 5 cm, sans piétons :
                fabriquer_pcd(enregistrement, sortie), assembler(...), lire_pcd, ecrire_pcd.
  carte2d       nuage .pcd → carte Nav2 .pgm + .yaml (tranche 0,1–1,5 m, ouverture par aire) :
                fabriquer_carte(points, emprise), fabriquer_carte_lieu(lieu, etage),
                comparer(...) (recouvrement et couverture de deux cartes).
  salle         position du robot (/odom) → salle ou nœud : lire_position(), ajouter(...).
  commande      lignes de commande g1-slam, g1-carte-3d, g1-carte-2d et g1-salle.

Scan intégré (vague 2, section 9 du plan) :

  session       la commande g1-scan (demarrer, arreter, traiter, etat, adopter), le processus de la
                session (enregistrement, 1801/1802, répétition), le traitement et l'adoption.
  apercu        nœud de l'aperçu en direct : apercu.png et apercu.json toutes les 2 s.
  exploration   tour automatique de tous les couloirs (pilote direct par /cmd_vel, ou guide).
  repetition    relais /points et /odom → /unitree/slam_mapping/* (répétition), attente de sujets.
  reconnaissance  reconnaitre(nuage, carte, dossier) : murs, passages et objets → reconnaissance.yaml
                et monde_scan.monde.yaml.
  evaluation    comparaison d'une reconnaissance à la vérité terrain (objectifs de 9.8), nuages
                synthétiques.

Le moteur du guide sur le vrai robot (commande 1102) est dans ws/src/g1_nav/g1_nav/moteur_unitree.py.
"""
