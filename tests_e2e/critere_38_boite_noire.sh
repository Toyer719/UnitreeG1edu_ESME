#!/usr/bin/env bash
# Critère 38, la boîte noire et le rapport de séance (section 13.9 du plan) : agent Boîte noire. Sans robot, sans
# fenêtre. $ATELIER_SEANCES et $ATELIER_BIN dans le dossier du test ($ATELIER_BIN : les vraies commandes g1-*, sauf
# un faux g1-jetson). Outils : tests_e2e/outils_seance_e2e.py ; le niveau 2 réutilise critere_18_outils.py et
# critere_19_outils.py sans les modifier.
#   1. Atelier A : POST /api/seance/demarrer {mode: repetition, ouverture: auto} : dossier, seance.json conforme
#      (ouverte), lieu/, l'enregistreur en route ; /ws/etat a seance ; Firefox : le badge [data-role=seance] ;
#      répétition par l'Atelier (Gazebo --jumeau, faux slam_operate, navigation), repérage ; « Y aller » b204
#      (l'enregistreur prend moins de 15 % d'un cœur pendant le trajet), « Y aller » CDI, ARRÊT en route (moins de
#      1 s), « Débloquer », « Y aller » accueil ; un /cmd_vel du test hors de toute demande (5 s) ;
#      « Terminer la séance » : le bag (ros2 bag info : guide, pont, repérage, requêtes sport, /cmd_vel ; ni nuage ni
#      image ; odométrie du robot à 10 Hz au plus), le journal des actions conforme, le rapport en moins de 60 s
#      (trajets arrivé et interrompu par l'ARRÊT, distance, arrêt d'urgence, batterie, mouvement sans demande) ;
#   2. le journal du conteneur du Jetson avant « g1-jetson arreter » (faux g1-jetson, mode robot posé à la main) ;
#   3. Atelier B avec ATELIER_SEANCE_PLACE_MIN_GO énorme : enregistrement coupé, séance ouverte, actions notées ;
#   4. Atelier C : une séance, puis SIGKILL de l'Atelier : l'enregistreur ferme son bag seul ; Atelier D relancé : la
#      séance est interrompue, son bag se lit, son rapport existe, aucune séance nouvelle ;
#   5. g1-seance exporter et liste ; aucun processus restant ; jamais d'erreur 500.
source "$(dirname "$0")/commun.sh"
exiger_commande g1-monde g1-guide g1-atelier g1-slam g1-seance
exiger_paquet_ros g1_sim g1_nav g1_bridge g1_jumeau unitree_api unitree_hg
"$PY" -c "import rosbag2_py" 2>/dev/null || en_attente "rosbag2_py introuvable (ros-humble-rosbag2-py)"
"$PY" -c "import websockets.sync.client" 2>/dev/null || en_attente "le module websockets manque dans .venv-projet"
OUTILS38="$E2E/outils_seance_e2e.py"
OUTILS18="$E2E/critere_18_outils.py"
export ATELIER_SEANCES="$TRAVAIL/seances"

# ATELIER_BIN : les vraies commandes, et un faux g1-jetson qui note ses appels
mkdir -p "$TRAVAIL/bin"
for c in "$RACINE"/bin/g1-*; do
  [ "$(basename "$c")" = g1-jetson ] || ln -s "$c" "$TRAVAIL/bin/$(basename "$c")"
done
cat > "$TRAVAIL/bin/g1-jetson" <<SCRIPT
#!/bin/bash
echo "\$*" >> "$TRAVAIL/jetson.txt"
case "\$1" in
  journal) echo "[INFO] [pont_g1]: journal du conteneur (faux g1-jetson du critère 38)"; echo "[ERROR] [guide]: essai" ;;
  arreter) echo "conteneur arrêté (faux)" ;;
esac
exit 0
SCRIPT
chmod +x "$TRAVAIL/bin/g1-jetson"
export ATELIER_BIN="$TRAVAIL/bin"

port_libre() { "$PY" -c "import socket; s = socket.socket(); s.bind(('127.0.0.1', 0)); print(s.getsockname()[1])"; }
# atelier NOM [VARIABLE=VALEUR...] : lance g1-atelier sur un port libre ; $API, $PORT et $GROUPE_ATELIER
atelier() {
  local nom="$1"; shift
  PORT=$(port_libre)
  lancer_fond "$nom" env "$@" g1-atelier --port "$PORT" --sans-navigateur
  GROUPE_ATELIER=$DERNIER
  API="http://127.0.0.1:$PORT"
  "$PY" "$OUTILS" attendre-http "$API/api/lieux" --delai 30 || echoue "l'Atelier $nom ne répond pas"
}
pid_uvicorn() { pgrep -f "uvicorn atelier.serveur.main:app .*--port $1" | head -n 1; }

copier_demo essai
sans_pieton_nord essai
generer essai
cd "$RACINE" || exit 1

# 1. la séance principale
atelier atelier_a
"$PY" "$OUTILS38" principal --api "$API" --lieu essai --seances "$ATELIER_SEANCES" 2>&1 | tee "$TRAVAIL/journaux/principal.log"
code=${PIPESTATUS[0]}
[ "$code" = 77 ] && en_attente "$(grep 'EN ATTENTE' "$TRAVAIL/journaux/principal.log" | tail -n 1)"
[ "$code" = 0 ] || echoue "$(grep -E 'ÉCHEC|Error|Traceback' "$TRAVAIL/journaux/principal.log" | tail -n 1 | cut -c1-500)"
SEANCE=$(grep '^SEANCE ' "$TRAVAIL/journaux/principal.log" | tail -n 1 | cut -d' ' -f2)
# la séance principale est gardée pour être regardée (E2E_GARDER_RAPPORT=DOSSIER)
if [ -n "$E2E_GARDER_RAPPORT" ]; then
  mkdir -p "$E2E_GARDER_RAPPORT" && cp -r "$ATELIER_SEANCES/$SEANCE" "$E2E_GARDER_RAPPORT/" \
    && dire "séance $SEANCE copiée dans $E2E_GARDER_RAPPORT"
fi
serveur_pid=$(pid_uvicorn "$PORT")
sleep 3
"$PY" "$OUTILS18" restes --lieux "$ATELIER_LIEUX" --sauf $serveur_pid || echoue "des processus restent après « Arrêter »"
arreter_groupe "$GROUPE_ATELIER"

# 2. le journal du conteneur du Jetson, avant « g1-jetson arreter »
rm -f "$TRAVAIL/jetson.txt"
"$PY" "$OUTILS38" jetson --seances "$TRAVAIL/seances_jetson" --bin "$ATELIER_BIN" --trace "$TRAVAIL/jetson.txt" \
  2>&1 | tee "$TRAVAIL/journaux/jetson.log"
[ "${PIPESTATUS[0]}" = 0 ] || echoue "$(grep -E 'ÉCHEC|Error|Traceback' "$TRAVAIL/journaux/jetson.log" | tail -n 1)"

# 3. le garde-fou de la place libre
atelier atelier_b ATELIER_SEANCE_PLACE_MIN_GO=1000000
"$PY" "$OUTILS38" garde-fou --api "$API" --seances "$ATELIER_SEANCES" 2>&1 | tee "$TRAVAIL/journaux/garde_fou.log"
[ "${PIPESTATUS[0]}" = 0 ] || echoue "$(grep -E 'ÉCHEC|Error|Traceback' "$TRAVAIL/journaux/garde_fou.log" | tail -n 1)"
arreter_groupe "$GROUPE_ATELIER"

# 4. le plantage : l'Atelier tué pendant une séance, puis relancé
atelier atelier_c
"$PY" "$OUTILS38" plantage-avant --api "$API" --seances "$ATELIER_SEANCES" 2>&1 | tee "$TRAVAIL/journaux/plantage.log"
[ "${PIPESTATUS[0]}" = 0 ] || echoue "$(grep -E 'ÉCHEC|Error|Traceback' "$TRAVAIL/journaux/plantage.log" | tail -n 1)"
INTERROMPUE=$(grep '^SEANCE ' "$TRAVAIL/journaux/plantage.log" | tail -n 1 | cut -d' ' -f2)
kill -9 "$(pid_uvicorn "$PORT")" || echoue "Atelier C introuvable"
dire "Atelier C tué (SIGKILL) pendant la séance $INTERROMPUE"
"$PY" "$OUTILS38" plantage-enregistreur --seances "$ATELIER_SEANCES" --seance "$INTERROMPUE" \
  2>&1 | tee -a "$TRAVAIL/journaux/plantage.log"
[ "${PIPESTATUS[0]}" = 0 ] || echoue "$(grep -E 'ÉCHEC|Error|Traceback' "$TRAVAIL/journaux/plantage.log" | tail -n 1)"
arreter_groupe "$GROUPE_ATELIER"
atelier atelier_d
"$PY" "$OUTILS38" plantage-apres --api "$API" --seances "$ATELIER_SEANCES" --seance "$INTERROMPUE" \
  2>&1 | tee -a "$TRAVAIL/journaux/plantage.log"
[ "${PIPESTATUS[0]}" = 0 ] || echoue "$(grep -E 'ÉCHEC|Error|Traceback' "$TRAVAIL/journaux/plantage.log" | tail -n 1)"
arreter_groupe "$GROUPE_ATELIER"

# 5. l'export, et rien ne reste
"$PY" "$OUTILS38" exporter --seances "$ATELIER_SEANCES" --seance "$SEANCE" --sortie "$TRAVAIL/seance.zip" \
  2>&1 | tee "$TRAVAIL/journaux/export.log"
[ "${PIPESTATUS[0]}" = 0 ] || echoue "$(grep -E 'ÉCHEC|Error|Traceback' "$TRAVAIL/journaux/export.log" | tail -n 1)"
sleep 2
"$PY" "$OUTILS18" restes --lieux "$ATELIER_LIEUX" || echoue "des processus restent à la fin"
"$PY" "$OUTILS38" restes --seances "$ATELIER_SEANCES" || echoue "un enregistreur ou un rapport reste à la fin"
reussi "séance en répétition (actions, bag léger, ARRÊT, mouvement sans demande, rapport), journal du Jetson, place libre, plantage et reprise, export"
