"""La carte 3D dans Firefox sans fenêtre, avec WebGL (vague 5, section 12.3 du plan, décisions I7 et I8).

Page d'essai essais/carte3d.html (la carte seule, sans la coque) sur une copie du demo (id « demo ») dont
l'étage a un nuage de test (murs et objets tous les 5 cm, environ 300 000 points). Les gestes sont de vrais
événements (API « actions » de WebDriver : souris, molette, clavier). On vérifie : le nuage et les repères,
les vues et le zoom vers le pointeur, tourner et déplacer, placer l'accueil et une salle puis enregistrer
par la route du plan 2D (salles.yaml, lieu.yaml, monde, itineraires.yaml), choisir, déplacer et tourner
une salle, Annuler / Rétablir, mesurer, le même repère que le plan 2D, le repli sans WebGL, le monde de la
Simulation, et la fluidité avec 300 000 points.
"""
import math
import time

import pytest
import yaml

from .test_carte3d_communs import (  # noqa: F401  (fixtures)
    atelier_carte3d, attendre_camera, cliquer, firefox, firefox_sans_webgl, glisser, lieux_carte3d, molette,
    ouvrir_essai, taper, vers_ecran)

CAPTURES = None      # dossier de captures (variable d'environnement CARTE3D_CAPTURES), sinon aucune


def _capturer(nav, nom):
    import os
    from pathlib import Path
    dossier = os.environ.get("CARTE3D_CAPTURES")
    if dossier:
        nav.capture(Path(dossier) / f"{nom}.png")


def _sans_erreur(nav):
    erreurs = nav.js("return [window.erreursAtelier, (window.essaiCarte3d || {}).erreurs]")
    assert erreurs == [[], []], erreurs


def _ouvrir(nav, a, **parametres):
    return ouvrir_essai(nav, a["adresse"], a["entete"], a["dossier"], **parametres)


def _cadrer(nav, bornes, vue="dessus"):
    nav.js("window.carte3d.vue(arguments[0]); window.carte3d.recadrer(arguments[1]);", vue, bornes)
    attendre_camera(nav)


def _outil(nav, nom):
    nav.js("document.querySelector('[data-outil=\"' + arguments[0] + '\"]').click()", nom)


def _glisser_sol(nav, points, **options):
    glisser(nav, [vers_ecran(nav, x, y) for x, y in points], **options)
    time.sleep(0.15)


def _salle(nav, ident):
    return nav.js("return window.edition3d.salles().find((s) => s.id === arguments[0]) || null", ident)


def _lire_yaml(chemin):
    return yaml.safe_load(chemin.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- affichage

def test_nuage_et_reperes_du_demo(atelier_carte3d, firefox):
    a = atelier_carte3d
    route = _ouvrir(firefox, a)
    e = firefox.js("return window.carte3d.etat()")
    assert e["webgl"] is True
    assert e["points"] == a["entete"]["points"] > 250000, e["points"]
    assert e["salles"] == 6 and e["principal"] == "accueil" and e["noeuds"] == 13 and e["zones"] == 2
    assert e["coupe"] == 2.2 and e["vue"] == "iso" and e["outil"] == "naviguer"
    assert set(e["calques"]) == {"nuage", "carte2d", "monde", "points", "itineraires", "zones", "robot", "pietons",
                                 "trajet"} and all(e["calques"].values())
    # étiquettes HTML : textContent, une par salle ; l'accueil en étoile ; la légende des hauteurs
    noms = firefox.js("return Array.from(document.querySelectorAll('.carte3d-etiquette[data-salle]'))"
                      ".map((x) => [x.getAttribute('data-salle'), x.textContent, x.classList.contains('principal')])")
    assert sorted(noms) == sorted([["accueil", "Accueil", True], ["vie_scolaire", "Vie scolaire", False],
                                   ["infirmerie", "Infirmerie", False], ["cdi", "CDI", False],
                                   ["amphi", "Amphithéâtre", False], ["b204", "Salle B204", False]])
    tetes = firefox.js("return Array.from(document.querySelectorAll('.carte3d-tete[data-salle]'))"
                       ".map((x) => x.textContent)")
    assert sorted(tetes) == ["1", "2", "3", "4", "5", "★"]
    assert firefox.js("return !document.querySelector('[data-role=carte3d-legende]').hidden")
    assert firefox.js("return document.querySelectorAll('[data-role=carte3d-axes] [data-axe]').length") == 3
    # robot et piétons en direct (format de /ws/etat)
    firefox.js("window.carte3d.afficherRobot({x: 2.5, y: 10, theta: 0.5});"
               "window.carte3d.afficherPietons([{id: 'pieton_sud', x: 6, y: 7.8}, {id: 'h2', x: 10, y: 13}]);")
    e = firefox.js("return window.carte3d.etat()")
    assert e["robot"] == {"x": 2.5, "y": 10, "theta": 0.5} and e["pietons"] == 2
    firefox.js("window.carte3d.afficherPietons([{id: 'h2', x: 11, y: 13}]); window.carte3d.afficherRobot(null);")
    e = firefox.js("return window.carte3d.etat()")
    assert e["robot"] is None and e["pietons"] == 1
    _capturer(firefox, "test_demo_iso")
    _sans_erreur(firefox)
    assert route in (200, 501)


def test_en_direct_robot_et_pietons_de_ws_etat(atelier_carte3d, firefox):
    """direct3d.js : un message de /ws/etat (robot repéré ou périmé, piétons) arrive dans la carte ; et la page
    abonnée au vrai /ws/etat du serveur (sans ROS : ni robot ni piétons) ne casse rien."""
    _ouvrir(firefox, atelier_carte3d, direct="1")
    r = firefox.js_async("""
      const fin = arguments[arguments.length - 1];
      import('/js/carte3d/direct3d.js').then((D) => {
        const c = window.carte3d;
        D.appliquerEtat(c, {robot: {x: 4, y: 7, theta: 1.2, age_s: 0.1, perimee: false},
                            pietons: [{id: 'pieton_sud', x: 6, y: 7.8, theta: 0}, {id: 3, x: 9, y: 13}]});
        const a = c.etat();
        D.appliquerEtat(c, {robot: {x: 4.5, y: 7, theta: 1.2, perimee: true}, pietons: [{id: 3, x: 9.5, y: 13}]});
        const b = c.etat();
        D.appliquerEtat(c, {robot: null, pietons: null});
        D.appliquerEtat(c, null);
        fin({a: [a.robot, a.pietons], b: [b.robot, b.pietons], c: [c.etat().robot, c.etat().pietons]});
      }, (e) => fin({erreur: String(e)}));""")
    assert "erreur" not in r, r
    assert r["a"] == [{"x": 4, "y": 7, "theta": 1.2}, 2]
    assert r["b"] == [{"x": 4.5, "y": 7, "theta": 1.2}, 1]
    assert r["c"] == [None, 0]
    time.sleep(1.0)            # quelques messages du vrai /ws/etat (environ 10 par seconde)
    assert firefox.js("return window.carte3d.etat().robot") is None
    _sans_erreur(firefox)


def test_meme_repere_que_salles_yaml_et_que_le_nuage(atelier_carte3d, firefox):
    """Un point (x, y) de salles.yaml, du nuage et du sol visé sont le même pixel : aucune conversion."""
    _ouvrir(firefox, atelier_carte3d)
    for vue in ("dessus", "iso", "face"):
        firefox.js("window.carte3d.vue(arguments[0])", vue)
        attendre_camera(firefox)
        for x, y in [(21.0, 13.0), (2.5, 10.0), (0.0, 0.0), (30.0, 20.0), (12.0, 4.0)]:
            p = firefox.js("return window.carte3d.versEcran(arguments[0], arguments[1], 0)", x, y)
            if p is None:
                continue
            sol = firefox.js("return window.carte3d.versSol(arguments[0], arguments[1])", p["x"], p["y"])
            assert sol is not None, (vue, x, y)
            assert sol["x"] == pytest.approx(x, abs=0.01) and sol["y"] == pytest.approx(y, abs=0.01), (vue, x, y, sol)
        # la base de chaque épingle est le pixel de la pose de salles.yaml
        for s in yaml.safe_load((atelier_carte3d["dossier"] / "salles.yaml").read_text(encoding="utf-8")):
            base = firefox.js("return window.carte3d.positionRepere('salle', arguments[0])", s["id"])
            attendu = firefox.js("return window.carte3d.versEcran(arguments[0], arguments[1], 0)",
                                 s["pose"]["x"], s["pose"]["y"])
            assert base == pytest.approx(attendu, abs=0.5), (vue, s["id"])
    # un coin de mur du nuage (mur ext_sud et cloison_1 se croisent en (10, 0)) : même pixel que le sol visé
    firefox.js("window.carte3d.vue('dessus')")
    attendre_camera(firefox)
    p = firefox.js("return window.carte3d.versEcran(10, 0, 0)")
    sol = firefox.js("return window.carte3d.versSol(arguments[0], arguments[1])", p["x"], p["y"])
    assert sol == pytest.approx({"x": 10.0, "y": 0.0}, abs=0.01)
    _sans_erreur(firefox)


def test_vues_recadrer_et_clavier(atelier_carte3d, firefox):
    _ouvrir(firefox, atelier_carte3d)
    vues = {}
    for nom in ("dessus", "iso", "face"):
        firefox.js("document.querySelector('[data-cadrage=\"' + arguments[0] + '\"]').click()", nom)
        attendre_camera(firefox)
        vues[nom] = firefox.js("return window.carte3d.etat().camera")
        assert firefox.js("return window.carte3d.etat().vue") == nom
        assert firefox.js("return document.querySelector('[data-cadrage=\"' + arguments[0] + '\"]')"
                          ".getAttribute('aria-pressed')", nom) == "true"
    assert vues["dessus"]["elevation"] > 89.9
    assert vues["iso"]["elevation"] == pytest.approx(35, abs=0.1) and vues["iso"]["azimut"] == pytest.approx(-120, abs=0.1)
    assert vues["face"]["elevation"] == pytest.approx(8, abs=0.1) and vues["face"]["azimut"] == pytest.approx(-90, abs=0.1)
    assert len({tuple(v["position"]) for v in vues.values()}) == 3
    # tout le demo est dans l'image en Dessus (coins du nuage)
    firefox.js("window.carte3d.vue('dessus')")
    attendre_camera(firefox)
    taille = firefox.js("return window.carte3d.etat().taille")
    for x, y in [(0, 0), (30, 0), (0, 20), (30, 20)]:
        p = firefox.js("return window.carte3d.versEcran(arguments[0], arguments[1], 0)", x, y)
        assert 0 <= p["x"] <= taille["largeur"] and 0 <= p["y"] <= taille["hauteur"], (x, y, p)
    # recadrer après un zoom : la caméra revient à la vue d'ensemble, même direction
    avant = firefox.js("return window.carte3d.etat().camera")
    molette(firefox, (taille["largeur"] * 0.3, taille["hauteur"] * 0.6), -400)
    zoome = firefox.js("return window.carte3d.etat().camera")
    assert zoome["distance"] < avant["distance"] * 0.8
    firefox.js("document.querySelector('[data-cadrage=recadrer]').click()")
    attendre_camera(firefox)
    apres = firefox.js("return window.carte3d.etat().camera")
    assert apres["distance"] == pytest.approx(avant["distance"], rel=0.02)
    assert apres["cible"] == pytest.approx(avant["cible"], abs=0.05)
    # clavier : 1 2 3, F, flèches, + et -
    firefox.js("document.querySelector('.carte3d').focus()")
    for touche, elevation in (("2", 35), ("3", 8), ("1", 89.97)):
        taper(firefox, touche)
        attendre_camera(firefox)
        assert firefox.js("return window.carte3d.etat().camera.elevation") == pytest.approx(elevation, abs=0.1), touche
    c0 = firefox.js("return window.carte3d.etat().camera")
    taper(firefox, "")               # flèche droite : la vue glisse vers l'est
    c1 = firefox.js("return window.carte3d.etat().camera")
    assert c1["cible"][0] > c0["cible"][0] + 0.5 and c1["distance"] == pytest.approx(c0["distance"])
    taper(firefox, "+")
    assert firefox.js("return window.carte3d.etat().camera.distance") < c1["distance"] * 0.9
    taper(firefox, "-", "-")
    assert firefox.js("return window.carte3d.etat().camera.distance") > c1["distance"]
    taper(firefox, "f")
    attendre_camera(firefox)
    assert firefox.js("return window.carte3d.etat().camera.distance") == pytest.approx(c0["distance"], rel=0.02)
    _sans_erreur(firefox)


@pytest.mark.parametrize("vue", ["iso", "dessus"])
def test_molette_zoome_vers_le_pointeur(atelier_carte3d, firefox, vue):
    """Le point du sol sous le pointeur y reste (à 2 pixels près), en s'approchant comme en s'éloignant."""
    _ouvrir(firefox, atelier_carte3d)
    firefox.js("window.carte3d.vue(arguments[0])", vue)
    attendre_camera(firefox)
    t = firefox.js("return window.carte3d.etat().taille")
    for fx, fy, delta in ((0.3, 0.62, -300), (0.72, 0.35, -150), (0.45, 0.5, 300)):
        px, py = t["largeur"] * fx, t["hauteur"] * fy
        sol = firefox.js("return window.carte3d.versSol(arguments[0], arguments[1])", px, py)
        assert sol is not None
        d0 = firefox.js("return window.carte3d.etat().camera.distance")
        molette(firefox, (px, py), delta)
        d1 = firefox.js("return window.carte3d.etat().camera.distance")
        assert (d1 < d0) if delta < 0 else (d1 > d0)
        p = firefox.js("return window.carte3d.versEcran(arguments[0], arguments[1], 0)", sol["x"], sol["y"])
        # pixel entier de WebDriver : le point visé est à 0,5 pixel au plus du pixel réellement pointé
        assert math.hypot(p["x"] - round(px), p["y"] - round(py)) <= 2.0, (sol, p, px, py)
    _sans_erreur(firefox)


def test_tourner_deplacer_et_jamais_sous_le_sol(atelier_carte3d, firefox):
    _ouvrir(firefox, atelier_carte3d)
    # sans les repères : un appui sur une épingle la déplacerait (outil « naviguer »), ici on ne bouge que la vue
    firefox.js("window.carte3d.calque('points', false); window.carte3d.calque('itineraires', false);")
    t = firefox.js("return window.carte3d.etat().taille")
    centre = (t["largeur"] / 2, t["hauteur"] / 2)
    c0 = firefox.js("return window.carte3d.etat().camera")
    # gauche glissé : tourner (la cible ne bouge pas)
    glisser(firefox, [centre, (centre[0] + 150, centre[1])])
    c1 = firefox.js("return window.carte3d.etat().camera")
    assert abs(c1["azimut"] - c0["azimut"]) > 20 and c1["cible"] == pytest.approx(c0["cible"], abs=1e-3)
    # droit glissé : déplacer (la direction ne change pas)
    glisser(firefox, [centre, (centre[0] + 120, centre[1] + 80)], bouton=2)
    c2 = firefox.js("return window.carte3d.etat().camera")
    assert c2["cible"] != pytest.approx(c1["cible"], abs=0.1)
    assert c2["azimut"] == pytest.approx(c1["azimut"], abs=0.01)
    assert c2["elevation"] == pytest.approx(c1["elevation"], abs=0.01)
    assert c2["cible"][2] == pytest.approx(c1["cible"][2], abs=1e-6)        # parallèle au sol
    # Maj + gauche : déplacer aussi
    glisser(firefox, [centre, (centre[0] - 100, centre[1])], maj=True)
    c3 = firefox.js("return window.carte3d.etat().camera")
    assert c3["cible"] != pytest.approx(c2["cible"], abs=0.1) and c3["azimut"] == pytest.approx(c2["azimut"], abs=0.01)
    # milieu glissé : tourner (SolidWorks)
    glisser(firefox, [centre, (centre[0], centre[1] - 120)], bouton=1)
    c4 = firefox.js("return window.carte3d.etat().camera")
    assert abs(c4["elevation"] - c3["elevation"]) > 5 and c4["cible"] == pytest.approx(c3["cible"], abs=1e-3)
    # on tire vers le haut tant qu'on peut : la caméra reste au-dessus du sol (2,8° au moins)
    for _ in range(3):
        glisser(firefox, [centre, (centre[0], centre[1] - 400)])
        c = firefox.js("return window.carte3d.etat().camera")
        assert c["elevation"] >= 2.8 and c["position"][2] > 0, c
    _sans_erreur(firefox)


def _doigt(ident, points, duree_ms=100):
    """Un doigt (WebDriver, pointerType touch) qui se pose, glisse par les points (pixels de la fenêtre), se lève."""
    pas = [{"type": "pointerMove", "duration": 0, "x": int(points[0][0]), "y": int(points[0][1]), "origin": "viewport"},
           {"type": "pointerDown", "button": 0}]
    pas += [{"type": "pointerMove", "duration": duree_ms, "x": int(x), "y": int(y), "origin": "viewport"}
            for x, y in points[1:]]
    pas.append({"type": "pointerUp", "button": 0})
    return {"type": "pointer", "id": ident, "parameters": {"pointerType": "touch"}, "actions": pas}


def test_gestes_tactiles(atelier_carte3d, firefox):
    """Tablette : un doigt tourne, deux doigts déplacent et zooment ; toucher une épingle la choisit."""
    from .test_carte3d_communs import actions, origine_toile
    _ouvrir(firefox, atelier_carte3d)
    firefox.js("window.selections = []; window.carte3d.surSelection((e) => window.selections.push(e));")
    ox, oy = origine_toile(firefox)
    # toucher l'épingle de b204
    base = firefox.js("return window.carte3d.positionRepere('salle', 'b204')")
    actions(firefox, [_doigt("d1", [(ox + base["x"], oy + base["y"]), (ox + base["x"], oy + base["y"])], 1)])
    assert firefox.js("return window.selections") == [{"genre": "salle", "id": "b204"}]
    firefox.js("window.carte3d.calque('points', false); window.carte3d.calque('itineraires', false);")
    t = firefox.js("return window.carte3d.etat().taille")
    cx, cy = ox + t["largeur"] / 2, oy + t["hauteur"] / 2
    c0 = firefox.js("return window.carte3d.etat().camera")
    actions(firefox, [_doigt("d1", [(cx, cy), (cx + 60, cy), (cx + 120, cy)])])
    c1 = firefox.js("return window.carte3d.etat().camera")
    assert abs(c1["azimut"] - c0["azimut"]) > 20 and c1["cible"] == pytest.approx(c0["cible"], abs=1e-3)
    # deux doigts qui s'écartent : on s'approche
    actions(firefox, [_doigt("d1", [(cx - 20, cy), (cx - 50, cy), (cx - 80, cy)]),
                      _doigt("d2", [(cx + 20, cy), (cx + 50, cy), (cx + 80, cy)])])
    c2 = firefox.js("return window.carte3d.etat().camera")
    assert c2["distance"] < c1["distance"] * 0.7, (c1, c2)
    # deux doigts qui glissent ensemble : la vue se déplace (parallèlement au sol)
    actions(firefox, [_doigt("d1", [(cx - 40, cy), (cx - 40, cy + 60), (cx - 40, cy + 120)]),
                      _doigt("d2", [(cx + 40, cy), (cx + 40, cy + 60), (cx + 40, cy + 120)])])
    c3 = firefox.js("return window.carte3d.etat().camera")
    assert c3["cible"] != pytest.approx(c2["cible"], abs=0.05) and c3["cible"][2] == pytest.approx(c2["cible"][2], abs=1e-6)
    _sans_erreur(firefox)


# ---------------------------------------------------------------- placer et enregistrer

def test_placer_accueil_et_salle_puis_enregistrer(atelier_carte3d, firefox):
    """Critère 32 sur la page d'essai : l'accueil posé en (3,0 ; 9,5) et tourné vers l'est, une salle
    « Essai 3D » posée en (12,0 ; 4,0) tournée vers −90°, enregistrés par PUT …/salles?synchroniser=true."""
    a = atelier_carte3d
    _ouvrir(firefox, a)
    firefox.js("window.poses = []; window.carte3d.surPose((e) => window.poses.push(e));")
    _cadrer(firefox, {"xmin": 0, "ymin": 2, "xmax": 14, "ymax": 12})
    _outil(firefox, "accueil")
    assert firefox.js("return window.carte3d.etat().outil") == "accueil"
    _glisser_sol(firefox, [(3.0, 9.5), (3.5, 9.5), (4.0, 9.5)])
    poses = firefox.js("return window.poses")
    assert poses[0]["fini"] is False and poses[-1]["fini"] is True and poses[-1]["geste"] == "poser"
    assert poses[-1]["outil"] == "accueil" and poses[-1]["id"] == "accueil" and poses[-1]["genre"] == "salle"
    s = _salle(firefox, "accueil")
    assert (s["pose"]["x"], s["pose"]["y"], s["pose"]["theta"]) == (3.0, 9.5, 0)
    assert firefox.js("return window.carte3d.etat().outil") == "naviguer"      # comme le plan 2D
    # une salle nouvelle, tournée vers le sud (−90°)
    _outil(firefox, "salle")
    _glisser_sol(firefox, [(12.0, 4.0), (12.0, 3.4), (12.0, 3.0)])
    s = _salle(firefox, "salle_1")
    assert s is not None and (s["pose"]["x"], s["pose"]["y"]) == (12.0, 4.0)
    assert s["pose"]["theta"] == pytest.approx(-1.5708, abs=1e-4)
    # le panneau : le nom, et l'identifiant fabriqué depuis le nom (comme le plan 2D)
    firefox.js("const c = document.querySelector('[data-champ=nom] input'); c.value = 'Essai 3D';"
               "c.dispatchEvent(new Event('change'));")
    assert _salle(firefox, "essai_3d") is not None
    champs = firefox.js("return ['x', 'y', 'orientation'].map((n) => document.querySelector("
                        "'[data-champ=' + n + '] input').value)")
    assert champs == ["12", "4", "-90"]
    _capturer(firefox, "test_placer_dessus")
    firefox.js("document.querySelector('[data-role=enregistrer]').click()")
    firefox.attendre("return document.querySelector('[data-role=etat-enregistrement]').textContent === "
                     "'Tout est enregistré'", message="enregistrement")
    salles = _lire_yaml(a["dossier"] / "salles.yaml")
    accueil = next(x for x in salles if x["id"] == "accueil")
    essai = next(x for x in salles if x["id"] == "essai_3d")
    assert (accueil["pose"]["x"], accueil["pose"]["y"]) == pytest.approx((3.0, 9.5), abs=0.05)
    assert abs(math.degrees(accueil["pose"]["theta"])) <= 2
    assert essai["nom"] == "Essai 3D" and essai["etage"] == "rdc"
    assert (essai["pose"]["x"], essai["pose"]["y"]) == pytest.approx((12.0, 4.0), abs=0.05)
    assert math.degrees(essai["pose"]["theta"]) == pytest.approx(-90, abs=2)
    lieu = _lire_yaml(a["dossier"] / "lieu.yaml")
    assert (lieu["accueil"]["x"], lieu["accueil"]["y"], lieu["accueil"]["theta"]) == pytest.approx((3.0, 9.5, 0), abs=0.05)
    depart = _lire_yaml(a["dossier"] / "mondes" / "rdc.monde.yaml")["depart_robot"]
    assert (depart["x"], depart["y"], depart["theta"]) == pytest.approx((3.0, 9.5, 0), abs=0.05)
    noeuds = _lire_yaml(a["dossier"] / "itineraires.yaml")["noeuds"]
    assert (noeuds["essai_3d"]["x"], noeuds["essai_3d"]["y"]) == pytest.approx((12.0, 4.0), abs=0.05)
    assert (noeuds["accueil"]["x"], noeuds["accueil"]["y"]) == pytest.approx((3.0, 9.5), abs=0.05)
    # relu par l'API, comme le plan 2D le relit
    from .test_carte3d_communs import lire_api
    api = {x["id"]: x["pose"] for x in lire_api(a["adresse"], "/api/lieux/demo/salles")}
    assert api["essai_3d"]["x"] == pytest.approx(12.0) and api["accueil"]["y"] == pytest.approx(9.5)
    _sans_erreur(firefox)


def test_choisir_deplacer_tourner_annuler_retablir(atelier_carte3d, firefox):
    _ouvrir(firefox, atelier_carte3d)
    firefox.js("window.selections = []; window.carte3d.surSelection((e) => window.selections.push(e));")
    _cadrer(firefox, {"xmin": 14, "ymin": 9, "xmax": 28, "ymax": 17}, vue="iso")
    # clic sur l'épingle de b204 : choisie (anneau, poignée, panneau)
    base = firefox.js("return window.carte3d.positionRepere('salle', 'b204')")
    cliquer(firefox, (base["x"], base["y"]))
    assert firefox.js("return window.selections") == [{"genre": "salle", "id": "b204"}]
    assert firefox.js("return window.carte3d.etat().selection") == {"genre": "salle", "id": "b204"}
    assert "Salle B204" in firefox.js("return document.querySelector('[data-role=panneau] h3').textContent")
    assert firefox.js("return document.querySelector('.carte3d-tete[data-salle=b204]').classList.contains('choisi')")
    # glisser l'épingle : déplacée de (21, 13) à (20, 12), orientation gardée
    _glisser_sol(firefox, [(21.0, 13.0), (20.5, 12.5), (20.0, 12.0)])
    s = _salle(firefox, "b204")
    assert (s["pose"]["x"], s["pose"]["y"]) == (20.0, 12.0) and s["pose"]["theta"] == pytest.approx(1.5708)
    # glisser la poignée blanche (bout de la flèche du repère choisi) : tournée vers l'ouest
    poignee = firefox.js("return window.carte3d.positionRepere('salle', 'b204', 'poignee')")
    ouest = vers_ecran(firefox, 17.0, 12.0)
    glisser(firefox, [(poignee["x"], poignee["y"]), ((poignee["x"] + ouest[0]) / 2, (poignee["y"] + ouest[1]) / 2), ouest])
    time.sleep(0.15)
    s = _salle(firefox, "b204")
    assert s["pose"]["theta"] == pytest.approx(math.pi, abs=1e-3), s
    assert (s["pose"]["x"], s["pose"]["y"]) == (20.0, 12.0)
    # le panneau corrige l'orientation au degré près
    firefox.js("const c = document.querySelector('[data-champ=orientation] input'); c.value = '-45';"
               "c.dispatchEvent(new Event('change'));")
    assert _salle(firefox, "b204")["pose"]["theta"] == pytest.approx(-0.7854, abs=1e-4)
    # Annuler trois fois : revenue à (21, 13, 90°) ; Rétablir : (20, 12, 180°)
    for _ in range(3):
        firefox.js("document.querySelector('[data-role=annuler]').click()")
    s = _salle(firefox, "b204")
    assert (s["pose"]["x"], s["pose"]["y"], s["pose"]["theta"]) == (21.0, 13.0, pytest.approx(1.5708))
    assert firefox.js("return window.carte3d.positionRepere('salle', 'b204')") == pytest.approx(
        firefox.js("return window.carte3d.versEcran(21, 13, 0)"), abs=0.5)
    firefox.js("const b = document.querySelector('[data-role=retablir]'); b.click(); b.click();")
    s = _salle(firefox, "b204")
    assert (s["pose"]["x"], s["pose"]["y"]) == (20.0, 12.0) and s["pose"]["theta"] == pytest.approx(math.pi, abs=1e-3)
    # Ctrl+Z au clavier
    firefox.js("document.body.focus()")
    from .test_carte3d_communs import actions
    actions(firefox, [{"type": "key", "id": "clavier", "actions": [
        {"type": "keyDown", "value": ""}, {"type": "keyDown", "value": "z"}, {"type": "keyUp", "value": "z"},
        {"type": "keyUp", "value": ""}]}])
    assert _salle(firefox, "b204")["pose"]["theta"] == pytest.approx(1.5708, abs=1e-3)
    # clic sur le sol vide : plus rien de choisi ; dans une zone : la zone
    cliquer(firefox, vers_ecran(firefox, 17.0, 10.0))
    assert firefox.js("return window.selections[window.selections.length - 1]") == {"genre": None, "id": None}
    _sans_erreur(firefox)


def test_echap_annule_le_geste_et_le_point_principal_reste(atelier_carte3d, firefox):
    _ouvrir(firefox, atelier_carte3d)
    _cadrer(firefox, {"xmin": 0, "ymin": 6, "xmax": 10, "ymax": 14})
    firefox.js("window.poses = []; window.carte3d.surPose((e) => window.poses.push(e));")
    _outil(firefox, "salle")
    # Échap pendant le choix d'outil : retour à naviguer
    firefox.js("document.querySelector('.carte3d').focus()")
    taper(firefox, "")
    assert firefox.js("return window.carte3d.etat().outil") == "naviguer"
    # le point principal ne se supprime pas (même règle et même message que le plan 2D)
    firefox.js("window.edition3d.choisir('accueil')")
    assert firefox.js("return window.edition3d.supprimer('accueil')") is False
    assert "point principal" in firefox.js("return document.querySelector('[data-role=etat-message]').textContent")
    assert _salle(firefox, "accueil") is not None
    _sans_erreur(firefox)


def test_mesurer_et_outil_noeud(atelier_carte3d, firefox):
    _ouvrir(firefox, atelier_carte3d)
    _cadrer(firefox, {"xmin": 0, "ymin": 4, "xmax": 12, "ymax": 10})
    _outil(firefox, "mesurer")
    cliquer(firefox, vers_ecran(firefox, 2.0, 7.0))
    cliquer(firefox, vers_ecran(firefox, 6.0, 7.0))
    texte = firefox.js("return document.querySelector('[data-role=carte3d-mesure]').textContent")
    assert texte.endswith(" m") and float(texte[:-2].replace(",", ".")) == pytest.approx(4.0, abs=0.06)
    # l'outil noeud (les itinéraires restent au Plan 2D) : un appui émet une pose de nœud
    firefox.js("window.poses = []; window.carte3d.surPose((e) => window.poses.push(e));"
               "window.carte3d.outil('noeud', {id: 'c9'});")
    _glisser_sol(firefox, [(8.0, 7.0), (8.0, 7.0)])
    p = firefox.js("return window.poses[window.poses.length - 1]")
    assert p["genre"] == "noeud" and p["id"] == "c9" and (p["x"], p["y"]) == (8.0, 7.0) and p["theta"] is None and p["fini"]
    _sans_erreur(firefox)


# ---------------------------------------------------------------- calques, plafond, points

def test_carte_creee_dans_une_vue_cachee_se_cadre_a_l_affichage(atelier_carte3d, firefox):
    """La coque peut créer la carte pendant que la vue 3D est cachée (Plan 2D affiché) : à son premier vrai
    affichage, elle cadre le contenu (et non une vue de 1 × 1 pixel)."""
    _ouvrir(firefox, atelier_carte3d, nuage="0")
    resultat = firefox.js_async("""
      const fin = arguments[arguments.length - 1];
      const script = document.createElement('script');
      script.type = 'module';
      script.textContent = `
        import { creerCarte3D } from '../js/carte3d/carte3d.js';
        const boite = document.createElement('div');
        boite.style.cssText = 'position: fixed; left: 0; top: 0; width: 900px; height: 600px; display: none;';
        document.body.appendChild(boite);
        const c = creerCarte3D(boite, {etage: 'rdc', nomGlobal: 'carteCachee', animation: false});
        c.afficherPoints(new Float32Array([0, 0, 0, 30, 20, 2]), {xmin: 0, ymin: 0, zmin: 0, xmax: 30, ymax: 20, zmax: 2});
        const avant = c.etat().camera.distance;
        boite.style.display = 'block';
        setTimeout(() => { window.resultatCachee = {avant: avant, apres: c.etat().camera, taille: c.etat().taille}; }, 300);
      `;
      document.head.appendChild(script);
      const attendre = () => (window.resultatCachee ? fin(window.resultatCachee) : setTimeout(attendre, 50));
      attendre();""")
    assert resultat["taille"] == {"largeur": 900, "hauteur": 600}
    # cadrée pour 900 × 600 : tout le rectangle de 30 × 20 m dans l'image, et serré (un coin près d'un bord)
    coins = firefox.js("""
      const c = window.carteCachee;
      return [[0, 0, 0], [30, 0, 0], [0, 20, 0], [30, 20, 0], [0, 0, 2], [30, 0, 2], [0, 20, 2], [30, 20, 2]]
        .map((p) => c.versEcran(p[0], p[1], p[2]));""")
    for p in coins:
        assert 0 <= p["x"] <= 900 and 0 <= p["y"] <= 600, coins
    marge = min(min(p["x"], 900 - p["x"], p["y"], 600 - p["y"]) for p in coins)
    assert marge < 40, (marge, coins)
    _sans_erreur(firefox)


def test_calques_plafond_et_taille_des_points(atelier_carte3d, firefox):
    _ouvrir(firefox, atelier_carte3d)
    # calques par le menu de la barre
    firefox.js("document.querySelector('.carte3d-menu').open = true;"
               "const c = document.querySelector('input[data-calque=points]'); c.click();")
    assert firefox.js("return window.carte3d.calque('points')") is False
    assert firefox.js("return Array.from(document.querySelectorAll('.carte3d-etiquette[data-salle]'))"
                      ".every((e) => e.hidden)")
    firefox.js("window.carte3d.calque('points', true)")
    assert firefox.js("return document.querySelector('input[data-calque=points]').checked") is True
    assert firefox.js("return window.carte3d.calque('inconnu')") is False
    # plafond : caché par défaut (coupe à 2,2 m), montré par la case
    firefox.js("document.querySelector('[data-role=carte3d-plafond]').click()")
    assert firefox.js("return window.carte3d.etat().coupe") is None
    firefox.js("window.carte3d.coupe(2.2)")
    assert firefox.js("return [window.carte3d.etat().coupe, "
                      "document.querySelector('[data-role=carte3d-plafond]').checked]") == [2.2, False]
    # taille des points (m), bornée
    firefox.js("window.carte3d.taillePoints(0.1)")
    assert firefox.js("return window.carte3d.etat().taillePoints") == 0.1
    firefox.js("window.carte3d.taillePoints(5)")
    assert firefox.js("return window.carte3d.etat().taillePoints") == 0.15
    _sans_erreur(firefox)


def test_fluide_avec_300000_points(atelier_carte3d, firefox):
    """300 000 points (plus que le nuage du 27/10, 293 504) : affichés en moins d'une seconde, et la vue
    qui tourne garde au moins 20 images par seconde (mesure : 60 images de suite)."""
    _ouvrir(firefox, atelier_carte3d)
    mesure = firefox.js_async("""
      const fin = arguments[arguments.length - 1];
      const n = 300000, p = new Float32Array(3 * n);
      for (let i = 0; i < n; i++) { p[3*i] = Math.random() * 30; p[3*i+1] = Math.random() * 20; p[3*i+2] = Math.random() * 3; }
      const c = window.carte3d;
      const t0 = performance.now();
      c.afficherPoints(p, {xmin: 0, ymin: 0, zmin: 0, xmax: 30, ymax: 20, zmax: 3});
      c.dessiner();
      const affichage = performance.now() - t0;
      let images = 0; const debut = performance.now();
      const tour = () => {
        c.centrerSur(15 + Math.sin(images / 10), 10);
        c.dessiner();
        images += 1;
        if (images < 60) requestAnimationFrame(tour);
        else fin({affichage: affichage, msParImage: (performance.now() - debut) / images, points: c.etat().points});
      };
      requestAnimationFrame(tour);""")
    print(f"300 000 points : affichés en {mesure['affichage']:.0f} ms, {mesure['msParImage']:.1f} ms par image")
    assert mesure["points"] == 300000
    assert mesure["affichage"] < 1000
    assert mesure["msParImage"] < 50, mesure
    _sans_erreur(firefox)


# ---------------------------------------------------------------- Simulation, sans WebGL, erreurs

def test_simulation_monde_en_volumes_et_carte_au_sol(atelier_carte3d, firefox):
    _ouvrir(firefox, atelier_carte3d, mode="simu")
    essai = firefox.js("return window.essaiCarte3d")
    assert essai["monde"] == "ok" and essai["carte2d"] == "ok" and essai["nuage"] is None
    e = firefox.js("return window.carte3d.etat()")
    assert e["points"] == 0 and e["salles"] == 6
    assert e["bornes"]["xmin"] == pytest.approx(-0.05) and e["bornes"]["xmax"] == pytest.approx(30.05)
    assert firefox.js("return document.querySelector('[data-role=carte3d-legende]').hidden") is True
    _capturer(firefox, "test_simulation_iso")
    _sans_erreur(firefox)


def _stl_binaire(triangles):
    import struct
    octets = bytearray(b"carte extrudee de test".ljust(80, b" ")) + struct.pack("<I", len(triangles))
    for t in triangles:
        octets += struct.pack("<3f", 0.0, 0.0, 1.0) + b"".join(struct.pack("<3f", *p) for p in t) + struct.pack("<H", 0)
    return bytes(octets)


def _boite(x0, y0, x1, y1, h):
    """Les 12 triangles d'une boîte posée au sol."""
    c = [(x0, y0, 0), (x1, y0, 0), (x1, y1, 0), (x0, y1, 0), (x0, y0, h), (x1, y0, h), (x1, y1, h), (x0, y1, h)]
    faces = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5), (2, 3, 7),
             (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    return [[c[i] for i in f] for f in faces]


def test_monde_avec_carte_extrudee_en_un_maillage(atelier_carte3d, firefox):
    """Un étage scanné : son monde a carte_extrudee, et la carte 3D montre le maillage STL de GET …/monde/maillage
    (binaire, ou texte) ; un maillage illisible ne casse rien (message, aucune erreur dans la page)."""
    from atelier.lieu import CarteExtrudee, charger_monde, enregistrer_monde
    a = atelier_carte3d
    monde = charger_monde(a["dossier"], "rdc")
    monde.carte_extrudee = CarteExtrudee("rdc_carte.stl", 1.5)
    enregistrer_monde(a["dossier"], "rdc", monde)
    stl = a["dossier"] / "mondes" / "rdc_carte.stl"
    stl.write_bytes(_stl_binaire(_boite(10, 6, 12, 8, 1.5)))
    from .test_carte3d_communs import statut_http
    if statut_http(a["adresse"], "/api/lieux/demo/etages/rdc/monde/maillage") != 200:
        pytest.skip("la route du maillage (agent Scan) ne sert pas encore mondes/rdc_carte.stl")
    _ouvrir(firefox, a, mode="simu")
    essai = firefox.js("return window.essaiCarte3d")
    assert essai["monde"] == "ok" and essai["maillage"] == 12, essai
    assert firefox.js("return window.carte3d.etat().monde.maillage") == 12
    # en texte (STL « solid ») : deux triangles
    stl.write_text("solid essai\n" + "".join(
        "facet normal 0 0 1\nouter loop\n" + "".join(f"vertex {x} {y} {z}\n" for x, y, z in t) + "endloop\nendfacet\n"
        for t in _boite(0, 0, 1, 1, 1)[:2]) + "endsolid essai\n", encoding="ascii")
    r = firefox.js_async("const fin = arguments[arguments.length - 1];"
                         "fetch('/api/lieux/demo/etages/rdc/monde').then((r) => r.json()).then((m) => "
                         "window.carte3d.afficherMonde(m, {urlMaillage: '/api/lieux/demo/etages/rdc/monde/maillage'}))"
                         ".then(fin, (e) => fin({rejet: String(e)}))")
    assert r == {"ok": True, "maillage": 2}, r
    # illisible : la promesse se résout avec l'erreur, sans rejet ni erreur dans la page
    stl.write_bytes(b"pas un maillage")
    r = firefox.js_async("const fin = arguments[arguments.length - 1];"
                         "fetch('/api/lieux/demo/etages/rdc/monde').then((r) => r.json()).then((m) => "
                         "window.carte3d.afficherMonde(m, {urlMaillage: '/api/lieux/demo/etages/rdc/monde/maillage'}))"
                         ".then(fin, (e) => fin({rejet: String(e)}))")
    assert r["ok"] is False and "illisible" in r["erreur"], r
    r = firefox.js_async("const fin = arguments[arguments.length - 1];"
                         "window.carte3d.afficherCarte2D('/inexistant.png', {xmin: 0, ymin: 0, xmax: 1, ymax: 1}).then(fin)")
    assert r["ok"] is False and "carte 2D" in r["erreur"]
    _capturer(firefox, "test_monde_maillage")
    _sans_erreur(firefox)


def test_sans_webgl_un_message_et_rien_ne_casse(atelier_carte3d, firefox_sans_webgl):
    nav = firefox_sans_webgl
    _ouvrir(nav, atelier_carte3d, nuage="0")
    message = nav.js("const m = document.querySelector('[data-role=carte3d-sans-webgl]');"
                     "return m && m.offsetParent !== null ? m.textContent : null")
    assert message and "WebGL" in message and "Plan 2D" in message
    e = nav.js("return window.carte3d.etat()")
    assert e["webgl"] is False and e["points"] == 0
    r = nav.js_async("""
      const fin = arguments[arguments.length - 1];
      const c = window.carte3d;
      c.afficherPoints(new Float32Array(9)); c.afficherSalles([]); c.afficherItineraires({}); c.afficherZones({});
      c.afficherRobot({x: 1, y: 1, theta: 0}); c.afficherPietons([]); c.afficherTrajet([]); c.vue('dessus');
      c.recadrer(); c.centrerSur(1, 1); c.coupe(null); c.outil('salle'); c.choisir('salle', 'b204');
      const d = [c.surSelection(() => {}), c.surPose(() => {}), c.surPointeur(() => {})];
      d.forEach((f) => f());
      Promise.all([c.afficherMonde(null), c.afficherCarte2D('x.png', {xmin: 0, ymin: 0, xmax: 1, ymax: 1})])
        .then(() => c.chargerNuage('/api/lieux/demo/etages/rdc/nuage').then(() => fin('charge'), (e) => fin(e.message)));""")
    assert "WebGL" in r
    assert nav.js("return [window.carte3d.versEcran(1, 2), window.carte3d.versSol(3, 4), "
                  "window.carte3d.calque('nuage')]") == [None, None, False]
    # le reste de la page marche : la liste des salles est dans le panneau
    assert nav.js("return document.querySelectorAll('[data-role=panneau] .liste-choix li').length") == 6
    _sans_erreur(nav)


def test_nuage_absent_message_en_francais(atelier_carte3d, firefox):
    """404 du serveur (pas de nuage pour cet étage) : rejet avec un message en français."""
    a = atelier_carte3d
    for f in (a["dossier"] / "cartes").glob("rdc.nuage.*"):
        f.unlink()
    _ouvrir(firefox, a, nuage="0")
    r = firefox.js_async("const fin = arguments[arguments.length - 1];"
                         "window.carte3d.chargerNuage('/api/lieux/demo/etages/rdc/nuage')"
                         ".then(() => fin(null), (e) => fin([e.message, e.statut || null]))")
    if r and r[1] == 501:
        pytest.skip("la route du nuage n'est pas encore écrite (agent Scan) : 501")
    assert r is not None and r[1] == 404 and "nuage 3D" in r[0] and "Utiliser cette carte" in r[0]
    assert firefox.js("return window.carte3d.etat().points") == 0
    _sans_erreur(firefox)


# ---------------------------------------------------------------- sol dense, repères modifiables, étiquettes

PIXEL = """
const c = window.carte3d, toile = document.querySelector('.carte3d-toile');
c.dessiner();
const p = c.versEcran(arguments[0], arguments[1], arguments[2]);
const r = window.devicePixelRatio || 1;
const t = document.createElement('canvas'); t.width = toile.width; t.height = toile.height;
const ctx = t.getContext('2d'); ctx.drawImage(toile, 0, 0);
const d = ctx.getImageData(Math.round(p.x * r), Math.round(p.y * r), 1, 1).data;
return [d[0], d[1], d[2]];
"""


def _ecart_couleurs(a, b):
    return max(abs(x - y) for x, y in zip(a, b))


def test_sol_dense_les_zones_restent_visibles_et_les_murs_les_cachent(atelier_carte3d, firefox):
    """Un sol dense (un point tous les 5 cm, comme le nuage d'affichage d'un vrai scan) ne cache pas les zones ni
    les couloirs posés au sol ; un mur de points devant eux les cache toujours (pixels de la toile)."""
    _ouvrir(firefox, atelier_carte3d, nuage="0", image="1")
    firefox.js("""
      const pts = [];
      for (let x = 0; x <= 10.0001; x += 0.05) for (let y = 0; y <= 10.0001; y += 0.05) pts.push(x, y, 0.01);
      for (let y = 0; y <= 10.0001; y += 0.05) for (let k = 0; k <= 36; k++) pts.push(5, y, 0.2 + k * 0.05);
      const c = window.carte3d;
      c.calque('carte2d', false); c.calque('points', false);
      c.afficherPoints(new Float32Array(pts), {xmin: 0, ymin: 0, zmin: 0, xmax: 10, ymax: 10, zmax: 2});
      c.afficherZones({interdites: [{etage: 'rdc', polygone: [[1, 1], [4, 1], [4, 9], [1, 9]]}],
                       lentes: [{etage: 'rdc', polygone: [[6, 1], [9, 1], [9, 9], [6, 9]], vitesse_max: 0.2}]});
      c.afficherItineraires({noeuds: {}, couloirs: []});""")
    e = firefox.js("return window.carte3d.etat()")
    assert e["pointsSol"] == 201 * 201 and e["points"] == 201 * 201 + 201 * 37, e
    # vue de dessus : la zone interdite teinte le sol, calque montré ou caché
    _cadrer(firefox, {"xmin": 0, "ymin": 0, "xmax": 10, "ymax": 10})
    avec = firefox.js(PIXEL, 2.5, 5.0, 0.0)
    firefox.js("window.carte3d.calque('zones', false)")
    sans = firefox.js(PIXEL, 2.5, 5.0, 0.0)
    assert _ecart_couleurs(avec, sans) > 25, (avec, sans)
    assert avec[0] > sans[0], (avec, sans)                        # plus rouge avec la zone interdite
    # vue Iso (depuis le sud-sud-ouest) : derrière le mur (x = 5), à 1,6 m de haut, on verrait le sol de la zone
    # lente : le pixel du mur ne change pas avec le calque des zones
    firefox.js("window.carte3d.calque('zones', true); window.carte3d.vue('iso');"
               "window.carte3d.recadrer({xmin: 0, ymin: 0, xmax: 10, ymax: 10});")
    attendre_camera(firefox)
    mur_avec = firefox.js(PIXEL, 5.0, 5.0, 1.6)
    firefox.js("window.carte3d.calque('zones', false)")
    mur_sans = firefox.js(PIXEL, 5.0, 5.0, 1.6)
    assert _ecart_couleurs(mur_avec, mur_sans) <= 3, (mur_avec, mur_sans)
    # et sans le mur (calque du nuage caché), la zone lente se voit bien à ce pixel : le mur la cachait
    firefox.js("window.carte3d.calque('zones', true); window.carte3d.calque('nuage', false)")
    zone_seule = firefox.js(PIXEL, 5.0, 5.0, 1.6)
    firefox.js("window.carte3d.calque('zones', false)")
    rien = firefox.js(PIXEL, 5.0, 5.0, 1.6)
    assert _ecart_couleurs(zone_seule, rien) > 25, (zone_seule, rien)
    _capturer(firefox, "test_sol_dense_zones")
    _sans_erreur(firefox)


def test_un_repere_ne_bouge_que_si_un_ecran_le_modifie(atelier_carte3d, firefox):
    """La page d'essai modifie les salles seulement (surPose avec genres) : un nœud glissé ne bouge pas (la vue
    tourne), un clic le choisit. Sans écran abonné, une salle non plus ; avec un écran qui n'accepte pas la
    pose (il ne rappelle pas afficherSalles), la salle glissée revient à sa place."""
    _ouvrir(firefox, atelier_carte3d)
    firefox.js("window.selections = []; window.carte3d.surSelection((e) => window.selections.push(e));")
    _cadrer(firefox, {"xmin": 6, "ymin": 4, "xmax": 24, "ymax": 15}, vue="iso")
    assert firefox.js("return window.carte3d.etat().modifiables") == {"salle": True, "noeud": False}
    # un nœud (couloir_sud_1, en (11 ; 7)) : glissé, il ne bouge pas, la vue tourne ; un clic le choisit
    noeud = firefox.js("return window.carte3d.positionRepere('noeud', 'couloir_sud_1')")
    c0 = firefox.js("return window.carte3d.etat().camera")
    glisser(firefox, [(noeud["x"], noeud["y"]), (noeud["x"] + 60, noeud["y"]), (noeud["x"] + 120, noeud["y"])])
    c1 = firefox.js("return window.carte3d.etat().camera")
    assert abs(c1["azimut"] - c0["azimut"]) > 10, (c0, c1)
    assert firefox.js("return window.carte3d.positionRepere('noeud', 'couloir_sud_1')") == pytest.approx(
        firefox.js("return window.carte3d.versEcran(11, 7, 0)"), abs=0.5)
    noeud = firefox.js("return window.carte3d.positionRepere('noeud', 'couloir_sud_1')")
    cliquer(firefox, (noeud["x"], noeud["y"]))
    assert firefox.js("return window.selections[window.selections.length - 1]") == {"genre": "noeud", "id": "couloir_sud_1"}
    # plus aucun écran : une salle ne se glisse plus (la vue tourne), pas de poignée ; un clic la choisit
    firefox.js("window.edition3d.detruire()")
    assert firefox.js("return window.carte3d.etat().modifiables") == {"salle": False, "noeud": False}
    _cadrer(firefox, {"xmin": 14, "ymin": 9, "xmax": 28, "ymax": 17}, vue="iso")
    base = firefox.js("return window.carte3d.positionRepere('salle', 'b204')")
    cliquer(firefox, (base["x"], base["y"]))
    assert firefox.js("return window.carte3d.etat().selection") == {"genre": "salle", "id": "b204"}
    c0 = firefox.js("return window.carte3d.etat().camera")
    glisser(firefox, [(base["x"], base["y"]), (base["x"] - 60, base["y"] + 30), (base["x"] - 120, base["y"] + 60)])
    c1 = firefox.js("return window.carte3d.etat().camera")
    assert c1["position"] != pytest.approx(c0["position"], abs=0.01), "la vue aurait dû tourner"
    assert firefox.js("return window.carte3d.positionRepere('salle', 'b204')") == pytest.approx(
        firefox.js("return window.carte3d.versEcran(21, 13, 0)"), abs=0.5)
    # un écran qui écoute mais n'accepte rien : la salle suit le glissé, puis revient à (21 ; 13)
    firefox.js("window.recues = []; window.carte3d.surPose((e) => window.recues.push(e));")
    assert firefox.js("return window.carte3d.etat().modifiables") == {"salle": True, "noeud": True}
    _cadrer(firefox, {"xmin": 14, "ymin": 9, "xmax": 28, "ymax": 17}, vue="dessus")
    _glisser_sol(firefox, [(21.0, 13.0), (20.5, 12.5), (20.0, 12.0)])
    recues = firefox.js("return window.recues")
    assert recues and recues[-1]["fini"] is True and (recues[-1]["x"], recues[-1]["y"]) == (20.0, 12.0), recues
    assert firefox.js("return window.carte3d.positionRepere('salle', 'b204')") == pytest.approx(
        firefox.js("return window.carte3d.versEcran(21, 13, 0)"), abs=0.5)
    _sans_erreur(firefox)


def test_etiquettes_sans_chevauchement(atelier_carte3d, firefox):
    """Cinq salles serrées autour de l'accueil (comme la séance du 27/10) : les noms affichés ne se coupent
    pas et ne couvrent la tête d'aucune autre salle ; un nom sans place est caché, sa tête reste."""
    _ouvrir(firefox, atelier_carte3d)
    firefox.js("""
      const s = window.edition3d.salles();
      const ici = {accueil: [2.5, 10], vie_scolaire: [3.6, 10], infirmerie: [4.6, 10.05], cdi: [3.0, 10.6],
                   amphi: [3.0, 9.4], b204: [1.9, 9.5]};
      s.forEach((x) => { if (ici[x.id]) { x.pose.x = ici[x.id][0]; x.pose.y = ici[x.id][1]; } });
      window.carte3d.afficherSalles(s, 'accueil');""")
    for vue, bornes in (("dessus", {"xmin": 0.5, "ymin": 8.5, "xmax": 6.5, "ymax": 11.5}),
                        ("iso", {"xmin": -4, "ymin": 4, "xmax": 10, "ymax": 16})):
        _cadrer(firefox, bornes, vue=vue)
        firefox.js("window.carte3d.dessiner()")
        r = firefox.js("""
          const rect = (e) => { const q = e.getBoundingClientRect(); return [q.left, q.top, q.right, q.bottom]; };
          const vus = (sel) => Array.from(document.querySelectorAll(sel)).filter((e) => !e.hidden
            && getComputedStyle(e).display !== 'none' && getComputedStyle(e).visibility !== 'hidden');
          return {noms: vus('.carte3d-etiquette[data-salle]').map((e) => [e.getAttribute('data-salle'), rect(e)]),
                  tetes: vus('.carte3d-tete[data-salle]').map((e) => [e.getAttribute('data-salle'), rect(e)]),
                  caches: Array.from(document.querySelectorAll('.carte3d-etiquette.cachee')).map((e) => e.getAttribute('data-salle'))};""")
        coupe = lambda a, b: a[0] < b[2] - 0.5 and b[0] < a[2] - 0.5 and a[1] < b[3] - 0.5 and b[1] < a[3] - 0.5  # noqa: E731
        assert len(r["tetes"]) == 6, r
        for i, (a, ra) in enumerate(r["noms"]):
            for b, rb in r["noms"][i + 1:]:
                assert not coupe(ra, rb), (vue, a, b, r)
            for b, rb in r["tetes"]:
                assert b == a or not coupe(ra, rb), (vue, a, "couvre la tête de", b, r)
        if vue == "dessus":           # l'accueil passe d'abord (en Iso, ici, d'autres têtes entourent la sienne)
            assert "accueil" in [n for n, _ in r["noms"]], (vue, r)
        assert len(r["noms"]) >= 3 and len(r["noms"]) + len(r["caches"]) == 6, (vue, r)
    _capturer(firefox, "test_etiquettes_serrees")
    _sans_erreur(firefox)


def test_glisser_un_noeud_ses_couloirs_suivent(atelier_carte3d, firefox):
    """Un écran qui modifie les nœuds (surPose avec genres ['noeud']) : pendant le glissé de couloir_sud_1, ses
    couloirs suivent le nœud ; pose acceptée (afficherItineraires rappelé) : ils restent à la nouvelle place ;
    pose refusée : le nœud et ses couloirs reviennent."""
    _ouvrir(firefox, atelier_carte3d)
    firefox.js_async("""
      const fin = arguments[arguments.length - 1];
      fetch('/api/lieux/demo/itineraires').then((r) => r.json()).then((i) => {
        window.itin = i; window.pendant = []; window.accepter = true;
        window.carte3d.surPose((e) => {
          if (!e.fini) { window.pendant.push(window.carte3d.etat().couloirs); return; }
          if (!window.accepter) return;
          window.itin.noeuds[e.id].x = e.x; window.itin.noeuds[e.id].y = e.y;
          window.carte3d.afficherItineraires(window.itin);
        }, {genres: ['noeud']});
        fin(true);
      });""")
    assert firefox.js("return window.carte3d.etat().modifiables") == {"salle": True, "noeud": True}
    _cadrer(firefox, {"xmin": 6, "ymin": 4, "xmax": 16, "ymax": 10})

    def bouts(couloirs):
        return sorted(tuple(c["de"] if c["a"] == "couloir_sud_1" else c["vers"])
                      for c in couloirs if "couloir_sud_1" in (c["a"], c["b"]))

    avant = bouts(firefox.js("return window.carte3d.etat().couloirs"))
    assert avant and all(b == pytest.approx((11, 7)) for b in avant), avant
    _glisser_sol(firefox, [(11.0, 7.0), (11.0, 7.5), (11.0, 8.0)])
    pendant = [bouts(c) for c in firefox.js("return window.pendant")]
    assert any(b and all(p[1] > 7.2 for p in b) for b in pendant), pendant      # les couloirs ont suivi
    apres = bouts(firefox.js("return window.carte3d.etat().couloirs"))
    assert len(apres) == len(avant) and all(b == pytest.approx((11, 8)) for b in apres), apres
    assert firefox.js("return window.carte3d.positionRepere('noeud', 'couloir_sud_1')") == pytest.approx(
        firefox.js("return window.carte3d.versEcran(11, 8, 0)"), abs=0.5)
    # refusée : retour en (11 ; 8), couloirs compris
    firefox.js("window.accepter = false; window.pendant = [];")
    _glisser_sol(firefox, [(11.0, 8.0), (12.0, 8.0), (13.0, 8.0)])
    assert any(b and all(p[0] > 11.5 for p in b) for b in (bouts(c) for c in firefox.js("return window.pendant")))
    revenu = bouts(firefox.js("return window.carte3d.etat().couloirs"))
    assert all(b == pytest.approx((11, 8)) for b in revenu), revenu
    assert firefox.js("return window.carte3d.positionRepere('noeud', 'couloir_sud_1')") == pytest.approx(
        firefox.js("return window.carte3d.versEcran(11, 8, 0)"), abs=0.5)
    _sans_erreur(firefox)
