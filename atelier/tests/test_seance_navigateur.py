"""La boîte noire dans l'Atelier, dans Firefox sans fenêtre (vague 6, sections 13.3 et 13.7 du plan) : agent Boîte
noire.

Serveur g1-atelier de test (faux g1-monde, g1-guide, g1-slam, et un faux g1-seance qui écrit enregistrement.json),
$ATELIER_SEANCES dans le dossier du test :
  - en répétition, la séance s'ouvre seule à l'ouverture de l'espace (ouverture « auto ») ; le badge
    [data-role=seance] dit « Enregistrement » (data-etat=enregistrement), tient dans la barre d'outils sans couvrir
    l'ARRÊT ; son menu [data-role=menu-seance] s'ouvre, se ferme par Échap (sans ARRÊT : rien ne bouge) et par ✗ ;
  - « Terminer la séance » (menu, puis ruban) demande confirmation dans la page, ferme la séance, et le lien du
    rapport [data-role=rapport-seance] devient actif quand le rapport est prêt ; il sert le rapport HTML ;
  - en Simulation : aucune séance, pas de badge ;
  - les fonctions pures de seance.js ; aucune boîte native, window.erreursAtelier vide.
"""
import json
import os
import signal
import stat
import time
import urllib.request
from pathlib import Path

import pytest

from . import test_coque_communs as C
from .test_seance_gestionnaire import FAUX_ENREGISTREUR
from .test_serveur_communs import faux_bin, journaux, lieux  # noqa: F401
from .test_serveur_demarrage import serveur  # noqa: F401
from .test_serveur_navigateur import GECKODRIVER, navigateur  # noqa: F401

pytestmark = pytest.mark.skipif(GECKODRIVER is None, reason="geckodriver absent")

BADGE = ("const b = document.querySelector('[data-role=seance]'); "
         "return b && !b.hidden ? b.getAttribute('data-etat') : null")


@pytest.fixture
def seances(tmp_path, monkeypatch, faux_bin):  # noqa: F811
    """$ATELIER_SEANCES dans le dossier du test, et un faux g1-seance dans le $ATELIER_BIN du serveur de test. À la
    fin (le serveur de test est tué), aucun faux enregistreur ne reste : il s'arrête seul quand l'Atelier disparaît,
    et le filet de sécurité arrête ceux qui resteraient."""
    monkeypatch.setenv("ATELIER_SEANCES", str(tmp_path / "seances"))
    chemin = faux_bin.dossier / "g1-seance"
    chemin.write_text(FAUX_ENREGISTREUR, encoding="utf-8")
    chemin.chmod(chemin.stat().st_mode | stat.S_IXUSR)
    yield tmp_path / "seances"
    fin = time.monotonic() + 5.0
    while _faux_enregistreurs(chemin) and time.monotonic() < fin:
        time.sleep(0.1)
    for pid in _faux_enregistreurs(chemin):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _faux_enregistreurs(chemin):
    """PID des faux enregistreurs de ce test encore vivants."""
    vus = []
    for d in Path("/proc").iterdir():
        if d.name.isdigit():
            try:
                if str(chemin) in (d / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace"):
                    vus.append(int(d.name))
            except OSError:
                continue
    return vus


def _api(base, chemin):
    with urllib.request.urlopen(base + chemin, timeout=20) as r:
        return json.loads(r.read())


def test_badge_menu_et_terminer_en_repetition(seances, serveur, navigateur, lieux):  # noqa: F811
    _, base = serveur
    nav = navigateur
    nav.taille(1366, 768)
    C.ouvrir_espace(nav, base, "repetition")
    C.installer_espions(nav)
    assert nav.attendre(BADGE, message="badge de la séance") == "enregistrement"
    seance = _api(base, "/api/seance")["seance"]
    assert seance["ouverture"] == "auto" and seance["mode"] == "repetition" and seance["lieu"] == "demo"
    assert (seances / seance["id"] / "seance.json").is_file()
    texte = nav.js("return document.querySelector('[data-role=seance]').textContent")
    assert "Enregistrement" in texte                       # le texte est là (montré à partir de 1 600 px)
    assert "Enregistrement" in nav.js("return document.querySelector('[data-role=seance]').title + "
                                      "document.querySelector('[data-role=seance]').getAttribute('aria-label')")
    # le badge tient dans la barre d'outils, sans couvrir l'ARRÊT
    boites = nav.js("""const b = document.querySelector('[data-role=seance]').getBoundingClientRect();
      const a = document.querySelector('[data-role=arret]').getBoundingClientRect();
      const barre = document.querySelector('[data-role=barre-outils]').getBoundingClientRect();
      const t = document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2);
      return [b.left, b.right, b.top, b.bottom, a.left, barre.bottom, window.innerWidth,
              !!t && !!t.closest('[data-role=seance]')];""")
    gauche, droite, haut, bas, arret_gauche, barre_bas, largeur, visible = boites
    assert 0 <= gauche < droite <= largeur and bas <= barre_bas + 1 and droite <= arret_gauche, boites
    assert visible, "le badge est recouvert"
    assert C.mesurer(nav)["fautes"] == []
    # le menu : il s'ouvre sous la barre d'outils ; Échap le ferme sans envoyer l'ARRÊT (rien ne bouge)
    nav.clic("[data-role=seance]")
    nav.attendre("return !!document.querySelector('[data-role=menu-seance]')", message="menu de la séance")
    haut_menu = nav.js("return document.querySelector('[data-role=menu-seance]').getBoundingClientRect().top")
    assert haut_menu >= barre_bas - 1
    nav.js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}))")
    nav.attendre("return !document.querySelector('[data-role=menu-seance]')", message="menu fermé par Échap")
    assert C.requetes(nav, "POST", "/api/arret") == []
    nav.clic("[data-role=seance]")
    nav.clic("[data-role=fermer-menu-seance]")
    assert nav.js("return !document.querySelector('[data-role=menu-seance]')")
    # « Terminer la séance » depuis le menu : confirmation dans la page, puis le lien du rapport
    nav.clic("[data-role=seance]")
    nav.clic("[data-role=terminer-seance]")
    nav.attendre("return !!document.querySelector('[data-role=confirmation]')", message="confirmation")
    nav.clic("[data-role=confirmation] [data-role=confirmer]")
    nav.attendre("const l = document.querySelector('[data-role=zone-seance] [data-role=rapport-seance]');"
                 "return l && !l.hidden", message="lien du rapport")
    assert nav.js(BADGE) is None
    assert [r["corps"] for r in C.requetes(nav, "POST", "/api/seance/arreter")] == [{"fermeture": "terminer"}]
    nav.attendre("return document.querySelector('[data-role=zone-seance] [data-role=rapport-seance]')"
                 ".getAttribute('data-etat') === 'pret'", delai=90, message="rapport prêt")
    lien = nav.js("return document.querySelector('[data-role=zone-seance] [data-role=rapport-seance]').href")
    assert lien.endswith(f"/api/seances/{seance['id']}/rapport")
    with urllib.request.urlopen(lien, timeout=20) as r:
        assert "Rapport de séance du" in r.read().decode("utf-8")
    m = _api(base, f"/api/seances/{seance['id']}")
    assert m["etat"] == "fermee" and m["fermeture"] == "terminer" and m["rapport"]["etat"] == "pret"
    # le ruban : Naviguer › ⚙ › Rapport de séance ouvre le menu, avec le lien de la séance terminée
    nav.commande("seance.rapport")
    nav.attendre(f"return !!document.querySelector('[data-role=menu-seance] [data-seance=\"{seance['id']}\"] "
                 "[data-role=rapport-seance]')", message="rapport dans le menu")
    nav.js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}))")
    assert C.fenetres_natives(nav) == [] and nav.js("return window.erreursAtelier") == []


def test_terminer_par_le_ruban_puis_nouvelle_seance(seances, serveur, navigateur, lieux):  # noqa: F811
    _, base = serveur
    nav = navigateur
    nav.taille(1366, 768)
    C.ouvrir_espace(nav, base, "reel")
    nav.attendre(BADGE, message="badge de la séance")
    premiere = _api(base, "/api/seance")["seance"]["id"]
    assert _api(base, "/api/seance")["seance"]["mode"] == "reel"
    nav.commande("seance.terminer")
    nav.attendre("return !!document.querySelector('[data-role=confirmation]')", message="confirmation")
    nav.clic("[data-role=confirmation] [data-role=renoncer]")         # « Continuer » : rien ne change
    assert _api(base, "/api/seance")["seance"]["id"] == premiere
    nav.commande("seance.terminer")
    nav.clic("[data-role=confirmation] [data-role=confirmer]")
    nav.attendre("return !document.querySelector('[data-role=seance]') || "
                 "document.querySelector('[data-role=seance]').hidden", message="badge caché")
    assert _api(base, "/api/seance")["seance"] is None
    # à la main : le menu (Naviguer › ⚙ › Rapport de séance) propose « Commencer une séance »
    nav.commande("seance.rapport")
    nav.clic("[data-role=menu-seance] [data-role=commencer-seance]")
    nav.attendre(BADGE, message="séance commencée à la main")
    seconde = _api(base, "/api/seance")["seance"]
    assert seconde["id"] != premiere and seconde["ouverture"] == "manuel"
    # une nouvelle ouverture de l'espace en Réel rend la séance ouverte (une seule à la fois)
    C.ouvrir_espace(nav, base, "repetition")
    nav.attendre(BADGE, message="séance de nouveau montrée")
    assert _api(base, "/api/seance")["seance"]["id"] == seconde["id"]
    assert nav.js("return window.erreursAtelier") == []


def test_pas_de_seance_en_simulation(seances, serveur, navigateur, lieux):  # noqa: F811
    _, base = serveur
    nav = navigateur
    nav.taille(1366, 768)
    C.ouvrir_espace(nav, base, "simu")
    time.sleep(1.0)
    assert nav.js(BADGE) is None and _api(base, "/api/seance")["seance"] is None
    assert not seances.exists() or not any(seances.iterdir())
    assert nav.js("return window.erreursAtelier") == []


def test_fonctions_pures_de_seance_js(serveur, navigateur):  # noqa: F811
    _, base = serveur
    nav = navigateur
    C.charger(nav, base + "/", C.ACCUEIL, "accueil")
    r = nav.js_async("""const fini = arguments[arguments.length - 1];
      import('/js/coque/seance.js').then((S) => fini({
        modes: [S.modeSeance({mode: 'reel'}), S.modeSeance({mode: 'reel', repetition: true}),
                S.modeSeance({mode: 'repetition'}), S.modeSeance({mode: 'simu'}), S.modeSeance(null)],
        heure: S.heureDe('2026-11-12T14:03:05+01:00'), jour: S.jourDe('2026-11-12T14:03:05+01:00'),
        tailles: [S.tailleLisible(1843200), S.tailleLisible(5300), S.tailleLisible(null)],
        durees: [S.dureeLisible(45), S.dureeLisible(2532), S.dureeLisible(3725)],
        badge: S.badgeDe({badge: 'enregistrement', debut: '2026-11-12T14:03:05+01:00', actions: 2,
                          enregistrement: {octets: 1843200}}),
        coupe: S.badgeDe({badge: 'coupe', debut: '2026-11-12T14:03:05+01:00', actions: 1,
                          enregistrement: {message: 'Enregistrement arrêté : disque plein.'}}),
        inconnu: S.badgeDe({badge: 'zzz', debut: ''}), aucun: S.badgeDe(null),
        url: [S.urlRapport('2026-11-12_14h03'), S.urlRapport('2026-11-12_14h03', 'md')],
        ligne: S.ligneSeance({debut: '2026-11-12T14:03:05+01:00', duree_s: 2532, mode: 'repetition', lieu: 'demo',
                             etat: 'interrompue'}),
        bref: S.brefDuManifeste({etat: 'ouverte', id: 'x', debut: 'd', actions: 3, mode: 'reel',
                                 enregistrement: {etat: 'coupe', octets: 9, message: 'm'}}),
        ferme: S.brefDuManifeste({etat: 'fermee'}),
      }));""")
    assert r["modes"] == ["reel", "repetition", "repetition", None, None]
    assert r["heure"] == "14:03" and r["jour"] == "12/11"
    assert r["tailles"] == ["1,8\u00a0Mo", "5\u00a0ko", "0\u00a0ko"] and r["durees"] == ["45 s", "42 min", "1 h 02"]
    assert r["badge"]["etat"] == "enregistrement" and r["badge"]["texte"] == "Enregistrement"
    assert "2 actions notées, 1,8\u00a0Mo enregistrés" in r["badge"]["titre"]
    assert r["coupe"]["texte"] == "Enregistrement coupé" and "disque plein" in r["coupe"]["titre"]
    assert r["inconnu"]["etat"] == "arrete" and r["aucun"] is None
    assert r["url"] == ["/api/seances/2026-11-12_14h03/rapport", "/api/seances/2026-11-12_14h03/rapport?format=md"]
    assert r["ligne"] == "12/11 14:03 · 42 min · Répétition (interrompue) · demo"
    assert r["bref"]["badge"] == "coupe" and r["bref"]["actions"] == 3 and r["ferme"] is None
