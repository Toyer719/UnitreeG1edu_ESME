"""
Nœud dialogue (exécutable dialogue).

Squelette livré par l'intégrateur, à écrire par l'agent Équipe.

Contrat (section 11.6 du plan) : écoute /visiteur/texte (std_msgs/String, texte brut),
applique les règles de dialogues.yaml du lieu (la première qui correspond), publie la réponse
sur /robot/dire (schéma robot_dire) et, pour l'action guider, la demande sur /guide/aller
(JSON {cible, accompagner, source: "dialogue"}, schéma demande_guide) ; relaie /guide/evenement
vers /robot/dire avec les phrases de la personnalité active. Fichiers : atelier.lieu.equipe.

Tant qu'il n'est pas écrit, il ne publie rien et sort avec le code 1.
"""
import sys


def main(args=None):
    """Point d'entrée de ros2 run g1_equipe dialogue."""
    print('dialogue : le nœud dialogue n\'est pas encore écrit (vague 4, agent Équipe, '
          'section 11.6 du plan)', file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())
