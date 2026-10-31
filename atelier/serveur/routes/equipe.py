"""Routes de l'équipe (vague 4, section 11.6 du plan) : agent Équipe.

Fichiers du lieu, facultatifs (le lieu s'en passe), lus et écrits par atelier.lieu.equipe :
  GET  /api/lieux/{id}/personnalites           personnalites.yaml (404 s'il n'existe pas encore)
  GET  /api/lieux/{id}/dialogues               dialogues.yaml (idem)
  GET  /api/lieux/{id}/camera                  camera.yaml (idem)
  PUT  /api/lieux/{id}/personnalites|dialogues|camera
                                               écrit le fichier, refusé (422, en français) s'il est faux ;
                                               {enregistre, donnees, rapport} comme les autres PUT (4.4),
                                               rapport = vérification du lieu + celle des fichiers de
                                               l'équipe (verifier_equipe : personnalité inconnue d'une
                                               règle, motif jamais utilisé, caméra mal placée…)
  POST /api/lieux/{id}/personnalites|dialogues|camera/verifier
                                               même vérification, sans rien écrire (contenu dans le corps)
  POST /api/lieux/{id}/dialogues/essayer       {texte, dialogues?, etage?} : réponse du chatbot à une
                                               phrase, sans robot (dialogues : contenu pas encore
                                               enregistré ; sinon le fichier du lieu, ou l'exemple)
  POST /api/lieux/{id}/personnalites/active    {id} : la personnalité active, écrite dans le fichier et
                                               annoncée sur /personnalite/active (fiable, transient_local)

Informations et sujets ROS 2 :
  GET  /api/equipe                             schémas, exemples, sujets, codes des événements du guide,
                                               gestes, préréglages de caméra (aide des trois onglets)
  GET  /api/equipe/etat                        dernière personnalité annoncée, dernières phrases de
                                               /robot/dire, derniers visiteurs (caméra) et personnes
                                               (LiDAR) reçus par le pont ROS 2 du serveur
  GET  /api/equipe/cameras                     caméras vidéo branchées sur cet ordinateur (/dev/video*) ;
                                               vague 5 : leur nom stable (/dev/v4l/by-id/…) et le débit
                                               de leur lien USB (5000 : USB 3)
  POST /api/equipe/visiteur                    {texte} : publie la phrase sur /visiteur/texte, comme la
                                               reconnaissance vocale ; le nœud dialogue la traite (et peut
                                               faire partir le robot : l'onglet demande confirmation)

Aucune de ces routes ne fait bouger le robot elle-même : seule une phrase envoyée au nœud dialogue
peut finir en /guide/aller, et c'est alors le guide qui décide et conduit.
"""
import os
import re
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Body, Request
from pydantic import BaseModel

from atelier.lieu import ErreurLieu, charger_salles
from atelier.lieu import equipe as E
from atelier.lieu.comportement import CODES_EVENEMENT
from atelier.lieu.pilotage import GESTE_RELACHER, GESTES_BRAS
from atelier.lieu.validation import charger_schema

from ..communs import ErreurAtelier, dossier_du_lieu, erreur_validation, rapport_du_lieu

routeur = APIRouter(tags=["équipe"])

NOMS = {"personnalites": "les personnalités", "dialogues": "les dialogues", "camera": "la caméra"}
ONGLETS = {"personnalites": "Personnalités", "dialogues": "Dialogues", "camera": "Caméra"}
DOSSIER_VIDEO = Path("/sys/class/video4linux")      # remplaçable par les tests
DOSSIER_BY_ID = Path("/dev/v4l/by-id")              # noms stables des caméras (vague 5), idem
PHRASES_GARDEES = 20


class Essai(BaseModel):
    texte: str
    dialogues: Optional[Any] = None
    etage: Optional[str] = None


class Choix(BaseModel):
    id: str


class Phrase(BaseModel):
    texte: str


def _etat(request):
    return request.app.state.atelier


def _lire(dossier, quoi):
    try:
        return E.charger_equipe(dossier, quoi)
    except ErreurLieu as e:
        raise ErreurAtelier(422, f"Le fichier {E.FICHIERS_EQUIPE[quoi]} est invalide : corrigez les points "
                                 "ci-dessous (ou réécrivez-le depuis Équipe › " + ONGLETS[quoi] + ").",
                            e.erreurs) from None


def _rapport(dossier, donnees=None):
    """Vérification du lieu (comme g1-lieu valider) et des fichiers de l'équipe, réunies."""
    lieu = rapport_du_lieu(dossier)
    equipe = E.verifier_equipe(dossier, donnees)
    erreurs = list(lieu["erreurs"]) + [m for m in equipe["erreurs"] if m not in lieu["erreurs"]]
    avertissements = list(lieu["avertissements"]) + equipe["avertissements"]
    return {"ok": not erreurs, "erreurs": erreurs, "avertissements": avertissements,
            "equipe": equipe}


def _lire_fichier(quoi):
    def lire(id_lieu: str):
        dossier = dossier_du_lieu(id_lieu)
        donnees = _lire(dossier, quoi)
        if donnees is None:
            raise ErreurAtelier(404, f"Le lieu « {id_lieu} » n'a pas encore de fichier {E.FICHIERS_EQUIPE[quoi]} "
                                     f"(facultatif) : dans Équipe › {ONGLETS[quoi]}, partez de l'exemple puis "
                                     "enregistrez.")
        return donnees
    lire.__name__ = f"lire_{quoi}"
    lire.__doc__ = f"{E.FICHIERS_EQUIPE[quoi]} du lieu ; 404 s'il n'existe pas encore."
    return lire


def _ecrire_fichier(quoi):
    def ecrire(id_lieu: str, donnees: Any = Body(...)):
        dossier = dossier_du_lieu(id_lieu)
        fichier = E.FICHIERS_EQUIPE[quoi]
        erreurs = E.valider_equipe(quoi, donnees)
        if erreurs:
            raise erreur_validation(fichier, erreurs)
        try:
            E.enregistrer_equipe(dossier, quoi, donnees)
        except ErreurLieu as e:
            raise erreur_validation(fichier, e.erreurs) from None
        return {"enregistre": [fichier], "donnees": E.charger_equipe(dossier, quoi), "rapport": _rapport(dossier)}
    ecrire.__name__ = f"ecrire_{quoi}"
    ecrire.__doc__ = f"Écrit {E.FICHIERS_EQUIPE[quoi]} (vérifié) ; 422 avec les erreurs en français sinon."
    return ecrire


def _verifier_fichier(quoi):
    def verifier(id_lieu: str, donnees: Any = Body(...)):
        dossier = dossier_du_lieu(id_lieu)
        erreurs = E.valider_equipe(quoi, donnees)
        if erreurs:
            return {"ok": False, "erreurs": erreurs, "avertissements": []}
        return E.verifier_equipe(dossier, {quoi: donnees})
    verifier.__name__ = f"verifier_{quoi}"
    verifier.__doc__ = f"Vérifie un contenu de {E.FICHIERS_EQUIPE[quoi]} sans l'écrire : {{ok, erreurs, avertissements}}."
    return verifier


for _quoi in E.FICHIERS_EQUIPE:
    routeur.add_api_route(f"/api/lieux/{{id_lieu}}/{_quoi}", _lire_fichier(_quoi), methods=["GET"])
    routeur.add_api_route(f"/api/lieux/{{id_lieu}}/{_quoi}", _ecrire_fichier(_quoi), methods=["PUT"])
    routeur.add_api_route(f"/api/lieux/{{id_lieu}}/{_quoi}/verifier", _verifier_fichier(_quoi), methods=["POST"])


# ---------------------------------------------------------------- dialogues : essayer une phrase

@routeur.post("/api/lieux/{id_lieu}/dialogues/essayer")
def essayer(id_lieu: str, essai: Essai):
    """Réponse du chatbot d'exemple (atelier.equipe.dialogue) à une phrase, sans robot ni ROS."""
    from atelier.equipe.dialogue import Chatbot
    dossier = dossier_du_lieu(id_lieu)
    texte = essai.texte.strip()
    if not texte:
        raise ErreurAtelier(400, "Tapez une phrase à essayer (ex. « je cherche la salle B204 »).")
    if len(texte) > 500:
        raise ErreurAtelier(400, "Phrase trop longue : 500 caractères au plus.")
    origine = "onglet"
    dialogues = essai.dialogues
    if dialogues is None:
        dialogues = _lire(dossier, "dialogues")
        origine = "fichier"
        if dialogues is None:
            dialogues, origine = E.exemple_equipe("dialogues"), "exemple"
    else:
        erreurs = E.valider_equipe("dialogues", dialogues)
        if erreurs:
            raise ErreurAtelier(422, "Les règles de l'écran Dialogues ont des erreurs : corrigez-les avant d'essayer.", erreurs)
    try:
        salles = charger_salles(dossier)
    except ErreurLieu as e:
        raise ErreurAtelier(422, "Le fichier salles.yaml est invalide : corrigez les points ci-dessous.",
                            e.erreurs) from None
    resultat = Chatbot(dialogues, salles, etage=essai.etage).repondre(texte)
    return dict(resultat, origine=origine)


# ---------------------------------------------------------------- personnalité active

@routeur.post("/api/lieux/{id_lieu}/personnalites/active")
def choisir_personnalite(id_lieu: str, choix: Choix, request: Request):
    """Écrit active dans personnalites.yaml, puis annonce la personnalité sur /personnalite/active."""
    dossier = dossier_du_lieu(id_lieu)
    donnees = _lire(dossier, "personnalites")
    if donnees is None:
        raise ErreurAtelier(404, f"Le lieu « {id_lieu} » n'a pas encore de personnalites.yaml : enregistrez d'abord "
                                 "les personnalités.")
    perso = E.personnalite_active(donnees, choix.id)
    if perso is None:
        ids = ", ".join(p["id"] for p in donnees["personnalites"])
        raise ErreurAtelier(404, f"La personnalité « {choix.id} » n'existe pas dans personnalites.yaml "
                                 f"(personnalités : {ids}).")
    enregistre = []
    if donnees["active"] != choix.id:
        donnees["active"] = choix.id
        try:
            E.enregistrer_equipe(dossier, "personnalites", donnees)
        except ErreurLieu as e:
            raise erreur_validation("personnalites.yaml", e.erreurs) from None
        enregistre.append("personnalites.yaml")
    message = E.message_personnalite_active(perso, lieu=id_lieu)
    reponse = {"enregistre": enregistre, "active": choix.id, "message": message, "publie": False, "ecoute": 0}
    pont = _etat(request).pont
    if not pont.actif:
        reponse["avertissement"] = ("ROS 2 n'est pas actif dans le serveur : la personnalité est enregistrée, mais "
                                    "pas annoncée sur /personnalite/active.")
        return reponse
    reponse.update(publie=True, ecoute=pont.publier_json("/personnalite/active", message))
    if reponse["ecoute"] == 0:
        reponse["avertissement"] = ("Annoncée sur /personnalite/active ; personne n'écoute encore (la voix et le "
                                    "nœud dialogue la recevront en démarrant).")
    return reponse


# ---------------------------------------------------------------- informations et sujets

@routeur.get("/api/equipe")
def informations():
    """Ce que les onglets de l'équipe affichent comme aide : schémas, exemples, sujets, codes, gestes."""
    fichiers = {quoi: {"fichier": fichier, "schema": charger_schema(quoi), "exemple": E.exemple_equipe(quoi),
                       "onglet": ONGLETS[quoi]}
                for quoi, fichier in E.FICHIERS_EQUIPE.items()}
    sujets = [{"sujet": s, "type": t, "schema": sch, "qui": qui} for s, (t, sch, qui) in E.SUJETS_EQUIPE.items()]
    return {"fichiers": fichiers, "sujets": sujets, "codes_evenement": dict(CODES_EVENEMENT),
            "gestes": {str(k): v for k, v in GESTES_BRAS.items() if k != GESTE_RELACHER},
            "actions": list(E.ACTIONS_DIALOGUE), "prereglages_camera": E.PREREGLAGES_CAMERA,
            "reperes": {"motif": list(E.REPERES_MOTIF), "reponse": list(E.REPERES_REPONSE),
                        "phrase": list(E.REPERES_PHRASE)}}


@routeur.get("/api/equipe/etat")
def etat_equipe(request: Request):
    """Ce que le pont ROS 2 du serveur a reçu des parties de l'équipe."""
    pont = _etat(request).pont
    actif = bool(pont.actif)
    return {"ros": {"actif": actif, "erreur": pont.erreur},
            "personnalite": pont.dernier("/personnalite/active") if actif else None,
            "dire": pont.historique("/robot/dire")[-PHRASES_GARDEES:] if actif else [],
            "visiteurs": pont.dernier("/visiteurs/detectes") if actif else None,
            "personnes": pont.dernier("/personnes/lidar") if actif else None}


def _noms_stables():
    """{videoN: chemin /dev/v4l/by-id/…} des caméras qui ont un nom stable (numéro de série)."""
    noms = {}
    try:
        liens = sorted(DOSSIER_BY_ID.iterdir()) if DOSSIER_BY_ID.is_dir() else []
    except OSError:
        liens = []
    for lien in liens:
        cible = Path(os.path.realpath(lien)).name
        if re.fullmatch(r"video\d+", cible):
            noms.setdefault(cible, str(lien))
    return noms


def _debit_usb(dossier):
    """Débit du lien USB (Mbit/s : 480 en USB 2, 5000 en USB 3) d'une caméra de /sys, ou None."""
    try:
        return int(float((dossier / "device" / ".." / "speed").read_text(encoding="utf-8").strip()))
    except (OSError, ValueError):
        return None


@routeur.get("/api/equipe/cameras")
def cameras():
    """Caméras vidéo de cet ordinateur : [{peripherique, nom, by_id, usb_mbps}] (lecture de /sys et
    /dev/v4l/by-id, rien n'est ouvert). by_id : le nom stable (vague 5), ou null."""
    trouvees = []
    stables = _noms_stables()
    if DOSSIER_VIDEO.is_dir():
        for d in DOSSIER_VIDEO.iterdir():
            m = re.fullmatch(r"video(\d+)", d.name)
            if not m:
                continue
            try:
                nom = (d / "name").read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                nom = ""
            trouvees.append((int(m.group(1)), {"peripherique": f"/dev/{d.name}", "nom": nom,
                                               "by_id": stables.get(d.name), "usb_mbps": _debit_usb(d)}))
    return [c for _, c in sorted(trouvees, key=lambda x: x[0])]


@routeur.post("/api/equipe/visiteur")
def envoyer_phrase(phrase: Phrase, request: Request):
    """Publie une phrase sur /visiteur/texte, comme la reconnaissance vocale de l'équipe."""
    texte = phrase.texte.strip()
    if not texte:
        raise ErreurAtelier(400, "Tapez une phrase à envoyer.")
    if len(texte) > 500:
        raise ErreurAtelier(400, "Phrase trop longue : 500 caractères au plus.")
    pont = _etat(request).pont
    if not pont.actif:
        raise ErreurAtelier(503, "ROS 2 n'est pas actif dans le serveur : impossible d'envoyer la phrase sur "
                                 "/visiteur/texte (" + (pont.erreur or "pont ROS 2 arrêté") + ").")
    ecoute = pont.publier_json("/visiteur/texte", texte)
    reponse = {"envoye": texte, "sujet": "/visiteur/texte", "ecoute": ecoute}
    if ecoute == 0:
        reponse["avertissement"] = ("Personne n'écoute /visiteur/texte : lancez le nœud dialogue (ros2 run g1_equipe "
                                    "dialogue --ros-args -p lieu:=…), voir docs/integration-equipe.md.")
    return reponse
