# Documents Word de l'Atelier G1

| Fichier | Contenu | Pages |
|---|---|---|
| `Seance2_A_faire.docx` | Séance robot n° 2 : ce qu'il faut faire (préparation, étapes, commandes, cases à cocher), avec l'avancement du projet | 21 |
| `Seance2_A_remplir.docx` | Séance robot n° 2 : feuille de résultats à remplir (mêmes lignes que `docs/releves/seance-2.md`, mesures des seuils, notes) | 12 |
| `Atelier_G1_documentation_logiciel.docx` | Document complet sur le logiciel : technologies, code, construction, revue et recette de la vague 5, nouvelle interface avec ses captures | 64 |

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
grisé pendant le blocage, rien ne bouge au « Débloquer »). Le document du logiciel n'a pas été refait.

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
travail, avec le venv `~/robot-g1-donnees/venv-docx`) :

```bash
~/robot-g1-donnees/venv-docx/bin/python ~/robot-g1-donnees/vague5/documents/logiciel/generer.py --images
~/robot-g1-donnees/vague5/documents/fiches/rendu/rendre.sh
```
