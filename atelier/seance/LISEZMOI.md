# La boîte noire des séances avec le robot

Vague 6, décision B (section 13.3 du plan). Pendant chaque séance avec le robot (ou une répétition sans robot),
l'Atelier garde tout ce qu'il faut pour comprendre ce qui s'est passé, puis écrit un rapport en français.

## Ce qui se passe tout seul

- **Ouverture** : dès qu'on ouvre l'espace de travail en mode **Réel** (vrai robot ou « Répétition sans
  robot »), une séance s'ouvre. La barre d'outils montre le badge **● Enregistrement** (à partir de 1 600 px de
  large ; en dessous, un simple point rouge, avec son infobulle). Jamais en Simulation.
- **Pendant la séance** :
  - le journal des **actions** : chaque clic qui change quelque chose (ARRÊT, Bloquer, Débloquer, Y aller,
    Repérer, Lancer, postures, danses, scan, démo…), avec l'heure, le mode et la réponse de l'Atelier ;
  - un **enregistrement ROS 2 léger** (`bag/`) : guide, pont, repérage, requêtes au robot, odométrie (10 fois
    par seconde au plus), batterie, pilotage, démo, voix, journaux des nœuds ; **jamais** les nuages de points
    ni les images ni le son. Mesuré en répétition avec Nav2 : 2 % d'un cœur pendant un trajet, environ 2,6 Mo
    par minute (150 Mo par heure, surtout les quatre odométries à 10 Hz) ;
  - le **journal du serveur** et, à la fin, la fin des journaux des commandes lancées par l'Atelier ;
  - le **journal du conteneur du Jetson**, récupéré avant chaque arrêt de la navigation du robot, et à la fin ;
  - le **diagnostic du début** (« Vérifier le robot »), s'il est disponible.
- **Fin** : « Terminer la séance » (clic sur le badge, ou Naviguer › ⚙ › Terminer la séance), ou l'arrêt de
  l'Atelier. Le **rapport** s'écrit alors tout seul en moins d'une minute ; le lien « Rapport de séance »
  apparaît dans la barre d'outils.
- **Garde-fous** : l'enregistrement s'arrête proprement si le disque descend sous 2 Go libres ou si le bag
  dépasse 1 024 Mo (le badge devient orange : « Enregistrement coupé ») ; la séance continue (actions, rapport).
- **Plantage** : si l'Atelier s'arrête brutalement, l'enregistreur ferme son bag tout seul ; au démarrage
  suivant, la séance est marquée « interrompue » et son rapport est écrit. Aucune séance ne s'ouvre seule.

## Où sont les fichiers

`~/robot-g1/journaux/seances/<AAAA-MM-JJ_HHhMM>/` (variable `ATELIER_SEANCES` pour un autre dossier) :
`seance.json` (le manifeste), `actions.jsonl`, `bag/` (rosbag2, lisible par `ros2 bag info`),
`enregistrement.json` (l'état de l'enregistreur), `journaux/`, `lieu/` (la copie du lieu ouvert),
`diagnostic_debut.json`, et le rapport : `rapport.html`, `rapport.md`, `rapport.json`, `trajets.png`.

## La commande g1-seance

```bash
g1-seance liste                      # les séances, la plus récente d'abord
g1-seance rapport derniere           # (re)fait le rapport de la dernière séance
g1-seance exporter derniere          # un .zip de toute la séance, à donner à Claude (--sans-bag : plus petit)
g1-seance demarrer --mode repetition # ouvre la séance de l'Atelier qui tourne (aussi : arreter, etat)
g1-seance enregistrer --dossier D    # l'enregistreur seul, sans Atelier (Ctrl+C pour arrêter)
```

## Le rapport

En bref (durée, trajets, distance, arrêts d'urgence, anomalies, erreurs, batterie), **à regarder en premier**
(les anomalies détectées toutes seules : mouvement sans demande, robot qui ne répond plus, arrêts d'urgence,
séance interrompue, enregistrement coupé, erreurs du serveur, repérage perdu), la carte avec chaque trajet coloré
selon son résultat, le tableau des trajets (départ, but, résultat et cause, durée, distance, arrêts), le temps
dans chaque état du pont, les modes du robot, la précision du repérage, les erreurs, le diagnostic du début et la
chronologie complète.

## À vérifier à la séance 2

Le coût de l'enregistrement pendant une vraie navigation (le badge, `enregistrement.json` : `cpu_recent`), la
détection du « mouvement sans demande » avec l'odométrie du vrai robot (le robot debout qui oscille ne doit pas
la déclencher ; la télécommande est signalée en « attention »), et le journal du conteneur récupéré avant
« Arrêter ».
