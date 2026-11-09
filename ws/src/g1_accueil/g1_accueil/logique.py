"""
La machine d'états de la démo d'accueil, sans ROS (vague 6, section 13.4 du plan).

Un visiteur s'approche du robot (ou touche la borne), le robot le salue, le visiteur choisit une
salle, le robot l'y accompagne (le guide de la vague 4 conduit), annonce l'arrivée, revient seul à
l'accueil, puis attend le visiteur suivant. Après un arrêt, un blocage ou une panne, la démo se met
en PAUSE et ne repart jamais seule (règle de la vague 5, section 12.15) : il faut « Reprendre »
(robot à l'accueil, plus rien n'empêche), ou « Ramener à l'accueil » (une demande explicite).

Testée à fausse horloge, comme le guide (g1_nav/guide.py). Chaque entrée rend la liste des
messages à publier, des couples (sujet, données) :
  ('/guide/aller', {...})        demande_guide, source « accueil » (jamais pendant une pause) ;
  ('/guide/stop', None)          pause demandée pendant une visite de la démo ;
  ('/robot/dire', {...})         robot_dire (salutation, « Je vous accompagne à … », pause en
                                 priorité securite, événements du guide relayés) ;
  ('/robot/geste', {...})        robot_geste (le geste de salut de la personnalité) ;
  ('/accueil/evenement', {...})  evenement_demo (réponse à chaque choix et à chaque commande) ;
  ('/accueil/etat', {...})       etat_demo, à chaque changement (le nœud le publie aussi 2 fois
                                 par seconde).
Entrées : entrer(sujet, donnees, t) pour chaque message reçu (SUJETS_ENTREE), et pas(t) pour les
délais ; etat(t) rend le message de /accueil/etat (schéma etat_demo).
"""
import math
import time

from atelier.equipe.relais import Relais
from atelier.lieu.accueil import (DELAI_ETAT_PERIME_S, ECRAN_DE_L_ETAT, ETATS_CHOIX_POSSIBLE,
                                  maintenant_iso, refus_choix, REGLAGES_DEMO, TEXTES_BORNE)
from atelier.lieu.comportement import ETATS_EN_MISSION, texte_evenement
from atelier.lieu.equipe import message_robot_dire, message_robot_geste

# Délais propres à la logique (s)
DELAI_GUIDE_MUET_S = DELAI_ETAT_PERIME_S    # /guide/etat muet depuis ce temps : pause guide_absent
DUREE_SALUTATION_S = 1.0                    # la salutation dite, la borne montre les salles
DELAI_RAISON_S = 0.8                        # blocage vu en visite : le guide dit pourquoi
DELAI_PONT_ABSENT_S = 3.0                   # pont déjà vu, muet depuis ce temps : pont_absent
POSE_FRAICHE_S = 2.0                        # position du robot plus vieille : inconnue
PERSONNES_FRAICHES_S = 1.0                  # message du détecteur plus vieux : personne en vue
CAMERA_FRAICHE_S = 3.0                      # source auto : la caméra, si elle a publié depuis
DELAI_REPOS_S = 1.0                         # guide au repos en visite, sans raison : arrêté
DELAI_OCCUPE_DIT_S = 30.0                   # « Je suis occupé… » pas plus souvent que cela
ANGLE_DEVANT_RAD = math.pi / 4              # un visiteur est devant le robot : |angle| < 45°

SUJETS_ENTREE = ('/guide/etat', '/guide/evenement', '/pont/etat', '/pont/arret',
                 '/mouvement/maitre', '/visiteurs/detectes', '/personnes/lidar',
                 '/personnalite/active', '/accueil/choix', '/accueil/commande', 'position')
ETATS_VISITE_DEMO = ('depart', 'accompagnement', 'arrivee', 'retour')   # le robot bouge (démo)
REPOS_GUIDE = ('attente', 'arrive', 'echec')
ETATS_BLOQUANTS_PONT = ('verrou', 'pas_en_marche', 'pont_absent')

SOURCES = ('borne', 'dialogue', 'atelier', 'operateur', 'test')   # SOURCES_ACCUEIL
NOTE_LOIN = 'Le robot n\'est pas à l\'accueil : cliquez sur « Ramener à l\'accueil ».'
SALUTATION_DEFAUT = "Bonjour ! Choisissez une salle sur l'écran : je vous y accompagne."
PHRASE_DEPART = 'Je vous accompagne à {nom}. Suivez-moi !'
PHRASE_PAUSE = 'Je fais une petite pause.'
PHRASE_OCCUPE = 'Je suis occupé, je reviens dans un instant !'

MESSAGES_ETAT = {
    'demarrage': 'La démo démarre : elle attend le guide et le robot à l\'accueil.',
    'attente': 'Le robot attend un visiteur à l\'accueil.',
    'salutation': 'Un visiteur est là : le robot le salue.',
    'choix': 'Le visiteur choisit une salle sur la borne.',
    'depart': 'Départ vers « {nom} » demandé au guide.',
    'accompagnement': 'Visite vers « {nom} » : le robot accompagne le visiteur.',
    'arrivee': 'Arrivé à « {nom} » : le robot retournera seul à l\'accueil.',
    'retour': 'Le robot retourne à l\'accueil.',
    'occupe': 'Le guide fait une visite demandée hors de la démo : la démo attend son retour.',
}
MESSAGES_PAUSE = {
    'arret': 'Pause : arrêt demandé pendant la visite.',
    'verrou': 'Pause : le robot est bloqué.',
    'pas_en_marche': 'Pause : le robot n\'est pas en mode marche.',
    'robot_muet': 'Pause : le robot ne répond plus aux ordres de marche.',
    'refus': 'Pause : le robot refuse de marcher.',
    'pont_absent': 'Pause : plus de nouvelles du pont vers la marche.',
    'echec': 'Pause : la visite a échoué.',
    'perdu': 'Pause : le robot s\'est perdu pendant la visite.',
    'pilotage': 'Pause : le robot est piloté à la main.',
    'guide_absent': 'Pause : le guide ne répond plus (la navigation tourne-t-elle ?).',
    'operateur': 'Pause demandée par l\'opérateur.',
}
# Ce qui empêche encore de reprendre (texte des refus de « Reprendre » et « Ramener »)
EMPECHEMENTS = {
    'verrou': 'Le robot est encore bloqué : cliquez d\'abord sur « Débloquer ».',
    'pas_en_marche': 'Le robot n\'est pas en mode marche : remettez-le en marche d\'abord.',
    'pont_absent': 'Le pont vers la marche ne répond plus : relancez la navigation d\'abord.',
    'pilotage': 'Le robot est piloté à la main : rendez la main dans Piloter d\'abord.',
    'guide_absent': 'Le guide ne répond plus : relancez la navigation d\'abord.',
    'robot_muet': 'Le robot ne répond plus aux ordres de marche : vérifiez-le d\'abord.',
    'refus': 'Le robot refuse de marcher : vérifiez son mode d\'abord.',
    'occupe': 'Le guide est encore en route : attendez qu\'il s\'arrête.',
    'position': 'La position du robot est inconnue : repérez-le d\'abord.',
}
TEXTES_REFUS = {
    'occupe': 'Je suis occupé : la visite en cours doit d\'abord finir.',
    'pause': 'La démo est en pause.',
    'demo_arretee': 'La démo ne tourne pas.',
    'action_impossible': 'Ce n\'est pas possible maintenant.',
}


def _nombre(v):
    """Un nombre fini, ou None."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v) if math.isfinite(v) else None


def _salle_dict(s):
    """Salle de salles.yaml (objet Salle ou dict) en dict {id, nom, etage, etiquettes, pose}."""
    if isinstance(s, dict):
        pose = s.get('pose') or {}
        return {'id': s.get('id'), 'nom': s.get('nom') or s.get('id'), 'etage': s.get('etage'),
                'etiquettes': list(s.get('etiquettes') or []),
                'pose': (pose.get('x'), pose.get('y'), pose.get('theta'))}
    pose = getattr(s, 'pose', None)
    return {'id': s.id, 'nom': getattr(s, 'nom', None) or s.id, 'etage': getattr(s, 'etage', None),
            'etiquettes': list(getattr(s, 'etiquettes', None) or []),
            'pose': (pose.x, pose.y, pose.theta) if pose is not None else (None, None, None)}


class Orchestrateur:
    """Machine d'états de la démo d'accueil (section 13.4 du plan), sans ROS."""

    def __init__(self, salles, id_principal, etage, reglages=None, horloge=None, lieu='demo',
                 pose_principale=None, personnalite=None, personnalites=None,
                 suivre_personnalite=True):
        """
        Prépare la démo.

        salles          : les salles du lieu (objets Salle ou dicts de salles.yaml) ;
        id_principal    : id du point principal (salle portant l'étiquette principal) ;
        etage           : étage de la démo ;
        reglages        : REGLAGES_DEMO complétés (demo.yaml, paramètres du nœud) ;
        horloge         : temps en secondes (fausse horloge des tests), défaut time.monotonic ;
        lieu            : id du lieu (champ lieu de /accueil/etat) ;
        pose_principale : (x, y, theta) du point principal, sinon celle de sa salle ;
        personnalite    : dict de la personnalité (salutation, phrases, geste_salut), ou None ;
        personnalites   : celles de personnalites.yaml (pour compléter un /personnalite/active
                          réduit à {id, nom}) ;
        suivre_personnalite : faux si demo.yaml impose sa personnalité (/personnalite/active
                          ignoré).
        """
        self.salles = [_salle_dict(s) for s in salles]
        self.par_id = {s['id']: s for s in self.salles}
        self.id_principal = id_principal
        self.etage = etage
        self.lieu = lieu
        self.reglages = dict(REGLAGES_DEMO, **{k: v for k, v in (reglages or {}).items()
                                               if v is not None})
        self.horloge = horloge or time.monotonic
        if pose_principale is None and id_principal in self.par_id:
            pose_principale = self.par_id[id_principal]['pose']
        self.pose_principale = pose_principale
        self.personnalite = personnalite
        self.personnalites = {p.get('id'): p for p in (personnalites or []) if isinstance(p, dict)}
        self.suivre_personnalite = bool(suivre_personnalite)
        t = self.horloge()
        self._t = t
        self._relais = Relais(horloge=lambda: self._t)
        self._etat = 'demarrage'
        self._depuis = t
        self._debut = t
        self._raison = None
        self._note = None                # précision du message (pause, robot loin de l'accueil)
        self._visite = None              # la visite en cours (ou la dernière, pendant le retour)
        self._demande = None             # {cible, id, t} : dernière demande au guide de la démo
        self._abandon = False            # visiteur perdu : le guide rentre seul
        self._guide = None
        self._t_guide = None
        self._guide_perdu = False        # dernier état du guide vu : perdu
        self._repos_depuis = None        # le guide au repos pendant une visite, depuis
        self._pont = None
        self._t_pont = None
        self._verrou = False             # dernier /pont/arret
        self._maitre = 'guide'
        self._pose = None
        self._t_pose = None
        self._retour_vu = False          # le guide a dit qu'il était de retour au principal
        self._detections = {}            # source → (message, instant)
        self._presents = {'camera': {}, 'lidar': {}}    # source → {id: instant où il est entré}
        self._detection_permise = t
        self._attendre_absence = False
        self._cause_vue = None           # (raison, instant) : blocage vu par la démo en visite
        self._dernier_occupe_dit = None
        self._numero = 0
        self._stats = self._statistiques_neuves()
        self._signature = None
        self._sorties = []
        self.pauses_vues = []            # (raison, instant) de chaque pause (essais)
        self.demandes_guide = []         # chaque /guide/aller envoyé (essais)
        self._entrees = {
            '/guide/etat': self._sur_guide, '/guide/evenement': self._sur_evenement,
            '/pont/etat': self._sur_pont, '/pont/arret': self._sur_verrou,
            '/mouvement/maitre': self._sur_maitre, '/visiteurs/detectes': self._sur_camera,
            '/personnes/lidar': self._sur_lidar, '/personnalite/active': self._sur_personnalite,
            '/accueil/choix': self._sur_choix, '/accueil/commande': self._sur_commande,
            'position': self._sur_position,
        }

    # ------------------------------------------------------------ interface

    def entrer(self, sujet, donnees, t=None):
        """Un message reçu sur un sujet d'entrée ; rend les messages à publier."""
        self._commencer(t)
        traiter = self._entrees.get(sujet)
        if traiter is not None:
            traiter(donnees)
        self._evaluer()
        return self._finir()

    def pas(self, t=None):
        """Délais (choix, départ, guide muet, pont absent) ; rend les messages à publier."""
        self._commencer(t)
        self._evaluer()
        return self._finir()

    def etat(self, t=None):
        """Rend l'état de la démo, le message de /accueil/etat : schéma etat_demo."""
        if t is not None:
            self._t = t
        t = self._t
        etat = self._etat
        message = self._message()
        visite = None
        if self._visite is not None and etat in ETATS_VISITE_DEMO + ('pause', 'occupe'):
            v = self._visite
            visite = {'id': v['id'], 'salle': v['salle'], 'nom': v['nom'], 'source': v['source'],
                      'debut': v['debut'], 'reste_m': self._reste(),
                      'accompagner': v['accompagner']}
            if v.get('resultat'):
                visite['resultat'] = v['resultat']
        guide = None
        if self._guide is not None:
            g = self._guide
            guide = {'etat': str(g.get('etat')), 'mission': g.get('mission'),
                     'cible': g.get('cible'), 'age_s': round(max(0.0, t - self._t_guide), 1)}
            if g.get('immobilise'):
                guide['immobilise'] = g['immobilise']
        texte_borne = TEXTES_BORNE[ECRAN_DE_L_ETAT[etat]]
        return {
            'version': 1, 'etat': etat, 'depuis_s': round(max(0.0, t - self._depuis), 1),
            'lieu': self.lieu, 'etage': self.etage, 'message': message[:300],
            'texte_borne': texte_borne, 'raison': self._raison if etat == 'pause' else None,
            'visite': visite, 'visiteur': self._visiteur_vu(), 'guide': guide,
            'au_principal': self._au_principal(), 'reprise_possible': self._reprise_possible(),
            'actions_possibles': self._actions_possibles(),
            'source_visiteurs': self.reglages['source_visiteurs'],
            'personnalite': (self.personnalite or {}).get('id'),
            'statistiques': self._statistiques(), 'temps': maintenant_iso(),
        }

    def changer_salles(self, salles):
        """Les salles du lieu ont changé (salles.yaml relu) : salles cachées, noms."""
        self.salles = [_salle_dict(s) for s in salles]
        self.par_id = {s['id']: s for s in self.salles}

    @property
    def etat_courant(self):
        """Nom de l'état de la démo (ETATS_DEMO)."""
        return self._etat

    @property
    def raison(self):
        """Raison de la pause (RAISONS_PAUSE), ou None hors pause."""
        return self._raison if self._etat == 'pause' else None

    # ------------------------------------------------------------ cycle d'une entrée

    def _commencer(self, t):
        self._t = self.horloge() if t is None else float(t)
        self._sorties = []

    def _finir(self):
        etat = self.etat()
        signature = (etat['etat'], etat['raison'], (etat['visite'] or {}).get('id'),
                     etat['au_principal'], etat['reprise_possible'],
                     tuple(etat['actions_possibles']), etat['message'],
                     tuple(sorted(etat['statistiques'].items())))
        if signature != self._signature:
            self._signature = signature
            self._sorties.append(('/accueil/etat', etat))
        sorties, self._sorties = self._sorties, []
        return sorties

    def _publier(self, sujet, donnees):
        self._sorties.append((sujet, donnees))

    def _evenement(self, code, texte, **champs):
        message = {'version': 1, 'code': code, 'texte': str(texte)[:300],
                   'temps': maintenant_iso()}
        message.update({k: v for k, v in champs.items() if v is not None})
        self._publier('/accueil/evenement', message)
        return message

    def _dire(self, texte, ident, priorite='normale'):
        message = message_robot_dire(texte, 'accueil', priorite=priorite,
                                     personnalite=self.personnalite)
        message['id'] = ident
        self._publier('/robot/dire', message)

    def _changer(self, etat, note=None):
        if etat != self._etat:
            self._etat = etat
            self._depuis = self._t
        self._note = note
        if etat != 'pause':
            self._raison = None

    def _nouvel_id(self, prefixe):
        self._numero += 1
        return f'{prefixe}{self._numero}'

    # ------------------------------------------------------------ entrées

    def _sur_guide(self, d):
        if not isinstance(d, dict) or not isinstance(d.get('etat'), str):
            return
        self._guide = d
        self._t_guide = self._t
        if d['etat'] == 'perdu':
            self._guide_perdu = True
        elif d['etat'] != 'echec':
            self._guide_perdu = False
        if self._en_mission():
            self._retour_vu = False
        elif d['etat'] == 'arrive' and d.get('cible') == self.id_principal:
            self._retour_vu = True

    def _sur_evenement(self, d):
        if not isinstance(d, dict) or not isinstance(d.get('code'), str):
            return
        code = d['code']
        if code == 'retour_arrive':
            self._retour_vu = True
        if self.reglages.get('relayer_evenements'):
            message = self._relais.message(d, self.personnalite)
            if message is not None:
                self._publier('/robot/dire', message)
        if self._etat not in ETATS_VISITE_DEMO:
            return
        if code == 'visiteur_perdu' and self._etat in ('depart', 'accompagnement'):
            self._abandonner()
        elif code == 'arret':
            self._pauser('arret')
        elif code == 'immobilise':
            raison = d.get('raison')
            self._pauser(raison if raison in MESSAGES_PAUSE else 'verrou')
        elif code == 'pilotage':
            self._pauser('pilotage')
        elif code == 'echec' and not (self._etat == 'retour' and self._abandon):
            self._pauser('perdu' if self._guide_perdu else 'echec')

    def _sur_pont(self, d):
        if isinstance(d, dict) and isinstance(d.get('etat'), str) and self.reglages['suivre_pont']:
            self._pont = d
            self._t_pont = self._t

    def _sur_verrou(self, d):
        if isinstance(d, dict):
            d = d.get('data')
        if self.reglages['suivre_pont']:
            self._verrou = bool(d)

    def _sur_maitre(self, d):
        if isinstance(d, dict) and d.get('maitre') in ('guide', 'pilotage'):
            self._maitre = d['maitre']

    def _sur_personnalite(self, d):
        if not self.suivre_personnalite or not isinstance(d, dict) or not d.get('id'):
            return
        base = self.personnalites.get(d['id']) or {}
        if (self.personnalite or {}).get('id') == d['id']:
            base = dict(base, **self.personnalite)
        self.personnalite = dict(base, **d)

    def _sur_position(self, d):
        if d is None:
            return
        try:
            x, y, theta = (float(v) for v in d[:3])
        except (TypeError, ValueError):
            return
        if all(math.isfinite(v) for v in (x, y, theta)):
            self._pose = (x, y, theta)
            self._t_pose = self._t

    def _sur_camera(self, d):
        self._sur_personnes('camera', d)

    def _sur_lidar(self, d):
        self._sur_personnes('lidar', d)

    def _sur_personnes(self, source, d):
        if not isinstance(d, dict) or not isinstance(d.get('personnes'), list):
            return
        self._detections[source] = (d, self._t)
        presents = self._presents[source]
        vus = set()
        for p in d['personnes']:
            if self._qualifie(p):
                ident = p.get('id')
                vus.add(ident)
                presents.setdefault(ident, self._t)
        for ident in list(presents):
            if ident not in vus:
                del presents[ident]
        if not vus and source == self._source_visiteurs():
            self._attendre_absence = False

    def _qualifie(self, p):
        """Une personne proche, devant le robot et (si la caméra le dit) tournée vers lui."""
        if not isinstance(p, dict):
            return False
        distance, angle = _nombre(p.get('distance_m')), _nombre(p.get('angle_rad'))
        if distance is None or angle is None:
            return False
        if distance > float(self.reglages['distance_visiteur_m']):
            return False
        if abs(angle) >= ANGLE_DEVANT_RAD:
            return False
        return p.get('regarde_robot', True) is not False

    # ------------------------------------------------------------ ce que la démo voit

    def _guide_frais(self):
        return self._guide is not None and self._t - self._t_guide <= DELAI_GUIDE_MUET_S

    def _en_mission(self):
        """Le guide est en mission (ou partira de lui-même) : ETATS_EN_MISSION ou champ actif."""
        g = self._guide
        if g is None:
            return False
        return g.get('etat') in ETATS_EN_MISSION or g.get('actif') is True

    def _au_repos(self):
        g = self._guide
        return g is not None and g.get('etat') in REPOS_GUIDE and not self._en_mission()

    def _notre_mission(self):
        """La mission du guide est celle que la démo a demandée (visite, ramener ou retour)."""
        g = self._guide
        if g is None or self._demande is None:
            return False
        cible = g.get('cible')
        voulue = self._demande['cible']
        if voulue == 'principal':
            voulue = self.id_principal
        retour = g.get('mission') == 'retour'
        if retour or (g.get('etat') == 'retour' and g.get('mission') is None):
            return self._demande.get('retour', True) or self._abandon
        return cible == voulue

    def _pose_fraiche(self):
        return self._pose is not None and self._t - self._t_pose <= POSE_FRAICHE_S

    def _au_principal(self):
        """
        Le robot est au point principal (à distance_principal_m près).

        Position fraîche : elle décide. Position trop vieille, guide au repos (le robot ne bouge
        pas) : la dernière position. Sans position : le guide a dit qu'il était de retour.
        """
        if self.pose_principale is None or None in tuple(self.pose_principale[:2]):
            return False
        if self._pose is not None and (self._pose_fraiche() or self._au_repos()):
            px, py = float(self.pose_principale[0]), float(self.pose_principale[1])
            return math.hypot(self._pose[0] - px, self._pose[1] - py) \
                <= float(self.reglages['distance_principal_m'])
        return self._retour_vu and self._au_repos()

    def _reste(self):
        g = self._guide
        if g is None or self._visite is None or g.get('cible') != self._visite['salle']:
            return None
        r = _nombre(g.get('reste_m'))
        return None if r is None else round(max(0.0, r), 1)

    def _source_visiteurs(self):
        """camera, lidar, ou None (borne : seulement les appuis)."""
        source = self.reglages['source_visiteurs']
        if source == 'auto':
            recu = self._detections.get('camera')
            frais = recu is not None and self._t - recu[1] <= CAMERA_FRAICHE_S
            return 'camera' if frais else 'lidar'
        return source if source in ('camera', 'lidar') else None

    def _personne_la_plus_proche(self):
        source = self._source_visiteurs()
        recu = self._detections.get(source) if source else None
        if recu is None or self._t - recu[1] > PERSONNES_FRAICHES_S:
            return None, source
        proches = [p for p in recu[0]['personnes'] if self._qualifie(p)]
        if not proches:
            return None, source
        return min(proches, key=lambda p: float(p['distance_m'])), source

    def _visiteur_present(self):
        """La personne présente depuis presence_s devant le robot, ou None."""
        p, source = self._personne_la_plus_proche()
        if p is None:
            return None
        debut = self._presents.get(source, {}).get(p.get('id'))
        if debut is None or self._t - debut < float(self.reglages['presence_s']):
            return None
        return dict(p, source=source)

    def _visiteur_vu(self):
        """Champ visiteur de /accueil/etat : le visiteur suivi en visite, sinon le plus proche."""
        suivi = (self._guide or {}).get('visiteur')
        if self._etat in ('depart', 'accompagnement') and isinstance(suivi, dict):
            v = self._guide['visiteur']
            return {'vu': bool(v.get('vu')), 'source': 'lidar',
                    'distance_m': _nombre(v.get('distance_m')), 'id': None}
        p, source = self._personne_la_plus_proche()
        if p is None:
            return None
        ident = p.get('id')
        return {'vu': True, 'source': source, 'distance_m': round(float(p['distance_m']), 2),
                'id': ident if isinstance(ident, int) and not isinstance(ident, bool) else None}

    def _blocage(self):
        """Ce qui empêche : verrou, pas_en_marche, pont_absent, pilotage, guide_absent, ou None."""
        t = self._t
        if self.reglages['suivre_pont']:
            pont_frais = self._pont is not None and t - self._t_pont <= DELAI_PONT_ABSENT_S
            p = self._pont if pont_frais else None
            if self._verrou or (p is not None and (p.get('verrou') is True
                                                   or p.get('etat') == 'arret_verrouille')):
                return 'verrou'
            if self._pont is not None and not pont_frais:
                return 'pont_absent'
            if p is not None and p.get('etat') == 'pas_en_marche':
                return 'pas_en_marche'
        if self._maitre == 'pilotage':
            return 'pilotage'
        if self._guide is None:
            if t - self._debut > DELAI_GUIDE_MUET_S:
                return 'guide_absent'
        elif not self._guide_frais():
            return 'guide_absent'
        immobilise = (self._guide or {}).get('immobilise')
        if immobilise in ETATS_BLOQUANTS_PONT and self.reglages['suivre_pont']:
            return immobilise
        return None

    def _empechement(self):
        """Ce qui empêche de reprendre ou de ramener (clé d'EMPECHEMENTS), ou None."""
        blocage = self._blocage()
        if blocage is not None:
            return blocage
        immobilise = (self._guide or {}).get('immobilise')
        if immobilise in ('robot_muet', 'refus') and self.reglages['suivre_pont']:
            p = self._pont or {}
            if p.get('etat') == immobilise:
                return immobilise
        if self._en_mission():
            return 'occupe'
        return None

    def _reprise_possible(self):
        return self._etat == 'pause' and self._empechement() is None and self._au_principal()

    def _ramener_possible(self):
        if self._etat not in ('pause', 'occupe', 'demarrage', 'arrivee'):
            return False
        if self._empechement() is not None or self._au_principal():
            return False
        return self._pose_fraiche() or self._etat == 'pause'

    def _actions_possibles(self):
        etat = self._etat
        actions = []
        if etat == 'attente':
            actions.append('appui')
        if etat in ('salutation', 'choix'):
            actions += ['appui', 'annuler']
        if etat != 'pause':
            actions.append('pause')
        if self._reprise_possible():
            actions.append('reprendre')
        if self._ramener_possible():
            actions.append('ramener')
        actions.append('remise_a_zero')
        return actions

    # ------------------------------------------------------------ la machine d'états

    def _evaluer(self):
        if self._etat != 'pause':
            cause = self._cause_de_pause()
            if cause is not None:
                self._pauser(cause)
                return
        getattr(self, '_dans_' + self._etat)()

    def _cause_de_pause(self):
        """La raison de mettre la démo en pause maintenant (blocage vu par la démo), ou None."""
        blocage = self._blocage()
        if blocage is None:
            self._cause_vue = None
            return None
        if self._etat not in ETATS_VISITE_DEMO or blocage in ('guide_absent', 'pont_absent'):
            return blocage
        # en visite, le guide dit pourquoi (ARRÊT, « Bloquer », panne) : on lui laisse un instant
        if self._cause_vue is None or self._cause_vue[0] != blocage:
            self._cause_vue = (blocage, self._t)
        if self._t - self._cause_vue[1] >= DELAI_RAISON_S:
            return blocage
        return None

    def _pauser(self, raison):
        if self._etat == 'pause':
            return
        if self._etat in ETATS_VISITE_DEMO:
            # rien ne doit continuer pour la démo : la demande en attente, le trajet, le retour
            # prévu (le guide les annule ; déjà arrêté, il reste au repos)
            self._publier('/guide/stop', None)
        if self._visite is not None and self._etat in ('depart', 'accompagnement'):
            if raison in ('echec', 'perdu'):
                self._stats['echecs'] += 1
                self._visite['resultat'] = 'echec'
                v = self._visite
                self._evenement('visite_echouee', f'Visite vers « {v["nom"]} » échouée.',
                                salle=v['salle'], nom=v['nom'], visite=v['id'], raison=raison)
            else:
                self._visite['resultat'] = 'interrompue'
        self._changer('pause')
        self._raison = raison
        self._cause_vue = None
        self._stats['pauses'] += 1
        self.pauses_vues.append((raison, self._t))
        del self.pauses_vues[:-1000]
        self._evenement('pause', MESSAGES_PAUSE[raison], raison=raison)
        self._dire(PHRASE_PAUSE, self._nouvel_id('accueil-pause-'), priorite='securite')

    def _dans_demarrage(self):
        if not self._guide_frais():
            return
        if self._en_mission():
            self._changer('occupe')
            self._evenement('occupe', 'Le guide est déjà en route : la démo attend son retour.')
        elif self._au_principal():
            self._entrer_attente()
            self._evenement('demarree', 'La démo est prête : le robot attend un visiteur.')
        else:
            self._note = (NOTE_LOIN if self._pose_fraiche() else
                          'Position du robot inconnue : la démo attend de savoir où il est.')

    def _entrer_attente(self, delai_detection=0.0, attendre_absence=False):
        self._changer('attente')
        self._visite = None
        self._demande = None
        self._abandon = False
        self._repos_depuis = None
        self._detection_permise = self._t + delai_detection
        self._attendre_absence = attendre_absence

    def _delai_entre(self):
        return float(self.reglages['delai_entre_visiteurs_s'])

    def _occupe_si_autre_mission(self):
        if self._en_mission() and not self._notre_mission():
            self._changer('occupe')
            self._evenement('occupe', 'Le guide fait une visite demandée hors de la démo.')
            return True
        return False

    def _dans_attente(self):
        if self._occupe_si_autre_mission():
            return
        if not self._au_principal():
            self._changer('occupe', NOTE_LOIN)
            return
        if self._t < self._detection_permise or self._attendre_absence:
            return
        visiteur = self._visiteur_present()
        if visiteur is not None:
            source = visiteur['source']
            distance = float(visiteur['distance_m'])
            capteur = 'caméra' if source == 'camera' else 'LiDAR'
            self._evenement('visiteur', f'Un visiteur est là ({capteur}, {distance:.1f} m).')
            self._saluer()

    def _saluer(self):
        self._stats['visiteurs'] += 1
        self._changer('salutation')
        salutation = (self.personnalite or {}).get('salutation') or SALUTATION_DEFAUT
        self._dire(salutation, self._nouvel_id('accueil-salut-'))
        geste = (self.personnalite or {}).get('geste_salut')
        entier = isinstance(geste, int) and not isinstance(geste, bool)
        if self.reglages.get('saluer_geste') and entier:
            self._publier('/robot/geste', message_robot_geste(
                geste, 'personnalite', 'salutation de la démo d\'accueil'))
        self._evenement('salutation', salutation)

    def _dans_salutation(self):
        if self._occupe_si_autre_mission():
            return
        if self._t - self._depuis >= DUREE_SALUTATION_S:
            self._changer('choix')

    def _dans_choix(self):
        if self._occupe_si_autre_mission():
            return
        if self._t - self._depuis >= float(self.reglages['delai_choix_s']):
            self._evenement('delai_choix', 'Personne n\'a choisi de salle : retour à l\'attente.')
            self._entrer_attente(self._delai_entre(), attendre_absence=True)

    def _dans_depart(self):
        g = self._guide or {}
        if self._notre_mission() and g.get('mission') == 'visite':
            if g.get('etat') == 'arrive':
                self._arriver()
                return
            if g.get('etat') in ETATS_EN_MISSION:
                self._partir()
                return
        if self._en_mission() and not self._notre_mission():
            self._perdre_la_visite()
            return
        if self._t - self._demande['t'] >= float(self.reglages['delai_depart_s']):
            self._pauser('echec')

    def _partir(self):
        self._changer('accompagnement')
        self._visite['depart_t'] = self._t
        self._repos_depuis = None
        v = self._visite
        self._evenement('depart', f'Le robot accompagne le visiteur vers « {v["nom"]} ».',
                        salle=v['salle'], nom=v['nom'], visite=v['id'])

    def _arriver(self):
        v = self._visite
        self._changer('arrivee')
        v['resultat'] = 'arrivee'
        self._stats['visites_reussies'] += 1
        debut = v.get('depart_t', self._demande['t'] if self._demande else self._t)
        v['duree_s'] = round(max(0.0, self._t - debut), 1)
        self._durees.append(v['duree_s'])
        self._evenement('arrivee', f'Arrivé à « {v["nom"]} » en {v["duree_s"]:.0f} s.',
                        salle=v['salle'], nom=v['nom'], visite=v['id'])

    def _abandonner(self):
        v = self._visite
        v['resultat'] = 'abandonnee'
        self._abandon = True
        self._stats['visites_abandonnees'] += 1
        self._evenement('visite_abandonnee', f'Le visiteur ne suit plus : visite vers '
                                             f'« {v["nom"]} » abandonnée, le robot rentre.',
                        salle=v['salle'], nom=v['nom'], visite=v['id'])
        self._changer('retour')
        self._repos_depuis = None

    def _perdre_la_visite(self):
        """Une autre demande (Atelier, chatbot) a remplacé la visite de la démo."""
        if self._visite is not None:
            self._visite['resultat'] = 'remplacee'
        self._changer('occupe')
        self._evenement('occupe', 'Une autre demande a remplacé la visite de la démo.')

    def _dans_accompagnement(self):
        g = self._guide or {}
        if self._notre_mission():
            if g.get('etat') == 'arrive' and g.get('mission') == 'visite':
                self._arriver()
                return
            if g.get('mission') == 'retour':
                self._abandonner()
                return
        elif self._en_mission():
            self._perdre_la_visite()
            return
        self._verifier_repos()

    def _verifier_repos(self):
        """Le guide s'est arrêté pendant la visite sans rien dire : la démo se met en pause."""
        if self._au_repos() and not (self._etat == 'retour' and self._au_principal()):
            if self._repos_depuis is None:
                self._repos_depuis = self._t
            elif self._t - self._repos_depuis >= DELAI_REPOS_S:
                g = self._guide or {}
                self._pauser('echec' if g.get('etat') == 'echec' else 'arret')
        else:
            self._repos_depuis = None

    def _dans_arrivee(self):
        g = self._guide or {}
        if g.get('mission') == 'retour' or g.get('etat') == 'retour':
            self._changer('retour')
            self._evenement('retour', 'Le robot retourne à l\'accueil.')
            return
        if self._en_mission() and not self._notre_mission():
            self._perdre_la_visite()

    def _dans_retour(self):
        if self._au_repos() and self._au_principal():
            self._evenement('retour_arrive', 'Le robot est de retour à l\'accueil.')
            self._entrer_attente(self._delai_entre())
            return
        if self._en_mission() and not self._notre_mission():
            self._perdre_la_visite()
            return
        self._verifier_repos()

    def _dans_occupe(self):
        if self._en_mission():
            self._note = None
            return
        if self._guide_frais() and self._au_repos() and self._au_principal():
            self._evenement('libre', 'Le guide est de nouveau libre : la démo reprend l\'attente.')
            self._entrer_attente(self._delai_entre())
            return
        self._note = NOTE_LOIN

    def _dans_pause(self):
        return

    # ------------------------------------------------------------ choix et commandes

    def _sur_choix(self, d):
        if not isinstance(d, dict):
            return
        ident = d.get('id') if isinstance(d.get('id'), str) else None
        salle = d.get('salle')
        source = d.get('source') if d.get('source') in SOURCES else None
        if not isinstance(salle, str):
            self._refuser_choix(ident, None, source, 'salle_inconnue', 'Choix sans salle.')
            return
        if self._etat == 'pause':
            self._refuser_choix(ident, salle, source, 'pause', TEXTES_REFUS['pause'])
            return
        if self._etat not in ETATS_CHOIX_POSSIBLE:
            if self._etat in ETATS_VISITE_DEMO + ('occupe',):
                self._stats['refus_occupe'] += 1
            texte = ('Le robot se prépare : un instant !' if self._etat == 'demarrage'
                     else TEXTES_REFUS['occupe'])
            self._refuser_choix(ident, salle, source, 'occupe', texte)
            return
        refus = refus_choix(salle, self.salles, self.id_principal, self.etage)
        if refus is not None:
            self._refuser_choix(ident, salle, source, refus[0], refus[1])
            return
        nom = self.par_id[salle]['nom']
        accompagner = d.get('accompagner')
        if not isinstance(accompagner, bool):
            accompagner = bool(self.reglages['accompagner'])
        visite = self._nouvel_id('v')
        self._stats['demandes'] += 1
        self._visite = {'id': visite, 'salle': salle, 'nom': nom, 'source': source or 'test',
                        'debut': maintenant_iso(), 'accompagner': accompagner, 'resultat': None}
        self._evenement('choix_accepte', f'Visite vers « {nom} » acceptée.', id=ident, salle=salle,
                        nom=nom, source=source, visite=visite)
        retour = bool(self.reglages['retour'])
        demande = {'cible': salle, 'accompagner': accompagner, 'retour': retour,
                   'source': 'accueil', 'id': visite}
        self._envoyer(demande)
        self._relais.noter_guidage(salle)
        if source != 'dialogue':
            phrases = (self.personnalite or {}).get('phrases') or {}
            texte = (texte_evenement('depart', nom, phrases) if phrases.get('depart')
                     else PHRASE_DEPART.replace('{nom}', nom))
            self._dire(texte, f'accueil-{visite}-depart')
        self._abandon = False
        self._changer('depart')

    def _envoyer(self, demande):
        """Publie /guide/aller : jamais en pause (règle 13.4), sauf « ramener » (explicite)."""
        self._demande = dict(demande, t=self._t)
        self._repos_depuis = None
        self.demandes_guide.append((dict(demande), self._t, self._etat))
        del self.demandes_guide[:-1000]
        self._publier('/guide/aller', dict(demande))

    def _refuser_choix(self, ident, salle, source, raison, texte):
        nom = (self.par_id.get(salle) or {}).get('nom') if salle else None
        self._evenement('choix_refuse', texte, id=ident,
                        salle=salle if salle in self.par_id else None, nom=nom, source=source,
                        raison=raison)

    def _sur_commande(self, d):
        if not isinstance(d, dict):
            return
        ident = d.get('id') if isinstance(d.get('id'), str) else None
        action = d.get('action')
        source = d.get('source') if d.get('source') in SOURCES else None
        traiter = {'appui': self._appui, 'annuler': self._annuler, 'pause': self._pause_demandee,
                   'reprendre': self._reprendre, 'ramener': self._ramener,
                   'remise_a_zero': self._remise_a_zero}.get(action)
        if traiter is None:
            self._evenement('commande_refusee', 'Commande inconnue.', id=ident, source=source,
                            raison='action_impossible')
            return
        refus = traiter(source)
        if refus is None:
            self._evenement('commande_acceptee', f'Commande « {action} » acceptée.', id=ident,
                            source=source, action=action)
        else:
            raison, texte = refus
            self._evenement('commande_refusee', texte, id=ident, source=source, action=action,
                            raison=raison)

    def _appui(self, source):
        etat = self._etat
        if etat == 'attente':
            self._evenement('visiteur', 'Un visiteur a touché la borne.', source=source)
            self._saluer()
            return None
        if etat in ('salutation', 'choix'):
            self._depuis = self._t if etat == 'choix' else self._depuis     # le visiteur est là
            return None
        if etat == 'pause':
            return 'pause', TEXTES_REFUS['pause']
        if etat == 'demarrage':
            return 'occupe', 'Le robot se prépare : un instant !'
        self._stats['refus_occupe'] += 1
        dit = self._dernier_occupe_dit
        if dit is None or self._t - dit >= DELAI_OCCUPE_DIT_S:
            self._dernier_occupe_dit = self._t
            self._dire(PHRASE_OCCUPE, self._nouvel_id('accueil-occupe-'))
        return 'occupe', PHRASE_OCCUPE

    def _annuler(self, source):
        if self._etat in ('salutation', 'choix'):
            self._entrer_attente(self._delai_entre(), attendre_absence=True)
            return None
        return 'action_impossible', 'Rien à annuler : aucun choix de salle en cours.'

    def _pause_demandee(self, source):
        if self._etat == 'pause':
            return 'action_impossible', 'La démo est déjà en pause.'
        self._pauser('operateur')
        return None

    def _reprendre(self, source):
        if self._etat != 'pause':
            return 'action_impossible', 'La démo n\'est pas en pause.'
        empechement = self._empechement()
        if empechement is not None:
            return 'action_impossible', EMPECHEMENTS[empechement]
        if not self._au_principal():
            return 'action_impossible', ('Ramenez d\'abord le robot à l\'accueil (« Ramener à '
                                         'l\'accueil »).')
        self._evenement('reprise', 'La démo reprend : le robot attend un visiteur.')
        self._entrer_attente()
        return None

    def _ramener(self, source):
        if self._etat in ('attente', 'salutation', 'choix'):
            return 'action_impossible', 'Le robot est déjà à l\'accueil.'
        if self._etat not in ('pause', 'occupe', 'demarrage', 'arrivee'):
            return 'action_impossible', ('Le robot est en visite : il reviendra seul (ou '
                                         'mettez la démo en pause).')
        empechement = self._empechement()
        if empechement is not None:
            return 'action_impossible', EMPECHEMENTS[empechement]
        if self._au_principal():
            if self._etat == 'pause':
                return 'action_impossible', ('Le robot est déjà à l\'accueil : cliquez sur '
                                             '« Reprendre ».')
            return 'action_impossible', 'Le robot est déjà à l\'accueil.'
        if self._etat != 'pause' and not self._pose_fraiche():
            return 'action_impossible', EMPECHEMENTS['position']
        self._visite = None
        self._abandon = False
        self._envoyer({'cible': 'principal', 'accompagner': False, 'retour': False,
                       'source': 'accueil', 'id': self._nouvel_id('ramener-')})
        self._evenement('retour', 'Le robot est ramené à l\'accueil (demande de l\'opérateur).')
        self._changer('retour')
        return None

    def _remise_a_zero(self, source):
        self._stats = self._statistiques_neuves()
        return None

    # ------------------------------------------------------------ messages et statistiques

    def _message(self):
        etat = self._etat
        if etat == 'pause':
            message = MESSAGES_PAUSE[self._raison]
            if self._reprise_possible():
                message += ' Cliquez sur « Reprendre » quand vous êtes prêt.'
            else:
                empechement = self._empechement()
                if empechement is not None:
                    message += ' ' + EMPECHEMENTS[empechement]
                elif not self._au_principal():
                    message += ' Puis « Ramener à l\'accueil » : rien ne repart seul.'
            return message
        nom = (self._visite or {}).get('nom') or ''
        message = MESSAGES_ETAT[etat].replace('{nom}', nom)
        if self._note:
            message += ' ' + self._note
        return message

    def _statistiques_neuves(self):
        self._durees = []
        return {'visiteurs': 0, 'demandes': 0, 'visites_reussies': 0, 'visites_abandonnees': 0,
                'echecs': 0, 'pauses': 0, 'refus_occupe': 0, 'depuis': maintenant_iso()}

    def _statistiques(self):
        s = dict(self._stats)
        s['duree_moyenne_s'] = (round(sum(self._durees) / len(self._durees), 1)
                                if self._durees else None)
        return s
