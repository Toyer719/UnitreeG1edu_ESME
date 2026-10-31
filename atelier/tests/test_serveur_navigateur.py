"""Parcours principal de l'interface dans un vrai navigateur, sans fenêtre (critère 9 du plan), sur la coque
de la vague 5 (section 12.2) : accueil → Nouveau lieu (Simulation) → Ouvrir → Dessiner (mur, objet, départ,
piéton, annuler, rétablir, passage) → ✓ Enregistrer (la carte se refait seule) → Placer › Salle (plan 2D) →
Placer › Relier → Placer › Zone interdite → Simuler › Lancer → Y aller → ARRÊT → Arrêter → Scan simulé.

Firefox est piloté par geckodriver, en WebDriver simple (requêtes HTTP), avec -headless. Pas de Playwright.
Le test est sauté si geckodriver ou Firefox manquent, ou si Firefox ne démarre pas. Les gestes (cliquer-
glisser sur le plan) sont des PointerEvent envoyés par script. Les éléments sont trouvés par les repères
stables de la coque (data-role, data-commande, data-onglet, data-ecran ; section 12.2 du plan), jamais par
leur texte. Serveur : bin/g1-atelier, comme en vrai, sur une copie de demo, avec les fausses commandes g1-*.
"""
import json
import os
import shutil
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request

import pytest

from .test_serveur_communs import faux_bin, journaux, lieux  # noqa: F401
from .test_serveur_demarrage import serveur  # noqa: F401

GECKODRIVER = shutil.which("geckodriver")
pytestmark = pytest.mark.skipif(GECKODRIVER is None or shutil.which("firefox") is None,
                                reason="geckodriver ou Firefox absent")

# Geste sur le plan : PointerEvent envoyés au cadre du plan, en coordonnées relatives au plan (0 à 1)
GESTE = """
const [selecteur, points, relacher] = arguments;
const cadre = document.querySelector(selecteur + ' .plan-cadre');
const r = cadre.getBoundingClientRect();
const ev = (type, p, boutons) => cadre.dispatchEvent(new PointerEvent(type, {
  bubbles: true, cancelable: true, pointerId: 7, pointerType: 'mouse', isPrimary: true,
  button: 0, buttons: boutons, clientX: r.left + p[0] * r.width, clientY: r.top + p[1] * r.height}));
ev('pointerdown', points[0], 1);
for (const p of points.slice(1)) ev('pointermove', p, 1);
if (relacher) ev('pointerup', points[points.length - 1], 0);
return [r.width, r.height];
"""

# Clic sur une commande du ruban ([data-commande=id]) ; avec une valeur, le choix du menu qui s'ouvre
COMMANDE = """
const [id, valeur] = arguments;
if (document.querySelector('[data-role=vue-plan].chargement')) return false;     // écran pas encore prêt
const b = document.querySelector('[data-commande="' + id + '"]');
if (!b || b.disabled) return false;
b.click();
if (valeur === null || valeur === undefined) return true;
const choix = document.querySelector('.menu-ruban [data-valeur="' + valeur + '"]');
if (!choix) return false;
choix.click();
return true;
"""

CLIC = """
const [selecteur] = arguments;
if (document.querySelector('[data-role=vue-plan].chargement')) return false;
const b = document.querySelector(selecteur);
if (!b || b.disabled) return false;
b.click();
return true;
"""

# Donne une valeur à un champ (input ou textarea) et déclenche « input » et « change », comme une saisie
CHAMP = """
const [selecteur, valeur] = arguments;
const c = document.querySelector(selecteur);
if (!c) return false;
c.value = valeur;
c.dispatchEvent(new Event('input', { bubbles: true }));
c.dispatchEvent(new Event('change', { bubbles: true }));
return true;
"""


class Navigateur:
    """Client WebDriver minimal pour geckodriver."""

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
            raise RuntimeError(f"WebDriver {methode} {chemin} : {e.read().decode()[:500]}") from None

    def demarrer(self, prefs=None):
        p = {"app.update.enabled": False, "toolkit.telemetry.enabled": False,
             "datareporting.policy.dataSubmissionEnabled": False}
        p.update(prefs or {})
        options = {"args": ["-headless", "--width=1400", "--height=900"], "prefs": p}
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

    def attendre(self, script, *args, delai=15.0, message=""):
        fin = time.monotonic() + delai
        dernier = None
        while time.monotonic() < fin:
            dernier = self.js(script, *args)
            if dernier:
                return dernier
            time.sleep(0.2)
        erreurs = self.js("return [window.erreursAtelier, Array.from(document.querySelectorAll('.message-erreur, "
                          ".message-avertissement')).map(e => e.textContent)]")
        pytest.fail(f"délai dépassé : {message or script} (dernière valeur {dernier!r}) ; erreurs de la page : {erreurs}")

    def taille(self, largeur, hauteur):
        """Zone d'affichage de largeur × hauteur pixels (la fenêtre est un peu plus grande)."""
        self._requete("POST", f"/session/{self.session}/window/rect", {"width": largeur, "height": hauteur})
        time.sleep(0.2)
        iw, ih = self.js("return [window.innerWidth, window.innerHeight]")
        self._requete("POST", f"/session/{self.session}/window/rect",
                      {"width": largeur + (largeur - iw), "height": hauteur + (hauteur - ih)})
        time.sleep(0.4)

    # ------------------------------------------------------------ la coque (repères stables, section 12.2)

    def commande(self, ident, valeur=None, delai=30.0):
        """Clic sur [data-commande=ident] du ruban (son onglet est choisi d'abord) ; valeur : le choix du menu."""
        onglet = self.js("const b = document.querySelector('[data-commande=\"' + arguments[0] + '\"]');"
                         "return b ? null : arguments[0];", ident)
        if onglet:
            # la commande n'est pas dans l'onglet affiché : on cherche son onglet par le registre du ruban
            ou = self.js_async("const [id, fini] = arguments; import('/js/coque/ruban.js').then((R) => "
                               "{ const c = R.commande(id); fini(c ? [c.onglet, c.avance] : null); });", ident)
            assert ou, f"commande inconnue : {ident}"
            self.onglet(ou[0])
            if ou[1]:
                self.attendre(CLIC, "[data-role=avance]", message="menu Avancé")
        assert self.attendre(COMMANDE, ident, valeur, delai=delai, message=f"commande {ident}")

    def onglet(self, ident):
        assert self.attendre(CLIC, f"[data-onglet='{ident}']", delai=30.0, message=f"onglet {ident}")

    def clic(self, selecteur, delai=30.0, message=""):
        assert self.attendre(CLIC, selecteur, delai=delai, message=message or f"clic sur {selecteur}")

    def ecran(self, ident, delai=30.0):
        self.attendre(f"return document.querySelector('[data-ecran={ident}]') && "
                      "!document.querySelector('[data-role=vue-plan].chargement') && "
                      "!document.querySelector('.chargement-panneau')", delai=delai, message=f"écran {ident}")

    def vue(self, nom):
        """Choisit la vue centrale (3d, plan, camera) si elle est proposée ; renvoie la vue affichée."""
        self.js("const b = document.querySelector('[data-vue=' + arguments[0] + ']'); if (b && !b.hidden) b.click();", nom)
        return self.js("return document.querySelector('[data-role=vue]').getAttribute('data-vue')")

    def ok(self):
        """✓ du panneau de tâches (Enregistrer)."""
        self.clic("[data-role=ok]", message="✓ du panneau")

    def champ(self, selecteur, valeur):
        assert self.js(CHAMP, selecteur, valeur), f"champ introuvable : {selecteur}"

    def messages(self, genre):
        return self.js("return Array.from(document.querySelectorAll('[data-role=journal] .message-' + arguments[0] + "
                       "' .message-texte')).map(e => e.textContent)", genre)

    def geste(self, ecran, points, relacher=True):
        self.ecran(ecran)
        return self.js(GESTE, f"[data-ecran={ecran}]", points, relacher)

    def clic_plan(self, ecran, p):
        self.geste(ecran, [p, p])

    def capture(self, chemin):
        import base64
        from pathlib import Path
        png = self._requete("GET", f"/session/{self.session}/screenshot")
        Path(chemin).parent.mkdir(parents=True, exist_ok=True)
        Path(chemin).write_bytes(base64.b64decode(png))

    def fermer(self):
        if self.session:
            try:
                self._requete("DELETE", f"/session/{self.session}", delai=60)
            except Exception:     # noqa: BLE001 : on arrête geckodriver de toute façon
                pass
            self.session = None


def _port_libre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def demarrer_navigateur(prefs=None):
    """(geckodriver, Navigateur prêt), ou pytest.skip. À arrêter avec arreter_navigateur."""
    port = _port_libre()
    gecko = subprocess.Popen([GECKODRIVER, "--port", str(port)], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
    nav = Navigateur(port)
    fin = time.monotonic() + 20
    while True:
        try:
            urllib.request.urlopen(nav.base + "/status", timeout=2)
            break
        except (urllib.error.URLError, ConnectionError):
            if time.monotonic() > fin or gecko.poll() is not None:
                arreter_navigateur(gecko, nav)
                pytest.skip("geckodriver ne démarre pas")
            time.sleep(0.2)
    try:
        nav.demarrer(prefs)
    except Exception as e:      # noqa: BLE001
        arreter_navigateur(gecko, nav)
        pytest.skip(f"Firefox sans fenêtre ne démarre pas : {e}")
    return gecko, nav


def arreter_navigateur(gecko, nav):
    nav.fermer()
    try:
        os.killpg(gecko.pid, signal.SIGTERM)
        gecko.wait(timeout=10)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(gecko.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


@pytest.fixture
def navigateur(tmp_path):
    gecko, nav = demarrer_navigateur()
    try:
        yield nav
    finally:
        arreter_navigateur(gecko, nav)


@pytest.fixture
def sans_ros(monkeypatch):
    """Serveur sans pont ROS 2 : « Y aller » répond alors qu'il manque ROS 2 (pas de Nav2 à attendre)."""
    monkeypatch.setenv("ATELIER_ROS", "0")


def _api(base, chemin):
    with urllib.request.urlopen(base + chemin, timeout=20) as r:
        return json.loads(r.read())


def ouvrir_espace(nav, base, mode="simu", repetition=False, lieu="demo", hash_="", etage="rdc"):
    """Ouvre directement l'espace de travail (la mémoire du navigateur, puis une adresse avec ?recharger)."""
    nav.ouvrir(base + "/")
    nav.attendre("return document.querySelector('[data-role=accueil]') !== null", message="accueil")
    nav.js("localStorage.clear(); localStorage.setItem('atelier.lieu', arguments[0]);"
           "localStorage.setItem('atelier.etage', arguments[1]); localStorage.setItem('atelier.mode', arguments[2]);"
           "localStorage.setItem('atelier.repetition', arguments[3] ? '1' : '0');"
           "localStorage.setItem('atelier.mode-simulation', arguments[2] === 'simu' ? 'simu' : (arguments[3] ? 'repetition' : 'robot'));",
           lieu, etage, mode, repetition)
    nav.ouvrir(base + "/?recharger=1" + hash_)
    nav.attendre("return document.querySelector('[data-role=espace]') !== null", message="espace de travail")


def test_parcours_principal_dans_le_navigateur(sans_ros, serveur, navigateur, lieux, faux_bin):
    _, base = serveur
    nav = navigateur
    L = "/api/lieux/essai_nav"

    # Accueil : Simulation, Nouveau lieu, Ouvrir
    nav.ouvrir(base + "/")
    nav.attendre("return document.querySelector('[data-role=liste-lieux] [data-lieu=demo]')", message="lieux de l'accueil")
    nav.clic("[data-role=mode-simu]")
    assert nav.js("return document.querySelector('[data-role=mode-simu]').getAttribute('aria-pressed')") == "true"
    nav.clic("[data-role=nouveau-lieu]")
    nav.champ("[data-role=nom-lieu]", "Essai nav")
    nav.clic("[data-role=creer-lieu]")
    nav.attendre("return document.querySelector('[data-lieu=essai_nav][aria-selected=true]')", message="lieu créé et choisi")
    assert len(_api(base, "/api/lieux")) == 2
    nav.clic("[data-role=ouvrir]")
    nav.attendre("return document.querySelector('[data-role=espace][data-mode=simu]')", message="espace Simulation")
    assert nav.js("return document.querySelector('[data-role=lieu]').value") == "essai_nav"
    assert nav.js("return Array.from(document.querySelectorAll('[data-onglet]')).map(b => b.dataset.onglet)") == [
        "dessiner", "placer", "simuler", "equipe"]

    # Dessiner : le monde neuf (4 murs), un mur cliquer-glisser, un objet, le déplacer et le tourner
    nav.commande("monde.choisir")
    nav.ecran("monde")
    assert nav.vue("plan") == "plan"
    nav.attendre("return document.querySelectorAll('[data-ecran=monde] path.mur').length === 4", message="monde neuf")
    nav.commande("monde.mur")
    assert nav.js("return document.querySelector('[data-commande=\"monde.mur\"]').getAttribute('aria-pressed')") == "true"
    nav.geste("monde", [[0.35, 0.5], [0.45, 0.5], [0.6, 0.5]])
    nav.attendre("return document.querySelectorAll('[data-ecran=monde] path.mur').length === 5", message="mur tracé")
    nav.attendre("return !document.querySelector('[data-role=enregistrer]').disabled", message="Enregistrer actif")
    nav.commande("monde.objet", "table")
    nav.clic_plan("monde", [0.5, 0.35])
    nav.attendre("return document.querySelectorAll('[data-ecran=monde] path.objet').length === 1", message="objet posé")
    nav.commande("monde.choisir")
    position = "const r = document.querySelector('[data-ecran=monde] path.objet').getBoundingClientRect(); return r.left;"
    avant = nav.js(position)
    nav.geste("monde", [[0.5, 0.35], [0.52, 0.35], [0.55, 0.35]])
    assert nav.js(position) > avant + 20, "l'objet n'a pas suivi le glissé"
    nav.js("""const l = Array.from(document.querySelectorAll('[data-role=panneau-corps] label'))
                .find((x) => x.textContent.startsWith('Rotation'));
              const i = l.querySelector('input'); i.value = '90'; i.dispatchEvent(new Event('change'));""")
    # départ du robot : clic puis glissé vers le haut de l'écran (le nord)
    nav.commande("monde.depart")
    nav.geste("monde", [[0.2, 0.8], [0.2, 0.75], [0.2, 0.7]])
    # piéton : deux points, puis « Terminer le trajet » dans le panneau
    nav.commande("monde.pieton")
    nav.clic_plan("monde", [0.3, 0.65])
    nav.clic_plan("monde", [0.6, 0.65])
    nav.attendre("return Array.from(document.querySelectorAll('[data-section=outil] button')).some(b => "
                 "b.textContent.startsWith('Terminer') && !b.disabled)", message="Terminer le trajet")
    nav.js("Array.from(document.querySelectorAll('[data-section=outil] button')).find(b => b.textContent.startsWith('Terminer')).click()")
    nav.attendre("return document.querySelectorAll('[data-ecran=monde] path.trajet-pieton').length >= 1", message="piéton")
    nav.clic("[data-role=defaire]")
    nav.attendre("return document.querySelectorAll('[data-ecran=monde] path.trajet-pieton').length === 0", message="annuler")
    nav.clic("[data-role=refaire]")
    nav.attendre("return document.querySelectorAll('[data-ecran=monde] path.trajet-pieton').length >= 1", message="rétablir")
    nav.commande("monde.passage")
    nav.js(GESTE, "[data-ecran=monde]", [[0.5, 0.5]], False)       # survol puis clic sur le mur tracé
    nav.clic_plan("monde", [0.5, 0.5])
    nav.attendre("return document.querySelectorAll('[data-ecran=monde] path.mur').length === 6", message="passage coupé")
    # ✓ Enregistrer : le monde, puis la carte du robot refaite seule
    nav.ok()
    nav.attendre("return document.querySelector('[data-role=ok]').disabled", message="monde enregistré")
    monde = _api(base, L + "/etages/rdc/monde")
    assert (len(monde["murs"]), len(monde["objets"]), len(monde["pietons"])) == (6, 1, 1)
    assert monde["objets"][0]["modele"] == "table" and abs(monde["objets"][0]["cap"] - 1.5708) < 1e-3
    assert abs(monde["depart_robot"]["theta"] - 1.5708) < 0.01 and monde["depart_robot"]["x"] != 1.0
    fin = time.monotonic() + 30
    while time.monotonic() < fin and not any(a.startswith("g1-monde generer") for a in faux_bin.appels()):
        time.sleep(0.2)
    assert any(a.startswith("g1-monde generer") for a in faux_bin.appels()), "la carte ne s'est pas refaite"
    nav.attendre("return Array.from(document.querySelectorAll('[data-role=journal] .message-succes')).some("
                 "m => m.textContent.includes('Carte du robot à jour'))", delai=30, message="carte refaite")

    # Placer › Salle, sur le plan 2D : clic puis glissé vers le haut, nom dans le panneau, ✓
    nav.commande("salles.salle")
    nav.ecran("salles")
    nav.vue("plan")
    nav.geste("salles", [[0.7, 0.3], [0.7, 0.2], [0.7, 0.1]])
    nav.attendre("return document.querySelector('[data-role=panneau-corps] [data-champ=nom] input')", message="panneau salle")
    nav.champ("[data-role=panneau-corps] [data-champ=nom] input", "Labo de physique")
    nav.ok()
    nav.attendre("return document.querySelector('[data-role=ok]').disabled", message="salles enregistrées")
    salles = _api(base, L + "/salles")
    labo = next(s for s in salles if s["id"] == "labo_de_physique")
    assert labo["nom"] == "Labo de physique" and abs(labo["pose"]["theta"] - 1.5708) < 0.01   # glissé vers le haut
    assert "labo_de_physique" in _api(base, L + "/itineraires")["noeuds"]
    # l'arbre du lieu montre la salle
    nav.attendre("return document.querySelector('[data-role=arbre] [data-noeud=\"salle:labo_de_physique\"]')",
                 message="salle dans l'arbre")

    # Placer › Relier : l'accueil et la salle
    nav.commande("itineraires.relier")
    nav.ecran("itineraires")
    nav.attendre("return document.querySelectorAll('[data-ecran=itineraires] .noeud').length === 2", message="nœuds")
    nav.js("document.querySelectorAll('[data-ecran=itineraires] .noeud')[0].click()")
    nav.js("document.querySelectorAll('[data-ecran=itineraires] .noeud')[1].click()")
    nav.attendre("return document.querySelectorAll('[data-ecran=itineraires] path.couloir').length === 1", message="couloir")
    nav.ok()
    nav.attendre("return document.querySelector('[data-role=ok]').disabled", message="itinéraires enregistrés")
    assert len(_api(base, L + "/itineraires")["couloirs"]) == 1

    # Placer › Zone interdite : trois coins, « Terminer la zone », ✓
    nav.commande("zones.interdite")
    nav.ecran("zones")
    for p in ([0.2, 0.2], [0.3, 0.2], [0.3, 0.3]):
        nav.clic_plan("zones", p)
    nav.js("Array.from(document.querySelectorAll('[data-section=outil] button')).find(b => b.textContent.startsWith('Terminer')).click()")
    nav.ok()
    nav.attendre("return document.querySelector('[data-role=ok]').disabled", message="zones enregistrées")
    assert len(_api(base, L + "/zones")["interdites"]) == 1

    # Simuler : Lancer, Y aller, ARRÊT, Arrêter
    nav.commande("simulation.lancer")
    nav.ecran("simulation")
    nav.attendre("return document.querySelector('[data-role=etat-simu]').textContent.includes('Simulation en cours')",
                 delai=20, message="simulation en cours")
    assert _api(base, "/api/simulation/etat")["simulation"]["en_cours"]
    nav.attendre("return document.querySelectorAll('[data-role=salles] li button').length === 2", message="Y aller")
    nav.js("document.querySelectorAll('[data-role=salles] li button')[1].click()")
    nav.attendre("return Array.from(document.querySelectorAll('[data-role=journal] .message-erreur')).some(m => "
                 "m.textContent.includes('Pas de liaison avec ROS 2'))", message="Y aller sans ROS 2")
    nav.clic("[data-role=arret]")
    nav.attendre("return document.querySelector('[data-role=etat-message]').textContent.includes('ARRÊT')", message="ARRÊT")
    fin = time.monotonic() + 15
    while time.monotonic() < fin and "g1-guide stop" not in faux_bin.appels():
        time.sleep(0.2)
    assert "g1-guide stop" in faux_bin.appels()          # ARRÊT sans ROS 2 : par la commande du guide
    nav.commande("simulation.arreter")
    nav.attendre("return document.querySelector('[data-role=etat-simu]').textContent.startsWith('Simulation arrêtée')",
                 delai=30, message="simulation arrêtée")

    # Scan simulé (Simuler › Avancé) : l'écran du scan s'ouvre (parcours complet : test_serveur_scan_navigateur.py)
    nav.commande("scan.simule")
    nav.ecran("scan")

    # Aucune erreur JavaScript pendant tout le parcours
    assert nav.js("return window.erreursAtelier") == []


def test_calculs_geometriques_du_js(sans_ros, serveur, navigateur):
    """js/geometrie.js exécuté dans le navigateur : passage dans un mur, identifiants, angles."""
    _, base = serveur
    navigateur.ouvrir(base + "/")
    r = navigateur.js_async("""
        const fin = arguments[arguments.length - 1];
        const mur = {id: 'm1', de: [0, 0], a: [10, 0], epaisseur: 0.15, hauteur: 2.5};
        import('/js/geometrie.js').then((G) => fin({
          milieu: G.couperMur(mur, [4, 0.2], 1.0, ['m1']),
          bout: G.couperMur(mur, [0.2, 0], 1.0, []),
          noms: [G.idDepuisNom('Salle B204 (labo)'), G.idDepuisNom('Yes'), G.idDepuisNom('Élève à l’accueil')],
          libre: G.idLibre('mur', ['mur_1', 'mur_2']),
          angles: [G.accrocherAngle(1.5, 15), G.accrocherAngle(3.13, 15), G.accrocherAngle(-3.13, 15)],
          refus: [G.verifierId('B204', []), G.verifierId('b204', ['b204']), G.verifierId('b204', [])],
          dedans: [G.dansPolygone([1, 1], [[0, 0], [2, 0], [2, 2], [0, 2]]), G.dansPolygone([3, 1], [[0, 0], [2, 0], [2, 2]])],
          nb: G.nb(12.5),
        })).catch((e) => fin({erreur: String(e)}));""")
    assert "erreur" not in r, r
    assert [(m["id"], m["de"], m["a"]) for m in r["milieu"]] == [("m1", [0, 0], [3.5, 0]), ("m1_1", [4.5, 0], [10, 0])]
    assert [(m["id"], m["de"], m["a"]) for m in r["bout"]] == [("m1", [0.7, 0], [10, 0])]
    assert r["noms"] == ["salle_b204_labo", "yes_1", "eleve_a_l_accueil"]
    assert r["libre"] == "mur_3"
    assert r["angles"] == [1.5708, 3.1416, 3.1416]
    assert "identifiant refusé" in r["refus"][0] and "déjà" in r["refus"][1] and r["refus"][2] is None
    assert r["dedans"] == [True, False] and r["nb"] == "12,5"
