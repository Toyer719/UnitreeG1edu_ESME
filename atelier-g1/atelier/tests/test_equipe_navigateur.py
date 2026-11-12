"""Équipe › Personnalités, Dialogues et Caméra dans Firefox sans fenêtre (vague 4, section 11.6 du plan,
critère 30 ; coque de la vague 5, section 12.2 : la liste dans la vue, la fiche choisie dans le panneau,
✓ Enregistrer et ✗ Annuler) : partir de l'exemple → ✓ (fichier écrit et relu par l'API) → « Rendre active »
(annoncée sur /personnalite/active, reçue par un nœud ROS 2 du test) → une phrase modifiée (bloc « Phrases
pendant une visite ») ; Dialogues : « Essayer » une phrase (réponse et action, sans robot), une règle
modifiée ; Caméra : préréglage See3CAM_11CUG, enregistrement, et un visiteur publié sur /visiteurs/detectes
dessiné en direct. Aucune erreur JavaScript dans la page.

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
from .test_serveur_navigateur import GECKODRIVER, navigateur, ouvrir_espace  # noqa: E402,F401

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
BOUTON = """
const [dans, texte] = arguments;
const b = Array.from(document.querySelectorAll(dans + ' button')).find((x) => x.textContent.trim() === texte && !x.disabled);
if (!b) return false;
b.click();
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


def _enregistrer(nav, fichier):
    """✓ Enregistrer du panneau ; pour un écran sans ✓ (caméra), le bouton de sa barre, ou celui de la barre d'outils."""
    if nav.js("const b = document.querySelector('[data-role=ok]'); return !!b && !b.hidden && !b.disabled"):
        nav.ok()
    elif nav.js("return !!document.querySelector('[data-role=vue-plan] .barre [data-role=enregistrer]')"):
        nav.clic("[data-role=vue-plan] .barre [data-role=enregistrer]")
    else:
        nav.clic("[data-role=barre-outils] [data-role=enregistrer]")
    nav.attendre("return document.querySelector('[data-role=vue-plan] [data-role=etat]').textContent === 'Tout est enregistré'",
                 message=f"{fichier} enregistré")


def test_ecrans_de_l_equipe(serveur, navigateur, ecouteur, lieux, faux_bin):
    _, base = serveur
    nav = navigateur
    ouvrir_espace(nav, base, mode="simu", hash_="#personnalites")
    nav.ecran("personnalites")
    assert nav.js("return document.querySelector('[data-onglet=equipe]').getAttribute('aria-selected')") == "true"
    assert nav.js("return document.querySelector('[data-commande=\"personnalites.ouvrir\"]').getAttribute('aria-pressed')") == "true"
    nav.attendre("return document.querySelector('[data-ecran=personnalites] [data-role=absent]') !== null && "
                 "!document.querySelector('[data-ecran=personnalites] [data-role=absent]').hidden",
                 message="écran Personnalités ouvert")

    # ---------------------------------------------------------------- Personnalités
    assert _api(base, "/api/lieux/demo/personnalites") == {"statut": 404}
    # pas de nom de fichier dans les titres (section 12.2) : il est dans l'infobulle du titre
    assert "Pas encore de personnalités" in nav.js("return document.querySelector('[data-role=absent]').textContent")
    assert "personnalites.yaml" in nav.js("return document.querySelector('[data-ecran=personnalites] [data-role=titre]').title")
    assert nav.js("return document.querySelector('[data-ecran=personnalites] [data-role=fichier]').hidden")
    assert nav.js(BOUTON, "[data-role=absent]", "Partir de l'exemple")
    nav.attendre("return document.querySelectorAll('.equipe-carte').length === 2", message="cartes de l'exemple")
    assert "non enregistrées" in nav.js("return document.querySelector('[data-ecran=personnalites] [data-role=etat]').textContent")
    nav.attendre("return !document.querySelector('[data-role=ok]').disabled", message="✓ actif")
    _enregistrer(nav, "personnalites.yaml")
    assert _api(base, "/api/lieux/demo/personnalites") == E.exemple_equipe("personnalites")
    # rendre active « Discret » : écrite dans le fichier, annoncée sur /personnalite/active
    assert nav.js(BOUTON, ".equipe-cartes", "Rendre active")
    assert attendre(lambda: _api(base, "/api/lieux/demo/personnalites")["active"] == "discret", 10)
    assert attendre(lambda: any(json.loads(m)["id"] == "discret" for m in ecouteur.personnalites), 10), \
        "rien de reçu sur /personnalite/active"
    m = json.loads(ecouteur.personnalites[-1])
    assert m["lieu"] == "demo" and m["vitesse_max"] == 0.25
    nav.attendre("return document.querySelector('.equipe-carte.active').dataset.id === 'discret'",
                 message="carte active")
    nav.attendre("return document.querySelector('[data-role=annonce]').textContent.includes('Discret (discret)')",
                 delai=10, message="annonce reçue par l'Atelier")
    # une phrase de la personnalité ouverte (l'active), dans le panneau, puis ✓
    assert nav.js("return document.querySelector('[data-role=panneau-titre]').textContent").startswith("Discret")
    assert nav.js(CHAMP, "[data-role=panneau-corps] [data-phrase=retour] input", None, "Je rentre au hall.")
    assert "non enregistrées" in nav.js("return document.querySelector('[data-ecran=personnalites] [data-role=etat]').textContent")
    _enregistrer(nav, "personnalites.yaml")
    discret = E.personnalite_active(_api(base, "/api/lieux/demo/personnalites"), "discret")
    assert discret["phrases"] == {"retour": "Je rentre au hall."}

    # ---------------------------------------------------------------- Dialogues
    nav.commande("dialogues.ouvrir")
    nav.ecran("dialogues")
    assert nav.js(BOUTON, "[data-role=absent]", "Partir de l'exemple")
    nav.attendre("return document.querySelectorAll('[data-role=regles] tr[data-id]').length === 5",
                 message="règles de l'exemple")
    # essayer une phrase, sans robot ni enregistrement
    assert nav.js(CHAMP, "[data-role=phrase]", None, "Je cherche la salle B204, s'il vous plaît")
    assert nav.js(BOUTON, "[data-role=essai]", "Essayer")
    nav.attendre("return document.querySelector('[data-role=resultat]').textContent.includes('Salle B204. Suivez-moi')",
                 message="réponse de l'essai")
    resultat = nav.js("return document.querySelector('[data-role=resultat]').textContent")
    assert "chercher_salle" in resultat and '"cible":"b204"' in resultat and "/guide/aller" in resultat
    # une règle modifiée dans le panneau sert tout de suite à l'essai
    assert nav.js(BOUTON, "[data-role=regles]", "bonjour")
    nav.attendre("return document.querySelector('[data-role=panneau-titre]').textContent.includes('Règle « bonjour »')",
                 message="panneau de la règle")
    assert nav.js(CHAMP, "[data-role=panneau-corps] [data-champ=reponse] textarea", None, "Bonjour, je suis le robot !")
    assert nav.js(CHAMP, "[data-role=phrase]", None, "salut")
    assert nav.js(BOUTON, "[data-role=essai]", "Essayer")
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

    # ---------------------------------------------------------------- Caméra (écran de l'agent Caméra)
    nav.commande("camera.ouvrir")
    nav.ecran("camera")
    assert nav.js(BOUTON, "[data-role=absent]", "Partir de l'exemple")
    nav.attendre("return document.querySelector('[data-role=vue-dessus] [data-role=champ]') !== null",
                 message="vue de dessus avec le champ de la caméra")
    assert nav.js("const b = Array.from(document.querySelectorAll('button')).find((x) => "
                  "x.textContent.trim() === 'Préréglage See3CAM_11CUG'); if (b) b.click(); return !!b;")
    _enregistrer(nav, "camera.yaml")
    c = _api(base, "/api/lieux/demo/camera")
    assert c["camera"]["modele"] == "See3CAM_11CUG" and (c["camera"]["largeur"], c["camera"]["hauteur"]) == (1280, 720)
    # tangage saisi en degrés, enregistré en radians
    assert nav.js(CHAMP, "[data-role=panneau-corps]", "Tangage", "-12") or nav.js(CHAMP, "[data-ecran=camera]", "Tangage", "-12")
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
    assert nav.messages("erreur") == []
    time.sleep(0.1)
