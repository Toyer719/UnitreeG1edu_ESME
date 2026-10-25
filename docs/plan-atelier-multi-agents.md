# Atelier G1 : le logiciel de configuration des lieux

Plan de construction pour une équipe d'agents. Il s'agit de tout ce qui peut se faire **sans le robot**.

Ce document est la référence commune. Chaque agent lit en entier les sections 1 à 5 (but, contraintes, architecture, contrats, organisation), puis sa propre fiche dans la section 6. En cas de doute, les contrats de la section 4 font foi. On ne les modifie qu'en passant par l'agent intégrateur.

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
- **Chaque outil prend `--lieu DOSSIER`**, et n'écrit que dans ce dossier, sauf les journaux, dans `~/robot-g1/journaux/`.
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
│   │   └── vendor/                # leaflet, three.js copiés en local (fonctionne sans Internet)
│   └── tests/                     # tests unitaires (chaque agent dans ses fichiers)
├── ws/src/
│   ├── g1_sim/                    # agent Simulation (ament_cmake)
│   │   ├── models/g1_proxy/model.sdf
│   │   ├── config/pont_gz.yaml    # correspondances ros_gz_bridge
│   │   └── launch/simulation.launch.py
│   └── g1_nav/                    # agent Navigation (ament_python)
│       ├── g1_nav/routeur.py, guide.py, banc.py, odom_vers_tf.py
│       ├── config/nav2_g1_simu.yaml, nav2_g1_reel.yaml
│       └── launch/navigation.launch.py
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
├── cartes/<etage>_interdit.pgm    # masque Keepout (généré depuis zones.yaml)
├── cartes/<etage>.pcd             # nuage 3D du scan (facultatif)
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

### 4.2 ROS 2

| Sujet ou service | Type | Sens | Rôle |
|---|---|---|---|
| `/guide/aller` | std_msgs/String | → guide | identifiant de salle ou de nœud (« b204 », « accueil ») |
| `/guide/stop` | std_msgs/Empty | → guide | arrêt immédiat |
| `/guide/etat` | std_msgs/String (JSON) | guide → | `{"etat": "attente|en_route|bloque|detour|arrive|echec", "cible": "b204", "reste_m": 12.5, "itineraire": ["accueil","c1","b204"]}` |
| `/cmd_vel` | geometry_msgs/Twist | Nav2 → robot | vitesses vx, vy, wz |
| `/odom` | nav_msgs/Odometry | robot → | simulation : odométrie de Gazebo ; vrai robot : `/unitree/slam_relocation/odom` relayé |
| `/points` | sensor_msgs/PointCloud2 | robot → | simulation : LiDAR de Gazebo ; vrai robot : `/unitree/slam_relocation/points` relayé |
| TF | `map → odom → base_link → lidar` | | simulation : `map → odom` fixe (identité) |

### 4.3 Commandes

| Commande | Rôle | Agent |
|---|---|---|
| `g1-atelier [--port 8000]` | lance le serveur et ouvre le navigateur | Interface |
| `g1-lieu creer ID --nom NOM` / `g1-lieu valider --lieu L` | créer ou vérifier un paquet de lieu | Données |
| `g1-monde generer --lieu L --etage E` | monde.yaml → .sdf, carte .pgm/.yaml, masque | Monde |
| `g1-monde simuler --lieu L --etage E [--sans-fenetre]` | Gazebo, robot proxy et piétons | Simulation |
| `g1-guide navigation --lieu L --etage E [--simu]` | Nav2, routeur et guide sur la carte du lieu | Navigation |
| `g1-guide aller ID` / `g1-guide stop` | envoyer le robot (publie sur /guide/*) | Navigation |
| `g1-banc --lieu L --etage E --trajets 50` | banc de test, résultats en CSV | Navigation |
| `g1-slam scan-debut|scan-fin --nom N|relocaliser|aller|pause|reprendre|arreter [--faux]` | client slam_operate | Scan |
| `g1-carte-3d --lieu L --etage E --enregistrement DOSSIER` | enregistrement → .pcd | Scan |
| `g1-carte-2d --lieu L --etage E` | .pcd → carte .pgm/.yaml | Scan |
| `g1-salle ajouter NOM [--type salle|noeud] --lieu L` | position actuelle du robot → salles ou itinéraires | Scan |

### 4.4 API du serveur

REST sous `/api`, en JSON. Chaque route correspond à un fichier du paquet, ou à une action.

- `GET/POST /api/lieux`, `GET /api/lieux/{id}`
- `GET/PUT /api/lieux/{id}/etages/{e}/monde`, `POST …/monde/generer`
- `GET …/carte.png` : la carte PGM convertie en PNG pour l'affichage. `GET …/carte.yaml`
- `GET/PUT /api/lieux/{id}/salles`, `…/itineraires`, `…/zones`
- `POST /api/simulation/demarrer {lieu, etage}`, `POST /api/simulation/arreter`, `GET /api/simulation/etat`
- `POST /api/guide/aller {cible}`, `POST /api/guide/stop`
- `POST /api/scan/debut`, `POST /api/scan/fin {nom}` (vrai robot ou faux service)
- WebSocket `/ws/etat` : environ 10 messages par seconde, `{robot: {x, y, theta}, guide: {...}, pietons: [...], processus: {...}}`

---

## 5. Organisation de l'équipe d'agents

Sept agents. Chacun possède ses dossiers, et personne n'écrit dans les dossiers d'un autre. Si un agent a besoin d'un changement chez un autre, il le demande à l'intégrateur.

| Agent | Possède | Dépend de |
|---|---|---|
| 1. Intégrateur | section 4, `tests_e2e/` (avec l'agent 7), `bin/g1-atelier`, revues, fusions | — |
| 2. Données | `atelier/lieu/`, `lieux/demo/`, `bin/g1-lieu` | contrats |
| 3. Monde | `atelier/monde/`, `bin/g1-monde` (sous-commande generer) | Données |
| 4. Simulation | `ws/src/g1_sim/`, sous-commande `g1-monde simuler` | Monde (fichier .sdf) |
| 5. Navigation | `ws/src/g1_nav/`, `bin/g1-guide`, `bin/g1-banc` | Données, Simulation |
| 6. Interface | `atelier/serveur/`, `atelier/web/` | Données, Monde ; Simulation et Navigation pour l'intégration |
| 7. Scan et Testeur | `atelier/scan/`, `bin/g1-slam`, `g1-carte-*`, `g1-salle`, `tests_e2e/` | Données, Simulation |

### Phases

| Phase | Qui | Résultat attendu |
|---|---|---|
| 0. Contrats | Intégrateur | Section 4 figée en schémas JSON, arborescence vide créée, lieu `demo` minimal écrit à la main, `git init` et premier commit |
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
1. Phase 0 :
   - écrire `atelier/lieu/schemas/*.json` à partir de la section 4.1 ;
   - créer l'arborescence et les paquets ROS vides : `ros2 pkg create` pour `g1_sim` en ament_cmake et pour `g1_nav` en ament_python ;
   - écrire un `lieux/demo` minimal : deux couloirs et trois salles ;
   - faire le premier commit.
2. Écrire `bin/g1-atelier`. Il charge `env.sh`, lance `uvicorn atelier.serveur.main:app` avec `.venv-projet`, puis ouvre `http://localhost:8000`.
3. À chaque fin de phase :
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
5. Écrire `lieux/demo` complet : un monde inventé de 30 × 20 m, deux couloirs parallèles reliés à chaque bout (pour qu'il existe un chemin de secours), cinq salles, l'accueil, le graphe et une zone interdite.

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
4. Écrire `bin/g1-monde generer`.
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
   - arguments : `lieu`, `etage`, `sans_fenetre` ;
   - lancer Gazebo sur `mondes/<etage>.sdf` et faire apparaître `g1_proxy` à `depart_robot` ;
   - lancer le pont et `robot_state_publisher` (repères base_link → lidar).
5. Écrire la sous-commande `g1-monde simuler`.
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
3. Écrire `launch/navigation.launch.py`. Arguments : `lieu`, `etage`, `simu`. En simulation, il publie un repère fixe `map → odom`. Sur le robot, ce sera `odom_vers_tf.py`, qui relaie `/unitree/slam_relocation/odom`.
4. Écrire `routeur.py`. Il charge `itineraires.yaml`, cherche le plus court chemin avec A*, et peut marquer un couloir bloqué pour 120 s.
5. Écrire `guide.py` :
   - il écoute `/guide/aller` et `/guide/stop`, et publie `/guide/etat` (section 4.2) ;
   - il envoie la suite de nœuds à Nav2 avec `nav2_simple_commander` (`goThroughPoses`) ;
   - si la distance restante ne baisse pas pendant 3 s, état `bloque` ; pendant 8 s, il annule, marque le couloir bloqué, recalcule l'itinéraire (`detour`) et repart.
   - Prévoir une interface `Moteur` avec deux réalisations. `MoteurNav2` est à faire maintenant. `MoteurUnitree`, avec la commande 1102 et des tronçons de 8 m au plus, sera fait par l'agent 7.
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
   - **Scan** : boutons Démarrer / Terminer reliés à `g1-slam`, à tester avec le faux service.
3. Règles d'écriture de l'interface :
   - les boutons disent ce qu'ils font (« Fabriquer la carte », « Y aller ») ;
   - les erreurs disent quoi corriger ;
   - tout est en français ; l'interface reste utilisable sur une tablette.

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
4. Écrire `MoteurUnitree` pour le guide de l'agent 5 : tronçons de 8 m au plus, le robot s'arrête devant les obstacles, le guide gère pause et détour.
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

---

## 8. Après ce plan, avec le robot

1. **Avec `g1-slam` sans `--faux`** :
   - vérifier un par un les formats de 1801, 1802, 1804 et 1102 ;
   - corriger `slam_client.py` et noter les vrais formats dans ce document.
2. **Scanner le vrai étage** : `source_carte: scan` dans `lieu.yaml`, puis `g1-carte-3d` et `g1-carte-2d`. Le reste du logiciel ne change pas.
3. **Placer les salles en vrai** : amener le robot devant chaque porte, puis `g1-salle ajouter`.
4. **Pont et relais** sur le Jetson, dans le conteneur Humble : `/cmd_vel` → `/api/sport/request` (7105), et le relais de la relocalisation vers `/odom` et TF.
5. **Recette en vrai** : niveau 1 (MoteurUnitree), puis niveau 2 (MoteurNav2), avec des volontaires et le même `g1-banc`.
