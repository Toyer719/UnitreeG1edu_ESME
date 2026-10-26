"""Routes de l'équipe (atelier/serveur/routes/equipe.py, vague 4, section 11.6 du plan), sans ROS
puis avec le pont ROS 2 du serveur : fichiers écrits et relus sur une copie de demo, refus en
français, essai d'une phrase, personnalité active annoncée sur /personnalite/active, phrase
publiée sur /visiteur/texte, caméras de l'ordinateur. Agent Équipe.

Avec ROS : domaine $ROS_DOMAIN_ID (75 par défaut, celui de l'agent Équipe). Sauté sans rclpy.
"""
import json
import os
import threading
import time

import pytest
from fastapi.testclient import TestClient

from atelier.lieu import equipe as E
from atelier.lieu import valider_message
from atelier.serveur.main import creer_app

from .test_serveur_communs import attendre, faux_bin, journaux, lieux  # noqa: F401

os.environ.setdefault("ROS_DOMAIN_ID", "75")


@pytest.fixture
def client(lieux, faux_bin):
    with TestClient(creer_app(ros=False)) as c:
        yield c


def _erreur(r, statut):
    assert r.status_code == statut, r.text
    d = r.json()
    assert isinstance(d["detail"], str) and d["detail"]
    return d


# ---------------------------------------------------------------- fichiers du lieu

@pytest.mark.parametrize("quoi", list(E.FICHIERS_EQUIPE))
def test_fichier_absent_puis_ecrit_et_relu(client, lieux, quoi):
    d = _erreur(client.get(f"/api/lieux/demo/{quoi}"), 404)
    assert "facultatif" in d["detail"] and "partez de l'exemple" in d["detail"]
    exemple = client.get("/api/equipe").json()["fichiers"][quoi]["exemple"]
    assert exemple == E.exemple_equipe(quoi)
    r = client.put(f"/api/lieux/demo/{quoi}", json=exemple)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["enregistre"] == [E.FICHIERS_EQUIPE[quoi]] and corps["donnees"] == exemple
    assert set(corps["rapport"]) >= {"ok", "erreurs", "avertissements", "equipe"}
    assert (lieux / "demo" / E.FICHIERS_EQUIPE[quoi]).read_text(encoding="utf-8").startswith("# ")
    assert client.get(f"/api/lieux/demo/{quoi}").json() == exemple


FAUTES = {"personnalites": lambda d: d.update(active="joyeux"),
          "dialogues": lambda d: d["regles"][0].update(action="danser"),
          "camera": lambda d: d["detection"].update(confiance_min=3)}


@pytest.mark.parametrize("quoi", list(E.FICHIERS_EQUIPE))
def test_fichier_faux_refuse_en_francais(client, lieux, quoi):
    d = E.exemple_equipe(quoi)
    FAUTES[quoi](d)
    e = _erreur(client.put(f"/api/lieux/demo/{quoi}", json=d), 422)
    assert e["detail"] == f"{E.FICHIERS_EQUIPE[quoi]} n'a pas été enregistré : corrigez les points ci-dessous."
    assert e["erreurs"] and all(m.startswith(E.FICHIERS_EQUIPE[quoi]) for m in e["erreurs"])
    assert not (lieux / "demo" / E.FICHIERS_EQUIPE[quoi]).exists()
    v = client.post(f"/api/lieux/demo/{quoi}/verifier", json=d).json()
    assert v["ok"] is False and v["erreurs"] == e["erreurs"]
    # pas un objet du tout
    assert _erreur(client.put(f"/api/lieux/demo/{quoi}", json=[1, 2]), 422)["erreurs"]


def test_fichier_illisible_sur_le_disque(client, lieux):
    (lieux / "demo" / "camera.yaml").write_text("version: 1\ncamera: [\n", encoding="utf-8")
    e = _erreur(client.get("/api/lieux/demo/camera"), 422)
    assert "camera.yaml est invalide" in e["detail"] and e["erreurs"]


def test_verifier_sans_ecrire(client, lieux):
    client.put("/api/lieux/demo/personnalites", json=E.exemple_equipe("personnalites"))
    d = E.exemple_equipe("dialogues")
    d["regles"][3]["personnalite"] = "joyeux"
    r = client.post("/api/lieux/demo/dialogues/verifier", json=d).json()
    assert r["ok"] is False and "joyeux" in r["erreurs"][0]
    assert not (lieux / "demo" / "dialogues.yaml").exists()
    # le rapport du PUT réunit la vérification du lieu et celle de l'équipe (l'enregistrement passe)
    r = client.put("/api/lieux/demo/dialogues", json=d).json()
    assert any("joyeux" in m for m in r["rapport"]["erreurs"]) and r["rapport"]["equipe"]["ok"] is False


def test_lieu_inconnu_et_id_faux(client):
    assert "n'existe pas" in _erreur(client.get("/api/lieux/inconnu/dialogues"), 404)["detail"]
    _erreur(client.get("/api/lieux/..%2Fdemo/camera"), 404)
    _erreur(client.put("/api/lieux/Mauvais Id/camera", json={}), 400)


def test_routes_des_autres_inchangees(client):
    # les routes de l'équipe ne prennent pas les adresses des autres (pas de /{quoi} générique)
    assert _erreur(client.put("/api/lieux/demo/verification", json={}), 405)["detail"].startswith("Méthode PUT")
    assert _erreur(client.get("/api/lieux/demo/musique"), 404)["detail"].startswith("Adresse inconnue")


# ---------------------------------------------------------------- essayer une phrase

def test_essayer_avec_l_exemple_le_fichier_puis_l_onglet(client):
    r = client.post("/api/lieux/demo/dialogues/essayer", json={"texte": "je cherche la salle b204"}).json()
    assert r["origine"] == "exemple" and r["action"] == "guider"
    assert r["guide"] == {"cible": "b204", "accompagner": True, "source": "dialogue"}
    d = E.exemple_equipe("dialogues")
    d["regles"][1]["reponse"] = "Bonjour à vous !"
    client.put("/api/lieux/demo/dialogues", json=d)
    r = client.post("/api/lieux/demo/dialogues/essayer", json={"texte": "Bonjour"}).json()
    assert (r["origine"], r["reponse"], r["guide"]) == ("fichier", "Bonjour à vous !", None)
    d["regles"][1]["reponse"] = "Salut de l'onglet."
    r = client.post("/api/lieux/demo/dialogues/essayer", json={"texte": "bonjour", "dialogues": d}).json()
    assert (r["origine"], r["reponse"]) == ("onglet", "Salut de l'onglet.")
    r = client.post("/api/lieux/demo/dialogues/essayer", json={"texte": "quelle heure est-il"}).json()
    assert r["action"] == "repli" and r["reponse"] == d["repli"]


def test_essayer_refus(client):
    assert "Tapez" in _erreur(client.post("/api/lieux/demo/dialogues/essayer", json={"texte": "  "}), 400)["detail"]
    _erreur(client.post("/api/lieux/demo/dialogues/essayer", json={"texte": "x" * 501}), 400)
    e = _erreur(client.post("/api/lieux/demo/dialogues/essayer", json={"texte": "bonjour", "dialogues": {"version": 1}}),
                422)
    assert "onglet" in e["detail"] and e["erreurs"]
    assert "texte" in _erreur(client.post("/api/lieux/demo/dialogues/essayer", json={}), 422)["detail"]


def test_essayer_un_autre_etage(client, lieux):
    salles = json.loads(json.dumps(client.get("/api/lieux/demo/salles").json()))
    r = client.post("/api/lieux/demo/dialogues/essayer", json={"texte": "je cherche la b204", "etage": "etage1"}).json()
    assert r["guide"] is None and r["raison"] == "autre_etage" and len(salles) == 6


# ---------------------------------------------------------------- personnalité active, sans ROS

def test_personnalite_active_sans_fichier_puis_sans_ros(client, lieux):
    assert "enregistrez d'abord" in _erreur(client.post("/api/lieux/demo/personnalites/active", json={"id": "discret"}),
                                            404)["detail"]
    client.put("/api/lieux/demo/personnalites", json=E.exemple_equipe("personnalites"))
    e = _erreur(client.post("/api/lieux/demo/personnalites/active", json={"id": "joyeux"}), 404)
    assert "accueillant, discret" in e["detail"]
    r = client.post("/api/lieux/demo/personnalites/active", json={"id": "discret"}).json()
    assert r["enregistre"] == ["personnalites.yaml"] and r["active"] == "discret" and r["publie"] is False
    assert "ROS 2 n'est pas actif" in r["avertissement"]
    assert valider_message("personnalite_active", r["message"]) == [] and r["message"]["lieu"] == "demo"
    assert client.get("/api/lieux/demo/personnalites").json()["active"] == "discret"
    # déjà active : rien n'est réécrit
    assert client.post("/api/lieux/demo/personnalites/active", json={"id": "discret"}).json()["enregistre"] == []


def test_sans_ros(client):
    assert "ROS 2 n'est pas actif" in _erreur(client.post("/api/equipe/visiteur", json={"texte": "bonjour"}), 503)["detail"]
    e = client.get("/api/equipe/etat").json()
    assert e == {"ros": {"actif": False, "erreur": None}, "personnalite": None, "dire": [], "visiteurs": None,
                 "personnes": None}


def test_informations(client):
    i = client.get("/api/equipe").json()
    assert set(i["fichiers"]) == set(E.FICHIERS_EQUIPE)
    assert i["fichiers"]["camera"]["schema"]["title"] == "camera.yaml"
    assert {s["sujet"] for s in i["sujets"]} == set(E.SUJETS_EQUIPE)
    assert "depart" in i["codes_evenement"] and "99" not in i["gestes"] and i["gestes"]["26"] == "Grand salut"
    assert i["actions"] == list(E.ACTIONS_DIALOGUE) and "See3CAM_11CUG" in i["prereglages_camera"]


def test_cameras_de_l_ordinateur(client, tmp_path, monkeypatch):
    from atelier.serveur.routes import equipe
    sys_video = tmp_path / "video4linux"
    for n, nom in ((10, "See3CAM_11CUG"), (2, "Webcam"), (3, None)):
        (sys_video / f"video{n}").mkdir(parents=True)
        if nom:
            (sys_video / f"video{n}" / "name").write_text(nom + "\n")
    (sys_video / "v4l-subdev0").mkdir()
    monkeypatch.setattr(equipe, "DOSSIER_VIDEO", sys_video)
    assert client.get("/api/equipe/cameras").json() == [
        {"peripherique": "/dev/video2", "nom": "Webcam"}, {"peripherique": "/dev/video3", "nom": ""},
        {"peripherique": "/dev/video10", "nom": "See3CAM_11CUG"}]
    monkeypatch.setattr(equipe, "DOSSIER_VIDEO", tmp_path / "rien")
    assert client.get("/api/equipe/cameras").json() == []


# ---------------------------------------------------------------- avec le pont ROS 2 du serveur

class Ecouteur:
    """Nœud rclpy dans un fil : écoute /personnalite/active (transient_local) et /visiteur/texte."""

    def __init__(self):
        import rclpy
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
        from std_msgs.msg import String
        self.rclpy = rclpy
        self.contexte = rclpy.Context()
        rclpy.init(context=self.contexte)
        self.noeud = rclpy.create_node("ecouteur_equipe", context=self.contexte)
        self.String = String
        self.personnalites, self.textes = [], []
        verrou = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.noeud.create_subscription(String, "/personnalite/active", lambda m: self.personnalites.append(m.data), verrou)
        self.noeud.create_subscription(String, "/visiteur/texte", lambda m: self.textes.append(m.data), 10)
        self.pub_dire = self.noeud.create_publisher(String, "/robot/dire", 10)
        self.pub_visiteurs = self.noeud.create_publisher(String, "/visiteurs/detectes", 10)
        self.executeur = SingleThreadedExecutor(context=self.contexte)
        self.executeur.add_node(self.noeud)
        self._fin = threading.Event()
        self._fil = threading.Thread(target=self._tourner, daemon=True)
        self._fil.start()

    def _tourner(self):
        while not self._fin.is_set():
            self.executeur.spin_once(timeout_sec=0.05)

    def publier(self, publieur, donnees):
        publieur.publish(self.String(data=json.dumps(donnees, ensure_ascii=False)))

    def fermer(self):
        self._fin.set()
        self._fil.join(timeout=3)
        self.executeur.shutdown()
        self.noeud.destroy_node()
        self.rclpy.shutdown(context=self.contexte)


@pytest.fixture
def ecouteur():
    pytest.importorskip("rclpy", reason="ROS 2 n'est pas chargé : source ~/robot-g1/setup/env.sh")
    e = Ecouteur()
    yield e
    e.fermer()


def test_avec_ros(ecouteur, lieux, faux_bin):
    with TestClient(creer_app(ros=True)) as c:
        etat = c.app.state.atelier
        assert attendre(lambda: etat.pont.actif, 10)
        c.put("/api/lieux/demo/personnalites", json=E.exemple_equipe("personnalites"))
        # le pont du serveur et l'écouteur se découvrent : l'annonce est fiable et transient_local
        r = c.post("/api/lieux/demo/personnalites/active", json={"id": "discret"}).json()
        assert r["publie"] is True
        assert attendre(lambda: ecouteur.personnalites, 10), "rien reçu sur /personnalite/active"
        m = json.loads(ecouteur.personnalites[-1])
        assert m["id"] == "discret" and m["nom"] == "Discret" and m["lieu"] == "demo" and m["vitesse_max"] == 0.25
        assert valider_message("personnalite_active", m) == []
        assert attendre(lambda: (c.get("/api/equipe/etat").json()["personnalite"] or {}).get("id") == "discret", 10)
        # une phrase envoyée « au robot » part sur /visiteur/texte, texte brut
        assert attendre(lambda: c.post("/api/equipe/visiteur", json={"texte": "réveil"}).json()["ecoute"] > 0, 10)
        r = c.post("/api/equipe/visiteur", json={"texte": "  je cherche la salle b204  "}).json()
        assert r["envoye"] == "je cherche la salle b204" and r["ecoute"] >= 1 and "avertissement" not in r
        assert attendre(lambda: "je cherche la salle b204" in ecouteur.textes, 10)
        # ce que la voix et la caméra publient apparaît dans l'état de l'équipe
        ecouteur.publier(ecouteur.pub_dire, E.message_robot_dire("Bonjour !", "dialogue"))
        vus = {"version": 1, "source": "camera", "temps": 1.0,
               "personnes": [{"id": 1, "x": 1.5, "y": 0.0, "distance_m": 1.5, "angle_rad": 0.0, "confiance": 0.9}]}
        assert attendre(lambda: (ecouteur.publier(ecouteur.pub_visiteurs, vus)
                                 or c.get("/api/equipe/etat").json()["visiteurs"] is not None), 10)
        e = c.get("/api/equipe/etat").json()
        assert e["ros"]["actif"] and e["dire"][-1]["texte"] == "Bonjour !"
        assert e["visiteurs"]["personnes"][0]["id"] == 1 and e["visiteurs"]["perime"] is False
        with c.websocket_connect("/ws/etat") as ws:
            direct = ws.receive_json()
        assert direct["visiteurs"]["source"] == "camera"
        time.sleep(0.1)
