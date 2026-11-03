# LE PROJET — Entraîner le G1 à monter les escaliers

Tâche ajoutée : **`g1_stairs`** (G1, 12 articulations des jambes, Isaac Gym + PPO).

| Fichier | Rôle |
|---|---|
| `legged_gym/envs/g1/g1_stairs_config.py` | Paramètres : terrain, commandes, récompenses, PPO |
| `legged_gym/envs/g1/g1_stairs_env.py` | Environnement : terrain en maillage, curriculum, mesure du terrain |
| `legged_gym/utils/stairs_terrain.py` | Génération des escaliers (marches de 3 à 20 cm, 20 à 35 cm de profondeur) |
| `legged_gym/envs/__init__.py` | Enregistrement de la tâche `g1_stairs` (1 ligne ajoutée) |
| `resources/robots/g1_description/scene_stairs.xml` | Décor Unitree pour MuJoCo, robot face à l'escalier |
| `deploy/deploy_mujoco/configs/g1_stairs.yaml` | Test visuel sim2sim dans ce décor |
| `deploy/deploy_mujoco/eval_stairs.py` | Test sans affichage : le robot monte-t-il l'escalier ? |

**Principe.** L'acteur (la politique déployée) reçoit les **mêmes 47 observations** que la
tâche `g1` d'origine : il est « aveugle » et compatible avec les scripts de déploiement
existants. Seul le critique (utilisé à l'entraînement) voit une carte de hauteur du terrain.
Le terrain devient plus difficile au fil de l'entraînement (curriculum sur 10 niveaux) :
le décor Unitree (marches de 15 cm × 20 cm) correspond à peu près au **niveau 7**.

Référence avant entraînement : la politique de marche fournie par Unitree (`motion.pt`)
tombe sur la première marche (`eval_stairs.py` → CHUTE à x = 1,24 m).

---

## 1. Copier le projet sur le PC NVIDIA

Sur ce PC :
```bash
cd ~/unitree
tar czf g1_stairs_pack.tar.gz --exclude=unitree_rl_gym/logs unitree_rl_gym
```
Copier `g1_stairs_pack.tar.gz` (clé USB, scp…) puis, sur le PC NVIDIA :
```bash
tar xzf g1_stairs_pack.tar.gz
```

## 2. Installation sur le PC NVIDIA (une seule fois)

Prérequis : Ubuntu 20.04 ou 22.04, GPU NVIDIA avec **≥ 12 Go de VRAM conseillés**
(RTX 3090 / 4090 / A5000…), pilote NVIDIA récent (`nvidia-smi` doit fonctionner).

```bash
# Python 3.8 (imposé par Isaac Gym)
conda create -n unitree-rl python=3.8 -y
conda activate unitree-rl
conda install pytorch==2.3.1 torchvision==0.18.1 torchaudio==2.3.1 pytorch-cuda=12.1 -c pytorch -c nvidia -y

# Isaac Gym Preview 4 : télécharger IsaacGym_Preview_4_Package.tar.gz sur
# https://developer.nvidia.com/isaac-gym (compte NVIDIA gratuit)
tar xzf IsaacGym_Preview_4_Package.tar.gz
cd isaacgym/python && pip install -e . && cd ../..

# rsl_rl, version 1.0.2 obligatoire
git clone https://github.com/leggedrobotics/rsl_rl.git
cd rsl_rl && git checkout v1.0.2 && pip install -e . && cd ..

# ce dépôt
cd unitree_rl_gym && pip install -e .
```
Si `numpy` pose problème (`np.float` / `np.int` introuvable) : `pip install "numpy<1.24"`.

Vérifier Isaac Gym : `python isaacgym/python/examples/1080_balls_of_solitude.py`.

## 3. Test rapide (5 minutes, avec affichage)

```bash
cd unitree_rl_gym
python legged_gym/scripts/train.py --task=g1_stairs --num_envs=64 --max_iterations=10
```
On doit voir des pyramides d'escaliers et des robots qui apparaissent dessus. Fermer la fenêtre.

## 4. Entraînement complet

```bash
python legged_gym/scripts/train.py --task=g1_stairs --headless
```
- 15 000 itérations, sauvegarde toutes les 500 itérations dans `logs/g1_stairs/<date>/model_XXXX.pt`.
- Durée : plusieurs heures (environ 4 à 10 h selon le GPU).
- Manque de mémoire GPU : ajouter `--num_envs=2048`.
- Reprendre après une interruption : ajouter `--resume` (repart du dernier run et du dernier modèle).

**Suivi** (dans un autre terminal) :
```bash
tensorboard --logdir logs/g1_stairs
```
Courbes à surveiller :
- `Episode/terrain_level` : doit monter régulièrement. Au-dessus de **6–7**, le robot gère les marches de 15 cm.
- `Train/mean_reward` : doit augmenter.
- `Episode/rew_tracking_lin_vel` : le robot suit-il la vitesse demandée ?

## 5. Visualiser et exporter la politique

```bash
python legged_gym/scripts/play.py --task=g1_stairs
```
Cette commande affiche les robots et **exporte** la politique dans
`logs/g1_stairs/exported/policies/policy_lstm_1.pt`.

## 6. Retour sur ce PC : test dans le décor Unitree (MuJoCo)

Copier `policy_lstm_1.pt` au **même chemin** dans `~/unitree/unitree_rl_gym/logs/g1_stairs/exported/policies/`, puis :
```bash
cd ~/unitree/unitree_rl_gym
python3 deploy/deploy_mujoco/eval_stairs.py                                   # verdict chiffré
python3 deploy/deploy_mujoco/deploy_mujoco.py g1_stairs.yaml                  # visuel
```
Succès : le bassin monte d'environ 150 cm sans chute (haut de l'escalier).
La commande de vitesse se règle dans `configs/g1_stairs.yaml` (`cmd_init`).

---

### Si ça ne marche pas du premier coup

Ce code n'a pas pu être exécuté dans Isaac Gym (pas de GPU NVIDIA sur le PC de préparation).
Le terrain, la scène MuJoCo et le script d'évaluation ont été testés ; l'environnement
Isaac Gym compile mais n'a pas encore tourné. Réglages possibles :
- `terrain_level` bloqué bas → baisser `step_height_range` ou `max_init_terrain_level`.
- Le robot traîne les pieds sur les marches → augmenter `feet_swing_height_target` (0.10 → 0.12).
- Le robot reste immobile → baisser `collision` et `stumble` (pénalités trop fortes au début).

### Avant le vrai robot

Toujours tester d'abord en MuJoCo (étape 6), puis sur le G1 **suspendu au portique/harnais**,
sur sol plat, avant le moindre escalier réel.
