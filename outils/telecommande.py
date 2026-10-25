#!/usr/bin/env python3
"""Affiche ce que le G1 reçoit de sa télécommande Unitree : sticks et boutons.

  g1-telecommande                 vrai robot (robot.sh lancé avant dans ce terminal)
  g1-telecommande lo              simulateur g1-sim : la manette fait office de télécommande
  g1-telecommande --diagnostic    enregistre 15 s dans ~/robot-g1/docs/releves/ pour Claude :
                                  bougez les deux sticks et appuyez sur A et B pendant ce temps

Le robot peut transmettre la télécommande à deux endroits : le sujet rt/wirelesscontroller,
et le champ wireless_remote de l'état du robot (rt/lowstate). On écoute les deux.
Le décodage de wireless_remote reprend l'exemple officiel unitree_sdk2_python/example/wireless_controller.
"""
import argparse
import struct
import sys
import time
from datetime import datetime
from pathlib import Path

from unitree_sdk2py.core.channel import ChannelSubscriber
from unitree_sdk2py.idl.unitree_go.msg.dds_ import WirelessController_

from connexion import connecter

# Un bit par bouton, dans l'ordre des octets 2 et 3 de wireless_remote (et des 16 bits de « keys »)
BOUTONS = ["R1", "L1", "Start", "Select", "R2", "L2", "F1", "F3",
           "A", "B", "X", "Y", "Haut", "Droite", "Bas", "Gauche"]
DOSSIER_RELEVES = Path.home() / "robot-g1" / "docs" / "releves"


def boutons(bits):
    return [nom for i, nom in enumerate(BOUTONS) if bits >> i & 1]


def decoder_etat(octets):
    """wireless_remote de l'état du robot → (lx, ly, rx, ry, boutons)."""
    donnees = bytes(octets)
    lx, rx, ry, _, ly = struct.unpack_from("<5f", donnees, 4)
    return lx, ly, rx, ry, boutons(donnees[2] | donnees[3] << 8)


class Ecoute:
    def __init__(self, lecteur):
        self.lecteur = lecteur
        self.dernier_wc = None
        self.nb_wc = 0
        self.abonnement = ChannelSubscriber("rt/wirelesscontroller", WirelessController_)
        self.abonnement.Init(self.recevoir_wc, 10)

    def recevoir_wc(self, msg):
        self.dernier_wc = msg
        self.nb_wc += 1

    def lire(self):
        """Renvoie (source, lx, ly, rx, ry, boutons), ou None si aucune télécommande n'est vue."""
        if self.dernier_wc is not None:
            m = self.dernier_wc
            return ("rt/wirelesscontroller", m.lx, m.ly, m.rx, m.ry, boutons(m.keys))
        octets = bytes(self.lecteur.dernier.wireless_remote)
        if any(octets):
            return ("état du robot",) + decoder_etat(octets)
        return None


def diagnostic(ecoute, duree):
    print(f"Pendant {duree:.0f} s : bougez les deux sticks dans tous les sens et appuyez sur A, puis sur B.")
    debut, nb_etat0 = time.time(), ecoute.lecteur.nb
    octets_vus, max_etat, max_wc, boutons_vus = set(), [0.0] * 4, [0.0] * 4, set()
    while time.time() - debut < duree:
        octets = bytes(ecoute.lecteur.dernier.wireless_remote)
        octets_vus |= {i for i, x in enumerate(octets) if x}
        if any(octets):
            lx, ly, rx, ry, b = decoder_etat(octets)
            max_etat = [max(a, abs(v)) for a, v in zip(max_etat, (lx, ly, rx, ry))]
            boutons_vus |= set(b)
        if ecoute.dernier_wc is not None:
            m = ecoute.dernier_wc
            max_wc = [max(a, abs(v)) for a, v in zip(max_wc, (m.lx, m.ly, m.rx, m.ry))]
            boutons_vus |= set(boutons(m.keys))
        restant = duree - (time.time() - debut)
        print(f"\r  encore {restant:4.1f} s", end="", flush=True)
        time.sleep(0.02)
    print()
    lignes = [
        f"=== Diagnostic de la télécommande, {datetime.now():%d/%m/%Y %H:%M}, {duree:.0f} s",
        f"État du robot (rt/lowstate) : {ecoute.lecteur.nb - nb_etat0} messages, "
        f"octets non nuls de wireless_remote : {sorted(octets_vus) or 'aucun'}",
        f"  sticks maximum lx ly rx ry : {' '.join(f'{v:.2f}' for v in max_etat)}",
        f"rt/wirelesscontroller : {ecoute.nb_wc} messages",
        f"  sticks maximum lx ly rx ry : {' '.join(f'{v:.2f}' for v in max_wc)}",
        f"Boutons vus : {', '.join(sorted(boutons_vus)) or 'aucun'}",
    ]
    DOSSIER_RELEVES.mkdir(parents=True, exist_ok=True)
    fichier = DOSSIER_RELEVES / f"telecommande_{datetime.now():%Y-%m-%d_%Hh%M}.txt"
    fichier.write_text("\n".join(lignes) + "\n")
    print("\n".join(lignes))
    print(f"\nEnregistré dans {fichier}. Dites à Claude « diagnostic fait ».")


def main():
    p = argparse.ArgumentParser(description="État de la télécommande Unitree vu par le robot.")
    p.add_argument("interface", nargs="?", default="eno2", help="eno2 (robot, défaut) ou lo (simulateur)")
    p.add_argument("--une-fois", action="store_true", help="affiche une mesure puis quitte")
    p.add_argument("--diagnostic", nargs="?", type=float, const=15.0, metavar="SECONDES",
                   help="enregistre ce qui arrive pendant 15 s (ou la durée donnée) pour Claude")
    args = p.parse_args()

    lecteur = connecter(args.interface)
    if lecteur is None:
        return 1
    ecoute = Ecoute(lecteur)
    time.sleep(0.5)
    if args.diagnostic:
        diagnostic(ecoute, args.diagnostic)
        return 0
    try:
        while True:
            vu = ecoute.lire()
            if vu is None:
                ligne = "Aucune donnée de télécommande reçue : télécommande allumée et reliée au robot ?"
            else:
                source, lx, ly, rx, ry, appuyes = vu
                ligne = (f"Stick gauche x {lx:+.2f} y {ly:+.2f}   Stick droit x {rx:+.2f} y {ry:+.2f}   "
                         f"Boutons : {', '.join(appuyes) or 'aucun':<20} ({source})")
            print(f"\r{ligne:<110}", end="", flush=True)
            if args.une_fois:
                print()
                return 0
            time.sleep(0.1)
    except KeyboardInterrupt:
        print()
        return 0


if __name__ == "__main__":
    sys.exit(main())
