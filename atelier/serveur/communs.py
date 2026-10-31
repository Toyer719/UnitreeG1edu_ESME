"""Outils communs aux routes du serveur : erreurs en français, dossier d'un lieu, image PNG.

Toutes les erreurs renvoyées à l'interface ont la même forme JSON :
  {"detail": "phrase qui dit quoi faire", "erreurs": [...], "sortie": "..."}
erreurs (liste de messages d'atelier.lieu) et sortie (texte d'une commande) sont facultatifs.
"""
import struct
import zlib

import numpy as np

import atelier
from atelier.lieu import ErreurLieu, Rapport, charger_fiche, valider_lieu
from atelier.lieu.fichiers import FICHE


class ErreurAtelier(Exception):
    """Erreur à montrer à l'utilisateur : code HTTP, phrase, et détails facultatifs."""

    def __init__(self, statut, detail, erreurs=None, sortie=None):
        super().__init__(detail)
        self.statut = statut
        self.detail = detail
        self.erreurs = list(erreurs or [])
        self.sortie = sortie

    def vers_dict(self):
        d = {"detail": self.detail}
        if self.erreurs:
            d["erreurs"] = self.erreurs
        if self.sortie is not None:
            d["sortie"] = self.sortie
        return d


def verifier_id(texte, quoi="identifiant"):
    """Refuse un identifiant mal formé (et donc tout chemin du type « ../ »)."""
    if not isinstance(texte, str) or not atelier.MOTIF_ID.match(texte):
        raise ErreurAtelier(400, f"« {texte} » n'est pas un {quoi} valable : utilisez de 1 à 40 lettres "
                                 "minuscules sans accent, chiffres, « _ » ou « - », en commençant par une "
                                 "lettre ou un chiffre (ex. lycee_nord)")
    return texte


def dossier_du_lieu(id_lieu):
    """Dossier d'un lieu existant de $ATELIER_LIEUX, à partir de son id. Sinon 400 ou 404."""
    verifier_id(id_lieu, "identifiant de lieu")
    dossier = atelier.chemin_lieu(id_lieu)
    if not (dossier / FICHE).is_file():
        raise ErreurAtelier(404, f"Le lieu « {id_lieu} » n'existe pas. Choisissez-en un sur l'accueil de "
                                 "l'Atelier (⌂), ou créez-le.")
    return dossier


def fiche_du_lieu(dossier):
    """lieu.yaml du dossier (objet Lieu sans les autres fichiers). 422 s'il est invalide."""
    try:
        return charger_fiche(dossier)
    except ErreurLieu as e:
        raise ErreurAtelier(422, f"Le fichier lieu.yaml du lieu « {dossier.name} » est invalide : "
                                 "corrigez les points ci-dessous.", e.erreurs) from None


def etage_du_lieu(dossier, etage):
    """(fiche, étage) : 404 si l'étage n'existe pas dans lieu.yaml."""
    fiche = fiche_du_lieu(dossier)
    trouve = fiche.etage(etage)
    if trouve is None:
        connus = ", ".join(e.id for e in fiche.etages) or "aucun"
        raise ErreurAtelier(404, f"L'étage « {etage} » n'existe pas dans le lieu « {dossier.name} » "
                                 f"(étages : {connus}).")
    return fiche, trouve


def exiger_point_principal(dossier):
    """Vague 4 (section 11.2 du plan) : 409 si le lieu n'a pas de point principal (ni salle étiquetée
    « principal », ni salle « accueil », ou deux principaux) ; 422 si salles.yaml est illisible. Appelé
    avant de lancer la simulation, la répétition ou le robot sur un lieu."""
    from atelier.lieu.principal import point_principal
    try:
        principal = point_principal(dossier)
    except ErreurLieu as e:
        raise ErreurAtelier(422, "Le fichier salles.yaml est invalide : corrigez les points ci-dessous.",
                            e.erreurs) from None
    if principal is None:
        raise ErreurAtelier(409, "Ce lieu n'a pas de point principal (l'accueil, où le robot démarre et revient "
                                 "après chaque visite) : posez-le dans Placer › Accueil.")
    return principal


def erreur_validation(fichier, erreurs):
    """ErreurAtelier 422 pour un fichier refusé par la validation."""
    return ErreurAtelier(422, f"{fichier} n'a pas été enregistré : corrigez les points ci-dessous.", erreurs)


def rapport_json(rapport: Rapport):
    return {"ok": rapport.ok, "erreurs": list(rapport.erreurs), "avertissements": list(rapport.avertissements)}


def rapport_du_lieu(dossier):
    """Vérification de tout le lieu (règles entre fichiers), sans jamais lever d'exception."""
    try:
        return rapport_json(valider_lieu(dossier))
    except Exception as e:      # noqa: BLE001 : le rapport ne doit pas empêcher l'enregistrement
        return {"ok": False, "erreurs": [f"vérification impossible : {e}"], "avertissements": []}


# ---------------------------------------------------------------- image PNG

def _bloc_png(genre, donnees):
    return (struct.pack(">I", len(donnees)) + genre + donnees
            + struct.pack(">I", zlib.crc32(genre + donnees) & 0xFFFFFFFF))


def png_gris(image):
    """Image numpy (hauteur, largeur) en niveaux de gris → octets d'un fichier PNG 8 bits.
    image[0] est la ligne du haut, comme dans le PGM : rien n'est retourné."""
    image = np.asarray(image)
    if image.dtype != np.uint8:
        maxi = max(int(image.max()), 1) if image.size else 1
        image = (image.astype(np.float64) * 255.0 / maxi).astype(np.uint8)
    hauteur, largeur = image.shape
    lignes = np.hstack([np.zeros((hauteur, 1), dtype=np.uint8), image])   # filtre 0 à chaque ligne
    entete = struct.pack(">IIBBBBB", largeur, hauteur, 8, 0, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + _bloc_png(b"IHDR", entete)
            + _bloc_png(b"IDAT", zlib.compress(lignes.tobytes(), 6)) + _bloc_png(b"IEND", b""))


# ---------------------------------------------------------------- squelettes (vague 5)

def pas_encore_fait(quoi, agent, section):
    """ErreurAtelier 501 d'une route livrée vide par l'agent Contrats (vague 5), tant que son agent
    ne l'a pas écrite : pas_encore_fait("le nuage 3D d'un étage", "Scan", "12.4")."""
    return ErreurAtelier(501, f"Pas encore fait : {quoi} (vague 5, agent {agent}, section {section} du plan).")
