"""Lecture d'une manette de jeu, partagée par la simulation et le vrai robot.

Disposition Xbox : manette Xbox, Logitech F310 en mode X, ou PS4/PS5
(sur PlayStation, A = croix, B = rond, LB = L1).
"""
import os
from dataclasses import dataclass

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
# Sans ceci, pygame intercepte Ctrl+C et le programme ne s'arrête plus
os.environ["SDL_NO_SIGNAL_HANDLERS"] = "1"
import pygame  # noqa: E402

# Indices sous Linux (pilotes xpad et hid-playstation)
AXE_GAUCHE_X = 0
AXE_GAUCHE_Y = 1
AXE_DROIT_X = 3
BOUTON_A = 0
BOUTON_B = 1
BOUTON_LB = 4
ZONE_MORTE = 0.12


@dataclass
class EtatManette:
    avant: float      # stick gauche haut/bas, +1 = vers l'avant
    gauche: float     # stick gauche gauche/droite, +1 = vers la gauche
    rotation: float   # stick droit gauche/droite, +1 = tourner à gauche
    a: bool
    b: bool
    lb: bool


def _zone_morte(v):
    return 0.0 if abs(v) < ZONE_MORTE else v


def manette_presente():
    pygame.init()
    pygame.joystick.init()
    return pygame.joystick.get_count() > 0


class Manette:
    def __init__(self):
        pygame.init()
        pygame.joystick.init()
        self.js = None
        self._connecter()

    def _connecter(self):
        if pygame.joystick.get_count() > 0:
            self.js = pygame.joystick.Joystick(0)
            self.js.init()

    @property
    def nom(self):
        return self.js.get_name() if self.js else None

    def lire(self):
        """Renvoie un EtatManette, ou None si aucune manette n'est branchée."""
        for ev in pygame.event.get():
            if ev.type == pygame.JOYDEVICEREMOVED:
                self.js = None
            elif ev.type == pygame.JOYDEVICEADDED and self.js is None:
                self._connecter()
        if self.js is None:
            return None
        return EtatManette(
            avant=-_zone_morte(self.js.get_axis(AXE_GAUCHE_Y)),
            gauche=-_zone_morte(self.js.get_axis(AXE_GAUCHE_X)),
            rotation=-_zone_morte(self.js.get_axis(AXE_DROIT_X)),
            a=bool(self.js.get_button(BOUTON_A)),
            b=bool(self.js.get_button(BOUTON_B)),
            lb=bool(self.js.get_button(BOUTON_LB)),
        )
