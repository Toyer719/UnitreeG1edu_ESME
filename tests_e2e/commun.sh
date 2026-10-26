# Fonctions communes aux tests de bout en bout (à charger avec « source », pas à lancer).
#
# Chaque critere_NN_*.sh charge ce fichier, puis :
#   - travaille dans un dossier temporaire ($TRAVAIL), avec ses propres lieux ($ATELIER_LIEUX) ;
#   - lance ses processus avec lancer_fond, qui les range dans un groupe à part ;
#   - finit par reussi, echoue "raison" ou en_attente "raison".
# À la sortie (même sur Ctrl+C), tous les processus lancés sont arrêtés et le dossier effacé.
#
# Codes de sortie : 0 réussi, 1 échoué, 77 pas encore possible (un module manque).
# Isolement : ROS_DOMAIN_ID=36 et IGN_PARTITION=atelier_e2e par défaut (E2E_DOMAINE, E2E_PARTITION) ;
# le faux service du robot est sur lo.
# Pas de set -u : les scripts de ROS 2 ne le supportent pas.

E2E="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RACINE="$(cd "$E2E/.." && pwd)"
source "$HOME/robot-g1/setup/env.sh"
# Paquets ROS du projet : dans ws/install (chargé par env.sh) ; à défaut, compilés à part dans
# ws/install_<paquet> (copie de travail d'un agent)
for _paquet in g1_sim g1_nav g1_bridge g1_jumeau; do
  if [ ! -d "$RACINE/ws/install/$_paquet" ] && [ -f "$RACINE/ws/install_$_paquet/local_setup.bash" ]; then
    source "$RACINE/ws/install_$_paquet/local_setup.bash"
  fi
done
export PATH="$RACINE/bin:$PATH"
export PYTHONPATH="$RACINE:$RACINE/ws/src/g1_nav${PYTHONPATH:+:$PYTHONPATH}"
# Domaine et partition propres aux tests (modifiables : E2E_DOMAINE=30 E2E_PARTITION=... tout.sh)
export ROS_DOMAIN_ID="${E2E_DOMAINE:-36}"
export IGN_PARTITION="${E2E_PARTITION:-atelier_e2e}"
# Pas de ROS_LOCALHOST_ONLY=1 : sur lo, CycloneDDS n'a pas de multicast et ne trouve plus de
# numéro de participant libre au-delà d'une dizaine de nœuds (Nav2 en lance plus).
export ROS_LOCALHOST_ONLY=0
export G1_SLAM_FAUX=1                 # jamais le vrai robot dans ces tests
unset DISPLAY WAYLAND_DISPLAY         # aucune fenêtre
export BROWSER=true                   # g1-atelier n'ouvre pas de navigateur
PY="$RACINE/.venv-projet/bin/python"
OUTILS="$E2E/outils_e2e.py"

NOM_TEST="$(basename "$0" .sh)"
TRAVAIL="$(mktemp -d "${TMPDIR:-/tmp}/atelier_e2e_${NOM_TEST}_XXXX")"
export ATELIER_LIEUX="$TRAVAIL/lieux"
mkdir -p "$ATELIER_LIEUX" "$TRAVAIL/journaux"
GROUPES=()
DEBUT_TEST=$(date +%s)

dire() { echo "[$NOM_TEST] $*"; }

# lancer_fond NOM COMMANDE... : lance en arrière-plan, dans un nouveau groupe de processus,
# sortie dans $TRAVAIL/journaux/NOM.log. Le numéro du processus est dans $DERNIER.
lancer_fond() {
  local nom="$1"; shift
  setsid "$@" > "$TRAVAIL/journaux/$nom.log" 2>&1 < /dev/null &
  DERNIER=$!
  GROUPES+=("$DERNIER")
  dire "lancé : $nom (groupe $DERNIER)"
}

# arreter_groupe PID : SIGINT, puis SIGTERM, puis SIGKILL au groupe entier
arreter_groupe() {
  local pid="$1" signal
  for signal in INT TERM KILL; do
    kill -0 -- "-$pid" 2>/dev/null || return 0
    kill -s "$signal" -- "-$pid" 2>/dev/null
    for _ in $(seq 1 50); do
      kill -0 -- "-$pid" 2>/dev/null || return 0
      sleep 0.1
    done
  done
}

nettoyer() {
  local code=$?
  trap - EXIT INT TERM
  local i
  for (( i=${#GROUPES[@]}-1; i>=0; i-- )); do
    arreter_groupe "${GROUPES[$i]}"
  done
  # Restes éventuels de Gazebo lancés dans cette partition (ne touche pas aux autres agents)
  local restes
  restes=$(pgrep -f "ign gazebo" 2>/dev/null | while read -r p; do
    tr '\0' '\n' < "/proc/$p/environ" 2>/dev/null | grep -qx "IGN_PARTITION=$IGN_PARTITION" && echo "$p"
  done)
  [ -n "$restes" ] && kill -9 $restes 2>/dev/null
  if [ -n "$GARDER_TRAVAIL" ]; then
    dire "dossier de travail gardé : $TRAVAIL"
  else
    rm -rf "$TRAVAIL"
  fi
  exit "$code"
}
trap nettoyer EXIT
trap 'exit 130' INT TERM

reussi() { dire "RÉUSSI ($(( $(date +%s) - DEBUT_TEST )) s)${1:+ : $1}"; exit 0; }
echoue() {
  dire "ÉCHOUÉ : $*"
  if [ -n "$(ls "$TRAVAIL/journaux" 2>/dev/null)" ]; then
    dire "fin des journaux :"
    for f in "$TRAVAIL"/journaux/*.log; do
      echo "--- $(basename "$f")"; tail -n 15 "$f"
    done
  fi
  exit 1
}
en_attente() { dire "PAS ENCORE POSSIBLE : $*"; exit 77; }

# exiger_commande g1-x : la commande doit exister (sinon : en attente)
exiger_commande() {
  local c
  for c in "$@"; do
    [ -x "$RACINE/bin/$c" ] || en_attente "la commande $c n'existe pas encore"
  done
}

# exiger_paquet_ros g1_sim : le paquet doit être compilé (sinon : en attente)
exiger_paquet_ros() {
  local p
  for p in "$@"; do
    ros2 pkg prefix "$p" > /dev/null 2>&1 || en_attente "le paquet ROS $p n'est pas compilé"
  done
}

# copier_demo ID : copie de lieux/demo dans $ATELIER_LIEUX/ID (les tests n'écrivent jamais dans demo)
copier_demo() {
  local id="${1:-essai}"
  rm -rf "${ATELIER_LIEUX:?}/$id"
  cp -r "$RACINE/lieux/demo" "$ATELIER_LIEUX/$id"
  rm -f "$ATELIER_LIEUX/$id"/cartes/*.pcd
}

# generer ID : g1-monde generer sur l'étage rdc
generer() {
  exiger_commande g1-monde
  g1-monde generer --lieu "$1" --etage rdc > "$TRAVAIL/journaux/generer.log" 2>&1 \
    || echoue "g1-monde generer a échoué ($(tail -n 3 "$TRAVAIL/journaux/generer.log" | tr '\n' ' '))"
}

# simuler ID : lance la simulation sans fenêtre et attend /odom et /points (au plus 60 s)
simuler() {
  exiger_commande g1-monde
  exiger_paquet_ros g1_sim
  lancer_fond simulation g1-monde simuler --lieu "$1" --etage rdc --sans-fenetre
  "$PY" "$OUTILS" attendre-sujets /odom /points --delai "${2:-60}" \
    || echoue "la simulation ne publie pas /odom et /points"
}

# serveur : lance g1-atelier sur un port libre ; l'adresse de l'API est dans $API
serveur() {
  exiger_commande g1-atelier
  PORT=$("$PY" -c "import socket; s = socket.socket(); s.bind(('127.0.0.1', 0)); print(s.getsockname()[1])")
  lancer_fond serveur g1-atelier --port "$PORT" --sans-navigateur
  API="http://127.0.0.1:$PORT"
  "$PY" "$OUTILS" attendre-http "$API/api/lieux" --delai 30 || echoue "le serveur de l'Atelier ne répond pas"
}

# http METHODE CHEMIN [JSON] : appel à l'API du serveur lancé par « serveur »
http() { "$PY" "$OUTILS" http "$1" "$API$2" ${3:+"$3"}; }
