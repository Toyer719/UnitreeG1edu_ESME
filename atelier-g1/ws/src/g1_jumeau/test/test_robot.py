"""
Faux G1 étendu, sans ROS (section 11.5 du plan).

Modes et refus du service sport, danses (liste 7100, lecture, retour au mode d'avant), gestes
(7401, 7404, 7400, 99), voix, LED, commandes interdites comptées, vérification de rt/arm_sdk et
bras simulés de /lowstate. Vague 5 (section 12.6) : marche en 501, 7105 hors marche accepté sans
bouger (ou refusé), course 802, mode changé d'un coup, seuil de marche.
"""
import json

from g1_jumeau.logique import FauxSport
from g1_jumeau.robot import BrasSimules, FauxG1, VerificationArmSdk
import pytest


class Horloge:
    def __init__(self, t=10.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def h():
    return Horloge()


@pytest.fixture
def g1(h):
    return FauxG1(FauxSport(horloge=h))


def sport(g1, api, d=None):
    return g1.traiter('sport', api, json.dumps({} if d is None else d))


def fsm(g1):
    code, data = sport(g1, 7001)
    assert code == 0
    return json.loads(data)['data']


def vitesse(vx, d=0.5):
    return {'velocity': [vx, 0.0, 0.0], 'duration': d}


def test_modes_et_transitions(g1, h):
    assert fsm(g1) == 501                   # en marche (posé par l'utilisateur), comme le 27/10
    assert sport(g1, 7101, {'data': 706}) == (0, '') and fsm(g1) == 706
    # accroupi : 7105 accepté (code 0) sans bouger, comme le vrai robot assis le 27/10
    assert sport(g1, 7105, vitesse(0.3)) == (0, '') and g1.sport.consigne() == (0.0, 0.0, 0.0)
    assert g1.etat()['ignores_hors_marche'] == 1 and not g1.etat()['marche_possible']
    assert sport(g1, 7105, {'velocity': [0, 0, 0], 'duration': 1.0}) == (0, '')   # l'arrêt passe
    assert sport(g1, 7101, {'data': 706}) == (0, '') and fsm(g1) == 501
    assert sport(g1, 7101, {'data': 3}) == (0, '') and fsm(g1) == 3
    assert sport(g1, 7101, {'data': 500}) == (0, '') and fsm(g1) == 500
    assert sport(g1, 7105, vitesse(0.2)) == (0, '') and g1.sport.consigne() == (0.2, 0.0, 0.0)
    h.t += 1.01
    assert fsm(g1) == 501                         # « Démarrer » : 500 pendant 1 s, puis 501
    assert sport(g1, 7105, vitesse(0.3)) == (0, '') and g1.sport.consigne() == (0.3, 0.0, 0.0)
    assert sport(g1, 7101, {'data': 1}) == (0, '') and fsm(g1) == 1
    assert sport(g1, 7101, {'data': 0}) == (0, '') and fsm(g1) == 0
    assert sport(g1, 7101, {'data': 702}) == (0, '') and fsm(g1) == 702
    h.t += 2.01
    assert fsm(g1) == 501
    assert [p[1:] for p in g1.etat()['postures']] == [(706, 0), (706, 0), (3, 0), (500, 0), (1, 0),
                                                      (0, 0), (702, 0)]


def test_refus_realistes(g1):
    assert sport(g1, 7101, {'data': 9}) == (7302, '')
    assert sport(g1, 7101, {'data': 'x'}) == (3204, '')
    assert g1.traiter('sport', 7101, 'pas du json') == (3204, '')
    assert sport(g1, 7106, {'data': 7}) == (7303, '')
    assert sport(g1, 7106, {'data': 1}) == (0, '') and g1.taches == [1]
    assert sport(g1, 7999, {}) == (3203, '')
    assert g1.traiter('moteurs', 1, '{}') == (3203, '')


def test_commandes_interdites_comptees(g1):
    for api in (7104, 7110, 7102, 7111):
        assert sport(g1, api, {'data': 1})[0] == 0
    for posture in (2, 4, 501, 801, 802):             # postures que l'Atelier n'envoie jamais
        assert sport(g1, 7101, {'data': posture})[0] == 7302
    assert fsm(g1) == 501
    assert g1.etat()['nombre_interdits'] == 9
    assert [x[1] for x in g1.interdits_recus] == [7104, 7110, 7102, 7111] + [7101] * 5


def test_liste_et_lecture_des_danses(g1, h):
    code, data = sport(g1, 7100, {'fsm_id': 550, 'api_id': 1})
    liste = json.loads(data)
    assert code == 0 and liste['fsm_id'] == 550 and liste['api_id'] == 1
    assert liste['motion']['604'] == {'name': 'robot_dance', 'duration': 18.2}
    assert {'401', '402', '403', '602', '603', '604', '574'} == set(liste['motion'])
    lieu = pytest.importorskip('atelier.lieu')
    assert set(lieu.pilotage.lire_liste_danses(data)) == {401, 402, 403, 574, 602, 603, 604}
    assert sport(g1, 7100, {'fsm_id': 550, 'api_id': 2})[0] == 3204
    assert sport(g1, 7101, {'data': 550999}) == (7302, '')            # pas dans la liste
    assert sport(g1, 7101, {'data': 550604}) == (0, '') and fsm(g1) == 550604
    assert g1.etat()['danse']['id'] == 604
    # pendant la danse : marche, autre posture, gestes refusés ; l'arrêt passe sans effet
    assert sport(g1, 7105, vitesse(0.2))[0] == 7301
    assert sport(g1, 7105, {'velocity': [0, 0, 0], 'duration': 1.0}) == (0, '')
    assert sport(g1, 7101, {'data': 500})[0] == 7301
    assert g1.traiter('arm', 7106, json.dumps({'action_id': 26}))[0] == 7404
    h.t += 18.21
    assert fsm(g1) == 501 and g1.etat()['danse'] is None and g1.danses_jouees == [604]


def test_danse_depuis_801_retour_en_801(h):
    g1 = FauxG1(FauxSport(horloge=h), fsm=801)
    assert sport(g1, 7101, {'data': 550602}) == (0, '') and fsm(g1) == 550602
    h.t += 9.01
    assert fsm(g1) == 801


def test_danse_hors_de_la_marche_refusee(g1):
    sport(g1, 7101, {'data': 3})
    assert sport(g1, 7101, {'data': 550604})[0] == 7301


def test_gestes(g1, h):
    def geste(n):
        return g1.traiter('arm', 7106, json.dumps({'action_id': n}))[0]
    assert geste(26) == 0 and g1.etat()['bras_tenus']
    assert geste(20) == 7401                      # les bras tiennent le grand salut
    assert geste(26) == 0 and not g1.etat()['bras_tenus']           # le même geste relâche
    assert geste(17) == 0 and geste(99) == 0 and not g1.etat()['bras_tenus']
    assert geste(5) == 7402
    assert g1.traiter('arm', 7106, json.dumps({'data': 25}))[0] == 0     # format du SDK Python
    h.t += 20.1
    assert not g1.etat()['bras_tenus']            # un geste tient au plus 20 s
    sport(g1, 7101, {'data': 3})
    assert geste(26) == 7404                      # assis : pas de geste
    code, data = g1.traiter('arm', 7107, '{}')
    assert code == 0 and {'id': 26, 'name': 'high wave'} in json.loads(data)


def test_geste_refuse_quand_arm_sdk_pilote(g1, h):
    q = [0.0] * 35
    q[29] = 0.5
    g1.arm_sdk.recevoir(q, [0.0] * 35, [0.0] * 35)
    assert g1.traiter('arm', 7106, json.dumps({'action_id': 26}))[0] == 7400
    h.t += 0.6
    assert g1.traiter('arm', 7106, json.dumps({'action_id': 26}))[0] == 0


def test_voix_volume_led(g1, h):
    texte = {'index': 3, 'speaker_id': 0, 'text': 'Bonjour à tous'}
    assert g1.traiter('voice', 1001, json.dumps(texte, ensure_ascii=False)) == (0, '')
    assert g1.traiter('voice', 1006, json.dumps({'volume': 55})) == (0, '')
    assert json.loads(g1.traiter('voice', 1005, '{}')[1]) == {'volume': 55}
    assert g1.traiter('voice', 1010, json.dumps({'R': 255, 'G': 0, 'B': 128})) == (0, '')
    h.t += 1.0
    assert g1.traiter('voice', 1010, json.dumps({'R': 0, 'G': 0, 'B': 0})) == (0, '')
    voix = g1.etat()['voix']
    assert voix['tts']['text'] == 'Bonjour à tous' and voix['tts']['speaker_id'] == 0
    assert voix['volume'] == 55 and voix['led'] == {'R': 0, 'G': 0, 'B': 0}
    assert [(e['t'], e['R']) for e in voix['led_historique']] == [(10.0, 255), (11.0, 0)]
    assert g1.traiter('voice', 1006, json.dumps({'volume': 101}))[0] == 3204
    assert g1.traiter('voice', 1010, json.dumps({'R': 300, 'G': 0, 'B': 0}))[0] == 3204


def test_panne_muet_sur_tous_les_services(g1):
    g1.sport.changer_panne('muet')
    assert g1.traiter('arm', 7106, json.dumps({'action_id': 26})) is None
    assert g1.traiter('voice', 1010, json.dumps({'R': 1, 'G': 2, 'B': 3})) is None
    assert sport(g1, 7001) is None and sport(g1, 7105, vitesse(0.2)) is None
    g1.sport.changer_panne('aucune')
    assert fsm(g1) == 501


# ---------------------------------------------------------------- vague 5 : modes et 7105

def test_hors_marche_refuser_comme_avant(h):
    g1 = FauxG1(FauxSport(horloge=h), fsm=3, hors_marche='refuser')
    assert sport(g1, 7105, vitesse(0.3)) == (7301, '')
    assert sport(g1, 7105, {'velocity': [0, 0, 0], 'duration': 1.0}) == (0, '')
    assert g1.etat()['ignores_hors_marche'] == 0
    with pytest.raises(ValueError, match='ignorer ou refuser'):
        FauxG1(FauxSport(horloge=h), hors_marche='oublier')


def test_parametres_illisibles_refuses_meme_hors_marche(h):
    g1 = FauxG1(FauxSport(horloge=h), fsm=3)
    assert g1.traiter('sport', 7105, 'pas du json') == (3204, '')
    assert sport(g1, 7105, {'velocity': [0.1, 0.0], 'duration': 0.5}) == (3204, '')
    assert g1.etat()['ignores_hors_marche'] == 0


def test_course_802_marche(h):
    g1 = FauxG1(FauxSport(horloge=h), fsm=802)
    assert fsm(g1) == 802 and g1.etat()['marche_possible']
    assert sport(g1, 7105, vitesse(0.3)) == (0, '') and g1.sport.consigne() == (0.3, 0.0, 0.0)


def test_mode_change_d_un_coup(g1, h):
    """Sujet d'essai /g1_jumeau/mode : la télécommande simulée (assis, course, marche)."""
    assert sport(g1, 7105, vitesse(0.3, 5.0)) == (0, '') and g1.sport.consigne()[0] == 0.3
    g1.changer_mode(3)                             # assis en pleine marche : il s'arrête
    assert fsm(g1) == 3 and g1.sport.consigne() == (0.0, 0.0, 0.0)
    g1.changer_mode(802)
    assert fsm(g1) == 802
    sport(g1, 7101, {'data': 550604})
    g1.changer_mode(501)
    assert fsm(g1) == 501
    sport(g1, 7101, {'data': 550604})
    assert g1.etat()['danse'] is not None
    g1.changer_mode(0)                             # même pendant une danse
    assert fsm(g1) == 0 and g1.etat()['danse'] is None
    for faux in (-1, 'marche', True, 3.5):
        with pytest.raises(ValueError):
            g1.changer_mode(faux)


def test_7001_rend_toujours_le_mode(g1, h):
    for mode in (0, 1, 3, 500, 501, 702, 706, 801, 802):
        g1.changer_mode(mode)
        assert sport(g1, 7001) == (0, json.dumps({'data': mode}))


def test_seuil_de_marche_par_le_faux_g1(h):
    """Avec le seuil du nœud (0,15 m/s ; 0,2 rad/s) : 0,1 m/s ne bouge pas, 0,2 m/s marche."""
    g1 = FauxG1(FauxSport(horloge=h, seuil_lin=0.15, seuil_rot=0.2))
    assert sport(g1, 7105, vitesse(0.1)) == (0, '') and g1.sport.consigne() == (0.0, 0.0, 0.0)
    assert sport(g1, 7105, vitesse(0.2)) == (0, '') and g1.sport.consigne() == (0.2, 0.0, 0.0)
    assert g1.sport.sous_seuil == 1


# ---------------------------------------------------------------- rt/arm_sdk vérifié

def commandes_d_une_choregraphie(d):
    """Commandes LowCmd (q, kp, kd) d'une chorégraphie, à 50 Hz, comme le nœud pilotage."""
    D = pytest.importorskip('atelier.lieu.pilotage')
    sorties = []
    n = int(d['duree_s'] * 50) + 1
    for k in range(n):
        poids, angles = D.poses_bras(d, k * 0.02)
        q, kp, kd = [0.0] * 35, [0.0] * 35, [0.0] * 35
        for nom, i in D.ARTICULATIONS_BRAS.items():
            q[i], kp[i], kd[i] = angles[nom], 60.0, 1.5
        for i in (12, 13, 14):
            q[i], kp[i], kd[i] = 0.02, 240.0, 6.0
        q[29] = poids
        sorties.append((10.0 + k * 0.02, q, kp, kd))
    return sorties


def test_choregraphie_conforme_sans_ecart(h):
    D = pytest.importorskip('atelier.lieu.pilotage')
    v = VerificationArmSdk(h)
    d = D.charger_choregraphie('exemple_kpop')
    for t, q, kp, kd in commandes_d_une_choregraphie(d):
        h.t = t
        v.recevoir(q, kp, kd)
    h.t += 1.0
    etat = v.etat()
    assert etat['ecarts'] == {k: 0 for k in etat['ecarts']}, etat['exemples']
    (s,) = etat['sessions']
    assert s['frequence_hz'] == pytest.approx(50.0, rel=0.01) and s['poids_max'] == 1.0
    assert s['rampe_montee_s'] >= 1.0 and s['rampe_descente_s'] >= 1.0 and s['finie']


@pytest.mark.parametrize('faute,genre', [
    (lambda q, kp, kd: q.__setitem__(3, 0.2), 'jambes_ecrites'),
    (lambda q, kp, kd: kp.__setitem__(0, 10.0), 'jambes_ecrites'),
    (lambda q, kp, kd: q.__setitem__(12, 0.3), 'taille_pilotee'),
    (lambda q, kp, kd: q.__setitem__(18, 2.5), 'angle_hors_limites'),
    (lambda q, kp, kd: q.__setitem__(22, q[22] + 0.2), 'vitesse_bras'),
    (lambda q, kp, kd: q.__setitem__(29, 1.4), 'poids_hors_0_1'),
    (lambda q, kp, kd: q.__setitem__(30, 1.0), 'autres_moteurs')])
def test_ecarts_comptes(h, faute, genre):
    D = pytest.importorskip('atelier.lieu.pilotage')
    v = VerificationArmSdk(h)
    commandes = commandes_d_une_choregraphie(D.charger_choregraphie('exemple_kpop'))
    for k, (t, q, kp, kd) in enumerate(commandes[:400]):
        h.t = t
        if k == 300:
            faute(q, kp, kd)
        v.recevoir(q, kp, kd)
    assert v.etat()['ecarts'][genre] >= 1


def test_saut_de_poids_compte(h):
    v = VerificationArmSdk(h)
    q, z = [0.0] * 35, [0.0] * 35
    v.recevoir(list(q), z, z)
    h.t += 0.02
    q[29] = 0.5                                   # 0 → 0,5 en 20 ms : pas de rampe
    v.recevoir(list(q), z, z)
    assert v.etat()['ecarts']['saut_poids'] == 1


def test_bras_simules_suivent_les_ordres():
    b = BrasSimules()
    repos = b.avancer(0.0, False)
    assert repos[16] == pytest.approx(0.2) and repos[18] == pytest.approx(0.3)
    q = [0.0] * 35
    q[18] = 1.2
    b.ordonner(1.0, q)
    for k in range(1, 50):
        mesure = b.avancer(k * 0.02, True)
    assert mesure[18] == pytest.approx(1.2, abs=0.01)
    assert mesure[16] == pytest.approx(0.0, abs=0.01)
    b.ordonner(0.5, q)
    for k in range(50, 100):
        mesure = b.avancer(k * 0.02, True)
    assert mesure[18] == pytest.approx(0.75, abs=0.01)
    for k in range(100, 150):
        mesure = b.avancer(k * 0.02, False)
    assert mesure[18] == pytest.approx(0.3, abs=0.01)
