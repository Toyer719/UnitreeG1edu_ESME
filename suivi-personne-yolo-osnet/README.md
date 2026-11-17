# Suivi de personne : YOLO11n + BoT-SORT + OSNet

Sélectionner une personne au clic, la suivre dans la vidéo, puis tenter de la
retrouver après une sortie du champ. Version autonome du suivi caméra testé
sur le robot Rémi (Unitree G1 EDU).

- **YOLO11n** détecte les personnes.
- **BoT-SORT** associe les détections entre les images.
- **OSNet x0.25 MSMT17** compare l'apparence du corps et des vêtements.
- Une **mémoire de cible** conserve les signatures indépendamment des numéros
  de piste. Un numéro peut changer sans que l'identité cible soit oubliée.

Aucune reconnaissance faciale, aucune commande moteur, aucun ROS ou SDK Unitree.
Le LiDAR expérimental n'est pas inclus. Les images et signatures restent en RAM ;
l'application n'enregistre pas de vidéo. Des associations erronées restent possibles,
notamment entre vêtements similaires, en cas de masquage ou de changement d'apparence.
Ce prototype n'est pas un système de commande de déplacement du robot.

## Installation sur un autre PC Ubuntu

Recommandé : Ubuntu 22.04/24.04, Python 3.10 à 3.13, session graphique pour la
fenêtre. Un GPU NVIDIA est recommandé pour la fluidité ; le CPU fonctionne aussi.

Installer les dépendances système si elles manquent :

```bash
sudo apt update
sudo apt install python3-venv python3-tk libgl1 libglib2.0-0
```

Après avoir cloné ce dépôt, ouvrir un terminal dans son dossier :

```bash
# PC avec carte NVIDIA et pilote fonctionnel :
bash installer.sh cuda

# OU installation CPU, sans carte NVIDIA :
bash installer.sh cpu
```

Le script crée `.venv/`, installe le package et télécharge environ 15 Mo de
modèles vérifiés par SHA256. PyTorch et les dépendances représentent un
téléchargement bien plus important. Aucun service payant ni compte n'est requis.
Les pilotes NVIDIA ne sont pas installés/modifiés par ce script.

La variante CUDA du script utilise les roues PyTorch `cu126`. Vérifier la
compatibilité du pilote avec la [documentation officielle PyTorch](https://pytorch.org/get-started/locally/).
Pour un autre CUDA, une autre architecture ou une installation manuelle, suivre
la section correspondante plus bas.

## Lancer avec une webcam branchée au PC

```bash
bash lancer.sh --source 0
```

Si la webcam est sur un autre index : `--source 1`. Sur Linux, un chemin stable
`/dev/v4l/by-id/...-video-index0` fonctionne aussi. Pour une e-con locale :

```bash
bash lancer.sh --source /dev/video0 --width 1280 --height 720 --fps 30 --fourcc YUYV
```

La résolution et la cadence demandées doivent être supportées par la caméra ;
le bandeau de la fenêtre affiche la résolution réellement reçue.

1. Cliquer dans le cadre du corps pour mémoriser la cible.
2. Se déplacer, sortir du champ et revenir sans recliquer.
3. Vérifier le libellé **CIBLE MÉMORISÉE**, pas seulement le numéro technique de piste.
4. Utiliser **Désélectionner la cible** pour effacer la mémoire ; fermer pour arrêter.

La mémoire est effacée à la fermeture. Si l'apparence est ambiguë, la fenêtre
l'indique et ne choisit pas de cible confirmée.

## Utiliser la caméra de Rémi depuis un autre PC

Sur le même réseau que le robot, avec son serveur caméra déjà actif :

```bash
bash lancer.sh --source http://192.168.0.105:18082/camera/usb.mjpg
```

L'adresse est un **exemple à adapter à l'IP actuelle de Rémi**. Aucune clé SSH
n'est nécessaire pour lire ce flux existant. Ce dépôt n'installe pas le serveur
caméra sur le robot et ne change pas sa configuration : il en consomme les images.
Pour la caméra de tête, remplacer `usb.mjpg` par `color.mjpg`.
L'application affiche la résolution fournie par ce serveur ; elle ne peut pas
transformer un flux 640×480 en acquisition 720p.

Les flux HTTP doivent fournir des images JPEG/MJPEG, avec ou sans Content-Length.
Un timeout entraîne une reconnexion automatique, sans oublier la cible.
Les images périmées sont masquées. L'âge affiché/mesuré commence à la réception
sur le PC : ce n'est pas une mesure du délai optique complet.

## Fichier vidéo et flux RTSP

```bash
bash lancer.sh --source exemple.mp4
bash lancer.sh --source rtsp://adresse-du-flux

# Sans fenêtre, pour vérifier le calcul sur 20 images :
bash lancer.sh --source exemple.mp4 --frames 20 --device cpu
```

Le test sans fenêtre affiche les IDs et le nombre de signatures calculées ;
il ne sélectionne pas automatiquement de personne. Le délai maximal se règle
avec `--timeout 120`. Une vidéo trop courte peut finir avant les 20 images,
car le lecteur conserve seulement l'image la plus récente pendant le chargement
initial des réseaux. Utiliser une vidéo plus longue ou un plus petit nombre.
Une caméra USB doit être libre : fermer les autres applications qui l'occupent.

## GPU et diagnostic

```bash
bash lancer.sh --diagnostic
bash lancer.sh --source 0 --device cuda:0  # exiger le GPU, erreur si indisponible
bash lancer.sh --source 0 --device cpu     # forcer le CPU
```

Sans option, CUDA est choisi s'il est accessible, sinon CPU. YOLO et OSNet
utilisent le même périphérique. La première image est plus lente à cause de
l'initialisation. Un environnement sandbox/conteneur peut masquer le GPU même
si le PC possède une carte : vérifier `nvidia-smi` et le diagnostic PyTorch dans
le même environnement que celui qui lance le suivi.

## Installation manuelle / Windows

Le code Python peut utiliser une webcam locale ou un flux, sans dépendance
spécifique au robot. Les scripts `.sh` visent Linux ; sous Windows, utiliser
Python avec Tkinter et les commandes équivalentes dans PowerShell :

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
# Installer torch et torchvision avec la commande adaptée du site PyTorch.
.venv\Scripts\python -m pip install -e .
.venv\Scripts\python -m suivi_personne.modeles
.venv\Scripts\python -m suivi_personne --source 0
```

Windows n'a pas été validé ici. Le chemin `--source /dev/videoN` et `--fourcc
YUYV` de l'exemple e-con sont propres à Linux. Sous macOS/Jetson, sélectionner
une installation PyTorch adaptée ; l'accélération MPS et l'installation Jetson
ne sont pas configurées par ce projet.

## Modèles et lancement hors ligne

Modèles stockés par défaut dans `~/.cache/suivi-personne/modeles/`, séparément
des sources Git. Pour les mettre dans un autre dossier :

```bash
.venv/bin/python -m suivi_personne.modeles --models-dir ./modeles
bash lancer.sh --models-dir ./modeles --source 0
```

On peut aussi définir `SUIVI_MODELS_DIR`. Après installation et téléchargement,
une webcam locale ou un fichier vidéo fonctionnent sans Internet. Un flux robot
nécessite seulement son réseau local. Les URLs publiques et empreintes sont
épinglées dans `suivi_personne/modeles.py` ; aucun téléchargement implicite de
modèle n'est effectué au lancement normal.

## Paramètres conservés

| Élément | Valeur |
|---|---|
| Détection | YOLO11n, personnes uniquement, `conf=0.1`, `imgsz=640` |
| BoT-SORT | `track_high_thresh=0.35`, `track_low_thresh=0.1`, `new_track_thresh=0.45` |
| Pistes perdues | `track_buffer=50` **images traitées**, pas secondes |
| Association BoT-SORT | `match_thresh=0.8`, `fuse_score=true` |
| Mouvement caméra | `sparseOptFlow` |
| Apparence BoT-SORT | `with_reid=true`, `model=auto`, proximité 0.25, apparence 0.8 |
| OSNet | x0.25 MSMT17, découpes RGB 128×256, normalisation ImageNet |
| Silhouette exploitable | confiance ≥0.20, largeur ≥16 px, hauteur ≥48 px ; bords acceptés |
| Maintien récent | même ID vu depuis moins de 1.2 s : similarité ≥0.60, marge ≥0.03 |
| Retour / nouvel ID | similarité ≥0.78, marge ≥0.07, trois confirmations consécutives |
| Galerie | ancre initiale fixe + 16 signatures maximum, en RAM |
| Enrichissement | similarité ≥0.88 et proximité de l'ancre ≥0.78, au plus tous les 0.7 s |
| Clic sans signature | attente jusqu'à 3 s sur la piste choisie |

Les similarités ne sont pas des probabilités. Ces seuils ont été réglés pour
les essais de Rémi, pas calibrés universellement. Deux personnes habillées de
façon proche peuvent être confondues. L'encodeur BoT-SORT `auto` utilise les
caractéristiques natives YOLO ; l'OSNet spécialisé est utilisé par la mémoire
de cible au-dessus de ce suivi local.

## Tests et paquet Python

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m pip check

# Facultatif : construire une roue installable, dans dist/ :
.venv/bin/python -m pip wheel . --no-deps --wheel-dir dist
```

Les tests couvrent la mémoire de cible, la reconnexion MJPEG, la lecture d'un
fichier et la vérification des téléchargements. Ils ne mesurent pas une précision
de réidentification sur un jeu annoté. Voir `VALIDATION.md` pour les essais réels
de cette copie autonome.

## Mettre ce dossier sur GitHub

Créer un dépôt vide sur GitHub, puis depuis **ce dossier uniquement** :

```bash
git init -b main
git add .
git commit -m "Ajout du suivi YOLO BoT-SORT OSNet"
git remote add origin URL_DE_TON_DEPOT
git push -u origin main
```

Le `.gitignore` exclut environnements, modèles, vidéos et secrets. Le dépôt
contient le code OSNet et sa licence, pas les poids binaires. Aucun dépôt GitHub
n'est créé ni publié automatiquement par les scripts.

## Licences

Application distribuée sous AGPL-3.0, code OSNet original sous MIT (texte conservé).
Voir [NOTICE.md](NOTICE.md), [LICENSE](LICENSE) et la provenance dans
[`suivi_personne/vendor/PROVENANCE.md`](suivi_personne/vendor/PROVENANCE.md).
