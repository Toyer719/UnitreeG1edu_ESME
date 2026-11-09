"""Le diagnostic contre le vrai nœud du faux G1, par ROS 2 (vague 6, section 13.2 du plan) : agent Diagnostic.

Le faux G1 seul (ros2 run g1_jumeau jumeau, services_arretes:=lidar_driver,unitree_slam), un faux service de
cartographie réduit à son abonnement (le graphe du robot), le vrai PontRos de l'Atelier, et g1-diagnostic ; dans le
domaine ROS des tests (ROS_DOMAIN_ID de l'environnement), jamais rien vers le vrai robot.

- le diagnostic en répétition : services arrêtés vus par 1003, mode lu par 7001, batterie, sujets, en moins de 10 s ;
- « Démarrer les services » : exactement deux 1001 {"name", "switch": 1} reçus par le faux G1, aucun interdit,
  services actifs, puis tout va bien ;
- g1-diagnostic --json (son propre nœud) : mêmes vérifications, code 1 avec un problème, 0 quand tout va bien ;
  --action demarrer-services avec « oui » ;
- faux G1 muet : « inconnu », rien ne plante, à temps.
"""
import json
import os
import shutil
import signal
import subprocess
import threading
import time

import pytest

import atelier
from atelier.diagnostic import diagnostiquer, faire_action
from atelier.lieu import valider_donnees
from atelier.lieu.diagnostic import code_de_sortie

from .test_diagnostic_communs import par_id

rclpy = pytest.importorskip("rclpy", reason="ROS 2 n'est pas chargé (source ~/robot-g1/setup/env.sh)")
pytestmark = pytest.mark.skipif(shutil.which("ros2") is None, reason="ros2 introuvable")
G1_DIAGNOSTIC = atelier.RACINE / "bin" / "g1-diagnostic"


class Temoin:
    """Un nœud du test, dans son propre contexte : publie /g1_jumeau/services et /g1_jumeau/panne, lit
    /g1_jumeau/etat, et écoute /api/slam_operate/request comme le service de cartographie (graphe du robot)."""

    def __init__(self):
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.qos import QoSProfile, ReliabilityPolicy
        from std_msgs.msg import String
        from unitree_api.msg import Request
        self.contexte = rclpy.Context()
        rclpy.init(context=self.contexte)
        self.noeud = rclpy.create_node("temoin_diagnostic", context=self.contexte)
        fiable = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE)
        self.String = String
        self.pub_services = self.noeud.create_publisher(String, "/g1_jumeau/services", fiable)
        self.pub_panne = self.noeud.create_publisher(String, "/g1_jumeau/panne", fiable)
        self.etat = None
        self.noeud.create_subscription(String, "/g1_jumeau/etat", self._etat, 10)
        self.noeud.create_subscription(Request, "/api/slam_operate/request", lambda m: None, fiable)
        self.executeur = SingleThreadedExecutor(context=self.contexte)
        self.executeur.add_node(self.noeud)
        self.fin = threading.Event()
        self.fil = threading.Thread(target=self._tourner, daemon=True)
        self.fil.start()

    def _tourner(self):
        while not self.fin.is_set() and self.contexte.ok():
            self.executeur.spin_once(timeout_sec=0.1)

    def _etat(self, msg):
        self.etat = (json.loads(msg.data), time.monotonic())

    def services_du_faux_g1(self, apres=None, delai=10.0):
        """Le champ services de /g1_jumeau/etat, reçu après l'instant apres (time.monotonic)."""
        fin = time.monotonic() + delai
        while time.monotonic() < fin:
            if self.etat is not None and (apres is None or self.etat[1] > apres):
                return self.etat[0]["robot"]["services"]
            time.sleep(0.1)
        raise AssertionError("pas de /g1_jumeau/etat du faux G1")

    def publier(self, publieur, donnees, abonnes=1):
        fin = time.monotonic() + 10
        while publieur.get_subscription_count() < abonnes and time.monotonic() < fin:
            time.sleep(0.05)
        publieur.publish(self.String(data=donnees if isinstance(donnees, str) else json.dumps(donnees)))

    def changer_services(self, statuts):
        self.publier(self.pub_services, statuts)
        fin = time.monotonic() + 10
        while time.monotonic() < fin:
            s = self.services_du_faux_g1(apres=time.monotonic() - 0.01)
            if all(s["services"].get(n) == v for n, v in statuts.items()):
                return s
        raise AssertionError(f"le faux G1 n'a pas pris {statuts}")

    def arreter(self):
        self.fin.set()
        self.fil.join(5)
        self.executeur.shutdown()
        self.noeud.destroy_node()
        rclpy.shutdown(context=self.contexte)


@pytest.fixture(scope="module")
def montage(tmp_path_factory):
    """Le faux G1 (services de cartographie arrêtés), le témoin et le PontRos de l'Atelier."""
    sortie = open(tmp_path_factory.mktemp("faux_g1") / "faux_g1.log", "w")
    faux_g1 = subprocess.Popen(["ros2", "run", "g1_jumeau", "jumeau", "--ros-args", "-p",
                                "services_arretes:=lidar_driver,unitree_slam"],
                               stdout=sortie, stderr=subprocess.STDOUT, start_new_session=True)
    temoin = pont = None
    try:
        temoin = Temoin()
        from atelier.serveur.pont_ros import PontRos
        pont = PontRos(nom_noeud="atelier_pont_essai")
        assert pont.demarrer(), pont.erreur
        try:
            depart = temoin.services_du_faux_g1(delai=20)
        except AssertionError:
            pytest.skip("le faux G1 ne démarre pas (g1_jumeau compilé ?)")
        if "switchs" not in depart:
            pytest.skip("le faux G1 compilé n'a pas encore le service robot_state de la vague 6")
        yield {"pont": pont, "temoin": temoin, "faux_g1": faux_g1}
    finally:
        if pont is not None:
            pont.arreter()
        if temoin is not None:
            temoin.arreter()
        try:
            os.killpg(faux_g1.pid, signal.SIGINT)
            faux_g1.wait(10)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            os.killpg(faux_g1.pid, signal.SIGKILL)
        sortie.close()


def test_diagnostic_contre_le_faux_g1(montage):
    montage["temoin"].changer_services({"lidar_driver": 1, "unitree_slam": 1})
    debut = time.monotonic()
    d = diagnostiquer("repetition", pont=montage["pont"])
    assert time.monotonic() - debut < 10.0
    assert valider_donnees("diagnostic", d) == [], valider_donnees("diagnostic", d)
    v = par_id(d)
    assert v["services"]["etat"] == "probleme" and v["services"]["action"] == "demarrer-services"
    assert v["services"]["detail"] == ("Le LiDAR et la cartographie d'Unitree (lidar_driver, unitree_slam) sont "
                                       "arrêtés.")
    assert v["mode"]["etat"] == "ok" and v["mode"]["donnees"]["fsm"] == 501
    assert v["batterie"]["etat"] == "ok" and 80 <= v["batterie"]["donnees"]["soc"] <= 87
    assert v["sujets"]["etat"] == "ok" and v["ros"]["etat"] == "ok"
    assert d["etat"] == "probleme" and code_de_sortie(d) == 1
    appels = montage["temoin"].services_du_faux_g1(apres=time.monotonic())["appels"]
    assert appels["1003"] >= 1 and appels["1001"] == 0


def test_demarrer_les_services_contre_le_faux_g1(montage):
    temoin = montage["temoin"]
    avant = temoin.changer_services({"lidar_driver": 1, "unitree_slam": 1})
    debut = time.monotonic()
    r = faire_action("demarrer-services", "repetition", pont=montage["pont"])
    assert r["ok"] is True and time.monotonic() - debut < 20.0, r
    apres = temoin.services_du_faux_g1(apres=time.monotonic())
    nouveaux = apres["switchs"][len(avant["switchs"]):]
    assert [(s["name"], s["switch"]) for s in nouveaux] == [("lidar_driver", 1), ("unitree_slam", 1)]
    assert apres["nombre_interdits"] == 0 and apres["services"]["lidar_driver"] == 0
    d = diagnostiquer("repetition", pont=montage["pont"])
    assert par_id(d)["services"]["etat"] == "ok" and d["etat"] == "ok" and code_de_sortie(d) == 0


def _g1_diagnostic(*args, entree=None):
    env = dict(os.environ)
    env.pop("ATELIER_DIAGNOSTIC_FAUX", None)
    return subprocess.run([str(G1_DIAGNOSTIC), *args], capture_output=True, text=True, timeout=60, env=env,
                          input=entree)


def test_g1_diagnostic_en_ligne_de_commande(montage):
    temoin = montage["temoin"]
    temoin.changer_services({"lidar_driver": 1, "unitree_slam": 0})
    r = _g1_diagnostic("--mode", "repetition", "--json")
    assert r.returncode == 1, r.stderr[-800:]
    d = json.loads(r.stdout)
    assert valider_donnees("diagnostic", d) == [] and d["source"] == "g1-diagnostic"
    assert par_id(d)["services"]["detail"] == "Le LiDAR (lidar_driver) est arrêté."
    assert par_id(d)["mode"]["etat"] == "ok"
    assert [v["id"] for v in d["verifications"]] == ["ros", "sujets", "services", "mode", "batterie"]
    texte = _g1_diagnostic("--mode", "repetition")
    assert texte.returncode == 1 and "PROBLÈME" in texte.stdout and "g1-diagnostic --action demarrer-services" in \
        texte.stdout.replace(" ", " ")
    temoin.changer_services({"lidar_driver": 0})
    r = _g1_diagnostic("--mode", "repetition", "--json")
    assert r.returncode == 0 and json.loads(r.stdout)["etat"] == "ok", r.stdout[-1500:] + r.stderr[-500:]


def test_g1_diagnostic_action_avec_oui(montage):
    temoin = montage["temoin"]
    avant = temoin.changer_services({"unitree_slam": 1})
    r = _g1_diagnostic("--action", "demarrer-services", "--mode", "repetition", entree="non\n")
    assert r.returncode == 1 and "Rien n'a été envoyé" in r.stdout
    assert len(temoin.services_du_faux_g1(apres=time.monotonic())["switchs"]) == len(avant["switchs"])
    r = _g1_diagnostic("--action", "demarrer-services", "--mode", "repetition", entree="oui\n")
    assert r.returncode == 0 and "La cartographie d'Unitree a démarré" in r.stdout, r.stdout + r.stderr[-800:]
    apres = temoin.services_du_faux_g1(apres=time.monotonic())
    assert [(s["name"], s["switch"]) for s in apres["switchs"][len(avant["switchs"]):]] == [("unitree_slam", 1)]
    assert apres["nombre_interdits"] == 0


def test_faux_g1_muet(montage):
    temoin = montage["temoin"]
    temoin.publier(temoin.pub_panne, "muet")
    time.sleep(0.5)
    try:
        debut = time.monotonic()
        d = diagnostiquer("repetition", pont=montage["pont"])
        assert time.monotonic() - debut < 10.0
        assert valider_donnees("diagnostic", d) == []
        assert par_id(d)["services"]["etat"] == "inconnu" and par_id(d)["mode"]["etat"] == "inconnu"
        r = faire_action("demarrer-services", "repetition", pont=montage["pont"])
        assert r["ok"] is False and "Rien n'a été envoyé" in r["message"]
    finally:
        temoin.publier(temoin.pub_panne, "aucune")
        time.sleep(0.5)
