"""
Le faux G1 étendu (vague 4, section 11.5 du plan), sans ROS, à horloge injectable.

Services sport, arm et voice, rt/arm_sdk vérifié et /lowstate simulé.

FauxG1 répond comme le vrai robot (réponses (code, data)) :
  - sport : machine d'états des modes (0, 1, 3, 500 puis 801, 702 puis 801, 706 ; 7001 rend le
    mode) et les refus réalistes : 7301 pour marcher hors de 500/801, 7302 pour un mode
    inconnu ; la liste 7100 des danses ({"fsm_id": 550, "api_id": 1, "motion": {...}}) et
    leur lecture (7101 550000 + n depuis 801, durée, retour seul en 801 ; marche refusée
    pendant la danse) ; les tâches 7106 ; les commandes que l'Atelier interdit (7102, 7103,
    7104, 7107, 7110, 7111) sont acceptées comme par le vrai robot, mais comptées
    (interdits_recus) : les tests vérifient qu'il n'en arrive jamais. 7105 passe toujours par
    FauxSport (logique.py, inchangé) ;
  - arm : gestes 7106 {"action_id"} (7402 inconnu, 7404 hors de 500/501/801, 7400 si rt/arm_sdk
    pilote les bras, 7401 pour un autre geste pendant que les bras tiennent le précédent ; 99, ou
    le même geste, les relâche ; un geste tient au plus 20 s), liste 7107, gestes appris 7108 ;
  - voice : TTS 1001, volume 1005 et 1006, LED 1010 (dernières valeurs et historique gardés).
VerificationArmSdk contrôle chaque LowCmd reçu sur /arm_sdk avec les limites du contrat
(atelier.lieu.pilotage) : poids, rampes, angles, vitesses, taille tenue, jambes jamais écrites ;
tout écart est compté. BrasSimules donne les angles mesurés de /lowstate : les bras suivent les
ordres pondérés par le poids, sinon la pose où le contrôleur d'Unitree les tient.
"""
import json
import math
from pathlib import Path
import sys

FSM_MARCHE = 801
POSTURES = (0, 1, 3, 500, 702, 706)
FSM_GESTES = (500, 501, 801)
DANSE_PREFIXE = 550000
GESTES = {99: 'release '
              'arm', 11: 'two-hand kiss', 12: 'left kiss', 13: 'right kiss', 15: 'hands up',
          17: 'clap', 18: 'high five', 19: 'hug', 20: 'heart', 21: 'right heart', 22: 'reject',
          23: 'right hand up', 24: 'x-ray', 25: 'face wave', 26: 'high wave', 27: 'shake hand'}
TENUE_MAX_S = 20.0              # un geste tient les bras au plus 20 s (SDK C++)
# rt/arm_sdk pilote les bras : poids > 0 reçu il y a moins de ce temps
ARM_SDK_ACTIF_S = 0.5
DUREES_POSTURE_S = {500: 1.0, 702: 2.0}     # 500 puis 801, 702 puis 801
# Danses du faux G1 : celles essayées par la communauté, l'accueil, et les interdites (pour les
# refus)
DANSES = {602: ('popping', 9.0), 603: ('capture', 12.0), 604: ('robot_dance', 18.2),
          574: ('welcome', 42.0), 401: ('lie_down', 5.0), 402: ('lie_down_2', 5.0),
          403: ('unknown', 4.0)}
SPORT_INTERDITS = (7102, 7103, 7104, 7107, 7110, 7111)
CODE_OK = 0
CODE_MODE = 7301                # pas en mode marche
CODE_FSM_INCONNU = 7302
CODE_TACHE = 7303
CODE_ARM_SDK = 7400
CODE_TENU = 7401
CODE_GESTE = 7402
CODE_FSM_GESTE = 7404
CODE_API = 3203
CODE_PARAMETRES = 3204


def contrat_pilotage():
    """atelier.lieu.pilotage (limites des bras), trouvé depuis le dépôt si besoin ; None sinon."""
    try:
        from atelier.lieu import pilotage
        return pilotage
    except ImportError:
        pass
    for parent in Path(__file__).resolve().parents:
        if (parent / 'atelier' / 'lieu' / 'pilotage.py').is_file():
            sys.path.insert(0, str(parent))
            try:
                from atelier.lieu import pilotage
                return pilotage
            except ImportError:
                return None
    return None


def lire_json(texte):
    """Objet JSON d'un parameter, ou None."""
    try:
        d = json.loads(texte) if texte else {}
    except (TypeError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def entier(v):
    return isinstance(v, int) and not isinstance(v, bool)


class FauxG1:
    """Services sport (modes, danses, tâches), arm et voice du faux G1 ; 7105 par FauxSport."""

    def __init__(self, sport, horloge=None, fsm=FSM_MARCHE, danses=None, echelle_danses=1.0):
        # FauxSport : 7105, pannes, échéance de la consigne
        self.sport = sport
        self.horloge = horloge or sport.horloge
        self.fsm = int(fsm)
        self.fsm_suivant = None                  # (mode, instant) : 500 → 801, 702 → 801
        self.danses = dict(DANSES if danses is None else danses)
        self.echelle_danses = float(echelle_danses)
        self.danse = None                        # {id, debut, fin}
        self.danses_jouees = []
        self.tenu = None                         # (geste, instant)
        self.gestes_joues = []
        self.taches = []
        self.postures = []                       # [(instant, mode demandé, code)]
        self.interdits_recus = []                # [(service, api_id, parameter)]
        self.requetes = {'sport': 0, 'arm': 0, 'voice': 0}
        self.tts = None
        self.tts_historique = []
        self.volume = 70
        self.led = None
        self.led_historique = []
        self.arm_sdk = VerificationArmSdk(self.horloge)
        self.dernier_code = {}

    # ------------------------------------------------------------ état

    def maintenant(self):
        return float(self.horloge())

    def mettre_a_jour(self, t=None):
        """Fins de transition (500 → 801, 702 → 801), de danse et de geste tenu."""
        t = self.maintenant() if t is None else t
        if self.fsm_suivant is not None and t >= self.fsm_suivant[1]:
            self.fsm, self.fsm_suivant = self.fsm_suivant[0], None
        if self.danse is not None and t >= self.danse['fin']:
            self.danse = None
            self.fsm = FSM_MARCHE
        if self.tenu is not None and t - self.tenu[1] >= TENUE_MAX_S:
            self.tenu = None

    def etat(self):
        t = self.maintenant()
        self.mettre_a_jour(t)
        danse = None
        if self.danse is not None:
            danse = {'id': self.danse['id'], 'reste_s': round(self.danse['fin'] - t, 2)}
        return {
            'fsm': self.fsm, 'danse': danse, 'danses_jouees': list(self.danses_jouees[-10:]),
            'bras_tenus': self.tenu is not None,
            'geste_tenu': None if self.tenu is None else self.tenu[0],
            'gestes_joues': list(self.gestes_joues[-20:]), 'taches': list(self.taches[-10:]),
            'postures': list(self.postures[-20:]),
            'interdits_recus': list(self.interdits_recus[-20:]),
            'nombre_interdits': len(self.interdits_recus),
            'requetes_services': dict(self.requetes),
            'voix': {'tts': self.tts, 'tts_nombre': len(self.tts_historique),
                     'volume': self.volume,
                     'led': self.led, 'led_historique': list(self.led_historique[-50:])},
            'arm_sdk': self.arm_sdk.etat(t),
        }

    # ------------------------------------------------------------ requêtes

    def traiter(self, service, api_id, parametre):
        """(code, data) de la réponse, ou None si le faux G1 ne répond pas (panne muet)."""
        self.requetes[service] = self.requetes.get(service, 0) + 1
        if service == 'sport' and api_id == 7105:
            return self._marche(parametre)
        if self.sport.panne == 'muet':
            return None
        t = self.maintenant()
        self.mettre_a_jour(t)
        if service == 'sport':
            reponse = self._sport(int(api_id), parametre, t)
        elif service == 'arm':
            reponse = self._arm(int(api_id), parametre, t)
        elif service == 'voice':
            reponse = self._voice(int(api_id), parametre, t)
        else:
            reponse = (CODE_API, '')
        self.dernier_code[service] = reponse[0]
        return reponse

    def _marche(self, parametre):
        """7105 : refusé (7301) hors de 500/801 ou pendant une danse, sauf l'arrêt (sans effet)."""
        self.mettre_a_jour()
        hors_marche = self.danse is not None or self.fsm not in (500, FSM_MARCHE)
        if self.sport.panne == 'aucune' and hors_marche:
            d = lire_json(parametre) or {}
            vitesse = d.get('velocity')
            nul = isinstance(vitesse, list) and all(isinstance(v, (int, float)) and abs(v) < 1e-9
                                                    for v in vitesse)
            self.sport.requetes += 1
            self.sport.reponses += 1
            if nul:
                self.sport.consigne_en_cours, self.sport.fin = (0.0, 0.0, 0.0), None
                self.sport.dernier_code = CODE_OK
                return (CODE_OK, '')
            self.sport.dernier_code = CODE_MODE
            return (CODE_MODE, '')
        code = self.sport.traiter(7105, parametre)
        return None if code is None else (code, '')

    def _sport(self, api, parametre, t):
        if self.sport.panne == 'refus':
            return (CODE_MODE, '')
        d = lire_json(parametre)
        if api == 7001:
            return (CODE_OK, json.dumps({'data': self.fsm}))
        if api in (7002, 7003, 7004, 7005, 7006):
            return (CODE_OK, json.dumps({'data': 0}))
        if d is None:
            return (CODE_PARAMETRES, '')
        if api == 7100:
            if d != {'fsm_id': 550, 'api_id': 1}:
                return (CODE_PARAMETRES, '')
            motion = {str(n): {'name': nom, 'duration': duree}
                      for n, (nom, duree) in self.danses.items()}
            return (CODE_OK, json.dumps({'fsm_id': 550, 'api_id': 1, 'motion': motion}))
        if api == 7101:
            return self._posture(d.get('data'), t)
        if api == 7106:
            tache = d.get('data')
            if not entier(tache) or tache not in (0, 1, 2, 3):
                return (CODE_TACHE, '')
            if self.danse is not None or self.fsm not in (500, FSM_MARCHE):
                return (CODE_MODE, '')
            self.taches.append(tache)
            return (CODE_OK, '')
        if api in SPORT_INTERDITS:
            self.interdits_recus.append(('sport', api, str(parametre)[:200]))
            return (CODE_OK, '')
        return (CODE_API, '')

    def _posture(self, fsm, t):
        if not entier(fsm):
            return (CODE_PARAMETRES, '')
        if self.danse is not None:
            code = CODE_MODE                       # pendant une danse, le robot n'écoute pas
        elif DANSE_PREFIXE < fsm < DANSE_PREFIXE + 1000:
            n = fsm - DANSE_PREFIXE
            if n not in self.danses:
                code = CODE_FSM_INCONNU
            elif self.fsm != FSM_MARCHE:
                code = CODE_MODE
            else:
                duree = self.danses[n][1] * self.echelle_danses
                self.danse = {'id': n, 'debut': t, 'fin': t + duree}
                self.danses_jouees.append(n)
                self.fsm, self.fsm_suivant = fsm, None
                self.tenu = None
                code = CODE_OK
            if n in (401, 402, 403):
                self.interdits_recus.append(('sport', 7101, json.dumps({'data': fsm})))
        elif fsm in POSTURES:
            code = CODE_OK
            if fsm == 706:
                self.fsm = 706 if self.fsm in (500, FSM_MARCHE) else FSM_MARCHE
                self.fsm_suivant = None
            elif fsm in DUREES_POSTURE_S:
                self.fsm, self.fsm_suivant = fsm, (FSM_MARCHE, t + DUREES_POSTURE_S[fsm])
            else:
                self.fsm, self.fsm_suivant = fsm, None
            if self.fsm not in FSM_GESTES:
                self.tenu = None
        else:
            code = CODE_FSM_INCONNU
            if fsm in (2, 4, FSM_MARCHE):
                self.interdits_recus.append(('sport', 7101, json.dumps({'data': fsm})))
        self.postures.append((round(t, 3), fsm, code))
        return (code, '')

    def _arm(self, api, parametre, t):
        d = lire_json(parametre)
        if api == 7107:
            return (CODE_OK, json.dumps([{'id': n, 'name': nom} for n, nom in GESTES.items()]))
        if api == 7113:
            return (CODE_OK, '')
        if d is None:
            return (CODE_PARAMETRES, '')
        if api == 7108:
            nom = d.get('action_name')
            return (CODE_OK, '') if isinstance(nom, str) and nom else (CODE_PARAMETRES, '')
        if api != 7106:
            return (CODE_API, '')
        action = d.get('action_id', d.get('data'))
        if not entier(action) or action not in GESTES:
            return (CODE_GESTE, '')
        if self.danse is not None or self.fsm not in FSM_GESTES:
            return (CODE_FSM_GESTE, '')
        if self.arm_sdk.actif(t):
            return (CODE_ARM_SDK, '')
        if action == 99 or (self.tenu is not None and action == self.tenu[0]):
            self.tenu = None
        elif self.tenu is not None:
            return (CODE_TENU, '')
        else:
            self.tenu = (action, t)
        self.gestes_joues.append(action)
        return (CODE_OK, '')

    def _voice(self, api, parametre, t):
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


class VerificationArmSdk:
    """Contrôle des LowCmd reçus sur /arm_sdk ; chaque écart au contrat est compté."""

    SESSION_FIN_S = 0.5             # plus de message depuis ce temps : la session est finie
    TOLERANCE = 1.10                # 10 % de marge sur les pas de poids et d'angle par message

    def __init__(self, horloge, contrat=None):
        self.horloge = horloge
        self.contrat = contrat or contrat_pilotage()
        c = self.contrat
        self.indices_bras = {} if c is None else {i: n for n, i in c.ARTICULATIONS_BRAS.items()}
        self.limites = {} if c is None else dict(c.LIMITES_BRAS)
        self.taille = (12, 13, 14) if c is None else tuple(sorted(c.ARTICULATIONS_TAILLE.values()))
        self.poids_indice = 29 if c is None else c.INDICE_POIDS
        frequence = 50.0 if c is None else c.FREQUENCE_BRAS_HZ
        self.pas_angle = (1.5 if c is None else c.VITESSE_BRAS_MAX) / frequence * self.TOLERANCE
        self.pas_poids = 1.0 / ((1.0 if c is None else c.RAMPE_MIN_S) * frequence) * self.TOLERANCE
        self.recus = 0
        self.sessions = []
        self.session = None
        self.precedent = None           # (instant, poids, q)
        self.ecarts = {'poids_hors_0_1': 0, 'saut_poids': 0, 'angle_hors_limites': 0,
                       'vitesse_bras': 0, 'jambes_ecrites': 0, 'taille_pilotee': 0,
                       'autres_moteurs': 0}
        self.exemples = []

    def _ecart(self, genre, detail):
        self.ecarts[genre] += 1
        if len(self.exemples) < 20:
            self.exemples.append(f'{genre} : {detail}')

    def actif(self, t=None):
        """rt/arm_sdk pilote les bras : un poids non nul reçu il y a moins de 0,5 s."""
        t = self.horloge() if t is None else t
        s = self.session
        return s is not None and s['t_poids'] is not None and t - s['t_poids'] < ARM_SDK_ACTIF_S

    def recevoir(self, q, kp, kd, t=None):
        """Un LowCmd : q, kp, kd des 35 moteurs (poids dans q[29])."""
        t = self.horloge() if t is None else t
        self.recus += 1
        poids = float(q[self.poids_indice])
        s = self.session
        if s is None or t - s['t_fin'] > self.SESSION_FIN_S:
            s = self.session = {'debut': t, 't_fin': t, 'messages': 0, 'poids_max': 0.0,
                                't_poids': None, 't_premier_poids': None, 't_plein': None,
                                't_dernier_plein': None, 't_zero': None, 'taille': None}
            self.sessions.append(s)
            del self.sessions[:-20]
            self.precedent = None
        s['messages'] += 1
        s['t_fin'] = t
        if not 0.0 <= poids <= 1.0:
            self._ecart('poids_hors_0_1', f'poids {poids:g}')
        if poids > 1e-3:
            s['t_poids'] = t
            if s['t_premier_poids'] is None:
                s['t_premier_poids'] = t
            s['t_zero'] = None
        elif s['t_premier_poids'] is not None and s['t_zero'] is None:
            s['t_zero'] = t
        if poids >= 1.0 - 1e-6:
            s['t_dernier_plein'] = t
            if s['t_plein'] is None:
                s['t_plein'] = t
        s['poids_max'] = max(s['poids_max'], poids)
        for i in range(12):
            if q[i] != 0.0 or kp[i] != 0.0 or kd[i] != 0.0:
                self._ecart('jambes_ecrites', f'moteur {i}')
                break
        for i in range(30, len(q)):
            if q[i] != 0.0 or kp[i] != 0.0 or kd[i] != 0.0:
                self._ecart('autres_moteurs', f'moteur {i}')
                break
        taille = tuple(round(float(q[i]), 4) for i in self.taille)
        if s['taille'] is None:
            s['taille'] = taille
        elif any(abs(a - b) > 1e-3 for a, b in zip(taille, s['taille'])):
            self._ecart('taille_pilotee', f'taille {taille} au lieu de {s["taille"]}')
        for i, nom in self.indices_bras.items():
            bas, haut = self.limites[nom]
            if (kp[i] != 0.0 or poids > 1e-3) and not bas - 1e-6 <= q[i] <= haut + 1e-6:
                self._ecart('angle_hors_limites', f'{nom} = {q[i]:.3f}')
        if self.precedent is not None:
            _, poids0, q0 = self.precedent
            if abs(poids - poids0) > self.pas_poids + 1e-9:
                self._ecart('saut_poids', f'{poids0:.3f} → {poids:.3f}')
            if max(poids, poids0) > 1e-3:
                for i, nom in self.indices_bras.items():
                    if abs(q[i] - q0[i]) > self.pas_angle + 1e-9:
                        self._ecart('vitesse_bras', f'{nom} : {q0[i]:.3f} → {q[i]:.3f}')
                        break
        self.precedent = (t, poids, list(q))

    def etat(self, t=None):
        t = self.horloge() if t is None else t

        def resume(s):
            duree = s['t_fin'] - s['debut']
            montee = None if s['t_plein'] is None or s['t_premier_poids'] is None else \
                round(s['t_plein'] - s['t_premier_poids'], 3)
            descente = None if s['t_zero'] is None or s['t_dernier_plein'] is None else \
                round(s['t_zero'] - s['t_dernier_plein'], 3)
            frequence = None
            if s['messages'] >= 2 and duree > 0:
                frequence = round((s['messages'] - 1) / duree, 2)
            return {'debut': round(s['debut'], 3), 'duree_s': round(duree, 3),
                    'messages': s['messages'],
                    'frequence_hz': frequence, 'poids_max': round(s['poids_max'], 4),
                    'rampe_montee_s': montee, 'rampe_descente_s': descente,
                    'fin_poids_zero': None if s['t_zero'] is None else round(s['t_zero'], 3),
                    'finie': t - s['t_fin'] > self.SESSION_FIN_S}
        poids = None if self.precedent is None else round(self.precedent[1], 4)
        return {'recus': self.recus, 'actif': self.actif(t), 'poids': poids,
                'sessions': [resume(s) for s in self.sessions[-5:]], 'ecarts': dict(self.ecarts),
                'exemples': list(self.exemples), 'contrat': self.contrat is not None}


class BrasSimules:
    """Angles mesurés (/lowstate) : ordre pondéré par le poids d'arm_sdk, sinon le repos."""

    # Pose où le contrôleur d'Unitree tient les bras (à vérifier sur le robot) : bras le long du
    # corps
    POSE_CONTROLEUR = {16: 0.2, 23: -0.2, 18: 0.3, 25: 0.3}
    CONSTANTE_S = 0.05              # retard du premier ordre des moteurs

    def __init__(self):
        self.q = [self.POSE_CONTROLEUR.get(i, 0.0) for i in range(35)]
        self.ordre = None               # (poids, q des 35 moteurs)
        self.t = None

    def ordonner(self, poids, q):
        self.ordre = (max(0.0, min(1.0, poids)), list(q))

    def avancer(self, t, arm_sdk_actif):
        dt = 0.02 if self.t is None else max(0.0, min(0.2, t - self.t))
        self.t = t
        k = 1.0 - math.exp(-dt / self.CONSTANTE_S)
        for i in range(12, 29):
            repos = self.POSE_CONTROLEUR.get(i, 0.0)
            cible = repos
            if self.ordre is not None and arm_sdk_actif:
                poids, q = self.ordre
                cible = poids * q[i] + (1.0 - poids) * repos if i >= 15 else repos
            self.q[i] += (cible - self.q[i]) * k
        return list(self.q)
