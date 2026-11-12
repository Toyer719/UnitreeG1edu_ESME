#!/usr/bin/env python3
"""Petits outils ROS 2 des tests de bout en bout (lancés par les critere_NN_*.sh).

  attendre-sujets /odom /points [--delai 30] [--frequence /points=5]
      attend un message sur chaque sujet ; code 0 si tous arrivent à temps
  etat-guide --attendre arrive [--suite bloque,detour,arrive] [--delai 180] [--cible b204]
      suit /guide/etat jusqu'à l'état voulu ; affiche les états vus
  position
      affiche la position lue sur /odom : x y theta
  pres-de --lieu L --salle ID [--max 0.3]
      code 0 si le robot (/odom) est à moins de --max mètres de la salle
  moteur-unitree --lieu L --de accueil --vers b204 | --parcours a,b,c [--delai 600]
      fait suivre l'itinéraire au robot par MoteurUnitree et le faux service slam_operate
  http GET|POST|PUT URL [JSON]     attendre-http URL [--delai 30]
      appels au serveur de l'Atelier
"""
import argparse
import json
import math
import sys
import threading
import time


def _noeud(nom):
    import rclpy
    from rclpy.executors import SingleThreadedExecutor
    rclpy.init()
    noeud = rclpy.create_node(nom)
    executeur = SingleThreadedExecutor()
    executeur.add_node(noeud)
    fil = threading.Thread(target=lambda: _tourner(executeur), daemon=True)
    fil.start()
    executeur.fil_atelier = fil
    return noeud, executeur


def _tourner(executeur):
    try:
        executeur.spin()
    except Exception:
        pass


def _fermer(noeud, executeur):
    """Arrête le fil qui fait tourner le nœud, puis le nœud, puis rclpy (dans cet ordre)."""
    import rclpy
    executeur.shutdown(timeout_sec=2.0)
    executeur.fil_atelier.join(timeout=2.0)
    noeud.destroy_node()
    rclpy.try_shutdown()


def _type_du_sujet(noeud, sujet, fin):
    while time.monotonic() < fin:
        for nom, types in noeud.get_topic_names_and_types():
            if nom == sujet and types:
                return types[0]
        time.sleep(0.2)
    return None


def attendre_sujets(args):
    from rclpy.qos import qos_profile_sensor_data
    from rosidl_runtime_py.utilities import get_message
    noeud, executeur = _noeud("e2e_attente")
    debut = time.monotonic()
    fin = debut + args.delai
    frequences = dict(f.split("=") for f in args.frequence)
    recus, premier = {s: 0 for s in args.sujets}, {}
    try:
        for sujet in args.sujets:
            type_ = _type_du_sujet(noeud, sujet, fin)
            if type_ is None:
                print(f"{sujet} : n'apparaît pas en {args.delai:g} s")
                return 1

            def rappel(_, s=sujet):
                recus[s] += 1
                premier.setdefault(s, time.monotonic())
            noeud.create_subscription(get_message(type_), sujet, rappel, qos_profile_sensor_data)
        while time.monotonic() < fin and len(premier) < len(args.sujets):
            time.sleep(0.05)
        manquants = [s for s in args.sujets if s not in premier]
        if manquants:
            print(f"aucun message en {args.delai:g} s sur : {', '.join(manquants)}")
            return 1
        for s in args.sujets:
            print(f"{s} : premier message après {premier[s] - debut:.1f} s")
        code = 0
        if frequences:
            avant = dict(recus)
            time.sleep(3.0)
            for s, minimum in frequences.items():
                f = (recus[s] - avant[s]) / 3.0
                print(f"{s} : {f:.1f} messages/s (minimum {minimum})")
                code |= int(f < float(minimum))
        return code
    finally:
        _fermer(noeud, executeur)


def etat_guide(args):
    from std_msgs.msg import String
    noeud, executeur = _noeud("e2e_guide")
    vus, dernier = [], {}

    def rappel(msg):
        try:
            etat = json.loads(msg.data)
        except ValueError:
            return
        dernier.update(etat)
        if not vus or vus[-1] != etat.get("etat"):
            vus.append(etat.get("etat"))
            print(f"  {time.strftime('%H:%M:%S')} guide : {msg.data}", flush=True)
    noeud.create_subscription(String, "/guide/etat", rappel, 10)
    try:
        if args.cible:
            editeur = noeud.create_publisher(String, "/guide/aller", 10)
            time.sleep(1.5)
            editeur.publish(String(data=args.cible))
            print(f"/guide/aller : {args.cible}")
        fin = time.monotonic() + args.delai
        while time.monotonic() < fin:
            if vus and vus[-1] == args.attendre and (not args.cible or dernier.get("cible") == args.cible):
                break
            if vus and vus[-1] == "echec" and args.attendre != "echec":
                break
            time.sleep(0.1)
        print(f"états vus : {' → '.join(str(v) for v in vus) or 'aucun'}")
        if not vus or vus[-1] != args.attendre:
            return 1
        suite = [s for s in args.suite.split(",") if s] if args.suite else []
        reste = iter(vus)
        if not all(any(v == s for v in reste) for s in suite):
            print(f"suite attendue dans l'ordre : {' → '.join(suite)}")
            return 1
        return 0
    finally:
        _fermer(noeud, executeur)


def _lire_odom(delai=10.0):
    from nav_msgs.msg import Odometry
    from rclpy.qos import qos_profile_sensor_data
    noeud, executeur = _noeud("e2e_position")
    recu = []
    noeud.create_subscription(Odometry, "/odom", recu.append, qos_profile_sensor_data)
    fin = time.monotonic() + delai
    while not recu and time.monotonic() < fin:
        time.sleep(0.05)
    _fermer(noeud, executeur)
    if not recu:
        return None
    p, q = recu[0].pose.pose.position, recu[0].pose.pose.orientation
    return p.x, p.y, math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))


def position(args):
    pose = _lire_odom()
    if pose is None:
        print("pas de /odom")
        return 1
    print(f"{pose[0]:.3f} {pose[1]:.3f} {pose[2]:.3f}")
    return 0


def pres_de(args):
    from atelier.lieu import charger_salles
    salle = next((s for s in charger_salles(args.lieu) if s.id == args.salle), None)
    if salle is None:
        print(f"salle inconnue : {args.salle}")
        return 1
    pose = _lire_odom()
    if pose is None:
        print("pas de /odom")
        return 1
    d = math.hypot(pose[0] - salle.pose.x, pose[1] - salle.pose.y)
    print(f"robot en ({pose[0]:.2f} ; {pose[1]:.2f}), salle {args.salle} en ({salle.pose.x:g} ; {salle.pose.y:g}) : "
          f"{d:.2f} m (maximum {args.max:g})")
    return 0 if d <= args.max else 1


def moteur_unitree(args):
    from g1_nav.moteur_unitree import MoteurUnitree
    from g1_nav.routeur import Routeur
    routeur = Routeur.depuis_lieu(args.lieu, args.etage)
    if args.parcours:
        itineraire = args.parcours.split(",")
    else:
        itineraire = routeur.itineraire(args.de, args.vers)
        if itineraire is None:
            print(f"pas d'itinéraire de {args.de} à {args.vers}")
            return 1
    poses = routeur.poses(itineraire, sauter_depart=True)
    print(f"itinéraire : {' → '.join(itineraire)} ({routeur.longueur(itineraire):.1f} m)", flush=True)
    noeud, executeur = _noeud("e2e_moteur_unitree")
    moteur = MoteurUnitree(noeud=noeud, faux=True)
    try:
        time.sleep(1.0)
        if not moteur.demarrer(poses):
            print("MoteurUnitree refuse le départ (1102 refusé)")
            return 1
        debut = time.monotonic()
        dernier_affichage = 0.0
        while time.monotonic() - debut < args.delai:
            etat = moteur.etat()
            if time.monotonic() - dernier_affichage > 10:
                dernier_affichage = time.monotonic()
                reste = etat["reste_m"]
                print(f"  {time.monotonic() - debut:5.0f} s : reste {reste if reste is None else round(reste, 1)} m, "
                      f"progresse {etat['progresse']}", flush=True)
            if etat["arrive"]:
                print(f"arrivé en {time.monotonic() - debut:.0f} s")
                return 0
            if etat["echec"]:
                print("échec du moteur")
                return 1
            time.sleep(0.2)
        print(f"pas arrivé en {args.delai:g} s")
        return 1
    finally:
        moteur.annuler()
        time.sleep(0.5)
        moteur.fermer()
        _fermer(noeud, executeur)


def http(args):
    """Appel HTTP en JSON ; affiche la réponse ; code 0 si 2xx."""
    import urllib.error
    import urllib.request
    corps = None if args.json is None else args.json.encode()
    requete = urllib.request.Request(args.url, data=corps, method=args.methode,
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(requete, timeout=args.delai) as r:
            texte, code = r.read().decode(errors="replace"), r.status
    except urllib.error.HTTPError as e:
        texte, code = e.read().decode(errors="replace"), e.code
    except OSError as e:
        print(f"{args.methode} {args.url} : {e}")
        return 1
    print(texte if len(texte) < 2000 else texte[:2000] + "...")
    return 0 if 200 <= code < 300 else 1


def attendre_http(args):
    import urllib.request
    fin = time.monotonic() + args.delai
    while time.monotonic() < fin:
        try:
            with urllib.request.urlopen(args.url, timeout=2) as r:
                if r.status == 200:
                    return 0
        except OSError:
            pass
        time.sleep(0.3)
    print(f"{args.url} ne répond pas en {args.delai:g} s")
    return 1


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sous = p.add_subparsers(dest="commande", required=True)
    s = sous.add_parser("attendre-sujets")
    s.add_argument("sujets", nargs="+")
    s.add_argument("--delai", type=float, default=30.0)
    s.add_argument("--frequence", action="append", default=[], metavar="SUJET=HZ")
    s.set_defaults(fonction=attendre_sujets)
    s = sous.add_parser("etat-guide")
    s.add_argument("--attendre", default="arrive")
    s.add_argument("--suite", default="")
    s.add_argument("--delai", type=float, default=180.0)
    s.add_argument("--cible", help="publie d'abord cette cible sur /guide/aller")
    s.set_defaults(fonction=etat_guide)
    s = sous.add_parser("position")
    s.set_defaults(fonction=position)
    s = sous.add_parser("pres-de")
    s.add_argument("--lieu", required=True)
    s.add_argument("--salle", required=True)
    s.add_argument("--max", type=float, default=0.3)
    s.set_defaults(fonction=pres_de)
    s = sous.add_parser("moteur-unitree")
    s.add_argument("--lieu", required=True)
    s.add_argument("--etage", default="rdc")
    s.add_argument("--de", default="accueil")
    s.add_argument("--vers", default="b204")
    s.add_argument("--parcours", help="suite de nœuds séparés par des virgules")
    s.add_argument("--delai", type=float, default=600.0)
    s.set_defaults(fonction=moteur_unitree)
    s = sous.add_parser("http")
    s.add_argument("methode", choices=["GET", "POST", "PUT", "DELETE"])
    s.add_argument("url")
    s.add_argument("json", nargs="?")
    s.add_argument("--delai", type=float, default=120.0)
    s.set_defaults(fonction=http)
    s = sous.add_parser("attendre-http")
    s.add_argument("url")
    s.add_argument("--delai", type=float, default=30.0)
    s.set_defaults(fonction=attendre_http)
    args = p.parse_args()
    sys.exit(args.fonction(args))


if __name__ == "__main__":
    main()
