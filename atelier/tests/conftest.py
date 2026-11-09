"""Réglages communs à tous les tests de atelier/tests (assemblage de la vague 6, section 13.13 du plan).

Les séances de la boîte noire et les sons de la voix des tests restent dans le dossier du test : un essai qui ouvre
l'espace en Réel (une séance s'ouvre seule, 13.3) ou qui fait parler la voix n'écrit jamais dans
~/robot-g1/journaux/seances ni dans ~/robot-g1/journaux/voix/sons, même par un serveur lancé dans un sous-processus
(la variable passe dans son environnement). Un test qui règle lui-même ces variables (monkeypatch.setenv) garde la
sienne.
"""
import pytest


@pytest.fixture(autouse=True)
def journaux_de_la_vague_6_dans_le_test(tmp_path, monkeypatch):
    monkeypatch.setenv("ATELIER_SEANCES", str(tmp_path / "seances_du_test"))
    monkeypatch.setenv("ATELIER_VOIX_SONS", str(tmp_path / "sons_du_test"))
