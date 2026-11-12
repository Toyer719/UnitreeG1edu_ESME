#!/usr/bin/env python3
"""Manette virtuelle : une fenêtre qui se comporte comme une manette Xbox branchée.

Les autres programmes (g1-sim-marche, g1-sim, g1-manette, jstest, ROS 2) la voient
comme une vraie manette. Lancez-la avant eux, et gardez sa fenêtre active pour le clavier.

  Stick gauche   Z Q S D, ou glisser à la souris
  Stick droit    flèches gauche / droite, ou glisser à la souris
  A              touche A ou Espace (relever le robot dans g1-sim-marche, coucou sur le robot)
  B              touche B (stop)
  LB             Maj gauche maintenue (homme mort de g1-manette)
"""
import argparse
import math
import os
import sys
import time

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
os.environ["SDL_NO_SIGNAL_HANDLERS"] = "1"  # garder Ctrl+C
import pygame  # noqa: E402
from evdev import AbsInfo, UInput, UInputError, ecodes as e  # noqa: E402

NOM = "Manette virtuelle G1"
MAX = 32767
# Même ordre que le pilote xpad : A=0, B=1, X=2, Y=3, LB=4, RB=5, Select=6, Start=7
BOUTONS = [e.BTN_A, e.BTN_B, e.BTN_X, e.BTN_Y, e.BTN_TL, e.BTN_TR,
           e.BTN_SELECT, e.BTN_START, e.BTN_MODE, e.BTN_THUMBL, e.BTN_THUMBR]
AIDE_PERMISSION = ("La manette virtuelle n'a pas le droit de se créer.\n"
                   "Activez-la une fois (mot de passe demandé) :\n"
                   "  sudo bash ~/robot-g1/setup/activer_manette_virtuelle.sh")

LARGEUR, HAUTEUR = 720, 400
RAYON = 70
CENTRES = {"gauche": (180, 210), "droit": (540, 210)}
ZONES_BOUTONS = {"a": (380, 140), "b": (440, 90), "lb": (180, 60)}
FOND, SOCLE, BORD, TEXTE, DISCRET = (16, 25, 29), (27, 42, 48), (61, 191, 180), (226, 235, 236), (151, 170, 176)
COULEURS = {"a": (93, 193, 132), "b": (236, 122, 108), "lb": (130, 168, 219)}


def creer_manette():
    stick = AbsInfo(value=0, min=-32768, max=MAX, fuzz=16, flat=128, resolution=0)
    gachette = AbsInfo(value=0, min=0, max=255, fuzz=0, flat=0, resolution=0)
    croix = AbsInfo(value=0, min=-1, max=1, fuzz=0, flat=0, resolution=0)
    capacites = {
        e.EV_KEY: BOUTONS,
        e.EV_ABS: [(e.ABS_X, stick), (e.ABS_Y, stick), (e.ABS_Z, gachette), (e.ABS_RX, stick),
                   (e.ABS_RY, stick), (e.ABS_RZ, gachette), (e.ABS_HAT0X, croix), (e.ABS_HAT0Y, croix)],
    }
    return UInput(capacites, name=NOM, vendor=0x045E, product=0x028E, version=0x110, bustype=e.BUS_USB)


class Etat:
    """Position des sticks (x vers la droite, y vers le bas, entre -1 et 1) et boutons."""

    def __init__(self):
        self.sticks = {"gauche": [0.0, 0.0], "droit": [0.0, 0.0]}
        self.boutons = {"a": False, "b": False, "lb": False}

    def envoyer(self, manette):
        for nom, (ax, ay) in (("gauche", (e.ABS_X, e.ABS_Y)), ("droit", (e.ABS_RX, e.ABS_RY))):
            x, y = self.sticks[nom]
            manette.write(e.EV_ABS, ax, int(x * MAX))
            manette.write(e.EV_ABS, ay, int(y * MAX))
        for nom, code in (("a", e.BTN_A), ("b", e.BTN_B), ("lb", e.BTN_TL)):
            manette.write(e.EV_KEY, code, int(self.boutons[nom]))
        manette.syn()


def borner(x, y):
    n = math.hypot(x, y)
    return (x / n, y / n) if n > 1 else (x, y)


def lire_clavier(etat, souris_stick):
    t = pygame.key.get_pressed()
    if souris_stick != "gauche":
        etat.sticks["gauche"] = list(borner(t[pygame.K_d] - t[pygame.K_q], t[pygame.K_s] - t[pygame.K_z]))
    if souris_stick != "droit":
        etat.sticks["droit"] = [float(t[pygame.K_RIGHT] - t[pygame.K_LEFT]), float(t[pygame.K_DOWN] - t[pygame.K_UP])]


def dessiner(ecran, police, petite, etat):
    ecran.fill(FOND)
    for nom, (cx, cy) in CENTRES.items():
        pygame.draw.circle(ecran, SOCLE, (cx, cy), RAYON)
        pygame.draw.circle(ecran, BORD, (cx, cy), RAYON, 2)
        x, y = etat.sticks[nom]
        pygame.draw.circle(ecran, BORD, (int(cx + x * RAYON * 0.75), int(cy + y * RAYON * 0.75)), 26)
        legende = "Z Q S D" if nom == "gauche" else "← →"
        ecran.blit(petite.render(f"Stick {nom} · {legende}", True, DISCRET), (cx - 70, cy + RAYON + 12))
    for nom, (bx, by) in ZONES_BOUTONS.items():
        appuye = etat.boutons[nom]
        couleur = COULEURS[nom]
        if nom == "lb":
            rect = pygame.Rect(bx - 60, by - 18, 120, 36)
            pygame.draw.rect(ecran, couleur if appuye else SOCLE, rect, border_radius=10)
            pygame.draw.rect(ecran, couleur, rect, 2, border_radius=10)
            ecran.blit(police.render("LB", True, FOND if appuye else couleur), (bx - 13, by - 12))
            ecran.blit(petite.render("Maj gauche", True, DISCRET), (bx + 70, by - 8))
        else:
            pygame.draw.circle(ecran, couleur if appuye else SOCLE, (bx, by), 24)
            pygame.draw.circle(ecran, couleur, (bx, by), 24, 2)
            ecran.blit(police.render(nom.upper(), True, FOND if appuye else couleur), (bx - 8, by - 12))
    ecran.blit(petite.render("A : touche A ou Espace    B : touche B    Ctrl+C dans le terminal pour quitter",
                             True, DISCRET), (20, HAUTEUR - 32))
    ecran.blit(police.render(NOM, True, TEXTE), (LARGEUR - 250, 20))
    pygame.display.flip()


def tester():
    """Crée la manette, pousse le stick gauche vers l'avant et appuie sur A et LB, puis relit."""
    manette = creer_manette()
    etat = Etat()
    etat.sticks["gauche"] = [0.0, -1.0]
    etat.boutons["a"] = etat.boutons["lb"] = True
    time.sleep(1.0)  # laisser le système créer /dev/input/js*
    pygame.init()
    pygame.joystick.init()
    # SDL renomme la manette « Xbox 360 Controller » : on la reconnaît à son identifiant
    # (USB, Microsoft 045e, produit 028e, version 0110)
    js = next((pygame.joystick.Joystick(i) for i in range(pygame.joystick.get_count())
               if pygame.joystick.Joystick(i).get_guid().endswith("5e0400008e02000010010000")), None)
    if js is None:
        print("Échec : la manette virtuelle n'est pas vue par pygame.")
        return 1
    js.init()
    etat.envoyer(manette)
    time.sleep(0.2)
    pygame.event.pump()
    avant, a, lb = js.get_axis(1), js.get_button(0), js.get_button(4)
    manette.close()
    ok = avant < -0.9 and a == 1 and lb == 1
    print(f"{'OK' if ok else 'ÉCHEC'} : stick gauche avant = {avant:+.2f}, A = {a}, LB = {lb}")
    return 0 if ok else 1


def main():
    p = argparse.ArgumentParser(description="Manette virtuelle vue par le système comme une manette Xbox.")
    p.add_argument("--test", action="store_true", help="vérifie sans fenêtre que la manette est bien vue")
    args = p.parse_args()

    try:
        if args.test:
            return tester()
        manette = creer_manette()
    except (UInputError, PermissionError, OSError):
        print(AIDE_PERMISSION)
        return 1

    pygame.init()
    ecran = pygame.display.set_mode((LARGEUR, HAUTEUR))
    pygame.display.set_caption(NOM)
    police = pygame.font.SysFont(None, 34)
    petite = pygame.font.SysFont(None, 22)
    horloge = pygame.time.Clock()
    etat = Etat()
    souris_stick = None  # stick tenu à la souris
    souris_bouton = None
    print(__doc__.split("\n\n", 1)[1])

    try:
        while True:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    return 0
                if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                    for nom, (cx, cy) in CENTRES.items():
                        if math.hypot(ev.pos[0] - cx, ev.pos[1] - cy) <= RAYON:
                            souris_stick = nom
                    for nom, (bx, by) in ZONES_BOUTONS.items():
                        if math.hypot(ev.pos[0] - bx, ev.pos[1] - by) <= (40 if nom == "lb" else 26):
                            souris_bouton = nom
                elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
                    if souris_stick:
                        etat.sticks[souris_stick] = [0.0, 0.0]
                    souris_stick = souris_bouton = None
            if souris_stick:
                cx, cy = CENTRES[souris_stick]
                mx, my = pygame.mouse.get_pos()
                etat.sticks[souris_stick] = list(borner((mx - cx) / (RAYON * 0.75), (my - cy) / (RAYON * 0.75)))
            lire_clavier(etat, souris_stick)
            t = pygame.key.get_pressed()
            etat.boutons["a"] = bool(t[pygame.K_a] or t[pygame.K_SPACE]) or souris_bouton == "a"
            etat.boutons["b"] = bool(t[pygame.K_b]) or souris_bouton == "b"
            etat.boutons["lb"] = bool(t[pygame.K_LSHIFT]) or souris_bouton == "lb"
            etat.envoyer(manette)
            dessiner(ecran, police, petite, etat)
            horloge.tick(60)
    except KeyboardInterrupt:
        return 0
    finally:
        manette.close()
        pygame.quit()


if __name__ == "__main__":
    sys.exit(main())
