#!/usr/bin/env bash
# Critère 8, service du robot simulé : avec g1-slam --faux, les commandes 1801, 1802, 1804 et
# 1102 suivent le bon déroulé ; MoteurUnitree mène le robot proxy de l'accueil à b204.
source "$(dirname "$0")/commun.sh"
exiger_commande g1-slam
copier_demo essai

# 1. Le déroulé, avec le faux service sur papier
lancer_fond faux_slam g1-slam faux-service --lieu essai
FAUX=$DERNIER
for _ in $(seq 1 100); do grep -q "prêt" "$TRAVAIL/journaux/faux_slam.log" && break; sleep 0.1; done
attendu() {   # attendu CODE COMMANDE... : g1-slam doit rendre ce code
  local code="$1"; shift
  g1-slam "$@" --faux > "$TRAVAIL/journaux/slam.log" 2>&1
  local obtenu=$?
  sed 's/^/    /' "$TRAVAIL/journaux/slam.log" | grep -v "multicast"
  [ "$obtenu" -eq "$code" ] || echoue "g1-slam $* : code $obtenu, attendu $code"
}
attendu 1 aller 3.5 10            # 1102 refusé : pas encore repéré (1804)
attendu 1 scan-fin --nom rdc      # 1802 refusé : pas de scan en cours (1801)
attendu 0 scan-debut              # 1801
attendu 0 scan-fin --nom rdc --lieu essai    # 1802, carte notée dans lieu.yaml
grep -q "carte_unitree: rdc.pcd" "$ATELIER_LIEUX/essai/lieu.yaml" || echoue "carte_unitree absente de lieu.yaml"
attendu 1 relocaliser --nom autre # 1804 refusé : carte inconnue
attendu 0 relocaliser --lieu essai --x 2.5 --y 10   # 1804
attendu 0 aller 3.5 10 0 --attendre 20              # 1102, jusqu'à is_arrived
attendu 0 arreter                                   # 1901
arreter_groupe "$FAUX"
dire "déroulé 1801 → 1802 → 1804 → 1102 correct"

# 2. MoteurUnitree mène le robot proxy de Gazebo de l'accueil à b204
exiger_commande g1-monde
exiger_paquet_ros g1_sim
generer essai
simuler essai
lancer_fond faux_gazebo g1-slam faux-service --gazebo --relocalise
for _ in $(seq 1 100); do grep -q "prêt" "$TRAVAIL/journaux/faux_gazebo.log" && break; sleep 0.1; done
"$PY" "$OUTILS" moteur-unitree --lieu essai --de accueil --vers b204 --delai 400 \
  || echoue "MoteurUnitree n'a pas mené le robot à b204"
"$PY" "$OUTILS" pres-de --lieu essai --salle b204 --max 0.3 || echoue "le robot n'est pas devant b204"
reussi "déroulé correct ; MoteurUnitree mène le robot proxy de l'accueil à b204"
