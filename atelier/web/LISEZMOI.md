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
