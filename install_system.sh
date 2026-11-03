#!/usr/bin/env bash
# Installation système (sudo) : ROS 2 Humble + dépendances Unitree SDK2 / MuJoCo.
# À lancer en tant qu'utilisateur normal :  bash ~/unitree/install_system.sh
set -euo pipefail

sudo apt update
sudo apt install -y software-properties-common curl locales
sudo locale-gen en_US en_US.UTF-8
sudo add-apt-repository -y universe

# --- Dépôt ROS 2 ---
ROS_APT_SOURCE_VERSION=$(curl -s https://api.github.com/repos/ros-infrastructure/ros-apt-source/releases/latest | grep -F "tag_name" | awk -F\" '{print $4}')
curl -L -o /tmp/ros2-apt-source.deb \
  "https://github.com/ros-infrastructure/ros-apt-source/releases/download/${ROS_APT_SOURCE_VERSION}/ros2-apt-source_${ROS_APT_SOURCE_VERSION}.$(. /etc/os-release && echo $VERSION_CODENAME)_all.deb"
sudo dpkg -i /tmp/ros2-apt-source.deb
sudo apt update

# --- ROS 2 Humble + outils ---
sudo apt install -y ros-humble-desktop ros-dev-tools python3-colcon-common-extensions \
  ros-humble-rmw-cyclonedds-cpp ros-humble-rosidl-generator-dds-idl

# --- Dépendances build Unitree SDK2 / unitree_mujoco ---
sudo apt install -y build-essential cmake g++ git python3-pip \
  libyaml-cpp-dev libeigen3-dev libboost-all-dev libfmt-dev libspdlog-dev libglfw3-dev

# --- unitree_sdk2 installé dans /opt/unitree_robotics ---
cd ~/unitree/unitree_sdk2
mkdir -p build && cd build
cmake .. -DCMAKE_INSTALL_PREFIX=/opt/unitree_robotics
make -j"$(nproc)"
sudo make install

echo "=== Installation système terminée ==="
