#!/usr/bin/env bash
# Critère 41, la démo complète en simulation (section 13.9 du plan, agent Borne et orchestrateur). Copie du demo
# (guide : delai_avant_retour_s 5, scène accompagnement : le faux visiteur ; demo.yaml : voix sur la borne ;
# personnalités d'exemple), simulation par l'Atelier, POST /api/demo/lancer : attente en moins de 30 s ;
#   - trois visiteurs de suite (b204, cdi, amphi) : le faux visiteur suit ; visiteur vu au LiDAR (ou un appui sur la
#     borne) → salutation de la personnalité sur /robot/dire → POST /api/borne/choisir → accompagnement
#     (/guide/aller avec accompagner et source accueil) → arrivée à moins de 0,3 m → retour → attente au principal
#     (0,3 m) ; la borne suit (GET /api/borne/etat) ;
#   - statistiques : 3 visiteurs, 3 visites réussies ; /accueil/etat et /accueil/evenement conformes ; moins de
#     15 min ; POST /api/demo/arreter : plus de nœud accueil ni voix ; aucun processus restant.
source "$(dirname "$0")/commun.sh"
exiger_commande g1-monde g1-guide g1-atelier g1-accueil
exiger_paquet_ros g1_sim g1_nav g1_accueil
LANCEMENT_SIM="$(ros2 pkg prefix g1_sim)/share/g1_sim/launch/simulation.launch.py"
grep -q "pietons" "$LANCEMENT_SIM" || en_attente "g1_sim n'a pas les piétons crédibles (le faux visiteur)"
OUTILS_GUIDE="$E2E/outils_guide_e2e.py"
OUTILS_DEMO="$E2E/outils_demo_e2e.py"
export ATELIER_VOIX_SONS="$TRAVAIL/sons"

copier_demo essai
"$PY" "$OUTILS_GUIDE" preparer --lieu essai --scene accompagnement --guide '{"delai_avant_retour_s": 5}' \
  || echoue "la scène accompagnement ne s'applique pas à la copie"
"$PY" "$OUTILS_DEMO" preparer --lieu essai --sortie borne || echoue "demo.yaml de la copie"
generer essai
serveur
lancer_fond faux_visiteur "$PY" -m g1_nav.faux_visiteur --ros-args -p visiteur:=visiteur -p verite:=/odom \
  -p lieu:="$ATELIER_LIEUX/essai" -p etage:=rdc -p use_sim_time:=true -p mode:=suivre
VISITEUR=$DERNIER

cd "$RACINE" || exit 1
"$PY" "$OUTILS_DEMO" critere-41 --api "$API" --lieu essai --journaux "$TRAVAIL/journaux" 2>&1 \
  | tee "$TRAVAIL/journaux/critere_41.log"
code=${PIPESTATUS[0]}
http POST /api/demo/arreter > /dev/null
http POST /api/simulation/arreter > /dev/null || echoue "POST /api/simulation/arreter refusé"
arreter_groupe "$VISITEUR"
serveur_pid=$(pgrep -f "uvicorn atelier.serveur.main:app .*--port $PORT" | tr '\n' ' ')
sleep 3
"$PY" "$OUTILS_GUIDE" restes --lieux "$ATELIER_LIEUX" --sauf $serveur_pid || echoue "des processus restent après « Arrêter »"
case $code in
  0) reussi "trois visiteurs de suite en simulation (salutation, borne, accompagnement, arrivée, retour), statistiques, arrêt propre" ;;
  77) en_attente "$(grep 'EN ATTENTE' "$TRAVAIL/journaux/critere_41.log" | tail -n 1)" ;;
  *) echoue "$(grep -E 'ÉCHEC|Error|Traceback' "$TRAVAIL/journaux/critere_41.log" | tail -n 1 | cut -c1-500)" ;;
esac
