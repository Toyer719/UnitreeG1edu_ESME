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
| `g1-pilotage` | Piloter le G1 comme Réel › Piloter de l'Atelier : postures, gestes, voix, LED, danses, chorégraphies (section « Pilotage et danses ») | oui (non contre le faux G1) |
| `g1-visiteurs` | Les visiteurs vus par la caméra de poitrine (YOLO) : cadres, distances, `/visiteurs/detectes` (section « L'équipe ») | non (oui pour la caméra du robot) |

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

L'Atelier s'ouvre sur un **accueil** (comme « Nouveau document » de SolidWorks) : deux grandes
cartes, **Simulation** (dessiner un lieu et essayer le guide sur l'ordinateur, sans robot) et
**Robot réel** (scanner le bâtiment, placer les salles et guider le vrai G1 ; la case **Répétition
sans robot** joue tout contre un faux G1 dans Gazebo). Choisissez un lieu (ou « Nouveau lieu »),
puis **Ouvrir**. En Robot réel, l'accueil vérifie aussi le câble, le robot et la télécommande.

L'espace de travail ne défile jamais (habillage d'Unitree Explore, thème sombre ou clair ◐) :

- la **barre d'outils** : ⌂ (retour à l'accueil), lieu et étage, mode, Annuler / Rétablir,
  **Enregistrer**, et le gros bouton **ARRÊT** : il arrête le guide, la téléopération et le
  pilotage en moins d'une seconde, et en Réel il bloque le robot jusqu'à **Débloquer**. La touche
  **Échap** envoie l'ARRÊT dès que le robot bouge ou que quelque chose tourne (simulation, navigation,
  pilotage) ; sinon elle ferme seulement le menu ou la fenêtre, ou annule la saisie ou l'outil en
  cours. Revenu à l'accueil pendant une navigation, l'ARRÊT y est aussi ;
- le **ruban**, avec de grosses icônes ; ce qui est rare est dans son menu **⚙ Avancé** :

| Mode | Onglets du ruban |
|---|---|
| Simulation | **Dessiner** (murs, passages, meubles, piétons, départ ; la carte se refait seule à « Enregistrer »), **Placer** (salle, accueil ★, nœud, relier, zones interdites et lentes), **Simuler** (Lancer, Arrêter, Y aller, Accompagner, Retour ; Avancé : faux visiteur, passants, réglages du guide, scan simulé), **Équipe** |
| Robot réel | **Scanner** (Scan, Fin, Utiliser cette carte), **Placer** (sur le nuage du scan, en 3D), **Naviguer** (Lancer, Repérer, Y aller, Bloquer, Débloquer, Arrêter), **Piloter** (prendre la main, postures, gestes, voix, lumière, joysticks ; Spectacle : danses, chorégraphies), **Équipe** (personnalités, dialogues, caméra) |

- l'**arbre du lieu** à gauche (étage, carte, monde, ★ accueil et salles, itinéraires, zones, scans,
  équipe ; ⚠ sur ce que « Vérifier le lieu » signale) ;
- la **vue** au centre : **3D** (le nuage de points du scan en Réel, coloré par la hauteur, plafond
  caché ; le monde en volumes et la carte 2D au sol en Simulation ; l'accueil en étoile ambre, les
  salles en épingles numérotées, les itinéraires, les zones, le robot et les piétons en direct),
  **Plan 2D** (pour dessiner le monde, les itinéraires et les zones) ou **Caméra** (en Réel) ;
  gestes en 3D : glisser = tourner, clic droit ou Maj = déplacer, molette = zoom vers le pointeur,
  F = tout voir ; boutons Dessus, Iso, Face, Recadrer ;
- le **panneau** à droite : le formulaire de la commande en cours, ✓ Enregistrer et ✗ Annuler.

**Placer un point en 3D** (Placer › Accueil ou Salle) : un clic sur le sol pose le point, un glissé
depuis le point règle son orientation (par pas de 15°, Maj : libre), x, y et l'angle se corrigent à
droite, puis ✓ Enregistrer. Les fichiers et les coordonnées sont les mêmes qu'en Plan 2D.
Ctrl+C dans le terminal arrête le serveur, et avec lui la simulation et la navigation. Les anciennes
adresses (`#salles`, `#simulation`, `#pilotage`…) mènent au bon endroit. Détails :
`atelier/web/LISEZMOI.md`.

Depuis la vague 4 (section 11 du plan) : le **point principal** du lieu (l'accueil : départ de la
simulation, pose du repérage, retour après chaque visite), des **passants** que le robot contourne
ou attend, l'**accompagnement** du visiteur et le retour automatique, **Piloter** (postures,
joystick, gestes, voix, LED, danses du robot, chorégraphies) et l'**Équipe** (personnalités,
dialogues, caméra). Depuis la vague 5 (section 12) : cette interface, la carte 3D, le scan corrigé,
la vitesse minimale du pont et la caméra de poitrine. Chacun a sa section ci-dessous.

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
| `g1-scan demarrer\|arreter\|etat\|traiter\|adopter --lieu L …` | Le scan intégré, comme Scan, Fin et « Utiliser cette carte » de Réel › Scanner (section suivante) |
| `g1-scan traiter --lieu L --session S --refaire` | Refait le traitement d'un scan fini, même adopté, avec la chaîne d'aujourd'hui ; les résultats d'avant sont gardés dans `ancien_<date>/` (à réadopter) |
| `g1-scan carte-unitree --lieu L [--etage E] [--delai 60]` | Enregistre la carte d'Unitree (`/unitree/slam_relocation/global_map`, publiée pendant « Repérer le robot ») dans `cartes/<etage>_unitree.pcd` |
| `g1-visiteurs [--lieu L] [--source robot\|N\|/dev/…\|video.mp4] [--image] [--fenetre]` | Les visiteurs vus par la caméra de poitrine (YOLO pose et suivi), publiés sur `/visiteurs/detectes` (section « L'équipe ») |
| `g1-jetson construire\|envoyer\|demarrer\|arreter\|etat\|journal\|verifier …` | Le conteneur de la navigation sur le Jetson (section « Le vrai robot » ; `--local` : sur le PC) |

Chaque commande a un alias `gl-…` et accepte `--help`.

### Scanner un lieu

Le scan fabrique la **carte 2D** de navigation d'un étage et son **nuage de points 3D** (celui de la
vue 3D), à partir de ce que voit le LiDAR du robot. Tout se fait dans **Réel › Scanner** : **Scan**
pour commencer, **Fin** pour arrêter, puis **Utiliser cette carte** ; le reste est automatique.
Depuis la vague 5, il n'y a plus de reconnaissance des tables et des chaises : la carte et le nuage
sont gardés tels quels (le nuage montre déjà les meubles), et le monde de simulation d'un étage
scanné est la carte extrudée sur 1,5 m, en un seul maillage.

**Avec le vrai robot** : le PC suit le robot au câble. Les données du scan n'arrivent au PC que par
le câble Ethernet, pas par le Wi-Fi. Il faut deux personnes : l'une pilote le robot à la
télécommande, l'autre marche derrière avec le PC portable, relié au robot par un câble de 2 à 5 m.

1. Robot allumé et debout en mode marche, **sur le point de départ** (il deviendra l'origine de la
   carte : le plus simple est d'y mettre le point principal) ; dans l'appli Unitree, les services
   `unitree_slam` et `lidar_driver` sont activés.
2. Branchez le câble, puis dans un terminal : `source ~/robot-g1/setup/robot.sh` (doit dire « le
   robot répond »), puis `g1-atelier`.
3. Accueil : **Robot réel**, le lieu, **Ouvrir**. **Scanner › Scan** : le PC demande au robot de
   commencer sa cartographie (commande 1801) et enregistre ce qu'il publie
   (`/unitree/slam_mapping/points` et `/unitree/slam_mapping/odom`). L'écran passe en plein écran
   sombre, comme « 3D LiDAR Mapping » d'Unitree Explore : le nuage se remplit en direct, coloré par la
   hauteur, avec le trajet du robot, la durée, la distance et le nombre de points. Sans câble,
   l'Atelier répond « Robot non détecté » et ne lance rien.
4. Promenez le robot **lentement** dans tout l'étage (moins de 0,5 m/s, virages lents, personne entre
   le robot et les murs), câble lâche. Il se pilote à la télécommande, qui reste l'arrêt d'urgence.
5. Revenez au point de départ, puis **Fin** : le robot enregistre sa propre carte (commande 1802,
   fichier `<etage>_<session>.pcd` sur le robot) et le PC fabrique en quelques secondes la carte 2D
   et le nuage : tous les nuages sont gardés (même avec des horodatages nuls, comme sur le G1), les
   passants sont retirés depuis la vraie position du capteur, et le sol est trouvé comme un plan
   (même un peu penché) : plus de « damier » sur la carte.
6. Regardez la carte et le nuage, puis **Utiliser cette carte** : elle devient la carte de l'étage,
   le nuage devient celui de la vue 3D (`cartes/<etage>.nuage.bin`) et le monde de simulation devient
   la carte extrudée. Les salles, les itinéraires et les zones ne bougent pas (mêmes coordonnées) ;
   si l'étage avait un monde dessiné (autre repère), replacez-les.

**En simulation** (sans robot, pour essayer ou pour préparer) : **Simulation › Simuler › ⚙ Avancé ›
Scan simulé** : le robot simulé de Gazebo, à la taille du G1, scanne le monde dessiné de l'étage.
Cochez **Exploration automatique** pour qu'il fasse seul le tour des couloirs des itinéraires ;
sinon, conduisez-le avec les flèches de l'écran ou du clavier (il s'arrête dès qu'on lâche). Pour
s'entraîner au déroulé du vrai robot sans robot : **Robot réel** avec **Répétition sans robot**, puis
Scanner (faux service de cartographie et robot simulé).

Les mêmes étapes en ligne de commande :

```bash
g1-scan demarrer --lieu demo --etage rdc --mode simu --explorer   # « Scan » : rend la main tout de suite
g1-scan etat --lieu demo                                          # où en est le scan
g1-scan arreter --lieu demo --attendre                            # « Fin », puis attend la carte et le nuage
g1-scan adopter --lieu demo --session 2026-10-25_17h42            # « Utiliser cette carte »
g1-scan traiter --lieu seance --session 2026-10-27_14h22 --refaire   # refait le traitement d'un vieux scan
g1-scan carte-unitree --lieu seance --etage rdc                   # la carte d'Unitree, pendant « Repérer le robot »
```

Vrai robot : `--mode robot` (câble branché et `source ~/robot-g1/setup/robot.sh` fait) ;
répétition sans robot : `--mode robot --repetition`. Chaque scan est rangé dans
`lieux/<id>/scans/<date>_<heure>/` (enregistrement, aperçu, carte, nuage 3D `nuage.pcd`, nuage
d'affichage `nuage_affichage.bin`, `rapport.json` avec les nuages gardés, la base de temps, le plan du
sol et les passants retirés). `--refaire` range les résultats d'avant dans `ancien_<date>/`, sans
rien effacer ; la session est alors à réadopter. L'enregistrement pèse environ 100 Mo par minute de
scan ; il n'est pas sauvegardé par Git : gardez-en une copie (le scan du 27/10 est aussi dans
`~/robot-g1-donnees/2026-10-27_seance1/`).

**Le scan du 27/10** (lieu `seance`, étage `rdc`) a été retraité et adopté le 31/10 avec la nouvelle
chaîne : 2 327 nuages gardés sur 2 327 (953 avant), 299 558 points (158 791 avant), sol penché de
0,58° trouvé, plus de damier ; la carte nettoyée à la main n'est plus nécessaire. La copie d'avant est
dans `lieux/seance/sauvegardes/`.

### Le point principal

Chaque lieu a **un seul point principal** : l'accueil, où le robot attend les visiteurs. C'est une
salle de `salles.yaml` qui porte l'étiquette `principal`, avec une flèche (le sens du robot). Il sert
à trois choses :

- la **simulation** part de lui (le départ du robot du monde de son étage le suit) ;
- le **repérage** du vrai robot part de lui : on pose le robot sur le point principal, dans le sens
  de la flèche, puis « Repérer le robot » (plus besoin de la marque au départ du scan) ;
- le **retour** : après chaque visite, le guide revient seul au point principal et se tourne dans le
  sens de la flèche.

Dans l'Atelier, **Placer › Accueil** : le point principal est l'étoile ambre avec sa flèche, en 3D
comme en Plan 2D. Un clic sur le sol le pose, un glissé depuis l'étoile le tourne (par pas de 15°),
puis ✓ Enregistrer. Pour donner ce rôle à une autre salle : choisissez-la, puis **« Faire de cette
salle l'accueil »**. On ne peut pas supprimer le point principal sans en avoir choisi un autre. Un lieu d'avant la vague 4 sans
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
d'un piéton, Simulation › Dessiner) : `ecart` (défaut : il ralentit et s'écarte, ou attend 8 s au plus s'il
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
la plus courte, les attentes de passage et la longueur parcourue. **Simuler › ⚙ Avancé › Passants**
montre les piétons en direct, la distance au plus proche, les scènes et les derniers bancs.

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

Dans **Simuler** : les cases **Accompagner** et **Retour**, puis **Y aller** vers une salle ; en Réel
(**Naviguer**), le bouton « Accompagner un visiteur » du panneau **Visite guidée**. Le panneau montre
l'état du guide et du visiteur et les derniers événements.
**⚙ Avancé › Faux visiteur** (Suivre, Traîner, Partir) joue un visiteur dans Gazebo, et **Réglages du
guide** règle les délais ci-dessus.

### Pilotage et danses

**Réel › Piloter** pilote le robot comme l'appli Unitree Explore (en Réel seulement : vrai robot ou
répétition). La vue du robot est au centre, avec deux **joysticks** en surimpression (tactiles sur une
tablette) ; le ruban donne **Prendre la main** / **Rendre la main**, **Postures**, **Gestes**,
**Voix**, **Lumière**, et le groupe **Spectacle** ; le bouton **ARRÊT** de la barre d'outils (touche
Échap dès que le robot bouge) reste toujours là ; en répétition, si le pilotage n'est pas démarré,
la première commande du ruban s'appelle **Démarrer** :

- **Postures** : 500 démarrer, 706 accroupi ↔ debout, 702 se relever, 3 s'asseoir ; **⚙ Avancé ›
  Portique** : 1 amortir et 0 couple nul, seulement avec la case « robot au portique » et une double
  confirmation ;
- **joysticks** : le robot s'arrête seul 0,5 s après le dernier ordre, ou dès que la page ou le Wi-Fi
  se coupe ; un manche à peine incliné fait marcher à 0,2 m/s (le robot ne marche pas plus lentement) ;
  refusés quand le robot est assis ou pas démarré ; **après un ARRÊT, un manche resté tenu ne relance
  pas le robot** : il faut le lâcher, puis le reprendre ;
- **Spectacle › Danses** : la liste lue dans le robot ; 401, 402 et 403 sont toujours interdites ;
  chaque danse demande la case « zone libre de 2 à 3 m autour du robot » ; permises en mode marche
  (500, 501 ou 801 : le vrai G1 marche en 501) ;
- **Spectacle › Chorégraphies** : éditeur à ligne de temps (poses des bras, pas de marche, gestes, LED,
  paroles, musique) et **aperçu 3D** du G1 avant de jouer. Les bras passent par rt/arm_sdk avec des
  rampes, des angles et des vitesses bornés ; les jambes restent au contrôleur d'Unitree. Un pas plus
  lent que 0,2 m/s est joué deux fois plus vite pendant deux fois moins longtemps (même trajet), avec
  un avertissement.

**La Vue du robot** (au centre de Piloter) montre ce que fait le robot, sans rien commander :

- une **carte** du lieu en cours avec la position et le cap du robot et les passants (en répétition
  et avec le robot, après **Naviguer › Repérer**) ; « Suivre le robot » la recentre ;
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

Dans l'Atelier, en répétition : bouton **« Démarrer le pilotage »** de Piloter (le nœud tourne sur le
PC, contre le faux G1). Avec le robot : le nœud tourne dans le conteneur du
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

Trois fichiers facultatifs du lieu, chacun avec son écran (ruban **Équipe**) et un bouton « Partir de
l'exemple » :

- `personnalites.yaml` (**Équipe › Personnalités**) : les modes du robot (salutation, voix et son
  nom, couleur de la LED, geste de salut, vitesse maximale, phrases du guide) ; la personnalité
  active part sur `/personnalite/active` : le guide applique sa vitesse maximale, le nœud pilotage
  sa LED ;
- `dialogues.yaml` (**Équipe › Dialogues**) : le chatbot à règles (guider, dire, personnalité, stop,
  geste) ; « Essayer » montre la réponse d'une phrase sans rien faire bouger ;
- `camera.yaml` (**Équipe › Caméra** ; ⚙ Avancé › Réglages de la caméra) : la See3CAM_11CUG, sa
  position sur le robot (tangage positif : vers le bas), l'exposition, les images publiées, la
  détection des visiteurs et l'étalonnage des distances.

**La caméra de poitrine** (vague 5) : la See3CAM_11CUG, branchée sur un port USB 3 du Jetson, est
passée au conteneur par `g1-jetson demarrer` quand elle est là (sinon il démarre sans) ; le nœud
`camera_usb` de `g1_equipe` règle l'exposition automatique, lit l'image en 1280 × 720 et publie un
JPEG de 640 pixels à 10 images par seconde sur `/camera_poitrine/image/compressed`. Sur le PC,
**`g1-visiteurs`** (YOLO pose et suivi, sur la carte graphique) trouve les personnes, estime leur
distance et publie `/visiteurs/detectes` ; l'Atelier montre l'image en direct avec un cadre autour de
chaque visiteur (vue **Caméra**, et en incrustation dans Piloter et Naviguer).

```bash
ros2 run g1_equipe camera_usb                                   # la caméra branchée sur ce PC, sans conteneur
g1-visiteurs --source robot --image                             # les visiteurs de l'image du robot, cadres dessinés
g1-visiteurs --source /dev/v4l/by-id/<la See3CAM>-video-index0 --fenetre --sans-ros   # essai local, fenêtre (q : quitter)
```

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
├── cartes/<etage>.pcd                 nuage 3D du scan adopté
├── cartes/<etage>.nuage.bin + .json   nuage de la vue 3D (x, y du repère de la carte, z au-dessus du sol)
├── cartes/<etage>_unitree.pcd, _unitree.nuage.bin + .json   carte d'Unitree (g1-scan carte-unitree)
├── mondes/<etage>_carte.stl           carte d'un étage scanné, extrudée en un maillage (monde de simulation)
├── salles.yaml                        salles : nom, alias, position devant la porte, phrase d'arrivée ;
│                                      la salle qui porte l'étiquette « principal » est le point principal
├── itineraires.yaml                   nœuds et couloirs du guide
├── zones.yaml                         zones interdites et lentes
├── personnalites.yaml, dialogues.yaml, camera.yaml   pour l'équipe (vague 4, facultatifs)
├── sauvegardes/<date>_<raison>/       copies faites avant une migration (g1-lieu migrer, vague 4)
└── scans/<date>_<heure>/              un dossier par scan (session.json, enregistrement, carte, nuages, rapport)
```

Les formats exacts sont dans `atelier/lieu/schemas/` et dans la section 4 du plan.

### Tester

```bash
cd ~/robot-g1 && .venv-projet/bin/python -m pytest atelier/tests -q --ignore=atelier/tests/test_robot_reperage_ros.py   # bibliothèques, scan, serveur, interface : 10 min environ
cd ~/robot-g1 && ROS_LOCALHOST_ONLY=0 .venv-projet/bin/python -m pytest atelier/tests/test_robot_reperage_ros.py -q   # ce fichier à part (ses programmes l'imposent)
cd ~/robot-g1 && .venv-projet/bin/python -m pytest docker/tests -q    # conteneur du Jetson : 1 min
cd ~/robot-g1/ws && colcon test --executor sequential --packages-select g1_sim g1_nav g1_bridge g1_jumeau g1_pilotage g1_equipe && colcon test-result --all   # paquets ROS 2
~/robot-g1/tests_e2e/tout.sh            # les 36 critères de recette, sans fenêtre : « N / 36 » (3 h environ)
~/robot-g1/tests_e2e/tout.sh 1 2 3 4    # seulement certains (11 à 15 : le scan ; 16 à 20 : le vrai robot en répétition ;
                                        # 21 à 30 : point principal, passants, guide, pilotage, équipe ;
                                        # 31 à 36 : coque, carte 3D, scan corrigé, pont, caméra, ARRÊT)
```

Tous les tests tournent sans robot et sans écran, sur des copies de `lieux/demo` dans des
dossiers temporaires. Journaux : `~/robot-g1/journaux/`. La carte 3D a besoin de WebGL : Firefox
sans fenêtre n'en a qu'avec l'affichage de la session graphique (`DISPLAY=:1`, aucune fenêtre ne
s'ouvre) ; lancez donc les tests depuis un terminal de la session (sinon, le critère 32 répond « en
attente » et quelques tests de la carte 3D sont sautés).

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
depuis la vague 4, le nœud pilotage de Réel › Piloter, et depuis la vague 5 la caméra de poitrine,
dans le même conteneur) :

- **le conteneur `g1-jetson`**, sur le Jetson du robot : ROS 2 Humble, Nav2, le guide, le relais
  de position et le pont ;
- **le pont** (`g1_bridge`) : il traduit les vitesses de Nav2 (`/cmd_vel`) en ordres de marche du
  robot (`/api/sport/request`, ordre 7105), avec les sécurités ci-dessous ;
- **le repérage** : au démarrage, le robot posé sur le point principal du lieu (dans le sens de sa
  flèche), « Repérer le robot » envoie la commande 1804 au service de cartographie d'Unitree, avec
  la pose du point principal ; le relais `odom_vers_tf` transforme ensuite la position fournie par
  Unitree en repères pour Nav2.

**État** : tout est prêt et répété sans robot, contre un faux G1 dans Gazebo (critères 16 à 20, 34
et 36 de `tests_e2e/tout.sh`). La séance n° 1 avec le robot (27/10) a validé le scan et l'ordre de
marche 7105 du pont ; elle a montré que le G1 ne fait **aucun pas à 0,1 m/s** (il marche à 0,2) et
que le mode lu par 7001 vaut 0, 3, 501 ou 802 : le pont en tient compte depuis la vague 5 (voir
« Les sécurités »). Le conteneur, le repérage et le premier trajet restent à essayer sur le vrai
robot : suivez **`docs/tutoriel-seance-2.md`** (brouillon de la séance n° 2, avec sa feuille
`docs/releves/seance-2.md`) ; le déroulé de référence est `docs/seance-robot.md`.

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

Le robot navigue sur la carte d'un **scan fait avec lui** (Réel › Scanner, section « Scanner un
lieu »), adoptée pour l'étage. Placez ensuite les salles et les itinéraires sur la nouvelle carte
(Réel › Placer, sur le nuage en 3D), et le **point principal** (Placer › Accueil, section « Le point
principal ») : c'est
là qu'on pose le robot avant de le repérer. Marquez-le au sol d'une croix et d'une flèche (le sens
du robot). Le plus simple, au début : le point principal au point de départ du scan.

#### 3. Se repérer et lancer la navigation

```bash
source ~/robot-g1/setup/robot.sh      # câble branché : « le robot répond »
g1-atelier                            # ou G1_VITESSE_MAX=0.2 g1-atelier pour les premiers essais
```

1. Accueil : **Robot réel** (sans « Répétition »), le lieu, les vérifications au vert, **Ouvrir** ;
   puis **Naviguer › Lancer** : l'Atelier lance le conteneur sur le Jetson (`g1-jetson demarrer`, le
   lieu y est copié).
2. Posez le robot **sur le point principal, dans le sens de la flèche** (l'étoile sur la carte),
   debout en mode marche.
3. **Naviguer › Repérer** : « Repéré », avec la précision, en quelques secondes. Si le robot n'est
   pas sur le point principal : **⚙ Avancé › Situer le robot**, cliquez sa position sur la carte,
   glissez vers son orientation, puis repérez.
4. **Y aller** vers une salle. « Y aller » reste grisé tant que le robot n'est pas repéré.
5. Pour finir : **Naviguer › Arrêter** (arrêt propre du conteneur).

Sans l'Atelier : `g1-jetson demarrer --lieu L --etage E [--vitesse-max 0.2]`, `g1-jetson etat`,
`g1-jetson journal -f`, `g1-jetson arreter` ; `g1-guide aller ID` et `g1-guide stop`.

#### 4. Les sécurités

- **La télécommande reste l'arrêt d'urgence**, toujours en main pendant que le robot navigue.
- **Vitesses plafonnées** par le pont : 0,4 m/s en avant, 0,25 m/s de côté, 0,6 rad/s en rotation.
  Une valeur absurde (NaN, infini) donne un arrêt ; le pont refuse de démarrer avec des plafonds
  plus hauts. Premiers essais : `G1_VITESSE_MAX=0.2` (ou `--vitesse-max 0.2`) baisse les trois
  plafonds dans la même proportion, et aussi les vitesses de Nav2 ; moins de 0,2 m/s est refusé
  (« le robot ne marche pas sous 0,2 m/s »).
- **Vitesse minimale** (vague 5) : le G1 ne fait aucun pas sous 0,2 m/s ; le pont monte donc une
  petite consigne à 0,2 m/s dans la même direction (0,3 rad/s pour une rotation sur place), et une
  consigne minuscule (moins de 0,05 m/s et 0,1 rad/s) donne un arrêt. Nav2 ne recule jamais avec le
  vrai robot. Seuils à mesurer à la séance n° 2 (`python3 -m g1_bridge.mesure`, voir
  `ws/src/g1_bridge/LISEZMOI.md`).
- **Le mode du robot** (vague 5) : le pont le lit une fois par seconde (7001). Assis, pas démarré ou
  en mode course, il n'envoie plus d'ordre de marche (`pas_en_marche`, avec un message qui dit quoi
  faire à la télécommande) ; revenu en marche (501), il attend une nouvelle consigne.
- **Chaque ordre ne vaut que 0,5 s** : si le pont, le conteneur ou le Jetson s'arrête, le robot
  s'arrête seul. Le pont envoie aussi un arrêt 0,3 s après la dernière consigne de Nav2, et un
  arrêt quand il quitte.
- **Pas de mouvement sans repérage** : tant que le robot n'est pas repéré, ou si le repérage est
  perdu (plus de position d'Unitree depuis 3 s), le pont refuse de le faire bouger.
- **ARRÊT** (barre d'outils de l'Atelier, et de l'accueil quand quelque chose tourne ; touche Échap
  dès que le robot bouge ou qu'une navigation tourne) : arrête le guide, la téléopération et le
  pilotage en moins d'une seconde, et bloque le robot jusqu'à **Débloquer** ; sans réponse du serveur
  en 1,5 s, la barre d'état dit de prendre la télécommande ; `g1-guide stop` :
  arrêt immédiat, puis 1 s sans mouvement. **Naviguer › Bloquer** : il reste immobile, quoi qu'on lui
  demande, jusqu'à « Débloquer ».
- Si le robot ne répond plus (`robot_muet`), refuse les ordres (`refus`) ou n'est pas en mode marche
  (`pas_en_marche`), le pont le dit en français (pastille du robot dans la barre d'outils, panneau de
  Naviguer).
- Le conteneur ne redémarre jamais seul : on ne relance pas une navigation sans un humain.

#### 5. Répéter sans robot

Accueil : **Robot réel** avec **Répétition sans robot** : tout le déroulé ci-dessus (repérage, pont,
« Y aller », ARRÊT, pilotage) est joué avec un faux G1 dans Gazebo, qui répond comme le vrai (il
démarre en mode 501 et ne fait aucun pas sous 0,15 m/s). Les mêmes étapes en ligne de commande :

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
│                  g1_pilotage (pilotage, vague 4), g1_equipe (chatbot, personnalités, caméra de poitrine)
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
