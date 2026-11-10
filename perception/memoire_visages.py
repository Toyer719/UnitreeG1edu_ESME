"""Memoire des personnes par reconnaissance faciale (OpenCV YuNet + SFace).

Principe :
- le tracker YOLO donne un id de piste (tid) qui ne vit que tant que la personne est visible ;
- on cherche un visage dans la boite de la personne, on en calcule une signature (128 nombres) ;
- on compare a la galerie des personnes deja vues -> identifiant persistant "P1, P2..." ;
- galerie EN MEMOIRE uniquement (rien sur disque) : effacee a la fermeture du programme.

Regles anti-doublons (v3) :
1. Periode d'observation : une NOUVELLE personne n'est creee qu'apres `vues_creation` vues
   de BONNE qualite (visage >= taille_creation px, score YuNet eleve, quasi de face) qui ne
   ressemblent a personne. Une seule image ratee (profil, flou) ne cree plus de doublon.
2. Petits visages / profils : peuvent RECONNAITRE quelqu'un, jamais CREER ni enrichir la galerie.
3. Fusion : si un visage ressemble fortement a DEUX personnes de la galerie, c'etait un doublon
   -> on fusionne dans la plus ancienne.
4. Un visage deja porte par une autre piste visible (voisin dans la boite) est ignore.
"""
import time
from pathlib import Path

import cv2
import numpy as np

MODELS = Path(__file__).parent / "models"
SFACE_SEUIL = 0.363   # seuil cosinus recommande par OpenCV pour SFace (meme personne si >)


class MemoireVisages:
    def __init__(self, seuil=0.38, score_visage=0.7, taille_min=16, taille_creation=48,
                 score_creation=0.85, vues_creation=3, marge_fusion=0.08,
                 max_signatures=30, recheck_s=0.5, zone_cible=160, debug=False):
        self.det = cv2.FaceDetectorYN.create(
            str(MODELS / "face_detection_yunet_2023mar.onnx"), "", (320, 320), score_visage)
        self.rec = cv2.FaceRecognizerSF.create(str(MODELS / "face_recognition_sface_2021dec.onnx"), "")
        self.seuil = max(seuil, SFACE_SEUIL)
        self.taille_min = taille_min            # plus petit visage exploite (px, image d'origine)
        self.taille_creation = taille_creation  # visage minimal pour creer / enrichir
        self.score_creation = score_creation    # score YuNet minimal pour creer / enrichir
        self.vues_creation = vues_creation      # nb de bonnes vues inconnues avant de creer
        self.seuil_fusion = self.seuil + marge_fusion
        self.max_signatures = max_signatures
        self.recheck_s = recheck_s              # re-verifie une piste identifiee toutes les N s
        self.zone_cible = zone_cible            # largeur visee de la zone visage apres agrandissement
        self.debug = debug
        self.galerie = {}                       # pid -> {"sig": [vecteurs], "vu": t, "premiere": t}
        self.piste_pid = {}                     # tid -> pid
        self.piste_verif = {}                   # tid -> instant de la derniere verification
        self.attente = {}                       # tid -> [signatures] (piste inconnue en observation)
        self.prochain = 1

    # -- visage -> signature -------------------------------------------------
    def signature(self, frame, box):
        """Retourne (signature, bbox_visage, infos) ou (None, None, None).
        infos = {"taille": px, "score": YuNet, "face": ratio nez/yeux (0.5 = parfaitement de face)}"""
        x1, y1, x2, y2 = box
        w, h = x2 - x1, y2 - y1
        # visage = haut de la personne ; si la boite est un buste (personne proche) on prend plus
        haut = 0.6 if h > 1.6 * w else 0.9
        mx, my = int(0.1 * w) + 4, int(0.1 * w) + 4
        cx1, cy1 = max(0, x1 - mx), max(0, y1 - my)
        cx2, cy2 = min(frame.shape[1], x2 + mx), min(frame.shape[0], y1 + int(haut * h) + my)
        crop = frame[cy1:cy2, cx1:cx2]
        if crop.shape[0] < 8 or crop.shape[1] < 8:
            return None, None, None
        # agrandit les petites zones pour que YuNet trouve les visages lointains
        k = min(4.0, max(1.0, self.zone_cible / crop.shape[1]))
        if k > 1.0:
            crop = cv2.resize(crop, None, fx=k, fy=k, interpolation=cv2.INTER_CUBIC)
        self.det.setInputSize((crop.shape[1], crop.shape[0]))
        _, faces = self.det.detect(crop)
        if faces is None or len(faces) == 0:
            return None, None, None
        # le visage de CETTE personne = le plus proche du centre-haut de sa boite
        # (la zone peut contenir le visage d'un voisin)
        ox, oy = (x1 + x2) / 2 - cx1, y1 - cy1 + 0.12 * h
        f = min(faces, key=lambda r: (r[0] / k + r[2] / (2 * k) - ox) ** 2
                + (r[1] / k + r[3] / (2 * k) - oy) ** 2)
        fcx = f[0] / k + f[2] / (2 * k) + cx1
        if not (x1 <= fcx <= x2):                     # visage hors de la boite : c'est un voisin
            return None, None, None
        taille = min(f[2], f[3]) / k                  # taille dans l'image d'origine
        if taille < self.taille_min:
            return None, None, None
        # de face ? position du nez entre les deux yeux (0.5 = de face, 0 ou 1 = profil)
        oeil_a, oeil_b, nez = f[4], f[6], f[8]
        ecart = oeil_b - oeil_a
        face = float((nez - oeil_a) / ecart) if abs(ecart) > 1e-3 else 0.0
        aligne = self.rec.alignCrop(crop, f)
        sig = self.rec.feature(aligne).flatten()
        sig = sig / (np.linalg.norm(sig) + 1e-9)
        bbox = (int(f[0] / k) + cx1, int(f[1] / k) + cy1, int(f[2] / k), int(f[3] / k))
        return sig, bbox, {"taille": taille, "score": float(f[14]), "face": face}

    def bonne_vue(self, infos):
        return (infos["taille"] >= self.taille_creation and infos["score"] >= self.score_creation
                and 0.3 <= infos["face"] <= 0.7)

    # -- comparaison -----------------------------------------------------------
    def similarites(self, sig, exclus=()):
        """Liste triee [(sim, pid)] : meilleure ressemblance a chaque personne de la galerie."""
        sims = [(max(float(np.dot(sig, g)) for g in p["sig"]), pid)
                for pid, p in self.galerie.items() if pid not in exclus]
        return sorted(sims, reverse=True)

    def _ajoute_sig(self, pid, sig):
        sigs = self.galerie[pid]["sig"]
        if len(sigs) < self.max_signatures and max(float(np.dot(sig, g)) for g in sigs) < 0.85:
            sigs.append(sig)

    def _fusionne(self, garde, perd, events):
        self.galerie[garde]["sig"].extend(self.galerie[perd]["sig"])
        self.galerie[garde]["sig"] = self.galerie[garde]["sig"][: 2 * self.max_signatures]
        self.galerie[garde]["premiere"] = min(self.galerie[garde]["premiere"],
                                              self.galerie[perd]["premiere"])
        del self.galerie[perd]
        for t, p in self.piste_pid.items():
            if p == perd:
                self.piste_pid[t] = garde
        events.append(f"[~] fusion : P{perd} etait un doublon de P{garde}")

    def _log(self, msg):
        if self.debug:
            print("   dbg", msg)

    # -- appel a chaque image -------------------------------------------------
    def update(self, frame, pistes):
        """pistes: liste de (tid, box). Retourne (dict tid -> (pid|None, bbox_visage|None), evenements)."""
        now = time.time()
        actives = {tid for tid, _ in pistes}
        for d in (self.piste_pid, self.piste_verif, self.attente):   # oublie les pistes disparues
            for tid in [t for t in d if t not in actives]:
                d.pop(tid)

        out, events = {}, []
        for tid, box in pistes:
            pid = self.piste_pid.get(tid)
            if pid is not None and now - self.piste_verif.get(tid, 0) < self.recheck_s:
                self.galerie[pid]["vu"] = now
                out[tid] = (pid, None)
                continue

            self.piste_verif[tid] = now
            sig, fbox, infos = self.signature(frame, box)
            if sig is None:
                out[tid] = (pid, None)
                if pid is not None:
                    self.galerie[pid]["vu"] = now
                continue
            bonne = self.bonne_vue(infos)

            # pids deja portes par une AUTRE piste visible
            pris = {p for t, p in self.piste_pid.items() if t != tid}
            tous = self.similarites(sig)
            if tous and tous[0][1] in pris and tous[0][0] >= self.seuil:
                self._log(f"piste {tid}: visage de P{tous[0][1]} (deja a l'ecran) -> ignore")
                out[tid] = (pid, None)
                continue
            sims = [(s, p) for s, p in tous if p not in pris]
            score, cand = sims[0] if sims else (-1.0, None)
            self._log(f"piste {tid} (P{pid}): visage {infos['taille']:.0f}px score {infos['score']:.2f} "
                      f"face {infos['face']:.2f} {'BONNE' if bonne else 'faible'} | "
                      + ", ".join(f"P{p}={s:.2f}" for s, p in sims[:3]))

            if cand is not None and score >= self.seuil:
                if cand != pid:
                    absent = now - self.galerie[cand]["vu"]
                    events.append(f"[=] P{cand} reconnu(e) (absent {absent:.0f} s, sim {score:.2f}, "
                                  f"visage {infos['taille']:.0f} px)")
                pid = cand
                self.attente.pop(tid, None)
                if bonne:
                    self._ajoute_sig(pid, sig)
                    # ressemble aussi fortement a une autre personne -> doublon a fusionner
                    for s2, p2 in sims[1:]:
                        if s2 >= self.seuil_fusion:
                            garde, perd = min(pid, p2), max(pid, p2)
                            self._fusionne(garde, perd, events)
                            pid = garde
            elif pid is None and bonne:
                obs = self.attente.setdefault(tid, [])
                obs.append(sig)
                if len(obs) >= self.vues_creation:
                    pid = self.prochain
                    self.prochain += 1
                    self.galerie[pid] = {"sig": [obs[0]], "vu": now, "premiere": now}
                    for s in obs[1:]:
                        self._ajoute_sig(pid, s)
                    self.attente.pop(tid)
                    events.append(f"[+] nouvelle personne P{pid} (meilleure sim {score:.2f}, "
                                  f"visage {infos['taille']:.0f} px, {len(obs)} vues)")
            # sinon : vue faible inconnue, ou piste deja identifiee mais vue peu ressemblante
            # -> on garde l'etat actuel sans toucher a la galerie

            if pid is not None:
                self.galerie[pid]["vu"] = now
                self.piste_pid[tid] = pid
            out[tid] = (pid, fbox)
        return out, events

    def oublie_tout(self):
        self.galerie.clear()
        self.piste_pid.clear()
        self.piste_verif.clear()
        self.attente.clear()
        self.prochain = 1
