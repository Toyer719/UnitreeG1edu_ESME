"""Assemblage de la vague 6 (section 13.13 du plan) : ce qui relie les modules entre eux.

- Échap ferme la fenêtre du diagnostic et l'adresse de la borne (écran Démo) sans envoyer l'ARRÊT quand le robot ne
  bouge pas, même si la navigation tourne (comme les menus, revue de la vague 5) ; plus rien d'ouvert, Échap envoie
  l'ARRÊT ; la fenêtre du diagnostic et l'adresse portent data-ferme-echap (echapServi de js/coque/coque.js) ;
- les réglages de la voix (js/voix/reglages_voix.js, composant de l'agent Voix) dans Équipe › Démo › ⚙ Réglages de
  la démo : la sortie choisie, « Démarrer la voix » lance le vrai nœud voix (sortie borne : rien vers un robot),
  « Essayer » fait dire une phrase dont le WAV est servi, le volume changé part au nœud qui tourne, « Arrêter la
  voix », puis « Enregistrer les réglages » écrit la voix dans demo.yaml ;
- les séances et les sons des tests restent dans le dossier du test (conftest.py, tests_e2e/commun.sh).
"""
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from atelier.lieu import accueil as A

from . import test_coque_communs as C
from .test_serveur_communs import faux_bin, journaux, lieux  # noqa: F401
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

def test_les_seances_et_les_sons_des_tests_restent_dans_le_test(tmp_path):
    from atelier.lieu.seance import dossier_seances
    from atelier.lieu.voix import dossier_sons
    assert tmp_path in dossier_seances().parents and tmp_path in dossier_sons().parents
    commun = (RACINE / "tests_e2e" / "commun.sh").read_text(encoding="utf-8")
    assert 'export ATELIER_SEANCES="$TRAVAIL/seances"' in commun
    assert 'export ATELIER_VOIX_SONS="$TRAVAIL/sons"' in commun


# ---------------------------------------------------------------- Échap et les fenêtres de la vague 6

@NAVIGATEUR
def test_echap_ferme_le_diagnostic_et_l_adresse_de_la_borne_sans_arret(sans_ros, serveur, navigateur, lieux):
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
def test_barre_d_outils_de_la_repetition_a_toutes_les_largeurs(sans_ros, serveur, navigateur, lieux):
    """Avec le badge de la séance et « Vérifier le robot » en plus, les pastilles d'état étaient rognées de 1100 à
    1600 px (« Refus du ro… ») : les états ne rétrécissent plus, les listes du lieu et de l'étage d'abord, puis la
    marque, le texte d'« Enregistrer » et de ROS 2 ; le texte du badge et de « Vérifier » à partir de 1800 px."""
    _, base = serveur
    nav = navigateur
    textes = {}
    for largeur in (1100, 1280, 1366, 1600, 1920):
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
                                 "v('[data-role=seance] .seance-badge-texte')];")
    assert textes[1100] == [False, False, False] and textes[1366] == [False, True, False], textes
    assert textes[1600] == [True, True, False] and textes[1920] == [True, True, True], textes
    assert nav.js("return window.erreursAtelier") == []


# ---------------------------------------------------------------- les réglages de la voix dans l'écran Démo

@pytest.fixture
def vraie_voix(faux_bin):
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
def test_reglages_de_la_voix_dans_l_ecran_demo(vraie_voix, serveur, navigateur, lieux):
    _, base = serveur
    nav = navigateur
    if not _lire(base, "/api/etat").get("ros", {}).get("actif"):
        pytest.skip("pont ROS 2 du serveur inactif (rclpy absent ?)")
    nav.taille(1600, 1000)
    C.ouvrir_espace(nav, base, "simu")
    purs = nav.js_async("""const fini = arguments[arguments.length - 1];
      import('/js/voix/reglages_voix.js').then((V) => fini([V.reglagesVoix({ volume: 300, vitesse: 'x', sortie: 'pc' }),
        V.reglagesVoix({ sortie: 'borne', nom: 'fr_FR-tom-medium', volume: 42.4, vitesse: 1.3 }),
        V.resumeEtatVoix(null).genre, V.resumeEtatVoix({ tourne: true, etat: { sortie: 'robot', robot: { abonne: false } } }).genre,
        V.resumeEtatVoix({ tourne: true, etat: { sortie: 'borne', en_cours: { texte: 'Bonjour' } } }).genre,
        V.resumeEtatVoix({ tourne: true, etat: { sortie: 'borne', dites: 2 } }).texte])).catch((e) => fini(String(e)));""")
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
