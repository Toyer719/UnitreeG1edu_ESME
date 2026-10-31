"""Chapitre 5 : le dépôt, arborescence commentée."""

BLOCS = [
    ("h1", "Le dépôt : où se trouve quoi"),
    ("chapeau", "Tout le logiciel est dans un seul dossier, `~/robot-g1`, suivi par Git ([[fichiers]] fichiers "
                "suivis). Voici son plan, puis ce qui n'est pas dans Git, et les conventions communes."),

    ("h2", "L'arborescence"),
    ("code",
     "robot-g1/\n"
     "├── atelier/               le paquet Python « atelier », cœur de l'Atelier G1\n"
     "│   ├── lieu/              lire, vérifier, écrire un lieu ; schémas ; contrats\n"
     "│   ├── monde/             monde.yaml → Gazebo, carte 2D, masques ; piétons\n"
     "│   ├── scan/              session, aperçu, cartes 3D et 2D, nuage, faux SLAM\n"
     "│   ├── serveur/           serveur FastAPI : routes/, pont ROS 2, processus\n"
     "│   ├── web/               l'interface : index.html, js/, css/, vendor/\n"
     "│   ├── equipe/            chatbot, relais des phrases, géométrie caméra\n"
     "│   └── tests/             tests pytest (unitaires, API, navigateur)\n"
     "├── ws/src/                l'espace de travail ROS 2\n"
     "│   ├── g1_sim/            simulation Gazebo : robot proxy, piétons\n"
     "│   ├── g1_nav/            guide, routeur, relais, repérage, réglages Nav2\n"
     "│   ├── g1_bridge/         le pont /cmd_vel → ordres de marche 7105\n"
     "│   ├── g1_jumeau/         le faux G1 de la répétition\n"
     "│   ├── g1_pilotage/       le pilotage depuis l'Atelier (conteneur)\n"
     "│   ├── g1_equipe/         chatbot, relais, caméra de poitrine\n"
     "│   └── livox_ros_driver2/, FAST_LIO/    LiDAR et SLAM de secours (tiers)\n"
     "├── docker/                le conteneur du Jetson et g1-jetson\n"
     "├── bin/                   les commandes g1-* et leurs alias gl-*\n"
     "├── tests_e2e/             les 36 critères de recette et tout.sh\n"
     "├── lieux/                 demo (tests), demo_scan, bomboclat, seance\n"
     "├── docs/                  plan, journal, séances, tutoriels, équipe, relevés\n"
     "├── choregraphies/         chorégraphies du G1 (musique/ : hors Git)\n"
     "├── setup/                 installation, env.sh, robot.sh\n"
     "├── outils/, sim/, robot/  première semaine (manette, MuJoCo…), g1-visiteurs\n"
     "└── third_party/           dépôts d'Unitree et de Livox (VERSIONS.txt)"),

    ("h2", "Ce qui n'est pas dans Git"),
    ("p", "Certains dossiers sont trop gros, personnels ou recréés à la demande. Ils sont listés dans "
          "`.gitignore` ou simplement pas ajoutés :"),
    ("table", {
        "entetes": ["Dossier", "Contenu", "Comment le retrouver"],
        "largeurs": [4.2, 6.4, 6.0],
        "taille": 9,
        "lignes": [
            ["`.venv-projet/`, `.venv-sim/`", "les deux environnements Python (plusieurs Go)",
             "`setup/installer_utilisateur.sh`"],
            ["`modeles/`", "YOLO, Vosk, Piper, Whisper", "téléchargés par l'installation"],
            ["`opt/`", "SDK compilés, archive de l'image du Jetson, jeton du pilotage", "installation, `g1-jetson`"],
            ["`journaux/`", "journaux des programmes et des recettes (`e2e_<date>/`)", "recréés à chaque lancement"],
            ["`lieux/*/scans/*/enregistrement/`", "enregistrements bruts du LiDAR (environ 100 Mo par minute)",
             "copie dans `~/robot-g1-donnees/2026-10-27_seance1/`"],
            ["`lieux/seance/`", "le lieu du vrai scan du 27/10 (pas encore ajouté à Git)",
             "copié toutes les 20 min dans `~/robot-g1-donnees/lieu_seance_courant/`"],
            ["`choregraphies/musique/`", "les musiques de l'utilisateur", "jamais de musique protégée dans le dépôt"],
            ["`ws/build`, `ws/install`, `ws/log`", "résultats de la compilation", "`colcon build --symlink-install`"],
        ],
    }),
    ("p", "En dehors du dépôt, `~/robot-g1-donnees/` garde ce qui ne doit pas se perdre : les copies du scan "
          "du 27/10, les décisions et les résumés de la vague 5, les documents Word, et le script de "
          "sauvegarde qui pousse le travail en cours dans la branche Git `sauvegarde-vague5`."),

    ("h2", "Les conventions communes"),
    ("puces", [
        "**Français partout** : interface, messages, documentation. Les noms de fichiers et de champs sont en "
        "français, sans accents (`salles.yaml`, `phrase_arrivee`).",
        "**Identifiants** (lieu, étage, salle, nœud, mur, objet, piéton) : lettres minuscules, chiffres, `_` "
        "et `-`, 40 caractères au plus (`^[a-z0-9][a-z0-9_-]{0,39}$`). On évite `yes`, `no`, `on`, `off`, "
        "que YAML lit comme des booléens.",
        "**Unités** : mètres et radians ; `theta` depuis l'axe x, dans le sens inverse des aiguilles d'une montre.",
        "**`--lieu`** accepte un identifiant (`demo` désigne `~/robot-g1/lieux/demo`, ou `$ATELIER_LIEUX/demo`) "
        "ou un chemin. Chaque outil n'écrit que dans le dossier du lieu, sauf ses journaux, dans `journaux/`.",
        "**Écritures sûres** : un fichier est écrit à côté, puis renommé (jamais à moitié écrit), et vérifié "
        "par son schéma avant d'être accepté.",
        "**`lieux/demo`** est la référence des tests : on ne l'écrit jamais ; les tests travaillent sur des "
        "copies dans des dossiers temporaires. `lieux/bomboclat` et `lieux/seance` sont à l'utilisateur.",
        "**Messages d'erreur** : ils disent ce qui ne va pas et quoi faire, en français ; le serveur ne "
        "répond jamais par une erreur 500 brute.",
    ]),
]
