# g1_sim : la simulation Gazebo d'un étage

```bash
ros2 launch g1_sim simulation.launch.py lieu:=DOSSIER etage:=ID sans_fenetre:=true|false \
    [monde:=FICHIER.sdf] [jumeau:=true|false] [pietons:=corps|acteurs]
```

Gazebo Fortress sur le monde de l'étage (`<lieu>/mondes/<etage>.sdf`), le robot proxy `g1_proxy` (taille du
G1, LiDAR à 1,245 m) posé à `depart_robot`, le pont `ros_gz_bridge` (`/cmd_vel`, `/odom`, `/tf`, `/clock`,
`/points`), `robot_state_publisher` (base_link → lidar). `jumeau:=true` : répétition du vrai robot avec le
faux G1 (`g1_jumeau`, section 10.4 du plan).

## Les piétons crédibles (vague 4, section 11.3 du plan)

`pietons:=corps` (le défaut) : chaque piéton du monde qui a un corps (`corps: true`, le défaut) devient dans
Gazebo un cylindre solide de `rayon_m` et 1,7 m de haut, que le LiDAR voit et que le robot ne traverse pas.
Le `.sdf` du lieu ne change pas : le monde simulé est écrit au lancement dans un dossier temporaire
(`atelier.monde.sdf.sdf_simulation`). Le nœud `pietons` (`scripts/pietons.py`, logique dans
`atelier.monde.foule`) conduit chaque corps 20 fois par seconde (plugin VelocityControl) sur son horaire
(trajet, pauses, départ, un seul parcours), avec sa réaction au robot :

| `reaction` | Quand le robot est à moins de `distance_reaction_m` bord à bord, devant lui (±60°) |
|---|---|
| `ecart` (défaut) | il ralentit à 0,5 m/s et s'écarte de 0,6 m au plus du côté opposé au robot, dans l'espace libre ; sinon il s'arrête ; si son écart ne laisse pas 0,15 m pour passer (robot arrêté droit devant), il n'avance plus tant que le robot est devant lui (8 s au plus) ; il revient sur son trajet 1 s après que le robot s'est éloigné |
| `arret` | il s'arrête, et repart 1 s après que le robot s'est éloigné |
| `aucune` | il ne voit pas le robot (scènes « pire cas ») |

Les corps ne se cognent pas entre eux (un bit de masque de collision chacun, 15 au plus), mais cognent le
robot, les murs et les objets. Un corps pèse 70 kg (le robot proxy 35 kg) : il pousse le robot plus qu'il
n'est poussé, puis revient sur son trajet. `pietons:=acteurs` : les `<actor>` de la vague 1, traversables,
sans nœud ; un piéton `corps: false` reste toujours un `<actor>`.

| Sujet | Type | Rôle |
|---|---|---|
| `/pietons/etat` | std_msgs/String (JSON, schéma `pietons_etat`), 10 Hz | positions et vitesses vraies (repère map), `etat`, `reaction`, `corps` ; en plus `temps_scene` |
| `/pietons/consigne` | std_msgs/String (JSON, schéma `pietons_consigne`) | vitesse d'un piéton `pilote: externe` (le faux visiteur), valable 0,5 s, 1,5 m/s au plus ; il s'arrête devant un mur |
| `/pietons/reinitialiser` | std_msgs/Empty | ajout : tous les piétons-corps reviennent à `trajet[0]` (service `set_pose` de Gazebo) et la scène repart de zéro (`g1-banc --scene`, avant chaque essai) ; les `<actor>` ne sont pas remis au début |
| `/pietons/corps/<id>/cmd_vel`, `/pietons/corps/<id>/odom` | Twist, Odometry | usage interne (pont `pont_pietons`) |

La position vraie du robot vient de `/odom` (ou `/g1_jumeau/odom` avec `jumeau:=true`). Le facteur temps réel
reste à 1,0 avec 5 piétons-corps (0,95 à 0,98 avec Nav2 et les autres essais de la machine).

## Le LiDAR du robot proxy

360 × 16 points (de −7° à +52°), 10 Hz, 0,1 à 40 m. Les rayons sont décalés d'un demi-degré (de −179,5° à
+179,5°) : le gpu_lidar de Fortress assemble quatre caméras, et un rayon pile sur une couture (±45°, ±135°)
rendait une distance fausse de 10 à 90 % (points fantômes au milieu des couloirs).

## Tests

`colcon test --packages-select g1_sim`, ou `python3 -m pytest test` (avec l'environnement ROS) :
`test_fichiers.py` sans Gazebo, `test_simulation.py`, `test_pietons.py` et `test_demo.py` avec Gazebo sans
fenêtre (environ 3 min en tout).
