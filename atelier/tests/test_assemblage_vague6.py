"""Assemblage de la vague 6 (section 13.13 du plan) : ce qui relie les modules entre eux.

- Échap ferme la fenêtre du diagnostic et l'adresse de la borne (écran Démo) sans envoyer l'ARRÊT quand le robot ne
  bouge pas, même si la navigation tourne (comme les menus, revue de la vague 5) ; plus rien d'ouvert, Échap envoie
  l'ARRÊT ; la fenêtre du diagnostic et l'adresse portent data-ferme-echap (echapServi de js/coque/coque.js) ;
- les réglages de la voix (js/voix/reglages_voix.js, composant de l'agent Voix) dans Équipe › Démo › ⚙ Réglages de
  la démo : la sortie choisie, « Démarrer la voix » lance le vrai nœud voix (sortie borne : rien vers un robot),
  « Essayer » fait dire une phrase dont le WAV est servi, le volume changé part au nœud qui tourne, « Arrêter la
  voix », puis « Enregistrer les réglages » écrit la voix dans demo.yaml ;
- les séances et les sons des tests restent dans le dossier du test (conftest.py, tests_e2e/commun.sh) ;
- la boîte noire garde le vrai diagnostic du début (agent Diagnostic, faux contexte des tests) et chaque action de
  la démo, de la borne, de la voix et du diagnostic, et son rapport les montre (diagnostic en français, refus dans
  la chronologie) ; la chronologie montre les événements de la démo, une pause en « attention ».
"""
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

from atelier.lieu import accueil as A
from atelier.lieu import valider_donnees

from . import test_coque_communs as C
from .test_serveur_communs import client, faux_bin, journaux, lieux  # noqa: F401
from .test_serveur_demarrage import serveur  # noqa: F401
from .test_serveur_navigateur import GECKODRIVER, navigateur, sans_ros  # noqa: F401

RACINE = Path(__file__).resolve().parents[2]
NAVIGATEUR = pytest.mark.skipif(GECKODRIVER is None, reason="geckodriver absent")


def _poster(base, chemin, corps=None):
    requete = urllib.request.Request(base + chemin, data=json.dumps(corps or {}).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(requete, timeout=30) as r:
        return json.loads(r.read() or b"null")


def _lire(base, chemin):
    with urllib.request.urlopen(base + chemin, timeout=20) as r:
        return json.loads(r.read())


def _echap(nav):
    """Un vrai appui sur Échap (WebDriver), envoyé à l'élément qui a le curseur."""
    nav._requete("POST", f"/session/{nav.session}/actions", {"actions": [{"type": "key", "id": "clavier", "actions": [
        {"type": "keyDown", "value": ""}, {"type": "keyUp", "value": ""}]}]})
    time.sleep(0.3)


# ---------------------------------------------------------------- les dossiers des tests

def test_les_seances_et_les_sons_des_tests_restent_dans_le_test(tmp_path, tmp_path_factory):
    import atelier
    from atelier.diagnostic import FauxContexte, contexte_par_defaut
    from atelier.lieu.seance import dossier_seances
    from atelier.lieu.voix import dossier_sons
    # dans un dossier temporaire des tests, propre à ce test, et pas dans tmp_path (des tests comptent ce qu'ils y
    # écrivent) ni dans les journaux du projet
    base = tmp_path_factory.getbasetemp()
    for dossier in (dossier_seances(), dossier_sons(), Path(os.environ["ATELIER_DIAGNOSTIC_FAUX"])):
        assert base in dossier.parents and tmp_path not in dossier.parents, dossier
        assert atelier.dossier_journaux() not in dossier.parents, dossier
    assert list(tmp_path.iterdir()) == []
    # le diagnostic des tests (et celui de l'ouverture d'une séance en Réel) : un faux contexte vide, câble absent,
    # jamais de ping ni de ssh vers le robot, même câble branché
    ctx = contexte_par_defaut()
    assert type(ctx) is FauxContexte and ctx.lire("/sys/class/net/eno2/carrier") is None
    assert ctx.ping("192.168.123.161") is None
    commun = (RACINE / "tests_e2e" / "commun.sh").read_text(encoding="utf-8")
    assert 'export ATELIER_SEANCES="$TRAVAIL/seances"' in commun
    assert 'export ATELIER_VOIX_SONS="$TRAVAIL/sons"' in commun


# ---------------------------------------------------------------- la boîte noire garde le diagnostic et la démo

def _attendre(condition, delai=20.0, pas=0.2):
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        if condition():
            return True
        time.sleep(pas)
    return condition()


def _lignes(fichier):
    try:
        return [json.loads(x) for x in fichier.read_text(encoding="utf-8").splitlines() if x.strip()]
    except OSError:
        return []


def test_la_seance_garde_le_diagnostic_et_les_actions_de_la_demo(client):  # noqa: F811
    """Séance ouverte en Réel par l'Atelier entier (sans ROS 2) : le diagnostic du début est le vrai (agent
    Diagnostic) sur le faux contexte des tests, source « seance » ; chaque demande de la démo, de la borne, de la voix
    et du diagnostic est une ligne du journal des actions, refusée en français (jamais 500) ; « Terminer la séance » :
    le rapport montre le diagnostic (états en français) et les refus dans sa chronologie."""
    from atelier.lieu.seance import dossier_seances
    r = client.post("/api/seance/demarrer", json={"mode": "reel", "lieu": "demo", "etage": "rdc",
                                                  "ouverture": "auto"})
    assert r.status_code == 200, r.text
    ident = r.json()["seance"]["id"]
    dossier = dossier_seances() / ident
    # le diagnostic du début : le vrai, en arrière-plan, jamais vers le robot (faux contexte : câble absent)
    assert _attendre(lambda: (dossier / "diagnostic_debut.json").is_file()
                     and json.loads((dossier / "seance.json").read_text())["diagnostic_debut"]
                     == "diagnostic_debut.json"), "diagnostic du début pas écrit"
    diag = json.loads((dossier / "diagnostic_debut.json").read_text(encoding="utf-8"))
    assert valider_donnees("diagnostic", diag) == []
    assert (diag["source"], diag["mode"]) == ("seance", "reel")
    etats = {v["id"]: v["etat"] for v in diag["verifications"]}
    assert etats["cable"] == "probleme" and diag["etat"] == "probleme"
    assert {i["id"] for i in diag["ignorees"]} >= {"pc1", "jetson", "lidar", "jetson_ssh"}   # ni ping ni ssh
    # les demandes des modules de la vague 6 pendant la séance
    demandes = [("/api/robot/diagnostic/demarrer-services", {}, "diagnostic",
                 "Diagnostic : Démarrer les services de cartographie"),
                ("/api/demo/lancer", {"lieu": "demo", "etage": "rdc"}, "demo", "Lancer la démo"),
                ("/api/demo/commande", {"action": "pause"}, "demo", "Démo : pause"),
                ("/api/borne/appui", {}, "borne", "Borne : appui"),
                ("/api/borne/choisir", {"salle": "b204"}, "borne", "Borne : Salle B204"),
                ("/api/borne/operateur", {"code": "1234"}, "borne", "Borne : code opérateur"),
                ("/api/voix/essayer", {"texte": "Bonjour"}, "voix", "Voix : essayer « Bonjour »"),
                ("/api/demo/arreter", {}, "demo", "Arrêter la démo")]
    statuts = {}
    for chemin, corps, _, _ in demandes:
        r = client.post(chemin, json=corps)
        assert r.status_code < 500 or r.status_code == 503, (chemin, r.status_code, r.text[:200])
        if r.status_code >= 400:
            assert isinstance(r.json()["detail"], str) and r.json()["detail"], chemin
        statuts[chemin] = r.status_code
    assert statuts["/api/robot/diagnostic/demarrer-services"] == 409        # sans confirmation : rien ne part
    assert statuts["/api/demo/lancer"] == 409                               # le guide ne tourne pas
    assert _attendre(lambda: len(_lignes(dossier / "actions.jsonl")) >= 1 + len(demandes))
    lignes = _lignes(dossier / "actions.jsonl")[1:]                          # la 1re : l'ouverture de la séance
    assert [(x["chemin"], x["genre"], x["texte"], x["statut"]) for x in lignes] == [
        (chemin, genre, texte, statuts[chemin]) for chemin, _, genre, texte in demandes]
    assert all(valider_donnees("action_seance", x) == [] and x["mode"] == "reel" for x in lignes)
    assert lignes[5]["requete"] == {"code": "••••"}                         # le code opérateur jamais en clair
    # « Terminer la séance » : le rapport
    assert client.post("/api/seance/arreter", json={}).status_code == 200
    assert _attendre(lambda: client.get(f"/api/seances/{ident}").json()["rapport"]["etat"] == "pret", 90)
    rapport = client.get(f"/api/seances/{ident}/rapport?format=json").json()
    assert rapport["diagnostic"]["etat"] == "probleme"
    assert "Câble du robot" in [v["titre"] for v in rapport["diagnostic"]["a_regler"]]
    textes = [c["texte"] for c in rapport["chronologie"]]
    for _, _, _, texte in demandes:
        assert any(t.startswith(texte) for t in textes), texte
    refus = [c for c in rapport["chronologie"] if c["texte"].startswith("Lancer la démo")][0]
    assert refus["gravite"] == "attention" and "refusé (409)" in refus["texte"] and "guide" in refus["texte"]
    md = client.get(f"/api/seances/{ident}/rapport?format=md").text
    assert "État : **Problème**." in md and "- Câble du robot (Problème) :" in md and "probleme" not in md
    page = client.get(f"/api/seances/{ident}/rapport").text
    assert "État : <strong>Problème</strong>." in page and "Borne : Salle B204" in page


def test_la_chronologie_montre_la_demo():
    """Les événements de la démo enregistrés (/accueil/evenement) sont dans la chronologie du rapport ; la démo
    mise en pause (ARRÊT, verrou…) et une visite en échec sont « à regarder » (attention), le reste pour info."""
    from atelier.seance import analyse as AN
    from atelier.seance import rapport as R
    from atelier.seance.lecture import Donnees
    from atelier.seance.manifeste import heure_iso
    t0 = 1794000000.0
    d = Donnees()
    evenements = [(5.0, {"version": 1, "code": "salutation", "texte": "Bonjour ! Je suis le robot d'accueil."}),
                  (9.0, {"version": 1, "code": "choix_accepte", "texte": "Visite vers « Salle B204 » acceptée.",
                         "salle": "b204", "source": "borne"}),
                  (30.0, {"version": 1, "code": "pause", "texte": "La démo est en pause : ARRÊT.", "raison": "arret"}),
                  (60.0, {"version": 1, "code": "visite_echouee", "texte": "La visite n'a pas abouti."}),
                  (61.0, {"version": 1, "code": "reprise"})]
    for t, e in evenements:
        d.ajouter("/accueil/evenement", "std_msgs/msg/String", t0 + t, SimpleNamespace(data=json.dumps(e)))
    m = {"id": "2026-11-12_14h03", "etat": "fermee", "mode": "repetition", "debut": heure_iso(t0),
         "fin": heure_iso(t0 + 90), "ouverture": "auto", "fermeture": "terminer"}
    demo = [(c["texte"], c["gravite"]) for c in AN.chronologie(d, [], m) if c["genre"] == "demo"]
    assert demo == [("Démo : Bonjour ! Je suis le robot d'accueil.", "info"),
                    ("Démo : Visite vers « Salle B204 » acceptée.", "info"),
                    ("Démo : La démo est en pause : ARRÊT.", "attention"),
                    ("Démo : La visite n'a pas abouti.", "attention"),
                    ("Démo : reprise", "info")]
    # les états du diagnostic écrits comme dans « Vérifier le robot »
    assert [R.etat_diagnostic(e) for e in ("ok", "attention", "probleme", "inconnu", None, "autre")] == [
        "OK", "Attention", "Problème", "Inconnu", "?", "autre"]


# ---------------------------------------------------------------- Échap et les fenêtres de la vague 6

@NAVIGATEUR
def test_echap_ferme_le_diagnostic_et_la_borne_sans_arret(sans_ros, serveur, navigateur, lieux):  # noqa: F811
    _, base = serveur
    nav = navigateur
    nav.taille(1366, 768)
    _poster(base, "/api/lieux/demo/etages/rdc/monde/generer")
    _poster(base, "/api/simulation/demarrer", {"lieu": "demo", "etage": "rdc", "mode": "repetition"})
    try:
        C.ouvrir_espace(nav, base, "repetition")
        # la navigation (fausse) tourne : sans fenêtre ouverte, Échap enverrait l'ARRÊT
        nav.attendre("const b = document.querySelector('[data-role=bouton-ce-qui-tourne]'); return !!b && !b.hidden",
                     delai=20.0, message="« Ce qui tourne » montré (la répétition tourne)")
        C.installer_espions(nav)
        nav.clic("[data-role=zone-diagnostic] [data-role=verifier-robot]")
        nav.attendre("return !!document.querySelector('[data-role=diagnostic][data-ferme-echap]')",
                     message="fenêtre du diagnostic")
        _echap(nav)
        nav.attendre("return !document.querySelector('[data-role=diagnostic]')", message="Échap ferme le diagnostic")
        time.sleep(0.8)
        assert C.requetes(nav, "POST", "/api/arret") == [], "Échap sur la fenêtre du diagnostic a envoyé l'ARRÊT"
        nav.commande("demo.borne")
        nav.attendre("return !!document.querySelector('[data-role=demo-borne][data-ferme-echap]')",
                     message="adresse de la borne en grand")
        _echap(nav)
        nav.attendre("return !document.querySelector('[data-role=demo-borne]')", message="Échap ferme l'adresse")
        time.sleep(0.8)
        assert C.requetes(nav, "POST", "/api/arret") == [], "Échap sur l'adresse de la borne a envoyé l'ARRÊT"
        # plus rien d'ouvert, la navigation tourne toujours : Échap est l'ARRÊT (règle de la vague 5)
        _echap(nav)
        r = nav.attendre(C.DERNIER_ARRET, 0, "/api/arret", delai=5.0, message="ARRÊT envoyé par Échap")
        assert (r.get("corps") or {}).get("mode") == "repetition"
        assert C.fenetres_natives(nav) == []
        assert nav.js("return window.erreursAtelier") == []
    finally:
        _poster(base, "/api/simulation/arreter")


# ---------------------------------------------------------------- la barre d'outils, pleine depuis la vague 6

@NAVIGATEUR
def test_barre_d_outils_de_la_repetition_a_toutes_les_largeurs(sans_ros, serveur, navigateur, lieux):  # noqa: F811
    """Avec le badge de la séance et « Vérifier le robot » en plus, les pastilles d'état étaient rognées de 1100 à
    1600 px (« Refus du ro… ») : les états ne rétrécissent plus, les listes du lieu et de l'étage d'abord, puis la
    marque, le texte d'« Enregistrer » et de ROS 2 ; le texte du badge et de « Vérifier » à partir de 1800 px.
    Corrections de la vague 6 (revue de l'interface, défaut 9) : le badge dit « Séance » de 1440 à 1799 px (un point
    seul ressemblait à un voyant d'erreur), la marque laisse sa place sous 1600 px, « Vérifier » écrit dès 1700 px ;
    les listes du lieu et de l'étage gardent au moins 100 px à partir de 1366 px."""
    _, base = serveur
    nav = navigateur
    textes = {}
    for largeur in (1100, 1280, 1366, 1440, 1600, 1700, 1920):
        nav.taille(largeur, 800)
        C.ouvrir_espace(nav, base, "repetition")
        nav.attendre("return !!document.querySelector('[data-role=seance]') && "
                     "!!document.querySelector('[data-role=zone-diagnostic] [data-role=verifier-robot]')", delai=20.0,
                     message="badge de la séance et « Vérifier le robot »")
        fautes = nav.js(C.BARRE_SANS_CHEVAUCHEMENT, "Refus du robot")
        assert not fautes, f"barre d'outils à {largeur} px : {fautes}"
        textes[largeur] = nav.js("const v = (s) => { const e = document.querySelector(s); return !!e && "
                                 "getComputedStyle(e).display !== 'none'; };"
                                 "return [v('.marque-barre'), v('.bouton-enregistrer .bouton-barre-texte'),"
                                 "v('[data-role=seance] .seance-badge-texte'), v('[data-role=seance] .seance-badge-court'),"
                                 "v('[data-role=zone-diagnostic] .bouton-barre-texte')];")
        if largeur >= 1366:
            listes = nav.js("return ['[data-role=lieu]', '[data-role=etage]'].map((s) => "
                            "document.querySelector(s).getBoundingClientRect().width);")
            assert min(listes) >= 100, f"à {largeur} px, les listes du lieu et de l'étage : {listes} px"
    assert textes[1100] == [False, False, False, False, False], textes
    assert textes[1366] == [False, True, False, False, False], textes
    assert textes[1440] == [False, True, False, True, False], textes
    assert textes[1600] == [True, True, False, True, False], textes
    assert textes[1700] == [True, True, False, True, True], textes
    assert textes[1920] == [True, True, True, False, True], textes
    assert nav.js("return window.erreursAtelier") == []


# ---------------------------------------------------------------- les réglages de la voix dans l'écran Démo

# le texte choisi de chaque liste (et la valeur de chaque champ texte d'une ligne) des réglages de la démo tient-il ?
TEXTES_COUPES = r"""
const c = document.createElement('canvas').getContext('2d');
const coupes = [];
for (const e of document.querySelectorAll('[data-role=demo-reglages] select, [data-role=demo-reglages] input[type=text]')) {
  if (!e.offsetParent) continue;
  const s = getComputedStyle(e);
  c.font = s.fontWeight + ' ' + s.fontSize + ' ' + s.fontFamily;
  const textes = e.tagName === 'SELECT' ? Array.from(e.options).map((o) => o.textContent) : [e.value];
  const place = e.clientWidth - parseFloat(s.paddingLeft) - parseFloat(s.paddingRight) - (e.tagName === 'SELECT' ? 18 : 0);
  for (const t of textes) {
    const l = c.measureText(t).width;
    if (l > place + 1) coupes.push('« ' + t + ' » : ' + Math.round(l) + ' px pour ' + Math.round(place));
  }
}
return coupes;"""


@NAVIGATEUR
def test_listes_des_reglages_de_la_demo_entieres(sans_ros, serveur, navigateur, lieux):  # noqa: F811
    """Corrections de la vague 6 (revue de l'interface, défaut 3) : dans le panneau étroit, « Le robot parle par »
    montrait « Haut-parleur du » (113 px sur 259), « Voix » et « Personnalité » coupées aussi, à toutes les tailles
    d'écran. L'étiquette est au-dessus, la liste en pleine largeur, les noms des sorties sont courts et une phrase dit
    la différence (voix du PC, borne, synthèse du robot à vérifier)."""
    _, base = serveur
    nav = navigateur
    for largeur, hauteur in ((1920, 1080), (1366, 768)):
        nav.taille(largeur, hauteur)
        C.ouvrir_espace(nav, base, "simu")
        nav.commande("demo.reglages")
        nav.ecran("demo")
        nav.attendre("const d = document.querySelector('[data-role=demo-reglages]'); return !!d && d.open && "
                     "!!d.querySelector('[data-role=voix-sortie-aide]')", message="réglages ouverts")
        assert nav.js(TEXTES_COUPES) == [], largeur
        aide = nav.js("return document.querySelector('[data-role=voix-sortie-aide]').textContent")
        assert "PC" in aide and "haut-parleur du robot" in aide, aide
    _choisir(nav, "Le robot parle par", "robot_tts")
    assert "à vérifier" in nav.js("return document.querySelector('[data-role=voix-sortie-aide]').textContent")
    purs = nav.js_async("""const fini = arguments[arguments.length - 1];
      import('/js/voix/reglages_voix.js').then((V) => fini([V.SORTIES_VOIX.map((s) => s.id), V.aideSortie('borne'),
        V.aideSortie('inconnue')])).catch((e) => fini(String(e)));""")
    assert purs[0] == ["robot", "borne", "robot_tts"] and "borne" in purs[1] and purs[2] == "", purs
    assert nav.js("return window.erreursAtelier") == []


@pytest.fixture
def vraie_voix(faux_bin):  # noqa: F811
    """Le vrai g1-voix dans le $ATELIER_BIN des tests (les autres commandes restent fausses)."""
    (faux_bin.dossier / "g1-voix").symlink_to(RACINE / "bin" / "g1-voix")
    yield
    # filet de sécurité : aucun nœud voix lancé avec les sons de ce test ne doit rester
    sons = os.environ.get("ATELIER_VOIX_SONS", "")
    for p in Path("/proc").iterdir():
        if not p.name.isdigit():
            continue
        try:
            commande = (p / "cmdline").read_bytes()
            env = (p / "environ").read_bytes()
        except OSError:
            continue
        if b"atelier.voix" in commande and f"ATELIER_VOIX_SONS={sons}".encode() in env:
            os.kill(int(p.name), 9)


def _choisir(nav, libelle, valeur):
    """Change le champ de libellé donné des réglages de la voix (liste ou nombre), comme l'utilisateur."""
    assert nav.js("const l = Array.from(document.querySelectorAll('[data-role=voix-reglages] label.champ'))"
                  ".find((x) => x.querySelector('.champ-libelle').textContent === arguments[0]);"
                  "if (!l) return false; const c = l.querySelector('input, select'); c.value = arguments[1];"
                  "c.dispatchEvent(new Event('change', { bubbles: true })); return true;", libelle, valeur), libelle


@NAVIGATEUR
def test_reglages_de_la_voix_dans_l_ecran_demo(vraie_voix, serveur, navigateur, lieux):  # noqa: F811
    _, base = serveur
    nav = navigateur
    if not _lire(base, "/api/etat").get("ros", {}).get("actif"):
        pytest.skip("pont ROS 2 du serveur inactif (rclpy absent ?)")
    nav.taille(1600, 1000)
    C.ouvrir_espace(nav, base, "simu")
    purs = nav.js_async("""const fini = arguments[arguments.length - 1];
      import('/js/voix/reglages_voix.js').then((V) => fini([
        V.reglagesVoix({ volume: 300, vitesse: 'x', sortie: 'pc' }),
        V.reglagesVoix({ sortie: 'borne', nom: 'fr_FR-tom-medium', volume: 42.4, vitesse: 1.3 }),
        V.resumeEtatVoix(null).genre,
        V.resumeEtatVoix({ tourne: true, etat: { sortie: 'robot', robot: { abonne: false } } }).genre,
        V.resumeEtatVoix({ tourne: true, etat: { sortie: 'borne', en_cours: { texte: 'Bonjour' } } }).genre,
        V.resumeEtatVoix({ tourne: true, etat: { sortie: 'borne', dites: 2 } }).texte]))
        .catch((e) => fini(String(e)));""")
    assert purs[0] == {"sortie": "robot", "nom": "fr_FR-siwis-medium", "volume": 100, "vitesse": 1}, purs
    assert purs[1] == {"sortie": "borne", "nom": "fr_FR-tom-medium", "volume": 42, "vitesse": 1.3}, purs
    assert purs[2:5] == ["arrete", "muet", "parle"] and "2 phrases dites" in purs[5], purs
    nav.commande("demo.reglages")
    nav.ecran("demo")
    nav.attendre("const d = document.querySelector('[data-role=demo-reglages]'); return !!d && d.open",
                 message="réglages ouverts")
    nav.attendre("const e = document.querySelector('[data-role=demo-reglages] [data-role=voix-etat]');"
                 "return e && e.dataset.etat === 'arrete'", message="la voix ne tourne pas au départ")
    _choisir(nav, "Le robot parle par", "borne")
    nav.attendre("return !document.querySelector('[data-role=demo-enregistrer]').disabled",
                 message="« Enregistrer les réglages » actif après le changement de la voix")
    nav.clic("[data-role=voix-demarrer]")
    nav.attendre("return document.querySelector('[data-role=voix-etat]').dataset.etat === 'attente'", delai=40.0,
                 message="la voix démarrée (prête)")
    assert _lire(base, "/api/voix/etat")["etat"]["sortie"] == "borne"
    nav.clic("[data-role=voix-essayer]")
    src = nav.attendre("const a = document.querySelector('[data-role=voix-ecouter]');"
                       "return a.src && a.src.indexOf('/api/voix/son/essai-') >= 0 ? a.src : null", delai=20.0,
                       message="le son de l'essai chargé dans la page")
    fin = time.monotonic() + 15
    while True:
        try:
            with urllib.request.urlopen(src, timeout=10) as r:
                assert r.headers.get("Content-Type", "").startswith("audio/wav") and len(r.read()) > 1000
            break
        except urllib.error.HTTPError:
            assert time.monotonic() < fin, f"le WAV de l'essai n'est pas servi : {src}"
            time.sleep(0.5)
    _choisir(nav, "Volume", "50")
    fin = time.monotonic() + 10
    while (_lire(base, "/api/voix/etat").get("etat") or {}).get("volume") != 50:
        assert time.monotonic() < fin, "le volume changé n'est pas arrivé au nœud voix"
        time.sleep(0.3)
    nav.clic("[data-role=voix-arreter]")
    nav.attendre("return document.querySelector('[data-role=voix-etat]').dataset.etat === 'arrete'", delai=20.0,
                 message="la voix arrêtée")
    nav.clic("[data-role=demo-enregistrer]")
    dossier = lieux / "demo"
    fin = time.monotonic() + 5
    while not (dossier / "demo.yaml").exists() and time.monotonic() < fin:
        time.sleep(0.1)
    voix = A.charger_demo(dossier)["voix"]
    assert voix["sortie"] == "borne" and voix["volume"] == 50, voix
    assert nav.js("return window.erreursAtelier") == []
