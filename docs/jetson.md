# Installer la navigation sur le Jetson du G1

Ce guide sert le jour où le robot est là. Il installe sur le Jetson du G1 le **conteneur
`g1-jetson`** : ROS 2 Humble, Nav2, le guide, le relais de position (`odom_vers_tf`) et le pont
vers la marche (`pont_g1`). Le PC garde l'Atelier.

Tout se fait depuis le PC avec une seule commande, `g1-jetson`. Chaque sous-commande accepte
`--help`, et `--dry-run` pour voir ce qui serait lancé sans rien lancer.

Durée : environ 30 minutes la première fois, dont 10 minutes d'attente.

```
PC (Atelier, au câble eno2, 192.168.123.99)          Jetson du G1 (192.168.123.164)
  g1-jetson construire   → image g1-jetson:arm64
  g1-jetson envoyer      ─────── ssh + scp ────────►  docker load
  g1-jetson demarrer     ─────── ssh ──────────────►  conteneur g1-jetson (réseau de l'hôte, domaine 0)
                                                        Nav2, guide, odom_vers_tf, pont_g1
  Atelier, mode Robot    ◄────── DDS (câble) ───────►  /guide/*, /pont/*, /reperage/*
```

## Avant la séance (sans robot, au bureau)

1. Construire l'image du Jetson et la vérifier. Il faut Internet sur le PC.

   ```bash
   g1-jetson construire --arch amd64          # l'image du PC, pour l'essai ci-dessous (2 à 3 min)
   ~/robot-g1/tests_e2e/tout.sh 16            # critère 16 : le conteneur tourne et se pilote depuis le PC
   g1-jetson construire                       # l'image du Jetson (arm64), par émulation
   ```

   Sur le PC du projet, la première construction arm64 prend **4 minutes**. Ensuite, après une
   modification de `g1_nav` ou de `g1_bridge`, elle prend **30 secondes**, car le reste est en
   cache. `construire` finit toujours par des vérifications dans l'image : architecture,
   paquets, CycloneDDS, Python de l'Atelier. Une image déjà à jour est réutilisée telle quelle.

2. Pour aller plus loin :
   - `E2E_NIVEAU2=1 ~/robot-g1/tests_e2e/tout.sh 16` joue aussi le niveau 2 en répétition avec la
     navigation dans le conteneur : Gazebo et le faux G1 sur le PC, « Repérer », puis b204
     (arrivée à 0,10 m en 68 s) ;
   - `E2E_ARM64=1 ~/robot-g1/tests_e2e/tout.sh 16` fait aussi tourner la navigation de l'image
     arm64 sur le PC, par émulation (environ 1 minute 30 de plus).

3. Voir à blanc ce que fera la séance :

   ```bash
   G1_SLAM_FAUX=1 g1-jetson envoyer --dry-run
   G1_SLAM_FAUX=1 g1-jetson demarrer --lieu demo --etage rdc --dry-run
   ```

4. Le lieu du robot doit avoir sa carte : `cartes/<etage>.yaml`, issue d'un scan adopté ou du
   monde dessiné.

## Le jour du robot

### 1. Relier le PC au robot

Robot sur son portique, télécommande en main (elle reste l'arrêt d'urgence). Branchez le câble
Ethernet, puis dans un terminal :

```bash
source ~/robot-g1/setup/robot.sh      # doit dire « le robot répond »
```

### 2. La clé ssh (une seule fois)

`g1-jetson` ne tape jamais de mot de passe. Il lui faut une clé ssh installée sur le Jetson.

```bash
ls ~/.ssh/id_*.pub || ssh-keygen -t ed25519        # crée une clé si le PC n'en a pas (Entrée 3 fois)
ssh-copy-id unitree@192.168.123.164                # mot de passe : 123
ssh unitree@192.168.123.164 true && echo "clé OK"  # ne doit plus demander de mot de passe
```

Si un autre Jetson se trouve à une autre adresse, ajoutez `export G1_JETSON=unitree@ADRESSE`
avant les commandes.

### 3. Vérifier le Jetson

```bash
g1-jetson verifier
```

Chaque ligne dit `OK`, `PROBLÈME` ou `info` :

| Ligne | Si c'est un PROBLÈME |
|---|---|
| architecture aarch64 | ce n'est pas le Jetson : vérifiez `G1_JETSON` |
| Docker utilisable sans sudo | `ssh unitree@192.168.123.164`, puis `sudo usermod -aG docker unitree` (mot de passe 123), puis `exit` et recommencez |
| place libre (4 Go au moins) | faites de la place sur le Jetson : `docker image prune`, vieux fichiers |
| mémoire disponible (4 Go au moins) | des programmes d'Unitree occupent la mémoire : notez-le, et essayez quand même |
| réseau interne du robot (192.168.123.x) | le Jetson n'a pas d'adresse sur le réseau du robot : noter `ip -o -4 addr` du Jetson |
| horloge du Jetson | plus d'une seconde d'écart avec le PC : à noter (point 4 de la séance, plan 10.9) |
| Internet depuis le Jetson | information : oui permet le plan B (construire sur le Jetson) |
| image g1-jetson:arm64 | absente avant `envoyer`, c'est normal |

Une fois l'image envoyée (étape 4), `verifier` lance aussi un conteneur jetable qui doit voir les
sujets du robot `/state_estimator/odom_pelvis` et `/lf/sportmodestate` depuis ROS 2 Humble. C'est
la preuve que le conteneur parle au robot.

### 4. Envoyer l'image

```bash
g1-jetson envoyer
```

Cette commande fait l'archive (`docker save | gzip`, 0,45 Go, gardée dans
`~/robot-g1/opt/jetson/`), la copie par scp au câble, puis la charge sur le Jetson
(`docker load`). Elle vérifie ensuite que l'image du Jetson est bien celle du PC (même
empreinte). Comptez 2 à 5 minutes. Relancez ensuite `g1-jetson verifier` : la dernière ligne doit
voir les sujets du robot.

### 5. Premier démarrage, en veille

En veille, le conteneur ne lance pas la navigation. Il annonce seulement sa présence.

```bash
g1-jetson demarrer --veille
g1-jetson etat                       # « running », et le dernier /g1_jetson/etat
g1-jetson shell                      # un terminal dans le conteneur (exit pour sortir)
#   ros2 topic list | grep -E 'odom_pelvis|sportmodestate|slam'
#   ros2 interface show unitree_api/msg/Request
g1-jetson arreter
```

### 6. Démarrer la navigation

```bash
g1-jetson demarrer --lieu demo --etage rdc
```

Le lieu est d'abord copié sur le Jetson, dans `~/robot-g1/lieux/<id>`, sans le dossier `scans/`.
Le conteneur démarre ensuite, et la commande rend la main quand il tourne (30 s au plus). Elle
affiche la ligne de démarrage, par exemple :

```
g1-jetson : domaine 0, interfaces eth0, lieu demo (étage rdc), lancement navigation (localisation unitree, simu false), …, aarch64
```

Vérifier depuis le PC, dans le terminal où `robot.sh` a été chargé (domaine 0) :

```bash
ros2 node list --no-daemon | grep -E 'pont_g1|odom_vers_tf|guide|bt_navigator'
ros2 topic echo --once /pont/etat          # attente_reperage tant que le robot n'est pas repéré
ros2 topic echo --once /reperage/etat      # non_repere
```

Ensuite, dans l'Atelier (`g1-atelier`), onglet Simulation, mode « Robot » : « Repérer le robot »,
puis « Y aller ». En mode « Robot », l'Atelier lance lui-même `g1-jetson demarrer --lieu L
--etage E`, et `g1-jetson arreter` à l'arrêt : la ligne de commande ci-dessus sert aux essais et
au dépannage.

Options de `demarrer` :
- `--vitesse-max 0.2` (ou la variable `G1_VITESSE_MAX=0.2`, que l'Atelier transmet aussi) : pour
  les premiers essais, les plafonds du pont baissent dans la même proportion (0,2 m/s en avant,
  0,125 m/s de côté, 0,3 rad/s en rotation, au lieu de 0,4 / 0,25 / 0,6). La ligne de démarrage
  l'affiche (« vitesse max 0.2 m/s ») ;
- `--localisation amcl` : le secours (notre carte et le LiDAR) à la place de la relocalisation
  d'Unitree ;
- `--wifi wlan0 --pair 192.168.1.50` : l'Atelier par le Wi-Fi (multicast coupé sur le Wi-Fi,
  le PC joint en unicast). À essayer en option seulement.

### 7. Suivre, arrêter

```bash
g1-jetson etat               # code 0 s'il tourne
g1-jetson journal -f         # le journal en direct (Ctrl+C pour quitter, le conteneur continue)
g1-jetson arreter            # arrêt propre : le pont envoie un arrêt au robot, puis le conteneur est retiré
```

L'arrêt prend 5 secondes environ, et 20 secondes au plus. Le conteneur ne redémarre jamais tout
seul : après un redémarrage du robot, relancez `g1-jetson demarrer`. On ne relance pas une
navigation sans un humain.

### 6 bis. Le pilotage par le Wi-Fi (onglet Pilotage, vague 4)

Avec le robot, `g1-jetson demarrer` lance aussi le **nœud pilotage** dans le conteneur
(`G1_PILOTAGE=1` par défaut ; `G1_PILOTAGE=0 g1-jetson demarrer …` s'en passe). C'est lui qui
reçoit les ordres de l'onglet Pilotage de l'Atelier : postures, joystick, gestes, voix, LED,
danses du robot et chorégraphies. Il écoute le port 8010 (`G1_PILOTAGE_PORT`) sur toutes les
interfaces du Jetson, et exige un **jeton** : la première fois, `g1-jetson demarrer` le crée dans
`~/robot-g1/opt/jetson/jeton_pilotage` (sur le PC, jamais dans Git), et l'Atelier le relit dans ce
fichier. Sans le bon jeton, le nœud répond 401.

L'Atelier joint le nœud à l'adresse `G1_PILOTAGE_URL` : au câble
`G1_PILOTAGE_URL=http://192.168.123.164:8010 g1-atelier`, par le Wi-Fi
`G1_PILOTAGE_URL=http://<adresse Wi-Fi du Jetson>:8010 g1-atelier`. Ce n'est pas DDS : une simple
connexion HTTP et WebSocket, qui ne demande aucun réglage réseau de plus. Si le Wi-Fi ou la page se
coupent, le nœud arrête le robot lui-même 0,5 s après le dernier ordre (homme mort).

La ligne de démarrage le dit : « pilotage port 8010 avec jeton ». Vérifier depuis le PC :

```bash
curl -s -H "X-Jeton: $(cat ~/robot-g1/opt/jetson/jeton_pilotage)" http://192.168.123.164:8010/etat
g1-pilotage etat        # avec G1_PILOTAGE_URL et G1_PILOTAGE_JETON exportés
```

À l'arrêt du conteneur, le nœud pilotage s'arrête en premier : bras rendus au contrôleur
d'Unitree en 1 s, StopMove, et le guide reprend la main.

**En cas de problème pendant une marche : la télécommande d'abord.** Ensuite, « Bloquer le robot »
dans l'Atelier, ou depuis un terminal :
`ros2 topic pub --once --qos-durability transient_local --qos-reliability reliable /pont/arret std_msgs/msg/Bool "{data: true}"`.

Les journaux de ROS 2 restent sur le Jetson, dans `~/robot-g1/journaux/jetson/ros/log/`. Le
journal de Docker est limité à 5 fichiers de 20 Mo.

## Points incertains, à vérifier le jour du robot

1. **Le nom de l'interface réseau interne du Jetson** (`eth0` ?). Le conteneur la trouve seul
   (`G1_INTERFACES=auto` : l'interface qui a une adresse 192.168.123.x), et `verifier` l'affiche.
   Si plusieurs interfaces ont une adresse 192.168.123.x, toutes sont prises. Pour en imposer une :
   `G1_INTERFACES=eth0 g1-jetson demarrer …`. Sans aucune, le conteneur s'arrête sur « réseau du
   robot introuvable ».
2. **L'accès Internet du Jetson.** Inutile dans le cas normal : l'image vient du PC. Il ne sert
   qu'au plan B ci-dessous.
3. **L'espace disque.** Il faut environ 2 Go : l'archive de 0,45 Go, effacée après le chargement,
   et l'image de 1,5 Go. `verifier` en demande 4 pour garder de la marge. La place est vérifiée
   dans le dossier personnel et dans celui de Docker, qui peuvent être sur deux disques.
4. **Docker sans sudo** pour l'utilisateur `unitree` (groupe `docker`).
5. **Le runtime par défaut de Docker sur le Jetson** (`nvidia` ?). `verifier` l'affiche. Le
   conteneur n'utilise pas le GPU. Si le runtime nvidia gêne (bibliothèques montées en trop,
   erreur au lancement), relancez avec `G1_JETSON_RUNTIME=runc g1-jetson demarrer …`.
6. **Les limites `--cpus 4 --memory 4g`.** Suffisent-elles, et le noyau L4T accepte-t-il la
   limite de mémoire ? Si Docker affiche « kernel does not support memory limit », la limite est
   ignorée, mais le conteneur tourne quand même.
7. **Le chargement de l'archive par Docker 24.0.7.** Il a été essayé sur le PC, dans un Docker
   24.0.7 isolé (« Docker dans Docker ») : `docker load` réussit et l'image tourne. La commande
   `docker run` exacte du robot y a été essayée, avec une interface factice en 192.168.123.164 et
   l'utilisateur 1000. Ce n'est pas le vrai Jetson.
8. **L'horloge** : l'écart entre le PC1 du robot et le Jetson n'est pas mesurable depuis le PC.
   Le relais horodate lui-même ses messages, pour ne pas en dépendre.
9. **Le pilotage par le Wi-Fi** (vague 4) : le port 8010 du Jetson est-il joignable depuis le PC
   par le Wi-Fi (pare-feu, isolement des clients du point d'accès) ? Latence du joystick par le
   Wi-Fi, et arrêt seul 0,5 s après une coupure (Wi-Fi coupé exprès, page fermée).

## Plan B : si l'image ne passe pas

- **`docker load` échoue sur le Jetson** (format d'archive). Refaites l'archive avec
  `docker save --platform linux/arm64 g1-jetson:arm64 | gzip -1 > ~/robot-g1/opt/jetson/g1-jetson_arm64.tar.gz`
  (Docker 29 sait le faire), puis envoyez-la à la main, avec les commandes `scp` et `docker load`
  de `g1-jetson envoyer --dry-run`.
- **Construire sur le Jetson**, s'il a Internet (Wi-Fi). Le Jetson est arm64 : pas d'émulation.
  Comptez sans doute 10 minutes, selon le débit (145 Mo de paquets à télécharger).

  ```bash
  g1-jetson construire --contexte /tmp/g1_contexte         # sur le PC : le contexte seul (quelques Mo)
  scp -r /tmp/g1_contexte unitree@192.168.123.164:robot-g1/opt/jetson/contexte
  ssh unitree@192.168.123.164
  cd robot-g1/opt/jetson && docker build -t g1-jetson:arm64 --build-arg G1_EMPREINTE=<empreinte affichée> contexte
  ```

- **La construction arm64 échoue sur le PC** au milieu (réseau, paquet) : `g1-jetson construire`
  reprend aux couches déjà faites. `--sans-cache` reconstruit tout. Le journal est dans
  `~/robot-g1/journaux/jetson_construire_arm64.log`.
- **Sous l'émulation du PC**, CycloneDDS ne peut pas utiliser le multicast (`IP_MULTICAST_IF` non
  émulé par qemu). Pour faire tourner l'image arm64 sur le PC, le critère 16 passe donc en
  unicast sur `lo`. Le vrai Jetson n'est pas concerné.

## Ce que contient le conteneur

| Élément | Valeur |
|---|---|
| Base | `ros:humble-ros-base-jammy` (Ubuntu 22.04), désignée par l'empreinte de l'architecture |
| Paquets apt | CycloneDDS, les composants de Nav2 (sans RViz : ni `nav2_rviz_plugins`, ni `nav2_waypoint_follower`), `pointcloud_to_laserscan`, numpy, PyYAML, iproute2 |
| Paquets apt (vague 4) | `python3-tornado` (API HTTP et WebSocket du nœud pilotage) |
| Compilés dans `/opt/g1/install` | `unitree_api`, `unitree_hg` (rt/arm_sdk, /lowstate), `g1_nav`, `g1_bridge`, `g1_pilotage`, `g1_equipe` (nœuds de l'équipe : `dialogue`, `fausse_camera`, `voix_journal`, non lancés d'office) |
| Python dans `/opt/g1/python` | `atelier/__init__.py`, `atelier/lieu/`, `atelier/scan/slam_client.py`, `atelier/equipe/` (chatbot d'exemple et relais) |
| Version | `/opt/g1/VERSION` : date, commit, empreinte ; dans `/g1_jetson/etat` (1 Hz) |
| Lancement | réseau de l'hôte, `--init`, aucun redémarrage automatique, utilisateur `unitree`, lieux en lecture seule, pas de `--privileged` |

Variables du conteneur (section 10.2 du plan) : `ROS_DOMAIN_ID` (0), `G1_INTERFACES`
(`auto`, `defaut` ou des noms), `G1_WIFI`, `G1_PAIRS`, `G1_LANCEMENT` (`navigation`, `veille`
ou `commande`), `G1_LIEU`, `G1_ETAGE`, `G1_LOCALISATION` (`unitree` ou `amcl`), `G1_SIMU`,
`G1_VITESSE_MAX` (premiers essais, m/s), `G1_CYCLONEDDS_URI`. Détails techniques :
`docker/LISEZMOI.md`. Le déroulé complet de la première séance avec le robot (pont, repérage,
conteneur, premier trajet) : `docs/seance-robot.md`.

Essai sur le PC, sans robot : `g1-jetson tester-local --lieu demo --etage rdc` (ou
`g1-jetson demarrer --local …` : image amd64, réseau de l'hôte, domaine du terminal, lieu monté
en lecture seule ; `g1-jetson arreter --local` pour finir). Avec `G1_SIMU=true` et Gazebo
lancé par `g1-monde simuler --jumeau`, c'est la répétition du niveau 2 dans le conteneur.
