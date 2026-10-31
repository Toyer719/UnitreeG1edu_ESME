"""Panneau « Comportement du guide » de Simuler (section 11.4 ; coque de la vague 5, section 12.2), dans
Firefox sans fenêtre : la section « Visite guidée » du panneau de droite s'ouvre par la commande Avancé
« Réglages du guide », liste les salles de l'étage (le point principal marqué), montre les réglages du guide
du lieu ; un réglage changé puis « Enregistrer les réglages » écrit la section guide de lieu.yaml,
« Valeurs par défaut » la retire. Les cases « Accompagner » et « Retour » du ruban partent avec « Y aller ».
Rien n'est envoyé au robot. Sauté sans geckodriver ou Firefox.
"""
import yaml

from .test_serveur_communs import faux_bin, journaux, lieux  # noqa: F401
from .test_serveur_demarrage import serveur  # noqa: F401
from .test_serveur_navigateur import navigateur, ouvrir_espace, pytestmark  # noqa: F401

CHANGER = """
const [libelle, valeur] = arguments;
const champ = Array.from(document.querySelectorAll('.comportement-reglages .champ')).find(
  (c) => c.textContent.includes(libelle));
const entree = champ.querySelector('input');
entree.value = String(valeur);
entree.dispatchEvent(new Event('change'));
return true;
"""


def test_panneau_du_comportement(serveur, navigateur, lieux):
    _, base = serveur
    nav = navigateur
    ouvrir_espace(nav, base, mode="simu", hash_="#simulation")
    nav.ecran("simulation")
    nav.attendre("const p = document.querySelector('[data-role=panneau-comportement]');"
                 "return p && !p.hidden && !!p.querySelector('.comportement-reglages')", message="panneau")
    # en Simulation, « Accompagner un visiteur » est dans le ruban (cases et Y aller) : pas de doublon ici
    assert nav.js("return document.querySelector('.comportement-accompagner').hidden") is True
    assert nav.js("return document.querySelector('.comportement-faux-visiteur').hidden") is False
    # la section est repliée ; la commande Avancé « Réglages du guide » l'ouvre sur les réglages
    assert nav.js("return document.querySelector('[data-section=comportement]').open") is False
    nav.commande("simulation.reglages-guide")
    nav.attendre("return document.querySelector('[data-section=comportement]').open && "
                 "document.querySelector('.comportement-reglages').open", message="réglages ouverts")
    nav.attendre("return document.querySelectorAll('.comportement-accompagner option').length === 6",
                 message="les six salles du demo")
    options = nav.js("return Array.from(document.querySelectorAll('.comportement-accompagner option'))"
                     ".map((o) => o.textContent)")
    assert "Accueil (point principal)" in options and "Salle B204" in options
    # l'état du guide n'est dit qu'une fois, en haut du panneau
    assert nav.js("return document.querySelector('.comportement-etat')") is None
    assert nav.js("return document.querySelector('[data-role=guide]').textContent")
    nav.attendre("return document.querySelectorAll('.comportement-reglages .champ').length === 8",
                 message="les huit réglages du guide")
    assert nav.js(CHANGER, "Attente à destination avant le retour", 7)
    nav.js("Array.from(document.querySelectorAll('.comportement-reglages button')).find((b) => "
           "b.textContent === 'Enregistrer les réglages').click()")
    fichier = lieux / "demo" / "lieu.yaml"
    nav.attendre("return document.querySelector('[data-role=journal] .message-succes') !== null", message="réglages enregistrés")
    assert yaml.safe_load(fichier.read_text(encoding="utf-8"))["guide"] == {"delai_avant_retour_s": 7}
    nav.js("Array.from(document.querySelectorAll('.comportement-reglages button')).find((b) => "
           "b.textContent === 'Valeurs par défaut').click()")
    nav.attendre("return document.querySelectorAll('[data-role=journal] .message-succes').length >= 2", message="remis par défaut")
    assert "guide" not in yaml.safe_load(fichier.read_text(encoding="utf-8"))
    # les cases du ruban : cochées, elles restent cochées (mémoire du navigateur)
    nav.commande("simulation.accompagner")
    assert nav.js("return document.querySelector('[data-commande=\"simulation.accompagner\"]').getAttribute('aria-pressed')") == "true"
    assert nav.js("return JSON.parse(localStorage.getItem('atelier.cases')).accompagner") is True
    nav.commande("simulation.accompagner")
    assert nav.js("return JSON.parse(localStorage.getItem('atelier.cases')).accompagner") is False
    assert not nav.js("return window.erreursAtelier || []")
