"""Tests de la commande g1-lieu (et de son alias gl-lieu), lancée comme un utilisateur.

  ~/robot-g1/.venv-projet/bin/python -m pytest ~/robot-g1/atelier/tests/test_lieu_commande.py -v

Les lieux sont créés dans un dossier temporaire (ATELIER_LIEUX), jamais dans ~/robot-g1/lieux.
"""
import os
import subprocess

import pytest

import atelier
from atelier import lieu as L

BIN = atelier.RACINE / "bin"
DEMO = atelier.RACINE / "lieux" / "demo"


def lancer(tmp_path, *arguments, commande="g1-lieu"):
    env = dict(os.environ, ATELIER_LIEUX=str(tmp_path))
    resultat = subprocess.run([str(BIN / commande), *arguments], env=env, cwd=tmp_path,
                              capture_output=True, text=True, timeout=60)
    return resultat.returncode, resultat.stdout + resultat.stderr


def test_creer_puis_valider(tmp_path):
    code, sortie = lancer(tmp_path, "creer", "essai", "--nom", "Lycée essai")
    assert code == 0, sortie
    assert f"Lieu « Lycée essai » créé dans {tmp_path / 'essai'}" in sortie
    for nom in ("lieu.yaml", "salles.yaml", "itineraires.yaml", "zones.yaml", "mondes/rdc.monde.yaml"):
        assert (tmp_path / "essai" / nom).is_file(), nom
    code, sortie = lancer(tmp_path, "valider", "--lieu", "essai")
    assert code == 0, sortie
    assert "Lieu « Lycée essai »" in sortie and "Aucune erreur." in sortie
    assert "1 étage, 1 salle, 1 nœud, 0 couloir" in sortie


def test_creer_avec_options(tmp_path):
    code, sortie = lancer(tmp_path, "creer", str(tmp_path / "musee"), "--nom", "Musée", "--etage", "niveau0",
                          "--nom-etage", "Niveau 0", "--largeur", "40", "--profondeur", "25")
    assert code == 0, sortie
    lieu = L.charger_lieu(tmp_path / "musee")
    assert lieu.etages[0].id == "niveau0" and lieu.mondes["niveau0"].emprise == L.Emprise(0, 0, 40, 25)


def test_creer_un_lieu_qui_existe(tmp_path):
    lancer(tmp_path, "creer", "essai", "--nom", "Essai")
    code, sortie = lancer(tmp_path, "creer", "essai", "--nom", "Essai")
    assert code == 1 and "Lieu non créé" in sortie and "existe déjà" in sortie


def test_valider_le_demo_par_son_chemin(tmp_path):
    code, sortie = lancer(tmp_path, "valider", "--lieu", str(DEMO))
    assert code == 0, sortie
    assert "Lieu « Lycée démo »" in sortie
    assert "1 étage, 6 salles, 13 nœuds, 13 couloirs, 1 zone interdite, 1 zone lente, 1 monde" in sortie


def test_valider_un_lieu_errone(tmp_path):
    copie = L.copier_lieu(DEMO, tmp_path / "demo")
    texte = (copie / "salles.yaml").read_text(encoding="utf-8")
    (copie / "salles.yaml").write_text(texte.replace("pose: {x: 21.0, y: 13.0, theta: 1.5708}",
                                                     "pose: {x: 21.0, y: 13.0}"), encoding="utf-8")
    code, sortie = lancer(tmp_path, "valider", "--lieu", "demo")
    assert code == 1
    assert "Erreurs à corriger (1) :" in sortie
    assert "  - salles.yaml, salle « b204 » : il manque theta dans pose" in sortie


def test_valider_un_lieu_absent(tmp_path):
    code, sortie = lancer(tmp_path, "valider", "--lieu", "inconnu")
    assert code == 1 and "n'existe pas" in sortie


def test_alias_et_liste(tmp_path):
    assert lancer(tmp_path, "creer", "essai", "--nom", "Essai", commande="gl-lieu")[0] == 0
    code, sortie = lancer(tmp_path, "liste", commande="gl-lieu")
    assert code == 0 and "essai" in sortie


@pytest.mark.parametrize("arguments", [[], ["creer", "essai"], ["valider"], ["effacer"]])
def test_commande_mal_tapee(tmp_path, arguments):
    code, sortie = lancer(tmp_path, *arguments)
    assert code == 2 and "erreur :" in sortie and "--help" in sortie
    assert "required" not in sortie and "invalid choice" not in sortie


# ---------------------------------------------------------------- g1-lieu migrer (vague 4, section 11.2)

def _empreintes(dossier):
    import hashlib
    return {str(f.relative_to(dossier)): hashlib.sha256(f.read_bytes()).hexdigest()
            for f in sorted(dossier.rglob("*")) if f.is_file()}


def test_migrer_puis_valider(tmp_path):
    copie = L.copier_lieu(DEMO, tmp_path / "essai")
    avant = _empreintes(copie)
    code, sortie = lancer(tmp_path, "migrer", "--lieu", "essai", "--a-blanc")
    assert code == 0 and "Changements prévus (1) :" in sortie and "Essai à blanc" in sortie, sortie
    assert "salles.yaml, salle « accueil », etiquettes : aucune → [principal]" in sortie
    assert _empreintes(copie) == avant
    code, sortie = lancer(tmp_path, "migrer", "--lieu", "essai")
    assert code == 0 and "Lieu migré" in sortie and "sauvegarde des fichiers d'avant :" in sortie, sortie
    sauvegardes = list((copie / "sauvegardes").iterdir())
    assert len(sauvegardes) == 1
    for nom in ("lieu.yaml", "salles.yaml", "itineraires.yaml", "mondes/rdc.monde.yaml"):
        assert (sauvegardes[0] / nom).read_bytes() == (DEMO / nom).read_bytes(), nom
    assert L.charger_salles(copie)[0].etiquettes == ["principal"]
    code, sortie = lancer(tmp_path, "valider", "--lieu", "essai")
    assert code == 0 and "Aucune erreur." in sortie, sortie
    # second passage : rien ne change
    avant = _empreintes(copie)
    code, sortie = lancer(tmp_path, "migrer", "--lieu", "essai")
    assert code == 0 and "Rien à changer" in sortie and _empreintes(copie) == avant


def test_migrer_refuse_la_reference(tmp_path):
    avant = _empreintes(DEMO)
    code, sortie = lancer(tmp_path, "migrer", "--lieu", str(DEMO))
    assert code == 1 and "Migration refusée" in sortie and "référence des tests" in sortie
    assert _empreintes(DEMO) == avant
    code, sortie = lancer(tmp_path, "migrer", "--lieu", "absent")
    assert code == 1 and "n'existe pas" in sortie


def test_migrer_mal_tape(tmp_path):
    code, sortie = lancer(tmp_path, "migrer")
    assert code == 2 and "il manque : --lieu" in sortie
