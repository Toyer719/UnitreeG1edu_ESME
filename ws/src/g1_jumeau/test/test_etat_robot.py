"""
Le service robot_state du faux G1 (vague 6, section 13.2 du plan) : etat_robot.py, sans ROS.

Format du SDK d'Unitree (1003 ServiceList, 1001 ServiceSwitch), services arrêtés au départ,
démarrage après delai_demarrage_s, services protégés et inconnus, arrêts et services hors de la
liste blanche de l'Atelier comptés comme interdits, requêtes illisibles, sujet d'essai (changer),
état publié ; et dans FauxG1 : branchement, panne muet.
"""
import json
from pathlib import Path
import sys

import pytest

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI.parent))
for parent in ICI.parents:
    if (parent / 'atelier' / 'lieu' / 'diagnostic.py').is_file():
        sys.path.insert(0, str(parent))
        break

from g1_jumeau.etat_robot import (CODE_API, CODE_PARAMETRES, FauxRobotState,  # noqa: E402
                                  LISTE_BLANCHE_ATELIER, SERVICES_FAUX_G1)
from g1_jumeau.logique import FauxSport  # noqa: E402
from g1_jumeau.robot import FauxG1  # noqa: E402


class Horloge:
    def __init__(self, t=10.0):
        self.t = t

    def __call__(self):
        return self.t


def liste(etat, t=None):
    code, data = etat.traiter(1003, '{}', t)
    assert code == 0
    services = json.loads(data)
    assert all(isinstance(s['status'], int) and isinstance(s['protect'], int) for s in services)
    return {s['name']: s['status'] for s in services}


def switch(etat, nom, valeur=1, t=None):
    code, data = etat.traiter(1001, json.dumps({'name': nom, 'switch': valeur}), t)
    assert code == 0, (code, data)
    reponse = json.loads(data)
    assert reponse['name'] == nom and set(reponse) == {'name', 'status'}
    return reponse['status']


def test_liste_des_services_au_format_du_sdk():
    etat = FauxRobotState(Horloge(), arretes=('lidar_driver', 'unitree_slam'))
    code, data = etat.traiter(1003, '{}')
    services = json.loads(data)
    assert code == 0 and [s['name'] for s in services] == [n for n, _ in SERVICES_FAUX_G1]
    par_nom = {s['name']: s for s in services}
    assert par_nom['lidar_driver'] == {'name': 'lidar_driver', 'status': 1, 'protect': 0}
    assert par_nom['unitree_slam']['status'] == 1
    assert par_nom['ai_sport'] == {'name': 'ai_sport', 'status': 0, 'protect': 1}
    assert par_nom['motion_switcher']['protect'] == 1 and par_nom['voice']['status'] == 0
    # le SDK Python lit les mêmes clés, le SDK C++ les mêmes types (status, protect entiers)
    assert etat.arretes == ('lidar_driver', 'unitree_slam')
    assert liste(FauxRobotState(Horloge()))['lidar_driver'] == 0      # aucun arrêté : tous actifs


def test_demarrage_apres_le_delai():
    h = Horloge()
    etat = FauxRobotState(h, arretes=('lidar_driver', 'unitree_slam'), delai_demarrage_s=2.0)
    assert switch(etat, 'lidar_driver') == 1        # démarre : arrêté pour l'instant
    assert liste(etat)['lidar_driver'] == 1
    h.t += 1.0
    assert switch(etat, 'lidar_driver') == 1        # redemandé : le délai ne repart pas
    h.t += 1.0
    assert liste(etat) == {**liste(etat), 'lidar_driver': 0, 'unitree_slam': 1}
    assert switch(etat, 'lidar_driver') == 0                            # déjà actif
    assert switch(etat, 'unitree_slam', t=h.t) == 1
    assert liste(etat, t=h.t + 2.0)['unitree_slam'] == 0
    assert etat.etat()['interdits'] == [] and etat.nombre_interdits == 0
    assert [(s['name'], s['switch'], s['status']) for s in etat.etat()['switchs']] == [
        ('lidar_driver', 1, 1), ('lidar_driver', 1, 1), ('lidar_driver', 1, 0),
        ('unitree_slam', 1, 1)]
    assert etat.etat()['appels']['1001'] == 4


def test_delai_nul_actif_tout_de_suite():
    etat = FauxRobotState(Horloge(), arretes=('unitree_slam',), delai_demarrage_s=0.0)
    assert switch(etat, 'unitree_slam') == 0 and liste(etat)['unitree_slam'] == 0
    with pytest.raises(ValueError):
        FauxRobotState(Horloge(), delai_demarrage_s=-1.0)


def test_proteges_inconnus_et_interdits_comptes():
    etat = FauxRobotState(Horloge(), arretes=('lidar_driver',))
    assert switch(etat, 'ai_sport') == 5 and switch(etat, 'motion_switcher', 0) == 5
    assert liste(etat)['ai_sport'] == 0 and liste(etat)['motion_switcher'] == 0  # inchangés
    assert switch(etat, 'service_inconnu') == 2
    assert switch(etat, 'voice', 0) == 1 and liste(etat)['voice'] == 1   # arrêté, comme le vrai
    assert switch(etat, 'video_hub') == 0                                # actif, hors liste
    interdits = etat.etat()['interdits']
    assert [(x['name'], x['switch']) for x in interdits] == [
        ('ai_sport', 1), ('motion_switcher', 0), ('service_inconnu', 1), ('voice', 0),
        ('video_hub', 1)]
    assert etat.nombre_interdits == 5 and 'switch 0' in interdits[1]['raison']
    assert 'liste blanche' in interdits[0]['raison']
    # un switch 0 sur un service de la liste blanche est aussi interdit (l'Atelier n'arrête
    # jamais rien)
    assert switch(etat, 'unitree_slam', 0) == 1 and etat.nombre_interdits == 6


def test_requetes_illisibles_et_autres_api():
    etat = FauxRobotState(Horloge())
    for parametre in ('pas du json', json.dumps({'name': 'lidar_driver'}),
                      json.dumps({'name': 'lidar_driver', 'switch': True}),
                      json.dumps({'name': 'lidar_driver', 'switch': 2}), json.dumps({'switch': 1}),
                      json.dumps(['lidar_driver', 1])):
        assert etat.traiter(1001, parametre) == (CODE_PARAMETRES, ''), parametre
    assert etat.traiter(1003, 'pas du json') == (CODE_PARAMETRES, '')
    assert etat.traiter(1002, json.dumps({'interval': 1, 'duration': 10})) == (0, '')
    assert etat.traiter(1004, '{}') == (CODE_API, '')
    assert etat.traiter(7105, '{}') == (CODE_API, '')
    appels = etat.etat()['appels']
    assert appels == {'1001': 6, '1002': 1, '1003': 1, 'autres': 2, 'illisibles': 7}
    assert etat.nombre_interdits == 0 and etat.switchs == []


def test_changer_par_le_sujet_d_essai():
    h = Horloge()
    etat = FauxRobotState(h, delai_demarrage_s=5.0)
    etat.changer({'lidar_driver': 1, 'unitree_slam': 1})
    assert liste(etat)['lidar_driver'] == 1
    switch(etat, 'lidar_driver')
    etat.changer({'lidar_driver': 1})                  # annule le démarrage en cours
    h.t += 10.0
    assert liste(etat)['lidar_driver'] == 1 and etat.etat()['demarrage_en_cours'] == []
    etat.changer({'lidar_driver': 0})
    assert liste(etat)['lidar_driver'] == 0
    for faute in ({'inconnu': 0}, {'lidar_driver': 3}, {'lidar_driver': True},
                  {'lidar_driver': '0'}, ['x']):
        with pytest.raises(ValueError):
            etat.changer(faute)
    with pytest.raises(ValueError, match='inconnu'):
        FauxRobotState(h, arretes=('lidar',))


def test_etat_publie():
    etat = FauxRobotState(Horloge(), arretes=('unitree_slam',))
    e = etat.etat()
    assert set(e) >= {'services', 'interdits', 'appels', 'switchs', 'nombre_interdits',
                      'arretes_au_depart', 'requetes'}
    assert e['services']['unitree_slam'] == 1 and e['services']['lidar_driver'] == 0
    assert e['arretes_au_depart'] == ['unitree_slam']
    json.dumps(e)                                       # publiable tel quel dans /g1_jumeau/etat
    etat.traiter(1003, '{}')
    etat.traiter(1001, json.dumps({'name': 'unitree_slam', 'switch': 1}))
    assert [(r['api'], r['parameter']) for r in etat.etat()['requetes']] == [
        (1003, '{}'), (1001, '{"name": "unitree_slam", "switch": 1}')]


def test_liste_blanche_copie_de_celle_de_l_atelier():
    diagnostic = pytest.importorskip('atelier.lieu.diagnostic')
    assert LISTE_BLANCHE_ATELIER == tuple(diagnostic.SERVICES_CARTOGRAPHIE)
    assert diagnostic.STATUT_ACTIF == 0 and diagnostic.STATUT_ARRETE == 1
    assert diagnostic.STATUT_PROTEGE == 5
    # la réponse de 1001 du faux G1 se lit avec la fonction de l'Atelier
    etat = FauxRobotState(Horloge(), arretes=('lidar_driver',))
    assert diagnostic.lire_reponse_switch(etat.traiter(1001, diagnostic.parametre_service_switch(
        'lidar_driver'))[1])[:2] == (True, 1)
    assert diagnostic.lire_reponse_switch(etat.traiter(1001, json.dumps(
        {'name': 'ai_sport', 'switch': 1}))[1])[:2] == (False, 5)
    liste_brute = etat.traiter(1003, diagnostic.parametre_service_list())[1]
    services = diagnostic.lire_liste_services(liste_brute)
    assert diagnostic.services_arretes(services) == ['lidar_driver']


def test_branche_dans_le_faux_g1():
    h = Horloge()
    g1 = FauxG1(FauxSport(horloge=h), services_arretes=('lidar_driver', 'unitree_slam'))
    code, data = g1.traiter('robot_state', 1003, '{}')
    assert code == 0 and {s['name']: s['status'] for s in json.loads(data)}['lidar_driver'] == 1
    reponse = g1.traiter('robot_state', 1001, json.dumps({'name': 'unitree_slam', 'switch': 1}))
    assert json.loads(reponse[1])['status'] == 1
    h.t += 2.5
    assert g1.etat()['services']['services']['unitree_slam'] == 0
    assert g1.requetes['robot_state'] == 2
    g1.sport.changer_panne('muet')
    assert g1.traiter('robot_state', 1003, '{}') is None             # panne muet : aucune réponse
    with pytest.raises(ValueError):
        FauxG1(FauxSport(horloge=h), services_arretes=('pas_un_service',))
