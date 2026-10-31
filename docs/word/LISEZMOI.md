# Documents Word de l'Atelier G1

| Fichier | Contenu |
|---|---|
| `Seance2_A_faire.docx` | Séance robot n° 2 : ce qu'il faut faire (préparation, étapes, commandes, cases à cocher), avec l'avancement du projet |
| `Seance2_A_remplir.docx` | Séance robot n° 2 : feuille de résultats à remplir (constats, mesures des seuils, notes) |
| `Atelier_G1_documentation_logiciel.docx` | Document complet sur le logiciel : technologies, code, construction, nouvelle interface |

Version du 31/10/2026 au soir : écrite, mais **avant la relecture finale**. Il manque encore les
captures de la nouvelle interface dans le document du logiciel, les derniers chiffres de la recette
(N / 36), et le report dans la fiche « à faire » des dernières corrections du tutoriel
(`docs/tutoriel-seance-2.md`, commit da397bf : plafonds de l'étape M, précision E3, petits écarts).

Les documents sont produits par des scripts Python (python-docx) : `sources/`. Ils se régénèrent
depuis `~/robot-g1-donnees/vague5/documents/` (dossier de travail, avec le venv
`~/robot-g1-donnees/venv-docx`), par exemple :
`~/robot-g1-donnees/venv-docx/bin/python ~/robot-g1-donnees/vague5/documents/logiciel/generer.py`.
