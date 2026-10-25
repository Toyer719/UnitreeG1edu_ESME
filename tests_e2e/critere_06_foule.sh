#!/usr/bin/env bash
# Critère 6, foule : 5 piétons et 20 trajets avec g1-banc donnent au moins 90 % de réussite,
# et un CSV est produit.
source "$(dirname "$0")/commun.sh"
exiger_commande g1-monde g1-guide g1-banc
exiger_paquet_ros g1_sim g1_nav
copier_demo essai
# Trois piétons de plus (5 en tout), dans les couloirs
"$PY" - <<'PYTHON' || echoue "ajout des piétons impossible"
from atelier.lieu import Pieton, charger_monde, enregistrer_monde
m = charger_monde("essai", "rdc")
m.pietons += [Pieton("pieton_3", [(8.0, 13.2), (22.0, 13.2)], 0.8, True),
              Pieton("pieton_4", [(26.5, 6.5), (26.5, 13.5)], 0.7, True),
              Pieton("pieton_5", [(1.5, 8.5), (4.0, 12.0)], 0.6, True)]
enregistrer_monde("essai", "rdc", m)
print(f"{len(m.pietons)} piétons")
PYTHON
generer essai
cd "$TRAVAIL" || echoue "dossier de travail"
g1-banc --lieu essai --etage rdc --trajets 20 --simu --lancer --seuil 90 --csv "$TRAVAIL/banc.csv" 2>&1 | tee "$TRAVAIL/journaux/banc.log"
CODE=${PIPESTATUS[0]}
CSV="$TRAVAIL/banc.csv"; [ -s "$CSV" ] || CSV=""
[ -n "$CSV" ] || echoue "aucun CSV produit par g1-banc"
dire "CSV : $CSV ($(($(wc -l < "$CSV") - 1)) trajets)"
[ "$CODE" -eq 0 ] || echoue "g1-banc : moins de 90 % de réussite, ou erreur (code $CODE)"
reussi "20 trajets, au moins 90 % de réussite"
