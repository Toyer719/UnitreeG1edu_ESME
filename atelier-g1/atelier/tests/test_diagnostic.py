"""Le diagnostic « Vérifier le robot » sans ROS (vague 6, section 13.2 du plan) : agent Diagnostic.

Vérifications injectées : un faux pont (test_diagnostic_communs.FauxPont, avec le vrai service robot_state du faux
G1) et le faux contexte des vérifications système (ATELIER_DIAGNOSTIC_FAUX), jamais rien vers le réseau du robot.

- les contextes : le faux (fichier relu, journal de chaque commande, délais simulés), celui des essais (ni ping, ni
  ssh, ni nmcli up), le vrai sur ce PC (fichier, commande, délai, commande absente, ping de 127.0.0.1) ;
- les verdicts, cas par cas (câble, adresse, connexion, ROS, pings, sujets, services, mode, batterie, Jetson, caméra) :
  un conseil pour chaque état qui n'est pas OK, une phrase, aucun nom de sujet ROS à l'écran ;
- le diagnostic complet : conforme au schéma et à ses règles, en parallèle et à temps (une vérification qui ne
  répond pas devient « inconnu »), répétition (le réseau et le Jetson dans « ignorees »), câble absent, rapide ;
- les actions : liste blanche, jamais d'arrêt de service, rien sans « oui », câble par nmcli (noté, pas lancé) ;
- g1-diagnostic : texte, --json, code de sortie, --action et sa confirmation.
"""
import io
import json
import os
import shutil
import subprocess
import sys
import time

import pytest

import atelier
from atelier.diagnostic import (ActionImpossible, ActionInconnue, ContexteEssais, ContexteSysteme, EssaisInterdits,
                                FauxContexte, ServiceInterdit, contexte_par_defaut, diagnostiquer, faire_action,
                                normaliser_mode, services_demandes, verifier_action)
from atelier.diagnostic import actions as A
from atelier.diagnostic import sondes as S
from atelier.diagnostic import verdicts as V
from atelier.diagnostic.texte import texte_action, texte_diagnostic
from atelier.lieu import diagnostic as G
from atelier.lieu import valider_donnees
from atelier.lieu.diagnostic import VERIFICATIONS, VERIFICATIONS_REPETITION

from .test_diagnostic_communs import (EMPREINTE, GRAPHE_FAUX_G1, GRAPHE_ROBOT, FauxPont, ecrire_faux, faux_systeme,
                                      lire_journal, par_id, script_jetson)

SUJETS_ROS_A_L_ECRAN = ("/api/", "/lf/", "/state_estimator", "/unitree", "/pont/", "/camera_poitrine", "rt/",
                        "robot_state 100", "1003", "1001")


@pytest.fixture
def faux(tmp_path, monkeypatch):
    """Un fichier de faux contexte (tout va bien), et la variable qui le désigne."""
    chemin = ecrire_faux(tmp_path / "faux.json", faux_systeme())
    monkeypatch.setenv("ATELIER_DIAGNOSTIC_FAUX", str(chemin))
    return chemin


def conforme(d):
    """Le diagnostic suit le schéma et ses règles, et ses textes les règles de l'interface."""
    assert valider_donnees("diagnostic", d) == [], valider_donnees("diagnostic", d)
    for v in d["verifications"]:
        for champ in ("titre", "detail", "conseil"):
            texte = v.get(champ) or ""
            assert "\n" not in texte and len(texte) <= 300, (v["id"], champ, texte)
            assert not any(x in texte for x in SUJETS_ROS_A_L_ECRAN), (v["id"], champ, texte)
        if v["etat"] != "ok":
            assert v["conseil"], v
        assert v["detail"].rstrip().endswith((".", "!")), (v["id"], v["detail"])
    return d


# ---------------------------------------------------------------- contextes

def test_faux_contexte_lit_tout_dans_le_fichier_et_note_chaque_commande(tmp_path):
    chemin = ecrire_faux(tmp_path / "f.json", {
        "fichiers": {"/sys/class/net/eno2/carrier": "1\n"},
        "commandes": {"nmcli connection up robot-g1": {"code": 0, "sortie": "ok"}},
        "ping": {"192.168.123.161": 0.7, "192.168.123.164": None},
        "env": {"ROS_DOMAIN_ID": "0"}, "adresses": {"eno2": "192.168.123.99"}})
    ctx = FauxContexte.depuis_fichier(chemin)
    assert ctx.faux and ctx.lire("/sys/class/net/eno2/carrier") == "1\n" and ctx.lire("/absent") is None
    assert ctx.commande(["nmcli", "connection", "up", "robot-g1"]).code == 0
    assert ctx.commande(["nmcli", "inconnue"]).code == 127
    assert ctx.ping("192.168.123.161") == 0.7 and ctx.ping("192.168.123.164") is None and ctx.ping("1.2.3.4") is None
    r = ctx.ssh("echo")                      # pas de réponse : comme un délai dépassé
    assert r.code == 255 and "timed out" in r.erreur
    assert ctx.env("ROS_DOMAIN_ID") == "0" and ctx.env("HOME") == os.environ["HOME"]
    assert ctx.adresse_ipv4("eno2") == "192.168.123.99" and ctx.adresse_ipv4("eno3") is None
    journal = lire_journal(chemin)
    assert [x["genre"] for x in journal] == ["commande", "commande", "ping", "ping", "ping", "ssh"]
    assert journal[0]["commande"] == "nmcli connection up robot-g1" and journal[0]["mots"][-1] == "robot-g1"
    assert journal[5]["hote"] == "unitree@192.168.123.164"
    with pytest.raises(ValueError, match="illisible"):
        FauxContexte.depuis_fichier(tmp_path / "absent.json")


def test_faux_contexte_heure_du_jetson_au_moment_du_ssh():
    ctx = FauxContexte(faux_systeme(ssh={"code": 0, "sortie": script_jetson()}))
    time.sleep(0.2)
    heure = float(S.lire_champs_jetson(ctx.ssh("x").sortie)[0]["heure"])
    assert abs(heure - time.time()) < 0.1


def test_faux_contexte_delais_simules(tmp_path):
    ctx = FauxContexte(faux_systeme(delais={"ping": 0.3}))
    debut = time.monotonic()
    assert ctx.ping("192.168.123.161") == 0.6
    assert time.monotonic() - debut >= 0.29


def test_contexte_des_essais_ne_touche_jamais_le_reseau_du_robot():
    ctx = ContexteEssais()
    with pytest.raises(EssaisInterdits):
        ctx.ping("192.168.123.161")
    with pytest.raises(EssaisInterdits):
        ctx.ssh("true")
    for mots in (["nmcli", "connection", "up", "robot-g1"], ["nmcli", "connection", "modify", "robot-g1", "x", "y"],
                 ["nmcli", "con", "up", "robot-g1"]):
        with pytest.raises(EssaisInterdits):
            ctx.commande(mots)
    assert ctx.commande(["true"]).code == 0              # le reste marche (lecture de nmcli, docker…)


def test_contexte_systeme_sur_ce_pc(tmp_path):
    ctx = ContexteSysteme()
    f = tmp_path / "carrier"
    f.write_text("1\n")
    assert ctx.lire(f) == "1\n" and ctx.lire(tmp_path / "absent") is None
    r = ctx.commande(["echo", "bonjour"])
    assert r.code == 0 and r.sortie == "bonjour\n"
    assert ctx.commande(["commande-qui-n-existe-pas"]).code == 127
    lent = ctx.commande(["sleep", "5"], delai=0.3)
    assert lent.code == 124 and lent["duree_s"] < 2.0
    assert ctx.adresse_ipv4("lo") == "127.0.0.1" and ctx.adresse_ipv4("interface_absente") is None
    if shutil.which("ping"):
        ms = ctx.ping("127.0.0.1")                       # jamais vers le robot pendant les essais
        assert ms is not None and ms >= 0


def test_contexte_par_defaut(tmp_path, monkeypatch):
    monkeypatch.delenv("ATELIER_DIAGNOSTIC_FAUX", raising=False)
    monkeypatch.delenv("G1_SLAM_FAUX", raising=False)
    assert type(contexte_par_defaut()) is ContexteSysteme
    monkeypatch.setenv("G1_SLAM_FAUX", "1")
    assert type(contexte_par_defaut()) is ContexteEssais
    monkeypatch.setenv("ATELIER_DIAGNOSTIC_FAUX", str(ecrire_faux(tmp_path / "f.json", {})))
    assert type(contexte_par_defaut()) is FauxContexte


def test_outils_de_lecture():
    assert S.lire_terse("robot-g1:eno2:activated") == ["robot-g1", "eno2", "activated"]
    assert S.lire_terse(r"Wi-Fi\:maison:wlo1:activated") == ["Wi-Fi:maison", "wlo1", "activated"]
    champs, cameras = S.lire_champs_jetson("docker_ok=oui\nimage=sha256:ab\ncamera=/dev/v4l/x|/dev/video0|480\n"
                                           "camera=/dev/v4l/y|/dev/video2|\nfin=oui\n")
    assert champs == {"docker_ok": "oui", "image": "sha256:ab", "fin": "oui"}
    assert cameras[0] == {"by_id": "/dev/v4l/x", "chemin": "/dev/video0", "usb_mbps": 480}
    assert cameras[1]["usb_mbps"] is None
    from atelier.diagnostic.contexte import interface_cyclonedds
    from atelier.serveur.routes.liaison import interface_cyclonedds as celle_de_la_liaison
    from .test_diagnostic_communs import URI_ROBOT
    for uri in (URI_ROBOT, "", "<NetworkInterfaceAddress>enp3s0</NetworkInterfaceAddress>",
                "<NetworkInterface name='wlo1'/>"):
        assert interface_cyclonedds(uri) == celle_de_la_liaison(uri), uri
    assert V.nombre(0.62) == "0,6" and V.nombre(12.0) == "12" and V.nombre(41.04) == "41" and V.nombre(3.5, 0) == "4"
    assert V.liste_noms(["a"]) == "a" and V.liste_noms(["a", "b", "c"]) == "a, b et c"
    assert V.typographie("Cliquez sur « Démarrer »") == "Cliquez sur « Démarrer »"


# ---------------------------------------------------------------- verdicts (fonctions pures)

def faits_robot(**changements):
    """Les faits d'un vrai robot en bonne santé, puis les changements demandés (une sonde à la fois)."""
    faits = {
        "_interface": "eno2",
        "cable": {"interface": "eno2", "carrier": "1", "operstate": "up"},
        "adresse": {"adresse": "192.168.123.99"},
        "profil": {"code_actives": 0, "actives": [{"nom": "robot-g1", "interface": "eno2", "etat": "activated"}],
                   "code_profil": 0, "autoconnect": "yes"},
        "ros": {"domaine": "0", "interface_dds": "eno2", "pont_actif": True},
        "pc1": {"adresse": "192.168.123.161", "repond": True, "ms": 0.6},
        "jetson": {"adresse": "192.168.123.164", "repond": True, "ms": 0.5},
        "lidar": {"adresse": "192.168.123.120", "repond": True, "ms": 0.9},
        "sujets": {"vus": {s: dict(GRAPHE_ROBOT[s]) for s in GRAPHE_ROBOT}},
        "services": {"code": 0, "services": [{"name": "lidar_driver", "status": 0, "protect": False},
                                             {"name": "unitree_slam", "status": 0, "protect": False}]},
        "mode": {"fsm": 501, "source": "7001"},
        "batterie": {"soc": 87},
        "camera": {"etat": None},
        "ssh": {"code": 0, "erreur": "", "complet": True, "t0": 100.0, "t1": 100.4, "cameras": [
            {"by_id": "/dev/v4l/by-id/usb-See3CAM", "chemin": "/dev/video0", "usb_mbps": 5000}],
                "champs": {"docker_ok": "oui", "image": EMPREINTE, "place_ko": "40000000",
                           "place_docker_ko": "40000000", "heure": "100.2", "fin": "oui"}},
        "image_pc": {"code": 0, "empreinte": EMPREINTE},
    }
    for nom, valeur in changements.items():
        faits[nom] = valeur
    return faits


def juger(faits, mode="reel", source="atelier"):
    verifications, ignorees = V.juger(faits, mode, source=source)
    d = G.diagnostic(verifications, mode, "2026-11-12T14:03:05+01:00", 1.0, ignorees=ignorees, source=source)
    return conforme(d)


def test_tout_va_bien_sur_le_vrai_robot():
    d = juger(faits_robot())
    assert d["etat"] == "ok" and d["ignorees"] == [] and d["actions"] == []
    assert [v["id"] for v in d["verifications"]] == list(VERIFICATIONS)
    assert d["message"] == "Tout va bien : le robot est prêt." and G.code_de_sortie(d) == 0


@pytest.mark.parametrize("cable, etat, action, mot", [
    ({"carrier": "0", "operstate": "down"}, "probleme", None, "Branchez"),
    ({"carrier": None, "operstate": "down"}, "attention", "retablir-cable", "Rétablir"),
    ({"carrier": None, "operstate": None}, "probleme", None, "ATELIER_INTERFACE_ROBOT"),
])
def test_cable(cable, etat, action, mot):
    sautes = {nom: {"adresse": "x", "saute": "cable"} for nom in ("pc1", "jetson", "lidar")}    # comme les sondes
    d = juger(faits_robot(cable=dict(cable, interface="eno2"), ssh={"saute": "cable"}, **sautes))
    v = par_id(d)["cable"]
    assert (v["etat"], v["action"]) == (etat, action) and mot in v["conseil"]
    if cable["carrier"] != "1":
        ignorees = {x["id"]: x["raison"] for x in d["ignorees"]}
        assert {"adresse", "pc1", "jetson", "lidar"} <= set(ignorees)
        assert ignorees["pc1"] == "le câble n'est pas branché"


def test_adresse_et_connexion():
    v = par_id(juger(faits_robot(adresse={"adresse": "192.168.123.50"})))["adresse"]
    assert v["etat"] == "attention" and v["action"] == "retablir-cable"
    v = par_id(juger(faits_robot(adresse={"adresse": None})))["adresse"]
    assert v["etat"] == "probleme" and v["action"] == "retablir-cable"
    actives = [{"nom": "robot-g1", "interface": "eno2", "etat": "activated"}]
    cas = {
        "autoconnect no": ({"code_actives": 0, "actives": actives, "code_profil": 0, "autoconnect": "no"},
                           "attention", "cable-automatique"),
        "éteinte": ({"code_actives": 0, "actives": [], "code_profil": 0, "autoconnect": "no"}, "probleme",
                    "retablir-cable"),
        "absente": ({"code_actives": 0, "actives": [], "code_profil": 10, "autoconnect": None}, "probleme", None),
        "autre port": ({"code_actives": 0, "actives": [{"nom": "robot-g1", "interface": "enx00", "etat": "a"}],
                        "code_profil": 0, "autoconnect": "yes"}, "attention", None),
        "sans nmcli": ({"code_actives": 127, "actives": None, "code_profil": 127}, "inconnu", None),
    }
    for nom, (profil, etat, action) in cas.items():
        v = par_id(juger(faits_robot(profil=profil)))["profil"]
        assert (v["etat"], v["action"]) == (etat, action), (nom, v)
    v = par_id(juger(faits_robot(profil=cas["absente"][0])))["profil"]
    assert "robot.sh" in v["conseil"]
    # sans câble, connexion éteinte qui ne se rallume pas seule : on propose le réglage automatique
    d = juger(faits_robot(cable={"carrier": "0", "operstate": "down"}, profil=cas["éteinte"][0]))
    assert par_id(d)["profil"]["action"] == "cable-automatique"


def test_reglages_ros():
    v = par_id(juger(faits_robot(ros={"domaine": "141", "interface_dds": None, "pont_actif": True})))["ros"]
    assert v["etat"] == "probleme" and "robot.sh" in v["conseil"]
    v = par_id(juger(faits_robot(ros={"domaine": "0", "interface_dds": "wlo1", "pont_actif": True})))["ros"]
    assert v["etat"] == "attention"
    d = juger(faits_robot(ros={"domaine": "0", "interface_dds": "eno2", "pont_actif": False, "erreur_pont": "x"},
                          sujets={"sans_ros": True}, services={"sans_ros": True}, mode={"sans_ros": True},
                          batterie={"sans_ros": True}))
    assert par_id(d)["ros"]["etat"] == "probleme"
    assert all(par_id(d)[x]["etat"] == "inconnu" for x in ("sujets", "services", "mode", "batterie"))
    v = par_id(juger(faits_robot(ros={"domaine": "141", "pont_actif": True}), source="g1-diagnostic"))["ros"]
    assert v["titre"] == "Réglages ROS de ce terminal" and "g1-diagnostic" in v["conseil"]


def test_pings():
    d = juger(faits_robot(pc1={"adresse": "x", "repond": False, "ms": None}))
    assert par_id(d)["pc1"]["etat"] == "probleme" and d["etat"] == "probleme"
    assert "Le PC1" in d["message"] or "PC1" in d["message"]
    d = juger(faits_robot(jetson={"adresse": "x", "essais": True}, ssh={"essais": True, "erreur": "essais"}))
    assert par_id(d)["jetson"]["etat"] == "inconnu" and "essais" in par_id(d)["jetson"]["detail"]
    assert par_id(d)["jetson_ssh"]["etat"] == "inconnu"
    assert par_id(juger(faits_robot(lidar={"commande_absente": True})))["lidar"]["etat"] == "inconnu"


def test_sujets():
    sans_slam = {s: dict(GRAPHE_ROBOT[s]) for s in GRAPHE_ROBOT}
    sans_slam["/api/slam_operate/request"] = {"publieurs": ["g1_scan"], "abonnes": []}      # un client seulement
    v = par_id(juger(faits_robot(sujets={"vus": sans_slam})))["sujets"]
    assert v["etat"] == "attention" and v["action"] is None and "Attendez" in v["conseil"]   # services actifs
    arretes = {"code": 0, "services": [{"name": "lidar_driver", "status": 1, "protect": False},
                                       {"name": "unitree_slam", "status": 1, "protect": False}]}
    v = par_id(juger(faits_robot(sujets={"vus": sans_slam}, services=arretes)))["sujets"]
    assert v["action"] == "demarrer-services"
    rien = {s: {"publieurs": [], "abonnes": []} for s in GRAPHE_ROBOT}
    v = par_id(juger(faits_robot(sujets={"vus": rien})))["sujets"]
    assert v["etat"] == "probleme" and v["conseil"] == V.RELIER
    v = par_id(juger(faits_robot(sujets={"vus": rien}, cable={"carrier": "0"})))["sujets"]
    assert v["conseil"] == V.CABLE
    moitie = dict(GRAPHE_ROBOT, **{"/lf/sportmodestate": {"publieurs": [], "abonnes": ["x"]}})
    assert par_id(juger(faits_robot(sujets={"vus": moitie})))["sujets"]["etat"] == "attention"
    # répétition : le faux G1 n'a pas /lf/sportmodestate ; sans faux service de cartographie : Attention
    v = par_id(juger(faits_robot(sujets={"vus": dict(GRAPHE_FAUX_G1)}), mode="repetition"))["sujets"]
    assert v["etat"] == "attention" and "Naviguer" in v["conseil"]
    avec_slam = dict(GRAPHE_FAUX_G1, **{"/api/slam_operate/request": {"publieurs": [], "abonnes": ["faux_slam"]}})
    assert par_id(juger(faits_robot(sujets={"vus": avec_slam}), mode="repetition"))["sujets"]["etat"] == "ok"


def test_services():
    def services(*statuts, noms=("lidar_driver", "unitree_slam")):
        return {"code": 0, "services": [{"name": n, "status": s, "protect": False} for n, s in zip(noms, statuts)]}
    v = par_id(juger(faits_robot(services=services(1, 1))))["services"]
    assert v["etat"] == "probleme" and v["action"] == "demarrer-services"
    # corrections de la vague 6 (revue de l'interface, défaut 16) : le nom en français, puis celui de l'appli
    # Unitree, une seule fois
    assert v["detail"] == "Le LiDAR et la cartographie d'Unitree (lidar_driver, unitree_slam) sont arrêtés."
    assert v["donnees"]["services"][0]["name"] == "lidar_driver" and "lidar_driver 1" in v["technique"]
    v = par_id(juger(faits_robot(services=services(0, 1))))["services"]
    assert v["detail"] == "La cartographie d'Unitree (unitree_slam) est arrêtée." and v["action"] == "demarrer-services"
    v = par_id(juger(faits_robot(services=services(0, noms=("lidar_driver",)))))["services"]
    assert v["etat"] == "probleme" and v["action"] is None and "« unitree_slam »" in v["detail"].replace(" ", " ")
    v = par_id(juger(faits_robot(services=services(1, noms=("lidar_driver",)))))["services"]
    assert v["action"] == "demarrer-services"
    assert v["detail"].replace("\u00a0", " ").startswith("Le LiDAR (lidar_driver) est arrêté ; le robot")
    for fait in ({"sans_reponse": True, "erreur": "personne n'écoute"}, {"delai_depasse": True},
                 {"code": 3203, "data": ""}, {"code": 0, "data": "x", "illisible": "liste"},
                 {"erreur": "messages unitree_api introuvables"}):
        v = par_id(juger(faits_robot(services=fait)))["services"]
        assert v["etat"] == "inconnu" and v["action"] is None, fait
    v = par_id(juger(faits_robot(services=services(1, 1)), mode="repetition"))["services"]
    assert v["action"] == "demarrer-services"


def test_mode_du_robot():
    attendus = {501: "ok", 500: "ok", 801: "ok", 802: "attention", 0: "attention", 1: "attention", 3: "attention",
                550604: "attention", 706: "attention"}
    for fsm, etat in attendus.items():
        v = par_id(juger(faits_robot(mode={"fsm": fsm, "source": "pont"})))["mode"]
        assert v["etat"] == etat and v["donnees"]["fsm"] == fsm, (fsm, v)
    assert "assis" in par_id(juger(faits_robot(mode={"fsm": 3})))["mode"]["detail"]
    assert "course" in par_id(juger(faits_robot(mode={"fsm": 802})))["mode"]["detail"]
    for fait in ({"sans_reponse": True}, {"code": 3104}, {"code": 0, "illisible": True}):
        assert par_id(juger(faits_robot(mode=fait)))["mode"]["etat"] == "inconnu", fait


def test_batterie():
    for soc, etat in ((87, "ok"), (30, "ok"), (29, "attention"), (15, "attention"), (14, "probleme"), (3, "probleme")):
        v = par_id(juger(faits_robot(batterie={"soc": soc})))["batterie"]
        assert v["etat"] == etat and v["donnees"] == {"soc": soc} and f"{soc} %" in v["detail"], soc
    assert par_id(juger(faits_robot(batterie={"rien": True})))["batterie"]["etat"] == "inconnu"
    assert par_id(juger(faits_robot(batterie={"type_absent": True, "erreur": "x"})))["batterie"]["etat"] == "inconnu"


def test_jetson_un_seul_ssh():
    d = juger(faits_robot())
    jetson = ("jetson_ssh", "jetson_docker", "jetson_image", "jetson_place", "jetson_horloge", "camera")
    assert all(par_id(d)[x]["etat"] == "ok" for x in jetson)
    refus = {"code": 255, "erreur": "unitree@192.168.123.164: Permission denied (publickey,password).",
             "champs": {}, "cameras": [], "complet": False, "t0": 1, "t1": 2}
    d = juger(faits_robot(ssh=refus))
    v = par_id(d)["jetson_ssh"]
    assert v["etat"] == "probleme" and "ssh-copy-id unitree@192.168.123.164" in v["conseil"]
    assert {x["id"] for x in d["ignorees"]} == {"jetson_docker", "jetson_image", "jetson_place", "jetson_horloge",
                                                "camera"}
    change = dict(refus, erreur=("@@@ WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED! @@@ Host key "
                                 "verification failed."))
    assert "ssh-keygen -R" in par_id(juger(faits_robot(ssh=change)))["jetson_ssh"]["conseil"]
    muet = dict(refus, erreur="ssh: connect to host 192.168.123.164 port 22: Connection timed out")
    assert par_id(juger(faits_robot(ssh=muet)))["jetson_ssh"]["etat"] == "inconnu"

    def jetson(**champs):
        f = faits_robot()["ssh"]
        f["champs"] = dict(f["champs"], **champs)
        return f
    assert par_id(juger(faits_robot(ssh=jetson(docker_ok="non"))))["jetson_docker"]["etat"] == "probleme"
    v = par_id(juger(faits_robot(ssh=jetson(image=""))))["jetson_image"]
    assert v["etat"] == "probleme" and "g1-jetson envoyer" in v["conseil"]
    v = par_id(juger(faits_robot(ssh=jetson(image="sha256:autre"))))["jetson_image"]
    assert v["etat"] == "attention" and "g1-jetson envoyer" in v["conseil"]
    v = par_id(juger(faits_robot(image_pc={"code": 1, "empreinte": None})))["jetson_image"]
    assert v["etat"] == "inconnu" and "g1-jetson construire" in v["conseil"]
    assert par_id(juger(faits_robot(ssh=jetson(place_docker_ko="3000000"))))["jetson_place"]["etat"] == "attention"
    assert par_id(juger(faits_robot(ssh=jetson(place_docker_ko="500000"))))["jetson_place"]["etat"] == "probleme"
    assert par_id(juger(faits_robot(ssh=jetson(place_docker_ko="", place_ko=""))))["jetson_place"]["etat"] == "inconnu"
    v = par_id(juger(faits_robot(ssh=jetson(heure="160.2"))))["jetson_horloge"]
    assert v["etat"] == "attention" and v["donnees"]["ecart_s"] == 60.0 and "date -s" in v["conseil"]
    assert par_id(juger(faits_robot(ssh=jetson(heure="101.5"))))["jetson_horloge"]["etat"] == "ok"   # 1,3 s
    for saute, raison in (("rapide", "vérification rapide, sans le Jetson"), ("jetson", "le Jetson ne répond pas")):
        d = juger(faits_robot(ssh={"saute": saute}))
        ignorees = {x["id"]: x["raison"] for x in d["ignorees"]}
        assert ignorees["jetson_ssh"] == raison and "camera" in ignorees, saute


def test_camera():
    etat = {"ouverte": True, "largeur": 640, "hauteur": 360, "age_recu_s": 0.4}
    assert par_id(juger(faits_robot(camera={"etat": etat})))["camera"]["etat"] == "ok"
    v = par_id(juger(faits_robot(camera={"etat": dict(etat, ouverte=False, erreur="caméra débranchée")})))["camera"]
    assert v["etat"] == "attention"
    f = faits_robot()["ssh"]
    assert par_id(juger(faits_robot(ssh=dict(f, cameras=[]))))["camera"]["etat"] == "attention"
    usb2 = dict(f, cameras=[{"by_id": "x", "chemin": "/dev/video0", "usb_mbps": 480}])
    assert "USB 2" in par_id(juger(faits_robot(ssh=usb2)))["camera"]["detail"]
    # un état de la caméra trop vieux ne compte pas : le ssh le remplace
    vieux = {"etat": dict(etat, ouverte=False, age_recu_s=10.0)}
    assert par_id(juger(faits_robot(camera=vieux)))["camera"]["etat"] == "ok"


def test_repetition_seulement_ce_qui_a_un_sens():
    d = juger(faits_robot(sujets={"vus": dict(GRAPHE_FAUX_G1, **{"/api/slam_operate/request": {
        "publieurs": [], "abonnes": ["faux_slam"]}})}), mode="repetition")
    assert [v["id"] for v in d["verifications"]] == list(VERIFICATIONS_REPETITION)
    assert {x["id"] for x in d["ignorees"]} == set(VERIFICATIONS) - set(VERIFICATIONS_REPETITION)
    assert all(x["raison"] == "sans objet en répétition" for x in d["ignorees"])
    assert d["etat"] == "ok" and "faux G1" in par_id(d)["mode"]["detail"]


def test_une_sonde_qui_n_a_pas_repondu():
    faits = faits_robot(**{nom: {"erreur": "pas de réponse à temps", "delai_depasse": True}
                           for nom in ("cable", "profil", "sujets", "services", "mode", "batterie", "ssh", "pc1")})
    d = juger(faits)
    for ident in ("cable", "profil", "sujets", "services", "mode", "batterie", "jetson_ssh"):
        assert par_id(d)[ident]["etat"] == "inconnu", ident


# ---------------------------------------------------------------- le diagnostic complet

def test_diagnostic_complet_tout_va_bien(faux):
    pont = FauxPont()
    d = conforme(diagnostiquer("reel", pont=pont, contexte=FauxContexte.depuis_fichier(faux)))
    assert d["etat"] == "ok" and d["faux"] is True and d["source"] == "atelier" and len(d["verifications"]) == 17
    assert d["mode"] == "reel" and d["duree_s"] < 5
    # le diagnostic ne demande au robot que la liste des services et le mode : jamais 1001
    assert {(s, a) for s, a, _ in pont.appels} == {("robot_state", 1003), ("sport", 7001)}
    assert pont.messages == [("/lf/bmsstate", "unitree_hg/msg/BmsState")]
    genres = [x["genre"] for x in lire_journal(faux)]
    assert genres.count("ssh") == 1 and genres.count("ping") == 3      # UN ssh, trois pings
    assert not any("up" in x.get("mots", []) or "modify" in x.get("mots", []) for x in lire_journal(faux))


def test_diagnostic_en_repetition_et_services_arretes(faux):
    pont = FauxPont(graphe=GRAPHE_FAUX_G1, arretes=("lidar_driver", "unitree_slam"))
    d = conforme(diagnostiquer("repetition", pont=pont, contexte=FauxContexte.depuis_fichier(faux)))
    assert d["etat"] == "probleme" and d["actions"] == ["demarrer-services"]
    assert par_id(d)["services"]["etat"] == "probleme" and lire_journal(faux) == []    # rien du réseau en répétition
    assert ("robot_state", 1003, "{}") in pont.appels
    assert d["message"].startswith("2 points à régler : Services de cartographie.")


def test_diagnostic_sans_cable(tmp_path):
    chemin = ecrire_faux(tmp_path / "f.json", faux_systeme(cable=False, actif=False))
    d = conforme(diagnostiquer("reel", pont=FauxPont(), contexte=FauxContexte.depuis_fichier(chemin)))
    assert par_id(d)["cable"]["etat"] == "probleme" and par_id(d)["cable"]["conseil"]
    genres = [x["genre"] for x in lire_journal(chemin)]
    assert "ping" not in genres and "ssh" not in genres                 # rien vers le robot sans câble
    assert "Câble du robot" in d["message"]


def test_diagnostic_rapide_sans_ssh(faux):
    d = conforme(diagnostiquer("reel", pont=FauxPont(), contexte=FauxContexte.depuis_fichier(faux), rapide=True))
    assert "ssh" not in [x["genre"] for x in lire_journal(faux)]
    assert {x["id"] for x in d["ignorees"]} >= {"jetson_ssh", "jetson_image"}
    assert all(x["raison"] == "vérification rapide, sans le Jetson" for x in d["ignorees"] if x["id"] != "camera")


def test_diagnostic_en_parallele_et_a_temps(tmp_path, monkeypatch):
    # chaque ping prend 1 s et le ssh 1 s : en série 4 s, en parallèle (pings ensemble, puis ssh) 2 s ; le robot
    # muet fait attendre robot_state, 7001 et la batterie 2 s chacun, en même temps
    chemin = ecrire_faux(tmp_path / "f.json", faux_systeme(delais={"ping": 1.0, "ssh": 1.0}))
    debut = time.monotonic()
    d = conforme(diagnostiquer("reel", pont=FauxPont(muet=True), contexte=FauxContexte.depuis_fichier(chemin)))
    duree = time.monotonic() - debut
    assert duree < 3.5, duree
    assert all(par_id(d)[x]["etat"] == "inconnu" for x in ("services", "mode", "batterie"))
    # une sonde bloquée ne retient pas le diagnostic : « inconnu » à l'échéance
    monkeypatch.setattr(S, "sonde_profil", lambda ctx, interface: time.sleep(30))
    debut = time.monotonic()
    d = conforme(diagnostiquer("reel", pont=FauxPont(), contexte=FauxContexte(faux_systeme()), echeance_s=1.5))
    assert time.monotonic() - debut < 2.5
    assert par_id(d)["profil"]["etat"] == "inconnu" and "temps" in par_id(d)["profil"]["technique"]


def test_une_sonde_qui_plante_devient_inconnu(monkeypatch):
    class PontCasse(FauxPont):
        def infos_sujet(self, sujet):
            raise KeyError("graphe cassé")
    d = conforme(diagnostiquer("repetition", pont=PontCasse(), contexte=FauxContexte({})))
    assert par_id(d)["sujets"]["etat"] == "inconnu"


def test_arguments_hors_contrat():
    assert normaliser_mode("robot") == "reel" and normaliser_mode(None) == "reel"
    with pytest.raises(ValueError):
        diagnostiquer("simu", pont=FauxPont(), contexte=FauxContexte({}))
    with pytest.raises(ValueError):
        diagnostiquer("reel", pont=FauxPont(), contexte=FauxContexte({}), source="moi")


# ---------------------------------------------------------------- actions

def test_demarrer_les_services_liste_blanche_seulement():
    pont = FauxPont(arretes=("lidar_driver", "unitree_slam"), delai_demarrage_s=0.3)
    r = faire_action("demarrer-services", "repetition", pont=pont)
    assert r["ok"] is True and r["action"] == "demarrer-services"
    assert r["services"] == {"lidar_driver": 0, "unitree_slam": 0}
    assert pont.switchs() == [{"name": "lidar_driver", "switch": 1}, {"name": "unitree_slam", "switch": 1}]
    assert r["message"].startswith("Les services de cartographie ont démarré en ")
    assert r["message"].endswith(" s : le scan et le repérage peuvent marcher.")
    assert "lidar_driver" not in r["message"] and pont.robot_state.nombre_interdits == 0
    # déjà actifs : rien n'est envoyé
    r = faire_action("demarrer-services", "reel", pont=pont)
    assert r["ok"] is True and len(pont.switchs()) == 2
    assert r["message"] == "Les services de cartographie sont déjà actifs : rien n'a été envoyé."
    # un seul arrêté, ou un sous-ensemble demandé : seulement celui-là
    pont = FauxPont(arretes=("unitree_slam",), delai_demarrage_s=0.1)
    r = faire_action("demarrer-services", "reel", pont=pont)
    assert pont.switchs() == [{"name": "unitree_slam", "switch": 1}]
    assert r["message"].startswith("La cartographie d'Unitree a démarré en ")
    pont = FauxPont(arretes=("lidar_driver", "unitree_slam"), delai_demarrage_s=0.1)
    faire_action("demarrer-services", "reel", pont=pont, services=["unitree_slam"])
    assert pont.switchs() == [{"name": "unitree_slam", "switch": 1}]


def test_demarrer_les_services_refus_avant_tout_envoi():
    pont = FauxPont(arretes=("lidar_driver",))
    for services in (["ai_sport"], ["lidar_driver", "motion_switcher"], "lidar_driver", [1], {"lidar_driver": 1}):
        with pytest.raises(ServiceInterdit):
            faire_action("demarrer-services", "reel", pont=pont, services=services)
    assert pont.appels == []
    with pytest.raises(ActionImpossible):
        faire_action("demarrer-services", "simu", pont=pont)
    with pytest.raises(ActionInconnue):
        faire_action("arreter-services", "reel", pont=pont)
    assert pont.appels == [] and services_demandes([]) == []
    r = faire_action("demarrer-services", "reel", pont=pont, services=[])
    assert r["ok"] is True and pont.appels == []


def test_demarrer_les_services_robot_muet_lent_ou_qui_refuse():
    pont = FauxPont(arretes=("lidar_driver",), muet=True)
    r = faire_action("demarrer-services", "reel", pont=pont)
    assert r["ok"] is False and "Rien n'a été envoyé" in r["message"] and pont.switchs() == []
    pont = FauxPont(arretes=("lidar_driver",), delai_demarrage_s=60.0)
    horloge = [0.0]

    def avancer(dt):
        horloge[0] += dt
    r = A.demarrer_services(pont, None, delai=3.0, horloge=lambda: horloge[0], dormir=avancer)
    assert r["ok"] is False and "pas encore actif après 3 s" in r["message"]
    assert pont.switchs() == [{"name": "lidar_driver", "switch": 1}]       # envoyé une seule fois, puis relu
    pont = FauxPont(arretes=("lidar_driver",))
    pont.robot_state.protection["lidar_driver"] = True                     # le robot refuserait (protégé : 5)
    r = faire_action("demarrer-services", "reel", pont=pont)
    assert r["ok"] is False and "refusé" in r["message"] and "protégé" in r["message"]
    pont = FauxPont(actif=False)
    assert faire_action("demarrer-services", "reel", pont=pont)["ok"] is False


def test_actions_du_cable_notees_jamais_lancees(tmp_path):
    chemin = ecrire_faux(tmp_path / "f.json", faux_systeme())
    ctx = FauxContexte.depuis_fichier(chemin)
    r = faire_action("retablir-cable", "reel", contexte=ctx)
    assert r["ok"] is True and r["commande"] == "nmcli connection up robot-g1"
    r = faire_action("cable-automatique", "reel", contexte=ctx)
    assert r["ok"] is True and "Wi-Fi" in r["message"]
    assert [x["commande"] for x in lire_journal(chemin)] == [
        "nmcli connection up robot-g1", "nmcli connection modify robot-g1 connection.autoconnect yes"]
    donnees = faux_systeme()
    donnees["commandes"]["nmcli connection up robot-g1"] = {
        "code": 10, "erreur": "Error: unknown connection 'robot-g1'."}
    donnees["commandes"]["nmcli connection modify robot-g1 connection.autoconnect yes"] = {
        "code": 4, "erreur": "Error: Failed to modify connection 'robot-g1': Not authorized to modify this connection."}
    ctx = FauxContexte(donnees)
    assert "robot.sh" in faire_action("retablir-cable", "reel", contexte=ctx)["message"]
    r = faire_action("cable-automatique", "reel", contexte=ctx)
    assert r["ok"] is False and "nmcli connection modify robot-g1" in r["message"]
    r = faire_action("retablir-cable", "reel", contexte=ContexteEssais())
    assert r["ok"] is False and "essais" in r["message"]
    with pytest.raises(ActionImpossible):
        verifier_action("retablir-cable", "repetition")
    assert texte_action(r).startswith("Pas fait : ")


# ---------------------------------------------------------------- g1-diagnostic

def test_texte_du_terminal():
    d = juger(faits_robot(services={"code": 0, "services": [{"name": "lidar_driver", "status": 1, "protect": False},
                                                            {"name": "unitree_slam", "status": 0, "protect": False}]}))
    texte = texte_diagnostic(d)
    assert "Câble et réseau" in texte and "Robot" in texte and "Jetson" in texte
    assert "PROBLÈME" in texte and "→ Cliquez sur" in texte
    assert "  Ici : g1-diagnostic --action demarrer-services\n" in texte.replace("\u00a0", " ")     # copiable
    assert "\033[" not in texte and "\033[1;31m" in texte_diagnostic(d, couleur=True)
    assert all(len(ligne) <= 100 for ligne in texte.splitlines()), texte


def commande(*args, env=None, entree=None):
    environnement = dict(os.environ, **(env or {}))
    environnement["PYTHONPATH"] = str(atelier.RACINE)
    return subprocess.run([sys.executable, "-m", "atelier.diagnostic", *args], capture_output=True, text=True,
                          env=environnement, input=entree, timeout=60, cwd=str(atelier.RACINE))


def test_commande_aide_et_erreurs():
    r = commande("--help")
    assert r.returncode == 0 and "Vérifier le robot" in r.stdout and "--action" in r.stdout
    r = commande("--mode", "simu")
    assert r.returncode == 2 and "choix inconnu" in r.stderr


def test_commande_action_demande_oui(tmp_path):
    chemin = ecrire_faux(tmp_path / "f.json", faux_systeme())
    env = {"ATELIER_DIAGNOSTIC_FAUX": str(chemin)}
    r = commande("--action", "retablir-cable", env=env, entree="non\n")
    assert r.returncode == 1 and "Rien n'a été envoyé" in r.stdout and lire_journal(chemin) == []
    r = commande("--action", "retablir-cable", env=env, entree="oui\n")
    assert r.returncode == 0 and "Fait : Connexion" in r.stdout, r.stdout + r.stderr
    assert [x["commande"] for x in lire_journal(chemin)] == ["nmcli connection up robot-g1"]
    r = commande("--action", "retablir-cable", "--mode", "repetition", env=env, entree="oui\n")
    assert r.returncode == 1 and "répétition" in r.stderr
    sortie = io.StringIO()
    from atelier.diagnostic.__main__ import confirmer
    assert confirmer("demarrer-services", io.StringIO("Oui\n"), sortie) is True
    assert "Le robot ne bouge pas" in sortie.getvalue()
    assert confirmer("demarrer-services", io.StringIO(""), io.StringIO()) is False


def test_commande_json_sans_ros(tmp_path):
    """g1-diagnostic --json sans ROS 2 (variables de ROS retirées : rclpy introuvable) : le résultat est conforme,
    le code de sortie dit qu'il y a un problème, les vérifications système viennent du faux contexte."""
    chemin = ecrire_faux(tmp_path / "f.json", faux_systeme())
    env = {"ATELIER_DIAGNOSTIC_FAUX": str(chemin), "PYTHONNOUSERSITE": "1"}
    script = ("import sys, builtins\n"
              "vrai = builtins.__import__\n"
              "def sans_ros(nom, *a, **k):\n"
              "    if nom.split('.')[0] == 'rclpy':\n"
              "        raise ImportError('rclpy masqué pour le test')\n"
              "    return vrai(nom, *a, **k)\n"
              "builtins.__import__ = sans_ros\n"
              "from atelier.diagnostic.__main__ import main\n"
              "sys.exit(main(['--json']))\n")
    environnement = dict(os.environ, **env, PYTHONPATH=str(atelier.RACINE))
    r = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, env=environnement, timeout=60)
    assert r.returncode == 1, r.stderr
    d = conforme(json.loads(r.stdout))
    assert d["source"] == "g1-diagnostic" and d["faux"] is True
    assert par_id(d)["ros"]["etat"] == "probleme" and par_id(d)["ros"]["titre"] == "Réglages ROS de ce terminal"
    assert par_id(d)["cable"]["etat"] == "ok"


# ---------------------------------------------------------------- les copies du contrat dans la page

def test_copies_du_contrat_dans_le_module_de_la_page():
    """js/coque/diagnostic.js recopie les libellés et confirmations des actions et les titres des vérifications :
    les mêmes que atelier.lieu.diagnostic (lu par esprima, comme test_coque.py)."""
    pytest.importorskip("esprima", reason="pip install esprima dans .venv-projet")
    from .test_coque import _table
    js = atelier.RACINE / "atelier" / "web" / "js" / "coque" / "diagnostic.js"
    actions = _table(js, "ACTIONS_DIAGNOSTIC")
    assert {k: (v["libelle"], v["confirmation"]) for k, v in actions.items()} == {
        k: (v["libelle"], v["confirmation"]) for k, v in G.ACTIONS_DIAGNOSTIC.items()}
    assert all(v["ok"] and v["attente"] for v in actions.values())
    assert _table(js, "TITRES_IGNOREES") == {k: v[1] for k, v in VERIFICATIONS.items()}
    assert _table(js, "ETATS_VERIFICATION") == list(G.ETATS_VERIFICATION)
    assert dict(_table(js, "GROUPES_DIAGNOSTIC")) == G.GROUPES_DIAGNOSTIC
    css = (atelier.RACINE / "atelier" / "web" / "css" / "diagnostic.css").read_text(encoding="utf-8")
    assert "z-index: 4000" in css and "var(--h-barre-outils)" in css      # sous la barre d'outils : jamais sur l'ARRÊT


def test_noms_des_services_en_francais():
    """Corrections de la vague 6 (revue de l'interface, défaut 16) : « Démarrer lidar_driver et unitree_slam… » dans la
    confirmation et « lidar_driver et unitree_slam démarrés en 2 s » après l'action : le nom technique n'est plus écrit
    qu'une fois, dans le détail de la vérification."""
    from atelier.lieu.diagnostic import accord_services, majuscule, noms_services
    assert noms_services(["lidar_driver", "unitree_slam"]) == "le LiDAR et la cartographie d'Unitree"
    assert noms_services(["unitree_slam"], technique=True) == "la cartographie d'Unitree (unitree_slam)"
    assert noms_services(["voice"], technique=True) == "« voice »"
    groupes = (["lidar_driver"], ["unitree_slam"], ["lidar_driver", "unitree_slam"])
    assert [accord_services(n, "arrêté", "arrêtée", "arrêtés") for n in groupes] == ["arrêté", "arrêtée", "arrêtés"]
    assert majuscule("le LiDAR") == "Le LiDAR" and majuscule("") == ""
    assert "lidar_driver" not in G.ACTIONS_DIAGNOSTIC["demarrer-services"]["confirmation"]
    # un service qui ne démarre pas : le nom de l'appli Unitree, pour le chercher
    pont = FauxPont(arretes=("lidar_driver",), delai_demarrage_s=60.0)
    r = A.demarrer_services(pont, delai=0.3)
    assert r["ok"] is False and r["message"].startswith("Le LiDAR (lidar_driver) n'est pas encore actif après "), r
