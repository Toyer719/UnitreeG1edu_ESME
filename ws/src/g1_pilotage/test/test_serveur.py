"""
API HTTP et WebSocket du nœud pilotage, sans ROS : le cœur publie vers un faux robot en mémoire.

Le faux robot est celui de g1_jumeau (FauxG1) s'il est là, sinon un robot minimal qui répond 0.
Jeton (401), interdits (403), confirmations (428), verrou (409), joystick par WebSocket (homme mort
et fermeture), un seul joystick à la fois, demandes absurdes (jamais d'erreur 500).
"""
import json
import time

from g1_pilotage.coeur import Coeur
from g1_pilotage.logique import Envoi, Pilotage
from g1_pilotage.serveur import creer_application
import pytest
from tornado import gen, testing, websocket
from tornado.httpclient import HTTPRequest

try:
    from g1_jumeau.logique import FauxSport
    from g1_jumeau.robot import FauxG1
except ImportError:          # g1_jumeau absent : robot minimal
    FauxG1 = None


class RobotMemoire:
    """Reçoit les sorties du cœur, répond tout de suite comme le faux G1."""

    def __init__(self):
        self.recues = []
        self.coeur = None
        self.robot = FauxG1(FauxSport()) if FauxG1 is not None else None

    def __call__(self, sorties):
        for s in sorties:
            if not isinstance(s, Envoi):
                continue
            self.recues.append((time.monotonic(), s))
            if self.robot is None:
                reponse = (0, json.dumps({'data': 801}) if s.api_id == 7001 else '')
            else:
                reponse = self.robot.traiter(s.service, s.api_id, s.parametre)
            if reponse is not None:
                self.coeur.sur_reponse(s.identifiant, *reponse)

    def marche(self, depuis=0.0):
        return [(t, json.loads(s.parametre)) for t, s in self.recues
                if s.api_id == 7105 and s.service == 'sport' and t >= depuis]


ABSURDES = [
    ('/posture', 'pas du json'), ('/posture', '[1, 2]'), ('/posture', {}),
    ('/posture', '{"fsm": NaN}'),
    ('/requete', '{"service": "sport", "api_id": 7105, '
                 '"parametre": {"velocity": [Infinity, 0, 0], "duration": 0.5}}'),
    ('/posture', {'fsm': 'x'}), ('/posture', {'fsm': 1e300}),
    ('/led', {'r': -1, 'g': 0, 'b': 0}), ('/led', {'r': True, 'g': 0, 'b': 0}),
    ('/volume', {'volume': 200}), ('/voix', {'texte': ''}),
    ('/danse', {'id': 'cent'}), ('/choregraphie', {'choregraphie': 3}),
    ('/requete', {'service': 'sport', 'api_id': None}),
    ('/maitre', {'maitre': 'personne'}), ('/inconnue', {}),
    ('/requete', {'service': 'sport', 'api_id': 7105,
                  'parametre': {'velocity': [1e9, 0, 0], 'duration': 0.5}}),
]


class Base(testing.AsyncHTTPTestCase):
    JETON = ''

    def get_app(self):
        self.robot = RobotMemoire()
        self.coeur = Coeur(Pilotage(), self.robot)
        self.robot.coeur = self.coeur
        self.coeur.pas()                      # première lecture du mode (7001)
        return creer_application(self.coeur, self.JETON)

    def appel(self, chemin, corps=None, jeton=None, methode=None):
        entetes = {'X-Jeton': jeton} if jeton else {}
        if corps is not None and not isinstance(corps, str):
            corps = json.dumps(corps)
        r = self.fetch(chemin, method=methode or ('GET' if corps is None else 'POST'),
                       body=corps, headers=entetes)
        assert r.headers['Content-Type'].startswith('application/json')
        return r.code, json.loads(r.body)

    def prendre(self):
        code, corps = self.appel('/maitre', {'maitre': 'pilotage'})
        assert code == 200 and corps['maitre'] == 'pilotage', corps


class TestSansJeton(Base):
    def test_etat_conforme(self):
        code, etat = self.appel('/etat')
        assert code == 200 and etat['maitre'] == 'guide' and etat['fsm'] == 801
        lieu = pytest.importorskip('atelier.lieu')
        assert lieu.valider_message('etat_pilotage', etat) == []

    def test_interdits_403_rien_d_envoye(self):
        self.prendre()
        avant = len(self.robot.recues)
        for corps in ({'service': 'sport', 'api_id': 7104, 'parametre': {'data': 1}},
                      {'service': 'sport', 'api_id': 7110, 'parametre': {}},
                      {'service': 'moteurs', 'api_id': 1, 'parametre': {}},
                      {'service': 'sport', 'api_id': 7101, 'parametre': {'data': 550401},
                       'zone_libre': True}):
            code, r = self.appel('/requete', corps)
            assert code == 403 and r['detail'], r
        for fsm in (2, 4, 801):
            code, r = self.appel('/posture', {'fsm': fsm})
            assert code == 403 and 'refusée' in r['detail']
        assert len([1 for _, s in self.robot.recues[avant:] if s.api_id != 7001]) == 0

    def test_portique_confirmation_double(self):
        self.prendre()
        code, r = self.appel('/posture', {'fsm': 1})
        assert code == 428 and r['confirmation'] == 'portique'
        code, r = self.appel('/posture', {'fsm': 1, 'portique': True})
        assert code == 428 and r['jeton']
        code, r = self.appel('/posture', {'fsm': 1, 'portique': True, 'jeton': r['jeton']})
        assert code == 200 and r['code'] == 0

    def test_sans_la_main_409(self):
        for chemin, corps in (('/posture', {'fsm': 500}), ('/geste', {'action': 26}),
                              ('/danse', {'id': 604, 'zone_libre': True})):
            code, r = self.appel(chemin, corps)
            assert code == 409 and 'main' in r['detail']
        code, r = self.appel('/led', {'r': 10, 'g': 20, 'b': 30})
        assert code == 200
        code, r = self.appel('/voix', {'texte': 'Bonjour'})
        assert code == 200

    def test_refus_du_robot_traduits(self):
        self.prendre()
        assert self.appel('/posture', {'fsm': 3})[0] == 200
        code, r = self.appel('/geste', {'action': 26})
        if self.robot.robot is not None:
            assert code == 409 and r['code'] == 7404 and 'debout' in r['detail']

    def test_demandes_absurdes_jamais_500(self):
        for chemin, corps in ABSURDES:
            code, r = self.appel(chemin, corps)
            assert 400 <= code < 500 and r['detail'], (chemin, corps, code, r)
        code, r = self.appel('/arret', methode='GET')
        assert code == 405 and r['detail']

    def test_choregraphie_fausse_422(self):
        D = pytest.importorskip('atelier.lieu.pilotage')
        self.prendre()
        d = D.charger_choregraphie('exemple_kpop')
        d['bras']['poses'][2]['q']['left_elbow'] = 3.0
        code, r = self.appel('/choregraphie', {'choregraphie': d, 'zone_libre': True})
        assert code == 422 and any('limites' in e for e in r['erreurs'])

    def test_arret_toujours_permis(self):
        code, r = self.appel('/arret', {})
        assert code == 200 and self.robot.marche()[-1][1]['velocity'] == [0.0, 0.0, 0.0]

    @testing.gen_test
    async def test_joystick_homme_mort_et_fermeture(self):
        assert self.coeur.prendre_main().statut == 200
        debut = time.monotonic()
        url = f'ws://127.0.0.1:{self.get_http_port()}/joystick'
        ws = await websocket.websocket_connect(url)
        bienvenue = json.loads(await ws.read_message())
        assert bienvenue['type'] == 'bienvenue'
        for _ in range(5):
            await ws.write_message(json.dumps({'vx': 1.0, 'vy': 0, 'wz': 0}))
            await gen.sleep(0.1)
        ordres = self.robot.marche(debut)
        assert len(ordres) >= 4
        assert all(o['velocity'] == [0.4, 0.0, 0.0] and o['duration'] == 0.5 for _, o in ordres)
        dernier = ordres[-1][0]
        # homme mort : plus d'ordre, StopMove de lui-même 0,5 s après le dernier
        fin = time.monotonic() + 1.0
        while time.monotonic() < fin:
            self.coeur.pas()
            await gen.sleep(0.02)
        arrets = [t for t, o in self.robot.marche(dernier) if o['velocity'] == [0.0, 0.0, 0.0]]
        assert arrets and 0.45 <= arrets[0] - dernier <= 0.6
        # un second joystick est refusé tant que le premier est ouvert
        ws2 = await websocket.websocket_connect(url)
        refus = json.loads(await ws2.read_message())
        assert refus['type'] == 'refus' and 'déjà ouvert' in refus['detail']
        # fermeture en marche : StopMove tout de suite
        await ws.write_message(json.dumps({'vx': 0.2, 'vy': 0, 'wz': 0}))
        await gen.sleep(0.05)
        ferme = time.monotonic()
        ws.close()
        for _ in range(50):
            if [1 for t, o in self.robot.marche(ferme) if o['velocity'] == [0.0, 0.0, 0.0]]:
                break
            await gen.sleep(0.01)
        arrets = [t for t, o in self.robot.marche(ferme) if o['velocity'] == [0.0, 0.0, 0.0]]
        assert arrets and arrets[0] - ferme < 0.3


class TestAvecJeton(Base):
    JETON = 'secret-du-test'

    def test_401_sans_le_bon_jeton(self):
        code, r = self.appel('/etat')
        assert code == 401 and 'Jeton' in r['detail']
        code, r = self.appel('/arret', {}, jeton='faux')
        assert code == 401
        code, r = self.appel('/etat', jeton=self.JETON)
        assert code == 200 and r['version'] == 1

    @testing.gen_test
    async def test_joystick_401_sans_jeton(self):
        url = f'ws://127.0.0.1:{self.get_http_port()}/joystick'
        with pytest.raises(Exception):
            await websocket.websocket_connect(url)
        ws = await websocket.websocket_connect(HTTPRequest(url, headers={'X-Jeton': self.JETON}))
        assert json.loads(await ws.read_message())['type'] == 'bienvenue'
        ws.close()
