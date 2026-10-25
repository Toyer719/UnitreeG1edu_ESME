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


def actions(module, lieu, etage='rdc', simu='true', moteur='nav2'):
    contexte = LaunchContext()
    contexte.launch_configurations.update(
        {'lieu': str(lieu), 'etage': etage, 'simu': simu, 'moteur': moteur})
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
    assert set(arguments) == {'lieu', 'etage', 'simu', 'moteur'}
    assert texte(arguments['simu'].default_value) == 'false'
    assert texte(arguments['moteur'].default_value) == 'nav2'
    assert {'nav2', 'unitree'} <= set(arguments['moteur'].choices)


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
    assert {'map_server', 'odom_vers_tf', 'repere_map_odom', 'guide'} <= set(n)
    for nom in ['controller_server', 'bt_navigator', 'collision_monitor', 'filter_mask_server']:
        assert nom not in n, f'{nom} ne devrait pas être lancé avec moteur:=unitree'
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
