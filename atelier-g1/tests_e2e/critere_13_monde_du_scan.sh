#!/usr/bin/env bash
# Critère 13, monde issu du scan (vague 5, section 12.5 du plan) : la session du critère 11 est adoptée
# (« Utiliser cette carte », POST /api/scan/sessions/{s}/adopter) : la carte de l'étage est celle du scan,
# telle quelle ; son nuage 3D devient celui de l'étage (cartes/rdc.nuage, source scan) ; le monde de
# simulation est la carte extrudée (mondes/rdc_carte.stl, carte_extrudee de 1,5 m), sans les murs et objets
# dessinés (le monde d'avant est gardé dans la session), avec ses piétons ; g1-lieu valider ne signale
# aucune erreur ; g1-monde generer réussit sans toucher à la carte du scan ; la simulation démarre sur le
# monde maillé et le robot va de l'accueil à une salle placée depuis l'API (le parcours du critère 4).
# Sans session gardée par le critère 11 (ou E2E_SESSION_SCAN=DOSSIER), le critère 11 est lancé d'abord.
source "$(dirname "$0")/commun.sh"
LIEU=scan_e2e                  # lieu de ce test : nom propre, car les journaux de session portent son nom
OUTILS_SCAN="$E2E/outils_scan_e2e.py"
PARTAGE="${E2E_SCAN_PARTAGE:-$RACINE/journaux/e2e_scan/domaine_$ROS_DOMAIN_ID}"
trap 'c=$?; "$PY" "$OUTILS_SCAN" nettoyer --lieux "$ATELIER_LIEUX"; (exit $c); nettoyer' EXIT
exiger_commande g1-scan g1-lieu g1-monde g1-guide g1-atelier
exiger_paquet_ros g1_sim g1_nav
copier_demo "$LIEU"
L="$ATELIER_LIEUX/$LIEU"

# La session à adopter
SOURCE="${E2E_SESSION_SCAN:-$("$PY" "$OUTILS_SCAN" partagee --depuis "$PARTAGE" 2> /dev/null)}"
if [ -z "$SOURCE" ]; then
  dire "pas de session récente du critère 11 : je le lance d'abord (journal : critere_11.log)"
  E2E_SCAN_PARTAGE="$TRAVAIL/partage" "$E2E/critere_11_scan_simu_api.sh" > "$TRAVAIL/journaux/critere_11.log" 2>&1
  case $? in
    0) ;;
    77) en_attente "le critère 11 n'est pas encore possible : $(grep 'PAS ENCORE' "$TRAVAIL/journaux/critere_11.log")" ;;
    *) echoue "le critère 11 a échoué : pas de session à adopter" ;;
  esac
  SOURCE=$("$PY" "$OUTILS_SCAN" partagee --depuis "$TRAVAIL/partage")
fi
SESSION=$(basename "$SOURCE")
mkdir -p "$L/scans"
cp -r "$SOURCE" "$L/scans/$SESSION"
cp "$L/mondes/rdc.monde.yaml" "$TRAVAIL/monde_dessine.yaml"
dire "session adoptée : $SESSION (copie de $SOURCE)"

serveur
"$PY" "$OUTILS_SCAN" route --api "$API" POST "/api/scan/sessions/{s}/adopter" \
  || en_attente "le serveur n'a pas encore la route POST /api/scan/sessions/{s}/adopter (agent Interface)"

# « Utiliser cette carte »
"$PY" "$OUTILS_SCAN" appel --api "$API" POST "/api/scan/sessions/$SESSION/adopter?lieu=$LIEU" '{}' \
  --codes 200 --sortie "$TRAVAIL/adoption.json" || echoue "l'adoption de la session a échoué"
"$PY" -c "import json, sys; r = json.load(open(sys.argv[1])); sys.exit(0 if r.get('adopte') and r.get('monde') else 1)" \
  "$TRAVAIL/adoption.json" || echoue "la réponse de l'adoption ne dit pas « adopte » et « monde »"
"$PY" "$OUTILS_SCAN" verifier-adoption --lieu "$LIEU" --session "$SESSION" --reference "$RACINE/lieux/demo" --api "$API" \
  || echoue "carte, nuage, masque, monde maillé ou session non conformes après l'adoption"
cmp -s "$TRAVAIL/monde_dessine.yaml" "$L/scans/$SESSION/monde_remplace.monde.yaml" \
  || echoue "monde_remplace.monde.yaml n'est pas l'ancien monde dessiné"

SORTIE=$(g1-lieu valider --lieu "$LIEU" 2>&1); CODE=$?
echo "$SORTIE"
[ $CODE -eq 0 ] || echoue "g1-lieu valider signale des erreurs après l'adoption (code $CODE)"
AVANT=$(md5sum < "$L/cartes/rdc.pgm")
g1-monde generer --lieu "$LIEU" --etage rdc > "$TRAVAIL/journaux/generer.log" 2>&1 \
  || echoue "g1-monde generer a échoué sur le monde du scan ($(tail -n 3 "$TRAVAIL/journaux/generer.log" | tr '\n' ' '))"
cat "$TRAVAIL/journaux/generer.log"
[ "$(md5sum < "$L/cartes/rdc.pgm")" = "$AVANT" ] || echoue "g1-monde generer a remplacé la carte du scan"
grep -q '^carte_extrudee:' "$L/mondes/rdc.monde.yaml" || echoue "le monde de l'étage n'est pas la carte extrudée du scan"
grep -q '<model name="carte_du_scan"' "$L/mondes/rdc.sdf" || echoue "le monde Gazebo n'a pas la carte extrudée"
grep -q '<model name="ext_sud"' "$L/mondes/rdc.sdf" && echoue "le monde Gazebo contient encore les murs dessinés"

# Le parcours du critère 4 sur le monde du scan : une salle placée par l'API, puis « Y aller »
"$PY" - "$API" "$LIEU" <<'PYTHON' || echoue "placement de la salle par l'API impossible"
import json, sys, urllib.request
api = sys.argv[1] + "/api/lieux/" + sys.argv[2]
def appel(methode, chemin, corps=None):
    r = urllib.request.Request(api + chemin, method=methode, data=None if corps is None else json.dumps(corps).encode(),
                               headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=30) as reponse:
        return json.loads(reponse.read())
salles = appel("GET", "/salles")
salles.append({"id": "salle_e2e", "nom": "Salle de bout en bout", "alias": [], "etage": "rdc",
               "pose": {"x": 18.0, "y": 13.0, "theta": 1.5708}, "phrase_arrivee": ""})
appel("PUT", "/salles?synchroniser=true", salles)
itineraires = appel("GET", "/itineraires")
assert "salle_e2e" in itineraires["noeuds"], "le nœud de la salle n'a pas été créé"
itineraires["couloirs"] = [c for c in itineraires["couloirs"] if sorted(c) != ["b204", "couloir_nord_1"]]
itineraires["couloirs"] += [["couloir_nord_1", "salle_e2e"], ["salle_e2e", "b204"]]
r = appel("PUT", "/itineraires", itineraires)
print("salle_e2e placée en (18 ; 13) ; rapport :", json.dumps(r.get("rapport", {}), ensure_ascii=False)[:300])
PYTHON

http POST /api/simulation/demarrer "{\"lieu\": \"$LIEU\", \"etage\": \"rdc\"}" > "$TRAVAIL/journaux/demarrer.log" \
  || echoue "POST /api/simulation/demarrer refusé : $(cat "$TRAVAIL/journaux/demarrer.log")"
"$PY" "$OUTILS" attendre-sujets /odom /points /guide/etat --delai 90 || echoue "simulation ou guide absents"
sleep 5   # que Nav2 finisse de démarrer
"$PY" "$OUTILS" etat-guide --attendre arrive --delai 240 > "$TRAVAIL/journaux/guide.log" 2>&1 &
ECOUTE=$!
sleep 2
http POST /api/guide/aller '{"cible": "salle_e2e"}' || echoue "POST /api/guide/aller refusé"
wait $ECOUTE; CODE=$?
cat "$TRAVAIL/journaux/guide.log"
[ $CODE -eq 0 ] || echoue "le guide n'est pas arrivé à salle_e2e dans le monde du scan"
"$PY" "$OUTILS" pres-de --lieu "$LIEU" --salle salle_e2e --max 0.3 || echoue "le robot est à plus de 0,3 m de la salle"
http POST /api/simulation/arreter > /dev/null
reussi "session $SESSION adoptée : carte, nuage et monde maillé ; lieu valide ; arrivé à salle_e2e dans le monde maillé"
