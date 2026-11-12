#!/usr/bin/env bash
# Critère 20, sécurité (sections 7 et 10.3 du plan) : la vraie chaîne de répétition, lancée par
# l'Atelier (Gazebo --jumeau avec le faux G1, faux slam_operate, relais odom_vers_tf, pont, Nav2,
# guide). Un témoin compare en continu la vérité terrain aux mouvements permis : jamais plus de
# 5 cm hors d'une consigne permise. Cas (critere_20_outils.py) :
#   pont sans repérage ; guide avant le repérage ; consignes absurdes (NaN, infini, 1e9) par /cmd_vel
#   et par les flèches ; faux G1 muet en marche ; relocalisation perdue en marche ; ARRÊT et verrou
#   depuis l'Atelier pendant « Y aller » ; faux G1 arrêté par SIGTERM puis relancé ; pont tué par
#   SIGKILL puis relancé ; demandes absurdes à l'API (messages en français, jamais d'erreur 500).
# Puis POST /api/simulation/arreter : plus aucun processus ne reste.
# Sans fenêtre ; jamais le vrai robot (G1_SLAM_FAUX=1).
source "$(dirname "$0")/commun.sh"
exiger_commande g1-monde g1-guide g1-atelier g1-slam
exiger_paquet_ros g1_sim g1_nav g1_bridge g1_jumeau unitree_api
grep -q "jumeau" "$(ros2 pkg prefix g1_sim)/share/g1_sim/launch/simulation.launch.py" \
  || en_attente "g1_sim n'a pas encore l'argument jumeau (agent Pont et faux G1)"
OUTILS20="$E2E/critere_20_outils.py"
OUTILS18="$E2E/critere_18_outils.py"

copier_demo essai
generer essai
serveur

"$PY" "$OUTILS20" securite --api "$API" --lieu essai --journaux "$TRAVAIL/journaux" 2>&1 \
  | tee "$TRAVAIL/journaux/securite.log"
[ "${PIPESTATUS[0]}" -eq 0 ] \
  || echoue "$(grep -E 'ÉCHEC|ERREUR' "$TRAVAIL/journaux/securite.log" | head -n 3 | tr '\n' ' ')"

http POST /api/simulation/arreter > /dev/null || echoue "POST /api/simulation/arreter refusé"
serveur_pid=$(pgrep -f "uvicorn atelier.serveur.main:app .*--port $PORT" | tr '\n' ' ')
sleep 2
"$PY" "$OUTILS18" restes --lieux "$ATELIER_LIEUX" --sauf $serveur_pid || echoue "des processus restent après « Arrêter »"
reussi "témoin sans faute ; arrêts, verrou, pannes, plafonds et refus vérifiés"
