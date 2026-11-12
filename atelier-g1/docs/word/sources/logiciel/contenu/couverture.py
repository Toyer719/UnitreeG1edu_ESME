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
        ["Durée", "Deux mois, du 21/10 au 18/12/2026. Le 10/11, on est au jour 21 sur 59."],
        ["Logiciel", "« Atelier G1 », dépôt Git `~/robot-g1` : [[commits]] commits, le dernier ([[dernier_commit]]) "
                     "du [[date_commit]]."],
        ["État décrit", "Vagues 1 à 6 faites et vérifiées sans robot : à la recette de la vague 6, le 10/11, "
                        "42 critères sur 42 et 2 885 tests réussis, sans échec. Avancement du projet estimé à "
                        "environ 55 % (section 1.4) ; prochaine étape : la séance robot n° 2."],
        ["Rédaction", "Claude (IA d'Anthropic), à partir du dépôt, du plan, du journal et du code lui-même ; "
                      "document généré le [[date]]."],
        ["Pour le regénérer", "`~/robot-g1-donnees/vague5/documents/logiciel/generer.py` (mode d'emploi dans "
                              "`NOTES.md`, dans le même dossier)."],
    ],
    "lecture_titre": "Comment lire ce document",
    "lecture": [
        "Pour comprendre vite : les chapitres 1 et 2, puis le chapitre 8, qui suit les données de bout en bout.",
        "- Pour apprendre ROS 2 à partir du projet : le chapitre 4.",
        "- Pour la vague 6 (« Vérifier le robot », la boîte noire, la démo d'accueil, la borne, la voix) : le "
        "chapitre 12.",
        "- Pour modifier quelque chose : le chapitre 14 (onze recettes), puis les annexes du chapitre 16.",
        "- Pour un mot inconnu : le glossaire (chapitre 15).",
        "- Dans le texte, `ce style` désigne un nom de fichier, une commande ou un sujet ROS à taper tel quel.",
    ],
}
