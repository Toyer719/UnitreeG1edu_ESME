"""Le nœud voix en vrai (vague 6, section 13.6 du plan ; agent Voix) : python -m atelier.voix lancé dans son
domaine ROS 2, contre un service voice de test (la FausseVoix du faux G1, g1_jumeau/audio.py, dans un nœud du
test) ; jamais le vrai robot.

Sortie robot : volume réglé puis relu au départ, une phrase de /robot/dire en morceaux de PCM 16 kHz conformes
(même stream_id, 96 000 octets au plus, pairs, une durée à 5 % près de celle du WAV de Piper rééchantillonné),
une phrase haute qui coupe (1004 avant la nouvelle), /voix/commande volume et taire, robot qui ne répond plus,
SIGTERM pendant une phrase (1004, puis fin). Sortie borne : /voix/son et le WAV, rien vers le robot. Sortie
robot_tts : 1001. /voix/etat conforme tout du long. Sauté sans ROS 2, sans unitree_api ou sans Piper.
"""
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

os.environ.setdefault("ROS_DOMAIN_ID", "144")
rclpy = pytest.importorskip("rclpy", reason="ROS 2 n'est pas chargé : source ~/robot-g1/setup/env.sh")
pytest.importorskip("unitree_api.msg", reason="messages unitree_api absents")

import atelier  # noqa: E402
from atelier.lieu import voix as V  # noqa: E402
from atelier.lieu.validation import valider_donnees  # noqa: E402
from atelier.voix.synthese import lire_wav, reechantillonner, voix_disponibles  # noqa: E402

pytestmark = pytest.mark.skipif(V.VOIX_DEFAUT not in voix_disponibles(), reason="modèle Piper absent")

JUMEAU = atelier.RACINE / "ws" / "src" / "g1_jumeau"
PYTHON = atelier.RACINE / ".venv-projet" / "bin" / "python"


def env_projet(**en_plus):
    """L'environnement du test, avec le dépôt en tête du PYTHONPATH (ROS 2 y reste)."""
    chemin = os.pathsep.join(x for x in (str(atelier.RACINE), os.environ.get("PYTHONPATH")) if x)
    return dict(os.environ, PYTHONPATH=chemin, PYTHONDONTWRITEBYTECODE="1", **en_plus)


def _fausse_voix():
    sys.path.insert(0, str(JUMEAU))
    try:
        from g1_jumeau.audio import FausseVoix
    finally:
        sys.path.remove(str(JUMEAU))
    return FausseVoix(horloge=time.monotonic)


class ServiceVoix:
    """Un nœud du test : le service voice du robot (FausseVoix), et ce que publie le nœud voix."""

    def __init__(self):
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.qos import QoSProfile, ReliabilityPolicy
        from rclpy.signals import SignalHandlerOptions
        from std_msgs.msg import String
        from unitree_api.msg import Request, Response
        self.contexte = rclpy.Context()
        rclpy.init(context=self.contexte, signal_handler_options=SignalHandlerOptions.NO)
        self.noeud = rclpy.create_node("essai_service_voix", context=self.contexte)
        self.Response, self.String = Response, String
        fiable = QoSProfile(depth=50, reliability=ReliabilityPolicy.RELIABLE)
        self.voix = _fausse_voix()
        self.repondre = True
        self.verrou = threading.Lock()
        self.requetes, self.etats, self.sons, self.non_conformes = [], [], [], []
        self.pub_reponse = self.noeud.create_publisher(Response, "/api/voice/response", fiable)
        self.pub_dire = self.noeud.create_publisher(String, "/robot/dire", 10)
        self.pub_commande = self.noeud.create_publisher(String, "/voix/commande", 10)
        self.noeud.create_subscription(Request, "/api/voice/request", self._requete, fiable)
        self.noeud.create_subscription(String, "/voix/etat", self._etat, 50)
        self.noeud.create_subscription(String, "/voix/son", self._son, 50)
        self.executeur = SingleThreadedExecutor(context=self.contexte)
        self.executeur.add_node(self.noeud)
        self.fil = threading.Thread(target=self.executeur.spin, daemon=True)
        self.fil.start()

    def _requete(self, msg):
        t = time.monotonic()
        binaire = bytes(msg.binary)
        identite = msg.header.identity
        with self.verrou:
            self.requetes.append({"t": t, "api_id": identite.api_id, "parametre": msg.parameter,
                                  "octets": len(binaire), "id": identite.id})
            code, data = self.voix.traiter(identite.api_id, msg.parameter, binaire, t)
        if not self.repondre:
            return
        reponse = self.Response()
        reponse.header.identity.id = identite.id
        reponse.header.identity.api_id = identite.api_id
        reponse.header.status.code = int(code)
        reponse.data = data
        self.pub_reponse.publish(reponse)

    def _etat(self, msg):
        d = json.loads(msg.data)
        erreurs = valider_donnees("etat_voix", d)
        with self.verrou:
            if erreurs:
                self.non_conformes.append((erreurs, d))
            self.etats.append((time.monotonic(), d))

    def _son(self, msg):
        d = json.loads(msg.data)
        with self.verrou:
            self.sons.append(d)

    def dire(self, texte, **champs):
        self.pub_dire.publish(self.String(data=json.dumps(dict({"version": 1, "texte": texte, "source": "guide"},
                                                               **champs), ensure_ascii=False)))

    def commander(self, **champs):
        self.pub_commande.publish(self.String(data=json.dumps(dict({"version": 1}, **champs))))

    def depuis(self, rang):
        with self.verrou:
            return list(self.requetes[rang:])

    def dernier_etat(self):
        with self.verrou:
            return self.etats[-1][1] if self.etats else None

    def fermer(self):
        self.executeur.shutdown(timeout_sec=1.0)
        self.fil.join(timeout=3.0)
        self.noeud.destroy_node()
        rclpy.shutdown(context=self.contexte)


def attendre(condition, delai, message):
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        valeur = condition()
        if valeur:
            return valeur
        time.sleep(0.05)
    raise AssertionError(message)


@pytest.fixture
def montage(tmp_path):
    service = ServiceVoix()
    env = env_projet(ATELIER_VOIX_SONS=str(tmp_path / "sons"))
    processus = []

    def lancer(*arguments):
        p = subprocess.Popen([str(PYTHON), "-m", "atelier.voix", *arguments], env=env, cwd=str(tmp_path),
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
        processus.append(p)
        attendre(lambda: service.dernier_etat(), 20, f"pas de /voix/etat du nœud voix ({arguments})")
        return p

    service.lancer = lancer
    service.sons_dossier = tmp_path / "sons"
    yield service
    for p in processus:
        if p.poll() is None:
            os.killpg(p.pid, signal.SIGKILL)
        p.wait(timeout=5)
    service.fermer()


def flux_de(requetes):
    return [json.loads(r["parametre"])["stream_id"] for r in requetes if r["api_id"] == 1003]


def test_sortie_robot(montage):
    s = montage
    p = s.lancer("--sortie", "robot", "--volume", "60")
    attendre(lambda: [r["api_id"] for r in s.depuis(0)][:2] == [1006, 1005], 10, "pas de 1006 puis 1005 au départ")
    assert json.loads(s.depuis(0)[0]["parametre"]) == {"volume": 60}
    attendre(lambda: (s.dernier_etat() or {}).get("volume_lu") == 60, 5, "volume pas relu")

    # une phrase : morceaux conformes, même stream_id, durée du WAV de Piper rééchantillonné
    rang = len(s.depuis(0))
    s.dire("Bonjour, suivez-moi !", id="essai-bonjour")
    attendre(lambda: (s.dernier_etat() or {}).get("dites", 0) >= 1, 20, "la phrase n'a pas été dite")
    lectures = [r for r in s.depuis(rang) if r["api_id"] == 1003]
    assert lectures and set(flux_de(lectures)) == {"essai-bonjour"}
    assert all(0 < r["octets"] <= V.TAILLE_MORCEAU_OCTETS and r["octets"] % 2 == 0 for r in lectures)
    frequence, echantillons = lire_wav(s.sons_dossier / "essai-bonjour.wav")
    attendu = len(reechantillonner(echantillons.astype("float32") / 32768.0, frequence)) * 2
    recu = sum(r["octets"] for r in lectures)
    assert abs(recu - attendu) <= 0.05 * attendu, (recu, attendu)
    flux = s.voix.etat()["flux"][-1]
    assert flux["stream_id"] == "essai-bonjour" and flux["octets"] == recu and s.voix.ecarts == 0

    # une phrase longue, puis une haute : 1004 avant la nouvelle, jamais deux flux en même temps
    rang = len(s.depuis(0))
    s.dire("Je vous accompagne jusqu'à la salle B204, au bout du couloir nord. Restez bien derrière moi, merci "
           "beaucoup, et faites attention aux marches.", id="essai-longue")
    attendre(lambda: (s.dernier_etat() or {}).get("en_cours") or None, 10, "la phrase longue n'a pas commencé")
    time.sleep(1.2)
    s.dire("Attention, je passe !", priorite="haute", id="essai-haute")
    attendre(lambda: "essai-haute" in flux_de(s.depuis(rang)), 10, "la phrase haute n'est pas partie")
    apis = [(r["api_id"], flux_de([r])[0] if r["api_id"] == 1003 else None) for r in s.depuis(rang)]
    rang_arret = apis.index((1004, None))
    assert all(f == "essai-longue" for a, f in apis[:rang_arret] if a == 1003)
    assert all(f == "essai-haute" for a, f in apis[rang_arret + 1:] if a == 1003)
    assert s.voix.flux_meles == 0 and s.voix.etat()["flux"][-2]["interrompu"]

    # commandes : volume, puis taire
    rang = len(s.depuis(0))
    s.commander(action="volume", volume=40)
    attendre(lambda: any(r["api_id"] == 1006 for r in s.depuis(rang)), 5, "pas de 1006 après la commande")
    assert json.loads(next(r for r in s.depuis(rang) if r["api_id"] == 1006)["parametre"]) == {"volume": 40}
    rang = len(s.depuis(0))
    s.commander(action="taire")
    attendre(lambda: any(r["api_id"] == 1004 for r in s.depuis(rang)), 5, "pas de 1004 après « taire »")

    # le robot ne répond plus : l'état le dit, rien ne plante
    s.repondre = False
    s.dire("Personne ne répond.", id="essai-muet")
    attendre(lambda: ((s.dernier_etat() or {}).get("robot") or {}).get("repond") is False, 10,
             "le robot muet n'est pas vu")
    assert p.poll() is None and s.dernier_etat()["erreurs"] >= 1
    s.repondre = True

    # SIGTERM pendant une phrase : 1004, puis le nœud s'arrête
    attendre(lambda: (s.dernier_etat() or {}).get("en_cours") is None, 10, "la phrase muette ne finit pas")
    s.dire("Une dernière phrase assez longue pour être coupée par l'arrêt du nœud voix, je pense.", id="essai-fin")
    attendre(lambda: "essai-fin" in flux_de(s.depuis(0)), 10, "la dernière phrase n'est pas partie")
    rang = len(s.depuis(0))
    p.send_signal(signal.SIGTERM)
    assert p.wait(timeout=10) == 0
    attendre(lambda: any(r["api_id"] == 1004 for r in s.depuis(rang)), 3, "pas de 1004 à l'arrêt du nœud")
    with s.verrou:
        assert s.non_conformes == [] and all(r["api_id"] in V.APIS_NOEUD_VOIX for r in s.requetes)
    sortie = p.stdout.read().decode("utf-8", "replace")
    assert "voix prête" in sortie and "Traceback" not in sortie


def test_sortie_borne_puis_robot_tts(montage):
    s = montage
    p = s.lancer("--sortie", "borne", "--volume", "80")
    s.dire("Bonjour, je suis la borne.", id="essai-borne")
    attendre(lambda: s.sons, 15, "pas de /voix/son")
    son = s.sons[0]
    assert valider_donnees("son_voix", son) == [] and son["id"] == "essai-borne"
    assert son["url"] == "/api/voix/son/essai-borne" and son["frequence_hz"] == 22050
    frequence, echantillons = lire_wav(s.sons_dossier / "essai-borne.wav")
    assert frequence == 22050 and abs(len(echantillons) / frequence - son["duree_s"]) < 0.01
    assert max(abs(int(x)) for x in echantillons) <= 0.81 * 32767          # volume 80 : le WAV plus bas
    time.sleep(0.5)
    assert s.depuis(0) == []                         # la borne ne parle jamais au robot
    s.commander(action="sortie", sortie="robot_tts")
    attendre(lambda: (s.dernier_etat() or {}).get("sortie") == "robot_tts", 5, "sortie pas changée")
    s.dire("Bonjour à tous", id="essai-tts")
    attendre(lambda: any(r["api_id"] == 1001 for r in s.depuis(0)), 10, "pas de 1001")
    tts = json.loads(next(r for r in s.depuis(0) if r["api_id"] == 1001)["parametre"])
    assert tts == {"index": 0, "speaker_id": 1, "text": "Bonjour à tous"} and s.voix.tts["text"] == "Bonjour à tous"
    p.send_signal(signal.SIGINT)
    assert p.wait(timeout=10) == 0
    with s.verrou:
        assert s.non_conformes == []


def test_reglages_refuses():
    r = subprocess.run([str(PYTHON), "-m", "atelier.voix", "--volume", "150"], capture_output=True, text=True,
                       env=env_projet(), timeout=60)
    assert r.returncode == 2 and "de 0 à 100" in r.stderr


def test_mesurer_sans_ros():
    r = subprocess.run([str(PYTHON), "-m", "atelier.voix", "--mesurer", "Bonjour, suivez-moi !"],
                       capture_output=True, text=True, env=env_projet(), timeout=120)
    assert r.returncode == 0, r.stderr
    assert "Bonjour, suivez-moi !" in r.stdout and "Pire temps de synthèse" in r.stdout
