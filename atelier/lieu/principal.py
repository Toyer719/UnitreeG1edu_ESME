"""Le point principal d'un lieu (vague 4, section 11.2 du plan) : accueil, départ, repérage, retour.

Une salle de salles.yaml, et une seule, porte l'étiquette « principal » (ETIQUETTE_PRINCIPAL) :
  - c'est l'accueil, où le robot attend les visiteurs et revient seul après chaque visite ;
  - au démarrage du vrai robot, on le pose dessus, dans le sens de sa flèche (theta), et
    « Repérer le robot » part de cette pose (POST /api/robot/reperer sans pose) ;
  - c'est le départ du robot en simulation : depart_robot du monde de son étage a la même pose.
Sa pose est recopiée dans accueil de lieu.yaml (champ inchangé depuis la vague 1).

Lieux d'avant la vague 4 (demo, demo_scan, bomboclat) : sans étiquette, le point principal est la
salle « accueil » (principal implicite) ; verifier_lieu le signale par un avertissement, et
« g1-lieu migrer » pose l'étiquette, avec une sauvegarde. lieux/demo, la référence des tests,
n'est jamais migré.

Fichier de l'agent Point principal (vague 4). Les fonctions marquées « contrat » sont livrées et
testées par l'intégrateur (atelier/tests/test_contrats_vague4.py) : elles gardent leur nom, leurs
arguments et leur comportement. Les autres sont à écrire par l'agent (NotImplementedError d'ici là).
"""
from .fichiers import (ErreurLieu, charger_fiche, charger_monde, charger_salles, chemin_monde,
                       dossier_lieu)
from .modeles import ETIQUETTE_PRINCIPAL, Lieu, Pose, PoseEtage
from .robot import marque_au_sol

DOSSIER_SAUVEGARDES = "sauvegardes"      # lieux/<id>/sauvegardes/AAAA-MM-JJ_HHhMM_<raison>/
ID_PRINCIPAL_IMPLICITE = "accueil"       # principal d'un lieu d'avant la vague 4
MOT_PRINCIPAL = "principal"              # cible de /guide/aller qui désigne le point principal


def _salles(lieu):
    return list(lieu.salles) if isinstance(lieu, Lieu) else charger_salles(lieu)


def _fiche(lieu):
    return lieu if isinstance(lieu, Lieu) else charger_fiche(lieu)


# ---------------------------------------------------------------- contrat (livré par l'intégrateur)

def salles_principales(lieu):
    """Contrat. Salles qui portent l'étiquette « principal » (0, 1, ou plus si le lieu est faux)."""
    return [s for s in _salles(lieu) if ETIQUETTE_PRINCIPAL in s.etiquettes]


def point_principal(lieu):
    """Contrat. La salle du point principal : celle qui porte l'étiquette ; à défaut (lieu d'avant
    la vague 4), la salle « accueil » ; None s'il n'y en a pas, ou s'il y en a plusieurs (lieu faux,
    signalé par la validation). lieu : Lieu chargé, id ou dossier."""
    salles = _salles(lieu)
    marquees = [s for s in salles if ETIQUETTE_PRINCIPAL in s.etiquettes]
    if len(marquees) == 1:
        return marquees[0]
    if marquees:
        return None
    return next((s for s in salles if s.id == ID_PRINCIPAL_IMPLICITE), None)


def principal_explicite(lieu):
    """Contrat. Vrai si une salle porte l'étiquette (lieu migré ou créé en vague 4)."""
    return len(salles_principales(lieu)) == 1


def pose_principale(lieu):
    """Contrat. PoseEtage du point principal (étage, x, y, theta), ou None sans point principal."""
    s = point_principal(lieu)
    return None if s is None else PoseEtage(s.etage, s.pose.x, s.pose.y, s.pose.theta)


def pose_de_reperage(lieu, etage):
    """Contrat. Pose (repère map de l'étage) où l'on pose le robot avant « Repérer le robot » :
    celle du point principal s'il est sur cet étage, sinon la marque au sol (origine de la carte
    d'Unitree, atelier.lieu.robot.marque_au_sol). C'est la pose par défaut de /api/robot/reperer."""
    p = pose_principale(lieu)
    if p is not None and p.etage == etage:
        return Pose(p.x, p.y, p.theta)
    return marque_au_sol(lieu if not isinstance(lieu, Lieu) else lieu.dossier, etage)


def depart_simulation(lieu, etage):
    """Contrat. Pose de départ du robot dans la simulation de cet étage : le point principal s'il
    est sur cet étage (depart_robot doit alors être le même, synchroniser_depart), sinon depart_robot
    du monde ; None si l'étage n'a pas de monde."""
    p = pose_principale(lieu)
    if p is not None and p.etage == etage:
        return Pose(p.x, p.y, p.theta)
    dossier = lieu.dossier if isinstance(lieu, Lieu) else lieu
    if not chemin_monde(dossier, etage).is_file():
        return None
    d = charger_monde(dossier, etage).depart_robot
    return Pose(d.x, d.y, d.theta)


def accueil_conforme(lieu):
    """Contrat. Vrai si accueil de lieu.yaml a la pose du point principal (à 1 mm et 1 mrad près)."""
    p, a = pose_principale(lieu), _fiche(lieu).accueil
    return (p is not None and p.etage == a.etage and abs(p.x - a.x) <= 1e-3 and abs(p.y - a.y) <= 1e-3
            and abs(p.theta - a.theta) <= 1e-3)


# ---------------------------------------------------------------- à écrire par l'agent Point principal

def definir_principal(lieu, salle=None, x=None, y=None, theta=None):
    """Fait de « salle » le point principal (étiquette déplacée) et/ou change sa pose (x et y
    ensemble, theta seul possible). Écrit, tout ou rien : salles.yaml, le nœud de même id
    (itineraires.yaml), accueil de lieu.yaml et depart_robot du monde de son étage. Renvoie
    {"principal": {...}, "enregistre": [fichiers], "rapport": {...}}. ErreurLieu (en français) sinon."""
    raise NotImplementedError("definir_principal : à écrire par l'agent Point principal (section 11.2 du plan)")


def synchroniser_depart(lieu):
    """Recopie la pose du point principal dans depart_robot du monde de son étage (s'il existe).
    Renvoie True si le fichier a changé."""
    raise NotImplementedError("synchroniser_depart : à écrire par l'agent Point principal (section 11.2 du plan)")


def sauvegarder_lieu(lieu, raison):
    """Copie lieu.yaml, salles.yaml, itineraires.yaml et mondes/*.monde.yaml dans
    lieux/<id>/sauvegardes/AAAA-MM-JJ_HHhMM_<raison>/ (suffixe -2, -3… si besoin). Renvoie le dossier."""
    raise NotImplementedError("sauvegarder_lieu : à écrire par l'agent Point principal (section 11.2 du plan)")


def migrer_lieu(lieu, depuis_depart=False, a_blanc=False):
    """« g1-lieu migrer » : sauvegarde, puis étiquette « principal » sur la salle accueil (ou, avec
    depuis_depart, le principal prend la pose depart_robot de son étage), accueil, nœud et depart_robot
    alignés. Idempotent ; a_blanc : rien n'est écrit. Renvoie le rapport {sauvegarde, changements,
    avertissements}. Refuse lieux/demo (référence des tests)."""
    raise NotImplementedError("migrer_lieu : à écrire par l'agent Point principal (section 11.2 du plan)")


__all__ = ["DOSSIER_SAUVEGARDES", "ETIQUETTE_PRINCIPAL", "ID_PRINCIPAL_IMPLICITE", "MOT_PRINCIPAL",
           "accueil_conforme", "definir_principal", "depart_simulation", "dossier_lieu", "migrer_lieu",
           "point_principal", "pose_de_reperage", "pose_principale", "principal_explicite", "salles_principales",
           "sauvegarder_lieu", "synchroniser_depart", "ErreurLieu"]
