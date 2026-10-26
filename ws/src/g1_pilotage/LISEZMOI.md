# g1_pilotage

Pilotage du G1 depuis l'onglet **Pilotage** de l'Atelier (vague 4, section 11.5 du plan), dans le
conteneur du Jetson : postures, marche au joystick avec homme mort, gestes, voix, LED, danses du
robot, chorégraphies sûres et verrou des mouvements avec le guide.

Squelette livré par l'intégrateur : le paquet se compile, son nœud `pilote` n'est pas encore écrit
(agent Pilotage et danses). Compilation, sans jamais toucher à `ws/build` :

```bash
cd ~/robot-g1/ws && colcon --log-base log_g1_pilotage build --symlink-install --packages-select g1_pilotage \
    --build-base build_g1_pilotage --install-base install_g1_pilotage
```
