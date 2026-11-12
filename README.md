# Unitree G1 EDU — ESME (« LE PROJET »)

Espace de travail pour le robot humanoïde **Unitree G1 EDU** : simulation MuJoCo,
télécommande virtuelle, apprentissage de la montée d'escaliers (Isaac Gym), perception, et
**Atelier G1**, le logiciel du robot d'accueil (scanner un bâtiment, placer les salles, y guider les
visiteurs en évitant la foule), dans [`atelier-g1/`](#atelier-g1--le-logiciel-du-robot-daccueil-atelier-g1).

> Le dépôt se clone **dans `~/unitree`** : les scripts et raccourcis utilisent ce chemin.

## Contenu

| Chemin | Rôle |
|---|---|
| `virtual_remote/` | Télécommande virtuelle (tkinter) pour piloter le G1 simulé — mode d'emploi et journal des corrections : [`virtual_remote/LISEZMOI.txt`](virtual_remote/LISEZMOI.txt) |
| `patches/` | Nos modifications des dépôts Unitree (un patch par dépôt) + `BASES.txt` (commit Unitree d'origine) |
| `docs/` | [Entraînement escaliers](docs/ENTRAINEMENT_ESCALIERS.md) · [Instructions PC NVIDIA](docs/INSTRUCTIONS_PC_NVIDIA.txt) |
| `scripts/apply_patches.sh` | Sur un nouveau PC : clone les dépôts Unitree et applique les patchs |
| `scripts/export_patches.sh` | Avant un commit : régénère les patchs depuis les dépôts locaux |
| `env.sh` | Raccourcis (`g1_mujoco_py`, `g1_remote`, `g1_deploy_sim`, `g1_walk`, `g1_stairs_eval`…) |
| `install_system.sh` | Installation système : ROS 2 Humble, dépendances, `unitree_sdk2` |
| `perception/` | Détection de personnes YOLO et mémoire des visages : [`perception/LISEZMOI.txt`](perception/LISEZMOI.txt) |
| `atelier-g1/` | **Atelier G1**, le logiciel du robot d'accueil : interface web, navigation (Nav2), simulation Gazebo, vrai robot, borne visiteur. Voir [la section plus bas](#atelier-g1--le-logiciel-du-robot-daccueil-atelier-g1) et son guide complet [`atelier-g1/README.md`](atelier-g1/README.md) |

Les dépôts Unitree (`unitree_rl_gym`, `unitree_mujoco`, `unitree_ros2`, `unitree_sdk2_python`,
`unitree_sdk2`, `unitree_ros`) et `cyclonedds` ne sont **pas** copiés ici : seules nos
modifications le sont, dans `patches/`.

### Ce que contiennent les patchs

- **unitree_rl_gym** : tâche `g1_stairs` (terrain d'escaliers + curriculum, critique avec carte
  de hauteur), scène MuJoCo `scene_stairs.xml` (décor Unitree), `eval_stairs.py`,
  `deploy_real/configs/g1_sim.yaml` (gains bras/taille ×2, **simulation uniquement**).
- **unitree_mujoco** (simulateur Python) : télécommande virtuelle, `lowstate.tick`,
  couple PD recalculé à chaque pas, pas de 2 ms, configuration G1.
- **unitree_ros2** : scripts `setup*.sh` pour ROS 2 Humble et le chemin `~/unitree`.
- **unitree_sdk2_python** : exemple G1 bas niveau compatible MuJoCo.

## Installer sur un nouveau PC (Ubuntu 22.04)

```bash
git clone https://github.com/Toyer719/UnitreeG1edu_ESME.git ~/unitree
bash ~/unitree/scripts/apply_patches.sh      # clone Unitree + applique les patchs
bash ~/unitree/install_system.sh             # ROS 2 Humble, dépendances, unitree_sdk2 (sudo)
echo 'source ~/unitree/env.sh' >> ~/.bashrc
```
Puis compiler `cyclonedds` et le simulateur C++, et installer les SDK Python
(`pip install -e` de `unitree_sdk2_python` et `unitree_rl_gym`), comme décrit dans leurs README.

## Lancer la simulation avec la télécommande

```bash
# T1
cd ~/unitree/unitree_mujoco/simulate_python && python3 unitree_mujoco.py
# T2
python3 ~/unitree/virtual_remote/virtual_remote.py
# T3
cd ~/unitree/unitree_rl_gym/deploy/deploy_real
PYTHONPATH=$HOME/unitree/unitree_rl_gym python3 deploy_real.py lo g1_sim.yaml
```
Séquence : F5 → F2 (START) → j (A) → dans MuJoCo, 8 (environ 15 fois) puis 9 → flèches.
Détails : [`virtual_remote/LISEZMOI.txt`](virtual_remote/LISEZMOI.txt).

## Enregistrer et publier ses modifications

```bash
bash ~/unitree/scripts/export_patches.sh
cd ~/unitree && git add -A && git commit -m "description" && git push
```

## Atelier G1 : le logiciel du robot d'accueil (`atelier-g1/`)

Un seul logiciel, avec une interface web, pour préparer et faire tourner le robot d'accueil :

- **décrire un lieu** : scan du bâtiment avec le LiDAR du robot, carte 2D et **nuage de points 3D**
  où l'on place les salles et l'accueil à la souris, itinéraires, zones interdites ou lentes ;
- **essayer sans robot** : simulation Gazebo avec Nav2 et des passants, le robot va de salle en
  salle, contourne les gens, accompagne un visiteur et revient seul à l'accueil ;
- **le vrai robot** : notre navigation tourne dans un conteneur Docker sur le Jetson du G1, un
  pont transforme ses vitesses en ordres de marche Unitree (avec vitesse minimale, plafonds,
  arrêt automatique, verrou), repérage sur la carte, pilotage et danses ;
- **la démo d'accueil** : une **borne visiteur** (page web pour tablette ou téléphone : « Où
  voulez-vous aller ? »), le robot qui parle en français, la caméra de poitrine See3CAM et la
  détection des visiteurs ;
- **les séances avec le robot** : « Vérifier le robot » en un clic (câble, services, mode,
  batterie, Jetson) et une **boîte noire** qui enregistre tout et fait un rapport.

État au 12/11/2026 : 42 critères de recette sur 42 et 2 885 tests réussis, sans robot ; sur le
vrai G1, le scan, le pont et les seuils de vitesse sont validés (séances du 27/10 et du 10/11),
la navigation complète reste à essayer.

### Installer (Ubuntu 22.04)

Le logiciel attend d'être dans **`~/robot-g1`** : on crée un lien vers le dossier du dépôt.

```bash
git clone https://github.com/Toyer719/UnitreeG1edu_ESME.git ~/unitree   # si ce n'est pas déjà fait
ln -s ~/unitree/atelier-g1 ~/robot-g1
bash ~/robot-g1/setup/installer_pc.sh            # partie système (sudo) : ROS 2 Humble, Nav2, Gazebo Fortress, pilote NVIDIA…
bash ~/robot-g1/setup/installer_utilisateur.sh   # SDK Unitree, simulation, LiDAR, espace ROS 2, Python du projet, modèles
```

`installer_pc.sh` ajoute `source ~/robot-g1/setup/env.sh` à `~/.bashrc` (les commandes `g1-…`,
avec un tiret ; celles de `~/unitree/env.sh` ont un trait bas : `g1_…`, les deux se chargent
ensemble). Ouvrez un nouveau terminal après l'installation. Les dépôts Unitree, les environnements
Python et les modèles (YOLO, voix Piper…) sont téléchargés par ces scripts : ils ne sont pas dans Git.

### Démarrer

```bash
g1-atelier          # ouvre l'Atelier dans le navigateur (http://localhost:8000)
```

Sur l'écran d'accueil : **Simulation** et le lieu « Lycée démo » pour tout essayer sur
l'ordinateur ; **Robot réel** quand le PC est relié au robot par le câble Ethernet
(`source ~/robot-g1/setup/robot.sh` d'abord, dans chaque terminal).

### Documentation

| Document | Pour quoi |
|---|---|
| [`atelier-g1/README.md`](atelier-g1/README.md) | le guide complet : toutes les commandes, l'interface, la simulation, le vrai robot, le dépannage |
| [`atelier-g1/docs/word/`](atelier-g1/docs/word/) | **document complet du logiciel** (technologies, code, construction, 82 pages) et fiches Word de la séance robot n° 2 (à faire, à remplir) |
| [`atelier-g1/docs/tutoriel-seance-2.md`](atelier-g1/docs/tutoriel-seance-2.md) | le déroulé d'une séance avec le vrai robot, pas à pas, avec la sécurité |
| [`atelier-g1/docs/integration-equipe.md`](atelier-g1/docs/integration-equipe.md) | **pour brancher vos parties** (caméra, chatbot, voix, personnalités) : sujets ROS 2, formats, exemples |
| [`atelier-g1/docs/jetson.md`](atelier-g1/docs/jetson.md) | le conteneur de la navigation sur le Jetson du robot |
| [`atelier-g1/docs/plan-atelier-multi-agents.md`](atelier-g1/docs/plan-atelier-multi-agents.md), [`journal-atelier.md`](atelier-g1/docs/journal-atelier.md) | l'architecture, les contrats entre modules, l'historique et les décisions |

### Tester

```bash
cd ~/robot-g1 && .venv-projet/bin/python -m pytest -q atelier/tests   # tests de l'Atelier
tests_e2e/tout.sh                                                     # les 42 critères de recette (environ 2 h 30)
```

### Sécurité avec le vrai robot

- Toujours une personne avec **la télécommande officielle** : c'est l'arrêt d'urgence.
- Premiers essais **au portique**, à 0,2 m/s au plus (`G1_VITESSE_MAX=0.2 g1-atelier`).
- Le bouton **ARRÊT** de l'Atelier (ou Échap) arrête et bloque le robot ; après un arrêt ou un
  blocage, rien ne repart seul.
- Jamais de simulation sur le PC pendant que le robot est branché (même réseau ROS 2).

## Sécurité

- `g1_sim.yaml` et la télécommande virtuelle sont **réservés à la simulation**.
  Sur le vrai robot : `g1.yaml` et la vraie télécommande.
- Avant tout essai réel : robot suspendu au portique/harnais, sol plat.

## Crédits et licences

- Dépôts Unitree Robotics (BSD-3-Clause) : <https://github.com/unitreerobotics>. Les patchs
  modifient leur code et restent soumis à leur licence.
- Atelier G1 : Leaflet 1.9.4 (BSD-2-Clause) et three.js r160 (MIT) sont copiés dans
  `atelier-g1/atelier/web/vendor/`, avec leur mention de copyright d'origine ; ROS 2, Nav2 et Gazebo (Apache-2.0) ; YOLO
  d'Ultralytics (AGPL-3.0) et les voix Piper sont téléchargés par les scripts d'installation, pas
  copiés ici.
- Ergonomie de la télécommande inspirée du *Virtual Gamepad* d'EngineAI
  (`engineai_robotics_native_sdk/tools/virtual_gamepad`, GPL-3.0). Aucun code n'en a été copié.
