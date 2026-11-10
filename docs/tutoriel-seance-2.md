# Séance robot n° 2 : brouillon (date à fixer)

Ce tutoriel suit toute la journée, dans l'ordre :

1. la veille au soir ;
2. le matin, avant d'allumer le robot ;
3. la séance elle-même, en neuf étapes, plus la démo d'accueil en option (V) et la fin ;
4. ce qu'il faut me rapporter.

C'est un **brouillon** écrit après la vague 5 (31/10/2026) et mis à jour après la vague 6 (10/11/2026),
sans robot : les commandes ont été essayées contre le faux G1, dans Gazebo, pas sur le vrai robot. Le
déroulé de référence est dans `docs/seance-robot.md` (sections 1 à 8) et la liste des points à vérifier
dans les sections 12.12 et 13.10 du plan. La feuille de résultats est prête : `docs/releves/seance-2.md`.

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

**Ce que la vague 6 change dans la journée** (sections 13.2 à 13.6 du plan) :

- **au début**, **Vérifier le robot** remplace les vérifications à la main (`g1-etat`, la liste de
  l'accueil, les services activés dans l'appli, le premier `g1-jetson verifier`) : un clic, une phrase
  par point, et le bouton qui **démarre les services de cartographie** s'ils sont arrêtés (étape A) ;
- **pendant toute la séance**, la **boîte noire** enregistre tout dès l'ouverture de l'espace : nos
  actions, les états du robot, du pont et du guide, les journaux, et **le journal du conteneur du
  Jetson, gardé tout seul** à chaque « Naviguer › Arrêter ». Il ne reste qu'un journal à garder à la
  main : celui du pilotage (étape P), lancé dans un terminal ;
- **à la fin**, **Terminer la séance** écrit le **rapport de séance**, et une commande en fait un `.zip`
  à me donner (étape Fin) ;
- **en option**, si le temps le permet : **la voix du robot**, essayée prudemment (volume bas d'abord),
  et **la démo d'accueil** avec la borne (étape V).

**Durée :** environ 2 h 30 avec le robot (plus 20 min pour l'option V), 45 min la veille et 15 min le
matin. Si le temps manque, on garde l'ordre et on saute H, puis V.

**Ce qui ne change pas dans le robot :** comme à la séance n° 1. Le PC1 d'Unitree n'est jamais
touché ; sur le Jetson, seulement notre image Docker (environ 2 Go) et le dossier `~/robot-g1` ;
rien n'est installé dans Ubuntu, ROS ou les programmes d'Unitree ; notre conteneur ne redémarre
jamais tout seul. Deux réglages du robot peuvent changer, comme avec l'appli : les services de
cartographie démarrés par « Vérifier le robot », et le volume de son haut-parleur (étape V). Pour tout
retirer : d'abord `g1-jetson arreter`, puis
`ssh unitree@192.168.123.164 'docker rmi g1-jetson:arm64; rm -rf ~/robot-g1'`.

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
   on passe au suivant s'il n'y a pas de danger. La boîte noire enregistre aussi tout de son côté, mais
   ce que tu vois (un pas de travers, un bruit, un son trop fort) n'est que dans la feuille.
8. **L'Atelier reste ouvert toute la journée** (T1, lancé à l'étape A). Le fermer (Ctrl+C) termine la
   séance de la boîte noire ; une navigation lancée continuerait sur le Jetson sans que l'Atelier le
   sache.

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
#    la vitesse minimale et les modes, la caméra, l'ARRÊT, puis « Vérifier le robot »,
#    la boîte noire, la voix et la sécurité de la démo (environ 20 min).
#    Attendu à la fin : « 12 / 12 »
tests_e2e/tout.sh 16 17 18 19 20 34 35 36 37 38 40 42

# 3) L'image du Jetson (avec la caméra, le nouveau pont et le pilotage). Déjà à jour : quelques
#    secondes ; sinon, 5 à 10 min.
g1-jetson construire

# 4) Le lieu de la séance : la carte retraitée du 27/10 (attendu : « Aucune erreur. » ;
#    les nœuds 1, 2 et 3 ne sont reliés à rien, c'est normal)
g1-lieu valider --lieu seance

# 5) Voir à blanc ce que fera l'envoi au Jetson (rien n'est envoyé)
G1_SLAM_FAUX=1 g1-jetson envoyer --dry-run

# 6) De la place pour la boîte noire : au moins 5 Go libres (colonne « Dispo ») ;
#    elle s'arrête sous 2 Go, et une séance pèse environ 150 Mo par heure
df -h ~
```

Si `tout.sh` n'affiche pas « 12 / 12 », envoie-moi la fin de l'affichage avant la séance.

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
- [ ] Les services **`unitree_slam` et `lidar_driver`** (sans eux, ni repérage ni scan) : **ne les
  active pas ici**. « Vérifier le robot » (étape A) les voit arrêtés et les démarre en un clic : c'est
  un des essais du jour. Seulement s'il n'y arrive pas, on les activera dans l'appli (solution de
  secours).
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
| T1 | l'Atelier (la page web), ouvert toute la journée |
| T2 | le pont |
| T3 | l'état du pont |
| T4 | les réponses du robot |
| T5 | les mesures et les commandes à la main |
| T6 | les commandes d'urgence (tuer le pont) |

### Étape A : brancher, vérifier le robot, ouvrir la séance (10 min)

1. Robot accroché au portique, allumé. Attends la fin de son démarrage, environ 1 min.
2. Branche le câble Ethernet entre le PC et le robot.
3. **A1. L'Atelier, pour toute la journée.** Dans T1 :

   ```bash
   source ~/robot-g1/setup/robot.sh      # attendu : « … le robot répond. »
   G1_VITESSE_MAX=0.2 G1_PILOTAGE_URL=http://192.168.123.164:8010 g1-atelier
   ```

   Le navigateur s'ouvre sur l'Atelier. Il reste ouvert jusqu'à la fin (règle d'or 8) : 0,2 m/s au
   plus pour la navigation et le joystick, et l'onglet Piloter sait déjà où trouver le Jetson (étape
   P). Si `robot.sh` ne dit pas « le robot répond » : le robot a-t-il fini de démarrer ? Le câble
   est-il branché ? Relance `source ~/robot-g1/setup/robot.sh` (il réactive la connexion du câble),
   puis recommence (section 4).

   **Variante**, seulement si tu veux essayer la borne de la démo sur ton téléphone à l'étape V :
   ajoute `--hote 0.0.0.0` à la fin de la commande (depuis le Wi-Fi, seule la borne est permise ; ni
   l'Atelier, ni « Débloquer », ni les réglages). Sinon, la borne s'ouvrira sur ce PC.
4. **A2. Vérifier le robot.** Sur l'accueil de l'Atelier, carte **Robot réel** (sans « Répétition »),
   clique sur **Vérifier le robot**. En 10 s environ (15 s au plus), chaque point dit **OK**,
   **Attention**, **Problème** ou **Inconnu**, avec une phrase qui dit quoi faire : le câble, l'adresse
   du PC, la connexion `robot-g1`, les réglages ROS, le PC1, le Jetson et le LiDAR, les sujets du robot,
   les **services de cartographie**, le mode du robot, la **batterie**, le Jetson (clé SSH, Docker,
   image du conteneur, place, horloge) et la caméra. Il remplace `g1-etat`, la liste de l'accueil et les
   services de l'appli, et il ne fait jamais bouger le robot.
   - **Services de cartographie arrêtés** (attendu, comme le 27/10) : **Démarrer les services de
     cartographie**, puis confirme dans la page. Seuls `lidar_driver` et `unitree_slam` sont démarrés ;
     jamais un arrêt, rien d'autre n'est touché. Attendu, en 20 s au plus : « Les services de
     cartographie ont démarré en … s ». Puis **Vérifier à nouveau**. S'ils restent arrêtés : active-les
     dans l'appli Unitree Explore (secours), et note le message.
   - **Connexion du câble tombée** : **Rétablir la connexion du câble**.
   - **Image du conteneur** : « faites g1-jetson envoyer » est attendu (l'image a été refaite le
     10/11) : ce sera l'étape D. **Caméra** pas vue : normal, elle sera branchée sur le Jetson à
     l'étape D. **Mode du robot** : Attention est normal tant qu'il n'est pas en mode marche.

   Note la batterie, la durée, et chaque ligne qui n'est pas OK avec son texte (ligne A2). Si la page ne
   répond pas : le même diagnostic dans un terminal, `g1-diagnostic` (T5), et `g1-etat` pour la
   batterie.
5. **A3. Ouvrir la séance.** Toujours sur l'accueil : le lieu **« Séance robot »**, coche
   **« Télécommande en main »**, puis **Ouvrir**. La **séance** s'ouvre seule : badge
   « ● Enregistrement » dans la barre d'outils (« Séance », ou un point rouge, sur un écran plus
   étroit). Dès lors, la boîte noire garde tout jusqu'à « Terminer la séance » (étape Fin) : rien
   d'autre à faire. Note l'heure (ligne A3). Les marches lancées à la main aux étapes M et C seront dans
   le rapport comme « mouvements sans demande » : c'est normal.

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
   ssh-copy-id unitree@192.168.123.164        # seulement si « Vérifier le robot » l'a demandé ; mot de passe : 123
   g1-jetson envoyer                          # 2 à 5 min : copie la nouvelle image et la charge
   g1-jetson verifier                         # les sujets du robot vus du conteneur, et la caméra
   ```

   Attendu, ligne de la caméra : « caméra See3CAM : OK … USB 5000 Mbit/s ». Une vitesse plus basse
   (480) : la caméra est sur un port USB 2, change de port.
3. Dans l'Atelier, **Vérifier le robot** de nouveau (bouton de la barre d'outils, ou Naviguer ›
   Vérifier le robot) : les lignes du Jetson sont OK (« Le Jetson a la même image du conteneur que le
   PC »), et la caméra est « branchée sur le Jetson ».
4. Note dans la feuille (ligne D) : la durée d'`envoyer`, la ligne de la caméra, le groupe du
   périphérique (un nombre, celui du groupe video), ce que `verifier` dit des sujets du robot, et les
   lignes du Jetson et de la caméra de « Vérifier le robot ».

Si « Vérifier le robot » dit « Docker ne marche pas sur le Jetson sans sudo », voir la séance n° 1
(étape D). Si le conteneur ne marche pas, fais E et F avec le **plan B** (section 4).

### Étape E : le repérage, et la carte d'Unitree (20 min)

La carte est celle du 27/10, retraitée : l'accueil (le point principal) est sur la croix.

1. Décroche le robot du portique. Pose-le **sur la croix, dans le sens de la flèche**, en **mode
   marche**.
2. L'Atelier tourne depuis l'étape A, sur le lieu « Séance robot », séance ouverte : rien à relancer.
   Si tu as un doute, **Vérifier le robot** : tout doit être OK (le mode du robot aussi, maintenant).
3. Ruban **Naviguer** : **Lancer**. L'Atelier demande de confirmer : relis sa liste, puis
   « **Lancer sur le robot** ». Il copie alors le lieu sur le Jetson et démarre notre conteneur, avec
   la caméra. Attendu : « Non repéré », et la pastille du robot « à repérer ».
4. **La carte d'Unitree** (ligne E4) : dans T5, **avant** de repérer, lance l'attente (90 s au plus) :

   ```bash
   g1-scan carte-unitree --lieu seance --etage rdc --delai 90
   ```

5. Dans T4 : `ros2 topic echo /api/slam_operate/response`. Puis, dans l'Atelier, **Naviguer ›
   Repérer** (ligne E1). Attendu, en moins de 20 s : **« Repéré »**, avec la précision. Note le texte
   de la réponse et la durée.
6. Dans T5, `g1-scan carte-unitree` doit finir pendant ce temps : il écrit
   `lieux/seance/cartes/rdc_unitree.pcd` et son nuage. **Note ce qu'il affiche** : le nombre de points,
   ou « Erreur : aucune carte reçue… » (dans ce cas, note-le : la documentation non officielle se
   trompait peut-être).
7. **Ce que publie le robot** (ligne E2). Dans T5 :

   ```bash
   ros2 topic hz /unitree/slam_relocation/odom          # 5 s, puis Ctrl+C
   ros2 topic hz /unitree/slam_relocation/points        # 5 s, puis Ctrl+C
   ```

8. **La précision** (ligne E3), **à la télécommande** : avance le robot d'environ 2 m, tourne-le
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

1. Ruban **Naviguer › Arrêter** (la navigation et le conteneur s'arrêtent). Juste avant, la boîte
   noire garde toute seule le journal du conteneur dans la séance (30 s au plus) : plus rien à copier
   à la main. Pour le voir, dans T5 :

   ```bash
   ls ~/robot-g1/journaux/seances/*/journaux/jetson/      # attendu : conteneur_…_avant_arret.log
   ```

   **Secours**, seulement si aucune séance n'est ouverte (pas de badge dans la barre d'outils) : avant
   « Arrêter », garde le journal à la main (le conteneur l'emporte avec lui quand il s'arrête) :
   `g1-jetson journal --lignes 100000 > ~/robot-g1/docs/releves/seance-2_navigation.log 2>&1`.
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
refuserait (« le conteneur g1-jetson tourne déjà ») : fais d'abord **Naviguer › Arrêter** (point 1 de
l'étape H : la boîte noire garde son journal).

1. **Robot raccroché au portique**, pieds au sol, en mode marche.
2. Le nœud pilotage seul, sur le Jetson. Dans T5 :

   ```bash
   G1_VITESSE_MAX=0.2 g1-jetson demarrer --veille
   export G1_PILOTAGE_URL=http://192.168.123.164:8010 G1_PILOTAGE_JETON=$(cat ~/robot-g1/opt/jetson/jeton_pilotage)
   g1-pilotage etat                       # robot_repond : true ; noter fsm (501 ?)
   ```

3. Dans l'Atelier, ruban **Piloter** : l'Atelier, lancé à l'étape A avec l'adresse du pilotage
   (`G1_PILOTAGE_URL`), le trouve sur le Jetson ; **ne le relance pas** (la séance continue).
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
8. **P5.** **Rendre la main**, puis dans T5, garde le journal du pilotage **avant** d'arrêter. Ce
   conteneur a été lancé dans un terminal : la boîte noire ne le connaît pas, c'est le seul journal à
   garder à la main.

   ```bash
   g1-jetson journal --lignes 100000 > ~/robot-g1/docs/releves/seance-2_pilotage.log 2>&1
   g1-jetson arreter
   ```

### Étape V : la voix du robot et la démo d'accueil (20 min, en option)

Seulement si tout le reste est fait et qu'il reste du temps. **V1** (la voix, 5 min) se fait au
portique, juste après P ; **V2** (la démo, 15 min) demande de relancer la navigation.

1. **V1. La voix, prudemment.** Robot au portique, une personne à 1 ou 2 m (pas l'oreille contre le
   haut-parleur).
   - Ruban **Équipe › ⚙ Avancé › Réglages de la démo**, partie « La voix du robot » : « Le robot parle
     par » **Haut-parleur du robot** (la voix est fabriquée sur le PC). **Mets le volume à 20 %** (il
     est à 70 % par défaut), puis clique sur **Enregistrer les réglages** (en bas du panneau) : la démo
     prendra ce volume.
   - **Démarrer la voix**, puis **Essayer** (« Bonjour ! Je suis le robot d'accueil. Suivez-moi ! »).
     Attendu : la phrase sort du haut-parleur du robot, doucement.
   - On l'entend mal à 2 m ? Monte de **10 en 10** (30, 40, 50 %), un essai à chaque fois : le volume
     part tout de suite au robot. **Pas plus de 70 %.** Note le volume retenu, si le son est net (sans
     craquement) et le délai avant le son (ligne V1). Puis **Enregistrer les réglages** avec ce volume.
   - Essaie aussi « Synthèse du robot » (sa voix intégrée) dans la même liste, puis **Essayer** :
     parle-t-elle français ? (sans doute non : elle est réglée sur l'anglais en attendant). Remets
     **Haut-parleur du robot**, puis **Enregistrer les réglages**.
   - **Arrêter la voix** (la démo lance la sienne).
2. **V2. La démo d'accueil** (ligne V2).
   - **Relancer la navigation** (arrêtée avant H ou P) : robot décroché, **sur la croix, dans le sens
     de la flèche**, en mode marche ; **Naviguer › Lancer** (confirme « Lancer sur le robot »), puis
     **Repérer** : « Repéré ».
   - **Réglages de la démo**, pour un premier essai : sous « Salles proposées par la borne », décoche
     « 1 », « 2 » et « 3 » (elles ne sont reliées à rien) et garde **« Essai à 2,5 m »** ; « Visiteurs
     vus par » : **La borne seule** (personne n'est salué par erreur pendant qu'on s'agite autour du
     robot) ; **Enregistrer les réglages**.
   - **Équipe › Démo › Lancer la démo**. Attendu : « Démo lancée : le robot attend un visiteur à
     l'accueil ». Sinon, le message dit quoi faire (par exemple lancer la navigation et repérer).
   - **La borne** : sur ce PC, une nouvelle fenêtre du navigateur à l'adresse
     `http://localhost:8000/borne` ; ou sur ton téléphone, si l'Atelier a été lancé avec
     `--hote 0.0.0.0` (variante de l'étape A) : **Équipe › Démo › Borne** montre l'adresse et son code
     QR (téléphone sur le même Wi-Fi que le PC).
   - **Une visite** : un volontaire touche la borne ; le robot le salue (la voix), la borne propose les
     salles ; il touche **« Essai à 2,5 m »**, confirme (Oui) : « Suivez-moi ! », le robot l'accompagne à
     0,2 m/s (la borne montre la distance), annonce l'arrivée, puis revient seul à l'accueil.
   - **La pause** : pendant une seconde visite, **ARRÊT** à mi-chemin. Attendu : arrêt net, la démo
     passe « en pause », la borne dit qu'elle fait une petite pause. **Débloquer** : **rien ne bouge**
     (attends 15 s et regarde). Puis **Ramener à l'accueil** (panneau de la démo) : le robot revient,
     c'est une demande explicite, et la démo attend le visiteur suivant. **Si quelque chose repart
     seul : télécommande, amortissement, fin de la séance.**
   - Note ce qui marche et ce qui gêne : salutation, voix, borne (PC ou téléphone), accompagnement,
     arrivée, retour, pause.
   - **Arrêter la démo** (cela n'arrête pas le robot : c'est le rôle de l'ARRÊT), puis **Naviguer ›
     Arrêter** (la boîte noire garde le journal du conteneur).

### Fin (10 min)

1. **Plus rien sur le Jetson.** Si la navigation tourne encore : **Naviguer › Arrêter** (la boîte noire
   garde son journal). Puis, dans T5 :

   ```bash
   g1-jetson etat
   ```

   « aucun conteneur g1-jetson… » : c'est fini pour le conteneur. S'il dit « running » (le conteneur du
   pilotage, si P n'est pas allée au bout) ou « exited » (un conteneur arrêté tout seul), garde son
   journal **avant** de l'arrêter :

   ```bash
   g1-jetson journal --lignes 100000 > ~/robot-g1/docs/releves/seance-2_conteneur.log 2>&1
   g1-jetson arreter
   ```

2. **Z1. Terminer la séance** : clique sur le badge de la séance (barre d'outils), **Terminer la
   séance**, puis **Terminer**. L'enregistrement s'arrête et le rapport s'écrit en moins d'une minute :
   **Rapport de séance** (barre d'outils, ou le même menu) l'ouvre dans un onglet. En haut, **En bref**
   (durée, trajets, distance, arrêts d'urgence, anomalies, erreurs, batterie) et **À regarder en
   premier** ; puis la carte des trajets, chaque trajet avec son résultat et la cause de ses arrêts,
   les états du pont, les modes du robot, la précision du repérage, les diagnostics et la chronologie.
   Les marches à la main de M et C et les déplacements à la télécommande (E3, H) y sont des
   « mouvements sans demande » : c'est attendu. Note ce qui t'étonne (ligne Z1). (Si tu oublies, Ctrl+C
   dans T1 ferme aussi la séance et écrit son rapport.)
3. **Z2. Le `.zip` pour moi.** Dans T5 :

   ```bash
   g1-seance liste                  # les séances, la plus récente d'abord : celle d'aujourd'hui, fermée, rapport prêt
   g1-seance exporter derniere --sortie ~/robot-g1/docs/releves/seance-2_boite_noire.zip
   ```

   Attendu : « Séance exportée : … (… Mo) », quelques centaines de Mo au plus (ligne Z2). Si `liste`
   montre **plusieurs séances aujourd'hui** (l'Atelier a été relancé), exporte aussi chacune des autres
   avec son identifiant, écrit au début de sa ligne (par exemple `2026-11-12_14h03`) :
   `g1-seance exporter 2026-11-12_14h03 --sortie ~/robot-g1/docs/releves/seance-2_boite_noire_2.zip`.
4. Robot en amortissement, puis éteint. Débranche le câble. Ctrl+C dans T1 (l'Atelier).
5. Complète la feuille de résultats.

---

## 4. Si ça ne marche pas

| Ce que tu vois | Que faire |
|---|---|
| `robot.sh` : « Câble non détecté » | Rebranche le câble des deux côtés et attends 10 s. |
| `robot.sh` : le robot ne répond pas | Robot fini de démarrer ? Attends 1 min et recommence. |
| `robot.sh` : « Impossible d'activer la connexion robot-g1 », ou câble débranché puis rebranché | `nmcli connection up robot-g1`, puis recommence. |
| `g1-etat` ne dit pas « Connecté » (« Aucune donnée du robot… ») | Robot fini de démarrer ? Câble branché ? Relance `source ~/robot-g1/setup/robot.sh`, puis recommence. |
| « Vérifier le robot » ne répond pas, ou l'Atelier ne s'ouvre pas | Le même diagnostic dans T5 : `g1-diagnostic` (chaque ligne et son conseil ; « Ici : g1-diagnostic --action … » donne la commande d'une action) ; la batterie : `g1-etat`. |
| Services de cartographie toujours arrêtés après « Démarrer les services de cartographie » | Note le message. Active-les dans l'appli Unitree Explore (secours), puis **Vérifier à nouveau**. |
| T3 dit `arret_verrouille` alors que personne n'a posé de verrou | L'ARRÊT de l'Atelier (bouton ou Échap) l'a posé : **Débloquer** (barre d'outils). |
| Pas de badge de séance dans la barre d'outils | **Nouvelle séance** (barre d'outils) ; en attendant, garde les journaux du conteneur à la main (secours de l'étape H). |
| Badge orange « Enregistrement coupé » | Disque presque plein (moins de 2 Go) ou plus de 1 Go enregistré : la séance continue (actions, rapport) sans l'enregistrement ROS 2. Note l'heure ; fais de la place après la séance. |
| Le pont refuse de démarrer (« … le robot ne ferait aucun pas ») | Un plafond est sous 0,2 m/s : utilise les commandes de ce tutoriel telles quelles. |
| T3 reste `pas_en_marche` | Lis le message : assis ou pas démarré → « Démarrer » à la télécommande ; course (802) → marche normale. |
| T3 reste `robot_muet` | Note `ros2 topic info -v /api/sport/request`, puis passe à l'étape D. |
| `mesure` n'envoie rien | Le pont n'est pas `pret` : regarde T3. |
| Le robot ne s'arrête pas seul (C4) | Télécommande, amortissement, **fin de la séance**. |
| `ssh` redemande un mot de passe | Refais `ssh-copy-id unitree@192.168.123.164` (mot de passe 123). |
| `verifier` ou « Vérifier le robot » : caméra pas vue, ou USB 480 (USB 2) | Rebranche la See3CAM sur un port USB 3 (bleu) du Jetson. Si le conteneur tourne déjà, relance-le pour qu'il la reçoive : Naviguer › Arrêter (la boîte noire garde son journal), Lancer, robot sur la croix, et Repérer de nouveau. |
| Vue Caméra : « Pas d'image » | `ros2 topic hz /camera_poitrine/image/compressed` ; `g1-jetson journal 2>&1 \| grep -i cam`. |
| Image noire | Équipe › Caméra › Réglages avancés : exposition automatique ; note la lumière de la pièce. |
| « Repérer » échoue | Note le message, `ros2 topic echo --once /slam_info` et `g1-jetson journal 2>&1 \| tail -n 30`. |
| `carte-unitree` : « aucune carte reçue » | Note-le ; relance-le, puis **Repérer** de nouveau pendant l'attente. |
| Le robot oscille à la fin d'un trajet | Fais F5. |
| `g1-jetson demarrer` : « le conteneur g1-jetson tourne déjà » | La navigation : **Naviguer › Arrêter** (la boîte noire garde son journal). Si l'Atelier ne la connaît plus (il a été relancé) : `g1-jetson journal --lignes 100000 >> ~/robot-g1/docs/releves/seance-2_relances.log 2>&1`, puis `g1-jetson arreter`. Puis recommence. |
| La voix ne sort pas du haut-parleur du robot | Regarde la ligne d'état sous « La voix du robot » (le robot écoute-t-il ?) ; **Vérifier le robot** (le robot parle-t-il au PC ?) ; essaie un volume un peu plus haut (pas plus de 70 %). Note le message. |
| « Lancer la démo » refusé | Lis le message : la démo a besoin de la navigation (**Naviguer › Lancer**) et du robot repéré (**Repérer**). |
| La démo reste « en pause » | C'est voulu après un ARRÊT, un blocage, le robot assis ou le pilotage : **Débloquer** s'il le faut, puis **Ramener à l'accueil** (ou **Reprendre** si le robot est déjà à l'accueil). Rien ne repart seul. |
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
   démarrer). S'il dit « running » : si c'est la navigation lancée par l'Atelier, **Naviguer ›
   Arrêter** (la boîte noire garde son journal) ; sinon, garde son journal, puis arrête-le :

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
2. **le `.zip` de la boîte noire**, `docs/releves/seance-2_boite_noire.zip` (étape Fin), et les autres
   s'il y a eu plusieurs séances : avec lui, je revois toute la séance, même ce que la feuille n'a pas eu
   le temps de noter : le diagnostic du début (et celui pris après le lancement de la navigation),
   chaque action et sa réponse, les états du robot, du pont et du guide, la voix et la démo, les journaux
   du serveur et des programmes, **les journaux du conteneur gardés à chaque « Arrêter »** et le rapport ;
3. le journal du pilotage, `docs/releves/seance-2_pilotage.log` (étape P), et, s'il y en a, les journaux
   gardés à la main en secours : `seance-2_conteneur.log` (un conteneur qui tournait encore à la fin),
   `seance-2_relances.log` (un conteneur arrêté hors de l'Atelier) et `seance-2_navigation.log` (sans
   séance ouverte) ;
4. les messages d'erreur, copiés mot pour mot ;
5. ce qui t'a étonné dans le rapport de séance (« À regarder en premier »).

Je retrouverai seul le nouveau scan (`lieux/seance/scans/`), la carte d'Unitree
(`lieux/seance/cartes/rdc_unitree.*`), les réglages de la démo (`lieux/seance/demo.yaml`), les journaux
de l'Atelier (`journaux/`) et ceux de ROS 2 restés sur le Jetson (`~/robot-g1/journaux/jetson/ros/log/`).

Avec tes mesures, je réglerai :

- la vitesse minimale du pont (`config/pont.yaml` et `VITESSES_MIN_PONT`) : un peu au-dessus du seuil
  mesuré ;
- la rotation finale du guide (`tolerance_orientation_rad`, `anticipation_rotation_rad`) ;
- la correction des distances de la caméra et sa position sur le robot ;
- le volume de la voix et la sortie de la démo (la synthèse du robot parle-t-elle français ?), et ce
  qui a gêné pendant la démo.
