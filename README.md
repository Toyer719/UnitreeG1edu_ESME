# Robot d'accueil G1

Poste de développement du projet robot d'accueil sur Unitree G1 EDU.
Ubuntu 22.04, ROS 2 Humble, SDK Unitree, simulation MuJoCo.

## Les commandes

Toutes les commandes s'utilisent dans un terminal ouvert après l'installation (Ctrl+Alt+T).

| Commande | À quoi elle sert | Robot nécessaire |
|---|---|---|
| `g1-sim-marche` | G1 qui marche dans MuJoCo, piloté à la manette ou au clavier | non |
| `g1-sim` | Simulateur officiel Unitree : G1 complet relié au SDK | non |
| `g1-sim-demo` | Exemple bas niveau d'Unitree joué dans `g1-sim` | non |
| `g1-etat lo` | État du G1 simulé, en lecture seule | non |
| `source ~/robot-g1/setup/robot.sh` | Relier le PC au robot par le câble Ethernet | oui |
| `g1-etat` | État du vrai G1, en lecture seule | oui |
| `g1-telecommande` | Ce que le G1 reçoit de sa télécommande Unitree (`lo` : simulateur) | oui |
| `g1-releve` | Relevé du robot (version, sujets publiés, LiDAR, Jetson) dans `docs/releves/` | oui |
| `g1-nuage` | Affiche dans RViz le nuage de points du LiDAR publié sur le réseau | oui |
| `g1-premiers-pas` | Premiers tests : voix, LED, gestes, quelques pas | oui |
| `g1-manette` | Piloter le vrai G1 à la manette | oui |
| `g1-manette-virtuelle` | Manette Xbox virtuelle (clavier ou souris), vue comme une vraie | non |
| `g1-personnes` | Détecter et suivre les personnes (webcam ou caméra) | non |
| `g1-parler "texte"` | Voix française hors ligne (Piper) | non |
| `g1-ecouter` | Reconnaissance vocale en français (Vosk, faster-whisper) | non |
| `g1-atelier` | Atelier G1 : décrire ou scanner un lieu, fabriquer la carte, essayer le guide dans Gazebo (section ci-dessous) | non (oui pour scanner un vrai bâtiment) |
| `g1-jetson` | Conteneur de la navigation sur le Jetson du robot : construire, envoyer, démarrer, arrêter (section « Le vrai robot ») | oui (non avec `--local`) |
| `g1-pilotage` | Piloter le G1 comme l'onglet Pilotage de l'Atelier : postures, gestes, voix, LED, danses, chorégraphies (section « Pilotage et danses ») | oui (non contre le faux G1) |

Le calendrier jour par jour, avec toutes les commandes de chaque étape, est sur la page du
projet : https://claude.ai/artifact/3sjPDb9CYcwJGrTZ8vgxNP

Chaque commande accepte `--help`. Pour arrêter une commande : **Ctrl+C** dans le terminal,
ou fermer la fenêtre MuJoCo.

Si un terminal répond « commande introuvable », il a été ouvert avant l'installation :
tapez `source ~/.bashrc` ou ouvrez-en un nouveau.

## Atelier G1 : décrire un lieu et y essayer le guide

L'Atelier G1 sert à décrire un bâtiment (murs, portes, meubles, piétons), à en tirer la carte
de navigation, à placer les salles et les itinéraires, puis à essayer le guide dans Gazebo,
**sans robot**. Il sait aussi **scanner** un étage avec le LiDAR, en simulation ou avec le vrai
G1 (section « Scanner un lieu »). Le même lieu servira ensuite au vrai G1 : seule la carte (scan
au lieu du monde dessiné) et le moteur de déplacement changent.
Plan : `docs/plan-atelier-multi-agents.md`. Décisions et état : `docs/journal-atelier.md`.

### Le plus simple : l'interface web

```bash
g1-atelier                 # ouvre http://localhost:8000 dans le navigateur
```

Les onglets se suivent de gauche à droite : **Lieux** (créer ou choisir un lieu),
**Monde** (dessiner murs, passages, meubles et piétons, vue 3D), **Carte**
(« Fabriquer la carte »), **Salles**, **Itinéraires** (nœuds et couloirs de 8 m au plus),
**Zones** (interdites en rouge, lentes en orange), **Simulation** (« Lancer la simulation »,
puis « Y aller » ; gros bouton ARRÊT) et **Scan** (boutons « Scan » et « Fin », section
« Scanner un lieu » ci-dessous). L'onglet Simulation a trois modes : **Simulation** (Gazebo
seul), **Répétition sans robot** (comme avec le vrai robot, mais contre un faux G1 dans Gazebo :
repérage, pont vers la marche) et **Robot** (section « Le vrai robot »).
Ctrl+C dans le terminal arrête le serveur, et avec lui la simulation et la navigation.

Depuis la vague 4 (section 11 du plan) : le **point principal** du lieu (l'accueil : départ de la
simulation, pose du repérage, retour après chaque visite), des **passants** que le robot contourne
ou attend, l'**accompagnement** du visiteur et le retour automatique, l'onglet **Pilotage**
(postures, joystick, gestes, voix, LED, danses du robot, chorégraphies) et les onglets
**Personnalités**, **Dialogues** et **Caméra** pour l'équipe. Chacun a sa section ci-dessous.

### Les mêmes étapes en ligne de commande

Sur le lieu fourni `demo` (lycée de 30 × 20 m, deux couloirs, accueil et cinq salles) :

```bash
g1-lieu valider --lieu demo                                 # vérifie les fichiers et dit quoi corriger
g1-monde generer --lieu demo --etage rdc                    # monde Gazebo, carte 2D, masque des zones interdites
g1-monde simuler --lieu demo --etage rdc --sans-fenetre     # terminal 1 : Gazebo, robot proxy, piétons
g1-guide navigation --lieu demo --etage rdc --simu          # terminal 2 : Nav2, routeur et guide
g1-guide aller b204                                         # terminal 3 : le robot y va (suit l'état jusqu'à l'arrivée)
g1-guide stop                                               # arrêt immédiat
```

Sans `--sans-fenetre`, Gazebo s'ouvre dans une fenêtre. `--lieu` accepte un id (dossier de
`~/robot-g1/lieux/`) ou un chemin.

| Commande | À quoi elle sert |
|---|---|
| `g1-atelier [--port 8000] [--sans-navigateur] [--hote 0.0.0.0]` | Le logiciel web (`--hote 0.0.0.0` : depuis une tablette du réseau) |
| `g1-lieu creer ID --nom "Nom"`, `g1-lieu valider --lieu L`, `g1-lieu liste` | Créer, vérifier (fichiers de l'équipe compris), lister les lieux |
| `g1-lieu migrer --lieu L [--a-blanc] [--depuis-depart]` | Donne au lieu son point principal (la salle `accueil`), après une sauvegarde (section « Le point principal ») |
| `g1-monde generer --lieu L --etage E` | Monde Gazebo `.sdf`, carte `.pgm`/`.yaml` et masque, depuis le monde dessiné |
| `g1-monde simuler --lieu L --etage E [--sans-fenetre] [--jumeau]` | Gazebo avec le robot proxy (taille du G1, LiDAR à 1,245 m) et les piétons ; `--jumeau` : le faux G1 (répétition) |
| `g1-guide navigation --lieu L --etage E --simu [--localisation unitree\|amcl] [--pont auto\|oui\|non] [--vitesse-max 0.2]` | Nav2, routeur et guide (sans `--simu` : vrai robot) ; `--localisation unitree` : relais et repérage d'Unitree, avec le pont |
| `g1-guide aller ID [--accompagner] [--sans-retour]`, `g1-guide stop`, `g1-guide etat` | Envoyer le robot vers une salle (en accompagnant le visiteur, sans retour seul au point principal), l'arrêter, voir l'état du guide |
| `g1-banc --lieu L --etage E --trajets 20 --lancer` | Banc de test : trajets tirés au sort, résultats en CSV dans `journaux/` |
| `g1-banc --scene ID [--reaction aucune\|arret\|ecart]` | Banc d'une scène de passants (copie du lieu, simulation lancée, trajets, seuils ; section « Les passants ») |
| `g1-slam scan-debut`, `scan-fin --nom N`, `relocaliser`, `aller`, `pause`, `reprendre`, `arreter` | Service de cartographie du G1 (`--faux` : faux service, à lancer avec `g1-slam faux-service` ; `g1-slam faux-service --jumeau --lieu L --etage E` : celui de la répétition) |
| `g1-carte-3d --lieu L --etage E --enregistrement DOSSIER` | Enregistrement ros2 bag → nuage 3D `.pcd` |
| `g1-carte-2d --lieu L --etage E` | Nuage 3D → carte 2D de navigation |
| `g1-salle ajouter "Nom" --lieu L` | Ajoute une salle à la position actuelle du robot |
| `g1-scan demarrer\|arreter\|etat\|traiter\|adopter --lieu L …` | Le scan intégré, comme les boutons « Scan » et « Fin » de l'onglet Scan (section suivante) |
| `g1-jetson construire\|envoyer\|demarrer\|arreter\|etat\|journal\|verifier …` | Le conteneur de la navigation sur le Jetson (section « Le vrai robot » ; `--local` : sur le PC) |

Chaque commande a un alias `gl-…` et accepte `--help`.

### Scanner un lieu

Le scan fabrique la carte 2D d'un étage, et un monde 3D modifiable, à partir de ce que voit le
LiDAR du robot. Tout se fait dans l'onglet **Scan** de l'Atelier : un bouton **Scan** pour
commencer, un bouton **Fin** pour arrêter, et le reste est automatique.

**En simulation** (sans robot, pour essayer ou pour préparer) : le robot simulé de Gazebo, à la
taille du G1, scanne le monde dessiné de l'étage.

1. Onglet **Carte** : « Fabriquer la carte », si ce n'est pas déjà fait (le robot simulé a besoin
   du monde Gazebo de l'étage).
2. Onglet **Scan** : choisissez **Simulation**. Cochez **Exploration automatique** pour que le
   robot fasse seul le tour des couloirs de l'onglet Itinéraires ; sinon, conduisez-le avec les
   flèches de l'écran ou du clavier (il s'arrête dès qu'on lâche).
3. Cliquez sur **Scan**. Après 10 à 20 s (démarrage de Gazebo), l'aperçu se remplit en direct :
   murs vus d'en haut, trajet du robot, nuage de points en 3D, durée et distance.
4. Cliquez sur **Fin** quand tout l'étage a été vu. Avec l'exploration, le scan s'arrête de
   lui-même à la fin du tour (environ 3 min pour le lieu `demo`).
5. Une barre suit la suite, automatique : carte 3D, carte 2D, reconnaissance, monde (10 à 30 s).
6. La revue montre ce qui a été reconnu : murs, passages (les portes) et objets (tables, chaises,
   bancs, poubelles, poteaux, meubles, personnes), chacun avec une case **garder**. Les personnes
   sont décochées d'office : elles ne vont jamais sur la carte. Décochez ce qui est faux.
7. Choisissez :
   - **Utiliser cette carte pour l'étage** : la carte du scan remplace celle de l'étage ;
   - **Ouvrir dans l'éditeur du monde** : la carte **et** le monde du scan remplacent ceux de
     l'étage (l'ancien monde est gardé dans le dossier du scan), puis l'onglet **Monde** s'ouvre.
     On y modifie le monde du scan comme un monde dessiné, et l'onglet **Simulation** le lance
     dans Gazebo pour essayer le guide.

**Avec le vrai robot** : le PC suit le robot au câble. Les données du scan n'arrivent au PC que par
le câble Ethernet, pas par le Wi-Fi. Il faut deux personnes : l'une pilote le robot à la
télécommande, l'autre marche derrière avec le PC portable, relié au robot par un câble de 2 à 3 m.

1. Robot allumé et debout en mode marche, dans une zone dégagée ; dans l'appli Unitree, les
   services `unitree_slam` et `lidar_driver` sont activés.
2. Branchez le câble, puis dans un terminal : `source ~/robot-g1/setup/robot.sh` (doit dire « le
   robot répond »).
3. `g1-atelier`, onglet **Scan** : choisissez **Robot**, cliquez sur **Scan** et confirmez. Le PC
   demande au robot de commencer sa cartographie (commande 1801) et enregistre ce que le robot
   publie (`/unitree/slam_mapping/points` et `/unitree/slam_mapping/odom`). Sans câble, l'Atelier
   répond « Robot non détecté » et ne lance rien.
4. Promenez le robot lentement dans tout l'étage, câble lâche, sans couper les virages. Les flèches
   de l'écran ne servent pas avec le vrai robot : il se pilote à la télécommande, qui reste
   l'arrêt d'urgence.
5. Revenez près du point de départ, puis **Fin** : le robot enregistre sa propre carte (commande
   1802, fichier `<etage>_<session>.pcd` sur le robot) et le PC fabrique la carte 2D et le monde,
   comme en simulation.
6. Revue et adoption, comme en simulation. Le repère du scan du robot (origine au point de départ)
   n'est pas celui du monde dessiné : replacez ensuite les salles, les itinéraires et les zones sur
   la nouvelle carte.

Pour s'entraîner sans robot, cochez **Répétition sans robot** en mode Robot : tout le déroulé du
mode robot est joué avec un faux service de cartographie et le robot simulé.

**Attention** : le mode robot n'a encore jamais été essayé sur le vrai G1, seulement en
répétition. Au premier vrai scan, vérifiez la carte (elle ne doit être ni dédoublée ni tournée) et
lisez les avertissements du rapport.

Les mêmes étapes en ligne de commande :

```bash
g1-scan demarrer --lieu demo --etage rdc --mode simu --explorer   # « Scan » : rend la main tout de suite
g1-scan etat --lieu demo                                          # où en est le scan
g1-scan arreter --lieu demo --attendre                            # « Fin », puis attend la carte et le monde
g1-scan adopter --lieu demo --session 2026-10-25_17h42 --monde    # adopte la carte et le monde du scan
```

Vrai robot : `--mode robot` (câble branché et `source ~/robot-g1/setup/robot.sh` fait) ;
répétition sans robot : `--mode robot --repetition`. Chaque scan est rangé dans
`lieux/<id>/scans/<date>_<heure>/` (enregistrement, aperçu, nuage 3D, carte, reconnaissance,
monde, `rapport.json`). L'enregistrement pèse environ 100 Mo par minute de scan ; il n'est pas
sauvegardé par Git : effacez le dossier `enregistrement/` quand le scan est adopté.

### Le point principal

Chaque lieu a **un seul point principal** : l'accueil, où le robot attend les visiteurs. C'est une
salle de `salles.yaml` qui porte l'étiquette `principal`, avec une flèche (le sens du robot). Il sert
à trois choses :

- la **simulation** part de lui (le départ du robot du monde de son étage le suit) ;
- le **repérage** du vrai robot part de lui : on pose le robot sur le point principal, dans le sens
  de la flèche, puis « Repérer le robot » (plus besoin de la marque au départ du scan) ;
- le **retour** : après chaque visite, le guide revient seul au point principal et se tourne dans le
  sens de la flèche.

Dans l'Atelier, onglet **Salles** : le point principal est dessiné d'une étoile et d'une flèche.
Pour en changer : choisissez la salle, puis **« Faire de cette salle le point principal »**. Pour
le tourner : glissez la flèche (par pas de 15°), puis **« Enregistrer les salles »**. On ne peut pas
supprimer le point principal sans en avoir choisi un autre. Un lieu d'avant la vague 4 sans
étiquette prend la salle `accueil` ; un lieu sans point principal du tout est refusé par
`g1-lieu valider`, et l'Atelier refuse d'y lancer la simulation.

Pour donner explicitement son point principal à un lieu existant (une sauvegarde est faite d'abord
dans `lieux/<id>/sauvegardes/`, avec un `LISEZMOI.txt` pour revenir en arrière) :

```bash
g1-lieu migrer --lieu bomboclat --a-blanc      # montre ce qui changerait, sans rien écrire
g1-lieu migrer --lieu bomboclat                # sauvegarde, puis étiquette « principal » sur la salle accueil
g1-lieu migrer --lieu L --depuis-depart        # le point principal prend d'abord la pose du départ du robot
g1-lieu valider --lieu bomboclat               # vérifie tout, fichiers de l'équipe compris
```

`lieux/demo` (la référence des tests) n'est jamais migré. API : `GET` et `PUT
/api/lieux/{id}/principal` (`{salle?, x?, y?, theta?}`).

### Les passants

Dans Gazebo, chaque piéton du monde est un **corps** (cylindre de 0,25 m de rayon, 1,7 m de haut)
que le LiDAR voit et que le robot ne peut pas traverser, et il **réagit** au robot (champ `reaction`
d'un piéton, onglet Monde) : `ecart` (défaut : il ralentit et s'écarte, ou attend 8 s au plus s'il
ne peut pas passer), `arret` (il s'arrête), `aucune` (il ne voit pas le robot : le pire cas).
`g1-monde simuler … ` lance les corps (argument `pietons:=corps` de `simulation.launch.py`, ou
`acteurs` pour les silhouettes de la vague 1).

Ce que fait le robot : il garde ses distances (carte des coûts locale, inflation de 0,9 m), voit les
obstacles bas de 0,15 à 1,9 m, ralentit de moitié quand un obstacle (une personne) est à moins de
1 m devant lui ou à moins de 0,7 m tout autour, et s'arrête à 0,4 m. Si une personne lui bouche le passage (aucun
progrès depuis 3 s, une personne vue à moins de 2,5 m devant lui ou dans la direction du couloir),
il **s'arrête et attend** (« Pardon, puis-je passer ? »), repart quand le passage est libre
(« Merci ! »), ou prend un autre couloir après 20 s (`delai_passant_s`).

Scènes de test (`atelier/monde/scenes/`, sur des copies du lieu `demo`) : `immobile_couloir`,
`en_face`, `coupe_route`, `groupe_couloir`, `groupe_reste`, `foule`, `accompagnement` :

```bash
g1-banc --scene immobile_couloir                  # copie du demo, simulation sans fenêtre, 5 trajets, seuils
g1-banc --scene en_face --reaction ecart          # même scène, piétons qui s'écartent
g1-banc --scene foule                             # les 5 piétons du demo, 20 trajets tirés au sort
```

Le CSV (dans `journaux/`) compte les contacts, leur cause (robot ou piéton), la distance bord à bord
la plus courte, les attentes de passage et la longueur parcourue. Dans l'onglet **Simulation**, le
panneau **Passants** montre les piétons en direct, la distance au plus proche, les scènes et les
derniers bancs.

### Accompagnement du visiteur et retour au point principal

Le guide (`g1_nav`) sait maintenant :

- **accompagner** : au départ, le visiteur est la personne vue au LiDAR la plus proche derrière le
  robot (moins de 2,5 m) ; s'il traîne à plus de 2 m, le robot ralentit ; à plus de 3,5 m (ou plus
  vu), il l'attend 30 s au plus, puis abandonne et rentre. Sans visiteur au départ, il part seul ;
- **revenir seul** au point principal 15 s après l'arrivée (ou un abandon, ou un échec) ;
- **se dire perdu** quand le repérage se perd : il s'arrête, attend 30 s au plus de retrouver sa
  position, puis échoue avec un message qui dit quoi faire ;
- **attendre les passants** (section précédente) ;
- **annoncer** chaque étape au visiteur, en français, sur `/guide/evenement` (la voix de l'équipe
  les dit) : « Suivez-moi, je vous emmène à … », « Je vous attends. », « Je retourne à l'accueil. »…

```bash
g1-guide aller b204 --accompagner          # le robot suit le visiteur des yeux, ralentit ou l'attend
g1-guide aller b204 --sans-retour          # il reste à b204
g1-guide aller principal                   # retour au point principal
g1-guide navigation --lieu L --etage E --simu --sans-personnes   # sans détecteur de personnes
```

Les délais se règlent par lieu, dans une section facultative de `lieu.yaml` :

```yaml
guide: {retour_auto: true, delai_avant_retour_s: 15, delai_visiteur_s: 30, distance_ralentir_m: 2.0,
        distance_attendre_m: 3.5, ralenti: 0.5, delai_perdu_s: 30, delai_passant_s: 20}
```

Dans l'onglet **Simulation**, le panneau **Comportement du guide** : « Accompagner un visiteur »
vers une salle (avec ou sans retour), l'état du guide et du visiteur, les derniers événements, et
le **faux visiteur** de la simulation (Suivre, Traîner, Partir), qui joue un visiteur dans Gazebo.

### Pilotage et danses

L'onglet **Pilotage** pilote le robot comme l'appli Unitree Explore. Une barre reste toujours en
haut : l'état, la batterie, **Prendre la main** / **Rendre la main**, et le gros bouton **ARRÊT**
(touche Échap). Trois sous-onglets :

- **Commandes** : postures (500 démarrer, 706 accroupi ↔ debout, 702 se relever, 3 s'asseoir ;
  1 amortir et 0 couple nul seulement avec la case « robot au portique » et une double
  confirmation), **joystick** (tactile sur une tablette ; le robot s'arrête seul 0,5 s après le
  dernier ordre, ou dès que la page ou le Wi-Fi se coupe), gestes des bras, voix du robot, volume,
  LED ;
- **Danses du robot** : la liste lue dans le robot ; 401, 402 et 403 sont toujours interdites ;
  chaque danse demande la case « zone libre de 2 à 3 m autour du robot » ;
- **Mes chorégraphies** : éditeur à ligne de temps (poses des bras, pas de marche, gestes, LED,
  paroles, musique) et **aperçu 3D** du G1 avant de jouer. Les bras passent par rt/arm_sdk avec des
  rampes, des angles et des vitesses bornés ; les jambes restent au contrôleur d'Unitree.

**La Vue du robot** (sous « Commandes » et « Danses du robot », pliable avec « Masquer la vue ») montre
ce que fait le robot, sans rien commander :

- une **carte** du lieu en cours (simulation, répétition ou robot) avec la position et le cap du
  robot et les passants, comme l'onglet Simulation (en répétition et avec le robot, il faut avoir
  cliqué « Repérer le robot » dans l'onglet Simulation) ; « Suivre le robot » la recentre ;
- **le G1 en 3D** : la posture d'après le mode du robot (debout, accroupi, assis, amorti), les
  jambes qui marchent avec le joystick, les gestes des bras et la danse du robot en **aperçu
  approché** (le vrai mouvement est dans le robot ; une danse montre sa barre de progression), et
  une chorégraphie de l'Atelier avec ses **vraies poses** ;
- la **caméra de la tête** : avec le robot, quelques images par seconde (bouton « Voir » /
  « Couper », seulement quand la vue est à l'écran) ; en répétition, une image de remplacement, et
  « Voir » montre l'image de test du faux G1 (toute la chaîne de la vidéo est essayée).

**Un seul maître des mouvements** : tant que le guide a la main, le pilotage refuse joystick,
postures, gestes et danses (voix, LED et ARRÊT restent permis) ; quand le pilotage a la main, le
guide refuse les visites et le pont ignore Nav2. **ARRÊT est toujours permis.** La télécommande
reste l'arrêt d'urgence (une danse du robot ne s'interrompt que par elle).

```bash
g1-pilotage noeud                              # simulation ou répétition : le nœud pilotage sur le PC
g1-pilotage prendre                            # prendre la main (--forcer pendant une visite : le guide s'arrête)
g1-pilotage posture 706                        # accroupi ↔ debout
g1-pilotage geste 26                           # grand salut (99 : relâcher les bras)
g1-pilotage dire "Bonjour" ; g1-pilotage led 0 120 255 ; g1-pilotage volume 70
g1-pilotage danses --lire                      # la liste des danses du robot
g1-pilotage danse 604 --zone-libre             # une danse courte, zone libre confirmée
g1-pilotage verifier exemple_kpop              # vérifie une chorégraphie (limites, vitesses, pas)
g1-pilotage jouer exemple_kpop --zone-libre    # la joue
g1-pilotage arret                              # ARRÊT
g1-pilotage rendre                             # rendre la main au guide
g1-pilotage importer-video danse.mp4 --id ma_danse   # bras d'une vidéo filmée de face (pose YOLO, hors ligne)
```

Dans l'Atelier, en simulation ou en répétition : bouton **« Démarrer le pilotage »** de l'onglet
(le nœud tourne sur le PC, contre le faux G1). Avec le robot : le nœud tourne dans le conteneur du
Jetson (`G1_PILOTAGE=1`, défaut de `g1-jetson demarrer`), joint par le Wi-Fi ou le câble :
`G1_PILOTAGE_URL=http://<adresse du Jetson>:8010 g1-atelier` (jeton partagé dans
`opt/jetson/jeton_pilotage`, ou `G1_PILOTAGE_JETON`). Les chorégraphies sont dans
`~/robot-g1/choregraphies/` (`exemple_kpop` : 29 s sur un battement généré) ; vos musiques vont dans
`choregraphies/musique/`, jamais dans Git. Détails : `ws/src/g1_pilotage/LISEZMOI.md`.

La caméra de la tête passe par le service `videohub` du robot (une image JPEG à chaque demande,
5 par seconde au plus, partagée entre les pages) : le nœud pilotage la demande seulement quand une
page la regarde, et l'Atelier la relaie (`GET /api/pilotage/camera`). Le flux H264 de
`/frontvideostream` n'est jamais lu. **À vérifier sur le robot** (`docs/seance-robot.md`, 6.12).

### L'équipe : personnalités, dialogues, caméra

Trois fichiers facultatifs du lieu, chacun avec son onglet et un bouton « Partir de l'exemple » :

- `personnalites.yaml` (onglet **Personnalités**) : les modes du robot (salutation, voix et son
  nom, couleur de la LED, geste de salut, vitesse maximale, phrases du guide) ; la personnalité
  active part sur `/personnalite/active` : le guide applique sa vitesse maximale, le nœud pilotage
  sa LED ;
- `dialogues.yaml` (onglet **Dialogues**) : le chatbot à règles (guider, dire, personnalité, stop,
  geste) ; « Essayer » montre la réponse d'une phrase sans rien faire bouger ;
- `camera.yaml` (onglet **Caméra**) : la See3CAM_11CUG, sa position sur le robot (tangage positif :
  vers le bas) et la détection des visiteurs.

Pour essayer sans la caméra ni la voix de l'équipe (simulation lancée) :

```bash
ros2 run g1_equipe dialogue --ros-args -p lieu:=demo -p etage:=rdc     # chatbot d'exemple et relais
ros2 run g1_equipe voix_journal                                         # écrit ce que le robot dirait
ros2 topic pub --once /visiteur/texte std_msgs/msg/String "{data: 'je cherche la salle b204'}"
```

Le robot répond (« Je vous emmène à Salle B204. Suivez-moi ! ») et le guide y va. Le guide pour les
coéquipiers (sujets, formats, comment brancher la See3CAM, le chatbot et la voix) :
**`docs/integration-equipe.md`**.

### Les fichiers d'un lieu

```
lieux/<id>/
├── lieu.yaml                          nom, étages, accueil
├── mondes/<etage>.monde.yaml          monde dessiné : murs, objets, piétons, départ du robot
├── mondes/<etage>.sdf                 monde Gazebo (généré)
├── cartes/<etage>.pgm + .yaml         carte de navigation (générée, ou issue du scan)
├── cartes/<etage>_interdit.pgm + .yaml   masque des zones interdites (généré)
├── salles.yaml                        salles : nom, alias, position devant la porte, phrase d'arrivée ;
│                                      la salle qui porte l'étiquette « principal » est le point principal
├── itineraires.yaml                   nœuds et couloirs du guide
├── zones.yaml                         zones interdites et lentes
├── personnalites.yaml, dialogues.yaml, camera.yaml   pour l'équipe (vague 4, facultatifs)
├── sauvegardes/<date>_<raison>/       copies faites avant une migration (g1-lieu migrer, vague 4)
└── scans/<date>_<heure>/              un dossier par scan (session.json, carte, reconnaissance, monde…)
```

Les formats exacts sont dans `atelier/lieu/schemas/` et dans la section 4 du plan.

### Tester

```bash
cd ~/robot-g1 && .venv-projet/bin/python -m pytest atelier/tests -q    # bibliothèques, scan, serveur, interface : 4 min environ
cd ~/robot-g1 && .venv-projet/bin/python -m pytest docker/tests -q    # conteneur du Jetson : 30 s
cd ~/robot-g1/ws && colcon test --executor sequential --packages-select g1_sim g1_nav g1_bridge g1_jumeau g1_pilotage g1_equipe && colcon test-result --all   # paquets ROS 2
~/robot-g1/tests_e2e/tout.sh            # les 30 critères de recette, sans fenêtre : « N / 30 » (3 h environ)
~/robot-g1/tests_e2e/tout.sh 1 2 3 4    # seulement certains (11 à 15 : le scan ; 16 à 20 : le vrai robot en répétition ;
                                        # 21 à 30 : point principal, passants, guide, pilotage, équipe)
```

Tous les tests tournent sans robot et sans écran, sur des copies de `lieux/demo` dans des
dossiers temporaires. Journaux : `~/robot-g1/journaux/`.

Après une modification de `ws/src` (nouveau fichier, lancement, réglage), recompilez, puis
refaites l'image du Jetson (elle contient `g1_nav`, `g1_bridge`, `g1_pilotage`, `g1_equipe` et
`atelier/lieu`, `atelier/equipe`) :

```bash
cd ~/robot-g1/ws && colcon build --symlink-install
g1-jetson construire --arch amd64 && g1-jetson construire     # 30 s pour l'amd64, quelques minutes pour l'arm64
```

## Simulation

### Le G1 qui marche : `g1-sim-marche`

Le G1 marche grâce à la politique pré-entraînée d'Unitree. Vous lui donnez trois consignes :
avancer (m/s), glisser sur le côté (m/s), tourner (rad/s). Ce sont exactement les trois
valeurs que le vrai robot reçoit avec `LocoClient.Move(vx, vy, vyaw)`.

| Action | Manette | Clavier (fenêtre MuJoCo active) |
|---|---|---|
| Avancer / reculer | stick gauche haut / bas | flèches haut / bas (+/- 0,1 m/s par appui) |
| Glisser sur le côté | stick gauche gauche / droite | Page préc. / Page suiv. |
| Tourner | stick droit | flèches gauche / droite |
| Stop | B | Fin |
| Relever le robot tombé | A | Origine |

La caméra suit le robot. La souris tourne la vue (clic gauche) et zoome (molette).

**Sans manette physique :** lancez d'abord `g1-manette-virtuelle` dans un terminal, puis
`g1-sim-marche` dans un autre. Gardez la fenêtre de la manette virtuelle active :
Z Q S D = stick gauche, flèches = stick droit, Espace = A, B = B, Maj gauche = LB.
Activation une seule fois : `sudo bash ~/robot-g1/setup/activer_manette_virtuelle.sh`.
`g1-sim-marche --test 10` vérifie sans fenêtre que le robot marche 10 s sans tomber.

### Le simulateur officiel : `g1-sim`

Il reproduit le vrai G1 vu par le SDK, moteur par moteur. Un programme du SDK ne voit pas
la différence : il suffit de remplacer l'interface réseau `eno2` par `lo`.

- Le robot pend à un élastique virtuel, comme sur le portique : touche **7** pour le remonter,
  **8** pour le descendre, **9** pour le détacher ou le rattacher.
- Sans programme qui commande ses moteurs, le robot reste mou : c'est normal.
- Une manette branchée au lancement remplace la télécommande Unitree, y compris la manette
  virtuelle (`g1-manette-virtuelle`, à lancer avant). `g1-telecommande lo` affiche ce que le
  robot simulé reçoit.
- `g1-sim --ddl 23` charge la version à 23 degrés de liberté (29 par défaut).

Pour voir le SDK piloter le robot simulé, ouvrez un deuxième terminal pendant que `g1-sim` tourne :

```bash
g1-etat lo       # lit l'état du robot simulé (Ctrl+C pour quitter)
g1-sim-demo      # fait bouger chevilles et bras, moteur par moteur
```

Dans vos propres programmes Python :

```python
from unitree_sdk2py.core.channel import ChannelFactoryInitialize
ChannelFactoryInitialize(0, "lo")     # simulateur
ChannelFactoryInitialize(0, "eno2")   # vrai robot
```

**Limite à connaître :** le simulateur ne contient que la partie bas niveau. La marche
intégrée d'Unitree (`LocoClient`), la voix, la LED et les gestes n'existent que sur le
vrai robot. En simulation, ces appels renvoient l'erreur 3102 ou 3104, c'est normal.

### LiDAR et cartographie

Le pilote du LiDAR (Livox MID-360) et FAST-LIO2 sont dans l'espace de travail `~/robot-g1/ws`.
Adresses réglées pour le G1 dans `ws/src/livox_ros_driver2/config/MID360_config.json` :
PC en 192.168.123.99, LiDAR en 192.168.123.120 (adresse habituelle, à vérifier).

```bash
ros2 launch livox_ros_driver2 rviz_MID360_launch.py                 # voir le nuage de points
ros2 launch livox_ros_driver2 msg_MID360_launch.py                  # format pour FAST-LIO2
ros2 launch fast_lio mapping.launch.py config_file:=mid360.yaml    # carte 3D en direct
```

### Gazebo (navigation)

Gazebo Fortress et Nav2 sont installés. Le monde du bâtiment, le robot « proxy » et la
navigation sont ceux de l'Atelier G1 (section ci-dessus : `g1-monde simuler`,
`g1-guide navigation`). Pour vérifier que Gazebo s'ouvre : `ign gazebo shapes.sdf`.

## Le vrai robot

### Avant chaque séance

1. Robot sur son portique, zone dégagée.
2. Une personne garde la télécommande officielle en main pendant tout l'essai.
3. Chargeur du PC branché, batterie du robot chargée.

### La télécommande officielle

Elle reste l'arrêt d'urgence, même quand le PC pilote le robot. Trois modes comptent pour
ce projet (combinaisons de boutons exactes dans le manuel du G1) :

- **amortissement** : les moteurs se relâchent doucement, c'est l'arrêt d'urgence ;
- **mode marche** : le contrôleur d'Unitree tient le robot debout ; `g1-premiers-pas`
  et `g1-manette` en ont besoin ;
- **mode debug** : coupe le contrôleur de marche. Ne jamais l'utiliser hors du portique.
  Ce projet n'en a pas besoin.

### Relier le PC au robot

Branchez le câble Ethernet entre le PC et le robot, puis :

```bash
source ~/robot-g1/setup/robot.sh   # PC en 192.168.123.99 sur le port eno2
g1-etat                            # doit afficher « Connecté »
```

`g1-etat` affiche le nombre de moteurs actifs : 23 ou 29 selon la version de votre G1.
`robot.sh` ne vaut que pour le terminal où vous le lancez : relancez-le dans chaque
nouveau terminal qui parle au robot.

### Premiers tests : `g1-premiers-pas`

Un menu propose, dans l'ordre conseillé : faire parler le robot, changer la LED, faire un
geste, faire coucou, avancer à 0,2 m/s pendant 2 s, tourner sur place. Chaque déplacement
demande une confirmation de sécurité. La voix intégrée ne parle pas français ; la voix
française (Piper) viendra plus tard.

### Piloter à la manette : `g1-manette`

| Bouton | Effet |
|---|---|
| LB (L1) **maintenu** | autorise le mouvement ; relâché, le robot s'arrête |
| Stick gauche | avancer / reculer, glisser |
| Stick droit | tourner |
| B (rond) | arrêt immédiat |
| A (croix) | coucou, robot à l'arrêt |

Vitesse limitée à 0,3 m/s par défaut ; `g1-manette --vitesse-max 0.5` pour aller plus vite
(plafond 0,6 m/s). Chaque consigne envoyée au robot ne vaut que 0,5 s : si la manette se
débranche ou si le programme s'arrête, le robot doit s'arrêter de lui-même. Vérifiez-le lors
du premier essai, robot sur le portique.

### Le guide sur le vrai robot : navigation de niveau 2

Le guide de l'Atelier conduit le vrai G1 avec Nav2. Trois pièces font le lien avec le robot (et,
depuis la vague 4, le nœud pilotage de l'onglet Pilotage, dans le même conteneur) :

- **le conteneur `g1-jetson`**, sur le Jetson du robot : ROS 2 Humble, Nav2, le guide, le relais
  de position et le pont ;
- **le pont** (`g1_bridge`) : il traduit les vitesses de Nav2 (`/cmd_vel`) en ordres de marche du
  robot (`/api/sport/request`, ordre 7105), avec les sécurités ci-dessous ;
- **le repérage** : au démarrage, le robot posé sur le point principal du lieu (dans le sens de sa
  flèche), « Repérer le robot » envoie la commande 1804 au service de cartographie d'Unitree, avec
  la pose du point principal ; le relais `odom_vers_tf` transforme ensuite la position fournie par
  Unitree en repères pour Nav2.

**État** : tout est prêt et répété sans robot, contre un faux G1 dans Gazebo (critères 16 à 20 de
`tests_e2e/tout.sh`). Rien n'a encore été essayé sur le vrai G1 : les formats des messages
viennent d'un projet tiers. La première fois, suivez **`docs/seance-robot.md`** (séance de 1 h 30 :
le pont au portique, à vitesse réduite, puis le repérage, puis un premier trajet court).

#### 1. Installer le conteneur sur le Jetson

Une fois, puis après chaque modification de `g1_nav` ou `g1_bridge`. Le PC est relié au robot par
le câble (`source ~/robot-g1/setup/robot.sh`). Pas à pas et dépannage : `docs/jetson.md`.

```bash
g1-jetson construire                         # sur le PC, sans robot : l'image du Jetson (4 min, puis 30 s)
ssh-copy-id unitree@192.168.123.164          # une seule fois (mot de passe 123)
g1-jetson verifier                           # Docker, place, mémoire, réseau du robot
g1-jetson envoyer                            # copie l'image sur le Jetson (2 à 5 min)
g1-jetson verifier                           # doit voir les sujets du robot depuis le conteneur
```

#### 2. La carte et le point principal

Le robot navigue sur la carte d'un **scan fait avec lui** (onglet Scan, mode Robot, section
« Scanner un lieu »), adoptée pour l'étage. Placez ensuite les salles et les itinéraires sur la
nouvelle carte, et le **point principal** (onglet Salles, section « Le point principal ») : c'est
là qu'on pose le robot avant de le repérer. Marquez-le au sol d'une croix et d'une flèche (le sens
du robot). Le plus simple, au début : le point principal au point de départ du scan.

#### 3. Se repérer et lancer la navigation

```bash
source ~/robot-g1/setup/robot.sh      # câble branché : « le robot répond »
g1-atelier                            # ou G1_VITESSE_MAX=0.2 g1-atelier pour les premiers essais
```

1. Onglet **Simulation**, mode **Robot**, **Lancer sur le robot**, et confirmer : l'Atelier lance
   le conteneur sur le Jetson (`g1-jetson demarrer`, le lieu y est copié).
2. Posez le robot **sur le point principal, dans le sens de la flèche** (l'étoile sur la carte),
   debout en mode marche.
3. **Repérer le robot** : « Repéré », avec la précision, en quelques secondes. Si le robot n'est
   pas sur le point principal : « Le robot n'est pas sur le point principal », cliquez sa position
   sur la carte, glissez vers son orientation, puis repérez.
4. **Y aller** vers une salle. « Y aller » reste grisé tant que le robot n'est pas repéré.
5. Pour finir : **Arrêter la navigation du robot** (arrêt propre du conteneur).

Sans l'Atelier : `g1-jetson demarrer --lieu L --etage E [--vitesse-max 0.2]`, `g1-jetson etat`,
`g1-jetson journal -f`, `g1-jetson arreter` ; `g1-guide aller ID` et `g1-guide stop`.

#### 4. Les sécurités

- **La télécommande reste l'arrêt d'urgence**, toujours en main pendant que le robot navigue.
- **Vitesses plafonnées** par le pont : 0,4 m/s en avant, 0,25 m/s de côté, 0,6 rad/s en rotation.
  Une valeur absurde (NaN, infini) donne un arrêt ; le pont refuse de démarrer avec des plafonds
  plus hauts. Premiers essais : `G1_VITESSE_MAX=0.2` (ou `--vitesse-max 0.2`) baisse les trois
  plafonds dans la même proportion.
- **Chaque ordre ne vaut que 0,5 s** : si le pont, le conteneur ou le Jetson s'arrête, le robot
  s'arrête seul. Le pont envoie aussi un arrêt 0,3 s après la dernière consigne de Nav2, et un
  arrêt quand il quitte.
- **Pas de mouvement sans repérage** : tant que le robot n'est pas repéré, ou si le repérage est
  perdu (plus de position d'Unitree depuis 3 s), le pont refuse de le faire bouger.
- **ARRÊT** (Atelier, ou `g1-guide stop`) : arrêt immédiat, puis 1 s sans mouvement.
  **Bloquer le robot** : il reste immobile, quoi qu'on lui demande, jusqu'à « Débloquer ».
- Si le robot ne répond plus (`robot_muet`) ou refuse les ordres (`refus`, par exemple hors du
  mode marche), le pont le dit en français dans l'onglet Simulation.
- Le conteneur ne redémarre jamais seul : on ne relance pas une navigation sans un humain.

#### 5. Répéter sans robot

Onglet **Simulation**, mode **Répétition sans robot** : tout le déroulé ci-dessus (repérage, pont,
« Y aller ») est joué avec un faux G1 dans Gazebo, qui répond comme le vrai. Les mêmes étapes en
ligne de commande :

```bash
g1-monde simuler --lieu demo --etage rdc --sans-fenetre --jumeau        # terminal 1 : Gazebo et le faux G1
g1-slam faux-service --jumeau --lieu demo --etage rdc                    # terminal 2 : faux service de cartographie
g1-guide navigation --lieu demo --etage rdc --simu --localisation unitree   # terminal 3 : relais, pont, Nav2, guide
```

Puis « Repérer le robot » et « Y aller » dans l'Atelier. Le conteneur se répète aussi sur le PC :
`g1-jetson tester-local --lieu demo --etage rdc`, et les critères `tests_e2e/tout.sh 16 17 18 19 20`.

## Dépannage

| Message | Cause probable |
|---|---|
| « Aucune donnée du robot sur eno2 » | robot éteint, câble débranché, ou `robot.sh` pas lancé dans ce terminal |
| « Aucune donnée du robot sur lo » | `g1-sim` n'est pas lancé |
| Erreur 3104 (pas de réponse) | robot pas en mode marche, ou commande lancée sur le simulateur |
| Erreur 3102 (envoi impossible) | service absent : normal sur le simulateur |
| `selected interface "lo" is not multicast-capable` | normal, sans conséquence |
| « Aucune manette détectée » | brancher la manette en USB avant de lancer ; vérifier avec `ls /dev/input/js*` |
| Simulation saccadée | lancer avec la carte NVIDIA : `__NV_PRIME_RENDER_OFFLOAD=1 __GLX_VENDOR_LIBRARY_NAME=nvidia g1-sim` |

## Contenu du dossier

```
robot-g1/
├── bin/            commandes g1-*
├── sim/            scripts de simulation
├── robot/          scripts pour le vrai robot
├── outils/         modules communs (manette, connexion, état)
├── atelier/        Atelier G1 : lieu, monde, scan, serveur web, interface, tests
├── lieux/          paquets de lieu (demo : le lycée d'exemple)
├── tests_e2e/      critères de recette de l'Atelier (tout.sh)
├── docker/         conteneur de la navigation pour le Jetson du robot (g1-jetson)
├── docs/           plan de l'Atelier, journal, séance robot, installation du Jetson, relevés
├── setup/          installation et environnement (env.sh, robot.sh)
├── third_party/    dépôts Unitree, versions dans VERSIONS.txt
├── ws/            espace de travail ROS 2 : pilote LiDAR, FAST-LIO2, g1_sim, g1_nav, g1_bridge (pont), g1_jumeau (faux G1),
│                  g1_pilotage (pilotage, vague 4), g1_equipe (chatbot et personnalités, vague 4)
├── choregraphies/ chorégraphies du G1 (vague 4) ; musique/ : vos musiques, jamais dans Git
├── modeles/       YOLO, Vosk, voix Piper, Whisper
├── opt/           SDK C++ Unitree et SDK Livox compilés
├── .venv-sim/     Python de simulation (MuJoCo, PyTorch processeur)
└── .venv-projet/  Python du projet (YOLO, voix, Open3D, FastAPI, PyTorch CUDA), voit ROS 2
```

Tout réinstaller, dans l'ordre :

```bash
bash ~/robot-g1/setup/installer_pc.sh            # partie système, demande le mot de passe
bash ~/robot-g1/setup/installer_utilisateur.sh   # tout le reste, sans mot de passe
```
