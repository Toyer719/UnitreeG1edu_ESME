"""Panneau des passants de Simuler (section 11.3 du plan ; coque de la vague 5, section 12.2), dans Firefox
sans fenêtre : la commande Avancé « Passants » ouvre la section « Passants » du panneau de droite, qui liste
les scènes (GET /api/passants/scenes) avec leur commande, les derniers bancs, et dit qu'il n'y a pas de
piéton tant que la simulation ne tourne pas. En Réel, pas de passants simulés. Serveur : bin/g1-atelier sans
ROS, sur une copie du demo (fixtures de test_serveur_navigateur). Sauté sans geckodriver.
"""
from .test_serveur_communs import faux_bin, journaux, lieux  # noqa: F401
from .test_serveur_demarrage import serveur  # noqa: F401
from .test_serveur_navigateur import navigateur, ouvrir_espace, sans_ros  # noqa: F401
from .test_serveur_navigateur import pytestmark  # noqa: F401


def test_panneau_des_passants(sans_ros, serveur, navigateur, lieux):  # noqa: F811
    _, base = serveur
    nav = navigateur
    ouvrir_espace(nav, base, mode="simu", hash_="#simulation")
    nav.ecran("simulation")
    nav.attendre("return document.querySelector('.panneau-passants .panneau-titre') !== null",
                 message="panneau des passants")
    nav.commande("simulation.passants")
    nav.attendre("return document.querySelector('[data-section=passants]').open", message="section Passants ouverte")
    panneau = "document.querySelector('.panneau-passants')"
    assert nav.js(f"return {panneau}.hidden") is False
    assert nav.js("return document.querySelector('[data-section=passants] > summary').textContent") == "Passants"
    nav.attendre(f"return {panneau}.querySelectorAll('.passants-scene').length >= 6", message="scènes chargées")
    texte = nav.js(f"return {panneau}.querySelector('[data-role=scenes]').textContent")
    assert "Passant immobile au milieu du couloir nord" in texte and "g1-banc --scene immobile_couloir" in texte
    assert "0,20 m bord à bord" in texte
    nav.attendre(f"return {panneau}.querySelector('[data-role=bancs]').textContent.length > 0",
                 message="derniers bancs")
    nav.attendre(f"return {panneau}.querySelector('[data-role=distance]').textContent.includes('Aucun piéton')",
                 message="aucun piéton sans simulation")
    # en Réel : la section des passants simulés n'existe pas
    ouvrir_espace(nav, base, mode="reel", repetition=True, hash_="#simulation")
    nav.ecran("simulation")
    assert nav.js("return document.querySelector('[data-section=passants]').hidden") is True
    assert nav.js("return window.erreursAtelier") == []
