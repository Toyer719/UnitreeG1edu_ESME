"""Chapitre 14 : se repérer et modifier, onze recettes."""

BLOCS = [
    ("h1", "Se repérer et modifier : onze recettes"),
    ("chapeau", "Chaque recette dit quand s'en servir, où se trouve ce qu'il faut changer, comment faire, et "
                "comment vérifier. Règle générale : changer une chose à la fois, lancer les tests de cette "
                "partie, puis recompiler (ROS 2) ou recharger la page (interface). Et faire un commit quand "
                "ça marche."),

    ("h2", "Changer le texte, l'aide ou l'icône d'une commande"),
    ("p", "**Où** : `atelier/web/js/coque/ruban.js`, le registre `COMMANDES`. Chaque commande y a un `libelle` "
          "(sous l'icône), une phrase d'`aide` (au survol) et une `icone` (dessinée dans `js/coque/icones.js`). "
          "Les couleurs de toute l'interface sont des jetons dans `atelier/web/css/theme.css`."),
    ("num", [
        "Modifier le `libelle` ou l'`aide` de la commande ; ne jamais changer son `id` (les tests et les autres "
        "écrans s'en servent).",
        "Recharger la page de l'Atelier (Ctrl+Maj+R) : le serveur n'a pas besoin d'être relancé.",
        "Vérifier : `.venv-projet/bin/python -m pytest atelier/tests/test_coque.py -q`.",
    ]),

    ("h2", "Ajouter ou corriger une salle à la main"),
    ("p", "**Où** : `lieux/<id>/salles.yaml` et `lieux/<id>/itineraires.yaml`. Le plus simple reste l'Atelier "
          "(Placer › Salle, en 3D ou en 2D), qui écrit les deux fichiers d'un coup."),
    ("num", [
        "Dans `salles.yaml`, ajouter une salle : `id`, `nom`, `alias`, `etage`, `pose` (x, y, theta) et "
        "`phrase_arrivee`.",
        "Dans `itineraires.yaml`, ajouter un nœud de même `id` à la même position, et au moins un couloir qui "
        "le relie au graphe (8 m au plus, en ligne droite dans l'espace libre).",
        "Vérifier : `g1-lieu valider --lieu <id>` dit « Aucune erreur. » ou quoi corriger.",
    ]),
    ("p", "Attention : l'Atelier réécrit ces fichiers quand il enregistre ; les commentaires ajoutés à la main ne "
          "sont pas conservés."),

    ("h2", "Changer ce que dit le robot"),
    ("p", "**Où** : la phrase d'arrivée de chaque salle (`phrase_arrivee` de `salles.yaml`) ; les phrases du guide "
          "par personnalité (`phrases` de `personnalites.yaml`, écran Équipe › Personnalités) ; les phrases par "
          "défaut dans `CODES_EVENEMENT` de `atelier/lieu/comportement.py` (départ, ralentir, attente, retour…)."),
    ("code", "personnalites:\n"
             "  - id: accueillant\n"
             "    phrases:                       # {nom} : le nom de la salle\n"
             "      depart: \"Avec plaisir ! Suivez-moi jusqu'à {nom}.\"\n"
             "      arrivee: \"Et voilà : {nom}. Bonne journée !\""),
    ("p", "**Vérifier** : écran Équipe, ou `g1-lieu valider --lieu <id>` (il vérifie aussi les fichiers de l'équipe). "
          "Les phrases de la démo d'accueil (« Je fais une petite pause. », « Je suis occupé… », « Direction … : "
          "suivez-moi ! ») sont en tête de `ws/src/g1_accueil/g1_accueil/logique.py`, celles des écrans de la borne "
          "dans `TEXTES_BORNE` de `atelier/lieu/accueil.py` ; le titre de la borne se change dans les réglages de "
          "la démo."),

    ("h2", "Régler les délais du guide"),
    ("p", "**Où** : la section `guide` de `lieu.yaml`, ou Simuler › Avancé › Réglages du guide, qui l'écrit."),
    ("code", "guide: {retour_auto: true, delai_avant_retour_s: 15, delai_visiteur_s: 30,\n"
             "        distance_ralentir_m: 2.0, distance_attendre_m: 3.5, ralenti: 0.5,\n"
             "        delai_perdu_s: 30, delai_passant_s: 20}"),
    ("p", "Le guide lit ces valeurs au lancement de la navigation : relancer la simulation (ou Naviguer › Arrêter "
          "puis Lancer). Trois réglages se changent en marche, sans relancer : "
          "`ros2 param set /guide tolerance_orientation_rad 0.4` (et `anticipation_rotation_rad`, `pourcentage_min`)."),

    ("h2", "Mettre à jour la vitesse minimale après une mesure"),
    ("p", "**Quand** : après la séance n° 2, quand les vrais seuils de marche et de rotation auront été mesurés "
          "(`python3 -m g1_bridge.mesure marche|rotation|cap`). **Où** : la même valeur est à trois endroits, "
          "qu'un test compare :"),
    ("table", {
        "entetes": ["Fichier", "Nom"],
        "largeurs": [8.6, 8.0],
        "taille": 9,
        "lignes": [
            ["`atelier/lieu/robot.py`", "`VITESSES_MIN_PONT = {\"lin\": 0.20, \"rot\": 0.30}`"],
            ["`ws/src/g1_bridge/g1_bridge/logique.py`", "`VITESSES_MIN = {'lin': 0.20, 'rot': 0.30}`"],
            ["`ws/src/g1_bridge/config/pont.yaml`", "`vitesse_min_lin: 0.2`, `vitesse_min_rot: 0.3`"],
        ],
    }),
    ("num", [
        "Changer la valeur aux trois endroits.",
        "Vérifier : `cd ~/robot-g1/ws && colcon test --packages-select g1_bridge && colcon test-result --all`, "
        "puis `tests_e2e/tout.sh 34`.",
        "Refaire l'image du Jetson (dernière recette).",
    ]),

    ("h2", "Changer un réglage de Nav2"),
    ("p", "**Où** : `ws/src/g1_nav/config/nav2_g1_reel.yaml` (robot réel et répétition) et `nav2_g1_simu.yaml` "
          "(simulation). Ils doivent rester identiques, sauf les vitesses et l'horloge : un test "
          "(`ws/src/g1_nav/test/test_reglages.py`) le vérifie. Exemples : `inflation_radius` (la distance gardée "
          "aux obstacles), les zones du `collision_monitor` (ralentir, arrêter), les hauteurs de la `voxel_layer`."),
    ("num", [
        "Modifier les deux fichiers de la même façon.",
        "Sur le PC, avec `colcon build --symlink-install`, relancer la navigation suffit en général ; pour "
        "le robot, refaire l'image du Jetson (dernière recette).",
        "Vérifier sur les scènes de passants : `tests_e2e/tout.sh 23 24 25` (environ une heure), ou "
        "`g1-banc --scene immobile_couloir` pour un essai rapide.",
    ]),

    ("h2", "Ajouter une règle au chatbot"),
    ("p", "**Où** : `lieux/<id>/dialogues.yaml` (écran Équipe › Dialogues ; « Partir de l'exemple » le crée). La "
          "première règle qui correspond l'emporte ; `{salle}` vaut une salle (identifiant, nom ou alias), `{*}` "
          "n'importe quels mots ; les motifs s'écrivent sans majuscules, accents ni ponctuation."),
    ("code", "  - id: toilettes\n"
             "    motifs: [\"ou sont les toilettes\", \"toilettes\"]\n"
             "    action: dire\n"
             "    reponse: \"Les toilettes sont au bout du couloir, à gauche.\""),
    ("p", "**Vérifier** : bouton « Essayer » de l'écran Dialogues (aucun mouvement), ou "
          "`POST /api/lieux/<id>/dialogues/essayer` avec la phrase."),

    ("h2", "Refaire le traitement d'un scan"),
    ("p", "**Quand** : après une amélioration de la chaîne du scan, pour en profiter sur un vieux scan. Rien n'est "
          "effacé : les résultats d'avant partent dans `ancien_<date>/`."),
    ("code", "g1-scan traiter --lieu seance --session 2026-10-27_14h22 --refaire\n"
             "g1-scan adopter --lieu seance --session 2026-10-27_14h22   # la réadopter\n"
             "g1-lieu valider --lieu seance"),
    ("p", "Faire une copie du lieu avant (`cp -a ~/robot-g1/lieux/seance <ailleurs>`) : le dossier "
          "`lieux/seance` n'est pas dans Git."),

    ("h2", "Ajouter une route à l'API"),
    ("p", "**Où** : `atelier/serveur/routes/<sujet>.py`. Chaque fichier a un `routeur` (FastAPI) ; une erreur se "
          "dit avec `ErreurAtelier(code, \"message en français\")`, que le serveur transforme en `{\"detail\": …}`. "
          "Un exemple simplifié :"),
    ("code", "@routeur.get(\"/api/lieux/{id_lieu}/resume\")\n"
             "def resume(id_lieu: str):\n"
             "    \"\"\"Le nom du lieu et son nombre de salles.\"\"\"\n"
             "    lieu = charger_lieu(chemin_lieu(id_lieu))\n"
             "    return {\"nom\": lieu.nom, \"salles\": len(lieu.salles)}"),
    ("p", "Un nouveau fichier de routes doit être ajouté à la liste des modules de `atelier/serveur/main.py`. "
          "Écrire son test dans `atelier/tests/` (le client de test de FastAPI sur une copie du lieu demo), puis "
          "relancer `g1-atelier`."),

    ("h2", "Régler la démo d'accueil et la voix"),
    ("p", "**Où** : Équipe › Avancé › **Réglages de la démo**, qui écrit `lieux/<id>/demo.yaml` (fichier facultatif : "
          "sans lui, les réglages par défaut, dont un volume de 70 %) ; les salles proposées par la borne y sont des "
          "cases à cocher (une salle décochée reçoit l'étiquette `hors_borne` dans `salles.yaml`)."),
    ("code", "version: 1\n"
             "voix: {sortie: robot, volume: 30, nom: fr_FR-siwis-medium, vitesse: 1.0}\n"
             "visiteurs: {source: borne, distance_m: 1.5, presence_s: 1.0}   # la borne seule\n"
             "delais: {choix_s: 45, depart_s: 10, entre_visiteurs_s: 8}\n"
             "accompagner: true\n"
             "retour: true\n"
             "borne:\n"
             "  langue: fr\n"
             "  titre: \"Bonjour ! Où voulez-vous aller ?\"\n"
             "  code_operateur: \"2468\"     # 4 à 8 chiffres ; sans lui, pas de mode opérateur"),
    ("num", [
        "Avec le robot, **baisser le volume d'abord** (20 à 30 %), « Enregistrer les réglages », puis « Démarrer la "
        "voix » et « Essayer » : le volume part au haut-parleur du robot (ordre 1006) ; le monter ensuite de 10 en 10.",
        "« Arrêter la voix », puis **Lancer la démo** : elle prend les réglages enregistrés (une démo qui tourne "
        "doit être relancée pour les prendre).",
        "Vérifier : `g1-lieu valider --lieu <id>` (il vérifie aussi `demo.yaml`) ; sans robot, la démo s'essaie en "
        "simulation, avec la scène « Accompagnement d'un visiteur » (Simuler › Avancé › Passants) et la borne "
        "ouverte sur ce PC (`http://localhost:8000/borne`).",
    ]),

    ("h2", "Mettre à jour le conteneur du Jetson"),
    ("p", "**Quand** : après toute modification de `ws/src` (`g1_nav`, `g1_bridge`, `g1_pilotage`, `g1_equipe`) "
          "ou de `atelier/lieu` et `atelier/equipe`, qui sont copiés dans l'image."),
    ("code", "cd ~/robot-g1/ws && colcon build --symlink-install   # le PC d'abord\n"
             "g1-jetson construire --arch amd64                     # l'image du PC\n"
             "~/robot-g1/tests_e2e/tout.sh 16                       # son critère\n"
             "g1-jetson construire                                  # l'image du Jetson\n"
             "source ~/robot-g1/setup/robot.sh                      # robot branché\n"
             "g1-jetson envoyer                                     # 2 à 5 min\n"
             "g1-jetson demarrer --lieu seance --etage rdc          # ou Naviguer › Lancer"),
    ("p", "Seules les dernières couches de l'image sont refaites : moins d'une minute pour l'image du PC, "
          "quelques minutes pour celle du Jetson."),
]
