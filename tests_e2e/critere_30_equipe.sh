#!/usr/bin/env bash
# Critère 30, équipe (sections 7 et 11.6 du plan), sans fenêtre ni robot, sur des copies du demo :
#   1. fichiers : les exemples de personnalites.yaml, dialogues.yaml et camera.yaml sont valides,
#      trois fautes de chacun sont refusées (422) en français, puis chacun est écrit et relu par
#      l'API ; trois phrases s'essaient sans robot ;
#   2. onglets : Personnalités, Dialogues et Caméra s'ouvrent dans Firefox sans fenêtre ; une
#      personnalité choisie part sur /personnalite/active ; une phrase s'essaie dans l'onglet
#      Dialogues (atelier/tests/test_equipe_navigateur.py) ;
#   3. bout en bout en simulation (Gazebo, navigation, nœud dialogue de g1_equipe) : « bonjour »
#      → une réponse, sans guidage ; une phrase inconnue → le repli ; « je cherche la salle b204 »
#      sur /visiteur/texte → /robot/dire (en français, conforme) et /guide/aller en JSON vers b204
#      → arrive à moins de 0,3 m (vérité : /odom) ;
#   4. aucun processus restant.
# La copie du bout en bout n'a pas de piétons : l'accompagnement du guide (vague 4) prendrait un
# piéton qui passe près de l'accueil pour le visiteur ; ce critère vérifie la chaîne de l'équipe.
source "$(dirname "$0")/commun.sh"
exiger_commande g1-atelier g1-monde g1-guide
exiger_paquet_ros g1_sim g1_nav g1_equipe
ros2 pkg executables g1_equipe 2>/dev/null | grep -q "dialogue" \
  || en_attente "le paquet g1_equipe n'a pas d'exécutable dialogue"
OUTILS30="$E2E/outils_equipe_e2e.py"

# restes : plus aucun processus lancé avec nos lieux
restes() {
  sleep 2
  "$PY" "$OUTILS30" restes --lieux "$ATELIER_LIEUX" "$@"
}

# 1. Fichiers de l'équipe, par l'API, sur une copie du demo
copier_demo essai
serveur
"$PY" "$OUTILS30" fichiers --api "$API" --lieu essai 2>&1 | tee "$TRAVAIL/journaux/fichiers.log"
[ "${PIPESTATUS[0]}" -eq 0 ] || echoue "fichiers : $(grep 'ÉCHEC' "$TRAVAIL/journaux/fichiers.log" | tail -n 1)"

# 2. Les onglets dans Firefox sans fenêtre (son propre serveur, ses propres copies)
TEST="$RACINE/atelier/tests/test_equipe_navigateur.py"
SORTIE=$(cd "$RACINE" && "$PY" -m pytest -q -rs -p no:cacheprovider "$TEST" 2>&1); CODE=$?
echo "$SORTIE" | tail -n 6
if echo "$SORTIE" | grep -qE "[0-9]+ skipped" && ! echo "$SORTIE" | grep -qE "[0-9]+ passed"; then
  echoue "le test des onglets dans Firefox a été sauté (geckodriver, Firefox ou ROS 2 absents)"
fi
[ $CODE -eq 0 ] || echoue "onglets Personnalités, Dialogues et Caméra dans Firefox : échec"
dire "onglets Personnalités, Dialogues et Caméra : parcours réussi dans Firefox sans fenêtre"

# 3. Bout en bout en simulation, sur une copie sans piétons
copier_demo equipe
"$PY" - "$ATELIER_LIEUX/equipe" <<'PYTHON' || echoue "piétons non retirés de la copie"
import sys
from atelier.lieu import charger_monde, enregistrer_monde
monde = charger_monde(sys.argv[1], "rdc")
monde.pietons = []
enregistrer_monde(sys.argv[1], "rdc", monde)
print("copie sans piétons : equipe")
PYTHON
generer equipe
http POST /api/simulation/demarrer '{"lieu": "equipe", "etage": "rdc"}' > "$TRAVAIL/journaux/demarrer.log" \
  || echoue "POST /api/simulation/demarrer refusé : $(cat "$TRAVAIL/journaux/demarrer.log")"
"$PY" "$OUTILS" attendre-sujets /odom /points /guide/etat --delai 90 || echoue "simulation ou guide absents"
lancer_fond dialogue ros2 run g1_equipe dialogue --ros-args -p "lieu:=$ATELIER_LIEUX/equipe" -p etage:=rdc
DIALOGUE=$DERNIER
"$PY" "$OUTILS30" bout-en-bout --api "$API" --lieu equipe --delai 240 2>&1 | tee "$TRAVAIL/journaux/bout_en_bout.log"
[ "${PIPESTATUS[0]}" -eq 0 ] || echoue "bout en bout : $(grep 'ÉCHEC' "$TRAVAIL/journaux/bout_en_bout.log" | tail -n 1)"
grep "→" "$TRAVAIL/journaux/dialogue.log" | sed 's/^/  nœud dialogue : /'

# 4. Tout s'arrête : la navigation et Gazebo (« Arrêter »), le nœud dialogue, le serveur
http POST /api/simulation/arreter > /dev/null || echoue "POST /api/simulation/arreter refusé"
arreter_groupe "$DIALOGUE"
SERVEUR_PID=$(pgrep -f "uvicorn atelier.serveur.main:app .*--port $PORT" | tr '\n' ' ')
restes --sauf $SERVEUR_PID || echoue "des processus restent après « Arrêter » et l'arrêt du nœud dialogue"
for p in "${GROUPES[@]}"; do arreter_groupe "$p"; done
restes || echoue "des processus restent après l'arrêt du serveur"
reussi "fichiers, onglets et bout en bout de l'équipe (« je cherche la salle b204 » → b204)"
