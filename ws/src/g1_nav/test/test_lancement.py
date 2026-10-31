"""
Tests de launch/navigation.launch.py : arguments du contrat et nœuds lancés.

Arguments de la section 4.5 du plan, et nœuds lancés selon simu et moteur. Rien n'est lancé :
on regarde seulement la liste des actions.

Il faut les paquets launch de ROS 2 (source ~/robot-g1/setup/env.sh) ; sinon les tests sont
sautés.

  python3 -m pytest ~/robot-g1/ws/src/g1_nav/test/test_lancement.py -v
"""
import importlib.util
from pathlib import Path

from atelier import RACINE
from atelier.lieu import copier_lieu
import pytest
import yaml

pytest.importorskip('launch_ros')
from launch import LaunchContext  # noqa: E402
from launch.actions import DeclareLaunchArgument, LogInfo  # noqa: E402
from launch_ros.actions import Node  # noqa: E402

PAQUET = Path(__file__).resolve().parent.parent


@pytest.fixture
def lancement(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        'navigation_launch', PAQUET / 'launch' / 'navigation.launch.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Les réglages sont lus dans les sources, sans avoir besoin de compiler g1_nav
    monkeypatch.setattr(module, 'get_package_share_directory', lambda paquet: str(PAQUET))
    return module


@pytest.fixture
def dossier(tmp_path):
    from atelier.monde import generer
    dossier = copier_lieu(RACINE / 'lieux' / 'demo', tmp_path / 'demo')
    generer(dossier, 'rdc')
    return dossier


def actions(module, lieu, etage='rdc', simu='true', moteur='nav2', localisation='', pont='auto',
            nuage='', vitesse_max='', personnes=None):
    contexte = LaunchContext()
    contexte.launch_configurations.update(
        {'lieu': str(lieu), 'etage': etage, 'simu': simu, 'moteur': moteur,
         'localisation': localisation, 'pont': pont, 'nuage': nuage, 'vitesse_max': vitesse_max})
    if personnes is not None:
        contexte.launch_configurations['personnes'] = personnes
    return module._lancer(contexte)


def noeuds(liste):
    """Nœuds lancés, rangés par nom (ou par exécutable s'ils n'ont pas de name=)."""
    return {a._Node__node_name or a._Node__node_executable: a
            for a in liste if isinstance(a, Node)}


def parametres(noeud):
    """Dictionnaires de paramètres d'un nœud, fusionnés (les fichiers sont ignorés)."""
    fusion = {}
    for p in noeud._Node__parameters:
        if isinstance(p, dict):
            fusion.update({str(k[0].text if isinstance(k, tuple) else k): v for k, v in p.items()})
    return fusion


def texte(valeur):
    """Valeur de paramètre : chaîne simple, liste de substitutions, ou fichier de paramètres."""
    if isinstance(valeur, str):
        return valeur
    if hasattr(valeur, '_ParameterFile__param_file'):
        return texte(valeur._ParameterFile__param_file)
    t = ''.join(getattr(s, 'text', str(s)) for s in valeur)
    # launch_ros range certaines chaînes en YAML (« ...\n...\n ») : on les relit
    return yaml.safe_load(t) if t.endswith('\n...\n') else t


def test_arguments_du_contrat(lancement):
    description = lancement.generate_launch_description()
    arguments = {a.name: a for a in description.entities if isinstance(a, DeclareLaunchArgument)}
    # sections 4.5 et 10.7 ; nuage et vitesse_max : ajouts (source du nuage du relais, premiers
    # essais à vitesse réduite)
    assert set(arguments) == {'lieu', 'etage', 'simu', 'moteur', 'localisation', 'pont', 'nuage',
                              'vitesse_max', 'personnes'}
    # vague 4 (section 11.4 du plan) : détecteur de personnes au LiDAR, lancé par défaut
    assert texte(arguments['personnes'].default_value) == 'true'
    assert texte(arguments['vitesse_max'].default_value) == ''
    assert texte(arguments['simu'].default_value) == 'false'
    assert texte(arguments['moteur'].default_value) == 'nav2'
    assert {'nav2', 'unitree'} <= set(arguments['moteur'].choices)
    assert texte(arguments['localisation'].default_value) == ''
    assert texte(arguments['pont'].default_value) == 'auto'
    assert set(arguments['pont'].choices) == {'auto', 'true', 'false'}


def test_simulation_avec_nav2(lancement, dossier):
    n = noeuds(actions(lancement, dossier, simu='true', moteur='nav2'))
    for nom in ['map_server', 'filter_mask_server', 'costmap_filter_info_server',
                'lifecycle_manager_carte', 'repere_map_odom', 'controller_server',
                'planner_server', 'behavior_server', 'bt_navigator', 'velocity_smoother',
                'collision_monitor', 'lifecycle_manager_navigation', 'guide']:
        assert nom in n, f'{nom} manque'
    assert 'odom_vers_tf' not in n
    assert texte(parametres(n['map_server'])['yaml_filename']) == \
        str(dossier / 'cartes' / 'rdc.yaml')
    assert texte(parametres(n['filter_mask_server'])['yaml_filename']) == \
        str(dossier / 'cartes' / 'rdc_interdit.yaml')
    fichiers = [p for p in n['controller_server']._Node__parameters if not isinstance(p, dict)]
    assert any('nav2_g1_simu.yaml' in texte(f) for f in fichiers)
    guide = parametres(n['guide'])
    assert texte(guide['moteur']) == 'nav2' and texte(guide['lieu']) == str(dossier)
    assert parametres(n['controller_server'])['use_sim_time'] is True
    # map → odom fixe, identité
    assert [texte(a) for a in n['repere_map_odom']._Node__arguments] == \
        ['--frame-id', 'map', '--child-frame-id', 'odom']
    # Arbre de comportement du guide (nœuds passés à 1,5 m, carte locale vidée chaque seconde)
    arbre = Path(texte(parametres(n['bt_navigator'])['default_nav_through_poses_bt_xml']))
    assert arbre.name == 'naviguer_par_poses.xml' and arbre.is_file()
    # Le Collision Monitor est géré par le lifecycle_manager de la navigation
    gestion = parametres(n['lifecycle_manager_navigation'])
    assert 'collision_monitor' in [texte(nom) for nom in gestion['node_names']]


def test_vrai_robot_avec_moteur_unitree(lancement, dossier):
    n = noeuds(actions(lancement, dossier, simu='false', moteur='unitree'))
    assert {'map_server', 'odom_vers_tf', 'repere_base_lidar', 'guide'} <= set(n)
    # map → odom vient du relais (relocalisation d'Unitree), plus d'identité fixe
    assert 'repere_map_odom' not in n
    for nom in ['controller_server', 'bt_navigator', 'collision_monitor', 'filter_mask_server']:
        assert nom not in n, f'{nom} ne devrait pas être lancé avec moteur:=unitree'
    # sans Nav2, pas de pont (pont:=auto)
    assert 'pont_g1' not in n
    assert texte(parametres(n['guide'])['moteur']) == 'unitree'
    assert parametres(n['guide'])['use_sim_time'] is False


def test_reglages_du_vrai_robot(lancement, dossier):
    n = noeuds(actions(lancement, dossier, simu='false', moteur='nav2'))
    fichiers = [p for p in n['planner_server']._Node__parameters if not isinstance(p, dict)]
    assert any('nav2_g1_reel.yaml' in texte(f) for f in fichiers)


def test_lieu_par_son_id(lancement, dossier, monkeypatch):
    monkeypatch.setenv('ATELIER_LIEUX', str(dossier.parent))
    n = noeuds(actions(lancement, 'demo'))
    assert texte(parametres(n['guide'])['lieu']) == str(dossier)


def test_carte_absente(lancement, tmp_path):
    dossier = copier_lieu(RACINE / 'lieux' / 'demo', tmp_path / 'sans_carte')
    for fichier in (dossier / 'cartes').glob('rdc.*'):
        fichier.unlink()
    with pytest.raises(lancement.ErreurNavigation, match='g1-monde generer'):
        actions(lancement, dossier)
    with pytest.raises(lancement.ErreurNavigation, match="n'existe pas"):
        actions(lancement, tmp_path / 'lieu_absent')


def test_masque_absent_remplace_par_un_masque_vide(lancement, dossier):
    (dossier / 'cartes' / 'rdc_interdit.yaml').unlink()
    liste = actions(lancement, dossier)
    masque = Path(texte(parametres(noeuds(liste)['filter_mask_server'])['yaml_filename']))
    assert masque.is_file() and masque.parent != dossier / 'cartes'
    from atelier.lieu import charger_carte
    info, image = charger_carte(masque)
    assert image.shape == (402, 602) and (image == 254).all()
    messages = [texte(a.msg) for a in liste if isinstance(a, LogInfo)]
    assert any('aucune zone interdite' in m for m in messages)


# ---------------------------------------------------------------- vague 3 : localisation et pont

def _fichiers(noeud):
    return [texte(f) for f in noeud._Node__parameters if not isinstance(f, dict)]


def test_simulation_sans_relais_ni_pont(lancement, dossier):
    n = noeuds(actions(lancement, dossier, simu='true'))
    assert 'repere_map_odom' in n
    for nom in ('odom_vers_tf', 'pont_g1', 'amcl', 'repere_base_lidar'):
        assert nom not in n


def test_repetition_unitree(lancement, dossier):
    """Répétition : temps simulé, relais avec le repère du lieu, pont, réglages du vrai robot."""
    n = noeuds(actions(lancement, dossier, simu='true', localisation='unitree'))
    assert {'odom_vers_tf', 'pont_g1', 'bt_navigator', 'guide'} <= set(n)
    assert 'repere_map_odom' not in n
    # base_link → lidar : publié par g1_sim en répétition
    assert 'repere_base_lidar' not in n
    relais = parametres(n['odom_vers_tf'])
    assert texte(relais['localisation']) == 'unitree'
    assert [float(v) for v in relais['repere_unitree']] == [2.5, 10.0, 0.0]   # départ du robot
    assert texte(relais['carte']) == 'repetition.pcd'
    assert texte(relais['nuage']) == '/unitree/slam_relocation/points'
    assert relais['use_sim_time'] is True
    assert any('nav2_g1_reel.yaml' in f for f in _fichiers(n['controller_server']))
    assert parametres(n['controller_server'])['use_sim_time'] is True
    # le pont compte en temps mural : pas de use_sim_time
    assert 'use_sim_time' not in parametres(n['pont_g1'])


def test_repetition_repere_unitree_tourne(lancement, dossier):
    from atelier.lieu import charger_fiche, enregistrer_fiche, Pose
    fiche = charger_fiche(dossier)
    fiche.etages[0].repere_unitree = Pose(3.0, 9.0, 0.5)
    fiche.carte_unitree = 'rdc_e2e.pcd'
    enregistrer_fiche(fiche)
    n = noeuds(actions(lancement, dossier, localisation='unitree'))
    relais = parametres(n['odom_vers_tf'])
    assert [float(v) for v in relais['repere_unitree']] == [3.0, 9.0, 0.5]
    assert texte(relais['carte']) == 'rdc_e2e.pcd'


def test_robot_unitree(lancement, dossier):
    """Vrai robot : relais, base_link → lidar fixe, pont, sans carte_unitree le relais le dira."""
    liste = actions(lancement, dossier, simu='false')
    n = noeuds(liste)
    assert {'odom_vers_tf', 'repere_base_lidar', 'pont_g1'} <= set(n)
    assert yaml.safe_load(texte(parametres(n['odom_vers_tf'])['carte'])) in ('', None)
    arguments = [texte(a) for a in n['repere_base_lidar']._Node__arguments]
    assert arguments[arguments.index('--z') + 1] == '1.245'
    assert arguments[-4:] == ['--frame-id', 'base_link', '--child-frame-id', 'lidar']
    messages = [texte(a.msg) for a in liste if isinstance(a, LogInfo)]
    assert any('pas de carte_unitree' in m for m in messages)


def test_amcl_en_repetition(lancement, dossier):
    n = noeuds(actions(lancement, dossier, simu='true', localisation='amcl'))
    assert {'odom_vers_tf', 'nuage_vers_scan', 'amcl', 'lifecycle_manager_localisation',
            'pont_g1'} <= set(n)
    relais = parametres(n['odom_vers_tf'])
    assert texte(relais['localisation']) == 'amcl'
    assert texte(relais['nuage']) == '/g1_jumeau/points'
    assert texte(relais['points_repere']) == 'capteur'
    scan = parametres(n['nuage_vers_scan'])
    assert (scan['min_height'], scan['max_height']) == (0.1, 1.5)
    assert texte(scan['target_frame']) == 'base_link'
    assert dict((texte(a), texte(b)) for a, b in n['nuage_vers_scan']._Node__remappings) == \
        {'cloud_in': '/points', 'scan': '/scan'}
    assert any(f.endswith('amcl_g1.yaml') and Path(f).is_file() for f in _fichiers(n['amcl']))
    gestion = parametres(n['lifecycle_manager_localisation'])
    assert [texte(x) for x in gestion['node_names']] == ['amcl']


def test_externe(lancement, dossier):
    n = noeuds(actions(lancement, dossier, simu='true', localisation='externe', pont='true'))
    for nom in ('odom_vers_tf', 'repere_map_odom', 'amcl'):
        assert nom not in n
    assert 'pont_g1' in n


def test_pont_force(lancement, dossier):
    assert 'pont_g1' not in noeuds(actions(lancement, dossier, localisation='unitree',
                                           pont='false'))
    assert 'pont_g1' in noeuds(actions(lancement, dossier, localisation='simu', pont='true'))


def test_pont_absent(lancement, dossier, monkeypatch):
    monkeypatch.setattr(lancement, 'partage', lambda paquet: None)
    with pytest.raises(lancement.ErreurNavigation, match='g1_bridge'):
        actions(lancement, dossier, localisation='unitree')
    # sans pont, rien ne manque
    assert 'odom_vers_tf' in noeuds(actions(lancement, dossier, localisation='unitree',
                                            pont='false'))


@pytest.mark.parametrize('localisation, simu, message', [
    ('gps', 'true', 'inconnue'), ('simu', 'false', 'simu:=true')])
def test_localisation_refusee(lancement, dossier, localisation, simu, message):
    with pytest.raises(lancement.ErreurNavigation, match=message):
        actions(lancement, dossier, simu=simu, localisation=localisation)


def test_vitesse_reduite(lancement, dossier):
    """vitesse_max:=0.2 : plafonds du pont abaissés dans la même proportion (premiers essais)."""
    sans = parametres(noeuds(actions(lancement, dossier, localisation='unitree'))['pont_g1'])
    assert not {'vx_max', 'vy_max', 'wz_max'} & set(sans)      # ceux de config/pont.yaml
    pont = noeuds(actions(lancement, dossier, localisation='unitree',
                          vitesse_max='0.2'))['pont_g1']
    assert {k: parametres(pont)[k] for k in ('vx_max', 'vy_max', 'wz_max')} == {
        'vx_max': 0.2, 'vy_max': 0.125, 'wz_max': 0.3}
    assert lancement.plafonds_pont('0,25') == {'vx_max': 0.25, 'vy_max': 0.156, 'wz_max': 0.375}
    assert lancement.plafonds_pont('0.4') == {'vx_max': 0.4, 'vy_max': 0.25, 'wz_max': 0.6}
    assert lancement.plafonds_pont(' ') is None


@pytest.mark.parametrize('valeur', ['0', '-0.1', '0.5', '1e9', 'nan', 'inf', 'vite', '0.15',
                                    '0,1', '0.199'])
def test_vitesse_reduite_refusee(lancement, dossier, valeur):
    """Jamais au-delà des plafonds du contrat, jamais nulle, négative, illisible ou sous 0,2."""
    with pytest.raises(lancement.ErreurNavigation, match='vitesse_max'):
        actions(lancement, dossier, localisation='unitree', vitesse_max=valeur)


def test_vitesse_sous_0_2_refusee_avec_le_message_du_contrat(lancement):
    from atelier.lieu.robot import MESSAGE_VITESSE_MAX_BASSE
    with pytest.raises(lancement.ErreurNavigation, match=MESSAGE_VITESSE_MAX_BASSE):
        lancement.plafonds_pont('0.15')
    assert lancement.plafonds_pont('0.2')['vx_max'] == 0.2


def test_vitesse_reduite_aussi_pour_nav2(lancement, dossier):
    """Vague 5 (section 12.6) : vitesse_max:=0.25 baisse aussi le contrôleur et le lisseur."""
    liste = actions(lancement, dossier, localisation='unitree', vitesse_max='0.25')
    n = noeuds(liste)
    controleur = parametres(n['controller_server'])
    assert {k: controleur[k] for k in ('FollowPath.vx_max', 'FollowPath.vy_max',
                                       'FollowPath.wz_max')} == {
        'FollowPath.vx_max': 0.25, 'FollowPath.vy_max': 0.125, 'FollowPath.wz_max': 0.375}
    lisseur = parametres(n['velocity_smoother'])
    assert list(lisseur['max_velocity']) == [0.25, 0.125, 0.375]       # launch_ros : un tuple
    assert list(lisseur['min_velocity']) == [0.0, -0.125, -0.375]
    guide = parametres(n['guide'])
    assert guide['vitesse_max_nav2'] == pytest.approx(0.25)
    assert guide['pourcentage_min'] == pytest.approx(80.0)      # 0,2 m/s sur 0,25
    # sans vitesse_max : rien d'ajouté, les fichiers de réglages font foi
    n = noeuds(actions(lancement, dossier, localisation='unitree'))
    assert 'FollowPath.vx_max' not in parametres(n['controller_server'])
    assert 'max_velocity' not in parametres(n['velocity_smoother'])
    # sans pont (simulation) : vitesse_max ignorée, comme avant
    liste = actions(lancement, dossier, simu='true', vitesse_max='0.25')
    assert 'FollowPath.vx_max' not in parametres(noeuds(liste)['controller_server'])
    assert any('vitesse_max ignorée' in texte(a.msg) for a in liste if isinstance(a, LogInfo))


def test_reglages_du_guide_avec_le_pont(lancement, dossier):
    """Avec le pont : tolérance de cap relevée, ralenti jamais sous la vitesse minimale."""
    guide = parametres(noeuds(actions(lancement, dossier, localisation='unitree'))['guide'])
    assert guide['tolerance_orientation_rad'] == lancement.TOLERANCE_ORIENTATION_PONT_RAD == 0.4
    assert guide['pourcentage_min'] == pytest.approx(50.0)      # 0,2 m/s sur 0,4
    assert guide['vitesse_max_nav2'] == pytest.approx(0.4)
    # simulation sans pont : les valeurs du guide (0,09 rad, 10 %), rien n'est passé
    guide = parametres(noeuds(actions(lancement, dossier, simu='true'))['guide'])
    assert 'tolerance_orientation_rad' not in guide and 'pourcentage_min' not in guide
    # répétition par le pont (localisation externe) : comme le vrai robot
    guide = parametres(noeuds(actions(lancement, dossier, simu='true', localisation='externe',
                                      pont='true'))['guide'])
    assert guide['tolerance_orientation_rad'] == 0.4


def detecteur(liste):
    """
    Renvoie le détecteur de personnes et ses paramètres en texte, ou (None, None).

    Un Node, ou un ExecuteProcess (python3 -m) si g1_nav a été compilé avant son ajout.
    """
    from launch.actions import ExecuteProcess
    for a in liste:
        if isinstance(a, Node):
            if a._Node__node_name == 'detecteur_personnes':
                return a, {k: v if isinstance(v, (bool, int, float)) else texte(v)
                           for k, v in parametres(a).items()}
        elif isinstance(a, ExecuteProcess) and a.name and texte(a.name) == 'detecteur_personnes':
            cmd = [texte(c) for c in a.cmd]
            assert 'g1_nav.personnes' in cmd and '__node:=detecteur_personnes' in cmd
            p = dict(cmd[i + 1].split(':=', 1) for i, c in enumerate(cmd) if c == '-p')
            return a, p
    return None, None


def test_detecteur_de_personnes(lancement, dossier):
    """Vague 4 (section 11.4) : personnes:=true par défaut, avec le lieu pour la carte."""
    liste = actions(lancement, dossier, simu='true', moteur='nav2')
    action, p = detecteur(liste)
    assert action is not None, 'detecteur_personnes manque'
    assert str(p['lieu']) == str(dossier) and p['etage'] == 'rdc'
    guide = parametres(noeuds(liste)['guide'])
    assert 'accompagnement' not in guide and 'passants' not in guide
    assert guide['vitesse_max_nav2'] == pytest.approx(0.5)      # vx_max de nav2_g1_simu.yaml
    # personnes:=false : ni détecteur, ni accompagnement, ni attente des passants
    liste = actions(lancement, dossier, simu='true', moteur='nav2', personnes='false')
    assert detecteur(liste) == (None, None)
    guide = parametres(noeuds(liste)['guide'])
    assert guide['accompagnement'] is False and guide['passants'] is False
    # Aussi sur le vrai robot
    action, p = detecteur(actions(lancement, dossier, simu='false', moteur='nav2'))
    assert action is not None
