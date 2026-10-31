"""Chapitre 6 : les données d'un lieu."""

BLOCS = [
    ("h1", "Les données d'un lieu"),
    ("chapeau", "Un lieu est un dossier de fichiers texte (YAML) et de cartes. Tous les outils les lisent et "
                "les écrivent de la même façon, par la bibliothèque `atelier.lieu`, et des schémas JSON "
                "vérifient chaque fichier. Les exemples viennent du lycée démo (`lieux/demo`) et du vrai "
                "scan du 27/10 (`lieux/seance`)."),
    ("schema", "donnees_lieu", "Les fichiers d'un lieu : ce que l'on décrit, ce qui est fabriqué, qui s'en sert",
     14.0, 12.5),

    ("h2", "lieu.yaml, salles.yaml, itineraires.yaml, zones.yaml"),
    ("p", "**`lieu.yaml`** donne le nom du lieu, ses étages et, pour chacun, la source de sa carte : `monde` "
          "(un bâtiment dessiné) ou `scan` (un vrai scan). Le champ `accueil` recopie la pose du point "
          "principal ; `carte_unitree` nomme la carte enregistrée sur le robot au scan ; une section `guide` "
          "facultative règle les délais du guide."),
    ("code", "version: 1\n"
             "nom: \"Lycée démo\"\n"
             "langue: fr\n"
             "etages:\n"
             "  - id: rdc\n"
             "    nom: \"Rez-de-chaussée\"\n"
             "    source_carte: monde          # monde | scan\n"
             "accueil: {etage: rdc, x: 2.5, y: 10.0, theta: 0.0}\n"
             "carte_unitree: null"),
    ("p", "**`salles.yaml`** liste les destinations : un identifiant, un nom, des alias (les mots du visiteur), "
          "une **pose** devant la porte (x, y et theta, l'orientation du robot à l'arrivée), une phrase "
          "d'arrivée. La salle qui porte l'étiquette `principal` est le **point principal** : l'accueil, d'où "
          "part la simulation, d'où se fait le repérage et où le robot revient après chaque visite. Il y en a "
          "un seul par lieu, et il est obligatoire."),
    ("code", "- id: accueil\n"
             "  nom: Accueil\n"
             "  alias: [accueil]\n"
             "  etage: rdc\n"
             "  pose: {x: 0, y: 0, theta: 0}\n"
             "  phrase_arrivee: ''\n"
             "  etiquettes: [principal]        # le point principal du lieu « seance »"),
    ("p", "**`itineraires.yaml`** est le graphe du guide : des **nœuds** (des points de passage) et des "
          "**couloirs** qui en relient deux, en ligne droite dans l'espace libre, 8 m au plus. Chaque salle a "
          "un nœud de même identifiant, à la même position. Le routeur y cherche le plus court chemin (A*) ; "
          "s'il trouve un couloir bloqué, il en prend un autre. Le lycée démo forme une boucle de 13 nœuds : "
          "entre l'accueil et chaque salle, il existe deux chemins."),
    ("p", "**`zones.yaml`** décrit des polygones : les **zones interdites** (le robot n'y entre jamais : elles "
          "deviennent un masque pour Nav2) et les **zones lentes** (avec une `vitesse_max`). Les zones lentes "
          "sont décrites, dessinées et vérifiées, mais Nav2 ne les applique pas encore : seul le masque des "
          "zones interdites est branché."),

    ("h2", "mondes/ : le bâtiment dessiné et sa simulation"),
    ("p", "**`mondes/<etage>.monde.yaml`** est le bâtiment inventé, vu de dessus avec des hauteurs : une "
          "emprise (le rectangle qui contient tout), des **murs** (segments avec une épaisseur et une hauteur ; "
          "un passage est l'écart entre deux murs alignés), des **objets** (boîtes, cylindres, ou modèles : "
          "chaise, table, banc, poubelle), des **piétons** (un trajet, une vitesse, une réaction au robot : "
          "`ecart`, `arret` ou `aucune`) et le départ du robot. `g1-monde generer` en tire "
          "**`<etage>.sdf`**, le monde de Gazebo. Pour un étage scanné, le monde est la carte du scan "
          "**extrudée** sur 1,5 m de haut en un seul maillage, **`<etage>_carte.stl`** (champ `carte_extrudee`)."),

    ("h2", "cartes/ : ce que Nav2 et la carte 3D lisent"),
    ("table", {
        "entetes": ["Fichier", "Contenu", "Écrit par"],
        "largeurs": [4.6, 7.6, 4.4],
        "taille": 9,
        "lignes": [
            ["`rdc.pgm` + `rdc.yaml`", "la carte de navigation (5 cm par pixel ; 0 occupé, 254 libre, 205 inconnu)",
             "`g1-monde generer` ou `g1-scan adopter`"],
            ["`rdc_interdit.pgm` + `.yaml`", "le masque des zones interdites, même taille que la carte",
             "`g1-monde generer`"],
            ["`rdc.pcd`", "le nuage 3D du scan adopté (format PCD d'Open3D)", "`g1-scan adopter`"],
            ["`rdc.nuage.bin` + `.json`", "le nuage d'affichage de la carte 3D : x, y et hauteur au-dessus du sol",
             "`g1-scan adopter`"],
            ["`rdc_unitree.pcd`, `rdc_unitree.nuage.*`", "la carte d'Unitree, récupérée pendant un repérage",
             "`g1-scan carte-unitree`"],
        ],
    }),
    ("p", "Le **nuage d'affichage** est fait pour le navigateur : le fichier `.bin` est une simple suite de "
          "nombres à virgule (Float32) x, y, z, 12 octets par point, sans en-tête ; le fichier `.json` à côté "
          "en donne la description. Celui du lieu `seance` :"),
    ("code", "{\"version\": 1, \"format\": \"float32_xyz\", \"points\": 299558, \"grille\": 0.05,\n"
             " \"repere\": \"map\",\n"
             " \"bornes\": {\"xmin\": -6.897, \"ymin\": -15.99, \"zmin\": -2.15,\n"
             "            \"xmax\": 7.997, \"ymax\": 5.527, \"zmax\": 4.049},\n"
             " \"sol\": {\"plan\": [0.001057, -0.010145, -1.271333],\n"
             "         \"inclinaison_deg\": 0.584, \"methode\": \"ransac\"},\n"
             " \"source\": \"scan\", \"session\": \"2026-10-27_14h22\", \"etage\": \"rdc\",\n"
             " \"date\": \"2026-10-31T16:37:22+01:00\", \"mobiles_retires\": 106371}"),
    ("p", "x et y sont ceux du repère `map`, les mêmes que dans `salles.yaml` : une salle placée en 3D l'est "
          "aussi en 2D, sans conversion. z est la hauteur au-dessus du plan du sol (le sol réel était penché "
          "de 0,58°)."),

    ("h2", "scans/ : une session par scan"),
    ("p", "Chaque scan est une **session** : un dossier `scans/<date>_<heure>/` (par exemple "
          "`2026-10-27_14h22`). Un seul scan peut être actif par lieu. Son état passe par `en_cours`, "
          "`arret_en_cours`, `traitement`, puis `termine` (ou `echec`, avec un message qui dit quoi faire)."),
    ("table", {
        "entetes": ["Fichier de la session", "Contenu"],
        "largeurs": [5.0, 11.6],
        "taille": 9,
        "lignes": [
            ["`session.json`", "l'état, l'étape, la progression, les statistiques (durée, points, distance)"],
            ["`enregistrement/`", "l'enregistrement brut (ros2 bag) : nuages et odométrie du SLAM"],
            ["`apercu.png`, `apercu.json`, `apercu_nuage.bin`", "l'aperçu en direct, réécrit toutes les 2 s"],
            ["`nuage.pcd`, `carte.pgm` + `.yaml`", "le nuage 3D et la carte 2D fabriqués à la fin"],
            ["`nuage_affichage.bin` + `.json`", "le nuage de la carte 3D (grille de 5 cm)"],
            ["`rapport.json`", "le bilan : nuages reçus et gardés, base de temps, plan du sol, passants retirés"],
            ["`ancien_<date>/`", "les résultats d'avant, quand on refait le traitement (`--refaire`)"],
        ],
    }),

    ("h2", "Les fichiers de l'équipe, les sauvegardes et les schémas"),
    ("puces", [
        "**`personnalites.yaml`** : les modes du robot (salutation, voix, couleur de la LED, geste de salut, "
        "vitesse maximale, phrases du guide) ; **`dialogues.yaml`** : le chatbot à règles ; "
        "**`camera.yaml`** : la See3CAM, sa position sur le robot, l'exposition, la détection. Tous trois "
        "sont facultatifs et ont un exemple dans `atelier/lieu/exemples/`.",
        "**`sauvegardes/<date>_<raison>/`** : une copie faite avant une opération qui réécrit le lieu "
        "(migration, retraitement), avec un `LISEZMOI.txt` qui dit comment revenir en arrière.",
        "**Les schémas** : `atelier/lieu/schemas/` en contient 28, en JSON Schema draft-07 : un par sorte de "
        "fichier (lieu, monde, salles, itinéraires, zones, carte, session de scan, nuage, personnalités, "
        "dialogues, caméra, scène, chorégraphie) et un par message JSON des sujets ROS 2 (état du guide, "
        "état du pont, état du repérage, personnes vues…). En cas de doute sur un champ, ce sont eux qui font foi.",
    ]),
    ("code", "g1-lieu valider --lieu seance      # vérifie tout le lieu et dit quoi corriger"),
]
