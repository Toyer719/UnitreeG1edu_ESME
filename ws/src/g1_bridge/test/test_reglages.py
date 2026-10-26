"""
config/pont.yaml, les défauts du nœud et les valeurs du contrat (atelier.lieu.robot) sont égaux.

Les mêmes valeurs servent quand le pont est lancé avec le fichier (navigation.launch.py) et sans
(ros2 run g1_bridge pont) : un écart entre les trois changerait le comportement selon le lancement.
"""
from pathlib import Path

import pytest
import yaml

from g1_bridge.logique import PLAFONDS, Reglages
from g1_bridge.requete import API_SET_VELOCITY, DUREE_ARRET_S, SUJET_REPONSE, SUJET_REQUETE

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


def test_etats_du_contrat():
    lieu = pytest.importorskip('atelier.lieu')
    from g1_bridge.logique import ETATS
    assert set(ETATS) == set(lieu.ETATS_PONT)


def test_exemple_du_contrat_a_les_memes_champs():
    """L'état du pont a exactement les champs de l'exemple du contrat (EXEMPLE_ETAT_PONT)."""
    lieu = pytest.importorskip('atelier.lieu')
    from g1_bridge.logique import Pont
    assert set(Pont().etat()) == set(lieu.EXEMPLE_ETAT_PONT)
