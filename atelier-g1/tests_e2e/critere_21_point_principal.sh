#!/usr/bin/env bash
# Critère 21, le point principal (sections 7 et 11.2 du plan), sur des copies du demo :
#   A. données et API : un lieu sans point principal (g1-lieu valider en erreur, simulation 409) ; deux
#      principaux (PUT …/salles 422) ; g1-lieu migrer (sauvegarde identique, étiquette, aucune erreur,
#      second passage sans effet) ; g1-lieu migrer de lieux/demo refusé, lieux/demo inchangé ; un lieu
#      migré dont PUT …/salles perdrait le principal (422) ; PUT …/principal {theta: 1.5708} → salles.yaml,
#      accueil et depart_robot, GET ; puis le principal déplacé en (2,5 ; 11,0 ; 1,5708) ;
#   B. la simulation part du principal : première pose de /odom à moins de 0,05 m et 0,05 rad ;
#   C. le repérage part du principal (répétition) : /reperage/demander porte sa pose, 1804 reçoit
#      carte_vers_unitree(principal, repere_unitree), robot repéré, TF à moins de 0,1 m de la vérité ;
#      de même avec repere_unitree (3 ; 9 ; 0,5) dans la copie ;
#   plus aucun processus à la fin. Sans fenêtre ; jamais le vrai robot (G1_SLAM_FAUX=1).
source "$(dirname "$0")/commun.sh"
exiger_commande g1-lieu g1-monde g1-guide g1-atelier g1-slam
exiger_paquet_ros g1_sim g1_nav g1_bridge g1_jumeau unitree_api
grep -q "jumeau" "$(ros2 pkg prefix g1_sim)/share/g1_sim/launch/simulation.launch.py" \
  || en_attente "g1_sim n'a pas encore l'argument jumeau (agent Pont et faux G1)"
"$PY" -c "from atelier.lieu.principal import migrer_lieu, definir_principal" 2>/dev/null \
  || en_attente "atelier.lieu.principal n'a pas encore definir_principal ni migrer_lieu"
OUTILS21="$E2E/critere_21_outils.py"

restes() {
  local serveur_pid
  serveur_pid=$(pgrep -f "uvicorn atelier.serveur.main:app .*--port $PORT" | tr '\n' ' ')
  sleep 2
  "$PY" "$OUTILS21" restes --lieux "$ATELIER_LIEUX" --sauf $serveur_pid
}

etape() {          # etape NOM COMMANDE... : lance un outil, journal dans $TRAVAIL/journaux/NOM.log
  local nom="$1"; shift
  "$@" 2>&1 | tee "$TRAVAIL/journaux/$nom.log"
  [ "${PIPESTATUS[0]}" -eq 0 ] || echoue "$nom : $(grep 'ÉCHEC' "$TRAVAIL/journaux/$nom.log" | tail -n 1)"
}

# A. données et API
copier_demo sans
copier_demo essai
serveur
etape donnees "$PY" "$OUTILS21" donnees --api "$API" --lieux "$ATELIER_LIEUX" --reference "$RACINE/lieux/demo"

# B. la simulation part du point principal (déplacé et tourné en A)
generer essai
etape depart "$PY" "$OUTILS21" depart-simulation --api "$API" --lieu essai
restes || echoue "simulation : des processus restent après « Arrêter »"

# C. le repérage part du point principal : repère d'Unitree implicite (le départ, donc le principal)
etape reperage_a "$PY" "$OUTILS21" reperage --api "$API" --lieu essai
http POST /api/simulation/arreter > /dev/null || echoue "POST /api/simulation/arreter refusé"
restes || echoue "repérage : des processus restent après « Arrêter »"

#    … puis repère d'Unitree tourné (3 ; 9 ; 0,5), sur une copie du lieu migré et déplacé
rm -rf "$ATELIER_LIEUX/essai_b"
cp -r "$ATELIER_LIEUX/essai" "$ATELIER_LIEUX/essai_b"
"$PY" - "$ATELIER_LIEUX/essai_b" <<'PYTHON' || echoue "repere_unitree de essai_b non écrit"
import sys
from atelier.lieu import Pose, charger_fiche, enregistrer_fiche
fiche = charger_fiche(sys.argv[1])
fiche.etages[0].repere_unitree = Pose(3.0, 9.0, 0.5)
enregistrer_fiche(fiche)
print("repere_unitree de essai_b : (3 ; 9 ; 0,5)")
PYTHON
etape reperage_b "$PY" "$OUTILS21" reperage --api "$API" --lieu essai_b
http POST /api/simulation/arreter > /dev/null || echoue "POST /api/simulation/arreter refusé"
restes || echoue "repérage (repère tourné) : des processus restent après « Arrêter »"
reussi "principal unique et obligatoire, migration sûre, orientation, départ de la simulation et repérage"
