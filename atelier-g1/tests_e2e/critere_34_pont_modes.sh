#!/usr/bin/env bash
# Critère 34, le pont : vitesse minimale et mode du robot (section 12.10 du plan, vague 5), sans
# fenêtre et sans robot. Montage : Gazebo --jumeau (le faux G1 avec son seuil de marche : comme le
# vrai G1 le 27/10, il ne fait aucun pas à 0,1 m/s), le relais simple du critère 17 (repéré), et le
# pont avec ses défauts (config/pont.yaml). On vérifie :
#   - vx 0,1 : 7105 à 0,2 (même direction), la vérité avance de 0,6 ± 0,2 m en 3 s ; /pont/etat
#     demande 0,1, consigne 0,2, minimums ; wz 0,15 seul : 0,3 ; vx 0,03 : rien, robot immobile ;
#   - faux G1 assis : pas_en_marche (« assis »), /cmd_vel ignoré ; « Démarrer » : pret sans
#     mouvement, puis un /cmd_vel neuf le fait avancer ; course (802) : pas_en_marche (« course ») ;
#   - 7001 à 1 Hz au format « {} », 7105 au format de 10.3, /pont/etat conforme tout du long ;
#   - refus : vitesse_max:=0.15 (lancement et g1-guide navigation --vitesse-max 0.15) avec « le
#     robot ne marche pas sous 0,2 m/s » ; vx_max:=0.1 sans vitesse_min_lin:=0 refusé par le pont ;
#     nav2_g1_reel.yaml : vx_min 0,0 ;
#   - avec vitesse_max:=0.25, les vitesses maximales de Nav2 lancé valent 0,25 (paramètres lus sur
#     les nœuds) ; aucun processus restant.
source "$(dirname "$0")/commun.sh"
OUTILS_PONT="$E2E/outils_pont_e2e.py"
OUTILS_ROBOT="$E2E/outils_robot_e2e.py"
exiger_commande g1-monde g1-guide
exiger_paquet_ros g1_sim g1_nav g1_bridge g1_jumeau
g1-monde simuler --help 2>/dev/null | grep -q -- --jumeau || en_attente "g1-monde simuler n'a pas l'option --jumeau"
PONT_YAML="$(ros2 pkg prefix g1_bridge)/share/g1_bridge/config/pont.yaml"
grep -q "vitesse_min_lin" "$PONT_YAML" || en_attente "le pont compilé ne connaît pas encore la vitesse minimale (recompilez g1_bridge)"

copier_demo essai
generer essai

dire "1. refus des réglages qui ne feraient faire aucun pas au robot"
sortie=$(g1-guide navigation --lieu essai --etage rdc --simu --localisation externe --pont oui --vitesse-max 0.15 2>&1)
code=$?
[ $code -ne 0 ] && echo "$sortie" | grep -q "le robot ne marche pas sous 0,2 m/s" \
  || echoue "g1-guide navigation --vitesse-max 0.15 aurait dû être refusé (code $code) : $sortie"
dire "   g1-guide navigation --vitesse-max 0.15 : refusé (code $code) : ${sortie:0:120}"
sortie=$(timeout 60 ros2 launch g1_nav navigation.launch.py lieu:=essai etage:=rdc simu:=true localisation:=externe pont:=true vitesse_max:=0.15 2>&1)
code=$?
echo "$sortie" | grep -q "le robot ne marche pas sous 0,2 m/s" && [ $code -ne 0 ] \
  || echoue "le lancement avec vitesse_max:=0.15 aurait dû être refusé (code $code) : $(echo "$sortie" | tail -n 3)"
dire "   ros2 launch … vitesse_max:=0.15 : refusé (code $code)"
sortie=$(timeout 30 ros2 run g1_bridge pont --ros-args -p vx_max:=0.1 2>&1)
code=$?
[ $code -eq 1 ] && echo "$sortie" | grep -q "vx_max 0,1 est sous la vitesse minimale" \
  || echoue "le pont avec vx_max:=0.1 aurait dû refuser de démarrer (code $code) : $(echo "$sortie" | tail -n 2)"
dire "   pont avec vx_max:=0.1 : refusé (code 1) : $(echo "$sortie" | grep -o 'vx_max 0,1 est sous[^;]*')"
REEL="$(ros2 pkg prefix g1_nav)/share/g1_nav/config/nav2_g1_reel.yaml"
"$PY" - "$REEL" <<'FIN' || echoue "nav2_g1_reel.yaml : la marche arrière est encore permise"
import sys, yaml
d = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
suivi = d["controller_server"]["ros__parameters"]["FollowPath"]
lisseur = d["velocity_smoother"]["ros__parameters"]
assert suivi["vx_min"] == 0.0 and lisseur["min_velocity"][0] == 0.0, (suivi["vx_min"], lisseur["min_velocity"])
print(f"   nav2_g1_reel.yaml : vx_min {suivi['vx_min']}, min_velocity {lisseur['min_velocity']}")
FIN

dire "2. Gazebo --jumeau, relais simple et pont avec ses défauts"
lancer_fond simulation g1-monde simuler --lieu essai --etage rdc --sans-fenetre --jumeau
"$PY" "$OUTILS" attendre-sujets /g1_jumeau/odom /g1_jumeau/etat /clock --delai 60 \
  || echoue "la simulation --jumeau ne publie pas /g1_jumeau/odom et /g1_jumeau/etat"
lancer_fond relais "$PY" "$OUTILS_PONT" relais-simple --lieu essai --etage rdc
lancer_fond pont ros2 run g1_bridge pont --ros-args --params-file "$PONT_YAML"
GROUPE_PONT=$DERNIER
"$PY" "$OUTILS" attendre-sujets /pont/etat /reperage/etat --delai 30 || echoue "le pont ou le relais ne publient pas"
sleep 2

dire "3. vitesse minimale et mode du robot, par /cmd_vel"
"$PY" "$OUTILS_ROBOT" pont-modes || echoue "vitesse minimale ou mode du robot : une vérification a échoué"
arreter_groupe "$GROUPE_PONT"

dire "4. vitesse_max:=0.25 : les vitesses maximales de Nav2 lancé"
lancer_fond navigation g1-guide navigation --lieu essai --etage rdc --simu --localisation externe --pont oui --vitesse-max 0.25
"$PY" "$OUTILS_PONT" attendre-nav2 --delai 120 || echoue "Nav2 ne devient pas actif"
vx=$(ros2 param get --no-daemon /controller_server FollowPath.vx_max 2>&1)
lisseur=$(ros2 param get --no-daemon /velocity_smoother max_velocity 2>&1)
pont=$(ros2 param get --no-daemon /pont_g1 vx_max 2>&1)
tolerance=$(ros2 param get --no-daemon /guide tolerance_orientation_rad 2>&1)
dire "   controller_server FollowPath.vx_max : $vx ; velocity_smoother max_velocity : $lisseur ; pont vx_max : $pont ; guide tolerance_orientation_rad : $tolerance"
echo "$vx" | grep -q "0.25" || echoue "FollowPath.vx_max de Nav2 ne vaut pas 0,25 : $vx"
echo "$lisseur" | grep -q "0.25" || echoue "max_velocity du velocity_smoother ne commence pas par 0,25 : $lisseur"
echo "$pont" | grep -q "0.25" || echoue "vx_max du pont ne vaut pas 0,25 : $pont"
echo "$tolerance" | grep -q "0.4" || echoue "tolerance_orientation_rad du guide ne vaut pas 0,4 avec le pont : $tolerance"

dire "5. arrêt de tout, aucun processus restant"
for (( i=${#GROUPES[@]}-1; i>=0; i-- )); do arreter_groupe "${GROUPES[$i]}"; done
sleep 2
"$PY" "$OUTILS_ROBOT" restes --lieux "$ATELIER_LIEUX" || echoue "des processus restent après l'arrêt"

reussi "vitesse minimale (0,1 → 0,2 m/s, 0,15 → 0,3 rad/s, zone morte), mode du robot (assis, Démarrer, course), refus sous 0,2 m/s, Nav2 à 0,25"
