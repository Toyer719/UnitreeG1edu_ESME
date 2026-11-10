"""Chapitre 2 : vue d'ensemble."""

BLOCS = [
    ("h1", "Vue d'ensemble : les pièces et qui tourne où"),
    ("chapeau", "Le logiciel est réparti entre le PC portable du projet et le robot. Ce chapitre montre "
                "les grandes pièces, comment elles se parlent, et ce qui change entre la simulation, la "
                "répétition sans robot et le vrai robot."),

    ("h2", "Les grandes pièces"),
    ("schema", "vue_ensemble", "Les pièces du logiciel, sur le PC et sur le robot", 15.0, 17.5),
    ("puces", [
        "**Le navigateur** affiche l'interface de l'Atelier (HTML, CSS et JavaScript). Il ne parle qu'au "
        "serveur de l'Atelier : par **HTTP** (des questions et des réponses : « donne-moi les salles ») et "
        "par un **WebSocket** (un canal qui reste ouvert, par lequel le serveur envoie l'état du robot dix "
        "fois par seconde).",
        "**Le serveur de l'Atelier** (Python, FastAPI) lit et écrit les fichiers des lieux, lance les "
        "commandes `g1-*` (simulation, navigation, scan, conteneur du robot, démo d'accueil et voix) et contient "
        "un petit programme ROS 2, `atelier_pont`, qui écoute le robot et lui transmet les demandes (« Y aller », "
        "ARRÊT, repérage). Il ne contient aucune logique de robotique : il appelle les bibliothèques et les "
        "commandes. Depuis la vague 6, il tient aussi la **boîte noire** de chaque séance en Réel (chapitre 12).",
        "**La borne visiteur** (vague 6) est une page de ce même serveur, ouverte sur une tablette ou un "
        "téléphone du même Wi-Fi : depuis le réseau, elle seule est permise.",
        "**ROS 2** relie tous les programmes du robot entre eux : la navigation (Nav2), le guide, le pont "
        "vers la marche, la simulation… Le chapitre 4 l'explique en détail.",
        "**Le robot** a deux ordinateurs. Le **PC1** d'Unitree est fermé : il fait marcher et tenir debout "
        "le robot, et fait sa cartographie (le SLAM). On ne le touche jamais. Le **Jetson** (PC2) est "
        "l'ordinateur où l'on a le droit d'installer : notre **conteneur Docker** « g1-jetson » y fait "
        "tourner la navigation, le pont de marche, le pilotage et la caméra de poitrine.",
        "**Le LiDAR** Livox MID-360 est relié au PC1 ; la **caméra de poitrine** See3CAM_11CUG est branchée "
        "en USB 3 sur le Jetson ; la **télécommande** d'Unitree parle directement au robot et reste l'arrêt "
        "d'urgence.",
    ]),

    ("h2", "Trois modes : simulation, répétition, robot réel"),
    ("p", "Le même logiciel, avec les mêmes fichiers, fonctionne de trois façons. Ce qui change, c'est "
          "surtout le chemin de la vitesse calculée par Nav2 jusqu'aux jambes du robot :"),
    ("schema", "trois_modes", "Le chemin de la vitesse dans les trois modes", 15.5, 10.0),
    ("puces", [
        "**Simulation** : tout tourne sur le PC. Gazebo simule le bâtiment et un « robot proxy » de la taille "
        "du G1 ; la vitesse de Nav2 va directement à Gazebo.",
        "**Répétition sans robot** : on joue tout le déroulé du vrai robot (repérage, pont, ordres de marche "
        "7105, ARRÊT, pilotage) contre un **faux G1** (`g1_jumeau`) qui répond comme le vrai et fait bouger "
        "le robot de Gazebo. C'est grâce à elle que tout a été essayé avant la première séance avec le robot.",
        "**Robot réel** : la navigation tourne dans le conteneur du Jetson, le pont envoie ses ordres au "
        "service de marche du PC1, et l'Atelier, sur le PC, suit et commande par le câble.",
    ]),
    ("table", {
        "legende": "Qui tourne où, selon le mode",
        "entetes": ["Pièce", "Simulation", "Répétition (sans robot)", "Robot réel"],
        "largeurs": [3.6, 3.7, 4.6, 4.7],
        "taille": 9,
        "premiere_col_gras": True,
        "lignes": [
            ["Le robot", "robot proxy de Gazebo", "robot proxy, commandé par le faux G1", "le vrai G1"],
            ["Gazebo", "`g1-monde simuler`", "`g1-monde simuler --jumeau`", "aucun"],
            ["Service de marche (ordre 7105)", "aucun", "`g1_jumeau` (faux G1)", "PC1 du robot"],
            ["Service de cartographie (1801, 1804)", "aucun", "`g1-slam faux-service --jumeau`", "PC1 du robot"],
            ["Nav2, guide, relais, pont", "`g1-guide navigation --simu` (sans pont)",
             "sur le PC (`--localisation unitree`), ou le conteneur en local", "conteneur `g1-jetson` sur le Jetson"],
            ["Atelier", "PC", "PC", "PC, relié par le câble"],
            ["Démo d'accueil et voix (vague 6)", "PC ; la voix passe par la borne", "PC ; voix vers le faux G1",
             "PC ; voix vers le haut-parleur du robot"],
            ["Boîte noire (vague 6)", "aucune", "une séance par ouverture de l'espace", "une séance par ouverture "
             "de l'espace"],
            ["Domaine ROS 2", "celui du terminal", "celui du terminal", "0 (celui du robot)"],
        ],
    }),

    ("h2", "Le réseau du robot"),
    ("p", "Le PC parle au robot par un **câble Ethernet**, sur le réseau interne du robot, "
          "192.168.123.x. La commande `source ~/robot-g1/setup/robot.sh` met le PC en 192.168.123.99 sur "
          "son port `eno2`, attache ROS 2 à ce port et vérifie que le robot répond. Le Wi-Fi du PC reste "
          "sur Internet."),
    ("table", {
        "entetes": ["Machine", "Adresse", "Rôle"],
        "largeurs": [4.0, 3.4, 9.2],
        "taille": 9.5,
        "lignes": [
            ["PC portable du projet", "192.168.123.99", "l'Atelier, la simulation, YOLO, la démo et la voix ; relié "
             "par `eno2`"],
            ["PC1 d'Unitree", "192.168.123.161", "marche, équilibre, SLAM, services `sport`, `slam_operate`, `voice`, `arm`, `videohub`"],
            ["Jetson (PC2)", "192.168.123.164", "notre conteneur ; Ubuntu 20.04, L4T R35.3.1, Docker 24.0.7, 15 Go de mémoire"],
            ["LiDAR Livox MID-360", "192.168.123.120", "le capteur laser 3D, lu par le SLAM d'Unitree"],
        ],
    }),
    ("encadre", "Ce qu'on installe sur le robot, et ce qu'on n'y touche pas",
     ["Le PC1 d'Unitree n'est jamais modifié. Sur le Jetson, on ajoute seulement une image Docker "
      "(environ 2 Go une fois chargée) et un dossier `~/robot-g1`. Rien n'est installé ni remplacé dans "
      "Ubuntu, ROS ou les programmes d'Unitree, et notre conteneur ne redémarre jamais tout seul.",
      "Pour tout retirer : d'abord arrêter le conteneur (sinon Docker refuse d'effacer l'image), puis effacer "
      "l'image et le dossier, depuis le PC relié au robot :"],
     "info"),
    ("code", "g1-jetson arreter\n"
             "ssh unitree@192.168.123.164 'docker rmi g1-jetson:arm64; rm -rf ~/robot-g1'"),
]
