#!/usr/bin/env bash
# Critère 26, accompagnement (sections 7 et 11.4 du plan, agent Comportement du guide).
# Simulation, scène accompagnement (atelier/monde/scenes/accompagnement.scene.yaml : faux visiteur
# 1 m derrière le robot au principal, delai_visiteur_s: 10), /guide/aller {"cible": "b204",
# "accompagner": true} :
#   - événement depart (et non seul) ; visiteur « suivre » : le robot va à sa vitesse normale ;
#   - « trainer » : /speed_limit publié, robot à 60 % au plus de sa vitesse d'avant, puis
#     attente_visiteur (robot à moins de 2 cm/s) quand le visiteur est à plus de 3,5 m ;
#   - « suivre » de nouveau : visiteur_retrouve, reprise, arrive à moins de 0,3 m ;
#   - second essai, « partir » : attente_visiteur, puis visiteur_perdu 10 s après (± 2 s), puis
#     retour et attente au principal (0,3 m, 10°) ; événements en français, conformes.
# Le visiteur est un piéton « pilote: externe » de l'agent Passants (nœud pietons de g1_sim) :
# sans lui, le critère est « en attente » (77).
source "$(dirname "$0")/commun.sh"
exiger_commande g1-monde g1-guide g1-atelier
exiger_paquet_ros g1_sim g1_nav
OUTILS_GUIDE="$E2E/outils_guide_e2e.py"
LANCEMENT_SIM="$(ros2 pkg prefix g1_sim)/share/g1_sim/launch/simulation.launch.py"
grep -q "pietons" "$LANCEMENT_SIM" \
  || en_attente "g1_sim n'a pas encore les piétons crédibles (argument pietons, nœud pietons : agent Passants)"
copier_demo essai
"$PY" "$OUTILS_GUIDE" preparer --lieu essai --scene accompagnement \
  || echoue "la scène accompagnement ne s'applique pas à la copie"
generer essai
serveur
lancer_fond faux_visiteur "$PY" -m g1_nav.faux_visiteur --ros-args -p visiteur:=visiteur -p verite:=/odom \
  -p lieu:="$ATELIER_LIEUX/essai" -p etage:=rdc -p use_sim_time:=true -p mode:=suivre

"$PY" "$OUTILS_GUIDE" accompagnement --api "$API" --lieu essai 2>&1 | tee "$TRAVAIL/journaux/accompagnement.log"
CODE=${PIPESTATUS[0]}
[ "$CODE" -eq 77 ] && en_attente "$(grep 'EN ATTENTE' "$TRAVAIL/journaux/accompagnement.log" | tail -n 1)"
[ "$CODE" -eq 0 ] || echoue "$(grep 'ÉCHEC' "$TRAVAIL/journaux/accompagnement.log" | tail -n 1)"

http POST /api/simulation/arreter > /dev/null || echoue "POST /api/simulation/arreter refusé"
reussi "accompagnement : suivre, traîner (ralenti, attente), revenir (arrivée), partir (abandon, retour)"
