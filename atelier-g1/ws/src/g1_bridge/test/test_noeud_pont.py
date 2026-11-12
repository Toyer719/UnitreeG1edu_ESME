"""
Le nœud pont_g1 en vrai (ROS 2, sans Gazebo) : le test joue le robot (outils_pont.FauxRobot).

Arrêt de lancement et vérification du lien, cadence de 10 Hz, chien de garde de 0,3 s,
plafonds et NaN, /guide/stop et sa garde, verrou /pont/arret (y compris après un redémarrage du
pont : transient_local), repérage exigé, robot muet, refus, arrêt envoyé à la sortie (SIGINT et
SIGTERM), réglage refusé, temps simulé sans effet, aucune publication hors du contrat. Vague 5
(section 12.6) : vitesse minimale (0,1 m/s envoyé à 0,2), vx_max sous le minimum refusé, lecture du
mode à 1 Hz, robot assis (pas_en_marche) puis démarré, réponses des autres programmes ignorées.
Chaque /pont/etat reçu est validé par le schéma etat_pont. Environ 2 min.
"""
import signal
import time

import pytest

from outils_pont import est_arret, FauxRobot, NoeudLance, vitesses

DEMARRAGE_S = 8.0
# Une consigne périodique peut partir entre l'instant noté par le test et l'arrivée du message au
# pont (quelques ms) : les vérifications « plus aucun mouvement » commencent un peu après
MARGE_S = 0.05


def premier_arret(robot, t0):
    """Instant du premier arrêt reçu après t0 (None s'il n'y en a pas)."""
    return next((t for t, m in robot.requetes_depuis(t0) if est_arret(m)), None)


@pytest.fixture
def robot():
    r = FauxRobot()
    yield r
    r.fermer()
    assert r.erreurs_schema == [], r.erreurs_schema[:3]


@pytest.fixture
def lancer():
    """Fabrique qui démarre un pont (arguments ROS) ; tous ceux du test sont arrêtés à la fin."""
    lances = []

    def _lancer(*arguments, nom='pont'):
        pont = NoeudLance(nom, arguments).demarrer()
        lances.append(pont)
        return pont
    yield _lancer
    for p in lances:
        p.arreter()


def demarre(robot, lancer, *arguments, repere=True):
    """Pont lancé, premier arrêt reçu ; robot repéré (5 Hz) si repere. Renvoie le pont."""
    robot.reperage = True if repere else None
    pont = lancer(*arguments)
    robot.attendre(lambda: robot.requetes, DEMARRAGE_S, "pas d'arrêt au lancement")
    if repere:
        robot.attendre_etat('pret')
    return pont


def marcher(robot, consigne, duree):
    """
    /cmd_vel à 20 Hz pendant duree, puis un dernier /cmd_vel publié par le test.

    Renvoie (début, fin) en temps monotone ; fin suit de quelques µs le dernier /cmd_vel. Les
    délais du pont se mesurent donc depuis le vrai dernier message : avant, fin était l'instant où
    le test arrêtait le fil de publication, dont le dernier envoi pouvait dater de 50 ms ou plus
    (sous charge, l'arrêt du pont arrivait alors moins de 0,24 s après fin).
    """
    debut = time.monotonic()
    robot.cmd_vel = consigne
    time.sleep(duree)
    robot.cesser('cmd_vel')
    robot.publier_cmd_vel(*consigne)
    return debut, time.monotonic()


def test_lancement_arret_puis_pret(robot, lancer):
    robot.reperage = None
    lancer()
    robot.attendre(lambda: robot.requetes, DEMARRAGE_S, 'pas d\'arrêt au lancement')
    _, premiere = robot.requetes[0]
    assert vitesses(premiere) == (0.0, 0.0, 0.0, 1.0)
    assert premiere.header.identity.api_id == 7105
    # « non repéré » passe avant « demarrage » (test_logique) : attente_reperage peut être publié
    # avant la réponse à l'arrêt de vérification. On attend donc que la réponse soit comptée. Sous
    # charge, une réponse lente (plus de 0,3 s) fait repartir l'arrêt de vérification, 2 fois au
    # plus (règle 9 de 10.3) : 1 à 3 envois, tous répondus.

    def lien_verifie():
        e = robot.dernier_etat() or {}
        if e.get('etat') == 'attente_reperage' and 1 <= e.get('reponses', 0) == e.get('envoyees'):
            return e
        return None
    etat = robot.attendre(lien_verifie, DEMARRAGE_S, 'arrêt de vérification sans réponse comptée '
                          'en attente_reperage')
    assert etat['envoyees'] <= 3, etat
    assert etat['code'] == 0 and not etat['mouvement_permis']
    robot.reperage = True
    robot.attendre_etat('pret')
    # 2 Hz au repos, et plus aucune requête
    n = len(robot.etats)
    t0 = time.monotonic()
    time.sleep(2.0)
    assert 3 <= len(robot.etats) - n <= 6
    assert robot.requetes_depuis(t0) == []


def test_pont_lance_avant_le_robot(lancer):
    """Le service sport apparaît après le pont : l'arrêt de vérification part à ce moment."""
    lancer()
    time.sleep(3.0)
    robot = FauxRobot(nom='robot_en_retard')
    try:
        robot.reperage = True
        robot.attendre(lambda: robot.requetes, 3.0, "pas d'arrêt quand le robot apparaît")
        assert est_arret(robot.requetes[0][1])
        robot.attendre_etat('pret', delai=3.0)
        time.sleep(1.0)
        assert len(robot.requetes) <= 3
    finally:
        robot.fermer()
    assert robot.erreurs_schema == []


def test_marche_a_10_hz_puis_arret_0_3_s_apres(robot, lancer):
    demarre(robot, lancer)
    debut, fin = marcher(robot, (0.3, 0.0, 0.1), 3.0)
    time.sleep(2.0)
    pendant = robot.requetes_depuis(debut + 0.5, fin - 0.2)
    frequence = len(pendant) / (fin - 0.2 - debut - 0.5)
    assert 9.0 <= frequence <= 11.0, frequence
    assert all(vitesses(m) == (0.3, 0.0, 0.1, 0.5) for _, m in pendant)
    ids = [m.header.identity.id for _, m in robot.requetes]
    assert all(b > a for a, b in zip(ids, ids[1:]))
    apres = robot.requetes_depuis(fin)
    arrets = [(t, m) for t, m in apres if est_arret(m)]
    assert len(arrets) == 1, [vitesses(m) for _, m in apres]
    # Le dernier /cmd_vel part au plus 50 ms avant « fin » : arrêt 0,3 s après, à 20 ms près
    assert 0.24 <= arrets[0][0] - fin <= 0.40, arrets[0][0] - fin
    assert all(t < arrets[0][0] for t, m in apres if not est_arret(m))
    assert robot.dernier_etat()['etat'] == 'pret'
    assert robot.dernier_etat()['reponses'] == robot.dernier_etat()['envoyees']


def test_plafonds_et_nan(robot, lancer):
    demarre(robot, lancer)
    debut, fin = marcher(robot, (1.0, 0.6, 2.0), 1.0)
    assert {vitesses(m) for _, m in robot.requetes_depuis(debut, fin)} == {(0.4, 0.25, 0.6, 0.5)}
    assert robot.dernier_etat()['consigne'] == {'vx': 0.4, 'vy': 0.25, 'wz': 0.6}
    robot.cmd_vel = (-1e9, 1e9, -1e9)
    time.sleep(0.5)
    nan = (float('nan'), 0.0, 0.0)
    robot.cmd_vel = nan
    t_nan = time.monotonic()
    robot.publier_cmd_vel(*nan)
    time.sleep(1.0)
    robot.cmd_vel = None
    # Une consigne périodique a pu partir juste avant que le NaN n'arrive : on regarde après
    apres = robot.requetes_depuis(t_nan + 0.1, t_nan + 1.0)
    assert apres and all(est_arret(m) for _, m in apres)
    arrets = [t for t, m in robot.requetes_depuis(t_nan) if est_arret(m)]
    assert arrets and arrets[0] - t_nan < 0.15


def test_guide_stop_puis_garde_de_1_s(robot, lancer):
    demarre(robot, lancer)
    robot.cmd_vel = (0.3, 0.0, 0.0)
    time.sleep(1.0)
    t_stop = time.monotonic()
    robot.guide_stop()
    time.sleep(1.8)
    robot.cmd_vel = None
    apres = robot.requetes_depuis(t_stop)
    arret = premier_arret(robot, t_stop)
    assert arret is not None and arret - t_stop < 0.1, arret and arret - t_stop
    mouvement = [t for t, m in apres if not est_arret(m) and t > t_stop + MARGE_S]
    assert mouvement, 'la marche aurait dû reprendre après 1 s'
    assert 1.0 <= min(mouvement) - t_stop <= 1.2, min(mouvement) - t_stop
    etats = [e['etat'] for t, e in robot.etats if t_stop < t < t_stop + 0.9]
    assert etats and set(etats) == {'arret'}


def test_verrou_et_redemarrage_du_pont(robot, lancer):
    pont = demarre(robot, lancer)
    robot.cmd_vel = (0.3, 0.0, 0.0)
    time.sleep(1.0)
    t_verrou = time.monotonic()
    robot.verrouiller(True)
    time.sleep(3.0)
    apres = [(t, m) for t, m in robot.requetes_depuis(t_verrou) if est_arret(m)]
    assert len(apres) == 3, [vitesses(m) for _, m in robot.requetes_depuis(t_verrou)]
    assert all(est_arret(m) for _, m in robot.requetes_depuis(t_verrou + MARGE_S))
    assert apres[0][0] - t_verrou < 0.1 and apres[-1][0] - t_verrou < 0.35
    assert robot.attendre_etat('arret_verrouille')['verrou']
    # Le verrou survit au redémarrage du pont (transient_local), sans nouveau message
    pont.signaler(signal.SIGTERM)
    assert pont.attendre(10) == 0
    t_relance = time.monotonic()
    lancer(nom='pont_relance')
    robot.attendre(lambda: robot.requetes_depuis(t_relance), DEMARRAGE_S, 'pont relancé muet')
    time.sleep(2.0)
    assert robot.dernier_etat()['etat'] == 'arret_verrouille'
    assert all(est_arret(m) for _, m in robot.requetes_depuis(t_relance))
    # Déverrouillé : rien ne part tant qu'aucun /cmd_vel neuf n'arrive
    robot.cmd_vel = None
    time.sleep(0.3)
    t_libre = time.monotonic()
    robot.verrouiller(False)
    robot.attendre_etat('pret')
    time.sleep(1.0)
    assert robot.requetes_depuis(t_libre) == []
    debut, fin = marcher(robot, (0.2, 0.0, 0.0), 0.5)
    assert any(not est_arret(m) for _, m in robot.requetes_depuis(debut))


def test_sans_reperage_cmd_vel_ignore(robot, lancer):
    demarre(robot, lancer, repere=False)
    robot.attendre_etat('attente_reperage')
    debut, fin = marcher(robot, (0.3, 0.0, 0.0), 2.0)
    assert robot.requetes_depuis(debut) == []
    robot.reperage = False
    time.sleep(0.5)
    debut, fin = marcher(robot, (0.3, 0.0, 0.0), 1.0)
    assert robot.requetes_depuis(debut) == []
    # Repéré : la marche passe ; perdu pendant la marche : arrêt tout de suite
    robot.reperage = True
    robot.attendre_etat('pret')
    robot.cmd_vel = (0.3, 0.0, 0.0)
    time.sleep(1.0)
    robot.cesser('reperage')          # plus aucun « repéré » ne peut partir après le « perdu »
    t_perdu = time.monotonic()
    robot.publier_reperage(False)
    time.sleep(1.0)
    robot.cmd_vel = None
    arret = premier_arret(robot, t_perdu)
    assert arret is not None and arret - t_perdu < 0.15
    assert all(est_arret(m) for _, m in robot.requetes_depuis(t_perdu + MARGE_S))


def test_reperage_qui_se_tait_arrete_le_robot(robot, lancer):
    demarre(robot, lancer)
    robot.cmd_vel = (0.3, 0.0, 0.0)
    time.sleep(1.0)
    # Le dernier /reperage/etat est publié par le test, et daté juste après : le fil de
    # publication (5 Hz) pouvait sinon avoir envoyé le sien jusqu'à 0,25 s avant t_dernier, et
    # l'arrêt (1 s après le dernier message) arriver moins de 0,8 s après t_dernier
    robot.cesser('reperage')
    robot.publier_reperage(True)
    t_dernier = time.monotonic()
    time.sleep(2.0)
    robot.cmd_vel = None
    arrets = [t for t, m in robot.requetes_depuis(t_dernier) if est_arret(m)]
    assert arrets and 0.8 <= arrets[0] - t_dernier <= 1.3
    assert robot.dernier_etat()['etat'] == 'attente_reperage'


def test_robot_muet_puis_retour(robot, lancer):
    demarre(robot, lancer)
    robot.cmd_vel = (0.3, 0.0, 0.0)
    time.sleep(1.0)
    t_muet = time.monotonic()
    robot.repondre = False
    etat = robot.attendre_etat('robot_muet', delai=3.0)
    assert 0.9 <= time.monotonic() - t_muet <= 1.5
    assert etat['mouvement_permis'] and 'ne répond plus' in etat['message']
    # Le pont continue d'envoyer la consigne fraîche
    t0 = time.monotonic()
    time.sleep(1.0)
    assert len([m for _, m in robot.requetes_depuis(t0) if not est_arret(m)]) >= 9
    robot.repondre = True
    robot.attendre_etat('en_mouvement', delai=1.0)
    robot.cmd_vel = None


def test_refus_avec_code_et_message(robot, lancer):
    pont = demarre(robot, lancer)
    robot.code = 7301
    robot.cmd_vel = (0.3, 0.0, 0.0)
    etat = robot.attendre_etat('refus', delai=2.0)
    robot.cmd_vel = None
    assert etat['code'] == 7301
    assert etat['message'] == ('Le robot refuse de marcher (code 7301) : mettez-le en mode '
                               'marche avec la télécommande.')
    time.sleep(0.5)
    assert 'code 7301' in pont.texte()
    robot.code = 0
    marcher(robot, (0.3, 0.0, 0.0), 0.5)
    robot.attendre(lambda: robot.dernier_etat()['code'] == 0, 2.0, 'le refus reste')


@pytest.mark.parametrize('numero', [signal.SIGINT, signal.SIGTERM])
def test_arret_envoye_a_la_sortie(robot, lancer, numero):
    pont = demarre(robot, lancer)
    robot.cmd_vel = (0.3, 0.0, 0.0)
    time.sleep(1.0)
    t_signal = time.monotonic()
    pont.signaler(numero)
    assert pont.attendre(10) == 0
    robot.cmd_vel = None
    time.sleep(0.3)
    apres = robot.requetes_depuis(t_signal)
    assert apres and est_arret(apres[-1][1]), [vitesses(m) for _, m in apres]
    assert 'arrêt envoyé (sortie)' in pont.texte()


@pytest.mark.parametrize('reglage', ['vx_max:=0.5', 'wz_max:=1.0', 'duree_consigne:=2.0'])
def test_reglage_trop_haut_refuse(lancer, reglage):
    pont = lancer('-p', reglage)
    assert pont.attendre(15) == 1
    texte = pont.texte()
    assert 'réglage refusé' in texte and reglage.split(':=')[0] in texte


def test_temps_simule_sans_effet(robot, lancer):
    """use_sim_time:=true sans /clock : les délais du pont restent en temps mural."""
    demarre(robot, lancer, '-p', 'use_sim_time:=true')
    debut, fin = marcher(robot, (0.2, 0.0, 0.0), 1.5)
    time.sleep(1.0)
    pendant = robot.requetes_depuis(debut + 0.3, fin - 0.2)
    assert 9.0 <= len(pendant) / (fin - 0.2 - debut - 0.3) <= 11.0
    assert any(est_arret(m) for _, m in robot.requetes_depuis(fin))


def test_publications_du_contrat_seulement(robot, lancer):
    """Le pont ne publie que /api/sport/request et /pont/etat (jamais /cmd_vel, ni Gazebo)."""
    demarre(robot, lancer)
    publies = robot.attendre(
        lambda: dict(robot.noeud.get_publisher_names_and_types_by_node('pont_g1', '/')),
        5.0, 'nœud pont_g1 introuvable')
    sujets = {s for s in publies if not s.startswith('/parameter_events') and s != '/rosout'}
    assert sujets == {'/api/sport/request', '/pont/etat'}
    assert publies['/api/sport/request'] == ['unitree_api/msg/Request']
    abonnements = dict(robot.noeud.get_subscriber_names_and_types_by_node('pont_g1', '/'))
    assert {'/cmd_vel', '/api/sport/response', '/reperage/etat', '/guide/stop',
            '/pont/arret'} <= set(abonnements)


# ---------------------------------------------------------------- vague 5 (section 12.6)

def test_marche_lente_envoyee_a_la_vitesse_minimale(robot, lancer):
    """Marche à 0,1 m/s (le 27/10, aucun pas) : 7105 à 0,2 ; wz 0,15 seul : 0,3 ; 0,03 : rien."""
    demarre(robot, lancer)
    t0 = time.monotonic()
    robot.cmd_vel = (0.1, 0.0, 0.0)
    etat = robot.attendre_etat('en_mouvement', delai=2.0)
    time.sleep(1.0)
    robot.cesser('cmd_vel')
    assert etat['demande'] == {'vx': 0.1, 'vy': 0.0, 'wz': 0.0}
    assert etat['consigne'] == {'vx': 0.2, 'vy': 0.0, 'wz': 0.0}
    assert etat['minimums']['vitesse_min_lin'] == 0.2
    mouvement = [m for _, m in robot.requetes_depuis(t0) if not est_arret(m)]
    assert mouvement and all(vitesses(m) == (0.2, 0.0, 0.0, 0.5) for m in mouvement)
    time.sleep(0.5)
    debut, fin = marcher(robot, (0.0, 0.0, 0.15), 1.0)
    mouvement = [m for _, m in robot.requetes_depuis(debut, fin) if not est_arret(m)]
    assert mouvement and all(vitesses(m) == (0.0, 0.0, 0.3, 0.5) for m in mouvement)
    time.sleep(0.5)
    debut, fin = marcher(robot, (0.03, 0.0, 0.0), 1.0)
    assert all(est_arret(m) for _, m in robot.requetes_depuis(debut))


def test_vx_max_sous_la_vitesse_minimale_refuse(lancer):
    pont = lancer('-p', 'vx_max:=0.1')
    assert pont.attendre(15) == 1
    texte = pont.texte()
    assert 'réglage refusé' in texte and 'vx_max 0,1 est sous la vitesse minimale' in texte
    # Mesure au portique : accepté avec les minimums à 0, et signalé dans le journal
    mesure = lancer('-p', 'vx_max:=0.1', '-p', 'wz_max:=0.15', '-p', 'vitesse_min_lin:=0.0',
                    '-p', 'vitesse_min_rot:=0.0', '-p', 'zone_morte_lin:=0.0',
                    '-p', 'zone_morte_rot:=0.0', nom='pont_mesure')
    time.sleep(4.0)
    assert mesure.vivant(), mesure.texte()[-500:]
    assert 'vitesse minimale désactivée' in mesure.texte()


def test_lecture_du_mode_une_fois_par_seconde(robot, lancer):
    demarre(robot, lancer)
    time.sleep(1.0)
    t0 = time.monotonic()
    time.sleep(4.0)
    lectures = robot.lectures_depuis(t0)
    assert 3 <= len(lectures) <= 5, len(lectures)
    assert all(m.parameter == '{}' and m.header.identity.api_id == 7001 for _, m in lectures)
    etat = robot.dernier_etat()
    assert etat['mode_robot']['fsm'] == 501 and etat['mode_robot']['en_marche'] is True
    assert etat['envoyees'] == etat['reponses']           # les lectures ne comptent pas
    assert robot.requetes_depuis(t0) == []                # au repos, aucun 7105


def test_robot_assis_pas_en_marche_puis_demarre(robot, lancer):
    demarre(robot, lancer)
    robot.cmd_vel = (0.3, 0.0, 0.0)
    robot.attendre_etat('en_mouvement', delai=2.0)
    t_assis = time.monotonic()
    robot.fsm = 3                                          # assis à la télécommande
    etat = robot.attendre_etat('pas_en_marche', delai=2.5)
    assert 'assis' in etat['message'] and 'télécommande' in etat['message']
    assert etat['mode_robot']['fsm'] == 3 and not etat['mouvement_permis']
    # l'état change à la réponse de la lecture ; l'arrêt part au pas suivant (20 ms au plus)
    arret = robot.attendre(lambda: premier_arret(robot, t_assis), 1.0, 'pas d\'arrêt (assis)')
    assert arret - t_assis < 1.5
    time.sleep(1.5)
    assert all(est_arret(m) for _, m in robot.requetes_depuis(arret + MARGE_S))
    robot.cesser('cmd_vel')
    # « Démarrer » : 500 puis 501 ; prêt, rien ne part sans /cmd_vel neuf
    robot.fsm = 500
    robot.attendre_etat('pret', delai=2.5)
    robot.fsm = 501
    time.sleep(1.5)
    t0 = time.monotonic()
    time.sleep(1.0)
    assert robot.requetes_depuis(t0) == [] and robot.dernier_etat()['etat'] == 'pret'
    debut, fin = marcher(robot, (0.3, 0.0, 0.0), 1.0)
    assert any(not est_arret(m) for _, m in robot.requetes_depuis(debut))


def test_course_et_mode_inconnu(robot, lancer):
    """Course (802) : pas_en_marche ; réponse sans data (mode inconnu) : rien n'est bloqué."""
    demarre(robot, lancer)
    robot.fsm = 802
    etat = robot.attendre_etat('pas_en_marche', delai=2.5)
    assert 'mode course' in etat['message']
    robot.fsm = None
    etat = robot.attendre_etat('pret', delai=2.5)
    assert etat['mode_robot']['fsm'] is None and etat['mode_robot']['en_marche'] is None
    debut, fin = marcher(robot, (0.3, 0.0, 0.0), 1.0)
    assert any(not est_arret(m) for _, m in robot.requetes_depuis(debut))


def test_reponses_des_autres_programmes_ignorees(robot, lancer):
    """Rafale de réponses à d'autres programmes (7001 « assis », 7105 refusés) : rien ne change."""
    demarre(robot, lancer)
    robot.cmd_vel = (0.3, 0.0, 0.0)
    robot.attendre_etat('en_mouvement', delai=2.0)
    fin = time.monotonic() + 3.0
    i = 0
    while time.monotonic() < fin:
        robot.reponse_etrangere(10 ** 9 + i, 7001, '{"data": 3}')
        robot.reponse_etrangere(2 * 10 ** 9 + i, 7105, '', code=7301)
        i += 1
        time.sleep(0.005)
    etat = robot.dernier_etat()
    robot.cmd_vel = None
    assert i > 200
    assert etat['etat'] == 'en_mouvement' and etat['code'] == 0, etat
    assert etat['mode_robot']['fsm'] == 501 and etat['reponses'] <= etat['envoyees']


@pytest.mark.parametrize('reglage,mot', [('modes_marche:=501', 'modes_marche'),
                                         ('lire_mode:=3', 'lire_mode'),
                                         ('vitesse_min_lin:=0.5', 'vitesse_min_lin')])
def test_reglages_de_la_vague_5_refuses_en_francais(lancer, reglage, mot):
    """Mauvais type ou valeur : le pont ne démarre pas et dit quoi corriger, sans trace Python."""
    pont = lancer('-p', reglage)
    assert pont.attendre(15) == 1
    texte = pont.texte()
    assert 'réglage refusé' in texte and mot in texte and 'Traceback' not in texte
