"""
Logique du nœud pilotage, sans ROS, avec une horloge à la main (section 11.5 du plan).

Interdits, confirmations, verrou, homme mort, danses, chorégraphies (rampes, limites, vitesses,
taille tenue, jambes jamais écrites, pas) et ARRÊT. Vague 5 (section 12.6) : marche en 501,
joystick par la vitesse minimale et refusé hors marche, danses depuis 501 et retour, pas des
chorégraphies montés à la vitesse minimale (même trajet), vitesse maximale sous 0,2 refusée.
"""
import copy
import json
import math

from g1_pilotage.logique import ArretGuide, Bras, Dire, Envoi, Maitre, Pilotage
from g1_pilotage.logique import D
import pytest


class Horloge:
    def __init__(self, t=100.0):
        self.t = t

    def __call__(self):
        return self.t


def envois(resultat_ou_sorties, service=None, api=None):
    sorties = getattr(resultat_ou_sorties, 'sorties', resultat_ou_sorties)
    return [s for s in sorties if isinstance(s, Envoi)
            and (service is None or s.service == service) and (api is None or s.api_id == api)]


def repondre(p, sorties, code=0, data=''):
    for e in envois(sorties):
        p.sur_reponse(e.identifiant, code, data)


@pytest.fixture
def h():
    return Horloge()


@pytest.fixture
def p(h):
    return Pilotage(horloge=h, mur=lambda: 1.7e9 + h.t)


def en_mode(p, h, fsm):
    """Le robot répond à la prochaine lecture 7001 avec ce mode."""
    lectures = envois(p.pas(), 'sport', 7001)
    if not lectures:
        h.t += 1.0
        lectures = envois(p.pas(), 'sport', 7001)
    for e in lectures:
        p.sur_reponse(e.identifiant, 0, json.dumps({'data': fsm}))
    assert p.fsm == fsm


def en_801(p, h):
    """Le robot répond à 7001 : mode 801 (debout, prêt à marcher)."""
    en_mode(p, h, 801)


def prendre(p, h):
    r = p.prendre_main(par='test')
    assert r.statut == 202 and any(isinstance(s, ArretGuide) for s in r.sorties)
    h.t += D.ARRET_MAX_S + 0.01
    r = p.finir_prise()
    assert r.statut == 200 and p.a_la_main()
    assert [s.message['maitre'] for s in r.sorties if isinstance(s, Maitre)] == ['pilotage']


def avancer(p, h, duree, pas=0.02):
    """Fait tourner la logique à 50 Hz pendant duree ; renvoie [(t, sortie)]."""
    sorties = []
    fin = h.t + duree
    while h.t < fin - 1e-9:
        h.t = round(h.t + pas, 6)
        sorties += [(h.t, s) for s in p.pas(h.t)]
    return sorties


# ---------------------------------------------------------------- interdits et confirmations

@pytest.mark.parametrize('fsm', [2, 4, 501, 801, 802, 5, 702000, 550401, 550402, 550403])
def test_postures_interdites_rien_d_envoye(p, h, fsm):
    prendre(p, h)
    avant = p.requetes
    r = p.posture(fsm)
    assert r.statut == 403 and not r.sorties and p.requetes == avant
    assert 'refusée' in r.corps['detail']


@pytest.mark.parametrize('service,api,donnees', [
    ('sport', 7104, {'data': 1}), ('sport', 7110, {}), ('sport', 7111, {}), ('sport', 7102,
                                                                             {'data': 1}),
    ('sport', 7107, {'data': 1}), ('sport', 7103, {'data': 0.1}), ('arm', 7110, {}), ('voice',
                                                                                      1002, {}),
    ('moteurs', 1, {}), ('sport', 7105, {'velocity': [0.5, 0, 0], 'duration': 0.5}),
    ('sport', 7105, {'velocity': [0.2, 0, 0], 'duration': 3.0}), ('sport', 7101, {'data': 550403}),
    ('sport', 7100, {'fsm_id': 550, 'api_id': 2}), ('arm', 7106, {'action_id': 5}),
    ('voice', 1006, {'volume': 101}), ('voice', 1010, {'R': 300, 'G': 0, 'B': 0}),
    ('sport', 7101, 'pas du json')])
def test_requetes_interdites_403(p, h, service, api, donnees):
    prendre(p, h)
    avant = p.requetes
    r = p.requete(service, api, donnees, portique=True, zone_libre=True)
    assert r.statut == 403 and not envois(r) and p.requetes == avant


def test_confirmation_double_du_portique(p, h):
    prendre(p, h)
    for fsm in (1, 0):
        r = p.posture(fsm)
        assert r.statut == 428 and r.corps['confirmation'] == 'portique' and not r.sorties
        assert 'jeton' not in r.corps               # d'abord la case « robot au portique »
        r = p.posture(fsm, portique=True)
        assert r.statut == 428 and r.corps['jeton'] and not r.sorties
        jeton = r.corps['jeton']
        assert p.posture(fsm, portique=False, jeton=jeton).statut == 428      # case décochée
        r = p.posture(fsm, portique=True, jeton=jeton)
        assert r.statut == 200 and json.loads(envois(r, 'sport',
                                                     7101)[0].parametre) == {'data': fsm}
        assert p.posture(fsm, portique=True, jeton=jeton).statut == 428      # jeton déjà servi


def test_confirmation_expire_apres_10_s(p, h):
    prendre(p, h)
    jeton = p.posture(1, portique=True).corps['jeton']
    h.t += D.DELAI_CONFIRMATION_S + 0.01
    r = p.posture(1, portique=True, jeton=jeton)
    assert r.statut == 428 and 'expirée' in r.corps['detail'] and r.corps['jeton'] != jeton
    jeton2 = p.posture(0, portique=True).corps['jeton']
    assert p.posture(1, portique=True,
                     jeton=jeton2).statut == 428        # jeton d'une autre posture


@pytest.mark.parametrize('fsm', [500, 706, 702, 3])
def test_postures_permises(p, h, fsm):
    prendre(p, h)
    r = p.posture(fsm)
    assert r.statut == 200 and r.attendre == envois(r)[0].identifiant
    assert envois(r)[0].parametre == json.dumps({'data': fsm})


# ---------------------------------------------------------------- verrou des mouvements

def test_sans_la_main_tout_mouvement_est_refuse_mais_pas_la_voix(p, h):
    en_801(p, h)
    p.danses = {604: {'nom': 'robot', 'duree_s': 18.0}}
    for r in (p.posture(500), p.geste(26), p.tache(0), p.ordre_joystick(0.2, 0, 0), p.danser(604,
                                                                                             True),
              p.jouer(D.charger_choregraphie('exemple_kpop'), True),
              p.requete('sport', 7105, {'velocity': [0.1, 0, 0], 'duration': 0.5})):
        assert r.statut == 409 and 'prenez la main' in r.corps['detail'].lower() and not r.sorties
    for r in (p.voix('Bonjour'), p.volume(50), p.led(255, 0, 0), p.geste(99)):
        assert r.statut == 200 and len(envois(r)) == 1
    assert p.arret().statut == 200


def test_prendre_la_main_pendant_une_visite(p, h):
    p.sur_guide_etat({'etat': 'en_route', 'cible': 'b204'})
    r = p.prendre_main()
    assert r.statut == 409 and 'en mission' in r.corps['detail'] and not r.sorties
    r = p.prendre_main(forcer=True, par='atelier')
    assert r.statut == 202 and any(isinstance(s, ArretGuide) for s in r.sorties)
    assert envois(r, 'sport', 7105)[0].parametre == json.dumps({'velocity': [0.0, 0.0, 0.0],
                                                                'duration': 1.0})
    # le robot doit être immobile : pas avant 0,6 s, ni tant que le pont dit qu'il bouge
    assert not p.robot_immobile()
    h.t += 0.7
    p.sur_pont_etat({'etat': 'en_mouvement', 'consigne': {'vx': 0.3, 'vy': 0, 'wz': 0}})
    assert not p.robot_immobile()
    p.sur_pont_etat({'etat': 'arret', 'consigne': {'vx': 0, 'vy': 0, 'wz': 0}})
    assert p.robot_immobile()
    r = p.finir_prise()
    assert r.statut == 200 and p.maitre['maitre'] == 'pilotage'
    assert p.maitre['par'] == 'atelier (forcé)'
    assert p.etat()['maitre'] == 'pilotage'


def test_prise_echoue_si_le_robot_bouge_encore(p, h):
    p.prendre_main()
    h.t += 1.0
    p.sur_pont_etat({'etat': 'en_mouvement', 'consigne': {'vx': 0.3, 'vy': 0, 'wz': 0}})
    r = p.finir_prise()
    assert r.statut == 504 and not p.a_la_main() and not r.sorties


def test_rendre_la_main(p, h):
    prendre(p, h)
    p.ordre_joystick(0.2, 0, 0)
    r = p.rendre_main()
    assert r.statut == 200 and not p.a_la_main()
    assert envois(r, 'sport', 7105)
    assert [s.message['maitre'] for s in r.sorties if isinstance(s, Maitre)] == ['guide']
    assert p.ordre_joystick(0.2, 0, 0).statut == 409


def test_message_du_maitre_conforme(p, h):
    lieu = pytest.importorskip('atelier.lieu')
    assert lieu.valider_message('maitre_mouvement', p.maitre) == []
    prendre(p, h)
    assert lieu.valider_message('maitre_mouvement', p.maitre) == []
    assert lieu.valider_message('etat_pilotage', p.etat()) == []


# ---------------------------------------------------------------- joystick et homme mort

def test_joystick_plafonne_et_7105_de_0_5_s(p, h):
    prendre(p, h)
    r = p.ordre_joystick(1.0, -1.0, 2.0)
    (e,) = envois(r, 'sport', 7105)
    assert json.loads(e.parametre) == {'velocity': [0.4, -0.25, 0.6], 'duration': 0.5}
    assert r.corps['consigne'] == {'vx': 0.4, 'vy': -0.25, 'wz': 0.6}
    h.t += 0.1
    (e,) = envois(p.ordre_joystick(float('nan'), 0, 0), 'sport', 7105)
    assert json.loads(e.parametre) == {'velocity': [0.0, 0.0, 0.0],
                                       'duration': 1.0}   # NaN : arrêt


def test_vitesse_reduite():
    h = Horloge()
    p = Pilotage(horloge=h, vitesse_max=0.2)
    prendre(p, h)
    (e,) = envois(p.ordre_joystick(1.0, 1.0, 1.0), 'sport', 7105)
    assert json.loads(e.parametre)['velocity'] == [0.2, 0.125, 0.3]
    with pytest.raises(ValueError):
        Pilotage(vitesse_max=0.9)


def test_homme_mort_stopmove_0_5_s_apres_le_dernier_ordre(p, h):
    prendre(p, h)
    debut = h.t
    sorties = []
    for _ in range(10):                      # 1 s d'ordres, toutes les 0,1 s
        sorties += envois(p.ordre_joystick(0.3, 0, 0))
        sorties += [s for _, s in avancer(p, h, 0.1) if isinstance(s, Envoi) and s.api_id == 7105]
    assert len([s for s in sorties if json.loads(s.parametre)['velocity'] == [0.3, 0.0,
                                                                              0.0]]) == 10
    dernier = h.t - 0.1
    arrets = [(t, s) for t, s in avancer(p, h, 1.0) if isinstance(s, Envoi) and s.api_id == 7105]
    assert len(arrets) == 1 and json.loads(arrets[0][1].parametre)['velocity'] == [0.0, 0.0, 0.0]
    assert D.DELAI_HOMME_MORT_S - 0.001 <= arrets[0][0] - dernier <= D.DELAI_HOMME_MORT_S + 0.021
    assert arrets[0][0] - dernier + 0.0 <= D.ARRET_MAX_S
    assert p.activite() == 'repos' and debut < h.t


def test_websocket_ferme_stopmove_tout_de_suite(p, h):
    prendre(p, h)
    p.ordre_joystick(0.3, 0.1, 0)
    r = p.lacher_joystick('WebSocket fermé')
    (e,) = envois(r, 'sport', 7105)
    assert json.loads(e.parametre)['velocity'] == [0.0, 0.0, 0.0]
    assert not envois(p.lacher_joystick())                 # déjà arrêté : rien de plus


def test_joystick_qui_inonde_au_plus_20_ordres_par_seconde(p, h):
    prendre(p, h)
    total = 0
    for _ in range(100):                    # 100 ordres en 1 s
        total += len(envois(p.ordre_joystick(0.2, 0, 0), 'sport', 7105))
        total += len(envois([s for _, s in avancer(p, h, 0.01, pas=0.01)], 'sport', 7105))
    assert 15 <= total <= 21


# ---------------------------------------------------------------- gestes

def test_gestes_et_bras_tenus(p, h):
    prendre(p, h)
    r = p.geste(26)
    assert json.loads(envois(r)[0].parametre) == {'action_id': 26}
    repondre(p, r)
    assert p.bras_tenus and p.etat()['bras_tenus']
    repondre(p, p.geste(26))                       # le même geste relâche (SDK C++)
    assert not p.bras_tenus
    repondre(p, p.geste(20))
    repondre(p, p.geste(99))
    assert not p.bras_tenus
    r = p.geste(17)
    repondre(p, r, code=7404)
    assert p.dernier_refus['code'] == 7404 and 'debout' in p.dernier_refus['message']


# ---------------------------------------------------------------- équipe : LED, gestes demandés

def test_personnalite_active_met_la_led_sans_la_main(p, h):
    r = p.appliquer_personnalite({'id': 'accueillant', 'nom': 'Accueillant',
                                  'led': {'r': 0, 'g': 120, 'b': 255}})
    assert r.ok and 'LED' in r.corps['detail']
    assert [e.api_id for e in envois(r, 'voice')] == [1010]
    assert not p.a_la_main()
    r = p.appliquer_personnalite({'id': 'discret', 'nom': 'Discret'})
    assert r.ok and not envois(r)
    assert p.appliquer_personnalite('pas un dict').statut == 400


def test_geste_demande_seulement_robot_au_repos(p, h):
    r = p.geste_auto({'geste': 26, 'source': 'personnalite'})
    assert r.ok and json.loads(envois(r, 'arm', 7106)[0].parametre) == {'action_id': 26}
    repondre(p, r)
    assert p.bras_tenus
    # un second geste avant le relâchement : refusé ; puis 99 envoyé tout seul 5 s après
    assert p.geste_auto({'geste': 25}).statut == 409
    sorties = [s for _, s in avancer(p, h, 5.1) if isinstance(s, Envoi) and s.service == 'arm']
    assert [json.loads(s.parametre) for s in sorties] == [{'action_id': 99}]
    repondre(p, sorties)
    assert not p.bras_tenus
    assert p.geste_auto({'geste': 25}).statut == 429         # un toutes les 10 s
    h.t += 5.0
    assert p.geste_auto({'geste': 25}).ok


@pytest.mark.parametrize('geste', [99, 7, 'x', True, None])
def test_geste_demande_interdit(p, h, geste):
    r = p.geste_auto({'geste': geste})
    assert r.statut in (400, 403) and not r.sorties


def test_geste_demande_refuse_pilote_visite_danse(p, h):
    p.sur_guide_etat({'etat': 'en_route'})
    r = p.geste_auto({'geste': 26})
    assert r.statut == 409 and 'visite' in r.corps['detail'] and not r.sorties
    p.sur_guide_etat({'etat': 'attente'})
    prendre(p, h)
    r = p.geste_auto({'geste': 26})
    assert r.statut == 409 and 'main' in r.corps['detail'] and not r.sorties


# ---------------------------------------------------------------- danses

def liste_robot():
    return json.dumps({'fsm_id': 550, 'api_id': 1, 'motion': {
        '602': {'name': 'popping', 'duration': 9.0}, '604': {'name': 'robot_dance',
                                                             'duration': 18.2},
        '574': {'name': 'welcome', 'duration': 42.0}, '401': {'name': 'lie', 'duration': 5.0},
        '402': {'name': 'lie2', 'duration': 5.0}, '403': {'name': '?', 'duration': 3.0}}})


def danses_lues(p):
    r = p.lister_danses()
    assert json.loads(envois(r, 'sport', 7100)[0].parametre) == {'fsm_id': 550, 'api_id': 1}
    repondre(p, r, data=liste_robot())
    return p.liste_danses()


def test_liste_des_danses_et_interdites(p, h):
    liste = danses_lues(p)
    assert [d['id'] for d in liste] == [401, 402, 403, 574, 602, 604]
    assert {d['id'] for d in liste if d['interdite']} == {401, 402, 403}


def test_danse_confirmee_puis_retour_en_801(p, h):
    prendre(p, h)
    danses_lues(p)
    en_801(p, h)
    for n in (401, 402, 403):
        r = p.danser(n, zone_libre=True)
        assert r.statut == 403 and not r.sorties
    assert p.danser(999, zone_libre=True).statut == 403          # absente de la liste
    r = p.danser(604)
    assert r.statut == 428 and r.corps['confirmation'] == 'zone_libre' and not r.sorties
    r = p.danser(604, zone_libre=True)
    (e,) = envois(r)
    assert (e.service, e.api_id, json.loads(e.parametre)) == ('sport', 7101, {'data': 550604})
    repondre(p, r)
    assert p.activite() == 'danse'
    # pendant la danse : joystick, gestes, chorégraphies, postures refusés
    for refuse in (p.ordre_joystick(0.2, 0, 0), p.geste(26), p.posture(500), p.danser(602, True),
                   p.jouer(D.charger_choregraphie('exemple_kpop'), True), p.geste(99),
                   p.rendre_main()):
        assert refuse.statut == 409 and not envois(refuse)
    # ARRÊT pendant la danse : StopMove, rien d'autre
    r = p.arret()
    assert [(s.service, s.api_id) for s in r.sorties] == [('sport', 7105)] and r.corps['danse']
    # le robot danse (mode 550604), puis revient en 801 après sa durée
    debut = p.danse['debut']
    fin = None
    while h.t < debut + 25.0:
        h.t = round(h.t + 0.05, 6)
        for s in envois(p.pas(h.t), 'sport', 7001):
            p.sur_reponse(s.identifiant, 0,
                          json.dumps({'data': 801 if h.t - debut > 18.2 else 550604}))
        if fin is None and p.danse is None:
            fin = h.t
    assert fin is not None and 18.2 <= fin - debut <= 19.5
    assert 'finie' in p.message and p.activite() == 'repos'


def test_danse_refusee_hors_de_801_ou_en_mouvement(p, h):
    prendre(p, h)
    danses_lues(p)
    assert p.danser(604, True).statut == 409                     # mode inconnu
    for e in envois(p.pas(), 'sport', 7001):
        p.sur_reponse(e.identifiant, 0, json.dumps({'data': 3}))
    r = p.danser(604, True)
    assert r.statut == 409 and '801' in r.corps['detail']
    h.t += 1.0
    en_801(p, h)
    p.ordre_joystick(0.2, 0, 0)
    assert p.danser(604, True).statut == 409                     # pas immobile


def test_sans_liste_pas_de_danse(p, h):
    prendre(p, h)
    en_801(p, h)
    r = p.danser(604, True)
    assert r.statut == 409 and 'liste' in r.corps['detail']


# ---------------------------------------------------------------- chorégraphies

def prete(p, h, d=None):
    prendre(p, h)
    en_801(p, h)
    p.sur_lowstate([0.01 * i for i in range(35)])
    d = d or D.charger_choregraphie('exemple_kpop')
    r = p.jouer(d, zone_libre=True)
    assert r.statut == 200, r.corps
    return d, r


def test_choregraphie_hors_limites_refusee(p, h):
    prendre(p, h)
    en_801(p, h)
    d = D.charger_choregraphie('exemple_kpop')
    d['bras']['poses'][3]['q']['left_elbow'] = 2.5
    d['bras']['poses'][4]['q']['right_elbow'] = -1.5
    r = p.jouer(d, zone_libre=True)
    assert r.statut == 422 and len(r.corps['erreurs']) >= 2 and not r.sorties
    assert any('sort des limites' in m for m in r.corps['erreurs'])
    d = D.charger_choregraphie('exemple_kpop')
    d['pas'][0]['vy'] = 0.6
    r = p.jouer(d, zone_libre=True)
    assert r.statut == 422 and 'vy' in r.corps['erreurs'][0] and p.lecture is None


def test_choregraphie_confirmations_et_lowstate(p, h):
    prendre(p, h)
    en_801(p, h)
    d = D.charger_choregraphie('exemple_kpop')
    assert p.jouer(d).statut == 428
    r = p.jouer(d, zone_libre=True)
    # taille impossible à tenir
    assert r.statut == 409 and '/lowstate' in r.corps['detail']


def test_choregraphie_complete(p, h):
    d, r = prete(p, h)
    debut = h.t + 0.5
    assert r.corps['debut_mur'] == pytest.approx(1.7e9 + debut)
    sorties = avancer(p, h, d['duree_s'] + 2.0)
    bras = [(t, s) for t, s in sorties if isinstance(s, Bras)]
    # 50 Hz pendant toute la chorégraphie (puis plus rien)
    assert len(bras) == pytest.approx(d['duree_s'] * 50, abs=3)
    assert bras[-1][1].poids == 0.0 and p.descente is None and p.lecture is None
    poids = [s.poids for _, s in bras]
    assert max(poids) == pytest.approx(1.0)
    # rampes de 1 s au moins
    dt = 0.02
    assert max(abs(b - a) for a, b in zip(poids, poids[1:])) <= dt / D.RAMPE_MIN_S + 1e-6
    montee = next(t for t, s in bras if s.poids >= 1.0) - bras[0][0]
    descente = bras[-1][0] - max(t for t, s in bras if s.poids >= 1.0)
    assert montee >= D.RAMPE_MIN_S - 0.03 and descente >= D.RAMPE_MIN_S - 0.03
    # angles dans les limites, vitesse plafonnée, taille tenue, jambes jamais écrites
    indices = {i: n for n, i in D.ARTICULATIONS_BRAS.items()}
    taille = set(D.ARTICULATIONS_TAILLE.values())
    for (_, a), (_, b) in zip(bras, bras[1:]):
        assert set(b.q) == set(indices) | taille
        for i, nom in indices.items():
            bas, haut = D.LIMITES_BRAS[nom]
            assert bas <= b.q[i] <= haut
            assert abs(b.q[i] - a.q[i]) / dt <= D.VITESSE_BRAS_MAX + 1e-6
        for i in taille:
            assert b.q[i] == pytest.approx(0.01 * i) and b.kp[i] == D.GAINS_TAILLE['kp']
        assert not set(b.q) & set(D.INDICES_JAMBES)
    # pas : 7105 plafonnés, robot à 1 m au plus de son départ (intégration des ordres envoyés)
    pas = [(t, json.loads(s.parametre)) for t, s in sorties
           if isinstance(s, Envoi) and s.api_id == 7105]
    assert pas
    for _, prm in pas:
        assert D.refus_commande('sport', 7105, prm) is None
        vx, vy, wz = prm['velocity']
        assert abs(vx) <= D.LIMITES_PAS['vx'] and abs(vy) <= D.LIMITES_PAS['vy']
        assert abs(wz) <= D.LIMITES_PAS['wz']
    x = y = cap = 0.0
    loin = 0.0
    actif = None
    for (t, prm), suivant in zip(pas, pas[1:] + [(h.t, None)]):
        fin = min(t + prm['duration'], suivant[0])
        vx, vy, wz = prm['velocity']
        n = max(1, int((fin - t) / 0.01))
        for _ in range(n):
            ddt = (fin - t) / n
            x += (vx * math.cos(cap) - vy * math.sin(cap)) * ddt
            y += (vx * math.sin(cap) + vy * math.cos(cap)) * ddt
            cap += wz * ddt
            loin = max(loin, math.hypot(x, y))
        actif = prm
    assert loin <= D.DEPLACEMENT_MAX_M and actif['velocity'] == [0.0, 0.0, 0.0]
    attendu, _ = D.deplacement_pas(d)
    assert loin == pytest.approx(attendu, abs=0.03)
    # LED et paroles à leur temps
    leds = [(t - debut, json.loads(s.parametre)) for t, s in sorties
            if isinstance(s, Envoi) and s.api_id == 1010]
    assert [(round(t, 1), (c['R'], c['G'], c['B'])) for t, c in leds] == \
        [(round(e['t'], 1), (e['r'], e['g'], e['b'])) for e in d['led']]
    assert all(abs(t - e['t']) <= 0.021 for (t, _), e in zip(leds, d['led']))
    paroles = [(t - debut, s.message) for t, s in sorties if isinstance(s, Dire)]
    assert [m['texte'] for _, m in paroles] == [e['texte'] for e in d['paroles']]
    assert all(abs(t - e['t']) <= 0.021 and m['source'] == 'choregraphie'
               for (t, m), e in zip(paroles, d['paroles']))


def test_arret_au_milieu_d_une_choregraphie(p, h):
    d, _ = prete(p, h)
    premier = min(d['pas'], key=lambda q: q['t'])
    avancer(p, h, 0.5 + premier['t'] + premier['duree_s'] / 2)     # en plein pas, bras à poids 1
    assert p.lecture.poids == pytest.approx(1.0) and p.lecture.pas is not None
    r = p.arret()
    assert [s.api_id for s in envois(r)] == [7105]
    assert any(isinstance(s, ArretGuide) for s in r.sorties)
    t_arret = h.t
    bras = [(t, s) for t, s in avancer(p, h, 2.0) if isinstance(s, Bras)]
    assert bras[-1][1].poids == 0.0
    fin = next(t for t, s in bras if s.poids == 0.0)
    assert fin - t_arret <= 1.5
    # pendant la descente, les bras ne bougent plus
    assert all(s.q == bras[0][1].q for _, s in bras)
    # plus aucun pas ni événement après l'ARRÊT
    assert not [s for _, s in avancer(p, h, 15.0) if isinstance(s, (Bras, Dire))
                or (isinstance(s, Envoi) and s.api_id in (7105, 1010, 7106))]


def test_choregraphie_sans_bras_n_ecrit_pas_arm_sdk(p, h):
    d = copy.deepcopy(D.charger_choregraphie('exemple_kpop'))
    del d['bras']
    prendre(p, h)
    en_801(p, h)
    assert p.jouer(d,
                   zone_libre=True).statut == 200                       # sans /lowstate : permis
    assert not [s for _, s in avancer(p, h, d['duree_s'] + 1) if isinstance(s, Bras)]


def test_geste_tenu_interdit_la_choregraphie(p, h):
    prendre(p, h)
    en_801(p, h)
    p.sur_lowstate([0.0] * 35)
    repondre(p, p.geste(26))
    r = p.jouer(D.charger_choregraphie('exemple_kpop'), zone_libre=True)
    assert r.statut == 409 and '99' in r.corps['detail']


# ---------------------------------------------------------------- ARRÊT et sortie

def test_arret_toujours_permis(p, h):
    r = p.arret()                                  # sans la main
    assert envois(r, 'sport', 7105) and any(isinstance(s, ArretGuide) for s in r.sorties)
    assert p.activite() == 'arret'
    prendre(p, h)
    repondre(p, p.geste(26))
    r = p.arret()
    assert [json.loads(e.parametre) for e in envois(r, 'arm', 7106)] == [{'action_id': 99}]


def test_arret_joystick_ignore_jusqu_a_ce_qu_il_soit_lache(p, h):
    """Un pouce resté sur le manche après l'ARRÊT ne relance pas le robot : il faut le lâcher."""
    prendre(p, h)
    assert envois(p.ordre_joystick(0.3, 0.0, 0.0), 'sport', 7105)
    h.t += 0.1
    r = p.arret()
    vitesses = [json.loads(e.parametre)['velocity'] for e in envois(r, 'sport', 7105)]
    assert vitesses == [[0.0, 0.0, 0.0]]
    for _ in range(5):                      # le manche toujours tenu : refusé, rien n'est envoyé
        h.t += 0.1
        r = p.ordre_joystick(0.3, 0.0, 0.0)
        assert r.statut == 409 and 'Lâchez le joystick' in r.corps['detail']
        assert not envois(r)
        assert not p.marche
    h.t += 0.1
    assert p.ordre_joystick(0.0, 0.0, 0.0).statut == 200      # lâché (ordre nul)
    h.t += 0.1
    (e,) = envois(p.ordre_joystick(0.3, 0.0, 0.0), 'sport', 7105)    # repris : il repart
    assert json.loads(e.parametre)['velocity'] == [0.3, 0.0, 0.0]
    # « lacher » ou WebSocket fermé débloquent aussi
    h.t += 0.1
    p.arret()
    h.t += 0.1
    assert p.ordre_joystick(0.3, 0.0, 0.0).statut == 409
    p.lacher_joystick('WebSocket fermé')
    h.t += 0.1
    assert p.ordre_joystick(0.3, 0.0, 0.0).statut == 200
    h.t += 0.1
    p.arret()                               # un nouveau joystick (WebSocket ouvert) : pas bloqué
    h.t += 0.1
    p.joystick_ouvert()
    assert p.ordre_joystick(0.3, 0.0, 0.0).statut == 200


# ---------------------------------------------------------------- verrou du pont (section 12.15)
# Constat du 01/11/2026 : « Bloquer » (/pont/arret) n'arrêtait ni le joystick ni une chorégraphie,
# qui parlent directement au robot sans passer par le pont.

def test_verrou_du_pont_arrete_le_joystick_et_ne_relance_rien(p, h):
    prendre(p, h)
    en_801(p, h)
    assert envois(p.ordre_joystick(0.3, 0.0, 0.0), 'sport', 7105)
    h.t += 0.1
    r = p.sur_verrou(True)
    assert [json.loads(e.parametre)['velocity'] for e in envois(r, 'sport', 7105)] == \
        [[0.0, 0.0, 0.0]]
    assert not any(isinstance(s, ArretGuide) for s in r.sorties)    # le guide écoute le verrou
    assert p.etat()['verrou'] is True and 'Débloquer' in p.etat()['message']
    for _ in range(5):                     # manche toujours tenu : refusé, rien n'est envoyé
        h.t += 0.1
        r = p.ordre_joystick(0.3, 0.0, 0.0)
        assert r.statut == 409 and 'bloqué' in r.corps['detail'] and not envois(r)
    assert not [s for _, s in avancer(p, h, 2.0) if isinstance(s, Envoi) and s.api_id == 7105
                and json.loads(s.parametre)['velocity'] != [0.0, 0.0, 0.0]]
    # débloqué, le manche toujours tenu : rien ne repart (il faut le lâcher, puis le reprendre)
    r = p.sur_verrou(False)
    assert not envois(r) and p.etat()['verrou'] is False
    h.t += 0.1
    r = p.ordre_joystick(0.3, 0.0, 0.0)
    assert r.statut == 409 and 'Lâchez le joystick' in r.corps['detail'] and not envois(r)
    h.t += 0.1
    p.ordre_joystick(0.0, 0.0, 0.0)
    h.t += 0.1
    assert envois(p.ordre_joystick(0.3, 0.0, 0.0), 'sport', 7105)
    # le même verrou deux fois : rien de plus
    p.sur_verrou(True)
    assert not envois(p.sur_verrou(True))


def test_verrou_du_pont_refuse_les_mouvements(p, h):
    prendre(p, h)
    danses_lues(p)
    en_801(p, h)
    p.sur_verrou(True)
    for r in (p.posture(706), p.tache(1), p.geste(26), p.danser(604, zone_libre=True),
              p.jouer(D.charger_choregraphie('exemple_kpop'), zone_libre=True),
              p.requete('sport', 7105, {'velocity': [0.3, 0.0, 0.0], 'duration': 0.5})):
        assert r.statut == 409 and 'Débloquer' in r.corps['detail'] and not envois(r), r.corps
    # toujours permis : StopMove, relâcher les bras, LED, voix, l'ARRÊT
    assert envois(p.requete('sport', 7105, {'velocity': [0.0, 0.0, 0.0], 'duration': 1.0}))
    assert envois(p.geste(99)) and envois(p.led(0, 0, 255)) and envois(p.voix('bonjour'))
    assert envois(p.arret(), 'sport', 7105)
    # un geste demandé par l'équipe (robot au repos, guide qui a la main) : refusé aussi
    q = Pilotage(horloge=h, mur=lambda: 1.7e9 + h.t)
    q.sur_verrou(True)
    assert q.geste_auto({'geste': 26, 'source': 'dialogue'}).statut == 409
    q.sur_verrou(False)
    assert q.geste_auto({'geste': 26, 'source': 'dialogue'}).statut == 200


def test_verrou_du_pont_pendant_une_danse(p, h):
    """Une danse du robot ne s'interrompt pas : StopMove seulement ; ensuite, rien de nouveau."""
    prendre(p, h)
    danses_lues(p)
    en_801(p, h)
    repondre(p, p.danser(604, zone_libre=True))
    assert p.activite() == 'danse'
    r = p.sur_verrou(True)
    assert [(s.service, s.api_id) for s in r.sorties] == [('sport', 7105)]
    assert 'télécommande' in r.corps['detail']
    debut = p.danse['debut']
    while p.danse is not None and h.t < debut + 25.0:
        h.t = round(h.t + 0.05, 6)
        for s in envois(p.pas(h.t), 'sport', 7001):
            p.sur_reponse(s.identifiant, 0,
                          json.dumps({'data': 801 if h.t - debut > 18.2 else 550604}))
    assert p.danse is None
    # danse finie, toujours bloqué : aucune autre danse ni marche ; débloqué : rien ne repart
    assert p.danser(604, zone_libre=True).statut == 409
    p.sur_verrou(False)
    assert not [s for _, s in avancer(p, h, 5.0)
                if isinstance(s, Envoi) and s.api_id in (7101, 7105)]


def test_verrou_du_pont_arrete_une_choregraphie_sans_reprise(p, h):
    d, _ = prete(p, h)
    avancer(p, h, 3.0)
    assert p.lecture is not None and p.lecture.poids == pytest.approx(1.0)
    r = p.sur_verrou(True)
    assert envois(r, 'sport', 7105) and p.lecture is None
    bras = [s for _, s in avancer(p, h, 2.0) if isinstance(s, Bras)]
    assert bras and bras[-1].poids == 0.0                  # poids des bras ramené à 0
    p.sur_verrou(False)
    # débloqué : la chorégraphie ne reprend pas
    apres = avancer(p, h, 10.0)
    assert not [s for _, s in apres if isinstance(s, (Bras, Dire))
                or (isinstance(s, Envoi) and s.api_id in (7105, 1010, 7106))]
    assert p.lecture is None and p.activite() == 'repos'


def test_quitter_rend_la_main_au_guide(p, h):
    prendre(p, h)
    sorties = p.quitter()
    assert envois(sorties, 'sport', 7105)
    assert [s.message['maitre'] for s in sorties if isinstance(s, Maitre)] == ['guide']


def test_lecture_du_mode_une_fois_par_seconde(p, h):
    lectures = [s for _, s in avancer(p, h, 5.0) if isinstance(s, Envoi) and s.api_id == 7001]
    assert 5 <= len(lectures) <= 6
    assert not p.robot_repond()
    repondre(p, lectures[-1:], data=json.dumps({'data': 801}))
    assert p.robot_repond() and p.etat()['fsm'] == 801


def test_vitesse_de_lecture_moitie(p, h):
    """À la vitesse 0,5 : tout deux fois plus lent (bras, pas, LED), même chemin."""
    prendre(p, h)
    en_801(p, h)
    p.sur_lowstate([0.0] * 35)
    d = D.charger_choregraphie('exemple_kpop')
    for vitesse in (1.5, 0.1, float('nan'), 0):
        assert p.jouer(d, zone_libre=True, vitesse=vitesse).statut == 400
    r = p.jouer(d, zone_libre=True, vitesse=0.5)
    assert r.statut == 200 and r.corps['vitesse'] == 0.5
    debut = h.t + 0.5
    sorties = avancer(p, h, 2 * d['duree_s'] + 2.0)
    bras = [(t, s) for t, s in sorties if isinstance(s, Bras)]
    assert bras[-1][0] - bras[0][0] == pytest.approx(2 * d['duree_s'], abs=0.1)
    vitesse_max = max(abs(b.q[i] - a.q[i]) / 0.02
                      for (_, a), (_, b) in zip(bras, bras[1:]) for i in a.q)
    assert vitesse_max <= D.VITESSE_BRAS_MAX / 2 + 0.01
    leds = [t - debut for t, s in sorties if isinstance(s, Envoi) and s.api_id == 1010]
    assert leds == pytest.approx([2 * e['t'] for e in d['led']], abs=0.03)
    pas = [(t, json.loads(s.parametre)) for t, s in sorties
           if isinstance(s, Envoi) and s.api_id == 7105]
    # vague 5 : les pas de côté (0,2 m/s, donc 0,1 à mi-vitesse) sont refaits à 0,2 m/s, en deux
    # fois moins de temps : le vrai robot fait le même trajet
    assert max(abs(x['velocity'][1]) for _, x in pas) == pytest.approx(0.2)
    assert integrer(pas, h.t) == pytest.approx(D.deplacement_pas(d)[0], abs=0.03)


def test_guide_muet_en_pleine_visite_compte_encore(p, h):
    p.sur_guide_etat({'etat': 'en_route', 'cible': 'b204'})
    h.t += 20.0                                  # le guide s'est tu : il faut forcer
    assert p.prendre_main().statut == 409
    h.t += 11.0                                  # au-delà de 30 s : le guide ne compte plus
    assert p.prendre_main().statut == 202


# ---------------------------------------------------------------- Vue du robot : geste en cours

def test_geste_en_cours_dans_l_etat(p, h):
    assert p.etat()['geste'] is None
    prendre(p, h)
    en_801(p, h)
    r = p.geste(17)
    repondre(p, r)
    g = p.etat()['geste']
    assert (g['numero'], g['genre'], g['id'], g['nom']) == (1, 'bras', 17, D.GESTES_BRAS[17])
    h.t += 3.0
    assert p.etat()['geste']['ecoule_s'] == 3.0
    repondre(p, p.tache(2))
    g = p.etat()['geste']
    assert (g['numero'], g['genre'], g['id']) == (2, 'tache', 2)
    h.t += 10.5                                    # au-delà de DUREE_GESTE_VU_S
    assert p.etat()['geste'] is None
    repondre(p, p.geste(20), code=7404)            # refusé par le robot : pas montré
    assert p.etat()['geste'] is None
    repondre(p, p.geste(26))
    p.arret()                                      # ARRÊT relâche les bras : 99 montré
    assert p.etat()['geste']['id'] == D.GESTE_RELACHER


# ---------------------------------------------------------------- vague 5 (section 12.6)

def integrer(pas, fin_t):
    """Distance maximale au départ des ordres de marche envoyés [(t, parameter)], intégrés."""
    x = y = cap = loin = 0.0
    for (t, prm), suivant in zip(pas, pas[1:] + [(fin_t, None)]):
        fin = min(t + prm['duration'], suivant[0])
        vx, vy, wz = prm['velocity']
        n = max(1, int((fin - t) / 0.01))
        for _ in range(n):
            ddt = (fin - t) / n
            x += (vx * math.cos(cap) - vy * math.sin(cap)) * ddt
            y += (vx * math.sin(cap) + vy * math.cos(cap)) * ddt
            cap += wz * ddt
            loin = max(loin, math.hypot(x, y))
    return loin


def test_joystick_par_la_vitesse_minimale(p, h):
    """Le 27/10, 0,1 m/s ne faisait aucun pas : le manche peu incliné fait marcher à 0,2 m/s."""
    prendre(p, h)
    (e,) = envois(p.ordre_joystick(0.1, 0.0, 0.0), 'sport', 7105)
    assert json.loads(e.parametre)['velocity'] == pytest.approx([0.2, 0.0, 0.0])
    h.t += 0.1
    (e,) = envois(p.ordre_joystick(0.0, 0.0, 0.15), 'sport', 7105)
    assert json.loads(e.parametre)['velocity'] == pytest.approx([0.0, 0.0, 0.3])
    h.t += 0.1
    r = p.ordre_joystick(0.03, 0.0, 0.0)                 # zone morte : manche lâché, StopMove
    (e,) = envois(r, 'sport', 7105)
    assert json.loads(e.parametre)['velocity'] == [0.0, 0.0, 0.0] and not p.marche


def test_joystick_refuse_hors_marche(p, h):
    prendre(p, h)
    en_mode(p, h, 3)
    r = p.ordre_joystick(0.3, 0.0, 0.0)
    assert r.statut == 409 and 'assis' in r.corps['detail'] and not envois(r)
    assert r.corps['fsm'] == 3
    en_mode(p, h, 0)
    assert "n'est pas démarré" in p.ordre_joystick(0.3, 0.0, 0.0).corps['detail']
    for permis in (501, 500, 801, 802):                    # marche et course : permis
        en_mode(p, h, permis)
        h.t += 0.1
        assert p.ordre_joystick(0.3, 0.0, 0.0).statut == 200, permis
    # assis pendant la marche au joystick (la lecture arrive pendant que le manche est tenu) :
    # refus et StopMove
    h.t += 1.0
    (lecture,) = envois(p.pas(h.t), 'sport', 7001)
    assert p.ordre_joystick(0.3, 0.0, 0.0).statut == 200 and p.marche
    p.sur_reponse(lecture.identifiant, 0, json.dumps({'data': 3}))
    h.t += 0.1
    r = p.ordre_joystick(0.3, 0.0, 0.0)
    assert r.statut == 409 and [json.loads(e.parametre)['velocity'] for e in envois(r)] == \
        [[0.0, 0.0, 0.0]]
    # mode inconnu (plus de réponse depuis 3 s) : rien n'est bloqué
    h.t += 3.5
    assert p.ordre_joystick(0.3, 0.0, 0.0).statut == 200


def test_vitesse_maximale_sous_0_2_refusee():
    for v in (0.15, '0.1', 0.05):
        with pytest.raises(ValueError, match='le robot ne marche pas sous 0,2 m/s'):
            Pilotage(vitesse_max=v)
    Pilotage(vitesse_max=0.2)


def test_danse_depuis_501_et_retour_en_501(p, h):
    """Le vrai robot marche en 501 : la danse y est permise, sa fin est vue au retour en 501."""
    prendre(p, h)
    danses_lues(p)
    en_mode(p, h, 501)
    r = p.danser(604, zone_libre=True)
    assert r.statut == 200 and envois(r, 'sport', 7101)
    repondre(p, r)
    debut = p.danse['debut']
    fin = None
    while h.t < debut + 25.0:
        h.t = round(h.t + 0.05, 6)
        for s in envois(p.pas(h.t), 'sport', 7001):
            p.sur_reponse(s.identifiant, 0,
                          json.dumps({'data': 501 if h.t - debut > 18.2 else 550604}))
        if fin is None and p.danse is None:
            fin = h.t
    assert fin is not None and 18.2 <= fin - debut <= 19.5
    assert 'finie' in p.message and '501' in p.message


def test_danse_finie_au_retour_meme_avant_la_duree(p, h):
    """Vue en train de danser, puis revenue en marche plus tôt (télécommande) : finie."""
    prendre(p, h)
    danses_lues(p)
    en_mode(p, h, 501)
    repondre(p, p.danser(604, zone_libre=True))
    debut = p.danse['debut']
    while p.danse is not None and h.t < debut + 15.0:
        h.t = round(h.t + 0.05, 6)
        for s in envois(p.pas(h.t), 'sport', 7001):
            p.sur_reponse(s.identifiant, 0, json.dumps({'data': 501 if h.t - debut > 5.0
                                                        else 550604}))
    assert p.danse is None and h.t - debut < 7.0


def test_danse_pas_revenue_en_marche(p, h):
    """Le robot reste en 500 (passage) ou ailleurs : danse supposée finie après durée + 10 s."""
    prendre(p, h)
    danses_lues(p)
    en_mode(p, h, 501)
    repondre(p, p.danser(602, zone_libre=True))
    debut = p.danse['debut']
    while p.danse is not None and h.t < debut + 30.0:
        h.t = round(h.t + 0.05, 6)
        for s in envois(p.pas(h.t), 'sport', 7001):
            p.sur_reponse(s.identifiant, 0, json.dumps({'data': 500 if h.t - debut > 9.0
                                                        else 550602}))
    assert p.danse is None and 9.0 + 10.0 <= h.t - debut <= 9.0 + 10.2
    assert 'supposée finie' in p.message and 'démarrage' in p.message


def choregraphie_pas(pas):
    """Chorégraphie sans bras, avec ces pas."""
    d = copy.deepcopy(D.charger_choregraphie('exemple_kpop'))
    del d['bras']
    d['pas'] = pas
    d['gestes'], d['led'], d['paroles'] = [], [], []
    return d


def test_pas_lent_monte_a_la_vitesse_minimale_meme_trajet(p, h):
    """Un pas de côté à 0,1 m/s pendant 1 s : fait à 0,2 m/s pendant 0,5 s, puis StopMove."""
    d = choregraphie_pas([{'t': 2.0, 'vx': 0.0, 'vy': 0.1, 'wz': 0.0, 'duree_s': 1.0},
                          {'t': 5.0, 'vx': 0.0, 'vy': 0.0, 'wz': 0.15, 'duree_s': 2.0}])
    assert D.verifier_choregraphie(d) == []
    prendre(p, h)
    en_801(p, h)
    r = p.jouer(d, zone_libre=True)
    assert r.statut == 200 and len(r.corps['avertissements']) == 2
    assert 'même trajet' in r.corps['avertissements'][0]
    debut = h.t + 0.5
    sorties = avancer(p, h, d['duree_s'] + 1.0)
    pas = [(t, json.loads(s.parametre)) for t, s in sorties
           if isinstance(s, Envoi) and s.api_id == 7105]
    cote = [(t - debut, x) for t, x in pas if x['velocity'][1]]
    assert {tuple(x['velocity']) for _, x in cote} == {(0.0, 0.2, 0.0)}
    assert 2.0 - 0.03 <= cote[0][0] and cote[-1][0] + cote[-1][1]['duration'] <= 2.5 + 0.03
    arret = [t - debut for t, x in pas if x['velocity'] == [0.0, 0.0, 0.0] and t - debut > 2.0]
    assert arret and arret[0] == pytest.approx(2.5, abs=0.03)
    rotation = [x for _, x in pas if x['velocity'][2]]
    assert {tuple(x['velocity']) for x in rotation} == {(0.0, 0.0, 0.3)}
    assert integrer(pas, h.t) == pytest.approx(D.deplacement_pas(d)[0], abs=0.01)


def test_pas_trop_petit_le_robot_reste_sur_place(p, h):
    d = choregraphie_pas([{'t': 2.0, 'vx': 0.03, 'vy': 0.0, 'wz': 0.05, 'duree_s': 1.0}])
    prendre(p, h)
    en_801(p, h)
    r = p.jouer(d, zone_libre=True)
    assert r.statut == 200 and 'ne bougera pas' in r.corps['avertissements'][0]
    sorties = avancer(p, h, d['duree_s'] + 1.0)
    vitesses = [json.loads(s.parametre)['velocity'] for _, s in sorties
                if isinstance(s, Envoi) and s.api_id == 7105]
    assert vitesses and all(v == [0.0, 0.0, 0.0] for v in vitesses)


def test_exemple_kpop_sans_avertissement_et_meme_deplacement():
    d = D.charger_choregraphie('exemple_kpop')
    assert D.avertissements_choregraphie(d) == []
    assert D.deplacement_pas(d) == pytest.approx((0.15, 1.5), abs=1e-6)
    for pas in d['pas']:
        if pas['vx'] or pas['vy']:
            assert math.hypot(pas['vx'], pas['vy']) >= D.VITESSES_MIN_PONT['lin']
