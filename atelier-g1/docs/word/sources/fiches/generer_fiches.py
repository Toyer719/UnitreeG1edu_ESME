#!/usr/bin/env python3
"""
Fiches Word de la séance robot n° 2 (Atelier G1, vague 5 : 31/10/2026, mises à jour le 01/11 après la recette,
puis après la relecture critique du soir, la correction du verrou et sa relecture : section 12.15 du plan ;
vague 6 : 10/11/2026, « Vérifier le robot », boîte noire, voix et démo d'accueil en option : section 13 du plan).

    /home/joonho/robot-g1-donnees/venv-docx/bin/python \
        /home/joonho/robot-g1-donnees/vague5/documents/fiches/generer_fiches.py

Écrit, dans le dossier de ce fichier :
    Seance2_A_faire.docx     « Ce qu'il faut faire » : le déroulé pas à pas, commandes exactes
    Seance2_A_remplir.docx   « Feuille de résultats à remplir »
    schemas/*.dot, *.png     les schémas (Graphviz, 200 dpi, police DejaVu Sans)

Sources (lecture seule) : ~/robot-g1/docs/tutoriel-seance-2.md, docs/releves/seance-2.md,
docs/tutoriel-seance-1.md, docs/seance-robot.md ; commandes vérifiées dans bin/, ws/src, docker/.
"""
import math
import re
import subprocess
from pathlib import Path

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_ROW_HEIGHT_RULE
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Mm, Pt, RGBColor
from docx.table import _Cell
from docx.text.paragraph import Paragraph

ICI = Path(__file__).resolve().parent
SCHEMAS = ICI / "schemas"

POLICE = "Calibri"            # Carlito (même chasse) la remplace dans LibreOffice quand elle est installée
MONO = "Courier New"          # Liberation Mono (même chasse) la remplace sous Linux
SYMBOLES = "Segoe UI Symbol"  # ☐ ☒ ✓ ; DejaVu Sans les dessine sous Linux
LARGEUR = 17.4                # cm de texte utile : A4, marges de 1,8 cm
RETRAIT = 0.8                 # cm : début du texte d'un élément de liste

C = dict(bleu_fonce="184F95", bleu="1C5CAB", bleu_vif="2A78D6", bleu_clair="CDE2FB", bleu_pale="EAF2FC",
         texte="1F1F1F", texte2="4D4D4D", gris="6B6B6B", gris_code="F3F4F6", bordure="A6A6A6",
         vert="1E7B3C", vert_pale="E8F5EC", ambre="8A5A00", ambre_pale="FFF4DB", rouge="B42318",
         rouge_pale="FDECEC", gris_temps="8A8A8A", gris_temps_pale="E3E3E3", blanc="FFFFFF")

GENRES = {  # encadrés : (fond, couleur du filet et du titre)
    "info": (C["bleu_pale"], C["bleu"]),
    "ok": (C["vert_pale"], C["vert"]),
    "attention": (C["ambre_pale"], C["ambre"]),
    "danger": (C["rouge_pale"], C["rouge"]),
    "neutre": (C["gris_code"], C["gris"]),
}

# Ordre des enfants imposé par le schéma OOXML (Word refuse un ordre faux)
ORDRE = {
    "pPr": ["pStyle", "keepNext", "keepLines", "pageBreakBefore", "framePr", "widowControl", "numPr",
            "suppressLineNumbers", "pBdr", "shd", "tabs", "suppressAutoHyphens", "kinsoku", "wordWrap",
            "overflowPunct", "topLinePunct", "autoSpaceDE", "autoSpaceDN", "bidi", "adjustRightInd",
            "snapToGrid", "spacing", "ind", "contextualSpacing", "mirrorIndents", "suppressOverlap", "jc",
            "textDirection", "textAlignment", "textboxTightWrap", "outlineLvl", "divId", "cnfStyle", "rPr",
            "sectPr", "pPrChange"],
    "rPr": ["rStyle", "rFonts", "b", "bCs", "i", "iCs", "caps", "smallCaps", "strike", "dstrike", "outline",
            "shadow", "emboss", "imprint", "noProof", "snapToGrid", "vanish", "webHidden", "color", "spacing",
            "w", "kern", "position", "sz", "szCs", "highlight", "u", "effect", "bdr", "shd", "fitText",
            "vertAlign", "rtl", "cs", "em", "lang", "eastAsianLayout", "specVanish", "oMath"],
    "tcPr": ["cnfStyle", "tcW", "gridSpan", "hMerge", "vMerge", "tcBorders", "shd", "noWrap", "tcMar",
             "textDirection", "tcFitText", "vAlign", "hideMark", "headers", "cellIns", "cellDel", "cellMerge",
             "tcPrChange"],
    "trPr": ["cnfStyle", "divId", "gridBefore", "gridAfter", "wBefore", "wAfter", "cantSplit", "trHeight",
             "tblHeader", "tblCellSpacing", "jc", "hidden", "ins", "del", "trPrChange"],
    "tblPr": ["tblStyle", "tblpPr", "tblOverlap", "bidiVisual", "tblStyleRowBandSize", "tblStyleColBandSize",
              "tblW", "jc", "tblCellSpacing", "tblInd", "tblBorders", "shd", "tblLayout", "tblCellMar",
              "tblLook", "tblCaption", "tblDescription", "tblPrChange"],
}

W14 = "http://schemas.microsoft.com/office/word/2010/wordml"


# =====================================================================================================
# Outils XML
# =====================================================================================================

def el(tag, **attrs):
    """Élément w:… avec ses attributs w:… (valeurs converties en texte)."""
    e = OxmlElement(tag)
    for cle, valeur in attrs.items():
        e.set(qn("w:" + cle), str(valeur))
    return e


def poser(parent, enfant):
    """Place enfant dans parent à la place que le schéma lui donne (et remplace l'ancien du même nom)."""
    nom = parent.tag.split("}")[1]
    ordre = [qn("w:" + n) for n in ORDRE[nom]]
    for ancien in parent.findall(enfant.tag):
        parent.remove(ancien)
    rang = ordre.index(enfant.tag)
    for c in parent:
        if c.tag in ordre and ordre.index(c.tag) > rang:
            c.addprevious(enfant)
            return enfant
    parent.append(enfant)
    return enfant


def garder_avant(element):
    """Le bloc qui précède element (paragraphe ou tableau) reste sur la même page que lui."""
    prec = element.getprevious()
    if prec is None:
        return
    if prec.tag == qn("w:p"):
        poser(prec.get_or_add_pPr(), el("w:keepNext"))
    elif prec.tag == qn("w:tbl"):
        for q in prec.iter(qn("w:p")):
            poser(q.get_or_add_pPr(), el("w:keepNext"))


def garder_lignes(t, sauf_derniere=True):
    """Les lignes d'un tableau restent ensemble (keep with next sur leurs paragraphes)."""
    lignes = t.rows[:-1] if sauf_derniere else t.rows
    for row in lignes:
        for q in row._tr.iter(qn("w:p")):
            poser(q.get_or_add_pPr(), el("w:keepNext"))


def dxa(cm):
    return int(round(cm * 567))


def ombrer_cellule(cellule, couleur):
    poser(cellule._tc.get_or_add_tcPr(), el("w:shd", val="clear", color="auto", fill=couleur))


def ombrer_paragraphe(p, couleur):
    poser(p._p.get_or_add_pPr(), el("w:shd", val="clear", color="auto", fill=couleur))


def filet_paragraphe(p, cote, couleur, taille=6, espace=4):
    pPr = p._p.get_or_add_pPr()
    bdr = pPr.find(qn("w:pBdr"))
    if bdr is None:
        bdr = poser(pPr, el("w:pBdr"))
    ordre = ["top", "left", "bottom", "right", "between", "bar"]
    nouveau = el("w:" + cote, val="single", sz=taille, space=espace, color=couleur)
    for ancien in bdr.findall(qn("w:" + cote)):
        bdr.remove(ancien)
    for c in bdr:
        if ordre.index(c.tag.split("}")[1]) > ordre.index(cote):
            c.addprevious(nouveau)
            break
    else:
        bdr.append(nouveau)


def marges_cellule(cellule, haut=None, bas=None, gauche=None, droite=None):
    tcPr = cellule._tc.get_or_add_tcPr()
    m = el("w:tcMar")
    for cote, v in (("top", haut), ("left", gauche), ("bottom", bas), ("right", droite)):
        if v is not None:
            m.append(el("w:" + cote, w=v, type="dxa"))
    poser(tcPr, m)


def bordures_cellule(cellule, **cotes):
    """cotes : top=(taille, couleur) ou None (aucune)…"""
    tcPr = cellule._tc.get_or_add_tcPr()
    b = el("w:tcBorders")
    for cote in ("top", "left", "bottom", "right"):
        if cote in cotes:
            v = cotes[cote]
            b.append(el("w:" + cote, val="nil") if v is None
                     else el("w:" + cote, val="single", sz=v[0], space=0, color=v[1]))
    poser(tcPr, b)


def police_run(run, nom, taille=None, gras=None, italique=None, couleur=None):
    rPr = run._r.get_or_add_rPr()
    poser(rPr, el("w:rFonts", ascii=nom, hAnsi=nom, cs=nom, eastAsia=nom))
    if taille is not None:
        run.font.size = Pt(taille)
    if gras is not None:
        run.bold = gras
    if italique is not None:
        run.italic = italique
    if couleur is not None:
        run.font.color.rgb = RGBColor.from_string(couleur)
    return run


def sans_correcteur(run):
    poser(run._r.get_or_add_rPr(), el("w:noProof"))


def champ(p, code, taille=9, couleur=None):
    """Champ Word (PAGE, NUMPAGES) : LibreOffice et Word le calculent à l'ouverture."""
    def morceau(enfant=None, texte=None):
        r = p.add_run(texte) if texte is not None else p.add_run()
        police_run(r, POLICE, taille, couleur=couleur)
        if enfant is not None:
            r._r.append(enfant)
        return r
    debut = el("w:fldChar", fldCharType="begin")
    morceau(debut)
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = f" {code} "
    morceau(instr)
    morceau(el("w:fldChar", fldCharType="separate"))
    morceau(texte="1")
    morceau(el("w:fldChar", fldCharType="end"))


# =====================================================================================================
# Texte : typographie et petites balises (**gras**, `code`)
# =====================================================================================================

JETONS = re.compile(r"(\*\*.+?\*\*|`[^`]+`)")
UNITES = r"(m/s|rad/s|rad|m|cm|mm|s|min|h|Go|Mo|Ko|Hz|°|Mbit/s|px|%)"


def fr(t):
    """Typographie française de la prose (jamais appliquée aux commandes)."""
    t = t.replace("'", "\u2019")
    t = re.sub(r" ([:;?!»%])", "\u00a0\\1", t)
    t = t.replace("« ", "«\u00a0")
    t = re.sub(r"(\d) " + UNITES + r"(?=[\s,.;:)!?\u00a0/]|$)", "\\1\u00a0\\2", t)
    t = re.sub(r"\bn° (\d)", "n°\u00a0\\1", t)
    return t


def ecrire(p, texte, taille=None, couleur=None, gras=False, italique=False):
    """Ajoute texte (avec **gras** et `code`) au paragraphe p."""
    taille_code = (taille or 11) - 1.5
    for morceau in JETONS.split(texte):
        if not morceau:
            continue
        if morceau.startswith("**") and morceau.endswith("**") and len(morceau) > 4:
            for sous in re.split(r"(`[^`]+`)", morceau[2:-2]):
                if not sous:
                    continue
                if sous.startswith("`") and sous.endswith("`"):
                    _code_en_ligne(p, sous[1:-1], taille_code, True)
                else:
                    police_run(p.add_run(fr(sous)), POLICE, taille, True, italique, couleur)
        elif morceau.startswith("`") and morceau.endswith("`") and len(morceau) > 2:
            _code_en_ligne(p, morceau[1:-1], taille_code, gras)
        else:
            for bout in re.split("([\u2610\u2612\u2713\u2605\u271a])", fr(morceau)):
                if not bout:
                    continue
                fonte = SYMBOLES if bout in "\u2610\u2612\u2713\u2605\u271a" else POLICE
                police_run(p.add_run(bout), fonte, taille, gras, italique, couleur)
    return p


def _code_en_ligne(p, texte, taille, gras):
    r = police_run(p.add_run(texte), MONO, taille, gras, None, C["texte"])
    poser(r._r.get_or_add_rPr(), el("w:shd", val="clear", color="auto", fill="ECEEF2"))
    sans_correcteur(r)
    return r


# =====================================================================================================
# Le document
# =====================================================================================================

class Fiche:
    """Un document Word A4 avec ses styles, ses listes, son en-tête et son pied de page."""

    def __init__(self, entete_gauche, entete_droite, titre_doc, sujet):
        self.doc = Document()
        self._numeros = 200
        self.etape = ""
        self._page()
        self._styles()
        self._numerotation()
        self._entete_pied(entete_gauche, entete_droite)
        cp = self.doc.core_properties
        cp.title = titre_doc
        cp.subject = sujet
        cp.author = "Atelier G1 (Claude, intégrateur)"
        cp.language = "fr-FR"
        cp.keywords = "Unitree G1, séance robot, Atelier G1"
        zoom = self.doc.settings.element.find(qn("w:zoom"))
        if zoom is not None:                       # le schéma exige w:percent
            zoom.set(qn("w:percent"), "100")

    # ------------------------------------------------------------------ mise en page et styles

    def _page(self):
        s = self.doc.sections[0]
        s.page_width, s.page_height = Mm(210), Mm(297)
        s.left_margin = s.right_margin = Cm(1.8)
        s.top_margin = Cm(2.0)
        s.bottom_margin = Cm(1.9)
        s.header_distance = Cm(0.9)
        s.footer_distance = Cm(0.8)

    def _styles(self):
        st = self.doc.styles
        normal = st["Normal"]
        rPr = normal.element.get_or_add_rPr()
        poser(rPr, el("w:rFonts", ascii=POLICE, hAnsi=POLICE, cs=POLICE, eastAsia=POLICE))
        normal.font.size = Pt(11)
        normal.font.color.rgb = RGBColor.from_string(C["texte"])
        poser(rPr, el("w:lang", val="fr-FR", eastAsia="fr-FR", bidi="ar-SA"))
        pf = normal.paragraph_format
        pf.space_before = Pt(0)
        pf.space_after = Pt(4)
        pf.line_spacing = 1.08
        poser(normal.element.get_or_add_pPr(), el("w:widowControl"))
        # valeurs par défaut du document (styles hérités, tableaux)
        defauts = st.element.find(qn("w:docDefaults"))
        if defauts is not None:
            rpd = defauts.find(qn("w:rPrDefault"))
            if rpd is not None and rpd.find(qn("w:rPr")) is not None:
                r = rpd.find(qn("w:rPr"))
                poser(r, el("w:rFonts", ascii=POLICE, hAnsi=POLICE, cs=POLICE, eastAsia=POLICE))
                poser(r, el("w:lang", val="fr-FR", eastAsia="fr-FR", bidi="ar-SA"))
        for nom, taille, couleur, avant, apres in (("Heading 1", 17, C["bleu_fonce"], 16, 8),
                                                   ("Heading 2", 13.5, C["bleu"], 14, 5),
                                                   ("Heading 3", 11.5, C["texte"], 10, 3)):
            h = st[nom]
            rp = h.element.get_or_add_rPr()
            for attr in ("asciiTheme", "hAnsiTheme", "eastAsiaTheme", "cstheme"):
                f = rp.find(qn("w:rFonts"))
                if f is not None and f.get(qn("w:" + attr)) is not None:
                    del f.attrib[qn("w:" + attr)]
            poser(rp, el("w:rFonts", ascii=POLICE, hAnsi=POLICE, cs=POLICE, eastAsia=POLICE))
            h.font.size = Pt(taille)
            h.font.bold = True
            h.font.italic = False
            h.font.color.rgb = RGBColor.from_string(couleur)
            hp = h.paragraph_format
            hp.space_before = Pt(avant)
            hp.space_after = Pt(apres)
            hp.keep_with_next = True
            hp.keep_together = True
            hp.line_spacing = 1.0
        # en-tête et pied : sans les taquets du modèle (centre à 8,25 cm) qui happaient le texte de droite
        for style in st:
            if style.type == WD_STYLE_TYPE.PARAGRAPH and style.style_id in ("Header", "Footer"):
                pPr = style.element.pPr
                taquets = pPr.find(qn("w:tabs")) if pPr is not None else None
                if taquets is not None:
                    pPr.remove(taquets)
        # styles de listes (numérotation posée dans _numerotation)
        for nom in ("Puce", "Case", "Numero"):
            s = st.add_style(nom, WD_STYLE_TYPE.PARAGRAPH)
            s.base_style = normal
            s.paragraph_format.space_after = Pt(2.5)
        # légendes
        leg = st.add_style("Legende G1", WD_STYLE_TYPE.PARAGRAPH)
        leg.base_style = normal
        leg.font.size = Pt(9.5)
        leg.font.italic = True
        leg.font.color.rgb = RGBColor.from_string(C["texte2"])
        leg.paragraph_format.space_after = Pt(8)
        leg.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER

    def _numerotation(self):
        numbering = self.doc.part.numbering_part.element

        def abstrait(ident, niveaux, multi="multilevel"):
            a = el("w:abstractNum", abstractNumId=ident)
            a.append(el("w:multiLevelType", val=multi))
            for i, n in enumerate(niveaux):
                lvl = el("w:lvl", ilvl=i)
                lvl.append(el("w:start", val=1))
                lvl.append(el("w:numFmt", val=n["fmt"]))
                if n.get("style"):
                    lvl.append(el("w:pStyle", val=n["style"]))
                lvl.append(el("w:lvlText", val=n["texte"]))
                lvl.append(el("w:lvlJc", val="left"))
                pPr = el("w:pPr")
                pPr.append(el("w:ind", left=n["gauche"], hanging=n["suspendu"]))
                lvl.append(pPr)
                rPr = el("w:rPr")
                fonte = n.get("police", POLICE)
                rPr.append(el("w:rFonts", ascii=fonte, hAnsi=fonte, cs=fonte, eastAsia=fonte, hint="default"))
                if n.get("gras"):
                    rPr.append(el("w:b"))
                if n.get("couleur"):
                    rPr.append(el("w:color", val=n["couleur"]))
                if n.get("taille"):
                    rPr.append(el("w:sz", val=int(n["taille"] * 2)))
                lvl.append(rPr)
                a.append(lvl)
            existants = numbering.findall(qn("w:abstractNum"))
            if existants:
                existants[-1].addnext(a)
            else:
                numbering.insert(0, a)

        abstrait(150, [dict(fmt="decimal", texte="%1.", style="Heading1", gauche=567, suspendu=567),
                       dict(fmt="decimal", texte="%1.%2", style="Heading2", gauche=737, suspendu=737),
                       dict(fmt="decimal", texte="%1.%2.%3", style="Heading3", gauche=907, suspendu=907)])
        abstrait(151, [dict(fmt="bullet", texte="\u2022", gauche=454, suspendu=284, couleur=C["bleu"]),
                       dict(fmt="bullet", texte="\u2013", gauche=851, suspendu=284, couleur=C["bleu"])],
                 "hybridMultilevel")
        abstrait(152, [dict(fmt="bullet", texte="\u2610", gauche=454, suspendu=397, police=SYMBOLES,
                            couleur=C["bleu"], taille=12)], "hybridMultilevel")
        abstrait(153, [dict(fmt="decimal", texte="%1.", gauche=454, suspendu=340, gras=True, couleur=C["bleu"]),
                       dict(fmt="lowerLetter", texte="%2)", gauche=851, suspendu=340)], "hybridMultilevel")
        self.NUM_TITRES, self.NUM_PUCES, self.NUM_CASES, self.ABS_NUMEROS = 150, 151, 152, 153
        for num_id, abs_id in ((150, 150), (151, 151), (152, 152)):
            self._num(num_id, abs_id)
        # titres numérotés : les styles Titre 1 à 3 pointent sur la liste 150
        for niveau, nom in enumerate(("Heading 1", "Heading 2", "Heading 3")):
            pPr = self.doc.styles[nom].element.get_or_add_pPr()
            numPr = el("w:numPr")
            numPr.append(el("w:ilvl", val=niveau))
            numPr.append(el("w:numId", val=150))
            poser(pPr, numPr)
        for nom, num_id in (("Puce", 151), ("Case", 152)):
            pPr = self.doc.styles[nom].element.get_or_add_pPr()
            numPr = el("w:numPr")
            numPr.append(el("w:ilvl", val=0))
            numPr.append(el("w:numId", val=num_id))
            poser(pPr, numPr)

    def _num(self, num_id, abs_id, redemarrer=False):
        numbering = self.doc.part.numbering_part.element
        n = el("w:num", numId=num_id)
        n.append(el("w:abstractNumId", val=abs_id))
        if redemarrer:
            o = el("w:lvlOverride", ilvl=0)
            o.append(el("w:startOverride", val=1))
            n.append(o)
        fin = numbering.find(qn("w:numIdMacAtCleanup"))
        if fin is not None:
            fin.addprevious(n)
        else:
            numbering.append(n)
        return num_id

    def _entete_pied(self, gauche, droite):
        s = self.doc.sections[0]
        s.different_first_page_header_footer = True
        h = s.header
        h.is_linked_to_previous = False
        p = h.paragraphs[0]
        p.paragraph_format.tab_stops.add_tab_stop(Cm(LARGEUR), WD_TAB_ALIGNMENT.RIGHT)
        p.paragraph_format.space_after = Pt(0)
        police_run(p.add_run(gauche), POLICE, 9, True, couleur=C["bleu_fonce"])
        police_run(p.add_run("\t" + droite), POLICE, 9, couleur=C["texte2"])
        filet_paragraphe(p, "bottom", C["bleu_clair"], 6, 4)
        f = s.footer
        f.is_linked_to_previous = False
        q = f.paragraphs[0]
        q.alignment = WD_ALIGN_PARAGRAPH.CENTER
        q.paragraph_format.space_after = Pt(0)
        police_run(q.add_run("Page "), POLICE, 9, couleur=C["texte2"])
        champ(q, "PAGE", 9, C["texte2"])
        police_run(q.add_run(" sur "), POLICE, 9, couleur=C["texte2"])
        champ(q, "NUMPAGES", 9, C["texte2"])

    # ------------------------------------------------------------------ paragraphes

    def _para(self, conteneur=None, style=None):
        conteneur = conteneur if conteneur is not None else self.doc
        if isinstance(conteneur, _Cell):
            dernier = conteneur._tc[-1]
            if dernier.tag == qn("w:p") and not dernier.findall(qn("w:r")) \
                    and dernier.find(qn("w:sdt")) is None:
                p = Paragraph(dernier, conteneur)
                if style:
                    p.style = self.doc.styles[style]
                return p
        p = conteneur.add_paragraph()
        if style:
            p.style = self.doc.styles[style]
        return p

    def p(self, texte="", conteneur=None, style=None, taille=None, couleur=None, gras=False, italique=False,
          align=None, avant=None, apres=None, garder=False, retrait=None, ensemble=False):
        p = self._para(conteneur, style)
        if texte:
            ecrire(p, texte, taille, couleur, gras, italique)
        pf = p.paragraph_format
        if align == "centre":
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        elif align == "droite":
            p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        if avant is not None:
            pf.space_before = Pt(avant)
        if apres is not None:
            pf.space_after = Pt(apres)
        if garder:
            pf.keep_with_next = True
        if ensemble:
            pf.keep_together = True
        if retrait is not None:
            pf.left_indent = Cm(retrait)
        return p

    def titre(self, texte, niveau=1, saut=False, bande=False, numero=True):
        p = self.doc.add_paragraph(style=f"Heading {niveau}")
        ecrire(p, texte, gras=True)
        if not numero:
            numPr = el("w:numPr")
            numPr.append(el("w:ilvl", val=0))
            numPr.append(el("w:numId", val=0))
            poser(p._p.get_or_add_pPr(), numPr)
        if saut:
            p.paragraph_format.page_break_before = True
        if niveau == 1:
            filet_paragraphe(p, "bottom", C["bleu_clair"], 8, 3)
        if bande:
            ombrer_paragraphe(p, C["bleu_pale"])
            filet_paragraphe(p, "left", C["bleu"], 24, 6)
        return p

    def titre_etape(self, lettre, texte, duree):
        self.etape = lettre
        p = self.titre(f"Étape {lettre} : {texte}", 2, bande=True)
        police_run(p.add_run(fr(f"   ({duree})")), POLICE, 11.5, False, couleur=C["texte2"])
        return p

    def puces(self, items, conteneur=None, niveau=0, taille=None):
        dernier = None
        for item in items:
            p = self._para(conteneur, "Puce")
            if niveau:
                numPr = el("w:numPr")
                numPr.append(el("w:ilvl", val=niveau))
                numPr.append(el("w:numId", val=self.NUM_PUCES))
                poser(p._p.get_or_add_pPr(), numPr)
            ecrire(p, item, taille)
            dernier = p
        return dernier

    def numeros(self, items, conteneur=None, taille=None):
        num = self._numeros
        self._numeros += 1
        self._num(num, self.ABS_NUMEROS, redemarrer=True)
        dernier = None
        for item in items:
            p = self._para(conteneur, "Numero")
            numPr = el("w:numPr")
            numPr.append(el("w:ilvl", val=0))
            numPr.append(el("w:numId", val=num))
            poser(p._p.get_or_add_pPr(), numPr)
            ecrire(p, item, taille)
            dernier = p
        return dernier

    def case(self, texte, conteneur=None, feuille=None, taille=None):
        """Une action à cocher (☐ de la liste Word), avec la ligne de la feuille à remplir."""
        p = self._para(conteneur, "Case")
        ecrire(p, texte, taille)
        if feuille:
            police_run(p.add_run("   \u2192 feuille\u00a0: "), POLICE, 9.5, False, couleur=C["bleu"])
            police_run(p.add_run(feuille), POLICE, 9.5, True, couleur=C["bleu"])
        p.paragraph_format.space_before = Pt(3)
        return p

    def cases(self, items, conteneur=None):
        for item in items:
            self.case(item, conteneur)

    def _bloc_code_precedent(self, conteneur):
        """Le bloc de commandes qui est le dernier élément du conteneur, ou None."""
        t = getattr(self, "_dernier_cmd", None)
        if t is None:
            return None
        corps = self.doc.element.body if conteneur is None else conteneur._tc
        enfants = [e for e in corps if e.tag in (qn("w:p"), qn("w:tbl"))]
        return t if enfants and enfants[-1] is t._tbl else None

    def _ligne_sous_code(self, t):
        """Nouvelle ligne du bloc de commandes (sous les commandes) : le résultat attendu y tient avec elles,
        sur la même page, dans Word comme dans LibreOffice."""
        row = t.add_row()
        for cellule, w in zip(row.cells, t._g1_largeurs):
            cellule.width = Cm(w)
        poser(row._tr.get_or_add_trPr(), el("w:cantSplit"))
        for q in t.rows[-2]._tr.iter(qn("w:p")):
            poser(q.get_or_add_pPr(), el("w:keepNext"))
        cellule = row.cells[-1]
        marges_cellule(cellule, haut=25, bas=15)
        q = cellule.paragraphs[0]
        q.paragraph_format.space_after = Pt(1)
        return q

    def attendu(self, texte, conteneur=None, retrait=RETRAIT, mot="Attendu :"):
        return self.note(texte, conteneur, retrait, mot, C["vert"])

    def note(self, texte, conteneur=None, retrait=RETRAIT, mot=None, couleur=None, taille=10.5):
        t = self._bloc_code_precedent(conteneur)
        if t is not None:
            p = self._ligne_sous_code(t)
            taille = min(taille, 10)
        else:
            p = self._para(conteneur)
            p.paragraph_format.left_indent = Cm(retrait)
            p.paragraph_format.space_after = Pt(3)
            garder_avant(p._p)
        if mot:
            police_run(p.add_run(mot + "\u00a0"), POLICE, taille, True, couleur=couleur or C["texte"])
        ecrire(p, texte, taille)
        return p

    def stop(self, texte, conteneur=None, retrait=RETRAIT):
        return self.note(texte, conteneur, retrait, "STOP :", C["rouge"])

    def saut_page(self):
        p = self.doc.add_paragraph()
        p.paragraph_format.space_after = Pt(0)
        p.add_run().add_break(WD_BREAK.PAGE)
        return p

    # ------------------------------------------------------------------ tableaux

    def table(self, largeurs, conteneur=None, retrait=0.0, bordures=True, couleur=C["bordure"],
              interieur=True, marges=(45, 45, 100, 100)):
        conteneur = conteneur if conteneur is not None else self.doc
        if not isinstance(conteneur, _Cell) and abs(sum(largeurs) + retrait - 17.0) < 0.05:
            # largeurs écrites pour 17 cm : étirées à la largeur du texte
            largeurs = [w * (LARGEUR - retrait) / sum(largeurs) for w in largeurs]
        t = conteneur.add_table(rows=0, cols=len(largeurs))
        t.autofit = False
        tblPr = t._tbl.tblPr
        poser(tblPr, el("w:tblW", w=dxa(sum(largeurs)), type="dxa"))
        if retrait:
            poser(tblPr, el("w:tblInd", w=dxa(retrait), type="dxa"))
        b = el("w:tblBorders")
        for cote in ("top", "left", "bottom", "right", "insideH", "insideV"):
            if not bordures or (not interieur and cote.startswith("inside")):
                b.append(el("w:" + cote, val="nil"))
            else:
                b.append(el("w:" + cote, val="single", sz=4, space=0, color=couleur))
        poser(tblPr, b)
        poser(tblPr, el("w:tblLayout", type="fixed"))
        m = el("w:tblCellMar")
        for cote, v in zip(("top", "left", "bottom", "right"), (marges[0], marges[2], marges[1], marges[3])):
            m.append(el("w:" + cote, w=v, type="dxa"))
        poser(tblPr, m)
        look = tblPr.find(qn("w:tblLook"))
        if look is not None:
            tblPr.remove(look)
        for gc, w in zip(t._tbl.tblGrid.findall(qn("w:gridCol")), largeurs):
            gc.set(qn("w:w"), str(dxa(w)))
        t._g1_largeurs = list(largeurs)
        return t

    def ligne(self, t, valeurs=(), entete=False, hauteur=None, exacte=False, insecable=True, taille=10,
              fond=None, gras=False, couleur=None):
        row = t.add_row()
        for cellule, w in zip(row.cells, t._g1_largeurs):
            cellule.width = Cm(w)
        trPr = row._tr.get_or_add_trPr()
        if insecable:
            poser(trPr, el("w:cantSplit"))
        if hauteur:
            row.height = Cm(hauteur)
            row.height_rule = WD_ROW_HEIGHT_RULE.EXACTLY if exacte else WD_ROW_HEIGHT_RULE.AT_LEAST
        if entete:
            poser(row._tr.get_or_add_trPr(), el("w:tblHeader"))
        for i, valeur in enumerate(valeurs):
            cellule = row.cells[i]
            if entete:
                ombrer_cellule(cellule, C["bleu_clair"])
            elif fond:
                ombrer_cellule(cellule, fond)
            if valeur is None:
                continue
            textes = valeur if isinstance(valeur, (list, tuple)) else [valeur]
            for texte in textes:
                q = self._para(cellule)
                q.paragraph_format.space_after = Pt(1)
                q.paragraph_format.line_spacing = 1.0
                ecrire(q, texte, taille, couleur if not entete else C["bleu_fonce"], gras or entete)
        if entete:
            for q in row._tr.iter(qn("w:p")):
                poser(q.get_or_add_pPr(), el("w:keepNext"))
        return row

    def cellule_vide(self, cellule, taille=10):
        """La cellule garde son paragraphe vide (pour écrire) : un run vide le réserve."""
        p = cellule.paragraphs[0]
        police_run(p.add_run(""), POLICE, taille)
        return p

    # ------------------------------------------------------------------ commandes et encadrés

    def cmd(self, terminal, lignes, conteneur=None, retrait=0.0, largeur=None):
        """Bloc de commandes : la case bleue dit le terminal, une commande par paragraphe (gris)."""
        largeur = (largeur if largeur is not None else LARGEUR) - retrait
        label = 1.2 if terminal else 0
        largeurs = [label, largeur - label] if terminal else [largeur]
        t = self.table(largeurs, conteneur, retrait=retrait, bordures=False, marges=(50, 50, 80, 60))
        garder_avant(t._tbl)
        self._dernier_cmd = t
        row = t.add_row()
        for cellule, w in zip(row.cells, largeurs):
            cellule.width = Cm(w)
        poser(row._tr.get_or_add_trPr(), el("w:cantSplit"))
        cellules = row.cells
        if terminal:
            c0 = cellules[0]
            ombrer_cellule(c0, C["bleu"])
            c0.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            q = self._para(c0)
            q.alignment = WD_ALIGN_PARAGRAPH.CENTER
            q.paragraph_format.space_after = Pt(0)
            for i, morceau in enumerate(terminal.split("\n")):
                r = police_run(q.add_run(morceau), POLICE, 9.5 if len(terminal) <= 3 else 8, True,
                               couleur=C["blanc"])
                if i < len(terminal.split("\n")) - 1:
                    r.add_break()
        code = cellules[-1]
        ombrer_cellule(code, C["gris_code"])
        bordures_cellule(code, left=(12, C["bleu"]) if not terminal else None)
        for ligne in lignes:
            q = self._para(code)
            pf = q.paragraph_format
            pf.space_after = Pt(1)
            pf.space_before = Pt(1.5)
            pf.line_spacing = 1.0
            pf.left_indent = Cm(0.4)
            pf.first_line_indent = Cm(-0.4)
            commentaire = ligne.startswith("#")
            r = police_run(q.add_run(ligne), MONO, 8.5, False, commentaire, C["gris"] if commentaire else C["texte"])
            sans_correcteur(r)
        return t

    def encadre(self, genre, titre=None, conteneur=None, largeur=LARGEUR, insecable=True, retrait=0.0,
                taille_titre=11):
        fond, trait = GENRES[genre]
        t = self.table([largeur - retrait], conteneur, retrait=retrait, bordures=False, marges=(90, 90, 160, 160))
        row = t.add_row()
        row.cells[0].width = Cm(largeur - retrait)
        if insecable:
            poser(row._tr.get_or_add_trPr(), el("w:cantSplit"))
        cellule = row.cells[0]
        ombrer_cellule(cellule, fond)
        bordures_cellule(cellule, left=(24, trait), top=None, bottom=None, right=None)
        if titre:
            q = self._para(cellule)
            q.paragraph_format.space_after = Pt(3)
            q.paragraph_format.keep_with_next = True
            ecrire(q, titre, taille_titre, trait, True)
        cellule._g1_largeur = largeur - retrait
        return cellule

    def apres_tableau(self, espace=4):
        """Petit paragraphe après un tableau (Word colle sinon deux tableaux voisins)."""
        p = self.doc.add_paragraph()
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.line_spacing = Pt(espace)
        r = p.add_run("")
        r.font.size = Pt(2)
        return p

    def image(self, chemin, largeur_cm, legende=None):
        self.doc.add_picture(str(chemin), width=Cm(largeur_cm))
        p = self.doc.paragraphs[-1]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_after = Pt(2)
        p.paragraph_format.keep_with_next = bool(legende)
        if legende:
            self.p(legende, style="Legende G1")

    def jauge(self, conteneur, part, couleur, fond, largeur=15.0, hauteur=0.42):
        """Jauge : la part faite en couleur, le reste dans un ton clair de la même famille."""
        faite = max(0.05, min(largeur - 0.05, largeur * part))
        t = self.table([faite, largeur - faite], conteneur, bordures=False, marges=(0, 0, 0, 0))
        row = self.ligne(t, (None, None), hauteur=hauteur, exacte=True)
        ombrer_cellule(row.cells[0], couleur)
        ombrer_cellule(row.cells[1], fond)
        for c in row.cells:
            q = c.paragraphs[0]
            q.paragraph_format.space_after = Pt(0)
            q.paragraph_format.line_spacing = Pt(2)
            r = q.add_run("")
            r.font.size = Pt(1)
        return t

    # ------------------------------------------------------------------ cases à cocher (Word 2010+)

    def case_word(self, p, libelle, taille=10):
        """Case à cocher de Word (contrôle de contenu, se coche d'un clic), suivie de son libellé."""
        sdt = OxmlElement("w:sdt")
        sdtPr = OxmlElement("w:sdtPr")
        cb = OxmlElement("w14:checkbox")
        for nom, val in (("checked", "0"),):
            e = OxmlElement("w14:" + nom)
            e.set("{%s}val" % W14, val)
            cb.append(e)
        for nom, code in (("checkedState", "2612"), ("uncheckedState", "2610")):
            e = OxmlElement("w14:" + nom)
            e.set("{%s}val" % W14, code)
            e.set("{%s}font" % W14, SYMBOLES)
            cb.append(e)
        sdtPr.append(cb)
        sdt.append(sdtPr)
        contenu = OxmlElement("w:sdtContent")
        r = OxmlElement("w:r")
        rPr = OxmlElement("w:rPr")
        rPr.append(el("w:rFonts", ascii=SYMBOLES, hAnsi=SYMBOLES, eastAsia=SYMBOLES, cs=SYMBOLES))
        rPr.append(el("w:color", val=C["bleu"]))
        rPr.append(el("w:sz", val=int((taille + 2) * 2)))
        r.append(rPr)
        t = OxmlElement("w:t")
        t.text = "\u2610"
        r.append(t)
        contenu.append(r)
        sdt.append(contenu)
        p._p.append(sdt)
        if libelle:
            police_run(p.add_run("\u00a0" + libelle), POLICE, taille, couleur=C["texte"])
        return p

    def enregistrer(self, chemin):
        self.doc.save(str(chemin))


# =====================================================================================================
# Les schémas (Graphviz)
# =====================================================================================================

SCHEMA_LIAISONS = r"""
digraph liaisons {
  graph [rankdir=TB, fontname="DejaVu Sans", fontsize=14, bgcolor="white", pad=0.2, nodesep=0.55,
         ranksep=0.5, compound=true, newrank=true];
  node [fontname="DejaVu Sans", fontsize=14, shape=box, style="rounded,filled", fillcolor="#EAF2FC",
        color="#1C5CAB", penwidth=1.4, margin="0.18,0.10"];
  edge [fontname="DejaVu Sans", fontsize=12.5, color="#4D4D4D", fontcolor="#1F1F1F", penwidth=1.4];

  { rank=same;
    tele [label=<<b>Télécommande officielle</b><br/>tenue par la personne 1<br/><font color="#B42318"><b>arrêt d'urgence</b></font>>,
          fillcolor="#FDECEC", color="#B42318"];
    tel [label=<<b>Téléphone</b><br/>appli Unitree Explore<br/>(le matin : version,<br/>services du robot)>,
         fillcolor="#F3F4F6", color="#8A8A8A"];
  }

  subgraph cluster_robot {
    label=<<b>Le robot G1 EDU</b>>; labeljust="l"; style="rounded"; color="#184F95"; penwidth=1.8;
    fontcolor="#184F95"; fontsize=15; margin=16;
    { rank=same;
      pc1 [label=<<b>PC1 d'Unitree</b><br/>marche et équilibre<br/>(on n'y touche jamais)>,
           fillcolor="#F3F4F6", color="#8A8A8A"];
      cam [label=<<b>Caméra See3CAM</b><br/>sur la poitrine>, fillcolor="#FFFFFF"];
    }
    jetson [label=<<b>Jetson (PC2)</b><br/>notre conteneur Docker :<br/>navigation (Nav2), guide, pont,<br/>caméra, pilotage<br/>(à partir de l'étape E)>];
  }

  pc [label=<<b>PC portable</b> (personne 2)<br align="left"/>T1 : l'Atelier (la page web)<br align="left"/>T2 : le pont (étapes M et C)<br align="left"/>T3 : l'état du pont<br align="left"/>T4 : les réponses du robot<br align="left"/>T5 : mesures et commandes<br align="left"/>T6 : urgence (tuer le pont)<br align="left"/>>,
      fillcolor="#FFFFFF"];

  tele -> pc1 [label=" radio : toujours\n prioritaire", color="#B42318", fontcolor="#B42318", penwidth=2];
  tel -> pc1 [label=" Wi-Fi", style=dashed, color="#8A8A8A", fontcolor="#6B6B6B"];
  pc1 -> jetson [dir=back, label=" ordres de marche\n (commande 7105)"];
  cam -> jetson [label=" USB 3\n (port bleu)"];
  jetson -> pc [dir=both, ltail=cluster_robot, label=" câble Ethernet\n (réseau 192.168.123.x)", penwidth=2.6,
                color="#1C5CAB", fontcolor="#1C5CAB"];
}
"""


def schema_sol():
    """Le sol : la croix, la flèche, les repères à 1, 2, 3 et 4 m et le but « Essai à 2,5 m »."""
    k = 1.25          # pouces par mètre
    gauche, droite = 0.55, 4.55          # la zone libre, en mètres devant la croix
    lignes = [
        "digraph sol {",
        '  graph [layout=neato, bgcolor="white", pad=0.2, outputorder=edgesfirst, fontname="DejaVu Sans"];',
        '  node [fontname="DejaVu Sans", fontsize=13, shape=plaintext, margin=0];',
        '  edge [fontname="DejaVu Sans", fontsize=12];',
        f'  zone [pos="{(gauche + droite) / 2 * k:.3f},0.02!", shape=box, style="dashed,rounded", color="#8A8A8A", '
        f'width={(droite - gauche) * k:.3f}, height=2.05, fixedsize=true, label=""];',
        f'  zone_txt [pos="{(gauche + droite) / 2 * k:.3f},0.82!", label="au moins 4 m libres devant le robot", '
        'fontcolor="#4D4D4D", fontsize=12.5];',
        f'  fin [pos="{5.25 * k:.3f},0!", shape=point, width=0.01, style=invis];',
        '  o [pos="0,0!", label="✚", fontsize=34, fontcolor="#B42318"];',
        '  o -> fin [penwidth=3.4, color="#1C5CAB", arrowsize=1.3];',
        f'  fleche_txt [pos="{5.3 * k:.3f},-0.55!", label="la flèche :\\nle sens du robot\\n(l\'axe x)", '
        'fontcolor="#1C5CAB", fontsize=12.5];',
        '  yfin [pos="0,0.95!", shape=point, width=0.01, style=invis];',
        '  o -> yfin [style=dashed, color="#8A8A8A", arrowsize=0.8];',
        '  y_txt [pos="-0.62,0.86!", label="y : à gauche", fontcolor="#6B6B6B", fontsize=11.5];',
        '  o_txt [pos="0,-0.66!", label="la croix :\\nle point\\nprincipal", fontcolor="#B42318", fontsize=12.5];',
    ]
    for m in (1, 2, 3, 4):
        x = m * k
        lignes.append(f'  r{m} [pos="{x:.3f},0!", shape=box, style=filled, fillcolor="#8A5A00", color="#8A5A00", '
                      'width=0.075, height=0.44, fixedsize=true, label=""];')
        lignes.append(f'  r{m}_txt [pos="{x:.3f},-0.43!", label="{m} m", fontcolor="#8A5A00", fontsize=13];')
    xb = 2.5 * k
    lignes += [
        f'  but [pos="{xb:.3f},0.02!", label="★", fontsize=26, fontcolor="#2A78D6"];',
        f'  but_txt [pos="{xb:.3f},0.42!", label="« Essai à 2,5 m » (étape F)", fontcolor="#1C5CAB", fontsize=12.5];',
        f'  rep_txt [pos="{(gauche + droite) / 2 * k:.3f},-0.8!", label="repères au ruban (la personne s\'y '
        'tient à l\'étape G)", fontcolor="#8A5A00", fontsize=11.5];',
        "}",
    ]
    return "\n".join(lignes)


def fabriquer_schemas():
    SCHEMAS.mkdir(parents=True, exist_ok=True)
    sorties = {}
    for nom, source, moteur in (("liaisons", SCHEMA_LIAISONS, "dot"), ("sol", schema_sol(), "neato")):
        dot = SCHEMAS / f"{nom}.dot"
        png = SCHEMAS / f"{nom}.png"
        dot.write_text(source, encoding="utf-8")
        subprocess.run([moteur, "-Tpng", "-Gdpi=200", str(dot), "-o", str(png)], check=True)
        sorties[nom] = png
    return sorties


# =====================================================================================================
# Contenu commun : l'avancement du projet
# =====================================================================================================

AVANCEMENT = [
    ("Logiciel en simulation (lieux, monde, carte, salles, itinéraires, zones, Gazebo + Nav2, foule, guide, "
     "point principal, retour, accompagnement)", 25, 95,
     "fait et vérifié sans robot (42 / 42 à la recette du 10/11)"),
    ("Interface (accueil Simulation / Réel, espace à la SolidWorks, carte 3D, écrans de la vague 6)", 10, 90,
     "faite le 31/10, complétée le 09/11 (diagnostic, séance, démo), deux revues corrigées ; à essayer par toi"),
    ("Scan réel → carte", 10, 70,
     "chaîne corrigée, vrai scan du 27/10 retraité ; à valider par un nouveau scan ; carte d'Unitree à récupérer"),
    ("Liaison avec le vrai robot (pont, conteneur du Jetson, repérage, premier trajet)", 25, 30,
     "pont essayé le 27/10 (marche à 0,2 m/s) ; « Vérifier le robot » et la boîte noire prêts ; Jetson, "
     "repérage et trajet pas encore faits"),
    ("Guide réel avec des visiteurs et évitement de la foule réel", 15, 10, "seulement en simulation"),
    ("Caméra, détection des visiteurs et parties de l'équipe (chatbot, voix)", 10, 55,
     "caméra, détection et voix du robot prêtes sur le PC ; pas encore sur le robot ; chatbot de l'équipe en "
     "attente (son branchement est prêt)"),
    ("Démo finale, réglages sur place, documentation finale", 5, 60,
     "démo d'accueil complète en simulation (borne, accueil, voix) ; à faire avec le robot"),
]
DATE_AVANCEMENT = "10/11"          # jour de l'estimation (vague 6, après la recette : 42 / 42)
JOUR_PROJET, JOURS_PROJET = 21, 59  # le 10/11 est le jour 21 du projet (21/10 → 18/12/2026)
ARRONDI_AVANCEMENT = "environ 55\u00a0%"


def nombre(x):
    texte = f"{x:.2f}".rstrip("0").rstrip(".")
    return texte.replace(".", ",")


def encadre_avancement(f, avec_avis=False):
    total = sum(p * d / 100 for _, p, d, _ in AVANCEMENT)          # 57,25
    temps = round(100 * JOUR_PROJET / JOURS_PROJET)                  # 36
    cellule = f.encadre("info", None, insecable=False)
    q = f.p("", cellule, apres=0)
    police_run(q.add_run("Avancement du projet : "), POLICE, 15, True, couleur=C["bleu_fonce"])
    police_run(q.add_run(ARRONDI_AVANCEMENT), POLICE, 22, True, couleur=C["bleu_fonce"])
    f.p(f"Estimation de l'intégrateur (Claude) du 31/10/2026 (environ 50 %), mise à jour le {DATE_AVANCEMENT} "
        f"après la vague 6 (recette : 42 / 42), avec les mêmes poids : quatre parts faites ont augmenté (interface, "
        f"liaison avec le robot, caméra et voix, démo). Calcul exact : **{nombre(total)} %**, "
        f"arrondi à « {ARRONDI_AVANCEMENT} ».", cellule, taille=10, couleur=C["texte2"], apres=6)
    largeur_jauge = LARGEUR - 0.6
    f.p(f"**Travail fait** : {nombre(total)} % du projet", cellule, taille=10, apres=1, garder=True)
    f.jauge(cellule, total / 100, C["bleu_vif"], C["bleu_clair"], largeur_jauge)
    f.p(f"**Temps passé** : {temps} % (jour {JOUR_PROJET} sur {JOURS_PROJET} le {DATE_AVANCEMENT}, du 21/10 au "
        "18/12/2026)", cellule, taille=10, avant=5, apres=1, garder=True)
    f.jauge(cellule, JOUR_PROJET / JOURS_PROJET, C["gris_temps"], C["gris_temps_pale"], largeur_jauge)
    f.p("Chaque partie du projet a un **poids** (sa part du travail total) et une part **faite**. "
        "Points = poids × fait. Le total des points donne l'avancement.", cellule, taille=10, avant=6, apres=4)
    largeurs = [4.85, 1.6, 1.3, 1.6]
    largeurs.append(largeur_jauge - sum(largeurs))
    t = f.table(largeurs, cellule)
    f.ligne(t, ("Partie", "Poids", "Fait", "Points", "Pourquoi"), entete=True, taille=9.5)
    for partie, poids, fait, pourquoi in AVANCEMENT:
        f.ligne(t, (partie, f"{poids} %", f"{fait} %", nombre(poids * fait / 100), pourquoi), taille=9.5)
    f.ligne(t, ("**Total pondéré**", "**100 %**", "", f"**{nombre(total)}**",
                f"**{nombre(total)} %, soit « {ARRONDI_AVANCEMENT} »**"), taille=9.5, fond=C["bleu_clair"])
    f.p(f"**Ce que ça veut dire.** Au {DATE_AVANCEMENT}, on est au jour {JOUR_PROJET} sur {JOURS_PROJET} ({temps} % "
        "du temps) : le logiciel reste **en avance**. Ce qui reste est surtout **l'essai sur le vrai robot** (la "
        "liaison, le repérage, les trajets, le guide avec des visiteurs, la démo) : c'est le but des séances avec le "
        "robot, à commencer par celle-ci.", cellule, taille=10, avant=6, apres=2)
    if avec_avis:
        t2 = f.table([5.6, 2.4, largeur_jauge - 8.0], cellule, couleur=C["bleu"])
        row = f.ligne(t2, ("**Ton avis après la séance :**", None, None), hauteur=1.6, taille=10.5)
        row.cells[0].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        ombrer_cellule(row.cells[1], C["blanc"])
        q = row.cells[1].paragraphs[0]
        q.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        police_run(q.add_run("%"), POLICE, 11, True, couleur=C["bleu_fonce"])
        row.cells[1].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.BOTTOM
        ombrer_cellule(row.cells[2], C["blanc"])
        q = row.cells[2].paragraphs[0]
        police_run(q.add_run("Pourquoi : "), POLICE, 9.5, False, True, C["texte2"])
        row.cells[2].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.TOP
    return cellule


def mots_avancement(f, conteneur=None):
    f.p("**Mots du tableau.** Gazebo : le simulateur 3D du robot sur le PC. Nav2 : le logiciel de navigation "
        "(il calcule le chemin et évite les obstacles). Critères de recette : 42 essais automatiques qui vérifient "
        "le logiciel de bout en bout, sans robot. Pont : notre programme qui transforme une vitesse demandée en "
        "ordre de marche du robot. Jetson : l'ordinateur de bord du robot où tourne notre conteneur (une « boîte » "
        "qui contient notre logiciel). Repérage : le robot retrouve sa position sur la carte. Boîte noire : "
        "l'enregistrement de toute la séance, avec son rapport.",
        conteneur, taille=9.5, couleur=C["texte2"], avant=4)


# =====================================================================================================
# Document 1 : Ce qu'il faut faire
# =====================================================================================================

def fiche_a_faire(schemas):
    f = Fiche("Atelier G1 · Séance robot n° 2 · Ce qu'il faut faire", "document du 10/11/2026",
              "Séance robot n° 2 : ce qu'il faut faire", "Déroulé pas à pas de la séance robot n° 2")
    page_titre_a_faire(f)
    partie_avancement(f)
    partie_appris(f)
    partie_regles(f)
    partie_veille(f, schemas)
    partie_matin(f)
    partie_seance(f, schemas)
    partie_depannage(f)
    partie_rapport(f)
    partie_lexique(f)
    return f


def page_titre_a_faire(f):
    f.p("ATELIER G1 · ROBOT D'ACCUEIL UNITREE G1 EDU", taille=10.5, couleur=C["bleu"], gras=True, avant=40, apres=6)
    f.p("Séance robot n° 2", taille=34, couleur=C["bleu_fonce"], gras=True, apres=2)
    f.p("Ce qu'il faut faire : le déroulé pas à pas", taille=17, couleur=C["texte2"], apres=4)
    p = f.p("", apres=18)
    filet_paragraphe(p, "bottom", C["bleu_vif"], 18, 1)
    t = f.table([5.2, 11.8])
    for libelle, aide in (("Date de la séance", ""),
                          ("Lieu", "si possible la même zone que le 27/10 : la croix du point principal au même "
                                   "endroit, dans le même sens"),
                          ("Personne 1 : la télécommande (l'arrêt d'urgence)", ""),
                          ("Personne 2 : le PC", ""),
                          ("Autres personnes présentes", ""),
                          ("Heure de début · heure de fin", "")):
        row = f.ligne(t, (f"**{libelle}**", None), hauteur=1.15, taille=10.5)
        ombrer_cellule(row.cells[0], C["bleu_pale"])
        row.cells[0].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        if aide:
            q = row.cells[1].paragraphs[0]
            police_run(q.add_run(fr(aide)), POLICE, 8.5, False, True, C["gris"])
            row.cells[1].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.BOTTOM
    f.apres_tableau(10)
    cellule = f.encadre("neutre", "Comment lire ce document", insecable=True)
    f.puces([
        "**☐ Une case par action** : coche-la quand c'est fait (au stylo sur la feuille imprimée, ou dans Word).",
        "**Les commandes** sont dans les cadres gris ; la case bleue à gauche dit dans quel terminal les taper "
        "(T1 à T6 ; « PC » : n'importe quel terminal du PC). Une commande = un paragraphe gris : si elle est trop "
        "longue, elle continue à la ligne, décalée. Tape-la (ou colle-la) en entier, puis Entrée.",
        "**« Ce qu'on doit voir »** (vert), **« Si ça ne marche pas »** (orange), **STOP** (rouge).",
        "**Les résultats** se notent sur l'autre document, **« Feuille de résultats à remplir »** "
        "(`Seance2_A_remplir.docx`) : la flèche « → feuille : M1 » dit quelle ligne remplir.",
        "Préparé le 31/10/2026 (vague 5), mis à jour le 01/11 après la recette (36 / 36) et le 10/11 après la "
        "vague 6 (42 / 42), **sans robot** : les commandes ont été vérifiées dans le dépôt et essayées contre le "
        "faux G1 (la simulation), pas encore sur le vrai robot. Il suit `docs/tutoriel-seance-2.md` ; en cas "
        "d'écart, suis ce document-ci. **Un déblocage ne relance jamais un mouvement** : après « Débloquer », une "
        "remise en marche ou une relance du pont, il faut un nouveau « Y aller », ou lâcher puis reprendre le "
        "joystick ; la démo d'accueil, elle, se met en pause. Une surprise n'est pas une faute de ta part : "
        "note-la.",
        "**Nouveau (vague 6)** : **« Vérifier le robot »** remplace les vérifications à la main au début (étape A) ; "
        "la **boîte noire** enregistre toute la séance et garde toute seule le journal du conteneur du Jetson ; "
        "à la fin, **« Terminer la séance »** écrit le rapport, et un `.zip` me l'apporte ; en option, **la voix "
        "du robot et la démo d'accueil** (étape V).",
    ], cellule, taille=10)
    f.saut_page()


def partie_avancement(f):
    f.titre("Où en est le projet", 1)
    encadre_avancement(f)
    f.apres_tableau(6)
    mots_avancement(f)


def partie_appris(f):
    f.titre("Ce qu'on a appris à la séance n° 1 (27/10), et le but d'aujourd'hui", 1, saut=True)
    f.titre("Ce qu'on a appris le 27/10", 2)
    f.puces([
        "**Le scan marche**, une fois démarrés les services `lidar_driver` (le programme du LiDAR, le capteur laser "
        "3D de la tête) et `unitree_slam` (la cartographie d'Unitree) dans l'appli Unitree Explore : commande 1801 "
        "(début du scan), puis 1802 (fin : la carte est enregistrée sur le robot). La carte a été **retraitée le "
        "31/10** par notre nouvelle chaîne : plus de « damier », tous les nuages de points gardés, les traînées des "
        "passants retirées. Depuis, **« Vérifier le robot »** voit ces services arrêtés et les démarre en un clic.",
        "**Le pont marche à 0,2 m/s, pas à 0,1 m/s** : à 0,1 m/s, le robot ne fait aucun pas. Le pont est notre "
        "programme qui transforme une vitesse demandée en ordre de marche du robot (commande 7105). Depuis, il "
        "**monte toute petite consigne à 0,2 m/s** (0,3 rad/s pour tourner), dans la même direction.",
        "**Les modes du robot**, lus par la commande 7001 (« dis-moi ton mode ») : 0 (pas démarré), 3 (assis), "
        "501 (marche) et 802 (course).",
        "**Assis, le robot accepte les ordres de marche sans bouger** : il répond « code 0 », comme si tout allait "
        "bien. Depuis, le pont lit le mode : assis, pas démarré ou en course, il n'envoie plus d'ordre de marche "
        "(état `pas_en_marche`, avec un message qui dit quoi faire).",
        "**La connexion `robot-g1` tombe quand on débranche le câble** : ce profil réseau du PC ne se reconnecte "
        "pas tout seul. Après avoir rebranché le câble, dans n'importe quel terminal :",
    ])
    f.cmd("PC", ["nmcli connection up robot-g1"])
    f.puces([
        "**Pas encore faits** le 27/10 : les points de sécurité du pont **C3 à C5 et C7**, notre logiciel sur le "
        "Jetson (**D**), le repérage (**E**) et le premier trajet (**F**). Ils sont au programme aujourd'hui.",
    ])
    f.titre("Le but de la séance n° 2", 2)
    f.p("Dans l'ordre :", apres=2)
    f.puces([
        "**mesurer les vrais seuils** du robot (marche, pas de côté, rotation) et sa latence (son temps de réaction) ;",
        "refaire les vérifications de sécurité du pont (C3 à C5 et C7 de la séance n° 1), avec le nouveau pont ;",
        "notre conteneur sur le Jetson (D), le repérage (E) et un premier trajet de 2,5 m (F) ;",
        "**la caméra See3CAM** sur le robot (G) et **la carte d'Unitree** (pendant E) ;",
        "**un nouveau scan**, plus lent, avec la nouvelle chaîne (H, si le temps le permet) ;",
        "**le pilotage depuis le mode 501 et une danse sûre**, d'abord au portique (P) ;",
        "**« Vérifier le robot »** sur le vrai robot (A), et **la boîte noire** pendant toute la séance, avec son "
        "rapport à la fin ;",
        "en option, **la voix du robot**, prudemment, et **la démo d'accueil** avec la borne (V).",
    ])
    f.p("**Durée :** environ 2 h 40 avec le robot (3 h avec l'étape H, 3 h 20 avec H et V), plus 45 min la veille "
        "et 15 min le matin. **Si le temps manque, on garde l'ordre et on saute H, puis V.**", avant=4)


def partie_regles(f):
    f.titre("Les règles d'or : à lire avant tout", 1, saut=True)
    f.numeros([
        "**Deux personnes.** La première tient la **télécommande officielle pendant toute la séance** : c'est "
        "l'arrêt d'urgence. En cas de doute, **mode amortissement** (les moteurs se relâchent et freinent : le robot "
        "s'affaisse doucement ; au portique, la sangle le retient). La seconde est au PC.",
        "**Aucune simulation sur le PC pendant que le robot est branché.** La simulation et le robot utilisent le "
        "même canal ROS (le « domaine 0 ») : le faux G1 de la simulation pourrait répondre à la place du vrai. "
        "Le matin, **redémarre le PC**.",
        "**`source ~/robot-g1/setup/robot.sh` dans CHAQUE terminal** qui parle au robot. Cette commande relie le "
        "terminal au robot par le câble ; elle doit dire « le robot répond ». Elle ne vaut que pour le terminal où "
        "tu la tapes.",
        "**Vitesses : 0,2 m/s au plus**, au portique comme au sol (`G1_VITESSE_MAX=0.2`). Les mesures de l'étape M "
        "vont jusqu'à 0,2 m/s et 0,4 rad/s (radians par seconde : 0,4 rad/s, c'est environ 23° par seconde), "
        "pendant 3 s au plus.",
        "**Le bouton ARRÊT de l'Atelier** (ou la touche **Échap**, dès qu'une navigation ou le pilotage tourne, et "
        "toujours quand le robot bouge ou va repartir seul, par exemple pendant les 15 s avant le retour "
        "automatique, même si un menu est ouvert) arrête le guide, le pilotage et bloque le robot. **Il ne "
        "remplace pas la télécommande.**",
        "**Danses : jamais 401, 402 ni 403** (401 et 402 couchent le robot par terre, 403 est inconnue). La "
        "danse 604 d'abord **au portique, robot tenu**, 3 m libres autour.",
        "**On note tout** sur la feuille de résultats. Un point qui échoue : on note ce qu'on a vu, puis on passe "
        "au suivant s'il n'y a pas de danger. La boîte noire enregistre aussi tout de son côté, mais ce que tu vois "
        "(un pas de travers, un bruit, un son trop fort) n'est que sur la feuille.",
        "**L'Atelier reste ouvert toute la journée** (T1, lancé à l'étape A). Le fermer (Ctrl+C) termine la séance "
        "de la boîte noire ; une navigation lancée continuerait sur le Jetson sans que l'Atelier le sache.",
    ])
    cellule = f.encadre("danger", "On arrête la séance (télécommande, puis amortissement) si l'une de ces choses "
                                  "arrive :", insecable=True)
    f.puces([
        "la télécommande ne reprend pas la main pendant que notre pont envoie des ordres ;",
        "le robot ne s'arrête pas tout seul quand on coupe le pont ;",
        "un mouvement part sans qu'on l'ait demandé.",
    ], cellule)
    f.apres_tableau(8)
    f.titre("Ce qui ne change pas dans le robot", 2)
    f.puces([
        "Comme à la séance n° 1 : le **PC1 d'Unitree** (l'ordinateur de la marche et de l'équilibre) n'est jamais "
        "touché.",
        "Sur le **Jetson** (l'ordinateur de bord sur lequel tourne notre logiciel), on ajoute seulement notre "
        "**image Docker** (environ 2 Go : le modèle de notre conteneur) et le dossier `~/robot-g1`.",
        "Rien n'est installé dans Ubuntu, ROS ou les programmes d'Unitree ; notre conteneur ne redémarre jamais "
        "tout seul.",
        "Deux réglages du robot peuvent changer, comme avec l'appli : les services de cartographie démarrés par "
        "« Vérifier le robot » (étape A), et le volume de son haut-parleur (étape V).",
        "Pour tout retirer, plus tard (d'abord arrêter le conteneur, puis effacer l'image et le dossier) :",
    ])
    f.cmd("T5", ["g1-jetson arreter", "ssh unitree@192.168.123.164 'docker rmi g1-jetson:arm64; rm -rf ~/robot-g1'"])


def partie_veille(f, schemas):
    f.titre("La veille au soir (environ 45 min)", 1, saut=True)
    f.titre("Charger et préparer", 2)
    f.cases([
        "La batterie du robot, la télécommande, le PC (et son chargeur), le téléphone avec l'appli Unitree Explore.",
        "Le portique avec la sangle, le câble Ethernet (5 m ou plus : le PC suit le robot pendant les trajets et le "
        "scan), le ruban adhésif de couleur, le mètre ruban.",
        "Un rapporteur si possible (étape F2) et une règle d'un mètre ou un deuxième mètre ruban (étape G6).",
        "**La caméra See3CAM_11CUG**, son câble USB 3 et de quoi la fixer sur la poitrine du robot (support ou "
        "adhésif double face), **objectif à l'horizontale ou un peu vers le haut**.",
        "Quatre bouts de ruban au sol, à **1, 2, 3 et 4 m** devant la croix, sur la ligne de la flèche (étape G).",
        "La même zone que le 27/10 si possible : **la croix du point principal doit être au même endroit** (la "
        "carte du 27/10 a son origine sur la croix, et son axe x dans le sens de la flèche).",
    ])
    f.image(schemas["sol"], 16.5, "Schéma 1. Le sol, vu de dessus : la croix et la flèche du 27/10, les repères à "
                                  "1, 2, 3 et 4 m (étape G) et le but « Essai à 2,5 m » (étape F).")

    f.titre("Sur le PC (environ 15 min)", 2)
    f.p("Ouvre un terminal (**Ctrl+Alt+T** : la fenêtre où l'on tape des commandes) et tape les commandes une par "
        "une, en attendant la fin de chacune.")
    f.case("Va dans le dossier du projet.")
    f.cmd("PC", ["cd ~/robot-g1"])
    f.case("Vérifie que rien ne tourne encore (Atelier, simulations).")
    f.cmd("PC", ['pgrep -af "ign gazebo|ros2 launch|uvicorn"'])
    f.attendu("**aucune ligne**. Sinon : dans l'Atelier ouvert, « Arrêter », puis Ctrl+C dans son terminal, et "
              "recommence.")
    f.case("La répétition sans robot (environ 20 min) : elle vérifie, contre le faux G1, le conteneur, le pont, le "
           "repérage, le trajet, la sécurité, la vitesse minimale et les modes, la caméra et l'ARRÊT, puis "
           "« Vérifier le robot », la boîte noire, la voix et la sécurité de la démo (vague 6).")
    f.cmd("PC", ["tests_e2e/tout.sh 16 17 18 19 20 34 35 36 37 38 40 42"])
    f.attendu("à la fin, « **12 / 12** (critères 16 17 18 19 20 34 35 36 37 38 40 42) ». Sinon, envoie-moi la fin de "
              "l'affichage avant la séance.")
    f.case("L'image du Jetson (avec la caméra, le nouveau pont et le pilotage).")
    f.cmd("PC", ["g1-jetson construire"])
    f.attendu("déjà à jour (elle a été refaite à la recette du 10/11) : quelques secondes ; sinon, environ 1 min "
              "avec le cache de Docker, 5 à 10 min sans.")
    f.case("Le lieu de la séance : la carte retraitée du 27/10.")
    f.cmd("PC", ["g1-lieu valider --lieu seance"])
    f.attendu("« **Aucune erreur.** », puis 4 avertissements : les nœuds « 1 », « 2 » et « 3 » ne sont reliés à "
              "aucun couloir, et le nœud « 3 » (sa salle) est « à 0.28 m d'un obstacle […], moins que le rayon du "
              "robot (0.35 m) ». C'est connu, et sans effet aujourd'hui : le trajet de la séance va vers « Essai à "
              "2,5 m ». Plus tard, tu pourras écarter la salle « 3 » d'environ 0,2 m (Réel › Placer) et relier les "
              "nœuds (Placer › Relier).")
    f.case("Voir à blanc ce que fera l'envoi au Jetson : rien n'est envoyé (`G1_SLAM_FAUX=1` interdit tout envoi "
           "vers le robot, `--dry-run` montre les commandes sans les lancer).")
    f.cmd("PC", ["G1_SLAM_FAUX=1 g1-jetson envoyer --dry-run"])
    f.attendu("la liste des commandes de l'envoi, en 4 temps (archive, dossiers, copie, chargement).")
    f.case("De la place pour la boîte noire : elle s'arrête sous 2 Go libres, et une séance pèse environ 150 Mo "
           "par heure.")
    f.cmd("PC", ["df -h ~"])
    f.attendu("au moins **5 Go** dans la colonne « Dispo ».")

    f.titre("La caméra, sur le PC d'abord (10 min)", 2)
    f.case("Branche la See3CAM sur un port USB du PC (USB 3 si possible), puis vérifie qu'elle est vue.")
    f.cmd("PC", ["ls /dev/v4l/by-id/"])
    f.attendu("un nom qui contient `usb-e-con_Systems_See3CAM_11CUG` et finit par `-video-index0`.")
    f.case("L'essai de la vraie caméra (environ 20 s).")
    f.cmd("PC", ["cd ~/robot-g1/ws/src/g1_equipe",
                           "G1_TEST_CAMERA=$(ls /dev/v4l/by-id/*See3CAM*-video-index0) python3 -m pytest -q -p "
                           "no:cacheprovider test/test_camera_usb.py -k vraie"])
    f.attendu("« **1 passed** » (les autres essais sont « deselected », c'est normal). « 1 skipped » : la caméra "
              "n'est pas vue (reprends la commande `ls` ci-dessus).")
    f.case("L'image et la détection des personnes (YOLO, le programme qui reconnaît les personnes dans l'image).")
    f.cmd("PC", ["cd ~/robot-g1",
                           "g1-visiteurs --source $(ls /dev/v4l/by-id/*See3CAM*-video-index0) --fenetre --sans-ros"])
    f.attendu("une fenêtre montre l'image avec **un cadre autour de toi et ta distance**. L'image ne doit pas être "
              "noire (exposition automatique). Touche **q** pour quitter.")
    f.case("Débranche la caméra du PC et **fixe-la sur la poitrine du robot**, câble rangé le long du corps (il ne "
           "doit pas gêner les bras). Elle sera branchée sur le Jetson à l'étape D.")


def partie_matin(f):
    f.titre("Le matin, avant d'allumer le robot (environ 15 min)", 1)
    f.titre("Le PC", 2)
    f.case("**Redémarre le PC** (aucune simulation ne doit rester en mémoire).")
    f.case("Ouvre un terminal et vérifie qu'aucune simulation ne tourne.")
    f.cmd("PC", ['pgrep -af "ign gazebo|ros2 launch|uvicorn"'])
    f.attendu("aucune ligne.")
    f.case("Le Wi-Fi du PC reste sur ton réseau habituel : on ne s'en sert pas pour le robot.")
    f.titre("Dans l'appli Unitree Explore, robot allumé", 2)
    cellule = f.encadre("attention", None)
    f.p("**Ne lance pas de mise à jour du robot aujourd'hui.**", cellule, apres=0)
    f.apres_tableau(4)
    f.case("**Note la version du logiciel du robot** (le micrologiciel, dans les informations du robot), si ce n'est "
           "pas déjà fait.", feuille="en-tête")
    f.case("Les services **`unitree_slam` et `lidar_driver`** (sans eux, ni repérage ni scan) : **ne les active pas "
           "ici**. « Vérifier le robot » (étape A) les voit arrêtés et les démarre en un clic : c'est un des essais du "
           "jour. Seulement s'il n'y arrive pas, on les activera dans l'appli (solution de secours).",
           feuille="en-tête")
    f.case("Ensuite, **ne pilote plus le robot avec l'appli** pendant nos essais : une seule source de commandes à la "
           "fois, en plus de la télécommande.")
    f.titre("Le point principal au sol", 2)
    f.case("**La croix** du 27/10 (le point principal, l'accueil du robot) et **sa flèche** (la direction où le "
           "robot regarde, au moins 4 m libres devant) : remets-les si le ruban a été enlevé, au même endroit, dans "
           "le même sens.", feuille="en-tête (même croix ?)")
    f.case("Les repères à 1, 2, 3 et 4 m devant la croix, sur la ligne de la flèche (schéma 1).")
    f.titre("La feuille de résultats", 2)
    f.case("Ouvre **`Seance2_A_remplir.docx`** (ou `~/robot-g1/docs/releves/seance-2.md` dans VS Code). Note la "
           "date, l'heure et les personnes.", feuille="en-tête")


def partie_seance(f, schemas):
    f.titre("La séance", 1, saut=True)
    f.titre("Le déroulé en un coup d'œil", 2)
    t = f.table([1.6, 6.8, 3.7, 1.8, 3.1])
    f.ligne(t, ("Étape", "Ce qu'on fait", "Où est le robot", "Durée", "Feuille"), entete=True)
    for ligne in (("A", "Brancher, vérifier le robot, ouvrir la séance", "portique, allumé", "10 min", "A1 à A3"),
                  ("M", "Mesurer les vrais seuils (pont en consignes brutes)", "portique, mode marche", "25 min",
                   "M0 à M6"),
                  ("C", "La sécurité du pont, réglages normaux", "portique", "20 min", "C2 à C7"),
                  ("D", "Notre logiciel sur le Jetson, avec la caméra", "portique, immobile", "15 min", "D"),
                  ("E", "Le repérage, et la carte d'Unitree", "au sol, sur la croix", "20 min", "E1 à E4"),
                  ("F", "Le premier trajet : 2,5 m à 0,2 m/s", "au sol", "15 min", "F1 à F5"),
                  ("G", "La caméra de poitrine", "au sol, à l'accueil", "20 min", "G1 à G6"),
                  ("H", "Un nouveau scan, plus lent (si le temps le permet)", "au sol", "20 min", "H"),
                  ("P", "Le pilotage et une danse sûre", "portique", "25 min", "P1 à P5"),
                  ("V", "La voix du robot et la démo d'accueil (en option)", "portique, puis au sol", "20 min",
                   "V1, V2"),
                  ("Fin", "Plus rien sur le Jetson, Terminer la séance, le .zip, ranger", "portique, puis éteint",
                   "10 min", "Fin, Z1, Z2")):
        f.ligne(t, (f"**{ligne[0]}**",) + ligne[1:])
    f.ligne(t, ("", "**Total**", "", "**2 h 40**", "3 h avec H, 3 h 20 avec H et V"), fond=C["bleu_pale"])
    f.apres_tableau(6)

    f.titre("Les six terminaux, et qui parle à qui", 2)
    f.p("On utilise **6 terminaux**. Ouvre-les comme des onglets, dans l'ordre (**Ctrl+Maj+T** ouvre un nouvel "
        "onglet) : le premier est T1, le deuxième T2, etc. Dans **chacun**, une fois le câble branché (étape A), "
        "tape d'abord :")
    f.cmd("T1\nà T6", ["source ~/robot-g1/setup/robot.sh"], retrait=0)
    f.apres_tableau(4)
    t = f.table([2.4, 14.6])
    f.ligne(t, ("Terminal", "Sert à"), entete=True)
    for ligne in (("**T1**", "l'Atelier (notre logiciel : la page web), ouvert toute la journée"),
                  ("**T2**", "le pont (étapes M et C)"),
                  ("**T3**", "l'état du pont (`/pont/etat`)"),
                  ("**T4**", "les réponses du robot"),
                  ("**T5**", "les mesures et les commandes à la main"),
                  ("**T6**", "les commandes d'urgence (tuer le pont) et quelques commandes en plus")):
        f.ligne(t, ligne)
    f.apres_tableau(6)
    f.image(schemas["liaisons"], 13.0, "Schéma 2. Qui parle à qui. Aux étapes M et C, le pont tourne sur le PC (T2) "
                                       "et ses ordres passent par le câble ; à partir de l'étape E, tout tourne dans "
                                       "notre conteneur, sur le Jetson.")
    etape_a(f)
    etape_m(f)
    etape_c(f)
    etape_d(f)
    etape_e(f)
    etape_f(f)
    etape_g(f)
    etape_h(f)
    etape_p(f)
    etape_v(f)
    etape_fin(f)


def bloc_but(f, but, avant):
    f.p(f"**But :** {but}", apres=3, garder=True)
    if isinstance(avant, str):
        f.p(f"**Avant de commencer :** {avant}", apres=2, garder=True)
    else:
        f.p("**Avant de commencer :**", apres=1, garder=True)
        f.puces(avant).paragraph_format.keep_with_next = True


def nom_etape(f):
    return "fin de séance" if f.etape == "Fin" else f"étape {f.etape}"


def bloc_voir(f, items):
    f.apres_tableau(3)
    cellule = f.encadre("ok", f"Ce qu'on doit voir ({nom_etape(f)})")
    f.puces(items, cellule, taille=10.5)
    f.apres_tableau(3)


def bloc_probleme(f, items, avec=None):
    f.apres_tableau(3)
    cellule = f.encadre("attention", f"Si ça ne marche pas ({nom_etape(f)})", insecable=avec is None)
    f.puces(items, cellule, taille=10.5)
    if avec:
        avec(cellule)
    f.apres_tableau(4)


def etape_a(f):
    f.titre_etape("A", "brancher, vérifier le robot, ouvrir la séance", "10 min")
    bloc_but(f, "relier le PC au robot par le câble, lancer l'Atelier pour toute la journée, tout vérifier en un "
                "clic (« Vérifier le robot ») et ouvrir la séance que la boîte noire enregistre.",
             "robot accroché au portique (le cadre qui le tient par une sangle) ; les 6 terminaux ouverts.")
    f.case("Robot accroché au portique, allumé. Attends la fin de son démarrage, **environ 1 min**.")
    f.case("Branche le câble Ethernet entre le PC et le robot.")
    f.case("Dans T1, relie le terminal au robot :")
    f.cmd("T1", ["source ~/robot-g1/setup/robot.sh"])
    f.attendu("« ROS 2 relié au robot par eno2 (PC en 192.168.123.99) : le robot répond. »")
    f.case("La même commande dans T2, T3, T4, T5 et T6 : chacun doit dire « le robot répond ».")
    f.cmd("T2\nà T6", ["source ~/robot-g1/setup/robot.sh"])
    f.case("**A1. L'Atelier, pour toute la journée.** Dans T1 : 0,2 m/s au plus pour la navigation et le joystick, "
           "et l'adresse du pilotage sur le Jetson (étape P). Le navigateur s'ouvre tout seul.", feuille="A1")
    f.cmd("T1", ["G1_VITESSE_MAX=0.2 G1_PILOTAGE_URL=http://192.168.123.164:8010 g1-atelier"])
    f.attendu("l'accueil de l'Atelier, avec ses deux grandes cartes, **Simulation** et **Robot réel**. Laisse T1 "
              "ainsi jusqu'à la fin (règle d'or 8).")
    f.note("**seulement si tu veux essayer la borne de la démo sur ton téléphone** à l'étape V, ajoute "
           "`--hote 0.0.0.0` à la fin de la commande (depuis le Wi-Fi, seule la borne est permise : ni l'Atelier, ni "
           "« Débloquer », ni les réglages). Sinon, la borne s'ouvrira sur ce PC.", mot="Variante :",
           couleur=C["texte"])
    f.case("**A2. Vérifier le robot.** Sur l'accueil, la carte **Robot réel** (sans cocher « Répétition sans "
           "robot »), puis le bouton **Vérifier le robot**. Il ne fait jamais bouger le robot.",
           feuille="A2 et en-tête (batterie, services)")
    f.attendu("en 10 s environ (15 s au plus), une fenêtre où chaque point dit **OK**, **Attention**, **Problème** "
              "ou **Inconnu**, avec une phrase qui dit quoi faire : le câble, l'adresse du PC, la connexion "
              "`robot-g1`, les réglages ROS, le PC1, le Jetson et le LiDAR, les sujets du robot, les **services de "
              "cartographie**, le mode du robot, la **batterie**, le Jetson (clé SSH, Docker, image, place, horloge) "
              "et la caméra. Il remplace `g1-etat`, la liste de l'accueil et les services de l'appli.")
    f.case("**Services de cartographie arrêtés** (attendu, comme le 27/10) : clique sur **Démarrer les services de "
           "cartographie**, puis confirme dans la page. Seuls `lidar_driver` et `unitree_slam` sont démarrés : "
           "jamais un arrêt, rien d'autre n'est touché.", feuille="A2")
    f.attendu("en 20 s au plus : « Les services de cartographie ont démarré en … s ». Puis **Vérifier à nouveau** : "
              "la ligne passe à OK.")
    f.case("Lis les autres lignes. **Connexion du câble tombée** : **Rétablir la connexion du câble**. **Image du "
           "conteneur** : « faites g1-jetson envoyer » est attendu (l'image a été refaite le 10/11) : ce sera "
           "l'étape D. **Caméra** pas vue : normal, elle sera branchée sur le Jetson à l'étape D. **Mode du robot** : "
           "Attention est normal tant qu'il n'est pas en mode marche.")
    f.case("Note la batterie, la durée du diagnostic, et chaque ligne qui n'est pas OK avec son texte.", feuille="A2")
    f.case("**A3. Ouvrir la séance.** Toujours sur l'accueil : le lieu **« Séance robot »**, coche **« Télécommande "
           "en main »**, puis **Ouvrir**.", feuille="A3")
    f.attendu("l'espace de travail ; dans la barre d'outils, le badge **« ● Enregistrement »** (« Séance », ou un "
              "point rouge, sur un écran plus étroit) : la boîte noire garde tout jusqu'à « Terminer la séance » (fin "
              "de séance). Note l'heure.")
    f.note("les marches lancées à la main aux étapes M et C seront dans le rapport comme « mouvements sans "
           "demande » : c'est normal.", mot="Bon à savoir :", couleur=C["texte"])
    bloc_probleme(f, [
        "« Câble non détecté sur eno2 » : rebranche le câble des deux côtés, attends 10 s et recommence.",
        "« Câble branché, mais le robot ne répond pas » : attends la fin de son démarrage (1 min), puis recommence.",
        "« Impossible d'activer la connexion robot-g1 » : `nmcli connection up robot-g1`, puis recommence.",
        "Les services de cartographie restent arrêtés : note le message, active-les dans l'appli Unitree Explore "
        "(secours), puis **Vérifier à nouveau**.",
        "La page ne répond pas : le même diagnostic dans T5, `g1-diagnostic` ; la batterie : `g1-etat` (Ctrl+C pour "
        "quitter).",
    ])


def etape_m(f):
    f.titre_etape("M", "mesurer les vrais seuils, au portique", "25 min")
    bloc_but(f, "mesurer ce que fait vraiment le robot pour de petites vitesses : à partir de quelle vitesse il fait "
                "des pas (le **seuil**), en avant, de côté et en rotation, et son temps de réaction (la "
                "**latence**).",
             "robot accroché au portique, **sangle lâche, pieds au sol**, en **mode marche** (à la télécommande) ; la "
             "personne 1 a la télécommande en main.")
    f.p("Ici, le pont tourne en **consignes brutes** : il transmet la vitesse demandée telle quelle, sans la monter "
        "au minimum de 0,2 m/s. Chaque mesure envoie une vitesse pendant 3 s, à travers le pont, puis affiche en "
        "français : le **retard** (du premier ordre jusqu'à la moitié de la vitesse), la **montée** (de 10 % à 90 % "
        "de la vitesse), la **vitesse atteinte**, l'**arrêt** (du dernier ordre jusqu'à l'arrêt du robot) et le "
        "**dépassement** (ce que le robot parcourt après le dernier ordre). Elle n'envoie rien si le pont n'est pas "
        "« pret ».", taille=10.5)
    cellule = f.encadre("attention", "Prudence")
    f.puces([
        "Pendant cette étape, le pont n'a **pas de vitesse minimale** : tape les vitesses **exactement** comme "
        "écrit (la mesure refuse plus de 0,3 m/s, 0,6 rad/s et 5 s ; le pont, lui, plafonne à 0,2 m/s et "
        "0,4 rad/s).",
        "Attends la fin de chaque mesure (environ 6 s) avant la suivante.",
        "Si le robot s'éloigne du centre du portique, ramène-le à la télécommande entre deux mesures : la sangle "
        "ne doit jamais se tendre pendant une marche.",
    ], cellule, taille=10.5)
    f.apres_tableau(4)
    f.case("**T2, le pont en consignes brutes** (sans vitesse minimale ni zone morte), avec des plafonds de "
           "0,2 m/s et 0,4 rad/s :")
    f.cmd("T2", ["ros2 run g1_bridge pont --ros-args -p exiger_reperage:=false -p vitesse_min_lin:=0.0 -p "
                 "vitesse_min_rot:=0.0 -p zone_morte_lin:=0.0 -p zone_morte_rot:=0.0 -p vx_max:=0.2 -p "
                 "vy_max:=0.2 -p wz_max:=0.4"])
    f.attendu("le pont démarre. Deux avertissements jaunes sont normaux ici : « exiger_reperage est faux… » et "
              "« vitesse minimale désactivée… ».")
    f.case("**M0. T3, l'état du pont :**", feuille="M0")
    f.cmd("T3", ["ros2 topic echo /pont/etat --field data"])
    f.attendu("`\"etat\": \"pret\"` et, dans `mode_robot`, `\"fsm\": 501` (marche). Note le `fsm`. Laisse T3 "
              "ouvert : il sert jusqu'à la fin de l'étape C.")
    f.case("**M1. En avant**, dans T5, une commande après l'autre. Le **seuil** est la plus petite vitesse où le "
           "robot fait vraiment des pas. Copie chaque résultat.", feuille="tableau M1")
    f.cmd("T5", ["python3 -m g1_bridge.mesure marche --vx 0.12 --duree 3",
                 "python3 -m g1_bridge.mesure marche --vx 0.15 --duree 3",
                 "python3 -m g1_bridge.mesure marche --vx 0.18 --duree 3",
                 "python3 -m g1_bridge.mesure marche --vx 0.2 --duree 3"])
    f.case("**M2. De côté** (vers la gauche, puis une fois vers la droite) :", feuille="tableau M2")
    f.cmd("T5", ["python3 -m g1_bridge.mesure marche --vx 0 --vy 0.12 --duree 3",
                 "python3 -m g1_bridge.mesure marche --vx 0 --vy 0.15 --duree 3",
                 "python3 -m g1_bridge.mesure marche --vx 0 --vy 0.18 --duree 3",
                 "python3 -m g1_bridge.mesure marche --vx 0 --vy 0.2 --duree 3",
                 "python3 -m g1_bridge.mesure marche --vx 0 --vy -0.15 --duree 3"])
    f.note("la dernière commande fait un pas **à droite** (vitesse négative).", mot="Remarque :",
           couleur=C["texte"])
    f.case("**M3. En diagonale.** Le pont suppose que le robot regarde la **norme** de (vx, vy), c'est-à-dire la "
           "longueur de la flèche de vitesse, √(vx² + vy²) : (0,1 ; 0,1) fait 0,14, et (0,14 ; 0,14) fait 0,20.",
           feuille="tableau M3")
    f.cmd("T5", ["python3 -m g1_bridge.mesure marche --vx 0.1 --vy 0.1 --duree 3",
                 "python3 -m g1_bridge.mesure marche --vx 0.14 --vy 0.14 --duree 3"])
    f.attendu("la première (norme 0,14) : immobile ? La seconde (norme 0,20) : il marche ?", mot="À regarder :")
    f.case("**M4. Rotation sur place** :", feuille="tableau M4")
    f.cmd("T5", ["python3 -m g1_bridge.mesure rotation --wz 0.1 --duree 3",
                 "python3 -m g1_bridge.mesure rotation --wz 0.15 --duree 3",
                 "python3 -m g1_bridge.mesure rotation --wz 0.2 --duree 3",
                 "python3 -m g1_bridge.mesure rotation --wz 0.3 --duree 3",
                 "python3 -m g1_bridge.mesure rotation --wz 0.4 --duree 3"])
    f.note("pour `--wz 0.3`, note aussi le **retard** et la **montée** : ils servent à régler la rotation finale du "
           "guide (étape F).", mot="Important :", couleur=C["texte"])
    f.case("**M5. Latence et distance d'arrêt à 0,2 m/s** :", feuille="tableau M5")
    f.cmd("T5", ["python3 -m g1_bridge.mesure marche --vx 0.2 --duree 3"])
    f.note("le retard (jusqu'à la moitié de la vitesse), la montée, l'arrêt après le dernier ordre et le dépassement "
           "en mètres.", mot="Note :", couleur=C["texte"])
    f.case("**M6. Les modes.** Avec la télécommande, mets le robot dans chaque posture et lis le `fsm` dans T3 "
           "(dans `mode_robot`) : amorti, assis, accroupi, debout, marche, course ; puis, depuis assis, "
           "« Démarrer » : 500, puis 501 ?", feuille="tableau M6")
    f.note("avant « amorti », tends la sangle : le portique doit tenir le robot quand ses moteurs se relâchent.",
           mot="Prudence :", couleur=C["ambre"])
    f.case("**Ctrl+C dans T2** : le pont envoie un arrêt en quittant. Remets le robot en mode marche.")
    bloc_voir(f, [
        "Chaque mesure affiche : « consigne demandée », « vitesse atteinte », « retard », « montée », « arrêt », "
        "« dépassement après le dernier ordre », « parcouru en tout », puis « 7105 envoyé par le pont : (…) ».",
        "Sous le seuil, la vitesse atteinte est presque nulle, ou « inconnu » : le robot n'a pas bougé.",
    ])
    bloc_probleme(f, [
        "« le pont n'est pas prêt (…) : rien n'est envoyé » : regarde T3. `pas_en_marche` : mets le robot en mode "
        "marche à la télécommande ; `robot_muet` : voir la ligne suivante.",
        "T3 reste `robot_muet` (le robot ne répond pas au pont) : dans T5, `ros2 topic info -v /api/sport/request`, "
        "note ce qui s'affiche, arrête le pont (Ctrl+C dans T2) et passe à l'étape D.",
        "« pas d'odométrie (/state_estimator/odom_pelvis) ou pas de /pont/etat » : `robot.sh` a-t-il été tapé dans "
        "T5 ? Le pont tourne-t-il dans T2 ?",
        "« mesure refusée : au plus 0,3 m/s… » : faute de frappe dans la vitesse ou la durée.",
    ])


def etape_c(f):
    f.titre_etape("C", "la sécurité du pont, avec ses réglages normaux", "20 min")
    bloc_but(f, "vérifier, avec le nouveau pont, que le robot s'arrête seul si le pont meurt, que la télécommande "
                "reste prioritaire, que le robot assis ne bouge pas et que nos arrêts marchent (reprise des points "
                "C3 à C5 et C7 de la séance n° 1).",
             "robot au portique, en mode marche ; pont arrêté (Ctrl+C fait à la fin de M) ; T3 montre toujours "
             "l'état du pont.")
    f.case("**T2, le pont avec ses défauts** (vitesse minimale 0,2 m/s et 0,3 rad/s) et des plafonds réduits :")
    f.cmd("T2", ["ros2 run g1_bridge pont --ros-args -p exiger_reperage:=false -p vx_max:=0.2 -p vy_max:=0.2 -p "
                 "wz_max:=0.3"])
    f.attendu("T3 repasse à `pret`.")
    f.case("**C2. Le minimum du pont** : on demande 0,1 m/s, le pont envoie 0,2 m/s.", feuille="C2")
    f.cmd("T5", ["python3 -m g1_bridge.mesure marche --vx 0.1 --duree 3"])
    f.attendu("« **7105 envoyé par le pont : (0.2, 0.0, 0.0)** », et le robot marche.")
    f.case("**C3. Tourner, puis un pas de côté**, 2 s chacun (`-r 10 -t 20` : 10 messages par seconde, 20 messages, "
           "donc 2 s) :", feuille="C3")
    f.cmd("T5", ["# tourne à gauche",
                 'ros2 topic pub -r 10 -t 20 /cmd_vel geometry_msgs/msg/Twist "{angular: {z: 0.3}}"',
                 "# pas vers la gauche",
                 'ros2 topic pub -r 10 -t 20 /cmd_vel geometry_msgs/msg/Twist "{linear: {y: 0.2}}"'])
    f.attendu("il tourne vers la gauche, puis fait un pas vers la gauche : dans le bon sens.")
    f.case("**C4. Le robot s'arrête-t-il seul si le pont meurt ?** C'est **essentiel**. Lance une marche de 10 s "
           "dans T5 :", feuille="C4")
    f.cmd("T5", ['ros2 topic pub -r 10 -t 100 /cmd_vel geometry_msgs/msg/Twist "{linear: {x: 0.2}}"'])
    f.case("Après 3 s, dans T6, tue le pont (`-9` : arrêt brutal, sans que le pont puisse envoyer un arrêt) :")
    f.cmd("T6", ["pkill -9 -f lib/g1_bridge/pont"])
    f.attendu("le robot s'arrête en **moins d'une seconde**.")
    f.stop("**s'il continue : télécommande, amortissement, fin de la séance.**")
    f.case("**Avant de relancer le pont, arrête la marche dans T5 (Ctrl+C)**, ou attends qu'elle soit finie : "
           "sinon le nouveau pont reprend ces ordres et **le robot repart tout seul** (un pont relancé suit tout "
           "ordre frais, même ceux d'une marche lancée avant lui). Relance ensuite le pont dans T2 (la même "
           "commande qu'au début de l'étape : flèche ↑ pour la retrouver).")
    f.case("**C5. La télécommande reste-t-elle prioritaire ?** C'est **la condition pour continuer**. Relance la "
           "marche de 10 s dans T5 (la même commande, flèche ↑) ; pendant ce temps, la personne 1 arrête le robot "
           "avec la télécommande.", feuille="C5")
    f.attendu("la télécommande gagne **tout de suite**.")
    f.stop("**si la télécommande ne reprend pas la main : amortissement, fin de la séance.**")
    f.case("Puis **Ctrl+C dans T5** si la marche n'est pas finie : sinon, quand la télécommande lâche, le robot "
           "peut repartir.")
    f.case("**C6. Hors du mode marche.** Mets le robot **assis** (télécommande), puis lance une marche de 2 s :",
           feuille="C6")
    f.cmd("T5", ['ros2 topic pub -r 10 -t 20 /cmd_vel geometry_msgs/msg/Twist "{linear: {x: 0.2}}"'])
    f.attendu("il ne bouge pas ; T3 passe à `pas_en_marche`, avec un message qui contient « assis ». Remets-le en "
              "marche : T3 repasse à `pret` **sans mouvement** ; la marche ne reprend qu'avec une nouvelle "
              "commande.")
    f.case("**C7. Nos arrêts.** Lance une marche de 10 s dans T5 (comme en C4), puis, dans T6, l'arrêt du guide :",
           feuille="C7")
    f.cmd("T6", ['ros2 topic pub --once /guide/stop std_msgs/msg/Empty "{}"'])
    f.attendu("arrêt net, puis il repart 1 s plus tard (la marche de 10 s continue d'envoyer).")
    f.case("Toujours pendant la marche, dans T6, **le verrou** (il interdit tout mouvement jusqu'à ce qu'on "
           "l'enlève) :")
    f.cmd("T6", ['ros2 topic pub --once --qos-durability transient_local --qos-reliability reliable /pont/arret '
                 'std_msgs/msg/Bool "{data: true}"'])
    f.attendu("arrêt net, puis plus rien ne bouge ; T3 : `arret_verrouille`.")
    f.case("Enlève le verrou (la même commande avec `false`) :")
    f.cmd("T6", ['ros2 topic pub --once --qos-durability transient_local --qos-reliability reliable /pont/arret '
                 'std_msgs/msg/Bool "{data: false}"'])
    f.note("si la marche de 10 s n'est pas finie, le robot repart : c'est normal.", mot="Remarque :",
           couleur=C["texte"])
    f.case("Fin de l'étape : **Ctrl+C dans T2** (le pont envoie un arrêt en quittant). Tends la sangle, puis mets "
           "le robot en **amortissement** sur le portique.")
    bloc_probleme(f, [
        "Le pont refuse de démarrer (« … le robot ne ferait aucun pas ») : un plafond est sous 0,2 m/s ; utilise "
        "les commandes de ce document telles quelles.",
        "T3 reste `pas_en_marche` : lis le message. Assis ou pas démarré : « Démarrer » à la télécommande ; course "
        "(802) : marche normale.",
        "Le robot ne s'arrête pas seul (C4) : télécommande, amortissement, **fin de la séance**.",
    ])


def etape_d(f):
    f.titre_etape("D", "notre logiciel sur le Jetson, avec la caméra", "15 min")
    bloc_but(f, "copier notre image Docker sur le Jetson et vérifier que notre conteneur (la « boîte » qui contient "
                "notre logiciel, sans rien installer dans le Jetson) voit le robot et la caméra.",
             "robot au portique, immobile ; pont arrêté.")
    f.case("**Branche la See3CAM sur un port USB 3 du Jetson** (port bleu). Le conteneur ne reçoit la caméra qu'à "
           "son démarrage : elle doit être branchée avant.")
    f.case("Dans T5, la clé ssh (ssh : la connexion au Jetson par le câble), **seulement si « Vérifier le robot » "
           "l'a demandée** (« Le Jetson demande un mot de passe ») : la première fois, réponds `yes`, puis le mot de "
           "passe **123**.")
    f.cmd("T5", ["ssh-copy-id unitree@192.168.123.164"])
    f.case("L'envoi : **2 à 5 min** (copie la nouvelle image et la charge dans Docker du Jetson). Note la durée.",
           feuille="D")
    f.cmd("T5", ["g1-jetson envoyer"])
    f.case("La vérification du Jetson : elle regarde aussi les sujets du robot vus du conteneur, et la caméra.",
           feuille="D")
    f.cmd("T5", ["g1-jetson verifier"])
    f.case("Dans l'Atelier, **Vérifier le robot** de nouveau (le bouton de la barre d'outils, ou Naviguer › "
           "Vérifier le robot).", feuille="D")
    bloc_voir(f, [
        "La ligne de la caméra de `verifier` : « OK caméra See3CAM : /dev/v4l/by-id/…-video-index0 → /dev/video… "
        "(**USB 5000 Mbit/s**, groupe …) ». Le groupe est un nombre (44 est en général le groupe « video ») : "
        "note-le.",
        "« OK sujets du robot vus depuis le conteneur Humble : /state_estimator/odom_pelvis (…) et "
        "/lf/sportmodestate (…) », puis « **Jetson prêt.** »",
        "Dans « Vérifier le robot » : les lignes du Jetson sont OK (« Le Jetson a la même image du conteneur que le "
        "PC »), et la caméra est « branchée sur le Jetson ».",
        "À noter (ligne D) : la durée d'`envoyer`, la ligne de la caméra, le groupe, ce que `verifier` dit des "
        "sujets du robot, et les lignes du Jetson et de la caméra de « Vérifier le robot ».",
    ])

    def suite(cellule):
        f.p("« **Docker ne marche pas sur le Jetson sans sudo** » (« Vérifier le robot ») ou « **Docker inutilisable "
            "sans sudo** » (`verifier`) : seul changement système possible, si tu es d'accord. Ajoute "
            "l'utilisateur `unitree` au groupe docker :", cellule, taille=10.5, avant=4, apres=2)
        f.cmd("T5", ["ssh unitree@192.168.123.164", "sudo usermod -aG docker unitree", "exit"], cellule,
              retrait=0.3, largeur=cellule._g1_largeur - 0.6)
        f.p("Le mot de passe est **123**. Puis relance `g1-jetson verifier`. Si tu préfères ne pas faire ce "
            "changement, fais les étapes E et F avec le **plan B** (section 7).", cellule, taille=10.5, avant=3)

    bloc_probleme(f, [
        "Caméra « en USB 2 (480 Mbit/s) » : change de port (un USB 3, bleu), puis relance `g1-jetson verifier`.",
        "« caméra See3CAM : non branchée » : rebranche-la, puis relance `g1-jetson verifier`.",
        "« le Jetson ne répond pas par ssh » : câble, `robot.sh` ; la première fois, `ssh-copy-id`.",
        "`envoyer` échoue : note le message ; `g1-jetson verifier` montre la place libre. Puis plan B (section 7).",
        "« sujets du robot invisibles depuis le conteneur » : fais E et F avec le plan B (section 7).",
    ], avec=suite)


def etape_e(f):
    f.titre_etape("E", "le repérage, et la carte d'Unitree", "20 min")
    bloc_but(f, "le robot retrouve sa position sur la carte du 27/10 (le **repérage**, commande 1804), et on "
                "récupère au passage la carte d'Unitree.",
             "notre image est sur le Jetson (étape D) et la caméra y est branchée. La carte est celle du 27/10, "
             "retraitée : l'accueil (le point principal) est sur la croix.")
    f.case("À la télécommande, remets le robot **debout, puis en mode marche**, encore tenu par la sangle (il est en "
           "amortissement depuis la fin de l'étape C). Puis décroche-le et amène-le **sur la croix, dans le sens de "
           "la flèche**, toujours en **mode marche**.")
    f.case("L'Atelier tourne depuis l'étape A, sur le lieu « Séance robot », séance ouverte : **rien à relancer**. "
           "Si tu as un doute, **Vérifier le robot** : tout doit être OK (le mode du robot aussi, maintenant).")
    f.case("Ruban **Naviguer › Lancer** (le ruban : la barre d'onglets en haut de l'Atelier). L'Atelier demande "
           "de confirmer : relis sa liste, puis « **Lancer sur le robot** ». Il copie alors le lieu sur le Jetson "
           "et démarre notre conteneur, avec la caméra.")
    f.attendu("« Non repéré », et la pastille du robot, en haut à droite, « À repérer ».")
    f.case("T4, les réponses du robot au repérage :")
    f.cmd("T4", ["ros2 topic echo /api/slam_operate/response"])
    f.case("**E4. La carte d'Unitree.** Dans T5, lance l'attente (90 s au plus) **juste avant** de repérer :",
           feuille="E4")
    f.cmd("T5", ["g1-scan carte-unitree --lieu seance --etage rdc --delai 90"])
    f.case("**E1. Tout de suite**, dans l'Atelier : **Naviguer › Repérer**.", feuille="E1")
    f.attendu("en moins de 20 s : « **Repéré** », avec la précision. Note le texte de la réponse (T4) et la durée.")
    f.case("**E4 (suite).** Dans T5, `g1-scan carte-unitree` doit finir pendant ce temps : il écrit "
           "`lieux/seance/cartes/rdc_unitree.pcd` et son nuage. Note ce qu'il affiche : « Carte d'Unitree reçue "
           "(… points, …) », ou « Erreur : aucune carte reçue… » (dans ce cas, note-le : la documentation non "
           "officielle se trompait peut-être).", feuille="E4")
    f.case("**E2. Ce que publie le robot.** Dans T5, chaque commande 5 s, puis Ctrl+C :", feuille="E2")
    f.cmd("T5", ["ros2 topic hz /unitree/slam_relocation/odom",
                 "ros2 topic hz /unitree/slam_relocation/points"])
    f.attendu("une fréquence (« average rate », en messages par seconde) pour chacun. Note-les.", mot="À noter :")
    f.case("**E3. La précision, à la télécommande** (notre logiciel n'envoie rien tant qu'on ne lui demande pas de "
           "trajet) : avance le robot d'environ 2 m, puis tourne-le d'un quart de tour. Compare la position du robot "
           "avec le mètre ruban, depuis la croix. Trois mesures.", feuille="tableau E3")
    f.note("les chiffres exacts sont dans le champ `\"pose\"` de cette commande (T5) : x (le long de la flèche) "
           "et y (vers la gauche) en mètres, theta en radians.", mot="Pour lire la position :", couleur=C["texte"])
    f.cmd("T5", ["ros2 topic echo --once /reperage/etat --field data"])
    f.attendu("**moins de 10 cm** d'écart.")
    bloc_probleme(f, [
        "« Repérer » échoue : note le message, puis dans T5 `ros2 topic echo --once /slam_info` et "
        "`g1-jetson journal 2>&1 | tail -n 30`.",
        "`carte-unitree` : « aucune carte reçue » : note-le ; relance-le, puis **Repérer** de nouveau pendant "
        "l'attente.",
        "« Le conteneur du robot n'a pas démarré : … » : note le message mot pour mot, puis plan B (section 7).",
    ])


def etape_f(f):
    f.titre_etape("F", "le premier trajet, 2,5 m à 0,2 m/s", "15 min")
    bloc_but(f, "le robot va seul jusqu'à 2,5 m devant la croix, revient seul à l'accueil, et s'arrête net sur "
                "ARRÊT.",
             "robot repéré (étape E), près de la croix. La personne 1 se tient à côté du robot, télécommande en "
             "main ; la personne 2 suit, câble lâche (ne jamais tirer sur le câble : la prise du robot est fragile).")
    f.case("**F1.** Ruban **Naviguer › Y aller** : « **Essai à 2,5 m** ».", feuille="F1")
    f.attendu("le panneau dit « En route », le robot marche droit vers le but, puis « Arrivé ». Note la durée et "
              "l'écart au mètre ruban.")
    f.case("**F2. Le retour seul.** 15 s après l'arrivée, le robot revient seul à l'accueil et **se tourne dans le "
           "sens de la flèche**. Regarde s'il tourne **une seule fois** ou s'il oscille (il tourne, dépasse, "
           "revient…). Note l'écart final à la flèche, en degrés (à l'œil ou au rapporteur).", feuille="F2")
    f.note("pendant ces 15 s, **ARRÊT** (ou Échap, même avec un menu ouvert) annule le retour : le robot reste sur "
           "place.", mot="Bon à savoir :", couleur=C["texte"])
    f.case("**F3. ARRÊT.** **Y aller** « Essai à 2,5 m » de nouveau, puis clique sur **ARRÊT** (barre d'outils, en "
           "haut à droite) à mi-chemin.", feuille="F3")
    f.attendu("arrêt net ; le bouton devient « **Débloquer** » ; le panneau dit « Robot bloqué : le trajet vers "
              "« Essai à 2,5 m » est annulé… ». **Y aller** est grisé (« Robot bloqué : « Débloquer » d'abord ») ; "
              "demandé quand même (par le chatbot, par exemple), il est refusé : le robot ne garde aucune demande "
              "pour plus tard.")
    f.case("Clique sur **Débloquer** (l'Atelier demande de confirmer : « Débloquer ») : **rien ne bouge**, le robot "
           "ne reprend pas l'ancien trajet (correction du 01/11), et le panneau dit « Robot débloqué : il attend un "
           "nouveau « Y aller » ». Pour repartir, il faut **refaire « Y aller »** : **Y aller** « Accueil ».")
    f.stop("**si le robot repart seul au « Débloquer » : télécommande, amortissement, fin de la séance** ; "
           "note-le (ligne F3).")
    f.case("**F4.** À l'arrivée, l'écart entre le robot et la croix.", feuille="F4")
    f.attendu("**moins de 30 cm**.")
    f.case("**F5. La rotation finale, seulement si le robot a oscillé en F2** (10 min ; 1 m libre autour du "
           "robot). Dans T5, le suivi du cap (il n'envoie rien) :", feuille="tableau F5")
    f.cmd("T5", ["python3 -m g1_bridge.mesure cap --pendant 20 --angle 90"])
    f.case("Tout de suite, dans T6, une rotation de 90° demandée à Nav2 (le « Spin » ; 1,5708 rad = 90°) :")
    f.cmd("T6", ['ros2 action send_goal /spin nav2_msgs/action/Spin "{target_yaw: 1.5708, time_allowance: '
                 '{sec: 20}}"'])
    f.attendu("dans T5, « dépassement par rapport à 90° : +…° (+… rad) ». Note-le, en degrés et en radians.",
              mot="À noter :")
    f.case("Règle le guide en marche, dans T6. Les valeurs sont en radians, **avec un point** (la mesure affiche "
           "« 0,30 » avec une virgule : tape `0.30`). Remplace `D` par le dépassement, et `T` par 0,6 × D :")
    f.cmd("T6", ["ros2 param set /guide anticipation_rotation_rad D",
                 "ros2 param set /guide tolerance_orientation_rad T"])
    f.note("dépassement de 17° = 0,30 rad : tape `0.30` à la place de D, et `0.18` à la place de T "
           "(0,6 × 0,30). Attendu : « Set parameter successful ». Un dépassement négatif (le robot tourne moins "
           "de 90°) : ne change rien, note-le.", mot="Exemple :", couleur=C["texte"])
    f.case("Refais F2 (Y aller « Essai à 2,5 m », puis attends le retour) : **une seule rotation** attendue.",
           feuille="F5")
    bloc_probleme(f, [
        "« Y aller » refusé, « Repérez d'abord le robot… » : refais E1.",
        "Le robot oscille à la fin d'un trajet : fais F5.",
        "Quelque chose bouge sans qu'on l'ait demandé : télécommande, amortissement, **fin de la séance**.",
    ])


def etape_g(f):
    f.titre_etape("G", "la caméra de poitrine", "20 min")
    bloc_but(f, "vérifier que les images de la caméra arrivent sur le PC, régler sa position et étalonner les "
                "distances.",
             "le conteneur tourne depuis l'étape E, avec la caméra ; robot à l'accueil (sur la croix), face à la "
             "flèche ; les repères à 1, 2, 3 et 4 m sont au sol.")
    f.case("**G1. Les images arrivent sur le PC.** Dans T5, chaque commande quelques secondes, puis Ctrl+C :",
           feuille="G1")
    f.cmd("T5", ["ros2 topic hz /camera_poitrine/image/compressed",
                 "ros2 topic bw /camera_poitrine/image/compressed",
                 "ros2 topic echo --once /camera_poitrine/etat --field data"])
    f.attendu("`hz` : **environ 10** images par seconde ; `bw` : une image de 30 à 60 Ko (« Message size mean ») ? "
              "La dernière affiche l'état de la caméra, une seule fois.")
    f.case("**G2. Dans l'Atelier** : barre de la vue centrale › **Caméra**. L'image doit être nette, **ni noire ni "
           "blanche** (exposition automatique), en pleine lumière comme à l'ombre.", feuille="G2")
    f.case("**G3. Les réglages** : ruban **Équipe › Caméra**, « **Préréglage See3CAM_11CUG** », puis la "
           "**position sur le robot**, robot debout : z = hauteur de la caméra au-dessus du sol, x = avance par "
           "rapport au centre du robot, tangage = inclinaison (**négatif si elle regarde vers le haut** : 12° vers "
           "le haut = −12°). **✓ Enregistrer.**", feuille="G3")
    f.case("**G4. Les visiteurs.** Dans T5 :", feuille="G4")
    f.cmd("T5", ["g1-visiteurs --lieu seance --source robot --image"])
    f.attendu("une personne debout devant le robot : un cadre apparaît sur l'image de l'Atelier (vue Caméra), avec son "
              "numéro et sa distance (« n° 1 · 3,4 m ») ; vert si elle regarde le robot, orange sinon.")
    f.case("**G5. Les distances.** La personne se tient sur les repères à **1, 2, 3 et 4 m**. Dans T6, les distances "
           "estimées par la caméra :", feuille="tableau G5")
    f.cmd("T6", ["ros2 topic echo /visiteurs/detectes --field data | grep --line-buffered -o '\"distance_m\": "
                 "[0-9.]*'"])
    f.note("note la distance affichée pour chaque repère. La correction est : distance vraie ÷ distance affichée, "
           "en moyenne sur les 4 repères. Mets-la dans **Équipe › Caméra › Réglages avancés › « Correction des "
           "distances »** (le réglage `correction_distance`), puis **✓ Enregistrer**.", mot="Puis :",
           couleur=C["texte"])
    f.case("**G6. Le champ de vision** (l'angle que voit la caméra) : une règle ou un mètre à 1 m devant la "
           "caméra, d'un bord à l'autre de l'image. Note la largeur vue (le champ supposé est de 90°, soit 2 m vus à "
           "1 m). Le tableau donne le champ (champ = 2 × arctan(largeur ÷ 2)) ; tu peux l'écrire dans Équipe › "
           "Caméra › « Champ horizontal ».", feuille="tableau G6").paragraph_format.keep_with_next = True
    largeurs = [1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5]
    t = f.table([3.1] + [1.9] * len(largeurs), retrait=RETRAIT)
    f.ligne(t, ["Largeur vue à 1 m"] + [nombre(x) + " m" for x in largeurs], entete=True, taille=9.5)
    f.ligne(t, ["Champ de vision"] + [f"{2 * math.degrees(math.atan(x / 2)):.0f}°" for x in largeurs], taille=9.5)
    f.apres_tableau(3)
    f.case("Ctrl+C dans T5 (`g1-visiteurs`) et dans T6.")
    bloc_probleme(f, [
        "Vue Caméra : « Pas d'image » : `ros2 topic hz /camera_poitrine/image/compressed` ; "
        "`g1-jetson journal 2>&1 | grep -i cam`.",
        "Image noire : Équipe › Caméra › Réglages avancés : exposition automatique ; note la lumière de la pièce.",
        "`g1-visiteurs` dit « aucune image de … depuis 5 s » : la caméra est-elle dans le conteneur ? "
        "`g1-jetson etat` doit dire « caméra /dev/g1_camera » ; « caméra non » : voir la section 7, ligne "
        "« `verifier` : pas de ligne caméra ».",
    ])


def etape_h(f):
    f.titre_etape("H", "un nouveau scan, plus lent", "20 min, si le temps le permet")
    bloc_but(f, "comparer la carte de notre nouvelle chaîne à celle d'Unitree Explore.",
             "l'étape G est finie. Si le temps manque, saute H et va à l'étape P (son premier point le prévoit).")
    f.case("Ruban **Naviguer › Arrêter** (la navigation et le conteneur s'arrêtent). Juste avant, la boîte noire "
           "garde toute seule le journal du conteneur dans la séance (30 s au plus) : plus rien à copier à la "
           "main. Pour le voir, dans T5 :", feuille="H")
    f.cmd("T5", ["ls ~/robot-g1/journaux/seances/*/journaux/jetson/"])
    f.attendu("un fichier `conteneur_…_avant_arret.log`.")
    f.note("seulement si aucune séance n'est ouverte (pas de badge dans la barre d'outils) : **avant** « Arrêter », "
           "garde le journal à la main (le conteneur l'emporte avec lui quand il s'arrête) : `g1-jetson journal "
           "--lignes 100000 > ~/robot-g1/docs/releves/seance-2_navigation.log 2>&1`.", mot="Secours :",
           couleur=C["ambre"])
    f.case("**Robot sur la croix**, dans le sens de la flèche, en mode marche.")
    f.case("Ruban **Scanner › Scan** (confirme si l'Atelier le demande). L'écran passe en plein écran : le nuage se "
           "remplit en direct.")
    f.case("Promène le robot à la télécommande, **plus lentement que le 27/10** : moins de 0,5 m/s, virages lents, "
           "personne entre le robot et les murs. La personne du PC suit, câble lâche.")
    f.case("**Reviens sur la croix, dans le sens de la flèche**, puis **Fin**. La carte et le nuage sont prêts en "
           "quelques secondes.")
    f.case("**Ne clique pas sur « Utiliser cette carte » aujourd'hui** : on compare d'abord, à tête reposée. Note la "
           "durée, la distance, le nombre de points, et ce que tu vois : murs fermés ? tables et chaises "
           "reconnaissables ? carte ni dédoublée ni tournée ?", feuille="H")
    bloc_probleme(f, [
        "Le câble s'est débranché pendant le scan : rebranche-le, `nmcli connection up robot-g1`, puis note-le "
        "(le scan sera sans doute incomplet).",
        "Carte dédoublée ou tournée : ne l'adopte pas ; note-le.",
    ])


def etape_p(f):
    f.titre_etape("P", "le pilotage et une danse sûre", "25 min")
    bloc_but(f, "vérifier le pilotage (prendre la main, postures, joysticks, ARRÊT) depuis le mode 501, puis une "
                "danse sûre (604), robot tenu au portique.",
             "le conteneur de navigation est arrêté (étape H, ou le premier point ci-dessous).")
    f.case("**Seulement si tu as sauté l'étape H** : le conteneur de la navigation tourne encore, et le démarrage "
           "ci-dessous refuserait (« le conteneur g1-jetson tourne déjà »). Fais d'abord ruban **Naviguer › "
           "Arrêter** (premier point de l'étape H : la boîte noire garde son journal).")
    f.case("**Robot raccroché au portique**, pieds au sol, en mode marche.")
    f.case("Le nœud pilotage seul, sur le Jetson (un nœud : un programme ROS). Dans T5, l'une après l'autre :")
    f.cmd("T5", ["G1_VITESSE_MAX=0.2 g1-jetson demarrer --veille",
                 "export G1_PILOTAGE_URL=http://192.168.123.164:8010",
                 "export G1_PILOTAGE_JETON=$(cat ~/robot-g1/opt/jetson/jeton_pilotage)",
                 "g1-pilotage etat"])
    f.attendu("`\"robot_repond\": true` ; note le `fsm` (501 ?).")
    f.case("Dans l'Atelier, ruban **Piloter** : l'Atelier, lancé à l'étape A avec l'adresse du pilotage "
           "(`G1_PILOTAGE_URL`), le trouve sur le Jetson. **Ne le relance pas** : la séance continue.")
    f.case("**P1. Prendre la main**, puis **Postures › Démarrer** : note le mode lu.", feuille="P1")
    f.case("**P2. Les joysticks** (case **Joysticks** du ruban) : le manche gauche **à peine incliné** fait marcher "
           "le robot à 0,2 m/s (la vitesse minimale, la même que celle du pont), pas moins.", feuille="P2")
    f.case("**P3. ARRÊT pendant le joystick** : un pouce tient le manche, l'autre main clique sur **ARRÊT**.",
           feuille="P3")
    f.attendu("le robot s'arrête, et **le manche tenu ne le relance pas** : il faut le lâcher, puis le reprendre. "
              "Clique ensuite sur **Débloquer** (et confirme).")
    f.note("de même, si le robot est mis assis ou en amortissement à la télécommande pendant que le manche est "
           "tenu, il ne repart pas à la remise en marche tant que le manche n'a pas été lâché ; une chorégraphie "
           "interrompue ainsi ne reprend pas (correction du 01/11).", mot="Bon à savoir :", couleur=C["texte"])
    f.case("**P4. Une danse sûre, depuis 501** : robot **tenu** au portique, 3 m libres autour. **Spectacle › "
           "Danses**, la **604** (environ 18 s), coche « Zone libre de 2 à 3 m, télécommande en main », **Jouer**, "
           "confirme. **Jamais 401, 402 ni 403.**", feuille="P4")
    f.note("dans T5, la même danse, puis l'état (pendant la danse, puis après : le robot revient-il en 501 ou en "
           "801 ?) :", mot="Ou bien,", couleur=C["texte"])
    f.cmd("T5", ["g1-pilotage danse 604 --zone-libre", "g1-pilotage etat"])
    f.attendu("la durée de la danse et le mode à la fin.", mot="À noter :")
    f.case("**P5. Rendre la main.** Puis, dans T5, garde le journal du pilotage **avant** d'arrêter le "
           "conteneur. Ce conteneur a été lancé dans un terminal : la boîte noire ne le connaît pas, c'est le seul "
           "journal à garder à la main.", feuille="P5")
    f.cmd("T5", ["g1-jetson journal --lignes 100000 > ~/robot-g1/docs/releves/seance-2_pilotage.log 2>&1",
                 "g1-jetson arreter"])
    f.attendu("« conteneur g1-jetson arrêté et retiré en … s ».")
    bloc_probleme(f, [
        "`g1-jetson demarrer` : « le conteneur g1-jetson tourne déjà » : fais d'abord le premier point de cette "
        "étape (ruban Naviguer › Arrêter), puis recommence.",
        "`g1-pilotage etat` : « le nœud pilotage ne répond pas » : le `export` a-t-il été tapé dans **ce** "
        "terminal ? Le conteneur tourne-t-il (`g1-jetson etat`) ?",
        "La danse ne s'arrête pas quand il faut : la télécommande est l'arrêt d'urgence.",
    ])


def etape_v(f):
    f.titre_etape("V", "la voix du robot et la démo d'accueil", "20 min, en option")
    bloc_but(f, "entendre le robot parler, **prudemment**, puis essayer la démo d'accueil : un visiteur choisit "
                "une salle sur la borne, le robot l'y accompagne et revient seul.",
             ["seulement si tout le reste est fait et qu'il reste du temps ; **V1** (la voix, 5 min) se fait au "
              "portique, juste après P ; **V2** (la démo, 15 min) demande de relancer la navigation ;",
              "une personne à 1 ou 2 m du robot (pas l'oreille contre le haut-parleur)."])
    f.case("**V1. La voix, volume bas d'abord.** Ruban **Équipe › Avancé › Réglages de la démo**, partie « La "
           "voix du robot » : « Le robot parle par » **Haut-parleur du robot** (la voix est fabriquée sur le PC). "
           "**Mets le volume à 20 %** (il est à 70 % par défaut), puis **Enregistrer les réglages** (en bas du "
           "panneau) : la démo prendra ce volume.", feuille="V1")
    f.case("**Démarrer la voix**, puis **Essayer** (« Bonjour ! Je suis le robot d'accueil. Suivez-moi ! »).")
    f.attendu("la phrase sort du haut-parleur du robot, doucement.")
    f.case("On l'entend mal à 2 m ? Monte de **10 en 10** (30, 40, 50 %), un essai à chaque fois : le volume part "
           "tout de suite au robot. **Pas plus de 70 %.** Note le volume retenu, si le son est net (sans "
           "craquement) et le délai avant le son. Puis **Enregistrer les réglages** avec ce volume.", feuille="V1")
    f.case("La **Synthèse du robot** (sa voix intégrée), dans la même liste, puis **Essayer** : parle-t-elle "
           "français ? (sans doute non : elle est réglée sur l'anglais en attendant). Remets **Haut-parleur du "
           "robot**, puis **Enregistrer les réglages**.", feuille="V1")
    f.case("**Arrêter la voix** (la démo lance la sienne).")
    f.case("**V2. La démo d'accueil : relancer la navigation** (arrêtée avant H ou P). Robot décroché, **sur la "
           "croix, dans le sens de la flèche**, en mode marche ; ruban **Naviguer › Lancer** (confirme « Lancer sur "
           "le robot »), puis **Repérer** : « Repéré ».")
    f.case("**Réglages de la démo**, pour un premier essai : sous « Salles proposées par la borne », décoche « 1 », "
           "« 2 » et « 3 » (elles ne sont reliées à rien) et garde **« Essai à 2,5 m »** ; « Visiteurs vus par » : "
           "**La borne seule** (personne n'est salué par erreur pendant qu'on s'agite autour du robot) ; "
           "**Enregistrer les réglages**.")
    f.case("Ruban **Équipe › Démo › Lancer la démo**.")
    f.attendu("« Démo lancée : le robot attend un visiteur à l'accueil ». Sinon, le message dit quoi faire (par "
              "exemple lancer la navigation et repérer).")
    f.case("**La borne** : sur ce PC, une nouvelle fenêtre du navigateur à l'adresse `http://localhost:8000/borne` ; "
           "ou sur ton téléphone, si l'Atelier a été lancé avec `--hote 0.0.0.0` (variante de l'étape A) : ruban "
           "**Équipe › Démo › Borne** montre l'adresse et son code QR (téléphone sur le même Wi-Fi que le PC).")
    f.case("**Une visite** : un volontaire touche la borne ; le robot le salue, la borne propose les salles ; il "
           "touche **« Essai à 2,5 m »** et confirme (Oui).", feuille="V2")
    f.attendu("« Suivez-moi ! » : le robot l'accompagne à 0,2 m/s (la borne montre la distance), annonce l'arrivée, "
              "puis revient seul à l'accueil.")
    f.case("**La pause** : pendant une seconde visite, **ARRÊT** à mi-chemin, puis **Débloquer**.", feuille="V2")
    f.attendu("arrêt net ; la démo passe « en pause », la borne dit qu'elle fait une petite pause ; au « Débloquer », "
              "**rien ne bouge** (attends 15 s et regarde).")
    f.stop("si quelque chose repart seul : télécommande, amortissement, fin de la séance.")
    f.case("**Ramener à l'accueil** (panneau de la démo) : le robot revient (c'est une demande explicite), et la démo "
           "attend le visiteur suivant. Note ce qui marche et ce qui gêne : salutation, voix, borne, "
           "accompagnement, arrivée, retour, pause.", feuille="V2")
    f.case("**Arrêter la démo** (cela n'arrête pas le robot : c'est le rôle de l'ARRÊT), puis ruban **Naviguer › "
           "Arrêter** (la boîte noire garde le journal du conteneur).")
    bloc_probleme(f, [
        "La voix ne sort pas du robot : regarde la ligne d'état sous « La voix du robot » ; **Vérifier le robot** ; "
        "essaie un volume un peu plus haut (pas plus de 70 %). Note le message.",
        "« Lancer la démo » refusé : lis le message (la démo a besoin de la navigation et du robot repéré).",
        "La démo reste « en pause » : c'est voulu après un ARRÊT, un blocage, le robot assis ou le pilotage : "
        "**Débloquer** s'il le faut, puis **Ramener à l'accueil** (ou **Reprendre** si le robot est déjà à "
        "l'accueil). Rien ne repart seul.",
    ])


def etape_fin(f):
    f.titre_etape("Fin", "terminer la séance et ranger", "10 min")
    f.case("**Plus rien sur le Jetson.** Si la navigation tourne encore : ruban **Naviguer › Arrêter** (la boîte "
           "noire garde son journal). Puis, dans T5 :", feuille="Fin")
    f.cmd("T5", ["g1-jetson etat"])
    f.attendu("« aucun conteneur g1-jetson… » : c'est fini pour le conteneur. S'il dit « running » (le conteneur du "
              "pilotage, si P n'est pas allée au bout) ou « exited » (un conteneur arrêté tout seul), garde son "
              "journal, puis arrête-le :")
    f.cmd("T5", ["g1-jetson journal --lignes 100000 > ~/robot-g1/docs/releves/seance-2_conteneur.log 2>&1",
                 "g1-jetson arreter"])
    f.case("**Z1. Terminer la séance** : clique sur le badge de la séance (barre d'outils), **Terminer la séance**, "
           "puis **Terminer**.", feuille="Z1")
    f.attendu("l'enregistrement s'arrête et le rapport s'écrit en moins d'une minute ; **Rapport de séance** (barre "
              "d'outils) l'ouvre dans un onglet : en haut, **En bref** (durée, trajets, distance, arrêts d'urgence, "
              "anomalies, erreurs, batterie) et **À regarder en premier** ; puis la carte des trajets, chaque trajet "
              "et la cause de ses arrêts, les états du pont, les diagnostics et la chronologie.")
    f.note("les marches à la main de M et C et les déplacements à la télécommande (E3, H) y sont des « mouvements "
           "sans demande » : c'est attendu. Note ce qui t'étonne. Si tu oublies « Terminer la séance », Ctrl+C dans "
           "T1 ferme aussi la séance et écrit son rapport.", mot="Bon à savoir :", couleur=C["texte"])
    f.case("**Z2. Le `.zip` pour moi**, dans T5 :", feuille="Z2")
    f.cmd("T5", ["g1-seance liste",
                 "g1-seance exporter derniere --sortie ~/robot-g1/docs/releves/seance-2_boite_noire.zip"])
    f.attendu("`liste` montre la séance d'aujourd'hui en haut, « fermée », « rapport prêt » ; puis « Séance "
              "exportée : … (… Mo) », quelques centaines de Mo au plus.")
    f.note("si `liste` montre **plusieurs séances aujourd'hui** (l'Atelier a été relancé), exporte aussi chacune des "
           "autres avec son identifiant, écrit au début de sa ligne : `g1-seance exporter 2026-11-12_14h03 --sortie "
           "~/robot-g1/docs/releves/seance-2_boite_noire_2.zip` (avec l'identifiant lu).", mot="Plusieurs "
           "séances :", couleur=C["texte"])
    f.case("Robot en amortissement (sangle tendue), puis éteint. Débranche le câble. Ctrl+C dans T1 (l'Atelier).")
    f.case("Complète la feuille de résultats, et enregistre-la (voir la section 8).")


def partie_depannage(f):
    f.titre("Si ça ne marche pas", 1)
    t = f.table([7.0, 10.0])
    f.ligne(t, ("Ce que tu vois", "Que faire"), entete=True)
    for gauche, droite in (
            ("`robot.sh` : « Câble non détecté »", "Rebranche le câble des deux côtés et attends 10 s."),
            ("`robot.sh` : le robot ne répond pas", "Robot fini de démarrer ? Attends 1 min et recommence."),
            ("`robot.sh` : « Impossible d'activer la connexion robot-g1 », ou câble débranché puis rebranché",
             "`nmcli connection up robot-g1`, puis recommence."),
            ("`g1-etat` ne dit pas « Connecté » (« Aucune donnée du robot… »)",
             "Robot fini de démarrer ? Câble branché ? Relance `source ~/robot-g1/setup/robot.sh`, puis "
             "recommence."),
            ("« Vérifier le robot » ne répond pas, ou l'Atelier ne s'ouvre pas",
             "Le même diagnostic dans T5 : `g1-diagnostic` (chaque ligne et son conseil ; « Ici : g1-diagnostic "
             "--action … » donne la commande d'une action) ; la batterie : `g1-etat`."),
            ("Services de cartographie toujours arrêtés après « Démarrer les services de cartographie »",
             "Note le message. Active-les dans l'appli Unitree Explore (secours), puis **Vérifier à nouveau**."),
            ("T3 dit `arret_verrouille` alors que personne n'a posé de verrou",
             "L'ARRÊT de l'Atelier (bouton ou Échap) l'a posé : **Débloquer** (barre d'outils)."),
            ("Pas de badge de séance dans la barre d'outils",
             "**Nouvelle séance** (barre d'outils) ; en attendant, garde les journaux du conteneur à la main "
             "(secours de l'étape H)."),
            ("Badge orange « Enregistrement coupé »",
             "Disque presque plein (moins de 2 Go) ou plus de 1 Go enregistré : la séance continue (actions, "
             "rapport) sans l'enregistrement ROS 2. Note l'heure ; fais de la place après la séance."),
            ("Le pont refuse de démarrer (« … le robot ne ferait aucun pas »)",
             "Un plafond est sous 0,2 m/s : utilise les commandes de ce document telles quelles."),
            ("T3 reste `pas_en_marche`",
             "Lis le message : assis ou pas démarré → « Démarrer » à la télécommande ; course (802) → marche "
             "normale."),
            ("T3 reste `robot_muet`", "Note `ros2 topic info -v /api/sport/request`, puis passe à l'étape D."),
            ("`mesure` n'envoie rien", "Le pont n'est pas `pret` : regarde T3."),
            ("**Le robot ne s'arrête pas seul (C4)**", "**Télécommande, amortissement, fin de la séance.**"),
            ("`ssh` redemande un mot de passe", "Refais `ssh-copy-id unitree@192.168.123.164` (mot de passe 123)."),
            ("`verifier` ou « Vérifier le robot » : caméra pas vue, ou USB 480 (USB 2)",
             "Rebranche la See3CAM sur un port USB 3 (bleu) du Jetson. Si le conteneur tourne déjà, relance-le "
             "pour qu'il la reçoive : Naviguer › Arrêter (la boîte noire garde son journal), Lancer, robot sur la "
             "croix, et Repérer de nouveau."),
            ("Vue Caméra : « Pas d'image »",
             "`ros2 topic hz /camera_poitrine/image/compressed` ; `g1-jetson journal 2>&1 | grep -i cam`."),
            ("Image noire", "Équipe › Caméra › Réglages avancés : exposition automatique ; note la lumière de la "
                            "pièce."),
            ("« Repérer » échoue",
             "Note le message, `ros2 topic echo --once /slam_info` et `g1-jetson journal 2>&1 | tail -n 30`."),
            ("`carte-unitree` : « aucune carte reçue »",
             "Note-le ; relance-le, puis **Repérer** de nouveau pendant l'attente."),
            ("Le robot oscille à la fin d'un trajet", "Fais F5."),
            ("`g1-jetson demarrer` : « le conteneur g1-jetson tourne déjà »",
             "La navigation : **Naviguer › Arrêter** (la boîte noire garde son journal). Si l'Atelier ne la "
             "connaît plus (il a été relancé) : `g1-jetson journal --lignes 100000 >> "
             "~/robot-g1/docs/releves/seance-2_relances.log 2>&1`, puis `g1-jetson arreter`. Puis recommence."),
            ("La voix ne sort pas du haut-parleur du robot",
             "La ligne d'état sous « La voix du robot » (le robot écoute-t-il ?) ; **Vérifier le robot** ; un volume "
             "un peu plus haut (pas plus de 70 %). Note le message."),
            ("« Lancer la démo » refusé", "Lis le message : la démo a besoin de la navigation (**Naviguer › Lancer**) "
                                          "et du robot repéré (**Repérer**)."),
            ("La démo reste « en pause »",
             "C'est voulu après un ARRÊT, un blocage, le robot assis ou le pilotage : **Débloquer** s'il le faut, "
             "puis **Ramener à l'accueil** (ou **Reprendre** si le robot est déjà à l'accueil). Rien ne repart "
             "seul."),
            ("**Quelque chose bouge sans qu'on l'ait demandé**",
             "**Télécommande, amortissement, fin de la séance.**")):
        f.ligne(t, (gauche, droite))
    f.apres_tableau(8)
    f.titre("Plan B : la navigation sur le PC, au câble", 2)
    f.p("**Seulement si le conteneur ne marche pas** (étape D ou E). La navigation tourne alors sur le PC ; la "
        "personne du PC suit le robot de près. Les boutons « Repérer » et « Y aller » de l'Atelier ne servent qu'à "
        "la navigation que l'Atelier a lancée lui-même : avec le plan B, on passe par ces commandes.")
    f.case("Dans T5, vérifie d'abord qu'aucun conteneur ne tourne sur le Jetson (sinon, deux ponts "
           "commanderaient le robot) :")
    f.cmd("T5", ["g1-jetson etat"])
    f.attendu("« aucun conteneur g1-jetson… » (ou « le Jetson ne répond pas par ssh » : il n'a rien pu "
              "démarrer). S'il dit « running » : si c'est la navigation lancée par l'Atelier, **Naviguer › "
              "Arrêter** (la boîte noire garde son journal) ; sinon, garde son journal, puis arrête-le :")
    f.cmd("T5", ["g1-jetson journal --lignes 100000 >> ~/robot-g1/docs/releves/seance-2_relances.log 2>&1",
                 "g1-jetson arreter"])
    f.case("Dans T2 (avec `robot.sh`), la navigation à 0,2 m/s au plus :")
    f.cmd("T2", ["g1-guide navigation --lieu seance --etage rdc --vitesse-max 0.2"])
    f.case("Dans T5, le robot posé sur la croix, dans le sens de la flèche : le repérage en (0 ; 0 ; 0), puis son "
           "état.")
    f.cmd("T5", ['ros2 topic pub --once /reperage/demander std_msgs/msg/String "{data: \'{\\"id\\": \\"seance-2\\", '
                 '\\"x\\": 0, \\"y\\": 0, \\"theta\\": 0}\'}"',
                 "ros2 topic echo /reperage/etat --field data"])
    f.attendu("`\"etat\": \"repere\"`. Ctrl+C pour quitter.")
    f.case("Le trajet court (`essai_3m` est le nom interne de la salle « Essai à 2,5 m ») :")
    f.cmd("T5", ["g1-guide aller essai_3m"])
    f.attendu("le robot y va, et la commande affiche son état jusqu'à l'arrivée (Ctrl+C n'arrête que "
              "l'affichage, **pas le robot**). 15 s après l'arrivée, le robot revient seul sur la croix, comme "
              "en F2.")
    f.case("Pour arrêter le robot à tout moment (comme ARRÊT), dans T6 :")
    f.cmd("T6", ["g1-guide stop"])


def partie_rapport(f):
    f.titre("Après la séance : ce qu'il faut me rapporter", 1)
    f.p("Dis-moi **« séance 2 faite »**, avec :", apres=2, garder=True)
    f.numeros([
        "**la feuille remplie** : le fichier Word `Seance2_A_remplir.docx` enregistré dans `~/robot-g1/docs/releves/` "
        "(par exemple sous le nom `seance-2_resultats.docx`), ou `docs/releves/seance-2.md`, avec **les résultats "
        "des mesures copiés tels quels** ;",
        "**le `.zip` de la boîte noire**, `docs/releves/seance-2_boite_noire.zip` (fin de séance), et les autres "
        "s'il y a eu plusieurs séances : avec lui, je revois toute la séance, même ce que la feuille n'a pas eu le "
        "temps de noter (diagnostics, chaque action et sa réponse, états du robot, du pont et du guide, voix et "
        "démo, journaux, **journaux du conteneur gardés à chaque « Arrêter »**, rapport) ;",
        "**le journal du pilotage**, `docs/releves/seance-2_pilotage.log` (étape P), et, s'il y en a, les journaux "
        "gardés à la main en secours : `seance-2_conteneur.log` (un conteneur qui tournait encore à la fin), "
        "`seance-2_relances.log` (un conteneur arrêté hors de l'Atelier) et `seance-2_navigation.log` (sans "
        "séance ouverte) ;",
        "**les messages d'erreur**, copiés mot pour mot, et ce qui t'a étonné dans le rapport de séance.",
    ])
    f.p("Je retrouverai seul le nouveau scan (`lieux/seance/scans/`), la carte d'Unitree "
        "(`lieux/seance/cartes/rdc_unitree.*`), les réglages de la démo (`lieux/seance/demo.yaml`), les journaux de "
        "l'Atelier (`journaux/`) et ceux de ROS 2 restés sur le Jetson (`~/robot-g1/journaux/jetson/ros/log/`).",
        avant=4)
    f.p("Avec tes mesures, je réglerai :", apres=2, garder=True)
    reglages = [
        "la vitesse minimale du pont (`config/pont.yaml` et `VITESSES_MIN_PONT`) : un peu au-dessus du seuil mesuré ;",
        "la rotation finale du guide (`tolerance_orientation_rad`, `anticipation_rotation_rad`) ;",
        "la correction des distances de la caméra et sa position sur le robot ;",
        "le volume de la voix et la sortie de la démo, et ce qui a gêné pendant la démo.",
    ]
    for i, texte in enumerate(reglages):          # la liste reste entière, sur une seule page
        q = f.puces([texte])
        if i < len(reglages) - 1:
            q.paragraph_format.keep_with_next = True


def partie_lexique(f):
    f.titre("Petit lexique", 1, saut=True)
    t = f.table([4.0, 13.0], marges=(25, 25, 100, 100))
    f.ligne(t, ("Mot", "Ce que ça veut dire ici"), entete=True, taille=9.5)
    for mot, sens in (
            ("Atelier", "notre logiciel de configuration : une page web lancée par `g1-atelier`, avec un ruban "
                        "d'onglets (Scanner, Placer, Naviguer, Piloter, Équipe)."),
            ("Vérifier le robot (diagnostic)", "le bouton qui contrôle tout en quelques secondes (câble, réseau, "
                                               "services, mode, batterie, Jetson, caméra) et dit quoi faire ; "
                                               "`g1-diagnostic` dans un terminal."),
            ("Services de cartographie", "`lidar_driver` (le programme du LiDAR) et `unitree_slam` (la cartographie "
                                         "d'Unitree), à démarrer pour le scan et le repérage."),
            ("Boîte noire, séance", "l'enregistrement de toute la séance (actions, états du robot, journaux), "
                                    "ouvert avec l'espace en Réel, fermé par « Terminer la séance » ; le rapport "
                                    "de séance le résume ; `g1-seance exporter` en fait un `.zip`."),
            ("Démo d'accueil, borne", "le robot salue un visiteur, la borne (une page sur une tablette, un téléphone "
                                      "ou ce PC) propose les salles, le robot l'accompagne et revient ; un ARRÊT la "
                                      "met en pause."),
            ("Voix du robot", "les phrases fabriquées sur le PC (Piper) et jouées par le haut-parleur du robot ; "
                              "« Synthèse du robot » : sa voix intégrée."),
            ("Terminal", "la fenêtre où l'on tape des commandes (Ctrl+Alt+T ; Ctrl+Maj+T pour un nouvel onglet)."),
            ("ROS 2", "l'ensemble d'outils qui fait parler les programmes du robot entre eux."),
            ("Nœud", "un programme ROS (le pont, le guide, le pilotage…)."),
            ("Sujet (topic)", "un canal nommé, comme `/cmd_vel` ou `/pont/etat`, sur lequel un nœud publie des "
                              "messages que d'autres lisent."),
            ("Domaine ROS", "le numéro du « canal » ROS : le robot parle sur le domaine 0."),
            ("Pont", "notre nœud `g1_bridge` : il transforme une vitesse demandée (`/cmd_vel`) en ordre de marche du "
                     "robot (commande 7105), et lit son mode (7001)."),
            ("7105, 7001, 1801, 1802, 1804", "numéros des commandes du robot : 7105 « marche à cette vitesse "
                                             "pendant 0,5 s », 7001 « dis-moi ton mode », 1801 et 1802 début et fin "
                                             "du scan, 1804 repérage."),
            ("Mode (fsm)", "l'état du robot lu par 7001 : 0 pas démarré, 1 amorti, 3 assis, 500 démarrage, 501 et "
                           "801 marche, 802 course."),
            ("Consigne, seuil", "la consigne est la vitesse demandée ; le seuil, la plus petite vitesse qui fait "
                                "vraiment marcher le robot."),
            ("Latence, retard, montée", "le temps de réaction : retard jusqu'à la moitié de la vitesse, montée de "
                                        "10 % à 90 %."),
            ("m/s, rad/s, radian", "mètres par seconde, radians par seconde ; 1 radian ≈ 57,3° ; 90° = 1,5708 rad ; "
                                   "10° = 0,17 rad."),
            ("Portique, amortissement", "le cadre qui tient le robot par une sangle ; le mode où les moteurs se "
                                        "relâchent et freinent (le robot s'affaisse)."),
            ("PC1, Jetson (PC2)", "les deux ordinateurs du robot : le PC1 d'Unitree (marche, équilibre : jamais "
                                  "touché) et le Jetson, où tourne notre conteneur."),
            ("Docker, image, conteneur", "Docker range un logiciel dans une « boîte » (le conteneur), fabriquée à "
                                         "partir d'un modèle (l'image `g1-jetson:arm64`) : rien n'est installé dans "
                                         "le Jetson."),
            ("ssh", "la connexion au Jetson depuis le PC, par le câble (`unitree@192.168.123.164`)."),
            ("Repérage (relocalisation)", "le robot retrouve sa position sur la carte, à partir de la croix (1804)."),
            ("Nav2, guide", "Nav2 calcule le chemin et évite les obstacles ; le guide (notre nœud) reçoit « Y aller », "
                            "envoie Nav2 et ramène le robot à l'accueil."),
            ("Point principal (accueil)", "la croix au sol : le robot y démarre et y revient après chaque visite."),
            ("LiDAR, scan", "le capteur laser 3D de la tête (MID-360) ; le scan est la promenade qui fabrique la "
                            "carte."),
            ("See3CAM, YOLO", "la caméra USB de poitrine ; YOLO est le programme qui reconnaît les personnes dans "
                              "l'image (`g1-visiteurs`)."),
            ("Spin", "une rotation sur place demandée à Nav2."),
            ("Verrou", "`/pont/arret` : interdit tout mouvement jusqu'à ce qu'on l'enlève (« Débloquer »)."),
            ("Micrologiciel", "le logiciel interne du robot (sa version se lit dans l'appli Unitree Explore).")):
        f.ligne(t, (f"**{mot}**", sens), taille=9.5)


# =====================================================================================================
# Document 2 : Feuille de résultats à remplir
# =====================================================================================================

HAUTEUR = 1.65    # cm : hauteur minimale d'une ligne à remplir


def ok_non(f, cellule, taille=10):
    q = f._para(cellule)
    q.paragraph_format.space_after = Pt(3)
    f.case_word(q, "OK", taille)
    q2 = cellule.add_paragraph()
    q2.paragraph_format.space_after = Pt(0)
    f.case_word(q2, "NON", taille)


def tableau_points(f, lignes, hauteur=HAUTEUR):
    """Tableau N° | Point vérifié | Attendu | Constaté (à écrire) | OK / NON."""
    largeurs = [1.25, 3.85, 4.15, 5.65, 2.1]
    t = f.table(largeurs)
    f.ligne(t, ("N°", "Point vérifié", "Attendu", "Constaté (à écrire)", "OK / NON"), entete=True, taille=9.5)
    for numero, point, attendu, *reste in lignes:
        h = reste[0] if reste else hauteur
        row = f.ligne(t, (f"**{numero}**", point, attendu, None, None), hauteur=h, taille=9.5)
        ombrer_cellule(row.cells[0], C["bleu_pale"])
        f.cellule_vide(row.cells[3])
        ok_non(f, row.cells[4], 9.5)
    f.apres_tableau(6)
    return t


def tableau_mesures(f, titre, entetes, largeurs, valeurs, colonne_cases=None, hauteur=1.0, pied=None,
                    etiquette=True):
    f.p(titre, gras=True, couleur=C["bleu_fonce"], avant=4, apres=2, garder=True)
    t = f.table(largeurs)
    f.ligne(t, entetes, entete=True, taille=9)
    for v in valeurs:
        cellules = list(v) + [None] * (len(entetes) - len(v))
        row = f.ligne(t, cellules, hauteur=hauteur, taille=9.5)
        if etiquette:
            ombrer_cellule(row.cells[0], C["bleu_pale"])
        for i, c in enumerate(row.cells):
            if cellules[i] is None and (colonne_cases is None or i != colonne_cases[0]):
                f.cellule_vide(c, 9.5)
        if colonne_cases is not None:
            cell = row.cells[colonne_cases[0]]
            q = f._para(cell)
            q.paragraph_format.space_after = Pt(2)
            f.case_word(q, colonne_cases[1], 9)
            q2 = cell.add_paragraph()
            q2.paragraph_format.space_after = Pt(0)
            f.case_word(q2, colonne_cases[2], 9)
    if pied:
        for texte in pied:
            row = f.ligne(t, (texte,) + (None,) * (len(entetes) - 1), hauteur=0.9, taille=9.5, fond=C["bleu_pale"])
            row.cells[0].merge(row.cells[-1])
            row.cells[0].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    garder_lignes(t)
    f.apres_tableau(6)
    return t


def ligne_a_cocher(f, texte, taille=11):
    """Une ligne avec une case à cocher de Word devant (retrait suspendu)."""
    q = f._para()
    q.paragraph_format.left_indent = Cm(0.9)
    q.paragraph_format.first_line_indent = Cm(-0.9)
    q.paragraph_format.space_after = Pt(4)
    q.paragraph_format.tab_stops.add_tab_stop(Cm(0.9))
    f.case_word(q, "", taille)
    police_run(q.add_run("\t"), POLICE, taille)
    ecrire(q, texte, taille)
    return q


def lignes_vierges(f, n, hauteur=0.82, conteneur=None, largeur=LARGEUR):
    t = f.table([largeur], conteneur, couleur="BFBFBF", marges=(0, 0, 60, 60))
    tblPr = t._tbl.tblPr
    b = el("w:tblBorders")
    for cote in ("top", "left", "bottom", "right", "insideH", "insideV"):
        if cote in ("left", "right", "insideV", "top"):
            b.append(el("w:" + cote, val="nil"))
        else:
            b.append(el("w:" + cote, val="single", sz=4, space=0, color="BFBFBF"))
    poser(tblPr, b)
    for _ in range(n):
        row = f.ligne(t, (None,), hauteur=hauteur, exacte=True)
        f.cellule_vide(row.cells[0])
    return t


def fiche_a_remplir():
    f = Fiche("Atelier G1 · Séance robot n° 2 · Feuille de résultats", "date : ……… /……… /2026",
              "Séance robot n° 2 : feuille de résultats", "Feuille de résultats à remplir pendant la séance robot n° 2")
    # ---------------------------------------------------------------- en-tête
    f.p("ATELIER G1 · SÉANCE ROBOT N° 2", taille=10.5, couleur=C["bleu"], gras=True, avant=0, apres=2)
    f.p("Feuille de résultats à remplir", taille=26, couleur=C["bleu_fonce"], gras=True, apres=2)
    f.p("À remplir au fur et à mesure, en suivant « Ce qu'il faut faire » (`Seance2_A_faire.docx`).",
        taille=11, couleur=C["texte2"], apres=8)
    cellule = f.encadre("neutre", "Comment remplir cette feuille")
    f.puces([
        "Écris dans les **cases blanches** ce que tu as vu : **mot pour mot** quand c'est un message.",
        "Coche **☐ OK** ou **☐ NON** : dans Word, un clic sur la case la coche ; sur papier, une croix.",
        "Pour les mesures (étape M), recopie les chiffres affichés dans les tableaux ; s'il y a plus, copie la "
        "sortie de la commande dans les notes libres, à la fin.",
        "Une case trop petite : continue d'écrire, elle s'agrandit (dans Word). Rien n'est protégé.",
    ], cellule, taille=10)
    f.apres_tableau(8)
    t = f.table([5.4, 11.6])
    for libelle, contenu in (
            ("Date", None), ("Heure de début · heure de fin", None),
            ("Personnes (télécommande · PC · autres)", None),
            ("Batterie au début · à la fin", "au début :            %          à la fin :            %"),
            ("Version du robot (lue dans l'appli Unitree Explore)", None),
            ("Heures de début des étapes (pour retrouver chaque essai dans le rapport de séance)",
             "A ……  M ……  C ……  D ……  E ……  F ……  G ……  H ……  P ……  V ……  Fin ……")):
        row = f.ligne(t, (f"**{libelle}**", None), hauteur=1.05, taille=10)
        ombrer_cellule(row.cells[0], C["bleu_pale"])
        row.cells[0].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        if contenu:
            q = row.cells[1].paragraphs[0]
            police_run(q.add_run(contenu.replace(" ", "\u00a0")), POLICE, 9.5, False, True, C["gris"])
            row.cells[1].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    for libelle, cases in (("Services de cartographie arrêtés au début ? (A2)", (("oui", "non"),)),
                           ("Démarrés par « Vérifier le robot » ? (A2)", (("oui", "non, par l'appli"),)),
                           ("Lieu : même croix que le 27/10 ?", (("oui", "non"),))):
        row = f.ligne(t, (f"**{libelle}**", None), hauteur=1.05, taille=10)
        ombrer_cellule(row.cells[0], C["bleu_pale"])
        row.cells[0].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        row.cells[1].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        q = row.cells[1].paragraphs[0]
        for i, (a, b) in enumerate(cases):
            if i:
                police_run(q.add_run("\u2003\u2003\u2003"), POLICE, 10)
            f.case_word(q, a, 10)
            police_run(q.add_run("\u2003"), POLICE, 10)
            f.case_word(q, b, 10)
    f.apres_tableau(6)
    f.p("Mots utiles : **fsm** = le mode du robot (501 = marche) ; **7105** = un ordre de marche du pont ; "
        "**pret**, **pas_en_marche**, **robot_muet** = les états du pont (T3) ; **OK**, **Attention**, "
        "**Problème**, **Inconnu** = les états de « Vérifier le robot ».", taille=9.5, couleur=C["texte2"])

    # ---------------------------------------------------------------- avancement
    f.titre("Où en est le projet", 1, saut=True)
    encadre_avancement(f, avec_avis=True)
    f.apres_tableau(6)
    mots_avancement(f)

    # ---------------------------------------------------------------- étapes
    f.titre("Étape A : brancher, vérifier le robot, ouvrir la séance", 1, saut=True)
    tableau_points(f, [
        ("A1", "Branchement, `robot.sh`, l'Atelier lancé pour la journée", "« le robot répond » ; l'Atelier s'ouvre"),
        ("A2", "Vérifier le robot (accueil Robot réel ; secours : `g1-diagnostic`)", "durée (10 s environ) ; "
               "batterie ; lignes pas OK et leur texte ; services de cartographie démarrés en … s, puis tout OK "
               "(tableau A2)"),
        ("A3", "Ouvrir la séance (lieu « Séance robot »)", "badge « ● Enregistrement » (ou « Séance ») ; heure"),
    ])
    tableau_mesures(f, "Tableau A2 : les lignes de « Vérifier le robot » qui ne sont pas OK (au premier clic)",
                    ("Ligne (titre)", "État", "Phrase affichée (mot pour mot)", "Fait ensuite"),
                    [3.6, 2.1, 7.0, 4.7],
                    [(None,), (None,), (None,), (None,), (None,)], hauteur=1.0, etiquette=False,
                    pied=["**« Démarrer les services de cartographie »** : message affiché                            "
                          "      · durée :           s · puis tout OK ?"])

    f.titre("Étape M : les vrais seuils, au portique", 1)
    tableau_points(f, [
        ("M0", "Pont en consignes brutes, `/pont/etat`", "`pret` ; `mode_robot.fsm` 501 en marche"),
        ("M1", "Seuil en avant : 0,12 ; 0,15 ; 0,18 ; 0,2 m/s", "vitesse atteinte de chaque essai ; seuil (tableau M1)"),
        ("M2", "Seuil de côté : 0,12 à 0,2 m/s, et −0,15", "vitesse atteinte ; seuil (tableau M2)"),
        ("M3", "Diagonale (0,1 ; 0,1) puis (0,14 ; 0,14)", "immobile, puis marche (règle de la norme) ? (tableau M3)"),
        ("M4", "Seuil de rotation : 0,1 à 0,4 rad/s", "vitesse atteinte ; seuil ; retard et montée à 0,3 (tableau M4)"),
        ("M5", "Latence et arrêt à 0,2 m/s", "retard, montée, arrêt, dépassement (m) (tableau M5)"),
        ("M6", "Mode 7001 dans chaque posture", "amorti, assis, accroupi, debout, marche, course ; « Démarrer » : "
                                                "500 puis 501 ? (tableau M6)"),
    ], hauteur=1.45)
    ent = ("Consigne", "Vitesse atteinte", "Retard (s)", "Montée (s)", "Arrêt (s)", "Dépasse­ment",
           "Le robot…")
    larg = [2.25, 2.2, 1.7, 1.7, 1.7, 2.75, 5.1]
    tableau_mesures(f, "Tableau M1 : en avant (vitesses en m/s, dépassement en m ; T5 : `mesure marche --vx …`)",
                    ent, larg,
                    [("**0,12**",), ("**0,15**",), ("**0,18**",), ("**0,20**",)],
                    (6, "a marché (des pas)", "n'a pas marché"),
                    pied=["**Seuil en avant** (plus petite vitesse qui fait des pas) :                    m/s"])
    tableau_mesures(f, "Tableau M2 : de côté (m/s et m ; T5 : `mesure marche --vx 0 --vy …`)", ent, larg,
                    [("**0,12**",), ("**0,15**",), ("**0,18**",), ("**0,20**",),
                     ("**−0,15** (à droite)",)],
                    (6, "a marché (des pas)", "n'a pas marché"),
                    pied=["**Seuil de côté** :                    m/s     ·     vers la droite comme vers la gauche ?"])
    tableau_mesures(f, "Tableau M3 : en diagonale, la règle de la norme (m/s et m)", ent, larg,
                    [("**0,1 et 0,1** (norme 0,14)",), ("**0,14 et 0,14** (norme 0,20)",)],
                    (6, "a marché (des pas)", "n'a pas marché"),
                    pied=["**La règle de la norme se vérifie** (immobile à 0,14, marche à 0,20) ?"])
    ent_r = ent[:6] + ("Le robot…",)
    tableau_mesures(f, "Tableau M4 : rotation sur place (rad/s et rad ; T5 : `mesure rotation --wz …`)", ent_r,
                    larg,
                    [("**0,10**",), ("**0,15**",), ("**0,20**",), ("**0,30**",), ("**0,40**",)],
                    (6, "a tourné", "n'a pas tourné"),
                    pied=["**Seuil de rotation** :                    rad/s     ·     à 0,3 rad/s : retard        "
                          "        s, montée                    s"])
    tableau_mesures(f, "Tableau M5 : latence et distance d'arrêt à 0,2 m/s (m/s et m)", ent[:6] + ("Remarque",),
                    larg,
                    [("**0,20**",)], hauteur=1.3)
    tableau_mesures(f, "Tableau M6 : le mode lu dans chaque posture (T3, `mode_robot`)",
                    ("Posture (à la télécommande)", "fsm lu", "Nom affiché (`nom`)", "Remarque"),
                    [4.6, 2.2, 3.6, 7.0],
                    [("**amorti** (sangle tendue)",), ("**assis**",), ("**accroupi**",), ("**debout**",),
                     ("**marche**",), ("**course**",), ("**« Démarrer »** depuis assis : d'abord",),
                     ("… puis",)], hauteur=0.9)

    f.titre("Étape C : la sécurité du pont, réglages normaux", 1)
    tableau_points(f, [
        ("C2", "Pont normal : 0,1 m/s demandé", "7105 à (0,2 ; 0 ; 0), le robot marche"),
        ("C3", "Rotation 0,3 rad/s, pas de côté 0,2 m/s", "dans le bon sens (vers la gauche)"),
        ("C4", "Pont tué pendant la marche", "**arrêt seul en moins de 1 s**"),
        ("C5", "Télécommande pendant que le pont envoie", "**la télécommande gagne**"),
        ("C6", "Robot assis, ordre de marche", "`pas_en_marche` (« assis »), aucun pas ; retour en marche : `pret` "
                                               "sans mouvement"),
        ("C7", "`/guide/stop`, puis verrou `/pont/arret`", "arrêt net ; immobile sous verrou (`arret_verrouille`)"),
    ])

    f.titre("Étape D : notre logiciel sur le Jetson, avec la caméra", 1)
    tableau_points(f, [("D", "`g1-jetson envoyer`, `verifier`, puis Vérifier le robot", "« Jetson prêt. » ; sujets "
                                                                                       "du robot vus du conteneur ; "
                                                                                       "lignes du Jetson et de la "
                                                                                       "caméra OK")])
    tableau_mesures(f, "Détail de l'étape D", ("Ce qu'on note", "Constaté (à écrire)"), [5.0, 12.4],
                    [("**Durée d'`envoyer`**",), ("**Ligne de la caméra** (copiée : « USB 5000 Mbit/s » ?)",),
                     ("**Groupe** du périphérique (un nombre)",), ("**Sujets du robot vus du conteneur**",),
                     ("**Lignes PROBLÈME** (copiées)",),
                     ("**Vérifier le robot** : Jetson et caméra (lignes pas OK)",)], hauteur=1.2)

    f.titre("Étape E : le repérage, et la carte d'Unitree", 1)
    tableau_points(f, [
        ("E1", "Repérer (1804) depuis l'Atelier", "« Repéré » en moins de 20 s ; texte de la réponse (T4) ; durée"),
        ("E2", "`/unitree/slam_relocation/odom` et `/points`", "fréquences (messages par seconde)"),
        ("E3", "Précision, 3 mesures au mètre ruban", "moins de 10 cm (tableau E3)"),
        ("E4", "`g1-scan carte-unitree` pendant Repérer", "`rdc_unitree.pcd` écrit ; nombre de points ; ou « aucune "
                                                          "carte reçue »"),
    ])
    tableau_mesures(f, "Tableau E3 : la précision du repérage",
                    ("Mesure", "Déplacement (à la télécommande)", "Position lue (x ; y ; theta)",
                     "Mètre ruban depuis la croix (x ; y)", "Écart (cm)"),
                    [1.9, 4.0, 4.0, 4.6, 2.9],
                    [("**1**",), ("**2**",), ("**3**",)], hauteur=1.3)

    f.titre("Étape F : le premier trajet, 2,5 m à 0,2 m/s", 1)
    tableau_points(f, [
        ("F1", "Y aller « Essai à 2,5 m » à 0,2 m/s", "« Arrivé » ; durée ; écart"),
        ("F2", "Retour seul à l'accueil, rotation finale", "une seule rotation ; écart à la flèche (°)"),
        ("F3", "ARRÊT à mi-chemin, Y aller grisé, puis Débloquer", "arrêt net ; « Débloquer » ; immobile tant "
                                                                  "que bloqué, et après Débloquer (rien ne repart)"),
        ("F4", "Écart à l'arrivée sur la croix", "moins de 30 cm"),
        ("F5", "Spin de 90° (si F2 oscille)", "dépassement (°) ; réglages du guide ; une seule rotation ensuite "
                                              "(tableau F5)"),
    ])
    tableau_mesures(f, "Tableau F5 : la rotation finale (seulement si F2 oscille)",
                    ("Angle tourné (°)", "Dépasse­ment (°)", "Dépasse­ment (rad)", "Anticipation tapée (D)",
                     "Tolérance tapée (T)", "F2 refait : une seule rotation ?"),
                    [2.3, 2.75, 2.75, 2.75, 2.65, 4.2],
                    [(None,)], hauteur=1.4, colonne_cases=(5, "oui", "non"), etiquette=False)

    f.titre("Étape G : la caméra de poitrine", 1)
    tableau_points(f, [
        ("G1", "Images de la caméra sur le PC", "environ 10 par seconde ; taille d'une image (Ko)"),
        ("G2", "Vue Caméra de l'Atelier, lumière et ombre", "image nette, ni noire ni blanche"),
        ("G3", "Position de la caméra sur le robot", "x, z (m), tangage (°)"),
        ("G4", "`g1-visiteurs` : cadres sur l'image", "un cadre par personne"),
        ("G5", "Distances à 1, 2, 3 et 4 m", "distances affichées ; correction calculée (tableau G5)"),
        ("G6", "Champ de vision à 1 m", "largeur vue (m) ; champ (°) (tableau G6)"),
    ])
    tableau_mesures(f, "Tableau G3 : la position de la caméra (robot debout)",
                    ("x : avance (m)", "y : à gauche (m)", "z : hauteur (m)", "Tangage (°)", "Roulis (°)",
                     "Lacet (°)"), [2.9] * 6, [(None,)], hauteur=1.2, etiquette=False)
    tableau_mesures(f, "Tableau G5 : les distances (T6, `distance_m`)",
                    ("Repère (distance vraie)", "Distance affichée (m)", "Vraie ÷ affichée", "Remarque"),
                    [4.0, 3.6, 3.4, 6.4],
                    [("**1 m**",), ("**2 m**",), ("**3 m**",), ("**4 m**",)], hauteur=1.0,
                    pied=["**Correction = moyenne des 4 rapports** :                         → écrite dans Équipe › "
                          "Caméra › Réglages avancés ?"])
    f.p("**Tableau G6 : le champ de vision**", couleur=C["bleu_fonce"], avant=4, apres=2, garder=True)
    largeurs = [1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5]
    t = f.table([3.4] + [2.0] * len(largeurs))
    f.ligne(t, ["Largeur vue à 1 m"] + [nombre(x) + " m" for x in largeurs], entete=True, taille=9)
    f.ligne(t, ["Champ de vision"] + [f"{2 * math.degrees(math.atan(x / 2)):.0f}°" for x in largeurs], taille=9.5)
    row = f.ligne(t, ["**Mesuré**"] + [None] * len(largeurs), hauteur=1.0, taille=9.5, fond=C["bleu_pale"])
    row.cells[1].merge(row.cells[-1])
    q = row.cells[1].paragraphs[0]
    police_run(q.add_run("largeur vue :                    m     →     champ ≈                    °"), POLICE, 9.5,
               False, True, C["gris"])
    row.cells[1].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    ombrer_cellule(row.cells[1], C["blanc"])
    garder_lignes(t)
    f.apres_tableau(6)

    f.titre("Étape H : un nouveau scan, plus lent (facultatif)", 1)
    tableau_points(f, [("H", "Naviguer › Arrêter, puis nouveau scan lent (sans l'adopter)",
                        "journal du conteneur gardé par la boîte noire (`conteneur_…_avant_arret.log`) ; durée, "
                        "distance, points ; murs, tables ; ni dédoublé ni tourné")])
    tableau_mesures(f, "Détail du scan", ("Durée", "Distance", "Points", "Murs fermés ?",
                                          "Tables et chaises reconnaissables ?", "Ni dédoublée ni tournée ?"),
                    [2.3, 2.3, 2.3, 3.0, 3.8, 3.7], [(None,)], hauteur=1.6, etiquette=False)

    f.titre("Étape P : le pilotage et une danse sûre", 1)
    tableau_points(f, [
        ("P1", "Pilotage : prendre la main, Démarrer", "mode lu"),
        ("P2", "Joystick à peine incliné", "marche à 0,2 m/s"),
        ("P3", "ARRÊT, joystick toujours tenu", "arrêt ; le manche tenu ne relance pas le robot"),
        ("P4", "Danse 604 depuis 501, au portique", "durée ; mode à la fin (501 ou 801)"),
        ("P5", "Journal du pilotage gardé, `g1-jetson arreter`", "`seance-2_pilotage.log` écrit ; arrêt propre, "
                                                                 "conteneur retiré"),
    ])

    f.titre("Étape V : la voix du robot et la démo d'accueil (en option)", 1)
    tableau_points(f, [
        ("V1", "La voix par le haut-parleur du robot, à 20 % puis de 10 en 10 ; la synthèse du robot",
         "son net (sans craquement) ; délai avant le son ; volume retenu ; la synthèse du robot parle-t-elle "
         "français ? (tableau V1)"),
        ("V2", "Démo d'accueil (borne sur le PC ou le téléphone) : une visite « Essai à 2,5 m », puis ARRÊT "
               "pendant une visite", "salutation, accompagnement, arrivée, retour seul ; pause sur ARRÊT ; rien ne "
                                     "bouge au « Débloquer » ; « Ramener à l'accueil »"),
    ])
    tableau_mesures(f, "Tableau V1 : la voix, volume après volume (Essayer, à 2 m du robot)",
                    ("Volume", "On l'entend bien ?", "Son net ?", "Délai avant le son (s)", "Remarque"),
                    [2.0, 3.2, 2.6, 3.6, 6.0],
                    [("**20 %**",), ("**30 %**",), ("**40 %**",), ("**50 %**",), ("**… %**",)], hauteur=0.9,
                    pied=["**Volume retenu** :           %     ·     **Synthèse du robot** : parle-t-elle français ?"
                          "          oui / non"])

    f.titre("Fin de la séance", 1)
    tableau_points(f, [
        ("Fin", "Plus rien sur le Jetson (`g1-jetson etat`)", "« aucun conteneur g1-jetson » (sinon journal gardé, "
                                                              "puis `g1-jetson arreter`)"),
        ("Z1", "Terminer la séance, rapport de séance", "rapport en moins d'une minute ; « À regarder en premier » : "
                                                        "ce qui étonne (les mouvements à la main de M, C, E3 et H "
                                                        "sont attendus)"),
        ("Z2", "`g1-seance exporter derniere --sortie …`", "`seance-2_boite_noire.zip` dans `docs/releves/` (une "
                                                          "par séance du jour) ; taille"),
    ])

    # ---------------------------------------------------------------- erreurs, notes, rapport
    f.titre("Messages d'erreur, copiés mot pour mot", 1, saut=True)
    f.p("Un message par ligne : l'étape, l'heure, puis le message **exactement** comme il s'affiche (dans Word, tu "
        "peux le coller ; la case s'agrandit).", taille=10, couleur=C["texte2"])
    t = f.table([1.7, 1.7, 13.6])
    f.ligne(t, ("Étape", "Heure", "Message (mot pour mot)"), entete=True, taille=9.5)
    for _ in range(9):
        row = f.ligne(t, (None, None, None), hauteur=2.25)
        for c in row.cells:
            f.cellule_vide(c)
    f.titre("Notes libres", 1, saut=True)
    f.p("Sorties des mesures copiées telles quelles, ce qui a surpris, les durées…", taille=10, couleur=C["texte2"])
    lignes_vierges(f, 26)
    f.titre("Notes libres (suite)", 1, saut=True, numero=False)
    lignes_vierges(f, 15)
    f.titre("À me rapporter après la séance", 1)
    f.p("Dis-moi « **séance 2 faite** », avec :", apres=3)
    ligne_a_cocher(f, "**cette feuille remplie**, enregistrée dans `~/robot-g1/docs/releves/` (par exemple "
                      "`seance-2_resultats.docx` : Fichier › Enregistrer sous), avec les résultats des mesures "
                      "copiés tels quels ;", 11)
    ligne_a_cocher(f, "**le `.zip` de la boîte noire**, `~/robot-g1/docs/releves/seance-2_boite_noire.zip` (et les "
                      "autres s'il y a eu plusieurs séances) : toute la séance, journaux du conteneur compris ;", 11)
    ligne_a_cocher(f, "**les journaux gardés à la main**, dans `~/robot-g1/docs/releves/` (coche ceux qui "
                      "existent) :", 11).paragraph_format.keep_with_next = True
    for nom, quand in (("seance-2_pilotage.log", "étape P"),
                       ("seance-2_conteneur.log", "seulement si un conteneur tournait encore à la fin"),
                       ("seance-2_relances.log", "seulement si un conteneur a été arrêté hors de l'Atelier"),
                       ("seance-2_navigation.log", "seulement sans séance ouverte (secours de l'étape H)")):
        q = ligne_a_cocher(f, f"`{nom}` ({quand})", 10.5)
        q.paragraph_format.left_indent = Cm(1.8)
        q.paragraph_format.tab_stops.add_tab_stop(Cm(1.8))
        q.paragraph_format.space_after = Pt(2)
    ligne_a_cocher(f, "**les messages d'erreur**, copiés mot pour mot (page « Messages d'erreur ») ;", 11)
    ligne_a_cocher(f, "**ton avis sur l'avancement** (section 1 de cette feuille).", 11)
    f.p("Je retrouverai seul le nouveau scan (`lieux/seance/scans/`), la carte d'Unitree "
        "(`lieux/seance/cartes/rdc_unitree.*`), les réglages de la démo (`lieux/seance/demo.yaml`) et les journaux "
        "de l'Atelier (`journaux/`).", avant=6, taille=10, couleur=C["texte2"])
    return f


# =====================================================================================================

def main():
    schemas = fabriquer_schemas()
    a = fiche_a_faire(schemas)
    a.enregistrer(ICI / "Seance2_A_faire.docx")
    b = fiche_a_remplir()
    b.enregistrer(ICI / "Seance2_A_remplir.docx")
    print("écrit :", ICI / "Seance2_A_faire.docx")
    print("écrit :", ICI / "Seance2_A_remplir.docx")


if __name__ == "__main__":
    main()
