# Environnement du projet robot d'accueil G1, chargé par ~/.bashrc.
source /opt/ros/humble/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

# Messages et exemples Unitree pour ROS 2
source "$HOME/robot-g1/third_party/unitree_ros2/cyclonedds_ws/install/setup.bash"
source "$HOME/robot-g1/third_party/unitree_ros2/example/install/local_setup.bash"

# SDK C++ Unitree (installé sans sudo) et outils Python installés avec pip --user
export CMAKE_PREFIX_PATH="$HOME/robot-g1/opt/unitree_robotics${CMAKE_PREFIX_PATH:+:$CMAKE_PREFIX_PATH}"
export PATH="$HOME/.local/bin:$PATH"

# SDK Livox (LiDAR) et espace de travail du projet : pilote LiDAR, FAST-LIO2, puis vos paquets
export LD_LIBRARY_PATH="$HOME/robot-g1/opt/livox_sdk2/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
[ -f "$HOME/robot-g1/ws/install/local_setup.bash" ] && source "$HOME/robot-g1/ws/install/local_setup.bash"

# Commandes du projet : g1-sim, g1-sim-marche, g1-etat, g1-premiers-pas, g1-manette...
export PATH="$HOME/robot-g1/bin:$PATH"
