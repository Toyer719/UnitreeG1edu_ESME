"""Boîte noire et rapport de séance (vague 6, section 13.3 du plan) : agent Boîte noire.

Squelette livré par l'agent Contrats ; l'agent Boîte noire écrit ce paquet (il peut y ajouter des modules :
enregistreur du bag, journal des actions, rapport…). Le dossier d'une séance, les sujets enregistrés et les
réglages sont dans atelier.lieu.seance.

Contrat : GestionnaireSeance(etat_serveur), un par serveur, créé par EtatServeur (etat.seance). Ses méthodes
sont appelées par le serveur et ne doivent JAMAIS lever d'exception vers lui ni le ralentir (sauf demarrer et
arreter, appelées par les routes, qui peuvent lever ErreurAtelier ou NotImplementedError → 501) :
  demarrer(mode, lieu=None, etage=None, ouverture="auto") -> dict   ouvre la séance (mode reel ou repetition),
        ou rend celle qui est déjà ouverte : le manifeste (schéma seance) ;
  arreter(fermeture="terminer") -> dict | None   la ferme (journal du Jetson, fin de l'enregistrement, manifeste),
        puis lance le rapport en arrière-plan ; None s'il n'y en avait pas ;
  etat() -> dict | None          la séance ouverte, en bref (champ seance de /ws/etat, badge « ● Enregistrement ») ;
  noter_action(action) -> None   appelée par l'accroche de main.py (JournalDesActions), APRÈS chaque réponse à une
        demande POST, PUT, PATCH ou DELETE sous /api/ : action = {t, methode, chemin, requete, statut, reponse,
        duree_ms, client} (13.3) ; sans séance ouverte, rien ; doit rendre la main tout de suite (file + fil) ;
  avant_arret_jetson(local=False) -> dict | None   juste avant chaque « g1-jetson arreter » lancé par l'Atelier
        (routes/simulation.py) : g1-jetson journal dans journaux/jetson/ de la séance (30 s au plus) ;
  demarrage_serveur() -> None    au démarrage du serveur : une séance restée « ouverte » sans enregistreur vivant
        devient « interrompue » (bag réindexé, rapport) ; aucune séance ne s'ouvre seule ;
  fermer(fermeture="arret_atelier") -> None   à l'arrêt du serveur, 10 s au plus (le rapport se fait à part).
"""

MESSAGE_PAS_ENCORE_FAIT = "Pas encore fait : {quoi} (vague 6, agent Boîte noire, section 13.3 du plan)."


class GestionnaireSeance:
    """Contrat (squelette) : la séance de l'Atelier ; sans l'agent Boîte noire, aucune séance ne s'ouvre."""

    def __init__(self, etat_serveur=None):
        self.etat_serveur = etat_serveur

    def demarrer(self, mode, lieu=None, etage=None, ouverture="auto"):
        raise NotImplementedError(MESSAGE_PAS_ENCORE_FAIT.format(quoi="ouvrir une séance"))

    def arreter(self, fermeture="terminer"):
        raise NotImplementedError(MESSAGE_PAS_ENCORE_FAIT.format(quoi="fermer une séance"))

    def etat(self):
        return None

    def noter_action(self, action):
        return None

    def avant_arret_jetson(self, local=False):
        return None

    def demarrage_serveur(self):
        return None

    def fermer(self, fermeture="arret_atelier"):
        return None
