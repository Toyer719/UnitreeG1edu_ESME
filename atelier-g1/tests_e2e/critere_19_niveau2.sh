#!/usr/bin/env bash
# Critère 19, le niveau 2 complet en répétition, depuis l'Atelier (sections 7 et 10 du plan) :
#   - g1-atelier, puis POST /api/simulation/demarrer {lieu, etage, mode: repetition} : Gazebo
#     --jumeau (faux G1), g1-slam faux-service --jumeau, g1-guide navigation --simu
#     --localisation unitree (relais, pont, Nav2, guide) ;
#   - « Y aller » avant le repérage : 409 ; POST /api/robot/reperer ; attente de Nav2 ;
#   - POST /api/guide/aller b204 : arrive en moins de 180 s, à moins de 0,3 m de b204 (vérité
#     terrain /g1_jumeau/odom) ; tout le mouvement passe par le pont et le faux G1 (requêtes 7105
#     comptées, rien dans Gazebo n'écoute /cmd_vel ; vague 5 : plus les lectures du mode 7001) ;
#   - une boîte dans le couloir nord (comme au critère 5), puis POST /api/guide/aller accueil :
#     bloque → detour → arrive, à moins de 0,3 m ;
#   - POST /api/simulation/arreter : plus aucun processus ne reste.
# E2E_CONTENEUR=1 : la navigation tourne dans le conteneur du Jetson (g1-jetson demarrer --local,
# G1_SIMU=true) au lieu de l'hôte. L'Atelier lance alors un g1-guide de test qui démarre le
# conteneur, suit son journal et l'arrête (g1-jetson arreter --local) quand on arrête la répétition.
# Sans fenêtre ; jamais le vrai robot (G1_SLAM_FAUX=1).
source "$(dirname "$0")/commun.sh"
exiger_commande g1-monde g1-guide g1-atelier g1-slam
exiger_paquet_ros g1_sim g1_nav g1_bridge g1_jumeau unitree_api
grep -q "jumeau" "$(ros2 pkg prefix g1_sim)/share/g1_sim/launch/simulation.launch.py" \
  || en_attente "g1_sim n'a pas encore l'argument jumeau (agent Pont et faux G1)"
OUTILS19="$E2E/critere_19_outils.py"
OUTILS18="$E2E/critere_18_outils.py"
OPTION_CONTENEUR=""

if [ "$E2E_CONTENEUR" = 1 ]; then
  command -v docker > /dev/null && docker info > /dev/null 2>&1 || en_attente "E2E_CONTENEUR=1 : Docker inutilisable"
  exiger_commande g1-jetson
  export G1_JETSON_NOM="g1-jetson-e2e-$ROS_DOMAIN_ID-niveau2"
  dire "E2E_CONTENEUR=1 : image g1-jetson:amd64 (reconstruite si g1_nav ou g1_bridge ont changé)"
  g1-jetson construire --arch amd64 > "$TRAVAIL/journaux/construire.log" 2>&1 \
    || echoue "g1-jetson construire --arch amd64 a échoué ($(tail -n 3 "$TRAVAIL/journaux/construire.log" | tr '\n' ' '))"
  # Les commandes de l'Atelier : les vraies, sauf g1-guide navigation, qui passe par le conteneur
  mkdir -p "$TRAVAIL/bin"
  for c in "$RACINE"/bin/g1-*; do ln -s "$c" "$TRAVAIL/bin/$(basename "$c")"; done
  rm "$TRAVAIL/bin/g1-guide"
  cat > "$TRAVAIL/bin/g1-guide" <<SCRIPT
#!/usr/bin/env bash
# g1-guide du critère 19 (E2E_CONTENEUR=1) : « navigation » tourne dans le conteneur du Jetson.
[ "\$1" = navigation ] || exec "$RACINE/bin/g1-guide" "\$@"
shift
lieu=""; etage=""; localisation=unitree
while [ \$# -gt 0 ]; do
  case "\$1" in
    --lieu) lieu="\$2"; shift 2 ;;
    --etage) etage="\$2"; shift 2 ;;
    --localisation) localisation="\$2"; shift 2 ;;
    *) shift ;;
  esac
done
finir() { trap - INT TERM; echo "arrêt du conteneur"; "$RACINE/bin/g1-jetson" arreter --local; exit 0; }
trap finir INT TERM
G1_SIMU=true "$RACINE/bin/g1-jetson" demarrer --local --lieu "\$lieu" --etage "\$etage" --localisation "\$localisation" || exit 1
"$RACINE/bin/g1-jetson" journal --local -f &
wait \$!
finir
SCRIPT
  chmod +x "$TRAVAIL/bin/g1-guide"
  export ATELIER_BIN="$TRAVAIL/bin"
  OPTION_CONTENEUR="--conteneur"
  # Ménage du conteneur, même après une erreur
  trap 'code=$?; docker rm -f "$G1_JETSON_NOM" > /dev/null 2>&1; (exit $code); nettoyer' EXIT
fi

copier_demo essai
sans_pieton_nord essai
generer essai
serveur

"$PY" "$OUTILS19" niveau2 --api "$API" --lieu essai $OPTION_CONTENEUR 2>&1 | tee "$TRAVAIL/journaux/niveau2.log"
[ "${PIPESTATUS[0]}" -eq 0 ] || echoue "$(grep 'ÉCHEC' "$TRAVAIL/journaux/niveau2.log" | tail -n 1)"

http POST /api/simulation/arreter > /dev/null || echoue "POST /api/simulation/arreter refusé"
serveur_pid=$(pgrep -f "uvicorn atelier.serveur.main:app .*--port $PORT" | tr '\n' ' ')
sleep 2
"$PY" "$OUTILS18" restes --lieux "$ATELIER_LIEUX" --sauf $serveur_pid || echoue "des processus restent après « Arrêter »"
if [ "$E2E_CONTENEUR" = 1 ]; then
  [ -z "$(docker ps -aq --filter "name=^$G1_JETSON_NOM\$")" ] || echoue "le conteneur $G1_JETSON_NOM reste après « Arrêter »"
fi
reussi "niveau 2 de bout en bout depuis l'Atelier : repérage, b204, détour par le couloir sud${OPTION_CONTENEUR:+ (navigation dans le conteneur)}"
