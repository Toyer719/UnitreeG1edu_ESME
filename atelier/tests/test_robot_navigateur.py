"""Onglet Simulation en répétition, dans Firefox sans fenêtre (section 10.8 du plan) :
« Répétition sans robot » → « Lancer la répétition » → marque au sol et panneau « Repérage » →
« Y aller » grisé → « Repérer le robot » → repéré → « Y aller » permis → « Le robot n'est pas sur
la marque » (clic puis glissé sur la carte) → « Bloquer le robot » / « Débloquer » → arrêt.

Serveur : bin/g1-atelier, avec les fausses commandes g1-* et le pont ROS 2 du serveur ; le faux
relais odom_vers_tf de test_robot_serveur_ros répond aux demandes de repérage et dit Nav2 actif.
Sauté sans geckodriver, Firefox ou ROS 2. Domaine ROS : $ROS_DOMAIN_ID, 63 par défaut.
"""
import json
import os
import urllib.request

import pytest

os.environ.setdefault("ROS_DOMAIN_ID", "63")
pytest.importorskip("rclpy", reason="ROS 2 n'est pas chargé : source ~/robot-g1/setup/env.sh")

from .test_robot_serveur_ros import FauxRelais  # noqa: E402
from .test_serveur_communs import attendre, faux_bin, journaux, lieux  # noqa: E402,F401
from .test_serveur_demarrage import serveur  # noqa: E402,F401
from .test_serveur_navigateur import GECKODRIVER, navigateur  # noqa: E402,F401

pytestmark = pytest.mark.skipif(GECKODRIVER is None, reason="geckodriver absent")


class RelaisAvecNav2(FauxRelais):
    """Faux relais, plus un faux bt_navigator actif (« Y aller » attend Nav2)."""

    def __init__(self):
        super().__init__()
        from lifecycle_msgs.srv import GetState
        self.noeud.create_service(GetState, "/bt_navigator/get_state", self._nav2)

    @staticmethod
    def _nav2(demande, reponse):
        reponse.current_state.label = "active"
        return reponse


@pytest.fixture
def relais():
    r = RelaisAvecNav2()
    yield r
    r.fermer()


def _api(base, chemin, corps=None):
    r = urllib.request.Request(base + chemin, method="GET" if corps is None else "POST",
                               data=None if corps is None else json.dumps(corps).encode(),
                               headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=20) as reponse:
        return json.loads(reponse.read())


def test_reperage_dans_l_onglet_simulation(serveur, navigateur, relais, faux_bin):
    _, base = serveur
    nav = navigateur
    _api(base, "/api/lieux/demo/etages/rdc/monde/generer", {})
    nav.ouvrir(base + "/")
    # La page démarre en asynchrone (GET /api/etat, puis le lieu mémorisé) : on attend qu'elle ait
    # ouvert son premier écran avant d'écrire le lieu, sinon son démarrage en cours, coupé par le
    # rechargement ci-dessous, pouvait encore relire et changer ce qu'on vient d'écrire.
    nav.attendre("return document.querySelector('.onglet.actif') !== null", message="premier écran ouvert")
    nav.js("localStorage.setItem('atelier.lieu', 'demo'); localStorage.setItem('atelier.etage', 'rdc');"
           "localStorage.setItem('atelier.mode-simulation', 'simu');")
    nav.ouvrir(base + "/?recharger=1#simulation")      # autre adresse : la page se recharge
    nav.attendre("return document.querySelectorAll('.modes-simulation .outil').length === 3", message="modes")
    # en simulation : pas de panneau Repérage
    assert nav.js("return document.querySelector('[data-role=reperage]').hidden") is True
    nav.bouton("Répétition sans robot", ".modes-simulation")
    nav.attendre("return !document.querySelector('[data-role=reperage]').hidden", message="panneau Repérage")
    assert nav.js("return document.querySelector('[data-role=lancer]').textContent") == "Lancer la répétition"
    assert "marque au sol" in nav.js("return document.querySelector('[data-role=reperage]').textContent")
    nav.attendre("return document.querySelector('.ecran-simulation .marque-sol')", message="marque au sol dessinée")
    nav.bouton("Lancer la répétition")
    nav.attendre("return document.querySelector('[data-role=etat-simu]').textContent.includes('Répétition en cours')",
                 delai=20, message="répétition en cours")
    appels = faux_bin.appels()
    assert any(a.startswith("g1-slam faux-service --jumeau") for a in appels)
    assert any(a.endswith("--simu --localisation unitree") for a in appels)
    # pas encore repéré : « Y aller » grisé, le guide attend le repérage
    nav.attendre("return document.querySelector('[data-role=etat-reperage]').textContent === 'Non repéré'",
                 message="non repéré")
    nav.attendre("return Array.from(document.querySelectorAll('.liste-salles button')).every((b) => b.disabled)",
                 message="Y aller grisé")
    assert "repérage" in nav.js("return document.querySelector('[data-role=guide]').textContent")
    assert "attend le repérage" in nav.js("return document.querySelector('[data-role=pont]').textContent")
    # « Repérer le robot » : repéré, puis « Y aller » permis
    nav.bouton("Repérer le robot", "[data-role=reperage]")
    nav.attendre("return document.querySelector('[data-role=etat-reperage]').textContent.startsWith('Repéré')",
                 delai=20, message="repéré")
    assert "précision 2 cm" in nav.js("return document.querySelector('[data-role=etat-reperage]').textContent")
    assert set(relais.demandes[-1]) == {"id"}
    nav.attendre("return Array.from(document.querySelectorAll('.liste-salles button')).some((b) => !b.disabled)",
                 message="Y aller permis")
    nav.attendre("return document.querySelector('.ecran-simulation .robot-direct')", message="robot sur la carte")
    # le robot n'est pas sur la marque : clic puis glissé vers la droite de l'écran (l'est, cap 0)
    nav.bouton("Le robot n'est pas sur la marque", "[data-role=reperage]")
    assert nav.js("return document.querySelector('[data-role=aide-position]').hidden") is False
    nombre = len(relais.demandes)
    nav.geste("simulation", [[0.3, 0.5], [0.35, 0.5], [0.4, 0.5]])
    assert attendre(lambda: len(relais.demandes) > nombre, 15)
    d = relais.demandes[-1]
    assert {"x", "y", "theta"} <= set(d) and abs(d["theta"]) < 0.1
    nav.attendre("return document.querySelector('[data-role=etat-reperage]').textContent.startsWith('Repéré')",
                 delai=20, message="repéré à la position cliquée")
    # verrou du pont
    nav.bouton("Bloquer le robot", "[data-role=reperage]")
    assert attendre(lambda: relais.verrous[-1:] == [True], 10)
    nav.bouton("Débloquer", "[data-role=reperage]")
    assert attendre(lambda: relais.verrous[-1:] == [False], 10)
    # arrêt
    nav.bouton("Arrêter la répétition")
    nav.attendre("return document.querySelector('[data-role=etat-simu]').textContent.startsWith('Simulation arrêtée')",
                 delai=30, message="répétition arrêtée")
    assert nav.js("return document.querySelectorAll('.modes-simulation .outil:disabled').length") == 0
    assert nav.js("return window.erreursAtelier") == []
    erreurs = nav.js("return Array.from(document.querySelectorAll('.message-erreur')).map(e => e.textContent)")
    assert erreurs == [], erreurs
