"""Réel › Naviguer en répétition, dans Firefox sans fenêtre (sections 10.8 et 12.2 du plan) :
« Lancer » (la répétition) → l'accueil sur le plan et la section « Repérage » → « Y aller » grisé →
« Repérer le robot » → repéré → « Y aller » permis → « Le robot n'est pas sur l'accueil » (clic puis glissé
sur le plan) → « Bloquer » / « Débloquer » (ruban) → « Arrêter ». En Simulation, la section Repérage est
cachée (et vraiment invisible : [hidden] l'emporte sur le CSS).
Vague 4 (section 11.2) : le robot se pose sur le point principal (l'étoile, ici la salle accueil du
demo), dont la pose part dans la demande de repérage.

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
from .test_serveur_navigateur import GECKODRIVER, GESTE, navigateur, ouvrir_espace  # noqa: E402,F401

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


def test_reperage_dans_naviguer(serveur, navigateur, relais, faux_bin):
    _, base = serveur
    nav = navigateur
    _api(base, "/api/lieux/demo/etages/rdc/monde/generer", {})
    # en simulation : pas de section Repérage (cachée pour de bon)
    ouvrir_espace(nav, base, mode="simu", hash_="#simulation")
    nav.ecran("simulation")
    assert nav.js("const r = document.querySelector('[data-role=reperage]'); return [r.hidden, getComputedStyle(r).display]") \
        == [True, "none"]
    assert nav.js("return document.querySelectorAll('[data-commande^=\"navigation.\"]').length") == 0
    # répétition : Réel › Naviguer
    ouvrir_espace(nav, base, mode="reel", repetition=True, hash_="#simulation")
    nav.ecran("simulation")
    assert nav.js("return document.querySelector('[data-role=espace]').dataset.mode") == "repetition"
    assert nav.js("return document.querySelector('[data-onglet=naviguer]').getAttribute('aria-selected')") == "true"
    nav.attendre("return !document.querySelector('[data-role=reperage]').hidden", message="section Repérage")
    texte = nav.js("return document.querySelector('[data-role=consigne-reperage]').textContent")
    nav.attendre("return document.querySelector('[data-role=consigne-reperage]').textContent.includes('Accueil')",
                 message="consigne de l'accueil")
    texte = nav.js("return document.querySelector('[data-role=consigne-reperage]').textContent")
    assert texte == "Posez le robot sur l'accueil «\u00a0Accueil\u00a0» (étoile sur la carte), tourné dans le sens de la flèche.", texte
    nav.vue("plan")
    nav.attendre("return document.querySelector('[data-ecran=simulation] path.marque-principal')",
                 message="accueil entouré sur le plan")
    assert nav.js("return document.querySelectorAll('[data-ecran=simulation] .leaflet-marker-icon.salle.principal').length") == 1
    assert nav.js("return document.querySelector('[data-ecran=simulation] .marque-sol')") is None
    nav.commande("navigation.lancer")
    nav.attendre("return document.querySelector('[data-role=etat-simu]').textContent.includes('Répétition en cours')",
                 delai=20, message="répétition en cours")
    appels = faux_bin.appels()
    assert any(a.startswith("g1-slam faux-service --jumeau") for a in appels)
    assert any(a.endswith("--simu --localisation unitree") for a in appels)
    # pas encore repéré : « Y aller » grisé (panneau et ruban, avec la raison), le guide attend le repérage
    nav.attendre("return document.querySelector('[data-role=etat-reperage]').textContent === 'Non repéré'",
                 message="non repéré")
    nav.attendre("return Array.from(document.querySelectorAll('[data-role=salles] button')).every((b) => b.disabled)",
                 message="Y aller grisé")
    nav.attendre("const b = document.querySelector('[data-commande=\"navigation.y-aller\"]'); "
                 "return b.disabled && b.title.includes('Repérez')", message="Y aller grisé dans le ruban")
    assert "repérage" in nav.js("return document.querySelector('[data-role=guide]').textContent")
    assert "attend le repérage" in nav.js("return document.querySelector('[data-role=pont]').textContent")
    # « Repérer » (ruban) : repéré, puis « Y aller » permis
    nav.commande("navigation.reperer")
    nav.attendre("return document.querySelector('[data-role=etat-reperage]').textContent.startsWith('Repéré')",
                 delai=20, message="repéré")
    assert "précision 2 cm" in nav.js("return document.querySelector('[data-role=etat-reperage]').textContent")
    d = relais.demandes[-1]
    assert (d["x"], d["y"], d["theta"]) == (2.5, 10.0, 0.0), d       # la pose du point principal
    nav.attendre("return Array.from(document.querySelectorAll('[data-role=salles] button')).some((b) => !b.disabled)",
                 message="Y aller permis")
    nav.attendre("return document.querySelector('[data-ecran=simulation] .robot-direct')", message="robot sur le plan")
    # le robot n'est pas sur l'accueil : clic puis glissé vers la droite de l'écran (l'est, cap 0)
    nav.clic("[data-role=pas-sur-marque]")
    assert nav.js("return document.querySelector('[data-role=aide-position]').hidden") is False
    assert nav.js("return document.querySelector('[data-role=vue]').dataset.vue") == "plan"
    nombre = len(relais.demandes)
    nav.geste("simulation", [[0.3, 0.5], [0.35, 0.5], [0.4, 0.5]])
    assert attendre(lambda: len(relais.demandes) > nombre, 15)
    d = relais.demandes[-1]
    assert {"x", "y", "theta"} <= set(d) and abs(d["theta"]) < 0.1
    nav.attendre("return document.querySelector('[data-role=etat-reperage]').textContent.startsWith('Repéré')",
                 delai=20, message="repéré à la position cliquée")
    # verrou du pont (ruban), retenu comme celui de l'ARRÊT
    nav.commande("navigation.bloquer")
    assert attendre(lambda: relais.verrous[-1:] == [True], 10)
    assert _api(base, "/api/arret")["par"] == "bloquer"
    nav.attendre("return document.querySelector('[data-role=arret]').dataset.etat === 'bloque'", message="bouton Débloquer")
    nav.commande("navigation.debloquer")
    assert attendre(lambda: relais.verrous[-1:] == [False], 10)
    nav.attendre("return document.querySelector('[data-role=arret]').dataset.etat === 'pret'", message="bouton ARRÊT")
    # arrêt de la répétition
    nav.commande("navigation.arreter")
    nav.attendre("return document.querySelector('[data-role=etat-simu]').textContent.startsWith('Répétition arrêtée')",
                 delai=30, message="répétition arrêtée")
    assert nav.js("return window.erreursAtelier") == []
    assert nav.messages("erreur") == []


class FauxPont:
    """Bouchon du contrat 12.9 : EXEMPLE_ETAT_PONT_V5 (état pas_en_marche, robot assis, mode 3) publié sur
    /pont/etat à 5 Hz, comme le pont de la vague 5 quand le robot n'est pas en mode marche."""

    def __init__(self, etat):
        import threading
        from rclpy.executors import SingleThreadedExecutor
        from std_msgs.msg import String
        import rclpy
        self.rclpy, self.String, self.etat = rclpy, String, etat
        self.contexte = rclpy.Context()
        rclpy.init(context=self.contexte)
        self.noeud = rclpy.create_node("faux_pont_v5_atelier", context=self.contexte)
        self.pub = self.noeud.create_publisher(String, "/pont/etat", 10)
        self.noeud.create_timer(0.2, lambda: self.pub.publish(self.String(data=json.dumps(self.etat))))
        self.executeur = SingleThreadedExecutor(context=self.contexte)
        self.executeur.add_node(self.noeud)
        self._fin = threading.Event()
        self._fil = threading.Thread(target=self._tourner, daemon=True)
        self._fil.start()

    def _tourner(self):
        while not self._fin.is_set():
            self.executeur.spin_once(timeout_sec=0.05)

    def fermer(self):
        self._fin.set()
        self._fil.join(timeout=3)
        self.executeur.shutdown()
        self.noeud.destroy_node()
        self.rclpy.shutdown(context=self.contexte)


@pytest.fixture
def faux_pont():
    from atelier.lieu import robot as R
    p = FauxPont(dict(R.EXEMPLE_ETAT_PONT_V5))
    yield p
    p.fermer()


def test_pont_pas_en_marche_dans_la_coque(faux_pont, serveur, navigateur, faux_bin):
    """Vague 5 (sections 12.6 et 12.9) : l'état pas_en_marche du pont se voit dans la barre d'outils (pastille
    Robot), dans Naviguer (pont vers la marche) et dans Piloter (l'alerte qui dit quoi faire)."""
    _, base = serveur
    nav = navigateur
    assert faux_pont.etat["etat"] == "pas_en_marche" and "assis" in faux_pont.etat["message"]
    ouvrir_espace(nav, base, mode="reel", repetition=True)
    pastille = nav.attendre("const p = document.querySelector('[data-role=barre-outils] [data-etat=robot]');"
                            "return p && !p.hidden && p.getAttribute('data-genre') === 'ko' ? [p.textContent, p.title] : null",
                            delai=20.0, message="pastille Robot « pas en marche »")
    assert "pas en marche" in pastille[0].lower() and "assis" in pastille[1], pastille
    nav.onglet("naviguer")
    texte = nav.attendre("const p = document.querySelector('.pastille-pont');"
                         "return p && p.textContent.indexOf('pas en mode marche') >= 0 ? p.textContent : null",
                         delai=15.0, message="Naviguer : pont pas en mode marche")
    assert "assis" in texte and "pont-ko" in nav.js("return document.querySelector('.pastille-pont').className")
    nav.onglet("piloter")
    alerte = nav.attendre("const a = document.querySelector('.alerte-mode');"
                          "return a && !a.hidden && a.textContent ? a.textContent : null", delai=15.0,
                          message="Piloter : alerte du mode du robot")
    assert "assis" in alerte and "télécommande" in alerte
    assert nav.js("return window.erreursAtelier") == []
