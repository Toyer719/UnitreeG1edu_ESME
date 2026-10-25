#!/usr/bin/env bash
# Critère 9, interface : le parcours « créer → dessiner → fabriquer la carte → placer une salle →
# lancer la simulation → Y aller » fonctionne. L'agent Interface fournit un test dans un vrai
# navigateur sans fenêtre (atelier/tests/test_serveur_navigateur.py), ou la liste de
# vérifications cochée dans docs/journal-atelier.md.
source "$(dirname "$0")/commun.sh"
TEST="$RACINE/atelier/tests/test_serveur_navigateur.py"
if [ -f "$TEST" ]; then
  cd "$RACINE" || exit 1
  SORTIE=$("$PY" -m pytest -q -rs -p no:cacheprovider "$TEST" 2>&1); CODE=$?
  echo "$SORTIE" | tail -n 8
  if echo "$SORTIE" | grep -qE "[0-9]+ passed" && [ $CODE -eq 0 ]; then
    reussi "parcours de l'interface réussi dans le navigateur sans fenêtre"
  fi
  [ $CODE -eq 0 ] || echoue "le test du parcours dans le navigateur échoue"
  dire "test du navigateur sauté (voir la raison ci-dessus) : on cherche la liste de vérifications"
fi
JOURNAL="$RACINE/docs/journal-atelier.md"
LISTE=$(awk '/^## Interface/{dans=1; next} /^## /{dans=0} dans' "$JOURNAL" 2>/dev/null | grep -E '^\s*[-*] \[[ xX]\]')
[ -n "$LISTE" ] || en_attente "ni test du navigateur exécutable, ni liste de vérifications dans le journal"
if echo "$LISTE" | grep -qE '\[ \]'; then
  echoue "liste de vérifications incomplète : $(echo "$LISTE" | grep -cE '\[ \]') case(s) non cochée(s)"
fi
reussi "liste de vérifications entièrement cochée ($(echo "$LISTE" | wc -l) points)"
