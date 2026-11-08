#!/usr/bin/env bash
# Lance les critères de recette (sections 7, 9.10, 10, 11, 12 et 13 du plan), sans fenêtre, et affiche « N / 42 ».
#   tests_e2e/tout.sh            les 42 critères, dans l'ordre
#   tests_e2e/tout.sh 1 2 8      seulement ceux-là
#   tests_e2e/tout.sh 11 12 13   le scan intégré : le 11 garde sa session pour le 12 et le 13
#   tests_e2e/tout.sh 16 17 18 19 20   le vrai robot en répétition : conteneur, pont, repérage, niveau 2
#   tests_e2e/tout.sh 21 22 23 24 25 26 27 28 29 30   la vague 4 : point principal, retour, passants,
#                                accompagnement, robot perdu, pilotage, danses, équipe
#   tests_e2e/tout.sh 31 32 33 34 35 36   la vague 5 (section 12.10 du plan) : coque, carte 3D, scan corrigé,
#                                vitesse minimale et mode du pont, caméra, ARRÊT global
#   tests_e2e/tout.sh 37 38 39 40 41 42   la vague 6 (section 13.9 du plan) : diagnostic, boîte noire et rapport,
#                                borne, voix, démo complète en simulation, sécurité de la démo
# Un critère dont le script n'existe pas encore est « absent » : il compte comme non réussi.
# Journal de chaque critère : ~/robot-g1/journaux/e2e_<date>/critere_NN.log
# Le critère 10 n'est compté que si son script réussit ET que les critères 1 à 9 réussissent.
# Code de sortie : 0 si tout ce qui a été lancé est réussi, 1 sinon.
E2E="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
JOURNAUX="$(cd "$E2E/.." && pwd)/journaux/e2e_$(date +%Y-%m-%d_%Hh%M)"
mkdir -p "$JOURNAUX"
TOUS=(1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32 33 34 35 36 37 38 39 40 41 42)

# Délai maximal de chaque critère, en secondes (le 13 relance le 11 s'il n'a pas de session gardée ;
# le 16 construit l'image du conteneur si elle manque : environ 15 min la première fois, avec Internet)
declare -A DELAI=([1]=300 [2]=600 [3]=300 [4]=900 [5]=1200 [6]=3600 [7]=1800 [8]=1200 [9]=1200 [10]=300
                  [11]=1800 [12]=900 [13]=3000 [14]=1800 [15]=900
                  [16]=3600 [17]=1200 [18]=1500 [19]=2400 [20]=1800
                  [21]=1200 [22]=900 [23]=1800 [24]=3000 [25]=3600 [26]=1800 [27]=1500 [28]=1200 [29]=1200
                  [30]=1200
                  [31]=1200 [32]=1200 [33]=3600 [34]=1500 [35]=1200 [36]=1500
                  [37]=900 [38]=1800 [39]=1200 [40]=900 [41]=2700 [42]=1800)
CHOIX=("$@")
[ ${#CHOIX[@]} -eq 0 ] && CHOIX=("${TOUS[@]}")

declare -A ETAT
REUSSIS=0
for n in "${CHOIX[@]}"; do
  script=$(ls "$E2E"/critere_$(printf '%02d' "$n")_*.sh 2>/dev/null | head -n 1)
  if [ -z "$script" ]; then
    ETAT[$n]="absent"; continue
  fi
  nom=$(basename "$script" .sh)
  echo "=== $nom (au plus ${DELAI[$n]} s)"
  debut=$SECONDS
  timeout --kill-after=30 "${DELAI[$n]}" "$script" > "$JOURNAUX/$nom.log" 2>&1
  code=$?
  duree=$(( SECONDS - debut ))
  case $code in
    0) ETAT[$n]="réussi"; REUSSIS=$((REUSSIS + 1)) ;;
    77) ETAT[$n]="en attente" ;;
    124|137) ETAT[$n]="délai dépassé" ;;
    *) ETAT[$n]="échoué" ;;
  esac
  grep -E "^\[$nom\] (RÉUSSI|ÉCHOUÉ|PAS ENCORE)" "$JOURNAUX/$nom.log" | tail -n 1
  echo "    → ${ETAT[$n]} en $duree s"
done

# Le critère 10 exige les neuf premiers
if [ "${ETAT[10]}" = "réussi" ]; then
  for n in 1 2 3 4 5 6 7 8 9; do
    if [ "${ETAT[$n]}" != "réussi" ]; then
      ETAT[10]="réussi, mais pas les 9 autres"
      REUSSIS=$((REUSSIS - 1))
      break
    fi
  done
fi

echo
echo "Bilan (journaux : $JOURNAUX)"
for n in "${TOUS[@]}"; do
  [ -n "${ETAT[$n]}" ] && printf "  critère %2d : %s\n" "$n" "${ETAT[$n]}"
done
echo
if [ ${#CHOIX[@]} -eq ${#TOUS[@]} ]; then
  echo "$REUSSIS / ${#TOUS[@]}"
else
  echo "$REUSSIS / ${#CHOIX[@]} (critères ${CHOIX[*]})"
fi
[ "$REUSSIS" -eq "${#CHOIX[@]}" ]
