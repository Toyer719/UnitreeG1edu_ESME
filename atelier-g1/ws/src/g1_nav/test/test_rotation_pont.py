"""
Rotation finale du guide à travers le pont : la simulation de la chaîne (vague 5, section 12.6).

Ces tests figent le raisonnement qui fixe TOLERANCE_ORIENTATION_PONT_RAD (navigation.launch.py) :
avec la rotation minimale du pont (0,3 rad/s), le robot dépasse la flèche d'un angle presque
constant ; sous ce dépassement, le guide tournerait trois fois sans rien gagner.
"""
import ast
import math
from pathlib import Path

from atelier.lieu.robot import VITESSES_MIN_PONT, ZONES_MORTES_PONT
from g1_nav import rotation_pont as R
import pytest
import yaml

PAQUET = Path(__file__).resolve().parent.parent
PONT_YAML = PAQUET.parent / 'g1_bridge' / 'config' / 'pont.yaml'


def tolerance_du_lancement():
    """TOLERANCE_ORIENTATION_PONT_RAD de navigation.launch.py, lue sans lancer ROS."""
    arbre = ast.parse((PAQUET / 'launch' / 'navigation.launch.py').read_text(encoding='utf-8'))
    for noeud in arbre.body:
        if isinstance(noeud, ast.Assign) and any(
                isinstance(c, ast.Name) and c.id == 'TOLERANCE_ORIENTATION_PONT_RAD'
                for c in noeud.targets):
            return ast.literal_eval(noeud.value)
    raise AssertionError('TOLERANCE_ORIENTATION_PONT_RAD absente de navigation.launch.py')


def test_valeurs_de_la_chaine_egales_aux_reglages():
    """Spin, velocity_smoother et pont de la simulation : ceux du vrai robot."""
    with open(PAQUET / 'config' / 'nav2_g1_reel.yaml', encoding='utf-8') as f:
        reel = yaml.safe_load(f)
    secours = reel['behavior_server']['ros__parameters']
    assert secours['cycle_frequency'] == R.FREQUENCE_SPIN_HZ
    assert secours['min_rotational_vel'] == R.ROTATION_MIN_SPIN
    assert secours['max_rotational_vel'] == R.ROTATION_MAX_SPIN
    assert secours['rotational_acc_lim'] == R.ACCELERATION_SPIN
    lisseur = reel['velocity_smoother']['ros__parameters']
    assert lisseur['smoothing_frequency'] == R.FREQUENCE_LISSEUR_HZ
    assert lisseur['feedback'] == 'OPEN_LOOP'
    assert lisseur['max_accel'][2] == R.ACCELERATION_LISSEUR == -lisseur['max_decel'][2]
    pont = yaml.safe_load(PONT_YAML.read_text(encoding='utf-8'))['pont_g1']['ros__parameters']
    assert pont['frequence'] == R.FREQUENCE_PONT_HZ
    assert pont['vitesse_min_rot'] == VITESSES_MIN_PONT['rot']
    assert pont['zone_morte_rot'] == ZONES_MORTES_PONT['rot']


def test_consigne_du_pont():
    assert R.consigne_pont(0.15) == pytest.approx(0.3)          # montée au minimum
    assert R.consigne_pont(-0.2) == pytest.approx(-0.3)
    assert R.consigne_pont(0.05) == 0.0                         # zone morte
    assert R.consigne_pont(0.5) == pytest.approx(0.5)
    assert R.consigne_pont(2.0) == pytest.approx(0.6)           # plafond


def test_depassement_presque_constant_et_croissant_avec_le_retard():
    """Le robot finit à 0,3 rad/s au moins : il dépasse du même angle, petit ou grand."""
    depassements = [R.depassement(retard, constante) for retard, constante in R.CAS]
    assert depassements == sorted(depassements)
    assert all(math.radians(10) < d < math.radians(30) for d in depassements), depassements
    pour_un_angle = [R.depassement(0.2, 0.2, angle=math.radians(a)) for a in (15, 45, 90, 180)]
    assert max(pour_un_angle) - min(pour_un_angle) < math.radians(2.0), pour_un_angle
    assert R.rotation(-math.pi / 2, 0.2, 0.2) == pytest.approx(-R.rotation(math.pi / 2, 0.2, 0.2))


def test_sous_le_depassement_le_guide_tourne_trois_fois():
    """L'oscillation que la tolérance du lancement évite (10° de tolérance, le cap de la simu)."""
    n, ecart = R.guide(math.radians(90), 0.2, 0.2, tolerance=0.17)
    assert n == R.ESSAIS and abs(ecart) > 0.17


def test_tolerance_du_lancement_une_seule_rotation():
    """0,40 rad : une seule rotation si le robot répond en 0,5 s au plus (retard + constante)."""
    tolerance = tolerance_du_lancement()
    assert tolerance == pytest.approx(0.40)
    for retard, constante in R.CAS:
        if retard + constante <= 0.5 + 1e-9:
            rotations, pire = R.pire_cas(retard, constante, tolerance)
            assert rotations <= 1 and pire <= tolerance + 1e-9, (retard, constante, pire)


def test_anticipation_conseillee():
    """Anticipation = dépassement mesuré, tolérance 0,6 × : une rotation, 10° au plus."""
    for retard, constante in R.CAS:
        if retard + constante <= 0.5 + 1e-9:
            d = R.depassement(retard, constante)
            rotations, pire = R.pire_cas(retard, constante, 0.6 * d, anticipation=d)
            assert rotations <= 1 and pire < math.radians(10.5), (retard, constante, pire)


def test_commande_en_francais_avec_le_conseil(capsys):
    assert R.main(['--retard', '0.2', '--constante', '0.2']) == 0
    sortie = capsys.readouterr().out
    assert 'dépassement d\'une rotation de 90° 19,' in sortie
    assert 'ros2 param set /guide anticipation_rotation_rad 0.33' in sortie
    assert 'ros2 param set /guide tolerance_orientation_rad 0.20' in sortie
    assert R.main([]) == 0 and capsys.readouterr().out.count('dépassement') == len(R.CAS)


def test_valeur_illisible_refusee_en_francais(capsys):
    with pytest.raises(SystemExit) as fin:
        R.main(['--retard', 'vite'])
    assert fin.value.code == 2
    assert "erreur : argument --retard: nombre attendu, pas 'vite'" in capsys.readouterr().err
