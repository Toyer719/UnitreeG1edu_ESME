"""
Faux visiteur de la simulation (nœud faux_visiteur).

Squelette livré par l'intégrateur, à écrire par l'agent Comportement du guide.

Contrat (section 11.4 du plan) : conduit le piéton « pilote: externe » de la scène (le visiteur)
par /pietons/consigne (schéma pietons_consigne, mécanisme de l'agent Passants, section 11.3), en
lisant sa position sur /pietons/etat et celle du robot (vérité terrain : /odom en simulation,
/g1_jumeau/odom en répétition). Modes sur /faux_visiteur/mode (std_msgs/String) : suivre, trainer,
partir, arreter.

Tant qu'il n'est pas écrit, il ne publie rien et sort avec le code 1.
"""
import sys


def main(args=None):
    """Point d'entrée de ros2 run g1_nav faux_visiteur."""
    print('faux_visiteur : pas encore écrit (vague 4, agent Comportement du guide, section 11.4 '
          'du plan)', file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())
