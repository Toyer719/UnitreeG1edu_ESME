#!/usr/bin/env bash
# Critère 37, « Vérifier le robot » (section 13.9 du plan, vague 6) : agent Diagnostic. Sans robot et sans fenêtre.
# Montage : le faux G1 seul (ros2 run g1_jumeau jumeau, services_arretes:=lidar_driver,unitree_slam), le complément
# du graphe du robot (/lf/sportmodestate publié, /api/slam_operate/request écouté : outils_diagnostic_e2e.py
# complement-robot), l'Atelier, et les vérifications système simulées (ATELIER_DIAGNOSTIC_FAUX, un fichier par cas,
# copié avant chaque demande). On vérifie (outils : tests_e2e/outils_diagnostic_e2e.py critere-37) :
#   - GET /api/robot/diagnostic?mode=repetition en moins de 15 s, conforme au schéma et à ses règles ; services en
#     probleme avec l'action demarrer-services ; le faux G1 a reçu 1003 avec {} ; réseau et Jetson dans ignorees ;
#   - l'action sans confirme : 409 et aucun 1001 ; avec : exactement deux 1001 {"name": "lidar_driver", "switch": 1}
#     et {"name": "unitree_slam", "switch": 1}, aucun interdit (ni switch 0, ni autre service), services actifs en
#     moins de 20 s, services ok au diagnostic suivant ;
#   - Réel avec le faux contexte : câble absent → cable en probleme avec un conseil ; connexion éteinte → profil avec
#     l'action retablir-cable, puis l'action confirmée « lance » nmcli connection up robot-g1 (noté dans
#     <fichier>.journal, rien de réel) ; tout bon (et services actifs) → état ok ;
#   - g1-diagnostic --json (même faux contexte) : mêmes ids et mêmes états que la route ; code 1 avec un problème,
#     0 quand tout va bien ;
#   - Firefox sans fenêtre : accueil Réel avec « Répétition », [data-role=verifier-robot] → [data-role=diagnostic]
#     montre services en probleme ; [data-action=demarrer-services] demande confirmation dans la page, puis les
#     services démarrent ; le bouton de la barre d'outils marche ; window.erreursAtelier vide.
# Jamais de son, de ssh, de ping ni de commande vers le vrai robot ; aucun processus restant.
source "$(dirname "$0")/commun.sh"
OUTILS_DIAG="$E2E/outils_diagnostic_e2e.py"
exiger_commande g1-atelier g1-diagnostic
exiger_paquet_ros g1_jumeau
"$PY" -c "from atelier.diagnostic import diagnostiquer, faire_action" 2>/dev/null \
  || en_attente "le paquet atelier.diagnostic n'est pas encore écrit"
grep -q "switchs" "$RACINE/ws/src/g1_jumeau/g1_jumeau/etat_robot.py" \
  || en_attente "le faux G1 n'a pas encore le service robot_state de la vague 6 (etat_robot.py)"
command -v geckodriver > /dev/null && command -v firefox > /dev/null \
  || en_attente "Firefox sans fenêtre (firefox et geckodriver) n'est pas installé"

copier_demo demo
export ATELIER_DIAGNOSTIC_FAUX="$TRAVAIL/faux.json"
echo '{}' > "$ATELIER_DIAGNOSTIC_FAUX"

lancer_fond faux_g1 ros2 run g1_jumeau jumeau --ros-args -p services_arretes:=lidar_driver,unitree_slam
lancer_fond complement "$PY" "$OUTILS_DIAG" complement-robot
"$PY" "$OUTILS" attendre-sujets /g1_jumeau/etat --delai 30 || echoue "le faux G1 ne publie pas /g1_jumeau/etat"
serveur
dire "faux G1, complément du robot et Atelier sur $API (domaine $ROS_DOMAIN_ID)"

cd "$RACINE" || exit 1
"$PY" "$OUTILS_DIAG" critere-37 --api "$API" --faux "$ATELIER_DIAGNOSTIC_FAUX" --cas "$TRAVAIL/cas" 2>&1 \
  | tee "$TRAVAIL/journaux/critere_37.log"
CODE=${PIPESTATUS[0]}
[ $CODE -eq 77 ] && en_attente "une pièce manque"
[ $CODE -eq 0 ] || echoue "$(grep -E '^ÉCHEC' "$TRAVAIL/journaux/critere_37.log" | tail -n 1 | cut -c1-600)"
reussi "diagnostic en répétition et en Réel (faux contexte), liste blanche des services, câble, g1-diagnostic, fenêtre dans Firefox"
