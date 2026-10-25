#!/usr/bin/env bash
# Lance les critères de recette (sections 7 et 9.10 du plan), sans fenêtre, et affiche « N / 15 ».
#   tests_e2e/tout.sh            les 15 critères, dans l'ordre
#   tests_e2e/tout.sh 1 2 8      seulement ceux-là
#   tests_e2e/tout.sh 11 12 13   le scan intégré : le 11 garde sa session pour le 12 et le 13
# Journal de chaque critère : ~/robot-g1/journaux/e2e_<date>/critere_NN.log
# Le critère 10 n'est compté que si son script réussit ET que les critères 1 à 9 réussissent.
# Code de sortie : 0 si tout ce qui a été lancé est réussi, 1 sinon.
E2E="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
JOURNAUX="$(cd "$E2E/.." && pwd)/journaux/e2e_$(date +%Y-%m-%d_%Hh%M)"
mkdir -p "$JOURNAUX"
TOUS=(1 2 3 4 5 6 7 8 9 10 11 12 13 14 15)

# Délai maximal de chaque critère, en secondes (le 13 relance le 11 s'il n'a pas de session gardée)
declare -A DELAI=([1]=300 [2]=600 [3]=300 [4]=900 [5]=1200 [6]=3600 [7]=1800 [8]=1200 [9]=1200 [10]=300
                  [11]=1800 [12]=900 [13]=3000 [14]=1800 [15]=900)
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
