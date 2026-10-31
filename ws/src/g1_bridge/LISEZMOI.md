# g1_bridge : le pont vers la marche du G1

Le nœud `pont_g1` transforme les vitesses de Nav2 (`/cmd_vel`) en ordres de marche du G1 :
`unitree_api/msg/Request` sur `/api/sport/request`, commande 7105 (SetVelocity). Contrat : section
10.3 du plan (`docs/plan-atelier-multi-agents.md`).

```bash
ros2 run g1_bridge pont                                     # réglages par défaut (= config/pont.yaml)
ros2 run g1_bridge pont --ros-args -p exiger_reperage:=false   # essai au portique SEULEMENT
# mesure du seuil de marche au portique (vague 5) : consignes brutes, sans minimum ni zone morte
ros2 run g1_bridge pont --ros-args -p exiger_reperage:=false -p vitesse_min_lin:=0.0 \
    -p vitesse_min_rot:=0.0 -p zone_morte_lin:=0.0 -p zone_morte_rot:=0.0
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
| Vitesse minimale (vague 5, règle 11) | le 27/10, le vrai G1 ne faisait aucun pas à 0,1 m/s et marchait à 0,2 m/s. Si la norme de (vx, vy) atteint `vitesse_min_lin` (0,2 m/s) ou si \|wz\| atteint `vitesse_min_rot` (0,3 rad/s), la consigne passe telle quelle ; sinon toute la consigne est petite : sous `zone_morte_lin` (0,05 m/s, sur la norme) et `zone_morte_rot` (0,1 rad/s), la composante vaut 0 ; puis la marche est portée à 0,2 m/s dans la même direction (sans dépasser les plafonds), ou la rotation seule à ± 0,3 rad/s. 0 désactive. Exemples : (0,1 ; 0 ; 0) → (0,2 ; 0 ; 0) ; (0,1 ; 0,1 ; 0) → (0,141 ; 0,141 ; 0) ; (0 ; 0 ; 0,15) → (0 ; 0 ; 0,3) ; (0,03 ; 0 ; 0) → arrêt. `vx_max` (ou `wz_max`) sous le minimum est refusé au démarrage, sauf avec le minimum à 0 (mesures) |
| Mode du robot (vague 5, règle 12) | lecture de 7001 (GetFsmId, `{}`) une fois par seconde ; hors de `modes_marche` (500, 501, 801 : assis 3, pas démarré 0, course 802...) : état `pas_en_marche`, un arrêt s'il bougeait, `/cmd_vel` ignoré, message qui dit quoi faire ; de retour en marche : `pret`, reprise avec un `/cmd_vel` neuf. Un mode inconnu (pas de réponse lisible, lecture refusée, lu il y a plus de 3 s) ne bloque rien. Seules les réponses à nos requêtes comptent (identity.id, et api_id quand il est rempli) : les 7001 des autres programmes du robot arrivent sur le même sujet |

**Zones « ralentir » de Nav2 et vitesse minimale** (revue de la vague 5) : le Collision Monitor de Nav2
ralentit le robot (× 0,5) près d'un obstacle ou d'une personne, puis le pont monte toute consigne
comprise entre 0,05 et 0,2 m/s à 0,2 m/s. Sous 0,4 m/s (et toujours avec `vitesse_max:=0.2`), ces zones
ne ralentissent donc plus le vrai robot : seul le cercle d'arrêt de 0,4 m l'arrête près d'un obstacle,
et `navigation.launch.py` le dit au lancement. Gardez la télécommande en main ; la conduite près des
personnes est à mesurer à la séance 2 (des zones « stop » arrêteraient aussi le robot devant les murs
des couloirs étroits et des portes).

L'arrêt est `{"velocity": [0.0, 0.0, 0.0], "duration": 1.0}` (StopMove du SDK). La requête est
remplie exactement comme `LocoClient::SetVelocity` (C++) et `LocoClient.SetVelocity` (SDK Python) :
`test/test_requete.py` compare le message sérialisé octet par octet au SDK Python, et à la requête
réellement publiée par `g1_loco_client_example`.

État : `/pont/etat` (JSON, schéma `atelier/lieu/schemas/etat_pont.schema.json`), 2 Hz et à chaque
changement. Vague 5 : `demande` (le dernier `/cmd_vel`, après les plafonds), `consigne` (ce qui est
vraiment envoyé, après la vitesse minimale), `minimums` (les quatre réglages) et `mode_robot`
(`{fsm, nom, en_marche, age_s, modes_marche, lectures}`, null avec `lire_mode:=false`). Ordre des
états : `arret_verrouille`, `robot_muet`, `pas_en_marche`, `refus`, `pilotage`,
`attente_reperage`, `arret`, `demarrage`, `en_mouvement`, `pret`.

| Réglage (vague 5) | Défaut | Rôle |
|---|---|---|
| `vitesse_min_lin` | 0,2 m/s (mesuré le 27/10) | norme minimale de (vx, vy) ; 0 désactive ; 0,3 au plus |
| `vitesse_min_rot` | 0,3 rad/s (à mesurer) | rotation sur place minimale ; 0 désactive ; 0,5 au plus |
| `zone_morte_lin`, `zone_morte_rot` | 0,05 m/s, 0,1 rad/s | en dessous : 0 ; pas plus que le minimum ; avec le minimum actif, au moins 0,01 m/s et 0,02 rad/s (une zone nulle ferait marcher le robot sur le moindre résidu de consigne : refusée au démarrage) ; une composante sous 0,001 n'est jamais montée au minimum |
| `lire_mode` | true | lecture de 7001 chaque seconde |
| `modes_marche` | [500, 501, 801] | ajouter 802 accepte la course |

Pour bloquer le robot à la main :

```bash
ros2 topic pub --once --qos-durability transient_local --qos-reliability reliable /pont/arret std_msgs/msg/Bool "{data: true}"
```

## Mesures pour la séance 2 (vague 5)

`python3 -m g1_bridge.mesure` envoie un échelon de vitesse sur `/cmd_vel`, donc toujours à travers
le pont (rien n'est envoyé si `/pont/etat` n'est pas « pret »), et lit l'odométrie du robot
(`/state_estimator/odom_pelvis`) : retard, montée, vitesse atteinte, arrêt et dépassement, en
français. Au plus 0,3 m/s, 0,6 rad/s et 5 s ; télécommande en main.

```bash
python3 -m g1_bridge.mesure marche --vx 0.2 --duree 2       # en avant (aussi --vy pour le côté)
python3 -m g1_bridge.mesure rotation --wz 0.3 --duree 3     # rotation sur place
python3 -m g1_bridge.mesure cap --pendant 20 --angle 90     # suit le cap pendant un Spin de Nav2 lancé à côté
```

Déroulé (chaque terminal : `source ~/robot-g1/setup/robot.sh` d'abord ; essayé le 31/10 contre le faux
G1, qui a un seuil de marche de 0,15 m/s et de rotation de 0,2 rad/s) :

1. **Au portique, pont sur le PC, consignes brutes** (terminal A ; minimums et zones mortes à 0) :
   `ros2 run g1_bridge pont --ros-args -p exiger_reperage:=false -p vitesse_min_lin:=0.0 -p vitesse_min_rot:=0.0 -p zone_morte_lin:=0.0 -p zone_morte_rot:=0.0`.
   Terminal B : `ros2 topic echo /pont/etat --field data` (état `pret`, `mode_robot`).
   Dans le terminal C, chaque mesure ci-dessous est `python3 -m g1_bridge.mesure` suivi de ce qui
   est écrit (par exemple `python3 -m g1_bridge.mesure marche --vx 0.12 --duree 3`).
2. **Seuil de marche**, en notant « vitesse atteinte » : `marche --vx 0.12 --duree 3`,
   puis `--vx 0.15`, `--vx 0.18`, `--vx 0.2` ; **de côté** : `marche --vx 0 --vy 0.12 --duree 3`, puis
   `--vy 0.15`, `0.18`, `0.2` (et `--vy -0.15`, à droite) ; **en diagonale** (la règle de la norme) :
   `marche --vx 0.1 --vy 0.1` (norme 0,14) et `marche --vx 0.14 --vy 0.14` (norme 0,2).
3. **Seuil de rotation** : `rotation --wz 0.1 --duree 3`, puis `--wz 0.15`, `0.2`, `0.3`, `0.4`.
4. **Latence et arrêt à 0,2 m/s** : `marche --vx 0.2 --duree 3` : retard, montée, arrêt et
   dépassement (distance faite après le dernier ordre).
5. **Le pont avec ses défauts** : terminal A, `ros2 run g1_bridge pont --ros-args -p exiger_reperage:=false` ;
   `marche --vx 0.1 --duree 3` : « 7105 envoyé par le pont : (0.2, 0.0, 0.0) » et le robot marche.
6. **Rotation finale du guide** (navigation lancée, robot repéré, 1 m libre autour) : terminal C,
   `cap --pendant 20 --angle 90`, puis tout de suite, terminal D :
   `ros2 action send_goal /spin nav2_msgs/action/Spin "{target_yaw: 1.5708, time_allowance: {sec: 20}}"` ;
   aussi `-1.5708` et `0.5`. Le « dépassement par rapport à 90° » règle le guide, en marche :
   `ros2 param set /guide anticipation_rotation_rad <dépassement en rad>`, puis
   `ros2 param set /guide tolerance_orientation_rad <0,6 × le dépassement>` (défaut avec le pont :
   0,40 rad, voir `navigation.launch.py` ; valeurs en radians avec un point, par exemple `0.25` ;
   une valeur hors des bornes est refusée avec un message en français, essayé le 31/10).
   Vérification : `g1-guide aller accueil` (le point principal) ; à l'arrivée, avant le retour
   automatique, tournez le robot d'environ 90° à la télécommande ; au retour, le guide se tourne
   vers la flèche, et `ros2 topic echo /guide/etat --field data | grep --line-buffered "se tourne"`
   ne montre qu'une ligne (la fin, « de retour au point principal (… de la flèche) », dit l'écart).
   Sans Nav2, une estimation : le retard et la montée de l'étape 3 (`rotation --wz 0.3`) dans
   `python3 -m g1_nav.rotation_pont --constante <montée ÷ 2,2> --retard <retard − 0,3 × montée>`
   (le retard mesuré va jusqu'à la moitié de la vitesse), qui simule la chaîne (Spin, lisseur,
   pont, robot) et écrit les deux `ros2 param set` conseillés.

Les valeurs mesurées remplacent celles de `config/pont.yaml` et du contrat (`VITESSES_MIN_PONT`
d'`atelier.lieu.robot`, à l'assemblage) : un minimum un peu au-dessus du seuil mesuré.

## Tests

```bash
cd ~/robot-g1/ws/src/g1_bridge && python3 -m pytest test     # environ 1 min, sans robot ni Gazebo
```

`test_logique.py` (règles avec une horloge à la main, dont la vitesse minimale et le mode),
`test_requete.py` (format, SDK et C++, lecture 7001), `test_reglages.py` (`config/pont.yaml` =
valeurs du contrat ; `vitesse_effective`, `nom_mode` et `message_pas_en_marche` identiques à ceux
d'`atelier.lieu`), `test_noeud_pont.py` (le nœud en vrai, le test joue le robot : marche lente à
0,2 m/s, robot assis, rafale de réponses d'autres programmes). Les essais dans Gazebo, avec le
faux G1, sont dans `g1_jumeau` ; la recette de bout en bout : `tests_e2e/critere_34_pont_modes.sh`.
