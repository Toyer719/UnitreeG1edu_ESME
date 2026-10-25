#!/usr/bin/env python3
"""Simulateur MuJoCo officiel d'Unitree avec un G1 complet, relié au SDK par DDS.

Il se comporte comme le vrai robot en mode bas niveau : les programmes du SDK
s'y connectent avec l'interface « lo » au lieu de « eno2 ».
Le robot est tenu par un élastique virtuel, comme sur le portique :
  touche 7 = le remonter, 8 = le descendre, 9 = détacher / rattacher l'élastique.
Une manette branchée remplace la télécommande Unitree.
"""
import argparse
import runpy
import signal
import sys
import threading
import time
import types
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
SIM = RACINE / "third_party" / "unitree_mujoco" / "simulate_python"
sys.path.insert(0, str(RACINE / "outils"))
from manette import manette_presente  # noqa: E402


def main():
    p = argparse.ArgumentParser(description="Simulateur MuJoCo officiel d'Unitree, G1 relié au SDK.")
    p.add_argument("--ddl", choices=["23", "29"], default="29",
                   help="version du G1 : 23 ou 29 degrés de liberté (défaut : 29)")
    args = p.parse_args()

    # Remplace config.py d'Unitree sans modifier leur dépôt
    config = types.ModuleType("config")
    config.ROBOT = "g1"
    config.ROBOT_SCENE = str(SIM.parent / "unitree_robots" / "g1" / f"scene_{args.ddl}dof.xml")
    config.DOMAIN_ID = 0
    config.INTERFACE = "lo"
    config.USE_JOYSTICK = 1 if manette_presente() else 0
    config.JOYSTICK_TYPE = "xbox"
    config.JOYSTICK_DEVICE = 0
    config.PRINT_SCENE_INFORMATION = False
    config.ENABLE_ELASTIC_BAND = True
    config.SIMULATE_DT = 0.005
    config.VIEWER_DT = 0.02
    sys.modules["config"] = config

    # Ctrl+C ferme la fenêtre ; les fils du simulateur s'arrêtent avec elle
    arret = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: arret.set())

    print(__doc__)
    print(f"G1 {args.ddl} ddl, manette {'détectée' if config.USE_JOYSTICK else 'absente'}. Ctrl+C pour quitter.")
    sys.path.insert(0, str(SIM))
    # Le script d'Unitree ouvre la fenêtre, démarre ses fils de simulation puis rend la main
    viewer = runpy.run_path(str(SIM / "unitree_mujoco.py"), run_name="__main__")["viewer"]
    while viewer.is_running() and not arret.is_set():
        time.sleep(0.1)
    viewer.close()
    # Attendre les fils de simulation d'Unitree et le fil de la fenêtre MuJoCo (sinon Python plante
    # en sortant) ; les fils de communication du SDK, eux, ne s'arrêtent jamais et disparaissent à la sortie.
    for fil in threading.enumerate():
        fenetre = getattr(getattr(fil, "_target", None), "__name__", "") == "_launch_internal"
        if fil is not threading.current_thread() and (not fil.daemon or fenetre):
            fil.join(timeout=3.0)
    print("Simulateur arrêté.")


if __name__ == "__main__":
    main()
