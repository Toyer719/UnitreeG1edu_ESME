"""L'écran Démo de l'Atelier dans Firefox sans fenêtre (vague 6, sections 13.4, 13.5 et 13.7 du plan) : agent
Borne et orchestrateur.

Le serveur (sans ROS) tourne dans un fil, branché sur la vraie machine d'états de la démo par un faux pont
(test_borne_communs), avec de fausses commandes g1-accueil et g1-voix. Parcours : Équipe › Démo › Lancer la démo
(les deux commandes lancées, l'état « Attend un visiteur » de [data-role=demo-etat]), une visite jouée par le faux
guide (statistiques), « Mettre en pause » puis « Reprendre » depuis le panneau, Équipe › Démo › Borne : l'adresse en
grand ([data-role=adresse-borne]) et son code QR, Échap la ferme, Réglages de la démo : le code opérateur et une
salle cachée enregistrés (demo.yaml, salles.yaml), Arrêter la démo ; window.erreursAtelier vide.
Captures : $ATELIER_CAPTURES_BORNE (sinon le dossier temporaire du test).
"""
import os
import shutil
import time
from pathlib import Path

import pytest

from atelier.lieu import accueil as A
from atelier.lieu import charger_salles

from .test_borne_communs import ServeurDemo, client_demo, ecrire_fausses_commandes
from .test_serveur_navigateur import arreter_navigateur, demarrer_navigateur, ouvrir_espace

pytestmark = pytest.mark.skipif(shutil.which("geckodriver") is None or shutil.which("firefox") is None,
                                reason="geckodriver ou Firefox absent")


@pytest.fixture
def nav():
    gecko, n = demarrer_navigateur()
    try:
        yield n
    finally:
        arreter_navigateur(gecko, n)


def _etat_demo(nav):
    return nav.js("const e = document.querySelector('[data-role=demo-etat]'); return e ? e.dataset.etat : null")


def _statistique(nav, cle):
    return nav.js("const e = document.querySelector('[data-role=demo-statistiques] [data-statistique=' + arguments[0] + "
                  "'] dd'); return e ? e.textContent : null", cle)


def test_ecran_demo(nav, tmp_path, monkeypatch):
    captures = Path(os.environ.get("ATELIER_CAPTURES_BORNE") or tmp_path / "captures")
    captures.mkdir(parents=True, exist_ok=True)
    journal = tmp_path / "appels.txt"
    monkeypatch.setenv("ATELIER_BIN", str(ecrire_fausses_commandes(tmp_path / "bin", journal)))
    app, pont, dossier = client_demo(tmp_path, monkeypatch, nom="essai")
    monkeypatch.setenv("ATELIER_HOTE", "192.168.0.12")      # l'Atelier écoute le réseau (après client_demo)
    monkeypatch.setenv("ATELIER_PORT", "8143")
    etat = app.state.atelier
    etat.simulation = {"lieu": "essai", "etage": "rdc", "dossier": str(dossier), "monde": None, "debut": time.time(),
                       "avertissements": [], "mode": "simu"}
    etat.mode_navigation = lambda: None          # rien ne tourne encore
    pont.muet = True                             # la démo ne tourne pas encore
    pont.recus.pop("/accueil/etat", None)
    with ServeurDemo(app, pont) as serveur:
        nav.taille(1600, 1000)
        ouvrir_espace(nav, serveur.base, mode="simu", lieu="essai")
        # corrections de la vague 6 (revue de l'interface, défaut 13) : sans guide, la phrase du mode de l'Atelier
        nav.commande("demo.lancer")
        sans_guide = nav.attendre("const e = Array.from(document.querySelectorAll('.message-erreur')).find((x) => "
                                  "x.textContent.indexOf('besoin du guide') >= 0); return e ? e.textContent : null",
                                  message="la démo a besoin du guide")
        assert "Simuler › Lancer" in sans_guide and "Naviguer" not in sans_guide, sans_guide
        etat.mode_navigation = lambda: "simu"
        nav.commande("demo.lancer")
        nav.attendre("const b = document.querySelector('[data-role=demo-arreter]'); return !!b && !b.hidden",
                     message="démo lancée")
        pont.muet = False                        # le nœud (ici la machine d'états du faux pont) publie son état
        nav.ecran("demo")
        nav.attendre("const e = document.querySelector('[data-role=demo-etat]'); return e && e.dataset.etat === 'attente'",
                     message="la démo attend un visiteur")
        appels = journal.read_text() if journal.exists() else ""
        assert "g1-accueil --lieu" in appels and "g1-voix --lieu" in appels and "--sortie borne" in appels
        nav.attendre("return !document.querySelector('[data-role=demo-arreter]').hidden", message="Arrêter visible")
        # une visite jouée par le faux guide : les statistiques suivent
        pont.publier_json("/accueil/commande", A.message_commande("appui", "test", "t-1"))
        pont.publier_json("/accueil/choix", A.message_choix("b204", "borne", "t-2"))
        pont.guide("en_route", mission="visite", cible="b204", reste_m=12.0, pose=(8.0, 10.0, 0.0))
        nav.attendre("const e = document.querySelector('[data-role=demo-visite]'); return e && !e.hidden && "
                     "e.textContent.indexOf('Salle B204') >= 0", message="la visite dans le panneau")
        assert _etat_demo(nav) == "accompagnement"
        nav.capture(captures / "atelier_demo_1_visite.png")
        pont.guide("arrive", mission="visite", cible="b204", reste_m=0.0, actif=True, pose=(21.0, 13.0, 1.57))
        nav.attendre("const e = document.querySelector('[data-statistique=visites_reussies] dd'); "
                     "return e && e.textContent === '1'", message="statistique des visites réussies")
        assert _statistique(nav, "visiteurs") == "1"
        pont.guide("retour", mission="retour", cible="accueil", pose=(15.0, 10.0, 3.1))
        pont.guide("attente")
        nav.attendre("return document.querySelector('[data-role=demo-etat]').dataset.etat === 'attente'", message="retour")
        # pause et reprise depuis le panneau
        nav.clic("[data-action=pause]:not([hidden])")
        nav.attendre("return document.querySelector('[data-role=demo-etat]').dataset.etat === 'pause'", message="pause")
        assert pont.o.raison == "operateur"
        # corrections de la vague 6 (défaut 11) : les guillemets du message gardent leur espace insécable
        message = nav.js("return document.querySelector('[data-role=demo-message]').textContent")
        assert "«\u00a0Reprendre\u00a0»" in message and "« " not in message, message
        assert [d for s, d in pont.publies if s == "/accueil/commande"][-1]["source"] == "atelier"
        nav.clic("[data-action=reprendre]:not([hidden])")
        nav.attendre("return document.querySelector('[data-role=demo-etat]').dataset.etat === 'attente'", message="reprise")
        # l'adresse de la borne en grand, et son code QR
        nav.commande("demo.borne")
        adresse = nav.attendre("const e = document.querySelector('[data-role=adresse-borne]'); "
                               "return e && e.textContent.indexOf('8143') >= 0 ? e.textContent : null", message="adresse")
        assert adresse == "http://192.168.0.12:8143/borne"
        assert nav.js("return !!document.querySelector('[data-role=qr-borne] svg.qr .qr-modules')")
        nav.capture(captures / "atelier_demo_2_borne.png")
        nav.clic("[data-role=fermer-borne]")
        nav.attendre("return !document.querySelector('[data-role=demo-borne]')", message="✗ ferme l'adresse")
        nav.commande("demo.borne")
        nav.attendre("return !!document.querySelector('[data-role=demo-borne]')", message="l'adresse de nouveau")
        nav.commande("demo.borne")
        nav.attendre("return !document.querySelector('[data-role=demo-borne]')", message="Borne une seconde fois : fermée")
        # les réglages : un code opérateur et une salle cachée de la borne
        nav.commande("demo.reglages")
        nav.attendre("return document.querySelector('[data-role=demo-reglages]').open", message="réglages ouverts")
        nav.champ("[data-role=code-operateur]", "4826")
        nav.js("const c = document.querySelector('[data-salle-borne=cdi]'); c.checked = false;"
               "c.dispatchEvent(new Event('change', {bubbles: true}));")
        nav.attendre("return !document.querySelector('[data-role=demo-enregistrer]').disabled", message="Enregistrer actif")
        nav.capture(captures / "atelier_demo_3_reglages.png")
        nav.clic("[data-role=demo-enregistrer]")
        fin = time.monotonic() + 5
        while not (dossier / "demo.yaml").exists() and time.monotonic() < fin:
            time.sleep(0.1)
        assert A.charger_demo(dossier)["borne"]["code_operateur"] == "4826"
        nav.attendre("return document.querySelector('[data-role=demo-enregistrer]').disabled", message="enregistré")
        cdi = next(s for s in charger_salles(dossier) if s.id == "cdi")
        assert "hors_borne" in (cdi.etiquettes or [])
        # arrêter la démo
        nav.commande("demo.arreter")
        pont.muet = True                         # le nœud arrêté ne publie plus : son état vieillit (3 s)
        nav.attendre("return !document.querySelector('[data-role=demo-lancer]').hidden", delai=10,
                     message="démo arrêtée")
        assert _etat_demo(nav) == "arretee"
        assert nav.js("return window.erreursAtelier") == []
