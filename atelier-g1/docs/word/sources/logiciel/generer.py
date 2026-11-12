#!/usr/bin/env python3
"""Génère le document Word « Atelier G1 : le logiciel, de A à Z ».

    /home/joonho/robot-g1-donnees/venv-docx/bin/python \
        /home/joonho/robot-g1-donnees/vague5/documents/logiciel/generer.py

Ce que fait le script, dans l'ordre :
  1. il dessine les schémas : chaque schemas/<nom>.dot (Graphviz) devient schemas/png/<nom>.png
     (200 dpi, police DejaVu Sans), seulement s'il a changé ;
  2. il lit le contenu : contenu/couverture.py, puis contenu/chapitre_01.py à chapitre_16.py
     (chacun définit BLOCS, une liste de blocs : titres, paragraphes, listes, tableaux, schémas,
     captures…) ;
  3. il écrit Atelier_G1_documentation_logiciel.docx (python-docx) : styles, titres numérotés,
     vraies listes Word, tableaux à en-tête ombré, en-tête et pied de page, table des matières ;
  4. il le convertit en PDF avec LibreOffice (controle/), relève la page de chaque titre et
     réécrit la table des matières avec ces numéros (deux ou trois passes), pour que la table
     s'affiche aussi dans LibreOffice ; Word la met de toute façon à jour à l'ouverture.

Options : --captures DOSSIER, plusieurs fois possible (défaut : ~/robot-g1-donnees/vague5/captures pour le
chapitre 11, puis ~/robot-g1-donnees/vague6/captures pour le chapitre 12 ; les captures absentes sont
simplement omises), --sans-pdf (pas de LibreOffice : table des matières sans numéros de page), --images
(pages du PDF en PNG à 60 dpi dans controle/pages/, pour les relire).

Notation dans le contenu : **gras**, `code`, __italique__ ; [[cle]] est remplacé par un chiffre
mesuré dans le dépôt au moment de la génération (voir chiffres()).
"""
import argparse
import datetime
import importlib
import os
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_TAB_ALIGNMENT, WD_TAB_LEADER
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Cm, Pt, RGBColor

ICI = Path(__file__).resolve().parent
DEPOT = Path.home() / "robot-g1"
CAPTURES_DEFAUT = [Path.home() / "robot-g1-donnees" / "vague5" / "captures",     # chapitre 11 (vague 5)
                   Path.home() / "robot-g1-donnees" / "vague6" / "captures"]     # chapitre 12 (vague 6)
SORTIE = ICI / "Atelier_G1_documentation_logiciel.docx"
CONTROLE = ICI / "controle"
SCHEMAS = ICI / "schemas"
PNG_SCHEMAS = SCHEMAS / "png"
CACHE_CAPTURES = CONTROLE / "captures_jpeg"

NB_CHAPITRES = 16

# Mise en page (A4)
LARGEUR_PAGE_CM = 21.0
MARGE_CM = 2.2
LARGEUR_TEXTE_CM = LARGEUR_PAGE_CM - 2 * MARGE_CM          # 16,6 cm
HAUTEUR_IMAGE_MAX_CM = 21.5
LIGNE_CODE_MAX = 84            # caractères par ligne de code, en Consolas 9 pt sur 16,6 cm

POLICE = "Calibri"
POLICE_CODE = "Consolas"
BLEU = RGBColor(0x1F, 0x3A, 0x5F)
BLEU_CLAIR = "D9E2F3"
GRIS_CODE = "F2F4F7"
ZEBRE = "F7F9FC"
BORDURE = "B4BFCC"

# Numérotation (numbering.xml) : titres, puces, listes numérotées
ID_ABSTRAIT_TITRES, ID_NUM_TITRES = 90, 90
ID_ABSTRAIT_PUCES, ID_NUM_PUCES = 91, 91
ID_ABSTRAIT_NUMEROS = 92


# ------------------------------------------------------------------ chiffres mesurés dans le dépôt

def _sortie(cmd, cwd=DEPOT, timeout=120, env=None):
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _milliers(n):
    return f"{n:,}".replace(",", "\u202f")


def chiffres():
    """Chiffres du dépôt au moment de la génération (valeurs du 10/11 si une mesure échoue)."""
    c = {"commits": "101", "dernier_commit": "1f73bdf", "date_commit": "10/11/2026 04:16",
         "fichiers": "830", "lignes_python": "131\u202f000", "lignes_python_code": "60\u202f000",
         "lignes_python_tests": "71\u202f000", "lignes_js": "26\u202f000", "lignes_css": "2\u202f900",
         "lignes_shell": "3\u202f600", "commandes": "30", "routes": "136", "tests_atelier": "1\u202f960",
         "tests_docker": "71", "fonctions_test_ros": "760", "criteres": "42", "paquets_ros": "7"}
    sortie = _sortie(["git", "rev-list", "--count", "HEAD"])
    if sortie.strip():
        c["commits"] = sortie.strip()
    sortie = _sortie(["git", "log", "-1", "--format=%h|%ad", "--date=format:%d/%m/%Y %H:%M"])
    if "|" in sortie:
        c["dernier_commit"], c["date_commit"] = sortie.strip().split("|", 1)
    fichiers = [f for f in _sortie(["git", "ls-files"]).splitlines() if f]
    if fichiers:
        c["fichiers"] = _milliers(len(fichiers))
        # docs/ : les générateurs de ces documents Word (docs/word/sources/) ne sont pas le logiciel du robot
        exclus = re.compile(r"^(third_party/|atelier/web/vendor/|ws/src/(FAST_LIO|livox_ros_driver2)/|docs/)")
        test = re.compile(r"(^|/)(test_[^/]*|critere[^/]*|outils[^/]*)\.py$|/test/|atelier/tests/|tests_e2e/|docker/tests/")

        def lignes(filtre):
            total = 0
            for f in fichiers:
                if exclus.search(f) or not filtre(f):
                    continue
                try:
                    with open(DEPOT / f, "rb") as fh:
                        total += fh.read().count(b"\n")
                except OSError:
                    pass
            return total

        py = lignes(lambda f: f.endswith(".py"))
        py_tests = lignes(lambda f: f.endswith(".py") and bool(test.search(f)))
        c["lignes_python"] = _milliers(py)
        c["lignes_python_tests"] = _milliers(py_tests)
        c["lignes_python_code"] = _milliers(py - py_tests)
        c["lignes_js"] = _milliers(lignes(lambda f: f.endswith(".js")))
        c["lignes_css"] = _milliers(lignes(lambda f: f.endswith(".css")))
        c["lignes_shell"] = _milliers(lignes(lambda f: f.endswith(".sh") or f.startswith("bin/g1-")))
    commandes = sorted(p.name for p in (DEPOT / "bin").glob("g1-*"))
    if commandes:
        c["commandes"] = str(len(commandes))
    paquets = [p for p in (DEPOT / "ws" / "src").glob("g1_*") if (p / "package.xml").exists()]
    if paquets:
        c["paquets_ros"] = str(len(paquets))
    criteres = {m.group(1) for p in (DEPOT / "tests_e2e").glob("critere_*.sh")
                for m in [re.match(r"critere_(\d+)_", p.name)] if m}
    if criteres:
        c["criteres"] = str(len(criteres))
    n = 0
    for dossier in (DEPOT / "ws" / "src").glob("g1_*/test"):
        for f in dossier.glob("*.py"):
            try:
                n += len(re.findall(r"^\s*def test_", f.read_text(encoding="utf-8"), re.M))
            except OSError:
                pass
    if n:
        c["fonctions_test_ros"] = str(n)
    python_projet = DEPOT / ".venv-projet" / "bin" / "python"
    if python_projet.exists():
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", ATELIER_ROS="0")
        for cle, dossier in (("tests_atelier", "atelier/tests"), ("tests_docker", "docker/tests")):
            sortie = _sortie([str(python_projet), "-m", "pytest", dossier, "--collect-only", "-q",
                              "-p", "no:cacheprovider"], timeout=300, env=env)
            m = re.search(r"(\d+) tests? collected", sortie)
            if m:
                c[cle] = _milliers(int(m.group(1)))
        code = ("import importlib\n"
                "mods='lieux monde plan simulation scan robot principal passants guide pilotage equipe "
                "arret liaison nuage camera diagnostic seance borne demo voix'.split()\n"
                "print(sum(len(importlib.import_module('atelier.serveur.routes.'+m).routeur.routes) for m in mods))")
        sortie = _sortie([str(python_projet), "-c", code], timeout=120, env=env)
        if sortie.strip().isdigit():
            c["routes"] = str(int(sortie.strip()) + 2)      # + GET /api/etat et le WebSocket /ws/etat
    c["date"] = datetime.date.today().strftime("%d/%m/%Y")
    return c


# ------------------------------------------------------------------ schémas Graphviz

def dessiner_schemas(forcer=False):
    PNG_SCHEMAS.mkdir(parents=True, exist_ok=True)
    if not shutil.which("dot"):
        print("Graphviz (dot) absent : les schémas déjà dessinés servent tels quels.")
        return
    for source in sorted(SCHEMAS.glob("*.dot")):
        cible = PNG_SCHEMAS / (source.stem + ".png")
        if not forcer and cible.exists() and cible.stat().st_mtime >= source.stat().st_mtime:
            continue
        r = subprocess.run(["dot", "-Tpng", "-Gdpi=200", str(source), "-o", str(cible)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit(f"Schéma {source.name} : {r.stderr.strip()}")
        print(f"  schéma {source.stem} dessiné")


def taille_png(chemin):
    """(largeur, hauteur) en pixels d'un PNG, sans Pillow."""
    with open(chemin, "rb") as f:
        tete = f.read(24)
    if tete[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return struct.unpack(">II", tete[16:24])


def taille_jpeg(chemin):
    with open(chemin, "rb") as f:
        donnees = f.read()
    i = 2
    while i < len(donnees):
        if donnees[i] != 0xFF:
            i += 1
            continue
        marque = donnees[i + 1]
        if marque in (0xC0, 0xC1, 0xC2):
            h, w = struct.unpack(">HH", donnees[i + 5:i + 9])
            return w, h
        longueur = struct.unpack(">H", donnees[i + 2:i + 4])[0]
        i += 2 + longueur
    return None


# ------------------------------------------------------------------ outils XML

def _el(tag, **attrs):
    e = OxmlElement(tag)
    for k, v in attrs.items():
        e.set(qn(k.replace("__", ":")), str(v))
    return e


# Ordre imposé des enfants (schéma OOXML) : Word refuse un fichier où il n'est pas respecté
ORDRES = {
    "pPr": ["pStyle", "keepNext", "keepLines", "pageBreakBefore", "framePr", "widowControl", "numPr",
            "suppressLineNumbers", "pBdr", "shd", "tabs", "suppressAutoHyphens", "kinsoku", "wordWrap",
            "overflowPunct", "topLinePunct", "autoSpaceDE", "autoSpaceDN", "bidi", "adjustRightInd",
            "snapToGrid", "spacing", "ind", "contextualSpacing", "mirrorIndents", "suppressOverlap", "jc",
            "textDirection", "textAlignment", "textboxTightWrap", "outlineLvl", "divId", "cnfStyle", "rPr",
            "sectPr", "pPrChange"],
    "tblPr": ["tblStyle", "tblpPr", "tblOverlap", "bidiVisual", "tblStyleRowBandSize", "tblStyleColBandSize",
              "tblW", "jc", "tblCellSpacing", "tblInd", "tblBorders", "shd", "tblLayout", "tblCellMar", "tblLook",
              "tblCaption", "tblDescription"],
    "tcPr": ["cnfStyle", "tcW", "gridSpan", "hMerge", "vMerge", "tcBorders", "shd", "noWrap", "tcMar",
             "textDirection", "tcFitText", "vAlign", "hideMark"],
    "trPr": ["cnfStyle", "divId", "gridBefore", "gridAfter", "wBefore", "wAfter", "cantSplit", "trHeight",
             "tblHeader", "tblCellSpacing", "jc", "hidden"],
    "settings": ["updateFields", "hdrShapeDefaults", "footnotePr", "endnotePr", "compat", "docVars", "rsids",
                 "mathPr", "attachedSchema", "themeFontLang", "clrSchemeMapping", "doNotIncludeSubdocsInStats",
                 "doNotAutoCompressPictures", "forceUpgrade", "captions", "readModeInkLockDown", "smartTagType",
                 "schemaLibrary", "shapeDefaults", "doNotEmbedSmartTags", "decimalSymbol", "listSeparator"],
}


def _local(element):
    return element.tag.split("}")[1] if "}" in element.tag else element.tag


def inserer(parent, element):
    """Ajoute element dans parent à sa place (ORDRES), en remplaçant un élément de même nom."""
    nom = _local(element)
    for ancien in parent.findall(element.tag):
        parent.remove(ancien)
    ordre = ORDRES[_local(parent)]
    suivants = set(ordre[ordre.index(nom) + 1:])
    for enfant in parent:
        if _local(enfant) in suivants:
            enfant.addprevious(element)
            return element
    parent.append(element)
    return element


def ombrer(element_pr, couleur):
    """Ombrage « clear » (jamais « solid », qui rend noir) sur un tcPr ou un pPr."""
    return inserer(element_pr, _el("w:shd", w__val="clear", w__color="auto", w__fill=couleur))


def champ(paragraphe, instruction, resultat="", gras=False, taille=None, italique=False):
    """Champ Word (PAGE, NUMPAGES, SEQ…) avec sa valeur en cache, que LibreOffice affiche.
    La mise en forme va sur toutes les parties du champ (LibreOffice prend celle du début)."""
    runs = []

    def run_avec(elem=None, texte=None):
        r = paragraphe.add_run(texte) if texte is not None else paragraphe.add_run()
        if elem is not None:
            r._r.append(elem)
        r.bold = gras
        r.italic = italique
        if taille:
            r.font.size = Pt(taille)
        runs.append(r)
        return r
    run_avec(_el("w:fldChar", w__fldCharType="begin"))
    instr = _el("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = f" {instruction} "
    run_avec(instr)
    run_avec(_el("w:fldChar", w__fldCharType="separate"))
    r = run_avec(texte=resultat)
    run_avec(_el("w:fldChar", w__fldCharType="end"))
    return r


# ------------------------------------------------------------------ texte : gras, code, italique

INLINE = re.compile(r"(\*\*.+?\*\*|`[^`]+`|__.+?__)")
ESPACES_FINES = [(re.compile(r" ([:;!?»])"), "\u00a0\\1"), (re.compile(r"« "), "«\u00a0"),
                 (re.compile(r"(\d) (\d{3})(?!\d)"), "\\1\u202f\\2"),
                 (re.compile(r"(\d) (%|°|m/s|rad/s|m|cm|mm|km|s|ms|min|h|Hz|Go|Mo|Ko|px|pixels|dpi|pt)(?![\w/])"),
                  "\\1\u00a0\\2")]


def typographie(texte):
    for motif, rempl in ESPACES_FINES:
        texte = motif.sub(rempl, texte)
        if motif.pattern.startswith("(\\d)"):
            texte = motif.sub(rempl, texte)       # 1 234 567 : deux passages
    return texte


class Generateur:
    def __init__(self, valeurs, captures, pages_titres=None):
        self.valeurs = valeurs
        self.captures = captures
        self.pages_titres = pages_titres or {}
        self.doc = Document()
        self.titres = []            # (niveau, numero, texte) des titres 1 et 2, pour la table
        self.compteurs = [0, 0, 0]
        self.nb_figures = 0
        self.nb_tableaux = 0
        self.prochain_num = 100
        self.captures_utilisees = []
        self.schemas_utilises = []
        self._preparer()

    # ---------------------------------------------------------------- préparation

    def remplir(self, texte):
        return re.sub(r"\[\[(\w+)\]\]", lambda m: str(self.valeurs.get(m.group(1), m.group(0))), texte)

    def _preparer(self):
        doc = self.doc
        section = doc.sections[0]
        section.page_width, section.page_height = Cm(LARGEUR_PAGE_CM), Cm(29.7)
        section.left_margin = section.right_margin = Cm(MARGE_CM)
        section.top_margin, section.bottom_margin = Cm(2.3), Cm(2.0)
        section.header_distance, section.footer_distance = Cm(1.0), Cm(1.0)
        section.different_first_page_header_footer = True

        styles = doc.styles
        # Police et langue par défaut (rPrDefault) : Calibri 11, français
        rpr_defaut = doc.styles.element.find(qn("w:docDefaults")).find(qn("w:rPrDefault")).find(qn("w:rPr"))
        polices = rpr_defaut.find(qn("w:rFonts"))
        if polices is None:
            polices = _el("w:rFonts")
            rpr_defaut.insert(0, polices)
        for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
            polices.set(qn(attr), POLICE)
        for attr in ("w:asciiTheme", "w:hAnsiTheme", "w:cstheme", "w:eastAsiaTheme"):
            if polices.get(qn(attr)) is not None:
                del polices.attrib[qn(attr)]
        langue = rpr_defaut.find(qn("w:lang"))
        if langue is None:
            langue = _el("w:lang")
            rpr_defaut.append(langue)
        langue.set(qn("w:val"), "fr-FR")
        langue.set(qn("w:eastAsia"), "fr-FR")
        langue.set(qn("w:bidi"), "ar-SA")

        normal = styles["Normal"]
        normal.font.name = POLICE
        normal.font.size = Pt(11)
        pf = normal.paragraph_format
        pf.space_before = Pt(0)
        pf.space_after = Pt(5)
        pf.line_spacing = 1.1
        pf.widow_control = True

        tailles = {1: 17, 2: 13.5, 3: 11.5}
        avant = {1: 0, 2: 12, 3: 9}
        apres = {1: 10, 2: 5, 3: 3}
        for niveau in (1, 2, 3):
            st = styles[f"Heading {niveau}"]
            st.font.name = POLICE
            st.font.size = Pt(tailles[niveau])
            st.font.bold = True
            st.font.italic = False
            st.font.color.rgb = BLEU
            rpr = st.element.get_or_add_rPr()
            rf = rpr.find(qn("w:rFonts"))
            if rf is None:
                rf = _el("w:rFonts")
                rpr.insert(0, rf)
            for attr in list(rf.attrib):
                del rf.attrib[attr]
            for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
                rf.set(qn(attr), POLICE)
            f = st.paragraph_format
            f.space_before = Pt(avant[niveau])
            f.space_after = Pt(apres[niveau])
            f.keep_with_next = True
            f.page_break_before = niveau == 1
            f.line_spacing = 1.0
        # Filet sous les titres de chapitre
        ppr = styles["Heading 1"].element.get_or_add_pPr()
        bordures = _el("w:pBdr")
        bordures.append(_el("w:bottom", w__val="single", w__sz="8", w__space="4", w__color="1F3A5F"))
        inserer(ppr, bordures)

        self._style_paragraphe("Code", taille=9, police=POLICE_CODE, apres=6, avant=2, interligne=1.0,
                               retrait_gauche=0.25, couleur_fond=GRIS_CODE)
        self._style_paragraphe("Legende", taille=9, italique=True, apres=8, avant=2, centre=True,
                               couleur=RGBColor(0x40, 0x4A, 0x58))
        self._style_paragraphe("Chapeau", taille=10.5, italique=True, apres=8, couleur=RGBColor(0x33, 0x3D, 0x4A))
        self._style_paragraphe("Cellule", taille=9.5, apres=0, interligne=1.0)
        self._style_paragraphe("Titre TDM", taille=17, gras=True, couleur=BLEU, apres=10)
        for niveau in (1, 2):
            # vague 6 : 112 titres ; 9,5 pt et peu d'espace pour que la table tienne sur deux pages
            st = self._style_paragraphe(f"toc {niveau}", taille=10.5 if niveau == 1 else 9.5, gras=niveau == 1,
                                        apres=1 if niveau == 1 else 0.5, avant=2.5 if niveau == 1 else 0,
                                        interligne=1.0, retrait_gauche=0 if niveau == 1 else 0.6)
            st.element.set(qn("w:styleId"), f"TOC{niveau}")
            tabs = st.paragraph_format.tab_stops
            tabs.add_tab_stop(Cm(0.8 if niveau == 1 else 1.7))
            tabs.add_tab_stop(Cm(LARGEUR_TEXTE_CM), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS)

        self._numerotations()
        self._entete_pied()
        inserer(doc.settings.element, _el("w:updateFields", w__val="true"))
        zoom = doc.settings.element.find(qn("w:zoom"))
        if zoom is not None and zoom.get(qn("w:percent")) is None:
            zoom.set(qn("w:percent"), "100")         # attribut obligatoire (schéma OOXML)

        cp = doc.core_properties
        cp.title = "Atelier G1 : le logiciel du robot d'accueil, de A à Z"
        cp.subject = "Documentation de référence du logiciel du projet robot d'accueil Unitree G1 EDU"
        cp.author = "Claude (IA), pour le projet robot d'accueil G1"
        cp.language = "fr-FR"
        cp.keywords = "Atelier G1, ROS 2, Nav2, Gazebo, Unitree G1, documentation"

    def _style_paragraphe(self, nom, taille=11, police=None, gras=False, italique=False, apres=4, avant=0,
                          interligne=1.1, retrait_gauche=0.0, centre=False, couleur=None, couleur_fond=None):
        styles = self.doc.styles
        try:
            st = styles[nom]
        except KeyError:
            st = styles.add_style(nom, WD_STYLE_TYPE.PARAGRAPH)
        st.base_style = styles["Normal"]
        st.font.size = Pt(taille)
        st.font.bold = gras
        st.font.italic = italique
        if police:
            st.font.name = police
            rpr = st.element.get_or_add_rPr()
            rf = rpr.find(qn("w:rFonts"))
            for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
                rf.set(qn(attr), police)
        if couleur is not None:
            st.font.color.rgb = couleur
        f = st.paragraph_format
        f.space_after = Pt(apres)
        f.space_before = Pt(avant)
        f.line_spacing = interligne
        f.left_indent = Cm(retrait_gauche)
        if centre:
            f.alignment = WD_ALIGN_PARAGRAPH.CENTER
        if couleur_fond:
            ombrer(st.element.get_or_add_pPr(), couleur_fond)
        return st

    def _numerotations(self):
        numerotation = self.doc.part.numbering_part.element
        titres = f"""
        <w:abstractNum {nsdecls('w')} w:abstractNumId="{ID_ABSTRAIT_TITRES}">
          <w:multiLevelType w:val="multilevel"/>
          <w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:pStyle w:val="Heading1"/>
            <w:lvlText w:val="%1."/><w:lvlJc w:val="left"/><w:pPr><w:ind w:left="567" w:hanging="567"/></w:pPr></w:lvl>
          <w:lvl w:ilvl="1"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:pStyle w:val="Heading2"/>
            <w:lvlText w:val="%1.%2"/><w:lvlJc w:val="left"/><w:pPr><w:ind w:left="737" w:hanging="737"/></w:pPr></w:lvl>
          <w:lvl w:ilvl="2"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:pStyle w:val="Heading3"/>
            <w:lvlText w:val="%1.%2.%3"/><w:lvlJc w:val="left"/><w:pPr><w:ind w:left="850" w:hanging="850"/></w:pPr></w:lvl>
        </w:abstractNum>"""
        puces = f"""
        <w:abstractNum {nsdecls('w')} w:abstractNumId="{ID_ABSTRAIT_PUCES}">
          <w:multiLevelType w:val="hybridMultilevel"/>
          <w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="•"/><w:lvlJc w:val="left"/>
            <w:pPr><w:ind w:left="454" w:hanging="284"/></w:pPr><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/></w:rPr></w:lvl>
          <w:lvl w:ilvl="1"><w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="–"/><w:lvlJc w:val="left"/>
            <w:pPr><w:ind w:left="851" w:hanging="284"/></w:pPr><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/></w:rPr></w:lvl>
          <w:lvl w:ilvl="2"><w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="▪"/><w:lvlJc w:val="left"/>
            <w:pPr><w:ind w:left="1247" w:hanging="284"/></w:pPr><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/></w:rPr></w:lvl>
        </w:abstractNum>"""
        numeros = f"""
        <w:abstractNum {nsdecls('w')} w:abstractNumId="{ID_ABSTRAIT_NUMEROS}">
          <w:multiLevelType w:val="hybridMultilevel"/>
          <w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/><w:lvlJc w:val="left"/>
            <w:pPr><w:ind w:left="454" w:hanging="340"/></w:pPr></w:lvl>
          <w:lvl w:ilvl="1"><w:start w:val="1"/><w:numFmt w:val="lowerLetter"/><w:lvlText w:val="%2)"/><w:lvlJc w:val="left"/>
            <w:pPr><w:ind w:left="907" w:hanging="340"/></w:pPr></w:lvl>
        </w:abstractNum>"""
        premier_num = numerotation.find(qn("w:num"))
        for xml in (titres, puces, numeros):
            element = parse_xml(xml)
            if premier_num is not None:
                premier_num.addprevious(element)
            else:
                numerotation.append(element)
        for num_id, abstrait in ((ID_NUM_TITRES, ID_ABSTRAIT_TITRES), (ID_NUM_PUCES, ID_ABSTRAIT_PUCES)):
            numerotation.append(parse_xml(
                f'<w:num {nsdecls("w")} w:numId="{num_id}"><w:abstractNumId w:val="{abstrait}"/></w:num>'))
        # les titres 1 à 3 portent la numérotation dans leur style
        for niveau in (1, 2, 3):
            ppr = self.doc.styles[f"Heading {niveau}"].element.get_or_add_pPr()
            num_pr = ppr.get_or_add_numPr()
            num_pr.get_or_add_ilvl().val = niveau - 1
            num_pr.get_or_add_numId().val = ID_NUM_TITRES

    def _nouvelle_liste_numerotee(self):
        numerotation = self.doc.part.numbering_part.element
        self.prochain_num += 1
        numerotation.append(parse_xml(
            f'<w:num {nsdecls("w")} w:numId="{self.prochain_num}"><w:abstractNumId w:val="{ID_ABSTRAIT_NUMEROS}"/>'
            f'<w:lvlOverride w:ilvl="0"><w:startOverride w:val="1"/></w:lvlOverride></w:num>'))
        return self.prochain_num

    def _entete_pied(self):
        section = self.doc.sections[0]
        for nom in ("Header", "Footer"):
            tabs = self.doc.styles[nom].paragraph_format.tab_stops
            tabs.clear_all()
            tabs.add_tab_stop(Cm(LARGEUR_TEXTE_CM / 2), WD_TAB_ALIGNMENT.CENTER)
            tabs.add_tab_stop(Cm(LARGEUR_TEXTE_CM), WD_TAB_ALIGNMENT.RIGHT)
        entete = section.header.paragraphs[0]
        entete.text = ""
        r = entete.add_run("Atelier G1 · le logiciel du robot d'accueil, de A à Z")
        r.font.size = Pt(8.5)
        r.font.color.rgb = RGBColor(0x55, 0x60, 0x70)
        r = entete.add_run("\t\t" + "État du " + self.valeurs.get("date", ""))
        r.font.size = Pt(8.5)
        r.font.color.rgb = RGBColor(0x55, 0x60, 0x70)
        bordure = _el("w:pBdr")
        bordure.append(_el("w:bottom", w__val="single", w__sz="4", w__space="3", w__color="B4BFCC"))
        inserer(entete._p.get_or_add_pPr(), bordure)

        pied = section.footer.paragraphs[0]
        pied.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = pied.add_run("Page ")
        r.font.size = Pt(9)
        champ(pied, "PAGE", "1", taille=9)
        r = pied.add_run(" sur ")
        r.font.size = Pt(9)
        champ(pied, "NUMPAGES", "1", taille=9)

    # ---------------------------------------------------------------- texte

    def texte(self, paragraphe, texte, gras=False, italique=False, taille=None, couleur=None):
        texte = self.remplir(texte)
        for morceau in INLINE.split(texte):
            if not morceau:
                continue
            if morceau.startswith("**") and morceau.endswith("**") and len(morceau) > 4:
                self.texte(paragraphe, morceau[2:-2], gras=True, italique=italique, taille=taille, couleur=couleur)
                continue
            if morceau.startswith("__") and morceau.endswith("__") and len(morceau) > 4:
                self.texte(paragraphe, morceau[2:-2], gras=gras, italique=True, taille=taille, couleur=couleur)
                continue
            if morceau.startswith("`") and morceau.endswith("`") and len(morceau) > 2:
                r = paragraphe.add_run(morceau[1:-1])
                r.font.name = POLICE_CODE
                r.font.size = Pt((taille or 11) * 0.86)
                r.font.color.rgb = RGBColor(0x1C, 0x3D, 0x6E)
                r.bold = gras
                r.italic = italique
                continue
            r = paragraphe.add_run(typographie(morceau))
            r.bold = gras or None
            r.italic = italique or None
            if taille:
                r.font.size = Pt(taille)
            if couleur is not None:
                r.font.color.rgb = couleur
        return paragraphe

    def paragraphe(self, texte, style=None, garder=False):
        p = self.doc.add_paragraph(style=style)
        self.texte(p, texte)
        if garder or texte.rstrip().endswith(":"):
            p.paragraph_format.keep_with_next = True
        return p

    def titre(self, niveau, texte):
        texte = self.remplir(texte)
        self.compteurs[niveau - 1] += 1
        for i in range(niveau, 3):
            self.compteurs[i] = 0
        numero = ".".join(str(n) for n in self.compteurs[:niveau])
        if niveau == 1:
            numero += "."
        if niveau <= 2:
            self.titres.append((niveau, numero, texte))
        p = self.doc.add_heading(level=niveau)
        p.add_run(typographie(texte))
        return p

    # ---------------------------------------------------------------- listes

    def liste(self, elements, numerotee=False, niveau=0, num_id=None, dans=None):
        if num_id is None:
            num_id = self._nouvelle_liste_numerotee() if numerotee else ID_NUM_PUCES
        conteneur = dans if dans is not None else self.doc
        for element in elements:
            if isinstance(element, (list, tuple)) and len(element) == 2 and isinstance(element[1], list):
                texte, sous = element
            else:
                texte, sous = element, None
            p = conteneur.add_paragraph(style="Cellule" if dans is not None else None)
            self.texte(p, texte)
            ppr = p._p.get_or_add_pPr()
            num_pr = ppr.get_or_add_numPr()
            num_pr.get_or_add_ilvl().val = niveau
            num_pr.get_or_add_numId().val = num_id
            p.paragraph_format.space_after = Pt(2.5)
            if sous:
                self.liste(sous, numerotee=False, niveau=niveau + 1, dans=dans)
        if dans is None and niveau == 0:
            # un peu d'air après la liste
            dernier = self.doc.paragraphs[-1]
            dernier.paragraph_format.space_after = Pt(6)

    # ---------------------------------------------------------------- tableaux

    def legende(self, prefixe, texte, avant=False):
        p = self.doc.add_paragraph(style="Legende")
        r = p.add_run(f"{prefixe} ")
        r.bold = True
        r.italic = False
        compteur = self.nb_tableaux if prefixe == "Tableau" else self.nb_figures
        champ(p, f"SEQ {prefixe} \\* ARABIC", str(compteur), gras=True)
        r = p.add_run(" – ")
        r.italic = False
        self.texte(p, texte)
        if avant:
            p.paragraph_format.keep_with_next = True
            p.paragraph_format.space_before = Pt(6)
            p.paragraph_format.space_after = Pt(3)
        return p

    def tableau(self, entetes, lignes, largeurs=None, taille=9.5, legende=None, premiere_col_gras=False,
                zebre=True, couleur_entete=BLEU_CLAIR):
        n = len(entetes) if entetes else len(lignes[0])
        if largeurs is None:
            largeurs = [LARGEUR_TEXTE_CM / n] * n
        total = sum(largeurs)
        largeurs = [l * LARGEUR_TEXTE_CM / total for l in largeurs] if total > LARGEUR_TEXTE_CM + 0.01 else largeurs
        if legende:
            self.nb_tableaux += 1
            self.legende("Tableau", legende, avant=True)
        nb_lignes = len(lignes) + (1 if entetes else 0)
        table = self.doc.add_table(rows=nb_lignes, cols=n)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.autofit = False
        tbl_pr = table._tbl.tblPr
        largeur_dxa = int(sum(largeurs) * 567)
        inserer(tbl_pr, _el("w:tblW", w__w=str(largeur_dxa), w__type="dxa"))
        bordures = _el("w:tblBorders")
        for cote in ("top", "left", "bottom", "right", "insideH", "insideV"):
            bordures.append(_el(f"w:{cote}", w__val="single", w__sz="4", w__space="0", w__color=BORDURE))
        inserer(tbl_pr, bordures)
        inserer(tbl_pr, _el("w:tblLayout", w__type="fixed"))
        marges = _el("w:tblCellMar")
        marges.append(_el("w:top", w__w="28", w__type="dxa"))
        marges.append(_el("w:left", w__w="85", w__type="dxa"))
        marges.append(_el("w:bottom", w__w="28", w__type="dxa"))
        marges.append(_el("w:right", w__w="85", w__type="dxa"))
        inserer(tbl_pr, marges)
        for i, l in enumerate(largeurs):
            table.columns[i].width = Cm(l)
        toutes = ([entetes] if entetes else []) + list(lignes)
        for i, valeurs in enumerate(toutes):
            ligne = table.rows[i]
            tr_pr = ligne._tr.get_or_add_trPr()
            inserer(tr_pr, _el("w:cantSplit"))
            est_entete = bool(entetes) and i == 0
            if est_entete:
                inserer(tr_pr, _el("w:tblHeader"))
            for j in range(n):
                cellule = ligne.cells[j]
                cellule.width = Cm(largeurs[j])
                valeur = valeurs[j] if j < len(valeurs) else ""
                tc_pr = cellule._tc.get_or_add_tcPr()
                if est_entete:
                    ombrer(tc_pr, couleur_entete)
                elif zebre and i % 2 == 0:
                    ombrer(tc_pr, ZEBRE)
                self._remplir_cellule(cellule, valeur, taille, gras=est_entete or (premiere_col_gras and j == 0))
        self._pas_de_ligne_seule(table, bool(entetes))
        espace = self.doc.add_paragraph()
        espace.paragraph_format.space_after = Pt(4)
        espace.paragraph_format.line_spacing = 0.8
        return table

    @staticmethod
    def _pas_de_ligne_seule(table, avec_entete):
        """Un petit tableau reste sur une page ; un grand ne laisse jamais une ligne seule en haut ou en
        bas d'une page (« garder avec le suivant » sur les paragraphes des lignes concernées)."""
        lignes = table.rows
        n = len(lignes)

        def garder(i):
            for cellule in lignes[i].cells:
                for p in cellule.paragraphs:
                    p.paragraph_format.keep_with_next = True
        if n <= 7:
            for i in range(n - 1):
                garder(i)
        elif n >= 3:
            garder(0)
            if avec_entete:
                garder(1)
            garder(n - 2)

    def _remplir_cellule(self, cellule, valeur, taille, gras=False):
        premier = cellule.paragraphs[0]
        premier.style = self.doc.styles["Cellule"]
        if isinstance(valeur, list):            # liste à puces dans la cellule
            cellule._tc.remove(premier._p)
            self.liste(valeur, dans=cellule)
            for p in cellule.paragraphs:
                for r in p.runs:
                    r.font.size = Pt(taille)
            return
        morceaux = str(valeur).split("\n")
        for k, morceau in enumerate(morceaux):
            p = premier if k == 0 else cellule.add_paragraph(style="Cellule")
            self.texte(p, morceau, gras=gras, taille=taille)

    # ---------------------------------------------------------------- code, encadrés, images

    def code(self, texte):
        p = self.doc.add_paragraph(style="Code")
        lignes = self.remplir(texte).strip("\n").split("\n")
        if len(lignes) <= 25:
            p.paragraph_format.keep_together = True
        for ligne in lignes:
            if len(ligne) > LIGNE_CODE_MAX:
                print(f"  attention : ligne de code de {len(ligne)} caractères (coupée à l'affichage) : {ligne[:50]}…")
        for k, ligne in enumerate(lignes):
            r = p.add_run(ligne)
            if k < len(lignes) - 1:
                r.add_break()
        return p

    def encadre(self, titre, contenu, couleur="EAF1E4", bord="70AD47"):
        table = self.doc.add_table(rows=1, cols=1)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.autofit = False
        tbl_pr = table._tbl.tblPr
        bordures = _el("w:tblBorders")
        bordures.append(_el("w:top", w__val="nil"))
        bordures.append(_el("w:left", w__val="single", w__sz="24", w__space="0", w__color=bord))
        bordures.append(_el("w:bottom", w__val="nil"))
        bordures.append(_el("w:right", w__val="nil"))
        inserer(tbl_pr, bordures)
        inserer(tbl_pr, _el("w:tblLayout", w__type="fixed"))
        table.columns[0].width = Cm(LARGEUR_TEXTE_CM - 0.4)
        cellule = table.rows[0].cells[0]
        cellule.width = Cm(LARGEUR_TEXTE_CM - 0.4)
        ombrer(cellule._tc.get_or_add_tcPr(), couleur)
        inserer(table.rows[0]._tr.get_or_add_trPr(), _el("w:cantSplit"))
        p = cellule.paragraphs[0]
        p.style = self.doc.styles["Cellule"]
        p.paragraph_format.space_after = Pt(2)
        self.texte(p, titre, gras=True, taille=10.5)
        elements = contenu if isinstance(contenu, list) else [contenu]
        puces = [e for e in elements if isinstance(e, str) and e.startswith("- ")]
        for e in elements:
            if isinstance(e, str) and e.startswith("- "):
                continue
            q = cellule.add_paragraph(style="Cellule")
            q.paragraph_format.space_after = Pt(2)
            self.texte(q, e, taille=10)
        if puces:
            self.liste([e[2:] for e in puces], dans=cellule)
            for q in cellule.paragraphs:
                for r in q.runs:
                    if r.font.size is None:
                        r.font.size = Pt(10)
        espace = self.doc.add_paragraph()
        espace.paragraph_format.space_after = Pt(4)
        espace.paragraph_format.line_spacing = 0.8

    def image(self, chemin, largeur_cm, legende_texte, hauteur_max_cm=HAUTEUR_IMAGE_MAX_CM):
        taille = taille_png(chemin) if str(chemin).endswith(".png") else taille_jpeg(chemin)
        largeur_cm = min(largeur_cm, LARGEUR_TEXTE_CM)
        if taille:
            l, h = taille
            if largeur_cm * h / l > hauteur_max_cm:
                largeur_cm = hauteur_max_cm * l / h
        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.keep_with_next = True
        p.paragraph_format.space_before = Pt(4)
        p.paragraph_format.space_after = Pt(0)
        p.add_run().add_picture(str(chemin), width=Cm(largeur_cm))
        self.nb_figures += 1
        self.legende("Figure", legende_texte)

    def schema(self, nom, legende_texte, largeur_cm=LARGEUR_TEXTE_CM, hauteur_max_cm=HAUTEUR_IMAGE_MAX_CM):
        chemin = PNG_SCHEMAS / f"{nom}.png"
        if not chemin.exists():
            raise SystemExit(f"Schéma introuvable : {chemin} (schemas/{nom}.dot manque ?)")
        self.schemas_utilises.append(nom)
        self.image(chemin, largeur_cm, legende_texte, hauteur_max_cm)

    def dossiers_captures(self):
        """Les dossiers de captures qui existent, dans l'ordre donné (vague 5, puis vague 6)."""
        dossiers = self.captures if isinstance(self.captures, (list, tuple)) else [self.captures]
        return [d for d in dossiers if d and Path(d).is_dir()]

    def trouver_capture(self, motifs):
        for motif in motifs:
            for dossier in self.dossiers_captures():
                trouves = sorted(Path(dossier).rglob(motif))
                trouves = [t for t in trouves if t.suffix.lower() in (".png", ".jpg", ".jpeg")
                           and t not in self.captures_utilisees]
                if trouves:
                    return trouves[0]
        return None

    def capture(self, motifs, legende_texte, largeur_cm=LARGEUR_TEXTE_CM, hauteur_max_cm=12.5):
        chemin = self.trouver_capture(motifs)
        if chemin is None:
            return
        self.captures_utilisees.append(chemin)
        self.image(jpeg_de(chemin), largeur_cm, legende_texte, hauteur_max_cm)

    def captures_cote_a_cote(self, liste_motifs, legende_texte, largeur_cm=LARGEUR_TEXTE_CM, hauteur_max_cm=12.5):
        """Plusieurs captures (une liste de motifs par image) réunies côte à côte en une seule figure (la borne au
        téléphone : deux écrans étroits). Les images absentes sont sautées ; s'il n'en reste qu'une, elle seule."""
        chemins = []
        for motifs in liste_motifs:
            chemin = self.trouver_capture(motifs)
            if chemin is not None:
                self.captures_utilisees.append(chemin)
                chemins.append(chemin)
        if not chemins:
            return
        image = montage_de(chemins) if len(chemins) > 1 else jpeg_de(chemins[0])
        self.image(image, largeur_cm, legende_texte, hauteur_max_cm)

    def a_des_captures(self):
        return any(any(Path(d).rglob("*.png")) for d in self.dossiers_captures())

    # ---------------------------------------------------------------- table des matières

    def table_des_matieres(self, titres_prevus):
        """Champ TOC de Word (niveaux 1 et 2), avec les entrées déjà écrites : LibreOffice les affiche
        telles quelles, Word les refait à l'ouverture (updateFields)."""
        p = self.doc.add_paragraph(style="Titre TDM")
        p.add_run("Table des matières")
        if not titres_prevus:
            titres_prevus = [(1, "1.", "…")]
        for k, (niveau, numero, texte) in enumerate(titres_prevus):
            e = self.doc.add_paragraph(style=f"toc {niveau}")
            if k == 0:
                e.add_run()._r.append(_el("w:fldChar", w__fldCharType="begin"))
                instr = _el("w:instrText")
                instr.set(qn("xml:space"), "preserve")
                instr.text = ' TOC \\o "1-2" \\h \\z \\u '
                e.add_run()._r.append(instr)
                e.add_run()._r.append(_el("w:fldChar", w__fldCharType="separate"))
            page = self.pages_titres.get((numero, texte), "")
            e.add_run(f"{numero}\t{typographie(texte)}\t{page}")
            if k == len(titres_prevus) - 1:
                e.add_run()._r.append(_el("w:fldChar", w__fldCharType="end"))

    # ---------------------------------------------------------------- blocs

    def bloc(self, b):
        genre = b[0]
        if genre == "h1":
            self.titre(1, b[1])
        elif genre == "h2":
            self.titre(2, b[1])
        elif genre == "h3":
            self.titre(3, b[1])
        elif genre == "p":
            self.paragraphe(b[1])
        elif genre == "chapeau":
            self.paragraphe(b[1], style="Chapeau")
        elif genre == "puces":
            self.liste(b[1])
        elif genre == "num":
            self.liste(b[1], numerotee=True)
        elif genre == "table":
            d = b[1]
            self.tableau(d.get("entetes"), d["lignes"], d.get("largeurs"), d.get("taille", 9.5),
                         d.get("legende"), d.get("premiere_col_gras", False), d.get("zebre", True))
        elif genre == "code":
            self.code(b[1])
        elif genre == "encadre":
            couleurs = {"retenir": ("EAF1E4", "70AD47"), "attention": ("FBE9E7", "C0392B"),
                        "info": ("E8EEF8", "2F5597")}
            fond, bord = couleurs.get(b[3] if len(b) > 3 else "retenir")
            self.encadre(b[1], b[2], fond, bord)
        elif genre == "schema":
            largeur = b[3] if len(b) > 3 and b[3] else LARGEUR_TEXTE_CM
            hauteur = b[4] if len(b) > 4 and b[4] else HAUTEUR_IMAGE_MAX_CM
            self.schema(b[1], b[2], largeur, hauteur)
        elif genre == "capture":
            largeur = b[3] if len(b) > 3 and b[3] else LARGEUR_TEXTE_CM
            hauteur = b[4] if len(b) > 4 and b[4] else 12.5
            self.capture(b[1], b[2], largeur, hauteur)
        elif genre == "captures":
            largeur = b[3] if len(b) > 3 and b[3] else LARGEUR_TEXTE_CM
            hauteur = b[4] if len(b) > 4 and b[4] else 12.5
            self.captures_cote_a_cote(b[1], b[2], largeur, hauteur)
        elif genre == "si_captures":
            if self.a_des_captures():
                for sous in b[1]:
                    self.bloc(sous)
        elif genre == "sans_captures":
            if not self.a_des_captures():
                for sous in b[1]:
                    self.bloc(sous)
        elif genre == "fiche":
            self.fiche(b[1])
        elif genre == "saut":
            self.doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
        else:
            raise SystemExit(f"Bloc inconnu : {genre}")

    def fiche(self, d):
        self.titre(3, d["nom"])
        for cle, etiquette in (("quoi", "Ce que c'est."), ("pourquoi", "Pourquoi ce choix."),
                               ("ici", "Dans le projet."), ("exemple", "Exemple réel.")):
            if not d.get(cle):
                continue
            p = self.doc.add_paragraph()
            p.paragraph_format.space_after = Pt(2.5)
            r = p.add_run(etiquette + " ")
            r.bold = True
            r.font.color.rgb = BLEU
            self.texte(p, d[cle])
        self.doc.paragraphs[-1].paragraph_format.space_after = Pt(6)

    # ---------------------------------------------------------------- couverture

    def couverture(self, c):
        doc = self.doc
        for _ in range(3):
            doc.add_paragraph()
        p = doc.add_paragraph()
        r = p.add_run(c["surtitre"])
        r.font.size = Pt(12)
        r.font.color.rgb = RGBColor(0x55, 0x60, 0x70)
        r.bold = True
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(4)
        r = p.add_run(c["titre"])
        r.font.size = Pt(30)
        r.bold = True
        r.font.color.rgb = BLEU
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(18)
        r = p.add_run(typographie(c["sous_titre"]))
        r.font.size = Pt(15)
        r.font.color.rgb = RGBColor(0x2F, 0x55, 0x97)
        bordure = _el("w:pBdr")
        bordure.append(_el("w:bottom", w__val="single", w__sz="12", w__space="8", w__color="1F3A5F"))
        inserer(p._p.get_or_add_pPr(), bordure)
        self.paragraphe(c["resume"])
        doc.add_paragraph()
        self.tableau(None, c["fiche"], [4.2, 12.4], taille=10, premiere_col_gras=True, zebre=False)
        doc.add_paragraph()
        self.encadre(c["lecture_titre"], c["lecture"], "E8EEF8", "2F5597")

    # ---------------------------------------------------------------- tout

    def construire(self, couverture, chapitres, titres_prevus):
        self.couverture(couverture)
        self.doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
        self.table_des_matieres(titres_prevus)
        for blocs in chapitres:
            for b in blocs:
                self.bloc(b)
        return self.doc


# ------------------------------------------------------------------ captures en JPEG (plus léger)

def jpeg_de(chemin):
    """Une capture PNG devient un JPEG de qualité 88 dans controle/captures_jpeg (Pillow du système),
    pour un .docx plus léger ; sans Pillow, la capture reste en PNG."""
    chemin = Path(chemin)
    if chemin.suffix.lower() != ".png" or not Path("/usr/bin/python3").exists():
        return chemin
    CACHE_CAPTURES.mkdir(parents=True, exist_ok=True)
    cible = CACHE_CAPTURES / (re.sub(r"[^\w.-]", "_", str(chemin.relative_to(chemin.anchor))) + ".jpg")
    if cible.exists() and cible.stat().st_mtime >= chemin.stat().st_mtime:
        return cible
    code = ("import sys\nfrom PIL import Image\n"
            "im = Image.open(sys.argv[1]).convert('RGB')\n"
            "if im.width > 1600:\n    im = im.resize((1600, round(im.height * 1600 / im.width)), Image.LANCZOS)\n"
            "im.save(sys.argv[2], 'JPEG', quality=88, optimize=True)\n")
    r = subprocess.run(["/usr/bin/python3", "-I", "-c", code, str(chemin), str(cible)],
                       capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"})
    return cible if r.returncode == 0 and cible.exists() else chemin


def montage_de(chemins, hauteur=1100, marge=36):
    """Des captures mises à la même hauteur, côte à côte sur fond blanc, en un JPEG de controle/captures_jpeg
    (Pillow du système) ; sans Pillow, la première capture seule."""
    chemins = [Path(c) for c in chemins]
    CACHE_CAPTURES.mkdir(parents=True, exist_ok=True)
    nom = "montage_" + "_".join(re.sub(r"[^\w.-]", "_", c.stem) for c in chemins) + ".jpg"
    cible = CACHE_CAPTURES / nom
    if cible.exists() and all(cible.stat().st_mtime >= c.stat().st_mtime for c in chemins):
        return cible
    code = ("import sys\nfrom PIL import Image\n"
            "h, m = int(sys.argv[1]), int(sys.argv[2])\n"
            "ims = [Image.open(p).convert('RGB') for p in sys.argv[4:]]\n"
            "ims = [i.resize((round(i.width * h / i.height), h), Image.LANCZOS) for i in ims]\n"
            "w = sum(i.width for i in ims) + m * (len(ims) - 1)\n"
            "out = Image.new('RGB', (w, h), (255, 255, 255))\n"
            "x = 0\n"
            "for i in ims:\n    out.paste(i, (x, 0))\n    x += i.width + m\n"
            "out.save(sys.argv[3], 'JPEG', quality=90, optimize=True)\n")
    r = subprocess.run(["/usr/bin/python3", "-I", "-c", code, str(hauteur), str(marge), str(cible)]
                       + [str(c) for c in chemins], capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"})
    return cible if r.returncode == 0 and cible.exists() else jpeg_de(chemins[0])


# ------------------------------------------------------------------ contenu

def charger_contenu():
    import contenu.couverture as couv
    importlib.reload(couv)
    chapitres = []
    for n in range(1, NB_CHAPITRES + 1):
        module = importlib.import_module(f"contenu.chapitre_{n:02d}")
        importlib.reload(module)
        chapitres.append(module.BLOCS)
    return couv.COUVERTURE, chapitres


# ------------------------------------------------------------------ PDF de contrôle

def vers_pdf(docx):
    """Convertit le .docx en PDF avec LibreOffice (profil à part, polices proches de Calibri)."""
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        return None
    profil = CONTROLE / "profil_libreoffice"
    env = dict(os.environ, FONTCONFIG_FILE=str(CONTROLE / "fonts.conf"))
    cmd = [soffice, f"-env:UserInstallation=file://{profil}", "--headless", "--convert-to", "pdf",
           "--outdir", str(CONTROLE), str(docx)]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=300, env=env)
    except subprocess.SubprocessError:
        return None
    pdf = CONTROLE / (Path(docx).stem + ".pdf")
    return pdf if pdf.exists() else None


def pages_pdf(pdf):
    sortie = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, text=True).stdout
    return sortie.split("\f")


def _plat(texte):
    texte = texte.replace("\u00a0", " ").replace("\u202f", " ").replace("’", "'")
    return re.sub(r"\s+", " ", texte).strip()


def relever_pages(pdf, titres):
    """Page (physique, à partir de 1) de chaque titre 1 et 2, cherchée dans l'ordre du document."""
    pages = [[_plat(l) for l in page.splitlines() if l.strip()] for page in pages_pdf(pdf)]
    resultat = {}
    i = 1
    # les premières pages contiennent la table des matières : on cherche après elle
    for k, lignes in enumerate(pages):
        if any(l.startswith("Table des matières") for l in lignes):
            i = k + 1
    for niveau, numero, texte in titres:
        debut = _plat(f"{numero} {texte}")[:38]
        trouve = None
        for k in range(i, len(pages)):
            for l in pages[k]:
                ligne_de_table = re.search(r"(\.{3,}|…)\s*\d+$", l) or (
                    re.search(r"\s\d+$", l) and not re.search(r"\d$", texte))
                if l.startswith(debut) and not ligne_de_table:
                    trouve = k
                    break
            if trouve is not None:
                break
        if trouve is not None:
            resultat[(numero, texte)] = str(trouve + 1)
            i = trouve
    return resultat, len(pages) - (1 if pages and not pages[-1] else 0)


# ------------------------------------------------------------------ main

def generer(valeurs, captures, pages_titres, titres_prevus):
    couverture, chapitres = charger_contenu()
    g = Generateur(valeurs, captures, pages_titres)
    g.construire(couverture, chapitres, titres_prevus)
    g.doc.save(SORTIE)
    return g


def main():
    global SORTIE
    parser = argparse.ArgumentParser(description="Génère le document Word du logiciel de l'Atelier G1.")
    parser.add_argument("--captures", action="append",
                        help="dossier des captures de l'interface, plusieurs fois possible (défaut : "
                             + " puis ".join(str(d) for d in CAPTURES_DEFAUT) + ")")
    parser.add_argument("--sans-pdf", action="store_true", help="ne pas passer par LibreOffice")
    parser.add_argument("--images", action="store_true", help="pages du PDF en PNG (60 dpi) dans controle/pages/")
    parser.add_argument("--schemas", action="store_true", help="redessiner tous les schémas")
    parser.add_argument("--sortie", help="autre fichier .docx à écrire (défaut : %s)" % SORTIE.name)
    args = parser.parse_args()
    if args.sortie:
        SORTIE = Path(args.sortie).expanduser().resolve()

    os.chdir(ICI)
    CONTROLE.mkdir(exist_ok=True)
    print("Schémas…")
    dessiner_schemas(forcer=args.schemas)
    print("Chiffres du dépôt…")
    valeurs = chiffres()
    captures = [Path(d).expanduser() for d in (args.captures or CAPTURES_DEFAUT)]

    # Passe 1 : liste des titres (numéros de page inconnus)
    g = generer(valeurs, captures, {}, None)
    titres = g.titres
    g = generer(valeurs, captures, {}, titres)
    pages = {}
    nb_pages = None
    if not args.sans_pdf:
        for passe in range(1, 5):
            pdf = vers_pdf(SORTIE)
            if pdf is None:
                print("LibreOffice indisponible : table des matières sans numéros de page (Word les mettra).")
                break
            nouvelles, nb_pages = relever_pages(pdf, titres)
            manquants = [t for t in titres if (t[1], t[2]) not in nouvelles]
            if manquants:
                print(f"  {len(manquants)} titre(s) non retrouvé(s) dans le PDF : " +
                      " ; ".join(f"{n} {t}" for _, n, t in manquants[:5]))
            if nouvelles == pages:
                break
            pages = nouvelles
            g = generer(valeurs, captures, pages, titres)
            print(f"  passe {passe} : {nb_pages} pages, table des matières mise à jour")
    print(f"Écrit : {SORTIE}")
    print(f"  {len([t for t in titres if t[0] == 1])} chapitres, {len(titres)} titres dans la table, "
          f"{g.nb_figures} figures (schémas : {len(set(g.schemas_utilises))}, captures : "
          f"{len(g.captures_utilisees)}), {g.nb_tableaux} tableaux légendés"
          + (f", {nb_pages} pages (PDF de contrôle)" if nb_pages else ""))
    if args.images and not args.sans_pdf:
        pdf = CONTROLE / (SORTIE.stem + ".pdf")
        dossier = CONTROLE / "pages"
        if dossier.exists():
            shutil.rmtree(dossier)
        dossier.mkdir()
        subprocess.run(["pdftoppm", "-r", "60", "-png", str(pdf), str(dossier / "page")], check=False)
        print(f"  pages en images : {dossier}")


if __name__ == "__main__":
    main()
