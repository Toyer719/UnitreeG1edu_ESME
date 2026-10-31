"""Routes /api/pilotage/* et /ws/pilotage de l'Atelier (section 11.5 du plan), sans ROS.

Le vrai nœud pilotage (logique, cœur et API tornado de ws/src/g1_pilotage) tourne dans un fil de ce
test, sur un port libre, devant le faux G1 en mémoire (g1_jumeau.robot) : l'Atelier relaie, le
nœud décide. Chorégraphies dans un dossier temporaire ($ATELIER_CHOREGRAPHIES).
"""
import asyncio
import json
import socket
import sys
import threading
import time

import pytest

import atelier
from atelier.lieu import pilotage as D

sys.path[:0] = [str(atelier.RACINE / "ws" / "src" / "g1_pilotage"), str(atelier.RACINE / "ws" / "src" / "g1_jumeau")]
tornado = pytest.importorskip("tornado")

from g1_jumeau.camera import FausseCamera  # noqa: E402
from g1_jumeau.logique import FauxSport  # noqa: E402
from g1_jumeau.robot import FauxG1  # noqa: E402
from g1_pilotage.coeur import Coeur  # noqa: E402
from g1_pilotage.logique import Bras, Envoi, Pilotage  # noqa: E402
from g1_pilotage.serveur import creer_application  # noqa: E402


def port_libre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class NoeudEnMemoire:
    """Le nœud pilotage sans ROS : API tornado dans un fil, pas à 50 Hz, faux G1 en mémoire."""

    def __init__(self, jeton=""):
        self.port = port_libre()
        self.recues = []
        self.bras = []
        self.robot = FauxG1(FauxSport())
        self.camera = FausseCamera()                 # caméra de la tête (Vue du robot)
        self.coeur = Coeur(Pilotage(), self.publier)
        self.jeton = jeton
        self.fin = threading.Event()
        self.pret = threading.Event()
        self.boucle = None

    def publier(self, sorties):
        for s in sorties:
            t = time.monotonic()
            if isinstance(s, Bras):
                self.bras.append((t, s))
                q = [0.0] * 35
                kp = [0.0] * 35
                for i, v in s.q.items():
                    q[i], kp[i] = v, s.kp[i]
                q[29] = s.poids
                self.robot.arm_sdk.recevoir(q, kp, kp)
            if not isinstance(s, Envoi):
                continue
            self.recues.append((t, s))
            if s.service == "videohub":
                self.coeur.sur_image(s.identifiant, *self.camera.traiter(s.api_id, s.parametre))
                continue
            reponse = self.robot.traiter(s.service, s.api_id, s.parametre)
            if reponse is not None:
                self.coeur.sur_reponse(s.identifiant, *reponse)

    def _tourner(self):
        from tornado import ioloop
        asyncio.set_event_loop(asyncio.new_event_loop())
        self.boucle = ioloop.IOLoop.current()
        creer_application(self.coeur, self.jeton).listen(self.port, address="127.0.0.1")
        pas = ioloop.PeriodicCallback(self.coeur.pas, 20)
        pas.start()
        self.coeur.entree("sur_lowstate", [0.0] * 35)
        lowstate = ioloop.PeriodicCallback(lambda: self.coeur.entree("sur_lowstate", [0.0] * 35), 100)
        lowstate.start()
        self.pret.set()
        self.boucle.start()

    def demarrer(self):
        threading.Thread(target=self._tourner, daemon=True).start()
        assert self.pret.wait(5)
        time.sleep(0.1)
        return self

    def arreter(self):
        if self.boucle is not None:
            self.boucle.add_callback(self.boucle.stop)

    def marche(self, depuis=0.0):
        return [(t, json.loads(s.parametre)) for t, s in self.recues if s.api_id == 7105 and t >= depuis]


@pytest.fixture
def noeud(monkeypatch):
    n = NoeudEnMemoire().demarrer()
    monkeypatch.setenv("G1_PILOTAGE_URL", f"http://127.0.0.1:{n.port}")
    monkeypatch.setenv("G1_PILOTAGE_JETON", "")
    yield n
    n.arreter()


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from atelier.serveur.main import creer_app
    dossier = tmp_path / "choregraphies"
    dossier.mkdir()
    (dossier / "musique").mkdir()
    exemple = D.chemin_choregraphie("exemple_kpop")
    (dossier / exemple.name).write_text(exemple.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv("ATELIER_CHOREGRAPHIES", str(dossier))
    monkeypatch.setenv("ATELIER_LIEUX", str(tmp_path / "lieux"))
    monkeypatch.setenv("ATELIER_BIN", str(tmp_path / "bin_vide"))
    with TestClient(creer_app(ros=False)) as c:
        yield c


def prendre(client):
    r = client.post("/api/pilotage/maitre", json={"maitre": "pilotage"})
    assert r.status_code == 200 and r.json()["maitre"] == "pilotage", r.json()


def test_config_sans_robot(client):
    c = client.get("/api/pilotage/config").json()
    assert {p["fsm"] for p in c["postures"]} == set(D.POSTURES)
    assert [p for p in c["postures"] if p["fsm"] == 1][0]["confirmation"] == "portique"
    assert c["danses_interdites"] == [401, 402, 403] and len(c["articulations"]) == 14
    assert c["limites_marche"] == D.LIMITES_MARCHE and c["local"] is True
    # vague 5 (section 12.6) : vitesse minimale et modes de marche, rien de refusé
    assert c["vitesse_max_refusee"] is None and c["vitesses_min"] == {"lin": 0.2, "rot": 0.3}
    assert c["modes_marche"] == [500, 501, 801]


def test_config_vitesse_max_sous_0_2_refusee(client, monkeypatch):
    monkeypatch.setenv("G1_VITESSE_MAX", "0.15")
    c = client.get("/api/pilotage/config").json()
    assert "le robot ne marche pas sous 0,2 m/s" in c["vitesse_max_refusee"]
    assert c["limites_marche"] == D.LIMITES_MARCHE          # le nœud, lui, refusera de démarrer
    monkeypatch.setenv("G1_VITESSE_MAX", "0.25")
    c = client.get("/api/pilotage/config").json()
    assert c["vitesse_max_refusee"] is None and c["limites_marche"]["vx"] == 0.25


def test_avertissements_des_pas_sous_la_vitesse_minimale(client):
    """Un pas à 0,1 m/s n'est pas une erreur : un avertissement dit qu'il sera fait à 0,2 m/s."""
    d = client.get("/api/pilotage/choregraphies/exemple_kpop").json()
    assert d["avertissements"] == []
    lente = json.loads(json.dumps(d["choregraphie"]))
    lente["pas"][0].update(vy=0.1, duree_s=1.0)
    r = client.post("/api/pilotage/choregraphies/verifier", json={"choregraphie": lente}).json()
    assert r["sure"] and r["erreurs"] == []
    (avertissement,) = r["avertissements"]
    assert "pas à 10 s" in avertissement and "même trajet" in avertissement
    r = client.put("/api/pilotage/choregraphies/lente", json={"choregraphie": lente}).json()
    assert len(r["avertissements"]) == 1
    liste = {c["id"]: c for c in client.get("/api/pilotage/choregraphies").json()["choregraphies"]}
    assert len(liste["lente"]["avertissements"]) == 1 and liste["exemple_kpop"]["avertissements"] == []


def test_noeud_injoignable_503_en_francais(client, monkeypatch):
    monkeypatch.setenv("G1_PILOTAGE_URL", f"http://127.0.0.1:{port_libre()}")
    for methode, chemin in (("get", "/api/pilotage/etat"), ("post", "/api/pilotage/posture"),
                            ("get", "/api/pilotage/danses")):
        r = getattr(client, methode)(chemin, **({"json": {"fsm": 500}} if methode == "post" else {}))
        assert r.status_code == 503 and "ne répond pas" in r.json()["detail"]
    r = client.post("/api/pilotage/arret")
    assert r.status_code == 503 and "télécommande" in r.json()["detail"]
    assert client.get("/api/pilotage/gestes").json()["gestes"]          # liste du contrat


def test_demarrer_refuse_sans_commande_ou_noeud_distant(client, monkeypatch):
    monkeypatch.setenv("G1_PILOTAGE_URL", f"http://127.0.0.1:{port_libre()}")
    r = client.post("/api/pilotage/demarrer")
    assert r.status_code == 503 and "g1-pilotage" in r.json()["detail"]
    monkeypatch.setenv("G1_PILOTAGE_URL", "http://10.0.0.7:8010")
    r = client.post("/api/pilotage/demarrer")
    assert r.status_code == 409 and "pas sur ce PC" in r.json()["detail"]
    assert client.post("/api/pilotage/arreter").json()["arrete"] is False


def test_relais_des_regles_du_noeud(client, noeud):
    etat = client.get("/api/pilotage/etat").json()
    assert etat["maitre"] == "guide" and etat["url"].endswith(str(noeud.port))
    assert client.post("/api/pilotage/posture", json={"fsm": 500}).status_code == 409     # sans la main
    prendre(client)
    assert client.post("/api/pilotage/posture", json={"fsm": 500}).status_code == 200
    r = client.post("/api/pilotage/posture", json={"fsm": 1})
    assert r.status_code == 428 and r.json()["confirmation"] == "portique"
    avant = len(noeud.recues)
    for corps in ({"service": "sport", "api_id": 7104, "parametre": {"data": 1}},
                  {"service": "sport", "api_id": 7110, "parametre": {}}):
        r = client.post("/api/pilotage/requete", json=corps)
        assert r.status_code == 403 and "interdite" in r.json()["detail"]
    for fsm in (2, 4, 801):
        assert client.post("/api/pilotage/posture", json={"fsm": fsm}).status_code == 403
    assert not [s for _, s in noeud.recues[avant:] if s.api_id != 7001]
    assert noeud.robot.etat()["nombre_interdits"] == 0
    r = client.post("/api/pilotage/posture", content="pas du json", headers={"Content-Type": "application/json"})
    assert r.status_code == 400 and "JSON" in r.json()["detail"]
    for texte in ('{"fsm": NaN}', '{"service": "sport", "api_id": 7105, "parametre": {"velocity": [Infinity, 0, 0]}}'):
        r = client.post("/api/pilotage/requete", content=texte, headers={"Content-Type": "application/json"})
        assert r.status_code == 400 and "NaN" in r.json()["detail"], r.json()
    r = client.post("/api/pilotage/led", json={"r": 255, "g": 0, "b": 128})
    assert r.status_code == 200 and noeud.robot.led == {"R": 255, "G": 0, "B": 128}


def test_danses_lues_et_interdites(client, noeud):
    prendre(client)
    assert client.get("/api/pilotage/danses").status_code == 409            # pas encore lue
    r = client.get("/api/pilotage/danses?lire=1").json()
    assert {d["id"] for d in r["danses"] if d["interdite"]} == {401, 402, 403}
    for n in (401, 402, 403):
        assert client.post("/api/pilotage/danse", json={"id": n, "zone_libre": True}).status_code == 403
    assert client.post("/api/pilotage/danse", json={"id": 604}).status_code == 428
    time.sleep(1.1)                                                     # lecture du mode : 501
    r = client.post("/api/pilotage/danse", json={"id": 604, "zone_libre": True})
    assert r.status_code == 200, r.json()
    assert noeud.robot.etat()["danse"]["id"] == 604 and noeud.robot.danses_jouees == [604]
    assert client.post("/api/pilotage/geste", json={"action": 26}).status_code == 409
    r = client.post("/api/pilotage/arret")
    assert r.status_code == 200 and r.json()["danse"] is True


def test_choregraphies_lire_verifier_ecrire_jouer(client, noeud):
    liste = client.get("/api/pilotage/choregraphies").json()["choregraphies"]
    assert [c["id"] for c in liste] == ["exemple_kpop"] and liste[0]["erreurs"] == [] and liste[0]["protegee"]
    d = client.get("/api/pilotage/choregraphies/exemple_kpop").json()
    assert d["erreurs"] == [] and d["resume"]["vitesse_bras_max"] <= D.VITESSE_BRAS_MAX
    contenu = d["choregraphie"]
    assert client.put("/api/pilotage/choregraphies/exemple_kpop", json={"choregraphie": contenu}).status_code == 409
    faux = json.loads(json.dumps(contenu))
    faux["bras"]["poses"][3]["q"]["left_elbow"] = 2.9
    r = client.post("/api/pilotage/choregraphies/verifier", json={"choregraphie": faux}).json()
    assert not r["sure"] and any("limites" in e for e in r["erreurs"])
    r = client.put("/api/pilotage/choregraphies/ma_danse", json={"choregraphie": faux})
    assert r.status_code == 422 and r.json()["erreurs"]
    r = client.put("/api/pilotage/choregraphies/ma_danse", json={"choregraphie": contenu})
    assert r.status_code == 200 and r.json()["choregraphie"]["id"] == "ma_danse"
    relue = client.get("/api/pilotage/choregraphies/ma_danse").json()
    assert relue["choregraphie"]["bras"] == contenu["bras"] and relue["erreurs"] == []
    assert client.get("/api/pilotage/choregraphies/..%2Fetc").status_code in (400, 404)
    assert client.get("/api/pilotage/choregraphies/Pas-Bon").status_code == 400
    # jouer : zone libre, puis le nœud la joue (rt/arm_sdk vérifié par le faux G1)
    prendre(client)
    time.sleep(1.1)
    assert client.post("/api/pilotage/choregraphies/ma_danse/jouer", json={}).status_code == 428
    r = client.post("/api/pilotage/choregraphies/ma_danse/jouer", json={"zone_libre": True})
    assert r.status_code == 200 and r.json()["duree_s"] == contenu["duree_s"]
    time.sleep(4.0)
    etat = client.get("/api/pilotage/etat").json()
    assert etat["activite"] == "choregraphie" and etat["choregraphie"]["poids_bras"] > 0.5
    r = client.post("/api/pilotage/arret")
    assert r.status_code == 200
    time.sleep(1.5)
    arm = noeud.robot.arm_sdk.etat()
    assert arm["ecarts"] == {k: 0 for k in arm["ecarts"]}, arm["exemples"]
    assert noeud.bras[-1][1].poids == 0.0
    assert client.delete("/api/pilotage/choregraphies/ma_danse").status_code == 200
    assert client.delete("/api/pilotage/choregraphies/exemple_kpop").status_code == 409


def test_musique_et_modele(client):
    assert client.get("/api/pilotage/musique/chanson.mp3").status_code == 404
    assert client.get("/api/pilotage/musique/..%2F..%2Fsecret.mp3").status_code in (400, 404)
    assert client.get("/api/pilotage/musique/notes.txt").status_code == 400
    from atelier.serveur.routes import pilotage as R
    if not R.URDF_G1.is_file():
        pytest.skip("URDF du G1 absent (third_party)")
    m = client.get("/api/pilotage/modele").json()
    assert m["racine"] == "pelvis" and len([a for a in m["articulations"] if a["type"] == "revolute"]) == 29
    noms = {a["nom"].removesuffix("_joint") for a in m["articulations"]}
    assert set(D.ARTICULATIONS_BRAS) <= noms
    if m["maillages"]:
        r = client.get("/api/pilotage/modele/maillages/pelvis.STL")
        assert r.status_code == 200 and len(r.content) > 1000
    assert client.get("/api/pilotage/modele/maillages/..%2Fx.STL").status_code in (400, 404)
    assert client.get("/api/pilotage/modele/maillages/pelvis.stl").status_code == 400


def test_joystick_par_le_websocket_de_l_atelier(client, noeud):
    prendre(client)
    debut = time.monotonic()
    with client.websocket_connect("/ws/pilotage") as ws:
        assert json.loads(ws.receive_text())["type"] == "bienvenue"
        for _ in range(10):
            ws.send_text(json.dumps({"vx": 1.0, "vy": 0.0, "wz": 0.0}))
            time.sleep(0.1)
        ordres = [o for _, o in noeud.marche(debut) if o["velocity"] != [0.0, 0.0, 0.0]]
        assert len(ordres) >= 8 and all(o["velocity"] == [0.4, 0.0, 0.0] for o in ordres)
        coupure = time.monotonic()
    time.sleep(0.4)
    arrets = [t for t, o in noeud.marche(coupure) if o["velocity"] == [0.0, 0.0, 0.0]]
    assert arrets and arrets[0] - coupure < 0.6           # WebSocket fermé : StopMove


def test_joystick_sans_noeud(client, monkeypatch):
    monkeypatch.setenv("G1_PILOTAGE_URL", f"http://127.0.0.1:{port_libre()}")
    with client.websocket_connect("/ws/pilotage") as ws:
        m = json.loads(ws.receive_text())
        assert m["type"] == "refus" and "ne répond pas" in m["detail"]


def test_jeton_transmis(client, monkeypatch):
    n = NoeudEnMemoire(jeton="jeton-du-test").demarrer()
    try:
        monkeypatch.setenv("G1_PILOTAGE_URL", f"http://127.0.0.1:{n.port}")
        monkeypatch.setenv("G1_PILOTAGE_JETON", "mauvais")
        r = client.get("/api/pilotage/etat")
        assert r.status_code == 401 and "G1_PILOTAGE_JETON" in r.json()["detail"]
        monkeypatch.setenv("G1_PILOTAGE_JETON", "jeton-du-test")
        assert client.get("/api/pilotage/etat").status_code == 200
    finally:
        n.arreter()


def test_camera_de_la_tete_relayee(client, noeud):
    """Vue du robot (section 11.13) : JPEG du service videohub, lecture seule (sans la main)."""
    from atelier.serveur.routes import pilotage as routes
    r = client.get("/api/pilotage/camera")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert r.content[:2] == b"\xff\xd8" and r.headers["x-image-numero"] == "1"
    assert r.headers["cache-control"] == "no-store"
    # pages qui demandent en même temps : une image partagée, une demande au robot
    r2 = client.get("/api/pilotage/camera")
    assert r2.status_code == 200 and r2.headers["x-image-numero"] == "1"
    time.sleep(routes.CacheCamera.PARTAGE_S + D.CAMERA_ECART_MIN_S)
    assert client.get("/api/pilotage/camera").headers["x-image-numero"] == "2"
    demandes = [s for _, s in noeud.recues if s.service == "videohub"]
    assert len(demandes) == 2 and all(s.api_id == D.API_VIDEO["get_image_sample"] for s in demandes)
    assert client.get("/api/pilotage/etat").json()["maitre"] == "guide"      # rien n'a changé


def test_camera_sans_noeud_ou_sans_image(client, noeud, monkeypatch):
    monkeypatch.setenv("G1_PILOTAGE_URL", f"http://127.0.0.1:{port_libre()}")
    time.sleep(0.2)
    r = client.get("/api/pilotage/camera")
    assert r.status_code == 503 and "ne répond pas" in r.json()["detail"]
    monkeypatch.setenv("G1_PILOTAGE_URL", f"http://127.0.0.1:{noeud.port}")
    noeud.camera.traiter = lambda api_id, parametre: (3104, b"")       # caméra muette
    noeud.coeur.camera.ecart_min_s = 0.0
    time.sleep(0.2)
    r = client.get("/api/pilotage/camera")
    assert r.status_code == 503 and "code 3104" in r.json()["detail"]
