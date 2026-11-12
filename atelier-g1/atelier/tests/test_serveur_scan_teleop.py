"""Téléopération du robot simulé (POST /api/simulation/teleop) avec le vrai pont ROS 2 du serveur
et un faux robot qui écoute /cmd_vel : consignes ramenées aux limites, homme mort (vitesse nulle
publiée par le serveur 0,5 s après la dernière consigne), consigne répétée sans arrêt intempestif.

Lancer dans un shell où ROS 2 est chargé (source ~/robot-g1/setup/env.sh), sinon le test est
sauté. Domaine ROS : celui de l'environnement, 53 par défaut (pour ne pas gêner les autres).
"""
import os
import time

import pytest

os.environ.setdefault("ROS_DOMAIN_ID", "53")
rclpy = pytest.importorskip("rclpy", reason="ROS 2 n'est pas chargé : source ~/robot-g1/setup/env.sh")

from geometry_msgs.msg import Twist  # noqa: E402
from rclpy.executors import SingleThreadedExecutor  # noqa: E402

from .outils_scan import creer_session_exemple  # noqa: E402
from .test_serveur_scan_communs import faux_bin, faux_scan, journaux, lieux_scan  # noqa: E402,F401


class FauxCmdVel:
    """Nœud du test : note chaque Twist reçu sur /cmd_vel, avec l'instant de réception."""

    def __init__(self):
        self.contexte = rclpy.Context()
        rclpy.init(context=self.contexte)
        self.noeud = rclpy.create_node("faux_cmd_vel_atelier", context=self.contexte)
        self.recus = []
        self.noeud.create_subscription(Twist, "/cmd_vel", self._recevoir, 10)
        self.executeur = SingleThreadedExecutor(context=self.contexte)
        self.executeur.add_node(self.noeud)

    def _recevoir(self, m):
        self.recus.append((time.monotonic(), round(m.linear.x, 3), round(m.linear.y, 3), round(m.angular.z, 3)))

    def tourner(self, duree, condition=lambda: False):
        fin = time.monotonic() + duree
        while time.monotonic() < fin:
            self.executeur.spin_once(timeout_sec=0.02)
            if condition():
                return True
        return condition()

    def fermer(self):
        self.executeur.shutdown()
        self.noeud.destroy_node()
        rclpy.shutdown(context=self.contexte)


@pytest.fixture
def faux_robot():
    r = FauxCmdVel()
    yield r
    r.fermer()


def test_teleop_limites_et_homme_mort(faux_robot, lieux_scan, faux_scan):
    from fastapi.testclient import TestClient
    from atelier.serveur.main import creer_app
    creer_session_exemple(lieux_scan / "demo", "en_cours", mode="simu")      # un scan du robot simulé
    with TestClient(creer_app(ros=True)) as c:
        assert c.get("/api/etat").json()["ros"]["actif"]
        assert c.get("/api/scan/etat?lieu=demo").json()["actif"]
        # découverte DDS : on envoie l'arrêt jusqu'à ce que le faux robot soit vu
        ecoute = {"n": 0}

        def vu():
            r = c.post("/api/simulation/teleop", json={})
            assert r.status_code == 200, r.text
            ecoute["n"] = r.json()["ecoute"]
            return ecoute["n"] >= 1
        assert faux_robot.tourner(15, vu), "le faux robot n'est jamais vu sur /cmd_vel"
        assert faux_robot.tourner(5, lambda: len(faux_robot.recus) > 0)
        # le publieur est celui du nœud du pont : pas de second participant
        infos = faux_robot.noeud.get_publishers_info_by_topic("/cmd_vel")
        assert [i.node_name for i in infos] == ["atelier_pont"]

        # consigne trop forte : ramenée aux limites du contrat
        faux_robot.recus.clear()
        envoi = time.monotonic()
        r = c.post("/api/simulation/teleop", json={"vx": 2.0, "vy": -1.0, "wz": 0.3})
        assert r.status_code == 200 and r.json()["envoye"] == {"vx": 0.5, "vy": -0.25, "wz": 0.3}
        assert faux_robot.tourner(3, lambda: (0.5, -0.25, 0.3) in [x[1:] for x in faux_robot.recus])
        # on lâche la flèche sans rien envoyer : le serveur publie lui-même l'arrêt après 0,5 s.
        # Délai compté depuis la réception de la consigne (et non depuis l'appel à l'API, qui peut
        # tarder quand le PC est chargé : instable à l'assemblage de la vague 4)
        assert faux_robot.tourner(3, lambda: faux_robot.recus[-1][1:] == (0.0, 0.0, 0.0)), faux_robot.recus
        consigne = max(x[0] for x in faux_robot.recus if x[1:] == (0.5, -0.25, 0.3))
        delai = faux_robot.recus[-1][0] - consigne
        assert 0.4 <= delai <= 1.2, f"arrêt de l'homme mort {delai:.2f} s après la consigne"
        assert faux_robot.recus[-1][0] - envoi >= 0.45
        assert c.app.state.teleop.arrets_auto == 1
        assert faux_robot.tourner(1.0) is False and faux_robot.recus[-1][1:] == (0.0, 0.0, 0.0)   # une seule fois
        n = len(faux_robot.recus)
        faux_robot.tourner(0.5)
        assert len(faux_robot.recus) == n

        # flèche appuyée : consigne répétée toutes les 0,2 s pendant 2 s, sans arrêt au milieu.
        # Un PC très chargé peut espacer deux appels de plus de 0,5 s : l'homme mort a alors raison
        # d'arrêter ; on recommence (3 essais au plus), et on ne juge que des appels assez serrés
        for _essai in range(3):
            faux_robot.recus.clear()
            arrets_avant = c.app.state.teleop.arrets_auto
            appels = []
            fin = time.monotonic() + 2.0
            while time.monotonic() < fin:
                appels.append(time.monotonic())
                assert c.post("/api/simulation/teleop", json={"wz": -0.6}).status_code == 200
                faux_robot.tourner(0.2)
            if max(b - a for a, b in zip(appels, appels[1:])) < 0.45:
                break
            c.post("/api/simulation/teleop", json={"vx": 0, "vy": 0, "wz": 0})
            faux_robot.tourner(1.0)
        assert faux_robot.recus and all(x[1:] == (0.0, 0.0, -0.6) for x in faux_robot.recus), faux_robot.recus
        assert len(faux_robot.recus) >= len(appels) - 2
        assert c.app.state.teleop.arrets_auto == arrets_avant
        # relâchée : l'interface envoie {0, 0, 0}, reçu tout de suite ; l'homme mort n'a plus rien à faire
        assert c.post("/api/simulation/teleop", json={"vx": 0, "vy": 0, "wz": 0}).json()["envoye"] == \
            {"vx": 0.0, "vy": 0.0, "wz": 0.0}
        assert faux_robot.tourner(2, lambda: faux_robot.recus[-1][1:] == (0.0, 0.0, 0.0))
        faux_robot.tourner(1.0)
        assert c.app.state.teleop.arrets_auto == arrets_avant
    assert not c.app.state.atelier.pont.actif
