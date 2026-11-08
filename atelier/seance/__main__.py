"""g1-seance (vague 6, section 13.3 du plan) : squelette, écrit par l'agent Boîte noire."""
import sys

from . import MESSAGE_PAS_ENCORE_FAIT

if __name__ == "__main__":
    print(MESSAGE_PAS_ENCORE_FAIT.format(quoi="g1-seance"), file=sys.stderr)
    sys.exit(1)
