#!/usr/bin/env bash
# Critère 35, caméra : de la fausse source aux visiteurs (section 12.10 du plan, agent Caméra), sans
# fenêtre ni robot ni caméra :
#   1. camera_usb avec source:=fichier (vidéo YUYV de 1280 × 720 fabriquée depuis bus.jpg d'ultralytics) :
#      /camera_poitrine/image/compressed à 8 Hz au moins, JPEG lisibles de 640 pixels de large ;
#      /camera_poitrine/etat conforme (etat_camera), ouverte vrai ;
#   2. l'Atelier dans le même domaine : GET /api/camera/image?source=poitrine rend un JPEG de moins de
#      1 s ; GET /api/camera/flux?source=poitrine&images=5 rend 5 images en moins de 2 s ;
#      GET /api/camera/etat cohérent ;
#   3. g1-visiteurs --source robot : /visiteurs/detectes conforme au schéma personnes (source camera), au
#      moins 3 personnes sur l'image du bus, chacune avec une boite dans l'image (640 × 360), en moins de
#      60 s après le lancement (chargement du modèle) ; le champ visiteurs de /ws/etat les montre ;
#   4. la vue Caméra dans Firefox sans fenêtre (page d'essai, puis l'écran Caméra de l'Atelier) :
#      [data-role=camera-flux] reçoit des images (naturalWidth 640), [data-role=camera-cadres] dessine
#      au moins 3 cadres ;
#   5. conteneur, à blanc (g1-jetson demarrer --local --dry-run) : avec une fausse caméra by-id,
#      --device …:/dev/g1_camera, --group-add et G1_CAMERA ; sans caméra, ni --device ni échec ;
#      G1_VITESSE_MAX=0.15 refusé ;
#   6. aucun processus restant.
# Sans le modèle YOLO (modeles/yolo/yolo11n-pose.pt) ou sans ultralytics : « en attente » (77).
source "$(dirname "$0")/commun.sh"
OUTILS35="$E2E/outils_camera_e2e.py"
exiger_commande g1-atelier g1-visiteurs g1-jetson
exiger_paquet_ros g1_equipe
ros2 pkg executables g1_equipe 2>/dev/null | grep -q "camera_usb" \
  || en_attente "le paquet g1_equipe compilé n'a pas l'exécutable camera_usb (colcon build, ou E2E_OVERLAY)"
[ -f "$RACINE/modeles/yolo/yolo11n-pose.pt" ] || en_attente "modèle YOLO absent : modeles/yolo/yolo11n-pose.pt"
"$PY" -c "import ultralytics" 2> /dev/null || en_attente "ultralytics absent de .venv-projet"

# restes : plus aucun camera_usb, v4l2-ctl ni g1-visiteurs du critère
restes() {
  sleep 1
  "$PY" "$OUTILS35" restes --travail "$TRAVAIL" "$@"
}

# 1. La caméra de poitrine, sur une fausse vidéo (le bus d'ultralytics)
"$PY" "$OUTILS35" video --sortie "$TRAVAIL/bus.yuyv"
code=$?
[ $code -eq 77 ] && en_attente "pas de vidéo de test (ultralytics ?)"
[ $code -eq 0 ] || echoue "vidéo de test impossible à fabriquer"
lancer_fond camera ros2 run g1_equipe camera_usb --ros-args -p source:=fichier -p "fichier:=$TRAVAIL/bus.yuyv"
CAMERA=$DERNIER
"$PY" "$OUTILS35" images --delai 30 || echoue "images de la caméra (journal camera.log)"

# 2. L'Atelier dans le même domaine : image, flux MJPEG, état
copier_demo essai
serveur
"$PY" "$OUTILS35" atelier --api "$API" || echoue "routes /api/camera/* de l'Atelier"

# 3. g1-visiteurs sur l'image du robot : les visiteurs du bus
debut=$(date +%s.%N)
lancer_fond visiteurs g1-visiteurs --source robot --image
VISITEURS=$DERNIER
"$PY" "$OUTILS35" visiteurs --api "$API" --delai 60 --depuis "$debut" \
  || echoue "g1-visiteurs (journal visiteurs.log : $(tail -n 2 "$TRAVAIL/journaux/visiteurs.log" | tr '\n' ' '))"

# 4. La vue Caméra dans Firefox sans fenêtre
"$PY" "$OUTILS35" navigateur --api "$API"
code=$?
[ $code -eq 77 ] && en_attente "Firefox ou geckodriver absent : la vue Caméra n'a pas pu être essayée"
[ $code -eq 0 ] || echoue "la vue Caméra dans Firefox"

# 5. Le conteneur du Jetson, à blanc : la caméra seulement si elle est branchée, vitesse minimale
"$PY" "$OUTILS35" conteneur || echoue "g1-jetson demarrer à blanc (caméra, G1_VITESSE_MAX)"

# 6. Tout s'arrête
arreter_groupe "$VISITEURS"
arreter_groupe "$CAMERA"
SERVEUR_PID=$(pgrep -f "uvicorn atelier.serveur.main:app .*--port $PORT" | tr '\n' ' ')
restes --sauf $SERVEUR_PID || echoue "des processus de la caméra restent"
for p in "${GROUPES[@]}"; do arreter_groupe "$p"; done
restes || echoue "des processus restent après l'arrêt du serveur"
reussi "caméra (fausse vidéo) → Atelier (image, flux, état) → g1-visiteurs (3 personnes) → Firefox ; conteneur à blanc"
