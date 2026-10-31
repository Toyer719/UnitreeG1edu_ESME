#!/usr/bin/env python3
"""Outils des critères 31 (accueil, espace de travail et défilement) et 36 (ARRÊT global, partie navigateur)
de la section 12.10 du plan : agent Coquille. Firefox sans fenêtre, piloté par geckodriver (comme
atelier/tests/test_serveur_navigateur.py) ; les mesures viennent de atelier/tests/test_coque_communs.py.

  outils_coque_e2e.py critere-31 --api URL [--tailles 1366x768,1600x1000,1920x1080] [--modes simu,reel,repetition]
        1. accueil : les deux cartes, le demo dans la liste (présélectionné par atelier.lieu), Ouvrir ;
           Simulation + demo + Ouvrir : [data-mode=simu], 4 onglets, aucune commande pilotage.* ; retour à
           l'accueil, Robot réel + « Répétition sans robot » : [data-mode=repetition], 5 onglets ; les
           vérifications du mode Réel avec leur data-etat ; aucune boîte native ;
        2. pour chaque taille, chaque mode, chaque onglet et chaque commande qui n'est pas Avancé : la page ne
           défile pas, les six zones sont entières, chaque élément cliquable est atteignable, entier et non
           recouvert, ARRÊT visible et cliquable ;
        3. les anciennes adresses (#salles, #simulation, #scan, #pilotage, #camera) mènent à leur écran ;
        4. le thème clair change data-theme et atelier.theme, la vue 3D reste sombre ;
        5. revue de la vague 5 : l'arbre replié se rouvre (languette « Le lieu »), le Plan 2D ouvert après la 3D
           montre les salles, la barre d'outils de la répétition ne se chevauche pas ;
        6. window.erreursAtelier reste vide.
  outils_coque_e2e.py captures --api URL --sortie DOSSIER [--taille 1600x1000]
        captures d'écran : l'accueil (deux modes), chaque onglet en Simulation et en Réel (répétition), en
        thème sombre et en thème clair, et l'accueil en 1366 × 768.
  outils_coque_e2e.py contrastes --api URL [--taille 1600x1000]
        les textes affichés sous le seuil AA (4,5:1 ; 3:1 pour le grand texte) : couleur calculée de chaque
        texte sur son fond réel, à l'accueil et dans chaque onglet, en thèmes sombre et clair (code 1 s'il y
        en a).
  outils_coque_e2e.py arret-navigateur --api URL --lieu ID [--mode repetition|reel|simu] [--attendre-verrou]
        (critère 36) le clic sur [data-role=arret] et la touche Échap envoient POST /api/arret ; en Réel ou en
        répétition, avec --attendre-verrou, le bouton passe à « Débloquer » (data-etat=bloque).

Codes de sortie : 0 réussi, 1 échoué, 77 en attente (Firefox sans fenêtre absent). Chaque étape réussie écrit
une ligne « ok : … ».
"""
import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

import pytest  # noqa: E402  (demarrer_navigateur signale un Firefox absent par pytest.skip)

from atelier.tests import test_coque_communs as C  # noqa: E402
from atelier.tests.test_serveur_navigateur import arreter_navigateur, demarrer_navigateur  # noqa: E402

EN_ATTENTE = 77
TAILLES = "1366x768,1600x1000,1920x1080"


class Echec(Exception):
    pass


def ok(texte):
    print("ok : " + texte, flush=True)


def dire(texte):
    print("   " + texte, flush=True)


def verifier(condition, texte):
    if not condition:
        raise Echec(texte)


def lire_api(api, chemin):
    with urllib.request.urlopen(api + chemin, timeout=20) as r:
        return json.loads(r.read())


class Firefox:
    """Firefox sans fenêtre (geckodriver), fermé à la sortie du bloc with ; absent : en attente (77)."""

    def __init__(self, prefs=None):
        self.prefs = prefs
        self.gecko = self.nav = None

    def __enter__(self):
        try:
            self.gecko, self.nav = demarrer_navigateur(self.prefs)
        except pytest.skip.Exception as e:
            print(f"EN ATTENTE : Firefox sans fenêtre indisponible ({e})", flush=True)
            sys.exit(EN_ATTENTE)
        return self.nav

    def __exit__(self, *exc):
        arreter_navigateur(self.gecko, self.nav)
        return False


def taille(texte):
    largeur, hauteur = texte.lower().split("x")
    return int(largeur), int(hauteur)


def erreurs_page(nav):
    return nav.js("return window.erreursAtelier || []")


# ---------------------------------------------------------------- critère 31

def mesures(nav, api, tailles, modes, avec_commandes=True):
    fautes = []
    for t in tailles:
        largeur, hauteur = taille(t)
        nav.taille(largeur, hauteur)
        for mode in modes:
            debut = time.monotonic()
            C.ouvrir_espace(nav, api, mode)
            iw, ih = nav.js("return [window.innerWidth, window.innerHeight]")
            verifier(abs(iw - largeur) <= 2 and abs(ih - hauteur) <= 2, f"fenêtre de {iw} × {ih} au lieu de {t}")
            f, n, e = C.balayer(nav, f"{t} {mode}", avec_commandes=avec_commandes)
            f += [f"{t} {mode} : boîte native {x}" for x in C.fenetres_natives(nav)]
            fautes += f
            ok(f"{largeur} × {hauteur}, {mode} : {n} mesures, {e} éléments cliquables vérifiés, "
               f"{len(f)} faute(s) ({time.monotonic() - debut:.0f} s)")
            for x in f[:12]:
                dire(x)
    return fautes


def critere_31(args):
    tailles = [t for t in args.tailles.split(",") if t]
    modes = [m for m in args.modes.split(",") if m]
    liaison = lire_api(args.api, "/api/robot/liaison")
    with Firefox() as nav:
        nav.taille(*taille(tailles[0]))
        for phrase in C.parcours_accueil(nav, args.api, cable_attendu="ok" if liaison["cable"] else "non"):
            ok(phrase)
        fautes = mesures(nav, args.api, tailles, modes, avec_commandes=not args.sans_commandes)
        ok(C.parcours_anciens_hash(nav, args.api))
        ok(C.parcours_theme(nav, args.api))
        nav.taille(*taille(tailles[0]))
        for phrase in C.parcours_revue_v5(nav, args.api):
            ok(phrase)
        erreurs = erreurs_page(nav)
    verifier(not fautes, f"{len(fautes)} faute(s) de mise en page, dont : " + " | ".join(fautes[:6]))
    verifier(not erreurs, f"erreurs JavaScript dans la page : {erreurs[:5]}")
    ok("aucune erreur dans la page (window.erreursAtelier vide)")
    return 0


# ---------------------------------------------------------------- captures

def capturer_espace(nav, api, mode, dossier, prefixe, theme_page):
    C.ouvrir_espace(nav, api, mode, memoire={"atelier.theme": theme_page})
    for o in C.onglets(nav):
        nav.js("document.querySelector('[data-onglet=\"' + arguments[0] + '\"]').click()", o)
        C.attendre_pret(nav)
        time.sleep(1.5)                     # la carte 3D et les panneaux se dessinent
        nav.capture(dossier / f"{prefixe}_{o}.png")


def captures(args):
    dossier = Path(args.sortie)
    dossier.mkdir(parents=True, exist_ok=True)
    with Firefox() as nav:
        nav.taille(*taille(args.taille))
        for theme_page in ("sombre", "clair"):
            C.charger(nav, args.api + "/", C.ACCUEIL, "accueil")
            nav.js("localStorage.clear(); localStorage.setItem('atelier.lieu', 'demo');"
                   "localStorage.setItem('atelier.theme', arguments[0]);", theme_page)
            C.charger(nav, args.api + "/", "return !!document.querySelector('[data-lieu=demo]')", "accueil")
            time.sleep(0.8)
            nav.capture(dossier / f"accueil_simulation_{theme_page}.png")
            nav.clic("[data-role=mode-reel]")
            time.sleep(1.5)
            nav.capture(dossier / f"accueil_reel_{theme_page}.png")
            for mode, nom in (("simu", "simulation"), ("repetition", "reel")):
                capturer_espace(nav, args.api, mode, dossier, f"{nom}_{theme_page}", theme_page)
        nav.taille(1366, 768)
        C.charger(nav, args.api + "/", C.ACCUEIL, "accueil")
        nav.js("localStorage.clear(); localStorage.setItem('atelier.lieu', 'demo');")
        C.charger(nav, args.api + "/", "return !!document.querySelector('[data-lieu=demo]')", "accueil")
        time.sleep(0.8)
        nav.capture(dossier / "accueil_1366x768.png")
        C.ouvrir_espace(nav, args.api, "repetition")
        nav.js("document.querySelector('[data-onglet=naviguer]').click()")
        C.attendre_pret(nav)
        time.sleep(1.5)
        nav.capture(dossier / "reel_naviguer_1366x768.png")
        erreurs = erreurs_page(nav)
    ok(f"captures dans {dossier} ({len(list(dossier.glob('*.png')))} images)")
    verifier(not erreurs, f"erreurs JavaScript dans la page : {erreurs[:5]}")
    return 0


# ---------------------------------------------------------------- critère 36 (navigateur)

def arret_navigateur(args):
    """Le clic sur ARRÊT et la touche Échap envoient POST /api/arret ; en Réel, « Débloquer » ensuite."""
    with Firefox() as nav:
        nav.taille(1366, 768)
        for phrase in C.parcours_arret(nav, args.api, args.mode, lieu=args.lieu, verrou=args.attendre_verrou):
            ok(phrase)
        erreurs = erreurs_page(nav)
    verifier(not erreurs, f"erreurs JavaScript dans la page : {erreurs[:5]}")
    return 0


# ---------------------------------------------------------------- contrastes affichés

def contrastes_affiches(args):
    """Les textes affichés sous le seuil AA, à l'accueil et dans chaque onglet, en thèmes sombre et clair."""
    trouves = {}
    with Firefox() as nav:
        nav.taille(*taille(args.taille))
        for theme_page in ("sombre", "clair"):
            C.charger(nav, args.api + "/", C.ACCUEIL, "accueil")
            nav.js("localStorage.clear(); localStorage.setItem('atelier.lieu', 'demo');"
                   "localStorage.setItem('atelier.theme', arguments[0]);", theme_page)
            for mode_accueil in ("mode-simu", "mode-reel"):
                C.charger(nav, args.api + "/", "return !!document.querySelector('[data-lieu=demo]')", "accueil")
                nav.clic(f"[data-role={mode_accueil}]")
                time.sleep(1.2)
                for f in C.contrastes(nav)["faibles"]:
                    trouves.setdefault(f, []).append(f"{theme_page} accueil {mode_accueil}")
            for mode in ("simu", "repetition"):
                C.ouvrir_espace(nav, args.api, mode, memoire={"atelier.theme": theme_page})
                for o in C.onglets(nav):
                    nav.js("document.querySelector('[data-onglet=\"' + arguments[0] + '\"]').click()", o)
                    C.attendre_pret(nav)
                    time.sleep(1.0)
                    for f in C.contrastes(nav)["faibles"]:
                        trouves.setdefault(f, []).append(f"{theme_page} {mode} › {o}")
    for f, ou in sorted(trouves.items()):
        dire(f"{f}  [{', '.join(ou[:3])}{' …' if len(ou) > 3 else ''}]")
    ok(f"{len(trouves)} texte(s) sous le seuil AA")
    return 0 if not trouves else 1


def main(argv=None):
    p = argparse.ArgumentParser(prog="outils_coque_e2e.py", description=__doc__.split("\n")[0])
    sous = p.add_subparsers(dest="action", required=True)
    s = sous.add_parser("critere-31")
    s.add_argument("--api", required=True)
    s.add_argument("--tailles", default=TAILLES)
    s.add_argument("--modes", default="simu,reel,repetition")
    s.add_argument("--sans-commandes", action="store_true", help="seulement les onglets (plus court)")
    s = sous.add_parser("captures")
    s.add_argument("--api", required=True)
    s.add_argument("--sortie", required=True)
    s.add_argument("--taille", default="1600x1000")
    s = sous.add_parser("contrastes")
    s.add_argument("--api", required=True)
    s.add_argument("--taille", default="1600x1000")
    s = sous.add_parser("arret-navigateur")
    s.add_argument("--api", required=True)
    s.add_argument("--lieu", default="demo")
    s.add_argument("--mode", default="repetition", choices=["simu", "reel", "repetition"])
    s.add_argument("--attendre-verrou", action="store_true")
    args = p.parse_args(argv)
    fonctions = {"critere-31": critere_31, "captures": captures, "arret-navigateur": arret_navigateur,
                 "contrastes": contrastes_affiches}
    try:
        return fonctions[args.action](args)
    except (Echec, AssertionError, pytest.fail.Exception) as e:
        print(f"ÉCHEC : {e}", flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
