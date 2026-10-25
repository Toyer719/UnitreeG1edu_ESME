"""Piétons du monde inventé : leur trajectoire dans le temps, et leur silhouette pour Gazebo.

Trajectoire (contrat 4.1) : départ à trajet[0], vitesse constante. aller_retour vrai : va-et-vient
sur le trajet ; faux : boucle, avec retour direct du dernier point au premier. Elle se répète sans
fin. Chaque segment est découpé en pas de 0,5 m au plus : Gazebo lisse la trajectoire entre les
points (spline), et des points serrés la gardent droite, à vitesse constante.
Le même calcul sert au SDF (<waypoint>) et à position_pieton(), qui donne où se trouve un piéton
à un instant de la simulation (pour l'interface, sans interroger Gazebo).

Silhouette : un prisme elliptique de 1,7 m de haut, 0,5 m de large et 0,36 m d'épaisseur. Gazebo
Fortress n'accepte un <actor> qu'avec un maillage animé (« skin » avec squelette). Pour ne rien
télécharger, on l'écrit nous-mêmes en COLLADA : un seul os, et une animation immobile. Le fichier
pieton.dae est écrit à côté du .sdf, qui le désigne par un chemin relatif.
"""
import math

PAS_MAX = 0.5            # m entre deux points de passage
NOM_MAILLAGE = "pieton.dae"
NOM_ANIMATION = "marche"
HAUTEUR = 1.7            # m
DEMI_LARGEUR = 0.25      # m, de l'épaule gauche à l'épaule droite / 2 (axe y du piéton)
DEMI_EPAISSEUR = 0.18    # m, du dos au ventre / 2 (axe x : sens de la marche)


def _parcours(pieton):
    """Points du parcours d'un tour complet : aller et retour, ou boucle refermée."""
    points = [tuple(p) for p in pieton.trajet]
    if pieton.aller_retour:
        return points + points[-2::-1]
    return points + points[:1]


def points_de_passage(pieton, pas_max=PAS_MAX):
    """Liste de (t, x, y, cap) d'un tour complet, de t = 0 (trajet[0]) au retour à trajet[0].
    cap : direction de la marche, en radians. Les points confondus sont sautés.
    Un piéton qui ne se déplace pas (tous ses points confondus) reste sur place."""
    parcours = _parcours(pieton)
    points, t, cap = [], 0.0, 0.0
    for (x1, y1), (x2, y2) in zip(parcours, parcours[1:]):
        longueur = math.hypot(x2 - x1, y2 - y1)
        if longueur < 1e-9:
            continue
        cap = math.atan2(y2 - y1, x2 - x1)
        n = max(1, math.ceil(longueur / pas_max - 1e-9))
        for k in range(n):
            points.append((t + k * longueur / n / pieton.vitesse,
                           x1 + (x2 - x1) * k / n, y1 + (y2 - y1) * k / n, cap))
        t += longueur / pieton.vitesse
    x0, y0 = parcours[0]
    if not points:
        return [(0.0, x0, y0, 0.0), (1.0, x0, y0, 0.0)]
    points.append((t, x0, y0, cap))
    return points


def duree_tour(pieton):
    """Durée d'un tour complet, en secondes."""
    return points_de_passage(pieton)[-1][0]


def position_pieton(pieton, t):
    """(x, y, cap) du piéton au temps t de la simulation (s), en ligne droite entre les points."""
    points = points_de_passage(pieton)
    t = t % points[-1][0]
    for (t1, x1, y1, cap), (t2, x2, y2, _) in zip(points, points[1:]):
        if t <= t2:
            u = 0.0 if t2 == t1 else (t - t1) / (t2 - t1)
            return (x1 + (x2 - x1) * u, y1 + (y2 - y1) * u, cap)
    return points[-1][1:]


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
