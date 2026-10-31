# Interface web de l'Atelier G1

HTML, CSS et modules JavaScript servis tels quels par `atelier.serveur`, sans étape de compilation.
Leaflet 1.9.4 et three.js 0.160.0 sont copiés dans `vendor/` : l'Atelier marche sans Internet.

Lancer : `g1-atelier` (ouvre http://localhost:8000). Options : `--port 8080`, `--sans-navigateur`,
`--hote 0.0.0.0` (pour une tablette du même réseau). Avec le vrai robot : `source ~/robot-g1/setup/robot.sh`
d'abord, dans le même terminal.

## L'interface en bref (vague 5, section 12.2 du plan)

Structure de SolidWorks, habillage d'Unitree Explore (thème sombre par défaut, accent pervenche).

1. **L'accueil** : deux grandes cartes, **Simulation** (« Dessiner un lieu et essayer le guide sur
   l'ordinateur, sans robot ») et **Robot réel** (« Scanner le bâtiment, placer les salles et guider le vrai
   G1 »). Un clic choisit, un double-clic ou Entrée ouvre. Dessous : la liste des lieux (le dernier ouvert
   présélectionné), « Nouveau lieu », le bouton **Ouvrir**. En Robot réel : la case **« Répétition sans robot
   (faux G1) »** et les vérifications (Atelier lancé avec robot.sh, câble branché, PC1 et Jetson répondent,
   télécommande en main), relues toutes les 4 s par `GET /api/robot/liaison`. Lien « Piloter le robot sans
   lieu ». Une adresse avec un hash (`#salles`…) ou `?recharger` saute l'accueil ; ⌂ y revient.
2. **L'espace de travail**, qui ne défile jamais :

```
┌ barre d'outils : ⌂ Atelier G1 │ Lieu ▾ › Étage ▾ │ SIMULATION / RÉEL / RÉPÉTITION │ ↶ ↷ Enregistrer │ états │ ◐ ⚙ │ ARRÊT ┐
├ ruban (92 px, repliable) : onglets du mode ; grosses icônes et libellés courts ; menu ⚙ Avancé de l'onglet ──────────┤
├ arbre du lieu (260 px) ┬ vue centrale : 3D │ Plan 2D │ Caméra + Dessus Iso Face Recadrer · Calques ┬ panneau (320 px) ┤
└ barre d'état : consigne de l'outil · dernier message (clic : le journal) · x, y sous le pointeur ────────────────────┘
```

| Mode | Onglets du ruban |
|---|---|
| Simulation | **Dessiner** (choisir, mur, passage, objet, piéton, départ), **Placer** (salle, accueil, nœud, relier, zones), **Simuler** (lancer, arrêter, Y aller, accompagner, retour ; Avancé : faux visiteur, passants, réglages du guide, scan simulé), **Équipe** (personnalités, dialogues, caméra ; Avancé : réglages de la caméra) |
| Réel (et répétition) | **Scanner** (Scan, Fin, Utiliser cette carte), **Placer**, **Naviguer** (lancer, repérer, Y aller, bloquer, débloquer, arrêter), **Piloter** (prendre la main, postures, gestes, voix, lumière, joysticks ; groupe Spectacle : danses, chorégraphies), **Équipe** |

- **Arbre** : Lieu ▸ Étage ▸ Carte, Monde, Points (★ Accueil d'abord), Itinéraires, Zones, Scans, Équipe ;
  clic : l'élément choisi dans la vue et ses propriétés à droite ; double-clic : la vue 3D se centre dessus ;
  ⚠ sur ce que signale « Vérifier le lieu ».
- **Vue centrale** : 3D (la carte 3D de `js/carte3d/`, partagée : nuage du scan en Réel, monde en Simulation,
  points, itinéraires, zones, robot, piétons), Plan 2D (Leaflet : la carte de l'écran ouvert), Caméra (Réel).
  Sans WebGL, la coque passe au Plan 2D. Gestes 3D : glisser = tourner, clic droit ou Maj = déplacer,
  molette = zoom vers le pointeur, F = tout voir.
- **Panneau de tâches** : le formulaire de la commande ou les propriétés de l'élément choisi, avec
  ✓ Enregistrer et ✗ Annuler en haut ; il défile seul.
- **ARRÊT** (barre d'outils, touche **Échap**, partout) : `POST /api/arret` arrête en moins de 1 s le guide,
  la téléopération et le pilotage, et en Réel ou en répétition bloque le robot (verrou du pont) ; le
  bouton devient alors « Débloquer » (confirmation dans la page). Les écrans lâchent leurs manettes à
  l'appui (événement `atelier-arret` de la page). L'ARRÊT n'arrête pas un scan (« Fin » le fait).
- **Messages** : dans la barre d'état (une ligne) et son journal (le message complet, ses détails), plus de
  notifications volantes. « Ce qui tourne » (commandes lancées par l'Atelier) : menu ⚙, ou le bouton de la
  barre d'état quand quelque chose tourne.
- **Thème** : sombre par défaut ; ◐ passe au clair (clé `atelier.theme`) ; la vue 3D reste sombre.
- **Écrans étroits** (moins de 1100 px, tablette) : l'arbre et le panneau deviennent des tiroirs (boutons
  de la barre d'outils) ; cibles tactiles de 44 px.

## Fichiers

| Fichier | Rôle |
|---|---|
| `index.html` | page unique ; thème posé avant les feuilles ; importmap de three.js ; Leaflet en script classique (`window.L`) ; `window.erreursAtelier` |
| `css/theme.css` | les jetons : couleurs des deux thèmes, couleurs de la vue 3D et des repères, tailles de la coque (rien d'autre) |
| `css/atelier.css` | la mise en page de la coque (accueil, barres, ruban, arbre, vue, panneau, tiroirs) et les styles communs des écrans |
| `css/{principal,passants,guide,pilotage,equipe}.css` | les styles des écrans et panneaux de la vague 4 (jetons du thème seulement) |
| `css/{scan,carte3d,camera}.css` | écran Scan, carte 3D, vue Caméra (agents Scan, Carte 3D, Caméra) |
| `js/app.js` | point d'entrée : `demarrerCoque()` |
| `js/coque/coque.js` | la coque : accueil ou espace de travail, table des écrans, commandes du ruban, carte 3D partagée, clavier, mémoire du navigateur (`MODES`, `CLES_MEMOIRE`, `demarrerCoque`, `ouvrirEspace`, `retourAccueil`, `modeCourant`, `ouvrirCommande`) |
| `js/coque/accueil.js` | l'écran d'accueil (`afficherAccueil`) et les vérifications du Réel |
| `js/coque/ruban.js` | `ONGLETS_RUBAN`, le registre `COMMANDES` (id stable, modes, onglet, groupe, libellé, icône, aide, écran, commande, avance, case, menu), `construireRuban` |
| `js/coque/arbre.js`, `vue.js`, `panneau.js`, `barre_etat.js` | arbre du lieu, vue centrale et sa barre flottante, panneau de tâches, barre d'état |
| `js/coque/arret.js` | le bouton ARRÊT / Débloquer (`monterArret`) |
| `js/coque/confirmation.js` | `demanderConfirmation` et `demanderSaisie` : fenêtres dans la page (plus de `confirm` ni de `prompt`) |
| `js/coque/anciens_hash.js` | les anciennes adresses (`#salles`, `#simulation`, `#scan`, `#pilotage`…) |
| `js/coque/ecran.js`, `icones.js` | outils des écrans (`preparerEcran`, `section`) ; icônes SVG en ligne et illustrations de l'accueil |
| `js/ecrans/*.js` | un module par écran : lieux, monde, carte, salles, itineraires, zones, simulation, scan, pilotage, personnalites, dialogues, camera |
| `js/carte3d/carte3d.js` | la carte 3D partagée (`creerCarte3D`, section 12.3 du plan) : nuage coloré par la hauteur (vert → jaune → rose de 0 à 2,2 m, plafond caché), monde en volumes et maillage STL, carte 2D au sol, repères, robot et piétons en direct, vues Dessus / Iso / Face / Recadrer, gestes (souris, molette vers le pointeur, tactile, clavier), outils de placement ; rendu à la demande |
| `js/carte3d/geometrie3d.js`, `reperes.js`, `monde3d.js`, `edition.js`, `direct3d.js` | fonctions pures (rayon contre le sol, accroche à 5 cm et 15°, couleurs, cadrage, étiquettes sans chevauchement), repères (étoile de l'accueil, épingles numérotées, couloirs, zones), monde en volumes, gestes de placement, robot et piétons de `/ws/etat` |
| `js/carte3d/essai.js`, `essais/carte3d.html` | page d'essai de la carte seule (`?lieu=demo&mode=simu`), jamais liée par l'interface |
| `js/camera/flux.js` | la vue Caméra (`creerVueCamera`, section 12.7) : le flux MJPEG de `/api/camera/flux` dans `<img data-role=camera-flux>`, les cadres des visiteurs dans `<canvas data-role=camera-cadres>` ; le flux s'arrête quand la vue est cachée ; `data-etat` (`arrete`, `attente`, `sans-image`, `ok`) replie l'incrustation |
| `js/camera/essai.js`, `essais/camera.html` | page d'essai de la vue Caméra |
| `js/ecrans/scan.js`, `js/nuage3d.js`, `css/scan.css` | l'écran de scan : plein écran sombre pendant le scan (nuage en direct, trajet, compteurs, gros boutons Scan et Fin), progression, « Utiliser cette carte » |
| `js/panneaux/`, `js/pilotage/`, `js/equipe/` | panneaux de la vague 4 (passants, guide), vue du robot et joysticks du pilotage, éditeurs de l'équipe |
| `js/api.js`, `contexte.js`, `direct.js` | appels à l'API (`ErreurApi`), lieu et étage choisis, WebSocket `/ws/etat` (reconnexion automatique) |
| `js/plan.js`, `vue3d.js`, `nuage3d.js`, `teleop.js` | plan 2D Leaflet (`CRS.Simple`, 1 unité = 1 m, lat = y, lng = x), vue 3D du monde, nuage du scan, flèches du robot simulé |
| `js/geometrie.js`, `historique.js`, `formulaire.js`, `messages.js` | outils communs (`messages.js` envoie les messages à la barre d'état quand la coque est là) |

### Le contrat des écrans

`ouvrir(racine, options)` → `{modifie(), fermer(), commande?(nom, valeur), selectionner?(genre, id),
vue?(nom), enregistrer?(), defaire?(), refaire?(), peutDefaire?(), peutRefaire?()}` :
- `racine` : la vue Plan 2D de la vue centrale, où l'écran met sa carte (ou sa page, qui défile seule) ;
  la coque y pose `class="ecran ecran-<id>"` et `data-ecran="<id>"` ;
- `options.panneau` : le corps du panneau de tâches, vidé, pour le formulaire ; `ouvrirPanneau` règle
  le titre et ✓ / ✗ ;
- `options.mode` (`simu`, `reel`, `repetition`), `options.commande` (la commande du ruban : `salle`,
  `mur`…), `options.vue` et `options.carte3d` (la carte 3D partagée, ou null sans WebGL) ;
- `options.coque` : `confirmer`, `saisir`, `message`, `pleinEcran`, `ouvrirCommande`, `choisirVue`,
  `surVue`, `barreEtat`, `activer`, `griser`, `libelle`, `menu`, `coche`, `lieuModifie`, `incruster`…
Un écran d'avant, `ouvrir(racine)` sans options, marche encore : il dessine tout dans la racine.

## Règles d'écriture

- JavaScript lisible par esprima (ES2017) : pas de `?.`, de `??`, de champs de classe, ni de `catch {}`.
  `atelier/tests/test_serveur_web.py` vérifie la syntaxe et les imports de chaque module.
- Textes en français simples : une phrase d'aide par commande (infobulle et barre d'état) ; aucun nom de
  sujet ROS ni de fichier dans les titres (seulement en infobulle, en Avancé ou dans cette documentation).
- Aucune donnée des fichiers insérée en HTML : `textContent` ou `value` seulement.
- Aucune boîte native : `options.coque.confirmer` (ou `demanderConfirmation`), jamais `window.confirm`.
- **Défilement** : `html, body {height: 100%; overflow: hidden}` ; la page ne défile jamais ; l'arbre, le
  panneau, les pages des écrans et les menus défilent seuls (`overflow-y: auto`, `overscroll-behavior:
  contain`) ; `min-height: 0` sur les enfants de grille et de flex ; jamais `100vh` ni de hauteur fixe en
  pixels pour une liste ; `[hidden] {display: none !important}` ; les cadres qui coupent sans défiler sont
  en `overflow: clip` (un cadre `hidden` défile encore par programme).
- **Couleurs** : seulement les jetons de `css/theme.css` (`var(--accent)`…), jamais en dur ; contrastes AA
  vérifiés par `atelier/tests/test_coque.py` (texte 4,5:1 sur tous les fonds, dans les deux thèmes).
- Toute conversion mètres ↔ pixels de la carte se fait côté serveur (`atelier.lieu.conversions`).
- Stockage du navigateur (`CLES_MEMOIRE`, toujours dans un try/catch) : `atelier.mode`, `atelier.repetition`,
  `atelier.theme`, `atelier.lieu`, `atelier.etage`, `atelier.onglet.<mode>`, `atelier.vue.<mode>`,
  `atelier.calques`, `atelier.arbre.replie`, `atelier.ruban.replie` ; les anciennes clés
  `atelier.mode-simulation`, `atelier.scan.mode`, `atelier.scan.repetition` restent écrites.

## Repères stables des tests

Les tests ne cherchent jamais un bouton par son texte : `[data-role=accueil]`, `[data-role=mode-simu|mode-reel]`,
`[data-role=repetition]`, `[data-role=verifications] [data-verif=ros|cable|robot|telecommande]` (`data-etat`),
`[data-role=liste-lieux] [data-lieu=<id>]`, `[data-role=ouvrir]` ; `[data-role=espace]` (`data-mode`),
`[data-role=barre-outils|lieu|etage|accueil-retour|defaire|refaire|enregistrer|theme|arret]` ;
`[data-role=ruban]`, `[data-onglet=<id>]`, `[data-commande=<id>]`, `[data-role=avance]` ; `[data-role=arbre]`,
`[data-noeud=<genre>:<id>]` ; `[data-role=vue|vue-plan|vue-3d|vue-camera|barre-vue]`, `[data-vue]`,
`[data-cadrage]`, `[data-calque]` ; `[data-role=panneau|panneau-titre|panneau-corps|ok|annuler]` ;
`[data-role=barre-etat|etat-message|etat-coordonnees|etat-liaison]` ; `[data-role=confirmation|confirmer|renoncer]` ;
`[data-ecran=<id>]` sur l'écran ouvert. Liste complète : section 12.2 du plan.

## Routes de la coque

- `POST /api/arret {mode?, raison?}` → `{arrete, mode, verrou, duree_s, parties: {guide, teleop, pilotage,
  verrou: {ok, detail}}, message}`, toujours 200 et en moins de 1 s (`atelier/serveur/routes/arret.py`) ;
  `POST /api/arret/debloquer` ; `GET /api/arret` (aussi dans `/ws/etat`, champ `arret`).
- `GET /api/robot/liaison` → câble (`/sys/class/net/<interface>/carrier`), ping du PC1 et du Jetson (seulement
  si le câble est là), domaine ROS et `CYCLONEDDS_URI`, `pret`, `message` (`routes/liaison.py`). Réglages :
  `ATELIER_INTERFACE_ROBOT` (eno2), `ATELIER_PC1` (192.168.123.161), `ATELIER_JETSON` (192.168.123.164) ;
  les tests visent `lo` et 127.0.0.1.

## Tests

```bash
cd ~/robot-g1
.venv-projet/bin/python -m pytest -q atelier/tests/test_coque.py            # registre, icônes, contrastes, feuilles, pas de boîte native
.venv-projet/bin/python -m pytest -q atelier/tests/test_coque_navigateur.py # Firefox sans fenêtre : accueil, mise en page, ARRÊT, thème
.venv-projet/bin/python -m pytest -q atelier/tests/test_arret.py atelier/tests/test_liaison.py
E2E_DOMAINE=101 tests_e2e/tout.sh 9 31 36                                   # parcours, coque à trois tailles, ARRÊT global
DISPLAY=:1 .venv-projet/bin/python -m pytest -q atelier/tests/test_carte3d_web.py atelier/tests/test_carte3d_geometrie.py atelier/tests/test_carte3d_navigateur.py
.venv-projet/bin/python -m pytest -q atelier/tests/test_camera_geometrie.py atelier/tests/test_camera_serveur.py atelier/tests/test_camera_navigateur.py
DISPLAY=:1 E2E_DOMAINE=101 tests_e2e/tout.sh 32 35                           # carte 3D par la coque (WebGL), caméra
```

- La carte 3D a besoin de WebGL : Firefox sans fenêtre n'en a qu'avec l'affichage X de la session
  graphique (`DISPLAY=:1` : aucune fenêtre ne s'ouvre). Sans lui, la coque passe au Plan 2D, les tests
  WebGL sont sautés et le critère 32 répond « en attente ».

- `atelier/tests/test_coque_communs.py` : la mesure de la mise en page dans la page (rien ne déborde, chaque
  élément cliquable de la barre d'outils, du ruban, de l'arbre, du panneau et de la barre de la vue peut être
  amené à l'écran, entier et non recouvert ; ARRÊT visible) et les parcours partagés par les tests et le
  critère 31.
- Critère 31 (`tests_e2e/critere_31_coque.sh`) : la même mesure à 1366 × 768, 1600 × 1000 et 1920 × 1080, en
  Simulation, en Réel et en répétition, pour chaque onglet et chaque commande ; `CRITERE31_CAPTURES=dossier`
  ajoute des captures (accueil et chaque onglet, thèmes sombre et clair). Captures seules :
  `tests_e2e/outils_coque_e2e.py captures --api http://127.0.0.1:8111 --sortie dossier`.
- Critère 36 (`tests_e2e/critere_36_arret.sh`) : l'ARRÊT en simulation (sans verrou), en répétition (guide,
  verrou, Débloquer), par le bouton et Échap dans Firefox, et avec le nœud pilotage (joystick, nœud arrêté).
- Les écrans des vagues précédentes ont leurs tests dans Firefox sans fenêtre, réécrits sur les repères de la
  coque : `test_serveur_navigateur.py` (critère 9 : créer, dessiner, carte, salle, simulation, Y aller),
  `test_robot_navigateur.py`, `test_principal_navigateur.py`, `test_passants_navigateur.py`,
  `test_guide_navigateur.py`, `test_pilotage_navigateur.py`, `test_pilotage_vue_navigateur.py`,
  `test_equipe_navigateur.py`.

## Où sont passés les anciens onglets

| Avant (vagues 1 à 4) | Maintenant |
|---|---|
| Lieux | l'accueil (liste, Nouveau lieu) ; la fiche du lieu : clic sur le lieu dans l'arbre |
| Monde, Carte | Simulation › Dessiner (la carte se refait seule après « Enregistrer » ; Avancé : Refaire la carte) |
| Salles, Itinéraires, Zones | Placer (Simulation et Réel) ; l'accueil (point principal) : commande « Accueil » |
| Simulation | Simulation › Simuler ; la répétition et le vrai robot : Réel › Naviguer (repérage, Y aller, bloquer) ; passants, guide, faux visiteur : Simuler › Avancé et le panneau |
| Scan | Réel › Scanner ; le scan simulé : Simulation › Simuler › Avancé › Scan simulé |
| Pilotage | Réel › Piloter (la vue du robot au centre, deux joysticks en surimpression ; postures et gestes dans le ruban ; Spectacle : danses et chorégraphies) |
| Personnalités, Dialogues, Caméra | Équipe |

Les détails de chaque écran (repérage, passants, comportement du guide, pilotage, équipe) sont dans les
sections 10.8, 11 et 12 du plan (`docs/plan-atelier-multi-agents.md`).
