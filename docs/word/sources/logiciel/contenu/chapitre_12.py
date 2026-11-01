"""Chapitre 12 : les tests."""

BLOCS = [
    ("h1", "Les tests"),
    ("chapeau", "Tout le logiciel se teste sans robot et sans écran. Cinq sortes de tests, du plus petit (une "
                "fonction) au plus grand (un scénario complet, du navigateur à Gazebo), et 36 critères de "
                "recette qui disent si une vague est finie. À la recette de la vague 5, le 01/11/2026 : "
                "2 281 tests réussis, aucun échec, et 36 / 36."),

    ("h2", "Cinq sortes de tests"),
    ("table", {
        "entetes": ["Sorte", "Où", "Outil", "Combien", "Durée (01/11)"],
        "largeurs": [3.8, 4.0, 3.5, 3.2, 2.1],
        "taille": 8.5,
        "premiere_col_gras": True,
        "lignes": [
            ["Tests unitaires et de l'API", "`atelier/tests/` (74 fichiers)", "pytest ; client de test de FastAPI",
             "[[tests_atelier]] tests", "11 min"],
            ["Tests des paquets ROS 2", "`ws/src/g1_*/test/`", "`colcon test` (pytest et contrôles de style)",
             "[[fonctions_test_ros]] fonctions (750 tests avec les contrôles de style)", "7 min"],
            ["Tests du conteneur", "`docker/tests/`", "pytest, Docker", "[[tests_docker]] tests", "30 s"],
            ["Tests dans le navigateur", "`atelier/tests/test_*_navigateur.py`", "Firefox sans fenêtre, geckodriver",
             "12 fichiers", "compris ci-dessus"],
            ["Critères de recette", "`tests_e2e/critere_NN_*.sh`", "bash et outils Python ; Gazebo, Nav2, Atelier",
             "[[criteres]] critères", "2 h 10"],
        ],
    }),
    ("p", "Les tests dans le navigateur pilotent un vrai Firefox, sans fenêtre, par geckodriver (un petit client "
          "WebDriver écrit dans `test_serveur_navigateur.py`, sans Selenium ni Playwright) : ils cliquent, "
          "mesurent la mise en page et lisent la page. Les critères de recette montent tout pour de vrai : "
          "Gazebo sans fenêtre, Nav2, le serveur de l'Atelier, le faux G1, le conteneur en local."),

    ("h2", "Comment les lancer"),
    ("code", "cd ~/robot-g1\n"
             ".venv-projet/bin/python -m pytest atelier/tests -q \\\n"
             "    --ignore=atelier/tests/test_robot_reperage_ros.py\n"
             "ROS_LOCALHOST_ONLY=0 .venv-projet/bin/python -m pytest \\\n"
             "    atelier/tests/test_robot_reperage_ros.py -q\n"
             ".venv-projet/bin/python -m pytest docker/tests -q\n"
             "cd ws && colcon test --executor sequential --packages-select \\\n"
             "    g1_sim g1_nav g1_bridge g1_jumeau g1_pilotage g1_equipe\n"
             "colcon test-result --all\n"
             "~/robot-g1/tests_e2e/tout.sh            # les 36 critères, « N / 36 » (2 h 10)\n"
             "~/robot-g1/tests_e2e/tout.sh 31 32 33   # seulement certains critères"),
    ("p", "Le fichier `test_robot_reperage_ros.py` se lance à part, avec `ROS_LOCALHOST_ONLY=0`, car ses programmes "
          "l'imposent. La carte 3D a besoin de WebGL : lancez `tout.sh` depuis un terminal de la session "
          "graphique (`DISPLAY=:1` ; aucune fenêtre ne s'ouvre), sinon le critère 32 répond « en attente ». Les "
          "critères passent tous par `tests_e2e/commun.sh`, qui met `ROS_LOCALHOST_ONLY=0` : avec 1, Nav2 lance trop "
          "de participants pour la seule interface locale, et des nœuds plantent."),

    ("h2", "Les règles des tests"),
    ("puces", [
        "**Jamais le vrai robot** : `G1_SLAM_FAUX=1` refuse toute commande vers le robot (ni ssh, ni ping vers "
        "192.168.123.x) ; le mode robot ne s'essaie qu'en répétition.",
        "**Jamais d'écran** : Gazebo, Firefox et les nœuds tournent sans fenêtre.",
        "**Jamais `lieux/demo`** : chaque test travaille sur une copie, dans un dossier temporaire (`ATELIER_LIEUX`).",
        "**Chacun son domaine ROS 2** (`E2E_DOMAINE`, 36 par défaut) et sa partition Gazebo, pour ne pas se gêner.",
        "**Tout s'arrête à la fin**, même après une erreur ou un Ctrl+C : Gazebo, Nav2, le serveur, les faux "
        "services, les enregistrements, les conteneurs.",
        "**Codes de sortie** : 0 réussi, 1 échoué, 77 « en attente » (une pièce manque, par exemple le modèle YOLO). "
        "Les journaux vont dans `~/robot-g1/journaux/e2e_<date>/`.",
    ]),

    ("h2", "Les chiffres, vague après vague"),
    ("table", {
        "entetes": ["Vague", "Tests de atelier/tests", "Paquets ROS 2 (colcon)", "Conteneur", "Recette"],
        "largeurs": [2.0, 4.1, 5.0, 2.2, 3.3],
        "taille": 8.5,
        "premiere_col_gras": True,
        "lignes": [
            ["1 (25/10)", "408 réussis", "136 tests (g1_sim, g1_nav)", "—", "10 / 10"],
            ["2 (25/10)", "609 réussis", "138 tests", "—", "15 / 15"],
            ["3 (26/10)", "694 réussis", "332 tests (4 paquets)", "54", "18 / 20, puis 20 / 20"],
            ["4 (26/10)", "1 131 réussis", "6 paquets, sans échec", "58", "30 / 30 en un passage"],
            ["5, contrats (31/10)", "1 265 réussis", "6 paquets (un test sensible au réglage réseau)", "—",
             "critères 31 à 36 écrits par les agents"],
            ["5, recette (01/11)", "1 466 réussis, 3 sautés ; repérage ROS : 4 réussis",
             "6 paquets, 750 tests : 741 réussis, 9 sautés, 0 échec", "70 réussis, 1 sauté",
             "36 / 36 en un passage (2 h 08)"],
        ],
    }),

    ("h2", "La recette de la vague 5 (01/11/2026)"),
    ("p", "La recette a tourné sur le PC du projet, sans robot, dans son propre domaine ROS 2 (113), sur des "
          "copies des lieux `demo` et `seance` ; Firefox, sans fenêtre, avait la 3D par l'affichage de la "
          "session graphique (`DISPLAY=:1`). D'abord la compilation (`colcon build --symlink-install` : les "
          "8 paquets en 3 s) et les images du Jetson, refaites parce que le code avait changé depuis leur "
          "construction (amd64 en 26 s, arm64 en 45 s, avec le cache) ; puis toutes les suites :"),
    ("table", {
        "legende": "Les suites de tests à la recette du 01/11 (sur le code final)",
        "entetes": ["Suite", "Résultat", "Durée"],
        "largeurs": [6.4, 8.0, 2.2],
        "taille": 8.5,
        "premiere_col_gras": True,
        "lignes": [
            ["`atelier/tests` (sans le repérage ROS)", "1 466 réussis, 3 sautés (des scans réels dans Gazebo, "
             "seulement avec `G1_SCAN_SIMULATION=1`)", "673 s"],
            ["`test_robot_reperage_ros.py` (`ROS_LOCALHOST_ONLY=0`)", "4 réussis", "33 s"],
            ["`docker/tests` (images refaites)", "70 réussis, 1 sauté (il demande la vraie caméra)", "29 s"],
            ["`g1_sim`", "57 tests, 0 échec", "130 s"],
            ["`g1_nav`", "263 tests, 0 échec, 4 sautés", "74 s"],
            ["`g1_bridge`", "179 tests, 0 échec, 1 sauté", "93 s"],
            ["`g1_jumeau`", "104 tests, 0 échec, 1 sauté", "63 s"],
            ["`g1_pilotage`", "104 tests, 0 échec, 1 sauté", "7 s"],
            ["`g1_equipe`", "43 tests, 0 échec, 2 sautés", "45 s"],
            ["`fast_lio`, `livox_ros_driver2` (code tiers, hors Git)", "`fast_lio` n'a pas de test ; "
             "`livox_ros_driver2` : 891 échecs et 1 erreur de style sur le code d'origine, comme à la vague 4 "
             "(pas une régression)", "7 s"],
            ["**Total pour le code du projet**", "**2 281 réussis, 13 sautés, 0 échec**", "**20 min environ**"],
        ],
    }),
    ("p", "Puis `tests_e2e/tout.sh`, lancé depuis la session graphique (`DISPLAY=:1 E2E_DOMAINE=113 "
          "tests_e2e/tout.sh`), a joué les 36 critères de 17 h 25 à 19 h 33 (7 662 s) : **36 / 36** au premier "
          "passage, aucun critère rejoué. La durée de chacun est dans le tableau des critères, ci-dessous. "
          "Quelques résultats : le chemin de secours « bloqué, détour, arrivé » (critère 5) ; 19 trajets sur 20 "
          "dans la foule, soit 95 % (6) ; un recouvrement de 99,4 % pour le scan simulé (7) et de 99,6 % pour le "
          "scan par l'API (11) ; une précision de 99,8 % pour la carte du scan (12), et de 99,8 % avec 99,7 % de "
          "recouvrement pour le scan corrigé (33) ; 5 arrivées sur 5 devant un passant immobile, toujours à "
          "0,20 m au moins (23) ; 10 arrivées sur 10 et aucun contact causé par le robot face à des passants qui "
          "coupent la route (24) ; aucune faute dans les 165 mesures de la mise en page (31) ; la carte 3D avec "
          "WebGL et 305 820 points (32) ; l'ARRÊT en 0,06 à 0,19 s (36)."),
    ("encadre", "Les marges à surveiller",
     ["Tous les critères passent, mais quatre passent de peu :",
      "- **critère 26** (accompagnement) : le robot ralentit à 57 % de sa vitesse, pour un seuil de 60 % ;",
      "- **critère 6** (foule) : 19 trajets sur 20 ; un trajet bloqué par la foule a dépassé 180 s ;",
      "- **critère 25** (groupe qui bouche) : le groupe qui reste est passé en 174 et 171 s, pour une limite "
      "de 180 s par trajet ;",
      "- **critère 24** (passants croisés) : avec des passants qui s'écartent, un échec sur 5 (bloqué, détour, "
      "puis bloqué à nouveau), que le critère ne compte pas : il ne compte que les contacts."], "attention"),

    ("h2", "Les 36 critères de recette"),
    ("table", {
        "legende": "Les critères de recette, tous joués sans robot ni écran, et leur durée à la recette du 01/11",
        "entetes": ["N°", "Critère", "Ce qui est vérifié", "Vague", "Durée"],
        "largeurs": [0.9, 3.3, 9.9, 1.1, 1.4],
        "taille": 8,
        "lignes": [
            ["1", "Monde inventé", "lieu « essai » : 6 murs, un passage, 3 objets, 2 piétons ; `g1-lieu valider` sans erreur", "1", "1 s"],
            ["2", "Carte sans scan", "`g1-monde generer` : monde Gazebo, carte, masque ; des pixels connus vérifiés", "1", "18 s"],
            ["3", "Simulation", "Gazebo sans fenêtre : `/odom` et `/points` publiés en moins de 30 s", "1", "10 s"],
            ["4", "Point A → point B", "une salle placée par l'API, « Y aller » : arrivé à moins de 0,3 m", "1", "67 s"],
            ["5", "Chemin de secours", "une boîte dans le couloir nord : `bloque → detour → arrive`", "1", "178 s"],
            ["6", "Foule", "5 piétons, 20 trajets tirés au sort : 90 % de réussite au moins, et un CSV", "1", "1 324 s"],
            ["7", "Scan simulé", "tour des couloirs enregistré, carte 3D puis 2D : 80 % de recouvrement au moins", "1", "180 s"],
            ["8", "Service du robot simulé", "faux service : 1801 → 1802 → 1804 → 1102 ; `MoteurUnitree` jusqu'à b204", "1", "94 s"],
            ["9", "Interface", "le parcours complet dans Firefox sans fenêtre", "1", "11 s"],
            ["10", "Point d'entrée", "`g1-atelier` sert la page et l'API ; compté si les 9 premiers réussissent", "1", "2 s"],
            ["11", "Scan intégré par l'API", "Scan, aperçu en direct, Fin, `termine` ; 90 % de recouvrement ; rien ne reste", "2", "171 s"],
            ["12", "Carte du scan", "carte, nuage et nuage d'affichage, sans reconnaissance ; précision 0,98 (réécrit en vague 5)", "2", "2 s"],
            ["13", "Monde du scan", "adoption, monde maillé, simulation et une salle atteinte (réécrit en vague 5)", "2", "65 s"],
            ["14", "Répétition du mode robot", "1801 puis 1802 reçus par le faux service, sujets du SLAM enregistrés", "2", "57 s"],
            ["15", "Robustesse", "refus clairs, jamais d'erreur 500 ; flèches avec homme mort ; écran de scan dans Firefox", "2", "63 s"],
            ["16", "Conteneur", "image amd64, démarrage en local, nœuds vus de l'hôte, verrou, arrêt propre, jamais de ssh", "3", "19 s"],
            ["17", "Pont et faux G1", "ordres 7105 bien formés, 10 par seconde ; plafonds, NaN, `/guide/stop`, `/pont/arret`", "3", "70 s"],
            ["18", "Repérage", "non repéré avant ; « Repérer » ; position à 0,1 m malgré la dérive ; perte puis reprise", "3", "46 s"],
            ["19", "Niveau 2 complet", "depuis l'Atelier, tout par le pont : b204 à moins de 0,3 m ; détour ; rien ne reste", "3", "243 s"],
            ["20", "Sécurité", "un témoin : jamais plus de 5 cm hors d'un mouvement permis ; pannes, consignes absurdes", "3", "85 s"],
            ["21", "Point principal", "un seul et obligatoire ; migration ; simulation et repérage qui en partent", "4", "43 s"],
            ["22", "Retour automatique", "b204, puis retour seul au point principal, à 0,3 m et 10° près", "4", "195 s"],
            ["23", "Passant immobile", "5 arrivées, aucun contact, 0,20 m bord à bord au moins à chaque essai", "4", "298 s"],
            ["24", "Passants croisés", "en face et qui coupent la route : aucun contact causé par le robot", "4", "1 567 s"],
            ["25", "Groupe qui bouche", "attente, puis passage, ou détour après 20 s ; banc de la foule à 90 %", "4", "1 681 s"],
            ["26", "Accompagnement", "faux visiteur : ralentir, attendre, retrouvé ; ou perdu, puis retour", "4", "181 s"],
            ["27", "Perdu en route", "repérage coupé : `perdu` en moins de 4 s, robot arrêté ; reprise, ou échec après 15 s", "4", "113 s"],
            ["28", "Pilotage", "postures, joystick avec homme mort, gestes, voix, LED, verrou ; interdits jamais envoyés", "4", "52 s"],
            ["29", "Danses et chorégraphies", "liste, danse 604 avec la zone libre, `exemple_kpop` dans les limites, ARRÊT", "4", "103 s"],
            ["30", "Équipe", "fichiers valides, écrans ; « je cherche la salle b204 » → le robot y va", "4", "78 s"],
            ["31", "Coque", "accueil et espace de travail ; 165 mesures sans défilement ni élément coupé ; thème", "5", "108 s"],
            ["32", "Carte 3D", "accueil et salle posés en 3D, mêmes coordonnées en 2D ; vues, zoom ; sans WebGL", "5", "116 s"],
            ["33", "Scan corrigé", "sans reconnaissance ; « damier » simulé corrigé ; monde maillé à 0,9 fois le temps réel", "5", "283 s"],
            ["34", "Pont : vitesse minimale et mode", "0,1 m/s demandé → 0,2 envoyé ; assis → `pas_en_marche` ; 7001 à 1 Hz", "5", "59 s"],
            ["35", "Caméra", "fausse source → `camera_usb` → flux MJPEG → YOLO → cadres dans Firefox", "5", "25 s"],
            ["36", "ARRÊT global", "guide, téléopération et pilotage arrêtés en moins d'1 s ; verrou ; touche Échap", "5", "54 s"],
            ["", "**Recette du 01/11**", "**36 / 36 au premier passage**, de 17 h 25 à 19 h 33 (2 h 08)", "", "**7 662 s**"],
        ],
    }),
]
