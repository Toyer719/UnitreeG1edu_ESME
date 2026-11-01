# Atelier G1 : le logiciel de configuration des lieux

Plan de construction pour une équipe d'agents. Il s'agit de tout ce qui peut se faire **sans le robot**.

Ce document est la référence commune. Chaque agent lit en entier les sections 1 à 5 (but, contraintes, architecture, contrats, organisation), puis sa propre fiche dans la section 6. En cas de doute, les contrats de la section 4 font foi. On ne les modifie qu'en passant par l'agent intégrateur.

Vague 2, le scan intégré : chaque agent lit aussi la section 9 en entier (contrats, fiches et critères de cette vague). Ses contrats font foi au même titre que ceux de la section 4.

Vague 3, le vrai robot (conteneur du Jetson, pont vers la marche, repérage au démarrage) : chaque agent lit aussi la section 10 en entier. Ses contrats font foi au même titre que ceux des sections 4 et 9.

Vague 4 (point principal, passants, comportement du guide, pilotage et danses, emplacements de l'équipe) : chaque agent lit aussi la section 11 en entier. Ses contrats font foi au même titre que ceux des sections 4, 9 et 10.

Vague 5 (interface à la SolidWorks, carte 3D, scan corrigé sans reconnaissance, vitesse minimale et mode du pont, caméra See3CAM) : chaque agent lit aussi la section 12 en entier. Ses contrats font foi au même titre que ceux des sections 4 et 9 à 11.

---

## 1. Le but

Un seul logiciel, **Atelier G1**, qui permet à une personne sans compétence en robotique de :

1. **Créer un lieu** (un bâtiment, un ou plusieurs étages).
2. **Inventer un environnement 3D**, sans scan : dessiner des murs, laisser des passages pour les portes, poser des tables, des chaises, des poteaux, ajouter des piétons qui marchent. Le tout se voit en 3D.
3. **Obtenir automatiquement la carte 2D** de navigation à partir de cet environnement inventé.
4. **Placer les points** sur la carte :
   - salles et point d'accueil ;
   - nœuds et couloirs des itinéraires ;
   - zones interdites et zones lentes.
5. **Simuler le robot** dans cet environnement : le faire aller d'un point A à un point B, en contournant les obstacles et les piétons.
6. Plus tard, avec le robot, **scanner un vrai bâtiment en 3D** avec la cartographie intégrée d'Unitree. La carte du scan remplace alors celle de l'environnement inventé, et tout le reste fonctionne pareil.

Le même logiciel, avec les mêmes fichiers, sert au vrai robot. Seuls deux éléments changent : la source de la carte (le scan au lieu de l'environnement inventé) et le moteur de déplacement.

### Ce qui se fait sans le robot

Tout ce document : formats de fichiers, éditeur 2D et 3D, générateur de monde, simulation Gazebo, navigation Nav2, routeur, banc de test, interface web. Pour le scan, on prépare aussi le client du service du robot, un faux service pour les tests, et une chaîne complète de scan simulé dans Gazebo.

### Ce qui attend le robot

- Le vrai scan : commandes 1801 et 1802 du service `slam_operate`.
- La vraie relocalisation (1804) et la navigation d'Unitree (1102).
- La vérification des noms de champs JSON de ce service : ils viennent d'un projet tiers et ne sont pas encore vérifiés sur notre G1.
- Le pont `/cmd_vel` → `/api/sport/request` (commande 7105) sur le vrai robot.
- Les réglages finaux de Nav2 au milieu de vraies personnes.

---

## 2. Contraintes et environnement

| Élément | Valeur |
|---|---|
| Système | Ubuntu 22.04, ROS 2 Humble, CycloneDDS (`RMW_IMPLEMENTATION=rmw_cyclonedds_cpp`) |
| Simulation | Gazebo **Fortress** (commande `ign gazebo`, paquets `ros_gz_sim`, `ros_gz_bridge`, messages `ignition.msgs.*`) |
| Navigation | Nav2 Humble : Smac 2D, MPPI (`motion_model: Omni`, le G1 se déplace aussi sur le côté), Collision Monitor, filtre Keepout, `nav2_simple_commander` |
| Python projet | `~/robot-g1/.venv-projet` (FastAPI, uvicorn, Open3D, numpy < 2, voit `rclpy` grâce à `--system-site-packages`) |
| Python simulation MuJoCo | `~/robot-g1/.venv-sim` (MuJoCo, PyTorch processeur, pygame, SDK Unitree) |
| Espace ROS 2 | `~/robot-g1/ws` (déjà présents : `livox_ros_driver2`, `fast_lio`) |
| Environnement shell | `source ~/robot-g1/setup/env.sh` (chargé par `~/.bashrc`) |
| Robot (plus tard) | G1 EDU 29 ddl ; Jetson Ubuntu 20.04 avec Docker ; réseau 192.168.123.x ; PC en .99 |

Règles qui s'imposent à tous les agents :

- **Tout doit tourner sans robot et sans écran.** Chaque fonctionnalité a un test automatique qui passe en mode sans fenêtre : `ign gazebo -s -r --headless-rendering`, et pytest.
- **Chaque outil prend `--lieu DOSSIER`**, et n'écrit que dans ce dossier, sauf les journaux, dans `~/robot-g1/journaux/`. Un id seul (ex. `demo`) désigne `~/robot-g1/lieux/demo` (section 4.1).
- **Unités** : mètres, radians, angle `theta` mesuré depuis l'axe x, sens inverse des aiguilles d'une montre. Repère `map` : z vers le haut.
- **Langue** : interface, messages et documentation en français. Noms de fichiers et de champs en français sans accents (`salles.yaml`, `phrase_arrivee`).
- **Noms de commandes déjà pris**, à ne pas réutiliser : `g1-sim`, `g1-sim-marche`, `g1-sim-demo`, `g1-etat`, `g1-telecommande`, `g1-releve`, `g1-nuage`, `g1-manette`, `g1-manette-virtuelle`, `g1-premiers-pas`, `g1-personnes`, `g1-parler`, `g1-ecouter`. Chaque commande `g1-x` a aussi un alias `gl-x` dans `~/robot-g1/bin`.
- **Pièges déjà rencontrés** dans ce projet :
  - pygame intercepte Ctrl+C : mettre `SDL_NO_SIGNAL_HANDLERS=1` avant l'import ;
  - la fenêtre MuJoCo tourne dans un fil de fond : le joindre avant de quitter ;
  - `set -u` est incompatible avec `source /opt/ros/humble/setup.bash` ;
  - le démon `ros2` peut garder un ancien environnement : utiliser `ros2 topic list --no-daemon`.

---

## 3. Architecture

```
                 Navigateur (Atelier G1)
   Lieux · Monde 3D · Carte · Salles · Itinéraires · Zones · Simulation · Scan · Pilotage
                          │  HTTP + WebSocket
                          ▼
             atelier/serveur  (FastAPI, uvicorn)
       │ lit / écrit            │ lance / arrête           │ écoute / commande
       ▼                        ▼                          ▼
 atelier/lieu  ◄── atelier/monde ──►  ws/src/g1_sim  ◄──►  ws/src/g1_nav
 (paquet de lieu)   (générateur)       (Gazebo + robot       (Nav2, routeur,
                    monde.yaml →        proxy)                guide, banc)
                    SDF + carte 2D
       ▲
 atelier/scan  (client slam_operate, faux service, carte 3D → carte 2D, enregistrement des salles)
```

Principe : le serveur ne contient aucune logique robotique. Il appelle les bibliothèques Python (`atelier.lieu`, `atelier.monde`, `atelier.scan`) et lance des commandes ROS 2 (`ros2 launch g1_sim …`, `ros2 launch g1_nav …`). Tout ce que fait l'interface doit donc aussi être possible en ligne de commande.

### Arborescence cible

```
~/robot-g1/
├── atelier/                       # paquet Python « atelier » (lancé avec .venv-projet)
│   ├── lieu/                      # agent Données
│   │   ├── modeles.py             # dataclasses Lieu, Etage, Salle, Noeud, Couloir, Zone, Monde…
│   │   ├── fichiers.py            # charger / enregistrer / valider un paquet de lieu
│   │   ├── conversions.py         # pixel ↔ monde, angle ↔ quaternion
│   │   └── schemas/*.json         # schémas JSON de chaque fichier YAML
│   ├── monde/                     # agent Monde
│   │   ├── sdf.py                 # monde.yaml → monde Gazebo .sdf
│   │   ├── carte.py               # monde.yaml → carte 2D .pgm + .yaml
│   │   ├── zones.py               # zones.yaml → masque Keepout .pgm
│   │   └── mjcf.py                # bonus : monde.yaml → scène MuJoCo avec le G1
│   ├── scan/                      # agent Scan et robot
│   │   ├── slam_client.py         # client du service slam_operate (1801 … 1901)
│   │   ├── faux_slam.py           # faux service slam_operate sur « lo », pour les tests
│   │   ├── carte3d.py             # enregistrement → nuage .pcd
│   │   ├── carte2d.py             # nuage .pcd → carte .pgm + .yaml
│   │   └── salle.py               # position actuelle du robot → salle ou nœud
│   ├── serveur/                   # agent Interface
│   │   ├── main.py                # application FastAPI
│   │   ├── routes/                # lieux, monde, carte, salles, itineraires, zones, simulation, guide, scan
│   │   ├── processus.py           # lancer / arrêter les ros2 launch, suivre leur état
│   │   └── pont_ros.py            # nœud rclpy dans un fil : position du robot, /guide/*
│   ├── web/                       # agent Interface (HTML, CSS, JS modules, sans compilation)
│   │   ├── index.html
│   │   ├── js/  css/
│   │   ├── js/coque/, js/carte3d/, js/camera/, css/theme.css   # vague 5 : coque, carte 3D, caméra (section 12)
│   │   └── vendor/                # leaflet, three.js copiés en local (fonctionne sans Internet)
│   └── tests/                     # tests unitaires (chaque agent dans ses fichiers)
├── ws/src/
│   ├── g1_sim/                    # agent Simulation (ament_cmake)
│   │   ├── models/g1_proxy/model.sdf
│   │   ├── config/pont_gz.yaml    # correspondances ros_gz_bridge
│   │   └── launch/simulation.launch.py
│   ├── g1_nav/                    # agent Navigation (ament_python)
│   │   ├── g1_nav/routeur.py, guide.py, banc.py, odom_vers_tf.py, reperage.py (vague 3)
│   │   ├── g1_nav/moteurs.py (interface Moteur), moteur_nav2.py, moteur_unitree.py
│   │   ├── config/nav2_g1_simu.yaml, nav2_g1_reel.yaml
│   │   └── launch/navigation.launch.py
│   ├── g1_bridge/                 # vague 3 : pont /cmd_vel → /api/sport/request (section 10.3)
│   ├── g1_jumeau/                 # vague 3 : faux service sport du G1 pour Gazebo (section 10.4)
│   ├── g1_pilotage/               # vague 4 : pilotage depuis l'Atelier, dans le conteneur (section 11.5)
│   └── g1_equipe/                 # vague 4 : chatbot, personnalités, caméra de l'équipe (section 11.6)
├── docker/                        # vague 3 : conteneur Humble du Jetson (section 10.2)
├── choregraphies/                 # vague 4 : chorégraphies du G1 ; musique/ ignoré par Git (section 11.5)
├── lieux/demo/                    # lieu d'exemple fourni par l'agent Données
├── tests_e2e/                     # agent Testeur
└── bin/                           # commandes g1-* (chaque agent ajoute les siennes)
```

---

## 4. Contrats

L'agent intégrateur les fige en phase 0. Ensuite, toute modification passe par lui.

### 4.1 Paquet de lieu

```
lieux/<id>/
├── lieu.yaml
├── mondes/<etage>.monde.yaml      # environnement inventé (facultatif)
├── mondes/<etage>.sdf             # généré
├── cartes/<etage>.pgm + .yaml     # carte 2D Nav2 (générée depuis le monde ou depuis le scan)
├── cartes/<etage>_interdit.pgm + .yaml   # masque Keepout (généré depuis zones.yaml), même taille et origine que la carte
├── cartes/<etage>_lent.pgm + .yaml       # masque des zones lentes (facultatif, phase 3)
├── cartes/<etage>.pcd             # nuage 3D du scan (facultatif)
├── cartes/<etage>.nuage.bin + .json      # nuage d'affichage de la carte 3D (vague 5, section 12.5)
├── cartes/<etage>_unitree.pcd, _unitree.nuage.bin + .json   # carte d'Unitree (g1-scan carte-unitree, 12.5)
├── mondes/<etage>_carte.stl       # carte d'un étage scanné extrudée en un maillage (champ carte_extrudee, 12.5)
├── scans/<session>/               # sessions du scan intégré (section 9.2), une par scan
├── salles.yaml
├── itineraires.yaml
├── zones.yaml
└── modes/*.yaml                   # hors périmètre de ce plan (autre piste)
```

**lieu.yaml**
```yaml
version: 1
nom: "Lycée démo"
langue: fr
etages:
  - id: rdc
    nom: "Rez-de-chaussée"
    source_carte: monde          # monde | scan
accueil: {etage: rdc, x: 1.0, y: 1.0, theta: 0.0}
carte_unitree: null              # nom du .pcd enregistré sur le robot par 1802, ex. "test1.pcd"
```

**mondes/rdc.monde.yaml** : l'environnement inventé, vu de dessus avec des hauteurs
```yaml
version: 1
emprise: {min: [0, 0], max: [30, 20]}          # m, rectangle qui contient tout
murs:
  - {id: m1, de: [0, 0], a: [30, 0], epaisseur: 0.15, hauteur: 2.5}
  - {id: m2, de: [0, 6], a: [11, 6], epaisseur: 0.15, hauteur: 2.5}
  - {id: m3, de: [12, 6], a: [30, 6], epaisseur: 0.15, hauteur: 2.5}   # passage de 1 m = une porte
objets:
  - {id: t1, type: boite, centre: [5, 3], taille: [1.2, 0.6, 0.75], cap: 0.0}
  - {id: p1, type: cylindre, centre: [8, 2], rayon: 0.2, hauteur: 2.5}
  - {id: c1, type: modele, modele: chaise, centre: [5, 4], cap: 1.57}     # modèles : chaise, table, banc, poubelle
pietons:
  - {id: h1, trajet: [[2, 3], [25, 3]], vitesse: 1.0, aller_retour: true}
depart_robot: {x: 1.0, y: 1.0, theta: 0.0}
```

**salles.yaml**
```yaml
- id: b204
  nom: "Salle B204"
  alias: ["b204", "labo de physique"]
  etage: rdc
  pose: {x: 12.4, y: -3.1, theta: 1.57}
  phrase_arrivee: "Voici le labo de physique."
```

**itineraires.yaml**
```yaml
noeuds:
  accueil: {etage: rdc, x: 1.0, y: 1.0}
  c1:      {etage: rdc, x: 7.5, y: 3.0}
couloirs:
  - [accueil, c1]          # passage libre dans les deux sens ; longueur calculée
```
Règle : un nœud tous les 8 m au plus le long d'un couloir, pour la navigation d'Unitree (1102) sur le vrai robot.

**zones.yaml**
```yaml
interdites:
  - {etage: rdc, polygone: [[10, 0], [12, 0], [12, 1], [10, 1]]}
lentes:
  - {etage: rdc, polygone: [[0, 0], [4, 0], [4, 4], [0, 4]], vitesse_max: 0.2}
```

**cartes/rdc.yaml** : format Nav2 standard
```yaml
image: rdc.pgm
resolution: 0.05
origin: [xmin, ymin, 0.0]
negate: 0
occupied_thresh: 0.65
free_thresh: 0.196
```
Valeurs des pixels : 0 = occupé, 254 = libre, 205 = inconnu. La ligne 0 de l'image correspond au **y maximal**. Toute conversion passe par `atelier.lieu.conversions`, et nulle part ailleurs.

**Schémas** (figés en phase 0) : `atelier/lieu/schemas/<nom>.schema.json`, en JSON Schema draft-07, pour `lieu`, `monde`, `salles`, `itineraires`, `zones` et `carte` (les `cartes/*.yaml`). Pour chaque champ, ils disent s'il est obligatoire, son type, son unité et ses valeurs possibles. En cas de doute sur un champ, ce sont eux qui font foi. Champs facultatifs, avec leur valeur par défaut : `carte_unitree` (null), `murs`, `objets` et `pietons` (listes vides), `alias` (liste vide), `phrase_arrivee` (vide : le guide annonce le nom de la salle), `nom` d'une zone. Tous les autres champs des exemples ci-dessus sont obligatoires. Le test `atelier/tests/test_contrats.py` vérifie les schémas et le lieu `demo`.

**Règles complémentaires**, que les schémas ne peuvent pas exprimer (à vérifier dans `atelier.lieu`) :
- **Identifiants** (étages, salles, nœuds, murs, objets, piétons ; un lieu est identifié par le nom de son dossier) : `^[a-z0-9][a-z0-9_-]{0,39}$`. Éviter `yes`, `no`, `on` et `off`, que YAML lit comme des booléens. Uniques dans leur fichier. Dans un monde, ils sont uniques entre murs, objets et piétons, car ils deviennent les noms des modèles Gazebo ; `sol` et `g1_proxy` sont réservés.
- **Salles et nœuds** : chaque salle de `salles.yaml`, accueil compris, a dans `itineraires.yaml` un nœud de même id, à la même position. La salle `accueil` a la pose `accueil` de `lieu.yaml`. Vague 4 (11.2) : c'est la règle du point principal, la salle qui porte l'étiquette `principal` (à défaut, la salle `accueil`), un seul par lieu, obligatoire. Une cible de `/guide/aller` est un id de salle ou de nœud (vague 4 : ou `principal`, ou du JSON, 11.4).
- **Couloirs** : un couloir relie deux nœuds du même étage par un segment droit dans l'espace libre, de 8 m au plus.
- **Murs** : boîte de longueur exactement égale au segment `de` → `a` (pas de débordement aux bouts), d'épaisseur centrée sur le segment, posée au sol. Un passage est l'écart entre les bouts de deux murs alignés.
- **Objets** posés au sol. `boite` : `taille` = [longueur le long du cap, largeur, hauteur]. Encombrement des modèles (longueur × largeur × hauteur, en mètres) : chaise 0,45 × 0,45 × 0,9 ; table 1,2 × 0,8 × 0,75 ; banc 1,5 × 0,4 × 0,45 ; poubelle, cylindre de rayon 0,25 et de 0,8 de haut.
- **Piétons** : départ à `trajet[0]`. `aller_retour: true` : va-et-vient sur le trajet. `false` : boucle, avec retour direct du dernier point au premier.
- **Polygones** : au moins 3 sommets, dans l'ordre du contour, sans répéter le premier.
- **Angles** : de −2π à 2π dans les fichiers, de préférence entre −π et π.
- **Dossier d'un lieu** : partout, `--lieu X` et `lieu:=X` acceptent un chemin, ou un id seul (ex. `demo`) qui désigne `$ATELIER_LIEUX/demo`. Par défaut, `ATELIER_LIEUX` vaut `~/robot-g1/lieux`. Fonction commune : `atelier.chemin_lieu(X)`. Journaux : `atelier.dossier_journaux()`.
- **Tests** : ils travaillent sur une copie de `lieux/demo` dans un dossier temporaire, et n'écrivent jamais dans `lieux/demo`.

### 4.2 ROS 2

| Sujet ou service | Type | Sens | Rôle |
|---|---|---|---|
| `/guide/aller` | std_msgs/String | → guide | identifiant de salle ou de nœud (« b204 », « accueil ») |
| `/guide/stop` | std_msgs/Empty | → guide | arrêt immédiat |
| `/guide/etat` | std_msgs/String (JSON) | guide → | `{"etat": "attente|en_route|bloque|detour|arrive|echec", "cible": "b204", "reste_m": 12.5, "itineraire": ["accueil","c1","b204"]}` |
| `/cmd_vel` | geometry_msgs/Twist | Nav2 → robot | vitesses vx, vy, wz ; simulation : vers Gazebo ; répétition et vrai robot : vers le pont (10.3) |
| `/odom` | nav_msgs/Odometry | robot → | simulation : odométrie de Gazebo ; répétition et vrai robot : odométrie locale `/state_estimator/odom_pelvis` relayée par `odom_vers_tf` (repère odom, section 10.5) |
| `/points` | sensor_msgs/PointCloud2 | robot → | simulation : LiDAR de Gazebo ; répétition et vrai robot : `/unitree/slam_relocation/points` ramené dans le repère `lidar` par `odom_vers_tf` |
| TF | `map → odom → base_link → lidar` | | simulation : `map → odom` fixe (identité) ; répétition et vrai robot : `map → odom` = correction de la relocalisation d'Unitree, `odom → base_link` = odométrie locale (section 10.5) |

Vague 3 (section 10) : sujets du pont (`/api/sport/*`, `/pont/etat`, `/pont/arret`), du repérage (`/reperage/demander`, `/reperage/etat`, `/api/slam_operate/*`, `/unitree/slam_relocation/*`) et du faux G1 (`/g1_jumeau/*`, `/state_estimator/odom_pelvis`) en 10.3 à 10.6. `/guide/etat` peut porter un champ `message` (10.7).

Vague 4 (section 11) : nouveaux états et champs de `/guide/etat`, `/guide/aller` en JSON, `/guide/evenement` (11.4) ; `/pietons/etat`, `/pietons/consigne` (11.3) ; `/personnes/lidar`, `/faux_visiteur/mode`, `/speed_limit` (11.4) ; `/mouvement/maitre`, `/pilotage/etat`, `/api/arm/*`, `/api/voice/*`, `/arm_sdk`, `/lowstate` (11.5) ; `/visiteur/texte`, `/visiteurs/detectes`, `/personnalite/active`, `/robot/dire` (11.6).

Vague 5 (section 12) : requêtes 7001 du pont sur `/api/sport/request`, état `pas_en_marche` et champ `mode_robot` de `/pont/etat`, `/g1_jumeau/mode` (12.6) ; `/camera_poitrine/image/compressed`, `/camera_poitrine/etat`, `/visiteurs/image/compressed`, champs `boite` et `image` de `/visiteurs/detectes` (12.7) ; `/unitree/slam_relocation/global_map` (12.5).

### 4.3 Commandes

| Commande | Rôle | Agent |
|---|---|---|
| `g1-atelier [--port 8000]` | lance le serveur et ouvre le navigateur | Interface |
| `g1-lieu creer ID --nom NOM` / `g1-lieu valider --lieu L` | créer ou vérifier un paquet de lieu | Données |
| `g1-monde generer --lieu L --etage E` | monde.yaml → .sdf, carte .pgm/.yaml, masque | Monde |
| `g1-monde simuler --lieu L --etage E [--sans-fenetre]` | Gazebo, robot proxy et piétons : appelle `ros2 launch g1_sim simulation.launch.py` (section 4.5) | Monde |
| `g1-guide navigation --lieu L --etage E [--simu]` | Nav2, routeur et guide sur la carte du lieu | Navigation |
| `g1-guide aller ID` / `g1-guide stop` | envoyer le robot (publie sur /guide/*) | Navigation |
| `g1-banc --lieu L --etage E --trajets 50` | banc de test, résultats en CSV | Navigation |
| `g1-slam scan-debut|scan-fin --nom N|relocaliser|aller|pause|reprendre|arreter [--faux]` | client slam_operate | Scan |
| `g1-carte-3d --lieu L --etage E --enregistrement DOSSIER` | enregistrement → .pcd | Scan |
| `g1-carte-2d --lieu L --etage E` | .pcd → carte .pgm/.yaml | Scan |
| `g1-salle ajouter NOM [--type salle|noeud] --lieu L` | position actuelle du robot → salles ou itinéraires | Scan |

Vague 2 (section 9.5) : `g1-scan demarrer|arreter|traiter|etat|adopter`, agent Orchestrateur.

Vague 3 (section 10) : `g1-jetson construire|envoyer|lieu|demarrer|arreter|etat|journal|verifier` (agent Jetson) ; `g1-monde simuler … --jumeau` (agent Pont et faux G1) ; `g1-guide navigation … --localisation simu|unitree|amcl|externe --pont auto|oui|non` et `g1-slam faux-service --jumeau --lieu L --etage E` (agent Repérage). Ajouts acceptés à l'assemblage (10.12) : `g1-jetson tester-local|shell`, `construire --contexte|--incomplet`, `demarrer --vitesse-max` ; `g1-guide navigation … --vitesse-max`.

Vague 4 (section 11) : `g1-lieu migrer --lieu L [--depuis-depart] [--a-blanc]` (agent Point principal) ; `g1-banc … --scene ID` (agent Passants) ; `g1-pilotage` (agent Pilotage et danses, facultatif : les commandes de l'onglet Pilotage en ligne de commande).

Vague 5 (section 12) : `g1-scan traiter --refaire` et `g1-scan carte-unitree --lieu L [--etage E]` (agent Scan) ; `g1-visiteurs` et l'exécutable `camera_usb` de `g1_equipe` (agent Caméra) ; `--vitesse-max` refusée sous 0,2 m/s.

Ajouts de la phase 1, acceptés à l'assemblage : `g1-lieu liste` ; `g1-monde simuler … [--monde F.sdf] [--afficher]` ; `g1-guide etat` et `g1-guide aller ID --sans-suivre` ; `g1-banc … [--simu] [--lancer] [--graine N] [--seuil P] [--csv F]` ; `g1-slam etat` et `g1-slam faux-service [--gazebo] [--relocalise]`, `scan-fin --lieu L` (note `carte_unitree`) ; `g1-atelier [--sans-navigateur] [--hote H]`.

### 4.4 API du serveur

REST sous `/api`, en JSON. Chaque route correspond à un fichier du paquet, ou à une action.

- `GET/POST /api/lieux`, `GET /api/lieux/{id}`
- `GET/PUT /api/lieux/{id}/etages/{e}/monde`, `POST …/monde/generer`
- `GET …/carte.png` : la carte PGM convertie en PNG pour l'affichage. `GET …/carte.yaml`
- `GET/PUT /api/lieux/{id}/salles`, `…/itineraires`, `…/zones`
- `POST /api/simulation/demarrer {lieu, etage}`, `POST /api/simulation/arreter`, `GET /api/simulation/etat`
- `POST /api/guide/aller {cible}`, `POST /api/guide/stop`
- `POST /api/scan/debut`, `POST /api/scan/fin {nom}` (vrai robot ou faux service). **Remplacées en vague 2** par l'API du scan intégré (section 9.7) : `POST /api/scan/demarrer` et `POST /api/scan/arreter`.
- WebSocket `/ws/etat` : environ 10 messages par seconde, `{robot: {x, y, theta}, guide: {...}, pietons: [...], processus: {...}}`

Précisions et ajouts de la phase 1, acceptés à l'assemblage :
- `GET …/carte.yaml` renvoie du JSON : les champs du fichier, plus `largeur` et `hauteur` (pixels), `bornes` `{xmin, ymin, xmax, ymax}` en mètres et `modifiee`.
- Routes ajoutées : `GET /api/etat`, `PUT /api/lieux/{id}` (lieu.yaml), `GET /api/lieux/{id}/verification`, `PUT …/salles?synchroniser=true` (crée ou déplace le nœud de même id, recopie l'accueil dans lieu.yaml), `GET /api/scan/etat` (nouveau format en vague 2), `POST /api/scan/faux-service/arreter` (retirée en vague 2, section 9.7).
- Champs facultatifs : `fenetre` (false) et `navigation` (true) de `simulation/demarrer` ; `faux`, `lieu` et `etage` du scan.
- Chaque PUT renvoie `{enregistre: [...], rapport: {ok, erreurs, avertissements}}` ; une erreur est toujours `{detail, erreurs?, sortie?}`, en français.
- `/ws/etat` contient aussi `simulation`, `temps_sim` et `ros {actif, erreur, nav2}`.

Vague 3 (section 10.8) : champ `mode` (`simu`, `repetition`, `robot`) de `POST /api/simulation/demarrer` ; `GET /api/robot/etat`, `POST /api/robot/reperer`, `POST /api/robot/arret` ; `mode`, `reperage` et `pont` dans `/ws/etat`.

Vague 4 (section 11) : `GET/PUT /api/lieux/{id}/principal` (11.2) ; `/api/pilotage/*` et `/ws/pilotage` (11.5) ; `GET/PUT /api/lieux/{id}/personnalites`, `…/dialogues`, `…/camera` (11.6) ; `evenements`, `maitre`, `personnes` et `visiteurs` dans `/ws/etat`, et `pietons` tiré de `/pietons/etat` quand il est publié.

Vague 5 (section 12.4) : `POST /api/arret`, `POST /api/arret/debloquer`, `GET /api/arret`, `GET /api/robot/liaison`, `GET …/etages/{e}/nuage` et `…/nuage/info`, `GET …/etages/{e}/monde/maillage`, `GET /api/scan/nuage` et `…/info`, `GET /api/camera/image`, `…/flux` et `…/etat` ; champ `arret` dans `/ws/etat` ; retirées : `GET/PUT /api/scan/sessions/{s}/reconnaissance`, `GET /api/scan/sessions/{s}/monde`.

### 4.5 Lancements ROS 2

```
ros2 launch g1_sim simulation.launch.py lieu:=DOSSIER etage:=ID sans_fenetre:=true|false [monde:=FICHIER.sdf]
ros2 launch g1_nav navigation.launch.py lieu:=DOSSIER etage:=ID simu:=true|false moteur:=nav2|unitree
```

| Argument | Défaut | Rôle |
|---|---|---|
| `lieu` | obligatoire | dossier du lieu, ou id seul (section 4.1, `atelier.chemin_lieu`) |
| `etage` | obligatoire | id de l'étage |
| `sans_fenetre` (g1_sim) | `false` | `true` : `ign gazebo -s -r --headless-rendering`, serveur seul, sans fenêtre |
| `monde` (g1_sim) | vide | monde .sdf à charger ; vide : `<lieu>/mondes/<etage>.sdf`. Le robot apparaît à `depart_robot` de `<lieu>/mondes/<etage>.monde.yaml` |
| `simu` (g1_nav) | `false` | `true` : temps simulé (`use_sim_time`) et repère `map → odom` fixe ; `false` : vrai robot, avec `odom_vers_tf.py` |
| `moteur` (g1_nav) | `nav2` | `nav2` : `MoteurNav2`, Nav2 lancé ; `unitree` : `MoteurUnitree` (commande 1102), Nav2 non lancé |

- g1_nav lit `<lieu>/cartes/<etage>.yaml`, `<lieu>/cartes/<etage>_interdit.yaml`, `<lieu>/salles.yaml` et `<lieu>/itineraires.yaml`.
- Les commandes `g1-monde simuler` et `g1-guide navigation` ne font que traduire leurs options en ces arguments.
- Les deux lancements respectent les variables `ROS_DOMAIN_ID` et `IGN_PARTITION` de l'environnement : pendant les tests, chaque agent a les siennes.
- Le monde Gazebo porte le nom de l'étage (`<world name="rdc">`) : sujets `/world/rdc/…`.
- `moteur:=factice` (ajout de la phase 1) : `MoteurFactice`, sans Gazebo ni Nav2, pour les essais.
- Vague 4 (section 11) : `pietons:=corps|acteurs` pour g1_sim (11.3, défaut `corps`) ; `personnes:=true|false` pour g1_nav (11.4, détecteur de personnes au LiDAR, défaut true).
- Vague 5 (section 12.6) : `vitesse_max:=` de g1_nav baisse aussi les vitesses maximales de Nav2 et refuse moins de 0,2 m/s ; paramètre `tolerance_orientation_rad` du guide.
- Vague 3 (section 10) : `jumeau:=true|false` pour g1_sim (10.4, défaut `false` : rien ne change) ; `localisation:=simu|unitree|amcl|externe` et `pont:=auto|true|false` pour g1_nav (10.7), plus `nuage:=SUJET` et `vitesse_max:=M_PAR_S` (ajouts acceptés à l'assemblage, 10.12). `simu:=false` lance le relais `odom_vers_tf` de la section 10.5, qui remplace celui de la vague 1.
- Si `cartes/<etage>_interdit.yaml` manque, g1_nav crée un masque tout libre dans `/tmp` et le signale ; si la carte manque, il s'arrête et propose `g1-monde generer`.
- Les deux lancements sont complets depuis la phase 1 (agents Simulation et Navigation). Ils sont compilés dans `ws/install` : `cd ~/robot-g1/ws && colcon build --symlink-install --packages-select g1_sim g1_nav`.

### 4.6 Interface Moteur

Fichier `ws/src/g1_nav/g1_nav/moteurs.py`. Le guide passe toujours par un `Moteur`, jamais directement par Nav2 ou par `slam_operate`.

| Méthode | Rôle |
|---|---|
| `demarrer(poses) -> bool` | `poses` : liste de `(x, y, theta)` dans le repère `map`. La dernière est la destination, les autres sont les nœuds à traverser dans l'ordre. Rend la main tout de suite et remplace un déplacement en cours. Renvoie `False` si le moteur refuse, et `etat()` indique alors `echec`. `ValueError` si `poses` est vide |
| `annuler()` | arrête le robot au plus vite ; ensuite `etat()` est au repos : une annulation n'est pas un échec |
| `etat() -> dict` | `{en_cours, arrive, echec, reste_m, progresse}`. Trois booléens, dont un seul vrai au plus ; tous faux : repos. `reste_m` : mètres jusqu'à la dernière pose, `None` si inconnu, `0.0` à l'arrivée. `progresse` : `reste_m` a baissé d'au moins 0,10 m pendant la dernière seconde |

- Les méthodes rendent la main en moins d'une seconde. Elles sont appelées depuis le fil du guide, environ 5 fois par seconde pour `etat()`.
- Réalisations : `MoteurNav2` dans `moteur_nav2.py` (agent Navigation) ; `MoteurUnitree` dans `moteur_unitree.py` (agent Scan, seul fichier de `g1_nav` qui lui appartient).
- `moteurs.py` fournit aussi `SuiviProgres`, qui calcule `progresse`, et `MoteurFactice`, un moteur sans ROS pour les tests du guide. Tests : `ws/src/g1_nav/test/test_moteurs.py`.
- Constructeurs (phase 1) : `MoteurNav2()` ; `MoteurUnitree(noeud=None, …)`, que le guide crée avec `noeud=` son propre nœud. Le faux service est choisi par `G1_SLAM_FAUX=1`, ou par `use_sim_time`.

---

## 5. Organisation de l'équipe d'agents

Sept agents. Chacun possède ses dossiers, et personne n'écrit dans les dossiers d'un autre. Si un agent a besoin d'un changement chez un autre, il le demande à l'intégrateur.

| Agent | Possède | Dépend de |
|---|---|---|
| 1. Intégrateur | section 4, `atelier/__init__.py`, `atelier/lieu/schemas/`, `atelier/tests/test_contrats.py`, `ws/src/g1_nav/g1_nav/moteurs.py`, `setup.py`, `pytest.ini`, `.gitignore`, `tests_e2e/` (avec l'agent 7), revues, fusions | — |
| 2. Données | `atelier/lieu/` (sauf `schemas/`), `lieux/demo/` (écrit par l'intégrateur en phase 0, repris par l'agent Données), `bin/g1-lieu` | contrats |
| 3. Monde | `atelier/monde/`, `bin/g1-monde` (sous-commandes generer et simuler) | Données ; Simulation pour `simuler` |
| 4. Simulation | `ws/src/g1_sim/`, dont `launch/simulation.launch.py`, appelé par `g1-monde simuler` | Monde (fichier .sdf) |
| 5. Navigation | `ws/src/g1_nav/` (sauf `moteurs.py` et `moteur_unitree.py`), `bin/g1-guide`, `bin/g1-banc` | Données, Simulation |
| 6. Interface | `atelier/serveur/`, `atelier/web/`, `bin/g1-atelier` | Données, Monde ; Simulation et Navigation pour l'intégration |
| 7. Scan et Testeur | `atelier/scan/`, `ws/src/g1_nav/g1_nav/moteur_unitree.py`, `bin/g1-slam`, `g1-carte-*`, `g1-salle`, `tests_e2e/` | Données, Simulation, Navigation (guide) |

Vague 2 : agents et fichiers en 9.9. Vague 3 : agents Jetson, Pont et faux G1, Repérage, en 10.10. Vague 4 : agents Point principal, Passants, Comportement du guide, Pilotage et danses, Équipe, en 11.7. Vague 5 : agents Coquille, Carte 3D, Scan, Robot, Caméra, en 12.8.

### Phases

| Phase | Qui | Résultat attendu |
|---|---|---|
| 0. Contrats | Intégrateur | Section 4 figée en schémas JSON, arborescence vide créée, lieu `demo` écrit à la main (30 × 20 m, deux couloirs, accueil et cinq salles), `git init` et premier commit |
| 1. Fondations, en parallèle | 2, 3, 4, 5, 6, 7 | Chaque module fonctionne seul avec ses tests. L'interface travaille avec des réponses factices, la navigation sur un monde écrit à la main |
| 2. Assemblage | Intégrateur + tous | Depuis l'interface : dessiner un monde → générer → simuler → placer une salle → « Y aller » → le robot arrive |
| 3. Foule, scan simulé, banc | 4, 5, 7 | Piétons, détours, chaîne de scan simulé, banc de 50 trajets |
| 4. Recette | Intégrateur + 7 | Tous les critères de la section 7 passent sans fenêtre, puis guide utilisateur |

Avant de lancer les agents :
- le dossier `~/robot-g1` doit être sous Git, avec le `.gitignore` existant ;
- chaque agent travaille dans sa propre copie de travail (worktree), puis l'intégrateur fusionne en fin de phase.

---

## 6. Fiches des agents

### Agent 1 · Intégrateur

**Mission** : garant des contrats, de l'arborescence et de l'assemblage.

Tâches :
1. Phase 0, faite le 25/10 (voir `docs/journal-atelier.md`) :
   - écrire `atelier/lieu/schemas/*.json` à partir de la section 4.1 ;
   - créer l'arborescence et les paquets ROS vides : `ros2 pkg create` pour `g1_sim` en ament_cmake et pour `g1_nav` en ament_python ;
   - écrire l'interface `Moteur` (section 4.6) ;
   - écrire `lieux/demo` : 30 × 20 m, deux couloirs, l'accueil et cinq salles ;
   - faire le premier commit.
2. `bin/g1-atelier` est confié à l'agent Interface (fiche 6).
3. À chaque fin de phase (phase 1 assemblée le 25/10, voir le journal) :
   - fusionner les branches ;
   - lancer `colcon build --symlink-install --packages-select g1_sim g1_nav`, puis tous les tests ;
   - corriger les écarts aux contrats.
4. Tenir à jour `docs/journal-atelier.md` : décisions, écarts, ce qui reste.

**Terminé quand** : les critères de la section 7 passent.

### Agent 2 · Données (`atelier/lieu`)

**Mission** : charger, valider et enregistrer un paquet de lieu, sans aucune dépendance à ROS.

Tâches :
1. Écrire `modeles.py` : dataclasses de chaque objet de la section 4.1, avec `vers_dict()` et `depuis_dict()`.
2. Écrire `fichiers.py` :
   - `charger_lieu(dossier)` et `enregistrer_lieu(lieu)` ;
   - validation par les schémas JSON, avec des messages en français qui disent quoi corriger (« salles.yaml, salle « b204 » : il manque theta ») ;
   - écriture atomique : fichier temporaire, puis renommage.
3. Écrire `conversions.py` :
   - `monde_vers_pixel(x, y, info_carte)` et `pixel_vers_monde(...)`, en tenant compte de l'axe y inversé de l'image ;
   - `cap_vers_quaternion(theta)` et `quaternion_vers_cap(q)`.
4. Écrire `bin/g1-lieu creer|valider`.
5. Reprendre `lieux/demo`, écrit par l'intégrateur en phase 0 : un monde inventé de 30 × 20 m, deux couloirs parallèles reliés à chaque bout (pour qu'il existe un chemin de secours), l'accueil et cinq salles dont `b204`, un graphe en boucle, une zone interdite et une zone lente. Le garder valide : `atelier/tests/test_contrats.py` doit continuer de passer.

**Tests** : aller-retour de chaque fichier, erreurs de validation, conversions sur des cas connus, coins de la carte compris.

### Agent 3 · Monde (`atelier/monde`)

**Mission** : transformer `monde.yaml` en monde Gazebo et en carte 2D, sans scan.

Tâches :
1. Écrire `carte.py` :
   - tracer les murs et objets qui coupent la tranche de 0,1 à 1,5 m de haut, avec une résolution de 0,05 m ;
   - laisser une marge d'un pixel ; l'intérieur de l'emprise est libre (254) ;
   - écrire `.pgm` et `.yaml` (section 4.1) ;
   - les piétons ne vont **pas** sur la carte : ce sont des obstacles mobiles.
2. Écrire `sdf.py` :
   - générer un monde SDF 1.9 pour Fortress : sol, lumière, murs (boîtes orientées le long de chaque segment) et objets ;
   - modèles simples écrits en SDF, sans téléchargement : chaise, table, banc, poubelle ;
   - piétons en `<actor>` avec un `<script>` de trajectoire qui suit `trajet` à la `vitesse` donnée, aller-retour si demandé ;
   - plugins de monde : Physics, SceneBroadcaster, UserCommands, Sensors (rendu ogre2).
3. Écrire `zones.py` : `zones.yaml` → masque Keepout, à la même taille et la même origine que la carte.
4. Écrire `bin/g1-monde`, avec l'alias `gl-monde` :
   - `generer` : monde.yaml → .sdf, carte et masque ;
   - `simuler` : vérifie que `mondes/<etage>.sdf` existe (sinon, propose `generer`), puis appelle `ros2 launch g1_sim simulation.launch.py lieu:=… etage:=… sans_fenetre:=…` (section 4.5).
5. Bonus, après la phase 3 : écrire `mjcf.py`, une scène MuJoCo qui contient le monde et le G1 de `unitree_rl_gym`. Elle permettra de rejouer le trajet de Nav2 avec la politique de marche de `~/robot-g1/sim/g1_marche.py`.

**Tests** :
- un pixel sur un mur est à 0, un pixel au milieu d'un couloir est à 254 ;
- le SDF généré se charge sans erreur avec `ign gazebo -s -r --iterations 10 monde.sdf` ;
- le nombre de modèles du SDF correspond au nombre de murs et d'objets.

### Agent 4 · Simulation (`ws/src/g1_sim`)

**Mission** : un robot proxy de la taille du G1 dans le monde généré, relié à ROS 2.

Tâches :
1. Écrire `models/g1_proxy/model.sdf` :
   - boîte de 0,45 × 0,30 × 1,30 m, 35 kg, centre de masse bas ;
   - plugin `ignition-gazebo-velocity-control-system` (le robot suit vx, vy et wz, comme le G1) ;
   - plugin `ignition-gazebo-odometry-publisher-system` (odom → base_link, dimensions 2).
2. Ajouter le LiDAR `gpu_lidar` à 1,2 m de haut :
   - 360 échantillons sur 360° à l'horizontale ;
   - 16 lignes verticales entre −7° et +52° (comme le MID-360) ;
   - portée de 0,1 à 40 m, 10 Hz.
3. Écrire `config/pont_gz.yaml` pour `ros_gz_bridge` : `/cmd_vel`, `/odom`, `/tf`, `/clock` et `/points` (`ignition.msgs.PointCloudPacked` → `sensor_msgs/msg/PointCloud2`).
4. Écrire `launch/simulation.launch.py` :
   - arguments : ceux de la section 4.5 (`lieu`, `etage`, `sans_fenetre`, `monde`) ;
   - lancer Gazebo sur `mondes/<etage>.sdf` et faire apparaître `g1_proxy` à `depart_robot` ;
   - lancer le pont et `robot_state_publisher` (repères base_link → lidar).
5. La sous-commande `g1-monde simuler` est écrite par l'agent Monde : elle appelle ce lancement.
6. Vérifier que les piétons (`<actor>`) sont vus par le LiDAR. Sinon, ajouter à chaque piéton un cylindre qui le suit (plugin de trajectoire), et le noter dans le journal.

**Tests, sans fenêtre** :
- `/points` publie plus de 5 messages par seconde ;
- envoyer `/cmd_vel` vx = 0,3 pendant 3 s fait avancer `/odom` d'environ 0,9 m ;
- le robot ne traverse pas un mur.

### Agent 5 · Navigation (`ws/src/g1_nav`)

**Mission** : aller d'un point A à un point B sur la carte du lieu, contourner les obstacles, changer de couloir.

Tâches :
1. Écrire `config/nav2_g1_simu.yaml` :
   - emprise circulaire de 0,35 m ;
   - vitesses maximales vx 0,5, vy 0,25 et wz 0,8 ;
   - planificateur Smac 2D ; contrôleur MPPI en `motion_model: Omni` ;
   - carte des coûts : couche d'obstacles (voxel_layer) alimentée par `/points`, inflation de 0,4 m ;
   - filtre Keepout sur le masque ;
   - Collision Monitor : polygone « ralentir » de 1 m à ×0,5, polygone « arrêt » de 0,4 m.
2. Écrire `nav2_g1_reel.yaml` : mêmes réglages, vitesses plafonnées à 0,4 / 0,2 / 0,6. Il servira sur le robot.
3. Écrire `launch/navigation.launch.py`. Arguments : ceux de la section 4.5 (`lieu`, `etage`, `simu`, `moteur`). En simulation, il publie un repère fixe `map → odom`. Sur le robot, ce sera `odom_vers_tf.py`, qui relaie `/unitree/slam_relocation/odom`.
4. Écrire `routeur.py`. Il charge `itineraires.yaml`, cherche le plus court chemin avec A*, et peut marquer un couloir bloqué pour 120 s.
5. Écrire `guide.py` :
   - il écoute `/guide/aller` et `/guide/stop`, et publie `/guide/etat` (section 4.2) ;
   - il envoie la suite de nœuds à Nav2 avec `nav2_simple_commander` (`goThroughPoses`) ;
   - si la distance restante ne baisse pas pendant 3 s, état `bloque` ; pendant 8 s, il annule, marque le couloir bloqué, recalcule l'itinéraire (`detour`) et repart.
   - Passer par l'interface `Moteur` de `g1_nav/moteurs.py` (section 4.6). `MoteurNav2` (`moteur_nav2.py`) est à faire maintenant. `MoteurUnitree` (`moteur_unitree.py`), avec la commande 1102 et des tronçons de 8 m au plus, sera fait par l'agent 7. `MoteurFactice` sert aux tests du guide sans Nav2.
6. Écrire `banc.py` et `bin/g1-banc` :
   - N trajets entre salles tirées au sort ;
   - un CSV avec une ligne par trajet : départ, arrivée, réussite, durée, nombre d'arrêts, distance minimale aux piétons, détours ;
   - un résumé à l'écran.
7. Écrire `bin/g1-guide navigation|aller|stop`.

**Tests, dans le lieu demo et sans fenêtre** :
- accueil → b204 arrive à moins de 0,3 m en moins de 90 s ;
- une boîte posée dans le couloir principal provoque `bloque` → `detour` → `arrive` par l'autre couloir ;
- avec 5 piétons, 20 trajets donnent au moins 90 % de réussite.

### Agent 6 · Interface (`atelier/serveur`, `atelier/web`)

**Mission** : un logiciel web que l'on comprend sans formation, servi par le PC (et plus tard par le Jetson).

Tâches :
1. Serveur FastAPI (section 4.4) :
   - routes de lecture et d'écriture du paquet de lieu, en passant par `atelier.lieu` ;
   - génération en passant par `atelier.monde` ;
   - `processus.py` : lancer et arrêter `g1-monde simuler` et `g1-guide navigation` en groupes de processus ; journaux dans `~/robot-g1/journaux/` ; état disponible ;
   - `pont_ros.py` : nœud rclpy dans un fil, qui écoute `/odom` (ou TF `map → base_link`) et `/guide/etat`, et publie `/guide/aller`. Il alimente le WebSocket `/ws/etat`.
2. Interface web, sans étape de compilation : ES modules, Leaflet et three.js copiés dans `web/vendor/`.
   - **Lieux** : liste, création, choix de l'étage.
   - **Monde** :
     - vue de dessus pour dessiner : mur (cliquer-glisser, accroché à une grille de 0,25 m), objet (choisir un modèle et cliquer), piéton (cliquer les points du trajet), passage (couper un mur) ;
     - vue 3D (three.js) mise à jour en direct ; annuler et refaire ; enregistrer.
   - **Carte** : bouton « Fabriquer la carte » (génération), affichage de la carte (Leaflet `CRS.Simple`, coordonnées en mètres grâce à `conversions`).
   - **Salles** : clic pour placer, glisser pour régler l'orientation, panneau nom, alias, phrase d'arrivée.
   - **Itinéraires** : clic pour poser un nœud, clic sur deux nœuds pour les relier, avertissement si un couloir dépasse 8 m.
   - **Zones** : polygones interdits (rouge) et lents (orange).
   - **Simulation** :
     - « Lancer la simulation » ;
     - robot et piétons en direct sur la carte et dans la vue 3D ;
     - liste des salles avec « Y aller » ; gros bouton « Arrêt » ;
     - affichage de l'état du guide.
   - **Scan** : boutons Démarrer / Terminer reliés à `g1-slam`, à tester avec le faux service (vague 1 ; remplacé en vague 2 par l'onglet du scan intégré, section 9.7).
3. Règles d'écriture de l'interface :
   - les boutons disent ce qu'ils font (« Fabriquer la carte », « Y aller ») ;
   - les erreurs disent quoi corriger ;
   - tout est en français ; l'interface reste utilisable sur une tablette.
4. Écrire `bin/g1-atelier [--port 8000]`, avec l'alias `gl-atelier`. Il charge `env.sh`, lance `uvicorn atelier.serveur.main:app` avec `.venv-projet`, puis ouvre `http://localhost:8000`.

**Tests** :
- tests de l'API avec `fastapi.testclient` sur une copie du lieu `demo` ;
- un test du parcours principal dans le navigateur (Playwright, si on peut l'installer dans `.venv-projet`) ; sinon, une liste de vérifications à la main dans le journal.

### Agent 7 · Scan, robot et Testeur

**Mission A, le scan** : tout préparer pour le jour où le robot sera là, et le prouver en simulation.

Tâches :
1. Écrire `slam_client.py` :
   - utiliser `unitree_sdk2py.rpc.client.Client("slam_operate", False)`, `SetTimeout(10)`, `_SetApiVerson("1.0.0.1")`, `_RegistApi(id, 0)` pour 1801, 1802, 1804, 1102, 1201, 1202 et 1901, puis `_Call(id, json.dumps({"data": {...}}))` ;
   - formats, à vérifier sur le robot : 1801 `{"slam_type": "indoor"}` ; 1802 `{"address": "…pcd"}` ; 1804 `{x, y, z, q_x, q_y, q_z, q_w, address}` ; 1102 `{"targetPose": {...}, "mode": 1}` ;
   - lire `rt/slam_info` et `rt/slam_key_info` (type `String_`, JSON, `task_result.is_arrived`) ;
   - dans le journal, noter chaque supposition à vérifier.
2. Écrire `faux_slam.py` : un faux service `slam_operate` sur l'interface `lo`. Il répond aux mêmes commandes avec des JSON plausibles et publie `slam_info` et `slam_key_info`. Pour 1102, il peut piloter le robot proxy de Gazebo en ligne droite, ce qui permet de tester `MoteurUnitree` en simulation.
3. Écrire `bin/g1-slam` (section 4.3). L'option `--faux` utilise `lo` et le faux service ; sans elle, `eno2` et le vrai robot.
4. Écrire `MoteurUnitree` pour le guide de l'agent 5, dans `ws/src/g1_nav/g1_nav/moteur_unitree.py`, sur l'interface `Moteur` (section 4.6) : tronçons de 8 m au plus, le robot s'arrête devant les obstacles, le guide gère pause et détour.
5. Écrire `carte3d.py` et `carte2d.py`.
   - `carte3d.py` assemble un enregistrement (ros2 bag de `/points` et `/odom`, ou de `/unitree/slam_mapping/points` et `/unitree/slam_mapping/odom`) en un nuage `.pcd`, réduit à une grille de 5 cm.
   - `carte2d.py` prend la tranche de 0,1 à 1,5 m, la projette, la nettoie (ouverture morphologique) et écrit `.pgm` et `.yaml`.
6. Écrire `salle.py` et `bin/g1-salle` : lire une fois `/odom` (ou la relocalisation d'Unitree) et ajouter une salle ou un nœud au lieu.

**Mission B, le testeur** : la chaîne de **scan simulé**, qui prouve que tout fonctionnera avec un vrai scan.
- Dans le lieu `demo` simulé, faire parcourir les couloirs au robot proxy (avec le guide) en enregistrant `/points` et `/odom`.
- Enchaîner `g1-carte-3d` puis `g1-carte-2d` sur cet enregistrement.
- Comparer la carte obtenue à celle générée directement depuis le monde : au moins 80 % de recouvrement des pixels occupés.
- Écrire `tests_e2e/` avec l'intégrateur : des scripts sans fenêtre qui reprennent les critères de la section 7, et un `tests_e2e/tout.sh` qui les lance tous et affiche un bilan.

---

## 7. Critères de recette, tous sans robot et sans fenêtre

1. **Monde inventé** : créer le lieu `essai`, y dessiner 6 murs, un passage, 3 objets et 2 piétons, puis enregistrer. `g1-lieu valider` ne signale aucune erreur.
2. **Carte sans scan** : la génération produit `.sdf`, `.pgm`, `.yaml` et le masque. Les tests de pixels de l'agent 3 passent.
3. **Simulation** : `g1-monde simuler --sans-fenetre` démarre en moins de 30 s. `/points` et `/odom` sont publiés.
4. **Point A → point B** : une salle placée depuis l'API, puis `POST /api/guide/aller` : `/guide/etat` passe à `arrive` à moins de 0,3 m.
5. **Chemin de secours** : une boîte placée dans un couloir donne `bloque` → `detour` → `arrive`.
6. **Foule** : 5 piétons et 20 trajets avec `g1-banc` donnent au moins 90 % de réussite, et un CSV est produit.
7. **Scan simulé** : enregistrement, puis `g1-carte-3d` et `g1-carte-2d` ; recouvrement d'au moins 80 % avec la carte générée.
8. **Service du robot simulé** : avec `g1-slam --faux`, les commandes 1801, 1802, 1804 et 1102 suivent le bon déroulé. `MoteurUnitree` mène le robot proxy de l'accueil à b204.
9. **Interface** : le parcours « créer → dessiner → fabriquer la carte → placer une salle → lancer la simulation → Y aller » fonctionne. L'agent 6 fournit soit un test Playwright, soit la liste de vérifications cochée.
10. **Un seul point d'entrée** : `g1-atelier` ouvre le logiciel, et `tests_e2e/tout.sh` affiche « 10 / 10 ».

Critères 11 à 15 (vague 2, scan intégré) : section 9.10. Critères 16 à 20 (vague 3, le vrai robot en répétition, section 10), ci-dessous. En répétition, la vérité terrain est `/g1_jumeau/odom`. Critères 21 à 30 (vague 4, section 11) : à la suite ; `tests_e2e/tout.sh` lance les trente et affiche « N / 30 ».

16. **Conteneur** (`critere_16_conteneur.sh`, agent Jetson) :
    - `g1-jetson construire --arch amd64` réussit (une image déjà construite est réutilisée). Dans l'image : `ros2 pkg prefix g1_nav g1_bridge unitree_api`, `RMW_IMPLEMENTATION=rmw_cyclonedds_cpp`, `python3 -c "import atelier.lieu, atelier.scan.slam_client"` ;
    - `g1-jetson demarrer --local --lieu <copie du demo> --etage rdc` rend la main en moins de 60 s ;
    - en moins de 90 s, l'hôte (même domaine, hors du conteneur) voit les nœuds `pont_g1`, `odom_vers_tf`, `guide`, `bt_navigator` et `map_server`. Il reçoit `/g1_jetson/etat`, `/pont/etat` (conforme, `attente_reperage`), `/reperage/etat` (conforme, `non_repere`) et `/guide/etat` ;
    - dans l'autre sens, `/pont/arret` true publié par l'hôte donne `arret_verrouille` en moins de 3 s ;
    - `g1-jetson etat --local` répond 0. `g1-jetson arreter --local` s'arrête en moins de 30 s, et plus aucun conteneur `g1-jetson-e2e-*` ne reste ;
    - avec `G1_INTERFACES=auto`, sur une machine sans adresse 192.168.123.x, le conteneur s'arrête sur « réseau du robot introuvable » ;
    - jamais de ssh. Avec `E2E_ARM64=1` : aussi `construire --arch arm64`, puis les mêmes vérifications de l'image sous émulation (`uname -m` : `aarch64`).
17. **Pont et faux G1** (`critere_17_pont.sh`, agent Pont et faux G1). Montage : Gazebo `--jumeau` (avec `g1_jumeau`), navigation `--simu --localisation externe --pont oui`, et le relais simple du test (TF tiré de la vérité terrain, `/reperage/etat` repéré). On vérifie :
    - aucun lien direct entre `/cmd_vel` et Gazebo : `ros_gz_bridge` n'est pas abonné à `/cmd_vel`, et seul `g1_jumeau` publie `/g1_jumeau/cmd_vel` ;
    - Nav2 → pont → faux G1 → Gazebo : avec `g1-guide aller hall_sud`, le robot proxy avance d'au moins 1 m et arrive à moins de 0,3 m. Les requêtes de `/api/sport/request` ont l'api_id 7105, un `parameter` `{velocity: [3 nombres], duration: 0,5}` et des `identity.id` croissants. Il en part au moins 8 par seconde en marche, et chacune a sa réponse ;
    - un `/cmd_vel` du test à vx 0,3 pendant 3 s fait 0,9 ± 0,2 m. Quand il cesse, le robot est arrêté (moins de 0,02 m/s) moins de 0,6 s après le dernier `/cmd_vel`, et un 7105 `[0, 0, 0]` est parti ;
    - la consigne (1,0 ; 0,6 ; 2,0) donne des requêtes plafonnées à (0,4 ; 0,25 ; 0,6) et une vitesse mesurée de 0,42 m/s au plus ; un NaN donne un arrêt ;
    - `/guide/stop` en marche : arrêt en moins de 0,3 s, et `/cmd_vel` ignoré pendant 1 s ;
    - `/pont/arret` true : arrêt en moins de 0,3 s, puis immobile pendant 3 s malgré `/cmd_vel`. Avec false, la marche ne reprend qu'au `/cmd_vel` suivant ;
    - `/pont/etat` reste conforme au schéma tout du long.
18. **Repérage** (`critere_18_reperage.sh`, agent Repérage). Répétition sur une copie du demo : Gazebo `--jumeau`, `g1-slam faux-service --jumeau`, navigation `--simu --localisation unitree`, `g1-atelier`. On vérifie :
    - avant le repérage : `GET /api/robot/etat` dit non repéré, il n'y a pas de TF map → odom, et `POST /api/guide/aller` répond 409 ;
    - `POST /api/robot/reperer {lieu, etage}` (marque au sol = départ du robot, (2,5 ; 10 ; 0)) répond en moins de 20 s, et le robot est repéré. Le faux service a reçu 1804 avec la pose (0, 0, 0) du repère d'Unitree et une `address` en `repetition.pcd`. Le TF map → base_link est à moins de 0,1 m et 0,05 rad de la vérité, et `precision_m` est renseignée ;
    - le robot avance de 2 m et tourne de 90° (par `/cmd_vel`, donc par le pont). map → base_link reste à moins de 0,1 m de la vérité, alors que l'odométrie dérive : map → odom a changé de plus de 2 cm ;
    - variante B, avec `repere_unitree: {x: 3.0, y: 9.0, theta: 0.5}` dans la copie. Le repérage à la marque est refusé (502, message en français) et map → odom n'est pas publié. Le repérage à x 2,5, y 10, cap 0 réussit : 1804 arrive avec la pose convertie (`carte_vers_unitree`), et map → base_link est à moins de 0,1 m ;
    - relocalisation coupée (`/faux_slam/panne` muet) : `perdu` en moins de 4 s, puis `repere` quand elle reprend ;
    - `/reperage/etat` reste conforme au schéma, et aucun processus ne reste.
19. **Niveau 2 complet en répétition, depuis l'Atelier** (`critere_19_niveau2.sh`, agent Repérage) :
    - `g1-atelier`, puis `POST /api/simulation/demarrer {lieu, etage, mode: "repetition"}`, et attente de Nav2 ;
    - « Y aller » avant le repérage répond 409. Puis `POST /api/robot/reperer` ;
    - `POST /api/guide/aller {cible: "b204"}` donne `arrive`, le robot à moins de 0,3 m de b204 (vérité), en moins de 180 s. Tout le mouvement passe par le pont et le faux G1 : les requêtes 7105 sont comptées, et rien dans Gazebo n'est abonné à `/cmd_vel` ;
    - une boîte dans le couloir nord (comme au critère 5), puis `POST /api/guide/aller {cible: "accueil"}` : `bloque → detour → arrive` à moins de 0,3 m ;
    - `POST /api/simulation/arreter` : plus aucun processus ne reste ;
    - avec `E2E_CONTENEUR=1`, la navigation tourne dans le conteneur (`g1-jetson demarrer --local`, `G1_SIMU=true`).
20. **Sécurité** (`critere_20_securite.sh`, agent Pont et faux G1). Chaîne de répétition réelle, avec le relais et le faux slam_operate de l'agent Repérage. Un témoin compare en continu la vérité terrain aux mouvements permis : aucun déplacement de plus de 5 cm hors d'une consigne permise. Cas :
    - pont sans repérage : un `/cmd_vel` de 2 s laisse le robot immobile, en `attente_reperage`, sans aucun 7105 non nul ;
    - guide avant le repérage : `echec` avec message, robot immobile ;
    - faux G1 muet pendant la marche (`/g1_jumeau/panne` muet) : arrêt en moins de 0,6 s et `robot_muet` en moins de 1,5 s ; au retour, pas de reprise sans `/cmd_vel` frais ;
    - faux G1 arrêté par SIGTERM : arrêt en moins de 0,6 s ; une fois relancé, le robot reste immobile ;
    - pont tué par SIGKILL pendant la marche : arrêt en moins de 0,6 s (durée de la consigne) ;
    - relocalisation perdue pendant la marche : `perdu`, puis robot arrêté en moins de 4 s ;
    - arrêt : `POST /api/guide/stop` arrête le robot en moins de 0,3 s ; avec `POST /api/robot/arret {verrou: true}`, il reste immobile 5 s, même avec « Y aller » ;
    - consignes absurdes (NaN, 1e9) : jamais au-delà des plafonds ;
    - messages en français, jamais d'erreur 500.

Critères 21 à 30 (vague 4 : point principal, passants, comportement du guide, pilotage, équipe ; section 11), ci-dessous ; `tests_e2e/tout.sh` lance les trente et affiche « N / 30 » (« N / 36 » depuis la vague 5 : critères 31 à 36 en 12.10). Un critère dont la pièce d'un autre agent manque répond « en attente » (77). Mesures dans le lieu `demo` (couloirs nord et sud de 2,85 m libres), sur des copies ; vérité terrain : `/odom` en simulation, `/g1_jumeau/odom` en répétition.

21. **Point principal** (`critere_21_point_principal.sh`, agent Point principal). Sur des copies du demo :
    - un lieu sans principal (ni étiquette ni salle `accueil`) : `g1-lieu valider` en erreur (« pas de point principal ») et `POST /api/simulation/demarrer` répond 409 ; deux principaux : `PUT …/salles` répond 422 ; un lieu migré dont `PUT …/salles` perdrait le principal : 422 ;
    - `g1-lieu migrer` : la sauvegarde contient les fichiers d'avant à l'identique, l'étiquette est posée, `g1-lieu valider` ne signale aucune erreur, un second passage ne change rien ; `g1-lieu migrer --lieu demo` (la référence) est refusé, `lieux/demo` inchangé (empreintes) ;
    - `PUT /api/lieux/{id}/principal {theta: 1.5708}` : `salles.yaml`, `accueil` de `lieu.yaml` et `depart_robot` valent 1,5708, et `GET …/principal` le rend ; puis le principal déplacé en (2,5 ; 11,0 ; 1,5708) ;
    - la simulation part du principal : après `POST /api/simulation/demarrer` (simu), la première pose de `/odom` est à moins de 0,05 m et 0,05 rad du principal ;
    - le repérage part du principal : en répétition, `POST /api/robot/reperer {lieu, etage}` sans pose → `/reperage/demander` porte x, y et theta du principal, le faux service reçoit 1804 avec `carte_vers_unitree(principal, repere_unitree)`, le robot est repéré, TF map → base_link à moins de 0,1 m de la vérité ; de même avec `repere_unitree` (3 ; 9 ; 0,5) dans la copie (pose convertie, repéré).
22. **Retour automatique** (`critere_22_retour.sh`, agent Comportement du guide). Simulation d'une copie du demo (`guide: {delai_avant_retour_s: 5}`) :
    - `POST /api/guide/aller {cible: "b204"}` → `arrive` à moins de 0,3 m ;
    - puis, seul, `retour` (cible : le principal) et `attente` en moins de 120 s, le robot à moins de 0,3 m et 10° du principal ;
    - événements `arrivee`, `retour` et `retour_arrive` reçus sur `/guide/evenement`, en français, conformes au schéma ; tous les `/guide/etat` conformes au schéma `etat_guide` ;
    - avec `{"cible": "b204", "retour": false}`, le robot reste à b204 (moins de 0,1 m en 20 s après l'arrivée).
23. **Passant immobile au milieu du couloir** (`critere_23_passant_immobile.sh`, agent Passants). Scène `immobile_couloir`, 5 essais accueil → b204 : 5 arrivées à moins de 0,3 m en moins de 180 s, sans détour, 0 contact, et sur chaque essai une distance bord à bord minimale de **0,20 m** au moins (0,71 m de centre à centre ; il reste 1,18 m libre de chaque côté du passant).
24. **Passants en face et qui coupent la route** (`critere_24_passants_croises.sh`, agent Passants). Scènes `en_face` et `coupe_route`, piétons en pire cas (`reaction: aucune`), 5 essais chacune : **0 contact causé par le robot** sur les 10 essais, au moins 9 arrivées sur 10 à moins de 0,3 m en moins de 180 s ; les contacts causés par le piéton sont comptés et affichés. Puis les mêmes scènes avec `reaction: ecart` : 0 contact de toute sorte.
25. **Groupe qui bouche le couloir** (`critere_25_groupe.sh`, agent Passants, avec le guide de l'agent Comportement) :
    - scène `groupe_couloir` (3 essais, le groupe part après 15 s) : le guide passe par `attente_passage` (événement `passant_gene`), aucun `detour` tant que le groupe est là, puis il passe et arrive à moins de 0,3 m en moins de 180 s, 0 contact causé par le robot ;
    - scène `groupe_reste` (2 essais, le groupe reste) : `attente_passage`, puis `detour` au plus tôt 20 s après (`delai_passant_s`), arrivée par le couloir sud en moins de 300 s, `longueur_m` au plus 75 m (un détour raisonnable) ;
    - banc `foule` (les 5 piétons du critère 6, piétons crédibles, 20 trajets) avec la nouvelle mesure : au moins 90 % de réussite et **0 contact causé par le robot** ; le CSV a les colonnes de 11.3.
26. **Accompagnement** (`critere_26_accompagnement.sh`, agent Comportement du guide). Simulation, scène `accompagnement` (faux visiteur 1 m derrière le robot au principal, `delai_visiteur_s: 10`), `/guide/aller {"cible": "b204", "accompagner": true}` :
    - événement `depart` (et non `seul`) ; visiteur `suivre` : le robot va à sa vitesse normale ;
    - `trainer` : `/speed_limit` publié, vitesse du robot au plus 60 % de celle d'avant, puis `attente_visiteur` (robot à moins de 2 cm/s) quand le visiteur est à plus de 3,5 m ;
    - `suivre` de nouveau : `visiteur_retrouve`, reprise, `arrive` à moins de 0,3 m ;
    - second essai, `partir` : `attente_visiteur`, puis `visiteur_perdu` 10 s après (± 2 s), puis `retour` et `attente` au principal (0,3 m, 10°) ; événements en français, conformes.
27. **Perdu en route** (`critere_27_perdu.sh`, agent Comportement du guide). Répétition d'une copie du demo (`guide: {delai_perdu_s: 15}`), repérage, `/guide/aller b204`, puis `/faux_slam/panne muet` en route :
    - `perdu` en moins de 4 s, événement `perdu`, robot arrêté (moins de 5 cm en 3 s) ;
    - cas A, panne levée après 5 s : `retrouve`, reprise, `arrive` à moins de 0,3 m ;
    - cas B, la panne reste : `echec` 15 s (± 2 s) après `perdu`, avec un message qui dit quoi faire, événement `echec`, robot immobile, pas de retour automatique.
28. **Pilotage contre le faux G1** (`critere_28_pilotage.sh`, agent Pilotage et danses). Gazebo `--jumeau`, nœud pilotage sur le PC (port libre, jeton), `g1-atelier`, navigation de la répétition :
    - postures 500, 706 et 3 acceptées (mode du faux G1 changé, lu par 7001) ; 1 et 0 refusées sans la confirmation double et la case « robot au portique », acceptées avec ;
    - joystick par le WebSocket de l'Atelier : vx 0,3 pendant 2 s → 0,6 ± 0,2 m ; robot arrêté (moins de 2 cm/s) moins de 0,6 s après le dernier ordre ; WebSocket coupé en marche : arrêt en moins de 0,6 s ; plafonds (1,0 demandé → 0,4) ;
    - gestes : 26 accepté ; un autre geste pendant que les bras tiennent → refus 7401 en français ; 99 relâche ; geste en posture assise → refus 7404 en français ;
    - voix (TTS), volume et LED reçus par le faux G1 avec les bons paramètres ;
    - verrou : guide en route → « prendre la main » refusé (409) ; avec `forcer` → `/guide/stop`, robot arrêté, `maitre: pilotage` ; `/guide/aller` alors refusé (`echec`, événement `pilotage`), pont en état `pilotage`, robot immobile ; « rendre la main » → le guide repart à la demande suivante ; ARRÊT permis dans tous les cas ;
    - interdits : 7104, 7110, postures 2, 4 et 801 refusées (403), sans aucune requête au faux G1 ; demandes absurdes : jamais d'erreur 500, refus en français ; aucun processus restant.
29. **Danses et chorégraphies** (`critere_29_danses.sh`, agent Pilotage et danses). Même montage :
    - la liste des danses est lue (7100) et montrée, 401, 402 et 403 marquées interdites ;
    - danse 604 avec la « zone libre » confirmée → le faux G1 reçoit 7101 `{"data": 550604}` ; sans confirmation : refus ; 401, 402 et 403 refusées même confirmées, rien d'envoyé ; pendant la danse, joystick refusé ; à la fin, mode 801 ; ARRÊT pendant une danse : StopMove, rien d'autre ;
    - la chorégraphie `exemple_kpop` jouée sur le faux G1 (zone libre confirmée) : rt/arm_sdk reçu à 50 Hz (± 10 %), rampes du poids de 1 s au moins au début et à la fin, aucun angle hors de `LIMITES_BRAS`, aucune vitesse au-delà de `VITESSE_BRAS_MAX`, taille et jambes jamais pilotées, pas sous `LIMITES_PAS` et robot à 1 m au plus de son départ (vérité), LED et paroles à leur temps (± 0,2 s) ; ARRÊT au milieu : poids ramené à 0 en moins de 1,5 s, StopMove ;
    - une chorégraphie hors limites est refusée avant de jouer, avec ses erreurs en français ;
    - l'onglet Pilotage dans Firefox sans fenêtre : l'aperçu 3D de `exemple_kpop` se charge et avance (images dessinées), sans erreur dans la page.
30. **Équipe** (`critere_30_equipe.sh`, agent Équipe) :
    - les exemples de `personnalites.yaml`, `dialogues.yaml` et `camera.yaml` sont valides, trois fautes de chacun sont refusées en français ; écrits puis relus par l'API sur une copie du demo ;
    - les onglets Personnalités, Dialogues et Caméra s'ouvrent dans Firefox sans fenêtre ; une personnalité choisie part sur `/personnalite/active` ; une phrase s'essaie dans l'onglet Dialogues ;
    - bout en bout en simulation (Gazebo, navigation, nœud `dialogue`) : « je cherche la salle b204 » sur `/visiteur/texte` → `/robot/dire` (réponse en français, conforme) et `/guide/aller` en JSON vers b204 → `arrive` à moins de 0,3 m ; « bonjour » → une réponse, sans guidage ; une phrase inconnue → le `repli` ; aucun processus restant.

---

## 8. Après ce plan, avec le robot

1. **Avec `g1-slam` sans `--faux`** :
   - vérifier un par un les formats de 1801, 1802, 1804 et 1102 ;
   - corriger `slam_client.py` et noter les vrais formats dans ce document.
2. **Scanner le vrai étage** : `source_carte: scan` dans `lieu.yaml`, puis `g1-carte-3d` et `g1-carte-2d`. Le reste du logiciel ne change pas.
3. **Placer les salles en vrai** : amener le robot devant chaque porte, puis `g1-salle ajouter`.
4. **Pont et relais** sur le Jetson, dans le conteneur Humble : `/cmd_vel` → `/api/sport/request` (7105), et le relais de la relocalisation vers `/odom` et TF. Préparés sans robot en vague 3 (section 10), avec la liste de la séance de vérification en 10.9.
5. **Recette en vrai** : niveau 1 (MoteurUnitree), puis niveau 2 (MoteurNav2), avec des volontaires et le même `g1-banc`.

---

## 9. Scan intégré (vague 2)

Contrats figés par l'intégrateur le 25/10/2026, avant le travail en parallèle de quatre agents (9.9), puis complétés à l'assemblage du même jour (paragraphes « Précisions de l'assemblage » de 9.5 à 9.10). Comme la section 4, cette section fait foi ; on ne la modifie qu'en passant par l'intégrateur. Le code partagé est déjà livré et testé : `atelier.lieu.scans` (sessions, reconnaissance, monde tiré du scan, état du scan), les schémas `session_scan` et `reconnaissance`, les champs facultatifs des objets du monde, et `atelier/tests/outils_scan.py` (sessions d'exemple, sans ROS).

> **Vague 5 (section 12.5) : la reconnaissance est retirée.** Tout ce qui, dans cette section, parle de la reconnaissance (9.3, 9.4, 9.6, 9.8, la revue de 9.1 et 9.7, l'étape `reconnaissance` et `monde` de 9.2 et 9.5, les critères 12 et 13 de 9.10) est historique : la chaîne est maintenant `carte_3d` → `carte_2d` → `nuage`, l'adoption copie la carte telle quelle et le monde d'un étage scanné est la carte extrudée en un seul maillage (`carte_extrudee`). L'onglet Scan est devenu Réel › Scanner (12.2), et les critères 12 et 13 ont été réécrits (`critere_12_carte_du_scan.sh`, `critere_13_monde_du_scan.sh`). Les champs `categorie`, `source` et `confiance` restent acceptés dans `monde.yaml` (anciens lieux).

### 9.1 Le but et le déroulé

Dans l'onglet **Scan** de l'Atelier :

1. On choisit le mode : **robot** (le vrai G1, avec sa cartographie Unitree) ou **simu** (le robot proxy de Gazebo scanne le monde de l'étage). En mode robot, la case **Répétition** permet de tout essayer sans robot.
2. Le bouton **« Scan »** lance la cartographie. Un **aperçu en direct** montre la carte qui se construit, la trajectoire et la position du robot. En simu, on pilote le robot avec les flèches, ou on coche **Explorer** et il parcourt seul les couloirs.
3. Le bouton **« Fin »** arrête le scan. La suite est automatique : carte 3D, carte 2D, reconnaissance des murs, des passages et des objets, puis un monde au format `monde.yaml`. Une barre de progression suit les étapes.
4. On relit ce qui a été reconnu : chaque élément a une case **à garder**. Les personnes sont décochées d'office.
5. **« Adopter »** : la carte du scan devient celle de l'étage ; avec le monde, le monde du scan remplace le monde dessiné, et se modifie dans l'éditeur et se simule dans Gazebo comme les autres.

```
Navigateur                     Serveur (atelier/serveur)           g1-scan (atelier/scan)
« Scan »   POST /api/scan/demarrer ──► g1-scan demarrer ──► crée scans/<session>/ et lance, détaché,
                                                            le processus de la session :
                                                              robot       : 1801, ros2 bag record /unitree/slam_mapping/*
                                                              répétition  : faux slam_operate + simulation + relais
                                                              simu        : simulation (si besoin), ros2 bag record /points /odom
                                                              tous        : apercu.png/json toutes les 2 s, session.json
aperçu     GET /api/scan/etat, /api/scan/apercu.png|json   (lus dans le dossier, par atelier.lieu)
flèches    POST /api/simulation/teleop ──► /cmd_vel (pont ROS 2 du serveur)
« Fin »    POST /api/scan/arreter ──► g1-scan arreter ──► SIGINT au processus : 1802, fermeture du bag,
                                                            puis traitement : carte_3d → carte_2d →
                                                            reconnaissance → monde → rapport.json
revue      GET/PUT /api/scan/sessions/{s}/reconnaissance  (atelier.lieu.changer_a_garder)
« Adopter » POST /api/scan/sessions/{s}/adopter ──► g1-scan adopter [--monde]
```

Tout ce que fait l'interface se fait aussi en ligne de commande avec `g1-scan`.

### 9.2 La session de scan

Chaque scan est une **session** : un dossier `LIEU/scans/AAAA-MM-JJ_HHhMM/`, nommé d'après l'heure locale du début (ex. `2026-10-25_17h42`). Si la minute est déjà prise : `-2`, `-3`… L'identifiant de session est validé partout (`atelier.lieu.verifier_id_session`) : un `{s}` d'URL ne peut pas sortir du dossier `scans/`.

| Fichier | Contenu | Écrit par |
|---|---|---|
| `enregistrement/` | ros2 bag du scan (ignoré par Git : `lieux/*/scans/*/enregistrement/`) | processus de la session |
| `session.json` | état de la session (schéma `session_scan.schema.json`) | `atelier.lieu` seulement (`creer_session`, `maj_session`) |
| `apercu.png`, `apercu.json` | vue de dessus en direct ; points décimés et trajectoire | processus de la session, toutes les 2 s au plus |
| `nuage.pcd` | nuage 3D assemblé, grille de 5 cm (`atelier.scan.carte3d`) | `g1-scan traiter` |
| `carte.pgm`, `carte.yaml` | carte 2D Nav2 (`atelier.scan.carte2d`), `image: carte.pgm` | `g1-scan traiter` |
| `reconnaissance.yaml` | murs, passages et objets reconnus (schéma `reconnaissance.schema.json`) | `reconnaitre`, puis `changer_a_garder` |
| `monde_scan.monde.yaml` | monde tiré des éléments gardés (schéma `monde.schema.json`) | `atelier.lieu.ecrire_monde_scan` |
| `rapport.json` | bilan du traitement | `g1-scan traiter` |
| `monde_remplace.monde.yaml` | ancien monde de l'étage, gardé à l'adoption avec `--monde` | `g1-scan adopter` |
| `.session.lock` | verrou des écritures de `session.json` (ignoré par Git) | `atelier.lieu` |
| `.processus.json` | programmes lancés par la session (pid, groupe, journal), pour nettoyer une session interrompue (ignoré par Git) | processus de la session |

Toutes les coordonnées d'une session sont dans le **repère du nuage** : l'odométrie de l'enregistrement. En simu, c'est le repère du monde Gazebo (la session se compare donc pixel à pixel au monde dessiné). Sur le vrai robot, c'est le repère de la carte Unitree, avec l'origine au départ du scan.

**session.json.** Tous les champs sont obligatoires, sauf les quatre derniers (null par défaut). Exemple complet : `EXEMPLE_SESSION` dans `atelier/tests/test_contrats_scan.py`.

| Champ | Valeurs |
|---|---|
| `version`, `id`, `lieu`, `etage`, `nom` | 1 ; id de la session ; nom du dossier du lieu ; id de l'étage ; nom affiché (« Scan rdc du 25/10/2026 à 17h42 » par défaut) |
| `mode`, `repetition`, `explorer` | `robot` ou `simu` ; répétition sans robot (mode robot seulement) ; exploration automatique (simu, ou robot en répétition) |
| `debut`, `fin`, `maj` | heures ISO 8601 locales avec décalage, à la seconde (`2026-10-25T17:42:05+01:00`) ; `fin` : null jusqu'à la fermeture de l'enregistrement ; `maj` : dernière écriture, au moins toutes les 5 s pendant l'enregistrement |
| `etat`, `etape`, `progression`, `message` | voir le tableau ci-dessous ; progression entière de 0 à 100 ; message en français pour l'utilisateur, qui dit quoi faire en cas d'échec |
| `sujets` | `{nuage, odom, autres}` : robot (répétition comprise) `/unitree/slam_mapping/points` et `/unitree/slam_mapping/odom` ; simu `/points` et `/odom` ; `autres` : `["/tf_static"]` |
| `statistiques` | `{duree_s, points, distance_m, nuages}` : durée de l'enregistrement, points reçus, distance parcourue (somme des déplacements de l'odométrie), nuages reçus |
| `processus` | `{pid, debut, hote}` du processus qui travaille pour la session (`atelier.lieu.infos_processus()`), ou null |
| `journal` | chemin du journal de ce processus, dans `~/robot-g1/journaux/` |
| `carte_unitree` | mode robot : nom du `.pcd` demandé par 1802, `<etage>_<session>.pcd` |
| `adoption` | `{quand, monde}` quand la session a été adoptée |

| État | Étapes | Progression | Qui l'écrit |
|---|---|---|---|
| `en_cours` | `preparation`, puis `enregistrement` | 0 | `creer_session`, puis le processus de la session |
| `arret_en_cours` | `arret` (1802, fermeture du bag, arrêt de ce qui a été lancé) | 5 | le processus de la session, dès qu'il reçoit l'arrêt |
| `traitement` | `carte_3d`, `carte_2d`, `reconnaissance`, `monde` | 10–50, 50–65, 65–90, 90–99 (`progression_etape(etape, fraction)`) | `g1-scan traiter` |
| `termine` | `fini` | 100 | `g1-scan traiter` |
| `echec` | l'étape où c'est arrivé | celle de l'étape | celui qui a échoué, ou `g1-scan arreter` pour une session interrompue |

Règles (vérifiées par `atelier.lieu` à chaque écriture, en plus du schéma) : l'étape va avec l'état ; `termine` ⇒ progression 100 ; `traitement` et `termine` ⇒ `fin` renseignée ; `en_cours` ⇒ `fin` null ; `fin` après `debut` ; `repetition` seulement en mode robot ; `explorer` seulement avec le robot simulé ; `carte_unitree` seulement en mode robot ; `adoption` seulement pour une session terminée.

- **Un seul scan actif par lieu** : `creer_session` refuse si une session du lieu est `en_cours`, `arret_en_cours` ou `traitement` et n'est pas interrompue.
- **Session interrompue** (`session_interrompue`) : active, mais son processus est mort (pid absent, ou repris par un autre processus : on compare l'instant de démarrage lu dans `/proc`), ou, sans processus noté, muette depuis 30 s. Elle ne bloque pas un nouveau scan. `g1-scan arreter` la termine (9.5).
- **Écritures** : toujours par `ecrire_session` ou `maj_session` (atomique, validée ; `maj_session` prend le verrou `fcntl` de la session pour le lire-modifier-écrire). Personne n'écrit `session.json` à la main.

**apercu.json** (au plus `APERCU_POINTS_MAX` = 20 000 points, `APERCU_TRAJECTOIRE_MAX` = 5 000 poses) :

```json
{"version": 1, "session": "2026-10-25_17h42", "maj": "2026-10-25T17:43:10+01:00", "repere": "odom",
 "resolution": 0.05, "bornes": {"xmin": -0.05, "ymin": -0.05, "xmax": 30.05, "ymax": 20.05},
 "largeur": 602, "hauteur": 402, "sol": 0.0,
 "points": [[12.31, 5.52, 1.04], ...], "trajectoire": [[2.5, 10.0, 0.0], ...],
 "robot": {"x": 7.1, "y": 7.0, "theta": 0.02},
 "statistiques": {"duree_s": 64.0, "points": 368640, "distance_m": 21.4, "nuages": 640}}
```

- `points` : `[x, y, z]` en mètres, arrondis au centimètre, décimés au hasard parmi les points de la tranche 0,1–1,5 m au-dessus du sol estimé (`sol`, null tant qu'il est inconnu). `trajectoire` : `[x, y, theta]`, un point au moins tous les 0,1 m. `robot` : dernière pose, ou null.
- `apercu.png` : vue de dessus, même convention qu'une carte (ligne 0 = y maximal), `largeur` × `hauteur` pixels de `resolution` mètres (0,05 m ; 0,1 m si un côté dépasse 2 000 pixels), posée sur `bornes`. Fond gris 205 (inconnu), obstacles vus en noir ; la trajectoire et le robot peuvent y être dessinés en couleur, mais l'interface les dessine aussi elle-même depuis `apercu.json`. Les deux fichiers sont réécrits ensemble, de façon atomique, toutes les 2 s au plus (`PERIODE_APERCU`).

**rapport.json** :

```json
{"version": 1, "session": "2026-10-25_17h42", "termine": "2026-10-25T17:58:02+01:00", "duree_traitement_s": 95.3,
 "etapes": [{"etape": "carte_3d", "ok": true, "duree_s": 61.2, "message": "..."}, ...],
 "nuage": {"fichier": "nuage.pcd", "points": 412345, "nuages": 6152, "retires_mobiles": 2310},
 "carte": {"fichier": "carte.yaml", "largeur": 602, "hauteur": 402, "resolution": 0.05, "occupes": 15234, "sol": 0.01},
 "reconnaissance": {"murs": 21, "murs_gardes": 20, "passages": 5, "passages_gardes": 5,
                    "objets": {"table": 1, "poteau": 2, "personne": 1}, "objets_gardes": {"table": 1, "poteau": 2}},
 "comparaison": {"reference": "cartes/rdc.yaml", "recouvrement": 0.987, "couverture": 0.66},
 "avertissements": ["..."]}
```

`reconnaissance` vaut `atelier.lieu.resume_reconnaissance(...)`, ou null si la reconnaissance a échoué. `comparaison` : `atelier.scan.carte2d.comparer_fichiers(carte de la session, carte de l'étage)` si l'étage a déjà une carte, sinon null.

### 9.3 reconnaissance.yaml et monde_scan.monde.yaml

```yaml
version: 1
session: "2026-10-25_17h42"          # ou null hors session
etage: rdc
emprise: {min: [0.0, 0.0], max: [30.0, 20.0]}     # contient tous les bouts, centres et depart_robot
depart_robot: {x: 2.5, y: 10.0, theta: 0.0}       # en général : la pose du robot au début du scan
sol: 0.01                                          # facultatif : hauteur du sol dans le nuage
parametres: {tranche: [0.1, 1.5]}                  # facultatif : paramètres utilisés (libres)
murs:
  - {id: mur_1, categorie: mur, de: [0.0, 5.5], a: [6.4, 5.5], epaisseur: 0.15, hauteur: 2.5, confiance: 0.95, a_garder: true}
  - {id: mur_2, categorie: mur, de: [7.6, 5.5], a: [14.4, 5.5], epaisseur: 0.15, hauteur: 2.5, confiance: 0.9, a_garder: true}
passages:
  - {id: passage_1, categorie: passage, de: [6.4, 5.5], a: [7.6, 5.5], murs: [mur_1, mur_2], confiance: 0.85, a_garder: true}
objets:
  - {id: table_1, categorie: table, forme: boite, centre: [29.2, 6.1], taille: [1.2, 0.8, 0.75], cap: 0.0, confiance: 0.7, a_garder: true}
  - {id: poteau_1, categorie: poteau, forme: cylindre, centre: [26.0, 10.0], rayon: 0.2, hauteur: 2.5, confiance: 0.92, a_garder: true}
  - {id: personne_1, categorie: personne, forme: cylindre, centre: [21.0, 16.5], rayon: 0.25, hauteur: 1.7, confiance: 0.6, a_garder: false}
```

- Chaque élément : `id` (identifiant du contrat 4.1, unique entre murs, passages et objets, ni `sol` ni `g1_proxy`), `categorie`, `confiance` de 0 à 1, `a_garder`, et un champ libre facultatif `infos` (nombre de points, hauteur mesurée…).
- Un mur : comme dans `monde.yaml` (`de`, `a`, `epaisseur` ≤ 1, `hauteur` ≤ 10), catégorie `mur`.
- Un passage : `de` et `a` sont les bouts des deux murs qui bordent le trou (à 0,15 m près), `murs` leurs deux ids ; catégorie `passage`.
- Un objet : sa **forme mesurée**, `boite` (`taille` [longueur le long du cap, largeur, hauteur] et `cap`) ou `cylindre` (`rayon`, `hauteur`) ; jamais `modele`. La catégorie dit ce que c'est.
- Lire, écrire, valider : `atelier.lieu.lire_reconnaissance`, `ecrire_reconnaissance` (validée, atomique), `valider_reconnaissance`. Squelette : `nouvelle_reconnaissance(etage, emprise, depart_robot, session, sol, parametres)`.

**Le monde tiré du scan** (`atelier.lieu.monde_depuis_reconnaissance`, écrit par `ecrire_monde_scan`) ne contient que ce qui est gardé :

| Élément reconnu | Dans `monde_scan.monde.yaml` |
|---|---|
| mur gardé | un mur, avec `source: scan` et sa `confiance` |
| mur non gardé | rien |
| passage gardé | rien : le trou entre les deux murs reste ouvert |
| passage non gardé | le trou est **bouché** : un mur de même id, de `de` à `a`, de l'épaisseur et de la hauteur du plus grand des deux murs |
| objet gardé | une `boite` ou un `cylindre` (sa forme mesurée), avec `categorie`, `source: scan` et `confiance` |
| personne gardée | un cylindre de catégorie `personne` : dans le monde Gazebo, jamais sur la carte 2D |
| objet non gardé | rien |

Pas de piéton ; `emprise` et `depart_robot` de la reconnaissance ; nombres arrondis au millimètre. Le monde obtenu est toujours valide si la reconnaissance l'est (test).

### 9.4 Catégories et règles

| Catégorie | Pour | Déduite d'un objet dessiné sans `categorie` |
|---|---|---|
| `mur` | murs (reconnaissance seulement) | — |
| `passage` | passages, les portes (reconnaissance seulement) | — |
| `table` | plateau sur pieds, vers 0,7–0,8 m | modèle `table` |
| `chaise` | assise vers 0,45 m, dossier vers 0,9 m | modèle `chaise` |
| `banc` | assise longue et basse | modèle `banc` |
| `poteau` | colonne mince et haute | `cylindre` |
| `meuble` | bloc plein : armoire, bureau plein, banque d'accueil | `boite` |
| `poubelle` | petit cylindre bas | modèle `poubelle` |
| `personne` | personne debout et immobile | — |
| `inconnu` | obstacle non classé | — |

Les catégories d'objets (`CATEGORIES_OBJETS`) sont les mêmes dans `monde.yaml` et dans `reconnaissance.yaml`. `Objet.categorie_effective` donne la catégorie écrite, sinon celle déduite de la forme.

Règles :
- **Une personne n'est jamais dessinée sur la carte 2D.** `atelier.monde.carte` ignore les objets de catégorie `personne` (`Objet.sur_la_carte`), `verifier_lieu` aussi ; à l'adoption, les pixels occupés d'une personne sont effacés de la carte du scan, même cochée. Dans la reconnaissance, `a_garder` vaut **faux par défaut** pour une personne (`a_garder_par_defaut`), vrai pour tout le reste.
- **Un passage est un trou de 0,7 à 1,6 m (bornes comprises) entre les bouts de deux murs alignés** (`PASSAGE_MIN`, `PASSAGE_MAX`, `est_passage`). Deux murs sont alignés si leurs directions diffèrent de 5° au plus, quel que soit leur sens, et si chaque bout de l'un est à 0,10 m au plus de la droite de l'autre (`murs_alignes`). Un trou de moins de 0,7 m n'est pas un passage (le robot n'y passe pas) : la reconnaissance réunit les deux murs en un seul. Un trou de plus de 1,6 m est une ouverture : deux murs, sans passage.
- **La carte reste celle du scan.** Décocher un mur ou un passage ne change que le monde. À l'adoption, seuls les objets retirés (décochés) et les personnes sont effacés de la carte (`carte_sans_elements_retires` : pixels occupés dont le centre est dans l'empreinte agrandie de 5 cm).
- **Champs facultatifs du monde** (schéma `monde`, rétrocompatible : un monde existant reste valide) : pour un objet, `categorie`, `source` (`dessin` par défaut, ou `scan`) et `confiance` (0 à 1) ; pour un mur, `source` et `confiance`. Les dataclasses `Mur` et `Objet` les portent (None : absent du fichier).

### 9.5 La commande g1-scan (agent Orchestrateur)

Alias `gl-scan`. Codes de sortie : 0 réussi, 1 échec (message en français qui dit quoi faire), 2 commande mal tapée. Sans `--session`, la session visée est la session active du lieu, sinon la plus récente.

| Commande | Rôle |
|---|---|
| `g1-scan demarrer --lieu L --etage E --mode robot\|simu [--repetition] [--explorer] [--nom N] [--json]` | crée la session et lance son processus, détaché ; **rend la main en moins de 3 s**. Dernière ligne : `session: <id>` ; avec `--json`, la sortie de `etat --json` |
| `g1-scan arreter --lieu L [--session S] [--sans-traitement] [--attendre]` | demande la fin du scan, attend la fermeture de l'enregistrement (30 s au plus), puis rend la main pendant que le traitement continue ; `--attendre` : jusqu'à `termine` (code 0) ou `echec` (code 1) |
| `g1-scan traiter --lieu L --session S` | carte 3D, carte 2D, reconnaissance, monde et rapport, au premier plan ; sert aussi à refaire le traitement d'une session finie |
| `g1-scan etat --lieu L [--session S] [--json]` | état lisible ; avec `--json`, seulement le JSON de `atelier.lieu.etat_scan` sur la sortie standard |
| `g1-scan adopter --lieu L --session S [--monde]` | la session devient la carte de l'étage ; avec `--monde`, son monde aussi |

**demarrer.** Avant de créer quoi que ce soit (sinon code 1) : le lieu et l'étage existent ; aucun scan actif dans le lieu ; en simu, `mondes/<etage>.sdf` existe (sinon : « g1-monde generer ») ; avec `--explorer`, l'étage a au moins deux nœuds reliés dans `itineraires.yaml`. Puis `creer_session`, lancement du processus de la session dans son propre groupe de processus, avec son journal `journaux/scan_<lieu>_<session>.log`, et `processus` et `journal` notés dans `session.json`. Le processus de la session :

- **robot** (vrai G1) : 1801 (`ClientSlam`, eno2, domaine 0, environnement de `setup/robot.sh`), puis `ros2 bag record -o enregistrement/` des sujets de `sujets` (+ `/tf_static`) sur le réseau du robot. Le PC suit le robot au câble.
- **robot + répétition** : faux service `slam_operate` sur lo (domaine `$ROS_DOMAIN_ID`) ; la simulation de l'étage (déjà lancée, ou lancée par lui) ; un relais qui republie `/points` et `/odom` sous `/unitree/slam_mapping/points` et `/unitree/slam_mapping/odom`, messages inchangés. Puis 1801 au faux service, et le même enregistrement que sur le robot.
- **simu** : la simulation de l'étage. Si `/odom` et `/points` sont déjà publiés dans le domaine (vérifié en 5 s au plus), il l'utilise telle quelle et ne l'arrêtera pas ; sinon il lance `g1-monde simuler --lieu L --etage E --sans-fenetre` et l'arrêtera à la fin. Puis l'enregistrement de `/points`, `/odom` et `/tf_static`.
- **explorer** (simu, ou robot en répétition) : le robot fait seul un tour qui passe par tous les couloirs de `itineraires.yaml` de l'étage, en ligne droite de nœud en nœud (`/cmd_vel`, `/odom`, 0,4 m/s au plus, arrêt devant un obstacle à moins de 0,6 m), en partant du nœud le plus proche et en y revenant. À la fin du tour, il s'arrête et **le scan se termine de lui-même**, comme avec « Fin ».
- **pendant l'enregistrement** : étape `enregistrement` ; `statistiques` et `maj` au moins toutes les 5 s ; `apercu.png` et `apercu.json` toutes les 2 s au plus, à partir des sujets écoutés directement (pas du bag en cours d'écriture).
- **à l'arrêt** (SIGINT ou SIGTERM reçu, ou fin de l'exploration) : `arret_en_cours`, vitesse nulle sur `/cmd_vel` en simu, 1802 avec `carte_unitree` (mode robot), fermeture propre du bag (`metadata.yaml` présent), arrêt de ce qu'il a lancé, `fin` ; puis le traitement, sauf avec `--sans-traitement` (état `traitement` → `termine`). Tout ce que la session a lancé s'arrête avec elle : aucun processus ne lui survit.

**arreter.** Envoie SIGINT au groupe du processus de la session (vérifié par `processus_vivant`). Si la session est interrompue (processus mort) : avec un enregistrement complet, il lance lui-même le traitement ; sinon il la passe en `echec` (« le scan s'est arrêté sans enregistrement : recommencez »). Sur une session déjà finie : code 0, rien à faire.

**traiter.** Refuse une session `en_cours` ou dont le traitement tourne encore, et une session déjà adoptée (« faites un nouveau scan »). Refaire le traitement d'une session finie remplace sa reconnaissance : les choix « à garder » faits à la main sont perdus. Étapes, avec la progression de 9.2 :
1. `carte_3d` : `atelier.scan.carte3d.fabriquer_pcd(enregistrement, nuage.pcd, sujets de la session)`. Le LiDAR du robot proxy est à 1,245 m : la position du capteur vient de `/tf_static` enregistré.
2. `carte_2d` : `atelier.scan.carte2d.fabriquer_carte_lieu(lieu, etage, pcd=nuage.pcd, sortie=carte.yaml)` (avec `sortie`, le lieu n'est pas touché). Emprise : celle du monde de l'étage en simu (comparaison pixel à pixel), celle du nuage en mode robot.
3. `reconnaissance` : `atelier.scan.reconnaissance.reconnaitre(nuage.pcd, carte.yaml, dossier de la session, parametres)` avec `parametres["depart_robot"]` = première pose de l'odométrie. **Un échec de la reconnaissance ne fait pas échouer la session** : elle se termine avec la carte 2D, un avertissement dans `rapport.json` et dans `message`, sans `reconnaissance.yaml` (adopter sans `--monde` reste possible).
4. `monde` : vérifie `monde_scan.monde.yaml` (schéma et règles), compare la carte à celle de l'étage s'il en a une, écrit `rapport.json`.
Un échec de `carte_3d` ou `carte_2d` donne `echec`, avec un message qui dit quoi faire.

**etat --json** : exactement `atelier.lieu.etat_scan(lieu, session)` :

```json
{"version": 1, "lieu": "demo", "dossier_lieu": "/home/joonho/robot-g1/lieux/demo", "sessions": 3, "actif": true,
 "session": {"...": "tous les champs de session.json",
             "dossier": "/home/joonho/robot-g1/lieux/demo/scans/2026-10-25_17h42",
             "vivant": true, "interrompue": false,
             "fichiers": {"enregistrement": false, "apercu_png": true, "apercu_json": true, "nuage": false,
                          "carte": false, "reconnaissance": false, "monde": false, "rapport": false}}}
```

`session` vaut null si le lieu n'a aucune session. `actif` : la session rendue est active et non interrompue. `vivant` : true, false, ou null si on ne peut pas savoir.

**adopter.** Session `termine` seulement. Écrit `cartes/<etage>.pgm` (la carte de la session passée par `carte_sans_elements_retires`) et `cartes/<etage>.yaml` (`image: <etage>.pgm`), copie `nuage.pcd` en `cartes/<etage>.pcd`, passe l'étage à `source_carte: scan` et, en mode robot, recopie `carte_unitree` dans `lieu.yaml`. Avec `--monde` : l'ancien `mondes/<etage>.monde.yaml` est gardé dans la session (`monde_remplace.monde.yaml`), puis remplacé par `monde_scan.monde.yaml`. Ensuite `atelier.monde.generer(lieu, etage)` : masque Keepout à la taille de la nouvelle carte et, avec `--monde`, le SDF du nouveau monde. Enfin `adoption` dans `session.json`, et le rapport de `valider_lieu` affiché. En mode robot, il prévient que le repère du scan n'est pas celui du monde dessiné : salles, nœuds et zones sont à replacer sur la nouvelle carte.

**Précisions de l'assemblage** (écarts acceptés, 25/10) :
- `demarrer --pilote direct|guide` (ou `G1_SCAN_PILOTE`) : exploration en ligne droite par `/cmd_vel` (défaut, ci-dessus) ou par le guide (`/guide/aller` de nœud en nœud ; `g1-guide navigation --simu` est lancé s'il ne tourne pas). Le tour suit chaque couloir au moins une fois (circuit du postier chinois) ; un couloir bloqué 30 s est abandonné.
- `arreter --sans-traitement` envoie SIGUSR1 (et non SIGINT) : la session reste `arret_en_cours` avec sa `fin` ; `g1-scan traiter` ou `arreter` la finit. `arreter` sans aucune session dans le lieu : code 0, « rien à arrêter ».
- En plus des fichiers de 9.2 : `.processus.json`, un journal par programme (`journaux/scan_<lieu>_<session>.<nom>.log`) et le champ `repere` de `rapport.json` (`{nuage, odom, robot, deja_dans_le_monde, capteur, premiere_pose}`) : si le `frame_id` du nuage est celui de l'odométrie (ou `odom`, `map`, `world`, `camera_init`), les points sont pris tels quels, sinon ils sont placés par l'odométrie et `/tf_static`.
- Mode robot : `sujets.autres` contient aussi `/state_estimator/odom_pelvis` et `/slam_info`. Sans câble, le message commence par « Robot non détecté », comme dans l'interface. Avec `G1_SLAM_FAUX=1` (essais), le vrai robot est toujours refusé.
- Position du LiDAR par défaut (`carte3d.CAPTEUR_DEFAUT`, `faux_slam`) : (−0,004 ; 0 ; 1,245) m, celle du `model.sdf` de `g1_proxy` ; `/tf_static` enregistré reste prioritaire.
- Variables : `G1_SCAN_BIN` (fausses commandes des tests), `ATELIER_RECONNAISSANCE=module:fonction` (fausse reconnaissance des tests), `G1_INTERFACE` (port du robot, eno2 par défaut), `G1_SCAN_PILOTE`.
- Tous les programmes de la session ont `OPENBLAS_NUM_THREADS=1` (sinon numpy occupe tous les cœurs en attente active, au détriment de Gazebo) et reçoivent SIGTERM si le processus de la session meurt.
- Un bag de simulation pèse environ 100 Mo par minute de scan (`/points` à 10 Hz) ; il reste dans `scans/<session>/enregistrement/`, ignoré par Git.

### 9.6 La reconnaissance (agent Reconnaissance)

```python
from atelier.scan.reconnaissance import reconnaitre
resultat = reconnaitre(chemin_pcd, chemin_carte_yaml, dossier_sortie, parametres=None)
```

- **Entrées** : le nuage `.pcd` de la session (repère de l'odométrie, déjà sans obstacles mobiles), la carte 2D `.yaml` de la session (son `.pgm` à côté), le dossier où écrire (le dossier de la session). `parametres` : dict facultatif ; clés reconnues au moins `depart_robot` (`(x, y, theta)`, par défaut un point libre de la carte près du centre de l'emprise), `session` (par défaut : le nom de `dossier_sortie` s'il a la forme d'une session, sinon null), `etage` (par défaut `"rdc"`), `sol` (par défaut : estimé) ; les autres clés sont des réglages propres à l'algorithme.
- **Sorties** : `dossier_sortie/reconnaissance.yaml` (par `atelier.lieu.ecrire_reconnaissance`) et `dossier_sortie/monde_scan.monde.yaml` (par `atelier.lieu.ecrire_monde_scan`). Rien d'autre n'est écrit dans le lieu.
- **Renvoie** `{"fichier": chemin de reconnaissance.yaml, "monde": chemin du monde, "resume": resume_reconnaissance(...), "duree_s": ..., "avertissements": [...]}`.
- **Erreurs** : `atelier.scan.reconnaissance.ErreurReconnaissance(Exception)`, message en français qui dit quoi faire ; jamais de fichier à moitié écrit.
- **Contraintes** : sans ROS ni écran ; Python du projet (numpy 1.26, Open3D, opencv-python ; autre paquet : demander à l'intégrateur) ; moins de 60 s sur un scan du lieu demo ; même résultat à chaque appel avec les mêmes entrées (graine fixe). Ids : `mur_N`, `passage_N`, et pour les objets `<categorie>_N` (ex. `table_1`, `personne_1`). Confiance : une estimation honnête entre 0 et 1 ; l'interface signale les éléments sous 0,5. Les règles de 9.4 s'appliquent (passages de 0,7 à 1,6 m, personnes décochées, trous de moins de 0,7 m bouchés).
- Une commande de mise au point est permise : `python -m atelier.scan.reconnaissance NUAGE.pcd CARTE.yaml DOSSIER`.

**Précisions de l'assemblage** : le sol et le plafond sont trouvés par un RANSAC numpy à graine fixe (celui d'Open3D, parallèle, ne rendait pas deux fois le même plan) ; Open3D sert au DBSCAN, aux voisinages et aux fichiers. `reconnaitre` accepte en plus `progression=` (fonction appelée avec la fraction et l'étape) et `depart_robot` en dict ; chaque élément a un champ `infos` (mesures, scores des catégories). Les 71 réglages sont dans `PARAMETRES` ; la commande de mise au point accepte `--depart X Y THETA` et `--parametre cle=valeur`. Durée sur le demo : 1 à 2 s.

### 9.7 L'API du serveur (agent Interface)

REST sous `/api/scan`, en JSON ; erreurs `{detail, erreurs?, sortie?}` en français, comme en 4.4. Le serveur lance `g1-scan` pour démarrer, arrêter et adopter (fausses commandes possibles dans les tests, `$ATELIER_BIN`), et lit directement les fichiers des sessions par `atelier.lieu` pour l'état, l'aperçu, la liste et la reconnaissance (pas de sous-processus à chaque interrogation).

| Route | Corps ou paramètres | Réponse |
|---|---|---|
| `POST /api/scan/demarrer` | `{lieu, etage, mode, repetition: false, explorer: false, nom?}` | l'état (format `etat --json`) ; 409 si un scan est actif, ou si la simulation de l'Atelier tourne sur un autre lieu ou étage (« arrêtez la simulation ») ; 503 sans `g1-scan` ; 502 si `g1-scan` échoue, avec sa `sortie` |
| `POST /api/scan/arreter` | `{lieu, session?}` | l'état, quand l'enregistrement est fermé (le traitement continue) |
| `GET /api/scan/etat` | `?lieu=L[&session=S]` | `atelier.lieu.etat_scan` ; sans `lieu` : le lieu du dernier scan démarré par le serveur, sinon 400. L'interface l'interroge chaque seconde |
| `GET /api/scan/apercu.png`, `GET /api/scan/apercu.json` | `?lieu=L[&session=S]` | les fichiers de la session (`Cache-Control: no-store`) ; 404 tant qu'ils n'existent pas |
| `GET /api/scan/sessions` | `?lieu=L` | liste de `lister_sessions(lieu, avec_illisibles=True)`, chaque session avec `fichiers`, la plus récente d'abord |
| `GET /api/scan/sessions/{s}/reconnaissance` | `?lieu=L` | `{reconnaissance, resume}` ; 404 si elle n'existe pas encore |
| `PUT /api/scan/sessions/{s}/reconnaissance` | `?lieu=L`, corps `{"a_garder": {"<id>": true\|false, ...}}` | `changer_a_garder` : `{reconnaissance, monde, resume}` ; 400 pour un id inconnu, 409 si la session n'est pas finie |
| `GET /api/scan/sessions/{s}/carte.png`, `…/carte.yaml`, `…/monde` | `?lieu=L` | la carte de la session (mêmes formats que la carte d'un étage en 4.4) et `monde_scan.monde.yaml` en JSON, pour la revue en 2D et en 3D |
| `POST /api/scan/sessions/{s}/adopter` | `?lieu=L`, corps `{monde: bool}` | `g1-scan adopter` : `{adopte: true, monde: bool, sortie}` ; 409 si la session n'est pas `termine` |
| `POST /api/simulation/teleop` | `{vx, vy, wz}` en m/s et rad/s | publie un `geometry_msgs/Twist` sur `/cmd_vel` par le pont ROS 2 : `{envoye: {vx, vy, wz}, ecoute: n}` |

- **Téléopération** : valeurs ramenées à |vx| ≤ 0,5, |vy| ≤ 0,25, |wz| ≤ 0,8. L'interface renvoie la consigne toutes les 0,2 s tant qu'une flèche est appuyée, puis `{0, 0, 0}`. **Homme mort** : sans consigne depuis 0,5 s, le serveur publie lui-même une vitesse nulle (VelocityControl garde la dernière consigne). Seulement avec le robot simulé : 409 si ni la simulation de l'Atelier ni un scan simu ou en répétition ne tourne ; 503 sans pont ROS 2.
- **Retirées** : `POST /api/scan/debut`, `POST /api/scan/fin` et `POST /api/scan/faux-service/arreter` (le faux service est maintenant lancé et arrêté par la session en répétition). `GET /api/scan/etat` change de format. `g1-slam` reste une commande à part entière.
- **Onglet Scan** : choix du mode, cases Répétition et Explorer, gros bouton « Scan », aperçu en direct sur la carte de l'étage (image `apercu.png` posée sur `bornes`, trajectoire, robot, durée, distance, points), flèches à l'écran et au clavier en simu, bouton « Fin », barre de progression avec le `message` de chaque étape, puis la revue (éléments par catégorie, cases à garder, confiance, éléments douteux signalés, carte de la session et vue 3D du monde) et les boutons « Adopter la carte » et « Adopter la carte et le monde ». Historique des sessions du lieu. En mode robot sans répétition, une confirmation rappelle le câble Ethernet.

**Précisions de l'assemblage** :
- Route ajoutée : `GET /api/scan/sessions/{s}/rapport` (`rapport.json`). Champs ajoutés aux réponses : `sortie` (demarrer, arreter), `interrompue` (chaque session listée), `session`, `etage`, `avertissements` et `rapport` (adopter), `avertissement` (teleop, quand personne n'écoute `/cmd_vel`).
- Le scan démarré par le serveur est un de ses processus (rôle « scan », dans « Ce qui tourne ») ; quand le serveur s'arrête, il demande la fin de l'enregistrement (`g1-scan arreter`).
- Mode robot sans répétition : le serveur lit seulement `/sys/class/net/<interface>/carrier` (`ATELIER_INTERFACE_ROBOT`, eno2 par défaut) ; sans câble, 409 « Robot non détecté : branchez le câble Ethernet… ». La téléopération est refusée avec le vrai robot (409) : il se pilote à la télécommande. Le 409 « simulation sur un autre lieu ou étage » vaut dans les deux modes.
- Les deux boutons d'adoption s'appellent « Utiliser cette carte pour l'étage » (Adopter la carte) et « Ouvrir dans l'éditeur du monde » (Adopter la carte et le monde, puis l'onglet Monde s'ouvre sur le monde du scan). Les deux demandent une confirmation qui dit ce qui sera remplacé.

### 9.8 Le lieu de référence et l'évaluation

**Lieu de référence : `lieux/demo`.** Son `mondes/rdc.monde.yaml` est la vérité terrain : chaque objet y a sa `categorie`, et chaque catégorie y est présente. Trois objets ont été ajoutés pour cela, placés hors du graphe et des trajets des piétons : `table_est` et `chaise_est` au bout est du couloir sud (vus de loin depuis le couloir : le rayon le plus bas du LiDAR, à −7° depuis 1,245 m, ne touche une table de 0,75 m qu'au-delà de 4 m), et `personne_b204`, une personne debout dans b204, vue par le passage (cylindre de 0,25 × 1,7 m, absent de la carte). Les objets dans les salles ne sont vus qu'en partie, par les passages.

| Catégorie | Objets du demo |
|---|---|
| table | `table_cdi`, `table_est` |
| chaise | `chaise_cdi_1`, `chaise_cdi_2`, `chaise_est` |
| banc, poubelle | `banc_hall`, `poubelle_hall` |
| poteau | `poteau_1`, `poteau_2` |
| meuble | `banque_accueil`, `bureau_amphi` |
| personne | `personne_b204` (debout) ; les piétons `pieton_sud` et `pieton_nord` marchent et sont retirés du nuage |
| passages | 5, de 1,2 m (`atelier.lieu.passages_du_monde`) |

La vérité terrain au format de la reconnaissance : `atelier.lieu.reconnaissance_depuis_monde(monde, "rdc")` (reconnaissance « parfaite »). L'évaluation compare les deux, élément par élément.

**Évaluation** (`atelier/scan/evaluation.py`, agent Testeur) : `evaluer(reconnaissance, monde_reference, info_carte, image_carte) -> dict`, et `python -m atelier.scan.evaluation --session DOSSIER --reference LIEU [--etage rdc]` qui affiche un bilan en français. Seul ce que le scan a **vu** compte dans les rappels : un pixel occupé de la carte de la session à 0,10 m au plus.

| Mesure | Définition | Objectif sur le demo (scan simu avec `--explorer`) |
|---|---|---|
| murs, rappel | part des points des murs vrais vus (un tous les 0,05 m) à 0,15 m au plus d'un mur gardé de même direction (10° près) | ≥ 0,90 |
| murs, précision | part des points des murs gardés à 0,15 m au plus d'un mur vrai | ≥ 0,90 |
| passages | un passage vrai, dont les deux bouts sont vus, est trouvé si un passage reconnu a son milieu à 0,30 m au plus et sa largeur à 0,30 m près ; rappel et précision | ≥ 0,8 chacun |
| objets, détection | objets vrais vus (au moins 3 pixels occupés dans l'empreinte agrandie de 0,10 m), appariés au plus proche reconnu, centres à 0,5 m au plus | ≥ 0,8 |
| objets, catégorie | part des appariés qui ont la bonne catégorie | ≥ 0,7 |
| faux objets | objets reconnus gardés, ni appariés ni à 0,3 m d'un mur vrai | ≤ 3 |
| personnes | `personne_b204` reconnue `personne`, avec `a_garder: false` ; aucun pixel occupé dans son empreinte après adoption | oui |

Ces objectifs sont ceux de la vague. Si une catégorie est hors de portée du LiDAR simulé, le Testeur le montre (chiffres à l'appui) et l'intégrateur ajuste l'objectif dans cette section.

**Précisions de l'assemblage** : `evaluation.py` a été écrit par l'agent Reconnaissance (et non par le Testeur), avec en plus des mesures plus strictes (murs retrouvés à 0,2 m et 5°, objets à 0,3 m avec la bonne catégorie), un mur « vu » à 0,10 m plus sa demi-épaisseur de son axe, et une personne vraie non vue qui fait échouer la mesure « personnes ». Il fabrique aussi des nuages synthétiques par lancer de rayons (`nuage_synthetique`). Tous les objectifs ont été atteints sur le scan simulé d'un tour complet (murs 99,5 % / 95,7 %, passages 5 sur 5, objets 11 sur 11 de la bonne catégorie, 1 faux objet, personne reconnue et décochée) : ils ne changent pas. Sur un scan arrêté à 80 % du tour, les passages sont juste à l'objectif (4 sur 5). La précision des murs (96–97 %) est limitée par des murs fantômes en diagonale, dus aux traînées de recalage pendant les rotations du robot proxy.

### 9.9 Les agents de la vague 2

| Agent | Possède | Dépend de |
|---|---|---|
| Intégrateur | sections 4 et 9, `atelier/lieu/` (dont les schémas), `atelier/tests/test_contrats*.py`, `test_lieu_scans.py`, `outils_scan.py`, `lieux/demo`, `.gitignore`, assemblage | — |
| A. Orchestrateur | `atelier/scan/` sauf `reconnaissance*` et `evaluation.py` (nouveaux modules du scan intégré `session.py`, `apercu.py`, `exploration.py`, `repetition.py`, et `carte3d`, `carte2d`, `faux_slam`, `slam_client`, `commande`), `bin/g1-scan`, `bin/gl-scan`, `atelier/tests/test_scan_session*.py` | contrats ; Reconnaissance (appel de `reconnaitre`) |
| B. Reconnaissance | `atelier/scan/reconnaissance.py` et `atelier/scan/evaluation.py`, `atelier/tests/test_reconnaissance*.py` | contrats |
| C. Interface | `atelier/serveur/`, `atelier/web/` (dont `js/ecrans/scan.js`, `js/teleop.js`, `js/nuage3d.js`, `css/scan.css`), `atelier/tests/test_serveur_*.py` | contrats ; `g1-scan` (fausses commandes en attendant) |
| D. Testeur | `tests_e2e/critere_11_*` à `critere_15_*`, `tests_e2e/outils_scan_e2e.py`, `tests_e2e/tout.sh` et `LISEZMOI.md` | tous |

Ce tableau donne les fichiers tels qu'ils ont été livrés (noms des tests et attribution d'`evaluation.py` corrigés à l'assemblage).

Règles communes : chaque agent n'écrit que dans ce qu'il possède et demande le reste à l'intégrateur ; `atelier/lieu` et les schémas ne changent que par l'intégrateur ; dans chaque shell ROS ou Gazebo, un `ROS_DOMAIN_ID` et une `IGN_PARTITION` propres à l'agent ; Gazebo sans fenêtre ; pas de compilation dans `ws/build` ; jamais rien sur eno2 (le vrai mode robot n'est essayé qu'en répétition) ; tous les processus lancés sont arrêtés à la fin (vérifier avec `ps`) ; tests réels, sans écran ni robot ; une section dans `docs/journal-atelier.md`. Pour travailler sans attendre les autres : `atelier.tests.outils_scan.creer_session_exemple(copie_du_lieu, etat)` crée une session complète et conforme (en_cours, traitement, termine ou echec), sans ROS.

**A. Orchestrateur.** 1) `g1-scan` et ses cinq sous-commandes (9.5), avec l'aide en français. 2) Le processus de la session : enregistrement, aperçu en direct, 1801 et 1802, répétition (faux service, simulation, relais), exploration. 3) Le traitement et l'adoption. 4) `carte3d` : position du LiDAR par défaut à mettre à jour (robot proxy : 1,245 m). Tests : cycle complet en simu sur une copie du demo (`demarrer --explorer`, puis `termine`), répétition du mode robot (1801 puis 1802 reçus par le faux service, sujets `/unitree/slam_mapping/*` enregistrés), `arreter` d'une session interrompue, `adopter` avec et sans `--monde` (lieu valide ensuite), aucun processus restant. En attendant la reconnaissance : une fausse `reconnaitre` dans les tests.

**B. Reconnaissance.** `reconnaitre` (9.6) : sol, tranche, murs (segments droits, épaisseur et hauteur), passages (9.4), objets (regroupement, forme mesurée, catégorie par la hauteur, la taille et le profil vertical), personnes, confiance. Tests : nuages synthétiques (une pièce, une porte de 0,9 m, un trou de 0,5 m, une table, une chaise, un poteau, une personne), puis un scan simulé du demo évalué avec l'évaluation du Testeur (objectifs de 9.8). Pour avoir un scan du demo avant `g1-scan` : l'enregistrement du critère 7 (`tests_e2e/critere_07_scan_simule.sh`), puis `g1-carte-3d` et `g1-carte-2d --sortie`.

**C. Interface.** Routes de 9.7, onglet Scan, téléopération (pont ROS 2 avec homme mort), revue et adoption ; mise à jour du parcours navigateur et de la liste de vérifications à la main. Tests : API avec de fausses commandes `g1-scan` et des sessions d'exemple ; téléopération avec un faux `/cmd_vel` (consignes ramenées aux limites, zéro après 0,5 s) ; syntaxe des modules JS ; parcours dans Firefox sans fenêtre si présent.

**D. Testeur.** `evaluation.py` (9.8 ; une reconnaissance parfaite donne 1 partout, une reconnaissance abîmée fait baisser la bonne mesure) ; critères de recette 11 à 15 (9.10) dans `tests_e2e/`, avec `tout.sh` qui affiche « N / 15 » ; vérifier que les critères 1 à 10 passent toujours.

### 9.10 Critères de recette de la vague 2, sans robot et sans fenêtre

Numérotation fixée à l'assemblage : celle des scripts `tests_e2e/critere_11_*` à `critere_15_*`, lancés par `tests_e2e/tout.sh`, qui affiche « N / 15 ». Elle remplace celle du premier jet de cette section (11 g1-scan, 12 répétition, 13 reconnaissance, 14 adoption, 15 interface) ; tout son contenu est couvert, comme indiqué entre parenthèses.

11. **Scan simulé intégré, par l'API** (`critere_11_scan_simu_api.sh`) : sur une copie du demo, `POST /api/scan/demarrer` en mode simu avec exploration rend la main en moins de 3 s ; l'aperçu (`apercu.json` et `.png`) se met à jour pendant le tour ; « Fin » (`POST /api/scan/arreter`) après 80 % des couloirs ; la session finit `termine` ; la carte de la session recouvre la carte du monde à au moins 90 % ; `reconnaissance.yaml` et `monde_scan.monde.yaml` sont valides ; aucun processus ne reste. Avec `E2E_FIN_AUTO=1`, pas de « Fin » : l'exploration termine le scan d'elle-même (premier jet, n° 11).
12. **Reconnaissance** (`critere_12_reconnaissance.sh`) : sur la session du critère 11 (sinon sur un nuage fabriqué), l'évaluation de 9.8 donne murs ≥ 0,90, passages ≥ 0,8, objets de la bonne catégorie ≥ 0,7, et aucune personne cochée ; les autres objectifs de 9.8 sont affichés, et bloquants avec `E2E_STRICT=1` (premier jet, n° 13).
13. **Monde du scan** (`critere_13_monde_du_scan.sh`) : dans la revue, un objet est décoché (`PUT …/reconnaissance`) ; « Adopter la carte et le monde » par l'API ; la carte de l'étage est celle de la session sans les éléments retirés, le masque a sa taille, `source_carte: scan`, l'ancien monde est dans la session, l'objet décoché n'est pas dans le monde adopté ; `g1-lieu valider` ne signale aucune erreur ; `g1-monde generer` ne touche pas à la carte du scan ; la simulation démarre sur le monde adopté, et le robot va de l'accueil à une salle placée par l'API, à moins de 0,3 m (premier jet, n° 14 et une partie du 15).
14. **Répétition du mode robot** (`critere_14_repetition_robot.sh`) : `g1-scan demarrer --mode robot --repetition --explorer` rend la main en moins de 3 s ; puis `g1-scan arreter --attendre` : le faux service a reçu 1801 puis 1802 (avec `carte_unitree`), le bag contient `/unitree/slam_mapping/points` et `/unitree/slam_mapping/odom`, la session finit `termine`, aucun processus ne reste (premier jet, n° 12).
15. **Robustesse et interface** (`critere_15_robustesse.sh`) : « Fin » sans scan, « Scan » deux fois, mode robot sans robot (« Robot non détecté »), demandes absurdes : refus clairs en français, jamais d'erreur 500 ; pendant un scan simulé, les flèches (`POST /api/simulation/teleop`) font avancer le robot, qui s'arrête seul quand on lâche ; « Fin » pendant la préparation ; puis le parcours de l'onglet Scan dans Firefox sans fenêtre (`atelier/tests/test_serveur_scan_navigateur.py`). Aucun processus ne reste (premier jet, n° 15).

Les critères 1 à 10 (section 7) doivent toujours passer.

---

## 10. Vrai robot : Jetson, pont, repérage

Contrats figés par l'intégrateur le 25/10/2026, avant le travail en parallèle de trois agents (10.10). Comme les sections 4 et 9, cette section fait foi ; on ne la modifie qu'en passant par l'intégrateur. But : préparer sans robot le passage au vrai G1, en trois pièces (le conteneur du Jetson, le pont vers la marche, le repérage au démarrage), et faire tourner le **niveau 2** (Nav2, pont, repérage d'Unitree) de bout en bout en **répétition**, contre un « faux G1 » dans Gazebo qui répond comme le vrai.

Code partagé déjà livré et testé (`atelier/tests/test_contrats_robot.py`) :
- `atelier.lieu.robot` : `repere_unitree(lieu, etage)`, `marque_au_sol(lieu, etage)`, `carte_pour_reperage(lieu, repetition)`, `pose_unitree_depuis_carte`, `pose_carte_depuis_unitree`, `valider_message(type, donnees)`, et les valeurs du contrat (`LIMITES_PONT`, `DUREE_CONSIGNE_S`, `DELAI_CMD_VEL_S`, `FREQUENCE_PONT_HZ`, `GARDE_APRES_STOP_S`, `CARTE_REPETITION`, `DELAI_REPERAGE_S`, `DELAI_PERDU_S`, `ECART_MAX_M`, `ECART_MAX_RAD`, `DERIVE_ECHELLE`, `DERIVE_LACET_PAR_M`, `ETATS_PONT`, `ETATS_REPERAGE`, `LOCALISATIONS`, `MODES_NAVIGATION`, exemples `EXEMPLE_ETAT_PONT`, `EXEMPLE_ETAT_REPERAGE`, `EXEMPLE_DEMANDE_REPERAGE`) ; tout s'importe depuis `atelier.lieu` ;
- `atelier.lieu.conversions` : `composer_poses`, `inverser_pose`, `unitree_vers_carte`, `carte_vers_unitree` (poses au sol) ;
- le champ facultatif `repere_unitree` d'un étage de `lieu.yaml` (schéma et dataclass `Etage`) ;
- les schémas `etat_pont`, `etat_reperage` et `demande_reperage` (messages JSON), reconnus par `valider_donnees` ;
- `tests_e2e/tout.sh` compte 20 critères (« N / 20 ») ; un critère sans script est « absent ».

### 10.1 Les trois modes et ce qui tourne où

| | simu (inchangé) | répétition (PC, sans robot) | robot |
|---|---|---|---|
| Robot | robot proxy de Gazebo | robot proxy de Gazebo, commandé par le faux G1 | le vrai G1 |
| Gazebo | `g1-monde simuler` | `g1-monde simuler --jumeau` (lance aussi `g1_jumeau`) | — |
| Service `sport` (marche, 7105) | — | `g1_jumeau` (10.4) | PC1 du robot |
| Service `slam_operate` (1804) | — | `g1-slam faux-service --jumeau` (10.6) | robot |
| Nav2, guide, relais, pont | `g1-guide navigation --simu` (sans relais ni pont) | `g1-guide navigation --simu --localisation unitree` sur l'hôte, ou le conteneur en local | conteneur `g1-jetson` sur le Jetson (au portique : aussi possible sur le PC au câble) |
| Atelier | PC | PC | PC, au câble (eno2) ; Wi-Fi en option (10.2) |
| Domaine DDS | `$ROS_DOMAIN_ID` | `$ROS_DOMAIN_ID` | 0 |
| Vitesse → robot | `/cmd_vel` → `ros_gz_bridge` → Gazebo | `/cmd_vel` → pont → `/api/sport/request` → `g1_jumeau` → `/g1_jumeau/cmd_vel` → Gazebo | `/cmd_vel` → pont → `/api/sport/request` → G1 |

En répétition et sur le robot, **aucune vitesse ne va directement à Gazebo** : tout passe par le pont et le service `sport` (vrai ou faux).

```
Nav2 : controller → velocity_smoother → collision_monitor ── /cmd_vel ──► pont_g1 (g1_bridge)
                                                                            │ ▲
     /reperage/etat (repéré ?), /guide/stop, /pont/arret ──────────────────►│ │ /api/sport/response
                                                    /api/sport/request 7105 ▼ │
                                                  service sport : vrai G1, ou g1_jumeau ──► /g1_jumeau/cmd_vel ──► Gazebo

Atelier « Repérer le robot » ── POST /api/robot/reperer ──► /reperage/demander ──► odom_vers_tf (g1_nav)
odom_vers_tf ── 1804 sur /api/slam_operate/request ──► slam_operate (vrai, ou faux_slam --jumeau)
slam_operate ── /unitree/slam_relocation/odom, /unitree/slam_relocation/points ──► odom_vers_tf
robot ── /state_estimator/odom_pelvis ──► odom_vers_tf ──► TF odom → base_link, /odom
odom_vers_tf ──► TF map → odom (correction), /points (repère lidar), /reperage/etat
```

### 10.2 Le conteneur du Jetson (agent Jetson)

**Choix validé : l'image officielle multi-architecture `ros:humble-ros-base-jammy`** (Ubuntu 22.04, amd64 et arm64/v8 ; vérifié le 25/10 avec `docker manifest inspect ros:humble-ros-base`). Raisons :
- le Jetson (L4T R35.3.1, noyau 5.10 aarch64, Docker 24.0.7) fait tourner n'importe quel espace utilisateur Ubuntu 22.04 arm64 ;
- Nav2, `rmw_cyclonedds_cpp` et `pointcloud_to_laserscan` existent en paquets apt arm64 pour Humble. L'image `dustynv/ros:humble-ros-base-l4t-r35.3.1` compile ROS depuis les sources, sans paquets apt ROS : il faudrait y compiler Nav2 (des heures, et sous émulation sur le PC) ;
- la navigation n'a pas besoin du GPU. La vision (YOLO) aura plus tard sa propre image L4T (dustynv), reliée par DDS ;
- un seul `Dockerfile` pour le PC (amd64, critère 16) et pour le Jetson (arm64). L'image arm64 se construit sur le PC par émulation (qemu et binfmt installés) avec le constructeur classique : `docker build --platform linux/arm64`. Essayé le 25/10 sur une petite image : `uname -m` donne `aarch64`. `buildx` n'est pas installé et n'est pas nécessaire.

**Image `g1-jetson:<arch>`** (étiquettes `amd64` et `arm64`) :
- base `ros:humble-ros-base-jammy` ; apt : `ros-humble-rmw-cyclonedds-cpp`, `ros-humble-navigation2` et `ros-humble-nav2-simple-commander`, `ros-humble-pointcloud-to-laserscan`, `python3-numpy`, `python3-yaml`, `iproute2`. Ni Gazebo, ni `ros_gz`, ni RViz, ni `g1_sim`, ni `g1_jumeau` ;
- compilés par colcon dans `/opt/g1/install` : **`unitree_api` seul** (depuis `third_party/unitree_ros2/cyclonedds_ws/src/unitree/unitree_api` : `unitree_go` et `unitree_hg` ne servent pas et rallongeraient beaucoup la construction sous émulation), `g1_nav`, `g1_bridge` ;
- Python : `atelier/__init__.py`, `atelier/lieu/`, `atelier/scan/__init__.py` et `atelier/scan/slam_client.py`, copiés dans `/opt/g1/python` (sur le `PYTHONPATH`). `atelier.lieu` n'a besoin que de numpy et PyYAML, et `slam_client` n'importe le SDK Unitree qu'à l'appel : le conteneur s'en passe ;
- `/opt/g1/VERSION` : date de construction et commit Git ;
- contexte de construction assemblé par `g1-jetson` dans un dossier temporaire : jamais tout le dépôt, car `.venv-projet` pèse plusieurs gigaoctets.

**Lancement** (fixé par `g1-jetson demarrer`) :

```
docker run -d --name g1-jetson --network host --init --restart no --stop-timeout 20 \
  --user <uid>:<gid> --cpus 4 --memory 4g \
  -e ROS_DOMAIN_ID=0 -e G1_INTERFACES=auto -e G1_LIEU=<id> -e G1_ETAGE=<etage> -e G1_LANCEMENT=navigation \
  -v ~/robot-g1/lieux:/lieux:ro -v ~/robot-g1/journaux/jetson:/journaux \
  g1-jetson:arm64
```

Réseau de l'hôte (DDS sans traduction d'adresses), aucun redémarrage automatique (on ne relance pas une navigation sans un humain), pas de `--privileged`, lieux en lecture seule. Essai sur le PC (`--local`) : image `amd64`, nom `g1-jetson-local` (`G1_JETSON_NOM` le change ; tests : `g1-jetson-e2e-<domaine>`), `ROS_DOMAIN_ID` du terminal, `G1_INTERFACES=defaut`, lieux de `$ATELIER_LIEUX`, journaux dans `~/robot-g1/journaux/jetson_local/`.

| Variable | Défaut | Rôle |
|---|---|---|
| `ROS_DOMAIN_ID` | 0 | le robot publie sur le domaine 0 |
| `RMW_IMPLEMENTATION` | `rmw_cyclonedds_cpp` | fixé dans l'image |
| `G1_INTERFACES` | `auto` | `auto` : l'interface qui a une adresse 192.168.123.x (réseau interne du robot), sinon le conteneur s'arrête (code 1, « réseau du robot introuvable ») ; `defaut` : pas de `CYCLONEDDS_URI`, CycloneDDS choisit comme l'hôte (essais sur le PC) ; sinon des noms séparés par des virgules |
| `G1_WIFI` | vide | option : interface Wi-Fi ajoutée pour joindre l'Atelier sans câble, multicast désactivé dessus |
| `G1_PAIRS` | vide | adresses unicast des pairs DDS sur le Wi-Fi (le PC de l'Atelier), séparées par des virgules ; avec des pairs, `MaxAutoParticipantIndex` vaut 100 (Nav2 lance une quinzaine de processus) |
| `G1_LANCEMENT` | `navigation` | `navigation` : `ros2 launch g1_nav navigation.launch.py lieu:=/lieux/$G1_LIEU etage:=$G1_ETAGE simu:=$G1_SIMU localisation:=$G1_LOCALISATION` ; `veille` : le nœud de présence seul ; `commande` : la commande donnée après le nom de l'image (mise au point) |
| `G1_LIEU`, `G1_ETAGE` | — | obligatoires avec `navigation` ; le lieu est un dossier de `/lieux` |
| `G1_LOCALISATION` | `unitree` | `unitree` ou `amcl` (`simu` est refusé dans le conteneur) |
| `G1_SIMU` | `false` | `true` : temps simulé, pour la répétition avec Gazebo sur l'hôte (critère 19 avec `E2E_CONTENEUR=1`) |
| `ATELIER_LIEUX` | `/lieux` | fixé dans l'image |
| `ROS_HOME`, `ROS_LOG_DIR` | `/journaux/ros`, `/journaux/ros/log` | journaux ROS dans le dossier monté |
| `CYCLONEDDS_URI` | généré | `file:///tmp/cyclonedds.xml`, écrit au démarrage depuis `cyclonedds.xml.modele` ; `G1_CYCLONEDDS_URI` le remplace tel quel |

**Démarrage** (`docker/demarrer.sh`, point d'entrée de l'image) :
1. il choisit les interfaces et écrit la configuration CycloneDDS ;
2. il charge `/opt/ros/humble` et `/opt/g1/install` ;
3. il écrit une ligne `g1-jetson : domaine N, interfaces …, lieu …, lancement …` ;
4. il lance toujours `docker/presence.py`, qui publie `/g1_jetson/etat` (std_msgs/String JSON, 1 Hz : `{version, image, arch, domaine, interfaces, lancement, lieu, etage, depuis_s}`) ;
5. il lance enfin ce que demande `G1_LANCEMENT`.

SIGTERM (`docker stop`) devient SIGINT pour `ros2 launch`, avec 15 s pour s'arrêter proprement (le pont envoie un arrêt en quittant).

**`bin/g1-jetson`** (alias `gl-jetson`). Codes de sortie : 0 réussi, 1 échec (message en français qui dit quoi faire), 2 commande mal tapée. Hôte par défaut : `unitree@192.168.123.164` (`G1_JETSON`). Avec `G1_SLAM_FAUX=1` (tous les tests), toute commande vers le Jetson (ssh, scp) est refusée.

| Commande | Rôle |
|---|---|
| `g1-jetson construire [--arch arm64\|amd64] [--sans-cache]` | construit `g1-jetson:<arch>` (`arm64` par défaut : par émulation, 4 min la première fois sur le PC du projet, 30 s ensuite ; `amd64` pour les essais sur le PC) |
| `g1-jetson envoyer` | robot : `docker save g1-jetson:arm64 \| gzip`, copie par scp, puis `docker load` sur le Jetson |
| `g1-jetson lieu --lieu L` | robot : copie le dossier du lieu, sans `scans/`, dans `~/robot-g1/lieux/<id>` du Jetson |
| `g1-jetson demarrer --lieu L --etage E [--local] [--localisation unitree\|amcl] [--veille] [--wifi IFACE --pair IP]` | lance le conteneur (sur le robot, le lieu est d'abord copié) ; rend la main quand il tourne (30 s au plus) |
| `g1-jetson arreter [--local]` | `docker stop` (arrêt propre), puis `docker rm` |
| `g1-jetson etat [--local] [--json]` | conteneur, image, lieu, interfaces, dernier `/g1_jetson/etat` ; code 0 s'il tourne, 1 sinon |
| `g1-jetson journal [--local] [-f]` | `docker logs` |
| `g1-jetson verifier` | robot : Docker, architecture, place libre, mémoire, interface 192.168.123.x, puis un conteneur en veille qui doit voir `/state_estimator/odom_pelvis` et `/lf/sportmodestate` |

Fichiers : `docker/Dockerfile`, `docker/demarrer.sh`, `docker/cyclonedds.xml.modele`, `docker/presence.py`, `docker/jetson.py` (le code de `g1-jetson`, Python du système, sans ROS), `docker/LISEZMOI.md`, `docker/tests/` (lancés par `.venv-projet/bin/python -m pytest docker/tests`), `bin/g1-jetson`, `bin/gl-jetson`. L'archive pour le Jetson est dans `~/robot-g1/opt/jetson/` (ignoré par Git).

### 10.3 Le pont (agent Pont et faux G1)

Paquet `ws/src/g1_bridge` (ament_python), exécutable `pont` (`g1_bridge.pont:main`), nœud `pont_g1`, réglages `config/pont.yaml` (installé dans `share/g1_bridge/config`). Dépendances : rclpy, geometry_msgs, std_msgs, unitree_api. Lancé par `navigation.launch.py` quand `pont` est vrai (10.7).

| Sujet | Type | Sens | Rôle |
|---|---|---|---|
| `/cmd_vel` | geometry_msgs/Twist | entrée | consigne de Nav2 (sortie du collision_monitor), ou de la téléopération en répétition |
| `/api/sport/request` | unitree_api/msg/Request | sortie | ordres 7105 (SetVelocity) |
| `/api/sport/response` | unitree_api/msg/Response | entrée | réponses, appariées par `header.identity.id` (les autres clients du robot y répondent aussi) |
| `/reperage/etat` | std_msgs/String (JSON, schéma `etat_reperage`) | entrée | `repere` : le mouvement n'est permis que si le robot est repéré |
| `/guide/stop` | std_msgs/Empty | entrée | arrêt immédiat, puis `/cmd_vel` ignoré 1 s |
| `/pont/arret` | std_msgs/Bool | entrée | `true` : arrêt verrouillé ; `false` : déverrouillé. QoS fiable, transient_local, profondeur 1, **pour l'abonné comme pour chaque publieur** : un publieur volatile ne serait pas entendu (règle DDS), et le verrou survit ainsi à un redémarrage du pont. En ligne de commande : `ros2 topic pub --once --qos-durability transient_local --qos-reliability reliable /pont/arret std_msgs/msg/Bool "{data: true}"` |
| `/pont/etat` | std_msgs/String (JSON, schéma `etat_pont`) | sortie | 2 Hz et à chaque changement d'état |

**La requête**, remplie exactement comme `LocoClient::SetVelocity` de `unitree_ros2` (`g1_loco_client.hpp`, `base_client.hpp`) et `LocoClient.SetVelocity` du SDK Python :
- `header.identity.id` : `time.monotonic_ns()` (l'équivalent de `GetSystemUptimeInNanoseconds`), strictement croissant ;
- `header.identity.api_id` : 7105 ; `header.lease.id` : 0 ; `header.policy.priority` : 0 ; `header.policy.noreply` : false ;
- `parameter` : `json.dumps({"velocity": [vx, vy, wz], "duration": d})`, en flottants. C'est le texte du SDK Python ; nlohmann (C++) trie les clés, mais les deux se lisent pareil ;
- `binary` : vide ; QoS des requêtes : fiable, volatile, profondeur 10 (l'exemple C++ utilise `QoS(1)`). Les réponses sont écoutées en best_effort, qui s'accorde avec un émetteur fiable comme best_effort. Même règle pour `/api/slam_operate/*` (10.5) ;
- **arrêt** : `{"velocity": [0.0, 0.0, 0.0], "duration": 1.0}`, c'est-à-dire `StopMove` du SDK.

**Règles** (valeurs de `atelier.lieu.robot`, reprises par `config/pont.yaml`) :
1. **Plafonds** : chaque composante est ramenée à |vx| ≤ 0,4 m/s, |vy| ≤ 0,25 m/s, |wz| ≤ 0,6 rad/s, avec son signe. Une valeur non finie (NaN, infini) fait de toute la consigne un arrêt. Les plafonds sont durs : le nœud refuse de démarrer avec un réglage plus haut.
2. **Consigne fraîche** (dernier `/cmd_vel` il y a moins de 0,3 s) : envoyée à 10 Hz avec `duration` 0,5 s. Une consigne nulle (toutes les composantes sous 1e-3) part au format de l'arrêt.
3. **Plus de `/cmd_vel` depuis 0,3 s** : un arrêt tout de suite, sans attendre le prochain envoi, puis plus rien. Au repos, le pont n'envoie rien en continu.
4. **`/guide/stop`** : arrêt immédiat ; `/cmd_vel` ignoré pendant 1 s (état `arret`).
5. **`/pont/arret` true** : arrêt immédiat, envoyé 3 fois en 0,2 s ; état `arret_verrouille` ; `/cmd_vel` ignoré jusqu'à `/pont/arret` false. Ensuite, le mouvement ne reprend qu'avec un `/cmd_vel` reçu après le déverrouillage. Le guide écoute aussi le verrou et annule lui-même son trajet : un but de Nav2 resté actif ferait repartir le robot au déverrouillage (correction du 01/11/2026, 12.15).
6. **Repérage exigé** (paramètre `exiger_reperage`, vrai par défaut) : le mouvement n'est permis que si le dernier `/reperage/etat` date de moins de 1 s et a `repere` vrai. Sinon `/cmd_vel` est ignoré, et un arrêt part si le robot bougeait. `exiger_reperage:=false` ne sert qu'aux essais au portique (10.9).
7. **Robot muet** : si les requêtes envoyées n'ont reçu aucune réponse depuis 1 s, l'état passe à `robot_muet`. Le pont continue d'envoyer la consigne fraîche ; le robot, lui, s'arrête seul à la fin de `duration`. On revient à la normale dès qu'une réponse arrive, et le mouvement ne reprend qu'avec un `/cmd_vel` frais.
8. **Refus** : si une réponse a `status.code` ≠ 0, l'état passe à `refus`, avec le code et un message, par exemple « Le robot refuse de marcher (code 7301) : mettez-le en mode marche avec la télécommande ».
9. **Au lancement** : un arrêt, qui vérifie le lien (état `demarrage` jusqu'à la réponse, `robot_muet` après 1 s sans réponse). **À la sortie** (Ctrl+C, SIGTERM) : un arrêt, envoyé avant de quitter. Précision de l'assemblage : un arrêt publié avant que DDS ait découvert le service `sport` serait perdu ; l'arrêt de vérification part donc dès qu'un abonné à `/api/sport/request` est vu (tout de suite s'il l'est déjà), puis encore 2 fois au plus à 0,3 s d'écart tant qu'aucune réponse n'arrive. Une nouvelle vérification se fait quand un nouvel abonné apparaît alors que le robot n'a jamais répondu ou est muet (service relancé). Rien de continu au repos. Relecture du 01/11/2026 (12.15) : un pont relancé suit tout `/cmd_vel` frais, même un flux qui courait avant son lancement (il ne peut pas les distinguer : la découverte DDS retarde le premier message) ; le guide annule donc son trajet dès que le pont se tait (`pont_absent`), et un `/cmd_vel` envoyé à la main doit être arrêté avant de relancer le pont (tutoriel de la séance 2, étape C4).
10. Tous les délais du pont comptent en temps mural monotone, jamais en temps simulé. Le pont ne publie jamais sur `/cmd_vel` ni sur un sujet de Gazebo.
11. **Vitesse minimale** (vague 5, 12.6 ; le 27/10, le vrai G1 ne faisait aucun pas à 0,1 m/s et marchait à 0,2) : si la norme de (vx, vy) atteint `vitesse_min_lin` (0,2 m/s) ou si |wz| atteint `vitesse_min_rot` (0,3 rad/s), la consigne passe telle quelle ; sinon toute la consigne est petite : sous les zones mortes (`zone_morte_lin` 0,05 m/s, `zone_morte_rot` 0,1 rad/s), zéro ; au-dessus, l'intention dominante est portée au minimum dans la même direction (marche à la norme minimale, ou rotation sur place à ± 0,3 rad/s), sans dépasser les plafonds. Algorithme de référence : `vitesse_effective` d'`atelier.lieu.robot` ; le pont en a une copie exacte (comparée sur 2 000 consignes au hasard). 0 désactive une règle (mesures au portique). Un réglage qui ne ferait faire aucun pas au robot (un plafond sous le minimum) arrête le nœud au lancement, avec un message qui dit quoi corriger. `/pont/etat` reçoit `demande` (la consigne après les plafonds, avant le minimum) et `minimums`.
12. **Mode du robot** (vague 5, 12.6) : le pont lit 7001 (`{}`, réponse `{"data": N}`) une fois par seconde ; ces lectures ne comptent ni dans `envoyees`, ni dans `reponses`, ni pour `robot_muet` et `refus`, et seules comptent les réponses qui portent nos `identity.id` (les autres programmes du robot inondent `/api/sport/response`). Un mode connu hors de `modes_marche` (500, 501, 801) donne l'état `pas_en_marche` (après `robot_muet` dans l'ordre des priorités) : arrêt si le robot bougeait, `/cmd_vel` ignoré, message en français (« le robot est assis… », « mode course : passez en marche normale à la télécommande », « le robot n'est pas démarré… ») ; au retour en marche, `pret`, et le mouvement ne reprend qu'avec un `/cmd_vel` neuf. Un mode inconnu (pas de `data`, lecture refusée, lu il y a plus de 3 s) ne bloque rien. Champ `mode_robot` de `/pont/etat` : `{fsm, nom, en_marche, age_s, modes_marche, lectures}`, ou null avec `lire_mode:=false`.

`config/pont.yaml` : `vx_max` 0,4, `vy_max` 0,25, `wz_max` 0,6, `duree_consigne` 0,5, `duree_arret` 1,0, `delai_cmd_vel` 0,3, `frequence` 10,0, `garde_stop` 1,0, `exiger_reperage` true, `delai_reperage` 1,0, `delai_muet` 1,0, `sujet_requete` `/api/sport/request`, `sujet_reponse` `/api/sport/response`. Un test vérifie qu'ils valent les constantes de `atelier.lieu.robot`. Les autres sujets du pont et du repérage (`/cmd_vel`, `/pont/etat`, `/reperage/*`, `/guide/*`) gardent la QoS par défaut de ROS 2 (fiable, volatile, profondeur 10).

### 10.4 Le faux G1, pour la répétition dans Gazebo (agent Pont et faux G1)

**`g1_sim` reçoit l'argument `jumeau:=true|false`** (défaut `false` : comportement actuel, octet pour octet). Avec `true`, le robot proxy n'est plus relié à `/cmd_vel`, `/odom` ni `/tf`, car sur le vrai robot ce sont le pont et le relais qui les tiennent. Un seul booléen plutôt qu'un nom de sujet de vitesse : l'odométrie, le TF et le nuage de Gazebo doivent changer de nom en même temps, sinon ils entreraient en conflit avec le relais (10.5).

| Sujet Gazebo | ROS 2, `jumeau:=false` | ROS 2, `jumeau:=true` (`config/pont_gz_jumeau.yaml`) |
|---|---|---|
| `/model/g1_proxy/cmd_vel` | `/cmd_vel` | `/g1_jumeau/cmd_vel` |
| `/model/g1_proxy/odometry` | `/odom` | `/g1_jumeau/odom` : la **vérité terrain** (repère du monde Gazebo = map) |
| `/model/g1_proxy/tf` | `/tf` (odom → base_link) | non relié |
| `/model/g1_proxy/lidar/points` | `/points` | `/g1_jumeau/points` (repère `lidar`) |
| `/clock` | `/clock` | `/clock` |

`robot_state_publisher` (base_link → lidar) tourne dans les deux cas. Avec `jumeau:=true`, `simulation.launch.py` lance aussi le nœud `g1_jumeau`. `g1-monde simuler … --jumeau` passe l'argument.

**Paquet `ws/src/g1_jumeau`** (ament_python), exécutable `jumeau` (`g1_jumeau.jumeau:main`), nœud `g1_jumeau` : le faux service `sport` du G1.

| Sujet | Type | Sens | Rôle |
|---|---|---|---|
| `/api/sport/request` | unitree_api/msg/Request | entrée | comme le vrai service |
| `/api/sport/response` | unitree_api/msg/Response | sortie | `header.identity` recopié de la requête (id, api_id), `status.code` 0, `data` vide. Api inconnue : 3203 ; paramètres illisibles : 3204 ; panne `refus` : 7301 |
| `/g1_jumeau/cmd_vel` | geometry_msgs/Twist | sortie | vers Gazebo, à 20 Hz, toujours : la consigne valide, sinon zéro |
| `/g1_jumeau/odom` | nav_msgs/Odometry | entrée | vérité terrain de Gazebo |
| `/state_estimator/odom_pelvis` | nav_msgs/Odometry | sortie | comme le vrai : au rythme de `/g1_jumeau/odom` (50 Hz), `frame_id` `odom`, `child_frame_id` `pelvis`, z 0,75 m. Origine : la pose du robot au lancement. **Dérive** : déplacements comptés 2 % trop longs, et 0,01 rad de lacet ajouté par mètre parcouru (`DERIVE_ECHELLE`, `DERIVE_LACET_PAR_M`). Vitesses (twist) dans le repère du robot, sans dérive |
| `/g1_jumeau/panne` | std_msgs/String (fiable, volatile) | entrée | `aucune` ; `muet` : ne répond plus et n'applique plus rien, comme un câble coupé (la consigne en cours expire normalement) ; `refus` : répond 7301 sans bouger |
| `/g1_jumeau/etat` | std_msgs/String (JSON) | sortie | 2 Hz, pour les tests : `{version, panne, consigne: {vx, vy, wz}, reste_s, requetes, appliquees}` |

- 7105 : `parameter` `{"velocity": [vx, vy, wz], "duration": d}`. La consigne est appliquée telle quelle jusqu'à t + d, en temps mural. Le faux G1 n'a pas de plafond à lui : le vrai robot a les siens, plus hauts que ceux du pont.
- **VelocityControl garde sa dernière consigne** : le faux G1 publie zéro à l'expiration, au lancement, en panne `muet` ou `refus`, et en quittant (SIGINT, SIGTERM). Un SIGKILL du faux G1 laisse la dernière consigne dans Gazebo : c'est une limite de la simulation (le vrai robot, lui, s'arrête seul), et le critère 20 ne tue donc le faux G1 que par SIGTERM.

### 10.5 Le repérage et les repères (agent Repérage)

**Les repères**, selon l'argument `localisation` de `navigation.launch.py` :

| Transformation ou sujet | `simu` | `unitree` (répétition et robot) | `amcl` (secours) | `externe` |
|---|---|---|---|---|
| map → odom | statique, identité | `odom_vers_tf` : correction issue de la relocalisation, à 20 Hz, seulement une fois repéré | `nav2_amcl` | un autre programme |
| odom → base_link | Gazebo | `odom_vers_tf`, depuis `/state_estimator/odom_pelvis` | `odom_vers_tf`, depuis `/state_estimator/odom_pelvis` | un autre programme |
| base_link → lidar | `g1_sim` | répétition : `g1_sim` ; robot : `navigation.launch.py`, statique (−0,004 ; 0 ; 1,245), sans rotation, à vérifier | idem | un autre programme |
| map → carte_unitree | — | `odom_vers_tf`, statique : `repere_unitree` (pour RViz) | — | — |
| `/odom` | Gazebo | `odom_vers_tf` (odom → base_link, twist de l'odométrie) | `odom_vers_tf` | un autre programme |
| `/points` (repère `lidar`) | Gazebo | `odom_vers_tf`, depuis `/unitree/slam_relocation/points` | répétition : `/g1_jumeau/points` recopié ; robot : à déterminer (10.9) | un autre programme |

**Le choix de l'odométrie locale et de la correction** (REP-105) : `odom → base_link` vient de `/state_estimator/odom_pelvis`, l'odométrie continue du robot (jambes et centrale inertielle), sans saut. MPPI et la carte des coûts locale, qui travaillent dans `odom`, restent donc lisses. La relocalisation d'Unitree, plus lente et qui peut sauter, ne corrige que `map → odom`. Si elle s'arrête, le repère local reste valable et le pont arrête le robot (`perdu`). Le relais de la vague 1, qui publiait `odom → base_link` directement depuis la relocalisation, est remplacé.

**Le repère d'Unitree** (`atelier.lieu.repere_unitree(lieu, etage)`, en-tête de `atelier/lieu/robot.py`) est la pose, dans le repère map de l'étage, de l'origine de la carte d'Unitree. Cette origine est le départ du scan ; c'est aussi **la marque au sol** où l'on pose le robot. On a `pose_map = repere ∘ pose_unitree`. Valeur :
- le champ `repere_unitree` de l'étage dans `lieu.yaml` s'il existe ;
- sinon (0, 0, 0) si `source_carte: scan` : la carte vient du scan, dans son repère ;
- sinon `depart_robot` du monde de l'étage. **C'est le décalage figé de la répétition** : il imite un scan commencé au départ du robot, là où le robot proxy apparaît dans Gazebo. Pour le demo : (2,5 ; 10 ; 0).

Le relais, le faux service et le serveur passent tous par cette fonction et par `atelier.lieu.conversions` : il n'y a qu'une façon de changer de repère. Le critère 18 essaie aussi un `repere_unitree` tourné (3 ; 9 ; 0,5). Adopter un scan du vrai robot (`g1-scan adopter`) laisse `repere_unitree` absent, donc l'identité (à vérifier en 10.9).

**`g1_nav/odom_vers_tf.py`**, nœud `odom_vers_tf` : relais de position et repérage. Le code de l'envoi de 1804 est dans le nouveau module `g1_nav/reperage.py`.
- **Entrées** (paramètres) : `relocalisation` (`/unitree/slam_relocation/odom`), `odometrie` (`/state_estimator/odom_pelvis`), `nuage` (`/unitree/slam_relocation/points`). Les trois sont écoutés en best_effort (`qos_profile_sensor_data`), qui s'accorde avec un émetteur fiable comme avec un best_effort. Autres paramètres : `localisation` (`unitree` ou `amcl`), `repere_unitree` (`[x, y, theta]`), `carte` (nom du .pcd pour 1804 : `carte_pour_reperage`), `lieu`, `etage`, `horodatage` (`local` par défaut, ou `message`), `points_repere` (`auto`, `carte` ou `capteur`), `pose_suivi` (`[x, y, theta]` du repère suivi par la relocalisation dans base_link, (0, 0, 0) par défaut), `pose_capteur` (pour `points_repere: capteur`), `z_carte_unitree` (hauteur de l'origine du repère d'Unitree au-dessus du sol, en mètres : 0 en répétition ; sur le robot, sans doute la hauteur du capteur au départ du scan, à vérifier).
- **Au sol** : chaque pose reçue est ramenée à x, y et un cap. Le cap est celui de l'axe x tourné, ce qui marche aussi avec un capteur monté à l'envers. z, le roulis et le tangage valent 0 (base_link est au sol).
- **Correction** : à chaque relocalisation R (instant t), `P_map = repere ∘ R ∘ inverse(pose_suivi)`. L'odométrie O de l'instant t est le message le plus proche dans un tampon de 2 s, ou le dernier si les horodatages ne se comparent pas. Puis `map → odom = P_map ∘ inverse(O)`, republié à 20 Hz. Une correction de plus de 0,5 m ou 0,3 rad compte comme un saut (`sauts`). Elle est appliquée quand même.
- **Horodatage `local`** : TF, `/odom` et `/points` portent l'heure du relais (`now()`, temps simulé en répétition), pour ne pas dépendre du décalage d'horloge entre le PC1 du robot et le Jetson. L'appariement relocalisation ↔ odométrie, lui, utilise les horodatages des messages, qui viennent tous deux du robot.
- **Nuage** : avec `points_repere: auto`, un nuage dont le `frame_id` est `map`, `odom`, `world`, `camera_init` ou celui de la relocalisation est dans le repère d'Unitree. Il est ramené dans `lidar` par `inverse(map → lidar) ∘ (map → carte_unitree)`, où map → carte_unitree vaut `repere_unitree` et la hauteur `z_carte_unitree`, et publié sur `/points` (best_effort, 10 Hz au plus), comme le nuage de Gazebo en simulation. Sinon (`capteur`), ses points sont placés par `pose_capteur` dans `lidar`.
- **`/reperage/etat`** (schéma `etat_reperage`, 5 Hz et à chaque changement) ; **`/reperage/demander`** (schéma `demande_reperage`).

**Le repérage** (localisation `unitree`), à chaque `/reperage/demander` `{id, x?, y?, theta?}` (une nouvelle demande remplace celle en cours) :
1. Pose annoncée P (repère map) : celle de la demande, sinon la marque au sol. Pose U = `carte_vers_unitree(P, repere)`. Sans carte, `echec` : « Ce lieu n'a pas de carte enregistrée sur le robot : faites d'abord un scan avec le robot (onglet Scan) ».
2. Envoi de 1804 **en ROS 2** sur `/api/slam_operate/request` : unitree_api/Request rempli comme le pont (identity, api_id 1804), `parameter` = `json.dumps(slam_client.parametres_relocaliser(U.x, U.y, U.theta, carte))`. Les formats non vérifiés restent dans `atelier/scan/slam_client.py`, et nulle part ailleurs.
3. Réponse attendue 10 s au plus sur `/api/slam_operate/response`, avec le même id, et lue par `slam_client.lire_reponse`. Sans réponse, `echec` : « Le service de cartographie du robot ne répond pas : vérifiez que unitree_slam est activé dans l'appli Unitree ». Si elle est refusée, `echec` avec son `info`.
4. Une relocalisation reçue après la réponse, en moins de 15 s depuis la demande ; sinon `echec` : « Le robot n'a pas réussi à se repérer : vérifiez qu'il est sur la marque, tourné dans le bon sens, puis recommencez ».
5. Pose trouvée à plus de 1,0 m ou 0,5 rad de P : `echec`, « le robot s'est repéré à X m de la position annoncée » ; `map → odom` n'est pas publié.
6. Sinon `repere` : `map → odom` est publié, avec le message « Robot repéré (précision N cm) ». `precision_m` = √((cov[0] + cov[7]) / 2) de la relocalisation, ou null si la covariance est nulle.
7. Une fois repéré : plus de relocalisation depuis 3 s donne `perdu`. Le dernier `map → odom` reste publié, mais `repere` est faux et le pont arrête le robot. L'état revient seul à `repere` quand la relocalisation reprend. Un `echec` après une réussite arrête la publication de `map → odom`.

**`amcl`** (secours, « notre carte et le LiDAR ») : `nav2_amcl` (`config/amcl_g1.yaml`) sur un `/scan` tiré de `/points` par `pointcloud_to_laserscan` (tranche de 0,1 à 1,5 m). Le repérage publie `/initialpose` (σ 0,25 m et 0,2 rad), et l'état passe à `repere` quand l'écart-type d'AMCL descend sous 0,15 m (15 s au plus). Il passe à `perdu` au-dessus de 0,5 m. Essayé en répétition seulement.

**`externe`** : `navigation.launch.py` ne lance aucune localisation, et un autre programme fournit `map → odom → base_link` et `/reperage/etat`. C'est le cas du relais simple du critère 17, et ce sera celui d'une autre localisation plus tard.

### 10.6 Le faux service slam_operate en répétition (agent Repérage)

`atelier/scan/faux_slam.py`, lancé par `g1-slam faux-service --jumeau --lieu L --etage E` :
- en plus du serveur du SDK sur `lo` (inchangé, pour `g1-slam --faux`), un **frontal ROS 2** dans le nœud `faux_slam` : il écoute `/api/slam_operate/request` (unitree_api/Request), traite chaque requête par le même `_traiter(api, parameter)`, et publie `/api/slam_operate/response` (identity recopiée, `status.code` = code RPC, `data` = texte JSON) ;
- le robot est la vérité terrain `/g1_jumeau/odom`, et le nuage `/g1_jumeau/points` (LiDAR à (−0,004 ; 0 ; 1,245) dans base_link). Il ne publie jamais de vitesse, et refuse 1102 (code `ERREUR_DEROULE` : « pas de 1102 en répétition du niveau 2 : la navigation passe par Nav2 ») ;
- son repère d'Unitree est `repere_unitree(lieu, etage)`, celui du relais. Cartes connues : `carte_unitree` du lieu et `repetition.pcd` ;
- **1804** : une `address` inconnue donne `ERREUR_CARTE`. Si la pose initiale, ramenée dans map, est à plus de 1,0 m ou 0,5 rad de la vérité, c'est un refus avec le nouveau code `ERREUR_RELOCALISATION` = 5 (« relocalisation impossible : le robot n'est pas à la position donnée »). Sinon, il se repère ;
- une fois repéré, à 10 Hz :
  - **`/unitree/slam_relocation/odom`** : `frame_id` `map`, `child_frame_id` `body` ; pose = vérité exprimée dans le repère d'Unitree (`carte_vers_unitree`), z 1,245 ; covariance diagonale 0,0004 (x, y) et 0,0001 (lacet) ; twist nul ;
  - **`/unitree/slam_relocation/points`** : le dernier `/g1_jumeau/points`, placé dans le repère d'Unitree par la vérité à son instant, `frame_id` `map` ;
  - `/slam_info` (`pos_info`, repère d'Unitree), comme aujourd'hui ;
- rien sur ces deux sujets avant le premier 1804 réussi, après un 1804 refusé ou après 1901 ; horodatage : celui des messages de Gazebo ;
- options `--retard S` (latence) et `--bruit M` (σ de position), nulles par défaut ; `/faux_slam/panne` (std_msgs/String, fiable, volatile) : `aucune` ou `muet` (il ne publie plus la relocalisation : essais de `perdu`).

### 10.7 Le lancement de la navigation (agent Repérage)

```
ros2 launch g1_nav navigation.launch.py lieu:=DOSSIER etage:=ID simu:=true|false moteur:=nav2|unitree|factice
    [localisation:=simu|unitree|amcl|externe] [pont:=auto|true|false]
```

| Argument | Défaut | Rôle |
|---|---|---|
| `localisation` | vide : `simu` si `simu:=true`, `unitree` sinon | 10.5 |
| `pont` | `auto` : vrai avec `moteur:=nav2`, sauf avec `localisation:=simu` | lance `g1_bridge` (`pont_g1`, `config/pont.yaml`). Si le paquet manque alors qu'il le faut, le lancement s'arrête avec un message |
| `nuage` (ajout) | vide | sujet du nuage donné au relais (vide : `/unitree/slam_relocation/points` ; `amcl` en répétition : `/g1_jumeau/points`) |
| `vitesse_max` (ajout) | vide | premiers essais : vitesse maximale en m/s (au plus 0,4) ; les plafonds du pont baissent dans la même proportion (0,2 donne 0,2 / 0,125 / 0,3). Vide : ceux du contrat. Repris par `g1-guide navigation --vitesse-max`, `g1-jetson demarrer --vitesse-max` et la variable `G1_VITESSE_MAX` (transmise par l'Atelier au conteneur) |

- Réglages de Nav2 : `nav2_g1_simu.yaml` avec `localisation:=simu`, `nav2_g1_reel.yaml` sinon, même en répétition (vitesses du robot) ; `use_sim_time` = `simu`.
- Avec `unitree` : `odom_vers_tf`, avec ses paramètres lus dans le lieu (`repere_unitree`, `carte_pour_reperage(lieu, repetition)` ; `repetition` = `simu:=true`) ; sur le robot (`simu:=false`), en plus, le TF statique base_link → lidar.
- `g1-guide navigation` : options `--localisation simu|unitree|amcl|externe` et `--pont auto|oui|non`.
- **Défauts de la vague 1 corrigés dans le guide** : si Nav2 n'est pas encore actif (serveur d'action absent), le guide passe à `attente`, avec le `message` « La navigation démarre : départ dès qu'elle est prête », et réessaie à chaque pas pendant 90 s au plus avant `echec`. Sans TF map → base_link, si le dernier `/reperage/etat` dit `repere` faux, c'est `echec` tout de suite : « Robot non repéré : cliquez sur « Repérer le robot » » ; sinon il attend comme pour Nav2. `/guide/etat` reçoit un champ facultatif `message` (texte en français), ajout rétrocompatible au contrat 4.2.

### 10.8 L'API et l'interface de l'Atelier (agent Repérage)

| Route | Corps | Réponse |
|---|---|---|
| `POST /api/simulation/demarrer` | `{lieu, etage, fenetre?, navigation?, mode?}` | `mode` (champ ajouté, `simu` par défaut) : `simu` ne change pas. `repetition` lance trois rôles : `simulation` (`g1-monde simuler --jumeau --sans-fenetre`), `faux_slam` (`g1-slam faux-service --jumeau --lieu L --etage E`) et `navigation` (`g1-guide navigation --simu --localisation unitree`). `robot` lance le rôle `navigation` : `g1-jetson demarrer --lieu L --etage E`. 409 sans câble (carrier de `ATELIER_INTERFACE_ROBOT`), ou si le serveur n'a pas été lancé dans un terminal relié au robot (`source setup/robot.sh` : `CYCLONEDDS_URI` sur cette interface, domaine 0). Dans les modes `repetition` et `robot`, aucune vitesse ne va directement à Gazebo |
| `POST /api/simulation/arreter` | | arrête tous les rôles ; en mode robot, par `g1-jetson arreter` |
| `GET /api/robot/etat` | | `{mode, lieu, etage, localisation, repere, etat, position: {x, y, theta} \| null, precision_m, age_s, message, marque: {x, y, theta}, pont: dernier /pont/etat \| null, reperage: dernier /reperage/etat \| null}`. `mode` vaut null si aucune navigation ne tourne |
| `POST /api/robot/reperer` | `{lieu, etage, x?, y?, cap?}` (repère map, cap en radians ; sans eux : la marque au sol, (0, 0, 0) dans le repère d'Unitree) | publie `/reperage/demander` (nouvel id ; `cap` devient `theta`) et attend 25 s au plus le `/reperage/etat` de cette demande. Repéré : 200 et l'état de `GET /api/robot/etat` ; `echec` : 502, avec le message du relais en `detail` ; rien : 504 ; 409 en mode simu, sans navigation, ou pour un autre lieu ou étage ; 400 si x, y et cap ne sont pas donnés ensemble ; 503 sans pont ROS 2 |
| `POST /api/robot/arret` | `{verrou: bool}` | publie `/pont/arret` ; `{verrou, pont}` |
| `POST /api/guide/aller` | | en `repetition` et `robot` : 409 « Repérez d'abord le robot » si l'état n'est pas repéré |
| `POST /api/simulation/teleop` | | en `repetition` : permise, elle passe par `/cmd_vel` puis le pont ; en `robot` : 409, comme avant |
| `/ws/etat` | | en plus : `mode`, `reperage`, `pont`. `robot` est la pose de `/reperage/etat` quand il est reçu, sinon `/odom` comme avant (en répétition, `/odom` est l'odométrie du relais, pas une position sur la carte) |

**Onglet Simulation** :
- un choix du mode : « Simulation », « Répétition sans robot » ou « Robot » ; ce dernier demande une confirmation, comme pour le scan (câble, télécommande en main) ;
- en répétition et en mode robot, un panneau « Repérage » :
  - la consigne « Posez le robot sur la marque au sol (croix sur la carte), tourné dans le sens de la flèche » ;
  - le gros bouton **« Repérer le robot »**, et le lien « Le robot n'est pas sur la marque », qui permet de cliquer sa position sur la carte puis de glisser vers son orientation ;
  - l'état : « Repéré », avec la précision et l'âge ; « Non repéré » ; « Repérage perdu » ; ou un échec avec son message ;
  - la pastille du pont, avec son état et son message ;
  - les boutons « Bloquer le robot » et « Débloquer » (`/api/robot/arret`) ;
- la marque au sol est dessinée sur la carte. « Y aller » reste grisé tant que le robot n'est pas repéré ou que Nav2 n'est pas prêt.

En répétition, la vérité terrain des tests est `/g1_jumeau/odom` (repère du monde Gazebo = map) ; `/odom` est l'odométrie du relais. L'outil `pres-de` de `tests_e2e/outils_e2e.py` (qui lit `/odom`) ne convient donc pas : les critères 17 à 20 lisent `/g1_jumeau/odom`.

### 10.9 Ce qui reste à vérifier sur le robot (séance d'environ 1 h 30)

Aucune simulation ne garantit que le vrai robot comprend ces formats de messages (ils viennent d'un projet tiers), ni comment il réagit vraiment. Liste de la séance, robot au portique et télécommande en main (déroulé pas à pas, avec les commandes : `docs/seance-robot.md` ; il fait le pont en premier, puis le conteneur, puis le repérage, puis un premier trajet court) :

**Installation (≈ 30 min)**
1. `ssh-copy-id unitree@192.168.123.164`, puis `g1-jetson verifier` : Docker, aarch64, place libre, mémoire, interface 192.168.123.164.
2. `g1-jetson construire`, `envoyer`, `demarrer --veille` : depuis le conteneur Humble, on voit les sujets du robot (Foxy et SDK2) : `/state_estimator/odom_pelvis`, `/lf/sportmodestate`, et le type `unitree_api/msg/Request`.
3. Charge du Jetson avec le conteneur : `--cpus 4 --memory 4g` suffisent-ils, et des services d'Unitree tournent-ils sur le Jetson ?
4. Décalage d'horloge entre le PC1 (horodatage des messages du robot) et le Jetson.
5. En option, l'Atelier par le Wi-Fi : `G1_WIFI`, `G1_PAIRS`, multicast coupé.

**Pont, au portique (≈ 30 min)**
6. Le service `sport` accepte nos requêtes ROS 2 sur `/api/sport/request` (sans bail, priorité 0). Noter le format de la réponse (code, `data`).
7. Une consigne de 0,5 s : le robot s'arrête seul à la fin (`kill -9` du pont pendant une marche lente).
8. L'arrêt `[0, 0, 0]` (durée 1,0) est net. 10 Hz passent sans saccade. Mesurer la latence entre l'ordre et le mouvement.
9. Les codes de refus réels, par exemple 7301 hors du mode marche : ajuster le message.
10. Les vitesses réelles pour 0,1 à 0,4 m/s, vy 0,25 et wz 0,6 : régler les plafonds et `nav2_g1_reel.yaml`.
11. **La télécommande reste-t-elle prioritaire et sert-elle toujours d'arrêt d'urgence** pendant que le pont envoie ? C'est la condition pour aller plus loin.
12. Ces essais se font avec `ros2 run g1_bridge pont --ros-args -p exiger_reperage:=false`, au portique seulement.

**Repérage (≈ 30 min, le plus incertain)**
13. 1804 envoyé en ROS 2 sur `/api/slam_operate/request` est-il accepté, sans passer par `unitree_sdk2py` ? Vérifier le format `{"data": {x, y, z, q_x, q_y, q_z, q_w, address}}`, le dossier des cartes, la réponse, et `/slam_info` après 1804.
14. `/unitree/slam_relocation/odom` :
    - n'est-elle publiée qu'après 1804 ? À quelle fréquence ?
    - quels sont son `frame_id` et son `child_frame_id`, et quel point du robot suit-elle (`pose_suivi`) ?
    - sa covariance est-elle remplie ?
    - son repère est-il celui du scan adopté (`repere_unitree` identité), avec l'origine au départ du scan ?
15. `/unitree/slam_relocation/points` : fréquence, repère (monde recalé ou capteur : `points_repere`), hauteur du sol dans ce repère (`z_carte_unitree`), contenu (balayage en cours ou carte). Suffit-il à l'évitement d'obstacles de Nav2 ? Sinon, trouver une autre source : MID-360 brut, `/unitree/slam_mapping/points`… C'est aussi la source de `/points` pour `amcl`.
16. `/state_estimator/odom_pelvis` : fréquence, `frame_id`, dérive réelle, continuité. Solution de rechange : `/unitree_slam/high_rate_odometry`.
17. Précision : robot sur la marque, « Repérer », puis écart mesuré au mètre ruban en trois endroits. Robustesse à 0,5 m ou 20° de la marque, et durée du repérage.
18. Comportement quand la relocalisation se perd (couloir sans repères, foule).
19. Montage du MID-360 (retourné ?) : base_link → lidar réel, et réglage de `voxel_layer` (un capteur retourné voit le sol).

### 10.10 Les agents de la vague 3

| Agent | Possède | Dépend de |
|---|---|---|
| Intégrateur | sections 4, 7, 9 et 10 du plan ; `atelier/lieu/` (dont les schémas et `robot.py`) ; `atelier/tests/test_contrats*.py` ; `tests_e2e/tout.sh`, `tests_e2e/LISEZMOI.md`, `commun.sh` ; `.gitignore`, `README.md` ; `lieux/demo` ; assemblage | — |
| J. Jetson | `docker/` (tout), `bin/g1-jetson`, `bin/gl-jetson`, `tests_e2e/critere_16_conteneur.sh` et ses outils (`tests_e2e/outils_jetson_e2e.py`) | contrats ; `g1_nav` et `g1_bridge` pour l'image (paquets en cours : l'image se reconstruit) |
| P. Pont et faux G1 | `ws/src/g1_bridge/`, `ws/src/g1_jumeau/` (tout) ; dans `ws/src/g1_sim/` : l'argument `jumeau`, `config/pont_gz_jumeau.yaml`, le lancement de `g1_jumeau` et leurs tests ; dans `atelier/monde/commande.py` : l'option `--jumeau` de `g1-monde simuler`, seulement ; `tests_e2e/critere_17_pont.sh`, `critere_20_securite.sh`, `tests_e2e/outils_pont_e2e.py` (dont le relais simple) | contrats ; Repérage pour le critère 20 (relais réel) |
| R. Repérage | `ws/src/g1_nav/` sauf `moteurs.py` (`odom_vers_tf.py`, `reperage.py`, `launch/navigation.launch.py`, `guide.py`, `commande.py`, `config/amcl_g1.yaml`, `nav2_g1_reel.yaml` si besoin, tests) ; `atelier/scan/faux_slam.py`, `slam_client.py` (ajouts seulement) et l'option `faux-service --jumeau` de `atelier/scan/commande.py` ; `atelier/serveur/`, `atelier/web/` ; `atelier/tests/test_serveur_robot*.py`, `test_scan_faux_slam_ros*.py` ; `tests_e2e/critere_18_reperage.sh`, `critere_19_niveau2.sh`, `tests_e2e/outils_reperage_e2e.py` | contrats ; Pont et faux G1 pour la répétition (`--jumeau`, `g1_jumeau`, `g1_bridge`) |

Règles communes (celles de la section 9.9, plus) :
- chaque agent n'écrit que dans ce qu'il possède et demande le reste à l'intégrateur ; `atelier/lieu` et les schémas ne changent que par lui ;
- domaines et partitions, sauf consigne contraire du lancement : Jetson 61 (`robot_61`), Pont 62 (`robot_62`), Repérage 63 (`robot_63`), y compris dans les conteneurs (réseau de l'hôte, même `ROS_DOMAIN_ID`) ; les critères se lancent avec `E2E_DOMAINE` et `E2E_PARTITION` ;
- Gazebo sans fenêtre ; compilations dans `ws/build_<paquet>` et `ws/install_<paquet>`, jamais dans `ws/build` ;
- **jamais rien sur eno2, jamais de ssh vers 192.168.123.x** : le vrai robot ne s'essaie qu'en répétition ;
- à la fin, tous les processus et conteneurs lancés sont arrêtés (vérifier avec `ps` et `docker ps -a`) ; tests réels, sans écran ni robot ; une section dans `docs/journal-atelier.md`, avec la liste de ce qui reste à vérifier sur le robot ;
- `lieux/demo` est la référence des tests : on n'y adopte pas de scan et on n'y écrit rien (voir le journal de l'intégrateur du 25/10 au soir). On travaille sur des copies.

**J. Jetson.**
1. Le `Dockerfile` multi-architecture, `demarrer.sh`, le modèle CycloneDDS (choix de l'interface 192.168.123.x, `defaut`, Wi-Fi et pairs), le nœud de présence.
2. `g1-jetson` et ses sous-commandes (10.2), avec l'aide en français. Le code qui parle au robot (ssh, scp) est écrit et relu, mais seulement essayé à blanc : commande affichée, et refus avec `G1_SLAM_FAUX=1`.
3. Construire l'image amd64 et la faire tourner sur le PC. Construire aussi l'image **arm64** une fois sous émulation, et y lancer les vérifications de l'image (`aarch64`, `ros2 pkg prefix`, imports) ; noter le temps de construction et la taille.
4. Tests : `docker/tests/`, avec la génération de la configuration CycloneDDS pour de fausses sorties de `ip -o -4 addr`, les commandes `docker run` produites et les refus ; puis le critère 16.

**P. Pont et faux G1.**
1. `g1_bridge` (10.3) : la logique du pont dans une classe sans ROS, à horloge injectable, testée finement (plafonds, délais, garde, verrou, repérage, robot muet, refus), puis le nœud.
2. `g1_jumeau` (10.4).
3. L'argument `jumeau` de `g1_sim`, dont les tests existants doivent passer sans changement, et `g1-monde simuler --jumeau`.
4. Tests ROS avec le faux G1 (et Gazebo pour les mesures de temps d'arrêt), puis les critères 17 et 20. Le relais simple du critère 17 (`outils_pont_e2e.py relais-simple`) publie map → odom (identité), odom → base_link depuis `/g1_jumeau/odom`, `/points` recopié de `/g1_jumeau/points` et `/reperage/etat` repéré ; il prend aussi la commande `perdre` pour les essais. Le critère 20 utilise le vrai relais et le faux slam_operate de l'agent Repérage. Tant qu'ils manquent, il répond « en attente » (code 77) ; avec `E2E_RELAIS=simple`, il tourne sur le relais simple.

**R. Repérage.**
1. Le relais et le repérage (10.5), avec la logique des repères testée sans ROS (corrections, dérive, sauts, perte, échecs), et l'envoi de 1804 en ROS 2.
2. Le faux service en répétition (10.6).
3. `navigation.launch.py` (10.7) et la correction du guide.
4. L'API, l'onglet Simulation et le bouton « Repérer le robot » (10.8), avec la mise à jour du parcours navigateur.
5. Le mode `amcl`, essayé en répétition.
6. Les critères 18 et 19. Le 19 répond « en attente » tant que `g1_jumeau` ou `g1_bridge` manquent ; avec `E2E_CONTENEUR=1`, il fait tourner la navigation dans le conteneur, si l'agent Jetson l'a livré.

### 10.11 Critères de recette de la vague 3

Les critères 16 à 20 sont dans la section 7, avec les dix premiers. `tests_e2e/tout.sh` les lance (scripts `critere_16_*` à `critere_20_*`) et affiche « N / 20 ». Les critères 1 à 15 doivent toujours passer.

Scripts et outils livrés : `critere_16_conteneur.sh` (outils : `critere_16_outils.py`), `critere_17_pont.sh` (`outils_pont_e2e.py`), `critere_18_reperage.sh` (`critere_18_outils.py`), `critere_19_niveau2.sh` (`critere_19_outils.py`) et `critere_20_securite.sh` (`critere_20_outils.py`), ces deux derniers écrits à l'assemblage. Résultats : journal, section « Intégrateur (assemblage de la vague 3) ».

### 10.12 Précisions de l'assemblage (vague 3)

Acceptées par l'intégrateur le 26/10/2026. Elles complètent les sections 10.2 à 10.11 et font foi comme elles.

**Compilation.** `g1_sim`, `g1_nav`, `g1_bridge` et `g1_jumeau` sont compilés dans `ws/install` (`colcon build --symlink-install --packages-select g1_sim g1_nav g1_bridge g1_jumeau`), vus par `setup/env.sh`. Les dossiers `ws/build_*`, `ws/install_*` et `ws/log_*` des agents sont retirés ; `tests_e2e/commun.sh` les charge encore en repli, pour une copie de travail. Après une modification de `g1_nav` ou `g1_bridge`, l'image du Jetson se refait (`g1-jetson construire --arch amd64`, puis `g1-jetson construire`, 30 s chacune).

**Conteneur (10.2).**
- L'image de base est désignée par l'empreinte de son manifeste (`--build-arg BASE=ros:humble-ros-base-jammy@sha256:…`) : avec le magasin containerd de Docker 29, le nom seul désigne les deux architectures, et le constructeur classique prenait l'amd64 malgré `--platform linux/arm64`.
- Nav2 est installé composant par composant : tout `ros-humble-navigation2` sauf `nav2_rviz_plugins` (RViz, Qt) et `nav2_waypoint_follower` (OpenCV). L'image passe de 0,74 à 0,47 Go compressés.
- `docker run` reçoit aussi `--log-opt max-size=20m --log-opt max-file=5`, et `--runtime R` avec `G1_JETSON_RUNTIME=R`. En mode `navigation`, les arguments donnés après le nom de l'image s'ajoutent à `ros2 launch`.
- Sous-commandes et options en plus du tableau : `tester-local`, `shell`, `construire --contexte DOSSIER` (plan B : construire sur le Jetson) et `--incomplet`, `demarrer --vitesse-max` ; variables `G1_JETSON_ARCH`, `G1_JETSON_RUNTIME`, `G1_JETSON_CPUS_CONSTRUCTION`, `G1_VITESSE_MAX`.
- `verifier` lance un conteneur jetable (`G1_LANCEMENT=commande`), pas un conteneur en veille ; `etat` lit `/g1_jetson/etat` par `docker exec`, avec en secours le fichier `/tmp/g1_jetson_etat.json`. `demarrer` attend 3 s de plus après la ligne de démarrage, pour rendre une erreur précoce avec son message ; `verifier` demande 4 Go libres.
- Sous qemu-user, `IP_MULTICAST_IF` n'est pas émulé : l'essai de l'image arm64 sur le PC passe en unicast sur `lo`. Le Jetson, natif, n'est pas concerné.
- Mesures : première construction arm64 en 4 min sur le PC du projet (et non 30 à 60 min), 0,45 Go compressés, 1,5 Go une fois chargée.

**Pont (10.3).**
- Règle 9 : vérification du lien à l'apparition de l'abonné, écrite en 10.3.
- « Vitesse mesurée de 0,42 m/s au plus » (critère 17) se lit composante par composante, dans le repère du robot : la norme vaut √(0,4² + 0,25²) = 0,47 m/s avec les plafonds du contrat.
- La consigne reste fraîche 0,3 s après le dernier `/cmd_vel` : 3 s de `/cmd_vel` à 0,3 m/s font 0,98 m. Un départ et un arrêt partent tout de suite, sans attendre le pas de 100 ms.
- Les plafonds peuvent être abaissés par les paramètres `vx_max`, `vy_max`, `wz_max` (jamais relevés) ; `navigation.launch.py vitesse_max:=V` le fait dans la même proportion (10.7).

**Faux G1 (10.4).** L'argument `jumeau` est déclaré au premier niveau de `simulation.launch.py`, comme les quatre du contrat 4.5 (le premier jet le cachait dans un `GroupAction`) ; les tests des arguments de `g1_sim` et de `g1_jumeau` le comptent. Le faux G1 écoute les requêtes et répond en fiable (le client C++ d'Unitree écoute en fiable) ; toute api autre que 7105 reçoit 3203.

**Repérage (10.5 à 10.8).**
- `perdu` après 3 s sans relocalisation (`DELAI_PERDU_S`).
- `amcl` : pendant le repérage, le relais demande à AMCL des mises à jour sans mouvement (`/request_nomotion_update`, 4 Hz), car le pont refuse de bouger un robot non repéré et AMCL ne converge pas sans cela.
- `pont:=auto` ne lance le pont qu'avec `moteur:=nav2` : sans Nav2, personne ne publie `/cmd_vel`.
- La répétition lancée par l'Atelier passe `--bruit 0.01` au faux slam_operate (1 cm), pour éprouver la correction ; le défaut de `g1-slam faux-service` reste 0.
- Ajouts : champs `correction` et `relocalisations` de `/reperage/etat` ; `GET /api/robot/etat?lieu=&etage=` donne la marque quand rien ne tourne ; `ecoute` et `avertissement` dans la réponse de `/api/robot/arret` ; dans `/ws/etat`, `robot` vaut null en répétition et en mode robot tant que le robot n'est pas repéré ; le guide ne compte pas comme « bloqué » le temps où le repérage est perdu.
- Avec `localisation:=unitree`, Nav2 n'est actif qu'après le repérage (la carte des coûts globale attend `map → base_link`) : le guide attend (`attente`, « La navigation démarre… »), puis part seul.

**Tests (10.10, 10.11).** Noms gardés : `atelier/tests/test_robot_*.py` (au lieu de `test_serveur_robot*.py` et `test_scan_faux_slam_ros*.py`) ; `tests_e2e/critere_16_outils.py` et `critere_18_outils.py` (au lieu de `outils_jetson_e2e.py` et `outils_reperage_e2e.py`). Le critère 19 avec `E2E_CONTENEUR=1` fait passer la navigation de la répétition par un `g1-guide` de test qui démarre le conteneur (`g1-jetson demarrer --local`, `G1_SIMU=true`) et l'arrête avec la répétition : l'Atelier n'a pas de mode « répétition dans le conteneur ». Le critère 20 retrouve le faux G1 et le pont parmi les processus lancés avec ses lieux, les arrête (SIGTERM, SIGKILL) puis les relance lui-même (`ros2 run`), et les arrête à la fin ; son témoin juge chaque instant hors d'une fenêtre de mouvement permis (fenêtre fermée à l'instant où le robot doit être arrêté).

**Réseau du robot.** `setup/robot.sh` exporte `ROS_DOMAIN_ID=0` (le robot publie sur le domaine 0 ; l'Atelier en mode robot l'exige).

**Séance avec le robot.** Le déroulé pas à pas est dans `docs/seance-robot.md`. Il reprend la liste de 10.9 dans cet ordre : le pont au portique, à vitesse réduite (plafonds 0,1 m/s, format 7105, arrêt seul quand le pont meurt, télécommande prioritaire), puis le conteneur, puis le repérage 1804 (avec un petit scan de la zone s'il n'y en a pas), puis un premier trajet court de 3 m à 0,2 m/s (`G1_VITESSE_MAX=0.2`).

---

## 11. Accueil, passants, pilotage et équipe (vague 4)

Contrats figés par l'intégrateur le 26/10/2026, avant le travail en parallèle de cinq agents (11.7). Comme les sections 4, 9 et 10, cette section fait foi ; on ne la modifie qu'en passant par l'intégrateur. Elle couvre cinq demandes de l'utilisateur : **A** un point principal unique par lieu ; **B** des passants que le robot contourne vraiment ; **C** le comportement du guide (retour, accompagnement, robot perdu, messages au visiteur) ; **D** un onglet Pilotage, comme l'appli Unitree Explore, avec les danses du robot et des chorégraphies sûres ; **E** les emplacements pour l'équipe (caméra See3CAM, chatbot à règles, modes de personnalité).

Code partagé déjà livré et testé (`atelier/tests/test_contrats_vague4.py`) :
- les schémas JSON (draft-07) des nouveaux fichiers et messages, reconnus par `valider_donnees` et `valider_message` : fichiers `personnalites`, `dialogues`, `camera`, `scene`, `choregraphie` ; messages `etat_guide`, `evenement_guide`, `demande_guide`, `pietons_etat`, `pietons_consigne`, `personnes`, `maitre_mouvement`, `etat_pilotage`, `robot_dire`, `personnalite_active` (`TYPES_MESSAGES`) ; l'état `pilotage` du pont dans `etat_pont` (`ETATS_PONT`) ;
- les champs facultatifs : `etiquettes` d'une salle (`Salle.etiquettes`), la section `guide` de `lieu.yaml` (`Lieu.guide`), les champs du piéton crédible dans `monde.yaml` (`Pieton`) ; tous absents des fichiers quand ils valent leur défaut : les lieux existants ne changent pas ;
- un module de contrat par agent dans `atelier/lieu/` : `principal.py`, `passants.py`, `comportement.py`, `pilotage.py`, `equipe.py` (fonctions et valeurs « contrat » écrites et testées ; les fonctions de l'agent lèvent `NotImplementedError` d'ici là) ; des exemples dans `atelier/lieu/exemples/` (personnalites, dialogues, camera) et la chorégraphie `choregraphies/exemple_kpop.choregraphie.yaml` ;
- la règle « un seul point principal par lieu, obligatoire » dans la validation et la vérification ; l'étiquette posée par `creer_lieu` ;
- `/guide/aller` en JSON et la cible `principal` acceptés par le nœud guide (passerelle : la cible seulement) ;
- les squelettes : onglets Pilotage, Personnalités, Dialogues et Caméra (`app.js`, écrans vides), panneaux du guide et des passants dans l'onglet Simulation, une feuille de style par agent, cinq fichiers de routes vides enregistrés dans le serveur, l'écoute des sujets JSON de la vague 4 par le pont ROS 2 du serveur (`dernier`, `historique`, `publier_json`) et leurs champs dans `/ws/etat`, les paquets `ws/src/g1_pilotage` et `ws/src/g1_equipe` (compilés et testés), les nœuds `detecteur_personnes` et `faux_visiteur` déclarés dans `g1_nav` (modules vides), `atelier/monde/scene.py` et `atelier/equipe/` ;
- `tests_e2e/tout.sh` compte 30 critères (« N / 30 ») ; un critère sans script est « absent ».

### 11.1 Ce qui change, et le chemin des commandes du pilotage

| Demande | Pièce | Où elle tourne |
|---|---|---|
| A | point principal (étiquette d'une salle) ; `depart_robot` synchronisé ; pose par défaut du repérage | fichiers du lieu, serveur, onglets Salles et Simulation |
| B | piétons crédibles (corps et réaction), scènes, mesure des contacts, réglages de Nav2 | `g1_sim` (Gazebo), `g1-banc`, `nav2_g1_*.yaml` |
| C | guide : retour, accompagnement, perdu, passant qui bouche, événements ; détecteur de personnes au LiDAR ; faux visiteur | `g1_nav` (guide, `detecteur_personnes`, `faux_visiteur`) |
| D | pilotage : postures, joystick, gestes, voix, LED, danses, chorégraphies ; verrou des mouvements ; faux G1 étendu | `g1_pilotage` (conteneur du Jetson), Atelier, `g1_jumeau`, `g1_bridge`, `docker/` |
| E | personnalités, dialogues, caméra ; sujets entre les parties ; document pour l'équipe | fichiers du lieu, onglets, `g1_equipe` |

```
Navigateur, onglet Pilotage ──HTTP /api/pilotage/* et WebSocket /ws/pilotage──► serveur de l'Atelier (PC)
   ──HTTP et WebSocket par le Wi-Fi (G1_PILOTAGE_URL, port 8010, en-tête X-Jeton)──► nœud pilotage (g1_pilotage,
     dans le conteneur du Jetson ; sur le PC en répétition)
   ──ROS 2 sur le réseau interne 192.168.123.x──► services sport, arm, voice (unitree_api/Request sur
     /api/<service>/request, réponses sur /api/<service>/response) et rt/arm_sdk (/arm_sdk, unitree_hg/LowCmd)
```

**Choix : une petite API HTTP et WebSocket dans le conteneur, et non DDS par le Wi-Fi.** Raisons :
1. la découverte DDS par le Wi-Fi est lourde et fragile (une trentaine de participants avec Nav2, multicast souvent bloqué, `G1_PAIRS` à tenir à jour) ; une connexion TCP vers un port connu suffit ;
2. la sécurité est au plus près du robot : plafonds, refus, homme mort et verrou sont dans le conteneur. Si le Wi-Fi ou la page se coupent, le conteneur arrête le robot de lui-même en 0,5 s, sans dépendre du PC ;
3. l'Atelier n'a besoin d'aucun réglage DDS sur le réseau du robot pour piloter ; la navigation, elle, reste en DDS sur le réseau interne ;
4. tout se teste sur le PC contre le faux G1, avec la même API.

Bibliothèque : `tornado` (`python3-tornado`, déjà présent dans le Python du système du PC, paquet apt arm64 pour Ubuntu 22.04), HTTP et WebSocket sans dépendance de plus. Port `PORT_PILOTAGE` = 8010 (`G1_PILOTAGE_PORT`). Sur le Wi-Fi, un jeton partagé `G1_PILOTAGE_JETON` est exigé dans l'en-tête `X-Jeton` (refus 401 sans lui ; vide : seules les connexions de 127.0.0.1 sont acceptées). Le serveur de l'Atelier joint le nœud par `G1_PILOTAGE_URL` (défaut `http://127.0.0.1:8010`, la répétition sur le PC ; avec le robot : l'adresse Wi-Fi du Jetson, ou `http://192.168.123.164:8010` au câble).

### 11.2 A. Le point principal (agent Point principal)

**Format.** Le point principal est une salle de `salles.yaml` qui porte l'étiquette `principal` :

```yaml
- id: accueil
  nom: Accueil
  alias: [accueil]
  etage: rdc
  pose: {x: 2.5, y: 10.0, theta: 0.0}      # la flèche : le robot y est posé tourné vers theta
  phrase_arrivee: ''
  etiquettes: [principal]                  # vague 4 : facultatif, liste vide par défaut
```

`accueil` de `lieu.yaml` garde son nom et devient la copie de la pose du point principal (`etage`, `x`, `y`, `theta`). L'id du principal est libre (en général `accueil`) ; il a son nœud de même id dans `itineraires.yaml`, comme toute salle. `etiquettes` : des identifiants, sans doublon, 20 au plus ; seule `principal` est réservée, les autres sont libres (l'équipe peut s'en servir : `toilettes`, `sortie`…) et ne changent rien au guide.

**Un seul principal par lieu, obligatoire** :
- deux salles étiquetées : erreur de `salles.yaml` (fichier refusé à la lecture et à l'écriture), et de `verifier_lieu` ;
- aucune étiquette : le **principal implicite** est la salle `accueil` (lieux d'avant la vague 4 : `demo`, `demo_scan`, `bomboclat`), sans avertissement ; ni étiquette ni salle `accueil` : erreur de `verifier_lieu` (« le lieu n'a pas de point principal »), et l'Atelier refuse de lancer la simulation, la répétition ou le robot sur ce lieu (409, message en français ; livré : `exiger_point_principal` de `atelier/serveur/communs.py`, appelé par `POST /api/simulation/demarrer`) ;
- la pose du principal doit être `accueil` de `lieu.yaml` (erreur sinon : la règle de la salle accueil, étendue) ;
- `PUT /api/lieux/{id}/salles` refuse (422, comme toute validation) une liste à deux principaux, et, si le lieu a un principal explicite, une liste qui le perd (« choisissez d'abord un autre point principal ») ; avec `?synchroniser=true`, c'est la pose du principal (et non plus celle de la salle « accueil ») qui est recopiée dans `accueil` de `lieu.yaml`, et dans `depart_robot`.

Fonctions de contrat (`atelier.lieu.principal`, livrées) : `point_principal(lieu)` (la salle, ou None), `principal_explicite`, `salles_principales`, `pose_principale(lieu)` (PoseEtage), `pose_de_reperage(lieu, etage)`, `depart_simulation(lieu, etage)`, `accueil_conforme(lieu)`. À écrire par l'agent : `definir_principal(lieu, salle?, x?, y?, theta?)` (tout ou rien : étiquette, `salles.yaml`, nœud, `accueil`, `depart_robot`), `synchroniser_depart(lieu)`, `sauvegarder_lieu(lieu, raison)`, `migrer_lieu(lieu, depuis_depart=False, a_blanc=False)`.

**Lien avec `depart_robot` : il se synchronise.** Chaque écriture du principal par l'Atelier ou par `g1-lieu migrer` recopie sa pose dans `depart_robot` du monde de son étage (s'il a un monde). `verifier_lieu` avertit s'ils diffèrent (« la simulation ne partira pas de l'accueil »). `g1_sim` ne change pas : il lit toujours `depart_robot`. Dans l'onglet Monde, `depart_robot` de l'étage du principal est affiché « = point principal », sans poignée. Après `g1-scan adopter --monde` (le monde du scan a son propre départ), `synchroniser_depart` est appelé (seule modification permise à l'agent A dans `atelier/scan/commande.py`).

**Lien avec le repérage.** `POST /api/robot/reperer {lieu, etage}` sans `x`, `y`, `cap` : le serveur prend `pose_de_reperage(lieu, etage)` — le point principal s'il est sur cet étage, sinon la marque au sol (origine de la carte d'Unitree) — et l'envoie toujours en entier (`x`, `y`, `theta`, repère map) dans `/reperage/demander`. Le relais la convertit vers le repère d'Unitree par `carte_vers_unitree(P, repere_unitree)` (`atelier.lieu.robot` et `conversions`, inchangés) avant 1804. Le relais garde son défaut de la vague 3 (une demande sans pose vise l'origine d'Unitree), qui ne sert plus à l'Atelier. Conséquences :
- sur le vrai robot, plus besoin de la marque au départ du scan : on pose le robot sur le point principal, dans le sens de la flèche ;
- pour un monde dessiné, `repere_unitree` vaut `depart_robot`, donc le principal : 1804 reçoit (0, 0, 0), comme en vague 3 ;
- variante B du critère 18 (`repere_unitree` tourné) : le repérage par défaut réussit désormais (le robot est bien sur le principal) ; le refus se vérifie avec une pose fausse donnée explicitement. L'agent A adapte `critere_18_reperage.sh` et `critere_18_outils.py`.

`GET /api/robot/etat` : `marque` devient la pose de repérage par défaut (le principal) ; champ ajouté `principal: {salle, nom, x, y, theta} | null`.

**Migration et sauvegarde** (`g1-lieu migrer --lieu L [--depuis-depart] [--a-blanc]`, agent A) :
1. sauvegarde d'abord : copie de `lieu.yaml`, `salles.yaml`, `itineraires.yaml` et `mondes/*.monde.yaml` dans `lieux/<id>/sauvegardes/AAAA-MM-JJ_HHhMM_migration/` (`-2`, `-3`… si besoin), suivie par Git comme le reste du lieu ;
2. puis : étiquette `principal` sur la salle `accueil` ; avec `--depuis-depart`, le principal prend d'abord la pose `depart_robot` de son étage ; `accueil`, nœud et `depart_robot` alignés ;
3. rapport en français : la sauvegarde, chaque valeur changée (avant, après), les erreurs qui existaient déjà (elles ne bloquent pas, sauf un fichier illisible) ;
4. idempotent (un second passage ne change rien) ; `--a-blanc` n'écrit rien ;
5. refuse `lieux/demo` (la référence des tests reste au format implicite : les tests couvrent les deux formes).

`bomboclat` (le lieu de l'utilisateur) et `demo_scan` sont migrés par l'agent A, après un essai sur une copie, avec la sauvegarde, et un test : `valider_lieu` donne les mêmes erreurs avant et après. Pour `bomboclat`, le principal reste la salle `accueil` (1 ; 1 ; 0), et son `depart_robot` actuel (36 ; 25,25 ; 1,8326), différent, est gardé dans la sauvegarde et cité dans le rapport : l'utilisateur pourra déplacer le principal sur la carte.

**Interface (agent A).** Onglet Salles : le principal dessiné d'une étoile et d'une flèche (theta) ; glisser la flèche le tourne (`PUT …/principal {theta}`) ; « Faire de cette salle le point principal » ; impossible de supprimer le principal sans en choisir un autre. Onglet Simulation (répétition et robot) : « Posez le robot sur le point principal « Accueil » (étoile sur la carte), tourné dans le sens de la flèche » ; l'étoile et la flèche remplacent la croix de la marque ; « Le robot n'est pas sur le point principal » garde le clic-glissé de la vague 3.

API (agent A, `routes/principal.py`) : `GET /api/lieux/{id}/principal` → `{salle, nom, etage, x, y, theta, explicite, depart_synchro, repere_unitree, pose_unitree}` (`pose_unitree` : la pose que recevra 1804) ; `PUT /api/lieux/{id}/principal {salle?, x?, y?, theta?}` → `definir_principal`, réponse `{enregistre, principal, rapport}` comme les autres PUT (4.4) ; `x` et `y` vont ensemble ; 404 pour une salle inconnue.

### 11.3 B. Les passants (agent Passants)

Constat (banc du critère 6, vague 3) : sur 20 trajets, 13 ont eu un piéton à moins de 0,6 m de centre à centre (10 sous 0,25 m), sans aucun détour. Les piétons de Gazebo (`<actor>`) n'ont pas de collision et ne voient pas le robot.

**Piétons crédibles** (`g1_sim`, nœud `pietons`, agent B). Chaque piéton du monde devient dans Gazebo un **corps qui gêne** (cylindre de `rayon_m`, 1,7 m de haut, que le LiDAR voit et que le robot proxy ne peut pas traverser), déplacé au moins 20 fois par seconde le long de son trajet, avec une **réaction simple** quand le robot est à moins de `distance_reaction_m` bord à bord, devant lui (±60° autour de sa direction de marche) :
- `arret` : il s'arrête, et repart 1 s après que le robot s'est éloigné ;
- `ecart` : il ralentit à 0,5 m/s et s'écarte de 0,6 m au plus du côté opposé au robot, dans l'espace libre de la carte ; s'il ne peut pas, il s'arrête ;
- `aucune` : il ne voit pas le robot (scènes « pire cas »).

Champs facultatifs d'un piéton (`monde.yaml`, schéma `monde`, défauts dans `atelier.lieu.passants.DEFAUTS_PIETON`) : `reaction` (`ecart`), `distance_reaction_m` (0,8), `corps` (true), `rayon_m` (0,25), `pauses` (`[{point, duree_s}]` : arrêt à chaque passage au point de ce rang ; un piéton immobile : une pause de 3600 s au point 0), `depart_s` (0), `repeter` (true ; false : un seul parcours, puis il reste au dernier point), `pilote` (`trajet` ; `externe` : il suit `/pietons/consigne`, pour le faux visiteur, 11.4). Le calcul du trajet prévu reste `atelier.monde.pietons` (l'agent B y ajoute pauses, départ et `repeter`).

Mécanisme dans Gazebo : au choix de l'agent B (modèles déplacés par `set_pose`, ou par `VelocityControl`…), avec trois exigences : le LiDAR les voit (comme les `<actor>` aujourd'hui), le robot ne les traverse pas, et le facteur temps réel de Gazebo reste à 0,9 au moins avec 5 piétons sur le PC du projet. Nouvel argument `pietons:=corps|acteurs` de `simulation.launch.py` (défaut `corps` ; `acteurs` : les `<actor>` de la vague 1, sans nœud) ; un piéton `corps: false` reste un `<actor>`.

| Sujet | Type | Sens | Rôle |
|---|---|---|---|
| `/pietons/etat` | std_msgs/String (JSON, schéma `pietons_etat`) | g1_sim → | positions et vitesses vraies (repère map), `etat` (`marche`, `pause`, `arret`, `ecart`, `pilote`, `fini`), 10 Hz |
| `/pietons/consigne` | std_msgs/String (JSON, schéma `pietons_consigne`) | → g1_sim | `{id, vx, vy, theta?}` d'un piéton `pilote: externe`, repère map, 1,5 m/s au plus, valable 0,5 s ; le nœud refuse d'entrer dans un mur |

Le serveur de l'Atelier montre dans `/ws/etat` les piétons de `/pietons/etat` quand il est frais (moins de 1 s), sinon il les recalcule comme avant (déjà livré).

**Scènes** (fichiers `atelier/monde/scenes/<id>.scene.yaml`, schéma `scene`, chargées par `atelier.monde.scene`, agent B) : un lieu de référence (`demo`), un étage, des piétons qui remplacent (ou complètent) ceux du monde d'une **copie** du lieu, des trajets, un nombre d'essais, des réglages du guide pour la copie, et les seuils de réussite (`mesures`). `g1-banc --scene ID` copie le lieu, applique la scène, fait les trajets et vérifie les seuils. Scènes de l'agent B, dans le lieu `demo` (couloirs nord et sud de 3 m entre axes de murs, soit 2,85 m libres) :

| Scène | Piétons | Trajets |
|---|---|---|
| `immobile_couloir` | un passant immobile au milieu du couloir nord, en (12,0 ; 13,0), `reaction: aucune` (il reste 1,18 m libre de chaque côté) | accueil → b204, 5 essais |
| `en_face` | un passant qui remonte le couloir nord vers l'ouest, sur la ligne du robot (y = 13), à 1,0 m/s, `reaction: aucune` | accueil → b204, 5 essais |
| `coupe_route` | un passant qui traverse le hall de part en part devant le robot (x = 2,5, de y = 11 à 12,5, va-et-vient à 1,0 m/s), `reaction: aucune` | accueil → b204, 5 essais |
| `groupe_couloir` | trois passants côte à côte en travers du couloir nord, en x = 15,5 (y = 12,0 ; 13,0 ; 14,0), immobiles 15 s (`pauses`) puis qui partent vers l'est et sortent par b204 (`repeter: false`) | accueil → b204, 3 essais |
| `groupe_reste` | les mêmes trois passants, immobiles 600 s | accueil → b204, 2 essais |
| `foule` | les 5 piétons du critère 6, piétons crédibles par défaut (`ecart`) | 20 trajets tirés au sort |

**Mesures** (`atelier.lieu.passants`, livrées) : distance **bord à bord** = distance des centres − `RAYON_ROBOT_CONTACT` (0,26 m, le cercle qui contient la boîte de collision 0,208 × 0,477 m du robot proxy) − `rayon_m` du piéton. **Contact** : la distance bord à bord passe sous `SEUIL_CONTACT_M` (0,05 m) ; il finit au-dessus de `SEUIL_FIN_CONTACT_M` (0,15 m). **Cause**, au début du contact (`cause_contact`) : `robot` si la vitesse du robot projetée vers le piéton dépasse `VITESSE_APPROCHE_M_S` (0,05 m/s), même si le piéton avançait aussi ; sinon `pieton` si le piéton avançait vers le robot ; sinon `aucun`. `SuiviContacts` tient le compte, au moins 20 fois par seconde. Vérités : `/odom` en simulation (Gazebo, map = odom), `/g1_jumeau/odom` en répétition ; `/pietons/etat` pour les piétons (sans lui, les positions calculées depuis le monde, et des vitesses par différences).

**CSV de `g1-banc`** : les colonnes de la vague 1 restent ; s'ajoutent, dans cet ordre (`COLONNES_BANC_V4`) : `scene`, `distance_min_bord_m`, `contacts`, `contacts_robot`, `contacts_pieton`, `contacts_aucun`, `temps_arret_pres_s` (robot arrêté, moins de 0,02 m/s, à moins de 1,5 m bord à bord d'un piéton), `attentes_passage` (passages à l'état `attente_passage`), `duree_attente_passage_s`, `longueur_m` (distance parcourue), `longueur_directe_m` (longueur de l'itinéraire du départ, sans détour). `distance_min_pietons_m` (centre à centre) reste.

**Réglages de Nav2 que l'agent B peut toucher**, dans `nav2_g1_simu.yaml` et `nav2_g1_reel.yaml` à l'identique (sauf les vitesses, `test_reglages.py`) :
- carte de coûts locale : `voxel_layer` (hauteurs `min_obstacle_height` et `max_obstacle_height`, pour voir les **obstacles bas sous 1,1 m** ; sources d'observation, portées, effacement) ; il peut ajouter une source tirée de `/points` (par exemple un `/scan` de `pointcloud_to_laserscan` dans une autre tranche) ; `inflation_radius` et `cost_scaling_factor` (**distance aux personnes**) ;
- MPPI : poids et marges des critiques (`ObstaclesCritic` : `collision_margin_distance`, `repulsion_weight`, `critical_weight`…), horizon ;
- Collision Monitor : le cercle `ralentir` (rayon, `slowdown_ratio` : **ralentir près des personnes**) ; un polygone de plus si besoin ;
- il ne touche pas : les repères, les sujets et la chaîne `cmd_vel` (controller → velocity_smoother → collision_monitor → `/cmd_vel`), `speed_limit_topic` (`/speed_limit` est au guide, 11.4), le filtre Keepout, l'arbre `naviguer_par_poses.xml`, `use_sim_time` ; il ne relève aucune vitesse maximale ; `robot_radius` reste à 0,35 m au moins, le cercle `arret` à 0,4 m au moins.
Sur le vrai robot, les mêmes réglages seront à revoir au milieu de vraies personnes (11.11).

**Passant qui bouche le couloir.** Règle mise dans le guide par l'agent C (11.4) : quand le robot n'avance plus et qu'une personne vue au LiDAR est devant lui, il attend `delai_passant_s` (20 s) dans l'état `attente_passage`, avec l'événement `passant_gene`, avant de déclarer le couloir bloqué. L'agent B fournit les scènes `groupe_couloir` et `groupe_reste` et vérifie la règle (critère 25).

### 11.4 C. Le comportement du guide (agent Comportement du guide)

**États de `/guide/etat`** (`ETATS_GUIDE`, schéma `etat_guide`) : ceux de la vague 1 restent, avec le même sens ; s'ajoutent `retour`, `attente_passage`, `attente_visiteur` et `perdu`.

| État | Quand |
|---|---|
| `attente` | au repos ; après un retour, au point principal, tourné selon sa flèche |
| `en_route` | visite vers la salle demandée |
| `retour` | retour automatique vers le point principal (cible : son id) |
| `bloque` | plus de progrès depuis 3 s (aucune personne devant) |
| `attente_passage` | plus de progrès, et une personne vue devant à moins de 2,5 m (1,5 m avant l'assemblage, voir 11.12) : robot arrêté, attente `delai_passant_s`, puis `detour` |
| `detour` | autre chemin après un couloir bloqué |
| `attente_visiteur` | le visiteur suivi traîne trop ou n'est plus vu : le robot l'attend, `delai_visiteur_s` au plus |
| `perdu` | le robot ne sait plus où il est (repérage `perdu`) : arrêté, `delai_perdu_s` au plus, puis `echec` |
| `arrive` | arrivé à la salle visée |
| `echec` | le trajet a échoué (`message`) |

Champs ajoutés, facultatifs (compatibles) : `version`, `mission` (`visite`, `retour`, ou null), `accompagner`, `visiteur` (`{vu, distance_m, age_s}` ou null), `depuis_s`. Un consommateur de la vague 1 reste juste : une visite finit toujours par `arrive` ou `echec` (`ETATS_FINAUX_VISITE`) avec la cible demandée ; le retour qui suit est un nouveau trajet, dont la cible est le principal.

**`/guide/aller`** (schéma `demande_guide`, `lire_demande_aller`, livré) : l'id simple d'avant reste accepté (visite sans accompagnement, retour automatique selon le lieu) ; en JSON : `{"cible": "b204", "accompagner": true, "retour": true, "source": "dialogue"}` (`accompagner` vaut true par défaut dans ce format). La cible `principal` désigne le point principal. La passerelle livrée dans le nœud guide ne prend que la cible ; l'agent C ajoute le reste.

**`/guide/evenement`** (std_msgs/String JSON, schéma `evenement_guide`, une fois par événement) : `{"version": 1, "code": "depart", "texte": "Suivez-moi, je vous emmène à Salle B204.", "salle": "b204", "nom": "Salle B204", "mission": "visite", "temps": "…"}`. Le `texte` est la phrase à dire, en français ; la partie voix de l'équipe la dit, par `/robot/dire` (11.6). Codes et textes par défaut (`CODES_EVENEMENT`, `{nom}` : nom de la salle) :

| Code | Texte par défaut | Code | Texte par défaut |
|---|---|---|---|
| `depart` | Suivez-moi, je vous emmène à {nom}. | `detour` | Le passage est encombré : je prends un autre chemin. |
| `seul` | Je ne vous vois pas derrière moi : je pars vers {nom}, suivez-moi. | `arrivee` | Nous sommes arrivés : voici {nom}. (ou `phrase_arrivee`) |
| `ralentir` | Je ralentis pour vous attendre. | `retour` | Je retourne à l'accueil. |
| `attente_visiteur` | Je vous attends. | `retour_arrive` | Je suis de retour à l'accueil. |
| `visiteur_retrouve` | Vous voilà ! Continuons. | `perdu` | Je me suis un peu perdu : un instant, s'il vous plaît. |
| `visiteur_perdu` | Je ne vous vois plus. Je retourne à l'accueil. | `retrouve` | C'est bon, je sais de nouveau où je suis. |
| `passant_gene` | Pardon, puis-je passer ? | `echec` | Désolé, je ne peux pas vous y emmener. Demandez de l'aide à l'accueil. |
| `passage_libre` | Merci ! | `arret` | Je m'arrête. |
| | | `pilotage` | Je suis piloté à la main pour le moment. |
| | | `immobilise` | Je ne peux pas bouger pour le moment. (correction du 01/11/2026, 12.15 : robot bloqué, pas en mode marche, muet ou qui refuse, pont vers la marche absent ; champ `raison`) |

**Comportements** :
- **retour automatique** : `delai_avant_retour_s` (15 s) après `arrive`, après un abandon (`visiteur_perdu`) ou après un `echec` (si le robot sait où il est et n'est pas piloté), le guide passe à `retour` vers le point principal, puis à `attente` à 0,3 m et 10° au plus de sa pose (`TOLERANCE_RETOUR_M`, `TOLERANCE_RETOUR_RAD`), avec les événements `retour` et `retour_arrive`. Une nouvelle demande l'interrompt. `retour_auto: false` (lieu) ou `"retour": false` (demande) l'empêche ;
- **accompagner** : au départ, le visiteur est la personne vue au LiDAR la plus proche du robot, à moins de 2,5 m (`DISTANCE_VISITEUR_DEPART_M`), dans les 3 s (`DELAI_VISITEUR_DEPART_S`) ; si personne, événement `seul` et visite sans accompagnement. En route : visiteur à plus de `distance_ralentir_m` (2 m) → le guide ralentit (`/speed_limit`, `nav2_msgs/SpeedLimit` en pourcentage, `ralenti` × 100, événement `ralentir` une fois) ; à plus de `distance_attendre_m` (3,5 m), ou plus vu depuis 2 s → arrêt (annulation du moteur, jamais `/speed_limit` à 0, qui veut dire « sans limite » dans Nav2), `attente_visiteur` ; revenu dans les `delai_visiteur_s` (30 s) → `visiteur_retrouve`, reprise de l'itinéraire ; sinon `visiteur_perdu`, abandon propre, puis retour ;
- **perdu** : repérage `perdu` (relais) ou plus de TF map → base_link depuis 2 s → arrêt, `perdu`, événement `perdu` ; retrouvé dans les `delai_perdu_s` (30 s) → `retrouve`, reprise ; sinon `echec` (« Le robot est perdu depuis 30 s : replacez-le sur le point principal, puis « Repérer le robot » »), sans retour automatique. Cela remplace l'attente sans limite de la vague 3 ;
- **passant qui bouche** : `attente_passage` (11.3), `passant_gene`, puis `passage_libre` s'il s'écarte, ou `detour` après `delai_passant_s` ;
- **verrou** : si `/mouvement/maitre` dit `pilotage`, `/guide/aller` est refusé (`echec`, événement `pilotage`, aucun mouvement) ; `/guide/stop` est toujours accepté.

**Délais** (`DELAIS_GUIDE`, section facultative `guide` de `lieu.yaml`, puis paramètres ROS du nœud guide, `reglages_guide(lieu, **parametres)`) : `retour_auto` (true), `delai_avant_retour_s` (15), `delai_visiteur_s` (30), `distance_ralentir_m` (2,0), `distance_attendre_m` (3,5, plus grand que la précédente), `ralenti` (0,5), `delai_perdu_s` (30), `delai_passant_s` (20).

**Détecteur de personnes au LiDAR** : nœud `detecteur_personnes` (`g1_nav/personnes.py`, exécutable déclaré), propriétaire **l'agent C**. Entrée `/points` (repère `lidar`, base_link par TF) ; sortie `/personnes/lidar` (schéma `personnes`, `source: lidar`, 10 Hz) : groupes de points dans la tranche 0,8–1,8 m, de 0,25 à 0,8 m de large, suivis d'un message à l'autre (`id`), avec vitesse, `derriere` pour |angle| > 90°. Il voit aussi derrière le robot (le visiteur), car le MID-360 voit tout autour. Lancé par `navigation.launch.py` (argument `personnes:=true|false`, défaut true).

**Faux visiteur de la simulation** : nœud `faux_visiteur` (`g1_nav/faux_visiteur.py`, exécutable déclaré), propriétaire **l'agent C**. Il conduit le piéton `pilote: externe` désigné par la scène (`visiteur`) par `/pietons/consigne`, en lisant sa position sur `/pietons/etat` et celle du robot (vérité). Il réutilise donc le corps, la collision et la visibilité au LiDAR du mécanisme de l'agent B. Modes sur `/faux_visiteur/mode` (std_msgs/String) : `suivre` (1,2 m derrière le robot, à sa vitesse), `trainer` (0,15 m/s : il se laisse distancer), `partir` (1,0 m/s, à l'opposé, jusqu'à sortir de la vue du robot), `arreter`. Scènes `atelier/monde/scenes/accompagnement*.scene.yaml` (agent C). En attendant le nœud `pietons`, l'agent C se sert d'un bouchon de `/personnes/lidar` dans ses tests sans Gazebo.

### 11.5 D. Le pilotage (agent Pilotage et danses)

**Paquet `ws/src/g1_pilotage`** (ament_python, livré vide et compilé), exécutable `pilote`, nœud `pilotage`. Dépendances : rclpy, std_msgs, geometry_msgs, unitree_api, unitree_hg ; Python : tornado, `atelier.lieu` (copié dans l'image). Logique sans ROS testée finement (horloge injectable), comme le pont.

| Sujet | Type | Sens | Rôle |
|---|---|---|---|
| `/api/sport/request`, `/api/arm/request`, `/api/voice/request` | unitree_api/msg/Request | sortie | ordres aux services sport, arm et voice, remplis comme le pont (identity croissante, lease 0, priorité 0) |
| `/api/sport/response`, `/api/arm/response`, `/api/voice/response` | unitree_api/msg/Response | entrée | réponses, appariées par `identity.id` (écoutées en best_effort) |
| `/arm_sdk` | unitree_hg/msg/LowCmd | sortie | bras des chorégraphies (rt/arm_sdk), 50 Hz pendant une chorégraphie seulement |
| `/lowstate` | unitree_hg/msg/LowState | entrée | angles mesurés (départ des bras, taille tenue) |
| `/mouvement/maitre` | std_msgs/String (JSON, schéma `maitre_mouvement`), fiable, transient_local, profondeur 1 | sortie | verrou des mouvements ; publié par ce nœud seulement |
| `/pilotage/etat` | std_msgs/String (JSON, schéma `etat_pilotage`) | sortie | 2 Hz et à chaque changement |
| `/guide/stop` | std_msgs/Empty | sortie | quand il prend la main de force, et à chaque ARRÊT |
| `/guide/etat`, `/pont/etat` | std_msgs/String | entrée | pour refuser de prendre la main pendant une visite |

Lancement : dans le conteneur, `G1_PILOTAGE=1` (défaut en mode robot) fait lancer `pilote` par `docker/demarrer.sh` à côté de la navigation ; en simulation et en répétition, la route `POST /api/pilotage/demarrer` du serveur le lance sur le PC (rôle `pilotage` du gestionnaire de processus) et `POST /api/pilotage/arreter` l'arrête. L'API HTTP du nœud et celle de l'Atelier (`/api/pilotage/…`, `/ws/pilotage`) sont celles de l'agent D, qui les documente dans `g1_pilotage/LISEZMOI.md`.

**Image du conteneur** : l'agent D a `docker/` pour cette vague. Il y ajoute `unitree_hg` (compilé comme `unitree_api`), `g1_pilotage` (`PAQUETS_WS` de `docker/jetson.py`), `python3-tornado`, et le lancement `G1_PILOTAGE` ; les critères 16, 17, 19 et 20 doivent toujours passer.

**Commandes permises et interdites** (`atelier.lieu.pilotage.refus_commande` et `confirmation_requise`, livrées ; le nœud et l'Atelier s'en servent tous deux) :

| Service, api | Permis | Confirmation |
|---|---|---|
| sport 7001 à 7006 | lectures (`GetFsmId`…) | — |
| sport 7101 `SetFsmId {"data"}` | postures 500 (démarrer), 706 (accroupi ↔ debout), 702 (se lever depuis couché), 3 (s'asseoir) | — |
| | 1 (amortir), 0 (couple nul) | **« portique »** : confirmation double (un premier appel rend un jeton, le second doit venir dans les 10 s avec ce jeton) et case « robot au portique » cochée |
| | danses 550000 + n, sauf **401, 402, 403** (toujours refusées) et toute danse absente de la liste du robot | **« zone_libre »** : « zone libre de 2 à 3 m autour du robot » |
| sport 7105 `SetVelocity` | marche plafonnée (`LIMITES_MARCHE` = 0,4 ; 0,25 ; 0,6, baissés par `G1_VITESSE_MAX`), `duration` 0,5 s au plus ; l'arrêt `[0, 0, 0]` (1 s au plus) | — |
| sport 7106 `SetTaskId` | 0, 1 (saluer), 2, 3 (serrer la main) | — |
| sport 7100 | seulement la liste des danses `{"fsm_id": 550, "api_id": 1}` | — |
| sport 7102, 7103, 7104, 7107, 7110, 7111 | **interdits** (équilibre, pas, hauteur, mode de vitesse, passage en commande utilisateur) | — |
| arm 7106 `{"action_id"}` | gestes `GESTES_BRAS` : 99 relâcher, 11, 12, 13 (à vérifier), 15, 17 à 27 | — |
| arm 7107, 7113 ; 7108 `{"action_name"}` | liste des gestes ; gestes appris (à vérifier) | — |
| voice 1001 TTS, 1004, 1005, 1006 volume (0–100), 1010 LED (0–255) | permis | — |
| tout le reste, `rt/lowcmd`, mode debug, politique corps entier | **interdit** | — |

Refus du robot traduits en français (`CODES_REFUS`) : 7301, 7302, 7303, 7400 (rt/arm_sdk occupé), 7401 (bras tenus : relâcher avec 99), 7402, 7404 (pas en 500, 501 ou 801), 3203, 3204, 3104.

**Joystick, avec un homme mort** : la page envoie l'ordre `{vx, vy, wz}` toutes les 0,1 s (`PERIODE_JOYSTICK_S`) par le WebSocket tant que le manche est tenu ; le nœud envoie un 7105 de 0,5 s (`DUREE_ORDRE_S`) à chaque ordre ; sans ordre depuis 0,5 s (`DELAI_HOMME_MORT_S`), il envoie StopMove (`[0, 0, 0]`, 1 s) ; quand le WebSocket se ferme (page fermée, Wi-Fi coupé, Atelier arrêté), StopMove tout de suite. Le robot est arrêté au plus 0,6 s (`ARRET_MAX_S`) après le dernier ordre ou la coupure. Le relais de l'Atelier n'envoie jamais d'ordre de lui-même : il ne fait que transmettre (une coupure entre l'Atelier et le nœud arrête aussi le robot).

**Le verrou entre pilotage et guide** : un seul maître des mouvements à la fois, **l'arrêt toujours permis**.
- `/mouvement/maitre` absent ou `guide` : le pont suit `/cmd_vel`, le guide accepte `/guide/aller` ; le pilotage refuse joystick, postures, gestes, danses et chorégraphies (409 « Prenez la main dans l'onglet Pilotage ») ; LED et voix restent permises ;
- « Prendre la main » : refusé (409) si le guide est en mission (`ETATS_EN_MISSION`) ; avec `forcer`, le pilotage envoie `/guide/stop`, attend le robot immobile, puis publie `maitre: pilotage` ;
- `maitre: pilotage` : le pont ignore `/cmd_vel` (nouvel état `pilotage`, `mouvement_permis` faux, un StopMove s'il bougeait ; agent D dans `g1_bridge`) ; le guide refuse `/guide/aller` (11.4, agent C) ;
- « Rendre la main » : `maitre: guide` ; le robot reste immobile jusqu'à la prochaine demande ;
- ARRÊT (`POST /arret` du nœud, bouton de l'onglet) : toujours permis, quel que soit le maître : StopMove, chorégraphie arrêtée (poids des bras ramené à 0 en 1 s), geste relâché (99), `/guide/stop`. Pendant une **danse du robot**, aucun ordre connu ne l'interrompt (`FSM_ARRET_DANSE` = None) : ARRÊT envoie StopMove et l'onglet rappelle que la télécommande reste l'arrêt d'urgence (à vérifier sur le robot).

**Danses du robot** (source communautaire non officielle, et `GetMimicMotion` du SDK C++, `g1_loco_client.hpp`) : liste par 7100 `{"fsm_id": 550, "api_id": 1}`, réponse `{"fsm_id": 550, "api_id": 1, "motion": {"604": {"name", "duration"}, …}}` (`lire_liste_danses` lit aussi la forme sans `motion`) ; lecture par 7101 `{"data": 550000 + n}`, robot debout immobile en mode 801, retour seul en 801 ; 2 à 3 m libres (les pieds bougent). Essayées par l'auteur : 602, 603, 604 ; non essayées : 502, 503, 504, 605, 574. Pendant une danse : joystick, gestes et chorégraphies refusés.

**Chorégraphies « K-pop » sûres** : un fichier par chorégraphie, `~/robot-g1/choregraphies/<id>.choregraphie.yaml` (schéma `choregraphie`), musique dans `choregraphies/musique/` (ignoré par Git : **aucune musique protégée dans le dépôt**). Une ligne de temps (s) :
- `bras.poses` : poses clés des 14 articulations des bras (`ARTICULATIONS_BRAS`, index 15 à 28 du G1 29 ddl), interpolation `douce` (cosinus) ou `lineaire`, départ et fin à la pose de repos (tous les angles à 0, `init_pos` de l'exemple d'Unitree) ; poids de rt/arm_sdk (`motor_cmd[29].q`, kNotUsedJoint) de 0 à 1 pendant `rampe_s` (1 s au moins) au début, de 1 à 0 à la fin ; angles dans `LIMITES_BRAS` (URDF `g1_29dof_rev_1_0` moins 0,05 rad) ; vitesse de chaque articulation 1,5 rad/s au plus (`VITESSE_BRAS_MAX`, au plus fort de l'interpolation) ; 50 Hz, kp 60 et kd 1,5 (exemple `g1_arm_sdk_dds_example.cpp`) ; la taille (12 à 14) est tenue à sa position mesurée au départ (gains ×4, comme l'exemple), jamais pilotée ; les jambes ne sont jamais écrites ;
- `pas` : pas de marche d'Unitree (7105), |vx| ≤ 0,3, |vy| ≤ 0,2, |wz| ≤ 0,6, de 0,2 à 2 s, sans chevauchement ; le robot reste à 1 m au plus de son départ (`DEPLACEMENT_MAX_M`), rotation cumulée 2π au plus ;
- `gestes` (arm 7106, interdits avec des poses de bras : 7400), `led` (1010), `paroles` (par `/robot/dire`, voix de l'équipe ; `voix: unitree` : TTS 1001) ;
- `musique` : `fichier` fourni par l'utilisateur, ou `battement` généré (`bpm`) ; `sortie: navigateur` (la page joue la musique, calée sur le départ annoncé par le nœud) ou `robot` (lecture 1003, à vérifier) ;
- `zone_libre_m` ≥ 2 : confirmation « zone libre » avant de jouer.
`verifier_choregraphie` (livrée) vérifie tout cela ; `poses_bras(d, t)` et `segments_bras(d)` donnent l'interpolation (le nœud et l'aperçu 3D la suivent). Exemple livré : `exemple_kpop` (24 s, battement à 120 temps par minute, bras à 1,41 rad/s au plus, 0,15 m de pas de côté et un quart de tour aller-retour). L'onglet Pilotage montre un **aperçu 3D** de la chorégraphie (three.js, modèle simplifié du G1), avant de la jouer.

**Faux G1 étendu** (`g1_jumeau`, agent D) : en plus de 7105, une machine d'états des modes (0, 1, 3, 500 puis 801, 702, 706 ; 7001 rend le mode), refus réalistes (7301 pour marcher hors de 500/801, 7302 pour un mode inconnu, **7404** pour un geste hors de 500/501/801, **7401** pour un autre geste pendant que les bras tiennent le précédent, 99 les relâche), la **liste 7100** (602, 603, 604, 574 et aussi 401, 402, 403, pour éprouver les refus) et la lecture d'une danse (durée, retour en 801, refus de 7105 pendant la danse), la **liste 7107**, les services `arm` et `voice` (`/api/arm/*`, `/api/voice/*`, réponses conformes au SDK, dernières valeurs gardées : TTS, volume, LED), **rt/arm_sdk reçu et vérifié** (poids, rampes, limites, vitesses, articulations écrites ; tout écart compté dans `/g1_jumeau/etat`) et un `/lowstate` simulé (bras qui suivent les ordres pondérés). `g1_sim` continue de lancer `g1_jumeau` avec les mêmes arguments.

### 11.6 E. L'équipe (agent Équipe)

**Fichiers du lieu**, facultatifs (un lieu s'en passe), avec leurs schémas et des exemples (`atelier/lieu/exemples/`) ; lecture, écriture et vérification par `atelier.lieu.equipe` (livré : `charger_equipe`, `enregistrer_equipe`, `valider_equipe`, `exemple_equipe`) :
- `personnalites.yaml` : `{version, active, personnalites: [{id, nom, salutation, description?, voix?, led?, geste_salut?, vitesse_max?, phrases?}]}` ; `phrases` remplace les textes des événements du guide, par code ; ids uniques, `active` parmi eux ;
- `dialogues.yaml` : `{version, langue?, repli, regles: [{id, motifs, action, reponse, accompagner?, personnalite?}]}` ; les motifs se comparent sans majuscules, accents ni ponctuation ; `{salle}` vaut une salle (id, nom ou alias de `salles.yaml`), `{*}` n'importe quels mots ; la première règle qui correspond l'emporte ; actions `guider` (`{salle}` dans chaque motif), `dire`, `personnalite`, `stop` ;
- `camera.yaml` : `{version, camera: {modele?, peripherique, largeur, hauteur, ips, champ_horizontal_deg?, position}, detection: {actif, modele?, confiance_min, distance_max_m, frequence_hz}}` ; `position` dans base_link, à mesurer sur le robot.

**Onglets** « Personnalités », « Dialogues » et « Caméra » (livrés vides, après Scan et Pilotage) : éditer chaque fichier ; choisir la personnalité active (publiée sur `/personnalite/active`) ; essayer une phrase dans l'onglet Dialogues (réponse et action, sans robot) ; voir la caméra et ses détections quand un nœud de l'équipe les publie.

**Sujets entre les parties** (`SUJETS_EQUIPE`) :

| Sujet | Type | De → vers | Rôle |
|---|---|---|---|
| `/visiteur/texte` | std_msgs/String (texte brut) | reconnaissance vocale de l'équipe → chatbot | ce que le visiteur a dit |
| `/visiteurs/detectes` | std_msgs/String (JSON, schéma `personnes`, `source: camera`) | caméra de l'équipe → guide, personnalités | visiteurs vus par la See3CAM |
| `/personnalite/active` | std_msgs/String (JSON, schéma `personnalite_active`), fiable, transient_local | onglet, chatbot → voix, relais | la personnalité active |
| `/robot/dire` | std_msgs/String (JSON, schéma `robot_dire`) | chatbot, relais des événements, chorégraphies → voix de l'équipe | la seule entrée de la partie voix |
| `/guide/aller` | std_msgs/String (JSON, schéma `demande_guide`) | chatbot → guide | demande de guidage, `accompagner: true`, `source: dialogue` |
| `/guide/evenement` | std_msgs/String (JSON, schéma `evenement_guide`) | guide → relais | relayé vers `/robot/dire`, avec les `phrases` de la personnalité active |

Paquet `ws/src/g1_equipe` (livré vide et compilé, exécutable `dialogue`) : le nœud `dialogue` (règles du lieu, relais des événements), et ce qu'il faut de bouchons pour essayer sans l'équipe (fausse caméra, voix qui écrit dans le journal). Logique sans ROS dans `atelier/equipe/` (le chatbot, aussi utilisé par l'onglet Dialogues).

**Document** `docs/integration-equipe.md` (agent E), pour les coéquipiers : les trois fichiers, les sujets, comment brancher la See3CAM, le chatbot et la voix, comment essayer sans robot, et l'exemple ci-dessous.

**Exemple de bout en bout** : « je cherche la salle b204 » publié sur `/visiteur/texte` → le nœud `dialogue` trouve la règle `chercher_salle` → `/robot/dire` « Je vous emmène à Salle B204. Suivez-moi ! » et `/guide/aller` `{"cible": "b204", "accompagner": true, "source": "dialogue"}` → le guide part (événement `depart`, ou `seul` sans visiteur vu) et arrive à b204.

### 11.7 Les agents de la vague 4 et leurs fichiers

Aucun fichier n'a deux propriétaires. Un agent n'écrit que dans ses fichiers ; s'il a besoin d'un changement ailleurs, il le note dans le journal (« demandé à l'intégrateur ») et fait sans, avec un bouchon.

| Agent | Domaine | Possède (seul à y écrire) |
|---|---|---|
| Intégrateur | — | le plan (sections 1 à 11) ; `atelier/lieu/` sauf les modules des agents ci-dessous (donc schémas, `validation.py`, `verification.py`, `modeles.py`, `fichiers.py`, `robot.py`, `conversions.py`, `scans.py`, `__init__.py`, `exemples/`) ; `atelier/tests/test_contrats*.py` ; `atelier/web/index.html`, `js/app.js`, les modules communs `js/{api,contexte,direct,formulaire,geometrie,historique,messages,plan,vue3d,teleop,nuage3d}.js`, `css/atelier.css` ; `atelier/serveur/main.py`, `pont_ros.py`, `etat.py`, `communs.py`, `processus.py` ; `atelier/web/LISEZMOI.md`, `atelier/serveur/routes/__init__.py` ; `ws/src/g1_nav/g1_nav/moteurs.py` ; `tests_e2e/tout.sh`, `LISEZMOI.md`, `commun.sh` ; `.gitignore`, `README.md`, `setup.py` et `pytest.ini` de la racine ; `lieux/demo` ; assemblage |
| A. Point principal | 71 (`robot_71`) | `atelier/lieu/principal.py`, `atelier/lieu/commande.py` (`g1-lieu migrer`) ; `atelier/serveur/routes/principal.py`, `routes/plan.py`, `routes/robot.py`, `routes/lieux.py` ; `atelier/web/js/ecrans/salles.js`, `ecrans/simulation.js`, `ecrans/monde.js`, `css/principal.css` ; dans `atelier/scan/commande.py`, l'appel à `synchroniser_depart` après `adopter --monde`, seulement ; `lieux/bomboclat` et `lieux/demo_scan` (migration avec sauvegarde) ; tests `atelier/tests/test_principal*.py`, et les tests existants de ses fichiers : `test_robot_serveur*.py`, `test_robot_navigateur.py`, `test_serveur_api.py`, `test_lieu_commande.py` ; `tests_e2e/critere_21_*` (et ses outils `critere_21_outils.py`), `critere_18_reperage.sh`, `critere_18_outils.py` |
| B. Passants | 72 (`robot_72`) | `ws/src/g1_sim/` (tout : nœud `pietons`, argument `pietons`, modèles, tests) ; `atelier/monde/` (tout : sdf, pietons, scene, commande, carte, zones) et `atelier/monde/scenes/` sauf accompagnement* ; `atelier/lieu/passants.py` ; dans g1_nav : `ws/src/g1_nav/g1_nav/banc.py`, `ws/src/g1_nav/config/nav2_g1_simu.yaml`, `ws/src/g1_nav/config/nav2_g1_reel.yaml`, `ws/src/g1_nav/test/test_banc.py`, `ws/src/g1_nav/test/test_reglages.py` ; `bin/g1-banc` ; `atelier/serveur/routes/passants.py`, `atelier/serveur/pietons.py` ; `atelier/web/js/panneaux/passants.js`, `css/passants.css` ; tests `atelier/tests/test_passants*.py`, `test_monde_*.py` ; `tests_e2e/critere_06_foule.sh`, `critere_23_*` à `critere_25_*`, `tests_e2e/outils_passants_e2e.py` |
| C. Comportement du guide | 73 (`robot_73`) | `ws/src/g1_nav/` sauf moteurs.py et les fichiers de B (donc guide, routeur, personnes, faux_visiteur, moteur_nav2, odom_vers_tf, reperage, nuages, commande, moteur_unitree, `ws/src/g1_nav/launch/navigation.launch.py`, `ws/src/g1_nav/config/amcl_g1.yaml`, `ws/src/g1_nav/setup.py`, `ws/src/g1_nav/package.xml`, et leurs tests) ; `atelier/lieu/comportement.py` ; `atelier/serveur/routes/guide.py`, `routes/simulation.py` ; `atelier/web/js/panneaux/guide.js`, `css/guide.css` ; `atelier/monde/scenes/accompagnement*.scene.yaml` ; tests `atelier/tests/test_guide*.py` ; `tests_e2e/critere_22_*`, `critere_26_*`, `critere_27_*`, `tests_e2e/outils_guide_e2e.py`, et les critères existants qui suivent le guide s'il faut les adapter (4, 5, 19) |
| D. Pilotage et danses | 74 (`robot_74`) | `ws/src/g1_pilotage/`, `ws/src/g1_jumeau/`, `ws/src/g1_bridge/` (tout) ; `docker/` (tout), `bin/g1-jetson`, `bin/gl-jetson`, et les nouvelles commandes `bin/g1-pilotage`, `bin/gl-pilotage` ; `atelier/lieu/pilotage.py` ; `choregraphies/` ; `atelier/serveur/routes/pilotage.py` ; `atelier/web/js/ecrans/pilotage.js` et ses nouveaux modules (`js/pilotage/*.js` : joystick, aperçu 3D, chorégraphie), `css/pilotage.css` ; tests `atelier/tests/test_pilotage*.py` ; `tests_e2e/critere_28_*`, `critere_29_*`, `tests_e2e/outils_pilotage_e2e.py`, et les critères 16, 17, 20 et leurs outils s'il faut les adapter ; `docs/jetson.md`, `docs/seance-robot.md` (ajouts du pilotage) |
| E. Équipe | 75 (`robot_75`) | `atelier/lieu/equipe.py` ; `atelier/equipe/` ; `ws/src/g1_equipe/` (tout) ; `atelier/serveur/routes/equipe.py` ; `atelier/web/js/ecrans/personnalites.js`, `ecrans/dialogues.js`, `ecrans/camera.js` et leurs nouveaux modules (`js/equipe/*.js`), `css/equipe.css` ; `docs/integration-equipe.md` ; tests `atelier/tests/test_equipe*.py` ; `tests_e2e/critere_30_*`, `tests_e2e/outils_equipe_e2e.py` |

Fichiers que personne ne touche dans cette vague (tous les agents s'en servent) : `atelier/scan/` (sauf l'appel de A), `atelier/web/js/ecrans/{lieux,carte,itineraires,zones,scan}.js`, `css/scan.css`, `atelier/serveur/routes/{monde,scan}.py`, les autres commandes de `bin/`, `tests_e2e/critere_01` à `critere_15`, `outils_e2e.py`, `outils_scan_e2e.py`, `outils_pont_e2e.py`, `critere_16_outils.py`, `critere_19_outils.py`, `critere_20_outils.py` (sauf adaptation par D de ceux du pont, ou par C du critère 19). Un nouveau fichier de test ou d'outil porte le préfixe de son agent.

### 11.8 Dépendances entre agents : contrats et bouchons

| Qui a besoin | De quoi | Chez qui | Contrat | En attendant |
|---|---|---|---|---|
| C | le principal (retour, cible `principal`) | A | `point_principal`, `pose_principale` (livrés) | — |
| C | le corps du visiteur dans Gazebo | B | `pilote: externe`, `/pietons/consigne`, `/pietons/etat` | bouchon de `/personnes/lidar` dans les tests sans Gazebo ; critère 26 « en attente » (77) sans le nœud `pietons` |
| B | l'attente du passant (critère 25) | C | état `attente_passage`, événement `passant_gene`, `delai_passant_s` | critère 25 « en attente » (77) tant que le guide ne connaît pas `attente_passage` ; scènes et mesures prêtes |
| C | le verrou des mouvements | D | `/mouvement/maitre` (schéma, QoS) | publier un faux message dans les tests |
| D | refuser de prendre la main pendant une visite | C | `ETATS_EN_MISSION` de `/guide/etat` | un faux `/guide/etat` dans les tests |
| E | le guidage JSON | C | `/guide/aller` JSON (passerelle livrée : la cible) | la passerelle suffit pour l'exemple de bout en bout |
| E | les textes des événements | C | `/guide/evenement`, `CODES_EVENEMENT` (livrés) | publier de faux événements |
| A | l'image du conteneur | D | aucune (A ne touche pas `docker/`) | — |
| D | `/robot/dire` pour les paroles des chorégraphies | E | schéma `robot_dire` (livré) | publier sans écouteur |

### 11.9 Critères de recette 21 à 30

Ils sont dans la section 7 (ce qu'on mesure, le seuil, et qui écrit le script) ; `tests_e2e/tout.sh` les lance et affiche « N / 30 ». Un critère dont une pièce d'un autre agent manque répond « en attente » (77) en disant laquelle. Les critères 1 à 20 doivent toujours passer : chaque agent relance ceux qu'il peut casser (A : 1, 4, 9, 13, 18, 19 ; B : 2, 3, 5, 6, 7 ; C : 4, 5, 8, 19, 20 ; D : 16, 17, 19, 20 ; E : 9, 10).

### 11.10 Règles communes de la vague 4

Celles des sections 9.9 et 10.10, plus :
- domaines et partitions : A 71 (`robot_71`), B 72, C 73, D 74, E 75, y compris dans les conteneurs ; les critères se lancent avec `E2E_DOMAINE` et `E2E_PARTITION` ; ports du serveur et du nœud pilotage : libres, choisis par les tests ;
- compilations dans `ws/build_<agent>` et `ws/install_<agent>` (avec `--log-base log_<agent>`), jamais dans `ws/build` ni `ws/install` ; `tests_e2e/commun.sh` charge en repli `ws/install_<paquet>` pour `g1_sim`, `g1_nav`, `g1_bridge`, `g1_jumeau`, `g1_pilotage` et `g1_equipe` ;
- **jamais rien sur eno2, jamais de ssh vers 192.168.123.x** ; le pilotage ne s'essaie que contre le faux G1 ;
- `lieux/bomboclat` est à l'utilisateur : seul l'agent A y écrit, pour la migration, avec la sauvegarde et un test ; `lieux/demo` est la référence des tests : personne n'y écrit (on travaille sur des copies : `ATELIER_LIEUX`, `copier_demo`) ;
- jamais de mouvement non voulu : plafonds, homme mort, confirmations et verrou sont testés avant tout le reste ;
- à la fin : tous les processus et conteneurs arrêtés (`ps`, `docker ps -a`), tests réels sans écran ni robot rapportés honnêtement, une section dans `docs/journal-atelier.md` avec ce qui reste à vérifier sur le robot.

### 11.11 Ce qui reste à vérifier sur le robot (vague 4)

En plus de la liste de 10.9, robot au portique et télécommande en main :
1. **point principal** : robot posé sur le principal dans le sens de la flèche, « Repérer le robot » : 1804 avec la pose convertie, écart au mètre ruban ; le principal loin de l'origine du scan, et tourné ;
2. **pilotage** : le service `sport` accepte nos 7101 (postures 500, 706, 702, 3) depuis le conteneur, sans bail ; temps de chaque transition ; la télécommande reste prioritaire et arrête tout ;
3. amortir (1) et couple nul (0) : **seulement au portique**, robot tenu ;
4. joystick : arrêt seul 0,5 s après le dernier ordre (Wi-Fi coupé exprès, page fermée), latence par le Wi-Fi, plafonds ;
5. le format des gestes : `{"action_id": n}` (SDK C++) ou `{"data": n}` (SDK Python) ; codes 7400, 7401, 7402, 7404 réels ; geste 13 ; gestes appris (7108) ;
6. TTS 1001 (langue, `speaker_id`), volume, LED 1010 (format `{"R","G","B"}`) ;
7. **danses** : la liste 7100 (format exact, ids présents sur ce micrologiciel), 7101 550604 au portique d'abord, durée, retour en 801, comportement si on envoie un 7105 ou un autre 7101 pendant la danse, et **ce qui interrompt une danse** ; 401, 402, 403 jamais essayées ;
8. **rt/arm_sdk** : le poids dans `motor_cmd[29].q`, les rampes, la tenue de la taille (12 à 14), les gains (kp 60, kd 1,5), la vitesse réelle des bras, la reprise par le contrôleur à la fin ; d'abord une pose lente au portique, puis l'exemple K-pop à mi-vitesse ;
9. musique sur le haut-parleur du robot (1003) : format du flux ;
10. **passants** : `voxel_layer` et Collision Monitor avec le MID-360 réel (obstacles bas, jambes, sacs), distances aux personnes et ralentissement au milieu de vraies personnes, avec des volontaires ; le détecteur de personnes au LiDAR sur de vraies personnes (et derrière le robot) ;
11. **guide** : retour au principal sur une vraie carte, accompagnement avec un vrai visiteur, délai et message quand le repérage se perd ;
12. **équipe** : la See3CAM (périphérique, position réelle dans base_link), le chatbot et la voix sur le Jetson ou le PC.
13. **vue du robot** (11.13) : la vidéo de la tête par le service videohub (GetImageSample, api 1001), son débit par le Wi-Fi, et la vue 3D comparée au vrai robot.

### 11.12 Précisions de l'assemblage (vague 4)

Acceptées par l'intégrateur le 26/10/2026. Elles complètent les sections 11.1 à 11.11 et font foi comme elles.

**Compilation.** Les huit paquets de `ws/src` (`livox_ros_driver2`, `fast_lio`, `g1_sim`, `g1_nav`, `g1_bridge`, `g1_jumeau`, `g1_pilotage`, `g1_equipe`) sont compilés dans `ws/install` (`cd ~/robot-g1/ws && colcon build --symlink-install`), vus par `setup/env.sh`. Les dossiers `ws/build_*`, `ws/install_*` et `ws/log_*` des agents sont retirés. L'image du Jetson contient aussi `g1_equipe` et `atelier/equipe/` (nœuds de l'équipe disponibles, non lancés d'office). `python3-tornado` est dans la liste d'`installer_pc_root.sh`.

**A. Point principal (11.2).**
- Onglet Salles : la flèche du principal se tourne dans la page (pas de 15°) et s'enregistre avec « Enregistrer les salles » (`PUT …/salles?synchroniser=true`, même effet que `PUT …/principal {theta}`) : un seul mode d'enregistrement par onglet.
- Onglet Monde : l'outil « Départ du robot » reste (le parcours du critère 9 s'en sert) ; à l'enregistrement du monde, le principal le suit (`PUT …/principal`) ; à l'ouverture, un départ différent du principal y est remis, avec un message.
- `PUT …/salles` refuse aussi de perdre un principal implicite (supprimer la salle `accueil` d'un lieu non migré). `definir_principal` pose toujours l'étiquette (le lieu devient explicite) ; `PUT …/salles?synchroniser=true` laisse un lieu implicite tel quel.
- API : `principal` dans `GET /api/lieux/{id}` ; `PUT /api/lieux/{id}` garde `accueil` sur le principal ; `etage` dans le `principal` de `/api/robot/etat` ; `changements` et `avertissement` dans la réponse de `PUT …/principal` ; `GET …/principal` répond 404 sans principal ; `PUT …/principal` répond 400 à une demande vide, à `x` sans `y` ou à un nombre absurde.
- Sauvegardes : un `LISEZMOI.txt` (comment revenir en arrière) à côté des copies ; seules les lignes `accueil`, `depart_robot` et `etiquettes` sont réécrites quand c'est possible (les commentaires écrits à la main restent) ; quand seul `depart_robot` change, la date du `.sdf` et de la carte avance (pas de « monde à refabriquer » pour un principal déplacé). `migrer_lieu` ne refuse que le vrai `lieux/demo`, reconnu par son chemin.
- `synchroniser_depart` est appelé par `adopter` de `atelier/scan/session.py` (l'adoption avec `--monde` est là, et non dans `commande.py`), et par `POST /api/simulation/demarrer` (agent C), qui avertit en citant l'ancienne pose.
- Textes : « point principal » partout où l'Atelier parlait de la marque au sol ; la marque au sol (origine de la carte d'Unitree) ne reste que le repli d'un étage sans principal, et le défaut du relais pour une demande sans pose.

**B. Passants (11.3).**
- Piétons-corps : nœud `pietons` de `g1_sim` (`scripts/pietons.py`, pont `pont_pietons`), argument `pietons:=corps|acteurs` ; rayons du LiDAR du robot proxy décalés d'un demi-degré (coutures du gpu_lidar de Fortress, qui donnaient des points fantômes). Un piéton `ecart` qui ne peut pas passer à côté du robot avec 0,15 m de marge (`MARGE_PASSAGE_M`) n'avance plus et attend, 8 s au plus (`ATTENTE_ROBOT_MAX_S`), puis passe.
- Réglages de Nav2 (identiques dans `nav2_g1_simu.yaml` et `nav2_g1_reel.yaml`, sauf les vitesses et l'horloge) : carte locale de 7 × 7 m ; `voxel_layer` de 0,15 à 1,9 m, deux sources qui marquent (`points` 1,125–1,9 m, `points_bas` 0,15–1,125 m) et une qui efface (−0,5 à 2,5 m) ; inflation locale 0,9 m, `cost_scaling_factor` 4 ; carte globale : couche `voxel_layer` « personnes » de 1,375 à 1,9 m, 5 m au plus (une boîte, une table ou un comptoir de 1,2 m n'y entrent pas) ; `robot_radius` 0,35 m. **Collision Monitor** : le cercle « ralentir » de 1 m est remplacé par deux zones à ×0,5, `ralentir` (demi-disque de 1 m devant, polygone de 13 sommets) et `ralentir_pres` (cercle de 0,7 m tout autour) ; `arret` (0,4 m) inchangé.
- `g1-banc` : options `--scene`, `--reaction`, `--pietons`, `--verite`, `--travail` ; robot reposé et piétons remis au début avant chaque essai.
- Scène `groupe_couloir` : les pauses du groupe passent de 50 / 51,5 / 53 s à 47 / 48 / 49 s depuis le départ du robot (le groupe part toujours « environ 15 s après que le robot est arrivé devant lui » ; avec 53 s, le dernier partait 17 à 18 s après le début de l'attente, trop près des 20 s de `delai_passant_s`).

**C. Comportement du guide (11.4).**
- **Passant qui bouche (critère 25), décision de l'assemblage** : `DISTANCE_PASSANT_M` vaut **2,5 m** (et non 1,5 m) ; « devant » est le cône de ±60° autour de l'avant du robot **ou de la direction du couloir de l'itinéraire** ; pendant `attente_passage`, **le robot est arrêté** (le moteur est annulé). Raisons, mesurées par l'agent Passants : Nav2 arrête le robot vers 2,4 m d'un groupe qui bouche le couloir (les personnes sont dans la carte globale), le fait pivoter vers l'autre couloir, et contournerait le groupe de lui-même si on le laissait faire. Le passage est libre quand, depuis 1,5 s, plus personne n'est vu à moins de 3,0 m dans ces cônes, sauf qui s'éloigne du robot à plus de 0,3 m/s (vitesse de `/personnes/lidar`) : le trajet reprend (« Merci ! » après un « Pardon »). Sinon, détour après `delai_passant_s`. Les personnes restent dans la carte globale (passer à côté d'un passant immobile).
- Ralenti du visiteur : `/speed_limit` reste en pourcentage de `vitesse_max_nav2`, mais vaut `ralenti` × la vitesse mesurée sur les 4 dernières secondes (entre 10 % et `ralenti` × 100), car le Collision Monitor freine déjà le robot quand le visiteur le suit de près. Critère 26 : la vitesse en ralenti est comparée à celle des 2 s qui précèdent le ralenti.
- **Personnalité active** : sa `vitesse_max` (m/s) devient un plafond de `/speed_limit` (`100 × vitesse_max / vitesse_max_nav2`) ; la limite envoyée est toujours la plus petite (visiteur qui traîne, personnalité). Le guide lit la personnalité active de `personnalites.yaml` au lancement, puis chaque `/personnalite/active` (fiable, transient_local) du même lieu.
- Retour : à l'arrivée au principal, rotation finale vers la flèche par la méthode facultative `tourner(angle)` du moteur (action Spin de Nav2), la tolérance de cap de Nav2 (0,4 rad) étant plus large que les 10° demandés.
- Réglages du nœud en plus de `DELAIS_GUIDE` (paramètres ROS seulement) : `accompagnement`, `passants`, `detour_facteur_max` (3,5), `detour_marge_m` (45), `vitesse_max_nav2` (donnée par `navigation.launch.py`). Un détour est refusé si le trajet total dépasse max(3,5 × le trajet direct ; trajet direct + 45 m) ; refusé à cause d'un passant, le guide attend encore (2 fois au plus), puis échoue.
- « Pardon, puis-je passer ? » au plus une fois toutes les 20 s ; « Merci ! » seulement après un « Pardon ». `visiteur_perdu` : la visite finit en `echec` sans l'événement `echec`, puis retour ; déjà au principal : pas d'annonce de retour. Événement `arret` seulement si quelque chose était en cours. `/guide/etat` porte aussi `retour_dans_s` quand un retour est prévu.
- `POST /api/guide/aller` pendant le pilotage : 200 avec un avertissement, et c'est le guide qui refuse (`echec`, événement `pilotage`).
- Faux visiteur : un pas de côté quand le robot revient vers lui, et `/faux_visiteur/etat` (essais). `g1-guide aller --accompagner --sans-retour`, `g1-guide navigation --sans-personnes`.

**D. Pilotage et danses (11.5).**
- Confirmations en HTTP 428 (champs `confirmation` et `jeton`) ; verrou et activités en cours en 409 ; interdits en 403 ; JSON strict (NaN et Infinity refusés en 400).
- `/pont/etat` n'a pas de champ `maitre` : l'état `pilotage` suffit. Le faux G1 répond comme le vrai robot (11.5), et non plus 3203 à toute api autre que 7105 (10.12) ; 3203 pour une api inconnue.
- `exemple_kpop` dure 29 s (et non 24 s). Vitesse de lecture d'une chorégraphie de 0,25 à 1 (jamais plus vite que prévu). Sans WebGL (Firefox sans fenêtre de ce PC), l'aperçu 3D est un squelette 2D en perspective des mêmes articulations. Pendant une danse, l'ARRÊT n'envoie que StopMove.
- `regles_choregraphie` refuse un segment des bras de durée nulle qui change d'angle (première pose collée à la fin de la rampe, ou dernière au début de la rampe de fin : les bras sauteraient d'un coup).
- Ajouts à l'API : `GET /api/pilotage/config`, `/modele`, `/modele/maillages/{nom}`, `/musique/{fichier}`, routes des chorégraphies (lister, lire, vérifier, écrire, supprimer, jouer), `POST /api/pilotage/requete` (mode avancé, mêmes règles) ; `g1-pilotage importer-video`.
- `g1-jetson demarrer` : `G1_PILOTAGE=1` avec le robot, 0 avec `--local` ; jeton créé une fois dans `opt/jetson/jeton_pilotage` (relu par l'Atelier) ; `G1_VITESSE_MAX` transmise aussi en veille.
- **Équipe, branché à l'assemblage** : le nœud pilotage écoute `/personnalite/active` et met la LED de la personnalité (voice 1010, toujours permise) ; il écoute `/robot/geste` (nouveau sujet, schéma `robot_geste`) et ne fait le geste que robot au repos (le guide a la main et n'est pas en mission, aucune danse, chorégraphie ni prise de main, bras libres), un toutes les 10 s au plus, puis relâche les bras (99) 5 s après.

**E. Équipe (11.6).**
- Les exemples restent dans `atelier/lieu/exemples/` (rien dans `lieux/demo`) ; chaque onglet a « Partir de l'exemple ». `GET` d'un fichier de l'équipe absent : 404 avec un message en français.
- Chatbot : deux passes (un motif qui couvre toute la phrase, puis un motif trouvé dans la phrase), avec deux gardes (un motif fait seulement de repères n'est essayé que sur toute la phrase ; une négation ne fait guider que si un motif la couvre en entier). Relais : les phrases de la personnalité remplacent celles du guide, sauf à l'arrivée dans une salle qui a sa propre `phrase_arrivee` ; le `depart` du guide est tu juste après la réponse du chatbot.
- Ajouts : routes `/api/equipe`, `/api/equipe/etat`, `/api/equipe/cameras`, `/api/equipe/visiteur`, `…/verifier`, `…/dialogues/essayer`, `…/personnalites/active` ; exécutables `fausse_camera` et `voix_journal`, sujet `/fausse_camera/mode`, paramètre `repondre` du nœud `dialogue`.
- **Ajouts de l'assemblage** : champ `voix.nom` d'une personnalité (la voix choisie, ex. `fr_FR-siwis-medium`) ; action `geste` des dialogues (champ `geste`, un geste de `GESTES_BRAS` sans 99), qui répond puis publie `/robot/geste`, sauf robot piloté à la main ou en visite ; le nœud `dialogue` publie aussi `geste_salut` sur `/robot/geste` quand il salue ; `SUJETS_EQUIPE` et `TYPES_MESSAGES` comptent `/robot/geste` (`robot_geste`) ; `verifier_lieu` appelle `verifier_equipe`, donc `g1-lieu valider` couvre les trois fichiers ; exemple `camera.yaml` : modèle `See3CAM_11CUG`, tangage −0,21 rad (12° vers le haut ; convention de ROS : positif = vers le bas, écrit dans le schéma), modèle de détection `yolo11n-pose.pt` (celui du PC).
- Critère 30 lancé sur une copie du demo sans piétons (avec l'accompagnement, un piéton près de l'accueil serait pris pour le visiteur ; les passants ont les critères 23 à 25).

**Tests stabilisés à l'assemblage.** `test_contrats_vague4.py::test_principal_fonctions_de_l_agent_pas_encore_ecrites` retiré (les fonctions sont écrites). `test_scan_session.py::test_arreter_session_interrompue_avec_enregistrement` : le traitement relancé écrit « termine » puis se ferme ; sous charge sa fin suivait de quelques secondes, le test lui laisse 30 s. `test_serveur_scan_teleop.py::test_teleop_limites_et_homme_mort` : délai de l'homme mort compté depuis la réception de la consigne (et non depuis l'appel à l'API) ; la phase « flèche appuyée » recommence (3 fois au plus) si le PC a espacé deux appels de plus de 0,45 s, ce qui déclenche à raison l'homme mort. Critères 5 et 19 : `pieton_nord` est retiré de leur copie du demo (`sans_pieton_nord` de `tests_e2e/commun.sh`) : son va-et-vient le long du couloir nord le faisait buter contre la boîte, posée dans Gazebo seulement ; collé à la boîte devant le robot, il ferait maintenant attendre le guide (`attente_passage`) au lieu de `bloque`.

### 11.13 La Vue du robot dans l'onglet Pilotage (26/10/2026)

Demande de l'utilisateur : en répétition, après « Démarrer le pilotage » et « Prendre la main », l'onglet Pilotage ne montrait rien du robot (gestes et danses du faux G1 invisibles, la marche seulement dans l'onglet Simulation). La **Vue du robot** s'affiche sous « Commandes » et « Danses du robot » (pas sous « Mes chorégraphies », qui a son aperçu), pliable (« Masquer la vue », retenu par le navigateur), en trois panneaux qui passent les uns sous les autres sur une tablette. **Elle ne commande rien** : aucune requête de mouvement ne part d'elle ; la barre (ARRÊT, Échap) reste en haut, collante.

**Carte** (`atelier/web/js/pilotage/vue_robot.js`) : `creerPlan`, `afficherFond`, `iconeOrientee` de `plan.js` et le WebSocket `/ws/etat` (`direct.js`), comme l'onglet Simulation : le lieu et l'étage de la simulation en cours (sinon ceux choisis), le robot (position de repérage en répétition et avec le robot, `/odom` en simulation), les passants ; suivi du robot (zoom 4,6, environ 24 pixels par mètre ; « Suivre le robot » après un glissé).

**Le G1 en 3D** : `Apercu3D` (maillages de l'URDF ; option `nomGlobal` : `window.vueRobot3d`, et cadrage de caméra réglable ; correction : `OrbitControls.update()` après le choix de la cible, sinon la caméra visait le sol), posé au sol (`poser(q, base, led, {sol: true})` : la semelle ou le dessous du bassin touche le sol). Les poses (`atelier/web/js/pilotage/poses_vue.js`) :
- posture d'après `fsm` (`/api/pilotage/etat`) : 500, 501, 702, 801 debout ; 706 accroupi ; 3 assis par terre ; 1 amorti ; 0 couple nul ; autre : debout, « mode inconnu » ; passage lissé (0,5 s) pendant 3 s après un changement ;
- marche quand `activite` vaut `marche` : jambes à 1,4 pas par seconde, amplitude selon la consigne `{vx, vy, wz}` rapportée aux limites de marche, pieds à plat (cheville = −(hanche + genou)), bras qui balancent ; la carte montre le déplacement ;
- gestes : les 16 gestes d'Unitree (`GESTES_BRAS` : 99, 11, 12, 13, 15, 17 à 27) et les 4 tâches (`TACHES_LOCO` 0 à 3), en **poses clés approchées** des bras (et de la taille pour 1), interpolées en cosinus, du départ affiché jusqu'au repos (la tâche 2, « tendre la main », est tenue jusqu'au geste suivant) ; légende « Aperçu approché : le vrai geste est dans le robot. » ;
- danse du robot (`danse` de l'état : id, nom, durée, écoulé) : barre de progression, nom et durée, et un mouvement générique en boucle (rebonds, balancement, bras), « Aperçu approché : la vraie danse est dans le robot. » ;
- chorégraphie en cours (`choregraphie` de l'état : id, t, vitesse) : le fichier lu par `GET /api/pilotage/choregraphies/{id}`, puis **les vraies poses** (`C.anglesVus`, `C.positionBase`, `C.couleurLed` : l'interpolation du nœud), sans lissage ; à l'arrêt, le poids des bras de l'état ramène les bras au repos.
Toutes les poses clés et les poses échantillonnées (gestes toutes les 0,05 s, danse sur 8 s, marche aux plafonds dans chaque posture) sont dans les limites de l'URDF moins 0,05 rad (vérifié par le test du navigateur), et la vue borne encore chaque angle aux limites de `/api/pilotage/modele` avant de dessiner. Rien n'est redessiné quand rien ne bouge.

**Geste en cours dans l'état du nœud** : champ facultatif `geste` de `/pilotage/etat` (schéma `etat_pilotage`) : `{numero, genre (bras | tache), id, nom, ecoule_s}`, pendant 10 s (`DUREE_GESTE_VU_S`) après l'envoi d'un geste ou d'une tâche (bouton, `/robot/geste` de l'équipe, relâchement automatique, ARRÊT qui relâche : 99), effacé si le robot le refuse. Avec un nœud plus ancien (sans ce champ), la page montre le geste qu'elle a elle-même demandé.

**Caméra de la tête** (voie choisie : la plus simple et la plus sûre) : le service `videohub` du robot, GetImageSample (api 1001, SDK Python `unitree_sdk2py/go2/video/video_client.py`), qui rend **un JPEG** dans le champ `binary` de la réponse (`/api/videohub/request` → `/api/videohub/response`, unitree_api). Jamais le flux H264 de `/frontvideostream` (il charge le réseau même quand personne ne regarde, et il faudrait le décoder). Contrat (`atelier.lieu.pilotage`) : `SERVICE_VIDEO`, `API_VIDEO`, `CAMERA_ECART_MIN_S` 0,2, `CAMERA_DELAI_S` 1,0, `CAMERA_PERIODE_PAGE_S` 0,35.
- nœud pilotage (`g1_pilotage/camera.py`, `Coeur.image_camera`, `GET /camera` de son API, jeton exigé comme ailleurs, permis quel que soit le maître) : une demande au robot seulement quand une page demande une image, une seule à la fois, au plus toutes les 0,2 s (la dernière image sert à toutes les pages) ; réponse `image/jpeg` avec `X-Image-Age-S` et `X-Image-Numero`, ou 503 avec la raison (pas de réponse en 1 s, code de refus, pas un JPEG) ; la caméra ne compte pas comme une réponse du robot (`robot_repond`) ;
- Atelier : `GET /api/pilotage/camera` relaie, une seule demande à la fois vers le nœud, partagée 0,15 s entre les pages (`CacheCamera`) ; 503 en français si le nœud ne répond pas ou ne connaît pas la caméra (nœud à redémarrer) ;
- page : « Voir » / « Couper » (retenu par mode) ; allumée d'office avec le robot, éteinte en répétition et en simulation ; une image toutes les 0,35 s au plus, chacune après la précédente, seulement si la vue est à l'écran et l'onglet du navigateur visible ; « Image figée » si la dernière a plus de 2 s ; en répétition, une image de remplacement (« Pas de caméra en répétition… ») ;
- faux G1 (`g1_jumeau/camera.py`) : répond à 1001 par une image de test JPEG 640 × 360 fabriquée par Pillow (mire, « Faux G1 : pas de caméra en répétition », numéro et heure, une bille qui avance) ; rien en panne `muet` ; 3203 pour une autre api.
À vérifier sur le robot : `docs/seance-robot.md`, 6.12 (le service existe-t-il sur ce G1, le format de la réponse, le débit par le Wi-Fi et l'effet sur le joystick).

**Tests** : `ws/src/g1_pilotage/test/test_camera.py` (une demande à la fois, 5 par seconde, refus, image illisible, silence, cœur multi-fil), `test_serveur.py` (`/camera` sans la main, jeton), `test_logique.py` (`geste` de l'état) ; `ws/src/g1_jumeau/test/test_camera.py` (image de test, puis de bout en bout avec ROS 2 : faux G1 ← nœud pilotage ← `GET /camera`) ; `atelier/tests/test_pilotage_serveur.py` (relais, partage, nœud absent, caméra muette) ; `atelier/tests/test_pilotage_vue_navigateur.py` (Firefox sans fenêtre, en répétition avec le pont ROS 2 de l'Atelier : vue sous Commandes et Danses et pas sous Mes chorégraphies, robot et passants sur la carte, G1 en 3D chargé et posé au sol, posture amortie, geste, marche, danse et sa barre, chorégraphie aux poses exactes, image de test de la caméra à quelques images par seconde, ARRÊT visible en bas de page et sur une tablette en portrait, aucune pose hors limites).

---

## 12. Interface à la SolidWorks, carte 3D, scan corrigé, robot et caméra (vague 5)

Contrats figés par l'agent Contrats le 31/10/2026, avant le travail en parallèle de cinq agents (12.8), puis complétés à l'assemblage du même jour (12.13, « Précisions de l'assemblage »). Comme les sections 4 et 9 à 11, cette section fait foi ; on ne la modifie qu'en passant par l'assemblage. Les choix viennent des décisions de l'intégrateur (l'utilisateur dort et a tout délégué), qui tranchent les cinq rapports de la phase « comprendre » (interface, recherche d'interface, scan, robot, tests) : les rapports donnent les détails (fichiers, lignes, mesures), cette section donne les choix et les interfaces entre agents.

Ce que l'utilisateur a demandé (31/10, résumé) :
- **une interface « à la SolidWorks »** : au début, deux grands boutons Simulation et Réel, puis un espace épuré (barre d'outils, ruban à onglets, arbre à gauche, grande vue au centre, panneau à droite), habillé comme Unitree Explore, « simple et ludique », où tout défile correctement ;
- **placer les points dans une carte 3D** faite des points du scan (accueil, salles, orientation), qu'on tourne et déplace ;
- **retirer la reconnaissance des tables et des chaises** (« il y en a de toute sorte »), et un scan aussi bon que celui d'Unitree Explore ;
- **la caméra See3CAM** du PC sur le robot (conteneur du Jetson, image dans l'Atelier) et la détection des visiteurs ;
- **les corrections du pont** : vitesse minimale (le 27/10, 0,1 m/s ne faisait aucun pas, 0,2 m/s marchait), lecture du mode du robot (lus : 0, 3, 501, 802), marche en mode 501.

Code partagé déjà livré et testé (`atelier/tests/test_contrats_vague5.py`) :
- les schémas : `nuage` (en-tête d'un nuage d'affichage) et `etat_camera` (nouveaux) ; l'état `pas_en_marche` et les champs facultatifs `mode_robot`, `demande` et `minimums` de `etat_pont` ; les champs facultatifs `boite` et `image` de `personnes` ; `carte_extrudee` de `monde` ; l'étape `nuage` de `session_scan` ; les réglages facultatifs `exposition`, `publication`, `taille_personne_m` et `correction_distance` de `camera` ; leurs règles dans `validation.py`. Les lieux et les mondes existants restent valides et s'enregistrent à l'identique ;
- `atelier.lieu.nuage` (emplacements, en-tête, lecture et écriture d'un nuage d'affichage, en-têtes HTTP) ; `CarteExtrudee` (champ `Monde.carte_extrudee`) et `chemin_maillage` ; l'id réservé `carte_du_scan` ; l'avertissement de `verifier_lieu` quand le maillage manque ou date d'avant la carte ;
- `atelier.lieu.robot` : `VITESSES_MIN_PONT`, `ZONES_MORTES_PONT`, `VITESSE_MIN_LIN_MAX`, `VITESSE_MIN_ROT_MAX`, `VITESSE_MAX_MIN`, `MESSAGE_VITESSE_MAX_BASSE`, `API_SPORT_GET_FSM_ID`, `PERIODE_LECTURE_MODE_S`, `DELAI_MODE_PERIME_S`, `PRIORITE_ETATS_PONT`, `EXEMPLE_ETAT_PONT_V5`, la fonction de référence `vitesse_effective` et ses cas `EXEMPLES_VITESSE_MIN` ; `atelier.lieu.pilotage` : `MODES_MARCHE` (500, 501, 801), `MODES_COURSE`, `NOMS_MODES`, `nom_mode`, `message_pas_en_marche` ; les copies de `MODES_MARCHE` et l'état `pas_en_marche` dans `g1_bridge` et `g1_jumeau`, comparées par le test ; `atelier.lieu.equipe` : `SUJETS_IMAGES`, `/camera_poitrine/etat` dans `SUJETS_EQUIPE`, `CAMERA_CONTENEUR` ;
- les squelettes : routes `atelier/serveur/routes/arret.py`, `liaison.py`, `nuage.py` et `camera.py` enregistrées dans `main.py` (chaque route répond 501 « Pas encore fait » tant que son agent ne l'a pas écrite ; `pas_encore_fait` de `communs.py`) ; modules `atelier/web/js/coque/*.js` (dont le registre des commandes du ruban et la table des anciens hash), `js/carte3d/carte3d.js` et `js/camera/flux.js` avec leurs exports ; `css/theme.css` (les jetons du thème, contrastes vérifiés), `css/carte3d.css` et `css/camera.css` vides, reliés par `index.html` ; le nœud `camera_usb` déclaré dans `g1_equipe` (il sort avec le code 1) ;
- `tests_e2e/tout.sh` compte 36 critères (« N / 36 ») ; un critère sans script est « absent » ; `tests_e2e/commun.sh` accepte `E2E_OVERLAY` (12.11) ; les tests qui figeaient les lignes d'`app.js` (vague 4 et scan) acceptent une table des écrans dans `js/coque/`.

### 12.1 Les décisions et qui les réalise

| Décisions | Ce qui change | Agent |
|---|---|---|
| I1 accueil, I2 espace de travail, I3 ruban à 5 onglets au plus, I4 arbre, I5 ARRÊT unique, I6 thème, I9 tests et tablette, I10 textes | `index.html`, `app.js`, `js/coque/`, `css/theme.css` et `atelier.css`, les écrans, `/api/arret`, `/api/robot/liaison` | Coquille |
| I7 vue centrale 3D, I8 placer les points en 3D | `js/carte3d/` (l'intégration dans la vue et l'écran Salles : Coquille) | Carte 3D |
| S1 trois bogues, S2 plus de reconnaissance, S3 monde maillé, S4 nuage de la carte 3D, S5 écran de scan, S6 `--refaire`, S7 carte d'Unitree | `atelier/scan/`, `atelier/monde/`, `atelier.lieu.scans`, routes du scan et des nuages, écran Scan | Scan |
| R1 vitesse minimale, R2 mode du robot, R3 Nav2 | `g1_bridge`, `g1_jumeau`, `g1_pilotage`, `g1_nav`, `atelier.lieu.robot` et `pilotage` | Robot |
| R4 caméra See3CAM | `docker/`, `g1_equipe`, `g1-visiteurs`, pont ROS 2 du serveur, `/api/camera/*`, vue Caméra | Caméra |

### 12.2 L'interface (agent Coquille)

**L'écran d'accueil** (I1, « Nouveau document » de SolidWorks) : deux grandes cartes illustrées, **Simulation** (« Dessiner un lieu et essayer le guide sur l'ordinateur, sans robot. ») et **Robot réel** (« Scanner le bâtiment, placer les salles et guider le vrai G1. ») ; un clic choisit, un double-clic ou Entrée ouvre ; dessous, la liste des lieux (le dernier ouvert présélectionné), « Nouveau lieu » (le nom ; la taille du monde seulement en Simulation) et le bouton **Ouvrir**. Sous la carte Robot réel : la case **« Répétition sans robot (faux G1) »** et la liste des vérifications, qui remplace les `confirm()` du lancement du robot et du scan : « Atelier lancé avec robot.sh » (domaine 0), « Câble du robot branché », « PC1 et Jetson répondent » (`GET /api/robot/liaison`, 12.4), « Télécommande en main » (à cocher) ; en répétition, seules restent celles qui ont un sens sans robot. Lien discret « Piloter le robot sans lieu » (Piloter s'ouvre sans lieu, comme aujourd'hui). Une adresse avec un hash (`#salles`…) ou `?recharger` saute l'accueil (tests, rechargement) ; le bouton ⌂ de la barre d'outils y revient.

**L'espace de travail** (I2) : la page ne défile jamais.

```
┌ barre d'outils 48 px : ⌂ Atelier G1 │ Lieu ▾ › Étage ▾ │ SIMULATION / RÉEL / RÉPÉTITION │ ↶ ↷ │ Enregistrer │ liaison │ ◐ │ ⚙ │ ARRÊT ┐
├ ruban 84 px, repliable : onglets du mode ; grosses icônes avec un libellé court ; menu ⚙ Avancé par onglet ──────────────────────┤
├ arbre 260 px (repliable, défile seul) ┬ vue centrale (remplit tout ; position: relative) ┬ panneau de tâches 320 px (défile seul) ┤
│ Lieu ▸ Étage ▸ Carte, Monde, Points, │ barre flottante : 3D │ Plan 2D │ Caméra ·        │ propriétés de l'élément choisi, ou    │
│ Itinéraires, Zones, Scans, Équipe    │ Dessus Iso Face Recadrer · Calques ▾             │ formulaire de la commande, ✓ OK ✗     │
└ barre d'état 28 px : consigne de l'outil · messages courts · x, y sous le pointeur · liaison ──────────────────────────────────────┘
```

Règles de mise en page (elles corrigent les panneaux écrasés à 24 px et la molette captée par les cartes) : `html, body {height: 100%; overflow: hidden}` ; une grille de 4 rangées (barre d'outils, ruban, centre, barre d'état), puis 3 colonnes au centre ; `min-height: 0` sur chaque enfant de grille ou de flex ; chaque colonne en `overflow-y: auto` avec `overscroll-behavior: contain` ; la vue en `position: relative`, la toile ou le plan en `inset: 0` ; jamais `100vh` codé en dur, ni de hauteur fixe en pixels pour une liste (c'est la colonne qui défile) ; `[hidden] {display: none !important}`. Sous 1100 px de large, l'arbre et le panneau deviennent des tiroirs (boutons dans la barre d'outils) ; cibles de 44 px (`--cible`) ; gestes tactiles de 12.3.

**Le ruban** (I3) : 4 onglets en Simulation (Dessiner, Placer, Simuler, Équipe), 5 en Réel (Scanner, Placer, Naviguer, Piloter, Équipe ; la répétition est le Réel sans robot) : `ONGLETS_RUBAN`. Le registre des commandes est `COMMANDES` de `js/coque/ruban.js`, livré : chaque commande a un `id` stable (repère `[data-commande=<id>]`), ses `modes`, son `onglet` et son `groupe`, un `libelle` court, une `icone`, une phrase d'`aide` (infobulle), l'`ecran` qui l'exécute et le nom de la `commande` passé à cet écran ; `avance: true` la range dans le menu ⚙ de l'onglet ; `case: true` en fait une case à cocher.

| Onglet | Commandes (`id`) | Écran |
|---|---|---|
| Dessiner (simu) | `monde.choisir`, `monde.mur`, `monde.passage`, `monde.objet` (menu des meubles), `monde.pieton`, `monde.depart` ; Avancé : `carte.refaire` | monde, carte |
| Placer (les deux) | `salles.salle`, `salles.accueil`, `itineraires.noeud`, `itineraires.relier`, `zones.interdite`, `zones.lente` | salles, itineraires, zones |
| Simuler (simu) | `simulation.lancer`, `simulation.arreter`, `simulation.y-aller`, cases `simulation.accompagner` et `simulation.retour` ; Avancé : `simulation.faux-visiteur`, `simulation.passants`, `simulation.reglages-guide`, `scan.simule` | simulation, scan |
| Scanner (réel) | `scan.scan`, `scan.fin`, `scan.utiliser` | scan |
| Naviguer (réel) | `navigation.lancer`, `navigation.reperer`, `navigation.y-aller`, `navigation.bloquer`, `navigation.debloquer`, `navigation.arreter` | simulation |
| Piloter (réel) | `pilotage.main`, `pilotage.postures`, `pilotage.gestes`, `pilotage.voix`, `pilotage.led`, `pilotage.joysticks` ; groupe Spectacle : `pilotage.danses`, `pilotage.choregraphies` ; Avancé : `pilotage.portique`, `pilotage.volume` | pilotage |
| Équipe (les deux) | `personnalites.ouvrir`, `dialogues.ouvrir`, `camera.ouvrir` | personnalites, dialogues, camera |

Le menu ⚙ Avancé reçoit aussi ce qui est rare (I3) : identifiants, emprise, console « Ce qui tourne », 17 phrases des personnalités, syntaxe des dialogues, réglages de la caméra, gestes rares. L'agent Coquille peut ajouter des commandes Avancé et changer libellés, icônes et aides ; un `id` ne change pas sans cette section. Icônes : SVG écrits dans `js/coque/`, sans bibliothèque ; le libellé est toujours sous l'icône. Piloter n'existe qu'en Réel.

**L'arbre du lieu** (I4, FeatureManager) : Lieu ▸ Étage ▸ Carte (source, date), Monde (en Simulation), Points (★ Accueil d'abord, puis les salles), Itinéraires (nœuds, couloirs), Zones, Scans (sessions), Équipe. Clic : choisit l'élément dans la vue (`carte3d.choisir`, ou le plan) et montre ses propriétés à droite ; double-clic : recentre la vue dessus ; pastille ⚠ sur les éléments cités par `GET /api/lieux/{id}/verification`. Chaque nœud porte `data-noeud="<genre>:<id>"` (`etage:rdc`, `carte:rdc`, `monde:rdc`, `salle:b204`, `noeud:c1`, `couloir:3`, `zone:interdite:0`, `scan:2026-10-27_14h22`, `equipe:camera`).

**La vue centrale** (I7) : trois vues, choisies dans la barre flottante. **3D** : la carte 3D de 12.3, partagée (la coque la crée une fois par lieu et étage, y charge le nuage de l'étage en Réel, ou le monde en Simulation, puis les points, itinéraires et zones, et le robot et les piétons de `/ws/etat`). **Plan 2D** : Leaflet, gardé dans cette vague pour dessiner le monde, les itinéraires et les zones. **Caméra** : en Réel, `creerVueCamera` de 12.7, aussi en incrustation dans Piloter et Naviguer. Par défaut : 3D en Réel (Placer s'ouvre dans la vue Nuage), Plan 2D pour Dessiner, 3D pour Placer en Simulation. Vues prédéfinies Dessus, Iso, Face, Recadrer ; calques : nuage, carte 2D, monde, points, itinéraires, zones, robot, piétons.

**Le thème** (I6) : `css/theme.css`, livré : les jetons de couleur sur `:root`, sombre par défaut (palette mesurée d'Unitree Explore : fond `#2e2e3d`, cartes `#201f2d`, accent `#5569d4`, actif `#6577e0`, ARRÊT `#d93036`), thème clair avec `data-theme="clair"` sur `<html>` (bouton ◐, clé `atelier.theme`) ; vue 3D toujours sombre (`--vue-fond` `#1e1e1e`) ; couleurs des repères (`--repere-accueil` ambre, `--repere-salle` accent, `--itineraire` cyan, `--zone-interdite` rouge, `--zone-lente` orange, `--nuage-bas`, `--nuage-milieu`, `--nuage-haut` : vert, jaune, rose) ; tailles de la coque. Les feuilles des agents n'écrivent aucune couleur en dur. Contrastes AA vérifiés par le test (texte 4,5:1, repères 3:1).

**Les modules de la coque** (`atelier/web/js/coque/`, squelettes livrés ; l'agent Coquille en ajoute d'autres s'il veut) :

| Module | Exports du contrat |
|---|---|
| `coque.js` | `MODES`, `CLES_MEMOIRE`, `demarrerCoque(options)`, `ouvrirEspace({mode, repetition, lieu, etage})`, `retourAccueil()`, `modeCourant()`, `ouvrirCommande(id)` |
| `accueil.js` | `afficherAccueil(racine, {surOuvrir, surPilotageSansLieu})` → `{fermer}` |
| `ruban.js` | `ONGLETS_RUBAN`, `COMMANDES`, `commandesDe(mode, onglet)`, `construireRuban(element, {mode, surCommande})` → `{choisirOnglet, activer, griser, detruire}` |
| `arbre.js` | `construireArbre(element, {lieu, etage, mode, surChoix, surDoubleClic})` → `{rafraichir, choisir, detruire}` |
| `panneau.js` | `ouvrirPanneau(element, {titre, aide, ok, annuler})` → `{corps, fermer}` |
| `barre_etat.js` | `construireBarreEtat(element)` → `{message, coordonnees, outil}` |
| `arret.js` | `monterArret(element, {mode})` → `{arreter, debloquer, detruire}` |
| `confirmation.js` | `demanderConfirmation(texte, {titre, ok, annuler, danger})` → promesse de vrai ou faux |
| `anciens_hash.js` | `ANCIENS_HASH`, `destinationDuHash(hash)` |

**Le contrat des écrans** devient `ouvrir(racine, options)` → `{modifie(), fermer(), commande?(nom), selectionner?(genre, id), vue?(nom)}` :
- `racine` : la vue Plan 2D de la vue centrale, où l'écran met sa carte Leaflet comme avant ; la coque y pose `class="ecran ecran-<id>"` et `data-ecran="<id>"` ;
- `options.panneau` : l'élément du panneau de tâches, vidé, où l'écran met son formulaire, ses listes et ses boutons ; ✓ OK et ✗ Annuler par `ouvrirPanneau` ;
- `options.mode` : `simu`, `reel` ou `repetition` ;
- `options.commande` : la commande du ruban qui a ouvert l'écran (`salle`, `mur`…) ou null ; une commande suivante du même écran arrive par `instance.commande(nom)` ;
- `options.vue` (`3d`, `plan` ou `camera`) et `options.carte3d` : la carte 3D partagée (12.3), ou null (pas de WebGL, ou pas encore créée) ;
- `options.coque` : `{confirmer(texte, options) → promesse, message(texte, genre), pleinEcran(vrai|faux), ouvrirCommande(id), choisirVue(nom), surVue(fn) → désabonner, barreEtat}`.
Un écran d'avant, `ouvrir(racine)` sans options, marche encore : il dessine tout dans `racine` (migration écran par écran). Les panneaux `monter(element, outils)` de la vague 4 ne changent pas. `scan.js` (agent Scan) et `camera.js` (agent Caméra) acceptent `options` et mettent leurs formulaires dans `options.panneau` quand il existe ; l'écran de scan demande `pleinEcran(true)` pendant un scan (S5).

**Plus de boîte native** : chaque agent remplace, dans ses fichiers, `window.confirm` et `window.prompt` par `options.coque.confirmer` (ou `demanderConfirmation` de `js/coque/confirmation.js` ; le squelette livré passe encore par `window.confirm`). Les tests remplacent `demanderConfirmation`, plus `window.confirm`.

**Les anciens hash** (`ANCIENS_HASH`, livré) : `#lieux` → l'accueil ; `#monde` → Simulation › Dessiner ; `#salles`, `#itineraires`, `#zones` → Placer (dans le mode retenu) ; `#carte` → l'écran Carte ; `#simulation` → Simuler, ou Naviguer selon `atelier.mode-simulation` (`repetition` : Réel avec la répétition ; `robot` : Réel) ; `#scan` → Scanner, ou Simuler › Avancé › Scan simulé si `atelier.scan.mode` vaut `simu` ; `#pilotage` → Réel › Piloter, même sans lieu ; `#personnalites`, `#dialogues`, `#camera` → Équipe.

**Les repères stables des tests**, posés par la coque (les tests ne cherchent plus les boutons par leur texte) :

| Où | Repères |
|---|---|
| accueil | `[data-role=accueil]`, `[data-role=mode-simu]` et `[data-role=mode-reel]` (`aria-pressed`), `[data-role=repetition]` (case), `[data-role=verifications]` avec `[data-verif=ros\|cable\|robot\|telecommande]` (`data-etat=ok\|non\|inconnu`), `[data-role=liste-lieux]` avec `[data-lieu=<id>]`, `[data-role=nouveau-lieu]`, `[data-role=ouvrir]`, `[data-role=pilotage-sans-lieu]` |
| barre d'outils | `[data-role=espace]` (`data-mode=simu\|reel\|repetition`), `[data-role=barre-outils]`, `[data-role=lieu]`, `[data-role=etage]`, `[data-role=accueil-retour]`, `[data-role=defaire]`, `[data-role=refaire]`, `[data-role=enregistrer]`, `[data-role=theme]`, `[data-role=arret]` (`data-etat=pret\|bloque`) |
| ruban | `[data-role=ruban]`, `[data-onglet=<id>]` (`aria-selected`), `[data-commande=<id>]` (`aria-pressed` si active ; `disabled` et `title` avec la raison si grisée), `[data-role=avance]` |
| arbre | `[data-role=arbre]`, `[data-noeud=<genre>:<id>]`, `[data-alerte]` |
| vue | `[data-role=vue]`, `[data-role=vue-plan]` (racine des écrans), `[data-role=vue-3d]`, `[data-role=vue-camera]`, `[data-role=barre-vue]` avec `[data-vue=3d\|plan\|camera]`, `[data-cadrage=dessus\|iso\|face\|recadrer]`, `[data-calque=<nom>]` |
| panneau | `[data-role=panneau]`, `[data-role=panneau-titre]`, `[data-role=panneau-corps]`, `[data-role=ok]`, `[data-role=annuler]` |
| barre d'état | `[data-role=barre-etat]`, `[data-role=etat-message]`, `[data-role=etat-coordonnees]`, `[data-role=etat-liaison]` |
| confirmation | `[data-role=confirmation]`, `[data-role=confirmer]`, `[data-role=renoncer]` |
| écrans | `[data-ecran=<id>]` (et `.ecran-<id>`) sur la racine de l'écran ouvert ; les `data-role` des écrans d'aujourd'hui restent quand c'est possible |
| carte 3D, caméra, scan | 12.3 et 12.7 ; écran de scan : `[data-role=scan-compteurs]`, `[data-role=scan-progression]` (agent Scan) |

Restent aussi : `window.erreursAtelier` (index.html), `<title>Atelier G1</title>` et le mot « atelier » dans la page (critère 10).

**Le stockage du navigateur** (`CLES_MEMOIRE`, toujours dans un try/catch) : `atelier.mode` (`simu` | `reel`), `atelier.repetition` (`1` | `0`), `atelier.theme` (`sombre` | `clair`), `atelier.lieu`, `atelier.etage`, `atelier.onglet.<mode>`, `atelier.vue.<mode>`, `atelier.calques` (JSON), `atelier.arbre.replie`, `atelier.ruban.replie`. Les anciennes clés `atelier.mode-simulation` (`simu` | `repetition` | `robot`), `atelier.scan.mode` et `atelier.scan.repetition` restent écrites à chaque changement de mode (écrans d'avant) ; `atelier.ecran` n'est plus lue ; les clés `atelier.pilotage.*` ne changent pas.

**Textes** (I10) : simples et ludiques, une seule phrase d'aide par commande ; aucun nom de sujet ROS ni note de développeur dans les titres (seulement dans les infobulles Avancé ou la documentation).

### 12.3 La carte 3D (agent Carte 3D)

Module `atelier/web/js/carte3d/carte3d.js` (squelette livré ; l'agent peut ajouter des fichiers dans `js/carte3d/`), three.js r160 de `vendor/` (`Raycaster`, `Plane`, `Points`, `OrbitControls` ; aucune nouvelle bibliothèque). **Repère** : celui de la carte (`map`), z vers le haut, gardé tel quel : x, y et theta sont ceux du plan 2D, de `salles.yaml`, `itineraires.yaml` et `zones.yaml`, sans conversion ; le sol est à z = 0 (le nuage d'affichage a déjà le plan du sol soustrait, 12.5) ; `fleche.rotation.z = theta` (radians, sens trigonométrique depuis l'axe x).

`creerCarte3D(conteneur, options)` → la carte. Options : `etage` (obligatoire : seuls les éléments de cet étage sont montrés), `nomGlobal` (ex. `'carte3d'` : `window.carte3d` pour les tests), `hauteurCoupe` (2,2 m), `plafond` (faux : points plus hauts cachés).

| Méthode | Rôle |
|---|---|
| `chargerNuage(url)` → promesse `{points, bornes, grille}` | lit le binaire d'un nuage d'affichage (12.4 : Float32 x y z petit-boutistes, en-têtes `X-Nuage-*`) et l'affiche ; rejet avec un message en français (404 : pas de nuage) |
| `afficherPoints(positions, bornes)` | un nuage déjà en mémoire (`Float32Array` x y z…) |
| `afficherMonde(monde, {urlMaillage})` | le monde de `GET …/monde` : murs, objets et piétons en volumes ; avec `carte_extrudee`, le maillage STL de `GET …/monde/maillage` |
| `afficherCarte2D(url, bornes)` | la carte 2D (`carte.png`) posée au sol sur `bornes` `{xmin, ymin, xmax, ymax}` de `GET …/carte.yaml` |
| `afficherSalles(salles, idPrincipal)` | les salles de `GET …/salles` : le principal en étoile ambre avec sa flèche, les autres en épingles numérotées couleur d'accent avec leur flèche ; étiquette HTML de chacune (`.carte3d-etiquette[data-salle=<id>]`, `textContent`) |
| `afficherItineraires({noeuds, couloirs})`, `afficherZones({interdites, lentes})` | nœuds et couloirs en cyan au sol ; zones translucides, interdites en rouge, lentes en orange |
| `afficherRobot(pose)`, `afficherPietons(liste)`, `afficherTrajet(points)` | `{x, y, theta}` ou null ; `[{id, x, y}]` ; `[[x, y, theta], …]` (trajet d'un scan) |
| `vue(nom)`, `recadrer(bornes?)`, `centrerSur(x, y)` | `dessus`, `iso`, `face` ; tout voir ; recentrer (double-clic dans l'arbre) |
| `calque(nom, visible?)`, `coupe(hauteur)` | `CALQUES` : nuage, carte2d, monde, points, itineraires, zones, robot, pietons, trajet ; coupe du plafond (null : plafond montré) |
| `outil(nom, {id})` | `naviguer` (défaut), `salle`, `accueil`, `noeud` (si le temps le permet ; sinon en Plan 2D), `mesurer` |
| `choisir(genre, id)` | met un repère en valeur (anneau blanc) |
| `surSelection(fn)`, `surPose(fn)`, `surPointeur(fn)` | abonnements, chacun renvoie la fonction qui désabonne : `{genre, id}` au clic sur un repère ; `{outil, id, x, y, theta, fini}` pendant et à la fin d'un placement ; `{x, y}` du sol sous le pointeur (barre d'état), ou null |
| `versEcran(x, y, z)`, `versSol(px, py)` | pixel du conteneur d'un point (z = 0 par défaut), et point du sol sous un pixel, ou null (tests, étiquettes) |
| `redimensionner()`, `etat()`, `detruire()` | `etat()` : `{webgl, points, vue, outil, calques, camera}` |

**Gestes** (I7) : clic gauche glissé = tourner ; clic droit glissé, ou Maj + gauche = déplacer ; molette = zoom vers le pointeur (`zoomToCursor`) ; clic du milieu glissé = tourner (SolidWorks) ; tactile : un doigt tourne, deux doigts déplacent et zooment. La caméra ne passe jamais sous le sol et ne bouge jamais d'elle-même, sauf au premier affichage et sur demande (Recadrer, double-clic dans l'arbre). F : recadrer ; Échap : retour à `naviguer`, geste en cours annulé. Avec un outil de placement, le bouton gauche place (le milieu tourne toujours).

**Placer** (I8), outils `salle` et `accueil` : un clic sur le sol pose le point (accroché à 5 cm) ; un glissé depuis le point règle l'orientation (flèche, accrochée à 15°, Maj : libre) ; un glissé du point le déplace ; chaque étape émet `surPose` (`fini` vrai au relâchement). On vise le plan du sol z = 0 (`Raycaster` contre un `Plane`), pas les points. C'est l'écran Salles (agent Coquille) qui garde la liste, montre le formulaire à droite (nom, x, y et orientation en degrés, corrigeables ; ✓ OK / ✗ Annuler), tient Annuler / Rétablir (`historique.js`) et enregistre par la même route qu'en 2D, `PUT /api/lieux/{id}/salles?synchroniser=true` (l'accueil est la salle principale : `lieu.yaml` et `depart_robot` suivent) : les deux vues lisent et écrivent les mêmes fichiers.

**Le nuage** : couleurs calculées dans le navigateur depuis z, dégradé `--nuage-bas` → `--nuage-milieu` → `--nuage-haut` de 0 à 2,2 m ; points plus hauts que `hauteurCoupe` cachés (case « Afficher le plafond ») ; taille des points réglable (vers 0,05 m, la grille du nuage) ; 250 000 points restent fluides. Couleurs des repères : les jetons de `theme.css`, lus par `getComputedStyle` (repli sur les mêmes valeurs dans le module). Rendu à la demande, pas de boucle continue au repos.

**Sans WebGL** : un message dans le conteneur (`[data-role=carte3d-sans-webgl]`), `etat().webgl` faux, et toutes les méthodes restent appelables sans effet ; la coque bascule alors sur le Plan 2D. Constat du 31/10 : Firefox sans fenêtre a WebGL sur le PC du projet (carte NVIDIA) **seulement avec l'affichage X de la session graphique** (`DISPLAY=:1` : aucune fenêtre ne s'ouvre) ; sans `DISPLAY`, pas de WebGL, même avec `webgl.force-enabled` (précision de l'assemblage, 12.13) ; les tests coupent WebGL (préférence `webgl.disabled`) pour essayer le repli.

**Essais sans la coque** : une page d'essai `atelier/web/essais/carte3d.html` (même importmap que `index.html`, jamais liée par l'interface), ou l'import dynamique du module dans la page ; `window.<nomGlobal>`, `versEcran` et `versSol` permettent de cliquer un point précis du sol.

### 12.4 Les routes nouvelles

| Route | Agent | Paramètres | Réponse |
|---|---|---|---|
| `POST /api/arret` | Coquille | `{mode?: simu\|reel\|repetition, raison?}` | en moins de 1 s, même si une partie ne répond pas : `{arrete, mode, verrou, duree_s, parties: {guide, teleop, pilotage, verrou: {ok: vrai\|faux\|null, detail}}, message}` (null : sans objet, rien ne tournait) ; toujours 200 |
| `POST /api/arret/debloquer` | Coquille | — | `/pont/arret` false : `{verrou: false, ecoute, message}` ; 503 sans pont ROS 2 |
| `GET /api/arret` | Coquille | — | `{verrou, depuis, mode, par}` : le dernier verrou posé par l'Atelier ; le même dans `/ws/etat`, champ `arret` |
| `GET /api/robot/liaison` | Coquille | — | `{interface, cable, adresse_pc, pc1: {adresse, repond, ms}, jetson: {adresse, repond, ms}, ros: {domaine, cyclonedds, actif}, pret, message, duree_s}`, en 1,5 s au plus |
| `GET /api/lieux/{id}/etages/{e}/nuage` | Scan | `?source=scan\|unitree` | `application/octet-stream` : le binaire `cartes/<e>.nuage.bin` (ou `<e>_unitree.nuage.bin`), avec `X-Nuage-Points`, `X-Nuage-Grille`, `X-Nuage-Bornes` (`xmin,ymin,zmin,xmax,ymax,zmax`), `X-Nuage-Source`, `X-Nuage-Date`, `X-Nuage-Session` (`entetes_http_nuage`) et `ETag` ; 404 en français sans nuage (« pas encore de nuage 3D : faites un scan, puis « Utiliser cette carte » ») |
| `GET /api/lieux/{id}/etages/{e}/nuage/info` | Scan | `?source=…` | l'en-tête JSON (schéma `nuage`), plus `{url, octets, modifie}` |
| `GET /api/lieux/{id}/etages/{e}/monde/maillage` | Scan | — | `mondes/<e>_carte.stl` (`model/stl`) ; 404 sans `carte_extrudee` |
| `GET /api/scan/nuage` | Scan | `?lieu=L[&session=S][&apercu=1]` | le binaire d'une session, même format et mêmes en-têtes : `nuage_affichage.bin` quand elle est traitée ; pendant le scan, ou avec `apercu=1`, l'aperçu en direct `apercu_nuage.bin` ; 404 sinon |
| `GET /api/scan/nuage/info` | Scan | idem | l'en-tête JSON correspondant |
| `GET /api/camera/image` | Caméra | `?source=poitrine\|visiteurs` | la dernière image (`image/jpeg`) avec `X-Image-Numero`, `X-Image-Age-S`, `X-Image-Largeur`, `X-Image-Hauteur` ; 503 en français sans image depuis 2 s |
| `GET /api/camera/flux` | Caméra | `?source=…[&ips=10][&images=N]` | flux MJPEG `multipart/x-mixed-replace; boundary=image-g1` : une partie par image nouvelle (`Content-Type: image/jpeg`, `Content-Length`, `X-Image-Numero`), au plus `ips` par seconde (15 au plus) ; `images=N` : fin après N images (tests) ; fin quand la page se ferme. `<img src="/api/camera/flux?source=poitrine">` l'affiche tel quel |
| `GET /api/camera/etat` | Caméra | — | `{ros: {actif}, sources: {poitrine, visiteurs: {recue, numero, age_s, largeur, hauteur, octets, ips}}, noeud: dernier /camera_poitrine/etat ou null, visiteurs: {age_s, nombre} ou null}` |

Les squelettes sont dans `atelier/serveur/routes/arret.py`, `liaison.py`, `nuage.py` et `camera.py`, déjà enregistrés dans `main.py` : l'agent remplit leurs fonctions sans toucher à `main.py`. Erreurs en français, `{detail, …}` comme en 4.4, jamais d'erreur 500. Retirées par l'agent Scan : `GET` et `PUT /api/scan/sessions/{s}/reconnaissance`, `GET /api/scan/sessions/{s}/monde`.

**L'ARRÊT** (I5) lance en parallèle, chacun avec son délai : `guide` (`/guide/stop` par le pont ROS 2 du serveur, `etat.pont.stop()`) ; `teleop` (vitesse nulle sur `/cmd_vel` si la téléopération simulée a servi, `app.state.teleop`) ; `pilotage` (`POST /arret` du nœud pilotage, 0,6 s au plus, s'il tourne ou répond) ; `verrou` (`/pont/arret` true, `etat.pont.bloquer(True)`) **seulement en Réel ou en répétition** (champ `mode` de la demande, ou mode de la navigation qui tourne), jamais en simulation (le verrou est transient_local : il bloquerait la répétition suivante). Le bouton ARRÊT de la barre d'outils et la touche Échap l'appellent ; en Réel il devient « Débloquer » tant que le verrou est posé. L'ARRÊT n'arrête pas un scan (« Fin » le fait) ; en répétition, l'exploration d'un scan passe par le pont, que le verrou arrête. `POST /api/robot/arret {verrou}` (vague 3) reste. Correction du 01/11/2026 (12.15) : « Bloquer » (`POST /api/robot/arret {verrou: true}`) envoie aussi `/guide/stop`, et aucun déblocage ne relance l'ancien trajet.

**La liaison** : le câble par `/sys/class/net/<interface>/carrier` (`ATELIER_INTERFACE_ROBOT`, eno2 par défaut, comme le scan) ; un ping (`ping -c 1 -W 1`) du PC1 (`ATELIER_PC1`, défaut 192.168.123.161) et du Jetson (`ATELIER_JETSON`, défaut 192.168.123.164), en parallèle et seulement si le câble est branché (sinon `repond` null) ; le domaine et l'interface de `CYCLONEDDS_URI` (comme `verifier_terminal_robot` de `routes/simulation.py`) ; `pret` : câble, PC1 qui répond, domaine 0. Rien d'autre n'est envoyé au robot. Tests : `ATELIER_PC1=127.0.0.1`, `ATELIER_INTERFACE_ROBOT=lo`.

### 12.5 Le scan corrigé (agent Scan)

**La chaîne** (`g1-scan traiter`) : `carte_3d` → `carte_2d` → `nuage`, sans reconnaissance (S2). Étapes de `session.json` : `nuage` (nouvelle, schéma et `ETATS_ETAPES` livrés) remplace `reconnaissance` et `monde`, qui restent acceptées pour les anciennes sessions ; `ETAPES`, `ETAPES_TRAITEMENT` et `PLAGES_PROGRESSION` de `atelier.lieu.scans` sont à l'agent. Les trois bogues (S1 ; rapport du scan, § 3 et § 5) :
1. **une seule base de temps** : si les nuages ont un horodatage nul, ou si nuages et odométrie n'ont pas le même décalage avec l'heure du bag (plus de 0,5 s d'écart), chaque nuage est apparié à la pose reçue au même instant de réception ; un nuage déjà dans le repère de l'odométrie n'est jamais jeté faute de pose (la plus proche sert) ; `rapport.json` : `nuages: {recus, utilises, ignores}`, `base_de_temps` (`message` ou `reception`), et un avertissement au-delà de 5 % d'ignorés ;
2. **le retrait des obstacles mobiles** part de la vraie origine du capteur (la pose appariée) et retire moins ; `rapport.json` : `mobiles_retires` ;
3. **le sol en plan** : un plan robuste (RANSAC à graine fixe, repris de `reconnaissance.py` avant de la retirer) ; la tranche de la carte 2D est prise en hauteur au-dessus de ce plan ; `rapport.json` : `sol: {plan: [a, b, c], inclinaison_deg}`.
Les x et y restent ceux du repère `map` du robot : aucune rotation autour de z, aucun déplacement d'origine (les salles déjà placées restent justes) ; on soustrait le plan, on ne tourne pas le nuage.

**Le nuage d'affichage** (S4 ; module livré `atelier.lieu.nuage`, schéma `nuage`) : deux fichiers de même nom, `<nom>.bin` (Float32 x y z petit-boutistes, 12 octets par point, sans en-tête) et `<nom>.json` (l'en-tête : `version`, `format: float32_xyz`, `points`, `grille`, `repere: map`, `bornes`, `sol: {plan, inclinaison_deg}`, `source` (`scan`, `apercu` ou `unitree`), `session`, `etage`, `date`, et des champs libres en plus) ; z est la hauteur au-dessus du plan du sol ; sol et plafond compris (la page coupe le plafond), mobiles retirés. Emplacements : `scans/<s>/nuage_affichage` (fin du traitement, grille 0,05 m), `scans/<s>/apercu_nuage` (aperçu en direct, toutes les 2 s, grille 0,10 m, toutes hauteurs, 150 000 points au plus : `APERCU_NUAGE_POINTS_MAX`), `cartes/<e>.nuage` (copié à l'adoption) et `cartes/<e>_unitree.nuage` (carte d'Unitree). Écriture : `ecrire_nuage(base, points, entete_nuage(...))`, atomique et vérifiée ; lecture : `lire_nuage`, `lire_entete_nuage` ; en-têtes HTTP : `entetes_http_nuage`. `apercu.json` et `apercu.png` restent (écrans d'avant). Exemple d'en-tête, `cartes/rdc.nuage.json` (le `.bin` à côté fait 12 × 245 317 octets) :

```json
{"version": 1, "format": "float32_xyz", "points": 245317, "grille": 0.05, "repere": "map",
 "bornes": {"xmin": -6.512, "ymin": -16.031, "zmin": -0.05, "xmax": 24.077, "ymax": 3.188, "zmax": 2.91},
 "sol": {"plan": [0.0009, -0.0101, -1.271], "inclinaison_deg": 0.582, "methode": "ransac"},
 "source": "scan", "session": "2026-10-27_14h22", "etage": "rdc", "date": "2026-10-31T03:10:00+01:00",
 "mobiles_retires": 136527}
```

**L'adoption** (`g1-scan adopter`, `POST /api/scan/sessions/{s}/adopter`) : la carte de la session telle quelle (plus d'effacement de « personnes ») ; `cartes/<e>.pcd` et `cartes/<e>.nuage.bin` et `.json` ; `source_carte: scan` ; `carte_unitree` en mode robot ; puis le **monde maillé** (S3). Si l'étage avait un monde dessiné (`source_carte: monde`), ce monde est gardé dans la session (`monde_remplace.monde.yaml`) et remplacé par un monde qui ne garde que ses piétons qui sont dans l'emprise de la carte, avec `depart_robot` sur le point principal (`synchroniser_depart`), l'emprise des bornes de la carte et `carte_extrudee` ; un étage déjà scanné garde son monde (les ajouts de l'utilisateur) et reçoit seulement `carte_extrudee`. Enfin `atelier.monde.generer`. Le champ `monde` de la demande d'adoption est accepté et ignoré. Le message « replacez les salles » ne s'affiche que si le repère change (scan d'un étage qui avait un monde dessiné).

**Le monde maillé** (S3, `atelier/monde/`) : `generer` d'un étage `source_carte: scan` qui a une carte écrit `mondes/<e>_carte.stl` (`chemin_maillage`), puis le `.sdf`, et met `carte_extrudee: {fichier: <e>_carte.stl, hauteur: 1.5}` dans `mondes/<e>.monde.yaml` (avec un monde minimal s'il n'y en a pas : emprise de la carte, départ sur le principal, aucun mur). Le maillage : les pixels occupés de la carte (petites taches retirées, fermeture 3 × 3), décomposés en rectangles, extrudés à `hauteur` (1,5 m par défaut, `HAUTEUR_CARTE_EXTRUDEE`, au-dessus du LiDAR simulé à 1,245 m) et fusionnés en **un seul STL binaire** ; dans le SDF, **un seul modèle statique `carte_du_scan`** (`MODELE_CARTE_EXTRUDEE`, id réservé) avec collision et visuel ; `sdf_simulation` rend absolu l'`uri` du maillage (le monde simulé est réécrit ailleurs). Essai du rapport : 1 617 boîtes fusionnées tournent à 1,0 fois le temps réel, contact vérifié ; en boîtes séparées, 0,59. La carte 2D reste celle du scan (`generer` n'y touche pas). Un monde dessiné sans `carte_extrudee` donne le même SDF qu'avant, octet pour octet. Le format exact, compatible avec les anciens mondes (le champ est facultatif et absent quand il vaut None) :

```yaml
# mondes/rdc.monde.yaml d'un étage scanné, écrit par g1-monde generer ou g1-scan adopter
version: 1
emprise: {min: [-6.55, -16.05], max: [24.1, 3.2]}    # les bornes de la carte
pietons: []                                          # les ajouts de l'utilisateur restent (murs, objets, piétons)
depart_robot: {x: 0.0, y: 0.0, theta: 0.0}           # le point principal
carte_extrudee: {fichier: rdc_carte.stl, hauteur: 1.5}   # mondes/rdc_carte.stl ; dans Gazebo : le modèle carte_du_scan
```

**L'écran de scan** (S5 ; `js/ecrans/scan.js`, `js/nuage3d.js`, `css/scan.css`) : plein écran sombre (`options.coque.pleinEcran(true)`) comme « 3D LiDAR Mapping » du Go2 : le nuage en direct (`GET /api/scan/nuage?apercu=1`, toutes hauteurs, couleurs par la hauteur), le trajet, le robot, de gros boutons Scan et Fin, les compteurs (durée, distance, points), puis la progression du traitement et « Utiliser cette carte » (`scan.utiliser`). Plus de revue, de cases, de catégories ni de « Ouvrir dans l'éditeur du monde ». Le scan simulé reste (Simulation › Avancé › Scan simulé), avec l'exploration automatique et les flèches.

**`g1-scan traiter --refaire`** (S6) : accepte une session finie, même adoptée ; non destructif : les résultats d'avant (`carte.pgm`, `carte.yaml`, `nuage.pcd`, `nuage_affichage.*`, `rapport.json`, `reconnaissance.yaml`, `monde_scan.monde.yaml`) sont déplacés dans `scans/<s>/ancien_<AAAA-MM-JJ_HHhMM>/` ; la session repasse `termine` sans `adoption` (il faut la réadopter). L'assemblage retraite `lieux/seance/scans/2026-10-27_14h22` et l'adopte pour `seance`, étage `rdc`, après sauvegarde ; la carte nettoyée à la main (785 pixels) n'est plus nécessaire si la nouvelle chaîne retire bien la traînée du suiveur.

**`g1-scan carte-unitree --lieu L [--etage E] [--delai 60]`** (S7) : s'abonne à `/unitree/slam_relocation/global_map` (sensor_msgs/PointCloud2, publiée une fois après le début d'un repérage 1804, d'après une documentation non officielle ; QoS fiable, transient_local essayée aussi), attend `--delai` secondes, puis écrit `cartes/<e>_unitree.pcd` et le nuage `cartes/<e>_unitree.nuage` (source `unitree`) ; code 1 et un message qui dit quoi faire si rien n'arrive (« lancez « Repérer le robot » pendant l'attente »). Le faux service slam_operate de la répétition la publie une fois après chaque 1804 réussi (nuage tiré du monde, dans le repère d'Unitree). À essayer à la séance 2.

**Ce qui part** (S2) : `atelier/scan/reconnaissance.py` et `evaluation.py` ; l'étape et son appel dans `session.py` (et `ATELIER_RECONNAISSANCE`) ; les routes `GET` et `PUT /api/scan/sessions/{s}/reconnaissance` et `GET /api/scan/sessions/{s}/monde` ; la revue de `scan.js` et ses styles ; les tests `test_reconnaissance*.py` ; le format (schéma `reconnaissance`, `regles_reconnaissance` et le type dans `validation.py`, les fonctions de `atelier/lieu/scans.py` de `nouvelle_reconnaissance` à `carte_sans_elements_retires`, leurs exports dans `atelier/lieu/__init__.py`, leurs tests dans `test_lieu_scans.py`, `test_contrats_scan.py` et `outils_scan.py`), et la documentation qui en parle. **Ce qui reste** : les champs `categorie`, `source` et `confiance` de `monde.yaml` (anciens lieux, monde du demo), `CATEGORIES_OBJETS` et la règle « une personne n'est pas sur la carte » d'un monde dessiné ; les anciens fichiers des sessions sur le disque (lus par personne).

### 12.6 Le robot (agent Robot)

**R1. La vitesse minimale du pont** (règle 11 du pont ; la section 10.3 sera complétée à l'assemblage) : `vitesse_effective` (`atelier.lieu.robot`, livrée, avec ses cas `EXEMPLES_VITESSE_MIN`) est l'algorithme de référence. Si la norme de (vx, vy) atteint `vitesse_min_lin`, ou |wz| atteint `vitesse_min_rot`, la consigne passe telle quelle (petites corrections comprises) ; sinon toute la consigne est petite : zones mortes, puis l'intention dominante (norme / minimum linéaire comparée à |wz| / minimum de rotation) : marche portée à la norme minimale dans la même direction (bornée pour qu'aucune composante ne dépasse son plafond), ou rotation sur place à ± `vitesse_min_rot`. Le pont, qui tourne sans atelier, en a une copie exacte, comparée sur 2 000 consignes au hasard par un test du paquet ; le joystick du pilotage appelle celle de `atelier.lieu.robot`.

| Paramètre du pont (`config/pont.yaml`) | Défaut | Contrat |
|---|---|---|
| `vitesse_min_lin` | 0,20 m/s (mesuré le 27/10) | `VITESSES_MIN_PONT["lin"]` ; 0 désactive ; refusé au-delà de 0,3 (`VITESSE_MIN_LIN_MAX`) ou de `vx_max` |
| `vitesse_min_rot` | 0,30 rad/s (à mesurer) | `VITESSES_MIN_PONT["rot"]` ; refusé au-delà de 0,5 (`VITESSE_MIN_ROT_MAX`) ou de `wz_max` ; `min_rotational_vel` du behavior_server au moins autant |
| `zone_morte_lin`, `zone_morte_rot` | 0,05 m/s, 0,10 rad/s | `ZONES_MORTES_PONT` ; 0 désactive ; pas plus que le minimum |
| `lire_mode` | true | R2 |
| `modes_marche` | [500, 501, 801] | `MODES_MARCHE` (une liste ; y ajouter 802 accepte la course) |

`vy_max` sous `vitesse_min_lin` (cas de `vitesse_max:=0.2`) : un avertissement seulement. Un réglage refusé arrête le nœud avec un message qui dit quoi corriger (« vx_max 0,1 est sous la vitesse minimale de marche 0,2 : le robot ne ferait aucun pas ; mettez vx_max ≥ 0,2, ou vitesse_min_lin:=0 pour une mesure ») ; les commandes du portique avec `vx_max:=0.1` (`docs/seance-robot.md`) sont à réécrire à l'assemblage. `/pont/etat` reçoit `demande` (la consigne après les plafonds, avant le minimum) et `minimums` (schéma livré) ; l'agent les ajoute aussi à `EXEMPLE_ETAT_PONT` (le test du paquet veut les mêmes champs que `Pont().etat()`). Pas d'une chorégraphie sous le minimum : avertissement de `regles_choregraphie` (« le vrai robot ne fera aucun pas à 0,1 m/s »), sans les monter ; `exemple_kpop` corrigé (vy 0,2 pendant 0,75 s, vx ± 0,2 pendant 0,5 s : même déplacement).

**R2. Le mode du robot** (règle 12) : le pont lit 7001 (`API_SPORT_GET_FSM_ID`, `parameter` `'{}'`, réponse `{"data": N}`) une fois par seconde (`PERIODE_LECTURE_MODE_S`), seulement quand le service sport a un abonné ou a déjà répondu ; ces lectures ne comptent ni dans `envoyees`, ni dans `reponses`, ni pour `robot_muet` et `refus`. Un mode lu il y a plus de 3 s (`DELAI_MODE_PERIME_S`), ou une lecture refusée : inconnu, **ne bloque rien**. Un mode connu hors de `modes_marche` : état **`pas_en_marche`**, `mouvement_permis` faux, un arrêt part si le robot bougeait, `/cmd_vel` ignoré, message `message_pas_en_marche(fsm)` (livré ; 802 : « mode course : passez en marche normale à la télécommande » ; 3 : « le robot est assis… » ; 0 ou 1 : « le robot n'est pas démarré… ») ; retour en marche : `pret`, et le mouvement ne reprend qu'avec un `/cmd_vel` neuf. Ordre des états (`PRIORITE_ETATS_PONT`) : `arret_verrouille`, `robot_muet`, `pas_en_marche`, `refus`, `pilotage`, `attente_reperage`, `arret`, `demarrage`, `en_mouvement`, `pret`. Champ **`mode_robot`** de `/pont/etat` : `{fsm, nom, en_marche, age_s}` (plus `modes_marche` et `lectures`), ou null avec `lire_mode` faux (schéma et règles livrés : `pas_en_marche` ⇔ `en_marche` faux, sauf verrou ou robot muet). Le format des 7105 ne change pas ; les critères 17, 19 et 20 acceptent les requêtes 7001 (16 : le faux service minimal ne rend pas de `data` : mode inconnu, rien de bloqué).

**Le faux G1** (`g1_jumeau`) : 501 après « Démarrer » (500 pendant 1 s, puis 501 ; 702 puis 501), `fsm_depart` 501 ; hors marche, 7105 répond **0 sans bouger**, comme le vrai en mode 3 (paramètre `hors_marche` : `ignorer` par défaut, `refuser` pour l'ancien 7301) ; un seuil de marche comme le vrai (paramètres du nœud `seuil_marche_m_s` 0,15 et `seuil_rotation_rad_s` 0,2 ; 0 dans la logique sans ROS, pour ses tests) ; le mode 802 atteignable par `fsm_depart:=802` ou le sujet d'essai `/g1_jumeau/mode` (std_msgs/Int32) ; 7001 rend toujours `{"data": fsm}`. **Le pilotage** (`g1_pilotage`, `atelier/lieu/pilotage.py`) : `in MODES_MARCHE` partout où il y avait `== FSM_MARCHE` (les danses ne sont plus refusées en 501) ; le joystick est refusé (409, `message_pas_en_marche`) quand le mode est connu et n'est ni la marche ni la course ; joystick et pas de chorégraphie passent par `vitesse_effective`. Les libellés des modes sont `NOMS_MODES` : l'agent Coquille corrige `MODES_FSM` de `pilotage.js` (501 « marche », 802 « course ») et l'affichage de `pas_en_marche`.

**R3. Nav2** (`ws/src/g1_nav`) : `nav2_g1_reel.yaml` sans marche arrière (`FollowPath.vx_min: 0.0`, `velocity_smoother.min_velocity: [0.0, -0.2, -0.6]`) ; `nav2_g1_simu.yaml` inchangé. `vitesse_max:=V` (`G1_VITESSE_MAX`, `--vitesse-max`) baisse aussi les vitesses maximales de Nav2 (`FollowPath.vx_max`, `vy_max`, `wz_max` du controller_server et `max_velocity` du velocity_smoother), dans la même proportion que les plafonds du pont ; il est **refusé sous 0,2 m/s** (`VITESSE_MAX_MIN`, message qui contient `MESSAGE_VITESSE_MAX_BASSE`, « le robot ne marche pas sous 0,2 m/s ») par `navigation.launch.py` (`plafonds_pont`), `g1-guide navigation`, `atelier.lieu.pilotage.limites_marche` et, côté conteneur, `docker/jetson.py` et `demarrer.sh` (agent Caméra). La tolérance d'orientation finale du guide devient un paramètre ROS du nœud guide (`tolerance_orientation_rad`) : la valeur d'aujourd'hui en simulation (0,09 rad) ; avec le pont, `navigation.launch.py` donne celle que l'agent choisit pour ne pas osciller avec 0,3 rad/s de rotation minimale (réglable, à mesurer à la séance 2 avec la latence) ; avec le pont, le ralenti du guide (`POURCENTAGE_MIN`) ne descend pas sous `100 × vitesse_min_lin / vitesse_max_nav2`. Le critère 22 (simulation, sans pont) garde ses 10°.

### 12.7 La caméra de poitrine (agent Caméra)

**Le conteneur** (`docker/`) : si la See3CAM est branchée sur le Jetson (`/dev/v4l/by-id/*See3CAM*-video-index0`, ou le `peripherique` by-id de `camera.yaml`), `g1-jetson demarrer` ajoute `--device <chemin résolu, /dev/videoN>:/dev/g1_camera` et `--group-add <groupe du périphérique>` (après `--memory`), et `-e G1_CAMERA=/dev/g1_camera` (`CAMERA_CONTENEUR`) ; sinon il démarre sans, avec un message ; jamais d'échec à cause de la caméra ; `G1_CAMERA=0` : pas de caméra. Avertissement si le lien USB n'est pas à 5000 (USB 3). `demarrer.sh` lance `camera_usb` quand `G1_CAMERA` existe (sauf `G1_LANCEMENT=commande`) et l'arrête avec le reste ; `presence.py` publie `camera` ; `g1-jetson verifier` la montre. L'image reçoit une couche de plus, après la 2c : `python3-pil` et `v4l-utils` (environ 5 Mo ; pas d'OpenCV, 580 Mo). `G1_VITESSE_MAX` sous 0,2 est refusé (`lire_vitesse_max`, `demarrer.sh`).

**Le nœud `camera_usb`** (paquet `g1_equipe`, nœud `camera_poitrine`, squelette déclaré) : capture par `v4l2-ctl` (YUYV, 1280 × 720 à 30 images par seconde par défaut ; tube agrandi à 1 Mo), exposition réglée au démarrage (`auto` par défaut : la See3CAM démarre en manuel, image noire dans une pièce sombre), JPEG par Pillow sans conversion de couleurs ; publication à 10 Hz sur **`/camera_poitrine/image/compressed`** (sensor_msgs/CompressedImage, `format: jpeg`, `frame_id: camera_poitrine`, QoS des capteurs : au mieux, profondeur 2), 640 pixels de large, qualité 70 ; état JSON à 1 Hz sur **`/camera_poitrine/etat`** (schéma `etat_camera`, livré). Paramètres : `source` (`v4l2`, `mire` ou `fichier`), `peripherique` (défaut : `camera.yaml`, sinon `/dev/g1_camera`), `lieu`, `largeur`, `hauteur`, `ips`, `frequence_hz`, `largeur_publiee`, `qualite_jpeg`, `exposition` (`auto` ou `manuelle`), `exposition_100us`, `gain`, `fichier` (YUYV brut, pour les tests) ; défauts lus dans `camera.yaml` quand il existe (champs facultatifs `exposition` et `publication`, livrés). Caméra absente ou débranchée : nouvel essai toutes les 2 s, `ouverte` faux et `erreur` en français, jamais de plantage ; à la sortie, `v4l2-ctl` est arrêté.

**`g1-visiteurs`** (`outils/visiteurs.py`, `bin/g1-visiteurs`, alias `gl-visiteurs` ; `.venv-projet` avec ROS chargé) : `g1-visiteurs [--lieu L] [--source robot|N|/dev/…|video.mp4] [--image] [--fenetre] [--modele yolo11n-pose.pt] [--frequence 10] [--confiance 0.5]` ; YOLO pose et ByteTrack (la classe personne), sur le GPU s'il y en a un ; `--source robot` (défaut) lit `/camera_poitrine/image/compressed`, sinon une caméra locale ou une vidéo. Il publie **`/visiteurs/detectes`** (schéma `personnes`, `source: camera`, à `detection.frequence_hz` au plus) avec, en plus des champs de la vague 4, **`boite`** `[x_min, y_min, x_max, y_max]` en pixels et **`image`** `{largeur, hauteur, numero, sujet}` (livrés) ; avec `--image`, `/visiteurs/image/compressed` (cadres dessinés, 2 à 5 Hz). La géométrie (focale, angle, distance par la taille de la personne ou du buste, position dans base_link, `regarde_robot`) est faite de fonctions pures dans `atelier/equipe/camera.py`, testées sans YOLO ; `detection.taille_personne_m` et `correction_distance` (facultatifs, livrés) servent à l'étalonnage. L'avertissement « une `vitesse_max` de personnalité sous 0,2 m/s n'a pas d'effet sur le vrai robot » (`equipe.py`) est facultatif.

**Dans l'Atelier** : le pont ROS 2 du serveur (`pont_ros.py`) s'abonne aux sujets de `SUJETS_IMAGES` (QoS des capteurs) et à `/camera_poitrine/etat`, et garde la dernière image de chacun (octets, numéro, heure de réception) ; routes `/api/camera/*` (12.4) ; `js/camera/flux.js` : `creerVueCamera(conteneur, {source, cadres, petit})` → `{demarrer, arreter, etat, detruire}` : le flux MJPEG dans `<img data-role=camera-flux>`, les cadres `boite` du champ `visiteurs` de `/ws/etat` dans `<canvas data-role=camera-cadres>` (mis à l'échelle de `image`), l'état dans `[data-role=camera-etat]` (« Pas d'image : … ») ; le flux s'arrête quand la vue est cachée ou l'onglet du navigateur invisible. La coque s'en sert pour la vue Caméra et l'incrustation dans Piloter et Naviguer ; l'écran `camera.js` montre en plus les réglages et les vues de dessus et de côté. Par le Wi-Fi sans DDS, le flux passera plus tard par le nœud pilotage (`GET /camera?source=poitrine`) : pas dans cette vague. `SUJETS_IMAGES` (livré) : `/camera_poitrine/image/compressed` et `/visiteurs/image/compressed` (sensor_msgs/CompressedImage), à part de `SUJETS_EQUIPE`, qui reste tout en std_msgs/String et reçoit `/camera_poitrine/etat`.

### 12.8 Les agents de la vague 5 et leurs fichiers

Aucun fichier n'a deux propriétaires. Un agent n'écrit que dans ses fichiers ; s'il a besoin d'un changement ailleurs, il ne le fait pas : il le note dans `ecarts_contrats` de son rapport (l'assemblage tranche) et fait sans, avec un bouchon. Un fichier qui n'est dans aucune ligne appartient à l'assemblage. Tous les agents travaillent dans le même arbre (pas de copie de travail par agent) : aucun commit sauf celui des contrats et ceux de l'assemblage, et jamais `git checkout`, `reset`, `stash` ni `clean`. Un nouveau fichier de test ou d'outil porte le préfixe de son agent.

| Agent | Domaine, partition, port | Possède (seul à y écrire) |
|---|---|---|
| Contrats, puis Assemblage | 100, `v5_contrats`, 8110 ; assemblage : 106, `v5_assemblage`, 8116 | `docs/plan-atelier-multi-agents.md`, `docs/journal-atelier.md`, `docs/seance-robot.md`, `README.md`, `.gitignore`, `setup.py`, `pytest.ini` ; `atelier/lieu/schemas/` (sauf `atelier/lieu/schemas/reconnaissance.schema.json`) ; `atelier/lieu/modeles.py`, `atelier/lieu/fichiers.py`, `atelier/lieu/verification.py`, `atelier/lieu/nuage.py` ; `atelier/serveur/main.py`, `atelier/serveur/communs.py`, `atelier/serveur/routes/__init__.py` ; `atelier/tests/test_contrats.py`, `atelier/tests/test_contrats_robot.py`, `atelier/tests/test_contrats_vague4.py`, `atelier/tests/test_contrats_vague5.py`, `atelier/tests/test_lieu_validation.py` ; `tests_e2e/tout.sh`, `tests_e2e/LISEZMOI.md`, `tests_e2e/commun.sh` ; `lieux/demo/` ; `lieux/seance/`, `lieux/bomboclat/`, `lieux/demo_scan/` (assemblage seulement, après sauvegarde) |
| Coquille (interface) | 101, `v5_coquille`, 8111 | `atelier/web/index.html`, `atelier/web/js/app.js`, `atelier/web/js/coque/`, `atelier/web/css/theme.css`, `atelier/web/css/atelier.css` ; les écrans `atelier/web/js/ecrans/{lieux,monde,carte,salles,itineraires,zones,simulation,pilotage,personnalites,dialogues}.js` ; `atelier/web/js/panneaux/`, `atelier/web/js/pilotage/`, `atelier/web/js/equipe/` ; les modules communs `atelier/web/js/{api,contexte,direct,formulaire,geometrie,historique,messages,plan,vue3d,teleop}.js` ; `atelier/web/css/{principal,passants,guide,pilotage,equipe}.css` ; `atelier/web/LISEZMOI.md` ; `atelier/serveur/etat.py`, `atelier/serveur/routes/{arret,liaison,simulation,robot,guide,lieux,plan,principal,passants}.py` ; tests `atelier/tests/test_coque*.py`, `atelier/tests/test_arret*.py`, `atelier/tests/test_liaison*.py`, `atelier/tests/{test_serveur_web,test_serveur_api,test_serveur_navigateur,test_robot_navigateur,test_principal_navigateur,test_guide_navigateur,test_passants_navigateur,test_pilotage_navigateur,test_pilotage_vue_navigateur,test_equipe_navigateur,test_guide_api,test_passants_serveur}.py` ; `tests_e2e/critere_09_interface.sh`, `tests_e2e/critere_31_*`, `tests_e2e/critere_36_*`, `tests_e2e/outils_coque_e2e.py` |
| Carte 3D | 102, `v5_carte3d`, 8112 | `atelier/web/js/carte3d/`, `atelier/web/css/carte3d.css`, `atelier/web/essais/carte3d.html` ; tests `atelier/tests/test_carte3d*.py` ; `tests_e2e/critere_32_*`, `tests_e2e/outils_carte3d_e2e.py` |
| Scan | 103, `v5_scan`, 8113 | `atelier/scan/`, `atelier/monde/` ; `atelier/lieu/scans.py`, `atelier/lieu/__init__.py`, `atelier/lieu/validation.py` (pour retirer le format de la reconnaissance seulement), `atelier/lieu/schemas/reconnaissance.schema.json` (à retirer) ; `atelier/serveur/routes/{scan,monde,nuage}.py` ; `atelier/web/js/ecrans/scan.js`, `atelier/web/js/nuage3d.js`, `atelier/web/css/scan.css` ; `bin/g1-scan`, `bin/gl-scan` ; tests `atelier/tests/test_scan_*.py`, `atelier/tests/test_serveur_scan*.py`, `atelier/tests/test_reconnaissance*.py`, `atelier/tests/test_monde_*.py`, `atelier/tests/test_nuage*.py`, `atelier/tests/{test_lieu_scans,test_contrats_scan,test_robot_faux_slam}.py`, `atelier/tests/outils_scan.py` ; `tests_e2e/critere_07_scan_simule.sh`, `tests_e2e/critere_11_*` à `critere_15_*`, `tests_e2e/critere_33_*`, `tests_e2e/outils_scan_e2e.py` |
| Robot | 104, `v5_robot`, 8114 | `ws/src/g1_bridge/`, `ws/src/g1_jumeau/`, `ws/src/g1_pilotage/`, `ws/src/g1_nav/` ; `atelier/lieu/robot.py`, `atelier/lieu/pilotage.py` ; `atelier/serveur/routes/pilotage.py` ; `choregraphies/` ; `bin/g1-guide`, `bin/g1-pilotage` ; tests `atelier/tests/test_pilotage_serveur.py`, `atelier/tests/test_pilotage_video.py`, `atelier/tests/test_pont*.py` ; `tests_e2e/critere_17_pont.sh`, `tests_e2e/critere_19_niveau2.sh`, `tests_e2e/critere_19_outils.py`, `tests_e2e/critere_20_securite.sh`, `tests_e2e/critere_20_outils.py`, `tests_e2e/critere_28_pilotage.sh`, `tests_e2e/critere_29_danses.sh`, `tests_e2e/critere_34_*`, `tests_e2e/outils_pont_e2e.py`, `tests_e2e/outils_pilotage_e2e.py`, `tests_e2e/outils_robot_e2e.py` |
| Caméra | 105, `v5_camera`, 8115 | `docker/`, `bin/g1-jetson`, `bin/gl-jetson`, `ws/src/g1_equipe/`, `outils/visiteurs.py`, `bin/g1-visiteurs`, `bin/gl-visiteurs`, `atelier/equipe/`, `atelier/lieu/equipe.py`, `atelier/serveur/pont_ros.py`, `atelier/serveur/routes/{camera,equipe}.py`, `atelier/web/js/camera/`, `atelier/web/js/ecrans/camera.js`, `atelier/web/css/camera.css`, `atelier/web/essais/camera.html` ; `docs/integration-equipe.md`, `docs/jetson.md` ; tests `atelier/tests/test_camera*.py`, `atelier/tests/test_visiteurs*.py`, `atelier/tests/{test_equipe_dialogue,test_equipe_fichiers,test_equipe_serveur,test_serveur_pont_ros}.py` ; `tests_e2e/critere_16_conteneur.sh`, `tests_e2e/critere_16_outils.py`, `tests_e2e/critere_30_equipe.sh`, `tests_e2e/outils_equipe_e2e.py`, `tests_e2e/critere_35_*`, `tests_e2e/outils_camera_e2e.py` |

Fichiers que personne ne touche dans cette vague (tous s'en servent ; un besoin va dans `ecarts_contrats`) : `atelier/lieu/{conversions,geometrie,principal,passants,comportement,commande}.py`, `atelier/serveur/processus.py`, `atelier/serveur/pietons.py`, `ws/src/g1_sim/`, `atelier/web/vendor/`, les autres commandes de `bin/` et de `setup/`, les autres critères et outils de `tests_e2e/`, les autres tests de `atelier/tests/` (dont `test_robot_serveur*.py`, `test_robot_reperage_ros.py`, `test_robot_communs.py`). Les agents ne touchent ni au journal ni au README : leur rapport sert à l'assemblage.

### 12.9 Dépendances entre agents : contrats et bouchons

| Qui a besoin | De quoi | Chez qui | Contrat | En attendant |
|---|---|---|---|---|
| Coquille | la carte 3D dans la vue centrale | Carte 3D | `creerCarte3D` (12.3 ; squelette livré, méthodes sans effet) | le squelette : vue 3D vide, le Plan 2D marche |
| Carte 3D | sa place dans la coque, Placer › Salle en 3D | Coquille | contrat des écrans (`options.carte3d`) ; `salles.js` écoute `surPose` | page d'essai `essais/carte3d.html` ; critère 32 « en attente » (77) tant que la coque ou le placement en 3D manquent |
| Coquille, Carte 3D | le nuage d'un étage | Scan | `GET …/nuage` et ses en-têtes (12.4), `atelier.lieu.nuage` | un nuage de test écrit par `ecrire_nuage` dans une copie du demo, et `window.fetch` remplacé dans la page (la route répond 501) |
| Coquille | la vue Caméra | Caméra | `creerVueCamera` (12.7 ; squelette livré) | le squelette : la vue dit qu'il n'y a pas d'image |
| Coquille | l'état `pas_en_marche` et `mode_robot` | Robot | schéma `etat_pont`, `NOMS_MODES`, `message_pas_en_marche` (livrés) | `EXEMPLE_ETAT_PONT_V5` publié par un faux `/pont/etat` |
| Coquille (critère 36) | l'arrêt du pilotage | Robot | `POST /api/pilotage/arret` (vague 4, inchangé) | le nœud d'aujourd'hui |
| Scan | l'écran plein écran et les commandes Scanner | Coquille | `options.coque.pleinEcran`, ids `scan.*` | `ouvrir(racine)` seul : l'écran prend toute la racine |
| Caméra | `VITESSE_MAX_MIN` dans le conteneur | Robot | valeur livrée dans `atelier.lieu.robot` (0,2) | — |
| Caméra | la vue Caméra dans la coque | Coquille | la vue centrale appelle `creerVueCamera` | page d'essai `essais/camera.html` ; la partie navigateur du critère 35 « en attente » sans la coque |
| Scan (critère 33), Robot (critère 34) | — | eux-mêmes | `g1_sim` ne change pas (le SDF du monde maillé a des `uri` absolues) | — |

### 12.10 Critères de recette 31 à 36

Tous sans robot et sans fenêtre, sur des copies du demo ; `tests_e2e/tout.sh` lance les trente-six et affiche « N / 36 ». Un critère dont une pièce d'un autre agent manque répond « en attente » (77) en disant laquelle.

31. **Accueil, espace de travail et défilement** (`critere_31_coque.sh`, agent Coquille). Firefox sans fenêtre :
    - `/` sans hash : l'accueil, les deux cartes, le demo dans la liste (présélectionné si `atelier.lieu` vaut demo), Ouvrir ; Simulation + demo + Ouvrir : `[data-role=espace][data-mode=simu]`, ruban de 4 onglets (`dessiner`, `placer`, `simuler`, `equipe`), aucune commande `pilotage.*` ; retour à l'accueil, Robot réel avec « Répétition sans robot » : `[data-mode=repetition]`, 5 onglets (`scanner`, `placer`, `naviguer`, `piloter`, `equipe`), les vérifications du mode Réel avec leur `data-etat`, sans aucune boîte native ;
    - à 1366 × 768 et à 1920 × 1080, dans les deux modes, pour chaque onglet du ruban et chaque commande qui n'est pas Avancé : la page ne défile pas (`scrollHeight` et `scrollWidth` de la page au plus la taille de la fenêtre, à 1 pixel près) ; barre d'outils, ruban, arbre, vue, panneau et barre d'état entièrement dans la fenêtre ; chaque élément cliquable visible (`button`, `input`, `select`, `a[href]`) de la barre d'outils, du ruban, de l'arbre et du panneau peut être amené à l'écran par `scrollIntoView` et y est alors entier et non recouvert (`elementFromPoint` en son centre le rend, ou un de ses enfants) ; ARRÊT visible et cliquable partout ;
    - les anciens hash (`/?recharger=1#salles`, `#simulation`, `#scan`, `#pilotage`, `#camera`) mènent à l'écran attendu (`[data-ecran=<id>]`) sans l'accueil ;
    - le thème clair (`[data-role=theme]`) change `data-theme` et `atelier.theme` ; la vue 3D reste sombre ;
    - `window.erreursAtelier` reste vide.
32. **Placer l'accueil et une salle dans la carte 3D** (`critere_32_carte3d.sh`, agent Carte 3D). Firefox sans fenêtre (WebGL) ; copie du demo avec un nuage d'étage de test (`cartes/rdc.nuage.bin`, écrit par `ecrire_nuage` depuis le monde du demo : murs et objets échantillonnés tous les 5 cm) :
    - Réel (répétition) › Placer : la vue 3D montre le nuage (`window.carte3d.etat()` : `webgl` vrai, `points` = celui de l'en-tête) ;
    - commande `salles.accueil`, appui sur le sol en (3,0 ; 9,5) (`versEcran`), glissé vers (4,0 ; 9,5), ✓ OK : dans `salles.yaml`, le point principal est à 0,05 m et 2° près de (3,0 ; 9,5 ; 0), et `accueil` de `lieu.yaml` et `depart_robot` aussi ;
    - commande `salles.salle`, nouvelle salle « Essai 3D » posée en (12,0 ; 4,0), tournée vers −90°, ✓ OK : `salles.yaml` la contient à 0,05 m et 2° près, avec son nœud dans `itineraires.yaml` ;
    - en Plan 2D, les marqueurs de l'accueil et de la salle sont à ces coordonnées (lat = y, lng = x, à 0,05 m près) ; une salle déplacée en 2D est retrouvée en 3D (`versEcran` de sa nouvelle pose à 3 pixels près de son épingle) ;
    - Dessus, Iso, Face et Recadrer changent la caméra ; la molette zoome vers le pointeur (le point du sol sous le pointeur reste à 2 pixels près) ; Annuler puis Rétablir d'un placement ;
    - WebGL coupé (préférence `webgl.disabled`) : `[data-role=carte3d-sans-webgl]`, et le Plan 2D reste utilisable ; aucune erreur dans la page.
33. **Scan corrigé, sans reconnaissance, et monde maillé** (`critere_33_scan_corrige.sh`, agent Scan) :
    - scan simulé du demo (`g1-scan demarrer --mode simu --explorer`, tour complet) : `termine`, étapes `carte_3d`, `carte_2d`, `nuage` ; ni `reconnaissance.yaml` ni `monde_scan.monde.yaml` ; `rapport.json` : `nuages.ignores` au plus 1 % de `nuages.recus`, pas de `reconnaissance` ; `nuage_affichage` conforme (`lire_nuage`), au moins 50 000 points, grille 0,05, sol à 0,02 m près de z = 0 ;
    - carte propre : comparée à la carte du monde du demo, précision au moins 0,98 (part des pixels occupés du scan à 0,10 m au plus d'un pixel occupé du monde) et recouvrement au moins 0,90 ;
    - le « damier » : la même session copiée par l'outil du test avec le sol incliné de 0,6° et abaissé de 1,27 m (comme le repère du vrai G1), les nuages à horodatage nul et l'odométrie décalée de −138 s (comme le bag du 27/10), puis `g1-scan traiter --refaire` : mêmes seuils (précision 0,98, recouvrement 0,90), `nuages.ignores` au plus 1 %, `sol.inclinaison_deg` entre 0,5 et 0,7 ; les résultats d'avant sont dans `ancien_<horodatage>/` ;
    - adoption (`POST …/adopter`) : `cartes/rdc.nuage.bin` et `.json` (source `scan`), `mondes/rdc_carte.stl` et `carte_extrudee` (hauteur 1,5) dans le monde, murs et objets dessinés retirés (gardés dans `monde_remplace.monde.yaml`), piétons gardés ; `g1-lieu valider` sans erreur ; `GET …/nuage`, `…/nuage/info` et `…/monde/maillage` les servent ;
    - Gazebo sans fenêtre sur ce monde maillé : au moins 0,9 fois le temps réel (temps de `/clock` sur 20 s de temps mural) ; `/points` voit le maillage ; le robot proxy envoyé 3 s vers un mur à 1 m s'arrête contre lui (jamais au-delà) ;
    - `g1-scan carte-unitree` pendant un repérage en répétition : `cartes/rdc_unitree.pcd` et le nuage `source: unitree` ; aucun processus restant.
34. **Pont : vitesse minimale et mode du robot** (`critere_34_pont_modes.sh`, agent Robot). Gazebo `--jumeau` (faux G1 avec son seuil de marche), pont avec ses défauts :
    - `/cmd_vel` vx 0,1 pendant 3 s : les 7105 portent (0,2 ; 0 ; 0) (norme au moins 0,2, même direction) ; la vérité avance de 0,6 ± 0,2 m ; `/pont/etat` : `demande` 0,1, `consigne` 0,2, `minimums` ; wz 0,15 seul : 7105 à (0 ; 0 ; 0,3) et le robot tourne ; vx 0,03 : aucun 7105 non nul, robot immobile (moins de 2 cm) ;
    - faux G1 assis (3) : `pas_en_marche` en moins de 2 s, `mode_robot.fsm` 3, message avec « assis » ; `/cmd_vel` vx 0,3 pendant 3 s : aucun 7105 non nul, robot immobile ; « Démarrer » (500 puis 501) : `pret` en moins de 3 s sans mouvement, puis un `/cmd_vel` neuf : `en_mouvement`, le robot avance ; mode 802 : `pas_en_marche`, message avec « course » ;
    - 7001 à 1 Hz (de 0,7 à 1,3 par seconde), au format `'{}'` ; chaque 7105 au format de 10.3 ; `/pont/etat` conforme (schéma et règles) tout du long ;
    - refus : `vitesse_max:=0.15` (lancement, `g1-guide navigation --vitesse-max 0.15`) avec « le robot ne marche pas sous 0,2 m/s » ; `vx_max:=0.1` sans `vitesse_min_lin:=0` refusé par le pont ; `nav2_g1_reel.yaml` : `vx_min` 0,0 ; avec `vitesse_max:=0.25`, les vitesses maximales de Nav2 lancé valent 0,25 (paramètres lus sur les nœuds) ; aucun processus restant.
35. **Caméra : de la fausse source aux visiteurs** (`critere_35_camera.sh`, agent Caméra) :
    - `camera_usb` avec `source:=fichier` (vidéo YUYV fabriquée par le test depuis `bus.jpg` d'ultralytics, 1280 × 720) : `/camera_poitrine/image/compressed` à 8 Hz au moins, JPEG lisibles de 640 pixels de large ; `/camera_poitrine/etat` conforme (`etat_camera`), `ouverte` vrai ;
    - l'Atelier dans le même domaine : `GET /api/camera/image?source=poitrine` rend un JPEG de moins de 1 s ; `GET /api/camera/flux?source=poitrine&images=5` rend 5 images en moins de 2 s ; `GET /api/camera/etat` cohérent ;
    - `g1-visiteurs --source robot` : `/visiteurs/detectes` conforme au schéma `personnes` (`source: camera`), au moins 3 personnes sur l'image du bus, chacune avec une `boite` dans l'`image` (640 × 360), en moins de 60 s après le lancement (chargement du modèle) ; le champ `visiteurs` de `/ws/etat` les montre ;
    - la vue Caméra dans Firefox sans fenêtre : `[data-role=camera-flux]` reçoit des images (`naturalWidth` 640) et `[data-role=camera-cadres]` dessine au moins 3 cadres ;
    - conteneur, à blanc (`g1-jetson demarrer --local --dry-run`) : avec une fausse caméra by-id, `--device …:/dev/g1_camera`, `--group-add` et `G1_CAMERA` ; sans caméra, ni `--device` ni échec ; `G1_VITESSE_MAX=0.15` refusé ;
    - sans le modèle YOLO (`modeles/yolo/yolo11n-pose.pt`) : « en attente » (77) ; aucun processus restant.
36. **ARRÊT global** (`critere_36_arret.sh`, agent Coquille) :
    - répétition depuis l'Atelier (`POST /api/simulation/demarrer {mode: repetition}`, repérage), « Y aller » vers b204 ; quand le robot roule (plus de 0,15 m/s, vérité `/g1_jumeau/odom`) : `POST /api/arret {mode: repetition}` répond en moins de 1 s (200, `parties.guide.ok` et `parties.verrou.ok` vrais) ; le robot est arrêté (moins de 2 cm/s) moins de 1 s après la demande ; `/guide/etat` quitte `en_route` ; `/pont/etat` passe à `arret_verrouille` en moins de 1 s ;
    - verrou posé : un nouveau « Y aller » laisse le robot immobile (moins de 5 cm) pendant 5 s ; `GET /api/arret` dit `verrou: true` ; `POST /api/arret/debloquer`, puis « Y aller » : le robot repart (0,3 m au moins) ;
    - correction du 01/11/2026 (12.15) : le « Y aller » posé pendant le verrou est refusé par le guide (`echec`, `immobilise` `verrou`) et rien ne repart pendant 5 s après « Débloquer » ; en route, « Bloquer » (`POST /api/robot/arret {verrou: true}`) arrête le robot en moins de 1 s et met le guide en `attente` avec `immobilise` `verrou` (ni `bloque`, ni `detour`, ni `echec`, ni retour pendant 5 s), puis « Débloquer » : **aucun mouvement pendant 15 s** (moins de 5 cm, aucun 7105 non nul), guide en `attente` sans `immobilise` (« Robot débloqué : il attend un nouveau « Y aller ». ») ; de même avec le verrou en ligne de commande (`/pont/arret`, transient_local, 8 s) et avec le faux G1 assis puis remis en marche (`pas_en_marche`, « Y aller » refusé entre-temps, 8 s) ; puis un nouveau « Y aller » repart (0,3 m) ; avec le pilotage, le joystick tenu est arrêté par « Bloquer », refusé pendant le blocage, et ne relance pas le robot au « Débloquer » tant qu'il n'est pas lâché ; relecture du 01/11/2026 : « Bloquer » publie bien `/guide/stop` (vu par l'observateur du test) et son champ `guide` compte un guide ; dans Firefox, pendant le blocage, les boutons « Y aller » de Naviguer et la commande du ruban sont grisés et le panneau dit « Robot bloqué » ; arrivé à une salle proche, retour automatique prévu, le menu « Y aller » du ruban ouvert, Échap envoie `POST /api/arret`, et rien ne part pendant 15 s après « Débloquer » ;
    - simulation, téléopération à 0,3 m/s : `POST /api/arret {mode: simu}` arrête le robot (vérité `/odom`) en moins de 1 s, sans verrou (`verrou` faux, rien publié sur `/pont/arret`) ;
    - répétition, nœud pilotage, main prise, joystick à vx 0,3 par `/ws/pilotage` : `POST /api/arret` → StopMove reçu par le faux G1 en moins de 1 s, robot arrêté ; nœud pilotage arrêté : `POST /api/arret` répond quand même en moins de 1 s, `parties.pilotage.ok` faux avec un message, le reste arrêté ;
    - dans Firefox, le clic sur `[data-role=arret]` et la touche Échap envoient `POST /api/arret` ; en Réel, le bouton passe à « Débloquer » (`data-etat=bloque`) ;
    - jamais d'erreur 500 ; aucun processus restant.

Critères existants à adapter, chacun par l'agent qui possède son script (12.8) : 7 et 11 à 15 (Scan : 12 devient `critere_12_carte_du_scan.sh`, la carte et le nuage de la session du 11 sans reconnaissance ; 13 : adoption, monde maillé, simulation et une salle atteinte ; 15 : l'écran de scan dans Firefox) ; 9 (Coquille : le parcours réécrit sur la coque) ; 16 et 30 (Caméra) ; 17, 19, 20, 28 et 29 (Robot : lectures 7001 admises, mode 501, `orienter` des outils au-dessus du seuil de rotation). Les critères 1 à 30 doivent toujours passer ; chaque agent relance ceux qu'il peut casser : Coquille 9, 10, 29, 30 (parties navigateur) ; Carte 3D 9 ; Scan 2, 3, 7, 11 à 15 ; Robot 4, 5, 16 à 22, 26 à 29 ; Caméra 16, 30.

### 12.11 Règles communes de la vague 5

Celles des sections 9.9, 10.10 et 11.10, plus :
- dans chaque terminal : `export ROS_DOMAIN_ID=<domaine> ROS_LOCALHOST_ONLY=1 IGN_PARTITION=v5_<agent>` (12.8) ; l'Atelier sur son port seulement (jamais 8000, celui de l'utilisateur) ; les critères : `E2E_DOMAINE=<domaine> E2E_PARTITION=v5_<agent> tests_e2e/tout.sh N` (`commun.sh` met `ROS_LOCALHOST_ONLY=0` : Nav2 lance trop de participants pour lo) ;
- compilation : `cd ~/robot-g1/ws && colcon --log-base log_v5_<agent> build --symlink-install --packages-select <paquets> --build-base build_v5_<agent> --install-base install_v5_<agent>`, puis `source ~/robot-g1/ws/install_v5_<agent>/local_setup.bash` par-dessus `setup/env.sh` ; jamais `ws/build` ni `ws/install` (l'assemblage seulement) ; les critères prennent les paquets de l'agent avec `E2E_OVERLAY=~/robot-g1/ws/install_v5_<agent>`. `ws/install` est en `--symlink-install` : un fichier Python modifié dans `ws/src` est vu tout de suite par tous (un nouvel exécutable demande une compilation) ;
- tests : le Python du projet (`~/robot-g1/.venv-projet/bin/python -m pytest`), avec `PYTHONDONTWRITEBYTECODE=1` et `-p no:cacheprovider` ; les `test_logique.py` des paquets ROS un par un (même nom dans plusieurs paquets) ; chaque agent lance les tests de son périmètre, ceux qui en dépendent, et `atelier/tests/test_contrats_vague5.py` ; `atelier/tests/test_robot_reperage_ros.py` lance ses programmes avec `ROS_LOCALHOST_ONLY=0` : le lancer aussi avec `ROS_LOCALHOST_ONLY=0` (dans son domaine), sinon ses quatre tests échouent (constaté le 31/10) et laissent des faux services et des relais ; après un test qui échoue, chercher les restes avec `pgrep -af '[p]ytest-of'` (les crochets évitent que `pgrep` ou `pkill` se trouvent eux-mêmes) ; `ws/src/g1_nav/test/test_noeud_guide.py::test_lieu_introuvable` échoue avec `ROS_LOCALHOST_ONLY=1` (CycloneDDS écrit un avertissement sur la sortie d'erreur avant le message du guide) : l'agent Robot le rend indépendant de ce réglage ;
- JavaScript ES2017 lisible par esprima (ni `?.`, ni `??`, ni champs de classe, ni `catch` sans paramètre), sans compilation ; aucune donnée des fichiers insérée en HTML (`textContent`, `value`) ; aucune adresse Internet ; textes et noms en français ; chaque fonction nouvelle a ses tests ;
- `lieux/demo` est la référence des tests (on travaille sur des copies : `ATELIER_LIEUX`) ; `lieux/seance`, `lieux/bomboclat` et `lieux/demo_scan` sont à l'utilisateur ;
- **jamais rien sur eno2, jamais de ssh ni de ping vers 192.168.123.x** (les tests de la liaison visent `ATELIER_PC1=127.0.0.1` et `ATELIER_INTERFACE_ROBOT=lo`) ; le robot n'est pas branché : faux G1, faux SLAM, répétition, simulation ;
- fichiers temporaires, captures et journaux dans le dossier de travail de l'agent, hors du dépôt ;
- à la fin : tous les processus et conteneurs lancés sont arrêtés (`pgrep`, `docker ps -a`) ; le rapport de l'agent dit honnêtement ce qui marche, ce qui a échoué et ce qui n'a pas pu être essayé, avec les commandes exactes ; l'assemblage écrit le journal et le README.

### 12.12 Ce qui reste à vérifier sur le robot (séance 2)

En plus des listes de 10.9 et 11.11 :
1. **pont** : le seuil réel de marche (0,12, 0,15 et 0,18 m/s ; de côté ; en diagonale (0,1 ; 0,1) pour l'hypothèse de la norme) et de rotation (0,1 à 0,4 rad/s), avec les minimums à 0 ; la latence et la distance d'arrêt à 0,2 m/s ; l'angle réel d'un Spin de 90° ; puis le pont avec ses défauts (0,1 demandé : marche à 0,2) ;
2. **modes** : 7001 dans chaque posture (couple nul, amorti, assis, accroupi, debout, marche, course, et après « Démarrer » : 500 puis 501 ?) ; 7002 ; la réponse de 7105 hors marche ; une danse depuis 501 ;
3. **caméra** : la See3CAM sur un port USB 3 du Jetson, `g1-jetson verifier`, 10 images par seconde sur le PC (`ros2 topic hz`, taille réelle), l'exposition automatique en lumière, le champ de vision (le mode 640 × 480 montre-t-il tout le champ ?), la position sur le robot, les distances à 1, 2, 3 et 4 m (`correction_distance`), la salutation ;
4. **carte d'Unitree** : `g1-scan carte-unitree` pendant « Repérer le robot » ;
5. **scan** : un nouveau scan plus lent (moins de 0,5 m/s, virages lents, personne entre le robot et les murs), comparé à celui d'Unitree Explore ; la carte du 27/10 retraitée colle-t-elle au bâtiment ;
6. **Nav2** : pas de marche arrière, `vitesse_max` transmise à Nav2, rotation finale du guide sans oscillation.

### 12.13 Précisions de l'assemblage (vague 5)

Écarts signalés par les agents et acceptés à l'assemblage (31/10/2026), comme 10.12 et 11.12. Ils complètent 12.2 à 12.7 ; en cas de doute, ce paragraphe fait foi.

**La coque** (12.2) :
- le ruban fait **92 px** (au lieu de 84 ; jeton `--h-ruban`), onglets de 28 px, libellés sur une ligne, titre du groupe Spectacle ; la barre d'outils a une partie gauche `.barre-outils-gauche` qui se coupe (jamais ARRÊT, toujours entier, même à 800 px) ;
- deux événements de la page : **`atelier-arret`** (émis par le bouton ARRÊT et Échap ; l'écran Piloter lâche ses manettes) et **`atelier-pointeur`** (x, y du Plan 2D vers la barre d'état) ;
- icônes : classe `ico-<nom>` ; jeton `--accueil-texte` (contraste AA de l'accueil en thème clair) ; « Ce qui tourne » n'apparaît dans la barre d'état que quand quelque chose tourne (toujours dans le menu ⚙) ; sous 900 px, le thème passe dans le menu ⚙ ; repères `data-role=etat-outil` et `bouton-ce-qui-tourne` ; cibles de 44 px sur écran tactile (`pointer: coarse`) ;
- ajouts de l'assemblage : la commande Avancé **`camera.reglages`** (Équipe › ⚙ › Réglages de la caméra : l'écran Caméra s'ouvre sur ses réglages avancés) ; le plein écran (`pleinEcran(true)`, écran de scan) a une grille de trois rangées (le ruban caché ne garde pas sa rangée : le centre tombait dans une rangée de 0 px) ; en Simulation, la carte 2D est posée au sol sous le monde par défaut (calque `carte2d`, décision I7) ; la coque transmet `perimee` à `afficherRobot` (en répétition et sur le robot, une pose de repérage trop vieille est estompée) ; l'écran Salles écoute `surPose(fn, {genres: ['salle']})` ; l'incrustation de la caméra de poitrine (Naviguer) se cache, et son flux s'arrête, quand la vue centrale est la vue Caméra (elle couvrait l'image) ;
- l'incrustation de la caméra de poitrine n'est que dans Naviguer : Piloter garde la Vue du robot de la vague 4 (carte, G1 en 3D, caméra de la tête), et la caméra de poitrine se regarde dans la vue Caméra de Naviguer ou dans Équipe › Caméra (à ajouter plus tard si besoin, sans couvrir les joysticks) ;
- les nœuds d'itinéraire se placent en Plan 2D (le module sait les placer en 3D : outil `noeud`, couloirs qui suivent ; le branchement dans l'écran Itinéraires reste à faire) ;
- les messages du serveur parlent le vocabulaire du ruban : « Simulation › Dessiner », « Réel › Scanner », « Placer › Accueil », « Simuler › Arrêter », « Réel › Piloter », « Équipe › Personnalités » (plus « l'onglet … » ni « Fabriquer la carte », qui n'existe plus : la carte se refait après « Enregistrer », ou par ⚙ Avancé › Refaire la carte).

**La carte 3D** (12.3), ajouts compatibles du module : `surPose(fn, {genres})` (un repère d'un genre ne se glisse que si un écran écoute ses poses ; l'écran qui accepte une pose rappelle `afficherSalles` ou `afficherItineraires` pendant l'appel, sinon le repère revient à sa place) ; options `margeHaut` (56 px, sous la barre flottante), `barre`, `reglages`, `animation`, `conserverImage` ; méthodes `taillePoints`, `positionRepere`, `dessiner` ; champs de `etat()` : `pointsSol`, `modifiables`, `couloirs`, `selection`, `salles`, `principal`, `noeuds`, `zones`, `robot`, `bornes`, `taille` ; `SEUIL_SOL` (0,12 m) : les points du sol n'écrivent pas la profondeur et sont dessinés sous les repères posés au sol (zones et couloirs visibles sur un sol dense) ; étiquettes des salles placées sans chevauchement (`placerEtiquettes`). WebGL de Firefox sans fenêtre : avec l'affichage X de la session (`DISPLAY=:1`) ; `tests_e2e/commun.sh` retire `DISPLAY`, `critere_32_carte3d.sh` le garde pour Firefox seul et répond « en attente » (77) sans affichage.

**Le scan** (12.5) : à l'adoption d'un étage déjà scanné, les murs et objets `source: scan` d'une ancienne reconnaissance sont retirés du monde (copie dans `monde_remplace.monde.yaml` de la session ; 109 éléments pour `seance`) : la carte extrudée les remplace ; les ajouts de l'utilisateur restent. `POST …/monde/generer` n'ajoute `fichiers.maillage` que pour un étage scanné. `rapport.json` reçoit `nuages {recus, utilises, ignores}`, `base_de_temps`, `mobiles_retires`, `sol {plan, inclinaison_deg, methode, points}` et `affichage`, et perd `reconnaissance` et `carte.sol` (un nombre). `carte2d.fabriquer_carte` rend le sol en dictionnaire (`atelier.scan.sol`) ; `g1-carte-2d` ne change pas. Retrait des mobiles : rayon de 0,30 m autour du trajet, de 0,08 à 2 m au-dessus du sol (`RAYON_TRAJET`, `HAUTEURS_MOBILES`, à revoir à la séance 2 si une porte étroite est rognée). Le scan du 27/10 a été retraité et adopté pour `seance` (journal) ; la carte nettoyée à la main n'est plus nécessaire.

**Le robot** (12.6) :
- un pas de chorégraphie sous le minimum ne passe pas par `regles_choregraphie` (dont les messages refusent le fichier) : `avertissements_choregraphie` (non bloquant) le signale, et à la lecture le pas passe par `vitesse_effective` avec une durée raccourcie, même trajet (`pas_effectif`, « fait 2 fois plus vite, pendant 0,5 s : même trajet ») ; le fichier n'est pas modifié ;
- seuils du faux G1 : 0,15 m/s et 0,2 rad/s (entre 0,1, aucun pas, et 0,2, marche) ;
- le guide a trois réglages réglables en marche, avec des bornes (`ros2 param set /guide …`) : `tolerance_orientation_rad` (0,09 rad sans pont ; **0,40 rad avec le pont**, justifié par `g1_nav/rotation_pont.py` : le dépassement d'une rotation va de 12° à 26° selon le retard du robot), `anticipation_rotation_rad` (0) et `pourcentage_min` (10 % ; avec le pont, au moins 100 × `vitesse_min_lin` / `vx_max` de Nav2) ;
- outils sans commande dans `bin/`, pour la séance 2 : `python3 -m g1_bridge.mesure marche|rotation|cap` (échelons par `/cmd_vel`, à travers le pont, lus sur l'odométrie du robot) et `python3 -m g1_nav.rotation_pont` (simulation de la rotation finale ; conseille les deux `ros2 param set`) ;
- champs facultatifs nouveaux : `seuils` et `sous_seuil` de `/g1_jumeau/etat`, `marche_possible`, `hors_marche`, `ignores_hors_marche` de son champ `robot` ; `vitesse_max_refusee`, `vitesses_min`, `modes_marche` de `GET /api/pilotage/config` ; `avertissements` des routes des chorégraphies ; `EXEMPLE_ETAT_PONT` contient `demande`, `minimums` et `mode_robot` ;
- ajout de l'assemblage : **après un ARRÊT, le nœud pilotage ignore le joystick tenu** (refus 409 « ARRÊT demandé. Lâchez le joystick, puis reprenez-le pour repartir. ») jusqu'à un ordre nul, un « lacher », la fermeture du WebSocket ou l'ouverture d'un nouveau joystick (`joystick_bloque`) : un pouce resté sur le manche ne relance pas le robot, même avec un client qui ne lâche pas ses manettes. Relecture du 01/11/2026 (12.15) : de même après tout ordre du joystick refusé pendant que le manche est tenu (robot bloqué, hors du mode marche, robot muet, danse ou chorégraphie).

**La caméra** (12.7) : contrat de fait entre `js/camera/flux.js` et `atelier.css` : sur `[data-role=camera-vue]`, `data-etat` (`arrete`, `attente`, `sans-image`, `ok`), `data-flux` (`oui`, `non`), `data-images` (nombre) et `data-source` ; sur `[data-role=camera-cadres]`, `data-cadres` (nombre) ; l'incrustation se replie selon `data-etat`. Le flux MJPEG respecte « `ips` par seconde au plus » en moyenne (`atelier.equipe.images.Cadence`). La couche 2d de l'image du Jetson pèse 9 Mo sur amd64 (et non 5). Le critère 16 refait `g1-jetson:amd64` quand le contexte de l'image change (1 min avec le cache). L'exemple `camera.yaml` nomme la See3CAM du projet par son chemin stable (`/dev/v4l/by-id/usb-e-con_Systems_See3CAM_11CUG_1A15C950-video-index0`) ; dans le conteneur, le nœud reçoit toujours `peripherique:=/dev/g1_camera`. `camera_usb` lit les erreurs de `v4l2-ctl` sur ses deux sorties (la version 1.22 écrit ses échecs d'ioctl sur la sortie standard).

**Les critères** (12.10) : le critère 31 mesure aussi à 1600 × 1000 et en mode Réel sans répétition (186 mesures) ; le critère 36 lit Nav2 par le service `/bt_navigator/get_state` (le champ `ros.nav2` n'existe que dans `/ws/etat`) ; il réutilise sans les modifier `critere_18_outils.py`, `outils_pont_e2e.py` et `outils_pilotage_e2e.py`. `tests_e2e/tout.sh` se lance depuis un terminal de la session graphique (`DISPLAY=:1`) pour que le critère 32 ait WebGL.

### 12.14 Corrections après la revue (vague 5)

Deux relecteurs (interface dans Firefox avec WebGL, et code) ont relevé 30 défauts le 31/10/2026 ; le correcteur (intégrateur) les a reproduits et corrigés. Ce paragraphe complète 12.2 à 12.13 et fait foi quand il les contredit.

**La coque** (12.2) :
- **Échap** (I5 précisé) : l'ARRÊT dès que le robot bouge ou peut repartir à l'instant (guide en mission, ou qui partira seul : retour automatique prévu, départ qui attend la navigation, champ `actif` de `/guide/etat` (relecture du 01/11/2026, 12.15) ; pont qui envoie des consignes, pilotage qui a la main, flèches tenues), et quand quelque chose tourne (simulation, navigation, pilotage, scan, pont vivant) si la touche ne sert pas déjà à fermer un menu, une fenêtre, un volet ou un tiroir, à annuler une saisie, un outil de Placer ou de Dessiner, ou un geste de la carte 3D ; sans nouvelles du serveur, l'ARRÊT ; rien ne tourne : Échap ferme et annule seulement, et la barre d'état dit qu'il n'y a rien à arrêter. Fonctions pures `etatMouvement(d, local)`, `guideActif(g)` et `decisionEchap(m, servi)` de `js/coque/arret.js` ; la coque écoute le clavier en capture sur la fenêtre. Le bouton ARRÊT, lui, part toujours ;
- **ARRÊT** : chaque appui envoie sa demande (la route est idempotente), avec un délai de 1,5 s (`DELAI_ARRET_MS`) ; sans réponse : « le serveur de l'Atelier ne répond pas : arrêtez le robot avec la télécommande ». « Débloquer » suit aussi le verrou du pont (`verrouVu(d)` : champ `arret` ou `pont.verrou` frais). L'**accueil** montre l'ARRÊT (et Échap l'envoie) quand quelque chose tourne encore ; `afficherAccueil` reçoit `modeArret` et rend `{fermer, arreter, formulaireOuvert}` ;
- **arbre replié** : la languette `[data-role=deplier-arbre]` (« ▸ Le lieu », au bord gauche de la vue) le rouvre au-dessus de 1100 px ; ⚙ › Montrer / Cacher l'arbre du lieu. Les points de l'arbre et des listes des panneaux sont dans l'ordre des épingles de la vue 3D, avec leur numéro (`sallesDansLOrdre` de `js/carte3d/geometrie3d.js`, classe `numero-salle`) ; nœuds nommés comme leur salle, sinon leur identifiant rendu lisible ; décomptes écrits (« 13 nœuds », « 18 murs · 12 objets ») ;
- **panneau** (`ouvrirPanneau`) : ✓ et ✗ restent les mêmes boutons (seuls action, texte et état changent ; un ancien appel n'a plus d'effet) ; option `actifSurSaisie` (`panneauEdition`) : ✓ et ✗ s'activent dès qu'on tape ; redessiné avec le même titre, le panneau garde défilement, blocs `<details>` ouverts, curseur et saisie en cours. Les champs de `formulaire.js` se valident après le clic en cours (`valider`) ou après le déplacement de Tab, et ✓ / ✗ agissent après ces validations (`apresValidations`). **Ctrl+S** enregistre même pendant une saisie (le champ est validé d'abord) ;
- **Plan 2D** : un cadrage demandé pendant que la vue est cachée attend qu'elle ait une taille (`plan.cadrageEnAttente`, `plan.bornesTout`, `plan.recadrer()`) ; « Recadrer » de la barre de vues et la touche F existent aussi en Plan 2D (méthode `recadrer()` des écrans à plan) ;
- **panneau Simuler / Naviguer** : l'état et la tâche, plus les commandes du ruban (Lancer, Arrêter, Repérer, Bloquer, Débloquer y sont seulement) ; « Y aller » grisé tant que rien ne tourne ; une seule section repliable ouverte à la fois, et une commande Avancé ouvre la sienne en haut du panneau ; une partie lancée par l'Atelier qui s'arrête seule, ou un nœud que ros2 launch dit planté (champ `plantages` de l'état des processus, `noeud_plante` de `processus.py`), est signalé (« n'a pas démarré correctement », bouton « Relancer ») ; « Repérer » grisé tant que le robot n'est pas prêt à être repéré (relais muet) ; « Situer le robot » remplace « Robot ailleurs » ;
- **Piloter** : en répétition, sans pilotage, la première commande du ruban devient « Démarrer » ; Voix et Lumière sont grisées comme Postures et Gestes ;
- **textes** (I10 appliquée) : ni sujet ROS, ni nom de nœud, ni commande, ni fichier dans les messages affichés ; le détail technique va dans l'infobulle ou les détails du journal (`/api/camera/etat` reçoit `details`, les 503 de la caméra et du pilotage un champ `sortie`) ; un message d'un autre écran ne reste pas dans la barre d'état (`barreEtat.effacer()`, `coque.effacerMessage()`) ;
- habillage : sol du nuage en `--nuage-sol` (nouveau jeton), aperçu du repère et bulle de consigne sous le pointeur avec un outil de pose (`[data-role=carte3d-bulle]`), poignée d'orientation de 0,26 m cerclée, flèches plus larges, `oriente` dans les poses (un simple clic : l'écran dit comment tourner la salle) ; frise des chorégraphies et légende de la carte selon le thème ; cases du ruban sans le petit carré ; titre « Spectacle » à la verticale ; accueil aligné en haut ; barre de vues et taille des points dans l'écran de scan, points du direct à la taille de leur grille.

**Le robot** (12.6) : avec un minimum actif, `zone_morte_lin` et `zone_morte_rot` ne descendent pas sous 0,01 m/s et 0,02 rad/s (`ZONES_MORTES_MIN_PONT`, refus au démarrage du pont), et `vitesse_effective` ne monte jamais au minimum une composante sous 0,001 (`SEUIL_NUL_PONT`, cas `EXEMPLES_ZONES_NULLES`). Les zones « ralentir » du Collision Monitor ne peuvent pas ralentir le vrai robot sous 0,2 m/s (le pont remonte la consigne) : sous 0,4 m/s, seul le cercle d'arrêt agit ; `navigation.launch.py` le dit au lancement (`zones_ralentir_sans_effet`) ; des zones « stop » arrêteraient aussi le robot devant les murs des couloirs étroits et des portes (les murs sont dans l'observation) : la conduite près des personnes est à mesurer à la séance 2.

**La caméra** (12.7) : `camera_usb` compte l'absence d'image depuis le plus récent de la dernière image et du lancement du `v4l2-ctl` en cours (`faut_relancer`) : un `v4l2-ctl` relancé a ses 5 s pour donner sa première image.

**Le scan** (12.5) : un plan du sol plus penché que 3° (`INCLINAISON_ACCEPTEE` ; un scan court avait donné 6,8°) est refusé : sol à plat au 1er centile des z, `raison` dans le sol, et un avertissement dans `rapport.json` ; l'écran dit « Sol peu vu : pris à plat ». Compteur « Points mesurés » ; le résumé dit les points gardés dans la carte 3D, et le compteur des nuages prend le même nombre que le résumé.

**Le lieu** : sur un étage scanné, `verifier_lieu` avertit d'un nœud (et de sa salle) à moins du rayon du robot (0,35 m) d'un pixel occupé de la carte (`distance_obstacle_carte`), comme pour un monde dessiné. Sur `seance`, la salle « 3 » est à 0,28 m d'un objet bas apparu au retraitement du scan : à déplacer par l'utilisateur (Placer), son lieu n'a pas été modifié.

### 12.15 Un déblocage ne relance plus l'ancien trajet (correction du 01/11/2026)

Constat de la relecture des documents (étape F3 de la séance 2) : « Bloquer » (Naviguer › Bloquer, `POST /api/robot/arret {verrou: true}`), comme le verrou posé en ligne de commande (`ros2 topic pub … /pont/arret`), ne posait que le verrou du pont. Nav2 gardait le but du guide et continuait de calculer des `/cmd_vel`, que le pont jetait ; le guide, qui voyait le robot ne plus avancer, passait à `bloque`, puis `detour` (couloir marqué bloqué pour 120 s), puis `echec`, et programmait le retour automatique. Au « Débloquer », le pont acceptait de nouveau les vitesses : **le robot repartait seul** vers l'ancien but, ou vers le point principal. Mesuré par le correcteur en répétition sans robot (`~/robot-g1-donnees/vague5/verrou/`, script `reproduire_verrou.sh`, sorties `avant_*` et `apres_*`) : « Bloquer » 10 s en route puis « Débloquer » : 3,5 m parcourus seul en 15 s (150 ordres 7105 non nuls) ; retour automatique prévu avant le blocage : parti pendant le blocage, 4,1 m au « Débloquer » ; faux G1 assis en route puis remis en marche : 3,8 m ; verrou en ligne de commande et faux G1 muet : couloirs fermés, `echec`, puis retour automatique au point principal après la levée. L'ARRÊT global, qui envoie aussi `/guide/stop`, n'était pas touché. Le pilotage, qui parle directement au robot, ignorait le verrou : joystick tenu, 1,2 m pendant le blocage ; chorégraphie continuée.

**Règle** : aucune levée d'un empêchement (verrou, mode du robot, panne du pont) ne relance un mouvement ; il faut une nouvelle demande explicite (« Y aller », joystick lâché puis repris, nouvelle commande du pilotage).

**Le guide** (`g1_nav/guide.py`, logique sans ROS testée à fausse horloge) :
- il écoute `/pont/arret` (std_msgs/Bool, fiable, transient_local, profondeur 1, comme le pont : un verrou posé avant son lancement est reçu) et `/pont/etat` (de moins de 2 s, `DELAI_PONT_PERIME_S`) ; paramètre ROS `suivre_pont` (vrai par défaut), que `navigation.launch.py` met à la valeur de `pont` : en simulation, sans pont, un verrou resté posé par une répétition ne bloque pas le guide ;
- **`verrou`** (`/pont/arret` true, ou `/pont/etat` qui dit `verrou` ou `arret_verrouille` : un verrou posé par un éditeur parti depuis, `ros2 topic pub --once`) et **`pas_en_marche`** (`/pont/etat`) : tout de suite, le trajet en cours (`moteur.annuler()`, donc le but de Nav2), la rotation finale au point principal, le retour automatique prévu et le départ en attente de Nav2 sont annulés ; l'état passe à `attente`, avec le champ `immobilise` et un `message` qui dit ce qui est annulé et quoi faire (« Robot bloqué : le trajet vers « Salle B204 » est annulé. Il ne repartira qu'avec un nouveau « Y aller », après « Débloquer ». ») ; événement `immobilise` (champ `raison`) si quelque chose était en cours. Tant que cela dure, `/guide/aller` est refusé : `echec` avec la cible demandée (le contrat de la vague 1 reste vrai), le message (« Robot bloqué : « Y aller » refusé… ») et l'événement `immobilise` ; la demande n'est pas gardée. `/guide/stop` et le verrou arrivent dans un ordre quelconque (ARRÊT, « Bloquer ») : un verrou reçu moins de 2 s après un `/guide/stop` qui a annulé un trajet le cite encore (`DELAI_STOP_VERROU_S`) ;
- **`pont_absent`** (relecture du 01/11/2026) : le pont, déjà vu, ne publie plus `/pont/etat` depuis `DELAI_PONT_PERIME_S` (2 s) et `PAS_SANS_PONT` (5) pas du guide (un guide resté figé ne prend pas son propre retard pour un pont muet) : tué, figé, ou arrêté à la main ; relancé, il suivrait l'ancien but de Nav2. Comme le verrou : tout est annulé tout de suite, « Y aller » est refusé tant que cela dure, aucun retour automatique n'est programmé ni lancé (« Plus de nouvelles du pont vers la marche : le trajet vers « Salle B204 » est annulé. Vérifiez que la navigation tourne encore, puis « Y aller ». ») ; au retour du pont : « Le pont vers la marche répond de nouveau : le robot attend un nouveau « Y aller ». ». Jusqu'à l'absence, le dernier état du pont compte : un pont qui se tait n'est jamais lu comme « rien n'empêche » (un verrou ou un robot assis vus par `/pont/etat` ne deviennent pas « Robot débloqué ») ;
- **`robot_muet`** et **`refus`** (`/pont/etat`), depuis `DELAI_PONT_PANNE_S` (2 s : un ordre perdu n'annule pas une visite), **seulement pendant que Nav2 conduit le robot** (`ETATS_ROULANT` : `en_route`, `retour`, `bloque`, `detour` ; relecture du 01/11/2026 : ni en attente d'un passant, du visiteur ou du repérage, où le guide a lui-même arrêté Nav2, ni avant un retour prévu) : même annulation, sans refuser `/guide/aller` (au repos, le pont n'envoie rien : il ne verrait jamais la fin de la panne). `robot_muet` ne compte que si le pont reçoit des consignes (`age_cmd_vel_s` de moins de 1 s, `DELAI_CMD_VEL_ACTIF_S` : au repos, une réponse perdue laisse le pont en `robot_muet`, ce n'est pas une panne en cours) et si le robot a déjà répondu (pendant ce trajet, ou `reponses` non nul depuis le lancement du pont : un robot qui ne répondrait jamais aux 7105 reste à vérifier sur le vrai G1, le guide fait alors comme avant, retour automatique compris) ; `refus` seulement si la dernière réponse refusée a moins de 1 s (`DELAI_REFUS_FRAIS_S` ; au repos, le pont garde le code de la dernière réponse). Le retour automatique n'est empêché que par le verrou, le mode du robot ou le pont absent ; une vraie panne se voit pendant le retour, qui est alors annulé ;
- à la levée, **rien ne repart** ; au repos, le message le dit (« Robot débloqué : il attend un nouveau « Y aller ». », « Le robot est de nouveau en mode marche… », « Le robot répond de nouveau… ») et `immobilise` disparaît (une panne reste dite tant que le pont la garde ; la demande suivante l'efface) ;
- le pont ne change pas : il reste la dernière barrière (règles 5, 10 et 12 de 10.3). Limite connue : un but envoyé à Nav2 par un autre programme que le guide (RViz, ligne de commande) n'est pas annulé par le guide, et repartirait au déblocage.

**Les contrats, étendus** (rien ne disparaît, les messages d'avant restent conformes) :
- `/guide/etat` : champ facultatif `immobilise` (`verrou`, `pas_en_marche`, `robot_muet`, `refus` ou, relecture du 01/11/2026, `pont_absent` : `RAISONS_IMMOBILE` de `atelier.lieu.comportement`), schéma `etat_guide` ; les états ne changent pas ; relecture du 01/11/2026 : champ `actif` (vrai si le robot peut bouger d'un instant à l'autre : mission, départ qui attend la navigation, retour prévu), pour la touche Échap (12.14) ;
- `/guide/evenement` : nouveau code `immobilise` (« Je ne peux pas bouger pour le moment. »), ajouté à la fin de `CODES_EVENEMENT` et des enum des schémas `evenement_guide` (avec le champ facultatif `raison`) et `personnalites` (une personnalité peut le dire autrement) ; table de 11.4 ;
- `POST /api/robot/arret {verrou: true}` (« Bloquer ») envoie aussi `/guide/stop` (champ `guide` : nombre de guides à l'écoute, les nœuds nommés `guide` ; relecture du 01/11/2026 : le pont vers la marche, qui écoute aussi `/guide/stop`, ne compte plus, `PontRos.guides_a_l_ecoute`) : le trajet est annulé même par un guide d'avant cette correction (image du Jetson pas refaite) ; la réponse a un `message` (`MESSAGE_BLOQUE`, `MESSAGE_DEBLOQUE` de `routes/arret.py`). L'ARRÊT envoyait déjà `/guide/stop` ;
- `POST /api/guide/aller`, en répétition et avec le robot, pendant un verrou (posé par l'Atelier ou vu par le pont), hors du mode marche ou, un guide tournant, avec un `/pont/etat` périmé (`pont_absent`, relecture du 01/11/2026) : 200 avec `avertissement` et `immobilise`, et c'est le guide qui refuse, comme pendant le pilotage (11.12) ; en simulation, un verrou resté posé ne compte pas ;
- **textes** : « Bloquer » dit que le trajet en cours est annulé (« Robot bloqué : le trajet en cours est annulé. Il reste immobile jusqu'à « Débloquer », puis attend un nouveau « Y aller ». ») ; « Débloquer » : « Robot débloqué : il ne repartira qu'avec un nouveau « Y aller ». » ; l'ARRÊT verrouillé : « ARRÊT : robot arrêté et bloqué, trajet annulé. Après « Débloquer », il attend un nouveau « Y aller ». » ; aides du ruban ; dans Naviguer, le titre de l'état du guide le dit (`TITRES_IMMOBILE` de `ecrans/simulation.js`) et « Y aller » est grisé tant que le robot est bloqué, pas en mode marche ou sans nouvelles du pont (`pont_absent`).

**Le pilotage** (`g1_pilotage`) : le nœud écoute aussi `/pont/arret` (transient_local). Posé : comme l'ARRÊT (StopMove, chorégraphie arrêtée et poids des bras ramené à 0, bras relâchés, joystick tenu ignoré jusqu'à ce qu'il soit lâché), sans `/guide/stop` (le guide écoute le verrou) ; puis joystick, postures, tâches, gestes, danses, chorégraphies, gestes demandés par l'équipe et ordres de marche avancés sont refusés (409 « robot bloqué (Naviguer › Bloquer, ou ARRÊT) : cliquez sur « Débloquer » d'abord ») ; LED, voix, volume, lectures, StopMove, relâcher les bras (99) et l'ARRÊT restent permis ; champ `verrou` de `/pilotage/etat` (en plus du schéma). Levé : rien ne repart (le joystick resté tenu est encore refusé jusqu'à ce qu'il soit lâché). Pendant une danse du robot, comme pour l'ARRÊT, seul StopMove part (la télécommande reste l'arrêt d'urgence). Relecture du 01/11/2026 : **tout ordre du joystick refusé pendant que le manche est tenu** (robot bloqué, mode lu hors de la marche et de la course, robot muet, danse ou chorégraphie) arme `joystick_bloque` (raison et message : `TEXTES_JOYSTICK_BLOQUE`, « Joystick : le robot a quitté le mode marche. Lâchez le joystick, puis reprenez-le pour repartir. ») : quand l'empêchement cesse, le manche doit être lâché puis repris, même s'il avait été lâché et repris (ou la page rechargée) pendant le blocage. **Robot muet** pour le pilotage (`robot_muet()`) : il a répondu, puis plus aucune réponse depuis 3 s (`DELAI_MUET_S` ; le mode est lu chaque seconde, un robot relié répond toujours, et deux lectures perdues d'affilée ne suffisent pas ; un robot qui n'a jamais répondu n'est pas muet) : joystick refusé (« le robot ne répond plus… »). Une **chorégraphie s'arrête** si le mode lu quitte `MODES_MARCHE` (assis, amorti à la télécommande) ou si le robot est muet : StopMove, plus aucun pas, poids des bras ramené à 0 en 1 s, geste relâché (99) si les bras en tiennent un, message « Chorégraphie « … » arrêtée : le robot n'est plus en mode marche (assis). Elle ne reprend pas : rejouez-la… » ; elle ne reprend jamais seule.

**Tests** : `test_comportement.py` (13 cas : verrou en route, au repos, pendant le retour et la rotation finale, départ en attente, stop et verrou dans les deux ordres, verrou vu par `/pont/etat`, `pas_en_marche`, robot muet après 2 s et robot qui n'a jamais répondu, vieux refus et refus qui dure, retour pas lancé pendant une panne, simulation sans pont ; sans la correction, 11 échouent, les 2 autres vérifient qu'il n'y a pas de régression), `test_noeud_guide.py` (verrou transient_local posé avant le lancement puis en route, `suivre_pont:=false`, `pas_en_marche` par `/pont/etat`), `test_lancement.py` (`suivre_pont`), `test_logique.py` du pilotage (joystick, mouvements refusés, danse, chorégraphie) et du pont (le constat figé), `atelier/tests/test_arret.py`, `test_guide_api.py` et `test_coque_navigateur.py` (« Bloquer » envoie `/guide/stop`, messages, avertissement et « Y aller » grisé), et le critère 36 (12.10). Relecture du 01/11/2026 : `test_comportement.py` (pont absent en route, pendant l'attente du retour et au repos ; guide figé ; réponse perdue au repos : retour et attente du passant ; robot muet pendant le retour ; robot qui ne répond jamais : retour fait ; champ `actif` ; deux cas avec la vraie logique du pont, `Couple` : réponse perdue, pont tué puis relancé ; 9 de ces cas échouent sur le code d'avant), `test_logique.py` du pilotage (joystick tenu, robot assis ou amorti puis remis en marche ; coupure du lien ; lâché et repris, ou page rechargée, pendant le blocage ; chorégraphie arrêtée par l'assise, l'amortissement ou le silence du robot ; 9 cas qui échouent sur le code d'avant), `test_coque_navigateur.py` (Échap pendant l'attente du retour ou d'un départ, `pont_absent` grise « Y aller »), `test_guide_api.py`, `test_arret.py` et `test_serveur_pont_ros.py` (`guides_a_l_ecoute` ne compte que les guides), et le critère 36 (réception de `/guide/stop`, « Y aller » grisé dans Naviguer, Échap avec le menu « Y aller » ouvert pendant l'attente du retour).

**Relecture du 01/11/2026** (deux relecteurs, en répétition et sur le code ; le finisseur a vérifié chaque défaut) : corrigés, voir ci-dessus : le pont tué puis relancé (le robot reprenait l'ancien trajet : 4,2 m et 4,9 m en 15 s ; ou le retour automatique lancé pendant que le pont était mort : 5,2 m), un `/pont/etat` trop vieux lu comme « rien n'empêche » (faux « Robot débloqué »), un `robot_muet` resté au repos (réponse perdue) qui annulait le retour automatique et l'attente d'un passant (régression), le joystick tenu après « assis », l'amortissement ou une coupure du lien (1,5 à 1,8 m), le joystick lâché puis repris pendant le blocage, la chorégraphie qui continuait sous l'assise (0,74 rad, 40 ordres de marche), Échap avec un menu ouvert pendant l'attente du retour (le robot partait 13 s plus tard : 2,5 m), et deux vérifications qui ne prouvaient rien (le champ `guide`, qui comptait le pont ; « Y aller » grisé, qui n'était testé que par une fonction pure). **Écartée, avec la raison** : la suggestion de faire ignorer au pont, à son lancement, un flux de `/cmd_vel` déjà en cours. Le pont ne peut pas distinguer un flux qui courait avant lui d'un flux qui commence juste après : la découverte DDS retarde le premier message reçu (parfois plus d'une seconde), si bien qu'une fenêtre de temps, ou bien laisserait passer le flux d'avant, ou bien refuserait la première consigne légitime (critères 17 et 20) ; le guide, lui, annule son trajet dès que le pont se tait. **Limites qui restent** : un but de Nav2 envoyé par un autre programme que le guide (RViz, ligne de commande), ou un `/cmd_vel` envoyé à la main, n'est pas annulé et repartirait au déblocage ou à la relance du pont (tutoriel, étape C4 : Ctrl+C avant de relancer le pont) ; un pont relancé en moins de 2 s (aucun lancement ne le relance seul : pas de `respawn`) n'est pas vu absent, et le robot continue la visite en cours, comme après un ordre perdu.

**À vérifier sur le robot** (séance 2) : F3 de `docs/tutoriel-seance-2.md` (ARRÊT à mi-chemin, « Y aller » refusé, « Débloquer » : le robot ne bouge pas, le panneau dit « Robot débloqué : il attend un nouveau « Y aller » ») ; le robot assis à la télécommande pendant un trajet (trajet annulé, rien ne repart quand il se relève) ; le code de réponse de 7105 (le robot répond-il toujours ?), dont dépend l'annulation sur `robot_muet` ; relecture du 01/11/2026 : la télécommande en amortissement pendant une chorégraphie (ce que fait `rt/arm_sdk` pendant la descente du poids), et le joystick tenu pendant une mise en position assise (il doit rester refusé à la remise en marche).
