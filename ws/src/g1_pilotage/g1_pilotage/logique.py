"""
Logique du nœud pilotage, sans ROS ni réseau (section 11.5 du plan).

Le nœud (noeud.py) et son API HTTP (serveur.py) ne font que passer les demandes et les messages à
la classe Pilotage et exécuter ce qu'elle renvoie. Toutes les règles de sécurité sont ici, avec une
horloge injectable (temps mural monotone, en secondes) pour les tester finement :

  - interdits : atelier.lieu.pilotage.refus_commande (403, rien n'est envoyé au robot) ;
  - confirmations : « portique » pour amortir (1) et couple nul (0), double (un premier appel rend
    un jeton, le second doit venir dans les 10 s avec ce jeton et la case « robot au portique ») ;
    « zone_libre » pour une danse ou une chorégraphie (428 tant qu'elle manque) ;
  - verrou des mouvements : un seul maître, le guide ou le pilotage (/mouvement/maitre). Sans la
    main, joystick, postures, gestes, danses et chorégraphies sont refusés (409) ; la voix, le
    volume, la LED et l'ARRÊT restent permis. Prendre la main est refusé pendant une visite du
    guide, sauf « forcer » (/guide/stop, robot immobile, puis maître pilotage) ;
  - joystick avec homme mort : chaque ordre donne un 7105 de 0,5 s, plafonné ; sans ordre depuis
    0,5 s, StopMove ; à la fermeture du WebSocket, StopMove tout de suite ;
  - danses du robot (7101 550000 + n) : jamais 401, 402, 403, ni une danse absente de la liste
    lue dans le robot ; robot debout immobile en mode 801 ; pendant la danse, joystick, gestes et
    chorégraphies refusés ; l'ARRÊT n'envoie que StopMove (aucun ordre connu n'interrompt une
    danse : la télécommande reste l'arrêt d'urgence) ;
  - chorégraphies : vérifiées (verifier_choregraphie) avant de jouer ; bras par rt/arm_sdk à
    50 Hz (poids de 0 à 1 et de 1 à 0 en rampes, angles et vitesses bornés une seconde fois ici),
    taille tenue à sa position mesurée au départ, jambes jamais écrites ; pas de marche d'Unitree
    plafonnés ; LED, gestes et paroles à leur temps ;
  - ARRÊT : toujours permis. StopMove, chorégraphie arrêtée (poids ramené à 0 en 1 s), geste
    relâché (99) si les bras tiennent un geste, /guide/stop.

Chaque entrée renvoie un Resultat : un statut HTTP, un corps JSON (detail en français) et les
sorties à exécuter (Envoi d'une requête unitree_api, Bras pour /arm_sdk, ArretGuide, Maitre,
Dire). Un Resultat peut demander d'attendre la réponse du robot à une requête (attendre).
"""
from collections import namedtuple, OrderedDict
import datetime
import json
import math
import secrets
import time

from .contrat import charger

D = charger()

# Sorties de la logique, exécutées par le nœud
Envoi = namedtuple('Envoi', 'service api_id parametre identifiant raison')
Bras = namedtuple('Bras', 'poids q kp kd')       # q, kp, kd : {indice moteur: valeur}
ArretGuide = namedtuple('ArretGuide', 'raison')
Maitre = namedtuple('Maitre', 'message')          # message : dict du schéma maitre_mouvement
Dire = namedtuple('Dire', 'message')              # message : dict du schéma robot_dire

DELAI_REPONSE_S = 2.0           # attente de la réponse du robot à une requête
ROBOT_REPOND_S = 2.0            # robot_repond : une réponse il y a moins de ce temps
PERIODE_FSM_S = 1.0             # lecture du mode (7001) une fois par seconde
ECART_MIN_7105_S = 0.05         # au plus 20 ordres de marche par seconde (joystick qui inonde)
PERIODE_PAS_S = 0.1             # pas d'une chorégraphie : 7105 renvoyé 10 fois par seconde
DUREE_POSTURE_S = 3.0           # activité « posture » affichée pendant ce temps
DUREE_GESTE_S = 4.0             # activité « geste » affichée pendant ce temps
DUREE_ARRET_S = 1.0             # activité « arret » affichée pendant ce temps
DELAI_DEPART_S = 0.5            # départ d'une chorégraphie, pour caler la musique de la page
LOWSTATE_FRAIS_S = 0.5          # /lowstate plus vieux : bras du robot inconnus
VITESSES_LECTURE = (0.25, 1.0)  # vitesse de lecture d'une chorégraphie : jamais plus vite
IMMOBILE_APRES_S = D.ARRET_MAX_S
FIN_DANSE_MARGE_S = 10.0        # au-delà de la durée annoncée, la danse est supposée finie
TOLERANCE_POIDS = 1e-6
GUIDE_PERIME_S = 30.0           # /guide/etat plus vieux : le guide ne compte plus comme en mission

STOP_MOVE = D.parametre_vitesse(0.0, 0.0, 0.0, 1.0)


def heure_iso(mur=None):
    """Heure locale ISO 8601 avec décalage, à la seconde."""
    instant = datetime.datetime.fromtimestamp(time.time() if mur is None else mur)
    return instant.astimezone().isoformat(timespec='seconds')


class Resultat:
    """Réponse à une demande : statut HTTP, corps JSON, sorties, requête à attendre."""

    def __init__(self, statut=200, corps=None, sorties=None, attendre=None):
        self.statut = statut
        self.corps = dict(corps or {})
        self.sorties = list(sorties or [])
        self.attendre = attendre          # identifiant de la requête dont la réponse est attendue

    @property
    def ok(self):
        return 200 <= self.statut < 300

    def __repr__(self):
        return f'Resultat({self.statut}, {self.corps!r}, {len(self.sorties)} sorties)'


def refus(statut, detail, **autres):
    """Resultat d'un refus : rien n'est envoyé au robot."""
    return Resultat(statut, dict(detail=detail, **autres))


class Identifiants:
    """identity.id des requêtes : time.monotonic_ns(), strictement croissant (comme le pont)."""

    def __init__(self, horloge_ns=time.monotonic_ns):
        self._horloge_ns = horloge_ns
        self._dernier = 0

    def __call__(self):
        self._dernier = max(int(self._horloge_ns()), self._dernier + 1)
        return self._dernier


class Lecture:
    """Une chorégraphie en cours : temps de départ, événements faits, dernier ordre des bras."""

    def __init__(self, d, t0, debut_mur, q_taille, limites_pas, vitesse=1.0):
        self.d = d
        self.t0 = t0
        self.vitesse = float(vitesse)         # 1 : comme prévu ; 0,5 : deux fois plus lent
        self.debut_mur = debut_mur
        self.q_taille = dict(q_taille)        # {indice: angle mesuré au départ}
        self.evenements = D.evenements_choregraphie(d)
        self.prochain = 0                     # rang du prochain événement à faire
        self.limites_pas = limites_pas
        self.pas = None                       # pas en cours (dict) ; fin : temps de la danse
        self.fin_pas = None
        self.t_dernier_pas = None
        self.bras = bool((d.get('bras') or {}).get('poses'))
        self.poids = 0.0
        self.q = {}                           # dernier ordre des bras {indice: angle}
        self.t_bras = None


class Pilotage:
    """Règles du nœud pilotage ; chaque entrée renvoie un Resultat."""

    def __init__(self, horloge=time.monotonic, mur=time.time, identifiants=None,
                 vitesse_max=None):
        self.horloge = horloge
        self.mur = mur
        self.identifiants = identifiants or Identifiants()
        self.limites = D.limites_marche(vitesse_max)
        self.limites_pas = {axe: min(D.LIMITES_PAS[axe],
                                     self.limites[axe]) for axe in D.LIMITES_PAS}
        self.maitre = self._message_maitre('guide', 'démarrage du nœud pilotage',
                                           'Le guide a la main (le pilotage vient de démarrer).')
        self.envoyes = OrderedDict()          # identifiant → (service, api_id, instant, raison)
        self.reponses = OrderedDict()         # identifiant → (code, data, instant)
        self.t_reponse = None
        self.requetes = 0
        self.fsm = None
        self.t_fsm = None
        self.t_lecture_fsm = None
        # joystick
        self.consigne = (0.0, 0.0, 0.0)
        self.t_ordre = None
        self.marche = False
        self.t_7105 = None
        self.ordre_en_attente = False
        self.t_mouvement = None               # dernier ordre de marche non nul envoyé
        # danses, gestes, chorégraphies
        self.danses = None                    # {n: {nom, duree_s}} lu dans le robot (7100)
        self.t_danses = None
        self.gestes_robot = None              # réponse de 7107, telle quelle
        self.danse = None                     # {id, nom, debut (monotone), debut_mur, duree_s}
        self.lecture = None
        self.descente = None                  # ramène le poids d'arm_sdk à 0 : {t0, poids0, q}
        self.bras_tenus = False
        self.geste_tenu = None
        self.t_geste = None
        self.t_posture = None
        self.t_arret = None
        self.confirmations = {}               # jeton → (genre, clé, échéance)
        self.dernier_refus = None
        self.message = 'Prêt : prenez la main pour piloter le robot.'
        self.tts_index = 0
        # entrées venues du robot et du reste du système
        self.lowstate = None                  # ([q des 35 moteurs], instant)
        self.guide = None                     # (dernier /guide/etat, instant)
        self.pont = None                      # (dernier /pont/etat, instant)
        self.batterie = None                  # (soc en %, instant)
        self.prise = None                     # prise de la main en cours : {t, par, force}

    # ------------------------------------------------------------ outils

    def maintenant(self):
        return float(self.horloge())

    def _message_maitre(self, maitre, par, message):
        return {'version': 1, 'maitre': maitre, 'par': str(par)[:80],
                'depuis': heure_iso(self.mur()),
                'message': message}

    def _envoi(self, service, api_id, parametre, raison):
        t = self.maintenant()
        identifiant = self.identifiants()
        self.envoyes[identifiant] = (service, int(api_id), t, raison)
        while len(self.envoyes) > 500:
            self.envoyes.popitem(last=False)
        self.requetes += 1
        return Envoi(service, int(api_id), parametre, identifiant, raison)

    def _stop_move(self, raison):
        """Arrêt : StopMove du SDK : 7105 [0, 0, 0] pendant 1 s ; le joystick est oublié."""
        self.marche = False
        self.ordre_en_attente = False
        self.consigne = (0.0, 0.0, 0.0)
        self.t_7105 = self.maintenant()
        return self._envoi('sport', 7105, STOP_MOVE, raison)

    def a_la_main(self):
        return self.maitre['maitre'] == 'pilotage'

    def robot_repond(self, t=None):
        t = self.maintenant() if t is None else t
        return self.t_reponse is not None and t - self.t_reponse < ROBOT_REPOND_S

    def guide_en_mission(self, t=None):
        """
        Le guide est en visite ou en retour, d'après son dernier /guide/etat.

        Un état de moins de 30 s compte : un guide qui s'est tu en pleine visite compte encore, il
        faut alors « forcer ».
        """
        t = self.maintenant() if t is None else t
        if self.guide is None or t - self.guide[1] > GUIDE_PERIME_S:
            return False
        return self.guide[0].get('etat') in D_COMPORTEMENT_EN_MISSION

    def _occupe(self, quoi):
        """Refus 409 si une danse ou une chorégraphie tourne (quoi : ce qu'on voulait faire)."""
        if self.danse is not None:
            return refus(409, f'{quoi} : impossible pendant une danse du robot. Attendez la fin '
                              'de la danse '
                              '(la télécommande reste l\'arrêt d\'urgence).')
        if self.lecture is not None or self.descente is not None:
            return refus(409, f'{quoi} : impossible pendant une chorégraphie. Arrêtez-la d\'abord '
                              '(ARRÊT).')
        return None

    def _sans_main(self, quoi):
        if not self.a_la_main():
            return refus(409, f'{quoi} : prenez la main dans l\'onglet Pilotage (le guide a la '
                              'main).',
                         maitre=self.maitre['maitre'])
        return None

    def _noter_refus(self, code, message, service=None, api_id=None):
        self.dernier_refus = {'code': code, 'message': message, 'service': service,
                              'api_id': api_id,
                              'depuis': heure_iso(self.mur())}

    # ------------------------------------------------------------ état

    def activite(self, t=None):
        t = self.maintenant() if t is None else t
        if self.t_arret is not None and t - self.t_arret < DUREE_ARRET_S:
            return 'arret'
        if self.danse is not None:
            return 'danse'
        if self.lecture is not None or self.descente is not None:
            return 'choregraphie'
        if self.t_posture is not None and t - self.t_posture < DUREE_POSTURE_S:
            return 'posture'
        if self.t_geste is not None and t - self.t_geste < DUREE_GESTE_S:
            return 'geste'
        if self.marche:
            return 'marche'
        return 'repos'

    def etat(self, t=None):
        """Message de /pilotage/etat, au schéma etat_pilotage, avec des champs en plus."""
        t = self.maintenant() if t is None else t
        vx, vy, wz = self.consigne
        danse = None
        if self.danse is not None:
            danse = {'id': self.danse['id'], 'nom': self.danse['nom'],
                     'debut': self.danse['debut_iso'],
                     'debut_mur': self.danse['debut_mur'], 'duree_s': self.danse['duree_s'],
                     'ecoule_s': round(t - self.danse['debut'], 2)}
        choregraphie = None
        if self.lecture is not None:
            lec = self.lecture
            choregraphie = {'id': lec.d['id'], 'nom': lec.d['nom'], 'vitesse': lec.vitesse,
                            't': round((t - lec.t0) * lec.vitesse, 3),
                            'duree_s': lec.d['duree_s'], 'poids_bras': round(lec.poids, 4),
                            'debut_mur': lec.debut_mur, 'pas': lec.pas is not None}
        elif self.descente is not None:
            choregraphie = {'id': self.descente['id'], 't': None, 'duree_s': None, 'arret': True,
                            'poids_bras': round(self._poids_descente(t), 4)}
        batterie = None
        if self.batterie is not None:
            batterie = {'pourcent': self.batterie[0], 'age_s': round(t - self.batterie[1], 1)}
        return {
            'version': 1, 'maitre': self.maitre['maitre'], 'robot_repond': self.robot_repond(t),
            'fsm': self.fsm, 'activite': self.activite(t), 'message': self.message,
            'consigne': {'vx': round(vx, 4), 'vy': round(vy, 4), 'wz': round(wz, 4)},
            'age_ordre_s': None if self.t_ordre is None else round(max(0.0, t - self.t_ordre), 3),
            'danse': danse, 'choregraphie': choregraphie, 'bras_tenus': self.bras_tenus,
            'dernier_refus': self.dernier_refus,
            # en plus du schéma
            'maitre_detail': dict(self.maitre), 'limites': dict(self.limites),
            'batterie': batterie,
            'guide_en_mission': self.guide_en_mission(t), 'requetes': self.requetes,
            'lowstate': self.lowstate is not None and t - self.lowstate[1] < LOWSTATE_FRAIS_S,
            'danses_lues': self.danses is not None,
            'age_reponse_s': None if self.t_reponse is None else round(t - self.t_reponse, 2),
            'mur': round(self.mur(), 3),
        }

    # ------------------------------------------------------------ entrées venues de ROS

    def sur_reponse(self, identifiant, code, data=''):
        """Réponse d'un service (sport, arm, voice). False si elle n'est pas à nous."""
        if identifiant not in self.envoyes:
            return False
        service, api_id, _, raison = self.envoyes.pop(identifiant)
        t = self.maintenant()
        self.t_reponse = t
        code = int(code)
        self.reponses[identifiant] = (code, data, t)
        while len(self.reponses) > 200:
            self.reponses.popitem(last=False)
        if code != 0:
            message = D.message_refus(code)
            self._noter_refus(code, message, service, api_id)
            if raison not in ('lecture_fsm',):
                self.message = message
            return True
        if service == 'sport' and api_id == 7001:
            fsm = D.lire_fsm(data)
            if fsm is not None:
                self.fsm, self.t_fsm = fsm, t
        elif service == 'sport' and api_id == 7100:
            try:
                self.danses = D.lire_liste_danses(data)
                self.t_danses = t
            except ValueError:
                self._noter_refus(3204, 'liste des danses illisible', service, api_id)
        elif service == 'arm' and api_id == 7107:
            self.gestes_robot = data
        elif service == 'arm' and api_id == 7106 and raison.startswith('geste:'):
            self._suivre_geste(int(raison.split(':', 1)[1]))
        return True

    def _suivre_geste(self, action):
        """Bras tenus après un geste ; 99, ou le même geste, les relâche (SDK C++)."""
        if action is None:
            return
        if action == D.GESTE_RELACHER or (self.bras_tenus and action == self.geste_tenu):
            self.bras_tenus, self.geste_tenu = False, None
        else:
            self.bras_tenus, self.geste_tenu = True, action

    def sur_lowstate(self, angles):
        """Angles mesurés des 35 moteurs (/lowstate)."""
        self.lowstate = (list(angles), self.maintenant())

    def sur_guide_etat(self, donnees):
        if isinstance(donnees, dict):
            self.guide = (donnees, self.maintenant())

    def sur_pont_etat(self, donnees):
        if isinstance(donnees, dict):
            self.pont = (donnees, self.maintenant())

    def sur_batterie(self, pourcent):
        try:
            self.batterie = (int(pourcent), self.maintenant())
        except (TypeError, ValueError):
            pass

    def reponse(self, identifiant):
        """(code, data) de la réponse reçue à une requête, ou None."""
        r = self.reponses.get(identifiant)
        return None if r is None else (r[0], r[1])

    # ------------------------------------------------------------ verrou des mouvements

    def prendre_main(self, forcer=False, par='atelier'):
        """« Prendre la main ». Pendant une visite : 409, sauf forcer (le guide est arrêté)."""
        if self.a_la_main():
            return Resultat(200, {'detail': 'Vous avez déjà la main.', 'maitre': 'pilotage'})
        t = self.maintenant()
        en_mission = self.guide_en_mission(t)
        if en_mission and not forcer:
            etat = self.guide[0].get('etat')
            return refus(409, f'Le guide est en mission ({etat}) : attendez la fin de la visite, '
                              'ou forcez '
                              '(le guide sera arrêté).', guide=etat)
        sorties = [ArretGuide('prise de la main'), self._stop_move('prise_main')]
        self.prise = {'t': t, 'par': f'{par} (forcé)' if forcer and en_mission else par,
                      'force': bool(forcer and en_mission)}
        self.message = 'Arrêt du guide et du robot avant de prendre la main…'
        return Resultat(202, {'detail': self.message, 'attendre_immobile': True}, sorties)

    def robot_immobile(self, t=None):
        """Le robot est immobile depuis la demande : délai d'arrêt passé, pont sans mouvement."""
        t = self.maintenant() if t is None else t
        if self.prise is None or t - self.prise['t'] < IMMOBILE_APRES_S:
            return False
        if self.pont is not None and t - self.pont[1] < 1.0:
            pont = self.pont[0]
            consigne = pont.get('consigne') or {}
            bouge = any(abs(consigne.get(a, 0.0)) > 1e-3 for a in ('vx', 'vy', 'wz'))
            if pont.get('etat') == 'en_mouvement' or bouge:
                return False
        return True

    def finir_prise(self):
        """Fin de la prise de la main : maître pilotage. 504 si le robot n'est pas immobile."""
        if self.prise is None:
            return Resultat(200, {'detail': 'Vous avez la main.', 'maitre': self.maitre['maitre']})
        if not self.robot_immobile():
            self.prise = None
            self.message = 'Le robot ne s\'est pas arrêté : la main n\'a pas été prise.'
            return refus(504, self.message + ' Réessayez, ou utilisez la télécommande.')
        prise, self.prise = self.prise, None
        texte = ('Le robot est piloté depuis l\'onglet Pilotage : le guide '
                 'attend.' if not prise['force'] else
                 'Le guide a été arrêté : le robot est piloté depuis l\'onglet Pilotage.')
        self.maitre = self._message_maitre('pilotage', prise['par'], texte)
        self.message = 'Vous avez la main : le robot obéit à l\'onglet Pilotage.'
        return Resultat(200, {'detail': self.message, 'maitre': 'pilotage'},
                        [Maitre(dict(self.maitre))])

    def rendre_main(self, par='atelier'):
        """« Rendre la main » au guide : le robot reste immobile jusqu'à la prochaine demande."""
        occupe = self._occupe('Rendre la main')
        if occupe is not None:
            return occupe
        sorties = []
        if self.marche:
            sorties.append(self._stop_move('rendre_main'))
        self.prise = None
        self.maitre = self._message_maitre('guide', par, 'Le guide a la main : le robot attend sa '
                                                         'prochaine visite.')
        self.message = 'Main rendue au guide.'
        sorties.append(Maitre(dict(self.maitre)))
        return Resultat(200, {'detail': self.message, 'maitre': 'guide'}, sorties)

    # ------------------------------------------------------------ joystick (homme mort)

    def ordre_joystick(self, vx, vy, wz):
        """Ordre du joystick (toutes les 0,1 s tant que le manche est tenu) : un 7105 de 0,5 s."""
        t = self.maintenant()
        if not self.a_la_main():
            return refus(409, 'Joystick : prenez la main dans l\'onglet Pilotage (le guide a la '
                              'main).')
        occupe = self._occupe('Joystick')
        if occupe is not None:
            if self.marche:
                occupe.sorties.append(self._stop_move('joystick_refuse'))
            return occupe
        consigne = D.plafonner_marche(vx, vy, wz, self.limites)
        self.t_ordre = t
        if all(abs(v) < 1e-3 for v in consigne):
            return self.lacher_joystick('manche lâché')
        self.consigne = consigne
        self.marche = True
        self.message = 'Marche au joystick.'
        if self.t_7105 is not None and t - self.t_7105 < ECART_MIN_7105_S:
            self.ordre_en_attente = True
            return Resultat(200, {'consigne': self._consigne_dict()})
        return Resultat(200, {'consigne': self._consigne_dict()}, [self._envoi_marche(t)])

    def _consigne_dict(self):
        return dict(zip(('vx', 'vy', 'wz'), (round(v, 4) for v in self.consigne)))

    def _envoi_marche(self, t):
        vx, vy, wz = self.consigne
        self.t_7105 = t
        self.t_mouvement = t
        self.ordre_en_attente = False
        return self._envoi('sport', 7105, D.parametre_vitesse(vx, vy, wz, D.DUREE_ORDRE_S),
                           'joystick')

    def lacher_joystick(self, raison='WebSocket fermé'):
        """Manche lâché ou WebSocket fermé : StopMove tout de suite si le robot marchait."""
        if not self.marche:
            self.consigne = (0.0, 0.0, 0.0)
            return Resultat(200, {'consigne': self._consigne_dict()})
        self.message = f'Robot arrêté ({raison}).'
        return Resultat(200, {'consigne': {'vx': 0.0, 'vy': 0.0, 'wz': 0.0}},
                        [self._stop_move('joystick_lache')])

    # ------------------------------------------------------------ postures, tâches, gestes

    def _jeton(self, genre, cle, t):
        for j in [j for j, (_, _, fin) in self.confirmations.items() if fin <= t]:
            del self.confirmations[j]
        jeton = secrets.token_hex(8)
        self.confirmations[jeton] = (genre, cle, t + D.DELAI_CONFIRMATION_S)
        return jeton

    def _jeton_valable(self, jeton, genre, cle, t):
        info = self.confirmations.get(str(jeton or ''))
        if info is None or info[0] != genre or info[1] != cle or info[2] <= t:
            return False
        del self.confirmations[jeton]
        return True

    def posture(self, fsm, portique=False, jeton=None):
        """Posture 7101 (500, 706, 702, 3 ; 1 et 0 avec la confirmation double « portique »)."""
        t = self.maintenant()
        if isinstance(fsm, bool) or not isinstance(fsm, int):
            return refus(400, 'posture : « fsm » doit être un nombre entier (500, 706, 702, 3, 1 '
                              'ou 0).')
        raison = D.refus_commande('sport', 7101, {'data': fsm})
        if raison is None and fsm not in D.POSTURES:
            raison = f'{fsm} n\'est pas une posture : les danses passent par « Danses du robot »'
        if raison is not None:
            return refus(403, f'Posture refusée : {raison}.')
        for verif in (self._sans_main('Posture'), self._occupe('Posture')):
            if verif is not None:
                return verif
        if D.confirmation_requise('sport', 7101, {'data': fsm}) == 'portique':
            if not portique:
                return refus(428, 'Cochez d\'abord « robot au portique » : le robot va '
                                  's\'affaisser '
                                  '(ou relâcher ses moteurs) s\'il n\'est pas '
                                  'tenu.', confirmation='portique')
            if not self._jeton_valable(jeton, 'portique', ('posture', fsm), t):
                nouveau = self._jeton('portique', ('posture', fsm), t)
                detail = ('Confirmez une seconde fois dans les 10 s : le robot est-il bien tenu '
                          'au portique ?'
                          if not jeton else 'Confirmation expirée ou inconnue : confirmez de '
                                            'nouveau dans les 10 s.')
                return refus(428, detail, confirmation='portique', jeton=nouveau,
                             expire_s=D.DELAI_CONFIRMATION_S)
        sorties = []
        if self.marche:
            sorties.append(self._stop_move('posture'))
        envoi = self._envoi('sport', 7101, D.parametre_fsm(fsm), 'posture')
        sorties.append(envoi)
        self.t_posture = t
        self.message = f'Posture demandée : {D.POSTURES[fsm]}.'
        return Resultat(200, {'detail': self.message, 'fsm': fsm}, sorties,
                        attendre=envoi.identifiant)

    def tache(self, tache):
        """Tâche de la marche (sport 7106 SetTaskId : saluer, serrer la main)."""
        if isinstance(tache, bool) or not isinstance(tache, int):
            return refus(400, 'tâche : « tache » doit être un nombre entier (0 à 3).')
        raison = D.refus_commande('sport', 7106, {'data': tache})
        if raison is not None:
            return refus(403, f'Tâche refusée : {raison}.')
        for verif in (self._sans_main('Tâche'), self._occupe('Tâche')):
            if verif is not None:
                return verif
        envoi = self._envoi('sport', 7106, D.parametre_tache(tache), 'tache')
        self.t_geste = self.maintenant()
        self.message = f'Tâche demandée : {D.TACHES_LOCO[tache]}.'
        return Resultat(200, {'detail': self.message}, [envoi], attendre=envoi.identifiant)

    def geste(self, action):
        """Geste d'Unitree (arm 7106). 99 (relâcher) reste permis sans la main."""
        if isinstance(action, bool) or not isinstance(action, int):
            return refus(400, 'geste : « action » doit être un nombre entier.')
        raison = D.refus_commande('arm', 7106, {'action_id': action})
        if raison is not None:
            return refus(403, f'Geste refusé : {raison}.')
        if action != D.GESTE_RELACHER:
            for verif in (self._sans_main('Geste'), self._occupe('Geste')):
                if verif is not None:
                    return verif
        else:
            occupe = self._occupe('Relâcher les bras')       # 99 reste permis sans la main
            if occupe is not None:
                return occupe
        envoi = self._envoi('arm', 7106, D.parametre_geste(action), f'geste:{action}')
        self.t_geste = self.maintenant()
        self.message = f'Geste demandé : {D.GESTES_BRAS[action]}.'
        return Resultat(200, {'detail': self.message, 'action': action}, [envoi],
                        attendre=envoi.identifiant)

    def lister_gestes(self):
        """Demande au robot la liste de ses gestes (arm 7107)."""
        envoi = self._envoi('arm', 7107, '{}', 'liste_gestes')
        return Resultat(200, {}, [envoi], attendre=envoi.identifiant)

    # ---------------------------------------------------- voix, volume, LED (toujours permis)

    def voix(self, texte, voix=0):
        """Parole par la synthèse du robot (voice 1001). Toujours permise."""
        if not isinstance(texte, str):
            return refus(400, 'voix : « texte » doit être un texte.')
        if isinstance(voix, bool) or not isinstance(voix, int):
            return refus(400, 'voix : « voix » doit être un nombre entier (speaker_id).')
        self.tts_index += 1
        parametre = D.parametre_tts(texte, self.tts_index, voix)
        raison = D.refus_commande('voice', 1001, parametre)
        if raison is not None:
            return refus(403, f'Parole refusée : {raison}.')
        envoi = self._envoi('voice', 1001, parametre, 'tts')
        return Resultat(200, {'detail': 'Phrase envoyée au '
                                        'robot.'}, [envoi], attendre=envoi.identifiant)

    def volume(self, volume):
        if isinstance(volume, bool) or not isinstance(volume, int):
            return refus(400, 'volume : un nombre entier de 0 à 100.')
        raison = D.refus_commande('voice', 1006, {'volume': volume})
        if raison is not None:
            return refus(403, f'Volume refusé : {raison}.')
        envoi = self._envoi('voice', 1006, D.parametre_volume(volume), 'volume')
        return Resultat(200, {'detail': f'Volume : {volume} '
                                        '%.'}, [envoi], attendre=envoi.identifiant)

    def led(self, r, g, b):
        if any(isinstance(c, bool) or not isinstance(c, int) for c in (r, g, b)):
            return refus(400, 'LED : r, g et b sont des nombres entiers de 0 à 255.')
        raison = D.refus_commande('voice', 1010, {'R': r, 'G': g, 'B': b})
        if raison is not None:
            return refus(403, f'Couleur refusée : {raison}.')
        envoi = self._envoi('voice', 1010, D.parametre_led(r, g, b), 'led')
        return Resultat(200, {'detail': 'Couleur envoyée.'}, [envoi], attendre=envoi.identifiant)

    # ------------------------------------------------------------ danses du robot

    def lister_danses(self):
        """Demande au robot la liste de ses danses (7100 {"fsm_id": 550, "api_id": 1})."""
        envoi = self._envoi('sport', 7100, D.parametre_liste_danses(), 'liste_danses')
        return Resultat(200, {}, [envoi], attendre=envoi.identifiant)

    def liste_danses(self):
        """La liste lue (pour l'interface), ou None si elle n'a pas encore été lue."""
        if self.danses is None:
            return None
        return D.danses_pour_l_interface(self.danses)

    def _debout_immobile(self, quoi, t):
        if self.fsm is None or self.t_fsm is None or t - self.t_fsm > 3.0:
            return refus(409, f'{quoi} : mode du robot inconnu (il ne répond pas à 7001) : '
                              'vérifiez la liaison.')
        if self.fsm != D.FSM_MARCHE:
            return refus(409, f'{quoi} : le robot doit être debout en mode marche (801), il est '
                              'en mode '
                              f'{self.fsm}. Utilisez la posture « Démarrer ».', fsm=self.fsm)
        if self.marche or (self.t_mouvement is not None and t - self.t_mouvement < 1.0):
            return refus(409, f'{quoi} : le robot doit être immobile ; lâchez le joystick et '
                              'attendez 1 s.')
        return None

    def danser(self, n, zone_libre=False):
        """Danse du robot n (7101 550000 + n), avec la confirmation « zone libre »."""
        t = self.maintenant()
        if isinstance(n, bool) or not isinstance(n, int) or not 0 < n < 1000:
            return refus(400, 'danse : « id » doit être un numéro de danse (ex. 604).')
        if D.danse_interdite(n):
            return refus(403, f'La danse {n} est interdite : le robot peut se coucher par '
                              'terre.', interdite=True)
        raison = D.refus_commande('sport', 7101, {'data': D.DANSE_PREFIXE + n})
        if raison is not None:
            return refus(403, f'Danse refusée : {raison}.')
        for verif in (self._sans_main('Danse'), self._occupe('Danse')):
            if verif is not None:
                return verif
        if self.danses is None:
            return refus(409, 'Lisez d\'abord la liste des danses du robot (bouton « Lire la '
                              'liste »).')
        if n not in self.danses:
            return refus(403, f'La danse {n} n\'est pas dans la liste du robot : refusée.')
        if not zone_libre:
            return refus(428, D.TEXTES_CONFIRMATION['zone_libre'], confirmation='zone_libre')
        verif = self._debout_immobile('Danse', t)
        if verif is not None:
            return verif
        envoi = self._envoi('sport', 7101, D.parametre_fsm(D.DANSE_PREFIXE + n), 'danse')
        info = self.danses[n]
        duree = info.get('duree_s')
        mur = self.mur()
        self.danse = {'id': n, 'nom': info.get('nom', ''), 'debut': t, 'debut_mur': round(mur, 3),
                      'debut_iso': heure_iso(mur), 'duree_s': duree, 'envoi': envoi.identifiant,
                      'vu_ailleurs': False}
        self.message = (f'Danse {n} ({info.get("nom") or "sans nom"}) : la télécommande reste '
                        'l\'arrêt d\'urgence.')
        return Resultat(200, {'detail': self.message, 'danse': n, 'duree_s': duree}, [envoi],
                        attendre=envoi.identifiant)

    def _suivre_danse(self, t):
        """Fin de la danse : retour en 801 après sa durée ; refusée par le robot : oubliée."""
        d = self.danse
        reponse = self.reponses.get(d['envoi'])
        if reponse is not None and reponse[0] != 0:
            self.danse = None
            self.message = f'Le robot a refusé la danse : {D.message_refus(reponse[0])}'
            return
        if self.fsm is not None and self.t_fsm is not None and self.t_fsm > d['debut'] + 0.5 \
                and self.fsm != D.FSM_MARCHE:
            # le robot a quitté 801 : la danse a commencé
            d['vu_ailleurs'] = True
        duree = d['duree_s'] if d['duree_s'] is not None else D.DUREE_DANSE_INCONNUE_S
        ecoule = t - d['debut']
        revenu = (self.fsm == D.FSM_MARCHE and self.t_fsm is not None
                  and self.t_fsm > d['debut'] + 1.0)
        if revenu and (ecoule >= duree or (d['vu_ailleurs'] and d['duree_s'] is None)):
            self.danse = None
            self.message = 'Danse finie : le robot est revenu en mode marche (801).'
        elif ecoule >= duree + FIN_DANSE_MARGE_S:
            self.danse = None
            self.message = (f'Danse supposée finie ({duree + FIN_DANSE_MARGE_S:.0f} s) : le robot '
                            'n\'est pas '
                            f'revenu en 801 (mode {self.fsm}). Vérifiez-le avant de continuer.')

    # ------------------------------------------------------------ chorégraphies

    def jouer(self, d, zone_libre=False, vitesse=1.0):
        """
        Joue une chorégraphie vérifiée : bras par rt/arm_sdk, pas, LED, gestes et paroles.

        vitesse : vitesse de lecture, de 0,25 à 1 (0,5 : tout deux fois plus lent, bras, pas
        et musique ; les premiers essais sur le robot se font ainsi). Jamais plus vite.
        """
        t = self.maintenant()
        if not nombre_fini(vitesse) or not VITESSES_LECTURE[0] <= vitesse <= VITESSES_LECTURE[1]:
            bas, haut = VITESSES_LECTURE
            return refus(400, f'vitesse de lecture {vitesse} : de {bas} (quatre fois plus lent) à '
                              f'{haut} (comme prévu), jamais plus vite.')
        if not isinstance(d, dict):
            return refus(400, 'chorégraphie : il faut un objet JSON (le contenu du fichier '
                              '.choregraphie.yaml).')
        erreurs = D.verifier_choregraphie(d)
        if erreurs:
            return refus(422, 'Chorégraphie refusée avant de jouer : corrigez les points '
                              'ci-dessous.',
                         erreurs=erreurs)
        for verif in (self._sans_main('Chorégraphie'), self._occupe('Chorégraphie')):
            if verif is not None:
                return verif
        if not zone_libre:
            return refus(428, D.TEXTES_CONFIRMATION['zone_libre'] + ' (zone de '
                                                                    f'{d["zone_libre_m"]:g} m)',
                         confirmation='zone_libre')
        verif = self._debout_immobile('Chorégraphie', t)
        if verif is not None:
            return verif
        bras = bool((d.get('bras') or {}).get('poses'))
        if bras and self.bras_tenus:
            return refus(409, 'Les bras tiennent encore un geste : relâchez-les (geste 99) avant '
                              'la chorégraphie.')
        q_taille = {}
        if bras:
            if self.lowstate is None or t - self.lowstate[1] > LOWSTATE_FRAIS_S:
                return refus(409, 'Le robot ne publie pas ses angles (/lowstate) : impossible de '
                                  'tenir la taille, '
                                  'la chorégraphie des bras est refusée.')
            angles = self.lowstate[0]
            q_taille = {i: float(angles[i]) for i in D.ARTICULATIONS_TAILLE.values()}
        avertissements = []
        if (d.get('musique') or {}).get('sortie') == 'robot':
            avertissements.append('Musique par le haut-parleur du robot (1003) : pas encore prise '
                                  'en charge '
                                  '(à vérifier sur le robot) ; elle est jouée par la page.')
        debut_mur = round(self.mur() + DELAI_DEPART_S, 3)
        self.lecture = Lecture(d, t + DELAI_DEPART_S, debut_mur, q_taille, self.limites_pas,
                               vitesse)
        self.message = f'Chorégraphie « {d["nom"]} » : départ dans {DELAI_DEPART_S:g} s.'
        return Resultat(200, {'detail': self.message, 'debut_mur': debut_mur,
                              'duree_s': d['duree_s'], 'vitesse': float(vitesse),
                              'avertissements': avertissements})

    def _ordre_bras(self, lec, poids, q, t):
        """Bras de la chorégraphie, bornés une seconde fois : limites, vitesse, rampe du poids."""
        # Écart permis d'un ordre au suivant : celui d'un pas de 20 ms au plus, même après un
        # retard du fil (les bras rattrapent la ligne de temps à la vitesse maximale, sans saut)
        dt = PERIODE_PAS_BRAS_S
        if lec.t_bras is not None:
            dt = max(1e-3, min(PERIODE_PAS_BRAS_S, t - lec.t_bras))
        pas_poids = dt / D.RAMPE_MIN_S + TOLERANCE_POIDS
        poids = max(0.0, min(1.0, poids, lec.poids + pas_poids))
        poids = max(poids, lec.poids - pas_poids)
        commande = {}
        for nom, indice in D.ARTICULATIONS_BRAS.items():
            bas, haut = D.LIMITES_BRAS[nom]
            v = max(bas, min(haut, q[nom]))
            if indice in lec.q:
                ecart = D.VITESSE_BRAS_MAX * dt
                v = max(lec.q[indice] - ecart, min(lec.q[indice] + ecart, v))
            commande[indice] = v
        lec.poids, lec.q, lec.t_bras = poids, dict(commande), t
        return self._bras(poids, commande, lec.q_taille)

    @staticmethod
    def _bras(poids, q_bras, q_taille):
        q, kp, kd = dict(q_bras), {}, {}
        for indice in q_bras:
            kp[indice], kd[indice] = D.GAINS_BRAS['kp'], D.GAINS_BRAS['kd']
        for indice, v in q_taille.items():
            q[indice] = v
            kp[indice], kd[indice] = D.GAINS_TAILLE['kp'], D.GAINS_TAILLE['kd']
        return Bras(float(poids), q, kp, kd)

    def _pas_lecture(self, t):
        lec = self.lecture
        te = (t - lec.t0) * lec.vitesse              # temps de la chorégraphie
        sorties = []
        if te < 0:
            return sorties
        fini = te >= lec.d['duree_s']
        te_ev = min(te, lec.d['duree_s'])
        evenements = lec.evenements
        while lec.prochain < len(evenements) and evenements[lec.prochain][0] <= te_ev + 1e-9:
            _, genre, e = lec.evenements[lec.prochain]
            lec.prochain += 1
            sorties += self._evenement(lec, genre, e, t)
        if lec.pas is not None and not fini and t - lec.t_dernier_pas >= PERIODE_PAS_S - 0.005:
            sorties.append(self._envoi_pas(lec, t, te))
        if lec.bras:
            poids, q = D.poses_bras(lec.d, te_ev)
            sorties.append(self._ordre_bras(lec, 0.0 if fini else poids, q, t))
        if fini:
            if lec.pas is not None:
                sorties.append(self._stop_move('fin_choregraphie'))
                lec.pas = None
            self.lecture = None
            if lec.bras and lec.poids > TOLERANCE_POIDS:
                self.descente = {'t0': t, 'poids0': lec.poids, 'q': dict(lec.q),
                                 'q_taille': lec.q_taille,
                                 'id': lec.d['id']}
            self.message = f'Chorégraphie « {lec.d["nom"]} » finie.'
        return sorties

    def _envoi_pas(self, lec, t, te):
        p = lec.pas
        reste = (lec.fin_pas - te) / lec.vitesse        # secondes réelles jusqu'à la fin du pas
        duree = max(0.05, min(D.DUREE_ORDRE_S, reste))
        vx, vy, wz = (max(-lec.limites_pas[a], min(lec.limites_pas[a], float(p[a]) * lec.vitesse))
                      for a in ('vx', 'vy', 'wz'))
        lec.t_dernier_pas = t
        self.t_mouvement = t
        return self._envoi('sport', 7105, D.parametre_vitesse(vx, vy, wz, duree), 'pas')

    def _evenement(self, lec, genre, e, t):
        if genre == 'pas_debut':
            lec.pas, lec.fin_pas = e, e['t'] + e['duree_s']
            return [self._envoi_pas(lec, t, e['t'])]
        if genre == 'pas_fin':
            if lec.pas is not e:
                return []
            lec.pas = None
            fin = e['t'] + e['duree_s']
            if any(abs(p['t'] - fin) < 1e-6 for p in lec.d.get('pas') or []):
                return []                     # un pas suit aussitôt : pas d'arrêt entre les deux
            return [self._stop_move('fin_pas')]
        if genre == 'led':
            return [self._envoi('voice', 1010, D.parametre_led(e['r'], e['g'], e['b']),
                                'led_choregraphie')]
        if genre == 'geste':
            return [self._envoi('arm', 7106, D.parametre_geste(e['action']),
                                f'geste:{e["action"]}')]
        if genre == 'parole':
            if e.get('voix') == 'unitree':
                self.tts_index += 1
                return [self._envoi('voice', 1001, D.parametre_tts(e['texte'], self.tts_index, 0),
                                    'tts')]
            return [Dire({'version': 1, 'texte': e['texte'], 'source': 'choregraphie',
                          'langue': 'fr'})]
        return []

    def _poids_descente(self, t):
        d = self.descente
        return max(0.0, d['poids0'] * (1.0 - (t - d['t0']) / D.ARRET_BRAS_S))

    def _pas_descente(self, t):
        d = self.descente
        poids = self._poids_descente(t)
        sorties = [self._bras(poids, d['q'], d['q_taille'])]
        if poids <= TOLERANCE_POIDS:
            self.descente = None
        return sorties

    # ------------------------------------------------------------ ARRÊT

    def arret(self, par='atelier'):
        """ARRÊT : toujours permis, quel que soit le maître."""
        t = self.maintenant()
        self.t_arret = t
        if self.danse is not None:
            # aucun ordre connu n'interrompt une danse : StopMove seulement (à vérifier)
            self.message = ('ARRÊT envoyé (StopMove) : une danse du robot ne s\'interrompt pas, '
                            'la télécommande '
                            'reste l\'arrêt d\'urgence.')
            return Resultat(200, {'detail': self.message, 'danse': True},
                            [self._stop_move('arret_danse')])
        sorties = [self._stop_move('arret')]
        if self.lecture is not None:
            lec = self.lecture
            self.lecture = None
            if lec.bras and lec.poids > TOLERANCE_POIDS:
                self.descente = {'t0': t, 'poids0': lec.poids, 'q': dict(lec.q),
                                 'q_taille': lec.q_taille,
                                 'id': lec.d['id']}
        if self.bras_tenus or (self.t_geste is not None and t - self.t_geste < DUREE_GESTE_S):
            sorties.append(self._envoi('arm', 7106, D.parametre_geste(D.GESTE_RELACHER),
                                       f'geste:{D.GESTE_RELACHER}'))
        sorties.append(ArretGuide(f'ARRÊT ({par})'))
        self.message = 'ARRÊT : robot arrêté.'
        return Resultat(200, {'detail': self.message}, sorties)

    # ---------------------------------------------------- requête générale (mode avancé)

    def requete(self, service, api_id, donnees=None, portique=False, jeton=None, zone_libre=False):
        """Une requête quelconque : passe par les mêmes règles que les boutons de l'onglet."""
        if isinstance(api_id, bool) or not isinstance(api_id, int):
            return refus(400, 'requête : « api_id » doit être un nombre entier.')
        donnees = {} if donnees is None else donnees
        raison = D.refus_commande(str(service), api_id, donnees)
        if raison is not None:
            return refus(403, f'Requête refusée : {raison}.')
        d = json.loads(donnees) if isinstance(donnees, str) else dict(donnees)
        if service == 'sport' and api_id == 7101:
            fsm = d['data']
            if D.DANSE_PREFIXE < fsm < D.DANSE_PREFIXE + 1000:
                return self.danser(fsm - D.DANSE_PREFIXE, zone_libre)
            return self.posture(fsm, portique, jeton)
        if service == 'sport' and api_id == 7105:
            if not self.a_la_main():
                return self._sans_main('Marche')
            occupe = self._occupe('Marche')
            if occupe is not None:
                return occupe
            v = d['velocity']
            if all(abs(x) < 1e-9 for x in v):
                return Resultat(200, {'detail': 'StopMove envoyé.'}, [self._stop_move('requete')])
            self.t_mouvement = self.maintenant()
            envoi = self._envoi('sport', 7105, D.parametre_vitesse(*v, d['duration']), 'requete')
            return Resultat(200, {'detail': 'Ordre de marche '
                                            'envoyé.'}, [envoi], attendre=envoi.identifiant)
        if service == 'sport' and api_id == 7106:
            return self.tache(d['data'])
        if service == 'sport' and api_id == 7100:
            return self.lister_danses()
        if service == 'arm' and api_id == 7106:
            return self.geste(d.get('action_id', d.get('data')))
        if service == 'arm' and api_id == 7108:
            for verif in (self._sans_main('Geste appris'), self._occupe('Geste appris')):
                if verif is not None:
                    return verif
        if service == 'voice' and api_id == 1001:
            return self.voix(d['text'], d.get('speaker_id', 0))
        envoi = self._envoi(str(service), api_id, json.dumps(d, ensure_ascii=False), 'requete')
        return Resultat(200, {'detail': 'Requête envoyée.'}, [envoi], attendre=envoi.identifiant)

    # ------------------------------------------------------------ pas régulier (50 Hz)

    def pas(self, t=None):
        """
        À appeler 50 fois par seconde : homme mort, lecture du mode, danse, chorégraphie.

        t : instant planifié du pas (le fil à 50 Hz du nœud le donne, à pas réguliers de 20 ms,
        même s'il prend du retard) ; défaut : maintenant. Les bras avancent donc d'un pas régulier
        de la ligne de temps à chaque ordre : leur vitesse reste celle prévue, même avec de la
        gigue.
        """
        t = self.maintenant() if t is None else float(t)
        sorties = []
        if self.marche and self.t_ordre is not None and t - self.t_ordre >= D.DELAI_HOMME_MORT_S:
            self.message = 'Plus d\'ordre du joystick depuis 0,5 s : robot arrêté (homme mort).'
            sorties.append(self._stop_move('homme_mort'))
        elif self.marche and self.ordre_en_attente and t - self.t_7105 >= ECART_MIN_7105_S:
            sorties.append(self._envoi_marche(t))
        if self.t_lecture_fsm is None or t - self.t_lecture_fsm >= PERIODE_FSM_S:
            self.t_lecture_fsm = t
            sorties.append(self._envoi('sport', 7001, '{}', 'lecture_fsm'))
        if self.danse is not None:
            self._suivre_danse(t)
        if self.lecture is not None:
            sorties += self._pas_lecture(t)
        elif self.descente is not None:
            sorties += self._pas_descente(t)
        return sorties

    def quitter(self):
        """À la sortie : StopMove, le guide reprend la main (bras redescendus avant)."""
        sorties = [self._stop_move('sortie')]
        if self.a_la_main():
            self.maitre = self._message_maitre('guide', 'arrêt du nœud pilotage',
                                               'Le nœud pilotage s\'est arrêté : le guide a la '
                                               'main.')
            sorties.append(Maitre(dict(self.maitre)))
        return sorties

    def bras_actifs(self):
        """Vrai tant qu'il faut publier sur /arm_sdk (chorégraphie ou descente du poids)."""
        return (self.lecture is not None and self.lecture.bras) or self.descente is not None

    def arreter_bras(self):
        """Avant de quitter : chorégraphie arrêtée, descente du poids des bras commencée."""
        if self.lecture is not None:
            lec, self.lecture = self.lecture, None
            if lec.bras and lec.poids > TOLERANCE_POIDS:
                self.descente = {'t0': self.maintenant(), 'poids0': lec.poids, 'q': dict(lec.q),
                                 'q_taille': lec.q_taille, 'id': lec.d['id']}


PERIODE_PAS_BRAS_S = 1.0 / D.FREQUENCE_BRAS_HZ
D_COMPORTEMENT_EN_MISSION = ('en_route', 'retour', 'bloque', 'detour', 'attente_passage',
                             'attente_visiteur', 'perdu')
try:
    from atelier.lieu.comportement import ETATS_EN_MISSION as _EN_MISSION
    D_COMPORTEMENT_EN_MISSION = tuple(_EN_MISSION)
# atelier.lieu absent (ne devrait pas arriver : contrat.charger l'a trouvé)
except ImportError:
    pass


def nombre_fini(v):
    """Vrai pour un nombre fini (pas un booléen)."""
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
