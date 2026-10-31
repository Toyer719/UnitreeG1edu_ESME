"""La coque de l'Atelier dans un vrai navigateur, sans fenêtre (vague 5, section 12.2 du plan ; version courte
du critère 31) : agent Coquille. Firefox piloté par geckodriver (test_serveur_navigateur.py), mesures et
parcours de test_coque_communs.py, repères stables data-role / data-commande / data-onglet / data-ecran.

- l'accueil (Simulation, Robot réel et ses vérifications par lo, la répétition), sans boîte native ;
- la mise en page à 1366 × 768, en Simulation et en répétition, pour chaque onglet et chaque commande ;
- la mesure elle-même voit un défaut (page qui déborde, élément coupé, ARRÊT recouvert) ;
- les anciennes adresses, le thème clair, l'ARRÊT (clic et Échap), « Débloquer » et sa confirmation dans
  la page, la barre d'état (messages au lieu des notifications volantes, « Ce qui tourne » caché au repos).
"""
import json
import time

import pytest

from . import test_coque_communs as C
from .test_serveur_communs import faux_bin, journaux, lieux  # noqa: F401
from .test_serveur_demarrage import serveur  # noqa: F401
from .test_serveur_navigateur import GECKODRIVER, navigateur, sans_ros  # noqa: F401

pytestmark = pytest.mark.skipif(GECKODRIVER is None, reason="geckodriver absent")


@pytest.fixture
def liaison_lo(monkeypatch):
    """La liaison avec le robot passe par lo (jamais rien sur eno2, jamais de ping vers le robot)."""
    monkeypatch.setenv("ATELIER_INTERFACE_ROBOT", "lo")
    monkeypatch.setenv("ATELIER_PC1", "127.0.0.1")
    monkeypatch.setenv("ATELIER_JETSON", "127.0.0.1")


def _sans_fautes(fautes):
    assert not fautes, f"{len(fautes)} faute(s) de mise en page :\n" + "\n".join(fautes[:15])


def test_accueil_et_les_deux_modes(liaison_lo, sans_ros, serveur, navigateur, lieux):
    _, base = serveur
    nav = navigateur
    nav.taille(1366, 768)
    vu = C.parcours_accueil(nav, base, cable_attendu="ok")
    assert "ros = non" in vu[1] and "robot = ok" in vu[1], vu       # domaine de test ≠ 0 ; 127.0.0.1 répond
    assert nav.js("return window.erreursAtelier") == []


def test_mise_en_page_a_1366(sans_ros, serveur, navigateur, lieux):
    _, base = serveur
    nav = navigateur
    nav.taille(1366, 768)
    fautes = []
    for mode in ("simu", "repetition"):
        C.ouvrir_espace(nav, base, mode)
        f, mesures, elements = C.balayer(nav, mode)
        assert mesures >= 18 and elements > 500, (mode, mesures, elements)
        fautes += f
    _sans_fautes(fautes)
    assert C.fenetres_natives(nav) == []
    assert nav.js("return window.erreursAtelier") == []


def test_la_mesure_voit_les_defauts(sans_ros, serveur, navigateur, lieux):
    """Contre-essai : la mesure signale une page qui déborde, un élément coupé et un ARRÊT recouvert."""
    _, base = serveur
    nav = navigateur
    nav.taille(1366, 768)
    C.ouvrir_espace(nav, base, "simu")
    assert C.mesurer(nav)["fautes"] == []
    nav.js("""const s = document.createElement('style');
      s.textContent = '.ruban-commandes { overflow: hidden !important; width: 200px !important; }';
      document.head.appendChild(s);
      const cache = document.createElement('div');
      cache.style.cssText = 'position: fixed; top: 0; right: 0; width: 260px; height: 48px; z-index: 99999;';
      document.body.appendChild(cache);
      const large = document.createElement('div');
      large.style.cssText = 'position: absolute; left: 0; top: 0; width: 3000px; height: 10px;';
      document.body.appendChild(large);""")
    fautes = C.mesurer(nav)["fautes"]
    texte = "\n".join(fautes)
    assert "la page déborde" in texte, texte
    assert "ARRÊT recouvert" in texte, texte
    assert "cache une partie de son contenu" in texte, texte        # le ruban coupé à 200 px ne défile pas


def test_anciennes_adresses_et_theme(sans_ros, serveur, navigateur, lieux):
    _, base = serveur
    nav = navigateur
    nav.taille(1366, 768)
    C.parcours_anciens_hash(nav, base)
    C.parcours_theme(nav, base)
    # #scan avec l'ancienne mémoire « scan simulé » : Simulation › Avancé › Scan simulé
    C.ouvrir_espace(nav, base, "simu", memoire={"atelier.scan.mode": "simu"})
    C.charger(nav, base + "/?recharger=1#scan", "return !!document.querySelector('[data-ecran=scan]')", "#scan simulé")
    assert nav.js("return document.querySelector('[data-role=espace]').getAttribute('data-mode')") == "simu"
    # #pilotage sans lieu retenu : Piloter s'ouvre quand même (sans lieu)
    C.charger(nav, base + "/", C.ACCUEIL, "accueil")
    nav.js("localStorage.clear()")
    C.charger(nav, base + "/?recharger=1#pilotage", "return !!document.querySelector('[data-ecran=pilotage]')",
              "#pilotage sans lieu")
    assert nav.js("return document.querySelector('[data-role=espace]').getAttribute('data-mode')") in ("reel", "repetition")
    assert nav.js("return window.erreursAtelier") == []


def test_arret_clic_et_echap_en_simulation(sans_ros, serveur, navigateur, lieux):
    _, base = serveur
    nav = navigateur
    nav.taille(1366, 768)
    # clic et Échap envoient l'ARRÊT ; en simulation, jamais de verrou : le bouton reste ARRÊT
    vu = C.parcours_arret(nav, base, "simu")
    assert len(vu) == 2
    assert nav.js("return document.querySelector('[data-role=arret]').getAttribute('data-etat')") == "pret"
    message = nav.attendre("const m = document.querySelector('[data-role=etat-message]');"
                           "return m && m.textContent.indexOf('ARRÊT') >= 0 ? m.textContent : null", message="message de l'ARRÊT")
    assert "ARRÊT" in message
    assert not nav.js("return document.querySelector('#messages .message')"), "notification volante dans l'espace"
    assert nav.js("return window.erreursAtelier") == []


def test_arret_en_repetition_verrou_puis_debloquer(serveur, navigateur, lieux):
    """Avec le pont ROS 2 du serveur : l'ARRÊT pose le verrou (/pont/arret), le bouton devient « Débloquer » ;
    « Rester bloqué » ne change rien ; « Débloquer » demande une confirmation dans la page, puis le retire."""
    _, base = serveur
    nav = navigateur
    if not C.lire_json(base, "/api/etat").get("ros", {}).get("actif"):
        pytest.skip("pont ROS 2 du serveur inactif (rclpy absent ?)")
    nav.taille(1366, 768)
    vu = C.parcours_arret(nav, base, "repetition", verrou=True)
    assert any("Débloquer" in v for v in vu), vu
    assert C.lire_json(base, "/api/arret")["verrou"] is True
    nav.clic("[data-role=arret]")
    nav.attendre("return !!document.querySelector('[data-role=confirmation]')", message="confirmation de « Débloquer »")
    nav.clic("[data-role=renoncer]")                       # « Rester bloqué » : rien n'est envoyé
    assert nav.js("return document.querySelector('[data-role=arret]').getAttribute('data-etat')") == "bloque"
    assert not C.requetes(nav, "POST", "/api/arret/debloquer")
    nav.clic("[data-role=arret]")
    nav.clic("[data-role=confirmer]")
    nav.attendre("return document.querySelector('[data-role=arret]').getAttribute('data-etat') === 'pret'",
                 message="bouton revenu à ARRÊT après « Débloquer »")
    assert C.requetes(nav, "POST", "/api/arret/debloquer"), "POST /api/arret/debloquer non envoyé"
    assert C.lire_json(base, "/api/arret")["verrou"] is False
    assert C.fenetres_natives(nav) == []
    assert nav.js("return window.erreursAtelier") == []


def test_barre_d_etat_et_ce_qui_tourne(sans_ros, serveur, navigateur, lieux):
    _, base = serveur
    nav = navigateur
    nav.taille(1366, 768)
    C.ouvrir_espace(nav, base, "simu")
    # au repos, rien ne tourne : le bouton « Ce qui tourne » est caché (il reste dans le menu ⚙)
    assert nav.js("return document.querySelector('[data-role=bouton-ce-qui-tourne]').hidden")
    nav.clic("[data-role=reglages]")
    nav.attendre("return !!document.querySelector('.menu-reglages')", message="menu ⚙")
    nav.js("Array.from(document.querySelectorAll('.menu-reglages button')).find((b) => "
           "b.textContent.indexOf('Ce qui tourne') >= 0).click()")
    nav.attendre("return !document.querySelector('[data-role=ce-qui-tourne]').hidden", message="volet « Ce qui tourne »")
    # x, y sous le pointeur dans le Plan 2D : dans la barre d'état
    nav.commande("monde.choisir")
    nav.ecran("monde")
    assert nav.vue("plan") == "plan"
    nav.js("const c = document.querySelector('[data-ecran=monde] .plan-carte'); const r = c.getBoundingClientRect();"
           "c.dispatchEvent(new MouseEvent('mousemove', {bubbles: true, clientX: r.left + r.width / 2, clientY: r.top + r.height / 2}));")
    texte = nav.attendre("const t = document.querySelector('[data-role=etat-coordonnees]').textContent;"
                         "return t.indexOf('x ') === 0 ? t : null", message="coordonnées dans la barre d'état")
    assert " m" in texte and "y " in texte
    # la consigne de l'outil s'affiche en entier quand il y a la place
    nav.commande("salles.salle")
    largeurs = nav.js("const o = document.querySelector('[data-role=etat-outil]');"
                      "return [o.scrollWidth, o.clientWidth, o.textContent.length]")
    assert largeurs[2] > 20 and largeurs[0] <= largeurs[1] + 1, f"consigne coupée dans la barre d'état : {largeurs}"
    # un message (ici celui de l'ARRÊT) arrive dans la barre d'état et dans son journal, pas en notification volante
    nav.clic("[data-role=arret]")
    nav.attendre("const m = document.querySelector('[data-role=etat-message]');"
                 "return m && m.textContent.indexOf('ARRÊT') >= 0 && m.getAttribute('data-genre')",
                 message="message de l'ARRÊT dans la barre d'état")
    assert nav.js("return document.querySelectorAll('[data-role=journal] .message').length") >= 1
    assert not nav.js("return document.querySelector('#messages .message')")
    assert json.loads(json.dumps(nav.js("return window.erreursAtelier"))) == []


def _molette(nav, x, y, dy):
    """Une vraie molette (action WebDriver « wheel ») au point (x, y) de la fenêtre."""
    nav._requete("POST", f"/session/{nav.session}/actions", {"actions": [{"type": "wheel", "id": "molette", "actions": [
        {"type": "scroll", "x": int(x), "y": int(y), "deltaX": 0, "deltaY": int(dy), "duration": 120}]}]})
    time.sleep(0.6)


DEFILEMENTS = """const e = document.querySelector('[data-role=espace]');
return [window.scrollY, document.documentElement.scrollTop, document.body.scrollTop, e.scrollTop,
  document.querySelector('[data-role=panneau-corps]').scrollTop, document.querySelector('[data-role=arbre]').scrollTop];"""


def test_la_molette_ne_fait_jamais_defiler_la_page(sans_ros, serveur, navigateur, lieux):
    _, base = serveur
    nav = navigateur
    nav.taille(1366, 768)
    C.ouvrir_espace(nav, base, "simu")
    nav.commande("monde.choisir")
    nav.ecran("monde")
    assert nav.vue("plan") == "plan"
    # l'échelle de la carte (« 5 m », « 50 cm »…) : en mètres pour la même longueur à l'écran
    echelle = """const t = document.querySelector('[data-ecran=monde] .leaflet-control-scale-line').textContent.trim();
      const m = /([0-9.,]+)\\s*(km|m|cm|mm)/.exec(t);
      const k = {km: 1000, m: 1, cm: 0.01, mm: 0.001};
      return m ? [parseFloat(m[1].replace(',', '.')) * k[m[2]], parseFloat(document.querySelector('[data-ecran=monde] .leaflet-control-scale-line').style.width)] : null;"""
    avant = nav.js(echelle)
    assert avant, "pas d'échelle sur le plan"
    r = nav.js("const r = document.querySelector('[data-role=vue-plan]').getBoundingClientRect();"
               "return [r.left + r.width / 2, r.top + r.height / 2]")
    _molette(nav, r[0], r[1], -300)                     # vers le haut : on zoome
    apres = nav.js(echelle)
    # mètres par pixel de la barre d'échelle : plus petits après un zoom avant
    assert apres[0] / apres[1] < 0.8 * avant[0] / avant[1], f"la molette au-dessus du plan ne zoome pas la carte : {avant} → {apres}"
    assert nav.js(DEFILEMENTS) == [0, 0, 0, 0, 0, 0], "la molette au-dessus du plan a fait défiler autre chose"
    # au-dessus du panneau : seul le panneau défile (s'il dépasse), jamais la page
    nav.onglet("simuler")
    nav.ecran("simulation")
    p = nav.js("const r = document.querySelector('[data-role=panneau-corps]').getBoundingClientRect();"
               "return [r.left + r.width / 2, r.top + r.height / 2, document.querySelector('[data-role=panneau-corps]').scrollHeight"
               " > document.querySelector('[data-role=panneau-corps]').clientHeight]")
    _molette(nav, p[0], p[1], 400)
    d = nav.js(DEFILEMENTS)
    assert d[:4] == [0, 0, 0, 0], f"la page a défilé : {d}"
    if p[2]:
        assert d[4] > 0, "le panneau, plus haut que sa place, ne défile pas à la molette"
    _molette(nav, p[0], p[1], 4000)                     # bout du panneau atteint : la page ne bouge toujours pas
    assert nav.js(DEFILEMENTS)[:4] == [0, 0, 0, 0]
