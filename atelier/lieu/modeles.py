"""Modèles d'un paquet de lieu : une dataclass par objet des fichiers YAML (contrat 4.1 du plan).

Chaque classe a :
  vers_dict()             ce qu'on écrit dans le fichier YAML (dictionnaire, ou liste pour un couloir) ;
  depuis_dict(donnees)    l'objet, à partir de ce que le fichier contient.
depuis_dict suppose des données déjà validées par le schéma (atelier.lieu.fichiers s'en charge) ;
un champ facultatif absent prend sa valeur par défaut.

Unités : mètres et radians, repère map (z vers le haut, theta depuis l'axe x, sens inverse des
aiguilles d'une montre). Un point est un tuple (x, y).
"""
import math
import numbers
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .geometrie import rectangle

VERSION = 1

# Encombrement des modèles de mobilier (contrat 4.1), en mètres, avant rotation par le cap.
# La poubelle est un cylindre.
MODELES_MOBILIER = {
    "chaise": {"longueur": 0.45, "largeur": 0.45, "hauteur": 0.9},
    "table": {"longueur": 1.2, "largeur": 0.8, "hauteur": 0.75},
    "banc": {"longueur": 1.5, "largeur": 0.4, "hauteur": 0.45},
    "poubelle": {"rayon": 0.25, "hauteur": 0.8},
}
TYPES_OBJET = ("boite", "cylindre", "modele")
SOURCES_CARTE = ("monde", "scan")

# Catégories d'objets (section 9.4 du plan) : les mêmes dans monde.yaml (champ facultatif
# categorie) et dans scans/<session>/reconnaissance.yaml. Une personne n'est jamais dessinée sur
# la carte 2D. Sans categorie, elle se déduit de la forme (Objet.categorie_effective).
CATEGORIES_OBJETS = ("table", "chaise", "banc", "poteau", "meuble", "poubelle", "personne", "inconnu")
CATEGORIES_HORS_CARTE = ("personne",)
SOURCES_ELEMENT = ("dessin", "scan")      # champ facultatif source d'un mur ou d'un objet
CATEGORIE_PAR_TYPE = {"boite": "meuble", "cylindre": "poteau"}   # type modele : le nom du modèle

Point = Tuple[float, float]


# ---------------------------------------------------------------- petits outils

def _nombre(v):
    """Nombre Python simple (les nombres numpy ne s'écrivent pas en YAML)."""
    if v is None or isinstance(v, bool):
        return v
    if isinstance(v, numbers.Integral):
        return int(v)
    if isinstance(v, numbers.Real):
        return float(v)
    return v


def _point(p) -> Point:
    return (_nombre(p[0]), _nombre(p[1]))


def _liste(p):
    return [_nombre(v) for v in p]


def _ajouter_facultatifs(d, element, champs):
    """Ajoute à d les champs facultatifs de element qui ne valent pas None (dans cet ordre)."""
    for champ in champs:
        valeur = getattr(element, champ)
        if valeur is not None:
            d[champ] = _nombre(valeur)
    return d


# ---------------------------------------------------------------- lieu.yaml

@dataclass
class Pose:
    """Position x, y (m) et orientation theta (rad) au sol."""
    x: float
    y: float
    theta: float = 0.0

    def vers_dict(self):
        return {"x": _nombre(self.x), "y": _nombre(self.y), "theta": _nombre(self.theta)}

    @classmethod
    def depuis_dict(cls, d):
        return cls(_nombre(d["x"]), _nombre(d["y"]), _nombre(d["theta"]))


@dataclass
class PoseEtage:
    """Pose sur un étage donné (ex. accueil de lieu.yaml)."""
    etage: str
    x: float
    y: float
    theta: float = 0.0

    def pose(self):
        return Pose(self.x, self.y, self.theta)

    def vers_dict(self):
        return {"etage": self.etage, "x": _nombre(self.x), "y": _nombre(self.y),
                "theta": _nombre(self.theta)}

    @classmethod
    def depuis_dict(cls, d):
        return cls(d["etage"], _nombre(d["x"]), _nombre(d["y"]), _nombre(d["theta"]))


@dataclass
class Etage:
    """Un étage : id (nomme ses fichiers), nom affiché, source de sa carte (monde ou scan)."""
    id: str
    nom: str
    source_carte: str = "monde"

    def vers_dict(self):
        return {"id": self.id, "nom": self.nom, "source_carte": self.source_carte}

    @classmethod
    def depuis_dict(cls, d):
        return cls(d["id"], d["nom"], d["source_carte"])


# ---------------------------------------------------------------- salles.yaml

@dataclass
class Salle:
    """Destination du guide. pose : où le robot s'arrête, tourné vers la salle."""
    id: str
    nom: str
    etage: str
    pose: Pose
    alias: List[str] = field(default_factory=list)
    phrase_arrivee: str = ""     # vide : le guide annonce le nom de la salle

    def vers_dict(self):
        return {"id": self.id, "nom": self.nom, "alias": list(self.alias), "etage": self.etage,
                "pose": self.pose.vers_dict(), "phrase_arrivee": self.phrase_arrivee}

    @classmethod
    def depuis_dict(cls, d):
        return cls(d["id"], d["nom"], d["etage"], Pose.depuis_dict(d["pose"]),
                   list(d.get("alias", [])), d.get("phrase_arrivee", ""))


# ---------------------------------------------------------------- itineraires.yaml

@dataclass
class Noeud:
    """Point de passage du graphe des itinéraires (son id est la clé dans Itineraires.noeuds)."""
    etage: str
    x: float
    y: float

    def vers_dict(self):
        return {"etage": self.etage, "x": _nombre(self.x), "y": _nombre(self.y)}

    @classmethod
    def depuis_dict(cls, d):
        return cls(d["etage"], _nombre(d["x"]), _nombre(d["y"]))


@dataclass
class Couloir:
    """Couloir entre deux nœuds, parcouru dans les deux sens. Dans le fichier : [a, b]."""
    a: str
    b: str

    def __iter__(self):
        return iter((self.a, self.b))

    def vers_dict(self):
        return [self.a, self.b]

    @classmethod
    def depuis_dict(cls, d):
        return cls(d[0], d[1])


@dataclass
class Itineraires:
    """Graphe du guide : nœuds rangés par id, et couloirs."""
    noeuds: Dict[str, Noeud] = field(default_factory=dict)
    couloirs: List[Couloir] = field(default_factory=list)

    def longueur(self, couloir):
        """Longueur du couloir, en mètres (distance entre ses deux nœuds)."""
        a, b = self.noeuds[couloir.a], self.noeuds[couloir.b]
        return math.hypot(b.x - a.x, b.y - a.y)

    def voisins(self, id_noeud):
        """Ids des nœuds reliés à id_noeud par un couloir."""
        return [c.b if c.a == id_noeud else c.a for c in self.couloirs if id_noeud in (c.a, c.b)]

    def vers_dict(self):
        return {"noeuds": {i: n.vers_dict() for i, n in self.noeuds.items()},
                "couloirs": [c.vers_dict() for c in self.couloirs]}

    @classmethod
    def depuis_dict(cls, d):
        return cls({i: Noeud.depuis_dict(n) for i, n in d["noeuds"].items()},
                   [Couloir.depuis_dict(c) for c in d["couloirs"]])


# ---------------------------------------------------------------- zones.yaml

@dataclass
class Zone:
    """Zone interdite (vitesse_max None) ou lente (vitesse_max en m/s). Polygone en mètres."""
    etage: str
    polygone: List[Point]
    nom: str = ""
    vitesse_max: Optional[float] = None

    def vers_dict(self):
        d = {}
        if self.nom:
            d["nom"] = self.nom
        d["etage"] = self.etage
        d["polygone"] = [_liste(p) for p in self.polygone]
        if self.vitesse_max is not None:
            d["vitesse_max"] = _nombre(self.vitesse_max)
        return d

    @classmethod
    def depuis_dict(cls, d):
        return cls(d["etage"], [_point(p) for p in d["polygone"]], d.get("nom", ""),
                   _nombre(d.get("vitesse_max")))


@dataclass
class Zones:
    """Zones interdites et lentes de tous les étages."""
    interdites: List[Zone] = field(default_factory=list)
    lentes: List[Zone] = field(default_factory=list)

    def vers_dict(self):
        return {"interdites": [z.vers_dict() for z in self.interdites],
                "lentes": [z.vers_dict() for z in self.lentes]}

    @classmethod
    def depuis_dict(cls, d):
        return cls([Zone.depuis_dict(z) for z in d["interdites"]],
                   [Zone.depuis_dict(z) for z in d["lentes"]])


# ---------------------------------------------------------------- mondes/<etage>.monde.yaml

@dataclass
class Emprise:
    """Rectangle aligné sur les axes qui contient tout le monde. Fichier : {min: [x, y], max: [x, y]}."""
    xmin: float
    ymin: float
    xmax: float
    ymax: float

    @property
    def taille_x(self):
        return self.xmax - self.xmin

    @property
    def taille_y(self):
        return self.ymax - self.ymin

    def contient(self, x, y, tolerance=1e-9):
        return (self.xmin - tolerance <= x <= self.xmax + tolerance
                and self.ymin - tolerance <= y <= self.ymax + tolerance)

    def vers_dict(self):
        return {"min": _liste((self.xmin, self.ymin)), "max": _liste((self.xmax, self.ymax))}

    @classmethod
    def depuis_dict(cls, d):
        return cls(_nombre(d["min"][0]), _nombre(d["min"][1]), _nombre(d["max"][0]), _nombre(d["max"][1]))


@dataclass
class Mur:
    """Mur droit de « de » à « a » : boîte de longueur exactement égale au segment, d'épaisseur
    centrée sur le segment, posée au sol."""
    id: str
    de: Point
    a: Point
    epaisseur: float = 0.15
    hauteur: float = 2.5
    source: Optional[str] = None         # facultatif : dessin (défaut) ou scan
    confiance: Optional[float] = None    # facultatif, de 0 à 1 : mur reconnu dans un scan

    @property
    def longueur(self):
        return math.hypot(self.a[0] - self.de[0], self.a[1] - self.de[1])

    @property
    def cap(self):
        """Direction du mur, de « de » vers « a », en radians."""
        return math.atan2(self.a[1] - self.de[1], self.a[0] - self.de[0])

    @property
    def centre(self):
        return ((self.de[0] + self.a[0]) / 2, (self.de[1] + self.a[1]) / 2)

    def coins(self):
        """Les 4 coins de l'empreinte au sol du mur."""
        return rectangle(self.centre, self.longueur, self.epaisseur, self.cap)

    def vers_dict(self):
        d = {"id": self.id, "de": _liste(self.de), "a": _liste(self.a),
             "epaisseur": _nombre(self.epaisseur), "hauteur": _nombre(self.hauteur)}
        return _ajouter_facultatifs(d, self, ("source", "confiance"))

    @classmethod
    def depuis_dict(cls, d):
        return cls(d["id"], _point(d["de"]), _point(d["a"]), _nombre(d["epaisseur"]), _nombre(d["hauteur"]),
                   d.get("source"), _nombre(d.get("confiance")))


@dataclass
class Objet:
    """Obstacle fixe posé au sol. Selon type :
      boite     centre, taille [longueur le long du cap, largeur, hauteur], cap
      cylindre  centre, rayon, hauteur
      modele    modele (chaise, table, banc, poubelle), centre, cap
    Champs facultatifs, pour tous les types (None : absent du fichier) :
      categorie  table, chaise, banc, poteau, meuble, poubelle, personne ou inconnu (CATEGORIES_OBJETS)
      source     dessin (défaut) ou scan
      confiance  de 0 à 1, pour un objet reconnu dans un scan
    """
    id: str
    type: str
    centre: Point
    cap: float = 0.0
    taille: Optional[Tuple[float, float, float]] = None
    rayon: Optional[float] = None
    hauteur: Optional[float] = None
    modele: Optional[str] = None
    categorie: Optional[str] = None
    source: Optional[str] = None
    confiance: Optional[float] = None

    @classmethod
    def boite(cls, id, centre, taille, cap=0.0, **facultatifs):
        """facultatifs : categorie, source, confiance."""
        return cls(id, "boite", _point(centre), cap, taille=tuple(taille), **facultatifs)

    @classmethod
    def cylindre(cls, id, centre, rayon, hauteur, **facultatifs):
        return cls(id, "cylindre", _point(centre), rayon=rayon, hauteur=hauteur, **facultatifs)

    @classmethod
    def meuble(cls, id, modele, centre, cap=0.0, **facultatifs):
        return cls(id, "modele", _point(centre), cap, modele=modele, **facultatifs)

    @property
    def categorie_effective(self):
        """Catégorie de l'objet : son champ categorie, sinon déduite de sa forme
        (modele → nom du modèle, cylindre → poteau, boite → meuble)."""
        if self.categorie:
            return self.categorie
        if self.type == "modele":
            return self.modele
        return CATEGORIE_PAR_TYPE.get(self.type, "inconnu")

    @property
    def sur_la_carte(self):
        """Faux pour un objet qui n'est jamais dessiné sur la carte 2D (catégorie personne)."""
        return self.categorie_effective not in CATEGORIES_HORS_CARTE

    def empreinte(self):
        """Forme au sol : ("cercle", centre, rayon) ou ("polygone", [4 coins])."""
        if self.type == "cylindre":
            return ("cercle", self.centre, self.rayon)
        if self.type == "modele":
            dims = MODELES_MOBILIER[self.modele]
            if "rayon" in dims:
                return ("cercle", self.centre, dims["rayon"])
            return ("polygone", rectangle(self.centre, dims["longueur"], dims["largeur"], self.cap))
        return ("polygone", rectangle(self.centre, self.taille[0], self.taille[1], self.cap))

    def hauteur_totale(self):
        """Hauteur de l'objet, en mètres."""
        if self.type == "boite":
            return self.taille[2]
        if self.type == "modele":
            return MODELES_MOBILIER[self.modele]["hauteur"]
        return self.hauteur

    def vers_dict(self):
        d = {"id": self.id, "type": self.type}
        if self.type == "modele":
            d["modele"] = self.modele
        d["centre"] = _liste(self.centre)
        if self.type == "boite":
            d["taille"] = _liste(self.taille)
        if self.type == "cylindre":
            d["rayon"] = _nombre(self.rayon)
            d["hauteur"] = _nombre(self.hauteur)
        else:
            d["cap"] = _nombre(self.cap)
        return _ajouter_facultatifs(d, self, ("categorie", "source", "confiance"))

    @classmethod
    def depuis_dict(cls, d):
        taille = tuple(_nombre(v) for v in d["taille"]) if "taille" in d else None
        return cls(d["id"], d["type"], _point(d["centre"]), _nombre(d.get("cap", 0.0)), taille,
                   _nombre(d.get("rayon")), _nombre(d.get("hauteur")), d.get("modele"),
                   d.get("categorie"), d.get("source"), _nombre(d.get("confiance")))


@dataclass
class Pieton:
    """Personne qui marche : part de trajet[0]. aller_retour False : boucle (retour direct au début)."""
    id: str
    trajet: List[Point]
    vitesse: float = 1.0
    aller_retour: bool = True

    def vers_dict(self):
        return {"id": self.id, "trajet": [_liste(p) for p in self.trajet],
                "vitesse": _nombre(self.vitesse), "aller_retour": bool(self.aller_retour)}

    @classmethod
    def depuis_dict(cls, d):
        return cls(d["id"], [_point(p) for p in d["trajet"]], _nombre(d["vitesse"]), d["aller_retour"])


@dataclass
class Monde:
    """Environnement inventé d'un étage : emprise, murs, objets, piétons et départ du robot."""
    emprise: Emprise
    depart_robot: Pose
    murs: List[Mur] = field(default_factory=list)
    objets: List[Objet] = field(default_factory=list)
    pietons: List[Pieton] = field(default_factory=list)
    version: int = VERSION

    def ids(self):
        """Ids des murs, objets et piétons (ils deviennent les noms des modèles Gazebo)."""
        return [e.id for e in (*self.murs, *self.objets, *self.pietons)]

    def element(self, id):
        """Mur, objet ou piéton d'id donné, ou None."""
        return next((e for e in (*self.murs, *self.objets, *self.pietons) if e.id == id), None)

    def vers_dict(self):
        return {"version": self.version, "emprise": self.emprise.vers_dict(),
                "murs": [m.vers_dict() for m in self.murs],
                "objets": [o.vers_dict() for o in self.objets],
                "pietons": [p.vers_dict() for p in self.pietons],
                "depart_robot": self.depart_robot.vers_dict()}

    @classmethod
    def depuis_dict(cls, d):
        return cls(Emprise.depuis_dict(d["emprise"]), Pose.depuis_dict(d["depart_robot"]),
                   [Mur.depuis_dict(m) for m in d.get("murs", [])],
                   [Objet.depuis_dict(o) for o in d.get("objets", [])],
                   [Pieton.depuis_dict(p) for p in d.get("pietons", [])],
                   d.get("version", VERSION))


# ---------------------------------------------------------------- cartes/<etage>.yaml

@dataclass
class InfoCarte:
    """Description d'une carte 2D Nav2 (cartes/<etage>.yaml, ou un masque cartes/<etage>_interdit.yaml).

    largeur et hauteur (en pixels) ne sont pas dans le fichier : charger_info_carte les lit dans
    l'en-tête de l'image .pgm. Elles sont nécessaires aux conversions pixel ↔ monde.
    chemin : fichier .yaml d'où vient l'info (None si elle est fabriquée en mémoire).
    autres : champs Nav2 supplémentaires (ex. mode), conservés tels quels.
    """
    image: str
    resolution: float = 0.05
    origin: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    negate: int = 0
    occupied_thresh: float = 0.65
    free_thresh: float = 0.196
    largeur: Optional[int] = None
    hauteur: Optional[int] = None
    chemin: Optional[Path] = None
    autres: dict = field(default_factory=dict)

    @property
    def chemin_image(self):
        """Chemin de l'image .pgm (à côté du .yaml), ou None si chemin est inconnu."""
        return None if self.chemin is None else Path(self.chemin).parent / self.image

    def vers_dict(self):
        d = {"image": self.image, "resolution": _nombre(self.resolution),
             "origin": _liste(self.origin), "negate": int(self.negate),
             "occupied_thresh": _nombre(self.occupied_thresh), "free_thresh": _nombre(self.free_thresh)}
        d.update(self.autres)
        return d

    @classmethod
    def depuis_dict(cls, d, chemin=None, largeur=None, hauteur=None):
        connus = ("image", "resolution", "origin", "negate", "occupied_thresh", "free_thresh")
        return cls(d["image"], _nombre(d["resolution"]), tuple(_nombre(v) for v in d["origin"]),
                   int(d["negate"]), _nombre(d["occupied_thresh"]), _nombre(d["free_thresh"]),
                   largeur, hauteur, Path(chemin) if chemin else None,
                   {k: v for k, v in d.items() if k not in connus})


# ---------------------------------------------------------------- le lieu complet

@dataclass
class Lieu:
    """Un paquet de lieu chargé en mémoire.

    Les champs nom, etages, accueil, langue, carte_unitree et version sont ceux de lieu.yaml ;
    vers_dict() et depuis_dict() ne concernent que ce fichier. Les autres fichiers sont dans
    salles, itineraires, zones et mondes (par id d'étage, seulement ceux qui existent).
    dossier : dossier du lieu ; son nom est l'identifiant du lieu.
    """
    nom: str
    etages: List[Etage]
    accueil: PoseEtage
    langue: str = "fr"
    carte_unitree: Optional[str] = None
    version: int = VERSION
    salles: List[Salle] = field(default_factory=list)
    itineraires: Itineraires = field(default_factory=Itineraires)
    zones: Zones = field(default_factory=Zones)
    mondes: Dict[str, Monde] = field(default_factory=dict)
    dossier: Optional[Path] = None

    @property
    def id(self):
        """Identifiant du lieu : le nom de son dossier (None si le lieu n'a pas de dossier)."""
        return None if self.dossier is None else Path(self.dossier).name

    def etage(self, id):
        """Étage d'id donné, ou None."""
        return next((e for e in self.etages if e.id == id), None)

    def salle(self, id):
        """Salle d'id donné, ou None."""
        return next((s for s in self.salles if s.id == id), None)

    def vers_dict(self):
        return {"version": self.version, "nom": self.nom, "langue": self.langue,
                "etages": [e.vers_dict() for e in self.etages],
                "accueil": self.accueil.vers_dict(), "carte_unitree": self.carte_unitree}

    @classmethod
    def depuis_dict(cls, d, dossier=None):
        return cls(d["nom"], [Etage.depuis_dict(e) for e in d["etages"]],
                   PoseEtage.depuis_dict(d["accueil"]), d["langue"], d.get("carte_unitree"),
                   d.get("version", VERSION), dossier=Path(dossier) if dossier else None)
