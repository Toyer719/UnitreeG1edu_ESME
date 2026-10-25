#!/usr/bin/env bash
# Critère 11, scan simulé intégré, par l'API du serveur (boutons « Scan » et « Fin » de l'onglet Scan) :
# sur une copie du lieu demo, POST /api/scan/demarrer en mode simu avec exploration ; l'aperçu se met
# à jour pendant le tour ; au moins 30 s plus tard, POST /api/scan/arreter (« Fin ») ; le traitement
# automatique finit « termine » ; la carte 2D de la session recouvre la carte générée du lieu à au
# moins 90 % ; reconnaissance.yaml et monde_scan.monde.yaml sont valides ; rien ne survit à la session.
# « Fin » est envoyé quand le robot a parcouru 80 % de la longueur des couloirs (E2E_PART_TOUR), pour
# que la session couvre presque tout l'étage. Elle est ensuite gardée pour les critères 12 et 13.
source "$(dirname "$0")/commun.sh"
LIEU=scan_e2e                  # lieu de ce test : nom propre, car les journaux de session portent son nom
OUTILS_SCAN="$E2E/outils_scan_e2e.py"
PARTAGE="${E2E_SCAN_PARTAGE:-$RACINE/journaux/e2e_scan/domaine_$ROS_DOMAIN_ID}"
# Les sessions de scan tournent détachées (leur propre groupe) : on les arrête avant le ménage commun
trap 'c=$?; "$PY" "$OUTILS_SCAN" nettoyer --lieux "$ATELIER_LIEUX"; (exit $c); nettoyer' EXIT
echoue_scan() { "$PY" "$OUTILS_SCAN" journaux --lieux "$ATELIER_LIEUX" --vers "$TRAVAIL/journaux"; echoue "$@"; }

exiger_commande g1-monde g1-scan g1-atelier
exiger_paquet_ros g1_sim
copier_demo "$LIEU"
generer "$LIEU"
L="$ATELIER_LIEUX/$LIEU"
cp "$L/cartes/rdc.pgm" "$TRAVAIL/reference.pgm"
sed 's/^image: .*/image: reference.pgm/' "$L/cartes/rdc.yaml" > "$TRAVAIL/reference.yaml"
serveur
SERVEUR=$DERNIER
for r in "POST /api/scan/demarrer" "POST /api/scan/arreter" "GET /api/scan/etat" "GET /api/scan/apercu.json"; do
  "$PY" "$OUTILS_SCAN" route --api "$API" $r || en_attente "le serveur n'a pas encore la route $r (agent Interface)"
done

# « Scan »
"$PY" "$OUTILS_SCAN" demarrer-api --api "$API" --lieu "$LIEU" --mode simu --explorer | tee "$TRAVAIL/demarrer.txt"
[ "${PIPESTATUS[0]}" -eq 0 ] || echoue_scan "POST /api/scan/demarrer en mode simu avec exploration a échoué"
SESSION=$(sed -n 's/^session: //p' "$TRAVAIL/demarrer.txt" | tail -n 1)
[ -n "$SESSION" ] || echoue_scan "pas d'identifiant de session dans la réponse de /api/scan/demarrer"

if [ "${E2E_FIN_AUTO:-0}" = 1 ]; then
  # Variante (section 9.10 du plan) : pas de « Fin » ; à la fin du tour, l'exploration termine le scan
  "$PY" "$OUTILS_SCAN" suivre --api "$API" --lieu "$LIEU" --session "$SESSION" \
    --duree-min 0 --part-tour 1000 --duree-max "${E2E_DUREE_MAX_SCAN:-1200}"
  case $? in
    3) dire "le scan s'est terminé de lui-même à la fin de l'exploration" ;;
    0) echoue_scan "le scan ne s'est pas terminé de lui-même à la fin de l'exploration" ;;
    *) echoue_scan "l'aperçu ou les statistiques de la session ne se mettent pas à jour pendant le scan" ;;
  esac
else
  # Pendant le tour : aperçu et statistiques, comme l'interface
  "$PY" "$OUTILS_SCAN" suivre --api "$API" --lieu "$LIEU" --session "$SESSION" \
    --duree-min "${E2E_DUREE_SCAN:-30}" --part-tour "${E2E_PART_TOUR:-0.8}" --duree-max "${E2E_DUREE_MAX_SCAN:-600}"
  case $? in
    0) ;;
    3) echoue_scan "le scan s'est terminé de lui-même avant « Fin » (exploration trop courte, ou arrêt sur erreur)" ;;
    *) echoue_scan "l'aperçu ou les statistiques de la session ne se mettent pas à jour pendant le scan" ;;
  esac
  # « Fin », puis le traitement automatique : carte 3D, carte 2D, reconnaissance, monde
  "$PY" "$OUTILS_SCAN" arreter-api --api "$API" --lieu "$LIEU" --session "$SESSION" \
    || echoue_scan "POST /api/scan/arreter n'a pas fermé l'enregistrement"
fi
"$PY" "$OUTILS_SCAN" attendre-fin --api "$API" --lieu "$LIEU" --session "$SESSION" --delai 1200 \
  || echoue_scan "la session n'a pas fini « termine » en 20 min"
"$PY" "$OUTILS_SCAN" verifier-session --session "$L/scans/$SESSION" --reference "$TRAVAIL/reference.yaml" --min 0.90 \
  | tee "$TRAVAIL/verification.txt"
[ "${PIPESTATUS[0]}" -eq 0 ] || echoue_scan "session incomplète, invalide, ou recouvrement de moins de 90 %"
"$PY" "$OUTILS_SCAN" restants --lieux "$ATELIER_LIEUX" --sauf "$SERVEUR" --attendre 30 \
  || echoue_scan "des processus lancés par la session lui survivent"

"$PY" "$OUTILS_SCAN" partager --session "$L/scans/$SESSION" --vers "$PARTAGE"
RECOUVREMENT=$(sed -n 's/^Recouvrement[^:]*: \([0-9.]*\) %.*/\1/p' "$TRAVAIL/verification.txt")
reussi "session $SESSION terminée ; recouvrement de $RECOUVREMENT % avec la carte générée"
