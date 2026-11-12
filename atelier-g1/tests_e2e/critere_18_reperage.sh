#!/usr/bin/env bash
# Critère 18, repérage (sections 7 et 10 du plan) : répétition sur une copie du demo, lancée par
# l'Atelier (POST /api/simulation/demarrer mode repetition : Gazebo --jumeau avec le faux G1,
# g1-slam faux-service --jumeau, g1-guide navigation --simu --localisation unitree).
#   A. repère d'Unitree figé (départ du robot, (2,5 ; 10 ; 0)) : non repéré avant, « Y aller » refusé ;
#      « Repérer le robot » sans pose, depuis le point principal (vague 4), en moins de 20 s (1804
#      avec (0, 0, 0) et repetition.pcd) ; map → base_link à moins de 0,1 m et 0,05 rad de la vérité,
#      aussi après 2 m et 90° par /cmd_vel (pont, faux G1) alors que l'odométrie dérive ;
#      relocalisation coupée : perdu en moins de 4 s, puis repéré ;
#   B. repere_unitree (3 ; 9 ; 0,5) : refus avec une pose fausse donnée exprès (502), puis repéré sans
#      pose, depuis le point principal (2,5 ; 10 ; 0), avec la pose convertie dans 1804 ;
#   /reperage/etat toujours conforme au schéma, et plus aucun processus à la fin.
# Vérité terrain : /g1_jumeau/odom. Sans fenêtre ; jamais le vrai robot (G1_SLAM_FAUX=1).
source "$(dirname "$0")/commun.sh"
exiger_commande g1-monde g1-guide g1-atelier g1-slam
exiger_paquet_ros g1_sim g1_nav g1_bridge g1_jumeau unitree_api
grep -q "jumeau" "$(ros2 pkg prefix g1_sim)/share/g1_sim/launch/simulation.launch.py" \
  || en_attente "g1_sim n'a pas encore l'argument jumeau (agent Pont et faux G1)"
OUTILS18="$E2E/critere_18_outils.py"

# restes : plus aucun processus lancé avec nos lieux, à part le serveur de l'Atelier lui-même
restes() {
  local serveur_pid
  serveur_pid=$(pgrep -f "uvicorn atelier.serveur.main:app .*--port $PORT" | tr '\n' ' ')
  sleep 2
  "$PY" "$OUTILS18" restes --lieux "$ATELIER_LIEUX" --sauf $serveur_pid
}

# A. repère d'Unitree figé de la répétition
copier_demo essai
generer essai
serveur
"$PY" "$OUTILS18" variante-a --api "$API" --lieu essai 2>&1 | tee "$TRAVAIL/journaux/variante_a.log"
[ "${PIPESTATUS[0]}" -eq 0 ] || echoue "variante A : $(grep 'ÉCHEC' "$TRAVAIL/journaux/variante_a.log" | tail -n 1)"
http POST /api/simulation/arreter > /dev/null || echoue "POST /api/simulation/arreter refusé"
restes || echoue "variante A : des processus restent après « Arrêter »"

# B. repère d'Unitree tourné (3 ; 9 ; 0,5)
copier_demo essai_b
"$PY" - "$ATELIER_LIEUX/essai_b" <<'PYTHON' || echoue "repere_unitree de la variante B non écrit"
import sys
from atelier.lieu import Pose, charger_fiche, enregistrer_fiche
fiche = charger_fiche(sys.argv[1])
fiche.etages[0].repere_unitree = Pose(3.0, 9.0, 0.5)
enregistrer_fiche(fiche)
print("repere_unitree de essai_b : (3 ; 9 ; 0,5)")
PYTHON
generer essai_b
"$PY" "$OUTILS18" variante-b --api "$API" --lieu essai_b 2>&1 | tee "$TRAVAIL/journaux/variante_b.log"
[ "${PIPESTATUS[0]}" -eq 0 ] || echoue "variante B : $(grep 'ÉCHEC' "$TRAVAIL/journaux/variante_b.log" | tail -n 1)"
http POST /api/simulation/arreter > /dev/null || echoue "POST /api/simulation/arreter refusé"
restes || echoue "variante B : des processus restent après « Arrêter »"
reussi "repérage depuis le point principal, dérive corrigée, perte et reprise, repère tourné"
