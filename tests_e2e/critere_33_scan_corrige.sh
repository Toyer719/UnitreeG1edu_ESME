#!/usr/bin/env bash
# Critère 33, scan corrigé, sans reconnaissance, et monde maillé (vague 5, sections 12.5 et 12.10 du plan),
# sur une copie du lieu demo :
#   1. scan simulé (g1-scan demarrer --mode simu --explorer, tour complet : l'exploration finit le scan) :
#      « termine », étapes carte_3d, carte_2d et nuage, sans reconnaissance ; nuages ignorés au plus 1 % ;
#      nuage d'affichage d'au moins 50 000 points, grille 0,05, sol à 0,02 m de z = 0 ; carte propre face à
#      la carte du monde : précision au moins 0,98 (à 0,10 m) et recouvrement au moins 0,90 ;
#   2. le « damier » : la même session copiée « comme le vrai G1 » (sol penché de 0,6° et 1,27 m sous
#      l'origine, nuages à horodatage nul dans map, odométrie décalée de −138 s), puis g1-scan traiter
#      --refaire : mêmes seuils, pente trouvée entre 0,5 et 0,7°, résultats d'avant dans ancien_<date>/ ;
#   3. adoption (POST …/adopter) : nuage de l'étage (source scan), carte extrudée de 1,5 m dans le monde,
#      murs et objets dessinés retirés (gardés dans la session), piétons gardés ; g1-lieu valider sans
#      erreur ; GET …/nuage, …/nuage/info et …/monde/maillage les servent ;
#   4. Gazebo sans fenêtre sur ce monde maillé : au moins 0,9 fois le temps réel (/clock sur 20 s) ;
#      /points voit le maillage ; le robot proxy poussé 3 s vers un mur à 1 m s'arrête contre lui ;
#   5. g1-scan carte-unitree pendant un repérage en répétition (lancée par l'Atelier) :
#      cartes/rdc_unitree.pcd et le nuage source unitree ; aucun processus restant.
# E2E_SESSION_SCAN=DOSSIER : reprend une session simulée finie du demo au lieu de scanner (mise au point).
source "$(dirname "$0")/commun.sh"
LIEU=scan_corrige_e2e          # lieu de ce test : nom propre, car les journaux de session portent son nom
OUTILS_SCAN="$E2E/outils_scan_e2e.py"
trap 'c=$?; "$PY" "$OUTILS_SCAN" nettoyer --lieux "$ATELIER_LIEUX"; (exit $c); nettoyer' EXIT
echoue_scan() { "$PY" "$OUTILS_SCAN" journaux --lieux "$ATELIER_LIEUX" --vers "$TRAVAIL/journaux"; echoue "$@"; }

exiger_commande g1-scan g1-monde g1-lieu g1-atelier g1-slam g1-guide
exiger_paquet_ros g1_sim g1_nav g1_bridge g1_jumeau unitree_api
copier_demo "$LIEU"
generer "$LIEU"
L="$ATELIER_LIEUX/$LIEU"
cp "$L/cartes/rdc.pgm" "$TRAVAIL/reference.pgm"
sed 's/^image: .*/image: reference.pgm/' "$L/cartes/rdc.yaml" > "$TRAVAIL/reference.yaml"
cp "$L/mondes/rdc.monde.yaml" "$TRAVAIL/monde_dessine.yaml"
SEUILS=(--reference "$TRAVAIL/reference.yaml" --precision 0.98 --min 0.90 --ignores-max 0.01 --points-min 50000)

dire "1. Scan simulé du demo, tour complet"
if [ -n "$E2E_SESSION_SCAN" ]; then
  SESSION=$(basename "$E2E_SESSION_SCAN")
  mkdir -p "$L/scans"
  cp -r "$E2E_SESSION_SCAN" "$L/scans/$SESSION"
  dire "session reprise (E2E_SESSION_SCAN) : $E2E_SESSION_SCAN"
else
  timeout 60 g1-scan demarrer --lieu "$LIEU" --etage rdc --mode simu --explorer > "$TRAVAIL/journaux/demarrer.log" 2>&1
  CODE=$?
  cat "$TRAVAIL/journaux/demarrer.log"
  [ $CODE -eq 0 ] || echoue_scan "g1-scan demarrer --mode simu --explorer a échoué (code $CODE)"
  SESSION=$(sed -n 's/^session: //p' "$TRAVAIL/journaux/demarrer.log" | tail -n 1)
  [ -n "$SESSION" ] || echoue_scan "pas de ligne « session: ID » à la fin de la sortie de g1-scan demarrer"
  "$PY" "$OUTILS_SCAN" attendre-fin --fichiers --lieu "$LIEU" --session "$SESSION" --delai "${E2E_DUREE_MAX_SCAN:-1800}" \
    || echoue_scan "la session n'a pas fini « termine » (tour de l'exploration, puis traitement)"
  "$PY" "$OUTILS_SCAN" restants --lieux "$ATELIER_LIEUX" --attendre 30 \
    || echoue_scan "des processus lancés par la session lui survivent"
fi
"$PY" "$OUTILS_SCAN" verifier-session --session "$L/scans/$SESSION" "${SEUILS[@]}" | tee "$TRAVAIL/verification.txt"
[ "${PIPESTATUS[0]}" -eq 0 ] || echoue_scan "session du scan simulé non conforme (fichiers, rapport, nuage ou carte)"

dire "2. Le « damier » : la même session comme le vrai G1, puis g1-scan traiter --refaire"
"$PY" "$OUTILS_SCAN" damier --session "$L/scans/$SESSION" | tee "$TRAVAIL/damier.txt"
[ "${PIPESTATUS[0]}" -eq 0 ] || echoue "la copie « comme le G1 » de la session a échoué"
DAMIER=$(sed -n 's/^session: //p' "$TRAVAIL/damier.txt" | tail -n 1)
[ -n "$DAMIER" ] || echoue "pas d'identifiant pour la copie « comme le G1 »"
timeout 1200 g1-scan traiter --lieu "$LIEU" --session "$DAMIER" --refaire > "$TRAVAIL/journaux/traiter_damier.log" 2>&1
CODE=$?
tail -n 12 "$TRAVAIL/journaux/traiter_damier.log"
[ $CODE -eq 0 ] || echoue "g1-scan traiter --refaire a échoué sur la copie « comme le G1 » (code $CODE)"
ls -d "$L/scans/$DAMIER"/ancien_*/ > /dev/null 2>&1 \
  || echoue "g1-scan traiter --refaire n'a pas gardé les résultats d'avant dans ancien_<date>/"
dire "résultats d'avant gardés : $(cd "$L/scans/$DAMIER" && ls -d ancien_* | tr '\n' ' ')"
"$PY" "$OUTILS_SCAN" verifier-session --session "$L/scans/$DAMIER" "${SEUILS[@]}" --inclinaison 0.5 0.7 \
  | tee "$TRAVAIL/verification_damier.txt"
[ "${PIPESTATUS[0]}" -eq 0 ] || echoue "copie « comme le G1 » retraitée non conforme (seuils, sol ou nuage)"
grep -q "base de temps reception" "$TRAVAIL/verification_damier.txt" \
  || echoue "nuages à horodatage nul : ils devaient être appariés à l'odométrie par instants de réception"

dire "3. « Utiliser cette carte » (POST …/adopter) sur la copie retraitée"
serveur
SERVEUR=$DERNIER
"$PY" "$OUTILS_SCAN" appel --api "$API" POST "/api/scan/sessions/$DAMIER/adopter?lieu=$LIEU" '{}' \
  --codes 200 --sortie "$TRAVAIL/adoption.json" || echoue "l'adoption de la session a échoué"
"$PY" -c "
import json, sys
r = json.load(open(sys.argv[1]))
print((r.get('sortie') or '').strip()[-600:])
sys.exit(0 if r.get('adopte') and not r.get('avertissements') else 1)" "$TRAVAIL/adoption.json" \
  || echoue "la réponse de l'adoption ne dit pas « adopte », ou elle avertit (scan simulé : rien à replacer)"
"$PY" "$OUTILS_SCAN" verifier-adoption --lieu "$LIEU" --session "$DAMIER" --reference "$RACINE/lieux/demo" --api "$API" \
  || echoue "nuage, carte extrudée, monde ou routes non conformes après l'adoption"
cmp -s "$TRAVAIL/monde_dessine.yaml" "$L/scans/$DAMIER/monde_remplace.monde.yaml" \
  || echoue "monde_remplace.monde.yaml n'est pas le monde dessiné d'avant l'adoption"
SORTIE=$(g1-lieu valider --lieu "$LIEU" 2>&1); CODE=$?
echo "$SORTIE" | tail -n 8
[ $CODE -eq 0 ] || echoue "g1-lieu valider signale des erreurs après l'adoption (code $CODE)"
grep -q '<model name="ext_sud"' "$L/mondes/rdc.sdf" && echoue "le monde Gazebo contient encore les murs dessinés"

dire "4. Gazebo sans fenêtre sur le monde maillé (copie, départ à 1 m d'un mur)"
LIEU_MUR="${LIEU}_mur"
rm -rf "${ATELIER_LIEUX:?}/$LIEU_MUR"
cp -r "$L" "$ATELIER_LIEUX/$LIEU_MUR"
rm -rf "$ATELIER_LIEUX/$LIEU_MUR/scans"
"$PY" "$OUTILS_SCAN" depart --lieu "$LIEU_MUR" --x 3.9 --y 10.0 || echoue "départ du robot simulé non écrit"
generer "$LIEU_MUR"
simuler "$LIEU_MUR" 90
SIMULATION=$DERNIER
"$PY" "$OUTILS_SCAN" temps-reel --duree 20 --min 0.9 || echoue "Gazebo sur le monde maillé : moins de 0,9 fois le temps réel"
"$PY" "$OUTILS_SCAN" voit-le-maillage --lieu "$LIEU_MUR" || echoue "/points ne voit pas la carte extrudée"
"$PY" "$OUTILS_SCAN" contre-un-mur --lieu "$LIEU_MUR" --vx 0.5 --duree 3 \
  || echoue "le robot proxy traverse le mur de la carte extrudée, ou ne va pas jusqu'à lui"
arreter_groupe "$SIMULATION"

dire "5. g1-scan carte-unitree pendant un repérage en répétition"
"$PY" "$OUTILS_SCAN" carte-unitree-repetition --api "$API" --lieu "$LIEU" \
  || echoue_scan "g1-scan carte-unitree n'a pas enregistré la carte globale de la répétition"
"$PY" "$OUTILS_SCAN" restants --lieux "$ATELIER_LIEUX" --sauf "$SERVEUR" --attendre 60 \
  || echoue "des processus de la répétition ou de la simulation restent"
PRECISION=$(sed -n 's/^Précision[^:]*: \([0-9.]*\) %.*/\1/p' "$TRAVAIL/verification_damier.txt")
RECOUVREMENT=$(sed -n 's/^Recouvrement[^:]*: \([0-9.]*\) %.*/\1/p' "$TRAVAIL/verification_damier.txt")
reussi "session $SESSION et sa copie « comme le G1 » $DAMIER (précision $PRECISION %, recouvrement $RECOUVREMENT %) ; adoptée, monde maillé dans Gazebo, carte d'Unitree enregistrée"
