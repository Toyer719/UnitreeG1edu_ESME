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


OUVRIR_ATTEIGNABLE = """const o = document.querySelector('[data-role=ouvrir]');
const r = o.getBoundingClientRect();
const t = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
return [Math.round(r.top), Math.round(r.bottom), window.innerHeight, !!t && o.contains(t)];"""


def test_ouvrir_visible_en_reel_a_1366_et_1280(sans_ros, serveur, navigateur, lieux):
    """Corrections de la vague 6 (revue de l'interface, défaut 2) : en Robot réel, la liste « Avant de commencer » et
    « Vérifier le robot » poussaient « Ouvrir » 74 px sous le bas de l'écran à 1366 × 768 (120 px à 1280 × 720). La
    rangée d'actions reste collée en bas de l'accueil : « Ouvrir » est visible et cliquable, sans défiler, même la
    fenêtre du diagnostic ouverte."""
    _, base = serveur
    nav = navigateur
    for largeur, hauteur in ((1366, 768), (1280, 720)):
        nav.taille(largeur, hauteur)
        C.charger(nav, base + "/", C.ACCUEIL, "accueil")
        nav.js("localStorage.setItem('atelier.mode', 'reel'); localStorage.setItem('atelier.repetition', '0');"
               "localStorage.setItem('atelier.lieu', 'demo');")
        C.charger(nav, base + "/", "return !!document.querySelector('[data-role=zone-diagnostic-accueil] "
                                   "[data-role=verifier-robot]')", "accueil Réel")
        nav.js("document.querySelector('[data-role=accueil]').scrollTop = 0")
        haut, bas, h, cliquable = nav.js(OUVRIR_ATTEIGNABLE)
        assert bas <= h and cliquable, f"{largeur} × {hauteur} : « Ouvrir » en {haut}–{bas} pour {h} px, cliquable {cliquable}"
        nav.clic("[data-role=zone-diagnostic-accueil] [data-role=verifier-robot]")
        nav.attendre("return !!document.querySelector('[data-role=diagnostic]')", message="fenêtre du diagnostic")
        haut, bas, h, cliquable = nav.js(OUVRIR_ATTEIGNABLE)
        assert bas <= h and cliquable, f"{largeur} × {hauteur}, diagnostic ouvert : « Ouvrir » recouvert ou caché"
        nav.js("document.querySelector('[data-role=diagnostic]').dispatchEvent(new KeyboardEvent('keydown', "
               "{key: 'Escape', bubbles: true}))")
    assert nav.js("return window.erreursAtelier") == []


def test_mise_en_page_a_1366(sans_ros, serveur, navigateur, lieux):
    _, base = serveur
    nav = navigateur
    nav.taille(1366, 768)
    fautes = []
    for mode in ("simu", "repetition"):
        C.ouvrir_espace(nav, base, mode)
        f, mesures, elements = C.balayer(nav, mode)
        # une commande grisée n'est pas cliquée (rien ne tourne : Y aller, Voix, Lumière…) : moins de mesures
        assert mesures >= 15 and elements > 500, (mode, mesures, elements)
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
    # le clic envoie l'ARRÊT ; rien ne tourne : Échap ne l'envoie pas (revue de la vague 5) ; en simulation,
    # jamais de verrou : le bouton reste ARRÊT
    vu = C.parcours_arret(nav, base, "simu", tourne=False)
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
    # rien de lancé : le clic pose le verrou, Échap n'envoie rien (revue de la vague 5)
    vu = C.parcours_arret(nav, base, "repetition", verrou=True, tourne=False)
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


# ---------------------------------------------------------------- revue de la vague 5 (corrections)

def _element(nav, selecteur):
    v = nav._requete("POST", f"/session/{nav.session}/element", {"using": "css selector", "value": selecteur})
    return list(v.values())[0]


def _vrai_clic(nav, selecteur):
    """Un vrai clic de WebDriver (appui, relâchement, clic), comme la souris : pas un .click() de script."""
    nav._requete("POST", f"/session/{nav.session}/element/{_element(nav, selecteur)}/click", {})


def _touches(nav, texte, ctrl=False):
    """Touches envoyées à l'élément qui a le curseur ('\\ue004' : Tab, '\\ue00c' : Échap) ; ctrl : avec Ctrl."""
    actions = [{"type": "keyDown", "value": "\ue009"}] if ctrl else []
    for c in texte:
        actions += [{"type": "keyDown", "value": c}, {"type": "keyUp", "value": c}]
    if ctrl:
        actions.append({"type": "keyUp", "value": "\ue009"})
    nav._requete("POST", f"/session/{nav.session}/actions",
                 {"actions": [{"type": "key", "id": "clavier", "actions": actions}]})
    time.sleep(0.3)


def _salle(lieux, ident):
    import yaml
    return next(s for s in yaml.safe_load((lieux / "demo" / "salles.yaml").read_text(encoding="utf-8")) if s["id"] == ident)


def test_arbre_replie_se_rouvre(sans_ros, serveur, navigateur, lieux):
    """Revue de la vague 5 : replié au-dessus de 1100 px, l'arbre se rouvre par la languette « Le lieu » (entière,
    non recouverte, 24 px au moins) et par le menu ⚙, même après un rechargement (c'est mémorisé)."""
    _, base = serveur
    nav = navigateur
    nav.taille(1366, 768)
    C.ouvrir_espace(nav, base, "simu")
    nav.clic("[data-role=replier-arbre]")
    nav.attendre("return document.querySelector('[data-role=espace]').classList.contains('arbre-replie')",
                 message="arbre replié")
    _sans_fautes(C.mesurer(nav)["fautes"])
    languette = """const b = document.querySelector('[data-role=deplier-arbre]'); const r = b.getBoundingClientRect();
      const t = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      return [getComputedStyle(b).display, Math.round(r.width), Math.round(r.height), t === b || b.contains(t)];"""
    vu = nav.js(languette)
    assert vu[0] != "none" and vu[1] >= 24 and vu[2] >= 24 and vu[3], f"languette « Le lieu » : {vu}"
    C.charger(nav, base + "/?recharger=1", C.ESPACE, "rechargement")
    assert C.attendre_pret(nav)
    assert nav.js("return document.querySelector('[data-role=espace]').classList.contains('arbre-replie')")
    nav.clic("[data-role=deplier-arbre]")
    nav.attendre("return !document.querySelector('[data-role=espace]').classList.contains('arbre-replie')",
                 message="arbre rouvert par la languette")
    assert nav.js("return localStorage.getItem('atelier.arbre.replie')") == "0"
    assert nav.js(languette)[0] == "none"
    # ⚙ › Cacher, puis Montrer l'arbre du lieu
    for attendu in (True, False):
        nav.clic("[data-role=reglages]")
        nav.attendre("return !!document.querySelector('.menu-reglages')", message="menu ⚙")
        nav.js("Array.from(document.querySelectorAll('.menu-reglages button')).find((b) => "
               "b.textContent.indexOf('arbre du lieu') >= 0).click()")
        nav.attendre("return document.querySelector('[data-role=espace]').classList.contains('arbre-replie') === "
                     "arguments[0]", attendu, message=f"⚙ › arbre replié = {attendu}")
    assert nav.js("return window.erreursAtelier") == []


def test_enregistrer_au_premier_clic_tab_et_ctrl_s(sans_ros, serveur, navigateur, lieux):
    """Revue de la vague 5 : le nom tapé (le champ a encore le curseur), un seul vrai clic sur ✓ Enregistrer
    l'enregistre (✓ s'active dès la frappe) ; Tab passe au champ suivant même si le panneau se redessine ;
    Ctrl+S pendant une saisie enregistre la salle (et pas la page)."""
    _, base = serveur
    nav = navigateur
    nav.taille(1366, 768)
    C.ouvrir_espace(nav, base, "simu", hash_="#salles")
    nav.ecran("salles")
    C.installer_espions(nav)
    nav.clic("[data-role=panneau-corps] [data-salle=b204]")
    nom = "[data-role=panneau-corps] [data-champ=nom] input"
    nav.attendre(f"return !!document.querySelector('{nom}')", message="champ Nom de b204")
    assert nav.js("return document.querySelector('[data-role=ok]').disabled"), "✓ actif sans modification"
    _vrai_clic(nav, nom)
    nav.js("document.activeElement.select()")
    _touches(nav, "Labo B204")
    assert not nav.js("return document.querySelector('[data-role=ok]').disabled"), "✓ grisé pendant la frappe"
    _vrai_clic(nav, "[data-role=ok]")
    nav.attendre("return document.querySelector('[data-role=ok]').disabled", message="salles enregistrées en un clic")
    assert len([r for r in C.requetes(nav, "PUT") if "/salles" in r["url"]]) == 1
    assert _salle(lieux, "b204")["nom"] == "Labo B204"
    # Tab : du nom aux autres noms, le curseur reste dans le panneau redessiné, ce qu'on tape y va
    _vrai_clic(nav, nom)
    nav.js("document.activeElement.select()")
    _touches(nav, "Salle B204\ue004")
    assert nav.js("const c = document.activeElement.closest('[data-champ]'); return c && c.getAttribute('data-champ')") == "alias"
    _touches(nav, "labo")
    assert nav.js("return document.querySelector('[data-champ=alias] input').value") == "labo"
    # Ctrl+S pendant la saisie : le champ est validé puis enregistré
    _touches(nav, "s", ctrl=True)
    nav.attendre("return document.querySelector('[data-role=ok]').disabled", message="Ctrl+S pendant la saisie")
    s = _salle(lieux, "b204")
    assert s["nom"] == "Salle B204" and s["alias"] == ["labo"], s
    assert C.fenetres_natives(nav) == [] and nav.js("return window.erreursAtelier") == []


def test_plan_2d_cadre_apres_avoir_ete_cache(sans_ros, serveur, navigateur, lieux):
    """Revue de la vague 5 : un cadrage demandé pendant que la vue Plan 2D est cachée (Placer s'ouvre en 3D)
    attend qu'elle ait une taille : tout l'étage se voit, pas un coin au zoom maximal ; « Recadrer » y revient."""
    _, base = serveur
    nav = navigateur
    nav.taille(1366, 768)
    C.ouvrir_espace(nav, base, "simu")
    r = nav.js_async("""const fini = arguments[arguments.length - 1];
      import('/js/plan.js').then((P) => {
        const hote = document.createElement('div');
        hote.style.cssText = 'position: fixed; left: 0; top: 0; width: 800px; height: 500px; z-index: 99999;';
        hote.hidden = true;
        document.body.appendChild(hote);
        const plan = P.creerPlan(hote);
        plan.cadrer(0, 0, 30, 20);
        const attente = plan.cadrageEnAttente;
        hote.hidden = false;
        setTimeout(() => {
          const b = plan.carte.getBounds();
          const vu = [plan.cadrageEnAttente, plan.carte.getZoom(), b.contains([[0, 0], [20, 30]])];
          plan.carte.setView([3, 3], 7);
          plan.recadrer();
          fini({ attente: attente, apres: vu, recadre: plan.carte.getBounds().contains([[0, 0], [20, 30]]) });
          plan.detruire();
          hote.remove();
        }, 600);
      }).catch((e) => fini({ erreur: String(e) }));""")
    assert "erreur" not in r, r
    assert r["attente"] is True, "le cadrage d'un plan caché n'a pas été mis en attente"
    assert r["apres"][0] is False and r["apres"][1] < 6 and r["apres"][2], f"plan mal cadré une fois visible : {r}"
    assert r["recadre"], "Recadrer ne montre pas tout l'étage"
    # avec WebGL (Placer s'ouvre en 3D) : le passage au Plan 2D montre les salles
    C.ouvrir_espace(nav, base, "simu", hash_="#salles")
    nav.ecran("salles")
    if nav.js("return document.querySelector('[data-role=vue]').getAttribute('data-vue')") == "3d":
        nav.vue("plan")
        time.sleep(1.0)
        visibles = nav.js("""const v = document.querySelector('[data-role=vue-plan]').getBoundingClientRect();
          return Array.from(document.querySelectorAll('[data-ecran=salles] .leaflet-marker-icon.icone-orientee')).filter((m) => {
            const r = m.getBoundingClientRect(); return r.right > v.left && r.left < v.right && r.bottom > v.top && r.top < v.bottom;
          }).length""")
        assert visibles >= 5, f"Plan 2D après la 3D : {visibles} salles visibles"
        assert nav.js("const b = document.querySelector('[data-cadrage=recadrer]'); return !!b && !b.hidden && "
                      "b.getBoundingClientRect().width > 0"), "pas de « Recadrer » en Plan 2D"
    assert nav.js("return window.erreursAtelier") == []


def test_echap_n_arrete_que_ce_qui_tourne(sans_ros, serveur, navigateur, lieux):
    """Revue de la vague 5 : rien de lancé (répétition), Échap ferme le menu ⚙ ou annule la saisie sans ARRÊT
    ni verrou ; seul, il dit qu'il n'y a rien à arrêter. decisionEchap : l'ARRÊT dès que le robot bouge,
    ou quand quelque chose tourne si la touche ne sert pas à autre chose ; sans nouvelles, on arrête."""
    _, base = serveur
    nav = navigateur
    nav.taille(1366, 768)
    C.ouvrir_espace(nav, base, "repetition")
    C.installer_espions(nav)
    nav.clic("[data-role=reglages]")
    nav.attendre("return !!document.querySelector('.menu-reglages')", message="menu ⚙")
    _touches(nav, "\ue00c")
    assert not nav.js("return !!document.querySelector('.menu-reglages')"), "Échap ne ferme pas le menu ⚙"
    nav.commande("salles.salle")
    nav.ecran("salles")
    nav.clic("[data-role=panneau-corps] [data-salle=b204]")
    nav.attendre("return !!document.querySelector('[data-role=panneau-corps] [data-champ=nom] input')", message="Nom")
    _vrai_clic(nav, "[data-role=panneau-corps] [data-champ=nom] input")
    _touches(nav, "\ue00c")                          # dans un champ : annule la saisie
    nav.js("document.activeElement.blur()")
    _touches(nav, "\ue00c")                          # l'outil Salle en cours : retour à « Choisir »
    assert nav.js("return document.querySelector('[data-commande=\"salles.salle\"]').getAttribute('aria-pressed')") == "false"
    _touches(nav, "\ue00c")                          # plus rien à fermer ni à annuler
    time.sleep(0.6)
    assert C.requetes(nav, "POST", "/api/arret") == [], "Échap a envoyé l'ARRÊT alors que rien ne tourne"
    assert nav.js("return document.querySelector('[data-role=arret]').getAttribute('data-etat')") == "pret"
    assert "rien à arrêter" in nav.js("return document.querySelector('[data-role=etat-message]').textContent")
    d = nav.js_async("""const fini = arguments[arguments.length - 1];
      import('/js/coque/arret.js').then((A) => {
        const rien = { processus: {}, simulation: null, mode: null, pont: null, guide: null, maitre: null };
        const nav = Object.assign({}, rien, { processus: { navigation: { en_cours: true } }, mode: 'repetition' });
        const route = Object.assign({}, nav, { guide: { etat: 'en_route', age_s: 0.2 } });
        const main = Object.assign({}, rien, { maitre: { maitre: 'pilotage' } });
        const vieux = Object.assign({}, rien, { guide: { etat: 'en_route', age_s: 30 } });
        const D = (d, servi, local) => A.decisionEchap(A.etatMouvement(d, local), servi);
        fini([D(rien, false), D(rien, true), D(nav, false), D(nav, true), D(route, true), D(main, true),
          D(rien, true, true), D(null, false), D(null, true), D(vieux, false),
          A.verrouVu({ arret: { verrou: false }, pont: { verrou: true, perime: false } }),
          A.verrouVu({ arret: { verrou: false }, pont: { verrou: true, perime: true } }),
          A.verrouVu({ arret: { verrou: true }, pont: null })]);
      }).catch((e) => fini(String(e)));""")
    assert d == ["rien", "local", "arret", "local", "arret", "arret", "arret", "arret", "local", "rien",
                 True, False, True], d
    assert nav.js("return window.erreursAtelier") == []


def test_echap_arrete_pendant_l_attente_du_retour(sans_ros, serveur, navigateur, lieux):
    """Relecture du 01/11/2026 : arrivé, retour automatique prévu dans 13 s, un menu ouvert : Échap fermait
    seulement le menu, et le robot partait seul. Un guide qui peut repartir d'un instant à l'autre (retour
    prévu, départ qui attend la navigation, champ actif) compte comme un robot qui bouge : l'ARRÊT part."""
    _, base = serveur
    nav = navigateur
    nav.taille(1366, 768)
    C.ouvrir_espace(nav, base, "repetition")
    d = nav.js_async("""const fini = arguments[arguments.length - 1];
      import('/js/coque/arret.js').then((A) => {
        const nav = { processus: { navigation: { en_cours: true } }, mode: 'repetition', simulation: null, pont: null,
          maitre: null };
        const avec = (g) => Object.assign({}, nav, { guide: Object.assign({ age_s: 0.2 }, g) });
        const D = (d, servi) => A.decisionEchap(A.etatMouvement(d, false), servi);
        fini([
          D(avec({ etat: 'arrive', mission: 'visite', retour_dans_s: 13.2 }), true),
          D(avec({ etat: 'echec', mission: 'visite', retour_dans_s: 3.0 }), true),
          D(avec({ etat: 'attente', mission: 'visite', cible: 'b204' }), true),
          D(avec({ etat: 'arrive', mission: 'visite', actif: true }), true),
          D(avec({ etat: 'attente', mission: null, actif: false }), true),
          D(avec({ etat: 'arrive', mission: 'visite', retour_dans_s: 13.2, age_s: 30 }), true),
          A.etatMouvement(avec({ etat: 'arrive', mission: 'visite', retour_dans_s: 5 }), false).enMouvement,
          A.guideActif({ etat: 'attente', mission: null }), A.guideActif(null),
          A.guideActif({ etat: 'echec', mission: 'visite' }), A.guideActif({ etat: 'perdu' })]);
      }).catch((e) => fini(String(e)));""")
    assert d == ["arret", "arret", "arret", "arret", "local", "local", True, False, False, False, True], d
    assert nav.js("return window.erreursAtelier") == []


def test_arret_qui_ne_repond_pas_et_fleches_lachees(sans_ros, serveur, navigateur, lieux):
    """Revue de la vague 5 : chaque appui sur ARRÊT part, même si le précédent attend encore ; sans réponse en
    1,5 s, la barre d'état dit de prendre la télécommande. Une flèche de téléopération tenue pendant l'ARRÊT
    ne relance pas le robot : il faut la relâcher, puis appuyer de nouveau."""
    _, base = serveur
    nav = navigateur
    nav.taille(1366, 768)
    C.ouvrir_espace(nav, base, "simu")
    r = nav.js_async("""const fini = arguments[arguments.length - 1];
      import('/js/teleop.js').then((T) => {
        const envois = [];
        const vrai = window.fetch;
        window.fetch = function (url, o) {
          const u = String(url);
          if (u.indexOf('/api/simulation/teleop') >= 0) {
            envois.push(JSON.parse(o.body));
            return Promise.resolve(new Response(JSON.stringify({ envoye: JSON.parse(o.body), ecoute: 1 }),
              { status: 200, headers: { 'Content-Type': 'application/json' } }));
          }
          return vrai.apply(this, arguments);
        };
        const zone = document.createElement('div');
        document.body.appendChild(zone);
        const t = new T.Teleop(zone);
        t.activer();
        const touche = (type, cle, rep) => window.dispatchEvent(new KeyboardEvent(type, { key: cle, repeat: !!rep, bubbles: true }));
        touche('keydown', 'ArrowUp');
        const tenue = T.flechesTenues();
        document.dispatchEvent(new CustomEvent('atelier-arret', { detail: { raison: 'essai' } }));
        const apres = [T.flechesTenues(), t.bloque];
        touche('keydown', 'ArrowUp', true);          // la flèche encore tenue (répétition du clavier)
        setTimeout(() => {
          const pendant = envois.length;
          const nonNuls = envois.filter((v) => v.vx || v.vy || v.wz).length;
          touche('keyup', 'ArrowUp');
          touche('keydown', 'ArrowUp');                // nouvel appui : le robot repart
          setTimeout(() => {
            const repart = envois.slice(pendant).some((v) => v.vx > 0);
            touche('keyup', 'ArrowUp');
            t.detruire();
            window.fetch = vrai;
            fini({ tenue: tenue, apres: apres, nonNuls: nonNuls, dernier: envois[pendant - 1], repart: repart });
          }, 300);
        }, 700);
      }).catch((e) => fini({ erreur: String(e) }));""")
    assert "erreur" not in r, r
    assert r["tenue"] is True and r["apres"] == [False, True], r
    assert r["nonNuls"] == 1 and r["dernier"] == {"vx": 0, "vy": 0, "wz": 0}, r      # un seul envoi avant l'ARRÊT
    assert r["repart"], "après relâchement, un nouvel appui ne repart pas"
    # ARRÊT sans réponse du serveur
    nav.js("""window.__envois = 0; const vrai = window.fetch;
      window.fetch = function (url, o) {
        if (String(url).indexOf('/api/arret') >= 0 && o && o.method === 'POST') {
          window.__envois += 1;
          return new Promise((res, rej) => { if (o.signal) o.signal.addEventListener('abort', () => rej(new Error('abandon'))); });
        }
        return vrai.apply(this, arguments);
      };""")
    for _ in range(3):
        nav.js("document.querySelector('[data-role=arret]').click()")
        time.sleep(0.2)
    message = nav.attendre("const t = document.querySelector('[data-role=etat-message]').textContent;"
                           "return t.indexOf('télécommande') >= 0 ? t : null", delai=5.0, message="message sans réponse")
    assert "ne répond pas" in message
    assert nav.js("return window.__envois") == 3, "un appui sur ARRÊT n'est pas parti"
    assert nav.js("return window.erreursAtelier") == []


def _poster(base, chemin, corps=None):
    """POST base + chemin, corps JSON ; la réponse en JSON."""
    import urllib.request
    requete = urllib.request.Request(base + chemin, data=json.dumps(corps or {}).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(requete, timeout=30) as r:
        return json.loads(r.read() or b"null")


ARRET_ACCUEIL = """const z = document.querySelector('[data-role=accueil] .accueil-arret');
return z && !z.hidden ? z.textContent : null;"""


def test_arret_sur_l_accueil_quand_quelque_chose_tourne(sans_ros, serveur, navigateur, lieux):
    """Revue de la vague 5 : revenu à l'accueil (⌂) pendant une simulation, l'ARRÊT y est (« En cours : la
    simulation… ») ; Échap et le bouton l'envoient. Rien ne tourne : pas d'ARRÊT sur l'accueil, Échap n'envoie
    rien. La simulation arrêtée, l'ARRÊT de l'accueil disparaît."""
    _, base = serveur
    nav = navigateur
    nav.taille(1366, 768)
    # rien ne tourne : l'accueil n'a pas d'ARRÊT, et Échap (état du serveur reçu) n'envoie rien
    C.charger(nav, base + "/", C.ACCUEIL, "accueil")
    nav.attendre("return (document.querySelector('[data-role=etat-serveur]') || {}).textContent"
                 ".indexOf('Serveur prêt') === 0", message="serveur prêt sur l'accueil")
    time.sleep(1.0)                                  # /ws/etat, ouvert en même temps, a donné l'état
    assert nav.js(ARRET_ACCUEIL) is None, "ARRÊT sur l'accueil alors que rien ne tourne"
    _touches(nav, "")
    time.sleep(0.5)
    assert C.requetes(nav, "POST", "/api/arret") == [], "Échap sur l'accueil a envoyé l'ARRÊT sans rien qui tourne"
    # la simulation (faux Gazebo) tourne : ⌂ ramène à un accueil qui montre l'ARRÊT
    _poster(base, "/api/lieux/demo/etages/rdc/monde/generer")
    _poster(base, "/api/simulation/demarrer", {"lieu": "demo", "etage": "rdc", "navigation": False})
    try:
        C.ouvrir_espace(nav, base, "simu")
        nav.clic("[data-role=accueil-retour]")
        texte = nav.attendre(ARRET_ACCUEIL, delai=15.0, message="ARRÊT sur l'accueil pendant la simulation")
        assert "la simulation" in texte, texte
        assert nav.js("return !!document.querySelector('[data-role=accueil] [data-role=arret]')")
        _touches(nav, "")                          # Échap sur l'accueil : l'ARRÊT part
        nav.attendre(C.DERNIER_ARRET, 0, "/api/arret", delai=5.0, message="ARRÊT envoyé par Échap sur l'accueil")
        nav.clic("[data-role=accueil] [data-role=arret]")  # le bouton aussi
        nav.attendre(C.DERNIER_ARRET, 1, "/api/arret", delai=5.0, message="ARRÊT envoyé par le bouton de l'accueil")
        assert nav.js(ARRET_ACCUEIL), "l'ARRÊT a disparu de l'accueil alors que la simulation tourne encore"
    finally:
        _poster(base, "/api/simulation/arreter")
    nav.attendre("const z = document.querySelector('[data-role=accueil] .accueil-arret'); return !!z && z.hidden",
                 delai=15.0, message="ARRÊT retiré de l'accueil, la simulation arrêtée")
    assert C.fenetres_natives(nav) == []
    assert nav.js("return window.erreursAtelier") == []


@pytest.fixture
def pilotage_absent(monkeypatch):
    """Le nœud pilotage attendu sur un port où rien n'écoute (jamais le 8010 de l'utilisateur)."""
    import socket
    with socket.socket() as so:
        so.bind(("127.0.0.1", 0))
        port = so.getsockname()[1]
    monkeypatch.setenv("G1_PILOTAGE_URL", f"http://127.0.0.1:{port}")


def test_piloter_demarre_depuis_le_ruban(pilotage_absent, sans_ros, serveur, navigateur, lieux):
    """Revue de la vague 5 : en répétition, pilotage pas démarré : la première commande du ruban s'appelle
    « Démarrer » et reste active ; Postures, Gestes, Voix et Lumière sont grisés avec la même raison."""
    _, base = serveur
    nav = navigateur
    nav.taille(1366, 768)
    C.ouvrir_espace(nav, base, "repetition", hash_="#pilotage")
    nav.ecran("pilotage")
    vu = nav.attendre("""const b = (id) => document.querySelector('[data-commande="' + id + '"]');
      if (!b('pilotage.main') || b('pilotage.main').textContent.indexOf('Démarrer') < 0) return null;
      return ['pilotage.main', 'pilotage.postures', 'pilotage.gestes', 'pilotage.voix', 'pilotage.led'].map((id) =>
        [id, b(id).disabled, b(id).title]);""", delai=20.0, message="« Démarrer » dans le ruban")
    assert vu[0][1] is False, vu
    assert all(x[1] and "Pilotage pas démarré" in x[2] for x in vu[1:]), vu
    assert nav.js("return window.erreursAtelier") == []


def test_fonctions_et_textes_de_la_revue(sans_ros, serveur, navigateur, lieux):
    """Revue de la vague 5 : l'ordre et les numéros des salles (ceux des épingles 3D), les alertes de l'arbre
    sans doublon, les identifiants lisibles, la phrase courte des scènes d'essai, la légende de la carte
    selon le thème, les couleurs de la frise prises du thème ; la fiche du lieu (chiffres en tuiles) ;
    Itinéraires : les salles reliées à rien par leur nom, « carré bleu », pluriels justes."""
    import json as _json
    import urllib.request
    _, base = serveur
    nav = navigateur
    nav.taille(1366, 768)
    C.ouvrir_espace(nav, base, "simu")
    r = nav.js_async("""const fini = arguments[arguments.length - 1];
      Promise.all([import('/js/carte3d/geometrie3d.js'), import('/js/coque/arbre.js'), import('/js/panneaux/passants.js'),
        import('/js/ecrans/carte.js'), import('/js/pilotage/ligne_temps.js')]).then(([G3, A, P, Ca, LT]) => {
        const salles = [{ id: 'accueil', nom: 'Accueil', etiquettes: ['principal'] }, { id: 'essai', nom: 'Essai à 2,5 m' },
          { id: '1', nom: '1' }, { id: '2', nom: '2' }, { id: 'bureau', nom: 'Bureau' }];
        const ordre = G3.sallesDansLOrdre(salles, 'accueil').map((x) => [x.salle.id, x.numero]);
        const alertes = A.alertesParId({ erreurs: [], avertissements: ['nœud « 1 » : relié à rien', 'nœud « 1 » : relié à rien'] }, ['1', '1', '2']);
        fini({ ordre: ordre, alertes: alertes, lisible: [A.nomLisible('couloir_sud_1'), A.nomLisible('hall-sud')],
          phrase: P.phraseCourte('Un passant reste au milieu du couloir nord, et ne voit pas le robot (reaction: aucune). Il reste 1,18 m.'),
          legendes: [Ca.legendeCarte('sombre'), Ca.legendeCarte('clair')],
          frise: LT.couleursFrise(document.body) });
      }).catch((e) => fini({ erreur: String(e) }));""")
    assert "erreur" not in r, r
    assert r["ordre"] == [["accueil", None], ["1", 1], ["2", 2], ["essai", 3], ["bureau", 4]], r["ordre"]
    assert r["alertes"] == {"1": ["nœud « 1 » : relié à rien"]}, r["alertes"]
    assert r["lisible"] == ["Couloir sud 1", "Hall sud"]
    assert r["phrase"] == "Un passant reste au milieu du couloir nord, et ne voit pas le robot.", r["phrase"]
    assert r["legendes"][0].startswith("Clair : obstacle") and r["legendes"][1].startswith("Noir : obstacle")
    assert r["frise"]["texte"] == "#f0f1f5" and r["frise"]["piste"] == "#2a2939", r["frise"]     # thème sombre
    # l'arbre : les salles dans l'ordre des épingles, avec leur numéro ; décomptes écrits
    nav.attendre("return document.querySelectorAll('[data-role=arbre] [data-noeud^=\"salle:\"] .numero-salle').length === 5",
                 message="numéros des salles dans l'arbre")
    notes = nav.js("return Array.from(document.querySelectorAll('[data-role=arbre] .arbre-note')).map((n) => n.textContent)")
    assert "6 points" in notes and "13 nœuds" in notes and "2 zones" in notes and "18 murs · 12 objets" in notes, notes
    # la fiche du lieu : chiffre au-dessus de son libellé
    nav.clic("[data-noeud=\"lieu:demo\"]")
    nav.attendre("return !!document.querySelector('.fiche-chiffre')", message="fiche du lieu")
    tuiles = nav.js("""return Array.from(document.querySelectorAll('.fiche-chiffre')).map((t) => {
      const v = t.querySelector('.fiche-chiffre-valeur').getBoundingClientRect();
      const l = t.querySelector('.fiche-chiffre-libelle').getBoundingClientRect(); return l.top >= v.bottom - 1; })""")
    assert tuiles and all(tuiles), tuiles
    # une salle reliée à rien : son nom, « carré bleu », et « 1 couloir » au singulier si besoin
    salles = _json.loads(urllib.request.urlopen(base + "/api/lieux/demo/salles", timeout=10).read())
    salles.append({"id": "labo_isole", "nom": "Labo isolé", "alias": [], "etage": "rdc",
                   "pose": {"x": 4.0, "y": 4.0, "theta": 0.0}, "phrase_arrivee": ""})
    req = urllib.request.Request(base + "/api/lieux/demo/salles?synchroniser=true", data=_json.dumps(salles).encode(),
                                 method="PUT", headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=20).read()
    nav.commande("itineraires.relier")
    nav.ecran("itineraires")
    texte = nav.attendre("const t = document.querySelector('[data-role=panneau-corps]').textContent;"
                         "return t.indexOf('reliée à rien') >= 0 ? t : null", message="salle reliée à rien")
    assert "« Labo isolé »" in texte and "carré bleu" in texte and "labo_isole" not in texte, texte
    # Simuler, rien de lancé : « Y aller » grisé (ruban et panneau) ; pas de Lancer dans le panneau (le ruban
    # l'a) ; une seule section repliable ouverte, et la commande Avancé ouvre la sienne
    nav.onglet("simuler")
    nav.ecran("simulation")
    nav.attendre("const b = document.querySelector('[data-commande=\"simulation.y-aller\"]');"
                 "return b.disabled && b.title.indexOf('Lancez d\\'abord la simulation') === 0", message="Y aller grisé")
    assert nav.js("return Array.from(document.querySelectorAll('[data-role=salles] button')).every((b) => b.disabled)")
    assert nav.js("return document.querySelector('[data-role=panneau-corps] [data-role=lancer]')") is None
    nav.commande("simulation.passants")
    nav.attendre("return document.querySelector('[data-section=passants]').open", message="Passants ouverte")
    nav.commande("simulation.reglages-guide")
    nav.attendre("return document.querySelector('[data-section=comportement]').open && "
                 "!document.querySelector('[data-section=passants]').open", message="une seule section ouverte")
    haut = nav.js("const r = document.querySelector('.comportement-reglages').getBoundingClientRect();"
                  "const c = document.querySelector('[data-role=panneau-corps]').getBoundingClientRect(); return r.top - c.top")
    assert -2 <= haut <= 40, f"les réglages du guide ne sont pas en haut du panneau ({haut} px)"
    # l'accueil : le champ du nouveau lieu garde sa hauteur, Ouvrir reste dans la fenêtre
    nav.clic("[data-role=accueil-retour]")
    nav.attendre("return !!document.querySelector('[data-role=accueil]')", message="accueil")
    nav.clic("[data-role=nouveau-lieu]")
    hauteurs = nav.js("return [document.querySelector('[data-role=nom-lieu]').getBoundingClientRect().height,"
                      "document.querySelector('[data-role=ouvrir]').getBoundingClientRect().bottom, window.innerHeight]")
    assert hauteurs[0] < 60 and hauteurs[1] <= hauteurs[2], hauteurs
    assert nav.js("return window.erreursAtelier") == []


def test_chemin_du_guide_avec_les_noms(sans_ros, serveur, navigateur, lieux):
    """Recette de la vague 5 (vu sur la capture de Simuler) : le chemin du guide dans le panneau donne le nom des
    salles et les autres nœuds lisibles (« Couloir nord 1 »), plus les identifiants (« couloir_nord_1 »)."""
    _, base = serveur
    nav = navigateur
    nav.taille(1366, 768)
    C.ouvrir_espace(nav, base, "simu")
    r = nav.js_async("""const fini = arguments[arguments.length - 1];
      import('/js/ecrans/simulation.js').then((S) => {
        const salles = [{ id: 'accueil', nom: 'Accueil' }, { id: 'amphi', nom: 'Amphithéâtre' }, { id: 'b204', nom: 'Salle B204' }];
        fini([S.texteChemin(['accueil', 'hall_nord', 'amphi', 'couloir_nord_1', 'b204'], salles),
              S.texteChemin([], salles), S.texteChemin(['x_1'], null)]);
      }).catch((e) => fini({ erreur: String(e) }));""")
    assert r == ["Accueil → Hall nord → Amphithéâtre → Couloir nord 1 → Salle B204", "", "X 1"], r
    assert nav.js("return window.erreursAtelier") == []


def test_y_aller_grise_quand_le_robot_est_bloque(sans_ros, serveur, navigateur, lieux):
    """Correction du 01/11/2026 (section 12.15 du plan) : pendant un blocage (verrou de l'Atelier, du pont, ou
    vu par le guide) ou hors du mode marche, « Y aller » est grisé avec la raison ; une panne (robot muet,
    refus) le laisse permis ; les messages de « Bloquer » et « Débloquer » disent que le trajet est annulé et
    que rien ne repart."""
    _, base = serveur
    nav = navigateur
    nav.taille(1366, 768)
    C.ouvrir_espace(nav, base, "simu")
    r = nav.js_async("""const fini = arguments[arguments.length - 1];
      import('/js/ecrans/simulation.js').then((S) => {
        const R = S.raisonImmobile;
        fini([R({ arret: { verrou: true } }, null), R({ pont: { verrou: true, perime: false } }, null),
              R({ pont: { verrou: true, perime: true } }, null), R({}, { immobilise: 'verrou' }),
              R({}, { immobilise: 'pas_en_marche' }), R({}, { immobilise: 'robot_muet' }), R(null, null),
              S.TITRES_IMMOBILE.verrou, S.MESSAGE_BLOQUE, S.MESSAGE_DEBLOQUE,
              R({}, { immobilise: 'pont_absent' }), S.TITRES_IMMOBILE.pont_absent]);
      }).catch((e) => fini({ erreur: String(e) }));""")
    assert r[0] == r[1] == r[3] == "Robot bloqué : « Débloquer » d'abord", r
    assert r[2] is None and r[5] is None and r[6] is None, r
    assert "mode marche" in r[4], r
    assert r[7] == "Robot bloqué : il ne bouge pas"
    assert "trajet en cours est annulé" in r[8] and "nouveau « Y aller »" in r[9], r
    # relecture du 01/11/2026 : le pont vers la marche qui ne donne plus de nouvelles grise aussi « Y aller »
    assert r[10] and "Pas de nouvelles du pont" in r[10] and r[11].startswith("Pas de nouvelles du pont"), r
    assert nav.js("return window.erreursAtelier") == []
