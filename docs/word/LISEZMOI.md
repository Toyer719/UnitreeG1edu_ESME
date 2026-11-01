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
