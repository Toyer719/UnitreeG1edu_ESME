# g1_bridge : le pont vers la marche du G1

Le nœud `pont_g1` transforme les vitesses de Nav2 (`/cmd_vel`) en ordres de marche du G1 :
`unitree_api/msg/Request` sur `/api/sport/request`, commande 7105 (SetVelocity). Contrat : section
10.3 du plan (`docs/plan-atelier-multi-agents.md`).

```bash
ros2 run g1_bridge pont                                     # réglages par défaut (= config/pont.yaml)
ros2 run g1_bridge pont --ros-args -p exiger_reperage:=false   # essai au portique SEULEMENT
```

En temps normal, c'est `navigation.launch.py` (paquet `g1_nav`) qui le lance, avec `pont:=true`
ou `g1-guide navigation ... --pont oui`.

## Ce que fait le pont

| Règle | Valeur |
|---|---|
| Plafonds durs (avec le signe) | vx 0,4 m/s, vy 0,25 m/s, wz 0,6 rad/s ; un réglage plus haut est refusé au démarrage |
| Valeur non finie (NaN, infini) | toute la consigne devient un arrêt |
| Consigne fraîche (< 0,3 s) | envoyée à 10 Hz, `duration` 0,5 s : si le pont meurt, le robot s'arrête seul |
| Plus de `/cmd_vel` depuis 0,3 s | un arrêt tout de suite, puis plus rien |
| `/guide/stop` | arrêt immédiat, `/cmd_vel` ignoré 1 s |
| `/pont/arret` true / false | arrêt envoyé 3 fois en 0,2 s, verrou ; reprise seulement avec un `/cmd_vel` neuf |
| Repérage | mouvement permis seulement si `/reperage/etat` (moins de 1 s) dit `repere` |
| Robot muet | aucune réponse depuis 1 s : état `robot_muet` |
| Refus | réponse de code non nul : état `refus`, avec le code et un message |
| Lancement et sortie | un arrêt (vérification du lien au lancement, dès que le service est vu) |
| `/mouvement/maitre` « pilotage » (vague 4) | état `pilotage` : `/cmd_vel` ignoré, un arrêt s'il bougeait ; « guide » (ou aucun message) : comme avant, reprise seulement avec un `/cmd_vel` neuf |

L'arrêt est `{"velocity": [0.0, 0.0, 0.0], "duration": 1.0}` (StopMove du SDK). La requête est
remplie exactement comme `LocoClient::SetVelocity` (C++) et `LocoClient.SetVelocity` (SDK Python) :
`test/test_requete.py` compare le message sérialisé octet par octet au SDK Python, et à la requête
réellement publiée par `g1_loco_client_example`.

État : `/pont/etat` (JSON, schéma `atelier/lieu/schemas/etat_pont.schema.json`), 2 Hz et à chaque
changement. Pour bloquer le robot à la main :

```bash
ros2 topic pub --once --qos-durability transient_local --qos-reliability reliable /pont/arret std_msgs/msg/Bool "{data: true}"
```

## Tests

```bash
cd ~/robot-g1/ws/src/g1_bridge && python3 -m pytest test     # environ 1 min, sans robot ni Gazebo
```

`test_logique.py` (règles avec une horloge à la main), `test_requete.py` (format, SDK et C++),
`test_reglages.py` (`config/pont.yaml` = valeurs du contrat), `test_noeud_pont.py` (le nœud en
vrai, le test joue le robot). Les essais dans Gazebo, avec le faux G1, sont dans `g1_jumeau`.
