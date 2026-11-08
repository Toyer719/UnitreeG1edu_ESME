"""
La machine d'états de la démo d'accueil, sans ROS (vague 6, section 13.4 du plan).

Squelette livré par l'agent Contrats ; l'agent Borne et orchestrateur l'écrit. Forme conseillée,
testée à fausse horloge comme le guide (g1_nav/guide.py) : chaque entrée rend la liste des messages
à publier, des couples (sujet, données) :
  ('/guide/aller', {...})  demande_guide, source « accueil » (jamais en pause : règle 13.4) ;
  ('/guide/stop', None)    pause demandée pendant une visite ;
  ('/robot/dire', {...})   robot_dire, source « accueil » (priorité securite pour une pause) ;
  ('/robot/geste', {...})  robot_geste (salutation), si saluer_geste ;
  ('/accueil/evenement', {...})  evenement_demo (réponse à chaque choix et commande avec id).
Entrées : entrer(sujet, donnees, t) pour chaque message reçu (/guide/etat, /guide/evenement,
/pont/etat, /pont/arret, /mouvement/maitre, /visiteurs/detectes ou /personnes/lidar,
/accueil/choix, /accueil/commande), et pas(t) pour les délais ; etat(t) rend le message de
/accueil/etat (schéma etat_demo).
"""


class Orchestrateur:
    """Machine d'états de la démo (squelette : toujours en démarrage, rien n'est publié)."""

    def __init__(self, salles, id_principal, etage, reglages=None, horloge=None):
        """Prépare la démo : salles du lieu, point principal, étage, réglages (demo.yaml)."""
        self.salles = list(salles)
        self.id_principal = id_principal
        self.etage = etage
        self.reglages = dict(reglages or {})
        self.horloge = horloge

    def entrer(self, sujet, donnees, t=None):
        """Un message reçu sur un sujet d'entrée ; rend les messages à publier."""
        return []

    def pas(self, t=None):
        """Délais (choix, départ, guide muet) ; rend les messages à publier."""
        return []

    def etat(self, t=None):
        """Rend le message à publier sur le sujet de l’état de la démo (squelette : None)."""
        return None
