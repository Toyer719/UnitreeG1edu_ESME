#!/usr/bin/env bash
# Critère 23, passant immobile au milieu du couloir (section 11.3 du plan, agent Passants).
# Scène immobile_couloir (passant debout en (12 ; 13), reaction: aucune), 5 essais accueil → b204 :
# 5 arrivées à moins de 0,3 m en moins de 180 s, sans détour, 0 contact, et sur chaque essai une
# distance bord à bord minimale de 0,20 m au moins (0,71 m de centre à centre).
source "$(dirname "$0")/commun.sh"
exiger_commande g1-banc g1-monde g1-guide
exiger_paquet_ros g1_sim g1_nav
OUTILS_P="$E2E/outils_passants_e2e.py"
copier_demo demo                       # la référence des scènes, copiée : g1-banc la recopie encore
g1-banc --scene immobile_couloir --travail "$TRAVAIL/banc" --csv "$TRAVAIL/immobile.csv" 2>&1 \
  | tee "$TRAVAIL/journaux/banc.log"
CODE=${PIPESTATUS[0]}
[ -s "$TRAVAIL/immobile.csv" ] || echoue "g1-banc n'a pas produit de CSV (code $CODE)"
"$PY" "$OUTILS_P" verifier "$TRAVAIL/immobile.csv" --essais 5 --arrivees-min 5 --duree-max 180 \
  --detours-max 0 --contacts-max 0 --bord-min-par-essai 0.20 \
  || echoue "passant immobile : seuils non tenus (voir le bilan ci-dessus)"
[ "$CODE" -eq 0 ] || echoue "g1-banc : seuils de la scène non tenus (code $CODE)"
reussi "5 arrivées sans détour ni contact, 0,20 m bord à bord au moins à chaque essai"
