#!/usr/bin/env bash
# Partie « utilisateur » de l'installation du poste (sans sudo). À lancer après installer_pc.sh.
#   bash ~/robot-g1/setup/installer_utilisateur.sh              tout installer
#   bash ~/robot-g1/setup/installer_utilisateur.sh livox ws     seulement certaines parties
# Parties : unitree simulation livox ws projet modeles
set -eo pipefail

R="$HOME/robot-g1"
TP="$R/third_party"
IP_PC_ROBOT=192.168.123.99
IP_LIDAR_G1=192.168.123.120   # adresse habituelle du MID-360 sur le G1, à vérifier sur le robot

etape() { echo; echo "==> $*"; }
cloner() {  # dépôt, dossier, [branche]
  [ -d "$2" ] || git clone -q --depth 1 ${3:+-b "$3"} --recurse-submodules "$1" "$2"
}
ros() { set +u; source /opt/ros/humble/setup.bash; export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp; }

unitree() {
  etape "SDK Unitree (C++, Python, messages ROS 2)"
  mkdir -p "$TP"
  for d in unitree_sdk2 unitree_sdk2_python unitree_ros2; do
    cloner "https://github.com/unitreerobotics/$d.git" "$TP/$d"
  done
  cmake -S "$TP/unitree_sdk2" -B "$TP/unitree_sdk2/build" -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX="$R/opt/unitree_robotics"
  cmake --build "$TP/unitree_sdk2/build" -j"$(nproc)"
  cmake --install "$TP/unitree_sdk2/build"
  python3 -m pip install --user "cyclonedds==0.10.2"
  python3 -m pip install --user --no-deps --no-build-isolation -e "$TP/unitree_sdk2_python"
  ros
  (cd "$TP/unitree_ros2/cyclonedds_ws" && colcon build)
  (cd "$TP/unitree_ros2/example" && source ../cyclonedds_ws/install/setup.bash && colcon build)
}

simulation() {
  etape "Simulation MuJoCo (environnement .venv-sim)"
  cloner https://github.com/unitreerobotics/unitree_mujoco.git "$TP/unitree_mujoco"
  cloner https://github.com/unitreerobotics/unitree_rl_gym.git "$TP/unitree_rl_gym"
  [ -d "$R/.venv-sim" ] || python3 -m venv "$R/.venv-sim"
  local pip="$R/.venv-sim/bin/pip"
  "$pip" install -q --upgrade pip
  "$pip" install -q torch --index-url https://download.pytorch.org/whl/cpu
  "$pip" install -q mujoco pygame pyyaml evdev "cyclonedds==0.10.2"
  "$pip" install -q --no-deps -e "$TP/unitree_sdk2_python"
}

livox() {
  etape "SDK Livox (LiDAR MID-360)"
  cloner https://github.com/Livox-SDK/Livox-SDK2.git "$TP/Livox-SDK2"
  cmake -S "$TP/Livox-SDK2" -B "$TP/Livox-SDK2/build" -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX="$R/opt/livox_sdk2"
  cmake --build "$TP/Livox-SDK2/build" -j"$(nproc)"
  cmake --install "$TP/Livox-SDK2/build"
}

ws() {
  etape "Espace de travail ROS 2 : pilote Livox, FAST-LIO2, g1_sim et g1_nav (Atelier G1)"
  mkdir -p "$R/ws/src"
  cloner https://github.com/Livox-SDK/livox_ros_driver2.git "$R/ws/src/livox_ros_driver2"
  cloner https://github.com/hku-mars/FAST_LIO.git "$R/ws/src/FAST_LIO" ROS2
  local drv="$R/ws/src/livox_ros_driver2"
  cp -f "$drv/package_ROS2.xml" "$drv/package.xml"
  rm -rf "$drv/launch" && cp -r "$drv/launch_ROS2" "$drv/launch"
  # Adresses du réseau du G1 : PC en 192.168.123.99, LiDAR du robot
  sed -i -E "s/\"(cmd_data|push_msg|point_data|imu_data)_ip\" *: *\"[0-9.]+\"/\"\1_ip\" : \"$IP_PC_ROBOT\"/; \
             s/\"ip\" *: *\"192\.168\.1\.[0-9]+\"/\"ip\" : \"$IP_LIDAR_G1\"/" "$drv/config/MID360_config.json"
  ros
  export CMAKE_PREFIX_PATH="$R/opt/livox_sdk2:$CMAKE_PREFIX_PATH"
  local selection=()
  if [ ! -d /opt/ros/humble/share/pcl_ros ]; then
    echo "pcl_ros absent : FAST-LIO2 sera compilé après installer_pc.sh. Pilote Livox seul pour l'instant."
    selection=(--packages-select livox_ros_driver2)
  fi
  (cd "$R/ws" && colcon build --symlink-install "${selection[@]}" --cmake-args -DROS_EDITION=ROS2 \
    -DDISTRO_ROS=humble -DCMAKE_BUILD_TYPE=Release)
}

projet() {
  etape "Environnement Python du projet (.venv-projet) : vision, voix, carte, web"
  # --system-site-packages : garde l'accès à rclpy et aux paquets ROS 2
  [ -d "$R/.venv-projet" ] || python3 -m venv --system-site-packages "$R/.venv-projet"
  local pip="$R/.venv-projet/bin/pip"
  # numpy < 2 : les paquets Python de ROS 2 Humble ne fonctionnent pas avec numpy 2
  echo "numpy<2" > "$R/.venv-projet/contraintes.txt"
  export PIP_CONSTRAINT="$R/.venv-projet/contraintes.txt"
  "$pip" install -q --upgrade pip
  "$pip" install -q torch torchvision --index-url https://download.pytorch.org/whl/cu126
  "$pip" install -q ultralytics open3d faster-whisper vosk piper-tts rapidfuzz sounddevice soundfile \
    fastapi "uvicorn[standard]" python-multipart pyyaml
  # Atelier G1 : outils de test (pytest 7 : le 6 du système plante avec anyio ; httpx pour le
  # TestClient de FastAPI ; esprima pour vérifier le JavaScript ; jsonschema pour les schémas)
  "$pip" install -q "pytest==7.4.4" httpx esprima jsonschema
  # Paquet Python « atelier » en mode éditable, pour .venv-projet et pour le python3 des nœuds ROS 2
  "$pip" install -q -e "$R"
  python3 -m pip install --user --no-deps --no-build-isolation -e "$R"
}

modeles() {
  etape "Modèles : YOLO, Vosk français, voix Piper, Whisper"
  local m="$R/modeles" py="$R/.venv-projet/bin/python"
  mkdir -p "$m/yolo" "$m/vosk" "$m/piper" "$m/whisper"
  (cd "$m/yolo" && "$py" -c "from ultralytics import YOLO; [YOLO(n) for n in ('yolo11n.pt', 'yolo11n-pose.pt')]")
  if [ ! -d "$m/vosk/vosk-model-small-fr-0.22" ]; then
    wget -q -O /tmp/vosk-fr.zip https://alphacephei.com/vosk/models/vosk-model-small-fr-0.22.zip
    "$py" -c "import zipfile; zipfile.ZipFile('/tmp/vosk-fr.zip').extractall('$m/vosk')"
    rm -f /tmp/vosk-fr.zip
  fi
  for voix in fr_FR-siwis-medium fr_FR-tom-medium; do
    [ -f "$m/piper/$voix.onnx" ] || "$py" -m piper.download_voices --download-dir "$m/piper" "$voix"
  done
  HF_HOME="$m/whisper" "$py" -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu')"
}

parties=("$@")
[ ${#parties[@]} -eq 0 ] && parties=(unitree simulation livox ws projet modeles)
for p in "${parties[@]}"; do
  "$p"
done
echo
echo "Installation utilisateur terminée : ${parties[*]}"
