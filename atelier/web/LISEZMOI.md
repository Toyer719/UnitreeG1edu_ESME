# Interface web de l'Atelier G1

HTML, CSS et modules JavaScript servis tels quels par `atelier.serveur`, sans étape de compilation.
Leaflet 1.9.4 et three.js 0.160.0 sont copiés dans `vendor/` : l'Atelier marche sans Internet.

Lancer : `g1-atelier` (ouvre http://localhost:8000). Options : `--port 8080`, `--sans-navigateur`,
`--hote 0.0.0.0` (pour une tablette du même réseau).

## Fichiers

| Fichier | Rôle |
|---|---|
| `index.html` | page unique ; importmap de three.js ; Leaflet en script classique (`window.L`) |
| `css/atelier.css` | toute la mise en page ; boutons de 44 px pour la tablette |
| `css/scan.css` | l'onglet Scan : gros boutons « Scan » et « Fin », aperçu, progression, revue |
| `js/app.js` | onglets, choix du lieu et de l'étage, liaison en direct |
| `js/api.js` | appels à l'API (`/api/...`), erreurs en français (`ErreurApi`) |
| `js/contexte.js` | lieu et étage choisis, partagés par les écrans |
| `js/direct.js` | WebSocket `/ws/etat` (robot, guide, piétons, processus), reconnexion automatique |
| `js/plan.js` | plan 2D Leaflet en `CRS.Simple` (1 unité = 1 m ; lat = y, lng = x), gestes au pointeur |
| `js/vue3d.js` | vue 3D three.js (repère map gardé tel quel : z vers le haut) |
| `js/nuage3d.js` | nuage de points 3D de l'aperçu du scan (`apercu.json`), coloré selon la hauteur |
| `js/teleop.js` | flèches à l'écran et au clavier qui pilotent le robot simulé (`/api/simulation/teleop`, consigne renvoyée toutes les 0,2 s) |
| `js/geometrie.js`, `historique.js`, `formulaire.js`, `messages.js` | outils communs |
| `js/ecrans/*.js` | un module par onglet : lieux, monde, carte, salles, itineraires, zones, simulation, scan |

Chaque écran exporte `ouvrir(racine)`, qui renvoie `{modifie(), fermer()}`.

## Règles d'écriture

- JavaScript lisible par esprima (ES2017) : pas de `?.`, de `??`, de champs de classe, ni de `catch {}`.
  Le test `atelier/tests/test_serveur_web.py` vérifie la syntaxe et les imports de chaque module.
- Textes en français ; les boutons disent ce qu'ils font ; les erreurs disent quoi corriger.
- Aucune donnée des fichiers n'est insérée en HTML : `textContent` ou `value` seulement.
- Toute conversion mètres ↔ pixels de la carte se fait côté serveur (`atelier.lieu.conversions`) :
  `GET …/carte.yaml` donne les bornes en mètres de l'image, que Leaflet place telles quelles.

## Onglet Scan (vague 2)

Choix du mode (Robot, Simulation, case « Répétition sans robot »), gros bouton « Scan », aperçu en
direct (`/api/scan/apercu.png` rendu transparent là où rien n'est vu, trajectoire, nuage 3D), flèches
en simulation, bouton « Fin », progression du traitement, revue des éléments reconnus (une couleur par
catégorie, case « garder », confiance), adoption (« Utiliser cette carte pour l'étage », « Ouvrir dans
l'éditeur du monde ») et scans précédents. L'état est relu chaque seconde (`/api/scan/etat`), l'aperçu
toutes les 2 s. Routes : section 9.7 du plan, `atelier/serveur/routes/scan.py`.

## Onglet Simulation : répétition et vrai robot (vague 3)

Trois modes en haut de l'onglet (section 10.8 du plan), retenus par le navigateur :
- **Simulation** : comme avant (« Lancer la simulation ») ;
- **Répétition sans robot** (« Lancer la répétition ») : Gazebo avec le faux G1, le faux service de
  cartographie et la navigation du vrai robot (repérage, pont vers la marche) ;
- **Robot** (« Lancer sur le robot ») : la navigation tourne dans le conteneur du Jetson
  (`g1-jetson demarrer`) ; une confirmation rappelle le câble, `source ~/robot-g1/setup/robot.sh` et la
  télécommande en main.

En répétition et avec le robot, le panneau **Repérage** :
- la consigne « Posez le robot sur le point principal « Accueil » (étoile sur la carte), tourné dans le
  sens de la flèche » (vague 4) ; l'étoile et la flèche du point principal sont dessinées sur la carte
  (`GET /api/robot/etat`, champs `marque` et `principal`). Sans point principal sur cet étage, c'est la
  marque au sol de la vague 3 (croix : l'origine de la carte d'Unitree) ;
- le gros bouton **« Repérer le robot »** (`POST /api/robot/reperer`, qui envoie la pose du point
  principal) ; le lien « Le robot n'est pas sur le point principal » : un clic sur la carte là où il est,
  puis un glissé vers son avant, envoie sa pose ;
- l'état du repérage (`/ws/etat`, champ `reperage`) : Repéré (précision, âge), Non repéré, Repérage perdu,
  Échec avec son message ;
- la pastille du pont (`/ws/etat`, champ `pont`), et « Bloquer le robot » / « Débloquer »
  (`POST /api/robot/arret`).

« Y aller » reste grisé tant que le robot n'est pas repéré ou que Nav2 n'est pas prêt. Le robot affiché
est alors la pose du repérage (et non `/odom`, qui est l'odométrie locale). Tests :
`atelier/tests/test_robot_serveur*.py` (API) et `test_robot_navigateur.py` (Firefox sans fenêtre).

## Vague 4 : point principal, passants, guide, pilotage, équipe

| Où | Fichiers | Ce qu'on y fait |
|---|---|---|
| Onglet Salles | `js/ecrans/salles.js`, `css/principal.css` | le point principal (étoile et flèche) ; « Faire de cette salle le point principal » ; flèche tournée puis « Enregistrer les salles » |
| Onglet Monde | `js/ecrans/monde.js` | le départ du robot de l'étage du principal est affiché « = point principal » |
| Onglet Simulation, panneau **Passants** | `js/panneaux/passants.js`, `css/passants.css` | piétons en direct, distance bord à bord au plus proche, scènes, derniers bancs (`/api/passants/*`) |
| Onglet Simulation, panneau **Comportement du guide** | `js/panneaux/guide.js`, `css/guide.css` | « Accompagner un visiteur », état du guide et du visiteur, événements, faux visiteur (Suivre, Traîner, Partir) |
| Onglet **Pilotage** | `js/ecrans/pilotage.js`, `js/pilotage/*.js`, `css/pilotage.css` | barre du haut (main, ARRÊT, Échap), Commandes, Danses du robot, Mes chorégraphies (aperçu 3D) ; `/api/pilotage/*`, `/ws/pilotage` |
| Onglets **Personnalités**, **Dialogues**, **Caméra** | `js/ecrans/{personnalites,dialogues,camera}.js`, `js/equipe/*.js`, `css/equipe.css` | les fichiers de l'équipe ; « Rendre active » ; « Essayer » une phrase ; vues de la caméra |

Tests dans Firefox sans fenêtre : `atelier/tests/test_principal_navigateur.py`, `test_passants_navigateur.py`,
`test_guide_navigateur.py`, `test_pilotage_navigateur.py`, `test_equipe_navigateur.py`.
