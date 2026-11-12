# Environnement ROS 2 du conteneur g1-jetson (section 10.2 du plan).
# Chargé par demarrer.sh, et par « g1-jetson shell » et « g1-jetson etat » (docker exec), pour
# que tout ce qui tourne dans le conteneur parle sur les mêmes interfaces DDS.
# Pas de set -u : les scripts de ROS 2 ne le supportent pas.
source /opt/ros/humble/setup.bash
source /opt/g1/install/local_setup.bash
# Choix du réseau fait au démarrage par demarrer.sh : CYCLONEDDS_URI et interfaces retenues
[ -f /tmp/g1_reseau.sh ] && source /tmp/g1_reseau.sh
if [[ $- == *i* ]]; then
  PS1='g1-jetson \w \$ '
  echo "Conteneur g1-jetson : domaine ${ROS_DOMAIN_ID}, interfaces ${G1_INTERFACES_CHOISIES:-par défaut}."
  echo "Exemples : ros2 node list ; ros2 topic echo /pont/etat ; ros2 topic echo /reperage/etat"
fi
