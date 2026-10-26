#!/usr/bin/env bash
# Critère 28, le pilotage contre le faux G1 (sections 7 et 11.5 du plan), sans fenêtre et sans robot.
# Montage : g1-atelier (avec G1_PILOTAGE_URL sur un port libre et un jeton), puis par l'API la
# répétition (Gazebo --jumeau avec le faux G1 étendu, faux slam_operate, navigation, pont), le
# repérage, et le nœud pilotage sur le PC (POST /api/pilotage/demarrer). On vérifie (outils :
# tests_e2e/outils_pilotage_e2e.py critere-28) :
#   - verrou : guide en visite → « prendre la main » refusé (409) ; avec forcer → /guide/stop, robot
#     arrêté, maître pilotage ; /guide/aller alors refusé (échec, événement « pilotage »), pont en
#     état pilotage, robot immobile ; « rendre la main » → le guide repart ; ARRÊT toujours permis ;
#   - postures 500, 706 et 3 acceptées (mode du faux G1 changé, lu par 7001) ; 1 et 0 refusées sans
#     la confirmation double et la case « robot au portique », acceptées avec ;
#   - joystick par le WebSocket de l'Atelier : vx 0,3 pendant 2 s → 0,6 ± 0,2 m ; arrêté 0,6 s au
#     plus après le dernier ordre ; WebSocket coupé en marche : arrêt en 0,6 s ; plafonds ;
#   - gestes : 26 accepté, un autre pendant qu'il tient → 7401 en français, 99 relâche, geste assis
#     → 7404 en français ; voix, volume et LED reçus par le faux G1 avec les bons paramètres ;
#   - interdits (7104, 7110, postures 2, 4 et 801) : 403, aucune requête au faux G1 ; demandes
#     absurdes : jamais 500, refus en français ; aucun processus restant.
# « En attente » (77) si le guide ne refuse pas encore /guide/aller pendant le pilotage (agent
# Comportement du guide) : tout le reste est alors vérifié, et le pont garde le robot immobile.
source "$(dirname "$0")/commun.sh"
exiger_commande g1-monde g1-guide g1-atelier g1-slam g1-pilotage
exiger_paquet_ros g1_sim g1_nav g1_bridge g1_jumeau g1_pilotage unitree_api unitree_hg
python3 -c "import g1_jumeau.robot" 2>/dev/null \
  || en_attente "le faux G1 n'est pas encore étendu aux services arm et voice (g1_jumeau.robot)"
OUTILS_PILOTAGE="$E2E/outils_pilotage_e2e.py"
OUTILS18="$E2E/critere_18_outils.py"

PORT_PILOTAGE=$("$PY" -c "import socket; s = socket.socket(); s.bind(('127.0.0.1', 0)); print(s.getsockname()[1])")
export G1_PILOTAGE_URL="http://127.0.0.1:$PORT_PILOTAGE"
export G1_PILOTAGE_JETON="jeton-e2e-$$-$RANDOM"
export ATELIER_CHOREGRAPHIES="$TRAVAIL/choregraphies"
mkdir -p "$ATELIER_CHOREGRAPHIES/musique"
cp "$RACINE/choregraphies/exemple_kpop.choregraphie.yaml" "$ATELIER_CHOREGRAPHIES/"
dire "nœud pilotage attendu sur le port $PORT_PILOTAGE, avec un jeton"

copier_demo essai
generer essai
serveur

"$PY" "$OUTILS_PILOTAGE" critere-28 --api "$API" --lieu essai 2>&1 | tee "$TRAVAIL/journaux/critere_28.log"
code=${PIPESTATUS[0]}
http POST /api/pilotage/arreter > /dev/null
http POST /api/simulation/arreter > /dev/null || echoue "POST /api/simulation/arreter refusé"
serveur_pid=$(pgrep -f "uvicorn atelier.serveur.main:app .*--port $PORT" | tr '\n' ' ')
sleep 2
"$PY" "$OUTILS18" restes --lieux "$ATELIER_LIEUX" --sauf $serveur_pid || echoue "des processus restent après « Arrêter »"
case $code in
  0) reussi "pilotage contre le faux G1 : verrou, postures et confirmations, joystick et homme mort, gestes, voix, LED, interdits" ;;
  77) en_attente "$(grep 'EN ATTENTE' "$TRAVAIL/journaux/critere_28.log" | tail -n 1)" ;;
  *) echoue "$(grep 'ÉCHEC' "$TRAVAIL/journaux/critere_28.log" | tail -n 1)" ;;
esac
