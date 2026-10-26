#!/usr/bin/env bash
# Critère 25, groupe qui bouche le couloir (section 11.3 du plan, agent Passants, avec le guide de
# l'agent Comportement) :
#   - groupe_couloir (3 essais, le groupe part après 15 s environ) : attente_passage (événement
#     passant_gene), aucun détour tant que le groupe est là, puis arrivée à moins de 0,3 m en moins
#     de 180 s, 0 contact causé par le robot ;
#   - groupe_reste (2 essais) : attente_passage, puis détour au plus tôt 20 s après (delai_passant_s),
#     arrivée par le couloir sud en moins de 300 s, longueur_m au plus 75 m ;
#   - banc foule (les 5 piétons du critère 6, piétons crédibles, 20 trajets) : au moins 90 % de
#     réussite et 0 contact causé par le robot ; le CSV a les colonnes de 11.3.
# En attente (77) tant que le guide ne connaît pas attente_passage (E2E_SANS_GUIDE=1 : on lance
# quand même les scènes, pour voir ce que fait le guide d'aujourd'hui ; le critère reste en attente).
source "$(dirname "$0")/commun.sh"
exiger_commande g1-banc g1-monde g1-guide
exiger_paquet_ros g1_sim g1_nav
OUTILS_P="$E2E/outils_passants_e2e.py"
GUIDE_PRET=1
"$PY" "$OUTILS_P" guide-connait attente_passage || GUIDE_PRET=0
if [ "$GUIDE_PRET" = 0 ] && [ -z "$E2E_SANS_GUIDE" ]; then
  en_attente "le guide ne connaît pas encore l'état attente_passage (agent Comportement du guide)"
fi
copier_demo demo
lancer_fond ecoute "$PY" "$OUTILS_P" ecouter --sortie "$TRAVAIL/guide.jsonl"
ECOUTE=$DERNIER
FAUTES=""
dire "groupe_couloir : le groupe part, le robot attend puis passe"
g1-banc --scene groupe_couloir --travail "$TRAVAIL/banc" --csv "$TRAVAIL/groupe_couloir.csv" 2>&1 \
  | tee "$TRAVAIL/journaux/banc_groupe_couloir.log"
[ -s "$TRAVAIL/groupe_couloir.csv" ] || echoue "g1-banc (groupe_couloir) n'a pas produit de CSV"
"$PY" "$OUTILS_P" verifier "$TRAVAIL/groupe_couloir.csv" --essais 3 --arrivees-min 3 --duree-max 180 \
  --detours-max 0 --contacts-robot-max 0 --attentes-min 1 || FAUTES="$FAUTES groupe_couloir"
"$PY" "$OUTILS_P" journal "$TRAVAIL/guide.jsonl" --evenement passant_gene --compter 3 || FAUTES="$FAUTES passant_gene"
cp "$TRAVAIL/guide.jsonl" "$TRAVAIL/guide_couloir.jsonl"; : > "$TRAVAIL/guide.jsonl"
dire "groupe_reste : le groupe reste, détour par le couloir sud après delai_passant_s"
g1-banc --scene groupe_reste --travail "$TRAVAIL/banc" --csv "$TRAVAIL/groupe_reste.csv" 2>&1 \
  | tee "$TRAVAIL/journaux/banc_groupe_reste.log"
[ -s "$TRAVAIL/groupe_reste.csv" ] || echoue "g1-banc (groupe_reste) n'a pas produit de CSV"
"$PY" "$OUTILS_P" verifier "$TRAVAIL/groupe_reste.csv" --essais 2 --arrivees-min 2 --duree-max 300 \
  --detours-min 1 --longueur-max 75 --contacts-robot-max 0 --attentes-min 1 --attente-min-s 19 \
  || FAUTES="$FAUTES groupe_reste"
"$PY" "$OUTILS_P" journal "$TRAVAIL/guide.jsonl" --itineraire-par couloir_sud_1 || FAUTES="$FAUTES couloir_sud"
dire "banc foule : 20 trajets avec les 5 piétons crédibles"
g1-banc --scene foule --travail "$TRAVAIL/banc" --csv "$TRAVAIL/foule.csv" 2>&1 | tee "$TRAVAIL/journaux/banc_foule.log"
[ -s "$TRAVAIL/foule.csv" ] || echoue "g1-banc (foule) n'a pas produit de CSV"
"$PY" "$OUTILS_P" verifier "$TRAVAIL/foule.csv" --essais 20 --arrivees-min 18 --contacts-robot-max 0 --colonnes \
  || FAUTES="$FAUTES foule"
arreter_groupe "$ECOUTE"
[ "$GUIDE_PRET" = 1 ] || en_attente "scènes lancées (E2E_SANS_GUIDE=1), mais le guide ne connaît pas attente_passage"
[ -z "$FAUTES" ] || echoue "seuils non tenus :$FAUTES"
reussi "groupe : attente puis passage, ou détour raisonnable ; foule : 90 % au moins, 0 contact causé par le robot"
