"""Tests de la vérification d'un lieu entier (atelier.lieu.verification) : règles entre fichiers,
géométrie du graphe, cartes et masques.

  ~/robot-g1/.venv-projet/bin/python -m pytest ~/robot-g1/atelier/tests/test_lieu_verification.py -v

Les tests travaillent sur une copie de lieux/demo dans un dossier temporaire.
"""
import os

import numpy as np
import pytest

import atelier
from atelier import lieu as L

DEMO = atelier.RACINE / "lieux" / "demo"
SANS_CARTE = ("étage « rdc » : pas encore de carte (cartes/rdc.yaml) ; fabriquez-la : "
              "g1-monde generer --lieu demo --etage rdc")
SANS_MASQUE = ("étage « rdc » : pas de masque des zones interdites (cartes/rdc_interdit.yaml) ; fabriquez-le : "
               "g1-monde generer --lieu demo --etage rdc")


@pytest.fixture
def demo(tmp_path):
    """Le lieu demo chargé depuis une copie temporaire."""
    return L.charger_lieu(L.copier_lieu(DEMO, tmp_path / "demo"))


def un_message(liste, *morceaux):
    """Vrai si un message de la liste contient tous les morceaux."""
    return any(all(m in message for m in morceaux) for message in liste)


def test_le_demo_est_valide(demo):
    # le demo est livré avec sa carte et son masque (g1-monde generer) : aucun avertissement
    rapport = L.verifier_lieu(demo)
    assert rapport.erreurs == []
    assert rapport.avertissements == []
    assert rapport.ok and rapport.lieu is demo
    # sans ses fichiers générés, il signale la carte manquante
    for fichier in (demo.dossier / "cartes").iterdir():
        fichier.unlink()
    assert L.verifier_lieu(demo).avertissements == [SANS_CARTE]
    assert L.valider_lieu(DEMO).erreurs == []


# ---------------------------------------------------------------- salles et nœuds

def test_salle_sans_noeud(demo):
    itin = demo.itineraires
    del itin.noeuds["b204"]
    itin.couloirs = [c for c in itin.couloirs if "b204" not in (c.a, c.b)]
    assert L.verifier_lieu(demo).erreurs == [
        "salles.yaml, salle « b204 » : il n'y a pas de nœud « b204 » dans itineraires.yaml ; ajoutez dans "
        "noeuds : b204: {etage: rdc, x: 21, y: 13}"]


def test_noeud_de_salle_deplace(demo):
    demo.itineraires.noeuds["b204"].x = 21.5
    assert un_message(L.verifier_lieu(demo).erreurs, "salle « b204 »", "pas au même endroit",
                      "salle : rdc [21, 13] ; nœud : rdc [21.5, 13]")


def test_accueil_different_de_lieu_yaml(demo):
    demo.salle("accueil").pose.theta = 1.0
    assert un_message(L.verifier_lieu(demo).erreurs, "salle « accueil » : sa pose doit être celle de accueil")


def test_pas_de_salle_accueil(demo):
    # Vague 4 (section 11.2 du plan) : sans étiquette « principal » ni salle « accueil », le lieu n'a pas
    # de point principal, et c'est une erreur (avant : un avertissement)
    demo.salles = [s for s in demo.salles if s.id != "accueil"]
    assert un_message(L.verifier_lieu(demo).erreurs, "le lieu n'a pas de point principal")


def test_etage_inconnu(demo):
    demo.salle("cdi").etage = "r2"
    demo.itineraires.noeuds["est_sud"].etage = "r2"
    demo.zones.lentes[0].etage = "r2"
    erreurs = L.verifier_lieu(demo).erreurs
    assert un_message(erreurs, "salles.yaml, salle « cdi » : l'étage « r2 » n'existe pas dans lieu.yaml")
    assert un_message(erreurs, "itineraires.yaml, nœud « est_sud » : l'étage « r2 » n'existe pas")
    assert un_message(erreurs, "zones.yaml, zone lente n°1 (« Hall d'accueil ») : l'étage « r2 » n'existe pas")


# ---------------------------------------------------------------- couloirs

def test_couloir_trop_long(demo):
    demo.itineraires.couloirs.append(L.Couloir("couloir_sud_1", "cdi"))
    assert L.verifier_lieu(demo).erreurs == [
        "itineraires.yaml, couloir n°14 [couloir_sud_1, cdi] : 12.00 m, plus de 8 m ; ajoutez un nœud entre les "
        "deux (le vrai robot navigue par tronçons de 8 m au plus)"]


def test_couloir_qui_traverse_un_mur(demo):
    demo.itineraires.couloirs.append(L.Couloir("vie_scolaire", "amphi"))
    assert un_message(L.verifier_lieu(demo).erreurs, "couloir n°14 [vie_scolaire, amphi] : il traverse le mur « bloc_",
                      "ajoutez un nœud pour le contourner")


def test_couloir_sur_deux_etages(demo):
    demo.etages.append(L.Etage("etage1", "1er étage", "scan"))
    demo.itineraires.noeuds["palier"] = L.Noeud("etage1", 2.5, 7.0)
    demo.itineraires.couloirs.append(L.Couloir("hall_sud", "palier"))
    assert un_message(L.verifier_lieu(demo).erreurs, "couloir n°14 [hall_sud, palier] : ses nœuds sont sur deux "
                      "étages (rdc et etage1)")


def test_noeud_dans_un_objet_et_noeud_trop_pres(demo):
    demo.itineraires.noeuds["hall_sud"] = L.Noeud("rdc", 0.7, 10.0)          # dans la banque d'accueil
    demo.itineraires.noeuds["couloir_sud_1"] = L.Noeud("rdc", 11.0, 5.9)     # à 0,33 m du mur
    rapport = L.verifier_lieu(demo)
    assert un_message(rapport.erreurs, "nœud « hall_sud » : il est dans l'objet « banque_accueil »")
    assert un_message(rapport.avertissements, "nœud « couloir_sud_1 » : à 0.33 m du mur « mur_sud_2 »",
                      "moins que le rayon du robot (0.35 m)")


def test_graphe_coupe_en_deux(demo):
    itin = demo.itineraires
    itin.couloirs = [c for c in itin.couloirs if (c.a, c.b) not in (("cdi", "est_sud"), ("amphi", "hall_nord"))]
    avertissements = L.verifier_lieu(demo).avertissements
    assert un_message(avertissements, "salle « b204 » : aucun chemin depuis l'accueil")
    assert un_message(avertissements, "salle « amphi » : aucun chemin depuis l'accueil")
    assert not un_message(avertissements, "salle « cdi » : aucun chemin")


def test_noeud_isole_et_couloir_en_double(demo):
    demo.itineraires.noeuds["seul"] = L.Noeud("rdc", 12.0, 13.0)
    demo.itineraires.couloirs.append(L.Couloir("b204", "est_nord"))
    avertissements = L.verifier_lieu(demo).avertissements
    assert un_message(avertissements, "nœud « seul » : il n'est relié à aucun couloir")
    assert un_message(avertissements, "couloir n°14 [b204, est_nord] : couloir en double")


def test_id_lu_comme_booleen(demo):
    demo.itineraires.noeuds["yes"] = L.Noeud("rdc", 12.0, 13.0)
    demo.itineraires.couloirs.append(L.Couloir("yes", "couloir_nord_1"))
    assert un_message(L.verifier_lieu(demo).avertissements, "nœud « yes » : l'id « yes » est lu comme oui ou non")


# ---------------------------------------------------------------- zones et monde

def test_zone_interdite_sur_le_graphe(demo):
    demo.zones.interdites.append(L.Zone("rdc", [(2.0, 6.5), (3.0, 6.5), (3.0, 7.5), (2.0, 7.5)], "Travaux"))
    erreurs = L.verifier_lieu(demo).erreurs
    assert un_message(erreurs, "zone interdite n°2 (« Travaux ») : le nœud « hall_sud » est dedans")
    assert un_message(erreurs, "zone interdite n°2 (« Travaux ») : le couloir [accueil, hall_sud] la traverse")


def test_depart_du_robot_dans_un_mur(demo):
    demo.mondes["rdc"].depart_robot = L.Pose(5.0, 10.0, 0.0)
    assert un_message(L.verifier_lieu(demo).erreurs, "depart_robot : le robot apparaîtrait dans le mur « bloc_ouest »")


def test_pieton_qui_traverse_un_mur(demo):
    demo.mondes["rdc"].pietons[1].trajet = [(6.0, 13.8), (6.0, 16.0)]
    assert un_message(L.verifier_lieu(demo).avertissements, "piéton « pieton_nord » : son trajet [6, 13.8] → [6, 16] "
                      "traverse le mur « mur_nord_1 »")


def test_monde_manquant_ou_orphelin(demo):
    monde = demo.mondes.pop("rdc")
    assert un_message(L.verifier_lieu(demo).avertissements, "étage « rdc » : pas encore de monde")
    demo.mondes["r9"] = monde
    assert un_message(L.verifier_lieu(demo).avertissements, "l'étage « r9 » n'existe pas dans lieu.yaml ; "
                      "ce monde est ignoré")


# ---------------------------------------------------------------- cartes et masques

def ecrire_carte(lieu, valeur=254, suffixe=""):
    """Carte (ou masque) de la taille de l'emprise du demo, remplie d'une seule valeur."""
    info = L.info_carte_pour_emprise(0, 0, 30, 20, 0.05, image=f"rdc{suffixe}.pgm")
    image = np.full((info.hauteur, info.largeur), valeur, dtype=np.uint8)
    L.enregistrer_carte(lieu.dossier / "cartes" / f"rdc{suffixe}.yaml", info, image)
    return info, image


def test_carte_et_masque_corrects(demo):
    ecrire_carte(demo)
    ecrire_carte(demo, 254, "_interdit")
    rapport = L.verifier_lieu(demo)
    assert rapport.erreurs == [] and rapport.avertissements == []


def test_masque_absent(demo):
    ecrire_carte(demo)
    for fichier in (demo.dossier / "cartes").glob("rdc_interdit.*"):
        fichier.unlink()
    assert L.verifier_lieu(demo).avertissements == [SANS_MASQUE]


def test_masque_d_une_autre_taille(demo):
    ecrire_carte(demo)
    info = L.info_carte_pour_emprise(0, 0, 20, 20, 0.05, image="rdc_interdit.pgm")
    L.enregistrer_carte(demo.dossier / "cartes" / "rdc_interdit.yaml", info,
                        np.full((info.hauteur, info.largeur), 254, dtype=np.uint8))
    assert un_message(L.verifier_lieu(demo).erreurs, "cartes/rdc_interdit.yaml : le masque doit avoir la même taille",
                      "402 × 402 px", "602 × 402 px")


def test_carte_plus_ancienne_que_le_monde(demo):
    ecrire_carte(demo)
    ecrire_carte(demo, 254, "_interdit")
    vieux = os.stat(demo.dossier / "mondes" / "rdc.monde.yaml").st_mtime - 3600
    os.utime(demo.dossier / "cartes" / "rdc.yaml", (vieux, vieux))
    assert un_message(L.verifier_lieu(demo).avertissements, "cartes/rdc.yaml : plus ancienne que mondes/rdc.monde.yaml")


def test_etage_scanne_graphe_sur_la_carte(demo):
    """Étage scanné : les nœuds et couloirs se vérifient sur les pixels de la carte."""
    demo.etages[0].source_carte = "scan"
    del demo.mondes["rdc"]
    info, image = ecrire_carte(demo)
    ecrire_carte(demo, 254, "_interdit")
    colonne, _ = L.monde_vers_pixel(13.0, 7.0, info)
    image[:, colonne] = 0                                     # obstacle au milieu du couloir sud
    c_b204, l_b204 = L.monde_vers_pixel(21.0, 13.0, info)
    image[l_b204, c_b204] = 205                               # b204 dans une partie inconnue
    L.enregistrer_carte(demo.dossier / "cartes" / "rdc.yaml", info, image)
    demo.itineraires.noeuds["hors_carte"] = L.Noeud("rdc", 40.0, 7.0)
    demo.itineraires.couloirs.append(L.Couloir("est_sud", "hors_carte"))
    rapport = L.verifier_lieu(demo)
    assert un_message(rapport.erreurs, "couloir n°4 [couloir_sud_1, infirmerie] : il traverse un obstacle de la carte "
                      "cartes/rdc.yaml")
    assert un_message(rapport.erreurs, "nœud « hors_carte » : [40, 7] est hors de la carte cartes/rdc.yaml")
    assert un_message(rapport.avertissements, "nœud « b204 » : [21, 13] est dans une partie inconnue de la carte")
    assert not un_message(rapport.erreurs, "couloir n°3 [vie_scolaire, couloir_sud_1]")


def test_etage_scanne_noeud_trop_pres_d_un_obstacle(demo):
    """Revue de la vague 5 (salle 3 de la séance, à 0,25 m d'un objet bas) : sur une carte scannée, un nœud
    (et sa salle) à moins du rayon du robot d'un pixel occupé est signalé ; plus loin, rien."""
    demo.etages[0].source_carte = "scan"
    del demo.mondes["rdc"]
    info, image = ecrire_carte(demo)
    ecrire_carte(demo, 254, "_interdit")
    n = demo.itineraires.noeuds["b204"]
    c, l = L.monde_vers_pixel(n.x + 0.25, n.y, info)          # un obstacle à 0,25 m de la salle b204
    image[l, c] = 0
    L.enregistrer_carte(demo.dossier / "cartes" / "rdc.yaml", info, image)
    d = L.verification.distance_obstacle_carte(n.x, n.y, info, image)
    assert d is not None and abs(d - 0.25) < info.resolution
    rapport = L.verifier_lieu(demo)
    assert un_message(rapport.avertissements, "nœud « b204 » (et sa salle) : à 0.2", "moins que le rayon du robot (0.35 m)")
    assert not un_message(rapport.avertissements, "nœud « cdi »", "moins que le rayon")
    # l'obstacle à 0,6 m : plus d'avertissement
    image[l, c] = 254
    c, l = L.monde_vers_pixel(n.x + 0.6, n.y, info)
    image[l, c] = 0
    L.enregistrer_carte(demo.dossier / "cartes" / "rdc.yaml", info, image)
    assert not un_message(L.verifier_lieu(demo).avertissements, "nœud « b204 »", "rayon du robot")


# ---------------------------------------------------------------- valider_lieu sur un dossier

def test_valider_dossier_absent_ou_pas_un_lieu(tmp_path):
    assert un_message(L.valider_lieu(tmp_path / "rien").erreurs, "n'existe pas", "g1-lieu creer")
    (tmp_path / "vide").mkdir()
    assert un_message(L.valider_lieu(tmp_path / "vide").erreurs, "pas de lieu.yaml")


def test_valider_fichier_casse(tmp_path):
    dossier = L.copier_lieu(DEMO, tmp_path / "demo")
    (dossier / "salles.yaml").write_text("- id: b204\n  nom: B204\n", encoding="utf-8")
    rapport = L.valider_lieu(dossier)
    assert rapport.erreurs == ["salles.yaml, salle « b204 » : il manque etage",
                               "salles.yaml, salle « b204 » : il manque pose"]
    assert un_message(rapport.avertissements, "seront faites une fois ces erreurs corrigées")
    assert not rapport.ok and rapport.lieu is None


def test_valider_fichiers_absents_et_monde_orphelin(tmp_path):
    dossier = L.copier_lieu(DEMO, tmp_path / "Mon_Lieu")
    (dossier / "zones.yaml").unlink()
    (dossier / "mondes" / "rdc.monde.yaml").rename(dossier / "mondes" / "r9.monde.yaml")
    avertissements = L.valider_lieu(dossier).avertissements
    assert un_message(avertissements, "zones.yaml : fichier absent, pris comme vide")
    assert un_message(avertissements, "mondes/r9.monde.yaml : l'étage « r9 » n'existe pas dans lieu.yaml")
    assert un_message(avertissements, "le nom du dossier « Mon_Lieu » n'est pas un identifiant de lieu valable")


def test_critere_1_monde_invente(tmp_path):
    """Critère de recette 1 : un lieu essai avec 6 murs, un passage, 3 objets et 2 piétons est valide."""
    lieu = L.creer_lieu(tmp_path / "essai", "Lycée essai", largeur=12, profondeur=8)
    monde = lieu.mondes["rdc"]
    monde.murs += [L.Mur("cloison_a", (0.0, 4.0), (5.0, 4.0), 0.15, 2.5),
                   L.Mur("cloison_b", (6.0, 4.0), (12.0, 4.0), 0.15, 2.5)]       # passage de 1 m
    monde.objets += [L.Objet.boite("table_1", (3.0, 2.0), (1.2, 0.6, 0.75), 0.0),
                     L.Objet.cylindre("poteau", (9.0, 2.0), 0.2, 2.5),
                     L.Objet.meuble("chaise_1", "chaise", (3.0, 6.0), 1.57)]
    monde.pietons += [L.Pieton("h1", [(1.5, 3.0), (10.0, 3.0)], 1.0, True),
                      L.Pieton("h2", [(2.0, 5.5), (10.0, 5.5), (10.0, 7.0)], 0.8, False)]
    L.enregistrer_lieu(lieu)
    rapport = L.valider_lieu(lieu.dossier)
    assert rapport.erreurs == []
    assert len(L.charger_monde(lieu, "rdc").murs) == 6
