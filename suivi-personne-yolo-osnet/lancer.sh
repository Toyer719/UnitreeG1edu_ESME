#!/usr/bin/env bash
set -euo pipefail
unset PYTHONPATH PYTHONHOME
ici="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [ ! -x "$ici/.venv/bin/python" ]; then
  echo 'Environnement absent. Lancer : bash installer.sh cpu (ou cuda).' >&2
  exit 1
fi
exec "$ici/.venv/bin/python" -m suivi_personne "$@"
