"""
Tests des réglages de Nav2 (config/nav2_g1_simu.yaml et nav2_g1_reel.yaml), sans ROS.

Vague 4 (section 11.3 du plan, agent Passants) : distance aux personnes (inflation de la carte
locale), ralentir près d'elles (Collision Monitor), obstacles bas sous 1,1 m (voxel_layer), sans
toucher aux repères, aux sujets, à la chaîne cmd_vel, ni aux vitesses maximales.

  python3 -m pytest ~/robot-g1/ws/src/g1_nav/test/test_reglages.py -v
"""
import math
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
    assert p['robot_radius'] == 0.35          # 0,35 m au moins (contrat 11.3) ; portes de 0,8 m
    rayon = p['inflation_layer']['inflation_radius']
    assert rayon >= 0.8                       # carte globale : chemin au milieu des couloirs
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


def cout_inflation(couche, distance, rayon_robot=0.35):
    """Coût de la couche d'inflation de Nav2 à cette distance (m) d'un obstacle."""
    if distance <= rayon_robot:
        return 253
    if distance > couche['inflation_radius']:
        return 0
    return 252 * math.exp(-couche['cost_scaling_factor'] * (distance - rayon_robot))


def test_voxel_layer_sur_points(reglages):
    p = params(reglages, 'local_costmap', 'local_costmap')
    assert 'voxel_layer' in p['plugins']
    voxels = p['voxel_layer']
    assert voxels['plugin'] == 'nav2_costmap_2d::VoxelLayer'
    sources = voxels['observation_sources'].split()
    for nom in sources:
        assert voxels[nom]['topic'] == '/points' and voxels[nom]['data_type'] == 'PointCloud2'
    assert voxels['z_voxels'] <= 16      # limite de la couche voxel de Nav2
    assert voxels['origin_z'] + voxels['z_voxels'] * voxels['z_resolution'] >= 1.9


def test_obstacles_bas_sans_obstacles_fantomes(reglages):
    """
    Vague 4 : obstacles bas marqués, sol jamais, et chaque rayon efface ce qu'il traverse.

    Obstacles bas : enfant, valise, fauteuil, sous 1,1 m. L'effacement passe par tous les
    rayons, sol compris : sans cela, les voxels bas restaient (obstacles fantômes, vague 1).
    """
    voxels = params(reglages, 'local_costmap', 'local_costmap')['voxel_layer']
    sources = [voxels[nom] for nom in voxels['observation_sources'].split()]
    marquage = [s for s in sources if s['marking']]
    effacement = [s for s in sources if s['clearing']]
    assert min(s['min_obstacle_height'] for s in marquage) <= 0.2
    assert max(s['max_obstacle_height'] for s in marquage) >= 1.8
    assert all(s['min_obstacle_height'] >= 0.1 for s in marquage)        # jamais le sol
    haut = max(t['max_obstacle_height'] for t in marquage)
    for s in marquage:                        # une tranche continue de bas en haut
        suivante = [t for t in marquage
                    if abs(t['min_obstacle_height'] - s['max_obstacle_height']) < 1e-9]
        assert suivante or s['max_obstacle_height'] == haut
    assert any(s['min_obstacle_height'] < 0.0 and s['max_obstacle_height'] >= 1.9
               for s in effacement)


def test_personnes_dans_la_carte_globale(reglages):
    """
    Vague 4 : les personnes vues sont aussi dans la carte globale.

    Tranche de 1,125 à 1,9 m, que les rayons du LiDAR balaient partout autour du robot : le
    chemin contourne les personnes au lieu de passer à travers (MPPI restait bloqué devant).
    Rien sous 1,125 m dans la carte globale : elle n'est pas vidée chaque seconde, et les
    voxels bas n'y seraient jamais effacés.
    """
    p = params(reglages, 'global_costmap', 'global_costmap')
    assert p['plugins'] == ['static_layer', 'voxel_layer', 'inflation_layer']
    voxels = p['voxel_layer']
    sources = [voxels[nom] for nom in voxels['observation_sources'].split()]
    for s in sources:
        assert s['topic'] == '/points' and s['data_type'] == 'PointCloud2'
    marquage = [s for s in sources if s['marking']]
    assert marquage and min(s['min_obstacle_height'] for s in marquage) >= 1.125
    assert max(s['max_obstacle_height'] for s in marquage) <= 1.9
    assert all(s['obstacle_max_range'] <= 5.0 for s in marquage)
    assert any(s['clearing'] and s['min_obstacle_height'] < 0.0 for s in sources)


def test_distance_aux_personnes(reglages):
    """
    Vague 4 : distance aux personnes dans la carte locale.

    Autour d'une personne, la carte coûte cher jusqu'à 0,2 m bord à bord et au-delà (MPPI s'en
    tient loin), mais le milieu d'un passage de 1,18 m reste libre.
    """
    couche = params(reglages, 'local_costmap', 'local_costmap')['inflation_layer']
    bord_02 = 0.25 + 0.26 + 0.20 - 0.25       # 0,20 m bord à bord : 0,46 m de sa surface
    assert cout_inflation(couche, bord_02) >= 150
    assert cout_inflation(couche, 1.175 / 2) < 128         # milieu du passage : pas inscrit
    assert cout_inflation(couche, 1.43) == 0               # milieu d'un couloir de 2,85 m : libre


def test_collision_monitor(reglages):
    p = params(reglages, 'collision_monitor')
    assert p['cmd_vel_in_topic'] == 'cmd_vel_smoothed' and p['cmd_vel_out_topic'] == 'cmd_vel'
    ralentir, arret = (p[nom] for nom in p['polygons'])
    # ralentir près des personnes (et de tout ce qui est à moins de 1 m)
    assert (ralentir['action_type'], ralentir['radius'], ralentir['slowdown_ratio']) == \
        ('slowdown', 1.0, 0.5)
    assert arret['action_type'] == 'stop' and arret['radius'] >= 0.4      # contrat 11.3
    source = p[p['observation_sources'][0]]
    assert source['type'] == 'pointcloud' and source['topic'] == '/points'
    assert source['min_height'] <= 0.15      # obstacles bas


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


def test_reperes_sujets_et_chaine_inchanges(reglages):
    """L'agent Passants ne touche ni aux repères, ni aux sujets, ni à la chaîne cmd_vel."""
    for carte, repere in (('local_costmap', 'odom'), ('global_costmap', 'map')):
        p = params(reglages, carte, carte)
        assert (p['global_frame'], p['robot_base_frame']) == (repere, 'base_link')
    cm = params(reglages, 'collision_monitor')
    assert (cm['base_frame_id'], cm['odom_frame_id']) == ('base_link', 'odom')
    assert params(reglages, 'bt_navigator')['global_frame'] == 'map'
    # speed_limit_topic : le défaut de Nav2, /speed_limit (au guide, section 11.4)
    assert 'speed_limit_topic' not in params(reglages, 'controller_server')
    assert params(reglages, 'velocity_smoother')['feedback'] == 'OPEN_LOOP'
