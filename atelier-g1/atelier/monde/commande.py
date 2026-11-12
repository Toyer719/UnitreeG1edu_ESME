#!/usr/bin/env python3
"""Fabriquer le monde Gazebo et la carte d'un étage, puis le simuler.

  g1-monde generer --lieu L --etage E [--hauteur-carte 1.5]
      mondes/E.monde.yaml → mondes/E.sdf, cartes/E.pgm et .yaml, cartes/E_interdit.pgm et .yaml ;
      étage scanné (vague 5) : la carte du scan extrudée en un maillage, mondes/E_carte.stl, dans le monde
  g1-monde simuler --lieu L --etage E [--sans-fenetre] [--jumeau] [--pietons corps|acteurs]
      Gazebo, robot proxy et piétons : ros2 launch g1_sim simulation.launch.py (section 4.5 du plan) ;
      --jumeau : répétition du vrai robot, avec le faux G1 (jumeau:=true, section 10.4) ;
      --pietons : piétons crédibles (corps, le défaut de g1_sim) ou <actor> de la vague 1 (11.3)

L : chemin du lieu, ou id seul (demo désigne ~/robot-g1/lieux/demo). Lancé par bin/g1-monde avec
le Python de .venv-projet. Code de sortie : 0 si tout va bien, 1 en cas d'erreur, 2 si la commande
est mal tapée.
"""
import argparse
import os
import shutil
import sys

from atelier.lieu import ErreurLieu, charger_fiche, chemin_monde, chemin_sdf, dossier_lieu
from atelier.monde import generer

# Messages d'argparse les plus courants, en français
TRADUCTIONS = [("the following arguments are required:", "il manque :"),
               ("invalid choice:", "choix inconnu :"), ("choose from", "possibles :"),
               ("unrecognized arguments:", "arguments inconnus :"), ("expected one argument", "il faut une valeur")]


class Analyseur(argparse.ArgumentParser):
    def error(self, message):
        for anglais, francais in TRADUCTIONS:
            message = message.replace(anglais, francais)
        self.print_usage(sys.stderr)
        self.exit(2, f"erreur : {message}\nAide : {self.prog} --help\n")


def _afficher_erreurs(titre, erreur):
    print(titre)
    for m in erreur.erreurs:
        print(f"  - {m}")


def _verifier_lieu(lieu, etage):
    """Dossier du lieu, après avoir vérifié qu'il existe et qu'il a cet étage. ErreurLieu sinon."""
    dossier = dossier_lieu(lieu)
    if not (dossier / "lieu.yaml").is_file():
        raise ErreurLieu(f"le lieu {dossier} n'existe pas ; pour en créer un : g1-lieu creer ID --nom NOM")
    fiche = charger_fiche(dossier)
    if fiche.etage(etage) is None:
        connus = ", ".join(e.id for e in fiche.etages)
        raise ErreurLieu(f"lieu.yaml : pas d'étage « {etage} » (étages du lieu : {connus})")
    return dossier


def commande_generer(args):
    try:
        dossier = _verifier_lieu(args.lieu, args.etage)
        resultat = generer(dossier, args.etage, hauteur_carte=args.hauteur_carte)
    except ErreurLieu as e:
        _afficher_erreurs("Rien n'a été généré :", e)
        return 1
    print(f"Étage « {args.etage} » du lieu {dossier} :")
    print(resultat.texte())
    if resultat.sdf:
        print(f"Suite : g1-monde simuler --lieu {args.lieu} --etage {args.etage}")
    return 0


def commande_ros2(args, dossier):
    """La commande ros2 launch du contrat 4.5, sous forme de liste."""
    commande = ["ros2", "launch", "g1_sim", "simulation.launch.py", f"lieu:={dossier}", f"etage:={args.etage}",
                f"sans_fenetre:={'true' if args.sans_fenetre else 'false'}"]
    if args.monde:
        commande.append(f"monde:={os.path.abspath(args.monde)}")
    if getattr(args, "jumeau", False):
        commande.append("jumeau:=true")
    if getattr(args, "pietons", None):
        commande.append(f"pietons:={args.pietons}")
    return commande


def paquet_ros_trouve(nom):
    """Vrai si le paquet ROS 2 est installé dans l'environnement chargé (AMENT_PREFIX_PATH).
    Sans ament_index_python, on laisse ros2 launch répondre."""
    try:
        from ament_index_python.packages import PackageNotFoundError, get_package_prefix
    except ImportError:
        return True
    try:
        get_package_prefix(nom)
        return True
    except PackageNotFoundError:
        return False


def commande_simuler(args):
    try:
        dossier = _verifier_lieu(args.lieu, args.etage)
    except ErreurLieu as e:
        _afficher_erreurs("Simulation non lancée :", e)
        return 1
    sdf = chemin_sdf(dossier, args.etage) if not args.monde else os.path.abspath(args.monde)
    if not os.path.isfile(sdf):
        print(f"Simulation non lancée : le monde Gazebo {sdf} n'existe pas.")
        if not args.monde:
            print(f"Fabriquez-le d'abord : g1-monde generer --lieu {args.lieu} --etage {args.etage}")
        return 1
    monde = chemin_monde(dossier, args.etage)
    if not args.monde and monde.is_file() and monde.stat().st_mtime > os.stat(sdf).st_mtime + 1:
        print(f"Attention : mondes/{args.etage}.monde.yaml a changé depuis la dernière génération ; "
              f"pour simuler la nouvelle version : g1-monde generer --lieu {args.lieu} --etage {args.etage}")

    commande = commande_ros2(args, dossier)
    if args.afficher:
        print(" ".join(commande))
        return 0
    if shutil.which("ros2") is None:
        print("Simulation non lancée : la commande ros2 est introuvable. "
              "Chargez l'environnement : source ~/robot-g1/setup/env.sh")
        return 1
    if not paquet_ros_trouve("g1_sim"):
        print("Simulation non lancée : le paquet ROS 2 g1_sim est introuvable. Compilez-le, puis rechargez "
              "l'environnement :\n  cd ~/robot-g1/ws && colcon build --symlink-install --packages-select g1_sim"
              "\n  source ~/robot-g1/setup/env.sh")
        return 1
    if args.jumeau and not paquet_ros_trouve("g1_jumeau"):
        print("Simulation non lancée : --jumeau demande le paquet ROS 2 g1_jumeau (faux G1), introuvable. "
              "Compilez-le, puis rechargez l'environnement :\n  cd ~/robot-g1/ws && colcon build "
              "--symlink-install --packages-select g1_bridge g1_jumeau\n  source ~/robot-g1/setup/env.sh")
        return 1
    print("Lancement :", " ".join(commande))
    sys.stdout.flush()
    # ros2 launch remplace ce programme : Ctrl+C et l'arrêt par l'Atelier lui parviennent directement
    os.execvp(commande[0], commande)


def main(argv=None):
    p = Analyseur(prog="g1-monde", description="Monde Gazebo, carte 2D et simulation d'un étage d'un lieu.")
    sous = p.add_subparsers(dest="action", metavar="ACTION", parser_class=Analyseur)
    sous.required = True

    g = sous.add_parser("generer", help="fabriquer le monde Gazebo, la carte 2D et le masque des zones interdites")
    g.add_argument("--lieu", required=True, help="dossier du lieu, ou id seul (ex. demo)")
    g.add_argument("--etage", required=True, help="id de l'étage (ex. rdc)")
    g.add_argument("--hauteur-carte", type=float, default=None, metavar="M",
                   help="étage scanné : hauteur des obstacles de la carte extrudée, en m (défaut : celle du monde, "
                        "sinon 1,5)")
    g.set_defaults(fonction=commande_generer)

    s = sous.add_parser("simuler", help="lancer Gazebo avec le robot proxy et les piétons")
    s.add_argument("--lieu", required=True, help="dossier du lieu, ou id seul (ex. demo)")
    s.add_argument("--etage", required=True, help="id de l'étage (ex. rdc)")
    s.add_argument("--sans-fenetre", action="store_true", help="Gazebo sans fenêtre (serveur seul)")
    s.add_argument("--monde", help="autre monde .sdf à charger (par défaut : mondes/<etage>.sdf du lieu)")
    s.add_argument("--jumeau", action="store_true",
                   help="répétition du vrai robot : le faux G1 reçoit les ordres de marche (7105) et pilote "
                        "le robot proxy ; rien sur /cmd_vel, /odom ni /tf")
    s.add_argument("--pietons", choices=["corps", "acteurs"], default=None,
                   help="piétons crédibles, un corps qui gêne le robot (corps, le défaut), ou <actor> de la "
                        "vague 1, traversables (acteurs)")
    s.add_argument("--afficher", action="store_true", help="afficher la commande ros2 launch sans la lancer")
    s.set_defaults(fonction=commande_simuler)

    args = p.parse_args(argv)
    return args.fonction(args)


if __name__ == "__main__":
    sys.exit(main())
