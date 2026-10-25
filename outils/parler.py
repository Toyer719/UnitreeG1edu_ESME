#!/usr/bin/env python3
"""Fait parler le PC en français avec Piper (voix hors ligne du futur robot d'accueil).

  g1-parler "Bonjour, je suis le robot d'accueil."
  g1-parler --voix tom --vitesse 0.9 "Suivez-moi."
  g1-parler --fichier bonjour.wav "Bonjour"      enregistre au lieu de jouer
"""
import argparse
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

from piper import PiperVoice, SynthesisConfig

DOSSIER_VOIX = Path(__file__).resolve().parents[1] / "modeles" / "piper"
VOIX = {"siwis": "fr_FR-siwis-medium", "tom": "fr_FR-tom-medium"}


def synthetiser(texte, voix, vitesse, chemin):
    modele = PiperVoice.load(str(DOSSIER_VOIX / f"{VOIX[voix]}.onnx"))
    # length_scale > 1 ralentit la voix : on l'inverse pour parler de « vitesse »
    reglage = SynthesisConfig(length_scale=1.0 / vitesse)
    with wave.open(str(chemin), "wb") as wav:
        modele.synthesize_wav(texte, wav, syn_config=reglage)


def main():
    p = argparse.ArgumentParser(description="Faire parler le PC en français (Piper).")
    p.add_argument("texte")
    p.add_argument("--voix", choices=VOIX, default="siwis", help="siwis (femme, défaut) ou tom (homme)")
    p.add_argument("--vitesse", type=float, default=1.0, help="1.0 = normal, 0.8 = plus lent, 1.2 = plus rapide")
    p.add_argument("--fichier", type=Path, help="enregistrer dans ce fichier .wav au lieu de jouer")
    args = p.parse_args()

    if args.fichier:
        synthetiser(args.texte, args.voix, args.vitesse, args.fichier)
        print(f"Enregistré : {args.fichier}")
        return 0
    with tempfile.NamedTemporaryFile(suffix=".wav") as f:
        synthetiser(args.texte, args.voix, args.vitesse, f.name)
        return subprocess.call(["paplay", f.name])


if __name__ == "__main__":
    sys.exit(main())
