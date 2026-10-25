# Journal de l'Atelier G1

Décisions, écarts aux contrats et travail restant, par agent et par phase. Chaque agent ajoute sa section à la fin.
Le plan de référence est `docs/plan-atelier-multi-agents.md` ; ses contrats (section 4) font foi.

## Intégrateur (phase 0), 25/10/2026

- **Contrats figés** : schémas draft-07 dans `atelier/lieu/schemas/` (lieu, monde, salles, itineraires, zones, plus carte pour les `cartes/*.yaml`). Ajouts au plan : règles complémentaires (4.1), lancements ROS 2 (4.5), interface `Moteur` (4.6).
- **Décisions** : une salle a un nœud de même id ; identifiants `^[a-z0-9][a-z0-9_-]{0,39}$` ; un mur ne déborde pas de ses bouts, et un passage est l'écart entre deux murs alignés ; piéton `aller_retour: false` = boucle ; `--lieu demo` désigne `~/robot-g1/lieux/demo` (`atelier.chemin_lieu`, variable `ATELIER_LIEUX`) ; le masque Keepout a son `.yaml` (`cartes/<etage>_interdit.yaml`).
- **Attributions** : `bin/g1-atelier` à l'agent Interface ; `bin/g1-monde generer` et `simuler` à l'agent Monde ; `g1_nav/moteur_unitree.py` à l'agent Scan ; `lieux/demo` à l'agent Données. Les schémas et `moteurs.py` restent à l'intégrateur.
- **Lieu demo** : 30 × 20 m. Le couloir sud (y = 7) et le couloir nord (y = 13) sont reliés par le hall (accueil en 2,5 ; 10) et par la liaison est. Il compte 5 salles (vie_scolaire, infirmerie et cdi au sud ; amphi et b204 au nord), 13 nœuds en boucle (couloirs de 3 à 6,5 m), 18 murs, 9 objets, 2 piétons, une zone interdite (escalier) et une zone lente (hall).
- **Chemins** : accueil → b204 fait 21,5 m par le nord et 40,5 m par le sud. Pour tester le détour, bloquer le couloir nord entre amphi et couloir_nord_1, par exemple avec une boîte de 0,5 × 2,9 m centrée en (12 ; 13).
- **ROS 2** : `g1_sim` (ament_cmake) et `g1_nav` (ament_python) compilent, et `colcon test` passe. Leurs lancements sont provisoires : ils déclarent les arguments du contrat, les affichent et s'arrêtent.
- **pytest** : pytest 7.4.4 est installé dans `.venv-projet`, car le pytest 6.2.5 du système plantait au chargement du plugin anyio. Commande : `.venv-projet/bin/python -m pytest atelier/tests` (`pytest.ini` limite la recherche au paquet).
- **Copies de travail (worktrees)** : `atelier` est installé en mode éditable sur `~/robot-g1`. Dans une copie, lancez les commandes depuis sa racine (`python -m pytest`), ou faites `export PYTHONPATH=<copie>:$PYTHONPATH` (pour `ros2 launch`, par exemple) ; sinon, c'est le `atelier` de `~/robot-g1` qui est importé.
- **Tests** : `atelier/tests/test_contrats.py` (45 tests : schémas, erreurs refusées, cohérence et géométrie du demo) et `ws/src/g1_nav/test/test_moteurs.py` (9 tests) passent.
- **Reste à faire** :
  - le lieu demo n'a encore ni carte ni SDF : l'agent Monde les générera. En phase 1, les agents Navigation et Simulation fabriquent leurs fichiers de test dans un dossier temporaire, jamais dans `lieux/demo` ;
  - la licence des paquets ROS est à choisir (TODO dans `package.xml`) ;
  - l'encodage du masque des zones lentes est à fixer en phase 3.

## Données (phase 1), 25/10/2026

- **Livré** : `atelier/lieu/` (`modeles.py`, `fichiers.py`, `conversions.py`, plus `validation.py`, `verification.py`, `geometrie.py`, `commande.py`) et `bin/g1-lieu` (alias `gl-lieu`) : `creer ID --nom NOM`, `valider --lieu L`, et en plus `liste`. L'API publique est décrite en tête de `atelier/lieu/__init__.py` : tout s'importe depuis `atelier.lieu`.
- **Validateur de schémas maison** : le Python du système (nœuds ROS 2) n'a pas `jsonschema`. `validation.py` contient donc un petit moteur draft-07 limité aux mots-clés de nos schémas (il refuse les autres). Un test le compare à `jsonschema` sur 600 variantes de chaque fichier du demo : aucun désaccord. Il refuse aussi les nombres infinis ou NaN.
- **Deux niveaux** : les erreurs propres à un fichier (schéma, ids en double, polygone qui répète son premier sommet, mur de longueur nulle, point hors emprise, couloir vers un nœud inconnu) bloquent `charger_*` et `enregistrer_*` (`ErreurLieu`). Les règles entre fichiers (salle ↔ nœud, accueil, couloirs de 8 m au plus dans l'espace libre, zones interdites, masque de même taille que la carte) ne bloquent rien : `verifier_lieu` et `valider_lieu` renvoient un `Rapport` (erreurs et avertissements), pour qu'un lieu en cours de dessin puisse être enregistré.
- **Fichiers** : `salles.yaml`, `itineraires.yaml` et `zones.yaml` absents sont lus comme vides (avertissement dans `valider`). Une clé YAML en double est refusée, avec sa ligne. L'écriture est atomique et perd les commentaires écrits à la main (un en-tête le signale). Les parties courtes sont écrites sur une ligne, comme dans le demo.
- **Conversions** : un pixel couvre [x0, x0 + rés.[ ; le bord droit et le bord haut de l'image sont dehors (`dans_image`). La tolérance est de 1e-6 pixel, pour que 0.15 / 0.05 donne bien 3. Une `origin` avec un lacet non nul est refusée. Ajouts utiles aux agents Monde et Scan : `info_carte_pour_emprise` (30 × 20 m → 602 × 402 px, origine −0,05), `centres_pixels`, `bornes_carte` (Leaflet), `lire_pgm`, `ecrire_pgm`, `enregistrer_carte`.
- **Lieu neuf** (`creer_lieu`) : un étage `rdc`, accueil en (1, 1), salle et nœud `accueil`, monde de 20 × 15 m entouré de 4 murs `ext_*`.
- **Lieu demo** : il passe la validation tel quel, il n'a pas été modifié. Seul avertissement : pas encore de carte (à générer par l'agent Monde).
- **Tests** : 6 fichiers `atelier/tests/test_lieu_*.py`, 204 tests, plus les 45 de l'intégrateur : 249 tests passent avec `.venv-projet/bin/python -m pytest atelier/tests`. Ils travaillent dans des dossiers temporaires (`copier_lieu`, `ATELIER_LIEUX`).
- **Reste** : vérifier le graphe sur la carte d'un étage scanné ne regarde que les pixels traversés, pas la largeur du robot ; aucune règle pour le masque des zones lentes (format à fixer en phase 3).

## Monde (phase 1), 25/10/2026

- **Livré** : `atelier/monde/` (`carte.py`, `zones.py`, `sdf.py`, `pietons.py`, `commande.py`) et `bin/g1-monde` (alias `gl-monde`) : `generer --lieu L --etage E` et `simuler --lieu L --etage E [--sans-fenetre] [--monde F.sdf] [--afficher]`. API en tête de `atelier/monde/__init__.py` ; `generer(lieu, etage)` renvoie un compte rendu (`.texte()`, `.vers_dict()`).
- **Carte** : tranche de 0,1 à 1,5 m, 0,05 m par pixel, marge d'un pixel inconnue (205) sauf sous un mur. Un pixel est occupé dès qu'un mur ou un objet le recouvre en partie (au moins 1 mm) : un mur de 0,15 m fait 4 pixels, un mur en biais n'a pas de trou en diagonale. Les piétons n'y sont pas. Demo : 602 × 402 px, origine (−0,05 ; −0,05).
- **Masque Keepout** (`cartes/<etage>_interdit.pgm` + `.yaml`) : 0 dans les zones interdites (centre du pixel dans le polygone), 254 ailleurs. Il est toujours écrit, même sans zone. Étage `source_carte: scan` : la carte n'est pas touchée, et le masque s'aligne sur la carte du scan.
- **SDF** : le monde Gazebo porte le nom de l'étage (`rdc`), comme `couloir.sdf` → `couloir` chez g1_sim. Modèles statiques nommés par leur id (murs, objets, meubles en boîtes et cylindres), plus `sol`. Plugins Physics, SceneBroadcaster, UserCommands et Sensors (ogre2).
- **Piétons** : un `<actor>` sans maillage provoque une erreur dans Fortress (`Invalid mesh filename extension`), et la physique ignore ses `<link>`. `generer` écrit donc `mondes/pieton.dae` : une silhouette COLLADA avec un os et une animation immobile, désignée par un chemin relatif. Le SDF doit donc être chargé depuis son fichier, pas en texte. Trajectoire : points tous les 0,5 m, vitesse constante, boucle sans fin.
- **Vérifié dans Gazebo** : un gpu_lidar posé à l'accueil voit les murs à 1 cm près et le piéton sud là où `position_pieton` le place (test automatique). Les piétons n'ont pas de collision physique, et Fortress ne publie pas leur position (absents de `/world/<etage>/pose/info`). Pour les suivre : `atelier.monde.position_pieton(pieton, t)` avec le temps simulé (même calcul que le SDF ; `atelier/serveur/pietons.py` fait le même).
- **Demo généré** : `lieux/demo/mondes/rdc.sdf`, `pieton.dae`, `cartes/rdc.*`, `cartes/rdc_interdit.*`. `g1-lieu valider --lieu demo` : aucune erreur, aucun avertissement.
- **Tests** : `atelier/tests/test_monde_carte.py`, `test_monde_sdf.py` et `test_monde_commande.py` (57 tests, 10 s, Gazebo compris). Effet de bord : trois tests de l'agent Données supposent un demo sans carte, ils échouent maintenant (`test_lieu_fichiers.py::test_copier_lieu`, `test_lieu_verification.py::test_le_demo_est_valide` et `::test_masque_absent`). Ils sont à mettre à jour par l'agent Données.
- **Reste** : `simuler` n'est testé qu'avec `--afficher` (le lancement g1_sim n'était pas prêt) ; masque des zones lentes (format à fixer en phase 3) ; bonus `mjcf.py` non commencé.

## Simulation (phase 1), 25/10/2026

- **Livré** (`ws/src/g1_sim`) : `models/g1_proxy/model.sdf`, une boîte de 0,45 × 0,30 × 1,30 m et 35 kg, avec le centre de masse à 0,4 m. Elle a les plugins VelocityControl et OdometryPublisher (2D, odom → base_link, 50 Hz), et un gpu_lidar à 1,2 m (360 × 16 points, de −7° à +52°, de 0,1 à 40 m, 10 Hz, repère `lidar`). Aussi : `config/pont_gz.yaml` (/clock, /cmd_vel, /odom, /tf, /points) et `launch/simulation.launch.py` (arguments du contrat 4.5). Monde de test : `worlds/couloir.sdf` et `couloir.monde.yaml`.
- **Repères** : base_link est au sol, au pied de la boîte. L'odom de Gazebo est le repère du monde, donc `map → odom` = identité est juste : le test le vérifie sur la carte du demo. g1_sim ne publie pas `map → odom` : c'est g1_nav qui s'en charge (contrat 4.2). robot_state_publisher reçoit un URDF fabriqué depuis la pose du capteur dans model.sdf, qui reste la seule source.
- **Autres décisions** : sujets Gazebo sous `/model/g1_proxy/…`. Le corps du robot a le drapeau de visibilité 0x2, que le LiDAR masque (sinon il voit sa propre boîte). Frottement de 0,01, car la vitesse est imposée. Le robot apparaît par `ros_gz_sim create`, qui attend le serveur, 1 cm au-dessus du sol. Si Gazebo s'arrête ou si le robot n'apparaît pas, tout le lancement s'arrête.
- **Départ** : `depart_robot` vient de `<lieu>/mondes/<etage>.monde.yaml`, validé par atelier.lieu. À défaut, `<nom>.monde.yaml` à côté du .sdf de `monde:=` (ajout au contrat), sinon (0, 0, 0). Si le monde manque, le lancement s'arrête avec le code 1 et propose `g1-monde generer`.
- **Piétons** : le gpu_lidar voit les actor, avec le `pieton.dae` de l'agent Monde (50 à 70 points à 2 m, là où `position_pieton` les place) comme avec la peau Fuel standard : pas besoin de cylindre qui suit. Solution de repli, essayée et qui marche : un `<link>` avec un cylindre visuel dans l'`<actor>`. Les piétons n'ont pas de collision : le robot peut les traverser.
- **Pour la Navigation** : le rayon le plus bas est à −7°. Un obstacle de hauteur h n'est donc plus vu à moins de (1,2 − h) / tan 7° : 3,7 m pour une table, 1,6 m pour une boîte de 1 m. Une boîte de test de détour devrait faire au moins 1,2 m de haut. VelocityControl garde la dernière consigne : pour arrêter le robot, il faut publier une vitesse nulle.
- **Vérifié** : `g1-monde simuler --sans-fenetre` sur une copie du demo publie /points en 4 s (critère 3 : moins de 30 s).
- **Tests** (`ws/src/g1_sim/test/`, 25 tests en 50 s environ, tous passent, aussi sous `colcon test` avec le lint). `test_fichiers.py` tourne sans Gazebo. `test_simulation.py` : /points à 10 Hz ; vx = 0,3 pendant 3 s donne 0,90 m ; arrêt contre la boîte et contre le mur, au millimètre ; points à 8 mm des surfaces, à travers odom → base_link → lidar. `test_demo.py`, sur une copie de `lieux/demo` : 99 % des points tombent sur les obstacles de la carte, avant et après un quart de tour. Avec aussi `test_pietons.py`. Isolement : `ROS_LOCALHOST_ONLY=1`, `IGN_IP=127.0.0.1`.
- **Reste** : le mode avec fenêtre (`sans_fenetre:=false`) n'est pas essayé (règle : jamais de fenêtre). Sur le robot, vérifier l'orientation du MID-360 dans la tête : s'il est tourné vers le bas, changer la `<pose>` du capteur dans model.sdf, et le TF suivra.

## Interface (phase 1), 25/10/2026

- **Livré** : `atelier/serveur/` (`main.py`, `routes/` lieux, monde, plan, simulation, scan ; `processus.py`, `pont_ros.py`, `pietons.py`, `etat.py`, `communs.py`), `atelier/web/` (8 onglets en modules ES sans compilation ; Leaflet 1.9.4 et three.js 0.160.0 copiés dans `vendor/`), `bin/g1-atelier [--port 8000] [--sans-navigateur] [--hote H]` et l'alias `gl-atelier`. Détails : `atelier/web/LISEZMOI.md`.
- **API** (section 4.4) : erreurs toujours en JSON `{detail, erreurs?, sortie?}`, en français. Les PUT valident avec `valider_donnees`, écrivent par les dataclasses d'`atelier.lieu` et renvoient le rapport de `valider_lieu`. `GET …/carte.yaml` rend du JSON avec la taille de l'image et ses bornes en mètres, que Leaflet (CRS.Simple, lat = y, lng = x) place telles quelles.
- **Ajouts au contrat** : `GET /api/etat` ; `PUT /api/lieux/{id}` (étages, accueil) ; `GET /api/lieux/{id}/verification` ; `PUT …/salles?synchroniser=true` (nœud de même id créé ou déplacé, salle accueil recopiée dans lieu.yaml) ; `GET /api/scan/etat` et `POST /api/scan/faux-service/arreter` ; champs `fenetre` et `navigation` de `simulation/demarrer`, `lieu` et `etage` du scan ; `ros.nav2`, `simulation` et `temps_sim` dans `/ws/etat`.
- **Processus** : `g1-monde simuler --sans-fenetre`, puis `g1-guide navigation --simu`, chacun dans son groupe de processus (SIGINT, puis SIGTERM, puis SIGKILL du groupe entier), journaux `journaux/atelier_<rôle>_*.log`. Tout s'arrête avec le serveur (Ctrl+C). Avec `faux`, `scan/debut` lance `g1-slam faux-service` s'il ne tourne pas. Commandes cherchées dans `$ATELIER_BIN` (fausses commandes dans les tests).
- **Pont ROS 2** : nœud rclpy dans un fil, avec son propre contexte (il laisse Ctrl+C à uvicorn). Il écoute /odom, /guide/etat et /clock, publie /guide/aller et /guide/stop, et interroge `/bt_navigator/get_state` : « Y aller » reste grisé tant que Nav2 démarre. Piétons à l'écran : `atelier.monde.position_pieton` au temps de /clock, car Fortress ne publie pas leur position.
- **Assemblage essayé** (copie du demo, domaine 34) : depuis le navigateur, Fabriquer la carte → Lancer la simulation → Nav2 prêt en 8 s → Y aller b204 → « Arrivé » en 60 s environ, robot et piétons en direct sur la carte et en 3D. Lors d'un autre essai : bloque → detour → echec dans le hall. À régler côté Navigation. Le vrai `g1-slam --faux` marche aussi : 1801 et 1802, puis `carte_unitree` notée dans lieu.yaml.
- **Tests** (`atelier/tests/test_serveur_*.py`, 69 tests en 25 s environ) : API avec TestClient sur une copie du demo, y compris le vrai `g1-monde generer` ; processus, arrêt de groupe, piétons ; pont ROS 2 avec faux /odom, faux guide et faux Nav2 ; syntaxe et imports des modules JS (esprima) ; démarrage réel de g1-atelier, curl, puis Ctrl+C. Parcours complet de la recette 9 dans Firefox sans fenêtre (geckodriver en WebDriver simple, pas Playwright), sauté si Firefox manque.
- **Pour l'intégrateur** : compiler g1_sim et g1_nav dans `ws/install` (en attendant, g1-atelier charge `ws/install_g1_sim` et `ws/install_g1_nav`). Ajouter `httpx` (TestClient) et `esprima` à l'installation de `.venv-projet`. Le guide accepte /guide/aller avant que Nav2 soit actif et répond aussitôt echec.
- **Reste** : pas d'onglet Pilotage (dans le schéma de la section 3, absent de la fiche) ; masque des zones lentes non affiché ; un seul étage visible à la fois ; vérifications à la main ci-dessous.

### Interface : vérifications à faire à la main dans le navigateur

1. `g1-atelier` ouvre http://localhost:8000. La pastille en haut à droite dit « Connecté · ROS 2 actif ».
2. Lieux : créer « Essai ». L'onglet Monde s'ouvre avec 4 murs.
3. Monde : tracer un mur (cliquer-glisser), poser une table et la tourner de 90°, faire un piéton (3 clics, puis « Terminer le trajet »), couper un passage. Essayer Ctrl+Z et Ctrl+Y. La vue 3D suit et tourne à la souris. Enregistrer.
4. Carte : « Fabriquer la carte ». L'image apparaît, et les coordonnées en mètres (en bas à gauche) suivent la souris.
5. Salles : « Ajouter une salle », en cliquant puis en glissant vers la porte. Remplir nom, alias et phrase, puis déplacer la salle et tourner sa poignée. Enregistrer : dans Itinéraires, un nœud vert du même nom apparaît.
6. Itinéraires : relier deux nœuds à plus de 8 m : le trait devient rouge et un message s'affiche. « Couper en deux », puis enregistrer.
7. Zones : tracer une zone interdite et une zone lente, déplacer un sommet, enregistrer, puis fabriquer à nouveau la carte.
8. Simulation : « Lancer ». « Le guide démarre… » s'affiche, puis les boutons « Y aller » s'activent. « Y aller » : le robot bouge sur la carte et en 3D, et l'état du guide change. ARRÊT l'arrête. « Arrêter la simulation », puis `ps` : il ne reste plus de Gazebo.
9. Scan : « Faux service » coché, « Démarrer » puis « Terminer le scan » : messages de réussite. Puis « Arrêter le faux service ».
10. Tablette (ou fenêtre étroite) : tout passe en une colonne, le dessin au doigt marche et pincer zoome. Quitter un onglet modifié demande une confirmation.

## Navigation (phase 1), 25/10/2026

- **Livré** (`ws/src/g1_nav`) : `routeur.py` (A* sur `itineraires.yaml`, couloir bloqué 120 s, alias de salle acceptés en plus des ids), `guide.py` (logique `Guide` sans ROS + nœud `/guide/aller|stop|etat`), `moteur_nav2.py` (`goThroughPoses`), `banc.py`, `odom_vers_tf.py`, `commande.py`, `config/nav2_g1_simu.yaml` et `nav2_g1_reel.yaml` (ne diffèrent que par les vitesses et l'horloge, vérifié par un test), `config/naviguer_par_poses.xml`, `launch/navigation.launch.py`. Commandes `g1-guide navigation|aller|stop|etat` et `g1-banc` (alias `gl-*`) ; elles prennent `ws/install/g1_nav` s'il existe, sinon `ws/install_g1_nav`.
- **Guide** : `bloque` après 3 s sans progrès (5 s juste après un départ), `detour` après 8 s : annule, bloque le couloir où est le robot (le plus proche de sa position TF), repart du nœud déjà passé. Un abandon de Nav2 est d'abord relancé une fois, puis donne un détour ; 3 détours au plus. Moteurs : `nav2`, `unitree` (MoteurUnitree de l'agent Scan, créé avec `noeud=` ; message clair s'il manque) et `factice` (ajout, pour les essais sans Gazebo).
- **Réglages trouvés en essayant dans Gazebo** (écarts à la fiche, voir les commentaires des fichiers) : voxel_layer seulement dans la carte locale et de 1,125 à 1,9 m (le LiDAR à 1,2 m ne voit pas sous −7° : les voxels bas ne s'effaçaient jamais) ; carte locale vidée chaque seconde par l'arbre de Nav2 (sinon des obstacles fantômes bloquaient le robot) ; nœud passé à 1,5 m (sinon le robot revenait en arrière) ; inflation 0,4 m en local mais 1 m en global (chemin au milieu des couloirs, hors du cercle « ralentir ») ; Keepout sur la carte globale seulement ; `reste_m` = ligne droite par les poses restantes (la distance de Nav2 remonte à chaque recalcul) ; pas de `name=` sur le nœud guide dans le lancement (il renommait aussi le nœud de nav2_simple_commander, qui ne recevait plus le retour).
- **Résultats, lieu demo copié, sans fenêtre** : critère 4, accueil → b204 arrivé en 53 s à 0,07 m ; critère 5, boîte 0,5 × 2,9 × 2 m en (12 ; 13) : `en_route → bloque → detour → arrive` en 176 s à 0,03 m ; banc avec 5 piétons (3 ajoutés au demo) : 20 / 20 trajets réussis, 48 s en moyenne, 1 arrêt.
- **Tests** : `cd ws/src/g1_nav && python3 -m pytest test` (environnement ROS chargé) : 90 passent, 4 sautés, en 9 s, aussi sous `colcon test`. Essais Gazebo (5 min) : `G1_NAV_SIMULATION=1 python3 -m pytest test/test_simulation.py`, ou `python3 test/test_simulation.py aller|detour|tous`.
- **Reste** : zones lentes non branchées (masque `_lent`, phase 3) ; la distance aux piétons du banc est calculée depuis `monde.yaml` et le temps simulé, pas vérifiée contre Gazebo ; dans la simulation, un obstacle de moins de 1,1 m absent de la carte n'est vu que par le Collision Monitor ; `moteur:=unitree` non essayé (il parle à eno2 sans `G1_SLAM_FAUX=1`) ; sur le robot : réglages réels, hauteur des voxels selon le montage du MID-360, cadres de `/unitree/slam_relocation/odom`.

## Scan et testeur (phase 1), 25/10/2026

- **Livré** : `atelier/scan/` (`slam_client`, `faux_slam`, `carte3d`, `carte2d`, `salle`, `commande`), `g1_nav/moteur_unitree.py`, `bin/g1-slam`, `g1-carte-3d`, `g1-carte-2d`, `g1-salle` (alias `gl-*`), `tests_e2e/` (10 scripts, `commun.sh`, `outils_e2e.py`, `tout.sh`). Tests : `atelier/tests/test_scan_*.py`, 33 tests, tous passent (2 min).
- **Suppositions à vérifier sur le robot** (chacune isolée dans une fonction de `slam_client.py`) : 1801 `{"slam_type": "indoor"}` ; 1802 `{"address": "/home/unitree/<nom>.pcd"}` (dossier supposé) ; 1804 `{x, y, z, q_x, q_y, q_z, q_w, address}` ; 1102 `{"targetPose": {...}, "mode": 1}` ; réponse `{"succeed", "errorCode", "info"}` ; position dans slam_info sous `currentPose` ; `is_arrived` dans slam_key_info (cherché à tout niveau du JSON), publié en continu ou seulement à l'arrivée ; 1201 arrête le robot, et on renvoie 1202 après un nouveau 1102 au cas où la pause persiste ; domaine DDS 0 sur eno2 ; repère et hauteur du LiDAR de `/unitree/slam_mapping/points`.
- **Faux service** (`g1-slam faux-service [--gazebo] [--relocalise]`, puis `g1-slam ... --faux`) : sur lo, domaine `$ROS_DOMAIN_ID`. Il refuse les commandes hors déroulé (1802 sans 1801, 1804 sur une carte inconnue, 1102 sans 1804 ou à plus de 10 m). Avec `--gazebo`, il conduit le robot proxy en ligne droite (`/cmd_vel`) et s'arrête devant un point de `/points`. Il affiche « prêt » (avec flush) : la route `/api/scan` de l'agent Interface s'en sert.
- **MoteurUnitree(noeud=None, client=None, faux=None, …)** : tronçons de 8 m au plus, 1102 dans un fil de fond. Un `is_arrived` vrai ne compte que si un faux a été reçu depuis l'envoi, ou si le robot est près de la cible et immobile (`SuiviArrivee`). Le faux service est choisi par `G1_SLAM_FAUX=1`, ou par `use_sim_time` du nœud du guide. En simulation avec `moteur:=unitree`, lancer d'abord `g1-slam faux-service --gazebo --relocalise`.
- **carte3d** : le bag est recalé par l'odométrie et `/tf_static` (sinon `--capteur`, 0 0 1,2 par défaut), réduit à 5 cm, puis les piétons sont retirés : une colonne que les rayons horizontaux traversent souvent est mobile. Les champs de PointCloud2 sont lus directement, car `read_points_numpy` de Humble refuse le nuage de Gazebo.
- **carte2d** : sol au 1er centile des z, puis une ouverture **par aire** (taches de moins de 4 pixels) au lieu de l'ouverture classique, qui effacerait les murs vus d'un seul côté. L'emprise est celle du monde quand il existe. Sans `--sortie`, `cartes/<etage>.yaml` est écrit et l'étage passe à `source_carte: scan`.
- **Recouvrement** (critère 7) : part des pixels occupés du scan qui tombent sur un obstacle de la carte du monde, à 1 pixel près. Résultats sur le demo simulé : 98,8 % de recouvrement, et 66 % de couverture (la part inverse : les pièces ne sont pas visitées).
- **tests_e2e** : `ROS_DOMAIN_ID=36` et `IGN_PARTITION=atelier_e2e`, sans `ROS_LOCALHOST_ONLY=1` : sur lo, CycloneDDS manque de numéros de participant au-delà d'une dizaine de nœuds, et Nav2 plante. Résultat de `tout.sh` le 25/10 à 15 h 45 : **10 / 10**. Le critère 6 prend 20 min ; le test navigateur du critère 9 utilise de fausses commandes g1-*, et la vraie chaîne API → Gazebo → guide est couverte par le critère 4.
- **Reste** : toutes les suppositions ci-dessus, à vérifier avec `g1-slam` sans `--faux`. `g1-salle` n'a pas encore été essayé sur `/unitree/slam_relocation/odom`. Hors de mon périmètre : 3 tests de l'agent Données échouent (`test_copier_lieu`, `test_le_demo_est_valide` et `test_masque_absent`), car ils supposent que `lieux/demo` n'a pas de carte, alors qu'il en a une maintenant.

## Intégrateur (assemblage), bilan de la vague 1, 25/10/2026

- **Compilation unique** : `cd ws && colcon build --symlink-install --packages-select g1_sim g1_nav` dans `ws/install`, chargé par `setup/env.sh` (`local_setup.bash`). Les dossiers `ws/build_*`, `ws/install_*` et `ws/log_*` des agents sont supprimés ; livox_ros_driver2 et fast_lio n'ont pas été touchés. Les replis vers `install_<paquet>` de `g1-guide`, `g1-banc`, `g1-atelier` et `commun.sh` restent, inoffensifs.
- **Corrections d'assemblage** : les 3 tests de l'agent Données qui supposaient un demo sans carte (`test_copier_lieu` compare maintenant tout le contenu copié ; `test_le_demo_est_valide` attend zéro avertissement, puis celui de la carte manquante une fois `cartes/` vidé ; `test_masque_absent` retire le masque de la copie). `tests_e2e/commun.sh` accepte `E2E_DOMAINE` et `E2E_PARTITION` (36 et `atelier_e2e` par défaut). `setup/installer_utilisateur.sh` installe pytest 7.4.4, httpx, esprima, jsonschema et le paquet `atelier` en mode éditable (venv et python3 du système). Aucun format, sujet ni argument de lancement n'a dû être changé.
- **Plan** : la section 4 note les ajouts de la phase 1 acceptés (sous-commandes, routes de l'API, `carte.yaml` en JSON, `moteur:=factice`, nom du monde Gazebo, constructeurs des moteurs).
- **Tests** : `atelier/tests` 408 réussis en 2 min 18 ; `colcon test` g1_sim et g1_nav : 136 tests, 0 échec, 4 sautés (copyright, MoteurUnitree absent, 2 essais Gazebo longs couverts par les critères 4 et 5).
- **Parcours principal sur `lieux/demo`**, sans fenêtre (domaine 30) : `g1-monde generer` (fichiers identiques octet pour octet), `g1-monde simuler --sans-fenetre` (prête en 3 s), `g1-guide navigation --simu` (Nav2 actif en 8 s), `g1-atelier`, puis `POST /api/guide/aller b204` : arrivé en 55 s à 0,07 m. Boîte en (12 ; 13), puis `POST /api/guide/aller accueil` : `en_route → bloque → detour → arrive` en 156 s, à 0,05 m.
- **Recette** : `tests_e2e/tout.sh` complet : **10 / 10** (critère 4 en 64 s, 5 en 187 s, 6 : 20 / 20 trajets avec 5 piétons en 18 min, 7 : recouvrement de 98,7 %, 8 : MoteurUnitree jusqu'à b204). Journaux : `journaux/e2e_2026-10-25_16h31/`.
- **Reste** : le guide accepte `/guide/aller` avant que Nav2 soit actif et répond `echec` (l'interface grise « Y aller », mais pas `g1-guide aller`) ; zones lentes non branchées (masque `_lent`, phase 3) ; piétons sans collision physique ; licence des paquets (TODO) ; toutes les suppositions « à vérifier sur le robot » (slam_operate, MID-360, `/unitree/slam_relocation/odom`, réglages réels) ; vérifications à la main de l'interface sur tablette ; mode avec fenêtre de Gazebo jamais essayé.

## Intégrateur (vague 2, contrats du scan intégré), 25/10/2026

- **Contrats figés** : section 9 du plan (déroulé, session de scan, `reconnaissance.yaml`, catégories et règles, `g1-scan`, interface de `reconnaitre`, API du serveur, lieu de référence et évaluation, fiches des quatre agents, critères 11 à 15). Renvois ajoutés en 4.1 (`scans/<session>/`), 4.3 (`g1-scan`) et 4.4 (`/api/scan/debut` et `/fin` remplacées).
- **Code partagé livré** :
  - `atelier/lieu/scans.py`, exporté par `atelier.lieu` : créer, lire, écrire et lister les sessions (écriture atomique, verrou `fcntl` entre processus), processus vivant ou session interrompue, `etat_scan` (la sortie de `g1-scan etat --json` et de `GET /api/scan/etat`), progression des étapes ; lire, écrire et valider `reconnaissance.yaml` ; `monde_depuis_reconnaissance`, `ecrire_monde_scan`, `changer_a_garder`, `carte_sans_elements_retires` ; `reconnaissance_depuis_monde` et `passages_du_monde` (la vérité terrain d'un monde dessiné, au format de la reconnaissance).
  - Schémas `session_scan.schema.json` et `reconnaissance.schema.json`. Ce sont deux nouveaux types de fichiers pour le validateur maison, avec leurs règles (étape et état, heures, passages de 0,7 à 1,6 m entre murs alignés, ids, emprise). Les dates, ids de session et sujets ont des messages lisibles.
  - Géométrie des passages dans `geometrie.py` : `murs_alignes` (5°, 0,10 m), `trou_entre`, `est_passage`.
  - Champs facultatifs du monde : `categorie`, `source` et `confiance` pour un objet ; `source` et `confiance` pour un mur. Ils sont portés par les dataclasses, avec `Objet.categorie_effective` et `Objet.sur_la_carte`. `atelier.monde.carte` et `verifier_lieu` ignorent les personnes.
  - `atelier/tests/outils_scan.py` : `creer_session_exemple(copie, etat)` crée une session complète et conforme (en_cours, traitement, termine ou echec) en 0,1 s, sans ROS. Elle permet aux agents Interface et Testeur de commencer sans attendre `g1-scan`.
- **Décisions** :
  - `session.json` est en JSON, et seul `atelier.lieu` l'écrit.
  - Un processus est identifié par son pid et son instant de démarrage dans `/proc` (un pid repris n'est pas pris pour le bon). Une session active, sans processus connu et muette depuis 30 s, est interrompue.
  - Un objet reconnu garde sa forme mesurée (boîte ou cylindre, jamais `modele`) ; sa catégorie porte le sens.
  - Un passage décoché est bouché par un mur de même id, sans fusionner les deux murs.
  - Une personne gardée devient un cylindre de catégorie `personne` : elle est dans le monde Gazebo, jamais sur la carte.
  - La carte reste celle du scan : à l'adoption, seuls les objets décochés et les personnes en sont effacés.
  - Le serveur lit les sessions par `atelier.lieu`, sans sous-processus à chaque seconde, et lance `g1-scan` pour démarrer, arrêter et adopter.
  - La répétition passe par un relais `/points` → `/unitree/slam_mapping/*` de l'Orchestrateur : `g1_sim` ne change pas.
  - L'exploration fait le tour du graphe des itinéraires, puis termine le scan d'elle-même.
  - Le quatrième agent est le Testeur (évaluation et critères 11 à 15).
- **Écarts à la demande** : `source` et `confiance` sont aussi permis sur les murs (le monde tiré du scan en a besoin), pas seulement sur les objets. Le lieu demo reçoit une table, une chaise et une **personne debout** plutôt qu'un poteau : deux poteaux y étaient déjà visibles, et il manquait une personne immobile pour la catégorie `personne`.
- **Lieu demo** (référence de l'évaluation) :
  - `table_est` et `chaise_est` au bout est du couloir sud, `personne_b204` dans b204 (vue par le passage, loin de l'accueil pour ne pas gêner le test des points du LiDAR de `g1_sim`) ;
  - catégorie écrite sur les 12 objets ;
  - `g1-monde generer` relancé : 484 pixels de la carte changent, tous au bout est du couloir sud, et la personne n'y est pas ; `g1-lieu valider` : aucune erreur.
  - Tests mis à jour : nombre d'objets (9 → 12) dans `test_lieu_fichiers`, `test_serveur_api` et `test_monde_commande` ; message des champs permis d'une boîte dans `test_lieu_validation`.
- **Correction** : `test_scan_slam.py::test_commande_sans_faux_service` échouait au hasard. Son domaine (200 + pid % 30) pouvait tomber sur celui du faux service du même processus (150 + pid % 80) : ce soir, les deux valaient 210. Il prend maintenant un autre domaine dans ce cas.
- **.gitignore** : `lieux/*/scans/*/enregistrement/` et `lieux/*/scans/*/.session.lock`.
- **Tests** (domaine 50, partition `scan_50`) :
  - nouveaux : `atelier/tests/test_contrats_scan.py` (60 tests : schémas draft-07, exemples du contrat, refus du schéma et des règles, accord avec jsonschema sur 600 variantes, champs facultatifs du monde, catégories, lieu de référence, règle des passages) et `test_lieu_scans.py` (37 tests : cycle d'une session, verrou entre 4 processus, processus mort ou pid repris, `etat_scan`, reconnaissance, monde tiré du scan, passage bouché, personne hors carte, `changer_a_garder`, sessions d'exemple) ;
  - `atelier/tests` : 505 réussis en 2 min 21 ; `ws/src/g1_sim/test` (avec Gazebo, sur une copie du nouveau demo) : 26 réussis ; `ws/src/g1_nav/test` : 90 réussis, 4 sautés ;
  - `tests_e2e/tout.sh 4 5 7`, à cause des objets ajoutés au demo : **3 / 3**. Critère 4 en 62 s ; critère 5 en 186 s (`bloque → detour → arrive`) ; critère 7 : recouvrement de 98,9 %. Journaux : `journaux/e2e_2026-10-25_18h22/`. Les critères 1 à 3, 6 et 8 à 10 n'ont pas été relancés.
- **Reste et risques** :
  - les objectifs de l'évaluation (9.8) n'ont encore été mesurés sur aucun scan : à confirmer avec le premier scan simulé, et à ajuster si une catégorie est hors de portée du LiDAR (rayon le plus bas à −7° : une table n'est touchée qu'au-delà de 4 m, un banc au-delà de 6,5 m) ;
  - `CAPTEUR_DEFAUT` de `carte3d` vaut encore 1,2 m (le robot proxy est à 1,245 m) : c'est à l'Orchestrateur, et `/tf_static` enregistré suffit ;
  - `copier_lieu` copie aussi `scans/`, enregistrements compris : si l'on scanne `lieux/demo` depuis l'interface, les tests qui copient le demo ralentiront (prévoir une option dans `copier_lieu` si besoin) ;
  - le README sera mis à jour à l'assemblage de la vague 2, quand `g1-scan` existera.

## Interface (vague 2, onglet Scan), 25/10/2026

- **Livré** :
  - `atelier/serveur/routes/scan.py` : toutes les routes de la section 9.7 ;
  - la route `POST /api/simulation/teleop` dans `routes/simulation.py` ;
  - l'onglet Scan : `web/js/ecrans/scan.js`, plus deux modules nouveaux, `web/js/teleop.js` (flèches) et `web/js/nuage3d.js` (nuage 3D de l'aperçu) ;
  - `web/css/scan.css`, relié par `index.html` ; l'onglet Scan demande maintenant un lieu (`app.js`) ;
  - `web/LISEZMOI.md` à jour.
- **Écran** :
  - choix du mode : Simulation, ou Robot (consignes du câble Ethernet, de `source ~/robot-g1/setup/robot.sh` et de la télécommande en marchant derrière le robot) ; case « Répétition sans robot » ; case « Exploration automatique » quand le robot est simulé ;
  - gros bouton « Scan ». En mode robot sans répétition, une confirmation rappelle le câble ;
  - en direct :
    - chronomètre, points et distance ;
    - `apercu.png` toutes les 2 s, l'inconnu rendu transparent, au-dessus du monde dessiné quand le robot est simulé ;
    - trajectoire et robot, et nuage 3D tiré d'`apercu.json` ;
    - six flèches à l'écran et au clavier (↑ ↓, ← →, Q et D pour le pas de côté) ;
    - gros bouton « Fin » ;
  - barre de progression, avec l'étape en cours et le message de la session ;
  - résultat :
    - carte de la session (Leaflet), avec les murs, les passages et les objets dessinés par-dessus, une couleur par catégorie et une légende ;
    - liste par catégorie : case « garder », confiance, badge « douteux » sous 50 %, « jamais sur la carte » pour une personne ; un clic sur un nom le montre sur le plan et en 3D ;
    - vue 3D du monde du scan ;
    - « Utiliser cette carte pour l'étage » (adopter sans monde), « Ouvrir dans l'éditeur du monde » (adopter avec monde, puis onglet Monde), « Nouveau scan » ;
  - écrans d'échec et de scan interrompu (« Terminer ce scan ») ; tableau des scans précédents, avec « Voir ».
- **Ajouts au contrat 9.7** :
  - `GET /api/scan/sessions/{s}/rapport` (rapport.json) ;
  - `sortie` (texte de g1-scan) dans les réponses de `demarrer` et `arreter` ;
  - `interrompue` pour chaque session de `GET /api/scan/sessions` ;
  - `session`, `etage`, `avertissements` et `rapport` (`valider_lieu`) dans la réponse d'`adopter` ;
  - `avertissement` dans la réponse de `teleop` quand personne n'écoute `/cmd_vel` ;
  - variable `ATELIER_INTERFACE_ROBOT` (eno2 par défaut) ;
  - rôle `scan` dans les processus du serveur (`/ws/etat`, « Ce qui tourne »).
- **Décisions** :
  - **Refus avant de lancer g1-scan**, pour des messages clairs :
    - 400 : mode inconnu, répétition en simu, exploration avec le vrai robot ;
    - 409 : simulation de l'Atelier sur un autre lieu ou étage ; scan déjà actif ; pas de `.sdf` avec le robot simulé ; exploration sans couloir sur l'étage ;
    - mode robot sans câble : 409 « Robot non détecté : branchez le câble… ». Le serveur lit seulement `/sys/class/net/<interface>/carrier` : rien n'est envoyé sur eno2 ;
    - 503 sans g1-scan ;
    - 502 si g1-scan échoue : la dernière ligne de sa sortie va dans `detail`, et la sortie entière dans `sortie`.
  - **Sortie de g1-scan** : elle passe par un fichier temporaire, pas par un tuyau, car le processus détaché de la session pourrait garder le tuyau ouvert. L'id de la session est lu sur la ligne `session: <id>`.
  - **Arrêt avec le serveur** : un scan démarré par le serveur est rangé parmi ses processus (`SuiviScan`). Si l'enregistrement tourne encore quand le serveur s'arrête, le serveur lance `g1-scan arreter`. Le traitement qui suit finit seul. Un scan lancé en ligne de commande n'est pas touché.
  - **Téléopération** :
    - le publieur `/cmd_vel` vit sur le nœud du pont ROS 2 : pas de second participant DDS ;
    - homme mort : un fil publie une vitesse nulle 0,5 s après la dernière consigne non nulle ;
    - consignes ramenées à 0,5 / 0,25 / 0,8 ; l'interface envoie 0,4 / 0,2 / 0,6, toutes les 0,2 s, puis {0, 0, 0} ;
    - permise si la simulation de l'Atelier tourne, ou si un lieu suivi par le serveur (dernier scan démarré, ou lieu affiché dans l'onglet Scan) a un scan simu ou en répétition qui enregistre. Une réponse positive est gardée 1 s ;
    - 409 avec le vrai robot.
  - **Anciennes routes retirées** (`/api/scan/debut`, `/fin`, `/faux-service/arreter`), comme le dit le contrat 9.7.
- **À faire par l'intégrateur** (fichiers hors de mon périmètre) :
  - supprimer les trois tests de l'ancienne API dans `test_serveur_api.py` (`test_scan_avec_faux_service`, `test_scan_vrai_robot_sans_faux_service`, `test_scan_erreurs`) ;
  - dans `test_serveur_navigateur.py`, remplacer l'étape « Scan : le faux service est coché » par l'ouverture de l'onglet (`.ecran-scan .scan-mode` au nombre de 2), en gardant `assert "g1-guide stop" in faux_bin.appels()` ;
  - tant que ce n'est pas fait, ces 4 tests échouent, et donc le critère 9 aussi. Les deux fichiers corrigés passent : 28 tests ;
  - `vue3d.js` (onglet Simulation) dessine encore le robot en 0,45 × 0,30 × 1,30 m ; `nuage3d.js` utilise déjà 0,208 × 0,477 × 1,315 m.
- **Tests** (domaine 53, partition `scan_53`, 29 tests en 45 s) :
  - `test_serveur_scan.py` (18 tests), avec un faux g1-scan qui suit le contrat 9.5 (`test_serveur_scan_communs.py` : vraies sessions par `atelier.lieu`, processus de session détaché, aperçu, traitement, adoption) et les sessions d'exemple ;
  - `test_serveur_scan_teleop.py` : vrai pont ROS 2 et faux robot sur `/cmd_vel`. On vérifie les limites, l'arrêt de l'homme mort entre 0,45 et 1,2 s (une seule fois), la consigne répétée sans arrêt pendant 2 s, et le publieur unique « atelier_pont » ;
  - `test_serveur_scan_web.py` : syntaxe (esprima), routes appelées, liens, réglages de la téléopération, pas de donnée en HTML ;
  - `test_serveur_scan_navigateur.py` (Firefox sans fenêtre) : le parcours complet de l'onglet, et `teleop.js` avec un faux `fetch` (consigne toutes les 0,2 s, touches combinées, arrêt au relâché).
  - Suite complète `atelier/tests` : 557 réussis, 9 échecs. 4 viennent des anciens tests ci-dessus. 5 sont dans `test_scan_session.py` (agent Orchestrateur, travail en cours).
- **Essais réels**, sur une copie du demo, avec le vrai g1-scan de l'Orchestrateur et le vrai g1-atelier, Gazebo sans fenêtre :
  - simu : `demarrer` répond en 1 s ; enregistrement à +14 s ; flèches (`ecoute: 1`) : 2,3 m parcourus ; aperçu (9 384 points) ; « Fin » : réponse en 2 s, puis `termine` 5 s après ; reconnaissance (6 murs, 3 objets dont une personne décochée) ; `adopter` avec le monde : `g1-lieu valider` sans erreur ;
  - robot en répétition : même parcours, 1801 au faux service ; à l'adoption, le rapport signale les nœuds hors de la nouvelle carte (scan partiel, repère du nuage) ;
  - après Ctrl+C sur le serveur, aucun processus ne reste.
- **Vérifications à faire à la main** (elles remplacent le point 9 de la liste de la phase 1) :
  1. Scan, mode Simulation, sans exploration : « Scan ». La vue de dessus se remplit en bleu foncé, et le nuage 3D aussi. Flèches du clavier : le robot avance, puis s'arrête quand on lâche.
  2. « Fin » : la barre avance (Carte 3D, Carte 2D, Reconnaissance, Monde), puis la revue s'affiche. La personne est décochée. Décocher une table : elle s'estompe sur le plan et disparaît de la 3D.
  3. « Ouvrir dans l'éditeur du monde » : l'onglet Monde montre le monde du scan, et l'onglet Carte montre la carte du scan.
  4. Mode Robot sans câble : « Robot non détecté : branchez le câble… ». Cocher « Répétition sans robot » : le scan démarre sans câble.
  5. Tablette : les six flèches répondent au doigt, et un appui long n'ouvre pas de menu.
- **Reste** :
  - le vrai mode robot n'a été essayé qu'en répétition (pas de robot) ;
  - l'exploration automatique jusqu'au bout avec le vrai g1-scan n'est pas essayée ici : c'est le critère 11 du Testeur ;
  - pas de pagination de l'historique ;
  - « Ouvrir dans l'éditeur du monde » adopte tout de suite (la revue se fait avant, dans l'onglet Scan).

## Orchestrateur du scan (vague 2, g1-scan), 25/10/2026

- **Livré** : `bin/g1-scan` (alias `gl-scan`) et `atelier/scan/session.py` : `demarrer`, `arreter`, `traiter`, `etat`, `adopter` (section 9.5), le processus de la session, le traitement et l'adoption. Aussi `atelier/scan/apercu.py` (nœud d'aperçu en direct), `exploration.py` (tour automatique des couloirs) et `repetition.py` (relais `/points` → `/unitree/slam_mapping/*`, attente de sujets). Tests : `atelier/tests/test_scan_session.py` et `test_scan_session_simulation.py`.
- **Processus de la session** : `demarrer` vérifie tout avant de créer la session, puis lance `python -m atelier.scan.session session` détaché (son propre groupe), note `processus` et `journal`, et rend la main en 0,4 s. Chaque programme lancé (simulation, faux service, relais, `ros2 bag record`, aperçu, exploration) a :
  - son groupe de processus et son journal `journaux/scan_<lieu>_<session>.<nom>.log` ;
  - `PR_SET_PDEATHSIG` : il reçoit SIGTERM si le processus de la session meurt ;
  - une ligne dans `scans/<session>/.processus.json`, dont `arreter` se sert pour nettoyer une session interrompue.
- **Ordre d'arrêt** : exploration, 1802 (mode robot), bag (SIGINT, `metadata.yaml`), aperçu (vitesse nulle sur `/cmd_vel` avec le robot simulé), `fin` notée, puis relais, simulation (seulement si la session l'a lancée), faux service. Le traitement suit dans le même processus. Un bag sans `metadata.yaml` est réparé par `ros2 bag reindex`.
- **Mode robot (vrai G1)** :
  - `demarrer` vérifie le câble sans rien envoyer : lecture de `/sys/class/net/eno2/carrier` et de `ip addr` ;
  - il refuse toujours avec `G1_SLAM_FAUX=1` (essais) ;
  - les programmes reçoivent le réseau de `setup/robot.sh` (domaine 0, CycloneDDS sur eno2) ;
  - en plus des sujets du contrat, il enregistre `/state_estimator/odom_pelvis` et `/slam_info` (notés dans `sujets.autres`) ;
  - **jamais essayé avec le robot** : seulement en répétition.
- **Repère des points d'Unitree** : `rapport.json` a un champ `repere` `{nuage, odom, robot, deja_dans_le_monde, capteur, premiere_pose}`, lu dans le premier message de chaque sujet du bag.
  - Si le `frame_id` du nuage est celui de l'odométrie, ou `odom`, `map`, `world` ou `camera_init`, les points sont déjà dans le monde : carte3d les prend tels quels.
  - Sinon, ils sont placés par l'odométrie et `/tf_static`. En simu et en répétition, la position de secours du LiDAR est lue dans le `model.sdf` de g1_proxy (−0,004 ; 0 ; 1,245).
  - En mode robot, un avertissement du rapport dit ce qui a été fait, à vérifier sur la carte du premier vrai scan.
  - Testé avec un faux bag dont le nuage est en `map` : `deja_dans_le_monde: true`, emprise du nuage.
- **Aperçu** : grille de 5 cm où chaque case 3D compte les nuages qui l'ont touchée. Une colonne est un obstacle si elle a au moins 2 cases dans la tranche, au moins 3 nuages et une tache d'au moins 4 pixels.
  - Ce filtre est nécessaire : le gpu_lidar de Gazebo produit des points fantômes le long des rayons, au bord des murs, qui traversaient l'aperçu (vérifié en rejouant le bag : ce n'est pas un défaut de recalage).
  - Les piétons laissent une traînée dans l'aperçu ; la carte finale les retire.
  - Le PNG est réécrit en 0,1 s environ sur le demo.
- **numpy à un seul fil** (`OPENBLAS_NUM_THREADS=1` pour tous les programmes de la session, plus de produits matriciels dans les boucles) : sans cela, le produit `points @ u` de l'exploration occupait **10 cœurs** en attente active, à 20 Hz.
- **Exploration** : un circuit qui emprunte chaque couloir au moins une fois (problème du postier chinois : appariement exact des nœuds impairs, puis circuit eulérien), depuis le nœud le plus proche, avec retour au départ. Un couloir bloqué 30 s est abandonné : le robot revient au nœud précédent, et la suite du tour est choisie au plus court (`Tournee`). Deux pilotes :
  - `direct` (défaut, contrat 9.5) : ligne droite par `/cmd_vel` à 0,4 m/s, arrêt devant un obstacle de `/points` à moins de 0,6 m ;
  - `guide` (`g1-scan demarrer --pilote guide`, comme le demandait ma fiche) : `/guide/aller` nœud après nœud, attente de `arrive` sur `/guide/etat`, lance `g1-guide navigation --simu` si le guide ne tourne pas.
- **Résultats** (sur des copies de lieux/demo, domaine 51, partition `scan_51`, sans fenêtre) :
  - scan simu avec `--explorer` : `demarrer` en 0,44 s, tour de 13 couloirs (62 m) en 3 min 10, traitement en 15 à 20 s, session `termine` seule en 207 s. Recouvrement de **99,1 %** avec la carte du monde (couverture 65 %). La reconnaissance de l'agent B a été appelée : 25 murs, 5 passages, 13 objets, la personne décochée. Puis `adopter --monde` : `valider_lieu` sans erreur ;
  - pilote `guide` (Nav2) : tour en 191 s, recouvrement de 95,9 % ;
  - répétition du mode robot : le faux service reçoit 1801 puis 1802 avec `rdc_<session>.pcd`, le bag contient `/unitree/slam_mapping/points` et `/unitree/slam_mapping/odom` (pas `/points`), et la session finit `termine` ;
  - après chaque essai, `ps` ne montre aucun programme restant (ni Gazebo de `scan_51`, ni Nav2 du domaine 51).
- **Tests** :
  - `test_scan_session.py` : 30 tests en 36 s, sans Gazebo (faux bags écrits avec rosbag2_py, sautés sans ROS 2). Ils couvrent les refus de `demarrer`, le double démarrage, `arreter` sans scan, sur une session finie ou interrompue (avec et sans enregistrement), les refus de `traiter`, le traitement simu et robot, une reconnaissance absente ou ratée, l'échec de `carte_3d`, `etat --json`, `adopter` avec et sans `--monde` (masque, personne effacée), le refus de 1801 par un faux g1-slam, le tour, l'aperçu et le placement des nuages ;
  - `test_scan_session_simulation.py` : 3 scans réels dans Gazebo en 4 min 30, avec `G1_SCAN_SIMULATION=1` (sautés sinon) : simu avec exploration puis adoption, répétition avec téléopération, puis `arreter --sans-traitement` suivi de `traiter`.
- **Écarts au contrat** :
  - `arreter --sans-traitement` envoie SIGUSR1 (au lieu de SIGINT) : la session reste en `arret_en_cours` avec sa `fin`, son processus se termine, puis `traiter` ou `arreter` la finit ;
  - `arreter` sans aucune session : code 0, « rien à arrêter » ;
  - en plus du contrat : `.processus.json` dans la session, des journaux par programme, le champ `repere` de `rapport.json`, l'option `--pilote` de `demarrer` ;
  - variables : `G1_SCAN_BIN` (fausses commandes des tests), `ATELIER_RECONNAISSANCE=module:fonction` (fausse reconnaissance des tests), `G1_INTERFACE` (port du robot).
- **Pour l'intégrateur** :
  - ajouter `lieux/*/scans/*/.processus.json` au `.gitignore` ;
  - `CAPTEUR_DEFAUT` de carte3d vaut toujours 1,2 m : ce fichier n'était pas dans mon périmètre cette fois, et g1-scan passe la position lue dans model.sdf ;
  - le README peut citer `g1-scan` ;
  - un bag de simulation pèse environ 100 Mo par minute de scan (328 Mo pour le tour du demo, `/points` à 10 Hz) : ces fichiers restent dans `scans/<session>/enregistrement/` (ignoré par Git) ; prévoir de les effacer après adoption.
- **Reste** :
  - le vrai mode robot (1801/1802 sur eno2, repère réel de `/unitree/slam_mapping/points`, `/slam_info` enregistré) ;
  - l'aperçu ne retire pas les piétons ;
  - l'exploration directe ne contourne pas un obstacle bas posé sur un couloir : le LiDAR, à −7°, ne le voit qu'au-delà de 1 à 10 m selon sa hauteur, puis plus du tout de près. Le couloir est alors abandonné après 30 s, ou il faut utiliser `--pilote guide`.

## Reconnaissance (vague 2, murs, passages et objets du scan), 25/10/2026

- **Livré** : `atelier/scan/reconnaissance.py` (`reconnaitre`, contrat 9.6 ; `PARAMETRES`, 71 réglages commentés ; `ErreurReconnaissance` ; `python -m atelier.scan.reconnaissance NUAGE.pcd CARTE.yaml DOSSIER [--parametre cle=valeur]`) et `atelier/scan/evaluation.py` (`evaluer` et `texte_bilan`, mesures de 9.8 ; `python -m atelier.scan.evaluation --session D --reference LIEU [--json] [--exiger]` ; nuages synthétiques par lancer de rayons Open3D : `nuage_synthetique`, `points_de_vue_du_lieu`, `essayer_sur_monde`). Le traitement de `g1-scan` (Orchestrateur) et le critère 12 (Testeur) les appellent déjà.
- **Méthode** :
  - sol : RANSAC d'un plan presque horizontal, puis moindres carrés ; plafond retiré s'il couvre 4 m² d'un seul tenant ;
  - murs : points de la tranche 1,3–1,9 m (au-dessus des meubles bas, sous les linteaux), `cv2.HoughLinesP`, réajustement, fusion des morceaux alignés (5°, 0,10 m) et des deux faces d'un même mur. Un trou de moins de 0,7 m est bouché ; un mur court de moins de 1,8 m de haut est rendu aux objets ;
  - passages : trous de 0,7 à 1,6 m entre murs voisins d'un alignement, sauf si un autre mur touche le trou (coin de pièce mal vu à travers une porte) ;
  - objets : DBSCAN vu de dessus. Seuls les points à plus de 0,35 m, qui ont au moins 2 voisins à 10 cm, relient deux objets ; les petits morceaux sont rattachés au voisin. Les traces (densité < 0,2, colonnes sans volume, groupes qui flottent) et les tranches de murs sont écartées ;
  - catégories : scores par règles (hauteur, emprise, plateau, remplissage sous le plateau, rondeur, profondeur, finesse). Personne : 1,5–1,95 m, emprise 0,25–0,75 m, `a_garder: false`. Confiance : score × marge sur la 2e catégorie × nombre de points ; « inconnu » toujours sous 0,5.
- **Résultats**, objectifs de 9.8 (murs rappel / précision ; passages trouvés / reconnus justes ; objets détectés, bonne catégorie ; faux objets ; personne) :

  | Nuage | Murs | Passages | Objets | Faux | Personne |
  |---|---|---|---|---|---|
  | scan simulé du critère 7 (`/points` `/odom`, `g1-carte-3d`, 194 225 points) | 99,4 % / 97,2 % | 5/5, 5/5 | 11/11, 11/11 | 0 | oui |
  | scan intégré du critère 11 (`g1-scan --mode simu --explorer`, domaine 52, sol de `carte2d` comme dans le traitement) | 99,5 % / 95,7 % | 5/5, 5/5 | 11/11, 11/11 | 1 | oui |
  | synthétique dense, bruit 1,5 cm, 40 trous, personne ajoutée dans le couloir sud | 99,4 % / 100 % | 5/5, 5/5 | 13/13, 13/13 | 1 | oui (2/2) |
  | synthétique clairsemé comme le LiDAR du robot proxy (16 lignes, −7° à +52°) | 99,6 % / 100 % | 5/5, 5/5 | 11/11, 10/11 | 0 | oui |
  | synthétique, bruit 2 cm et 100 trous | 99,4 % / 100 % | 5/5, 5/5 | 13/13, 13/13 | 1 | oui |
  | nuage fabriqué du critère 12 (Testeur) | 99,6 % / 100 % | 100 %, 100 % | 100 %, 100 % | 1 | oui |

  Mesures plus strictes demandées pour la mission : murs retrouvés à 0,2 m et 5°, 18/18 partout ; objets retrouvés à 0,3 m avec la bonne catégorie, 10/11 (critère 7) et 9/11 (critère 11). La reconnaissance prend 1 à 2 s sur le demo (contrat : moins de 60 s), avec le même résultat à chaque appel (vérifié octet pour octet). `table_cdi` n'est pas « vue » au sens de 9.8 (moins de 3 pixels occupés) dans les scans simulés.
- **Bout à bout** (copie du demo dans mon dossier de travail) : `g1-scan demarrer --mode simu --explorer` a fini seul, `termine` (3 min 21 s d'enregistrement, traitement 11 s avec cette version). Ensuite `g1-scan adopter --monde`, puis `g1-lieu valider` sans erreur. Enfin `g1-monde simuler --sans-fenetre` démarre sur le monde adopté (25 murs, 13 objets) et `/points` est publié. Tous les processus sont arrêtés ensuite (vérifié avec `ps`).
- **Écarts** :
  - RANSAC du sol écrit avec numpy, à graine fixe : celui d'Open3D (`segment_plane`) est parallèle et rendait deux plans différents d'un appel à l'autre, ce que le contrat (« même résultat ») interdit. Open3D sert au DBSCAN, aux voisinages et aux fichiers.
  - Ma mission me confiait aussi `evaluation.py` (agent Testeur en 9.9), et nommait mes tests `test_reconnaissance*.py` au lieu de `test_scan_reconnaissance*.py`.
  - Les mesures sont celles de 9.8. Ajouts : la mesure stricte demandée dans la mission (0,2 m et 5° ; 0,3 m), un objet vu à 0,10 m de sa surface (demi-épaisseur comprise pour un mur), et une personne qui n'a pas été vue compte comme un échec.
  - `reconnaitre` accepte en plus `progression=` (fonction appelée avec la fraction et l'étape) et `depart_robot` en dict.
- **Limites** :
  - un mur vu d'un seul côté a son axe sur la face vue (5 à 10 cm de l'axe vrai) et 0,15 m d'épaisseur ;
  - un meuble de plus de 1,8 m et long (armoire) devient un mur ;
  - la catégorie d'un objet vu de loin par une porte reste fragile (chaise du CDI vue par son seul dossier, bureau de l'amphi vu de face). Les chaises rangées contre une table peuvent être fusionnées avec elle ;
  - les nuages de la simulation ont des traînées de recalage pendant les rotations du robot proxy : environ 7 m de murs fantômes en diagonale dans le bloc fermé, d'où 96–97 % de précision des murs. `carte3d` pourrait ignorer les nuages pris pendant une rotation rapide (à proposer à l'Orchestrateur) ;
  - rien n'a été essayé sur un vrai scan du G1 (plafond, nuage de la SLAM d'Unitree).
- **Tests** : `atelier/tests/test_reconnaissance.py` (pièce de 8 × 6 m avec une porte de 0,9 m, un trou de 0,5 m bouché, une table, une chaise, un poteau et une personne ; sol, plafond, erreurs sans fichier à moitié écrit, reproductibilité, ligne de commande, règles), `test_reconnaissance_evaluation.py` (reconnaissance parfaite du demo = 1 partout ; chaque défaut fait baisser la bonne mesure ; ligne de commande) et `test_reconnaissance_demo.py` (demo synthétique dense et clairsemé). Résultat : 46 réussis et 1 sauté en 23 s. Le test sauté demande `G1_SCAN_DEMO=DOSSIER` ; lancé à part sur les deux scans simulés, il réussit. Suite complète `atelier/tests` : 608 réussis et 4 échecs hors de mon périmètre (`test_serveur_api.py::test_scan_*` et le parcours navigateur appellent `/api/scan/debut`, retirée en vague 2 ; réponse 405). Critère 12 (`tests_e2e/critere_12_reconnaissance.sh`, domaine 52) : RÉUSSI.

## Testeur du scan (vague 2, critères 11 à 15), 25/10/2026

- **Livré** : `tests_e2e/critere_11_scan_simu_api.sh` à `critere_15_robustesse.sh`, leur outil `tests_e2e/outils_scan_e2e.py` (appels à l'API, suivi d'une session comme l'interface, vérification d'une session finie, évaluation, nuage fabriqué, ménage des processus), `tout.sh` (« N / 15 », délais des nouveaux critères) et `LISEZMOI.md`. `commun.sh` n'a pas changé.
- **Les critères** (numérotation de la demande, différente de 9.10 : voir les écarts) :
  - 11, scan simulé par l'API : `POST /api/scan/demarrer` (simu, exploration), puis le suivi de l'interface (état chaque seconde, `apercu.json` et `.png` toutes les 2 s). « Fin » (`POST /api/scan/arreter`) part après 30 s au moins et 80 % de la longueur des couloirs, pour que la session couvre presque tout l'étage. Ensuite : `termine`, recouvrement d'au moins 90 %, reconnaissance et monde valides, aucun processus restant. La session finie est gardée (sans le bag) dans `journaux/e2e_scan/domaine_<N>/` pour les critères 12 et 13. Avec `E2E_FIN_AUTO=1`, pas de « Fin » : l'exploration doit terminer le scan d'elle-même (9.10).
  - 12, reconnaissance : `atelier.scan.evaluation.evaluer` et le bilan de `python -m atelier.scan.evaluation`, sur la session du 11 ; sans elle, sur un nuage fabriqué. Bloquants : murs ≥ 0,90, passages ≥ 0,80, objets de la bonne catégorie ≥ 0,70, aucune personne gardée. Les autres objectifs de 9.8 sont affichés, et bloquants avec `E2E_STRICT=1`.
  - 13, monde issu du scan : « Adopter la carte et le monde » par l'API. Vérifié ensuite : carte de l'étage = carte de la session sans les éléments retirés, masque à sa taille, `source_carte: scan`, nuage copié, `adoption` notée, ancien monde gardé. Puis `g1-lieu valider`, et `g1-monde generer`, qui ne doit pas toucher la carte du scan et dont le SDF ne doit plus contenir les murs dessinés. Enfin le parcours du critère 4 sur le monde du scan. Sans session gardée, il lance d'abord le 11.
  - 14, répétition, par `g1-scan` et non par l'API : `demarrer --mode robot --repetition --explorer` (moins de 3 s), enregistrement, puis `arreter --attendre`. Ensuite : 1801 puis 1802 (avec `carte_unitree`) lus dans le journal du faux service, sujets `/unitree/slam_mapping/*` dans le bag, `etat --json` à `termine`, aucun processus restant.
  - 15, robustesse : « Fin » sans scan, « Scan » deux fois, mode robot sans robot (« Robot non détecté »), demandes absurdes (mode, répétition en simu, étage inconnu, id de session qui sort de `scans/`, aperçu d'une session inconnue). Jamais d'erreur 500 ni de trace Python ; un message en français.
- **Décisions** :
  - Les sessions tournent détachées, dans leur propre groupe. Chaque script les arrête donc lui-même à la sortie (SIGINT au groupe, comme « Fin »). Il arrête ensuite tout processus dont l'environnement porte son `ATELIER_LIEUX`, un dossier temporaire propre au test, avant le ménage de `commun.sh`. Les autres agents ne sont jamais touchés (essayé avec deux processus témoins).
  - Chaque critère a son propre id de lieu (`scan_e2e`, `repetition_e2e`, `robustesse_e2e`). En effet, les journaux de session (`journaux/scan_<lieu>_<session>.*.log`) ne portent que le lieu et la minute, et deux tests sur « essai » à la même minute écriraient dans le même fichier.
  - Le nuage fabriqué est un lancer de rayons numpy sur les formes exactes du SDF (`atelier.monde.sdf`, meubles compris). Il reproduit le LiDAR du robot proxy (360 × 16 rayons, de −7° à +52°, à 1,245 m), placé tous les 0,25 m le long des couloirs, avec un bruit de 5 mm, puis réduit à 5 cm. Il est prêt en 2 s, sans ROS. Il diffère de `evaluation.nuage_synthetique` (champ de −30° à +52°).
  - Critère 15 : `G1_INTERFACE` pointe vers une interface qui n'existe pas, et l'étape 3 est sautée si un câble est branché sur eno2. Rien n'est jamais envoyé au robot : le serveur ne lit que `/sys/class/net/eno2/carrier`.
- **Résultats** (domaine 54, partition `scan_54`) :
  - `tests_e2e/tout.sh` complet, de 19 h 12 à 19 h 47 : **13 / 15**.
    - Critères 1 à 8 et 11 à 15 réussis.
    - Le 9 échoue : le parcours navigateur de l'agent Interface (`atelier/tests/test_serveur_navigateur.py`) coche une case qui n'existe plus dans le nouvel onglet Scan (`querySelector(...) is null`). Plus tôt, il appelait encore `/api/scan/debut`.
    - Le 10 n'est donc pas compté. Journaux : `journaux/e2e_2026-10-25_19h12/`.
  - Critère 11 : 169 s. Recouvrement de 99,1 %, couverture de 65 % ; « Fin » à 50 m sur 62 ; traitement en 10 s ; aperçu mis à jour 73 fois.
  - Critère 11 avec `E2E_FIN_AUTO=1` : tour complet de 61,5 m en 183 s, fin d'elle-même, `termine` 12 s plus tard ; recouvrement de 98,8 %.
  - Critère 12 sur la session de 18 h 57 : murs 99,5 %, passages 80 % (4 sur 5), catégorie 81,8 %, détection 91,7 %, 2 faux objets, personne reconnue et décochée.
  - Sur le tour complet de 19 h 09 (`E2E_STRICT=1`) : murs 99,6 %, passages 100 %, catégorie 100 %, détection 100 %, 1 faux objet.
  - Sur le nuage fabriqué : tous les objectifs de 9.8 sont atteints. La catégorie y est à 70 % au premier essai, puis à 90 % avec la reconnaissance suivante.
  - Critère 13 : 88 s, robot arrivé à salle_e2e à 0,07 m dans le monde du scan. Lancé seul, il refait d'abord le 11 : 264 s en tout.
  - Critère 14 : 54 à 62 s, `demarrer` en 0,94 s, bag de 349 nuages et 1745 odométries.
  - Critère 15 : 10 à 12 s.
- **Écarts** :
  - La numérotation de la demande (11 API, 12 reconnaissance, 13 monde, 14 répétition, 15 robustesse) n'est pas celle de 9.10 (11 g1-scan, 12 répétition, 13 reconnaissance, 14 adoption, 15 interface). Le fond de 9.10 est couvert, avec deux exceptions :
    - le parcours Firefox et la téléopération (9.10, n° 15) ne sont pas dans mes critères ; la téléopération n'est essayée que par les tests unitaires de l'agent Interface ;
    - la fin d'elle-même de l'exploration n'est essayée qu'avec `E2E_FIN_AUTO=1`.
  - Le seuil de recouvrement est de 90 % (demande), au lieu de 80 % (plan).
  - `g1-scan demarrer --mode robot` sans robot ne dit pas « Robot non détecté » comme l'interface. Il dit « câble non détecté sur … », ou, avec `G1_SLAM_FAUX=1`, que le vrai robot est interdit. Le critère 15 l'accepte (code 1, message clair), mais le signale.
  - « Fin » pendant la préparation donne `echec` (« rien n'a été enregistré ») et le code 1 : c'est accepté.
- **Reste** :
  - le critère 9, à refaire après la mise à jour du parcours navigateur par l'agent Interface ;
  - harmoniser le message « Robot non détecté » de `g1-scan` (Orchestrateur) ;
  - les passages de la session interrompue à 80 % sont juste à l'objectif (4 sur 5) : à surveiller si la reconnaissance change ;
  - aucun essai sur le vrai robot.

## Intégrateur (assemblage de la vague 2, scan intégré), 25/10/2026

- **Assemblé** : le travail des quatre agents de la vague 2 (Orchestrateur, Reconnaissance, Interface, Testeur), sur les contrats du commit « Scan intégré : contrats ». Dans l'onglet Scan, « Scan » lance la cartographie (robot ou simulation), l'aperçu se construit en direct, « Fin » l'arrête, puis carte 3D, carte 2D, reconnaissance et monde se font seuls ; la revue et l'adoption donnent un monde qui s'ouvre dans l'éditeur et se simule dans Gazebo.
- **Écarts corrigés entre modules** :
  - tests de la vague 1 qui appelaient les routes retirées (`/api/scan/debut`, `/fin`, `/faux-service/arreter`) : correctif de l'agent Interface appliqué (`test_serveur_api.py` : 3 tests supprimés ; `test_serveur_navigateur.py` : l'étape du faux service devient l'ouverture de l'onglet Scan). Le critère 9 repasse ;
  - position du LiDAR par défaut : (−0,004 ; 0 ; 1,245) m, celle du `model.sdf` de `g1_proxy`, dans `carte3d.CAPTEUR_DEFAUT` (et l'aide de `g1-carte-3d`), `faux_slam` (`HAUTEUR_LIDAR`) et `ws/src/g1_sim/test/outils_sim.py` (au lieu de 1,2 m) ;
  - message de `g1-scan demarrer --mode robot` sans câble : il commence maintenant par « Robot non détecté », comme l'interface (test mis à jour) ;
  - `.gitignore` : `lieux/*/scans/*/.processus.json` ;
  - interface : « Scan » nommé dans « Ce qui tourne » (`simulation.js`), robot de la vue 3D de l'onglet Simulation à la taille du G1 (0,208 × 0,477 × 1,315 m, comme `nuage3d.js`), `g1-scan` dans la liste des commandes de `GET /api/etat` ;
  - `atelier/scan/__init__.py` décrit les nouveaux modules ; import inutile retiré de `commande.py`.
- **Critères 11 à 15** : la numérotation des scripts du Testeur est gardée et écrite dans la section 9.10 du plan, avec la correspondance au premier jet. Deux trous de 9.10 sont bouchés :
  - critère 13 : un objet est décoché dans la revue (`PUT …/reconnaissance`, l'objet le plus loin de l'accueil) avant l'adoption, et il ne doit pas être dans le monde adopté ;
  - critère 15 : pendant un scan simulé, les flèches (`POST /api/simulation/teleop`, vx = 0,4 m/s pendant 3 s) doivent faire avancer le robot d'au moins 0,5 m, puis il doit s'arrêter seul quand on lâche (homme mort) ; ensuite « Fin » pendant la préparation (ancien cas), puis le parcours de l'onglet Scan dans Firefox (`test_serveur_scan_navigateur.py`). Nouvel outil : `outils_scan_e2e.py teleop`. Essai : 1,34 m parcourus, puis 0,000 m sans consigne.
- **Contrats tenus à jour** (plan, section 9) : paragraphes « Précisions de l'assemblage » en 9.5 (options `--pilote`, SIGUSR1 de `--sans-traitement`, `.processus.json`, champ `repere`, sujets en plus du mode robot, LiDAR à 1,245 m, variables), 9.6 (RANSAC numpy, `progression=`), 9.7 (route `rapport`, champs ajoutés, rôle « scan », câble, noms des boutons d'adoption), 9.8 (évaluation écrite par l'agent Reconnaissance, mesures plus strictes, objectifs gardés) ; 9.9 avec les fichiers livrés ; 9.10 réécrite ; `.processus.json` dans le tableau de 9.2 ; renvois en 4.4 et dans la fiche Interface.
- **README** : sous-section « Scanner un lieu » (simulation pas à pas ; vrai robot avec le câble, la télécommande et le PC qui suit ; répétition ; ligne de commande `g1-scan`), `g1-scan` dans le tableau des commandes, `scans/` dans les fichiers d'un lieu, durées des tests.
- **Décisions** :
  - les tests Gazebo de l'Orchestrateur (`G1_SCAN_SIMULATION=1 pytest atelier/tests/test_scan_session_simulation.py`) restent facultatifs : les critères 11 et 14 font la même chaîne de bout en bout ;
  - le bouton « Ouvrir dans l'éditeur du monde » garde son nom : il adopte la carte et le monde après une confirmation qui le dit ; le plan l'appelle « Adopter la carte et le monde ».
- **Parcours d'un utilisateur, par l'API et sans fenêtre** (copie du demo, vrai `g1-atelier`, vrai `g1-scan`, Gazebo sans fenêtre, domaine 50) : « Scan » en mode simulation avec exploration (réponse en 0,5 s) ; enregistrement 12 s plus tard ; aperçu réécrit 72 fois ; « Fin » à 50 m (réponse en 2,5 s, bag de 279 Mo) ; traitement en 7,6 s, `termine` ; carte de 602 × 402 pixels, recouvrement de 99,1 % avec la carte du monde ; reconnaissance : 22 murs, 5 passages, 13 objets (3 chaises, 1 table, 1 banc, 2 poubelles, 3 poteaux, 2 meubles, 1 personne décochée) ; évaluation : murs 99 % / 96 %, passages 5 sur 5, objets 11 sur 11 de la bonne catégorie, 1 faux objet, tous les objectifs atteints ; `table_1` décochée, puis adoption avec le monde (rapport sans erreur ; monde de l'étage : 22 murs `source: scan`, 11 objets ; `g1-lieu valider` : « Aucune erreur. ») ; simulation de ce monde par l'API, puis « Y aller » b204 : `attente → en_route → arrive` en 85 s, robot à 0,06 m ; serveur arrêté (code 0), aucun processus restant.
- **Tests** (domaine 50, partition `scan_50`) :
  - `atelier/tests` : « 609 passed, 4 skipped in 230.50s » (sautés : `test_vrai_scan_simule` sans `G1_SCAN_DEMO`, et les 3 scans Gazebo sans `G1_SCAN_SIMULATION=1`) ;
  - `colcon build` puis `colcon test` de `g1_sim` et `g1_nav` : « Summary: 138 tests, 0 errors, 0 failures, 4 skipped » ;
  - scans Gazebo de l'Orchestrateur (`G1_SCAN_SIMULATION=1 pytest atelier/tests/test_scan_session_simulation.py`) : « 3 passed in 255.00s » ;
  - `tests_e2e/tout.sh` complet, de 20 h 08 à 20 h 45 environ : **15 / 15** (journaux : `journaux/e2e_2026-10-25_20h08/`). Critère 6 : 1292 s ; 7 : recouvrement de 99,0 % ; 11 : 170 s, recouvrement de 99,2 % ; 12 : murs 0,995 / 0,965, passages 1,0 / 1,0, objets 1,0 (détection et catégorie), 1 faux objet ; 13 : `table_1` décochée, 0 pixel d'écart, arrivé à 0,07 m de salle_e2e ; 14 : 54 s ; 15 : 53 s, flèches 1,34 m puis arrêt, parcours Firefox « 2 passed ».
- **Reste** :
  - **rien n'a été essayé sur le vrai G1** : 1801 et 1802 lancés par `g1-scan` sur eno2, enregistrement de `/unitree/slam_mapping/*` au câble (méthode A), repère et hauteur réels du nuage (champ `repere` de `rapport.json`), qualité de la reconnaissance sur un vrai nuage du MID-360, seuils de bruit réglés sur la simulation ;
  - après l'adoption d'un vrai scan, les salles, les nœuds et les zones sont à replacer à la main (repère de la carte Unitree) ;
  - les enregistrements (environ 100 Mo par minute) ne sont pas effacés automatiquement après l'adoption ;
  - l'aperçu en direct garde la traînée des piétons ; le pilote direct de l'exploration ne contourne pas un obstacle bas (couloir abandonné après 30 s, ou `--pilote guide`) ;
  - limites de la reconnaissance : armoire de plus de 1,8 m prise pour un mur, catégorie fragile d'un objet vu de loin, mur vu d'un seul côté placé sur sa face ;
  - pas de pagination de l'historique des scans ; vérifications à la main sur tablette (liste de l'agent Interface) non faites.
