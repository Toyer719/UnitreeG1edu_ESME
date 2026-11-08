"""g1-voix (vague 6, section 13.6 du plan) : squelette, écrit par l'agent Voix."""
import sys

from . import MESSAGE_PAS_ENCORE_FAIT

if __name__ == "__main__":
    print(MESSAGE_PAS_ENCORE_FAIT.format(quoi="le nœud voix (g1-voix)"), file=sys.stderr)
    sys.exit(1)
