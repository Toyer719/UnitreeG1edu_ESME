#!/usr/bin/env bash
# Partie système de l'installation du poste (à lancer en root, sans interaction).
#   sudo bash ~/robot-g1/setup/installer_pc_root.sh
set -euo pipefail

ROS_APT_SOURCE_VERSION=1.3.0
export DEBIAN_FRONTEND=noninteractive
APT_OPTS=(-y -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold)

etape() { echo; echo "==> $*"; }

if [ "$(id -u)" -ne 0 ]; then
  echo "Ce script doit être lancé en root." >&2
  exit 1
fi
if [ "$(lsb_release -cs)" != "jammy" ]; then
  echo "Ce script est prévu pour Ubuntu 22.04 (jammy)." >&2
  exit 1
fi

etape "1/5 Nettoyage après la mise à niveau"
apt-get update
apt-get full-upgrade "${APT_OPTS[@]}"
apt-get autoremove --purge "${APT_OPTS[@]}"

etape "2/5 Pilote NVIDIA"
ubuntu-drivers install

etape "3/5 Dépôt ROS 2"
apt-get install "${APT_OPTS[@]}" software-properties-common
add-apt-repository -y universe
wget -q -O /tmp/ros2-apt-source.deb \
  "https://github.com/ros-infrastructure/ros-apt-source/releases/download/${ROS_APT_SOURCE_VERSION}/ros2-apt-source_${ROS_APT_SOURCE_VERSION}.jammy_all.deb"
dpkg -i /tmp/ros2-apt-source.deb
apt-get update

etape "4/5 ROS 2 Humble, Nav2, Gazebo Fortress et outils"
apt-get install "${APT_OPTS[@]}" \
  ros-humble-desktop ros-dev-tools \
  ros-humble-rmw-cyclonedds-cpp ros-humble-rosidl-generator-dds-idl \
  ros-humble-navigation2 ros-humble-nav2-bringup \
  ros-humble-ros-gz \
  git curl build-essential cmake libyaml-cpp-dev libeigen3-dev python3-pip python3-venv

[ -f /etc/ros/rosdep/sources.list.d/20-default.list ] || rosdep init

etape "5/5 Capteurs, cartographie, audio, Docker"
apt-get install "${APT_OPTS[@]}" \
  ros-humble-pcl-ros ros-humble-pointcloud-to-laserscan ros-humble-rtabmap-ros \
  ros-humble-librealsense2 ros-humble-realsense2-camera \
  ros-humble-rosbridge-suite ros-humble-joint-state-publisher-gui \
  libportaudio2 portaudio19-dev ffmpeg alsa-utils \
  joystick v4l-utils net-tools \
  docker.io qemu-user-static binfmt-support

# Caméras RealSense utilisables sans être root
if [ ! -f /etc/udev/rules.d/99-realsense-libusb.rules ]; then
  wget -q -O /etc/udev/rules.d/99-realsense-libusb.rules \
    https://raw.githubusercontent.com/IntelRealSense/librealsense/master/config/99-realsense-libusb.rules \
    && udevadm control --reload-rules && udevadm trigger \
    || echo "Règles RealSense non installées (pas d'accès à GitHub) : à refaire plus tard."
fi

# Manette virtuelle (g1-manette-virtuelle) : accès à /dev/uinput pour la session ouverte
cat > /etc/udev/rules.d/60-uinput-manette-virtuelle.rules <<'EOF'
KERNEL=="uinput", SUBSYSTEM=="misc", TAG+="uaccess", OPTIONS+="static_node=uinput"
EOF
udevadm control --reload-rules && udevadm trigger --sysname-match=uinput

# Docker utilisable sans sudo (prend effet après une déconnexion / reconnexion)
if [ -n "${SUDO_USER:-}" ]; then
  usermod -aG docker "$SUDO_USER"
fi

echo
echo "Partie système terminée."
