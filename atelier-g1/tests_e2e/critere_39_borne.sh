#!/usr/bin/env bash
# Critère 39, la borne visiteur (section 13.9 du plan, agent Borne et orchestrateur). Sans robot ni Gazebo :
# l'Atelier écoute le réseau (g1-atelier --hote 0.0.0.0), le vrai nœud accueil (g1-accueil) et un faux guide
# (tests_e2e/outils_borne_e2e.py : /guide/etat, TF, trajets joués vite) ; Firefox sans fenêtre à 390 × 844 puis
# 1024 × 768 :
#   - /borne ne défile pas, cartes de 64 px au moins et entières, les salles du demo sauf l'accueil et une salle
#     cachée (hors_borne), aucun jargon, window.erreursBorne vide ;
#   - salle touchée → confirmation → /accueil/choix {salle, source: borne} ; cinq appuis rapides → un seul choix ;
#     suivez_moi (distance), arrivee, retour, salles ; occupe et pause : cartes inactives et le message ;
#   - /voix/son → [data-role=borne-son] charge GET /api/voix/son/<id> ;
#   - code opérateur : faux refusé, cinq faux → 429, bon → pause, reprendre, ramener (source operateur), rien d'autre ;
#   - garde depuis l'adresse réseau du PC : la borne permise, /, /api/lieux, /api/arret/debloquer, /api/guide/aller
#     et /ws/etat refusés ; Équipe › Démo › Borne montre [data-role=adresse-borne].
# Captures : $E2E_CAPTURES_BORNE (sinon dans le dossier de travail, effacé à la fin).
source "$(dirname "$0")/commun.sh"
exiger_commande g1-atelier g1-accueil
exiger_paquet_ros g1_accueil
command -v geckodriver > /dev/null && command -v firefox > /dev/null \
  || en_attente "Firefox sans fenêtre (firefox et geckodriver) n'est pas installé"
OUTILS_BORNE="$E2E/outils_borne_e2e.py"
CAPTURES="${E2E_CAPTURES_BORNE:-$TRAVAIL/captures}"
mkdir -p "$CAPTURES"
export ATELIER_VOIX_SONS="$TRAVAIL/sons"

copier_demo essai
"$PY" "$OUTILS_BORNE" preparer --lieu essai || echoue "la copie du demo n'a pas pu être préparée"
# l'Atelier écoute le réseau (la borne d'une tablette) : la garde de la borne est active
PORT=$("$PY" -c "import socket; s = socket.socket(); s.bind(('127.0.0.1', 0)); print(s.getsockname()[1])")
lancer_fond serveur g1-atelier --port "$PORT" --sans-navigateur --hote 0.0.0.0
API="http://127.0.0.1:$PORT"
"$PY" "$OUTILS" attendre-http "$API/api/lieux" --delai 30 || echoue "le serveur de l'Atelier ne répond pas"

cd "$RACINE" || exit 1
"$PY" "$OUTILS_BORNE" critere-39 --api "$API" --lieu essai --captures "$CAPTURES" --journaux "$TRAVAIL/journaux" \
  2>&1 | tee "$TRAVAIL/journaux/critere_39.log"
code=${PIPESTATUS[0]}
case $code in
  0) reussi "borne à 390 × 844 et 1024 × 768 : salles, confirmation, anti-rebond, suivi de la visite, occupé, pause, son, code opérateur, garde, adresse" ;;
  77) en_attente "$(grep 'EN ATTENTE' "$TRAVAIL/journaux/critere_39.log" | tail -n 1)" ;;
  *) echoue "$(grep -E 'ÉCHEC|Error|Traceback' "$TRAVAIL/journaux/critere_39.log" | tail -n 1 | cut -c1-500)" ;;
esac
