"""
config/pont.yaml, les défauts du nœud et les valeurs du contrat (atelier.lieu.robot) sont égaux.

Les mêmes valeurs servent quand le pont est lancé avec le fichier (navigation.launch.py) et sans
(ros2 run g1_bridge pont) : un écart entre les trois changerait le comportement selon le lancement.
"""
from pathlib import Path

import pytest
import yaml

from g1_bridge import logique
from g1_bridge.logique import PLAFONDS, Reglages
from g1_bridge.requete import (API_GET_FSM_ID, API_SET_VELOCITY, DUREE_ARRET_S, SUJET_REPONSE,
                               SUJET_REQUETE)

PONT_YAML = Path(__file__).resolve().parent.parent / 'config' / 'pont.yaml'


@pytest.fixture(scope='module')
def fichier():
    donnees = yaml.safe_load(PONT_YAML.read_text(encoding='utf-8'))
    assert list(donnees) == ['pont_g1'], 'le fichier vise le nœud pont_g1'
    return donnees['pont_g1']['ros__parameters']


def test_fichier_egal_aux_defauts_du_noeud(fichier):
    attendu = {n: getattr(Reglages(), n) for n in Reglages.noms()}
    attendu.update(sujet_requete=SUJET_REQUETE, sujet_reponse=SUJET_REPONSE)
    assert fichier == attendu
    for nom, valeur in fichier.items():
        # Même type que le paramètre déclaré (un 1 au lieu de 1.0 serait refusé par ROS 2)
        assert isinstance(valeur, type(attendu[nom])), nom
        assert isinstance(valeur, bool) == isinstance(attendu[nom], bool), nom


def test_valeurs_du_contrat(fichier):
    lieu = pytest.importorskip('atelier.lieu')
    assert lieu.LIMITES_PONT == {'vx': fichier['vx_max'], 'vy': fichier['vy_max'],
                                 'wz': fichier['wz_max']} == PLAFONDS
    assert fichier['duree_consigne'] == lieu.DUREE_CONSIGNE_S
    assert fichier['duree_arret'] == lieu.DUREE_ARRET_S == DUREE_ARRET_S
    assert fichier['delai_cmd_vel'] == lieu.DELAI_CMD_VEL_S
    assert fichier['frequence'] == lieu.FREQUENCE_PONT_HZ
    assert fichier['garde_stop'] == lieu.GARDE_APRES_STOP_S
    assert fichier['delai_reperage'] == lieu.robot.DELAI_REPERAGE_PERIME_S
    assert fichier['delai_muet'] == lieu.robot.DELAI_ROBOT_MUET_S
    assert fichier['exiger_reperage'] is True
    assert API_SET_VELOCITY == lieu.API_SPORT_SET_VELOCITY
    # vague 5 (section 12.6) : vitesse minimale et lecture du mode
    robot = lieu.robot
    assert {'lin': fichier['vitesse_min_lin'], 'rot': fichier['vitesse_min_rot']} \
        == robot.VITESSES_MIN_PONT == logique.VITESSES_MIN
    assert {'lin': fichier['zone_morte_lin'], 'rot': fichier['zone_morte_rot']} \
        == robot.ZONES_MORTES_PONT == logique.ZONES_MORTES
    assert logique.VITESSE_MIN_LIN_MAX == robot.VITESSE_MIN_LIN_MAX
    assert logique.VITESSE_MIN_ROT_MAX == robot.VITESSE_MIN_ROT_MAX
    assert fichier['lire_mode'] is True
    assert fichier['modes_marche'] == list(lieu.pilotage.MODES_MARCHE) \
        == list(logique.MODES_MARCHE)
    assert API_GET_FSM_ID == robot.API_SPORT_GET_FSM_ID
    assert logique.PERIODE_LECTURE_MODE_S == robot.PERIODE_LECTURE_MODE_S
    assert logique.DELAI_MODE_PERIME_S == robot.DELAI_MODE_PERIME_S


def test_etats_du_contrat():
    lieu = pytest.importorskip('atelier.lieu')
    from g1_bridge.logique import ETATS
    assert set(ETATS) == set(lieu.ETATS_PONT)


def test_exemple_du_contrat_a_les_memes_champs():
    """L'état du pont a exactement les champs de l'exemple du contrat (EXEMPLE_ETAT_PONT)."""
    lieu = pytest.importorskip('atelier.lieu')
    from g1_bridge.logique import Pont
    assert set(Pont().etat()) == set(lieu.EXEMPLE_ETAT_PONT)


def test_ordre_des_etats_du_contrat():
    """La priorité des états du pont (nom_etat) suit atelier.lieu.PRIORITE_ETATS_PONT."""
    lieu = pytest.importorskip('atelier.lieu')
    import inspect
    from g1_bridge.logique import Pont
    source = inspect.getsource(Pont.nom_etat)
    rangs = [source.index(f"'{nom}'") for nom in lieu.PRIORITE_ETATS_PONT]
    assert rangs == sorted(rangs)


def test_vitesse_effective_copie_exacte_du_contrat():
    """Le pont et atelier.lieu.robot donnent la même consigne, sur 2000 consignes au hasard."""
    lieu = pytest.importorskip('atelier.lieu')
    import random
    robot = lieu.robot
    for entree, attendu, plafonds in robot.EXEMPLES_VITESSE_MIN:
        assert logique.vitesse_effective(*entree, plafonds=plafonds) == \
            pytest.approx(attendu, abs=2e-6)
    aleatoire = random.Random(2000)
    for _ in range(2000):
        plafonds = aleatoire.choice([None, dict(robot.PLAFONDS_VITESSE_MAX_0_2),
                                     {'vx': 0.3, 'vy': 0.2, 'wz': 0.5}])
        minimums = aleatoire.choice([None, {'lin': 0.0, 'rot': 0.0}, {'lin': 0.15, 'rot': 0.0},
                                     {'lin': 0.0, 'rot': 0.25}, {'lin': 0.3, 'rot': 0.5}])
        zones = aleatoire.choice([None, {'lin': 0.0, 'rot': 0.0}, {'lin': 0.1, 'rot': 0.05}])
        p = plafonds or robot.LIMITES_PONT
        e = [aleatoire.choice([aleatoire.uniform(-1, 1) * p[a], aleatoire.uniform(-0.3, 0.3),
                               0.0]) for a in ('vx', 'vy', 'wz')]
        e = [max(-p[a], min(p[a], v)) for a, v in zip(('vx', 'vy', 'wz'), e)]
        nous = logique.vitesse_effective(*e, plafonds=plafonds, minimums=minimums, zones=zones)
        contrat = robot.vitesse_effective(*e, plafonds=plafonds, minimums=minimums, zones=zones)
        assert nous == contrat, (e, plafonds, minimums, zones)


def test_noms_et_messages_des_modes_copies_du_contrat():
    lieu = pytest.importorskip('atelier.lieu')
    pilotage = lieu.pilotage
    assert logique.MODES_COURSE == pilotage.MODES_COURSE
    assert logique.NOMS_MODES == pilotage.NOMS_MODES
    assert logique.DANSE_PREFIXE == pilotage.DANSE_PREFIXE
    for fsm in [None, 0, 1, 2, 3, 4, 500, 501, 702, 706, 801, 802, 9999, 550604, 550401]:
        assert logique.nom_mode(fsm) == pilotage.nom_mode(fsm)
        if fsm is not None:
            assert logique.message_pas_en_marche(fsm) == pilotage.message_pas_en_marche(fsm)


def test_exemple_v5_du_contrat_publie_par_le_pont():
    """Un pont qui lit « assis » publie un état conforme, comme EXEMPLE_ETAT_PONT_V5."""
    lieu = pytest.importorskip('atelier.lieu')
    from g1_bridge.logique import Pont
    temps = [10.0]
    pont = Pont(horloge=lambda: temps[0])
    (arret,) = pont.demarrer()
    pont.sur_reponse(arret.identifiant, 0)
    pont.sur_reperage(True)
    (lecture,) = [e for e in pont.pas() if e.api_id == API_GET_FSM_ID]
    pont.sur_reponse(lecture.identifiant, 0, '{"data": 3}', API_GET_FSM_ID)
    pont.sur_cmd_vel(0.1, 0.0, 0.0)
    etat = pont.etat()
    v5 = lieu.robot.EXEMPLE_ETAT_PONT_V5
    assert lieu.valider_message('etat_pont', etat) == []
    attendu = (v5['etat'], v5['message'], v5['demande'])
    assert (etat['etat'], etat['message'], etat['demande']) == attendu
    assert etat['minimums'] == v5['minimums']
    assert {k: etat['mode_robot'][k] for k in ('fsm', 'nom', 'en_marche', 'modes_marche')} == \
        {k: v5['mode_robot'][k] for k in ('fsm', 'nom', 'en_marche', 'modes_marche')}
