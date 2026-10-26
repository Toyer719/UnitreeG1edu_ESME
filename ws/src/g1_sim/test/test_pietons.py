"""
Les piétons dans Gazebo : piétons crédibles (pietons:=corps, le défaut, vague 4) et <actor>.

Piétons crédibles (section 11.3 du plan) : chaque piéton est un cylindre solide conduit par le
nœud pietons. On vérifie : /pietons/etat conforme et à 10 Hz ; un corps suit son horaire ; le
LiDAR le voit ; le robot ne le traverse pas ; la consigne d'un piéton piloté, qui s'arrête devant
un mur ; la réinitialisation de la scène ; les réactions (ecart, arret, aucune) face au robot ; le
facteur temps réel avec 5 piétons. Les mondes de test sont fabriqués ici par atelier.monde.

<actor> de la vague 1 (pietons:=acteurs) : Fortress les dessine dans le rendu du LiDAR (résultat du
25/10/2026, toujours vrai), mais ils n'ont pas de corps ; pas de nœud pietons.
Ignoré si le paquet atelier n'est pas disponible.
"""
import json
import math
import time

import numpy as np
import pytest
from rosgraph_msgs.msg import Clock
from std_msgs.msg import Empty, String

from outils_sim import Ecoute, Simulation, lidar_vers_odom, points_xyz, temps

lieu_api = pytest.importorskip('atelier.lieu')
monde_api = pytest.importorskip('atelier.monde')
from atelier.monde.pietons import etat_prevu  # noqa: E402

RAYON = 0.45          # m autour de la position du piéton
RAYON_ROBOT = 0.26    # m, cercle de contact du robot proxy (atelier.lieu.passants)


def _murs(xmin, ymin, xmax, ymax):
    bouts = {'sud': ([xmin, ymin], [xmax, ymin]), 'nord': ([xmin, ymax], [xmax, ymax]),
             'ouest': ([xmin, ymin], [xmin, ymax]), 'est': ([xmax, ymin], [xmax, ymax])}
    return [{'id': i, 'de': de, 'a': a, 'epaisseur': 0.15, 'hauteur': 2.5}
            for i, (de, a) in bouts.items()]


def _pieton(ident, trajet, vitesse, aller_retour, **champs):
    return dict(id=ident, trajet=trajet, vitesse=vitesse, aller_retour=aller_retour, **champs)


MONDE_CORPS = {
    'version': 1, 'emprise': {'min': [-0.5, -3.0], 'max': [20.5, 6.0]},
    'murs': _murs(0, -2.5, 20, 5.5),
    'pietons': [
        _pieton('immobile', [[5.0, 0.0], [5.5, 0.0]], 1.0, True, reaction='aucune',
                pauses=[{'point': 0, 'duree_s': 3600}]),
        _pieton('marcheur', [[3.0, 3.0], [15.0, 3.0]], 1.0, True, reaction='aucune'),
        _pieton('visiteur', [[2.0, 4.5], [2.5, 4.5]], 1.0, True, pilote='externe'),
        _pieton('p4', [[16.0, -2.0], [16.0, 4.5]], 0.8, True),
        _pieton('p5', [[10.0, -1.5], [18.0, -1.5]], 0.6, True),
    ],
    'depart_robot': {'x': 2.0, 'y': 0.0, 'theta': 0.0},
}

MONDE_REACTIONS = {
    'version': 1, 'emprise': {'min': [-0.5, -2.0], 'max': [12.5, 2.0]},
    'murs': _murs(0, -1.5, 12, 1.5),
    'pietons': [
        _pieton('ecart', [[1.0, 0.0], [11.0, 0.0]], 1.0, False, repeter=False, reaction='ecart'),
        _pieton('arret', [[11.5, 0.6], [0.5, 0.6]], 0.8, False, repeter=False, reaction='arret',
                depart_s=3.0),
        _pieton('aucune', [[1.0, -0.95], [11.0, -0.95]], 1.0, False, repeter=False,
                reaction='aucune'),
    ],
    'depart_robot': {'x': 6.0, 'y': 0.0, 'theta': 0.0},
}

MONDE_ACTEURS = {
    'version': 1,
    'emprise': {'min': [-0.5, -2.5], 'max': [10.5, 2.5]},
    'murs': _murs(0, -2, 10, 2),
    'pietons': [
        {'id': 'h1', 'trajet': [[3, -1.5], [3, 1.5]], 'vitesse': 0.5, 'aller_retour': True},
        {'id': 'h2', 'trajet': [[6, 1.2], [6, -1.2]], 'vitesse': 0.3, 'aller_retour': True},
    ],
    'depart_robot': {'x': 1.0, 'y': 0.0, 'theta': 0.0},
}


class EcoutePietons(Ecoute):
    """Ecoute de outils_sim, plus /pietons/etat, /clock, /pietons/consigne, /reinitialiser."""

    def __init__(self, nom):
        super().__init__(nom)
        self.etats = []          # [(heure murale, message)]
        self.horloges = []       # [(heure murale, temps simulé)]
        self.noeud.create_subscription(String, '/pietons/etat', self._sur_etat, 50)
        self.noeud.create_subscription(Clock, '/clock', self._sur_horloge, 50)
        self.pub_consigne = self.noeud.create_publisher(String, '/pietons/consigne', 10)
        self.pub_reinit = self.noeud.create_publisher(Empty, '/pietons/reinitialiser', 10)

    def _sur_etat(self, msg):
        with self.verrou:
            self.etats.append((time.monotonic(), json.loads(msg.data)))
            del self.etats[:-500]

    def _sur_horloge(self, msg):
        with self.verrou:
            self.horloges.append((time.monotonic(), msg.clock.sec + msg.clock.nanosec * 1e-9))
            del self.horloges[:-3000]

    def dernier_etat(self):
        with self.verrou:
            return self.etats[-1][1] if self.etats else None

    def pieton(self, ident):
        etat = self.dernier_etat()
        return next(p for p in etat['pietons'] if p['id'] == ident)

    def etats_depuis(self, debut):
        with self.verrou:
            return [m for t, m in self.etats if t >= debut]


def _sim(tmp_path_factory, nom, monde, arguments=()):
    dossier = tmp_path_factory.mktemp(f'lieu_{nom}') / nom
    lieu = lieu_api.creer_lieu(dossier, f'Essai {nom}')
    lieu_api.enregistrer_lieu(lieu)
    lieu_api.enregistrer_monde(dossier, 'rdc', lieu_api.Monde.depuis_dict(monde))
    monde_api.generer(dossier, 'rdc')
    simulation = Simulation(dossier, 'rdc', nom=nom, arguments=arguments)
    simulation.demarrer()
    ecoute = EcoutePietons(f'test_g1_sim_{nom}')
    return simulation, ecoute


@pytest.fixture(scope='module')
def sim_corps(tmp_path_factory):
    simulation, ecoute = _sim(tmp_path_factory, 'corps', MONDE_CORPS)
    try:
        ecoute.attendre_pret(simulation)
        pret = ecoute.attendre(lambda: ecoute.dernier_etat() is not None, 30.0)
        assert pret, simulation.texte_journal()
        yield ecoute
    finally:
        ecoute.fermer()
        simulation.arreter()


@pytest.fixture(scope='module')
def sim_reactions(tmp_path_factory):
    simulation, ecoute = _sim(tmp_path_factory, 'reactions', MONDE_REACTIONS)
    try:
        ecoute.attendre_pret(simulation)
        pret = ecoute.attendre(lambda: ecoute.dernier_etat() is not None, 30.0)
        assert pret, simulation.texte_journal()
        yield ecoute
    finally:
        ecoute.fermer()
        simulation.arreter()


@pytest.fixture(scope='module')
def sim_acteurs(tmp_path_factory):
    simulation, ecoute = _sim(tmp_path_factory, 'acteurs', MONDE_ACTEURS, ['pietons:=acteurs'])
    try:
        ecoute.attendre_pret(simulation)
        yield ecoute, lieu_api.Monde.depuis_dict(MONDE_ACTEURS)
    finally:
        ecoute.fermer()
        simulation.arreter()


# ---------------------------------------------------------------- piétons crédibles

def test_etat_des_pietons_conforme_a_10_hz(sim_corps):
    debut = time.monotonic()
    time.sleep(3.0)
    etats = sim_corps.etats_depuis(debut)
    assert 8 * 3 <= len(etats) <= 12 * 3, len(etats)
    for etat in etats:
        assert lieu_api.valider_message('pietons_etat', etat) == []
    dernier = etats[-1]
    assert [p['id'] for p in dernier['pietons']] == [p['id'] for p in MONDE_CORPS['pietons']]
    assert all(p['corps'] for p in dernier['pietons'])
    assert {p['id']: p['etat'] for p in dernier['pietons']}['visiteur'] == 'pilote'


def test_un_corps_suit_son_horaire(sim_corps):
    pieton = lieu_api.Pieton.depuis_dict(MONDE_CORPS['pietons'][1])
    ecarts = []
    for _ in range(10):
        time.sleep(0.4)
        etat = sim_corps.dernier_etat()
        p = next(q for q in etat['pietons'] if q['id'] == 'marcheur')
        x, y, *_ = etat_prevu(pieton, etat['temps_scene'])
        ecarts.append(math.hypot(p['x'] - x, p['y'] - y))
        assert math.hypot(p['vx'], p['vy']) == pytest.approx(1.0, abs=0.15)
    print(f'écart à l\'horaire : moyen {np.mean(ecarts):.3f} m, au plus {max(ecarts):.3f} m')
    assert max(ecarts) < 0.15


def test_un_corps_est_vu_par_le_lidar(sim_corps):
    debut = time.monotonic()
    time.sleep(4.0)
    nuages = sim_corps.nuages_depuis(debut)[::4]
    vus = 0
    for nuage in nuages:
        x, y, theta, _ = sim_corps.pose()
        p = lidar_vers_odom(points_xyz(nuage), x, y, theta)
        cible = sim_corps.pieton('marcheur')
        proches = ((np.hypot(p[:, 0] - cible['x'], p[:, 1] - cible['y']) < RAYON)
                   & (p[:, 2] > 0.3) & (p[:, 2] < 1.8))
        vus += int(proches.sum() >= 5)
    print(f'nuages où le marcheur est vu : {vus} sur {len(nuages)}')
    assert vus >= 0.9 * len(nuages)


def test_le_robot_ne_traverse_pas_un_pieton(sim_corps):
    """Le robot fonce sur le passant immobile (5 ; 0) : il est arrêté par son corps."""
    au_plus_pres = math.inf
    commande_fin = time.monotonic() + 8.0
    from geometry_msgs.msg import Twist
    t = Twist()
    t.linear.x = 0.4
    while time.monotonic() < commande_fin:
        sim_corps.cmd_vel.publish(t)
        time.sleep(0.05)
        x, y, _, _ = sim_corps.pose()
        p = sim_corps.pieton('immobile')
        au_plus_pres = min(au_plus_pres, math.hypot(p['x'] - x, p['y'] - y))
        assert x < p['x'] - 0.3, (x, p)
    sim_corps.arreter_robot()
    x, _, _, _ = sim_corps.pose()
    print(f'robot arrêté en x = {x:.2f} ; centres au plus près : {au_plus_pres:.3f} m')
    assert x < 5.0 - 0.25 + 0.05 and au_plus_pres > 0.33
    # le passant poussé revient à sa place
    time.sleep(3.0)
    p = sim_corps.pieton('immobile')
    assert math.hypot(p['x'] - 5.0, p['y']) < 0.15, p


def test_consigne_du_pieton_pilote_et_mur(sim_corps):
    depart = sim_corps.pieton('visiteur')
    fin = time.monotonic() + 3.0
    vers_le_nord = json.dumps({'id': 'visiteur', 'vx': 0.0, 'vy': 0.8})
    while time.monotonic() < fin:                      # vers le mur nord (y = 5,5)
        sim_corps.pub_consigne.publish(String(data=vers_le_nord))
        time.sleep(0.1)
    p = sim_corps.pieton('visiteur')
    assert p['etat'] == 'pilote' and p['y'] > depart['y'] + 0.4
    assert p['y'] < 5.5 - 0.075 - 0.25 + 0.02, p       # arrêté devant le mur, pas dedans
    time.sleep(1.5)                                    # plus de consigne : il ne bouge plus
    q = sim_corps.pieton('visiteur')
    assert math.hypot(q['x'] - p['x'], q['y'] - p['y']) < 0.05
    assert math.hypot(q['vx'], q['vy']) < 0.05
    # une consigne pour un piéton qui suit son trajet est refusée (le nœud ne tombe pas)
    sim_corps.pub_consigne.publish(String(data=json.dumps({'id': 'marcheur', 'vx': 1.0,
                                                           'vy': 0.0})))
    sim_corps.pub_consigne.publish(String(data='pas du json'))
    time.sleep(0.5)
    assert sim_corps.dernier_etat() is not None


def test_reinitialiser_la_scene(sim_corps):
    sim_corps.pub_reinit.publish(Empty())
    assert sim_corps.attendre(lambda: sim_corps.dernier_etat()['temps_scene'] < 1.0, 5.0)
    time.sleep(1.0)
    v = sim_corps.pieton('visiteur')
    assert math.hypot(v['x'] - 2.0, v['y'] - 4.5) < 0.1, v
    etat = sim_corps.dernier_etat()
    m = next(p for p in etat['pietons'] if p['id'] == 'marcheur')
    marcheur = lieu_api.Pieton.depuis_dict(MONDE_CORPS['pietons'][1])
    x, y, *_ = etat_prevu(marcheur, etat['temps_scene'])
    assert math.hypot(m['x'] - x, m['y'] - y) < 0.2, (m, x, y)


def test_facteur_temps_reel_avec_5_pietons(sim_corps):
    debut = time.monotonic()
    time.sleep(8.0)
    with sim_corps.verrou:
        h = [x for x in sim_corps.horloges if x[0] >= debut]
    facteur = (h[-1][1] - h[0][1]) / (h[-1][0] - h[0][0])
    print(f'facteur temps réel avec 5 piétons-corps : {facteur:.3f}')
    assert facteur >= 0.9


# ---------------------------------------------------------------- réactions au robot

def _suivre(ecoute, duree):
    """[(t, {id: piéton})] pendant duree secondes, et la position du robot."""
    traces = []
    fin = time.monotonic() + duree
    while time.monotonic() < fin:
        time.sleep(0.1)
        etat = ecoute.dernier_etat()
        traces.append((etat['temps_scene'], {p['id']: p for p in etat['pietons']}))
    return traces


def test_reactions_au_robot(sim_reactions):
    x, y, _, _ = sim_reactions.pose()
    assert (x, y) == pytest.approx((6.0, 0.0), abs=0.05)
    sim_reactions.pub_reinit.publish(Empty())
    time.sleep(0.5)
    traces = _suivre(sim_reactions, 16.0)

    def bord(p):
        return math.hypot(p['x'] - x, p['y'] - y) - RAYON_ROBOT - p['rayon_m']

    etats = {i: {t[1][i]['etat'] for t in traces} for i in ('ecart', 'arret', 'aucune')}
    minimum = {i: min(bord(t[1][i]) for t in traces) for i in etats}
    print('états vus :', etats, '; distances bord à bord minimales :', minimum)
    # ecart : il s'écarte (0,6 m au plus), ne touche pas le robot, revient sur son trajet et arrive
    assert 'ecart' in etats['ecart'] and minimum['ecart'] > 0.0
    assert max(abs(t[1]['ecart']['y']) for t in traces) <= 0.65
    fin = traces[-1][1]['ecart']
    assert (fin['etat'], round(fin['x'], 1), round(abs(fin['y']), 1)) == ('fini', 11.0, 0.0)
    # arret : il s'arrête devant le robot (moins de 0,8 m bord à bord), et y reste
    assert 'arret' in etats['arret'] and 'ecart' not in etats['arret']
    assert 0.4 < minimum['arret'] < 0.85
    derniers = [t[1]['arret'] for t in traces[-20:]]
    assert all(p['etat'] == 'arret' and math.hypot(p['vx'], p['vy']) < 0.05 for p in derniers)
    # aucune : il ne voit pas le robot
    assert etats['aucune'] <= {'marche', 'fini'}


# ---------------------------------------------------------------- <actor> (pietons:=acteurs)

def _points_du_pieton(nuage, pieton, pose):
    """Points du nuage à moins de RAYON de la position attendue du piéton, entre 0,3 et 1,8 m."""
    x, y, theta = pose
    p = lidar_vers_odom(points_xyz(nuage), x, y, theta)
    px, py, _ = monde_api.position_pieton(pieton, temps(nuage.header))
    proches = (np.hypot(p[:, 0] - px, p[:, 1] - py) < RAYON) & (p[:, 2] > 0.3) & (p[:, 2] < 1.8)
    return p[proches], (px, py)


def test_acteurs_vus_par_le_lidar_sans_noeud(sim_acteurs):
    ecoute, monde = sim_acteurs
    assert ecoute.noeud.count_publishers('/pietons/etat') == 0
    debut = time.monotonic()
    time.sleep(6.0)
    nuages = ecoute.nuages_depuis(debut)[::5]   # un nuage toutes les 0,5 s
    x, y, theta, _ = ecoute.pose()
    vus = {p.id: 0 for p in monde.pietons}
    ecarts_y = []
    for nuage in nuages:
        for pieton in monde.pietons:
            points, (px, py) = _points_du_pieton(nuage, pieton, (x, y, theta))
            if len(points) >= 5:
                vus[pieton.id] += 1
                if pieton.id == 'h1':
                    ecarts_y.append(abs(points[:, 1].mean() - py))
    print(f'nuages où chaque piéton est vu : {vus} sur {len(nuages)}')
    assert vus['h1'] >= 0.9 * len(nuages)        # h1 toujours dans le champ, rien devant lui
    assert vus['h2'] >= 0.5 * len(nuages)        # h2 est plus loin, et h1 le cache parfois
    assert ecarts_y and np.mean(ecarts_y) < 0.25, ecarts_y
