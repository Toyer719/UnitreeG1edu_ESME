#!/usr/bin/env python3
"""Affiche l'état du G1 sans rien commander : connexion, inclinaison, moteurs, batterie.

  g1-etat          vrai robot (port eno2, lancer d'abord : source ~/robot-g1/setup/robot.sh)
  g1-etat lo       simulateur (g1-sim)
"""
import argparse
import math
import sys
import time

from unitree_sdk2py.core.channel import ChannelSubscriber
from unitree_sdk2py.idl.unitree_hg.msg.dds_ import BmsState_

from connexion import connecter


class Batterie:
    """Dernier état de la batterie (publié par le vrai robot seulement)."""

    def __init__(self):
        self.etat = None
        self.abonnement = ChannelSubscriber("rt/lf/bmsstate", BmsState_)
        self.abonnement.Init(self.recevoir, 10)

    def recevoir(self, msg: BmsState_):
        self.etat = msg

    def texte(self):
        return "Batterie   —" if self.etat is None else f"Batterie {self.etat.soc:3d} %"


def main():
    p = argparse.ArgumentParser(description="État du G1, en lecture seule.")
    p.add_argument("interface", nargs="?", default="eno2", help="eno2 (robot, défaut) ou lo (simulateur)")
    p.add_argument("--une-fois", action="store_true", help="affiche une mesure puis quitte")
    args = p.parse_args()

    lecteur = connecter(args.interface)
    if lecteur is None:
        return 1
    batterie = Batterie()

    try:
        while True:
            m = lecteur.dernier
            roulis, tangage, lacet = (math.degrees(a) for a in m.imu_state.rpy[:3])
            actifs = [mo for mo in m.motor_state if mo.temperature[0] > 0 or mo.q != 0.0]
            temp_max = max((max(mo.temperature) for mo in m.motor_state), default=0)
            n0, t0 = lecteur.nb, time.time()
            time.sleep(0.5)
            frequence = (lecteur.nb - n0) / (time.time() - t0)
            print(f"\rConnecté ({frequence:4.0f} msg/s)   Roulis {roulis:+6.1f}°  Tangage {tangage:+6.1f}°  "
                  f"Cap {lacet:+7.1f}°   Moteurs actifs {len(actifs):2d}   Temp. max {temp_max:3d} °C   "
                  f"{batterie.texte()} ", end="", flush=True)
            if args.une_fois:
                print()
                return 0
    except KeyboardInterrupt:
        print()
        return 0


if __name__ == "__main__":
    sys.exit(main())
