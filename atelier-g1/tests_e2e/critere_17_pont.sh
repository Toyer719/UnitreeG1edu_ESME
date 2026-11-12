#!/usr/bin/env bash
# Critère 17, pont et faux G1 (section 7 et 10 du plan), sans fenêtre et sans robot.
# Montage de la répétition : Gazebo --jumeau (avec le faux G1 g1_jumeau), navigation
# --simu --localisation externe --pont oui (Nav2 et le pont g1_bridge), et le relais simple du
# test (TF tiré de la vérité terrain /g1_jumeau/odom, /reperage/etat repéré). On vérifie :
#   - aucun lien direct entre /cmd_vel et Gazebo ;
#   - Nav2 → pont → faux G1 → Gazebo : g1-guide aller hall_sud, arrivée à moins de 0,3 m,
#     requêtes 7105 au bon format, identity.id croissants, 8 par seconde au moins, toutes répondues ;
#     vague 5 (section 12.6) : les seules autres requêtes sont les lectures du mode du pont (7001,
#     « {} », une par seconde, de 0,7 à 1,3) ;
#   - /cmd_vel du test : 0,9 m en 3 s, arrêt moins de 0,6 s après, 7105 [0, 0, 0] envoyé ;
#   - plafonds (0,4 ; 0,25 ; 0,6) et NaN ; /guide/stop (0,3 s, garde de 1 s) ;
#     /pont/arret (0,3 s, immobile 3 s, reprise seulement au /cmd_vel suivant) ;
#   - /pont/etat conforme au schéma tout du long.
# E2E_PONT_REPLI=1 : si navigation.launch.py ne connaît pas encore localisation:=externe, monte
# à la place la navigation de la vague 1 (--simu), le pont lancé à part et le relais sans map → odom.
source "$(dirname "$0")/commun.sh"
OUTILS_PONT="$E2E/outils_pont_e2e.py"
exiger_commande g1-monde g1-guide
exiger_paquet_ros g1_sim g1_nav g1_bridge g1_jumeau
g1-monde simuler --help 2>/dev/null | grep -q -- --jumeau || en_attente "g1-monde simuler n'a pas l'option --jumeau"

REPLI=""
if ! ros2 launch g1_nav navigation.launch.py --show-args 2>/dev/null | grep -q "'localisation'"; then
  [ "$E2E_PONT_REPLI" = "1" ] || en_attente "navigation.launch.py ne connaît pas encore localisation:=externe (agent Repérage) ; E2E_PONT_REPLI=1 pour le montage de repli"
  REPLI=1
  dire "montage de repli : navigation de la vague 1, pont lancé à part"
fi

copier_demo essai
generer essai

# Gazebo et le faux G1
lancer_fond simulation g1-monde simuler --lieu essai --etage rdc --sans-fenetre --jumeau
"$PY" "$OUTILS" attendre-sujets /g1_jumeau/odom /g1_jumeau/points /g1_jumeau/etat /clock --delai 60 \
  || echoue "la simulation --jumeau ne publie pas /g1_jumeau/odom, /g1_jumeau/points et /g1_jumeau/etat"

# Relais simple (localisation externe), puis la navigation avec le pont
if [ -n "$REPLI" ]; then
  lancer_fond relais "$PY" "$OUTILS_PONT" relais-simple --lieu essai --etage rdc --sans-map-odom
  lancer_fond navigation g1-guide navigation --lieu essai --etage rdc --simu
  lancer_fond pont ros2 run g1_bridge pont --ros-args --params-file "$(ros2 pkg prefix g1_bridge)/share/g1_bridge/config/pont.yaml"
else
  lancer_fond relais "$PY" "$OUTILS_PONT" relais-simple --lieu essai --etage rdc
  lancer_fond navigation g1-guide navigation --lieu essai --etage rdc --simu --localisation externe --pont oui
fi
"$PY" "$OUTILS" attendre-sujets /pont/etat /guide/etat /reperage/etat /odom /points --delai 90 \
  || echoue "le pont, le guide ou le relais ne publient pas"
"$PY" "$OUTILS_PONT" attendre-nav2 --delai 120 || echoue "Nav2 ne devient pas actif"
sleep 3

dire "1. aucun lien direct entre /cmd_vel et Gazebo"
"$PY" "$OUTILS_PONT" liens || echoue "lien direct entre /cmd_vel et Gazebo, ou faux G1 absent"

dire "2. Nav2 → pont → faux G1 → Gazebo : g1-guide aller hall_sud"
"$PY" "$OUTILS_PONT" navigation --lieu essai --cible hall_sud --delai 240 \
  || echoue "la navigation par le pont et le faux G1 n'a pas tenu ses promesses"

dire "3 à 6. /cmd_vel du test, plafonds, NaN, /guide/stop, /pont/arret"
"$PY" "$OUTILS_PONT" essais-directs || echoue "un essai par /cmd_vel a échoué"

dire "7. arrêt de la navigation (le pont envoie un arrêt en quittant)"
arreter_groupe "${GROUPES[-1]}"
[ -n "$REPLI" ] && arreter_groupe "${GROUPES[-2]}"
grep -q "arrêt envoyé (sortie)" "$TRAVAIL/journaux/"{navigation,pont}.log 2>/dev/null \
  || echoue "le pont n'a pas envoyé d'arrêt en quittant"

reussi "Nav2, pont, faux G1 et Gazebo de bout en bout ; arrêts, plafonds et verrou vérifiés${REPLI:+ (montage de repli)}"
