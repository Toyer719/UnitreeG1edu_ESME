#!/usr/bin/env python3
"""Commandes du scan : g1-slam, g1-carte-3d, g1-carte-2d et g1-salle.

  g1-slam scan-debut | scan-fin --nom N | relocaliser | aller X Y [THETA] | pause | reprendre
          | arreter | etat | faux-service      [--faux]
  g1-carte-3d --lieu L --etage E --enregistrement DOSSIER
  g1-carte-2d --lieu L --etage E
  g1-salle ajouter NOM [--type salle|noeud] --lieu L

Lancé par les scripts de bin/ : python -m atelier.scan.commande slam|carte-3d|carte-2d|salle ...
Code de sortie : 0 si tout va bien, 1 en cas d'échec, 2 si la commande est mal tapée.
"""
import argparse
import signal
import sys
import time

# Messages d'argparse les plus courants, en français
TRADUCTIONS = [("the following arguments are required:", "il manque :"),
               ("invalid choice:", "choix inconnu :"), ("choose from", "possibles :"),
               ("unrecognized arguments:", "arguments inconnus :"), ("expected one argument", "il faut une valeur"),
               ("invalid float value:", "nombre attendu, pas"), ("invalid int value:", "entier attendu, pas"),
               ("expected 3 arguments", "il faut trois valeurs")]


class Analyseur(argparse.ArgumentParser):
    def error(self, message):
        for anglais, francais in TRADUCTIONS:
            message = message.replace(anglais, francais)
        self.print_usage(sys.stderr)
        self.exit(2, f"erreur : {message}\nAide : {self.prog} --help\n")


def _erreur_lieu(e):
    """Affiche une ErreurLieu (liste de messages) et renvoie 1."""
    print("Erreur dans le lieu :")
    for m in getattr(e, "erreurs", [str(e)]):
        print(f"  - {m}")
    return 1


# ================================================================ g1-slam

AIDE_SLAM = """Commandes du service slam_operate du G1 (scan 3D, repérage, navigation d'Unitree).

Avec le robot : source ~/robot-g1/setup/robot.sh, puis g1-slam ... (port eno2).
Sans robot : lancez le faux service dans un terminal (g1-slam faux-service), puis
g1-slam ... --faux dans un autre (interface lo, domaine $ROS_DOMAIN_ID).

Déroulé d'un scan : scan-debut, promenez le robot, scan-fin --nom rdc --lieu L.
Ensuite, à chaque démarrage : posez le robot au point de départ du scan, puis
relocaliser --lieu L. Enfin : aller X Y [THETA], pause, reprendre, arreter."""


def _client(args):
    from atelier.scan import slam_client as sc
    interface, domaine = sc.connexion(args.faux, args.interface)
    if interface == sc.INTERFACE_ROBOT and args.faux is False:
        print(f"Connexion au robot par {interface} (domaine {domaine})...")
    return sc.ClientSlam(interface, domaine, delai=3.0 if args.faux else sc.DELAI_APPEL)


def _afficher(args, api, reponse):
    from atelier.scan import slam_client as sc
    print(f"{api} ({sc.NOMS_API[api]}) : {'OK' if reponse.ok else 'échec'} - {reponse.message}")
    if reponse.texte and args.detail:
        print(f"  réponse brute : {reponse.texte}")
    if reponse.code in (3102, 3104):     # personne n'écoute, ou pas de réponse
        if args.faux:
            print("Le faux service tourne-t-il ? Lancez-le dans un autre terminal : g1-slam faux-service")
            print("(même valeur de ROS_DOMAIN_ID dans les deux terminaux)")
        else:
            print("Robot allumé, câble branché, source ~/robot-g1/setup/robot.sh fait ? Services unitree_slam "
                  "et lidar_driver activés dans l'appli ? Pour essayer sans robot : ajoutez --faux")
    return 0 if reponse.ok else 1


def _nom_carte_du_lieu(lieu):
    from atelier.lieu import charger_fiche
    fiche = charger_fiche(lieu)
    if not fiche.carte_unitree:
        raise ValueError(f"le lieu {fiche.dossier} n'a pas de carte_unitree dans lieu.yaml : "
                         "faites d'abord g1-slam scan-fin --nom N --lieu L")
    return fiche.carte_unitree


def slam_scan_debut(args):
    from atelier.scan import slam_client as sc
    client = _client(args)
    code = _afficher(args, sc.API_DEBUT_SCAN, client.debut_scan(args.type))
    if code == 0:
        print("Scan commencé : promenez le robot lentement dans tout l'étage, puis : "
              "g1-slam scan-fin --nom NOM --lieu L" + (" --faux" if args.faux else ""))
    return code


def slam_scan_fin(args):
    from atelier.scan import slam_client as sc
    try:
        sc.adresse_carte(args.nom)
    except ValueError as e:
        print(f"Nom de carte invalide : {e}")
        return 2
    client = _client(args)
    code = _afficher(args, sc.API_FIN_SCAN, client.fin_scan(args.nom))
    if code != 0:
        return code
    print(f"Carte enregistrée sur le robot : {sc.adresse_carte(args.nom)}")
    if args.lieu:
        from atelier.lieu import ErreurLieu, charger_fiche, enregistrer_fiche
        try:
            fiche = charger_fiche(args.lieu)
            fiche.carte_unitree = sc.nom_fichier_carte(args.nom)
            enregistrer_fiche(fiche)
        except ErreurLieu as e:
            return _erreur_lieu(e)
        print(f"Noté dans {fiche.dossier}/lieu.yaml : carte_unitree: {fiche.carte_unitree}")
    else:
        print("Conseil : ajoutez --lieu L pour noter cette carte dans lieu.yaml (carte_unitree).")
    return 0


def slam_relocaliser(args):
    from atelier.scan import slam_client as sc
    nom = args.nom
    if nom is None:
        if not args.lieu:
            print("Dites quelle carte utiliser : --nom N (carte du robot) ou --lieu L (sa carte_unitree)")
            return 2
        from atelier.lieu import ErreurLieu
        try:
            nom = _nom_carte_du_lieu(args.lieu)
        except ErreurLieu as e:
            return _erreur_lieu(e)
        except ValueError as e:
            print(f"Erreur : {e}")
            return 1
    client = _client(args)
    code = _afficher(args, sc.API_RELOCALISER, client.relocaliser(args.x, args.y, args.theta, nom))
    if code == 0:
        print(f"Robot repéré sur {sc.adresse_carte(nom)}, en ({args.x:g} ; {args.y:g}), cap {args.theta:g} rad.")
    return code


def slam_aller(args):
    from atelier.scan import slam_client as sc
    client = _client(args)
    debut = time.monotonic()
    reponse = client.aller(args.x, args.y, args.theta)
    code = _afficher(args, sc.API_ALLER, reponse)
    if code != 0 or not args.attendre:
        return code
    # Attendre l'arrivée : un is_arrived vrai de cette navigation (pas de la précédente)
    suivi = sc.SuiviArrivee(client, debut, (args.x, args.y))
    while time.monotonic() - debut < args.attendre:
        if suivi.arrive(client.pose()[0]):
            print(f"Arrivé en {time.monotonic() - debut:.1f} s.")
            return 0
        time.sleep(0.1)
    print(f"Pas d'arrivée annoncée (is_arrived sur slam_key_info) après {args.attendre:g} s.")
    return 1


def _slam_simple(api_attr, api):
    def commande(args):
        client = _client(args)
        return _afficher(args, api, getattr(client, api_attr)())
    return commande


def slam_etat(args):
    from atelier.scan import slam_client as sc
    client = _client(args)
    print(f"Écoute de slam_info et slam_key_info pendant {args.duree:g} s...")
    time.sleep(args.duree)
    texte, _, n = client.info()
    print(f"slam_info : {n} message(s)" + (f", dernier : {texte}" if texte else ""))
    pose, _ = client.pose()
    if pose:
        print(f"  position lue : x = {pose[0]:.2f} m, y = {pose[1]:.2f} m, cap = {pose[2]:.2f} rad")
    texte, _, n = client.info_cle()
    print(f"slam_key_info : {n} message(s)" + (f", dernier : {texte}" if texte else ""))
    if texte is not None:
        print(f"  is_arrived lu : {sc.lire_arrivee(texte)}")
    return 0


def slam_faux_service(args):
    from atelier.scan import slam_client as sc
    from atelier.scan.faux_slam import DeplacementGazebo, FauxSlam
    interface, domaine = sc.connexion(True)
    depart = tuple(args.depart) if args.depart else (0.0, 0.0, 0.0)
    if args.lieu and not args.depart:
        from atelier.lieu import ErreurLieu, charger_fiche, charger_monde
        try:
            try:
                depart = charger_monde(args.lieu, args.etage).depart_robot
                depart = (depart.x, depart.y, depart.theta)
            except ErreurLieu:
                accueil = charger_fiche(args.lieu).accueil
                depart = (accueil.x, accueil.y, accueil.theta)
        except ErreurLieu as e:
            return _erreur_lieu(e)
    sc.initialiser_dds(interface, domaine)
    deplacement = DeplacementGazebo() if args.gazebo else None
    faux = FauxSlam(depart=depart, vitesse=args.vitesse, relocalise=args.relocalise,
                    publication_cle=args.publication, deplacement=deplacement, bavard=True)
    faux.demarrer()
    # flush : quand la sortie va dans un tuyau (serveur de l'Atelier), le texte part tout de suite
    print(f"Faux service slam_operate prêt sur {interface}, domaine {domaine} "
          f"({'robot proxy de Gazebo' if args.gazebo else f'robot imaginaire en {depart}'}).", flush=True)
    if args.relocalise:
        print("Déjà repéré sur la carte faux.pcd : 1102 est accepté tout de suite.", flush=True)
    print("Dans un autre terminal : g1-slam scan-debut --faux ... Ctrl+C pour arrêter.", flush=True)
    arret = []
    signal.signal(signal.SIGTERM, lambda *_: arret.append(1))
    try:
        while not arret:
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    faux.fermer()
    print("Faux service arrêté.", flush=True)
    return 0


def principal_slam(argv):
    commun = argparse.ArgumentParser(add_help=False)
    commun.add_argument("--faux", action="store_true", default=argparse.SUPPRESS,
                        help="faux service sur lo (g1-slam faux-service), au lieu du robot")
    commun.add_argument("--interface", default=argparse.SUPPRESS,
                        help="interface réseau (défaut : eno2 pour le robot, lo avec --faux)")
    commun.add_argument("--detail", action="store_true", default=argparse.SUPPRESS,
                        help="affiche aussi la réponse brute du service")

    p = Analyseur(prog="g1-slam", description=AIDE_SLAM, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--faux", action="store_true", default=False, help=argparse.SUPPRESS)
    p.add_argument("--interface", default=None, help=argparse.SUPPRESS)
    p.add_argument("--detail", action="store_true", default=False, help=argparse.SUPPRESS)
    sous = p.add_subparsers(dest="commande", metavar="COMMANDE", parser_class=Analyseur)
    sous.required = True

    s = sous.add_parser("scan-debut", parents=[commun], help="1801 : commencer un scan 3D")
    s.add_argument("--type", default="indoor", choices=["indoor", "outdoor"], help="intérieur (défaut) ou extérieur")
    s.set_defaults(fonction=slam_scan_debut)

    s = sous.add_parser("scan-fin", parents=[commun], help="1802 : terminer le scan et enregistrer la carte")
    s.add_argument("--nom", required=True, help="nom de la carte sur le robot, ex. rdc (→ rdc.pcd)")
    s.add_argument("--lieu", help="lieu où noter cette carte (carte_unitree de lieu.yaml)")
    s.set_defaults(fonction=slam_scan_fin)

    s = sous.add_parser("relocaliser", parents=[commun], help="1804 : repérer le robot sur une carte enregistrée")
    s.add_argument("--nom", help="carte du robot (défaut : carte_unitree du lieu)")
    s.add_argument("--lieu", help="lieu dont on prend la carte_unitree")
    s.add_argument("--x", type=float, default=0.0, help="position du robot sur la carte (défaut : départ du scan)")
    s.add_argument("--y", type=float, default=0.0)
    s.add_argument("--theta", type=float, default=0.0, help="cap du robot, en radians")
    s.set_defaults(fonction=slam_relocaliser)

    s = sous.add_parser("aller", parents=[commun], help="1102 : aller en ligne droite à une position (moins de 8 m)")
    s.add_argument("x", type=float)
    s.add_argument("y", type=float)
    s.add_argument("theta", type=float, nargs="?", default=0.0, help="cap à l'arrivée, en radians (défaut 0)")
    s.add_argument("--attendre", type=float, default=0.0, metavar="S",
                   help="attendre l'arrivée (is_arrived) au plus S secondes")
    s.set_defaults(fonction=slam_aller)

    for nom, attribut, api, aide in (("pause", "pause", 1201, "1201 : mettre la navigation en pause"),
                                     ("reprendre", "reprendre", 1202, "1202 : reprendre la navigation"),
                                     ("arreter", "arreter", 1901, "1901 : arrêter le service")):
        s = sous.add_parser(nom, parents=[commun], help=aide)
        s.set_defaults(fonction=_slam_simple(attribut, api))

    s = sous.add_parser("etat", parents=[commun], help="écouter slam_info et slam_key_info quelques secondes")
    s.add_argument("--duree", type=float, default=3.0, metavar="S")
    s.set_defaults(fonction=slam_etat)

    s = sous.add_parser("faux-service", help="lancer le faux service slam_operate (sur lo), pour essayer sans robot")
    s.add_argument("--gazebo", action="store_true", help="piloter le robot proxy de Gazebo (/cmd_vel, /odom, /points)")
    s.add_argument("--relocalise", action="store_true", help="commencer déjà repéré (comme après 1804)")
    s.add_argument("--depart", type=float, nargs=3, metavar=("X", "Y", "THETA"), help="pose de départ du robot imaginaire")
    s.add_argument("--lieu", help="départ du robot : depart_robot du monde de ce lieu (sinon son accueil)")
    s.add_argument("--etage", default="rdc")
    s.add_argument("--vitesse", type=float, default=0.5, help="m/s (défaut 0,5)")
    s.add_argument("--publication", choices=["periodique", "evenement"], default="periodique",
                   help="slam_key_info à 2 Hz (défaut) ou seulement à l'arrivée")
    s.set_defaults(fonction=slam_faux_service)

    args = p.parse_args(argv)
    try:
        return args.fonction(args)
    except KeyboardInterrupt:
        return 1
    except RuntimeError as e:
        print(f"Erreur : {e}")
        return 1


# ================================================================ g1-carte-3d et g1-carte-2d

def principal_carte3d(argv):
    p = Analyseur(prog="g1-carte-3d",
                  description="Assemble un enregistrement (ros2 bag du nuage et de l'odométrie) en un nuage "
                              "3D .pcd réduit à une grille de 5 cm : cartes/<etage>.pcd du lieu.")
    p.add_argument("--lieu", required=True, help="dossier du lieu, ou id seul (ex. demo)")
    p.add_argument("--etage", required=True, help="id de l'étage, ex. rdc")
    p.add_argument("--enregistrement", required=True, metavar="DOSSIER", help="dossier du ros2 bag")
    p.add_argument("--nuage", help="sujet du nuage (défaut : /unitree/slam_mapping/points, sinon /points)")
    p.add_argument("--odom", help="sujet de l'odométrie (défaut : /unitree/slam_mapping/odom, sinon /odom)")
    p.add_argument("--grille", type=float, default=0.05, help="taille de la grille, en m (défaut 0,05)")
    p.add_argument("--capteur", type=float, nargs=3, metavar=("X", "Y", "Z"),
                   help="position du LiDAR sur le robot, si l'enregistrement n'a pas /tf_static "
                        "(défaut : -0,004 0 1,245, le robot proxy)")
    p.add_argument("--portee", type=float, default=20.0, help="ignore les points plus loin, en m (défaut 20)")
    p.add_argument("--sortie", help="fichier .pcd à écrire (défaut : cartes/<etage>.pcd du lieu)")
    args = p.parse_args(argv)

    from atelier.lieu import ErreurLieu, chemin_pcd, dossier_lieu
    from atelier.scan import carte3d
    try:
        dossier = dossier_lieu(args.lieu)
        if not (dossier / "lieu.yaml").is_file():
            print(f"Le lieu {dossier} n'existe pas (pas de lieu.yaml).")
            return 1
        sortie = args.sortie or chemin_pcd(args.lieu, args.etage)
        resultat = carte3d.fabriquer_pcd(args.enregistrement, sortie, sujet_nuage=args.nuage, sujet_odom=args.odom,
                                         grille=args.grille, capteur=args.capteur, portee=args.portee,
                                         afficher=print)
    except (carte3d.ErreurCarte3d, ErreurLieu) as e:
        print(f"Carte 3D non fabriquée : {e}")
        return 1
    print(f"Nuage 3D écrit : {resultat['fichier']} ({resultat['points']} points, grille de {args.grille * 100:g} cm)")
    print(f"Suite : g1-carte-2d --lieu {args.lieu} --etage {args.etage}")
    return 0


def principal_carte2d(argv):
    p = Analyseur(prog="g1-carte-2d",
                  description="Fabrique la carte 2D de navigation (cartes/<etage>.pgm et .yaml) à partir du nuage "
                              "3D cartes/<etage>.pcd : tranche de 0,1 à 1,5 m au-dessus du sol, nettoyée.")
    p.add_argument("--lieu", required=True, help="dossier du lieu, ou id seul (ex. demo)")
    p.add_argument("--etage", required=True, help="id de l'étage, ex. rdc")
    p.add_argument("--pcd", help="nuage à lire (défaut : cartes/<etage>.pcd du lieu)")
    p.add_argument("--sortie", metavar="FICHIER.yaml",
                   help="carte à écrire ailleurs, sans toucher au lieu (défaut : cartes/<etage>.yaml, "
                        "et source_carte: scan dans lieu.yaml)")
    p.add_argument("--sol", type=float, help="hauteur du sol dans le nuage, en m (défaut : trouvée seule)")
    p.add_argument("--comparer", metavar="CARTE.yaml",
                   help="affiche le recouvrement avec une autre carte (ex. celle générée depuis le monde)")
    args = p.parse_args(argv)

    from atelier.lieu import ErreurLieu
    from atelier.scan import carte2d
    try:
        resultat = carte2d.fabriquer_carte_lieu(args.lieu, args.etage, pcd=args.pcd, sortie=args.sortie,
                                                sol=args.sol, afficher=print)
        if args.comparer:
            r = carte2d.comparer_fichiers(resultat["fichier"], args.comparer)
            print(f"Recouvrement avec {args.comparer} : {r['recouvrement'] * 100:.1f} % des pixels occupés du "
                  f"scan sur un obstacle de la carte (à 1 pixel près) ; couverture {r['couverture'] * 100:.1f} %")
    except (carte2d.ErreurCarte2d, ErreurLieu) as e:
        print(f"Carte 2D non fabriquée : {e}")
        return 1
    return 0


# ================================================================ g1-salle

def principal_salle(argv):
    p = Analyseur(prog="g1-salle",
                  description="Ajoute au lieu une salle (ou un nœud d'itinéraire) à la position actuelle du robot, "
                              "lue une fois sur /odom (ou --sujet).")
    sous = p.add_subparsers(dest="commande", metavar="COMMANDE", parser_class=Analyseur)
    sous.required = True
    s = sous.add_parser("ajouter", help="ajouter (ou déplacer) une salle ou un nœud à la position du robot")
    s.add_argument("nom", metavar="NOM", help="nom de la salle (ex. « Salle B204 ») ; l'id en est tiré (b204)")
    s.add_argument("--type", choices=["salle", "noeud"], default="salle")
    s.add_argument("--lieu", required=True, help="dossier du lieu, ou id seul (ex. demo)")
    s.add_argument("--etage", help="id de l'étage (défaut : le premier du lieu)")
    s.add_argument("--id", help="identifiant à utiliser (défaut : tiré du nom)")
    s.add_argument("--alias", action="append", default=[], help="autre nom de la salle (répétable)")
    s.add_argument("--phrase", default=None, help="phrase dite par le guide à l'arrivée")
    s.add_argument("--sujet", default="/odom",
                   help="sujet de la position (nav_msgs/Odometry), ex. /unitree/slam_relocation/odom")
    s.add_argument("--delai", type=float, default=5.0, help="attente maximale de la position, en s")
    args = p.parse_args(argv)

    from atelier.lieu import ErreurLieu
    from atelier.scan import salle
    try:
        pose = salle.lire_position(args.sujet, args.delai)
        if pose is None:
            print(f"Aucune position reçue sur {args.sujet} en {args.delai:g} s. La simulation (g1-monde simuler) "
                  "ou le relais du robot tourne-t-il ? Même ROS_DOMAIN_ID que lui ?")
            return 1
        resultat = salle.ajouter(args.lieu, args.nom, pose, type_=args.type, etage=args.etage, id_=args.id,
                                 alias=args.alias, phrase=args.phrase)
    except ErreurLieu as e:
        return _erreur_lieu(e)
    except ValueError as e:
        print(f"Erreur : {e}")
        return 1
    for ligne in resultat["messages"]:
        print(ligne)
    return 0


PRINCIPAUX = {"slam": principal_slam, "carte-3d": principal_carte3d, "carte-2d": principal_carte2d,
              "salle": principal_salle}


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in PRINCIPAUX:
        print("usage : python -m atelier.scan.commande slam|carte-3d|carte-2d|salle ...")
        sys.exit(2)
    sys.exit(PRINCIPAUX[sys.argv[1]](sys.argv[2:]))
