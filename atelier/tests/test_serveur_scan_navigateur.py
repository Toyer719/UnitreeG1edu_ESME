"""L'écran de scan (vague 5, section 12.5 du plan) dans un vrai navigateur sans fenêtre (Firefox par geckodriver).

L'écran est monté dans la page par le contrat des écrans de la coque (ouvrir(racine, options), section 12.2),
avec une fausse coque (pleinEcran, message, confirmer notés dans window.essaiScan) : le test ne dépend pas de
l'état de la coque. Parcours : Simulation → « Scan » (plein écran, nuage en direct, trajet, compteurs, flèches)
→ « Fin » → progression → nuage final, carte 2D, résumé → « Utiliser cette carte » (nuage et carte extrudée
de l'étage) ; puis le vrai robot sans câble (confirmation dans la page, message clair) et les commandes du ruban.

Serveur : bin/g1-atelier, comme en vrai, sur une copie de demo, sans pont ROS 2, avec les fausses
commandes g1-* (g1-scan : test_serveur_scan_communs). Sauté si geckodriver ou Firefox manquent.
"""
import json
import shutil
import urllib.error
import urllib.request

import pytest

from .test_serveur_communs import faux_bin, journaux, lieux  # noqa: F401
from .test_serveur_demarrage import serveur  # noqa: F401
from .test_serveur_navigateur import navigateur, sans_ros  # noqa: F401
from .test_serveur_scan_communs import faux_scan  # noqa: F401

pytestmark = pytest.mark.skipif(shutil.which("geckodriver") is None or shutil.which("firefox") is None,
                                reason="geckodriver ou Firefox absent")

# Monte l'écran de scan sur la page, par-dessus la coque, avec une fausse coque (arguments : mode, commande)
MONTER = """
const fin = arguments[arguments.length - 1];
window.essaiScanParametres = {mode: arguments[0], commande: arguments[1]};
window.essaiScanMonte = null;
window.essaiScan = {pleinEcran: [], messages: [], confirmations: []};
// Tout se fait dans un <script type=module> de la page : l'importmap (three) et les modules (contexte.js) de la
// page ne valent pas pour import() lancé par WebDriver
const s = document.createElement('script');
s.type = 'module';
s.textContent = `
import { contexte } from '/js/contexte.js';
import { api } from '/js/api.js';
import * as S from '/js/ecrans/scan.js';
(async () => {
  contexte.lieu = 'demo';
  contexte.etage = 'rdc';
  contexte.infoLieu = await api.lire('/api/lieux/demo');
  if (window.ecranScan) window.ecranScan.fermer();
  const ancien = document.getElementById('essai-scan');
  if (ancien) ancien.remove();
  const zone = document.createElement('div');
  zone.id = 'essai-scan';
  zone.style.cssText = 'position:fixed;inset:0;z-index:9000;display:grid;grid-template-columns:1fr 320px';
  const vue = document.createElement('div');
  vue.style.position = 'relative';
  const panneau = document.createElement('div');
  panneau.style.overflow = 'auto';
  zone.appendChild(vue);
  zone.appendChild(panneau);
  document.body.appendChild(zone);
  const coque = {
    pleinEcran: (v) => window.essaiScan.pleinEcran.push(v),
    message: (texte, genre) => window.essaiScan.messages.push([genre, texte]),
    confirmer: (texte) => { window.essaiScan.confirmations.push(texte); return Promise.resolve(true); },
  };
  const p = window.essaiScanParametres;
  window.ecranScan = S.ouvrir(vue, {panneau: panneau, mode: p.mode, commande: p.commande, coque: coque, vue: '3d',
    carte3d: null});
  window.essaiScanMonte = 'monté';
})().catch((e) => { window.essaiScanMonte = 'erreur : ' + e; });
`;
document.head.appendChild(s);
const attendre = (n) => {
  if (window.essaiScanMonte || n > 150) fin(window.essaiScanMonte || 'délai dépassé');
  else setTimeout(() => attendre(n + 1), 100);
};
attendre(0);
"""


def _api(base, chemin, corps=None):
    donnees = None if corps is None else json.dumps(corps).encode()
    req = urllib.request.Request(base + chemin, data=donnees, method="GET" if corps is None else "POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def _statut(base, chemin):
    try:
        with urllib.request.urlopen(base + chemin, timeout=30) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def _visible(nav, role):
    return nav.js("const e = document.querySelector('#essai-scan [data-role=' + arguments[0] + ']'); "
                  "return !!e && !e.hidden && e.offsetParent !== null", role)


def _cliquer(nav, role):
    nav.js("document.querySelector('#essai-scan [data-role=' + arguments[0] + ']').click()", role)


def test_ecran_de_scan_dans_le_navigateur(sans_ros, scan_lent, serveur, navigateur, lieux, faux_scan):
    _, base = serveur
    nav = navigateur
    _api(base, "/api/lieux/demo/etages/rdc/monde/generer", {})        # monde Gazebo de l'étage (faux g1-monde)
    nav.ouvrir(base + "/?recharger=1")
    assert nav.js_async(MONTER, "simu", None) == "monté"

    # avant le scan : le gros bouton Scan, les réglages dans le panneau, pas de compteurs
    nav.attendre("return document.querySelector('#essai-scan [data-role=scan-ecran]').dataset.vue === 'choix'",
                 message="écran prêt")
    assert _visible(nav, "scan-lancer") and not _visible(nav, "scan-fin") and not _visible(nav, "scan-compteurs")
    reglages = nav.js("return document.querySelector('#essai-scan [data-role=scan-reglages]').textContent")
    assert "Exploration automatique" in reglages and "robot simulé" in reglages
    webgl = nav.js("return !!(window.scanNuage3d && window.scanNuage3d.etat().webgl)")

    # « Scan » : plein écran, nuage en direct, trajet, robot, compteurs, flèches
    _cliquer(nav, "scan-lancer")
    nav.attendre("return document.querySelector('#essai-scan [data-role=scan-ecran]').dataset.vue === 'direct'",
                 delai=20, message="scan en direct")
    assert any(a.startswith("g1-scan demarrer") and "--mode simu" in a for a in faux_scan.appels())
    assert nav.js("return window.essaiScan.pleinEcran") == [True]
    assert _visible(nav, "scan-fin") and _visible(nav, "scan-compteurs") and _visible(nav, "scan-teleop")
    if webgl:
        nav.attendre("return window.scanNuage3d.etat().points > 100 && window.scanNuage3d.etat().trajet > 1 "
                     "&& window.scanNuage3d.etat().robot", delai=20, message="nuage en direct")
        n1 = nav.js("return window.scanNuage3d.etat().points")
        nav.attendre("return window.scanNuage3d.etat().points > arguments[0]", n1, delai=15, message="nuage qui grandit")
    else:
        nav.attendre("const i = document.querySelector('#essai-scan [data-role=scan-image2d]'); "
                     "return !i.hidden && i.complete && i.naturalWidth > 0", delai=20, message="vue de dessus (sans WebGL)")
    nav.attendre("return document.querySelector('[data-compteur=points] .scan-compteur-valeur').textContent !== '—' && "
                 "document.querySelector('[data-compteur=distance] .scan-compteur-valeur').textContent !== '0,0 m'",
                 delai=15, message="compteurs")
    assert nav.js("return document.querySelector('[data-compteur=duree] .scan-compteur-valeur').textContent").count(":") == 1

    # « Fin » : progression, puis le résultat
    _cliquer(nav, "scan-fin")
    nav.attendre("return document.querySelector('#essai-scan [data-role=scan-ecran]').dataset.vue === 'traitement'",
                 delai=30, message="fabrication de la carte")
    assert _visible(nav, "scan-progression")
    nav.attendre("const b = document.querySelector('[data-role=scan-progression-barre]'); "
                 "return b && parseFloat(b.style.width) >= 10 && document.querySelector('.scan-etape.en-cours')",
                 delai=20, message="barre qui avance")
    etape = nav.js("return document.querySelector('.scan-etape.en-cours').dataset.etape")
    assert etape in ("arret", "carte_3d", "carte_2d", "nuage")
    nav.attendre("return document.querySelector('#essai-scan [data-role=scan-ecran]').dataset.vue === 'resultat'",
                 delai=40, message="résultat")
    assert nav.js("return window.essaiScan.pleinEcran")[-1] is False
    assert _visible(nav, "scan-utiliser") and not _visible(nav, "scan-progression") and not _visible(nav, "scan-teleop")
    ident = _api(base, "/api/scan/sessions?lieu=demo")[0]["id"]
    info = _api(base, f"/api/scan/nuage/info?lieu=demo&session={ident}")
    if webgl:
        nav.attendre("return window.scanNuage3d.etat().points === arguments[0]", info["points"], delai=15,
                     message="nuage final")
    nav.attendre("const i = document.querySelector('#essai-scan [data-role=scan-carte2d]'); "
                 "return i && i.complete && i.naturalWidth > 0", delai=15, message="carte 2D")
    nav.attendre("return document.querySelector('[data-role=scan-resume-texte]').textContent.includes('nuages assemblés')",
                 delai=15, message="résumé du traitement")
    # recette de la vague 5 (revue de l'interface) : « Points mesurés » pendant le scan, le résumé parle des
    # points gardés dans la carte 3D et du sol, et le compteur des nuages dit le même nombre que le résumé
    assert "Points mesurés" in nav.js("return document.querySelector('[data-compteur=points]').textContent")
    resume = nav.js("return document.querySelector('[data-role=scan-resume-texte]').textContent")
    assert "points gardés dans la carte 3D" in resume and ("Sol trouvé" in resume or "Sol peu vu" in resume), resume
    nuages = nav.js("return document.querySelector('[data-compteur=nuages] .scan-compteur-valeur').textContent")
    assert nuages != "—" and f"sur {nuages}" in resume, (nuages, resume)
    texte_panneau = nav.js("return document.querySelector('#essai-scan').textContent")
    for retire in ("Ouvrir dans l'éditeur du monde", "confiance", "Reconnaissance des murs"):
        assert retire not in texte_panneau, retire
    nav.attendre("return document.querySelectorAll('#essai-scan .scan-session[data-session]').length === 1",
                 message="scans précédents")

    # « Utiliser cette carte » : confirmation dans la page, puis la carte, le nuage et la carte extrudée de l'étage
    _cliquer(nav, "scan-utiliser")
    nav.attendre("return window.essaiScan.confirmations.length === 1", message="confirmation")
    nav.attendre("return Array.from(document.querySelectorAll('.message-succes')).some(m => "
                 "m.textContent.includes('Carte du scan utilisée'))", delai=30, message="carte utilisée")
    assert _statut(base, "/api/lieux/demo/etages/rdc/nuage") == 200
    assert _statut(base, "/api/lieux/demo/etages/rdc/monde/maillage") == 200
    assert _api(base, "/api/lieux/demo")["etages"][0]["source_carte"] == "scan"
    nav.attendre("return document.querySelector('#essai-scan [data-role=scan-resume]').textContent"
                 ".includes('Déjà utilisée')", delai=10, message="session marquée utilisée")

    # commandes du ruban : « Fin » sans scan en cours → un message clair, rien d'envoyé
    appels = len(faux_scan.appels())
    nav.js("window.ecranScan.commande('fin')")
    nav.attendre("return window.essaiScan.messages.some(m => m[1].includes('Aucun scan en cours'))",
                 message="Fin sans scan")
    assert len(faux_scan.appels()) == appels

    # le vrai robot sans câble : confirmation dans la page, puis « Robot non détecté »
    assert nav.js_async(MONTER, "reel", None) == "monté"
    nav.attendre("return document.querySelector('#essai-scan [data-role=scan-ecran]').dataset.vue === 'choix'",
                 message="écran du vrai robot")
    consignes = nav.js("return document.querySelector('#essai-scan [data-role=scan-reglages]').textContent")
    assert "Câble Ethernet" in consignes and "source ~/robot-g1/setup/robot.sh" in consignes
    assert "Exploration automatique" not in consignes
    _cliquer(nav, "scan-lancer")
    nav.attendre("return window.essaiScan.confirmations.length === 1 && "
                 "window.essaiScan.confirmations[0].includes('télécommande')", message="confirmation du câble")
    nav.attendre("return Array.from(document.querySelectorAll('.message-erreur')).some(m => "
                 "m.textContent.includes('Robot non détecté'))", delai=15, message="robot non détecté")
    nav.js("window.ecranScan.fermer()")
    assert nav.js("return window.erreursAtelier") == []
    print(f"WebGL : {webgl} ; étape vue en cours : {etape}")


RECT = """const e = document.querySelector(arguments[0]);
if (!e) return null;
const r = e.getBoundingClientRect();
return {gauche: r.left, haut: r.top, droite: r.right, bas: r.bottom, largeur: r.width, hauteur: r.height};"""

# l'élément au centre d'un repère est lui-même ou un de ses enfants (il n'est pas recouvert)
DEGAGE = """const e = document.querySelector(arguments[0]);
if (!e || e.hidden || e.offsetParent === null) return false;
const r = e.getBoundingClientRect();
const x = r.left + r.width / 2, y = r.top + r.height / 2;
if (x < 0 || y < 0 || x > window.innerWidth || y > window.innerHeight) return false;
const vu = document.elementFromPoint(x, y);
return !!vu && (vu === e || e.contains(vu));"""


def _rect(nav, selecteur):
    return nav.js(RECT, selecteur)


def _a_peu_pres(a, b, tolerance=2.0):
    return all(abs(a[k] - b[k]) <= tolerance for k in ("gauche", "haut", "droite", "bas"))


def _sans_chevauchement(a, b):
    return a["droite"] <= b["gauche"] or b["droite"] <= a["gauche"] or a["bas"] <= b["haut"] or b["bas"] <= a["haut"]


def test_ecran_de_scan_dans_la_coque(sans_ros, scan_lent, serveur, navigateur, lieux, faux_scan):
    """L'écran de scan dans la vraie coque (Réel en répétition, ancien hash #scan), à 1366 × 768 : la vue sombre
    remplit la vue centrale ; pendant le scan, elle remplit tout sous la barre d'outils (ARRÊT et « Fin »
    visibles et cliquables) ; le résultat : vue centrale de nouveau, message et boutons sans chevauchement.
    Ce test a trouvé deux défauts que le montage d'essai ne voyait pas : la racine de l'écran ramenée en
    position relative (vue effondrée), et le plein écran de la coque qui laissait le centre à 0 pixel."""
    _, base = serveur
    nav = navigateur
    _api(base, "/api/lieux/demo/etages/rdc/monde/generer", {})
    nav.taille(1366, 768)
    nav.ouvrir(base + "/?recharger=1")
    nav.js("const m = {'atelier.lieu': 'demo', 'atelier.etage': 'rdc', 'atelier.mode': 'reel', 'atelier.repetition': '1',"
           " 'atelier.scan.mode': 'robot', 'atelier.scan.repetition': '1', 'atelier.mode-simulation': 'repetition'};"
           "Object.keys(m).forEach((k) => localStorage.setItem(k, m[k]));")
    nav.ouvrir(base + "/?recharger=1#scan")
    nav.ecran("scan", delai=60)
    nav.attendre("const e = document.querySelector('[data-role=scan-ecran]'); return !!e && e.dataset.vue === 'choix'",
                 delai=30, message="écran de scan dans la coque")
    vue = _rect(nav, "[data-role=vue]")
    ecran = _rect(nav, "[data-role=scan-ecran]")
    assert vue and vue["hauteur"] > 300 and _a_peu_pres(ecran, vue), (vue, ecran)
    assert nav.js(DEGAGE, "[data-role=scan-lancer]"), "le bouton Scan est caché ou recouvert"
    assert nav.js("return document.querySelector('[data-role=panneau]').textContent").count("Avant le scan") == 1

    # « Scan » (répétition : pas de confirmation) : plein écran sous la barre d'outils
    nav.js("document.querySelector('[data-role=scan-lancer]').click()")
    nav.attendre("return document.querySelector('[data-role=scan-ecran]').dataset.vue === 'direct'", delai=20,
                 message="scan en direct")
    assert any(a.startswith("g1-scan demarrer") and "--repetition" in a for a in faux_scan.appels())
    barre = _rect(nav, "[data-role=barre-outils]")
    hauteur = nav.js("return window.innerHeight")
    nav.attendre("const r = document.querySelector('[data-role=scan-ecran]').getBoundingClientRect(); "
                 "return r.width >= window.innerWidth - 2 && r.height >= 0.8 * window.innerHeight", delai=10,
                 message="vue du scan en plein écran")
    plein = _rect(nav, "[data-role=scan-ecran]")
    assert abs(plein["haut"] - barre["bas"]) <= 2 and plein["bas"] <= hauteur + 1, (barre, plein)
    for repere in ("[data-role=arret]", "[data-role=scan-fin]"):
        assert nav.js(DEGAGE, repere), f"{repere} caché ou recouvert pendant le scan"
    compteur = _rect(nav, "[data-compteur=points]")             # sans clic (pointer-events: none) : visible, dedans
    assert compteur["hauteur"] > 20 and plein["haut"] <= compteur["haut"] and compteur["bas"] <= plein["bas"], compteur

    # « Fin » : la fabrication de la carte, puis le résultat dans la vue centrale
    nav.js("document.querySelector('[data-role=scan-fin]').click()")
    nav.attendre("return document.querySelector('[data-role=scan-ecran]').dataset.vue === 'resultat'", delai=60,
                 message="résultat")
    nav.attendre("const v = document.querySelector('[data-role=vue]').getBoundingClientRect(); "
                 "const e = document.querySelector('[data-role=scan-ecran]').getBoundingClientRect(); "
                 "return Math.abs(v.top - e.top) <= 2 && Math.abs(v.height - e.height) <= 2", delai=10,
                 message="fin du plein écran")
    nav.attendre("return document.querySelector('[data-role=scan-message]').textContent.includes('Scan terminé')",
                 delai=10, message="message du résultat")
    utiliser, nouveau = _rect(nav, "[data-role=scan-utiliser]"), _rect(nav, "[data-role=scan-nouveau]")
    message = _rect(nav, "[data-role=scan-message]")
    assert abs(utiliser["haut"] - nouveau["haut"]) <= 2, (utiliser, nouveau)       # sur la même ligne
    assert _sans_chevauchement(message, utiliser) and _sans_chevauchement(message, nouveau), (message, utiliser)
    assert nav.js(DEGAGE, "[data-role=scan-utiliser]")
    assert nav.js("return window.erreursAtelier") == []


@pytest.fixture
def scan_lent(monkeypatch):
    """Avant le serveur : traitement assez lent pour voir la progression, et pas de câble du robot."""
    monkeypatch.setenv("FAUX_SCAN_ETAPE_S", "1.5")
    monkeypatch.setenv("ATELIER_INTERFACE_ROBOT", "absente0")


def test_fleches_repetees_puis_arret_dans_le_navigateur(sans_ros, serveur, navigateur):
    """js/teleop.js dans le navigateur, avec un faux fetch : la consigne repart toutes les 0,2 s tant
    que la touche est appuyée, les touches se combinent, et {0, 0, 0} part dès qu'on lâche."""
    _, base = serveur
    navigateur.ouvrir(base + "/")
    r = navigateur.js_async("""
        const fin = arguments[arguments.length - 1];
        const envois = [];
        window.fetch = (url, options) => {
          envois.push({t: performance.now(), url: url, corps: JSON.parse(options.body)});
          const c = JSON.parse(options.body);
          return Promise.resolve(new Response(JSON.stringify({envoye: c, ecoute: 1}), {status: 200}));
        };
        import('/js/teleop.js').then((T) => {
          const zone = document.createElement('div');
          document.body.appendChild(zone);
          const t = new T.Teleop(zone);
          t.activer();
          const touche = (genre, cle) => window.dispatchEvent(new KeyboardEvent(genre, {key: cle}));
          touche('keydown', 'ArrowUp');
          setTimeout(() => touche('keydown', 'q'), 300);
          setTimeout(() => { touche('keyup', 'ArrowUp'); touche('keyup', 'q'); }, 1000);
          setTimeout(() => {
            const n = envois.length;
            setTimeout(() => {
              t.detruire();
              fin({envois: envois, apres: envois.length - n, periode: T.PERIODE_TELEOP, vitesses: T.VITESSES,
                   texte: T.texteConsigne({vx: 0.4, vy: 0, wz: -0.6})});
            }, 700);
          }, 1100);
        }).catch((e) => fin({erreur: String(e)}));""")
    assert "erreur" not in r, r
    envois = r["envois"]
    assert all(e["url"] == "/api/simulation/teleop" for e in envois)
    corps = [(e["corps"]["vx"], e["corps"]["vy"], e["corps"]["wz"]) for e in envois]
    avant = [c for c, e in zip(corps, envois) if e["t"] - envois[0]["t"] < 280]
    assert avant and all(c == (0.4, 0, 0) for c in avant), corps
    assert (0.4, 0.2, 0) in corps                                   # flèche du haut + Q : avance et pas à gauche
    assert corps[-1] == (0, 0, 0) and r["apres"] == 0               # arrêt envoyé, puis plus rien
    assert 6 <= len([c for c in corps if c != (0, 0, 0)]) <= 8      # environ 1 s à 0,2 s d'intervalle
    ecarts = [b["t"] - a["t"] for a, b in zip(envois, envois[1:-1]) if a["corps"] == b["corps"]]
    assert ecarts and max(ecarts) < 450, ecarts                     # toujours sous les 0,5 s de l'homme mort
    assert r["periode"] == 200 and r["vitesses"] == {"vx": 0.4, "vy": 0.2, "wz": 0.6}
    assert r["texte"] == "avance à 0,4 m/s, tourne à droite à 0,6 rad/s"
