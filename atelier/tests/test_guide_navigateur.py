"""Panneau « Comportement du guide » de l'onglet Simulation, dans Firefox sans fenêtre (section 11.4).

Le panneau s'ouvre avec l'onglet, liste les salles de l'étage (le point principal marqué), montre
les réglages du guide du lieu ; un réglage changé puis « Enregistrer les réglages » écrit la
section guide de lieu.yaml, « Valeurs par défaut » la retire. Rien n'est envoyé au robot.
Sauté sans geckodriver ou Firefox.
"""
import yaml

from .test_serveur_communs import faux_bin, journaux, lieux  # noqa: F401
from .test_serveur_demarrage import serveur  # noqa: F401
from .test_serveur_navigateur import navigateur, pytestmark  # noqa: F401

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
    nav.ouvrir(base + "/")
    nav.attendre("return document.querySelector('.onglet.actif') !== null", message="premier écran ouvert")
    nav.js("localStorage.setItem('atelier.lieu', 'demo'); localStorage.setItem('atelier.etage', 'rdc');"
           "localStorage.setItem('atelier.mode-simulation', 'simu');")
    nav.ouvrir(base + "/?recharger=1#simulation")
    nav.attendre("const p = document.querySelector('[data-role=panneau-comportement]');"
                 "return p && !p.hidden && p.textContent.includes('Comportement du guide')", message="panneau")
    nav.attendre("return document.querySelectorAll('.comportement-accompagner option').length === 6",
                 message="les six salles du demo")
    options = nav.js("return Array.from(document.querySelectorAll('.comportement-accompagner option'))"
                     ".map((o) => o.textContent)")
    assert "Accueil (point principal)" in options and "Salle B204" in options
    # « Guide non lancé », ou l'état d'un guide qui tourne dans le même domaine ROS
    assert nav.js("return document.querySelector('.comportement-etat').textContent")
    nav.attendre("return document.querySelectorAll('.comportement-reglages .champ').length === 8",
                 message="les huit réglages du guide")
    nav.js("document.querySelector('.comportement-reglages').open = true;")
    assert nav.js(CHANGER, "Attente à destination avant le retour", 7)
    nav.bouton("Enregistrer les réglages", ".comportement-reglages")
    fichier = lieux / "demo" / "lieu.yaml"
    nav.attendre("return document.querySelector('.message-succes') !== null", message="réglages enregistrés")
    assert yaml.safe_load(fichier.read_text(encoding="utf-8"))["guide"] == {"delai_avant_retour_s": 7}
    nav.bouton("Valeurs par défaut", ".comportement-reglages")
    nav.attendre("return document.querySelectorAll('.message-succes').length >= 2", message="remis par défaut")
    assert "guide" not in yaml.safe_load(fichier.read_text(encoding="utf-8"))
    assert not nav.js("return window.erreursAtelier || []")
