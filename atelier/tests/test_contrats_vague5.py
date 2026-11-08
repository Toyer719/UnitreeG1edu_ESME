"""Tests des contrats de la vague 5 (agent Contrats, section 12 du plan).

  ~/robot-g1/.venv-projet/bin/python -m pytest ~/robot-g1/atelier/tests/test_contrats_vague5.py -v

Vérifie que :
  - les schémas nouveaux ou changés (nuage, etat_camera, etat_pont, personnes, monde, session_scan, camera)
    sont des schémas draft-07 valides, que leurs exemples sont conformes, qu'atelier.lieu et jsonschema
    rendent le même verdict sur des centaines de variantes, et que les règles refusent ce qu'elles doivent ;
  - les lieux et les mondes existants restent valides et s'enregistrent à l'identique ; carte_extrudee fait
    l'aller-retour, et verifier_lieu avertit quand son maillage manque ou date d'avant la carte ;
  - atelier.lieu.nuage écrit et relit un nuage d'affichage, et refuse un binaire tronqué ;
  - vitesse_effective suit ses cas de référence et ses règles sur des milliers de consignes ;
  - MODES_MARCHE a la même valeur dans atelier, g1_bridge et g1_jumeau, et le pont connaît pas_en_marche ;
  - les squelettes existent : routes enregistrées (jamais d'erreur 500), modules JS et leurs exports, feuilles
    reliées, nœud camera_usb ; le registre du ruban et les anciens hash ont leurs identifiants ; les jetons
    du thème ont des contrastes AA ;
  - la section 12 du plan est là, avec les critères 31 à 36 ; tout.sh en compte 36 ; aucun fichier de la
    table 12.8 n'a deux propriétaires.
"""
import ast
import copy
import fnmatch
import json
import math
import os
import random
import re
import struct
import time

import jsonschema
import numpy as np
import pytest
import yaml

import atelier
from atelier import lieu as L
from atelier.lieu import equipe as E
from atelier.lieu import pilotage as D
from atelier.lieu import robot as R
from atelier.lieu.validation import erreurs_schema
from atelier.tests.test_lieu_validation import MUTATIONS, _chemins, _muter

RACINE = atelier.RACINE
DOSSIER_SCHEMAS = RACINE / "atelier" / "lieu" / "schemas"
DEMO = RACINE / "lieux" / "demo"
WEB = RACINE / "atelier" / "web"
PLAN = RACINE / "docs" / "plan-atelier-multi-agents.md"
TOUT = RACINE / "tests_e2e" / "tout.sh"

NOUVEAUX = ("nuage", "etat_camera")
CHANGES = ("etat_pont", "personnes", "monde", "session_scan", "camera")

EXEMPLE_ETAT_CAMERA = {
    "version": 1, "source": "v4l2", "peripherique": "/dev/g1_camera", "ouverte": True, "largeur": 640,
    "hauteur": 360, "frequence_hz": 10.0, "ips_mesuree": 29.8, "images": 1790, "publiees": 600,
    "taille_moyenne_ko": 41.5, "exposition": "auto", "erreur": None}
EXEMPLE_PERSONNES_CAMERA = {
    "version": 1, "source": "camera", "temps": 812.4,
    "image": {"largeur": 640, "hauteur": 360, "numero": 1234, "sujet": "/camera_poitrine/image/compressed"},
    "personnes": [{"id": 3, "x": 1.5, "y": 0.2, "distance_m": 1.51, "angle_rad": 0.13, "confiance": 0.86,
                   "regarde_robot": True, "boite": [250.0, 40.0, 330.0, 350.0]}]}
EXEMPLE_SESSION_NUAGE = {
    "version": 1, "id": "2026-10-27_14h22", "lieu": "seance", "etage": "rdc",
    "nom": "Scan rdc du 27/10/2026 à 14h22", "mode": "robot", "repetition": False, "explorer": False,
    "debut": "2026-10-27T14:22:40+01:00", "fin": "2026-10-27T14:26:34+01:00", "maj": "2026-10-31T01:30:00+01:00",
    "etat": "traitement", "etape": "nuage", "progression": 80, "message": "Fabrication du nuage de la carte 3D…",
    "sujets": {"nuage": "/unitree/slam_mapping/points", "odom": "/unitree/slam_mapping/odom", "autres": ["/tf_static"]},
    "statistiques": {"duree_s": 234.0, "points": 2729631, "distance_m": 72.9, "nuages": 2327},
    "processus": None, "journal": None, "carte_unitree": "rdc_2026-10-27_14h22.pcd", "adoption": None}
SOL_DU_27_10 = [0.0009, -0.0101, -1.271]       # plan du sol mesuré sur le scan du 27/10 (0,58°)


def schema(nom):
    return json.loads((DOSSIER_SCHEMAS / f"{nom}.schema.json").read_text(encoding="utf-8"))


def erreurs_js(nom, donnees):
    return [e.message for e in jsonschema.Draft7Validator(schema(nom)).iter_errors(donnees)]


def modifie(exemple, changement):
    donnees = copy.deepcopy(exemple)
    changement(donnees)
    return donnees


def monde_du_demo():
    return yaml.safe_load((DEMO / "mondes" / "rdc.monde.yaml").read_text(encoding="utf-8"))


def exemples():
    """Un exemple conforme de chaque schéma nouveau ou changé."""
    camera = copy.deepcopy(E.exemple_equipe("camera"))
    camera["camera"]["exposition"] = {"mode": "manuelle", "temps_100us": 156, "gain": 4}
    camera["camera"]["publication"] = {"frequence_hz": 10, "largeur": 640, "qualite_jpeg": 70}
    camera["detection"].update(taille_personne_m=1.7, correction_distance=1.0)
    monde = monde_du_demo()
    monde["carte_extrudee"] = {"fichier": "rdc_carte.stl", "hauteur": 1.5}
    points = np.array([[0.0, 0.0, 0.0], [1.0, 2.0, 0.5], [-3.2, 4.4, 2.6]])
    return {
        "nuage": L.entete_nuage(points, 0.05, SOL_DU_27_10, "scan", session="2026-10-27_14h22", etage="rdc",
                                date="2026-10-31T01:20:00+01:00", mobiles_retires=12),
        "etat_camera": EXEMPLE_ETAT_CAMERA, "etat_pont": R.EXEMPLE_ETAT_PONT_V5,
        "personnes": EXEMPLE_PERSONNES_CAMERA, "monde": monde, "session_scan": EXEMPLE_SESSION_NUAGE,
        "camera": camera}


@pytest.fixture
def demo(tmp_path):
    return L.copier_lieu(DEMO, tmp_path / "demo")


# ---------------------------------------------------------------- schémas, exemples et règles

@pytest.mark.parametrize("nom", NOUVEAUX + CHANGES)
def test_schema_draft07_valide(nom):
    s = schema(nom)
    assert s["$schema"] == "http://json-schema.org/draft-07/schema#"
    jsonschema.Draft7Validator.check_schema(s)
    assert nom in L.TYPES_FICHIERS


def test_types_des_messages():
    assert "etat_camera" in L.TYPES_MESSAGES and "nuage" not in L.TYPES_MESSAGES
    assert L.ETATS_PONT[-1] == "pas_en_marche" and "pilotage" in L.ETATS_PONT
    assert tuple(schema("etat_pont")["properties"]["etat"]["enum"]) == L.ETATS_PONT
    assert sorted(L.PRIORITE_ETATS_PONT) == sorted(L.ETATS_PONT)
    p = L.PRIORITE_ETATS_PONT
    assert p.index("robot_muet") < p.index("pas_en_marche") < p.index("refus") < p.index("pilotage")
    assert tuple(schema("nuage")["properties"]["source"]["enum"]) == L.nuage.SOURCES_NUAGE
    assert schema("nuage")["properties"]["format"]["const"] == L.nuage.FORMAT_NUAGE


@pytest.mark.parametrize("nom", NOUVEAUX + CHANGES)
def test_exemples_conformes(nom):
    d = exemples()[nom]
    assert erreurs_js(nom, d) == []
    assert L.valider_donnees(nom, d) == []


def test_anciens_messages_et_fichiers_toujours_conformes():
    # EXEMPLE_ETAT_PONT a reçu les champs de la vague 5 (agent Robot) : un message d'avant, sans eux, reste conforme
    ancien = {k: v for k, v in L.EXEMPLE_ETAT_PONT.items() if k not in ("demande", "minimums", "mode_robot")}
    assert L.valider_message("etat_pont", ancien) == []
    assert L.valider_message("etat_pont", L.EXEMPLE_ETAT_PONT) == []
    assert L.valider_message("personnes", {"version": 1, "source": "lidar", "temps": 3.0, "personnes": []}) == []
    assert L.valider_donnees("camera", E.exemple_equipe("camera")) == []
    assert L.valider_donnees("monde", monde_du_demo()) == []


@pytest.mark.parametrize("nom", NOUVEAUX + CHANGES)
def test_meme_verdict_que_jsonschema(nom):
    """Sur des centaines de variantes des exemples, atelier.lieu et jsonschema sont d'accord."""
    exemple = exemples()[nom]
    validateur = jsonschema.Draft7Validator(schema(nom))
    cas = [(c, m) for c in _chemins(exemple) for m in MUTATIONS]
    random.Random(5).shuffle(cas)
    desaccords = []
    for chemin, mutation in cas[:500]:
        variante = _muter(exemple, chemin, mutation)
        nous = bool(erreurs_schema(nom, variante))
        eux = any(True for _ in validateur.iter_errors(variante))
        if nous != eux:
            desaccords.append((chemin, mutation, nous, eux))
    assert desaccords == []


REFUS_SCHEMA = {
    "nuage : format inconnu": ("nuage", lambda d: d.update(format="float64_xyz")),
    "nuage : repère odom": ("nuage", lambda d: d.update(repere="odom")),
    "nuage : points négatifs": ("nuage", lambda d: d.update(points=-1)),
    "nuage : grille nulle": ("nuage", lambda d: d.update(grille=0)),
    "nuage : source inconnue": ("nuage", lambda d: d.update(source="lidar")),
    "nuage : plan du sol à deux valeurs": ("nuage", lambda d: d["sol"].update(plan=[0.0, 1.0])),
    "nuage : date sans décalage": ("nuage", lambda d: d.update(date="2026-10-31T01:20:00")),
    "nuage : session mal formée": ("nuage", lambda d: d.update(session="../autre")),
    "nuage : borne inconnue": ("nuage", lambda d: d["bornes"].update(tmin=0.0)),
    "nuage : sans sol": ("nuage", lambda d: d.pop("sol")),
    "caméra : source inconnue": ("etat_camera", lambda d: d.update(source="usb")),
    "caméra : largeur négative": ("etat_camera", lambda d: d.update(largeur=-1)),
    "caméra : exposition inconnue": ("etat_camera", lambda d: d.update(exposition="nuit")),
    "caméra : sans erreur": ("etat_camera", lambda d: d.pop("erreur")),
    "pont : état inconnu": ("etat_pont", lambda d: d.update(etat="assis")),
    "pont : mode sans fsm": ("etat_pont", lambda d: d["mode_robot"].pop("fsm")),
    "pont : en_marche en texte": ("etat_pont", lambda d: d["mode_robot"].update(en_marche="non")),
    "pont : minimum négatif": ("etat_pont", lambda d: d["minimums"].update(vitesse_min_lin=-0.1)),
    "pont : minimums incomplets": ("etat_pont", lambda d: d["minimums"].pop("zone_morte_rot")),
    "pont : demande sans wz": ("etat_pont", lambda d: d["demande"].pop("wz")),
    "personnes : boite à trois valeurs": ("personnes", lambda d: d["personnes"][0].update(boite=[1, 2, 3])),
    "personnes : boite négative": ("personnes", lambda d: d["personnes"][0].update(boite=[-1, 2, 3, 4])),
    "personnes : image sans hauteur": ("personnes", lambda d: d["image"].pop("hauteur")),
    "personnes : image vide": ("personnes", lambda d: d["image"].update(largeur=0)),
    "monde : maillage dans un dossier": ("monde", lambda d: d["carte_extrudee"].update(fichier="../rdc_carte.stl")),
    "monde : maillage qui n'est pas un STL": ("monde", lambda d: d["carte_extrudee"].update(fichier="rdc_carte.obj")),
    "monde : maillage trop bas": ("monde", lambda d: d["carte_extrudee"].update(hauteur=0.1)),
    "monde : champ inconnu du maillage": ("monde", lambda d: d["carte_extrudee"].update(couleur="gris")),
    "monde : maillage sans hauteur": ("monde", lambda d: d["carte_extrudee"].pop("hauteur")),
    "session : étape inconnue": ("session_scan", lambda d: d.update(etape="reconnaitre")),
    "camera.yaml : exposition inconnue": ("camera", lambda d: d["camera"]["exposition"].update(mode="nuit")),
    "camera.yaml : qualité JPEG de 5": ("camera", lambda d: d["camera"]["publication"].update(qualite_jpeg=5)),
    "camera.yaml : correction de 3": ("camera", lambda d: d["detection"].update(correction_distance=3.0)),
    "camera.yaml : réglage de publication inconnu": ("camera", lambda d: d["camera"]["publication"].update(ips=30)),
}


@pytest.mark.parametrize("cas", list(REFUS_SCHEMA))
def test_schema_refuse(cas):
    nom, changement = REFUS_SCHEMA[cas]
    donnees = modifie(exemples()[nom], changement)
    assert erreurs_js(nom, donnees), f"jsonschema aurait dû refuser : {cas}"
    assert L.valider_donnees(nom, donnees), f"atelier.lieu aurait dû refuser : {cas}"


def _pret_avec_mode(d, fsm, nom, en_marche, age_s=0.4):
    d.update(etat="pret", mouvement_permis=True)
    d["mode_robot"].update(fsm=fsm, nom=nom, en_marche=en_marche, age_s=age_s)


REFUS_REGLES = {
    "pas_en_marche avec le mouvement permis": ("etat_pont", lambda d: d.update(mouvement_permis=True)),
    "pas_en_marche sans mode lu": ("etat_pont", lambda d: d.update(mode_robot=None)),
    "pas_en_marche alors que le robot marche": (
        "etat_pont", lambda d: d["mode_robot"].update(fsm=501, nom="marche", en_marche=True)),
    "robot assis mais pont prêt": ("etat_pont", lambda d: d.update(etat="pret", mouvement_permis=True)),
    "en_marche sans mode connu": ("etat_pont", lambda d: _pret_avec_mode(d, None, "inconnu", True)),
    "boite à l'envers": ("personnes", lambda d: d["personnes"][0].update(boite=[330.0, 40.0, 250.0, 350.0])),
    "boite plate": ("personnes", lambda d: d["personnes"][0].update(boite=[250.0, 40.0, 330.0, 40.0])),
    "boite hors de l'image": ("personnes", lambda d: d["personnes"][0].update(boite=[250.0, 40.0, 700.0, 350.0])),
    "nuage : bornes à l'envers": ("nuage", lambda d: d["bornes"].update(xmin=5.0, xmax=1.0)),
    "caméra : plus d'images publiées que lues": ("etat_camera", lambda d: d.update(publiees=d["images"] + 1)),
    "monde : mur nommé carte_du_scan": ("monde", lambda d: d["murs"][0].update(id="carte_du_scan")),
}


@pytest.mark.parametrize("cas", list(REFUS_REGLES))
def test_regles_refusent(cas):
    """Conformes au schéma, mais refusés par les règles d'atelier.lieu (validation.py)."""
    nom, changement = REFUS_REGLES[cas]
    donnees = modifie(exemples()[nom], changement)
    assert erreurs_js(nom, donnees) == [], cas
    assert L.valider_donnees(nom, donnees), f"atelier.lieu aurait dû refuser : {cas}"


ACCEPTES = {
    "verrou avant pas_en_marche": ("etat_pont", lambda d: d.update(etat="arret_verrouille", verrou=True)),
    "robot muet avant pas_en_marche": ("etat_pont", lambda d: d.update(etat="robot_muet")),
    "mode inconnu : rien de bloqué": ("etat_pont", lambda d: _pret_avec_mode(d, None, "inconnu", None, None)),
    "lecture du mode désactivée": (
        "etat_pont", lambda d: d.update(mode_robot=None, etat="pret", mouvement_permis=True)),
    "en marche en 501": ("etat_pont", lambda d: _pret_avec_mode(d, 501, "marche", True)),
    "boite sans taille d'image": ("personnes", lambda d: d.pop("image")),
    "nuage vide": ("nuage", lambda d: d.update(points=0)),
    "session : anciennes étapes": ("session_scan", lambda d: d.update(etape="reconnaissance")),
}


@pytest.mark.parametrize("cas", list(ACCEPTES))
def test_regles_acceptent(cas):
    nom, changement = ACCEPTES[cas]
    donnees = modifie(exemples()[nom], changement)
    assert erreurs_js(nom, donnees) == [] and L.valider_donnees(nom, donnees) == [], cas


# ---------------------------------------------------------------- lieux, mondes et carte extrudée

def test_lieux_et_mondes_existants_valides_et_inchanges(demo):
    rapport = L.valider_lieu(DEMO)
    assert rapport.erreurs == [] and rapport.avertissements == []
    avant = (demo / "mondes" / "rdc.monde.yaml").read_text(encoding="utf-8")
    L.enregistrer_monde(demo, "rdc", L.charger_monde(demo, "rdc"))
    apres = (demo / "mondes" / "rdc.monde.yaml").read_text(encoding="utf-8")
    assert "carte_extrudee" not in apres and yaml.safe_load(apres) == yaml.safe_load(avant)
    assert L.charger_monde(demo, "rdc").carte_extrudee is None
    for lieu in ("demo", "demo_scan", "bomboclat"):
        for fichier in sorted((RACINE / "lieux" / lieu / "mondes").glob("*.monde.yaml")):
            donnees = yaml.safe_load(fichier.read_text(encoding="utf-8"))
            assert L.valider_donnees("monde", donnees, fichier.name) == [], fichier


def test_carte_extrudee_aller_retour_et_verification(demo):
    monde = L.charger_monde(demo, "rdc")
    monde.carte_extrudee = L.CarteExtrudee("rdc_carte.stl")
    L.enregistrer_monde(demo, "rdc", monde)
    texte = (demo / "mondes" / "rdc.monde.yaml").read_text(encoding="utf-8")
    assert yaml.safe_load(texte)["carte_extrudee"] == {"fichier": "rdc_carte.stl", "hauteur": L.HAUTEUR_CARTE_EXTRUDEE}
    assert L.charger_monde(demo, "rdc") == monde
    stl = L.chemin_maillage(demo, "rdc")
    assert stl == demo / "mondes" / "rdc_carte.stl" and L.MODELE_CARTE_EXTRUDEE == "carte_du_scan"

    def alertes():
        return [m for m in L.valider_lieu(demo).avertissements if "carte_extrudee" in m]
    assert any("absent" in m for m in alertes())
    stl.write_bytes(bytes(84))
    maintenant = time.time()
    os.utime(stl, (maintenant + 10, maintenant + 10))
    assert alertes() == []
    carte = L.chemin_carte(demo, "rdc")
    os.utime(stl, (carte.stat().st_mtime - 100, carte.stat().st_mtime - 100))
    assert any("plus ancien" in m for m in alertes())


# ---------------------------------------------------------------- nuage d'affichage

def test_nuage_ecrit_et_relu(demo):
    rng = np.random.default_rng(5)
    points = rng.uniform([-6.5, -16.0, 0.0], [24.0, 3.2, 2.9], (1000, 3))
    entete = L.entete_nuage(points, 0.05, SOL_DU_27_10, "scan", session="2026-10-27_14h22", etage="rdc",
                            mobiles_retires=12)
    assert L.valider_entete_nuage(entete) == []
    assert entete["points"] == 1000 and entete["repere"] == "map" and entete["format"] == "float32_xyz"
    assert 0.5 < entete["sol"]["inclinaison_deg"] < 0.7
    b = entete["bornes"]
    for i, axe in enumerate("xyz"):
        assert b[f"{axe}min"] <= points[:, i].astype(np.float32).min() and b[f"{axe}max"] >= points[:, i].max()
    base = L.chemin_nuage(demo, "rdc")
    assert base == demo / "cartes" / "rdc.nuage"
    L.ecrire_nuage(base, points, entete)
    binaire, texte = L.fichiers_nuage(base)
    assert (binaire.name, texte.name) == ("rdc.nuage.bin", "rdc.nuage.json")
    assert binaire.stat().st_size == 12 * 1000
    assert struct.unpack("<3f", binaire.read_bytes()[:12]) == tuple(float(v) for v in points[0].astype(np.float32))
    relus, relu = L.lire_nuage(base)
    assert relus.dtype == np.float32 and relus.shape == (1000, 3) and np.allclose(relus, points.astype(np.float32))
    assert relu == json.loads(texte.read_text(encoding="utf-8")) == entete
    h = L.entetes_http_nuage(entete)
    assert h["X-Nuage-Points"] == "1000" and h["X-Nuage-Source"] == "scan"
    assert h["X-Nuage-Session"] == "2026-10-27_14h22"
    assert len(h["X-Nuage-Bornes"].split(",")) == 6 and float(h["X-Nuage-Grille"]) == 0.05
    with pytest.raises(L.ErreurLieu):
        L.ecrire_nuage(base, points[:10], entete)        # l'en-tête annonce 1000 points
    binaire.write_bytes(binaire.read_bytes()[:-12])
    with pytest.raises(L.ErreurLieu) as e:
        L.lire_entete_nuage(base)
    assert "octets" in " ".join(e.value.erreurs)


def test_nuage_vide_chemins_et_refus(demo, tmp_path):
    vide = L.entete_nuage(np.zeros((0, 3)), 0.1, [0.0, 0.0, 0.0], "apercu")
    assert vide["points"] == 0 and set(vide["bornes"].values()) == {0.0} and L.valider_entete_nuage(vide) == []
    L.ecrire_nuage(tmp_path / "apercu_nuage", [], vide)
    assert (tmp_path / "apercu_nuage.bin").stat().st_size == 0
    assert L.chemin_nuage(demo, "rdc", "unitree").name == "rdc_unitree.nuage"
    assert L.chemin_nuage_session(tmp_path).name == "nuage_affichage"
    assert L.chemin_nuage_session(tmp_path, apercu=True).name == "apercu_nuage"
    with pytest.raises(ValueError):
        L.chemin_nuage(demo, "rdc", "apercu")
    with pytest.raises(ValueError):
        L.entete_nuage([[0.0, 0.0, float("nan")]], 0.05, [0, 0, 0], "scan")
    with pytest.raises(ValueError):
        L.entete_nuage([[0.0, 0.0]], 0.05, [0, 0, 0], "scan")
    with pytest.raises(L.ErreurLieu):
        L.lire_entete_nuage(tmp_path / "absent")


# ---------------------------------------------------------------- robot : vitesse minimale et modes

@pytest.mark.parametrize("entree, attendu, plafonds", R.EXEMPLES_VITESSE_MIN)
def test_vitesse_effective_cas_de_reference(entree, attendu, plafonds):
    assert all(abs(a - b) < 2e-6 for a, b in zip(R.vitesse_effective(*entree, plafonds=plafonds), attendu))


def test_vitesse_effective_regles_au_hasard():
    rng = random.Random(12)
    smin, wmin = R.VITESSES_MIN_PONT["lin"], R.VITESSES_MIN_PONT["rot"]
    zl, zr = R.ZONES_MORTES_PONT["lin"], R.ZONES_MORTES_PONT["rot"]
    for _ in range(4000):
        plafonds = rng.choice([None, R.PLAFONDS_VITESSE_MAX_0_2])
        p = plafonds or R.LIMITES_PONT
        petit = rng.random() < 0.6           # surtout des consignes petites, là où la règle agit
        e = [rng.uniform(-1, 1) * (0.25 if petit else p[a]) for a in ("vx", "vy", "wz")]
        e = [max(-p[a], min(p[a], v)) for a, v in zip(("vx", "vy", "wz"), e)]
        s = R.vitesse_effective(*e, plafonds=plafonds)
        assert all(abs(v) <= p[a] + 1e-9 for a, v in zip(("vx", "vy", "wz"), s)), (e, s)
        n_e, a_e = math.hypot(e[0], e[1]), abs(e[2])
        n_s, a_s = math.hypot(s[0], s[1]), abs(s[2])
        if n_e >= smin or a_e >= wmin:
            assert s == tuple(e)                              # marche franche : telle quelle
        elif s == (0.0, 0.0, 0.0):
            assert n_e < zl and a_e < zr                      # arrêt : tout était sous les zones mortes
        else:
            au_plafond = any(abs(abs(v) - p[a]) < 1e-9 for a, v in zip(("vx", "vy"), s[:2]))
            assert n_s >= smin - 1e-9 or a_s >= min(wmin, p["wz"]) - 1e-9 or au_plafond, (e, s)
            if n_s > 0:                                       # direction gardée
                assert abs(e[0] * s[1] - e[1] * s[0]) < 1e-9 and e[0] * s[0] + e[1] * s[1] > 0
    zero = {"lin": 0.0, "rot": 0.0}
    for _ in range(500):
        e = tuple(rng.uniform(-0.3, 0.3) for _ in range(3))
        assert R.vitesse_effective(*e, minimums=zero, zones=zero) == e     # tout désactivé : rien ne change
    assert R.vitesse_effective(float("nan"), 0.1, 0.0) == (0.0, 0.0, 0.0)
    assert R.vitesse_effective(0.1, float("inf"), 0.0) == (0.0, 0.0, 0.0)


def test_valeurs_du_pont_de_la_vague_5():
    assert R.VITESSES_MIN_PONT == {"lin": 0.2, "rot": 0.3} and R.ZONES_MORTES_PONT == {"lin": 0.05, "rot": 0.1}
    assert R.VITESSE_MAX_MIN == 0.2 and "0,2 m/s" in R.MESSAGE_VITESSE_MAX_BASSE
    assert R.VITESSES_MIN_PONT["lin"] <= R.VITESSE_MIN_LIN_MAX and R.VITESSES_MIN_PONT["rot"] <= R.VITESSE_MIN_ROT_MAX
    for axe in ("lin", "rot"):
        assert R.ZONES_MORTES_PONT[axe] <= R.VITESSES_MIN_PONT[axe]
    assert R.VITESSES_MIN_PONT["lin"] <= R.LIMITES_PONT["vx"] and R.VITESSES_MIN_PONT["rot"] <= R.LIMITES_PONT["wz"]
    assert R.API_SPORT_GET_FSM_ID == D.API_SPORT["get_fsm_id"] == 7001
    assert R.PERIODE_LECTURE_MODE_S == 1.0 and R.DELAI_MODE_PERIME_S == 3.0
    m = R.EXEMPLE_ETAT_PONT_V5["minimums"]
    assert m == {"vitesse_min_lin": 0.2, "vitesse_min_rot": 0.3, "zone_morte_lin": 0.05, "zone_morte_rot": 0.1}


def test_modes_et_messages():
    assert D.MODES_MARCHE == (500, 501, 801) and D.MODES_COURSE == (802,)
    assert not set(D.MODES_MARCHE) & set(D.MODES_COURSE)
    assert all(f in D.NOMS_MODES for f in D.MODES_MARCHE + D.MODES_COURSE + (0, 1, 3))
    assert D.nom_mode(501) == "marche" and D.nom_mode(3) == "assis" and D.nom_mode(802) == "course"
    assert D.nom_mode(550604) == "danse 604" and D.nom_mode(None) == "inconnu" and "inconnu" in D.nom_mode(9999)
    course = D.message_pas_en_marche(802)
    assert "mode course" in course and "passez en marche normale à la télécommande" in course
    assert "robot est assis" in D.message_pas_en_marche(3)
    for fsm in (0, 1):
        assert "n'est pas démarré" in D.message_pas_en_marche(fsm)
    autre = D.message_pas_en_marche(706)
    assert "mode 706" in autre and "télécommande" in autre and "Démarrer" in autre
    v5 = R.EXEMPLE_ETAT_PONT_V5
    assert v5["message"] == D.message_pas_en_marche(3) and v5["mode_robot"]["nom"] == D.nom_mode(3)
    assert v5["mode_robot"]["modes_marche"] == list(D.MODES_MARCHE)


def _constante(chemin, nom):
    """Valeur d'une constante écrite au premier niveau d'un fichier Python (sans l'importer)."""
    for noeud in ast.parse(chemin.read_text(encoding="utf-8")).body:
        if isinstance(noeud, ast.Assign) and any(isinstance(c, ast.Name) and c.id == nom for c in noeud.targets):
            return ast.literal_eval(noeud.value)
    raise AssertionError(f"{nom} absent de {chemin}")


def test_copies_de_modes_marche_identiques():
    """Le pont et le faux G1 tournent sans atelier : leurs copies doivent rester exactement celles du contrat."""
    pont = RACINE / "ws" / "src" / "g1_bridge" / "g1_bridge" / "logique.py"
    jumeau = RACINE / "ws" / "src" / "g1_jumeau" / "g1_jumeau" / "robot.py"
    assert _constante(pont, "MODES_MARCHE") == D.MODES_MARCHE
    assert _constante(jumeau, "MODES_MARCHE") == D.MODES_MARCHE
    assert set(_constante(pont, "ETATS")) == set(L.ETATS_PONT)


# ---------------------------------------------------------------- caméra

def test_sujets_de_la_camera():
    for sujet, (type_ros, qui) in E.SUJETS_IMAGES.items():
        assert sujet.startswith("/") and sujet.endswith("/compressed") and type_ros == "sensor_msgs/CompressedImage"
        assert qui
    assert E.SUJET_IMAGE_POITRINE == "/camera_poitrine/image/compressed" and E.SUJET_IMAGE_POITRINE in E.SUJETS_IMAGES
    assert E.SUJETS_EQUIPE[E.SUJET_ETAT_CAMERA][:2] == ("std_msgs/String", "etat_camera")
    assert not set(E.SUJETS_IMAGES) & set(E.SUJETS_EQUIPE)
    assert E.CAMERA_CONTENEUR == "/dev/g1_camera"
    assert L.valider_message("etat_camera", EXEMPLE_ETAT_CAMERA) == []
    assert L.valider_message("personnes", EXEMPLE_PERSONNES_CAMERA) == []


def test_noeud_camera_usb_declare():
    equipe = RACINE / "ws" / "src" / "g1_equipe"
    assert "camera_usb = g1_equipe.camera_usb:main" in (equipe / "setup.py").read_text(encoding="utf-8")
    assert (equipe / "g1_equipe" / "camera_usb.py").is_file()


# ---------------------------------------------------------------- serveur

ROUTES_V5 = {
    ("POST", "/api/arret"), ("POST", "/api/arret/debloquer"), ("GET", "/api/arret"), ("GET", "/api/robot/liaison"),
    ("GET", "/api/lieux/{id_lieu}/etages/{etage}/nuage"), ("GET", "/api/lieux/{id_lieu}/etages/{etage}/nuage/info"),
    ("GET", "/api/lieux/{id_lieu}/etages/{etage}/monde/maillage"), ("GET", "/api/scan/nuage"),
    ("GET", "/api/scan/nuage/info"), ("GET", "/api/camera/image"), ("GET", "/api/camera/flux"),
    ("GET", "/api/camera/etat")}


def test_routes_de_la_vague_5_enregistrees():
    from atelier.serveur import main
    texte = (RACINE / "atelier" / "serveur" / "main.py").read_text(encoding="utf-8")
    for route in ("arret", "liaison", "nuage", "camera"):
        assert (RACINE / "atelier" / "serveur" / "routes" / f"{route}.py").is_file() and route in texte
    chemins = main.creer_app(ros=False).openapi()["paths"]      # toutes les routes, routeurs inclus
    vues = {(methode.upper(), chemin) for chemin, methodes in chemins.items() for methode in methodes}
    assert ROUTES_V5 <= vues, ROUTES_V5 - vues


def test_routes_de_la_vague_5_jamais_d_erreur_500(tmp_path, monkeypatch):
    """Squelettes (501) ou routes écrites : une réponse claire, jamais 500 (le flux MJPEG n'est pas appelé ici)."""
    from fastapi.testclient import TestClient
    from atelier.serveur.communs import pas_encore_fait
    from atelier.serveur.main import creer_app
    e = pas_encore_fait("un essai", "Contrats", "12.4")
    assert e.statut == 501 and e.detail.startswith("Pas encore fait : un essai")
    monkeypatch.setenv("ATELIER_LIEUX", str(tmp_path))
    monkeypatch.setenv("ATELIER_INTERFACE_ROBOT", "interface_absente_v5")
    L.copier_lieu(DEMO, tmp_path / "demo")
    with TestClient(creer_app(ros=False)) as client:
        reponses = [client.get("/api/arret"), client.get("/api/robot/liaison"),
                    client.get("/api/lieux/demo/etages/rdc/nuage"), client.get("/api/lieux/demo/etages/rdc/nuage/info"),
                    client.get("/api/lieux/demo/etages/rdc/monde/maillage"), client.get("/api/scan/nuage?lieu=demo"),
                    client.get("/api/scan/nuage/info?lieu=demo"), client.get("/api/camera/image"),
                    client.get("/api/camera/etat"), client.post("/api/arret", json={"mode": "simu"}),
                    client.post("/api/arret/debloquer")]
    for r in reponses:
        assert r.status_code < 500 or r.status_code in (501, 503), (r.request.url, r.status_code, r.text[:300])
        if r.status_code >= 400:
            assert r.json()["detail"], r.request.url


# ---------------------------------------------------------------- interface web

EXPORTS = {
    "coque/coque.js": {"MODES", "CLES_MEMOIRE", "demarrerCoque", "ouvrirEspace", "retourAccueil", "modeCourant",
                       "ouvrirCommande"},
    "coque/accueil.js": {"afficherAccueil"},
    "coque/ruban.js": {"ONGLETS_RUBAN", "COMMANDES", "commandesDe", "construireRuban"},
    "coque/arbre.js": {"construireArbre"},
    "coque/panneau.js": {"ouvrirPanneau"},
    "coque/barre_etat.js": {"construireBarreEtat"},
    "coque/arret.js": {"monterArret"},
    "coque/confirmation.js": {"demanderConfirmation"},
    "coque/anciens_hash.js": {"ANCIENS_HASH", "destinationDuHash"},
    "carte3d/carte3d.js": {"creerCarte3D", "VUES", "CALQUES", "OUTILS", "HAUTEUR_COUPE", "FOND"},
    "camera/flux.js": {"creerVueCamera"},
}
METHODES_CARTE3D = ("chargerNuage", "afficherPoints", "afficherMonde", "afficherCarte2D", "afficherSalles",
                    "afficherItineraires", "afficherZones", "afficherRobot", "afficherPietons", "afficherTrajet", "vue",
                    "recadrer", "centrerSur", "calque", "coupe", "outil", "choisir", "surSelection", "surPose",
                    "surPointeur", "versEcran", "versSol", "redimensionner", "etat", "detruire")
COMMANDES_DU_CONTRAT = (
    "monde.choisir", "monde.mur", "monde.passage", "monde.objet", "monde.pieton", "monde.depart", "carte.refaire",
    "salles.salle", "salles.accueil", "itineraires.noeud", "itineraires.relier", "zones.interdite", "zones.lente",
    "simulation.lancer", "simulation.arreter", "simulation.y-aller", "simulation.accompagner", "simulation.retour",
    "simulation.faux-visiteur", "simulation.passants", "simulation.reglages-guide", "scan.simule", "scan.scan",
    "scan.fin", "scan.utiliser", "navigation.lancer", "navigation.reperer", "navigation.y-aller",
    "navigation.bloquer", "navigation.debloquer", "navigation.arreter", "pilotage.main", "pilotage.postures",
    "pilotage.gestes", "pilotage.voix", "pilotage.led", "pilotage.joysticks", "pilotage.danses",
    "pilotage.choregraphies", "pilotage.portique", "pilotage.volume", "personnalites.ouvrir", "dialogues.ouvrir",
    "camera.ouvrir")
ONGLETS = {"simu": ("dessiner", "placer", "simuler", "equipe"),
           "reel": ("scanner", "placer", "naviguer", "piloter", "equipe")}
ANCIENS = ("lieux", "monde", "carte", "salles", "itineraires", "zones", "simulation", "scan", "pilotage",
           "personnalites", "dialogues", "camera")


def _exports(chemin):
    esprima = pytest.importorskip("esprima", reason="pip install esprima dans .venv-projet")
    noms = set()
    for n in esprima.parseModule(chemin.read_text(encoding="utf-8")).body:
        if n.type == "ExportNamedDeclaration":
            d = n.declaration
            if d is not None and d.type == "VariableDeclaration":
                noms.update(x.id.name for x in d.declarations)
            elif d is not None:
                noms.add(d.id.name)
            noms.update(s.exported.name for s in (n.specifiers or []))
    return noms


@pytest.mark.parametrize("module", sorted(EXPORTS))
def test_modules_et_exports(module):
    chemin = WEB / "js" / module
    assert chemin.is_file()
    assert EXPORTS[module] <= _exports(chemin), EXPORTS[module] - _exports(chemin)


def test_carte3d_api_et_registre_du_ruban():
    carte3d = "\n".join(p.read_text(encoding="utf-8") for p in sorted((WEB / "js" / "carte3d").glob("*.js")))
    assert [m for m in METHODES_CARTE3D if not re.search(rf"\b{m}\b", carte3d)] == []
    ruban = (WEB / "js" / "coque" / "ruban.js").read_text(encoding="utf-8")
    assert [c for c in COMMANDES_DU_CONTRAT if f"'{c}'" not in ruban] == []
    for mode, onglets in ONGLETS.items():
        assert all(f"'{o}'" in ruban for o in onglets), mode
    assert len(ONGLETS["simu"]) == 4 and len(ONGLETS["reel"]) == 5
    anciens = (WEB / "js" / "coque" / "anciens_hash.js").read_text(encoding="utf-8")
    assert [h for h in ANCIENS if not re.search(rf"\b{h}:", anciens)] == []
    commande = re.findall(r"commande: '([a-z0-9.-]+)'", anciens)
    assert commande and set(commande) <= set(COMMANDES_DU_CONTRAT)
    coque = (WEB / "js" / "coque" / "coque.js").read_text(encoding="utf-8")
    for cle in ("atelier.mode", "atelier.repetition", "atelier.theme", "atelier.mode-simulation", "atelier.scan.mode"):
        assert f"'{cle}" in coque, cle


def test_feuilles_reliees():
    index = (WEB / "index.html").read_text(encoding="utf-8")
    feuilles = re.findall(r'href="(css/[^"]+)"', index)
    assert feuilles[0] == "css/theme.css" and feuilles.index("css/theme.css") < feuilles.index("css/atelier.css")
    for css in ("theme", "atelier", "carte3d", "camera"):
        assert f"css/{css}.css" in feuilles and (WEB / "css" / f"{css}.css").is_file()


def _jetons(texte):
    """Jetons de couleur de chaque bloc de theme.css : {sélecteur: {nom: #rrggbb}}."""
    blocs = {}
    for selecteur, corps in re.findall(r"([^{}]+)\{([^{}]*)\}", re.sub(r"/\*.*?\*/", "", texte, flags=re.S)):
        blocs[" ".join(selecteur.split())] = dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\s*;", corps))
    return blocs


def _contraste(a, b):
    def luminance(h):
        r, g, bl = (int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))
        f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4    # noqa: E731
        return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(bl)
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


TEXTES = (("texte", "fond"), ("texte", "surface"), ("texte", "surface-2"), ("texte-doux", "fond"),
          ("texte-doux", "surface"), ("texte-doux", "surface-2"), ("accent-texte", "fond"), ("accent-texte", "surface"),
          ("sur-accent", "accent"), ("sur-danger", "danger"), ("succes", "surface"), ("avertissement", "surface"),
          ("mode-reel", "surface"), ("mode-simulation", "surface"))
REPERES = ("repere-accueil", "repere-salle", "repere-choisi", "repere-robot", "itineraire", "zone-interdite",
           "zone-lente", "trajet", "nuage-bas", "nuage-milieu", "nuage-haut")


def test_jetons_du_theme_et_contrastes():
    blocs = _jetons((WEB / "css" / "theme.css").read_text(encoding="utf-8"))
    sombre = blocs[':root, :root[data-theme="sombre"]']
    clair = blocs[':root[data-theme="clair"]']
    commun = blocs[":root"]
    assert set(sombre) == set(clair)
    # palette d'Unitree Explore (décision I6)
    assert (sombre["fond"], sombre["surface"], sombre["accent"], sombre["accent-actif"]) == \
        ("#2e2e3d", "#201f2d", "#5569d4", "#6577e0")
    assert commun["vue-fond"] == "#1e1e1e"
    faibles = [(nom, a, b, round(_contraste(t[a], t[b]), 2)) for nom, t in (("sombre", sombre), ("clair", clair))
               for a, b in TEXTES if _contraste(t[a], t[b]) < 4.5]
    faibles += [("vue", a, "vue-fond", round(_contraste(commun[a], commun["vue-fond"]), 2))
                for a in ("vue-texte", "vue-texte-doux") if _contraste(commun[a], commun["vue-fond"]) < 4.5]
    faibles += [("vue", a, "vue-fond", round(_contraste(commun[a], commun["vue-fond"]), 2))
                for a in REPERES if _contraste(commun[a], commun["vue-fond"]) < 3.0]
    assert faibles == []


# ---------------------------------------------------------------- plan, recette et propriétaires

def _section_12():
    plan = PLAN.read_text(encoding="utf-8")
    titre = "## 12. Interface à la SolidWorks, carte 3D, scan corrigé, robot et caméra (vague 5)"
    assert titre in plan
    s12 = plan[plan.index(titre):]
    fin = s12.find("\n## 13.")                # vague 6 : la section 13 suit (test_contrats_vague6.py)
    return plan, s12 if fin < 0 else s12[:fin]


def test_plan_section_12():
    plan, s12 = _section_12()
    for titre in ("### 12.2 L'interface (agent Coquille)", "### 12.3 La carte 3D (agent Carte 3D)",
                  "### 12.4 Les routes nouvelles", "### 12.5 Le scan corrigé (agent Scan)",
                  "### 12.6 Le robot (agent Robot)", "### 12.7 La caméra de poitrine (agent Caméra)",
                  "### 12.8 Les agents de la vague 5 et leurs fichiers", "### 12.9 Dépendances entre agents",
                  "### 12.10 Critères de recette 31 à 36", "### 12.11 Règles communes de la vague 5",
                  "### 12.12 Ce qui reste à vérifier sur le robot"):
        assert titre in s12, titre
    for mot in ("ouvrir(racine, options)", "options.panneau", "options.mode", "data-commande", "atelier.mode",
                "creerCarte3D", "surPose", "/api/arret", "/api/arret/debloquer", "/api/robot/liaison",
                "multipart/x-mixed-replace", "X-Nuage-Points", "cartes/<e>.nuage", "carte_extrudee", "carte_du_scan",
                "--refaire", "carte-unitree", "/unitree/slam_relocation/global_map", "vitesse_min_lin",
                "vitesse_min_rot", "zone_morte_lin", "zone_morte_rot", "MODES_MARCHE", "pas_en_marche", "mode_robot",
                "vx_min: 0.0", "G1_VITESSE_MAX", "camera_usb", "/camera_poitrine/image/compressed", "g1-visiteurs",
                "boite", "E2E_OVERLAY", "1366 × 768"):
        assert mot in s12, mot
    for n in range(31, 37):
        assert re.search(rf"^{n}\. \*\*", s12, re.M), f"critère {n} absent de la section 12"
    assert "section 12 en entier" in plan[:plan.index("## 1. Le but")]


def test_exemples_du_plan_conformes():
    """Les exemples écrits dans la section 12 (monde maillé, en-tête d'un nuage) passent la validation."""
    _, s12 = _section_12()
    mondes = [yaml.safe_load(b) for b in re.findall(r"```yaml\n(.*?)```", s12, re.S)]
    entetes = [json.loads(b) for b in re.findall(r"```json\n(.*?)```", s12, re.S)]
    assert mondes and entetes
    assert all(L.valider_donnees("monde", m) == [] and "carte_extrudee" in m for m in mondes)
    assert all(L.valider_donnees("nuage", e) == [] for e in entetes)


def test_tout_sh_compte_36_criteres():
    tout = TOUT.read_text(encoding="utf-8")
    # les 36 premiers critères restent (la vague 6 en ajoute six : test_contrats_vague6.py)
    assert re.search(r"^TOUS=\(" + " ".join(str(n) for n in range(1, 37)) + r"( \d+)*\)$", tout, re.M)
    assert re.search(r"N / (36|4[0-9])", tout)
    for n in range(31, 37):
        assert re.search(rf"\[{n}\]=\d+", tout), f"délai du critère {n}"
    assert "E2E_OVERLAY" in (RACINE / "tests_e2e" / "commun.sh").read_text(encoding="utf-8")


def _developper(texte):
    """Développe les accolades d'un chemin : a/{b,c}.py → a/b.py, a/c.py."""
    m = re.search(r"\{([^{}]+)\}", texte)
    if not m:
        return [texte]
    return [x for choix in m.group(1).split(",")
            for x in _developper(texte[:m.start()] + choix.strip() + texte[m.end():])]


def _revendications(cellule):
    """(chemins, exceptions) d'une cellule de la table 12.8 ; « (sauf `x`) » retire x d'un dossier revendiqué."""
    exceptions = set()
    for m in re.finditer(r"sauf ((?:`[^`]+`(?:, | et | ou )?)+)", cellule):
        exceptions |= set(re.findall(r"`([^`]+)`", m.group(1)))
    chemins = set()
    for brut in re.findall(r"`([^`]+)`", cellule):
        if brut in exceptions:
            continue
        chemins |= {c for c in _developper(brut) if "/" in c}
    return chemins, exceptions


def _se_recouvrent(a, b):
    if a == b or (a.endswith("/") and b.startswith(a)) or (b.endswith("/") and a.startswith(b)):
        return True
    return any(x in a for x in "*?[") and fnmatch.fnmatchcase(b, a) or \
        any(x in b for x in "*?[") and fnmatch.fnmatchcase(a, b)


def test_table_des_proprietaires_sans_recouvrement():
    """Aucun chemin (dossier, fichier ou motif) de la table 12.8 n'est à deux agents."""
    _, s12 = _section_12()
    table = s12[s12.index("### 12.8"):s12.index("### 12.9")]
    lignes = [x for x in table.splitlines() if x.startswith("| ") and not x.startswith("| Agent") and "---" not in x]
    assert len(lignes) == 6
    agents = {}
    for ligne in lignes:
        cellules = ligne.split(" | ")
        agents[cellules[0].strip("| ").strip()] = (_revendications(cellules[2]), cellules[1])
    for agent, domaine in (("Coquille", "101"), ("Carte 3D", "102"), ("Scan", "103"), ("Robot", "104"),
                           ("Caméra", "105")):
        nom = next(n for n in agents if n.startswith(agent))
        port = str(8110 + int(domaine) - 100)
        assert domaine in agents[nom][1] and "`v5_" in agents[nom][1] and port in agents[nom][1], nom
    conflits = []
    noms = sorted(agents)
    for i, a in enumerate(noms):
        (chemins_a, sauf_a), _ = agents[a]
        for b in noms[i + 1:]:
            (chemins_b, sauf_b), _ = agents[b]
            for x in chemins_a:
                for y in chemins_b:
                    if _se_recouvrent(x, y) and y not in sauf_a and x not in sauf_b:
                        conflits.append((a, x, b, y))
    assert conflits == []
    # quelques fichiers dont le propriétaire est fixé par la tâche de cette vague
    proprietaire = {c: n for n, ((chemins, _), _) in agents.items() for c in chemins}
    for chemin, agent in (("atelier/web/js/coque/", "Coquille"), ("atelier/web/js/carte3d/", "Carte 3D"),
                          ("atelier/scan/", "Scan"), ("ws/src/g1_bridge/", "Robot"), ("docker/", "Caméra"),
                          ("atelier/serveur/pont_ros.py", "Caméra"), ("atelier/web/js/ecrans/scan.js", "Scan"),
                          ("atelier/web/js/ecrans/camera.js", "Caméra"), ("atelier/lieu/pilotage.py", "Robot"),
                          ("atelier/serveur/main.py", "Contrats"), ("tests_e2e/tout.sh", "Contrats")):
        assert proprietaire[chemin].startswith(agent), (chemin, proprietaire[chemin])
