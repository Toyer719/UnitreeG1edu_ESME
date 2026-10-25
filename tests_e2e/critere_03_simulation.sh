#!/usr/bin/env bash
# Critère 3, simulation : g1-monde simuler --sans-fenetre démarre en moins de 30 s ;
# /points et /odom sont publiés.
source "$(dirname "$0")/commun.sh"
exiger_commande g1-monde
exiger_paquet_ros g1_sim
copier_demo essai
generer essai
DEBUT=$SECONDS
lancer_fond simulation g1-monde simuler --lieu essai --etage rdc --sans-fenetre
"$PY" "$OUTILS" attendre-sujets /odom /points --delai 30 --frequence /points=5 \
  || echoue "pas de /odom et /points à plus de 5 messages/s en 30 s"
reussi "simulation prête en $(( SECONDS - DEBUT )) s"
