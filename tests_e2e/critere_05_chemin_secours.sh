#!/usr/bin/env bash
# Critère 5, chemin de secours : une boîte posée dans un couloir (absente de la carte) donne
# « bloque » → « detour » → « arrive », par l'autre couloir.
source "$(dirname "$0")/commun.sh"
exiger_commande g1-monde g1-guide
exiger_paquet_ros g1_sim g1_nav
copier_demo essai
sans_pieton_nord essai
generer essai
simuler essai
lancer_fond navigation g1-guide navigation --lieu essai --etage rdc --simu
"$PY" "$OUTILS" attendre-sujets /guide/etat --delai 90 || echoue "le guide ne publie pas /guide/etat"
sleep 5

# La boîte bloque le couloir nord entre amphi et couloir_nord_1 (journal de l'intégrateur)
BOITE='<sdf version="1.9"><model name="boite_e2e"><static>true</static><link name="l">
<collision name="c"><geometry><box><size>0.5 2.9 1.2</size></box></geometry></collision>
<visual name="v"><geometry><box><size>0.5 2.9 1.2</size></box></geometry></visual></link></model></sdf>'
ros2 run ros_gz_sim create -string "$BOITE" -name boite_e2e -x 12 -y 13 -z 0.6 > "$TRAVAIL/journaux/boite.log" 2>&1 \
  || echoue "impossible de poser la boîte dans Gazebo"
dire "boîte posée en (12 ; 13)"
"$PY" "$OUTILS" etat-guide --cible b204 --attendre arrive --suite bloque,detour,arrive --delai 420 \
  || echoue "pas de « bloque → detour → arrive »"
"$PY" "$OUTILS" pres-de --lieu essai --salle b204 --max 0.3 || echoue "le robot n'est pas devant b204"
reussi "bloque → detour → arrive"
