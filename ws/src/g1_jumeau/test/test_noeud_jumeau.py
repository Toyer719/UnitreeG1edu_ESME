"""
Le nœud g1_jumeau en vrai (ROS 2, sans Gazebo) : réponses, vitesses vers Gazebo, odométrie.

Le test joue le client (le pont, ou le client C++ d'Unitree) et la vérité terrain de Gazebo
(/g1_jumeau/odom). Vague 5 (section 12.6) : mode 501, sujet d'essai /g1_jumeau/mode, 7105 hors
marche accepté sans bouger, seuil de marche. Environ 1 min 30.
"""
import json
import math
import shutil
import signal
import subprocess
import time

import pytest

from outils_jumeau import cap, Client, NoeudLance

DEMARRAGE_S = 8.0


@pytest.fixture
def client():
    c = Client()
    yield c
    c.fermer()


@pytest.fixture
def lancer():
    lances = []

    def _lancer(*arguments, nom='jumeau'):
        noeud = NoeudLance(nom, arguments).demarrer()
        lances.append(noeud)
        return noeud
    yield _lancer
    for n in lances:
        n.arreter()


def pret(client, lancer, *arguments):
    jumeau = lancer(*arguments)
    client.attendre_abonne('/api/sport/request', DEMARRAGE_S)
    client.attendre(lambda: client.vitesses, DEMARRAGE_S, 'pas de /g1_jumeau/cmd_vel')
    return jumeau


def test_reponse_identite_recopiee_code_0(client, lancer):
    pret(client, lancer)
    ident = client.vitesse(0.3, 0.0, 0.1, 0.5)
    t, r = client.attendre(lambda: client.reponse(ident), 2.0, 'pas de réponse')
    assert (r.header.identity.id, r.header.identity.api_id) == (ident, 7105)
    assert r.header.status.code == 0 and r.data == '' and list(r.binary) == []


def test_vitesses_pendant_duration_puis_zero_a_20_hz(client, lancer):
    pret(client, lancer)
    time.sleep(0.5)
    t0 = time.monotonic()
    time.sleep(1.0)
    au_repos = client.depuis(client.vitesses, t0)
    assert 18 <= len(au_repos) <= 22 and {v for _, v in au_repos} == {(0.0, 0.0, 0.0)}
    t_envoi = time.monotonic()
    client.vitesse(0.3, -0.2, 0.5, 0.5)
    time.sleep(1.2)
    vues = client.depuis(client.vitesses, t_envoi)
    actives = [t for t, v in vues if v == (0.3, -0.2, 0.5)]
    assert actives and actives[0] - t_envoi < 0.05          # appliquée tout de suite
    assert 0.44 <= actives[-1] - t_envoi <= 0.52             # jusqu'à t + 0,5 s
    zeros = [t for t, v in vues if v == (0.0, 0.0, 0.0) and t > actives[-1]]
    assert zeros and zeros[0] - t_envoi <= 0.56
    etat = client.etats[-1][1]
    assert etat['version'] == 1 and etat['panne'] == 'aucune' and etat['appliquees'] == 1
    assert etat['consigne'] == {'vx': 0.0, 'vy': 0.0, 'wz': 0.0} and etat['reste_s'] == 0.0


def test_codes_d_erreur(client, lancer):
    pret(client, lancer)
    cas = {client.requete('{}', api_id=7999): 3203,
           client.requete('pas du json'): 3204,
           client.requete('{"velocity": [0.1, 0.2], "duration": 0.5}'): 3204}
    for ident, code in cas.items():
        _, r = client.attendre(lambda i=ident: client.reponse(i), 2.0, f'pas de réponse {ident}')
        assert r.header.status.code == code
    assert {v for _, v in client.vitesses} == {(0.0, 0.0, 0.0)}


def test_panne_muet_puis_refus(client, lancer):
    pret(client, lancer)
    client.vitesse(0.2, 0.0, 0.0, 0.5)
    time.sleep(0.1)
    client.panne('muet')
    client.attendre(lambda: client.etats and client.etats[-1][1]['panne'] == 'muet', 2.0, 'muet')
    t_muet = time.monotonic()
    ident = client.vitesse(0.4, 0.0, 0.0, 0.5)
    time.sleep(1.0)
    assert client.reponse(ident) is None
    vues = client.depuis(client.vitesses, t_muet)
    assert (0.4, 0.0, 0.0) not in {v for _, v in vues}          # rien appliqué
    assert vues[-1][1] == (0.0, 0.0, 0.0)                       # la consigne a expiré
    client.panne('refus')
    client.attendre(lambda: client.etats and client.etats[-1][1]['panne'] == 'refus', 2.0, 'refus')
    ident = client.vitesse(0.3, 0.0, 0.0, 0.5)
    _, r = client.attendre(lambda: client.reponse(ident), 2.0, 'pas de réponse en refus')
    assert r.header.status.code == 7301
    time.sleep(0.2)
    assert client.vitesses[-1][1] == (0.0, 0.0, 0.0)
    client.panne('aucune')
    time.sleep(0.3)
    ident = client.vitesse(0.3, 0.0, 0.0, 0.5)
    _, r = client.attendre(lambda: client.reponse(ident), 2.0, 'pas de réponse après la panne')
    assert r.header.status.code == 0


def test_latence(client, lancer):
    pret(client, lancer, '-p', 'latence_s:=0.3')
    t_envoi = time.monotonic()
    ident = client.vitesse(0.3, 0.0, 0.0, 0.5)
    t, r = client.attendre(lambda: client.reponse(ident), 2.0, 'pas de réponse')
    assert 0.29 <= t - t_envoi <= 0.4
    actives = [t for t, v in client.depuis(client.vitesses, t_envoi) if v[0] == 0.3]
    assert actives and 0.29 <= actives[0] - t_envoi <= 0.4


def test_perte(client, lancer):
    pret(client, lancer, '-p', 'perte:=0.5', '-p', 'graine:=3')
    idents = []
    for _ in range(100):
        idents.append(client.vitesse(0.1, 0.0, 0.0, 0.5))
        time.sleep(0.01)
    time.sleep(1.0)
    repondues = sum(1 for i in idents if client.reponse(i) is not None)
    assert 30 <= repondues <= 70, repondues
    assert client.etats[-1][1]['perdues'] == 100 - repondues


def test_odometrie_pelvis_qui_derive(client, lancer):
    """Vérité : 2 m tout droit depuis (2,5 ; 10), cap 0,3 → odom_pelvis 2,04 m et +0,02 rad."""
    pret(client, lancer)
    x0, y0, cap0 = 2.5, 10.0, 0.3
    for i in range(201):
        d = 0.01 * i
        client.verite(x0 + d * math.cos(cap0), y0 + d * math.sin(cap0), cap0,
                      stamp_s=100.0 + 0.02 * i, vx=0.5)
        time.sleep(0.004)
    client.attendre(lambda: len(client.pelvis) >= 195, 3.0, 'odom_pelvis manquante')
    time.sleep(0.2)
    premier, dernier = client.pelvis[0][1], client.pelvis[-1][1]
    assert (premier.header.frame_id, premier.child_frame_id) == ('odom', 'pelvis')
    p = premier.pose.pose
    assert (p.position.x, p.position.y, cap(p.orientation)) == pytest.approx((0, 0, 0), abs=1e-9)
    assert p.position.z == pytest.approx(0.75)
    q = dernier.pose.pose
    assert math.hypot(q.position.x, q.position.y) == pytest.approx(2.04, abs=0.02)
    assert cap(q.orientation) == pytest.approx(0.02, abs=2e-3)
    assert q.position.z == pytest.approx(0.75)
    # Horodatage de la vérité, twist recopié sans dérive
    secondes = dernier.header.stamp.sec + dernier.header.stamp.nanosec * 1e-9
    assert 100.0 <= secondes <= 104.01
    assert dernier.twist.twist.linear.x == pytest.approx(0.5)


@pytest.mark.parametrize('numero', [signal.SIGINT, signal.SIGTERM])
def test_zero_vers_gazebo_en_quittant(client, lancer, numero):
    jumeau = pret(client, lancer)
    client.vitesse(0.3, 0.0, 0.0, 5.0)
    client.attendre(lambda: client.vitesses[-1][1] == (0.3, 0.0, 0.0), 1.0, 'consigne absente')
    t_signal = time.monotonic()
    jumeau.signaler(numero)
    assert jumeau.attendre(10) == 0
    time.sleep(0.3)
    apres = client.depuis(client.vitesses, t_signal)
    assert apres and apres[-1][1] == (0.0, 0.0, 0.0)
    assert 'zéro envoyé' in jumeau.texte()


def test_panne_inconnue_ignoree(client, lancer):
    jumeau = pret(client, lancer)
    client.panne('explosion')
    time.sleep(0.8)
    assert client.etats[-1][1]['panne'] == 'aucune'
    assert 'panne inconnue' in jumeau.texte()


def test_client_cpp_d_unitree(client, lancer):
    """g1_loco_client_example --set_velocity reçoit sa réponse : le faux G1 parle comme le vrai."""
    exemple = shutil.which('g1_loco_client_example')
    if exemple is None:
        pytest.skip('g1_loco_client_example (unitree_ros2/example) absent : chargez env.sh')
    pret(client, lancer)
    t0 = time.monotonic()
    processus = subprocess.Popen([exemple, '--set_velocity=0.2 0 0.1 0.5'],
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        client.attendre(lambda: any(v == pytest.approx((0.2, 0.0, 0.1), abs=1e-6)
                                    for _, v in client.depuis(client.vitesses, t0)),
                        10.0, "la consigne du client C++ n'est pas appliquée")
        time.sleep(1.0)
    finally:
        processus.send_signal(signal.SIGINT)
        try:
            sortie = processus.communicate(timeout=10)[0]
        except subprocess.TimeoutExpired:
            processus.kill()
            sortie = processus.communicate()[0]
    assert 'set velocity to 0.2 0 0.1 0.5' in sortie, sortie[-800:]
    assert 'SetVelocity failed' not in sortie and 'error code' not in sortie


def test_etat_json_a_2_hz(client, lancer):
    pret(client, lancer)
    time.sleep(0.6)
    t0 = time.monotonic()
    time.sleep(2.0)
    etats = client.depuis(client.etats, t0)
    assert 3 <= len(etats) <= 5
    etat = etats[-1][1]
    assert set(etat) >= {'version', 'panne', 'consigne', 'reste_s', 'requetes', 'appliquees'}
    json.dumps(etat)


# ---------------------------------------------------------------- vague 5 (section 12.6)

def test_mode_501_et_sujet_d_essai(client, lancer):
    """501 au départ ; assis par /g1_jumeau/mode : 7105 accepté (code 0) sans bouger."""
    pret(client, lancer)
    assert client.lire_mode() == 501
    client.mode(3)
    client.attendre(lambda: client.etats and client.etats[-1][1]['robot']['fsm'] == 3, 2.0,
                    'le mode ne passe pas à 3')
    assert client.lire_mode() == 3
    t0 = time.monotonic()
    ident = client.vitesse(0.3, 0.0, 0.0, 0.5)
    _, r = client.attendre(lambda: client.reponse(ident), 2.0, 'pas de réponse assis')
    assert r.header.status.code == 0
    time.sleep(0.6)
    assert {v for _, v in client.depuis(client.vitesses, t0)} == {(0.0, 0.0, 0.0)}
    client.attendre(lambda: client.etats[-1][1]['robot']['ignores_hors_marche'] >= 1, 2.0,
                    'le 7105 hors marche n\'est pas compté')
    client.mode(802)                                     # course : 7105 appliqué
    time.sleep(0.3)
    client.vitesse(0.3, 0.0, 0.0, 0.5)
    client.attendre(lambda: client.vitesses[-1][1] == (0.3, 0.0, 0.0), 2.0, 'course immobile')


def test_seuil_de_marche_par_defaut(client, lancer):
    """Comme le vrai G1 le 27/10 : 0,1 m/s accepté sans bouger, 0,2 m/s marche."""
    pret(client, lancer)
    t0 = time.monotonic()
    ident = client.vitesse(0.1, 0.0, 0.0, 0.5)
    _, r = client.attendre(lambda: client.reponse(ident), 2.0, 'pas de réponse à 0,1 m/s')
    assert r.header.status.code == 0
    time.sleep(0.6)
    assert {v for _, v in client.depuis(client.vitesses, t0)} == {(0.0, 0.0, 0.0)}
    client.vitesse(0.2, 0.0, 0.0, 0.5)
    client.attendre(lambda: client.vitesses[-1][1] == (0.2, 0.0, 0.0), 2.0, '0,2 m/s immobile')
    etat = client.attendre(lambda: client.etats and client.etats[-1][1].get('sous_seuil') == 1
                           and client.etats[-1][1], 2.0, 'sous_seuil absent')
    assert etat['seuils'] == {'marche_m_s': 0.15, 'rotation_rad_s': 0.2}


def test_reglages_de_la_vague_5(client, lancer):
    """Sans seuil (0), départ assis et hors_marche:=refuser (7301), réglage inconnu refusé."""
    pret(client, lancer, '-p', 'seuil_marche_m_s:=0.0', '-p', 'fsm_depart:=3',
         '-p', 'hors_marche:=refuser')
    assert client.lire_mode() == 3
    ident = client.vitesse(0.1, 0.0, 0.0, 0.5)
    _, r = client.attendre(lambda: client.reponse(ident), 2.0, 'pas de réponse')
    assert r.header.status.code == 7301
    client.mode(501)
    time.sleep(0.3)
    client.vitesse(0.1, 0.0, 0.0, 0.5)                   # sans seuil : 0,1 m/s appliqué
    client.attendre(lambda: client.vitesses[-1][1] == (0.1, 0.0, 0.0), 2.0, '0,1 m/s immobile')
    refuse = lancer('-p', 'hors_marche:=oublier', nom='jumeau_refuse')
    assert refuse.attendre(15) == 1
    assert 'réglage refusé' in refuse.texte() and 'ignorer ou refuser' in refuse.texte()
