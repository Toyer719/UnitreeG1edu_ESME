#!/usr/bin/env bash
# Critère 15, robustesse et interface du scan, par l'API du serveur, par g1-scan et dans le navigateur :
#   1. « Fin » sans scan en cours : un message clair en français, pas de plantage (ni erreur 500 ni
#      trace Python) ;
#   2. « Scan » deux fois de suite : le second est refusé (409, code 1 pour g1-scan), avec un message ;
#      pendant le premier, les flèches (POST /api/simulation/teleop) font avancer le robot simulé, qui
#      s'arrête seul quand on lâche (homme mort), puis « Fin » ; ensuite « Scan » puis « Fin » tout de suite ;
#   3. mode robot sans robot et sans répétition : le message « Robot non détecté », sans session
#      laissée active ;
#   4. demandes absurdes (lieu inconnu, mode inconnu, répétition en simu, id de session qui sort du
#      dossier scans/) : refusées avec un message, jamais de plantage ;
#   5. l'écran de scan dans Firefox sans fenêtre (vague 5 : vue 3D plein écran, Scan → nuage en direct →
#      flèches → Fin → progression → carte 2D et nuage 3D → « Utiliser cette carte »), avec un faux g1-scan.
# Le vrai robot n'est jamais contacté : G1_SLAM_FAUX=1 (commun.sh), G1_INTERFACE pointe vers une
# interface qui n'existe pas, et l'étape 3 est sautée si un câble est branché sur eno2.
source "$(dirname "$0")/commun.sh"
LIEU=robustesse_e2e                  # lieu de ce test : nom propre, car les journaux de session portent son nom
OUTILS_SCAN="$E2E/outils_scan_e2e.py"
trap 'c=$?; "$PY" "$OUTILS_SCAN" nettoyer --lieux "$ATELIER_LIEUX"; (exit $c); nettoyer' EXIT
echoue_scan() { "$PY" "$OUTILS_SCAN" journaux --lieux "$ATELIER_LIEUX" --vers "$TRAVAIL/journaux"; echoue "$@"; }
export G1_INTERFACE=e2e_aucune_interface
exiger_commande g1-scan g1-monde g1-atelier
exiger_paquet_ros g1_sim
copier_demo "$LIEU"
generer "$LIEU"
serveur
SERVEUR=$DERNIER
for r in "POST /api/scan/demarrer" "POST /api/scan/arreter" "GET /api/scan/etat"; do
  "$PY" "$OUTILS_SCAN" route --api "$API" $r || en_attente "le serveur n'a pas encore la route $r (agent Interface)"
done
appel() { "$PY" "$OUTILS_SCAN" appel --api "$API" "$@"; }

# g1-scan CODES COMMANDE... : le code de sortie doit être parmi CODES, avec un message et sans trace Python
g1_scan_attendu() {
  local codes="$1"; shift
  timeout 120 g1-scan "$@" > "$TRAVAIL/journaux/g1_scan.log" 2>&1
  local code=$?
  sed 's/^/    /' "$TRAVAIL/journaux/g1_scan.log" | tail -n 8
  dire "g1-scan $* → code $code"
  [[ ",$codes," == *",$code,"* ]] || echoue_scan "g1-scan $* : code $code (attendu : $codes)"
  [ -s "$TRAVAIL/journaux/g1_scan.log" ] || echoue_scan "g1-scan $* : aucun message"
  grep -q "Traceback" "$TRAVAIL/journaux/g1_scan.log" && echoue_scan "g1-scan $* : trace Python au lieu d'un message"
  return 0
}

dire "1. « Fin » sans scan en cours"
appel POST /api/scan/arreter "{\"lieu\": \"$LIEU\"}" --codes 200,400,404,409 --message \
  || echoue_scan "POST /api/scan/arreter sans scan : pas de message clair"
g1_scan_attendu 0,1 arreter --lieu "$LIEU"

dire "2. « Scan » deux fois de suite"
appel POST /api/scan/demarrer "{\"lieu\": \"$LIEU\", \"etage\": \"rdc\", \"mode\": \"simu\"}" --codes 200 > "$TRAVAIL/premier.txt"
CODE=$?; cat "$TRAVAIL/premier.txt"
[ $CODE -eq 0 ] || echoue_scan "le premier POST /api/scan/demarrer a échoué"
SESSION=$(sed -n 's/^session: //p' "$TRAVAIL/premier.txt" | tail -n 1)
appel POST /api/scan/demarrer "{\"lieu\": \"$LIEU\", \"etage\": \"rdc\", \"mode\": \"simu\"}" --codes 409 --message \
  || echoue_scan "le second POST /api/scan/demarrer n'est pas refusé avec un message (409 attendu)"
g1_scan_attendu 1 demarrer --lieu "$LIEU" --etage rdc --mode simu
"$PY" -c "
import sys
from atelier import lieu as L
n = len(L.lister_sessions(sys.argv[1]))
print(f'sessions du lieu : {n}')
sys.exit(0 if n == 1 else 1)" "$LIEU" || echoue_scan "un second scan a été créé malgré le refus"

dire "2 bis. Les flèches pendant le scan simulé, puis « Fin »"
"$PY" "$OUTILS_SCAN" attendre-etape --lieu "$LIEU" --session "$SESSION" --etape enregistrement --nuages-min 5 \
  --delai 150 || echoue_scan "le scan simulé n'arrive pas à l'enregistrement"
"$PY" "$OUTILS_SCAN" teleop --api "$API" --lieu "$LIEU" --session "$SESSION" --vx 0.4 --duree 3 --min 0.5 \
  || echoue_scan "la téléopération ne déplace pas le robot simulé, ou il ne s'arrête pas seul quand on lâche"
"$PY" "$OUTILS_SCAN" arreter-api --api "$API" --lieu "$LIEU" --session "$SESSION" || echoue_scan "« Fin » refusé"
"$PY" "$OUTILS_SCAN" attendre-fin --api "$API" --lieu "$LIEU" --session "$SESSION" --delai 300 --accepter-echec \
  || echoue_scan "la session arrêtée ne finit pas"
"$PY" "$OUTILS_SCAN" restants --lieux "$ATELIER_LIEUX" --sauf "$SERVEUR" --attendre 30 \
  || echoue_scan "des processus de la session arrêtée lui survivent"

dire "2 ter. « Scan » puis « Fin » tout de suite, souvent pendant la préparation"
"$PY" "$OUTILS_SCAN" demarrer-api --api "$API" --lieu "$LIEU" > "$TRAVAIL/deuxieme.txt" \
  || { cat "$TRAVAIL/deuxieme.txt"; echoue_scan "le nouveau POST /api/scan/demarrer a échoué"; }
SESSION=$(sed -n 's/^session: //p' "$TRAVAIL/deuxieme.txt" | tail -n 1)
# code 0, ou 1 avec « rien n'a été enregistré » si la préparation n'était pas finie
g1_scan_attendu 0,1 arreter --lieu "$LIEU" --session "$SESSION"
"$PY" "$OUTILS_SCAN" attendre-fin --fichiers --lieu "$LIEU" --session "$SESSION" --delai 300 --accepter-echec \
  || echoue_scan "la session arrêtée reste active"
"$PY" "$OUTILS_SCAN" restants --lieux "$ATELIER_LIEUX" --sauf "$SERVEUR" --attendre 30 \
  || echoue_scan "des processus de la session arrêtée lui survivent"

dire "3. Mode robot sans robot et sans répétition"
if [ "$(cat /sys/class/net/eno2/carrier 2> /dev/null)" = 1 ]; then
  dire "un câble est branché sur eno2 : étape sautée (ces tests ne parlent jamais au vrai robot)"
else
  appel POST /api/scan/demarrer "{\"lieu\": \"$LIEU\", \"etage\": \"rdc\", \"mode\": \"robot\"}" --codes 400,409,502,503 \
    --message --contient "Robot non détecté" --delai 180 \
    || echoue_scan "mode robot sans robot : pas de message « Robot non détecté »"
  # La commande seule : un refus clair (code 1) suffit ; son libellé est signalé s'il diffère de l'interface
  g1_scan_attendu 1 demarrer --lieu "$LIEU" --etage rdc --mode robot
  grep -qi "Robot non détecté" "$TRAVAIL/journaux/g1_scan.log" \
    || dire "remarque : g1-scan ne dit pas « Robot non détecté » comme l'interface (non bloquant)"
  "$PY" -c "
import sys
from atelier import lieu as L
e = L.etat_scan(sys.argv[1])
print(f\"actif {e['actif']} ; dernière session {e['session'] and (e['session']['id'], e['session']['etat'])}\")
sys.exit(1 if e['actif'] else 0)" "$LIEU" || echoue_scan "une session reste active après « Robot non détecté »"
fi

dire "4. Demandes absurdes"
appel GET "/api/scan/etat?lieu=lieu_inconnu" --codes 400,404 --message || echoue_scan "lieu inconnu mal refusé"
appel POST /api/scan/demarrer "{\"lieu\": \"$LIEU\", \"etage\": \"rdc\", \"mode\": \"avion\"}" --codes 400,422,502 \
  || echoue_scan "mode inconnu mal refusé"
appel POST /api/scan/demarrer "{\"lieu\": \"$LIEU\", \"etage\": \"rdc\", \"mode\": \"simu\", \"repetition\": true}" \
  --codes 400,409,422,502 --message || echoue_scan "répétition en mode simu mal refusée"
appel POST /api/scan/demarrer "{\"lieu\": \"$LIEU\", \"etage\": \"grenier\", \"mode\": \"simu\"}" --codes 400,404,409,502 --message \
  || echoue_scan "étage inconnu mal refusé"
appel GET "/api/scan/sessions/..%2F..%2Flieu.yaml/rapport?lieu=$LIEU" --codes 400,404 \
  || echoue_scan "un id de session qui sort de scans/ n'est pas refusé"
appel GET "/api/scan/nuage?lieu=$LIEU&session=../../lieu" --codes 400,404 --message \
  || echoue_scan "nuage d'une session hors de scans/ mal refusé"
appel GET "/api/scan/apercu.png?lieu=$LIEU&session=2020-01-01_00h00" --codes 400,404 --message \
  || echoue_scan "aperçu d'une session inconnue mal refusé"
"$PY" -c "
import sys
from atelier import lieu as L
sys.exit(0 if L.session_active(sys.argv[1]) is None else 1)" "$LIEU" || echoue_scan "une demande refusée a laissé un scan actif"
"$PY" "$OUTILS_SCAN" restants --lieux "$ATELIER_LIEUX" --sauf "$SERVEUR" --attendre 30 \
  || echoue_scan "des processus restent après les refus"

dire "5. L'écran de scan dans Firefox sans fenêtre (atelier/tests/test_serveur_scan_navigateur.py, faux g1-scan)"
NAVIGATEUR=$(cd "$RACINE" && "$PY" -m pytest -q -rs -p no:cacheprovider atelier/tests/test_serveur_scan_navigateur.py 2>&1)
CODE=$?
echo "$NAVIGATEUR" | tail -n 6
[ $CODE -eq 0 ] || echoue_scan "le parcours de l'écran de scan dans le navigateur échoue"
if echo "$NAVIGATEUR" | grep -q "skipped"; then
  dire "remarque : une partie du parcours dans le navigateur est sautée (Firefox ou geckodriver absent ?)"
fi
reussi "refus clairs : Fin sans scan, double Scan, robot non détecté, demandes absurdes ; flèches et homme mort ; écran de scan dans le navigateur"
