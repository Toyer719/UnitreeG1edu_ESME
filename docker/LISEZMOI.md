# docker/ : le conteneur g1-jetson

Conteneur ROS 2 Humble du Jetson du G1 (section 10.2 du plan) : Nav2, guide, relais
`odom_vers_tf` et pont `pont_g1`. Guide pas à pas pour le jour du robot : `docs/jetson.md`.

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
.venv-projet/bin/python -m pytest docker/tests -q     # 52 tests, 25 s (l'image amd64 doit exister)
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
