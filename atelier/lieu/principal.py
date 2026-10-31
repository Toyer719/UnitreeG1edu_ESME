"""Le point principal d'un lieu (vague 4, section 11.2 du plan) : accueil, départ, repérage, retour.

Une salle de salles.yaml, et une seule, porte l'étiquette « principal » (ETIQUETTE_PRINCIPAL) :
  - c'est l'accueil, où le robot attend les visiteurs et revient seul après chaque visite ;
  - au démarrage du vrai robot, on le pose dessus, dans le sens de sa flèche (theta), et
    « Repérer le robot » part de cette pose (POST /api/robot/reperer sans pose) ;
  - c'est le départ du robot en simulation : depart_robot du monde de son étage a la même pose.
Sa pose est recopiée dans accueil de lieu.yaml (champ inchangé depuis la vague 1).

Lieux d'avant la vague 4 (demo, demo_scan, bomboclat) : sans étiquette, le point principal est la
salle « accueil » (principal implicite), sans avertissement ; « g1-lieu migrer » pose l'étiquette,
avec une sauvegarde. lieux/demo, la référence des tests, n'est jamais migré.

Écritures (agent Point principal) : definir_principal, ecrire_salles (PUT …/salles), synchroniser_depart
et migrer_lieu passent toutes par le même chemin :
  - elles chargent les fichiers touchés (lieu.yaml, salles.yaml, itineraires.yaml, le monde de l'étage
    du principal), les modifient en mémoire, puis n'écrivent que les fichiers qui ont changé ;
  - tout ou rien : chaque fichier est validé avant d'en écrire un seul, et si une écriture échoue,
    ceux déjà écrits reprennent leur contenu d'avant ;
  - dans lieu.yaml et le monde, seule la ligne « accueil: {...} » ou « depart_robot: {...} » est
    remplacée quand c'est possible : les commentaires écrits à la main restent ;
  - depart_robot n'entre ni dans le monde Gazebo (.sdf) ni dans la carte : s'ils étaient à jour avant,
    ils le restent (leur date est avancée), et ni g1-lieu valider ni g1-monde simuler ne demandent de
    les refabriquer pour un point principal déplacé.

Fichier de l'agent Point principal (vague 4). Les fonctions marquées « contrat » sont livrées et
testées par l'intégrateur (atelier/tests/test_contrats_vague4.py) : elles gardent leur nom, leurs
arguments et leur comportement.
"""
import copy
import math
import numbers
import os
import re
import shutil
import threading
from datetime import datetime

import yaml

import atelier
from .conversions import carte_vers_unitree
from .fichiers import (ENTETES, FICHE, ITINERAIRES, SALLES, ErreurLieu, charger_fiche, charger_itineraires,
                       charger_monde, charger_salles, chemin_carte, chemin_monde, chemin_sdf, dossier_lieu,
                       ecrire_atomique, lire_yaml, texte_yaml)
from .modeles import ETIQUETTE_PRINCIPAL, Itineraires, Lieu, Monde, Noeud, Pose, PoseEtage, Salle
from .robot import marque_au_sol, repere_unitree
from .validation import valider_donnees

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


# ---------------------------------------------------------------- agent Point principal

REFERENCE_DES_TESTS = atelier.RACINE / "lieux" / "demo"   # jamais migré, jamais adopté (section 11.10)
RAISON_MIGRATION = "migration"
DECIMALES = 6             # x, y et theta écrits au micromètre et au microradian près
EGAL = 1e-9               # en deçà, deux valeurs sont la même (pas de réécriture)
TOLERANCE_SYNCHRO = 1e-3  # m et rad : depart_robot « sur » le principal, comme verifier_lieu
FICHIERS_SAUVEGARDES = (FICHE, SALLES, ITINERAIRES)       # plus mondes/*.monde.yaml
LISEZMOI_SAUVEGARDE = "LISEZMOI.txt"

_VERROU = threading.RLock()     # deux écritures du même processus (serveur) ne se mélangent pas

SANS_PRINCIPAL = (f"le lieu n'a pas de point principal : donnez l'étiquette « {ETIQUETTE_PRINCIPAL} » à la salle "
                  "où le robot accueille les visiteurs (Placer › Accueil, ou « Faire de cette salle l'accueil »)")


class SalleInconnue(ErreurLieu):
    """La salle demandée n'est pas dans salles.yaml (l'API répond 404)."""


class PerteDuPrincipal(ErreurLieu):
    """La nouvelle liste des salles n'a plus de point principal (l'API répond 422)."""


def est_reference_des_tests(lieu):
    """Vrai si lieu désigne lieux/demo du dépôt, la référence des tests (on n'y écrit jamais)."""
    try:
        return dossier_lieu(lieu).resolve() == REFERENCE_DES_TESTS.resolve()
    except (OSError, ValueError, RuntimeError):
        return False


def _mesure(v, nom):
    """x ou y donné par l'utilisateur : un nombre fini, arrondi au micromètre."""
    if isinstance(v, bool) or not isinstance(v, numbers.Real) or not math.isfinite(v):
        raise ErreurLieu(f"{nom} doit être un nombre fini, en mètres (repère de la carte), pas {v!r}")
    return round(float(v), DECIMALES)


def _angle(v):
    """theta donné par l'utilisateur, en radians : ramené entre -π et π (au microradian)."""
    if isinstance(v, bool) or not isinstance(v, numbers.Real) or not math.isfinite(v):
        raise ErreurLieu(f"theta doit être un nombre fini, en radians, pas {v!r}")
    v = float(v)
    if abs(v) > 2 * math.pi + 1e-9:
        raise ErreurLieu(f"theta vaut {v:g} : c'est un angle en radians, entre -2π et 2π "
                         "(par exemple 1.5708 pour un quart de tour vers la gauche)")
    if not -math.pi < v <= math.pi:
        v = math.remainder(v, 2 * math.pi)
    return round(v, DECIMALES)


def _differe(a, b):
    return abs(float(a) - float(b)) > EGAL


def _pose_differe(p, x, y, theta=None):
    return _differe(p.x, x) or _differe(p.y, y) or (theta is not None and _differe(p.theta, theta))


def _seules(salles):
    """Un Lieu en mémoire qui ne porte que ces salles, pour les fonctions du contrat (qui attendent un
    lieu, pas une liste)."""
    return Lieu("", [], PoseEtage("", 0.0, 0.0, 0.0), salles=list(salles))


def _pose_dict(p, theta=True):
    if p is None:
        return None
    d = {"x": p.x, "y": p.y}
    if theta:
        d["theta"] = p.theta
    if hasattr(p, "etage"):
        d = {"etage": p.etage, **d}
    return d


# ---------------------------------------------------------------- lecture

def _charger(dossier, salles=True):
    """Lieu partiel : lieu.yaml, salles.yaml (si salles) et itineraires.yaml, validés. Les mondes se
    chargent à la demande (_monde). ErreurLieu avec toutes les erreurs de ces fichiers."""
    erreurs = []

    def essayer(fonction, defaut=None):
        try:
            return fonction(dossier)
        except ErreurLieu as e:
            erreurs.extend(e.erreurs)
            return defaut

    if not (dossier / FICHE).is_file():
        raise ErreurLieu(f"{dossier} : pas de lieu.yaml, ce dossier n'est pas un lieu")
    lieu = essayer(charger_fiche)
    liste = essayer(charger_salles, []) if salles else []
    itineraires = essayer(charger_itineraires, Itineraires())
    if erreurs:
        raise ErreurLieu(erreurs)
    lieu.salles, lieu.itineraires, lieu.mondes = liste, itineraires, {}
    return lieu


def _monde(lieu, etage):
    """Le monde de l'étage (chargé une fois dans lieu.mondes), ou None si l'étage n'en a pas."""
    if etage not in lieu.mondes:
        if not chemin_monde(lieu.dossier, etage).is_file():
            return None
        lieu.mondes[etage] = charger_monde(lieu.dossier, etage)
    return lieu.mondes[etage]


# ---------------------------------------------------------------- modifications en mémoire

def _aligner(lieu, salle, pose, etiqueter):
    """La salle (objet de lieu.salles) prend la pose ; le nœud de même id, accueil de lieu.yaml et
    depart_robot du monde de son étage s'alignent sur elle. etiqueter : l'étiquette « principal » va
    à cette salle, et à elle seule. Une valeur déjà égale n'est pas remplacée (rien à réécrire)."""
    if etiqueter:
        for s in lieu.salles:
            if s is salle:
                if ETIQUETTE_PRINCIPAL not in s.etiquettes:
                    s.etiquettes = [ETIQUETTE_PRINCIPAL] + list(s.etiquettes)
            elif ETIQUETTE_PRINCIPAL in s.etiquettes:
                s.etiquettes = [e for e in s.etiquettes if e != ETIQUETTE_PRINCIPAL]
    if _pose_differe(salle.pose, pose.x, pose.y, pose.theta):
        salle.pose = Pose(pose.x, pose.y, pose.theta)
    x, y, theta = salle.pose.x, salle.pose.y, salle.pose.theta
    n = lieu.itineraires.noeuds.get(salle.id)
    if n is None or n.etage != salle.etage or _pose_differe(n, x, y):
        lieu.itineraires.noeuds[salle.id] = Noeud(salle.etage, x, y)
    a = lieu.accueil
    if a.etage != salle.etage or _pose_differe(a, x, y, theta):
        lieu.accueil = PoseEtage(salle.etage, x, y, theta)
    monde = _monde(lieu, salle.etage)
    if monde is not None and _pose_differe(monde.depart_robot, x, y, theta):
        monde.depart_robot = Pose(x, y, theta)


def _noeuds_des_salles(lieu):
    """Chaque salle a son nœud de même id, à sa position (PUT …/salles?synchroniser=true)."""
    for s in lieu.salles:
        n = lieu.itineraires.noeuds.get(s.id)
        if n is None or n.etage != s.etage or _pose_differe(n, s.pose.x, s.pose.y):
            lieu.itineraires.noeuds[s.id] = Noeud(s.etage, s.pose.x, s.pose.y)


def _changements(avant, apres):
    """Ce qui change entre deux états du lieu : [{fichier, champ, avant, apres}], pour les rapports."""
    liste = []
    anciennes = {s.id: s for s in avant.salles}
    for s in apres.salles:
        a = anciennes.get(s.id)
        if a is None:
            continue
        if list(a.etiquettes) != list(s.etiquettes):
            liste.append({"fichier": SALLES, "champ": f"salle « {s.id} », etiquettes",
                          "avant": list(a.etiquettes), "apres": list(s.etiquettes)})
        if _pose_differe(a.pose, s.pose.x, s.pose.y, s.pose.theta):
            liste.append({"fichier": SALLES, "champ": f"salle « {s.id} », pose",
                          "avant": _pose_dict(a.pose), "apres": _pose_dict(s.pose)})
    for i, n in apres.itineraires.noeuds.items():
        a = avant.itineraires.noeuds.get(i)
        if a is None or a.etage != n.etage or _pose_differe(a, n.x, n.y):
            liste.append({"fichier": ITINERAIRES, "champ": f"nœud « {i} »",
                          "avant": _pose_dict(a, theta=False), "apres": _pose_dict(n, theta=False)})
    a, b = avant.accueil, apres.accueil
    if a.etage != b.etage or _pose_differe(a, b.x, b.y, b.theta):
        liste.append({"fichier": FICHE, "champ": "accueil", "avant": _pose_dict(a), "apres": _pose_dict(b)})
    for etage, m in apres.mondes.items():
        ancien = avant.mondes.get(etage)
        if ancien is not None and _pose_differe(ancien.depart_robot, m.depart_robot.x, m.depart_robot.y,
                                                m.depart_robot.theta):
            liste.append({"fichier": f"mondes/{etage}.monde.yaml", "champ": "depart_robot",
                          "avant": _pose_dict(ancien.depart_robot), "apres": _pose_dict(m.depart_robot)})
    return liste


# ---------------------------------------------------------------- écriture, tout ou rien

def _sans(d, cle):
    return {k: v for k, v in d.items() if k != cle}


def _remplacer_ligne(texte, cle, valeur, type_fichier, fichier, modele, donnees):
    """Le texte du fichier avec sa seule ligne « cle: {...} » remplacée (commentaire de fin de ligne
    gardé), ou None si ce n'est pas possible ou si le fichier relu ne donne pas exactement donnees."""
    motif = re.compile(r"^" + re.escape(cle) + r"[ \t]*:[ \t]*\{[^{}\n#]*\}[ \t]*(?P<commentaire>#[^\n]*)?$",
                       re.MULTILINE)
    trouves = list(motif.finditer(texte))
    if len(trouves) != 1:
        return None
    m = trouves[0]
    ligne = texte_yaml({cle: valeur}).rstrip("\n")
    if m.group("commentaire"):
        ligne += "  " + m.group("commentaire")
    nouveau = texte[:m.start()] + ligne + texte[m.end():]
    try:
        ancien, relu = lire_yaml(texte, fichier), lire_yaml(nouveau, fichier)
    except ErreurLieu:
        return None
    if not isinstance(ancien, dict) or not isinstance(relu, dict) or relu != dict(ancien, **{cle: valeur}):
        return None
    if valider_donnees(type_fichier, relu, fichier):
        return None
    if modele.depuis_dict(relu).vers_dict() != modele.depuis_dict(donnees).vers_dict():
        return None
    return nouveau


_DEBUT_SALLE = re.compile(r"^(?P<retrait>[ \t]*)-[ \t]+(?P<cle>id)[ \t]*:[ \t]*(?P<id>[^#\n]*?)[ \t]*(#[^\n]*)?$")


def _etiquettes_seules(texte, avant, apres):
    """salles.yaml quand seules des étiquettes changent : dans le bloc de chaque salle concernée, la
    ligne « etiquettes: [...] » est ajoutée, remplacée ou retirée ; le reste du fichier (commentaires
    compris) ne bouge pas. None si ce n'est pas possible (la liste est alors réécrite en entier)."""
    if [s["id"] for s in avant] != [s["id"] for s in apres]:
        return None
    if any(_sans(a, "etiquettes") != _sans(b, "etiquettes") for a, b in zip(avant, apres)):
        return None
    changees = {b["id"]: b.get("etiquettes", []) for a, b in zip(avant, apres)
                if a.get("etiquettes", []) != b.get("etiquettes", [])}
    lignes = texte.split("\n")
    debuts = []
    for i, ligne in enumerate(lignes):
        m = _DEBUT_SALLE.match(ligne)
        if m:
            try:
                ident = yaml.safe_load(m.group("id"))
            except yaml.YAMLError:
                return None
            debuts.append((i, str(ident), len(m.group("retrait")), m.start("cle")))
    if sorted(d[1] for d in debuts) != sorted(s["id"] for s in apres):
        return None
    for k in sorted(range(len(debuts)), key=lambda k: -debuts[k][0]):     # du bas vers le haut
        debut, ident, retrait, colonne = debuts[k]
        if ident not in changees:
            continue
        fin = debuts[k + 1][0] if k + 1 < len(debuts) else len(lignes)
        bloc = range(debut + 1, fin)
        motif = re.compile(r"^" + " " * colonne + r"etiquettes[ \t]*:")
        existantes = [i for i in bloc if motif.match(lignes[i])]
        nouvelle = " " * colonne + texte_yaml({"etiquettes": changees[ident]}).rstrip("\n")
        if existantes:
            if len(existantes) != 1 or not re.match(r"^[ \t]*etiquettes[ \t]*:[ \t]*\[[^\]\n]*\][ \t]*(#.*)?$",
                                                    lignes[existantes[0]]):
                return None
            if changees[ident]:
                lignes[existantes[0]] = nouvelle
            else:
                del lignes[existantes[0]]
        elif changees[ident]:
            derniere = max([i for i in bloc if lignes[i].strip() and not lignes[i].lstrip().startswith("#")
                            and len(lignes[i]) - len(lignes[i].lstrip()) >= colonne] or [debut])
            lignes.insert(derniere + 1, nouvelle)
    return "\n".join(lignes)


def _texte_salles(chemin, avant, donnees):
    """Texte de salles.yaml : seules les lignes d'étiquettes changent si c'est possible (fichier relu
    vérifié), sinon la liste entière, comme l'écrit l'Atelier. Validé (ErreurLieu sinon)."""
    erreurs = valider_donnees("salles", donnees, SALLES)
    if erreurs:
        raise ErreurLieu(erreurs)
    if avant is not None and chemin.is_file():
        try:
            ancien = chemin.read_text(encoding="utf-8")
            nouveau = _etiquettes_seules(ancien, avant, donnees)
            relu = lire_yaml(nouveau, SALLES) if nouveau is not None else None
        except (OSError, UnicodeDecodeError, ErreurLieu):
            relu = None
        if (isinstance(relu, list) and not valider_donnees("salles", relu, SALLES)
                and [Salle.depuis_dict(s).vers_dict() for s in relu] == donnees):
            return nouveau
    return texte_yaml(donnees, ENTETES["salles"])


def _texte(chemin, type_fichier, fichier, donnees, cle=None, modele=None):
    """Texte YAML à écrire, validé (ErreurLieu sinon). Avec cle : si possible, seule la ligne de ce
    champ change dans le fichier existant ; sinon le fichier entier, comme l'écrit l'Atelier."""
    erreurs = valider_donnees(type_fichier, donnees, fichier)
    if erreurs:
        raise ErreurLieu(erreurs)
    if cle is not None and chemin.is_file():
        try:
            ancien = chemin.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            ancien = None
        if ancien is not None:
            nouveau = _remplacer_ligne(ancien, cle, donnees[cle], type_fichier, fichier, modele, donnees)
            if nouveau is not None:
                return nouveau
    return texte_yaml(donnees, ENTETES[type_fichier])


def _generes_a_jour(lieu, etage):
    """Fichiers générés depuis le monde de l'étage (.sdf, et la carte si elle vient du monde) qui sont
    à jour, avec la même règle que g1-lieu valider et g1-monde simuler (1 s de marge)."""
    monde = chemin_monde(lieu.dossier, etage)
    if not monde.is_file():
        return []
    candidats = [chemin_sdf(lieu.dossier, etage)]
    e = lieu.etage(etage)
    if e is not None and e.source_carte == "monde":
        candidats.append(chemin_carte(lieu.dossier, etage))
    t = monde.stat().st_mtime
    return [c for c in candidats if c.is_file() and t <= c.stat().st_mtime + 1]


def _ecrire_tout(liste):
    """liste : [(chemin, texte)]. Tout est écrit ; si une écriture échoue, les fichiers déjà écrits
    reprennent leur contenu d'avant, puis l'erreur remonte."""
    faits = []
    try:
        for chemin, texte in liste:
            ancien = chemin.read_bytes() if chemin.exists() else None
            ecrire_atomique(chemin, texte)
            faits.append((chemin, ancien))
    except BaseException:
        for chemin, ancien in reversed(faits):
            try:
                if ancien is None:
                    chemin.unlink()
                else:
                    ecrire_atomique(chemin, ancien)
            except OSError:
                pass
        raise


def _ecrire(avant, apres, toujours=()):
    """Écrit les fichiers qui diffèrent entre avant et apres (deux états du même lieu), tout ou rien.
    toujours : types de fichiers écrits même sans changement (« salles » pour PUT …/salles).
    Renvoie les noms écrits, dans l'ordre : salles.yaml, itineraires.yaml, lieu.yaml, mondes/…"""
    dossier = apres.dossier
    a_ecrire, noms, a_garder = [], [], []
    salles = [s.vers_dict() for s in apres.salles]
    salles_avant = [s.vers_dict() for s in avant.salles]
    if "salles" in toujours or salles_avant != salles:
        # avant.salles vient du fichier (sauf s'il était illisible) : seules les étiquettes changent si possible
        a_ecrire.append((dossier / SALLES, _texte_salles(dossier / SALLES, salles_avant if avant.salles else None,
                                                         salles)))
        noms.append(SALLES)
    itin = apres.itineraires.vers_dict()
    if avant.itineraires.vers_dict() != itin:
        a_ecrire.append((dossier / ITINERAIRES, _texte(dossier / ITINERAIRES, "itineraires", ITINERAIRES, itin)))
        noms.append(ITINERAIRES)
    fiche_avant, fiche = avant.vers_dict(), apres.vers_dict()
    if fiche_avant != fiche:
        cle = "accueil" if _sans(fiche_avant, "accueil") == _sans(fiche, "accueil") else None
        a_ecrire.append((dossier / FICHE, _texte(dossier / FICHE, "lieu", FICHE, fiche, cle, Lieu)))
        noms.append(FICHE)
    for etage, monde in apres.mondes.items():
        d, ancien = monde.vers_dict(), avant.mondes.get(etage)
        d_avant = ancien.vers_dict() if ancien is not None else None
        if d_avant == d:
            continue
        nom = f"mondes/{etage}.monde.yaml"
        depart_seul = d_avant is not None and _sans(d_avant, "depart_robot") == _sans(d, "depart_robot")
        chemin = chemin_monde(dossier, etage)
        a_ecrire.append((chemin, _texte(chemin, "monde", nom, d, "depart_robot" if depart_seul else None, Monde)))
        noms.append(nom)
        if depart_seul:
            a_garder += _generes_a_jour(apres, etage)
    if a_ecrire:
        _ecrire_tout(a_ecrire)
    for c in a_garder:        # depart_robot n'entre ni dans le .sdf ni dans la carte : ils restent à jour
        try:
            os.utime(c)
        except OSError:
            pass
    return noms


def _rapport_lieu(dossier):
    from .verification import valider_lieu      # ici : verification importe ce module
    r = valider_lieu(dossier)
    return {"ok": r.ok, "erreurs": list(r.erreurs), "avertissements": list(r.avertissements)}


# ---------------------------------------------------------------- description

def decrire_principal(lieu):
    """Le point principal, pour l'API et les rapports : {salle, nom, etage, x, y, theta, explicite,
    depart_synchro, repere_unitree, pose_unitree}, ou None si le lieu n'en a pas.
    depart_synchro : depart_robot du monde de son étage est sur lui (None : l'étage n'a pas de monde) ;
    pose_unitree : la pose que reçoit 1804 quand le robot est posé sur lui (repère de la carte d'Unitree)."""
    dossier = dossier_lieu(lieu)
    salles = _seules(charger_salles(dossier))
    s = point_principal(salles)
    if s is None:
        return None
    p = s.pose
    d = {"salle": s.id, "nom": s.nom, "etage": s.etage, "x": p.x, "y": p.y, "theta": p.theta,
         "explicite": principal_explicite(salles), "depart_synchro": None, "repere_unitree": None,
         "pose_unitree": None}
    if chemin_monde(dossier, s.etage).is_file():
        depart = charger_monde(dossier, s.etage).depart_robot
        d["depart_synchro"] = (math.hypot(depart.x - p.x, depart.y - p.y) <= TOLERANCE_SYNCHRO
                               and abs(depart.theta - p.theta) <= TOLERANCE_SYNCHRO)
    try:
        r = repere_unitree(dossier, s.etage)
    except ErreurLieu:
        return d                # étage absent de lieu.yaml : la vérification le dit
    u = carte_vers_unitree(p, r)
    d["repere_unitree"] = {"x": round(r.x, DECIMALES), "y": round(r.y, DECIMALES), "theta": round(r.theta, DECIMALES)}
    d["pose_unitree"] = {"x": round(u[0], DECIMALES), "y": round(u[1], DECIMALES), "theta": round(u[2], DECIMALES)}
    return d


# ---------------------------------------------------------------- les quatre écritures

def definir_principal(lieu, salle=None, x=None, y=None, theta=None):
    """Fait de « salle » le point principal (étiquette déplacée) et/ou change sa pose (x et y
    ensemble, theta seul possible). Écrit, tout ou rien : salles.yaml, le nœud de même id
    (itineraires.yaml), accueil de lieu.yaml et depart_robot du monde de son étage. Renvoie
    {"principal": {...}, "enregistre": [fichiers], "changements": [...], "rapport": {...}}.
    ErreurLieu (en français) sinon ; SalleInconnue si la salle n'existe pas."""
    dossier = dossier_lieu(lieu)
    if salle is None and x is None and y is None and theta is None:
        raise ErreurLieu("rien à changer : donnez la salle qui devient le point principal (salle), sa position "
                         "(x et y, en mètres) ou son orientation (theta, en radians)")
    if (x is None) != (y is None):
        raise ErreurLieu("x et y vont ensemble : donnez les deux (en mètres, repère de la carte), ou aucun")
    nouvelle = None
    if x is not None:
        nouvelle = (_mesure(x, "x"), _mesure(y, "y"))
    angle = None if theta is None else _angle(theta)
    with _VERROU:
        charge = _charger(dossier)
        if salle is not None:
            cible = next((s for s in charge.salles if s.id == salle), None)
            if cible is None:
                connues = ", ".join(s.id for s in charge.salles) or "aucune"
                raise SalleInconnue(f"la salle « {salle} » n'existe pas dans salles.yaml (salles : {connues}) ; "
                                    "placez-la d'abord (Placer › Salle)")
        else:
            cible = point_principal(charge)
            if cible is None:
                raise ErreurLieu(SANS_PRINCIPAL)
        if charge.etage(cible.etage) is None:
            raise ErreurLieu(f"salles.yaml, salle « {cible.id} » : l'étage « {cible.etage} » n'existe pas dans "
                             "lieu.yaml ; corrigez la salle avant d'en faire le point principal")
        x, y = nouvelle if nouvelle is not None else (cible.pose.x, cible.pose.y)
        pose = Pose(x, y, cible.pose.theta if angle is None else angle)
        _monde(charge, cible.etage)
        avant = copy.deepcopy(charge)
        _aligner(charge, cible, pose, etiqueter=True)
        ecrits = _ecrire(avant, charge)
        changements = _changements(avant, charge)
    return {"principal": decrire_principal(dossier), "enregistre": ecrits, "changements": changements,
            "rapport": _rapport_lieu(dossier)}


def ecrire_salles(lieu, salles, synchroniser=False):
    """PUT …/salles : écrit salles.yaml (liste de Salle ou de dict). Avec synchroniser, aussi, tout ou
    rien : le nœud de même id de chaque salle (créé ou déplacé), puis la pose du point principal dans
    accueil de lieu.yaml et dans depart_robot du monde de son étage. Renvoie les fichiers écrits.

    Refuse (ErreurLieu) une liste invalide, dont une liste à deux principaux ; PerteDuPrincipal si
    le lieu avait un point principal (explicite, ou la salle « accueil ») et que la liste n'en a plus,
    ou si elle retire l'étiquette sans la donner à une autre salle."""
    dossier = dossier_lieu(lieu)
    salles = [s if isinstance(s, Salle) else Salle.depuis_dict(s) for s in salles]
    erreurs = valider_donnees("salles", [s.vers_dict() for s in salles], SALLES)
    if erreurs:
        raise ErreurLieu(erreurs)
    with _VERROU:
        try:
            anciennes = charger_salles(dossier)
        except ErreurLieu:
            anciennes = None        # salles.yaml illisible : la nouvelle liste le remplace
        if anciennes is not None:
            ancien = point_principal(_seules(anciennes))
            perdu = (principal_explicite(_seules(anciennes)) and not salles_principales(_seules(salles))) or \
                (ancien is not None and point_principal(_seules(salles)) is None)
            if perdu:
                garde = next((s for s in salles if s.id == ancien.id), None) if ancien is not None else None
                quoi = "retirez-lui l'étiquette" if garde is not None else "supprimez-la"
                raise PerteDuPrincipal(
                    f"salles.yaml : la salle « {ancien.nom} » ({ancien.id}) est le point principal du lieu "
                    "(l'accueil, où le robot démarre et revient après chaque visite) ; choisissez d'abord un autre "
                    f"point principal (Placer › Accueil, ou « Faire de cette salle l'accueil »), puis {quoi}")
        if not synchroniser:
            avant = [s.vers_dict() for s in anciennes] if anciennes else None
            _ecrire_tout([(dossier / SALLES, _texte_salles(dossier / SALLES, avant, [s.vers_dict() for s in salles]))])
            return [SALLES]
        charge = _charger(dossier, salles=False)
        charge.salles = list(anciennes or [])
        principal = point_principal(_seules(salles))
        if principal is not None and charge.etage(principal.etage) is not None:
            _monde(charge, principal.etage)
        avant = copy.deepcopy(charge)
        charge.salles = salles
        _noeuds_des_salles(charge)
        if principal is not None and charge.etage(principal.etage) is not None:
            _aligner(charge, principal, principal.pose, etiqueter=False)
        return _ecrire(avant, charge, toujours=("salles",))


def synchroniser_depart(lieu):
    """Recopie la pose du point principal dans depart_robot du monde de son étage (s'il existe).
    Renvoie True si le fichier a changé."""
    dossier = dossier_lieu(lieu)
    with _VERROU:
        charge = _charger(dossier)
        principal = point_principal(charge)
        if principal is None or charge.etage(principal.etage) is None:
            return False
        monde = _monde(charge, principal.etage)
        if monde is None:
            return False
        avant = copy.deepcopy(charge)
        p = principal.pose
        if not _pose_differe(monde.depart_robot, p.x, p.y, p.theta):
            return False
        monde.depart_robot = Pose(p.x, p.y, p.theta)
        return bool(_ecrire(avant, charge))


def sauvegarder_lieu(lieu, raison):
    """Copie lieu.yaml, salles.yaml, itineraires.yaml et mondes/*.monde.yaml dans
    lieux/<id>/sauvegardes/AAAA-MM-JJ_HHhMM_<raison>/ (suffixe -2, -3… si besoin). Renvoie le dossier.

    Les fichiers sont copiés octet pour octet, avec leur date ; un LISEZMOI.txt dit comment revenir
    en arrière. Rien n'est laissé à moitié : en cas d'erreur, le dossier de la sauvegarde est retiré."""
    dossier = dossier_lieu(lieu)
    if not isinstance(raison, str) or not atelier.MOTIF_ID.match(raison):
        raise ValueError(f"raison de sauvegarde invalide : {raison!r} (lettres minuscules, chiffres, _ ou -)")
    if not (dossier / FICHE).is_file():
        raise ErreurLieu(f"{dossier} : pas de lieu.yaml, ce dossier n'est pas un lieu")
    racine = dossier / DOSSIER_SAUVEGARDES
    racine.mkdir(exist_ok=True)
    base = f"{datetime.now().strftime('%Y-%m-%d_%Hh%M')}_{raison}"
    n = 1
    while True:
        cible = racine / (base if n == 1 else f"{base}-{n}")
        try:
            cible.mkdir()
            break
        except FileExistsError:
            n += 1
    try:
        copies = []
        for nom in FICHIERS_SAUVEGARDES:
            if (dossier / nom).is_file():
                shutil.copy2(dossier / nom, cible / nom)
                copies.append(nom)
        mondes = sorted((dossier / "mondes").glob("*.monde.yaml")) if (dossier / "mondes").is_dir() else []
        if mondes:
            (cible / "mondes").mkdir()
        for m in mondes:
            shutil.copy2(m, cible / "mondes" / m.name)
            copies.append(f"mondes/{m.name}")
        relatif = f"{DOSSIER_SAUVEGARDES}/{cible.name}"
        lignes = [f"Sauvegarde du lieu « {dossier.name} », faite le {datetime.now().strftime('%d/%m/%Y à %Hh%M')} "
                  f"(raison : {raison}).",
                  "Elle contient ces fichiers tels qu'ils étaient avant, octet pour octet :",
                  *[f"  {c}" for c in copies],
                  "",
                  "Pour revenir en arrière, depuis le dossier du lieu (ex. cd ~/robot-g1/lieux/" + dossier.name + ") :",
                  *[f"  cp -p {relatif}/{c} {c}" for c in copies],
                  "puis vérifiez : g1-lieu valider --lieu " + dossier.name, ""]
        ecrire_atomique(cible / LISEZMOI_SAUVEGARDE, "\n".join(lignes))
    except BaseException:
        shutil.rmtree(cible, ignore_errors=True)
        raise
    return cible


def migrer_lieu(lieu, depuis_depart=False, a_blanc=False):
    """« g1-lieu migrer » : sauvegarde, puis étiquette « principal » sur la salle accueil (ou, avec
    depuis_depart, le principal prend la pose depart_robot de son étage), accueil, nœud et depart_robot
    alignés. Idempotent ; a_blanc : rien n'est écrit. Renvoie le rapport {sauvegarde, changements,
    avertissements} (et lieu, dossier, a_blanc, principal, enregistre, erreurs_avant, erreurs_apres,
    message). Refuse lieux/demo (référence des tests).

    Les erreurs qui existaient déjà ne bloquent pas ; un fichier illisible bloque (ErreurLieu)."""
    dossier = dossier_lieu(lieu)
    if est_reference_des_tests(dossier):
        raise ErreurLieu("lieux/demo est la référence des tests : il garde le format d'avant (principal implicite, "
                         "la salle « accueil ») et n'est jamais migré. Pour essayer, migrez une copie : "
                         "cp -r ~/robot-g1/lieux/demo /tmp/essai && g1-lieu migrer --lieu /tmp/essai")
    if not (dossier / FICHE).is_file():
        raise ErreurLieu(f"le lieu {dossier} n'existe pas (pas de lieu.yaml) ; liste des lieux : g1-lieu liste")
    from .verification import valider_lieu
    with _VERROU:
        verif = valider_lieu(dossier)
        if verif.lieu is None:
            raise ErreurLieu(["un fichier du lieu est illisible : corrigez-le avant de migrer "
                              "(g1-lieu valider --lieu " + dossier.name + ")"] + list(verif.erreurs))
        charge = _charger(dossier)
        marquees = salles_principales(charge)
        cible = marquees[0] if marquees else charge.salle(ID_PRINCIPAL_IMPLICITE)
        if cible is None:
            raise ErreurLieu("ce lieu n'a ni salle étiquetée « principal » ni salle « accueil » : choisissez son point "
                             "principal (Placer › Accueil, ou « Faire de cette salle l'accueil »)")
        if charge.etage(cible.etage) is None:
            raise ErreurLieu(f"salles.yaml, salle « {cible.id} » : l'étage « {cible.etage} » n'existe pas dans "
                             "lieu.yaml ; corrigez la salle avant de migrer")
        monde = _monde(charge, cible.etage)
        pose = Pose(cible.pose.x, cible.pose.y, cible.pose.theta)
        avertissements = []
        if depuis_depart:
            if monde is None:
                raise ErreurLieu(f"--depuis-depart : l'étage « {cible.etage} » n'a pas de monde "
                                 f"(mondes/{cible.etage}.monde.yaml), donc pas de depart_robot")
            d = monde.depart_robot
            pose = Pose(d.x, d.y, d.theta)
        elif monde is not None and _pose_differe(monde.depart_robot, pose.x, pose.y, pose.theta):
            d = monde.depart_robot
            avertissements.append(
                f"mondes/{cible.etage}.monde.yaml : l'ancien départ du robot ({_texte_pose(d)}) n'était pas le point "
                f"principal « {cible.nom} » ({_texte_pose(pose)}) ; la simulation partira désormais du point "
                "principal. L'ancien départ reste dans la sauvegarde ; pour en faire le point principal, déplacez "
                "celui-ci (Placer › Accueil ; sa flèche donne le sens du robot), ou restaurez la sauvegarde puis "
                f"g1-lieu migrer --lieu {dossier.name} --depuis-depart")
        avant = copy.deepcopy(charge)
        _aligner(charge, cible, pose, etiqueter=True)
        changements = _changements(avant, charge)
        rapport = {"lieu": dossier.name, "dossier": str(dossier), "a_blanc": bool(a_blanc), "sauvegarde": None,
                   "principal": {"salle": cible.id, "nom": cible.nom, "etage": cible.etage, **_pose_dict(cible.pose)},
                   "changements": changements, "enregistre": [], "erreurs_avant": list(verif.erreurs),
                   "erreurs_apres": list(verif.erreurs), "avertissements": avertissements if changements else []}
        if not changements:
            rapport["message"] = (f"Rien à changer : le point principal « {cible.nom} » est déjà étiqueté, et "
                                  "accueil, nœud et départ du robot sont alignés sur lui.")
            return rapport
        if a_blanc:
            rapport["message"] = "Essai à blanc : rien n'a été écrit (ni sauvegarde, ni fichier du lieu)."
            return rapport
        sauvegarde = sauvegarder_lieu(dossier, RAISON_MIGRATION)
        rapport["sauvegarde"] = str(sauvegarde)
        rapport["enregistre"] = _ecrire(avant, charge)
        rapport["erreurs_apres"] = list(valider_lieu(dossier).erreurs)
        rapport["message"] = (f"Lieu migré : « {cible.nom} » est le point principal "
                              f"(étiquette « {ETIQUETTE_PRINCIPAL} »).")
        return rapport


def _texte_pose(p):
    morceaux = [f"{v:g}".replace(".", ",") for v in (p.x, p.y)]
    if getattr(p, "theta", None) is not None:
        morceaux.append(f"{p.theta:g}".replace(".", ","))
    return " ; ".join(morceaux)


def _texte_valeur(v):
    if v is None:
        return "absent"
    if isinstance(v, dict):
        coord = " ; ".join(f"{v[k]:g}".replace(".", ",") for k in ("x", "y", "theta") if k in v)
        return (f"{v['etage']} " if "etage" in v else "") + f"({coord})"
    if isinstance(v, list):
        return "[" + ", ".join(v) + "]" if v else "aucune"
    return str(v)


def texte_migration(rapport):
    """Le rapport de migrer_lieu, à afficher (en français)."""
    lignes = [f"Lieu « {rapport['lieu']} » ({rapport['dossier']})"]
    p = rapport["principal"]
    lignes.append(f"  point principal : salle « {p['nom']} » ({p['salle']}), étage {p['etage']}, "
                  f"({_texte_pose(Pose(p['x'], p['y'], p['theta']))})")
    if rapport["sauvegarde"]:
        lignes.append(f"  sauvegarde des fichiers d'avant : {rapport['sauvegarde']}")
    if rapport["changements"]:
        lignes.append(("Changements prévus" if rapport["a_blanc"] else "Changements") +
                      f" ({len(rapport['changements'])}) :")
        for c in rapport["changements"]:
            lignes.append(f"  - {c['fichier']}, {c['champ']} : {_texte_valeur(c['avant'])} → "
                          f"{_texte_valeur(c['apres'])}")
    for m in rapport["avertissements"]:
        lignes.append(f"Attention : {m}")
    avant, apres = rapport["erreurs_avant"], rapport["erreurs_apres"]
    if avant:
        lignes.append(f"Erreurs qui existaient déjà ({len(avant)}), à corriger à part (g1-lieu valider) :")
        lignes += [f"  - {m}" for m in avant]
    nouvelles = [m for m in apres if m not in avant]
    if nouvelles:
        lignes.append(f"Erreurs nouvelles ({len(nouvelles)}) :")
        lignes += [f"  - {m}" for m in nouvelles]
    lignes.append(rapport["message"])
    return "\n".join(lignes)


__all__ = ["DOSSIER_SAUVEGARDES", "ETIQUETTE_PRINCIPAL", "ID_PRINCIPAL_IMPLICITE", "MOT_PRINCIPAL",
           "REFERENCE_DES_TESTS", "PerteDuPrincipal", "SalleInconnue", "accueil_conforme", "decrire_principal",
           "definir_principal", "depart_simulation", "dossier_lieu", "ecrire_salles", "est_reference_des_tests",
           "migrer_lieu", "point_principal", "pose_de_reperage", "pose_principale", "principal_explicite",
           "salles_principales", "sauvegarder_lieu", "synchroniser_depart", "texte_migration", "ErreurLieu"]
