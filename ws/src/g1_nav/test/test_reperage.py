"""
Tests de la logique du repérage (g1_nav/reperage.py), sans ROS : section 10.5 du plan.

Corrections map → odom, odométrie qui dérive, sauts, perte de la relocalisation, échecs (pas de
carte, pas de réponse, refus, pose trop loin, pas de relocalisation), appariement par
horodatage, et le secours amcl. Une fausse horloge remplace le temps.

  python3 -m pytest ~/robot-g1/ws/src/g1_nav/test/test_reperage.py -v
"""
import json
import math

from atelier.lieu import (composer_poses, DERIVE_ECHELLE, DERIVE_LACET_PAR_M, inverser_pose,
                          valider_message)
from g1_nav.reperage import (correction_map_odom, precision_covariance, Reperage, ReperageAmcl,
                             TamponOdometrie)
import pytest

MARQUE = (2.5, 10.0, 0.0)
COV = [0.0] * 36
COV[0] = COV[7] = 0.0004


class Horloge:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t

    def avancer(self, dt):
        self.t += dt


def proche(a, b, m=1e-6, rad=1e-6):
    return math.hypot(a[0] - b[0], a[1] - b[1]) <= m and \
        abs((a[2] - b[2] + math.pi) % (2 * math.pi) - math.pi) <= rad


def conforme(r):
    erreurs = valider_message('etat_reperage', r.etat())
    assert not erreurs, erreurs
    return r.etat()


class Banc:
    """Robot sur le papier : vérité (map), odométrie qui dérive comme le faux G1."""

    def __init__(self, repere=MARQUE, depart=None, carte='repetition.pcd', **options):
        self.horloge = Horloge()
        self.repere = repere
        self.verite = depart or repere
        self.odom = (0.0, 0.0, 0.0)
        self.r = Reperage(repere, carte, horloge=self.horloge, **options)
        self.stamp = 1000.0

    def avancer(self, dx=0.0, dy=0.0, dtheta=0.0, pas=0.02):
        """Déplacement dans le repère du robot, en petits pas, odométrie qui dérive."""
        n = max(1, int(max(abs(dx), abs(dy), abs(dtheta)) / pas))
        for _ in range(n):
            ddx, ddy, ddt = dx / n, dy / n, dtheta / n
            self.verite = composer_poses(self.verite, (ddx, ddy, ddt))
            d = math.hypot(ddx, ddy)
            self.odom = composer_poses(self.odom, (ddx * (1 + DERIVE_ECHELLE),
                                                   ddy * (1 + DERIVE_ECHELLE),
                                                   ddt + DERIVE_LACET_PAR_M * d))
            self.stamp += 0.02
            self.horloge.avancer(0.02)
            self.r.sur_odometrie(self.odom, self.stamp)

    def relocaliser(self, decalage=(0.0, 0.0, 0.0)):
        """Relocalisation d'Unitree : la vérité dans son repère (plus un décalage)."""
        vraie = composer_poses(inverser_pose(self.repere), self.verite)
        self.r.sur_relocalisation(composer_poses(vraie, decalage), self.stamp, COV)

    def reperer(self, demande=None):
        self.r.sur_odometrie(self.odom, self.stamp)
        requete = self.r.demander(demande or {'id': 'essai-1'})
        assert requete is not None, self.r.etat()['message']
        reponse = {'succeed': True, 'errorCode': 0, 'info': 'ok'}
        self.r.sur_reponse(requete['id'], 0, json.dumps(reponse))
        self.horloge.avancer(0.1)
        self.relocaliser()
        return requete

    def pose_carte(self):
        return composer_poses(self.r.map_odom(), self.odom)


def test_etat_initial_non_repere():
    b = Banc()
    e = conforme(b.r)
    assert (e['etat'], e['repere'], e['pose'], e['demande']) == ('non_repere', False, None, None)
    assert 'Repérer le robot' in e['message']
    assert b.r.map_odom() is None


def test_1804_a_la_marque_pose_zero_du_repere_unitree():
    b = Banc(repere=(3.0, 9.0, 0.5))
    requete = b.r.demander({'id': 'a'})
    assert requete['api_id'] == 1804
    donnees = json.loads(requete['parameter'])['data']
    assert (donnees['x'], donnees['y'], donnees['q_z'], donnees['q_w']) == (0.0, 0.0, 0.0, 1.0)
    assert donnees['address'].endswith('/repetition.pcd')
    assert conforme(b.r)['etat'] == 'en_cours'


def test_1804_avec_pose_convertie():
    b = Banc(repere=(3.0, 9.0, 0.5))
    requete = b.r.demander({'id': 'a', 'x': 2.5, 'y': 10.0, 'theta': 0.0})
    u = requete['pose_unitree']
    assert proche(composer_poses((3.0, 9.0, 0.5), u), (2.5, 10.0, 0.0))
    d = json.loads(requete['parameter'])['data']
    assert (d['x'], d['y']) == pytest.approx((u[0], u[1]))


def test_identites_croissantes():
    b = Banc()
    ids = [b.r.demander({'id': f'd{i}'})['id'] for i in range(5)]
    assert ids == sorted(ids) and len(set(ids)) == 5


def test_repere_puis_correction_suit_la_derive():
    """2 m puis un quart de tour : l'odométrie dérive, map → base_link reste juste."""
    b = Banc()
    b.reperer()
    e = conforme(b.r)
    assert e['etat'] == 'repere' and e['repere'] is True
    assert e['precision_m'] == pytest.approx(0.02)
    assert 'précision 2 cm' in e['message']
    assert proche(b.pose_carte(), b.verite, 1e-6)
    correction_avant = b.r.map_odom()
    for _ in range(20):                 # 2 m, relocalisation tous les 10 cm
        b.avancer(dx=0.1)
        b.relocaliser()
    for _ in range(10):
        b.avancer(dtheta=math.pi / 20)
        b.relocaliser()
    assert proche(b.pose_carte(), b.verite, 1e-6, 1e-6)
    # l'odométrie seule s'est trompée de 4 cm : la correction a bougé d'autant
    odom_seule = composer_poses(correction_avant, b.odom)
    assert math.dist(odom_seule[:2], b.verite[:2]) > 0.02
    assert math.dist(b.r.map_odom()[:2], correction_avant[:2]) > 0.02
    assert conforme(b.r)['sauts'] == 0


def test_relocalisation_en_retard_appariee_par_horodatage():
    """Une relocalisation de l'instant t arrive 0,3 s plus tard : on prend l'odométrie de t."""
    b = Banc()
    b.reperer()
    stamp, vraie = b.stamp, composer_poses(inverser_pose(MARQUE), b.verite)
    b.avancer(dx=0.12)              # le robot a avancé entre-temps (0,3 s à 0,4 m/s)
    b.r.sur_relocalisation(vraie, stamp, COV)
    # reste la dérive de l'odométrie sur ces 12 cm (2 %, 0,01 rad/m) : moins de 5 mm
    assert proche(b.pose_carte(), b.verite, 0.005, 0.005)
    # sans horodatage comparable : la dernière odométrie, d'où 12 cm d'erreur
    b.r.sur_relocalisation(vraie, None, COV)
    assert math.dist(b.pose_carte()[:2], b.verite[:2]) == pytest.approx(0.12 * 1.02, abs=0.01)


def test_saut_compte_mais_applique():
    b = Banc()
    b.reperer()
    b.avancer(dx=0.05)
    b.relocaliser(decalage=(0.8, 0.0, 0.0))
    e = conforme(b.r)
    assert e['sauts'] == 1 and e['etat'] == 'repere'
    assert proche(b.pose_carte(), composer_poses(b.verite, (0.8, 0.0, 0.0)), 1e-6)


def test_perdu_puis_repere_de_nouveau():
    b = Banc()
    b.reperer()
    b.horloge.avancer(2.9)
    b.r.pas()
    assert conforme(b.r)['etat'] == 'repere'
    b.horloge.avancer(0.2)
    b.r.pas()
    e = conforme(b.r)
    assert e['etat'] == 'perdu' and e['repere'] is False
    assert e['age_s'] == pytest.approx(3.1, abs=0.01)
    assert b.r.map_odom() is not None          # le dernier map → odom reste publié
    b.relocaliser()
    assert conforme(b.r)['etat'] == 'repere'


def test_sans_carte():
    b = Banc(carte=None)
    assert b.r.demander({'id': 'a'}) is None
    e = conforme(b.r)
    assert e['etat'] == 'echec' and 'pas de carte enregistrée' in e['message']
    assert e['demande'] == 'a'


def test_demande_mal_formee():
    b = Banc()
    assert b.r.demander({'id': 'a', 'x': 1.0}) is None
    assert 'x, y et theta vont ensemble' in conforme(b.r)['message']
    assert b.r.demander('texte') is None
    assert conforme(b.r)['etat'] == 'echec'


def test_service_muet():
    b = Banc()
    b.r.demander({'id': 'a'})
    b.horloge.avancer(9.9)
    b.r.pas()
    assert conforme(b.r)['etat'] == 'en_cours'
    b.horloge.avancer(0.2)
    b.r.pas()
    e = conforme(b.r)
    assert e['etat'] == 'echec' and 'unitree_slam' in e['message']


def test_refus_du_service():
    b = Banc()
    requete = b.r.demander({'id': 'a'})
    # réponse d'un autre client du robot : ignorée
    assert not b.r.sur_reponse(requete['id'] + 1, 0, '{}')
    texte = json.dumps({'succeed': False, 'errorCode': 5, 'info': 'relocalisation impossible'})
    assert b.r.sur_reponse(requete['id'], 0, texte)
    e = conforme(b.r)
    assert e['etat'] == 'echec' and 'relocalisation impossible' in e['message']


def test_erreur_rpc():
    b = Banc()
    requete = b.r.demander({'id': 'a'})
    b.r.sur_reponse(requete['id'], 3204, '')
    assert 'refusé 1804' in conforme(b.r)['message']


def test_pas_de_relocalisation_apres_la_reponse():
    b = Banc()
    b.r.sur_odometrie(b.odom, b.stamp)
    requete = b.r.demander({'id': 'a'})
    b.relocaliser()                      # avant la réponse : ignorée
    assert conforme(b.r)['etat'] == 'en_cours'
    b.r.sur_reponse(requete['id'], 0, '{"succeed": true}')
    b.horloge.avancer(15.1)
    b.r.pas()
    e = conforme(b.r)
    assert e['etat'] == 'echec' and 'pas réussi à se repérer' in e['message']


def test_sans_odometrie():
    b = Banc()
    requete = b.r.demander({'id': 'a'})
    b.r.sur_reponse(requete['id'], 0, '{"succeed": true}')
    b.relocaliser()
    b.horloge.avancer(15.1)
    b.r.pas()
    assert 'odom_pelvis' in conforme(b.r)['message']


@pytest.mark.parametrize('decalage', [(1.2, 0.0, 0.0), (0.0, 0.0, 0.6)])
def test_pose_trop_loin_de_la_marque(decalage):
    """Le robot n'est pas sur la marque : echec, et pas de map → odom."""
    b = Banc(depart=composer_poses(MARQUE, decalage))
    b.reperer()
    e = conforme(b.r)
    assert e['etat'] == 'echec' and 'de la position annoncée' in e['message']
    assert b.r.map_odom() is None


def test_echec_apres_reussite_arrete_map_odom():
    b = Banc()
    b.reperer()
    assert b.r.map_odom() is not None
    b.r.demander({'id': 'b'})
    assert b.r.map_odom() is not None          # pendant la nouvelle demande, on le garde
    b.horloge.avancer(10.1)
    b.r.pas()
    assert conforme(b.r)['etat'] == 'echec' and b.r.map_odom() is None
    assert conforme(b.r)['pose'] is not None   # dernière pose connue


def test_repere_unitree_tourne_variante_b():
    """Critère 18, variante B : repère (3 ; 9 ; 0,5), robot posé à (2,5 ; 10 ; 0)."""
    repere = (3.0, 9.0, 0.5)
    b = Banc(repere=repere, depart=(2.5, 10.0, 0.0))
    b.reperer()                                # à la marque : le robot n'y est pas
    assert conforme(b.r)['etat'] == 'echec'
    b.reperer({'id': 'b', 'x': 2.5, 'y': 10.0, 'theta': 0.0})
    assert conforme(b.r)['etat'] == 'repere'
    assert proche(b.pose_carte(), (2.5, 10.0, 0.0), 1e-6)


def test_pose_suivi():
    """La relocalisation suit un point décalé du robot (le capteur) : il est retiré."""
    suivi = (0.1, 0.0, 0.0)
    b = Banc(pose_suivi=suivi)
    b.r.sur_odometrie(b.odom, b.stamp)
    requete = b.r.demander({'id': 'a'})
    b.r.sur_reponse(requete['id'], 0, '{"succeed": true}')
    capteur = composer_poses(composer_poses(inverser_pose(MARQUE), b.verite), suivi)
    b.r.sur_relocalisation(capteur, b.stamp, COV)
    assert proche(b.pose_carte(), b.verite, 1e-6)


def test_correction_formule():
    correction, carte = correction_map_odom((1.0, 0.0, 0.0), (0.5, 0.0, 0.0),
                                            (2.0, 3.0, math.pi / 2))
    assert proche(carte, (2.0, 4.0, math.pi / 2))
    assert proche(composer_poses(correction, (0.5, 0.0, 0.0)), carte)


def test_precision():
    assert precision_covariance(COV) == pytest.approx(0.02)
    assert precision_covariance([0.0] * 36) is None
    assert precision_covariance(None) is None


def test_tampon():
    t = TamponOdometrie(duree=2.0)
    assert t.a_l_instant(5.0) is None
    for i in range(300):
        t.ajouter(10.0 + i * 0.02, (i, 0.0, 0.0))
    assert t.a_l_instant(15.0)[0] == 250          # le plus proche
    assert t.a_l_instant(5.0)[0] == 299           # hors du tampon : le dernier
    assert t.a_l_instant(None)[0] == 299
    assert t.a_l_instant(10.5)[0] == 299          # plus vieux que 2 s : oublié


def test_amcl():
    h = Horloge()
    r = ReperageAmcl(MARQUE, horloge=h, delai_muet=2.0)
    initiale = r.demander({'id': 'a'})
    assert initiale['pose'] == MARQUE
    assert initiale['covariance'][0] == pytest.approx(0.0625)
    assert initiale['covariance'][35] == pytest.approx(0.04)
    assert conforme(r)['etat'] == 'en_cours'
    large = [0.0] * 36
    large[0] = large[7] = 0.04
    r.sur_pose_amcl(MARQUE, large)
    assert conforme(r)['etat'] == 'en_cours'
    fine = [0.0] * 36
    fine[0] = fine[7] = 0.01
    r.sur_pose_amcl(MARQUE, fine)
    e = conforme(r)
    assert e['etat'] == 'repere' and e['localisation'] == 'amcl' and e['carte'] is None
    tres_large = [0.0] * 36
    tres_large[0] = tres_large[7] = 0.36
    r.sur_pose_amcl(MARQUE, tres_large)
    assert conforme(r)['etat'] == 'perdu'
    r.sur_pose_amcl(MARQUE, fine)
    h.avancer(2.5)
    r.pas()
    assert conforme(r)['etat'] == 'perdu'
    r.demander({'id': 'b'})
    h.avancer(15.5)
    r.pas()
    assert conforme(r)['etat'] == 'echec'


def test_memes_entrees_pour_le_relais():
    """Le relais appelle les mêmes méthodes quelle que soit la localisation (sinon il plante)."""
    communes = ('demander', 'sur_odometrie', 'pas', 'etat', 'map_odom', 'pose_carte')
    for classe in (Reperage, ReperageAmcl):
        for nom in communes:
            assert callable(getattr(classe, nom)), f'{classe.__name__}.{nom} manque'
    r = ReperageAmcl(MARQUE, horloge=Horloge())
    r.sur_odometrie((1.0, 2.0, 0.3), 12.0)
    assert conforme(r)['etat'] == 'non_repere' and r.map_odom() is None
