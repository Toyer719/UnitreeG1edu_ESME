# g1_accueil : la démo d'accueil

Le nœud `accueil` mène la démo d'accueil du G1 (vague 6, section 13.4 du plan) : un visiteur s'approche
(ou touche la borne), le robot le salue, le visiteur choisit une salle sur la borne, le robot l'y
accompagne (le guide de la vague 4 conduit), annonce l'arrivée et revient seul à l'accueil. Après un
arrêt, un blocage ou une panne, la démo se met en **pause** et ne repart jamais seule.

```bash
g1-accueil --lieu demo --etage rdc       # lancé par l'Atelier : Équipe › Démo › Lancer la démo
g1-accueil --lieu demo -- --ros-args -p delai_choix_s:=30.0 -p suivre_pont:=false
```

## Ce qu'il fait

| État | Quand | Ensuite |
|---|---|---|
| `demarrage` | au lancement | guide vu et robot à l'accueil → `attente` ; pas de guide en 3 s → `pause` (`guide_absent`) |
| `attente` | robot à l'accueil, guide au repos | visiteur vu (LiDAR ou caméra : à 1,5 m au plus, devant, depuis 1 s) ou appui sur la borne → `salutation` ; un choix → `depart` |
| `salutation` | la salutation de la personnalité est dite (et son geste) | 1 s après → `choix` |
| `choix` | la borne montre les salles | un choix accepté → `depart` ; 45 s sans choix, ou « Annuler » → `attente` |
| `depart` | `/guide/aller` envoyé (`source: accueil`, `accompagner`, `retour`, `id`) | le guide part → `accompagnement` ; 10 s sans départ → `pause` (`echec`) |
| `accompagnement` | le guide conduit | arrivé → `arrivee` ; visiteur perdu → `retour` (visite abandonnée) |
| `arrivee` | arrivé à la salle | le retour automatique du guide → `retour` |
| `retour` | le robot rentre | à l'accueil, guide au repos → `attente` (8 s avant de saluer quelqu'un d'autre) |
| `occupe` | le guide fait une visite que la démo n'a pas demandée | guide au repos à l'accueil → `attente` |
| `pause` | ARRÊT, verrou, robot pas en marche, muet, pont absent, échec, robot perdu, pilotage, guide muet, opérateur | **seulement** « Reprendre » (robot à l'accueil, plus rien n'empêche) → `attente`, ou « Ramener à l'accueil » (demande explicite) → `retour` |

En pause : aucun `/guide/aller` (sauf « Ramener »), la borne dit « Je fais une petite pause », un choix est refusé,
la phrase de pause est dite une fois (priorité `securite`). Une pause pendant une visite envoie `/guide/stop`
(la demande en attente, le trajet et le retour prévu sont annulés). La levée d'un empêchement (« Débloquer »,
robot remis en marche, pont relancé, main rendue) ne fait que rendre « Reprendre » possible. Pendant une visite,
un blocage vu par la démo attend 0,8 s que le guide dise pourquoi (ARRÊT : `arret`, « Bloquer » : `verrou`).

## Sujets

- écoute : `/guide/etat`, `/guide/evenement`, `/pont/etat`, `/pont/arret` (fiable, transient_local),
  `/mouvement/maitre`, `/personnalite/active` (transient_local), `/visiteurs/detectes`, `/personnes/lidar`,
  `/accueil/choix`, `/accueil/commande`, et la position du robot par TF `map → base_link` ;
- publie : `/guide/aller`, `/guide/stop`, `/robot/dire`, `/robot/geste`, `/accueil/etat` (2 fois par seconde et à
  chaque changement), `/accueil/evenement` (chaque choix ou commande avec un `id` reçoit sa réponse, même `id`).

Les événements du guide sont relayés vers `/robot/dire` avec les phrases de la personnalité
(`atelier.equipe.relais.Relais`, comme le nœud `dialogue` : lancez celui-ci avec `relayer_evenements:=false`
quand la démo tourne). Le chatbot de l'équipe choisit une salle par `/accueil/choix` (`source: dialogue`).

## Paramètres

`lieu` (obligatoire), `etage` (défaut : celui du point principal), et les réglages de
`atelier.lieu.accueil.REGLAGES_DEMO`, dont les défauts viennent de `demo.yaml` du lieu : `source_visiteurs`
(`auto`, `camera`, `lidar`, `borne`), `distance_visiteur_m`, `presence_s`, `delai_choix_s`, `delai_depart_s`,
`delai_entre_visiteurs_s`, `accompagner`, `retour`, `relayer_evenements`, `saluer_geste`, `suivre_pont`
(l'Atelier le met à faux en simulation : un verrou resté posé par une répétition n'y bloque pas la démo),
`distance_principal_m` ; plus `repere_carte` (`map`), `repere_robot` (`base_link`), `frequence` (10 Hz),
`relire_s` (2 s : `salles.yaml` et `personnalites.yaml` relus s'ils changent). La personnalité de `demo.yaml`
(si elle y est) est imposée, sinon la démo suit `/personnalite/active`.

## Fichiers et essais

- `g1_accueil/logique.py` : la machine d'états sans ROS (`Orchestrateur.entrer(sujet, donnees, t)`, `pas(t)`,
  `etat(t)`), testée à fausse horloge par `test/test_logique.py` ;
- `g1_accueil/noeud.py` : le nœud ROS 2, testé en vrai (faux guide, TF, borne) par `test/test_noeud.py` ;
- critères 39 (la borne), 41 (la démo complète en simulation) et 42 (la sécurité de la démo) dans `tests_e2e/`.

```bash
cd ~/robot-g1/ws && colcon build --symlink-install --packages-select g1_accueil
colcon test --packages-select g1_accueil && colcon test-result --verbose
```
