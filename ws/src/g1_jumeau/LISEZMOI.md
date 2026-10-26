# g1_jumeau : le faux G1 de la répétition

Le nœud `g1_jumeau` joue le service de marche (« sport ») du G1 dans Gazebo, pour essayer le pont et
la navigation du vrai robot sans robot. Contrat : section 10.4 du plan.

```bash
g1-monde simuler --lieu demo --etage rdc --sans-fenetre --jumeau    # Gazebo + robot proxy + faux G1
ros2 run g1_jumeau jumeau --ros-args -p latence_s:=0.2 -p perte:=0.1  # seul, avec latence et pertes
```

| Sujet | Sens | Rôle |
|---|---|---|
| `/api/sport/request` | entrée | comme le vrai service : 7105 `{"velocity": [vx, vy, wz], "duration": d}` |
| `/api/sport/response` | sortie | identité recopiée, code 0 ; api inconnue 3203 ; paramètres illisibles 3204 ; panne refus 7301 |
| `/g1_jumeau/cmd_vel` | sortie | vers Gazebo, 20 Hz : la consigne pendant `duration` (temps mural), sinon zéro |
| `/g1_jumeau/odom` | entrée | vérité terrain de Gazebo (repère du monde = map) |
| `/state_estimator/odom_pelvis` | sortie | odométrie comme celle du robot (repère `odom` → `pelvis`, z 0,75 m), qui dérive de 2 % et de 0,01 rad par mètre |
| `/g1_jumeau/panne` | entrée | `aucune`, `muet` (ne répond plus, n'applique plus rien) ou `refus` |
| `/g1_jumeau/etat` | sortie | JSON à 2 Hz, pour les tests |

Paramètres : `latence_s` (délai avant d'appliquer et de répondre), `perte` (part des requêtes
perdues), `graine`, `panne`. Le faux G1 n'a pas de plafond à lui : le vrai robot a les siens.

## Le faux G1 étendu (vague 4, section 11.5 du plan)

Pour l'onglet Pilotage et les critères 28 et 29, le faux G1 répond aussi comme le vrai aux autres
commandes (`g1_jumeau/robot.py`, logique sans ROS, classe `FauxG1`) :

| Service | Ce qu'il fait |
|---|---|
| sport 7001 à 7006 | lectures ; 7001 rend `{"data": mode}` (801 au lancement : debout, prêt à marcher ; paramètre `fsm_depart`) |
| sport 7101 | modes 0, 1, 3, 500 (puis 801 après 1 s), 702 (puis 801 après 2 s), 706 (accroupi ↔ debout) ; autre mode : 7302 ; danse 550000 + n depuis 801 seulement (7301 sinon), durée de la liste (paramètre `echelle_danses`), puis retour seul en 801 |
| sport 7105 | comme avant (FauxSport) ; refusé (7301) hors de 500/801 et pendant une danse, sauf l'arrêt `[0, 0, 0]`, sans effet |
| sport 7100 | `{"fsm_id": 550, "api_id": 1}` : la liste `{"fsm_id", "api_id", "motion": {"604": {"name", "duration"}}}` (602, 603, 604, 574, et 401, 402, 403 pour éprouver les refus) ; autre paramètre : 3204 |
| sport 7106 | tâches 0 à 3 (7303 sinon) |
| sport 7102, 7103, 7104, 7107, 7110, 7111 | acceptées comme par le vrai robot, mais **comptées** (`nombre_interdits`) : les tests vérifient qu'il n'en arrive jamais |
| arm 7106 | gestes `{"action_id"}` (ou `{"data"}`) : 7402 inconnu, 7404 hors de 500/501/801, 7400 si rt/arm_sdk pilote les bras, 7401 pour un autre geste pendant que les bras tiennent le précédent ; 99, ou le même geste, relâche ; un geste tient 20 s au plus |
| arm 7107, 7108, 7113 | liste des gestes, gestes appris, arrêt d'un geste appris |
| voice 1001, 1005, 1006, 1010 | TTS, volume, LED : dernières valeurs et historique horodaté gardés |
| `/arm_sdk` | chaque LowCmd est vérifié (`VerificationArmSdk`) : poids dans [0, 1] et sans saut (rampe de 1 s au moins), angles dans `LIMITES_BRAS`, vitesse par ordre au plus `VITESSE_BRAS_MAX`, taille tenue, jambes et moteurs 30 à 34 jamais écrits ; tout écart est compté |
| `/lowstate` | 50 Hz : les bras suivent l'ordre pondéré par le poids d'arm_sdk, sinon la pose où le contrôleur d'Unitree les tient |
| `/lf/bmsstate` | 1 Hz : batterie simulée (`soc`) |

`/g1_jumeau/etat` porte tout cela dans son champ `robot` : `fsm`, `danse`, `bras_tenus`,
`postures`, `gestes_joues`, `interdits_recus`, `voix` (`tts`, `volume`, `led`, `led_historique`),
`arm_sdk` (`recus`, `sessions` avec `frequence_hz`, `rampe_montee_s`, `rampe_descente_s`, et
`ecarts`).

Avec `jumeau:=true`, `g1_sim` ne relie plus le robot proxy à `/cmd_vel`, `/odom` ni `/tf`
(`config/pont_gz_jumeau.yaml`) : en répétition, aucune vitesse ne va directement à Gazebo.
Limite : un SIGKILL du faux G1 laisse la dernière consigne dans Gazebo (le vrai robot, lui,
s'arrête seul à la fin de `duration`).

## Tests

```bash
cd ~/robot-g1/ws/src/g1_jumeau && python3 -m pytest test     # environ 1 min 30, Gazebo sans fenêtre
```

`test_logique.py` (service et dérive, sans ROS), `test_robot.py` (le faux G1 étendu, sans ROS), `test_noeud_jumeau.py` (le nœud en vrai, et le
client C++ d'Unitree `g1_loco_client_example` qui reçoit sa réponse), `test_lancement_sim.py`
(argument `jumeau` de `g1_sim`, `g1-monde simuler --jumeau`), `test_gazebo.py` (pont → faux G1 →
Gazebo : 0,9 m en 3 s, plafonds mesurés, arrêts, pont tué).
