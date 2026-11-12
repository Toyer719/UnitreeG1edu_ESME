"""
Tests du banc : tirage, suivi d'un trajet, CSV, résumé et série de trajets.

La série de trajets utilise le guide et le moteur factice, sans ROS, avec une fausse horloge.

  python3 -m pytest ~/robot-g1/ws/src/g1_nav/test/test_banc.py -v
"""
import csv

from atelier import RACINE
from atelier.lieu import charger_monde, charger_salles, copier_lieu
from g1_nav.banc import (COLONNES, ecrire_csv, executer, Resultat, resume, salle_proche,
                         SuiviTrajet, taux_reussite, tirer_trajets)
from g1_nav.guide import Guide
from g1_nav.moteurs import MoteurFactice
from g1_nav.routeur import Routeur
import pytest


class ClientFactice:
    """Remplace le client ROS : guide + moteur factice, le temps avance dans attendre()."""

    def __init__(self, dossier, obstacle=None):
        self.t = 0.0
        horloge = self.temps
        self.routeur = Routeur.depuis_lieu(dossier, 'rdc', horloge=horloge)
        self.moteur = MoteurFactice(depart=(2.5, 10.0, 0.0), vitesse=0.5, horloge=horloge)
        self.guide = Guide(self.routeur, self.moteur, position=self.position, horloge=horloge,
                           journal=lambda m: None)
        self.obstacle = obstacle

    def aller(self, cible):
        self.guide.aller(cible)

    def stop(self):
        self.guide.stop()

    def etat(self):
        return self.guide.etat()

    def position(self):
        return self.moteur.position

    def temps(self):
        return self.t

    def attendre(self, duree_s):
        self.t += duree_s
        if self.obstacle is not None:
            self.moteur.bloquer(self.obstacle(self.guide, self.moteur))
        self.guide.pas()


@pytest.fixture
def dossier(tmp_path):
    return copier_lieu(RACINE / 'lieux' / 'demo', tmp_path / 'demo')


@pytest.fixture
def poses(dossier):
    return {s.id: (s.pose.x, s.pose.y, s.pose.theta) for s in charger_salles(dossier)}


def test_tirage(poses):
    trajets = tirer_trajets(sorted(poses), 50, 'accueil', graine=3)
    assert len(trajets) == 50
    assert trajets[0][0] == 'accueil'
    for (dep, arr), (dep_suivant, _) in zip(trajets, trajets[1:]):
        assert dep != arr and dep_suivant == arr
    assert {a for _, a in trajets} <= set(poses)
    assert tirer_trajets(sorted(poses), 10, 'accueil', 3) == trajets[:10]
    with pytest.raises(ValueError):
        tirer_trajets(['accueil'], 3, 'accueil')


def test_salle_proche(poses):
    assert salle_proche(poses, (20.5, 12.8, 0.0)) == 'b204'
    assert salle_proche(poses, None) is None


def test_suivi_compte_arrets_et_detours():
    suivi = SuiviTrajet('b204', (21.0, 13.0, 1.57))
    for etat in ['arrive', 'en_route']:    # états d'un trajet précédent : ignorés
        suivi.noter({'etat': etat, 'cible': 'cdi'}, None, 0.0)
    assert suivi.etat is None
    for etat in ['en_route', 'bloque', 'bloque', 'detour', 'bloque', 'detour', 'arrive']:
        suivi.noter({'etat': etat, 'cible': 'b204'}, (21.1, 13.1, 0.0), 1.0)
    assert suivi.fini
    r = suivi.resultat(1, 'accueil', 42.04)
    assert (r.arrets, r.detours, r.reussite, r.duree_s) == (2, 2, True, 42.0)
    assert r.erreur_m == pytest.approx(0.141, abs=1e-3)
    assert r.distance_min_pietons_m == ''


def test_arrivee_trop_loin_n_est_pas_une_reussite():
    suivi = SuiviTrajet('b204', (21.0, 13.0, 1.57))
    suivi.noter({'etat': 'arrive', 'cible': 'b204'}, (21.5, 13.0, 0.0), 1.0)
    assert not suivi.resultat(1, 'accueil', 10.0).reussite


def test_distance_aux_pietons(dossier):
    from atelier.monde.pietons import position_pieton
    pietons = charger_monde(dossier, 'rdc').pietons
    suivi = SuiviTrajet('b204', (21.0, 13.0, 0.0), pietons, position_pieton)
    # À t = 0, pieton_nord est en (6 ; 13,8) : robot en (6 ; 13) → 0,8 m
    suivi.noter(None, (6.0, 13.0, 0.0), 0.0)
    assert suivi.distance_min == pytest.approx(0.8)


def test_csv_et_resume(tmp_path):
    resultats = [
        Resultat(1, 'accueil', 'b204', True, 50.0, 0, 1.2, 0, 0.1, 'arrive'),
        Resultat(2, 'b204', 'cdi', False, 180.0, 3, 0.6, 1, 4.0, 'delai_depasse'),
    ]
    chemin = ecrire_csv(tmp_path / 'banc.csv', resultats)
    with open(chemin, encoding='utf-8') as f:
        lignes = list(csv.DictReader(f))
    assert list(lignes[0]) == COLONNES
    assert [ligne['reussite'] for ligne in lignes] == ['oui', 'non']
    assert lignes[1]['detours'] == '1'
    texte = resume(resultats)
    assert 'Réussite : 1 / 2 trajets (50 %)' in texte
    assert 'raté : trajet 2 b204 → cdi (delai_depasse, à 4.0 m)' in texte
    assert taux_reussite(resultats) == 0.5
    assert resume([]) == 'Aucun trajet.'


def test_serie_de_trajets_avec_le_guide_factice(dossier, poses, tmp_path):
    client = ClientFactice(dossier)
    trajets = tirer_trajets(sorted(poses), 6, 'accueil', graine=1)
    resultats = executer(client, trajets, poses, delai_s=200.0, journal=lambda m: None)
    assert len(resultats) == 6
    assert all(r.reussite for r in resultats), resume(resultats)
    assert [r.arrivee for r in resultats] == [a for _, a in trajets]
    assert resultats[1].depart == trajets[0][1]
    chemin = ecrire_csv(tmp_path / 'serie.csv', resultats)
    assert len(chemin.read_text(encoding='utf-8').splitlines()) == 7


def test_trajet_avec_detour_et_trajet_trop_long(dossier, poses):
    def boite(guide, moteur):
        x, y, _ = moteur.position
        return guide.etat()['etat'] != 'detour' and 11.4 < x < 12.0 and 12.0 < y < 14.0

    client = ClientFactice(dossier, obstacle=boite)
    resultats = executer(client, [('accueil', 'b204'), ('b204', 'accueil')], poses,
                         delai_s=150.0, journal=lambda m: None)
    assert resultats[0].reussite and resultats[0].arrets == 1 and resultats[0].detours == 1
    # Délai trop court : le banc arrête le guide et note l'échec
    client2 = ClientFactice(dossier)
    r = executer(client2, [('accueil', 'cdi')], poses, delai_s=5.0, journal=lambda m: None)[0]
    assert not r.reussite and r.etat_final == 'delai_depasse'
    assert client2.guide.etat()['etat'] == 'attente'


def test_pause_apres_un_arret(dossier, poses):
    """Après un trajet trop long, le banc laisse au guide le temps de traiter l'arrêt."""
    class Client(ClientFactice):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.ordres = []

        def aller(self, cible):
            self.ordres.append(('aller', self.t))
            super().aller(cible)

        def stop(self):
            self.ordres.append(('stop', self.t))
            super().stop()

    client = Client(dossier)
    executer(client, [('accueil', 'cdi'), ('cdi', 'b204')], poses, delai_s=5.0,
             journal=lambda m: None)
    assert [o for o, _ in client.ordres[:3]] == ['aller', 'stop', 'aller']
    assert client.ordres[2][1] - client.ordres[1][1] >= 1.0


# ---------------------------------------------------------------- vague 4 : mesures des passants

def test_colonnes_de_la_vague_4():
    from atelier.lieu.passants import COLONNES_BANC_V4
    from g1_nav.banc import COLONNES_V1
    assert COLONNES_V1 == ['numero', 'depart', 'arrivee', 'reussite', 'duree_s', 'arrets',
                           'distance_min_pietons_m', 'detours', 'erreur_m', 'etat_final']
    assert COLONNES == COLONNES_V1 + list(COLONNES_BANC_V4)


def _rouler_suivi(suivi, robot, v_robot, pieton, v_pieton, duree, t0=0.0, pas=0.05, rayon=0.25):
    """Robot et piéton à vitesse constante ; le suivi mesure 20 fois par seconde."""
    t = t0
    rx, ry = robot
    px, py = pieton
    while t < t0 + duree - 1e-9:
        suivi.noter({'etat': 'en_route', 'cible': suivi.cible}, (rx, ry, 0.0), t,
                    verite=(rx, ry) + tuple(v_robot),
                    pietons=[('p', px, py) + tuple(v_pieton) + (rayon,)])
        t += pas
        rx, ry = rx + v_robot[0] * pas, ry + v_robot[1] * pas
        px, py = px + v_pieton[0] * pas, py + v_pieton[1] * pas
    return t


def test_contact_cause_par_le_robot():
    suivi = SuiviTrajet('b204', (21.0, 13.0, 0.0))
    # robot à 0,5 m/s vers un piéton immobile : contact quand les bords sont à 5 cm
    _rouler_suivi(suivi, (0.0, 0.0), (0.5, 0.0), (2.0, 0.0), (0.0, 0.0), 3.4)
    r = suivi.resultat(1, 'accueil', 3.4)
    assert (r.contacts, r.contacts_robot, r.contacts_pieton) == (1, 1, 0)
    assert r.distance_min_bord_m < 0.05
    assert r.longueur_m == pytest.approx(0.5 * (3.4 - 0.05), abs=0.01)   # mesure à 3,35 s
    assert r.distance_min_pietons_m < 0.56


def test_contact_cause_par_le_pieton_et_temps_arrete_pres():
    suivi = SuiviTrajet('b204', (21.0, 13.0, 0.0))
    # robot arrêté ; le piéton (pire cas) lui fonce dessus à 1 m/s
    _rouler_suivi(suivi, (0.0, 0.0), (0.0, 0.0), (3.0, 0.0), (-1.0, 0.0), 2.6)
    r = suivi.resultat(1, 'accueil', 2.6)
    assert (r.contacts, r.contacts_robot, r.contacts_pieton) == (1, 0, 1)
    # robot arrêté (moins de 0,02 m/s) à moins de 1,5 m bord à bord : centres de 2,49 à 0,51 m
    assert r.temps_arret_pres_s == pytest.approx((3.0 - 0.51 - 1.5) / 1.0 + 0.6, abs=0.15)
    assert r.longueur_m == 0.0


def test_sans_pietons_mesures_calcul_depuis_le_monde(dossier):
    from atelier.monde.pietons import position_pieton
    pietons = charger_monde(dossier, 'rdc').pietons
    suivi = SuiviTrajet('b204', (21.0, 13.0, 0.0), pietons, position_pieton)
    suivi.noter(None, (6.0, 13.0, 0.0), 0.0)
    r = suivi.resultat(1, 'accueil', 1.0)
    # pieton_nord en (6 ; 13,8) : 0,8 m des centres, 0,8 − 0,26 − 0,25 bord à bord
    assert r.distance_min_bord_m == pytest.approx(0.29, abs=1e-3) and r.contacts == 0


def test_etat_final_d_avant_le_depart_ignore():
    """Robot reposé au départ, même cible : l'« arrive » du trajet d'avant ne compte pas."""
    suivi = SuiviTrajet('b204', (21.0, 13.0, 0.0), etat_avant={'etat': 'arrive', 'cible': 'b204'})
    suivi.noter({'etat': 'arrive', 'cible': 'b204'}, (2.5, 10.0, 0.0), 0.0)
    suivi.noter({'etat': 'arrive', 'cible': 'b204'}, (2.5, 10.0, 0.0), 0.2)
    assert not suivi.fini
    suivi.noter({'etat': 'en_route', 'cible': 'b204'}, (2.5, 10.0, 0.0), 0.4)
    suivi.noter({'etat': 'arrive', 'cible': 'b204'}, (21.0, 13.1, 0.0), 60.0)
    assert suivi.fini and suivi.resultat(1, 'accueil', 60.0).reussite
    # au-delà de 5 s sans changement, l'état est pris tel quel (le guide n'a pas répondu)
    vieux = SuiviTrajet('b204', (21.0, 13.0, 0.0), etat_avant={'etat': 'echec', 'cible': 'b204'})
    vieux.noter({'etat': 'echec', 'cible': 'b204'}, (2.5, 10.0, 0.0), 0.0)
    vieux.noter({'etat': 'echec', 'cible': 'b204'}, (2.5, 10.0, 0.0), 6.0)
    assert vieux.fini


def test_attentes_de_passage_comptees():
    suivi = SuiviTrajet('b204', (21.0, 13.0, 0.0))
    t = 0.0
    for etat, duree in (('en_route', 10.0), ('attente_passage', 20.0), ('detour', 5.0),
                        ('attente_passage', 3.0), ('en_route', 4.0), ('arrive', 0.1)):
        fin = t + duree
        while t < fin - 1e-9:
            suivi.noter({'etat': etat, 'cible': 'b204'}, (21.0, 13.0, 0.0), t)
            t += 0.05
    r = suivi.resultat(1, 'accueil', t)
    assert (r.attentes_passage, r.detours) == (2, 1)
    assert r.duree_attente_passage_s == pytest.approx(23.0, abs=0.2)


def test_longueur_directe(dossier):
    from g1_nav.banc import longueur_directe
    routeur = Routeur.depuis_lieu(dossier, 'rdc')
    assert longueur_directe(routeur, 'accueil', 'b204') == pytest.approx(21.5)
    assert longueur_directe(routeur, 'accueil', 'b204', (2.5, 9.0)) == pytest.approx(22.5)
    assert longueur_directe(routeur, 'accueil', 'inconnue') is None
    assert longueur_directe(None, 'accueil', 'b204') is None


def test_verifier_mesures():
    from g1_nav.banc import verifier_mesures
    resultats = [
        Resultat(1, 'accueil', 'b204', True, 60.0, 0, 0.9, 0, 0.1, 'arrive', 'en_face', 0.31,
                 1, 0, 1, 0, 2.0, 0, 0.0, 22.0, 21.5),
        Resultat(2, 'accueil', 'b204', True, 190.0, 1, 0.8, 1, 0.1, 'arrive', 'en_face', 0.12,
                 0, 0, 0, 0, 0.0, 1, 21.0, 70.0, 21.5),
    ]
    verifs = {nom: ok for nom, ok, _ in verifier_mesures(resultats, {
        'reussite_min': 1.0, 'distance_bord_min_m': 0.2, 'contacts_robot_max': 0, 'detours_max': 0,
        'duree_max_s': 180, 'longueur_max_m': 75})}
    assert verifs == {'reussite_min': True, 'distance_bord_min_m': False,
                      'contacts_robot_max': True, 'detours_max': False, 'duree_max_s': False,
                      'longueur_max_m': True}
    assert verifier_mesures(resultats, {}) == []
    texte = resume(resultats)
    assert 'Contacts : 1 (causés par le robot : 0, par le piéton : 1, sans cause : 0)' in texte
    assert 'Distance minimale bord à bord : 0.12 m' in texte
    assert 'Attentes de passage : 1 (21 s)' in texte


def test_serie_avec_preparation_avant_chaque_essai(dossier, poses):
    """Scène : avant chaque essai, preparer() est appelé (robot reposé, piétons au début)."""
    client = ClientFactice(dossier)
    appels = []

    def preparer(numero, depart, arrivee):
        appels.append((numero, depart, arrivee))
        client.moteur.position = poses[depart]          # le robot est reposé au départ

    routeur = Routeur.depuis_lieu(dossier, 'rdc')
    resultats = executer(client, [('accueil', 'b204')] * 2, poses, delai_s=200.0,
                         journal=lambda m: None, scene='essai', preparer=preparer,
                         routeur=routeur)
    assert appels == [(1, 'accueil', 'b204'), (2, 'accueil', 'b204')]
    assert all(r.reussite and r.scene == 'essai' and r.depart == 'accueil' for r in resultats)
    assert all(r.longueur_directe_m == pytest.approx(21.5) for r in resultats)
    assert all(r.longueur_m > 20.0 for r in resultats)
