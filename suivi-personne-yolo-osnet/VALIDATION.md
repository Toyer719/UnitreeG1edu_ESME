# Validation de la copie autonome

Vérifications locales du 17 novembre 2026. Aucun dépôt distant créé ni push exécuté.

## Installation isolée

Installation CPU depuis zéro avec `installer.sh cpu`, dans un nouvel environnement
`.venv`, indépendant des environnements du robot. Les scripts suppriment les
variables Python héritées du setup ROS (`PYTHONPATH`, `PYTHONHOME`) pour éviter
des dépendances implicites. Le téléchargement officiel des deux modèles réussit
et leurs empreintes correspondent aux valeurs épinglées.

Environnement testé : Linux x86_64, glibc 2.35, Python 3.10.12.

| Dépendance | Version installée |
|---|---|
| PyTorch | 2.14.1+cpu |
| torchvision | 0.29.2+cpu |
| Ultralytics | 8.4.211 |
| NumPy | 2.2.6 |
| OpenCV | 4.14.0.94 |
| Pillow | 12.3.0 |
| lap | 0.5.14 |

`pip check` : aucune dépendance cassée dans cet environnement isolé.
Les autres dépendances que le cœur épinglé peuvent évoluer à une nouvelle installation.

## Fonctionnement

- Dix tests unitaires passent : mémoire de cible, imposteur sous ancien ID,
  retour avec nouvel ID, ambiguïté, taille mémoire, reconnexion, lecture vidéo,
  téléchargement vérifié et refus d'une empreinte incorrecte.
- Pipeline complet sur cinq images d'une vidéo synthétique : résolution réelle
  640×360, détection et suivi exécutés, sortie normale. Ce média ne contient
  aucune personne réelle ; il ne mesure pas la qualité de réidentification.
- Calcul OSNet sur une découpe synthétique : signature de 512 dimensions, normée.
- Fenêtre Tkinter de cette copie ouverte puis fermée automatiquement : affichage,
  clic sur une boîte et mémorisation de la cible validés avec une vidéo et des
  observations synthétiques. Aucun accès à une caméra réelle pour ce test.
- Construction d'une roue Python, installation dans un dossier séparé sous `/tmp`,
  puis import hors du dépôt : modèle OSNet et configuration BoT-SORT chargés depuis
  la roue. Les données nécessaires (YAML et licence du code tiers) sont présentes.

Le suivi avec personnes réelles et CUDA provient des essais précédents sur Rémi.
Cette copie autonome a été vérifiée sur CPU ; une installation CUDA neuve, Windows,
macOS et un second ordinateur physique n'ont pas été testés ici. La commande
`--diagnostic` permet de vérifier le nouvel environnement avant les essais.

## Contenu prévu pour Git

Code, configurations, scripts d'installation/lancement, tests, documentation,
licence AGPL et licence MIT d'OSNet. Les environnements, poids binaires, vidéos
et accès privés au robot sont exclus. Le dépôt est initialisé localement sur
`main`, sans commit ni dépôt distant ; il reste à faire le commit et le push.
