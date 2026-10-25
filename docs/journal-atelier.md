# Journal de l'Atelier G1

Décisions, écarts aux contrats et travail restant, par agent et par phase. Chaque agent ajoute sa section à la fin.
Le plan de référence est `docs/plan-atelier-multi-agents.md` ; ses contrats (section 4) font foi.

## Intégrateur (phase 0), 25/10/2026

- **Contrats figés** : schémas draft-07 dans `atelier/lieu/schemas/` (lieu, monde, salles, itineraires, zones, plus carte pour les `cartes/*.yaml`). Ajouts au plan : règles complémentaires (4.1), lancements ROS 2 (4.5), interface `Moteur` (4.6).
- **Décisions** : une salle a un nœud de même id ; identifiants `^[a-z0-9][a-z0-9_-]{0,39}$` ; un mur ne déborde pas de ses bouts, et un passage est l'écart entre deux murs alignés ; piéton `aller_retour: false` = boucle ; `--lieu demo` désigne `~/robot-g1/lieux/demo` (`atelier.chemin_lieu`, variable `ATELIER_LIEUX`) ; le masque Keepout a son `.yaml` (`cartes/<etage>_interdit.yaml`).
- **Attributions** : `bin/g1-atelier` à l'agent Interface ; `bin/g1-monde generer` et `simuler` à l'agent Monde ; `g1_nav/moteur_unitree.py` à l'agent Scan ; `lieux/demo` à l'agent Données. Les schémas et `moteurs.py` restent à l'intégrateur.
- **Lieu demo** : 30 × 20 m. Le couloir sud (y = 7) et le couloir nord (y = 13) sont reliés par le hall (accueil en 2,5 ; 10) et par la liaison est. Il compte 5 salles (vie_scolaire, infirmerie et cdi au sud ; amphi et b204 au nord), 13 nœuds en boucle (couloirs de 3 à 6,5 m), 18 murs, 9 objets, 2 piétons, une zone interdite (escalier) et une zone lente (hall).
- **Chemins** : accueil → b204 fait 21,5 m par le nord et 40,5 m par le sud. Pour tester le détour, bloquer le couloir nord entre amphi et couloir_nord_1, par exemple avec une boîte de 0,5 × 2,9 m centrée en (12 ; 13).
- **ROS 2** : `g1_sim` (ament_cmake) et `g1_nav` (ament_python) compilent, et `colcon test` passe. Leurs lancements sont provisoires : ils déclarent les arguments du contrat, les affichent et s'arrêtent.
- **pytest** : pytest 7.4.4 est installé dans `.venv-projet`, car le pytest 6.2.5 du système plantait au chargement du plugin anyio. Commande : `.venv-projet/bin/python -m pytest atelier/tests` (`pytest.ini` limite la recherche au paquet).
- **Copies de travail (worktrees)** : `atelier` est installé en mode éditable sur `~/robot-g1`. Dans une copie, lancez les commandes depuis sa racine (`python -m pytest`), ou faites `export PYTHONPATH=<copie>:$PYTHONPATH` (pour `ros2 launch`, par exemple) ; sinon, c'est le `atelier` de `~/robot-g1` qui est importé.
- **Tests** : `atelier/tests/test_contrats.py` (45 tests : schémas, erreurs refusées, cohérence et géométrie du demo) et `ws/src/g1_nav/test/test_moteurs.py` (9 tests) passent.
- **Reste à faire** :
  - le lieu demo n'a encore ni carte ni SDF : l'agent Monde les générera. En phase 1, les agents Navigation et Simulation fabriquent leurs fichiers de test dans un dossier temporaire, jamais dans `lieux/demo` ;
  - la licence des paquets ROS est à choisir (TODO dans `package.xml`) ;
  - l'encodage du masque des zones lentes est à fixer en phase 3.
