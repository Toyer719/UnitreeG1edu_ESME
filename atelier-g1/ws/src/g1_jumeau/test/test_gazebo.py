"""
Pont → faux G1 → Gazebo, sans fenêtre, dans le couloir de test de g1_sim (worlds/couloir.sdf).

  ros2 launch g1_sim simulation.launch.py ... jumeau:=true     Gazebo, robot proxy, faux G1
  lib/g1_bridge/pont                                          le pont (repérage publié par le test)

Mesures sur la vérité terrain /g1_jumeau/odom : rien de Gazebo sur /cmd_vel, /odom ni /tf ;
/cmd_vel vx 0,3 pendant 3 s → 0,9 m, arrêt moins de 0,6 s après le dernier /cmd_vel ;
plafonds mesurés ; odométrie qui dérive de 2 % ; /guide/stop → arrêt en moins de 0,3 s ;
pont tué (SIGKILL) en marche → arrêt seul en moins de 0,6 s (+ 0,1 s de mesure).
Les tests partagent une simulation et s'enchaînent dans l'ordre du fichier (environ 1 min).
Sauté sans Gazebo (ign) ou sans les paquets compilés.
"""
import math
import shutil
import signal
import time
from pathlib import Path

import pytest

from outils_jumeau import cap, Client, NoeudLance

G1_SIM = Path(__file__).resolve().parents[2] / 'g1_sim'
COULOIR = G1_SIM / 'worlds' / 'couloir.sdf'


def _paquets_presents():
    try:
        from ament_index_python.packages import get_package_prefix
        for p in ('g1_sim', 'g1_bridge', 'g1_jumeau', 'ros_gz_bridge'):
            get_package_prefix(p)
        return True
    except Exception:       # noqa: B902
        return False


pytestmark = pytest.mark.skipif(shutil.which('ign') is None or not _paquets_presents(),
                                reason='Gazebo (ign) ou paquets g1_sim, g1_bridge, g1_jumeau '
                                       'absents')


class Banc:
    """La simulation, le pont et le client de test."""

    def __init__(self, sim, pont, client):
        self.sim, self.pont, self.client = sim, pont, client

    def pose(self):
        t, m = self.client.verites[-1]
        p = m.pose.pose
        return p.position.x, p.position.y, cap(p.orientation)

    def verites(self, t0, t1=math.inf):
        """[(instant mural, temps simulé, x, y, cap)] reçus entre t0 et t1."""
        sortie = []
        for t, m in self.client.depuis(self.client.verites, t0, t1):
            p = m.pose.pose
            sortie.append((t, m.header.stamp.sec + m.header.stamp.nanosec * 1e-9,
                           p.position.x, p.position.y, cap(p.orientation)))
        return sortie

    def vitesse_moyenne(self, t0, t1):
        """(avant, côté, rotation) moyens entre t0 et t1, dans le repère du robot au début."""
        v = self.verites(t0, t1)
        assert len(v) > 10, 'vérité terrain manquante'
        (_, s0, x0, y0, c0), (_, s1, x1, y1, c1) = v[0], v[-1]
        dt = s1 - s0
        dx, dy = x1 - x0, y1 - y0
        avant = (math.cos(c0) * dx + math.sin(c0) * dy) / dt
        cote = (-math.sin(c0) * dx + math.cos(c0) * dy) / dt
        rotation = math.atan2(math.sin(c1 - c0), math.cos(c1 - c0)) / dt
        return avant, cote, rotation

    def instant_arret(self, t_ref, seuil=0.02, tenue=0.3):
        """Premier instant mural après t_ref où la vitesse reste sous seuil pendant tenue."""
        v = self.verites(t_ref - 0.2)
        vitesses = []
        for i, (t, s, x, y, _) in enumerate(v):
            j = i
            while j + 1 < len(v) and v[j][1] - s < 0.1:
                j += 1
            if v[j][1] - s >= 0.099:
                vitesses.append((t, math.hypot(v[j][2] - x, v[j][3] - y) / (v[j][1] - s)))
        for k, (t, vitesse) in enumerate(vitesses):
            if t < t_ref or vitesse >= seuil:
                continue
            suite = [w for (u, w) in vitesses[k:] if u <= t + tenue]
            if all(w < seuil for w in suite) and vitesses[-1][0] >= t + tenue:
                return t
        return None


@pytest.fixture(scope='module')
def banc(tmp_path_factory):
    lieu = tmp_path_factory.mktemp('lieu_couloir_jumeau')
    (lieu / 'mondes').mkdir()
    shutil.copy(COULOIR, lieu / 'mondes' / 'rdc.sdf')
    shutil.copy(COULOIR.with_name('couloir.monde.yaml'), lieu / 'mondes' / 'rdc.monde.yaml')
    sim = NoeudLance('simulation_jumeau', commande=[
        'ros2', 'launch', 'g1_sim', 'simulation.launch.py', f'lieu:={lieu}', 'etage:=rdc',
        'sans_fenetre:=true', 'jumeau:=true']).demarrer()
    pont = NoeudLance('pont_gazebo', paquet='g1_bridge', executable_nom='pont').demarrer()
    client = Client(verite=True)
    client.reperage = True
    try:
        client.attendre(lambda: len(client.verites) > 20, 60.0,
                        'pas de vérité terrain /g1_jumeau/odom :\n' + sim.texte()[-2000:])
        client.attendre(lambda: client.etats_pont and client.etats_pont[-1][1]['etat'] == 'pret',
                        20.0, 'le pont ne passe pas à « pret »')
        time.sleep(1.0)
        yield Banc(sim, pont, client)
    finally:
        client.cmd_vel = None
        client.fermer()
        pont.arreter()
        sim.arreter()


def test_aucune_vitesse_directe_vers_gazebo(banc):
    n = banc.client.noeud
    abonnes_cmd_vel = {i.node_name for i in n.get_subscriptions_info_by_topic('/cmd_vel')}
    assert abonnes_cmd_vel == {'pont_g1'}, abonnes_cmd_vel
    editeurs = {i.node_name for i in n.get_publishers_info_by_topic('/g1_jumeau/cmd_vel')}
    assert editeurs == {'g1_jumeau'}, editeurs
    assert n.get_publishers_info_by_topic('/odom') == []
    assert 'pont_gz' not in {i.node_name for i in n.get_publishers_info_by_topic('/tf')}

    def editeurs_de(sujet):
        return {i.node_name for i in n.get_publishers_info_by_topic(sujet)}
    assert editeurs_de('/g1_jumeau/odom') == {'pont_gz'}
    assert editeurs_de('/g1_jumeau/points') == {'pont_gz'}
    assert editeurs_de('/state_estimator/odom_pelvis') == {'g1_jumeau'}


def test_vx_0_3_pendant_3_s_puis_arret(banc):
    c = banc.client
    x0, y0, _ = banc.pose()
    debut = time.monotonic()
    c.cmd_vel = (0.3, 0.0, 0.0)
    time.sleep(3.0)
    c.cmd_vel = None
    dernier = time.monotonic()           # le dernier /cmd_vel est parti au plus 50 ms avant
    time.sleep(2.0)
    x1, y1, _ = banc.pose()
    distance = math.hypot(x1 - x0, y1 - y0)
    arret = banc.instant_arret(dernier)
    print(f'vx 0,3 pendant 3 s : {distance:.3f} m ; arrêté '
          f'{(arret - dernier) if arret else float("nan"):.2f} s après le dernier /cmd_vel')
    assert distance == pytest.approx(0.9, abs=0.1), distance
    assert arret is not None and arret - dernier < 0.6, (arret and arret - dernier)
    requetes = [m for _, m in c.depuis(c.requetes, debut)]
    assert any(m.parameter == '{"velocity": [0.0, 0.0, 0.0], "duration": 1.0}'
               for m in requetes)
    # Chaque requête a sa réponse, code 0
    repondues = {r.header.identity.id for _, r in c.reponses if r.header.status.code == 0}
    assert {m.header.identity.id for m in requetes} <= repondues
    banc.deplacement_3s = (debut, dernier + 1.0)


def test_odometrie_locale_qui_derive(banc):
    """Le même déplacement vu par /state_estimator/odom_pelvis : 2 % plus long."""
    c = banc.client
    debut, fin = banc.deplacement_3s
    pelvis = c.depuis(c.pelvis, debut - 0.2, fin)
    verite = banc.verites(debut - 0.2, fin)
    p0, p1 = pelvis[0][1].pose.pose.position, pelvis[-1][1].pose.pose.position
    d_pelvis = math.hypot(p1.x - p0.x, p1.y - p0.y)
    d_verite = math.hypot(verite[-1][2] - verite[0][2], verite[-1][3] - verite[0][3])
    print(f'odom_pelvis / vérité : {d_pelvis:.3f} / {d_verite:.3f} m = {d_pelvis / d_verite:.4f}')
    assert d_pelvis / d_verite == pytest.approx(1.02, abs=0.005)
    assert pelvis[-1][1].header.frame_id == 'odom' and pelvis[-1][1].child_frame_id == 'pelvis'


@pytest.mark.parametrize('consigne, attendu', [
    ((1.0, 0.0, 0.0), (0.4, 0.0, 0.0)),
    ((0.0, 0.6, 0.0), (0.0, 0.25, 0.0)),
    ((0.0, -0.6, 0.0), (0.0, -0.25, 0.0)),
    ((0.0, 0.0, 2.0), (0.0, 0.0, 0.6)),
    ((0.0, 0.0, -2.0), (0.0, 0.0, -0.6))])
def test_plafonds_mesures(banc, consigne, attendu):
    c = banc.client
    debut = time.monotonic()
    c.cmd_vel = consigne
    time.sleep(1.2)
    c.cmd_vel = None
    time.sleep(1.0)
    mesure = banc.vitesse_moyenne(debut + 0.3, debut + 1.1)
    print(f'consigne {consigne} → mesuré ({mesure[0]:.3f} ; {mesure[1]:.3f} ; {mesure[2]:.3f})')
    for m, a, tolerance in zip(mesure, attendu, (0.02, 0.02, 0.03)):
        assert abs(m) <= abs(a) + tolerance, (mesure, attendu)
        assert m == pytest.approx(a, abs=max(tolerance, 0.1 * abs(a))), (mesure, attendu)


def test_guide_stop_arret_en_moins_de_0_3_s(banc):
    from std_msgs.msg import Empty
    c = banc.client
    editeur = c.noeud.create_publisher(Empty, '/guide/stop', 10)
    c.attendre(lambda: c.noeud.count_subscribers('/guide/stop') > 0, 5.0, 'pont absent')
    c.cmd_vel = (0.3, 0.0, 0.0)
    time.sleep(1.0)
    t_stop = time.monotonic()
    editeur.publish(Empty())
    time.sleep(0.8)                       # /cmd_vel continue, ignoré pendant 1 s
    c.cmd_vel = None
    time.sleep(1.0)
    arret = banc.instant_arret(t_stop)
    print(f'/guide/stop : robot arrêté {arret - t_stop:.2f} s après' if arret else 'pas arrêté')
    assert arret is not None and arret - t_stop < 0.3, (arret and arret - t_stop)
    # Pendant la garde de 1 s, /cmd_vel est ignoré : aucune consigne non nulle
    requetes = [m for t, m in c.depuis(c.requetes, t_stop + 0.05, t_stop + 0.8)]
    assert requetes == [] or all('[0.0, 0.0, 0.0]' in m.parameter for m in requetes)


def test_pont_tue_en_marche_le_robot_s_arrete_seul(banc):
    c = banc.client
    c.cmd_vel = (0.3, 0.0, 0.0)
    time.sleep(1.0)
    t_mort = time.monotonic()
    banc.pont.signaler(signal.SIGKILL)
    banc.pont.attendre(5)
    time.sleep(2.0)
    c.cmd_vel = None
    arret = banc.instant_arret(t_mort)
    print(f'pont tué : robot arrêté {arret - t_mort:.2f} s après' if arret else 'pas arrêté')
    # La dernière consigne (0,5 s) expire dans le faux G1, qui publie alors zéro
    assert arret is not None and arret - t_mort < 0.7, (arret and arret - t_mort)
