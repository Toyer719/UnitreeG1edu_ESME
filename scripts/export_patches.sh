#!/usr/bin/env bash
# LE PROJET — enregistre les modifications faites dans les dépôts Unitree clonés
# sous forme de patchs (patches/*.patch), à lancer AVANT chaque commit / push.
#   bash ~/unitree/scripts/export_patches.sh
# Ne modifie pas les dépôts clonés (index Git temporaire).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

REPOS=(unitree_rl_gym unitree_mujoco unitree_ros2 unitree_sdk2_python)
# fichiers à ne jamais mettre dans les patchs
EXCLUDES=(':(exclude)**/MUJOCO_LOG.TXT' ':(exclude)logs/**' ':(exclude)**/__pycache__/**' ':(exclude)**/*.pt')

: > patches/BASES.txt
echo "# dépôt | URL d'origine | commit de base (les patchs s'appliquent sur ce commit)" >> patches/BASES.txt
for r in "${REPOS[@]}"; do
  [ -d "$r/.git" ] || { echo "!! $r absent, ignoré"; continue; }
  url=$(git -C "$r" remote get-url upstream 2>/dev/null || git -C "$r" remote get-url origin)
  base=$(git -C "$r" rev-parse HEAD)
  echo "$r | $url | $base" >> patches/BASES.txt
  tmp_index=$(mktemp)
  GIT_INDEX_FILE="$tmp_index" git -C "$r" read-tree HEAD
  GIT_INDEX_FILE="$tmp_index" git -C "$r" add -A -- . "${EXCLUDES[@]}"
  GIT_INDEX_FILE="$tmp_index" git -C "$r" diff --cached --binary HEAD > "patches/$r.patch"
  rm -f "$tmp_index"
  n=$(grep -c '^diff --git' "patches/$r.patch" || true)
  if [ "$n" = "0" ]; then rm -f "patches/$r.patch"; echo "   $r : aucune modification"
  else echo "   $r : $n fichier(s) -> patches/$r.patch"; fi
done

# copies lisibles sur GitHub des guides qui vivent dans unitree_rl_gym
cp unitree_rl_gym/ENTRAINEMENT_ESCALIERS.md unitree_rl_gym/INSTRUCTIONS_PC_NVIDIA.txt docs/ 2>/dev/null || true
echo "OK. Ensuite :  cd ~/unitree && git add -A && git commit -m \"...\" && git push"
