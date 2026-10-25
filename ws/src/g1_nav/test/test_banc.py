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
