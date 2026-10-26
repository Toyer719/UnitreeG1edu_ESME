#!/usr/bin/env bash
# Critère 24, passants en face et qui coupent la route (section 11.3 du plan, agent Passants).
# Scènes en_face et coupe_route, piétons en pire cas (reaction: aucune), 5 essais chacune : 0 contact
# causé par le robot sur les 10 essais, au moins 9 arrivées sur 10 à moins de 0,3 m en moins de 180 s ;
# les contacts causés par le piéton sont comptés et affichés. Puis les mêmes scènes avec
# reaction: ecart : 0 contact de toute sorte.
source "$(dirname "$0")/commun.sh"
exiger_commande g1-banc g1-monde g1-guide
exiger_paquet_ros g1_sim g1_nav
OUTILS_P="$E2E/outils_passants_e2e.py"
copier_demo demo
for reaction in aucune ecart; do
  for scene in en_face coupe_route; do
    dire "scène $scene, reaction: $reaction"
    g1-banc --scene "$scene" --reaction "$reaction" --travail "$TRAVAIL/banc" \
      --csv "$TRAVAIL/${scene}_${reaction}.csv" 2>&1 | tee "$TRAVAIL/journaux/banc_${scene}_${reaction}.log"
    [ -s "$TRAVAIL/${scene}_${reaction}.csv" ] || echoue "g1-banc ($scene, $reaction) n'a pas produit de CSV"
  done
done
dire "pire cas (reaction: aucune), 10 essais :"
"$PY" "$OUTILS_P" verifier "$TRAVAIL/en_face_aucune.csv" "$TRAVAIL/coupe_route_aucune.csv" --essais 10 \
  --arrivees-min 9 --duree-max 180 --contacts-robot-max 0 \
  || echoue "pire cas : un contact causé par le robot, ou moins de 9 arrivées sur 10"
dire "piétons qui s'écartent (reaction: ecart), 10 essais :"
"$PY" "$OUTILS_P" verifier "$TRAVAIL/en_face_ecart.csv" "$TRAVAIL/coupe_route_ecart.csv" --essais 10 \
  --contacts-max 0 || echoue "reaction: ecart : au moins un contact"
reussi "0 contact causé par le robot en pire cas, 0 contact avec des piétons qui s'écartent"
