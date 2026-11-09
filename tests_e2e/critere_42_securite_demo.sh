#!/usr/bin/env bash
# Critère 42, la sécurité de la démo (section 13.9 du plan, agent Borne et orchestrateur). Répétition par l'Atelier
# (Gazebo --jumeau avec le faux G1, faux slam_operate, navigation et pont), repérage, démo lancée ; une visite à
# chaque cas, le robot en route :
#   - ARRÊT (POST /api/arret {mode: repetition}) : pause en moins de 2 s ; « Débloquer » : aucun mouvement pendant
#     15 s (vérité à moins de 5 cm, aucun 7105 non nul), toujours en pause ; un choix à la borne refusé, la borne dit
#     « pause » ; « Reprendre » loin de l'accueil refusé (« Ramenez… ») ; « Ramener à l'accueil » : le robot revient
#     (demande explicite), puis attente ;
#   - « Bloquer » (verrou), faux G1 assis puis remis en marche (pas_en_marche), pont tué puis relancé (pont_absent,
#     en moins de 6 s), pilotage qui prend la main (pilotage) : chaque fois pause, 15 s sans mouvement après la levée ;
#   - jamais de /guide/aller de la démo pendant une pause (hors « Ramener ») ; jamais d'erreur 500 ; aucun processus
#     restant.
source "$(dirname "$0")/commun.sh"
exiger_commande g1-monde g1-guide g1-atelier g1-slam g1-accueil
exiger_paquet_ros g1_sim g1_nav g1_bridge g1_jumeau g1_accueil unitree_api
python3 -c "import g1_jumeau.robot" 2>/dev/null || en_attente "le faux G1 n'a pas ses services (g1_jumeau.robot)"
OUTILS_DEMO="$E2E/outils_demo_e2e.py"
OUTILS18="$E2E/critere_18_outils.py"
export ATELIER_VOIX_SONS="$TRAVAIL/sons"

copier_demo essai
sans_pieton_nord essai
"$PY" "$OUTILS_DEMO" preparer --lieu essai --sortie robot || echoue "demo.yaml de la copie"
generer essai
serveur

cd "$RACINE" || exit 1
"$PY" "$OUTILS_DEMO" critere-42 --api "$API" --lieu essai --journaux "$TRAVAIL/journaux" 2>&1 \
  | tee "$TRAVAIL/journaux/critere_42.log"
code=${PIPESTATUS[0]}
http POST /api/demo/arreter > /dev/null
http POST /api/simulation/arreter > /dev/null || echoue "POST /api/simulation/arreter refusé"
serveur_pid=$(pgrep -f "uvicorn atelier.serveur.main:app .*--port $PORT" | tr '\n' ' ')
sleep 3
"$PY" "$OUTILS18" restes --lieux "$ATELIER_LIEUX" --sauf $serveur_pid || echoue "des processus restent après « Arrêter »"
case $code in
  0) reussi "démo en répétition : ARRÊT, Bloquer, faux G1 assis, pont tué, pilotage : pause, rien ne repart seul (15 s), Ramener à l'accueil" ;;
  77) en_attente "$(grep 'EN ATTENTE' "$TRAVAIL/journaux/critere_42.log" | tail -n 1)" ;;
  *) echoue "$(grep -E 'ÉCHEC|Error|Traceback' "$TRAVAIL/journaux/critere_42.log" | tail -n 1 | cut -c1-500)" ;;
esac
