# Séance robot n° 2 : brouillon (date à fixer)

Ce tutoriel suit toute la journée, dans l'ordre :

1. la veille au soir ;
2. le matin, avant d'allumer le robot ;
3. la séance elle-même, en neuf étapes ;
4. ce qu'il faut me rapporter.

C'est un **brouillon** écrit après la vague 5 (31/10/2026), sans robot : les commandes ont été essayées
contre le faux G1, dans Gazebo, pas sur le vrai robot. Le déroulé de référence est dans
`docs/seance-robot.md` (sections 1 à 8) et la liste des points à vérifier dans la section 12.12 du plan.
La feuille de résultats est prête : `docs/releves/seance-2.md`.

**Ce qu'on a appris le 27/10 (séance n° 1)** :

- le scan marche (1801, puis 1802) ; la carte a été **retraitée le 31/10** par la nouvelle chaîne :
  plus de « damier », tous les nuages gardés, les traînées des passants retirées ;
- le robot **ne fait aucun pas à 0,1 m/s**, et marche à 0,2 m/s ;
- le mode lu par 7001 vaut 0 (pas démarré), 3 (assis), 501 (marche) ou 802 (course).

Depuis, le pont **monte toute petite consigne à 0,2 m/s** (0,3 rad/s en rotation), dans la même
direction, et **lit le mode du robot** : assis, pas démarré ou en course, il n'envoie plus d'ordre de
marche (état `pas_en_marche`, avec un message qui dit quoi faire).

**But de la séance**, dans l'ordre :

- **mesurer les vrais seuils** du robot (marche, pas de côté, rotation) et sa latence ;
- refaire les vérifications de sécurité du pont (C3 à C5 et C7 de la séance n° 1), avec le nouveau pont ;
- notre conteneur sur le Jetson (D), le repérage (E) et un premier trajet de 2,5 m (F) ;
- **la caméra See3CAM** sur le robot (G) et **la carte d'Unitree** (pendant E) ;
- **un nouveau scan**, plus lent, avec la nouvelle chaîne (H, si le temps le permet) ;
- **le pilotage depuis le mode 501 et une danse sûre**, d'abord au portique (P).

**Durée :** environ 2 h 30 avec le robot, plus 45 min la veille et 15 min le matin. Si le temps
manque, on garde l'ordre et on saute H.

**Ce qui ne change pas dans le robot :** comme à la séance n° 1. Le PC1 d'Unitree n'est jamais
touché ; sur le Jetson, seulement notre image Docker (environ 2 Go) et le dossier `~/robot-g1` ;
rien n'est installé dans Ubuntu, ROS ou les programmes d'Unitree ; notre conteneur ne redémarre
jamais tout seul. Pour tout retirer :
d'abord `g1-jetson arreter`, puis `ssh unitree@192.168.123.164 'docker rmi g1-jetson:arm64; rm -rf ~/robot-g1'`.

---

## Les règles d'or : à lire avant tout

1. **Deux personnes.**
   - La première tient la **télécommande officielle pendant toute la séance**. C'est l'arrêt
     d'urgence : en cas de doute, mode amortissement.
   - La seconde est au PC.
2. **Aucune simulation sur le PC pendant que le robot est branché** (même canal ROS, domaine 0). Le
   matin, **redémarre le PC**.
3. **`source ~/robot-g1/setup/robot.sh` dans CHAQUE terminal** qui parle au robot. Il doit dire
   « le robot répond ».
4. **Vitesses :** 0,2 m/s au plus, au portique comme au sol (`G1_VITESSE_MAX=0.2`). Les mesures de
   l'étape M vont jusqu'à 0,2 m/s et 0,4 rad/s, pendant 3 s au plus.
5. **Le bouton ARRÊT de l'Atelier** (ou la touche **Échap**, dès qu'une navigation ou le pilotage
   tourne, et toujours quand le robot bouge ou va repartir seul, par exemple pendant les 15 s avant le
   retour automatique, même si un menu est ouvert) arrête le guide, le pilotage et bloque le robot.
   **Il ne remplace pas la télécommande.**
6. **Danses :** jamais 401, 402 ni 403. La danse 604 d'abord **au portique, robot tenu**, 3 m libres.
7. **On note tout** dans `docs/releves/seance-2.md`. Un point qui échoue : on note ce qu'on a vu, puis
   on passe au suivant s'il n'y a pas de danger.

**On arrête la séance** (télécommande, puis amortissement) si l'une de ces choses arrive :

- la télécommande ne reprend pas la main pendant que notre pont envoie des ordres ;
- le robot ne s'arrête pas tout seul quand on coupe le pont ;
- un mouvement part sans qu'on l'ait demandé.

---

## 1. La veille au soir (environ 45 min)

### 1.1 Charger et préparer

- [ ] la batterie du robot, la télécommande, le PC (et son chargeur), le téléphone avec l'appli
  Unitree Explore ;
- [ ] le portique avec la sangle, le câble Ethernet (5 m ou plus), le ruban adhésif, le mètre ruban ;
- [ ] **la caméra See3CAM_11CUG**, son câble USB 3 et de quoi la fixer sur la poitrine du robot
  (support ou adhésif double face), **objectif à l'horizontale ou un peu vers le haut** ;
- [ ] quatre bouts de ruban au sol, à **1, 2, 3 et 4 m** devant l'endroit où sera le robot (étape G) ;
- [ ] la même zone que le 27/10 si possible : **la croix du point principal doit être au même endroit**
  (la carte du 27/10 a son origine sur la croix, et son axe x dans le sens de la flèche).

### 1.2 Sur le PC

Ouvre un terminal (Ctrl+Alt+T) et tape les commandes une par une.

```bash
cd ~/robot-g1

# 1) Arrêter tout ce qui tourne encore. Attendu : aucune ligne
pgrep -af "ign gazebo|ros2 launch|uvicorn"

# 2) Vérifier, en répétition, le conteneur, le pont, le repérage, le trajet, la sécurité,
#    la vitesse minimale et les modes, la caméra et l'ARRÊT (environ 15 min).
#    Attendu à la fin : « 8 / 8 »
tests_e2e/tout.sh 16 17 18 19 20 34 35 36

# 3) L'image du Jetson (avec la caméra, le nouveau pont et le pilotage). Déjà à jour : quelques
#    secondes ; sinon, 5 à 10 min.
g1-jetson construire

# 4) Le lieu de la séance : la carte retraitée du 27/10 (attendu : « Aucune erreur. » ;
#    les nœuds 1, 2 et 3 ne sont reliés à rien, c'est normal)
g1-lieu valider --lieu seance

# 5) Voir à blanc ce que fera l'envoi au Jetson (rien n'est envoyé)
G1_SLAM_FAUX=1 g1-jetson envoyer --dry-run
```

Si `tout.sh` n'affiche pas « 8 / 8 », envoie-moi la fin de l'affichage avant la séance.

### 1.3 La caméra, sur le PC d'abord (10 min)

Branche la See3CAM sur un port USB du PC.

```bash
ls /dev/v4l/by-id/          # attendu : usb-e-con_Systems_See3CAM_11CUG_…-video-index0
cd ~/robot-g1/ws/src/g1_equipe
G1_TEST_CAMERA=$(ls /dev/v4l/by-id/*See3CAM*-video-index0) python3 -m pytest -q -p no:cacheprovider test/test_camera_usb.py -k vraie
cd ~/robot-g1
g1-visiteurs --source $(ls /dev/v4l/by-id/*See3CAM*-video-index0) --fenetre --sans-ros
```

- Le test doit dire « 1 passed ».
- La fenêtre de `g1-visiteurs` montre l'image avec un cadre autour de toi et ta distance. L'image ne
  doit pas être noire (exposition automatique). Touche **q** pour quitter.

Puis débranche la caméra du PC et **fixe-la sur la poitrine du robot**, câble rangé le long du corps
(il ne doit pas gêner les bras). Elle sera branchée sur le Jetson à l'étape D.

---

## 2. Le matin, avant d'allumer le robot (environ 15 min)

### 2.1 Le PC

1. **Redémarre le PC.**
2. Ouvre un terminal et vérifie qu'aucune simulation ne tourne :

   ```bash
   pgrep -af "ign gazebo|ros2 launch|uvicorn"       # attendu : aucune ligne
   ```

### 2.2 Dans l'appli Unitree Explore, robot allumé

**Ne lance pas de mise à jour du robot aujourd'hui.**

- [ ] **Note la version du logiciel du robot** (micrologiciel), si ce n'est pas déjà fait.
- [ ] **Active les services `unitree_slam` et `lidar_driver`** (sans eux, ni repérage ni scan).
- [ ] Ensuite, **ne pilote plus le robot avec l'appli** pendant nos essais.

### 2.3 Le point principal au sol

La **croix** du 27/10 (le point principal, l'accueil du robot) et sa **flèche** (la direction où le
robot regarde, au moins 4 m libres devant). Remets-les si le ruban a été enlevé : au même endroit,
dans le même sens.

### 2.4 La feuille de résultats

Ouvre `~/robot-g1/docs/releves/seance-2.md` dans VS Code.

---

## 3. La séance

On utilise **6 terminaux**. Dans **chacun**, tape d'abord :

```bash
source ~/robot-g1/setup/robot.sh
```

| Terminal | Sert à |
|---|---|
| T1 | l'Atelier (la page web) |
| T2 | le pont |
| T3 | l'état du pont |
| T4 | les réponses du robot |
| T5 | les mesures et les commandes à la main |
| T6 | les commandes d'urgence (tuer le pont) |

### Étape A : brancher et regarder (5 min)

1. Robot accroché au portique, allumé. Attends la fin de son démarrage, environ 1 min.
2. Branche le câble Ethernet entre le PC et le robot.
3. Dans T1 :

   ```bash
   source ~/robot-g1/setup/robot.sh      # attendu : « … le robot répond. »
   g1-etat                               # « Connecté » et la batterie (Ctrl+C pour quitter)
   ```

   Note la batterie (ligne A). Si `g1-etat` ne dit pas « Connecté » (« Aucune donnée du robot… ») :
   le robot a-t-il fini de démarrer ? Le câble est-il branché ? Relance
   `source ~/robot-g1/setup/robot.sh` (il réactive la connexion du câble), puis recommence.

### Étape M : mesurer les vrais seuils, au portique (25 min)

On mesure **ce que fait vraiment le robot** pour de petites vitesses. Le pont tourne ici en
**consignes brutes** : il transmet la vitesse demandée telle quelle, sans la monter au minimum.

1. **Robot accroché au portique**, sangle lâche, pieds au sol, en **mode marche** (télécommande).
2. **T2, le pont en consignes brutes :**

   ```bash
   ros2 run g1_bridge pont --ros-args -p exiger_reperage:=false -p vitesse_min_lin:=0.0 -p vitesse_min_rot:=0.0 -p zone_morte_lin:=0.0 -p zone_morte_rot:=0.0 -p vx_max:=0.2 -p vy_max:=0.2 -p wz_max:=0.4
   ```

3. **T3, l'état du pont :**

   ```bash
   ros2 topic echo /pont/etat --field data
   ```

   Attendu : `"etat": "pret"` et, dans `mode_robot`, `"fsm": 501` (marche). Note le `fsm` (ligne M0).
4. **T5, les mesures.** Chaque commande envoie une vitesse pendant quelques secondes, à travers le pont,
   puis affiche en français le retard, la montée, la **vitesse atteinte**, l'arrêt et le dépassement.
   Elle n'envoie rien si le pont n'est pas `pret`. **Copie chaque résultat dans la feuille.**

   **M1. En avant** (ligne M1) :

   ```bash
   python3 -m g1_bridge.mesure marche --vx 0.12 --duree 3
   python3 -m g1_bridge.mesure marche --vx 0.15 --duree 3
   python3 -m g1_bridge.mesure marche --vx 0.18 --duree 3
   python3 -m g1_bridge.mesure marche --vx 0.2 --duree 3
   ```

   Le seuil est la plus petite vitesse où le robot fait vraiment des pas.

   **M2. De côté** (ligne M2) :

   ```bash
   python3 -m g1_bridge.mesure marche --vx 0 --vy 0.12 --duree 3
   python3 -m g1_bridge.mesure marche --vx 0 --vy 0.15 --duree 3
   python3 -m g1_bridge.mesure marche --vx 0 --vy 0.18 --duree 3
   python3 -m g1_bridge.mesure marche --vx 0 --vy 0.2 --duree 3
   python3 -m g1_bridge.mesure marche --vx 0 --vy -0.15 --duree 3      # à droite
   ```

   **M3. En diagonale** : le pont suppose que le robot regarde la **norme** de (vx, vy) (ligne M3).

   ```bash
   python3 -m g1_bridge.mesure marche --vx 0.1 --vy 0.1 --duree 3      # norme 0,14 : immobile ?
   python3 -m g1_bridge.mesure marche --vx 0.14 --vy 0.14 --duree 3    # norme 0,2 : il marche ?
   ```

   **M4. Rotation sur place** (ligne M4) :

   ```bash
   python3 -m g1_bridge.mesure rotation --wz 0.1 --duree 3
   python3 -m g1_bridge.mesure rotation --wz 0.15 --duree 3
   python3 -m g1_bridge.mesure rotation --wz 0.2 --duree 3
   python3 -m g1_bridge.mesure rotation --wz 0.3 --duree 3
   python3 -m g1_bridge.mesure rotation --wz 0.4 --duree 3
   ```

   Pour `--wz 0.3`, note aussi le **retard** et la **montée** : ils servent à régler la rotation
   finale du guide (étape F).

   **M5. Latence et distance d'arrêt à 0,2 m/s** (ligne M5) :

   ```bash
   python3 -m g1_bridge.mesure marche --vx 0.2 --duree 3
   ```

   Note le retard (jusqu'à la moitié de la vitesse), la montée, l'arrêt après le dernier ordre et le
   dépassement en mètres.
5. **M6. Les modes** (ligne M6). Avec la télécommande, mets le robot dans chaque posture et lis le
   `fsm` dans T3 (`mode_robot`) : amorti, assis, accroupi, debout, marche, course ; puis, depuis
   assis, « Démarrer » : 500, puis 501 ?
6. **Ctrl+C dans T2** (le pont envoie un arrêt en quittant). Robot en mode marche.

### Étape C : la sécurité du pont, avec ses réglages normaux (20 min)

C'est la reprise des points C3 à C5 et C7 de la séance n° 1, avec le nouveau pont.

1. **T2, le pont avec ses défauts** (vitesse minimale 0,2 m/s, 0,3 rad/s) et des plafonds réduits :

   ```bash
   ros2 run g1_bridge pont --ros-args -p exiger_reperage:=false -p vx_max:=0.2 -p vy_max:=0.2 -p wz_max:=0.3
   ```

   T3 doit repasser à `pret`.
2. **C2. Le minimum du pont** (ligne C2) : on demande 0,1 m/s, le pont envoie 0,2 m/s.

   ```bash
   python3 -m g1_bridge.mesure marche --vx 0.1 --duree 3
   ```

   Attendu : « 7105 envoyé par le pont : (0.2, 0.0, 0.0) », et le robot marche.
3. **C3. Tourner, puis un pas de côté**, 2 s chacun (ligne C3) :

   ```bash
   ros2 topic pub -r 10 -t 20 /cmd_vel geometry_msgs/msg/Twist "{angular: {z: 0.3}}"    # tourne à gauche
   ros2 topic pub -r 10 -t 20 /cmd_vel geometry_msgs/msg/Twist "{linear: {y: 0.2}}"     # pas vers la gauche
   ```

4. **C4. Le robot s'arrête-t-il seul si le pont meurt ?** C'est **essentiel** (ligne C4).
   - Lance une marche de 10 s dans T5 :

     ```bash
     ros2 topic pub -r 10 -t 100 /cmd_vel geometry_msgs/msg/Twist "{linear: {x: 0.2}}"
     ```

   - Après 3 s, dans T6 :

     ```bash
     pkill -9 -f lib/g1_bridge/pont
     ```

   - Attendu : le robot s'arrête en **moins d'une seconde**.
   - **S'il continue : télécommande, amortissement, fin de la séance.**
   - **Avant de relancer le pont, arrête la marche dans T5 (Ctrl+C)**, ou attends qu'elle soit finie :
     sinon le nouveau pont reprend ces ordres et **le robot repart tout seul** (un pont relancé suit
     tout ordre frais, même ceux d'une marche lancée avant lui ; le guide, lui, annule son trajet dès
     que le pont se tait : section 12.15 du plan).
   - Relance ensuite le pont dans T2 (même commande qu'au point 1).
5. **C5. La télécommande reste-t-elle prioritaire ?** C'est **la condition pour continuer** (ligne C5).
   Relance la marche de 10 s ; pendant ce temps, la personne à la télécommande arrête le robot.
   Attendu : la télécommande gagne **tout de suite**. **Si la télécommande ne reprend pas la main :
   amortissement, fin de la séance.** Puis **Ctrl+C dans T5** si la marche n'est pas finie : sinon,
   quand la télécommande lâche, le robot peut repartir.
6. **C6. Hors du mode marche** (ligne C6). Mets le robot **assis**, puis lance une marche de 2 s :

   ```bash
   ros2 topic pub -r 10 -t 20 /cmd_vel geometry_msgs/msg/Twist "{linear: {x: 0.2}}"
   ```

   Attendu : il ne bouge pas ; T3 passe à `pas_en_marche`, avec un message qui contient « assis ».
   Remets-le en marche : T3 repasse à `pret` **sans mouvement** ; la marche ne reprend qu'avec une
   nouvelle commande.
7. **C7. Nos arrêts** (ligne C7). Pendant une marche de 10 s :

   ```bash
   ros2 topic pub --once /guide/stop std_msgs/msg/Empty "{}"
   ```

   Attendu : arrêt net, puis il repart 1 s plus tard. Ensuite, le verrou :

   ```bash
   ros2 topic pub --once --qos-durability transient_local --qos-reliability reliable /pont/arret std_msgs/msg/Bool "{data: true}"
   ```

   Attendu : arrêt net, puis plus rien ne bouge (`arret_verrouille`). Pour l'enlever, la même commande
   avec `{data: false}`.
8. Fin de l'étape : **Ctrl+C dans T2**. Mets le robot en amortissement sur le portique.

### Étape D : notre logiciel sur le Jetson, avec la caméra (15 min)

1. **Branche la See3CAM sur un port USB 3 du Jetson** (port bleu).
2. Le robot reste au portique, immobile. Dans T5 :

   ```bash
   ssh-copy-id unitree@192.168.123.164        # si ce n'est pas déjà fait ; mot de passe : 123
   g1-jetson verifier                         # chaque ligne : OK, PROBLÈME ou info
   g1-jetson envoyer                          # 2 à 5 min : copie la nouvelle image et la charge
   g1-jetson verifier                         # les sujets du robot vus du conteneur, et la caméra
   ```

   Attendu, ligne de la caméra : « caméra See3CAM : OK … USB 5000 Mbit/s ». Une vitesse plus basse
   (480) : la caméra est sur un port USB 2, change de port.
3. Note dans la feuille (ligne D) : la durée d'`envoyer`, la ligne de la caméra, le groupe du
   périphérique (un nombre, celui du groupe video), et ce que `verifier` dit des sujets du robot.

Si `verifier` dit « Docker inutilisable sans sudo », voir la séance n° 1 (étape D). Si le conteneur ne
marche pas, fais E et F avec le **plan B** (section 4).

### Étape E : le repérage, et la carte d'Unitree (20 min)

La carte est celle du 27/10, retraitée : l'accueil (le point principal) est sur la croix.

1. Décroche le robot du portique. Pose-le **sur la croix, dans le sens de la flèche**, en **mode
   marche**.
2. Dans T1 :

   ```bash
   G1_VITESSE_MAX=0.2 g1-atelier
   ```

3. Sur l'accueil de l'Atelier : **Robot réel** (sans « Répétition »), le lieu **« Séance robot »**.
   Les vérifications doivent être au vert : ROS lancé avec `robot.sh`, câble branché, PC1 et Jetson
   qui répondent ; coche **« Télécommande en main »**. Puis **Ouvrir**.
4. Ruban **Naviguer** : **Lancer**. L'Atelier demande de confirmer : relis sa liste, puis
   « **Lancer sur le robot** ». Il copie alors le lieu sur le Jetson et démarre notre conteneur, avec
   la caméra. Attendu : « Non repéré », et la pastille du robot « à repérer ».
5. **La carte d'Unitree** (ligne E4) : dans T5, **avant** de repérer, lance l'attente (90 s au plus) :

   ```bash
   g1-scan carte-unitree --lieu seance --etage rdc --delai 90
   ```

6. Dans T4 : `ros2 topic echo /api/slam_operate/response`. Puis, dans l'Atelier, **Naviguer ›
   Repérer** (ligne E1). Attendu, en moins de 20 s : **« Repéré »**, avec la précision. Note le texte
   de la réponse et la durée.
7. Dans T5, `g1-scan carte-unitree` doit finir pendant ce temps : il écrit
   `lieux/seance/cartes/rdc_unitree.pcd` et son nuage. **Note ce qu'il affiche** : le nombre de points,
   ou « Erreur : aucune carte reçue… » (dans ce cas, note-le : la documentation non officielle se
   trompait peut-être).
8. **Ce que publie le robot** (ligne E2). Dans T5 :

   ```bash
   ros2 topic hz /unitree/slam_relocation/odom          # 5 s, puis Ctrl+C
   ros2 topic hz /unitree/slam_relocation/points        # 5 s, puis Ctrl+C
   ```

9. **La précision** (ligne E3), **à la télécommande** : avance le robot d'environ 2 m, tourne-le
   d'un quart de tour. Compare la position du robot avec le mètre ruban depuis la croix. Les chiffres
   exacts sont dans le champ `pose` de (T5) : `ros2 topic echo --once /reperage/etat --field data`.
   Trois mesures. Attendu : **moins de 10 cm**.

### Étape F : le premier trajet, 2,5 m à 0,2 m/s (15 min)

1. Robot repéré, près de la croix. La personne à la télécommande se tient à côté ; celle du PC suit,
   câble lâche.
2. **F1.** Ruban **Naviguer › Y aller** : **« Essai à 2,5 m »**. Attendu : `en_route`, le robot marche
   droit vers le but, puis `arrive`. Note la durée et l'écart au mètre ruban.
3. **F2. Le retour seul.** 15 s après l'arrivée, le robot revient seul à l'accueil et **se tourne dans
   le sens de la flèche**. Regarde s'il tourne **une seule fois** ou s'il oscille (il tourne, dépasse,
   revient…). Note l'écart final à la flèche (en degrés, à l'œil ou au rapporteur). Pendant ces 15 s,
   **ARRÊT** (ou Échap, même avec un menu ouvert) annule le retour : le robot reste sur place.
4. **F3. ARRÊT.** **Y aller** « Essai à 2,5 m » de nouveau, puis clique sur **ARRÊT** (barre d'outils,
   en haut à droite) à mi-chemin. Attendu : arrêt net ; le bouton devient **« Débloquer »** ; le panneau
   dit « Robot bloqué : le trajet vers « Essai à 2,5 m » est annulé… ». **Y aller** est grisé
   (« Robot bloqué : « Débloquer » d'abord ») ; demandé quand même (par le chatbot, par exemple), il est
   refusé et ne fait pas bouger le robot : aucune demande n'est gardée pour plus tard. Clique sur
   **Débloquer** (l'Atelier demande de confirmer) : **rien ne bouge**. Le robot **ne reprend pas
   l'ancien trajet** (correction du 01/11, section 12.15 du plan) et le panneau dit « Robot débloqué :
   il attend un nouveau « Y aller » ». Pour repartir, il faut **refaire « Y aller »** : **Y aller**
   « Accueil ». **Si le robot repart seul au « Débloquer » : télécommande, amortissement, fin de la
   séance**, et note-le (ligne F3).
5. **F4.** À l'arrivée, l'écart entre le robot et la croix. Attendu : **moins de 30 cm**.
6. **F5. La rotation finale, si le robot a oscillé en F2** (10 min). Dans T5 :

   ```bash
   python3 -m g1_bridge.mesure cap --pendant 20 --angle 90
   ```

   et tout de suite, dans T6 (1 m libre autour du robot) :

   ```bash
   ros2 action send_goal /spin nav2_msgs/action/Spin "{target_yaw: 1.5708, time_allowance: {sec: 20}}"
   ```

   Note le « dépassement par rapport à 90° ». Puis règle le guide en marche (valeurs en radians, avec
   un point ; 10° = 0.17) :

   ```bash
   ros2 param set /guide anticipation_rotation_rad <dépassement en rad>
   ros2 param set /guide tolerance_orientation_rad <0,6 × le dépassement>
   ```

   Refais F2 : une seule rotation attendue.

### Étape G : la caméra de poitrine (20 min)

Le conteneur tourne depuis l'étape E, avec la caméra.

1. **G1. Les images arrivent sur le PC** (ligne G1). Dans T5 :

   ```bash
   ros2 topic hz /camera_poitrine/image/compressed      # attendu : environ 10 ; Ctrl+C
   ros2 topic bw /camera_poitrine/image/compressed      # taille : 30 à 60 Ko par image ? Ctrl+C
   ros2 topic echo --once /camera_poitrine/etat --field data
   ```

2. **G2. Dans l'Atelier** : barre de la vue centrale, **Caméra**. L'image doit être nette et **ni
   noire ni blanche** (exposition automatique), en pleine lumière comme à l'ombre (ligne G2).
3. **G3. Les réglages** : ruban **Équipe › Caméra**. « Préréglage See3CAM_11CUG », puis la **position
   sur le robot**, robot debout : hauteur de la caméra au-dessus du sol (z), avance par rapport au
   centre du robot (x), et l'inclinaison (tangage : négatif si elle regarde vers le haut).
   **Enregistrer** (ligne G3).
4. **G4. Les visiteurs** (ligne G4). Dans T5 :

   ```bash
   g1-visiteurs --lieu seance --source robot --image
   ```

   Une personne debout devant le robot : un cadre apparaît sur l'image de l'Atelier (vue Caméra).
5. **G5. Les distances** (ligne G5). La personne se tient sur les repères à **1, 2, 3 et 4 m**. Dans T6 :

   ```bash
   ros2 topic echo /visiteurs/detectes --field data | grep --line-buffered -o '"distance_m": [0-9.]*'
   ```

   Note la distance affichée pour chaque repère. La correction est : distance vraie ÷ distance affichée,
   en moyenne. Mets-la dans **Équipe › Caméra › Réglages avancés › Correction des distances**.
6. **G6. Le champ de vision** : une règle ou un mètre à 1 m, d'un bord à l'autre de l'image. Note la
   largeur vue (le champ supposé est de 90°).
7. Ctrl+C dans T5 (`g1-visiteurs`).

### Étape H : un nouveau scan, plus lent (20 min, si le temps le permet)

Le but : comparer la carte de la **nouvelle chaîne** à celle d'Unitree Explore.

1. Garde d'abord le journal de la navigation, dans T5 (le conteneur l'emporte avec lui quand il
   s'arrête) :

   ```bash
   g1-jetson journal --lignes 100000 > ~/robot-g1/docs/releves/seance-2_navigation.log 2>&1
   ```

   Puis ruban **Naviguer › Arrêter** (la navigation et le conteneur s'arrêtent).
2. **Robot sur la croix**, dans le sens de la flèche, en mode marche.
3. Ruban **Scanner › Scan**. L'écran passe en plein écran : le nuage se remplit en direct.
4. Promène le robot à la télécommande, **plus lentement que le 27/10** : moins de 0,5 m/s, virages
   lents, personne entre le robot et les murs. La personne du PC suit, câble lâche.
5. **Reviens sur la croix, dans le sens de la flèche**, puis **Fin**. La carte et le nuage sont prêts
   en quelques secondes.
6. **Ne clique pas sur « Utiliser cette carte » aujourd'hui** : on compare d'abord, à tête reposée
   (ligne H). Note la durée, la distance, le nombre de points, et ce que tu vois : murs fermés ? tables
   et chaises reconnaissables ? carte ni dédoublée ni tournée ?

### Étape P : le pilotage et une danse sûre (25 min)

**Si tu as sauté l'étape H**, le conteneur de la navigation tourne encore et `g1-jetson demarrer`
refuserait (« le conteneur g1-jetson tourne déjà ») : fais d'abord le point 1 de l'étape H, le
journal de la navigation (le conteneur l'emporte avec lui quand il s'arrête) :

```bash
g1-jetson journal --lignes 100000 > ~/robot-g1/docs/releves/seance-2_navigation.log 2>&1
```

puis **Naviguer › Arrêter**.

1. **Robot raccroché au portique**, pieds au sol, en mode marche.
2. Le nœud pilotage seul, sur le Jetson. Dans T5 :

   ```bash
   G1_VITESSE_MAX=0.2 g1-jetson demarrer --veille
   export G1_PILOTAGE_URL=http://192.168.123.164:8010 G1_PILOTAGE_JETON=$(cat ~/robot-g1/opt/jetson/jeton_pilotage)
   g1-pilotage etat                       # robot_repond : true ; noter fsm (501 ?)
   ```

3. Dans T1, Ctrl+C sur l'Atelier, puis :

   ```bash
   G1_PILOTAGE_URL=http://192.168.123.164:8010 G1_VITESSE_MAX=0.2 g1-atelier
   ```

   Accueil : **Robot réel**, « Séance robot », **Ouvrir**, ruban **Piloter**.
4. **P1. Prendre la main**, puis **Postures › Démarrer** : note le mode lu (ligne P1).
5. **P2. Les joysticks** (case Joysticks du ruban) : le manche gauche **à peine incliné** fait marcher le
   robot à 0,2 m/s (le minimum du pont), pas moins (ligne P2).
6. **P3. ARRÊT pendant le joystick** (ligne P3) : un pouce tient le manche, l'autre main clique sur
   **ARRÊT**. Attendu : le robot s'arrête, et **le manche tenu ne le relance pas** : il faut le lâcher,
   puis le reprendre. Clique sur **Débloquer** (et confirme). De même, si le robot est mis assis ou en
   amortissement à la télécommande pendant que le manche est tenu, il ne repart pas quand il est remis
   en marche tant que le manche n'a pas été lâché, et une chorégraphie interrompue ainsi ne reprend
   pas (relecture du 01/11).
7. **P4. Une danse sûre, depuis 501** (ligne P4) : robot **tenu** au portique, 3 m libres autour.
   **Spectacle › Danses**, la **604**, coche la zone libre, confirme. Ou, dans T5 :

   ```bash
   g1-pilotage danse 604 --zone-libre
   g1-pilotage etat                       # pendant, puis après : le robot revient-il en 501 ou en 801 ?
   ```

   Note la durée et le mode à la fin. **Jamais 401, 402 ni 403.**
8. **P5.** **Rendre la main**, puis dans T5, garde le journal du pilotage **avant** d'arrêter :

   ```bash
   g1-jetson journal --lignes 100000 > ~/robot-g1/docs/releves/seance-2_pilotage.log 2>&1
   g1-jetson arreter
   ```

### Fin (5 min)

1. Un conteneur tourne-t-il encore (par exemple si l'étape P a été sautée) ? Dans T5 :

   ```bash
   g1-jetson etat
   ```

   « aucun conteneur g1-jetson… » : c'est fini pour le conteneur. S'il dit « running » (ou « exited » :
   un conteneur arrêté tout seul), garde son journal **avant** de l'arrêter :

   ```bash
   g1-jetson journal --lignes 100000 > ~/robot-g1/docs/releves/seance-2_conteneur.log 2>&1
   g1-jetson arreter
   ```

2. Robot en amortissement, puis éteint. Débranche le câble. Ctrl+C dans T1 (l'Atelier).
3. Complète la feuille de résultats.

---

## 4. Si ça ne marche pas

| Ce que tu vois | Que faire |
|---|---|
| `robot.sh` : « Câble non détecté » | Rebranche le câble des deux côtés et attends 10 s. |
| `robot.sh` : le robot ne répond pas | Robot fini de démarrer ? Attends 1 min et recommence. |
| `robot.sh` : « Impossible d'activer la connexion robot-g1 », ou câble débranché puis rebranché | `nmcli connection up robot-g1`, puis recommence. |
| `g1-etat` ne dit pas « Connecté » (« Aucune donnée du robot… ») | Robot fini de démarrer ? Câble branché ? Relance `source ~/robot-g1/setup/robot.sh`, puis recommence. |
| Le pont refuse de démarrer (« … le robot ne ferait aucun pas ») | Un plafond est sous 0,2 m/s : utilise les commandes de ce tutoriel telles quelles. |
| T3 reste `pas_en_marche` | Lis le message : assis ou pas démarré → « Démarrer » à la télécommande ; course (802) → marche normale. |
| T3 reste `robot_muet` | Note `ros2 topic info -v /api/sport/request`, puis passe à l'étape D. |
| `mesure` n'envoie rien | Le pont n'est pas `pret` : regarde T3. |
| Le robot ne s'arrête pas seul (C4) | Télécommande, amortissement, **fin de la séance**. |
| `ssh` redemande un mot de passe | Refais `ssh-copy-id unitree@192.168.123.164` (mot de passe 123). |
| `verifier` : pas de ligne caméra, ou USB 480 | Rebranche la See3CAM sur un port USB 3 (bleu) du Jetson. Si le conteneur tourne déjà, relance-le pour qu'il la reçoive : garde d'abord son journal (`g1-jetson journal --lignes 100000 >> ~/robot-g1/docs/releves/seance-2_relances.log 2>&1`), puis Naviguer › Arrêter, Lancer, robot sur la croix, et Repérer de nouveau. |
| Vue Caméra : « Pas d'image » | `ros2 topic hz /camera_poitrine/image/compressed` ; `g1-jetson journal 2>&1 \| grep -i cam`. |
| Image noire | Équipe › Caméra › Réglages avancés : exposition automatique ; note la lumière de la pièce. |
| « Repérer » échoue | Note le message, `ros2 topic echo --once /slam_info` et `g1-jetson journal 2>&1 \| tail -n 30`. |
| `carte-unitree` : « aucune carte reçue » | Note-le ; relance-le, puis **Repérer** de nouveau pendant l'attente. |
| Le robot oscille à la fin d'un trajet | Fais F5. |
| `g1-jetson demarrer` : « le conteneur g1-jetson tourne déjà » | Fais d'abord le premier point de l'étape P (le journal, puis Naviguer › Arrêter), puis recommence. |
| Quelque chose bouge sans qu'on l'ait demandé | Télécommande, amortissement, **fin de la séance**. |

**Plan B : la navigation sur le PC, au câble**, seulement si le conteneur ne marche pas (étape D ou
E). La navigation tourne alors sur le PC ; la personne du PC suit le robot de près. Les boutons
« Repérer » et « Y aller » de l'Atelier ne servent qu'à la navigation que l'Atelier a lancée
lui-même : avec le plan B, on passe par ces commandes.

1. Dans T5, vérifie d'abord qu'**aucun conteneur ne tourne** sur le Jetson (sinon, deux ponts
   commanderaient le robot) :

   ```bash
   g1-jetson etat
   ```

   Attendu : « aucun conteneur g1-jetson… » (ou « le Jetson ne répond pas par ssh » : il n'a rien pu
   démarrer). S'il dit « running », garde son journal, puis arrête-le :

   ```bash
   g1-jetson journal --lignes 100000 >> ~/robot-g1/docs/releves/seance-2_relances.log 2>&1
   g1-jetson arreter
   ```

2. Dans T2 (avec `robot.sh`), la navigation à 0,2 m/s au plus :

   ```bash
   g1-guide navigation --lieu seance --etage rdc --vitesse-max 0.2
   ```

3. Dans T5, le robot posé sur la croix, dans le sens de la flèche : le repérage en (0 ; 0 ; 0), puis
   son état (Ctrl+C pour quitter) :

   ```bash
   ros2 topic pub --once /reperage/demander std_msgs/msg/String "{data: '{\"id\": \"seance-2\", \"x\": 0, \"y\": 0, \"theta\": 0}'}"
   ros2 topic echo /reperage/etat --field data       # attendu : "etat": "repere"
   ```

4. Le trajet court (`essai_3m` est le nom interne de la salle « Essai à 2,5 m ») :

   ```bash
   g1-guide aller essai_3m
   ```

   Le robot y va, et la commande affiche son état jusqu'à l'arrivée : **Ctrl+C n'arrête que
   l'affichage, pas le robot**. **15 s après l'arrivée, le robot revient seul sur la croix**, comme
   en F2.
5. Pour arrêter le robot à tout moment (comme ARRÊT), dans T6 :

   ```bash
   g1-guide stop
   ```

---

## 5. Après la séance : ce qu'il faut me rapporter

Dis-moi **« séance 2 faite »**, avec :

1. la feuille remplie, `docs/releves/seance-2.md` (ou la fiche Word `Seance2_A_remplir.docx`
   enregistrée dans `docs/releves/`), avec **les résultats des mesures copiés tels quels** ;
2. les journaux du conteneur, dans `docs/releves/` : `seance-2_navigation.log` (étapes E à G),
   `seance-2_pilotage.log` (étape P) et, s'il y en a, `seance-2_conteneur.log` (un conteneur qui
   tournait encore à la fin) et `seance-2_relances.log` (un conteneur arrêté en cours de route, pour le
   relancer ou pour le plan B) ;
3. les messages d'erreur, copiés mot pour mot.

Je retrouverai seul le nouveau scan (`lieux/seance/scans/`), la carte d'Unitree
(`lieux/seance/cartes/rdc_unitree.*`), les journaux de l'Atelier (`journaux/`) et ceux de ROS 2
restés sur le Jetson (`~/robot-g1/journaux/jetson/ros/log/`).

Avec tes mesures, je réglerai :

- la vitesse minimale du pont (`config/pont.yaml` et `VITESSES_MIN_PONT`) : un peu au-dessus du seuil
  mesuré ;
- la rotation finale du guide (`tolerance_orientation_rad`, `anticipation_rotation_rad`) ;
- la correction des distances de la caméra et sa position sur le robot.
