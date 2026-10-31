"""Chapitre 11 : la nouvelle interface (vague 5).

Les captures viennent de ~/robot-g1-donnees/vague5/captures/ (ou du dossier donné par --captures) :
chaque bloc « capture » donne des motifs de noms de fichiers, essayés dans l'ordre ; la première image
trouvée est insérée, sinon le bloc est simplement omis (le texte se suffit à lui-même). Les noms suivent
ceux de tests_e2e/outils_coque_e2e.py captures et des captures de l'assemblage (thème sombre d'abord).
"""

BLOCS = [
    ("h1", "La nouvelle interface (vague 5)"),
    ("chapeau", "Le 31/10, l'interface a été entièrement réorganisée, à la demande de l'utilisateur : "
                "« que ça fasse à la SolidWorks », simple et ludique, inspirée de l'appli Unitree Explore, et "
                "où tout défile correctement. Ce chapitre la décrit telle qu'on la voit."),
    ("si_captures", [
        ("p", "Les images de ce chapitre sont des captures prises automatiquement par les tests de l'interface "
              "(Firefox piloté sans fenêtre), en thème sombre."),
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
    ("p", "`g1-atelier` ouvre un **accueil**, comme la fenêtre « Nouveau document » de SolidWorks : deux grandes "
          "cartes, **Simulation** (« Dessiner un lieu et essayer le guide sur l'ordinateur, sans robot ») et "
          "**Robot réel** (« Scanner le bâtiment, placer les salles et guider le vrai G1 »). Dessous, la liste "
          "des lieux (le dernier ouvert est présélectionné), « Nouveau lieu » et le bouton **Ouvrir**. Sous "
          "Robot réel : la case **Répétition sans robot (faux G1)** et les vérifications, relues toutes les "
          "4 s : Atelier lancé avec `robot.sh`, câble du robot branché, PC1 et Jetson qui répondent, "
          "télécommande en main (à cocher). Un lien discret, « Piloter le robot sans lieu », ouvre Piloter "
          "directement."),
    ("capture", ["accueil_reel_sombre*.png", "accueil_reel*.png", "accueil_simulation_sombre*.png", "accueil*.png"],
     "L'accueil : choisir Simulation ou Robot réel, puis le lieu", 14.5, 9.0),

    ("h2", "L'espace de travail"),
    ("p", "Après « Ouvrir », l'espace de travail occupe toute la fenêtre. **La page ne défile jamais** : ce sont "
          "l'arbre, le panneau et les listes qui défilent, chacun pour soi."),
    ("schema", "interface_coque", "Le plan de l'espace de travail", 16.0, 8.5),
    ("puces", [
        "**La barre d'outils** : ⌂ (retour à l'accueil), le lieu et l'étage, le mode (SIMULATION, RÉEL ou "
        "RÉPÉTITION), Annuler et Rétablir, Enregistrer, les pastilles Serveur, ROS 2 et Robot, le bouton du "
        "thème, le menu des réglages (la roue dentée) et le gros bouton **ARRÊT**.",
        "**Le ruban** : les onglets du mode, avec de grosses icônes et un libellé court sous chacune ; ce qui "
        "est rare est rangé dans le menu **Avancé** (la roue dentée) de l'onglet. Une phrase d'aide apparaît au survol.",
        "**L'arbre du lieu**, à gauche : Lieu ▸ Étage ▸ Carte, Monde, Points (★ Accueil d'abord, puis les "
        "salles), Itinéraires, Zones, Scans, Équipe. Un clic choisit l'élément dans la vue et montre ses "
        "propriétés ; un double-clic centre la vue dessus ; un petit triangle d'alerte marque ce que « Vérifier le lieu » signale.",
        "**La vue centrale** : **3D**, **Plan 2D** (Leaflet, pour dessiner le monde, les itinéraires et les "
        "zones) ou **Caméra** (en Réel), avec les vues Dessus, Iso, Face, Recadrer et les calques.",
        "**Le panneau**, à droite : le formulaire de la commande en cours ou les propriétés de l'élément "
        "choisi, avec ✓ Enregistrer et ✗ Annuler.",
        "**La barre d'état** : la consigne de l'outil, le dernier message (un clic ouvre le journal des "
        "messages), les coordonnées x, y sous le pointeur.",
    ]),
    ("table", {
        "entetes": ["Mode", "Onglets du ruban"],
        "largeurs": [2.6, 14.0],
        "taille": 9,
        "premiere_col_gras": True,
        "lignes": [
            ["Simulation", "**Dessiner** (choisir, mur, passage, objet, piéton, départ ; la carte se refait seule à "
             "l'enregistrement), **Placer** (salle, accueil ★, nœud, relier, zones interdites et lentes), **Simuler** "
             "(lancer, arrêter, Y aller, accompagner, retour ; Avancé : faux visiteur, passants, réglages du guide, "
             "scan simulé), **Équipe** (personnalités, dialogues, caméra)"],
            ["Robot réel et répétition", "**Scanner** (Scan, Fin, Utiliser cette carte), **Placer** (sur le nuage du "
             "scan, en 3D), **Naviguer** (lancer, repérer, Y aller, bloquer, débloquer, arrêter), **Piloter** "
             "(prendre la main, postures, gestes, voix, lumière, joysticks ; Spectacle : danses, chorégraphies), "
             "**Équipe**"],
        ],
    }),
    ("capture", ["simulation_sombre_dessiner*.png", "simulation_*dessiner*.png", "simulation_sombre_placer*.png"],
     "L'espace de travail en Simulation, onglet Dessiner", 16.0, 9.5),
    ("p", "Sur un écran étroit (moins de 1 100 pixels, une tablette), l'arbre et le panneau deviennent des "
          "tiroirs, ouverts par des boutons de la barre d'outils, et les cibles tactiles font 44 pixels."),

    ("h2", "La carte 3D et le placement des points"),
    ("p", "La vue 3D montre le **nuage de points du scan**, coloré selon la hauteur au-dessus du sol (vert au "
          "sol, jaune vers 1,1 m, rose vers 2,2 m), le plafond caché (une case l'affiche). Par-dessus : "
          "l'accueil en **étoile ambre** avec sa flèche, les salles en **épingles numérotées** avec leur "
          "étiquette, les itinéraires en cyan au sol, les zones translucides (rouges interdites, orange lentes), "
          "le robot et les piétons en direct. En Simulation, c'est le monde dessiné, en volumes, sur la carte 2D "
          "posée au sol."),
    ("p", "**Les gestes** : glisser avec le bouton gauche fait tourner ; le bouton droit (ou Maj et le gauche) "
          "déplace ; la molette zoome vers le pointeur ; le bouton du milieu tourne aussi, comme dans "
          "SolidWorks ; sur une tablette, un doigt tourne, deux doigts déplacent et zooment ; la touche F "
          "recadre tout."),
    ("num", [
        "Choisir **Placer › Accueil** (ou **Placer › Salle**).",
        "Cliquer sur le sol : le point est posé (accroché tous les 5 cm).",
        "Glisser depuis le point pour régler son orientation (par pas de 15°, ou librement avec Maj) ; glisser "
        "le point lui-même le déplace.",
        "Corriger au besoin x, y et l'angle (en degrés) dans le panneau, puis **✓ Enregistrer**.",
    ]),
    ("p", "Les points sont écrits dans les mêmes fichiers et dans le même repère que depuis le Plan 2D "
          "(`salles.yaml`, et le nœud de même identifiant dans `itineraires.yaml`) : une salle placée en 3D "
          "apparaît au même endroit en 2D. Annuler et Rétablir marchent comme ailleurs. Sans WebGL (la 3D du "
          "navigateur), la vue affiche un message et l'Atelier passe au Plan 2D."),
    ("capture", ["*carte3d_iso_sombre*1366*.png", "*carte3d_iso_sombre*.png", "*carte3d_iso*.png", "*carte3d*.png",
                 "reel_sombre_placer*.png", "*placer*.png"],
     "Réel › Placer : l'accueil et les salles sur le nuage du scan", 16.0, 9.5),

    ("h2", "Le scan"),
    ("p", "**Réel › Scanner** passe en plein écran sombre, comme l'écran « 3D LiDAR Mapping » d'Unitree "
          "Explore : le nuage se remplit en direct, coloré par la hauteur, avec le trajet du robot, la durée, "
          "la distance, le nombre de points et de nuages, et deux gros boutons, **Scan** puis **Fin**. Après "
          "Fin, une barre suit le traitement (carte 3D, carte 2D, nuage), puis **Utiliser cette carte** en fait "
          "la carte de l'étage. Il n'y a plus de revue des tables et des chaises. En Simulation, le scan simulé "
          "est dans Simuler › Avancé › Scan simulé, avec l'exploration automatique ou les flèches."),
    ("capture", ["*pendant_le_scan*1366*.png", "*pendant_le_scan*.png", "*scan*en_cours*.png",
                 "reel_sombre_scanner*.png", "*scanner*.png"],
     "L'écran de scan, pendant un scan (ici en répétition)", 16.0, 9.5),

    ("h2", "Naviguer, Piloter et la caméra"),
    ("puces", [
        "**Naviguer** : Lancer (avec le robot, l'Atelier démarre le conteneur du Jetson), **Repérer** (le robot "
        "posé sur l'étoile, dans le sens de la flèche), Y aller (grisé tant que le robot n'est pas repéré), "
        "Bloquer, Débloquer, Arrêter. L'image de la caméra de poitrine s'incruste dans un coin.",
        "**Piloter** (en Réel seulement) : prendre ou rendre la main, postures, gestes, voix, lumière, deux "
        "joysticks en surimpression, et le groupe Spectacle (danses du robot, chorégraphies avec leur ligne de "
        "temps et leur aperçu 3D). Au centre, la **Vue du robot** : la carte avec sa position, le G1 en 3D qui "
        "reprend sa posture et ses gestes, la caméra de la tête. Elle ne commande rien.",
        "**La vue Caméra** : l'image de la caméra de poitrine en direct, avec un cadre autour de chaque "
        "visiteur détecté ; les réglages sont dans Équipe › Caméra.",
    ]),
    ("capture", ["reel_sombre_naviguer*.png", "reel_naviguer*.png", "*naviguer*.png"],
     "Réel › Naviguer", 16.0, 9.5),
    ("capture", ["reel_sombre_piloter*.png", "*piloter*.png"],
     "Réel › Piloter : la vue du robot, les joysticks et le panneau des commandes", 16.0, 9.5),
    ("capture", ["*vue_camera_sombre*1366*.png", "*vue_camera_sombre*.png", "*vue_camera*.png",
                 "*equipe_camera_sombre*1366*.png", "*camera*.png"],
     "La vue Caméra : l'image de la caméra de poitrine et les cadres des visiteurs", 16.0, 9.5),

    ("h2", "L'ARRÊT, les messages et le thème"),
    ("puces", [
        "**ARRÊT** est toujours visible, dans les deux modes et à toutes les tailles de fenêtre, et répond aussi "
        "à la touche **Échap**. En Réel et en répétition, il bloque aussi le robot et devient « Débloquer ». Il n'arrête pas un scan "
        "(c'est le rôle de Fin).",
        "Les **messages** s'affichent dans la barre d'état, sans fenêtres qui s'ouvrent ; les confirmations "
        "sont des fenêtres dans la page (plus de boîtes du navigateur).",
        "« **Ce qui tourne** » (les commandes lancées par l'Atelier) est dans le menu des réglages, et dans la barre "
        "d'état quand quelque chose tourne.",
        "Deux **thèmes**, sombre par défaut et clair (un bouton de la barre d'outils) ; la vue 3D reste toujours sur fond sombre. Les "
        "couleurs viennent de `css/theme.css`, et leurs contrastes sont vérifiés par les tests.",
        "Les anciennes adresses (`#salles`, `#simulation`, `#pilotage`…) mènent toujours au bon endroit.",
    ]),

    ("h2", "Sous le capot"),
    ("p", "La coque tient un **registre des commandes** (`COMMANDES` dans `js/coque/ruban.js`) : chaque commande a "
          "un identifiant stable (par exemple `salles.accueil` ou `navigation.reperer`), ses modes, son onglet, "
          "son libellé, son icône (un dessin SVG écrit dans le code), sa phrase d'aide et l'écran qui l'exécute. "
          "Les tests ne cherchent jamais un bouton par son texte : ils utilisent des repères stables "
          "(`data-role`, `data-commande`), si bien qu'un libellé peut changer sans casser les tests. Le "
          "critère 31 vérifie, à trois tailles de fenêtre et pour chaque onglet et chaque commande (186 "
          "mesures), que la page ne défile pas, que rien n'est coupé et que l'ARRÊT est visible. Le navigateur "
          "retient quelques choix (mode, thème, lieu, onglet) dans son stockage local."),
]
