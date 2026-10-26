"""Routes de la simulation et du guide.

  POST /api/simulation/demarrer {lieu, etage, fenetre?, navigation?, mode?}
        mode simu (défaut) :
          g1-monde simuler --lieu L --etage E --sans-fenetre  (Gazebo, robot proxy, piétons)
          puis g1-guide navigation --lieu L --etage E --simu  (Nav2, routeur, guide)
        mode repetition (le niveau 2 du vrai robot, sans robot, section 10.8 du plan) :
          g1-monde simuler ... --jumeau (Gazebo et le faux G1), g1-slam faux-service --jumeau
          --bruit 0.01 (faux slam_operate, 1 cm de bruit), g1-guide navigation ... --simu
          --localisation unitree (relais,
          pont, Nav2, guide) : aucune vitesse ne va directement à Gazebo
        mode robot : g1-jetson demarrer --lieu L --etage E (navigation dans le conteneur du
          Jetson) ; seulement au câble, serveur lancé après source ~/robot-g1/setup/robot.sh
  POST /api/simulation/arreter      arrête tout ce qui a été lancé (mode robot : g1-jetson arreter)
  GET  /api/simulation/etat         processus, simulation en cours, pont ROS 2
  POST /api/guide/aller {cible}     publie l'id sur /guide/aller (répétition et robot : 409 tant que
                                    le robot n'est pas repéré)
  POST /api/guide/stop              publie sur /guide/stop (à défaut : g1-guide stop)
  POST /api/simulation/teleop {vx, vy, wz}   pilote le robot simulé (flèches de l'onglet Scan) :
        publie /cmd_vel par le pont ROS 2, avec un homme mort (vitesse nulle après 0,5 s sans consigne) ;
        en répétition, /cmd_vel passe par le pont vers le faux G1 ; refusée avec le vrai robot
"""
import math
import os
import threading
import time

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from atelier.lieu import (MODES_NAVIGATION, ErreurLieu, charger_itineraires, charger_monde, charger_salles,
                          chemin_carte, chemin_monde, chemin_sdf)

from ..communs import ErreurAtelier, dossier_du_lieu, etage_du_lieu, exiger_point_principal, verifier_id
from ..processus import CommandeAbsente, commande, lancer_et_attendre
from .scan import cable_branche, interface_robot, scan_robot_simule_actif

routeur = APIRouter(tags=["simulation et guide"])

LIMITES_TELEOP = {"vx": 0.5, "vy": 0.25, "wz": 0.8}     # m/s, m/s, rad/s (contrat 9.7)
HOMME_MORT_S = 0.5      # s sans consigne : le serveur publie lui-même une vitesse nulle
DELAI_JETSON_S = 90.0   # g1-jetson demarrer rend la main quand le conteneur tourne (30 s au plus)
# Rôles des processus, dans l'ordre de lancement (arrêtés dans l'ordre inverse)
ROLES = ("simulation", "faux_slam", "navigation")
# Répétition : écart-type de position ajouté par le faux slam_operate à la relocalisation (m), pour
# que la correction map → odom soit éprouvée comme avec le vrai robot (g1-slam ... --bruit)
BRUIT_REPETITION_M = 0.01
MESSAGE_REPERER = ("Repérez d'abord le robot : posez-le sur la marque au sol, tourné dans le sens de la "
                   "flèche, puis cliquez sur « Repérer le robot ».")


class DemandeSimulation(BaseModel):
    lieu: str
    etage: str
    fenetre: bool = False        # True : fenêtre de Gazebo en plus (jamais pendant les tests)
    navigation: bool = True      # False : Gazebo seul, sans Nav2 ni guide
    mode: str = "simu"           # simu, repetition ou robot (section 10.8)


class DemandeAller(BaseModel):
    cible: str


class DemandeTeleop(BaseModel):
    vx: float = 0.0          # m/s vers l'avant
    vy: float = 0.0          # m/s vers la gauche (pas de côté)
    wz: float = 0.0          # rad/s, sens inverse des aiguilles d'une montre


def _etat(request):
    return request.app.state.atelier


def etat_simulation(etat):
    pont = etat.pont.etat()
    return {"simulation": None if etat.simulation is None else
            {"lieu": etat.simulation["lieu"], "etage": etat.simulation["etage"],
             "en_cours": etat.simulation_en_cours() or etat.mode_navigation() == "robot",
             "mode": etat.mode(), "avertissements": etat.simulation["avertissements"]},
            "processus": etat.gestionnaire.etat(),
            "ros": {"actif": pont["actif"], "erreur": pont["erreur"],
                    "guide_ecoute": etat.pont.abonnes_aller()}}


def verifier_terminal_robot():
    """Mode robot : le câble (carrier, rien n'est envoyé) et le terminal relié au robot. 409 sinon."""
    interface = interface_robot()
    if os.environ.get("G1_SLAM_FAUX") == "1":
        raise ErreurAtelier(409, "Le vrai robot est interdit pendant les essais (G1_SLAM_FAUX=1) : utilisez "
                                 "la répétition sans robot.")
    if not cable_branche(interface):
        raise ErreurAtelier(409, f"Robot non détecté : branchez le câble Ethernet entre le PC et le robot (port "
                                 f"{interface}), puis réessayez. Pour essayer sans robot : « Répétition sans robot ».")
    uri = os.environ.get("CYCLONEDDS_URI", "")
    domaine = os.environ.get("ROS_DOMAIN_ID", "0") or "0"
    if f'"{interface}"' not in uri or domaine != "0":
        raise ErreurAtelier(409, "Le serveur de l'Atelier n'a pas été lancé dans un terminal relié au robot : "
                                 "fermez-le (Ctrl+C), puis dans un terminal : source ~/robot-g1/setup/robot.sh, "
                                 "puis g1-atelier.")


async def _demarrer_robot(etat, demande, dossier):
    verifier_terminal_robot()
    if commande("g1-jetson") is None:
        raise ErreurAtelier(503, "Impossible de lancer la navigation du robot : la commande g1-jetson n'est pas "
                                 "installée (agent Jetson).")
    r = await run_in_threadpool(lancer_et_attendre, "g1-jetson",
                                ["demarrer", "--lieu", dossier, "--etage", demande.etage], DELAI_JETSON_S)
    if r["code"] != 0:
        lignes = [x for x in r["sortie"].strip().splitlines() if x.strip()]
        raise ErreurAtelier(502, "Le conteneur du robot n'a pas démarré : "
                                 + (lignes[-1] if lignes else "g1-jetson demarrer a échoué") + ".",
                            sortie=r["sortie"])
    return r["sortie"]


@routeur.post("/api/simulation/demarrer")
async def demarrer(demande: DemandeSimulation, request: Request):
    etat = _etat(request)
    dossier = dossier_du_lieu(demande.lieu)
    etage_du_lieu(dossier, demande.etage)
    exiger_point_principal(dossier)          # vague 4 (section 11.2) : livré par l'intégrateur
    mode = demande.mode
    if mode not in MODES_NAVIGATION:
        raise ErreurAtelier(400, f"Mode « {mode} » inconnu : simu (simulation), repetition (répétition sans "
                                 "robot) ou robot.")
    if mode != "simu" and not demande.navigation:
        raise ErreurAtelier(400, "La répétition et le mode robot font toujours tourner la navigation "
                                 "(navigation: false n'est possible qu'en simulation).")
    if etat.simulation_en_cours() or etat.mode_navigation() == "robot":
        s = etat.simulation
        raise ErreurAtelier(409, f"Une simulation tourne déjà (lieu « {s['lieu']} », étage « {s['etage']} ») : "
                                 "arrêtez-la d'abord avec « Arrêter la simulation ».")
    if mode == "robot":
        if not chemin_carte(dossier, demande.etage).is_file():
            raise ErreurAtelier(409, "Cet étage n'a pas de carte 2D : le guide ne peut pas naviguer. Faites d'abord "
                                     "un scan avec le robot (onglet Scan).")
        etat.pont.oublier()
        sortie = await _demarrer_robot(etat, demande, dossier)
        etat.simulation = {"lieu": demande.lieu, "etage": demande.etage, "dossier": str(dossier), "monde": None,
                           "debut": time.time(), "avertissements": [], "mode": "robot", "en_cours": True,
                           "sortie": sortie}
        return etat_simulation(etat)
    if commande("g1-monde") is None:
        raise ErreurAtelier(503, "Impossible de lancer la simulation : la commande g1-monde n'est pas "
                                 "encore installée (agent Monde).")
    if mode == "repetition":
        for nom in ("g1-slam", "g1-guide"):
            if commande(nom) is None:
                raise ErreurAtelier(503, f"Impossible de lancer la répétition : la commande {nom} n'est pas "
                                         "installée.")
    if not chemin_sdf(dossier, demande.etage).is_file():
        raise ErreurAtelier(409, "Le monde Gazebo de cet étage n'existe pas encore : dans l'onglet Carte, "
                                 "cliquez sur « Fabriquer la carte », puis relancez la simulation.")
    avertissements = []
    navigation = demande.navigation
    if navigation and not chemin_carte(dossier, demande.etage).is_file():
        raise ErreurAtelier(409, "Cet étage n'a pas de carte 2D : le guide ne peut pas naviguer. Dans "
                                 "l'onglet Carte, cliquez sur « Fabriquer la carte ».")
    if navigation and mode == "simu" and commande("g1-guide") is None:
        navigation = False
        avertissements.append("La commande g1-guide n'est pas encore installée : la simulation tourne "
                              "sans guide (le bouton « Y aller » ne fera rien).")
    monde = None
    if chemin_monde(dossier, demande.etage).is_file():
        try:
            monde = charger_monde(dossier, demande.etage)
        except ErreurLieu:
            avertissements.append("Le monde de cet étage est invalide : les piétons ne s'afficheront pas.")

    etat.pont.oublier()
    arguments = ["simuler", "--lieu", dossier, "--etage", demande.etage]
    if not demande.fenetre:
        arguments.append("--sans-fenetre")
    navigation_args = ["navigation", "--lieu", dossier, "--etage", demande.etage, "--simu"]
    if mode == "repetition":
        arguments.append("--jumeau")
        navigation_args += ["--localisation", "unitree"]
    infos = {"lieu": demande.lieu, "etage": demande.etage, "mode": mode}
    try:
        await run_in_threadpool(etat.gestionnaire.lancer, "simulation", "g1-monde", arguments, infos)
        if mode == "repetition":
            await run_in_threadpool(etat.gestionnaire.lancer, "faux_slam", "g1-slam",
                                    ["faux-service", "--jumeau", "--lieu", dossier, "--etage", demande.etage,
                                     "--bruit", f"{BRUIT_REPETITION_M:g}"],
                                    infos)
        if navigation:
            await run_in_threadpool(etat.gestionnaire.lancer, "navigation", "g1-guide", navigation_args, infos)
    except CommandeAbsente as e:
        for role in reversed(ROLES):
            await run_in_threadpool(etat.gestionnaire.arreter, role)
        raise ErreurAtelier(503, f"Impossible de lancer la simulation : {e}.") from None
    etat.simulation = {"lieu": demande.lieu, "etage": demande.etage, "dossier": str(dossier),
                       "monde": monde, "debut": time.time(), "avertissements": avertissements, "mode": mode}
    return etat_simulation(etat)


@routeur.post("/api/simulation/arreter")
async def arreter(request: Request):
    etat = _etat(request)
    if etat.mode() == "robot" and etat.simulation.get("en_cours"):
        r = await run_in_threadpool(lancer_et_attendre, "g1-jetson", ["arreter"], 60.0) \
            if commande("g1-jetson") is not None else {"code": None, "sortie": "g1-jetson absent"}
        etat.simulation["en_cours"] = False
        if r["code"] != 0:
            raise ErreurAtelier(502, "Le conteneur du robot ne s'est pas arrêté proprement : vérifiez avec "
                                     "g1-jetson etat, puis g1-jetson arreter.", sortie=r["sortie"])
        return etat_simulation(etat)
    # la navigation d'abord, puis le faux slam_operate, puis Gazebo (le faux service du scan continue)
    for role in reversed(ROLES):
        await run_in_threadpool(etat.gestionnaire.arreter, role)
    return etat_simulation(etat)


@routeur.get("/api/simulation/etat")
def lire_etat(request: Request):
    return etat_simulation(_etat(request))


def robot_repere(etat):
    """Vrai si le dernier /reperage/etat (frais) dit le robot repéré."""
    reperage = etat.pont.reperage()
    return bool(reperage and reperage.get("repere") and not reperage.get("perime"))


@routeur.post("/api/guide/aller")
def aller(demande: DemandeAller, request: Request):
    etat = _etat(request)
    cible = verifier_id(demande.cible.strip(), "identifiant de salle ou de nœud")
    if etat.mode_navigation() in ("repetition", "robot") and not robot_repere(etat):
        raise ErreurAtelier(409, MESSAGE_REPERER)
    if etat.simulation is not None:
        # cible connue du lieu simulé ? (sinon le guide la refuserait sans rien dire)
        dossier = dossier_du_lieu(etat.simulation["lieu"])
        try:
            connus = {s.id for s in charger_salles(dossier)} | set(charger_itineraires(dossier).noeuds)
        except ErreurLieu:
            connus = None
        if connus is not None and cible not in connus:
            raise ErreurAtelier(404, f"« {cible} » n'est ni une salle ni un nœud du lieu "
                                     f"« {etat.simulation['lieu']} ». Placez-la dans l'onglet Salles.")
    if not etat.pont.actif:
        raise ErreurAtelier(503, "Pas de liaison avec ROS 2 : "
                            + (etat.pont.erreur or "le pont ROS 2 du serveur n'est pas démarré") + ".")
    ecoute = etat.pont.aller(cible)
    reponse = {"envoye": cible, "ecoute": ecoute}
    if ecoute == 0:
        reponse["avertissement"] = ("Aucun guide n'écoute /guide/aller : lancez la simulation (avec la "
                                    "navigation) ou g1-guide navigation.")
    return reponse


@routeur.post("/api/guide/stop")
async def stop(request: Request):
    etat = _etat(request)
    if etat.pont.actif:
        return {"envoye": "stop", "ecoute": etat.pont.stop()}
    # sans pont ROS 2, on passe par la commande du guide
    try:
        resultat = await run_in_threadpool(lancer_et_attendre, "g1-guide", ["stop"], 15.0)
    except CommandeAbsente:
        raise ErreurAtelier(503, "Impossible d'envoyer l'arrêt : pas de liaison ROS 2 et pas de commande "
                                 "g1-guide. Arrêtez la simulation.") from None
    if resultat["code"] != 0:
        raise ErreurAtelier(500, "g1-guide stop a échoué : arrêtez la simulation.", sortie=resultat["sortie"])
    return {"envoye": "stop", "par": "g1-guide stop"}


# ---------------------------------------------------------------- téléopération du robot simulé

class Teleop:
    """Publie les consignes de vitesse sur /cmd_vel (geometry_msgs/Twist) par le nœud du pont ROS 2.

    Homme mort : le VelocityControl de Gazebo garde la dernière consigne reçue. Sans nouvelle consigne
    non nulle pendant homme_mort secondes, un fil publie donc lui-même une vitesse nulle. L'interface
    renvoie la consigne toutes les 0,2 s tant qu'une flèche est appuyée, puis {0, 0, 0}."""

    def __init__(self, pont, homme_mort=HOMME_MORT_S):
        self.pont = pont
        self.homme_mort = homme_mort
        self.arrets_auto = 0         # vitesses nulles publiées par l'homme mort
        self._verrou = threading.Lock()
        self._pub = None
        self._noeud = None
        self._Twist = None
        self._derniere = None        # instant de la dernière consigne non nulle ; None : robot à l'arrêt
        self._fil = None

    def _publier(self, vx, vy, wz):
        # le publieur vit sur le nœud du pont (même paquet) : pas de second participant DDS ;
        # il est refait si le pont a redémarré
        noeud = self.pont._noeud
        if noeud is None or not self.pont.actif:
            raise RuntimeError(self.pont.erreur or "le pont ROS 2 n'est pas démarré")
        if self._pub is None or self._noeud is not noeud:
            from geometry_msgs.msg import Twist
            self._Twist = Twist
            self._pub = noeud.create_publisher(Twist, "/cmd_vel", 10)
            self._noeud = noeud
        m = self._Twist()
        m.linear.x, m.linear.y, m.angular.z = float(vx), float(vy), float(wz)
        self._pub.publish(m)
        return self._pub.get_subscription_count()

    def envoyer(self, vx, vy, wz):
        """Publie une consigne. Renvoie le nombre d'abonnés à /cmd_vel (0 : personne n'écoute)."""
        with self._verrou:
            ecoute = self._publier(vx, vy, wz)
            if vx or vy or wz:
                self._derniere = time.monotonic()
                if self._fil is None:
                    self._fil = threading.Thread(target=self._veiller, name="homme mort /cmd_vel", daemon=True)
                    self._fil.start()
            else:
                self._derniere = None
        return ecoute

    def _veiller(self):
        while True:
            time.sleep(0.05)
            with self._verrou:
                if self._derniere is not None and time.monotonic() - self._derniere < self.homme_mort:
                    continue
                if self._derniere is not None:
                    self._derniere = None
                    try:
                        self._publier(0.0, 0.0, 0.0)
                        self.arrets_auto += 1
                    except Exception:      # noqa: BLE001 : pont arrêté entre-temps (le serveur s'arrête)
                        pass
                self._fil = None
                return


def _teleop(request):
    t = getattr(request.app.state, "teleop", None)
    if t is None:
        t = request.app.state.teleop = Teleop(_etat(request).pont)
    return t


@routeur.post("/api/simulation/teleop")
def teleop(demande: DemandeTeleop, request: Request):
    etat = _etat(request)
    valeurs = {"vx": demande.vx, "vy": demande.vy, "wz": demande.wz}
    for nom, v in valeurs.items():
        if not math.isfinite(v):
            raise ErreurAtelier(400, f"« {nom} » doit être un nombre fini (m/s ou rad/s), pas {v}.")
    if etat.mode_navigation() == "robot":
        raise ErreurAtelier(409, "Le vrai robot se pilote à sa télécommande, pas depuis l'Atelier.")
    if not (etat.simulation_en_cours() or scan_robot_simule_actif(request.app)):
        raise ErreurAtelier(409, "Il n'y a pas de robot simulé à piloter : lancez la simulation (onglet Simulation), "
                                 "ou un scan en mode simulation ou en répétition sans robot (onglet Scan). Le vrai "
                                 "robot se pilote à sa télécommande.")
    if not etat.pont.actif:
        raise ErreurAtelier(503, "Pas de liaison avec ROS 2 : "
                            + (etat.pont.erreur or "le pont ROS 2 du serveur n'est pas démarré") + ".")
    # ramenées aux limites du contrat ; « + 0.0 » évite d'écrire -0.0
    consigne = {nom: round(max(-LIMITES_TELEOP[nom], min(LIMITES_TELEOP[nom], v)), 3) + 0.0
                for nom, v in valeurs.items()}
    try:
        ecoute = _teleop(request).envoyer(**consigne)
    except RuntimeError as e:
        raise ErreurAtelier(503, f"Pas de liaison avec ROS 2 : {e}.") from None
    reponse = {"envoye": consigne, "ecoute": ecoute}
    if ecoute == 0:
        reponse["avertissement"] = ("Personne n'écoute /cmd_vel : le robot simulé n'est peut-être pas encore "
                                    "apparu dans Gazebo.")
    return reponse
