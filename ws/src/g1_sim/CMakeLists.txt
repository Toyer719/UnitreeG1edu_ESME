cmake_minimum_required(VERSION 3.8)
project(g1_sim)

# Simulation Gazebo Fortress de l'Atelier G1 : pas de code compilé, seulement des fichiers
# installés dans share/g1_sim (modèles SDF, mondes de test, réglages du pont, lancements).
find_package(ament_cmake REQUIRED)

install(DIRECTORY models worlds config launch
  DESTINATION share/${PROJECT_NAME})

if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  # Pas d'en-tête de copyright ni de code C++ dans ce paquet
  set(ament_cmake_copyright_FOUND TRUE)
  set(ament_cmake_cpplint_FOUND TRUE)
  ament_lint_auto_find_test_dependencies()
endif()

ament_package()
