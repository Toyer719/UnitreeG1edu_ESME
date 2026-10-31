"""Onglet Scan sans navigateur : syntaxe des modules (esprima), routes appelées par l'interface,
feuille de style reliée, réglages de la téléopération face aux limites du contrat 9.7."""
import re
from pathlib import Path

import pytest

esprima = pytest.importorskip("esprima", reason="pip install esprima dans .venv-projet")

WEB = Path(__file__).resolve().parent.parent / "web"
MODULES_SCAN = ("js/ecrans/scan.js", "js/teleop.js", "js/nuage3d.js")


@pytest.mark.parametrize("chemin", MODULES_SCAN)
def test_syntaxe_des_modules_du_scan(chemin):
    arbre = esprima.parseModule((WEB / chemin).read_text(encoding="utf-8"))
    assert arbre.body


def _texte(chemin):
    return (WEB / chemin).read_text(encoding="utf-8")


def test_routes_de_la_vague_2_seulement():
    """L'interface n'appelle que l'API du scan intégré (9.7), plus la téléopération."""
    scan, teleop = _texte("js/ecrans/scan.js"), _texte("js/teleop.js")
    for route in ("/api/scan/demarrer", "/api/scan/arreter", "/api/scan/sessions", "'apercu.png'", "'apercu.json'",
                  "'etat'", "'reconnaissance'", "'adopter'", "'carte.png'", "'carte.yaml'", "'monde'", "'rapport'"):
        assert route in scan, route
    assert "/api/simulation/teleop" in teleop
    for ancienne in ("/api/scan/debut", "/api/scan/fin", "faux-service"):
        assert ancienne not in scan + teleop, ancienne


def test_textes_de_l_ecran():
    scan = _texte("js/ecrans/scan.js")
    for texte in (">Scan<", ">Fin<", "Utiliser cette carte pour l'étage", "Ouvrir dans l'éditeur du monde",
                  "Répétition sans robot", "Exploration automatique", "source ~/robot-g1/setup/robot.sh",
                  "câble Ethernet", "télécommande", "Scans précédents"):
        assert texte in scan.replace("\\'", "'"), texte


def test_feuille_de_style_et_onglet():
    index = _texte("index.html")
    assert index.index("css/atelier.css") < index.index("css/scan.css")
    assert (WEB / "css/scan.css").is_file()
    # vague 5 (section 12.2 du plan) : la table des écrans peut être dans app.js ou dans js/coque/
    textes = [_texte("js/app.js")] + [p.read_text(encoding="utf-8") for p in sorted((WEB / "js" / "coque").glob("*.js"))]
    lignes = [x for t in textes for x in t.splitlines() if "id: 'scan'" in x]
    assert all("sansLieu" not in ligne for ligne in lignes), "l'écran Scan a besoin d'un lieu et d'un étage"


def test_teleop_dans_les_limites_du_contrat():
    from atelier.serveur.routes.simulation import HOMME_MORT_S, LIMITES_TELEOP
    teleop = _texte("js/teleop.js")
    vitesses = dict(re.findall(r"(vx|vy|wz): ([0-9.]+)", re.search(r"VITESSES = \{([^}]*)\}", teleop).group(1)))
    assert {k: float(v) for k, v in vitesses.items()} == {"vx": 0.4, "vy": 0.2, "wz": 0.6}
    assert all(float(vitesses[k]) <= LIMITES_TELEOP[k] for k in vitesses)
    periode = int(re.search(r"PERIODE_TELEOP = ([0-9]+)", teleop).group(1))
    assert periode / 1000 < HOMME_MORT_S / 2, "la consigne doit repartir bien avant l'homme mort"


def test_pas_de_donnee_inseree_en_html():
    """Les textes des fichiers (noms, ids, messages) passent par textContent : pas d'innerHTML avec des
    variables dans les modules du scan (seuls des gabarits fixes, sans ${...})."""
    for chemin in MODULES_SCAN:
        texte = _texte(chemin)
        for m in re.finditer(r"innerHTML\s*=\s*`([^`]*)`", texte):
            assert "${" not in m.group(1), chemin
        assert not re.search(r"innerHTML\s*=\s*[^`'\s]", texte.replace("innerHTML = ''", "")), chemin
