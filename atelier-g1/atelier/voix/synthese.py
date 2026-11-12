"""Synthèse de la voix du robot sur le PC (vague 6, section 13.6 du plan) : Piper, PCM 16 kHz, WAV.

Sans ROS. Le nœud voix (noeud.py) s'en sert dans un fil à part : une phrase se synthétise en 0,05 à 0,3 s sur
le processeur du PC (mesuré le 09/11/2026 : voir LISEZMOI.md), jamais dans le fil qui reçoit les messages.

  SynthesePiper().synthetiser(texte, voix, vitesse, gain) -> SonPhrase
      Piper (modeles/piper/<voix>.onnx et .onnx.json, .venv-projet), une voix chargée une fois puis gardée ;
      chaque phrase du texte (Piper découpe aux points) est suivie d'un court silence ; le son est coupé à
      DUREE_PHRASE_MAX_S. vitesse : 1,0 normal, 1,2 plus rapide (length_scale = 1 / vitesse) ; gain : 0 à 1,
      appliqué aux échantillons (volume d'une personnalité, ou volume de la sortie borne).
  SonPhrase : echantillons (int16, à la fréquence de la voix : 22 050 Hz pour siwis, 44 100 Hz pour tom),
      pcm16 (le même son rééchantillonné à 16 000 Hz, mono, 16 bits petit-boutiste : ce que reçoit le robot
      par 1003), duree_s, duree_synthese_s.
  SyntheseFactice : même interface, sans Piper (un bip de la longueur de la phrase), pour les essais.

Fonctions : reechantillonner (scipy.signal.resample_poly, sinon interpolation linéaire), pcm_16k, ecrire_wav
(atomique), lire_wav, voix_disponibles, choisir_voix.
"""
import math
import os
import threading
import time
import wave
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from atelier.lieu import voix as V

SILENCE_ENTRE_PHRASES_S = 0.2          # entre deux phrases d'un même texte (Piper les rend une à une)
FREQUENCE_FACTICE_HZ = 22050
DUREE_FACTICE_PAR_CARACTERE_S = 0.065  # la voix d'essai parle à peu près comme Piper (15 caractères par seconde)


class ErreurSynthese(Exception):
    """La phrase n'a pas pu être synthétisée (voix absente, Piper absent, texte vide…), en français."""


@dataclass
class SonPhrase:
    """Le son d'une phrase : à la fréquence de la voix (WAV de la borne) et à 16 kHz (le robot)."""

    echantillons: np.ndarray           # int16, mono
    frequence_hz: int
    pcm16: bytes                       # 16 000 Hz, mono, 16 bits signés petit-boutiste
    voix: str
    vitesse: float = 1.0
    gain: float = 1.0
    duree_synthese_s: float = 0.0
    tronque: bool = False
    phrases: int = 1
    infos: dict = field(default_factory=dict)

    @property
    def duree_s(self):
        """Durée du son, en secondes (à la fréquence de la voix)."""
        return len(self.echantillons) / float(self.frequence_hz)

    @property
    def duree_pcm_s(self):
        """Durée du PCM 16 kHz envoyé au robot."""
        return V.duree_pcm_s(len(self.pcm16))


# ---------------------------------------------------------------- calculs sur le son

def _resample_poly():
    """scipy.signal.resample_poly, ou None (le scipy du système avertit pour la version de numpy : sans effet)."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from scipy.signal import resample_poly
        return resample_poly
    except Exception:       # noqa: BLE001 : scipy absent ou cassé : interpolation linéaire
        return None


def reechantillonner(audio, frequence_source, frequence_cible=V.FREQUENCE_PCM_HZ):
    """Le son (flottants de -1 à 1) à une autre fréquence ; même durée à un échantillon près."""
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    frequence_source, frequence_cible = int(frequence_source), int(frequence_cible)
    if frequence_source <= 0 or frequence_cible <= 0:
        raise ValueError("fréquences positives attendues")
    if frequence_source == frequence_cible or audio.size == 0:
        return audio.copy()
    commun = math.gcd(frequence_source, frequence_cible)
    haut, bas = frequence_cible // commun, frequence_source // commun
    resample_poly = _resample_poly()
    if resample_poly is not None:
        return np.asarray(resample_poly(audio, haut, bas), dtype=np.float32)
    nombre = int(math.ceil(audio.size * haut / bas))
    temps_cible = np.arange(nombre, dtype=np.float64) * (frequence_source / frequence_cible)
    return np.interp(temps_cible, np.arange(audio.size, dtype=np.float64), audio).astype(np.float32)


def vers_int16(audio):
    """Flottants de -1 à 1 → entiers de 16 bits (écrêtés)."""
    audio = np.asarray(audio, dtype=np.float32)
    return np.clip(np.round(audio * 32767.0), -32768, 32767).astype(np.int16)


def pcm_16k(audio, frequence_source):
    """Le PCM du robot : rééchantillonné à 16 kHz, mono, 16 bits signés petit-boutiste (octets)."""
    return vers_int16(reechantillonner(audio, frequence_source)).astype("<i2").tobytes()


def ecrire_wav(chemin, echantillons, frequence_hz):
    """WAV mono 16 bits (écrit à côté puis renommé : la borne ne lit jamais un fichier à moitié écrit)."""
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    provisoire = chemin.with_name(f".{chemin.name}.{os.getpid()}.part")
    donnees = np.asarray(echantillons, dtype=np.int16).astype("<i2").tobytes()
    with wave.open(str(provisoire), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(int(frequence_hz))
        f.writeframes(donnees)
    os.replace(provisoire, chemin)
    return chemin


def lire_wav(chemin):
    """(fréquence, échantillons int16) d'un WAV mono 16 bits ; ValueError pour un autre format."""
    with wave.open(str(chemin), "rb") as f:
        if f.getsampwidth() != 2 or f.getnchannels() != 1:
            raise ValueError(f"{chemin} : WAV mono 16 bits attendu")
        frequence = f.getframerate()
        donnees = f.readframes(f.getnframes())
    return frequence, np.frombuffer(donnees, dtype="<i2").astype(np.int16)


def voix_disponibles(dossier=None):
    """Les voix Piper de VOIX_PIPER présentes sur ce PC (modèle .onnx et sa fiche .onnx.json)."""
    dossier = Path(dossier or V.DOSSIER_PIPER)
    return [nom for nom in V.VOIX_PIPER
            if (dossier / f"{nom}.onnx").is_file() and (dossier / f"{nom}.onnx.json").is_file()]


def choisir_voix(nom, disponibles, defaut=V.VOIX_DEFAUT):
    """La voix demandée si elle est là, sinon la voix par défaut, sinon la première présente ; None sans voix."""
    for candidat in (nom, defaut):
        if candidat and candidat in disponibles:
            return candidat
    return disponibles[0] if disponibles else None


def _borner(valeur, bas, haut, defaut):
    try:
        v = float(valeur)
    except (TypeError, ValueError):
        return defaut
    if not math.isfinite(v):
        return defaut
    return min(haut, max(bas, v))


def vitesse_valable(vitesse):
    """Vitesse de la voix bornée de 0,5 à 2 (1,0 par défaut), comme les schémas des personnalités et de demo.yaml."""
    return _borner(vitesse, 0.5, 2.0, 1.0)


def gain_valable(gain):
    """Gain des échantillons borné de 0 à 1 (1,0 par défaut)."""
    return _borner(gain, 0.0, 1.0, 1.0)


def _assembler(morceaux, frequence, gain):
    """Les phrases de Piper mises bout à bout avec un court silence, le gain appliqué, coupées à la durée max."""
    silence = np.zeros(int(round(SILENCE_ENTRE_PHRASES_S * frequence)), dtype=np.float32)
    parties = []
    for i, m in enumerate(morceaux):
        if i:
            parties.append(silence)
        parties.append(np.asarray(m, dtype=np.float32).reshape(-1))
    audio = np.concatenate(parties) if parties else np.zeros(0, dtype=np.float32)
    maximum = int(V.DUREE_PHRASE_MAX_S * frequence)
    tronque = audio.size > maximum
    if tronque:
        audio = audio[:maximum]
    return audio * np.float32(gain), tronque


def son_de_phrase(morceaux, frequence, voix, vitesse=1.0, gain=1.0, duree_synthese_s=0.0):
    """SonPhrase à partir des morceaux flottants (une phrase de Piper chacun)."""
    audio, tronque = _assembler(morceaux, frequence, gain)
    if audio.size == 0:
        raise ErreurSynthese("la synthèse n'a rendu aucun son")
    return SonPhrase(echantillons=vers_int16(audio), frequence_hz=int(frequence), pcm16=pcm_16k(audio, frequence),
                     voix=voix, vitesse=vitesse, gain=gain, duree_synthese_s=round(duree_synthese_s, 4),
                     tronque=tronque, phrases=max(1, len(morceaux)))


# ---------------------------------------------------------------- les synthétiseurs

class SynthesePiper:
    """Piper (piper-tts de .venv-projet) ; les voix sont chargées à la première phrase puis gardées."""

    def __init__(self, dossier=None):
        self.dossier = Path(dossier or V.DOSSIER_PIPER)
        self._voix = {}
        self._verrou = threading.Lock()
        self.chargements = {}              # voix → secondes de chargement

    def disponibles(self):
        return voix_disponibles(self.dossier)

    def charger(self, nom):
        """La voix Piper (chargée une seule fois) ; ErreurSynthese si elle manque."""
        with self._verrou:
            if nom in self._voix:
                return self._voix[nom]
            modele = self.dossier / f"{nom}.onnx"
            if nom not in V.VOIX_PIPER or not modele.is_file() or not Path(f"{modele}.json").is_file():
                raise ErreurSynthese(f"la voix « {nom} » est absente de {self.dossier} "
                                     f"(voix prévues : {', '.join(V.VOIX_PIPER)})")
            try:
                from piper import PiperVoice
            except ImportError as e:
                raise ErreurSynthese(f"Piper est introuvable ({e}) : lancez g1-voix avec le Python du projet "
                                     "(.venv-projet)") from None
            debut = time.perf_counter()
            self._voix[nom] = PiperVoice.load(str(modele))
            self.chargements[nom] = round(time.perf_counter() - debut, 3)
            return self._voix[nom]

    def synthetiser(self, texte, voix=V.VOIX_DEFAUT, vitesse=1.0, gain=1.0):
        texte = str(texte or "").strip()
        if not texte:
            raise ErreurSynthese("phrase vide")
        vitesse, gain = vitesse_valable(vitesse), gain_valable(gain)
        modele = self.charger(voix)
        from piper import SynthesisConfig
        debut = time.perf_counter()
        morceaux = [m.audio_float_array for m in modele.synthesize(texte, SynthesisConfig(length_scale=1.0 / vitesse))]
        duree = time.perf_counter() - debut
        return son_de_phrase(morceaux, modele.config.sample_rate, voix, vitesse, gain, duree)


class SyntheseFactice:
    """Voix d'essai sans Piper : un bip doux, aussi long que la phrase dite par Piper (environ)."""

    def __init__(self, frequence_hz=FREQUENCE_FACTICE_HZ):
        self.frequence_hz = int(frequence_hz)
        self.chargements = {}

    def disponibles(self):
        return list(V.VOIX_PIPER)

    def synthetiser(self, texte, voix=V.VOIX_DEFAUT, vitesse=1.0, gain=1.0):
        texte = str(texte or "").strip()
        if not texte:
            raise ErreurSynthese("phrase vide")
        vitesse, gain = vitesse_valable(vitesse), gain_valable(gain)
        debut = time.perf_counter()
        duree = max(0.4, len(texte) * DUREE_FACTICE_PAR_CARACTERE_S / vitesse)
        n = int(duree * self.frequence_hz)
        t = np.arange(n, dtype=np.float32) / self.frequence_hz
        bip = 0.3 * np.sin(2 * np.pi * 440.0 * t) * np.minimum(1.0, np.minimum(t, duree - t) / 0.02)
        return son_de_phrase([bip.astype(np.float32)], self.frequence_hz, voix, vitesse, gain,
                             time.perf_counter() - debut)


__all__ = ["ErreurSynthese", "FREQUENCE_FACTICE_HZ", "SILENCE_ENTRE_PHRASES_S", "SonPhrase", "SynthesePiper",
           "SyntheseFactice", "choisir_voix", "ecrire_wav", "gain_valable", "lire_wav", "pcm_16k",
           "reechantillonner", "son_de_phrase", "vers_int16", "vitesse_valable", "voix_disponibles"]
