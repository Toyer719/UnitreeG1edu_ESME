#!/usr/bin/env bash
# Critère 10, un seul point d'entrée : g1-atelier ouvre le logiciel (sa page répond), et
# tests_e2e/tout.sh existe. Le « 10 / 10 » lui-même est compté par tout.sh : ce critère n'y est
# réussi que si les neuf autres le sont aussi.
source "$(dirname "$0")/commun.sh"
exiger_commande g1-atelier
[ -x "$E2E/tout.sh" ] || echoue "tests_e2e/tout.sh manque"
copier_demo demo
serveur
PAGE=$("$PY" "$OUTILS" http GET "$API/") || echoue "la page d'accueil de l'Atelier ne répond pas"
echo "$PAGE" | grep -qi "atelier" || echoue "la page ne parle pas de l'Atelier"
http GET /api/lieux | grep -q '"demo"' || echoue "l'API ne liste pas le lieu demo"
reussi "g1-atelier sert la page et l'API"
