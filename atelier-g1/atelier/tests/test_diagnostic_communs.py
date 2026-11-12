"""Outils communs des tests du diagnostic (vague 6, section 13.2 du plan) : agent Diagnostic. Aucun test ici.

- FauxPont : la partie du PontRos dont le diagnostic se sert (actif, erreur, infos_sujet, appeler_unitree avec la
  même liste blanche, attendre_message, etat_pont, dernier), sans ROS ; robot_state est le vrai service du faux G1
  (ws/src/g1_jumeau/g1_jumeau/etat_robot.py, FauxRobotState), à horloge réelle ; on peut le rendre muet ou lent ;
- faux_systeme(...) : le contenu d'un fichier ATELIER_DIAGNOSTIC_FAUX (câble, connexion, adresse, ROS, pings, ssh du
  Jetson, image du PC) pour un cas donné ; ecrire_faux(chemin, donnees) ; lire_journal(chemin) ;
- GRAPHE_ROBOT, GRAPHE_FAUX_G1 : le graphe ROS 2 vu du serveur avec le vrai robot, et avec le faux G1 seul.
"""
import json
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import atelier
from atelier.lieu.diagnostic import verifier_appel_unitree
from atelier.lieu.equipe import SUJET_ETAT_CAMERA

JUMEAU = atelier.RACINE / "ws" / "src" / "g1_jumeau"
if str(JUMEAU) not in sys.path:
    sys.path.insert(0, str(JUMEAU))
from g1_jumeau.etat_robot import FauxRobotState  # noqa: E402

INCONNU = "_NODE_NAME_UNKNOWN_"      # nom des participants DDS du vrai robot (pas des nœuds ROS 2)
GRAPHE_ROBOT = {
    "/api/sport/request": {"publieurs": [], "abonnes": [INCONNU]},
    "/lf/sportmodestate": {"publieurs": [INCONNU], "abonnes": []},
    "/state_estimator/odom_pelvis": {"publieurs": [INCONNU], "abonnes": []},
    "/api/slam_operate/request": {"publieurs": [], "abonnes": [INCONNU]},
}
GRAPHE_FAUX_G1 = {
    "/api/sport/request": {"publieurs": [], "abonnes": ["g1_jumeau"]},
    "/state_estimator/odom_pelvis": {"publieurs": ["g1_jumeau"], "abonnes": []},
}
EMPREINTE = "sha256:0f1e2d3c4b5a69788796a5b4c3d2e1f00112233445566778899aabbccddeeff0"
URI_ROBOT = ('<CycloneDDS><Domain><General><Interfaces><NetworkInterface name="eno2" priority="default" '
             'multicast="default"/></Interfaces></General></Domain></CycloneDDS>')


class FauxPont:
    """Faux PontRos du diagnostic (sans ROS) : robot_state par FauxRobotState, 7001, batterie, graphe."""

    def __init__(self, actif=True, graphe=None, arretes=(), fsm=501, soc=87, etat_pont=None, camera=None,
                 muet=False, latence=0.0, delai_demarrage_s=0.3, nom_noeud="atelier_pont"):
        self.actif = actif
        self.erreur = None if actif else "ROS 2 est introuvable (essai)"
        self.nom_noeud = nom_noeud
        self.graphe = dict(GRAPHE_ROBOT if graphe is None else graphe)
        self.robot_state = FauxRobotState(time.monotonic, arretes=arretes, delai_demarrage_s=delai_demarrage_s)
        self.fsm = fsm
        self.soc = soc
        self._etat_pont = etat_pont
        self.camera = camera
        self.muet = muet
        self.latence = latence
        self.appels = []              # [(service, api_id, parametre)] : tout ce qui est « envoyé au robot »
        self.messages = []            # [(sujet, type)] demandés à attendre_message
        self._verrou = threading.Lock()

    def infos_sujet(self, sujet):
        if not self.actif:
            return None
        infos = self.graphe.get(sujet, {})
        return {"publieurs": list(infos.get("publieurs", [])), "abonnes": list(infos.get("abonnes", []))}

    def sujets(self):
        return {s: ["inconnu"] for s in self.graphe} if self.actif else {}

    def appeler_unitree(self, service, api_id, parametre="{}", delai=2.0):
        verifier_appel_unitree(service, api_id, parametre)          # la garde du vrai pont, paramètre compris
        if not self.actif:
            raise RuntimeError(self.erreur)
        with self._verrou:
            self.appels.append((service, int(api_id), str(parametre)))
        if self.muet:
            time.sleep(min(delai, 2.0))
            raise TimeoutError(f"personne n'écoute /api/{service}/request : le robot (ou le faux G1) est-il relié ?")
        if self.latence:
            time.sleep(self.latence)
        if service == "robot_state":
            return self.robot_state.traiter(int(api_id), parametre)
        return 0, json.dumps({"data": self.fsm})

    def attendre_message(self, sujet, type_message, delai=2.0):
        if not self.actif:
            raise RuntimeError(self.erreur)
        self.messages.append((sujet, type_message))
        if self.soc is None or self.muet:
            time.sleep(min(delai, 2.0))
            return None
        return SimpleNamespace(soc=self.soc)

    def etat_pont(self):
        return self._etat_pont

    def dernier(self, sujet):
        return self.camera if sujet == SUJET_ETAT_CAMERA else None

    def switchs(self):
        """Les 1001 « reçus » par le robot : [{name, switch}]."""
        return [json.loads(p) for s, a, p in self.appels if s == "robot_state" and a == 1001]

    # le reste du PontRos dont le serveur se sert (démarrage, arrêt, /ws/etat) : sans effet
    def demarrer(self, attente=10.0):
        return self.actif

    def arreter(self):
        return None

    def etat(self):
        return {"actif": self.actif, "erreur": self.erreur, "robot": None, "guide": None, "nav2": None}

    def reperage(self):
        return None

    def historique(self, sujet):
        return []

    def oublier(self):
        return None


def script_jetson(docker="oui", image=EMPREINTE, place_ko=40_000_000, ecart_s=0.0, camera=True, usb=5000):
    """La sortie de SCRIPT_JETSON pour un Jetson donné (heure : maintenant + ecart_s)."""
    lignes = [f"docker_ok={docker}", f"image={image or ''}", f"place_ko={place_ko}", f"place_docker_ko={place_ko}",
              "conteneur="]
    if camera:
        lignes.append(f"camera=/dev/v4l/by-id/usb-e-con_Systems_See3CAM_11CUG_1A15C950-video-index0|/dev/video0|"
                      f"{usb}")
    # « {maintenant} » : l'heure du PC au moment du ssh (faux contexte) ; avec un écart, une heure fixe
    lignes += ["heure={maintenant}" if not ecart_s else f"heure={time.time() + ecart_s:.6f}", "fin=oui"]
    return "\n".join(lignes) + "\n"


def faux_systeme(cable=True, actif=True, autoconnect="yes", profil=True, adresse="192.168.123.99", domaine="0",
                 uri=URI_ROBOT, pings=(0.6, 0.5, 0.9), ssh=None, empreinte_pc=EMPREINTE, delais=None):
    """Le contenu d'un fichier ATELIER_DIAGNOSTIC_FAUX : tout va bien par défaut ; chaque argument change un point.
    pings : (PC1, Jetson, LiDAR) en ms, None : pas de réponse. ssh : {code, sortie, erreur} ; None : un Jetson
    en bonne santé (script_jetson())."""
    from atelier.diagnostic.sondes import COMMANDE_AUTOCONNECT, COMMANDE_EMPREINTE_PC, COMMANDE_PROFILS_ACTIFS, \
        texte_commande
    actives = "Wi-Fi maison:wlo1:activated\n" + ("robot-g1:eno2:activated\n" if actif else "")
    commandes = {texte_commande(COMMANDE_PROFILS_ACTIFS): {"code": 0, "sortie": actives}}
    if profil:
        commandes[texte_commande(COMMANDE_AUTOCONNECT)] = {"code": 0, "sortie": autoconnect + "\n"}
    else:
        commandes[texte_commande(COMMANDE_AUTOCONNECT)] = {
            "code": 10, "sortie": "", "erreur": "Error: robot-g1 - no such connection profile."}
    commandes["nmcli connection up robot-g1"] = {"code": 0, "sortie": "Connection successfully activated\n"}
    commandes["nmcli connection modify robot-g1 connection.autoconnect yes"] = {"code": 0, "sortie": ""}
    if empreinte_pc is not None:
        commandes[texte_commande(COMMANDE_EMPREINTE_PC)] = {"code": 0, "sortie": empreinte_pc + "\n"}
    d = {"fichiers": {"/sys/class/net/eno2/carrier": "1\n" if cable else "0\n",
                      "/sys/class/net/eno2/operstate": "up\n" if cable else "down\n"},
         "commandes": commandes,
         "ping": {"192.168.123.161": pings[0], "192.168.123.164": pings[1], "192.168.123.120": pings[2]},
         "ssh": ssh if ssh is not None else {"code": 0, "sortie": script_jetson()},
         "env": {"ROS_DOMAIN_ID": domaine, "CYCLONEDDS_URI": uri, "ATELIER_INTERFACE_ROBOT": "eno2",
                 "ATELIER_PC1": "192.168.123.161", "ATELIER_JETSON": "192.168.123.164",
                 "ATELIER_LIDAR": "192.168.123.120", "G1_JETSON": "unitree@192.168.123.164"},
         "adresses": {"eno2": adresse} if adresse else {}}
    if delais:
        d["delais"] = dict(delais)
    return d


def ecrire_faux(chemin, donnees):
    Path(chemin).write_text(json.dumps(donnees, ensure_ascii=False, indent=1), encoding="utf-8")
    return Path(chemin)


def lire_journal(chemin):
    """Les lignes du journal du faux contexte (<fichier>.journal)."""
    journal = Path(str(chemin) + ".journal")
    if not journal.is_file():
        return []
    return [json.loads(x) for x in journal.read_text(encoding="utf-8").splitlines() if x.strip()]


def par_id(d):
    """{id: vérification} d'un diagnostic."""
    return {v["id"]: v for v in d["verifications"]}
