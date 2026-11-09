"""Tests du pont ROS 2 du serveur (pont_ros.py), avec un faux robot publié par le test.

Le faux robot publie /odom et /guide/etat, et écoute /guide/aller et /guide/stop.
Lancer dans un shell où ROS 2 est chargé (source ~/robot-g1/setup/env.sh), sinon le test est
sauté. Domaine ROS : celui de l'environnement, 34 par défaut (pour ne pas gêner les autres).
"""
import json
import math
import os
import time

import pytest

os.environ.setdefault("ROS_DOMAIN_ID", "34")
rclpy = pytest.importorskip("rclpy", reason="ROS 2 n'est pas chargé : source ~/robot-g1/setup/env.sh")

from geometry_msgs.msg import Quaternion  # noqa: E402
from lifecycle_msgs.srv import GetState  # noqa: E402
from nav_msgs.msg import Odometry  # noqa: E402
from rclpy.executors import SingleThreadedExecutor  # noqa: E402
from rosgraph_msgs.msg import Clock  # noqa: E402
from std_msgs.msg import Empty, String  # noqa: E402

from atelier.lieu import cap_vers_quaternion  # noqa: E402
from atelier.serveur.pont_ros import PontRos  # noqa: E402

from .test_serveur_communs import client, faux_bin, journaux, lieux  # noqa: E402,F401


class FauxRobot:
    """Nœud du test : publie /odom, /guide/etat et /clock ; note ce qui arrive sur /guide/*."""

    def __init__(self):
        self.contexte = rclpy.Context()
        rclpy.init(context=self.contexte)
        self.noeud = rclpy.create_node("faux_robot_atelier", context=self.contexte)
        self.pub_odom = self.noeud.create_publisher(Odometry, "/odom", 10)
        self.pub_etat = self.noeud.create_publisher(String, "/guide/etat", 10)
        self.pub_horloge = self.noeud.create_publisher(Clock, "/clock", 10)
        self.aller, self.stops = [], 0
        self.noeud.create_subscription(String, "/guide/aller", lambda m: self.aller.append(m.data), 10)
        self.noeud.create_subscription(Empty, "/guide/stop", self._stop, 10)
        self.nav2_actif = False
        self.noeud.create_service(GetState, "/bt_navigator/get_state", self._etat_nav2)
        self.executeur = SingleThreadedExecutor(context=self.contexte)
        self.executeur.add_node(self.noeud)

    def _stop(self, _):
        self.stops += 1

    def _etat_nav2(self, demande, reponse):
        """Faux navigateur de Nav2 : « inactive » puis « active »."""
        reponse.current_state.label = "active" if self.nav2_actif else "inactive"
        return reponse

    def publier(self, x, y, theta, etat, t_sim):
        m = Odometry()
        m.header.frame_id, m.child_frame_id = "odom", "base_link"
        m.pose.pose.position.x, m.pose.pose.position.y = x, y
        qx, qy, qz, qw = cap_vers_quaternion(theta)
        m.pose.pose.orientation = Quaternion(x=qx, y=qy, z=qz, w=qw)
        self.pub_odom.publish(m)
        self.pub_etat.publish(String(data=json.dumps(etat)))
        h = Clock()
        h.clock.sec, h.clock.nanosec = int(t_sim), int((t_sim % 1) * 1e9)
        self.pub_horloge.publish(h)

    def tourner(self, duree, condition, publier=None):
        """Fait tourner le nœud jusqu'à ce que condition() soit vraie (ou la fin du délai)."""
        fin = time.monotonic() + duree
        while time.monotonic() < fin:
            if publier:
                publier()
            self.executeur.spin_once(timeout_sec=0.05)
            if condition():
                return True
        return condition()

    def fermer(self):
        self.executeur.shutdown()
        self.noeud.destroy_node()
        rclpy.shutdown(context=self.contexte)


ETAT_GUIDE = {"etat": "en_route", "cible": "b204", "reste_m": 12.5, "itineraire": ["accueil", "hall_nord", "b204"]}


@pytest.fixture
def faux_robot():
    r = FauxRobot()
    yield r
    r.fermer()


def test_pont_position_etat_du_guide_et_commandes(faux_robot):
    pont = PontRos("atelier_pont_test")
    assert pont.demarrer(), pont.erreur
    try:
        assert pont.etat() == {"actif": True, "erreur": None, "robot": None, "guide": None, "nav2": None}
        publier = lambda: faux_robot.publier(1.5, -2.25, 2.0, ETAT_GUIDE, 42.5)      # noqa: E731
        assert faux_robot.tourner(15, lambda: pont.etat()["robot"] and pont.etat()["guide"], publier), \
            "le pont ne reçoit ni /odom ni /guide/etat"
        e = pont.etat()
        assert (e["robot"]["x"], e["robot"]["y"]) == (1.5, -2.25)
        assert e["robot"]["theta"] == pytest.approx(2.0, abs=1e-3) and not e["robot"]["perimee"]
        assert e["guide"]["etat"] == "en_route" and e["guide"]["itineraire"][-1] == "b204"
        assert pont.temps_sim() == pytest.approx(42.5, abs=1.5)
        # Nav2 : vu inactif, puis actif (le pont demande son état chaque seconde)
        assert faux_robot.tourner(10, lambda: pont.etat()["nav2"] is False), "état de Nav2 jamais lu"
        faux_robot.nav2_actif = True
        assert faux_robot.tourner(10, lambda: pont.etat()["nav2"] is True)
        # commandes vers le guide
        assert faux_robot.tourner(10, lambda: pont.abonnes_aller() > 0), "le faux guide n'est pas découvert"
        assert pont.aller("b204") >= 1
        assert faux_robot.tourner(5, lambda: faux_robot.aller == ["b204"])
        assert faux_robot.tourner(10, lambda: pont._pub_stop.get_subscription_count() > 0)
        pont.stop()
        assert faux_robot.tourner(5, lambda: faux_robot.stops == 1)
        # relecture du 01/11/2026 : guides_a_l_ecoute ne compte que les nœuds « guide » (le pont vers la marche
        # écoute aussi /guide/stop) ; le faux robot n'en est pas un
        assert pont.guides_a_l_ecoute() == 0
        guide = rclpy.create_node("guide", context=faux_robot.contexte)
        guide.create_subscription(Empty, "/guide/stop", lambda m: None, 10)
        faux_robot.executeur.add_node(guide)
        try:
            assert faux_robot.tourner(10, lambda: pont.guides_a_l_ecoute() == 1), pont.guides_a_l_ecoute()
            assert pont.stop() == 2
        finally:
            faux_robot.executeur.remove_node(guide)
            guide.destroy_node()
        # /guide/etat qui n'est pas du JSON : gardé tel quel, sans planter
        faux_robot.pub_etat.publish(String(data="pas du json"))
        assert faux_robot.tourner(5, lambda: pont.etat()["guide"]["etat"] == "inconnu")
        pont.oublier()
        assert pont.etat()["robot"] is None
    finally:
        pont.arreter()
    assert not pont.actif
    with pytest.raises(RuntimeError):
        pont.aller("b204")


def test_websocket_alimente_par_le_pont(faux_robot, lieux, faux_bin):
    """Le serveur complet, pont ROS 2 compris : la position du faux robot arrive dans /ws/etat,
    et POST /api/guide/aller la publie sur /guide/aller."""
    from fastapi.testclient import TestClient
    from atelier.serveur.main import creer_app
    with TestClient(creer_app(ros=True)) as c:
        assert c.get("/api/etat").json()["ros"]["actif"]
        publier = lambda: faux_robot.publier(3.0, 4.0, -math.pi / 2, ETAT_GUIDE, 10.0)     # noqa: E731
        etat = c.app.state.atelier
        assert faux_robot.tourner(15, lambda: etat.pont.etat()["robot"] is not None, publier)
        with c.websocket_connect("/ws/etat") as ws:
            m = ws.receive_json()
        assert (m["robot"]["x"], m["robot"]["y"]) == (3.0, 4.0)
        assert m["robot"]["theta"] == pytest.approx(-math.pi / 2, abs=1e-3)
        assert m["guide"]["cible"] == "b204" and m["ros"]["actif"]
        assert faux_robot.tourner(10, lambda: etat.pont.abonnes_aller() > 0)
        r = c.post("/api/guide/aller", json={"cible": "amphi"})
        assert r.status_code == 200 and r.json()["ecoute"] >= 1 and "avertissement" not in r.json()
        assert faux_robot.tourner(5, lambda: faux_robot.aller == ["amphi"])
        assert c.post("/api/guide/stop").json()["envoye"] == "stop"
        assert faux_robot.tourner(5, lambda: faux_robot.stops == 1)
    assert not etat.pont.actif          # arrêté avec le serveur


def test_noeud_observateur():
    """Corrections de la vague 6 : les nœuds de l'Atelier qui ne font qu'écouter le robot ne sont jamais le robot."""
    from atelier.seance.enregistreur import NOEUD_ENREGISTREUR
    from atelier.serveur.pont_ros import noeud_observateur
    from atelier.diagnostic import NOEUD_COMMANDE
    for nom in (NOEUD_ENREGISTREUR, NOEUD_COMMANDE, "atelier_pont", "/atelier_boite_noire", "_ros2cli_12345",
                "_ros2cli_daemon_0_9c1d"):
        assert noeud_observateur(nom), nom
    for nom in ("g1_jumeau", "faux_slam", "guide", "", None, "atelier_boite_noire_2"):
        assert not noeud_observateur(nom), nom


def test_l_enregistreur_de_la_seance_n_est_pas_le_robot(faux_robot, tmp_path, monkeypatch):
    """Corrections de la vague 6 (revue de l'interface, défaut 1) : l'enregistreur de la séance (atelier_boite_noire)
    écoute /api/sport/request ; sans robot ni faux G1, le diagnostic disait « Le PC voit le faux G1, mais pas tout
    (1 sur 2) ». infos_sujet ne le compte plus, et la vérification « sujets » est en Problème en Réel comme en
    répétition ; un vrai abonné (le faux G1) compte toujours."""
    from unitree_api.msg import Request
    from atelier.diagnostic import diagnostiquer
    from atelier.seance.enregistreur import NOEUD_ENREGISTREUR
    faux = tmp_path / "faux_vide.json"
    faux.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("ATELIER_DIAGNOSTIC_FAUX", str(faux))
    pont = PontRos("atelier_pont_test")
    assert pont.demarrer(), pont.erreur
    enregistreur = rclpy.create_node(NOEUD_ENREGISTREUR, context=faux_robot.contexte)
    enregistreur.create_subscription(Request, "/api/sport/request", lambda m: None, 10)
    outil = rclpy.create_node("_ros2cli_4242", context=faux_robot.contexte)
    outil.create_subscription(Request, "/api/sport/request", lambda m: None, 10)
    try:
        # le nœud du test voit bien les deux abonnés dans le graphe…
        assert faux_robot.tourner(10, lambda: len(faux_robot.noeud.get_subscriptions_info_by_topic(
            "/api/sport/request")) >= 2)
        time.sleep(1.0)
        # … mais le pont de l'Atelier ne les compte pas
        assert pont.infos_sujet("/api/sport/request") == {"publieurs": [], "abonnes": []}
        for mode in ("repetition", "reel"):
            r = diagnostiquer(mode, pont, source="atelier", rapide=True)
            sujets = next(v for v in r["verifications"] if v["id"] == "sujets")
            assert sujets["etat"] == "probleme", (mode, sujets)
            assert "mais pas tout" not in sujets["detail"], sujets
        # un vrai abonné (le faux G1) compte toujours
        jumeau = rclpy.create_node("g1_jumeau", context=faux_robot.contexte)
        jumeau.create_subscription(Request, "/api/sport/request", lambda m: None, 10)
        try:
            assert faux_robot.tourner(10, lambda: (pont.infos_sujet("/api/sport/request") or {}).get("abonnes")
                                      == ["g1_jumeau"]), pont.infos_sujet("/api/sport/request")
        finally:
            jumeau.destroy_node()
    finally:
        enregistreur.destroy_node()
        outil.destroy_node()
        pont.arreter()
