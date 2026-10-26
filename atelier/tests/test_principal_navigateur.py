"""Le point principal dans le navigateur (vague 4, section 11.2 du plan), Firefox sans fenêtre :

  - onglet Salles : l'étoile et le badge « principal » ; sa flèche se tourne en glissant sa poignée
    (par pas de 15°) ; « Faire de cette salle le point principal » ; supprimer le point principal est
    refusé, avec un message qui dit quoi faire ; « Enregistrer les salles » recopie sa pose dans
    l'accueil de lieu.yaml et le départ du robot ;
  - onglet Monde : le départ du robot affiché « = point principal », et l'outil « Départ du robot »
    qui déplace le point principal à l'enregistrement du monde ;
  - onglet Simulation, mode « Répétition sans robot » : « Posez le robot sur le point principal… »,
    le cercle autour de l'étoile, le lien « Le robot n'est pas sur le point principal ».

Serveur : bin/g1-atelier sur une copie du demo, fausses commandes g1-*, sans pont ROS 2.
Sauté sans geckodriver ou Firefox.
"""
import json
import math
import urllib.request

import pytest

from .test_serveur_communs import faux_bin, journaux, lieux  # noqa: F401
from .test_serveur_demarrage import serveur  # noqa: F401
from .test_serveur_navigateur import GECKODRIVER, navigateur, sans_ros  # noqa: F401

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


def _sans_erreur(nav):
    assert nav.js("return window.erreursAtelier") == []
    erreurs = nav.js("return Array.from(document.querySelectorAll('.message-erreur')).map(e => e.textContent)")
    assert erreurs == [], erreurs


def test_point_principal_dans_les_onglets(sans_ros, serveur, navigateur, lieux, faux_bin):
    _, base = serveur
    nav = navigateur
    _api(base, "/api/lieux/demo/etages/rdc/monde/generer", {})
    nav.ouvrir(base + "/")
    nav.attendre("return document.querySelector('.onglet.actif') !== null", message="premier écran ouvert")
    nav.js("localStorage.setItem('atelier.lieu', 'demo'); localStorage.setItem('atelier.etage', 'rdc');"
           "localStorage.setItem('atelier.mode-simulation', 'simu');")
    nav.ouvrir(base + "/?recharger=1#salles")

    # --- Salles : l'étoile, le badge, la flèche
    nav.attendre("return document.querySelectorAll('.ecran-salles .leaflet-marker-icon.salle').length === 6",
                 message="six salles")
    assert nav.js("return document.querySelectorAll('.ecran-salles .leaflet-marker-icon.salle.principal').length") == 1
    assert nav.js("return document.querySelector('.ecran-salles .leaflet-marker-icon.salle.principal').title") == \
        "Accueil (point principal)"
    assert nav.js("return document.querySelector('.ecran-salles .etoile-principal').textContent") == "★"
    # (Leaflet efface en fondu, en 200 ms, les étiquettes d'un dessin précédent : on attend)
    nav.attendre("const b = Array.from(document.querySelectorAll('.ecran-salles .leaflet-tooltip .badge-principal'))"
                 ".map((x) => x.parentNode.textContent); return b.length === 1 && b[0] === 'principal Accueil'",
                 message="badge « principal » à côté de l'accueil")
    assert "principal" in nav.js("return document.querySelector('.ecran-salles .liste-choix').textContent")
    # la flèche (poignée) glissée vers le haut de l'écran : le nord, 90°, par pas de 15°
    nav.attendre("return document.querySelector('.ecran-salles .poignee-principal')", message="flèche du principal")
    assert nav.js(GLISSER, ".ecran-salles .poignee-principal", -40, -60)
    nav.attendre("return document.querySelector('.ecran-salles [data-role=etat]').textContent.includes('non enregistrées')",
                 message="flèche tournée")
    # b204 devient le point principal
    nav.js("document.querySelector('.ecran-salles .leaflet-marker-icon[title=\"Salle B204\"]').click()")
    nav.bouton("Faire de cette salle le point principal", ".ecran-salles .panneau")
    nav.attendre("return document.querySelector('.ecran-salles .leaflet-marker-icon.salle.principal').title "
                 "=== 'Salle B204 (point principal)'", message="b204 principal")
    assert nav.js("return document.querySelectorAll('.ecran-salles .leaflet-marker-icon.salle.principal').length") == 1
    assert nav.js("return document.querySelector('.ecran-salles .panneau .badge-principal') !== null")
    # supprimer le point principal : refusé, avec un message clair
    nav.bouton("Supprimer la salle", ".ecran-salles .panneau")
    nav.attendre("return Array.from(document.querySelectorAll('.message-erreur')).some((m) => "
                 "m.textContent.includes('est le point principal du lieu') && "
                 "m.textContent.includes('choisissez d\\'abord un autre point principal'.replace('choisissez', 'Choisissez')))",
                 message="suppression du principal refusée")
    nav.js("document.querySelectorAll('.message-erreur').forEach((m) => m.remove())")
    assert nav.js("return document.querySelectorAll('.ecran-salles .leaflet-marker-icon.salle').length") == 6
    nav.bouton("Enregistrer les salles")
    nav.attendre("return document.querySelector('.ecran-salles [data-role=etat]').textContent.includes('Tout est')",
                 message="salles enregistrées")
    principal = _api(base, "/api/lieux/demo/principal")
    assert principal["salle"] == "b204" and principal["explicite"] and principal["depart_synchro"]
    salles = {s["id"]: s for s in _api(base, "/api/lieux/demo/salles")}
    assert "principal" not in salles["accueil"].get("etiquettes", [])
    theta = salles["accueil"]["pose"]["theta"]
    assert theta != 0.0 and abs(math.degrees(theta) / 15 - round(math.degrees(theta) / 15)) < 1e-3, theta   # pas de 15°
    fiche = _api(base, "/api/lieux/demo")
    assert fiche["accueil"] == {"etage": "rdc", "x": 21.0, "y": 13.0, "theta": 1.5708}
    assert _api(base, "/api/lieux/demo/etages/rdc/monde")["depart_robot"] == {"x": 21.0, "y": 13.0, "theta": 1.5708}

    # --- Monde : le départ du robot est le point principal
    nav.bouton("Monde", ".onglets")
    nav.attendre("return document.querySelector('.ecran-monde .depart-principal')", message="départ = principal")
    assert "= point principal « Salle B204 »" in nav.js(
        "return document.querySelector('.ecran-monde .depart-principal').textContent")
    assert nav.js("return document.querySelector('.ecran-monde path.robot.principal') !== null")
    nav.bouton("Départ du robot", ".groupe-outils")
    assert "point principal « Salle B204 »" in nav.js("return document.querySelector('.ecran-monde [data-role=aide]').textContent")
    nav.geste("monde", [[0.5, 0.5], [0.55, 0.5], [0.6, 0.5]])          # vers la droite de l'écran : l'est
    nav.bouton("Enregistrer le monde")
    nav.attendre("return document.querySelector('.ecran-monde [data-role=etat]').textContent.includes('Tout est')",
                 message="monde enregistré")
    nav.attendre("return Array.from(document.querySelectorAll('.message')).some((m) => "
                 "m.textContent.includes('a suivi le départ du robot'))", message="le principal a suivi")
    depart = _api(base, "/api/lieux/demo/etages/rdc/monde")["depart_robot"]
    principal = _api(base, "/api/lieux/demo/principal")
    assert (principal["x"], principal["y"], principal["theta"]) == (depart["x"], depart["y"], depart["theta"])
    assert (principal["x"], principal["y"]) != (21.0, 13.0) and abs(depart["theta"]) < 1e-6
    assert principal["salle"] == "b204" and principal["depart_synchro"]
    assert _api(base, "/api/lieux/demo/itineraires")["noeuds"]["b204"]["x"] == principal["x"]

    # --- Simulation, répétition : poser le robot sur le point principal
    nav.bouton("Simulation", ".onglets")
    nav.bouton("Répétition sans robot", ".modes-simulation")
    nav.attendre("return !document.querySelector('[data-role=reperage]').hidden", message="panneau Repérage")
    nav.attendre("return document.querySelector('[data-role=consigne-reperage]').textContent.includes('Salle B204')",
                 message="consigne du repérage")
    assert nav.js("return document.querySelector('[data-role=consigne-reperage]').textContent") == (
        "Posez le robot sur le point principal « Salle B204 » (étoile sur la carte), tourné dans le sens de la flèche.")
    assert nav.js("return document.querySelector('[data-role=pas-sur-marque]').textContent") == \
        "Le robot n'est pas sur le point principal"
    nav.attendre("return document.querySelector('.ecran-simulation path.marque-principal')", message="cercle du principal")
    assert nav.js("return document.querySelectorAll('.ecran-simulation .leaflet-marker-icon.salle.principal').length") == 1
    assert nav.js("return document.querySelector('.ecran-simulation .marque-sol')") is None
    nav.bouton("Simulation", ".modes-simulation")
    assert nav.js("return document.querySelector('[data-role=reperage]').hidden") is True
    _sans_erreur(nav)
