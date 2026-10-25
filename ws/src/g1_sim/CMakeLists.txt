cmake_minimum_required(VERSION 3.8)
project(g1_sim)

# Simulation Gazebo Fortress de l'Atelier G1 : pas de code compilé, seulement des fichiers
# installés dans share/g1_sim (modèle du robot proxy, mondes de test, réglages du pont, lancement).
find_package(ament_cmake REQUIRED)

install(DIRECTORY models worlds config launch
  DESTINATION share/${PROJECT_NAME})

if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  # Pas d'en-tête de copyright ni de code C++ dans ce paquet
  set(ament_cmake_copyright_FOUND TRUE)
  set(ament_cmake_cpplint_FOUND TRUE)
  ament_lint_auto_find_test_dependencies()

  # Tests pytest : rapides (sans Gazebo), puis simulations sans fenêtre (Gazebo, 20 à 40 s chacune)
  find_package(ament_cmake_pytest REQUIRED)
  ament_add_pytest_test(g1_sim_fichiers test/test_fichiers.py TIMEOUT 120)
  ament_add_pytest_test(g1_sim_simulation test/test_simulation.py TIMEOUT 300)
  ament_add_pytest_test(g1_sim_pietons test/test_pietons.py TIMEOUT 300)
  ament_add_pytest_test(g1_sim_demo test/test_demo.py TIMEOUT 300)
endif()

ament_package()
