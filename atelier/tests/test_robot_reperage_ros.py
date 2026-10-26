"""Repérage de bout en bout en ROS 2, sans Gazebo (sections 10.5 et 10.6 du plan).

Les vrais programmes : g1-slam faux-service --jumeau (faux slam_operate de la répétition) et le
relais odom_vers_tf (paquet g1_nav), dans des sous-processus. Le robot est le FauxRobot de
test_robot_communs : vérité terrain /g1_jumeau/odom, odométrie locale qui dérive
/state_estimator/odom_pelvis, nuage /g1_jumeau/points d'un mur connu (x = 6 m).
On vérifie : la commande 1804 (pose, carte), map → base_link contre la vérité malgré la dérive,
/points remis dans le repère lidar, la perte de la relocalisation (perdu, puis repere), le
repère d'Unitree tourné de la variante B du critère 18 (refus à la marque, réussite ailleurs),
le refus de 1102 en répétition, le bruit et le retard. Sautés sans ROS 2 ou sans unitree_api.
Domaine ROS : $ROS_DOMAIN_ID, 63 par défaut (agent Repérage).
"""
import json
import math
import os
import time

import pytest

os.environ.setdefault("ROS_DOMAIN_ID", "63")
pytest.importorskip("rclpy", reason="ROS 2 n'est pas chargé : source ~/robot-g1/setup/env.sh")
pytest.importorskip("unitree_api.msg", reason="messages unitree_api absents (env.sh)")

from atelier.lieu import (Pose, carte_vers_unitree, charger_fiche, copier_lieu,  # noqa: E402
                          enregistrer_fiche, quaternion_vers_cap, valider_message)

from .test_robot_communs import (RACINE, Ecoute, FauxRobot, arreter, ecart, faux_service,  # noqa: E402
                                 journal, relais)

MARQUE = (2.5, 10.0, 0.0)


@pytest.fixture
def lieu(tmp_path):
    return copier_lieu(RACINE / "lieux" / "demo", tmp_path / "lieux" / "essai")


class Chaine:
    """Faux robot, écoute, faux service et relais ; tout est arrêté par fermer()."""

    def __init__(self, dossier, tmp_path, repere=MARQUE, options_faux=(), **parametres_relais):
        self.robot = FauxRobot(depart=parametres_relais.pop("depart", MARQUE))
        self.ecoute = Ecoute()
        self.journal_faux = tmp_path / "faux.log"
        self.journal_relais = tmp_path / "relais.log"
        self.faux = faux_service(dossier, self.journal_faux, *options_faux)
        self.relais = relais(dossier, self.journal_relais, repere=repere, **parametres_relais)
        self.codes = None
        assert self.ecoute.attendre(lambda: self.ecoute.dernier() is not None, 30), \
            f"pas de /reperage/etat ; relais : {journal(self.journal_relais)[-2000:]}"
        assert self.ecoute.attendre(lambda: "prêt" in journal(self.journal_faux), 30), journal(self.journal_faux)
        time.sleep(1.0)          # que le faux service reçoive la vérité terrain

    def reperer(self, ident, *pose, delai=20.0):
        self.ecoute.demander(ident, *pose)
        ok = self.ecoute.attendre(lambda: self.ecoute.dernier()["demande"] == ident
                                  and self.ecoute.dernier()["etat"] in ("repere", "echec"), delai)
        assert ok, f"pas de réponse au repérage {ident} : {self.ecoute.dernier()}"
        return self.ecoute.dernier()

    def requetes_1804(self):
        return [r for r in self.ecoute.requetes if r.header.identity.api_id == 1804]

    def fermer(self):
        self.codes = (arreter(self.relais), arreter(self.faux))
        self.ecoute.fermer()
        self.robot.fermer()


@pytest.fixture
def chaine(lieu, tmp_path):
    faites = []

    def fabriquer(**options):
        c = Chaine(lieu, tmp_path, **options)
        faites.append(c)
        return c
    yield fabriquer
    for c in faites:
        c.fermer()
        assert c.codes == (0, 0), (c.codes, journal(c.journal_relais)[-1500:], journal(c.journal_faux)[-1500:])
        assert "Traceback" not in journal(c.journal_relais) + journal(c.journal_faux)


def _conformes(ecoute):
    erreurs = [e for etat in ecoute.etats for e in valider_message("etat_reperage", etat)]
    assert not erreurs, erreurs[:5]


def test_reperage_a_la_marque_et_derive(chaine):
    c = chaine()
    e = c.ecoute.dernier()
    assert e["etat"] == "non_repere" and c.ecoute.transformation("map", "odom") is None
    debut = time.monotonic()
    e = c.reperer("essai-1")
    assert e["etat"] == "repere", e
    assert time.monotonic() - debut < 5.0
    assert e["precision_m"] == pytest.approx(0.02) and e["carte"] == "repetition.pcd"
    # 1804 avec la pose (0, 0, 0) du repère d'Unitree et la carte de la répétition
    (requete,) = c.requetes_1804()
    d = json.loads(requete.parameter)["data"]
    assert (d["x"], d["y"], d["q_z"], d["q_w"]) == (0.0, 0.0, 0.0, 1.0)
    assert d["address"].endswith("repetition.pcd")
    assert requete.header.policy.priority == 0 and requete.header.lease.id == 0
    assert c.ecoute.attendre(lambda: c.ecoute.transformation("map", "base_link") is not None, 5)
    distance, cap = ecart(c.ecoute.transformation("map", "base_link"), c.robot.verite())
    assert distance < 0.02 and cap < 0.02
    # /points : le mur de x = 6 m, remis dans le repère lidar, retombe à sa place dans map
    assert c.ecoute.attendre(lambda: c.ecoute.points_dans_la_carte() is not None, 5)
    points = c.ecoute.points_dans_la_carte()
    assert abs(points[:, 0].mean() - 6.0) < 0.05 and points[:, 0].std() < 0.05
    assert abs(points[:, 2].min() - 0.3) < 0.05          # hauteurs au-dessus du sol
    correction_avant = c.ecoute.transformation("map", "odom")
    # 2 m tout droit, puis un quart de tour : l'odométrie dérive, la correction suit
    c.robot.commander(vx=0.4)
    time.sleep(5.0)
    c.robot.commander(wz=0.5)
    time.sleep(math.pi / 2 / 0.5)
    c.robot.commander()
    time.sleep(1.0)
    verite, odom = c.robot.verite(), c.robot.odometrie()
    assert ecart(verite, (4.5, 10.0, math.pi / 2))[0] < 0.1
    assert abs(odom[0] - 2.0 * 1.02) < 0.05             # l'odométrie a compté 2 % de trop
    distance, cap = ecart(c.ecoute.transformation("map", "base_link"), verite)
    assert distance < 0.05 and cap < 0.03, (distance, cap)
    correction = c.ecoute.transformation("map", "odom")
    assert ecart(correction, correction_avant)[0] > 0.02
    points = c.ecoute.points_dans_la_carte()
    assert abs(points[:, 0].mean() - 6.0) < 0.08
    assert c.ecoute.dernier()["sauts"] == 0
    _conformes(c.ecoute)


def test_relocalisation_perdue_puis_reprise(chaine):
    c = chaine()
    assert c.reperer("essai-2")["etat"] == "repere"
    c.ecoute.panne("muet")
    debut = time.monotonic()
    assert c.ecoute.attendre(lambda: c.ecoute.dernier()["etat"] == "perdu", 6)
    assert time.monotonic() - debut < 4.0
    e = c.ecoute.dernier()
    assert e["repere"] is False and "perdu" in e["message"]
    assert c.ecoute.transformation("map", "odom") is not None     # le dernier map → odom reste
    c.ecoute.panne("aucune")
    assert c.ecoute.attendre(lambda: c.ecoute.dernier()["etat"] == "repere", 5)
    _conformes(c.ecoute)


def test_variante_b_repere_tourne(lieu, chaine):
    """repere_unitree (3 ; 9 ; 0,5) : à la marque, le robot (resté au départ) n'y est pas."""
    fiche = charger_fiche(lieu)
    fiche.etages[0].repere_unitree = Pose(3.0, 9.0, 0.5)
    enregistrer_fiche(fiche)
    c = chaine(repere=(3.0, 9.0, 0.5))
    e = c.reperer("b-1")
    assert e["etat"] == "echec" and "relocalisation impossible" in e["message"]
    time.sleep(0.5)
    assert c.ecoute.transformation("map", "odom") is None
    e = c.reperer("b-2", 2.5, 10.0, 0.0)
    assert e["etat"] == "repere", e
    d = json.loads(c.requetes_1804()[-1].parameter)["data"]
    u = carte_vers_unitree(MARQUE, (3.0, 9.0, 0.5))
    assert (d["x"], d["y"]) == pytest.approx(u[:2], abs=1e-6)
    assert quaternion_vers_cap((d["q_x"], d["q_y"], d["q_z"], d["q_w"])) == pytest.approx(u[2], abs=1e-6)
    assert c.ecoute.attendre(lambda: c.ecoute.transformation("map", "base_link") is not None, 5)
    assert ecart(c.ecoute.transformation("map", "base_link"), c.robot.verite())[0] < 0.02
    _conformes(c.ecoute)


def test_bruit_retard_et_refus_de_1102(chaine):
    c = chaine(options_faux=("--bruit", "0.02", "--retard", "0.3"))
    e = c.reperer("bruit-1")
    assert e["etat"] == "repere" and e["precision_m"] == pytest.approx(0.02, abs=0.005)
    c.robot.commander(vx=0.4)
    time.sleep(3.0)
    c.robot.commander()
    time.sleep(1.0)
    # retard de 0,3 s apparié par horodatage, bruit de 2 cm : moins de 8 cm d'écart
    assert ecart(c.ecoute.transformation("map", "base_link"), c.robot.verite())[0] < 0.08
    # 1102 en ROS 2 : refusé par le faux service de la répétition
    from unitree_api.msg import Request, Response
    reponses = []
    noeud = c.ecoute.noeud
    noeud.create_subscription(Response, "/api/slam_operate/response", reponses.append, 10)
    pub = noeud.create_publisher(Request, "/api/slam_operate/request", 10)
    time.sleep(1.0)
    r = Request()
    r.header.identity.id, r.header.identity.api_id = 424242, 1102
    r.parameter = json.dumps({"data": {"targetPose": {"x": 1, "y": 0, "z": 0, "q_x": 0, "q_y": 0, "q_z": 0,
                                                      "q_w": 1}, "mode": 1}})
    pub.publish(r)
    assert c.ecoute.attendre(lambda: any(x.header.identity.id == 424242 for x in reponses), 5)
    reponse = next(x for x in reponses if x.header.identity.id == 424242)
    donnees = json.loads(reponse.data)
    assert donnees["succeed"] is False and "Nav2" in donnees["info"]
    _conformes(c.ecoute)
