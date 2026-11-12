#!/usr/bin/env bash
# Critère 7, scan simulé : le robot proxy parcourt les couloirs du lieu demo simulé pendant
# l'enregistrement de /points et /odom, puis g1-carte-3d et g1-carte-2d ; la carte du scan
# recouvre la carte générée depuis le monde à au moins 80 % (pixels occupés, à 1 pixel près).
# Le robot est mené par MoteurUnitree et le faux service slam_operate (pas besoin de Nav2).
source "$(dirname "$0")/commun.sh"
exiger_commande g1-monde g1-slam g1-carte-3d g1-carte-2d
exiger_paquet_ros g1_sim
copier_demo essai
generer essai
L="$ATELIER_LIEUX/essai"
cp "$L/cartes/rdc.pgm" "$TRAVAIL/reference.pgm"
sed 's/^image: .*/image: reference.pgm/' "$L/cartes/rdc.yaml" > "$TRAVAIL/reference.yaml"
simuler essai

lancer_fond faux_slam g1-slam faux-service --gazebo --relocalise
for _ in $(seq 1 100); do grep -q "prêt" "$TRAVAIL/journaux/faux_slam.log" && break; sleep 0.1; done
grep -q "prêt" "$TRAVAIL/journaux/faux_slam.log" || echoue "le faux service ne démarre pas"
lancer_fond enregistrement ros2 bag record -o "$TRAVAIL/scan" /points /odom /tf_static
ENREGISTREMENT=$DERNIER
sleep 3

# Tour complet : couloir nord, liaison est, couloir sud, retour à l'accueil
PARCOURS=accueil,hall_nord,amphi,couloir_nord_1,b204,est_nord,est_sud,cdi,couloir_sud_2,infirmerie
PARCOURS=$PARCOURS,couloir_sud_1,vie_scolaire,hall_sud,accueil
"$PY" "$OUTILS" moteur-unitree --lieu essai --parcours "$PARCOURS" --delai 900 \
  || echoue "le robot n'a pas fini le tour des couloirs"
arreter_groupe "$ENREGISTREMENT"
[ -f "$TRAVAIL/scan/metadata.yaml" ] || echoue "enregistrement incomplet (pas de metadata.yaml)"
dire "enregistrement : $(du -sh "$TRAVAIL/scan" | cut -f1)"

g1-carte-3d --lieu essai --etage rdc --enregistrement "$TRAVAIL/scan" || echoue "g1-carte-3d a échoué"
SORTIE=$(g1-carte-2d --lieu essai --etage rdc --comparer "$TRAVAIL/reference.yaml" 2>&1)
CODE=$?; echo "$SORTIE"
[ $CODE -eq 0 ] || echoue "g1-carte-2d a échoué"
RECOUVREMENT=$(echo "$SORTIE" | sed -n 's/.*Recouvrement[^:]*: \([0-9.]*\) %.*/\1/p')
[ -n "$RECOUVREMENT" ] || echoue "recouvrement introuvable dans la sortie de g1-carte-2d"
"$PY" -c "import sys; sys.exit(0 if float('$RECOUVREMENT') >= 80 else 1)" \
  || echoue "recouvrement de $RECOUVREMENT %, moins de 80 %"
reussi "recouvrement de $RECOUVREMENT % avec la carte générée"
