# g1_equipe

Emplacements de l'équipe (vague 4, section 11.6 du plan) : un chatbot à règles d'**exemple**, le
relais des événements du guide vers la voix, et deux bouchons pour essayer sans la caméra ni la
voix de l'équipe ; vague 5 (section 12.7) : le nœud de la **caméra de poitrine** See3CAM. Guide
pour les coéquipiers : `docs/integration-equipe.md`.

| Exécutable | Rôle | Sujets |
|---|---|---|
| `dialogue` | applique `dialogues.yaml` du lieu (ou les règles d'exemple) à ce que dit le visiteur ; relaie les événements du guide avec les phrases de la personnalité active ; salue un visiteur vu par la caméra | écoute `/visiteur/texte`, `/guide/evenement`, `/guide/etat`, `/visiteurs/detectes`, `/personnalite/active`, `/mouvement/maitre` ; publie `/robot/dire`, `/guide/aller` (JSON), `/guide/stop`, `/personnalite/active`, `/robot/geste` (règle « geste », `geste_salut` de la personnalité quand il salue) |
| `fausse_camera` | bouchon de la See3CAM : une personne fixe, personne, ou les piétons de Gazebo dans le champ de `camera.yaml` | publie `/visiteurs/detectes` ; écoute `/fausse_camera/mode`, `/pietons/etat`, `/odom` |
| `voix_journal` | bouchon de la voix : écrit chaque phrase de `/robot/dire` dans le journal, et la dit avec une commande (ex. `g1-parler`) | écoute `/robot/dire`, `/personnalite/active` |
| `camera_usb` (nœud `camera_poitrine`) | la See3CAM : capture par `v4l2-ctl` (YUYV 1280 × 720 à 30 i/s), exposition automatique au démarrage, JPEG par Pillow ; ou une image de test (`source:=mire`), ou un fichier (`source:=fichier`, `fichier:=` YUYV brut, v4l2-ctl --stream-to-hdr, photo ou vidéo) | publie `/camera_poitrine/image/compressed` (sensor_msgs/CompressedImage, 10 Hz, 640 px, qualité 70) et `/camera_poitrine/etat` (JSON, 1 Hz) |

```bash
ros2 run g1_equipe dialogue --ros-args -p lieu:=demo -p etage:=rdc
ros2 run g1_equipe fausse_camera --ros-args -p lieu:=demo [-p mode:=pietons]
ros2 run g1_equipe voix_journal [--ros-args -p commande:=g1-parler]
ros2 run g1_equipe camera_usb [--ros-args -p lieu:=demo] [-p peripherique:=/dev/v4l/by-id/…] [-p source:=mire]
```

Paramètres de `camera_usb` (0 ou vide : `camera.yaml` du lieu, sinon le défaut) : `source`, `peripherique`
(défaut : `camera.yaml`, sinon `/dev/g1_camera` dans le conteneur, sinon la première See3CAM branchée),
`lieu`, `largeur`, `hauteur`, `ips`, `frequence_hz`, `largeur_publiee`, `qualite_jpeg`, `exposition`
(`auto` ou `manuelle`), `exposition_100us`, `gain`, `fichier`. Caméra absente, débranchée ou occupée :
nouvel essai toutes les 2 s, « erreur » en français dans l'état. La logique sans ROS est dans
`g1_equipe/image_jpeg.py` (YUYV → JPEG, mire, cadence, lecture du flux de v4l2-ctl, exposition) et
`g1_equipe/peripherique.py` ; la détection des visiteurs sur le PC, dans `outils/visiteurs.py`
(`g1-visiteurs`).

Sécurité : aucun de ces nœuds ne commande un moteur. Le chatbot demande au guide (`/guide/aller`),
qui décide et conduit ; il ne le demande pas quand le robot est piloté à la main
(`/mouvement/maitre` : `pilotage`) ni pendant une visite ; l'arrêt (`/guide/stop`) est toujours
envoyé. Les gestes (`/robot/geste`) et la LED de la personnalité sont faits par le nœud pilotage,
qui ne fait un geste que robot au repos. La logique sans ROS est dans `atelier/equipe/` (chatbot, relais, caméra) et
`atelier/lieu/equipe.py` (fichiers et messages).

Compilation et tests (avec les autres paquets, dans `ws/install`) :

```bash
cd ~/robot-g1/ws && colcon build --symlink-install --packages-select g1_equipe
colcon test --packages-select g1_equipe && colcon test-result --all
```

Les tests (`test/test_noeuds.py`, environ 30 s) lancent les trois nœuds et jouent le guide, la
reconnaissance vocale, la caméra et le pilotage ; `test/test_image_jpeg.py` (sans ROS) et
`test/test_camera_usb.py` (environ 20 s : mire, fichiers, faux `v4l2-ctl` en tête du PATH,
caméra débranchée, occupée, absente, exposition refusée ; avec `G1_TEST_CAMERA=/dev/v4l/by-id/…`,
la vraie caméra, et `G1_TEST_CAMERA_IPS=8` si ce n'est pas une See3CAM en USB 3)
pour `camera_usb` ; domaine `$ROS_DOMAIN_ID` (75 par défaut), `ROS_LOCALHOST_ONLY=1`.

Dans le conteneur du Jetson : le paquet et `atelier/equipe/` sont dans l'image (assemblage de la
vague 4) ; `camera_usb` y est lancé par `docker/demarrer.sh` quand la See3CAM est passée au
conteneur (`docs/jetson.md`, « La caméra de poitrine ») ; les autres nœuds ne sont pas lancés
d'office.
