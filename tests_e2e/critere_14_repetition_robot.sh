#!/usr/bin/env bash
# Critère 14, répétition du mode robot sans robot : g1-scan demarrer --mode robot --repetition
# --explorer rend la main en moins de 3 s ; la session lance le faux service slam_operate (sur lo), la
# simulation et le relais vers /unitree/slam_mapping/* ; puis g1-scan arreter --attendre. Le faux
# service a reçu 1801 puis 1802 (avec carte_unitree), l'enregistrement contient
# /unitree/slam_mapping/points et /unitree/slam_mapping/odom, et la session finit « termine ».
source "$(dirname "$0")/commun.sh"
LIEU=repetition_e2e                  # lieu de ce test : nom propre, car les journaux de session portent son nom
OUTILS_SCAN="$E2E/outils_scan_e2e.py"
trap 'c=$?; "$PY" "$OUTILS_SCAN" nettoyer --lieux "$ATELIER_LIEUX"; (exit $c); nettoyer' EXIT
echoue_scan() { "$PY" "$OUTILS_SCAN" journaux --lieux "$ATELIER_LIEUX" --vers "$TRAVAIL/journaux"; echoue "$@"; }
exiger_commande g1-scan g1-monde g1-slam
exiger_paquet_ros g1_sim
copier_demo "$LIEU"
generer "$LIEU"
L="$ATELIER_LIEUX/$LIEU"

# « Scan » en mode robot, case Répétition cochée
DEBUT=$(date +%s%N)
timeout 60 g1-scan demarrer --lieu "$LIEU" --etage rdc --mode robot --repetition --explorer \
  > "$TRAVAIL/journaux/demarrer.log" 2>&1
CODE=$?
DUREE_MS=$(( ($(date +%s%N) - DEBUT) / 1000000 ))
cat "$TRAVAIL/journaux/demarrer.log"
[ $CODE -eq 0 ] || echoue_scan "g1-scan demarrer --mode robot --repetition a échoué (code $CODE)"
SESSION=$(sed -n 's/^session: //p' "$TRAVAIL/journaux/demarrer.log" | tail -n 1)
[ -n "$SESSION" ] || echoue_scan "pas de ligne « session: ID » à la fin de la sortie de g1-scan demarrer"
dire "g1-scan demarrer a rendu la main en $DUREE_MS ms"
[ "$DUREE_MS" -lt 3000 ] || echoue_scan "g1-scan demarrer a mis $DUREE_MS ms (au plus 3 s)"
"$PY" - "$L" "$SESSION" <<'PYTHON' || echoue_scan "session.json ne correspond pas à un scan robot en répétition"
import sys
from atelier import lieu as L
s = L.lire_session(sys.argv[1], sys.argv[2])
print(f"session {s['id']} : mode {s['mode']}, répétition {s['repetition']}, sujets {s['sujets']}, "
      f"carte_unitree {s['carte_unitree']}")
assert s["mode"] == "robot" and s["repetition"] is True, "mode robot et repetition attendus"
assert s["sujets"]["nuage"] == "/unitree/slam_mapping/points", s["sujets"]
assert s["sujets"]["odom"] == "/unitree/slam_mapping/odom", s["sujets"]
assert s["carte_unitree"] == f"{s['etage']}_{s['id']}.pcd", s["carte_unitree"]
PYTHON

# L'enregistrement commence, puis on le laisse tourner un moment
"$PY" "$OUTILS_SCAN" attendre-etape --lieu "$LIEU" --session "$SESSION" --etape enregistrement --nuages-min 1 --delai 120 \
  || echoue_scan "l'enregistrement ne commence pas (aucun nuage reçu sous /unitree/slam_mapping/points)"
sleep "${E2E_DUREE_REPETITION:-30}"

# « Fin »
timeout 1500 g1-scan arreter --lieu "$LIEU" --session "$SESSION" --attendre > "$TRAVAIL/journaux/arreter.log" 2>&1
CODE=$?
tail -n 20 "$TRAVAIL/journaux/arreter.log"
[ $CODE -eq 0 ] || echoue_scan "g1-scan arreter --attendre : code $CODE (la session n'a pas fini « termine »)"

"$PY" "$OUTILS_SCAN" faux-slam --lieu "$LIEU" --session "$SESSION" \
  || echoue_scan "le faux service n'a pas reçu 1801 puis 1802"
"$PY" "$OUTILS_SCAN" bag --dossier "$L/scans/$SESSION/enregistrement" /unitree/slam_mapping/points /unitree/slam_mapping/odom \
  || echoue_scan "les sujets du vrai robot manquent dans l'enregistrement"
g1-scan etat --lieu "$LIEU" --session "$SESSION" --json > "$TRAVAIL/etat.json" 2> "$TRAVAIL/journaux/etat.log" \
  || echoue_scan "g1-scan etat --json a échoué"
"$PY" -c "
import json, sys
e = json.load(open(sys.argv[1]))
s = e['session']
print(f\"g1-scan etat --json : {s['etat']} ({s['progression']} %), actif {e['actif']}, fichiers {s['fichiers']}\")
sys.exit(0 if s['etat'] == 'termine' and not e['actif'] and s['fichiers']['carte'] else 1)
" "$TRAVAIL/etat.json" || echoue_scan "la session n'est pas « termine » avec sa carte"
"$PY" "$OUTILS_SCAN" restants --lieux "$ATELIER_LIEUX" --attendre 30 \
  || echoue_scan "des processus de la répétition (faux service, simulation, relais) survivent à la session"
reussi "répétition $SESSION : 1801 puis 1802 reçus, /unitree/slam_mapping/* enregistrés, session terminée"
