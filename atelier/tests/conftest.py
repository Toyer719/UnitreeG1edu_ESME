"""Réglages communs à tous les tests de atelier/tests (assemblage de la vague 6, section 13.13 du plan).

- Les séances de la boîte noire et les sons de la voix des tests restent dans le dossier du test : un essai qui ouvre
  l'espace en Réel (une séance s'ouvre seule, 13.3) ou qui fait parler la voix n'écrit jamais dans
  ~/robot-g1/journaux/seances ni dans ~/robot-g1/journaux/voix/sons, même par un serveur lancé dans un
  sous-processus (la variable passe dans son environnement).
- Le diagnostic (« Vérifier le robot », et celui que la séance fait à son ouverture en Réel) passe par un faux
  contexte vide (ATELIER_DIAGNOSTIC_FAUX : câble absent, aucune commande) : jamais de ping, de ssh ni de nmcli vers
  le vrai robot, même si le câble du robot est branché pendant les tests (13.2, 12.11).
Un test qui règle lui-même une de ces variables (monkeypatch.setenv, ou delenv pour le vrai contexte) garde la sienne.
"""
import pytest


@pytest.fixture(autouse=True)
def vague_6_sans_journaux_ni_robot(tmp_path, monkeypatch):
    monkeypatch.setenv("ATELIER_SEANCES", str(tmp_path / "seances_du_test"))
    monkeypatch.setenv("ATELIER_VOIX_SONS", str(tmp_path / "sons_du_test"))
    faux = tmp_path / "diagnostic_faux_des_tests.json"
    faux.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("ATELIER_DIAGNOSTIC_FAUX", str(faux))
