"""Contrat de la voix du robot (vague 6, section 13.6 du plan) : sorties, priorités, requêtes au service voice du G1.

Les phrases à dire arrivent sur /robot/dire (schéma robot_dire : personnalités, guide, démo, chatbot). Le nœud
voix (atelier/voix/, commande g1-voix, sur le PC) les dit par une des trois sorties choisies dans l'Atelier :
  robot      synthèse en français sur le PC (Piper, modeles/piper/), PCM 16 kHz mono 16 bits, joué par le
             haut-parleur du robot : service voice, api 1003 START_PLAY (morceaux de 96 000 octets, 3 s), 1004
             STOP_PLAY pour couper ;
  borne      le même son, joué par la page de la borne (fichier WAV servi par GET /api/voix/son/<id>) ;
  robot_tts  la synthèse intégrée d'Unitree (api 1001 TtsMaker ; le français est à vérifier sur le robot).
Le volume du robot : 1005 (lire) et 1006 (régler). Une phrase « securite » coupe tout et vide la file, « haute »
coupe la phrase en cours, « normale » attend son tour.

Formats exacts (SDK d'Unitree : unitree_sdk2/example/g1/audio, unitree_sdk2py/g1/audio/g1_audio_client.py) :
requête unitree_api/Request sur /api/voice/request, header.identity.api_id = l'api, parameter = le JSON,
binary = les octets PCM (petit-boutiste, 16 bits signés) seulement pour 1003 :
  1003  {"app_name": "atelier", "stream_id": "<id de la phrase>"} + binary (≤ 96 000 octets, nombre pair) ;
        les morceaux d'une même phrase ont le même stream_id, envoyés dans l'ordre ;
  1004  {"app_name": "atelier"} ;
  1001  {"index": i, "speaker_id": n, "text": "…"} (pilotage.parametre_tts) ;
  1005  {} → data {"volume": n} ;     1006  {"volume": n}, de 0 à 100 (pilotage.parametre_volume).
erreurs_requete_voix(api_id, parametre, binaire) vérifie une requête (schéma requete_voix et règles) : le faux G1
s'en sert pour compter les requêtes mal formées. Le nœud voix n'envoie jamais 1002 (micro) ni 1010 (lumière :
c'est le pilotage) ; on n'envoie jamais de son au vrai robot pendant les tests automatiques.
"""
import json
import os
import re
from pathlib import Path

import atelier

from .pilotage import parametre_tts, parametre_volume
from .validation import valider_donnees

SORTIES_VOIX = ("robot", "borne", "robot_tts")
PRIORITES_VOIX = ("normale", "haute", "securite")
RANG_PRIORITE = {"normale": 0, "haute": 1, "securite": 2}

SERVICE_VOIX = "/api/voice"                     # + /request, /response (unitree_api/Request, Response)
API_VOIX = {"tts": 1001, "start_play": 1003, "stop_play": 1004, "get_volume": 1005, "set_volume": 1006}
APIS_NOEUD_VOIX = (1001, 1003, 1004, 1005, 1006)  # les seules que le nœud voix envoie
APP_VOIX = "atelier"                            # app_name de 1003 et 1004
FREQUENCE_PCM_HZ = 16000
CANAUX_PCM = 1
OCTETS_ECHANTILLON = 2                          # 16 bits signés, petit-boutiste
OCTETS_PAR_SECONDE = FREQUENCE_PCM_HZ * CANAUX_PCM * OCTETS_ECHANTILLON
TAILLE_MORCEAU_OCTETS = 96000                   # 3 s par requête 1003, comme les exemples du SDK
ECART_MORCEAUX_S = 1.0                          # un morceau par seconde au plus (exemples du SDK : 1 s)
DUREE_PHRASE_MAX_S = 30.0
VOIX_PIPER = {"fr_FR-siwis-medium": "Siwis (voix de femme)", "fr_FR-tom-medium": "Tom (voix d'homme)"}
VOIX_DEFAUT = "fr_FR-siwis-medium"
DOSSIER_PIPER = atelier.RACINE / "modeles" / "piper"
LOCUTEURS_TTS = {"zh": 0, "en": 1}              # speaker_id de 1001 (SDK C++) ; le français : à vérifier
VOLUME_DEFAUT = 70

SUJETS_VOIX = {                                 # sujet → (type, schéma, sens vu du nœud voix)
    "/robot/dire": ("std_msgs/String", "robot_dire", "entree"),
    "/voix/commande": ("std_msgs/String", "commande_voix", "entree"),
    "/voix/etat": ("std_msgs/String", "etat_voix", "sortie"),
    "/voix/son": ("std_msgs/String", "son_voix", "sortie"),
}
ACTIONS_VOIX = ("taire", "volume", "sortie", "voix")
PERIODE_ETAT_S = 1.0                            # /voix/etat : 1 fois par seconde, et à chaque changement
MOTIF_ID_SON = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
URL_SON = "/api/voix/son/"                      # + id : le WAV d'une phrase (sortie borne)


def dossier_sons():
    """Dossier des WAV de la sortie borne : $ATELIER_VOIX_SONS, sinon ~/robot-g1/journaux/voix/sons (créé)."""
    dossier = Path(os.environ.get("ATELIER_VOIX_SONS") or atelier.dossier_journaux() / "voix" / "sons").expanduser()
    dossier.mkdir(parents=True, exist_ok=True)
    return dossier


def chemin_son(ident):
    """Fichier WAV d'une phrase ; ValueError pour un id mal formé (jamais de chemin du type « ../ »)."""
    if not isinstance(ident, str) or not MOTIF_ID_SON.match(ident):
        raise ValueError(f"id de son mal formé : {ident!r}")
    return dossier_sons() / f"{ident}.wav"


# ---------------------------------------------------------------- requêtes au service voice

def parametre_lecture(stream_id, app_name=APP_VOIX):
    """parameter de 1003 START_PLAY (le binary porte un morceau de PCM)."""
    return json.dumps({"app_name": str(app_name), "stream_id": str(stream_id)})


def parametre_arret(app_name=APP_VOIX):
    """parameter de 1004 STOP_PLAY."""
    return json.dumps({"app_name": str(app_name)})


def parametre_lire_volume():
    """parameter de 1005 GetVolume."""
    return "{}"


def morceaux_pcm(pcm, taille=TAILLE_MORCEAU_OCTETS):
    """Le PCM d'une phrase en morceaux de « taille » octets au plus, dans l'ordre (le dernier peut être plus court).
    ValueError si le nombre d'octets est impair (des échantillons de 16 bits) ou la taille hors contrat."""
    pcm = bytes(pcm)
    if len(pcm) % OCTETS_ECHANTILLON:
        raise ValueError("PCM de 16 bits : le nombre d'octets doit être pair")
    if taille <= 0 or taille > TAILLE_MORCEAU_OCTETS or taille % OCTETS_ECHANTILLON:
        raise ValueError(f"taille de morceau de 2 à {TAILLE_MORCEAU_OCTETS} octets, paire")
    return [pcm[i:i + taille] for i in range(0, len(pcm), taille)]


def duree_pcm_s(nombre_octets):
    """Durée (s) de ce nombre d'octets de PCM 16 kHz mono 16 bits."""
    return nombre_octets / OCTETS_PAR_SECONDE


def description_requete(api_id, parametre, binaire=b""):
    """La requête décrite pour le schéma requete_voix : {api_id, parametre (le JSON lu), octets}. Un parameter
    illisible donne parametre « None » (refusé par le schéma)."""
    try:
        lu = json.loads(parametre) if isinstance(parametre, str) else parametre
    except ValueError:
        lu = None
    return {"api_id": api_id, "parametre": lu, "octets": len(binaire or b"")}


def erreurs_requete_voix(api_id, parametre, binaire=b""):
    """Erreurs (en français) d'une requête au service voice : [] si elle est bien formée."""
    return valider_donnees("requete_voix", description_requete(api_id, parametre, binaire),
                           f"requête voice {api_id}")


# parametre_tts (1001) et parametre_volume (1006) sont ceux de atelier.lieu.pilotage, repris ici tels quels
PARAMETRES_REPRIS = (parametre_tts, parametre_volume)

EXEMPLE_ETAT_VOIX = {
    "version": 1, "sortie": "robot", "voix": "fr_FR-siwis-medium", "volume": 70,
    "en_cours": {"id": "s-20261112-142031-0003", "texte": "Suivez-moi !", "priorite": "normale", "source": "guide",
                 "debut": "2026-11-12T14:20:31+01:00", "duree_s": 1.1},
    "file": 1, "dites": 14, "interrompues": 1, "erreurs": 0, "derniere_erreur": None,
    "robot": {"abonne": True, "repond": True, "age_reponse_s": 0.4}, "temps": "2026-11-12T14:20:32+01:00",
}
EXEMPLE_SON_VOIX = {"version": 1, "id": "s-20261112-142031-0003", "texte": "Suivez-moi !", "duree_s": 1.1,
                    "url": "/api/voix/son/s-20261112-142031-0003", "priorite": "normale", "source": "guide",
                    "frequence_hz": 22050, "temps": "2026-11-12T14:20:31+01:00"}
EXEMPLE_COMMANDE_VOIX = {"version": 1, "action": "volume", "volume": 60}
EXEMPLE_REQUETE_LECTURE = {"api_id": 1003, "parametre": {"app_name": APP_VOIX, "stream_id": "s-20261112-142031-0003"},
                           "octets": 35200}
