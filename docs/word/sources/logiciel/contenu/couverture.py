"""Couverture du document. [[cle]] : chiffre mesuré au moment de la génération (generer.chiffres)."""

COUVERTURE = {
    "surtitre": "Projet robot d'accueil · Unitree G1 EDU · du 21/10 au 18/12/2026",
    "titre": "Atelier G1",
    "sous_titre": "Le logiciel du robot d'accueil, de A à Z : comment il a été fait, ses technologies, son code",
    "resume": (
        "Ce document explique tout le logiciel du projet : ce qu'il fait, comment ses pièces se parlent, "
        "les technologies choisies et pourquoi, l'organisation du code et des fichiers, la sécurité, les "
        "tests, et la façon dont il a été construit, vague après vague, par une équipe d'agents IA "
        "coordonnée par Claude. Il sert de référence : on peut le lire d'un bout à l'autre, ou aller "
        "directement au chapitre utile."
    ),
    "fiche": [
        ["Projet", "Faire d'un robot humanoïde Unitree G1 EDU un robot d'accueil qui scanne un bâtiment, "
                   "connaît ses salles, y accompagne les visiteurs et contourne la foule."],
        ["Durée", "Deux mois, du 21/10 au 18/12/2026. Le 31/10, on est au jour 11 sur 59."],
        ["Logiciel", "« Atelier G1 », dépôt Git `~/robot-g1` : [[commits]] commits, le dernier ([[dernier_commit]]) "
                     "du [[date_commit]]."],
        ["État décrit", "Vagues 1 à 5 faites ; la vague 5 est en vérification finale. Avancement du projet "
                        "estimé à environ 50 % (section 1.4)."],
        ["Rédaction", "Claude (IA d'Anthropic), à partir du dépôt, du plan, du journal et du code lui-même ; "
                      "document généré le [[date]]."],
        ["Pour le regénérer", "`~/robot-g1-donnees/vague5/documents/logiciel/generer.py` (mode d'emploi dans "
                              "`NOTES.md`, dans le même dossier)."],
    ],
    "lecture_titre": "Comment lire ce document",
    "lecture": [
        "Pour comprendre vite : les chapitres 1 et 2, puis le chapitre 8, qui suit les données de bout en bout.",
        "- Pour apprendre ROS 2 à partir du projet : le chapitre 4.",
        "- Pour modifier quelque chose : le chapitre 13 (dix recettes), puis les annexes du chapitre 15.",
        "- Pour un mot inconnu : le glossaire (chapitre 14).",
        "- Dans le texte, `ce style` désigne un nom de fichier, une commande ou un sujet ROS à taper tel quel.",
    ],
}
