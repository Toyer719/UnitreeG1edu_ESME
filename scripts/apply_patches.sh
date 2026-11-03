#!/usr/bin/env bash
# LE PROJET — reconstruit l'installation sur un autre PC :
# clone les dépôts Unitree au commit de base puis applique nos patchs.
#   git clone https://github.com/Toyer719/UnitreeG1edu_ESME.git ~/unitree
#   bash ~/unitree/scripts/apply_patches.sh
# (le dossier DOIT être ~/unitree : les chemins des scripts en dépendent)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

grep -v '^#' patches/BASES.txt | while IFS='|' read -r repo url base; do
  repo=$(echo "$repo" | xargs); url=$(echo "$url" | xargs); base=$(echo "$base" | xargs)
  [ -n "$repo" ] || continue
  if [ ! -d "$repo/.git" ]; then
    echo "== clonage de $repo"
    git clone "$url" "$repo"
    git -C "$repo" remote rename origin upstream
  fi
  if [ -f "patches/$repo.patch" ]; then
    if git -C "$repo" apply --check --binary "$ROOT/patches/$repo.patch" 2>/dev/null; then
      git -C "$repo" checkout -q "$base" 2>/dev/null || true
      git -C "$repo" apply --binary "$ROOT/patches/$repo.patch"
      echo "   $repo : patch appliqué (base $base)"
    elif git -C "$repo" apply --check --reverse --binary "$ROOT/patches/$repo.patch" 2>/dev/null; then
      echo "   $repo : patch déjà appliqué"
    else
      echo "!! $repo : le patch ne s'applique pas (modifications locales ?). Vérifier à la main :"
      echo "   cd $ROOT/$repo && git checkout $base && git apply --binary ../patches/$repo.patch"
    fi
  fi
done

echo
echo "Étapes suivantes : installation système (bash ~/unitree/install_system.sh),"
echo "compilation de cyclonedds / unitree_mujoco, pip install -e des SDK : voir README.md"
