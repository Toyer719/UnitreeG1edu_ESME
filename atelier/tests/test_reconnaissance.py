"""Tests de la reconnaissance du scan (atelier.scan.reconnaissance, section 9.6 du plan), sans ROS ni écran.

Nuages synthétiques : atelier.scan.evaluation.nuage_synthetique lance des rayons (Open3D) depuis des
points de vue sur les murs et les objets d'un monde dessiné ; seules les surfaces visibles reçoivent des
points, avec du bruit et des trous. La pièce d'essai a une porte de 0,9 m, un trou de 0,5 m (pas un
passage : le mur doit rester d'un seul tenant), une table, une chaise, un poteau et une personne debout.
"""
import hashlib
import math
import subprocess
import sys

import numpy as np
import pytest

from atelier import RACINE
from atelier import lieu as L
from atelier.scan import evaluation as E
from atelier.scan import reconnaissance as R
from atelier.scan.carte2d import fabriquer_carte
from atelier.scan.carte3d import ecrire_pcd

PYTHON = RACINE / ".venv-projet" / "bin" / "python"


# ---------------------------------------------------------------- la pièce d'essai

def monde_piece():
    """Pièce de 8 × 6 m : porte de 0,9 m au nord (x 3,55 à 4,45), trou de 0,5 m à l'ouest (y 2,75 à
    3,25), une table, une chaise, un poteau et une personne debout."""
    murs = [L.Mur("sud", (0.0, 0.0), (8.0, 0.0), 0.15, 2.5),
            L.Mur("est", (8.0, 0.0), (8.0, 6.0), 0.15, 2.5),
            L.Mur("nord_1", (8.0, 6.0), (4.45, 6.0), 0.15, 2.5),
            L.Mur("nord_2", (3.55, 6.0), (0.0, 6.0), 0.15, 2.5),
            L.Mur("ouest_1", (0.0, 6.0), (0.0, 3.25), 0.15, 2.5),
            L.Mur("ouest_2", (0.0, 2.75), (0.0, 0.0), 0.15, 2.5)]
    objets = [L.Objet.meuble("table_1", "table", (2.0, 1.6), 0.0, categorie="table"),
              L.Objet.meuble("chaise_1", "chaise", (2.0, 2.5), -math.pi / 2, categorie="chaise"),
              L.Objet.cylindre("poteau_1", (6.0, 3.8), 0.2, 2.5, categorie="poteau"),
              L.Objet.cylindre("personne_1", (5.5, 1.9), 0.25, 1.7, categorie="personne")]
    return L.Monde(L.Emprise(0.0, 0.0, 8.0, 6.0), L.Pose(1.0, 1.0, 0.0), murs, objets, [])


def tour_de_piece(pas=0.25):
    """Points de vue le long d'une boucle dans la pièce, loin des objets."""
    coins = [(1.0, 0.8), (7.0, 0.8), (7.0, 5.0), (1.0, 5.0), (1.0, 0.8)]
    vues = []
    for a, b in zip(coins, coins[1:]):
        n = int(math.dist(a, b) / pas)
        vues += [(a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n) for k in range(n)]
    return vues


@pytest.fixture(scope="module")
def piece(tmp_path_factory):
    """Nuage, carte, reconnaissance et bilan de la pièce d'essai (une seule fois pour le module)."""
    dossier = tmp_path_factory.mktemp("piece")
    monde = monde_piece()
    resultat, bilan = E.essayer_sur_monde(monde, tour_de_piece(), dossier, bruit=0.015, trous=15, graine=4,
                                          parametres={"depart_robot": (1.0, 1.0, 0.0)})
    return {"dossier": dossier, "monde": monde, "resultat": resultat, "bilan": bilan,
            "reco": L.lire_reconnaissance(dossier)}


# ---------------------------------------------------------------- la pièce : murs, passages, objets

def test_fichiers_ecrits_et_valides(piece):
    d = piece["dossier"]
    r = piece["resultat"]
    assert r["fichier"] == str(d / "reconnaissance.yaml")
    assert r["monde"] == str(d / "monde_scan.monde.yaml")
    assert set(r) == {"fichier", "monde", "resume", "duree_s", "avertissements"}
    assert r["resume"] == L.resume_reconnaissance(piece["reco"])
    assert r["duree_s"] < 60
    assert L.valider_reconnaissance(piece["reco"]) == []
    monde = L.charger_fichier(d / "monde_scan.monde.yaml", "monde")
    assert L.valider_donnees("monde", monde) == []
    # rien d'autre que les entrées et les deux fichiers de la reconnaissance
    attendus = ["carte.pgm", "carte.yaml", "monde_scan.monde.yaml", "nuage.pcd", "reconnaissance.yaml"]
    assert sorted(p.name for p in d.iterdir()) == attendus


def test_murs_de_la_piece(piece):
    b = piece["bilan"]["murs"]
    assert b["rappel"] >= 0.9 and b["precision"] >= 0.9, E.texte_bilan(piece["bilan"])
    murs = piece["reco"]["murs"]
    assert all(m["id"].startswith("mur_") and m["categorie"] == "mur" for m in murs)
    assert all(m["a_garder"] and 0 <= m["confiance"] <= 1 for m in murs)
    # hauteur mesurée : 2,5 m
    assert all(abs(m["hauteur"] - 2.5) < 0.1 for m in murs)


def test_trou_de_50_cm_bouche(piece):
    """Le trou de 0,5 m du mur ouest n'est pas un passage : un seul mur, d'un bout à l'autre."""
    ouest = [m for m in piece["reco"]["murs"] if max(abs(m["de"][0]), abs(m["a"][0])) < 0.3]
    assert len(ouest) == 1, ouest
    m = ouest[0]
    assert math.dist(m["de"], m["a"]) > 5.0
    for p in piece["reco"]["passages"]:
        assert max(abs(p["de"][0]), abs(p["a"][0])) > 0.3, "passage dans le mur ouest"


def test_porte_de_90_cm(piece):
    passages = piece["reco"]["passages"]
    assert len(passages) == 1, passages
    p = passages[0]
    assert p["id"] == "passage_1" and p["categorie"] == "passage" and p["a_garder"]
    assert abs(math.dist(p["de"], p["a"]) - 0.9) < 0.1
    milieu = ((p["de"][0] + p["a"][0]) / 2, (p["de"][1] + p["a"][1]) / 2)
    assert math.dist(milieu, (4.0, 6.0)) < 0.15
    murs = {m["id"]: m for m in piece["reco"]["murs"]}
    m1, m2 = (murs[i] for i in p["murs"])
    assert L.est_passage(m1["de"], m1["a"], m2["de"], m2["a"])
    assert piece["bilan"]["passages"]["rappel"] == 1.0 and piece["bilan"]["passages"]["precision"] == 1.0


def test_objets_de_la_piece(piece):
    b = piece["bilan"]["objets"]
    assert b["detection"] == 1.0, E.texte_bilan(piece["bilan"])
    assert b["categorie"] == 1.0, E.texte_bilan(piece["bilan"])
    assert b["faux"] == []
    for o in piece["reco"]["objets"]:
        assert o["id"] == f"{o['categorie']}_{o['id'].rsplit('_', 1)[1]}"
        assert 0 <= o["confiance"] <= 1
        assert o["forme"] in ("boite", "cylindre")


def test_personne_jamais_gardee(piece):
    personnes = [o for o in piece["reco"]["objets"] if o["categorie"] == "personne"]
    assert len(personnes) == 1
    p = personnes[0]
    assert p["a_garder"] is False and p["forme"] == "cylindre"
    assert math.dist(p["centre"], (5.5, 1.9)) < 0.1
    assert abs(p["hauteur"] - 1.7) < 0.1
    assert piece["bilan"]["personnes"]["ok"]
    # absente du monde tiré du scan (non gardée), donc de sa carte et du monde Gazebo
    monde = L.charger_fichier(piece["dossier"] / "monde_scan.monde.yaml", "monde")
    assert all(o.get("categorie") != "personne" for o in monde["objets"])


def test_monde_du_scan_simulable(piece):
    """Le monde tiré du scan donne un monde Gazebo et une carte 2D (atelier.monde)."""
    from atelier.monde import fabriquer_carte as carte_du_monde
    from atelier.monde import texte_sdf
    monde = L.Monde.depuis_dict(L.charger_fichier(piece["dossier"] / "monde_scan.monde.yaml", "monde"))
    assert all(m.source == "scan" for m in monde.murs) and all(o.source == "scan" for o in monde.objets)
    sdf = texte_sdf(monde, nom="rdc")
    assert sdf.count("<model ") >= len(monde.murs) + len(monde.objets)
    info, image = carte_du_monde(monde)[:2]
    assert (np.asarray(image) == 0).sum() > 1000


def test_meme_resultat_a_chaque_appel(piece, tmp_path):
    d = piece["dossier"]
    for k in (1, 2):
        R.reconnaitre(d / "nuage.pcd", d / "carte.yaml", tmp_path / f"essai{k}", {"depart_robot": (1.0, 1.0, 0.0)})
    for nom in ("reconnaissance.yaml", "monde_scan.monde.yaml"):
        empreintes = {hashlib.sha256((tmp_path / f"essai{k}" / nom).read_bytes()).hexdigest() for k in (1, 2)}
        empreintes.add(hashlib.sha256((d / nom).read_bytes()).hexdigest())
        assert len(empreintes) == 1, nom


def test_session_etage_et_depart_par_defaut(piece, tmp_path):
    d = piece["dossier"]
    session = tmp_path / "2026-10-25_17h42"
    R.reconnaitre(d / "nuage.pcd", d / "carte.yaml", session)
    reco = L.lire_reconnaissance(session)
    assert reco["session"] == "2026-10-25_17h42" and reco["etage"] == "rdc"
    # départ : un point libre près du centre de l'emprise, loin des obstacles
    depart = (reco["depart_robot"]["x"], reco["depart_robot"]["y"])
    assert math.dist(depart, (4.0, 3.0)) < 1.5
    assert all(math.dist(depart, o["centre"]) > 0.4 for o in reco["objets"])
    autre = tmp_path / "essai"
    R.reconnaitre(d / "nuage.pcd", d / "carte.yaml", autre, {"etage": "etage1", "session": None})
    reco = L.lire_reconnaissance(autre)
    assert reco["session"] is None and reco["etage"] == "etage1"
    # emprise : la partie connue de la carte (à la marge près), qui contient tout
    e = reco["emprise"]
    assert all(-0.1 <= v <= 0.0 for v in e["min"]) and 8.0 <= e["max"][0] <= 8.1 and 6.0 <= e["max"][1] <= 6.1


# ---------------------------------------------------------------- erreurs : rien d'écrit à moitié

def test_nuage_ou_carte_introuvable(piece, tmp_path):
    d = piece["dossier"]
    with pytest.raises(R.ErreurReconnaissance, match="nuage introuvable"):
        R.reconnaitre(tmp_path / "absent.pcd", d / "carte.yaml", tmp_path / "sortie")
    with pytest.raises(R.ErreurReconnaissance, match="carte introuvable.*g1-carte-2d"):
        R.reconnaitre(d / "nuage.pcd", tmp_path / "absente.yaml", tmp_path / "sortie")
    assert not (tmp_path / "sortie").exists()


def test_nuage_presque_vide(piece, tmp_path):
    ecrire_pcd(tmp_path / "vide.pcd", np.zeros((10, 3)) + [[1.0, 1.0, 0.0]])
    with pytest.raises(R.ErreurReconnaissance, match="presque vide.*recommencez"):
        R.reconnaitre(tmp_path / "vide.pcd", piece["dossier"] / "carte.yaml", tmp_path / "sortie")


def test_parametres_refuses(piece, tmp_path):
    d = piece["dossier"]
    with pytest.raises(R.ErreurReconnaissance, match="paramètre inconnu : dbscan"):
        R.reconnaitre(d / "nuage.pcd", d / "carte.yaml", tmp_path, {"dbscan": 1})
    with pytest.raises(R.ErreurReconnaissance, match="mur_tranche.*liste de 2"):
        R.reconnaitre(d / "nuage.pcd", d / "carte.yaml", tmp_path, {"mur_tranche": 1.5})
    with pytest.raises(R.ErreurReconnaissance, match="étage « Rez »"):
        R.reconnaitre(d / "nuage.pcd", d / "carte.yaml", tmp_path, {"etage": "Rez"})
    assert list(tmp_path.iterdir()) == []


def test_resultat_invalide_rien_d_ecrit(piece, tmp_path, monkeypatch):
    """Si la reconnaissance produisait un fichier invalide, rien ne serait écrit."""
    vrai = R.analyser

    def abime(*args, **kwargs):
        donnees, avertissements, details = vrai(*args, **kwargs)
        donnees["murs"][0]["a"] = list(donnees["murs"][0]["de"])        # mur de longueur nulle
        return donnees, avertissements, details
    monkeypatch.setattr(R, "analyser", abime)
    d = piece["dossier"]
    with pytest.raises(R.ErreurReconnaissance, match="invalide.*adoptez-la sans le monde"):
        R.reconnaitre(d / "nuage.pcd", d / "carte.yaml", tmp_path / "sortie")
    assert not (tmp_path / "sortie").exists()


def test_erreur_imprevue_message_clair(piece, tmp_path, monkeypatch):
    monkeypatch.setattr(R, "trouver_sol", lambda *a, **k: 1 / 0)
    d = piece["dossier"]
    with pytest.raises(R.ErreurReconnaissance, match="ZeroDivisionError.*g1-scan traiter"):
        R.reconnaitre(d / "nuage.pcd", d / "carte.yaml", tmp_path / "sortie")
    assert not (tmp_path / "sortie").exists()


# ---------------------------------------------------------------- sol et plafond

def _sol_incline(n=4000, pente=math.radians(2.0), z0=-0.07, graine=0):
    rng = np.random.default_rng(graine)
    x, y = rng.uniform(0, 10, n), rng.uniform(0, 8, n)
    z = z0 + math.tan(pente) * (x - 5.0) + rng.normal(0, 0.005, n)
    return np.column_stack([x, y, z])


def test_sol_par_ransac():
    p, _ = R._reglages(None)
    sol = _sol_incline()
    mur = np.column_stack([np.full(3000, 2.0), np.linspace(0, 8, 3000), np.tile(np.linspace(-0.07, 2.5, 30), 100)])
    points = np.vstack([sol, mur])
    resultat = R.trouver_sol(points, p)
    assert resultat["methode"] == "ransac"
    a, b, c, d = resultat["plan"]
    assert math.degrees(math.acos(c)) == pytest.approx(2.0, abs=0.3)
    h = R.hauteurs(points, resultat["plan"])
    assert np.abs(h[:len(sol)]).max() < 0.03                      # le sol est à hauteur 0
    assert h[len(sol):].max() == pytest.approx(2.57, abs=0.2)
    # même plan à chaque appel (graine fixe)
    assert R.trouver_sol(points, p)["plan"] == resultat["plan"]


def test_sol_introuvable_ou_impose():
    p, _ = R._reglages(None)
    mur = np.column_stack([np.full(2000, 2.0), np.linspace(0, 8, 2000), np.linspace(0.2, 2.5, 2000)])
    resultat = R.trouver_sol(mur, p)
    assert resultat["methode"] == "centile"
    assert resultat["sol"] == pytest.approx(np.percentile(mur[:, 2], 1))
    assert R.trouver_sol(mur, p, sol_impose=-0.1)["plan"] == (0.0, 0.0, 1.0, 0.1)


def test_plafond(tmp_path):
    """Une pièce avec un plafond à 2,6 m : le plafond est retiré, les murs en prennent la hauteur et
    il ne devient pas un objet."""
    monde = monde_piece()
    monde.objets = [o for o in monde.objets if o.id != "personne_1"]
    vues = tour_de_piece(0.5)
    points = E.nuage_synthetique(monde, vues, bruit=0.01, graine=5)
    rng = np.random.default_rng(1)
    plafond = np.column_stack([rng.uniform(0.1, 7.9, 30000), rng.uniform(0.1, 5.9, 30000), np.full(30000, 2.6)])
    points = np.vstack([points[points[:, 2] < 2.55], plafond])
    p, _ = R._reglages(None)
    sol = R.trouver_sol(points, p)
    h = R.hauteurs(points, sol["plan"])
    assert R.trouver_plafond(points, h, p) == pytest.approx(2.6, abs=0.02)
    # sans plafond : le haut des murs (une bande) n'en est pas un
    sans = points[:len(points) - len(plafond)]
    assert R.trouver_plafond(sans, R.hauteurs(sans, sol["plan"]), p) is None
    ecrire_pcd(tmp_path / "nuage.pcd", points)
    info, image, _ = fabriquer_carte(points, (0, 0, 8, 6))
    L.enregistrer_carte(tmp_path / "carte.yaml", info, image)
    R.reconnaitre(tmp_path / "nuage.pcd", tmp_path / "carte.yaml", tmp_path)
    reco = L.lire_reconnaissance(tmp_path)
    assert reco["murs"] and all(m["hauteur"] == pytest.approx(2.6, abs=0.02) for m in reco["murs"])
    assert all(o["infos"]["hauteur_mesuree"] < 2.55 for o in reco["objets"])
    assert sorted(o["categorie"] for o in reco["objets"]) == ["chaise", "poteau", "table"]


# ---------------------------------------------------------------- petits outils et règles

def test_appartenance_et_troncons():
    assert R.appartenance(0.75, 0.7, 0.8, 0.1) == 1.0
    assert R.appartenance(0.65, 0.7, 0.8, 0.1) == pytest.approx(0.5)
    assert R.appartenance(0.95, 0.7, 0.8, 0.1) == 0.0
    t = np.array([0.0, 0.1, 0.2, 1.0, 1.1, 3.0])
    assert R._troncons(t, 0.5) == [(0, 2), (3, 4), (5, 5)]
    assert R._troncons(np.array([]), 0.5) == []


def test_cercle():
    angles = np.linspace(-1.2, 1.4, 40)
    xy = np.column_stack([3.0 + 0.25 * np.cos(angles), 2.0 + 0.25 * np.sin(angles)])
    centre, rayon, ecart = R._cercle(xy)
    assert np.allclose(centre, (3.0, 2.0), atol=1e-6) and rayon == pytest.approx(0.25) and ecart < 1e-6


def _mesures(**f):
    base = {"points": 200, "centre": np.zeros(2), "cap": 0.0, "longueur": 0.5, "largeur": 0.5, "hauteur": 0.9,
            "bas": 0.2, "plateau": None, "part_plateau": 0.1, "densite": 1.0, "remplissage": 0.2, "rondeur": 0.0,
            "centre_cercle": None, "rayon": None, "finesse": 1.8}
    base.update(f)
    base["finesse"] = base["hauteur"] / base["longueur"]
    return base


@pytest.mark.parametrize("mesures, attendue", [
    (dict(hauteur=0.76, plateau=0.73, longueur=1.25, largeur=0.85, remplissage=0.2), "table"),
    (dict(hauteur=0.9, plateau=0.45, longueur=0.5, largeur=0.48, remplissage=0.3), "chaise"),
    (dict(hauteur=0.55, plateau=0.52, longueur=0.5, largeur=0.4, remplissage=None), "chaise"),
    (dict(hauteur=0.47, plateau=0.45, longueur=1.55, largeur=0.45, remplissage=0.9), "banc"),
    (dict(hauteur=2.5, longueur=0.45, largeur=0.44, rondeur=1.0, remplissage=0.9), "poteau"),
    (dict(hauteur=0.8, longueur=0.55, largeur=0.55, rondeur=0.95, remplissage=0.95), "poubelle"),
    (dict(hauteur=1.1, longueur=2.0, largeur=0.8, remplissage=0.9), "meuble"),
    (dict(hauteur=0.75, plateau=0.72, longueur=3.0, largeur=0.8, remplissage=0.95), "meuble"),
    (dict(hauteur=1.7, longueur=0.5, largeur=0.45, rondeur=0.9), "personne"),
    (dict(hauteur=0.3, longueur=0.3, largeur=0.2), "inconnu"),
])
def test_categories(mesures, attendue):
    p, _ = R._reglages(None)
    categorie, confiance, scores = R.classer(_mesures(**mesures), p)
    assert categorie == attendue, scores
    assert 0 <= confiance <= 1
    if attendue == "inconnu":
        assert confiance < 0.5                        # l'interface signale les éléments sous 0,5


def test_personne_jamais_cochee_d_office():
    assert L.a_garder_par_defaut("personne") is False
    p, _ = R._reglages(None)
    f = _mesures(hauteur=1.75, longueur=0.5, largeur=0.5, rondeur=1.0, centre_cercle=np.array([1.0, 2.0]),
                 rayon=0.24)
    assert R.classer(f, p)[0] == "personne"
    forme = R.forme_objet(f, "personne")
    assert forme["forme"] == "cylindre" and forme["rayon"] >= 0.24 and tuple(forme["centre"]) == (1.0, 2.0)


# ---------------------------------------------------------------- ligne de commande

def test_ligne_de_commande(piece, tmp_path):
    d = piece["dossier"]
    sortie = subprocess.run([str(PYTHON if PYTHON.exists() else sys.executable), "-m", "atelier.scan.reconnaissance",
                             str(d / "nuage.pcd"), str(d / "carte.yaml"), str(tmp_path / "s"),
                             "--depart", "1", "1", "0", "--parametre", "dbscan_eps=0.12"],
                            capture_output=True, text=True, cwd=RACINE, timeout=120)
    assert sortie.returncode == 0, sortie.stderr
    assert "Reconnaissance écrite" in sortie.stdout and "passages : 1" in sortie.stdout
    assert (tmp_path / "s" / "reconnaissance.yaml").is_file()
    erreur = subprocess.run([str(PYTHON if PYTHON.exists() else sys.executable), "-m", "atelier.scan.reconnaissance",
                             str(tmp_path / "absent.pcd"), str(d / "carte.yaml"), str(tmp_path / "t")],
                            capture_output=True, text=True, cwd=RACINE, timeout=120)
    assert erreur.returncode == 1 and "Erreur : nuage introuvable" in erreur.stderr
