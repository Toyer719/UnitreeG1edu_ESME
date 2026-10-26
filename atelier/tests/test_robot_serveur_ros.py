"""Tests de l'API du repérage avec ROS 2 (section 10.8 du plan) : un faux relais odom_vers_tf du
test répond aux demandes de repérage comme le vrai (en_cours, puis repere ou echec) ; verrou
/pont/arret en transient_local. Sautés si ROS 2 n'est pas chargé (source ~/robot-g1/setup/env.sh).
Domaine ROS : $ROS_DOMAIN_ID, 63 par défaut (agent Repérage).
"""
import json
import os
import threading

import pytest

os.environ.setdefault("ROS_DOMAIN_ID", "63")

from .test_robot_serveur import _demarrer, _erreur, _generer  # noqa: E402
from .test_serveur_communs import attendre, faux_bin, journaux, lieux  # noqa: E402,F401

rclpy = pytest.importorskip("rclpy", reason="ROS 2 n'est pas chargé : source ~/robot-g1/setup/env.sh")


class FauxRelais:
    """Faux odom_vers_tf : /reperage/etat à 10 Hz, répond aux demandes ; écoute /pont/arret ;
    publie un /pont/etat. reponse : « repere », « echec » ou « rien » (ne répond pas)."""

    def __init__(self):
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
        from std_msgs.msg import Bool, String
        self.String = String
        self.contexte = rclpy.Context()
        rclpy.init(context=self.contexte)
        self.noeud = rclpy.create_node("faux_relais_atelier", context=self.contexte)
        self.pub = self.noeud.create_publisher(String, "/reperage/etat", 10)
        self.pub_pont = self.noeud.create_publisher(String, "/pont/etat", 10)
        self.demandes, self.verrous = [], []
        self.reponse = "repere"
        self.etat = self._etat("non_repere", None)
        self.noeud.create_subscription(String, "/reperage/demander", self._sur_demande, 10)
        verrou = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                            durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.noeud.create_subscription(Bool, "/pont/arret", lambda m: self.verrous.append(m.data), verrou)
        self.noeud.create_timer(0.1, self._publier)
        self.executeur = SingleThreadedExecutor(context=self.contexte)
        self.executeur.add_node(self.noeud)
        self._fin = threading.Event()
        self._fil = threading.Thread(target=self._tourner, daemon=True)
        self._fil.start()

    @staticmethod
    def _etat(etat, demande, pose=None, message="faux relais"):
        return {"version": 1, "etat": etat, "repere": etat == "repere", "localisation": "unitree",
                "message": message, "pose": pose, "precision_m": 0.02 if pose else None,
                "age_s": 0.05 if pose else None, "demande": demande, "carte": "repetition.pcd",
                "repere_unitree": {"x": 2.5, "y": 10.0, "theta": 0.0}, "sauts": 0}

    def _tourner(self):
        while not self._fin.is_set():
            self.executeur.spin_once(timeout_sec=0.05)

    def _publier(self):
        self.pub.publish(self.String(data=json.dumps(self.etat)))
        pont = {"version": 1, "etat": "pret" if self.etat["repere"] else "attente_reperage",
                "message": "faux pont", "mouvement_permis": self.etat["repere"]}
        self.pub_pont.publish(self.String(data=json.dumps(pont)))

    def _sur_demande(self, msg):
        d = json.loads(msg.data)
        self.demandes.append(d)
        if self.reponse == "rien":
            return
        self.etat = self._etat("en_cours", d["id"])
        self._publier()
        if self.reponse == "repere":
            pose = {"x": d.get("x", 2.5), "y": d.get("y", 10.0), "theta": d.get("theta", 0.0)}
            self.etat = self._etat("repere", d["id"], pose, "Robot repéré sur la carte (précision 2 cm).")
        else:
            self.etat = self._etat("echec", d["id"], None, "Le robot s'est repéré à 1.2 m de la position annoncée.")
        self._publier()

    def fermer(self):
        self._fin.set()
        self._fil.join(timeout=3)
        self.executeur.shutdown()
        self.noeud.destroy_node()
        rclpy.shutdown(context=self.contexte)


@pytest.fixture
def faux_relais():
    r = FauxRelais()
    yield r
    r.fermer()


def test_reperer_par_le_relais(faux_relais, lieux, faux_bin, monkeypatch):
    from fastapi.testclient import TestClient
    from atelier.serveur.main import creer_app
    from atelier.serveur.routes import robot
    with TestClient(creer_app(ros=True)) as c:
        etat = c.app.state.atelier
        assert attendre(lambda: etat.pont.actif, 10)
        _generer(c)
        assert _demarrer(c, "repetition").status_code == 200
        assert attendre(lambda: etat.pont.reperage() is not None and etat.pont.abonnes_reperage() > 0, 15)
        e = c.get("/api/robot/etat").json()
        assert e["etat"] == "non_repere" and e["pont"]["etat"] == "attente_reperage"
        # à la marque : pas de pose dans la demande
        r = c.post("/api/robot/reperer", json={"lieu": "demo", "etage": "rdc"})
        assert r.status_code == 200, r.text
        e = r.json()
        assert e["repere"] and e["etat"] == "repere" and e["position"] == {"x": 2.5, "y": 10.0, "theta": 0.0}
        assert e["precision_m"] == 0.02 and "précision 2 cm" in e["message"]
        assert set(faux_relais.demandes[-1]) == {"id"} and faux_relais.demandes[-1]["id"] == e["demande"]
        # le robot est sur la carte : /ws/etat donne la pose du repérage, « Y aller » passe
        with c.websocket_connect("/ws/etat") as ws:
            m = ws.receive_json()
        assert m["mode"] == "repetition" and m["reperage"]["repere"]
        assert (m["robot"]["x"], m["robot"]["y"]) == (2.5, 10.0) and not m["robot"]["perimee"]
        assert c.post("/api/guide/aller", json={"cible": "b204"}).status_code == 200
        # ailleurs que sur la marque : x, y, cap → x, y, theta
        r = c.post("/api/robot/reperer", json={"lieu": "demo", "etage": "rdc", "x": 3.0, "y": 9.5, "cap": 0.5})
        assert r.status_code == 200
        d = faux_relais.demandes[-1]
        assert (d["x"], d["y"], d["theta"]) == (3.0, 9.5, 0.5)
        # échec du relais : 502, avec son message
        faux_relais.reponse = "echec"
        d = _erreur(c.post("/api/robot/reperer", json={"lieu": "demo", "etage": "rdc"}), 502)
        assert "position annoncée" in d["detail"]
        assert "Repérez" in _erreur(c.post("/api/guide/aller", json={"cible": "b204"}), 409)["detail"]
        # pas de réponse : 504 (délai raccourci pour le test)
        faux_relais.reponse = "rien"
        monkeypatch.setattr(robot, "DELAI_REPERAGE_S", 1.5)
        _erreur(c.post("/api/robot/reperer", json={"lieu": "demo", "etage": "rdc"}), 504)
        # verrou du pont
        r = c.post("/api/robot/arret", json={"verrou": True})
        assert r.status_code == 200 and r.json()["verrou"] is True and r.json()["pont"]["etat"]
        assert attendre(lambda: faux_relais.verrous[-1:] == [True], 5)
        c.post("/api/robot/arret", json={"verrou": False})
        assert attendre(lambda: faux_relais.verrous[-1:] == [False], 5)
        c.post("/api/simulation/arreter")


def test_verrou_entendu_par_un_pont_lance_apres(lieux, faux_bin):
    """/pont/arret est transient_local : un pont qui démarre après le clic reçoit le verrou."""
    from fastapi.testclient import TestClient
    from atelier.serveur.main import creer_app
    with TestClient(creer_app(ros=True)) as c:
        assert attendre(lambda: c.app.state.atelier.pont.actif, 10)
        r = c.post("/api/robot/arret", json={"verrou": True})
        assert r.status_code == 200 and "avertissement" in r.json()
        relais = FauxRelais()
        try:
            assert attendre(lambda: relais.verrous == [True], 10)
        finally:
            relais.fermer()
