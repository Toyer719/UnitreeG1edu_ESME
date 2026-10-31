# docker/ : le conteneur g1-jetson

Conteneur ROS 2 Humble du Jetson du G1 (section 10.2 du plan) : Nav2, guide, relais
`odom_vers_tf` et pont `pont_g1` ; vague 4 (section 11.5) : le nœud `pilotage` de Réel › Piloter
(`G1_PILOTAGE=1`, défaut avec le robot) ; vague 5 (section 12.7) : la caméra de
poitrine See3CAM (nœud `camera_usb`, seulement si elle est branchée). Guide pas à pas pour le
jour du robot : `docs/jetson.md`.

| Fichier | Rôle |
|---|---|
| `Dockerfile` | image multi-architecture (amd64 pour le PC, arm64 pour le Jetson) ; couches de la plus stable à la plus changeante |
| `demarrer.sh` | point d'entrée : réseau, ROS, ligne de démarrage, présence, puis `G1_LANCEMENT` ; SIGTERM devient SIGINT pour `ros2 launch` (15 s) |
| `env.sh` | environnement ROS du conteneur, partagé par `demarrer.sh`, `g1-jetson shell` et `g1-jetson etat` |
| `reseau.py` | choix des interfaces (`G1_INTERFACES`, `G1_WIFI`, `G1_PAIRS`) et écriture de `/tmp/cyclonedds.xml` ; aussi utilisé par `g1-jetson verifier` |
| `cyclonedds.xml.modele` | modèle de la configuration CycloneDDS |
| `presence.py` | nœud `g1_jetson` : `/g1_jetson/etat` à 1 Hz ; `--lire` (pour `etat`) ; `--sujets` (pour `verifier`) |
| `jetson.py` | le code de `bin/g1-jetson` (Python du système, sans ROS) |
| `tests/` | `test_reseau.py` (fausses sorties de `ip -o -4 addr`), `test_jetson.py` (commandes produites, refus, à blanc, faux docker/ssh), `test_image.py` (l'image amd64 en `--network none`, sautés sans elle) |

```bash
.venv-projet/bin/python -m pytest docker/tests -q     # 71 tests, 30 s (l'image amd64 doit exister)
G1_TEST_CAMERA=/dev/v4l/by-id/usb-e-con_Systems_See3CAM_11CUG_1A15C950-video-index0 \
  .venv-projet/bin/python -m pytest docker/tests/test_image.py -k camera    # la vraie See3CAM dans le conteneur
tests_e2e/tout.sh 16                                  # critère 16 : 15 s si l'image est à jour
E2E_NIVEAU2=1 tests_e2e/tout.sh 16                    # plus le niveau 2 en répétition, navigation dans le conteneur (+70 s)
E2E_ARM64=1 tests_e2e/tout.sh 16                      # plus l'image arm64, navigation comprise, par émulation (+80 s)
```

Outils du critère (`tests_e2e/critere_16_outils.py`) : faux service « sport » minimal (sans lui,
le pont serait `robot_muet`), observation depuis l'hôte (nœuds, états conformes aux schémas),
verrou `/pont/arret`, dernier ordre reçu (le pont envoie un arrêt en quittant), repérage sans
l'Atelier et vérité terrain du faux G1.

## Construction

`g1-jetson construire [--arch arm64|amd64]` assemble le contexte dans un dossier temporaire
(quelques Mo, jamais le dépôt) : `Dockerfile`, les scripts ci-dessus, `unitree_api` (depuis
`third_party/unitree_ros2`), `atelier/__init__.py`, `atelier/lieu/`,
`atelier/scan/{__init__,slam_client}.py`, puis `ws/src/g1_nav` et `ws/src/g1_bridge` copiés au
moment de la construction (sans `test/` ni `__pycache__`). Son **empreinte** (sha256 des fichiers
et de l'image de base) est l'étiquette `fr.robot-g1.empreinte` de l'image : si elle n'a pas
changé, l'image est réutilisée sans rien reconstruire. Après chaque construction, ou réutilisation,
les vérifications de l'image passent : architecture, `ros2 pkg prefix`, `RMW_IMPLEMENTATION`,
imports Python.

Mesures sur le PC du projet (16 cœurs, Internet) :

| | amd64 | arm64 (émulation qemu) |
|---|---|---|
| première construction (base déjà téléchargée) | 1,6 min | 3,9 min (apt 2,5 min, `unitree_api` 57 s) |
| après une modification de `g1_nav` ou `g1_bridge` | 0,3 à 0,4 min | 0,5 min |
| taille compressée (décompressée) | 0,47 Go | 0,45 Go (1,5 Go une fois chargée dans Docker 24) |
| archive `docker save \| gzip -1` | | 0,45 Go en 11 s ; `docker load` (Docker 24.0.7) en 13 s |

**Base par empreinte.** Avec le magasin d'images containerd de Docker 29 (`driver-type:
io.containerd.snapshotter.v1`), `ros:humble-ros-base-jammy` désigne les deux architectures à la
fois, et le constructeur classique (sans buildx) prenait l'amd64 même avec
`--platform linux/arm64` : la première tentative a installé des paquets `:amd64`, puis s'est
arrêtée sur « does not provide the specified platform ». `construire` passe donc
`--build-arg BASE=ros:humble-ros-base-jammy@sha256:<manifeste de l'architecture>`. Sur un Docker
plus ancien (le Jetson), le nom seul suffit.

**Nav2 sans RViz.** Le contrat nomme `ros-humble-navigation2`. Ce méta-paquet installe aussi
`nav2_rviz_plugins` (RViz, Qt, Ogre) et `nav2_waypoint_follower` (OpenCV). L'image installe donc
tous ses autres composants un par un. Elle passe ainsi de 0,74 à 0,47 Go compressés, et le
contrat interdit RViz dans le conteneur.

**Sous émulation**, qemu-user ne sait pas faire `setsockopt(IP_MULTICAST_IF)` : CycloneDDS ne
crée pas son domaine sur une interface multicast (« ddsi_udp_create_conn: set IP_MULTICAST_IF
failed: Unsupported »), et chaque nœud meurt. Le critère 16 (`E2E_ARM64=1`) fait donc parler
l'image arm64 et l'hôte en unicast sur `lo` (`G1_CYCLONEDDS_URI`, pairs 127.0.0.1). Le Jetson,
natif, n'est pas concerné.

## Le nœud pilotage (vague 4)

L'image contient aussi `unitree_hg` (rt/arm_sdk, /lowstate ; couche 2b, compilée après
`unitree_api` pour garder son cache), `python3-tornado` (couche 2c), `g1_pilotage`, et depuis
l'assemblage de la vague 4 `g1_equipe` avec `atelier/equipe/` (le nœud `dialogue` de l'équipe peut
tourner sur le Jetson : `ros2 run g1_equipe dialogue --ros-args -p lieu:=<id>` dans
`g1-jetson shell` ; il n'est pas lancé d'office). Avec
`G1_PILOTAGE=1`, `demarrer.sh` lance l'exécutable `pilote` (pas `ros2 run` : SIGINT lui arrive
directement) sur `G1_PILOTAGE_PORT` (8010), en navigation comme en veille ; la ligne de démarrage
le dit (« pilotage port 8010 avec jeton »). À l'arrêt, il s'arrête en premier (SIGINT, 5 s) : bras
rendus au contrôleur d'Unitree en 1 s, StopMove, main rendue au guide.

`g1-jetson demarrer` (robot) passe `G1_PILOTAGE=1`, le port et le jeton `G1_PILOTAGE_JETON`
(sinon celui du fichier `~/robot-g1/opt/jetson/jeton_pilotage`, créé au premier démarrage, que
l'Atelier relit) ; `--local` passe `G1_PILOTAGE=0`, sauf `G1_PILOTAGE=1` dans le terminal.
`G1_VITESSE_MAX` est transmise aussi en veille : elle baisse les plafonds du joystick et des pas.

## Lancement

`g1-jetson demarrer` produit la commande du contrat (section 10.2) : `--network host --init
--restart no --stop-timeout 20 --user <uid>:<gid> --cpus 4 --memory 4g`, lieux en lecture seule,
journaux montés. Ajouts : `--log-opt max-size=20m --log-opt max-file=5`, pour que les journaux
de Nav2 ne remplissent pas le disque du Jetson, et `--runtime R` avec `G1_JETSON_RUNTIME=R`. Un
conteneur arrêté garde son journal jusqu'au `demarrer` suivant, qui le retire ; `arreter` fait
`docker stop`, puis `docker rm`.

Variables transmises du terminal au conteneur, si elles sont définies : `G1_SIMU`,
`G1_INTERFACES`, `G1_CYCLONEDDS_URI`, `G1_VITESSE_MAX` (premiers essais : vitesse maximale en
m/s, au plus 0,4, comme `demarrer --vitesse-max` ; le conteneur la passe en `vitesse_max:=` à
`navigation.launch.py`, qui baisse les plafonds du pont dans la même proportion). Variables de `g1-jetson` lui-même : `G1_JETSON` (hôte ssh),
`G1_JETSON_NOM` (nom du conteneur local), `G1_JETSON_ARCH` (image arm64 sur le PC, par
émulation), `G1_JETSON_RUNTIME`, `G1_JETSON_CPUS_CONSTRUCTION` (`--cpuset-cpus` de
`docker build`, pour laisser des cœurs aux autres) et `G1_SLAM_FAUX=1` (aucun ssh, sauf à blanc).

Essai dans un Docker 24.0.7 isolé (`docker:24.0.7-dind`, sur le PC, le 25/10) : l'archive
arm64 de Docker 29 se charge (même empreinte), l'image tourne, et la commande `docker run`
exacte du robot démarre la navigation avec `G1_INTERFACES=auto`, sur une interface factice en
192.168.123.164 et l'utilisateur 1000. `docker stop` l'arrête en 4,4 s, et le pont envoie son
arrêt.

## La caméra de poitrine (vague 5)

- **Image** : couche **2d**, après la 2c (le cache des couches 1 et 2 est gardé) : `python3-pil` et
  `v4l-utils` (couche de 9 Mo, mesurée sur l'image amd64 ; numpy est déjà là ; pas d'OpenCV, 580 Mo). `construire` vérifie dans
  l'image `import PIL, numpy`, `v4l2-ctl` et l'exécutable `camera_usb` de `g1_equipe`.
- **Lancement** (`jetson.py`) : `choisir_camera` cherche la See3CAM (le `peripherique`
  `/dev/v4l/by-id/…` de `camera.yaml` du lieu, sinon `/dev/v4l/by-id/*See3CAM*-video-index0`) :
  par `ssh` sur le Jetson (`script_camera`), en Python avec `--local`. Trouvée : `--device <chemin
  résolu, /dev/videoN>:/dev/g1_camera --group-add <groupe du périphérique>` juste après
  `--memory 4g`, et `-e G1_CAMERA=/dev/g1_camera`. On passe le chemin résolu : le nom by-id ne
  sert qu'à la retrouver. Absente : rien de tout cela, un message, et jamais d'échec. Lien USB
  sous 5000 Mbit/s : un avertissement. `G1_CAMERA=0` : pas de caméra ; `G1_CAMERA=/dev/…` : celle-là.
  À blanc sur le robot, la caméra n'est pas cherchée (la commande de recherche est montrée).
  Les tests remplacent `/dev/v4l/by-id` et `/sys/class/video4linux` par `G1_CAMERA_BY_ID` et
  `G1_CAMERA_SYS`.
- **Dans le conteneur** (`demarrer.sh`) : avec `G1_CAMERA` (sauf `G1_LANCEMENT=commande`), lance
  l'exécutable `camera_usb` (`-p peripherique:=/dev/g1_camera`, et `-p lieu:=/lieux/<id>` en
  navigation : `camera.yaml`) ; à l'arrêt, il s'arrête après le pilotage (SIGINT, 3 s : v4l2-ctl
  arrêté). La ligne de démarrage dit « caméra /dev/g1_camera », « caméra non » ou « caméra absente
  (… introuvable) ». `presence.py` publie `camera` dans `/g1_jetson/etat`.
- **Vitesse des premiers essais** : `G1_VITESSE_MAX` et `--vitesse-max` refusés sous 0,2 m/s (« le
  robot ne marche pas sous 0,2 m/s », mesuré le 27/10 ; `VITESSE_MAX_MIN` et
  `MESSAGE_VITESSE_MAX_BASSE` de `atelier.lieu.robot`, copiés dans `jetson.py` et `demarrer.sh`,
  comparés par `test_jetson.py`) et au-dessus de 0,4 (plafond du pont), en navigation comme en veille.
- **`verifier`** : une ligne par See3CAM du Jetson (`OK` en USB 3, `PROBLÈME` en USB 2, `info` sans caméra).
- **Essayé le 31/10 sur le PC** (sans reconstruire l'image complète) : une image d'essai faite de
  `g1-jetson:amd64` plus la couche 2d et les fichiers à jour (23 s de construction, +2,7 Mo) ; la
  commande `docker run` exacte de `g1-jetson demarrer --local --veille` avec la vraie See3CAM du PC :
  l'utilisateur 1000 lit `/dev/g1_camera` grâce à `--group-add 44`, `camera_usb` publie 10 images
  par seconde vues hors du conteneur, débit USB lu dans le conteneur (5000), `docker stop` en 0,6 s,
  code 0, plus de `v4l2-ctl`. Refait l'après-midi du 31/10 avec la webcam du portable (la See3CAM
  était débranchée) : `g1-jetson:amd64` reconstruite par le critère 16 (1,1 min grâce au cache),
  `g1-jetson demarrer --local --veille` avec `G1_CAMERA=/dev/v4l/by-id/…webcam…-video-index0` :
  `--device /dev/video0:/dev/g1_camera --group-add 44` après `--memory 4g`, l'avertissement USB 2,
  « caméra /dev/g1_camera » au démarrage, 10 images par seconde de 640 × 360 lues sur l'hôte et
  servies par l'Atelier, `g1-jetson etat` la montre, arrêt propre ; et `docker/tests` avec
  `G1_TEST_CAMERA=… G1_TEST_CAMERA_IPS=8` (la webcam fait 10 images par seconde en 1280 × 720).
