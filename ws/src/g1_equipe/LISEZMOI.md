# g1_equipe

Emplacements de l'équipe (vague 4, section 11.6 du plan) : le chatbot à règles (`dialogues.yaml`),
le relais des événements du guide vers `/robot/dire`, la personnalité active et un bouchon de la
caméra. Guide pour les coéquipiers : `docs/integration-equipe.md` (agent Équipe).

Squelette livré par l'intégrateur : le paquet se compile, son nœud `dialogue` n'est pas encore écrit.
Compilation, sans jamais toucher à `ws/build` :

```bash
cd ~/robot-g1/ws && colcon --log-base log_g1_equipe build --symlink-install --packages-select g1_equipe \
    --build-base build_g1_equipe --install-base install_g1_equipe
```
