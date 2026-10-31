"""
Test du nœud ROS 2 du guide avec le moteur factice : /guide/aller, /guide/stop, /guide/etat.

Sans Gazebo ni Nav2. Le nœud tourne dans un sous-processus, sur ROS_DOMAIN_ID (33 par défaut).
Il faut rclpy (source ~/robot-g1/setup/env.sh) ; sinon le test est sauté.

  ROS_DOMAIN_ID=33 python3 -m pytest ~/robot-g1/ws/src/g1_nav/test/test_noeud_guide.py -v
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from atelier import RACINE
from atelier.lieu import copier_lieu
import pytest

rclpy = pytest.importorskip('rclpy')
from std_msgs.msg import Empty, String  # noqa: E402

PAQUET = Path(__file__).resolve().parent.parent
DOMAINE = int(os.environ.get('ROS_DOMAIN_ID') or 33)


def environnement():
    env = dict(os.environ, ROS_DOMAIN_ID=str(DOMAINE), PYTHONUNBUFFERED='1')
    env['PYTHONPATH'] = os.pathsep.join([str(PAQUET), str(RACINE), env.get('PYTHONPATH', '')])
    return env


def lancer_guide(dossier, moteur='factice', **parametres):
    commande = [sys.executable, '-m', 'g1_nav.guide', '--ros-args', '-p', f'lieu:={dossier}',
                '-p', 'etage:=rdc', '-p', f'moteur:={moteur}', '-p', 'vitesse_factice:=4.0']
    for nom, valeur in parametres.items():
        commande += ['-p', f'{nom}:={valeur}']
    return subprocess.Popen(commande, env=environnement(), stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, start_new_session=True)


class Ecoute:
    """Nœud de test : publie les commandes et garde les états reçus."""

    def __init__(self):
        self.contexte = rclpy.Context()
        rclpy.init(context=self.contexte, domain_id=DOMAINE)
        self.noeud = rclpy.create_node('test_guide', context=self.contexte)
        self.executeur = rclpy.executors.SingleThreadedExecutor(context=self.contexte)
        self.executeur.add_node(self.noeud)
        self.pub_aller = self.noeud.create_publisher(String, '/guide/aller', 10)
        self.pub_stop = self.noeud.create_publisher(Empty, '/guide/stop', 10)
        self.etats = []
        self.evenements = []
        self.limites = []
        self.noeud.create_subscription(String, '/guide/etat',
                                       lambda m: self.etats.append(json.loads(m.data)), 10)
        self.noeud.create_subscription(String, '/guide/evenement',
                                       lambda m: self.evenements.append(json.loads(m.data)), 10)
        try:
            from nav2_msgs.msg import SpeedLimit
            self.noeud.create_subscription(
                SpeedLimit, '/speed_limit',
                lambda m: self.limites.append((m.percentage, m.speed_limit)), 10)
        except ImportError:
            pass

    def codes(self):
        return [e['code'] for e in self.evenements]

    def attendre(self, condition, delai_s):
        fin = time.monotonic() + delai_s
        while time.monotonic() < fin:
            self.executeur.spin_once(timeout_sec=0.1)
            if condition():
                return True
        return False

    def fermer(self):
        self.executeur.shutdown()
        self.noeud.destroy_node()
        rclpy.shutdown(context=self.contexte)


@pytest.fixture
def dossier(tmp_path):
    return copier_lieu(RACINE / 'lieux' / 'demo', tmp_path / 'demo')


def test_aller_stop_etat(dossier):
    guide = lancer_guide(dossier)
    ecoute = Ecoute()
    try:
        assert ecoute.attendre(lambda: ecoute.etats and ecoute.pub_aller.get_subscription_count(),
                               20.0), 'le guide ne publie pas /guide/etat'
        assert {k: ecoute.etats[-1][k] for k in ('etat', 'cible', 'reste_m', 'itineraire')} == \
            {'etat': 'attente', 'cible': None, 'reste_m': None, 'itineraire': []}
        # accueil → b204 : 21,5 m à 4 m/s
        ecoute.pub_aller.publish(String(data='b204'))
        assert ecoute.attendre(lambda: ecoute.etats[-1]['etat'] == 'arrive', 20.0)
        vus = [e['etat'] for e in ecoute.etats]
        assert 'en_route' in vus and vus.index('en_route') < vus.index('arrive')
        fin = ecoute.etats[-1]
        # Les champs de la vague 1, plus ceux de la vague 4 (section 11.4) ; pas de message
        assert set(fin) >= {'etat', 'cible', 'reste_m', 'itineraire', 'version', 'mission',
                            'accompagner', 'visiteur', 'depuis_s'}
        assert 'message' not in fin and fin['mission'] == 'visite'
        assert fin['cible'] == 'b204' and fin['reste_m'] == 0.0
        assert fin['itineraire'] == ['accueil', 'hall_nord', 'amphi', 'couloir_nord_1', 'b204']
        # Cible inconnue
        ecoute.pub_aller.publish(String(data='grenier'))
        assert ecoute.attendre(lambda: ecoute.etats[-1]['etat'] == 'echec', 5.0)
        assert ecoute.etats[-1]['cible'] == 'grenier'
        # Départ puis arrêt
        ecoute.pub_aller.publish(String(data='cdi'))
        assert ecoute.attendre(lambda: ecoute.etats[-1]['etat'] == 'en_route', 5.0)
        ecoute.pub_stop.publish(Empty())
        assert ecoute.attendre(lambda: ecoute.etats[-1]['etat'] == 'attente', 5.0)
        assert ecoute.etats[-1]['cible'] is None
    finally:
        ecoute.fermer()
        os.killpg(guide.pid, signal.SIGINT)
        sortie, erreurs = guide.communicate(timeout=10)
    assert guide.returncode == 0, erreurs
    assert 'Traceback' not in erreurs
    assert 'guide prêt' in sortie + erreurs


def test_aller_en_json_et_vers_le_principal(dossier):
    """Vague 4 (section 11.4) : /guide/aller en JSON, et la cible « principal »."""
    guide = lancer_guide(dossier)
    ecoute = Ecoute()
    try:
        assert ecoute.attendre(lambda: ecoute.etats and ecoute.pub_aller.get_subscription_count(),
                               20.0), 'le guide ne publie pas /guide/etat'
        demande = {'cible': 'b204', 'accompagner': True, 'source': 'dialogue'}
        ecoute.pub_aller.publish(String(data=json.dumps(demande)))
        assert ecoute.attendre(lambda: ecoute.etats[-1]['etat'] == 'arrive', 20.0)
        assert ecoute.etats[-1]['cible'] == 'b204'
        ecoute.pub_aller.publish(String(data='principal'))
        assert ecoute.attendre(lambda: ecoute.etats[-1]['etat'] == 'arrive'
                               and ecoute.etats[-1]['cible'] == 'accueil', 20.0)
        # JSON faux : la demande échoue proprement
        ecoute.pub_aller.publish(String(data='{"cible": 3}'))
        assert ecoute.attendre(lambda: ecoute.etats[-1]['etat'] == 'echec', 5.0)
    finally:
        ecoute.fermer()
        os.killpg(guide.pid, signal.SIGINT)
        sortie, erreurs = guide.communicate(timeout=10)
    assert guide.returncode == 0, erreurs
    assert 'Traceback' not in erreurs


@pytest.mark.skipif((PAQUET / 'g1_nav' / 'moteur_unitree.py').exists(),
                    reason='moteur_unitree.py existe : l\'agent Scan l\'a écrit')
def test_moteur_unitree_absent(dossier):
    guide = lancer_guide(dossier, moteur='unitree')
    sortie, erreurs = guide.communicate(timeout=20)
    assert guide.returncode == 1
    assert 'MoteurUnitree est absent' in erreurs and 'Traceback' not in erreurs


def test_lieu_introuvable(tmp_path):
    guide = lancer_guide(tmp_path / 'nulle_part')
    sortie, erreurs = guide.communicate(timeout=20)
    # Avec ROS_LOCALHOST_ONLY=1, CycloneDDS écrit d'abord un avertissement sur la sortie d'erreur
    # (multicast désactivé sur lo) : le message du guide est une des lignes, pas la première
    assert guide.returncode == 1, erreurs
    assert any(ligne.startswith('guide : ') for ligne in erreurs.splitlines()), erreurs
    assert 'Traceback' not in erreurs


def test_nav2_absent_attente_puis_non_repere(dossier):
    """
    Moteur nav2 sans Nav2 : /guide/aller donne attente avec un message (plus d'echec aussitôt).

    Puis le relais dit « non repéré » : echec tout de suite, avec le message du repérage.
    """
    guide = lancer_guide(dossier, moteur='nav2')
    ecoute = Ecoute()
    pub_reperage = ecoute.noeud.create_publisher(String, '/reperage/etat', 10)
    try:
        assert ecoute.attendre(lambda: ecoute.etats and ecoute.pub_aller.get_subscription_count(),
                               20.0), 'le guide ne publie pas /guide/etat'
        ecoute.pub_aller.publish(String(data='b204'))
        assert ecoute.attendre(lambda: ecoute.etats[-1].get('cible') == 'b204', 5.0)
        assert ecoute.etats[-1]['etat'] == 'attente'
        assert ecoute.etats[-1]['message'].startswith('La navigation démarre')
        assert not ecoute.attendre(lambda: ecoute.etats[-1]['etat'] == 'echec', 3.0)
        etat = {'version': 1, 'etat': 'non_repere', 'repere': False, 'localisation': 'unitree',
                'message': 'Robot non repéré', 'pose': None, 'precision_m': None, 'age_s': None,
                'demande': None, 'carte': 'repetition.pcd',
                'repere_unitree': {'x': 2.5, 'y': 10.0, 'theta': 0.0}, 'sauts': 0}

        def publier_reperage():
            pub_reperage.publish(String(data=json.dumps(etat)))
            return ecoute.etats[-1]['etat'] == 'echec'
        assert ecoute.attendre(publier_reperage, 5.0), 'le guide ne voit pas « non repéré »'
        assert 'Repérer le robot' in ecoute.etats[-1]['message']
    finally:
        ecoute.fermer()
        os.killpg(guide.pid, signal.SIGINT)
        sortie, erreurs = guide.communicate(timeout=15)
    assert 'Traceback' not in erreurs


# ---------------------------------------------------------------- vague 4 (section 11.4)

def personnes_json(personnes, temps=1.0):
    return json.dumps({'version': 1, 'source': 'lidar', 'temps': temps, 'personnes': [
        {'id': i, 'x': x, 'y': y, 'distance_m': (x * x + y * y) ** 0.5,
         'angle_rad': __import__('math').atan2(y, x), 'confiance': 0.9} for i, x, y in personnes]})


def test_evenements_et_retour_au_principal(dossier):
    """Événements en français, conformes ; retour seul au point principal après l'arrivée."""
    from atelier.lieu import valider_message
    guide = lancer_guide(dossier, delai_avant_retour_s=1.0)
    ecoute = Ecoute()
    try:
        assert ecoute.attendre(lambda: ecoute.etats and ecoute.pub_aller.get_subscription_count(),
                               20.0), 'le guide ne publie pas /guide/etat'
        ecoute.pub_aller.publish(String(data='b204'))
        assert ecoute.attendre(lambda: ecoute.etats[-1]['etat'] == 'retour', 20.0)
        assert ecoute.etats[-1]['cible'] == 'accueil' and ecoute.etats[-1]['mission'] == 'retour'
        assert ecoute.attendre(lambda: ecoute.etats[-1]['etat'] == 'attente'
                               and 'retour_arrive' in ecoute.codes(), 20.0)
        assert ecoute.codes() == ['depart', 'arrivee', 'retour', 'retour_arrive']
        assert ecoute.evenements[1]['texte'] == 'Voici le labo de physique.'
        for e in ecoute.evenements:
            assert valider_message('evenement_guide', e) == [], e
        for e in ecoute.etats:
            assert valider_message('etat_guide', e) == [], e
        # JSON, sans retour : le robot reste à b204
        ecoute.pub_aller.publish(String(data=json.dumps({'cible': 'b204', 'retour': False})))
        assert ecoute.attendre(lambda: ecoute.etats[-1]['etat'] == 'arrive', 20.0)
        assert not ecoute.attendre(lambda: ecoute.etats[-1]['etat'] == 'retour', 3.0)
        # Arrêt : « Je m'arrête. » seulement si quelque chose était en cours
        ecoute.pub_aller.publish(String(data='cdi'))
        assert ecoute.attendre(lambda: ecoute.etats[-1]['etat'] == 'en_route', 5.0)
        ecoute.pub_stop.publish(Empty())
        assert ecoute.attendre(lambda: ecoute.codes()[-1:] == ['arret'], 5.0)
    finally:
        ecoute.fermer()
        os.killpg(guide.pid, signal.SIGINT)
        sortie, erreurs = guide.communicate(timeout=10)
    assert guide.returncode == 0, erreurs
    assert 'Traceback' not in erreurs


def test_verrou_du_pilotage(dossier):
    """/mouvement/maitre pilotage (transient_local) : /guide/aller refusé, événement pilotage."""
    from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
    guide = lancer_guide(dossier)
    ecoute = Ecoute()
    verrou = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                        durability=DurabilityPolicy.TRANSIENT_LOCAL,
                        history=HistoryPolicy.KEEP_LAST)
    pub = ecoute.noeud.create_publisher(String, '/mouvement/maitre', verrou)
    maitre = {'version': 1, 'maitre': 'pilotage', 'par': 'test',
              'depuis': '2026-10-26T10:00:00+01:00', 'message': 'Piloté à la main'}
    try:
        pub.publish(String(data=json.dumps(maitre)))
        assert ecoute.attendre(lambda: ecoute.etats and ecoute.pub_aller.get_subscription_count(),
                               20.0), 'le guide ne publie pas /guide/etat'
        time.sleep(1.0)
        ecoute.pub_aller.publish(String(data='b204'))
        assert ecoute.attendre(lambda: ecoute.etats[-1]['etat'] == 'echec', 5.0)
        assert 'piloté à la main' in ecoute.etats[-1]['message']
        assert ecoute.attendre(lambda: 'pilotage' in ecoute.codes(), 3.0)
        assert 'depart' not in ecoute.codes()
        # Rendre la main : le guide repart à la demande suivante
        pub.publish(String(data=json.dumps(dict(maitre, maitre='guide'))))
        time.sleep(1.0)
        ecoute.pub_aller.publish(String(data='b204'))
        assert ecoute.attendre(lambda: ecoute.etats[-1]['etat'] == 'arrive', 20.0)
    finally:
        ecoute.fermer()
        os.killpg(guide.pid, signal.SIGINT)
        sortie, erreurs = guide.communicate(timeout=10)
    assert 'Traceback' not in erreurs


def test_accompagnement_avec_un_faux_detecteur(dossier):
    """
    Accompagnement avec un faux /personnes/lidar.

    Visiteur derrière (depart), puis loin (ralenti, /speed_limit), puis plus vu (attente_visiteur,
    robot arrêté), puis de retour (visiteur_retrouve).
    """
    guide = lancer_guide(dossier, vitesse_factice='0.5', delai_visiteur_s='30.0')
    ecoute = Ecoute()
    pub = ecoute.noeud.create_publisher(String, '/personnes/lidar', 10)
    vues = [[(7, -1.0, 0.0)]]

    def publier():
        if vues[0] is not None:
            pub.publish(String(data=personnes_json(vues[0])))
        return False
    try:
        assert ecoute.attendre(lambda: ecoute.etats and ecoute.pub_aller.get_subscription_count(),
                               20.0), 'le guide ne publie pas /guide/etat'
        ecoute.attendre(publier, 1.0)
        demande = {'cible': 'b204', 'accompagner': True, 'source': 'test'}
        ecoute.pub_aller.publish(String(data=json.dumps(demande)))
        assert ecoute.attendre(lambda: publier() or 'depart' in ecoute.codes(), 5.0)
        assert ecoute.etats[-1]['accompagner'] is True
        vues[0] = [(7, -2.8, 0.0)]
        assert ecoute.attendre(lambda: publier() or 'ralentir' in ecoute.codes(), 5.0)
        assert ecoute.attendre(lambda: publier() or (True, 50.0) in ecoute.limites, 3.0)
        vues[0] = []
        assert ecoute.attendre(lambda: publier() or ecoute.etats[-1]['etat'] == 'attente_visiteur',
                               6.0)
        assert ecoute.etats[-1]['visiteur']['vu'] is False
        # Il revient : visiteur_retrouve et reprise
        vues[0] = [(7, -1.2, 0.0)]
        assert ecoute.attendre(lambda: publier() or 'visiteur_retrouve' in ecoute.codes(), 5.0)
        assert ecoute.attendre(lambda: publier() or ecoute.etats[-1]['etat'] == 'en_route', 3.0)
        ecoute.pub_stop.publish(Empty())
    finally:
        ecoute.fermer()
        os.killpg(guide.pid, signal.SIGINT)
        sortie, erreurs = guide.communicate(timeout=10)
    assert 'Traceback' not in erreurs


def test_robot_perdu_par_le_relais(dossier):
    """/reperage/etat perdu en route : perdu, puis echec après delai_perdu_s, sans retour."""
    guide = lancer_guide(dossier, vitesse_factice='0.5', delai_perdu_s='3.0',
                         delai_avant_retour_s='1.0')
    ecoute = Ecoute()
    pub = ecoute.noeud.create_publisher(String, '/reperage/etat', 10)
    etat = {'version': 1, 'etat': 'perdu', 'repere': False, 'localisation': 'unitree',
            'message': 'Repérage perdu', 'pose': None, 'precision_m': None, 'age_s': 3.1,
            'demande': None, 'carte': 'repetition.pcd',
            'repere_unitree': {'x': 2.5, 'y': 10.0, 'theta': 0.0}, 'sauts': 0}
    perdre = [False]

    def publier():
        if perdre[0]:
            pub.publish(String(data=json.dumps(etat)))
        return False
    try:
        assert ecoute.attendre(lambda: ecoute.etats and ecoute.pub_aller.get_subscription_count(),
                               20.0), 'le guide ne publie pas /guide/etat'
        ecoute.pub_aller.publish(String(data='b204'))
        assert ecoute.attendre(lambda: ecoute.etats[-1]['etat'] == 'en_route', 5.0)
        perdre[0] = True
        assert ecoute.attendre(lambda: publier() or ecoute.etats[-1]['etat'] == 'perdu', 3.0)
        assert ecoute.attendre(lambda: publier() or 'perdu' in ecoute.codes(), 2.0)
        assert ecoute.attendre(lambda: publier() or ecoute.etats[-1]['etat'] == 'echec', 6.0)
        assert 'Repérer le robot' in ecoute.etats[-1]['message']
        assert not ecoute.attendre(lambda: publier() or ecoute.etats[-1]['etat'] == 'retour', 3.0)
    finally:
        ecoute.fermer()
        os.killpg(guide.pid, signal.SIGINT)
        sortie, erreurs = guide.communicate(timeout=10)
    assert 'Traceback' not in erreurs


def test_reglages_de_la_rotation_finale_en_marche(dossier):
    """Vague 5 : ros2 param set /guide tolerance_orientation_rad … change le réglage en marche."""
    from rcl_interfaces.msg import Parameter, ParameterType, ParameterValue
    from rcl_interfaces.srv import GetParameters, SetParameters
    guide = lancer_guide(dossier, tolerance_orientation_rad=0.4)
    ecoute = Ecoute()

    def reglage(nom, valeur):
        p = Parameter(name=nom, value=ParameterValue(type=ParameterType.PARAMETER_DOUBLE,
                                                     double_value=valeur))
        futur = changer.call_async(SetParameters.Request(parameters=[p]))
        assert ecoute.attendre(futur.done, 5.0)
        return futur.result().results[0]

    def valeur(nom):
        futur = lire.call_async(GetParameters.Request(names=[nom]))
        assert ecoute.attendre(futur.done, 5.0)
        return futur.result().values[0].double_value
    try:
        changer = ecoute.noeud.create_client(SetParameters, '/guide/set_parameters')
        lire = ecoute.noeud.create_client(GetParameters, '/guide/get_parameters')
        assert ecoute.attendre(lambda: changer.service_is_ready() and lire.service_is_ready(),
                               20.0), 'le guide ne répond pas aux paramètres'
        assert valeur('tolerance_orientation_rad') == pytest.approx(0.4)
        assert reglage('anticipation_rotation_rad', 0.3).successful
        assert valeur('anticipation_rotation_rad') == pytest.approx(0.3)
        refus = reglage('tolerance_orientation_rad', -0.5)
        assert not refus.successful and 'il faut un nombre de 0 à' in refus.reason
        assert valeur('tolerance_orientation_rad') == pytest.approx(0.4)
        assert not reglage('pourcentage_min', 150.0).successful
    finally:
        ecoute.fermer()
        guide.send_signal(signal.SIGINT)
        sortie, erreurs = guide.communicate(timeout=20)
    assert 'réglage changé en marche : anticipation_rotation_rad = 0.3' in sortie + erreurs
