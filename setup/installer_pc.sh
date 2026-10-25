#!/usr/bin/env bash
# Installe le poste de développement du projet robot d'accueil G1 (Ubuntu 22.04).
# À lancer dans un terminal :  bash ~/robot-g1/setup/installer_pc.sh
set -euo pipefail

sudo bash "$(dirname "$0")/installer_pc_root.sh"

echo; echo "==> Configuration de votre compte"
rosdep update

if ! grep -q "robot-g1/setup/env.sh" ~/.bashrc; then
  cat >> ~/.bashrc <<'EOF'

# Projet robot d'accueil G1 : ROS 2 Humble, SDK Unitree
source ~/robot-g1/setup/env.sh
EOF
fi

echo
echo "Installation terminée. Redémarrez le PC pour activer le pilote NVIDIA : sudo reboot"
