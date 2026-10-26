#!/usr/bin/env bash
# Critère 22, retour automatique (sections 7 et 11.4 du plan, agent Comportement du guide).
# Simulation d'une copie du demo, avec guide: {delai_avant_retour_s: 5} dans lieu.yaml :
#   - POST /api/guide/aller {cible: "b204"} → arrive à moins de 0,3 m ;
#   - puis, seul, retour (cible : le point principal) et attente en moins de 120 s, le robot à
#     moins de 0,3 m et 10° du principal ;
#   - événements arrivee, retour et retour_arrive sur /guide/evenement, en français, conformes ;
#     tous les /guide/etat conformes au schéma etat_guide ;
#   - avec {"cible": "b204", "retour": false}, le robot reste à b204 (moins de 0,1 m en 20 s) ;
#   - aucun processus restant après « Arrêter ».
source "$(dirname "$0")/commun.sh"
exiger_commande g1-monde g1-guide g1-atelier
exiger_paquet_ros g1_sim g1_nav
OUTILS_GUIDE="$E2E/outils_guide_e2e.py"
copier_demo essai
"$PY" "$OUTILS_GUIDE" preparer --lieu essai --guide '{"delai_avant_retour_s": 5}' \
  || echoue "réglages du guide de la copie impossibles"
generer essai
serveur

"$PY" "$OUTILS_GUIDE" retour --api "$API" --lieu essai 2>&1 | tee "$TRAVAIL/journaux/retour.log"
[ "${PIPESTATUS[0]}" -eq 0 ] || echoue "$(grep 'ÉCHEC' "$TRAVAIL/journaux/retour.log" | tail -n 1)"

http POST /api/simulation/arreter > /dev/null || echoue "POST /api/simulation/arreter refusé"
serveur_pid=$(pgrep -f "uvicorn atelier.serveur.main:app .*--port $PORT" | tr '\n' ' ')
sleep 2
"$PY" "$OUTILS_GUIDE" restes --lieux "$ATELIER_LIEUX" --sauf $serveur_pid || echoue "des processus restent après « Arrêter »"
reussi "b204, retour seul au point principal (0,3 m, 10°), puis b204 sans retour"
