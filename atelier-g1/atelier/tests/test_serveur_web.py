"""Vérifications de l'interface web sans navigateur : syntaxe des modules JS (esprima), imports
et exports entre modules, fichiers référencés par index.html, bibliothèques copiées dans vendor/.

esprima s'installe dans .venv-projet : PIP_CONSTRAINT=.venv-projet/contraintes.txt pip install esprima
"""
import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

esprima = pytest.importorskip("esprima", reason="pip install esprima dans .venv-projet")

WEB = Path(__file__).resolve().parent.parent / "web"
MODULES = sorted((WEB / "js").rglob("*.js"))


def _arbre(chemin):
    return esprima.parseModule(chemin.read_text(encoding="utf-8"))


def _exports(arbre):
    noms = set()
    for n in arbre.body:
        if n.type == "ExportNamedDeclaration":
            d = n.declaration
            if d is not None:
                if d.type == "VariableDeclaration":
                    noms.update(x.id.name for x in d.declarations)
                else:
                    noms.add(d.id.name)
            noms.update(s.exported.name for s in (n.specifiers or []))
        elif n.type == "ExportDefaultDeclaration":
            noms.add("default")
    return noms


def test_il_y_a_des_modules():
    noms = {p.relative_to(WEB / "js").as_posix() for p in MODULES}
    attendus = {"app.js", "api.js", "plan.js", "vue3d.js"} | {f"ecrans/{e}.js" for e in (
        "lieux", "monde", "carte", "salles", "itineraires", "zones", "simulation", "scan")}
    assert attendus <= noms


@pytest.mark.parametrize("chemin", MODULES, ids=lambda p: p.relative_to(WEB).as_posix())
def test_syntaxe_des_modules(chemin):
    _arbre(chemin)       # lève une erreur avec le numéro de ligne si la syntaxe est fausse


def test_imports_entre_modules_et_noms_exportes():
    """Chaque import relatif vise un fichier qui existe et qui exporte les noms demandés."""
    exports = {p: _exports(_arbre(p)) for p in MODULES}
    importmap = _importmap()
    problemes = []
    for p in MODULES:
        for n in _arbre(p).body:
            if n.type != "ImportDeclaration":
                continue
            source = n.source.value
            if source.startswith("."):
                cible = (p.parent / source).resolve()
                if cible not in exports:
                    problemes.append(f"{p.name} : import de {source} introuvable")
                    continue
                for s in n.specifiers:
                    nom = "default" if s.type == "ImportDefaultSpecifier" else (
                        s.imported.name if s.type == "ImportSpecifier" else None)
                    if nom and nom not in exports[cible]:
                        problemes.append(f"{p.name} : {nom} n'est pas exporté par {source}")
            else:
                # bibliothèque : elle doit passer par l'importmap de index.html
                if not any(source == k or (k.endswith("/") and source.startswith(k)) for k in importmap):
                    problemes.append(f"{p.name} : « {source} » n'est pas dans l'importmap de index.html")
    assert not problemes, "\n".join(problemes)


class _Lecteur(HTMLParser):
    def __init__(self):
        super().__init__()
        self.liens, self.importmap, self._dans_importmap = [], "", False

    def handle_starttag(self, balise, attributs):
        a = dict(attributs)
        if balise == "script" and a.get("type") == "importmap":
            self._dans_importmap = True
        for cle in ("src", "href"):
            if a.get(cle) and not a[cle].startswith(("data:", "http", "#")):
                self.liens.append(a[cle])

    def handle_endtag(self, balise):
        if balise == "script":
            self._dans_importmap = False

    def handle_data(self, donnees):
        if self._dans_importmap:
            self.importmap += donnees


def _lire_index():
    lecteur = _Lecteur()
    lecteur.feed((WEB / "index.html").read_text(encoding="utf-8"))
    return lecteur


def _importmap():
    return json.loads(_lire_index().importmap)["imports"]


def test_index_html_et_importmap():
    lecteur = _lire_index()
    for lien in lecteur.liens:
        assert (WEB / lien).is_file(), f"index.html : {lien} introuvable"
    for nom, cible in _importmap().items():
        chemin = WEB / cible
        assert chemin.is_dir() if nom.endswith("/") else chemin.is_file(), f"importmap : {cible} introuvable"
    # Leaflet (script classique) avant les modules, importmap avant le premier module
    texte = (WEB / "index.html").read_text(encoding="utf-8")
    assert texte.index("leaflet.js") < texte.index('type="importmap"') < texte.index('type="module"')


def test_bibliotheques_copiees_en_local():
    debut_leaflet = (WEB / "vendor/leaflet/leaflet.js").read_text(encoding="utf-8")[:300]
    assert "Leaflet 1.9.4" in debut_leaflet
    assert (WEB / "vendor/leaflet/leaflet.css").stat().st_size > 10000
    assert "REVISION = '160'" in (WEB / "vendor/three/three.module.js").read_text(encoding="utf-8")[:500]
    orbit = (WEB / "vendor/three/OrbitControls.js").read_text(encoding="utf-8")
    assert re.search(r"from\s+'three'", orbit) and "class OrbitControls" in orbit


def test_pas_de_ressource_internet_dans_l_interface():
    """L'Atelier doit marcher sans Internet (sur le Jetson) : aucune adresse http dans notre code."""
    for p in [*MODULES, WEB / "index.html", WEB / "css/atelier.css"]:
        texte = p.read_text(encoding="utf-8")
        assert not re.search(r"https?://(?!localhost)", texte.replace("http://www.w3.org/2000/svg", "")), p.name
