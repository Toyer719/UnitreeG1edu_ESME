#!/usr/bin/env python3
"""LE PROJET - G1 robot d'accueil JPO : detection de personnes YOLO + memoire des visages.

Lancement :
    cd ~/unitree/perception && .venv/bin/python detect_personnes.py
Options utiles :
    --source 0          index webcam (ou chemin video / URL flux)
    --model yolo11n.pt  n = rapide CPU ; s/m = plus precis mais plus lent
    --conf 0.5          seuil de confiance YOLO
    --seuil 0.38        seuil de ressemblance des visages (plus haut = plus strict)
    --fps 10            cadence de traitement (10 = cameras du G1 ; 0 = aussi vite que possible)
    --debug             affiche chaque decision de la memoire (taille, qualite, similarites)
    --imgsz 640         taille d'inference YOLO (416 = plus rapide mais perd les gens au loin)
    --largeur 1280 --hauteur 720   resolution camera (MJPG) ; plus grand = visages reconnus plus loin
    --sans-memoire      desactive la reconnaissance faciale (ids du tracker seuls)
    --headless N        sans fenetre : traite N images et sauve la derniere
Touches : q / Echap = quitter, s = capture, r = oublier tout le monde.

Couleurs : vert = personne reconnue (P1, P2...), orange = visage pas encore vu (?).
La memoire est uniquement en RAM : rien n'est enregistre sur disque.
"""
import argparse
import time
from pathlib import Path

import cv2
from ultralytics import YOLO

PERSON = 0  # classe COCO "person"
ICI = Path(__file__).parent
VERT, ORANGE, ROUGE, BLEU = (0, 200, 0), (0, 165, 255), (0, 0, 255), (255, 150, 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="0")
    ap.add_argument("--model", default="yolo11n.pt")
    ap.add_argument("--conf", type=float, default=0.5)
    ap.add_argument("--seuil", type=float, default=0.38)
    ap.add_argument("--fps", type=float, default=10)
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--sans-memoire", action="store_true")
    ap.add_argument("--largeur", type=int, default=1280)
    ap.add_argument("--hauteur", type=int, default=720)
    ap.add_argument("--headless", type=int, default=0)
    args = ap.parse_args()

    src = int(args.source) if args.source.isdigit() else args.source
    if isinstance(src, int):
        cap = cv2.VideoCapture(src, cv2.CAP_V4L2)
        # MJPG obligatoire : en YUYV la webcam tombe a 10 FPS des 1280x720
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.largeur)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.hauteur)
        cap.set(cv2.CAP_PROP_FPS, 30)
    else:
        cap = cv2.VideoCapture(src)
    if not cap.isOpened():
        raise SystemExit(f"Impossible d'ouvrir la source {args.source}")
    print(f"camera : {int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))} "
          f"@ {cap.get(cv2.CAP_PROP_FPS):.0f} FPS annonces")

    model = YOLO(str(ICI / args.model) if (ICI / args.model).exists() else args.model)
    memoire = None
    if not args.sans_memoire:
        from memoire_visages import MemoireVisages
        memoire = MemoireVisages(seuil=args.seuil, debug=args.debug)
    tracker = str(ICI / "tracker_accueil.yaml")

    fps, t_prev, n = 0.0, time.time(), 0
    periode = 1.0 / args.fps if args.fps > 0 else 0.0
    t_suivante = time.time()
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        # simule la cadence des cameras du G1 : on lit tout (image fraiche) mais on ne traite
        # qu'une image toutes les `periode` secondes
        if periode and time.time() < t_suivante:
            continue
        # pas de rafale de rattrapage apres une image lente : au moins 0.9 periode entre 2 images
        t_suivante = max(t_suivante + periode, time.time() + 0.9 * periode)
        t_img = time.time()                       # FPS mesure au debut de chaque image traitee
        fps = 0.9 * fps + 0.1 / max(t_img - t_prev, 1e-6)
        t_prev = t_img
        res = model.track(frame, persist=True, tracker=tracker, classes=[PERSON],
                          conf=args.conf, imgsz=args.imgsz, verbose=False)[0]
        b = res.boxes
        tids = b.id.int().tolist() if b.id is not None else []
        boxes = b.xyxy.int().tolist() if b.id is not None else []
        pistes = list(zip(tids, boxes))

        if memoire is not None:
            ident, events = memoire.update(frame, pistes)
            for e in events:
                print(e)
        else:
            ident = {tid: (tid, None) for tid in tids}

        for tid, (x1, y1, x2, y2) in pistes:
            pid, fbox = ident.get(tid, (None, None))
            coul = VERT if pid is not None else ORANGE
            label = f"P{pid}" if pid is not None else f"? (piste {tid})"
            cv2.rectangle(frame, (x1, y1), (x2, y2), coul, 2)
            cv2.putText(frame, label, (x1, max(18, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, coul, 2)
            if fbox is not None:
                fx, fy, fw, fh = fbox
                cv2.rectangle(frame, (fx, fy), (fx + fw, fy + fh), BLEU, 1)

        now = time.time()
        connus = len(memoire.galerie) if memoire is not None else "-"
        hud = f"a l'ecran: {len(pistes)} | personnes memorisees: {connus} | {fps:.1f} FPS"
        cv2.putText(frame, hud, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, ROUGE, 2)

        n += 1
        if args.headless:
            if n >= args.headless:
                cv2.imwrite(str(ICI / "capture_headless.jpg"), frame)
                print(hud)
                break
            continue
        cv2.imshow("G1 accueil - detection personnes", frame)
        k = cv2.waitKey(1) & 0xFF
        if k in (ord("q"), 27):
            break
        if k == ord("s"):
            name = str(ICI / f"capture_{int(now)}.jpg")
            cv2.imwrite(name, frame)
            print("capture ->", name)
        if k == ord("r") and memoire is not None:
            memoire.oublie_tout()
            print("[!] memoire effacee")

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
