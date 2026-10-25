"""
Tests des réglages de Nav2 (config/nav2_g1_simu.yaml et nav2_g1_reel.yaml), sans ROS.

  python3 -m pytest ~/robot-g1/ws/src/g1_nav/test/test_reglages.py -v
"""
from pathlib import Path

import pytest
import yaml

CONFIG = Path(__file__).resolve().parent.parent / 'config'


def charger(nom):
    with open(CONFIG / nom, encoding='utf-8') as f:
        return yaml.safe_load(f)


@pytest.fixture(params=['nav2_g1_simu.yaml', 'nav2_g1_reel.yaml'])
def reglages(request):
    return charger(request.param)


def params(reglages, *chemin):
    d = reglages
    for cle in chemin:
        d = d[cle]
    return d['ros__parameters'] if 'ros__parameters' in d else d


def test_mppi_omni(reglages):
    suivi = params(reglages, 'controller_server')['FollowPath']
    assert suivi['plugin'] == 'nav2_mppi_controller::MPPIController'
    assert suivi['motion_model'] == 'Omni'
    assert 'TwirlingCritic' in suivi['critics']
    for critique in suivi['critics']:
        assert critique in suivi, f'réglages du critique {critique} manquants'
    # Le contrôleur prend vy en compte (déplacement sur le côté)
    assert params(reglages, 'controller_server')['min_y_velocity_threshold'] < 0.01


def test_smac_2d(reglages):
    planif = params(reglages, 'planner_server')
    assert planif['GridBased']['plugin'] == 'nav2_smac_planner/SmacPlanner2D'


@pytest.mark.parametrize('carte', ['local_costmap', 'global_costmap'])
def test_emprise_inflation_et_keepout(reglages, carte):
    p = params(reglages, carte, carte)
    assert p['robot_radius'] == 0.35
    # 0,4 m autour des obstacles vus ; plus large sur la carte globale, pour centrer le chemin
    rayon = p['inflation_layer']['inflation_radius']
    assert rayon == 0.4 if carte == 'local_costmap' else rayon >= 0.4
    if carte == 'local_costmap':
        # Vidée chaque seconde par l'arbre du guide : pas de filtre (il rechargerait le masque)
        assert 'filters' not in p
        return
    assert p['filters'] == ['keepout_filter']
    assert p['keepout_filter']['plugin'] == 'nav2_costmap_2d::KeepoutFilter'
    info = params(reglages, 'costmap_filter_info_server')
    assert p['keepout_filter']['filter_info_topic'] == info['filter_info_topic']
    assert info['type'] == 0
    assert info['mask_topic'] == params(reglages, 'filter_mask_server')['topic_name']


def test_voxel_layer_sur_points(reglages):
    p = params(reglages, 'local_costmap', 'local_costmap')
    assert 'voxel_layer' in p['plugins']
    voxels = p['voxel_layer']
    assert voxels['plugin'] == 'nav2_costmap_2d::VoxelLayer'
    source = voxels[voxels['observation_sources']]
    assert source['topic'] == '/points' and source['data_type'] == 'PointCloud2'
    assert voxels['z_voxels'] <= 16      # limite de la couche voxel de Nav2


def test_collision_monitor(reglages):
    p = params(reglages, 'collision_monitor')
    assert p['cmd_vel_in_topic'] == 'cmd_vel_smoothed' and p['cmd_vel_out_topic'] == 'cmd_vel'
    ralentir, arret = (p[nom] for nom in p['polygons'])
    assert (ralentir['action_type'], ralentir['radius'], ralentir['slowdown_ratio']) == \
        ('slowdown', 1.0, 0.5)
    assert (arret['action_type'], arret['radius']) == ('stop', 0.4)
    source = p[p['observation_sources'][0]]
    assert source['type'] == 'pointcloud' and source['topic'] == '/points'


def test_arrivee_a_moins_de_0_3_m(reglages):
    verif = params(reglages, 'controller_server')['general_goal_checker']
    assert verif['xy_goal_tolerance'] < 0.3


def vitesses(reglages):
    suivi = params(reglages, 'controller_server')['FollowPath']
    lisseur = params(reglages, 'velocity_smoother')
    return (suivi['vx_max'], suivi['vy_max'], suivi['wz_max']), lisseur['max_velocity']


def test_vitesses_maximales():
    assert vitesses(charger('nav2_g1_simu.yaml')) == ((0.5, 0.25, 0.8), [0.5, 0.25, 0.8])
    assert vitesses(charger('nav2_g1_reel.yaml')) == ((0.4, 0.2, 0.6), [0.4, 0.2, 0.6])


def test_temps_simule():
    def horloges(reglages):
        trouvees = []

        def parcourir(d):
            if isinstance(d, dict):
                if 'use_sim_time' in d:
                    trouvees.append(d['use_sim_time'])
                for v in d.values():
                    parcourir(v)
        parcourir(reglages)
        return set(trouvees)

    assert horloges(charger('nav2_g1_simu.yaml')) == {True}
    assert horloges(charger('nav2_g1_reel.yaml')) == {False}


def test_reel_ne_differe_que_par_les_vitesses_et_l_horloge():
    simu, reel = charger('nav2_g1_simu.yaml'), charger('nav2_g1_reel.yaml')
    differences = []

    def comparer(a, b, chemin):
        if isinstance(a, dict) and isinstance(b, dict):
            assert set(a) == set(b), f'clés différentes sous {chemin}'
            for cle in a:
                comparer(a[cle], b[cle], chemin + (cle,))
        elif a != b:
            differences.append(chemin[-1])

    comparer(simu, reel, ())
    autorisees = {'use_sim_time', 'vx_max', 'vy_max', 'wz_max', 'max_velocity', 'min_velocity',
                  'max_rotational_vel'}
    assert set(differences) <= autorisees, set(differences) - autorisees
