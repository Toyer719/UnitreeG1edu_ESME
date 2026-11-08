"""Diagnostic « Vérifier le robot » (vague 6, section 13.2 du plan) : agent Diagnostic.

Squelette livré par l'agent Contrats ; l'agent Diagnostic écrit ce paquet (il peut y ajouter des modules).

Contrat :
  diagnostiquer(mode="reel", pont=None, contexte=None, source="atelier", rapide=False) -> dict
      toutes les vérifications de atelier.lieu.diagnostic.VERIFICATIONS (en répétition : VERIFICATIONS_REPETITION,
      les autres dans « ignorees »), en parallèle, en DELAI_DIAGNOSTIC_S au plus ; le résultat suit le schéma
      diagnostic (atelier.lieu.diagnostic.diagnostic le fabrique). pont : le PontRos du serveur (sujets(),
      infos_sujet(), appeler_unitree(), dernier()), ou None : g1-diagnostic démarre le sien. contexte : les
      vérifications système (fichiers, commandes, ping, ssh, variables) ; None : contexte_par_defaut(). rapide :
      sans ssh vers le Jetson (rafraîchissement de l'accueil).
  faire_action(action, mode="reel", pont=None, contexte=None, services=None) -> dict
      une action de ACTIONS_DIAGNOSTIC, déjà confirmée par l'utilisateur : {action, ok, message, ...} ;
      « demarrer-services » : 1001 {"name", "switch": 1} pour chaque service arrêté de SERVICES_CARTOGRAPHIE
      (services : un sous-ensemble ; ValueError hors liste blanche), puis 1003 jusqu'à ce qu'ils soient actifs
      (DELAI_SERVICES_S) ; jamais d'arrêt de service.
  contexte_par_defaut() -> le contexte système, ou le faux lu dans $ATELIER_DIAGNOSTIC_FAUX (tests : rien n'est
      lancé, rien n'est envoyé sur le réseau ; chaque commande « lancée » est notée dans <fichier>.journal).
  python -m atelier.diagnostic [--mode reel|repetition] [--json] [--rapide]  (commande g1-diagnostic) : le même
      code, sortie texte en français ; code de sortie atelier.lieu.diagnostic.code_de_sortie (0 : tout est bon).
"""

MESSAGE_PAS_ENCORE_FAIT = "Pas encore fait : {quoi} (vague 6, agent Diagnostic, section 13.2 du plan)."


def diagnostiquer(mode="reel", pont=None, contexte=None, source="atelier", rapide=False):
    """Contrat (squelette) : le diagnostic complet, au schéma diagnostic."""
    raise NotImplementedError(MESSAGE_PAS_ENCORE_FAIT.format(quoi="le diagnostic du robot"))


def faire_action(action, mode="reel", pont=None, contexte=None, services=None):
    """Contrat (squelette) : une action du diagnostic, déjà confirmée."""
    raise NotImplementedError(MESSAGE_PAS_ENCORE_FAIT.format(quoi="les actions du diagnostic"))


def contexte_par_defaut():
    """Contrat (squelette) : le contexte des vérifications système."""
    raise NotImplementedError(MESSAGE_PAS_ENCORE_FAIT.format(quoi="le contexte des vérifications"))
