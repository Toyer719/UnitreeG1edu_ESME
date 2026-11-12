"""Outils communs aux tests de la carte 3D (agent Carte 3D, vague 5, section 12.3 du plan).

Pas de test ici : des fonctions et des fixtures, importées par les fichiers test_carte3d_*.py et par
tests_e2e/outils_carte3d_e2e.py.
  nuage_du_monde(monde)      nuage de test (x y z, repère map) : murs et objets échantillonnés tous les
                             5 cm, sol tous les 10 cm, plafond clairsemé à 2,6 m (caché par défaut)
  preparer_lieu(lieux, id)   copie de lieux/demo avec sa carte 2D et le nuage de test
                             cartes/rdc.nuage.bin + .json (atelier.lieu.nuage.ecrire_nuage)
  lancer_atelier(lieux)      g1-atelier sur ces lieux (port libre, sans ROS) : (processus, adresse)
  Navigateur                 Firefox sans fenêtre par geckodriver, en WebDriver simple (requêtes HTTP)
  FETCH_NUAGE                script : fetch de …/nuage remplacé par un binaire donné, tant que la route
                             de l'agent Scan répond 501 (section 12.9 du plan)
Fixtures : lieux_carte3d, atelier_carte3d, firefox, firefox_sans_webgl.
Le serveur et Firefox sont arrêtés à la fin de chaque test (groupes de processus).
"""
import base64
import json
import math
import os
import shutil
import signal
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
import pytest

import atelier
from atelier.lieu import charger_monde, copier_lieu
from atelier.lieu.nuage import chemin_nuage, entete_nuage, ecrire_nuage, fichiers_nuage

DEMO = atelier.RACINE / "lieux" / "demo"
G1_ATELIER = atelier.RACINE / "bin" / "g1-atelier"
GECKODRIVER = shutil.which("geckodriver")
FIREFOX = shutil.which("firefox")
PAS = 0.05            # m : murs et objets
PAS_SOL = 0.10        # m : sol
PAS_PLAFOND = 0.25    # m : plafond
Z_PLAFOND = 2.6       # m : au-dessus de la coupe de 2,2 m


# ---------------------------------------------------------------- nuage de test

def _grille(debut, fin, pas):
    n = max(1, int(round((fin - debut) / pas)))
    return np.linspace(debut, fin, n + 1)


def _surface_verticale(a, b, hauteur, pas=PAS):
    """Points d'une paroi verticale au-dessus du segment a → b, de z = 0 à hauteur."""
    longueur = math.dist(a, b)
    t = _grille(0.0, 1.0, pas / max(longueur, pas)) if longueur > 0 else np.array([0.0])
    z = _grille(0.0, hauteur, pas)
    tt, zz = np.meshgrid(t, z)
    x = a[0] + tt * (b[0] - a[0])
    y = a[1] + tt * (b[1] - a[1])
    return np.column_stack([x.ravel(), y.ravel(), zz.ravel()])


def _dessus_polygone(points, z, pas=PAS):
    """Points d'une face horizontale (polygone convexe à 4 coins) à la hauteur z."""
    p = np.asarray(points)
    o, u, v = p[0], p[1] - p[0], p[3] - p[0]
    s = _grille(0.0, 1.0, pas / max(np.linalg.norm(u), pas))
    t = _grille(0.0, 1.0, pas / max(np.linalg.norm(v), pas))
    ss, tt = np.meshgrid(s, t)
    xy = o + ss.ravel()[:, None] * u + tt.ravel()[:, None] * v
    return np.column_stack([xy, np.full(len(xy), z)])


def nuage_du_monde(monde, pas=PAS, sol=True, plafond=True):
    """Nuage de test d'un monde (atelier.lieu.Monde) : float32 (n, 3), repère map, z au-dessus du sol.
    Murs : une paroi sur leur axe ; objets : leurs côtés et leur dessus ; sol tous les 10 cm ; plafond
    clairsemé à 2,6 m (plus haut que la coupe de 2,2 m : caché par défaut)."""
    morceaux = []
    for m in monde.murs:
        morceaux.append(_surface_verticale(m.de, m.a, m.hauteur, pas))
    for o in monde.objets:
        forme = o.empreinte()
        h = o.hauteur_totale()
        if forme[0] == "cercle":
            centre, rayon = forme[1], forme[2]
            n = max(8, int(2 * math.pi * rayon / pas))
            angles = np.linspace(0, 2 * math.pi, n, endpoint=False)
            for z in _grille(0.0, h, pas):
                morceaux.append(np.column_stack([centre[0] + rayon * np.cos(angles), centre[1] + rayon * np.sin(angles),
                                                 np.full(n, z)]))
        else:
            coins = forme[1]
            for i in range(4):
                morceaux.append(_surface_verticale(coins[i], coins[(i + 1) % 4], h, pas))
            morceaux.append(_dessus_polygone(coins, h, pas))
    e = monde.emprise
    if sol:
        xs, ys = np.meshgrid(_grille(e.xmin, e.xmax, PAS_SOL), _grille(e.ymin, e.ymax, PAS_SOL))
        morceaux.append(np.column_stack([xs.ravel(), ys.ravel(), np.zeros(xs.size)]))
    if plafond:
        xs, ys = np.meshgrid(_grille(e.xmin, e.xmax, PAS_PLAFOND), _grille(e.ymin, e.ymax, PAS_PLAFOND))
        morceaux.append(np.column_stack([xs.ravel(), ys.ravel(), np.full(xs.size, Z_PLAFOND)]))
    points = np.concatenate(morceaux).astype(np.float32)
    # une seule fois par case de 1 cm (les coins des murs se recouvrent)
    _, uniques = np.unique(np.round(points / 0.01).astype(np.int64), axis=0, return_index=True)
    return points[np.sort(uniques)]


def ecrire_nuage_de_test(dossier_lieu, etage="rdc"):
    """Écrit cartes/<etage>.nuage.bin + .json depuis le monde de l'étage ; renvoie l'en-tête."""
    points = nuage_du_monde(charger_monde(dossier_lieu, etage))
    entete = entete_nuage(points, 0.05, [0.0, 0.0, 0.0], "scan", session=None, etage=etage,
                          note="nuage de test : monde du demo échantillonné (tests de la carte 3D)")
    return ecrire_nuage(chemin_nuage(dossier_lieu, etage), points, entete)


def preparer_lieu(lieux, ident="demo"):
    """Copie de lieux/demo dans lieux/<ident>, avec le nuage de test ; renvoie (dossier, en-tête)."""
    dossier = copier_lieu(DEMO, lieux / ident)
    return dossier, ecrire_nuage_de_test(dossier)


def nuage_en_base64(dossier_lieu, etage="rdc"):
    """Le binaire du nuage de l'étage, en base64 (pour FETCH_NUAGE)."""
    binaire, _ = fichiers_nuage(chemin_nuage(dossier_lieu, etage))
    return base64.b64encode(binaire.read_bytes()).decode("ascii")


# Remplace fetch pour les adresses …/nuage (route 501 tant que l'agent Scan ne l'a pas écrite) : la
# réponse est le binaire donné, avec les en-têtes X-Nuage-* de la section 12.4.
FETCH_NUAGE = """
const [donnees, entetes] = arguments;
const octets = Uint8Array.from(atob(donnees), (c) => c.charCodeAt(0));
const original = window.fetch.bind(window);
window.fetch = (url, options) => {
  if (typeof url === 'string' && /\\/nuage(\\?|$)/.test(url)) {
    return Promise.resolve(new Response(octets.slice().buffer, {status: 200, headers: Object.assign(
      {'Content-Type': 'application/octet-stream'}, entetes)}));
  }
  return original(url, options);
};
return octets.length;
"""


def entetes_http(entete):
    from atelier.lieu.nuage import entetes_http_nuage
    return entetes_http_nuage(entete)


# ---------------------------------------------------------------- serveur

def port_libre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def lancer_atelier(lieux, port=None):
    """g1-atelier sans navigateur ni pont ROS 2, sur le dossier de lieux : (processus, adresse)."""
    port = port or int(os.environ.get("CARTE3D_PORT") or port_libre())
    env = dict(os.environ, ATELIER_LIEUX=str(lieux), ATELIER_ROS="0", BROWSER="true")
    env.setdefault("ROS_DOMAIN_ID", "102")
    p = subprocess.Popen([str(G1_ATELIER), "--sans-navigateur", "--port", str(port)], env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
    adresse = f"http://127.0.0.1:{port}"
    fin = time.monotonic() + 40
    while time.monotonic() < fin:
        if p.poll() is not None:
            raise RuntimeError("g1-atelier s'est arrêté : " + p.stdout.read().decode()[-2000:])
        try:
            with urllib.request.urlopen(adresse + "/api/lieux", timeout=2) as r:
                if r.status == 200:
                    return p, adresse
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.25)
    arreter_groupe(p)
    raise RuntimeError(f"g1-atelier ne répond pas sur {adresse}")


def arreter_groupe(p, delai=10):
    if p.poll() is not None:
        return
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(p.pid, sig)
        except ProcessLookupError:
            return
        try:
            p.wait(timeout=delai)
            return
        except subprocess.TimeoutExpired:
            continue


def lire_api(adresse, chemin):
    with urllib.request.urlopen(adresse + chemin, timeout=20) as r:
        return json.loads(r.read())


def statut_http(adresse, chemin):
    try:
        with urllib.request.urlopen(adresse + chemin, timeout=20) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


# ---------------------------------------------------------------- Firefox

class Navigateur:
    """Client WebDriver minimal pour geckodriver (Firefox sans fenêtre)."""

    def __init__(self, port):
        self.base = f"http://127.0.0.1:{port}"
        self.session = None

    def _requete(self, methode, chemin, corps=None, delai=120):
        donnees = None if corps is None else json.dumps(corps).encode()
        req = urllib.request.Request(self.base + chemin, data=donnees, method=methode,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=delai) as r:
                return json.loads(r.read() or b"null")["value"]
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"WebDriver {methode} {chemin} : {e.read().decode()[:800]}") from None

    def demarrer(self, prefs=None, largeur=1400, hauteur=900):
        options = {"args": ["-headless", f"--width={largeur}", f"--height={hauteur}"],
                   "prefs": dict({"app.update.enabled": False, "toolkit.telemetry.enabled": False,
                                  "datareporting.policy.dataSubmissionEnabled": False}, **(prefs or {}))}
        valeur = self._requete("POST", "/session", {"capabilities": {"alwaysMatch": {
            "browserName": "firefox", "moz:firefoxOptions": options}}})
        self.session = valeur["sessionId"]

    def ouvrir(self, url):
        self._requete("POST", f"/session/{self.session}/url", {"url": url})

    def js(self, script, *args):
        return self._requete("POST", f"/session/{self.session}/execute/sync", {"script": script, "args": list(args)})

    def js_async(self, script, *args):
        """Script asynchrone : il rend son résultat en appelant arguments[arguments.length - 1]."""
        return self._requete("POST", f"/session/{self.session}/execute/async", {"script": script, "args": list(args)})

    def attendre(self, script, *args, delai=20.0, message=""):
        fin = time.monotonic() + delai
        dernier = None
        while time.monotonic() < fin:
            dernier = self.js(script, *args)
            if dernier:
                return dernier
            time.sleep(0.1)
        erreurs = self.js("return [window.erreursAtelier || null, window.essaiCarte3d ? window.essaiCarte3d.erreurs : null]")
        pytest.fail(f"délai dépassé : {message or script} (dernière valeur {dernier!r}) ; "
                    f"erreurs de la page : {erreurs}")

    def capture(self, chemin):
        """Capture de la fenêtre (PNG) dans chemin."""
        donnees = self._requete("GET", f"/session/{self.session}/screenshot")
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_bytes(base64.b64decode(donnees))
        return chemin

    def fermer(self):
        if self.session:
            try:
                self._requete("DELETE", f"/session/{self.session}", delai=60)
            except Exception:     # noqa: BLE001 : on arrête geckodriver de toute façon
                pass
            self.session = None


def ouvrir_firefox(prefs=None, largeur=1400, hauteur=900):
    """(navigateur, processus geckodriver) ; pytest.skip si Firefox ne démarre pas."""
    if GECKODRIVER is None or FIREFOX is None:
        pytest.skip("geckodriver ou Firefox absent")
    port = port_libre()
    gecko = subprocess.Popen([GECKODRIVER, "--port", str(port)], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
    nav = Navigateur(port)
    fin = time.monotonic() + 20
    while True:
        try:
            urllib.request.urlopen(nav.base + "/status", timeout=2)
            break
        except (urllib.error.URLError, ConnectionError, OSError):
            if time.monotonic() > fin or gecko.poll() is not None:
                arreter_groupe(gecko)
                pytest.skip("geckodriver ne démarre pas")
            time.sleep(0.2)
    try:
        nav.demarrer(prefs, largeur, hauteur)
    except Exception as e:      # noqa: BLE001
        arreter_groupe(gecko)
        pytest.skip(f"Firefox sans fenêtre ne démarre pas : {e}")
    return nav, gecko


def fermer_firefox(nav, gecko):
    nav.fermer()
    arreter_groupe(gecko)


RAISON_SANS_WEBGL = ("WebGL indisponible dans Firefox sans fenêtre : il lui faut un affichage X (variable DISPLAY, "
                     "ex. DISPLAY=:1 depuis la session graphique) ; aucune fenêtre ne s'ouvre pour autant")


def webgl_disponible(nav):
    """Vrai si Firefox crée un contexte WebGL (sans affichage X, Firefox sans fenêtre n'en a pas)."""
    return bool(nav.js("try { const c = document.createElement('canvas'); "
                       "return !!(c.getContext('webgl2') || c.getContext('webgl')); } catch (e) { return false; }"))


@pytest.fixture
def lieux_carte3d(tmp_path, monkeypatch):
    """Dossier de lieux temporaire avec une copie du demo (id « demo ») et son nuage de test."""
    lieux = tmp_path / "lieux"
    lieux.mkdir()
    monkeypatch.setenv("ATELIER_LIEUX", str(lieux))
    dossier, entete = preparer_lieu(lieux, "demo")
    return {"lieux": lieux, "dossier": dossier, "entete": entete}


@pytest.fixture
def atelier_carte3d(lieux_carte3d):
    """g1-atelier sur la copie du demo : dict {adresse, lieux, dossier, entete}."""
    p, adresse = lancer_atelier(lieux_carte3d["lieux"])
    try:
        yield dict(lieux_carte3d, adresse=adresse)
    finally:
        arreter_groupe(p)


@pytest.fixture
def firefox():
    """Firefox sans fenêtre avec WebGL (test sauté, avec la raison, s'il n'y a pas de WebGL)."""
    nav, gecko = ouvrir_firefox()
    try:
        if not webgl_disponible(nav):
            pytest.skip(RAISON_SANS_WEBGL)
        yield nav
    finally:
        fermer_firefox(nav, gecko)


@pytest.fixture
def firefox_sans_webgl():
    nav, gecko = ouvrir_firefox({"webgl.disabled": True})
    try:
        yield nav
    finally:
        fermer_firefox(nav, gecko)


def ouvrir_essai(nav, adresse, entete, dossier, **parametres):
    """Ouvre essais/carte3d.html sur le demo et attend qu'elle soit prête. Si la route du nuage répond 501
    (agent Scan pas encore passé), le nuage de test est servi par FETCH_NUAGE ; sinon par la route."""
    route = statut_http(adresse, "/api/lieux/demo/etages/rdc/nuage")
    p = dict({"lieu": "demo", "animation": "0", "mode": "reel"}, **parametres)
    charger = p["mode"] == "reel" and parametres.get("nuage") != "0"
    if route != 200:
        p["nuage"] = "0"
    nav.ouvrir(adresse + "/essais/carte3d.html?" + "&".join(f"{k}={v}" for k, v in p.items()))
    nav.attendre("return window.essaiCarte3d && window.essaiCarte3d.pret", message="page d'essai prête")
    if route != 200 and charger:
        nav.js(FETCH_NUAGE, nuage_en_base64(dossier), entetes_http(entete))
        r = nav.js_async("const fin = arguments[arguments.length - 1];"
                         "window.carte3d.chargerNuage('/api/lieux/demo/etages/rdc/nuage')"
                         ".then((r) => fin(r), (e) => fin({erreur: e.message}))")
        assert "erreur" not in r, r
    return route


# ---------------------------------------------------------------- gestes réels (API « actions » de WebDriver)

MAJ = ""     # touche Maj (Shift) de WebDriver


def actions(nav, sources):
    """Joue des actions WebDriver (souris, molette, clavier), puis relâche tout."""
    nav._requete("POST", f"/session/{nav.session}/actions", {"actions": sources})
    nav._requete("DELETE", f"/session/{nav.session}/actions")


def origine_toile(nav):
    """Coin haut gauche de la toile de la carte 3D, en pixels de la fenêtre."""
    r = nav.js("const r = document.querySelector('.carte3d').getBoundingClientRect(); return [r.left, r.top];")
    return r[0], r[1]


def glisser(nav, pixels, bouton=0, duree_ms=240, maj=False):
    """Appui, glissé par les points donnés (pixels de la carte 3D), relâché. bouton : 0 gauche, 1 milieu,
    2 droit. maj : Maj enfoncée pendant tout le geste."""
    ox, oy = origine_toile(nav)
    point = lambda p: {"x": int(round(ox + p[0])), "y": int(round(oy + p[1])), "origin": "viewport"}   # noqa: E731
    pas = [dict({"type": "pointerMove", "duration": 0}, **point(pixels[0])), {"type": "pointerDown", "button": bouton}]
    for p in pixels[1:]:
        pas.append(dict({"type": "pointerMove", "duration": max(1, duree_ms // max(1, len(pixels) - 1))}, **point(p)))
    pas.append({"type": "pointerUp", "button": bouton})
    sources = [{"type": "pointer", "id": "souris", "parameters": {"pointerType": "mouse"}, "actions": pas}]
    if maj:
        touches = ([{"type": "keyDown", "value": MAJ}] + [{"type": "pause"}] * (len(pas) - 2)
                   + [{"type": "keyUp", "value": MAJ}])
        sources.append({"type": "key", "id": "clavier", "actions": touches})
    actions(nav, sources)


def cliquer(nav, pixel, bouton=0):
    glisser(nav, [pixel, pixel], bouton=bouton, duree_ms=1)


def molette(nav, pixel, delta_y):
    """Un cran de molette (delta_y < 0 : on s'approche) au pixel donné de la carte 3D."""
    ox, oy = origine_toile(nav)
    actions(nav, [{"type": "wheel", "id": "molette", "actions": [{"type": "scroll", "duration": 0,
                   "x": int(round(ox + pixel[0])), "y": int(round(oy + pixel[1])), "origin": "viewport",
                   "deltaX": 0, "deltaY": int(delta_y)}]}])


def taper(nav, *touches):
    """Touches envoyées à l'élément qui a le focus (la carte 3D après focus())."""
    pas = []
    for t in touches:
        pas += [{"type": "keyDown", "value": t}, {"type": "keyUp", "value": t}]
    actions(nav, [{"type": "key", "id": "clavier", "actions": pas}])


def vers_ecran(nav, x, y, z=0.0):
    p = nav.js("return window.carte3d.versEcran(arguments[0], arguments[1], arguments[2])", x, y, z)
    assert p is not None, f"({x}, {y}, {z}) n'est pas devant la caméra"
    return p["x"], p["y"]


def attendre_camera(nav):
    """Attend la fin d'un changement de vue animé, puis un rendu."""
    nav.attendre("return window.carte3d && !window.carte3d.etat().anime", message="fin de l'animation de la caméra")
    nav.js_async("const fin = arguments[arguments.length - 1];"
                 "requestAnimationFrame(() => requestAnimationFrame(() => fin(true)));")


# ---------------------------------------------------------------- serveur statique (fonctions seules)

WEB = atelier.RACINE / "atelier" / "web"


class _Fichiers(SimpleHTTPRequestHandler):
    """Fichiers de atelier/web, sans journal ; les modules .js en text/javascript."""

    extensions_map = dict(SimpleHTTPRequestHandler.extensions_map, **{".js": "text/javascript"})

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def log_message(self, *args):      # pas de journal
        pass


def serveur_statique():
    """(serveur, adresse) : atelier/web servi tel quel sur un port libre, dans un fil."""
    serveur = ThreadingHTTPServer(("127.0.0.1", 0), _Fichiers)
    threading.Thread(target=serveur.serve_forever, daemon=True).start()
    return serveur, f"http://127.0.0.1:{serveur.server_address[1]}"


@pytest.fixture(scope="module")
def page_vide():
    """Firefox sur essais/carte3d.html?vide=1 (l'importmap, sans rien d'autre), servie par un serveur
    statique : pour essayer les fonctions des modules. Une seule page pour tout le fichier de tests."""
    serveur, adresse = serveur_statique()
    nav, gecko = ouvrir_firefox()
    try:
        nav.ouvrir(adresse + "/essais/carte3d.html?vide=1")
        nav.attendre("return window.essaiCarte3d && window.essaiCarte3d.pret", message="page vide prête")
        yield nav
    finally:
        fermer_firefox(nav, gecko)
        serveur.shutdown()
        serveur.server_close()


def appeler(nav, module, corps, *args):
    """Importe le module (adresse absolue, ex. /js/carte3d/geometrie3d.js) sous le nom M, exécute corps
    (du JavaScript qui rend une valeur avec « return ») avec args (tableau A), et rend la valeur."""
    script = ("const fin = arguments[arguments.length - 1]; const A = arguments[0];"
              f"import('{module}').then((M) => {{ try {{ fin({{ok: (function () {{ {corps} }})()}}); }}"
              " catch (e) { fin({erreur: String(e && e.message || e)}); } },"
              " (e) => fin({erreur: 'import : ' + String(e && e.message || e)}));")
    r = nav.js_async(script, list(args))
    if "erreur" in r:
        raise AssertionError(f"{module} : {r['erreur']}")
    return r["ok"]
