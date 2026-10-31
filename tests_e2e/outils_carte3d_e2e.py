#!/usr/bin/env python3
"""Outils du critère 32 (placer l'accueil et une salle dans la carte 3D, section 12.10 du plan) : agent Carte 3D.

  outils_carte3d_e2e.py nuage --lieu DOSSIER
        écrit cartes/rdc.nuage.bin + .json (atelier.lieu.nuage.ecrire_nuage) depuis le monde de l'étage :
        murs et objets échantillonnés tous les 5 cm, sol tous les 10 cm, plafond clairsemé à 2,6 m
  outils_carte3d_e2e.py parcours --api URL --lieu DOSSIER [--captures DOSSIER]
        dans Firefox sans fenêtre (WebGL), par la coque : Réel (répétition) › Placer, le nuage dans la vue 3D,
        l'accueil posé en (3,0 ; 9,5) et tourné vers l'est, la salle « Essai 3D » en (12,0 ; 4,0) tournée vers
        −90°, ✓ OK, puis les fichiers ; le Plan 2D aux mêmes coordonnées et une salle déplacée en 2D retrouvée
        en 3D ; Dessus, Iso, Face, Recadrer ; la molette vers le pointeur ; Annuler et Rétablir d'un placement
  outils_carte3d_e2e.py sans-webgl --api URL
        WebGL coupé (préférence webgl.disabled) : [data-role=carte3d-sans-webgl], le Plan 2D reste utilisable

Codes de sortie : 0 réussi, 1 échoué, 77 en attente (une pièce d'un autre agent manque : la coque, sa vue
3D ou ses commandes ; ou Firefox sans fenêtre). Chaque étape réussie écrit une ligne « ok : … ».
"""
import argparse
import json
import math
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

import pytest  # noqa: E402  (les outils de test de la carte 3D en ont besoin pour « skip »)
import yaml  # noqa: E402

from atelier.tests import test_carte3d_communs as C  # noqa: E402


class EnAttente(Exception):
    """Une pièce d'un autre agent manque : le critère est « en attente » (77)."""


class Echec(Exception):
    pass


def ok(texte):
    print("ok : " + texte, flush=True)


def verifier(condition, texte):
    if not condition:
        raise Echec(texte)


def attendre(nav, script, *args, delai=20.0):
    """Valeur vraie du script, ou None après le délai (sans échouer)."""
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        v = nav.js(script, *args)
        if v:
            return v
        time.sleep(0.15)
    return None


def erreurs_page(nav):
    return nav.js("return window.erreursAtelier || []")


def lire_yaml(chemin):
    return yaml.safe_load(chemin.read_text(encoding="utf-8"))


def ouvrir_firefox(prefs=None):
    try:
        return C.ouvrir_firefox(prefs, largeur=1600, hauteur=1000)
    except pytest.skip.Exception as e:            # geckodriver ou Firefox absent
        raise EnAttente(f"Firefox sans fenêtre : {e}") from None


def ouvrir_placer(nav, api):
    """L'espace de travail en Réel avec la répétition, onglet Placer, écran Salles (ancien hash #salles)."""
    nav.ouvrir(api + "/")
    nav.js("try { localStorage.setItem('atelier.mode', 'reel'); localStorage.setItem('atelier.repetition', '1');"
           "localStorage.setItem('atelier.lieu', 'demo'); localStorage.setItem('atelier.etage', 'rdc');"
           "localStorage.removeItem('atelier.calques'); } catch (e) {}")
    nav.ouvrir(api + "/?recharger=1#salles")
    if not attendre(nav, "return document.querySelector('[data-role=espace]')", delai=20):
        raise EnAttente("la coque n'affiche pas l'espace de travail ([data-role=espace]) : agent Coquille")
    mode = nav.js("return document.querySelector('[data-role=espace]').getAttribute('data-mode')")
    verifier(mode == "repetition", f"Réel avec la répétition attendu, data-mode = {mode}")
    if not attendre(nav, "return document.querySelector('[data-ecran=salles]')", delai=20):
        raise EnAttente("l'écran Salles ([data-ecran=salles]) ne s'ouvre pas dans Placer : agent Coquille")
    for c in ("salles.accueil", "salles.salle"):
        if not attendre(nav, "return document.querySelector('[data-commande=\"' + arguments[0] + '\"]')", c, delai=10):
            raise EnAttente(f"la commande {c} n'est pas dans le ruban : agent Coquille")


def choisir_vue(nav, nom):
    b = nav.js("return !!document.querySelector('[data-role=barre-vue] [data-vue=\"' + arguments[0] + '\"]')", nom)
    if not b:
        raise EnAttente(f"la barre de la vue n'a pas le bouton [data-vue={nom}] : agent Coquille")
    nav.js("document.querySelector('[data-role=barre-vue] [data-vue=\"' + arguments[0] + '\"]').click()", nom)
    time.sleep(0.3)


def carte_prete(nav, points):
    """La carte 3D de la coque, avec WebGL et le nuage de l'en-tête (servi par la route, ou à défaut par
    le remplacement de fetch quand la route répond 501, section 12.9)."""
    if not attendre(nav, "return window.carte3d && window.carte3d.etat && window.carte3d.etat().webgl", delai=20):
        raise EnAttente("la vue 3D de la coque ne crée pas la carte 3D (window.carte3d avec WebGL) : agent Coquille")
    if attendre(nav, "return window.carte3d.etat().points === arguments[0]", points, delai=20):
        return "route"
    return None


def cadrer(nav, bornes, vue="dessus"):
    nav.js("window.carte3d.vue(arguments[0]); window.carte3d.recadrer(arguments[1]);", vue, bornes)
    C.attendre_camera(nav)


def glisser_sol(nav, points):
    C.glisser(nav, [C.vers_ecran(nav, x, y) for x, y in points])
    time.sleep(0.25)


def cliquer_ok(nav):
    if not nav.js("const b = document.querySelector('[data-role=panneau] [data-role=ok]'); if (!b || b.disabled) "
                  "return false; b.click(); return true;"):
        raise EnAttente("le panneau n'a pas de bouton ✓ OK ([data-role=ok]) actif : agent Coquille")


def champ_nom(nav, valeur):
    """Écrit le nom dans le champ « Nom » du panneau (le premier champ texte de la salle choisie)."""
    fait = nav.js("""
      const champs = Array.from(document.querySelectorAll('[data-role=panneau] label'));
      const l = champs.find((x) => /^Nom/.test((x.querySelector('.champ-libelle') || x).textContent.trim()));
      const c = l ? l.querySelector('input') : document.querySelector('[data-role=panneau] input[type=text]');
      if (!c) return false;
      c.value = arguments[0];
      c.dispatchEvent(new Event('input', {bubbles: true}));
      c.dispatchEvent(new Event('change', {bubbles: true}));
      return true;""", valeur)
    if not fait:
        raise EnAttente("le panneau de la salle n'a pas de champ « Nom » : agent Coquille")


def attendre_fichier(f, delai=10):
    """Valeur de f() (qui lit les fichiers du lieu) dès qu'elle est vraie, ou None après le délai."""
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        try:
            v = f()
            if v:
                return v
        except (OSError, KeyError, TypeError, yaml.YAMLError):
            pass
        time.sleep(0.2)
    return None


def salle_du_fichier(dossier, predicat, delai=10):
    return attendre_fichier(lambda: next((s for s in lire_yaml(dossier / "salles.yaml") if predicat(s)), None), delai)


def principal_de(salles):
    marquees = [s for s in salles if "principal" in (s.get("etiquettes") or [])]
    if len(marquees) == 1:
        return marquees[0]
    return next((s for s in salles if s["id"] == "accueil"), None)


def principal_en(dossier, x, y):
    """Le point principal de salles.yaml, s'il est à 5 cm de (x, y) ; sinon None."""
    p = principal_de(lire_yaml(dossier / "salles.yaml"))
    return p if p and math.dist((p["pose"]["x"], p["pose"]["y"]), (x, y)) <= 0.05 else None


def marqueurs_2d(nav, bornes):
    """Centres des marqueurs des salles du Plan 2D, en mètres : l'image de la carte (img.plan-image-carte)
    occupe exactement les bornes de GET …/carte.yaml (lat = y, lng = x) ; {titre: (x, y)}."""
    return nav.js("""
      const b = arguments[0];
      const img = document.querySelector('[data-role=vue-plan] img.plan-image-carte, img.plan-image-carte');
      if (!img) return null;
      const r = img.getBoundingClientRect();
      if (r.width < 10) return null;
      const sortie = {};
      document.querySelectorAll('[data-role=vue-plan] .leaflet-marker-icon.salle').forEach((m) => {
        const q = m.getBoundingClientRect();
        const cx = q.left + q.width / 2, cy = q.top + q.height / 2;
        sortie[m.getAttribute('title') || ''] = [b.xmin + (cx - r.left) / r.width * (b.xmax - b.xmin),
                                                 b.ymax - (cy - r.top) / r.height * (b.ymax - b.ymin)];
      });
      return sortie;""", bornes)


# ---------------------------------------------------------------- étapes

def parcours(api, dossier, captures):
    entete = json.loads((dossier / "cartes" / "rdc.nuage.json").read_text(encoding="utf-8"))
    route = C.statut_http(api, "/api/lieux/demo/etages/rdc/nuage")
    nav, gecko = ouvrir_firefox()
    try:
        if not C.webgl_disponible(nav):
            raise EnAttente(C.RAISON_SANS_WEBGL)
        ouvrir_placer(nav, api)
        choisir_vue(nav, "3d")
        if carte_prete(nav, entete["points"]) is None:
            verifier(route != 200, "la route du nuage répond, mais la vue 3D ne montre pas ses "
                                   f"{entete['points']} points : {nav.js('return window.carte3d.etat().points')}")
            nav.js(C.FETCH_NUAGE, C.nuage_en_base64(dossier), C.entetes_http(entete))
            r = nav.js_async("const fin = arguments[arguments.length - 1];"
                             "window.carte3d.chargerNuage('/api/lieux/demo/etages/rdc/nuage')"
                             ".then((r) => fin(r.points), (e) => fin(e.message))")
            verifier(r == entete["points"], f"nuage de test non affiché : {r}")
            ok(f"nuage de test servi par le remplacement de fetch (la route répond {route})")
        e = nav.js("return window.carte3d.etat()")
        verifier(e["webgl"] and e["points"] == entete["points"], f"carte 3D : {e}")
        ok(f"Réel (répétition) › Placer : la vue 3D montre le nuage ({e['points']} points, WebGL)")
        if captures:
            nav.capture(captures / "critere32_placer.png")

        # l'accueil, posé en (3,0 ; 9,5), tourné vers (4,0 ; 9,5)
        nav.js("document.querySelector('[data-commande=\"salles.accueil\"]').click()")
        if not attendre(nav, "return window.carte3d.etat().outil === 'accueil'", delai=5):
            raise EnAttente("la commande salles.accueil ne règle pas l'outil « accueil » de la carte 3D : agent Coquille")
        cadrer(nav, {"xmin": 0, "ymin": 2, "xmax": 14, "ymax": 12})
        glisser_sol(nav, [(3.0, 9.5), (3.5, 9.5), (4.0, 9.5)])
        cliquer_ok(nav)
        attendre_fichier(lambda: principal_en(dossier, 3.0, 9.5))
        p = principal_de(lire_yaml(dossier / "salles.yaml"))
        verifier(p is not None and math.dist((p["pose"]["x"], p["pose"]["y"]), (3.0, 9.5)) <= 0.05
                 and abs(math.degrees(p["pose"]["theta"])) <= 2, f"point principal dans salles.yaml : {p}")
        lieu = lire_yaml(dossier / "lieu.yaml")["accueil"]
        verifier(math.dist((lieu["x"], lieu["y"]), (3.0, 9.5)) <= 0.05 and abs(math.degrees(lieu["theta"])) <= 2,
                 f"accueil de lieu.yaml : {lieu}")
        depart = lire_yaml(dossier / "mondes" / "rdc.monde.yaml")["depart_robot"]
        verifier(math.dist((depart["x"], depart["y"]), (3.0, 9.5)) <= 0.05 and abs(math.degrees(depart["theta"])) <= 2,
                 f"depart_robot du monde : {depart}")
        ok("accueil posé en 3D en (3,0 ; 9,5 ; 0°) : salles.yaml, lieu.yaml et depart_robot")

        # la salle « Essai 3D », posée en (12,0 ; 4,0) et tournée vers −90°
        nav.js("document.querySelector('[data-commande=\"salles.salle\"]').click()")
        if not attendre(nav, "return window.carte3d.etat().outil === 'salle'", delai=5):
            raise EnAttente("la commande salles.salle ne règle pas l'outil « salle » de la carte 3D : agent Coquille")
        avant = nav.js("return window.carte3d.etat().salles")
        glisser_sol(nav, [(12.0, 4.0), (12.0, 3.5), (12.0, 3.0)])
        verifier(attendre(nav, "return window.carte3d.etat().salles === arguments[0] + 1", avant, delai=5),
                 "la nouvelle salle n'apparaît pas dans la carte 3D")
        champ_nom(nav, "Essai 3D")
        cliquer_ok(nav)
        essai = salle_du_fichier(dossier, lambda s: s.get("nom") == "Essai 3D")
        verifier(essai is not None, "« Essai 3D » n'est pas dans salles.yaml après ✓ OK")
        verifier(math.dist((essai["pose"]["x"], essai["pose"]["y"]), (12.0, 4.0)) <= 0.05
                 and abs(math.degrees(essai["pose"]["theta"]) + 90) <= 2, f"pose de « Essai 3D » : {essai}")
        noeud = lire_yaml(dossier / "itineraires.yaml")["noeuds"].get(essai["id"])
        verifier(noeud is not None and math.dist((noeud["x"], noeud["y"]), (12.0, 4.0)) <= 0.05,
                 f"nœud {essai['id']} dans itineraires.yaml : {noeud}")
        ok(f"salle « Essai 3D » posée en 3D en (12,0 ; 4,0 ; −90°), id {essai['id']}, avec son nœud")
        if captures:
            nav.capture(captures / "critere32_apres_poses.png")

        # Plan 2D : mêmes coordonnées ; une salle déplacée en 2D retrouvée en 3D
        bornes = C.lire_api(api, "/api/lieux/demo/etages/rdc/carte.yaml")["bornes"]
        choisir_vue(nav, "plan")
        m = None
        fin = time.monotonic() + 15
        while time.monotonic() < fin:
            m = marqueurs_2d(nav, bornes)
            if m and any("Essai 3D" in k for k in m) and len(m) >= 7:
                break
            time.sleep(0.3)
        if not m:
            raise EnAttente("le Plan 2D de l'écran Salles n'affiche pas sa carte (img.plan-image-carte) : agent Coquille")
        essai_2d = next((v for k, v in m.items() if k.startswith("Essai 3D")), None)
        accueil_2d = next((v for k, v in m.items() if "principal" in k or k.startswith(p["nom"])), None)
        verifier(essai_2d is not None and math.dist(essai_2d, (12.0, 4.0)) <= 0.05,
                 f"marqueur 2D de « Essai 3D » : {essai_2d}")
        verifier(accueil_2d is not None and math.dist(accueil_2d, (3.0, 9.5)) <= 0.05,
                 f"marqueur 2D de l'accueil : {accueil_2d} ({list(m)})")
        ok("Plan 2D : l'accueil et « Essai 3D » aux mêmes coordonnées (lat = y, lng = x, à 5 cm)")
        # b204 glissée dans le Plan 2D (vers le sud-ouest), puis ✓ OK ; d'abord amenée dans la vue
        # par l'arbre du lieu (clic : choisie, et le Plan 2D se centre dessus)
        nav.js("const n = document.querySelector('[data-noeud=\"salle:b204\"]'); if (n) n.click();")
        b204 = attendre(nav, """
          const m = Array.from(document.querySelectorAll('[data-role=vue-plan] .leaflet-marker-icon.salle'))
            .find((x) => (x.getAttribute('title') || '').startsWith('Salle B204'));
          const v = document.querySelector('[data-role=vue-plan]');
          if (!m || !v) return null;
          const q = m.getBoundingClientRect(), r = v.getBoundingClientRect();
          const c = [q.left + q.width / 2, q.top + q.height / 2];
          return c[0] > r.left + 60 && c[0] < r.right - 60 && c[1] > r.top + 60 && c[1] < r.bottom - 60 ? c : null;""",
                        delai=10)
        verifier(b204 is not None, "marqueur 2D de « Salle B204 » introuvable dans la vue "
                                   "(clic dans l'arbre sans effet ?)")
        arrivee = (b204[0] - 80, b204[1] + 60)          # vers le sud-ouest, à n'importe quel zoom du plan
        C.actions(nav, [{"type": "pointer", "id": "souris", "parameters": {"pointerType": "mouse"}, "actions": [
            {"type": "pointerMove", "duration": 0, "x": int(round(b204[0])), "y": int(round(b204[1])), "origin": "viewport"},
            {"type": "pointerDown", "button": 0},
            {"type": "pointerMove", "duration": 150, "x": int(round((b204[0] + arrivee[0]) / 2)),
             "y": int(round((b204[1] + arrivee[1]) / 2)), "origin": "viewport"},
            {"type": "pointerMove", "duration": 150, "x": int(round(arrivee[0])), "y": int(round(arrivee[1])),
             "origin": "viewport"},
            {"type": "pointerUp", "button": 0}]}])
        time.sleep(0.4)
        cliquer_ok(nav)
        deplacee = salle_du_fichier(dossier, lambda s: s["id"] == "b204" and math.dist(
            (s["pose"]["x"], s["pose"]["y"]), (21.0, 13.0)) > 0.2)
        verifier(deplacee is not None, "b204 glissée dans le Plan 2D n'a pas bougé dans salles.yaml")
        choisir_vue(nav, "3d")
        attendre(nav, "return window.carte3d && window.carte3d.etat().webgl", delai=10)
        C.attendre_camera(nav)
        x, y = deplacee["pose"]["x"], deplacee["pose"]["y"]
        trouve = attendre(nav, """
          const c = window.carte3d; const a = c.positionRepere('salle', 'b204'); const b = c.versEcran(arguments[0], arguments[1], 0);
          return a && b && Math.hypot(a.x - b.x, a.y - b.y) <= 3 ? [a, b] : null;""", x, y, delai=10)
        verifier(trouve, f"b204 déplacée en 2D en ({x} ; {y}) n'est pas à sa place dans la vue 3D")
        ok(f"b204 déplacée dans le Plan 2D en ({x:.2f} ; {y:.2f}) : retrouvée en 3D à 3 pixels près")

        # Dessus, Iso, Face, Recadrer changent la caméra
        cameras = []
        for cadrage in ("dessus", "iso", "face", "recadrer"):
            avant = nav.js("return window.carte3d.etat().camera")
            if cadrage == "recadrer":
                nav.js("window.carte3d.recadrer({xmin: 8, ymin: 6, xmax: 12, ymax: 9})")    # zoomé avant « tout voir »
                C.attendre_camera(nav)
                avant = nav.js("return window.carte3d.etat().camera")
            if not nav.js("const b = document.querySelector('[data-role=barre-vue] [data-cadrage=\"' + arguments[0] + "
                          "'\"]'); if (!b) return false; b.click(); return true;", cadrage):
                raise EnAttente(f"la barre de la vue n'a pas [data-cadrage={cadrage}] : agent Coquille")
            C.attendre_camera(nav)
            apres = nav.js("return window.carte3d.etat().camera")
            verifier(apres["position"] != avant["position"] or apres["cible"] != avant["cible"],
                     f"{cadrage} ne change pas la caméra")
            cameras.append(apres)
        verifier(cameras[0]["elevation"] > 89 and abs(cameras[1]["elevation"] - 35) < 1
                 and abs(cameras[2]["elevation"] - 8) < 1,
                 f"élévations Dessus, Iso, Face : {[c['elevation'] for c in cameras[:3]]}")
        ok("Dessus, Iso, Face et Recadrer changent la caméra")

        # la molette zoome vers le pointeur
        t = nav.js("return window.carte3d.etat().taille")
        px, py = t["largeur"] * 0.32, t["hauteur"] * 0.61
        sol = nav.js("return window.carte3d.versSol(arguments[0], arguments[1])", px, py)
        verifier(sol is not None, "pas de sol sous le pointeur")
        d0 = nav.js("return window.carte3d.etat().camera.distance")
        C.molette(nav, (px, py), -300)
        q = nav.js("return window.carte3d.versEcran(arguments[0], arguments[1], 0)", sol["x"], sol["y"])
        d1 = nav.js("return window.carte3d.etat().camera.distance")
        verifier(d1 < d0 and math.hypot(q["x"] - round(px), q["y"] - round(py)) <= 2,
                 f"molette : distance {d0} → {d1}, point du sol à {q} au lieu de ({px:.0f} ; {py:.0f})")
        ok("la molette zoome vers le pointeur (le point du sol reste sous le pointeur, à 2 pixels près)")

        # Annuler puis Rétablir d'un placement
        n0 = nav.js("return window.carte3d.etat().salles")
        nav.js("document.querySelector('[data-commande=\"salles.salle\"]').click()")
        attendre(nav, "return window.carte3d.etat().outil === 'salle'", delai=5)
        cadrer(nav, {"xmin": 12, "ymin": 1, "xmax": 20, "ymax": 6})
        glisser_sol(nav, [(16.0, 3.0), (16.0, 3.0)])
        verifier(attendre(nav, "return window.carte3d.etat().salles === arguments[0] + 1", n0, delai=5),
                 "la salle posée pour Annuler n'apparaît pas")
        for role, attendu in (("defaire", n0), ("refaire", n0 + 1)):
            # la coque met à jour ses boutons plusieurs fois par seconde : on attend qu'il soit actif
            if not attendre(nav, "const b = document.querySelector('[data-role=' + arguments[0] + ']'); if (!b || b.disabled) "
                                 "return false; b.click(); return true;", role, delai=5):
                raise EnAttente(f"le bouton [data-role={role}] de la barre d'outils manque ou reste grisé : agent Coquille")
            verifier(attendre(nav, "return window.carte3d.etat().salles === arguments[0]", attendu, delai=5),
                     f"après {role} : {nav.js('return window.carte3d.etat().salles')} salles au lieu de {attendu}")
        ok("Annuler puis Rétablir d'un placement")
        if captures:
            nav.capture(captures / "critere32_fin.png")
        err = erreurs_page(nav)
        verifier(err == [], f"erreurs dans la page : {err}")
        ok("aucune erreur dans la page")
    finally:
        C.fermer_firefox(nav, gecko)


def sans_webgl(api):
    nav, gecko = ouvrir_firefox({"webgl.disabled": True})
    try:
        ouvrir_placer(nav, api)
        if not attendre(nav, "return document.querySelector('[data-role=carte3d-sans-webgl]')", delai=15):
            raise EnAttente("sans WebGL, la coque ne crée pas la carte 3D (message [data-role=carte3d-sans-webgl]) : "
                            "agent Coquille")
        verifier(nav.js("return !window.carte3d || window.carte3d.etat().webgl === false"),
                 "sans WebGL, etat().webgl doit être faux")
        ok("WebGL coupé : message [data-role=carte3d-sans-webgl]")
        n = attendre(nav, "return document.querySelectorAll('[data-role=vue-plan] .leaflet-marker-icon.salle').length >= 6 "
                          "&& document.querySelectorAll('[data-role=vue-plan] .leaflet-marker-icon.salle').length", delai=15)
        verifier(n, "sans WebGL, le Plan 2D ne montre pas les salles")
        visible = nav.js("const v = document.querySelector('[data-role=vue-plan]'); return !!v && v.offsetParent !== null "
                         "&& v.getBoundingClientRect().width > 100;")
        verifier(visible, "sans WebGL, le Plan 2D n'est pas affiché")
        ok(f"le Plan 2D reste utilisable ({n} salles)")
        err = erreurs_page(nav)
        verifier(err == [], f"erreurs dans la page : {err}")
        ok("aucune erreur dans la page")
    finally:
        C.fermer_firefox(nav, gecko)


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sous = p.add_subparsers(dest="commande", required=True)
    a = sous.add_parser("nuage")
    a.add_argument("--lieu", required=True, type=Path)
    a = sous.add_parser("parcours")
    a.add_argument("--api", required=True)
    a.add_argument("--lieu", required=True, type=Path)
    a.add_argument("--captures", type=Path)
    a = sous.add_parser("sans-webgl")
    a.add_argument("--api", required=True)
    args = p.parse_args()
    try:
        if args.commande == "nuage":
            e = C.ecrire_nuage_de_test(args.lieu)
            ok(f"nuage de test : {e['points']} points, bornes {e['bornes']}")
        elif args.commande == "parcours":
            parcours(args.api, args.lieu, args.captures)
        else:
            sans_webgl(args.api)
    except EnAttente as e:
        print(f"en attente : {e}", flush=True)
        return 77
    except Echec as e:
        print(f"échec : {e}", flush=True)
        return 1
    except (urllib.error.URLError, RuntimeError) as e:
        print(f"échec : {e}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
