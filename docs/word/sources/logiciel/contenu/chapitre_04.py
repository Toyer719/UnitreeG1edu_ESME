"""Chapitre 4 : ROS 2 expliqué avec le projet."""

BLOCS = [
    ("h1", "ROS 2 expliqué avec le projet"),
    ("chapeau", "ROS 2 n'est pas un système d'exploitation : c'est une boîte à outils qui fait parler entre "
                "eux les programmes d'un robot. Voici ses notions, chacune avec un exemple du projet et la "
                "commande pour la voir de ses yeux (dans un terminal où `setup/env.sh` est chargé)."),

    ("h2", "Nœud, sujet et message"),
    ("p", "Un **nœud** est un programme ROS 2 qui a un nom. Le projet en a une douzaine : `guide` (le guide), "
          "`pont_g1` (le pont vers la marche), `odom_vers_tf` (le relais de position), `atelier_pont` (dans "
          "le serveur de l'Atelier), `pilotage`, `camera_poitrine`, `g1_jumeau` (le faux G1), "
          "`detecteur_personnes`, `faux_visiteur`, `pietons`, `dialogue`… Nav2, lui, en lance une quinzaine."),
    ("p", "Un **sujet** (__topic__ en anglais) est un canal nommé : des nœuds y **publient** des messages, "
          "d'autres s'y **abonnent** et les reçoivent. Personne n'a besoin de savoir qui est à l'autre bout. "
          "Un **message** a un type fixe : `std_msgs/String` (un texte ; chez nous souvent du JSON), "
          "`geometry_msgs/Twist` (les vitesses vx, vy, wz), `nav_msgs/Odometry` (une position et une vitesse), "
          "`sensor_msgs/PointCloud2` (un nuage de points), `sensor_msgs/CompressedImage` (une image JPEG), "
          "`unitree_api/Request` (un ordre au robot)."),
    ("schema", "ros2_noeuds", "Quelques nœuds et sujets du projet, autour du guide", 12.0, 15.0),
    ("p", "Exemple réel : l'Atelier publie « b204 » sur `/guide/aller` ; le guide, abonné, reçoit la demande, "
          "calcule l'itinéraire, lance Nav2, et publie son avancement sur `/guide/etat`, que l'Atelier affiche. "
          "Nav2 publie les vitesses sur `/cmd_vel`, que le pont transforme en ordres de marche. Pour le voir :"),
    ("code", "ros2 node list                    # les nœuds présents\n"
             "ros2 topic list                   # les sujets\n"
             "ros2 topic echo /guide/etat       # suivre l'état du guide\n"
             "# envoyer le robot vers la salle b204 :\n"
             "ros2 topic pub --once /guide/aller std_msgs/msg/String \"{data: 'b204'}\"\n"
             "ros2 topic hz /camera_poitrine/image/compressed    # images par seconde"),

    ("h2", "Service, action et paramètre"),
    ("puces", [
        "Un **service** est une question avec une réponse. Exemple : le serveur de l'Atelier demande à Nav2 "
        "s'il est prêt, par le service `/bt_navigator/get_state`, avant d'envoyer un but.",
        "Attention à un faux ami : les « services » d'Unitree (`sport`, `slam_operate`, `voice`, `arm`, "
        "`videohub`) ne sont pas des services ROS 2, mais des paires de sujets : la demande sur "
        "`/api/<service>/request`, la réponse sur `/api/<service>/response`, reliées par un numéro "
        "(`identity.id`). C'est pourquoi le pont n'écoute que les réponses qui portent ses propres numéros.",
        "Une **action** est une tâche longue, avec un suivi et la possibilité d'annuler. Exemple : `MoteurNav2` "
        "confie l'itinéraire à Nav2 par l'action `NavigateThroughPoses` (la suite des poses des nœuds), puis "
        "la rotation finale à l'action `Spin`.",
        "Un **paramètre** est un réglage d'un nœud, lu au lancement et parfois modifiable en marche. Exemple : "
        "le pont lit ses plafonds dans `ws/src/g1_bridge/config/pont.yaml` ; le guide accepte en marche "
        "`ros2 param set /guide tolerance_orientation_rad 0.4`.",
    ]),

    ("h2", "Paquet, lancement et compilation"),
    ("p", "Un **paquet** regroupe le code d'une fonction, avec un fichier `package.xml` (nom, dépendances) et "
          "un `setup.py` (Python) ou un `CMakeLists.txt` (C++). Le projet en écrit six (`g1_sim`, `g1_nav`, "
          "`g1_bridge`, `g1_jumeau`, `g1_pilotage`, `g1_equipe`) et en utilise deux d'ailleurs "
          "(`livox_ros_driver2`, `FAST_LIO`). Un **fichier de lancement** (__launch__, en Python) démarre "
          "plusieurs nœuds d'un coup, avec des arguments :"),
    ("code", "ros2 launch g1_sim simulation.launch.py lieu:=demo etage:=rdc sans_fenetre:=true\n"
             "ros2 launch g1_nav navigation.launch.py lieu:=demo etage:=rdc simu:=true"),
    ("p", "Les commandes du projet ne font que traduire leurs options en ces arguments : "
          "`g1-monde simuler --lieu demo --etage rdc --sans-fenetre` appelle le premier, "
          "`g1-guide navigation --lieu demo --etage rdc --simu` le second. Les paquets se **compilent** avec "
          "colcon dans `~/robot-g1/ws` (`colcon build --symlink-install`) ; `setup/env.sh` charge ensuite "
          "`ws/install`, et `ros2 run g1_bridge pont` trouve le programme."),

    ("h2", "DDS, domaine et qualité de service"),
    ("puces", [
        "**DDS** est la couche réseau de ROS 2 : les nœuds se découvrent seuls sur le réseau, sans serveur "
        "central. Le projet utilise **CycloneDDS**, comme le robot.",
        "Le **domaine** (`ROS_DOMAIN_ID`) est un numéro qui sépare des groupes de nœuds : deux nœuds de "
        "domaines différents ne se voient pas. Le robot publie sur le **domaine 0**. Les tests et les agents "
        "travaillent sur d'autres numéros (36 pour la recette, puis un numéro par agent : 50 à 54, 60 à 63, "
        "70 à 75, 100 à 106, puis 112 et 113 pour la revue et la recette de la vague 5) pour ne jamais se gêner, "
        "et souvent avec `ROS_LOCALHOST_ONLY=1` (rien ne sort du PC).",
        "Conséquence pratique, et règle des séances : **aucune simulation ne doit tourner sur le PC quand le "
        "robot est branché**, car un faux G1 sur le domaine 0 pourrait répondre à la place du vrai. Le plus "
        "sûr est de redémarrer le PC avant la séance.",
        "La **qualité de service** (QoS) règle la livraison : « fiable » (chaque message arrive) ou « au "
        "mieux » (les capteurs, où seul le dernier compte) ; « volatile » ou « transient_local » (le dernier "
        "message est gardé pour qui arrive plus tard). Exemple : le verrou `/pont/arret` est fiable et "
        "transient_local, pour qu'un pont relancé retrouve le verrou posé avant lui.",
    ]),

    ("h2", "Les repères (TF)"),
    ("p", "Un **repère** est un point d'origine avec trois axes. ROS 2 tient l'arbre des repères (TF) et sait "
          "passer de l'un à l'autre. Le projet suit la convention de ROS (REP-105) : x vers l'avant, y vers la "
          "gauche, z vers le haut, angles en radians, `theta` mesuré depuis l'axe x dans le sens inverse des "
          "aiguilles d'une montre."),
    ("schema", "reperes_tf", "L'arbre des repères du robot", 11.5, 11.0),
    ("puces", [
        "`map` est le repère de la carte de l'étage : les salles, les itinéraires et les zones y sont écrits. "
        "Il ne bouge pas.",
        "`odom` est le repère de l'odométrie (le compte des pas et la centrale inertielle) : la position y est "
        "continue, sans saut, mais elle dérive peu à peu. Le contrôleur MPPI travaille dans ce repère.",
        "`base_link` est le robot lui-même, au sol ; `lidar` est le capteur, 1,245 m plus haut.",
        "La transformation `map → odom` est la **correction** : en simulation, elle est nulle ; sur le robot, "
        "le relais `odom_vers_tf` la calcule à partir du repérage d'Unitree, 20 fois par seconde. Si le "
        "repérage s'arrête, le repère local reste juste et le pont arrête le robot.",
    ]),

    ("h2", "Carte d'occupation et cartes des coûts"),
    ("p", "Une **carte d'occupation** est une image vue de dessus où chaque pixel représente 5 cm de sol : "
          "noir (0) pour occupé, blanc (254) pour libre, gris (205) pour inconnu. Elle est accompagnée d'un "
          "fichier `.yaml` (la taille d'un pixel et la position du coin), au format standard de Nav2 ; la "
          "ligne 0 de l'image correspond au y le plus grand. Toutes les conversions entre pixels et mètres "
          "passent par `atelier.lieu.conversions`, et nulle part ailleurs."),
    ("p", "Une **carte des coûts** (__costmap__) est la grille de travail de Nav2 : la carte, plus les obstacles "
          "vus par le LiDAR, plus une « inflation » (un coût qui décroît en s'éloignant des obstacles, pour "
          "garder ses distances), plus le masque des zones interdites. Il y en a deux : la **globale**, sur "
          "tout l'étage, pour tracer le chemin ; la **locale**, 7 × 7 m autour du robot, pour les vitesses. "
          "Chez nous, la locale voit les obstacles de 0,15 à 1,9 m de haut (assez bas pour une valise) et "
          "garde 0,9 m d'inflation autour des personnes."),
    ("encadre", "À retenir",
     ["- Un nœud = un programme ; un sujet = un canal ; un message = des données typées.",
      "- Les « services » d'Unitree sont des paires de sujets `/api/<service>/request` et `/response`.",
      "- Le robot vit sur le domaine 0 : pas de simulation sur le PC pendant une séance.",
      "- `map` = la carte (fixe) ; `odom` = l'odométrie (continue, qui dérive) ; la correction relie les deux."],
     "retenir"),
]
