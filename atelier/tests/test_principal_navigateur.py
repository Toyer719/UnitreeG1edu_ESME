"""Le point principal (l'accueil) dans le navigateur (vague 4, section 11.2 du plan ; coque de la vague 5,
section 12.2), Firefox sans fenêtre :

  - Placer (plan 2D) : l'étoile et le badge « principal » ; sa flèche se tourne en glissant sa poignée
    (par pas de 15°) ; « Faire de cette salle l'accueil » ; supprimer l'accueil est refusé, avec un message
    qui dit quoi faire ; ✓ Enregistrer recopie sa pose dans l'accueil de lieu.yaml et le départ du robot ;
  - Dessiner : le départ du robot affiché « = point principal », et l'outil « Départ » qui déplace
    l'accueil à l'enregistrement du monde ;
  - Réel › Naviguer (répétition) : « Posez le robot sur l'accueil… », le cercle autour de l'étoile, le lien
    « Le robot n'est pas sur l'accueil ».

Serveur : bin/g1-atelier sur une copie du demo, fausses commandes g1-*, sans pont ROS 2.
Sauté sans geckodriver ou Firefox.
"""
import json
import math
import urllib.request

import pytest

from .test_serveur_communs import faux_bin, journaux, lieux  # noqa: F401
from .test_serveur_demarrage import serveur  # noqa: F401
from .test_serveur_navigateur import GECKODRIVER, navigateur, ouvrir_espace, sans_ros  # noqa: F401

pytestmark = pytest.mark.skipif(GECKODRIVER is None, reason="geckodriver absent")

# Glisser un marqueur Leaflet (L.Draggable écoute mousedown, puis mousemove et mouseup sur le document) :
# du centre de l'élément, de dx, dy pixels, en quelques pas. Comme dans un vrai navigateur, chaque
# événement vise l'élément sous le pointeur (Leaflet lit la classe de cette cible)
GLISSER = """
const [selecteur, dx, dy] = arguments;
const e = document.querySelector(selecteur);
if (!e) return false;
const r = e.getBoundingClientRect();
const x0 = r.left + r.width / 2, y0 = r.top + r.height / 2;
const souris = (cible, type, x, y, boutons) => cible.dispatchEvent(new MouseEvent(type, {
  bubbles: true, cancelable: true, view: window, button: 0, buttons: boutons, which: 1, clientX: x, clientY: y}));
souris(e, 'mousedown', x0, y0, 1);
const sous = (x, y) => document.elementFromPoint(x, y) || e;
for (let i = 1; i <= 6; i++) souris(sous(x0 + dx * i / 6, y0 + dy * i / 6), 'mousemove', x0 + dx * i / 6, y0 + dy * i / 6, 1);
souris(sous(x0 + dx, y0 + dy), 'mouseup', x0 + dx, y0 + dy, 0);
return true;
"""


def _api(base, chemin, corps=None, methode=None):
    r = urllib.request.Request(base + chemin, method=methode or ("GET" if corps is None else "POST"),
                               data=None if corps is None else json.dumps(corps).encode(),
                               headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=20) as reponse:
        return json.loads(reponse.read())


def test_point_principal_dans_la_coque(sans_ros, serveur, navigateur, lieux, faux_bin):
    _, base = serveur
    nav = navigateur
    _api(base, "/api/lieux/demo/etages/rdc/monde/generer", {})
    ouvrir_espace(nav, base, mode="simu", hash_="#salles")
    nav.ecran("salles")

    # --- Placer : l'étoile, le badge, la flèche (plan 2D, outil « choisir »)
    assert nav.js("return document.querySelector('[data-commande=\"salles.salle\"]').getAttribute('aria-pressed')") == "true"
    nav.commande("salles.salle")                 # deuxième clic : retour à « choisir »
    nav.vue("plan")
    nav.attendre("return document.querySelectorAll('[data-ecran=salles] .leaflet-marker-icon.salle').length === 6",
                 message="six salles")
    assert nav.js("return document.querySelectorAll('[data-ecran=salles] .leaflet-marker-icon.salle.principal').length") == 1
    assert nav.js("return document.querySelector('[data-ecran=salles] .leaflet-marker-icon.salle.principal').title") == \
        "Accueil (point principal)"
    assert nav.js("return document.querySelector('[data-ecran=salles] .etoile-principal').textContent") == "★"
    nav.attendre("const b = Array.from(document.querySelectorAll('[data-ecran=salles] .leaflet-tooltip .badge-principal'))"
                 ".map((x) => x.parentNode.textContent); return b.length === 1 && b[0] === 'principal Accueil'",
                 message="badge « principal » à côté de l'accueil")
    assert nav.js("return document.querySelector('[data-role=panneau-corps] [data-salle=accueil] .badge-principal') !== null")
    # la flèche (poignée) glissée vers le haut de l'écran : le nord, par pas de 15°
    nav.attendre("return document.querySelector('[data-ecran=salles] .poignee-principal')", message="flèche de l'accueil")
    assert nav.js(GLISSER, "[data-ecran=salles] .poignee-principal", -40, -60)
    nav.attendre("return !document.querySelector('[data-role=ok]').disabled", message="flèche tournée")
    # b204 devient l'accueil
    nav.js("document.querySelector('[data-ecran=salles] .leaflet-marker-icon[title=\"Salle B204\"]').click()")
    nav.clic("[data-role=panneau-corps] .bouton-faire-principal")
    nav.attendre("return document.querySelector('[data-ecran=salles] .leaflet-marker-icon.salle.principal').title "
                 "=== 'Salle B204 (point principal)'", message="b204 accueil")
    assert nav.js("return document.querySelectorAll('[data-ecran=salles] .leaflet-marker-icon.salle.principal').length") == 1
    assert nav.js("return document.querySelector('[data-role=panneau-corps] .badge-principal') !== null")
    # supprimer l'accueil : refusé, avec un message clair
    nav.clic("[data-role=panneau-corps] [data-role=supprimer-salle]")
    nav.attendre("return Array.from(document.querySelectorAll('[data-role=journal] .message-erreur')).some((m) => "
                 "m.textContent.includes('est le point principal du lieu') && "
                 "m.textContent.includes('Choisissez d\\'abord un autre point principal'))",
                 message="suppression de l'accueil refusée")
    assert nav.js("return document.querySelectorAll('[data-ecran=salles] .leaflet-marker-icon.salle').length") == 6
    nav.ok()
    nav.attendre("return document.querySelector('[data-role=ok]').disabled", message="salles enregistrées")
    principal = _api(base, "/api/lieux/demo/principal")
    assert principal["salle"] == "b204" and principal["explicite"] and principal["depart_synchro"]
    salles = {s["id"]: s for s in _api(base, "/api/lieux/demo/salles")}
    assert "principal" not in salles["accueil"].get("etiquettes", [])
    theta = salles["accueil"]["pose"]["theta"]
    assert theta != 0.0 and abs(math.degrees(theta) / 15 - round(math.degrees(theta) / 15)) < 1e-3, theta   # pas de 15°
    fiche = _api(base, "/api/lieux/demo")
    assert fiche["accueil"] == {"etage": "rdc", "x": 21.0, "y": 13.0, "theta": 1.5708}
    assert _api(base, "/api/lieux/demo/etages/rdc/monde")["depart_robot"] == {"x": 21.0, "y": 13.0, "theta": 1.5708}

    # --- Dessiner : le départ du robot est l'accueil
    nav.commande("monde.choisir")
    nav.ecran("monde")
    nav.vue("plan")
    nav.attendre("return document.querySelector('[data-ecran=monde] .depart-principal')", message="départ = accueil")
    assert "= point principal « Salle B204 »" in nav.js(
        "return document.querySelector('[data-ecran=monde] .depart-principal').textContent")
    assert nav.js("return document.querySelector('[data-ecran=monde] path.robot.principal') !== null")
    nav.commande("monde.depart")
    assert "« Salle B204 »" in nav.js("return document.querySelector('[data-role=etat-outil]').textContent")
    nav.geste("monde", [[0.5, 0.5], [0.55, 0.5], [0.6, 0.5]])          # vers la droite de l'écran : l'est
    nav.ok()
    nav.attendre("return document.querySelector('[data-role=ok]').disabled", message="monde enregistré")
    nav.attendre("return Array.from(document.querySelectorAll('[data-role=journal] .message')).some((m) => "
                 "m.textContent.includes('a suivi le départ du robot'))", message="l'accueil a suivi")
    depart = _api(base, "/api/lieux/demo/etages/rdc/monde")["depart_robot"]
    principal = _api(base, "/api/lieux/demo/principal")
    assert (principal["x"], principal["y"], principal["theta"]) == (depart["x"], depart["y"], depart["theta"])
    assert (principal["x"], principal["y"]) != (21.0, 13.0) and abs(depart["theta"]) < 1e-6
    assert principal["salle"] == "b204" and principal["depart_synchro"]
    assert _api(base, "/api/lieux/demo/itineraires")["noeuds"]["b204"]["x"] == principal["x"]

    # --- Réel › Naviguer (répétition) : poser le robot sur l'accueil
    ouvrir_espace(nav, base, mode="reel", repetition=True, hash_="#simulation")
    nav.ecran("simulation")
    nav.attendre("return document.querySelector('[data-role=consigne-reperage]').textContent.includes('Salle B204')",
                 message="consigne du repérage")
    assert nav.js("return document.querySelector('[data-role=consigne-reperage]').textContent") == (
        "Posez le robot sur l'accueil « Salle B204 » (étoile sur la carte), tourné dans le sens de la flèche.")
    assert nav.js("return document.querySelector('[data-role=pas-sur-marque]').textContent") == \
        "Le robot n'est pas sur l'accueil"
    nav.vue("plan")
    nav.attendre("return document.querySelector('[data-ecran=simulation] path.marque-principal')", message="cercle de l'accueil")
    assert nav.js("return document.querySelectorAll('[data-ecran=simulation] .leaflet-marker-icon.salle.principal').length") == 1
    assert nav.js("return document.querySelector('[data-ecran=simulation] .marque-sol')") is None
    assert nav.js("return window.erreursAtelier") == []
    erreurs = [m for m in nav.messages("erreur") if "point principal du lieu" not in m]
    assert erreurs == [], erreurs
