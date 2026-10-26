"""
Nœud pilotage (exécutable pilote).

Squelette livré par l'intégrateur, à écrire par l'agent Pilotage et danses.

Contrat (section 11.5 du plan) : petite API HTTP et WebSocket (tornado, port 8010,
G1_PILOTAGE_PORT, jeton G1_PILOTAGE_JETON dans l'en-tête X-Jeton) ; requêtes unitree_api sur
/api/sport/request, /api/arm/request, /api/voice/request ; /arm_sdk (unitree_hg/LowCmd) pour les
chorégraphies ; /mouvement/maitre (verrou des mouvements) et /pilotage/etat. Règles de sécurité :
atelier.lieu.pilotage (refus_commande, confirmation_requise, limites des bras et des pas).

Tant qu'il n'est pas écrit, il ne publie rien et sort avec le code 1.
"""
import sys


def main(args=None):
    """Point d'entrée de ros2 run g1_pilotage pilote."""
    print('pilote : le nœud pilotage n\'est pas encore écrit (vague 4, agent Pilotage et danses, '
          'section 11.5 du plan)', file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())
