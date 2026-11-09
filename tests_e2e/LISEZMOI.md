# Tests de bout en bout de l'Atelier G1

Scripts sans fenêtre qui reprennent les critères de recette (sections 7, 9.10, 10, 11, 12 et 13 du plan),
et `tout.sh` qui les lance tous et affiche un bilan (agents Intégrateur et Testeur).

```bash
~/robot-g1/tests_e2e/tout.sh            # les 42 critères, puis « N / 42 »
~/robot-g1/tests_e2e/tout.sh 7 8        # seulement les critères 7 et 8
~/robot-g1/tests_e2e/tout.sh 11 12 13   # le scan intégré (le 11 garde sa session pour le 12 et le 13)
~/robot-g1/tests_e2e/tout.sh 16 17 18 19 20   # le vrai robot en répétition (vague 3, section 10 du plan)
~/robot-g1/tests_e2e/tout.sh 21 22 23 24 25 26 27 28 29 30   # la vague 4 (section 11 du plan)
~/robot-g1/tests_e2e/tout.sh 31 32 33 34 35 36   # la vague 5 (section 12.10 du plan)
~/robot-g1/tests_e2e/tout.sh 37 38 39 40 41 42   # la vague 6 (section 13.9 du plan)
~/robot-g1/tests_e2e/critere_08_service_robot.sh    # un critère seul, sortie à l'écran
```

| Script | Critère | Durée |
|---|---|---|
| `critere_01_monde_invente.sh` | lieu `essai` : 6 murs, un passage, 3 objets, 2 piétons ; `g1-lieu valider` sans erreur | 1 s |
| `critere_02_carte_sans_scan.sh` | `g1-monde generer` : .sdf, .pgm, .yaml, masque ; pixels connus ; tests `test_monde*.py` | 15 s |
| `critere_03_simulation.sh` | `g1-monde simuler --sans-fenetre` : `/odom` et `/points` (5 Hz au moins) en moins de 30 s | 10 s |
| `critere_04_point_a_b.sh` | salle placée par l'API, `POST /api/guide/aller` : `arrive`, à moins de 0,3 m | 1 à 2 min |
| `critere_05_chemin_secours.sh` | boîte posée dans le couloir nord (Gazebo seulement) : `bloque → detour → arrive` | 3 à 5 min |
| `critere_06_foule.sh` | 5 piétons, `g1-banc` sur 20 trajets : 90 % de réussite et un CSV | 20 à 40 min |
| `critere_07_scan_simule.sh` | tour des couloirs enregistré, `g1-carte-3d`, `g1-carte-2d` : recouvrement d'au moins 80 % | 3 à 4 min |
| `critere_08_service_robot.sh` | `g1-slam --faux` : déroulé 1801 → 1802 → 1804 → 1102 ; `MoteurUnitree` de l'accueil à b204 | 1 à 2 min |
| `critere_09_interface.sh` | `atelier/tests/test_serveur_navigateur.py` (Firefox sans fenêtre), sinon la liste cochée du journal | quelques min |
| `critere_10_point_entree.sh` | `g1-atelier` sert la page et l'API ; compté par `tout.sh` seulement si les 9 premiers réussissent | 5 s |
| `critere_11_scan_simu_api.sh` | scan intégré par l'API : `POST /api/scan/demarrer` (simu, exploration), aperçu mis à jour, « Fin » (`POST /api/scan/arreter`) après 30 s au moins et 80 % des couloirs, `termine`, recouvrement d'au moins 90 %, carte et nuage de la session, aucun processus restant | 3 à 5 min |
| `critere_12_carte_du_scan.sh` | vague 5 (la reconnaissance est retirée) : la session du 11 a sa carte 2D, son nuage 3D et son nuage d'affichage, sans `reconnaissance.yaml` ; étapes `carte_3d`, `carte_2d`, `nuage` ; nuages ignorés au plus 1 % ; nuage d'au moins 50 000 points, sol à 0,02 m de z = 0 ; précision 0,98 et recouvrement 0,90 face à la carte du monde ; `GET /api/scan/nuage` | 10 s (+ le 11 s'il n'a pas de session) |
| `critere_13_monde_du_scan.sh` | adoption de la session du 11 (« Utiliser cette carte ») : carte du scan telle quelle, nuage de l'étage, monde = carte extrudée de 1,5 m (`mondes/rdc_carte.stl`) avec les piétons, sans les murs dessinés ; `g1-lieu valider` ; `g1-monde generer` ; simulation sur le monde maillé et parcours du critère 4 jusqu'à une salle | 1 à 2 min (+ le 11 s'il n'a pas de session) |
| `critere_14_repetition_robot.sh` | `g1-scan demarrer --mode robot --repetition` (moins de 3 s), puis `arreter --attendre` : 1801 puis 1802 reçus par le faux service, `/unitree/slam_mapping/*` enregistrés, `termine` | 3 à 6 min |
| `critere_15_robustesse.sh` | « Fin » sans scan, « Scan » deux fois, flèches pendant un scan simulé (le robot avance, puis s'arrête seul quand on lâche), « Fin » pendant la préparation, mode robot sans robot (« Robot non détecté »), demandes absurdes : refus clairs, jamais d'erreur 500 ; puis l'écran de scan dans Firefox sans fenêtre (`test_serveur_scan_navigateur.py` : plein écran, nuage en direct, Fin, « Utiliser cette carte ») | 1 à 2 min |
| `critere_16_conteneur.sh` | conteneur `g1-jetson` sur le PC : image amd64 (réutilisée si à jour), `demarrer --local`, l'hôte voit `pont_g1`, `odom_vers_tf`, `guide`, `bt_navigator`, `map_server` et les états du pont et du repérage, verrou en moins de 3 s, arrêt propre (le pont envoie son arrêt), « réseau du robot introuvable » sans 192.168.123.x, jamais de ssh | 15 à 20 s (+ 0,5 min si l'image est à refaire) |
| `critere_17_pont.sh` | Gazebo `--jumeau`, navigation `--localisation externe --pont oui` et relais simple : aucun lien direct `/cmd_vel` → Gazebo ; `g1-guide aller hall_sud` par le pont et le faux G1 ; 7105 au bon format, 10 par seconde ; 0,9 m en 3 s puis arrêt ; plafonds, NaN, `/guide/stop`, `/pont/arret` | 1 min |
| `critere_18_reperage.sh` | répétition par l'Atelier : non repéré avant, « Repérer le robot » (1804 en (0, 0, 0), `repetition.pcd`), TF à moins de 0,1 m de la vérité malgré la dérive, perte puis reprise ; repère d'Unitree tourné (refus à la marque, puis repérage converti) | 1 min |
| `critere_19_niveau2.sh` | niveau 2 complet depuis l'Atelier : « Y aller » refusé avant le repérage, repérage, Nav2 actif, accueil → b204 à moins de 0,3 m en moins de 180 s, tout par le pont (7105 comptés, seul `pont_g1` écoute `/cmd_vel`), boîte dans le couloir nord puis b204 → accueil : `bloque → detour → arrive` ; aucun processus restant | 4 à 5 min |
| `critere_20_securite.sh` | sécurité sur la vraie chaîne de répétition, avec un témoin (jamais plus de 5 cm hors d'une consigne permise) : pont sans repérage, guide avant le repérage, consignes absurdes (NaN, infini, 1e9) par `/cmd_vel` et par les flèches, faux G1 muet, relocalisation perdue, ARRÊT et verrou pendant « Y aller », faux G1 arrêté (SIGTERM) puis relancé, pont tué (SIGKILL) puis relancé, demandes absurdes à l'API (français, jamais d'erreur 500) | 1 min 30 |
| `critere_21_point_principal.sh` | copies du demo : lieu sans principal en erreur et simulation refusée (409), deux principaux refusés (422), `g1-lieu migrer` (sauvegarde identique, second passage sans effet, le vrai demo refusé), `PUT …/principal {theta}` puis déplacé, simulation qui part du principal (`/odom` à 5 cm), repérage par défaut depuis le principal (1804 avec la pose convertie, aussi avec `repere_unitree` tourné) | 1 min |
| `critere_22_retour.sh` | simulation, `delai_avant_retour_s: 5` : b204 à moins de 0,3 m, puis retour seul au principal (0,3 m, 10°) en moins de 120 s ; événements `arrivee`, `retour`, `retour_arrive` conformes ; avec `retour: false`, le robot reste à b204 | 3 à 4 min |
| `critere_23_passant_immobile.sh` | scène `immobile_couloir` (5 essais) : 5 arrivées en moins de 180 s, sans détour ni contact, 0,20 m bord à bord au moins à chaque essai | 5 min |
| `critere_24_passants_croises.sh` | scènes `en_face` et `coupe_route`, piétons en pire cas (5 essais chacune) : 0 contact causé par le robot, 9 arrivées sur 10 au moins ; puis les mêmes avec `reaction: ecart` : 0 contact | 25 à 35 min |
| `critere_25_groupe.sh` | `groupe_couloir` (3 essais) : `attente_passage` et `passant_gene`, aucun détour, arrivée ; `groupe_reste` (2 essais) : attente de 20 s au moins puis détour par le couloir sud, 75 m au plus ; banc `foule` (20 trajets) : 90 % et 0 contact causé par le robot, colonnes du CSV de 11.3 | 25 à 35 min |
| `critere_26_accompagnement.sh` | scène `accompagnement`, faux visiteur : `depart` (et non `seul`), ralenti à 60 % au plus de la vitesse d'avant quand il traîne, `attente_visiteur` à plus de 3,5 m, `visiteur_retrouve`, arrivée ; second essai : il s'en va, `visiteur_perdu` 10 s après, retour au principal | 3 à 5 min |
| `critere_27_perdu.sh` | répétition, `/faux_slam/panne muet` en route : `perdu` en moins de 4 s, robot arrêté ; panne levée : `retrouve` et arrivée ; panne qui reste : `echec` 15 s après, message, pas de retour | 2 min |
| `critere_28_pilotage.sh` | Gazebo `--jumeau`, nœud pilotage (port libre, jeton) et Atelier : postures, confirmation double du portique, joystick avec homme mort (WebSocket coupé : arrêt en moins de 0,6 s), plafonds, gestes et refus 7401 et 7404 en français, voix, volume, LED, verrou avec le guide, interdits jamais envoyés au faux G1 | 1 min |
| `critere_29_danses.sh` | même montage : liste 7100 (401, 402, 403 interdites), 604 envoyée comme 550604 avec la zone libre, ARRÊT pendant une danse ; `exemple_kpop` sur le faux G1 (arm_sdk à 50 Hz, rampes, limites, taille et jambes jamais pilotées, pas dans les limites, LED et paroles à leur temps, ARRÊT au milieu) ; chorégraphie hors limites refusée ; aperçu 3D dans Firefox sans fenêtre | 2 min |
| `critere_30_equipe.sh` | les trois fichiers de l'équipe (exemples valides, fautes refusées en français, écrits puis relus par l'API), onglets dans Firefox sans fenêtre, personnalité publiée ; bout en bout : « je cherche la salle b204 » sur `/visiteur/texte` → `/robot/dire` et `/guide/aller` → b204 ; « bonjour » → réponse sans guidage ; phrase inconnue → repli | 1 min 30 |
| `critere_31_coque.sh` | accueil puis espace de travail en Simulation, en Réel et en répétition dans Firefox sans fenêtre ; à 1366 × 768, 1600 × 1000 et 1920 × 1080, pour chaque onglet et chaque commande (186 mesures) : la page ne défile pas, rien n'est coupé, tout élément cliquable peut être amené à l'écran, ARRÊT visible ; anciens hash ; thème clair ; barre d'outils de la répétition à 1100, 1280 et 1366 px avec la séance et « Vérifier le robot », rien de coupé (vague 6) (`outils_coque_e2e.py critere-31`) | 2 min |
| `critere_32_carte3d.sh` | carte 3D (WebGL) d'un nuage de test, par la coque (Réel › Placer) : l'accueil et une salle posés et orientés en 3D, `salles.yaml`, `lieu.yaml`, `depart_robot` et `itineraires.yaml` à jour, mêmes coordonnées dans le Plan 2D ; vues, zoom vers le pointeur, Annuler et Rétablir ; repli sans WebGL ; plus les tests de la carte seule (`test_carte3d_*.py`). **WebGL demande l'affichage X de la session (`DISPLAY=:1`)** : sans lui, « en attente » (77) | 2 à 3 min |
| `critere_33_scan_corrige.sh` | scan simulé sans reconnaissance : étapes `carte_3d`, `carte_2d`, `nuage`, carte propre (précision 0,98, recouvrement 0,90), même avec un sol incliné de 0,6°, des horodatages nuls et l'odométrie décalée de −138 s (`--refaire`) ; adoption : nuage de l'étage et monde maillé, Gazebo à 0,9 fois le temps réel au moins, contact avec le mur ; `g1-scan carte-unitree` en répétition | 5 min |
| `critere_34_pont_modes.sh` | pont et faux G1 : vitesse minimale (0,1 demandé → 0,2 envoyé), zones mortes, faux G1 assis → `pas_en_marche` et aucun pas, retour à `pret` en 501, course refusée, 7001 à 1 Hz ; `vitesse_max` sous 0,2 refusée, transmise à Nav2 | 1 min |
| `critere_35_camera.sh` | fausse source d'images → `camera_usb` → `/camera_poitrine/image/compressed` → flux MJPEG de l'Atelier → `g1-visiteurs` (YOLO) → `/visiteurs/detectes` avec les cadres ; vue Caméra dans Firefox ; caméra dans le conteneur, à blanc ; sans le modèle YOLO : « en attente » | 30 s |
| `critere_36_arret.sh` | ARRÊT global : guide en route (répétition), téléopération (simulation) et joystick du pilotage arrêtés en moins de 1 s ; verrou posé en répétition puis « Débloquer » ; un déblocage ne relance jamais l'ancien trajet (section 12.15 : « Bloquer » en route puis « Débloquer », aucun mouvement pendant 15 s ; verrou en ligne de commande ; faux G1 assis puis remis en marche ; joystick tenu) ; nœud pilotage injoignable ; bouton et touche Échap dans Firefox, « Y aller » grisé pendant le blocage, Échap avec un menu ouvert pendant l'attente du retour automatique (relecture du 01/11/2026) (`critere_36_outils.py`) | 3 min |
| `critere_37_diagnostic.sh` | vague 6, agent Diagnostic : « Vérifier le robot » contre le faux G1 (services de cartographie arrêtés au départ) et des vérifications système simulées (`ATELIER_DIAGNOSTIC_FAUX`) : services arrêtés vus, « Démarrer les services » (exactement deux 1001, lidar_driver et unitree_slam, seulement après confirmation ; 409 sans), câble absent, connexion inactive puis « Rétablir » (journal du faux contexte, rien de réel), tout bon, `g1-diagnostic --json` et son code, fenêtre du diagnostic dans Firefox (accueil et barre d'outils) ; jamais de ssh ni de ping vers le robot | 30 s |
| `critere_38_boite_noire.sh` | vague 6, agent Boîte noire : séance ouverte en répétition (manifeste, copie du lieu, enregistreur, badge dans Firefox) ; repérage, trajets, ARRÊT, Débloquer : chaque action notée ; ARRÊT en moins de 1 s et enregistreur sous 15 % d'un cœur ; bag des sujets légers (fréquences, ni nuages ni images) ; « Terminer la séance » et rapport (trajets arrivé et interrompu, ARRÊT, batterie, mouvement sans demande) ; place libre trop faible ; Atelier tué puis relancé (séance interrompue, rapport) ; journal du Jetson avant `g1-jetson arreter` ; export et liste. `E2E_GARDER_RAPPORT=DOSSIER` garde la séance | 3 min |
| `critere_39_borne.sh` | vague 6, agent Borne et orchestrateur : la borne dans Firefox à 390 × 844 et 1024 × 768 (salles, cartes de 64 px, salle cachée, confirmation, anti-rebond, suivez-moi, arrivée, retour, occupé, pause, son de la voix, code opérateur et 429), garde de la borne depuis l'adresse du réseau du PC (403, WebSocket fermé), adresse de la borne dans l'Atelier | 1 min 15 |
| `critere_40_voix.sh` | vague 6, agent Voix : le faux G1 et `g1-voix` : `/robot/dire` → 1003 bien formés (PCM 16 kHz en morceaux de 96 000 octets au plus, même stream_id, durée à 5 % près du WAV de Piper), trois phrases dans l'ordre, priorités haute et sécurité (1004 d'abord), volume 1006, taire, sortie robot_tts (1001) et borne (WAV servi), écart compté pour un 1003 mal formé, robot muet sans plantage | 40 s |
| `critere_41_demo.sh` | vague 6, agent Borne et orchestrateur : démo complète en simulation, trois visiteurs de suite (salutation, choix à la borne, accompagnement, arrivée à moins de 0,3 m, retour à l'accueil), statistiques, la voix (sortie borne) qui dit les salutations (assemblage), arrêt propre | 6 min |
| `critere_42_securite_demo.sh` | vague 6, agent Borne et orchestrateur : en répétition, une visite à chaque cas (ARRÊT, « Bloquer », faux G1 assis, pont tué, pilotage) : la démo se met en pause et rien ne repart seul (15 s sans mouvement, aucun 7105 non nul) ; choix refusé pendant la pause ; « Reprendre » loin de l'accueil refusé, « Ramener à l'accueil » | 3 min |

Critères 16 à 20 (vague 3, le vrai robot en répétition, section 10 du plan) : en répétition, la vérité terrain
est `/g1_jumeau/odom` (et non `/odom`, l'odométrie du relais). Options :
- `E2E_ARM64=1` (critère 16) : construit aussi l'image arm64 du Jetson sous émulation, vérifie l'image et fait
  tourner sa navigation sur le PC (2 min de plus) ;
- `E2E_NIVEAU2=1` (critère 16) : niveau 2 en répétition avec la navigation dans le conteneur, jusqu'à b204 ;
- `E2E_CONTENEUR=1` (critère 19) : le même parcours que le critère 19, la navigation tournant dans le conteneur
  (`g1-jetson demarrer --local`, `G1_SIMU=true`) : l'Atelier lance alors un `g1-guide` de test qui démarre le
  conteneur et l'arrête avec la répétition ;
- `E2E_PONT_REPLI=1` (critère 17) : montage de repli, si `navigation.launch.py` ne connaît pas
  `localisation:=externe`.
Outils : `critere_16_outils.py` (faux service sport minimal, observation depuis l'hôte), `outils_pont_e2e.py`
(relais simple, témoin du pont, mesures), `critere_18_outils.py`, `critere_19_outils.py` et
`critere_20_outils.py` (témoin des mouvements permis, pannes, relances).

Critères 21 à 30 (vague 4, section 11 du plan) : chacun est écrit par l'agent nommé ; tant que la pièce d'un
autre agent manque, il répond « en attente » (77) en disant laquelle. Nouveaux outils, un par agent :
`critere_21_outils.py`, `outils_passants_e2e.py`, `outils_guide_e2e.py`, `outils_pilotage_e2e.py`,
`outils_equipe_e2e.py`.

Critères 31 à 36 (vague 5, section 12.10 du plan) : chacun est écrit par l'agent nommé, sur des copies du demo ;
tant que la pièce d'un autre agent manque, il répond « en attente » (77). Un agent essaie ses paquets ROS compilés à
part avec `E2E_OVERLAY=~/robot-g1/ws/install_v5_<agent>` (chargé après `ws/install`, donc prioritaire), dans son
domaine : `E2E_DOMAINE=<domaine> E2E_PARTITION=v5_<agent> tests_e2e/tout.sh N` (section 12.11). Outils :
`outils_coque_e2e.py` (sous-commandes `critere-31`, `captures`, `contrastes`, `arret-navigateur`),
`critere_36_outils.py`, `outils_carte3d_e2e.py`, `outils_robot_e2e.py`, `outils_camera_e2e.py` ; le critère 33
réutilise `outils_scan_e2e.py`. **Lancez `tout.sh` depuis un terminal de la session graphique** (`DISPLAY=:1`) :
le critère 32 a besoin de WebGL, que Firefox sans fenêtre n'a qu'avec l'affichage X (aucune fenêtre ne s'ouvre ;
`commun.sh` retire `DISPLAY` pour Gazebo et RViz, et le critère 32 le rend à Firefox seul). Captures de la coque :
`.venv-projet/bin/python tests_e2e/outils_coque_e2e.py captures --api http://127.0.0.1:<port> --sortie <dossier>`.

Critères 37 à 42 (vague 6, section 13.9 du plan) : chacun est écrit par l'agent nommé, sur des copies du demo ;
tant que la pièce d'un autre agent manque, il répond « en attente » (77). Un agent essaie ses paquets ROS compilés à
part avec `E2E_OVERLAY=~/robot-g1/ws/install_v6_<agent>`, dans son domaine :
`E2E_DOMAINE=<domaine> E2E_PARTITION=v6_<agent> tests_e2e/tout.sh N` (section 13.11). Outils, un par agent :
`outils_diagnostic_e2e.py`, `outils_seance_e2e.py`, `outils_borne_e2e.py` et `outils_demo_e2e.py`,
`outils_voix_e2e.py`. Le critère 39 mesure la borne dans Firefox sans fenêtre ; aucun critère n'envoie de son ni de
commande au vrai robot (faux G1, simulation). Depuis l'assemblage de la vague 6, `commun.sh` met aussi les séances de la
boîte noire (`ATELIER_SEANCES`, une séance s'ouvre seule quand un critère ouvre l'espace en Réel) et les sons de la voix
(`ATELIER_VOIX_SONS`) dans le dossier du test.

Codes de sortie : 0 réussi, 1 échoué, 77 pas encore possible (une commande, une route ou un module manque).

Règles communes (`commun.sh`) :
- chaque script travaille dans un dossier temporaire, sur une copie de `lieux/demo` (`$ATELIER_LIEUX`) ;
- `ROS_DOMAIN_ID=36`, `IGN_PARTITION=atelier_e2e` (autres valeurs : `E2E_DOMAINE=30 E2E_PARTITION=nom tout.sh`),
  `G1_SLAM_FAUX=1` (jamais le vrai robot), pas d'écran ;
- tous les processus lancés (Gazebo, Nav2, serveur, faux service, ros2 bag) sont arrêtés à la fin,
  même après une erreur ou un Ctrl+C ; `GARDER_TRAVAIL=1` garde le dossier temporaire pour enquêter ;
- `outils_e2e.py` : attendre des sujets, suivre `/guide/etat`, lire `/odom`, appeler l'API,
  conduire le robot avec `MoteurUnitree`.

Scan intégré (critères 11 à 15, `outils_scan_e2e.py`) :
- les sessions de scan tournent détachées, dans leur propre groupe de processus : à la sortie, chaque
  script les arrête (SIGINT, comme « Fin »), puis tout processus lancé avec ses lieux (`ATELIER_LIEUX`) ;
  en cas d'échec, la fin du journal de chaque session (`~/robot-g1/journaux/scan_<lieu>_<session>.log`)
  est affichée ;
- le critère 11 garde sa session finie (sans l'enregistrement) dans
  `~/robot-g1/journaux/e2e_scan/domaine_<ROS_DOMAIN_ID>/` ; le 12 et le 13 la reprennent si elle a moins
  de 12 h et si `lieux/demo` n'a pas changé. `E2E_SESSION_SCAN=DOSSIER` impose une autre session ;
- réglages : `E2E_DUREE_SCAN` (30 s au moins avant « Fin »), `E2E_PART_TOUR` (0,8 : part des couloirs à
  parcourir avant « Fin »), `E2E_DUREE_MAX_SCAN` (600 s), `E2E_FIN_AUTO=1` (critère 11 sans « Fin » :
  l'exploration doit terminer le scan d'elle-même), `E2E_DUREE_REPETITION` (30 s d'enregistrement
  au critère 14) ;
- la reconnaissance des murs, passages et objets a été retirée à la vague 5 (section 12.5 du plan) : les
  critères 12 et 13 vérifient maintenant la carte, le nuage et le monde maillé, sans elle ; le critère 33
  ajoute le « damier » (sol incliné, horodatages nuls, odométrie décalée, comme le scan du 27/10).

Les journaux de `tout.sh` vont dans `~/robot-g1/journaux/e2e_<date>/`.
