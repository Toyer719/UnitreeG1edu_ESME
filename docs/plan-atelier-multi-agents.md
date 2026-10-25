# Atelier G1 : le logiciel de configuration des lieux

Plan de construction pour une équipe d'agents. Il s'agit de tout ce qui peut se faire **sans le robot**.

Ce document est la référence commune. Chaque agent lit en entier les sections 1 à 5 (but, contraintes, architecture, contrats, organisation), puis sa propre fiche dans la section 6. En cas de doute, les contrats de la section 4 font foi. On ne les modifie qu'en passant par l'agent intégrateur.

Vague 2, le scan intégré : chaque agent lit aussi la section 9 en entier (contrats, fiches et critères de cette vague). Ses contrats font foi au même titre que ceux de la section 4.

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
│   │   └── vendor/                # leaflet, three.js copiés en local (fonctionne sans Internet)
│   └── tests/                     # tests unitaires (chaque agent dans ses fichiers)
├── ws/src/
│   ├── g1_sim/                    # agent Simulation (ament_cmake)
│   │   ├── models/g1_proxy/model.sdf
│   │   ├── config/pont_gz.yaml    # correspondances ros_gz_bridge
│   │   └── launch/simulation.launch.py
│   └── g1_nav/                    # agent Navigation (ament_python)
│       ├── g1_nav/routeur.py, guide.py, banc.py, odom_vers_tf.py
│       ├── g1_nav/moteurs.py (interface Moteur), moteur_nav2.py, moteur_unitree.py
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
├── cartes/<etage>_interdit.pgm + .yaml   # masque Keepout (généré depuis zones.yaml), même taille et origine que la carte
├── cartes/<etage>_lent.pgm + .yaml       # masque des zones lentes (facultatif, phase 3)
├── cartes/<etage>.pcd             # nuage 3D du scan (facultatif)
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
- **Salles et nœuds** : chaque salle de `salles.yaml`, accueil compris, a dans `itineraires.yaml` un nœud de même id, à la même position. La salle `accueil` a la pose `accueil` de `lieu.yaml`. Une cible de `/guide/aller` est un id de salle ou de nœud.
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
| `g1-monde simuler --lieu L --etage E [--sans-fenetre]` | Gazebo, robot proxy et piétons : appelle `ros2 launch g1_sim simulation.launch.py` (section 4.5) | Monde |
| `g1-guide navigation --lieu L --etage E [--simu]` | Nav2, routeur et guide sur la carte du lieu | Navigation |
| `g1-guide aller ID` / `g1-guide stop` | envoyer le robot (publie sur /guide/*) | Navigation |
| `g1-banc --lieu L --etage E --trajets 50` | banc de test, résultats en CSV | Navigation |
| `g1-slam scan-debut|scan-fin --nom N|relocaliser|aller|pause|reprendre|arreter [--faux]` | client slam_operate | Scan |
| `g1-carte-3d --lieu L --etage E --enregistrement DOSSIER` | enregistrement → .pcd | Scan |
| `g1-carte-2d --lieu L --etage E` | .pcd → carte .pgm/.yaml | Scan |
| `g1-salle ajouter NOM [--type salle|noeud] --lieu L` | position actuelle du robot → salles ou itinéraires | Scan |

Vague 2 (section 9.5) : `g1-scan demarrer|arreter|traiter|etat|adopter`, agent Orchestrateur.

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
- Routes ajoutées : `GET /api/etat`, `PUT /api/lieux/{id}` (lieu.yaml), `GET /api/lieux/{id}/verification`, `PUT …/salles?synchroniser=true` (crée ou déplace le nœud de même id, recopie l'accueil dans lieu.yaml), `GET /api/scan/etat`, `POST /api/scan/faux-service/arreter`.
- Champs facultatifs : `fenetre` (false) et `navigation` (true) de `simulation/demarrer` ; `faux`, `lieu` et `etage` du scan.
- Chaque PUT renvoie `{enregistre: [...], rapport: {ok, erreurs, avertissements}}` ; une erreur est toujours `{detail, erreurs?, sortie?}`, en français.
- `/ws/etat` contient aussi `simulation`, `temps_sim` et `ros {actif, erreur, nav2}`.

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
   - **Scan** : boutons Démarrer / Terminer reliés à `g1-slam`, à tester avec le faux service.
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

---

## 8. Après ce plan, avec le robot

1. **Avec `g1-slam` sans `--faux`** :
   - vérifier un par un les formats de 1801, 1802, 1804 et 1102 ;
   - corriger `slam_client.py` et noter les vrais formats dans ce document.
2. **Scanner le vrai étage** : `source_carte: scan` dans `lieu.yaml`, puis `g1-carte-3d` et `g1-carte-2d`. Le reste du logiciel ne change pas.
3. **Placer les salles en vrai** : amener le robot devant chaque porte, puis `g1-salle ajouter`.
4. **Pont et relais** sur le Jetson, dans le conteneur Humble : `/cmd_vel` → `/api/sport/request` (7105), et le relais de la relocalisation vers `/odom` et TF.
5. **Recette en vrai** : niveau 1 (MoteurUnitree), puis niveau 2 (MoteurNav2), avec des volontaires et le même `g1-banc`.

---

## 9. Scan intégré (vague 2)

Contrats figés par l'intégrateur le 25/10/2026, avant le travail en parallèle de quatre agents (9.9). Comme la section 4, cette section fait foi ; on ne la modifie qu'en passant par l'intégrateur. Le code partagé est déjà livré et testé : `atelier.lieu.scans` (sessions, reconnaissance, monde tiré du scan, état du scan), les schémas `session_scan` et `reconnaissance`, les champs facultatifs des objets du monde, et `atelier/tests/outils_scan.py` (sessions d'exemple, sans ROS).

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

### 9.9 Les agents de la vague 2

| Agent | Possède | Dépend de |
|---|---|---|
| Intégrateur | sections 4 et 9, `atelier/lieu/` (dont les schémas), `atelier/tests/test_contrats*.py`, `test_lieu_scans.py`, `outils_scan.py`, `lieux/demo`, `.gitignore`, assemblage | — |
| A. Orchestrateur | `atelier/scan/` sauf `reconnaissance*` et `evaluation.py` (nouveaux modules du scan intégré, `carte3d`, `carte2d`, `faux_slam`, `slam_client`, `commande`), `bin/g1-scan`, `bin/gl-scan`, `atelier/tests/test_scan_integre*.py` | contrats ; Reconnaissance (appel de `reconnaitre`) |
| B. Reconnaissance | `atelier/scan/reconnaissance.py` (ou le paquet `atelier/scan/reconnaissance/`), `atelier/tests/test_scan_reconnaissance*.py` | contrats ; Testeur (évaluation) |
| C. Interface | `atelier/serveur/`, `atelier/web/`, `atelier/tests/test_serveur_*.py` | contrats ; `g1-scan` (fausses commandes en attendant) |
| D. Testeur | `atelier/scan/evaluation.py`, `atelier/tests/test_scan_evaluation.py`, `tests_e2e/critere_11_*` à `critere_15_*`, `tests_e2e/tout.sh` et `LISEZMOI.md` | tous |

Règles communes : chaque agent n'écrit que dans ce qu'il possède et demande le reste à l'intégrateur ; `atelier/lieu` et les schémas ne changent que par l'intégrateur ; dans chaque shell ROS ou Gazebo, un `ROS_DOMAIN_ID` et une `IGN_PARTITION` propres à l'agent ; Gazebo sans fenêtre ; pas de compilation dans `ws/build` ; jamais rien sur eno2 (le vrai mode robot n'est essayé qu'en répétition) ; tous les processus lancés sont arrêtés à la fin (vérifier avec `ps`) ; tests réels, sans écran ni robot ; une section dans `docs/journal-atelier.md`. Pour travailler sans attendre les autres : `atelier.tests.outils_scan.creer_session_exemple(copie_du_lieu, etat)` crée une session complète et conforme (en_cours, traitement, termine ou echec), sans ROS.

**A. Orchestrateur.** 1) `g1-scan` et ses cinq sous-commandes (9.5), avec l'aide en français. 2) Le processus de la session : enregistrement, aperçu en direct, 1801 et 1802, répétition (faux service, simulation, relais), exploration. 3) Le traitement et l'adoption. 4) `carte3d` : position du LiDAR par défaut à mettre à jour (robot proxy : 1,245 m). Tests : cycle complet en simu sur une copie du demo (`demarrer --explorer`, puis `termine`), répétition du mode robot (1801 puis 1802 reçus par le faux service, sujets `/unitree/slam_mapping/*` enregistrés), `arreter` d'une session interrompue, `adopter` avec et sans `--monde` (lieu valide ensuite), aucun processus restant. En attendant la reconnaissance : une fausse `reconnaitre` dans les tests.

**B. Reconnaissance.** `reconnaitre` (9.6) : sol, tranche, murs (segments droits, épaisseur et hauteur), passages (9.4), objets (regroupement, forme mesurée, catégorie par la hauteur, la taille et le profil vertical), personnes, confiance. Tests : nuages synthétiques (une pièce, une porte de 0,9 m, un trou de 0,5 m, une table, une chaise, un poteau, une personne), puis un scan simulé du demo évalué avec l'évaluation du Testeur (objectifs de 9.8). Pour avoir un scan du demo avant `g1-scan` : l'enregistrement du critère 7 (`tests_e2e/critere_07_scan_simule.sh`), puis `g1-carte-3d` et `g1-carte-2d --sortie`.

**C. Interface.** Routes de 9.7, onglet Scan, téléopération (pont ROS 2 avec homme mort), revue et adoption ; mise à jour du parcours navigateur et de la liste de vérifications à la main. Tests : API avec de fausses commandes `g1-scan` et des sessions d'exemple ; téléopération avec un faux `/cmd_vel` (consignes ramenées aux limites, zéro après 0,5 s) ; syntaxe des modules JS ; parcours dans Firefox sans fenêtre si présent.

**D. Testeur.** `evaluation.py` (9.8 ; une reconnaissance parfaite donne 1 partout, une reconnaissance abîmée fait baisser la bonne mesure) ; critères de recette 11 à 15 (9.10) dans `tests_e2e/`, avec `tout.sh` qui affiche « N / 15 » ; vérifier que les critères 1 à 10 passent toujours.

### 9.10 Critères de recette de la vague 2, sans robot et sans fenêtre

11. **Scan simulé intégré** : sur une copie du demo, `g1-scan demarrer --mode simu --explorer` rend la main en moins de 3 s ; l'aperçu se met à jour pendant le tour ; la session finit `termine` toute seule, en moins de 20 min ; la carte de la session recouvre la carte du monde à au moins 80 % ; `monde_scan.monde.yaml` est valide.
12. **Répétition du mode robot** : `g1-scan demarrer --mode robot --repetition`, téléopération ou exploration, puis `g1-scan arreter --attendre` : le faux service a reçu 1801 puis 1802 (avec `carte_unitree`), le bag contient `/unitree/slam_mapping/points` et `/unitree/slam_mapping/odom`, la session finit `termine`.
13. **Reconnaissance** : sur le scan du critère 11, l'évaluation atteint les objectifs de 9.8 ; aucune personne n'est cochée d'office.
14. **Adoption** : `g1-scan adopter --monde` ; `g1-lieu valider` ne signale aucune erreur ; l'étage est en `source_carte: scan` ; le masque a la taille de la nouvelle carte ; `g1-monde simuler --sans-fenetre` démarre sur le monde adopté et `/points` est publié ; l'ancien monde est dans la session.
15. **Interface** : depuis l'API (et dans Firefox si présent) : Scan → aperçu → Fin → progression jusqu'à « termine » → décocher un élément → Adopter ; la téléopération déplace le robot simulé et s'arrête seule quand on lâche. Aucun processus ne reste après l'arrêt du serveur.
