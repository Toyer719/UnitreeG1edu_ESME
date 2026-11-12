"""Répétition du mode robot sans robot, et petits outils ROS 2 du scan intégré (section 9.5 du plan).

Relais : la simulation se fait passer pour la cartographie du vrai G1. Les messages de Gazebo
sont republiés tels quels (octets sérialisés, sans les décoder), sous les noms des sujets du robot :

    /points → /unitree/slam_mapping/points      sensor_msgs/msg/PointCloud2
    /odom   → /unitree/slam_mapping/odom        nav_msgs/msg/Odometry

Avec le faux service slam_operate (g1-slam faux-service), g1-scan suit alors exactement le chemin
du mode robot : 1801, enregistrement des sujets /unitree/slam_mapping/*, 1802, traitement.

Attente : vérifie que des sujets sont publiés (un message reçu sur chacun), par exemple pour savoir
si la simulation tourne déjà.

    python -m atelier.scan.repetition relais [--paire /points=/unitree/slam_mapping/points ...]
    python -m atelier.scan.repetition attendre /odom /points [--delai 5]
Codes de sortie : 0 réussi, 1 échec, 2 commande mal tapée.
"""
import argparse
import signal
import sys
import time

# Sujets de la simulation → sujets de la cartographie du vrai robot (SUJETS_PAR_MODE de atelier.lieu)
PAIRES = (("/points", "/unitree/slam_mapping/points"), ("/odom", "/unitree/slam_mapping/odom"))
TYPES = {"/points": "sensor_msgs/msg/PointCloud2", "/odom": "nav_msgs/msg/Odometry"}


def _initialiser(nom):
    """rclpy sans ses propres gestionnaires de signaux (on s'arrête proprement nous-mêmes)."""
    import rclpy
    from rclpy.signals import SignalHandlerOptions
    rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
    return rclpy, rclpy.create_node(nom)


def _arret_sur_signal():
    arret = []
    signal.signal(signal.SIGINT, lambda *_: arret.append(1))
    signal.signal(signal.SIGTERM, lambda *_: arret.append(1))
    return arret


def _type_du_sujet(noeud, sujet):
    for nom, types in noeud.get_topic_names_and_types():
        if nom == sujet and types:
            return types[0]
    return None


def relais(args):
    from rclpy.qos import QoSProfile, ReliabilityPolicy, qos_profile_sensor_data
    from rosidl_runtime_py.utilities import get_message
    paires = [tuple(p.split("=", 1)) for p in args.paire] if args.paire else list(PAIRES)
    for paire in paires:
        if len(paire) != 2 or not all(s.startswith("/") for s in paire):
            print(f"Paire de sujets mal écrite : {'='.join(paire)} (attendu : /source=/destination)")
            return 2
    arret = _arret_sur_signal()
    rclpy, noeud = _initialiser("g1_scan_relais")
    comptes = {source: 0 for source, _ in paires}
    # Publication fiable : ros2 bag record s'abonne en fiable, et un abonné « au mieux » l'accepte aussi
    qos_sortie = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE)
    try:
        for source, destination in paires:
            type_ = TYPES.get(source)
            fin = time.monotonic() + 30.0
            while type_ is None and time.monotonic() < fin and not arret:
                rclpy.spin_once(noeud, timeout_sec=0.2)
                type_ = _type_du_sujet(noeud, source)
            if type_ is None:
                print(f"Relais impossible : {source} n'est pas publié (la simulation tourne-t-elle ?)", flush=True)
                return 1
            classe = get_message(type_)
            publication = noeud.create_publisher(classe, destination, qos_sortie)

            def rappel(octets, pub=publication, s=source):
                comptes[s] += 1
                pub.publish(octets)              # message inchangé (octets sérialisés)
            noeud.create_subscription(classe, source, rappel, qos_profile_sensor_data, raw=True)
            print(f"Relais : {source} → {destination} ({type_})", flush=True)
        print("Relais prêt.", flush=True)
        dernier = time.monotonic()
        while not arret and rclpy.ok():
            rclpy.spin_once(noeud, timeout_sec=0.2)
            if time.monotonic() - dernier > 30:
                dernier = time.monotonic()
                print("Relais : " + ", ".join(f"{s} {n} messages" for s, n in comptes.items()), flush=True)
    finally:
        print("Relais arrêté : " + ", ".join(f"{s} {n} messages" for s, n in comptes.items()), flush=True)
        noeud.destroy_node()
        rclpy.try_shutdown()
    return 0


def sujets_publies(noeud, rclpy, sujets, delai, arret=()):
    """Attend un message sur chacun des sujets, au plus delai secondes.
    Renvoie (manquants, premiers) : sujets sans message, et instant du premier message de chacun."""
    from rclpy.qos import qos_profile_sensor_data
    from rosidl_runtime_py.utilities import get_message
    debut = time.monotonic()
    fin = debut + delai
    premiers, abonnes = {}, set()
    while time.monotonic() < fin and len(premiers) < len(sujets) and not arret:
        for sujet in sujets:
            if sujet in abonnes:
                continue
            type_ = _type_du_sujet(noeud, sujet)
            if type_ is not None:
                noeud.create_subscription(get_message(type_), sujet,
                                          lambda _, s=sujet: premiers.setdefault(s, time.monotonic() - debut),
                                          qos_profile_sensor_data, raw=True)
                abonnes.add(sujet)
        rclpy.spin_once(noeud, timeout_sec=0.1)
    return [s for s in sujets if s not in premiers], premiers


def attendre(args):
    arret = _arret_sur_signal()
    rclpy, noeud = _initialiser("g1_scan_attente")
    try:
        manquants, premiers = sujets_publies(noeud, rclpy, args.sujets, args.delai, arret)
    finally:
        noeud.destroy_node()
        rclpy.try_shutdown()
    for sujet, t in premiers.items():
        print(f"{sujet} : premier message après {t:.1f} s")
    if manquants:
        print(f"Aucun message en {args.delai:g} s sur : {', '.join(manquants)}")
        return 1
    return 0


def principal(argv=None):
    p = argparse.ArgumentParser(prog="repetition", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sous = p.add_subparsers(dest="commande", required=True)
    s = sous.add_parser("relais", help="republier /points et /odom sous les noms du vrai robot")
    s.add_argument("--paire", action="append", metavar="/SOURCE=/DESTINATION",
                   help="autre paire de sujets (répétable ; défaut : /points et /odom)")
    s.set_defaults(fonction=relais)
    s = sous.add_parser("attendre", help="attendre un message sur chaque sujet")
    s.add_argument("sujets", nargs="+")
    s.add_argument("--delai", type=float, default=5.0)
    s.set_defaults(fonction=attendre)
    args = p.parse_args(argv)
    return args.fonction(args)


if __name__ == "__main__":
    sys.exit(principal())
