#!/usr/bin/env bash
# Point d'entrée du conteneur g1-jetson (section 10.2 du plan).
#   1. choisit les interfaces réseau et écrit la configuration CycloneDDS (reseau.py) ;
#   2. charge /opt/ros/humble et /opt/g1/install (env.sh) ;
#   3. écrit une ligne « g1-jetson : domaine N, interfaces …, lieu …, lancement … » ;
#   4. lance toujours le nœud de présence, qui publie /g1_jetson/etat (presence.py) ;
#   5. lance ce que demande G1_LANCEMENT :
#        navigation  ros2 launch g1_nav navigation.launch.py lieu:=/lieux/$G1_LIEU etage:=$G1_ETAGE
#                    simu:=$G1_SIMU localisation:=$G1_LOCALISATION [vitesse_max:=$G1_VITESSE_MAX]
#                    [arguments donnés après l'image]
#        veille      le nœud de présence seul
#        commande    la commande donnée après le nom de l'image (mise au point)
# docker stop (SIGTERM, relayé par --init) devient SIGINT pour ros2 launch, avec 15 s pour
# s'arrêter proprement : le pont envoie un arrêt au robot en quittant.
# Codes de sortie : 0 arrêt demandé ; 1 réglage faux ou réseau du robot introuvable ;
# sinon celui de ce qui a été lancé.
# Pas de set -u : les scripts de ROS 2 ne le supportent pas.

G1=/opt/g1
DELAI_ARRET_S=15
MOTIF_ID='^[a-z0-9][a-z0-9_-]{0,39}$'
G1_DEBUT="$(date +%s.%N)"
export G1_DEBUT

dire() { echo "g1-jetson : $*"; }
refuser() { echo "g1-jetson : $*" >&2; exit 1; }

# --- 0. Les variables du lancement ---------------------------------------------------------
export G1_LANCEMENT="${G1_LANCEMENT:-navigation}"
export G1_LOCALISATION="${G1_LOCALISATION:-unitree}"
export G1_SIMU="${G1_SIMU:-false}"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-0}"

case "$G1_LANCEMENT" in
  navigation|veille|commande) ;;
  *) refuser "G1_LANCEMENT=$G1_LANCEMENT inconnu : navigation, veille ou commande" ;;
esac
if ! [[ "$ROS_DOMAIN_ID" =~ ^[0-9]+$ ]] || [ "$ROS_DOMAIN_ID" -gt 232 ]; then
  refuser "ROS_DOMAIN_ID=$ROS_DOMAIN_ID : il faut un nombre de 0 à 232 (le robot publie sur 0)"
fi
if [ "$G1_LANCEMENT" = navigation ]; then
  if [ -z "$G1_LIEU" ] || [ -z "$G1_ETAGE" ]; then
    refuser "G1_LIEU et G1_ETAGE sont obligatoires pour la navigation (g1-jetson demarrer --lieu L --etage E)"
  fi
  [[ "$G1_LIEU" =~ $MOTIF_ID ]] || refuser "G1_LIEU=$G1_LIEU : il faut l'id d'un lieu, dossier de /lieux"
  [[ "$G1_ETAGE" =~ $MOTIF_ID ]] || refuser "G1_ETAGE=$G1_ETAGE : il faut l'id d'un étage du lieu"
  if [ ! -f "/lieux/$G1_LIEU/lieu.yaml" ]; then
    refuser "lieu « $G1_LIEU » introuvable dans /lieux : copiez-le sur le robot avec « g1-jetson lieu --lieu $G1_LIEU » (sur le PC : vérifiez ATELIER_LIEUX)"
  fi
  case "$G1_LOCALISATION" in
    unitree|amcl) ;;
    simu) refuser "G1_LOCALISATION=simu est refusé dans le conteneur : unitree ou amcl (la simulation seule se lance sur le PC, avec g1-guide navigation --simu)" ;;
    *) refuser "G1_LOCALISATION=$G1_LOCALISATION inconnue : unitree ou amcl" ;;
  esac
  case "$G1_SIMU" in
    true|false) ;;
    *) refuser "G1_SIMU=$G1_SIMU : true (répétition avec Gazebo sur l'hôte) ou false (robot)" ;;
  esac
  # Premiers essais : vitesse maximale réduite (m/s), les plafonds du pont baissent d'autant
  if [ -n "$G1_VITESSE_MAX" ] && ! [[ "$G1_VITESSE_MAX" =~ ^0?\.[0-9]+$ ]]; then
    refuser "G1_VITESSE_MAX=$G1_VITESSE_MAX : une vitesse en m/s, plus petite que 1 (ex. 0.2)"
  fi
fi
if [ "$G1_LANCEMENT" = commande ] && [ $# -eq 0 ]; then
  refuser "G1_LANCEMENT=commande : donnez la commande après le nom de l'image (ex. ros2 topic list)"
fi

# --- 1. Le réseau --------------------------------------------------------------------------
# INTERFACES : noms retenus, séparés par des virgules (vide : CycloneDDS choisit) ; TEXTE : pour la ligne
if [ -n "$G1_CYCLONEDDS_URI" ]; then
  URI="$G1_CYCLONEDDS_URI"
  INTERFACES=""
  TEXTE_INTERFACES="imposées par G1_CYCLONEDDS_URI"
  rm -f /tmp/cyclonedds.xml
else
  SORTIE=$(python3 "$G1/reseau.py" cyclonedds --sortie /tmp/cyclonedds.xml \
             --modele "$G1/cyclonedds.xml.modele") || exit 1
  INTERFACES=$(sed -n 's/^interfaces=//p' <<< "$SORTIE")
  URI=$(sed -n 's/^uri=//p' <<< "$SORTIE")
  TEXTE_INTERFACES="${INTERFACES:-par défaut (CycloneDDS choisit)}"
fi
{
  if [ -n "$URI" ]; then printf 'export CYCLONEDDS_URI=%q\n' "$URI"; else echo 'unset CYCLONEDDS_URI'; fi
  printf 'export G1_INTERFACES_CHOISIES=%q\n' "$INTERFACES"
} > /tmp/g1_reseau.sh

# --- 2. ROS 2 Humble et les paquets du projet ---------------------------------------------
source "$G1/env.sh"
if ! mkdir -p "$ROS_LOG_DIR" 2>/dev/null || [ ! -w "$ROS_LOG_DIR" ]; then
  echo "g1-jetson : attention, $ROS_LOG_DIR n'est pas inscriptible (dossier des journaux monté ?) : journaux ROS dans /tmp/ros" >&2
  export ROS_HOME=/tmp/ros ROS_LOG_DIR=/tmp/ros/log
  mkdir -p "$ROS_LOG_DIR"
fi

# --- 3. La ligne de démarrage -------------------------------------------------------------
VERSION=$(sed -n 's/^\(date\|commit\)=//p' "$G1/VERSION" 2>/dev/null | paste -sd ' ')
dire "domaine $ROS_DOMAIN_ID, interfaces $TEXTE_INTERFACES," \
     "lieu ${G1_LIEU:-aucun}${G1_ETAGE:+ (étage $G1_ETAGE)}, lancement $G1_LANCEMENT" \
     "(localisation $G1_LOCALISATION, simu $G1_SIMU${G1_VITESSE_MAX:+, vitesse max $G1_VITESSE_MAX m/s})," \
     "version ${VERSION:-inconnue}, $(uname -m)"

# Contrôle des tâches : sans lui, bash fait ignorer SIGINT aux programmes lancés en arrière-plan,
# et ros2 launch ne recevrait jamais la demande d'arrêt.
set -m

# vivant PID : le processus existe et n'est pas un zombie
vivant() {
  [ -r "/proc/$1/stat" ] || return 1
  [ "$(sed -E 's/^.*\) ([A-Za-z]).*$/\1/' "/proc/$1/stat" 2>/dev/null)" != Z ]
}

# arreter_processus PID SIGNAL DELAI_S : envoie le signal, puis attend la fin (code 1 si trop long)
arreter_processus() {
  local pid="$1" signal="$2" delai="$3" i
  [ -n "$pid" ] && vivant "$pid" || return 0
  kill -s "$signal" "$pid" 2>/dev/null
  for ((i = 0; i < delai * 10; i++)); do
    vivant "$pid" || return 0
    sleep 0.1
  done
  return 1
}

arreter() {
  trap '' TERM INT
  dire "arrêt demandé : SIGINT à $NOM_PRINCIPAL ($DELAI_ARRET_S s au plus)"
  if ! arreter_processus "$PID_PRINCIPAL" INT "$DELAI_ARRET_S"; then
    dire "$NOM_PRINCIPAL ne s'est pas arrêté en $DELAI_ARRET_S s : SIGTERM, puis SIGKILL"
    arreter_processus "$PID_PRINCIPAL" TERM 2 || kill -KILL "$PID_PRINCIPAL" 2>/dev/null
  fi
  arreter_processus "$PID_PRESENCE" INT 3 || kill -KILL "$PID_PRESENCE" 2>/dev/null
  dire "arrêté"
  exit 0
}
trap arreter TERM INT

# --- 4. Le nœud de présence ---------------------------------------------------------------
python3 "$G1/presence.py" &
PID_PRESENCE=$!

# --- 5. Ce que demande G1_LANCEMENT -------------------------------------------------------
case "$G1_LANCEMENT" in
  navigation)
    NOM_PRINCIPAL="ros2 launch"
    VITESSE=()
    [ -n "$G1_VITESSE_MAX" ] && VITESSE=("vitesse_max:=$G1_VITESSE_MAX")
    ros2 launch g1_nav navigation.launch.py "lieu:=/lieux/$G1_LIEU" "etage:=$G1_ETAGE" \
      "simu:=$G1_SIMU" "localisation:=$G1_LOCALISATION" "${VITESSE[@]}" "$@" &
    PID_PRINCIPAL=$!
    ;;
  veille)
    NOM_PRINCIPAL="le nœud de présence"
    PID_PRINCIPAL=$PID_PRESENCE
    ;;
  commande)
    NOM_PRINCIPAL="$1"
    "$@" &
    PID_PRINCIPAL=$!
    ;;
esac

wait "$PID_PRINCIPAL"
CODE=$?
trap '' TERM INT
dire "$NOM_PRINCIPAL s'est arrêté seul (code $CODE)"
[ "$PID_PRESENCE" != "$PID_PRINCIPAL" ] && { arreter_processus "$PID_PRESENCE" INT 3 || kill -KILL "$PID_PRESENCE" 2>/dev/null; }
exit "$CODE"
