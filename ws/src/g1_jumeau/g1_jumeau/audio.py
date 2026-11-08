"""
Le service voice du faux G1 (vague 6, section 13.6 du plan) : fichier de l'agent Voix.

Sans ROS, à horloge injectable. FauxG1 (robot.py) lui passe chaque requête du service voice :
FausseVoix.traiter(api, parametre, binaire, t) -> (code, data). Livré par l'agent Contrats avec
le comportement d'avant la vague 6 (déplacé de robot.py, sans changement), que l'agent Voix étend :
  1001 TTS {"index", "speaker_id", "text"} : gardée (tts, historique) ;
  1003 START_PLAY et 1004 STOP_PLAY : acceptées (code 0) ; à faire (agent Voix) : vérifier chaque
       requête avec atelier.lieu.voix.erreurs_requete_voix (morceaux de PCM pairs, 96 000 octets
       au plus, même stream_id dans une phrase), suivre les flux (morceaux, octets, durée,
       interruption par 1004) et compter les écarts (code 3204) ;
  1005 GetVolume : {"volume": n} ; 1006 SetVolume {"volume": 0 à 100} ;
  1010 LED {"R", "G", "B"} de 0 à 255 (le pilotage s'en sert : dernières valeurs, historique).
etat() alimente le champ voix de /g1_jumeau/etat : tts, tts_nombre, volume, led, led_historique
(lus par le critère 28 et les tests du pilotage), plus ce que l'agent Voix ajoute (des champs
nouveaux seulement).
"""
import json

CODE_OK = 0
CODE_API = 3203
CODE_PARAMETRES = 3204


def lire_json(texte):
    """Objet JSON d'un parameter, ou None."""
    try:
        d = json.loads(texte) if texte else {}
    except (TypeError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def entier(v):
    return isinstance(v, int) and not isinstance(v, bool)


class FausseVoix:
    """Service voice du faux G1 : TTS, lecture de PCM, volume, LED."""

    def __init__(self, horloge=None):
        self.horloge = horloge
        self.tts = None
        self.tts_historique = []
        self.volume = 70
        self.led = None
        self.led_historique = []

    def traiter(self, api, parametre, binaire=b'', t=None):
        """(code, data) de la réponse à une requête du service voice."""
        if t is None:
            t = float(self.horloge()) if self.horloge else 0.0
        d = lire_json(parametre)
        if api == 1005:
            return (CODE_OK, json.dumps({'volume': self.volume}))
        if api in (1003, 1004):
            return (CODE_OK, '')
        if d is None:
            return (CODE_PARAMETRES, '')
        if api == 1001:
            texte = d.get('text')
            if not isinstance(texte, str) or not texte:
                return (CODE_PARAMETRES, '')
            self.tts = {'text': texte, 'index': d.get('index'), 'speaker_id': d.get('speaker_id'),
                        't': round(t, 3)}
            self.tts_historique.append(self.tts)
            return (CODE_OK, '')
        if api == 1006:
            v = d.get('volume')
            if not entier(v) or not 0 <= v <= 100:
                return (CODE_PARAMETRES, '')
            self.volume = v
            return (CODE_OK, '')
        if api == 1010:
            couleur = [d.get(c) for c in 'RGB']
            if not all(entier(c) and 0 <= c <= 255 for c in couleur):
                return (CODE_PARAMETRES, '')
            self.led = dict(zip('RGB', couleur))
            self.led_historique.append({'t': round(t, 3), 'R': couleur[0], 'G': couleur[1],
                                        'B': couleur[2]})
            return (CODE_OK, '')
        return (CODE_API, '')

    def etat(self):
        """Le champ voix de /g1_jumeau/etat."""
        return {'tts': self.tts, 'tts_nombre': len(self.tts_historique), 'volume': self.volume,
                'led': self.led, 'led_historique': list(self.led_historique[-50:])}
