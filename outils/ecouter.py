#!/usr/bin/env python3
"""Transcrit en direct ce que vous dites au micro (Vosk, français, hors ligne).

  g1-ecouter                      micro du PC, Ctrl+C pour arrêter
  g1-ecouter --fichier phrase.wav transcrit un fichier
  g1-ecouter --whisper --fichier phrase.wav   même chose avec faster-whisper (plus précis, plus lent)
"""
import argparse
import json
import queue
import sys
import wave
from pathlib import Path

MODELES = Path(__file__).resolve().parents[1] / "modeles"
MODELE_VOSK = MODELES / "vosk" / "vosk-model-small-fr-0.22"
FREQUENCE = 16000


def vosk_fichier(chemin):
    from vosk import KaldiRecognizer, Model, SetLogLevel
    SetLogLevel(-1)
    with wave.open(str(chemin)) as wav:
        rec = KaldiRecognizer(Model(str(MODELE_VOSK)), wav.getframerate())
        while data := wav.readframes(4000):
            rec.AcceptWaveform(data)
    return json.loads(rec.FinalResult())["text"]


def whisper_fichier(chemin):
    import os
    os.environ.setdefault("HF_HOME", str(MODELES / "whisper"))
    from faster_whisper import WhisperModel
    modele = WhisperModel("small", device="cpu", compute_type="int8")
    segments, _ = modele.transcribe(str(chemin), language="fr", vad_filter=True)
    return " ".join(s.text.strip() for s in segments)


def vosk_micro():
    import sounddevice as sd
    from vosk import KaldiRecognizer, Model, SetLogLevel
    SetLogLevel(-1)
    rec = KaldiRecognizer(Model(str(MODELE_VOSK)), FREQUENCE)
    blocs = queue.Queue()
    print("Parlez… (Ctrl+C pour arrêter)")
    with sd.RawInputStream(samplerate=FREQUENCE, blocksize=8000, dtype="int16", channels=1,
                           callback=lambda data, *_: blocs.put(bytes(data))):
        while True:
            if rec.AcceptWaveform(blocs.get()):
                texte = json.loads(rec.Result())["text"]
                if texte:
                    print(f"\r> {texte}" + " " * 20)
            else:
                partiel = json.loads(rec.PartialResult())["partial"]
                print(f"\r  {partiel[-70:]}", end="", flush=True)


def main():
    p = argparse.ArgumentParser(description="Reconnaissance vocale en français, hors ligne.")
    p.add_argument("--fichier", type=Path, help="transcrire un fichier .wav au lieu du micro")
    p.add_argument("--whisper", action="store_true", help="utiliser faster-whisper (fichier seulement)")
    args = p.parse_args()
    try:
        if args.fichier:
            print(whisper_fichier(args.fichier) if args.whisper else vosk_fichier(args.fichier))
        else:
            vosk_micro()
    except KeyboardInterrupt:
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
