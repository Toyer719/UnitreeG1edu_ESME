"""Chapitre 10 : comment le logiciel a été construit."""

BLOCS = [
    ("h1", "Comment le logiciel a été construit"),
    ("chapeau", "Le logiciel n'a pas été écrit ligne par ligne par une seule personne : Claude, une IA, l'a "
                "construit avec une équipe d'autres instances de Claude (les « agents »), en six vagues, du "
                "25/10 au 10/11/2026. Ce chapitre explique la méthode, la chronologie, la revue et la recette des "
                "vagues 5 et 6, la correction de sécurité du 01/11 au soir, les décisions et les problèmes "
                "rencontrés."),

    ("h2", "La méthode : un plan, des contrats, des agents, une recette"),
    ("schema", "methode", "Le déroulé d'une vague", 10.5, 13.0),
    ("puces", [
        "**Le plan** (`docs/plan-atelier-multi-agents.md`, sections 1 à 13) est la référence commune : le but, "
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
        "journal (`docs/journal-atelier.md`) et le README. Les agents qui travaillent en parallèle ne font aucun "
        "commit ; depuis la vague 6, toute la vague est enchaînée par un seul script (contrats, modules, "
        "assemblage, revues, corrections, recette, documents), et chacune de ces étapes commite son travail.",
        "**La revue** (depuis la vague 5) : après l'assemblage, deux relecteurs (d'autres instances de Claude) "
        "relisent, l'un l'interface, dans Firefox, l'autre le code ; un correcteur reproduit chaque défaut, le "
        "corrige et ajoute un test qui l'aurait vu.",
        "**La recette** : des critères mesurables, tous joués sans robot ni écran (« le robot arrive à moins de "
        "0,3 m en moins de 180 s », « zéro contact causé par le robot »). `tests_e2e/tout.sh` les lance tous et "
        "affiche « N / 42 ». Avant, toutes les suites de tests tournent, et chaque défaut de la revue est vérifié. "
        "Une vague n'est finie que quand tout passe.",
        "**Les précisions de l'assemblage** : les écarts acceptés à l'assemblage sont écrits dans le plan "
        "(sections 10.12, 11.12, 12.13, 13.13), ainsi que les corrections après la revue (12.14, 13.14) ; ils "
        "font foi comme les contrats.",
    ]),

    ("h2", "La chronologie"),
    ("schema", "vagues", "Du PC installé à la vague 6", 14.0, 13.0),
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
            ["5", "31/10, nuit → 01/11, 19 h 50", "Interface à la SolidWorks, carte 3D, scan corrigé sans "
             "reconnaissance, vitesse minimale et mode du pont, caméra de poitrine ; phase « comprendre » "
             "(5 lecteurs), 5 agents, assemblage ; revue (30 défauts : 28 corrigés, 2 écartés), puis recette "
             "le 01/11", "36 / 36 en un passage", "5bb9e95 → 31c4350 (21 commits)"],
            ["Verrou", "01/11, 21 h → 02/11, 1 h", "Correction de sécurité : un « Débloquer » relançait l'ancien "
             "trajet du guide (vu en relisant la séance n° 2). Un correcteur ; puis deux relecteurs (en répétition et "
             "dans le code) et un finisseur, qui a vérifié et corrigé chacune de leurs trouvailles (chapitre 9)",
             "12 critères : 11 / 12, puis le 29 rejoué : réussi", "2385386, 9650d0c, c554ea2 et les documents"],
            ["6", "08/11, 23 h → 10/11, 4 h 20", "« Vérifier le robot », boîte noire et rapport de séance, borne "
             "visiteur, démo d'accueil, voix du robot ; contrats, 4 agents en parallèle, assemblage ; deux revues "
             "(28 défauts, tous corrigés), puis recette ; deux coupures (limite d'utilisation, puis le PC éteint "
             "faute de batterie), chaque fois reprises", "41 / 42 au passage complet, puis le 27 (son outil) : 42 / 42",
             "bdf9346 → 1f73bdf (35 commits)"],
        ],
    }),
    ("p", "Le nombre de tests de `atelier/tests` montre la croissance : 408 à la vague 1, 609 à la vague 2, 694 "
          "à la vague 3, 1 131 à la vague 4, 1 265 avec les contrats de la vague 5, 1 466 réussis à la recette "
          "du 01/11 (plus 3 sautés, et les 4 du repérage ROS, lancés à part), 1 957 à la recette de la vague 6, "
          "le 10/11, et [[tests_atelier]] au moment de la génération de ce document."),

    ("h2", "La revue et la recette de la vague 5"),
    ("p", "Le 31/10 au soir, après l'assemblage, deux relecteurs ont relu la vague 5 : l'un dans Firefox, avec la "
          "3D (22 défauts d'interface, dont 3 graves), l'autre dans le code (8 défauts, dont 1 grave). Le "
          "correcteur (l'intégrateur) a reproduit chaque défaut avant de le corriger : aucun n'était faux. Ses "
          "corrections sont dans 7 commits (d6d3b26 → 8e1c1d1), et ses choix dans la section 12.14 du plan."),
    ("table", {
        "legende": "Les quatre défauts graves de la revue, et leur correction",
        "entetes": ["Défaut", "Correction"],
        "largeurs": [7.6, 9.0],
        "taille": 8.5,
        "lignes": [
            ["**L'arbre du lieu**, une fois replié, ne se rouvrait plus (au-dessus de 1 100 pixels de large), et "
             "c'était mémorisé", "une languette « ▸ Le lieu » au bord gauche de la vue, et une entrée du menu des "
             "réglages"],
            ["**Le premier clic sur ✓ Enregistrer** était perdu quand un champ avait le curseur : le champ quitté "
             "redessinait le panneau entre l'appui et le relâchement", "les mêmes boutons d'un dessin à l'autre, "
             "✓ actif dès la frappe, les champs validés après le clic ; le panneau redessiné garde le défilement et "
             "la saisie ; Ctrl+S marche pendant une saisie"],
            ["**Le Plan 2D restait vide** quand Placer s'était ouvert en 3D : le cadrage était calculé sur une vue "
             "de taille nulle", "le cadrage attend que la vue ait une taille ; « Recadrer » et la touche F en Plan 2D"],
            ["**L'ARRÊT se taisait** si sa première demande au serveur ne revenait pas", "chaque appui envoie sa "
             "demande ; sans réponse en 1,5 s : « arrêtez le robot avec la télécommande »"],
        ],
    }),
    ("p", "Les 26 autres (15 moyens, 11 mineurs) touchaient surtout l'interface : Échap envoyait l'ARRÊT, et le "
          "verrou du robot, pour fermer un simple menu ; du jargon ROS à l'écran ; des panneaux qui doublaient le "
          "ruban ; « Y aller » actif quand rien ne tournait ; une répétition annoncée lancée alors que des parties "
          "avaient planté ; un sol du nuage trop vert. Côté robot : avec la vitesse minimale, une zone morte à 0 "
          "faisait d'un bruit de calcul une marche à 0,2 m/s ; `camera_usb` tuait le `v4l2-ctl` qu'il venait de "
          "relancer ; un scan court donnait un sol penché de 6,8°."),
    ("p", "**28 défauts sont corrigés, chacun avec un test. 2 sont écartés, avec leur raison écrite** (section "
          "12.14) : les zones « ralentir » du Collision Monitor de Nav2, que la vitesse minimale du pont rend sans "
          "effet sous 0,4 m/s (des zones « stop » arrêteraient le robot devant les murs des couloirs étroits et "
          "des portes ; le lancement de la navigation le signale ; la conduite près des personnes est à mesurer à "
          "la séance n° 2), et la salle « 3 » du lieu `seance`, à 0,28 m d'un objet bas : c'est le lieu de "
          "l'utilisateur, il n'a pas été modifié, mais « Vérifier le lieu » la signale maintenant (un triangle d'alerte dans l'arbre)."),
    ("p", "**La recette** a eu lieu le 01/11. Elle a d'abord relu les 30 défauts, un à un, dans le code et dans "
          "les commits ; puis elle a corrigé ce qui restait, chaque fois avec un test : des messages du pilotage "
          "parlaient encore de « nœud » et de « StopMove » à l'écran ; deux corrections de la revue n'avaient pas "
          "de test (la bulle d'aide et la couleur du sol de la carte 3D, les compteurs de l'écran de scan) ; un "
          "scan déjà utilisé disait encore « puis Utiliser cette carte » ; le chemin du guide s'affichait en "
          "identifiants (`hall_nord`, `couloir_nord_1`) au lieu des noms ; le README plaçait l'image de la caméra "
          "de poitrine dans Piloter (commits 6f71145 → 31c4350)."),
    ("p", "Puis tout a été relancé sur le code final : la compilation (8 paquets en 3 s), les images du Jetson, "
          "refaites parce que le code avait changé depuis leur construction (amd64 en 26 s, arm64 en 45 s), "
          "toutes les suites de tests (**2 281 tests réussis, 13 sautés, 0 échec**, en 20 min environ ; détail au "
          "chapitre 12), et les 36 critères en un seul passage, sans en rejouer aucun : **36 / 36**, en 2 h 08 "
          "(7 662 s, de 17 h 25 à 19 h 33). Les captures du chapitre 11 ont été prises à la fin. Rien de la "
          "vague 5 n'a encore tourné sur le vrai G1 : c'est le but de la séance n° 2."),

    ("h2", "La correction du verrou (01/11 au soir)"),
    ("p", "En relisant les documents de la séance n° 2, on a vu qu'à l'étape F3 (« Bloquer », puis « Débloquer ») "
          "le robot repartait seul vers l'ancien but : le verrou ne valait que pour le pont, et Nav2 gardait le "
          "but du guide. Un correcteur a d'abord reproduit le défaut en répétition (3,5 m parcourus en 15 s, sans "
          "aucune demande), puis l'a corrigé : le guide écoute lui-même le verrou et l'état du pont, annule son "
          "trajet, et le robot attend un nouveau « Y aller » (section 12.15 du plan, chapitre 9)."),
    ("p", "Comme après la vague 5, deux relecteurs ont ensuite cherché ce qui restait : l'un en répétition, en "
          "mesurant chaque mouvement sur la vérité du faux G1, l'autre dans le code, avec une horloge simulée. Ils "
          "ont trouvé 8 défauts ; le finisseur les a vérifiés un à un : 6 failles réelles (le pont tué puis "
          "relancé, un état du pont trop vieux lu comme « rien n'empêche », une réponse perdue au repos qui annulait "
          "le retour automatique, le joystick tenu après une assise ou un blocage, la chorégraphie qui continuait, "
          "la touche Échap pendant l'attente du retour) et 2 vérifications qui ne prouvaient rien. Toutes sont "
          "corrigées, chacune avec un test qui échoue sur le code d'avant ; la seule suggestion écartée (que le pont "
          "ignore, à son lancement, un flux de vitesses déjà en cours) l'est avec sa raison : le pont ne peut pas "
          "distinguer un flux d'avant son lancement d'un flux qui commence juste après."),
    ("p", "Tout a été relancé sur le code corrigé : **1 473 tests** de `atelier/tests` réussis (plus les 4 du "
          "repérage ROS), 288 de la navigation, 116 du pilotage, 180 du pont et 70 du conteneur, **0 échec** ; les "
          "scénarios des relecteurs et ceux du correcteur, rejoués en répétition : **0,00 m** parcouru après chaque "
          "levée, sans aucun ordre de marche ; les critères qui touchent au pont, au guide, au pilotage et à "
          "l'ARRÊT (16 à 20, 22, 27 à 29 et 34 à 36) : **11 sur 12** au premier passage, puis le 29 au second "
          "(l'aperçu d'une chorégraphie dans la page n'avait pas avancé : un hasard de minutage, son test a "
          "réussi trois fois de suite ensuite) ; les images du Jetson ont été refaites. Rien de tout cela n'a "
          "encore tourné sur le vrai G1 : à vérifier à la séance n° 2 (étapes F3 et P3)."),

    ("h2", "La vague 6 : revues, corrections et recette (09-10/11)"),
    ("p", "La vague 6 a suivi la même méthode, enchaînée cette fois par un seul script : les contrats (section 13 "
          "du plan, 13 schémas nouveaux, 119 tests de contrat) le 09/11 à minuit, quatre agents en parallèle "
          "(Diagnostic, Boîte noire, Borne et orchestrateur, Voix) jusqu'à 2 h, puis l'assemblage (la touche Échap "
          "et la fenêtre du diagnostic, la barre d'outils à toutes les largeurs, les réglages de la voix dans l'écran "
          "Démo, des tests isolés qui n'écrivent plus de séance dans le dossier de l'utilisateur ni n'approchent le "
          "réseau du robot)."),
    ("p", "**Deux revues**, le 09/11 : l'interface dans Firefox, la démo jouée en simulation (18 défauts, dont 1 "
          "grave), et le code avec la sécurité (10 défauts, dont 2 moyens). Le grave : le diagnostic prenait "
          "l'enregistreur de la boîte noire pour le robot (« le PC voit le faux G1, mais pas tout » alors que rien "
          "ne tournait). Les moyens : une page d'un autre site pouvait agir sur l'Atelier (chapitre 9), et une "
          "démo relancée restait muette sur une borne déjà ouverte. Le reste : « Ouvrir » sous le bas de l'écran "
          "en Réel, des réglages coupés, « Ramener à l'accueil » qui disait « Suivez-moi », une séance qui "
          "continuait en Simulation, un arrêt normal compté comme une erreur dans le rapport, des phrases avec le "
          "nom d'une salle qui se disaient mal… Le correcteur a reproduit chaque défaut avant de le corriger : "
          "**aucun n'était faux, les 28 sont corrigés**, chacun avec un test, quatre d'une autre façon que "
          "proposé, avec la raison écrite (section 13.14 du plan) ; par exemple, plutôt qu'un article devant le "
          "nom des salles, des tournures qui se disent bien avec tous les noms (« Direction Infirmerie : "
          "suivez-moi ! »)."),
    ("p", "**La recette**, le 10/11 : les scripts des relecteurs rejoués sur le code final ; la compilation "
          "(9 paquets en 3 s) ; les images du Jetson, refaites (le guide et `atelier/lieu` avaient changé) ; "
          "toutes les suites (**2 885 tests réussis, 14 sautés, 0 échec**, chapitre 13) ; puis les 42 critères en "
          "un passage de 2 h 19 : **41 / 42**. Le seul échec, le critère 27, ne venait pas du robot : son outil "
          "attendait encore l'annonce « départ » pour un trajet seul vers l'accueil, devenue « Je retourne à "
          "l'accueil » après la revue ; l'outil corrigé, le critère a réussi deux fois, sans que le produit change : "
          "**42 / 42**. Les captures du chapitre 12 ont été prises pendant la recette. Rien de la vague 6 n'a "
          "encore tourné sur le vrai G1."),

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
            ["Un diagnostic qui ne fait qu'observer, avec trois actions confirmées (vague 6)", "Gagner du temps au début "
             "de chaque séance sans jamais risquer un mouvement ; la séance n° 1 avait perdu du temps sur des services "
             "arrêtés et un câble à rebrancher."],
            ["Une boîte noire légère, sans nuages ni images (vague 6)", "Comprendre une séance après coup (les journaux "
             "du conteneur partaient avec lui) sans ralentir le PC : 2 % d'un cœur, 150 Mo par heure."],
            ["Une démo qui se met en pause et attend une demande (vague 6)", "La règle « rien ne repart seul » de la "
             "vague 5, étendue à la démo : une visite interrompue ne reprend jamais d'elle-même."],
            ["La voix fabriquée sur le PC, par Piper (vague 6)", "Une voix française naturelle sans Internet ; la synthèse "
             "du robot ne parle sans doute pas français ; le son part en morceaux, comme dans les exemples d'Unitree."],
            ["Une borne qui ne peut rien faire d'autre (vague 6)", "Une tablette posée dans un hall est à tout le monde : "
             "depuis le réseau, seules les pages de la borne répondent."],
        ],
    }),
    ("p", "Pour les vagues 5 et 6, l'utilisateur avait délégué toutes les décisions : elles sont écrites, "
          "avec leurs raisons, dans `~/robot-g1-donnees/vague5/DECISIONS.md` (interface I1 à I10, scan S1 à S7, "
          "robot R1 à R4) et `~/robot-g1-donnees/vague6/DECISIONS.md` (diagnostic D, boîte noire B, borne K, "
          "orchestrateur O, voix V)."),

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
            ["Agents coupés par la limite d'utilisation (26/10 vers 9 h ; 31/10 à 19 h ; vérification arrêtée le 31/10 à "
             "22 h 40)", "Les longues sessions de travail "
             "dépassent la limite de la session", "Sauvegarde intermédiaire (commit b9d1639), reprise automatique "
             "planifiée, agents finis repris depuis leur résultat ; recette reprise le 01/11"],
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
             "coque : page fixe, colonnes qui défilent seules ; 165 mesures au critère 31"],
            ["Nav2 et la répétition plantent avec `ROS_LOCALHOST_ONLY=1` (vague 5)", "Nav2 lance trop de participants "
             "DDS pour la seule interface locale (« Failed to find a free participant index »)", "Les critères tournent "
             "avec `ROS_LOCALHOST_ONLY=0` (exception écrite en 12.11) ; l'Atelier signale une partie plantée et "
             "propose « Relancer »"],
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
            ["Un « Débloquer » relançait l'ancien trajet (01/11)", "Le verrou ne valait que pour le pont : Nav2 gardait "
             "le but du guide ; le pilotage ignorait le verrou", "Le guide et le pilotage écoutent le verrou et l'état "
             "du pont ; rien ne repart sans nouvelle demande (12.15) ; puis 6 failles de plus, trouvées par la "
             "relecture, corrigées"],
            ["Les tests écrivaient des séances dans le dossier de l'utilisateur (vague 6)", "Chaque test qui ouvrait "
             "l'espace en Réel ouvrait une vraie séance : 21 séances d'essai en une nuit", "Séances et sons des tests "
             "dans un dossier à part ; un faux contexte vide pour le diagnostic (jamais de ping ni de ssh)"],
            ["Le diagnostic voyait un robot qui n'était pas là (vague 6)", "L'enregistreur de la boîte noire écoute les "
             "sujets du robot, et comptait comme lui", "Les nœuds de l'Atelier qui observent ne comptent plus"],
            ["Vague 6 coupée deux fois (09/11)", "La limite d'utilisation, puis le PC éteint, batterie presque vide",
             "Le script de la vague reprend chaque étape depuis son travail ; sauvegarde toutes les 20 minutes"],
        ],
    }),

    ("h2", "Ce que la méthode apporte, et ses limites"),
    ("puces", [
        "**Ce qu'elle apporte** : beaucoup de travail en peu de temps (quatre ou cinq agents en parallèle), sans conflit "
        "grâce aux contrats ; tout est testé et retesté à chaque vague ; tout est essayé sans robot avant chaque "
        "séance ; le journal et le plan gardent la trace de chaque décision.",
        "**Ses limites** : rien n'est sûr tant que le vrai robot ne l'a pas confirmé (plusieurs formats d'Unitree "
        "viennent d'une documentation non officielle) ; les tests ne voient pas tout (la revue de la vague 5 a "
        "trouvé 30 défauts qu'ils n'avaient pas vus, et un défaut de sécurité n'a été vu qu'en relisant le "
        "déroulé de la séance n° 2) ; les sessions longues sont coupées par la limite d'utilisation ; ce que l'IA garde dans un dossier temporaire peut se perdre ; et "
        "l'utilisateur doit "
        "relire, essayer et dire ce qui ne lui convient pas : c'est ainsi que sont nées la vague 4 (le point "
        "principal), la vague 5 (l'interface, le scan), la vague 6 (une séance efficace, la démo) et ce document.",
    ]),
]
