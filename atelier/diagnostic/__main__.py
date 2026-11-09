"""g1-diagnostic : « Vérifier le robot » en ligne de commande (vague 6, section 13.2 du plan) : agent Diagnostic.

  g1-diagnostic [--mode reel|repetition] [--rapide] [--json]
        toutes les vérifications, le même code que le bouton de l'Atelier (atelier.diagnostic.diagnostiquer), avec
        son propre nœud ROS 2 (g1_diagnostic) ; sortie en français, ou le résultat brut (--json, schéma
        diagnostic) ; code de sortie 0 si rien n'est en Attention ni en Problème, 1 sinon ;
  g1-diagnostic --action demarrer-services|retablir-cable|cable-automatique [--mode …]
        une action de la liste blanche, après la question « Confirmer ? » (répondez oui) ; rien ne part sans
        « oui » ; code 0 si elle a réussi, 1 sinon.
Python du projet (.venv-projet) avec ROS 2 chargé (bin/g1-diagnostic). Dans le terminal relié au robot :
« source ~/robot-g1/setup/robot.sh » d'abord. Tests : ATELIER_DIAGNOSTIC_FAUX (vérifications système simulées).
"""
import argparse
import json
import sys

from atelier.lieu.diagnostic import ACTIONS_DIAGNOSTIC, code_de_sortie

TRADUCTIONS = [("the following arguments are required:", "il manque :"),
               ("invalid choice:", "choix inconnu :"), ("choose from", "possibles :"),
               ("unrecognized arguments:", "arguments inconnus :"), ("expected one argument", "il faut une valeur")]
REPONSES_OUI = ("oui", "o", "yes", "y")


class Analyseur(argparse.ArgumentParser):
    def error(self, message):
        for anglais, francais in TRADUCTIONS:
            message = message.replace(anglais, francais)
        self.print_usage(sys.stderr)
        self.exit(2, f"erreur : {message}\nAide : {self.prog} --help\n")


def analyseur():
    a = Analyseur(prog="g1-diagnostic", description="Vérifier le robot : câble, réseau, services, mode, batterie et "
                  "Jetson, en quelques secondes, avec un conseil pour chaque problème (section 13.2 du plan).")
    a.add_argument("--mode", choices=("reel", "repetition"), default="reel",
                   help="reel (le vrai robot, par défaut) ou repetition (le faux G1)")
    a.add_argument("--rapide", action="store_true", help="sans le Jetson (pas de ssh)")
    a.add_argument("--json", action="store_true", help="le résultat brut (schéma diagnostic)")
    a.add_argument("--action", choices=tuple(ACTIONS_DIAGNOSTIC),
                   help="une action, après confirmation : " + ", ".join(ACTIONS_DIAGNOSTIC))
    return a


def confirmer(action, entree=None, sortie=None):
    """Pose la question de l'action ; vrai seulement si la réponse est « oui »."""
    entree = entree or sys.stdin
    sortie = sortie or sys.stdout
    texte = ACTIONS_DIAGNOSTIC[action]
    print(f"{texte['libelle']} : {texte['confirmation']}", file=sortie)
    print("Confirmer ? Tapez oui puis Entrée (autre chose : rien n'est envoyé) : ", end="", file=sortie, flush=True)
    try:
        reponse = entree.readline()
    except (OSError, KeyboardInterrupt):
        reponse = ""
    print("", file=sortie)
    return reponse.strip().lower() in REPONSES_OUI


def main(argv=None):
    args = analyseur().parse_args(argv)
    from atelier.diagnostic import ActionImpossible, ServiceInterdit, diagnostiquer, faire_action, verifier_action
    from atelier.diagnostic.texte import couleurs_permises, texte_action, texte_diagnostic
    try:
        if args.action:
            try:
                verifier_action(args.action, args.mode)
            except (ActionImpossible, ServiceInterdit) as e:
                print(f"Rien n'a été envoyé : {e}", file=sys.stderr)
                return 1
            if not confirmer(args.action):
                print("Rien n'a été envoyé (pas de « oui »).")
                return 1
            r = faire_action(args.action, mode=args.mode)
            if args.json:
                print(json.dumps(r, ensure_ascii=False, indent=1))
            else:
                print(texte_action(r))
            return 0 if r.get("ok") else 1
        d = diagnostiquer(args.mode, source="g1-diagnostic", rapide=args.rapide)
    except ValueError as e:
        print(f"erreur : {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nInterrompu.", file=sys.stderr)
        return 130
    if args.json:
        print(json.dumps(d, ensure_ascii=False, indent=1))
    else:
        print(texte_diagnostic(d, couleur=couleurs_permises(sys.stdout)))
    return code_de_sortie(d)


if __name__ == "__main__":
    sys.exit(main())
