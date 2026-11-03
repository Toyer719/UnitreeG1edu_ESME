# Unitree G1 EDU — ESME (« LE PROJET »)

Espace de travail pour le robot humanoïde **Unitree G1 EDU** : simulation MuJoCo,
télécommande virtuelle, apprentissage de la montée d'escaliers (Isaac Gym).

> Le dépôt se clone **dans `~/unitree`** : les scripts et raccourcis utilisent ce chemin.

## Contenu

| Chemin | Rôle |
|---|---|
| `virtual_remote/` | Télécommande virtuelle (tkinter) pour piloter le G1 simulé — mode d'emploi et journal des corrections : [`virtual_remote/LISEZMOI.txt`](virtual_remote/LISEZMOI.txt) |
| `patches/` | Nos modifications des dépôts Unitree (un patch par dépôt) + `BASES.txt` (commit Unitree d'origine) |
| `docs/` | [Entraînement escaliers](docs/ENTRAINEMENT_ESCALIERS.md) · [Instructions PC NVIDIA](docs/INSTRUCTIONS_PC_NVIDIA.txt) |
| `scripts/apply_patches.sh` | Sur un nouveau PC : clone les dépôts Unitree et applique les patchs |
| `scripts/export_patches.sh` | Avant un commit : régénère les patchs depuis les dépôts locaux |
| `env.sh` | Raccourcis (`g1_mujoco_py`, `g1_remote`, `g1_deploy_sim`, `g1_walk`, `g1_stairs_eval`…) |
| `install_system.sh` | Installation système : ROS 2 Humble, dépendances, `unitree_sdk2` |

Les dépôts Unitree (`unitree_rl_gym`, `unitree_mujoco`, `unitree_ros2`, `unitree_sdk2_python`,
`unitree_sdk2`, `unitree_ros`) et `cyclonedds` ne sont **pas** copiés ici : seules nos
modifications le sont, dans `patches/`.

### Ce que contiennent les patchs

- **unitree_rl_gym** : tâche `g1_stairs` (terrain d'escaliers + curriculum, critique avec carte
  de hauteur), scène MuJoCo `scene_stairs.xml` (décor Unitree), `eval_stairs.py`,
  `deploy_real/configs/g1_sim.yaml` (gains bras/taille ×2, **simulation uniquement**).
- **unitree_mujoco** (simulateur Python) : télécommande virtuelle, `lowstate.tick`,
  couple PD recalculé à chaque pas, pas de 2 ms, configuration G1.
- **unitree_ros2** : scripts `setup*.sh` pour ROS 2 Humble et le chemin `~/unitree`.
- **unitree_sdk2_python** : exemple G1 bas niveau compatible MuJoCo.

## Installer sur un nouveau PC (Ubuntu 22.04)

```bash
git clone https://github.com/Toyer719/UnitreeG1edu_ESME.git ~/unitree
bash ~/unitree/scripts/apply_patches.sh      # clone Unitree + applique les patchs
bash ~/unitree/install_system.sh             # ROS 2 Humble, dépendances, unitree_sdk2 (sudo)
echo 'source ~/unitree/env.sh' >> ~/.bashrc
```
Puis compiler `cyclonedds` et le simulateur C++, et installer les SDK Python
(`pip install -e` de `unitree_sdk2_python` et `unitree_rl_gym`), comme décrit dans leurs README.

## Lancer la simulation avec la télécommande

```bash
# T1
cd ~/unitree/unitree_mujoco/simulate_python && python3 unitree_mujoco.py
# T2
python3 ~/unitree/virtual_remote/virtual_remote.py
# T3
cd ~/unitree/unitree_rl_gym/deploy/deploy_real
PYTHONPATH=$HOME/unitree/unitree_rl_gym python3 deploy_real.py lo g1_sim.yaml
```
Séquence : F5 → F2 (START) → j (A) → dans MuJoCo, 8 (environ 15 fois) puis 9 → flèches.
Détails : [`virtual_remote/LISEZMOI.txt`](virtual_remote/LISEZMOI.txt).

## Enregistrer et publier ses modifications

```bash
bash ~/unitree/scripts/export_patches.sh
cd ~/unitree && git add -A && git commit -m "description" && git push
```

## Sécurité

- `g1_sim.yaml` et la télécommande virtuelle sont **réservés à la simulation**.
  Sur le vrai robot : `g1.yaml` et la vraie télécommande.
- Avant tout essai réel : robot suspendu au portique/harnais, sol plat.

## Crédits et licences

- Dépôts Unitree Robotics (BSD-3-Clause) : <https://github.com/unitreerobotics>. Les patchs
  modifient leur code et restent soumis à leur licence.
- Ergonomie de la télécommande inspirée du *Virtual Gamepad* d'EngineAI
  (`engineai_robotics_native_sdk/tools/virtual_gamepad`, GPL-3.0). Aucun code n'en a été copié.
