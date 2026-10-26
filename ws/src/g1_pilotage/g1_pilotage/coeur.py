"""
Cœur du nœud pilotage : la logique (Pilotage), un verrou, et l'attente des réponses du robot.

Le nœud ROS (noeud.py) et les tests sans ROS donnent la fonction publier(sorties) qui exécute les
sorties de la logique (requêtes unitree_api, /arm_sdk, /guide/stop, /mouvement/maitre,
/robot/dire). L'API HTTP (serveur.py) appelle faire() et attendre() depuis ses fils de travail.
"""
import threading
import time

from .logique import D, DELAI_REPONSE_S, Pilotage, Resultat

DELAI_PRISE_S = 3.0             # prendre la main : attente du robot immobile, au plus


class Coeur:
    """La logique, sous un verrou ; un événement signale chaque réponse attendue."""

    def __init__(self, logique=None, publier=None, horloge=time.monotonic):
        self.logique = logique or Pilotage()
        self.publier = publier or (lambda sorties: None)
        self.horloge = horloge
        self.verrou = threading.RLock()
        self.attentes = {}              # identifiant → threading.Event
        self.ecouteurs = []             # fonctions appelées à chaque changement d'état (WebSocket)

    def faire(self, nom, *args, **kwargs):
        """Appelle une entrée de la logique, publie ses sorties ; renvoie le Resultat."""
        with self.verrou:
            resultat = getattr(self.logique, nom)(*args, **kwargs)
            if not isinstance(resultat, Resultat):
                resultat = Resultat(200, {}, resultat)
            if resultat.attendre is not None:
                self.attentes[resultat.attendre] = threading.Event()
            self.publier(resultat.sorties)
        return resultat

    def pas(self, t=None):
        """Le pas à 50 Hz de la logique."""
        with self.verrou:
            sorties = self.logique.pas(t)
            if sorties:
                self.publier(sorties)
        return sorties

    def sur_reponse(self, identifiant, code, data=''):
        with self.verrou:
            notre = self.logique.sur_reponse(identifiant, code, data)
            evenement = self.attentes.pop(identifiant, None)
        if evenement is not None:
            evenement.set()
        return notre

    def entree(self, nom, *args):
        """Entrée venue de ROS (sur_lowstate, sur_guide_etat, sur_pont_etat, sur_batterie)."""
        with self.verrou:
            getattr(self.logique, nom)(*args)

    def etat(self):
        with self.verrou:
            return self.logique.etat()

    def attendre(self, resultat, delai=DELAI_REPONSE_S):
        """Complète un Resultat qui attend la réponse du robot : 200, 409 (refus) ou 504."""
        if not resultat.ok or resultat.attendre is None:
            return resultat
        with self.verrou:
            evenement = self.attentes.get(resultat.attendre)
            deja = self.logique.reponse(resultat.attendre)
        if deja is None and evenement is not None:
            evenement.wait(delai)
        with self.verrou:
            self.attentes.pop(resultat.attendre, None)
            reponse = self.logique.reponse(resultat.attendre)
        corps = dict(resultat.corps)
        if reponse is None:
            corps['detail'] = (f'Le robot n\'a pas répondu en {delai:g} s : vérifiez qu\'il est '
                               'allumé et que la '
                               'liaison fonctionne (état du pilotage).')
            corps['envoye'] = True
            return Resultat(504, corps)
        code, data = reponse
        corps['code'] = code
        if code != 0:
            corps['detail'] = D.message_refus(code)
            corps['refus_robot'] = True
            return Resultat(409, corps)
        corps['data'] = data
        return Resultat(200, corps)

    def faire_et_attendre(self, nom, *args, delai=DELAI_REPONSE_S, **kwargs):
        return self.attendre(self.faire(nom, *args, **kwargs), delai)

    def prendre_main(self, forcer=False, par='atelier'):
        """Prendre la main : /guide/stop si besoin, robot immobile, puis maître pilotage."""
        resultat = self.faire('prendre_main', forcer=forcer, par=par)
        if resultat.statut != 202:
            return resultat
        fin = self.horloge() + DELAI_PRISE_S
        while self.horloge() < fin:
            with self.verrou:
                if self.logique.robot_immobile():
                    break
            time.sleep(0.05)
        return self.faire('finir_prise')
