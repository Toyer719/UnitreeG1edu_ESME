"""
Tests du comportement du guide (vague 4, section 11.4 du plan), sans ROS, à fausse horloge.

Retour au point principal, accompagnement du visiteur, passant qui bouche le passage, détours
déraisonnables, robot perdu, verrou du pilotage, événements au visiteur, format de /guide/etat.

  python3 -m pytest ~/robot-g1/ws/src/g1_nav/test/test_comportement.py -v
"""
import math

from atelier import RACINE
from atelier.lieu import copier_lieu, valider_message
from atelier.lieu.comportement import DELAIS_GUIDE, ETATS_GUIDE
from g1_nav.guide import (DELAI_BLOQUE_S, DELAI_DEPART_S, DELAI_DETOUR_S, DELAI_PASSANT_PARTI_S,
                          DELAI_TF_PERDU_S, DISTANCE_PASSANT_M, ecart_angle, Guide,
                          PERSISTANCE_DEVANT_S, SEUIL_ORIENTATION_RAD)
from g1_nav.moteurs import etat_repos, MoteurFactice
from g1_nav.routeur import Routeur
from g1_nav.visiteur import lire_personnes, Personne, personne_devant, SuiviVisiteur
import pytest

PAS_S = 0.2     # le nœud ROS appelle pas() 5 fois par seconde
LIBRE_S = DELAI_PASSANT_PARTI_S + PERSISTANCE_DEVANT_S + 0.6    # passage libre : reprise en moins
PRINCIPAL = (2.5, 10.0, 0.0)


class Horloge:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class MoteurTournant(MoteurFactice):
    """Moteur factice qui arrive avec un cap faux de erreur_cap, et sait tourner sur place."""

    def __init__(self, *args, erreur_cap=0.35, residu=0.0, **kwargs):
        super().__init__(*args, **kwargs)
        self.erreur_cap = erreur_cap
        self.residu = residu
        self.rotations = []
        self._rotation = None

    def demarrer(self, poses):
        self._rotation = None
        return super().demarrer(poses)

    def annuler(self):
        self._rotation = None
        super().annuler()

    def tourner(self, angle):
        self._avancer()
        self.rotations.append(angle)
        self._rotation = (self.horloge() + abs(angle) / 0.5, angle)
        self._etat = dict(etat_repos(), en_cours=True, reste_m=0.0)
        return True

    def etat(self):
        if self._rotation is not None:
            fin, angle = self._rotation
            if self.horloge() >= fin:
                x, y, cap = self.position
                self.position = (x, y, cap + angle + self.residu)
                self._rotation = None
                self._etat = dict(etat_repos(), arrive=True, reste_m=0.0)
            return dict(self._etat)
        avant = self._etat['en_cours']
        e = super().etat()
        if avant and e['arrive'] and self.erreur_cap:
            x, y, cap = self.position
            self.position = (x, y, cap + self.erreur_cap)
        return e


def personne(ident, x, y):
    return Personne(ident, x, y)


class Banc:
    """Guide + moteur factice + routeur du demo + personnes vues, maître et repérage choisis."""

    def __init__(self, dossier, depart=PRINCIPAL, principal='accueil', erreur_cap=0.35, residu=0.0,
                 **reglages):
        self.horloge = Horloge()
        self.routeur = Routeur.depuis_lieu(dossier, 'rdc', horloge=self.horloge)
        self.moteur = MoteurTournant(depart=depart, vitesse=0.5, horloge=self.horloge,
                                     erreur_cap=erreur_cap, residu=residu)
        self.messages, self.changements, self.evenements, self.limites = [], [], [], []
        self.vues = []                 # personnes vues : liste, ou fonction (guide, moteur)
        self.detecteur = True          # False : pas de message frais du détecteur
        self.pilote = 'guide'
        self.perdu = None              # raison si le repérage est perdu
        self.sans_position = False     # True : plus de TF map → base_link
        self.guide = Guide(self.routeur, self.moteur, position=self._position,
                           horloge=self.horloge,
                           journal=self.messages.append, au_changement=self.changements.append,
                           suspension=lambda: self.perdu, reglages=reglages, principal=principal,
                           personnes=self._personnes, au_evenement=self.evenements.append,
                           limiter_vitesse=self.limites.append, maitre=lambda: self.pilote)

    def _position(self):
        return None if self.sans_position else self.moteur.position

    def _personnes(self):
        if not self.detecteur:
            return None
        vues = self.vues(self.guide, self.moteur) if callable(self.vues) else self.vues
        return list(vues)

    def etats(self):
        etats = []
        for c in self.changements:
            if not etats or etats[-1] != c['etat']:
                etats.append(c['etat'])
        return etats

    def codes(self):
        return [e['code'] for e in self.evenements]

    def tourner(self, duree_s, obstacle=None, jusqu_a=('arrive', 'echec')):
        for _ in range(int(round(duree_s / PAS_S))):
            self.horloge.t += PAS_S
            if obstacle is not None:
                self.moteur.bloquer(obstacle(self.guide, self.moteur))
            etat = self.guide.pas()
            if etat['etat'] in jusqu_a:
                break
        return self.guide.etat()

    def conformes(self):
        """Tous les /guide/etat et /guide/evenement émis respectent leur schéma."""
        for e in self.changements + [self.guide.etat()]:
            assert valider_message('etat_guide', e) == [], e
            assert e['etat'] in ETATS_GUIDE
        for e in self.evenements:
            assert valider_message('evenement_guide', e) == [], e


@pytest.fixture
def dossier(tmp_path):
    return copier_lieu(RACINE / 'lieux' / 'demo', tmp_path / 'demo')


def visiteur_derriere(distance):
    """Le visiteur (n° 7) à distance m derrière le robot."""
    return lambda guide, moteur: [personne(7, -distance, 0.0)]


# ---------------------------------------------------------------- retour au point principal

def test_retour_automatique_apres_l_arrivee(dossier):
    banc = Banc(dossier, delai_avant_retour_s=5.0)
    assert banc.guide.aller('b204')
    assert banc.tourner(80.0)['etat'] == 'arrive'
    etat = banc.guide.etat()
    assert etat['mission'] == 'visite' and etat['retour_dans_s'] == pytest.approx(5.0)
    assert banc.codes() == ['depart', 'arrivee']
    assert banc.evenements[-1]['texte'] == 'Voici le labo de physique.'     # phrase_arrivee
    banc.tourner(4.6, jusqu_a=())
    assert banc.guide.etat()['etat'] == 'arrive'
    banc.tourner(0.6, jusqu_a=('retour',))
    etat = banc.guide.etat()
    assert etat['etat'] == 'retour' and etat['cible'] == 'accueil' and etat['mission'] == 'retour'
    assert banc.codes()[-1] == 'retour'
    assert banc.evenements[-1]['texte'] == 'Je retourne à l\'accueil.'
    etat = banc.tourner(120.0, jusqu_a=('attente', 'echec'))
    assert etat['etat'] == 'attente' and etat['cible'] is None and etat['mission'] is None
    assert etat['message'] == 'De retour au point principal « Accueil ».'
    assert banc.codes() == ['depart', 'arrivee', 'retour', 'retour_arrive']
    # Arrivé avec 0,35 rad d'écart, le robot s'est tourné vers la flèche (10° au plus)
    x, y, cap = banc.moteur.position
    assert math.dist((x, y), PRINCIPAL[:2]) < 0.3
    assert banc.moteur.rotations and abs(ecart_angle(cap, PRINCIPAL[2])) <= math.radians(10)
    assert banc.etats() == ['en_route', 'arrive', 'retour', 'attente']
    banc.conformes()
    # Plus rien ne bouge ensuite
    banc.tourner(30.0, jusqu_a=())
    assert banc.guide.etat()['etat'] == 'attente' and not banc.moteur.etat()['en_cours']


def test_orientation_reessayee_puis_attente(dossier):
    """La rotation laisse un écart : nouvel essai (3 au plus), puis attente quand même."""
    banc = Banc(dossier, erreur_cap=0.6, residu=0.2, delai_avant_retour_s=1.0)
    moteur = banc.moteur
    banc.guide.aller('amphi')
    banc.tourner(60.0)
    banc.tourner(80.0, jusqu_a=('attente',))
    assert banc.guide.etat()['etat'] == 'attente'
    assert len(moteur.rotations) == 3          # 0,2 rad de reste à chaque fois : 3 essais
    assert banc.codes()[-1] == 'retour_arrive'


def test_pas_de_retour_quand_demande_ou_lieu_le_refusent(dossier):
    banc = Banc(dossier, delai_avant_retour_s=2.0)
    banc.guide.aller('b204', retour=False)
    banc.tourner(80.0)
    assert 'retour_dans_s' not in banc.guide.etat()
    banc.tourner(20.0, jusqu_a=())
    assert banc.guide.etat()['etat'] == 'arrive'
    assert banc.moteur.position[:2] == pytest.approx((21.0, 13.0))
    banc2 = Banc(dossier, delai_avant_retour_s=2.0, retour_auto=False)
    banc2.guide.aller('amphi')
    banc2.tourner(60.0)
    banc2.tourner(20.0, jusqu_a=())
    assert banc2.guide.etat()['etat'] == 'arrive' and banc2.guide.retour_prevu is None
    # retour: true l'emporte sur le lieu
    banc2.guide.aller('cdi', retour=True)
    banc2.tourner(80.0)
    assert banc2.guide.retour_prevu is not None


def test_retour_apres_un_echec_mais_pas_sans_position(dossier):
    banc = Banc(dossier, delai_avant_retour_s=3.0)
    banc.guide.aller('amphi')
    banc.tourner(60.0)
    assert not banc.guide.aller('grenier')            # cible inconnue, loin de l'accueil
    assert banc.guide.etat()['etat'] == 'echec' and banc.codes()[-1] == 'echec'
    assert banc.tourner(5.0, jusqu_a=('retour',))['etat'] == 'retour'
    assert banc.tourner(60.0, jusqu_a=('attente',))['etat'] == 'attente'
    # Position inconnue au moment de l'échec : pas de retour
    banc.guide.aller('amphi')
    banc.tourner(60.0)
    banc.sans_position = True
    banc.guide.aller('grenier')
    assert banc.guide.retour_prevu is None
    assert any('position du robot est inconnue' in m for m in banc.messages)


def test_nouvelle_demande_ou_stop_annulent_le_retour(dossier):
    banc = Banc(dossier, delai_avant_retour_s=2.0)
    banc.guide.aller('amphi')
    banc.tourner(60.0)
    assert banc.guide.retour_prevu is not None
    banc.guide.stop()
    assert banc.guide.retour_prevu is None and banc.codes()[-1] == 'arret'
    banc.tourner(10.0, jusqu_a=())
    assert banc.guide.etat()['etat'] == 'attente' and not banc.moteur.etat()['en_cours']
    # Pendant le retour, une nouvelle demande l'interrompt
    banc.guide.aller('b204')
    banc.tourner(80.0)
    banc.tourner(3.0, jusqu_a=('retour',))
    assert banc.guide.etat()['etat'] == 'retour'
    banc.guide.aller('cdi')
    etat = banc.guide.etat()
    assert etat['etat'] == 'en_route' and etat['cible'] == 'cdi' and etat['mission'] == 'visite'
    # Un stop au repos ne dit rien
    banc.guide.stop()
    n = len(banc.evenements)
    banc.guide.stop()
    assert len(banc.evenements) == n


def test_visite_du_point_principal_lui_meme(dossier):
    """Aller à l'accueil depuis l'accueil, ou y revenir : pas de retour en plus, sans annonce."""
    banc = Banc(dossier, delai_avant_retour_s=1.0)
    banc.guide.aller('principal')
    assert banc.guide.etat()['cible'] == 'accueil'
    banc.tourner(10.0)
    assert banc.guide.etat()['etat'] == 'arrive'
    banc.tourner(15.0, jusqu_a=('attente',))
    assert banc.guide.etat()['etat'] == 'attente'
    assert 'retour' not in banc.codes() and 'retour_arrive' not in banc.codes()


# ---------------------------------------------------------------- accompagnement du visiteur

def test_accompagnement_depart_ralenti_attente_reprise(dossier):
    banc = Banc(dossier, delai_visiteur_s=10.0)
    distance = [1.0]
    banc.vues = lambda g, m: [personne(7, -distance[0], 0.2)]
    banc.guide.aller('b204', accompagner=True)
    etat = banc.guide.etat()
    assert etat['accompagner'] is True and etat['visiteur']['vu'] is True
    assert banc.codes() == ['depart']
    assert banc.evenements[0]['texte'] == 'Suivez-moi, je vous emmène à Salle B204.'
    banc.tourner(4.0, jusqu_a=())
    assert banc.limites == [None]          # aucune limite pendant que le visiteur suit
    # Il traîne : au-delà de 2 m, le robot ralentit (50 %), une seule fois
    distance[0] = 2.6
    banc.tourner(1.0, jusqu_a=())
    assert banc.limites[-1] == pytest.approx(50.0) and banc.codes()[-1] == 'ralentir'
    banc.tourner(2.0, jusqu_a=())
    assert banc.codes().count('ralentir') == 1
    # Au-delà de 3,5 m : arrêt, attente_visiteur
    distance[0] = 4.0
    banc.tourner(1.0, jusqu_a=('attente_visiteur',))
    etat = banc.guide.etat()
    assert etat['etat'] == 'attente_visiteur' and banc.codes()[-1] == 'attente_visiteur'
    assert not banc.moteur.etat()['en_cours']
    assert etat['message'] == 'Le visiteur ne suit plus : le robot l\'attend (10 s au plus).'
    position = banc.moteur.position
    banc.tourner(5.0, jusqu_a=())
    assert banc.moteur.position == position
    # Il revient : reprise, vitesse normale
    distance[0] = 1.2
    banc.tourner(1.0, jusqu_a=('en_route',))
    assert banc.guide.etat()['etat'] == 'en_route' and banc.codes()[-1] == 'visiteur_retrouve'
    assert banc.limites[-1] is None
    assert banc.tourner(80.0)['etat'] == 'arrive'
    assert banc.codes()[-1] == 'arrivee'
    banc.conformes()


def test_visiteur_qui_part_abandon_puis_retour(dossier):
    banc = Banc(dossier, delai_visiteur_s=10.0, delai_avant_retour_s=2.0)
    distance = [1.0]
    banc.vues = lambda g, m: [personne(7, -distance[0], 0.0)] if distance[0] < 8 else []
    banc.guide.aller('b204', accompagner=True)
    banc.tourner(6.0, jusqu_a=())
    distance[0] = 9.0                   # il part : plus vu
    banc.tourner(1.0, jusqu_a=())
    assert banc.guide.etat()['etat'] == 'en_route'    # pas encore 2 s sans le voir
    banc.tourner(2.0, jusqu_a=('attente_visiteur',))
    assert banc.guide.etat()['etat'] == 'attente_visiteur'
    t0 = banc.horloge.t
    banc.tourner(15.0, jusqu_a=('echec',))
    etat = banc.guide.etat()
    assert etat['etat'] == 'echec' and banc.horloge.t - t0 == pytest.approx(10.0, abs=0.3)
    assert 'visite abandonnée' in etat['message']
    assert banc.codes()[-1] == 'visiteur_perdu' and 'echec' not in banc.codes()
    assert banc.evenements[-1]['texte'] == 'Je ne vous vois plus. Je retourne à l\'accueil.'
    banc.tourner(3.0, jusqu_a=('retour',))
    assert banc.guide.etat()['etat'] == 'retour'
    assert banc.tourner(60.0, jusqu_a=('attente',))['etat'] == 'attente'
    banc.conformes()


def test_personne_derriere_au_depart_sinon_seul(dossier):
    banc = Banc(dossier)
    banc.vues = []
    banc.guide.aller('b204', accompagner=True)
    assert banc.codes() == []
    banc.tourner(2.0, jusqu_a=())
    assert banc.codes() == []
    banc.tourner(1.2, jusqu_a=())
    assert banc.codes() == ['seul']
    assert banc.evenements[0]['texte'] == ('Je ne vous vois pas derrière moi : je pars vers '
                                           'Salle B204, suivez-moi.')
    assert banc.guide.etat()['accompagner'] is False and banc.guide.etat()['visiteur'] is None
    assert banc.tourner(80.0)['etat'] == 'arrive'
    # Le visiteur arrive pendant les 3 s : départ annoncé dès qu'il est vu
    banc2 = Banc(dossier)
    banc2.vues = []
    banc2.guide.aller('amphi', accompagner=True)
    banc2.tourner(1.0, jusqu_a=())
    banc2.vues = [personne(4, -1.5, 0.5)]
    banc2.tourner(0.4, jusqu_a=())
    assert banc2.codes() == ['depart'] and banc2.guide.etat()['accompagner'] is True
    # Trop loin au départ (plus de 2,5 m) : pas choisi
    banc3 = Banc(dossier)
    banc3.vues = [personne(4, -3.0, 0.0)]
    banc3.guide.aller('amphi', accompagner=True)
    banc3.tourner(3.4, jusqu_a=())
    assert banc3.codes() == ['seul']


def test_accompagnement_desactive_ou_id_simple(dossier):
    banc = Banc(dossier, accompagnement=False)
    banc.vues = visiteur_derriere(1.0)
    banc.guide.aller('b204', accompagner=True)
    assert banc.guide.etat()['accompagner'] is False and banc.codes() == ['depart']
    banc2 = Banc(dossier)
    banc2.vues = visiteur_derriere(5.0)
    banc2.guide.aller('b204')                  # l'id simple : visite sans accompagnement
    assert banc2.tourner(80.0)['etat'] == 'arrive'
    assert 'attente_visiteur' not in banc2.etats()


def test_visiteur_suivi_sous_un_autre_numero(dossier):
    """Le détecteur renumérote le visiteur : retrouvé par sa position, sans arrêt."""
    banc = Banc(dossier)
    numero = [7]
    banc.vues = lambda g, m: [personne(numero[0], -1.0, 0.0)]
    banc.guide.aller('b204', accompagner=True)
    banc.tourner(3.0, jusqu_a=())
    numero[0] = 12
    banc.tourner(3.0, jusqu_a=())
    assert banc.guide.etat()['etat'] == 'en_route'
    assert banc.guide._suivi.id == 12


def test_detecteur_muet_le_robot_attend(dossier):
    banc = Banc(dossier, delai_visiteur_s=5.0, delai_avant_retour_s=1.0)
    banc.vues = visiteur_derriere(1.0)
    banc.guide.aller('b204', accompagner=True)
    banc.tourner(3.0, jusqu_a=())
    banc.detecteur = False
    banc.tourner(3.0, jusqu_a=('attente_visiteur',))
    assert banc.guide.etat()['etat'] == 'attente_visiteur'
    assert banc.guide.etat()['visiteur']['vu'] is False


# ---------------------------------------------------------------- passant qui bouche le passage

def passant_devant(guide, moteur):
    return [personne(3, 0.9, 0.1)]


def test_passant_qui_s_ecarte(dossier):
    banc = Banc(dossier)
    banc.guide.aller('b204')
    banc.tourner(4.0, jusqu_a=())
    banc.vues = passant_devant
    banc.moteur.bloquer(True)
    banc.tourner(DELAI_BLOQUE_S + 1.4, jusqu_a=('attente_passage',))
    etat = banc.guide.etat()
    assert etat['etat'] == 'attente_passage' and banc.codes()[-1] == 'passant_gene'
    assert banc.evenements[-1]['texte'] == 'Pardon, puis-je passer ?'
    assert 'bloque' not in banc.etats()
    # Pendant l'attente, le robot est arrêté (moteur annulé : Nav2 ne contourne pas de lui-même)
    assert not banc.moteur.etat()['en_cours']
    position = banc.moteur.position
    banc.tourner(12.0, jusqu_a=('detour',))
    assert banc.guide.etat()['etat'] == 'attente_passage' and banc.guide.detours == 0
    assert banc.moteur.position == position
    banc.vues = []
    banc.moteur.bloquer(False)
    banc.tourner(LIBRE_S, jusqu_a=('en_route',))
    assert banc.guide.etat()['etat'] == 'en_route' and banc.codes()[-1] == 'passage_libre'
    assert banc.moteur.etat()['en_cours']
    assert banc.tourner(80.0)['etat'] == 'arrive' and banc.guide.detours == 0
    assert banc.etats() == ['en_route', 'attente_passage', 'en_route', 'arrive']
    assert banc.guide.attentes_passage == 1
    banc.conformes()


def test_groupe_qui_reste_detour_apres_le_delai(dossier):
    banc = Banc(dossier, delai_passant_s=20.0)
    banc.guide.aller('b204')

    # Le groupe est en x = 15,5 : le robot s'arrête devant (14,5) et le voit devant lui
    def groupe(guide, moteur):
        x, y, _ = moteur.position
        return [personne(9, 1.0, 0.0)] if 13.8 < x < 15.0 and y > 12 else []

    def obstacle(guide, moteur):
        x, y, _ = moteur.position
        return guide.etat()['etat'] != 'detour' and 14.4 < x < 15.0 and y > 12
    banc.vues = groupe
    banc.tourner(60.0, obstacle=obstacle, jusqu_a=('attente_passage',))
    t0 = banc.horloge.t
    etat = banc.tourner(60.0, obstacle=obstacle, jusqu_a=('detour', 'echec'))
    assert etat['etat'] == 'detour'
    assert banc.horloge.t - t0 >= 20.0 and banc.horloge.t - t0 <= 21.0
    assert banc.codes()[-1] == 'detour'
    assert banc.evenements[-1]['texte'] == 'Le passage est encombré : je prends un autre chemin.'
    # Détour raisonnable : par le couloir sud, au plus 75 m en tout
    assert 'hall_sud' in etat['itineraire']
    assert banc.tourner(200.0, obstacle=obstacle)['etat'] == 'arrive'
    assert banc.guide._parcouru <= 75.0


def test_passant_parti_mais_obstacle_bloque_puis_detour(dossier):
    banc = Banc(dossier)
    banc.guide.aller('b204')
    banc.tourner(4.0, jusqu_a=())
    banc.vues = passant_devant
    banc.moteur.bloquer(True)
    banc.tourner(DELAI_BLOQUE_S + 1.4, jusqu_a=('attente_passage',))
    banc.vues = []                      # parti, mais le robot n'avance pas (une boîte)
    banc.tourner(LIBRE_S + DELAI_DEPART_S + DELAI_DETOUR_S, jusqu_a=('detour',))
    assert banc.etats() == ['en_route', 'attente_passage', 'en_route', 'bloque', 'detour']


def test_passants_desactives(dossier):
    banc = Banc(dossier, passants=False)
    banc.guide.aller('b204')
    banc.tourner(4.0, jusqu_a=())
    banc.vues = passant_devant
    banc.moteur.bloquer(True)
    banc.tourner(DELAI_DETOUR_S + 1.5, jusqu_a=('detour',))
    assert banc.etats() == ['en_route', 'bloque', 'detour']


def test_personne_sur_le_cote_ou_derriere_n_est_pas_un_passant(dossier):
    banc = Banc(dossier)
    banc.guide.aller('b204')
    banc.tourner(4.0, jusqu_a=())
    banc.vues = [personne(1, 0.3, 1.2), personne(2, -1.0, 0.0),
                 personne(3, DISTANCE_PASSANT_M + 0.3, 0.0)]
    banc.moteur.bloquer(True)
    banc.tourner(DELAI_BLOQUE_S + 1.4, jusqu_a=('bloque',))
    assert banc.guide.etat()['etat'] == 'bloque'


def test_detour_deraisonnable_refuse(dossier):
    """Vers amphi, à 9,5 m, le seul détour fait le tour du lycée (59 m) : refusé."""
    banc = Banc(dossier)
    banc.guide.aller('amphi')
    banc.tourner(8.0, jusqu_a=())       # sur hall_nord – amphi
    banc.moteur.bloquer(True)
    etat = banc.tourner(DELAI_DETOUR_S + 3.0, jusqu_a=('detour', 'echec'))
    assert etat['etat'] == 'echec' and 'le seul détour ferait' in etat['message']
    assert banc.routeur.couloirs_bloques() == []
    # Avec une marge plus grande, il est accepté
    banc2 = Banc(dossier, detour_marge_m=80.0)
    banc2.guide.aller('amphi')
    banc2.tourner(8.0, jusqu_a=())
    banc2.moteur.bloquer(True)
    assert banc2.tourner(DELAI_DETOUR_S + 3.0, jusqu_a=('detour', 'echec'))['etat'] == 'detour'


def test_detour_deraisonnable_avec_passant_attente_prolongee(dossier):
    banc = Banc(dossier, delai_passant_s=5.0)
    banc.guide.aller('amphi')
    banc.tourner(8.0, jusqu_a=())
    banc.vues = passant_devant
    banc.moteur.bloquer(True)
    banc.tourner(DELAI_BLOQUE_S + 1.4, jusqu_a=('attente_passage',))
    banc.tourner(5.4, jusqu_a=('detour', 'echec'))
    etat = banc.guide.etat()
    assert etat['etat'] == 'attente_passage' and 'détour serait trop long' in etat['message']
    assert banc.codes().count('passant_gene') == 2
    etat = banc.tourner(20.0, jusqu_a=('detour', 'echec'))
    assert etat['etat'] == 'echec' and banc.codes().count('passant_gene') == 3
    assert 'detour' not in banc.etats()


# ---------------------------------------------------------------- robot perdu

def test_perdu_puis_retrouve(dossier):
    banc = Banc(dossier, delai_perdu_s=15.0)
    banc.guide.aller('b204')
    banc.tourner(6.0, jusqu_a=())
    banc.perdu = 'repérage perdu'
    banc.tourner(PAS_S, jusqu_a=())
    etat = banc.guide.etat()
    assert etat['etat'] == 'perdu' and banc.codes()[-1] == 'perdu'
    assert banc.evenements[-1]['texte'] == ('Je me suis un peu perdu : un instant, s\'il vous '
                                            'plaît.')
    assert not banc.moteur.etat()['en_cours']
    position = banc.moteur.position
    banc.tourner(5.0, jusqu_a=())
    assert banc.moteur.position == position and banc.guide.etat()['etat'] == 'perdu'
    banc.perdu = None
    banc.tourner(PAS_S, jusqu_a=())
    assert banc.guide.etat()['etat'] == 'en_route' and banc.codes()[-1] == 'retrouve'
    assert banc.tourner(80.0)['etat'] == 'arrive'
    banc.conformes()


def test_perdu_trop_longtemps_echec_sans_retour(dossier):
    banc = Banc(dossier, delai_perdu_s=15.0, delai_avant_retour_s=1.0)
    banc.guide.aller('b204')
    banc.tourner(6.0, jusqu_a=())
    banc.perdu = 'repérage perdu'
    banc.tourner(PAS_S, jusqu_a=())
    t0 = banc.horloge.t
    etat = banc.tourner(20.0, jusqu_a=('echec',))
    assert etat['etat'] == 'echec' and banc.horloge.t - t0 == pytest.approx(15.0, abs=0.3)
    assert etat['message'] == ('Le robot est perdu depuis 15 s : replacez-le sur le point '
                               'principal « Accueil », puis cliquez sur « Repérer le robot ».')
    assert banc.codes()[-1] == 'echec'
    banc.perdu = None
    banc.tourner(10.0, jusqu_a=())
    assert banc.guide.etat()['etat'] == 'echec' and banc.guide.retour_prevu is None
    assert 'retour' not in banc.codes()


def test_plus_de_position_sur_la_carte(dossier):
    banc = Banc(dossier)
    banc.guide.aller('b204')
    banc.tourner(4.0, jusqu_a=())
    banc.sans_position = True
    banc.tourner(DELAI_TF_PERDU_S - 0.6, jusqu_a=())
    assert banc.guide.etat()['etat'] == 'en_route'
    banc.tourner(1.0, jusqu_a=('perdu',))
    assert banc.guide.etat()['etat'] == 'perdu'
    assert 'plus de position sur la carte' in banc.guide.etat()['message']
    banc.sans_position = False
    banc.tourner(PAS_S, jusqu_a=())
    assert banc.guide.etat()['etat'] == 'en_route'


def test_perdu_pendant_le_retour(dossier):
    banc = Banc(dossier, delai_perdu_s=5.0, delai_avant_retour_s=1.0)
    banc.guide.aller('amphi')
    banc.tourner(60.0)
    banc.tourner(2.0, jusqu_a=('retour',))
    banc.tourner(2.0, jusqu_a=())
    banc.perdu = 'repérage perdu'
    etat = banc.tourner(10.0, jusqu_a=('echec',))
    assert etat['etat'] == 'echec' and etat['mission'] == 'retour'
    banc.tourner(5.0, jusqu_a=())
    assert banc.guide.retour_prevu is None


# ---------------------------------------------------------------- verrou du pilotage

def test_pilotage_refuse_aller_et_arrete_la_mission(dossier):
    banc = Banc(dossier, delai_avant_retour_s=1.0)
    banc.pilote = 'pilotage'
    assert not banc.guide.aller('b204')
    etat = banc.guide.etat()
    assert etat['etat'] == 'echec' and 'piloté à la main' in etat['message']
    assert banc.codes() == ['pilotage'] and not banc.moteur.etat()['en_cours']
    banc.tourner(5.0, jusqu_a=())
    assert banc.moteur.position == PRINCIPAL and banc.guide.retour_prevu is None
    banc.guide.stop()                    # l'arrêt reste permis
    banc.pilote = 'guide'
    assert banc.guide.aller('b204')
    banc.tourner(5.0, jusqu_a=())
    banc.pilote = 'pilotage'             # le pilotage prend la main en route
    banc.tourner(PAS_S, jusqu_a=())
    assert banc.guide.etat()['etat'] == 'attente' and banc.codes()[-1] == 'pilotage'
    assert not banc.moteur.etat()['en_cours']
    # Retour prévu, puis pilotage : le retour est annulé
    banc.pilote = 'guide'
    banc.guide.aller('amphi')
    banc.tourner(60.0)
    banc.pilote = 'pilotage'
    banc.tourner(3.0, jusqu_a=())
    assert banc.guide.retour_prevu is None and banc.guide.etat()['etat'] == 'arrive'


# ---------------------------------------------------------------- format, réglages, personnes

def test_etat_et_evenements_conformes(dossier):
    banc = Banc(dossier, delai_avant_retour_s=1.0)
    banc.vues = visiteur_derriere(1.0)
    banc.guide.aller('b204', accompagner=True, source='dialogue')
    etat = banc.guide.etat()
    assert set(etat) >= {'version', 'etat', 'cible', 'reste_m', 'itineraire', 'mission',
                         'accompagner', 'visiteur', 'depuis_s'}
    banc.tourner(3.0, jusqu_a=())
    assert banc.guide.etat()['depuis_s'] == pytest.approx(3.0, abs=0.25)
    e = banc.evenements[0]
    assert e['salle'] == 'b204' and e['nom'] == 'Salle B204' and e['mission'] == 'visite'
    banc.tourner(80.0)
    banc.tourner(60.0, jusqu_a=('attente',))
    banc.conformes()
    assert all(e['version'] == 1 for e in banc.evenements)


def test_reglages_par_defaut():
    from g1_nav.guide import REGLAGES_DEFAUT
    assert {k: REGLAGES_DEFAUT[k] for k in DELAIS_GUIDE} == DELAIS_GUIDE
    assert REGLAGES_DEFAUT['accompagnement'] is True and REGLAGES_DEFAUT['passants'] is True


def test_suivi_visiteur_et_personne_devant():
    s = SuiviVisiteur()
    assert not s.choisir([personne(1, -3.0, 0.0)], 0.0, distance_max=2.5)
    assert s.choisir([personne(1, -2.0, 0.0), personne(2, -1.0, 0.5)], 0.0, robot=(0, 0, 0))
    assert s.id == 2
    assert s.observer([], 1.0) == {'vu': True, 'distance_m': 1.12, 'age_s': 1.0}
    assert s.observer(None, 2.5)['vu'] is False
    # Revenu sous un autre numéro, trop loin de sa dernière position pour être reconnu, mais proche
    # du robot pendant l'attente : repris
    assert s.reprendre([personne(5, -1.5, 0.0)], 3.0, robot=(0, 0, 0), distance_max=2.0)
    assert s.id == 5
    p = personne_devant([personne(1, 1.0, 1.0), personne(2, 1.2, 0.2), personne(3, -1, 0)],
                        distance_max=1.5)
    assert p.id == 2
    assert personne_devant([personne(2, 1.2, 0.2)], sauf=2) is None


def test_lire_personnes():
    from atelier.lieu.comportement import EXEMPLE_PERSONNES
    vues = lire_personnes(EXEMPLE_PERSONNES)
    assert len(vues) == 1 and vues[0].id == 3 and vues[0].derriere
    assert vues[0].sur_la_carte() == (1.4, 10.2)
    melange = {'personnes': [{'id': 'x', 'x': 1, 'y': 2}, {'id': 1, 'x': 1.0, 'y': 0.0}]}
    assert [p.id for p in lire_personnes(melange)] == [1]
    assert lire_personnes('rien') == [] and lire_personnes({'personnes': 3}) == []
    # Position sur la carte calculée depuis la pose du robot
    p = Personne(1, 1.0, 0.0)
    assert p.sur_la_carte((2.0, 3.0, math.pi / 2)) == pytest.approx((2.0, 4.0))


def test_seuil_orientation_dans_la_tolerance():
    from atelier.lieu.comportement import TOLERANCE_RETOUR_RAD
    from g1_nav.guide import POURCENTAGE_MIN, REGLAGES_NOEUD
    assert SEUIL_ORIENTATION_RAD < TOLERANCE_RETOUR_RAD
    # vague 5 : les réglages du nœud gardent les valeurs de la simulation par défaut
    assert REGLAGES_NOEUD['tolerance_orientation_rad'] == SEUIL_ORIENTATION_RAD
    assert REGLAGES_NOEUD['anticipation_rotation_rad'] == 0.0
    assert REGLAGES_NOEUD['pourcentage_min'] == POURCENTAGE_MIN


class MoteurQuiDepasse(MoteurTournant):
    """Moteur dont chaque rotation dépasse l'angle demandé (le vrai G1, à travers le pont)."""

    def __init__(self, *args, depassement=0.3, **kwargs):
        super().__init__(*args, **kwargs)
        self.depassement = depassement

    def tourner(self, angle):
        ok = super().tourner(angle)
        fin, demande = self._rotation
        self._rotation = (fin, demande + math.copysign(self.depassement, demande))
        return ok


def banc_qui_depasse(dossier, depassement, **reglages):
    banc = Banc(dossier, erreur_cap=0.6, delai_avant_retour_s=1.0, **reglages)
    m = banc.moteur
    banc.moteur = MoteurQuiDepasse(depart=PRINCIPAL, vitesse=0.5, horloge=banc.horloge,
                                   erreur_cap=0.6, depassement=depassement)
    banc.guide.moteur = banc.moteur
    assert m is not banc.moteur
    return banc


def test_rotation_qui_depasse_oscille_avec_la_tolerance_de_la_simulation(dossier):
    """Dépassement de 0,3 rad (rotation jamais sous 0,3 rad/s) et seuil de 0,09 : 3 essais."""
    banc = banc_qui_depasse(dossier, 0.3)
    banc.guide.aller('amphi')
    banc.tourner(60.0)
    banc.tourner(80.0, jusqu_a=('attente',))
    assert banc.guide.etat()['etat'] == 'attente'
    rotations = banc.moteur.rotations
    assert len(rotations) == 3 and rotations[0] < 0 < rotations[1]      # elle oscille


def test_tolerance_relevee_une_seule_rotation(dossier):
    """Avec le pont, tolérance de 0,4 rad : une rotation, puis attente (pas d'aller-retour)."""
    banc = banc_qui_depasse(dossier, 0.3, tolerance_orientation_rad=0.4)
    banc.guide.aller('amphi')
    banc.tourner(60.0)
    banc.tourner(80.0, jusqu_a=('attente',))
    assert banc.guide.etat()['etat'] == 'attente' and len(banc.moteur.rotations) == 1
    _, _, cap = banc.moteur.position
    assert abs(ecart_angle(cap, PRINCIPAL[2])) == pytest.approx(0.3, abs=1e-6)
    # arrivé déjà dans la tolérance : aucune rotation
    banc = banc_qui_depasse(dossier, 0.3, tolerance_orientation_rad=0.7)
    banc.guide.aller('amphi')
    banc.tourner(60.0)
    banc.tourner(80.0, jusqu_a=('attente',))
    assert banc.guide.etat()['etat'] == 'attente' and banc.moteur.rotations == []


def test_anticipation_de_la_rotation(dossier):
    """anticipation_rotation_rad = le dépassement mesuré : la rotation finit sur la flèche."""
    banc = banc_qui_depasse(dossier, 0.25, anticipation_rotation_rad=0.25)
    banc.guide.aller('amphi')
    banc.tourner(60.0)
    banc.tourner(80.0, jusqu_a=('attente',))
    (demande,) = banc.moteur.rotations
    assert demande == pytest.approx(-0.6 + 0.25)
    _, _, cap = banc.moteur.position
    assert abs(ecart_angle(cap, PRINCIPAL[2])) < 1e-6
    # jamais plus de la moitié de l'écart
    banc = banc_qui_depasse(dossier, 0.0, anticipation_rotation_rad=5.0)
    banc.guide.aller('amphi')
    banc.tourner(60.0)
    banc.tourner(80.0, jusqu_a=('attente',))
    assert banc.moteur.rotations[0] == pytest.approx(-0.3)


def test_ralenti_jamais_sous_la_vitesse_minimale_du_pont(dossier):
    """Avec le pont (pourcentage_min 50 : 0,2 m/s sur 0,4), ni le ralenti ni la personnalité."""
    distance = [1.0]
    banc = Banc(dossier, vitesse_max_nav2=0.4, pourcentage_min=50.0, ralenti=0.3)
    banc.vues = lambda g, m: [personne(7, -distance[0], 0.0)]
    banc.guide.aller('b204', accompagner=True)
    banc.tourner(6.0, jusqu_a=())
    distance[0] = 2.6
    banc.tourner(0.6, jusqu_a=())
    limites = [x for x in banc.limites if x is not None]       # None : limite levée
    assert limites and min(limites) >= 50.0
    banc.guide.fixer_vitesse_max(0.1, 'Lente')
    assert banc.guide._plafond_personnalite == 50.0


def test_ralenti_sur_la_vitesse_mesuree(dossier):
    """
    Ralenti : ralenti × la vitesse mesurée juste avant, en pourcentage de la vitesse maximale.

    Le Collision Monitor freine déjà le robot suivi de près par le visiteur.
    """
    banc = Banc(dossier, vitesse_max_nav2=1.0)      # le robot factice roule à 0,5 m/s
    distance = [1.0]
    banc.vues = lambda g, m: [personne(7, -distance[0], 0.0)]
    banc.guide.aller('b204', accompagner=True)
    banc.tourner(6.0, jusqu_a=())
    distance[0] = 2.6
    banc.tourner(0.6, jusqu_a=())
    assert banc.limites[-1] == pytest.approx(25.0, abs=1.0)     # 0,5 × 0,5 m/s sur 1 m/s
    # Vitesse maximale inconnue : ralenti × 100
    banc2 = Banc(dossier)
    banc2.vues = lambda g, m: [personne(7, -distance[0], 0.0)]
    distance[0] = 1.0
    banc2.guide.aller('b204', accompagner=True)
    banc2.tourner(6.0, jusqu_a=())
    distance[0] = 2.6
    banc2.tourner(0.6, jusqu_a=())
    assert banc2.limites[-1] == pytest.approx(50.0)


def test_passant_annonce_sans_repetition(dossier):
    """Le passant s'écarte puis revient bloquer le robot, trois fois : une annonce en 20 s."""
    banc = Banc(dossier)
    banc.guide.aller('b204')
    banc.tourner(4.0, jusqu_a=())
    for _ in range(3):
        banc.vues = passant_devant
        banc.moteur.bloquer(True)
        banc.tourner(DELAI_DEPART_S + DELAI_BLOQUE_S + 1.4, jusqu_a=('attente_passage',))
        assert banc.guide.etat()['etat'] == 'attente_passage'
        banc.vues = []
        banc.moteur.bloquer(False)
        banc.tourner(LIBRE_S, jusqu_a=('en_route',))
        assert banc.guide.etat()['etat'] == 'en_route'
    assert banc.codes().count('passant_gene') == 1 and banc.codes().count('passage_libre') <= 3
    assert banc.guide.attentes_passage == 3


def groupe_sur_la_carte(centre, guide, moteur):
    """Personnes vues depuis le robot : celles du groupe (sur la carte) à moins de 5 m."""
    x, y, cap = moteur.position
    vues = []
    for i, (gx, gy) in enumerate(centre):
        dx, dy = gx - x, gy - y
        if math.hypot(dx, dy) < 5.0:
            c, s = math.cos(-cap), math.sin(-cap)
            vues.append(personne(20 + i, c * dx - s * dy, s * dx + c * dy))
    return vues


def test_groupe_vu_dans_la_direction_du_couloir_robot_tourne(dossier):
    """
    Nav2 a fait pivoter le robot vers un autre chemin, à 2,4 m du groupe.

    C'est la direction du couloir qui compte : le robot s'arrête et attend, puis repart quand le
    groupe s'en va.
    """
    banc = Banc(dossier, delai_passant_s=20.0)
    banc.guide.aller('b204')
    groupe = [(15.5, 12.0), (15.5, 13.0), (15.5, 14.0)]
    banc.vues = lambda guide, moteur: groupe_sur_la_carte(groupe, guide, moteur)

    def devant_le_groupe(guide, moteur):
        x, y, _ = moteur.position
        return 12.9 < x < 14.0 and y > 12

    banc.tourner(60.0, obstacle=devant_le_groupe, jusqu_a=('attente_passage', 'bloque'))
    assert banc.guide.etat()['etat'] == 'attente_passage'
    x, y, _ = banc.moteur.position
    banc.moteur.position = (x, y, math.radians(150))       # Nav2 l'a fait pivoter vers l'ouest
    position = banc.moteur.position
    banc.tourner(10.0, jusqu_a=('detour', 'bloque', 'en_route'))
    assert banc.guide.etat()['etat'] == 'attente_passage' and banc.moteur.position == position
    groupe[:] = [(21.0, 15.2)]                              # le groupe part vers b204
    banc.moteur.bloquer(False)
    banc.tourner(LIBRE_S, jusqu_a=('en_route',))
    assert banc.guide.etat()['etat'] == 'en_route' and banc.codes()[-1] == 'passage_libre'
    assert banc.tourner(80.0)['etat'] == 'arrive' and banc.guide.detours == 0
    assert banc.etats() == ['en_route', 'attente_passage', 'en_route', 'arrive']
    banc.conformes()


def test_passant_qui_s_eloigne_libere_le_passage(dossier):
    """
    Robot arrêté devant un passant : dès qu'il s'éloigne, le passage est libre.

    Vitesse lue sur /personnes/lidar ; libre même s'il est encore à moins de 3 m.
    """
    banc = Banc(dossier)
    banc.guide.aller('b204')
    banc.tourner(4.0, jusqu_a=())
    banc.vues = passant_devant
    banc.moteur.bloquer(True)
    banc.tourner(DELAI_BLOQUE_S + 1.4, jusqu_a=('attente_passage',))
    assert banc.guide.etat()['etat'] == 'attente_passage'
    loin = {'id': 3, 'x': 1.6, 'y': 0.1, 'vx': 0.9, 'vy': 0.0}
    banc.vues = lire_personnes({'personnes': [loin]})
    banc.moteur.bloquer(False)
    banc.tourner(DELAI_PASSANT_PARTI_S + 0.6, jusqu_a=('en_route',))
    assert banc.guide.etat()['etat'] == 'en_route' and banc.codes()[-1] == 'passage_libre'
    # immobile à la même place : il bouche encore
    banc2 = Banc(dossier)
    banc2.guide.aller('b204')
    banc2.tourner(4.0, jusqu_a=())
    banc2.vues = passant_devant
    banc2.moteur.bloquer(True)
    banc2.tourner(DELAI_BLOQUE_S + 1.4, jusqu_a=('attente_passage',))
    reste = {'id': 3, 'x': 1.6, 'y': 0.1, 'vx': 0.05, 'vy': 0.0}
    banc2.vues = lire_personnes({'personnes': [reste]})
    banc2.tourner(5.0, jusqu_a=('en_route',))
    assert banc2.guide.etat()['etat'] == 'attente_passage'


def test_personne_devant_autour_d_un_cap():
    gens = [personne(1, -2.0, 0.0)]                         # derrière le robot, à 2 m
    assert personne_devant(gens, 2.5) is None
    assert personne_devant(gens, 2.5, cap=math.pi).id == 1
    assert personne_devant(gens, 2.5, cap=-math.pi + 0.1).id == 1
    assert personne_devant(gens, 1.5, cap=math.pi) is None


# ---------------------------------------------------------------- personnalité active

def test_vitesse_max_de_la_personnalite_plus_petite_limite(dossier):
    banc = Banc(dossier, vitesse_max_nav2=0.5, distance_ralentir_m=2.0, distance_attendre_m=3.5)
    banc.guide.fixer_vitesse_max(0.25, 'Discret')
    assert banc.limites[-1] == pytest.approx(50.0)
    banc.guide.aller('b204')
    assert banc.limites[-1] == pytest.approx(50.0)          # la nouvelle mission garde le plafond
    banc.guide._limiter(80.0)                       # le visiteur traîne : 80 %, plafond 50 %
    assert banc.limites[-1] == pytest.approx(50.0)
    banc.guide._limiter(30.0)
    assert banc.limites[-1] == pytest.approx(30.0)
    banc.guide._limiter(None)
    assert banc.limites[-1] == pytest.approx(50.0)
    banc.guide.fixer_vitesse_max(None, 'Accueillant')
    assert banc.limites[-1] is None                         # levée : 100 % pour Nav2
    banc.guide.fixer_vitesse_max(0.6, 'Rapide')             # au-delà de Nav2 : pas de plafond
    assert banc.limites[-1] is None


def test_vitesse_max_sans_vitesse_nav2_ignoree(dossier):
    banc = Banc(dossier)
    banc.guide.fixer_vitesse_max(0.25, 'Discret')
    assert all(v is None for v in banc.limites)
    assert any('vitesse_max_nav2 inconnue' in m for m in banc.messages)


def test_reglages_changeables_en_marche():
    from g1_nav.guide import REGLAGES_EN_MARCHE, refus_reglage_en_marche
    assert set(REGLAGES_EN_MARCHE) == {'tolerance_orientation_rad', 'anticipation_rotation_rad',
                                       'pourcentage_min'}
    assert refus_reglage_en_marche('tolerance_orientation_rad', 0.3) is None
    assert refus_reglage_en_marche('anticipation_rotation_rad', 0) is None
    for nom, valeur in (('tolerance_orientation_rad', -0.1), ('anticipation_rotation_rad', 2.0),
                        ('pourcentage_min', 101.0), ('pourcentage_min', math.nan),
                        ('tolerance_orientation_rad', True), ('tolerance_orientation_rad', 'a')):
        assert 'il faut un nombre' in refus_reglage_en_marche(nom, valeur), (nom, valeur)
    assert refus_reglage_en_marche('delai_perdu_s', -5.0) is None       # pas de ce ressort
