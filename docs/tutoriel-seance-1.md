# Séance robot n° 1 : mardi 27 octobre 2026

Ce tutoriel suit toute la journée, dans l'ordre :

1. la veille au soir ;
2. le matin, avant d'allumer le robot ;
3. la séance elle-même, en six étapes ;
4. ce qu'il faut me rapporter.

Le déroulé détaillé d'origine est dans `docs/seance-robot.md`. Ce tutoriel le suit, mais **fait
le scan juste après le branchement**.

**But de la séance :** vérifier que le vrai G1 comprend notre logiciel. Dans l'ordre :

- le scan d'une petite zone ;
- les ordres de marche (le pont) ;
- notre conteneur sur le Jetson ;
- le repérage sur la carte ;
- un premier trajet de 3 m.

**Durée :** environ 1 h 45 avec le robot, plus 30 min la veille et 15 min le matin.

**Ce qui ne change pas dans le robot :**

- Le PC1 d'Unitree, celui de la marche et de l'équilibre, n'est jamais touché.
- Sur le Jetson, on **ajoute** seulement deux choses : une image Docker d'environ 2 Go et un
  dossier `~/robot-g1`.
- Rien n'est installé ni remplacé dans Ubuntu, ROS ou les programmes d'Unitree.
- Notre conteneur ne redémarre jamais tout seul.

Pour tout retirer : `ssh unitree@192.168.123.164 'docker rmi g1-jetson:arm64; rm -rf ~/robot-g1'`.

---

## Les règles d'or : à lire avant tout

1. **Deux personnes.**
   - La première tient la **télécommande officielle pendant toute la séance**. C'est l'arrêt
     d'urgence : en cas de doute, mode amortissement.
   - La seconde est au PC.
2. **Aucune simulation sur le PC pendant que le robot est branché.** La simulation et le robot
   utilisent le même canal ROS (domaine 0). Le faux G1 de la simulation pourrait répondre à la
   place du vrai. Le matin, **redémarre le PC** : c'est le plus sûr.
3. **`source ~/robot-g1/setup/robot.sh` dans CHAQUE terminal** qui parle au robot. Il doit dire
   « le robot répond ». Il ne vaut que pour le terminal où tu le tapes.
4. **Vitesses réduites :** 0,1 m/s au portique, 0,2 m/s pour le premier trajet.
5. **On note tout** dans la feuille de résultats (`docs/releves/seance_2026-10-27.md`, déjà
   prête). Un point qui échoue : on note ce qu'on a vu, puis on passe au suivant s'il n'y a pas de
   danger.

**On arrête la séance** (télécommande, puis amortissement) si l'une de ces choses arrive :

- la télécommande ne reprend pas la main pendant que notre pont envoie des ordres ;
- le robot ne s'arrête pas tout seul quand on coupe le pont ;
- un mouvement part sans qu'on l'ait demandé.

---

## 1. La veille au soir (environ 30 min)

### 1.1 Charger

- [ ] la batterie du robot ;
- [ ] la télécommande officielle ;
- [ ] le PC portable, et prends son chargeur.

### 1.2 Préparer le matériel

- [ ] le portique, avec la sangle ;
- [ ] **le câble Ethernet.** 2 à 3 m suffisent ; 5 m ou plus, c'est mieux pour le scan, où le PC
  suit le robot ;
- [ ] du ruban adhésif de couleur, pour la croix et la flèche au sol ;
- [ ] un mètre ruban ;
- [ ] le téléphone avec l'appli Unitree Explore, chargé ;
- [ ] une zone dégagée d'au moins **5 m × 3 m**, au sol plat et sans marches. Le scan se fera dans
  cette zone.

### 1.3 Sur le PC

Ouvre un terminal (Ctrl+Alt+T) et tape les commandes une par une.

```bash
cd ~/robot-g1

# 1) Arrêter tout ce qui tourne encore (Atelier, simulations).
#    Dans l'Atelier ouvert : « Arrêter la simulation », puis Ctrl+C dans son terminal.
#    Vérifier ensuite qu'il ne reste rien :
pgrep -af "ign gazebo|ros2 launch|uvicorn"        # attendu : aucune ligne

# 2) Vérifier le conteneur, le pont, le repérage, le trajet et la sécurité, en répétition
#    (environ 10 min). Attendu à la fin : « 5 / 5 »
tests_e2e/tout.sh 16 17 18 19 20

# 3) L'image pour le Jetson. Si elle est déjà à jour, la commande le dit en quelques secondes ;
#    sinon, elle prend environ 4 min.
g1-jetson construire

# 4) Le lieu de la séance (une seule fois)
g1-lieu creer seance --nom "Séance robot"

# 5) Une clé ssh, pour ne plus taper le mot de passe du Jetson. Si la première commande affiche
#    un fichier, la clé existe déjà. Sinon, appuie 3 fois sur Entrée.
ls ~/.ssh/id_*.pub || ssh-keygen -t ed25519

# 6) Voir à blanc ce que fera l'envoi au Jetson (rien n'est envoyé)
G1_SLAM_FAUX=1 g1-jetson envoyer --dry-run
```

Si `tout.sh` n'affiche pas « 5 / 5 », envoie-moi la fin de l'affichage avant la séance.

---

## 2. Le matin, avant d'allumer le robot (environ 15 min)

### 2.1 Le PC

1. **Redémarre le PC.**
2. Ouvre un terminal et vérifie qu'aucune simulation ne tourne :

   ```bash
   pgrep -af "ign gazebo|ros2 launch|uvicorn"       # attendu : aucune ligne
   ```

3. Le Wi-Fi du PC reste sur ton réseau habituel, avec Internet : on ne s'en sert pas pour le robot.

### 2.2 Dans l'appli Unitree Explore, robot allumé

**Ne lance pas de mise à jour du robot aujourd'hui.**

- [ ] **Note la version du logiciel du robot** (micrologiciel), dans les informations du robot.
  Le scan et le repérage d'Unitree demandent la **1.5.3 ou plus**. Si elle est plus ancienne, le
  scan et le repérage risquent d'échouer, mais on fera quand même le pont et le conteneur.
- [ ] **Active les services `unitree_slam` et `lidar_driver`.** Ils se trouvent dans la liste des
  services du robot ; le nom exact du menu dépend de la version de l'appli. **Sans eux, le scan
  et le repérage ne marchent pas.**
- [ ] Ensuite, **ne pilote plus le robot avec l'appli** pendant nos essais : une seule source de
  commandes à la fois, en plus de la télécommande.

### 2.3 Le point principal au sol

Avec le ruban adhésif, au bord de la zone dégagée :

- une **croix** : c'est le **point principal**, l'accueil du robot ;
- une **flèche** qui part de la croix : c'est la direction où le robot regardera. Il faut **au
  moins 4 m libres devant**.

Le scan partira de là. Sa carte aura son origine sur la croix et son axe x dans le sens de la
flèche.

### 2.4 La feuille de résultats

Ouvre `~/robot-g1/docs/releves/seance_2026-10-27.md` dans VS Code. Tu y noteras les résultats au
fur et à mesure.

---

## 3. La séance

On utilise **5 terminaux**. Donne-leur un nom pour t'y retrouver. Dans **chacun**, tape d'abord :

```bash
source ~/robot-g1/setup/robot.sh
```

| Terminal | Sert à |
|---|---|
| T1 | l'Atelier (la page web) |
| T2 | le pont |
| T3 | l'état du pont |
| T4 | les réponses du robot |
| T5 | les commandes à la main |

### Étape A : brancher et regarder (10 min)

1. Robot allumé, debout. Attends la fin de son démarrage, environ 1 min.
2. Branche le câble Ethernet entre le PC et le robot.
3. Dans T1 :

   ```bash
   source ~/robot-g1/setup/robot.sh
   ```

   Attendu : « ROS 2 relié au robot par eno2 (PC en 192.168.123.99) : le robot répond. »
   - « Câble non détecté » : le câble est mal branché.
   - Pas de réponse : attends 1 min, puis recommence.
4. Toujours dans T1 :

   ```bash
   g1-etat                    # attendu : « Connecté » et la batterie (Ctrl+C pour quitter)
   ros2 topic list --no-daemon | grep -E 'api/sport|slam|odom_pelvis|sportmodestate'
   ```

   Note dans la feuille (ligne A) si on voit `/api/sport/request`, `/api/slam_operate/request`,
   `/state_estimator/odom_pelvis` et `/lf/sportmodestate`.

### Étape B : le petit scan (15 min)

Le scan n'utilise **ni notre pont ni notre conteneur**. Le robot marche avec **ta télécommande**,
comme d'habitude. Le PC demande seulement au robot de faire sa carte (commande 1801) puis de
l'enregistrer (commande 1802), et il enregistre ce que voit le LiDAR.

1. **Robot sur la croix**, tourné dans le sens de la flèche, debout en **mode marche**.
2. Dans T1 :

   ```bash
   g1-atelier
   ```

   Le navigateur s'ouvre sur l'Atelier.
3. Onglet **Lieux** : choisis **« Séance robot »**.
4. Onglet **Scan** : choisis **Robot**. Ne coche **pas** « Répétition sans robot ». Clique sur
   **Scan**, puis confirme.
   - « Robot non détecté » : `robot.sh` n'a pas été tapé dans T1, ou le câble est débranché.
   - Un message d'erreur au démarrage du scan : **note-le mot pour mot** (ligne B). Vérifie que
     les services `unitree_slam` et `lidar_driver` sont actifs dans l'appli, puis réessaie une
     fois. Si ça échoue encore, passe à l'étape C. Sans carte, les étapes E et F ne pourront pas
     se faire aujourd'hui.
5. **Promène le robot à la télécommande, lentement**, dans toute la zone, pendant 3 à 5 min.
   - Ne coupe pas les virages.
   - La personne du PC suit derrière, **câble lâche**. Ne tire jamais sur le câble : la prise du
     robot est fragile.
   - L'aperçu se remplit en direct à l'écran.
6. **Reviens sur la croix, dans le sens de la flèche**, puis clique sur **Fin**. Attends 10 à 30 s :
   le PC fabrique la carte 2D et reconnaît les objets.
7. **La revue :**
   - la carte ne doit être **ni dédoublée ni tournée** ;
   - décoche ce qui est faux ;
   - clique sur **« Utiliser cette carte pour l'étage »**.
8. Note le nom de la carte enregistrée sur le robot. Dans T5 :

   ```bash
   grep carte_unitree ~/robot-g1/lieux/seance/lieu.yaml
   ```

9. **L'accueil sur la croix, et un but à 3 m devant.** Dans T5, l'Atelier toujours ouvert, copie
   ces deux commandes telles quelles :

   ```bash
   curl -s -X PUT "http://localhost:8000/api/lieux/seance/salles?synchroniser=true" -H 'Content-Type: application/json' \
     -d '[{"id":"accueil","nom":"Accueil","alias":[],"etage":"rdc","pose":{"x":0,"y":0,"theta":0},"phrase_arrivee":""},
          {"id":"essai_3m","nom":"Essai à 3 m","alias":[],"etage":"rdc","pose":{"x":3,"y":0,"theta":0},"phrase_arrivee":""}]'
   curl -s -X PUT http://localhost:8000/api/lieux/seance/itineraires -H 'Content-Type: application/json' \
     -d '{"noeuds":{"accueil":{"etage":"rdc","x":0,"y":0},"essai_3m":{"etage":"rdc","x":3,"y":0}},"couloirs":[["accueil","essai_3m"]]}'
   ```

   Dans l'onglet **Carte**, le point (3 ; 0) doit tomber dans le **blanc** (libre), au milieu de
   la zone dégagée. Sinon, déplace « Essai à 3 m » dans l'onglet **Salles**.
10. Ferme l'Atelier : **Ctrl+C dans T1**.

> **Si accrocher le robot au portique est compliqué chez vous**, tu peux faire cette étape B
> juste avant l'étape E, une fois le robot décroché du portique. L'ordre d'origine de
> `docs/seance-robot.md` est celui-là.

### Étape C : le pont au portique, à 0,1 m/s (25 min)

Le pont transforme nos ordres de vitesse en ordres de marche du robot (commande 7105). Ici, il
tourne **sur le PC**, au câble, avec des vitesses 4 fois plus basses que d'habitude.

1. **Robot accroché au portique**, sangle lâche, pieds au sol, en **mode marche**.
2. **T2, le pont :**

   ```bash
   ros2 run g1_bridge pont --ros-args -p exiger_reperage:=false -p vx_max:=0.1 -p vy_max:=0.05 -p wz_max:=0.15
   ```

3. **T3, l'état du pont :**

   ```bash
   ros2 topic echo /pont/etat --field data
   ```

4. **T4, les réponses du robot :**

   ```bash
   ros2 topic echo /api/sport/response
   ```

5. **Le robot accepte-t-il nos ordres ?** (ligne C1)
   - Au lancement, le pont envoie un ordre d'arrêt pour tester le lien.
   - Attendu : une réponse dans T4, avec `api_id: 7105` et `code: 0`. T3 passe à `pret`.
   - **Note le contenu exact de la réponse.**
   - Si T3 reste sur `robot_muet` : tape `ros2 topic info -v /api/sport/request` dans T5 et note
     ce qui s'affiche. Arrête le pont (Ctrl+C dans T2) et passe à l'étape D : le reste de
     l'étape C ne peut pas se faire.
6. **Un pas en avant**, 2 s à 0,1 m/s. Dans T5 (ligne C2) :

   ```bash
   ros2 topic pub -r 10 -t 20 /cmd_vel geometry_msgs/msg/Twist "{linear: {x: 0.1}}"
   ```

   Attendu : le robot marche doucement pendant 2 s, puis s'arrête de lui-même. Note le délai
   avant le premier pas et si la marche est saccadée.
7. **Tourner, puis un pas de côté**, 2 s chacun (ligne C3) :

   ```bash
   ros2 topic pub -r 10 -t 20 /cmd_vel geometry_msgs/msg/Twist "{angular: {z: 0.15}}"    # tourne à gauche
   ros2 topic pub -r 10 -t 20 /cmd_vel geometry_msgs/msg/Twist "{linear: {y: 0.05}}"     # pas vers la gauche
   ```

8. **Le robot s'arrête-t-il seul si le pont meurt ?** C'est **essentiel** (ligne C4).
   - Lance une marche de 10 s dans T5 :

     ```bash
     ros2 topic pub -r 10 -t 100 /cmd_vel geometry_msgs/msg/Twist "{linear: {x: 0.1}}"
     ```

   - Après 3 s, ouvre un 6e terminal et tue le pont :

     ```bash
     pkill -9 -f lib/g1_bridge/pont
     ```

   - Attendu : le robot s'arrête en **moins d'une seconde**.
   - **S'il continue : télécommande, amortissement, fin de la séance.**
   - Ensuite, relance le pont dans T2 (même commande qu'au point 2).
9. **La télécommande reste-t-elle prioritaire ?** C'est **la condition pour continuer** (ligne C5).
   - Relance la marche de 10 s.
   - Pendant ce temps, la personne à la télécommande arrête le robot avec elle.
   - Attendu : la télécommande gagne **tout de suite**.
10. **Un refus** (ligne C6). Mets le robot en amortissement, ou assis, puis lance une marche de
    2 s : il ne doit pas bouger. Note le code de la réponse dans T4 et le message dans T3.
    Remets ensuite le robot en mode marche.
11. **Nos arrêts** (ligne C7). Pendant une marche de 10 s :

    ```bash
    ros2 topic pub --once /guide/stop std_msgs/msg/Empty "{}"
    ```

    Attendu : arrêt net, puis il repart 1 s plus tard. Ensuite, le verrou :

    ```bash
    ros2 topic pub --once --qos-durability transient_local --qos-reliability reliable /pont/arret std_msgs/msg/Bool "{data: true}"
    ```

    Attendu : arrêt net, puis plus rien ne bouge. Pour enlever le verrou, envoie la même commande
    avec `{data: false}`.
12. Fin de l'étape : **Ctrl+C dans T2**. Le pont envoie un arrêt en quittant. Mets le robot en
    amortissement sur le portique.

### Étape D : notre logiciel sur le Jetson (15 min)

Le robot reste au portique, immobile. Dans T5 :

```bash
ssh-copy-id unitree@192.168.123.164        # une seule fois ; mot de passe : 123
g1-jetson verifier                         # chaque ligne : OK, PROBLÈME ou info
g1-jetson envoyer                          # 2 à 5 min : copie l'image et la charge dans Docker du Jetson
g1-jetson verifier                         # la dernière ligne doit voir /state_estimator/odom_pelvis et /lf/sportmodestate
g1-jetson demarrer --veille
g1-jetson etat                             # attendu : « running »
g1-jetson arreter
```

À noter (ligne D) :

- ce qu'affiche `verifier` : le nom de l'interface réseau du Jetson, la place libre, la mémoire,
  l'écart d'horloge ;
- la durée d'`envoyer`.

**Seul changement système possible :** si `verifier` dit « Docker inutilisable sans sudo », il
faut ajouter l'utilisateur `unitree` au groupe docker :

```bash
ssh unitree@192.168.123.164
sudo usermod -aG docker unitree            # mot de passe : 123
exit
```

Puis relance `g1-jetson verifier`. Si tu préfères ne pas faire ce changement, fais les étapes E et
F avec le **plan B** (navigation sur le PC, section « Si ça ne marche pas »).

Si `verifier` ne voit pas les sujets du robot depuis le conteneur, utilise aussi le **plan B**.

### Étape E : le repérage (25 min)

Il faut la carte de l'étape B.

1. Décroche le robot du portique. Pose-le **sur la croix, dans le sens de la flèche**, en **mode
   marche**.
2. Dans T1, relance l'Atelier avec la vitesse limitée pour le premier trajet :

   ```bash
   G1_VITESSE_MAX=0.2 g1-atelier
   ```

3. Onglet **Lieux** : « Séance robot ». Onglet **Simulation** : mode **Robot**, puis **« Lancer sur
   le robot »**, et confirme.
   - L'Atelier copie le lieu sur le Jetson et démarre notre conteneur.
   - La ligne de démarrage doit dire « vitesse max 0.2 m/s ».
   - Attendu : « Non repéré » dans le panneau Repérage.
4. Dans T4 :

   ```bash
   ros2 topic echo /api/slam_operate/response
   ```

5. Clique sur **« Repérer le robot »** (ligne E1).
   - Attendu, en moins de 20 s : **« Repéré »**, avec la précision.
   - Note le texte de la réponse dans T4 et la durée.
   - En cas d'échec, note le message, puis dans T5 :

     ```bash
     ros2 topic echo --once /slam_info
     g1-jetson journal | tail -n 30
     ```

6. **Ce que publie le robot** (ligne E2). Dans T5 :

   ```bash
   ros2 topic hz /unitree/slam_relocation/odom                    # 5 s, puis Ctrl+C
   ros2 topic echo --once /unitree/slam_relocation/odom --field header
   ros2 topic echo --once /unitree/slam_relocation/odom --field child_frame_id
   ros2 topic hz /unitree/slam_relocation/points                  # 5 s, puis Ctrl+C
   ```

7. **La précision** (ligne E3). Ce test se fait **à la télécommande** : notre logiciel n'envoie rien
   tant qu'on ne lui demande pas de trajet.
   - Avance le robot d'environ 2 m, puis tourne-le d'un quart de tour.
   - À chaque arrêt, compare la position affichée dans l'Atelier (panneau Repérage) avec la mesure
     au mètre ruban depuis la croix.
   - Fais 3 mesures. Attendu : **moins de 10 cm** d'écart.

### Étape F : le premier trajet, 3 m à 0,2 m/s (10 min)

1. Robot repéré, près de la croix. La personne à la télécommande se tient à côté du robot ; celle
   du PC suit, câble lâche.
2. Onglet **Simulation** : **Y aller** vers **« Essai à 3 m »** (ligne F1). Attendu : `en_route`,
   puis le robot marche droit vers le but, puis `arrive`.
3. **Y aller** vers **« Accueil »**, puis clique une fois sur **ARRÊT** à mi-chemin (ligne F2).
   Attendu : arrêt net. Relance ensuite **Y aller** « Accueil ».
4. À l'arrivée, mesure l'écart entre le robot et la croix (ligne F3). Attendu : **moins de 30 cm**.
5. **Bloquer le robot**, puis **Y aller** : il ne doit pas bouger. Puis **Débloquer** (ligne F4).

### Fin (5 min)

1. Garde le journal du conteneur. Dans T5, **avant** d'arrêter :

   ```bash
   g1-jetson journal > ~/robot-g1/docs/releves/seance_2026-10-27_conteneur.log
   ```

2. Dans l'Atelier : **« Arrêter la navigation du robot »**. Le pont envoie un arrêt, et le
   conteneur s'arrête et se retire.
3. Robot en amortissement, puis éteint. Débranche le câble.
4. Complète la feuille de résultats.

---

## 4. Si ça ne marche pas

| Ce que tu vois | Que faire |
|---|---|
| `robot.sh` : « Câble non détecté » | Rebranche le câble des deux côtés et attends 10 s. |
| `robot.sh` : le robot ne répond pas | Robot fini de démarrer ? Attends 1 min et recommence. |
| `g1-etat` ne dit pas « Connecté » | `robot.sh` n'a pas été tapé dans **ce** terminal. |
| Scan : « Robot non détecté » | `robot.sh` dans T1 avant `g1-atelier`, et le câble. |
| Scan : refusé au démarrage | Services `unitree_slam` et `lidar_driver` dans l'appli, et la version du robot (1.5.3 ou plus). Note le message mot pour mot. |
| Carte dédoublée ou tournée | Ne l'adopte pas. Note-le et refais un scan plus lent, sans virages serrés. |
| Le pont reste `robot_muet` | Note la sortie de `ros2 topic info -v /api/sport/request`, puis passe à l'étape D. |
| Le robot ne s'arrête pas seul (C4) | Télécommande, amortissement, **fin de la séance**. Rapporte-le-moi. |
| `ssh` redemande un mot de passe | Refais `ssh-copy-id unitree@192.168.123.164` (mot de passe 123). |
| `envoyer` échoue | Note le message ; `g1-jetson verifier` montre la place libre. Puis plan B. |
| « Repérer » échoue | Note le message, `/slam_info` et `g1-jetson journal \| tail -n 30`. |
| Quelque chose bouge sans qu'on l'ait demandé | Télécommande, amortissement, **fin de la séance**. |

**Plan B : la navigation sur le PC, au câble**, si le conteneur ne marche pas. La personne du PC
suit le robot de près. Dans T2, avec `robot.sh` :

```bash
g1-guide navigation --lieu seance --etage rdc --vitesse-max 0.2
```

Puis, dans T5, avec `robot.sh` :

```bash
ros2 topic pub --once /reperage/demander std_msgs/msg/String "{data: '{\"id\": \"seance-1\", \"x\": 0, \"y\": 0, \"theta\": 0}'}"
ros2 topic echo /reperage/etat --field data       # attendu : "etat": "repere"
g1-guide aller essai_3m
g1-guide stop
```

---

## 5. Après la séance : ce qu'il faut me rapporter

Dis-moi **« séance faite »**, avec :

1. la feuille remplie, `docs/releves/seance_2026-10-27.md` ;
2. le journal du conteneur, `docs/releves/seance_2026-10-27_conteneur.log` ;
3. les messages d'erreur, copiés mot pour mot ;
4. la version du robot lue dans l'appli.

Je retrouverai seul le scan (`lieux/seance/scans/`) et les journaux de l'Atelier (`journaux/`).

Il y aura sûrement quelques écarts entre ce qu'on a prévu et ce que le vrai robot comprend. Je les
corrige à partir de ta feuille.

**La séance suivante** (`docs/seance-robot.md`, sections 6 et 7) testera :

- le pilotage : gestes, danses, joystick, Wi-Fi du Jetson ;
- puis le point principal, les passants et l'accompagnement.
