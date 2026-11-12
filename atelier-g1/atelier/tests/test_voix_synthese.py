"""La synthèse de la voix (vague 6, section 13.6 du plan ; agent Voix) : Piper sur le PC, PCM 16 kHz, WAV.

Rééchantillonnage (scipy, et le repli sans scipy) à la même durée, PCM pair et petit-boutiste, WAV écrits puis
relus (atomiques), voix présentes et choix de repli, voix d'essai sans Piper, et Piper lui-même (sauté sans le
modèle) : durée, fréquence, vitesse, gain, temps de synthèse d'une phrase, voix absente et phrase vide refusées.
"""
import time

import numpy as np
import pytest

from atelier.lieu import voix as V
from atelier.voix import synthese as S


def test_reechantillonner_garde_la_duree():
    for frequence in (22050, 44100, 16000, 48000):
        audio = np.sin(np.arange(frequence * 2) / frequence * 2 * np.pi * 200).astype(np.float32) * 0.5
        sortie = S.reechantillonner(audio, frequence)
        assert abs(len(sortie) - 32000) <= 1, frequence
        assert sortie.dtype == np.float32 and np.max(np.abs(sortie)) < 0.6


def test_reechantillonner_sans_scipy(monkeypatch):
    monkeypatch.setattr(S, "_resample_poly", lambda: None)
    audio = np.linspace(-0.5, 0.5, 22050, dtype=np.float32)
    sortie = S.reechantillonner(audio, 22050)
    assert len(sortie) == 16000 and sortie[0] == pytest.approx(-0.5) and sortie[-1] == pytest.approx(0.5, abs=1e-3)
    with pytest.raises(ValueError):
        S.reechantillonner(audio, 0)


def test_pcm_16k_pair_et_petit_boutiste():
    audio = np.array([0.0, 1.0, -1.0, 2.0, 0.5], dtype=np.float32)
    pcm = S.pcm_16k(audio, V.FREQUENCE_PCM_HZ)
    assert len(pcm) == 10 and len(pcm) % 2 == 0
    assert np.frombuffer(pcm, dtype="<i2").tolist() == [0, 32767, -32767, 32767, 16384]
    assert S.vers_int16(np.array([3.0, -3.0])).tolist() == [32767, -32768]


def test_wav_ecrit_puis_relu(tmp_path):
    echantillons = (np.arange(-100, 100) * 50).astype(np.int16)
    chemin = S.ecrire_wav(tmp_path / "sons" / "s-1.wav", echantillons, 22050)
    frequence, relus = S.lire_wav(chemin)
    assert frequence == 22050 and relus.tolist() == echantillons.tolist()
    assert [f.name for f in chemin.parent.iterdir()] == ["s-1.wav"]       # pas de fichier provisoire


def test_voix_presentes_et_choix(tmp_path):
    assert S.voix_disponibles(tmp_path) == []
    (tmp_path / "fr_FR-tom-medium.onnx").write_bytes(b"x")
    assert S.voix_disponibles(tmp_path) == []                              # sans la fiche .onnx.json
    (tmp_path / "fr_FR-tom-medium.onnx.json").write_text("{}")
    (tmp_path / "autre.onnx").write_bytes(b"x")
    assert S.voix_disponibles(tmp_path) == ["fr_FR-tom-medium"]
    assert S.choisir_voix("fr_FR-siwis-medium", ["fr_FR-tom-medium"]) == "fr_FR-tom-medium"
    assert S.choisir_voix("fr_FR-tom-medium", V.VOIX_PIPER) == "fr_FR-tom-medium"
    assert S.choisir_voix("inconnue", list(V.VOIX_PIPER)) == V.VOIX_DEFAUT
    assert S.choisir_voix("inconnue", []) is None


def test_vitesse_et_gain_bornes():
    assert S.vitesse_valable(5) == 2.0 and S.vitesse_valable(0.1) == 0.5 and S.vitesse_valable("x") == 1.0
    assert S.vitesse_valable(float("nan")) == 1.0 and S.gain_valable(1.5) == 1.0 and S.gain_valable(-1) == 0.0


def test_voix_d_essai():
    f = S.SyntheseFactice()
    son = f.synthetiser("Bonjour, suivez-moi !")
    assert son.frequence_hz == S.FREQUENCE_FACTICE_HZ and son.duree_s == pytest.approx(21 * 0.065, abs=0.01)
    assert len(son.pcm16) % 2 == 0 and abs(son.duree_pcm_s - son.duree_s) < 0.001
    plus_bas = f.synthetiser("Bonjour, suivez-moi !", gain=0.5)
    assert np.max(np.abs(plus_bas.echantillons)) == pytest.approx(np.max(np.abs(son.echantillons)) / 2, rel=0.01)
    assert f.synthetiser("x" * 600).duree_s == pytest.approx(V.DUREE_PHRASE_MAX_S, abs=0.01)
    assert f.synthetiser("x" * 600).tronque
    with pytest.raises(S.ErreurSynthese):
        f.synthetiser("   ")


def test_phrases_assemblees_avec_un_silence():
    morceaux = [np.ones(1000, dtype=np.float32) * 0.5, np.ones(500, dtype=np.float32) * 0.5]
    son = S.son_de_phrase(morceaux, 10000, "v")
    assert len(son.echantillons) == 1000 + 500 + int(S.SILENCE_ENTRE_PHRASES_S * 10000) and son.phrases == 2
    with pytest.raises(S.ErreurSynthese):
        S.son_de_phrase([], 10000, "v")


PIPER = pytest.mark.skipif(V.VOIX_DEFAUT not in S.voix_disponibles(), reason="modèle Piper absent")


@pytest.fixture(scope="module")
def piper():
    pytest.importorskip("piper")
    return S.SynthesePiper()


@PIPER
def test_piper_une_phrase(piper):
    son = piper.synthetiser("Bonjour, suivez-moi !")
    assert son.frequence_hz == 22050 and son.voix == V.VOIX_DEFAUT
    assert 0.8 < son.duree_s < 3.5
    assert abs(len(son.pcm16) / 2 - son.duree_s * V.FREQUENCE_PCM_HZ) <= 2
    assert abs(son.duree_pcm_s - son.duree_s) < 0.001 and len(son.pcm16) % 2 == 0
    assert 1000 < np.max(np.abs(son.echantillons)) <= 32767
    assert piper.chargements[V.VOIX_DEFAUT] < 10.0


@PIPER
def test_piper_temps_de_synthese(piper):
    piper.synthetiser("Bonjour.")                    # voix chargée
    debut = time.perf_counter()
    son = piper.synthetiser("Je vous accompagne à la Salle B204.")
    ecoule = time.perf_counter() - debut
    assert son.duree_synthese_s < 1.0 and ecoule < 2.0     # mesuré : 0,07 s sur le PC du projet
    assert son.duree_s > 5 * son.duree_synthese_s


@PIPER
def test_piper_vitesse_et_gain(piper):
    lent = piper.synthetiser("Je fais une petite pause, merci de patienter.", vitesse=0.75)
    rapide = piper.synthetiser("Je fais une petite pause, merci de patienter.", vitesse=1.5)
    assert lent.duree_s > rapide.duree_s * 1.5            # le hasard de Piper change la durée de quelques %
    bas = piper.synthetiser("Bonjour.", gain=0.25)
    assert np.max(np.abs(bas.echantillons)) <= 0.26 * 32767


@PIPER
def test_piper_plusieurs_phrases(piper):
    son = piper.synthetiser("Bonjour ! Je suis le robot d'accueil du lycée. Où voulez-vous aller ?")
    assert son.phrases == 3 and 2.5 < son.duree_s < 9.0


@PIPER
def test_piper_refus(piper):
    with pytest.raises(S.ErreurSynthese, match="absente"):
        piper.synthetiser("Bonjour", voix="fr_FR-inconnue")
    with pytest.raises(S.ErreurSynthese, match="vide"):
        piper.synthetiser("")


@pytest.mark.skipif("fr_FR-tom-medium" not in S.voix_disponibles(), reason="voix tom absente")
def test_piper_voix_d_homme_a_44100(piper):
    son = piper.synthetiser("Bonjour, suivez-moi !", voix="fr_FR-tom-medium")
    assert son.frequence_hz == 44100 and abs(len(son.pcm16) / 2 - son.duree_s * 16000) <= 2
