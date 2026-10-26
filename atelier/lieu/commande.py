#!/usr/bin/env python3
"""Créer ou vérifier un paquet de lieu de l'Atelier G1.

  g1-lieu creer ID --nom NOM     crée lieux/ID : un étage, l'accueil, un monde entouré de 4 murs
  g1-lieu valider --lieu L       vérifie le lieu L (chemin, ou id seul : demo) et dit quoi corriger
  g1-lieu liste                  liste les lieux de ~/robot-g1/lieux
  g1-lieu migrer --lieu L [--depuis-depart] [--a-blanc]
                                 vague 4 (section 11.2 du plan) : le point principal du lieu reçoit
                                 l'étiquette « principal », après une sauvegarde des fichiers d'avant

Lancé par bin/g1-lieu avec le Python de .venv-projet. Code de sortie : 0 si tout va bien,
1 s'il y a des erreurs (ou si la migration est refusée), 2 si la commande est mal tapée.
"""
import argparse
import sys

from atelier.lieu import ErreurLieu, creer_lieu, dossier_lieu, lister_lieux, valider_lieu
from atelier.lieu.principal import migrer_lieu, texte_migration


# Messages d'argparse les plus courants, en français
TRADUCTIONS = [("the following arguments are required:", "il manque :"),
               ("invalid choice:", "choix inconnu :"), ("choose from", "possibles :"),
               ("unrecognized arguments:", "arguments inconnus :"), ("expected one argument", "il faut une valeur"),
               ("invalid float value:", "nombre attendu, pas")]


class Analyseur(argparse.ArgumentParser):
    def error(self, message):
        for anglais, francais in TRADUCTIONS:
            message = message.replace(anglais, francais)
        self.print_usage(sys.stderr)
        self.exit(2, f"erreur : {message}\nAide : {self.prog} --help\n")


def _pluriel(n, mot, pluriel=None):
    return f"{n} {mot if n <= 1 else (pluriel or mot + 's')}"


def resume(lieu):
    """Une ligne qui décrit le contenu du lieu."""
    itin, zones = lieu.itineraires, lieu.zones
    return ", ".join([_pluriel(len(lieu.etages), "étage"), _pluriel(len(lieu.salles), "salle"),
                      _pluriel(len(itin.noeuds), "nœud"), _pluriel(len(itin.couloirs), "couloir"),
                      _pluriel(len(zones.interdites), "zone interdite", "zones interdites"),
                      _pluriel(len(zones.lentes), "zone lente", "zones lentes"),
                      _pluriel(len(lieu.mondes), "monde")])


def commande_creer(args):
    try:
        lieu = creer_lieu(args.id, args.nom, args.etage, args.nom_etage, args.largeur, args.profondeur)
    except ErreurLieu as e:
        print("Lieu non créé :")
        for m in e.erreurs:
            print(f"  - {m}")
        return 1
    print(f"Lieu « {lieu.nom} » créé dans {lieu.dossier}")
    print(f"  étage {args.etage} ({args.nom_etage}) : monde de {args.largeur:g} × {args.profondeur:g} m "
          "entouré de 4 murs, accueil en (1, 1)")
    print(f"Suite : dessinez le monde dans l'Atelier (g1-atelier), puis : g1-lieu valider --lieu {lieu.id}")
    return 0


def commande_valider(args):
    rapport = valider_lieu(args.lieu)
    if rapport.lieu is not None:
        print(f"Lieu « {rapport.lieu.nom} » ({rapport.lieu.dossier})")
        print(f"  {resume(rapport.lieu)}")
    else:
        try:
            print(f"Lieu {dossier_lieu(args.lieu)}")
        except ValueError:
            pass
    print(rapport.texte())
    return 0 if rapport.ok else 1


def commande_liste(args):
    lieux = lister_lieux()
    if not lieux:
        print("Aucun lieu. Pour en créer un : g1-lieu creer ID --nom NOM")
        return 0
    for dossier in lieux:
        print(f"  {dossier.name:20s} {dossier}")
    return 0


def commande_migrer(args):
    try:
        rapport = migrer_lieu(args.lieu, depuis_depart=args.depuis_depart, a_blanc=args.a_blanc)
    except ErreurLieu as e:
        print("Migration refusée :")
        for m in e.erreurs:
            print(f"  - {m}")
        return 1
    print(texte_migration(rapport))
    if rapport["changements"] and not rapport["a_blanc"]:
        print(f"Vérification : g1-lieu valider --lieu {args.lieu}")
    return 0


def main(argv=None):
    p = Analyseur(prog="g1-lieu", description="Créer ou vérifier un paquet de lieu de l'Atelier G1.")
    sous = p.add_subparsers(dest="commande", metavar="{creer,valider,liste,migrer}", parser_class=Analyseur)
    sous.required = True

    c = sous.add_parser("creer", help="créer un lieu neuf", description="Créer un lieu neuf : un étage, "
                        "l'accueil en (1, 1), la salle et le nœud accueil, un monde entouré de 4 murs.")
    c.add_argument("id", help="identifiant du lieu, ex. lycee (dossier ~/robot-g1/lieux/lycee), ou chemin")
    c.add_argument("--nom", required=True, help="nom affiché du lieu, ex. \"Lycée Victor Hugo\"")
    c.add_argument("--etage", default="rdc", help="id du premier étage (défaut : rdc)")
    c.add_argument("--nom-etage", default="Rez-de-chaussée", help="nom affiché du premier étage")
    c.add_argument("--largeur", type=float, default=20.0, help="taille du monde le long de x, en m (défaut : 20)")
    c.add_argument("--profondeur", type=float, default=15.0, help="taille du monde le long de y, en m (défaut : 15)")
    c.set_defaults(fonction=commande_creer)

    v = sous.add_parser("valider", help="vérifier un lieu et dire quoi corriger",
                        description="Vérifier tous les fichiers d'un lieu et leur cohérence.")
    v.add_argument("--lieu", required=True, help="dossier du lieu, ou son id seul (ex. demo)")
    v.set_defaults(fonction=commande_valider)

    li = sous.add_parser("liste", help="lister les lieux", description="Lister les lieux de ~/robot-g1/lieux.")
    li.set_defaults(fonction=commande_liste)

    m = sous.add_parser("migrer", help="donner au lieu son point principal (format de la vague 4)",
                        description="Point principal du lieu (l'accueil : départ de la simulation, pose du "
                        "repérage, retour après chaque visite) : la salle « accueil » reçoit l'étiquette "
                        "« principal », et accueil de lieu.yaml, son nœud et depart_robot s'alignent sur elle. "
                        "Les fichiers d'avant sont d'abord copiés dans lieux/<id>/sauvegardes/. Un second "
                        "passage ne change rien. lieux/demo (référence des tests) est refusé.")
    m.add_argument("--lieu", required=True, help="dossier du lieu, ou son id seul (ex. bomboclat)")
    m.add_argument("--depuis-depart", action="store_true",
                   help="le point principal prend d'abord la pose depart_robot du monde de son étage")
    m.add_argument("--a-blanc", action="store_true", help="montrer ce qui changerait, sans rien écrire")
    m.set_defaults(fonction=commande_migrer)

    args = p.parse_args(argv)
    return args.fonction(args)


if __name__ == "__main__":
    sys.exit(main())
