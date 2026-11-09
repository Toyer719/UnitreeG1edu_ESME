"""
Machine d'états de la démo d'accueil, sans ROS, à fausse horloge (section 13.4 du plan).

Un faux guide (FauxGuide) imite les états et les événements du guide de la vague 4 ; chaque
message publié par l'orchestrateur est vérifié par son schéma (atelier.lieu.valider_message).
"""
import math

from atelier.lieu import valider_message
from g1_accueil.logique import (DELAI_GUIDE_MUET_S, DELAI_RAISON_S, DUREE_SALUTATION_S,
                                marque_de_lancement, Orchestrateur)
import pytest

SALLES = [
    {'id': 'accueil', 'nom': 'Accueil', 'etage': 'rdc', 'etiquettes': ['principal'],
     'pose': {'x': 2.5, 'y': 10.0, 'theta': 0.0}},
    {'id': 'b204', 'nom': 'Salle B204', 'etage': 'rdc',
     'pose': {'x': 21.0, 'y': 13.0, 'theta': 1.57}},
    {'id': 'cdi', 'nom': 'CDI', 'etage': 'rdc', 'etiquettes': ['cdi'],
     'pose': {'x': 23.0, 'y': 7.0, 'theta': -1.57}},
    {'id': 'reserve', 'nom': 'Réserve', 'etage': 'rdc', 'etiquettes': ['hors_borne'],
     'pose': {'x': 5.0, 'y': 5.0, 'theta': 0.0}},
    {'id': 'labo', 'nom': 'Labo', 'etage': 'etage1', 'pose': {'x': 5.0, 'y': 5.0, 'theta': 0.0}},
]
PRINCIPAL = (2.5, 10.0, 0.0)
PERSO = {'id': 'accueillant', 'nom': 'Accueillant', 'salutation': 'Bonjour ! Je suis le robot.',
         'geste_salut': 26, 'phrases': {'arrivee': 'Et voilà : {nom}. Bonne journée !'}}
SCHEMAS = {'/accueil/etat': 'etat_demo', '/accueil/evenement': 'evenement_demo',
           '/guide/aller': 'demande_guide', '/robot/dire': 'robot_dire',
           '/robot/geste': 'robot_geste'}


class Horloge:
    """Fausse horloge des essais."""

    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


class FauxGuide:
    """Le guide de la vague 4, réduit à ses messages : états, mission, cible, actif, immobilise."""

    def __init__(self):
        self.etat = {'version': 1, 'etat': 'attente', 'cible': None, 'reste_m': None,
                     'itineraire': [], 'mission': None, 'actif': False}

    def changer(self, etat, mission='garder', cible='garder', actif=None, **plus):
        e = dict(self.etat, etat=etat, **plus)
        if mission != 'garder':
            e['mission'] = mission
        if cible != 'garder':
            e['cible'] = cible
        e['actif'] = (etat in ('en_route', 'retour', 'bloque', 'detour', 'attente_passage',
                               'attente_visiteur', 'perdu')) if actif is None else actif
        if 'immobilise' not in plus:
            e.pop('immobilise', None)
        self.etat = e
        return e


class Banc:
    """L'orchestrateur, le faux guide, la position du robot et tout ce qui a été publié."""

    def __init__(self, marque=None, **reglages):
        self.h = Horloge()
        self.guide = FauxGuide()
        self.pose = PRINCIPAL
        self.sorties = []
        reglages.setdefault('presence_s', 1.0)
        self.o = Orchestrateur(SALLES, 'accueil', 'rdc', reglages, horloge=self.h, lieu='demo',
                               personnalite=dict(PERSO), personnalites=[PERSO], marque=marque)
        self.non_conformes = []
        self.numero = 0

    def _garder(self, sorties):
        for sujet, d in sorties:
            schema = SCHEMAS.get(sujet)
            if schema and valider_message(schema, d):
                self.non_conformes.append((sujet, valider_message(schema, d), d))
            self.sorties.append((self.h.t, self.o.etat_courant, sujet, d))
        return sorties

    def entrer(self, sujet, d):
        return self._garder(self.o.entrer(sujet, d))

    def avancer(self, duree, pas=0.1, guide=True):
        """Le temps passe : le guide publie son état, le nœud la position, puis pas()."""
        fin = self.h.t + duree
        while self.h.t < fin - 1e-9:
            self.h.t = round(self.h.t + pas, 6)
            if guide:
                self.entrer('/guide/etat', dict(self.guide.etat))
            if self.pose is not None:
                self.entrer('position', self.pose)
            self._garder(self.o.pas())

    def demarrer(self):
        self.avancer(0.5)
        assert self.o.etat_courant == 'attente', self.o.etat()

    def publies(self, sujet, depuis=0.0):
        return [d for t, _, s, d in self.sorties if s == sujet and t >= depuis]

    def evenements(self, code=None, depuis=0.0):
        return [e for e in self.publies('/accueil/evenement', depuis)
                if code is None or e['code'] == code]

    def choisir(self, salle, ident='c1', source='borne'):
        self.entrer('/accueil/choix', {'version': 1, 'id': ident, 'salle': salle,
                                       'source': source})
        reponses = [e for e in self.publies('/accueil/evenement') if e.get('id') == ident]
        assert len(reponses) == 1, reponses
        return reponses[0]

    def commande(self, action, ident=None, source='atelier'):
        self.numero += 1
        ident = ident or f'k-{action}-{self.numero}'
        self.entrer('/accueil/commande', {'version': 1, 'id': ident, 'action': action,
                                          'source': source})
        reponses = [e for e in self.publies('/accueil/evenement') if e.get('id') == ident]
        assert len(reponses) == 1, reponses
        return reponses[0]

    def evenement_guide(self, code, **plus):
        message = {'version': 1, 'code': code, 'texte': code, 'temps': '2026-11-09T10:00:00+01:00'}
        return self.entrer('/guide/evenement', dict(message, **plus))

    def visite_jusqu_a_l_accompagnement(self, salle='b204'):
        self.demarrer()
        self.commande('appui', source='borne')
        assert self.o.etat_courant == 'salutation'
        self.avancer(DUREE_SALUTATION_S + 0.1)
        assert self.o.etat_courant == 'choix'
        r = self.choisir(salle)
        assert r['code'] == 'choix_accepte'
        assert self.o.etat_courant == 'depart'
        self.guide.changer('en_route', mission='visite', cible=salle, reste_m=18.0)
        self.avancer(0.2)
        assert self.o.etat_courant == 'accompagnement'
        self.pose = (6.0, 10.0, 0.0)
        return r

    def aucune_demande_en_pause(self):
        """Jamais de /guide/aller pendant une pause, sauf « ramener » (demande explicite)."""
        for demande, _, etat in self.o.demandes_guide:
            if etat == 'pause':
                assert demande['cible'] == 'principal', demande
                assert demande['id'].startswith('ramener-'), demande


def personnes(*liste, source='lidar'):
    return {'version': 1, 'source': source, 'temps': 10.0,
            'personnes': [dict({'id': i, 'x': d * math.cos(a), 'y': d * math.sin(a),
                                'distance_m': d, 'angle_rad': a, 'confiance': 0.9}, **plus)
                          for i, d, a, plus in liste]}


@pytest.fixture
def banc():
    b = Banc()
    yield b
    assert b.non_conformes == []
    b.aucune_demande_en_pause()


# ---------------------------------------------------------------- démarrage

def test_demarrage_puis_attente(banc):
    e = banc.o.etat()
    assert e['etat'] == 'demarrage' and valider_message('etat_demo', e) == []
    banc.avancer(0.3)
    assert banc.o.etat_courant == 'attente'
    assert banc.evenements('demarree')
    e = banc.o.etat()
    assert e['au_principal'] and e['texte_borne'] == 'Bonjour ! Où voulez-vous aller ?'
    assert e['actions_possibles'] == ['appui', 'pause', 'remise_a_zero']


def test_guide_absent_au_demarrage_et_en_attente(banc):
    banc.avancer(DELAI_GUIDE_MUET_S + 0.5, guide=False)
    assert banc.o.etat_courant == 'pause' and banc.o.raison == 'guide_absent'
    b = Banc()
    b.demarrer()
    b.avancer(DELAI_GUIDE_MUET_S + 0.3, guide=False)
    assert b.o.raison == 'guide_absent' and 'navigation' in b.o.etat()['message']
    b.avancer(1.0)        # le guide revient : rien ne repart seul, Reprendre devient possible
    assert b.o.etat_courant == 'pause' and b.o.etat()['reprise_possible']
    assert b.commande('reprendre')['code'] == 'commande_acceptee'
    assert b.o.etat_courant == 'attente'


def test_demarrage_loin_de_l_accueil_puis_ramener(banc):
    banc.pose = (10.0, 10.0, 0.0)
    banc.avancer(1.0)
    e = banc.o.etat()
    assert e['etat'] == 'demarrage' and 'ramener' in e['actions_possibles']
    assert 'Ramener' in e['message']
    assert banc.commande('ramener')['code'] == 'commande_acceptee'
    aller = banc.publies('/guide/aller')
    assert aller[-1]['cible'] == 'principal' and aller[-1]['accompagner'] is False
    assert aller[-1]['retour'] is False and aller[-1]['source'] == 'accueil'
    assert banc.o.etat_courant == 'retour'
    banc.guide.changer('en_route', mission='visite', cible='accueil')
    banc.avancer(2.0)
    assert banc.o.etat_courant == 'retour'
    banc.pose = PRINCIPAL
    banc.guide.changer('arrive', cible='accueil', actif=False)
    banc.avancer(0.3)
    assert banc.o.etat_courant == 'attente'


def test_guide_deja_en_route_au_lancement(banc):
    banc.guide.changer('en_route', mission='visite', cible='cdi')
    banc.avancer(0.3)
    assert banc.o.etat_courant == 'occupe'
    banc.guide.changer('retour', mission='retour', cible='accueil')
    banc.avancer(1.0)
    banc.guide.changer('attente', mission=None, cible=None)
    banc.avancer(0.3)
    assert banc.o.etat_courant == 'attente' and banc.evenements('libre')


# ---------------------------------------------------------------- visiteur, salutation, choix

def test_visiteur_vu_au_lidar_devant_le_robot(banc):
    banc.demarrer()
    # derrière (le faux visiteur de la scène accompagnement), trop loin, puis devant
    for _ in range(20):
        banc.entrer('/personnes/lidar', personnes((1, 1.0, math.pi, {}), (2, 2.4, 0.1, {})))
        banc.avancer(0.1)
    assert banc.o.etat_courant == 'attente'
    banc.entrer('/personnes/lidar', personnes((3, 1.2, 0.2, {})))
    banc.avancer(0.5)
    banc.entrer('/personnes/lidar', personnes((3, 1.2, 0.2, {})))
    assert banc.o.etat_courant == 'attente'            # pas encore présent depuis presence_s
    banc.avancer(0.6)
    banc.entrer('/personnes/lidar', personnes((3, 1.2, 0.2, {})))
    assert banc.o.etat_courant == 'salutation'
    dire = banc.publies('/robot/dire')
    assert dire[-1]['texte'] == PERSO['salutation'] and dire[-1]['source'] == 'accueil'
    assert dire[-1]['id'] == f'accueil-{banc.o.marque}-salut-1'
    assert banc.publies('/robot/geste')[-1]['geste'] == 26
    assert banc.evenements('visiteur') and banc.evenements('salutation')
    assert banc.o.etat()['visiteur'] == {'vu': True, 'source': 'lidar', 'distance_m': 1.2, 'id': 3}
    banc.avancer(DUREE_SALUTATION_S + 0.1)
    assert banc.o.etat_courant == 'choix'
    assert banc.o.etat()['statistiques']['visiteurs'] == 1


def test_camera_regarde_robot_et_source_auto(banc):
    banc.demarrer()
    tourne = personnes((5, 1.0, 0.0, {'regarde_robot': False}), source='camera')
    for _ in range(15):
        banc.entrer('/visiteurs/detectes', tourne)
        banc.entrer('/personnes/lidar', personnes((9, 1.0, 0.0, {})))    # la caméra l'emporte
        banc.avancer(0.1)
    assert banc.o.etat_courant == 'attente'
    face = personnes((5, 1.0, 0.0, {'regarde_robot': True}), source='camera')
    for _ in range(15):
        banc.entrer('/visiteurs/detectes', face)
        banc.avancer(0.1)
    assert banc.o.etat_courant in ('salutation', 'choix')
    assert banc.o.etat()['visiteur']['source'] == 'camera' or banc.o.etat_courant == 'choix'


def test_source_borne_seulement_les_appuis():
    b = Banc(source_visiteurs='borne')
    b.demarrer()
    for _ in range(20):
        b.entrer('/personnes/lidar', personnes((1, 1.0, 0.0, {})))
        b.avancer(0.1)
    assert b.o.etat_courant == 'attente'
    assert b.commande('appui', source='borne')['code'] == 'commande_acceptee'
    assert b.o.etat_courant == 'salutation'
    assert b.non_conformes == []


def test_delai_de_choix_et_annuler(banc):
    banc.demarrer()
    banc.commande('appui', source='borne')
    banc.avancer(DUREE_SALUTATION_S + 0.2)
    banc.avancer(30.0)
    banc.commande('appui', source='borne')         # le visiteur touche encore : le délai repart
    banc.avancer(30.0)
    assert banc.o.etat_courant == 'choix'
    banc.avancer(16.0)
    assert banc.o.etat_courant == 'attente' and banc.evenements('delai_choix')
    assert not banc.publies('/guide/aller')
    # le même visiteur, toujours là : pas resalué tant qu'il n'est pas parti
    for _ in range(100):
        banc.entrer('/personnes/lidar', personnes((4, 1.0, 0.0, {})))
        banc.avancer(0.1)
    assert banc.o.etat_courant == 'attente'
    banc.entrer('/personnes/lidar', personnes())
    for _ in range(20):
        banc.entrer('/personnes/lidar', personnes((5, 1.0, 0.0, {})))
        banc.avancer(0.1)
    assert banc.o.etat_courant in ('salutation', 'choix')
    banc.avancer(DUREE_SALUTATION_S)
    assert banc.commande('annuler', source='borne')['code'] == 'commande_acceptee'
    assert banc.o.etat_courant == 'attente'
    assert banc.commande('annuler', source='borne')['code'] == 'commande_refusee'


def test_choix_refuses(banc):
    banc.demarrer()
    attendus = {'nulle_part': 'salle_inconnue', 'reserve': 'salle_cachee', 'labo': 'autre_etage',
                'accueil': 'deja_la'}
    for i, (salle, raison) in enumerate(attendus.items()):
        r = banc.choisir(salle, ident=f'r{i}')
        assert r['code'] == 'choix_refuse' and r['raison'] == raison, r
    assert banc.o.etat_courant == 'attente' and not banc.publies('/guide/aller')


def test_choix_au_demarrage_refuse():
    b = Banc()
    r = b.choisir('b204', ident='tot')
    assert r['code'] == 'choix_refuse' and r['raison'] == 'occupe' and b.non_conformes == []


# ---------------------------------------------------------------- une visite complète

def test_visite_complete_et_statistiques(banc):
    r = banc.visite_jusqu_a_l_accompagnement('b204')
    assert r['visite'] == 'v3' or r['visite'].startswith('v')
    aller = banc.publies('/guide/aller')
    assert aller == [{'cible': 'b204', 'accompagner': True, 'retour': True, 'source': 'accueil',
                      'id': r['visite']}]
    dire = [d['texte'] for d in banc.publies('/robot/dire')]
    assert 'Je vous accompagne à Salle B204. Suivez-moi !' in dire
    # le départ du guide n'est pas redit (le relais le tait après « Je vous accompagne… »)
    banc.evenement_guide('depart', salle='b204', nom='Salle B204',
                         texte='Suivez-moi, je vous emmène à Salle B204.')
    assert not [d for d in banc.publies('/robot/dire') if d.get('code') == 'depart']
    e = banc.o.etat()
    assert e['etat'] == 'accompagnement' and e['visite']['salle'] == 'b204'
    assert e['visite']['reste_m'] == 18.0
    assert e['texte_borne'] == 'Suivez-moi !'
    banc.avancer(40.0)
    banc.pose = (21.0, 13.0, 1.57)
    banc.guide.changer('arrive', reste_m=0.0, actif=True)
    banc.avancer(0.2)
    assert banc.o.etat_courant == 'arrivee' and banc.evenements('arrivee')
    banc.evenement_guide('arrivee', salle='b204', nom='Salle B204',
                         texte='Voici le labo de physique.')
    assert banc.publies('/robot/dire')[-1]['texte'] == 'Voici le labo de physique.'
    banc.avancer(5.0)
    banc.guide.changer('retour', mission='retour', cible='accueil', reste_m=18.0)
    banc.avancer(0.2)
    assert banc.o.etat_courant == 'retour'
    banc.avancer(30.0)
    banc.pose = PRINCIPAL
    banc.guide.changer('attente', mission=None, cible=None, reste_m=None)
    banc.evenement_guide('retour_arrive', salle='accueil', nom='Accueil')
    banc.avancer(0.2)
    assert banc.o.etat_courant == 'attente' and banc.evenements('retour_arrive')
    s = banc.o.etat()['statistiques']
    vus = (s['visiteurs'], s['demandes'], s['visites_reussies'], s['echecs'], s['pauses'])
    assert vus == (1, 1, 1, 0, 0)
    assert s['duree_moyenne_s'] == pytest.approx(40.2, abs=0.5)
    # un visiteur devant le robot juste après le retour : pas avant delai_entre_visiteurs_s (8 s)
    for _ in range(50):
        banc.entrer('/personnes/lidar', personnes((7, 1.1, 0.0, {})))
        banc.avancer(0.1)
    assert banc.o.etat_courant == 'attente'
    for _ in range(40):
        banc.entrer('/personnes/lidar', personnes((7, 1.1, 0.0, {})))
        banc.avancer(0.1)
    assert banc.o.etat_courant in ('salutation', 'choix')
    assert banc.o.etat()['statistiques']['visiteurs'] == 2
    assert banc.commande('remise_a_zero')['code'] == 'commande_acceptee'
    assert banc.o.etat()['statistiques']['visiteurs'] == 0


def test_marque_de_lancement():
    assert marque_de_lancement(0) == '0' and marque_de_lancement(0.035) == 'z'
    assert marque_de_lancement(0.036) == '10' and len(marque_de_lancement()) == 8
    assert marque_de_lancement(1794254877.0) != marque_de_lancement(1794254877.001)


def test_deux_lancements_n_ont_jamais_les_memes_id_de_phrases():
    """
    Deux lancements de la démo n'ont jamais les mêmes id de phrases.

    Corrections de la vague 6 (revue du code, défaut 2) : relancée, la démo renumérotait
    ses phrases depuis 1 (accueil-salut-1, accueil-v2-depart…), la voix en faisait les
    mêmes sons, et la borne restée ouverte, qui ne joue qu'une fois chaque id, restait
    muette. Chaque lancement a sa marque dans l'id.
    """
    ids = []
    for marque in (marque_de_lancement(1794254877), marque_de_lancement(1794254878)):
        b = Banc(marque=marque)
        b.visite_jusqu_a_l_accompagnement('b204')
        b.commande('pause', source='operateur')
        ids.append([d['id'] for d in b.publies('/robot/dire')])
        assert all(i.startswith(f'accueil-{marque}-') for i in ids[-1]), ids[-1]
        assert len(ids[-1]) >= 3 and len(set(ids[-1])) == len(ids[-1]), ids[-1]
    assert not set(ids[0]) & set(ids[1]), ids
    # par défaut, la marque vient de l'heure du lancement
    assert len(Banc().o.marque) == 8


def test_choix_juste_apres_le_silence_du_guide_refuse(banc):
    """
    Un choix juste après 3 s de silence du guide est refusé.

    Corrections de la vague 6 (revue du code, défaut 5) : entre le passage aux 3 s de
    silence du guide et le pas suivant de la minuterie, un choix était accepté :
    /guide/aller et /guide/stop partaient dans le même lot (deux sujets sans ordre
    garanti). Les pauses sont évaluées avant le choix : refusé, et aucun /guide/aller.
    """
    banc.demarrer()
    banc.commande('appui', source='borne')
    banc.avancer(DUREE_SALUTATION_S + 0.1)
    assert banc.o.etat_courant == 'choix'
    dernier_guide = banc.h.t
    banc.h.t = round(dernier_guide + DELAI_GUIDE_MUET_S + 0.05, 6)      # aucun pas() entre-temps
    r = banc.choisir('b204')
    assert r['code'] == 'choix_refuse' and r['raison'] == 'pause', r
    assert banc.publies('/guide/aller') == [] and banc.o.etat_courant == 'pause'
    assert banc.o.raison == 'guide_absent'
    # une commande « appui » au même moment ne fait rien partir non plus
    assert banc.publies('/guide/aller') == []


def test_choix_du_chatbot_en_attente(banc):
    banc.demarrer()
    r = banc.choisir('cdi', ident='chat-1', source='dialogue')
    assert r['code'] == 'choix_accepte' and r['source'] == 'dialogue'
    assert banc.o.etat_courant == 'depart'
    # le chatbot répond lui-même au visiteur : la démo ne dit pas « Je vous accompagne… »
    assert not [d for d in banc.publies('/robot/dire') if d['source'] == 'accueil']


def test_borne_touchee_pendant_une_visite(banc):
    banc.visite_jusqu_a_l_accompagnement()
    r = banc.commande('appui', source='borne')
    assert r['code'] == 'commande_refusee' and r['raison'] == 'occupe'
    banc.commande('appui', source='borne')
    r = banc.choisir('cdi', ident='autre')
    assert r['code'] == 'choix_refuse' and r['raison'] == 'occupe'
    assert banc.o.etat()['statistiques']['refus_occupe'] == 3
    occupe = [d for d in banc.publies('/robot/dire') if 'occupé' in d['texte']]
    assert len(occupe) == 1                   # pas plus d'une fois toutes les 30 s
    assert banc.o.etat_courant == 'accompagnement'


def test_visiteur_perdu_puis_retour(banc):
    banc.visite_jusqu_a_l_accompagnement()
    banc.guide.changer('attente_visiteur')
    banc.avancer(10.0)
    banc.evenement_guide('visiteur_perdu', salle='b204')
    banc.guide.changer('echec', actif=True)            # abandon, retour prévu
    banc.avancer(0.2)
    assert banc.o.etat_courant == 'retour' and banc.evenements('visite_abandonnee')
    banc.avancer(5.0)
    banc.guide.changer('retour', mission='retour', cible='accueil')
    banc.avancer(3.0)
    assert banc.o.etat_courant == 'retour'
    banc.pose = PRINCIPAL
    banc.guide.changer('attente', mission=None, cible=None)
    banc.avancer(0.3)
    assert banc.o.etat_courant == 'attente'
    s = banc.o.etat()['statistiques']
    assert s['visites_abandonnees'] == 1 and s['visites_reussies'] == 0 and s['pauses'] == 0


def test_autre_demande_pendant_l_attente(banc):
    banc.demarrer()
    banc.guide.changer('en_route', mission='visite', cible='cdi')      # « Y aller » de l'Atelier
    banc.avancer(0.2)
    assert banc.o.etat_courant == 'occupe'
    assert banc.o.etat()['texte_borne'] == 'Je suis occupé. Je reviens dans un instant !'
    banc.guide.changer('arrive', actif=False)
    banc.pose = (23.0, 7.0, -1.57)
    banc.avancer(1.0)
    e = banc.o.etat()
    assert e['etat'] == 'occupe' and 'ramener' in e['actions_possibles']


# ---------------------------------------------------------------- pauses : rien ne repart seul

def _sans_mouvement_demande(b, depuis):
    return not [d for d in b.publies('/guide/aller', depuis) if not d['id'].startswith('ramener-')]


def test_arret_pendant_la_visite_puis_ramener(banc):
    banc.visite_jusqu_a_l_accompagnement()
    t = banc.h.t
    banc.entrer('/pont/arret', True)              # ARRÊT : verrou et /guide/stop presque ensemble
    assert banc.o.etat_courant == 'accompagnement'          # le guide va dire pourquoi
    banc.evenement_guide('arret')
    assert banc.o.etat_courant == 'pause' and banc.o.raison == 'arret'
    assert banc.publies('/guide/stop', t)
    pause = [d for d in banc.publies('/robot/dire', t) if d['priorite'] == 'securite']
    assert len(pause) == 1 and pause[0]['texte'] == 'Je fais une petite pause.'
    banc.guide.changer('attente', mission=None, cible=None, immobilise='verrou')
    banc.avancer(2.0)
    e = banc.o.etat()
    assert not e['reprise_possible'] and 'Débloquer' in e['message']
    r = banc.choisir('cdi', ident='pendant')
    assert r['code'] == 'choix_refuse' and r['raison'] == 'pause'
    r = banc.commande('ramener')
    assert r['code'] == 'commande_refusee' and 'Débloquer' in r['texte']
    # « Débloquer » : rien ne repart, la démo reste en pause
    banc.entrer('/pont/arret', False)
    banc.guide.changer('attente')
    banc.avancer(15.0)
    assert banc.o.etat_courant == 'pause' and _sans_mouvement_demande(banc, t)
    r = banc.commande('reprendre')
    assert r['code'] == 'commande_refusee' and 'Ramenez' in r['texte']
    assert 'ramener' in banc.o.etat()['actions_possibles']
    assert banc.commande('ramener')['code'] == 'commande_acceptee'
    assert banc.o.etat_courant == 'retour'
    banc.guide.changer('en_route', mission='visite', cible='accueil')
    banc.avancer(5.0)
    banc.pose = PRINCIPAL
    banc.guide.changer('arrive', actif=False)
    banc.avancer(0.3)
    assert banc.o.etat_courant == 'attente'
    assert banc.o.etat()['statistiques']['pauses'] == 1


def test_bloquer_pendant_la_visite(banc):
    banc.visite_jusqu_a_l_accompagnement()
    banc.entrer('/pont/arret', True)
    banc.evenement_guide('immobilise', raison='verrou')
    assert banc.o.raison == 'verrou'


def test_verrou_sans_evenement_du_guide(banc):
    banc.visite_jusqu_a_l_accompagnement()
    banc.entrer('/pont/etat', {'version': 1, 'etat': 'arret_verrouille', 'verrou': True})
    banc.avancer(DELAI_RAISON_S / 2)
    assert banc.o.etat_courant == 'accompagnement'
    banc.avancer(DELAI_RAISON_S)
    assert banc.o.raison == 'verrou'


def test_pas_en_marche_et_reprise(banc):
    banc.demarrer()
    banc.entrer('/pont/etat', {'version': 1, 'etat': 'pas_en_marche'})
    assert banc.o.raison == 'pas_en_marche'                 # en attente : tout de suite
    banc.avancer(2.0)
    banc.entrer('/pont/etat', {'version': 1, 'etat': 'pas_en_marche'})
    r = banc.commande('reprendre')
    assert r['code'] == 'commande_refusee' and 'mode marche' in r['texte']
    for _ in range(10):
        banc.entrer('/pont/etat', {'version': 1, 'etat': 'pret'})
        banc.avancer(0.1)
    assert banc.o.etat_courant == 'pause' and banc.o.etat()['reprise_possible']
    assert banc.commande('reprendre')['code'] == 'commande_acceptee'
    assert banc.o.etat_courant == 'attente' and banc.evenements('reprise')


def test_pont_absent(banc):
    banc.visite_jusqu_a_l_accompagnement()
    for _ in range(5):
        banc.entrer('/pont/etat', {'version': 1, 'etat': 'en_mouvement'})
        banc.avancer(0.2)
    t = banc.h.t
    banc.avancer(3.2)
    assert banc.o.raison == 'pont_absent'
    assert [r for r, tt in banc.o.pauses_vues if tt >= t] == ['pont_absent']


def test_pilotage_et_operateur(banc):
    banc.demarrer()
    banc.entrer('/mouvement/maitre', {'version': 1, 'maitre': 'pilotage', 'par': 'atelier',
                                      'depuis': 'x', 'message': 'm'})
    assert banc.o.raison == 'pilotage'
    assert banc.commande('reprendre')['code'] == 'commande_refusee'
    banc.entrer('/mouvement/maitre', {'version': 1, 'maitre': 'guide', 'par': 'atelier',
                                      'depuis': 'x', 'message': 'm'})
    banc.avancer(1.0)
    assert banc.commande('reprendre')['code'] == 'commande_acceptee'
    # pause de l'opérateur pendant une visite : /guide/stop
    b = Banc()
    b.visite_jusqu_a_l_accompagnement()
    t = b.h.t
    r = b.commande('pause', source='operateur')
    assert r['code'] == 'commande_acceptee' and b.o.raison == 'operateur'
    assert b.publies('/guide/stop', t)
    assert b.commande('pause', source='operateur')['code'] == 'commande_refusee'
    b.aucune_demande_en_pause()


def test_echec_et_robot_perdu(banc):
    banc.visite_jusqu_a_l_accompagnement()
    banc.guide.changer('echec', actif=True)
    banc.evenement_guide('echec')
    assert banc.o.raison == 'echec' and banc.evenements('visite_echouee')
    assert banc.o.etat()['statistiques']['echecs'] == 1
    b = Banc()
    b.visite_jusqu_a_l_accompagnement()
    b.guide.changer('perdu')
    b.avancer(15.0)
    b.guide.changer('echec', actif=False)
    b.evenement_guide('echec')
    assert b.o.raison == 'perdu' and b.non_conformes == []


def test_le_guide_ne_part_pas(banc):
    banc.demarrer()
    banc.commande('appui', source='borne')
    banc.avancer(DUREE_SALUTATION_S + 0.1)
    banc.choisir('b204')
    t = banc.h.t
    banc.avancer(9.5)
    assert banc.o.etat_courant == 'depart'
    banc.avancer(1.0)
    assert banc.o.raison == 'echec' and banc.publies('/guide/stop', t)


def test_guide_refuse_le_depart(banc):
    banc.demarrer()
    banc.entrer('/pont/etat', {'version': 1, 'etat': 'pret'})
    banc.commande('appui', source='borne')
    banc.choisir('b204')
    banc.evenement_guide('pilotage')
    banc.guide.changer('echec', mission='visite', cible='b204', actif=False)
    assert banc.o.raison == 'pilotage'


def test_arret_pendant_le_retour_puis_arrivee_seule(banc):
    banc.visite_jusqu_a_l_accompagnement()
    banc.pose = (21.0, 13.0, 1.57)
    banc.guide.changer('arrive', actif=True)
    banc.avancer(0.2)
    banc.guide.changer('retour', mission='retour', cible='accueil')
    banc.avancer(1.0)
    assert banc.o.etat_courant == 'retour'
    banc.evenement_guide('arret')
    banc.guide.changer('attente', mission=None, cible=None)
    assert banc.o.raison == 'arret'
    banc.avancer(20.0)
    assert banc.o.etat_courant == 'pause' and not banc.o.etat()['reprise_possible']


def test_guide_au_repos_sans_raison_pendant_la_visite(banc):
    banc.visite_jusqu_a_l_accompagnement()
    banc.guide.changer('attente', mission=None, cible=None)
    banc.avancer(1.5)
    assert banc.o.raison == 'arret'


def test_chaque_choix_et_commande_a_sa_reponse(banc):
    banc.demarrer()
    actions = ('appui', 'annuler', 'pause', 'reprendre', 'ramener', 'remise_a_zero', 'appui',
               'pause', 'pause')
    for i, action in enumerate(actions):
        r = banc.commande(action, ident=f'id-{i}')
        assert r['code'] in ('commande_acceptee', 'commande_refusee') and r['action'] == action
    banc.entrer('/accueil/commande', {'version': 1, 'id': 'z', 'action': 'danser',
                                      'source': 'test'})
    assert banc.evenements('commande_refusee')[-1]['id'] == 'z'


def test_personnalite_active_completee_par_le_fichier(banc):
    autre = {'id': 'discret', 'nom': 'Discret', 'salutation': 'Bonjour.', 'geste_salut': 11}
    banc.o.personnalites['discret'] = autre
    banc.entrer('/personnalite/active', {'version': 1, 'id': 'discret', 'nom': 'Discret'})
    assert banc.o.personnalite['salutation'] == 'Bonjour.'
    b = Banc()
    b.o.suivre_personnalite = False
    b.entrer('/personnalite/active', {'version': 1, 'id': 'discret', 'nom': 'Discret'})
    assert b.o.personnalite['id'] == 'accueillant'


def test_simulation_sans_pont():
    b = Banc(suivre_pont=False)
    b.demarrer()
    b.entrer('/pont/arret', True)       # un verrou resté posé par une répétition : ignoré
    b.avancer(1.0)
    assert b.o.etat_courant == 'attente' and b.non_conformes == []
