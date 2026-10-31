#!/usr/bin/env bash
# Critère 32, placer l'accueil et une salle dans la carte 3D (section 12.10 du plan, décisions I7 et I8) :
# agent Carte 3D. Sans robot, sans fenêtre : Firefox sans fenêtre avec WebGL (carte graphique du PC), sur
# une copie du demo (id « demo ») avec un nuage d'étage de test (cartes/rdc.nuage.bin, écrit par
# ecrire_nuage depuis le monde du demo : murs et objets tous les 5 cm). On vérifie, par la coque
# (outils : tests_e2e/outils_carte3d_e2e.py) :
#   - Réel (répétition) › Placer : la vue 3D montre le nuage (window.carte3d.etat() : webgl vrai, points =
#     ceux de l'en-tête) ;
#   - commande salles.accueil, appui sur le sol en (3,0 ; 9,5) (versEcran), glissé vers (4,0 ; 9,5), ✓ OK :
#     dans salles.yaml le point principal est à 0,05 m et 2° près de (3,0 ; 9,5 ; 0), et l'accueil de
#     lieu.yaml et depart_robot aussi ;
#   - commande salles.salle, nouvelle salle « Essai 3D » posée en (12,0 ; 4,0), tournée vers −90°, ✓ OK :
#     salles.yaml la contient à 0,05 m et 2° près, avec son nœud dans itineraires.yaml ;
#   - en Plan 2D, les marqueurs de l'accueil et de la salle sont à ces coordonnées (lat = y, lng = x, à
#     0,05 m près) ; une salle déplacée en 2D est retrouvée en 3D (à 3 pixels près de son épingle) ;
#   - Dessus, Iso, Face et Recadrer changent la caméra ; la molette zoome vers le pointeur (le point du sol
#     sous le pointeur reste à 2 pixels près) ; Annuler puis Rétablir d'un placement ;
#   - WebGL coupé (préférence webgl.disabled) : [data-role=carte3d-sans-webgl], et le Plan 2D reste
#     utilisable ; aucune erreur dans la page ;
#   - en plus, les tests de la carte seule (page d'essai essais/carte3d.html) : atelier/tests/test_carte3d_*.py.
# En attente (77) si une pièce manque : la coque, sa vue 3D ou ses commandes (agent Coquille), Firefox.
# Captures : CRITERE32_CAPTURES=dossier (facultatif).
# WebGL : Firefox sans fenêtre n'en a qu'avec un affichage X (DISPLAY, ex. :1 de la session graphique) ;
# commun.sh retire DISPLAY (Gazebo et RViz sans fenêtre) : on le rend à Firefox seul, qui n'ouvre toujours
# aucune fenêtre. Sans affichage : en attente (77), avec la raison.
AFFICHAGE_X="${DISPLAY:-}"
source "$(dirname "$0")/commun.sh"
[ -n "$AFFICHAGE_X" ] || en_attente "WebGL indisponible : Firefox sans fenêtre a besoin d'un affichage X (DISPLAY, ex. DISPLAY=:1)"
export DISPLAY="$AFFICHAGE_X"
exiger_commande g1-atelier
OUTILS3D="$E2E/outils_carte3d_e2e.py"
command -v geckodriver > /dev/null && command -v firefox > /dev/null \
  || en_attente "Firefox sans fenêtre (firefox et geckodriver) n'est pas installé"

# 1. les tests de la carte seule (fonctions, page d'essai, gestes réels)
cd "$RACINE" || exit 1
SORTIE=$(PYTHONDONTWRITEBYTECODE=1 "$PY" -m pytest -q -rs -p no:cacheprovider \
  atelier/tests/test_carte3d_web.py atelier/tests/test_carte3d_geometrie.py atelier/tests/test_carte3d_navigateur.py 2>&1)
CODE=$?
echo "$SORTIE" | tail -n 6
[ $CODE -eq 0 ] || echoue "les tests de la carte 3D seule échouent (atelier/tests/test_carte3d_*.py)"
echo "$SORTIE" | grep -E "^SKIPPED" | grep -qiE "firefox|geckodriver|webgl" \
  && echoue "des tests de la carte 3D ont été sautés faute de Firefox sans fenêtre ou de WebGL"
dire "tests de la carte 3D seule : $(echo "$SORTIE" | grep -oE '[0-9]+ passed' | tail -n 1)"

# 2. la copie du demo et son nuage de test
copier_demo demo
"$PY" "$OUTILS3D" nuage --lieu "$ATELIER_LIEUX/demo" || echoue "nuage de test non écrit"

# 3. l'Atelier (sans pont ROS 2 : rien de ROS dans ce critère), puis le parcours par la coque
export ATELIER_ROS=0
serveur
dire "Atelier sur $API"
ARGS_CAPTURES=()
[ -n "$CRITERE32_CAPTURES" ] && mkdir -p "$CRITERE32_CAPTURES" && ARGS_CAPTURES=(--captures "$CRITERE32_CAPTURES")
"$PY" "$OUTILS3D" parcours --api "$API" --lieu "$ATELIER_LIEUX/demo" "${ARGS_CAPTURES[@]}"
CODE=$?
[ $CODE -eq 77 ] && en_attente "parcours par la coque : une pièce manque (voir ci-dessus)"
[ $CODE -eq 0 ] || echoue "le parcours de la carte 3D par la coque a échoué (voir ci-dessus)"

# 4. sans WebGL
"$PY" "$OUTILS3D" sans-webgl --api "$API"
CODE=$?
[ $CODE -eq 77 ] && en_attente "sans WebGL : une pièce manque (voir ci-dessus)"
[ $CODE -eq 0 ] || echoue "sans WebGL, la coque ou le Plan 2D ne marchent pas (voir ci-dessus)"

reussi "accueil et salle placés dans la carte 3D, mêmes coordonnées que le Plan 2D, vues, molette, Annuler, sans WebGL"
