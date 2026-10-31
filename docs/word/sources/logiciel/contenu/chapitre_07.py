"""Chapitre 7 : les pièces du code."""

BLOCS = [
    ("h1", "Les pièces du code"),
    ("chapeau", "Une section par grande pièce : ce qu'elle fait, ses fichiers principaux et la façon de "
                "s'en servir. Les bibliothèques Python de `atelier/` ne dépendent pas de ROS 2 (sauf le "
                "pont du serveur et quelques parties du scan) : elles se testent seules, avec pytest."),

    ("h2", "atelier/lieu : la bibliothèque des lieux"),
    ("p", "Elle charge, vérifie et enregistre un lieu, et contient les **contrats** partagés : les valeurs que "
          "plusieurs pièces doivent avoir en commun (plafonds du pont, codes du robot, formats des messages). "
          "Elle n'a besoin que de numpy et PyYAML ; elle est donc aussi copiée dans le conteneur du Jetson."),
    ("table", {
        "entetes": ["Module", "Rôle"],
        "largeurs": [4.0, 12.6],
        "taille": 9,
        "lignes": [
            ["`modeles.py`", "les objets d'un lieu en Python (Lieu, Etage, Salle, Noeud, Couloir, Zone, Monde, Mur, Objet, Pieton…)"],
            ["`fichiers.py`, `validation.py`, `verification.py`", "lire et écrire (écriture atomique), vérifier par les schémas, "
             "vérifier la cohérence de tout le lieu (« Vérifier le lieu », `g1-lieu valider`)"],
            ["`conversions.py`, `geometrie.py`", "pixels ↔ mètres, angle ↔ quaternion, repère d'Unitree ↔ carte ; murs alignés, passages"],
            ["`scans.py`, `nuage.py`", "les sessions de scan (verrou entre processus) ; le format du nuage d'affichage"],
            ["`robot.py`", "le contrat du pont et du repérage : plafonds, délais, états, `vitesse_effective` (la vitesse minimale)"],
            ["`principal.py`, `passants.py`, `comportement.py`", "le point principal ; les mesures des passants ; les états et événements du guide"],
            ["`pilotage.py`, `equipe.py`", "ordres permis et interdits, gestes, danses, modes du robot ; fichiers et sujets de l'équipe"],
            ["`commande.py`, `schemas/`, `exemples/`", "la commande `g1-lieu` ; les 28 schémas JSON ; les exemples des fichiers de l'équipe"],
        ],
    }),

    ("h2", "atelier/monde : le générateur de monde"),
    ("p", "Il transforme un bâtiment dessiné en ce dont la simulation et la navigation ont besoin, sans ROS : "
          "`carte.py` trace la carte 2D (les murs et objets qui coupent la tranche de 0,1 à 1,5 m de haut ; "
          "les piétons n'y vont pas, ce sont des obstacles mobiles) ; `sdf.py` écrit le monde Gazebo (murs, "
          "objets, piétons) ; `zones.py` fabrique le masque des zones interdites ; `extrusion.py` transforme "
          "la carte d'un étage scanné en un seul maillage STL ; `pietons.py`, `scene.py` et `foule.py` "
          "calculent les trajets des piétons et chargent les **scènes** de test (`scenes/` : immobile dans le "
          "couloir, en face, coupe la route, groupe qui bouche, groupe qui reste, foule, accompagnement). "
          "`commande.py` est la commande `g1-monde` (`generer`, `simuler`)."),

    ("h2", "atelier/scan : le scan du bâtiment"),
    ("table", {
        "entetes": ["Module", "Rôle"],
        "largeurs": [3.6, 13.0],
        "taille": 9,
        "lignes": [
            ["`session.py`", "la commande `g1-scan` (demarrer, arreter, traiter, etat, adopter, carte-unitree) et le "
             "processus de la session : 1801, enregistrement, 1802, traitement, adoption"],
            ["`apercu.py`", "l'aperçu en direct : image, points et trajet toutes les 2 s"],
            ["`carte3d.py`, `sol.py`", "enregistrement → nuage 3D : une base de temps, passants retirés, sol trouvé comme un plan (RANSAC)"],
            ["`carte2d.py`, `affichage.py`", "nuage → carte 2D (tranche au-dessus du sol) ; nuage d'affichage de la carte 3D"],
            ["`slam_client.py`, `faux_slam.py`", "le client du service de cartographie d'Unitree ; un faux service pour les tests et la répétition"],
            ["`exploration.py`, `repetition.py`", "le tour automatique des couloirs (scan simulé) ; les relais de la répétition"],
            ["`carte_unitree.py`, `salle.py`, `commande.py`", "récupérer la carte d'Unitree ; ajouter une salle à la position du robot ; "
             "les commandes `g1-slam`, `g1-carte-3d`, `g1-carte-2d`, `g1-salle`"],
        ],
    }),

    ("h2", "atelier/serveur : le serveur web"),
    ("p", "`main.py` crée l'application FastAPI : il enregistre les routes, traduit chaque erreur en un message "
          "français (`{detail, erreurs}`), interdit la mise en cache et ouvre le WebSocket `/ws/etat`. "
          "`etat.py` tient l'état du serveur (ce qui tourne, le pont ROS 2, l'état envoyé dix fois par "
          "seconde). `processus.py` lance et arrête les commandes `g1-*` en **groupes de processus** (tout ce "
          "qu'une commande a lancé s'arrête avec elle), avec un journal chacune. `pont_ros.py` est le nœud "
          "`atelier_pont`, qui tourne dans un fil à part : il écoute `/odom`, `/guide/etat`, `/reperage/etat`, "
          "`/pont/etat`, les sujets JSON de l'équipe et les images de la caméra, et publie `/guide/aller`, "
          "`/guide/stop`, `/reperage/demander`, `/pont/arret`. Si ROS 2 n'est pas chargé, l'Atelier marche "
          "quand même, sans robot."),
    ("p", "Les routes sont rangées par sujet dans `routes/` (15 fichiers) : `lieux`, `monde`, `plan` (salles, "
          "itinéraires, zones), `simulation` (lancer, arrêter, téléopérer, « Y aller »), `scan`, `robot` "
          "(repérage, verrou), `principal`, `passants`, `guide`, `pilotage`, `equipe`, `arret`, `liaison`, "
          "`nuage`, `camera`. La liste complète est en annexe B."),

    ("h2", "atelier/web : l'interface"),
    ("p", "Une page unique (`index.html`) et des modules JavaScript, servis tels quels. `js/app.js` lance la "
          "**coque** (`js/coque/`), qui affiche l'accueil, puis l'espace de travail, et ouvre les **écrans** :"),
    ("table", {
        "entetes": ["Dossier", "Contenu"],
        "largeurs": [3.6, 13.0],
        "taille": 9,
        "lignes": [
            ["`js/coque/`", "12 modules : `coque.js` (accueil ou espace, table des écrans, clavier, mémoire du navigateur), "
             "`accueil.js`, `ruban.js` (le registre des commandes), `arbre.js`, `vue.js`, `panneau.js`, `barre_etat.js`, "
             "`arret.js`, `confirmation.js`, `anciens_hash.js`, `ecran.js`, `icones.js`"],
            ["`js/ecrans/`", "12 écrans : lieux, monde, carte, salles, itineraires, zones, simulation, scan, pilotage, "
             "personnalites, dialogues, camera"],
            ["`js/carte3d/`", "la carte 3D partagée : `carte3d.js` (`creerCarte3D`), `geometrie3d.js` (rayon contre le "
             "sol, accroche à 5 cm et 15°), `reperes.js` (étoile, épingles, couloirs, zones), `monde3d.js` (monde en "
             "volumes, maillage STL), `edition.js` (gestes de placement), `direct3d.js` (robot et piétons en direct)"],
            ["`js/camera/`, `js/pilotage/`", "la vue Caméra (flux MJPEG et cadres) ; la vue du robot, les joysticks, "
             "l'aperçu 3D du G1, l'éditeur de chorégraphies"],
            ["`js/panneaux/`, `js/equipe/`", "les panneaux du guide et des passants ; les éditeurs de l'équipe"],
            ["modules communs", "`api.js` (appels), `contexte.js`, `direct.js` (WebSocket), `plan.js` (Leaflet), "
             "`vue3d.js`, `nuage3d.js`, `teleop.js`, `geometrie.js`, `historique.js` (annuler, rétablir), "
             "`formulaire.js`, `messages.js`"],
            ["`css/`, `vendor/`", "10 feuilles de style (les couleurs dans `theme.css`) ; Leaflet 1.9.4 et three.js r160"],
        ],
    }),
    ("p", "Chaque écran suit le même **contrat** : `ouvrir(racine, options)` rend un objet avec `modifie()` et "
          "`fermer()`. `racine` est la vue Plan 2D, `options.panneau` le panneau de droite, `options.carte3d` "
          "la carte 3D partagée, `options.coque` les services de la coque (confirmer, message, plein écran…). "
          "Le chapitre 11 décrit l'interface vue de l'utilisateur."),

    ("h2", "atelier/equipe : la logique de l'équipe"),
    ("p", "`dialogue.py` est le **chatbot à règles** : il compare la phrase du visiteur aux motifs de "
          "`dialogues.yaml` (sans majuscules, accents ni ponctuation ; `{salle}` vaut une salle) et choisit une "
          "action (`guider`, `dire`, `personnalite`, `stop`, `geste`). `relais.py` transforme les événements du "
          "guide en phrases à dire, avec celles de la personnalité active. `camera.py` estime la distance d'un "
          "visiteur à partir de la taille de son cadre ; `images.py` garde la dernière image et règle la cadence "
          "du flux. Le nœud `dialogue` de `g1_equipe` s'en sert sur le robot, l'écran Dialogues aussi."),

    ("h2", "Les paquets ROS 2 (ws/src)"),
    ("table", {
        "legende": "Les six paquets ROS 2 du projet",
        "entetes": ["Paquet", "Nœuds (exécutable)", "Sujets principaux", "Rôle"],
        "largeurs": [2.4, 3.9, 5.2, 5.1],
        "taille": 8.5,
        "premiere_col_gras": True,
        "lignes": [
            ["g1_sim", "Gazebo, `ros_gz_bridge`, `pietons`, `robot_state_publisher`",
             "`/cmd_vel`, `/odom`, `/points`, `/clock`, `/pietons/etat`", "la simulation : monde, robot proxy, piétons qui réagissent"],
            ["g1_nav", "`guide`, `odom_vers_tf`, `detecteur_personnes`, `faux_visiteur`, `banc` ; Nav2",
             "`/guide/aller`, `/guide/etat`, `/guide/evenement`, `/reperage/*`, `/personnes/lidar`",
             "la navigation : guide, routeur A*, relais de position et repérage, réglages de Nav2, banc de test"],
            ["g1_bridge", "`pont` (nœud `pont_g1`)", "`/cmd_vel` → `/api/sport/request` ; `/pont/etat`, `/pont/arret`",
             "le pont vers la marche, avec ses sécurités ; outil de mesure `g1_bridge.mesure`"],
            ["g1_jumeau", "`jumeau` (nœud `g1_jumeau`)", "`/api/sport/*`, `/api/arm/*`, `/api/voice/*`, `/g1_jumeau/*`",
             "le faux G1 de la répétition : modes, refus, danses, odométrie qui dérive, image de test"],
            ["g1_pilotage", "`pilote` (nœud `pilotage`)", "`/api/sport|arm|voice/request`, `/arm_sdk`, `/mouvement/maitre`, `/pilotage/etat`",
             "le pilotage depuis l'Atelier (HTTP et WebSocket, port 8010), dans le conteneur"],
            ["g1_equipe", "`dialogue`, `camera_usb`, `fausse_camera`, `voix_journal`",
             "`/visiteur/texte`, `/robot/dire`, `/camera_poitrine/*`, `/personnalite/active`",
             "le chatbot d'exemple, le relais des phrases, la caméra de poitrine, des bouchons pour essayer"],
        ],
    }),
    ("p", "Le paquet `g1_sim` est déclaré comme un paquet C++ (ament_cmake), mais il ne contient que des "
          "fichiers de lancement, des modèles et des scripts Python ; les cinq autres sont des paquets Python "
          "(ament_python). "
          "Chaque paquet a son `LISEZMOI.md` et son dossier `test/`."),

    ("h2", "docker/ : le conteneur du Jetson"),
    ("p", "Le `Dockerfile` construit l'image `g1-jetson` en couches, de la plus stable à la plus changeante : "
          "les paquets apt (CycloneDDS, les composants de Nav2 sans rien de graphique), les messages Unitree "
          "(`unitree_api`, `unitree_hg`), tornado, la caméra (`python3-pil`, `v4l-utils`), les scripts, le Python "
          "de l'Atelier (`atelier/lieu`, `atelier/equipe`, le client du SLAM), puis nos paquets `g1_nav`, "
          "`g1_bridge`, `g1_pilotage`, `g1_equipe`. Une modification de nos paquets ne refait que les dernières "
          "couches. `demarrer.sh` est le point d'entrée : il choisit l'interface réseau 192.168.123.x, écrit la "
          "configuration CycloneDDS, lance `presence.py` (qui publie `/g1_jetson/etat`), puis la navigation, le "
          "pilotage et la caméra. `jetson.py` est la commande `g1-jetson`."),
    ("code", "docker run -d --name g1-jetson --network host --init --restart no \\\n"
             "  --stop-timeout 20 --user <uid>:<gid> --cpus 4 --memory 4g \\\n"
             "  [--device /dev/videoN:/dev/g1_camera --group-add <groupe video>] \\\n"
             "  -e ROS_DOMAIN_ID=0 -e G1_INTERFACES=auto -e G1_LIEU=<id> -e G1_ETAGE=<etage> \\\n"
             "  -v ~/robot-g1/lieux:/lieux:ro -v ~/robot-g1/journaux/jetson:/journaux \\\n"
             "  g1-jetson:arm64"),
    ("p", "Réseau de l'hôte (pour DDS), aucun redémarrage automatique, pas de mode privilégié, les lieux en "
          "lecture seule, la caméra seule par `--device`."),

    ("h2", "bin/ : les commandes"),
    ("p", "Chaque commande est un petit script bash qui charge l'environnement, puis appelle le bon module "
          "Python ou le bon lancement. Toutes acceptent `--help` et ont un alias `gl-…` (pour qui tape un L à "
          "la place du chiffre 1)."),
    ("table", {
        "legende": "Les commandes g1-*",
        "entetes": ["Commande", "À quoi elle sert", "Code appelé"],
        "largeurs": [3.4, 8.4, 4.8],
        "taille": 8.5,
        "premiere_col_gras": True,
        "lignes": [
            ["g1-atelier", "le logiciel web (http://localhost:8000)", "`uvicorn atelier.serveur.main:app`"],
            ["g1-lieu", "créer, vérifier, lister, migrer un lieu", "`atelier/lieu/commande.py`"],
            ["g1-monde", "générer le monde et la carte ; lancer la simulation", "`atelier/monde/commande.py`"],
            ["g1-guide", "lancer la navigation ; envoyer le robot ; l'arrêter ; son état", "`g1_nav/commande.py`"],
            ["g1-banc", "banc de test : trajets tirés au sort, scènes, CSV", "`g1_nav/banc.py`"],
            ["g1-scan", "le scan intégré, comme Réel › Scanner", "`atelier/scan/session.py`"],
            ["g1-slam", "le service de cartographie d'Unitree, à la main ; faux service", "`atelier/scan/commande.py`"],
            ["g1-carte-3d, g1-carte-2d", "enregistrement → nuage 3D → carte 2D", "`atelier/scan/commande.py`"],
            ["g1-salle", "ajouter une salle à la position actuelle du robot", "`atelier/scan/commande.py`"],
            ["g1-jetson", "le conteneur du Jetson : construire, envoyer, démarrer, arrêter, état, journal, vérifier", "`docker/jetson.py`"],
            ["g1-pilotage", "le pilotage en ligne de commande, comme Réel › Piloter", "`g1_pilotage/commande.py`"],
            ["g1-visiteurs", "les visiteurs vus par la caméra de poitrine (YOLO)", "`outils/visiteurs.py`"],
            ["g1-sim, g1-sim-marche, g1-sim-demo", "le G1 dans MuJoCo (première semaine)", "`sim/`"],
            ["g1-etat, g1-telecommande, g1-releve, g1-nuage", "lire l'état du robot, sa télécommande, faire un relevé, voir le LiDAR", "`robot/`, `outils/`"],
            ["g1-premiers-pas, g1-manette, g1-manette-virtuelle", "premiers essais du vrai robot ; piloter à la manette", "`robot/`, `outils/`"],
            ["g1-personnes, g1-parler, g1-ecouter", "détection de personnes, voix française, reconnaissance vocale", "`outils/`"],
        ],
    }),
]
