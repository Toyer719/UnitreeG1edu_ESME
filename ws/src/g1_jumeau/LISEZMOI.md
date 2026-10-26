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

Avec `jumeau:=true`, `g1_sim` ne relie plus le robot proxy à `/cmd_vel`, `/odom` ni `/tf`
(`config/pont_gz_jumeau.yaml`) : en répétition, aucune vitesse ne va directement à Gazebo.
Limite : un SIGKILL du faux G1 laisse la dernière consigne dans Gazebo (le vrai robot, lui,
s'arrête seul à la fin de `duration`).

## Tests

```bash
cd ~/robot-g1/ws/src/g1_jumeau && python3 -m pytest test     # environ 1 min 30, Gazebo sans fenêtre
```

`test_logique.py` (service et dérive, sans ROS), `test_noeud_jumeau.py` (le nœud en vrai, et le
client C++ d'Unitree `g1_loco_client_example` qui reçoit sa réponse), `test_lancement_sim.py`
(argument `jumeau` de `g1_sim`, `g1-monde simuler --jumeau`), `test_gazebo.py` (pont → faux G1 →
Gazebo : 0,9 m en 3 s, plafonds mesurés, arrêts, pont tué).
