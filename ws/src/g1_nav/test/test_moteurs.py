"""
Tests de l'interface Moteur et du moteur factice, sans robot ni ROS.

À lancer après la compilation de g1_nav, ou avec PYTHONPATH=ws/src/g1_nav :

  python3 -m pytest ~/robot-g1/ws/src/g1_nav/test/test_moteurs.py -v
"""
import math

from g1_nav.moteurs import CLES_ETAT, etat_repos, Moteur, MoteurFactice, SuiviProgres
import pytest


class Horloge:
    """Fausse horloge : le test fait avancer le temps à la main."""

    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def verifier_forme(etat):
    assert set(etat) == set(CLES_ETAT)
    assert sum([etat['en_cours'], etat['arrive'], etat['echec']]) <= 1


def test_moteur_est_abstrait():
    with pytest.raises(TypeError):
        Moteur()

    class Incomplet(Moteur):
        def demarrer(self, poses):
            return True

        def annuler(self):
            pass

    with pytest.raises(TypeError):
        Incomplet()


def test_etat_repos():
    etat = etat_repos()
    verifier_forme(etat)
    assert not etat['en_cours'] and not etat['arrive'] and not etat['echec']
    assert etat['reste_m'] is None and not etat['progresse']


def test_factice_va_jusqu_au_bout():
    horloge = Horloge()
    moteur = MoteurFactice(depart=(0, 0, 0), vitesse=0.5, horloge=horloge)
    verifier_forme(moteur.etat())
    assert moteur.demarrer([(3, 0, 0), (3, 4, math.pi / 2)]) is True
    etat = moteur.etat()
    verifier_forme(etat)
    assert etat['en_cours'] and etat['reste_m'] == pytest.approx(7.0)
    for _ in range(4):
        horloge.t += 0.5
        etat = moteur.etat()
    verifier_forme(etat)
    assert etat['en_cours'] and etat['progresse']
    assert etat['reste_m'] == pytest.approx(6.0)
    assert moteur.position[:2] == pytest.approx((1.0, 0.0))
    horloge.t += 20.0
    etat = moteur.etat()
    verifier_forme(etat)
    assert etat['arrive'] and not etat['en_cours'] and etat['reste_m'] == 0.0
    assert moteur.position == pytest.approx((3.0, 4.0, math.pi / 2))


def test_factice_bloque_puis_repart():
    horloge = Horloge()
    moteur = MoteurFactice(vitesse=1.0, horloge=horloge)
    moteur.demarrer([(10, 0, 0)])
    for _ in range(5):
        horloge.t += 0.2
        moteur.etat()
    assert moteur.etat()['progresse']
    moteur.bloquer()
    reste = moteur.etat()['reste_m']
    for _ in range(10):
        horloge.t += 0.2
        etat = moteur.etat()
    assert etat['en_cours'] and not etat['progresse'] and etat['reste_m'] == pytest.approx(reste)
    moteur.bloquer(False)
    for _ in range(5):
        horloge.t += 0.2
        etat = moteur.etat()
    assert etat['progresse'] and etat['reste_m'] < reste


def test_factice_annuler_n_est_pas_un_echec():
    horloge = Horloge()
    moteur = MoteurFactice(horloge=horloge)
    moteur.demarrer([(5, 0, 0)])
    horloge.t += 1.0
    moteur.annuler()
    assert moteur.etat() == etat_repos()
    horloge.t += 10.0
    assert moteur.position[0] == pytest.approx(0.5)    # il ne bouge plus
    moteur.annuler()                                    # sans effet au repos
    assert moteur.etat() == etat_repos()


def test_factice_echec_et_nouveau_depart():
    horloge = Horloge()
    moteur = MoteurFactice(horloge=horloge)
    moteur.demarrer([(5, 0, 0)])
    moteur.echouer()
    etat = moteur.etat()
    verifier_forme(etat)
    assert etat['echec'] and not etat['en_cours']
    assert moteur.demarrer([(0, 2, 0)])                 # un nouveau départ efface l'échec
    assert moteur.etat()['en_cours']


def test_factice_remplace_le_deplacement_en_cours():
    horloge = Horloge()
    moteur = MoteurFactice(vitesse=1.0, horloge=horloge)
    moteur.demarrer([(10, 0, 0)])
    horloge.t += 2.0
    moteur.demarrer([(2, 3, 0)])
    assert moteur.etat()['reste_m'] == pytest.approx(3.0)


def test_poses_invalides():
    moteur = MoteurFactice(horloge=Horloge())
    with pytest.raises(ValueError):
        moteur.demarrer([])
    with pytest.raises(ValueError):
        moteur.demarrer([(1, 2)])


def test_suivi_progres():
    horloge = Horloge()
    suivi = SuiviProgres(seuil_m=0.1, fenetre_s=1.0, horloge=horloge)
    assert not suivi.progresse()
    suivi.noter(5.0)
    assert not suivi.progresse()
    horloge.t += 0.5
    suivi.noter(4.85)
    assert suivi.progresse()                 # 0,15 m gagnés depuis le départ
    horloge.t += 1.0
    suivi.noter(4.83)
    assert not suivi.progresse()             # 0,02 m en une seconde : il piétine
    horloge.t += 0.5
    suivi.noter(4.60)
    assert suivi.progresse()
    suivi.noter(None)                        # mesure inconnue : ignorée
    assert suivi.progresse()
    suivi.effacer()
    assert not suivi.progresse()
