"""
Tests de la logique du guide avec le moteur factice et une fausse horloge, sans ROS.

  python3 -m pytest ~/robot-g1/ws/src/g1_nav/test/test_guide.py -v
"""
import json

from atelier import RACINE
from atelier.lieu import copier_lieu
from g1_nav.guide import (DELAI_BLOQUE_S, DELAI_DEPART_S, DELAI_DETOUR_S, distance_segment,
                          ErreurMoteur, fabriquer_moteur, Guide, MAX_DETOURS)
from g1_nav.moteurs import MoteurFactice
from g1_nav.routeur import Routeur
import pytest

PAS_S = 0.2     # le nœud ROS appelle pas() 5 fois par seconde


class Horloge:
    """Fausse horloge partagée par le guide, le routeur et le moteur factice."""

    def __init__(self):
        self.t = 500.0

    def __call__(self):
        return self.t


class Banc:
    """Guide + moteur factice + routeur du demo, et une boucle qui fait passer le temps."""

    def __init__(self, dossier, depart=(2.5, 10.0, 0.0), position_connue=True):
        self.horloge = Horloge()
        self.routeur = Routeur.depuis_lieu(dossier, 'rdc', horloge=self.horloge)
        self.moteur = MoteurFactice(depart=depart, vitesse=0.5, horloge=self.horloge)
        self.messages = []
        self.changements = []
        position = (lambda: self.moteur.position) if position_connue else None
        self.guide = Guide(self.routeur, self.moteur, position=position, horloge=self.horloge,
                           journal=self.messages.append, au_changement=self.changements.append)

    def etats(self):
        return [c['etat'] for c in self.changements]

    def tourner(self, duree_s, obstacle=None, jusqu_a=('arrive', 'echec')):
        """Fait passer le temps ; obstacle(guide, moteur) -> True immobilise le robot."""
        for _ in range(int(duree_s / PAS_S)):
            self.horloge.t += PAS_S
            if obstacle is not None:
                self.moteur.bloquer(obstacle(self.guide, self.moteur))
            etat = self.guide.pas()
            if etat['etat'] in jusqu_a:
                break
        return self.guide.etat()


def boite_couloir_nord(guide, moteur):
    """Une boîte en x = 12 dans le couloir nord : le robot s'arrête devant, à x = 11,5."""
    x, y, _ = moteur.position
    return guide.etat()['etat'] != 'detour' and 11.4 < x < 12.0 and 12.0 < y < 14.0


@pytest.fixture
def dossier(tmp_path):
    return copier_lieu(RACINE / 'lieux' / 'demo', tmp_path / 'demo')


def test_accueil_vers_b204_par_le_nord(dossier):
    banc = Banc(dossier)
    assert banc.guide.etat() == {'etat': 'attente', 'cible': None, 'reste_m': None,
                                 'itineraire': []}
    assert banc.guide.aller('b204')
    etat = banc.guide.etat()
    assert etat['etat'] == 'en_route' and etat['cible'] == 'b204'
    assert etat['itineraire'] == ['accueil', 'hall_nord', 'amphi', 'couloir_nord_1', 'b204']
    assert etat['reste_m'] == pytest.approx(21.5)
    banc.tourner(5.0, jusqu_a=())
    assert banc.guide.etat()['reste_m'] == pytest.approx(21.5 - 2.5, abs=0.15)
    etat = banc.tourner(60.0)
    assert etat['etat'] == 'arrive' and etat['reste_m'] == 0.0
    assert banc.moteur.position[:2] == pytest.approx((21.0, 13.0))
    assert banc.etats() == ['en_route', 'arrive']
    # Le format publié sur /guide/etat est du JSON
    assert json.loads(json.dumps(etat))['itineraire'][-1] == 'b204'


def test_boite_dans_le_couloir_nord_bloque_puis_detour_puis_arrive(dossier):
    banc = Banc(dossier)
    banc.guide.aller('b204')
    etat = banc.tourner(150.0, obstacle=boite_couloir_nord)
    assert etat['etat'] == 'arrive'
    assert banc.etats() == ['en_route', 'bloque', 'detour', 'arrive']
    # Après le détour, l'itinéraire repart de amphi, passe par le sud et la liaison est
    assert etat['itineraire'][0] == 'amphi'
    assert 'hall_sud' in etat['itineraire'] and 'est_nord' in etat['itineraire']
    assert 'couloir_nord_1' not in etat['itineraire'][:-1]
    assert banc.routeur.est_bloque('amphi', 'couloir_nord_1')
    assert banc.guide.detours == 1 and banc.guide.arrets == 1
    assert any('marqué bloqué' in m for m in banc.messages)


def test_delais_bloque_et_detour(dossier):
    banc = Banc(dossier)
    banc.guide.aller('b204')
    banc.tourner(2.0, jusqu_a=())
    banc.moteur.bloquer(True)
    t0 = banc.horloge.t
    # Le robot gagne encore un peu de distance pendant la première seconde de blocage
    banc.tourner(DELAI_BLOQUE_S + 1.2, jusqu_a=('bloque',))
    assert banc.guide.etat()['etat'] == 'bloque'
    assert banc.horloge.t - t0 <= DELAI_BLOQUE_S + 1.2
    banc.tourner(DELAI_DETOUR_S, jusqu_a=('detour',))
    assert banc.guide.etat()['etat'] == 'detour'
    assert banc.horloge.t - t0 <= DELAI_DETOUR_S + 1.2
    # Couloir bloqué : accueil - hall_nord (le robot était sur le premier couloir)
    assert banc.routeur.est_bloque('accueil', 'hall_nord')


def test_delai_de_depart(dossier):
    # Robot immobile dès le départ : il a DELAI_DEPART_S de plus pour démarrer
    banc = Banc(dossier)
    banc.moteur.bloquer(True)
    banc.guide.aller('b204')
    banc.tourner(DELAI_BLOQUE_S + DELAI_DEPART_S - 0.5, jusqu_a=())
    assert banc.guide.etat()['etat'] == 'en_route'
    banc.tourner(1.0, jusqu_a=())
    assert banc.guide.etat()['etat'] == 'bloque'


def test_bloque_puis_repart_sans_detour(dossier):
    banc = Banc(dossier)
    banc.guide.aller('b204')
    banc.tourner(2.0, jusqu_a=())
    banc.moteur.bloquer(True)
    banc.tourner(5.0, jusqu_a=('bloque',))
    banc.moteur.bloquer(False)
    etat = banc.tourner(80.0)
    assert etat['etat'] == 'arrive'
    assert banc.etats() == ['en_route', 'bloque', 'en_route', 'arrive']
    assert banc.guide.detours == 0


def test_stop(dossier):
    banc = Banc(dossier)
    banc.guide.aller('cdi')
    banc.tourner(3.0, jusqu_a=())
    banc.guide.stop()
    assert banc.guide.etat() == {'etat': 'attente', 'cible': None, 'reste_m': None,
                                 'itineraire': []}
    position = banc.moteur.position
    banc.tourner(3.0)
    assert banc.moteur.position == position
    assert not banc.moteur.etat()['en_cours']


def test_cible_inconnue(dossier):
    banc = Banc(dossier)
    assert not banc.guide.aller('salle_qui_n_existe_pas')
    etat = banc.guide.etat()
    assert etat['etat'] == 'echec' and etat['cible'] == 'salle_qui_n_existe_pas'
    assert any('cible inconnue' in m for m in banc.messages)


def test_alias(dossier):
    banc = Banc(dossier)
    assert banc.guide.aller('Bibliothèque')
    assert banc.guide.etat()['cible'] == 'cdi'


def test_aucun_chemin(dossier):
    banc = Banc(dossier)
    banc.guide.aller('cdi')
    banc.tourner(2.0, jusqu_a=())
    banc.routeur.bloquer('amphi', 'couloir_nord_1')
    banc.routeur.bloquer('infirmerie', 'couloir_sud_2')
    assert not banc.guide.aller('b204')
    assert banc.guide.etat()['etat'] == 'echec'
    # Le trajet précédent (vers cdi) ne continue pas
    assert not banc.moteur.etat()['en_cours']


def test_detour_impossible_donne_echec(dossier):
    banc = Banc(dossier)
    banc.guide.aller('b204')
    banc.routeur.bloquer('infirmerie', 'couloir_sud_2')     # le chemin de secours est coupé
    etat = banc.tourner(150.0, obstacle=boite_couloir_nord)
    assert etat['etat'] == 'echec'
    assert banc.etats() == ['en_route', 'bloque', 'echec']
    assert not banc.moteur.etat()['en_cours']


def test_abandon_du_moteur_relance_puis_detour(dossier):
    banc = Banc(dossier)
    banc.guide.aller('b204')
    banc.tourner(10.0, jusqu_a=())      # le robot est sur hall_nord - amphi
    # Premier abandon : nouvel essai depuis le couloir actuel, sans fermer de couloir
    banc.moteur.echouer()
    banc.guide.pas()
    assert banc.guide.etat()['etat'] == 'en_route'
    assert banc.routeur.couloirs_bloques() == []
    assert banc.moteur.etat()['reste_m'] == pytest.approx(21.5 - 5.0, abs=0.3)
    assert any('nouvel essai par amphi' in m for m in banc.messages)
    # Second abandon sur le même itinéraire : détour
    banc.moteur.echouer()
    banc.guide.pas()
    assert banc.guide.etat()['etat'] == 'detour'
    assert banc.routeur.est_bloque('hall_nord', 'amphi')
    assert banc.tourner(150.0)['etat'] == 'arrive'


def test_trop_de_detours(dossier):
    banc = Banc(dossier)
    banc.guide.aller('cdi')
    for _ in range(2 * MAX_DETOURS):
        banc.tourner(1.0, jusqu_a=())
        banc.moteur.echouer()
        banc.guide.pas()
        assert banc.guide.etat()['etat'] in ('en_route', 'detour', 'echec')
    for _ in range(2):
        banc.moteur.echouer()
        banc.guide.pas()
    assert banc.guide.etat()['etat'] == 'echec'


def test_position_inconnue_depart_a_l_accueil(dossier):
    banc = Banc(dossier, position_connue=False)
    assert banc.guide.aller('amphi')
    assert banc.guide.etat()['itineraire'] == ['accueil', 'hall_nord', 'amphi']
    assert any('position du robot inconnue' in m for m in banc.messages)
    # Sans position, le couloir à éviter vient de la distance restante
    banc.tourner(7.0, jusqu_a=())        # 3,4 m faits : le robot a passé hall_nord
    banc.moteur.bloquer(True)
    banc.tourner(DELAI_DETOUR_S + 2.0, jusqu_a=('detour',))
    assert banc.routeur.est_bloque('hall_nord', 'amphi')


def test_depart_au_milieu_d_un_couloir(dossier):
    # Robot entre amphi et couloir_nord_1, plus près d'amphi : inutile de revenir à amphi
    banc = Banc(dossier, depart=(10.5, 13.0, 0.0))
    banc.guide.aller('b204')
    assert banc.guide.etat()['itineraire'] == ['amphi', 'couloir_nord_1', 'b204']
    assert banc.moteur.etat()['reste_m'] == pytest.approx(10.5)


def test_nouvelle_cible_en_route(dossier):
    banc = Banc(dossier)
    banc.guide.aller('b204')
    banc.tourner(4.0, jusqu_a=())
    banc.guide.aller('accueil')
    assert banc.guide.etat()['cible'] == 'accueil'
    assert banc.tourner(30.0)['etat'] == 'arrive'
    assert banc.moteur.position[:2] == pytest.approx((2.5, 10.0))


def test_distance_segment():
    assert distance_segment((1, 1), (0, 0), (2, 0)) == pytest.approx(1.0)
    assert distance_segment((3, 0), (0, 0), (2, 0)) == pytest.approx(1.0)
    assert distance_segment((5, 5), (1, 1), (1, 1)) == pytest.approx(5.656854, abs=1e-5)


def test_fabriquer_moteur():
    assert isinstance(fabriquer_moteur('factice', depart=(1, 2, 0)), MoteurFactice)
    with pytest.raises(ErreurMoteur):
        fabriquer_moteur('voiture')


def test_moteur_unitree_absent_echoue_proprement(monkeypatch):
    import builtins
    import sys
    monkeypatch.delitem(sys.modules, 'g1_nav.moteur_unitree', raising=False)
    vrai_import = builtins.__import__

    def faux_import(nom, *args, **kwargs):
        if nom == 'g1_nav.moteur_unitree':
            raise ModuleNotFoundError(f"No module named '{nom}'", name=nom)
        return vrai_import(nom, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', faux_import)
    with pytest.raises(ErreurMoteur, match='MoteurUnitree est absent'):
        fabriquer_moteur('unitree')


# ---------------------------------------------------------------- attente de la navigation (10.7)

class Preparation:
    """Fausse préparation : verdict changé par le test (None : la navigation est prête)."""

    def __init__(self, verdict=('attendre', 'La navigation démarre.')):
        self.verdict = verdict
        self.appels = 0

    def __call__(self):
        self.appels += 1
        return self.verdict


def banc_avec_preparation(dossier, preparation):
    banc = Banc(dossier)
    banc.guide.preparation = preparation
    return banc


def test_attend_nav2_puis_part(dossier):
    """Nav2 pas encore actif : attente avec un message, pas d'echec ; départ dès qu'il est prêt."""
    prep = Preparation()
    banc = banc_avec_preparation(dossier, prep)
    assert banc.guide.aller('b204')
    etat = banc.guide.etat()
    assert etat['etat'] == 'attente' and etat['cible'] == 'b204'
    assert etat['message'] == 'La navigation démarre.'
    assert banc.guide.en_attente and not banc.moteur.etat()['en_cours']
    banc.tourner(20.0, jusqu_a=())
    assert banc.guide.etat()['etat'] == 'attente' and prep.appels > 50
    prep.verdict = None
    etat = banc.tourner(PAS_S, jusqu_a=())
    assert etat['etat'] == 'en_route' and 'message' not in etat
    assert etat['itineraire'] == ['accueil', 'hall_nord', 'amphi', 'couloir_nord_1', 'b204']
    assert banc.moteur.etat()['en_cours']
    assert banc.tourner(60.0)['etat'] == 'arrive'
    assert banc.etats()[:2] == ['attente', 'en_route']


def test_attente_trop_longue_donne_echec(dossier):
    banc = banc_avec_preparation(dossier, Preparation())
    banc.guide.aller('b204')
    banc.tourner(89.0, jusqu_a=('echec',))
    assert banc.guide.etat()['etat'] == 'attente'
    etat = banc.tourner(2.0)
    assert etat['etat'] == 'echec' and 'pas prête après 90 s' in etat['message']
    assert not banc.guide.en_attente


def test_robot_non_repere_echec_tout_de_suite(dossier):
    banc = banc_avec_preparation(dossier, Preparation(
        ('echec', 'Robot non repéré : cliquez sur « Repérer le robot ».')))
    assert not banc.guide.aller('b204')
    etat = banc.guide.etat()
    assert etat['etat'] == 'echec' and 'Repérer le robot' in etat['message']
    assert not banc.moteur.etat()['en_cours']


def test_repere_pendant_l_attente_puis_echec(dossier):
    """Pendant l'attente, le message suit ; un échec du repérage arrête l'attente."""
    prep = Preparation(('attendre', 'Repérage en cours : départ dès que le robot est repéré.'))
    banc = banc_avec_preparation(dossier, prep)
    banc.guide.aller('cdi')
    assert banc.guide.etat()['message'].startswith('Repérage en cours')
    prep.verdict = ('attendre', 'La navigation démarre : départ dès qu\'elle est prête.')
    banc.tourner(PAS_S, jusqu_a=())
    assert banc.guide.etat()['message'].startswith('La navigation démarre')
    assert banc.changements[-1]['message'].startswith('La navigation démarre')
    prep.verdict = ('echec', 'Robot non repéré : cliquez sur « Repérer le robot ».')
    assert banc.tourner(PAS_S)['etat'] == 'echec'


def test_stop_pendant_l_attente(dossier):
    prep = Preparation()
    banc = banc_avec_preparation(dossier, prep)
    banc.guide.aller('b204')
    banc.guide.stop()
    assert banc.guide.etat() == {'etat': 'attente', 'cible': None, 'reste_m': None,
                                 'itineraire': []}
    prep.verdict = None
    banc.tourner(5.0, jusqu_a=())
    assert not banc.moteur.etat()['en_cours'] and banc.guide.etat()['cible'] is None


def test_cible_inconnue_sans_attendre(dossier):
    prep = Preparation()
    banc = banc_avec_preparation(dossier, prep)
    assert not banc.guide.aller('grenier')
    assert banc.guide.etat()['etat'] == 'echec' and prep.appels == 0
    assert banc.guide.etat()['message'].startswith('Cible inconnue')


def test_reperage_perdu_en_route_n_est_pas_un_obstacle(dossier):
    """Le pont arrête le robot (repérage perdu) : ni bloque, ni détour ; reprise ensuite."""
    banc = Banc(dossier)
    perdu = []
    banc.guide.suspension = lambda: perdu[0] if perdu else None
    banc.guide.aller('b204')
    banc.tourner(5.0, jusqu_a=())
    perdu.append('Repérage perdu : le robot est arrêté.')
    banc.tourner(20.0, obstacle=lambda g, m: True, jusqu_a=('echec', 'detour'))
    etat = banc.guide.etat()
    assert etat['etat'] == 'en_route'
    assert etat['message'] == 'Repérage perdu : le robot est arrêté.'
    assert 'bloque' not in banc.etats() and banc.guide.detours == 0
    assert banc.changements[-1]['message'].startswith('Repérage perdu')
    perdu.clear()
    etat = banc.tourner(60.0, obstacle=lambda g, m: False)      # le pont laisse repartir
    assert etat['etat'] == 'arrive' and 'message' not in etat and banc.guide.detours == 0
