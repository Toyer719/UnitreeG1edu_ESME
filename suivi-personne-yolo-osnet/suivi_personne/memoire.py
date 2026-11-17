"""Mémoire corporelle d'une cible, indépendante des numéros de piste."""
from collections import deque

import numpy as np


class MemoireCible:
    def __init__(self, seuil=0.78, marge=0.07, confirmations=3):
        self.seuil, self.marge, self.confirmations = seuil, marge, confirmations
        self.effacer()

    def effacer(self):
        self.galerie = deque(maxlen=16)
        self.ancre = None
        self.piste = None
        self.derniere_vue = None
        self.pending = None
        self.compte = 0
        self.dernier_ajout = -1e9

    @staticmethod
    def normaliser(v):
        v = np.asarray(v, dtype=np.float32)
        if v.ndim != 1 or not np.isfinite(v).all() or np.linalg.norm(v) < 1e-8:
            raise ValueError('Signature corporelle invalide')
        return v / np.linalg.norm(v)

    def choisir(self, vecteur, piste, t):
        self.effacer()
        self.ancre = self.normaliser(vecteur).copy()
        self.galerie.append(self.ancre.copy())
        self.piste = piste
        self.derniere_vue = t

    def comparer(self, observations, t):
        """Observations : (id de piste, vecteur OSNet). Pas de position requise.

        Retourne la piste retrouvée seulement après seuil ET marge et confirmation.
        La galerie n'est jamais actualisée pendant une récupération incertaine.
        """
        if self.ancre is None:
            return {'etat': 'selection', 'piste': None, 'score': None, 'marge': None}
        scores = []
        galerie = np.stack([self.ancre, *self.galerie])
        for ident, vector in observations:
            if vector is not None:
                v = self.normaliser(vector)
                score = float(np.max(galerie @ v))
                scores.append((score, ident, v))
        scores.sort(key=lambda x: x[0], reverse=True)
        if not scores:
            self.pending, self.compte = None, 0
            return {'etat': 'perdue', 'piste': None, 'score': None, 'marge': None}
        # Maintien d'une piste visible : seuil plus souple que pour retrouver
        # quelqu'un après une absence. L'ancien ID seul ne suffit jamais.
        continu = self.derniere_vue is not None and t-self.derniere_vue < 1.2
        score, ident, vecteur = scores[0]
        gap = score-scores[1][0] if len(scores) > 1 else 1.0
        result = {'piste': None, 'score': score, 'marge': gap}
        continu = ident == self.piste and continu
        seuil = .60 if continu else self.seuil
        marge = .03 if continu else self.marge
        if score < seuil or gap < marge:
            self.pending, self.compte = None, 0
            return dict(result, etat='ambigue' if gap < self.marge else 'perdue')
        if not continu:
            self.compte = self.compte+1 if ident == self.pending else 1
            self.pending = ident
            if self.compte < self.confirmations:
                return dict(result, etat='verification')
        self.piste, self.derniere_vue = ident, t
        self.pending, self.compte = None, 0
        # Ancre immuable + enrichissement parcimonieux sur observations très proches.
        if score >= 0.88 and float(self.ancre @ vecteur) >= self.seuil and t-self.dernier_ajout > 0.7:
            self.galerie.append(vecteur.copy())
            self.dernier_ajout = t
        return dict(result, etat='visible', piste=ident)
