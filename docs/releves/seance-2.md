# Feuille de résultats : séance robot n° 2 (date : …)

Tutoriel : `docs/tutoriel-seance-2.md`. Remplis au fur et à mesure : ce que tu as vu, mot pour mot quand
c'est un message, et OK ou NON. Pour les mesures (étape M), **copie la sortie de la commande** dans les
notes libres, en bas.

**Version du robot (appli Unitree Explore) :**
**Services `unitree_slam` et `lidar_driver` actifs :**
**Batterie au début / à la fin :**
**Lieu : même croix que le 27/10 ? (oui / non) :**

| N° | Point vérifié | Attendu | Constaté | OK ? |
|---|---|---|---|---|
| A | Branchement, `g1-etat` | « Connecté », batterie | | |
| M0 | Pont en consignes brutes, `/pont/etat` | `pret`, `mode_robot.fsm` 501 en marche | | |
| M1 | Seuil en avant : 0,12, 0,15, 0,18, 0,2 m/s | vitesse atteinte de chaque essai ; seuil | | |
| M2 | Seuil de côté : 0,12 à 0,2 m/s, et −0,15 | vitesse atteinte ; seuil | | |
| M3 | Diagonale (0,1 ; 0,1) puis (0,14 ; 0,14) | immobile, puis marche (règle de la norme) ? | | |
| M4 | Seuil de rotation : 0,1 à 0,4 rad/s | vitesse atteinte ; seuil ; retard et montée à 0,3 | | |
| M5 | Latence et arrêt à 0,2 m/s | retard, montée, arrêt, dépassement (m) | | |
| M6 | Mode 7001 dans chaque posture | amorti, assis, accroupi, debout, marche, course ; « Démarrer » : 500 puis 501 ? | | |
| C2 | Pont normal : 0,1 m/s demandé | 7105 à (0,2 ; 0 ; 0), le robot marche | | |
| C3 | Rotation 0,3 rad/s, pas de côté 0,2 m/s | dans le bon sens | | |
| C4 | Pont tué pendant la marche | **arrêt seul en moins de 1 s** | | |
| C5 | Télécommande pendant que le pont envoie | **la télécommande gagne** | | |
| C6 | Robot assis, ordre de marche | `pas_en_marche` (« assis »), aucun pas ; retour en marche : `pret` sans mouvement | | |
| C7 | `/guide/stop`, puis verrou `/pont/arret` | arrêt net ; immobile sous verrou | | |
| D | `g1-jetson verifier`, `envoyer` | OK ; durée d'`envoyer` ; caméra « USB 5000 Mbit/s », groupe ; sujets du robot vus du conteneur | | |
| E1 | Repérer (1804) depuis l'Atelier | « Repéré » en moins de 20 s ; texte de la réponse | | |
| E2 | `/unitree/slam_relocation/odom` et `/points` | fréquences | | |
| E3 | Précision, 3 mesures au mètre ruban | moins de 10 cm | | |
| E4 | `g1-scan carte-unitree` pendant Repérer | `rdc_unitree.pcd` écrit ; nombre de points ; ou « rien reçu » | | |
| F1 | Y aller « Essai à 2,5 m » à 0,2 m/s | `arrive` ; durée ; écart | | |
| F2 | Retour seul à l'accueil, rotation finale | une seule rotation ; écart à la flèche (°) | | |
| F3 | ARRÊT à mi-chemin, puis Y aller, puis Débloquer | arrêt net ; « Débloquer » ; immobile tant que bloqué | | |
| F4 | Écart à l'arrivée sur la croix | moins de 30 cm | | |
| F5 | Spin de 90° (si F2 oscille) | dépassement (°) ; réglages du guide ; une seule rotation ensuite | | |
| G1 | Images de la caméra sur le PC | environ 10 par seconde ; taille d'une image | | |
| G2 | Vue Caméra de l'Atelier, lumière et ombre | image nette, ni noire ni blanche | | |
| G3 | Position de la caméra sur le robot | x, z (m), tangage (°) | | |
| G4 | `g1-visiteurs` : cadres sur l'image | un cadre par personne | | |
| G5 | Distances à 1, 2, 3 et 4 m | distances affichées ; correction calculée | | |
| G6 | Champ de vision à 1 m | largeur vue (m) ; champ (°) | | |
| H | Nouveau scan lent (sans l'adopter) | durée, distance, points ; murs, tables ; ni dédoublé ni tourné | | |
| P1 | Pilotage : prendre la main, Démarrer | mode lu | | |
| P2 | Joystick à peine incliné | marche à 0,2 m/s | | |
| P3 | ARRÊT, joystick toujours tenu | arrêt ; le manche tenu ne relance pas le robot | | |
| P4 | Danse 604 depuis 501, au portique | durée ; mode à la fin (501 ou 801) | | |
| Fin | Journal du conteneur, `g1-jetson arreter` | arrêt propre, conteneur retiré | | |

## Notes libres

(sorties des mesures copiées telles quelles, messages d'erreur mot pour mot, ce qui a surpris, durées…)
