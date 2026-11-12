"""Routes du monde inventé et de la carte 2D d'un étage.

  GET  /api/lieux/{id}/etages/{e}/monde            mondes/<e>.monde.yaml, en JSON
  PUT  /api/lieux/{id}/etages/{e}/monde            l'enregistre (validé par atelier.lieu)
  POST /api/lieux/{id}/etages/{e}/monde/generer    g1-monde generer : .sdf, carte, masque ; étage scanné
                                                   (vague 5) : la carte extrudée, mondes/<e>_carte.stl
  (le maillage lui-même : GET …/monde/maillage, dans routes/nuage.py)
  GET  /api/lieux/{id}/etages/{e}/carte.png        la carte .pgm convertie en PNG
  GET  /api/lieux/{id}/etages/{e}/carte.yaml       le .yaml de la carte, en JSON, avec la taille
                                                   de l'image et ses bornes en mètres (Leaflet)
"""
from typing import Any

from fastapi import APIRouter, Body
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response

from atelier.lieu import (ErreurLieu, Monde, bornes_carte, charger_carte, charger_fiche, charger_info_carte,
                          charger_monde, chemin_carte, chemin_interdit, chemin_maillage, chemin_monde, chemin_sdf,
                          enregistrer_monde, valider_donnees)

from ..communs import (ErreurAtelier, dossier_du_lieu, erreur_validation, etage_du_lieu, png_gris,
                       rapport_du_lieu)
from ..processus import CommandeAbsente, lancer_et_attendre

routeur = APIRouter(prefix="/api/lieux/{id_lieu}/etages/{etage}", tags=["monde et carte"])

DELAI_GENERATION = 300.0     # s : au-delà, la fabrication de la carte est arrêtée
SANS_CACHE = {"Cache-Control": "no-store"}


def _fichier_monde(etage):
    return f"mondes/{etage}.monde.yaml"


@routeur.get("/monde")
def lire_monde(id_lieu: str, etage: str):
    dossier = dossier_du_lieu(id_lieu)
    etage_du_lieu(dossier, etage)
    if not chemin_monde(dossier, etage).is_file():
        raise ErreurAtelier(404, f"L'étage « {etage} » n'a pas encore de monde inventé : dessinez-le "
                                 "(Simulation › Dessiner), puis enregistrez.")
    try:
        return charger_monde(dossier, etage).vers_dict()
    except ErreurLieu as e:
        raise ErreurAtelier(422, f"Le fichier {_fichier_monde(etage)} est invalide : corrigez les points "
                                 "ci-dessous.", e.erreurs) from None


@routeur.put("/monde")
def ecrire_monde(id_lieu: str, etage: str, donnees: Any = Body(...)):
    dossier = dossier_du_lieu(id_lieu)
    etage_du_lieu(dossier, etage)
    fichier = _fichier_monde(etage)
    erreurs = valider_donnees("monde", donnees, fichier)
    if erreurs:
        raise erreur_validation(fichier, erreurs)
    try:
        enregistrer_monde(dossier, etage, Monde.depuis_dict(donnees))
    except ErreurLieu as e:
        raise erreur_validation(fichier, e.erreurs) from None
    return {"enregistre": [fichier], "rapport": rapport_du_lieu(dossier)}


def _fichiers_generes(dossier, etage):
    """Fichiers écrits par generer. Un étage scanné (vague 5) a en plus « maillage » (mondes/<e>_carte.stl) ;
    pour un monde dessiné, la réponse reste celle d'avant (sdf, carte, interdit)."""
    fichiers = {"sdf": chemin_sdf(dossier, etage).is_file(), "carte": chemin_carte(dossier, etage).is_file(),
                "interdit": chemin_interdit(dossier, etage).is_file()}
    if _etage_scanne(dossier, etage):
        fichiers["maillage"] = chemin_maillage(dossier, etage).is_file()
    return fichiers


def _etage_scanne(dossier, etage):
    """Vrai si l'étage utilise la carte d'un scan et l'a déjà (generer en tire alors le monde, vague 5)."""
    try:
        e = charger_fiche(dossier).etage(etage)
    except ErreurLieu:
        return False
    return e is not None and e.source_carte == "scan" and chemin_carte(dossier, etage).is_file()


@routeur.post("/monde/generer")
async def generer(id_lieu: str, etage: str):
    dossier = dossier_du_lieu(id_lieu)
    etage_du_lieu(dossier, etage)
    if not chemin_monde(dossier, etage).is_file() and not _etage_scanne(dossier, etage):
        raise ErreurAtelier(409, "Il n'y a pas encore de monde pour cet étage : dessinez-le (Simulation › "
                                 "Dessiner), puis enregistrez : la carte se fait seule.")
    try:
        resultat = await run_in_threadpool(
            lancer_et_attendre, "g1-monde", ["generer", "--lieu", dossier, "--etage", etage], DELAI_GENERATION)
    except CommandeAbsente as e:
        raise ErreurAtelier(503, f"Impossible de fabriquer la carte : {e}. Elle est livrée par l'agent "
                                 "Monde (bin/g1-monde).") from None
    if resultat["code"] != 0:
        raison = ("elle a été arrêtée car trop longue" if resultat["code"] is None
                  else f"code de sortie {resultat['code']}")
        raise ErreurAtelier(422, f"La fabrication de la carte a échoué ({raison}) : lisez le message de "
                                 "g1-monde ci-dessous, corrigez le monde, puis recommencez.",
                            sortie=resultat["sortie"])
    return {"ok": True, "sortie": resultat["sortie"], "duree_s": resultat["duree_s"],
            "fichiers": _fichiers_generes(dossier, etage), "rapport": rapport_du_lieu(dossier)}


def _pas_de_carte(etage):
    return ErreurAtelier(404, f"L'étage « {etage} » n'a pas encore de carte : dessinez le monde (Simulation › "
                              "Dessiner) puis enregistrez, ou scannez l'étage (Réel › Scanner).")


@routeur.get("/carte.png")
def carte_png(id_lieu: str, etage: str):
    dossier = dossier_du_lieu(id_lieu)
    etage_du_lieu(dossier, etage)
    chemin = chemin_carte(dossier, etage)
    if not chemin.is_file():
        raise _pas_de_carte(etage)
    try:
        _, image = charger_carte(chemin)
    except ErreurLieu as e:
        raise ErreurAtelier(422, "La carte est illisible : fabriquez-la à nouveau.", e.erreurs) from None
    return Response(png_gris(image), media_type="image/png", headers=SANS_CACHE)


@routeur.get("/carte.yaml")
def carte_yaml(id_lieu: str, etage: str):
    dossier = dossier_du_lieu(id_lieu)
    etage_du_lieu(dossier, etage)
    chemin = chemin_carte(dossier, etage)
    if not chemin.is_file():
        raise _pas_de_carte(etage)
    try:
        info = charger_info_carte(chemin)
    except ErreurLieu as e:
        raise ErreurAtelier(422, "Le fichier de la carte est invalide : fabriquez-la à nouveau.",
                            e.erreurs) from None
    xmin, ymin, xmax, ymax = bornes_carte(info)
    return dict(info.vers_dict(), largeur=info.largeur, hauteur=info.hauteur,
                bornes={"xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax},
                modifiee=chemin.stat().st_mtime)
