"""Nuages 3D et maillage de la carte extrudée (vague 5, sections 12.4 et 12.5 du plan) : agent Scan.

Formats : atelier.lieu.nuage (schéma nuage), atelier.monde.extrusion (STL binaire).

  GET /api/lieux/{id}/etages/{e}/nuage[?source=scan|unitree]
        le binaire cartes/<e>.nuage.bin (ou <e>_unitree.nuage.bin) : application/octet-stream,
        Float32 x y z petit-boutistes, avec les en-têtes HTTP X-Nuage-Points, X-Nuage-Grille,
        X-Nuage-Bornes, X-Nuage-Source, X-Nuage-Date, X-Nuage-Session (entetes_http_nuage) et un
        ETag (If-None-Match → 304) ; 404 en français s'il n'y a pas de nuage.
  GET /api/lieux/{id}/etages/{e}/nuage/info[?source=scan|unitree]
        l'en-tête JSON (cartes/<e>.nuage.json), plus {url, octets, modifie}.
  GET /api/lieux/{id}/etages/{e}/monde/maillage
        mondes/<e>_carte.stl (model/stl) : la carte extrudée du champ carte_extrudee du monde ; 404 sinon.
  GET /api/scan/nuage?lieu=L[&session=S][&apercu=1]
        le binaire du nuage d'une session (même format et mêmes en-têtes) : nuage_affichage.bin quand
        la session est traitée ; pendant le scan, ou avec apercu=1, l'aperçu en direct apercu_nuage.bin.
  GET /api/scan/nuage/info?lieu=L[&session=S][&apercu=1]
        l'en-tête JSON correspondant, plus {url, octets, modifie, apercu}.

Les fichiers de l'aperçu sont réécrits toutes les 2 s (renommage atomique, le .bin avant le .json) : la
lecture vérifie que les deux vont ensemble et recommence sinon.
"""
import json
import time
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import Response

from atelier.lieu import (APERCU_NUAGE, ETATS_ACTIFS, NUAGE_AFFICHAGE, ErreurLieu, charger_monde, chemin_maillage,
                          chemin_monde, chemin_nuage, dossier_session, entetes_http_nuage, fichiers_nuage,
                          lire_session, valider_entete_nuage)

from ..communs import ErreurAtelier, dossier_du_lieu, etage_du_lieu

routeur = APIRouter(tags=["nuage 3D"])

TYPE_BINAIRE = "application/octet-stream"
TYPE_STL = "model/stl"
SANS_CACHE = "no-cache"            # le navigateur redemande, l'ETag évite de renvoyer le même fichier
ESSAIS_LECTURE = 5                 # relectures si le .bin et le .json changent pendant la lecture
SOURCES_ETAGE = ("scan", "unitree")
PAS_DE_NUAGE = ("Pas encore de nuage 3D pour cet étage : faites un scan, puis « Utiliser cette carte ».")
PAS_DE_CARTE_UNITREE = ("Pas encore de carte d'Unitree pour cet étage : lancez g1-scan carte-unitree --lieu {lieu} "
                        "--etage {etage}, puis « Repérer le robot » pendant l'attente.")


# ---------------------------------------------------------------- lecture d'un nuage

def lire_nuage_fichiers(base):
    """(octets du .bin, en-tête, instant de modification) d'un nuage, qui vont ensemble ; None s'il manque.
    ErreurAtelier 422 si l'en-tête est invalide (après les relectures)."""
    binaire, texte = fichiers_nuage(base)
    erreurs = []
    for essai in range(ESSAIS_LECTURE):
        try:
            entete = json.loads(texte.read_text(encoding="utf-8"))
            octets = binaire.read_bytes()
            modifie = max(binaire.stat().st_mtime, texte.stat().st_mtime)
        except FileNotFoundError:
            return None
        except (OSError, UnicodeDecodeError, ValueError) as e:
            erreurs = [f"{texte.name} : illisible ({e})"]
        else:
            erreurs = valider_entete_nuage(entete, len(octets))
            if not erreurs:
                return octets, entete, modifie
        time.sleep(0.05 * (essai + 1))           # réécrit à l'instant : on relit
    raise ErreurAtelier(422, "Le nuage 3D est illisible : refaites-le (g1-scan traiter --refaire, puis « Utiliser "
                             "cette carte »).", erreurs)


def _etag(entete, octets, modifie):
    return f'"nuage-{int(modifie * 1000)}-{len(octets)}-{entete["points"]}"'


def reponse_binaire(request, octets, entete, modifie):
    """Réponse binaire d'un nuage : en-têtes X-Nuage-*, ETag ; 304 si le navigateur l'a déjà."""
    etag = _etag(entete, octets, modifie)
    entetes = dict(entetes_http_nuage(entete), ETag=etag)
    entetes["Cache-Control"] = SANS_CACHE
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=entetes)
    return Response(octets, media_type=TYPE_BINAIRE, headers=entetes)


def _source(source):
    source = (source or "scan").strip()
    if source not in SOURCES_ETAGE:
        raise ErreurAtelier(400, f"Source de nuage « {source} » inconnue : scan (le nuage du scan adopté) ou "
                                 "unitree (la carte d'Unitree).")
    return source


def _nuage_etage(id_lieu, etage, source):
    dossier = dossier_du_lieu(id_lieu)
    etage_du_lieu(dossier, etage)
    source = _source(source)
    lu = lire_nuage_fichiers(chemin_nuage(dossier, etage, source))
    if lu is None:
        detail = PAS_DE_NUAGE if source == "scan" else PAS_DE_CARTE_UNITREE.format(lieu=id_lieu, etage=etage)
        raise ErreurAtelier(404, detail)
    return dossier, source, lu


# ---------------------------------------------------------------- nuage d'un étage

@routeur.get("/api/lieux/{id_lieu}/etages/{etage}/nuage")
def nuage_etage(id_lieu: str, etage: str, request: Request, source: Optional[str] = None):
    """Nuage d'affichage de l'étage, en binaire."""
    _, _, (octets, entete, modifie) = _nuage_etage(id_lieu, etage, source)
    return reponse_binaire(request, octets, entete, modifie)


@routeur.get("/api/lieux/{id_lieu}/etages/{etage}/nuage/info")
def info_nuage_etage(id_lieu: str, etage: str, source: Optional[str] = None):
    """En-tête du nuage d'affichage de l'étage."""
    _, source, (octets, entete, modifie) = _nuage_etage(id_lieu, etage, source)
    url = f"/api/lieux/{id_lieu}/etages/{etage}/nuage" + ("?source=unitree" if source == "unitree" else "")
    return dict(entete, url=url, octets=len(octets), modifie=modifie)


@routeur.get("/api/lieux/{id_lieu}/etages/{etage}/monde/maillage")
def maillage(id_lieu: str, etage: str):
    """Maillage STL de la carte extrudée de l'étage."""
    dossier = dossier_du_lieu(id_lieu)
    etage_du_lieu(dossier, etage)
    sans = (f"L'étage « {etage} » n'a pas de carte extrudée : elle est faite pour un étage scanné, quand on clique "
            "sur « Utiliser cette carte » (ou g1-monde generer).")
    if not chemin_monde(dossier, etage).is_file():
        raise ErreurAtelier(404, sans)
    try:
        carte = charger_monde(dossier, etage).carte_extrudee
    except ErreurLieu as e:
        raise ErreurAtelier(422, f"Le fichier mondes/{etage}.monde.yaml est invalide : corrigez les points ci-dessous.",
                            e.erreurs) from None
    if carte is None:
        raise ErreurAtelier(404, sans)
    stl = chemin_maillage(dossier, etage).parent / carte.fichier
    try:
        octets = stl.read_bytes()
    except FileNotFoundError:
        raise ErreurAtelier(404, f"Le maillage mondes/{carte.fichier} manque : refaites-le avec g1-monde generer "
                                 f"--lieu {id_lieu} --etage {etage}.") from None
    return Response(octets, media_type=TYPE_STL,
                    headers={"Cache-Control": SANS_CACHE, "X-Maillage-Hauteur": f"{carte.hauteur:g}",
                             "Content-Disposition": f'inline; filename="{carte.fichier}"'})


# ---------------------------------------------------------------- nuage d'une session de scan

def _vrai(texte):
    return str(texte or "").strip().lower() in ("1", "true", "oui", "vrai", "yes")


def _nuage_session(request, lieu, session, apercu):
    """(dossier du lieu, id de session, base du nuage, aperçu ?) de la session visée : celle donnée,
    sinon la session active du lieu, sinon la plus récente. Pendant le scan, ou avec apercu=1 :
    l'aperçu en direct ; sinon le nuage traité."""
    from .scan import _lieu_par_defaut, _session_visee
    lieu = _lieu_par_defaut(request, lieu)
    dossier = dossier_du_lieu(lieu)
    ident = _session_visee(dossier, session)
    try:
        s = lire_session(dossier, ident)
    except ErreurLieu as e:
        raise ErreurAtelier(422, "Le fichier session.json de ce scan est illisible.", e.erreurs) from None
    if not _vrai(apercu) and s["etat"] in ETATS_ACTIFS and s["etat"] != "traitement":
        apercu = "1"                             # pendant le scan : l'aperçu en direct
    en_direct = _vrai(apercu)
    base = dossier_session(dossier, ident) / (APERCU_NUAGE if en_direct else NUAGE_AFFICHAGE)
    return dossier, s, base, en_direct


def _absent(s, en_direct):
    if en_direct:
        return ErreurAtelier(404, "Le nuage en direct de ce scan n'est pas encore prêt : il apparaît quelques "
                                  "secondes après le début du scan.")
    if s["etat"] in ETATS_ACTIFS:
        return ErreurAtelier(404, "Le nuage 3D de ce scan n'est pas encore prêt : attendez la fin du traitement.")
    return ErreurAtelier(404, "Ce scan n'a pas de nuage 3D (scan d'avant la vague 5, ou traitement en échec) : "
                              f"refaites son traitement (g1-scan traiter --lieu {s['lieu']} --session {s['id']} "
                              "--refaire).")


@routeur.get("/api/scan/nuage")
def nuage_session(request: Request, lieu: Optional[str] = None, session: Optional[str] = None,
                  apercu: Optional[str] = None):
    """Nuage d'affichage d'une session de scan (ou son aperçu en direct), en binaire."""
    _, s, base, en_direct = _nuage_session(request, lieu, session, apercu)
    lu = lire_nuage_fichiers(base)
    if lu is None:
        raise _absent(s, en_direct)
    return reponse_binaire(request, *lu)


@routeur.get("/api/scan/nuage/info")
def info_nuage_session(request: Request, lieu: Optional[str] = None, session: Optional[str] = None,
                       apercu: Optional[str] = None):
    """En-tête du nuage d'affichage d'une session de scan."""
    dossier, s, base, en_direct = _nuage_session(request, lieu, session, apercu)
    lu = lire_nuage_fichiers(base)
    if lu is None:
        raise _absent(s, en_direct)
    octets, entete, modifie = lu
    url = f"/api/scan/nuage?lieu={dossier.name}&session={s['id']}" + ("&apercu=1" if en_direct else "")
    return dict(entete, url=url, octets=len(octets), modifie=modifie, apercu=en_direct)
