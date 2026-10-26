# Séance avec le robot : valider le pont, le repérage et le conteneur (1 h 30)

Cette séance valide sur le vrai G1 les trois pièces préparées sans robot (section 10 du plan) :

1. **le pont** `/cmd_vel` → ordre de marche 7105 (`g1_bridge`) ;
2. **le repérage** au démarrage : commande 1804 au service `slam_operate`, puis relais de
   `/unitree/slam_relocation/odom` vers les repères de Nav2 (`odom_vers_tf`) ;
3. **le conteneur** ROS 2 Humble sur le Jetson (`g1-jetson`).

Elle finit par un premier trajet court de la navigation de niveau 2 (Nav2, pont, repérage
d'Unitree), à vitesse réduite. Tout a été répété dans Gazebo contre un faux G1 (critères 16 à 20,
`tests_e2e/tout.sh 16 17 18 19 20`). Ce que la simulation ne peut pas garantir : que le robot
comprenne nos messages (leurs formats viennent d'un projet tiers), et comment il réagit vraiment.
C'est ce qu'on vérifie ici, dans cet ordre : le pont au portique, puis le repérage, puis le trajet.

## Les règles de la séance

- **Deux personnes.** L'une tient la télécommande officielle pendant toute la séance, le doigt
  prêt : c'est l'arrêt d'urgence (mode amortissement). L'autre est au PC.
- **Le portique** pour tout le début : robot accroché, sangle lâche, pieds au sol.
- **Vitesses réduites** : 0,1 m/s au portique, 0,2 m/s pour le premier trajet.
- **On arrête la séance** (télécommande, puis amortissement) si :
  - la télécommande ne reprend pas la main pendant que le pont envoie (étape 1.7) ;
  - le robot ne s'arrête pas seul quand le pont est tué (étape 1.6) ;
  - un mouvement part sans qu'on l'ait demandé.
- **On note tout** dans la feuille de résultats (dernière section). Chaque point qui échoue est
  noté avec ce qu'on a vu, puis on passe au suivant si c'est sans danger.

Matériel : robot chargé, télécommande, câble Ethernet de 2 à 3 m, PC chargé, rouleau de ruban
adhésif (le point principal au sol : une croix et une flèche), mètre ruban, une zone dégagée de
5 m × 3 m au moins.

Les commandes se tapent dans des terminaux ouverts après l'installation (Ctrl+Alt+T). Dans
**chaque** terminal qui parle au robot, tapez d'abord `source ~/robot-g1/setup/robot.sh` : il
relie ROS 2 au câble (port eno2, domaine 0) et doit dire « le robot répond ».

## La veille, sans robot (20 min, hors séance)

```bash
cd ~/robot-g1
tests_e2e/tout.sh 16 17 18 19 20     # le conteneur, le pont, le repérage, le niveau 2, la sécurité : « 5 / 5 »
g1-jetson construire                 # l'image du Jetson (arm64), 4 min la première fois, 30 s ensuite
g1-lieu creer seance --nom "Séance robot"     # le lieu de la séance (s'il n'existe pas déjà)
```

Préparez une feuille de notes : `docs/releves/seance_<date>.md`, avec le tableau de la dernière
section.

## 0. Au portique : brancher et regarder (0 h 00 → 0 h 10)

1. Robot accroché au portique, allumé. Attendez la fin de son démarrage (environ 1 min).
2. Câble Ethernet entre le PC et le robot. Terminal A :

   ```bash
   source ~/robot-g1/setup/robot.sh      # « ROS 2 relié au robot par eno2 … : le robot répond. »
   g1-etat                               # « Connecté » (Ctrl+C pour quitter)
   ros2 topic list --no-daemon | grep -E 'api/sport|slam|odom_pelvis|sportmodestate'
   ```

   À noter : les sujets `/api/sport/request`, `/api/sport/response`, `/api/slam_operate/*`,
   `/state_estimator/odom_pelvis`, `/lf/sportmodestate` sont-ils là ?
3. La fréquence et le repère de l'odométrie du robot (point 16 du plan 10.9) :

   ```bash
   ros2 topic hz /state_estimator/odom_pelvis          # 5 s, puis Ctrl+C
   ros2 topic echo --once /state_estimator/odom_pelvis --field header
   ros2 topic echo --once /state_estimator/odom_pelvis --field child_frame_id
   ```

## 1. Le pont au portique, à vitesse réduite (0 h 10 → 0 h 35)

Le pont tourne d'abord **sur le PC**, au câble, sans repérage exigé et avec des plafonds 4 fois
plus bas que ceux du contrat (0,1 m/s au lieu de 0,4).

1. **Robot en mode marche** avec la télécommande, au portique, pieds au sol.
2. **Terminal A, le pont** :

   ```bash
   ros2 run g1_bridge pont --ros-args -p exiger_reperage:=false -p vx_max:=0.1 -p vy_max:=0.05 -p wz_max:=0.15
   ```

   **Terminal B, l'état du pont** (`source ~/robot-g1/setup/robot.sh` d'abord) :

   ```bash
   ros2 topic echo /pont/etat --field data
   ```

   **Terminal C, les réponses du robot** (`source ~/robot-g1/setup/robot.sh` d'abord) :

   ```bash
   ros2 topic echo /api/sport/response
   ```

3. **Le format 7105 est-il accepté ?** Au lancement, le pont envoie un arrêt (7105 avec
   `{"velocity": [0.0, 0.0, 0.0], "duration": 1.0}`) pour vérifier le lien.
   - Attendu : une réponse dans le terminal C, avec notre `identity.id`, `api_id: 7105` et
     `status.code: 0` ; le pont passe à `pret`.
   - À noter : le contenu exact de la réponse (`status.code`, `data`).
   - Si le pont reste `robot_muet` : `ros2 topic info -v /api/sport/request` (le robot est-il
     abonné ?). Notez, arrêtez le pont (Ctrl+C) et passez à l'étape 2 : le reste du pont ne peut
     pas se vérifier.
4. **Premier pas en avant**, 2 s à 0,1 m/s. Terminal D (`source ~/robot-g1/setup/robot.sh`) :

   ```bash
   ros2 topic pub -r 10 -t 20 /cmd_vel geometry_msgs/msg/Twist "{linear: {x: 0.1}}"
   ```

   Attendu : le robot marche doucement vers l'avant pendant 2 s, puis s'arrête de lui-même environ
   0,3 s après la fin (le pont envoie l'arrêt). À noter : le délai entre la commande et le premier
   pas (latence), un mouvement saccadé ou non.
5. **Les autres axes**, chacun 2 s :

   ```bash
   ros2 topic pub -r 10 -t 20 /cmd_vel geometry_msgs/msg/Twist "{angular: {z: 0.15}}"    # tourne à gauche
   ros2 topic pub -r 10 -t 20 /cmd_vel geometry_msgs/msg/Twist "{linear: {y: 0.05}}"     # pas de côté, à gauche
   ```

6. **Le robot s'arrête seul si le pont meurt** (chaque ordre ne vaut que 0,5 s). Terminal D :
   une marche de 10 s ; pendant qu'il marche, terminal E : tuer le pont.

   ```bash
   ros2 topic pub -r 10 -t 100 /cmd_vel geometry_msgs/msg/Twist "{linear: {x: 0.1}}"   # terminal D
   pkill -9 -f lib/g1_bridge/pont                                                      # terminal E, après 3 s
   ```

   Attendu : arrêt moins d'une seconde après le `pkill`. **Si le robot continue : télécommande,
   amortissement, fin de la séance** (le robot ne s'arrête pas seul à la fin de la consigne).
   Relancez ensuite le pont (étape 2).
7. **La télécommande reste prioritaire.** Une marche de 10 s (comme ci-dessus), et pendant ce
   temps la personne à la télécommande l'arrête avec elle (puis amortissement si besoin).
   Attendu : la télécommande gagne tout de suite, même si le pont envoie encore. **C'est la
   condition pour continuer.**
8. **Un refus.** Robot en amortissement (ou assis), une commande de 2 s : le robot ne bouge pas.
   À noter : le code de la réponse (7301 ?) et le message de `/pont/etat` (état `refus`). Remettez
   ensuite le robot en mode marche.
9. **Arrêts du projet.** Pendant une marche de 10 s :

   ```bash
   ros2 topic pub --once /guide/stop std_msgs/msg/Empty "{}"      # arrêt, puis /cmd_vel ignoré 1 s
   ros2 topic pub --once --qos-durability transient_local --qos-reliability reliable /pont/arret std_msgs/msg/Bool "{data: true}"
   ```

   Attendu : avec `/guide/stop`, arrêt net, puis le robot repart 1 s plus tard (la marche de 10 s
   continue d'envoyer `/cmd_vel`). Avec le verrou, arrêt net, puis plus rien ne bouge
   (`arret_verrouille`) jusqu'à la même commande avec `{data: false}`, puis la marche reprend.
10. Fin de l'étape : Ctrl+C dans le terminal A (le pont envoie un arrêt en quittant), robot en
    amortissement sur le portique.

## 2. Le conteneur sur le Jetson (0 h 35 → 0 h 50)

Robot toujours au portique, immobile. Détails et dépannage : `docs/jetson.md`.

```bash
ls ~/.ssh/id_*.pub || ssh-keygen -t ed25519      # une clé ssh, si le PC n'en a pas (Entrée 3 fois)
ssh-copy-id unitree@192.168.123.164              # une seule fois ; mot de passe : 123
g1-jetson verifier                               # chaque ligne : OK, PROBLÈME ou info
g1-jetson envoyer                                # 2 à 5 min : copie et charge l'image sur le Jetson
g1-jetson verifier                               # la dernière ligne doit voir /state_estimator/odom_pelvis et /lf/sportmodestate
g1-jetson demarrer --veille
g1-jetson etat                                   # « running »
g1-jetson arreter
```

À noter : le nom de l'interface du Jetson et son adresse, la place libre, la mémoire, l'écart
d'horloge affiché, la durée de `envoyer`. Si `verifier` ne voit pas les sujets du robot depuis le
conteneur, la navigation ne pourra pas tourner sur le Jetson : on fera les étapes 3 et 4 avec la
navigation sur le PC, au câble (voir « Si le conteneur ne marche pas » à la fin).

## 3. Le repérage 1804 (0 h 50 → 1 h 15)

Le robot quitte le portique. La carte du robot est celle d'un scan : il en faut un de la zone de
l'essai. Depuis la vague 4, on pose le robot sur le **point principal** du lieu (l'accueil, une
étoile et une flèche dans l'onglet Salles) avant « Repérer le robot ». Pour cette première séance,
le point principal est au point de départ du scan : c'est le plus simple à vérifier.

1. **Le point principal au sol** : une croix au ruban adhésif au sol, au bord de la zone dégagée,
   et une flèche qui montre la direction où le robot regardera (au moins 4 m libres devant lui).
2. **Le petit scan** (10 min), si le lieu `seance` n'a pas encore de scan de cette zone. Dans
   l'appli Unitree, les services `unitree_slam` et `lidar_driver` sont activés. Robot sur la
   croix, tourné dans le sens de la flèche, en mode marche.

   ```bash
   g1-atelier            # dans le terminal A (robot.sh chargé) ; ouvre l'Atelier
   ```

   Onglet **Lieux** : choisir « Séance robot ». Onglet **Scan** : choisir **Robot**, cliquer sur
   **Scan** et confirmer. Promenez le robot à la télécommande, lentement, dans toute la zone
   (3 à 5 min), la personne du PC derrière avec le câble lâche. Revenez **sur la croix, dans le
   sens de la flèche**, puis **Fin**. Dans la revue : **Utiliser cette carte pour l'étage**.
   À noter : le nom de la carte enregistrée sur le robot (`carte_unitree` dans `lieux/seance/lieu.yaml`).
3. **L'accueil (le point principal) sur la croix et un but à 3 m devant**. Le repère de la carte
   du scan a son origine à la croix, l'axe x dans le sens de la flèche (à vérifier : c'est ce que
   suppose le relais). La salle `accueil` devient le point principal du lieu (principal implicite).
   Dans un autre terminal, l'Atelier tournant :

   ```bash
   curl -s -X PUT "http://localhost:8000/api/lieux/seance/salles?synchroniser=true" -H 'Content-Type: application/json' \
     -d '[{"id":"accueil","nom":"Accueil","alias":[],"etage":"rdc","pose":{"x":0,"y":0,"theta":0},"phrase_arrivee":""},
          {"id":"essai_3m","nom":"Essai à 3 m","alias":[],"etage":"rdc","pose":{"x":3,"y":0,"theta":0},"phrase_arrivee":""}]'
   curl -s -X PUT http://localhost:8000/api/lieux/seance/itineraires -H 'Content-Type: application/json' \
     -d '{"noeuds":{"accueil":{"etage":"rdc","x":0,"y":0},"essai_3m":{"etage":"rdc","x":3,"y":0}},"couloirs":[["accueil","essai_3m"]]}'
   ```

   Onglet **Carte** : le point (3 ; 0) doit être dans le blanc (libre), au milieu de la zone
   dégagée. Sinon, déplacez `essai_3m` dans l'onglet **Salles**.
4. **Navigation sur le robot, à vitesse réduite.** Fermez l'Atelier (Ctrl+C dans le terminal A),
   puis relancez-le avec la vitesse maximale du premier trajet :

   ```bash
   G1_VITESSE_MAX=0.2 g1-atelier
   ```

   Onglet **Simulation** : mode **Robot**, puis **Lancer sur le robot** et confirmer. L'Atelier
   lance `g1-jetson demarrer --lieu seance --etage rdc` (le lieu est copié sur le Jetson) ; la
   ligne de démarrage doit dire « vitesse max 0.2 m/s ». Attendu : « Non repéré » dans le panneau
   Repérage, et la pastille du pont en attente du repérage.
5. **Robot sur la croix, dans le sens de la flèche, en mode marche.** Terminal C :

   ```bash
   ros2 topic echo /api/slam_operate/response
   ```

   Puis **Repérer le robot**. Attendu, en moins de 20 s : « Repéré », avec la précision. À noter :
   le texte de la réponse (`succeed`, `errorCode`, `info` ?), la durée du repérage. Si c'est un
   échec, notez le message affiché, puis vérifiez : `ros2 topic echo --once /slam_info`, et
   `g1-jetson journal | tail -n 30`.
6. **Ce que publie la relocalisation** (points 14 et 15 du plan 10.9) :

   ```bash
   ros2 topic hz /unitree/slam_relocation/odom                               # 5 s
   ros2 topic echo --once /unitree/slam_relocation/odom --field header
   ros2 topic echo --once /unitree/slam_relocation/odom --field child_frame_id
   ros2 topic echo --once /unitree/slam_relocation/odom --field pose.covariance
   ros2 topic hz /unitree/slam_relocation/points                             # 5 s
   ros2 topic echo --once /unitree/slam_relocation/points --field header
   ```

7. **La précision**, à la télécommande (le pont n'envoie rien tant que personne ne demande de
   mouvement) : avancez le robot d'environ 2 m, puis tournez-le d'un quart de tour. À chaque arrêt,
   comparez la position affichée dans l'Atelier (Simulation, panneau Repérage) à la mesure au mètre
   ruban depuis la croix. Trois mesures. Attendu : moins de 10 cm d'écart.
8. **Hors du point principal** (si le temps le permet) : robot à 0,5 m de la croix et tourné de
   20°, « Repérer le robot » sans rien changer : accepté ou refusé, à noter. Puis « Le robot n'est
   pas sur le point principal » : cliquer sa position sur la carte, glisser vers son orientation,
   et repérer.

## 4. Premier trajet court (1 h 15 → 1 h 25)

La navigation tourne dans le conteneur du Jetson, plafonnée à 0,2 m/s (`G1_VITESSE_MAX`).

1. Robot repéré, près de la croix. La personne à la télécommande se tient à côté du robot ; celle
   du PC suit avec le câble lâche.
2. Onglet **Simulation** : **Y aller** vers « Essai à 3 m ». Attendu : `en_route`, le robot marche
   droit vers le but à 0,2 m/s au plus, puis `arrive`.
3. Pendant un deuxième essai (Y aller « Accueil »), cliquez une fois sur **ARRÊT** à mi-chemin :
   le robot s'arrête net. Puis **Y aller** « Accueil » de nouveau.
4. À l'arrivée, mesurez au mètre ruban l'écart entre le robot et le but (la croix pour
   l'accueil). Attendu : moins de 30 cm.
5. Une fois : **Bloquer le robot**, puis **Y aller** : il ne doit pas bouger. **Débloquer**.

## 5. Fin (1 h 25 → 1 h 30)

```bash
g1-jetson journal > ~/robot-g1/docs/releves/seance_$(date +%F)_conteneur.log     # avant l'arrêt
```

Puis, dans l'Atelier : **Arrêter la navigation du robot** (le pont envoie un arrêt, le conteneur
s'arrête et se retire). Robot en amortissement, puis éteint. Complétez la feuille de résultats.

## 6. Séance suivante : le pilotage (vague 4, environ 1 h, au portique)

But : vérifier sur le vrai G1 ce que l'onglet **Pilotage** envoie (section 11.5 du plan). Tout a
été essayé contre le faux G1 seulement (critères 28 et 29). **Au portique, télécommande en main,
une personne qui tient le robot** ; jamais les danses 401, 402, 403.

Avant de commencer, deux relevés (2 min) :

- **Version du micrologiciel** : dans l'appli Unitree Explore, réglages du robot, « version » (la
  source des danses parle du micrologiciel 1.5.6 ; noter la vôtre dans la feuille, ligne 6.0) ;
- **Le Jetson a-t-il du Wi-Fi ?** Au câble, `ssh unitree@192.168.123.164 'ip -br addr; nmcli
  device status'` (mot de passe 123) : une interface `wlan0` (ou `wlP…`) avec une adresse ? Si oui,
  noter l'adresse : c'est elle qui servira pour le joystick par le Wi-Fi (étape 4). Si non, le
  pilotage se fait au câble (`http://192.168.123.164:8010`), et le Wi-Fi est à ajouter (clé USB
  ou carte M.2) avant d'utiliser l'onglet Pilotage depuis une tablette.

Préparation (PC, au câble) :

```bash
source ~/robot-g1/setup/robot.sh
G1_VITESSE_MAX=0.2 g1-jetson demarrer --veille            # le nœud pilotage seul (G1_PILOTAGE=1), sans navigation
export G1_PILOTAGE_URL=http://192.168.123.164:8010 G1_PILOTAGE_JETON=$(cat ~/robot-g1/opt/jetson/jeton_pilotage)
g1-pilotage etat                                             # robot_repond : true ; noter fsm
G1_PILOTAGE_URL=$G1_PILOTAGE_URL g1-atelier                  # onglet Pilotage
```

1. **Lecture du mode (7001)** : `g1-pilotage etat` donne `fsm`. Noter la valeur robot debout, assis,
   accroupi, amorti. Si elle n'est jamais 801 debout, corriger `FSM_MARCHE` (danses et
   chorégraphies l'exigent).
2. **Postures** (« Prendre la main », puis les boutons) : 500, 706, 702, 3 depuis le conteneur, sans
   bail ; temps de chaque transition ; **la télécommande reste prioritaire et arrête tout**.
3. **Amortir (1) et couple nul (0)** : seulement robot tenu au portique ; case « robot au portique »
   et confirmation double.
4. **Joystick** (plafonds 0,2 m/s), d'abord au câble, puis **par le Wi-Fi** (si le Jetson en a :
   relancer l'Atelier avec `G1_PILOTAGE_URL=http://<adresse Wi-Fi du Jetson>:8010`, PC sur le même
   réseau Wi-Fi) : l'arrêt seul 0,5 s après le dernier ordre — fermer la page en marche ; puis,
   **pendant une marche lente** (0,1 m/s, robot au portique, pieds au sol), **couper le Wi-Fi du
   PC** : le robot doit s'arrêter seul en moins de 0,6 s (le conteneur ne dépend pas du PC).
   Noter la latence par le Wi-Fi (appui → premier pas) et les plafonds (1,0 demandé → 0,2).
5. **Gestes** : `g1-pilotage geste 26`. Si le robot répond 3204 (paramètres), le format est
   `{"data": n}` (SDK Python) et non `{"action_id": n}` (SDK C++) : corriger
   `atelier.lieu.pilotage.parametre_geste`. Noter les codes réels de 7400, 7401, 7402, 7404 ; le
   geste 13 ; la liste 7107 (format) ; les gestes appris (7108).
6. **Voix et LED** : `g1-pilotage dire "Bonjour"` (langue de la synthèse ? `speaker_id` ?),
   `g1-pilotage volume 50`, `g1-pilotage led 255 0 128` (format `{"R","G","B"}`).
7. **Danses** (pieds au sol, 3 m libres, robot tenu au portique d'abord) : `g1-pilotage danses
   --lire` (format exact de 7100, numéros présents sur ce micrologiciel, durées) ; puis 604 :
   `g1-pilotage danse 604 --zone-libre` ; durée réelle, retour seul en 801 (lu par 7001) ;
   ce que fait un 7105 ou un autre 7101 pendant la danse ; **ce qui interrompt une danse**
   (télécommande ? StopMove ?).
8. **rt/arm_sdk** : d'abord une chorégraphie lente, sans pas (onglet « Mes chorégraphies » :
   « Nouvelle », une seule pose coudes à 0,5 rad, vitesse de lecture 1/2), au portique ; vérifier
   le poids dans `motor_cmd[29].q`, les rampes, la taille tenue (12 à 14), les gains (kp 60,
   kd 1,5), le `mode` des moteurs (0 comme l'exemple d'Unitree, ou 1 ?), le CRC (non calculé, comme
   l'exemple ROS 2), la vitesse réelle des bras et la reprise par le contrôleur à la fin. Puis
   `exemple_kpop` à la vitesse de lecture 1/2, robot posé au sol, zone libre.
9. **Batterie** : `/lf/bmsstate` (unitree_hg/BmsState, champ `soc`) existe-t-il sur le G1 ?
10. **Musique par le haut-parleur du robot** (1003, flux PCM) : pas encore prise en charge.
11. **Personnalité** (onglet Personnalités, lieu de la séance avec un `personnalites.yaml` partant
    de l'exemple) : « Rendre active » « Accueillant » : la LED passe au bleu (0, 120, 255) sans
    prendre la main ; « Discret » : gris. Puis, la main rendue au guide, guide au repos :
    `ros2 topic pub --once /robot/geste std_msgs/msg/String "{data: '{\"geste\": 26, \"source\": \"atelier\"}'}"`
    → grand salut, puis bras relâchés 5 s après ; le même message pendant que l'onglet a la main :
    ignoré (journal du conteneur : « Geste demandé ignoré »).
12. **Vidéo de la tête dans la Vue du robot** (onglet Pilotage, « Commandes », panneau « Caméra de
    la tête », bouton « Voir » ; le conteneur doit venir de la nouvelle image, `g1-jetson
    demarrer`) :
    - le service existe-t-il ? `ros2 topic list | grep videohub` dans le conteneur
      (`/api/videohub/request` et `/api/videohub/response`) ; sinon noter ce qui existe
      (`/frontvideostream` seulement ? caméra RealSense de la tête ?) ;
    - une image arrive : `curl -s -H "X-Jeton: $(cat ~/robot-g1/opt/jetson/jeton_pilotage)"
      http://<Jetson>:8010/camera -o tete.jpg` puis ouvrir `tete.jpg` (le nœud demande
      GetImageSample, api 1001, et attend le JPEG dans le champ `binary` de la réponse) ; si la
      réponse est vide, refusée (code noté) ou n'est pas un JPEG, noter le code et le premier
      octet ; si rien ne revient en 1 s, le message de la page le dit ;
    - le débit : la page demande une image toutes les 0,35 s au plus (5 par seconde au plus au
      robot) ; noter la taille d'une image, le nombre d'images par seconde vues sur la tablette,
      au câble puis **par le Wi-Fi**, et si le joystick reste vif pendant que la caméra tourne
      (latence appui → premier pas, caméra allumée puis coupée) ;
    - « Couper », onglet fermé, autre sous-onglet : plus aucune demande (journal du conteneur : pas
      de requêtes videohub) ;
    - la vue 3D suit-elle le robot : posture lue (7001) après chaque changement, geste montré en
      même temps que le vrai (l'aperçu des gestes est approché : noter ceux qui ne ressemblent pas
      du tout), danse avec sa barre de progression, chorégraphie aux mêmes poses que le vrai robot.

## 7. Point principal, passants et accompagnement (vague 4, environ 45 min, au sol)

But : vérifier en vrai ce que les critères 21 à 27 ont vérifié dans Gazebo (sections 11.2 à 11.4
du plan). Robot au sol, navigation sur le Jetson (`G1_VITESSE_MAX=0.2 g1-atelier`, mode Robot),
télécommande en main, deux ou trois volontaires.

1. **Robot posé sur le point principal** : principal à la croix, robot dans le sens de la flèche,
   « Repérer le robot » : 1804 reçoit (0, 0, 0). Puis déplacez le principal **loin de l'origine du
   scan et tourné** (onglet Salles : la salle « Essai à 3 m », « Faire de cette salle le point
   principal », flèche tournée vers la croix, « Enregistrer les salles ») ; relancez la navigation
   du robot, posez le robot sur ce nouveau point, dans le sens de sa flèche, et « Repérer le
   robot » : « Repéré », écart au mètre ruban (moins de 10 cm), durée.
2. **Retour au point principal** : « Y aller » vers l'autre salle ; à l'arrivée, attendre 15 s : le
   robot revient seul et se tourne dans le sens de la flèche (écart de cap noté, 10° demandés).
3. **Accompagnement** (panneau « Comportement du guide », « Accompagner un visiteur ») : un
   volontaire derrière le robot à 1 m ; le robot le choisit (événement `depart`, pas `seul`) ;
   le volontaire traîne à 2,5 m : le robot ralentit ; à plus de 3,5 m : il l'attend ; il revient :
   « Vous voilà ! Continuons. ». Noter les distances ressenties, la vitesse du robot accompagné.
4. **Passant qui bouche** : deux volontaires immobiles en travers de la zone, sur le chemin : le
   robot s'arrête vers 2,5 m (« Pardon, puis-je passer ? »), attend ; ils s'écartent : il repart
   (« Merci ! »). Puis un volontaire immobile sur le côté : le robot passe à côté sans s'arrêter
   (distance bord à bord notée, 0,20 m au moins).
5. **Collision Monitor et obstacles bas** (robot immobile, puis à 0,1 m/s) : dans RViz
   (`collision_ralentir`, `collision_ralentir_pres`, `collision_arret`), aucun point du robot
   lui-même (bras, mains) dans les zones ; une valise et un sac au sol sont vus (carte locale) ;
   le robot ralentit à moins de 1 m devant, s'arrête à 0,4 m.
6. **Robot perdu** : couper la relocalisation (couvrir le LiDAR n'est pas sûr : plutôt une
   pièce sans repères, ou attendre une perte réelle) ; noter le message et le délai.

## Si le conteneur ne marche pas

Le repérage et le trajet se font alors avec la navigation **sur le PC**, au câble : la personne du
PC suit le robot de près. Dans un terminal avec `robot.sh` :

```bash
g1-guide navigation --lieu seance --etage rdc --vitesse-max 0.2      # Nav2, relais, pont, guide (sans --simu : vrai robot)
```

Les boutons « Repérer le robot » et « Y aller » de l'Atelier ne servent qu'à la navigation que
l'Atelier a lancée lui-même. Avec la navigation lancée à la main, on passe donc par les commandes,
chacune dans un terminal avec `robot.sh` :

```bash
ros2 topic pub --once /reperage/demander std_msgs/msg/String "{data: '{\"id\": \"seance-1\", \"x\": 0, \"y\": 0, \"theta\": 0}'}"   # repérer, robot sur le point principal (0 ; 0 ; 0)
ros2 topic echo /reperage/etat --field data                                                    # attendu : "etat": "repere"
g1-guide aller essai_3m                                                                        # le trajet court
g1-guide stop                                                                                  # arrêt
```

## Feuille de résultats

| N° | Point vérifié | Attendu | Constaté | OK ? |
|---|---|---|---|---|
| 0.2 | Sujets du robot vus du PC (domaine 0, eno2) | `/api/sport/*`, `/api/slam_operate/*`, `/state_estimator/odom_pelvis`, `/lf/sportmodestate` | | |
| 0.3 | `/state_estimator/odom_pelvis` | fréquence, `frame_id`, `child_frame_id` | | |
| 1.3 | 7105 accepté en ROS 2 (sans bail, priorité 0) | réponse avec notre `identity.id`, code 0 ; pont `pret` | | |
| 1.4 | Marche à 0,1 m/s, arrêt après la consigne | pas nets, arrêt 0,3 s après ; latence notée | | |
| 1.5 | Rotation 0,15 rad/s, pas de côté 0,05 m/s | dans le bon sens | | |
| 1.6 | Pont tué (`kill -9`) en marche | arrêt seul en moins de 1 s | | |
| 1.7 | Télécommande prioritaire pendant que le pont envoie | la télécommande gagne | | |
| 1.8 | Refus hors du mode marche | code (7301 ?), message du pont | | |
| 1.9 | `/guide/stop`, verrou `/pont/arret` | arrêt net ; immobile sous verrou | | |
| 2 | `g1-jetson verifier`, `envoyer`, `demarrer --veille` | OK ; sujets du robot vus du conteneur ; durée de `envoyer` | | |
| 3.2 | Petit scan (1801, 1802) | carte cohérente, `carte_unitree` notée | | |
| 3.5 | 1804 en ROS 2 sur `/api/slam_operate/request` | « Repéré » en moins de 20 s ; texte de la réponse | | |
| 3.6 | `/unitree/slam_relocation/odom` et `/points` | fréquence, repères, covariance | | |
| 3.7 | Précision du repérage, 3 mesures | moins de 10 cm | | |
| 3.8 | Hors du point principal (0,5 m, 20°) | accepté ou refusé | | |
| 4.2 | Y aller « Essai à 3 m » à 0,2 m/s | `arrive` | | |
| 4.3 | ARRÊT à mi-chemin | arrêt net | | |
| 4.4 | Écart à l'arrivée | moins de 30 cm | | |
| 4.5 | Bloquer, puis Y aller | immobile | | |
| 5 | Arrêt de la navigation | arrêt propre, conteneur retiré | | |
| 6.0 | Micrologiciel (appli) ; Wi-Fi du Jetson | version notée ; interface et adresse Wi-Fi, ou « pas de Wi-Fi » | | |
| 6.1 | 7001 (mode) debout, assis, accroupi, amorti | 801 debout ; valeurs notées | | |
| 6.2 | Postures 500, 706, 702, 3 depuis le conteneur | acceptées ; durées ; télécommande prioritaire | | |
| 6.3 | Amortir, couple nul (robot tenu) | confirmation double ; robot tenu | | |
| 6.4 | Joystick : page fermée, Wi-Fi coupé en marche | arrêt seul en 0,5 s ; latence notée | | |
| 6.4b | Joystick par le Wi-Fi ; Wi-Fi coupé pendant une marche lente | arrêt seul en moins de 0,6 s ; latence | | |
| 6.5 | Gestes : format `action_id` ou `data`, codes 7400 à 7404, geste 13 | code 0 ; codes notés | | |
| 6.6 | TTS, volume, LED | langue, `speaker_id`, couleur | | |
| 6.7 | Danses : 7100, 550604, retour en 801, interruption | liste notée ; durée ; ce qui l'interrompt | | |
| 6.8 | rt/arm_sdk : chorégraphie lente, puis exemple_kpop à 1/2 | poids, rampes, taille tenue, gains, `mode`, CRC | | |
| 6.9 | Batterie `/lf/bmsstate` | `soc` lu | | |
| 6.11 | LED de la personnalité ; geste demandé (`/robot/geste`) robot au repos | couleur ; salut puis bras relâchés | | |
| 6.12 | Vue du robot : vidéo de la tête (videohub 1001), au câble puis par le Wi-Fi ; vue 3D | image reçue ; taille, images par seconde, latence du joystick caméra allumée ; posture et gestes suivis | | |
| 7.1 | Repérage depuis le point principal, à la croix puis loin et tourné | « Repéré » ; écart < 10 cm ; durée | | |
| 7.2 | Retour seul au point principal | 15 s après l'arrivée ; cap à 10° près | | |
| 7.3 | Accompagnement d'un volontaire | `depart`, ralentit, attend, reprend | | |
| 7.4 | Passants : groupe qui bouche, personne sur le côté | attend puis repart ; 0,20 m bord à bord au moins | | |
| 7.5 | Collision Monitor, obstacles bas | pas de point du robot dans les zones ; valise vue | | |

Ce qui reste après la séance, si tout passe : les vitesses réelles de 0,1 à 0,4 m/s (régler les
plafonds et `nav2_g1_reel.yaml`), la position réelle du MID-360 (`base_link → lidar`), le nuage de
la relocalisation pour l'évitement d'obstacles, la perte de la relocalisation dans un couloir sans
repères, et l'option Wi-Fi. La liste complète est dans la section 10.9 du plan et dans le journal.
