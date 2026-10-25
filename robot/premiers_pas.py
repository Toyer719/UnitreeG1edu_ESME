#!/usr/bin/env python3
"""Premiers tests du vrai G1 : voix, LED, gestes, puis quelques pas très lents.

Avant de lancer :
  1. robot sur son portique, zone dégagée, une personne avec la télécommande officielle ;
  2. robot debout en mode marche (télécommande) pour les gestes et les déplacements ;
  3. dans ce terminal : source ~/robot-g1/setup/robot.sh
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "outils"))
from connexion import connecter, expliquer  # noqa: E402

from unitree_sdk2py.g1.arm.g1_arm_action_client import G1ArmActionClient, action_map  # noqa: E402
from unitree_sdk2py.g1.audio.g1_audio_client import AudioClient  # noqa: E402
from unitree_sdk2py.g1.loco.g1_loco_client import LocoClient  # noqa: E402

VITESSE_TEST = 0.2      # m/s
ROTATION_TEST = 0.3     # rad/s
DUREE_TEST = 2.0        # s
COULEURS = {"rouge": (255, 0, 0), "vert": (0, 255, 0), "bleu": (0, 0, 255), "blanc": (255, 255, 255),
            "eteinte": (0, 0, 0)}
GESTES = ["face wave", "high wave", "shake hand", "clap", "high five", "heart", "hug", "reject",
          "hands up", "release arm"]

MENU = """
  1  Faire parler le robot
  2  Changer la couleur de la LED
  3  Faire un geste avec les bras
  4  Faire coucou (contrôleur de marche)
  5  Avancer à 0,2 m/s pendant 2 s
  6  Tourner sur place pendant 2 s
  7  Arrêter tout déplacement
  0  Quitter"""


def demander(question):
    try:
        return input(question).strip()
    except EOFError:
        return "0"


def confirmer_securite():
    print("Le robot est debout en mode marche, la zone est dégagée, la télécommande est en main ?")
    return demander("Tapez « oui » pour continuer : ").lower() == "oui"


def deplacer(loco, vx, wz):
    if not confirmer_securite():
        print("Annulé.")
        return
    fin = time.time() + DUREE_TEST
    code = 0
    while time.time() < fin and code == 0:
        code = loco.SetVelocity(vx, 0.0, wz, 0.5)
        time.sleep(0.2)
    loco.SetVelocity(0.0, 0.0, 0.0, 1.0)
    print(f"Déplacement : {expliquer(code)}. Robot arrêté.")


def main():
    p = argparse.ArgumentParser(description="Premiers tests du vrai G1.")
    p.add_argument("interface", nargs="?", default="eno2", help="eno2 (robot, défaut) ou lo (simulateur)")
    args = p.parse_args()

    print(__doc__)
    if connecter(args.interface) is None:
        return 1
    print("Robot connecté.")

    audio, loco, bras = AudioClient(), LocoClient(), G1ArmActionClient()
    for client in (audio, loco, bras):
        client.SetTimeout(3.0)
        client.Init()

    while True:
        print(MENU)
        choix = demander("Votre choix : ")
        if choix == "0":
            loco.SetVelocity(0.0, 0.0, 0.0, 1.0)
            return 0
        if choix == "1":
            texte = demander("Phrase à dire (Entrée = « Hello, I am G1 ») : ") or "Hello, I am G1"
            print("La voix intégrée ne parle pas français : une phrase française sera mal prononcée.")
            print(f"Voix : {expliquer(audio.TtsMaker(texte, 0))}")
        elif choix == "2":
            nom = demander(f"Couleur ({', '.join(COULEURS)}) : ").lower()
            if nom in COULEURS:
                print(f"LED : {expliquer(audio.LedControl(*COULEURS[nom]))}")
            else:
                print("Couleur inconnue.")
        elif choix == "3":
            for i, nom in enumerate(GESTES, 1):
                print(f"  {i:2d}  {nom}")
            n = demander("Numéro du geste (« release arm » relâche les bras restés levés) : ")
            if n.isdigit() and 1 <= int(n) <= len(GESTES):
                print(f"Geste : {expliquer(bras.ExecuteAction(action_map[GESTES[int(n) - 1]]))}")
            else:
                print("Numéro inconnu.")
        elif choix == "4":
            print(f"Coucou : {expliquer(loco.SetTaskId(0))}")
        elif choix == "5":
            deplacer(loco, VITESSE_TEST, 0.0)
        elif choix == "6":
            deplacer(loco, 0.0, ROTATION_TEST)
        elif choix == "7":
            print(f"Arrêt : {expliquer(loco.SetVelocity(0.0, 0.0, 0.0, 1.0))}")
        else:
            print("Choix inconnu.")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
