"""État du serveur partagé par les routes : processus lancés, pont ROS 2, simulation en cours.

Vague 3 (section 10.8 du plan) : la navigation tourne dans un des trois modes de MODES_NAVIGATION,
noté dans simulation["mode"] :
  simu        Gazebo et la navigation de la simulation (rôles simulation et navigation) ;
  repetition  Gazebo avec le faux G1, le faux slam_operate et la navigation du vrai robot
              (rôles simulation, faux_slam et navigation) ;
  robot       le conteneur g1-jetson sur le Jetson (lancé par g1-jetson demarrer, qui rend la main :
              simulation["en_cours"] dit s'il tourne, jusqu'à « Arrêter »).

Vague 5 (section 12.4 du plan) : arret est le dernier verrou posé ou retiré par l'Atelier (ARRÊT de la
barre d'outils, « Bloquer » et « Débloquer » de Naviguer) : {verrou, depuis, mode, par}, aussi dans
/ws/etat.

Vague 6 (section 13 du plan) : seance est la boîte noire (atelier.seance.GestionnaireSeance, agent Boîte noire) :
reprise des séances interrompues au démarrage, fermeture à l'arrêt ; /ws/etat reçoit seance (la séance ouverte, en
bref), demo (dernier /accueil/etat) et voix (dernier /voix/etat).
"""
import logging
import time

from .pietons import positions_pietons
from .pont_ros import PERIMEE_S, PIETONS_FRAIS_S, PontRos
from .processus import Gestionnaire
from atelier.seance import GestionnaireSeance

JOURNAL = logging.getLogger("atelier.serveur")


class EtatServeur:
    def __init__(self, ros=True):
        self.ros = ros                    # False : pas de pont ROS 2 (tests de l'API)
        self.gestionnaire = Gestionnaire()
        self.pont = PontRos()
        # simulation en cours : {lieu, etage, dossier, monde (Monde ou None), debut, mode, ...}
        self.simulation = None
        # vague 5 (section 12.4) : dernier verrou du pont posé ou retiré par l'Atelier (routes/arret.py)
        self.arret = {"verrou": False, "depuis": None, "mode": None, "par": None}
        # vague 6 (section 13.3) : la boîte noire ; ses méthodes ne lèvent jamais d'exception vers le serveur
        self.seance = GestionnaireSeance(self)

    def demarrer(self):
        if self.ros:
            self.pont.demarrer()
        try:
            self.seance.demarrage_serveur()        # séances restées ouvertes : interrompues (13.3)
        except Exception:       # noqa: BLE001 : la boîte noire ne doit pas empêcher l'Atelier de démarrer
            JOURNAL.exception("boîte noire : reprise des séances impossible")

    def arreter(self):
        try:
            self.seance.fermer("arret_atelier")    # avant les processus : l'enregistrement se ferme proprement
        except Exception:       # noqa: BLE001
            JOURNAL.exception("boîte noire : séance non fermée")
        self.gestionnaire.arreter_tout()
        self.pont.arreter()

    def seance_direct(self):
        """La séance ouverte, en bref (champ seance de /ws/etat), ou None ; jamais d'exception."""
        try:
            return self.seance.etat()
        except Exception:       # noqa: BLE001
            return None

    def simulation_en_cours(self):
        """Vrai si Gazebo tourne (modes simu et repetition)."""
        return self.simulation is not None and self.gestionnaire.en_cours("simulation")

    def mode(self):
        """Mode de la dernière navigation lancée par l'Atelier (simu, repetition, robot), ou None."""
        return None if self.simulation is None else self.simulation.get("mode", "simu")

    def mode_navigation(self):
        """Mode de la navigation qui tourne maintenant, ou None si aucune ne tourne."""
        mode = self.mode()
        if mode == "robot":
            return mode if self.simulation.get("en_cours") else None
        if mode is not None and self.gestionnaire.en_cours("navigation"):
            return mode
        return None

    def temps_simulation(self):
        """Temps simulé (/clock) ; à défaut, secondes écoulées depuis le lancement."""
        t = self.pont.temps_sim() if self.pont.actif else None
        if t is None and self.simulation is not None:
            t = time.time() - self.simulation["debut"]
        return t

    def position_robot(self, pont=None):
        """Position du robot sur la carte : la pose de /reperage/etat en répétition et sur le robot
        (/odom y est l'odométrie locale, pas une position sur la carte) ; /odom sinon."""
        pont = pont or self.pont.etat()
        if self.mode() in ("repetition", "robot"):
            reperage = self.pont.reperage()
            if not reperage or not isinstance(reperage.get("pose"), dict):
                return None
            p = reperage["pose"]
            age = reperage.get("age_recu_s", 0.0) + (reperage.get("age_s") or 0.0)
            return {"x": p["x"], "y": p["y"], "theta": p["theta"], "age_s": round(age, 2),
                    "perimee": age > PERIMEE_S or not reperage.get("repere", False)}
        return pont["robot"]

    def pietons(self, en_cours, t):
        """Piétons à l'écran : ceux de /pietons/etat s'il est frais (piétons crédibles, vague 4), sinon
        recalculés depuis le monde et le temps simulé (contrat 4.4)."""
        if not en_cours:
            return []
        recu = self.pont.dernier("/pietons/etat")
        if recu is not None and recu["age_recu_s"] <= PIETONS_FRAIS_S and isinstance(recu.get("pietons"), list):
            return [p for p in recu["pietons"] if isinstance(p, dict) and {"id", "x", "y"} <= set(p)]
        return positions_pietons(self.simulation["monde"], t)

    def etat_direct(self):
        """Message du WebSocket /ws/etat : {robot, guide, pietons, processus, ...} (contrat 4.4)."""
        pont = self.pont.etat()
        en_cours = self.simulation_en_cours()
        t = self.temps_simulation() if en_cours else None
        sim = None
        if self.simulation is not None:
            sim = {"lieu": self.simulation["lieu"], "etage": self.simulation["etage"], "en_cours": en_cours}
        return {
            "robot": self.position_robot(pont),
            "guide": pont["guide"],
            "pietons": self.pietons(en_cours, t),
            "processus": self.gestionnaire.etat(),
            "simulation": sim,
            "temps_sim": None if t is None else round(t, 2),
            "ros": {"actif": pont["actif"], "erreur": pont["erreur"], "nav2": pont["nav2"]},
            # vague 3 (section 10.8)
            "mode": self.mode() if en_cours or self.mode_navigation() else None,
            "reperage": self.pont.reperage(),
            "pont": self.pont.etat_pont(),
            # vague 4 (section 11) : derniers événements du guide, verrou des mouvements, personnes vues
            "evenements": self.pont.historique("/guide/evenement")[-10:],
            "maitre": self.pont.dernier("/mouvement/maitre"),
            "personnes": self.pont.dernier("/personnes/lidar"),
            "visiteurs": self.pont.dernier("/visiteurs/detectes"),
            # vague 5 (section 12.4) : le verrou posé par l'ARRÊT de l'Atelier
            "arret": dict(self.arret),
            # vague 6 (section 13) : la séance de la boîte noire, la démo d'accueil et la voix
            "seance": self.seance_direct(),
            "demo": self.pont.dernier("/accueil/etat"),
            "voix": self.pont.dernier("/voix/etat"),
        }
