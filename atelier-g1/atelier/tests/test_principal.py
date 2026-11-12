"""Tests du point principal (vague 4, section 11.2 du plan), agent Point principal : les écritures de
atelier.lieu.principal (definir_principal, ecrire_salles, synchroniser_depart, sauvegarder_lieu,
migrer_lieu), sans serveur ni ROS.

  ~/robot-g1/.venv-projet/bin/python -m pytest ~/robot-g1/atelier/tests/test_principal.py -v

Toujours sur des copies (tmp_path) : lieux/demo, la référence, n'est jamais écrit (ses empreintes
sont vérifiées) ; bomboclat et demo_scan ne sont que lus, et leurs copies migrées.
"""
import hashlib
import json
import math
import os
import shutil
import sys
from pathlib import Path

import pytest
import yaml

import atelier
from atelier import lieu as L
from atelier.lieu import principal as A
from atelier.lieu.fichiers import lire_yaml

RACINE = atelier.RACINE
DEMO = RACINE / "lieux" / "demo"
REPERE_B = (3.0, 9.0, 0.5)           # repère d'Unitree tourné du critère 18 (variante B)


def empreintes(dossier):
    """{chemin relatif : sha256} de tous les fichiers d'un dossier."""
    dossier = Path(dossier)
    return {str(f.relative_to(dossier)): hashlib.sha256(f.read_bytes()).hexdigest()
            for f in sorted(dossier.rglob("*")) if f.is_file()}


@pytest.fixture(scope="module", autouse=True)
def demo_intact():
    """lieux/demo (la référence des tests) est le même avant et après tous ces tests."""
    avant = empreintes(DEMO)
    yield
    assert empreintes(DEMO) == avant, "lieux/demo a changé !"


@pytest.fixture
def demo(tmp_path):
    return L.copier_lieu(DEMO, tmp_path / "demo")


def lire(dossier, nom):
    return yaml.safe_load((Path(dossier) / nom).read_text(encoding="utf-8"))


def salle(dossier, ident):
    return next(s for s in lire(dossier, "salles.yaml") if s["id"] == ident)


# ---------------------------------------------------------------- definir_principal

def test_orientation_seule(demo):
    """theta seul : salles.yaml, accueil de lieu.yaml et depart_robot valent la même chose ; les
    commentaires écrits à la main de lieu.yaml et du monde restent (seule la ligne change)."""
    lieu_avant = (demo / "lieu.yaml").read_text(encoding="utf-8")
    monde_avant = (demo / "mondes" / "rdc.monde.yaml").read_text(encoding="utf-8")
    r = A.definir_principal(demo, theta=1.5708)
    assert r["enregistre"] == ["salles.yaml", "lieu.yaml", "mondes/rdc.monde.yaml"]
    assert salle(demo, "accueil")["pose"] == {"x": 2.5, "y": 10.0, "theta": 1.5708}
    assert salle(demo, "accueil")["etiquettes"] == ["principal"]          # devenu explicite
    assert lire(demo, "lieu.yaml")["accueil"] == {"etage": "rdc", "x": 2.5, "y": 10.0, "theta": 1.5708}
    assert lire(demo, "mondes/rdc.monde.yaml")["depart_robot"] == {"x": 2.5, "y": 10.0, "theta": 1.5708}
    lieu_apres = (demo / "lieu.yaml").read_text(encoding="utf-8")
    assert lieu_apres == lieu_avant.replace("accueil: {etage: rdc, x: 2.5, y: 10.0, theta: 0.0}",
                                            "accueil: {etage: rdc, x: 2.5, y: 10.0, theta: 1.5708}")
    monde_apres = (demo / "mondes" / "rdc.monde.yaml").read_text(encoding="utf-8")
    assert monde_apres.replace("theta: 1.5708}", "theta: 0.0}") == monde_avant
    assert r["principal"]["theta"] == 1.5708 and r["principal"]["explicite"] and r["principal"]["depart_synchro"]
    assert r["rapport"]["erreurs"] == [] and r["rapport"]["avertissements"] == []
    assert A.accueil_conforme(demo) and A.depart_simulation(demo, "rdc") == L.Pose(2.5, 10.0, 1.5708)
    # un second passage ne réécrit rien
    assert A.definir_principal(demo, theta=1.5708)["enregistre"] == []


def test_deplacer_puis_changer_de_salle(demo):
    r = A.definir_principal(demo, x=2.5, y=11.0, theta=1.5708)
    assert r["enregistre"] == ["salles.yaml", "itineraires.yaml", "lieu.yaml", "mondes/rdc.monde.yaml"]
    n = lire(demo, "itineraires.yaml")["noeuds"]["accueil"]
    assert (n["x"], n["y"]) == (2.5, 11.0)
    assert A.pose_de_reperage(demo, "rdc") == L.Pose(2.5, 11.0, 1.5708)
    assert {c["champ"] for c in r["changements"]} == {"salle « accueil », etiquettes", "salle « accueil », pose",
                                                      "nœud « accueil »", "accueil", "depart_robot"}
    # b204 devient le point principal : l'étiquette passe, accueil et départ suivent
    r = A.definir_principal(demo, salle="b204")
    assert "etiquettes" not in salle(demo, "accueil") and salle(demo, "b204")["etiquettes"] == ["principal"]
    assert lire(demo, "lieu.yaml")["accueil"] == {"etage": "rdc", "x": 21.0, "y": 13.0, "theta": 1.5708}
    assert lire(demo, "mondes/rdc.monde.yaml")["depart_robot"] == {"x": 21.0, "y": 13.0, "theta": 1.5708}
    assert A.point_principal(demo).id == "b204" and r["rapport"]["erreurs"] == []
    # étiquettes libres gardées (section 11.2 : seule « principal » est réservée)
    lieu = L.charger_lieu(demo)
    lieu.salle("cdi").etiquettes = ["sortie"]
    L.enregistrer_salles(demo, lieu.salles)
    A.definir_principal(demo, salle="cdi")
    assert salle(demo, "cdi")["etiquettes"] == ["principal", "sortie"]


def test_angle_ramene_entre_moins_pi_et_pi(demo):
    A.definir_principal(demo, theta=-4.0)
    assert math.isclose(A.point_principal(demo).pose.theta, -4.0 + 2 * math.pi, abs_tol=1e-6)
    A.definir_principal(demo, theta=math.pi)
    assert math.isclose(A.point_principal(demo).pose.theta, math.pi, abs_tol=1e-6)


@pytest.mark.parametrize("arguments, morceau", [
    ({}, "rien à changer"),
    ({"x": 1.0}, "x et y vont ensemble"),
    ({"x": float("nan"), "y": 1.0}, "nombre fini"),
    ({"theta": 9.0}, "entre -2π et 2π"),
    ({"theta": True}, "nombre fini"),
    ({"x": 100.0, "y": 10.0}, "sort de l'emprise"),           # depart_robot hors du monde : tout ou rien
])
def test_refus_sans_rien_ecrire(demo, arguments, morceau):
    avant = empreintes(demo)
    with pytest.raises(L.ErreurLieu) as e:
        A.definir_principal(demo, **arguments)
    assert any(morceau in m for m in e.value.erreurs), e.value.erreurs
    assert empreintes(demo) == avant


def test_salle_inconnue_et_lieu_sans_principal(demo):
    with pytest.raises(A.SalleInconnue) as e:
        A.definir_principal(demo, salle="grenier")
    assert "« grenier » n'existe pas" in str(e.value)
    L.enregistrer_salles(demo, [s for s in L.charger_salles(demo) if s.id != "accueil"])
    with pytest.raises(L.ErreurLieu) as e:
        A.definir_principal(demo, theta=0.5)
    assert "pas de point principal" in str(e.value)
    assert A.definir_principal(demo, salle="cdi")["principal"]["salle"] == "cdi"     # on peut en choisir un


def test_tout_ou_rien_si_une_ecriture_echoue(demo, monkeypatch):
    """La troisième écriture échoue : les deux premiers fichiers reprennent leur contenu d'avant."""
    avant = {n: (demo / n).read_bytes() for n in ("salles.yaml", "itineraires.yaml", "lieu.yaml")}
    vraie = A.ecrire_atomique
    appels = []

    def ecrire(chemin, texte):
        appels.append(Path(chemin).name)
        if len(appels) == 3:
            raise OSError("disque plein (essai)")
        vraie(chemin, texte)

    monkeypatch.setattr(A, "ecrire_atomique", ecrire)
    with pytest.raises(OSError):
        A.definir_principal(demo, x=3.0, y=10.0)
    monkeypatch.setattr(A, "ecrire_atomique", vraie)
    assert {n: (demo / n).read_bytes() for n in avant} == avant
    assert appels[:3] == ["salles.yaml", "itineraires.yaml", "lieu.yaml"]


def test_le_monde_genere_reste_a_jour(demo):
    """depart_robot n'entre ni dans le .sdf ni dans la carte : un monde à jour le reste ; un monde
    déjà en retard le reste aussi (on ne cache pas un vrai retard)."""
    from atelier.monde import generer
    generer(demo, "rdc")
    monde, sdf, carte = L.chemin_monde(demo, "rdc"), L.chemin_sdf(demo, "rdc"), L.chemin_carte(demo, "rdc")
    vieux = monde.stat().st_mtime - 3600
    for f in (sdf, carte):
        os.utime(f, (vieux + 10, vieux + 10))
    os.utime(monde, (vieux, vieux))
    A.definir_principal(demo, x=2.5, y=11.0, theta=1.5708)
    assert monde.stat().st_mtime > vieux + 1000                     # le monde a bien été réécrit
    assert all(monde.stat().st_mtime <= f.stat().st_mtime + 1 for f in (sdf, carte))
    assert not any("plus ancienne" in m for m in L.valider_lieu(demo).avertissements)
    # carte en retard pour une vraie raison (monde modifié après) : elle n'est pas rajeunie
    os.utime(carte, (vieux, vieux))
    os.utime(monde, (vieux + 100, vieux + 100))
    A.definir_principal(demo, theta=0.0)
    assert carte.stat().st_mtime == vieux
    assert any("plus ancienne" in m for m in L.valider_lieu(demo).avertissements)


def test_monde_ecrit_en_entier_si_la_ligne_est_sur_plusieurs_lignes(demo):
    """depart_robot écrit en bloc (pas sur une ligne) : le fichier est réécrit en entier, valide."""
    chemin = L.chemin_monde(demo, "rdc")
    texte = chemin.read_text(encoding="utf-8").replace("depart_robot: {x: 2.5, y: 10.0, theta: 0.0}",
                                                       "depart_robot:\n  x: 2.5\n  y: 10.0\n  theta: 0.0")
    chemin.write_text(texte, encoding="utf-8")
    A.definir_principal(demo, theta=0.25)
    assert L.charger_monde(demo, "rdc").depart_robot == L.Pose(2.5, 10.0, 0.25)
    assert chemin.read_text(encoding="utf-8").startswith("# Environnement inventé")


# ---------------------------------------------------------------- PUT …/salles

def test_ecrire_salles_deux_principaux_ou_perte_refuses(demo):
    salles = L.charger_salles(demo)
    for s in salles[:2]:
        s.etiquettes = ["principal"]
    with pytest.raises(L.ErreurLieu) as e:
        A.ecrire_salles(demo, salles)
    assert any("un lieu n'a qu'un point principal" in m for m in e.value.erreurs)
    # principal implicite (la salle accueil) : la supprimer est refusé
    sans = [s for s in L.charger_salles(demo) if s.id != "accueil"]
    with pytest.raises(A.PerteDuPrincipal) as e:
        A.ecrire_salles(demo, sans, synchroniser=True)
    assert "choisissez d'abord un autre point principal" in str(e.value) and "supprimez-la" in str(e.value)
    # principal explicite : lui retirer l'étiquette sans la donner à une autre salle est refusé…
    A.definir_principal(demo, salle="b204")
    salles = L.charger_salles(demo)
    salles[-1].etiquettes = []
    with pytest.raises(A.PerteDuPrincipal) as e:
        A.ecrire_salles(demo, salles)
    assert "Salle B204" in str(e.value) and "retirez-lui l'étiquette" in str(e.value)
    assert A.point_principal(demo).id == "b204"
    # … mais la donner à une autre salle, oui : avec synchroniser, accueil et départ suivent
    salles[0].etiquettes = ["principal"]
    ecrits = A.ecrire_salles(demo, salles, synchroniser=True)
    assert ecrits == ["salles.yaml", "lieu.yaml", "mondes/rdc.monde.yaml"]
    assert A.point_principal(demo).id == "accueil" and A.accueil_conforme(demo)
    assert L.charger_monde(demo, "rdc").depart_robot == L.Pose(2.5, 10.0, 0.0)


def test_ecrire_salles_implicite_reste_implicite(demo):
    salles = L.charger_salles(demo)
    salles[0].pose = L.Pose(3.0, 10.0, 0.3)
    assert A.ecrire_salles(demo, salles) == ["salles.yaml"]           # sans synchroniser : salles.yaml seul
    assert A.ecrire_salles(demo, salles, synchroniser=True) == ["salles.yaml", "itineraires.yaml", "lieu.yaml",
                                                                 "mondes/rdc.monde.yaml"]
    assert not A.principal_explicite(demo) and A.accueil_conforme(demo)
    assert "etiquettes" not in (demo / "salles.yaml").read_text(encoding="utf-8")
    assert A.ecrire_salles(demo, salles, synchroniser=True) == ["salles.yaml"]


def test_ecrire_salles_remplace_un_fichier_illisible(demo):
    (demo / "salles.yaml").write_text("- id: [\n", encoding="utf-8")
    salles = L.charger_salles(DEMO)
    assert A.ecrire_salles(demo, salles, synchroniser=True)[0] == "salles.yaml"
    assert A.point_principal(demo).id == "accueil"


# ---------------------------------------------------------------- synchroniser_depart

def test_synchroniser_depart(demo):
    monde = L.charger_monde(demo, "rdc")
    monde.depart_robot = L.Pose(5.0, 13.0, 1.0)
    L.enregistrer_monde(demo, "rdc", monde)
    assert A.decrire_principal(demo)["depart_synchro"] is False
    assert any("la simulation ne partira pas de l'accueil" in m for m in L.valider_lieu(demo).avertissements)
    assert A.synchroniser_depart(demo) is True
    assert L.charger_monde(demo, "rdc").depart_robot == L.Pose(2.5, 10.0, 0.0)
    assert A.synchroniser_depart(demo) is False
    assert not any("depart_robot" in m for m in L.valider_lieu(demo).avertissements)


def test_synchroniser_depart_sans_monde_ni_principal(tmp_path):
    lieu = L.creer_lieu(tmp_path / "neuf", "Neuf")
    (lieu.dossier / "mondes" / "rdc.monde.yaml").unlink()
    assert A.synchroniser_depart(lieu.dossier) is False
    L.enregistrer_salles(lieu.dossier, [])
    assert A.synchroniser_depart(lieu.dossier) is False


# ---------------------------------------------------------------- sauvegarde et migration

def test_sauvegarde_identique_et_numerotee(demo):
    s1 = A.sauvegarder_lieu(demo, "essai")
    s2 = A.sauvegarder_lieu(demo, "essai")
    assert s1.parent == demo / "sauvegardes" and s2.name == s1.name + "-2"
    for nom in ("lieu.yaml", "salles.yaml", "itineraires.yaml", "mondes/rdc.monde.yaml"):
        assert (s1 / nom).read_bytes() == (demo / nom).read_bytes(), nom
        assert (s1 / nom).stat().st_mtime == (demo / nom).stat().st_mtime, nom
    assert not (s1 / "zones.yaml").exists() and not (s1 / "cartes").exists()
    lisezmoi = (s1 / "LISEZMOI.txt").read_text(encoding="utf-8")
    assert "cp -p sauvegardes/" in lisezmoi and "g1-lieu valider --lieu demo" in lisezmoi
    with pytest.raises(ValueError):
        A.sauvegarder_lieu(demo, "../ailleurs")
    # le lieu reste valide avec ses sauvegardes, et sa copie aussi
    assert L.valider_lieu(demo).erreurs == []


def test_migrer_un_lieu(demo):
    avant = empreintes(demo)
    erreurs_avant = L.valider_lieu(demo).erreurs
    r = A.migrer_lieu(demo, a_blanc=True)
    assert r["a_blanc"] and r["sauvegarde"] is None and r["changements"] and empreintes(demo) == avant
    r = A.migrer_lieu(demo)
    sauvegarde = Path(r["sauvegarde"])
    assert sauvegarde.name.endswith("_migration") and sauvegarde.parent == demo / "sauvegardes"
    for nom in ("lieu.yaml", "salles.yaml", "itineraires.yaml", "mondes/rdc.monde.yaml"):
        assert hashlib.sha256((sauvegarde / nom).read_bytes()).hexdigest() == avant[nom], nom
    assert r["enregistre"] == ["salles.yaml"]          # le demo est déjà aligné : seule l'étiquette
    assert salle(demo, "accueil")["etiquettes"] == ["principal"] and A.principal_explicite(demo)
    assert r["erreurs_apres"] == erreurs_avant == L.valider_lieu(demo).erreurs
    assert "Lieu migré" in A.texte_migration(r)
    # idempotent : un second passage ne change rien, sans nouvelle sauvegarde
    avant = empreintes(demo)
    r = A.migrer_lieu(demo)
    assert r["changements"] == [] and r["sauvegarde"] is None and empreintes(demo) == avant
    assert "Rien à changer" in A.texte_migration(r)


def test_migrer_depuis_le_depart(demo):
    monde = L.charger_monde(demo, "rdc")
    monde.depart_robot = L.Pose(3.0, 10.5, 0.5)
    L.enregistrer_monde(demo, "rdc", monde)
    r = A.migrer_lieu(demo, depuis_depart=True)
    assert A.pose_principale(demo) == L.PoseEtage("rdc", 3.0, 10.5, 0.5) and A.accueil_conforme(demo)
    n = L.charger_itineraires(demo).noeuds["accueil"]
    assert (n.x, n.y) == (3.0, 10.5) and r["avertissements"] == []
    # sans --depuis-depart, un départ différent est cité (il reste dans la sauvegarde)
    monde.depart_robot = L.Pose(4.0, 10.0, 0.0)
    L.enregistrer_monde(demo, "rdc", monde)
    r = A.migrer_lieu(demo)
    assert L.charger_monde(demo, "rdc").depart_robot == L.Pose(3.0, 10.5, 0.5)
    assert any("l'ancien départ du robot (4 ; 10 ; 0)" in m for m in r["avertissements"])


def test_migrer_refuse_la_reference_et_les_lieux_illisibles(demo, tmp_path, monkeypatch):
    assert A.est_reference_des_tests(DEMO) and A.est_reference_des_tests(str(DEMO))
    assert not A.est_reference_des_tests(demo)
    monkeypatch.setenv("ATELIER_LIEUX", str(tmp_path))
    assert not A.est_reference_des_tests("demo")          # « demo » désigne ici la copie
    with pytest.raises(L.ErreurLieu) as e:
        A.migrer_lieu(DEMO)
    assert "référence des tests" in str(e.value)
    (demo / "zones.yaml").write_text("interdites: [\n", encoding="utf-8")
    avant = empreintes(demo)
    with pytest.raises(L.ErreurLieu) as e:
        A.migrer_lieu(demo)
    assert "illisible" in e.value.erreurs[0] and empreintes(demo) == avant
    L.copier_lieu(DEMO, tmp_path / "sans")
    L.enregistrer_salles(tmp_path / "sans", [s for s in L.charger_salles(DEMO) if s.id != "accueil"])
    with pytest.raises(L.ErreurLieu) as e:
        A.migrer_lieu(tmp_path / "sans")
    assert "ni salle étiquetée" in str(e.value)
    with pytest.raises(L.ErreurLieu):
        A.migrer_lieu(tmp_path / "absent")


def _etat_d_avant(source, copie):
    """Copie du lieu de l'utilisateur dans l'état d'avant sa migration : la plus ancienne
    sauvegarde « migration » si elle existe (lieu déjà migré), sinon le lieu tel quel."""
    L.copier_lieu(source, copie)
    sauvegardes = sorted((copie / "sauvegardes").glob("*_migration*")) if (copie / "sauvegardes").is_dir() else []
    if sauvegardes:
        for f in sauvegardes[0].rglob("*.yaml"):
            cible = copie / f.relative_to(sauvegardes[0])
            cible.write_bytes(f.read_bytes())
        for s in sauvegardes:
            shutil.rmtree(s)
    return copie


@pytest.mark.parametrize("nom", ["bomboclat", "demo_scan"])
def test_migrer_une_copie_des_lieux_de_l_utilisateur(tmp_path, nom):
    """bomboclat (le lieu de l'utilisateur) et demo_scan : sur une copie de leur état d'avant la
    migration, g1-lieu migrer donne les mêmes erreurs avant et après, pose l'étiquette sur la salle
    accueil, et un second passage ne change rien. Le vrai lieu n'est que lu."""
    source = RACINE / "lieux" / nom
    if not (source / "lieu.yaml").is_file():
        pytest.skip(f"lieux/{nom} absent")
    avant_source = empreintes(source)
    copie = _etat_d_avant(source, tmp_path / nom)
    assert not A.principal_explicite(copie)
    erreurs_avant = L.valider_lieu(copie).erreurs
    r = A.migrer_lieu(copie)
    assert r["changements"] and r["sauvegarde"]
    assert L.valider_lieu(copie).erreurs == erreurs_avant
    assert A.point_principal(copie).id == "accueil" and A.principal_explicite(copie) and A.accueil_conforme(copie)
    assert A.decrire_principal(copie)["depart_synchro"]
    assert A.migrer_lieu(copie)["changements"] == []
    assert empreintes(source) == avant_source


def test_les_lieux_migres_de_l_utilisateur_sont_intacts():
    """Les vrais lieux migrés (bomboclat, demo_scan) : leur sauvegarde de migration rend les fichiers
    d'avant (lisibles), le lieu est lisible et a son point principal étiqueté. Rien n'est écrit."""
    for nom in ("bomboclat", "demo_scan"):
        dossier = RACINE / "lieux" / nom
        sauvegardes = sorted((dossier / "sauvegardes").glob("*_migration*")) if (dossier / "sauvegardes").is_dir() else []
        if not sauvegardes:
            continue
        L.charger_lieu(dossier)
        assert A.principal_explicite(dossier), nom
        for f in ("lieu.yaml", "salles.yaml", "itineraires.yaml"):
            assert (sauvegardes[0] / f).is_file(), (nom, f)
            lire_yaml((sauvegardes[0] / f).read_text(encoding="utf-8"), f)
        assert list((sauvegardes[0] / "mondes").glob("*.monde.yaml")), nom


# ---------------------------------------------------------------- description et repérage

def test_decrire_principal_et_pose_pour_1804(demo):
    d = A.decrire_principal(demo)
    assert d == {"salle": "accueil", "nom": "Accueil", "etage": "rdc", "x": 2.5, "y": 10.0, "theta": 0.0,
                 "explicite": False, "depart_synchro": True, "repere_unitree": {"x": 2.5, "y": 10.0, "theta": 0.0},
                 "pose_unitree": {"x": 0.0, "y": 0.0, "theta": 0.0}}
    fiche = L.charger_fiche(demo)
    fiche.etages[0].repere_unitree = L.Pose(*REPERE_B)
    L.enregistrer_fiche(fiche)
    u = L.carte_vers_unitree((2.5, 10.0, 0.0), REPERE_B)
    d = A.decrire_principal(demo)
    assert d["repere_unitree"] == {"x": 3.0, "y": 9.0, "theta": 0.5}
    assert all(math.isclose(d["pose_unitree"][k], v, abs_tol=1e-6) for k, v in zip("x y theta".split(), u))
    L.enregistrer_salles(demo, [s for s in L.charger_salles(demo) if s.id != "accueil"])
    assert A.decrire_principal(demo) is None


@pytest.mark.parametrize("repere", [None, REPERE_B])
def test_reperage_par_defaut_coherent_avec_le_relais_et_le_faux_slam(demo, repere):
    """La chaîne du repérage par défaut, sans ROS : le principal déplacé et tourné ; la pose que
    l'Atelier envoie (pose_de_reperage) ; la requête 1804 du relais (g1_nav.reperage, carte_vers_unitree
    avec repere_unitree) ; le faux slam_operate de la répétition l'accepte (le robot proxy est au
    départ de Gazebo, depart_robot = le principal) ; la relocalisation remet le robot sur le principal."""
    sys.path.insert(0, str(RACINE / "ws" / "src" / "g1_nav"))
    from g1_nav.reperage import Reperage
    from atelier.scan.faux_slam import FauxSlamJumeau
    if repere is not None:
        fiche = L.charger_fiche(demo)
        fiche.etages[0].repere_unitree = L.Pose(*repere)
        L.enregistrer_fiche(fiche)
    A.definir_principal(demo, x=2.5, y=11.0, theta=1.5708)
    p = A.pose_de_reperage(demo, "rdc")
    assert (p.x, p.y, p.theta) == (2.5, 11.0, 1.5708)
    verite = A.depart_simulation(demo, "rdc")                     # où le robot proxy apparaît
    depart = L.charger_monde(demo, "rdc").depart_robot
    assert (verite.x, verite.y, verite.theta) == (depart.x, depart.y, depart.theta) == (2.5, 11.0, 1.5708)
    r = L.repere_unitree(demo, "rdc")
    r = (r.x, r.y, r.theta)
    assert r == (repere or (2.5, 11.0, 1.5708))                    # monde dessiné : le repère suit le départ
    horloge = [0.0]
    relais = Reperage(r, L.carte_pour_reperage(demo, repetition=True), horloge=lambda: horloge[0])
    requete = relais.demander({"id": "atelier-1", "x": p.x, "y": p.y, "theta": p.theta})
    attendue = L.carte_vers_unitree((p.x, p.y, p.theta), r)
    assert all(math.isclose(a, b, abs_tol=1e-9) for a, b in zip(requete["pose_unitree"], attendue))
    assert all(math.isclose(a, b, abs_tol=1e-6) for a, b in zip(requete["pose_unitree"],
                                                                  tuple(A.decrire_principal(demo)["pose_unitree"].values())))
    if repere is None:
        assert all(abs(v) < 1e-9 for v in requete["pose_unitree"])  # comme en vague 3 : (0, 0, 0)
    faux = FauxSlamJumeau(r, [L.CARTE_REPETITION])
    faux.deplacement.noter(0.0, (verite.x, verite.y, verite.theta))
    code, texte = faux._traiter(L.API_RELOCALISER, requete["parameter"])
    assert code == 0 and json.loads(texte)["succeed"], texte
    assert relais.sur_reponse(requete["id"], 0, texte)
    relais.sur_odometrie((0.0, 0.0, 0.0), None)
    horloge[0] = 1.0
    relais.sur_relocalisation(faux.deplacement.position(), None, [0.0004] * 36)
    etat = relais.etat()
    assert etat["etat"] == "repere", etat
    assert math.hypot(etat["pose"]["x"] - 2.5, etat["pose"]["y"] - 11.0) < 1e-3
    assert abs(etat["pose"]["theta"] - 1.5708) < 1e-3
    # l'ancienne marque (origine d'Unitree) n'est plus là où est le robot : refus du faux service
    if repere is not None:
        mauvaise = relais.demander({"id": "atelier-2", "x": repere[0], "y": repere[1], "theta": repere[2]})
        code, texte = faux._traiter(L.API_RELOCALISER, mauvaise["parameter"])
        assert not json.loads(texte)["succeed"] and "pas à la position donnée" in json.loads(texte)["info"]


def test_les_commentaires_de_salles_yaml_restent(demo):
    """Quand seules les étiquettes changent (migration, autre salle choisie sans la déplacer), seule la
    ligne « etiquettes » bouge dans salles.yaml : les commentaires et la mise en forme écrits à la main
    restent (le demo a les siens)."""
    original = (demo / "salles.yaml").read_text(encoding="utf-8")
    A.migrer_lieu(demo)
    lignes = original.split("\n")
    i = lignes.index('  phrase_arrivee: "Nous sommes de retour à l\'accueil."')
    attendu = lignes[:i + 1] + ["  etiquettes: [principal]"] + lignes[i + 1:]
    assert (demo / "salles.yaml").read_text(encoding="utf-8") == "\n".join(attendu)
    # le principal passe à b204 (même pose : seules les étiquettes changent dans salles.yaml)
    b204 = L.charger_lieu(demo).salle("b204").pose
    A.definir_principal(demo, salle="b204", x=b204.x, y=b204.y, theta=b204.theta)
    j = lignes.index('  phrase_arrivee: "Voici le labo de physique."')
    attendu = lignes[:j + 1] + ["  etiquettes: [principal]"] + lignes[j + 1:]
    assert (demo / "salles.yaml").read_text(encoding="utf-8") == "\n".join(attendu)
    assert A.point_principal(demo).id == "b204" and L.valider_lieu(demo).erreurs == []
