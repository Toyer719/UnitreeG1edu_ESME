#!/usr/bin/env bash
# Critère 12, reconnaissance : atelier.scan.evaluation compare les murs, passages et objets reconnus au
# monde du lieu demo (la vérité terrain). Il faut au moins 90 % des murs, 80 % des passages et 70 %
# des objets de la bonne catégorie, et aucune personne gardée (cochée d'office). Les autres objectifs
# de la section 9.8 (précisions, détection, faux objets, personne debout reconnue) sont affichés, et
# bloquants avec E2E_STRICT=1.
# Deux sources :
#   1. la session gardée par le critère 11 (ou E2E_SESSION_SCAN=DOSSIER), si elle existe ;
#   2. un nuage fabriqué sans Gazebo : les rayons du LiDAR du robot proxy lancés sur les formes du
#      monde Gazebo, le long des couloirs ; puis carte 2D et reconnaissance.
# Avec la session du critère 11, c'est elle qui décide ; le nuage fabriqué est alors indicatif.
source "$(dirname "$0")/commun.sh"
OUTILS_SCAN="$E2E/outils_scan_e2e.py"
PARTAGE="${E2E_SCAN_PARTAGE:-$RACINE/journaux/e2e_scan/domaine_$ROS_DOMAIN_ID}"
STRICT=${E2E_STRICT:+--strict}

"$PY" -c "import atelier.scan.reconnaissance" 2> /dev/null \
  || en_attente "le module atelier.scan.reconnaissance n'existe pas encore (agent Reconnaissance)"
"$PY" -c "import atelier.scan.evaluation" 2> /dev/null \
  || en_attente "le module atelier.scan.evaluation n'existe pas encore"
copier_demo essai          # le monde de référence

# 1. La session du critère 11
SESSION_11="${E2E_SESSION_SCAN:-$("$PY" "$OUTILS_SCAN" partagee --depuis "$PARTAGE" 2> "$TRAVAIL/partage.txt")}"
CODE_11=""
if [ -n "$SESSION_11" ]; then
  dire "session évaluée : $SESSION_11"
  "$PY" "$OUTILS_SCAN" evaluer --session "$SESSION_11" --reference essai $STRICT --json "$TRAVAIL/evaluation_11.json"
  CODE_11=$?
  dire "bilan de python -m atelier.scan.evaluation :"
  "$PY" -m atelier.scan.evaluation --session "$SESSION_11" --reference essai --etage rdc 2>&1 | sed 's/^/    /' | tail -n 40
else
  dire "pas de session du critère 11 : $(cat "$TRAVAIL/partage.txt") (tests_e2e/tout.sh 11 12 l'enchaîne)"
fi

# 2. Le nuage fabriqué
CODE_FAB=""
if [ "${E2E_NUAGE_FABRIQUE:-1}" = 1 ]; then
  F="$TRAVAIL/fabrique"
  "$PY" "$OUTILS_SCAN" fabriquer-nuage --reference essai --sortie "$F" || echoue "fabrication du nuage impossible"
  if "$PY" "$OUTILS_SCAN" reconnaitre --session "$F" --reference essai; then
    "$PY" "$OUTILS_SCAN" evaluer --session "$F" --reference essai $STRICT --json "$TRAVAIL/evaluation_fabrique.json"
    CODE_FAB=$?
  else
    CODE_FAB=1
    dire "la reconnaissance a échoué sur le nuage fabriqué"
  fi
fi

if [ -n "$CODE_11" ]; then
  [ -n "$CODE_FAB" ] && [ "$CODE_FAB" -ne 0 ] && dire "nuage fabriqué : objectifs non atteints (indicatif)"
  [ "$CODE_11" -eq 0 ] || echoue "objectifs de la reconnaissance non atteints sur la session du critère 11"
  reussi "objectifs atteints sur la session du critère 11 ($(basename "$SESSION_11"))"
fi
[ -n "$CODE_FAB" ] || en_attente "ni session du critère 11, ni nuage fabriqué (E2E_NUAGE_FABRIQUE=0)"
[ "$CODE_FAB" -eq 0 ] || echoue "objectifs de la reconnaissance non atteints sur le nuage fabriqué"
reussi "objectifs atteints sur le nuage fabriqué (sans session du critère 11)"
