"""État du serveur partagé par les routes : processus lancés, pont ROS 2, simulation en cours."""
import time

from .pietons import positions_pietons
from .pont_ros import PontRos
from .processus import Gestionnaire


class EtatServeur:
    def __init__(self, ros=True):
        self.ros = ros                    # False : pas de pont ROS 2 (tests de l'API)
        self.gestionnaire = Gestionnaire()
        self.pont = PontRos()
        # simulation en cours : {lieu, etage, dossier, monde (Monde ou None), debut}
        self.simulation = None

    def demarrer(self):
        if self.ros:
            self.pont.demarrer()

    def arreter(self):
        self.gestionnaire.arreter_tout()
        self.pont.arreter()

    def simulation_en_cours(self):
        return self.simulation is not None and self.gestionnaire.en_cours("simulation")

    def temps_simulation(self):
        """Temps simulé (/clock) ; à défaut, secondes écoulées depuis le lancement."""
        t = self.pont.temps_sim() if self.pont.actif else None
        if t is None and self.simulation is not None:
            t = time.time() - self.simulation["debut"]
        return t

    def etat_direct(self):
        """Message du WebSocket /ws/etat : {robot, guide, pietons, processus, ...} (contrat 4.4)."""
        pont = self.pont.etat()
        en_cours = self.simulation_en_cours()
        t = self.temps_simulation() if en_cours else None
        sim = None
        if self.simulation is not None:
            sim = {"lieu": self.simulation["lieu"], "etage": self.simulation["etage"], "en_cours": en_cours}
        return {
            "robot": pont["robot"],
            "guide": pont["guide"],
            "pietons": positions_pietons(self.simulation["monde"], t) if en_cours else [],
            "processus": self.gestionnaire.etat(),
            "simulation": sim,
            "temps_sim": None if t is None else round(t, 2),
            "ros": {"actif": pont["actif"], "erreur": pont["erreur"], "nav2": pont["nav2"]},
        }
