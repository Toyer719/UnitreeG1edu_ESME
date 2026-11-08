"""
Nœud accueil : la démo d'accueil (vague 6, section 13.4 du plan), lancé par g1-accueil.

    ros2 run g1_accueil accueil --ros-args -p lieu:=demo [-p etage:=rdc]

Squelette livré par l'agent Contrats : il s'arrête tout de suite (code 1) en disant que la
démo n'est pas encore faite. Contrat du nœud écrit par l'agent Borne et orchestrateur :
  écoute   /guide/etat, /guide/evenement, /pont/etat, /pont/arret (fiable, transient_local),
           /mouvement/maitre (transient_local), /visiteurs/detectes, /personnes/lidar,
           /personnalite/active (transient_local), /accueil/choix, /accueil/commande ;
  publie   /guide/aller, /guide/stop, /robot/dire, /robot/geste, /accueil/etat (2 Hz et à chaque
           changement), /accueil/evenement ;
  paramètres : lieu (obligatoire), etage (défaut : celui du point principal), et ceux de
           atelier.lieu.accueil.REGLAGES_DEMO (défauts : demo.yaml du lieu).
"""
import sys

MESSAGE = ("Pas encore fait : le nœud accueil de la démo (vague 6, agent Borne et "
           'orchestrateur, section 13.4 du plan).')


def main(args=None):
    """Point d'entrée de ros2 run g1_accueil accueil (squelette)."""
    print(MESSAGE, file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())
