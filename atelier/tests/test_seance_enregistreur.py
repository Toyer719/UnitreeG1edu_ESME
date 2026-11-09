"""L'enregistreur ROS 2 de la boîte noire (vague 6, section 13.3 du plan) : agent Boîte noire.

Fonctions pures (limiteur, garde-fous, QoS), puis le vrai enregistreur (python -m atelier.seance enregistrer) face à
un éditeur d'essai dans ce processus (domaine ROS_DOMAIN_ID du test) : sujets de la liste seulement, fréquences
réduites (odométrie à 10 Hz au plus), jamais d'image ni de nuage, l'état d'avant la séance des sujets qui le gardent
(transient_local), /rosout (erreurs toujours gardées), fermeture propre au SIGINT (metadata.yaml, ros2 bag info),
garde-fous (taille maximale, place libre) et arrêt quand l'Atelier qui l'a lancé disparaît.
"""
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import atelier
from atelier.seance import enregistreur as E
from atelier.seance.lecture import charger, infos_bag

try:
    import rosbag2_py  # noqa: F401
    from rclpy.serialization import serialize_message  # noqa: F401
    ROS = True
except ImportError:
    ROS = False
avec_ros = pytest.mark.skipif(not ROS, reason="ROS 2 non chargé (source ~/robot-g1/setup/env.sh)")


def test_limiteur():
    l10 = E.Limiteur(10.0)
    gardes = [t / 100 for t in range(200) if l10.garder(t / 100)]       # 100 Hz pendant 2 s → 10 Hz
    assert len(gardes) == 20 and all(b - a >= 0.1 - 1e-6 for a, b in zip(gardes, gardes[1:]))
    assert all(E.Limiteur(None).garder(t) for t in range(10))
    rafale = E.Limiteur(50.0, rafale=True)
    assert sum(rafale.garder(0.0) for _ in range(200)) == 50              # une rafale : 50 d'un coup
    assert sum(rafale.garder(1.0) for _ in range(200)) == 50              # puis 50 par seconde


def test_raison_de_coupure():
    assert E.raison_coupure(10, 100 * E.GO, 1024, 2.0) is None
    texte = E.raison_coupure(10, 1.5 * E.GO, 1024, 2.0)
    assert texte.startswith("Enregistrement arrêté : il ne reste que 1,5 Go") and "La séance continue" in texte
    assert "(au moins 2 Go" in texte
    assert "1\u202f025 Mo" in E.raison_coupure(1025 * E.MO, 100 * E.GO, 1024, 2.0)
    assert E.raison_coupure(1025 * E.MO, None, 1024, 2.0).startswith("Enregistrement arrêté : il a atteint")


@avec_ros
def test_qos_de_lecture():
    from rclpy.qos import DurabilityPolicy, ReliabilityPolicy
    verrou = SimpleNamespace(qos_profile=SimpleNamespace(durability=DurabilityPolicy.TRANSIENT_LOCAL,
                                                         reliability=ReliabilityPolicy.RELIABLE))
    ordinaire = SimpleNamespace(qos_profile=SimpleNamespace(durability=DurabilityPolicy.VOLATILE,
                                                            reliability=ReliabilityPolicy.RELIABLE))
    capteur = SimpleNamespace(qos_profile=SimpleNamespace(durability=DurabilityPolicy.TRANSIENT_LOCAL,
                                                          reliability=ReliabilityPolicy.BEST_EFFORT))
    assert E.qos_lecture([verrou]) == "transitoire"
    assert E.qos_lecture([verrou, ordinaire]) == "au_mieux" and E.qos_lecture([capteur]) == "au_mieux"
    assert E.qos_lecture([]) == "au_mieux"


def test_debut_de_processus():
    assert E.debut_processus(os.getpid()) is not None and E.debut_processus(10 ** 8) is None


class Editeur:
    """Un éditeur d'essai : /odom à 50 Hz, /guide/etat à 5 Hz, une image sur /visiteurs/detectes (un sujet de la
    liste : jamais enregistrée), /pont/arret vrai gardé (transient_local), des lignes de journal en rafale et une
    erreur, et /hors_liste (jamais enregistré)."""

    def __init__(self):
        import rclpy
        from nav_msgs.msg import Odometry
        from rcl_interfaces.msg import Log
        from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
        from sensor_msgs.msg import Image
        from std_msgs.msg import Bool, String
        self.contexte = rclpy.Context()
        rclpy.init(context=self.contexte)
        self.noeud = rclpy.create_node("editeur_essai_boite_noire", context=self.contexte)
        self.Odometry, self.String, self.Image, self.Log = Odometry, String, Image, Log
        # le journal publié directement sur /rosout (le journal du nœud écrirait aussi dans la sortie du test)
        self.journal = self.noeud.create_publisher(Log, "/rosout", 1000)
        self.odom = self.noeud.create_publisher(Odometry, "/odom", 10)
        self.guide = self.noeud.create_publisher(String, "/guide/etat", 10)
        self.image = self.noeud.create_publisher(Image, "/visiteurs/detectes", 10)
        self.hors = self.noeud.create_publisher(String, "/hors_liste", 10)
        self.verrou = self.noeud.create_publisher(Bool, "/pont/arret", QoSProfile(
            depth=1, reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.TRANSIENT_LOCAL))
        self.verrou.publish(Bool(data=True))
        self.fin = threading.Event()
        self.fil = threading.Thread(target=self._boucle, daemon=True)
        self.fil.start()

    def _boucle(self):
        i = 0
        while not self.fin.is_set():
            m = self.Odometry()
            m.pose.pose.position.x = 0.01 * i
            m.pose.pose.orientation.w = 1.0
            self.odom.publish(m)
            if i % 10 == 0:
                self.guide.publish(self.String(data=json.dumps({"etat": "attente", "cible": None})))
                self.image.publish(self.Image())
                self.hors.publish(self.String(data="x"))
            if i % 50 == 0:
                for k in range(120):
                    self.journal.publish(self.Log(level=20, name="editeur_essai", msg=f"ligne {i} {k}"))
                self.journal.publish(self.Log(level=40, name="editeur_essai", msg=f"erreur d'essai {i}"))
            i += 1
            time.sleep(0.02)

    def fermer(self):
        self.fin.set()
        self.fil.join(timeout=3)
        self.noeud.destroy_node()
        import rclpy
        rclpy.try_shutdown(context=self.contexte)


def lancer(dossier, *options, env=None):
    environnement = dict(os.environ)
    environnement["PYTHONPATH"] = str(atelier.RACINE) + os.pathsep + environnement.get("PYTHONPATH", "")
    environnement.update(env or {})
    return subprocess.Popen([sys.executable, "-m", "atelier.seance", "enregistrer", "--dossier", str(dossier),
                             *map(str, options)], cwd=str(atelier.RACINE), env=environnement,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)


def etat_de(dossier):
    return E.lire_etat(dossier) or {}


def attendre(condition, delai=20.0):
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        if condition():
            return True
        time.sleep(0.1)
    return condition()


def arreter(p):
    if p.poll() is None:
        os.killpg(p.pid, signal.SIGINT)
        try:
            p.wait(timeout=15)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGKILL)
            p.wait()
    return p.stdout.read().decode("utf-8", "replace")


@avec_ros
def test_enregistrement_leger_et_borne(tmp_path):
    editeur = Editeur()
    p = lancer(tmp_path)
    try:
        assert attendre(lambda: etat_de(tmp_path).get("etat") == "en_cours"), arreter(p)
        assert attendre(lambda: {"/odom", "/guide/etat", "/pont/arret", "/rosout"}
                        <= set(etat_de(tmp_path).get("sujets") or []), 20), arreter(p)
        time.sleep(6.0)
        e = etat_de(tmp_path)
        assert "/visiteurs/detectes" in e["ignores"] and "image" in e["ignores"]["/visiteurs/detectes"]
        assert "/hors_liste" not in e["sujets"]
        assert e["cpu_recent"] is None or e["cpu_recent"] < 0.15
    finally:
        sortie = arreter(p)
        editeur.fermer()
    assert p.returncode == 0, sortie
    e = etat_de(tmp_path)
    assert e["etat"] == "arrete" and e["messages"] > 0, e
    bag = tmp_path / "bag"
    assert (bag / "metadata.yaml").is_file()
    infos = infos_bag(bag)
    sujets = infos["sujets"]
    assert set(sujets) == {"/odom", "/guide/etat", "/pont/arret", "/rosout"}, sujets
    odom = sujets["/odom"]
    frequence = (odom["nombre"] - 1) / (odom["fin"] - odom["debut"])
    assert 7.0 < frequence <= 10.0, frequence                       # 50 Hz publiés, 10 Hz gardés
    assert odom["nombre"] / (odom["fin"] - odom["debut"]) <= 10.0    # même compté « nombre / durée »
    assert e["recus"]["/odom"] < 0.5 * 50 * (odom["fin"] - odom["debut"])   # DDS jette le reste (file de 1)
    d = charger(bag)
    assert d.serie("booleens", "/pont/arret")[0][1] is True           # l'état d'avant (transient_local)
    erreurs = [x for x in d.journal if x[1] >= 40]
    assert len(erreurs) >= 5                                         # les erreurs : toutes gardées
    assert d.comptes["/rosout"] < e["recus"]["/rosout"]             # les lignes INFO : 50 par seconde au plus
    r = subprocess.run(["ros2", "bag", "info", str(bag)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "/odom" in r.stdout and "nav_msgs/msg/Odometry" in r.stdout


@avec_ros
def test_garde_fous(tmp_path):
    # place libre trop faible dès le départ : rien n'est ouvert, état « coupe » avec la raison
    p = lancer(tmp_path / "a", env={"ATELIER_SEANCE_PLACE_MIN_GO": "1000000"})
    p.wait(timeout=30)
    e = etat_de(tmp_path / "a")
    assert p.returncode == 0 and e["etat"] == "coupe" and e["message"].startswith("Enregistrement arrêté : il ne "
                                                                                  "reste que")
    assert not (tmp_path / "a" / "bag").exists()
    # taille maximale atteinte en route : le bag est fermé proprement
    editeur = Editeur()
    p = lancer(tmp_path / "b", "--taille-max-mo", "0.02")
    try:
        assert attendre(lambda: etat_de(tmp_path / "b").get("etat") == "coupe", 40), arreter(p)
        p.wait(timeout=15)
    finally:
        arreter(p)
        editeur.fermer()
    e = etat_de(tmp_path / "b")
    assert "taille maximale" in e["message"] and (tmp_path / "b" / "bag" / "metadata.yaml").is_file()


@avec_ros
def test_l_atelier_disparait(tmp_path):
    atelier_essai = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    p = lancer(tmp_path, "--atelier", atelier_essai.pid)
    try:
        assert attendre(lambda: etat_de(tmp_path).get("etat") == "en_cours"), arreter(p)
        atelier_essai.kill()
        atelier_essai.wait()
        debut = time.monotonic()
        p.wait(timeout=15)
        assert time.monotonic() - debut < 5.0
    finally:
        sortie = arreter(p)
    e = etat_de(tmp_path)
    assert e["etat"] == "arrete" and "sans fermer la séance" in e["message"], sortie
    assert (tmp_path / "bag" / "metadata.yaml").is_file()


def test_lire_etat_absent(tmp_path):
    assert E.lire_etat(tmp_path) is None
    (Path(tmp_path) / E.FICHIER_ETAT).write_text("pas du json")
    assert E.lire_etat(tmp_path) is None
