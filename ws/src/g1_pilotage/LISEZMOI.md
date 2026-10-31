# g1_pilotage

Pilotage du G1 depuis l'onglet **Pilotage** de l'Atelier (vague 4, section 11.5 du plan), comme
l'appli Unitree Explore : postures, marche au joystick avec homme mort, gestes des bras, voix,
volume, LED, danses déjà dans le robot, chorégraphies « sûres » (bras par rt/arm_sdk, pas de marche
d'Unitree), et le verrou des mouvements avec le guide.

```
Navigateur (onglet Pilotage) ── /api/pilotage/*, /ws/pilotage ──► serveur de l'Atelier (PC)
   ── HTTP et WebSocket (G1_PILOTAGE_URL, port 8010, en-tête X-Jeton) ──► nœud pilotage (ce paquet,
      dans le conteneur du Jetson ; sur le PC en simulation et en répétition)
   ── ROS 2 ──► services sport, arm, voice (/api/<service>/request et /response) et rt/arm_sdk
```

Jamais de mode debug, de rt/lowcmd, de passage en commande utilisateur (7110) ni de politique corps
entier : l'équilibre et les jambes restent toujours au contrôleur d'Unitree.

## Lancer

| Où | Comment |
|---|---|
| Conteneur du Jetson (robot) | `G1_PILOTAGE=1`, défaut de `g1-jetson demarrer` ; jeton créé une fois dans `opt/jetson/jeton_pilotage` (lu aussi par l'Atelier) |
| PC, simulation ou répétition | bouton « Démarrer le pilotage » de l'onglet (POST `/api/pilotage/demarrer`, rôle `pilotage`) ou `g1-pilotage noeud` |
| À la main | `ros2 run g1_pilotage pilote [--port 8010] [--hote 127.0.0.1] [--vitesse-max 0.2]` |

Variables : `G1_PILOTAGE_PORT` (8010), `G1_PILOTAGE_JETON` (exigé dans l'en-tête `X-Jeton` ; vide :
seules les connexions de la machine elle-même sont acceptées), `G1_VITESSE_MAX` (plafonds de la
marche baissés d'autant). Côté Atelier : `G1_PILOTAGE_URL` (défaut `http://127.0.0.1:8010` ;
avec le robot : `http://<adresse Wi-Fi du Jetson>:8010`, ou `http://192.168.123.164:8010` au câble)
et le même `G1_PILOTAGE_JETON`.

Ctrl+C ou SIGTERM : la chorégraphie s'arrête (poids des bras ramené à 0 en 1 s), StopMove, et le
guide reprend la main (`/mouvement/maitre`).

## Fichiers

| Fichier | Rôle |
|---|---|
| `g1_pilotage/logique.py` | toutes les règles, sans ROS, horloge injectable (classe `Pilotage`) |
| `g1_pilotage/coeur.py` | la logique sous un verrou, l'attente des réponses du robot, la prise de la main |
| `g1_pilotage/noeud.py` | le nœud ROS 2 (publications, abonnements) et le fil à 50 Hz |
| `g1_pilotage/serveur.py` | l'API HTTP et WebSocket (tornado) |
| `g1_pilotage/pilote.py` | l'exécutable `pilote` |
| `g1_pilotage/commande.py` | `g1-pilotage` (l'onglet en ligne de commande) |
| `g1_pilotage/contrat.py` | trouve `atelier.lieu.pilotage` (contrat : refus, confirmations, limites) |

## Sujets ROS 2

| Sujet | Type | Sens | Rôle |
|---|---|---|---|
| `/api/sport/request`, `/api/arm/request`, `/api/voice/request` | unitree_api/Request | sortie | ordres, remplis comme le SDK (identity croissante, lease 0, priorité 0) |
| `/api/<service>/response` | unitree_api/Response | entrée | réponses, appariées par `identity.id` (au mieux) |
| `/arm_sdk` | unitree_hg/LowCmd | sortie | bras des chorégraphies, 50 Hz pendant une chorégraphie seulement |
| `/lowstate` | unitree_hg/LowState | entrée | angles mesurés : taille tenue à sa position du départ |
| `/lf/bmsstate` | unitree_hg/BmsState | entrée | batterie (`soc`), à vérifier sur le robot |
| `/mouvement/maitre` | std_msgs/String JSON (fiable, transient_local, profondeur 1) | sortie | verrou des mouvements (schéma `maitre_mouvement`) |
| `/pilotage/etat` | std_msgs/String JSON | sortie | 2 Hz et à chaque changement (schéma `etat_pilotage`) |
| `/guide/stop` | std_msgs/Empty | sortie | à la prise de la main forcée, et à chaque ARRÊT |
| `/guide/etat`, `/pont/etat` | std_msgs/String JSON | entrée | refuser la main pendant une visite ; robot immobile ? |
| `/robot/dire` | std_msgs/String JSON | sortie | paroles des chorégraphies (voix de l'équipe) |
| `/personnalite/active` | std_msgs/String JSON (fiable, transient_local) | entrée | LED de la personnalité active (voice 1010, toujours permise) ; assemblage de la vague 4 |
| `/robot/geste` | std_msgs/String JSON (schéma `robot_geste`) | entrée | geste demandé par l'équipe (règle « geste » du chatbot, `geste_salut` de la personnalité) : fait seulement robot au repos (guide maître sans mission, aucune danse, chorégraphie ni prise de main, bras libres), un toutes les 10 s au plus, bras relâchés (99) 5 s après |

## API HTTP et WebSocket du nœud

Réponses JSON avec un `detail` en français. Codes : 200 fait ; 202 (interne) prise de la main en
cours ; 400 demande mal formée ; 401 jeton ; 403 interdit (rien n'est envoyé au robot) ; 409 verrou,
activité en cours ou refus du robot (`code` et message traduits) ; 422 chorégraphie fausse
(`erreurs`) ; 428 confirmation demandée (`confirmation` : `portique` ou `zone_libre` ; `jeton` pour
la confirmation double) ; 504 le robot ne répond pas en 2 s.

| Route | Corps | Rôle |
|---|---|---|
| `GET /etat` | | état (schéma `etat_pilotage`, plus `maitre_detail`, `limites`, `batterie`, `lowstate`…) |
| `GET /danses[?lire=1]` | | danses du robot ; `lire=1` : 7100 `{"fsm_id": 550, "api_id": 1}` au robot |
| `GET /gestes[?lire=1]` | | gestes d'Unitree (et la liste 7107 du robot) |
| `GET /camera` | | image JPEG de la caméra de la tête (service videohub, GetImageSample 1001 ; une demande à la fois, 5 par seconde au plus, en-têtes `X-Image-Age-S` et `X-Image-Numero`) ; 503 sans image ; permise sans la main (Vue du robot, plan 11.13) |
| `POST /maitre` | `{maitre: pilotage\|guide, forcer?, par?}` | prendre (409 pendant une visite, sauf `forcer`) ou rendre la main |
| `POST /posture` | `{fsm, portique?, jeton?}` | 7101 : 500, 706, 702, 3 ; 1 et 0 : case `portique` puis confirmation double (10 s) |
| `POST /tache` | `{tache}` | sport 7106 : 0, 1 saluer ; 2, 3 serrer la main |
| `POST /geste` | `{action}` | arm 7106 `{"action_id"}` ; 99 relâche (permis sans la main) |
| `POST /voix`, `/volume`, `/led` | `{texte, voix?}`, `{volume}`, `{r, g, b}` | 1001, 1006, 1010 : toujours permis |
| `POST /danse` | `{id, zone_libre}` | 7101 `550000 + id` ; jamais 401, 402, 403 ni une danse absente de la liste |
| `POST /choregraphie` | `{choregraphie, zone_libre}` | vérifiée (`verifier_choregraphie`), puis jouée ; rend `debut_mur` |
| `POST /requete` | `{service, api_id, parametre, portique?, jeton?, zone_libre?}` | mode avancé : les mêmes règles |
| `POST /arret` | `{par?}` | ARRÊT, toujours permis |
| `WS /joystick` | `{vx, vy, wz}` toutes les 0,1 s ; `{lacher: true}` | un 7105 de 0,5 s par ordre ; sans ordre depuis 0,5 s : StopMove ; fermeture : StopMove tout de suite ; un seul joystick à la fois |

## Les règles (logique.py)

- **Homme mort** : chaque ordre du joystick donne un 7105 de 0,5 s, plafonné (`LIMITES_MARCHE`,
  baissés par `G1_VITESSE_MAX`, refusée sous 0,2 m/s : le nœud ne démarre pas) ; au plus 20 ordres
  par seconde ; sans ordre depuis 0,5 s, StopMove ; WebSocket fermé, StopMove tout de suite. Le
  robot est arrêté 0,6 s au plus après le dernier ordre.
- **Vitesse minimale et mode (vague 5)** : l'ordre passe par la vitesse minimale du pont
  (`consigne_marche`, `atelier.lieu.robot.vitesse_effective`) : sous 0,2 m/s le vrai G1 ne fait aucun
  pas, une petite inclinaison du manche le fait donc marcher à 0,2 m/s dans la même direction (sous
  0,05 m/s et 0,1 rad/s : arrêt). Le joystick est refusé (409, message qui dit quoi faire) quand le
  mode lu par 7001 (moins de 3 s) n'est ni la marche (500, 501, 801) ni la course (802), par exemple
  assis ; un mode inconnu ne bloque rien.
- **Verrou** : sans la main, joystick, postures, gestes, danses et chorégraphies sont refusés (409) ;
  voix, volume, LED, geste 99 et ARRÊT restent permis. Prendre la main pendant une visite du guide :
  409, sauf `forcer` (/guide/stop, robot immobile, puis maître `pilotage`). Le pont ignore alors
  `/cmd_vel` (état `pilotage`) et le guide refuse `/guide/aller`.
- **Danses** : liste lue dans le robot ; robot debout immobile en mode marche (500, 501 ou 801 ; le
  27/10, la marche lue était 501) ; confirmation « zone libre » ; pendant la danse, joystick, gestes,
  postures et chorégraphies refusés ; ARRÊT : StopMove seulement (aucun ordre connu n'interrompt une
  danse : la télécommande reste l'arrêt d'urgence) ; fin quand le robot est revenu en marche (501 ou
  801, lu par 7001) : après la durée annoncée, ou plus tôt s'il a été vu danser puis revenu ; pas
  revenu : supposée finie 10 s après la durée, avec un message.
- **Chorégraphies** : vérifiées avant de jouer ; bras à 50 Hz, temps planifié régulier ; chaque ordre
  borné une seconde fois (limites, 1,5 rad/s au plus par pas de 20 ms, poids à 1 par seconde au
  plus) ; taille tenue à sa position mesurée au départ (gains ×4), jambes jamais écrites ; pas de
  marche plafonnés (`LIMITES_PAS`), renvoyés à 10 Hz avec la durée qui reste ; vague 5 : un pas sous
  la vitesse minimale du vrai robot est fait plus vite et moins longtemps, même trajet
  (`atelier.lieu.pilotage.pas_effectif`, aussi à mi-vitesse de lecture), un pas trop petit (zones
  mortes) est remplacé par un arrêt, et `avertissements_choregraphie` le dit (réponse de « jouer »,
  et routes de l'Atelier) ; LED, gestes et paroles à leur temps ; départ 0,5 s après la demande
  (`debut_mur`, pour la musique de la page).
- **ARRÊT** : StopMove, chorégraphie arrêtée (poids ramené à 0 en 1 s, bras immobiles), geste relâché
  (99) si les bras tiennent un geste, `/guide/stop`.

## Tests

```bash
cd ~/robot-g1/ws && colcon build --symlink-install --packages-select g1_pilotage
colcon test --packages-select g1_pilotage && colcon test-result --all
```

`test/test_logique.py` (règles, horloge à la main), `test/test_serveur.py` (API tornado et WebSocket,
faux robot en mémoire). Bout en bout contre le faux G1 dans Gazebo : `tests_e2e/critere_28_pilotage.sh`
et `critere_29_danses.sh` ; l'Atelier : `atelier/tests/test_pilotage_serveur.py` et
`test_pilotage_navigateur.py`.

## À vérifier sur le robot

Les formats viennent du SDK d'Unitree et d'une source communautaire non officielle (danses) : liste
complète dans `docs/seance-robot.md` (pilotage) et la section 11.11 du plan. Au portique d'abord,
télécommande en main.
