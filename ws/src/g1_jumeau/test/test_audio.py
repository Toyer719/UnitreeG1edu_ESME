"""
Le service voice du faux G1 (vague 6, section 13.6 du plan) : g1_jumeau/audio.py, sans ROS.

Requêtes vérifiées comme le contrat du nœud voix (atelier.lieu.voix.erreurs_requete_voix : 3204 et
un écart compté), flux suivis (morceaux, octets, durée, ce qui joue), 1004 qui coupe, flux mêlés,
morceaux trop rapides et trous, comportement d'avant (TTS, volume, LED) gardé.
"""
import json
from pathlib import Path
import sys

import pytest

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI.parent))
for parent in ICI.parents:
    if (parent / 'atelier' / 'lieu' / 'voix.py').is_file():
        sys.path.insert(0, str(parent))
        break

from g1_jumeau.audio import erreurs_simples, FausseVoix, TAILLE_MORCEAU_MAX  # noqa: E402
from g1_jumeau.robot import FauxG1  # noqa: E402
from g1_jumeau.logique import FauxSport  # noqa: E402

LECTURE = json.dumps({'app_name': 'atelier', 'stream_id': 's-1'})
ARRET = json.dumps({'app_name': 'atelier'})


def lecture(flux, app='atelier'):
    return json.dumps({'app_name': app, 'stream_id': flux})


def pcm(secondes):
    return b'\x01\x00' * int(16000 * secondes)


class Horloge:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


@pytest.fixture
def h():
    return Horloge()


@pytest.fixture
def voix(h):
    return FausseVoix(horloge=h)


def test_le_contrat_est_trouve(voix):
    assert voix.contrat is not None
    assert voix.contrat.APIS_NOEUD_VOIX == (1001, 1003, 1004, 1005, 1006)


def test_une_phrase_en_trois_morceaux(voix, h):
    morceaux = [pcm(3.0), pcm(3.0), pcm(1.5)]
    for i, m in enumerate(morceaux):
        assert voix.traiter(1003, lecture('s-1'), m) == (0, '')
        assert voix.en_cours(h.t) == 's-1'
        if i < 2:
            h.t += 1.0
    e = voix.etat()
    assert e['morceaux_recus'] == 3 and e['octets_recus'] == sum(len(m) for m in morceaux)
    assert len(e['flux']) == 1 and e['ecarts'] == 0 and e['trop_rapides'] == 0 and e['trous'] == 0
    f = e['flux'][0]
    assert f['stream_id'] == 's-1' and f['morceaux'] == 3 and f['duree_s'] == pytest.approx(7.5)
    assert f['tailles'] == [96000, 96000, 48000] and f['fin_lecture'] == pytest.approx(107.5)
    h.t = 107.4
    assert voix.en_cours(h.t) == 's-1' and voix.etat()['joue_s'] == pytest.approx(7.4)
    h.t = 107.6
    assert voix.en_cours(h.t) is None and voix.etat()['en_cours'] is None
    assert voix.etat()['joue_s'] == pytest.approx(7.5)


@pytest.mark.parametrize('api, parametre, binaire', [
    (1003, LECTURE, b'\x00' * 3),                               # impair : pas du PCM de 16 bits
    (1003, LECTURE, b'\x00' * (TAILLE_MORCEAU_MAX + 2)),        # plus de 3 s
    (1003, LECTURE, b''),                                        # vide
    (1003, json.dumps({'app_name': 'atelier'}), b'\x00\x00'),   # sans stream_id
    (1003, json.dumps({'app_name': 'atelier', 'stream_id': 's 1'}), b'\x00\x00'),
    (1003, 'pas du JSON', b'\x00\x00'),
    (1004, ARRET, b'\x00\x00'),                                  # 1004 sans binary
    (1004, '{}', b''),                                           # 1004 sans app_name
    (1001, json.dumps({'index': 0, 'speaker_id': 1, 'text': ''}), b''),
    (1001, json.dumps({'index': 0, 'text': 'Bonjour'}), b''),   # sans speaker_id
    (1006, json.dumps({'volume': 101}), b''),
    (1006, json.dumps({'volume': '60'}), b''),
    (1005, json.dumps({'volume': 3}), b''),
])
def test_requete_mal_formee_ecart_compte(voix, api, parametre, binaire):
    assert voix.traiter(api, parametre, binaire) == (3204, '')
    e = voix.etat()
    assert e['ecarts'] == 1 and e['derniers_ecarts'][0]['api'] == api
    assert e['derniers_ecarts'][0]['raison'] and e['morceaux_recus'] == 0


def test_api_inconnue_sans_ecart(voix):
    assert voix.traiter(1002, '{}') == (3203, '')         # le micro : jamais par le nœud voix
    assert voix.traiter(1999, '{}') == (3203, '')
    assert voix.etat()['ecarts'] == 0 and voix.etat()['requetes'] == {'1002': 1, '1999': 1}


def test_1005_sans_parameter_comme_le_sdk_cpp(voix):
    assert voix.traiter(1006, json.dumps({'volume': 60})) == (0, '')
    assert json.loads(voix.traiter(1005, '')[1]) == {'volume': 60}
    assert json.loads(voix.traiter(1005, '{}')[1]) == {'volume': 60}
    assert voix.etat()['ecarts'] == 0


def test_1004_coupe_le_flux_qui_joue(voix, h):
    voix.traiter(1003, lecture('s-1'), pcm(3.0))
    h.t += 1.0
    assert voix.traiter(1004, ARRET) == (0, '')
    e = voix.etat()
    assert e['en_cours'] is None and e['arrets'] == 1
    assert e['flux'][0]['interrompu'] and e['flux'][0]['coupe'] == pytest.approx(101.0)
    assert e['joue_s'] == pytest.approx(1.0)
    h.t += 0.2
    voix.traiter(1003, lecture('s-2'), pcm(1.0))         # après le 1004 : pas de flux mêlé
    assert voix.etat()['flux_meles'] == 0 and voix.en_cours(h.t) == 's-2'


def test_1004_d_une_autre_application_ne_coupe_rien(voix, h):
    voix.traiter(1003, lecture('s-1'), pcm(3.0))
    assert voix.traiter(1004, json.dumps({'app_name': 'example'})) == (0, '')
    assert voix.en_cours(h.t) == 's-1' and voix.etat()['arrets'] == 1


def test_1004_sans_rien_qui_joue(voix):
    assert voix.traiter(1004, ARRET) == (0, '')
    assert voix.etat()['arrets'] == 1 and voix.etat()['ecarts'] == 0


def test_flux_meles_et_flux_qui_se_suivent(voix, h):
    voix.traiter(1003, lecture('s-1'), pcm(2.0))
    h.t += 1.0
    voix.traiter(1003, lecture('s-2'), pcm(2.0))         # s-1 joue encore : deux sons à la fois
    e = voix.etat()
    assert e['flux_meles'] == 1 and e['flux'][0]['remplace'] and e['en_cours'] == 's-2'
    h.t += 2.5                                            # s-2 a fini (101 + 2 = 103 < 103,5)
    voix.traiter(1003, lecture('s-3'), pcm(1.0))
    assert voix.etat()['flux_meles'] == 1 and [f['stream_id'] for f in voix.etat()['flux']] == [
        's-1', 's-2', 's-3']


def test_morceaux_trop_rapides_et_trou(voix, h):
    voix.traiter(1003, lecture('s-1'), pcm(1.0))
    h.t += 0.3
    voix.traiter(1003, lecture('s-1'), pcm(1.0))         # 0,3 s après : trop rapide
    assert voix.etat()['trop_rapides'] == 1 and voix.etat()['trous'] == 0
    h.t += 3.0                                            # tout était joué à 102,0 : un trou
    voix.traiter(1003, lecture('s-1'), pcm(1.0))
    e = voix.etat()
    assert e['trous'] == 1 and e['flux'][0]['trous'] == 1 and len(e['flux']) == 1


def test_les_vingt_derniers_flux(voix, h):
    for i in range(25):
        voix.traiter(1003, lecture(f's-{i}'), pcm(0.5))
        h.t += 1.0
    e = voix.etat()
    assert len(e['flux']) == 20 and e['flux'][0]['stream_id'] == 's-5'
    assert e['morceaux_recus'] == 25 and e['joue_s'] == pytest.approx(12.5)


def test_tts_volume_led_d_avant(voix, h):
    tts = {'index': 3, 'speaker_id': 1, 'text': 'Bonjour'}
    assert voix.traiter(1001, json.dumps(tts)) == (0, '')
    assert voix.traiter(1010, json.dumps({'R': 1, 'G': 2, 'B': 3})) == (0, '')
    assert voix.traiter(1010, json.dumps({'R': 300, 'G': 2, 'B': 3}))[0] == 3204
    e = voix.etat()
    assert e['tts']['text'] == 'Bonjour' and e['tts_nombre'] == 1
    assert e['led'] == {'R': 1, 'G': 2, 'B': 3}
    assert {'tts', 'tts_nombre', 'volume', 'led', 'led_historique'} <= set(e)


def test_repli_sans_le_contrat_meme_verdict(voix):
    cas = [(1003, LECTURE, pcm(0.5)), (1003, LECTURE, b'\x00' * 3), (1004, ARRET, b''),
           (1004, ARRET, b'\x00\x00'), (1006, json.dumps({'volume': 60}), b''),
           (1006, json.dumps({'volume': 101}), b''), (1001, json.dumps(
               {'index': 0, 'speaker_id': 1, 'text': 'Salut'}), b''), (1003, 'x', b'\x00\x00')]
    for api, parametre, binaire in cas:
        assert (erreurs_simples(api, parametre, binaire) == []) == (
            voix.erreurs(api, parametre, binaire) == []), (api, parametre, len(binaire))


def test_le_faux_g1_passe_le_binary_et_se_tait_en_panne(h):
    g1 = FauxG1(FauxSport(horloge=h))
    assert g1.traiter('voice', 1003, lecture('s-9'), pcm(1.0)) == (0, '')
    assert g1.traiter('voice', 1003, lecture('s-9'), b'\x00' * 3) == (3204, '')
    voix = g1.etat()['voix']
    assert voix['en_cours'] == 's-9' and voix['ecarts'] == 1 and voix['morceaux_recus'] == 1
    g1.sport.changer_panne('muet')
    assert g1.traiter('voice', 1003, lecture('s-9'), pcm(1.0)) is None
    assert g1.etat()['voix']['morceaux_recus'] == 1
