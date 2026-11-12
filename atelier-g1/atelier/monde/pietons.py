"""Piétons du monde inventé : leur horaire dans le temps, et leur silhouette pour Gazebo.

Trajectoire (contrat 4.1) : départ à trajet[0], vitesse constante. aller_retour vrai : va-et-vient
sur le trajet ; faux : boucle, avec retour direct du dernier point au premier. Elle se répète sans
fin. Chaque segment est découpé en pas de 0,5 m au plus : Gazebo lisse la trajectoire entre les
points (spline), et des points serrés la gardent droite, à vitesse constante.

Vague 4 (section 11.3 du plan), champs facultatifs du piéton (défauts : atelier.lieu.passants) :
  - pauses : [{point, duree_s}] : arrêt à chaque passage au point de ce rang (0 = le premier ; au
    départ de chaque tour pour le point 0). Un piéton immobile : une pause de 3600 s au point 0 ;
  - depart_s : il attend à trajet[0] jusqu'à ce temps, puis part ;
  - repeter : faux, un seul parcours (l'aller ; l'aller et le retour avec aller_retour), puis il
    reste au dernier point atteint (état « fini »).
Un piéton sans ces champs garde exactement le trajet de la vague 1.

L'horaire (horaire(), etat_prevu()) sert à tout le monde : aux points de passage du SDF des
<actor>, à position_pieton() (où se trouve un piéton à un instant, pour l'interface et le banc,
sans interroger Gazebo) et au nœud pietons de g1_sim, qui conduit les piétons-corps sur cet horaire
(atelier.monde.foule). Le temps est celui de la scène : le temps simulé, remis à zéro quand le nœud
pietons réinitialise la scène.

Silhouette : un prisme elliptique de 1,7 m de haut, 0,5 m de large et 0,36 m d'épaisseur. Gazebo
Fortress n'accepte un <actor> qu'avec un maillage animé (« skin » avec squelette). Pour ne rien
télécharger, on l'écrit nous-mêmes en COLLADA : un seul os, et une animation immobile. Le fichier
pieton.dae est écrit à côté du .sdf, qui le désigne par un chemin relatif.
"""
import math
from dataclasses import dataclass, field
from typing import List, Tuple

PAS_MAX = 0.5            # m entre deux points de passage
NOM_MAILLAGE = "pieton.dae"
NOM_ANIMATION = "marche"
HAUTEUR = 1.7            # m
DEMI_LARGEUR = 0.25      # m, de l'épaule gauche à l'épaule droite / 2 (axe y du piéton)
DEMI_EPAISSEUR = 0.18    # m, du dos au ventre / 2 (axe x : sens de la marche)


def _champ(pieton, nom, defaut):
    """Champ facultatif d'un piéton (Pieton ou dict), avec sa valeur par défaut."""
    valeur = pieton.get(nom) if isinstance(pieton, dict) else getattr(pieton, nom, None)
    return defaut if valeur is None else valeur


# ---------------------------------------------------------------- horaire

@dataclass
class Morceau:
    """Un morceau de l'horaire : marche en ligne droite de a à b, ou pause en a (b = a)."""
    debut: float
    fin: float
    a: Tuple[float, float]
    b: Tuple[float, float]
    etat: str               # « marche » ou « pause »
    cap: float              # direction de la marche (pause : celle du morceau voisin)


@dataclass
class Horaire:
    """Horaire d'un piéton : les morceaux d'un tour (de 0 à duree), le départ et la répétition."""
    morceaux: List[Morceau] = field(default_factory=list)
    duree: float = 0.0
    depart: float = 0.0
    repeter: bool = True
    debut: Tuple[float, float] = (0.0, 0.0)
    fin: Tuple[float, float] = (0.0, 0.0)
    cap_depart: float = 0.0
    cap_fin: float = 0.0


def _etapes(pieton, repeter):
    """Rangs des points dans l'ordre de passage d'un tour. Le dernier est l'arrivée du tour : le
    départ du tour suivant (piéton qui se répète), ou le point où il reste (repeter faux)."""
    n = len(pieton.trajet)
    if pieton.aller_retour:
        return list(range(n)) + list(range(n - 2, -1, -1))
    return list(range(n)) + ([0] if repeter else [])


def horaire(pieton):
    """Horaire d'un tour du piéton (pauses comprises), départ et répétition (voir l'en-tête)."""
    repeter = bool(_champ(pieton, "repeter", True))
    pauses = {int(p["point"]): float(p["duree_s"]) for p in (_champ(pieton, "pauses", []) or [])}
    points = [(float(x), float(y)) for x, y in pieton.trajet]
    rangs = _etapes(pieton, repeter)
    morceaux, t = [], 0.0
    for rang, suivant in zip(rangs, rangs[1:]):
        a, b = points[rang], points[suivant]
        if pauses.get(rang, 0.0) > 0:
            morceaux.append(Morceau(t, t + pauses[rang], a, a, "pause", math.nan))
            t += pauses[rang]
        longueur = math.hypot(b[0] - a[0], b[1] - a[1])
        if longueur < 1e-9:
            continue
        morceaux.append(Morceau(t, t + longueur / pieton.vitesse, a, b, "marche",
                                math.atan2(b[1] - a[1], b[0] - a[0])))
        t += longueur / pieton.vitesse
    # cap des pauses : celui de la marche d'avant, sinon celui de la marche d'après
    caps = [m.cap for m in morceaux if m.etat == "marche"]
    precedent = caps[0] if caps else 0.0
    for m in morceaux:
        if m.etat == "marche":
            precedent = m.cap
        else:
            m.cap = precedent
    return Horaire(morceaux=morceaux, duree=t, depart=float(_champ(pieton, "depart_s", 0.0)), repeter=repeter,
                   debut=points[rangs[0]], fin=points[rangs[-1]],
                   cap_depart=caps[0] if caps else 0.0, cap_fin=caps[-1] if caps else 0.0)


def etat_horaire(h, t):
    """(x, y, cap, vx, vy, etat) prévus par l'horaire h au temps t (s) de la scène.
    etat : « marche », « pause » (pause prévue, ou attente du départ) ou « fini » (repeter faux)."""
    x0, y0 = h.debut
    if t < h.depart:
        return (x0, y0, h.cap_depart, 0.0, 0.0, "pause")
    tau = t - h.depart
    if h.duree <= 0:            # tous les points confondus, sans pause : il reste sur place
        return (x0, y0, h.cap_depart, 0.0, 0.0, "pause")
    if h.repeter:
        tau = tau % h.duree
    elif tau >= h.duree:
        return (h.fin[0], h.fin[1], h.cap_fin, 0.0, 0.0, "fini")
    for m in h.morceaux:
        if tau <= m.fin:
            if m.etat == "pause":
                return (m.a[0], m.a[1], m.cap, 0.0, 0.0, "pause")
            u = 0.0 if m.fin == m.debut else (tau - m.debut) / (m.fin - m.debut)
            dx, dy = m.b[0] - m.a[0], m.b[1] - m.a[1]
            duree = m.fin - m.debut
            return (m.a[0] + dx * u, m.a[1] + dy * u, m.cap, dx / duree, dy / duree, "marche")
    dernier = h.morceaux[-1]
    return (dernier.b[0], dernier.b[1], dernier.cap, 0.0, 0.0, "marche")


def etat_prevu(pieton, t):
    """(x, y, cap, vx, vy, etat) du piéton au temps t de la scène, d'après son horaire."""
    return etat_horaire(horaire(pieton), t)


def position_pieton(pieton, t):
    """(x, y, cap) du piéton au temps t de la simulation (s), en ligne droite entre les points."""
    x, y, cap, _, _, _ = etat_prevu(pieton, t)
    return (x, y, cap)


def points_de_passage(pieton, pas_max=PAS_MAX):
    """Liste de (t, x, y, cap) d'un tour complet, de t = 0 (trajet[0]) au retour à trajet[0]
    (ou au dernier point atteint, avec repeter faux). cap : direction de la marche, en radians.
    Une pause est un point répété deux fois. Les points confondus sont sautés. Un piéton qui ne
    se déplace pas (tous ses points confondus) reste sur place. Le départ (depart_s) n'y est pas :
    c'est le delay_start du <script> du SDF."""
    h = horaire(pieton)
    points = []
    for m in h.morceaux:
        if m.etat == "pause":
            points.append((m.debut, m.a[0], m.a[1], m.cap))
            continue
        longueur = math.hypot(m.b[0] - m.a[0], m.b[1] - m.a[1])
        n = max(1, math.ceil(longueur / pas_max - 1e-9))
        for k in range(n):
            points.append((m.debut + k * longueur / n / pieton.vitesse,
                           m.a[0] + (m.b[0] - m.a[0]) * k / n, m.a[1] + (m.b[1] - m.a[1]) * k / n, m.cap))
    x0, y0 = pieton.trajet[0]
    if not h.morceaux:
        return [(0.0, x0, y0, 0.0), (1.0, x0, y0, 0.0)]
    if h.duree <= 0 or len(points) < 1:
        return [(0.0, x0, y0, 0.0), (1.0, x0, y0, 0.0)]
    points.append((h.duree, h.fin[0], h.fin[1], h.cap_fin))
    return points


def duree_tour(pieton):
    """Durée d'un tour complet, en secondes (pauses comprises, sans le départ)."""
    return points_de_passage(pieton)[-1][0]


# ---------------------------------------------------------------- maillage COLLADA

def texte_maillage(cotes=16):
    """Maillage COLLADA du piéton : prisme elliptique posé au sol (z de 0 à HAUTEUR), regardant
    vers +x, lié à un os unique « racine » qui porte une animation immobile."""
    angles = [2 * math.pi * k / cotes for k in range(cotes)]
    positions = ([(DEMI_EPAISSEUR * math.cos(a), DEMI_LARGEUR * math.sin(a), 0.0) for a in angles]
                 + [(DEMI_EPAISSEUR * math.cos(a), DEMI_LARGEUR * math.sin(a), HAUTEUR) for a in angles]
                 + [(0.0, 0.0, 0.0), (0.0, 0.0, HAUTEUR)])
    normales = [(0.0, 0.0, -1.0), (0.0, 0.0, 1.0)]
    for k in range(cotes):
        a = 2 * math.pi * (k + 0.5) / cotes
        nx, ny = math.cos(a) / DEMI_EPAISSEUR, math.sin(a) / DEMI_LARGEUR
        norme = math.hypot(nx, ny)
        normales.append((nx / norme, ny / norme, 0.0))
    bas, haut = 2 * cotes, 2 * cotes + 1
    triangles = []          # (sommet, normale) dans le sens inverse des aiguilles d'une montre
    for k in range(cotes):
        k2, cote = (k + 1) % cotes, 2 + k
        triangles += [(k, cote), (k2, cote), (cotes + k2, cote),
                      (k, cote), (cotes + k2, cote), (cotes + k, cote),
                      (bas, 0), (k2, 0), (k, 0),
                      (haut, 1), (cotes + k, 1), (cotes + k2, 1)]
    nb = len(positions)
    pos = " ".join(f"{c:.4f}" for p in positions for c in p)
    nor = " ".join(f"{c:.4f}" for n in normales for c in n)
    tri = " ".join(f"{s} {n}" for s, n in triangles)
    identite = "1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"

    def source(id_, tableau, compte, pas, params, type_param="float", balise="float_array"):
        champs = "".join(f'<param name="{p}" type="{type_param}"/>' for p in params)
        return (f'<source id="{id_}"><{balise} id="{id_}-a" count="{compte * pas}">{tableau}</{balise}>'
                f'<technique_common><accessor source="#{id_}-a" count="{compte}" stride="{pas}">'
                f'{champs}</accessor></technique_common></source>')

    return f"""<?xml version="1.0" encoding="utf-8"?>
<!-- Silhouette de piéton de l'Atelier G1, écrite par atelier.monde.pietons : ne pas modifier. -->
<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">
  <asset><unit name="meter" meter="1"/><up_axis>Z_UP</up_axis></asset>
  <library_effects>
    <effect id="effet"><profile_COMMON><technique sid="common"><lambert>
      <diffuse><color>0.85 0.35 0.2 1</color></diffuse>
    </lambert></technique></profile_COMMON></effect>
  </library_effects>
  <library_materials>
    <material id="matiere" name="matiere"><instance_effect url="#effet"/></material>
  </library_materials>
  <library_geometries>
    <geometry id="corps" name="corps"><mesh>
      {source("corps-pos", pos, nb, 3, "XYZ")}
      {source("corps-nor", nor, len(normales), 3, "XYZ")}
      <vertices id="corps-som"><input semantic="POSITION" source="#corps-pos"/></vertices>
      <triangles material="matiere" count="{len(triangles) // 3}">
        <input semantic="VERTEX" source="#corps-som" offset="0"/>
        <input semantic="NORMAL" source="#corps-nor" offset="1"/>
        <p>{tri}</p>
      </triangles>
    </mesh></geometry>
  </library_geometries>
  <library_controllers>
    <controller id="peau"><skin source="#corps">
      <bind_shape_matrix>{identite}</bind_shape_matrix>
      {source("peau-os", "racine", 1, 1, ["JOINT"], "name", "Name_array")}
      {source("peau-inv", identite, 1, 16, ["TRANSFORM"], "float4x4")}
      {source("peau-poids", "1", 1, 1, ["WEIGHT"])}
      <joints><input semantic="JOINT" source="#peau-os"/><input semantic="INV_BIND_MATRIX" source="#peau-inv"/></joints>
      <vertex_weights count="{nb}">
        <input semantic="JOINT" source="#peau-os" offset="0"/><input semantic="WEIGHT" source="#peau-poids" offset="1"/>
        <vcount>{" ".join(["1"] * nb)}</vcount>
        <v>{" ".join(["0 0"] * nb)}</v>
      </vertex_weights>
    </skin></controller>
  </library_controllers>
  <library_animations>
    <animation id="{NOM_ANIMATION}">
      {source("anim-t", "0 1", 2, 1, ["TIME"])}
      {source("anim-m", identite + " " + identite, 2, 16, ["TRANSFORM"], "float4x4")}
      {source("anim-i", "LINEAR LINEAR", 2, 1, ["INTERPOLATION"], "name", "Name_array")}
      <sampler id="anim-s">
        <input semantic="INPUT" source="#anim-t"/><input semantic="OUTPUT" source="#anim-m"/>
        <input semantic="INTERPOLATION" source="#anim-i"/>
      </sampler>
      <channel source="#anim-s" target="racine/transform"/>
    </animation>
  </library_animations>
  <library_visual_scenes>
    <visual_scene id="scene">
      <node id="racine" name="racine" sid="racine" type="JOINT"><matrix sid="transform">{identite}</matrix></node>
      <node id="pieton" name="pieton" type="NODE">
        <instance_controller url="#peau"><skeleton>#racine</skeleton>
          <bind_material><technique_common>
            <instance_material symbol="matiere" target="#matiere"/>
          </technique_common></bind_material>
        </instance_controller>
      </node>
    </visual_scene>
  </library_visual_scenes>
  <scene><instance_visual_scene url="#scene"/></scene>
</COLLADA>
"""
