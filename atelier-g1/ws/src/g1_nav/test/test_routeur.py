"""
Tests du routeur (A* et couloirs bloqués) sur une copie du lieu demo, sans ROS.

  python3 -m pytest ~/robot-g1/ws/src/g1_nav/test/test_routeur.py -v
"""
import math

from atelier import RACINE
from atelier.lieu import copier_lieu
from g1_nav.routeur import CibleInconnue, DUREE_BLOCAGE_S, Routeur
import pytest

NORD = ['accueil', 'hall_nord', 'amphi', 'couloir_nord_1', 'b204']


class Horloge:
    """Fausse horloge : le test fait avancer le temps à la main."""

    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def horloge():
    return Horloge()


@pytest.fixture
def routeur(tmp_path, horloge):
    dossier = copier_lieu(RACINE / 'lieux' / 'demo', tmp_path / 'demo')
    return Routeur.depuis_lieu(dossier, 'rdc', horloge=horloge)


def test_chargement_demo(routeur):
    assert len(routeur.noeuds) == 13
    assert routeur.voisins['accueil'] == {'hall_sud', 'hall_nord'}
    assert routeur.noeuds['b204'] == (21.0, 13.0)
    assert 'b204' in routeur.salles


def test_plus_court_chemin_par_le_nord(routeur):
    chemin = routeur.itineraire('accueil', 'b204')
    assert chemin == NORD
    assert routeur.longueur(chemin) == pytest.approx(21.5)


def test_chemin_vers_le_sud(routeur):
    chemin = routeur.itineraire('accueil', 'cdi')
    assert chemin == ['accueil', 'hall_sud', 'vie_scolaire', 'couloir_sud_1', 'infirmerie',
                      'couloir_sud_2', 'cdi']


def test_meme_noeud(routeur):
    assert routeur.itineraire('amphi', 'amphi') == ['amphi']


def test_couloir_bloque_donne_le_chemin_de_secours(routeur):
    routeur.bloquer('amphi', 'couloir_nord_1')
    chemin = routeur.itineraire('accueil', 'b204')
    assert chemin[:2] == ['accueil', 'hall_sud']
    assert chemin[-3:] == ['est_sud', 'est_nord', 'b204']
    assert routeur.longueur(chemin) == pytest.approx(40.5)
    # Le blocage vaut dans les deux sens
    assert routeur.est_bloque('couloir_nord_1', 'amphi')


def test_blocage_expire_apres_120_s(routeur, horloge):
    assert DUREE_BLOCAGE_S == 120.0
    routeur.bloquer('couloir_nord_1', 'amphi')
    horloge.t += 119.0
    assert routeur.itineraire('accueil', 'b204') != NORD
    assert routeur.couloirs_bloques()[0][:2] == ('amphi', 'couloir_nord_1')
    horloge.t += 1.5
    assert routeur.itineraire('accueil', 'b204') == NORD
    assert routeur.couloirs_bloques() == []


def test_duree_de_blocage_au_choix(routeur, horloge):
    routeur.bloquer('amphi', 'couloir_nord_1', duree=5.0)
    horloge.t += 6.0
    assert not routeur.est_bloque('amphi', 'couloir_nord_1')


def test_debloquer(routeur):
    routeur.bloquer('amphi', 'couloir_nord_1')
    routeur.bloquer('cdi', 'est_sud')
    routeur.debloquer('couloir_nord_1', 'amphi')
    assert routeur.itineraire('accueil', 'b204') == NORD
    routeur.debloquer()
    assert routeur.couloirs_bloques() == []


def test_aucun_chemin_si_les_deux_couloirs_sont_bloques(routeur):
    routeur.bloquer('amphi', 'couloir_nord_1')
    routeur.bloquer('infirmerie', 'couloir_sud_2')
    assert routeur.itineraire('accueil', 'b204') is None


def test_bloquer_un_couloir_qui_n_existe_pas(routeur):
    with pytest.raises(ValueError):
        routeur.bloquer('accueil', 'b204')


def test_cibles(routeur):
    assert routeur.resoudre('b204') == 'b204'
    assert routeur.resoudre(' couloir_nord_1 ') == 'couloir_nord_1'
    assert routeur.resoudre('Labo de physique') == 'b204'    # alias de salle
    with pytest.raises(CibleInconnue):
        routeur.resoudre('salle_inexistante')
    with pytest.raises(CibleInconnue):
        routeur.itineraire('accueil', 'salle_inexistante')


def test_noeud_proche(routeur):
    assert routeur.noeud_proche(2.6, 9.8) == 'accueil'
    assert routeur.noeud_proche(11.5, 13.2) == 'amphi'
    assert routeur.noeud_proche(20.0, 7.5) == 'couloir_sud_2'


def test_poses(routeur):
    poses = routeur.poses(NORD)
    assert len(poses) == 5
    # accueil → hall_nord : vers le nord ; hall_nord → amphi : vers l'est
    assert poses[0] == pytest.approx((2.5, 10.0, math.pi / 2))
    assert poses[1] == pytest.approx((2.5, 13.0, 0.0))
    # La dernière pose est celle de la salle, tournée vers la porte
    assert poses[-1] == pytest.approx((21.0, 13.0, 1.5708))
    assert routeur.poses(NORD, sauter_depart=True) == poses[1:]
    assert routeur.poses(['amphi'], sauter_depart=True) == [pytest.approx((9.0, 13.0, 1.5708))]


def test_noeud_sans_salle_garde_le_sens_de_la_marche(routeur):
    poses = routeur.poses(['accueil', 'hall_nord', 'amphi', 'couloir_nord_1'])
    assert poses[-1] == pytest.approx((15.0, 13.0, 0.0))


def test_autre_etage_vide(tmp_path):
    dossier = copier_lieu(RACINE / 'lieux' / 'demo', tmp_path / 'demo')
    routeur = Routeur.depuis_lieu(dossier, 'etage_absent')
    assert routeur.noeuds == {} and routeur.noeud_proche(0, 0) is None


def test_graphe_ecrit_a_la_main():
    routeur = Routeur({'a': (0, 0), 'b': (4, 0), 'c': (4, 3), 'd': (0, 3)},
                      [('a', 'b'), ('b', 'c'), ('a', 'd'), ('d', 'c'), ('a', 'c')])
    assert routeur.itineraire('a', 'c') == ['a', 'c']
    routeur.bloquer('c', 'a')
    assert routeur.itineraire('a', 'c') in (['a', 'b', 'c'], ['a', 'd', 'c'])
    with pytest.raises(ValueError):
        Routeur({'a': (0, 0)}, [('a', 'z')])
