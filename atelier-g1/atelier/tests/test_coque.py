"""La coque de l'Atelier sans navigateur (vague 5, section 12.2 du plan ; agent Coquille) : registre du
ruban (chaque commande a son onglet, son icône, une aide d'une phrase et un écran qui la traite),
anciennes adresses, clés de la mémoire du navigateur, icônes et illustrations, contrastes AA de tous les
textes sur tous les fonds de la coque (thèmes sombre et clair, barres posées sur la vue), feuilles de style
(la page ne défile jamais, [hidden] respecté, pas de 100vh ni de couleur en dur, aucun jeton inconnu),
aucune fenêtre du navigateur (confirm, prompt, alert) et aucune donnée insérée en HTML.

esprima s'installe dans .venv-projet : PIP_CONSTRAINT=.venv-projet/contraintes.txt pip install esprima
"""
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from atelier.lieu import pilotage as D

esprima = pytest.importorskip("esprima", reason="pip install esprima dans .venv-projet")

WEB = Path(__file__).resolve().parent.parent / "web"
JS = WEB / "js"
CSS = WEB / "css"
# Écrans, modules et feuilles de l'agent Coquille (section 12.8 du plan) ; scan.js et camera.js sont à
# d'autres agents (la coque les range seulement dans le ruban)
MES_ECRANS = ("lieux", "monde", "carte", "salles", "itineraires", "zones", "simulation", "pilotage",
              "personnalites", "dialogues")
MES_MODULES = sorted({*(JS / "coque").glob("*.js"), *(JS / f"ecrans/{e}.js" for e in MES_ECRANS),
                      *(JS / "panneaux").glob("*.js"), *(JS / "pilotage").glob("*.js"), *(JS / "equipe").glob("*.js"),
                      *(JS / f"{m}.js" for m in ("app", "api", "contexte", "direct", "formulaire", "geometrie",
                                                 "historique", "messages", "plan", "vue3d", "teleop"))})
MES_FEUILLES = [CSS / f"{f}.css" for f in ("atelier", "principal", "passants", "guide", "pilotage", "equipe")]
FONCTION = object()      # valeur d'une fonction dans une table (charger: () => import(…))


# ---------------------------------------------------------------- lecture des modules (esprima)

def _module(chemin):
    return esprima.parseModule(chemin.read_text(encoding="utf-8"), {"loc": True})


def _constantes(arbre):
    """Déclarations de premier niveau (const et export const) : {nom: nœud de la valeur}."""
    noeuds = {}
    for n in arbre.body:
        d = n.declaration if n.type == "ExportNamedDeclaration" else n
        if d is not None and d.type == "VariableDeclaration":
            for x in d.declarations:
                if x.id.type == "Identifier" and x.init is not None:
                    noeuds[x.id.name] = x.init
    return noeuds


def _valeur(n, constantes):
    """Valeur Python d'une expression littérale (tableaux, objets, chaînes concaténées, constantes)."""
    t = n.type
    if t == "Literal":
        return n.value
    if t == "TemplateLiteral" and not n.expressions:
        return n.quasis[0].value.cooked
    if t == "Identifier":
        return _valeur(constantes[n.name], constantes)
    if t == "ArrayExpression":
        return [_valeur(e, constantes) for e in n.elements]
    if t == "ObjectExpression":
        return {(p.key.name if p.key.type == "Identifier" else p.key.value): _valeur(p.value, constantes)
                for p in n.properties}
    if t == "UnaryExpression" and n.operator == "-":
        return -_valeur(n.argument, constantes)
    if t == "BinaryExpression" and n.operator == "+":
        return _valeur(n.left, constantes) + _valeur(n.right, constantes)
    if t in ("ArrowFunctionExpression", "FunctionExpression"):
        return FONCTION
    raise ValueError(f"expression non littérale : {t}")


def _table(chemin, nom):
    c = _constantes(_module(chemin))
    return _valeur(c[nom], c)


def _registre():
    """Les commandes du ruban : [{id, modes, onglet, groupe, libelle, icone, aide, ecran, commande, avance,
    case, vue, menu}], les onglets par mode et les titres des groupes."""
    c = _constantes(_module(JS / "coque" / "ruban.js"))
    commandes = []
    for appel in c["COMMANDES"].elements:
        assert appel.type == "CallExpression" and appel.callee.name == "c", appel.type
        a = [_valeur(x, c) for x in appel.arguments]
        d = dict(zip(("id", "modes", "onglet", "groupe", "libelle", "icone", "aide", "ecran", "commande"), a[:9]))
        d.update({"avance": False, "case": False, "vue": None, "menu": None})
        if len(a) > 9:
            d.update(a[9])
        commandes.append(d)
    return commandes, _valeur(c["ONGLETS_RUBAN"], c), _valeur(c["TITRES_GROUPES"], c)


def _noeuds(n):
    """Tous les nœuds d'un arbre esprima."""
    if isinstance(n, list):
        for x in n:
            yield from _noeuds(x)
    elif hasattr(n, "type") and isinstance(getattr(n, "type", None), str):
        yield n
        for cle, v in vars(n).items():
            if cle not in ("type", "loc", "range"):
                yield from _noeuds(v)


# ---------------------------------------------------------------- registre du ruban

def test_registre_du_ruban():
    commandes, onglets, titres = _registre()
    ids = [x["id"] for x in commandes]
    assert len(ids) == len(set(ids)), "identifiant en double"
    dessins = _table(JS / "coque" / "icones.js", "DESSINS")
    ecrans = _table(JS / "coque" / "coque.js", "ECRANS")
    a_cocher = _table(JS / "coque" / "coque.js", "COMMANDES_A_COCHER")
    modules = _table(JS / "coque" / "coque.js", "MODULES_COQUE")      # vague 6 (section 13.7 du plan)
    problemes = []
    for x in commandes:
        nom = x["id"]
        if nom.split(".", 1)[1] != x["commande"]:
            problemes.append(f"{nom} : le nom de la commande ({x['commande']}) ne suit pas l'identifiant")
        if not x["modes"] or not set(x["modes"]) <= {"simu", "reel"}:
            problemes.append(f"{nom} : modes {x['modes']}")
        for m in x["modes"]:
            if x["onglet"] not in [o["id"] for o in onglets[m]]:
                problemes.append(f"{nom} : l'onglet {x['onglet']} n'existe pas en {m}")
        if x["icone"] not in dessins:
            problemes.append(f"{nom} : icône « {x['icone']} » absente de icones.js")
        if x.get("module"):
            # vague 6 : une commande d'un module de la coque (diagnostic.js, seance.js), sans écran
            fichier = modules.get(x["module"], {}).get("fichier")
            if x["ecran"] is not None or not fichier or not (JS / "coque" / fichier).is_file():
                problemes.append(f"{nom} : module {x['module']} inconnu de la coque (MODULES_COQUE)")
            elif f"'{x['commande']}'" not in (JS / "coque" / fichier).read_text(encoding="utf-8"):
                problemes.append(f"{nom} : le module {fichier} ne traite pas « {x['commande']} »")
        elif x["ecran"] not in ecrans or not (JS / "ecrans" / f"{x['ecran']}.js").is_file():
            problemes.append(f"{nom} : écran {x['ecran']} inconnu de la coque")
            continue
        vues = ecrans[x["ecran"]]["vues"] if x["ecran"] in ecrans else []
        if x["vue"] is not None and x["vue"] not in vues:
            problemes.append(f"{nom} : vue {x['vue']} absente de l'écran {x['ecran']} ({vues})")
        # chaque commande est traitée : par l'écran (son nom y figure), par la coque (ouvrir, cases à cocher)
        if x.get("module"):
            pass
        elif x["case"]:
            if nom not in a_cocher:
                problemes.append(f"{nom} : case à cocher inconnue de la coque")
        elif x["commande"] != "ouvrir" and x["ecran"] in MES_ECRANS:
            source = (JS / "ecrans" / f"{x['ecran']}.js").read_text(encoding="utf-8")
            if f"'{x['commande']}'" not in source:
                problemes.append(f"{nom} : l'écran {x['ecran']} ne traite pas « {x['commande']} »")
        # textes courts : un libellé de quelques mots, une seule phrase d'aide
        if not x["libelle"] or len(x["libelle"]) > 22:
            problemes.append(f"{nom} : libellé « {x['libelle']} » (22 caractères au plus)")
        fins = re.findall(r"[.!?…](?=\s|$)", x["aide"])
        if len(fins) != 1 or not x["aide"].rstrip().endswith((".", "…", "!", "?")) or len(x["aide"]) > 140:
            problemes.append(f"{nom} : l'aide doit tenir en une phrase de 140 caractères au plus : « {x['aide']} »")
        if x["groupe"] in titres and not titres[x["groupe"]]:
            problemes.append(f"{nom} : groupe {x['groupe']} sans titre")
    assert problemes == [], "\n".join(problemes)
    # des onglets lisibles : au moins une commande visible, pas plus de 9 (le reste dans « Avancé »)
    for m, liste in onglets.items():
        for o in liste:
            visibles = [x for x in commandes if m in x["modes"] and x["onglet"] == o["id"] and not x["avance"]]
            assert 1 <= len(visibles) <= 9, (m, o["id"], len(visibles))
    # le Pilotage n'existe qu'en Réel (décision I2)
    assert all(x["modes"] == ["reel"] for x in commandes if x["ecran"] == "pilotage")
    assert titres == {"spectacle": "Spectacle", "demo": "Démo"}
    assert {x["id"] for x in commandes if x["groupe"] == "spectacle"} == {"pilotage.danses", "pilotage.choregraphies"}
    # vague 6 (section 13.7 du plan) : le groupe Démo d'Équipe, dans les deux modes
    assert {x["id"] for x in commandes if x["groupe"] == "demo"} == {"demo.lancer", "demo.arreter", "demo.borne"}
    assert all(x["modes"] == ["simu", "reel"] for x in commandes if x["id"].startswith("demo."))


def test_menus_du_ruban():
    """Postures et gestes du ruban : les valeurs du contrat (atelier.lieu.pilotage), jamais celles du portique."""
    commandes = {x["id"]: x for x in _registre()[0]}
    postures = commandes["pilotage.postures"]["menu"]
    gestes = commandes["pilotage.gestes"]["menu"]
    assert postures and all(p["libelle"] for p in postures)
    assert {p["valeur"] for p in postures} <= set(D.POSTURES) - set(D.POSTURES_PORTIQUE)
    assert 500 in {p["valeur"] for p in postures}
    assert gestes and {g["valeur"] for g in gestes} <= set(D.GESTES_BRAS) and D.GESTE_RELACHER in {g["valeur"] for g in gestes}
    assert commandes["simulation.y-aller"]["menu"] == "dynamique" == commandes["navigation.y-aller"]["menu"]
    meubles = commandes["monde.objet"]["menu"]
    assert meubles and len({m["valeur"] for m in meubles}) == len(meubles)
    # les commandes à menu sont des actions (ou un outil dont on choisit la variante)
    assert {x["id"] for x in commandes.values() if x["menu"]} == {
        "monde.objet", "simulation.y-aller", "navigation.y-aller", "pilotage.postures", "pilotage.gestes"}


def test_anciennes_adresses_et_cles_de_memoire():
    table = _table(JS / "coque" / "anciens_hash.js", "ANCIENS_HASH")
    commandes = {x["id"]: x for x in _registre()[0]}
    ecrans = _table(JS / "coque" / "coque.js", "ECRANS")
    for nom, d in table.items():
        if d.get("accueil"):
            continue
        assert d["ecran"] in ecrans, nom
        if d["commande"]:
            assert commandes[d["commande"]]["ecran"] == d["ecran"], nom
            if d["mode"] in ("simu", "reel"):
                assert d["mode"] in commandes[d["commande"]]["modes"], nom
        assert bool(d.get("sansLieu")) == bool(ecrans[d["ecran"]].get("sansLieu")), nom
    # clés du contrat (section 12.2) : elles ne changent pas de nom
    assert _table(JS / "coque" / "coque.js", "CLES_MEMOIRE") == {
        "mode": "atelier.mode", "repetition": "atelier.repetition", "theme": "atelier.theme", "lieu": "atelier.lieu",
        "etage": "atelier.etage", "onglet": "atelier.onglet.", "vue": "atelier.vue.", "calques": "atelier.calques",
        "arbreReplie": "atelier.arbre.replie", "rubanReplie": "atelier.ruban.replie",
        "modeSimulation": "atelier.mode-simulation", "modeScan": "atelier.scan.mode",
        "repetitionScan": "atelier.scan.repetition"}
    assert _table(JS / "coque" / "coque.js", "MODES") == ["simu", "reel", "repetition"]


# ---------------------------------------------------------------- icônes et illustrations

def test_icones_et_illustrations():
    dessins = _table(JS / "coque" / "icones.js", "DESSINS")
    assert len(dessins) >= 60
    for nom, svg in dessins.items():
        racine = ET.fromstring(f'<svg xmlns="http://www.w3.org/2000/svg">{svg}</svg>')     # XML bien formé
        for e in racine.iter():
            for attribut in ("fill", "stroke"):
                assert e.get(attribut) in (None, "none", "currentColor"), (nom, attribut, e.get(attribut))
        assert not re.search(r"#[0-9a-fA-F]{3,6}\b|rgb", svg), nom
    feuille = (CSS / "atelier.css").read_text(encoding="utf-8")
    for nom, svg in _table(JS / "coque" / "icones.js", "ILLUSTRATIONS").items():
        racine = ET.fromstring(svg if svg.lstrip().startswith("<svg") else f'<svg xmlns="http://www.w3.org/2000/svg">{svg}</svg>')
        classes = {c for e in racine.iter() for c in (e.get("class") or "").split()}
        assert classes, nom
        manquantes = [c for c in classes if c.startswith("ill-") and f".{c}" not in feuille]
        assert manquantes == [], (nom, manquantes)
        assert not re.search(r"#[0-9a-fA-F]{3,6}\b|var\(", svg), nom     # couleurs : par les classes du thème


# ---------------------------------------------------------------- thème et contrastes

def _blocs_du_theme():
    texte = re.sub(r"/\*.*?\*/", "", (CSS / "theme.css").read_text(encoding="utf-8"), flags=re.S)
    blocs = {}
    for selecteur, corps in re.findall(r"([^{}]+)\{([^{}]*)\}", texte):
        jetons = dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\s*;", corps))
        jetons.update({k: tuple(float(x) for x in v.split(",")) for k, v in
                       re.findall(r"--([a-z0-9-]+):\s*rgba\(([^)]*)\)\s*;", corps)})
        blocs[" ".join(selecteur.split())] = jetons
    return blocs


def _rvb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def _sur(rgba, fond):
    """Couleur d'un rgba posé sur un fond opaque (#rrggbb)."""
    r, v, b, a = rgba
    f = _rvb(fond)
    return "#" + "".join(f"{round(a * c + (1 - a) * d):02x}" for c, d in zip((r, v, b), f))


def contraste(a, b):
    def luminance(h):
        f = (lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
        r, g, bl = (f(c / 255) for c in _rvb(h))
        return 0.2126 * r + 0.7152 * g + 0.0722 * bl
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


TEXTES = ("texte", "texte-doux", "accent-texte", "danger-texte", "succes", "avertissement", "mode-reel", "mode-simulation",
          "accueil-texte")
FONDS = ("fond", "surface", "surface-2", "surface-3", "champ", "barre", "accent-doux")


def test_contrastes_de_tous_les_textes():
    blocs = _blocs_du_theme()
    sombre, clair, commun = blocs[':root, :root[data-theme="sombre"]'], blocs[':root[data-theme="clair"]'], blocs[":root"]
    faibles = []
    for nom, t in (("sombre", sombre), ("clair", clair)):
        faibles += [(nom, a, b, round(contraste(t[a], t[b]), 2)) for a in TEXTES for b in FONDS
                    if contraste(t[a], t[b]) < 4.5]
        faibles += [(nom, a, b, round(contraste(t[a], t[b]), 2)) for a, b in (("sur-accent", "accent"), ("sur-danger", "danger"))
                    if contraste(t[a], t[b]) < 4.5]
    # barres flottantes sur la vue : posées sur la 3D (toujours sombre) ou sur le plan (blanc en thème clair)
    for dessous in (commun["vue-fond"], "#ffffff"):
        barre = _sur(commun["vue-barre"], dessous)
        faibles += [("vue-barre", a, dessous, round(contraste(commun[a], barre), 2)) for a in ("vue-texte", "vue-texte-doux")
                    if contraste(commun[a], barre) < 4.5]
    assert faibles == [], faibles


def test_index_et_theme_sombre_par_defaut():
    index = (WEB / "index.html").read_text(encoding="utf-8")
    assert '<html lang="fr" data-theme="sombre">' in index
    # le thème clair retenu s'applique avant le premier affichage (pas d'éclair sombre)
    debut = index.index("atelier.theme")
    assert debut < index.index('href="css/theme.css"') and "data-theme" in index[debut - 200:debut + 200]
    assert 'data-role="atelier"' in index


# ---------------------------------------------------------------- feuilles de style

def _sans_commentaires(texte):
    return re.sub(r"/\*.*?\*/", "", texte, flags=re.S)


def test_feuilles_de_la_coque():
    atelier = _sans_commentaires((CSS / "atelier.css").read_text(encoding="utf-8"))
    assert re.search(r"\[hidden\]\s*\{\s*display:\s*none\s*!important;?\s*\}", atelier)
    # la page ne défile jamais : seuls les panneaux défilent, chacun pour soi
    regle = re.search(r"html,\s*body\s*\{([^}]*)\}", atelier)
    assert regle and "overflow: hidden" in regle.group(1) and "height: 100%" in regle.group(1)
    for classe in (".panneau-corps", ".arbre-contenu", ".etat-volet-liste"):
        corps = re.search(re.escape(classe) + r"\s*\{([^}]*)\}", atelier).group(1)
        assert "overflow-y: auto" in corps and "overscroll-behavior: contain" in corps and "min-height: 0" in corps, classe
    definis = set(re.findall(r"--([a-z0-9-]+)\s*:", (CSS / "theme.css").read_text(encoding="utf-8")))
    for f in MES_FEUILLES:
        definis |= set(re.findall(r"--([a-z0-9-]+)\s*:", f.read_text(encoding="utf-8")))
    problemes = []
    for f in [CSS / "theme.css", *MES_FEUILLES]:
        texte = _sans_commentaires(f.read_text(encoding="utf-8"))
        if re.search(r"\b100vh\b|\b100dvh\b", texte):
            problemes.append(f"{f.name} : 100vh (la coque se cale sur html et body à 100 %)")
        if f.name == "theme.css":
            continue
        for couleur in re.findall(r"#[0-9a-fA-F]{3,8}\b", texte):
            problemes.append(f"{f.name} : couleur en dur {couleur} (un jeton de theme.css)")
        for nom in re.findall(r"var\(--([a-z0-9-]+)\)", texte):          # sans valeur de repli
            if nom not in definis:
                problemes.append(f"{f.name} : jeton --{nom} défini nulle part")
    assert problemes == [], "\n".join(problemes)


# ---------------------------------------------------------------- code des modules

def test_pas_de_fenetre_du_navigateur():
    """confirm(), prompt() et alert() bloquent la page (et les tests) : la coque a ses fenêtres dans la page."""
    for p in MES_MODULES:
        texte = p.read_text(encoding="utf-8")
        texte = re.sub(r"//[^\n]*", "", texte)
        assert not re.search(r"(?<![\w.$])(?:window\.)?(?:confirm|prompt|alert)\s*\(", texte), p.name


def _html_sur(n):
    """Expression sans donnée : texte fixe, gabarit sans ${…}, ou gabarit SVG des tables d'icônes."""
    t = n.type
    if t == "Literal":
        return True
    if t == "TemplateLiteral":
        return not n.expressions
    if t == "BinaryExpression" and n.operator == "+":
        return _html_sur(n.left) and _html_sur(n.right)
    if t == "ConditionalExpression":
        return _html_sur(n.consequent) and _html_sur(n.alternate)
    if t == "MemberExpression" and n.object.type == "Identifier" and n.object.name in ("DESSINS", "ILLUSTRATIONS"):
        return True
    return False


@pytest.mark.parametrize("chemin", MES_MODULES, ids=lambda p: p.relative_to(JS).as_posix())
def test_aucune_donnee_inseree_en_html(chemin):
    problemes = []
    for n in _noeuds(_module(chemin).body):
        if n.type == "AssignmentExpression" and n.left.type == "MemberExpression" and not n.left.computed \
                and n.left.property.name in ("innerHTML", "outerHTML"):
            if n.operator != "=" or not _html_sur(n.right):
                problemes.append(f"ligne {n.loc.start.line} : {n.left.property.name} reçoit une valeur calculée")
        if n.type == "CallExpression" and n.callee.type == "MemberExpression" and not n.callee.computed \
                and n.callee.property.name in ("insertAdjacentHTML", "write", "writeln"):
            problemes.append(f"ligne {n.loc.start.line} : {n.callee.property.name}")
    assert problemes == [], problemes


def test_les_modules_de_la_coque_sont_en_francais_simple():
    """Un repère par module : en-tête en français qui dit son rôle (pas de module muet)."""
    for p in (JS / "coque").glob("*.js"):
        premiere = p.read_text(encoding="utf-8").lstrip().splitlines()[0]
        assert premiere.startswith("//") and len(premiere) > 20, p.name
