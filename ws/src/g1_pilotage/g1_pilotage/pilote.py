"""
Nœud pilotage (exécutable pilote), section 11.5 du plan.

  ros2 run g1_pilotage pilote [--port 8010] [--hote 0.0.0.0] [--vitesse-max 0.2]
  (dans le conteneur du Jetson : lancé par docker/demarrer.sh avec G1_PILOTAGE=1 ;
   sur le PC, en simulation et en répétition : par l'Atelier, POST /api/pilotage/demarrer,
   ou par « g1-pilotage noeud »)

Variables : G1_PILOTAGE_PORT (8010), G1_PILOTAGE_JETON (jeton exigé dans l'en-tête X-Jeton ;
vide : seulement 127.0.0.1), G1_VITESSE_MAX (plafonds de la marche baissés). API : serveur.py et
LISEZMOI.md.

Sécurité : atelier.lieu.pilotage (interdits, confirmations, limites), logique.py (verrou, homme
mort, danses, chorégraphies, ARRÊT). À la sortie (Ctrl+C, SIGTERM) : la chorégraphie s'arrête
(poids des bras ramené à 0 en 1 s), StopMove, et le guide reprend la main (/mouvement/maitre).
"""
import argparse
import os
import signal
import sys
import threading
import time

from .coeur import Coeur
from .logique import D, Maitre, Pilotage

TRADUCTIONS = [('usage:', 'usage :'), ('the following arguments are required:', 'il manque :'),
               ('unrecognized '
                'arguments:', 'arguments inconnus '
                              ':'), ('expected one argument', 'il faut une valeur'),
               ('invalid int value:', 'nombre entier attendu :'), ('error:', 'erreur :')]


class Analyseur(argparse.ArgumentParser):
    """ArgumentParser qui parle français."""

    def error(self, message):
        for anglais, francais in TRADUCTIONS:
            message = message.replace(anglais, francais)
        self.print_usage(sys.stderr)
        self.exit(2, f'pilote : {message}\n')


def analyseur():
    a = Analyseur(prog='pilote', description='Nœud pilotage du G1 : API HTTP et WebSocket vers '
                                             'les services '
                  'sport, arm et voice et rt/arm_sdk (section 11.5 du plan).', add_help=True)
    a.add_argument('--port', type=int,
                   default=int(os.environ.get('G1_PILOTAGE_PORT') or D.PORT_PILOTAGE),
                   help='port de l\'API (défaut $G1_PILOTAGE_PORT, sinon 8010)')
    a.add_argument('--hote', default=os.environ.get('G1_PILOTAGE_HOTE') or '0.0.0.0',
                   help='adresse d\'écoute (défaut 0.0.0.0 ; 127.0.0.1 : la machine seule)')
    a.add_argument('--vitesse-max', default=os.environ.get('G1_VITESSE_MAX') or None,
                   help='vitesse de marche maximale en m/s (plafonds baissés d\'autant ; défaut '
                        '0,4)')
    return a


def main(args=None):
    """Point d'entrée de ros2 run g1_pilotage pilote."""
    import rclpy
    from rclpy.executors import SingleThreadedExecutor
    from rclpy.signals import SignalHandlerOptions
    from rclpy.utilities import remove_ros_args
    from tornado import ioloop

    from .noeud import Boucle, creer_noeud, DESCENTE_MAX_S, PERIODE_S
    from .serveur import creer_application, ecouter

    argv = sys.argv if args is None else ['pilote', *args]
    options = analyseur().parse_args(remove_ros_args(argv)[1:])
    jeton = os.environ.get('G1_PILOTAGE_JETON', '')
    try:
        logique = Pilotage(vitesse_max=options.vitesse_max)
    except ValueError as erreur:
        print(f'pilote : réglage refusé : {erreur}', file=sys.stderr)
        return 1
    if not 0 < options.port < 65536:
        print(f'pilote : port {options.port} impossible', file=sys.stderr)
        return 2

    rclpy.init(args=argv, signal_handler_options=SignalHandlerOptions.NO)
    coeur = Coeur(logique)
    noeud = creer_noeud(coeur)
    coeur.publier = noeud.publier
    journal = noeud.get_logger()
    executeur = SingleThreadedExecutor()
    executeur.add_node(noeud)
    fil_ros = threading.Thread(target=executeur.spin, name='ros', daemon=True)
    fil_ros.start()
    boucle = Boucle(coeur, noeud).demarrer()
    coeur.publier([Maitre(dict(logique.maitre))])        # au démarrage, le guide a la main

    boucle_io = ioloop.IOLoop.current()
    try:
        serveur = ecouter(creer_application(coeur, jeton), options.port, options.hote)
    except OSError as erreur:
        print(f'pilote : le port {options.port} est pris ou interdit ({erreur}) : '
              'choisissez-en un autre (--port, G1_PILOTAGE_PORT)', file=sys.stderr)
        boucle.arreter()
        executeur.shutdown(timeout_sec=1.0)
        noeud.destroy_node()
        rclpy.try_shutdown()
        return 1

    def sortir(numero, _cadre):
        boucle_io.add_callback_from_signal(boucle_io.stop)

    signal.signal(signal.SIGINT, sortir)
    signal.signal(signal.SIGTERM, sortir)
    limites = logique.limites
    journal.info(f'pilotage prêt : http://{options.hote}:{options.port} (jeton '
                 f'{"exigé" if jeton else "absent : 127.0.0.1 seulement"}) ; marche plafonnée à '
                 f'{limites["vx"]:g} / {limites["vy"]:g} / {limites["wz"]:g} ; le guide a la main')
    try:
        boucle_io.start()
    finally:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        serveur.stop()
        # Chorégraphie en cours : le poids des bras redescend à 0 (1 s) avant de quitter
        with coeur.verrou:
            logique.arreter_bras()
        fin = time.monotonic() + DESCENTE_MAX_S
        while time.monotonic() < fin:
            with coeur.verrou:
                if not logique.bras_actifs():
                    break
            time.sleep(PERIODE_S)
        boucle.arreter()
        with coeur.verrou:
            coeur.publier(logique.quitter())
        journal.info('pilotage arrêté : StopMove envoyé, le guide a la main')
        try:
            from rclpy.duration import Duration
            for pub in list(noeud.pubs.values()) + [noeud.pub_maitre]:
                pub.wait_for_all_acked(Duration(seconds=ATTENTE_SORTIE_S))
        except Exception:       # noqa: B902 (selon le RMW, l'accusé peut manquer)
            pass
        executeur.shutdown(timeout_sec=1.0)
        fil_ros.join(timeout=2.0)
        noeud.destroy_node()
        rclpy.try_shutdown()
    return 0


ATTENTE_SORTIE_S = 0.5

if __name__ == '__main__':
    sys.exit(main())
