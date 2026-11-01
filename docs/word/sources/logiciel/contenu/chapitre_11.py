"""Chapitre 11 : la nouvelle interface (vague 5).

Les captures viennent de ~/robot-g1-donnees/vague5/captures/ (ou du dossier donné par --captures) :
chaque bloc « capture » donne des motifs de noms de fichiers, essayés dans l'ordre ; la première image
trouvée est insérée, sinon le bloc est simplement omis (le texte se suffit à lui-même). Les premiers
motifs sont les noms des captures finales de la recette du 01/11 (01_accueil.png à 09_theme_clair.png,
1600 × 900) ; les suivants, ceux de tests_e2e/outils_coque_e2e.py et des captures de l'assemblage.
"""

BLOCS = [
    ("h1", "La nouvelle interface (vague 5)"),
    ("chapeau", "Le 31/10, l'interface a été entièrement réorganisée, à la demande de l'utilisateur : "
                "« que ça fasse à la SolidWorks », simple et ludique, inspirée de l'appli Unitree Explore, et "
                "où tout défile correctement. Ce chapitre la décrit telle qu'on la voit à la fin de la vague 5, "
                "après la revue et la recette du 01/11."),
    ("si_captures", [
        ("p", "Les images de ce chapitre ont été prises le 01/11, à la fin de la recette, dans Firefox piloté sans "
              "fenêtre (avec WebGL, la 3D du navigateur), dans une fenêtre de 1 600 × 900 pixels, sur des copies des "
              "lieux « Lycée démo » (`demo`, le lieu dessiné des tests) et « Séance robot » (`seance`, le scan réel "
              "du 27/10). Thème sombre, sauf la dernière."),
    ]),

    ("h2", "Pourquoi une nouvelle interface"),
    ("p", "L'interface des vagues 1 à 4 avait grandi onglet par onglet : douze onglets, et des défauts que "
          "l'utilisateur résumait par « des trucs sont parfois pas scrollables ». L'étude de la vague 5 a "
          "mesuré : dans l'onglet Simulation, trois panneaux écrasés à 24 pixels de haut, chacun avec sa barre "
          "de défilement, si bien qu'aucun des six boutons « Y aller » n'était visible et qu'on ne voyait que "
          "12 pixels du bouton ARRÊT ; la molette zoomait les cartes au lieu de faire défiler la page ; l'onglet "
          "Pilotage avait 36 boutons, dont 22 sous le bas de l'écran ; la revue du vrai scan affichait 120 cases "
          "pour 92 objets ; le plan 2D était créé à 9 endroits, et il y avait trois boutons d'arrêt."),
    ("p", "La nouvelle interface reprend la **structure de SolidWorks** (on choisit d'abord le type de travail, "
          "puis un ruban de commandes, l'arbre des éléments à gauche, les propriétés à droite avec OK et "
          "Annuler) et **l'habillage d'Unitree Explore** (thème sombre, accent bleu pervenche, gros bouton "
          "d'arrêt rouge, nuage de points coloré par la hauteur)."),

    ("h2", "L'accueil : Simulation ou Robot réel"),
    ("p", "`g1-atelier` ouvre un **accueil**, comme la fenêtre « Nouveau document » de SolidWorks : « Avec quoi "
          "travaillez-vous aujourd'hui ? », puis deux grandes cartes, **Simulation** (« Dessiner un lieu et "
          "essayer le guide sur l'ordinateur, sans robot. ») et **Robot réel** (« Scanner le bâtiment, placer "
          "les salles et guider le vrai G1. »). Dessous, à gauche, la liste des lieux, avec leur étage et une "
          "étiquette « scanné » pour ceux qui ont une carte du vrai robot (le dernier lieu ouvert est "
          "présélectionné), et « Nouveau lieu » ; en bas, le bouton **Ouvrir**, et un lien discret, « Piloter le "
          "robot sans lieu », qui ouvre Piloter directement. En haut à droite, l'état du serveur (« Serveur "
          "prêt · ROS 2 ») et le bouton du thème."),
    ("p", "Le cadre de droite change avec la carte choisie. En Simulation, il rappelle les trois étapes : "
          "dessiner les murs et les meubles (la carte se fait seule), placer l'accueil et les salles, lancer "
          "la simulation puis « Y aller ». En Robot réel, il devient « Avant de commencer » : la case "
          "**Répétition sans robot (faux G1)** et les vérifications, relues toutes les 4 s : Atelier lancé avec "
          "`robot.sh`, câble du robot branché, PC1 et Jetson qui répondent, télécommande en main (à cocher). "
          "Si quelque chose tourne encore (un robot qui marche, une simulation), l'accueil montre aussi le "
          "bouton ARRÊT."),
    ("capture", ["01_accueil*.png", "accueil_reel_sombre*.png", "accueil_reel*.png", "accueil_simulation_sombre*.png",
                 "accueil*.png"],
     "L'accueil : Simulation est choisie ; dessous, les deux lieux et les trois étapes de la simulation", 14.5, 9.0),

    ("h2", "L'espace de travail"),
    ("p", "Après « Ouvrir », l'espace de travail occupe toute la fenêtre. **La page ne défile jamais** : ce sont "
          "l'arbre, le panneau et les listes qui défilent, chacun pour soi."),
    ("schema", "interface_coque", "Le plan de l'espace de travail", 16.0, 8.5),
    ("puces", [
        "**La barre d'outils** : ⌂ (retour à l'accueil), le lieu et l'étage, le mode (SIMULATION, RÉEL ou "
        "RÉPÉTITION ; un clic ramène à l'accueil pour en changer), Annuler et Rétablir, Enregistrer, les "
        "pastilles d'état, le bouton du thème, le menu des réglages (la roue dentée) et le gros bouton "
        "**ARRÊT**. Les pastilles : « ROS 2 » toujours ; en Réel, celle du robot, qui dit l'état du pont en un "
        "ou deux mots (« Robot prêt », « À repérer », « Pas en marche », « Robot bloqué »…) ; « Serveur "
        "injoignable » seulement quand le serveur ne répond plus.",
        "**Le ruban** : les onglets du mode, avec de grosses icônes et un libellé court sous chacune ; ce qui "
        "est rare est rangé dans le menu **Avancé** (la roue dentée, à droite du ruban). Une phrase d'aide "
        "apparaît au survol. Une flèche, à droite des onglets, replie le ruban.",
        "**L'arbre du lieu**, à gauche : Lieu ▸ Étage ▸ Carte (sa source et sa date), Monde (en Simulation), "
        "Points (★ Accueil d'abord, puis les salles, avec le même numéro que leur épingle dans la vue), "
        "Itinéraires, Zones, Scans (en Réel), Équipe, chacun avec son décompte (« 18 murs · 12 objets », "
        "« 6 points », « 13 nœuds »). Un clic choisit l'élément dans la vue et montre ses propriétés ; un "
        "double-clic centre la vue dessus ; un petit triangle d'alerte marque ce que « Vérifier le lieu » "
        "signale. Replié, l'arbre se rouvre par la languette « ▸ Le lieu », au bord gauche de la vue.",
        "**La vue centrale** : **3D**, **Plan 2D** (Leaflet, pour dessiner le monde, les itinéraires et les "
        "zones) ou **Caméra** (en Réel), avec les vues Dessus, Iso, Face, Recadrer (aussi la touche F) et le "
        "menu des calques, dans une barre flottante en haut de la vue.",
        "**Le panneau**, à droite : le formulaire de la commande en cours ou les propriétés de l'élément "
        "choisi, avec ✓ Enregistrer et ✗ Annuler en haut (actifs dès qu'on modifie un champ ; Ctrl+S "
        "enregistre aussi pendant une saisie).",
        "**La barre d'état**, en bas : la consigne de l'outil, le dernier message (un clic ouvre le journal "
        "des messages), les coordonnées x, y sous le pointeur, et « Ce qui tourne » (avec leur nombre) dès "
        "que l'Atelier a lancé quelque chose.",
    ]),
    ("table", {
        "entetes": ["Mode", "Onglets du ruban"],
        "largeurs": [2.6, 14.0],
        "taille": 9,
        "premiere_col_gras": True,
        "lignes": [
            ["Simulation", "**Dessiner** (Choisir, Mur, Passage, Objet, Piéton, Départ ; la carte se refait seule "
             "à l'enregistrement), **Placer** (Salle, Accueil, Nœud, Relier, Zone interdite, Zone lente), "
             "**Simuler** (Lancer, Arrêter, Y aller, et les cases Accompagner et Retour ; Avancé : Faux visiteur, "
             "Passants, Réglages du guide, Scan simulé), **Équipe** (Personnalités, Dialogues, Caméra)"],
            ["Robot réel et répétition", "**Scanner** (Scan, Fin, Utiliser cette carte), **Placer** (les mêmes "
             "commandes, sur le nuage du scan, en 3D), **Naviguer** (Lancer, Repérer, Y aller, Bloquer, "
             "Débloquer, Arrêter ; Avancé : Situer le robot), **Piloter** (Prendre la main, ou « Démarrer » en "
             "répétition tant que le pilotage ne tourne pas ; Postures, Gestes, Voix, Lumière, Joysticks ; "
             "Spectacle : Danses, Chorégraphies), **Équipe**"],
        ],
    }),
    ("capture", ["02_simulation_placer*.png", "simulation_sombre_dessiner*.png", "simulation_*dessiner*.png",
                 "simulation_sombre_placer*.png"],
     "Simulation › Placer, sur le lycée de démonstration : l'arbre du lieu, le monde en 3D, la salle B204 "
     "choisie et ses propriétés à droite", 16.0, 9.5),
    ("p", "Sur un écran étroit (moins de 1 100 pixels, une tablette), l'arbre et le panneau deviennent des "
          "tiroirs, ouverts par des boutons de la barre d'outils, et les cibles tactiles font 44 pixels."),

    ("h2", "Simuler : le guide sur l'ordinateur"),
    ("p", "**Simulation › Simuler** fait vivre le lieu dessiné. **Lancer** démarre Gazebo, la navigation et le "
          "guide sur ce lieu ; tant que rien ne tourne, « Y aller » reste grisé. Le panneau donne l'état "
          "(« Simulation en cours : « demo », rdc, guide lancé »), la mission en cours, avec la distance qui "
          "reste et le chemin écrit avec les noms des salles et des nœuds (« Accueil → Hall nord → "
          "Amphithéâtre → Couloir nord 1 → Salle B204 »), puis un bouton « Y aller » par salle. Les cases "
          "**Accompagner** et **Retour** du ruban règlent le guide (vérifier que le visiteur suit, revenir seul "
          "à l'accueil). Si une partie lancée par l'Atelier s'arrête d'elle-même, le panneau le dit (« … n'a pas "
          "démarré correctement ») et propose « Relancer »."),
    ("capture", ["03_simulation_simuler*.png", "simulation_sombre_simuler*.png", "*simuler*.png"],
     "Simulation › Simuler : le guide emmène le robot simulé vers la salle B204 ; le chemin s'écrit avec les "
     "noms des salles", 16.0, 9.5),

    ("h2", "La carte 3D et le placement des points"),
    ("p", "En Réel, la vue 3D montre le **nuage de points du scan**, coloré selon la hauteur au-dessus du sol : "
          "le sol (moins de 12 cm) en gris bleuté, puis du vert au jaune (vers 1,1 m) et au rose (2,2 m). Une "
          "légende, en bas à droite, rappelle ces couleurs et règle la taille des points ; le plafond est caché "
          "(case « Afficher le plafond » du menu des calques). Par-dessus : l'accueil en **étoile ambre** avec sa "
          "flèche, les salles en **épingles numérotées** avec leur étiquette, les itinéraires en cyan au sol, les "
          "zones translucides (rouges interdites, orange lentes), le robot et les piétons en direct. En "
          "Simulation, c'est le monde dessiné, en volumes, sur la carte 2D posée au sol."),
    ("p", "**Les gestes** : glisser avec le bouton gauche fait tourner ; le bouton droit (ou Maj et le gauche) "
          "déplace ; la molette zoome vers le pointeur ; le bouton du milieu tourne aussi, comme dans "
          "SolidWorks ; sur une tablette, un doigt tourne, deux doigts déplacent et zooment ; la touche F "
          "recadre tout."),
    ("num", [
        "Choisir **Placer › Accueil** (ou **Placer › Salle**) : un aperçu du repère suit le pointeur, avec une "
        "bulle de consigne (« Cliquez sur le sol devant la porte, puis tirez vers la salle »).",
        "Cliquer sur le sol : le point est posé (accroché tous les 5 cm).",
        "Glisser depuis le point pour régler son orientation (par pas de 15°, ou librement avec Maj). Après un "
        "simple clic, la barre d'état dit comment tourner le point : glisser la poignée blanche au bout de sa "
        "flèche. Glisser le point lui-même le déplace.",
        "Corriger au besoin x, y et l'angle (en degrés) dans le panneau, puis **✓ Enregistrer**.",
    ]),
    ("p", "Les points sont écrits dans les mêmes fichiers et dans le même repère que depuis le Plan 2D "
          "(`salles.yaml`, et le nœud de même identifiant dans `itineraires.yaml`) : une salle placée en 3D "
          "apparaît au même endroit en 2D. Annuler et Rétablir marchent comme ailleurs. Les nœuds des "
          "itinéraires, eux, se placent en Plan 2D. Sans WebGL (la 3D du navigateur), la vue affiche un message "
          "et l'Atelier passe au Plan 2D."),
    ("capture", ["05_reel_placer*.png", "*carte3d_iso_sombre*1366*.png", "*carte3d_iso_sombre*.png",
                 "*carte3d_iso*.png", "*carte3d*.png", "reel_sombre_placer*.png", "*placer*.png"],
     "Réel › Placer sur le nuage du scan du 27/10 (299 558 points) : l'accueil et les salles ; la salle « 3 », "
     "choisie, porte un triangle d'alerte dans l'arbre (trop près d'un objet bas)", 16.0, 9.5),

    ("h2", "Le scan"),
    ("p", "**Réel › Scanner › Scan** passe en plein écran sombre pendant le scan et son traitement, comme "
          "l'écran « 3D LiDAR Mapping » d'Unitree Explore : le nuage se remplit en direct, coloré par la "
          "hauteur, avec le trajet du robot, quatre compteurs (durée, distance, points mesurés, nuages) et deux "
          "gros boutons, **Scan** puis **Fin**. Après Fin, une barre suit le traitement (carte 3D, carte 2D, "
          "nuage). Le scan fini, l'espace de travail revient : la vue garde le nuage (vues Dessus, Iso, Suivre, "
          "case Plafond, taille des points), et le panneau donne le résultat : nuages assemblés, points gardés "
          "dans la carte 3D (un par case de 5 cm), points de passants retirés, sol trouvé et son inclinaison, "
          "taille de la carte 2D, puis la carte 2D elle-même. **Utiliser cette carte** en fait la carte de "
          "l'étage ; un scan déjà utilisé le dit (« Ce scan est déjà la carte de l'étage… ») et propose « Nouveau "
          "scan ». Il n'y a plus de revue des tables et des chaises. En Simulation, le scan simulé est dans "
          "Simuler › Avancé › Scan simulé, avec l'exploration automatique ou les flèches."),
    ("capture", ["04_reel_scanner*.png", "*pendant_le_scan*1366*.png", "*pendant_le_scan*.png",
                 "*scan*en_cours*.png", "reel_sombre_scanner*.png", "*scanner*.png"],
     "Réel › Scanner : le scan du 27/10, retraité par la nouvelle chaîne (2 327 nuages, 2 731 817 points "
     "mesurés, sol penché de 0,58°) et déjà utilisé comme carte de l'étage", 16.0, 9.5),

    ("h2", "Naviguer, Piloter et la caméra"),
    ("puces", [
        "**Naviguer** : Lancer (avec le robot, l'Atelier démarre le conteneur du Jetson), **Repérer** (le robot "
        "posé sur l'étoile, dans le sens de la flèche ; grisé tant que le robot n'est pas prêt à être repéré), "
        "Y aller (grisé tant que rien ne tourne), Bloquer, Débloquer, Arrêter ; dans Avancé, « Situer le "
        "robot » quand il n'est pas sur l'accueil. Le panneau suit la navigation, le repérage (« Non repéré », "
        "« Repéré ») et le pont. L'image de la caméra de poitrine s'incruste en haut à droite de la vue, avec "
        "les cadres des visiteurs.",
        "**Piloter** (en Réel seulement) : prendre ou rendre la main, postures, gestes, voix, lumière (grisés "
        "tant que le pilotage ne répond pas), deux joysticks en surimpression, et le groupe Spectacle (danses "
        "du robot, chorégraphies avec leur ligne de temps et leur aperçu 3D). Au centre, la **Vue du robot** : "
        "la carte avec sa position, le G1 en 3D qui reprend sa posture et ses gestes, la caméra de la tête. "
        "Elle ne commande rien. En répétition, tant que le pilotage ne tourne pas, la première commande du "
        "ruban devient « Démarrer » : elle le démarre, avec le faux G1.",
        "**La caméra de poitrine** se regarde dans la vue Caméra (Réel) ou dans **Équipe › Caméra**, qui "
        "montre l'image en direct (ou l'image analysée), un cadre autour de chaque visiteur détecté, avec son "
        "numéro et sa distance (vert : il regarde le robot ; orange : non), la taille de l'image, le nombre "
        "d'images par seconde et de visiteurs ; ses réglages (place sur le robot, détection) sont dans le "
        "panneau et dans Équipe › Avancé › Réglages de la caméra. Piloter garde la caméra de la tête.",
    ]),
    ("capture", ["06_reel_naviguer*.png", "reel_sombre_naviguer*.png", "reel_naviguer*.png", "*naviguer*.png"],
     "Réel › Naviguer, avant le lancement : le nuage, l'incrustation de la caméra de poitrine (ici une fausse "
     "vidéo, trois visiteurs) et le panneau du repérage", 16.0, 9.5),
    ("capture", ["07_reel_piloter*.png", "reel_sombre_piloter*.png", "*piloter*.png"],
     "Réel › Piloter en répétition : « Démarrer » en tête du ruban, la Vue du robot (carte, G1 en 3D, caméra "
     "de la tête), les joysticks et le panneau des commandes", 16.0, 9.5),
    ("capture", ["08_equipe_camera*.png", "*vue_camera_sombre*1366*.png", "*vue_camera_sombre*.png",
                 "*vue_camera*.png", "*equipe_camera_sombre*1366*.png", "*camera*.png"],
     "Équipe › Caméra : l'image de la caméra de poitrine (ici une fausse vidéo) et les cadres des trois "
     "visiteurs, avec leur distance", 16.0, 9.5),

    ("h2", "L'ARRÊT, les messages et le thème"),
    ("puces", [
        "**ARRÊT** est toujours visible, dans les deux modes et à toutes les tailles de fenêtre. Chaque appui "
        "envoie sa demande ; sans réponse en 1,5 s, l'Atelier dit d'arrêter le robot avec la télécommande. En "
        "Réel et en répétition, il bloque aussi le robot et devient « Débloquer » (qui demande confirmation). "
        "Il n'arrête pas un scan (c'est le rôle de Fin).",
        "La touche **Échap** envoie l'ARRÊT dès que le robot bouge ou peut repartir (guide en mission, pilotage "
        "qui a la main…) ; sinon, elle ferme d'abord un menu ou annule une saisie, et, quand rien ne tourne, "
        "la barre d'état dit qu'il n'y a rien à arrêter.",
        "Les **messages** s'affichent dans la barre d'état, sans fenêtres qui s'ouvrent ; les confirmations "
        "sont des fenêtres dans la page (plus de boîtes du navigateur). Ils parlent la langue du ruban "
        "(« Placer › Accueil », « Réel › Scanner ») : ni sujet ROS, ni nom de programme, ni commande ; le "
        "détail technique est dans l'infobulle ou dans le journal des messages.",
        "« **Ce qui tourne** » (les commandes lancées par l'Atelier) est dans le menu des réglages, et dans la "
        "barre d'état quand quelque chose tourne.",
        "Deux **thèmes**, sombre par défaut et clair (un bouton de la barre d'outils) ; la vue 3D reste "
        "toujours sur fond sombre. Les couleurs viennent de `css/theme.css`, et leurs contrastes sont "
        "vérifiés par les tests.",
        "Les anciennes adresses (`#salles`, `#simulation`, `#pilotage`…) mènent toujours au bon endroit.",
    ]),
    ("capture", ["09_theme_clair*.png", "*clair*.png"],
     "Le thème clair (Réel › Placer, liste des points de l'étage) : la vue 3D reste sombre", 16.0, 9.5),

    ("h2", "Sous le capot"),
    ("p", "La coque tient un **registre des commandes** (`COMMANDES` dans `js/coque/ruban.js`) : chaque commande a "
          "un identifiant stable (par exemple `salles.accueil` ou `navigation.reperer`), ses modes, son onglet, "
          "son libellé, son icône (un dessin SVG écrit dans le code), sa phrase d'aide et l'écran qui l'exécute. "
          "Les tests ne cherchent jamais un bouton par son texte : ils utilisent des repères stables "
          "(`data-role`, `data-commande`), si bien qu'un libellé peut changer sans casser les tests. Le "
          "critère 31 vérifie, à trois tailles de fenêtre (1 366 × 768, 1 600 × 1 000 et 1 920 × 1 080), dans "
          "les trois modes et pour chaque onglet et chaque commande, que la page ne défile pas, que rien n'est "
          "coupé ni recouvert et que l'ARRÊT est visible : 165 mesures et 7 428 éléments cliquables vérifiés à "
          "la recette du 01/11, sans une faute. Le navigateur retient quelques choix (mode, thème, lieu, onglet) "
          "dans son stockage local."),
]
