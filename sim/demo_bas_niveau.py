#!/usr/bin/env python3
"""Rejoue l'exemple bas niveau d'Unitree (g1_low_level_example.py) dans le simulateur.

Sur le vrai robot, cet exemple coupe d'abord le contrôleur de marche puis pilote
chaque moteur directement : ne jamais le lancer ailleurs que dans g1-sim.
Le simulateur n'a pas le service qui coupe la marche ; on le remplace ici
par une version vide, sans modifier le dépôt d'Unitree.
"""
import runpy
import signal
import sys
from pathlib import Path

import unitree_sdk2py.comm.motion_switcher.motion_switcher_client as motion_switcher

EXEMPLE = (Path(__file__).resolve().parents[1] / "third_party" / "unitree_sdk2_python"
           / "example" / "g1" / "low_level" / "g1_low_level_example.py")


class SansControleurDeMarche:
    """Le simulateur n'a pas de contrôleur de marche à couper."""

    def SetTimeout(self, _):
        pass

    def Init(self):
        pass

    def CheckMode(self):
        return 0, {"name": ""}

    def ReleaseMode(self):
        return 0


if __name__ == "__main__":
    # Ctrl+C doit marcher même si la démo a été lancée en arrière-plan
    signal.signal(signal.SIGINT, signal.default_int_handler)
    motion_switcher.MotionSwitcherClient = SansControleurDeMarche
    sys.argv = [str(EXEMPLE), "lo"]
    print(__doc__)
    print("Ctrl+C pour arrêter la démo.")
    try:
        runpy.run_path(str(EXEMPLE), run_name="__main__")
    except KeyboardInterrupt:
        print("\nDémo arrêtée.")
