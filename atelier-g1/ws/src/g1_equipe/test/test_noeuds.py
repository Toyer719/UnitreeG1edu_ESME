"""
Les nœuds de g1_equipe en vrai (ROS 2, sans Gazebo).

Le test joue le guide, la reconnaissance vocale, la caméra et le pilotage (outils_equipe.Temoin).

dialogue : l'exemple du plan (« je cherche la salle b204 » → /robot/dire et /guide/aller en
JSON), une salutation, le repli ; personnalité annoncée au démarrage puis changée par une règle ;
relais des événements du guide (phrases de la personnalité, « depart » tu après le chatbot,
priorité de l'arrêt) ; verrou du pilotage et visite en cours (pas de /guide/aller), stop
toujours envoyé ; fichiers relus quand ils changent ; refus au démarrage. fausse_camera : modes
fixe, aucune et piétons. voix_journal : phrases écrites, et dites par une commande. Chaque
message reçu est validé par son schéma. Environ 30 s.
"""
import os
import sys
import time

import atelier
from atelier.lieu import copier_lieu
from atelier.lieu import equipe as E
from outils_equipe import NoeudLance, Temoin
import pytest

DEMO = atelier.RACINE / 'lieux' / 'demo'
DEMARRAGE_S = 8.0
PILOTAGE = {'version': 1, 'maitre': 'pilotage', 'par': 'atelier',
            'depuis': '2026-10-26T10:00:00+01:00', 'message': 'Robot piloté depuis l\'Atelier.'}


@pytest.fixture
def temoin():
    t = Temoin()
    yield t
    t.fermer()
    assert t.erreurs_schema == [], t.erreurs_schema[:3]


@pytest.fixture
def lancer():
    """Fabrique qui démarre un exécutable du paquet ; tous ceux du test sont arrêtés à la fin."""
    lances = []

    def _lancer(nom, *arguments):
        n = NoeudLance(nom, arguments).demarrer()
        lances.append(n)
        return n
    yield _lancer
    for n in lances:
        n.arreter()


@pytest.fixture
def lieu(tmp_path):
    return copier_lieu(DEMO, tmp_path / 'demo')


def dialogue_pret(temoin, lancer, lieu, *autres):
    """Lance le nœud dialogue sur le lieu et attend qu'il écoute /visiteur/texte."""
    n = lancer('dialogue', '-p', f'lieu:={lieu}', *autres)
    temoin.attendre(lambda: temoin.abonnes('/visiteur/texte') > 0, DEMARRAGE_S,
                    'le nœud dialogue n\'écoute pas /visiteur/texte\n' + n.texte())
    time.sleep(0.3)
    return n


def evenement(code, texte, **autres):
    return dict({'version': 1, 'code': code, 'texte': texte}, **autres)


def du_guide(temoin, depuis, code=None):
    """Phrases du relais (source guide) reçues depuis l'instant donné."""
    return [m for m in temoin.messages('/robot/dire', depuis)
            if m['source'] == 'guide' and (code is None or m.get('code') == code)]


def dernieres_personnes(temoin):
    return (temoin.messages('/visiteurs/detectes') or [{}])[-1].get('personnes')


def test_exemple_du_plan(temoin, lancer, lieu):
    n = dialogue_pret(temoin, lancer, lieu, '-p', 'etage:=rdc')
    assert 'règles d\'exemple' in n.texte()
    t0, r = temoin.dire('je cherche la salle b204')
    assert r['texte'] == 'Je vous emmène à Salle B204. Suivez-moi !' and r['langue'] == 'fr'
    aller = temoin.attendre(lambda: temoin.messages('/guide/aller', t0), 3.0,
                            'pas de /guide/aller')
    assert aller == [{'cible': 'b204', 'accompagner': True, 'source': 'dialogue'}]
    t1, r = temoin.dire('Bonjour !')
    assert r['texte'] == 'Bonjour ! Où voulez-vous aller ?'
    _, r = temoin.dire('quelle heure est-il ?')
    assert r['texte'] == E.exemple_equipe('dialogues')['repli']
    time.sleep(1.0)
    assert temoin.messages('/guide/aller', t1) == []      # ni « bonjour » ni le repli ne guident
    assert '« je cherche la salle b204 » → chercher_salle (guider b204)' in n.texte()


def test_personnalites(temoin, lancer, lieu):
    E.enregistrer_equipe(lieu, 'personnalites', E.exemple_equipe('personnalites'))
    t0 = time.monotonic()
    dialogue_pret(temoin, lancer, lieu)
    # personne ne l'a annoncée : le nœud annonce celle du fichier, 2 s après son démarrage
    m = temoin.attendre(lambda: temoin.messages('/personnalite/active', t0), 6.0, 'pas d\'annonce')
    assert m[-1]['id'] == 'accueillant' and m[-1]['lieu'] == 'demo' and m[-1]['temps']
    # « depart » qui ne suit pas le chatbot se dit, avec la phrase de la personnalité
    t1 = time.monotonic()
    texte = 'Suivez-moi, je vous emmène à Salle B204.'
    temoin.publier('/guide/evenement', evenement('depart', texte, salle='b204', nom='Salle B204'))
    d = temoin.attendre(lambda: du_guide(temoin, t1), 3.0, 'événement non relayé')
    assert d[0]['texte'] == 'Avec plaisir ! Suivez-moi jusqu\'à Salle B204.'
    assert (d[0]['code'], d[0]['personnalite']) == ('depart', 'accueillant')
    # une règle change de personnalité : elle est annoncée, et ses réglages servent
    t2, r = temoin.dire('mode discret')
    assert r['texte'] == 'D\'accord, je me fais discret.'
    m = temoin.attendre(lambda: [x for x in temoin.messages('/personnalite/active', t2)
                                 if x['id'] == 'discret'], 3.0, 'personnalité non annoncée')
    assert m[0]['vitesse_max'] == 0.25 and m[0]['voix']['volume'] == 50
    _, r = temoin.dire('bonjour')
    assert r['personnalite'] == 'discret' and r['voix']['volume'] == 50
    # l'onglet de l'Atelier en annonce une autre : le nœud la suit (le reste vient du fichier)
    t3 = time.monotonic()
    temoin.publier('/personnalite/active',
                   {'version': 1, 'id': 'accueillant', 'nom': 'Accueillant'})
    time.sleep(0.5)
    temoin.publier('/guide/evenement', evenement('arrivee', 'Nous sommes arrivés : voici Salle X.',
                                                 salle='x', nom='Salle X'))
    d = temoin.attendre(lambda: du_guide(temoin, t3, 'arrivee'), 3.0, 'arrivée non relayée')
    assert d[0]['texte'] == 'Et voilà : Salle X. Bonne journée !'


def test_relais_des_evenements(temoin, lancer, lieu):
    dialogue_pret(temoin, lancer, lieu)
    # le chatbot vient d'annoncer le départ : le « depart » du guide est tu, pas « seul »
    t0, _ = temoin.dire('je cherche la b204')
    temoin.publier('/guide/evenement', evenement('depart', 'Départ.', salle='b204'))
    temoin.publier('/guide/evenement', evenement('seul', 'Seul.', salle='b204'))
    temoin.publier('/guide/evenement', evenement('arret', 'Je m\'arrête.'))
    temoin.attendre(lambda: len(du_guide(temoin, t0)) >= 2, 3.0, 'événements non relayés')
    time.sleep(0.5)
    assert [(m['code'], m['texte'], m['priorite']) for m in du_guide(temoin, t0)] == [
        ('seul', 'Seul.', 'normale'), ('arret', 'Je m\'arrête.', 'haute')]
    # un message illisible ne fait pas tomber le nœud
    temoin.publier('/guide/evenement', 'pas du json')
    temoin.dire('bonjour')


def test_relais_coupe(temoin, lancer, lieu):
    dialogue_pret(temoin, lancer, lieu, '-p', 'relayer_evenements:=false')
    t0 = time.monotonic()
    temoin.publier('/guide/evenement', evenement('arret', 'Je m\'arrête.'))
    time.sleep(1.0)
    assert temoin.messages('/robot/dire', t0) == []


def test_chatbot_coupe(temoin, lancer, lieu):
    dialogue_pret(temoin, lancer, lieu, '-p', 'repondre:=false')
    t0 = time.monotonic()
    temoin.publier('/visiteur/texte', 'je cherche la salle b204')
    temoin.publier('/guide/evenement', evenement('arret', 'Je m\'arrête.'))
    temoin.attendre(lambda: du_guide(temoin, t0), 3.0, 'le relais doit rester')
    time.sleep(1.0)
    assert temoin.messages('/guide/aller', t0) == []
    assert [m['source'] for m in temoin.messages('/robot/dire', t0)] == ['guide']


def test_verrou_du_pilotage_et_visite_en_cours(temoin, lancer, lieu):
    n = dialogue_pret(temoin, lancer, lieu)
    temoin.publier('/mouvement/maitre', PILOTAGE)
    time.sleep(0.5)
    t0, r = temoin.dire('je cherche la b204')
    assert r['texte'] == 'Je suis piloté à la main pour le moment.'
    # stop passe toujours
    t1, r = temoin.dire('stop')
    assert r['texte'] == 'Je m\'arrête.' and r['priorite'] == 'haute'
    temoin.attendre(lambda: temoin.messages('/guide/stop', t1), 3.0, 'pas de /guide/stop')
    # le guide reprend la main, mais une visite est en cours
    temoin.publier('/mouvement/maitre', dict(PILOTAGE, maitre='guide'))
    temoin.publier('/guide/etat', {'version': 1, 'etat': 'en_route', 'cible': 'cdi',
                                   'mission': 'visite'})
    time.sleep(0.5)
    _, r = temoin.dire('je cherche la b204')
    assert r['texte'] == 'Je guide déjà quelqu\'un vers CDI : je reviens dès que possible.'
    # pendant un retour au point principal, la demande part
    temoin.publier('/guide/etat', {'version': 1, 'etat': 'retour', 'cible': 'accueil',
                                   'mission': 'retour'})
    time.sleep(0.5)
    t2, _ = temoin.dire('je cherche la b204')
    temoin.attendre(lambda: temoin.messages('/guide/aller', t2), 3.0, 'pas de /guide/aller')
    time.sleep(0.3)
    assert len(temoin.messages('/guide/aller', t0)) == 1
    assert 'pas envoyé : pilotage' in n.texte() and 'pas envoyé : visite_en_cours' in n.texte()


def test_fichiers_relus(temoin, lancer, lieu):
    n = dialogue_pret(temoin, lancer, lieu, '-p', 'relire_s:=0.5')
    d = E.exemple_equipe('dialogues')
    d['regles'][1]['reponse'] = 'Bonjour, version 2 !'
    E.enregistrer_equipe(lieu, 'dialogues', d)
    assert n.attendre_texte('5 règles', 2.0)
    temoin.attendre(lambda: temoin.dire('bonjour')[1]['texte'] == 'Bonjour, version 2 !', 6.0,
                    'dialogues.yaml non relu')
    # un fichier faux : le nœud le dit et garde les règles d'avant
    (lieu / 'dialogues.yaml').write_text('version: 1\nregles: [\n', encoding='utf-8')
    assert n.attendre_texte('je garde les précédents', 3.0), n.texte()
    assert temoin.dire('bonjour')[1]['texte'] == 'Bonjour, version 2 !'


def test_salutation(temoin, lancer, lieu):
    E.enregistrer_equipe(lieu, 'personnalites', E.exemple_equipe('personnalites'))
    dialogue_pret(temoin, lancer, lieu)
    temoin.publier('/guide/etat', {'version': 1, 'etat': 'attente', 'cible': None})
    t0 = time.monotonic()
    vus = {'version': 1, 'source': 'camera', 'temps': 1.0, 'personnes': [
        {'id': 4, 'x': 1.0, 'y': 0.1, 'distance_m': 1.005, 'angle_rad': 0.1, 'confiance': 0.9,
         'regarde_robot': True}]}
    fin = time.monotonic() + 2.5
    while time.monotonic() < fin:
        temoin.publier('/visiteurs/detectes', dict(vus, temps=time.monotonic()))
        time.sleep(0.1)
    salut = [m['texte'] for m in temoin.messages('/robot/dire', t0)
             if m['source'] == 'personnalite']
    assert salut == [E.exemple_equipe('personnalites')['personnalites'][0]['salutation']]


@pytest.mark.parametrize('arguments, attendu', [
    ((), 'donnez le lieu'),
    (('-p', 'lieu:=/tmp/lieu_qui_n_existe_pas_g1_equipe'), None),
])
def test_refus_au_demarrage(lancer, arguments, attendu):
    n = lancer('dialogue', *arguments)
    if attendu:
        assert n.attendre(15.0) == 2 and attendu in n.texte()
        return
    # un lieu sans fichiers : règles d'exemple, aucune salle (il démarre)
    assert n.attendre_texte('0 salles', DEMARRAGE_S), n.texte()


def test_dialogues_faux_au_demarrage(lancer, lieu):
    (lieu / 'dialogues.yaml').write_text('version: 1\n', encoding='utf-8')
    n = lancer('dialogue', '-p', f'lieu:={lieu}')
    assert n.attendre(15.0) == 2 and 'dialogues.yaml' in n.texte()


# ---------------------------------------------------------------- fausse caméra

def test_fausse_camera(temoin, lancer, lieu):
    E.enregistrer_equipe(lieu, 'camera', E.exemple_equipe('camera'))
    lancer('fausse_camera', '-p', f'lieu:={lieu}', '-p', 'x:=2.0', '-p', 'y:=0.5')
    m = temoin.attendre(lambda: temoin.messages('/visiteurs/detectes'), DEMARRAGE_S,
                        'rien sur /visiteurs/detectes')
    p = m[-1]['personnes'][0]
    assert m[-1]['source'] == 'camera' and (p['x'], p['y'], p['regarde_robot']) == (2.0, 0.5, True)
    t0 = time.monotonic()
    time.sleep(1.0)
    assert 7 <= len(temoin.messages('/visiteurs/detectes', t0)) <= 13      # 10 Hz (camera.yaml)
    temoin.attendre(lambda: temoin.abonnes('/fausse_camera/mode') > 0, 3.0)
    temoin.publier('/fausse_camera/mode', 'aucune')
    temoin.attendre(lambda: dernieres_personnes(temoin) == [], 3.0, 'mode aucune')
    # piétons de Gazebo vus par la caméra (robot en (2,5 ; 10), regard vers l'est, champ de 90°)
    temoin.publier('/fausse_camera/mode', 'pietons')
    pietons = {'version': 1, 'temps': 1.0, 'pietons': [
        {'id': 'devant', 'x': 4.5, 'y': 10.2, 'vx': -1.0, 'vy': 0.0, 'theta': 3.14,
         'etat': 'marche'},
        {'id': 'derriere', 'x': 0.5, 'y': 10.0, 'vx': 0.0, 'vy': 0.0, 'theta': 0.0,
         'etat': 'pause'}]}

    def vus():
        temoin.publier('/pietons/etat', dict(pietons, temps=time.monotonic()))
        temoin.publier_odom(2.5, 10.0)
        return [p.get('pieton') for p in dernieres_personnes(temoin) or []] == ['devant']
    temoin.attendre(vus, 4.0, 'piétons non vus')
    temoin.publier('/fausse_camera/mode', 'fixe 1.0 -0.2')
    temoin.attendre(lambda: [(p['x'], p['y']) for p in dernieres_personnes(temoin) or []]
                    == [(1.0, -0.2)], 3.0, 'mode fixe avec position')


# ---------------------------------------------------------------- voix du journal

def test_voix_journal(temoin, lancer, tmp_path):
    dites = tmp_path / 'dites.txt'
    fausse = tmp_path / 'fausse_voix'
    fausse.write_text(f'#!{sys.executable}\nimport sys, time\ntime.sleep(0.2)\n'
                      f'open({str(dites)!r}, "a").write(" ".join(sys.argv[1:]) + "\\n")\n')
    fausse.chmod(0o755)
    fichier = tmp_path / 'voix.log'
    n = lancer('voix_journal', '-p', f'commande:={fausse}', '-p', f'fichier:={fichier}')
    temoin.attendre(lambda: 'voix du journal' in n.texte(), DEMARRAGE_S, n.texte())
    time.sleep(0.5)
    perso = E.exemple_equipe('personnalites')['personnalites'][1]
    temoin.publier('/robot/dire', E.message_robot_dire('Première phrase.', 'dialogue',
                                                       personnalite=perso))
    temoin.publier('/robot/dire', E.message_robot_dire('Deuxième phrase.', 'guide', code='depart'))
    temoin.publier('/robot/dire', {'texte': ''})                    # hors du schéma : pas dite
    temoin.attendre(lambda: dites.exists() and len(dites.read_text().splitlines()) == 2, 6.0,
                    'phrases non dites')
    assert dites.read_text().splitlines() == ['--vitesse 0.9 Première phrase.',
                                              '--vitesse 1 Deuxième phrase.']
    assert fichier.read_text(encoding='utf-8').splitlines() == [
        '[discret] Première phrase. (dialogue)', '[—] Deuxième phrase. (guide, depart)']
    assert 'hors du schéma robot_dire' in n.texte()
    assert os.access(fausse, os.X_OK)
