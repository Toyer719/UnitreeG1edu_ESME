# Conteneur ROS 2 Humble du Jetson du G1 (section 10.2 du plan) : Nav2, guide, relais et pont.
#
# Un seul fichier pour les deux architectures :
#   amd64 : essais sur le PC (critère 16), « g1-jetson construire --arch amd64 » ;
#   arm64 : le Jetson du robot (L4T R35.3.1, Docker 24), construit sur le PC par émulation qemu,
#           « g1-jetson construire » (docker build --platform linux/arm64, sans buildx).
#
# Le contexte de construction n'est jamais le dépôt entier (.venv-projet pèse plusieurs Go) :
# « g1-jetson construire » (docker/jetson.py) l'assemble dans un dossier temporaire :
#   Dockerfile            ce fichier
#   docker/               demarrer.sh, env.sh, reseau.py, presence.py, cyclonedds.xml.modele
#   unitree_api/          messages Unitree (third_party/unitree_ros2/.../unitree/unitree_api)
#   unitree_hg/           messages du G1 (rt/arm_sdk, /lowstate), pour le nœud pilotage (vague 4)
#   python/atelier/       atelier/__init__.py, atelier/lieu/, atelier/scan/{__init__,slam_client}.py, atelier/equipe/
#   ws/g1_nav/, ws/g1_bridge/, ws/g1_pilotage/, ws/g1_equipe/   copiés de ws/src au moment de la construction
#   VERSION               date de construction, commit Git, empreinte du contexte
#
# Les couches vont de la plus stable à la plus changeante. Une modification de g1_nav ou de
# g1_bridge ne refait que les trois dernières couches : moins d'une minute sur le PC, quelques
# minutes sous émulation. Les paquets apt et unitree_api (le plus long) restent en cache.

# BASE : « g1-jetson construire » donne l'image de l'architecture voulue par son empreinte
# (ros:humble-ros-base-jammy@sha256:…). Avec le magasin d'images containerd de Docker 29, le nom
# seul désigne les deux architectures à la fois, et le constructeur classique prenait celle du PC.
ARG BASE=ros:humble-ros-base-jammy
FROM ${BASE}

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV DEBIAN_FRONTEND=noninteractive

# 1. Paquets du système : CycloneDDS, Nav2 (avec AMCL et le commandant simple), nuage → balayage.
#    Nav2 : tous les composants du méta-paquet ros-humble-navigation2, sauf nav2_rviz_plugins
#    (RViz et Qt) et nav2_waypoint_follower (OpenCV) : rien de graphique sur le robot, et une image
#    deux fois plus petite (copie au câble, place sur le Jetson, construction sous émulation).
#    rosidl_generator_dds_idl est demandé par le CMakeLists.txt de unitree_api.
#    Ni Gazebo, ni ros_gz, ni RViz.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ros-humble-rmw-cyclonedds-cpp \
      ros-humble-nav2-amcl ros-humble-nav2-behavior-tree ros-humble-nav2-behaviors \
      ros-humble-nav2-bt-navigator ros-humble-nav2-collision-monitor \
      ros-humble-nav2-constrained-smoother ros-humble-nav2-controller ros-humble-nav2-core \
      ros-humble-nav2-costmap-2d ros-humble-nav2-dwb-controller ros-humble-nav2-lifecycle-manager \
      ros-humble-nav2-map-server ros-humble-nav2-mppi-controller ros-humble-nav2-msgs \
      ros-humble-nav2-navfn-planner ros-humble-nav2-planner \
      ros-humble-nav2-regulated-pure-pursuit-controller ros-humble-nav2-rotation-shim-controller \
      ros-humble-nav2-simple-commander ros-humble-nav2-smac-planner ros-humble-nav2-smoother \
      ros-humble-nav2-theta-star-planner ros-humble-nav2-util ros-humble-nav2-velocity-smoother \
      ros-humble-nav2-voxel-grid \
      ros-humble-pointcloud-to-laserscan \
      ros-humble-rosidl-generator-dds-idl \
      python3-numpy python3-yaml iproute2 \
 && rm -rf /var/lib/apt/lists/*

# 2. Messages Unitree : unitree_api (unitree_go ne sert pas ici et rallongerait beaucoup la
#    construction sous émulation ; unitree_hg vient dans la couche suivante, pour garder celle-ci).
COPY unitree_api /opt/g1/src/unitree_api
RUN source /opt/ros/humble/setup.bash \
 && cd /opt/g1 \
 && colcon --log-base /tmp/colcon_log build --base-paths src/unitree_api \
      --build-base /tmp/g1_build --install-base /opt/g1/install \
      --cmake-args -DBUILD_TESTING=OFF -DCMAKE_BUILD_TYPE=Release \
 && rm -rf /tmp/g1_build /tmp/colcon_log

# 2b. Messages du G1 (vague 4, section 11.5 du plan) : unitree_hg, pour rt/arm_sdk et /lowstate
#     (chorégraphies du nœud pilotage)
COPY unitree_hg /opt/g1/src/unitree_hg
RUN source /opt/ros/humble/setup.bash \
 && source /opt/g1/install/local_setup.bash \
 && cd /opt/g1 \
 && colcon --log-base /tmp/colcon_log build --base-paths src/unitree_hg \
      --build-base /tmp/g1_build --install-base /opt/g1/install \
      --cmake-args -DBUILD_TESTING=OFF -DCMAKE_BUILD_TYPE=Release \
 && rm -rf /tmp/g1_build /tmp/colcon_log

# 2c. API HTTP et WebSocket du nœud pilotage (vague 4) : tornado, paquet du système
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3-tornado \
 && rm -rf /var/lib/apt/lists/*

# 2d. Caméra de poitrine (vague 5, section 12.7 du plan) : v4l2-ctl (capture YUYV de la See3CAM) et
#     Pillow (JPEG), couche de 9 Mo (mesurée sur amd64) ; numpy est déjà dans la couche 1. Pas d'OpenCV
#     (580 Mo).
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3-pil v4l-utils \
 && rm -rf /var/lib/apt/lists/*

# 3. Scripts du conteneur
COPY docker/demarrer.sh docker/env.sh docker/reseau.py docker/presence.py docker/cyclonedds.xml.modele /opt/g1/
RUN chmod 755 /opt/g1/demarrer.sh /opt/g1/reseau.py /opt/g1/presence.py \
 && mkdir -p /journaux /lieux \
 && chmod 1777 /journaux

# 4. Python de l'Atelier : atelier.lieu (numpy et PyYAML seulement) et le client slam_operate
#    (le SDK Unitree n'est importé qu'à l'appel : le conteneur s'en passe).
#    atelier.dossier_journaux() vise /opt/g1/python/journaux : c'est le dossier monté.
COPY python /opt/g1/python
RUN ln -s /journaux /opt/g1/python/journaux \
 && python3 -c "import sys; sys.path.insert(0, '/opt/g1/python'); import atelier.lieu, atelier.scan.slam_client, atelier.equipe.dialogue, atelier.equipe.relais, atelier.equipe.camera, atelier.equipe.images"

# 5. Paquets du projet, copiés de ws/src au moment de la construction : g1_nav, g1_bridge, g1_pilotage,
#    g1_equipe (nœuds dialogue, fausse_camera et voix_journal de l'équipe, non lancés d'office ;
#    vague 5 : camera_usb, lancé par demarrer.sh quand G1_CAMERA est donné)
COPY ws /opt/g1/src/ws
RUN source /opt/ros/humble/setup.bash \
 && source /opt/g1/install/local_setup.bash \
 && cd /opt/g1 \
 && colcon --log-base /tmp/colcon_log build --base-paths src/ws \
      --build-base /tmp/g1_build --install-base /opt/g1/install \
 && rm -rf /tmp/g1_build /tmp/colcon_log

# Réglages fixes de l'image, et défauts des variables du lancement (tableau de la section 10.2)
ENV RMW_IMPLEMENTATION=rmw_cyclonedds_cpp \
    ATELIER_LIEUX=/lieux \
    ROS_HOME=/journaux/ros \
    ROS_LOG_DIR=/journaux/ros/log \
    PYTHONPATH=/opt/g1/python \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/tmp \
    ROS_DOMAIN_ID=0 \
    G1_INTERFACES=auto \
    G1_LANCEMENT=navigation \
    G1_LOCALISATION=unitree \
    G1_SIMU=false \
    G1_PILOTAGE=0 \
    G1_PILOTAGE_PORT=8010

# 6. Version : date de construction, commit Git et empreinte du contexte (toujours la dernière couche)
ARG G1_EMPREINTE=inconnue
LABEL fr.robot-g1.image="g1-jetson" \
      fr.robot-g1.empreinte="${G1_EMPREINTE}"
COPY VERSION /opt/g1/VERSION

ENTRYPOINT ["/opt/g1/demarrer.sh"]
CMD []
