"""Scan du vrai bâtiment : client slam_operate, faux service, cartes 3D et 2D, nuage 3D (agent Scan).

Modules (tout s'importe depuis le module, ex. from atelier.scan.carte2d import fabriquer_carte) :

  slam_client   client du service slam_operate du G1 (SDK Unitree) : 1801 scan, 1802 fin du scan,
                1804 relocalisation, 1102 aller, 1201/1202 pause/reprise, 1901 arrêt ; écoute de
                rt/slam_info (position) et rt/slam_key_info (is_arrived).
                ClientSlam(*connexion(faux)), SuiviArrivee, formats JSON « à vérifier sur le robot ».
  faux_slam     faux service slam_operate sur lo (mêmes commandes, déroulé vérifié) ;
                robot imaginaire, ou robot proxy de Gazebo (DeplacementGazebo) ; faux_partage()
                pour les tests (un seul serveur par processus).
  carte3d       ros2 bag (nuage + odométrie, /tf_static) → nuage .pcd réduit à 5 cm, sans piétons :
                fabriquer_pcd(enregistrement, sortie), assembler(...), lire_pcd, ecrire_pcd ; une seule
                base de temps (choisir_base_de_temps : horodatages, ou instants de réception).
  carte2d       nuage .pcd → carte Nav2 .pgm + .yaml (tranche 0,1–1,5 m au-dessus du plan du sol,
                ouverture par aire) : fabriquer_carte(points, emprise), fabriquer_carte_lieu(lieu, etage),
                comparer(...) (recouvrement et couverture de deux cartes).
  sol           plan du sol d'un nuage (RANSAC à graine fixe) : trouver_sol, hauteurs (vague 5).
  affichage     nuage d'affichage de la carte 3D (hauteur au-dessus du sol) : ecrire_nuage_affichage,
                nuage_du_monde (vague 5, section 12.5).
  salle         position du robot (/odom) → salle ou nœud : lire_position(), ajouter(...).
  commande      lignes de commande g1-slam, g1-carte-3d, g1-carte-2d et g1-salle.

Scan intégré (vague 2, section 9 du plan) :

  session       la commande g1-scan (demarrer, arreter, traiter [--refaire], etat, adopter,
                carte-unitree), le processus de la session (enregistrement, 1801/1802, répétition), le
                traitement (carte 3D, carte 2D, nuage) et l'adoption (carte, nuage, carte extrudée).
  apercu        nœud de l'aperçu en direct : apercu.png, apercu.json et apercu_nuage toutes les 2 s.
  exploration   tour automatique de tous les couloirs (pilote direct par /cmd_vel, ou guide).
  repetition    relais /points et /odom → /unitree/slam_mapping/* (répétition), attente de sujets.
  carte_unitree g1-scan carte-unitree : la carte d'Unitree (/unitree/slam_relocation/global_map) → le lieu.

Vague 5 (section 12.5 du plan) : la reconnaissance des murs, passages et meubles est retirée ; le monde
de simulation d'un étage scanné est sa carte 2D extrudée (atelier.monde.extrusion).

Le moteur du guide sur le vrai robot (commande 1102) est dans ws/src/g1_nav/g1_nav/moteur_unitree.py.
"""
