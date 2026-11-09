#!/usr/bin/env bash
# Critère 40, la voix du robot (section 13.9 du plan, critère 40 ; section 13.6), sans fenêtre et sans robot.
# Montage : le faux G1 seul (ros2 run g1_jumeau jumeau, sans Gazebo) et g1-atelier dans le domaine du test ; la
# voix (g1-voix, sortie robot) est lancée par l'Atelier (POST /api/voix/demarrer). On vérifie (outils :
# tests_e2e/outils_voix_e2e.py critere-40) :
#   - /robot/dire « Bonjour, suivez-moi ! » : 1003 conformes, même stream_id, morceaux de 96 000 octets au plus
#     et pairs, durée à 5 % près du WAV de Piper de la phrase rééchantillonné à 16 kHz ; aucune requête hors de
#     1001, 1003, 1004, 1005, 1006 ;
#   - trois phrases dans l'ordre, jamais deux flux en même temps ; haute : 1004 puis la nouvelle ; securite :
#     1004 puis elle seule (file vidée) ;
#   - /voix/commande volume 60 → 1006 {"volume": 60} ; taire → 1004 ; sortie robot_tts → 1001 ; sortie borne →
#     WAV dans ATELIER_VOIX_SONS, /voix/son conforme, GET /api/voix/son/<id> en audio/wav ;
#   - un 1003 de 3 octets envoyé par le test : écart compté par le faux G1 (3204) ; panne muet : /voix/etat dit
#     le robot muet, rien ne plante ; /voix/etat conforme tout du long ; aucun processus restant.
# Jamais de son ni de requête vers le vrai robot : le faux G1 seul, dans le domaine du test.
source "$(dirname "$0")/commun.sh"
exiger_commande g1-atelier g1-voix
exiger_paquet_ros g1_jumeau unitree_api
"$PY" -c "import piper" 2>/dev/null || en_attente "Piper n'est pas installé dans .venv-projet"
[ -f "$RACINE/modeles/piper/fr_FR-siwis-medium.onnx" ] || en_attente "la voix Piper fr_FR-siwis-medium manque (modeles/piper/)"
python3 -c "import g1_jumeau.audio as a; assert hasattr(a, 'Flux')" 2>/dev/null \
  || en_attente "le faux G1 ne suit pas encore les flux de son (g1_jumeau/audio.py, agent Voix)"
OUTILS_VOIX="$E2E/outils_voix_e2e.py"

export ATELIER_VOIX_SONS="$TRAVAIL/sons"
mkdir -p "$ATELIER_VOIX_SONS"
copier_demo essai

lancer_fond jumeau ros2 run g1_jumeau jumeau
serveur

"$PY" "$OUTILS_VOIX" critere-40 --api "$API" --lieu essai --sons "$ATELIER_VOIX_SONS" 2>&1 \
  | tee "$TRAVAIL/journaux/critere_40.log"
code=${PIPESTATUS[0]}
http POST /api/voix/arreter > /dev/null
sleep 1
"$PY" "$OUTILS_VOIX" restes --sons "$ATELIER_VOIX_SONS" || echoue "un nœud voix reste après « Arrêter la voix »"
case $code in
  0) reussi "voix contre le faux G1 : PCM 16 kHz en morceaux conformes, file et priorités, volume, taire, robot_tts, borne, écart compté, robot muet" ;;
  *) echoue "$(grep 'ÉCHEC' "$TRAVAIL/journaux/critere_40.log" | tail -n 1)" ;;
esac
