#!/usr/bin/env bash
# Critère 27, perdu en route (sections 7 et 11.4 du plan, agent Comportement du guide).
# Répétition d'une copie du demo (guide: {delai_perdu_s: 15, delai_avant_retour_s: 5}), repérage,
# /guide/aller b204, puis /faux_slam/panne muet en route :
#   - perdu en moins de 4 s, événement perdu, robot arrêté (moins de 5 cm en 3 s) ;
#   - cas A, panne levée après 5 s : retrouve, reprise, arrive à moins de 0,3 m ;
#   - cas B (vers l'accueil), la panne reste : echec 15 s (± 2 s) après perdu, avec un message qui
#     dit quoi faire, événement echec, robot immobile, pas de retour automatique ;
#   - aucun processus restant après « Arrêter ».
# Vérité terrain : /g1_jumeau/odom. Sans fenêtre ; jamais le vrai robot (G1_SLAM_FAUX=1).
source "$(dirname "$0")/commun.sh"
exiger_commande g1-monde g1-guide g1-atelier g1-slam
exiger_paquet_ros g1_sim g1_nav g1_bridge g1_jumeau unitree_api
OUTILS_GUIDE="$E2E/outils_guide_e2e.py"
copier_demo essai
"$PY" "$OUTILS_GUIDE" preparer --lieu essai --guide '{"delai_perdu_s": 15, "delai_avant_retour_s": 5}' \
  || echoue "réglages du guide de la copie impossibles"
generer essai
serveur

"$PY" "$OUTILS_GUIDE" perdu --api "$API" --lieu essai 2>&1 | tee "$TRAVAIL/journaux/perdu.log"
[ "${PIPESTATUS[0]}" -eq 0 ] || echoue "$(grep 'ÉCHEC' "$TRAVAIL/journaux/perdu.log" | tail -n 1)"

http POST /api/simulation/arreter > /dev/null || echoue "POST /api/simulation/arreter refusé"
serveur_pid=$(pgrep -f "uvicorn atelier.serveur.main:app .*--port $PORT" | tr '\n' ' ')
sleep 2
"$PY" "$OUTILS_GUIDE" restes --lieux "$ATELIER_LIEUX" --sauf $serveur_pid || echoue "des processus restent après « Arrêter »"
reussi "perdu en route : arrêt, reprise quand le robot se retrouve, échec sans retour s'il reste perdu"
