"""La borne visiteur dans Firefox sans fenêtre (vague 6, section 13.5 du plan ; critère 39) : agent Borne et
orchestrateur.

Le serveur de l'Atelier (sans ROS) tourne dans un fil, branché sur la vraie machine d'états de la démo par un faux
pont (test_borne_communs) ; la borne est ouverte dans un cadre de la taille d'un téléphone (390 × 844) puis d'une
tablette (1024 × 768). On vérifie : la page ne défile pas, chaque carte fait 64 px au moins et s'amène entière à
l'écran, les salles de la borne (ni l'accueil, ni une salle cachée), aucun jargon, la confirmation dans la page, cinq
appuis rapides → un seul choix, puis « Suivez-moi » avec la distance, l'arrivée, le retour, les salles ; occupé et
pause : cartes inactives et message ; le premier appui (le robot salue) ; le son de la sortie borne ; le mode
opérateur (code faux, bon code, seulement pause, reprendre et ramener) ; hors service ; l'anglais ;
window.erreursBorne vide. Captures : $ATELIER_CAPTURES_BORNE (sinon le dossier temporaire du test).
"""
import os
import shutil
import time
from pathlib import Path

import pytest

from atelier.lieu import accueil as A
from atelier.lieu import charger_salles, enregistrer_salles

from .test_borne_communs import (MESURE_BORNE, ServeurDemo, attendre_ecran, capture_cadre, client_demo,
                                 ouvrir_borne_cadre, preparer_firefox)
from .test_serveur_navigateur import arreter_navigateur, demarrer_navigateur

GECKODRIVER = shutil.which("geckodriver")
pytestmark = pytest.mark.skipif(GECKODRIVER is None or shutil.which("firefox") is None,
                                reason="geckodriver ou Firefox absent")
TAILLES = {"telephone": (390, 844), "tablette": (1024, 768)}
SALLES_BORNE = ["infirmerie", "cdi", "amphi", "b204"]       # demo sans l'accueil, vie_scolaire cachée

# chevrons « › » des cartes visibles à l'écran (cachés sur les cartes inactives ; la tablette n'en a pas)
CHEVRONS_VISIBLES = """
return Array.from(document.querySelectorAll('.borne-carte-chevron')).filter((c) => {
  const s = getComputedStyle(c);
  return s.display !== 'none' && s.visibility !== 'hidden';
}).length;
"""

CINQ_APPUIS = """
const oui = document.querySelector('[data-role=confirmer-salle]');
for (let i = 0; i < 5; i++) oui.click();
return true;
"""


@pytest.fixture(scope="module")
def nav():
    preparer_firefox()
    gecko, n = demarrer_navigateur()
    try:
        yield n
    finally:
        arreter_navigateur(gecko, n)


@pytest.fixture
def captures(tmp_path):
    dossier = Path(os.environ.get("ATELIER_CAPTURES_BORNE") or tmp_path / "captures")
    dossier.mkdir(parents=True, exist_ok=True)
    return dossier


def _demo(tmp_path, monkeypatch, cacher="vie_scolaire", ros=True):
    app, pont, dossier = client_demo(tmp_path, monkeypatch, ros=ros)
    if cacher:
        salles = charger_salles(dossier)
        for s in salles:
            if s.id == cacher:
                s.etiquettes = list(s.etiquettes or []) + ["hors_borne"]
        enregistrer_salles(dossier, salles)
    return app, pont, dossier


def _mesurer(nav, quoi):
    m = nav.js(MESURE_BORNE)
    assert m["fautes"] == [], f"{quoi} : {m['fautes']}"
    assert m["erreurs"] == [], f"{quoi} : erreurs de la page {m['erreurs']}"
    return m


def _texte(nav, role):
    return nav.js("const e = document.querySelector('[data-role=' + arguments[0] + ']'); "
                  "return e ? e.textContent.replace(/\\u00a0/g, ' ').replace(/\\u2011/g, '-') : null", role)


def _choix(pont):
    return [d for s, d in pont.publies if s == "/accueil/choix"]


@pytest.mark.parametrize("taille", sorted(TAILLES))
def test_parcours_d_un_visiteur(taille, nav, tmp_path, monkeypatch, captures):
    largeur, hauteur = TAILLES[taille]
    app, pont, _ = _demo(tmp_path, monkeypatch)
    with ServeurDemo(app, pont) as serveur:
        ouvrir_borne_cadre(nav, serveur.base, largeur, hauteur)
        attendre_ecran(nav, "salles")
        m = _mesurer(nav, f"{taille}, salles")
        assert m["taille"] == [largeur, hauteur] and m["cartes"] == SALLES_BORNE
        assert nav.js(CHEVRONS_VISIBLES) in (0, len(SALLES_BORNE))       # cartes actives : chevron s'il a la place
        assert _texte(nav, "borne-titre") == "Bonjour ! Où voulez-vous aller ?"
        capture_cadre(nav, captures / f"borne_{taille}_1_salles.png")
        # une salle touchée : la confirmation, dans la page
        nav.js("document.querySelector('[data-salle=b204]').click()")
        nav.attendre("return !document.querySelector('[data-role=confirmation-borne]').hidden", message="confirmation")
        assert _texte(nav, "salle-confirmee") == "« Salle B204 » ?"
        assert nav.js("return document.querySelector('.borne-question').textContent") == "Je vous accompagne à"
        capture_cadre(nav, captures / f"borne_{taille}_2_confirmation.png")
        # cinq appuis rapides sur « Oui » : un seul choix
        nav.js(CINQ_APPUIS)
        nav.attendre("return document.querySelector('[data-role=confirmation-borne]').hidden", message="confirmation fermée")
        time.sleep(0.8)
        assert len(_choix(pont)) == 1 and _choix(pont)[0]["salle"] == "b204" and _choix(pont)[0]["source"] == "borne"
        assert pont.o.etat_courant == "depart"
        # la visite : Suivez-moi avec la distance, l'arrivée, le retour, puis les salles
        pont.guide("en_route", mission="visite", cible="b204", reste_m=16.2, pose=(6.0, 10.0, 0.0))
        attendre_ecran(nav, "suivez_moi")
        nav.attendre("return document.querySelector('[data-role=borne-detail]').textContent.replace(/\\u00a0/g, ' ').replace(/\\u2011/g, '-') === arguments[0]",
                     "Encore 16 m jusqu'à « Salle B204 ».", message="distance restante")
        pont.guide("en_route", mission="visite", cible="b204", reste_m=8.0, pose=(14.0, 13.0, 0.0))
        time.sleep(1.0)
        _mesurer(nav, f"{taille}, suivez-moi")
        assert _texte(nav, "borne-titre") == "Suivez-moi !"
        # corrections de la vague 6 (revue de l'interface, défaut 18) : plus de grande flèche vers la droite (le
        # visiteur pouvait croire qu'il devait aller à droite), trois points qui s'allument tour à tour
        assert nav.js("return [document.querySelectorAll('.borne-en-route .r-point').length, "
                      "!!document.querySelector('.borne-fleche, .f-pointe')]") == [3, False]
        capture_cadre(nav, captures / f"borne_{taille}_3_suivez_moi.png")
        pont.guide("arrive", mission="visite", cible="b204", reste_m=0.0, actif=True, pose=(21.0, 13.0, 1.57))
        attendre_ecran(nav, "arrivee")
        assert _texte(nav, "borne-detail") == "Voici « Salle B204 »."
        capture_cadre(nav, captures / f"borne_{taille}_4_arrivee.png")
        pont.guide("retour", mission="retour", cible="accueil", reste_m=18.0, pose=(18.0, 13.0, 3.1))
        attendre_ecran(nav, "retour")
        assert _texte(nav, "borne-titre") == "Je retourne à l'accueil."
        capture_cadre(nav, captures / f"borne_{taille}_5_retour.png")
        pont.guide("attente")
        attendre_ecran(nav, "salles")
        # occupé (une visite demandée hors de la démo), puis pause : cartes inactives, le message
        pont.guide("en_route", mission="visite", cible="cdi", pose=(4.0, 10.0, 0.0))
        attendre_ecran(nav, "occupe")
        assert nav.js("return Array.from(document.querySelectorAll('[data-salle]')).every((c) => c.disabled)")
        assert nav.js(CHEVRONS_VISIBLES) == 0           # une carte inactive n'invite pas à toucher (défaut 18)
        assert _texte(nav, "borne-titre") == A.TEXTES_BORNE["occupe"]
        capture_cadre(nav, captures / f"borne_{taille}_6_occupe.png")
        pont.entrer("/mouvement/maitre", {"maitre": "pilotage"})
        attendre_ecran(nav, "pause")
        assert nav.js("return Array.from(document.querySelectorAll('[data-salle]')).every((c) => c.disabled)")
        assert nav.js(CHEVRONS_VISIBLES) == 0
        assert _texte(nav, "borne-titre") == "Je fais une petite pause."
        m = _mesurer(nav, f"{taille}, pause")
        capture_cadre(nav, captures / f"borne_{taille}_7_pause.png")
        nav.js("document.querySelector('[data-salle=cdi]').click()")
        time.sleep(0.5)
        assert len(_choix(pont)) == 1 and nav.js("return document.querySelector('[data-role=confirmation-borne]').hidden")
        assert nav.js("return window.erreursBorne") == []


def test_premier_appui_et_son(nav, tmp_path, monkeypatch):
    app, pont, _ = _demo(tmp_path, monkeypatch)
    with ServeurDemo(app, pont) as serveur:
        ouvrir_borne_cadre(nav, serveur.base, *TAILLES["telephone"])
        attendre_ecran(nav, "salles")
        nav.js("document.querySelector('[data-role=borne-titre]').dispatchEvent(new PointerEvent('pointerdown', "
               "{bubbles: true}))")
        nav.attendre("return true", delai=1)
        time.sleep(0.8)
        appuis = [d for s, d in pont.publies if s == "/accueil/commande" and d["action"] == "appui"]
        assert len(appuis) == 1 and appuis[0]["source"] == "borne"
        assert pont.o.etat_courant in ("salutation", "choix")
        ident = "s-20261109-101010-0042"
        pont.recevoir("/voix/son", {"version": 1, "id": ident, "texte": "Bonjour !", "duree_s": 0.5,
                                    "url": f"/api/voix/son/{ident}"})
        src = nav.attendre("const a = document.querySelector('[data-role=borne-son]'); "
                           "return a && a.getAttribute('src') && a.getAttribute('src').indexOf(arguments[0]) >= 0 "
                           "? a.getAttribute('src') : null", ident, message="le son de la borne")
        assert src == f"/api/voix/son/{ident}"
        assert nav.js("return window.erreursBorne.filter((e) => e.indexOf('NotSupported') < 0 "
                      "&& e.indexOf('play') < 0)") == []


def test_mode_operateur(nav, tmp_path, monkeypatch, captures):
    app, pont, dossier = _demo(tmp_path, monkeypatch)
    A.enregistrer_demo(dossier, {"version": 1, "borne": {"code_operateur": "4826"}})
    with ServeurDemo(app, pont) as serveur:
        ouvrir_borne_cadre(nav, serveur.base, *TAILLES["tablette"])
        attendre_ecran(nav, "salles")
        nav.attendre("return !document.querySelector('[data-role=borne-operateur]').hidden", message="bouton opérateur")
        nav.js("document.querySelector('[data-role=borne-operateur]').click()")
        nav.attendre("return !document.querySelector('[data-role=operateur-code]').hidden", message="clavier du code")

        def taper(code):
            nav.js("for (const c of arguments[0]) document.querySelector('[data-touche=\"' + c + '\"]').click();"
                   "document.querySelector('[data-touche=valider]').click();", code)
        taper("1111")
        nav.attendre("const m = document.querySelector('[data-role=code-message]'); return !m.hidden && m.textContent",
                     message="code faux")
        assert _texte(nav, "code-message") == "Code faux."
        time.sleep(0.7)
        taper("4826")
        nav.attendre("return !document.querySelector('[data-role=operateur-actions]').hidden", message="actions")
        actions = nav.js("return Array.from(document.querySelectorAll('[data-role=operateur-actions] [data-action]'))"
                         ".map((b) => b.dataset.action)")
        assert actions == ["pause", "reprendre", "ramener"]           # rien d'autre n'est proposé
        nav.attendre("return document.querySelector('[data-role=operateur-message]').textContent.length > 0",
                     message="message de l'opérateur")
        capture_cadre(nav, captures / "borne_tablette_8_operateur.png")
        nav.js("document.querySelector('[data-action=pause]').click()")
        nav.attendre("return true", delai=1)
        fin = time.monotonic() + 5
        while pont.o.raison != "operateur" and time.monotonic() < fin:
            time.sleep(0.1)
        assert pont.o.raison == "operateur"
        commande = [d for s, d in pont.publies if s == "/accueil/commande"][-1]
        assert commande["action"] == "pause" and commande["source"] == "operateur"
        attendre_ecran(nav, "pause")
        nav.js("document.querySelector('[data-role=fermer-operateur]').click()")
        assert nav.js("return window.erreursBorne") == []


def test_hors_service_et_anglais(nav, tmp_path, monkeypatch, captures):
    app, pont, dossier = _demo(tmp_path, monkeypatch, cacher=None, ros=False)
    with ServeurDemo(app, pont) as serveur:
        for taille, (largeur, hauteur) in TAILLES.items():
            ouvrir_borne_cadre(nav, serveur.base, largeur, hauteur)
            nav.attendre("return document.querySelector('[data-role=borne-titre]').textContent.replace(/\\u00a0/g, ' ').replace(/\\u2011/g, '-') === arguments[0]",
                         A.TEXTES_BORNE["hors_service"], message="hors service")
            _mesurer(nav, f"{taille}, hors service")
            capture_cadre(nav, captures / f"borne_{taille}_0_hors_service.png")
    app, pont, dossier = _demo(tmp_path / "en", monkeypatch, cacher=None)
    A.enregistrer_demo(dossier, {"version": 1, "borne": {"langue": "en"}})
    with ServeurDemo(app, pont) as serveur:
        ouvrir_borne_cadre(nav, serveur.base, *TAILLES["telephone"])
        nav.attendre("return document.querySelector('[data-role=borne-titre]').textContent.replace(/\\u00a0/g, ' ').replace(/\\u2011/g, '-') === arguments[0]",
                     "Hello! Where would you like to go?", message="anglais")
        nav.js("document.querySelector('[data-salle=cdi]').click()")
        nav.attendre("return !document.querySelector('[data-role=confirmation-borne]').hidden", message="confirmation")
        assert _texte(nav, "confirmer-salle") == "Yes, let's go!"
        # corrections de la vague 6 (revue de l'interface, défaut 14) : « Shall I take you to « CDI » ? »
        assert _texte(nav, "salle-confirmee") == "“CDI”?"
        purs = nav.js_async("""const fini = arguments[arguments.length - 1];
          import('/js/borne/textes.js').then((T) => fini([T.questionSalle('fr', 'Salle B204'),
            T.questionSalle('en', 'CDI'), T.questionSalle('de', 'X'), T.insecables('« A » : b ?')]))
            .catch((e) => fini(String(e)));""")
        assert purs == ["«\u00a0Salle B204\u00a0»\u00a0?", "“CDI”?", "«\u00a0X\u00a0»\u00a0?",
                        "«\u00a0A\u00a0»\u00a0: b\u00a0?"], purs
        assert nav.js("return document.documentElement.lang") == "en"
