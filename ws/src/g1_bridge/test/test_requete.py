"""
Format des requêtes 7105, comparé aux deux exemples d'Unitree (section 10.3 du plan).

  - le SDK Python (unitree_sdk2py/g1/loco, LocoClient.SetVelocity et StopMove) : le texte du
    parameter, et le message DDS entier sérialisé, octet par octet ;
  - le client C++ de unitree_ros2 (g1_loco_client_example, compilé dans third_party) : la
    requête qu'il publie vraiment sur /api/sport/request, captée en ROS 2, comparée octet par
    octet à la nôtre une fois l'identifiant et le texte JSON mis de côté ; le JSON se lit pareil.
Sans le SDK ou sans l'exemple compilé, ces comparaisons sont sautées (avec la raison).
"""
import json
import math
import os
import shutil
import subprocess
import time

import pytest

from g1_bridge.requete import (API_SET_VELOCITY, Identifiants, parametre_arret,
                               parametre_vitesse, remplir_requete, SUJET_REQUETE)

CONSIGNES = [(0.3, 0.0, 0.0, 0.5), (0.4, -0.25, 0.6, 0.5), (-0.123456789, 0.2, -0.6, 0.5),
             (0.0, 0.0, 0.0, 1.0), (1e-4, 0.0, 0.0, 0.5), (0.1, 0.0, 0.0, 0.25)]


def _loco_client_du_sdk():
    """Client de marche du SDK (LocoClient), sans DDS : _Call capture le parameter."""
    loco = pytest.importorskip('unitree_sdk2py.g1.loco.g1_loco_client')
    client = loco.LocoClient.__new__(loco.LocoClient)
    client.captures = []
    client._Call = lambda api, parametre: (client.captures.append((api, parametre)) or (0, ''))
    return client


def test_parametre_comme_le_sdk_python():
    """Le texte de parameter est celui de LocoClient.SetVelocity du SDK, octet pour octet."""
    client = _loco_client_du_sdk()
    for vx, vy, wz, duree in CONSIGNES:
        client.SetVelocity(vx, vy, wz, duree)
        api, attendu = client.captures[-1]
        assert api == API_SET_VELOCITY == 7105
        assert parametre_vitesse(vx, vy, wz, duree).encode() == attendu.encode()


def test_arret_comme_stopmove():
    """L'arrêt est StopMove du SDK : vitesses nulles, duration 1,0."""
    client = _loco_client_du_sdk()
    client.StopMove()
    assert parametre_arret() == client.captures[-1][1]
    assert parametre_arret() == '{"velocity": [0.0, 0.0, 0.0], "duration": 1.0}'


def test_parametre_en_flottants():
    """Des entiers donnent quand même des flottants (0 → 0.0), comme le SDK appelé en float."""
    assert parametre_vitesse(0, 1, -1, 1) == '{"velocity": [0.0, 1.0, -1.0], "duration": 1.0}'


def test_message_entier_comme_le_sdk_python():
    """Le message sérialisé (CDR) est celui du SDK Python, octet pour octet, en-tête compris."""
    pytest.importorskip('unitree_api.msg')
    idl = pytest.importorskip('unitree_sdk2py.idl.unitree_api.msg.dds_')
    client_base = pytest.importorskip('unitree_sdk2py.rpc.client_base')
    from rclpy.serialization import serialize_message
    from unitree_api.msg import Request

    for vx, vy, wz, duree in CONSIGNES:
        texte = parametre_vitesse(vx, vy, wz, duree)
        # En-tête du SDK : identity (monotonic_ns, api), lease 0, policy (priorité 0, réponse)
        entete = client_base.ClientBase._ClientBase__SetHeader(None, API_SET_VELOCITY, 0, 0, False)
        attendu = idl.Request_(entete, texte, []).serialize()
        nous = remplir_requete(Request(), entete.identity.id, texte)
        assert serialize_message(nous) == attendu


def test_champs_de_la_requete():
    """identity, lease, policy et binary : les valeurs du contrat."""
    pytest.importorskip('unitree_api.msg')
    from unitree_api.msg import Request
    r = remplir_requete(Request(), 123456789, parametre_arret())
    assert (r.header.identity.id, r.header.identity.api_id) == (123456789, 7105)
    assert r.header.lease.id == 0
    assert (r.header.policy.priority, r.header.policy.noreply) == (0, False)
    assert list(r.binary) == []
    assert json.loads(r.parameter) == {'velocity': [0.0, 0.0, 0.0], 'duration': 1.0}


def test_identifiants_strictement_croissants():
    """identity.id : monotonic_ns, strictement croissant même si l'horloge ne bouge pas."""
    fige = Identifiants(horloge_ns=lambda: 1000)
    assert [fige() for _ in range(4)] == [1000, 1001, 1002, 1003]
    vrais = Identifiants()
    suite = [vrais() for _ in range(1000)]
    assert all(b > a for a, b in zip(suite, suite[1:]))
    # Même horloge que GetSystemUptimeInNanoseconds (CLOCK_MONOTONIC) : proche de monotonic_ns
    assert abs(vrais() - time.monotonic_ns()) < 1e9


# ---------------------------------------------------------------- l'exemple C++ d'Unitree

def _exemple_cpp():
    chemin = shutil.which('g1_loco_client_example')
    if chemin is None:
        pytest.skip('g1_loco_client_example (unitree_ros2/example) absent : chargez env.sh')
    return chemin


@pytest.fixture
def ros_isole():
    """Initialise rclpy sur un domaine à part, sans sortir de la machine."""
    rclpy = pytest.importorskip('rclpy')
    pytest.importorskip('unitree_api.msg')
    os.environ['ROS_LOCALHOST_ONLY'] = '1'
    os.environ.setdefault('ROS_DOMAIN_ID', str(150 + os.getpid() % 50))
    deja = rclpy.ok()          # déjà initialisé par un autre fichier de tests du même pytest
    if not deja:
        rclpy.init()
    yield rclpy
    if not deja:
        rclpy.try_shutdown()


def test_comme_le_client_cpp(ros_isole):
    """La requête publiée par g1_loco_client_example --set_velocity est la nôtre, au JSON près."""
    from rclpy.serialization import serialize_message
    from unitree_api.msg import Request

    exemple = _exemple_cpp()
    noeud = ros_isole.create_node('capture_exemple_cpp')
    recues = []
    noeud.create_subscription(Request, SUJET_REQUETE, recues.append, 10)
    vx, vy, wz, duree = 0.3, -0.1, 0.2, 0.5
    processus = subprocess.Popen([exemple, f'--set_velocity={vx} {vy} {wz} {duree}'],
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        fin = time.monotonic() + 10.0
        while time.monotonic() < fin and not recues:
            ros_isole.spin_once(noeud, timeout_sec=0.1)
    finally:
        processus.terminate()
        sortie = processus.communicate(timeout=10)[0]
        noeud.destroy_node()
    assert recues, f"l'exemple C++ n'a rien publié sur {SUJET_REQUETE} :\n{sortie[-1000:]}"
    cpp = recues[0]
    # Le JSON de nlohmann : clés triées, float écrits en double ; il se lit comme le nôtre
    lu = json.loads(cpp.parameter)
    nous = json.loads(parametre_vitesse(vx, vy, wz, duree))
    assert sorted(lu) == sorted(nous) == ['duration', 'velocity']
    assert lu['duration'] == pytest.approx(nous['duration'], abs=1e-6)
    assert len(lu['velocity']) == 3
    for a, b in zip(lu['velocity'], nous['velocity']):
        assert math.isclose(a, b, abs_tol=1e-6)         # float32 du C++ contre double
    # Tout le reste du message est identique, octet pour octet
    notre_requete = remplir_requete(Request(), cpp.header.identity.id, cpp.parameter)
    assert serialize_message(notre_requete) == serialize_message(cpp)
    assert cpp.header.identity.api_id == 7105 and cpp.header.lease.id == 0
    assert (cpp.header.policy.priority, cpp.header.policy.noreply) == (0, False)
    # Son identity.id est un temps monotone en ns, comme le nôtre
    assert abs(cpp.header.identity.id - time.monotonic_ns()) < 60e9
