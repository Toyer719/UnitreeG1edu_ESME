"""La voix du robot depuis l'Atelier (vague 6, section 13.6 du plan) : agent Voix.

  GET  /api/voix/etat                    {lancee, tourne, etat: dernier /voix/etat (ou null), voix: les voix Piper
                                         prévues et présentes, sorties: SORTIES_VOIX avec leur libellé, processus}
  POST /api/voix/demarrer {lieu?, sortie?, volume?, voix?, vitesse?}   g1-voix (rôle voix) : {lance, detail, …} ;
                                         503 sans liaison ROS 2 du serveur
  POST /api/voix/arreter                 arrête le nœud voix (SIGINT : il envoie STOP_PLAY d'abord)
  POST /api/voix/essayer {texte, priorite?, voix?: {nom, vitesse, volume}}   /robot/dire (source atelier) ;
                                         {envoye, id, url, ecoutent} ; 409 si le nœud voix ne tourne pas
  POST /api/voix/commande {action, volume?, sortie?, voix?}   /voix/commande (schéma commande_voix) : taire,
                                         volume, sortie, voix ; 409 si le nœud voix ne tourne pas
  GET  /api/voix/son/{id}                le WAV d'une phrase (sortie borne ; aussi la trace d'une phrase dite par
                                         le robot), audio/wav ; 404 sinon (id de MOTIF_ID_SON, jamais un chemin) ;
                                         permis depuis la borne (garde de main.py)

Le serveur ne parle jamais au service voice du robot : seul le nœud voix le fait (la synthèse charge le processeur
et ne doit jamais retarder l'ARRÊT). Le nœud « tourne » quand son /voix/etat a moins de DELAI_ETAT_VOIX_S (il peut
avoir été lancé par l'Atelier, par la démo ou à la main avec g1-voix). Erreurs en français, jamais d'erreur 500.
"""
import asyncio
import itertools
import json
import math
import time

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from atelier.lieu import voix as V
from atelier.lieu.validation import valider_donnees

from ..communs import ErreurAtelier, dossier_du_lieu, verifier_id

routeur = APIRouter(tags=["voix"])

ROLE = "voix"
DELAI_ETAT_VOIX_S = 3.0           # /voix/etat plus vieux : le nœud voix ne tourne pas (il publie chaque seconde)
ATTENTE_DEMARRAGE_S = 1.5         # g1-voix qui s'arrête dans ce délai : erreur montrée tout de suite
TEXTE_MAX = 500
AIDES_SORTIES = {
    "robot": "La voix du PC (Piper), jouée par le haut-parleur du robot.",
    "borne": "La même voix, jouée par la tablette ou le téléphone de la borne (sans robot : en simulation).",
    "robot_tts": "La synthèse intégrée du robot : le français n'est pas sûr, à essayer avec le robot.",
}
_numeros = itertools.count(1)


def _etat(request):
    return request.app.state.atelier


async def _corps(request):
    texte = await request.body()
    if not texte:
        return {}
    try:
        d = json.loads(texte)
    except ValueError:
        raise ErreurAtelier(400, "Le corps de la demande n'est pas du JSON valable.") from None
    if not isinstance(d, dict):
        raise ErreurAtelier(400, "Le corps de la demande doit être un objet JSON.")
    return d


def _dernier_etat(etat):
    """Dernier /voix/etat reçu par le serveur (avec age_recu_s), ou None (pas de pont ROS 2, rien reçu)."""
    if not etat.pont.actif:
        return None
    try:
        return etat.pont.dernier("/voix/etat")
    except Exception:       # noqa: BLE001 : pont en cours d'arrêt
        return None


def _tourne(dernier):
    return dernier is not None and dernier.get("age_recu_s", 1e9) <= DELAI_ETAT_VOIX_S


def _voix_presentes():
    from atelier.voix.synthese import voix_disponibles
    presentes = set(voix_disponibles())
    return [{"id": nom, "nom": libelle, "presente": nom in presentes} for nom, libelle in V.VOIX_PIPER.items()]


def _sorties():
    from atelier.voix.logique import LIBELLES_SORTIES
    return [{"id": s, "libelle": LIBELLES_SORTIES[s], "aide": AIDES_SORTIES[s]} for s in V.SORTIES_VOIX]


def _exiger_voix(etat):
    """Le pont ROS 2 du serveur et un nœud voix qui tourne ; sinon 503 ou 409 avec la phrase qui dit quoi faire."""
    if not etat.pont.actif:
        raise ErreurAtelier(503, "L'Atelier n'a pas de liaison ROS 2 : relancez-le avec g1-atelier.",
                            sortie=etat.pont.erreur or "pont ROS 2 du serveur arrêté")
    dernier = _dernier_etat(etat)
    if not _tourne(dernier):
        raise ErreurAtelier(409, "La voix du robot ne tourne pas : cliquez d'abord sur « Démarrer la voix » "
                                 "(ou lancez la démo).",
                            sortie="aucun /voix/etat récent (nœud voix, g1-voix)")
    return dernier


def _entier(v, nom, bas, haut):
    if isinstance(v, bool) or not isinstance(v, int) or not bas <= v <= haut:
        raise ErreurAtelier(422, f"{nom} : un nombre entier de {bas} à {haut}.")
    return v


def _nombre(v, nom, bas, haut):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not bas <= v <= haut:
        raise ErreurAtelier(422, f"{nom} : un nombre de {bas:g} à {haut:g}.")
    return float(v)


def _reglages_voix(d, nom="voix"):
    """Le champ voix d'une phrase essayée : {nom, vitesse, volume}, chacun facultatif, vérifié."""
    if d is None:
        return None
    if not isinstance(d, dict):
        raise ErreurAtelier(422, f"{nom} : un ensemble de réglages {{nom, vitesse, volume}}.")
    inconnus = set(d) - {"nom", "vitesse", "volume"}
    if inconnus:
        raise ErreurAtelier(422, f"{nom} : réglage inconnu « {sorted(inconnus)[0]} » (nom, vitesse, volume).")
    reglages = {}
    if d.get("nom") is not None:
        if d["nom"] not in V.VOIX_PIPER:
            raise ErreurAtelier(422, f"Voix « {d['nom']} » inconnue : {', '.join(V.VOIX_PIPER)}.")
        reglages["nom"] = d["nom"]
    if d.get("vitesse") is not None:
        reglages["vitesse"] = _nombre(d["vitesse"], "vitesse", 0.5, 2.0)
    if d.get("volume") is not None:
        reglages["volume"] = _entier(d["volume"], "volume", 0, 100)
    return reglages or None


# ---------------------------------------------------------------- état

@routeur.get("/api/voix/etat")
def etat_voix(request: Request):
    """État de la voix : le nœud tourne-t-il, son dernier état, les voix et les sorties possibles."""
    etat = _etat(request)
    dernier = _dernier_etat(etat)
    return {"lancee": etat.gestionnaire.en_cours(ROLE), "tourne": _tourne(dernier), "etat": dernier,
            "voix": _voix_presentes(), "sorties": _sorties(), "processus": etat.gestionnaire.etat().get(ROLE),
            "voix_defaut": V.VOIX_DEFAUT, "volume_defaut": V.VOLUME_DEFAUT}


# ---------------------------------------------------------------- démarrer, arrêter

@routeur.post("/api/voix/demarrer")
async def demarrer(request: Request):
    """Lance g1-voix (rôle voix) avec les réglages demandés (lieu : ceux de sa démo, demo.yaml, puis les autres
    champs) ; un nœud déjà lancé par l'Atelier est relancé. 503 sans liaison ROS 2 du serveur : l'Atelier ne
    pourrait ni lui faire essayer une phrase ni lire son état."""
    etat = _etat(request)
    d = await _corps(request)
    lieu = d.get("lieu")
    arguments = []
    if lieu is not None:
        verifier_id(lieu, "identifiant de lieu")
        dossier_du_lieu(lieu)
        arguments = ["--lieu", lieu]
    sortie = d.get("sortie")
    if sortie is not None:
        if sortie not in V.SORTIES_VOIX:
            raise ErreurAtelier(422, f"Sortie « {sortie} » inconnue : {', '.join(V.SORTIES_VOIX)}.")
        arguments += ["--sortie", sortie]
    if d.get("volume") is not None:
        arguments += ["--volume", str(_entier(d["volume"], "volume", 0, 100))]
    if d.get("voix") is not None:
        if d["voix"] not in V.VOIX_PIPER:
            raise ErreurAtelier(422, f"Voix « {d['voix']} » inconnue : {', '.join(V.VOIX_PIPER)}.")
        arguments += ["--voix", d["voix"]]
    if d.get("vitesse") is not None:
        arguments += ["--vitesse", f"{_nombre(d['vitesse'], 'vitesse', 0.5, 2.0):g}"]
    if not etat.pont.actif:
        raise ErreurAtelier(503, "L'Atelier n'a pas de liaison ROS 2 : relancez-le avec g1-atelier, puis démarrez la "
                                 "voix.", sortie=etat.pont.erreur or "pont ROS 2 du serveur arrêté")
    from ..processus import CommandeAbsente
    try:
        await run_in_threadpool(etat.gestionnaire.lancer, ROLE, "g1-voix", arguments,
                                {"lieu": lieu, "sortie": sortie})
    except CommandeAbsente as e:
        raise ErreurAtelier(503, str(e)) from None
    fin = time.monotonic() + ATTENTE_DEMARRAGE_S
    while time.monotonic() < fin:
        if not etat.gestionnaire.en_cours(ROLE):
            lignes = etat.gestionnaire.etat().get(ROLE, {}).get("dernieres_lignes", [])
            raise ErreurAtelier(502, "La voix s'est arrêtée au démarrage : voir le détail.", sortie="\n".join(lignes))
        await asyncio.sleep(0.25)
    reponse = {"lance": True, "detail": "Voix démarrée : elle dit les phrases du robot.", "arguments": arguments}
    mode = etat.mode_navigation()
    if mode == "simu" and (sortie or "robot") != "borne":
        reponse["avertissement"] = ("En simulation, il n'y a pas de robot pour parler : choisissez la sortie "
                                    "« Borne » pour entendre la voix.")
    return reponse


@routeur.post("/api/voix/arreter")
async def arreter(request: Request):
    """Arrête le nœud voix lancé par l'Atelier (il coupe d'abord la phrase en cours : STOP_PLAY)."""
    etat = _etat(request)
    if not etat.gestionnaire.en_cours(ROLE):
        return {"arrete": False, "detail": "La voix n'a pas été lancée par l'Atelier : rien à arrêter."}
    await run_in_threadpool(etat.gestionnaire.arreter, ROLE)
    return {"arrete": True, "detail": "Voix arrêtée : le robot se tait."}


# ---------------------------------------------------------------- essayer, commandes

@routeur.post("/api/voix/essayer")
async def essayer(request: Request):
    """Une phrase d'essai sur /robot/dire (source atelier), dite par la sortie choisie du nœud voix."""
    etat = _etat(request)
    d = await _corps(request)
    texte = d.get("texte")
    if not isinstance(texte, str) or not texte.strip():
        raise ErreurAtelier(422, "Écrivez la phrase à essayer.")
    if len(texte) > TEXTE_MAX:
        raise ErreurAtelier(422, f"Phrase trop longue : {TEXTE_MAX} caractères au plus.")
    priorite = d.get("priorite") or "haute"
    if priorite not in V.PRIORITES_VOIX:
        raise ErreurAtelier(422, f"Priorité « {priorite} » inconnue : {', '.join(V.PRIORITES_VOIX)}.")
    reglages = _reglages_voix(d.get("voix"))
    dernier = _exiger_voix(etat)
    ident = f"essai-{time.strftime('%Y%m%d-%H%M%S')}-{next(_numeros)}"
    message = {"version": 1, "id": ident, "texte": texte.strip(), "source": "atelier", "priorite": priorite,
               "langue": "fr"}
    if reglages:
        message["voix"] = reglages
    erreurs = valider_donnees("robot_dire", message, "/robot/dire")
    if erreurs:
        raise ErreurAtelier(422, "Phrase refusée : voir les erreurs.", erreurs)
    try:
        ecoutent = etat.pont.publier_json("/robot/dire", message)
    except RuntimeError as e:
        raise ErreurAtelier(503, "L'Atelier n'a pas de liaison ROS 2 : relancez-le avec g1-atelier.",
                            sortie=str(e)) from None
    sortie = (dernier or {}).get("sortie")
    from atelier.voix.logique import LIBELLES_SORTIES
    return {"envoye": True, "id": ident, "url": V.URL_SON + ident, "ecoutent": ecoutent, "sortie": sortie,
            "detail": f"Phrase envoyée à la voix ({LIBELLES_SORTIES.get(sortie, 'sortie inconnue')})."}


@routeur.post("/api/voix/commande")
async def commande(request: Request):
    """Une commande du nœud voix sur /voix/commande : taire, volume, sortie, voix."""
    etat = _etat(request)
    d = await _corps(request)
    message = dict(d)
    message.setdefault("version", 1)
    message.setdefault("id", f"atelier-{next(_numeros)}")
    erreurs = valider_donnees("commande_voix", message, "commande de la voix")
    if erreurs:
        raise ErreurAtelier(422, "Commande de la voix refusée : voir les erreurs.", erreurs)
    if message["action"] == "voix" and message["voix"] not in V.VOIX_PIPER:
        raise ErreurAtelier(422, f"Voix « {message['voix']} » inconnue : {', '.join(V.VOIX_PIPER)}.")
    _exiger_voix(etat)
    try:
        ecoutent = etat.pont.publier_json("/voix/commande", message)
    except RuntimeError as e:
        raise ErreurAtelier(503, "L'Atelier n'a pas de liaison ROS 2 : relancez-le avec g1-atelier.",
                            sortie=str(e)) from None
    textes = {"taire": "Le robot se tait.", "volume": f"Volume : {message.get('volume')} %.",
              "sortie": "Sortie de la voix changée.", "voix": "Voix changée."}
    return {"envoye": True, "id": message["id"], "ecoutent": ecoutent, "detail": textes[message["action"]]}


# ---------------------------------------------------------------- le son d'une phrase

@routeur.get("/api/voix/son/{ident}")
def son(ident: str, request: Request):
    """Le WAV d'une phrase (sortie borne, ou trace d'une phrase dite par le robot) ; 404 sinon."""
    if not V.MOTIF_ID_SON.match(ident or ""):
        raise ErreurAtelier(404, "Ce son n'existe pas.")
    chemin = V.chemin_son(ident)
    if not chemin.is_file():
        raise ErreurAtelier(404, "Ce son n'existe pas, ou plus : la voix garde les 200 dernières phrases.")
    return FileResponse(chemin, media_type="audio/wav")
