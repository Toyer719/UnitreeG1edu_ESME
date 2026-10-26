"""Panneau des passants de l'onglet Simulation, dans Firefox sans fenêtre (section 11.3 du plan).

Le panneau s'affiche, liste les scènes (GET /api/passants/scenes) avec leur commande, les derniers
bancs, et dit qu'il n'y a pas de piéton tant que la simulation ne tourne pas. Serveur : bin/g1-atelier
sans ROS, sur une copie du demo (fixtures de test_serveur_navigateur). Sauté sans geckodriver.
"""
from .test_serveur_communs import faux_bin, journaux, lieux  # noqa: F401
from .test_serveur_demarrage import serveur  # noqa: F401
from .test_serveur_navigateur import navigateur, sans_ros  # noqa: F401
from .test_serveur_navigateur import pytestmark  # noqa: F401


def test_panneau_des_passants(sans_ros, serveur, navigateur, lieux):  # noqa: F811
    _, base = serveur
    nav = navigateur
    nav.ouvrir(base + "/")
    nav.attendre("return document.querySelector('.onglet.actif') !== null", message="premier écran ouvert")
    nav.js("localStorage.setItem('atelier.lieu', 'demo'); localStorage.setItem('atelier.etage', 'rdc');"
           "localStorage.setItem('atelier.mode-simulation', 'simu');")
    nav.ouvrir(base + "/?recharger=1#simulation")
    nav.attendre("return document.querySelector('.panneau-passants .panneau-titre') !== null",
                 message="panneau des passants")
    panneau = "document.querySelector('.panneau-passants')"
    assert nav.js(f"return {panneau}.hidden") is False
    assert nav.js(f"return {panneau}.querySelector('.panneau-titre').textContent") == "Passants"
    nav.attendre(f"return {panneau}.querySelectorAll('.passants-scene').length >= 6", message="scènes chargées")
    texte = nav.js(f"return {panneau}.querySelector('[data-role=scenes]').textContent")
    assert "Passant immobile au milieu du couloir nord" in texte and "g1-banc --scene immobile_couloir" in texte
    assert "0,20 m bord à bord" in texte
    nav.attendre(f"return {panneau}.querySelector('[data-role=bancs]').textContent.length > 0",
                 message="derniers bancs")
    nav.attendre(f"return {panneau}.querySelector('[data-role=distance]').textContent.includes('Aucun piéton')",
                 message="aucun piéton sans simulation")
