"""Réel › Piloter dans Firefox sans fenêtre (section 11.5 du plan, critère 29 pour l'aperçu 3D ; coque de la
vague 5, section 12.2 : postures et gestes dans le ruban, deux joysticks sur la vue, Danses et Chorégraphies
dans le groupe « Spectacle », l'ARRÊT de la barre d'outils, les confirmations dans la page).

Serveur : bin/g1-atelier (sans ROS), relié au nœud pilotage en mémoire de test_pilotage_serveur
(logique, cœur et API tornado réels, faux G1 en mémoire). Parcours, sans lieu (« Piloter le robot sans
lieu ») : état et « Prendre la main », posture (menu du ruban), joystick tactile (événements pointeur), ARRÊT,
portique (case puis confirmation), danses (liste, interdites, zone libre), « Chorégraphies » (aperçu 3D qui
avance, interpolation identique à celle du nœud). Sauté sans geckodriver ou Firefox.
"""
import json
import shutil
import time
import urllib.request

import pytest

from atelier.lieu import pilotage as D

from .test_pilotage_serveur import NoeudEnMemoire
from .test_serveur_communs import attendre, faux_bin, journaux, lieux  # noqa: F401
from .test_serveur_demarrage import serveur  # noqa: F401
from .test_serveur_navigateur import GECKODRIVER, navigateur  # noqa: F401

pytestmark = pytest.mark.skipif(GECKODRIVER is None or shutil.which("firefox") is None,
                                reason="geckodriver ou Firefox absent")

APPUI = """
const [selecteur, fx, fy, relacher] = arguments;
const zone = document.querySelector(selecteur);
const r = zone.getBoundingClientRect();
const ev = (type, boutons) => zone.dispatchEvent(new PointerEvent(type, {
  bubbles: true, cancelable: true, pointerId: 3, pointerType: 'touch', isPrimary: true, button: 0,
  buttons: boutons, clientX: r.left + fx * r.width, clientY: r.top + fy * r.height}));
if (relacher) { ev('pointerup', 0); return true; }
ev('pointerdown', 1);
ev('pointermove', 1);
return true;
"""

MODES_MARCHE = (500, 501, 801)


@pytest.fixture
def noeud(tmp_path, monkeypatch):
    n = NoeudEnMemoire().demarrer()
    dossier = tmp_path / "choregraphies"
    (dossier / "musique").mkdir(parents=True)
    exemple = D.chemin_choregraphie("exemple_kpop")
    (dossier / exemple.name).write_text(exemple.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv("G1_PILOTAGE_URL", f"http://127.0.0.1:{n.port}")
    monkeypatch.setenv("G1_PILOTAGE_JETON", "")
    monkeypatch.setenv("ATELIER_CHOREGRAPHIES", str(dossier))
    monkeypatch.setenv("ATELIER_ROS", "0")
    yield n
    n.arreter()


def _api(base, chemin):
    with urllib.request.urlopen(base + chemin, timeout=20) as r:
        return json.loads(r.read())


def confirmer(nav):
    """Accepte la fenêtre de confirmation de la page (à la place de window.confirm)."""
    nav.attendre("return document.querySelector('[data-role=confirmation] [data-role=confirmer]')", message="confirmation")
    nav.js("document.querySelector('[data-role=confirmation] [data-role=confirmer]').click()")


def test_piloter(noeud, serveur, navigateur):
    _, base = serveur
    nav = navigateur
    # « Piloter le robot sans lieu » depuis l'accueil
    nav.ouvrir(base + "/")
    nav.attendre("return document.querySelector('[data-role=pilotage-sans-lieu]')", message="accueil")
    nav.clic("[data-role=pilotage-sans-lieu]")
    nav.ecran("pilotage")
    assert nav.js("return document.querySelector('[data-role=espace]').dataset.mode") in ("reel", "repetition")
    assert nav.js("return document.querySelector('[data-onglet=piloter]').getAttribute('aria-selected')") == "true"
    # sans lieu : les commandes qui travaillent sur un lieu sont grisées, avec la raison
    assert nav.js("const b = document.querySelector('[data-onglet=placer]'); b.click();"
                  "return document.querySelector('[data-commande=\"salles.salle\"]').disabled")
    nav.onglet("piloter")
    nav.attendre("return document.querySelector('.pastille-pilotage').textContent.includes('Robot relié')",
                 message="robot relié")
    assert nav.js("return document.querySelector('[data-commande=\"pilotage.postures\"]').title").startswith("Prenez")
    # prendre la main
    nav.commande("pilotage.main")
    nav.attendre("return document.querySelector('.etat-maitre').textContent === 'Vous avez la main'", message="la main")
    assert noeud.coeur.logique.a_la_main()
    nav.attendre("return document.querySelector('[data-commande=\"pilotage.main\"] .commande-libelle').textContent "
                 "=== 'Rendre la main'", message="libellé du ruban")
    # posture « Démarrer » par le menu du ruban, puis le joystick tactile (manche tenu vers l'avant 1 s)
    nav.commande("pilotage.postures", 500)
    assert attendre(lambda: noeud.robot.fsm in MODES_MARCHE and noeud.coeur.logique.fsm in MODES_MARCHE, 5, 0.1)
    nav.attendre("return !document.querySelector('.pilotage-postures .mouvement').disabled", message="boutons de mouvement actifs")
    debut = time.monotonic()
    nav.js(APPUI, ".joystick-pave", 0.5, 0.0, False)
    time.sleep(1.2)
    nav.js(APPUI, ".joystick-pave", 0.5, 0.0, True)
    time.sleep(0.6)
    marche = noeud.marche(debut)
    avant = [o for _, o in marche if o["velocity"][0] > 0]
    assert len(avant) >= 6, marche
    assert all(o["velocity"][0] <= D.LIMITES_MARCHE["vx"] + 1e-9 and o["duration"] == 0.5 for o in avant)
    assert marche[-1][1]["velocity"] == [0.0, 0.0, 0.0]               # lâché : arrêt
    # manche tenu (un pouce), puis ARRÊT de l'autre main : la manette est lâchée par la page, plus aucun
    # ordre de marche ne part tant que le pouce n'a pas été relevé puis reposé
    nav.js(APPUI, ".joystick-pave", 0.5, 0.0, False)
    time.sleep(0.6)
    assert [o for _, o in noeud.marche(time.monotonic() - 0.4) if o["velocity"][0] > 0], "le manche tenu n'avance pas"
    nav.clic("[data-role=arret]")
    clic = time.monotonic()
    time.sleep(1.5)
    apres = [o for _, o in noeud.marche(clic + 0.3) if o["velocity"][0] > 0]
    assert not apres, f"ordres de marche après l'ARRÊT, manche encore tenu : {apres[:3]}"
    nav.js(APPUI, ".joystick-pave", 0.5, 0.0, True)
    # posture au portique (Avancé) : la case d'abord, puis la confirmation dans la page
    nav.commande("pilotage.portique")
    nav.attendre("return document.querySelector('.zone-portique')", message="section portique")
    nav.js("document.querySelector('.zone-portique [data-fsm=\"1\"]').click()")
    time.sleep(0.5)
    assert noeud.robot.fsm in MODES_MARCHE                              # case décochée : rien
    nav.js("document.querySelector('.zone-portique input[type=checkbox]').click()")
    nav.js("document.querySelector('.zone-portique [data-fsm=\"1\"]').click()")
    confirmer(nav)
    attendre(lambda: noeud.robot.fsm == 1, 5, 0.1)
    nav.commande("pilotage.postures", 500)
    attendre(lambda: noeud.robot.fsm in MODES_MARCHE, 5, 0.1)
    # ARRÊT de la barre d'outils : il arrête aussi le pilotage (POST /api/arret → /arret du nœud)
    debut = time.monotonic()
    nav.clic("[data-role=arret]")
    attendre(lambda: [o for _, o in noeud.marche(debut) if o["velocity"] == [0.0, 0.0, 0.0]], 5, 0.1)
    nav.attendre("return document.querySelector('[data-role=etat-message]').textContent.includes('ARRÊT')", message="ARRÊT")
    # danses du robot (groupe Spectacle)
    nav.commande("pilotage.danses")
    nav.js("Array.from(document.querySelectorAll('.pilotage-danses button')).find(b => "
           "b.textContent === 'Lire la liste du robot').click()")
    nav.attendre("return document.querySelectorAll('.tableau-danses tbody tr').length >= 7", message="danses")
    interdites = nav.js("return Array.from(document.querySelectorAll('.danse-interdite')).map(l => l.dataset.danse)")
    assert sorted(interdites) == ["401", "402", "403"]
    assert nav.js("return document.querySelectorAll('.danse-interdite .jouer-danse').length") == 0
    assert nav.js("return document.querySelector('tr[data-danse=\"604\"] .jouer-danse').disabled") is True
    nav.js("document.querySelector('.pilotage-danses input[type=checkbox]').click()")
    time.sleep(1.1)
    nav.attendre("return !document.querySelector('tr[data-danse=\"604\"] .jouer-danse').disabled", message="jouer 604")
    nav.js("document.querySelector('tr[data-danse=\"604\"] .jouer-danse').click()")
    confirmer(nav)
    attendre(lambda: noeud.robot.danses_jouees == [604], 5, 0.1)
    nav.attendre("return !document.querySelector('.progres-danse').hidden", message="danse en cours")
    nav.clic("[data-role=arret]")
    time.sleep(0.5)
    # chorégraphies : l'aperçu 3D se charge dans la vue et avance
    nav.commande("pilotage.choregraphies")
    nav.attendre("return window.apercuPilotage && window.apercuPilotage.pret", delai=20, message="aperçu chargé")
    nav.attendre("return document.querySelector('.liste-choregraphies').value === 'exemple_kpop'", message="exemple")
    assert nav.js("return document.querySelector('.zone-vue-robot').hidden") is True
    images = nav.js("return window.apercuPilotage.images")
    mode = nav.js("return window.apercuPilotage.mode")
    assert mode in ("webgl", "canvas")
    nav.js("document.querySelector('[data-role=apercu]').click()")
    time.sleep(2.0)
    etat = nav.js("return [window.apercuPilotage.images, window.apercuPilotage.tChoregraphie]")
    assert etat[0] >= images + 20 and etat[1] > 1.0, etat
    assert nav.js("return document.querySelector('.choregraphie-erreurs').textContent").startswith("Chorégraphie sûre")
    # l'interpolation de la page est celle du nœud
    contenu = _api(base, "/api/pilotage/choregraphies/exemple_kpop")["choregraphie"]
    instants = [0.3, 1.2, 2.5, 3.1, 7.77, 12.0, 15.9, contenu["duree_s"] - 0.4]
    js = nav.js_async("""
const [d, instants, fini] = arguments;
import('/js/pilotage/choregraphie.js').then((C) => fini(instants.map((t) => C.poses(d, t))));
""", contenu, instants)
    for t, page in zip(instants, js):
        poids, q = D.poses_bras(contenu, t)
        assert page["poids"] == pytest.approx(poids, abs=1e-9)
        for nom in D.ARTICULATIONS_BRAS:
            assert page["q"][nom] == pytest.approx(q[nom], abs=1e-9), (t, nom)
    distance, rotation = D.deplacement_pas(contenu)
    page = nav.js_async("""
const [d, fini] = arguments;
import('/js/pilotage/choregraphie.js').then((C) => fini(C.deplacement(d)));
""", contenu)
    assert page["distance"] == pytest.approx(distance, abs=1e-6) and page["rotation"] == pytest.approx(rotation, abs=1e-6)
    erreurs = nav.js("return window.erreursAtelier")
    assert erreurs == [], erreurs
