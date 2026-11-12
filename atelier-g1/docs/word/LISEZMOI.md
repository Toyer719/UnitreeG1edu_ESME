# Documents Word de l'Atelier G1

| Fichier | Contenu | Pages |
|---|---|---|
| `Seance2_A_faire.docx` | Séance robot n° 2 : ce qu'il faut faire (préparation, étapes, commandes, cases à cocher), avec l'avancement du projet | 26 |
| `Seance2_A_remplir.docx` | Séance robot n° 2 : feuille de résultats à remplir (mêmes lignes que `docs/releves/seance-2.md`, mesures des seuils, voix, notes) | 14 |
| `Atelier_G1_documentation_logiciel.docx` | Document complet sur le logiciel : technologies, code, sécurité, construction, revues et recettes des vagues 5 et 6, interface (vague 5) et chapitre de la vague 6, avec leurs captures | 82 |

**Version de la vague 6, du 10/11/2026**, après la recette (42 / 42, 2 885 tests réussis, 0 échec) ; agent Documents :

- **la fiche « à faire »** suit `docs/tutoriel-seance-2.md` mis à jour le même jour : « Vérifier le robot » remplace les
  vérifications à la main (`g1-etat`, la liste de l'accueil, les services dans l'appli, le premier `g1-jetson verifier`)
  et démarre les services de cartographie (l'appli en secours) ; l'Atelier est lancé une seule fois, à l'étape A
  (`G1_VITESSE_MAX=0.2 G1_PILOTAGE_URL=http://192.168.123.164:8010 g1-atelier`, `--hote 0.0.0.0` en variante pour la
  borne sur un téléphone), et la séance de la boîte noire s'ouvre avec l'espace ; « Naviguer › Arrêter » garde tout seul
  le journal du conteneur (la commande à la main reste en secours ; seul le journal du pilotage, étape P, se garde à la
  main) ; nouvelle étape V en option (la voix à 20 %, puis de 10 en 10, enregistrée avant la démo ; la démo avec la
  borne, une visite, puis la pause sur ARRÊT) ; fin : « Terminer la séance », le rapport, `g1-seance liste` et
  `exporter` ; veille : 12 critères (37, 38, 40, 42 en plus) et la place libre ; dépannage, lexique et « à me
  rapporter » à jour ; l'avancement est recalculé (environ 55 %, jour 21 sur 59) ;
- **la feuille « à remplir »** a les lignes A1 à A3, P5, V1 (avec un tableau volume par volume), V2, Fin, Z1 et Z2,
  les heures de début des étapes et les services de cartographie démarrés par « Vérifier le robot » ;
- **le document du logiciel** a un chapitre 12 nouveau, « Diagnostic, boîte noire et démo d'accueil (vague 6) », avec
  3 schémas et les 8 captures de la recette (`~/robot-g1-donnees/vague6/captures/`) ; les anciens chapitres 12 à 15
  deviennent 13 à 16 ; tout le reste est mis à jour (chiffres, avancement, technologies, arborescence, pièces du code,
  sécurité, construction, tests et 42 critères, onze recettes, glossaire, annexes des commandes, routes, sujets,
  réglages, variables et ordres du robot) ; la table des matières tient sur deux pages ;
- les trois fichiers sont vérifiés par le validateur OOXML du skill docx (« All validations PASSED! ») ; les pages
  changées ont été relues dans le PDF de contrôle (mise en page corrigée : tableau de l'avancement, table des matières,
  schéma d'ensemble moins large, figures du chapitre 12 sans pages à moitié vides).

**Version finale de la vague 5, du 01/11/2026**, après la recette (36 / 36, 2 281 tests réussis, 0 échec) :

- le document du logiciel donne les chiffres finals (chapitres 10 et 12 : suites de tests et leurs durées,
  durée de chacun des 36 critères, commits 5bb9e95 → 31c4350), la revue (30 défauts, dont 4 graves : 28
  corrigés, 2 écartés avec leur raison) et la recette ; le chapitre 11 décrit l'interface d'après les 9
  captures finales (`~/robot-g1-donnees/vague5/captures/`), vérifiée dans le code ;
- la fiche « à faire » suit la version actuelle de `docs/tutoriel-seance-2.md` (plafonds de l'étape M, C4,
  Échap, journaux complets `seance-2_navigation.log`, `seance-2_pilotage.log` et `seance-2_conteneur.log`,
  E3 par `/reperage/etat`, « Correction des distances », groupe video en nombre, message de `carte-unitree`,
  `g1-jetson arreter` avant `docker rmi`) et ce que la recette a changé (durée de la répétition, image du
  Jetson à jour, avertissement de la salle « 3 » de `seance`, pastille « À repérer », couleurs des cadres de
  la caméra).

**Fiches de la séance 2 refaites le 01/11 au soir, après la correction du verrou** (section 12.15 du plan) :
à F3, « Débloquer » ne relance plus l'ancien trajet du guide ; la précaution de la touche Échap avant
« Débloquer » n'est plus utile et a été retirée ; F3 dit maintenant ce qu'on doit voir (trajet annulé, « Y aller »
grisé pendant le blocage, rien ne bouge au « Débloquer »). Le document du logiciel n'avait pas été refait (il l'est
ensuite, ci-dessous).

**Refaits dans la nuit du 01 au 02/11, après la relecture de la correction du verrou** (section 12.15 du plan) :

- la fiche « à faire » : la touche Échap envoie l'ARRÊT pendant l'attente du retour automatique, même avec un
  menu ouvert (règle d'or 5, F2) ; à C4, un pont relancé suit tout ordre frais ; à F3, il faut refaire
  « Y aller » après « Débloquer », et un robot qui repartirait seul arrête la séance ; à P3, le joystick tenu
  pendant une assise ou un amortissement ne relance pas le robot à la remise en marche ; la répétition de la
  veille dure environ 12 min (22 pages ; la feuille à remplir ne change pas : son fichier n'est pas recopié) ;
- le document du logiciel : chapitre 9 (la barrière « Aucune reprise seule », la correction du verrou et sa
  relecture, ce qui reste à surveiller), chapitre 10 (chronologie, la correction du verrou, un problème de
  plus) et annexe C (le guide et le pilotage écoutent le verrou) ; refait : 66 pages (64 avant), la table des
  matières tient toujours sur deux pages ;
- `docs/tutoriel-seance-2.md` a repris les précautions que la fiche avait en plus (ci-dessous) : la fiche et
  le tutoriel disent maintenant la même chose.

**Relus le 01/11 au soir** (relecture critique : chaque affirmation confrontée au dépôt, toutes les pages lues) :

- la fiche « à faire » ajoute des précautions au tutoriel, et dit de la suivre en cas d'écart : à C5,
  Ctrl+C de la marche de 10 s ; le journal gardé avant chaque arrêt du conteneur (`seance-2_relances.log` pour
  un arrêt en cours de route) ; au plan B, vérifier d'abord qu'aucun conteneur ne tourne (un seul pont), et le
  retour automatique annoncé ; la confirmation « Lancer sur le robot » ; le diagnostic de `g1-etat` ;
- le document du logiciel corrige la marge du critère 25 (limite de 300 s, pas 180), la procédure pour tout
  retirer du Jetson (`g1-jetson arreter` d'abord), ce qui n'est pas dans Git (`third_party/`, FAST-LIO2, pilote
  du LiDAR), les schémas du repérage et du pilotage, et le nombre de lignes de code (sans les générateurs de ces
  documents).

Le nombre de pages est celui du PDF de contrôle (LibreOffice, Lato à la place de Calibri) : dans Word, il peut
y en avoir une ou deux de moins. À l'ouverture du document du logiciel, Word propose de mettre à jour les
champs : répondre **Oui** (table des matières et numéros de page).

Les documents sont produits par des scripts Python (python-docx) : `sources/` (générateurs, contenu, schémas
Graphviz, polices et scripts du rendu de contrôle ; mode d'emploi et points incertains dans
`sources/logiciel/NOTES.md`). Ils se régénèrent depuis `~/robot-g1-donnees/vague5/documents/` (dossier de
travail, avec le venv `~/robot-g1-donnees/venv-docx` ; les captures sont lues dans `~/robot-g1-donnees/vague5/captures/`
et `~/robot-g1-donnees/vague6/captures/`) :

```bash
~/robot-g1-donnees/venv-docx/bin/python ~/robot-g1-donnees/vague5/documents/logiciel/generer.py --images
~/robot-g1-donnees/vague5/documents/fiches/rendu/rendre.sh
```
