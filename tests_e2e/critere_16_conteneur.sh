#!/usr/bin/env bash
# Critère 16 (section 7 du plan, agent Jetson) : le conteneur g1-jetson, essayé sur le PC.
#   - g1-jetson construire --arch amd64 réussit (une image à jour est réutilisée) ; dans l'image :
#     ros2 pkg prefix g1_nav g1_bridge unitree_api, RMW_IMPLEMENTATION=rmw_cyclonedds_cpp,
#     import atelier.lieu, atelier.scan.slam_client ;
#   - g1-jetson demarrer --local sur une copie du demo, étage rdc : rend la main en moins de 60 s ;
#   - en moins de 90 s, l'hôte (même domaine, hors du conteneur) voit pont_g1, odom_vers_tf, guide,
#     bt_navigator et map_server ; il reçoit /g1_jetson/etat, /pont/etat (conforme, attente_reperage),
#     /reperage/etat (conforme, non_repere) et /guide/etat ;
#   - /pont/arret true publié par l'hôte donne arret_verrouille en moins de 3 s ;
#   - g1-jetson etat --local répond 0 ; g1-jetson arreter --local s'arrête en moins de 30 s (le pont
#     envoie un arrêt en quittant), et plus aucun conteneur g1-jetson-e2e-* ne reste ;
#   - G1_INTERFACES=auto, sans adresse 192.168.123.x : le conteneur s'arrête sur « réseau du robot
#     introuvable » ;
#   - avec E2E_NIVEAU2=1 (en plus du contrat) : le niveau 2 en répétition, navigation dans le
#     conteneur (G1_SIMU=true), Gazebo --jumeau et faux slam_operate sur l'hôte : repérage, puis b204 ;
#   - jamais de ssh (faux ssh et scp qui notent tout appel). Avec E2E_ARM64=1 : aussi
#     construire --arch arm64, puis les mêmes vérifications de l'image sous émulation (aarch64) ;
#     en plus du contrat, la navigation de l'image arm64 tourne sur le PC et se pilote de l'hôte.
# Le service « sport » du robot est remplacé par un faux minimal sur l'hôte (critere_16_outils.py) :
# sans réponse, le pont serait « robot_muet ».
# Seuls les conteneurs de ce domaine (g1-jetson-e2e-<domaine>*) sont comptés et retirés : un autre
# agent peut faire tourner le sien en même temps.
# Domaine : E2E_DOMAINE (36 par défaut, 61 pour l'agent Jetson). Durée : 15 s si l'image est à
# jour (2 min avec E2E_ARM64=1), plus la construction si elle manque (2 à 5 min, avec Internet).
source "$(dirname "$0")/commun.sh"
OUTILS16="$E2E/critere_16_outils.py"
export G1_JETSON_NOM="g1-jetson-e2e-$ROS_DOMAIN_ID"

command -v docker > /dev/null || en_attente "Docker n'est pas installé"
docker info > /dev/null 2>&1 || en_attente "Docker inutilisable sans sudo (groupe docker ?)"
exiger_commande g1-jetson
[ -f "$RACINE/ws/src/g1_bridge/package.xml" ] || en_attente "le paquet g1_bridge n'existe pas encore (agent Pont)"

# Jamais de ssh ni de scp : de faux programmes en tête du PATH notent tout appel
mkdir -p "$TRAVAIL/faux_bin"
for p in ssh scp; do
  printf '#!/bin/sh\necho "%s $*" >> "%s"\nexit 255\n' "$p" "$TRAVAIL/appels_ssh.txt" > "$TRAVAIL/faux_bin/$p"
  chmod +x "$TRAVAIL/faux_bin/$p"
done
export PATH="$TRAVAIL/faux_bin:$PATH"

# Ménage des conteneurs du test, même après une erreur (en plus de celui de commun.sh)
nettoyer_conteneurs() {
  local restes
  restes=$(docker ps -aq --filter "name=^g1-jetson-e2e-$ROS_DOMAIN_ID" 2>/dev/null)
  [ -n "$restes" ] && docker rm -f $restes > /dev/null 2>&1
}
trap 'code=$?; nettoyer_conteneurs; (exit $code); nettoyer' EXIT
nettoyer_conteneurs

# vérifier_image ARCH : paquets, RMW et Python de l'Atelier dans l'image (et architecture)
verifier_image() {
  local arch="$1" attendue sortie
  attendue=$([ "$arch" = arm64 ] && echo aarch64 || echo x86_64)
  sortie=$(docker run --rm --platform "linux/$arch" --network none --entrypoint bash "g1-jetson:$arch" -c '
    source /opt/g1/env.sh > /dev/null
    echo "arch=$(uname -m)"
    echo "rmw=$RMW_IMPLEMENTATION"
    for p in g1_nav g1_bridge unitree_api; do echo "prefix_$p=$(ros2 pkg prefix $p 2>&1)"; done
    python3 -c "import atelier.lieu, atelier.scan.slam_client; print(\"python=ok\")" 2>&1
    ros2 launch g1_nav navigation.launch.py --show-args 2>/dev/null | grep -q "localisation" && echo "launch=ok"' 2>&1)
  echo "$sortie" > "$TRAVAIL/journaux/image_$arch.log"
  grep -qx "arch=$attendue" <<< "$sortie" || echoue "image $arch : architecture $(grep '^arch=' <<< "$sortie") au lieu de $attendue"
  grep -qx "rmw=rmw_cyclonedds_cpp" <<< "$sortie" || echoue "image $arch : RMW_IMPLEMENTATION faux ($(grep '^rmw=' <<< "$sortie"))"
  for p in g1_nav g1_bridge unitree_api; do
    grep -qx "prefix_$p=/opt/g1/install/$p" <<< "$sortie" \
      || echoue "image $arch : ros2 pkg prefix $p ne donne pas /opt/g1/install/$p ($(grep "^prefix_$p=" <<< "$sortie"))"
  done
  grep -qx "python=ok" <<< "$sortie" || echoue "image $arch : import atelier.lieu, atelier.scan.slam_client impossible"
  grep -qx "launch=ok" <<< "$sortie" \
    || en_attente "navigation.launch.py de l'image ne connaît pas encore localisation:= (agent Repérage) : reconstruire ensuite"
  dire "image $arch : $attendue, rmw_cyclonedds_cpp, g1_nav, g1_bridge et unitree_api dans /opt/g1/install, imports Python réussis"
}

# --- 1. L'image amd64 ----------------------------------------------------------------------
dire "1. g1-jetson construire --arch amd64"
g1-jetson construire --arch amd64 > "$TRAVAIL/journaux/construire_amd64.log" 2>&1 \
  || echoue "g1-jetson construire --arch amd64 a échoué ($(tail -n 3 "$TRAVAIL/journaux/construire_amd64.log" | tr '\n' ' '))"
grep -E "réutilisée|construite en" "$TRAVAIL/journaux/construire_amd64.log" | sed "s/^/[$NOM_TEST]   /"
verifier_image amd64

# --- 2. Démarrage local sur une copie du demo ----------------------------------------------
dire "2. faux service sport sur l'hôte, puis g1-jetson demarrer --local"
copier_demo essai
lancer_fond service_sport "$PY" "$OUTILS16" service-sport --journal "$TRAVAIL/ordres.jsonl"
debut=$(date +%s%3N)
g1-jetson demarrer --local --lieu essai --etage rdc > "$TRAVAIL/journaux/demarrer.log" 2>&1 \
  || echoue "g1-jetson demarrer --local a échoué ($(tail -n 4 "$TRAVAIL/journaux/demarrer.log" | tr '\n' ' '))"
duree_ms=$(( $(date +%s%3N) - debut ))
(( duree_ms < 60000 )) || echoue "g1-jetson demarrer a mis $(( duree_ms / 1000 )) s (60 s au plus)"
dire "   rendu la main en $(( duree_ms / 1000 )),$(( duree_ms % 1000 / 100 )) s : $(grep 'g1-jetson : domaine' "$TRAVAIL/journaux/demarrer.log")"

# --- 3. Ce que voit l'hôte -----------------------------------------------------------------
dire "3. l'hôte (domaine $ROS_DOMAIN_ID, hors du conteneur) doit voir les nœuds et les états (90 s au plus)"
"$PY" "$OUTILS16" observer --noeuds pont_g1,odom_vers_tf,guide,bt_navigator,map_server --delai 90 \
  > "$TRAVAIL/observation.json" 2> "$TRAVAIL/journaux/observer.log"
code=$?
docker logs "$G1_JETSON_NOM" > "$TRAVAIL/journaux/conteneur.log" 2>&1
"$PY" - "$TRAVAIL/observation.json" <<'EOF' | sed "s/^/[critere_16_conteneur]    /"
import json, sys
b = json.load(open(sys.argv[1]))
print(f"en {b['duree_s']} s ; nœuds vus (s) : {b['noeuds_vus']} ; manquants : {b['noeuds_manquants']}")
for s, v in b['sujets'].items():
    print(f"{s} : {v['messages']} messages, états {v['etats']}")
for n in b['non_conformes']:
    print(f"NON CONFORME : {n}")
EOF
[ $code -eq 0 ] || echoue "l'hôte ne voit pas tout ce qu'il faut (bilan ci-dessus, journal du conteneur : $TRAVAIL/journaux/conteneur.log)"
# La même chose avec l'outil de tous les jours, depuis l'hôte
ros2 node list --no-daemon > "$TRAVAIL/journaux/node_list.log" 2>&1
for n in pont_g1 odom_vers_tf guide bt_navigator map_server; do
  grep -qx "/$n" "$TRAVAIL/journaux/node_list.log" || echoue "ros2 node list (hôte, domaine $ROS_DOMAIN_ID) ne montre pas /$n"
done
dire "   ros2 node list --no-daemon (hôte) : $(wc -l < "$TRAVAIL/journaux/node_list.log") nœuds, dont pont_g1, odom_vers_tf, guide, bt_navigator, map_server"

# --- 4. Verrou depuis l'hôte ---------------------------------------------------------------
dire "4. /pont/arret true publié par l'hôte : arret_verrouille en moins de 3 s"
verrou=$("$PY" "$OUTILS16" verrouiller --delai 3 2>> "$TRAVAIL/journaux/verrou.log") \
  || echoue "pas d'arret_verrouille en 3 s ($verrou)"
dire "   $verrou"

# --- 5. État, puis arrêt -------------------------------------------------------------------
dire "5. g1-jetson etat --local, puis arreter --local (30 s au plus)"
g1-jetson etat --local > "$TRAVAIL/journaux/etat.log" 2>&1 || echoue "g1-jetson etat --local ne répond pas 0 ($(cat "$TRAVAIL/journaux/etat.log"))"
sed "s/^/[$NOM_TEST]    /" "$TRAVAIL/journaux/etat.log"
g1-jetson etat --local --json > "$TRAVAIL/etat.json" 2>/dev/null
"$PY" -c "import json, sys; e = json.load(open(sys.argv[1])); sys.exit(0 if e['en_marche'] and e['presence'] and e['presence']['lancement'] == 'navigation' else 1)" \
  "$TRAVAIL/etat.json" || echoue "g1-jetson etat --json : pas de /g1_jetson/etat ($(cat "$TRAVAIL/etat.json"))"
arret=$(date +%s.%N)
debut=$(date +%s%3N)
g1-jetson arreter --local > "$TRAVAIL/journaux/arreter.log" 2>&1 || echoue "g1-jetson arreter --local a échoué ($(cat "$TRAVAIL/journaux/arreter.log"))"
duree_ms=$(( $(date +%s%3N) - debut ))
(( duree_ms < 30000 )) || echoue "g1-jetson arreter a mis $(( duree_ms / 1000 )) s (30 s au plus)"
dire "   arrêté en $(( duree_ms / 1000 )),$(( duree_ms % 1000 / 100 )) s : $(tail -n 2 "$TRAVAIL/journaux/arreter.log" | tr '\n' ' ')"
[ -z "$(docker ps -aq --filter "name=^g1-jetson-e2e-$ROS_DOMAIN_ID")" ] || echoue "un conteneur g1-jetson-e2e-$ROS_DOMAIN_ID* reste : $(docker ps -a --filter "name=^g1-jetson-e2e-$ROS_DOMAIN_ID" --format '{{.Names}} {{.Status}}')"
ordre=$("$PY" "$OUTILS16" dernier-ordre --journal "$TRAVAIL/ordres.jsonl" --apres "$arret") \
  || echoue "le pont n'a pas envoyé d'arrêt (7105 [0, 0, 0]) en quittant ($ordre)"
dire "   le pont a envoyé un arrêt en quittant : $ordre"

# --- 6. G1_INTERFACES=auto sans réseau du robot --------------------------------------------
dire "6. G1_INTERFACES=auto sur une machine sans 192.168.123.x : le conteneur doit s'arrêter"
if ip -o -4 addr | grep -q ' inet 192\.168\.123\.'; then
  dire "   ce PC a une adresse 192.168.123.x (câble du robot) : cas impossible à essayer ici, sauté"
else
  G1_JETSON_NOM="g1-jetson-e2e-$ROS_DOMAIN_ID-auto" G1_INTERFACES=auto \
    g1-jetson demarrer --local --lieu essai --etage rdc > "$TRAVAIL/journaux/auto.log" 2>&1 \
    && echoue "avec G1_INTERFACES=auto sans réseau du robot, g1-jetson demarrer a réussi"
  grep -q "réseau du robot introuvable" "$TRAVAIL/journaux/auto.log" \
    || echoue "pas de message « réseau du robot introuvable » ($(tail -n 3 "$TRAVAIL/journaux/auto.log" | tr '\n' ' '))"
  dire "   $(grep -m1 'réseau du robot introuvable' "$TRAVAIL/journaux/auto.log" | cut -c1-160)…"
  G1_JETSON_NOM="g1-jetson-e2e-$ROS_DOMAIN_ID-auto" g1-jetson arreter --local > /dev/null 2>&1
  [ -z "$(docker ps -aq --filter "name=^g1-jetson-e2e-$ROS_DOMAIN_ID")" ] || echoue "le conteneur de l'essai auto reste"
fi

# --- 7. Option : le niveau 2 en répétition, la navigation dans le conteneur ---------------
# E2E_NIVEAU2=1 (en plus du contrat) : Gazebo --jumeau (faux G1) et le faux slam_operate sur l'hôte,
# la navigation dans le conteneur (G1_SIMU=true) ; repérage à la marque, puis g1-guide aller b204 :
# arrivée à moins de 0,3 m (vérité /g1_jumeau/odom), tout le mouvement par le pont et le faux G1.
if [ "$E2E_NIVEAU2" = 1 ]; then
  dire "7. E2E_NIVEAU2=1 : niveau 2 en répétition, navigation dans le conteneur"
  if ! ros2 pkg prefix g1_jumeau > /dev/null 2>&1 \
     || ! grep -q jumeau "$(ros2 pkg prefix g1_sim)/share/g1_sim/launch/simulation.launch.py" 2>/dev/null; then
    dire "   g1_jumeau ou l'argument jumeau de g1_sim manque : étape sautée"
  else
    generer essai
    lancer_fond simulation g1-monde simuler --lieu essai --etage rdc --sans-fenetre --jumeau
    PID_SIMULATION=$DERNIER
    "$PY" "$OUTILS" attendre-sujets /g1_jumeau/odom /clock --delai 90 || echoue "Gazebo --jumeau ne publie pas /g1_jumeau/odom"
    lancer_fond faux_slam g1-slam faux-service --jumeau --lieu essai --etage rdc
    PID_FAUX_SLAM=$DERNIER
    export G1_JETSON_NOM="g1-jetson-e2e-$ROS_DOMAIN_ID-niveau2"
    debut=$(date +%s)
    G1_SIMU=true g1-jetson demarrer --local --lieu essai --etage rdc > "$TRAVAIL/journaux/demarrer_niveau2.log" 2>&1 \
      || echoue "g1-jetson demarrer (G1_SIMU=true) a échoué ($(tail -n 3 "$TRAVAIL/journaux/demarrer_niveau2.log" | tr '\n' ' '))"
    reperage=$("$PY" "$OUTILS16" reperer --delai 60 2>> "$TRAVAIL/journaux/reperer.log") || echoue "repérage impossible ($reperage)"
    dire "   repéré : $(cut -c1-150 <<< "$reperage")…"
    read -r X Y < <("$PY" -c "import sys; from atelier.lieu import charger_salles; s = [s for s in charger_salles(sys.argv[1]) if s.id == 'b204'][0]; print(s.pose.x, s.pose.y)" "$ATELIER_LIEUX/essai")
    timeout 300 g1-guide aller b204 > "$TRAVAIL/journaux/aller.log" 2>&1 \
      || { docker logs "$G1_JETSON_NOM" > "$TRAVAIL/journaux/conteneur_niveau2.log" 2>&1; echoue "g1-guide aller b204 n'est pas arrivé"; }
    ecart=$("$PY" "$OUTILS16" verite --x "$X" --y "$Y" --max 0.3) || echoue "robot loin de b204 : $ecart"
    dire "   arrivé à b204 en $(( $(date +%s) - debut )) s depuis le démarrage du conteneur : $ecart"
    g1-jetson arreter --local > "$TRAVAIL/journaux/arreter_niveau2.log" 2>&1 || echoue "arrêt du conteneur (niveau 2) impossible"
    export G1_JETSON_NOM="g1-jetson-e2e-$ROS_DOMAIN_ID"
    arreter_groupe "$PID_FAUX_SLAM"
    arreter_groupe "$PID_SIMULATION"
  fi
fi

# --- 8. Option : l'image arm64 sous émulation ----------------------------------------------
if [ "$E2E_ARM64" = 1 ]; then
  dire "8. E2E_ARM64=1 : g1-jetson construire --arch arm64 (émulation qemu)"
  g1-jetson construire --arch arm64 > "$TRAVAIL/journaux/construire_arm64.log" 2>&1 \
    || echoue "g1-jetson construire --arch arm64 a échoué ($(tail -n 3 "$TRAVAIL/journaux/construire_arm64.log" | tr '\n' ' '))"
  verifier_image arm64
  # En plus du contrat : l'image du robot fait vraiment tourner la navigation (émulation, lent).
  # Sous qemu-user, setsockopt(IP_MULTICAST_IF) n'est pas émulé : CycloneDDS ne crée pas son
  # domaine avec le multicast. Ici, le conteneur et l'hôte se parlent donc en unicast sur lo
  # (pairs 127.0.0.1). Le vrai Jetson, natif, n'est pas concerné.
  dire "   la navigation de l'image arm64, lancée sur le PC par émulation (G1_JETSON_ARCH=arm64, DDS unicast sur lo)"
  URI_LO='<CycloneDDS><Domain Id="any"><General><Interfaces><NetworkInterface name="lo"/></Interfaces><AllowMulticast>false</AllowMulticast></General><Discovery><ParticipantIndex>auto</ParticipantIndex><MaxAutoParticipantIndex>100</MaxAutoParticipantIndex><Peers><Peer address="127.0.0.1"/></Peers></Discovery></Domain></CycloneDDS>'
  lancer_fond service_sport_arm64 env CYCLONEDDS_URI="$URI_LO" "$PY" "$OUTILS16" service-sport --journal "$TRAVAIL/ordres_arm64.jsonl"
  export G1_JETSON_NOM="g1-jetson-e2e-$ROS_DOMAIN_ID-arm64"
  G1_CYCLONEDDS_URI="$URI_LO" G1_JETSON_ARCH=arm64 g1-jetson demarrer --local --lieu essai --etage rdc \
    > "$TRAVAIL/journaux/demarrer_arm64.log" 2>&1 \
    || echoue "g1-jetson demarrer (arm64) a échoué ($(tail -n 4 "$TRAVAIL/journaux/demarrer_arm64.log" | tr '\n' ' '))"
  CYCLONEDDS_URI="$URI_LO" "$PY" "$OUTILS16" observer --noeuds pont_g1,odom_vers_tf,guide,bt_navigator,map_server \
    --delai 300 > "$TRAVAIL/observation_arm64.json" 2> "$TRAVAIL/journaux/observer_arm64.log" \
    || { docker logs "$G1_JETSON_NOM" > "$TRAVAIL/journaux/conteneur_arm64.log" 2>&1;
         echoue "image arm64 : l'hôte ne voit pas tout ($(cat "$TRAVAIL/observation_arm64.json"))"; }
  dire "   arm64 : nœuds et états vus en $("$PY" -c "import json,sys; print(json.load(open(sys.argv[1]))['duree_s'])" "$TRAVAIL/observation_arm64.json") s"
  verrou=$(CYCLONEDDS_URI="$URI_LO" "$PY" "$OUTILS16" verrouiller --delai 10 2>> "$TRAVAIL/journaux/verrou.log") \
    || echoue "image arm64 : pas d'arret_verrouille en 10 s ($verrou)"
  dire "   arm64 : $verrou"
  arret=$(date +%s.%N)
  g1-jetson arreter --local > "$TRAVAIL/journaux/arreter_arm64.log" 2>&1 || echoue "arrêt du conteneur arm64 impossible"
  dire "   arm64 : $(tail -n 2 "$TRAVAIL/journaux/arreter_arm64.log" | tr '\n' ' ')"
  "$PY" "$OUTILS16" dernier-ordre --journal "$TRAVAIL/ordres_arm64.jsonl" --apres "$arret" > /dev/null \
    || echoue "image arm64 : le pont n'a pas envoyé d'arrêt en quittant"
  [ -z "$(docker ps -aq --filter "name=^g1-jetson-e2e-$ROS_DOMAIN_ID")" ] || echoue "un conteneur g1-jetson-e2e-* reste"
fi

# --- Jamais de ssh -------------------------------------------------------------------------
[ ! -s "$TRAVAIL/appels_ssh.txt" ] || echoue "ssh ou scp a été appelé : $(cat "$TRAVAIL/appels_ssh.txt")"
reussi "conteneur construit, démarré, vu de l'hôte, verrouillé et arrêté proprement ; jamais de ssh"
