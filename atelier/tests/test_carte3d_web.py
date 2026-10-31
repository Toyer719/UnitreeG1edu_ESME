"""Vérifications de la carte 3D sans navigateur (vague 5, section 12.3 du plan) : syntaxe ES2017 (esprima),
exports et méthodes du contrat, aucune donnée insérée en HTML, couleurs de theme.css (aucune en dur dans
carte3d.css, replis du module identiques aux jetons), page d'essai autonome (importmap, fichiers,
jamais liée par l'interface, aucune adresse Internet).
"""
import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

esprima = pytest.importorskip("esprima", reason="pip install esprima dans .venv-projet")

WEB = Path(__file__).resolve().parent.parent / "web"
CARTE3D = WEB / "js" / "carte3d"
MODULES = sorted(CARTE3D.glob("*.js"))
ESSAI = WEB / "essais" / "carte3d.html"

METHODES_CONTRAT = {
    "chargerNuage", "afficherPoints", "afficherMonde", "afficherCarte2D", "afficherSalles", "afficherItineraires",
    "afficherZones", "afficherRobot", "afficherPietons", "afficherTrajet", "vue", "recadrer", "centrerSur", "calque",
    "coupe", "outil", "choisir", "surSelection", "surPose", "surPointeur", "versEcran", "versSol", "redimensionner",
    "etat", "detruire",
}


def _arbre(chemin):
    return esprima.parseModule(chemin.read_text(encoding="utf-8"), {"range": True})


def _exports(arbre):
    noms = set()
    for n in arbre.body:
        if n.type == "ExportNamedDeclaration" and n.declaration is not None:
            d = n.declaration
            if d.type == "VariableDeclaration":
                noms.update(x.id.name for x in d.declarations)
            else:
                noms.add(d.id.name)
    return noms


def _objets_nommes(noeud, nom, trouves):
    """Les objets littéraux affectés à une constante de ce nom (const carte = {...}), partout dans l'arbre."""
    if isinstance(noeud, list):
        for x in noeud:
            _objets_nommes(x, nom, trouves)
        return trouves
    if not hasattr(noeud, "type"):
        return trouves
    if noeud.type == "VariableDeclarator" and getattr(noeud.id, "name", None) == nom and \
            noeud.init is not None and noeud.init.type == "ObjectExpression":
        trouves.append({p.key.name for p in noeud.init.properties if p.type == "Property" and p.key.type == "Identifier"})
    for cle in vars(noeud):
        valeur = getattr(noeud, cle)
        if isinstance(valeur, list) or hasattr(valeur, "type"):
            _objets_nommes(valeur, nom, trouves)
    return trouves


@pytest.mark.parametrize("chemin", MODULES, ids=lambda p: p.name)
def test_syntaxe_es2017(chemin):
    _arbre(chemin)


def test_exports_du_contrat():
    arbre = _arbre(CARTE3D / "carte3d.js")
    assert {"VUES", "CALQUES", "OUTILS", "HAUTEUR_COUPE", "FOND", "creerCarte3D"} <= _exports(arbre)
    texte = (CARTE3D / "carte3d.js").read_text(encoding="utf-8")
    assert "export const CALQUES = ['nuage', 'carte2d', 'monde', 'points', 'itineraires', 'zones', 'robot', " \
           "'pietons', 'trajet'];" in texte
    assert "export const VUES = ['dessus', 'iso', 'face'];" in texte
    assert "export const OUTILS = ['naviguer', 'salle', 'accueil', 'noeud', 'mesurer'];" in texte
    assert "export const HAUTEUR_COUPE = 2.2;" in texte and "export const FOND = '#1e1e1e';" in texte


def test_methodes_du_contrat_avec_et_sans_webgl():
    """L'objet rendu par creerCarte3D a toutes les méthodes de 12.3, avec WebGL comme sans (carteInerte)."""
    objets = _objets_nommes(_arbre(CARTE3D / "carte3d.js").body, "carte", [])
    assert len(objets) == 2, "deux objets « carte » attendus : la carte et la carte inerte (sans WebGL)"
    for cles in objets:
        assert METHODES_CONTRAT <= cles, METHODES_CONTRAT - cles


def test_modules_annexes_exportent_leurs_points_d_entree():
    assert "creerEditionSalles" in _exports(_arbre(CARTE3D / "edition.js"))
    assert "suivreEnDirect" in _exports(_arbre(CARTE3D / "direct3d.js"))
    g = _exports(_arbre(CARTE3D / "geometrie3d.js"))
    assert {"intersectionSol", "angleFleche", "accrocherPosition", "couleurHauteur", "lireEntetesNuage",
            "positionsDepuisTampon", "cadrage", "poseVue", "bornesRobustes", "idPrincipal", "numerosSalles"} <= g
    # géométrie pure : testable sans three.js
    assert "from 'three'" not in (CARTE3D / "geometrie3d.js").read_text(encoding="utf-8")


@pytest.mark.parametrize("chemin", MODULES, ids=lambda p: p.name)
def test_aucune_donnee_inseree_en_html(chemin):
    texte = chemin.read_text(encoding="utf-8")
    for interdit in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
        assert interdit not in texte, f"{chemin.name} : {interdit}"


def _jetons_theme():
    texte = (WEB / "css" / "theme.css").read_text(encoding="utf-8")
    return dict(re.findall(r"(--[a-z0-9-]+):\s*(#[0-9a-fA-F]{3,6})\b", texte))


def test_couleurs_du_theme_et_replis_identiques():
    css = (WEB / "css" / "carte3d.css").read_text(encoding="utf-8")
    sans_commentaires = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    assert not re.findall(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", sans_commentaires), "couleur en dur dans carte3d.css"
    jetons = _jetons_theme()
    texte = (CARTE3D / "carte3d.js").read_text(encoding="utf-8")
    replis = re.findall(r"\[\s*'(--[a-z0-9-]+)',\s*'(#[0-9a-fA-F]{6})'\s*\]", texte)
    assert len(replis) >= 12
    for jeton, valeur in replis:
        assert jeton in jetons, f"{jeton} n'est pas dans theme.css"
        assert jetons[jeton].lower() == valeur.lower(), f"{jeton} : {valeur} dans le module, {jetons[jeton]} dans theme.css"
    g = (CARTE3D / "geometrie3d.js").read_text(encoding="utf-8")
    for jeton, cle in (("--nuage-bas", "bas"), ("--nuage-milieu", "milieu"), ("--nuage-haut", "haut")):
        assert f"{cle}: '{jetons[jeton]}'" in g, f"PALETTE_NUAGE.{cle} ≠ {jeton}"


class _Lecteur(HTMLParser):
    def __init__(self):
        super().__init__()
        self.liens, self.importmap, self._dans = [], "", False

    def handle_starttag(self, balise, attributs):
        a = dict(attributs)
        if balise == "script" and a.get("type") == "importmap":
            self._dans = True
        for cle in ("src", "href"):
            if a.get(cle) and not a[cle].startswith(("data:", "#")):
                self.liens.append(a[cle])

    def handle_endtag(self, balise):
        if balise == "script":
            self._dans = False

    def handle_data(self, donnees):
        if self._dans:
            self.importmap += donnees


def test_page_d_essai_autonome():
    lecteur = _Lecteur()
    texte = ESSAI.read_text(encoding="utf-8")
    lecteur.feed(texte)
    for lien in lecteur.liens:
        assert not lien.startswith("http"), lien
        assert (ESSAI.parent / lien).resolve().is_file(), f"essais/carte3d.html : {lien} introuvable"
    imports = json.loads(lecteur.importmap)["imports"]
    assert set(imports) == {"three", "three/addons/"}
    assert (ESSAI.parent / imports["three"]).resolve().is_file()
    assert (ESSAI.parent / imports["three/addons/"] / "OrbitControls.js").resolve().is_file()
    assert texte.index('type="importmap"') < texte.index('type="module"')
    assert "window.erreursAtelier" in texte
    for p in [*MODULES, ESSAI, WEB / "css" / "carte3d.css"]:
        contenu = p.read_text(encoding="utf-8").replace("http://www.w3.org/2000/svg", "")
        assert not re.search(r"https?://", contenu), f"{p.name} : adresse Internet"


def test_page_d_essai_jamais_liee_par_l_interface():
    autres = [WEB / "index.html"] + [p for p in (WEB / "js").rglob("*.js") if p.parent != CARTE3D]
    for p in autres:
        assert "essais/carte3d" not in p.read_text(encoding="utf-8"), f"{p.relative_to(WEB)} lie la page d'essai"
