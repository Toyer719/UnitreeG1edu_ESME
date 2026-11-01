"""Chapitre 1 : le projet et le logiciel en une page."""

BLOCS = [
    ("h1", "Le projet et le logiciel en une page"),
    ("chapeau", "Ce que doit faire le robot, ce que fait le logiciel, quelques chiffres, et où en est le "
                "projet le 01/11/2026, après la recette de la vague 5."),

    ("h2", "Le but du projet"),
    ("p", "Le **Unitree G1 EDU** est un robot humanoïde d'environ 1,3 m. Le projet en fait un **robot "
          "d'accueil** : il attend à l'accueil d'un bâtiment, comprend où le visiteur veut aller, l'y "
          "accompagne en contournant les passants, puis revient seul à l'accueil. Pour cela, il doit "
          "connaître le bâtiment : on le **scanne** avec le LiDAR du robot (un capteur laser qui mesure les "
          "distances tout autour), puis on y **place les salles** et les chemins."),
    ("p", "L'utilisateur, étudiant, s'occupe de la partie **navigation** : scanner, placer les salles, "
          "accompagner, contourner la foule. Le reste (chatbot, voix, détection des visiteurs) revient à "
          "l'équipe ; le logiciel lui a préparé ses emplacements. Le projet dure deux mois, du 21/10 au "
          "18/12/2026."),

    ("h2", "Ce que fait le logiciel"),
    ("p", "Tout tient dans un seul logiciel, l'**Atelier G1**, qui s'utilise dans un navigateur web. Il permet de :"),
    ("puces", [
        "**décrire un lieu** : un bâtiment, ses étages, ses salles, le point d'accueil (le « point "
        "principal »), les itinéraires du guide et les zones interdites ou lentes ;",
        "**inventer un bâtiment sans robot** : dessiner des murs, des portes, des meubles et des piétons, "
        "puis en tirer automatiquement la carte de navigation et un monde 3D pour la simulation ;",
        "**scanner un vrai bâtiment** avec le robot : la carte 2D et le nuage de points 3D se fabriquent seuls ;",
        "**placer les points en 3D**, directement sur le nuage du scan ;",
        "**simuler** le robot dans Gazebo, au milieu de passants, et mesurer ses résultats ;",
        "**guider avec le vrai G1** : repérage au démarrage, trajets calculés par Nav2 et traduits en ordres "
        "de marche, accompagnement du visiteur, retour à l'accueil ;",
        "**piloter** le robot comme l'appli Unitree Explore : postures, gestes, voix, lumière, danses ;",
        "**préparer la place de l'équipe** : personnalités, chatbot à règles, caméra de poitrine et détection "
        "des visiteurs.",
    ]),
    ("p", "Une règle a été tenue depuis le début : **tout ce que fait l'interface se fait aussi en ligne de "
          "commande** (les commandes `g1-…`), et **tout se teste sans robot et sans écran**."),

    ("h2", "Quelques chiffres"),
    ("table", {
        "entetes": ["Ce qu'on compte", "Valeur au moment de la génération"],
        "largeurs": [6.2, 10.4],
        "lignes": [
            ["Code Python (hors tests)", "[[lignes_python_code]] lignes"],
            ["Tests en Python", "[[lignes_python_tests]] lignes"],
            ["Interface web", "[[lignes_js]] lignes de JavaScript et [[lignes_css]] lignes de CSS, sans compilation"],
            ["Paquets ROS 2 écrits pour le projet", "[[paquets_ros]] : g1_sim, g1_nav, g1_bridge, g1_jumeau, g1_pilotage, g1_equipe"],
            ["Commandes `g1-*`", "[[commandes]], chacune avec un alias `gl-*`"],
            ["Routes de l'API web", "[[routes]] (questions et ordres que l'interface envoie au serveur)"],
            ["Tests automatiques", "[[tests_atelier]] tests dans `atelier/tests`, [[tests_docker]] pour le conteneur, "
                                   "[[fonctions_test_ros]] fonctions de test dans les paquets ROS 2"],
            ["Critères de recette", "[[criteres]] scénarios complets, tous joués sans robot ni écran"],
            ["Historique", "[[commits]] commits Git, en 5 vagues de construction, du 25/10 au 01/11"],
        ],
    }),

    ("h2", "Où en est le projet (01/11/2026)"),
    ("p", "L'intégrateur (Claude, qui coordonne la construction) estime l'avancement à **environ 50 %** "
          "(estimation du 31/10, inchangée après la recette du 01/11 : elle a confirmé, sans robot, ce qui était "
          "compté comme fait). "
          "Chaque partie a un **poids** (sa part du travail total) et une **part faite** ; l'avancement est "
          "la somme des poids multipliés par les parts faites :"),
    ("table", {
        "legende": "Avancement estimé par l'intégrateur au 31/10/2026",
        "entetes": ["Partie", "Poids", "Fait", "Pourquoi"],
        "largeurs": [5.6, 1.5, 1.4, 8.1],
        "taille": 9,
        "lignes": [
            ["Logiciel en simulation (lieux, monde, carte, salles, itinéraires, zones, Gazebo + Nav2, foule, "
             "guide, point principal, retour, accompagnement)", "25 %", "95 %",
             "fait et vérifié sans robot (36 / 36 à la recette du 01/11)"],
            ["Interface (accueil Simulation / Réel, espace à la SolidWorks, carte 3D)", "10 %", "85 %",
             "faite le 31/10, revue et corrigée (30 défauts) ; à essayer par l'utilisateur et à ajuster"],
            ["Scan réel → carte", "10 %", "70 %",
             "chaîne corrigée, vrai scan du 27/10 retraité ; à valider par un nouveau scan ; carte d'Unitree à récupérer"],
            ["Liaison avec le vrai robot (pont, conteneur du Jetson, repérage, premier trajet)", "25 %", "25 %",
             "pont essayé le 27/10 (marche à 0,2 m/s) ; Jetson, repérage et trajet pas encore faits"],
            ["Guide réel avec des visiteurs et évitement de la foule réel", "15 %", "10 %",
             "seulement en simulation"],
            ["Caméra, détection des visiteurs et parties de l'équipe (chatbot, voix)", "10 %", "40 %",
             "caméra et détection prêtes sur le PC ; pas encore sur le robot ; parties de l'équipe en attente"],
            ["Démo finale, réglages sur place, documentation finale", "5 %", "30 %",
             "documentation déjà riche ; démo à préparer"],
            ["**Total pondéré**", "**100 %**", "**52,5 %**", "**soit « environ 50 % »**"],
        ],
    }),
    ("p", "Le calcul : 0,25 × 95 + 0,10 × 85 + 0,10 × 70 + 0,25 × 25 + 0,15 × 10 + 0,10 × 40 + 0,05 × 30 "
          "= 52,5 %. Le 01/11, on est au **jour 12 sur 59**, soit 20 % du temps : le logiciel est en avance. "
          "Ce qui reste est surtout **l'essai sur le vrai robot** : conteneur sur le Jetson, repérage, premier "
          "trajet, puis le guide au milieu de vraies personnes."),
    ("encadre", "À retenir",
     ["Le logiciel est presque complet et vérifié en simulation. La suite se joue avec le robot : chaque "
      "séance transforme une hypothèse (« le robot devrait accepter cet ordre ») en fait mesuré.",
      "- Prochaine étape : la séance n° 2 (`docs/tutoriel-seance-2.md`) : seuils de marche, sécurité du pont, "
      "conteneur, repérage, premier trajet de 2,5 m, caméra, nouveau scan."], "retenir"),
]
