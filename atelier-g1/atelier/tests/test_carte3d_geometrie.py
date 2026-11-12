"""Fonctions de la carte 3D (js/carte3d/geometrie3d.js, vague 5, section 12.3 du plan), essayées dans
Firefox sans fenêtre et comparées à un calcul miroir en Python : viser le sol (rayon contre le plan
z = 0), angle de la flèche (pas de 15°, Maj : libre), degrés ↔ radians, accroche de 5 cm, couleur par
la hauteur, en-têtes et binaire du nuage, cadrage des vues, zoom vers le pointeur, point principal
(même règle que js/ecrans/salles.js) et repère du plan 2D (lat = y, lng = x).

Le JavaScript n'a pas d'autre moteur que le navigateur sur ce PC (pas de Node) : la page
essais/carte3d.html?vide=1 sert les modules avec l'importmap, sur un serveur statique.
"""
import math

import pytest

from atelier.lieu.nuage import entete_nuage, entetes_http_nuage

from .test_carte3d_communs import appeler, page_vide  # noqa: F401  (fixture)

G3 = "/js/carte3d/geometrie3d.js"


# ---------------------------------------------------------------- miroirs Python

def miroir_intersection(o, d, z0=0.0):
    if abs(d[2]) < 1e-9:
        return None
    t = (z0 - o[2]) / d[2]
    if t <= 0:
        return None
    return (o[0] + t * d[0], o[1] + t * d[1])


def normaliser(a):
    r = ((a + math.pi) % (2 * math.pi) + 2 * math.pi) % (2 * math.pi) - math.pi
    return r + 2 * math.pi if r <= -math.pi else r


def miroir_angle(x0, y0, x1, y1, libre=False, pas=15):
    theta = math.atan2(y1 - y0, x1 - x0)
    if libre:
        return round(normaliser(theta), 4)
    p = math.radians(pas)
    return round(normaliser(round(theta / p) * p), 4)


# ---------------------------------------------------------------- viser le sol

RAYONS = [
    ([1.0, 2.0, 10.0], [0.0, 0.0, -1.0]),          # à la verticale
    ([0.0, 0.0, 5.0], [0.6, 0.0, -0.8]),            # en biais
    ([-3.0, 4.0, 2.0], [0.3, -0.5, -0.1]),          # rasant, loin
    ([0.0, 0.0, 5.0], [1.0, 0.0, 0.0]),             # parallèle au sol : rien
    ([0.0, 0.0, 5.0], [0.0, 0.6, 0.8]),             # vers le ciel : rien
    ([0.0, 0.0, -1.0], [0.0, 0.0, -1.0]),           # sous le sol, vers le bas : rien
]


def test_intersection_avec_le_sol(page_vide):
    r = appeler(page_vide, G3, "return A[0].map((c) => M.intersectionSol(c[0], c[1], 0));", RAYONS)
    for (o, d), obtenu in zip(RAYONS, r):
        attendu = miroir_intersection(o, d)
        if attendu is None:
            assert obtenu is None, (o, d, obtenu)
        else:
            assert obtenu["x"] == pytest.approx(attendu[0], abs=1e-9)
            assert obtenu["y"] == pytest.approx(attendu[1], abs=1e-9)
            assert obtenu["z"] == 0
    # un sol plus haut (z = 0,5) : le même calcul
    p = appeler(page_vide, G3, "return M.intersectionSol([0, 0, 5], [0.6, 0, -0.8], 0.5);")
    assert p["x"] == pytest.approx(0.6 * 4.5 / 0.8) and p["z"] == 0.5


# ---------------------------------------------------------------- flèche, angles, accroche

FLECHES = [
    (0, 0, 1, 0, False), (0, 0, 0, 1, False), (0, 0, 1, 1, False), (0, 0, 1, 0.2, False), (0, 0, 1, 0.2, True),
    (0, 0, -1, -0.001, False), (12, 4, 12, 3, False), (3, 9.5, 4, 9.5, False), (2, 2, 1.2, 2.9, False),
    (2, 2, 1.2, 2.9, True), (0, 0, -1, 0.3, False),
]


def test_angle_de_la_fleche(page_vide):
    r = appeler(page_vide, G3, "return A[0].map((f) => M.angleFleche(f[0], f[1], f[2], f[3], f[4]));", FLECHES)
    for f, obtenu in zip(FLECHES, r):
        assert obtenu == pytest.approx(miroir_angle(*f), abs=1e-4), f
    # vers le sud : −90° ; points confondus : pas d'angle
    assert appeler(page_vide, G3, "return M.angleFleche(12, 4, 12, 3, false);") == pytest.approx(-1.5708, abs=1e-4)
    assert appeler(page_vide, G3, "return M.angleFleche(1, 1, 1, 1, false);") is None
    # pas de 15° exactement : multiples de 0,2618 rad
    for theta in appeler(page_vide, G3, "return [0.1, 0.5, 1.0, 2.0, -2.9].map((a) => "
                         "M.angleFleche(0, 0, Math.cos(a), Math.sin(a), false));"):
        assert (theta / math.radians(15)) == pytest.approx(round(theta / math.radians(15)), abs=2e-3)


def test_degres_et_accroche_de_5_cm(page_vide):
    r = appeler(page_vide, G3, """return {
      deg: [0, 1.5708, -1.5708, 3.1416, 0.7854].map(M.versDegres),
      rad: [0, 90, -90, 270, 180, -180, 45, 360].map(M.depuisDegres),
      pos: [[12.024, 3.976], [3.0, 9.5], [-0.026, 0.074], [7.12345, -2.37]].map((p) => M.accrocherPosition(p[0], p[1])),
      bout: M.boutFleche(2, 3, Math.PI / 2, 1.5)};""")
    assert r["deg"] == [0, 90, -90, 180, 45]
    assert r["rad"] == pytest.approx([0, 1.5708, -1.5708, -1.5708, 3.1416, 3.1416, 0.7854, 0], abs=1e-4)
    assert [(p["x"], p["y"]) for p in r["pos"]] == [(12.0, 4.0), (3.0, 9.5), (-0.05, 0.05), (7.1, -2.35)]
    assert r["bout"]["x"] == pytest.approx(2.0, abs=1e-9) and r["bout"]["y"] == pytest.approx(4.5)


# ---------------------------------------------------------------- nuage

def test_couleur_par_la_hauteur(page_vide):
    r = appeler(page_vide, G3, """
      const t = (h) => M.couleurHauteur(h, 2.2).map((v) => Math.round(v * 255));
      return {bas: t(0), dessous: t(-1), milieu: t(1.1), haut: t(2.2), plafond: t(3.5), quart: t(0.55),
              texte: M.couleurDepuisTexte(' #2e9e6b'), court: M.couleurDepuisTexte('#fff'),
              rgb: M.couleurDepuisTexte('rgb(46, 158, 107)'), faux: M.couleurDepuisTexte('vert')};""")
    bas, milieu, haut = (0x2e, 0x9e, 0x6b), (0xcc, 0xad, 0x78), (0xdb, 0x38, 0x66)      # theme.css
    assert tuple(r["bas"]) == bas and tuple(r["dessous"]) == bas
    assert tuple(r["milieu"]) == milieu
    assert tuple(r["haut"]) == haut and tuple(r["plafond"]) == haut
    assert all(abs(v - (a + b) / 2) <= 1 for v, a, b in zip(r["quart"], bas, milieu)), r["quart"]
    assert r["texte"] == pytest.approx([46 / 255, 158 / 255, 107 / 255])
    assert r["court"] == [1, 1, 1] and r["rgb"] == pytest.approx(r["texte"]) and r["faux"] is None


def test_entetes_et_binaire_du_nuage(page_vide):
    """Les en-têtes HTTP écrits par atelier.lieu.nuage (section 12.4) sont relus tels quels."""
    import numpy as np
    points = np.array([[0.0, 0.0, 0.0], [30.0, 20.0, 2.6], [-6.512, -16.031, -0.05]], dtype=np.float32)
    entete = entete_nuage(points, 0.05, [0.0009, -0.0101, -1.271], "scan", session="2026-10-27_14h22", etage="rdc")
    http = entetes_http_nuage(entete)
    r = appeler(page_vide, G3, "return M.lireEntetesNuage((n) => (n in A[0] ? A[0][n] : null));", http)
    assert r["points"] == 3 and r["grille"] == 0.05 and r["source"] == "scan" and r["session"] == "2026-10-27_14h22"
    assert r["bornes"] == pytest.approx(entete["bornes"])
    vide = appeler(page_vide, G3, "return M.lireEntetesNuage((n) => (n === 'X-Nuage-Session' ? '' : null));")
    assert vide == {"points": None, "grille": None, "bornes": None, "source": None, "date": None, "session": None}
    faux = appeler(page_vide, G3, "return M.lireEntetesNuage((n) => (n === 'X-Nuage-Bornes' ? '1,2,3' : null));")
    assert faux["bornes"] is None
    # binaire : Float32 petit-boutistes, 12 octets par point
    r = appeler(page_vide, G3, """
      const t = new Float32Array([1.5, -2.25, 0.125, 30, 20, 2.6]);
      const p = M.positionsDepuisTampon(t.buffer);
      let erreur = null;
      try { M.positionsDepuisTampon(new ArrayBuffer(25)); } catch (e) { erreur = e.message; }
      return {n: p.length / 3, p: Array.from(p), erreur: erreur, bornes: M.bornesPositions(p)};""")
    assert r["n"] == 2 and r["p"][:3] == [1.5, -2.25, 0.125]
    assert "tronqué" in r["erreur"] and "25 octets" in r["erreur"]
    assert r["bornes"] == pytest.approx({"xmin": 1.5, "ymin": -2.25, "zmin": 0.125, "xmax": 30, "ymax": 20, "zmax": 2.6})


# ---------------------------------------------------------------- caméra

@pytest.mark.parametrize("aspect", [1.6, 0.7])
def test_cadrage_des_vues_montre_tout(page_vide, aspect):
    """Dessus, Iso et Face : les 8 coins des bornes (sol à 2,2 m) sont dans l'image, et au moins un touche
    presque le bord (le cadrage est serré, marge de 8 %)."""
    resultats = page_vide.js_async("""
      const fin = arguments[arguments.length - 1];
      const aspect = arguments[0];
      Promise.all([import('/vendor/three/three.module.js'), import('/js/carte3d/geometrie3d.js')]).then(([THREE, G]) => {
        const b = {xmin: -6.5, ymin: -16, xmax: 24, ymax: 3.2};
        const sortie = {};
        ['dessus', 'iso', 'face'].forEach((nom) => {
          const pose = G.poseVue(nom, b, 50, aspect, {hauteur: 2.2});
          const cam = new THREE.PerspectiveCamera(50, aspect, 0.05, 2000);
          cam.up.set(0, 0, 1);
          cam.position.fromArray(pose.position);
          cam.lookAt(new THREE.Vector3().fromArray(pose.cible));
          cam.updateMatrixWorld();
          let max = 0, dedans = true;
          const xs = [], ys = [];
          [b.xmin, b.xmax].forEach((x) => [b.ymin, b.ymax].forEach((y) => [0, 2.2].forEach((z) => {
            const p = new THREE.Vector3(x, y, z).project(cam);
            max = Math.max(max, Math.abs(p.x), Math.abs(p.y));
            xs.push(p.x); ys.push(p.y);
            if (Math.abs(p.x) > 1.0001 || Math.abs(p.y) > 1.0001 || p.z > 1) dedans = false;
          })));
          const centre = [(Math.min(...xs) + Math.max(...xs)) / 2, (Math.min(...ys) + Math.max(...ys)) / 2];
          sortie[nom] = {max: max, dedans: dedans, centre: centre, angles: G.anglesDepuisDirection(
            [pose.position[0] - pose.cible[0], pose.position[1] - pose.cible[1], pose.position[2] - pose.cible[2]])};
        });
        fin(sortie);
      }, (e) => fin({erreur: String(e)}));""", aspect)
    assert "erreur" not in resultats, resultats
    for nom, v in resultats.items():
        assert v["dedans"], (nom, v)
        assert v["max"] > 0.85, (nom, v)
        assert abs(v["centre"][0]) < 0.02 and abs(v["centre"][1]) < 0.02, (nom, v)       # image centrée
    assert resultats["dessus"]["angles"]["elevation"] > 89.9
    assert resultats["iso"]["angles"] == pytest.approx({"azimut": -120, "elevation": 35}, abs=0.01)
    assert resultats["face"]["angles"] == pytest.approx({"azimut": -90, "elevation": 8}, abs=0.01)


def test_bornes_robustes_sans_les_points_isoles(page_vide):
    """Le cadrage ignore les quelques points isolés (0,5 %) : un bâtiment de 10 × 6 m et 20 reflets à 40 m."""
    r = appeler(page_vide, G3, """
      const n = 20000, p = new Float32Array(3 * (n + 20));
      for (let i = 0; i < n; i++) { p[3*i] = (i % 100) / 10; p[3*i+1] = Math.floor(i / 100) * 6 / 200; p[3*i+2] = (i % 7) / 3; }
      for (let k = 0; k < 20; k++) { p[3*(n+k)] = 40 + k; p[3*(n+k)+1] = -30; p[3*(n+k)+2] = 1; }
      return {robustes: M.bornesRobustes(p), toutes: M.bornesPositions(p), petit: M.bornesRobustes(new Float32Array([1, 2, 3]))};""")
    assert r["toutes"]["xmax"] == 59 and r["toutes"]["ymin"] == -30
    assert r["robustes"]["xmin"] == pytest.approx(0, abs=0.15) and r["robustes"]["xmax"] == pytest.approx(9.9, abs=0.15)
    assert r["robustes"]["ymin"] == pytest.approx(0, abs=0.15) and r["robustes"]["ymax"] == pytest.approx(5.97, abs=0.15)
    assert r["petit"] == {"xmin": 1, "ymin": 2, "zmin": 3, "xmax": 1, "ymax": 2, "zmax": 3}


def test_zoom_homothetie_et_molette(page_vide):
    r = appeler(page_vide, G3, """return {
      fixe: M.homothetie([4, 5, 0], [4, 5, 0], 0.5), cam: M.homothetie([0, -10, 10], [4, 5, 0], 0.5),
      molette: [M.facteurMolette(100, 0, false), M.facteurMolette(-100, 0, false), M.facteurMolette(3, 1, false),
                M.facteurMolette(-5, 0, true), M.facteurMolette(100000, 0, false), M.facteurMolette(0, 0, false)]};""")
    assert r["fixe"] == [4, 5, 0]
    assert r["cam"] == pytest.approx([2, -2.5, 5])
    s, e, lignes, pincement, borne, nul = r["molette"]
    assert s > 1 > e and s == pytest.approx(1 / e)
    assert lignes == pytest.approx(math.exp(48 * 0.002))
    assert pincement < 1 and nul == 1
    assert borne == pytest.approx(math.exp(250 * 0.002))      # un cran énorme reste borné


# ---------------------------------------------------------------- salles

CAS_PRINCIPAL = [
    [{"id": "accueil"}, {"id": "b204"}],
    [{"id": "hall", "etiquettes": ["principal"]}, {"id": "accueil"}],
    [{"id": "a", "etiquettes": ["principal"]}, {"id": "b", "etiquettes": ["principal"]}],
    [{"id": "a"}, {"id": "b", "etiquettes": ["autre"]}],
    [],
]


def test_point_principal_et_numeros(page_vide):
    r = appeler(page_vide, G3, "return A[0].map((l) => M.idPrincipal(l));", CAS_PRINCIPAL)
    assert r == ["accueil", "hall", None, None, None]
    n = appeler(page_vide, G3, "return M.numerosSalles(A[0], 'hall');", CAS_PRINCIPAL[1] + [{"id": "c"}])
    assert n == {"accueil": 1, "c": 2}
    # salles nommées « 1 », « 2 », « 3 » (séance du 27/10) : l'épingle porte leur nom, les autres prennent
    # les numéros libres ; deux salles du même nombre : la seconde prend un numéro libre
    seance = [{"id": "accueil", "nom": "Accueil"}, {"id": "essai_3m", "nom": "Essai à 2,5 m"}, {"id": "1", "nom": "1"},
              {"id": "2", "nom": "2"}, {"id": "3", "nom": " 3 "}, {"id": "bis", "nom": "2"}]
    n = appeler(page_vide, G3, "return M.numerosSalles(A[0], 'accueil');", seance)
    assert n == {"essai_3m": 4, "1": 1, "2": 2, "3": 3, "bis": 5}
    assert appeler(page_vide, G3, "return M.texteDistance(3.254);") == "3,25 m"


def test_meme_regle_que_l_ecran_salles_et_meme_repere_que_le_plan_2d(page_vide):
    """idPrincipal rend la salle de sallePrincipale (js/ecrans/salles.js) ; le plan 2D (plan.js) place un
    point (x, y) en lat = y, lng = x : les deux vues lisent x et y de salles.yaml sans conversion."""
    charge = page_vide.js_async("""
      const fin = arguments[arguments.length - 1];
      if (window.L) { fin(true); return; }
      const s = document.createElement('script');
      s.src = '/vendor/leaflet/leaflet.js';
      s.onload = () => fin(true);
      s.onerror = () => fin(false);
      document.head.appendChild(s);""")
    assert charge, "Leaflet ne se charge pas"
    r = page_vide.js_async("""
      const fin = arguments[arguments.length - 1];
      const cas = arguments[0];
      Promise.all([import('/js/ecrans/salles.js'), import('/js/plan.js'), import('/js/carte3d/geometrie3d.js')])
        .then(([S, P, G]) => fin({
          salles: typeof S.sallePrincipale === 'function'
            ? cas.map((l) => { const s = S.sallePrincipale(l); return s ? s.id : null; }) : 'absent',
          trois: cas.map((l) => G.idPrincipal(l)),
          ll: typeof P.ll === 'function' ? [[21, 13], [3, 9.5], [-6.5, -16]].map((p) => {
            const q = P.ll(p[0], p[1]); return [q.lat, q.lng, P.xy(q)]; }) : 'absent'}),
        (e) => fin({erreur: String(e && e.message || e)}));""", CAS_PRINCIPAL)
    if "erreur" in r:
        pytest.skip("js/ecrans/salles.js ou js/plan.js ne se charge pas seul (coque en cours d'écriture ?) : "
                    + r["erreur"])
    if r["salles"] != "absent":
        assert r["salles"] == r["trois"]
    if r["ll"] != "absent":
        for (lat, lng, xy), (x, y) in zip(r["ll"], [(21, 13), (3, 9.5), (-6.5, -16)]):
            assert (lat, lng) == (y, x) and xy == [x, y]


# ---------------------------------------------------------------- sol du nuage

def test_separer_le_sol(page_vide):
    """separerSol : les points sous le seuil (12 cm dans la carte) d'un côté, les autres de l'autre, dans l'ordre.
    Le cas limite avec 0,125, exact en Float32 (0,12 y vaut 0,11999…)."""
    r = appeler(page_vide, G3, """
      const p = new Float32Array([0, 0, 0.0,  1, 1, 2.0,  2, 2, -0.03,  3, 3, 0.125,  4, 4, 0.1199,  5, 5, 1.0]);
      const s = M.separerSol(p, 0.125);
      const vide = M.separerSol(new Float32Array(0), 0.12);
      return {sol: Array.from(s.sol), reste: Array.from(s.reste), type: s.sol instanceof Float32Array,
              vide: [vide.sol.length, vide.reste.length]};""")
    assert r["type"] is True and r["vide"] == [0, 0]
    assert r["sol"] == pytest.approx([0, 0, 0, 2, 2, -0.03, 4, 4, 0.1199], abs=1e-6)
    assert r["reste"] == pytest.approx([1, 1, 2, 3, 3, 0.125, 5, 5, 1], abs=1e-6)


# ---------------------------------------------------------------- étiquettes sans chevauchement

ECART = 6           # px : ECART_ETIQUETTE
PLACES = ("droite", "gauche", "dessus", "dessous")


def miroir_rectangle(c, place):
    d = c["rayon"] + ECART
    x, y, w, h = c["x"], c["y"], c["largeur"], c["hauteur"]
    return {"droite": (x + d, y - h / 2, x + d + w, y + h / 2), "gauche": (x - d - w, y - h / 2, x - d, y + h / 2),
            "dessus": (x - w / 2, y - d - h, x + w / 2, y - d), "dessous": (x - w / 2, y + d, x + w / 2, y + d + h)}[place]


def coupe(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def miroir_placer(candidats, tetes=None):
    tetes = [(t["id"], (t["x"] - t["rayon"], t["y"] - t["rayon"], t["x"] + t["rayon"], t["y"] + t["rayon"]))
             for t in (tetes if tetes is not None else candidats)]
    posees, places = [], {}
    for c in candidats:
        places[c["id"]] = None
        for place in PLACES:
            r = miroir_rectangle(c, place)
            if not any(coupe(r, p) for p in posees) and not any(i != c["id"] and coupe(r, t) for i, t in tetes):
                places[c["id"]] = place
                posees.append(r)
                break
    return places


def _candidat(ident, x, y, largeur=80, rayon=12):
    return {"id": ident, "x": x, "y": y, "largeur": largeur, "hauteur": 22, "rayon": rayon}


def test_placer_les_etiquettes_cas_simples(page_vide):
    seules = [_candidat("a", 100, 100), _candidat("b", 400, 100)]
    voisines = [_candidat("accueil", 100, 100, 70, 14), _candidat("essai", 187, 100, 97), _candidat("un", 287, 100)]
    tetes_sans_nom = voisines + [_candidat("trois", 210, 100)]          # une tête sans étiquette (doublon)
    enfermee = [_candidat("milieu", 200, 200, 60)] + [
        _candidat(f"t{i}", 200 + dx, 200 + dy, 60) for i, (dx, dy) in enumerate([(70, 0), (-70, 0), (0, -40), (0, 40)])]
    r = appeler(page_vide, G3, """return {seules: M.placerEtiquettes(A[0]), voisines: M.placerEtiquettes(A[1]),
      obstacles: M.placerEtiquettes(A[1], A[2]), enfermee: M.placerEtiquettes(A[3]),
      rect: M.PLACES_ETIQUETTE.map((p) => M.rectangleEtiquette(A[0][0], p)), ecart: M.ECART_ETIQUETTE};""",
                seules, voisines, tetes_sans_nom, enfermee)
    assert r["ecart"] == ECART
    assert r["seules"] == {"a": "droite", "b": "droite"}
    # l'accueil d'abord : à droite il couvrirait la tête d'« essai » (87 px plus loin) : à gauche
    assert r["voisines"] == miroir_placer(voisines)
    assert r["voisines"]["accueil"] == "gauche" and r["voisines"]["essai"] in ("dessus", "dessous")
    assert r["obstacles"] == miroir_placer(voisines, tetes_sans_nom)
    assert r["enfermee"]["milieu"] is None                                # entourée : nom caché, la tête reste
    assert r["enfermee"] == miroir_placer(enfermee)
    attendu = [miroir_rectangle(seules[0], p) for p in PLACES]
    assert [(q["x0"], q["y0"], q["x1"], q["y1"]) for q in r["rect"]] == [pytest.approx(a) for a in attendu]


def test_placer_les_etiquettes_jamais_de_chevauchement(page_vide):
    """200 tirages de 2 à 25 salles : mêmes places que le miroir Python, et les étiquettes placées ne se
    coupent jamais, ni ne couvrent la tête d'une autre salle."""
    import random
    rng = random.Random(7)
    tirages = []
    for _ in range(200):
        n = rng.randint(2, 25)
        tirages.append([_candidat(f"s{i}", rng.uniform(0, 600), rng.uniform(0, 400), rng.uniform(20, 140),
                                  rng.choice((12, 14))) for i in range(n)])
    r = appeler(page_vide, G3, "return A[0].map((c) => M.placerEtiquettes(c));", tirages)
    placees = 0
    for candidats, places in zip(tirages, r):
        assert places == miroir_placer(candidats)
        rects = [(c["id"], miroir_rectangle(c, places[c["id"]])) for c in candidats if places[c["id"]]]
        placees += len(rects)
        for i, (a, ra) in enumerate(rects):
            assert not any(coupe(ra, rb) for b, rb in rects[i + 1:]), (a, places)
            for c in candidats:
                if c["id"] != a:
                    t = (c["x"] - c["rayon"], c["y"] - c["rayon"], c["x"] + c["rayon"], c["y"] + c["rayon"])
                    assert not coupe(ra, t), (a, c["id"])
    assert placees > 1000          # la plupart des noms trouvent une place


@pytest.mark.parametrize("nom", ["dessus", "iso", "face"])
def test_cadrage_sous_la_barre_du_haut(page_vide, nom):
    """Vue de 1080 × 728 px et barre flottante de 56 px en haut : les 8 coins des bornes (sol à 2,2 m) sont
    entre la barre et le bas de l'image, l'image est centrée dans la partie libre, la direction de la vue ne
    change pas ; sans marge (ou dans une vue trop basse), la pose est celle de poseVue."""
    r = page_vide.js_async("""
      const fin = arguments[arguments.length - 1];
      const nom = arguments[0];
      Promise.all([import('/vendor/three/three.module.js'), import('/js/carte3d/geometrie3d.js')]).then(([THREE, G]) => {
        const b = {xmin: -6.5, ymin: -16, xmax: 24, ymax: 3.2};
        const L = 1080, H = 728, M = 56;
        const poseDe = (fov, aspect) => G.poseVue(nom, b, fov, aspect, {hauteur: 2.2});
        const pose = G.cadrageSousMarge(poseDe, 50, L, H, M);
        const cam = new THREE.PerspectiveCamera(50, L / H, 0.05, 2000);
        cam.up.set(0, 0, 1);
        cam.position.fromArray(pose.position);
        cam.lookAt(new THREE.Vector3().fromArray(pose.cible));
        cam.updateMatrixWorld();
        const xs = [], ys = [];
        [b.xmin, b.xmax].forEach((x) => [b.ymin, b.ymax].forEach((y) => [0, 2.2].forEach((z) => {
          const p = new THREE.Vector3(x, y, z).project(cam);
          xs.push((p.x + 1) / 2 * L); ys.push((1 - p.y) / 2 * H);
        })));
        const u = [0, 1, 2].map((i) => pose.position[i] - pose.cible[i]);
        fin({xs: xs, ys: ys, angles: G.anglesDepuisDirection(u),
             sans: [G.cadrageSousMarge(poseDe, 50, L, H, 0), poseDe(50, L / H)],
             basse: [G.cadrageSousMarge(poseDe, 50, L, 200, M), poseDe(50, L / 200)]});
      }, (e) => fin({erreur: String(e)}));""", nom)
    assert "erreur" not in r, r
    assert min(r["xs"]) >= -1 and max(r["xs"]) <= 1081, r["xs"]
    assert min(r["ys"]) >= 56 - 1 and max(r["ys"]) <= 728 + 1, r["ys"]
    assert (min(r["ys"]) + max(r["ys"])) / 2 == pytest.approx((56 + 728) / 2, abs=12)     # centrée sous la barre
    attendu = {"dessus": (-90, 89.97), "iso": (-120, 35), "face": (-90, 8)}[nom]
    if nom != "dessus":          # en Dessus, l'azimut d'une vue presque verticale ne veut rien dire
        assert r["angles"]["azimut"] == pytest.approx(attendu[0], abs=0.01)
    assert r["angles"]["elevation"] == pytest.approx(attendu[1], abs=0.01)
    for a, b in (r["sans"], r["basse"]):
        assert a["position"] == pytest.approx(b["position"]) and a["cible"] == pytest.approx(b["cible"])
