"""
Tests de MoteurNav2 avec un faux BasicNavigator : pas besoin de lancer Nav2.

Il faut les messages ROS 2 (source ~/robot-g1/setup/env.sh) ; sinon les tests sont sautés.

  python3 -m pytest ~/robot-g1/ws/src/g1_nav/test/test_moteur_nav2.py -v
"""
import math
from types import SimpleNamespace

import pytest

pytest.importorskip('geometry_msgs.msg')
commandant = pytest.importorskip('nav2_simple_commander.robot_navigator')

from g1_nav.moteur_nav2 import MoteurNav2  # noqa: E402
from g1_nav.moteurs import CLES_ETAT  # noqa: E402


class FauxClientAction:
    def __init__(self, pret=True):
        self.pret = pret

    def wait_for_server(self, timeout_sec=None):
        return self.pret


class FauxNavigateur:
    """Imite l'interface de BasicNavigator utilisée par MoteurNav2."""

    def __init__(self, pret=True, accepte=True):
        self.nav_through_poses_client = FauxClientAction(pret)
        self.accepte = accepte
        self.feedback = None
        self.goal_handle = None
        self.result_future = None
        self.termine = False
        self.resultat = commandant.TaskResult.UNKNOWN
        self.envois = []
        self.annulations = 0
        self.erreurs = []

    def goThroughPoses(self, poses, behavior_tree=''):
        self.envois.append(poses)
        if not self.accepte:
            return False
        self.goal_handle = SimpleNamespace(cancel_goal_async=self._annuler)
        self.result_future = object()
        self.termine = False
        return True

    def _annuler(self):
        self.annulations += 1
        return 'futur'

    def isTaskComplete(self):
        return self.termine

    def getResult(self):
        return self.resultat

    def getFeedback(self):
        return self.feedback

    def error(self, message):
        self.erreurs.append(message)

    def retour(self, x, y, poses_restantes=1, distance=0.0):
        pose = SimpleNamespace(pose=SimpleNamespace(position=SimpleNamespace(x=x, y=y)))
        self.feedback = SimpleNamespace(distance_remaining=distance, current_pose=pose,
                                        number_of_poses_remaining=poses_restantes)


def moteur_avec(nav):
    attentes = []
    moteur = MoteurNav2(navigateur=nav, attendre=lambda futur, delai: attentes.append(delai))
    return moteur, attentes


def test_poses_envoyees_dans_map():
    nav = FauxNavigateur()
    moteur, _ = moteur_avec(nav)
    assert moteur.demarrer([(1.0, 2.0, 0.0), (3.0, 2.0, math.pi / 2)])
    poses = nav.envois[0]
    assert [p.header.frame_id for p in poses] == ['map', 'map']
    assert (poses[1].pose.position.x, poses[1].pose.position.y) == (3.0, 2.0)
    q = poses[1].pose.orientation
    assert (q.z, q.w) == pytest.approx((math.sin(math.pi / 4), math.cos(math.pi / 4)))
    etat = moteur.etat()
    assert set(etat) == set(CLES_ETAT) and etat['en_cours'] and etat['reste_m'] is None


def test_poses_vides():
    moteur, _ = moteur_avec(FauxNavigateur())
    with pytest.raises(ValueError):
        moteur.demarrer([])


def test_nav2_absent_ou_refus_donne_echec():
    nav = FauxNavigateur(pret=False)
    moteur, _ = moteur_avec(nav)
    assert not moteur.demarrer([(1, 1, 0)])
    assert moteur.etat()['echec'] and nav.envois == []
    assert 'Nav2 ne répond pas' in nav.erreurs[0]
    moteur, _ = moteur_avec(FauxNavigateur(accepte=False))
    assert not moteur.demarrer([(1, 1, 0)])
    assert moteur.etat()['echec']


def test_distance_restante_et_arrivee():
    nav = FauxNavigateur()
    moteur, _ = moteur_avec(nav)
    moteur.demarrer([(4.0, 0.0, 0.0), (4.0, 3.0, 0.0)])
    # En ligne droite, par les poses que Nav2 n'a pas encore passées
    nav.retour(0.0, 0.0, poses_restantes=2, distance=9.9)
    assert moteur.etat()['reste_m'] == pytest.approx(7.0)
    nav.retour(3.0, 1.0, poses_restantes=1)      # première pose passée (coin coupé)
    assert moteur.etat()['reste_m'] == pytest.approx(math.hypot(1.0, 2.0))
    nav.termine, nav.resultat = True, commandant.TaskResult.SUCCEEDED
    etat = moteur.etat()
    assert etat['arrive'] and not etat['en_cours'] and etat['reste_m'] == 0.0
    assert moteur.etat() == etat


def test_abandon_de_nav2_donne_echec():
    nav = FauxNavigateur()
    moteur, _ = moteur_avec(nav)
    moteur.demarrer([(4.0, 0.0, 0.0)])
    nav.termine, nav.resultat = True, commandant.TaskResult.FAILED
    etat = moteur.etat()
    assert etat['echec'] and not etat['en_cours'] and not etat['arrive']


def test_annuler_revient_au_repos():
    nav = FauxNavigateur()
    moteur, attentes = moteur_avec(nav)
    moteur.demarrer([(4.0, 0.0, 0.0)])
    moteur.annuler()
    # Attente de la réponse à l'annulation, puis de la fin du but annulé
    assert nav.annulations == 1 and attentes == [0.5, 0.5]
    etat = moteur.etat()
    assert not (etat['en_cours'] or etat['arrive'] or etat['echec'])
    moteur.annuler()       # sans effet si rien n'est en cours
    assert nav.annulations == 1


def test_progres():
    nav = FauxNavigateur()
    moteur, _ = moteur_avec(nav)
    temps = [0.0]
    moteur._suivi.horloge = lambda: temps[0]
    moteur.demarrer([(10.0, 0.0, 0.0)])
    for i in range(12):
        temps[0] = i * 0.2
        nav.retour(0.1 * i, 0.0)         # 0,5 m/s
        etat = moteur.etat()
    assert etat['progresse']
    for i in range(12, 24):
        temps[0] = i * 0.2
        nav.retour(1.1, 0.0)             # immobile
        etat = moteur.etat()
    assert not etat['progresse']
