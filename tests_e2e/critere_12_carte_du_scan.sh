#!/usr/bin/env bash
# Critère 12, carte et nuage du scan (vague 5 : la reconnaissance est retirée, section 12.5 du plan) : la
# session gardée par le critère 11 (ou E2E_SESSION_SCAN=DOSSIER) a sa carte 2D, son nuage 3D (nuage.pcd)
# et son nuage d'affichage, sans reconnaissance.yaml ni monde_scan.monde.yaml ; rapport.json : étapes
# carte_3d, carte_2d et nuage, nuages ignorés au plus 1 %, sol trouvé ; nuage d'affichage d'au moins
# 50 000 points (grille 0,05, sol à 0,02 m de z = 0) ; carte comparée à celle du monde du demo :
# précision au moins 0,98 (pixels du scan à 0,10 m d'un obstacle) et recouvrement au moins 0,90 (« Fin »
# à 80 % du tour : le recouvrement est celui du critère 11) ; le serveur sert carte.png, le rapport et le
# nuage (GET /api/scan/nuage, Float32) de la session.
# Sans session gardée par le critère 11, le critère 11 est lancé d'abord.
source "$(dirname "$0")/commun.sh"
LIEU=scan_e2e                  # lieu de ce test : nom propre, car les journaux de session portent son nom
OUTILS_SCAN="$E2E/outils_scan_e2e.py"
PARTAGE="${E2E_SCAN_PARTAGE:-$RACINE/journaux/e2e_scan/domaine_$ROS_DOMAIN_ID}"
trap 'c=$?; "$PY" "$OUTILS_SCAN" nettoyer --lieux "$ATELIER_LIEUX"; (exit $c); nettoyer' EXIT
exiger_commande g1-monde g1-scan g1-atelier
copier_demo "$LIEU"
generer "$LIEU"
L="$ATELIER_LIEUX/$LIEU"
cp "$L/cartes/rdc.pgm" "$TRAVAIL/reference.pgm"
sed 's/^image: .*/image: reference.pgm/' "$L/cartes/rdc.yaml" > "$TRAVAIL/reference.yaml"

# La session du critère 11
SOURCE="${E2E_SESSION_SCAN:-$("$PY" "$OUTILS_SCAN" partagee --depuis "$PARTAGE" 2> /dev/null)}"
if [ -z "$SOURCE" ]; then
  dire "pas de session récente du critère 11 : je le lance d'abord (journal : critere_11.log)"
  E2E_SCAN_PARTAGE="$TRAVAIL/partage" "$E2E/critere_11_scan_simu_api.sh" > "$TRAVAIL/journaux/critere_11.log" 2>&1
  case $? in
    0) ;;
    77) en_attente "le critère 11 n'est pas encore possible : $(grep 'PAS ENCORE' "$TRAVAIL/journaux/critere_11.log")" ;;
    *) echoue "le critère 11 a échoué : pas de session à vérifier" ;;
  esac
  SOURCE=$("$PY" "$OUTILS_SCAN" partagee --depuis "$TRAVAIL/partage")
fi
SESSION=$(basename "$SOURCE")
mkdir -p "$L/scans"
cp -r "$SOURCE" "$L/scans/$SESSION"
dire "session vérifiée : $SESSION (copie de $SOURCE)"

"$PY" "$OUTILS_SCAN" verifier-session --session "$L/scans/$SESSION" --reference "$TRAVAIL/reference.yaml" \
  --precision 0.98 --min 0.90 --ignores-max 0.01 --points-min 50000 | tee "$TRAVAIL/verification.txt"
[ "${PIPESTATUS[0]}" -eq 0 ] || echoue "carte, nuage ou rapport de la session non conformes"

serveur
"$PY" "$OUTILS_SCAN" servir-session --api "$API" --lieu "$LIEU" --session "$SESSION" \
  || echoue "le serveur ne sert pas la carte, le rapport ou le nuage 3D de la session"
PRECISION=$(sed -n 's/^Précision[^:]*: \([0-9.]*\) %.*/\1/p' "$TRAVAIL/verification.txt")
RECOUVREMENT=$(sed -n 's/^Recouvrement[^:]*: \([0-9.]*\) %.*/\1/p' "$TRAVAIL/verification.txt")
reussi "session $SESSION : carte et nuage sans reconnaissance ; précision $PRECISION %, recouvrement $RECOUVREMENT %"
