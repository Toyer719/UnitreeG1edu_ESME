"""
Le nœud accueil en vrai (ROS 2, sans Gazebo ni navigation), sur une copie du lieu demo.

Le test joue le guide (/guide/etat à 5 Hz, /guide/evenement), la position du robot (TF map →
base_link à 10 Hz), le pont (/pont/arret) et la borne (/accueil/choix, /accueil/commande). Il
vérifie : démarrage puis attente, demo.yaml lu (délai de choix), appui → salutation de la
personnalité et geste, choix → réponse avec le même id et /guide/aller de la source accueil,
accompagnement, ARRÊT → pause sans reprise seule (aucun /guide/aller), « Reprendre » refusé loin
de l'accueil, « Ramener » → retour puis attente, un choix hors du schéma refusé avec son id,
/accueil/etat 2 fois par seconde et conforme, l'événement arretee à l'arrêt ; sans lieu : code 1.
Isolement : ROS_LOCALHOST_ONLY=1 et ROS_DOMAIN_ID de l'environnement (143 par défaut, celui de
l'agent Borne et orchestrateur). Environ 40 s.
"""
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

os.environ.setdefault('ROS_DOMAIN_ID', '143')
os.environ['ROS_LOCALHOST_ONLY'] = '1'

import atelier  # noqa: E402
from atelier.lieu import copier_lieu, valider_message  # noqa: E402
from atelier.lieu import accueil as A  # noqa: E402
from atelier.lieu import equipe as E  # noqa: E402
import pytest  # noqa: E402

rclpy = pytest.importorskip('rclpy')
from geometry_msgs.msg import TransformStamped  # noqa: E402
from rclpy.executors import SingleThreadedExecutor  # noqa: E402
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy  # noqa: E402
from std_msgs.msg import Bool, Empty, String  # noqa: E402

DEMO = atelier.RACINE / 'lieux' / 'demo'
PAQUET = Path(__file__).resolve().parent.parent
VERROU = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                    durability=DurabilityPolicy.TRANSIENT_LOCAL)
FIABLE = QoSProfile(depth=20, reliability=ReliabilityPolicy.RELIABLE)
SCHEMAS = {'/accueil/etat': 'etat_demo', '/accueil/evenement': 'evenement_demo',
           '/guide/aller': 'demande_guide', '/robot/dire': 'robot_dire',
           '/robot/geste': 'robot_geste'}
PRINCIPAL = (2.5, 10.0, 0.0)


class Temoin:
    """Nœud de test dans un fil : faux guide, TF, pont et borne ; garde ce que publie la démo."""

    def __init__(self):
        import tf2_ros
        self.contexte = rclpy.Context()
        rclpy.init(context=self.contexte)
        self.noeud = rclpy.create_node('temoin_accueil', context=self.contexte)
        self.verrou = threading.Lock()
        self.recus = []               # (instant, sujet, données)
        self.erreurs_schema = []
        self.guide = {'version': 1, 'etat': 'attente', 'cible': None, 'reste_m': None,
                      'itineraire': [], 'mission': None, 'actif': False}
        self.pose = PRINCIPAL
        n = self.noeud
        self.pub_guide = n.create_publisher(String, '/guide/etat', 10)
        self.pub_evenement = n.create_publisher(String, '/guide/evenement', 10)
        self.pub_choix = n.create_publisher(String, '/accueil/choix', 10)
        self.pub_commande = n.create_publisher(String, '/accueil/commande', 10)
        self.pub_verrou = n.create_publisher(Bool, '/pont/arret', VERROU)
        self.tf = tf2_ros.TransformBroadcaster(n)
        for sujet in ('/accueil/etat', '/robot/dire', '/robot/geste', '/guide/aller'):
            n.create_subscription(String, sujet, self._recepteur(sujet), 10)
        n.create_subscription(String, '/accueil/evenement', self._recepteur('/accueil/evenement'),
                              FIABLE)
        n.create_subscription(Empty, '/guide/stop', self._recepteur('/guide/stop'), 10)
        n.create_timer(0.2, self._publier_guide)
        n.create_timer(0.1, self._publier_tf)
        self.executeur = SingleThreadedExecutor(context=self.contexte)
        self.executeur.add_node(n)
        self._fin = threading.Event()
        self._fil = threading.Thread(target=self._tourner, daemon=True)
        self._fil.start()

    def _tourner(self):
        while not self._fin.is_set() and self.contexte.ok():
            self.executeur.spin_once(timeout_sec=0.05)

    def _recepteur(self, sujet):
        def recevoir(msg):
            d = None if sujet == '/guide/stop' else json.loads(msg.data)
            schema = SCHEMAS.get(sujet)
            if schema and valider_message(schema, d):
                self.erreurs_schema.append((sujet, valider_message(schema, d)))
            with self.verrou:
                self.recus.append((time.monotonic(), sujet, d))
        return recevoir

    def _publier_guide(self):
        self.pub_guide.publish(String(data=json.dumps(self.guide)))

    def _publier_tf(self):
        x, y, theta = self.pose
        t = TransformStamped()
        t.header.stamp = self.noeud.get_clock().now().to_msg()
        t.header.frame_id = 'map'
        t.child_frame_id = 'base_link'
        t.transform.translation.x, t.transform.translation.y = float(x), float(y)
        t.transform.rotation.z, t.transform.rotation.w = math.sin(theta / 2), math.cos(theta / 2)
        self.tf.sendTransform(t)

    def changer_guide(self, etat, **champs):
        e = dict(self.guide, etat=etat, **champs)
        e['actif'] = champs.get('actif', etat in ('en_route', 'retour'))
        self.guide = e
        self._publier_guide()

    def evenement_guide(self, code, **plus):
        message = dict({'version': 1, 'code': code, 'texte': code,
                        'temps': '2026-11-09T10:00:00+01:00'}, **plus)
        self.pub_evenement.publish(String(data=json.dumps(message)))

    def messages(self, sujet, depuis=0.0):
        with self.verrou:
            return [d for t, s, d in self.recus if s == sujet and t >= depuis]

    def etat(self):
        m = self.messages('/accueil/etat')
        return m[-1] if m else {}

    def attendre(self, condition, delai, message):
        fin = time.monotonic() + delai
        while time.monotonic() < fin:
            v = condition()
            if v:
                return v
            time.sleep(0.05)
        raise AssertionError(f'{message} (dernier état de la démo : {self.etat()})')

    def attendre_etat(self, etat, delai=5.0):
        return self.attendre(lambda: self.etat().get('etat') == etat, delai,
                             f'la démo ne passe pas à « {etat} »')

    def reponse(self, ident, delai=A.DELAI_REPONSE_S):
        trouve = self.attendre(lambda: [e for e in self.messages('/accueil/evenement')
                                        if e.get('id') == ident], delai,
                               f'pas de réponse à {ident} en {delai} s')
        assert len(trouve) == 1, trouve
        return trouve[0]

    def choisir(self, salle, ident, source='borne'):
        self.pub_choix.publish(String(data=json.dumps(A.message_choix(salle, source, ident))))
        return self.reponse(ident)

    def commande(self, action, ident, source='atelier'):
        self.pub_commande.publish(String(data=json.dumps(A.message_commande(action, source,
                                                                            ident))))
        return self.reponse(ident)

    def fermer(self):
        self._fin.set()
        self._fil.join(timeout=2.0)
        self.executeur.shutdown()
        self.noeud.destroy_node()
        rclpy.try_shutdown(context=self.contexte)


def lancer(*arguments):
    chemin = f'{PAQUET}:{atelier.RACINE}:' + os.environ.get('PYTHONPATH', '')
    env = dict(os.environ, PYTHONPATH=chemin)
    return subprocess.Popen([sys.executable, '-m', 'g1_accueil.noeud', '--ros-args', *arguments],
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            start_new_session=True)


def arreter(p):
    if p.poll() is None:
        os.killpg(p.pid, signal.SIGINT)
        try:
            p.wait(timeout=8)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGKILL)
            p.wait()
    return p.stdout.read().decode('utf-8', 'replace')


@pytest.fixture
def lieu(tmp_path):
    dossier = copier_lieu(DEMO, tmp_path / 'essai')
    A.enregistrer_demo(dossier, {'version': 1, 'delais': {'choix_s': 6.0}})
    E.enregistrer_equipe(dossier, 'personnalites', E.exemple_equipe('personnalites'))
    return dossier


def test_sans_lieu_code_1():
    p = lancer()
    assert p.wait(timeout=20) == 1
    assert 'donnez le lieu' in p.stdout.read().decode('utf-8', 'replace')


def test_une_visite_une_pause_et_ramener(lieu):
    temoin = Temoin()
    p = lancer('-p', f'lieu:={lieu}')
    sortie = ''
    try:
        temoin.attendre_etat('attente', 15.0)
        assert temoin.etat()['personnalite'] == 'accueillant'
        # /accueil/etat 2 fois par seconde, même sans changement
        t0 = time.monotonic()
        time.sleep(2.1)
        assert len(temoin.messages('/accueil/etat', t0)) >= 4
        # appui → salutation de la personnalité et geste, puis choix ; demo.yaml : 6 s de choix
        r = temoin.commande('appui', 'n-1', source='borne')
        assert r['code'] == 'commande_acceptee'
        temoin.attendre(lambda: [d for d in temoin.messages('/robot/dire')
                                 if d['source'] == 'accueil' and 'robot d\'accueil' in d['texte']],
                        2.0, 'pas de salutation')
        assert temoin.attendre(lambda: temoin.messages('/robot/geste'), 2.0, 'pas de geste')[0][
            'geste'] == 26
        temoin.attendre_etat('choix', 3.0)
        t1 = time.monotonic()
        temoin.attendre_etat('attente', 8.0)
        assert 5.5 <= time.monotonic() - t1 <= 7.5
        # un choix hors du schéma : refusé, avec son id
        temoin.pub_choix.publish(String(data=json.dumps({'version': 1, 'id': 'faux-1',
                                                         'salle': 'B 204', 'source': 'borne'})))
        assert temoin.reponse('faux-1')['code'] == 'choix_refuse'
        # un choix : réponse avec le même id, /guide/aller de la source accueil
        r = temoin.choisir('b204', 'n-2')
        assert r['code'] == 'choix_accepte' and r['salle'] == 'b204'
        aller = temoin.attendre(lambda: temoin.messages('/guide/aller'), 2.0,
                                'pas de /guide/aller')
        assert aller == [{'cible': 'b204', 'accompagner': True, 'retour': True,
                          'source': 'accueil', 'id': r['visite']}]
        temoin.attendre_etat('depart', 2.0)
        temoin.changer_guide('en_route', mission='visite', cible='b204', reste_m=18.0)
        temoin.pose = (6.0, 10.0, 0.0)
        temoin.attendre_etat('accompagnement', 2.0)
        assert temoin.etat()['visite']['reste_m'] == 18.0
        # ARRÊT : verrou et /guide/stop ; le guide dit « arret » : pause, /guide/stop de la démo
        t2 = time.monotonic()
        temoin.pub_verrou.publish(Bool(data=True))
        temoin.evenement_guide('arret')
        temoin.changer_guide('attente', mission=None, cible=None, immobilise='verrou')
        temoin.attendre_etat('pause', 2.0)
        assert temoin.etat()['raison'] == 'arret'
        assert temoin.messages('/guide/stop', t2)
        assert [d for d in temoin.messages('/robot/dire', t2) if d.get('priorite') == 'securite']
        # « Débloquer » : rien ne repart pendant 5 s
        temoin.pub_verrou.publish(Bool(data=False))
        guide = dict(temoin.guide)
        guide.pop('immobilise')
        temoin.guide = guide
        time.sleep(5.0)
        assert temoin.etat()['etat'] == 'pause'
        assert len(temoin.messages('/guide/aller')) == 1
        r = temoin.commande('reprendre', 'n-3')
        assert r['code'] == 'commande_refusee' and 'Ramenez' in r['texte']
        r = temoin.commande('ramener', 'n-4', source='operateur')
        assert r['code'] == 'commande_acceptee'
        aller = temoin.messages('/guide/aller')
        assert aller[-1]['cible'] == 'principal' and aller[-1]['retour'] is False
        temoin.attendre_etat('retour', 2.0)
        temoin.changer_guide('en_route', mission='visite', cible='accueil')
        time.sleep(0.5)
        temoin.pose = PRINCIPAL
        temoin.changer_guide('arrive', mission='visite', cible='accueil', actif=False)
        temoin.attendre_etat('attente', 3.0)
        stats = temoin.etat()['statistiques']
        assert stats['visiteurs'] == 1 and stats['demandes'] == 1 and stats['pauses'] == 1
    finally:
        sortie = arreter(p)
        time.sleep(0.5)
        arretee = [e for e in temoin.messages('/accueil/evenement') if e['code'] == 'arretee']
        temoin.fermer()
    assert p.returncode == 0, sortie
    assert arretee, sortie
    assert temoin.erreurs_schema == [], temoin.erreurs_schema[:3]
    assert 'demande au guide' in sortie
