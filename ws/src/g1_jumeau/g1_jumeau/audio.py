"""
Le service voice du faux G1 (vague 6, section 13.6 du plan) : fichier de l'agent Voix.

Sans ROS, à horloge injectable. FauxG1 (robot.py) lui passe chaque requête du service voice :
FausseVoix.traiter(api, parametre, binaire, t) -> (code, data), comme le vrai G1 (SDK d'Unitree,
unitree_sdk2/example/g1/audio et unitree_sdk2py/g1/audio/g1_audio_client.py) :
  1001 TTS {"index", "speaker_id", "text"} : gardée (tts, historique) ;
  1003 START_PLAY {"app_name", "stream_id"} + binary (PCM 16 kHz mono 16 bits petit-boutiste,
       96 000 octets au plus, nombre pair) : le morceau s'ajoute au flux de son stream_id ;
  1004 STOP_PLAY {"app_name"} : le flux en cours de cette application est coupé (code 0, comme le
       SDK, qui ignore la réponse) ;
  1005 GetVolume : {"volume": n} (parameter vide accepté, comme GetVolume du SDK C++) ;
  1006 SetVolume {"volume": 0 à 100} ;
  1010 LED {"R", "G", "B"} de 0 à 255 (le pilotage s'en sert : dernières valeurs, historique).
Chaque requête 1001 à 1006 est vérifiée par atelier.lieu.voix.erreurs_requete_voix (le
contrat du nœud voix) : mal formée, elle répond 3204 et compte un écart (ecarts,
derniers_ecarts) ; une autre api (1002, le micro) répond 3203.

Ce que le faux G1 « joue » (suivi des flux, sans haut-parleur) : un flux commence à son premier
morceau et se joue sans arrêt tant que les morceaux arrivent avant la fin de ce qui est déjà
reçu (fin_lecture) ; un morceau qui arrive après est un trou (le son s'est tu entre deux
morceaux) ; deux morceaux d'un même flux à moins de ECART_MIN_S sont trop rapides (les exemples
du SDK attendent 1 s) ; un flux neuf qui commence pendant qu'un autre joue encore, sans 1004
entre les deux, est un flux mêlé (deux sons en même temps) ; un 1004 coupe le flux qui joue.

etat() : le champ voix de /g1_jumeau/etat : tts, tts_nombre, volume, led, led_historique
(d'avant la vague 6 : critère 28 et tests du pilotage), plus flux (les 20 derniers), en_cours
(stream_id qui joue, ou None), octets_recus, morceaux_recus, ecarts, derniers_ecarts,
flux_meles, trop_rapides, trous, arrets, requetes (par api) et joue_s (secondes jouées en tout).
"""
import json
from pathlib import Path
import sys

CODE_OK = 0
CODE_API = 3203
CODE_PARAMETRES = 3204

APIS_VERIFIEES = (1001, 1003, 1004, 1005, 1006)    # atelier.lieu.voix.APIS_NOEUD_VOIX
OCTETS_PAR_SECONDE = 32000                          # PCM 16 kHz, mono, 16 bits
TAILLE_MORCEAU_MAX = 96000                          # 3 s par requête 1003
ECART_MIN_S = 0.95                                  # 1 s entre deux morceaux (SDK), gigue ôtée
TOLERANCE_S = 0.15                                  # gigue permise : entre deux flux, trous
FLUX_GARDES = 20
ECARTS_GARDES = 20


def lire_json(texte):
    """Objet JSON d'un parameter, ou None."""
    try:
        d = json.loads(texte) if texte else {}
    except (TypeError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def entier(v):
    return isinstance(v, int) and not isinstance(v, bool)


def contrat_voix():
    """atelier.lieu.voix (contrat du nœud voix), trouvé depuis le dépôt si besoin ; None sinon."""
    try:
        from atelier.lieu import voix
        return voix
    except ImportError:
        pass
    for parent in Path(__file__).resolve().parents:
        if (parent / 'atelier' / 'lieu' / 'voix.py').is_file():
            sys.path.insert(0, str(parent))
            try:
                from atelier.lieu import voix
                return voix
            except ImportError:
                return None
    return None


def erreurs_simples(api, parametre, binaire):
    """
    Vérification de repli (sans atelier.lieu) : les règles principales du schéma requete_voix.

    Le faux G1 tourne toujours à côté du dépôt : ce repli ne sert que si atelier est introuvable.
    """
    d = lire_json(parametre)
    n = len(binaire or b'')
    if d is None:
        return ['parameter illisible']
    if api == 1003:
        if not isinstance(d.get('app_name'), str) or not isinstance(d.get('stream_id'), str):
            return ['1003 : app_name et stream_id attendus']
        if not 2 <= n <= TAILLE_MORCEAU_MAX or n % 2:
            return [f'1003 : {n} octets de PCM (de 2 à {TAILLE_MORCEAU_MAX}, nombre pair)']
        return []
    if n:
        return [f'{api} : pas de binary attendu ({n} octets)']
    if api == 1004 and not isinstance(d.get('app_name'), str):
        return ['1004 : app_name attendu']
    if api == 1006 and not (entier(d.get('volume')) and 0 <= d['volume'] <= 100):
        return ['1006 : volume de 0 à 100']
    if api == 1001 and not (isinstance(d.get('text'), str) and d['text']):
        return ['1001 : text attendu']
    return []


class Flux:
    """Un flux de son (un stream_id) : ses morceaux, sa durée et son déroulé dans le faux G1."""

    def __init__(self, stream_id, app_name, t):
        self.stream_id = stream_id
        self.app_name = app_name
        self.debut = t
        self.dernier_morceau = None
        self.fin_lecture = t            # instant où le son déjà reçu aura fini de jouer
        self.morceaux = 0
        self.octets = 0
        self.tailles = []
        self.trous = 0
        self.trop_rapides = 0
        self.coupe = None               # instant du 1004 qui l'a coupé
        self.remplace = False           # un autre flux a commencé pendant qu'il jouait (flux mêlé)

    def ajouter(self, octets, t):
        """Un morceau de plus ; rend (trou, trop_rapide)."""
        trou = self.morceaux > 0 and t > self.fin_lecture + TOLERANCE_S
        rapide = self.dernier_morceau is not None and t - self.dernier_morceau < ECART_MIN_S
        self.trous += int(trou)
        self.trop_rapides += int(rapide)
        self.fin_lecture = max(self.fin_lecture, t) + octets / OCTETS_PAR_SECONDE
        self.dernier_morceau = t
        self.morceaux += 1
        self.octets += octets
        if len(self.tailles) < 50:
            self.tailles.append(octets)
        return trou, rapide

    def joue(self, t):
        """Vrai si le flux joue encore à l'instant t."""
        return self.coupe is None and not self.remplace and t < self.fin_lecture

    def duree_s(self):
        """Durée du son reçu."""
        return self.octets / OCTETS_PAR_SECONDE

    def joue_s(self, t):
        """Secondes de ce flux déjà jouées à l'instant t."""
        fin = min(self.fin_lecture, t)
        if self.coupe is not None:
            fin = min(fin, self.coupe)
        return max(0.0, fin - self.debut) if self.morceaux else 0.0

    def resume(self, t):
        return {'stream_id': self.stream_id, 'app_name': self.app_name,
                'debut': round(self.debut, 3), 'morceaux': self.morceaux, 'octets': self.octets,
                'tailles': list(self.tailles), 'duree_s': round(self.duree_s(), 3),
                'fin_lecture': round(self.fin_lecture, 3), 'joue': self.joue(t),
                'interrompu': self.coupe is not None,
                'coupe': None if self.coupe is None else round(self.coupe, 3),
                'remplace': self.remplace, 'trous': self.trous, 'trop_rapides': self.trop_rapides}


class FausseVoix:
    """Service voice du faux G1 : TTS, lecture de PCM (vérifiée et suivie), volume, LED."""

    def __init__(self, horloge=None):
        self.horloge = horloge
        self.tts = None
        self.tts_historique = []
        self.volume = 70
        self.led = None
        self.led_historique = []
        self.contrat = contrat_voix()
        self.flux = []                  # les derniers flux, le plus récent à la fin
        self.octets_recus = 0
        self.morceaux_recus = 0
        self.ecarts = 0
        self.derniers_ecarts = []
        self.flux_meles = 0
        self.trop_rapides = 0
        self.trous = 0
        self.arrets = 0
        self.requetes = {}
        self.joue_avant = 0.0           # secondes jouées par les flux oubliés (au-delà des 20)

    # ---------------------------------------------------- vérification

    def erreurs(self, api, parametre, binaire):
        """Erreurs (en français) d'une requête 1001 à 1006 : [] si elle est bien formée."""
        if self.contrat is not None:
            return self.contrat.erreurs_requete_voix(api, parametre, binaire)
        return erreurs_simples(api, parametre, binaire)

    def _ecart(self, t, api, erreurs, binaire):
        self.ecarts += 1
        self.derniers_ecarts.append({'t': round(t, 3), 'api': api, 'octets': len(binaire or b''),
                                     'raison': str(erreurs[0])[:200]})
        del self.derniers_ecarts[:-ECARTS_GARDES]

    # ---------------------------------------------------- requêtes

    def traiter(self, api, parametre, binaire=b'', t=None):
        """(code, data) de la réponse à une requête du service voice."""
        if t is None:
            t = float(self.horloge()) if self.horloge else 0.0
        binaire = bytes(binaire or b'')
        self.requetes[api] = self.requetes.get(api, 0) + 1
        if api in APIS_VERIFIEES:
            if api == 1005 and not parametre:
                parametre = '{}'            # GetVolume du SDK C++ n'envoie pas de parameter
            erreurs = self.erreurs(api, parametre, binaire)
            if erreurs:
                self._ecart(t, api, erreurs, binaire)
                return (CODE_PARAMETRES, '')
        d = lire_json(parametre)
        if api == 1005:
            return (CODE_OK, json.dumps({'volume': self.volume}))
        if api == 1003:
            self._jouer(d, binaire, t)
            return (CODE_OK, '')
        if api == 1004:
            self._couper(d, t)
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

    def _courant(self):
        return self.flux[-1] if self.flux else None

    def _jouer(self, d, binaire, t):
        courant = self._courant()
        stream_id, app_name = str(d['stream_id']), str(d['app_name'])
        if courant is None or courant.stream_id != stream_id or courant.coupe is not None:
            if courant is not None and courant.joue(t - TOLERANCE_S):
                self.flux_meles += 1        # deux sons en même temps, sans 1004 entre les deux
                courant.remplace = True
            courant = Flux(stream_id, app_name, t)
            self.flux.append(courant)
            if len(self.flux) > FLUX_GARDES:
                self.joue_avant += self.flux.pop(0).joue_s(t)
        trou, rapide = courant.ajouter(len(binaire), t)
        self.trous += int(trou)
        self.trop_rapides += int(rapide)
        self.octets_recus += len(binaire)
        self.morceaux_recus += 1

    def _couper(self, d, t):
        self.arrets += 1
        courant = self._courant()
        if courant is not None and courant.app_name == str(d['app_name']) and courant.joue(t):
            courant.coupe = t
            courant.fin_lecture = t

    # ---------------------------------------------------- état

    def en_cours(self, t):
        """stream_id du flux qui joue à l'instant t, ou None."""
        courant = self._courant()
        return courant.stream_id if courant is not None and courant.joue(t) else None

    def etat(self, t=None):
        """Le champ voix de /g1_jumeau/etat."""
        if t is None:
            t = float(self.horloge()) if self.horloge else 0.0
        return {'tts': self.tts, 'tts_nombre': len(self.tts_historique), 'volume': self.volume,
                'led': self.led, 'led_historique': list(self.led_historique[-50:]),
                'flux': [f.resume(t) for f in self.flux], 'en_cours': self.en_cours(t),
                'octets_recus': self.octets_recus, 'morceaux_recus': self.morceaux_recus,
                'ecarts': self.ecarts, 'derniers_ecarts': list(self.derniers_ecarts),
                'flux_meles': self.flux_meles, 'trop_rapides': self.trop_rapides,
                'trous': self.trous, 'arrets': self.arrets,
                'requetes': {str(a): n for a, n in sorted(self.requetes.items())},
                'joue_s': round(self.joue_avant + sum(f.joue_s(t) for f in self.flux), 3)}
