"""Chapitre 12 : les tests."""

BLOCS = [
    ("h1", "Les tests"),
    ("chapeau", "Tout le logiciel se teste sans robot et sans écran. Cinq sortes de tests, du plus petit (une "
                "fonction) au plus grand (un scénario complet, du navigateur à Gazebo), et 36 critères de "
                "recette qui disent si une vague est finie."),

    ("h2", "Cinq sortes de tests"),
    ("table", {
        "entetes": ["Sorte", "Où", "Outil", "Combien", "Durée"],
        "largeurs": [4.0, 4.0, 3.6, 3.1, 1.9],
        "taille": 8.5,
        "premiere_col_gras": True,
        "lignes": [
            ["Tests unitaires et de l'API", "`atelier/tests/` (74 fichiers)", "pytest ; client de test de FastAPI",
             "[[tests_atelier]] tests", "10 min"],
            ["Tests des paquets ROS 2", "`ws/src/g1_*/test/`", "`colcon test` (pytest et contrôles de style)",
             "[[fonctions_test_ros]] fonctions", "quelques min"],
            ["Tests du conteneur", "`docker/tests/`", "pytest, Docker", "[[tests_docker]] tests", "1 min"],
            ["Tests dans le navigateur", "`atelier/tests/test_*_navigateur.py`", "Firefox sans fenêtre, geckodriver",
             "une douzaine de fichiers", "compris ci-dessus"],
            ["Critères de recette", "`tests_e2e/critere_NN_*.sh`", "bash et outils Python ; Gazebo, Nav2, Atelier",
             "[[criteres]] critères", "environ 3 h"],
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
             "~/robot-g1/tests_e2e/tout.sh            # les 36 critères, « N / 36 » (3 h)\n"
             "~/robot-g1/tests_e2e/tout.sh 31 32 33   # seulement certains critères"),
    ("p", "Le fichier `test_robot_reperage_ros.py` se lance à part, avec `ROS_LOCALHOST_ONLY=0`, car ses programmes "
          "l'imposent. La carte 3D a besoin de WebGL : lancez `tout.sh` depuis un terminal de la session "
          "graphique (`DISPLAY=:1` ; aucune fenêtre ne s'ouvre), sinon le critère 32 répond « en attente »."),

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
            ["5, au moment de ce document", "[[tests_atelier]] tests", "[[fonctions_test_ros]] fonctions de test",
             "[[tests_docker]]", "36 critères, vérification finale en cours"],
        ],
    }),
    ("p", "Les chiffres de la vague 5 finie (tests réussis et « N / 36 ») sont ceux de la vérification finale, "
          "lancée le 31/10 au soir : ils seront dans le journal de l'Atelier et dans les fiches de la séance n° 2."),

    ("h2", "Les 36 critères de recette"),
    ("table", {
        "legende": "Les critères de recette, tous joués sans robot ni écran",
        "entetes": ["N°", "Critère", "Ce qui est vérifié", "Vague"],
        "largeurs": [0.9, 3.4, 11.2, 1.1],
        "taille": 8,
        "lignes": [
            ["1", "Monde inventé", "lieu « essai » : 6 murs, un passage, 3 objets, 2 piétons ; `g1-lieu valider` sans erreur", "1"],
            ["2", "Carte sans scan", "`g1-monde generer` : monde Gazebo, carte, masque ; des pixels connus vérifiés", "1"],
            ["3", "Simulation", "Gazebo sans fenêtre : `/odom` et `/points` publiés en moins de 30 s", "1"],
            ["4", "Point A → point B", "une salle placée par l'API, « Y aller » : arrivé à moins de 0,3 m", "1"],
            ["5", "Chemin de secours", "une boîte dans le couloir nord : `bloque → detour → arrive`", "1"],
            ["6", "Foule", "5 piétons, 20 trajets tirés au sort : 90 % de réussite au moins, et un CSV", "1"],
            ["7", "Scan simulé", "tour des couloirs enregistré, carte 3D puis 2D : 80 % de recouvrement au moins", "1"],
            ["8", "Service du robot simulé", "faux service : 1801 → 1802 → 1804 → 1102 ; `MoteurUnitree` jusqu'à b204", "1"],
            ["9", "Interface", "le parcours complet dans Firefox sans fenêtre", "1"],
            ["10", "Point d'entrée", "`g1-atelier` sert la page et l'API ; compté si les 9 premiers réussissent", "1"],
            ["11", "Scan intégré par l'API", "Scan, aperçu en direct, Fin, `termine` ; 90 % de recouvrement ; rien ne reste", "2"],
            ["12", "Carte du scan", "carte, nuage et nuage d'affichage, sans reconnaissance ; précision 0,98 (réécrit en vague 5)", "2"],
            ["13", "Monde du scan", "adoption, monde maillé, simulation et une salle atteinte (réécrit en vague 5)", "2"],
            ["14", "Répétition du mode robot", "1801 puis 1802 reçus par le faux service, sujets du SLAM enregistrés", "2"],
            ["15", "Robustesse", "refus clairs, jamais d'erreur 500 ; flèches avec homme mort ; écran de scan dans Firefox", "2"],
            ["16", "Conteneur", "image amd64, démarrage en local, nœuds vus de l'hôte, verrou, arrêt propre, jamais de ssh", "3"],
            ["17", "Pont et faux G1", "ordres 7105 bien formés, 10 par seconde ; plafonds, NaN, `/guide/stop`, `/pont/arret`", "3"],
            ["18", "Repérage", "non repéré avant ; « Repérer » ; position à 0,1 m malgré la dérive ; perte puis reprise", "3"],
            ["19", "Niveau 2 complet", "depuis l'Atelier, tout par le pont : b204 à moins de 0,3 m ; détour ; rien ne reste", "3"],
            ["20", "Sécurité", "un témoin : jamais plus de 5 cm hors d'un mouvement permis ; pannes, consignes absurdes", "3"],
            ["21", "Point principal", "un seul et obligatoire ; migration ; simulation et repérage qui en partent", "4"],
            ["22", "Retour automatique", "b204, puis retour seul au point principal, à 0,3 m et 10° près", "4"],
            ["23", "Passant immobile", "5 arrivées, aucun contact, 0,20 m bord à bord au moins à chaque essai", "4"],
            ["24", "Passants croisés", "en face et qui coupent la route : aucun contact causé par le robot", "4"],
            ["25", "Groupe qui bouche", "attente, puis passage, ou détour après 20 s ; banc de la foule à 90 %", "4"],
            ["26", "Accompagnement", "faux visiteur : ralentir, attendre, retrouvé ; ou perdu, puis retour", "4"],
            ["27", "Perdu en route", "repérage coupé : `perdu` en moins de 4 s, robot arrêté ; reprise, ou échec après 15 s", "4"],
            ["28", "Pilotage", "postures, joystick avec homme mort, gestes, voix, LED, verrou ; interdits jamais envoyés", "4"],
            ["29", "Danses et chorégraphies", "liste, danse 604 avec la zone libre, `exemple_kpop` dans les limites, ARRÊT", "4"],
            ["30", "Équipe", "fichiers valides, écrans ; « je cherche la salle b204 » → le robot y va", "4"],
            ["31", "Coque", "accueil et espace de travail ; 186 mesures sans défilement ni élément coupé ; thème", "5"],
            ["32", "Carte 3D", "accueil et salle posés en 3D, mêmes coordonnées en 2D ; vues, zoom ; sans WebGL", "5"],
            ["33", "Scan corrigé", "sans reconnaissance ; « damier » simulé corrigé ; monde maillé à 0,9 fois le temps réel", "5"],
            ["34", "Pont : vitesse minimale et mode", "0,1 m/s demandé → 0,2 envoyé ; assis → `pas_en_marche` ; 7001 à 1 Hz", "5"],
            ["35", "Caméra", "fausse source → `camera_usb` → flux MJPEG → YOLO → cadres dans Firefox", "5"],
            ["36", "ARRÊT global", "guide, téléopération et pilotage arrêtés en moins d'1 s ; verrou ; touche Échap", "5"],
        ],
    }),
]
