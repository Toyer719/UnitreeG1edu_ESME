#!/usr/bin/env python3
"""Détecte et suit les personnes avec YOLO (pose) et ByteTrack.

  g1-personnes                 webcam du PC (touche q pour quitter)
  g1-personnes --source 2      autre caméra (/dev/video2, par exemple la RealSense)
  g1-personnes --source photo.jpg --sans-fenetre    compte les personnes d'une image
"""
import argparse
import sys
from pathlib import Path

import cv2
import torch
from ultralytics import YOLO

MODELE = Path(__file__).resolve().parents[1] / "modeles" / "yolo" / "yolo11n-pose.pt"


def main():
    p = argparse.ArgumentParser(description="Détection et suivi de personnes (YOLO + ByteTrack).")
    p.add_argument("--source", default="0", help="numéro de caméra (0 = webcam) ou chemin d'image / vidéo")
    p.add_argument("--sans-fenetre", action="store_true", help="affiche seulement le nombre de personnes")
    args = p.parse_args()

    source = int(args.source) if args.source.isdigit() else args.source
    appareil = 0 if torch.cuda.is_available() else "cpu"
    print(f"Calcul sur : {'carte graphique ' + torch.cuda.get_device_name(0) if appareil == 0 else 'processeur'}")
    modele = YOLO(str(MODELE))
    flux = modele.track(source=source, stream=True, classes=[0], tracker="bytetrack.yaml",
                        device=appareil, verbose=False)
    for r in flux:
        ids = [] if r.boxes.id is None else r.boxes.id.int().tolist()
        if args.sans_fenetre:
            print(f"{len(r.boxes)} personne(s) détectée(s), identifiants de suivi : {ids}")
            continue
        image = r.plot()
        cv2.putText(image, f"{len(r.boxes)} personne(s) - q pour quitter", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        cv2.imshow("Personnes", image)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break
    cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    sys.exit(main())
