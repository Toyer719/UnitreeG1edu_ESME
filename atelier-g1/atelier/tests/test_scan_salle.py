"""Tests de salle.py et g1-salle (agent Scan) : la position vient d'un faux /odom publié ici.

Le faux /odom est publié sur un domaine ROS 2 propre à ce test, en local seulement (lo).
"""
import math
import os
import subprocess
import threading

import pytest

from atelier import RACINE
from atelier.lieu import charger_fiche, charger_itineraires, charger_salles, copier_lieu, valider_lieu
from atelier.scan import salle

LIEU_DEMO = RACINE / "lieux" / "demo"


def test_identifiant():
    assert salle.identifiant("Salle B204") == "salle_b204"
    assert salle.identifiant("Vie scolaire") == "vie_scolaire"
    assert salle.identifiant("  Infirmerie (étage) ") == "infirmerie_etage"
    assert salle.identifiant("b204") == "b204"
    assert len(salle.identifiant("x" * 60)) == 40
    with pytest.raises(ValueError):
        salle.identifiant("€€€")
    with pytest.raises(ValueError):
        salle.identifiant("Yes")


@pytest.fixture
def lieu(tmp_path):
    return copier_lieu(LIEU_DEMO, tmp_path / "lieux" / "essai")


def test_ajouter_salle_et_noeud(lieu):
    r = salle.ajouter(lieu, "Salle B210", (24.0, 13.0, math.pi / 2), alias=["b210"], phrase="Voici la B210.")
    assert r["id"] == "salle_b210"
    s = next(s for s in charger_salles(lieu) if s.id == "salle_b210")
    assert (s.nom, s.etage, s.pose.x, s.pose.y) == ("Salle B210", "rdc", 24.0, 13.0)
    assert s.pose.theta == pytest.approx(math.pi / 2, abs=1e-3) and s.alias == ["b210"]
    assert s.phrase_arrivee == "Voici la B210."
    n = charger_itineraires(lieu).noeuds["salle_b210"]
    assert (n.etage, n.x, n.y) == ("rdc", 24.0, 13.0)
    assert any("Reliez-les" in m for m in r["messages"])
    # Déplacer une salle existante : la salle et son nœud suivent
    salle.ajouter(lieu, "b204", (21.2, 12.9, 1.5))
    b204 = next(s for s in charger_salles(lieu) if s.id == "b204")
    assert (b204.pose.x, b204.pose.y, b204.nom) == (21.2, 12.9, "Salle B204")
    assert charger_itineraires(lieu).noeuds["b204"].x == 21.2
    # Un nœud seul
    r = salle.ajouter(lieu, "Carrefour est", (27.5, 10.0, 0.3), type_="noeud")
    assert r["id"] == "carrefour_est"
    assert "carrefour_est" in charger_itineraires(lieu).noeuds
    assert "carrefour_est" not in [s.id for s in charger_salles(lieu)]
    # L'accueil met aussi à jour lieu.yaml
    salle.ajouter(lieu, "accueil", (2.6, 10.1, 0.1))
    accueil = charger_fiche(lieu).accueil
    assert (accueil.x, accueil.y, accueil.theta) == (2.6, 10.1, 0.1)
    rapport = valider_lieu(lieu)
    assert not [e for e in rapport.erreurs if "accueil" in e or "b204" in e], rapport.texte()
    with pytest.raises(ValueError):
        salle.ajouter(lieu, "x", (0, 0, 0), etage="etage_inconnu")


class FausseOdom:
    """Publie nav_msgs/Odometry sur /odom à 20 Hz, dans un fil, sur son propre contexte rclpy."""

    def __init__(self, pose, sujet="/odom"):
        import rclpy
        from nav_msgs.msg import Odometry
        from rclpy.context import Context
        from rclpy.executors import SingleThreadedExecutor
        self.contexte = Context()
        rclpy.init(context=self.contexte)
        self.noeud = rclpy.create_node("fausse_odom", context=self.contexte)
        editeur = self.noeud.create_publisher(Odometry, sujet, 10)
        msg = Odometry()
        msg.header.frame_id, msg.child_frame_id = "odom", "base_link"
        msg.pose.pose.position.x, msg.pose.pose.position.y = pose[0], pose[1]
        msg.pose.pose.orientation.z, msg.pose.pose.orientation.w = math.sin(pose[2] / 2), math.cos(pose[2] / 2)
        self.noeud.create_timer(0.05, lambda: editeur.publish(msg))
        self.executeur = SingleThreadedExecutor(context=self.contexte)
        self.executeur.add_node(self.noeud)
        self.fil = threading.Thread(target=self._tourner, daemon=True)
        self.fil.start()

    def _tourner(self):
        try:
            self.executeur.spin()
        except Exception:
            pass

    def fermer(self):
        import rclpy
        self.executeur.shutdown()
        self.noeud.destroy_node()
        rclpy.shutdown(context=self.contexte)
        self.fil.join(timeout=2)


@pytest.fixture
def domaine(monkeypatch):
    pytest.importorskip("rclpy")
    monkeypatch.setenv("ROS_DOMAIN_ID", str(60 + os.getpid() % 40))
    monkeypatch.setenv("ROS_LOCALHOST_ONLY", "1")
    return os.environ["ROS_DOMAIN_ID"]


def test_lire_position(domaine):
    odom = FausseOdom((3.0, -1.5, 0.8), sujet="/odom_essai")
    try:
        x, y, theta = salle.lire_position("/odom_essai", 10.0)
        assert (x, y) == (3.0, -1.5) and theta == pytest.approx(0.8)
    finally:
        odom.fermer()
    assert salle.lire_position("/odom_essai", 0.5) is None


def test_commande_g1_salle(lieu, domaine):
    env = dict(os.environ, ATELIER_LIEUX=str(lieu.parent))
    commande = [str(RACINE / "bin" / "g1-salle"), "ajouter", "Salle des profs", "--lieu", "essai"]
    r = subprocess.run(commande + ["--delai", "1"], env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 1 and "Aucune position" in r.stdout
    odom = FausseOdom((12.0, 13.0, 1.5708))
    try:
        r = subprocess.run(commande + ["--alias", "salle des professeurs"], env=env, capture_output=True,
                           text=True, timeout=60)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "salle_des_profs" in r.stdout
        r = subprocess.run([str(RACINE / "bin" / "g1-salle"), "ajouter", "noeud_12", "--type", "noeud",
                            "--lieu", "essai"], env=env, capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stdout + r.stderr
    finally:
        odom.fermer()
    s = next(s for s in charger_salles(lieu) if s.id == "salle_des_profs")
    assert (s.pose.x, s.pose.y) == (12.0, 13.0) and s.alias == ["salle des professeurs"]
    assert "noeud_12" in charger_itineraires(lieu).noeuds
