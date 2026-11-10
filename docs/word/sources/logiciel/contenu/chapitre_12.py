"""Chapitre 12 : diagnostic, boîte noire et démo d'accueil (vague 6).

Les captures viennent de ~/robot-g1-donnees/vague6/captures/ (deuxième dossier de --captures) : les captures
finales de la recette du 10/11 (10_diagnostic.png à 17_borne_tablette.png ; Atelier à 1600 × 900, borne à
390 × 844 et 1024 × 768). Comme au chapitre 11, une capture absente est simplement omise, et les légendes
décrivent ces captures-là : une autre capture demande de relire sa légende.
"""

BLOCS = [
    ("h1", "Diagnostic, boîte noire et démo d'accueil (vague 6)"),
    ("chapeau", "Du 08 au 10/11/2026, la vague 6 a ajouté deux choses. D'abord, de quoi rendre chaque séance avec "
                "le robot efficace : **« Vérifier le robot »**, un diagnostic en un clic, et la **boîte noire**, qui "
                "enregistre toute la séance et en écrit le rapport. Ensuite, la **démo d'accueil** complète, essayée "
                "en simulation : la **borne** où le visiteur choisit sa salle, le nœud **accueil** qui mène la visite, "
                "et la **voix** du robot. Rien de tout cela n'a encore tourné sur le vrai G1 : c'est pour la séance "
                "n° 2."),
    ("si_captures", [
        ("p", "Les images de ce chapitre ont été prises le 10/11, à la fin de la recette, dans Firefox piloté sans "
              "fenêtre (avec WebGL), sur des copies du lieu « Lycée démo » : l'Atelier dans une fenêtre de 1 600 × 900 "
              "pixels, en répétition (le faux G1) ou en simulation ; la borne à la taille d'un téléphone "
              "(390 × 844) et d'une tablette (1 024 × 768). La démo des captures a été jouée pour de vrai : "
              "simulation, faux visiteur qui suit, un appui sur la borne, le robot qui salue puis accompagne."),
    ]),

    ("h2", "Ce que la vague 6 apporte"),
    ("p", "Le 08/11 au soir, l'utilisateur a demandé « ok go 1 puis 2 » : **1**, une séance avec le robot qui ne "
          "perde plus de temps ni de journaux ; **2**, une démo d'accueil complète, testable dès maintenant sans le "
          "robot. Les choix sont écrits dans `~/robot-g1-donnees/vague6/DECISIONS.md`, les contrats dans la section 13 "
          "du plan. Cinq pièces nouvelles :"),
    ("table", {
        "legende": "Les pièces de la vague 6",
        "entetes": ["Pièce", "Ce qu'elle fait", "Code", "Commande"],
        "largeurs": [3.0, 7.0, 3.9, 2.7],
        "taille": 8.5,
        "premiere_col_gras": True,
        "lignes": [
            ["Vérifier le robot", "contrôle en quelques secondes le câble, le réseau, les services du robot, son "
             "mode, sa batterie, le Jetson et la caméra, et dit quoi faire", "`atelier/diagnostic/`, "
             "`js/coque/diagnostic.js`", "`g1-diagnostic`"],
            ["Boîte noire", "enregistre chaque séance en Réel (actions, états du robot, journaux), puis écrit son "
             "rapport", "`atelier/seance/`, `js/coque/seance.js`", "`g1-seance`"],
            ["Démo d'accueil", "le nœud `accueil` : il attend un visiteur, le salue, lui fait choisir une salle, "
             "l'y fait accompagner par le guide, puis attend le suivant", "`ws/src/g1_accueil/`, "
             "`js/ecrans/demo.js`", "`g1-accueil`"],
            ["Borne visiteur", "une page pour tablette ou téléphone : « Bonjour ! Où voulez-vous aller ? »",
             "`borne.html`, `js/borne/`", "(`g1-atelier --hote 0.0.0.0`)"],
            ["Voix du robot", "les phrases du robot, fabriquées sur le PC (Piper) et jouées par son haut-parleur, "
             "par la borne, ou par sa synthèse intégrée", "`atelier/voix/`, `js/voix/`", "`g1-voix`"],
        ],
    }),
    ("p", "La règle de sécurité de la vague 5 vaut partout (chapitre 9) : **rien ne repart seul**. La démo se met "
          "en pause au moindre empêchement et attend une demande explicite ; le diagnostic ne fait jamais bouger "
          "le robot et n'agit que sur un clic confirmé ; depuis le réseau, la borne ne peut rien faire d'autre que "
          "proposer les salles."),

    ("h2", "Vérifier le robot : le diagnostic en un clic"),
    ("p", "Le bouton **Vérifier le robot** est sur l'accueil (carte Robot réel), dans la barre d'outils en Réel et "
          "dans Naviguer ; `g1-diagnostic` fait la même chose dans un terminal, avec le même code. Les vérifications "
          "tournent en parallèle, chacune avec son délai : tout tient en 15 s (en général bien moins : 0,3 s en "
          "répétition). Chaque point dit **OK**, **Attention**, **Problème** ou **Inconnu** (rien pu vérifier), avec "
          "une phrase qui dit ce qui a été vu et, s'il n'est pas OK, **une phrase qui dit quoi faire**. L'état "
          "général est le pire des points ; en haut de la fenêtre, le conseil le plus important."),
    ("table", {
        "legende": "Les dix-sept vérifications de « Vérifier le robot »",
        "entetes": ["Groupe", "Ce qui est vérifié", "Comment"],
        "largeurs": [2.4, 7.2, 7.0],
        "taille": 8.5,
        "premiere_col_gras": True,
        "lignes": [
            ["Câble et réseau", "le câble branché ; l'adresse 192.168.123.99 du PC ; la connexion « robot-g1 » "
             "active (et rallumée seule au branchement) ; les réglages ROS de l'Atelier (domaine 0, DDS sur le "
             "câble) ; le PC1, le Jetson et le LiDAR qui répondent", "fichiers du système, `nmcli`, un `ping` "
             "chacun, seulement si le câble est là"],
            ["Robot", "le robot parle au PC (ses sujets sont vus) ; les **services de cartographie** `lidar_driver` "
             "et `unitree_slam` actifs ; le mode du robot (lecture seule) ; la batterie (Attention sous 30 %, "
             "Problème sous 15 %)", "ROS 2 : liste des services (robot_state 1003), mode (7001), `/lf/bmsstate`"],
            ["Jetson", "la clé SSH ; Docker utilisable sans sudo ; la même image du conteneur que sur le PC ; "
             "5 Go libres ; l'heure (2 s d'écart au plus) ; la caméra See3CAM branchée en USB 3",
             "**un seul** `ssh` qui lance un petit script ; `/camera_poitrine/etat` s'il est publié"],
        ],
    }),
    ("p", "**Trois actions**, proposées par le point concerné, ne partent qu'après une confirmation dans la page : "
          "**Démarrer les services de cartographie** (seulement `lidar_driver` et `unitree_slam`, s'ils sont "
          "arrêtés, puis la liste relue chaque seconde jusqu'à ce qu'ils tournent, 20 s au plus), **Rétablir la "
          "connexion du câble** (`nmcli connection up robot-g1`) et **La rétablir seule à chaque branchement**. "
          "Jamais un arrêt de service, jamais `ai_sport` ni `motion_switcher` (les services de la marche) : c'est "
          "une **liste blanche**, vérifiée par le serveur avant toute requête au robot. En répétition, les points "
          "sans objet (câble, réseau, Jetson) sont rangés dans « Pas vérifiés ici »."),
    ("capture", ["11_diagnostic_problemes*.png", "*diagnostic*probleme*.png"],
     "Vérifier le robot en répétition : le faux G1 a ses services de cartographie arrêtés ; un point à régler, "
     "et le bouton de l'action", 15.5, 9.0),
    ("capture", ["10_diagnostic.png", "10_diagnostic*.png"],
     "Après « Démarrer les services de cartographie » : « ont démarré en 2 s », puis « Tout est prêt ! »",
     15.5, 9.0),
    ("code", "g1-diagnostic                             # en texte ; code 0 si tout va bien\n"
             "g1-diagnostic --action demarrer-services  # une action, après la réponse « oui »\n"
             "g1-diagnostic --mode repetition --json    # contre le faux G1, le résultat brut"),
    ("p", "**Sans robot**, tout s'essaie : le faux G1 répond à robot_state (liste des services, démarrage avec 2 s "
          "de délai) et compte toute demande interdite ; les vérifications du système (câble, `nmcli`, ping, ssh) "
          "lisent un **faux contexte** (`ATELIER_DIAGNOSTIC_FAUX`, un fichier JSON de réponses), qui note ce que "
          "l'action « aurait » lancé sans rien lancer. Les tests n'envoient jamais de ping, de ssh ni de `nmcli` vers "
          "le robot. Le format exact de la réponse du vrai G1 à 1003 et 1001 reste à vérifier (sur ce G1, le "
          "statut 0 veut dire « actif » et 1 « arrêté », d'après la séance n° 1)."),

    ("h2", "La boîte noire et le rapport de séance"),
    ("p", "Dès qu'on ouvre l'espace de travail en Réel (vrai robot ou répétition), une **séance** s'ouvre : le badge "
          "« ● Enregistrement » apparaît dans la barre d'outils (« Séance » sur un écran plus étroit). Elle garde tout "
          "jusqu'à **Terminer la séance** (menu du badge, ou Naviguer › Avancé), ou jusqu'à l'arrêt de l'Atelier. "
          "Rouvrir l'espace en Simulation la termine ; « Nouvelle séance » en ouvre une autre."),
    ("table", {
        "legende": "Le dossier d'une séance : journaux/seances/<AAAA-MM-JJ_HHhMM>/",
        "entetes": ["Fichier", "Contenu"],
        "largeurs": [4.6, 12.0],
        "taille": 8.5,
        "lignes": [
            ["`seance.json`", "le manifeste : dates, lieu, mode, état de l'enregistrement, journaux du Jetson, rapport"],
            ["`actions.jsonl`", "une ligne par demande qui change quelque chose (ARRÊT, Bloquer, Débloquer, Y aller, "
             "Repérer, Lancer, postures, danses, scan, démo, borne, voix…), avec l'heure, le mode, la réponse et "
             "un texte en français ; le code opérateur de la borne y est masqué"],
            ["`bag/`", "l'enregistrement ROS 2 (rosbag2) des sujets légers : guide, pont, repérage, ordres de marche "
             "et leurs réponses, odométries (10 Hz au plus), batterie, pilotage, démo, voix, journaux des nœuds "
             "(`/rosout`) ; jamais les nuages de points, les images ni le son"],
            ["`journaux/`", "le journal du serveur, la fin des journaux des programmes lancés, et dans `jetson/` le "
             "**journal du conteneur du Jetson**, gardé avant chaque « Arrêter » de la navigation et à la fin"],
            ["`lieu/`, `diagnostic_debut.json`", "la copie du lieu ouvert ; le diagnostic pris à l'ouverture (et "
             "`diagnostic_lancement.json`, pris une fois la navigation lancée)"],
            ["`rapport.html`, `.md`, `.json`, `trajets.png`", "le rapport, écrit tout seul en moins d'une minute"],
        ],
    }),
    ("schema", "boite_noire", "La boîte noire : de l'ouverture de la séance à son rapport", 14.0, 10.0),
    ("p", "**Ce que ça coûte** : l'enregistreur relève les messages 20 fois par seconde et réduit les sujets rapides "
          "(une odométrie à 10 Hz) ; mesuré en répétition avec Nav2 : 1,9 % d'un cœur pendant un trajet, environ "
          "150 Mo par heure ; l'ARRÊT répondait toujours en 0,05 s. **Garde-fous** : au-delà de 1 Go, ou sous 2 Go "
          "libres sur le disque, l'enregistrement s'arrête proprement (badge orange « Enregistrement coupé ») et la "
          "séance continue ; un client qui insiste (3 000 demandes refusées) ne laisse qu'une ligne et son résumé. "
          "**Après un plantage**, la séance est marquée « interrompue » au redémarrage de l'Atelier, son bag est "
          "réindexé s'il le faut, et son rapport écrit."),
    ("capture", ["12_seance_badge*.png", "*seance*badge*.png"],
     "Le badge « Séance » et son menu : enregistrement depuis 01 h 26, 9 actions, 11,6 Mo ; « Terminer la "
     "séance » ; le rapport de la séance d'avant", 15.5, 9.0),
    ("p", "**Le rapport** dit, en français simple : **En bref** (durée, trajets, distance, arrêts d'urgence, "
          "anomalies, erreurs, batterie au début et à la fin) ; **À regarder en premier**, les anomalies trouvées "
          "toutes seules (un **mouvement sans demande** : le robot avance de plus de 5 cm/s sans mission du guide, "
          "sans joystick ni pilotage ; un robot qui ne répond plus ; un ARRÊT ou un verrou ; une séance "
          "interrompue ; un enregistrement coupé ; une erreur du serveur ; un repérage perdu) ; **Les trajets** sur "
          "la carte, chacun avec son résultat (arrivé, échec, interrompu par un ARRÊT, un blocage ou une panne, "
          "abandonné) et la cause de ses arrêts ; **Le robot** (temps dans chaque état du pont, modes vus, "
          "précision du repérage) ; les **erreurs** traduites, le détail technique replié ; les **diagnostics** ; "
          "la **chronologie** complète. Un arrêt normal (Ctrl+C, « Arrêter ») n'y est pas compté comme une erreur."),
    ("capture", ["13_rapport_seance*.png", "*rapport*seance*.png"],
     "Le rapport d'une séance de répétition : 3 trajets (2 arrivés, 1 interrompu par l'ARRÊT), 48,9 m, "
     "aucune erreur, et la carte des trajets", 15.5, 9.0),
    ("code", "g1-seance liste                  # les séances, la plus récente d'abord\n"
             "g1-seance rapport derniere       # refaire le rapport de la dernière\n"
             "g1-seance exporter derniere      # un .zip pour Claude (--sans-bag : plus petit)"),

    ("h2", "La démo d'accueil"),
    ("p", "**Équipe › Démo › Lancer la démo** lance deux nœuds sur le PC : `accueil`, qui mène les visites, et "
          "`voix`. Il faut que le guide tourne (simulation lancée, ou navigation du robot lancée et robot repéré) ; "
          "sinon la demande est refusée avec la phrase qui dit quoi faire. **Arrêter la démo** arrête ces deux "
          "nœuds, pas le robot : c'est le rôle de l'ARRÊT."),
    ("puces", [
        "**Un visiteur** est vu quand il se tient à 1,5 m au plus, devant le robot, depuis 1 s (par la caméra si "
        "`g1-visiteurs` tourne, sinon par le LiDAR) ; ou quand il touche la borne. Le robot le salue avec la "
        "phrase de sa personnalité, et la borne montre les salles (45 s pour choisir).",
        "**La visite** : le nœud envoie `/guide/aller` avec `accompagner` ; le guide de la vague 4 fait le reste "
        "(ralentir si le visiteur traîne, l'attendre, retour automatique). La démo suit `/guide/etat` et "
        "`/guide/evenement`, et relaie les phrases du guide vers la voix.",
        "**La pause** : ARRÊT, verrou, robot assis ou muet, pont absent, échec ou robot perdu pendant une visite, "
        "pilotage qui prend la main, guide muet depuis 3 s, ou « Mettre en pause ». En pause, aucun `/guide/aller` "
        "ne part, la borne dit « Je fais une petite pause » et refuse les choix. **La levée de l'empêchement ne "
        "fait rien d'autre que rendre « Reprendre » possible** : « Reprendre » (le robot à l'accueil), ou "
        "« Ramener à l'accueil » (une demande explicite, la seule permise en pause).",
        "**Pas des pauses** : le délai de choix (retour à l'attente, sans mouvement), le visiteur perdu (le guide "
        "revient seul, la visite compte comme abandonnée), la borne touchée pendant une visite (« Je suis occupé, "
        "je reviens dans un instant ! »).",
        "**Les statistiques** depuis le lancement : visiteurs salués, visites réussies, abandons, échecs, pauses, "
        "durée moyenne.",
    ]),
    ("schema", "demo_accueil", "La démo d'accueil : les états du nœud accueil, et la pause", 16.0, 11.5),
    ("capture", ["14_demo*.png", "*demo*.png"],
     "L'écran Démo, en simulation : le robot accompagne un visiteur vers la salle B204 (« encore 16 m ») ; "
     "l'adresse de la borne et les statistiques", 15.5, 9.0),
    ("p", "**Les réglages** (**Équipe › Avancé › Réglages de la démo**, fichier facultatif `demo.yaml` du lieu) : "
          "la personnalité ; la voix (sortie, voix, volume, vitesse) ; qui voit les visiteurs (automatique, caméra, "
          "LiDAR ou la borne seule) et à quelle distance ; les délais ; l'accompagnement et le retour seul ; le "
          "titre et la langue de la borne (français ou anglais) ; le **code opérateur** ; les salles proposées par "
          "la borne (une salle décochée reçoit l'étiquette `hors_borne` ; le point principal n'est jamais proposé). "
          "Le chatbot de l'équipe pourra choisir la salle à la place de la borne, par le même message "
          "(`/accueil/choix`, `docs/integration-equipe.md`)."),

    ("h2", "La borne visiteur"),
    ("p", "La page `/borne` est faite pour le tactile et pour un public : de grandes cartes de 64 pixels de haut au "
          "moins, aucun mot technique, une page qui ne défile jamais (seule la liste des salles défile). Elle "
          "suit la démo quatre fois par seconde : « Bonjour ! Où voulez-vous aller ? », la confirmation « Je vous "
          "accompagne à … ? » Oui / Non, « Suivez-moi ! » avec la distance restante, l'arrivée, « Je retourne à "
          "l'accueil », « Je suis occupé », la pause. Deux appuis à moins de 0,6 s comptent pour un, même envoyés "
          "en même temps. Avec la sortie « borne », la page joue aussi la voix du robot."),
    ("p", "**Sur une tablette du même Wi-Fi**, il faut lancer l'Atelier avec `g1-atelier --hote 0.0.0.0` ; "
          "**Équipe › Démo › Borne** montre alors l'adresse en grand, avec son code QR (dessiné par un petit "
          "encodeur écrit pour le projet, sans bibliothèque). Depuis le réseau, **seule la borne est permise** : "
          "l'Atelier, « Débloquer », « Y aller », les réglages et le pilotage répondent 403 (refusé). Un bouton "
          "discret et le **code opérateur** ouvrent, pour 5 minutes, trois commandes : pause, reprendre, ramener "
          "à l'accueil ; cinq mauvais codes en 5 minutes bloquent la saisie. Enfin, **une page d'un autre site** "
          "ouverte dans le navigateur du PC ne peut plus rien demander à l'Atelier (garde des origines, ajoutée "
          "après la revue)."),

    ("captures", [["15_borne_telephone_choix*.png"], ["16_borne_telephone_suivi*.png"]],
     "La borne sur un téléphone (390 × 844) : le choix de la salle, puis « Suivez-moi ! », la distance et les "
     "trois points qui s'allument tour à tour", 13.0, 10.0),
    ("capture", ["17_borne_tablette*.png", "*borne*tablette*.png"],
     "La borne sur une tablette (1 024 × 768)", 13.0, 9.5),
    ("h2", "La voix du robot"),
    ("schema", "voix", "La voix : d'une phrase au haut-parleur du robot", 15.0, 9.5),
    ("p", "Le nœud `voix` (`g1-voix`, lancé avec la démo ou seul, depuis les réglages de la démo) écoute "
          "`/robot/dire` : la salutation et la pause de la démo, les phrases du guide relayées (« Direction … : "
          "suivez-moi ! », « Nous sommes arrivés : … », « Je retourne à l'accueil. »), plus tard le chatbot, et "
          "« Essayer » dans l'Atelier. Une phrase à la fois : une phrase **haute** coupe celle qui est dite, une "
          "phrase de **sécurité** coupe et vide la file ; jamais deux sons en même temps."),
    ("table", {
        "legende": "Les trois sorties de la voix",
        "entetes": ["Sortie", "Comment", "Où l'entendre"],
        "largeurs": [3.2, 9.4, 4.0],
        "taille": 8.5,
        "premiere_col_gras": True,
        "lignes": [
            ["Haut-parleur du robot (`robot`)", "Piper, sur le PC, fabrique la phrase (voix française Siwis ou Tom, "
             "0,1 s environ par phrase) ; le son est ramené à 16 000 Hz, mono, 16 bits, et envoyé au service voice "
             "du robot en morceaux de 3 s au plus (ordre 1003), un par seconde ; 1004 coupe ; 1005 et 1006 lisent et "
             "règlent le volume", "le robot"],
            ["Borne (`borne`)", "le même son, en fichier WAV, joué par la page de la borne ; c'est la sortie de la "
             "simulation", "la tablette"],
            ["Synthèse du robot (`robot_tts`)", "le texte envoyé à la synthèse intégrée d'Unitree (ordre 1001) ; "
             "réglée sur l'anglais en attendant de savoir si elle parle français", "le robot"],
        ],
    }),
    ("p", "Le nœud n'envoie que ces cinq ordres (jamais le micro, jamais la lumière), chacun vérifié avant de "
          "partir. Le faux G1 les vérifie aussi (format, morceaux, flux mêlés, trop rapides) et compte les écarts : "
          "le critère 40 compare la durée reçue à celle du fichier de Piper, à 5 % près. Chaque phrase dite par "
          "Piper est gardée en WAV (les 200 dernières) : c'est la trace de ce que le robot a dit."),

    ("h2", "Ce qui reste à vérifier avec le robot"),
    ("puces", [
        "**Vérifier le robot** sur le vrai G1 : la réponse de robot_state à 1003 et 1001 (noms des services, "
        "statut 0 = actif), le temps de démarrage de `unitree_slam`, `nmcli connection up robot-g1` sans sudo, la "
        "batterie lue sur `/lf/bmsstate`.",
        "**La boîte noire** pendant une vraie navigation : son coût, le journal du conteneur gardé avant « Arrêter », "
        "un rapport sans « mouvement sans demande » quand le robot debout oscille sur place.",
        "**La voix** : le son du PC joué par le haut-parleur du robot (net ? délai entre deux phrases ? 1004 coupe-t-il "
        "tout de suite ?), le volume ; la synthèse du robot parle-t-elle français ?",
        "**La borne** sur une vraie tablette par le Wi-Fi (adresse, son), et **une démo** avec un vrai visiteur, la "
        "caméra et l'accompagnement.",
    ]),
    ("encadre", "À retenir",
     ["Une séance avec le robot commence maintenant par **Vérifier le robot** (et ses services démarrés en un "
      "clic), est enregistrée de bout en bout par la **boîte noire**, et se termine par un **rapport** et un "
      "`.zip` (`docs/tutoriel-seance-2.md`).",
      "- La **démo d'accueil** marche en simulation : trois visiteurs de suite, trois visites réussies (critère "
      "41) ; un ARRÊT, un blocage, un robot assis, un pont tué ou le pilotage la mettent en pause, et rien ne "
      "repart seul (critère 42).",
      "- Tout a été vérifié sans robot (critères 37 à 42, et deux revues) : la séance n° 2 dira ce que vaut le "
      "vrai G1."], "retenir"),
]
