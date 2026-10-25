# Robot d'accueil G1

Poste de développement du projet robot d'accueil sur Unitree G1 EDU.
Ubuntu 22.04, ROS 2 Humble, SDK Unitree, simulation MuJoCo.

## Les commandes

Toutes les commandes s'utilisent dans un terminal ouvert après l'installation (Ctrl+Alt+T).

| Commande | À quoi elle sert | Robot nécessaire |
|---|---|---|
| `g1-sim-marche` | G1 qui marche dans MuJoCo, piloté à la manette ou au clavier | non |
| `g1-sim` | Simulateur officiel Unitree : G1 complet relié au SDK | non |
| `g1-sim-demo` | Exemple bas niveau d'Unitree joué dans `g1-sim` | non |
| `g1-etat lo` | État du G1 simulé, en lecture seule | non |
| `source ~/robot-g1/setup/robot.sh` | Relier le PC au robot par le câble Ethernet | oui |
| `g1-etat` | État du vrai G1, en lecture seule | oui |
| `g1-telecommande` | Ce que le G1 reçoit de sa télécommande Unitree (`lo` : simulateur) | oui |
| `g1-releve` | Relevé du robot (version, sujets publiés, LiDAR, Jetson) dans `docs/releves/` | oui |
| `g1-nuage` | Affiche dans RViz le nuage de points du LiDAR publié sur le réseau | oui |
| `g1-premiers-pas` | Premiers tests : voix, LED, gestes, quelques pas | oui |
| `g1-manette` | Piloter le vrai G1 à la manette | oui |
| `g1-manette-virtuelle` | Manette Xbox virtuelle (clavier ou souris), vue comme une vraie | non |
| `g1-personnes` | Détecter et suivre les personnes (webcam ou caméra) | non |
| `g1-parler "texte"` | Voix française hors ligne (Piper) | non |
| `g1-ecouter` | Reconnaissance vocale en français (Vosk, faster-whisper) | non |
| `g1-atelier` | Atelier G1 : décrire un lieu, fabriquer la carte, essayer le guide dans Gazebo (section ci-dessous) | non |

Le calendrier jour par jour, avec toutes les commandes de chaque étape, est sur la page du
projet : https://claude.ai/artifact/3sjPDb9CYcwJGrTZ8vgxNP

Chaque commande accepte `--help`. Pour arrêter une commande : **Ctrl+C** dans le terminal,
ou fermer la fenêtre MuJoCo.

Si un terminal répond « commande introuvable », il a été ouvert avant l'installation :
tapez `source ~/.bashrc` ou ouvrez-en un nouveau.

## Atelier G1 : décrire un lieu et y essayer le guide

L'Atelier G1 sert à décrire un bâtiment (murs, portes, meubles, piétons), à en tirer la carte
de navigation, à placer les salles et les itinéraires, puis à essayer le guide dans Gazebo,
**sans robot**. Le même lieu servira ensuite au vrai G1 : seule la carte (scan au lieu du
monde dessiné) et le moteur de déplacement changent.
Plan : `docs/plan-atelier-multi-agents.md`. Décisions et état : `docs/journal-atelier.md`.

### Le plus simple : l'interface web

```bash
g1-atelier                 # ouvre http://localhost:8000 dans le navigateur
```

Les onglets se suivent de gauche à droite : **Lieux** (créer ou choisir un lieu),
**Monde** (dessiner murs, passages, meubles et piétons, vue 3D), **Carte**
(« Fabriquer la carte »), **Salles**, **Itinéraires** (nœuds et couloirs de 8 m au plus),
**Zones** (interdites en rouge, lentes en orange), **Simulation** (« Lancer la simulation »,
puis « Y aller » ; gros bouton ARRÊT) et **Scan** (à essayer avec le faux service).
Ctrl+C dans le terminal arrête le serveur, et avec lui la simulation et la navigation.

### Les mêmes étapes en ligne de commande

Sur le lieu fourni `demo` (lycée de 30 × 20 m, deux couloirs, accueil et cinq salles) :

```bash
g1-lieu valider --lieu demo                                 # vérifie les fichiers et dit quoi corriger
g1-monde generer --lieu demo --etage rdc                    # monde Gazebo, carte 2D, masque des zones interdites
g1-monde simuler --lieu demo --etage rdc --sans-fenetre     # terminal 1 : Gazebo, robot proxy, piétons
g1-guide navigation --lieu demo --etage rdc --simu          # terminal 2 : Nav2, routeur et guide
g1-guide aller b204                                         # terminal 3 : le robot y va (suit l'état jusqu'à l'arrivée)
g1-guide stop                                               # arrêt immédiat
```

Sans `--sans-fenetre`, Gazebo s'ouvre dans une fenêtre. `--lieu` accepte un id (dossier de
`~/robot-g1/lieux/`) ou un chemin.

| Commande | À quoi elle sert |
|---|---|
| `g1-atelier [--port 8000] [--sans-navigateur] [--hote 0.0.0.0]` | Le logiciel web (`--hote 0.0.0.0` : depuis une tablette du réseau) |
| `g1-lieu creer ID --nom "Nom"`, `g1-lieu valider --lieu L`, `g1-lieu liste` | Créer, vérifier, lister les lieux |
| `g1-monde generer --lieu L --etage E` | Monde Gazebo `.sdf`, carte `.pgm`/`.yaml` et masque, depuis le monde dessiné |
| `g1-monde simuler --lieu L --etage E [--sans-fenetre]` | Gazebo avec le robot proxy (LiDAR à 1,2 m) et les piétons |
| `g1-guide navigation --lieu L --etage E --simu` | Nav2, routeur et guide (sans `--simu` : vrai robot) |
| `g1-guide aller ID`, `g1-guide stop`, `g1-guide etat` | Envoyer le robot vers une salle, l'arrêter, voir l'état du guide |
| `g1-banc --lieu L --etage E --trajets 20 --lancer` | Banc de test : trajets tirés au sort, résultats en CSV dans `journaux/` |
| `g1-slam scan-debut`, `scan-fin --nom N`, `relocaliser`, `aller`, `pause`, `reprendre`, `arreter` | Service de cartographie du G1 (`--faux` : faux service, à lancer avec `g1-slam faux-service`) |
| `g1-carte-3d --lieu L --etage E --enregistrement DOSSIER` | Enregistrement ros2 bag → nuage 3D `.pcd` |
| `g1-carte-2d --lieu L --etage E` | Nuage 3D → carte 2D de navigation |
| `g1-salle ajouter "Nom" --lieu L` | Ajoute une salle à la position actuelle du robot |

Chaque commande a un alias `gl-…` et accepte `--help`.

### Les fichiers d'un lieu

```
lieux/<id>/
├── lieu.yaml                          nom, étages, accueil
├── mondes/<etage>.monde.yaml          monde dessiné : murs, objets, piétons, départ du robot
├── mondes/<etage>.sdf                 monde Gazebo (généré)
├── cartes/<etage>.pgm + .yaml         carte de navigation (générée, ou issue du scan)
├── cartes/<etage>_interdit.pgm + .yaml   masque des zones interdites (généré)
├── salles.yaml                        salles : nom, alias, position devant la porte, phrase d'arrivée
├── itineraires.yaml                   nœuds et couloirs du guide
└── zones.yaml                         zones interdites et lentes
```

Les formats exacts sont dans `atelier/lieu/schemas/` et dans la section 4 du plan.

### Tester

```bash
cd ~/robot-g1 && .venv-projet/bin/python -m pytest atelier/tests -q    # bibliothèques, serveur, interface : 2 à 3 min
cd ~/robot-g1/ws && colcon test --packages-select g1_sim g1_nav && colcon test-result --all   # paquets ROS 2 : 1 min
~/robot-g1/tests_e2e/tout.sh            # les 10 critères de recette, sans fenêtre : environ 45 min
~/robot-g1/tests_e2e/tout.sh 1 2 3 4    # seulement certains critères
```

Tous les tests tournent sans robot et sans écran, sur des copies de `lieux/demo` dans des
dossiers temporaires. Journaux : `~/robot-g1/journaux/`.

Après une modification de `ws/src/g1_sim` ou `ws/src/g1_nav` (nouveau fichier, lancement,
réglage), recompilez :

```bash
cd ~/robot-g1/ws && colcon build --symlink-install --packages-select g1_sim g1_nav
```

## Simulation

### Le G1 qui marche : `g1-sim-marche`

Le G1 marche grâce à la politique pré-entraînée d'Unitree. Vous lui donnez trois consignes :
avancer (m/s), glisser sur le côté (m/s), tourner (rad/s). Ce sont exactement les trois
valeurs que le vrai robot reçoit avec `LocoClient.Move(vx, vy, vyaw)`.

| Action | Manette | Clavier (fenêtre MuJoCo active) |
|---|---|---|
| Avancer / reculer | stick gauche haut / bas | flèches haut / bas (+/- 0,1 m/s par appui) |
| Glisser sur le côté | stick gauche gauche / droite | Page préc. / Page suiv. |
| Tourner | stick droit | flèches gauche / droite |
| Stop | B | Fin |
| Relever le robot tombé | A | Origine |

La caméra suit le robot. La souris tourne la vue (clic gauche) et zoome (molette).

**Sans manette physique :** lancez d'abord `g1-manette-virtuelle` dans un terminal, puis
`g1-sim-marche` dans un autre. Gardez la fenêtre de la manette virtuelle active :
Z Q S D = stick gauche, flèches = stick droit, Espace = A, B = B, Maj gauche = LB.
Activation une seule fois : `sudo bash ~/robot-g1/setup/activer_manette_virtuelle.sh`.
`g1-sim-marche --test 10` vérifie sans fenêtre que le robot marche 10 s sans tomber.

### Le simulateur officiel : `g1-sim`

Il reproduit le vrai G1 vu par le SDK, moteur par moteur. Un programme du SDK ne voit pas
la différence : il suffit de remplacer l'interface réseau `eno2` par `lo`.

- Le robot pend à un élastique virtuel, comme sur le portique : touche **7** pour le remonter,
  **8** pour le descendre, **9** pour le détacher ou le rattacher.
- Sans programme qui commande ses moteurs, le robot reste mou : c'est normal.
- Une manette branchée au lancement remplace la télécommande Unitree, y compris la manette
  virtuelle (`g1-manette-virtuelle`, à lancer avant). `g1-telecommande lo` affiche ce que le
  robot simulé reçoit.
- `g1-sim --ddl 23` charge la version à 23 degrés de liberté (29 par défaut).

Pour voir le SDK piloter le robot simulé, ouvrez un deuxième terminal pendant que `g1-sim` tourne :

```bash
g1-etat lo       # lit l'état du robot simulé (Ctrl+C pour quitter)
g1-sim-demo      # fait bouger chevilles et bras, moteur par moteur
```

Dans vos propres programmes Python :

```python
from unitree_sdk2py.core.channel import ChannelFactoryInitialize
ChannelFactoryInitialize(0, "lo")     # simulateur
ChannelFactoryInitialize(0, "eno2")   # vrai robot
```

**Limite à connaître :** le simulateur ne contient que la partie bas niveau. La marche
intégrée d'Unitree (`LocoClient`), la voix, la LED et les gestes n'existent que sur le
vrai robot. En simulation, ces appels renvoient l'erreur 3102 ou 3104, c'est normal.

### LiDAR et cartographie

Le pilote du LiDAR (Livox MID-360) et FAST-LIO2 sont dans l'espace de travail `~/robot-g1/ws`.
Adresses réglées pour le G1 dans `ws/src/livox_ros_driver2/config/MID360_config.json` :
PC en 192.168.123.99, LiDAR en 192.168.123.120 (adresse habituelle, à vérifier).

```bash
ros2 launch livox_ros_driver2 rviz_MID360_launch.py                 # voir le nuage de points
ros2 launch livox_ros_driver2 msg_MID360_launch.py                  # format pour FAST-LIO2
ros2 launch fast_lio mapping.launch.py config_file:=mid360.yaml    # carte 3D en direct
```

### Gazebo (navigation)

Gazebo Fortress et Nav2 sont installés. Le monde du bâtiment, le robot « proxy » et la
navigation sont ceux de l'Atelier G1 (section ci-dessus : `g1-monde simuler`,
`g1-guide navigation`). Pour vérifier que Gazebo s'ouvre : `ign gazebo shapes.sdf`.

## Vrai robot

### Avant chaque séance

1. Robot sur son portique, zone dégagée.
2. Une personne garde la télécommande officielle en main pendant tout l'essai.
3. Chargeur du PC branché, batterie du robot chargée.

### La télécommande officielle

Elle reste l'arrêt d'urgence, même quand le PC pilote le robot. Trois modes comptent pour
ce projet (combinaisons de boutons exactes dans le manuel du G1) :

- **amortissement** : les moteurs se relâchent doucement, c'est l'arrêt d'urgence ;
- **mode marche** : le contrôleur d'Unitree tient le robot debout ; `g1-premiers-pas`
  et `g1-manette` en ont besoin ;
- **mode debug** : coupe le contrôleur de marche. Ne jamais l'utiliser hors du portique.
  Ce projet n'en a pas besoin.

### Relier le PC au robot

Branchez le câble Ethernet entre le PC et le robot, puis :

```bash
source ~/robot-g1/setup/robot.sh   # PC en 192.168.123.99 sur le port eno2
g1-etat                            # doit afficher « Connecté »
```

`g1-etat` affiche le nombre de moteurs actifs : 23 ou 29 selon la version de votre G1.
`robot.sh` ne vaut que pour le terminal où vous le lancez : relancez-le dans chaque
nouveau terminal qui parle au robot.

### Premiers tests : `g1-premiers-pas`

Un menu propose, dans l'ordre conseillé : faire parler le robot, changer la LED, faire un
geste, faire coucou, avancer à 0,2 m/s pendant 2 s, tourner sur place. Chaque déplacement
demande une confirmation de sécurité. La voix intégrée ne parle pas français ; la voix
française (Piper) viendra plus tard.

### Piloter à la manette : `g1-manette`

| Bouton | Effet |
|---|---|
| LB (L1) **maintenu** | autorise le mouvement ; relâché, le robot s'arrête |
| Stick gauche | avancer / reculer, glisser |
| Stick droit | tourner |
| B (rond) | arrêt immédiat |
| A (croix) | coucou, robot à l'arrêt |

Vitesse limitée à 0,3 m/s par défaut ; `g1-manette --vitesse-max 0.5` pour aller plus vite
(plafond 0,6 m/s). Chaque consigne envoyée au robot ne vaut que 0,5 s : si la manette se
débranche ou si le programme s'arrête, le robot doit s'arrêter de lui-même. Vérifiez-le lors
du premier essai, robot sur le portique.

## Dépannage

| Message | Cause probable |
|---|---|
| « Aucune donnée du robot sur eno2 » | robot éteint, câble débranché, ou `robot.sh` pas lancé dans ce terminal |
| « Aucune donnée du robot sur lo » | `g1-sim` n'est pas lancé |
| Erreur 3104 (pas de réponse) | robot pas en mode marche, ou commande lancée sur le simulateur |
| Erreur 3102 (envoi impossible) | service absent : normal sur le simulateur |
| `selected interface "lo" is not multicast-capable` | normal, sans conséquence |
| « Aucune manette détectée » | brancher la manette en USB avant de lancer ; vérifier avec `ls /dev/input/js*` |
| Simulation saccadée | lancer avec la carte NVIDIA : `__NV_PRIME_RENDER_OFFLOAD=1 __GLX_VENDOR_LIBRARY_NAME=nvidia g1-sim` |

## Contenu du dossier

```
robot-g1/
├── bin/            commandes g1-*
├── sim/            scripts de simulation
├── robot/          scripts pour le vrai robot
├── outils/         modules communs (manette, connexion, état)
├── atelier/        Atelier G1 : lieu, monde, scan, serveur web, interface, tests
├── lieux/          paquets de lieu (demo : le lycée d'exemple)
├── tests_e2e/      critères de recette de l'Atelier (tout.sh)
├── docs/           plan de l'Atelier, journal, relevés du robot
├── setup/          installation et environnement (env.sh, robot.sh)
├── third_party/    dépôts Unitree, versions dans VERSIONS.txt
├── ws/            espace de travail ROS 2 : pilote LiDAR, FAST-LIO2, g1_sim, g1_nav
├── modeles/       YOLO, Vosk, voix Piper, Whisper
├── opt/           SDK C++ Unitree et SDK Livox compilés
├── .venv-sim/     Python de simulation (MuJoCo, PyTorch processeur)
└── .venv-projet/  Python du projet (YOLO, voix, Open3D, FastAPI, PyTorch CUDA), voit ROS 2
```

Tout réinstaller, dans l'ordre :

```bash
bash ~/robot-g1/setup/installer_pc.sh            # partie système, demande le mot de passe
bash ~/robot-g1/setup/installer_utilisateur.sh   # tout le reste, sans mot de passe
```
