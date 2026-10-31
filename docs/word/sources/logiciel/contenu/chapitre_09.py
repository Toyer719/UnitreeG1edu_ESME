"""Chapitre 9 : la sécurité."""

BLOCS = [
    ("h1", "La sécurité"),
    ("chapeau", "Un robot humanoïde qui marche au milieu de personnes : la sécurité passe avant tout. Elle "
                "est faite de plusieurs barrières indépendantes ; si l'une manque, les autres tiennent. "
                "Chacune est vérifiée par des tests sans robot, puis à vérifier sur le vrai robot."),
    ("schema", "securite", "Les barrières entre une demande de mouvement et les jambes du robot", 11.5, 15.0),

    ("h2", "Les barrières, une par une"),
    ("table", {
        "legende": "Les sécurités du logiciel",
        "entetes": ["Barrière", "Ce qu'elle fait", "Où dans le code", "Vérifiée par"],
        "largeurs": [3.0, 7.0, 3.9, 2.7],
        "taille": 8.5,
        "premiere_col_gras": True,
        "lignes": [
            ["Télécommande", "Elle parle directement au robot et reste prioritaire : le mode amortissement est "
             "l'arrêt d'urgence. Toujours en main pendant un essai.", "robot (Unitree)", "séance n° 2 (C5)"],
            ["ARRÊT unique", "Bouton de la barre d'outils ou touche Échap : arrête le guide, la téléopération et le "
             "pilotage en moins d'1 s, même si une partie ne répond pas ; en Réel et en répétition, pose aussi le "
             "verrou, jusqu'à « Débloquer ».", "`routes/arret.py`, `js/coque/arret.js`", "critère 36"],
            ["Verrou du pont", "`/pont/arret` à vrai : arrêt immédiat, plus aucun mouvement jusqu'au déverrouillage ; "
             "puis il faut une consigne neuve. Le message est gardé (transient_local) : un pont relancé le retrouve.",
             "`g1_bridge/logique.py`", "critères 17, 20, 36"],
            ["Plafonds", "Chaque vitesse est ramenée à 0,4 m/s en avant, 0,25 m/s de côté, 0,6 rad/s en rotation ; "
             "une valeur absurde (NaN, infini) donne un arrêt ; le pont refuse de démarrer avec des plafonds plus "
             "hauts. `G1_VITESSE_MAX=0.2` les baisse pour les premiers essais (jamais sous 0,2).",
             "`atelier/lieu/robot.py`, `config/pont.yaml`", "critères 17, 20, 34"],
            ["Vitesse minimale", "Le G1 ne fait aucun pas sous 0,2 m/s : une petite consigne est montée à 0,2 m/s "
             "dans la même direction (0,3 rad/s pour tourner sur place) ; une consigne minuscule (moins de "
             "0,05 m/s et 0,1 rad/s) devient un arrêt.", "`vitesse_effective` (`robot.py`)", "critère 34"],
            ["Homme mort", "Chaque ordre de marche ne vaut que 0,5 s : si le pont, le conteneur ou le Jetson "
             "s'arrête, le robot s'arrête seul. Le pont envoie un arrêt 0,3 s après la dernière consigne ; le "
             "joystick, 0,5 s après le dernier ordre ou dès que la page se ferme.", "`g1_bridge`, `g1_pilotage`",
             "critères 17, 20, 28"],
            ["Repérage exigé", "Pas de mouvement tant que le robot n'est pas repéré, ni quand le repérage est perdu "
             "(plus de position d'Unitree depuis 3 s).", "`g1_bridge`, `g1_nav/odom_vers_tf.py`", "critères 18, 20, 27"],
            ["Mode du robot", "Le pont lit le mode (ordre 7001) chaque seconde : assis, pas démarré ou en course, il "
             "n'envoie plus d'ordre de marche (état `pas_en_marche`) et dit quoi faire.", "`g1_bridge/logique.py`",
             "critère 34"],
            ["Robot muet", "Plus de réponse du robot depuis 1 s : état `robot_muet` ; la marche ne reprend qu'avec "
             "une consigne neuve.", "`g1_bridge`", "critère 20"],
            ["Un seul maître", "Le guide ou le pilotage, jamais les deux : `/mouvement/maitre`. L'ARRÊT est toujours "
             "permis.", "`g1_pilotage`, `guide.py`, `g1_bridge`", "critère 28"],
            ["Interdits et confirmations", "Ordres interdits (équilibre, hauteur, commande bas niveau, danses 401 "
             "à 403) refusés sans rien envoyer ; « robot au portique » pour amortir ou couper le couple ; « zone "
             "libre » pour danser.", "`atelier/lieu/pilotage.py`", "critères 28, 29"],
            ["Collision Monitor", "Nav2 ralentit de moitié près d'un obstacle (1 m devant, 0,7 m autour) et "
             "arrête à 0,4 m ; pas de marche arrière avec le vrai robot.", "`nav2_g1_reel.yaml`", "critères 23 à 25"],
            ["Conteneur", "Il ne redémarre jamais seul : on ne relance pas une navigation sans un humain.",
             "`docker/jetson.py` (`--restart no`)", "critère 16"],
        ],
    }),

    ("h2", "Les états du pont"),
    ("p", "Le pont publie son état sur `/pont/etat` deux fois par seconde ; l'Atelier l'affiche dans la "
          "pastille du robot et dans Naviguer. Quand plusieurs états valent à la fois, le premier de cette "
          "liste l'emporte :"),
    ("table", {
        "entetes": ["État", "Quand", "Le robot bouge-t-il ?"],
        "largeurs": [3.6, 9.4, 3.6],
        "taille": 9,
        "premiere_col_gras": True,
        "lignes": [
            ["arret_verrouille", "le verrou `/pont/arret` est posé (ARRÊT, Bloquer)", "non"],
            ["robot_muet", "le robot ne répond plus depuis 1 s", "s'il entend encore : ses ordres expirent en 0,5 s"],
            ["pas_en_marche", "le mode lu n'est pas la marche (assis, pas démarré, course)", "non"],
            ["refus", "le robot a refusé l'ordre (code ≠ 0), avec un message en français", "non"],
            ["pilotage", "le pilotage a la main : le pont ignore Nav2", "non (par le pont)"],
            ["attente_reperage", "le robot n'est pas repéré, ou le repérage est perdu", "non"],
            ["arret", "juste après `/guide/stop` : consignes ignorées pendant 1 s", "non"],
            ["demarrage", "au lancement, en attendant la première réponse du robot", "non"],
            ["en_mouvement", "une consigne fraîche est envoyée", "oui"],
            ["pret", "tout va bien, aucune consigne en cours", "non"],
        ],
    }),

    ("h2", "Ce que la séance n° 1 a appris (27/10)"),
    ("p", "La première séance avec le robot a validé le scan et l'ordre de marche 7105. Elle a surtout appris "
          "des choses qu'aucune simulation ne pouvait dire, et la vague 5 en a tiré les corrections :"),
    ("puces", [
        "**Le G1 ne fait aucun pas à 0,1 m/s** ; il marche à 0,2 m/s. Nav2 envoie souvent de petites vitesses "
        "(au démarrage, en approche) : d'où la **vitesse minimale** du pont.",
        "**Le mode lu par 7001 valait 0 (pas démarré), 3 (assis), 501 (marche) ou 802 (course)**, alors que le "
        "code supposait 801. Les modes de marche permis sont devenus 500, 501 et 801.",
        "**Assis, le robot accepte un ordre 7105 (code 0) mais ne bouge pas**, et le pont affichait "
        "`en_mouvement`. D'où la lecture du mode et l'état `pas_en_marche`.",
        "**D'autres programmes du robot répondent sur `/api/sport/response`** (des lectures 7001 en continu) : "
        "le pont ne compte que les réponses qui portent ses propres numéros.",
        "**Le scan échouait d'abord (erreur 3104, délai dépassé)** : les services `lidar_driver` et "
        "`unitree_slam` du robot étaient arrêtés. Ils ont été démarrés depuis le PC (service `robot_state`). "
        "Reste à savoir s'ils le restent après un redémarrage du robot.",
        "**Le port `eno2` perd son adresse à chaque débranchement** : `source ~/robot-g1/setup/robot.sh` la remet.",
        "Les vérifications de sécurité du pont (télécommande prioritaire, robot qui s'arrête seul quand le pont "
        "est tué, verrou) n'ont pas été notées : elles sont refaites en premier à la séance n° 2.",
    ]),
    ("encadre", "Les règles d'or d'une séance avec le robot",
     ["- Deux personnes : l'une tient la télécommande pendant toute la séance, l'autre est au PC.",
      "- Aucune simulation sur le PC pendant que le robot est branché (même domaine 0) : redémarrer le PC avant.",
      "- `source ~/robot-g1/setup/robot.sh` dans chaque terminal qui parle au robot (« le robot répond »).",
      "- Vitesses réduites : `G1_VITESSE_MAX=0.2` pour les premiers trajets ; d'abord au portique.",
      "- On arrête tout si la télécommande ne reprend pas la main, si le robot ne s'arrête pas seul quand on "
      "coupe le pont, ou si un mouvement part sans qu'on l'ait demandé."],
     "attention"),
]
