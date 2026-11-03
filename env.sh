# ===== Unitree G1 / ROS 2 Humble / MuJoCo =====
# Ajouter à ~/.bashrc :  source ~/unitree/env.sh
export CYCLONEDDS_HOME=$HOME/unitree/cyclonedds/install
export CMAKE_PREFIX_PATH=/opt/unitree_robotics${CMAKE_PREFIX_PATH:+:$CMAKE_PREFIX_PATH}

# Environnement ROS 2 pour la simulation MuJoCo (interface lo, domain 1)
alias g1_sim_env='source $HOME/unitree/unitree_ros2/setup_local.sh; export ROS_DOMAIN_ID=0'

# Environnement ROS 2 pour le robot réel : g1_real_env <interface_ethernet>   (ex: g1_real_env enp3s0)
g1_real_env() {
  source /opt/ros/humble/setup.bash
  source $HOME/unitree/unitree_ros2/cyclonedds_ws/install/setup.bash
  export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
  export CYCLONEDDS_URI="<CycloneDDS><Domain><General><Interfaces><NetworkInterface name=\"$1\" priority=\"default\" multicast=\"default\" /></Interfaces></General></Domain></CycloneDDS>"
}

# Lance le simulateur C++ (robot défini dans unitree_mujoco/simulate/config.yaml → g1)
alias g1_mujoco='cd $HOME/unitree/unitree_mujoco/simulate/build && ./unitree_mujoco'

# Lance le simulateur version Python (même rôle que g1_mujoco)
alias g1_mujoco_py='cd $HOME/unitree/unitree_mujoco/simulate_python && python3 unitree_mujoco.py'

# Démo : politique de marche pré-entraînée du G1 dans MuJoCo (unitree_rl_gym, sim2sim)
alias g1_walk='(cd $HOME/unitree/unitree_rl_gym && PYTHONPATH=$HOME/unitree/unitree_rl_gym python3 deploy/deploy_mujoco/deploy_mujoco.py g1.yaml)'

# LE PROJET — escaliers (voir ~/unitree/unitree_rl_gym/ENTRAINEMENT_ESCALIERS.md)
# Test sans affichage de la politique escaliers sur l'escalier du décor Unitree
alias g1_stairs_eval='(cd $HOME/unitree/unitree_rl_gym && python3 deploy/deploy_mujoco/eval_stairs.py)'
# Visualisation MuJoCo de la politique escaliers dans le décor Unitree
alias g1_stairs_view='(cd $HOME/unitree/unitree_rl_gym && PYTHONPATH=$HOME/unitree/unitree_rl_gym python3 deploy/deploy_mujoco/deploy_mujoco.py g1_stairs.yaml)'

# LE PROJET — télécommande virtuelle (voir ~/unitree/virtual_remote/LISEZMOI.txt)
# 1) simulateur Python (seul à gérer la télécommande virtuelle)  2) télécommande  3) contrôleur de marche
alias g1_remote='python3 $HOME/unitree/virtual_remote/virtual_remote.py'
alias g1_deploy_sim='(cd $HOME/unitree/unitree_rl_gym/deploy/deploy_real && PYTHONPATH=$HOME/unitree/unitree_rl_gym python3 deploy_real.py lo g1_sim.yaml)'
