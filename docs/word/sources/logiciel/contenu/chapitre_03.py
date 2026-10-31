"""Chapitre 3 : les technologies (tableau, puis une fiche par technologie)."""

BLOCS = [
    ("h1", "Les technologies"),
    ("chapeau", "Les outils sur lesquels le logiciel est bâti : d'abord un tableau d'ensemble, avec les "
                "versions relevées sur le PC du projet, puis une fiche par technologie : ce que c'est, "
                "pourquoi ce choix, comment le projet s'en sert, et un exemple réel."),

    ("h2", "Le tableau d'ensemble"),
    ("table", {
        "legende": "Les technologies du projet (versions relevées le 31/10/2026)",
        "entetes": ["Technologie", "Version", "Rôle", "Où dans le code"],
        "largeurs": [3.3, 3.6, 4.4, 5.3],
        "taille": 8.5,
        "premiere_col_gras": True,
        "lignes": [
            ["Ubuntu", "22.04.5 (PC) ; 20.04.6 (Jetson)", "système d'exploitation", "`setup/` (installation)"],
            ["ROS 2", "Humble (rclpy 3.3.22)", "faire parler les programmes du robot", "`ws/src/`, `atelier/serveur/pont_ros.py`"],
            ["CycloneDDS", "0.10.5 (rmw 1.3.5)", "transport réseau de ROS 2", "`setup/env.sh`, `setup/robot.sh`, `docker/`"],
            ["Gazebo Fortress", "6.18.0 (ros_gz 0.244.26)", "simulateur 3D", "`ws/src/g1_sim/`, `atelier/monde/sdf.py`"],
            ["Nav2", "1.1.20", "navigation : chemin, vitesses, sécurité", "`ws/src/g1_nav/config/`"],
            ["Python", "3.10.12", "langage principal", "`atelier/`, `ws/src/g1_*/`, `docker/`"],
            ["FastAPI + uvicorn", "0.159.0 + 0.54.0", "serveur web de l'Atelier", "`atelier/serveur/`"],
            ["WebSocket", "protocole (websockets 16.1.1)", "état en direct, joysticks", "`/ws/etat`, `/ws/pilotage`"],
            ["HTML, CSS, JavaScript", "ES2017, modules", "l'interface, sans compilation", "`atelier/web/`"],
            ["Leaflet", "1.9.4", "plan 2D", "`atelier/web/vendor/leaflet/`, `js/plan.js`"],
            ["three.js", "r160", "vues 3D et carte 3D", "`atelier/web/vendor/three/`, `js/carte3d/`"],
            ["tornado", "6.1", "HTTP et WebSocket du nœud pilotage", "`ws/src/g1_pilotage/`"],
            ["Docker", "24.0.7 (Jetson) ; 29.1.3 (PC)", "conteneur ROS 2 Humble sur le Jetson", "`docker/`, `bin/g1-jetson`"],
            ["SDK et messages Unitree", "unitree_sdk2, unitree_sdk2_python, unitree_ros2", "parler au robot",
             "`third_party/`, `g1_bridge`, `g1_pilotage`, `atelier/scan/slam_client.py`"],
            ["SLAM et repérage d'Unitree", "micrologiciel du G1", "carte du scan, repérage (1801, 1802, 1804)",
             "`atelier/scan/`, `g1_nav/reperage.py`"],
            ["YOLO (ultralytics)", "8.4.183, yolo11n-pose ; PyTorch 2.14.1", "voir les visiteurs", "`outils/visiteurs.py`"],
            ["Pillow, OpenCV, numpy, Open3D", "9.0.1 ; 4.11 ; 1.26.4 ; 0.20.0", "images, cartes, calcul, nuages",
             "`g1_equipe/`, `atelier/scan/`, `atelier/monde/`"],
            ["V4L2 (v4l2-ctl)", "v4l-utils 1.22.1", "lire la caméra USB", "`g1_equipe/camera_usb.py`"],
            ["YAML et JSON Schema", "PyYAML 5.4.1 ; draft-07", "fichiers des lieux, messages", "`atelier/lieu/schemas/` (28 schémas)"],
            ["pytest", "7.4.4", "tests automatiques", "`atelier/tests/`, `docker/tests/`, `ws/src/*/test/`"],
            ["colcon", "colcon-core 0.21.3", "compiler les paquets ROS 2", "`ws/`"],
            ["Git", "2.34.1", "historique et sauvegardes", "`~/robot-g1/.git`"],
            ["Graphviz", "2.43", "les schémas de ce document", "`schemas/*.dot` (hors dépôt)"],
        ],
    }),
    ("p", "Sont aussi installés sur le PC, pour l'équipe ou pour la première semaine : MuJoCo et la politique "
          "de marche d'Unitree (`g1-sim-marche`), FAST-LIO2 et le pilote du LiDAR (plan B de la cartographie), "
          "Piper (voix française), Vosk et faster-whisper (reconnaissance vocale). Firefox 158 et geckodriver "
          "0.37 servent aux tests dans le navigateur."),

    ("h2", "Système, ROS 2 et simulation"),
    ("fiche", {
        "nom": "Ubuntu 22.04",
        "quoi": "Le système d'exploitation Linux du PC. Le Jetson du robot, lui, reste en Ubuntu 20.04, "
                "installé par Unitree.",
        "pourquoi": "ROS 2 Humble, Gazebo Fortress et Nav2 sont faits pour Ubuntu 22.04. Le PC a été mis à "
                    "niveau depuis la 20.04 le 21/10, sans double démarrage.",
        "ici": "`setup/installer_pc.sh` installe la partie système (avec le mot de passe), puis "
               "`setup/installer_utilisateur.sh` tout le reste ; `~/.bashrc` charge `setup/env.sh`.",
        "exemple": "`lsb_release -ds` répond « Ubuntu 22.04.5 LTS ».",
    }),
    ("fiche", {
        "nom": "ROS 2 Humble",
        "quoi": "Une boîte à outils qui fait parler entre eux les programmes d'un robot (les « nœuds »), par "
                "des canaux nommés (les « sujets »). Humble est la version de 2022, maintenue jusqu'en 2027.",
        "pourquoi": "C'est le standard de la robotique ; Nav2 et Gazebo s'y branchent, et Unitree fournit "
                    "ses messages pour ROS 2. Le Jetson a ROS 2 Foxy : plutôt que de mélanger deux versions, "
                    "tout le projet est en Humble, et le Jetson le reçoit dans un conteneur Docker.",
        "ici": "Six paquets du projet dans `ws/src`, et le nœud `atelier_pont` du serveur. Le chapitre 4 "
               "explique les notions de ROS 2 avec ces exemples.",
        "exemple": "`ros2 topic echo /guide/etat` affiche l'état du guide, en JSON.",
    }),
    ("fiche", {
        "nom": "CycloneDDS",
        "quoi": "La couche réseau sous ROS 2 (une réalisation de DDS) : elle découvre seule les programmes "
                "présents et transporte les messages.",
        "pourquoi": "Le robot d'Unitree utilise CycloneDDS : on prend le même pour lui parler sans traduction.",
        "ici": "`RMW_IMPLEMENTATION=rmw_cyclonedds_cpp` (`setup/env.sh`) ; `setup/robot.sh` attache CycloneDDS "
               "au port du câble ; le conteneur écrit sa configuration depuis `docker/cyclonedds.xml.modele`.",
        "exemple": "`CYCLONEDDS_URI` désigne l'interface `eno2` dans un terminal relié au robot.",
    }),
    ("fiche", {
        "nom": "Gazebo Fortress",
        "quoi": "Un simulateur 3D avec la physique et des capteurs simulés (dont un LiDAR). Commande `ign gazebo`.",
        "pourquoi": "Il marche avec ROS 2 Humble (paquets `ros_gz`) et tourne sans fenêtre, ce que demandent les "
                    "tests automatiques.",
        "ici": "`ws/src/g1_sim` : le « robot proxy » (une boîte de 0,208 × 0,477 × 1,315 m qui glisse dans "
               "toutes les directions, avec l'apparence du G1 et un LiDAR à 1,245 m), les piétons, le pont "
               "`ros_gz_bridge`. `atelier/monde/sdf.py` écrit le monde à partir de `monde.yaml`.",
        "exemple": "`g1-monde simuler --lieu demo --etage rdc --sans-fenetre` lance le lycée démo.",
    }),
    ("fiche", {
        "nom": "Nav2 : MPPI, Smac, Collision Monitor et lisseurs",
        "quoi": "La pile de navigation de ROS 2 : elle calcule un chemin sur la carte, puis les vitesses à "
                "envoyer au robot, en évitant les obstacles. Le **planificateur Smac 2D** trace le chemin ; le "
                "**contrôleur MPPI** essaie 2 000 trajectoires possibles 20 fois par seconde et garde la "
                "meilleure ; le **lisseur de chemin** (SimpleSmoother) adoucit le tracé ; le **lisseur de "
                "vitesse** (velocity_smoother) évite les à-coups ; le **Collision Monitor** ralentit ou arrête "
                "le robot quand un obstacle est trop près.",
        "pourquoi": "MPPI accepte un robot qui se déplace aussi de côté (`motion_model: Omni`), comme le G1, et "
                    "Nav2 est l'outil standard, bien testé.",
        "ici": "`ws/src/g1_nav/config/nav2_g1_simu.yaml` et `nav2_g1_reel.yaml` (mêmes réglages, vitesses du "
               "robot réel plus basses et sans marche arrière) ; `MoteurNav2` dans `moteur_nav2.py`.",
        "exemple": "Le Collision Monitor ralentit de moitié à moins de 1 m devant ou 0,7 m autour, et arrête à 0,4 m.",
    }),

    ("h2", "Le serveur et l'interface"),
    ("fiche", {
        "nom": "Python",
        "quoi": "Le langage de presque tout le projet : bibliothèques, serveur, nœuds ROS 2, outils, tests.",
        "pourquoi": "ROS 2 (rclpy), YOLO, Open3D et FastAPI s'en servent ; il se lit facilement.",
        "ici": "Deux environnements : `.venv-projet` (FastAPI, YOLO, Open3D ; il voit aussi ROS 2) et "
               "`.venv-sim` (MuJoCo). Les nœuds ROS 2 tournent avec le Python du système. `atelier/lieu` "
               "n'a besoin que de numpy et PyYAML : il tourne partout, même dans le conteneur.",
        "exemple": "`from atelier.lieu import charger_lieu` charge un lieu, dans n'importe quel outil.",
    }),
    ("fiche", {
        "nom": "FastAPI et uvicorn",
        "quoi": "FastAPI écrit un serveur web en Python (des « routes » : une adresse et une fonction) ; "
                "uvicorn le fait tourner.",
        "pourquoi": "Simple, rapide, avec la validation des demandes et les WebSocket intégrés.",
        "ici": "`atelier/serveur/main.py` crée l'application, `routes/` en contient les [[routes]] routes ; "
               "`bin/g1-atelier` lance `uvicorn atelier.serveur.main:app` sur le port 8000 et ouvre le navigateur.",
        "exemple": "`GET /api/lieux/demo/salles` rend les salles du lycée démo, en JSON.",
    }),
    ("fiche", {
        "nom": "WebSocket",
        "quoi": "Une connexion web qui reste ouverte dans les deux sens, au lieu d'une question et d'une réponse.",
        "pourquoi": "Pour suivre le robot en direct et pour le joystick : si la page se ferme, la connexion "
                    "tombe et le robot s'arrête (homme mort).",
        "ici": "`/ws/etat` envoie environ dix messages par seconde (robot, guide, piétons, pont, repérage, "
               "ARRÊT…) ; `/ws/pilotage` relaie le joystick vers le nœud pilotage.",
        "exemple": "`js/direct.js` s'abonne à `/ws/etat` et se reconnecte seul.",
    }),
    ("fiche", {
        "nom": "HTML, CSS et JavaScript sans compilation",
        "quoi": "Les langages des pages web : HTML pour la structure, CSS pour l'apparence, JavaScript pour "
                "le comportement.",
        "pourquoi": "Pas d'outil de compilation (ni npm, ni bundler) : les fichiers sont servis tels quels, "
                    "et l'Atelier marche sans Internet. Le JavaScript reste en ES2017 (lisible par l'outil de "
                    "test esprima).",
        "ici": "`atelier/web/` : `index.html`, des modules JavaScript (`js/coque/`, `js/ecrans/`, "
               "`js/carte3d/`…), 10 feuilles de style ; les couleurs sont des « jetons » de `css/theme.css`.",
        "exemple": "`js/app.js` ne fait qu'une chose : `demarrerCoque()`.",
    }),
    ("fiche", {
        "nom": "Leaflet",
        "quoi": "Une bibliothèque de cartes interactives pour le web (zoom, glisser, marqueurs).",
        "pourquoi": "Légère et éprouvée ; son mode `CRS.Simple` affiche une image en mètres, comme une carte de robot.",
        "ici": "Le **Plan 2D** (`js/plan.js`) : 1 unité = 1 m, latitude = y, longitude = x. Il sert à dessiner "
               "le monde, les itinéraires et les zones. Copié dans `vendor/` (marche sans Internet).",
        "exemple": "La carte `carte.png` est posée sur ses `bornes` en mètres, lues dans `carte.yaml`.",
    }),
    ("fiche", {
        "nom": "three.js",
        "quoi": "Une bibliothèque de 3D pour le navigateur (WebGL) : caméras, objets, nuages de points.",
        "pourquoi": "La référence de la 3D web ; la version r160 suffit (OrbitControls réglé comme SolidWorks).",
        "ici": "La **carte 3D** (`js/carte3d/`) : le nuage du scan coloré par la hauteur, les salles en "
               "épingles, l'accueil en étoile ; l'aperçu 3D du G1 dans Piloter.",
        "exemple": "Le nuage du 27/10 (299 558 points) s'affiche d'un seul envoi binaire.",
    }),
    ("fiche", {
        "nom": "tornado",
        "quoi": "Un petit serveur web Python, HTTP et WebSocket.",
        "pourquoi": "Il existe en paquet apt pour Ubuntu 22.04 sur le Jetson (`python3-tornado`) : rien à "
                    "compiler dans le conteneur.",
        "ici": "Le nœud pilotage (`g1_pilotage/serveur.py`) écoute sur le port 8010 ; sur le Wi-Fi, il exige un "
               "jeton dans l'en-tête `X-Jeton`.",
        "exemple": "`POST /arret` du nœud pilotage arrête tout, quel que soit le maître des mouvements.",
    }),

    ("h2", "Le robot"),
    ("fiche", {
        "nom": "Docker sur le Jetson",
        "quoi": "Un conteneur est une boîte qui contient un programme et tout ce dont il a besoin (ici "
                "Ubuntu 22.04 et ROS 2 Humble), isolée du reste de la machine.",
        "pourquoi": "Le Jetson est en Ubuntu 20.04 avec ROS 2 Foxy ; le conteneur apporte Humble sans rien "
                    "changer au robot. Image de base officielle `ros:humble-ros-base-jammy`, qui existe pour "
                    "le PC (amd64) et pour le Jetson (arm64).",
        "ici": "`docker/Dockerfile` (couches : paquets apt, messages Unitree, tornado, caméra, nos paquets), "
               "`docker/demarrer.sh` (point d'entrée), `docker/jetson.py` (la commande `g1-jetson`). L'image "
               "arm64 se construit sur le PC par émulation, puis s'envoie au Jetson par le câble.",
        "exemple": "`g1-jetson construire`, `g1-jetson envoyer`, `g1-jetson demarrer --lieu seance --etage rdc`.",
    }),
    ("fiche", {
        "nom": "SDK et messages Unitree",
        "quoi": "Les bibliothèques d'Unitree pour commander le G1 : `unitree_sdk2` (C++), `unitree_sdk2_python`, "
                "et `unitree_ros2`, qui fournit les messages ROS 2 du robot (`unitree_api`, `unitree_hg`).",
        "pourquoi": "Le robot reçoit ses ordres sous forme de messages `unitree_api/Request` : un numéro d'ordre "
                    "(`api_id`) et des paramètres en JSON.",
        "ici": "Le pont et le nœud pilotage écrivent ces messages eux-mêmes en ROS 2 ; `atelier/scan/slam_client.py` "
               "utilise le SDK Python pour le service de cartographie (`g1-slam`).",
        "exemple": "L'ordre de marche : `api_id` 7105, paramètre `{\"velocity\": [0.2, 0.0, 0.0], \"duration\": 0.5}`.",
    }),
    ("fiche", {
        "nom": "SLAM et repérage d'Unitree",
        "quoi": "Le SLAM (localisation et cartographie simultanées) construit une carte en même temps qu'il "
                "suit la position du robot. Le G1 a le sien, dans le PC1, avec un service `slam_operate`.",
        "pourquoi": "Il marche déjà sur le robot, avec son LiDAR ; FAST-LIO2 et AMCL restent des plans B.",
        "ici": "Le scan enregistre `/unitree/slam_mapping/points` et `/odom` (ordres 1801 et 1802) ; le "
               "repérage envoie 1804 avec la pose du point principal (`g1_nav/reperage.py`).",
        "exemple": "Le scan du 27/10 : 2 327 nuages en 3 min 54 s, sur 69,8 m de trajet.",
    }),

    ("h2", "Vision et images"),
    ("fiche", {
        "nom": "YOLO (ultralytics)",
        "quoi": "Un réseau de neurones qui trouve des objets dans une image ; la version « pose » trouve aussi "
                "les articulations des personnes.",
        "pourquoi": "Rapide sur la carte graphique du PC (RTX 3060), précis, simple à utiliser ; ByteTrack suit "
                    "chaque personne d'une image à l'autre.",
        "ici": "`g1-visiteurs` (`outils/visiteurs.py`) lit l'image de la caméra de poitrine et publie "
               "`/visiteurs/detectes` (distance, cadre, regarde-t-il le robot).",
        "exemple": "`g1-visiteurs --source robot --image` dessine un cadre autour de chaque visiteur.",
    }),
    ("fiche", {
        "nom": "Pillow, OpenCV, numpy et Open3D",
        "quoi": "Pillow lit et écrit des images ; OpenCV traite des images ; numpy calcule sur des tableaux ; "
                "Open3D lit et écrit les nuages de points `.pcd`.",
        "pourquoi": "Dans le conteneur, Pillow suffit pour le JPEG (la couche Pillow et v4l-utils pèse 9 Mo, "
                    "contre 580 Mo pour OpenCV) ; sur le PC, OpenCV nettoie les cartes et Open3D gère les nuages.",
        "ici": "`g1_equipe/camera_usb.py` (JPEG par Pillow) ; `atelier/scan/carte2d.py` et "
               "`atelier/monde/extrusion.py` (OpenCV) ; `atelier/scan/carte3d.py` (Open3D, numpy).",
        "exemple": "Une image YUYV de 1280 × 720 devient un JPEG de 640 pixels de large, 10 fois par seconde.",
    }),
    ("fiche", {
        "nom": "V4L2",
        "quoi": "Video4Linux 2, l'interface de Linux pour les caméras ; `v4l2-ctl` la commande en ligne.",
        "pourquoi": "Elle règle l'exposition de la See3CAM et capture l'image brute, sans OpenCV.",
        "ici": "`camera_usb` lance `v4l2-ctl` pour passer l'exposition en automatique (la caméra démarre en "
               "manuel : image noire) et lire les images YUYV.",
        "exemple": "`v4l2-ctl -d /dev/g1_camera -C auto_exposure` lit le réglage dans le conteneur.",
    }),

    ("h2", "Données, tests et outils"),
    ("fiche", {
        "nom": "YAML et JSON Schema",
        "quoi": "YAML est un format de fichier texte lisible (clés, listes). JSON Schema décrit ce qu'un "
                "fichier doit contenir : les champs obligatoires, leur type, leurs valeurs possibles.",
        "pourquoi": "Les fichiers d'un lieu s'écrivent et se corrigent à la main ; les schémas les vérifient et "
                    "donnent des erreurs en français qui disent quoi corriger.",
        "ici": "`atelier/lieu/schemas/` : 28 schémas (draft-07) pour les fichiers d'un lieu et pour les messages "
               "JSON des sujets ROS 2. Le validateur est écrit dans `atelier/lieu/validation.py` (sans "
               "dépendance) et comparé au paquet `jsonschema` par les tests.",
        "exemple": "« salles.yaml, salle « b204 » : il manque theta ».",
    }),
    ("fiche", {
        "nom": "pytest",
        "quoi": "L'outil de tests de Python : chaque fonction `test_…` vérifie un comportement.",
        "pourquoi": "Simple, standard, et utilisé aussi par les paquets ROS 2 (`colcon test`).",
        "ici": "[[tests_atelier]] tests dans `atelier/tests`, [[tests_docker]] dans `docker/tests`, et les tests de "
               "chaque paquet ROS 2. Les tests dans le navigateur pilotent Firefox sans fenêtre par geckodriver.",
        "exemple": "`.venv-projet/bin/python -m pytest atelier/tests -q`.",
    }),
    ("fiche", {
        "nom": "colcon",
        "quoi": "L'outil qui compile et installe les paquets ROS 2 d'un espace de travail.",
        "pourquoi": "C'est l'outil standard de ROS 2.",
        "ici": "`cd ~/robot-g1/ws && colcon build --symlink-install` installe les huit paquets dans `ws/install` "
               "(le lien symbolique fait voir tout de suite un fichier Python modifié).",
        "exemple": "`colcon test --packages-select g1_bridge && colcon test-result --all`.",
    }),
    ("fiche", {
        "nom": "Git",
        "quoi": "Le gestionnaire de versions : il garde l'historique de chaque fichier, par « commits ».",
        "pourquoi": "Pour revenir en arrière, voir qui a changé quoi, et sauvegarder.",
        "ici": "Dépôt `~/robot-g1` ([[commits]] commits) ; seul l'intégrateur fait les commits, avec la ligne "
               "« Co-Authored-By » ; une branche `sauvegarde-vague5` reçoit toutes les 20 minutes le travail en "
               "cours (`~/robot-g1-donnees/sauvegarder.sh`).",
        "exemple": "`git log --oneline` montre les vagues, des contrats aux assemblages.",
    }),
    ("fiche", {
        "nom": "Graphviz",
        "quoi": "Un outil qui dessine des graphes à partir d'un texte (langage « dot »).",
        "pourquoi": "Les schémas se modifient comme du texte et se redessinent seuls.",
        "ici": "Les schémas de ce document : `schemas/*.dot`, dessinés en PNG à 200 dpi par `generer.py`.",
        "exemple": "`dot -Tpng -Gdpi=200 schemas/vue_ensemble.dot -o vue_ensemble.png`.",
    }),
]
