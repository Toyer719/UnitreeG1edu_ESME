"""Parcours principal de l'interface dans un vrai navigateur, sans fenêtre (critère 9 du plan) :
créer un lieu → dessiner (mur, objet, piéton, passage, annuler, refaire) → enregistrer →
fabriquer la carte → placer une salle → la relier → une zone → lancer la simulation → Y aller
→ Arrêt → arrêter la simulation → scan avec le faux service.

Firefox est piloté par geckodriver, en WebDriver simple (requêtes HTTP), avec -headless.
Pas de Playwright. Le test est sauté si geckodriver ou Firefox manquent, ou si Firefox ne
démarre pas. Les gestes (cliquer-glisser sur le plan) sont des PointerEvent envoyés par script.
Serveur : bin/g1-atelier, comme en vrai, sur une copie de demo, avec les fausses commandes g1-*.
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

CLIC_BOUTON = """
const [texte, dans] = arguments;
if (document.querySelector('.ecran.chargement')) return false;     // écran pas encore prêt
const b = Array.from(document.querySelectorAll((dans || '') + ' button')).find(
  (x) => x.textContent.trim().startsWith(texte) && !x.disabled);
if (!b) return false;
b.click();
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

    def demarrer(self):
        options = {"args": ["-headless", "--width=1400", "--height=900"],
                   "prefs": {"app.update.enabled": False, "toolkit.telemetry.enabled": False,
                             "datareporting.policy.dataSubmissionEnabled": False}}
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

    def bouton(self, texte, dans=""):
        assert self.attendre(CLIC_BOUTON, texte, dans, message=f"bouton « {texte} »")

    def geste(self, ecran, points, relacher=True):
        self.attendre("return !document.querySelector('.ecran.chargement')", message="fin du chargement")
        return self.js(GESTE, f".ecran-{ecran}", points, relacher)

    def clic(self, ecran, p):
        self.geste(ecran, [p, p])

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


@pytest.fixture
def navigateur(tmp_path):
    port = _port_libre()
    gecko = subprocess.Popen([GECKODRIVER, "--port", str(port)], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
    nav = Navigateur(port)
    try:
        fin = time.monotonic() + 20
        while True:
            try:
                urllib.request.urlopen(nav.base + "/status", timeout=2)
                break
            except (urllib.error.URLError, ConnectionError):
                if time.monotonic() > fin or gecko.poll() is not None:
                    pytest.skip("geckodriver ne démarre pas")
                time.sleep(0.2)
        try:
            nav.demarrer()
        except Exception as e:      # noqa: BLE001
            pytest.skip(f"Firefox sans fenêtre ne démarre pas : {e}")
        yield nav
    finally:
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
def sans_ros(monkeypatch):
    """Serveur sans pont ROS 2 : « Y aller » répond alors qu'il manque ROS 2 (pas de Nav2 à attendre)."""
    monkeypatch.setenv("ATELIER_ROS", "0")


def _api(base, chemin):
    with urllib.request.urlopen(base + chemin, timeout=20) as r:
        return json.loads(r.read())


def test_parcours_principal_dans_le_navigateur(sans_ros, serveur, navigateur, lieux, faux_bin):
    _, base = serveur
    nav = navigateur
    L = "/api/lieux/essai_nav"

    # Lieux : la liste, puis la création d'un lieu
    nav.ouvrir(base + "/#lieux")
    nav.attendre("return document.querySelectorAll('.onglet').length === 8", message="onglets construits")
    nav.attendre("return document.querySelector('.liste-lieux').textContent.includes('Lycée démo')")
    nav.js("""const i = document.querySelector('.ecran-lieux form input[type=text]');
              i.value = 'Essai nav'; i.dispatchEvent(new Event('input')); i.dispatchEvent(new Event('change'));""")
    assert nav.js("return document.querySelectorAll('.ecran-lieux form input[type=text]')[1].value") == "essai_nav"
    nav.bouton("Créer le lieu")
    # l'Atelier passe seul à l'onglet Monde du nouveau lieu, avec ses 4 murs
    nav.attendre("return document.querySelectorAll('.ecran-monde path.mur').length === 4", message="monde neuf")
    assert nav.js("return document.getElementById('choix-lieu').value") == "essai_nav"
    assert len(_api(base, "/api/lieux")) == 2

    # Monde : un mur cliquer-glisser, un objet, un piéton, annuler et refaire, un passage
    nav.bouton("Mur", ".groupe-outils")
    nav.geste("monde", [[0.35, 0.5], [0.45, 0.5], [0.6, 0.5]])
    nav.attendre("return document.querySelectorAll('.ecran-monde path.mur').length === 5", message="mur tracé")
    assert "non enregistrées" in nav.js("return document.querySelector('[data-role=etat]').textContent")
    nav.bouton("Objet", ".groupe-outils")
    nav.clic("monde", [0.5, 0.35])
    nav.attendre("return document.querySelectorAll('.ecran-monde path.objet').length === 1", message="objet posé")
    # outil Choisir : glisser l'objet pour le déplacer, puis le tourner de 90° dans le panneau
    nav.bouton("Choisir", ".groupe-outils")
    position = "const r = document.querySelector('.ecran-monde path.objet').getBoundingClientRect(); return r.left;"
    avant = nav.js(position)
    nav.geste("monde", [[0.5, 0.35], [0.52, 0.35], [0.55, 0.35]])
    assert nav.js(position) > avant + 20, "l'objet n'a pas suivi le glissé"
    nav.js("""const l = Array.from(document.querySelectorAll('.ecran-monde .panneau label'))
                .find((x) => x.textContent.startsWith('Rotation'));
              const i = l.querySelector('input'); i.value = '90'; i.dispatchEvent(new Event('change'));""")
    # départ du robot : clic puis glissé vers le haut de l'écran (le nord)
    nav.bouton("Départ du robot", ".groupe-outils")
    nav.geste("monde", [[0.2, 0.8], [0.2, 0.75], [0.2, 0.7]])
    nav.bouton("Piéton", ".groupe-outils")
    nav.clic("monde", [0.3, 0.65])
    nav.clic("monde", [0.6, 0.65])
    nav.bouton("Terminer le trajet")
    nav.attendre("return document.querySelectorAll('.ecran-monde path.trajet-pieton').length >= 1", message="piéton")
    nav.bouton("Annuler")
    nav.attendre("return document.querySelectorAll('.ecran-monde path.trajet-pieton').length === 0", message="annuler")
    nav.bouton("Refaire")
    nav.attendre("return document.querySelectorAll('.ecran-monde path.trajet-pieton').length >= 1", message="refaire")
    nav.bouton("Passage", ".groupe-outils")
    nav.js(GESTE, ".ecran-monde", [[0.5, 0.5]], False)       # survol puis clic sur le mur tracé
    nav.clic("monde", [0.5, 0.5])
    nav.attendre("return document.querySelectorAll('.ecran-monde path.mur').length === 6", message="passage coupé")
    nav.bouton("Enregistrer le monde")
    nav.attendre("return document.querySelector('[data-role=etat]').textContent.includes('Tout est enregistré')")
    monde = _api(base, L + "/etages/rdc/monde")
    assert (len(monde["murs"]), len(monde["objets"]), len(monde["pietons"])) == (6, 1, 1)
    assert monde["objets"][0]["modele"] == "table" and abs(monde["objets"][0]["cap"] - 1.5708) < 1e-3
    assert abs(monde["depart_robot"]["theta"] - 1.5708) < 0.01 and monde["depart_robot"]["x"] != 1.0
    vue3d = nav.js("return document.querySelector('.ecran-monde .vue3d canvas') ? 'canvas' : "
                   "document.querySelector('.ecran-monde .vue3d').textContent")

    # Carte : fabriquer, puis l'image de la carte s'affiche
    nav.bouton("Carte", ".onglets")
    nav.bouton("Fabriquer la carte")
    nav.attendre("const i = document.querySelector('.ecran-carte img.plan-image-carte'); "
                 "return i && i.complete && i.naturalWidth > 0", delai=30, message="image de la carte")
    assert "g1-monde generer" in faux_bin.appels()[-1]

    # Salles : clic pour placer, glisser pour orienter, nom dans le panneau, enregistrer
    nav.bouton("Salles", ".onglets")
    nav.attendre("return document.querySelector('.ecran-salles .leaflet-marker-icon.salle')", message="salle accueil")
    nav.bouton("Ajouter une salle", ".groupe-outils")
    nav.geste("salles", [[0.7, 0.3], [0.7, 0.2], [0.7, 0.1]])
    nav.attendre("return document.querySelector('.ecran-salles [data-champ=nom] input')", message="panneau salle")
    nav.js("""const i = document.querySelector('.ecran-salles [data-champ=nom] input');
              i.value = 'Labo de physique'; i.dispatchEvent(new Event('change'));""")
    nav.bouton("Enregistrer les salles")
    nav.attendre("return document.querySelector('.ecran-salles [data-role=etat]').textContent.includes('Tout est')")
    salles = _api(base, L + "/salles")
    labo = next(s for s in salles if s["id"] == "labo_de_physique")
    assert labo["nom"] == "Labo de physique" and abs(labo["pose"]["theta"] - 1.5708) < 0.01   # glissé vers le haut
    assert "labo_de_physique" in _api(base, L + "/itineraires")["noeuds"]

    # Itinéraires : relier l'accueil à la salle
    nav.bouton("Itinéraires", ".onglets")
    nav.attendre("return document.querySelectorAll('.ecran-itineraires .noeud').length === 2", message="nœuds")
    nav.bouton("Relier deux nœuds", ".groupe-outils")
    # un nœud, puis l'autre (l'écran redessine les nœuds après chaque clic)
    nav.js("document.querySelectorAll('.ecran-itineraires .noeud')[0].click()")
    nav.js("document.querySelectorAll('.ecran-itineraires .noeud')[1].click()")
    nav.attendre("return document.querySelectorAll('.ecran-itineraires path.couloir').length === 1", message="couloir")
    nav.bouton("Enregistrer les itinéraires")
    nav.attendre("return document.querySelector('.ecran-itineraires [data-role=etat]').textContent.includes('Tout est')")
    assert len(_api(base, L + "/itineraires")["couloirs"]) == 1

    # Zones : une zone interdite de trois coins
    nav.bouton("Zones", ".onglets")
    nav.bouton("Zone interdite", ".groupe-outils")
    for p in ([0.2, 0.2], [0.3, 0.2], [0.3, 0.3]):
        nav.clic("zones", p)
    nav.bouton("Terminer la zone")
    nav.bouton("Enregistrer les zones")
    nav.attendre("return document.querySelector('.ecran-zones [data-role=etat]').textContent.includes('Tout est')")
    assert len(_api(base, L + "/zones")["interdites"]) == 1

    # Simulation : lancer, Y aller, Arrêt, arrêter
    nav.bouton("Simulation", ".onglets")
    nav.bouton("Lancer la simulation")
    nav.attendre("return document.querySelector('[data-role=etat-simu]').textContent.includes('Simulation en cours')",
                 delai=20, message="simulation en cours")
    assert _api(base, "/api/simulation/etat")["simulation"]["en_cours"]
    nav.attendre("return Array.from(document.querySelectorAll('.liste-salles button')).length === 2")
    nav.js("document.querySelectorAll('.liste-salles button')[1].click()")
    nav.attendre("return Array.from(document.querySelectorAll('.message-erreur')).some(m => "
                 "m.textContent.includes('Pas de liaison avec ROS 2'))", message="Y aller sans ROS 2")
    nav.js("document.querySelectorAll('.message-erreur').forEach((m) => m.remove())")
    nav.js("document.querySelector('.bouton-arret').click()")
    nav.attendre("return Array.from(document.querySelectorAll('.message')).some(m => m.textContent.includes('Arrêt'))")
    nav.bouton("Arrêter la simulation")
    nav.attendre("return document.querySelector('[data-role=etat-simu]').textContent.startsWith('Simulation arrêtée')",
                 delai=20, message="simulation arrêtée")

    # Scan : le faux service est coché par défaut
    nav.bouton("Scan", ".onglets")
    assert nav.js("return document.querySelector('.ecran-scan input[type=checkbox]').checked")
    nav.bouton("Démarrer le scan")
    nav.attendre("return document.querySelector('.ecran-scan [data-role=etat]').textContent.includes('Scan démarré')")
    assert "g1-slam scan-debut --faux" in faux_bin.appels()
    assert "g1-guide stop" in faux_bin.appels()          # Arrêt sans ROS 2 : par la commande du guide

    # Aucune erreur JavaScript pendant tout le parcours
    assert nav.js("return window.erreursAtelier") == []
    erreurs = nav.js("return Array.from(document.querySelectorAll('.message-erreur')).map(e => e.textContent)")
    assert erreurs == [], erreurs
    print(f"vue 3D : {vue3d}")


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
