"""Nuages d'affichage de la carte 3D (vague 5, section 12.5 du plan) : emplacements, en-tête, lecture
et écriture. Module de contrat, livré et testé par l'agent Contrats (atelier/tests/test_contrats_vague5.py).

Un nuage d'affichage, ce sont deux fichiers de même nom :
  <nom>.bin    les points : n × (x, y, z) en Float32 petit-boutistes, 12 octets par point, sans en-tête ;
  <nom>.json   l'en-tête (schéma nuage) : version, format, points, grille, repere, bornes, sol, source, date…
x, y : repère map de l'étage, en mètres, exactement ceux de la carte 2D, des salles, des itinéraires et
des zones (aucune conversion) ; z : hauteur au-dessus du sol, le plan du sol étant déjà soustrait (le
sol est à z = 0 partout). Le navigateur colore lui-même les points d'après z.

Emplacements (base = chemin sans .bin ni .json) :
  cartes/<etage>.nuage               nuage de l'étage, copié à l'adoption d'un scan        source scan
  cartes/<etage>_unitree.nuage       carte d'Unitree (g1-scan carte-unitree)                source unitree
  scans/<session>/nuage_affichage    nuage traité d'une session (g1-scan traiter)           source scan
  scans/<session>/apercu_nuage       aperçu en direct pendant le scan (toutes les 2 s)      source apercu

Fonctions :
  chemin_nuage(lieu, etage, source="scan") -> Path         base du nuage d'un étage
  chemin_nuage_session(dossier_session, apercu=False) -> Path
  fichiers_nuage(base) -> (Path du .bin, Path du .json)
  entete_nuage(points, grille, sol, source, session=None, etage=None, date=None, **autres) -> dict
  ecrire_nuage(base, points, entete) -> dict     .bin puis .json, atomiques, validés (ErreurLieu sinon)
  lire_entete_nuage(base) -> dict                validé, taille du .bin comprise (ErreurLieu sinon)
  lire_nuage(base) -> (tableau numpy float32 (n, 3), en-tête)
  valider_entete_nuage(entete, taille_octets=None) -> [messages]
  entetes_http_nuage(entete) -> {nom: texte}     en-têtes X-Nuage-* de GET …/nuage (section 12.4)

Seulement numpy et la bibliothèque standard : le module tourne aussi dans le conteneur du Jetson.
"""
import json
import math
from datetime import datetime
from pathlib import Path

import numpy as np

from .fichiers import ErreurLieu, dossier_lieu, ecrire_atomique
from .validation import valider_donnees

VERSION = 1
FORMAT_NUAGE = "float32_xyz"
OCTETS_PAR_POINT = 12
TYPE_NUMPY = "<f4"                    # Float32 petit-boutiste
SOURCES_NUAGE = ("scan", "apercu", "unitree")
GRILLE_NUAGE = 0.05                   # m : voxels du nuage traité (scan) et de la carte d'Unitree
GRILLE_APERCU = 0.10                  # m : voxels de l'aperçu en direct
APERCU_NUAGE_POINTS_MAX = 150000      # points au plus dans l'aperçu en direct (réécrit toutes les 2 s)
NUAGE_POINTS_MAX = 5000000            # points au plus dans un nuage d'affichage (60 Mo)
HAUTEUR_COUPE = 2.2                   # m : la page cache les points plus hauts (plafond), case pour les montrer
EXTENSIONS = (".bin", ".json")
PREFIXE_HTTP = "X-Nuage-"


def chemin_nuage(lieu, etage, source="scan"):
    """Base (sans extension) du nuage d'un étage : cartes/<etage>.nuage (source scan) ou
    cartes/<etage>_unitree.nuage (source unitree)."""
    if source not in ("scan", "unitree"):
        raise ValueError(f"source de nuage d'un étage inconnue : {source} (scan ou unitree)")
    nom = f"{etage}.nuage" if source == "scan" else f"{etage}_unitree.nuage"
    return dossier_lieu(lieu) / "cartes" / nom


def chemin_nuage_session(dossier_session, apercu=False):
    """Base du nuage d'une session : nuage_affichage (traité), ou apercu_nuage (en direct)."""
    return Path(dossier_session) / ("apercu_nuage" if apercu else "nuage_affichage")


def fichiers_nuage(base):
    """(.bin, .json) d'une base : cartes/rdc.nuage → cartes/rdc.nuage.bin et cartes/rdc.nuage.json."""
    base = Path(base)
    return base.with_name(base.name + ".bin"), base.with_name(base.name + ".json")


def _points(points):
    tableau = np.asarray(points, dtype=np.float64)
    if tableau.size == 0:
        return np.zeros((0, 3), dtype=np.float32)
    if tableau.ndim != 2 or tableau.shape[1] != 3:
        raise ValueError(f"les points doivent être un tableau (n, 3) de x, y, z ; reçu la forme {tableau.shape}")
    if not np.isfinite(tableau).all():
        raise ValueError("les points contiennent des valeurs non finies (NaN ou infini) : retirez-les avant")
    return tableau.astype(np.float32)


def _instant(quand=None):
    quand = quand or datetime.now()
    return quand.astimezone().replace(microsecond=0).isoformat()


def entete_nuage(points, grille, sol, source, session=None, etage=None, date=None, **autres):
    """En-tête (dict, schéma nuage) de ces points. sol : [a, b, c] (le plan z = a·x + b·y + c soustrait
    des points) ou un dict {plan, inclinaison_deg?, methode?}. Bornes arrondies au millimètre vers
    l'extérieur. autres : champs en plus (mobiles_retires…)."""
    p = _points(points)
    if len(p):
        mins = p.min(axis=0).astype(np.float64)
        maxs = p.max(axis=0).astype(np.float64)
        bornes = {}
        for i, axe in enumerate("xyz"):
            bornes[f"{axe}min"] = math.floor(float(mins[i]) * 1000.0) / 1000.0
            bornes[f"{axe}max"] = math.ceil(float(maxs[i]) * 1000.0) / 1000.0
    else:
        bornes = {f"{axe}{m}": 0.0 for axe in "xyz" for m in ("min", "max")}
    bornes = {cle: bornes[cle] for cle in ("xmin", "ymin", "zmin", "xmax", "ymax", "zmax")}
    if isinstance(sol, dict):
        sol = dict(sol)
        sol["plan"] = [float(v) for v in sol["plan"]]
    else:
        a, b, c = (float(v) for v in sol)
        sol = {"plan": [a, b, c], "inclinaison_deg": round(math.degrees(math.atan(math.hypot(a, b))), 3)}
    entete = {"version": VERSION, "format": FORMAT_NUAGE, "points": int(len(p)), "grille": float(grille),
              "repere": "map", "bornes": bornes, "sol": sol, "source": source,
              "session": session, "date": date or _instant()}
    if etage is not None:
        entete["etage"] = etage
    entete.update(autres)
    return entete


def valider_entete_nuage(entete, taille_octets=None):
    """Erreurs (en français) d'un en-tête ; taille_octets : taille du .bin, à comparer à 12 × points."""
    erreurs = valider_donnees("nuage", entete)
    if not erreurs and taille_octets is not None and taille_octets != OCTETS_PAR_POINT * entete["points"]:
        erreurs.append(f"en-tête du nuage : le fichier .bin fait {taille_octets} octets, mais l'en-tête annonce "
                       f"{entete['points']} points ({OCTETS_PAR_POINT} × {entete['points']} = "
                       f"{OCTETS_PAR_POINT * entete['points']} octets) : refaites le nuage "
                       "(g1-scan traiter --refaire, puis g1-scan adopter)")
    return erreurs


def ecrire_nuage(base, points, entete):
    """Écrit <base>.bin puis <base>.json (atomiques), après avoir vérifié l'en-tête face aux points
    (nombre de points compris). Renvoie l'en-tête. ErreurLieu si l'en-tête est faux."""
    p = _points(points)
    erreurs = valider_entete_nuage(entete, OCTETS_PAR_POINT * len(p))
    if not erreurs and entete["points"] > NUAGE_POINTS_MAX:
        erreurs = [f"en-tête du nuage : {entete['points']} points, plus que {NUAGE_POINTS_MAX} : réduisez le "
                   "nuage (grille plus grande)"]
    if erreurs:
        raise ErreurLieu(erreurs)
    binaire, texte = fichiers_nuage(base)
    ecrire_atomique(binaire, p.astype(TYPE_NUMPY).tobytes())
    ecrire_atomique(texte, json.dumps(entete, ensure_ascii=False, indent=1) + "\n")
    return entete


def lire_entete_nuage(base):
    """En-tête d'un nuage, vérifié (schéma, et taille du .bin). ErreurLieu si un fichier manque ou est faux."""
    binaire, texte = fichiers_nuage(base)
    for chemin in (binaire, texte):
        if not chemin.is_file():
            raise ErreurLieu(f"{chemin.name} : fichier absent (le nuage n'a pas encore été fabriqué)")
    try:
        entete = json.loads(texte.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ErreurLieu(f"{texte.name} : illisible ({e}) ; refaites le nuage") from None
    erreurs = valider_entete_nuage(entete, binaire.stat().st_size)
    if erreurs:
        raise ErreurLieu([f"{texte.name} : {m}" for m in erreurs])
    return entete


def lire_nuage(base):
    """(points, en-tête) : points en tableau numpy float32 de forme (n, 3)."""
    entete = lire_entete_nuage(base)
    binaire, _ = fichiers_nuage(base)
    points = np.fromfile(binaire, dtype=TYPE_NUMPY).astype(np.float32).reshape(-1, 3)
    return points, entete


def _nombre_http(v):
    return f"{float(v):.6g}"


def entetes_http_nuage(entete):
    """En-têtes HTTP de la réponse binaire d'un nuage (section 12.4) : X-Nuage-Points, -Grille,
    -Bornes (xmin,ymin,zmin,xmax,ymax,zmax), -Source, -Date et -Session (vide si aucune)."""
    b = entete["bornes"]
    bornes = ",".join(_nombre_http(b[c]) for c in ("xmin", "ymin", "zmin", "xmax", "ymax", "zmax"))
    return {PREFIXE_HTTP + "Points": str(int(entete["points"])),
            PREFIXE_HTTP + "Grille": _nombre_http(entete["grille"]),
            PREFIXE_HTTP + "Bornes": bornes, PREFIXE_HTTP + "Source": entete["source"],
            PREFIXE_HTTP + "Date": entete["date"], PREFIXE_HTTP + "Session": entete.get("session") or ""}
