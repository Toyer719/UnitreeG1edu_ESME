#!/usr/bin/env bash
# Installation dans le dossier du dépôt, sans sudo ni modification du robot.
set -euo pipefail
unset PYTHONPATH PYTHONHOME
ici="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
mode="${1:-cpu}"
case "$mode" in
  cpu) index=https://download.pytorch.org/whl/cpu ;;
  cuda) index=https://download.pytorch.org/whl/cu126 ;;
  *) echo 'Usage : bash installer.sh [cpu|cuda]' >&2; exit 2 ;;
esac
python_bin="${PYTHON_BIN:-python3}"
"$python_bin" -c 'import sys; assert (3,10) <= sys.version_info < (3,14), "Utiliser Python 3.10 à 3.13"'
"$python_bin" -m venv "$ici/.venv"
py="$ici/.venv/bin/python"
"$py" -m pip install --upgrade pip
torch_options=()
if [ -f "$ici/.venv/.suivi-torch-mode" ] && [ "$(cat "$ici/.venv/.suivi-torch-mode")" != "$mode" ]; then
  torch_options+=(--force-reinstall)
fi
"$py" -m pip install "${torch_options[@]}" torch torchvision --index-url "$index"
printf '%s\n' "$mode" > "$ici/.venv/.suivi-torch-mode"
"$py" -m pip install -e "$ici"
"$py" -m suivi_personne.modeles
echo 'Installation terminée. Lancer : bash lancer.sh --source 0'
echo 'Pour une fenêtre sur Ubuntu/Debian, python3-tk doit être installé.'
