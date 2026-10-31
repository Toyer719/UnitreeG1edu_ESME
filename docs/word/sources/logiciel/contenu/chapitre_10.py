"""Chapitre 10 : comment le logiciel a été construit."""

BLOCS = [
    ("h1", "Comment le logiciel a été construit"),
    ("chapeau", "Le logiciel n'a pas été écrit ligne par ligne par une seule personne : Claude, une IA, l'a "
                "construit avec une équipe d'autres instances de Claude (les « agents »), en cinq vagues, du "
                "25 au 31/10/2026. Ce chapitre explique la méthode, la chronologie, les décisions et les "
                "problèmes rencontrés."),

    ("h2", "La méthode : un plan, des contrats, des agents, une recette"),
    ("schema", "methode", "Le déroulé d'une vague", 10.5, 13.0),
    ("puces", [
        "**Le plan** (`docs/plan-atelier-multi-agents.md`, sections 1 à 12) est la référence commune : le but, "
        "les contraintes, l'architecture, les formats, et une fiche par agent. Chaque vague y ajoute sa section.",
        "**Les contrats** sont figés avant le travail en parallèle : les formats de fichiers (schémas JSON), "
        "les sujets ROS 2 et leurs messages, les routes de l'API, les arguments des lancements, et du **code "
        "partagé** déjà écrit et testé (fonctions, valeurs, squelettes de modules). Ils font l'objet d'un commit "
        "à part (« contrats »). Ainsi, chaque agent sait exactement ce que les autres vont produire.",
        "**Les agents** sont d'autres instances de Claude, lancées par un script d'orchestration. Chacun a sa "
        "fiche (sa mission), **ses fichiers** (aucun fichier n'a deux propriétaires), son domaine ROS 2, sa "
        "partition Gazebo et son port, pour ne jamais gêner les autres. S'il a besoin d'un changement chez un "
        "autre, il ne le fait pas : il le note, et fait sans, avec un bouchon.",
        "**L'intégrateur** (Claude, dans la session de l'utilisateur) écrit le plan et les contrats, puis "
        "**assemble** : il compile tout, corrige les écarts entre les modules, relance tous les tests, écrit le "
        "journal (`docs/journal-atelier.md`) et le README ; lui seul fait les commits.",
        "**La recette** : des critères mesurables, tous joués sans robot ni écran (« le robot arrive à moins de "
        "0,3 m en moins de 180 s », « zéro contact causé par le robot »). `tests_e2e/tout.sh` les lance tous et "
        "affiche « N / 36 ». Une vague n'est finie que quand tous passent.",
        "**Les précisions de l'assemblage** : les écarts acceptés à l'assemblage sont écrits dans le plan "
        "(sections 10.12, 11.12, 12.13) et font foi comme les contrats.",
    ]),

    ("h2", "La chronologie"),
    ("schema", "vagues", "Du PC installé à la vague 5", 14.0, 12.0),
    ("table", {
        "legende": "Les vagues de construction",
        "entetes": ["Vague", "Quand", "Ce qui a été construit", "Recette", "Commits"],
        "largeurs": [1.6, 2.6, 7.7, 1.9, 2.8],
        "taille": 8.5,
        "premiere_col_gras": True,
        "lignes": [
            ["Départ", "21-22/10", "PC installé (Ubuntu 22.04, ROS 2, Nav2, Gazebo, SDK Unitree, YOLO, voix) ; "
             "premier branchement du robot et relevé du Jetson", "—", "8b5b119 (25/10)"],
            ["1", "25/10, 14 h → 17 h", "Contrats, bibliothèque des lieux, puis 5 agents en parallèle : générateur "
             "de monde, simulation Gazebo, navigation (Nav2, routeur, guide, banc), serveur et interface, scan (client "
             "du SLAM, faux service) et testeur ; puis l'assemblage (8 agents en tout)", "10 / 10",
             "0217cf0 → 5c30b39, b3ac22a"],
            ["2", "25/10, 18 h 30 → 21 h", "Le scan intégré : `g1-scan`, aperçu en direct, reconnaissance des murs, "
             "passages et meubles, onglet Scan, téléopération ; 4 agents en parallèle (6 en tout)", "15 / 15", "6d7c1dc → e195059"],
            ["3", "25/10, 22 h 30 → 26/10, 2 h", "Le vrai robot en répétition : conteneur du Jetson, pont 7105, faux G1, "
             "repérage 1804 et relais ; 3 agents en parallèle", "20 / 20", "c6e6fe7 → 5c5a643"],
            ["4", "26/10, 3 h 40 → 18 h 20", "Point principal, passants crédibles, comportement du guide (retour, "
             "accompagnement, perdu), pilotage et danses, emplacements de l'équipe ; 5 agents en parallèle. Puis la Vue "
             "du robot "
             "dans Pilotage et le tutoriel de la séance n° 1", "30 / 30", "ac1c59b → 5ac563c, ac255ad, 4e5fb73"],
            ["Séance 1", "27/10", "Premier essai sur le robot : scan réel, ordre de marche 7105 (chapitre 9)", "—", "a5d0f05"],
            ["5", "31/10", "Interface à la SolidWorks, carte 3D, scan corrigé sans reconnaissance, vitesse minimale et "
             "mode du pont, caméra de poitrine ; phase « comprendre » (5 lecteurs), 5 agents, assemblage ; "
             "vérification finale en cours le 31/10 au soir", "36 critères", "5bb9e95 → d0730c1"],
        ],
    }),
    ("p", "Le nombre de tests de `atelier/tests` montre la croissance : 408 à la vague 1, 609 à la vague 2, 694 "
          "à la vague 3, 1 131 à la vague 4, 1 265 avec les contrats de la vague 5, et [[tests_atelier]] au moment "
          "de la génération de ce document."),

    ("h2", "Les décisions et leurs raisons"),
    ("table", {
        "legende": "Les principales décisions",
        "entetes": ["Décision", "Pourquoi"],
        "largeurs": [6.4, 10.2],
        "taille": 8.5,
        "lignes": [
            ["ROS 2 Humble partout, dans un conteneur Docker sur le Jetson", "Le Jetson est en Ubuntu 20.04 avec Foxy ; "
             "Nav2 et Gazebo Fortress sont en Humble ; le conteneur ne change rien au robot."],
            ["Image `ros:humble-ros-base-jammy` plutôt qu'une image L4T de NVIDIA", "Nav2 existe en paquets apt pour arm64 "
             "(sinon des heures de compilation) ; la navigation n'a pas besoin du GPU ; un seul Dockerfile pour le PC et le Jetson."],
            ["SLAM et repérage d'Unitree plutôt que FAST-LIO2 et AMCL", "Ils tournent déjà sur le robot, avec son LiDAR ; "
             "FAST-LIO2 et AMCL restent des solutions de secours (`--localisation amcl`)."],
            ["Navigation « niveau 2 » : Nav2 + pont 7105, plutôt que la navigation d'Unitree (1102)", "1102 va en ligne "
             "droite et s'arrête devant un obstacle ; Nav2 contourne, ralentit, attend. 1102 reste en niveau 1 (`MoteurUnitree`)."],
            ["Simulation avec un robot proxy qui glisse", "La marche du G1 ne se simule pas avec Nav2 ; pour la navigation, "
             "comptent la taille, les vitesses et le LiDAR, reproduits fidèlement."],
            ["Ordres de 0,5 s répétés 10 fois par seconde", "C'est l'homme mort : si quoi que ce soit tombe, le robot s'arrête seul."],
            ["Une répétition complète contre un faux G1", "Le robot n'est disponible que par séances : tout le déroulé "
             "réel est essayé avant, sur le PC."],
            ["Pilotage par HTTP et WebSocket vers le conteneur", "Les sécurités au plus près du robot ; DDS par le Wi-Fi est fragile."],
            ["Interface web sans compilation, bibliothèques copiées dans `vendor/`", "Rien à installer, marche sans Internet "
             "et sur une tablette ; pas de chaîne d'outils JavaScript à maintenir."],
            ["Formats en YAML vérifiés par des schémas JSON, tout en français", "Les fichiers se lisent et se corrigent à la "
             "main ; les erreurs disent quoi corriger."],
            ["Un seul point principal par lieu (vague 4)", "L'accueil, le départ de la simulation, le point de repérage et "
             "le retour étaient trois points distincts : un seul suffit."],
            ["Retirer la reconnaissance des meubles (vague 5)", "Sur le vrai scan : 92 objets dont 11 « personnes » effacées "
             "à tort, aucune porte ; le nuage montre déjà les meubles."],
            ["Monde d'un étage scanné = la carte extrudée en un seul maillage", "1 617 boîtes séparées faisaient tourner "
             "Gazebo à 0,59 fois le temps réel ; fusionnées en un maillage, à 1,0."],
            ["Nuage binaire (Float32) pour la carte 3D", "Une seule requête, environ 3,6 Mo pour 300 000 points, rien à décoder."],
            ["Caméra : Pillow et v4l2-ctl dans le conteneur, YOLO sur le PC, flux MJPEG", "9 Mo de plus dans l'image au "
             "lieu de 580 Mo pour OpenCV ; la carte graphique du PC ; une balise `<img>` affiche le flux."],
            ["Interface « à la SolidWorks », habillée comme Unitree Explore (vague 5)", "La demande de l'utilisateur ; "
             "l'ancienne avait 12 onglets, des panneaux écrasés et des pages qui ne défilaient pas."],
        ],
    }),
    ("p", "Pour la vague 5, l'utilisateur dormait et avait délégué toutes les décisions : elles sont écrites, "
          "avec leurs raisons, dans `~/robot-g1-donnees/vague5/DECISIONS.md` (interface I1 à I10, scan S1 à S7, "
          "robot R1 à R4)."),

    ("h2", "Les problèmes rencontrés et leurs solutions"),
    ("table", {
        "legende": "Problèmes et solutions",
        "entetes": ["Problème", "Cause", "Solution"],
        "largeurs": [4.6, 5.6, 6.4],
        "taille": 8.5,
        "lignes": [
            ["Scan de l'Atelier moins bon que celui d'Unitree Explore (31/10)", "Trois bogues du traitement : horloge "
             "(138 s d'écart), passants retirés depuis de fausses positions, sol penché", "Chaîne corrigée, scan du 27/10 "
             "retraité et adopté (chapitre 8)"],
            ["Agents coupés par la limite d'utilisation (26/10 vers 9 h ; 31/10 à 19 h)", "Les longues sessions de travail "
             "dépassent la limite de la session", "Sauvegarde intermédiaire (commit b9d1639), reprise automatique "
             "planifiée, agents finis repris depuis leur résultat"],
            ["PC éteint le matin du 31/10, redémarré à 14 h 54 : dossier temporaire vidé", "Le dossier de travail "
             "`/tmp` est effacé à "
             "chaque démarrage", "Rapports de la phase « comprendre » et première version de ce document (58 pages) "
             "perdus ; désormais tout ce qui compte va dans `~/robot-g1-donnees/`, et le travail en cours part toutes "
             "les 20 minutes dans la branche `sauvegarde-vague5`"],
            ["Banc de la foule à 85 % (vague 3)", "`/guide/stop` puis `/guide/aller` sur deux sujets : DDS ne garde pas "
             "leur ordre", "Pause de 1 s après un arrêt dans `g1-banc`"],
            ["Le robot ne s'arrêtait pas devant un groupe qui bouche le couloir (vague 4)", "Nav2 le voyait et le "
             "contournait de lui-même", "Règle du guide : personne à moins de 2,5 m dans le couloir → robot arrêté, "
             "« Pardon, puis-je passer ? », détour après 20 s"],
            ["Piétons sans corps dans Gazebo (vague 1)", "Les « acteurs » de Gazebo n'ont pas de collision", "Piétons-corps "
             "qui réagissent au robot (vague 4)"],
            ["Panneaux écrasés à 24 px, page qui ne défile pas (interface de la vague 4)", "Mise en page CSS mal "
             "contrainte", "Nouvelle "
             "coque : page fixe, colonnes qui défilent seules ; 186 mesures au critère 31"],
            ["Pas de WebGL dans Firefox sans fenêtre", "Pas d'accès à la carte graphique sans affichage", "Lancer les tests "
             "depuis la session graphique (`DISPLAY=:1`)"],
            ["Docker 29 prenait l'image amd64 au lieu de l'arm64", "Le nom de l'image désigne les deux architectures",
             "Image de base désignée par son empreinte"],
            ["Image du Jetson trop grosse (0,74 Go compressés)", "Nav2 complet apporte RViz et OpenCV", "Nav2 installé "
             "composant par composant : 0,47 Go"],
            ["Séance 1 : le scan échouait (erreur 3104)", "Services `lidar_driver` et `unitree_slam` arrêtés sur le robot",
             "Démarrés depuis le PC ; à vérifier après un redémarrage du robot"],
            ["Séance 1 : robot assis mais pont « en mouvement »", "Le robot accepte 7105 sans bouger hors du mode marche",
             "Lecture du mode (7001) et état `pas_en_marche` (vague 5)"],
        ],
    }),

    ("h2", "Ce que la méthode apporte, et ses limites"),
    ("puces", [
        "**Ce qu'elle apporte** : beaucoup de travail en peu de temps (cinq agents en parallèle), sans conflit "
        "grâce aux contrats ; tout est testé et retesté à chaque vague ; tout est essayé sans robot avant chaque "
        "séance ; le journal et le plan gardent la trace de chaque décision.",
        "**Ses limites** : rien n'est sûr tant que le vrai robot ne l'a pas confirmé (plusieurs formats d'Unitree "
        "viennent d'une documentation non officielle) ; les sessions longues sont coupées par la limite "
        "d'utilisation ; ce que l'IA garde dans un dossier temporaire peut se perdre ; et l'utilisateur doit "
        "relire, essayer et dire ce qui ne lui convient pas : c'est ainsi que sont nées la vague 4 (le point "
        "principal), la vague 5 (l'interface, le scan) et ce document.",
    ]),
]
