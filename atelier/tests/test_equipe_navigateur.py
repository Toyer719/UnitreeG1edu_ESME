"""Onglets Personnalités, Dialogues et Caméra dans Firefox sans fenêtre (vague 4, section 11.6 du
plan ; critère 30) : partir de l'exemple → enregistrer (fichier écrit et relu par l'API) →
« Rendre active » (annoncée sur /personnalite/active, reçue par un nœud ROS 2 du test) → une
phrase modifiée ; Dialogues : « Essayer » une phrase (réponse et action, sans robot), une
règle modifiée ; Caméra : préréglage See3CAM_11CUG, enregistrement, et un visiteur publié sur
/visiteurs/detectes dessiné en direct. Aucune erreur JavaScript dans la page.

Serveur : bin/g1-atelier, avec les fausses commandes g1-* et le pont ROS 2 du serveur, sur une
copie de demo. Sauté sans geckodriver, Firefox ou ROS 2. Domaine ROS : $ROS_DOMAIN_ID, 75 par
défaut (agent Équipe).
"""
import json
import os
import time
import urllib.error
import urllib.request

import pytest

os.environ.setdefault("ROS_DOMAIN_ID", "75")
pytest.importorskip("rclpy", reason="ROS 2 n'est pas chargé : source ~/robot-g1/setup/env.sh")

from atelier.lieu import equipe as E  # noqa: E402

from .test_equipe_serveur import Ecouteur  # noqa: E402
from .test_serveur_communs import attendre, faux_bin, journaux, lieux  # noqa: E402,F401
from .test_serveur_demarrage import serveur  # noqa: E402,F401
from .test_serveur_navigateur import GECKODRIVER, navigateur  # noqa: E402,F401

pytestmark = pytest.mark.skipif(GECKODRIVER is None, reason="geckodriver absent")

# Donne une valeur à un champ (input ou textarea) trouvé par son libellé dans le panneau, ou par
# un sélecteur ; déclenche « change », comme une saisie
CHAMP = """
const [selecteur, libelle, valeur] = arguments;
let c = null;
if (libelle) {
  const l = Array.from(document.querySelectorAll(selecteur + ' label.champ'))
    .find((x) => x.querySelector('.champ-libelle') && x.querySelector('.champ-libelle').textContent === libelle);
  c = l ? l.querySelector('input, textarea, select') : null;
} else {
  c = document.querySelector(selecteur);
}
if (!c) return false;
c.value = valeur;
c.dispatchEvent(new Event('input', { bubbles: true }));
c.dispatchEvent(new Event('change', { bubbles: true }));
return true;
"""


def _api(base, chemin):
    try:
        with urllib.request.urlopen(base + chemin, timeout=20) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"statut": e.code}


@pytest.fixture
def ecouteur():
    e = Ecouteur()
    yield e
    e.fermer()


def _ouvrir_onglet(nav, texte, ecran):
    nav.bouton(texte, ".onglets")
    nav.attendre(f"return document.querySelector('.ecran.ecran-{ecran}') && "
                 f"!document.querySelector('.ecran.chargement')", message=f"onglet {texte}")


def _enregistrer(nav, fichier):
    nav.bouton("Enregistrer", ".ecran .barre")
    nav.attendre("return document.querySelector('[data-role=etat]').textContent === 'Tout est enregistré'",
                 message=f"{fichier} enregistré")


def test_onglets_de_l_equipe(serveur, navigateur, ecouteur, lieux, faux_bin):
    _, base = serveur
    nav = navigateur
    nav.ouvrir(base + "/")
    nav.attendre("return document.querySelector('.onglet.actif') !== null", message="premier écran ouvert")
    nav.js("localStorage.setItem('atelier.lieu', 'demo'); localStorage.setItem('atelier.etage', 'rdc');")
    nav.ouvrir(base + "/?recharger=1#personnalites")
    nav.attendre("return document.querySelectorAll('.onglet').length === 12", message="onglets")
    nav.js("window.confirm = () => true;")
    # l'écran s'ouvre après le chargement du lieu mémorisé (asynchrone), puis lit son fichier
    nav.attendre("return document.querySelector('.ecran-personnalites [data-role=absent]') !== null && "
                 "!document.querySelector('.ecran.chargement')", message="onglet Personnalités ouvert")

    # ---------------------------------------------------------------- Personnalités
    assert _api(base, "/api/lieux/demo/personnalites") == {"statut": 404}
    assert "personnalites.yaml" in nav.js("return document.querySelector('[data-role=absent]').textContent")
    nav.bouton("Partir de l'exemple")
    nav.attendre("return document.querySelectorAll('.equipe-carte').length === 2", message="cartes de l'exemple")
    assert "non enregistrées" in nav.js("return document.querySelector('[data-role=etat]').textContent")
    _enregistrer(nav, "personnalites.yaml")
    assert _api(base, "/api/lieux/demo/personnalites") == E.exemple_equipe("personnalites")
    # rendre active « Discret » : écrite dans le fichier, annoncée sur /personnalite/active
    nav.bouton("Rendre active", ".equipe-cartes")
    assert attendre(lambda: _api(base, "/api/lieux/demo/personnalites")["active"] == "discret", 10)
    assert attendre(lambda: any(json.loads(m)["id"] == "discret" for m in ecouteur.personnalites), 10), \
        "rien de reçu sur /personnalite/active"
    m = json.loads(ecouteur.personnalites[-1])
    assert m["lieu"] == "demo" and m["vitesse_max"] == 0.25
    nav.attendre("return document.querySelector('.equipe-carte.active').dataset.id === 'discret'",
                 message="carte active")
    nav.attendre("return document.querySelector('[data-role=annonce]').textContent.includes('Discret (discret)')",
                 delai=10, message="annonce reçue par l'Atelier")
    # une phrase de la personnalité ouverte (l'active), puis enregistrer
    assert nav.js(CHAMP, ".ecran [data-role=panneau] [data-phrase=retour] input", None, "Je rentre au hall.")
    assert "non enregistrées" in nav.js("return document.querySelector('[data-role=etat]').textContent")
    _enregistrer(nav, "personnalites.yaml")
    discret = E.personnalite_active(_api(base, "/api/lieux/demo/personnalites"), "discret")
    assert discret["phrases"] == {"retour": "Je rentre au hall."}

    # ---------------------------------------------------------------- Dialogues
    _ouvrir_onglet(nav, "Dialogues", "dialogues")
    nav.bouton("Partir de l'exemple")
    nav.attendre("return document.querySelectorAll('[data-role=regles] tr[data-id]').length === 5",
                 message="règles de l'exemple")
    # essayer une phrase, sans robot ni enregistrement
    assert nav.js(CHAMP, "[data-role=phrase]", None, "Je cherche la salle B204, s'il vous plaît")
    nav.bouton("Essayer", "[data-role=essai]")
    nav.attendre("return document.querySelector('[data-role=resultat]').textContent.includes('Salle B204. Suivez-moi')",
                 message="réponse de l'essai")
    resultat = nav.js("return document.querySelector('[data-role=resultat]').textContent")
    assert "chercher_salle" in resultat and '"cible":"b204"' in resultat and "/guide/aller" in resultat
    # une règle modifiée dans l'onglet sert tout de suite à l'essai
    nav.bouton("bonjour", "[data-role=regles]")
    nav.attendre("return document.querySelector('[data-role=panneau]').textContent.includes('Règle « bonjour »')",
                 message="panneau de la règle")
    assert nav.js(CHAMP, "[data-role=panneau] [data-champ=reponse] textarea", None, "Bonjour, je suis le robot !")
    assert nav.js(CHAMP, "[data-role=phrase]", None, "salut")
    nav.bouton("Essayer", "[data-role=essai]")
    nav.attendre("return document.querySelector('[data-role=resultat]').textContent.includes('je suis le robot')",
                 message="essai avec la règle modifiée")
    _enregistrer(nav, "dialogues.yaml")
    d = _api(base, "/api/lieux/demo/dialogues")
    assert d["regles"][1]["reponse"] == "Bonjour, je suis le robot !" and len(d["regles"]) == 5
    # monter la règle « merci » d'un cran
    nav.js("document.querySelector('[data-role=regles] tr[data-id=merci] .equipe-deplacer button').click()")
    _enregistrer(nav, "dialogues.yaml")
    assert [r["id"] for r in _api(base, "/api/lieux/demo/dialogues")["regles"]][:3] == [
        "chercher_salle", "merci", "bonjour"]

    # ---------------------------------------------------------------- Caméra
    _ouvrir_onglet(nav, "Caméra", "camera")
    nav.bouton("Partir de l'exemple")
    nav.attendre("return document.querySelector('[data-role=vue-dessus] [data-role=champ]') !== null",
                 message="vue de dessus avec le champ de la caméra")
    nav.bouton("Préréglage See3CAM_11CUG")
    _enregistrer(nav, "camera.yaml")
    c = _api(base, "/api/lieux/demo/camera")
    assert c["camera"]["modele"] == "See3CAM_11CUG" and (c["camera"]["largeur"], c["camera"]["hauteur"]) == (1280, 720)
    # tangage saisi en degrés, enregistré en radians
    assert nav.js(CHAMP, ".ecran [data-role=panneau]", "Tangage", "-12")
    _enregistrer(nav, "camera.yaml")
    assert abs(_api(base, "/api/lieux/demo/camera")["camera"]["position"]["tangage"] + 0.2094) < 1e-3
    # un visiteur publié par « la caméra de l'équipe » est dessiné en direct
    vus = {"version": 1, "source": "camera", "temps": 1.0, "personnes": [
        {"id": 7, "x": 1.5, "y": 0.3, "distance_m": 1.53, "angle_rad": 0.197, "confiance": 0.9}]}

    def dessine():
        ecouteur.publier(ecouteur.pub_visiteurs, vus)
        return nav.js("return document.querySelector('[data-role=detections]').dataset.visiteurs === '1' && "
                      "document.querySelectorAll('[data-role=vue-dessus] circle.cam-visiteur').length === 1")
    assert attendre(dessine, 15, 0.3), nav.js("return document.querySelector('[data-role=detections]').textContent")
    assert "1 visiteur vu par la caméra" in nav.js("return document.querySelector('[data-role=detections]').textContent")

    # ---------------------------------------------------------------- aucune erreur dans la page
    assert nav.js("return window.erreursAtelier") == []
    assert nav.js("return document.querySelectorAll('.message-erreur').length") == 0
    time.sleep(0.1)
