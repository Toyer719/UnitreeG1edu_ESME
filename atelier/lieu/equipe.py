"""Les emplacements de l'équipe (vague 4, section 11.6 du plan) : fichiers du lieu et sujets ROS 2.

L'équipe de l'utilisateur fait la caméra See3CAM, le chatbot à règles et les modes de personnalité.
L'Atelier leur prépare :
  - trois fichiers facultatifs du lieu, avec leurs schémas : personnalites.yaml, dialogues.yaml et
    camera.yaml (exemples : atelier/lieu/exemples/) ; charger_equipe, enregistrer_equipe et
    valider_equipe les lisent, les écrivent (atomique, validé) et les vérifient ;
  - des sujets ROS 2 entre les parties (SUJETS_EQUIPE) : ce que dit le visiteur, les visiteurs vus
    par la caméra, la personnalité active, les phrases à dire, et la demande de guidage.

Fichier de l'agent Équipe (vague 4). Les fonctions et valeurs marquées « contrat » sont livrées et
testées par l'intégrateur (atelier/tests/test_contrats_vague4.py) : elles gardent leur nom, leurs
arguments et leur comportement.
"""
from pathlib import Path

from .fichiers import ErreurLieu, charger_fichier, dossier_lieu, ecrire_yaml, lire_yaml
from .validation import valider_donnees

# ---------------------------------------------------------------- valeurs du contrat

FICHIERS_EQUIPE = {"personnalites": "personnalites.yaml", "dialogues": "dialogues.yaml", "camera": "camera.yaml"}
DOSSIER_EXEMPLES = Path(__file__).resolve().parent / "exemples"
ENTETES_EQUIPE = {
    "personnalites": "Modes de personnalité du robot. Format : atelier/lieu/schemas/personnalites.schema.json.",
    "dialogues": "Chatbot à règles du lieu. Format : atelier/lieu/schemas/dialogues.schema.json.",
    "camera": "Caméra du robot et détection des visiteurs. Format : atelier/lieu/schemas/camera.schema.json.",
}
ACTIONS_DIALOGUE = ("guider", "dire", "personnalite", "stop")

# Sujets ROS 2 entre les parties (section 11.6) : sujet → (type, schéma JSON ou None, qui publie)
SUJETS_EQUIPE = {
    "/visiteur/texte": ("std_msgs/String", None, "reconnaissance vocale de l'équipe (texte brut, en français)"),
    "/visiteurs/detectes": ("std_msgs/String", "personnes", "caméra de l'équipe (camera.yaml)"),
    "/personnalite/active": ("std_msgs/String", "personnalite_active", "gestion des personnalités (fiable, transient_local)"),
    "/robot/dire": ("std_msgs/String", "robot_dire", "chatbot, relais des événements du guide, chorégraphies"),
    "/guide/aller": ("std_msgs/String", "demande_guide", "chatbot (JSON {cible, accompagner, source})"),
    "/guide/evenement": ("std_msgs/String", "evenement_guide", "guide (relayé vers /robot/dire)"),
}

EXEMPLE_ROBOT_DIRE = {"version": 1, "texte": "Je vous emmène à la Salle B204. Suivez-moi !", "source": "dialogue",
                      "priorite": "normale"}
EXEMPLE_PERSONNALITE_ACTIVE = {"version": 1, "id": "accueillant", "nom": "Accueillant", "lieu": "demo"}


# ---------------------------------------------------------------- contrat (livré par l'intégrateur)

def _quoi(quoi):
    if quoi not in FICHIERS_EQUIPE:
        raise ValueError(f"fichier de l'équipe inconnu : {quoi} ({', '.join(FICHIERS_EQUIPE)})")
    return quoi


def chemin_equipe(lieu, quoi):
    """Contrat. lieux/<id>/<quoi>.yaml (quoi : personnalites, dialogues ou camera)."""
    return dossier_lieu(lieu) / FICHIERS_EQUIPE[_quoi(quoi)]


def exemple_equipe(quoi):
    """Contrat. Contenu de l'exemple livré (atelier/lieu/exemples/<quoi>.yaml), déjà vérifié."""
    chemin = DOSSIER_EXEMPLES / FICHIERS_EQUIPE[_quoi(quoi)]
    return lire_yaml(chemin.read_text(encoding="utf-8"), chemin.name)


def valider_equipe(quoi, donnees, fichier=None):
    """Contrat. Erreurs (en français) d'un fichier de l'équipe : schéma, puis règles. [] si tout va bien."""
    return valider_donnees(_quoi(quoi), donnees, fichier or FICHIERS_EQUIPE[quoi])


def charger_equipe(lieu, quoi):
    """Contrat. Contenu du fichier de l'équipe du lieu, vérifié ; None s'il n'existe pas (le lieu
    s'en passe). ErreurLieu s'il est faux."""
    chemin = chemin_equipe(lieu, quoi)
    if not chemin.is_file():
        return None
    return charger_fichier(chemin, quoi)


def enregistrer_equipe(lieu, quoi, donnees):
    """Contrat. Écrit le fichier de l'équipe (atomique) après l'avoir vérifié. ErreurLieu sinon.
    Renvoie le chemin."""
    erreurs = valider_equipe(quoi, donnees)
    if erreurs:
        raise ErreurLieu(erreurs)
    chemin = chemin_equipe(lieu, quoi)
    ecrire_yaml(chemin, donnees, ENTETES_EQUIPE[quoi])
    return chemin


__all__ = ["ACTIONS_DIALOGUE", "DOSSIER_EXEMPLES", "ENTETES_EQUIPE", "EXEMPLE_PERSONNALITE_ACTIVE",
           "EXEMPLE_ROBOT_DIRE", "FICHIERS_EQUIPE", "SUJETS_EQUIPE", "charger_equipe", "chemin_equipe",
           "enregistrer_equipe", "exemple_equipe", "valider_equipe"]
