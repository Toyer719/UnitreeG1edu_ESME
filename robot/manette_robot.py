#!/usr/bin/env python3
"""Piloter le vrai G1 à la manette, avec un bouton d'homme mort.

Le robot doit déjà être debout en mode marche (télécommande officielle).
  LB (L1) maintenu   autorise le mouvement ; relâché, le robot s'arrête
  stick gauche       avancer / reculer, glisser sur le côté
  stick droit        tourner
  B (rond)           arrêt immédiat
  A (croix)          coucou, robot à l'arrêt
La télécommande officielle reste l'arrêt d'urgence : gardez-la en main.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "outils"))
from connexion import connecter, expliquer  # noqa: E402
from manette import Manette  # noqa: E402

from unitree_sdk2py.g1.loco.g1_loco_client import LocoClient  # noqa: E402

VITESSE_PLAFOND = 0.6   # m/s, même si on demande plus
ROTATION_MAX = 0.5      # rad/s
PERIODE = 0.1           # s, 10 commandes par seconde
DUREE_CONSIGNE = 0.5    # s : sans nouvelle commande, le robot s'arrête de lui-même


def main():
    p = argparse.ArgumentParser(description="Piloter le vrai G1 à la manette.")
    p.add_argument("interface", nargs="?", default="eno2", help="eno2 (robot, défaut) ou lo (simulateur)")
    p.add_argument("--vitesse-max", type=float, default=0.3,
                   help=f"vitesse maximale vers l'avant en m/s (défaut 0.3, plafond {VITESSE_PLAFOND})")
    args = p.parse_args()
    vx_max = min(args.vitesse_max, VITESSE_PLAFOND)
    vy_max = vx_max / 1.5

    print(__doc__)
    manette = Manette()
    if manette.nom is None:
        print("Aucune manette détectée : branchez-la puis relancez.")
        return 1
    print(f"Manette : {manette.nom}")
    if connecter(args.interface) is None:
        return 1

    loco = LocoClient()
    loco.SetTimeout(1.0)
    loco.Init()
    print(f"Prêt. Vitesse max {vx_max:.2f} m/s. Ctrl+C pour quitter.\n")

    en_mouvement = False
    a_avant = False
    prochaine_erreur = 0.0

    def arreter():
        nonlocal en_mouvement
        loco.SetVelocity(0.0, 0.0, 0.0, 1.0)
        en_mouvement = False

    try:
        while True:
            debut = time.time()
            etat = manette.lire()
            if etat is None:
                if en_mouvement:
                    arreter()
                print("\rManette déconnectée : robot arrêté. Rebranchez-la.        ", end="", flush=True)
            elif etat.b:
                arreter()
                print("\rArrêt (B).                                              ", end="", flush=True)
            elif etat.lb:
                vx, vy, wz = etat.avant * vx_max, etat.gauche * vy_max, etat.rotation * ROTATION_MAX
                code = loco.SetVelocity(vx, vy, wz, DUREE_CONSIGNE)
                en_mouvement = True
                if code != 0 and debut > prochaine_erreur:
                    print(f"\nCommande refusée : {expliquer(code)}. Le robot est-il debout en mode marche ?")
                    prochaine_erreur = debut + 2.0
                print(f"\rAvancer {vx:+.2f} m/s   Glisser {vy:+.2f} m/s   Tourner {wz:+.2f} rad/s   ",
                      end="", flush=True)
            else:
                if en_mouvement:
                    arreter()
                if etat.a and not a_avant:
                    print(f"\nCoucou : {expliquer(loco.SetTaskId(0))}")
                print("\rLB relâché : robot à l'arrêt.                           ", end="", flush=True)
            a_avant = etat is not None and etat.a
            time.sleep(max(0.0, PERIODE - (time.time() - debut)))
    except KeyboardInterrupt:
        arreter()
        print("\nRobot arrêté. Au revoir.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
