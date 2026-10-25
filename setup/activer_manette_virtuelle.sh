#!/usr/bin/env bash
# Autorise la session de l'utilisateur connecté à créer des manettes virtuelles (/dev/uinput).
# Même règle que celle installée par Steam pour ses manettes.
#   sudo bash ~/robot-g1/setup/activer_manette_virtuelle.sh
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Lancez ce script avec sudo : sudo bash $0" >&2
  exit 1
fi

cat > /etc/udev/rules.d/60-uinput-manette-virtuelle.rules <<'EOF'
# Manette virtuelle du projet robot d'accueil G1 (~/robot-g1/outils/manette_virtuelle.py)
KERNEL=="uinput", SUBSYSTEM=="misc", TAG+="uaccess", OPTIONS+="static_node=uinput"
EOF
udevadm control --reload-rules
udevadm trigger --sysname-match=uinput
echo "Manette virtuelle activée. Lancez : g1-manette-virtuelle"
