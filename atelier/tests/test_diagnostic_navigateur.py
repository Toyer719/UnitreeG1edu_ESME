"""« Vérifier le robot » dans Firefox sans fenêtre (vague 6, sections 13.2 et 13.7 du plan) : agent Diagnostic.

Un vrai serveur (g1-atelier, sans ROS), la page de l'Atelier, et les réponses du diagnostic soit du serveur (faux
contexte des vérifications système), soit d'un faux fetch posé dans la page (résultats réalistes faits par
atelier.diagnostic.verdicts, pour essayer les états et l'action sans robot ni ROS) :

- l'accueil Robot réel avec « Répétition » : le bouton et le résumé ; la fenêtre dans la page, chaque vérification
  avec son état, son conseil et son bouton ; l'action demande confirmation DANS la page (Annuler : rien ne part ;
  Démarrer : POST {confirme: true, mode}) ; le résultat redessiné ; Échap et ✗ ferment ; aucune boîte native ;
- la barre d'outils (Réel et répétition, rien en simulation) et la commande du ruban robot.verifier ; la fenêtre ne
  couvre jamais l'ARRÊT, tient dans la page à 1366 × 768 et 1024 × 768, la page ne défile pas ;
- le vrai serveur : le diagnostic du faux contexte (Réel) s'affiche ; window.erreursAtelier reste vide.
"""

import pytest

from . import test_coque_communs as C
from .test_diagnostic_communs import ecrire_faux, faux_systeme
from .test_serveur_communs import faux_bin, journaux, lieux  # noqa: F401
from .test_serveur_demarrage import serveur  # noqa: F401
from .test_serveur_navigateur import GECKODRIVER, navigateur  # noqa: F401

pytestmark = pytest.mark.skipif(GECKODRIVER is None, reason="geckodriver absent")

FAUX_FETCH = r"""
const [reponses] = arguments;
window.essaiDiagnostic = { appels: [], reponses: reponses, delai: 120 };
const fetchAvant = window.fetch.bind(window);
function repondre(statut, corps) {
  return new Promise((ok) => setTimeout(() => ok(new Response(JSON.stringify(corps),
    { status: statut, headers: { 'Content-Type': 'application/json' } })), window.essaiDiagnostic.delai));
}
window.fetch = function (ressource, init) {
  const url = typeof ressource === 'string' ? ressource : String(ressource.url || ressource);
  if (url.indexOf('/api/robot/diagnostic') !== 0) return fetchAvant(ressource, init);
  const methode = ((init && init.method) || 'GET').toUpperCase();
  let corps = null;
  try { corps = init && init.body ? JSON.parse(init.body) : null; } catch (e) { corps = init.body; }
  window.essaiDiagnostic.appels.push({ methode: methode, url: url, corps: corps });
  const r = window.essaiDiagnostic.reponses;
  if (methode === 'POST') return repondre(200, r.action);
  if (url.indexOf('/dernier') >= 0) return repondre(404, { detail: 'Aucun diagnostic pour le moment.' });
  return repondre(200, r.diagnostic);
};
return true;
"""

APPELS = "return window.essaiDiagnostic ? window.essaiDiagnostic.appels : []"
FENETRE = "return !!document.querySelector('[data-role=diagnostic][data-occupe=non]')"
ETAT_LIGNE = ("const v = document.querySelector('[data-role=diagnostic] [data-verification=' + arguments[0] + ']');"
              "return v ? v.getAttribute('data-etat') : null")
MESURE_FENETRE = """
const f = document.querySelector('[data-role=diagnostic]');
const a = document.querySelector('[data-role=arret]');
const r = f.getBoundingClientRect();
let couvre = false;
if (a && a.offsetParent !== null) {
  const ra = a.getBoundingClientRect();
  const e = document.elementFromPoint(ra.left + ra.width / 2, ra.top + ra.height / 2);
  couvre = !(e === a || a.contains(e));
  couvre = couvre || !(r.bottom <= ra.top || r.top >= ra.bottom || r.right <= ra.left || r.left >= ra.right);
}
return {dedans: r.left >= 0 && r.top >= 0 && r.right <= window.innerWidth + 1 && r.bottom <= window.innerHeight + 1,
        couvre_arret: couvre, defile: document.documentElement.scrollHeight > window.innerHeight + 1
          || document.documentElement.scrollWidth > window.innerWidth + 1,
        largeur: r.width, hauteur: r.height};
"""


def resultats(etat_services):
    """Un diagnostic de répétition réaliste (verdicts du vrai code), services arrêtés ou actifs."""
    from atelier.diagnostic import verdicts as V
    from atelier.lieu import diagnostic as G
    from .test_diagnostic import faits_robot
    from .test_diagnostic_communs import GRAPHE_FAUX_G1
    statut = 1 if etat_services == "arretes" else 0
    faits = faits_robot(sujets={"vus": dict(GRAPHE_FAUX_G1)}, services={"code": 0, "services": [
        {"name": "lidar_driver", "status": statut, "protect": False},
        {"name": "unitree_slam", "status": statut, "protect": False}]})
    verifications, ignorees = V.juger(faits, "repetition")
    return G.diagnostic(verifications, "repetition", "2026-11-12T14:03:05+01:00", 1.8, ignorees=ignorees,
                        source="atelier")


def poser_faux_fetch(nav):
    action = {"action": "demarrer-services", "ok": True, "services": {"lidar_driver": 0, "unitree_slam": 0},
              "message": "Les services de cartographie ont démarré en 2 s : le scan et le repérage peuvent marcher.",
              "diagnostic": resultats("actifs")}
    nav.js(FAUX_FETCH, {"diagnostic": resultats("arretes"), "action": action})


@pytest.fixture
def sans_ros_lo(monkeypatch):
    monkeypatch.setenv("ATELIER_ROS", "0")
    monkeypatch.setenv("ATELIER_INTERFACE_ROBOT", "lo")
    monkeypatch.setenv("ATELIER_PC1", "127.0.0.1")
    monkeypatch.setenv("ATELIER_JETSON", "127.0.0.1")


def test_accueil_verifier_puis_demarrer_les_services(sans_ros_lo, serveur, navigateur, lieux):  # noqa: F811
    _, base = serveur
    nav = navigateur
    nav.taille(1366, 768)
    C.charger(nav, base + "/", C.ACCUEIL, "accueil")
    nav.js("localStorage.clear(); localStorage.setItem('atelier.lieu', 'demo');"
           "localStorage.setItem('atelier.mode', 'reel');"
           "localStorage.setItem('atelier.repetition', '1');")
    C.charger(nav, base + "/", "return !!document.querySelector('[data-role=zone-diagnostic-accueil] "
                               "[data-role=verifier-robot]')", "bouton « Vérifier le robot » de l'accueil")
    resume = nav.js("return document.querySelector('[data-role=diagnostic-resume]').textContent")
    assert "contrôle complet" in resume.lower(), resume
    poser_faux_fetch(nav)
    nav.clic("[data-role=zone-diagnostic-accueil] [data-role=verifier-robot]")
    nav.attendre(FENETRE, message="fenêtre du diagnostic")
    assert nav.js(ETAT_LIGNE, "services") == "probleme" and nav.js(ETAT_LIGNE, "mode") == "ok"
    assert nav.js("return document.querySelector('[data-role=diagnostic]').getAttribute('data-etat')") == "probleme"
    assert nav.js(APPELS)[-1]["url"] == "/api/robot/diagnostic?mode=repetition"
    textes = nav.js("return document.querySelector('[data-role=diagnostic]').textContent")
    assert "Démarrer les services de cartographie" in textes and "Pas vérifiés ici" in textes
    assert "/api/" not in textes and "/lf/" not in textes                  # aucun sujet ROS à l'écran
    # l'action : confirmation dans la page ; Annuler n'envoie rien
    nav.clic("[data-role=diagnostic] [data-action=demarrer-services]")
    nav.attendre("return !!document.querySelector('[data-role=confirmation]')", message="confirmation dans la page")
    confirmation = nav.js("return document.querySelector('[data-role=confirmation]').textContent")
    assert "le LiDAR et la cartographie d'Unitree" in confirmation and "ne bouge pas" in confirmation
    assert "lidar_driver" not in confirmation              # corrections de la vague 6 (défaut 16)
    nav.clic("[data-role=confirmation] [data-role=renoncer]")
    assert not [a for a in nav.js(APPELS) if a["methode"] == "POST"]
    nav.clic("[data-role=diagnostic] [data-action=demarrer-services]")
    nav.attendre("return !!document.querySelector('[data-role=confirmation]')", message="confirmation")
    nav.clic("[data-role=confirmation] [data-role=confirmer]")
    nav.attendre("const v = document.querySelector('[data-role=diagnostic] [data-verification=services]');"
                 "return v && v.getAttribute('data-etat') === 'ok'", message="services démarrés", delai=20)
    posts = [a for a in nav.js(APPELS) if a["methode"] == "POST"]
    assert posts == [{"methode": "POST", "url": "/api/robot/diagnostic/demarrer-services",
                      "corps": {"confirme": True, "mode": "repetition"}}]
    retour = nav.js("const r = document.querySelector('[data-role=diagnostic-retour]');"
                    "return [r.hidden, r.getAttribute('data-genre'), r.textContent]")
    assert retour[0] is False and retour[1] == "succes" and "ont démarré" in retour[2]
    resume = nav.js("return document.querySelector('[data-role=diagnostic-resume]').getAttribute('data-etat')")
    assert resume in ("attention", "ok")                  # le résumé de l'accueil suit le dernier diagnostic
    # Échap ferme la fenêtre (rien ne tourne : pas d'ARRÊT)
    nav.js("document.body.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}))")
    nav.attendre("return !document.querySelector('[data-role=diagnostic]')", message="fenêtre fermée par Échap")
    # le résumé rouvre le dernier diagnostic sans en refaire un
    n = len(nav.js(APPELS))
    nav.clic("[data-role=diagnostic-resume]")
    nav.attendre(FENETRE, message="fenêtre rouverte")
    assert len(nav.js(APPELS)) == n
    nav.clic("[data-role=fermer-diagnostic]")
    nav.attendre("return !document.querySelector('[data-role=diagnostic]')", message="fenêtre fermée par ✗")
    assert C.fenetres_natives(nav) == [] and nav.js("return window.erreursAtelier") == []


def test_barre_d_outils_ruban_et_mise_en_page(sans_ros_lo, serveur, navigateur, lieux):  # noqa: F811
    _, base = serveur
    nav = navigateur
    for largeur, hauteur in ((1366, 768), (1024, 768)):
        nav.taille(largeur, hauteur)
        C.ouvrir_espace(nav, base, "repetition")
        bouton = "[data-role=zone-diagnostic] [data-role=verifier-robot]"
        assert nav.js(f"const b = document.querySelector('{bouton}'); return !!b && b.offsetParent !== null")
        poser_faux_fetch(nav)
        nav.clic(bouton)
        nav.attendre(FENETRE, message="fenêtre par la barre d'outils")
        mesure = nav.js(MESURE_FENETRE)
        assert mesure["dedans"] and not mesure["couvre_arret"] and not mesure["defile"], (largeur, mesure)
        nav.clic("[data-role=fermer-diagnostic]")
        nav.attendre("return !document.querySelector('[data-role=diagnostic]')", message="fermée")
        # la commande du ruban (Naviguer › Vérifier le robot)
        nav.commande("robot.verifier")
        nav.attendre(FENETRE, message="fenêtre par le ruban")
        assert nav.js(ETAT_LIGNE, "services") == "probleme"
        # retour à l'accueil : la fenêtre se ferme avec l'espace de travail
        nav.clic("[data-role=accueil-retour]")
        nav.attendre("return !!document.querySelector('[data-role=accueil]') && "
                     "!document.querySelector('[data-role=diagnostic]')", message="fenêtre fermée avec l'espace")
    # en simulation : pas de bouton (pas de robot à vérifier)
    C.ouvrir_espace(nav, base, "simu")
    assert nav.js("const z = document.querySelector('[data-role=zone-diagnostic]');"
                  "return !z || z.hidden || !z.querySelector('[data-role=verifier-robot]')")
    assert C.fenetres_natives(nav) == [] and nav.js("return window.erreursAtelier") == []


@pytest.fixture
def faux_reel(tmp_path, monkeypatch):
    """Le faux contexte des vérifications système (connexion qui ne se rallume pas seule), avant le serveur."""
    chemin = ecrire_faux(tmp_path / "faux.json", faux_systeme(autoconnect="no"))
    monkeypatch.setenv("ATELIER_DIAGNOSTIC_FAUX", str(chemin))
    return chemin


def test_le_vrai_serveur_en_reel(sans_ros_lo, faux_reel, serveur, navigateur, lieux):  # noqa: F811
    """Sans faux fetch : la fenêtre montre ce que le serveur a vérifié (faux contexte, sans ROS)."""
    _, base = serveur
    nav = navigateur
    nav.taille(1366, 768)
    C.ouvrir_espace(nav, base, "reel")
    nav.clic("[data-role=zone-diagnostic] [data-role=verifier-robot]")
    nav.attendre(FENETRE + " && !!document.querySelector('[data-role=diagnostic] [data-verification]')",
                 message="fenêtre du diagnostic (vrai serveur)", delai=20)
    assert nav.js(ETAT_LIGNE, "cable") == "ok" and nav.js(ETAT_LIGNE, "ros") == "probleme"     # sans ROS
    assert nav.js(ETAT_LIGNE, "profil") == "attention"
    assert nav.js("return !!document.querySelector('[data-role=diagnostic] [data-action=cable-automatique]')")
    assert nav.js("return document.querySelector('[data-role=diagnostic-mode]').textContent") == "Vrai robot"
    duree = nav.js("return document.querySelector('.diagnostic-duree').textContent")
    assert "simulées" in duree, duree
    assert nav.js("return window.erreursAtelier") == [] and C.fenetres_natives(nav) == []


def test_fonctions_pures_du_module(sans_ros_lo, serveur, navigateur):  # noqa: F811
    """js/coque/diagnostic.js exécuté dans le navigateur : mode, titres, résumés, compteurs, heures, nombres."""
    _, base = serveur
    navigateur.ouvrir(base + "/")
    d = resultats("arretes")
    ok = resultats("actifs")
    r = navigateur.js_async("""
        const [d, ok] = arguments;
        const fin = arguments[arguments.length - 1];
        import('/js/coque/diagnostic.js').then((M) => fin({
          modes: [M.modeDiagnostic({mode: 'reel'}), M.modeDiagnostic({mode: 'reel', repetition: true}),
                  M.modeDiagnostic({mode: 'repetition'}), M.modeDiagnostic({mode: 'simu'}), M.modeDiagnostic(null)],
          url: [M.urlDiagnostic('repetition'), M.urlDiagnostic('reel', true)],
          titres: [M.titreBandeau(d), M.titreBandeau(ok), M.titreBandeau(null),
                   M.titreBandeau({etat: 'inconnu', resume: {ok: 3, attention: 0, probleme: 0, inconnu: 2}})],
          aRegler: M.aRegler(d).map((v) => v.id), regler: M.nombreARegler(d),
          bandeau: [M.phraseBandeau(d), M.phraseBandeau(ok)],
          resume: [M.phraseResume(d), M.phraseResume(ok), M.phraseResume(null)],
          compteurs: M.compteurs(d), groupes: M.parGroupe(d.verifications).map((g) => [g[0], g[2].length]),
          heures: [M.heureDe('2026-11-12T14:03:05+01:00'), M.heureDe('')],
          nombres: [M.nombreFr(1.84), M.nombreFr(2, 0), M.nombreFr('x')],
          depuis: [M.depuis(0, 10000), M.depuis(0, 125000), M.depuis(0, 3900000), M.depuis(0, 7200000)],
          executer: M.executer('autre', null, {}),
        })).catch((e) => fin({erreur: String(e)}));""", d, ok)
    assert "erreur" not in r, r
    assert r["modes"] == ["reel", "repetition", "repetition", None, None]
    assert r["url"] == ["/api/robot/diagnostic?mode=repetition", "/api/robot/diagnostic?mode=reel&rapide=1"]
    assert r["titres"] == ["2 points à régler", "1 point à régler", "Vérification…", "Rien à régler pour le moment"]
    assert r["aRegler"] == ["services", "sujets"] and r["regler"] == 2         # le problème avant l'attention
    assert r["bandeau"][0].startswith("D'abord : Services de cartographie. Cliquez sur")
    assert r["resume"][0] == "2 points à régler : Services de cartographie, Le robot parle au PC."
    assert r["resume"][1] == "1 point à régler : Le robot parle au PC." and "quelques secondes" in r["resume"][2]
    assert r["compteurs"] == [["ok", "3 OK"], ["attention", "1 attention"], ["probleme", "1 problème"]]
    assert r["groupes"] == [["reseau", 1], ["robot", 4]]
    assert r["heures"] == ["14:03", ""] and r["nombres"] == ["1,8", "2", "?"]
    assert r["depuis"] == ["à l'instant", "il y a 2 min", "il y a 1 h 05", "il y a 2 h"]
    assert r["executer"] is None
