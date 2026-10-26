# g1_equipe

Emplacements de l'équipe (vague 4, section 11.6 du plan) : un chatbot à règles d'**exemple**, le
relais des événements du guide vers la voix, et deux bouchons pour essayer sans la caméra ni la
voix de l'équipe. Guide pour les coéquipiers : `docs/integration-equipe.md`.

| Exécutable | Rôle | Sujets |
|---|---|---|
| `dialogue` | applique `dialogues.yaml` du lieu (ou les règles d'exemple) à ce que dit le visiteur ; relaie les événements du guide avec les phrases de la personnalité active ; salue un visiteur vu par la caméra | écoute `/visiteur/texte`, `/guide/evenement`, `/guide/etat`, `/visiteurs/detectes`, `/personnalite/active`, `/mouvement/maitre` ; publie `/robot/dire`, `/guide/aller` (JSON), `/guide/stop`, `/personnalite/active` |
| `fausse_camera` | bouchon de la See3CAM : une personne fixe, personne, ou les piétons de Gazebo dans le champ de `camera.yaml` | publie `/visiteurs/detectes` ; écoute `/fausse_camera/mode`, `/pietons/etat`, `/odom` |
| `voix_journal` | bouchon de la voix : écrit chaque phrase de `/robot/dire` dans le journal, et la dit avec une commande (ex. `g1-parler`) | écoute `/robot/dire`, `/personnalite/active` |

```bash
ros2 run g1_equipe dialogue --ros-args -p lieu:=demo -p etage:=rdc
ros2 run g1_equipe fausse_camera --ros-args -p lieu:=demo [-p mode:=pietons]
ros2 run g1_equipe voix_journal [--ros-args -p commande:=g1-parler]
```

Sécurité : aucun de ces nœuds ne commande un moteur. Le chatbot demande au guide (`/guide/aller`),
qui décide et conduit ; il ne le demande pas quand le robot est piloté à la main
(`/mouvement/maitre` : `pilotage`) ni pendant une visite ; l'arrêt (`/guide/stop`) est toujours
envoyé. La logique sans ROS est dans `atelier/equipe/` (chatbot, relais, caméra) et
`atelier/lieu/equipe.py` (fichiers et messages).

Compilation et tests, sans jamais toucher à `ws/build` pendant le travail en parallèle :

```bash
cd ~/robot-g1/ws && colcon --log-base log_g1_equipe build --symlink-install --packages-select g1_equipe \
    --build-base build_g1_equipe --install-base install_g1_equipe
source install_g1_equipe/local_setup.bash
colcon --log-base log_g1_equipe test --packages-select g1_equipe --build-base build_g1_equipe \
    --install-base install_g1_equipe && colcon test-result --test-result-base build_g1_equipe --all
```

Les tests (`test/test_noeuds.py`, environ 30 s) lancent les trois nœuds et jouent le guide, la
reconnaissance vocale, la caméra et le pilotage ; domaine `$ROS_DOMAIN_ID` (75 par défaut),
`ROS_LOCALHOST_ONLY=1`.

Dans le conteneur du Jetson : pas encore. L'image ne copie que `atelier/lieu/` ; il faudra y
ajouter `atelier/equipe/` et ce paquet (agent Pilotage, propriétaire de `docker/` en vague 4).
