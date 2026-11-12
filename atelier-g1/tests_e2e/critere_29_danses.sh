#!/usr/bin/env bash
# Critère 29, danses du robot et chorégraphies (sections 7 et 11.5 du plan), sans fenêtre et sans robot.
# Même montage que le critère 28 (Atelier, répétition, repérage, nœud pilotage sur le PC). On vérifie
# (outils : tests_e2e/outils_pilotage_e2e.py critere-29) :
#   - la liste des danses est lue (7100) et montrée, 401, 402 et 403 marquées interdites ;
#   - danse 604 avec la « zone libre » confirmée → le faux G1 reçoit 7101 {"data": 550604} ; sans
#     confirmation : refus ; 401, 402 et 403 refusées même confirmées, rien d'envoyé ; pendant la
#     danse, joystick refusé ; à la fin, mode 501 (la marche du vrai G1) ; ARRÊT pendant la danse : StopMove, rien d'autre ;
#   - exemple_kpop jouée (zone libre) : rt/arm_sdk à 50 Hz ± 10 %, rampes du poids de 1 s au moins,
#     aucun angle hors de LIMITES_BRAS, aucune vitesse au-delà de VITESSE_BRAS_MAX, taille et jambes
#     jamais pilotées, pas sous LIMITES_PAS et robot à 1 m au plus de son départ (vérité), LED et
#     paroles à leur temps (± 0,2 s) ; ARRÊT au milieu : poids à 0 en moins de 1,5 s, StopMove ;
#   - une chorégraphie hors limites est refusée avant de jouer, avec ses erreurs en français ;
#   - l'onglet Pilotage dans Firefox sans fenêtre : l'aperçu 3D de exemple_kpop se charge et avance
#     (images dessinées), sans erreur dans la page (atelier/tests/test_pilotage_navigateur.py) ;
#   - aucun processus restant.
source "$(dirname "$0")/commun.sh"
exiger_commande g1-monde g1-guide g1-atelier g1-slam g1-pilotage
exiger_paquet_ros g1_sim g1_nav g1_bridge g1_jumeau g1_pilotage unitree_api unitree_hg
python3 -c "import g1_jumeau.robot" 2>/dev/null \
  || en_attente "le faux G1 n'est pas encore étendu aux danses et à rt/arm_sdk (g1_jumeau.robot)"
OUTILS_PILOTAGE="$E2E/outils_pilotage_e2e.py"
OUTILS18="$E2E/critere_18_outils.py"

PORT_PILOTAGE=$("$PY" -c "import socket; s = socket.socket(); s.bind(('127.0.0.1', 0)); print(s.getsockname()[1])")
export G1_PILOTAGE_URL="http://127.0.0.1:$PORT_PILOTAGE"
export G1_PILOTAGE_JETON="jeton-e2e-$$-$RANDOM"
export ATELIER_CHOREGRAPHIES="$TRAVAIL/choregraphies"
mkdir -p "$ATELIER_CHOREGRAPHIES/musique"
cp "$RACINE/choregraphies/exemple_kpop.choregraphie.yaml" "$ATELIER_CHOREGRAPHIES/"

copier_demo essai
generer essai
serveur

"$PY" "$OUTILS_PILOTAGE" critere-29 --api "$API" --lieu essai --choregraphies "$ATELIER_CHOREGRAPHIES" 2>&1 \
  | tee "$TRAVAIL/journaux/critere_29.log"
code=${PIPESTATUS[0]}
http POST /api/pilotage/arreter > /dev/null
http POST /api/simulation/arreter > /dev/null || echoue "POST /api/simulation/arreter refusé"
serveur_pid=$(pgrep -f "uvicorn atelier.serveur.main:app .*--port $PORT" | tr '\n' ' ')
sleep 2
"$PY" "$OUTILS18" restes --lieux "$ATELIER_LIEUX" --sauf $serveur_pid || echoue "des processus restent après « Arrêter »"
[ "$code" -eq 0 ] || echoue "$(grep 'ÉCHEC' "$TRAVAIL/journaux/critere_29.log" | tail -n 1)"

dire "onglet Pilotage dans Firefox sans fenêtre (aperçu 3D de exemple_kpop)"
command -v geckodriver > /dev/null && command -v firefox > /dev/null \
  || en_attente "geckodriver ou Firefox absent : l'aperçu 3D dans le navigateur n'est pas vérifié"
(cd "$RACINE" && "$PY" -m pytest -q -p no:cacheprovider atelier/tests/test_pilotage_navigateur.py) \
  > "$TRAVAIL/journaux/navigateur.log" 2>&1 || echoue "onglet Pilotage dans Firefox : $(tail -n 5 "$TRAVAIL/journaux/navigateur.log" | tr '\n' ' ')"
grep -q "1 passed" "$TRAVAIL/journaux/navigateur.log" || echoue "le test de l'onglet Pilotage a été sauté : $(tail -n 2 "$TRAVAIL/journaux/navigateur.log" | tr '\n' ' ')"
dire "aperçu 3D chargé et animé dans Firefox sans fenêtre, sans erreur dans la page"
reussi "danses (liste, interdits, zone libre, ARRÊT) et chorégraphie exemple_kpop (rt/arm_sdk vérifié, pas, LED, paroles)"
