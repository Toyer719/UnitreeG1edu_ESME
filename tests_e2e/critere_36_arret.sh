#!/usr/bin/env bash
# Critère 36, l'ARRÊT global (section 12.10 du plan, décision I5) : agent Coquille. Sans robot, sans fenêtre.
# Montage : g1-atelier (avec G1_PILOTAGE_URL sur un port libre et un jeton), puis par l'API la simulation, la
# répétition (Gazebo --jumeau avec le faux G1, faux slam_operate, navigation, pont), le repérage et le nœud
# pilotage sur le PC. On vérifie (outils : tests_e2e/critere_36_outils.py ; la partie navigateur avec
# atelier/tests/test_coque_communs.py) :
#   - simulation, téléopération à 0,3 m/s : POST /api/arret {mode: simu} arrête le robot (vérité /odom) en
#     moins de 1 s, sans verrou (verrou faux, rien publié sur /pont/arret) ;
#   - répétition, « Y aller » vers b204 ; quand le robot roule (plus de 0,15 m/s, vérité /g1_jumeau/odom) :
#     POST /api/arret {mode: repetition} répond en moins de 1 s (200, parties.guide.ok et parties.verrou.ok
#     vrais), robot arrêté (moins de 2 cm/s) moins de 1 s après la demande, /guide/etat quitte en_route,
#     /pont/etat passe à arret_verrouille en moins de 1 s ;
#   - verrou posé : un nouveau « Y aller » laisse le robot immobile (moins de 5 cm) pendant 5 s ; GET /api/arret
#     dit verrou vrai ; POST /api/arret/debloquer, puis « Y aller » : le robot repart (0,3 m au moins) ;
#   - dans Firefox, robot en route : le clic sur [data-role=arret] et la touche Échap envoient POST /api/arret ;
#     le bouton passe à « Débloquer » (data-etat=bloque) ;
#   - nœud pilotage, main prise, joystick à vx 0,3 par /ws/pilotage : POST /api/arret → StopMove reçu par le
#     faux G1 en moins de 1 s, robot arrêté ; nœud pilotage arrêté : POST /api/arret répond quand même en
#     moins de 1 s, parties.pilotage.ok faux avec un message, le reste arrêté ;
#   - jamais d'erreur 500 ; aucun processus restant.
source "$(dirname "$0")/commun.sh"
exiger_commande g1-monde g1-guide g1-atelier g1-slam g1-pilotage
exiger_paquet_ros g1_sim g1_nav g1_bridge g1_jumeau g1_pilotage unitree_api unitree_hg
python3 -c "import g1_jumeau.robot" 2>/dev/null \
  || en_attente "le faux G1 n'est pas étendu aux services du pilotage (g1_jumeau.robot)"
command -v geckodriver > /dev/null && command -v firefox > /dev/null \
  || en_attente "Firefox sans fenêtre (firefox et geckodriver) n'est pas installé"
OUTILS36="$E2E/critere_36_outils.py"
OUTILS18="$E2E/critere_18_outils.py"

PORT_PILOTAGE=$("$PY" -c "import socket; s = socket.socket(); s.bind(('127.0.0.1', 0)); print(s.getsockname()[1])")
export G1_PILOTAGE_URL="http://127.0.0.1:$PORT_PILOTAGE"
export G1_PILOTAGE_JETON="jeton-e2e-$$-$RANDOM"
export ATELIER_CHOREGRAPHIES="$TRAVAIL/choregraphies"
mkdir -p "$ATELIER_CHOREGRAPHIES"
dire "nœud pilotage attendu sur le port $PORT_PILOTAGE, avec un jeton"

copier_demo essai
sans_pieton_nord essai
generer essai
serveur

cd "$RACINE" || exit 1
"$PY" "$OUTILS36" critere-36 --api "$API" --lieu essai 2>&1 | tee "$TRAVAIL/journaux/critere_36.log"
code=${PIPESTATUS[0]}
http POST /api/pilotage/arreter > /dev/null
http POST /api/simulation/arreter > /dev/null || echoue "POST /api/simulation/arreter refusé"
serveur_pid=$(pgrep -f "uvicorn atelier.serveur.main:app .*--port $PORT" | tr '\n' ' ')
sleep 3
"$PY" "$OUTILS18" restes --lieux "$ATELIER_LIEUX" --sauf $serveur_pid || echoue "des processus restent après « Arrêter »"
case $code in
  0) reussi "ARRÊT global : simulation sans verrou, répétition (guide, verrou, Débloquer), bouton et Échap, pilotage, nœud arrêté" ;;
  77) en_attente "$(grep 'EN ATTENTE' "$TRAVAIL/journaux/critere_36.log" | tail -n 1)" ;;
  *) echoue "$(grep -E 'ÉCHEC|Error|Traceback' "$TRAVAIL/journaux/critere_36.log" | tail -n 1 | cut -c1-500)" ;;
esac
