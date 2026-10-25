"""Lire, valider et enregistrer un paquet de lieu (contrat 4.1 du plan).

Principes :
  - un dossier de lieu se donne par son chemin, ou par son id seul (« demo » désigne
    $ATELIER_LIEUX/demo, voir atelier.chemin_lieu) ;
  - à la lecture comme à l'écriture, chaque fichier passe son schéma JSON et ses règles propres
    (validation.py) ; sinon ErreurLieu, avec des messages en français qui disent quoi corriger ;
  - les règles entre fichiers (salle ↔ nœud, couloirs de 8 m...) ne bloquent ni la lecture ni
    l'écriture : verification.verifier_lieu les signale ;
  - toute écriture est atomique : fichier temporaire dans le même dossier, puis renommage.
    Un lecteur voit donc l'ancien fichier ou le nouveau, jamais un fichier à moitié écrit.
  - un fichier enregistré perd les commentaires écrits à la main (YAML relu puis réécrit).
"""
import os
import shutil
import tempfile
from pathlib import Path

import numpy as np
import yaml

import atelier
from .modeles import (Emprise, Etage, InfoCarte, Itineraires, Lieu, Monde, Mur, Noeud, PoseEtage, Salle,
                      Zones)
from .validation import REGLE_ID, valider_donnees

FICHE = "lieu.yaml"
SALLES = "salles.yaml"
ITINERAIRES = "itineraires.yaml"
ZONES = "zones.yaml"

ENTETES = {
    "lieu": "Fiche du lieu. Format : atelier/lieu/schemas/lieu.schema.json. Unités : mètres et radians.",
    "salles": "Destinations du guide. Format : atelier/lieu/schemas/salles.schema.json.",
    "itineraires": "Graphe des itinéraires du guide. Format : atelier/lieu/schemas/itineraires.schema.json.",
    "zones": "Zones interdites et lentes. Format : atelier/lieu/schemas/zones.schema.json.",
    "monde": "Environnement inventé d'un étage. Format : atelier/lieu/schemas/monde.schema.json.",
    "carte": "Carte 2D au format Nav2. Format : atelier/lieu/schemas/carte.schema.json.",
}
FICHIER_VIDE = {
    "salles": "s'il n'y a encore aucune salle, écrivez []",
    "itineraires": "s'il n'y a encore aucun nœud, écrivez « noeuds: {} » puis « couloirs: [] »",
    "zones": "s'il n'y a encore aucune zone, écrivez « interdites: [] » puis « lentes: [] »",
}


class ErreurLieu(Exception):
    """Un fichier de lieu est illisible ou invalide. erreurs : messages en français."""

    def __init__(self, erreurs):
        self.erreurs = [erreurs] if isinstance(erreurs, str) else list(erreurs)
        super().__init__("\n".join(self.erreurs))


# ---------------------------------------------------------------- chemins

def dossier_lieu(lieu):
    """Dossier d'un lieu : depuis un Lieu, un chemin, ou un id seul (atelier.chemin_lieu)."""
    if isinstance(lieu, Lieu):
        if lieu.dossier is None:
            raise ValueError("ce lieu n'a pas encore de dossier : donnez-en un à enregistrer_lieu")
        return Path(lieu.dossier)
    return atelier.chemin_lieu(lieu)


def chemin_monde(lieu, etage):
    """mondes/<etage>.monde.yaml : l'environnement inventé de l'étage."""
    return dossier_lieu(lieu) / "mondes" / f"{etage}.monde.yaml"


def chemin_sdf(lieu, etage):
    """mondes/<etage>.sdf : le monde Gazebo généré."""
    return dossier_lieu(lieu) / "mondes" / f"{etage}.sdf"


def chemin_carte(lieu, etage):
    """cartes/<etage>.yaml : la carte 2D Nav2 (son image : cartes/<etage>.pgm)."""
    return dossier_lieu(lieu) / "cartes" / f"{etage}.yaml"


def chemin_interdit(lieu, etage):
    """cartes/<etage>_interdit.yaml : le masque Keepout des zones interdites."""
    return dossier_lieu(lieu) / "cartes" / f"{etage}_interdit.yaml"


def chemin_lent(lieu, etage):
    """cartes/<etage>_lent.yaml : le masque des zones lentes."""
    return dossier_lieu(lieu) / "cartes" / f"{etage}_lent.yaml"


def chemin_pcd(lieu, etage):
    """cartes/<etage>.pcd : le nuage 3D du scan."""
    return dossier_lieu(lieu) / "cartes" / f"{etage}.pcd"


def _nom_affiche(chemin):
    """Nom court d'un fichier dans les messages : salles.yaml, mondes/rdc.monde.yaml, cartes/rdc.yaml."""
    chemin = Path(chemin)
    if chemin.parent.name in ("mondes", "cartes"):
        return f"{chemin.parent.name}/{chemin.name}"
    return chemin.name


# ---------------------------------------------------------------- écriture atomique

def ecrire_atomique(chemin, contenu):
    """Écrit contenu (texte ou octets) dans chemin : fichier temporaire, puis renommage.
    Crée le dossier au besoin ; garde les droits du fichier remplacé (sinon rw-r--r--)."""
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    octets = contenu.encode("utf-8") if isinstance(contenu, str) else bytes(contenu)
    droits = chemin.stat().st_mode & 0o777 if chemin.exists() else 0o644
    fd, temporaire = tempfile.mkstemp(dir=chemin.parent, prefix=f".{chemin.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(octets)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(temporaire, droits)
        os.replace(temporaire, chemin)
    except BaseException:
        try:
            os.unlink(temporaire)
        except FileNotFoundError:
            pass
        raise


# ---------------------------------------------------------------- YAML

class _Chargeur(yaml.SafeLoader):
    """Lecteur YAML sûr qui refuse une clé écrite deux fois (PyYAML garderait la dernière)."""

    def construct_mapping(self, node, deep=False):
        self.flatten_mapping(node)
        vues = set()
        for noeud_cle, _ in node.value:
            cle = self.construct_object(noeud_cle, deep=deep)
            try:
                deja = cle in vues
            except TypeError:
                deja = False
            if deja:
                raise yaml.constructor.ConstructorError(
                    None, None, f"la clé « {cle} » apparaît deux fois ; gardez-en une seule", noeud_cle.start_mark)
            if not isinstance(cle, (list, dict)):
                vues.add(cle)
        return super().construct_mapping(node, deep)


SYNTAXE = [
    ("mapping values are not allowed", "un « : » est mal placé (texte qui contient « : » à mettre entre guillemets ?)"),
    ("found character '\\t'", "tabulation trouvée : indentez avec des espaces"),
    ("could not find expected ':'", "il manque « : » après un nom de champ"),
    ("expected ',' or ']'", "crochet [ ] mal fermé, ou virgule manquante"),
    ("expected ',' or '}'", "accolade { } mal fermée, ou virgule manquante"),
    ("did not find expected key", "indentation incohérente"),
    ("expected <block end>", "indentation incohérente"),
    ("did not find expected '-'", "indentation incohérente dans une liste"),
    ("found unexpected end of stream", "guillemet ou crochet ouvert et jamais fermé"),
    ("while scanning a quoted scalar", "guillemet ouvert et jamais fermé"),
]


def lire_yaml(texte, fichier="fichier"):
    """Lit un texte YAML (clés en double refusées). Erreur de syntaxe : ErreurLieu en français."""
    try:
        return yaml.load(texte, Loader=_Chargeur)
    except yaml.MarkedYAMLError as e:
        marque = e.problem_mark or e.context_mark
        ou = f", ligne {marque.line + 1}, colonne {marque.column + 1}" if marque else ""
        probleme = e.problem or ""
        if probleme.startswith("la clé"):
            raise ErreurLieu(f"{fichier}{ou} : {probleme}") from None
        explication = next((fr for en, fr in SYNTAXE if en in str(e)), f"erreur de syntaxe YAML ({probleme})")
        raise ErreurLieu(f"{fichier}{ou} : {explication}. Vérifiez l'indentation (des espaces, pas de "
                         "tabulations), les « : », les crochets et les guillemets") from None
    except yaml.YAMLError as e:
        raise ErreurLieu(f"{fichier} : YAML illisible ({e})") from None


class _Flux(list):
    """Liste écrite sur une ligne : [1.0, 2.0]."""


class _FluxDict(dict):
    """Dictionnaire écrit sur une ligne : {x: 1.0, y: 2.0}."""


class _Ecrivain(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True      # jamais de &id001 / *id001


_Ecrivain.add_representer(_Flux, lambda d, v: d.represent_sequence("tag:yaml.org,2002:seq", v, flow_style=True))
_Ecrivain.add_representer(_FluxDict, lambda d, v: d.represent_mapping("tag:yaml.org,2002:map", v, flow_style=True))


def _contient_dict(v):
    if isinstance(v, dict):
        return True
    return isinstance(v, (list, tuple)) and any(_contient_dict(x) for x in v)


def _mettre_en_forme(v, niveau=0):
    """Choisit les parties écrites sur une ligne, comme dans les fichiers faits à la main :
    un élément sans sous-dictionnaire ({id: m1, de: [0, 0], ...}) et une liste de nombres."""
    if isinstance(v, dict):
        contenu = {k: _mettre_en_forme(x, niveau + 1) for k, x in v.items()}
        if niveau >= 1 and not any(_contient_dict(x) for x in v.values()):
            return _FluxDict(contenu)
        return contenu
    if isinstance(v, (list, tuple)):
        contenu = [_mettre_en_forme(x, niveau + 1) for x in v]
        scalaires = not any(isinstance(x, (dict, list, tuple)) for x in v)
        if niveau >= 1 and not _contient_dict(v) and (scalaires or niveau >= 2):
            return _Flux(contenu)
        return contenu
    return v


def texte_yaml(donnees, entete=None):
    """Texte YAML lisible des données, précédé d'un commentaire facultatif."""
    corps = yaml.dump(_mettre_en_forme(donnees), Dumper=_Ecrivain, sort_keys=False, allow_unicode=True,
                      default_flow_style=False, width=100)
    if not entete:
        return corps
    return (f"# {entete}\n# Écrit par l'Atelier G1 : les commentaires ajoutés à la main ne sont pas "
            f"conservés.\n{corps}")


def ecrire_yaml(chemin, donnees, entete=None):
    """Écrit des données en YAML, de façon atomique (sans validation)."""
    ecrire_atomique(chemin, texte_yaml(donnees, entete))


# ---------------------------------------------------------------- lecture et écriture validées

def charger_fichier(chemin, type_fichier, fichier=None):
    """Lit un fichier YAML et le valide (schéma et règles propres). Renvoie les données brutes.

    type_fichier : lieu, monde, salles, itineraires, zones ou carte.
    fichier : nom affiché dans les messages (par défaut : salles.yaml, mondes/rdc.monde.yaml...).
    ErreurLieu si le fichier manque, est illisible ou invalide.
    """
    chemin = Path(chemin)
    fichier = fichier or _nom_affiche(chemin)
    if not chemin.is_file():
        raise ErreurLieu(f"{fichier} : fichier introuvable ({chemin})")
    try:
        texte = chemin.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise ErreurLieu(f"{fichier} : le fichier n'est pas en UTF-8 ; réenregistrez-le en UTF-8") from None
    donnees = lire_yaml(texte, fichier)
    if donnees is None:
        conseil = FICHIER_VIDE.get(type_fichier)
        raise ErreurLieu(f"{fichier} : le fichier est vide" + (f" ; {conseil}" if conseil else ""))
    erreurs = valider_donnees(type_fichier, donnees, fichier)
    if erreurs:
        raise ErreurLieu(erreurs)
    return donnees


def enregistrer_fichier(chemin, type_fichier, donnees, fichier=None):
    """Valide des données (schéma et règles propres) puis les écrit en YAML, de façon atomique.
    ErreurLieu (et rien d'écrit) si elles sont invalides."""
    chemin = Path(chemin)
    erreurs = valider_donnees(type_fichier, donnees, fichier or _nom_affiche(chemin))
    if erreurs:
        raise ErreurLieu(erreurs)
    ecrire_yaml(chemin, donnees, ENTETES.get(type_fichier))


def charger_fiche(lieu):
    """lieu.yaml seul → Lieu (sans salles, itinéraires, zones ni mondes)."""
    dossier = dossier_lieu(lieu)
    donnees = charger_fichier(dossier / FICHE, "lieu")
    return Lieu.depuis_dict(donnees, dossier)


def enregistrer_fiche(lieu, dossier=None):
    """Écrit lieu.yaml depuis un Lieu."""
    dossier = dossier_lieu(dossier if dossier is not None else lieu)
    enregistrer_fichier(dossier / FICHE, "lieu", lieu.vers_dict())


def charger_salles(lieu):
    """salles.yaml → liste de Salle. Fichier absent : liste vide."""
    chemin = dossier_lieu(lieu) / SALLES
    if not chemin.exists():
        return []
    return [Salle.depuis_dict(s) for s in charger_fichier(chemin, "salles")]


def enregistrer_salles(lieu, salles):
    """Écrit salles.yaml depuis une liste de Salle."""
    enregistrer_fichier(dossier_lieu(lieu) / SALLES, "salles", [s.vers_dict() for s in salles])


def charger_itineraires(lieu):
    """itineraires.yaml → Itineraires. Fichier absent : graphe vide."""
    chemin = dossier_lieu(lieu) / ITINERAIRES
    if not chemin.exists():
        return Itineraires()
    return Itineraires.depuis_dict(charger_fichier(chemin, "itineraires"))


def enregistrer_itineraires(lieu, itineraires):
    """Écrit itineraires.yaml depuis un Itineraires."""
    enregistrer_fichier(dossier_lieu(lieu) / ITINERAIRES, "itineraires", itineraires.vers_dict())


def charger_zones(lieu):
    """zones.yaml → Zones. Fichier absent : aucune zone."""
    chemin = dossier_lieu(lieu) / ZONES
    if not chemin.exists():
        return Zones()
    return Zones.depuis_dict(charger_fichier(chemin, "zones"))


def enregistrer_zones(lieu, zones):
    """Écrit zones.yaml depuis un Zones."""
    enregistrer_fichier(dossier_lieu(lieu) / ZONES, "zones", zones.vers_dict())


def charger_monde(lieu, etage):
    """mondes/<etage>.monde.yaml → Monde. ErreurLieu si le fichier n'existe pas."""
    return Monde.depuis_dict(charger_fichier(chemin_monde(lieu, etage), "monde"))


def enregistrer_monde(lieu, etage, monde):
    """Écrit mondes/<etage>.monde.yaml depuis un Monde."""
    enregistrer_fichier(chemin_monde(lieu, etage), "monde", monde.vers_dict())


# ---------------------------------------------------------------- images PGM et cartes

def _entete_pgm(octets):
    """En-tête d'un PGM : (format, largeur, hauteur, maxval, position du début des pixels)."""
    jetons, pos = [], 0
    while len(jetons) < 4:
        while pos < len(octets) and octets[pos:pos + 1].isspace():
            pos += 1
        if octets[pos:pos + 1] == b"#":
            while pos < len(octets) and octets[pos:pos + 1] not in (b"\n", b"\r"):
                pos += 1
            continue
        debut = pos
        while pos < len(octets) and not octets[pos:pos + 1].isspace() and octets[pos:pos + 1] != b"#":
            pos += 1
        if debut == pos:
            raise ValueError("en-tête PGM incomplet")
        jetons.append(octets[debut:pos])
    if jetons[0] not in (b"P5", b"P2"):
        raise ValueError(f"pas une image PGM (début : {jetons[0][:4]!r}, attendu P5 ou P2)")
    return jetons[0].decode(), int(jetons[1]), int(jetons[2]), int(jetons[3]), pos + 1


def taille_pgm(chemin):
    """(largeur, hauteur) en pixels d'une image PGM, en ne lisant que son en-tête."""
    with open(chemin, "rb") as f:
        debut = f.read(4096)
    try:
        _, largeur, hauteur, _, _ = _entete_pgm(debut)
    except ValueError:
        _, largeur, hauteur, _, _ = _entete_pgm(Path(chemin).read_bytes())
    return largeur, hauteur


def lire_pgm(chemin):
    """Image PGM (P5 binaire ou P2 texte) → tableau numpy (hauteur, largeur), uint8 si maxval ≤ 255.
    image[0] est la ligne du haut de l'image."""
    octets = Path(chemin).read_bytes()
    forme, largeur, hauteur, maxval, debut = _entete_pgm(octets)
    type_pixel = np.uint8 if maxval < 256 else np.dtype(">u2")
    if forme == "P5":
        taille = largeur * hauteur * np.dtype(type_pixel).itemsize
        if len(octets) - debut < taille:
            raise ValueError(f"image PGM tronquée : {chemin}")
        pixels = np.frombuffer(octets, dtype=type_pixel, count=largeur * hauteur, offset=debut)
    else:
        pixels = np.array(octets[debut:].split()[:largeur * hauteur], dtype=int)
    return pixels.reshape(hauteur, largeur).astype(np.uint8 if maxval < 256 else np.uint16)


def ecrire_pgm(chemin, image):
    """Écrit un tableau (hauteur, largeur) de valeurs 0 à 255 en PGM binaire (P5), de façon atomique.
    image[0] est la ligne du haut (le y maximal d'une carte)."""
    image = np.asarray(image)
    if image.ndim != 2:
        raise ValueError(f"image PGM : il faut un tableau à 2 dimensions (hauteur, largeur), pas {image.shape}")
    if image.size and (image.min() < 0 or image.max() > 255):
        raise ValueError("image PGM : les valeurs doivent aller de 0 à 255")
    hauteur, largeur = image.shape
    entete = f"P5\n# Atelier G1\n{largeur} {hauteur}\n255\n".encode("ascii")
    ecrire_atomique(chemin, entete + image.astype(np.uint8).tobytes())


def charger_info_carte(chemin_yaml):
    """Lit un .yaml de carte Nav2 (carte ou masque) → InfoCarte, avec la taille de l'image .pgm.
    ErreurLieu si le .yaml est invalide ou si l'image manque."""
    chemin = Path(chemin_yaml)
    fichier = _nom_affiche(chemin)
    donnees = charger_fichier(chemin, "carte", fichier)
    image = chemin.parent / donnees["image"]
    if not image.is_file():
        raise ErreurLieu(f"{fichier} : l'image {donnees['image']} est introuvable à côté du fichier ({image})")
    try:
        largeur, hauteur = taille_pgm(image)
    except (ValueError, OSError) as e:
        raise ErreurLieu(f"{fichier} : l'image {donnees['image']} est illisible ({e})") from None
    return InfoCarte.depuis_dict(donnees, chemin, largeur, hauteur)


def enregistrer_info_carte(chemin_yaml, info):
    """Écrit le .yaml d'une carte (ou d'un masque) depuis un InfoCarte. Met à jour info.chemin."""
    chemin = Path(chemin_yaml)
    enregistrer_fichier(chemin, "carte", info.vers_dict(), _nom_affiche(chemin))
    info.chemin = chemin


def charger_carte(chemin_yaml):
    """Carte complète : (InfoCarte, image numpy (hauteur, largeur)). image[0] : ligne du y maximal."""
    info = charger_info_carte(chemin_yaml)
    try:
        return info, lire_pgm(info.chemin_image)
    except (ValueError, OSError) as e:
        raise ErreurLieu(f"{_nom_affiche(chemin_yaml)} : l'image {info.image} est illisible ({e})") from None


def enregistrer_carte(chemin_yaml, info, image):
    """Écrit une carte ou un masque : l'image .pgm (nommée info.image, à côté du .yaml), puis le .yaml.
    info.largeur et info.hauteur sont mis à jour d'après l'image. 0 = occupé, 254 = libre, 205 = inconnu."""
    chemin = Path(chemin_yaml)
    image = np.asarray(image)
    if not info.image:
        info.image = chemin.stem + ".pgm"
    erreurs = valider_donnees("carte", info.vers_dict(), _nom_affiche(chemin))
    if erreurs:
        raise ErreurLieu(erreurs)
    ecrire_pgm(chemin.parent / info.image, image)
    info.hauteur, info.largeur = image.shape
    enregistrer_info_carte(chemin, info)


# ---------------------------------------------------------------- le lieu complet

def charger_lieu(lieu):
    """Charge tout le paquet : lieu.yaml, salles, itinéraires, zones, et le monde de chaque étage
    qui en a un. Les fichiers salles, itinéraires et zones absents sont pris comme vides.

    ErreurLieu (avec toutes les erreurs de tous les fichiers) si un fichier est invalide.
    Les règles entre fichiers ne sont pas vérifiées ici : voir verifier_lieu / valider_lieu.
    """
    dossier = dossier_lieu(lieu)
    if not dossier.is_dir():
        raise ErreurLieu(f"le lieu {dossier} n'existe pas ; pour en créer un : g1-lieu creer ID --nom NOM")
    if not (dossier / FICHE).is_file():
        raise ErreurLieu(f"{dossier} : pas de lieu.yaml, ce dossier n'est pas un lieu ; "
                         "pour en créer un : g1-lieu creer ID --nom NOM")
    erreurs = []

    def essayer(fonction, *args, defaut=None):
        try:
            return fonction(*args)
        except ErreurLieu as e:
            erreurs.extend(e.erreurs)
            return defaut

    resultat = essayer(charger_fiche, dossier)
    salles = essayer(charger_salles, dossier, defaut=[])
    itineraires = essayer(charger_itineraires, dossier, defaut=Itineraires())
    zones = essayer(charger_zones, dossier, defaut=Zones())
    mondes = {}
    if resultat is not None:
        for etage in resultat.etages:
            if chemin_monde(dossier, etage.id).exists():
                monde = essayer(charger_monde, dossier, etage.id)
                if monde is not None:
                    mondes[etage.id] = monde
    if erreurs:
        raise ErreurLieu(erreurs)
    resultat.salles, resultat.itineraires, resultat.zones, resultat.mondes = salles, itineraires, zones, mondes
    return resultat


def enregistrer_lieu(lieu, dossier=None):
    """Enregistre tout le paquet : lieu.yaml, salles.yaml, itineraires.yaml, zones.yaml et
    mondes/<etage>.monde.yaml pour chaque monde de lieu.mondes. Les fichiers générés (cartes, .sdf)
    ne sont pas touchés.

    dossier : où enregistrer (par défaut lieu.dossier) ; lieu.dossier est mis à jour.
    Tout est validé avant d'écrire : en cas d'erreur, ErreurLieu et aucun fichier n'est modifié.
    Renvoie le dossier.
    """
    if dossier is None and lieu.dossier is None:
        raise ValueError("enregistrer_lieu : donnez un dossier (ce lieu n'en a pas encore)")
    dossier = dossier_lieu(dossier if dossier is not None else lieu)
    a_ecrire = [(dossier / FICHE, "lieu", lieu.vers_dict()),
                (dossier / SALLES, "salles", [s.vers_dict() for s in lieu.salles]),
                (dossier / ITINERAIRES, "itineraires", lieu.itineraires.vers_dict()),
                (dossier / ZONES, "zones", lieu.zones.vers_dict())]
    a_ecrire += [(chemin_monde(dossier, e), "monde", m.vers_dict()) for e, m in lieu.mondes.items()]
    erreurs = []
    for chemin, type_fichier, donnees in a_ecrire:
        erreurs += valider_donnees(type_fichier, donnees, _nom_affiche(chemin))
    if erreurs:
        raise ErreurLieu(erreurs)
    for chemin, type_fichier, donnees in a_ecrire:
        ecrire_yaml(chemin, donnees, ENTETES[type_fichier])
    lieu.dossier = dossier
    return dossier


def creer_lieu(lieu, nom, etage="rdc", nom_etage="Rez-de-chaussée", largeur=20.0, profondeur=15.0, langue="fr"):
    """Crée un lieu neuf et l'enregistre. Renvoie le Lieu.

    lieu : id (ex. « lycee », dans $ATELIER_LIEUX) ou chemin du dossier, qui ne doit pas exister
    (ou être vide). Contenu : un étage, l'accueil en (1, 1) tourné vers x, la salle et le nœud
    « accueil », aucune zone, et un monde de largeur × profondeur mètres entouré de 4 murs.
    """
    dossier = dossier_lieu(lieu)
    if not atelier.MOTIF_ID.match(dossier.name):
        raise ErreurLieu(f"« {dossier.name} » n'est pas un identifiant de lieu valable : {REGLE_ID}")
    if dossier.exists() and (not dossier.is_dir() or any(dossier.iterdir())):
        raise ErreurLieu(f"le lieu « {dossier.name} » existe déjà ({dossier}) ; choisissez un autre id")
    if largeur < 3 or profondeur < 3:
        raise ErreurLieu(f"monde de {largeur:g} × {profondeur:g} m : trop petit, il faut au moins 3 × 3 m")
    accueil = PoseEtage(etage, 1.0, 1.0, 0.0)
    x, y = float(largeur), float(profondeur)
    murs = [Mur("ext_sud", (0.0, 0.0), (x, 0.0), 0.2, 2.5), Mur("ext_est", (x, 0.0), (x, y), 0.2, 2.5),
            Mur("ext_nord", (x, y), (0.0, y), 0.2, 2.5), Mur("ext_ouest", (0.0, y), (0.0, 0.0), 0.2, 2.5)]
    nouveau = Lieu(
        nom=nom, etages=[Etage(etage, nom_etage, "monde")], accueil=accueil, langue=langue,
        salles=[Salle("accueil", "Accueil", etage, accueil.pose(), ["accueil"], "")],
        itineraires=Itineraires({"accueil": Noeud(etage, accueil.x, accueil.y)}, []),
        zones=Zones(),
        mondes={etage: Monde(Emprise(0.0, 0.0, x, y), accueil.pose(), murs)})
    enregistrer_lieu(nouveau, dossier)
    return nouveau


def copier_lieu(source, destination):
    """Copie tout le dossier d'un lieu (ex. lieux/demo vers un dossier de test). Renvoie la destination.
    La destination ne doit pas exister."""
    source, destination = dossier_lieu(source), dossier_lieu(destination)
    if not (source / FICHE).is_file():
        raise ErreurLieu(f"{source} : pas de lieu.yaml, ce dossier n'est pas un lieu")
    if destination.exists():
        raise ErreurLieu(f"{destination} existe déjà ; choisissez une autre destination")
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns("__pycache__", ".*.tmp"))
    return destination


def lister_lieux(dossier=None):
    """Dossiers des lieux (ceux qui ont un lieu.yaml) dans dossier, par défaut $ATELIER_LIEUX."""
    racine = Path(dossier) if dossier else atelier.dossier_lieux()
    if not racine.is_dir():
        return []
    return sorted(d for d in racine.iterdir() if (d / FICHE).is_file())
