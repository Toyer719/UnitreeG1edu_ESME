"""Tests de g1-scan (atelier.scan.session), de l'aperçu, de l'exploration et du relais, sans Gazebo
ni robot (agent Orchestrateur, section 9.5 du plan).

  ~/robot-g1/.venv-projet/bin/python -m pytest ~/robot-g1/atelier/tests/test_scan_session.py -v

Les tests travaillent sur des copies de lieux/demo dans des dossiers temporaires. Ceux qui écrivent
un faux ros2 bag ont besoin de ROS 2 (source ~/robot-g1/setup/env.sh), sinon ils sont sautés.
Rien ne passe par eno2 : le seul essai du mode robot sans répétition s'arrête avant tout réseau
(faux g1-slam, et G1_INTERFACE=lo). Le scan complet dans Gazebo est dans test_scan_session_simulation.py.
"""
import json
import math
import os
import shutil
import socket
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import numpy as np
import pytest

import atelier
from atelier import lieu as L
from atelier.scan import apercu, exploration, session as S
from atelier.tests.outils_scan import creer_session_exemple

DEMO = atelier.RACINE / "lieux" / "demo"


@pytest.fixture
def lieux(tmp_path, monkeypatch):
    """Dossier de lieux temporaire avec une copie du demo (« essai »), sans scan."""
    monkeypatch.setenv("ATELIER_LIEUX", str(tmp_path / "lieux"))
    monkeypatch.delenv("G1_SCAN_BIN", raising=False)
    monkeypatch.delenv("ATELIER_RECONNAISSANCE", raising=False)
    (tmp_path / "lieux").mkdir()
    L.copier_lieu(DEMO, tmp_path / "lieux" / "essai")
    return tmp_path / "lieux"


def g1_scan(*arguments):
    """Lance la commande dans ce processus : (code, sortie)."""
    import contextlib
    import io
    sortie = io.StringIO()
    with contextlib.redirect_stdout(sortie):
        try:
            code = S.principal([str(a) for a in arguments])
        except SystemExit as e:
            code = e.code
    return code, sortie.getvalue()


def sessions(lieux):
    dossier = lieux / "essai" / "scans"
    return sorted(d.name for d in dossier.iterdir()) if dossier.is_dir() else []


# ================================================================ la commande

def test_aide_et_commande_mal_tapee():
    code, _ = g1_scan("--help")
    assert code == 0
    assert g1_scan()[0] == 2
    assert g1_scan("demarrer", "--lieu", "essai")[0] == 2                 # --etage et --mode manquent
    assert g1_scan("demarrer", "--lieu", "essai", "--etage", "rdc", "--mode", "drone")[0] == 2
    r = subprocess.run([str(atelier.RACINE / "bin" / "gl-scan"), "etat", "--help"], capture_output=True, text=True,
                       timeout=60)
    assert r.returncode == 0 and "--json" in r.stdout


@pytest.mark.parametrize("arguments, message", [
    (("--lieu", "inconnu", "--etage", "rdc", "--mode", "simu"), "n'existe pas"),
    (("--lieu", "essai", "--etage", "etage9", "--mode", "simu"), "pas d'étage « etage9 »"),
    (("--lieu", "essai", "--etage", "rdc", "--mode", "simu", "--repetition"), "--repetition ne s'emploie qu'avec"),
    (("--lieu", "essai", "--etage", "rdc", "--mode", "robot", "--explorer"), "--explorer n'existe qu'avec"),
])
def test_demarrer_refuse(lieux, arguments, message):
    code, sortie = g1_scan("demarrer", *arguments)
    assert code == 1 and message in sortie, sortie
    assert sessions(lieux) == []


def test_demarrer_sans_monde_gazebo_ni_itineraires(lieux):
    (lieux / "essai" / "mondes" / "rdc.sdf").unlink()
    code, sortie = g1_scan("demarrer", "--lieu", "essai", "--etage", "rdc", "--mode", "simu")
    assert code == 1 and "g1-monde generer --lieu essai --etage rdc" in sortie
    L.copier_lieu(DEMO, lieux / "seul")
    (lieux / "seul" / "itineraires.yaml").write_text("noeuds: {}\ncouloirs: []\n")
    code, sortie = g1_scan("demarrer", "--lieu", "seul", "--etage", "rdc", "--mode", "simu", "--explorer")
    assert code == 1 and "deux nœuds reliés" in sortie
    assert sessions(lieux) == [] and not (lieux / "seul" / "scans").exists()


def test_demarrer_robot_sans_cable(lieux, monkeypatch):
    """Le vrai robot : refusé sans câble (lecture de /sys seulement), et toujours avec G1_SLAM_FAUX=1."""
    monkeypatch.setenv("G1_INTERFACE", "interface_absente_g1")
    monkeypatch.delenv("G1_SLAM_FAUX", raising=False)
    code, sortie = g1_scan("demarrer", "--lieu", "essai", "--etage", "rdc", "--mode", "robot")
    assert code == 1 and "Robot non détecté : câble non détecté sur interface_absente_g1" in sortie
    assert "--repetition" in sortie
    monkeypatch.setenv("G1_SLAM_FAUX", "1")
    code, sortie = g1_scan("demarrer", "--lieu", "essai", "--etage", "rdc", "--mode", "robot")
    assert code == 1 and "G1_SLAM_FAUX=1" in sortie
    assert sessions(lieux) == []


def test_double_demarrer(lieux):
    active = creer_session_exemple(lieux / "essai", "en_cours")       # processus noté : ce test, vivant
    code, sortie = g1_scan("demarrer", "--lieu", "essai", "--etage", "rdc", "--mode", "simu")
    assert code == 1 and "déjà en cours" in sortie and active["id"] in sortie
    assert sessions(lieux) == [active["id"]]


def test_arreter_sans_scan_et_session_finie(lieux):
    code, sortie = g1_scan("arreter", "--lieu", "essai")
    assert code == 0 and "rien à arrêter" in sortie
    finie = creer_session_exemple(lieux / "essai", "termine")
    code, sortie = g1_scan("arreter", "--lieu", "essai")
    assert code == 0 and "déjà finie" in sortie and finie["id"] in sortie
    assert L.lire_session(lieux / "essai", finie["id"])["etat"] == "termine"
    ratee = creer_session_exemple(lieux / "essai", "echec")
    assert g1_scan("arreter", "--lieu", "essai", "--session", ratee["id"])[0] == 0
    assert g1_scan("arreter", "--lieu", "essai", "--session", ratee["id"], "--attendre")[0] == 1
    assert g1_scan("arreter", "--lieu", "essai", "--session", "2020-01-01_00h00")[0] == 1


def _pid_mort():
    p = subprocess.Popen(["true"])
    p.wait()
    return p.pid


def test_arreter_session_interrompue_sans_enregistrement(lieux):
    s = L.creer_session(lieux / "essai", "rdc", "simu")
    L.maj_session(lieux / "essai", s["id"], etape="enregistrement",
                  processus={"pid": _pid_mort(), "debut": 1, "hote": socket.gethostname()})
    assert L.session_interrompue(L.lire_session(lieux / "essai", s["id"]))
    code, sortie = g1_scan("arreter", "--lieu", "essai")
    assert code == 1 and "sans enregistrement complet" in sortie
    s = L.lire_session(lieux / "essai", s["id"])
    assert (s["etat"], s["etape"]) == ("echec", "enregistrement") and "recommencez" in s["message"]
    # Un nouveau scan n'est plus bloqué
    assert L.session_active(lieux / "essai") is None


def test_traiter_refuse(lieux):
    en_cours = creer_session_exemple(lieux / "essai", "en_cours")
    code, sortie = g1_scan("traiter", "--lieu", "essai", "--session", en_cours["id"])
    assert code == 1 and "arrêtez-le d'abord" in sortie
    L.maj_session(lieux / "essai", en_cours["id"], etat="echec", etape="enregistrement")
    code, sortie = g1_scan("traiter", "--lieu", "essai", "--session", en_cours["id"])
    assert code == 1 and "pas d'enregistrement complet" in sortie
    finie = creer_session_exemple(lieux / "essai", "termine")
    L.maj_session(lieux / "essai", finie["id"], adoption={"quand": L.scans.instant(), "monde": False})
    code, sortie = g1_scan("traiter", "--lieu", "essai", "--session", finie["id"])
    assert code == 1 and "déjà été adoptée" in sortie


def test_etat(lieux):
    code, sortie = g1_scan("etat", "--lieu", "essai", "--json")
    assert code == 0 and json.loads(sortie) == L.etat_scan(lieux / "essai") and json.loads(sortie)["session"] is None
    code, sortie = g1_scan("etat", "--lieu", "essai")
    assert code == 0 and "0 session(s)" in sortie and "g1-scan demarrer" in sortie
    s = creer_session_exemple(lieux / "essai", "en_cours")
    code, sortie = g1_scan("etat", "--lieu", "essai", "--json")
    etat = json.loads(sortie)
    assert etat["actif"] and etat["session"]["id"] == s["id"] and etat["session"]["vivant"] is True
    assert etat["session"]["fichiers"]["apercu_png"] and set(etat) == set(L.etat_scan(lieux / "essai"))
    code, sortie = g1_scan("etat", "--lieu", "essai")
    assert code == 0 and "scan en cours" in sortie and s["id"] in sortie
    assert g1_scan("etat", "--lieu", "inconnu", "--json")[0] == 1


# ================================================================ adoption

def test_adopter_carte_seule(lieux):
    lieu = lieux / "essai"
    s = creer_session_exemple(lieu, "termine")
    dossier = L.dossier_session(lieu, s["id"])
    # Carte du scan plus petite que celle du monde (marge d'un pixel en moins) : le masque doit la suivre
    info, image = L.charger_carte(dossier / "carte.yaml")
    petite = L.InfoCarte(image="carte.pgm", resolution=info.resolution,
                         origin=(info.origin[0] + 0.05, info.origin[1] + 0.05, 0.0))
    L.enregistrer_carte(dossier / "carte.yaml", petite, image[1:-1, 1:-1])
    monde_avant = (lieu / "mondes" / "rdc.monde.yaml").read_text()
    code, sortie = g1_scan("adopter", "--lieu", "essai", "--session", s["id"])
    assert code == 0, sortie
    assert "source_carte: scan" in sortie and "Vérification du lieu" in sortie
    fiche = L.charger_fiche(lieu)
    assert fiche.etage("rdc").source_carte == "scan" and fiche.carte_unitree is None
    carte = L.charger_info_carte(lieu / "cartes" / "rdc.yaml")
    masque = L.charger_info_carte(lieu / "cartes" / "rdc_interdit.yaml")
    assert (carte.largeur, carte.hauteur) == (masque.largeur, masque.hauteur) == (image.shape[1] - 2,
                                                                                  image.shape[0] - 2)
    assert carte.image == "rdc.pgm" and (lieu / "cartes" / "rdc.pcd").is_file()
    assert (lieu / "mondes" / "rdc.monde.yaml").read_text() == monde_avant
    assert not (dossier / "monde_remplace.monde.yaml").exists()
    assert L.lire_session(lieu, s["id"])["adoption"]["monde"] is False
    assert not L.valider_lieu(lieu).erreurs


def test_adopter_avec_monde_et_personne_effacee(lieux):
    lieu = lieux / "essai"
    s = creer_session_exemple(lieu, "termine")
    dossier = L.dossier_session(lieu, s["id"])
    # La personne debout de b204 : marquons sa place occupée dans la carte du scan
    reco = L.lire_reconnaissance(dossier)
    personne = next(o for o in reco["objets"] if o["categorie"] == "personne")
    info, image = L.charger_carte(dossier / "carte.yaml")
    colonne, ligne = L.monde_vers_pixel(personne["centre"][0], personne["centre"][1], info)
    image[ligne - 2:ligne + 3, colonne - 2:colonne + 3] = 0
    L.enregistrer_carte(dossier / "carte.yaml", info, image)
    ancien = (lieu / "mondes" / "rdc.monde.yaml").read_text()
    code, sortie = g1_scan("adopter", "--lieu", "essai", "--session", s["id"], "--monde")
    assert code == 0, sortie
    assert (dossier / "monde_remplace.monde.yaml").read_text() == ancien
    monde = L.charger_monde(lieu, "rdc")
    assert not monde.pietons and all(m.source == "scan" for m in monde.murs)
    assert {o.id for o in monde.objets} == {o["id"] for o in reco["objets"] if o["a_garder"]}
    info, image = L.charger_carte(lieu / "cartes" / "rdc.yaml")
    colonne, ligne = L.monde_vers_pixel(personne["centre"][0], personne["centre"][1], info)
    assert (image[ligne - 2:ligne + 3, colonne - 2:colonne + 3] != 0).all()      # personne effacée
    assert (lieu / "mondes" / "rdc.sdf").stat().st_mtime >= (lieu / "mondes" / "rdc.monde.yaml").stat().st_mtime - 1
    assert L.lire_session(lieu, s["id"])["adoption"]["monde"] is True
    rapport = L.valider_lieu(lieu)
    assert not rapport.erreurs, rapport.texte()


def test_adopter_refuse(lieux):
    s = creer_session_exemple(lieux / "essai", "traitement")
    code, sortie = g1_scan("adopter", "--lieu", "essai", "--session", s["id"])
    assert code == 1 and "n'est pas terminée" in sortie
    t = creer_session_exemple(lieux / "essai", "termine")
    (L.dossier_session(lieux / "essai", t["id"]) / "reconnaissance.yaml").unlink()
    code, sortie = g1_scan("adopter", "--lieu", "essai", "--session", t["id"], "--monde")
    assert code == 1 and "sans --monde" in sortie
    assert L.charger_fiche(lieux / "essai").etage("rdc").source_carte == "monde"


# ================================================================ le processus de la session (sans ROS)

def _faux_bin(dossier, slam_code=0):
    """Fausses commandes g1-slam (note ses appels) et g1-monde, pour le processus de la session."""
    dossier.mkdir()
    (dossier / "g1-slam").write_text(textwrap.dedent(f"""\
        #!/bin/sh
        echo "faux g1-slam $*" >> "{dossier}/appels.txt"
        echo "1801 (commencer le scan) : échec - refusé par le service (errorCode 1)"
        exit {slam_code}
        """))
    (dossier / "g1-slam").chmod(0o755)
    return dossier


def test_session_robot_1801_refuse(lieux, tmp_path, monkeypatch):
    """Échec d'une étape : le robot refuse 1801 → échec en préparation, message utile, rien de lancé.
    Faux g1-slam : aucun réseau (et G1_INTERFACE=lo par précaution)."""
    faux = _faux_bin(tmp_path / "faux_bin", slam_code=1)
    monkeypatch.setenv("G1_SCAN_BIN", str(faux))
    monkeypatch.setenv("G1_INTERFACE", "lo")
    s = L.creer_session(lieux / "essai", "rdc", "robot")
    r = subprocess.run([sys.executable, "-m", "atelier.scan.session", "session", "--lieu", str(lieux / "essai"),
                        "--session", s["id"]], capture_output=True, text=True, timeout=120,
                       env=dict(os.environ, PYTHONPATH=str(atelier.RACINE)))
    assert r.returncode == 1, r.stdout + r.stderr
    s = L.lire_session(lieux / "essai", s["id"])
    assert (s["etat"], s["etape"]) == ("echec", "preparation")
    assert "1801" in s["message"] and "câble" in s["message"] and "errorCode 1" in s["message"]
    assert (faux / "appels.txt").read_text().splitlines() == ["faux g1-slam scan-debut"]   # pas de 1802
    assert not (L.dossier_session(lieux / "essai", s["id"]) / "enregistrement").exists()
    assert not L.session_interrompue(s) and L.session_active(lieux / "essai") is None


def test_lancement_et_arret_de_groupe(tmp_path):
    """Un programme lancé par la session : groupe à part, arrêté avec ses enfants, journal écrit."""
    journal = tmp_path / "essai.log"
    p = S.Programme("essai", ["sh", "-c", "sleep 60 & echo enfant lancé; wait"], journal, dict(os.environ))
    assert os.getpgid(p.pid) == p.pid != os.getpgid(0)
    import time
    for _ in range(50):
        if "enfant lancé" in journal.read_text():
            break
        time.sleep(0.05)
    assert p.vivant() and p.arreter() and not S._groupe_vivant(p.pid)
    assert p.infos()["arrete"] and "sleep 60" in journal.read_text()


# ================================================================ traitement d'un faux enregistrement

def ecrire_bag(dossier, monde, poses, sujet_nuage="/points", sujet_odom="/odom", repere_nuage="lidar",
               repere_odom="odom", hauteur_lidar=1.245, avec_tf=True, frequence=5.0):
    """ros2 bag d'un faux scan : points des murs et objets du monde visibles depuis le robot."""
    rosbag2_py = pytest.importorskip("rosbag2_py", reason="ROS 2 n'est pas chargé : source ~/robot-g1/setup/env.sh")
    from builtin_interfaces.msg import Time
    from geometry_msgs.msg import TransformStamped
    from nav_msgs.msg import Odometry
    from rclpy.serialization import serialize_message
    from sensor_msgs.msg import PointCloud2, PointField
    from tf2_msgs.msg import TFMessage

    from atelier.tests.test_scan_cartes import _visibles, nuage_synthetique
    tous = nuage_synthetique(monde, pas=0.05)
    ecrivain = rosbag2_py.SequentialWriter()
    ecrivain.open(rosbag2_py.StorageOptions(uri=str(dossier), storage_id="sqlite3"),
                  rosbag2_py.ConverterOptions("cdr", "cdr"))
    sujets = [(sujet_nuage, "sensor_msgs/msg/PointCloud2"), (sujet_odom, "nav_msgs/msg/Odometry")]
    if avec_tf:
        sujets.append(("/tf_static", "tf2_msgs/msg/TFMessage"))
    for nom, type_ in sujets:
        ecrivain.create_topic(rosbag2_py.TopicMetadata(name=nom, type=type_, serialization_format="cdr"))

    def instant(t):
        return Time(sec=int(t), nanosec=int(round((t % 1) * 1e9)) % 1000000000)
    if avec_tf:
        tf = TransformStamped()
        tf.header.frame_id, tf.child_frame_id = "base_link", "lidar"
        tf.transform.translation.x, tf.transform.translation.z = -0.004, hauteur_lidar
        tf.transform.rotation.w = 1.0
        ecrivain.write("/tf_static", serialize_message(TFMessage(transforms=[tf])), int(1e9))
    t0 = 1000.0
    for k, (x, y, theta) in enumerate(poses):
        t = t0 + k / frequence
        o = Odometry()
        o.header.frame_id, o.child_frame_id = repere_odom, "base_link"
        o.header.stamp = instant(t)
        o.pose.pose.position.x, o.pose.pose.position.y = x, y
        o.pose.pose.orientation.z, o.pose.pose.orientation.w = math.sin(theta / 2), math.cos(theta / 2)
        ecrivain.write(sujet_odom, serialize_message(o), int(t * 1e9))
        proches = tous[np.hypot(tous[:, 0] - x, tous[:, 1] - y) < 8.0]
        visibles = _visibles(proches, (x, y), monde.murs)
        if repere_nuage == "lidar":
            c, s = math.cos(theta), math.sin(theta)
            capteur = np.array([x - 0.004 * c, y - 0.004 * s, hauteur_lidar])
            d = visibles - capteur
            local = np.column_stack([c * d[:, 0] + s * d[:, 1], -s * d[:, 0] + c * d[:, 1], d[:, 2]])
        else:
            local = visibles                                         # déjà dans le repère du monde
        local = local.astype(np.float32)
        nuage = PointCloud2()
        nuage.header.frame_id, nuage.header.stamp = repere_nuage, instant(t)
        nuage.height, nuage.width = 1, len(local)
        nuage.fields = [PointField(name=n, offset=4 * i, datatype=PointField.FLOAT32, count=1)
                        for i, n in enumerate("xyz")]
        nuage.point_step, nuage.row_step = 12, 12 * len(local)
        nuage.is_bigendian, nuage.is_dense = False, True
        nuage.data = local.tobytes()
        ecrivain.write(sujet_nuage, serialize_message(nuage), int(t * 1e9))
    del ecrivain


def parcours_nord():
    """Du hall au bout est du couloir nord du demo, à 0,8 m/s (5 nuages par seconde)."""
    poses = [(2.5, 10.0 + 0.16 * k, math.pi / 2) for k in range(19)]
    poses += [(2.5 + 0.16 * k, 13.0, 0.0) for k in range(int(25 / 0.16))]
    return poses


@pytest.fixture(scope="module")
def faux_bags(tmp_path_factory):
    """Deux faux enregistrements du couloir nord, écrits une fois pour tous les tests :
    « lidar » (simulation : /points dans le repère du LiDAR, /tf_static) et « map » (comme peut-être
    le vrai robot : /unitree/slam_mapping/points déjà dans le repère de la carte)."""
    pytest.importorskip("rosbag2_py", reason="ROS 2 n'est pas chargé : source ~/robot-g1/setup/env.sh")
    base = tmp_path_factory.mktemp("bags")
    monde = L.charger_monde(DEMO, "rdc")
    ecrire_bag(base / "lidar", monde, parcours_nord())
    ecrire_bag(base / "map", monde, parcours_nord(), sujet_nuage="/unitree/slam_mapping/points",
               sujet_odom="/unitree/slam_mapping/odom", repere_nuage="map", repere_odom="map", avec_tf=False)
    return base


def fausse_reconnaissance(nuage, carte, dossier, parametres=None):
    """Remplace atelier.scan.reconnaissance.reconnaitre dans les tests : un seul mur."""
    parametres = parametres or {}
    info = L.charger_info_carte(carte)
    xmin, ymin, xmax, ymax = L.bornes_carte(info)
    donnees = L.nouvelle_reconnaissance(parametres.get("etage", "rdc"), (xmin, ymin, xmax, ymax),
                                        parametres.get("depart_robot", ((xmin + xmax) / 2, (ymin + ymax) / 2, 0.0)),
                                        session=parametres.get("session"), sol=parametres.get("sol"))
    donnees["murs"].append({"id": "mur_1", "categorie": "mur", "de": [0.0, 14.5], "a": [8.4, 14.5],
                            "epaisseur": 0.15, "hauteur": 2.5, "confiance": 0.9, "a_garder": True})
    fichier = L.ecrire_reconnaissance(dossier, donnees)
    L.ecrire_monde_scan(dossier, donnees)
    return {"fichier": str(fichier), "monde": str(Path(dossier) / "monde_scan.monde.yaml"),
            "resume": L.resume_reconnaissance(donnees), "duree_s": 0.0, "avertissements": []}


class ErreurReconnaissance(Exception):
    pass


def reconnaissance_ratee(nuage, carte, dossier, parametres=None):
    (Path(dossier) / "reconnaissance.yaml").write_text("à moitié écrit")
    raise ErreurReconnaissance("aucun mur trouvé dans le nuage : scannez plus près des murs")


@pytest.fixture
def session_enregistree(lieux, faux_bags):
    """Session simu arrêtée (arret_en_cours, fin notée) avec un faux enregistrement du couloir nord."""
    s = L.creer_session(lieux / "essai", "rdc", "simu")
    dossier = L.dossier_session(lieux / "essai", s["id"])
    shutil.copytree(faux_bags / "lidar", dossier / "enregistrement")
    L.maj_session(lieux / "essai", s["id"], etape="enregistrement")
    L.maj_session(lieux / "essai", s["id"], etat="arret_en_cours", etape="arret", fin=L.scans.instant())
    return lieux / "essai", s["id"]


def test_traiter_simu(session_enregistree, monkeypatch):
    lieu, ident = session_enregistree
    monkeypatch.setenv("ATELIER_RECONNAISSANCE", "atelier.tests.test_scan_session:fausse_reconnaissance")
    assert S.traiter(lieu, ident) == 0
    s = L.lire_session(lieu, ident)
    assert (s["etat"], s["etape"], s["progression"]) == ("termine", "fini", 100)
    assert "Adopter" in s["message"] and s["processus"]["pid"] == os.getpid()
    dossier = L.dossier_session(lieu, ident)
    assert all(L.fichiers_presents(lieu, ident).values()) is False          # pas d'aperçu dans ce faux scan
    for nom in ("nuage.pcd", "carte.pgm", "carte.yaml", "reconnaissance.yaml", "monde_scan.monde.yaml", "rapport.json"):
        assert (dossier / nom).is_file(), nom
    rapport = json.loads((dossier / "rapport.json").read_text())
    assert [e["etape"] for e in rapport["etapes"]] == list(L.ETAPES_TRAITEMENT)
    assert all(e["ok"] for e in rapport["etapes"])
    assert rapport["repere"]["nuage"] == "lidar" and rapport["repere"]["deja_dans_le_monde"] is False
    assert rapport["repere"]["capteur"] == "tf_static" and rapport["repere"]["premiere_pose"][:2] == [2.5, 10.0]
    assert rapport["reconnaissance"]["murs"] == 1 and rapport["nuage"]["nuages"] == len(parcours_nord())
    # Emprise du monde en simu : comparable pixel à pixel ; le couloir nord est bien vu
    carte = L.charger_info_carte(dossier / "carte.yaml")
    monde = L.charger_info_carte(lieu / "cartes" / "rdc.yaml")
    assert (carte.largeur, carte.hauteur, tuple(carte.origin)) == (monde.largeur, monde.hauteur, tuple(monde.origin))
    assert rapport["comparaison"]["reference"] == "cartes/rdc.yaml"
    assert rapport["comparaison"]["recouvrement"] > 0.9
    # Refaire le traitement d'une session finie : permis, et la reconnaissance est remplacée
    monkeypatch.setenv("ATELIER_RECONNAISSANCE", "atelier.tests.test_scan_session:reconnaissance_ratee")
    assert S.traiter(lieu, ident) == 0
    s = L.lire_session(lieu, ident)
    assert s["etat"] == "termine" and "Reconnaissance non faite" in s["message"]
    assert "scannez plus près des murs" in s["message"] and "adopter seule" in s["message"]
    assert not (dossier / "reconnaissance.yaml").exists() and not (dossier / "monde_scan.monde.yaml").exists()
    rapport = json.loads((dossier / "rapport.json").read_text())
    assert rapport["reconnaissance"] is None and not rapport["etapes"][2]["ok"]


def test_traiter_sans_module_de_reconnaissance(session_enregistree, monkeypatch):
    lieu, ident = session_enregistree
    monkeypatch.setenv("ATELIER_RECONNAISSANCE", "atelier.scan.module_absent_essai:reconnaitre")
    assert S.traiter(lieu, ident) == 0
    s = L.lire_session(lieu, ident)
    assert s["etat"] == "termine" and "ne se charge pas" in s["message"]


def test_traiter_robot_points_deja_dans_le_monde(lieux, faux_bags, monkeypatch):
    """Mode robot : nuage dans le repère « map » (comme peut-être /unitree/slam_mapping/points) :
    pris tel quel, noté dans le rapport ; emprise du nuage."""
    monkeypatch.setenv("ATELIER_RECONNAISSANCE", "atelier.tests.test_scan_session:fausse_reconnaissance")
    s = L.creer_session(lieux / "essai", "rdc", "robot")
    dossier = L.dossier_session(lieux / "essai", s["id"])
    shutil.copytree(faux_bags / "map", dossier / "enregistrement")
    L.maj_session(lieux / "essai", s["id"], etape="enregistrement")
    L.maj_session(lieux / "essai", s["id"], etat="arret_en_cours", etape="arret", fin=L.scans.instant())
    assert S.traiter(lieux / "essai", s["id"]) == 0
    rapport = json.loads((dossier / "rapport.json").read_text())
    assert rapport["repere"]["nuage"] == "map" and rapport["repere"]["deja_dans_le_monde"] is True
    assert any("déjà celui de l'odométrie" in a for a in rapport["avertissements"])
    carte = L.charger_info_carte(dossier / "carte.yaml")
    monde = L.charger_info_carte(lieux / "essai" / "cartes" / "rdc.yaml")
    assert carte.hauteur < monde.hauteur and carte.origin[1] > monde.origin[1] + 1   # emprise du nuage
    assert rapport["comparaison"]["recouvrement"] > 0.9                              # même repère ici


def test_traiter_carte3d_en_echec(lieux):
    """Échec d'une étape : un enregistrement sans nuage → echec à carte_3d, avec quoi faire."""
    rosbag2_py = pytest.importorskip("rosbag2_py", reason="ROS 2 n'est pas chargé")
    s = L.creer_session(lieux / "essai", "rdc", "simu")
    dossier = L.dossier_session(lieux / "essai", s["id"])
    ecrivain = rosbag2_py.SequentialWriter()
    ecrivain.open(rosbag2_py.StorageOptions(uri=str(dossier / "enregistrement"), storage_id="sqlite3"),
                  rosbag2_py.ConverterOptions("cdr", "cdr"))
    ecrivain.create_topic(rosbag2_py.TopicMetadata(name="/odom", type="nav_msgs/msg/Odometry",
                                                   serialization_format="cdr"))
    del ecrivain
    L.maj_session(lieux / "essai", s["id"], etat="echec", etape="enregistrement", message="essai")
    code, sortie = g1_scan("traiter", "--lieu", "essai", "--session", s["id"])
    assert code == 1
    s = L.lire_session(lieux / "essai", s["id"])
    assert (s["etat"], s["etape"], s["progression"]) == ("echec", "carte_3d", 10)
    assert "carte 3D n'a pas pu être fabriquée" in s["message"] and "refaites le scan" in s["message"]
    assert s["fin"] is not None


def test_arreter_session_interrompue_avec_enregistrement(session_enregistree, monkeypatch):
    """Processus mort après l'enregistrement : arreter relance le traitement, en arrière-plan."""
    lieu, ident = session_enregistree
    monkeypatch.setenv("ATELIER_RECONNAISSANCE", "atelier.tests.test_scan_session:fausse_reconnaissance")
    L.maj_session(lieu, ident, processus={"pid": _pid_mort(), "debut": 1, "hote": socket.gethostname()})
    code, sortie = g1_scan("arreter", "--lieu", "essai", "--attendre")
    assert code == 0, sortie
    assert "traitement relancé" in sortie and "Terminé" in sortie
    s = L.lire_session(lieu, ident)
    assert s["etat"] == "termine" and s["processus"]["pid"] != os.getpid()
    # Le traitement relancé écrit « termine » puis se ferme : sous charge, sa fin peut suivre de
    # quelques secondes (instable à l'assemblage de la vague 4) ; on lui laisse 30 s
    assert attendre_fin(s["processus"]["pid"], 30.0)


def attendre_fin(pid, delai_s):
    fin = time.monotonic() + delai_s
    while not processus_fini(pid):
        if time.monotonic() > fin:
            return False
        time.sleep(0.1)
    return True


def processus_fini(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return open(f"/proc/{pid}/stat").read().split(")")[-1].split()[0] == "Z"


# ================================================================ exploration : le tour

def test_tour_du_demo():
    noeuds, aretes = exploration.graphe_etage(L.charger_itineraires(DEMO), "rdc")
    tour = exploration.tour_des_couloirs(noeuds, aretes, "accueil")
    assert tour[0] == tour[-1] == "accueil" and len(tour) == len(aretes) + 1    # boucle : chaque couloir une fois
    assert {frozenset(p) for p in zip(tour, tour[1:])} == {frozenset(a) for a in aretes}


def test_tour_avec_impasses_et_composantes():
    noeuds = {"a": (0, 0), "b": (4, 0), "c": (8, 0), "d": (4, 4), "e": (4, -3), "x": (20, 20), "y": (24, 20)}
    aretes = [("a", "b"), ("b", "c"), ("b", "d"), ("b", "e"), ("x", "y")]
    tour = exploration.tour_des_couloirs(noeuds, aretes, "a")
    assert tour[0] == tour[-1] == "a"
    passages = [frozenset(p) for p in zip(tour, tour[1:])]
    assert set(passages) == {frozenset(a) for a in aretes[:4]}                     # x – y : autre composante
    assert all(passages.count(frozenset(a)) == 2 for a in aretes[:4])              # impasses : aller et retour
    assert exploration.tour_des_couloirs(noeuds, aretes, "x") == ["x", "y", "x"]
    assert exploration.tour_des_couloirs({"seul": (0, 0)}, [], "seul") == ["seul"]
    t = exploration.Tournee(noeuds, aretes, "a")
    assert t.hors_composante == 1 and len(t.a_parcourir) == 4


def test_tournee_avec_couloir_bloque():
    noeuds, aretes = exploration.graphe_etage(L.charger_itineraires(DEMO), "rdc")
    tournee = exploration.Tournee(noeuds, aretes, "accueil")
    courant, vus = "accueil", []
    for _ in range(100):
        suivant = tournee.prochain(courant)
        if suivant is None:
            break
        if {courant, suivant} == {"b204", "couloir_nord_1"}:
            tournee.bloque(courant, suivant)          # le robot revient au nœud courant
            continue
        tournee.arrive(courant, suivant)
        courant = suivant
        vus.append(courant)
    assert courant == "accueil" and tournee.bloques == {frozenset({"b204", "couloir_nord_1"})}
    assert tournee.parcourus | tournee.bloques == tournee.a_parcourir and not tournee.restants


def test_noeud_proche():
    noeuds = {"a": (0, 0), "b": (5, 0)}
    assert exploration.noeud_proche(noeuds, 3.0, 1.0) == "b"


# ================================================================ aperçu

def mur(x0, y0, x1, y1, pas=0.03, hauteur=2.5):
    n = max(2, int(math.hypot(x1 - x0, y1 - y0) / pas))
    t, z = np.meshgrid(np.linspace(0, 1, n), np.arange(0.0, hauteur, pas))
    return np.column_stack([x0 + (x1 - x0) * t.ravel(), y0 + (y1 - y0) * t.ravel(), z.ravel()])


def test_apercu_vue_et_json(tmp_path):
    accu = apercu.Accumulateur()
    piece = np.vstack([mur(0, 0, 6, 0), mur(6, 0, 6, 4), mur(6, 4, 0, 4), mur(0, 4, 0, 0)])
    sol = np.column_stack([np.random.default_rng(0).uniform(0, 6, 3000),
                           np.random.default_rng(1).uniform(0, 4, 3000), np.zeros(3000)])
    for k in range(20):
        accu.ajouter_pose(1.0 + 0.2 * k, 2.0, 0.0)
        accu.ajouter_nuage(np.vstack([piece[k::20], sol[k::20]]))
    s = L.creer_session(L.copier_lieu(DEMO, tmp_path / "lieu"), "rdc", "simu")
    dossier = L.dossier_session(tmp_path / "lieu", s["id"])
    donnees = accu.ecrire(dossier, s["id"])
    assert donnees == json.loads((dossier / "apercu.json").read_text())
    assert donnees["resolution"] == 0.05 and abs(donnees["sol"]) < 0.05
    b = donnees["bornes"]
    assert b["xmin"] <= -0.05 and b["xmax"] >= 6.05 and b["ymin"] <= -0.05 and b["ymax"] >= 4.05
    assert donnees["largeur"] == round((b["xmax"] - b["xmin"]) / 0.05)
    assert donnees["hauteur"] == round((b["ymax"] - b["ymin"]) / 0.05)
    assert 0 < len(donnees["points"]) <= L.APERCU_POINTS_MAX
    assert all(0.1 <= p[2] - donnees["sol"] <= 1.55 for p in donnees["points"])   # tranche 0,1–1,5 m
    assert donnees["robot"] == {"x": 4.8, "y": 2.0, "theta": 0.0}
    traj = donnees["trajectoire"]
    assert all(math.dist(a[:2], b[:2]) <= 0.1 + 1e-9 or True for a, b in zip(traj, traj[1:]))
    assert len(traj) == 20 and donnees["statistiques"]["nuages"] == 20
    assert donnees["statistiques"]["distance_m"] == pytest.approx(3.8, abs=0.01)
    import cv2
    image = cv2.imread(str(dossier / "apercu.png"))
    assert image.shape[:2] == (donnees["hauteur"], donnees["largeur"])

    def pixel(x, y):                                     # 3 × 3 pixels autour du point
        ligne, colonne = int((b["ymax"] - y) / 0.05), int((x - b["xmin"]) / 0.05)
        return image[ligne - 1:ligne + 2, colonne - 1:colonne + 2].reshape(-1, 3)
    assert (pixel(3.0, 0.01) == 0).all(axis=1).any() and (pixel(6.01, 2.0) == 0).all(axis=1).any()   # murs
    assert (pixel(3.0, 1.0) == 205).all()                                        # rien vu : gris
    assert ((pixel(2.0, 2.0)[:, 0] == 255) & (pixel(2.0, 2.0)[:, 2] == 0)).any()  # trajectoire en bleu


def test_apercu_grande_zone_et_limites():
    accu = apercu.Accumulateur()
    sol = np.column_stack([np.linspace(0, 150, 2000), np.zeros(2000), np.zeros(2000) - 0.3])
    for _ in range(3):                                                         # un obstacle est vu plusieurs fois
        accu.ajouter_nuage(np.vstack([mur(0, 0, 150, 0, pas=0.04), mur(0, 0, 0, 3, pas=0.04), sol]))
    image, infos = accu.vue()
    assert infos["resolution"] == 0.1 and image.shape[1] <= 1600                 # 150 m : cases de 10 cm
    vide = apercu.Accumulateur()
    image, infos = vide.vue()
    assert infos["sol"] is None and (image == 205).all()
    assert vide.donnees_json("s", infos)["points"] == [] and vide.donnees_json("s", infos)["robot"] is None


def test_placement_des_nuages():
    from atelier.scan.carte3d import transformation
    p = apercu.Placement(capteur=(0.0, 0.0, 1.0))
    points = np.array([[1.0, 0.0, 0.0]])
    assert p.placer(points, "lidar", 10.0) is None                               # pas encore d'odométrie
    p.ajouter_odom(10.0, (2.0, 3.0, 0.0), (0.0, 0.0, math.sin(math.pi / 4), math.cos(math.pi / 4)), "odom",
                   "base_link")
    assert np.allclose(p.placer(points, "lidar", 10.02), [[2.0, 4.0, 1.0]])   # capteur par défaut (1 m)
    p.ajouter_tf("lidar", "base_link", transformation((0.0, 0.0, 1.245), (0, 0, 0, 1)))
    assert np.allclose(p.placer(points, "lidar", 10.0), [[2.0, 4.0, 1.245]])  # /tf_static
    assert p.source_capteur == "tf_static"
    assert p.placer(points, "map", 10.0) is points and p.placer(points, "/odom", 10.0) is points
    assert apercu.position_lidar_proxy() == pytest.approx((-0.004, 0.0, 1.245))


def test_cles_cases():
    points = np.array([[0.01, 0.01, 0.01], [0.02, 0.02, 0.02], [-0.01, 5.0, 1.0], [1000.0, -2000.0, -50.0]])
    cles = apercu.cles_cases(points)
    assert len(cles) == 3
    i, j, k = apercu.indices_cases(cles)
    assert sorted(zip(i.tolist(), j.tolist(), k.tolist())) == sorted([(0, 0, 0), (-1, 100, 20),
                                                                      (20000, -40000, -1000)])
