"""Chapitre 8 : les chemins des données."""

BLOCS = [
    ("h1", "Les chemins des données"),
    ("chapeau", "Six trajets suivis de bout en bout, dans l'ordre où les choses se passent : le scan, un "
                "trajet vers une salle, le repérage au démarrage, le pilotage, la caméra, et la simulation "
                "avec la répétition."),

    ("h2", "Du scan à la carte et au nuage"),
    ("schema", "chaine_scan", "Du scan au lieu : enregistrement, traitement en trois étapes, adoption", 13.5, 14.5),
    ("num", [
        "Le robot est debout, en mode marche, sur le point de départ (qui deviendra l'origine de la carte : "
        "le plus simple est d'y mettre le point principal). Dans l'appli Unitree, les services `unitree_slam` "
        "et `lidar_driver` sont actifs.",
        "**Réel › Scanner › Scan** appelle `POST /api/scan/demarrer`, qui lance `g1-scan demarrer --mode robot`. "
        "Une session est créée ; son processus envoie l'ordre **1801** au SLAM d'Unitree et enregistre "
        "(`ros2 bag record`) `/unitree/slam_mapping/points` (un balayage du LiDAR, déjà placé dans le repère de "
        "la carte, 10 fois par seconde) et `/unitree/slam_mapping/odom` (la position du robot).",
        "Pendant le scan, un aperçu est réécrit toutes les 2 s : l'écran, en plein écran sombre, montre le "
        "nuage qui se remplit, le trajet, la durée, la distance et le nombre de points. On promène le robot "
        "lentement, à la télécommande.",
        "**Fin** envoie l'ordre **1802** (le robot enregistre sa propre carte `.pcd`), ferme l'enregistrement, "
        "puis lance le traitement, sans rien attendre de l'utilisateur.",
        "Étape **carte_3d** : chaque nuage est placé par la pose du même instant ; les points des passants sont "
        "retirés (une petite case de l'espace traversée par les rayons du LiDAR bien plus souvent qu'elle "
        "n'est touchée est un obstacle qui a bougé) ; le **sol est trouvé comme un plan** par RANSAC (on tire "
        "au hasard des trios de points, on garde le plan qui en contient le plus) ; le tout est réduit à une "
        "grille de 5 cm (`nuage.pcd`).",
        "Étape **carte_2d** : les points entre 0,1 et 1,5 m au-dessus du sol sont projetés sur une image de "
        "5 cm par pixel ; une case est occupée si elle a au moins 2 points ; les taches de moins de 4 cases "
        "sont du bruit. Résultat : `carte.pgm` et `carte.yaml`, au format de Nav2.",
        "Étape **nuage** : le nuage d'affichage (x, y, hauteur au-dessus du sol), pour la carte 3D ; puis "
        "`rapport.json`.",
        "**Utiliser cette carte** (`g1-scan adopter`) copie la carte, le nuage et le nuage d'affichage dans "
        "`cartes/`, passe l'étage en `source_carte: scan`, refait le masque des zones et le **monde maillé** "
        "de la simulation (la carte extrudée sur 1,5 m). Les salles ne bougent pas : elles sont dans le même "
        "repère `map`.",
    ]),
    ("p", "**Les trois bogues trouvés le 31/10.** L'utilisateur trouvait le scan de l'Atelier moins bon que "
          "celui d'Unitree Explore. L'analyse du vrai scan du 27/10 a montré que l'enregistrement était bon, "
          "mais que le traitement l'abîmait :"),
    ("table", {
        "entetes": ["Bogue", "Ce qui se passait", "Correction"],
        "largeurs": [2.8, 7.6, 6.2],
        "taille": 9,
        "premiere_col_gras": True,
        "lignes": [
            ["1. L'horloge", "Les nuages du robot ont une heure nulle ; le traitement prenait l'heure d'arrivée sur le "
             "PC, alors que l'odométrie a l'heure du robot, en retard de 138 s. 1 374 nuages sur 2 327 (59 %) "
             "étaient jetés, et les 953 gardés recevaient une pose prise 138 s plus tard (8,2 m d'erreur, en médiane).",
             "Une seule base de temps : chaque nuage est apparié à la pose reçue au même instant ; un nuage déjà "
             "placé n'est jamais jeté faute de pose."],
            ["2. Les passants", "Le retrait des obstacles mobiles partait de ces fausses positions du capteur : 39,7 % "
             "des cases du nuage retirées, dont des murs et des meubles.", "Le retrait part de la vraie position du capteur, et "
             "seulement de 0,08 à 2 m au-dessus du sol."],
            ["3. Le sol", "Le sol n'est pas horizontal dans le repère du robot (penché de 0,58°, 1 cm par mètre). "
             "Avec un seul niveau de sol, sur 45 % de la surface le sol entrait dans la tranche de la carte : un "
             "« damier » noir.", "Le sol est un plan (RANSAC) et les hauteurs sont mesurées au-dessus de ce plan, "
             "sans tourner le nuage (x et y ne changent pas)."],
        ],
    }),
    ("p", "Retraité le 31/10 avec la chaîne corrigée (`g1-scan traiter --refaire`), le scan du 27/10 (3 min 54 s, "
          "69,8 m parcourus, 2,73 millions de points reçus) garde ses **2 327 nuages sur 2 327** (953 avant), "
          "donne **299 558 points** (158 791 avant), retire 106 371 points de passants, trouve le sol penché de "
          "0,58°, et une carte de 239 × 403 pixels sans damier, en 4 secondes. La carte nettoyée à la main n'est "
          "plus nécessaire."),

    ("h2", "D'une salle à un pas du robot"),
    ("schema", "chaine_trajet", "Le chemin d'un trajet : le guide, Nav2, le pont, le robot", 16.6, 9.0),
    ("num", [
        "Dans l'Atelier, **Y aller** vers « b204 » appelle `POST /api/guide/aller`. En répétition et sur le "
        "robot, la réponse est 409 (« Repérez d'abord le robot ») tant que le robot n'est pas repéré. Sinon, "
        "le nœud `atelier_pont` publie la demande sur `/guide/aller` : l'identifiant seul (« b204 »), ou, "
        "avec les cases Accompagner et Retour, du JSON : "
        "`{\"cible\": \"b204\", \"accompagner\": true, \"retour\": true, \"source\": \"atelier\"}`.",
        "Le **guide** (`g1_nav/guide.py`) demande l'itinéraire au **routeur**, qui cherche le plus court chemin "
        "dans le graphe de `itineraires.yaml` (algorithme A*). Il passe à l'état `en_route` et annonce le départ "
        "sur `/guide/evenement` (« Suivez-moi, je vous emmène à Salle B204. »).",
        "Le guide confie la suite des poses des nœuds à `MoteurNav2`, qui les donne à **Nav2** (action "
        "`NavigateThroughPoses`). Le **planificateur Smac 2D** trace le chemin sur la carte et son masque ; le "
        "**contrôleur MPPI** calcule les vitesses 20 fois par seconde en regardant 2,8 s en avant et en évitant "
        "ce que voit le LiDAR ; le **lisseur de vitesse** évite les à-coups ; le **Collision Monitor** ralentit "
        "de moitié si un obstacle est à moins de 1 m devant ou 0,7 m autour, et arrête tout à 0,4 m. "
        "Le résultat part sur `/cmd_vel`.",
        "En simulation, `/cmd_vel` va directement à Gazebo. Sur le robot (et en répétition), le **pont** "
        "`g1_bridge` le reçoit et applique ses règles : plafonds, vitesse minimale, repérage exigé, mode du "
        "robot, verrou, maître des mouvements (chapitre 9).",
        "Le pont envoie l'**ordre 7105** (SetVelocity) sur `/api/sport/request`, 10 fois par seconde, chacun "
        "valable 0,5 s. Le service `sport` du PC1 le transmet au contrôleur d'Unitree, qui fait les pas en "
        "gardant l'équilibre. Si plus rien n'arrive, le robot s'arrête seul.",
        "Le guide suit la distance restante. Plus de progrès depuis 3 s : état `bloque` ; depuis 8 s : le "
        "couloir est marqué bloqué pour 120 s et le routeur cherche un autre chemin (`detour`). Si une personne "
        "est devant (moins de 2,5 m), il attend d'abord (`attente_passage`, « Pardon, puis-je passer ? »), "
        "jusqu'à 20 s. En accompagnement, il ralentit si le visiteur traîne et l'attend s'il ne le voit plus.",
        "À l'arrivée : état `arrive`, rotation finale vers l'orientation de la salle, phrase d'arrivée. "
        "15 s plus tard, retour seul au point principal (`retour`, puis `attente`).",
    ]),
    ("p", "Un ordre de marche, tel que le pont le remplit (vx, vy en m/s, wz en rad/s ; l'arrêt est le "
          "« StopMove » du SDK d'Unitree) :"),
    ("code", "header.identity.id     : un compteur toujours croissant (time.monotonic_ns())\n"
             "header.identity.api_id : 7105\n"
             "parameter (marche)     : {\"velocity\": [0.2, 0.0, 0.0], \"duration\": 0.5}\n"
             "parameter (arrêt)      : {\"velocity\": [0.0, 0.0, 0.0], \"duration\": 1.0}"),

    ("h2", "Le repérage au démarrage"),
    ("p", "Pour naviguer, le robot doit savoir où il est sur la carte de l'étage. On ne le devine pas : on le "
          "pose à un endroit connu, le **point principal**, et on demande au SLAM d'Unitree de se repérer à "
          "partir de là."),
    ("schema", "reperage", "Le repérage : de « Repérer » au feu vert du pont", 15.0, 9.5),
    ("puces", [
        "La pose du point principal (repère `map`) est convertie dans le repère de la carte d'Unitree "
        "(`carte_vers_unitree`, dans `atelier.lieu.conversions`). Pour un étage scanné par le robot, les deux "
        "repères sont les mêmes : l'origine est le départ du scan.",
        "L'ordre **1804** part en ROS 2 sur `/api/slam_operate/request`, avec la pose et le nom de la carte "
        "enregistrée au scan (`carte_unitree` de `lieu.yaml`).",
        "Si le robot se repère à moins de 1 m et 0,5 rad de la pose annoncée, le relais `odom_vers_tf` publie la "
        "correction `map → odom` et l'état `repere`, avec la précision tirée de la covariance. Sinon : `echec` "
        "et un message (« vérifiez qu'il est sur la marque, tourné dans le bon sens »).",
        "Ensuite, plus de relocalisation depuis 3 s donne `perdu` : le pont arrête le robot ; le guide attend "
        "30 s au plus de la retrouver, puis abandonne avec un message qui dit quoi faire.",
    ]),

    ("h2", "Le pilotage depuis l'Atelier"),
    ("schema", "pilotage", "Le pilotage : HTTP et WebSocket jusqu'au nœud du conteneur", 14.0, 9.5),
    ("p", "**Pourquoi pas ROS 2 par le Wi-Fi ?** La découverte automatique de DDS par le Wi-Fi est lourde et "
          "fragile (une trentaine de participants avec Nav2, multicast souvent bloqué). Une simple connexion "
          "HTTP vers un port connu (8010) suffit, et surtout **les sécurités sont au plus près du robot** : "
          "plafonds, refus, homme mort et verrou sont dans le nœud du conteneur. Si le Wi-Fi ou la page se "
          "coupent, le nœud arrête le robot de lui-même en 0,5 s, sans dépendre du PC."),
    ("puces", [
        "Le joystick envoie son ordre toutes les 0,1 s par `/ws/pilotage` ; le nœud envoie un 7105 de 0,5 s à "
        "chaque ordre ; sans ordre depuis 0,5 s, il envoie un arrêt ; WebSocket fermé : arrêt tout de suite.",
        "Après un ARRÊT, un joystick resté tenu ne relance pas le robot : il faut le lâcher, puis le reprendre.",
        "Les ordres sensibles demandent une confirmation (réponse HTTP 428 avec un jeton) : « robot au "
        "portique » pour amortir ou couper le couple, « zone libre de 2 à 3 m » pour une danse. Les ordres "
        "interdits sont refusés (403) sans rien envoyer au robot.",
        "**Un seul maître des mouvements** : le nœud publie `/mouvement/maitre` ; tant que le pilotage a la main, "
        "le pont ignore Nav2 et le guide refuse les visites. L'ARRÊT est toujours permis.",
    ]),

    ("h2", "La caméra de poitrine et les visiteurs"),
    ("schema", "camera", "De la See3CAM au cadre autour du visiteur, dans le navigateur", 15.5, 9.0),
    ("num", [
        "`g1-jetson demarrer` cherche la See3CAM (`/dev/v4l/by-id/…See3CAM_11CUG…`) et la passe au conteneur "
        "sous le nom `/dev/g1_camera` ; sans caméra, le conteneur démarre quand même.",
        "Le nœud `camera_usb` règle l'exposition automatique (la See3CAM démarre en manuel : image noire), "
        "capture en 1280 × 720 avec `v4l2-ctl`, et publie un JPEG de 640 pixels de large (qualité 70) "
        "10 fois par seconde sur `/camera_poitrine/image/compressed`, et son état chaque seconde.",
        "Sur le PC, `g1-visiteurs` lit ces images, trouve les personnes (YOLO pose, suivi ByteTrack), estime "
        "leur distance d'après la taille de leur cadre, et publie `/visiteurs/detectes`.",
        "Le pont ROS 2 du serveur garde la dernière image ; `GET /api/camera/flux` l'envoie en **MJPEG** (une "
        "suite de JPEG dans une seule réponse HTTP, qu'une balise `<img>` affiche telle quelle). La vue Caméra "
        "dessine un cadre autour de chaque visiteur, à partir du WebSocket `/ws/etat`.",
    ]),
    ("code", "{\"version\": 1, \"source\": \"camera\", \"temps\": 1793107360.2,\n"
             " \"image\": {\"largeur\": 640, \"hauteur\": 360},\n"
             " \"personnes\": [{\"id\": 3, \"x\": 1.8, \"y\": 0.2, \"distance_m\": 1.81,\n"
             "                \"angle_rad\": 0.11, \"confiance\": 0.91,\n"
             "                \"regarde_robot\": true, \"boite\": [212, 40, 380, 355]}]}"),
    ("p", "Ci-dessus, la forme d'un message `/visiteurs/detectes` (valeurs d'exemple) : x et y sont dans le "
          "repère du robot, `boite` est le cadre en pixels dans l'image analysée."),

    ("h2", "La simulation et la répétition"),
    ("p", "**Simulation.** `POST /api/simulation/demarrer {lieu, etage, mode: \"simu\"}` lance deux rôles : "
          "`g1-monde simuler` (Gazebo sans fenêtre, le robot proxy posé sur le point principal, `ros_gz_bridge`, "
          "les piétons qui réagissent au robot) et `g1-guide navigation --simu` (Nav2, guide, détecteur de "
          "personnes au LiDAR). Le temps est celui de Gazebo (`/clock`) ; `map → odom` est l'identité."),
    ("p", "**Répétition.** Avec `mode: \"repetition\"`, l'Atelier lance trois rôles : Gazebo avec le **faux G1** "
          "(`g1-monde simuler --jumeau` : le robot proxy n'écoute plus `/cmd_vel`, seulement le faux G1), le "
          "**faux service de cartographie** (`g1-slam faux-service --jumeau`, qui répond à 1804 et publie la "
          "relocalisation avec 1 cm de bruit), et la navigation avec le relais et le pont "
          "(`g1-guide navigation --simu --localisation unitree`). Le faux G1 démarre en mode 501, ne fait aucun "
          "pas sous 0,15 m/s, et son odométrie dérive (2 % trop longue, 0,01 rad par mètre) pour éprouver la "
          "correction du repérage. **Robot réel** : `mode: \"robot\"` lance seulement `g1-jetson demarrer` ; "
          "tout le reste est sur le robot."),
]
