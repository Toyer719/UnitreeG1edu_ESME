#!/usr/bin/env bash
# Critère 31, accueil, espace de travail et défilement (section 12.10 du plan, décisions I1 à I6, I9, I10) :
# agent Coquille. Sans robot, sans fenêtre : Firefox sans fenêtre (geckodriver) sur une copie du demo (id
# « demo »). On vérifie (outils : tests_e2e/outils_coque_e2e.py critere-31, mesures de
# atelier/tests/test_coque_communs.py) :
#   - l'accueil : les deux cartes, le demo dans la liste (présélectionné par atelier.lieu), Ouvrir ;
#     Simulation + demo + Ouvrir : [data-role=espace][data-mode=simu], 4 onglets (dessiner, placer, simuler,
#     equipe), aucune commande pilotage.* ; retour à l'accueil, Robot réel : les vérifications ros, cable,
#     robot, telecommande avec leur data-etat (la liaison passe par lo : jamais rien sur eno2 ni vers le
#     robot), puis « Répétition sans robot » : [data-mode=repetition], 5 onglets ; aucune boîte native ;
#   - à 1366 × 768, 1600 × 1000 et 1920 × 1080, en Simulation, en Réel et en répétition, pour chaque onglet
#     du ruban et chaque commande qui n'est pas Avancé : la page ne défile pas (scrollWidth et scrollHeight
#     au plus la fenêtre, à 1 px près) ; barre d'outils, ruban, arbre, vue, panneau et barre d'état entiers
#     dans la fenêtre ; chaque élément cliquable visible de la barre d'outils, du ruban, de l'arbre, du
#     panneau et de la barre de la vue, amené à l'écran par scrollIntoView, y est entier et non recouvert ;
#     ARRÊT visible et cliquable partout. Les actions qui lancent quelque chose (Lancer, Scan, Prendre la
#     main…) sont mesurées dans leur onglet sans être déclenchées ;
#   - les anciennes adresses (/?recharger=1#salles, #simulation, #scan, #pilotage, #camera) mènent à leur
#     écran ([data-ecran=<id>]) sans l'accueil ;
#   - le thème clair ([data-role=theme]) change data-theme et atelier.theme, gardé au rechargement ; la vue 3D
#     reste sombre ;
#   - window.erreursAtelier reste vide.
# Tailles et modes : CRITERE31_TAILLES (ex. 1366x768,1920x1080), CRITERE31_MODES (ex. simu,repetition).
# Captures : CRITERE31_CAPTURES=dossier (facultatif ; accueil et chaque onglet, thèmes sombre et clair).
# WebGL : avec un affichage X (DISPLAY, ex. :1), Firefox sans fenêtre a la vue 3D ; sans, la coque passe au
# Plan 2D, et le critère se fait quand même.
AFFICHAGE_X="${DISPLAY:-}"
source "$(dirname "$0")/commun.sh"
exiger_commande g1-atelier
command -v geckodriver > /dev/null && command -v firefox > /dev/null \
  || en_attente "Firefox sans fenêtre (firefox et geckodriver) n'est pas installé"
[ -n "$AFFICHAGE_X" ] && export DISPLAY="$AFFICHAGE_X"     # pour Firefox seulement (WebGL), sans fenêtre
OUTILS_COQUE="$E2E/outils_coque_e2e.py"

# La liaison avec le robot passe par lo : le « câble » est lo, le PC1 et le Jetson sont 127.0.0.1
export ATELIER_INTERFACE_ROBOT=lo ATELIER_PC1=127.0.0.1 ATELIER_JETSON=127.0.0.1
copier_demo demo
serveur
if [ -n "$DISPLAY" ]; then dire "Atelier sur $API (WebGL par l'affichage $DISPLAY)"; else dire "Atelier sur $API (sans WebGL)"; fi

cd "$RACINE" || exit 1
"$PY" "$OUTILS_COQUE" critere-31 --api "$API" ${CRITERE31_TAILLES:+--tailles "$CRITERE31_TAILLES"} \
  ${CRITERE31_MODES:+--modes "$CRITERE31_MODES"} 2>&1 | tee "$TRAVAIL/journaux/critere_31.log"
CODE=${PIPESTATUS[0]}
[ $CODE -eq 77 ] && en_attente "Firefox sans fenêtre ne démarre pas"
[ $CODE -eq 0 ] || echoue "$(grep -E '^ÉCHEC' "$TRAVAIL/journaux/critere_31.log" | tail -n 1 | cut -c1-600)"

if [ -n "$CRITERE31_CAPTURES" ]; then
  "$PY" "$OUTILS_COQUE" captures --api "$API" --sortie "$CRITERE31_CAPTURES" || echoue "captures impossibles"
fi
reussi "accueil, espace de travail sans défilement à trois tailles et trois modes, anciennes adresses, thème clair, aucune erreur"
