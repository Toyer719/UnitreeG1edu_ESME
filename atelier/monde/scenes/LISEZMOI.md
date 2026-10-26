# Scènes des passants

Une scène par fichier `<id>.scene.yaml` (format : `atelier/lieu/schemas/scene.schema.json`, section
11.3 du plan). Fichiers de l'agent Passants, sauf `accompagnement*.scene.yaml` (agent Comportement du
guide). Une scène ne modifie jamais `lieux/demo` : elle s'applique à une copie.

```bash
g1-banc --scene immobile_couloir                 # copie du demo, Gazebo et Nav2 lancés, 5 essais, seuils
g1-banc --scene en_face --reaction ecart         # la même scène, piétons qui s'écartent du robot
g1-banc --scene foule --travail /tmp/essai       # copie et journaux ailleurs que dans ~/robot-g1/journaux
```

Le banc copie le lieu de référence de la scène (`lieu`, en général `demo`), remplace (ou complète,
`ajouter: true`) les piétons de son monde, recopie `reglages_guide` dans la section `guide` de
`lieu.yaml`, regénère le monde, lance la simulation et la navigation, puis fait les trajets. Avant
chaque essai, le robot est reposé au départ dans Gazebo et les piétons-corps reprennent la scène au
début (`/pietons/reinitialiser`) ; les temps (`depart_s`, `pauses`) comptent depuis ce moment. Le CSV
a les colonnes de la vague 4 (contacts et leur cause, distance bord à bord, attentes de passage,
longueur parcourue) ; le code de sortie vaut 1 si un seuil de `mesures` n'est pas tenu.

| Scène | Piétons | Essais | Seuils |
|---|---|---|---|
| `immobile_couloir` | un passant debout en (12 ; 13), qui ne voit pas le robot | accueil → b204 × 5 | 100 %, 0,20 m bord à bord, 0 contact du robot, 0 détour, 180 s |
| `en_face` | un passant qui remonte le couloir nord vers l'ouest sur la ligne du robot, 1 m/s, sans le voir (départ 8 s après le robot) | accueil → b204 × 5 | 80 %, 0 contact du robot, 180 s |
| `coupe_route` | un passant qui traverse le hall en va-et-vient (1 m/s) en coupant la ligne x = 2,5 entre y = 11,5 et 12,5 | accueil → b204 × 5 | 80 %, 0 contact du robot, 180 s |
| `groupe_couloir` | trois passants en travers du couloir nord (x = 15,5), qui partent vers b204 environ 15 s après l'arrivée du robot | accueil → b204 × 3 | 100 %, 0 détour, 0 contact du robot, 180 s |
| `groupe_reste` | les mêmes, qui restent 600 s | accueil → b204 × 2 | 100 %, 300 s, 75 m parcourus au plus |
| `foule` | les 5 piétons du critère 6 (le demo et 3 de plus), qui s'écartent du robot | 20 trajets tirés au sort | 90 %, 0 contact du robot |

Pour `groupe_couloir`, le temps de pause du groupe (50 s depuis le début de l'essai) est réglé sur le
temps que met le robot à l'atteindre (35 s environ dans le demo) : le format des scènes n'a pas de
déclencheur « quand le robot arrive ».
