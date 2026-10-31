# Brancher sa partie sur le robot d'accueil : guide pour l'équipe

Ce document est pour vous si vous faites une de ces parties du robot d'accueil G1 :

- **la caméra** See3CAM_11CUG, qui voit les visiteurs ;
- **le chatbot à règles**, qui comprend ce que dit le visiteur et décide quoi répondre ;
- **les modes de personnalité**, qui changent la façon dont le robot parle et se comporte ;
- **la voix** (reconnaissance de la parole et synthèse), qui fait le lien avec le visiteur.

Il dit ce que votre partie reçoit et envoie, comment l'essayer sans robot, et les règles de sécurité à respecter. Il suppose que vous débutez en ROS 2 : les notions utiles sont rappelées au fur et à mesure.

Tout ce qui est décrit ici est déjà en place et testé sans robot (critères 30 et 35 de `tests_e2e/tout.sh`). Le chatbot fourni est un **exemple** : vous pouvez le garder, le modifier ou le remplacer par le vôtre. Depuis la vague 5, la **caméra** est faite aussi : le nœud `camera_usb` lit la See3CAM sur le robot, et `g1-visiteurs` trouve les visiteurs sur le PC (section 5). Seuls comptent les **fichiers du lieu** et les **sujets ROS 2** décrits plus bas : tant que votre programme les respecte, il se branche sur le reste sans rien changer ailleurs.

Références : sections 11.6 et 12.7 du plan (`docs/plan-atelier-multi-agents.md`), formats exacts dans `atelier/lieu/schemas/`.

---

## 1. Le robot en une image

```
 Visiteur ── parle ──► [reconnaissance vocale]  ── /visiteur/texte ──►  [chatbot]
                         (partie voix)                                    │  │
                                                    /robot/dire ◄─────────┘  └── /guide/aller ──► [guide]
 Visiteur ◄── entend ── [synthèse vocale] ◄──────── /robot/dire                                     │
                         (partie voix)       ▲                                                     │
                                             └──── [relais] ◄── /guide/evenement ◄─────────────────┤
                                                                                                   ▼
 Visiteur ── est vu ──► [See3CAM : camera_usb, sur le robot] ── /camera_poitrine/image/compressed ──┐   le robot
                                                                                                    │   marche
           Atelier (image en direct) ◄──┬── [g1-visiteurs, sur le PC : YOLO] ◄───────────────────────┘
           chatbot (salutation)     ◄───┴── /visiteurs/detectes
 [onglet Personnalités] ou [chatbot] ── /personnalite/active ──► voix, relais, chatbot
```

- Le **guide** (déjà écrit) emmène le robot vers une salle, en évitant les obstacles et les gens. C'est **lui seul** qui fait marcher le robot, avec la navigation Nav2 et le pont vers la marche d'Unitree.
- Le **nœud pilotage** (Réel › Piloter dans l'Atelier) commande les postures, les gestes des bras, la LED et les danses. C'est **lui seul** qui fait bouger les bras.
- Votre partie **demande** des choses (une salle où aller, une phrase à dire) ; elle ne commande jamais un moteur.

---

## 2. Avant de commencer

### Les commandes de base

Dans chaque terminal (déjà fait par `~/.bashrc` sur le PC du projet) :

```bash
source ~/robot-g1/setup/env.sh          # ROS 2 Humble, messages d'Unitree, paquets du projet
export ROS_DOMAIN_ID=42                 # votre numéro, de 1 à 100 : vos essais ne gênent pas ceux des autres
```

`ROS_DOMAIN_ID` sépare les essais : deux terminaux ne se voient que s'ils ont le même numéro. Sur le vrai robot, c'est 0. Prenez un numéro à vous pour les essais sur le PC, et mettez **le même** dans tous les terminaux d'un même essai (y compris celui de `g1-atelier`).

Le paquet de l'équipe, `g1_equipe`, se compile une fois (et après chaque nouveau fichier) :

```bash
cd ~/robot-g1/ws && colcon build --symlink-install --packages-select g1_equipe
source ~/robot-g1/ws/install/local_setup.bash
ros2 pkg executables g1_equipe          # camera_usb, dialogue, fausse_camera, voix_journal
```

### Trois notions de ROS 2

- Un **nœud** est un programme ROS 2 (ex. le chatbot). Il se lance avec `ros2 run paquet exécutable`.
- Un **sujet** (topic) est un canal nommé, comme `/robot/dire`. Un nœud **publie** des messages sur un sujet ; d'autres nœuds s'y **abonnent** et les reçoivent. Personne n'a besoin de savoir qui est à l'autre bout.
- Un **message** a un type. Ici, presque tout passe en `std_msgs/String` : un simple texte, qui contient du **JSON** (un dictionnaire Python écrit en texte). Le format de chaque JSON est fixé par un **schéma** dans `atelier/lieu/schemas/`, et se vérifie en Python :

```python
from atelier.lieu import valider_message
valider_message("robot_dire", {"texte": "Bonjour !"})      # [] : conforme ; sinon, la liste des erreurs en français
```

Écouter et publier à la main, pour voir ce qui passe :

```bash
ros2 topic list --no-daemon                                  # les sujets qui existent
ros2 topic echo --no-daemon /robot/dire                      # ce qui passe sur un sujet (Ctrl+C pour arrêter)
ros2 topic pub --once /visiteur/texte std_msgs/msg/String "{data: 'je cherche la salle b204'}"
```

(`--no-daemon` évite un piège connu : le démon `ros2` garde parfois un ancien `ROS_DOMAIN_ID`.)

### Le lieu

Toutes les informations d'un bâtiment sont dans un **dossier de lieu** : `~/robot-g1/lieux/<id>/`. Le lieu d'exemple est `demo` (un lycée imaginaire, avec les salles `accueil`, `vie_scolaire`, `infirmerie`, `cdi`, `amphi` et `b204`). **N'écrivez jamais dans `lieux/demo`** : c'est la référence des tests. Pour vos essais, faites une copie :

```bash
cp -r ~/robot-g1/lieux/demo ~/robot-g1/lieux/essai_equipe
```

et ouvrez-la dans l'Atelier (`g1-atelier`, puis le lieu « essai_equipe » en haut de la page).

---

## 3. Les trois fichiers de l'équipe

Ils sont **facultatifs** : un lieu s'en passe. Ils se modifient dans l'Atelier, ruban **Équipe** : **Personnalités**, **Dialogues** et **Caméra** (bouton « Partir de l'exemple » si le fichier n'existe pas encore). L'Atelier vérifie tout avant d'enregistrer, et dit en français ce qui ne va pas. On peut aussi les écrire à la main ; ils sont lus et vérifiés par `atelier.lieu.equipe` :

```python
from atelier.lieu import equipe
d = equipe.charger_equipe("essai_equipe", "dialogues")      # le contenu, ou None si le fichier n'existe pas
equipe.valider_equipe("dialogues", d)                        # [] si tout va bien
equipe.verifier_equipe("essai_equipe")                       # en plus : entre les fichiers (personnalité inconnue, motif inutile…)
equipe.enregistrer_equipe("essai_equipe", "dialogues", d)    # écrit le fichier, seulement s'il est valide
```

Les exemples complets sont dans `atelier/lieu/exemples/`.

### personnalites.yaml : les modes de personnalité

```yaml
version: 1
active: accueillant                 # une seule est active
personnalites:
  - id: accueillant                 # lettres minuscules sans accent, chiffres, _ et -
    nom: Accueillant
    description: Chaleureux et patient, pour l'accueil des visiteurs.
    salutation: "Bonjour ! Je suis le robot d'accueil du lycée. Où voulez-vous aller ?"
    voix: {nom: fr_FR-siwis-medium, vitesse: 1.0, hauteur: 1.0, volume: 80}   # nom : la voix choisie (facultatif) ; 1.0 = normal ; volume de 0 à 100
    led: {r: 0, g: 120, b: 255}     # couleur de la LED, de 0 à 255
    geste_salut: 26                 # geste des bras d'Unitree (26 : grand salut)
    vitesse_max: 0.3                # m/s, 0,4 au plus
    phrases:                        # remplacent les phrases du guide, par code d'événement
      depart: "Avec plaisir ! Suivez-moi jusqu'à {nom}."
      arrivee: "Et voilà : {nom}. Bonne journée !"
```

| Champ | Qui s'en sert | État |
|---|---|---|
| `salutation` | le chatbot d'exemple, quand la caméra voit un visiteur proche et que le robot attend à l'accueil | branché |
| `voix` (`nom`, `vitesse`, `hauteur`, `volume`) | la partie voix (elle reçoit ces réglages avec chaque phrase, et sur `/personnalite/active`) ; `nom` : la voix à prendre (ex. `fr_FR-siwis-medium` ou `fr_FR-tom-medium` de Piper) | à brancher par la partie voix |
| `phrases` | le relais des événements du guide (nœud `dialogue`) ; `{nom}` devient le nom de la salle | branché |
| `led` | le nœud pilotage, qui écoute `/personnalite/active` et met la couleur (service voice, 1010) | branché (à l'assemblage de la vague 4) |
| `geste_salut` | le nœud `dialogue` le demande sur `/robot/geste` quand il salue ; le nœud pilotage le fait seulement robot au repos (guide sans mission, pas piloté à la main, aucune danse), un toutes les 10 s au plus, puis relâche les bras | branché (à l'assemblage de la vague 4) |
| `vitesse_max` | le guide, qui seul règle la vitesse de marche : la plus petite des limites (personnalité, visiteur qui traîne) part sur `/speed_limit` | branché (à l'assemblage de la vague 4) |

Codes des phrases (textes par défaut dans `atelier/lieu/comportement.py`, `CODES_EVENEMENT`) : `depart`, `seul`, `ralentir`, `attente_visiteur`, `visiteur_retrouve`, `visiteur_perdu`, `passant_gene`, `passage_libre`, `detour`, `arrivee`, `retour`, `retour_arrive`, `perdu`, `retrouve`, `echec`, `arret`, `pilotage`. À l'arrivée, si la salle a sa propre phrase (`phrase_arrivee`, Placer › Salle), c'est elle qui est dite : elle est plus précise.

Dans l'onglet **Personnalités**, « Rendre active » écrit `active` dans le fichier et **annonce** la personnalité sur `/personnalite/active`.

### dialogues.yaml : le chatbot à règles

```yaml
version: 1
langue: fr
repli: "Je n'ai pas compris. Vous pouvez me dire par exemple : je cherche la salle B204."
regles:
  - id: chercher_salle
    motifs: ["je cherche {salle}", "ou est {salle}", "je vais {salle}", "emmene moi {salle}", "{salle}"]
    action: guider                  # guider, dire, personnalite, stop ou geste
    accompagner: true               # le robot surveille que le visiteur suit (ralentit, l'attend)
    reponse: "Je vous emmène à {nom_salle}. Suivez-moi !"
  - id: bonjour
    motifs: ["bonjour", "salut", "bonsoir"]
    action: dire
    reponse: "Bonjour ! Où voulez-vous aller ?"
  - id: discret
    motifs: ["sois discret", "mode discret"]
    action: personnalite
    personnalite: discret           # un id de personnalites.yaml
    reponse: "D'accord, je me fais discret."
  - id: stop
    motifs: ["stop", "arrete toi", "arrete"]
    action: stop
    reponse: "Je m'arrête."
  - id: coucou                      # action geste (assemblage de la vague 4)
    motifs: ["fais coucou", "dis au revoir"]
    action: geste
    geste: 25                       # geste des bras d'Unitree (Réel › Piloter, liste des gestes)
    reponse: "Au revoir !"
```

L'action `geste` répond, puis demande le geste sur `/robot/geste` (schéma `robot_geste`) : le nœud pilotage ne le fait que robot au repos (ni piloté à la main, ni en visite, ni pendant une danse), un toutes les 10 s au plus, et relâche les bras 5 s après.

Comment le chatbot d'exemple lit une phrase (`atelier/equipe/dialogue.py`) :

- majuscules, accents et ponctuation ne comptent pas : « Où est l'Accueil ? » se lit « ou est l accueil » ;
- `{salle}` vaut une salle du lieu : son identifiant, son nom ou un de ses autres noms (Placer › Salle), avec ou sans « la », « le », « au », « l' », « jusqu'à la »… devant ; une règle à `{salle}` ne marche que si une salle est trouvée ;
- `{*}` vaut n'importe quels mots (ou aucun) ;
- d'abord, la première règle dont un motif couvre **toute** la phrase ; sinon, la première dont un motif se trouve **dans** la phrase (« bonjour, je cherche le CDI merci » contient « je cherche {salle} ») ; sinon, le repli ;
- prudence : un motif fait seulement de `{salle}` ou de `{*}` n'est essayé que sur toute la phrase, et une phrase avec « ne », « pas » ou « jamais » ne fait partir le robot que si un motif la couvre en entier (« je ne cherche pas la B204 » ne le fait pas partir).

Dans la réponse d'une règle `guider`, `{nom_salle}` devient le nom de la salle et `{salle}` son identifiant. Dans l'onglet **Dialogues**, « Essayer » montre la réponse et l'action d'une phrase **sans rien faire bouger**, avec les règles de l'onglet, même pas encore enregistrées.

### camera.yaml : la caméra des visiteurs

```yaml
version: 1
camera:
  modele: See3CAM_11CUG
  peripherique: /dev/v4l/by-id/usb-e-con_Systems_See3CAM_11CUG_1A15C950-video-index0   # nom stable (ou /dev/videoN)
  largeur: 1280
  hauteur: 720
  ips: 30                            # images par seconde
  champ_horizontal_deg: 90.0         # dépend de l'objectif : fiche de l'objectif, ou mesure
  position: {x: 0.08, y: 0.0, z: 1.10, roulis: 0.0, tangage: -0.21, lacet: 0.0}
  # facultatifs (vague 5) : réglages du nœud camera_usb
  exposition: {mode: auto}           # auto (conseillé) ; manuelle : temps_100us (156 = 15,6 ms) et gain
  publication: {frequence_hz: 10, largeur: 640, qualite_jpeg: 70}
detection:
  actif: true
  modele: yolo11n-pose.pt            # fichier dans ~/robot-g1/modeles/
  confiance_min: 0.5
  distance_max_m: 4.0
  frequence_hz: 10
  # facultatifs (vague 5) : étalonnage des distances de g1-visiteurs
  taille_personne_m: 1.70
  correction_distance: 1.0
```

La **position** est celle de la caméra dans le repère du robot, `base_link` : x vers l'avant, y vers sa gauche, z vers le haut, en mètres, depuis le sol entre les pieds ; les angles en radians (l'onglet les montre en degrés). **Tangage positif = la caméra regarde vers le bas** (convention de ROS) : une caméra inclinée de 12° vers le haut a un tangage de −0,21 rad. Tout cela se mesure sur le robot, debout, au mètre ruban.

Le **périphérique** : sur le robot, le conteneur reçoit toujours la See3CAM sous le nom `/dev/g1_camera` ; le nom stable `/dev/v4l/by-id/…` (avec son numéro de série) sert à `g1-jetson demarrer` pour la retrouver sur le Jetson, quel que soit l'ordre des branchements. Un `/dev/videoN` ne sert que sur le PC.

L'onglet **Caméra** montre l'**image en direct** de la caméra, avec un cadre autour de chaque visiteur (vert : il regarde le robot ; orange : non), une vue de dessus et une vue de côté de ce que voit la caméra, où se dessinent en direct les visiteurs vus par la caméra (en vert) et les personnes vues par le LiDAR (en gris). On y trouve le « Préréglage See3CAM_11CUG » (1280 × 720 à 30 images par seconde, vérifié sur la caméra du PC avec `v4l2-ctl -d /dev/videoN --list-formats-ext` : YUYV en 1280 × 720 à 30, 1280 × 960 à 20, 640 × 480 à 60 ou 30), et, dans « Réglages avancés », l'exposition, les images publiées et l'étalonnage des distances.

---

## 4. Les sujets ROS 2 entre les parties

Tous sont des `std_msgs/String`, sauf les images de la caméra (`sensor_msgs/CompressedImage`, en fin de tableau). Sauf `/visiteur/texte` (texte brut), ils contiennent du JSON, au format du schéma indiqué.

| Sujet | Schéma | Qui publie → qui écoute | Ce que c'est |
|---|---|---|---|
| `/visiteur/texte` | texte brut | reconnaissance vocale → chatbot | ce que le visiteur a dit, en français |
| `/robot/dire` | `robot_dire` | chatbot, relais des événements, chorégraphies → **voix** | **la seule entrée de la voix** : la phrase à dire |
| `/guide/aller` | `demande_guide` | chatbot → guide | « emmène le visiteur à cette salle » |
| `/guide/stop` | `std_msgs/Empty` | chatbot (règle stop), Atelier → guide | arrêt immédiat, **toujours permis** |
| `/guide/evenement` | `evenement_guide` | guide → relais (nœud `dialogue`) | ce qui arrive pendant une visite (départ, arrivée, détour…) |
| `/guide/etat` | `etat_guide` | guide → tout le monde | où en est le guide (`attente`, `en_route`, `retour`, `arrive`…) |
| `/visiteurs/detectes` | `personnes` (`source: camera`) | **caméra** → chatbot, Atelier | les visiteurs vus par la See3CAM |
| `/personnalite/active` | `personnalite_active` | onglet Personnalités, chatbot → voix, relais, guide (`vitesse_max`), nœud pilotage (`led`) | la personnalité active (QoS spéciale, ci-dessous) |
| `/robot/geste` | `robot_geste` | chatbot (règle `geste`, `geste_salut` en saluant) → nœud pilotage | un geste des bras, fait seulement robot au repos |
| `/mouvement/maitre` | `maitre_mouvement` | nœud pilotage → guide, chatbot | qui commande les mouvements : `guide` ou `pilotage` |
| `/camera_poitrine/etat` | `etat_camera` | nœud `camera_usb` → Atelier | l'état de la caméra, 1 fois par seconde : ouverte, images lues et publiées, erreur en français |
| `/camera_poitrine/image/compressed` | `sensor_msgs/CompressedImage` (JPEG) | nœud `camera_usb` → `g1-visiteurs`, Atelier | l'image de la See3CAM, 10 fois par seconde, 640 × 360, qualité 70 ; QoS des capteurs (au mieux) |
| `/visiteurs/image/compressed` | `sensor_msgs/CompressedImage` (JPEG) | `g1-visiteurs --image` → Atelier | la même image avec les cadres et les distances dessinés, 3 fois par seconde |

### Les messages, un par un

`/robot/dire` (publié par le chatbot) :

```json
{"version": 1, "texte": "Je vous emmène à Salle B204. Suivez-moi !", "source": "dialogue",
 "priorite": "normale", "langue": "fr", "temps": "2026-10-26T10:00:00+01:00",
 "personnalite": "accueillant", "voix": {"vitesse": 1.0, "hauteur": 1.0, "volume": 80}}
```

Seul `texte` est obligatoire. `source` : `guide`, `dialogue`, `personnalite`, `choregraphie`, `atelier` ou `autre`. `priorite: haute` doit **couper la phrase en cours** (c'est le cas de « Je m'arrête. »). Le relais ajoute `code` (le code de l'événement du guide).

`/guide/aller` (publié par le chatbot) :

```json
{"cible": "b204", "accompagner": true, "source": "dialogue"}
```

`cible` : l'identifiant d'une salle (ou d'un nœud des itinéraires), ou `principal` (le point principal, l'accueil). `accompagner` : le robot surveille que le visiteur suit. `retour` (facultatif) : `false` empêche le retour automatique à l'accueil après la visite.

`/visiteurs/detectes` (publié par `g1-visiteurs`, ou par votre propre détecteur) :

```json
{"version": 1, "source": "camera", "temps": 812.4,
 "image": {"largeur": 640, "hauteur": 360, "numero": 1234, "sujet": "/camera_poitrine/image/compressed"},
 "personnes": [{"id": 3, "x": 1.5, "y": 0.2, "distance_m": 1.51, "angle_rad": 0.13, "confiance": 0.86,
                "regarde_robot": true, "boite": [250.0, 40.0, 330.0, 350.0]}]}
```

Positions dans `base_link` (x vers l'avant, y vers la gauche), en mètres ; `angle_rad` depuis l'avant du robot ; `id` : le même tant que la personne est suivie (le suivi ByteTrack de YOLO le donne). `temps` : l'heure ROS de l'image, en secondes. `regarde_robot` (facultatif) : la personne fait face au robot. Vague 5, facultatifs : `boite`, le cadre de la personne dans l'image analysée, en pixels `[x_min, y_min, x_max, y_max]` (origine en haut à gauche), et `image`, la taille de cette image : l'Atelier s'en sert pour dessiner les cadres sur l'image en direct. `atelier.equipe.camera.message_visiteurs(temps, personnes, image)` fabrique ce message, distances et angles compris.

`/personnalite/active` (publié par l'onglet ou le chatbot) : la personnalité entière, telle que dans `personnalites.yaml`, plus `version`, `lieu` et `temps`. Ce sujet a une **QoS fiable et transient_local** : le dernier message est gardé, et un nœud qui démarre plus tard le reçoit quand même. Il faut la même QoS pour s'y abonner (sinon on ne reçoit rien). Si plusieurs messages arrivent, **gardez le plus récent** (champ `temps`).

### Écouter et publier en Python

Un nœud minimal qui écoute `/robot/dire` et `/personnalite/active`, et publie sur `/visiteur/texte` (à copier pour démarrer votre partie) :

```python
import json
import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String

VERROU = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                    durability=DurabilityPolicy.TRANSIENT_LOCAL)


class MaPartie(Node):
    def __init__(self):
        super().__init__('ma_partie')
        self.create_subscription(String, '/robot/dire', self.sur_dire, 10)
        self.create_subscription(String, '/personnalite/active', self.sur_personnalite, VERROU)
        self.pub_texte = self.create_publisher(String, '/visiteur/texte', 10)

    def sur_dire(self, msg):
        d = json.loads(msg.data)
        self.get_logger().info(f'à dire : {d["texte"]}')

    def sur_personnalite(self, msg):
        self.get_logger().info(f'personnalité : {json.loads(msg.data)["nom"]}')

    def visiteur_a_dit(self, texte):
        self.pub_texte.publish(String(data=texte))


def main():
    rclpy.init()
    rclpy.spin(MaPartie())


if __name__ == '__main__':
    main()
```

Lancez-le avec `python3 ma_partie.py` (le Python du système, celui de ROS 2), après `source ~/robot-g1/setup/env.sh`.

---

## 5. Brancher chaque partie

### La caméra See3CAM_11CUG

Elle est faite (vague 5, section 12.7 du plan) ; vous pouvez la régler, l'étalonner, ou remplacer `g1-visiteurs` par votre propre détecteur, tant qu'il publie `/visiteurs/detectes` au même format.

**Sur le robot**, la See3CAM est branchée sur un port **USB 3 (bleu)** du Jetson. `g1-jetson demarrer` la trouve (`/dev/v4l/by-id/…See3CAM…-video-index0`, ou le `peripherique` by-id de `camera.yaml`), la passe au conteneur sous le nom `/dev/g1_camera`, et le conteneur lance le nœud **`camera_usb`** (paquet `g1_equipe`) : capture YUYV en 1280 × 720 à 30 images par seconde avec `v4l2-ctl`, exposition automatique réglée au démarrage, JPEG de 640 × 360 publiés 10 fois par seconde sur `/camera_poitrine/image/compressed`, état sur `/camera_poitrine/etat`. Sans caméra branchée, le conteneur démarre quand même, sans elle (pas à pas : `docs/jetson.md`, « La caméra de poitrine »).

**Sur le PC**, **`g1-visiteurs`** lit cette image (par le câble), trouve les personnes avec YOLO pose et le suivi ByteTrack (sur la carte graphique), estime la distance de chacune (la See3CAM ne la mesure pas : par la taille de la personne dans l'image, ou celle du buste ou des épaules), la place dans `base_link` avec la position de `camera.yaml`, garde celles qui dépassent `confiance_min` et sont à moins de `distance_max_m`, puis publie `/visiteurs/detectes` à `frequence_hz` :

```bash
g1-visiteurs --lieu essai_equipe --image        # l'image du robot ; --image : l'image avec les cadres, pour l'Atelier
g1-visiteurs --lieu essai_equipe --fenetre      # la même chose, avec une fenêtre (touche q pour quitter)
```

**Essayer sur le PC, sans robot**, avec la See3CAM branchée sur le PC (ou une webcam) :

```bash
ros2 run g1_equipe camera_usb                                    # la See3CAM du PC (trouvée seule), comme sur le robot
ros2 run g1_equipe camera_usb --ros-args -p source:=mire         # sans caméra : une image de test
ros2 run g1_equipe camera_usb --ros-args -p source:=fichier -p fichier:=photo.jpg   # une photo, répétée
g1-visiteurs --lieu essai_equipe --image                         # dans un autre terminal (même ROS_DOMAIN_ID)
g1-visiteurs --source 2                                          # ou directement une caméra du PC (/dev/video2)
g1-visiteurs --source photo.jpg --une-fois --sans-ros            # les personnes d'une photo, en JSON
```

Puis dans l'Atelier, onglet **Caméra** (ou la vue **Caméra** en mode Réel) : l'image en direct et un cadre autour de chaque visiteur ; les points verts des vues de dessus et de côté doivent tomber au bon endroit autour du robot.

**Vérifier** : `ros2 topic hz /camera_poitrine/image/compressed` (environ 10), `ros2 topic echo --once /camera_poitrine/etat` (`ouverte: true`, `erreur: null`, `usb_mbps: 5000`), `ros2 topic echo --once /visiteurs/detectes`. L'Atelier montre aussi l'état (`GET /api/camera/etat`) et dit en clair ce qui manque quand il n'y a pas d'image.

**Régler** (onglet Caméra) : la position sur le robot (au mètre ruban, robot debout), le champ horizontal (une règle à 1 m, d'un bord à l'autre de l'image), puis l'**étalonnage des distances** : des repères au sol à 1, 2, 3 et 4 m, une personne debout sur chacun, et dans « Réglages avancés » la `correction_distance` = distance vraie ÷ distance affichée (en moyenne). La taille supposée d'une personne (`taille_personne_m`, 1,70 m) se règle au même endroit.

**Image noire** : la See3CAM démarre en exposition **manuelle** (15,6 ms) ; `camera_usb` la met en automatique (sauf `exposition: {mode: manuelle}`), mais un autre programme ne le fait pas : avant `g1-personnes --source 2`, tapez `v4l2-ctl -d /dev/video2 -c auto_exposure=0`.

En attendant la vraie caméra (par exemple en simulation), la **fausse caméra** publie le même message de visiteurs :

```bash
ros2 run g1_equipe fausse_camera --ros-args -p lieu:=essai_equipe              # une personne fixe à 1,5 m devant
ros2 topic pub --once /fausse_camera/mode std_msgs/msg/String "{data: 'fixe 2.0 0.5'}"   # ailleurs
ros2 topic pub --once /fausse_camera/mode std_msgs/msg/String "{data: 'pietons'}"        # les piétons de Gazebo
ros2 topic pub --once /fausse_camera/mode std_msgs/msg/String "{data: 'aucune'}"
```

Le mode `pietons` « voit » les piétons de la simulation qui sont dans le champ de la caméra, placée comme dans `camera.yaml`.

### Le chatbot

Le nœud d'exemple applique `dialogues.yaml` du lieu (ou les règles d'exemple s'il n'y en a pas) :

```bash
ros2 run g1_equipe dialogue --ros-args -p lieu:=essai_equipe -p etage:=rdc
```

Il écoute `/visiteur/texte`, publie la réponse sur `/robot/dire` et, pour une règle `guider`, la demande sur `/guide/aller`. Il relit les fichiers du lieu quand ils changent (inutile de le relancer après « Enregistrer » dans l'onglet). Il fait aussi deux choses de plus :

- il **relaie** les événements du guide (`/guide/evenement`) vers `/robot/dire`, avec les phrases de la personnalité active ; il tait le « départ » du guide quand il vient lui-même de dire « Je vous emmène… » ;
- il **salue** un visiteur que la caméra voit à moins de 1,5 m, tourné vers le robot, quand le guide attend à l'accueil (une fois par visiteur, pas plus d'une fois toutes les 30 s).

Paramètres : `repondre` (true), `relayer_evenements` (true), `saluer` (true), `distance_salut_m` (1.5), `delai_salut_s` (30), `remplacer_visite` (false), `taire_depart_s` (10), `relire_s` (2). Code : `ws/src/g1_equipe/g1_equipe/dialogue.py` (le nœud), `atelier/equipe/dialogue.py` (les règles, sans ROS), `atelier/equipe/relais.py` (relais et salutation).

Pour le **remplacer** par le vôtre (un autre algorithme, un modèle de langue…) : écoutez `/visiteur/texte`, publiez sur `/robot/dire` et `/guide/aller` aux formats ci-dessus, et respectez les règles de la section 7. Arrêtez alors le nœud d'exemple, ou lancez-le avec `-p repondre:=false` : il ne répond plus aux phrases, mais garde le relais des événements du guide et la salutation (si vous ne les refaites pas).

### Les personnalités

Le fichier se règle dans l'onglet **Personnalités**. La personnalité active est annoncée sur `/personnalite/active` par l'onglet (« Rendre active ») et par le chatbot (règle `personnalite`) ; au démarrage, le nœud `dialogue` annonce celle du fichier si personne ne l'a fait. Votre partie l'écoute (QoS transient_local) et applique ce qui la concerne : la voix et ses réglages, les phrases. Ce qui fait bouger ou allumer quelque chose (geste, LED) passe par le nœud pilotage, et la vitesse par le guide (section 7).

### La voix

La partie voix a **une seule entrée** : `/robot/dire`. Elle dit `texte`, avec les réglages `voix` du message (ou ceux de la personnalité active), coupe la phrase en cours pour une `priorite: haute`, et ne dit rien d'un message hors du schéma `robot_dire`. Dans l'autre sens, la reconnaissance vocale publie ce qu'elle a compris sur `/visiteur/texte`, en texte brut.

Ce qui existe déjà sur le PC : `g1-ecouter` (reconnaissance Vosk ou faster-whisper, hors ligne) et `g1-parler "texte"` (voix française Piper). En attendant votre nœud, la **voix du journal** écrit chaque phrase dans son journal, et peut la dire avec `g1-parler` :

```bash
ros2 run g1_equipe voix_journal                                   # écrit seulement
ros2 run g1_equipe voix_journal --ros-args -p commande:=g1-parler   # et dit les phrases sur le PC
```

La voix intégrée du G1 (service `voice`, TTS 1001) ne parle pas français : c'est pourquoi la voix de l'équipe passe par `/robot/dire`.

---

## 6. Essayer sans robot

Trois niveaux, du plus simple au plus complet. Aucun n'a besoin du robot ; aucun ne fait bouger un vrai moteur.

**1. Sans ROS** : onglet **Dialogues**, « Essayer » : la réponse, la règle et l'action d'une phrase s'affichent. Ou en Python :

```python
from atelier.lieu import charger_salles, equipe
from atelier.equipe.dialogue import Chatbot
bot = Chatbot(equipe.exemple_equipe("dialogues"), charger_salles("demo"))
bot.repondre("Je cherche la salle B204, s'il vous plaît")["guide"]   # {'cible': 'b204', 'accompagner': True, 'source': 'dialogue'}
```

**2. ROS 2, sans Gazebo** : quatre terminaux, le même `ROS_DOMAIN_ID` partout :

```bash
ros2 run g1_equipe dialogue --ros-args -p lieu:=essai_equipe          # terminal 1 : le chatbot
ros2 run g1_equipe voix_journal                                        # terminal 2 : la voix
ros2 topic echo --no-daemon /guide/aller                               # terminal 3 : ce qui irait au guide
ros2 topic pub --once /visiteur/texte std_msgs/msg/String "{data: 'je cherche la salle b204'}"   # terminal 4
```

Le terminal 2 écrit « Je vous emmène à Salle B204. Suivez-moi ! », le terminal 3 montre `{"cible": "b204", "accompagner": true, "source": "dialogue"}`.

**3. Simulation complète** : `g1-atelier`, onglet **Simulation**, « Lancer la simulation » sur votre copie du lieu ; puis, dans un terminal, le nœud `dialogue` sur le même lieu ; onglet **Dialogues**, tapez « je cherche la salle b204 » et « Envoyer au robot » : le robot simulé part vers la B204, et « Ce que le robot a dit » montre les phrases, y compris celles du guide en route. C'est ce que vérifie le critère 30 :

```bash
E2E_DOMAINE=42 ~/robot-g1/tests_e2e/tout.sh 30
```

**Les tests automatiques** de l'équipe (à relancer après toute modification) :

```bash
cd ~/robot-g1 && .venv-projet/bin/python -m pytest -q atelier/tests/test_equipe_*.py      # 30 s environ
cd ~/robot-g1 && .venv-projet/bin/python -m pytest -q atelier/tests/test_camera_*.py atelier/tests/test_visiteurs.py   # caméra, 1 min
cd ~/robot-g1/ws && colcon test --packages-select g1_equipe && colcon test-result --all    # nœuds ROS 2, 1 min
E2E_DOMAINE=42 ~/robot-g1/tests_e2e/tout.sh 35        # la caméra de bout en bout : fausse vidéo → Atelier → g1-visiteurs → Firefox
```

---

## 7. Les règles de sécurité

Le robot pèse 35 kg et marche au milieu des gens. Ces règles ne se discutent pas.

1. **Le guide et le pilotage gardent la main sur les mouvements.** Votre partie ne publie **jamais** sur `/cmd_vel`, `/api/sport/request`, `/api/arm/request`, `/arm_sdk`, `/pont/arret` ni `/mouvement/maitre`. Pour faire marcher le robot, elle **demande** au guide (`/guide/aller`), qui décide, plafonne la vitesse (0,4 m/s), évite les obstacles et s'arrête seul s'il le faut.
2. **L'arrêt est toujours permis** : `/guide/stop` peut être publié à tout moment, par n'importe qui. Une règle « stop » doit toujours exister dans le chatbot.
3. **Respectez le verrou** `/mouvement/maitre` : quand il vaut `pilotage`, quelqu'un pilote le robot à la main ; ne publiez pas `/guide/aller` (le guide refuserait de toute façon). Le chatbot d'exemple répond alors « Je suis piloté à la main pour le moment. ».
4. **Ne détournez pas une visite** : pendant une visite (`/guide/etat` en mission `visite`), le chatbot d'exemple ne lance pas de nouvelle visite ; il répond « Je guide déjà quelqu'un… ». Un retour à l'accueil, lui, peut être interrompu.
5. **Les gestes des bras et la LED** d'une personnalité passent par le nœud pilotage (son API, `ws/src/g1_pilotage/LISEZMOI.md`), jamais directement par le service `arm` : il sait si les bras sont déjà occupés (chorégraphie) et refuse ce qui est dangereux.
6. **Une négation ne fait pas partir le robot** : gardez cette prudence dans votre chatbot (« je ne cherche pas la B204 »). Dans le doute, répondez sans guider.
7. **Essayez d'abord sans robot** (section 6), puis sur le robot **au portique**, avec quelqu'un qui tient la télécommande : elle reste l'arrêt d'urgence. Jamais d'essai sur le vrai robot sans l'encadrant.
8. **Pas de mode debug**, pas de commande bas niveau des moteurs (`rt/lowcmd`) : ce projet n'en a jamais besoin.
9. **Ne modifiez pas `lieux/demo`** ni les fichiers des autres parties : travaillez sur une copie du lieu, et dans vos propres fichiers.

---

## 8. Où est le code

| Fichier | Contenu |
|---|---|
| `atelier/lieu/schemas/{personnalites,dialogues,camera}.schema.json` | les formats des trois fichiers |
| `atelier/lieu/schemas/{robot_dire,personnalite_active,personnes,demande_guide,evenement_guide}.schema.json` | les formats des messages |
| `atelier/lieu/exemples/` | les exemples des trois fichiers |
| `atelier/lieu/equipe.py` | lire, écrire, vérifier les fichiers ; fabriquer les messages (`message_robot_dire`, `message_personnalite_active`) |
| `atelier/equipe/dialogue.py`, `relais.py`, `camera.py` | le chatbot d'exemple, le relais et la salutation, la géométrie de la caméra (sans ROS) : des pixels aux mètres (`distance_personne`, `position_dans_base_link`, `regarde_robot`) |
| `atelier/equipe/images.py` | les dernières images reçues par l'Atelier, le flux MJPEG |
| `ws/src/g1_equipe/` | les nœuds `dialogue`, `fausse_camera`, `voix_journal` et `camera_usb` (`image_jpeg.py` : YUYV → JPEG, mire ; `peripherique.py`), et leurs tests |
| `outils/visiteurs.py`, `bin/g1-visiteurs` | YOLO pose et ByteTrack sur l'image de la caméra → `/visiteurs/detectes` |
| `atelier/serveur/routes/equipe.py`, `routes/camera.py` | l'API de l'Atelier pour l'équipe (`/api/lieux/{id}/personnalites`, `…/dialogues`, `…/camera`, `/api/equipe/*`) et la caméra (`/api/camera/image`, `…/flux`, `…/etat`) |
| `atelier/web/js/ecrans/{personnalites,dialogues,camera}.js`, `js/equipe/commun.js`, `js/camera/flux.js` | les trois onglets, et la vue de l'image en direct (page d'essai : `atelier/web/essais/camera.html`) |
| `atelier/tests/test_equipe_*.py`, `test_camera_*.py`, `test_visiteurs.py`, `tests_e2e/critere_30_equipe.sh`, `critere_35_camera.sh` | les tests |

---

## 9. Ce qu'il reste à faire ou à vérifier

**À faire par l'équipe** : la reconnaissance vocale branchée sur `/visiteur/texte` ; la voix branchée sur `/robot/dire` (avec les réglages de la personnalité et la priorité haute) ; les règles du chatbot pour votre bâtiment ; l'étalonnage de la caméra sur le robot (position, champ, distances).

**Fait à la vague 5** : la caméra de poitrine (nœud `camera_usb` dans le conteneur du Jetson, `g1-visiteurs` sur le PC, image en direct et cadres dans l'Atelier).

**Branché à l'assemblage de la vague 4** : `vitesse_max` d'une personnalité appliquée par le guide ; `led` et `geste_salut` appliqués par le nœud pilotage ; le champ `voix.nom` (choix de la voix) ; l'action `geste` des dialogues (`/robot/geste`) ; `g1-lieu valider` vérifie aussi les trois fichiers de l'équipe ; `atelier/equipe/` et `g1_equipe` sont dans l'image du Jetson (`ros2 run g1_equipe dialogue …` dans `g1-jetson shell`, non lancé d'office).

**À vérifier sur le robot** : la See3CAM sur un port USB 3 du Jetson (`g1-jetson verifier`), 10 images par seconde sur le PC (`ros2 topic hz`), l'exposition automatique en pleine lumière (l'essai sur le PC, la nuit, donnait une image noire), le champ de vision (le mode 640 × 480 montre-t-il tout le champ ?), sa position réelle dans `base_link` ; la distance estimée contre le mètre ruban (`correction_distance`) ; la salutation à 1,5 m ; où tournent le chatbot et la voix (Jetson ou PC) et la latence de bout en bout (parole → réponse → départ) ; le haut-parleur et le micro du robot dans un hall bruyant.
