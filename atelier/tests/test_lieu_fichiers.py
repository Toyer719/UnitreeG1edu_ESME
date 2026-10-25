"""Tests de lecture et d'écriture d'un paquet de lieu (atelier.lieu.fichiers).

  ~/robot-g1/.venv-projet/bin/python -m pytest ~/robot-g1/atelier/tests/test_lieu_fichiers.py -v

Les tests travaillent sur une copie de lieux/demo dans un dossier temporaire.
"""
import os
import stat

import numpy as np
import pytest
import yaml

import atelier
from atelier import lieu as L
from atelier.lieu import ErreurLieu

DEMO = atelier.RACINE / "lieux" / "demo"
FICHIERS_DEMO = ["lieu.yaml", "salles.yaml", "itineraires.yaml", "zones.yaml", "mondes/rdc.monde.yaml"]


@pytest.fixture
def demo(tmp_path):
    """Copie du lieu demo, dans un dossier temporaire."""
    return L.copier_lieu(DEMO, tmp_path / "demo")


def lire_brut(chemin):
    return yaml.safe_load(chemin.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- lieu complet

def test_charger_le_demo(demo):
    lieu = L.charger_lieu(demo)
    assert lieu.nom == "Lycée démo" and lieu.id == "demo" and lieu.dossier == demo
    assert [e.id for e in lieu.etages] == ["rdc"]
    assert len(lieu.salles) == 6 and lieu.salle("b204").pose.theta == pytest.approx(1.5708)
    assert len(lieu.itineraires.noeuds) == 13 and len(lieu.itineraires.couloirs) == 13
    assert len(lieu.zones.interdites) == 1 and len(lieu.zones.lentes) == 1
    monde = lieu.mondes["rdc"]
    assert (len(monde.murs), len(monde.objets), len(monde.pietons)) == (18, 9, 2)


def test_charger_par_id(demo, monkeypatch):
    monkeypatch.setenv("ATELIER_LIEUX", str(demo.parent))
    assert L.charger_lieu("demo").dossier == demo
    assert L.dossier_lieu("demo") == demo
    assert L.lister_lieux() == [demo]


def test_aller_retour_du_lieu_complet(demo):
    avant = L.charger_lieu(demo)
    L.enregistrer_lieu(avant)
    apres = L.charger_lieu(demo)
    assert apres == avant
    for nom in FICHIERS_DEMO:
        assert lire_brut(demo / nom) == lire_brut(DEMO / nom), nom


def test_enregistrer_ailleurs(demo, tmp_path):
    lieu = L.charger_lieu(demo)
    destination = L.enregistrer_lieu(lieu, tmp_path / "autre")
    assert destination == tmp_path / "autre" and lieu.dossier == destination
    assert L.charger_lieu(destination).salles == L.charger_lieu(demo).salles


def test_rien_n_est_ecrit_si_le_lieu_est_invalide(demo):
    lieu = L.charger_lieu(demo)
    avant = {nom: (demo / nom).read_bytes() for nom in FICHIERS_DEMO}
    lieu.nom = "Lycée modifié"                         # valide
    lieu.salles[0].pose.theta = 10.0                   # invalide : plus de 2π
    with pytest.raises(ErreurLieu) as e:
        L.enregistrer_lieu(lieu)
    assert "salles.yaml, salle « accueil » : pose.theta vaut 10" in str(e.value)
    assert {nom: (demo / nom).read_bytes() for nom in FICHIERS_DEMO} == avant


def test_erreurs_de_plusieurs_fichiers_reunies(demo):
    (demo / "salles.yaml").write_text("- {id: b204, nom: B204, etage: rdc, pose: {x: 1, y: 2}}\n", encoding="utf-8")
    zones = lire_brut(demo / "zones.yaml")
    zones["lentes"][0].pop("vitesse_max")
    (demo / "zones.yaml").write_text(yaml.safe_dump(zones, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ErreurLieu) as e:
        L.charger_lieu(demo)
    assert e.value.erreurs == [
        "salles.yaml, salle « b204 » : il manque theta dans pose",
        "zones.yaml, zone lente n°1 (« Hall d'accueil ») : il manque vitesse_max"]


def test_fichiers_absents_pris_comme_vides(demo):
    for nom in ("salles.yaml", "itineraires.yaml", "zones.yaml"):
        (demo / nom).unlink()
    lieu = L.charger_lieu(demo)
    assert lieu.salles == [] and lieu.itineraires == L.Itineraires() and lieu.zones == L.Zones()


def test_dossier_qui_n_est_pas_un_lieu(tmp_path):
    with pytest.raises(ErreurLieu, match="n'existe pas"):
        L.charger_lieu(tmp_path / "rien")
    (tmp_path / "vide").mkdir()
    with pytest.raises(ErreurLieu, match="pas de lieu.yaml"):
        L.charger_lieu(tmp_path / "vide")


# ---------------------------------------------------------------- fichier par fichier

def test_aller_retour_salles(demo):
    salles = L.charger_salles(demo)
    salles.append(L.Salle("labo_2", "Labo 2", "rdc", L.Pose(3.0, 4.0, -1.0), ["labo : chimie"], "Voici : le labo."))
    L.enregistrer_salles(demo, salles)
    assert L.charger_salles(demo) == salles


def test_aller_retour_itineraires(demo):
    itin = L.charger_itineraires(demo)
    itin.noeuds["nouveau"] = L.Noeud("rdc", 4.0, 7.0)
    itin.couloirs.append(L.Couloir("hall_sud", "nouveau"))
    L.enregistrer_itineraires(demo, itin)
    assert L.charger_itineraires(demo) == itin


def test_aller_retour_zones(demo):
    zones = L.charger_zones(demo)
    zones.interdites.append(L.Zone("rdc", [(10.0, 0.5), (12.0, 0.5), (12.0, 1.0)]))
    L.enregistrer_zones(demo, zones)
    assert L.charger_zones(demo) == zones


def test_aller_retour_monde(demo):
    monde = L.charger_monde(demo, "rdc")
    monde.objets.append(L.Objet.meuble("chaise_3", "chaise", (3.0, 3.0), 0.5))
    monde.pietons[0].vitesse = 1.2
    L.enregistrer_monde(demo, "rdc", monde)
    assert L.charger_monde(demo, "rdc") == monde
    with pytest.raises(ErreurLieu, match="introuvable"):
        L.charger_monde(demo, "etage1")


def test_aller_retour_fiche(demo):
    lieu = L.charger_fiche(demo)
    lieu.etages.append(L.Etage("etage1", "1er étage", "scan"))
    lieu.carte_unitree = "lycee.pcd"
    L.enregistrer_fiche(lieu)
    relu = L.charger_fiche(demo)
    assert relu.etages == lieu.etages and relu.carte_unitree == "lycee.pcd"


def test_aller_retour_info_carte_et_image(tmp_path):
    info = L.info_carte_pour_emprise(0, 0, 3, 2, 0.05, image="rdc.pgm")
    image = np.full((info.hauteur, info.largeur), 254, dtype=np.uint8)
    image[0, :] = 0
    image[-1, 5] = 205
    chemin = tmp_path / "cartes" / "rdc.yaml"
    L.enregistrer_carte(chemin, info, image)
    assert (tmp_path / "cartes" / "rdc.pgm").read_bytes().startswith(b"P5\n")
    relue_info, relue = L.charger_carte(chemin)
    assert (relue == image).all() and relue.dtype == np.uint8
    assert relue_info == info and relue_info.chemin == chemin
    assert set(lire_brut(chemin)) == {"image", "resolution", "origin", "negate", "occupied_thresh", "free_thresh"}
    L.enregistrer_info_carte(tmp_path / "cartes" / "copie.yaml", relue_info)
    assert L.charger_info_carte(tmp_path / "cartes" / "copie.yaml").vers_dict() == info.vers_dict()


def test_pgm_texte_avec_commentaire(tmp_path):
    (tmp_path / "a.pgm").write_bytes(b"P2\n# un commentaire\n3 2\n255\n0 254 205\n1 2 3\n")
    assert L.taille_pgm(tmp_path / "a.pgm") == (3, 2)
    assert L.lire_pgm(tmp_path / "a.pgm").tolist() == [[0, 254, 205], [1, 2, 3]]


def test_pgm_refuse(tmp_path):
    with pytest.raises(ValueError, match="2 dimensions"):
        L.ecrire_pgm(tmp_path / "a.pgm", np.zeros(5))
    with pytest.raises(ValueError, match="0 à 255"):
        L.ecrire_pgm(tmp_path / "a.pgm", np.full((2, 2), 300))
    (tmp_path / "b.pgm").write_bytes(b"P6\n1 1\n255\n\x00\x00\x00")
    with pytest.raises(ValueError, match="pas une image PGM"):
        L.lire_pgm(tmp_path / "b.pgm")


def test_info_carte_sans_image(tmp_path):
    (tmp_path / "rdc.yaml").write_text("image: rdc.pgm\nresolution: 0.05\norigin: [0, 0, 0]\nnegate: 0\n"
                                       "occupied_thresh: 0.65\nfree_thresh: 0.196\n", encoding="utf-8")
    with pytest.raises(ErreurLieu, match="rdc.pgm est introuvable"):
        L.charger_info_carte(tmp_path / "rdc.yaml")


# ---------------------------------------------------------------- écriture atomique et YAML

def test_ecriture_atomique_sans_fichier_temporaire_restant(demo):
    L.enregistrer_lieu(L.charger_lieu(demo))
    assert not [p for p in demo.rglob("*") if p.name.endswith(".tmp")]
    mode = stat.S_IMODE((demo / "salles.yaml").stat().st_mode)
    assert mode == stat.S_IMODE((DEMO / "salles.yaml").stat().st_mode)


def test_droits_d_un_nouveau_fichier(tmp_path):
    L.ecrire_atomique(tmp_path / "x" / "nouveau.txt", "bonjour")
    assert (tmp_path / "x" / "nouveau.txt").read_text() == "bonjour"
    assert stat.S_IMODE((tmp_path / "x" / "nouveau.txt").stat().st_mode) == 0o644


def test_ecriture_interrompue_garde_l_ancien_fichier(tmp_path, monkeypatch):
    chemin = tmp_path / "f.yaml"
    chemin.write_text("ancien\n")

    def panne(*args):
        raise OSError("disque plein")
    monkeypatch.setattr(os, "replace", panne)
    with pytest.raises(OSError):
        L.ecrire_atomique(chemin, "nouveau\n")
    assert chemin.read_text() == "ancien\n"
    assert [p.name for p in tmp_path.iterdir()] == ["f.yaml"]


def test_yaml_garde_les_textes_ambigus(demo):
    """« yes », « 204 » et un texte avec « : » restent des textes après écriture."""
    salles = [L.Salle("yes", "204", "rdc", L.Pose(1, 2, 0), ["on", "off"], "Attention : marche")]
    L.enregistrer_salles(demo, salles)
    brut = lire_brut(demo / "salles.yaml")
    assert brut[0]["id"] == "yes" and brut[0]["nom"] == "204" and brut[0]["alias"] == ["on", "off"]
    assert L.charger_salles(demo) == salles


def test_yaml_lisible(demo):
    L.enregistrer_lieu(L.charger_lieu(demo))
    texte = (demo / "itineraires.yaml").read_text(encoding="utf-8")
    assert texte.startswith("# Graphe des itinéraires")
    assert "  accueil: {etage: rdc, x: 2.5, y: 10.0}\n" in texte
    assert "- [accueil, hall_sud]\n" in texte
    assert "- {id: ext_sud, de: [0.0, 0.0], a: [30.0, 0.0], epaisseur: 0.2, hauteur: 2.5}\n" in \
        (demo / "mondes" / "rdc.monde.yaml").read_text(encoding="utf-8")


def test_cle_en_double_refusee(demo):
    (demo / "itineraires.yaml").write_text(
        "noeuds:\n  a: {etage: rdc, x: 1, y: 1}\n  a: {etage: rdc, x: 2, y: 2}\ncouloirs: []\n", encoding="utf-8")
    with pytest.raises(ErreurLieu) as e:
        L.charger_itineraires(demo)
    assert str(e.value) == ("itineraires.yaml, ligne 3, colonne 3 : la clé « a » apparaît deux fois ; "
                            "gardez-en une seule")


def test_syntaxe_yaml_ligne_indiquee(demo):
    (demo / "zones.yaml").write_text("interdites: [\nlentes: []\n", encoding="utf-8")
    with pytest.raises(ErreurLieu, match=r"zones.yaml, ligne \d+, colonne \d+ : .*Vérifiez l'indentation"):
        L.charger_zones(demo)


def test_fichier_vide(demo):
    (demo / "salles.yaml").write_text("# rien\n", encoding="utf-8")
    with pytest.raises(ErreurLieu, match=r"salles.yaml : le fichier est vide ; s'il n'y a encore aucune salle, "
                                         r"écrivez \[\]"):
        L.charger_salles(demo)


def test_fichier_pas_en_utf8(demo):
    (demo / "salles.yaml").write_bytes("- id: caf\xe9\n".encode("latin-1"))
    with pytest.raises(ErreurLieu, match="UTF-8"):
        L.charger_salles(demo)


# ---------------------------------------------------------------- créer, copier

def test_creer_lieu(tmp_path, monkeypatch):
    monkeypatch.setenv("ATELIER_LIEUX", str(tmp_path))
    lieu = L.creer_lieu("essai", "Lycée essai")
    assert lieu.dossier == tmp_path / "essai"
    relu = L.charger_lieu("essai")
    assert relu == lieu
    assert relu.salles[0].id == "accueil" and "accueil" in relu.itineraires.noeuds
    assert len(relu.mondes["rdc"].murs) == 4
    assert relu.mondes["rdc"].emprise == L.Emprise(0, 0, 20, 15)
    rapport = L.valider_lieu("essai")
    assert rapport.erreurs == []


def test_creer_lieu_refuse(tmp_path):
    L.creer_lieu(tmp_path / "essai", "Essai")
    with pytest.raises(ErreurLieu, match="existe déjà"):
        L.creer_lieu(tmp_path / "essai", "Essai")
    with pytest.raises(ErreurLieu, match="identifiant de lieu valable"):
        L.creer_lieu(tmp_path / "Mon Lieu", "Essai")
    with pytest.raises(ErreurLieu, match="trop petit"):
        L.creer_lieu(tmp_path / "petit", "Petit", largeur=2)
    with pytest.raises(ErreurLieu, match="nom ne doit pas être vide"):
        L.creer_lieu(tmp_path / "sans_nom", "")
    assert not (tmp_path / "sans_nom" / "lieu.yaml").exists()


def test_copier_lieu(tmp_path):
    copie = L.copier_lieu(DEMO, tmp_path / "copie")

    def contenu(dossier):
        return sorted(f.relative_to(dossier).as_posix() for f in dossier.rglob("*") if f.is_file())
    # tout le paquet est copié : fichiers écrits à la main et fichiers générés (cartes, SDF)
    assert contenu(copie) == contenu(DEMO)
    assert set(FICHIERS_DEMO) <= set(contenu(copie))
    with pytest.raises(ErreurLieu, match="existe déjà"):
        L.copier_lieu(DEMO, tmp_path / "copie")


def test_chemins_d_un_lieu(demo):
    lieu = L.charger_lieu(demo)
    assert L.chemin_monde(lieu, "rdc") == demo / "mondes" / "rdc.monde.yaml"
    assert L.chemin_sdf(demo, "rdc") == demo / "mondes" / "rdc.sdf"
    assert L.chemin_carte(demo, "rdc") == demo / "cartes" / "rdc.yaml"
    assert L.chemin_interdit(demo, "rdc") == demo / "cartes" / "rdc_interdit.yaml"
    assert L.chemin_lent(demo, "rdc") == demo / "cartes" / "rdc_lent.yaml"
    assert L.chemin_pcd(demo, "rdc") == demo / "cartes" / "rdc.pcd"
