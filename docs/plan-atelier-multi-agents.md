# Atelier G1 : le logiciel de configuration des lieux

Plan de construction pour une équipe d'agents. Il s'agit de tout ce qui peut se faire **sans le robot**.

Ce document est la référence commune. Chaque agent lit en entier les sections 1 à 5 (but, contraintes, architecture, contrats, organisation), puis sa propre fiche dans la section 6. En cas de doute, les contrats de la section 4 font foi. On ne les modifie qu'en passant par l'agent intégrateur.

Vague 2, le scan intégré : chaque agent lit aussi la section 9 en entier (contrats, fiches et critères de cette vague). Ses contrats font foi au même titre que ceux de la section 4.

Vague 3, le vrai robot (conteneur du Jetson, pont vers la marche, repérage au démarrage) : chaque agent lit aussi la section 10 en entier. Ses contrats font foi au même titre que ceux des sections 4 et 9.

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
│   ├── g1_nav/                    # agent Navigation (ament_python)
│   │   ├── g1_nav/routeur.py, guide.py, banc.py, odom_vers_tf.py, reperage.py (vague 3)
│   │   ├── g1_nav/moteurs.py (interface Moteur), moteur_nav2.py, moteur_unitree.py
│   │   ├── config/nav2_g1_simu.yaml, nav2_g1_reel.yaml
│   │   └── launch/navigation.launch.py
│   ├── g1_bridge/                 # vague 3 : pont /cmd_vel → /api/sport/request (section 10.3)
│   └── g1_jumeau/                 # vague 3 : faux service sport du G1 pour Gazebo (section 10.4)
├── docker/                        # vague 3 : conteneur Humble du Jetson (section 10.2)
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
| `/cmd_vel` | geometry_msgs/Twist | Nav2 → robot | vitesses vx, vy, wz ; simulation : vers Gazebo ; répétition et vrai robot : vers le pont (10.3) |
| `/odom` | nav_msgs/Odometry | robot → | simulation : odométrie de Gazebo ; répétition et vrai robot : odométrie locale `/state_estimator/odom_pelvis` relayée par `odom_vers_tf` (repère odom, section 10.5) |
| `/points` | sensor_msgs/PointCloud2 | robot → | simulation : LiDAR de Gazebo ; répétition et vrai robot : `/unitree/slam_relocation/points` ramené dans le repère `lidar` par `odom_vers_tf` |
| TF | `map → odom → base_link → lidar` | | simulation : `map → odom` fixe (identité) ; répétition et vrai robot : `map → odom` = correction de la relocalisation d'Unitree, `odom → base_link` = odométrie locale (section 10.5) |

Vague 3 (section 10) : sujets du pont (`/api/sport/*`, `/pont/etat`, `/pont/arret`), du repérage (`/reperage/demander`, `/reperage/etat`, `/api/slam_operate/*`, `/unitree/slam_relocation/*`) et du faux G1 (`/g1_jumeau/*`, `/state_estimator/odom_pelvis`) en 10.3 à 10.6. `/guide/etat` peut porter un champ `message` (10.7).

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

Vague 2 : agents et fichiers en 9.9. Vague 3 : agents Jetson, Pont et faux G1, Repérage, en 10.10.

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

Critères 11 à 15 (vague 2, scan intégré) : section 9.10. Critères 16 à 20 (vague 3, le vrai robot en répétition, section 10), ci-dessous ; `tests_e2e/tout.sh` lance les vingt et affiche « N / 20 ». En répétition, la vérité terrain est `/g1_jumeau/odom`.

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
5. **`/pont/arret` true** : arrêt immédiat, envoyé 3 fois en 0,2 s ; état `arret_verrouille` ; `/cmd_vel` ignoré jusqu'à `/pont/arret` false. Ensuite, le mouvement ne reprend qu'avec un `/cmd_vel` reçu après le déverrouillage.
6. **Repérage exigé** (paramètre `exiger_reperage`, vrai par défaut) : le mouvement n'est permis que si le dernier `/reperage/etat` date de moins de 1 s et a `repere` vrai. Sinon `/cmd_vel` est ignoré, et un arrêt part si le robot bougeait. `exiger_reperage:=false` ne sert qu'aux essais au portique (10.9).
7. **Robot muet** : si les requêtes envoyées n'ont reçu aucune réponse depuis 1 s, l'état passe à `robot_muet`. Le pont continue d'envoyer la consigne fraîche ; le robot, lui, s'arrête seul à la fin de `duration`. On revient à la normale dès qu'une réponse arrive, et le mouvement ne reprend qu'avec un `/cmd_vel` frais.
8. **Refus** : si une réponse a `status.code` ≠ 0, l'état passe à `refus`, avec le code et un message, par exemple « Le robot refuse de marcher (code 7301) : mettez-le en mode marche avec la télécommande ».
9. **Au lancement** : un arrêt, qui vérifie le lien (état `demarrage` jusqu'à la réponse, `robot_muet` après 1 s sans réponse). **À la sortie** (Ctrl+C, SIGTERM) : un arrêt, envoyé avant de quitter. Précision de l'assemblage : un arrêt publié avant que DDS ait découvert le service `sport` serait perdu ; l'arrêt de vérification part donc dès qu'un abonné à `/api/sport/request` est vu (tout de suite s'il l'est déjà), puis encore 2 fois au plus à 0,3 s d'écart tant qu'aucune réponse n'arrive. Une nouvelle vérification se fait quand un nouvel abonné apparaît alors que le robot n'a jamais répondu ou est muet (service relancé). Rien de continu au repos.
10. Tous les délais du pont comptent en temps mural monotone, jamais en temps simulé. Le pont ne publie jamais sur `/cmd_vel` ni sur un sujet de Gazebo.

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
