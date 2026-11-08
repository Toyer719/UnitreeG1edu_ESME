"""g1-diagnostic (vague 6, section 13.2 du plan) : squelette, écrit par l'agent Diagnostic."""
import sys

from . import MESSAGE_PAS_ENCORE_FAIT

if __name__ == "__main__":
    print(MESSAGE_PAS_ENCORE_FAIT.format(quoi="g1-diagnostic"), file=sys.stderr)
    sys.exit(1)
