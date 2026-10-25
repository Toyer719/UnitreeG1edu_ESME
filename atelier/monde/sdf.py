"""Monde Gazebo Fortress (SDF 1.9) d'un étage, à partir de son monde inventé (monde.yaml).

Contenu du monde :
  - plugins de monde Physics, SceneBroadcaster, UserCommands et Sensors (rendu ogre2,
    indispensable au gpu_lidar du robot proxy) ;
  - un soleil et le sol (modèle « sol ») ;
  - un modèle statique par mur : boîte de la longueur exacte du segment, tournée selon le mur ;
  - un modèle statique par objet : boîte, cylindre, ou meuble simple (chaise, table, banc,
    poubelle) écrit ici en SDF, sans rien télécharger ;
  - un <actor> par piéton, qui suit son trajet (voir pietons.py).
Les modèles portent l'id du mur, de l'objet ou du piéton. Le robot n'y est pas : g1_sim le fait
apparaître à depart_robot. Le monde Gazebo porte le nom de l'étage (ex. « rdc »).
"""
import xml.etree.ElementTree as ET

from atelier.lieu import MODELES_MOBILIER, charger_monde, chemin_sdf, ecrire_atomique

from .pietons import NOM_ANIMATION, NOM_MAILLAGE, points_de_passage, texte_maillage

VERSION_SDF = "1.9"

# Couleurs (rouge, vert, bleu), de 0 à 1
COULEURS = {
    "sol": (0.75, 0.75, 0.72),
    "mur": (0.92, 0.90, 0.84),
    "boite": (0.55, 0.42, 0.30),
    "cylindre": (0.65, 0.65, 0.68),
    "bois": (0.62, 0.45, 0.28),
    "metal": (0.30, 0.30, 0.32),
    "assise": (0.20, 0.35, 0.60),
    "poubelle": (0.15, 0.40, 0.20),
}

PLUGINS_MONDE = [
    ("ignition-gazebo-physics-system", "ignition::gazebo::systems::Physics", {}),
    ("ignition-gazebo-scene-broadcaster-system", "ignition::gazebo::systems::SceneBroadcaster", {}),
    ("ignition-gazebo-user-commands-system", "ignition::gazebo::systems::UserCommands", {}),
    ("ignition-gazebo-sensors-system", "ignition::gazebo::systems::Sensors", {"render_engine": "ogre2"}),
]


# ---------------------------------------------------------------- petits outils XML

def _nombre(v):
    """Nombre court et exact au micromètre : 2.5, 0.15, -1.5708 (jamais « -0 »)."""
    texte = f"{float(v):.6f}".rstrip("0").rstrip(".")
    return "0" if texte in ("-0", "") else texte


def _nombres(*valeurs):
    return " ".join(_nombre(v) for v in valeurs)


def _sous(parent, balise, texte=None, **attributs):
    element = ET.SubElement(parent, balise, attributs)
    if texte is not None:
        element.text = str(texte)
    return element


def _pose(parent, x=0.0, y=0.0, z=0.0, cap=0.0):
    """<pose> au sol : position et rotation autour de z (roulis et tangage nuls)."""
    return _sous(parent, "pose", _nombres(x, y, z, 0, 0, cap))


def _materiau(visuel, couleur):
    r, v, b = COULEURS[couleur]
    m = _sous(visuel, "material")
    _sous(m, "ambient", _nombres(r, v, b, 1))
    _sous(m, "diffuse", _nombres(r, v, b, 1))
    _sous(m, "specular", _nombres(0.1, 0.1, 0.1, 1))


def _forme(lien, nom, geometrie, couleur, pose=None):
    """Ajoute au lien une collision et un visuel de même forme. geometrie : ("box", (lx, ly, lz))
    ou ("cylinder", (rayon, longueur)). pose : (x, y, z) dans le repère du modèle."""
    for balise in ("collision", "visual"):
        element = _sous(lien, balise, name=f"{nom}_{'collision' if balise == 'collision' else 'visuel'}")
        if pose is not None:
            _pose(element, *pose)
        g = _sous(_sous(element, "geometry"), geometrie[0])
        if geometrie[0] == "box":
            _sous(g, "size", _nombres(*geometrie[1]))
        else:
            _sous(g, "radius", _nombre(geometrie[1][0]))
            _sous(g, "length", _nombre(geometrie[1][1]))
        if balise == "visual":
            _materiau(element, couleur)


def _modele(monde_sdf, nom, x, y, z=0.0, cap=0.0):
    """Modèle statique avec un lien unique « lien ». Renvoie le lien."""
    modele = _sous(monde_sdf, "model", name=nom)
    _sous(modele, "static", "true")
    _pose(modele, x, y, z, cap)
    return _sous(modele, "link", name="lien")


# ---------------------------------------------------------------- meubles

def _chaise(lien):
    d = MODELES_MOBILIER["chaise"]
    lx, ly, h = d["longueur"], d["largeur"], d["hauteur"]
    assise, pied, dossier = 0.45, 0.04, 0.04
    _forme(lien, "assise", ("box", (lx, ly, 0.05)), "assise", (0, 0, assise - 0.025))
    for i, (sx, sy) in enumerate(((1, 1), (1, -1), (-1, 1), (-1, -1))):
        _forme(lien, f"pied_{i + 1}", ("box", (pied, pied, assise - 0.05)), "metal",
               (sx * (lx - pied) / 2, sy * (ly - pied) / 2, (assise - 0.05) / 2))
    # Dossier à l'arrière : la personne assise regarde vers le cap de la chaise
    _forme(lien, "dossier", ("box", (dossier, ly, h - assise)), "assise",
           (-(lx - dossier) / 2, 0, (h + assise) / 2))


def _table(lien):
    d = MODELES_MOBILIER["table"]
    lx, ly, h = d["longueur"], d["largeur"], d["hauteur"]
    plateau, pied, retrait = 0.04, 0.05, 0.05
    _forme(lien, "plateau", ("box", (lx, ly, plateau)), "bois", (0, 0, h - plateau / 2))
    for i, (sx, sy) in enumerate(((1, 1), (1, -1), (-1, 1), (-1, -1))):
        _forme(lien, f"pied_{i + 1}", ("box", (pied, pied, h - plateau)), "metal",
               (sx * (lx / 2 - retrait), sy * (ly / 2 - retrait), (h - plateau) / 2))


def _banc(lien):
    d = MODELES_MOBILIER["banc"]
    lx, ly, h = d["longueur"], d["largeur"], d["hauteur"]
    assise, montant = 0.05, 0.06
    _forme(lien, "assise", ("box", (lx, ly, assise)), "bois", (0, 0, h - assise / 2))
    for i, sx in enumerate((1, -1)):
        _forme(lien, f"montant_{i + 1}", ("box", (montant, ly, h - assise)), "metal",
               (sx * (lx / 2 - 0.15), 0, (h - assise) / 2))


def _poubelle(lien):
    d = MODELES_MOBILIER["poubelle"]
    _forme(lien, "corps", ("cylinder", (d["rayon"], d["hauteur"])), "poubelle", (0, 0, d["hauteur"] / 2))


MEUBLES = {"chaise": _chaise, "table": _table, "banc": _banc, "poubelle": _poubelle}


# ---------------------------------------------------------------- éléments du monde

def _ajouter_sol(monde_sdf, emprise):
    cx, cy = (emprise.xmin + emprise.xmax) / 2, (emprise.ymin + emprise.ymax) / 2
    taille = (emprise.taille_x + 20, emprise.taille_y + 20)
    lien = _modele(monde_sdf, "sol", cx, cy)
    for balise, nom in (("collision", "sol_collision"), ("visual", "sol_visuel")):
        element = _sous(lien, balise, name=nom)
        plan = _sous(_sous(element, "geometry"), "plane")
        _sous(plan, "normal", "0 0 1")
        _sous(plan, "size", _nombres(*taille))
        if balise == "visual":
            _materiau(element, "sol")


def _ajouter_mur(monde_sdf, mur):
    cx, cy = mur.centre
    lien = _modele(monde_sdf, mur.id, cx, cy, mur.hauteur / 2, mur.cap)
    _forme(lien, "mur", ("box", (mur.longueur, mur.epaisseur, mur.hauteur)), "mur")


def _ajouter_objet(monde_sdf, objet):
    cx, cy = objet.centre
    if objet.type == "boite":
        lx, ly, h = objet.taille
        lien = _modele(monde_sdf, objet.id, cx, cy, h / 2, objet.cap)
        _forme(lien, "boite", ("box", (lx, ly, h)), "boite")
    elif objet.type == "cylindre":
        lien = _modele(monde_sdf, objet.id, cx, cy, objet.hauteur / 2)
        _forme(lien, "cylindre", ("cylinder", (objet.rayon, objet.hauteur)), "cylindre")
    else:
        MEUBLES[objet.modele](_modele(monde_sdf, objet.id, cx, cy, 0.0, objet.cap))


def _ajouter_pieton(monde_sdf, pieton):
    acteur = _sous(monde_sdf, "actor", name=pieton.id)
    peau = _sous(acteur, "skin")
    _sous(peau, "filename", NOM_MAILLAGE)
    _sous(peau, "scale", "1")
    animation = _sous(acteur, "animation", name=NOM_ANIMATION)
    _sous(animation, "filename", NOM_MAILLAGE)
    _sous(animation, "interpolate_x", "false")
    script = _sous(acteur, "script")
    _sous(script, "loop", "true")
    _sous(script, "delay_start", "0")
    _sous(script, "auto_start", "true")
    trajectoire = _sous(script, "trajectory", id="0", type=NOM_ANIMATION, tension="0")
    for t, x, y, cap in points_de_passage(pieton):
        point = _sous(trajectoire, "waypoint")
        _sous(point, "time", _nombre(t))
        _pose(point, x, y, 0.0, cap)


def texte_sdf(monde, nom="monde", source=None):
    """Monde → texte du fichier .sdf. nom : nom du monde Gazebo (l'id de l'étage).
    source : nom du fichier monde.yaml, cité dans le commentaire d'en-tête."""
    racine = ET.Element("sdf", version=VERSION_SDF)
    monde_sdf = _sous(racine, "world", name=nom)

    physique = _sous(monde_sdf, "physics", name="1ms", type="ignored")
    _sous(physique, "max_step_size", "0.001")
    _sous(physique, "real_time_factor", "1.0")
    for fichier, nom_plugin, reglages in PLUGINS_MONDE:
        plugin = _sous(monde_sdf, "plugin", filename=fichier, name=nom_plugin)
        for cle, valeur in reglages.items():
            _sous(plugin, cle, valeur)

    scene = _sous(monde_sdf, "scene")
    _sous(scene, "ambient", "0.5 0.5 0.5 1")
    _sous(scene, "background", "0.75 0.82 0.9 1")

    soleil = _sous(monde_sdf, "light", type="directional", name="soleil")
    _sous(soleil, "cast_shadows", "false")
    _pose(soleil, 0, 0, 10)
    _sous(soleil, "diffuse", "0.8 0.8 0.8 1")
    _sous(soleil, "specular", "0.2 0.2 0.2 1")
    _sous(soleil, "direction", "-0.5 0.1 -0.9")

    _ajouter_sol(monde_sdf, monde.emprise)
    for mur in monde.murs:
        _ajouter_mur(monde_sdf, mur)
    for objet in monde.objets:
        _ajouter_objet(monde_sdf, objet)
    for pieton in monde.pietons:
        _ajouter_pieton(monde_sdf, pieton)

    ET.indent(racine, space="  ")
    origine = f" depuis {source}" if source else ""
    entete = (f'<?xml version="1.0" ?>\n'
              f"<!-- Monde Gazebo de l'Atelier G1, généré par atelier.monde{origine}.\n"
              f"     Ne pas modifier à la main : refaire avec g1-monde generer. -->\n")
    return entete + ET.tostring(racine, encoding="unicode") + "\n"


def ecrire_sdf(lieu, etage, monde=None):
    """Écrit mondes/<etage>.sdf (et mondes/pieton.dae s'il y a des piétons).
    monde : Monde déjà chargé (sinon, lu dans mondes/<etage>.monde.yaml). Renvoie le chemin du .sdf."""
    if monde is None:
        monde = charger_monde(lieu, etage)
    chemin = chemin_sdf(lieu, etage)
    if monde.pietons:
        ecrire_atomique(chemin.parent / NOM_MAILLAGE, texte_maillage())
    ecrire_atomique(chemin, texte_sdf(monde, nom=etage, source=f"{etage}.monde.yaml"))
    return chemin
