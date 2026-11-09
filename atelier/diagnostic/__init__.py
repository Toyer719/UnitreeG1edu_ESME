"""Diagnostic « Vérifier le robot » (vague 6, section 13.2 du plan) : agent Diagnostic.

Contrat :
  diagnostiquer(mode="reel", pont=None, contexte=None, source="atelier", rapide=False) -> dict
      toutes les vérifications de atelier.lieu.diagnostic.VERIFICATIONS (en répétition : VERIFICATIONS_REPETITION,
      les autres dans « ignorees »), en parallèle, en DELAI_DIAGNOSTIC_S au plus (moins de 10 s : ECHEANCE_S) ; le
      résultat suit le schéma diagnostic (atelier.lieu.diagnostic.diagnostic le fabrique). pont : le PontRos du
      serveur (sujets(), infos_sujet(), appeler_unitree(), attendre_message(), etat_pont(), dernier()), ou None :
      g1-diagnostic démarre le sien. contexte : les vérifications système (fichiers, commandes, ping, ssh,
      variables) ; None : contexte_par_defaut(). rapide : sans ssh vers le Jetson (rafraîchissement de l'accueil).
      Ne lève que ValueError (mode ou source hors contrat) : une vérification qui échoue devient « inconnu ».
  faire_action(action, mode="reel", pont=None, contexte=None, services=None) -> dict
      une action de ACTIONS_DIAGNOSTIC, déjà confirmée par l'utilisateur : {action, ok, message, ...} ;
      « demarrer-services » : 1001 {"name", "switch": 1} pour chaque service arrêté de SERVICES_CARTOGRAPHIE
      (services : un sous-ensemble ; ServiceInterdit (ValueError) hors liste blanche), puis 1003 jusqu'à ce qu'ils
      soient actifs (DELAI_SERVICES_S) ; jamais d'arrêt de service. ActionInconnue, ActionImpossible (simulation,
      ou le câble en répétition) avant tout envoi.
  contexte_par_defaut() -> le contexte système, ou le faux lu dans $ATELIER_DIAGNOSTIC_FAUX (tests : rien n'est
      lancé, rien n'est envoyé sur le réseau ; chaque commande « lancée » est notée dans <fichier>.journal) ; avec
      G1_SLAM_FAUX=1 sans ce fichier, ni ping, ni ssh, ni nmcli up (« pas pendant les essais »).
  python -m atelier.diagnostic [--mode reel|repetition] [--json] [--rapide]  (commande g1-diagnostic) : le même
      code, sortie texte en français ; code de sortie atelier.lieu.diagnostic.code_de_sortie (0 : tout est bon).

Modules : contexte.py (primitives système : vrai, essais, faux), sondes.py (les faits, en parallèle, chacun avec
son délai), verdicts.py (faits → vérifications, fonctions pures), actions.py (liste blanche), texte.py (sortie de
g1-diagnostic), __main__.py (la commande).
"""
import time
from datetime import datetime

from atelier.lieu.diagnostic import DELAI_APPEL_S, DELAI_DIAGNOSTIC_S, diagnostic

from .actions import ActionImpossible, ActionInconnue, ServiceInterdit, faire_action, services_demandes, verifier_action
from .contexte import ContexteEssais, ContexteSysteme, EssaisInterdits, FauxContexte, contexte_par_defaut
from .sondes import DELAI_SUJETS_S, collecter
from .verdicts import juger

__all__ = ["diagnostiquer", "faire_action", "contexte_par_defaut", "demarrer_pont", "normaliser_mode",
           "ActionInconnue", "ActionImpossible", "ServiceInterdit", "EssaisInterdits", "FauxContexte",
           "ContexteEssais", "ContexteSysteme", "services_demandes", "verifier_action", "ECHEANCE_S",
           "SOURCES", "NOEUD_COMMANDE"]

ECHEANCE_S = min(9.0, DELAI_DIAGNOSTIC_S)      # tout le diagnostic : moins de 10 s (contrat : 15 s au plus)
SOURCES = ("atelier", "g1-diagnostic", "seance")
NOEUD_COMMANDE = "g1_diagnostic"               # le nœud ROS 2 de g1-diagnostic (PontRos à soi)
DELAI_SUJETS_COMMANDE_S = 4.0                  # nœud neuf : la découverte DDS du robot prend une à deux secondes
DELAI_APPEL_COMMANDE_S = 3.5                   # nœud neuf : attente de l'abonné, puis de la réponse


def normaliser_mode(mode):
    """reel ou repetition (« robot » vaut reel, comme le mode de la navigation) ; ValueError sinon."""
    texte = str(mode or "reel").strip().lower()
    if texte in ("reel", "robot"):
        return "reel"
    if texte == "repetition":
        return "repetition"
    raise ValueError(f"mode « {mode} » impossible pour le diagnostic : reel ou repetition (pas de robot en simulation)")


def demarrer_pont(nom_noeud=NOEUD_COMMANDE, attente=10.0):
    """Un PontRos à soi (g1-diagnostic), démarré ; inactif sans ROS 2 (son champ erreur dit pourquoi)."""
    from atelier.serveur.pont_ros import PontRos
    pont = PontRos(nom_noeud=nom_noeud)
    pont.demarrer(attente=attente)
    return pont


def diagnostiquer(mode="reel", pont=None, contexte=None, source="atelier", rapide=False, echeance_s=ECHEANCE_S):
    """Le diagnostic complet (schéma diagnostic), en parallèle, en moins de echeance_s secondes."""
    mode = normaliser_mode(mode)
    if source not in SOURCES:
        raise ValueError(f"source « {source} » inconnue ({', '.join(SOURCES)})")
    debut = time.monotonic()
    date = datetime.now().astimezone().isoformat(timespec="seconds")
    if contexte is None:
        contexte = contexte_par_defaut()
    propre = None
    if pont is None:
        propre = pont = demarrer_pont()
    try:
        reste = max(1.0, float(echeance_s) - (time.monotonic() - debut))
        neuf = propre is not None
        faits = collecter(mode, pont, contexte, rapide=rapide, echeance=time.monotonic() + reste,
                          delai_sujets=DELAI_SUJETS_COMMANDE_S if neuf else DELAI_SUJETS_S,
                          delai_appel=DELAI_APPEL_COMMANDE_S if neuf else DELAI_APPEL_S)
    finally:
        if propre is not None:
            propre.arreter()
    verifications, ignorees = juger(faits, mode, source=source, rapide=rapide)
    return diagnostic(verifications, mode, date, time.monotonic() - debut, ignorees=ignorees, source=source,
                      faux=bool(getattr(contexte, "faux", False)))
