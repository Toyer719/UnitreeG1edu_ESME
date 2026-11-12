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

    Tranche de 1,375 à 1,9 m (une personne debout) : le chemin contourne les personnes au lieu
    de passer à travers (MPPI restait bloqué devant). Rien plus bas dans la carte globale : elle
    n'est pas vidée chaque seconde (les voxels bas n'y seraient jamais effacés), et une boîte de
    1,2 m n'y entre pas.
    """
    p = params(reglages, 'global_costmap', 'global_costmap')
    assert p['plugins'] == ['static_layer', 'voxel_layer', 'inflation_layer']
    voxels = p['voxel_layer']
    sources = [voxels[nom] for nom in voxels['observation_sources'].split()]
    for s in sources:
        assert s['topic'] == '/points' and s['data_type'] == 'PointCloud2'
    marquage = [s for s in sources if s['marking']]
    # une personne debout (1,7 m) y est ; une boîte, une table, un comptoir (1,2 m) n'y sont pas :
    # sinon Nav2 bascule entre deux chemins devant une boîte qui bouche le couloir (critères 5, 19)
    assert marquage and min(s['min_obstacle_height'] for s in marquage) > 1.25
    assert min(s['min_obstacle_height'] for s in marquage) <= 1.5
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


def dans_polygone(points, x, y):
    """Vrai si le point (x, y) est dans le polygone [x1, y1, x2, y2...] (lancer de rayon)."""
    sommets = list(zip(points[0::2], points[1::2]))
    dedans = False
    for (xa, ya), (xb, yb) in zip(sommets, sommets[1:] + sommets[:1]):
        if (ya > y) != (yb > y) and x < xa + (y - ya) * (xb - xa) / (yb - ya):
            dedans = not dedans
    return dedans


def zone_touchee(zone, x, y):
    """Vrai si un obstacle en (x, y) de base_link déclenche cette zone du Collision Monitor."""
    if zone['type'] == 'circle':
        return math.hypot(x, y) <= zone['radius']
    return dans_polygone(zone['points'], x, y)


def test_collision_monitor(reglages):
    p = params(reglages, 'collision_monitor')
    assert p['cmd_vel_in_topic'] == 'cmd_vel_smoothed' and p['cmd_vel_out_topic'] == 'cmd_vel'
    assert p['polygons'] == ['ralentir', 'ralentir_pres', 'arret']
    arret = p['arret']
    assert p['ralentir']['action_type'] == 'slowdown'          # zone : test suivant
    assert arret['action_type'] == 'stop' and arret['type'] == 'circle'
    assert arret['radius'] >= 0.4                                          # contrat 11.3
    source = p[p['observation_sources'][0]]
    assert source['type'] == 'pointcloud' and source['topic'] == '/points'
    assert source['min_height'] <= 0.15      # obstacles bas


def test_ralentir_devant_seulement(reglages):
    """
    Vague 4 : ralentir quand quelque chose est DEVANT le robot, pas derrière.

    Le cercle de 1 m tout autour freinait le robot quand le visiteur le suit à 1,2 m (sa surface à
    0,95 m) : un robot accompagné roulait à mi-vitesse. La zone est la moitié avant de ce cercle :
    devant, rien ne change (une zone qui porte plus loin faisait rester le robot sur le passage
    d'un passant qui coupe la route : critère 24) ; derrière, rien ne freine.
    """
    ralentir = params(reglages, 'collision_monitor')['ralentir']
    assert (ralentir['type'], ralentir['action_type']) == ('polygon', 'slowdown')
    assert ralentir['slowdown_ratio'] == 0.5
    assert all(isinstance(v, float) for v in ralentir['points'])   # ROS 2 : un seul type
    xs, ys = ralentir['points'][0::2], ralentir['points'][1::2]
    assert len(xs) == len(ys) >= 3
    assert min(xs) >= 0.0                       # rien derrière l'axe du robot
    # Devant et sur les côtés avant : le cercle de 1 m, à 2 cm près
    for k in range(-6, 7):
        angle = math.radians(15 * k + 7.5 * (k < 6))
        if abs(angle) > math.pi / 2:
            continue
        assert zone_touchee(ralentir, 0.98 * math.cos(angle), 0.98 * math.sin(angle)), k
        assert not zone_touchee(ralentir, 1.02 * math.cos(angle), 1.02 * math.sin(angle)), k
    for x, y in ((0.45, 0.0), (0.6, 0.55), (0.6, -0.55), (0.3, 0.85), (0.95, 0.0)):
        assert zone_touchee(ralentir, x, y), (x, y)
    # Le visiteur qui suit à 1,2 m derrière (ou en biais derrière) : pas de ralentissement
    for x, y in ((-1.2, 0.0), (-1.0, 0.4), (-0.95, -0.3), (-0.5, 0.0), (-0.05, 0.6)):
        assert not zone_touchee(ralentir, x, y), (x, y)
    # Un mur de couloir (2,85 m libres, robot au milieu) ne freine pas le robot qui longe
    assert not zone_touchee(ralentir, 0.5, 1.4) and not zone_touchee(ralentir, 0.5, -1.4)


def test_ralentir_tout_pres(reglages):
    """
    Vague 4 : ralentir aussi quand une personne est tout près, sur le côté ou derrière.

    Sans cette zone (demi-disque seul), un contact causé par le robot sur cinq trajets dans
    coupe_route (critère 24) : le robot qui tourne ou se déplace de côté près d'un passant. Le
    visiteur qui suit à 1,2 m (sa surface à 0,95 m) reste dehors, avec 0,25 m de marge.
    """
    cm = params(reglages, 'collision_monitor')
    pres, arret = cm['ralentir_pres'], cm['arret']
    assert (pres['type'], pres['action_type'], pres['slowdown_ratio']) == \
        ('circle', 'slowdown', 0.5)
    assert arret['radius'] + 0.2 <= pres['radius'] <= 0.95 - 0.2
    for x, y in ((-0.6, 0.0), (0.0, 0.65), (-0.4, -0.4)):      # tout près, côté ou derrière
        assert zone_touchee(pres, x, y), (x, y)
    for x, y in ((-0.95, 0.0), (-0.7, 0.6), (-0.5, -0.8)):     # surface du visiteur, derrière
        assert not any(zone_touchee(cm[nom], x, y) for nom in cm['polygons']), (x, y)


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
                  'max_rotational_vel', 'vx_min'}         # vx_min : vague 5, pas de recul
    assert set(differences) <= autorisees, set(differences) - autorisees


def test_pas_de_marche_arriere_sur_le_vrai_robot():
    """Vague 5 (section 12.6) : le pont monte un petit recul à 0,2 m/s : Nav2 n'en demande plus."""
    reel = charger('nav2_g1_reel.yaml')
    assert params(reel, 'controller_server')['FollowPath']['vx_min'] == 0.0
    assert params(reel, 'velocity_smoother')['min_velocity'] == [0.0, -0.2, -0.6]
    simu = charger('nav2_g1_simu.yaml')          # la simulation, sans pont, garde son recul
    assert params(simu, 'controller_server')['FollowPath']['vx_min'] == -0.2


def test_rotation_des_secours_au_moins_le_minimum_du_pont():
    """Spin (behavior_server) ne commande jamais moins que la rotation minimale du pont."""
    pont = Path(__file__).resolve().parents[2] / 'g1_bridge' / 'config' / 'pont.yaml'
    minimum = yaml.safe_load(pont.read_text(encoding='utf-8'))['pont_g1']['ros__parameters'][
        'vitesse_min_rot']
    for nom in ('nav2_g1_reel.yaml', 'nav2_g1_simu.yaml'):
        secours = params(charger(nom), 'behavior_server')
        assert secours['min_rotational_vel'] >= minimum, nom
        assert secours['max_rotational_vel'] >= secours['min_rotational_vel'], nom


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
