"""
L'argument jumeau de g1_sim (section 10.4 du plan), sans Gazebo.

  - jumeau:=false (défaut) : les mêmes actions qu'avant, avec config/pont_gz.yaml ;
  - jumeau:=true : config/pont_gz_jumeau.yaml (/g1_jumeau/cmd_vel, /g1_jumeau/odom,
    /g1_jumeau/points, /clock ; rien sur /cmd_vel, /odom ni /tf) et le nœud g1_jumeau ;
  - g1-monde simuler --jumeau passe l'argument.
Les tests du paquet g1_sim (test_fichiers.py) vérifient, eux, que le reste n'a pas changé.
"""
import importlib.util
import os
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml

SOURCES = Path(__file__).resolve().parents[2]
G1_SIM = SOURCES / 'g1_sim'
LANCEMENT = G1_SIM / 'launch' / 'simulation.launch.py'
PONT_GZ = G1_SIM / 'config' / 'pont_gz.yaml'
PONT_JUMEAU = G1_SIM / 'config' / 'pont_gz_jumeau.yaml'
MODELE = G1_SIM / 'models' / 'g1_proxy' / 'model.sdf'
COULOIR = G1_SIM / 'worlds' / 'couloir.sdf'
RACINE = SOURCES.parents[1]

pytestmark = pytest.mark.skipif(not LANCEMENT.is_file(), reason='g1_sim absent des sources')


@pytest.fixture(scope='module')
def lancement():
    pytest.importorskip('launch')
    spec = importlib.util.spec_from_file_location('simulation_launch_jumeau', LANCEMENT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def regles(chemin):
    return {r['ros_topic_name']: r for r in yaml.safe_load(chemin.read_text())}


def test_argument_jumeau_faux_par_defaut(lancement):
    from launch.actions import DeclareLaunchArgument
    entites = lancement.generate_launch_description().entities
    arguments = {a.name: a for a in entites if isinstance(a, DeclareLaunchArgument)}
    # contrat 4.5 ; vague 4 (11.3) : pietons, de l'agent Passants
    assert set(arguments) - {'pietons'} == {'lieu', 'etage', 'sans_fenetre', 'monde', 'jumeau'}
    assert arguments['jumeau'].default_value[0].text == 'false'
    assert arguments['jumeau'].choices == ['true', 'false']


def test_ros2_launch_montre_l_argument():
    if shutil.which('ros2') is None:
        pytest.skip('ROS 2 non chargé')
    sortie = subprocess.run(['ros2', 'launch', 'g1_sim', 'simulation.launch.py', '--show-args'],
                            capture_output=True, text=True, timeout=60).stdout
    assert "'jumeau'" in sortie and "(default: 'false')" in sortie


def test_pont_gz_jumeau(lancement):
    """Mêmes sujets Gazebo que le modèle, mais rien sur /cmd_vel, /odom ni /tf côté ROS 2."""
    jumeau, normal = regles(PONT_JUMEAU), regles(PONT_GZ)
    assert set(jumeau) == {'/clock', '/g1_jumeau/cmd_vel', '/g1_jumeau/odom', '/g1_jumeau/points'}
    correspondance = {'/clock': '/clock', '/g1_jumeau/cmd_vel': '/cmd_vel',
                      '/g1_jumeau/odom': '/odom', '/g1_jumeau/points': '/points'}
    for sujet, ancien in correspondance.items():
        a, b = jumeau[sujet], normal[ancien]
        assert (a['gz_topic_name'], a['ros_type_name'], a['gz_type_name'], a['direction']) == (
            b['gz_topic_name'], b['ros_type_name'], b['gz_type_name'], b['direction']), sujet
    gz = {r['gz_topic_name'] for r in jumeau.values()}
    assert '/model/g1_proxy/tf' not in gz
    # Les sujets Gazebo sont bien ceux du modèle
    modele = ET.parse(MODELE).getroot().find('model')
    plugins = {p.get('name'): p for p in modele.findall('plugin')}
    assert jumeau['/g1_jumeau/cmd_vel']['gz_topic_name'] == plugins[
        'ignition::gazebo::systems::VelocityControl'].findtext('topic')
    assert jumeau['/g1_jumeau/odom']['gz_topic_name'] == plugins[
        'ignition::gazebo::systems::OdometryPublisher'].findtext('odom_topic')


def test_fichier_pont(lancement, tmp_path):
    partage = tmp_path / 'share'
    (partage / 'config').mkdir(parents=True)
    assert lancement.fichier_pont(partage, False) == partage / 'config' / 'pont_gz.yaml'
    # Paquet installé avant l'ajout du fichier (--symlink-install) : repli sur les sources
    assert lancement.fichier_pont(partage, True) == PONT_JUMEAU
    (partage / 'config' / 'pont_gz_jumeau.yaml').write_text('[]')
    assert lancement.fichier_pont(partage, True) == partage / 'config' / 'pont_gz_jumeau.yaml'


def _actions(lancement, tmp_path, jumeau):
    from launch import LaunchContext
    (tmp_path / 'mondes').mkdir(exist_ok=True)
    shutil.copy(COULOIR, tmp_path / 'mondes' / 'rdc.sdf')
    shutil.copy(COULOIR.with_name('couloir.monde.yaml'), tmp_path / 'mondes' / 'rdc.monde.yaml')
    contexte = LaunchContext()
    contexte.launch_configurations.update({
        'lieu': str(tmp_path), 'etage': 'rdc', 'sans_fenetre': 'true', 'monde': '',
        'jumeau': 'true' if jumeau else 'false',
        'pietons': 'acteurs'})            # vague 4 : les <actor> d'avant, sans nœud pietons
    return contexte, lancement._lancer(contexte)


def _noeuds(actions):
    from launch_ros.actions import Node
    return [(a.node_package, a.node_executable) for a in actions if isinstance(a, Node)]


def _config_du_pont(contexte, actions):
    from launch_ros.actions import Node
    from launch_ros.utilities import evaluate_parameters
    for a in actions:
        if isinstance(a, Node) and a.node_executable == 'parameter_bridge':
            parametres = evaluate_parameters(contexte, a._Node__parameters)
            return Path(parametres[0]['config_file'])
    raise AssertionError('pas de parameter_bridge')


def test_actions_sans_jumeau_inchangees(lancement, tmp_path):
    contexte, actions = _actions(lancement, tmp_path, False)
    assert _noeuds(actions) == [('ros_gz_sim', 'create'), ('ros_gz_bridge', 'parameter_bridge'),
                                ('robot_state_publisher', 'robot_state_publisher')]
    assert _config_du_pont(contexte, actions).name == 'pont_gz.yaml'
    from launch.actions import LogInfo
    # Gazebo, 3 nœuds, 2 surveillances (comme avant) ; les messages (LogInfo) peuvent varier
    assert len([a for a in actions if not isinstance(a, LogInfo)]) == 6


def test_actions_avec_jumeau(lancement, tmp_path):
    pytest.importorskip('ament_index_python')
    from ament_index_python.packages import get_package_prefix, PackageNotFoundError
    try:
        get_package_prefix('g1_jumeau')
    except PackageNotFoundError:
        pytest.skip('g1_jumeau pas compilé')
    contexte, actions = _actions(lancement, tmp_path, True)
    assert _noeuds(actions) == [('ros_gz_sim', 'create'), ('ros_gz_bridge', 'parameter_bridge'),
                                ('robot_state_publisher', 'robot_state_publisher'),
                                ('g1_jumeau', 'jumeau')]
    assert _config_du_pont(contexte, actions).name == 'pont_gz_jumeau.yaml'


def test_jumeau_sans_paquet_message_clair(lancement, monkeypatch):
    import ament_index_python.packages as paquets

    def absent(nom):
        raise paquets.PackageNotFoundError(nom)
    monkeypatch.setattr(paquets, 'get_package_prefix', absent)
    with pytest.raises(lancement.ErreurSimulation, match='colcon build .*g1_jumeau'):
        lancement.noeud_jumeau()


def test_g1_monde_simuler_jumeau(tmp_path):
    commande = RACINE / 'bin' / 'g1-monde'
    if not commande.is_file():
        pytest.skip('bin/g1-monde absent')
    lieu = tmp_path / 'lieu'
    shutil.copytree(RACINE / 'lieux' / 'demo', lieu)
    env = dict(os.environ)
    assert subprocess.run([str(commande), 'generer', '--lieu', str(lieu), '--etage', 'rdc'],
                          capture_output=True, text=True, env=env).returncode == 0

    def simuler(*options):
        r = subprocess.run([str(commande), 'simuler', '--lieu', str(lieu), '--etage', 'rdc',
                            '--sans-fenetre', '--afficher', *options],
                           capture_output=True, text=True, env=env)
        assert r.returncode == 0, r.stdout + r.stderr
        return r.stdout.strip().splitlines()[-1]
    assert simuler('--jumeau') == (f'ros2 launch g1_sim simulation.launch.py lieu:={lieu} '
                                   'etage:=rdc sans_fenetre:=true jumeau:=true')
    assert simuler().endswith('sans_fenetre:=true')
