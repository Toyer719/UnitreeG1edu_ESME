"""
Le service robot_state du faux G1 (vague 6, section 13.2 du plan) : fichier de l'agent Diagnostic.

Sans ROS, à horloge injectable. FauxG1 (robot.py) lui passe chaque requête du service robot_state :
FauxRobotState.traiter(api, parametre, t) -> (code, data). Format du SDK d'Unitree
(unitree_sdk2py/go2/robot_state/robot_state_client.py, et ServiceStateData / ServiceSwitchData du
SDK C++, unitree/robot/go2/robot_state/robot_state_api.hpp) :
  1003 ServiceList    parameter « {} » ; data : la liste JSON [{"name", "status", "protect"}] des
                      services (SERVICES_FAUX_G1), entiers comme le SDK C++ : status 0 = actif,
                      1 = arrêté (comme ce G1, à vérifier à la séance 2), protect 0 ou 1 ;
  1001 ServiceSwitch  parameter {"name", "switch": 0|1} ; data {"name", "status": s} : service
                      connu et non protégé, switch 1 → status 1 tout de suite (0 s'il tourne déjà),
                      puis actif (0) après delai_demarrage_s ; switch 0 → arrêté (1) ; protégé →
                      status 5, rien ne change ; inconnu → status 2 ; un switch 0, et tout service
                      hors de la liste blanche de l'Atelier (LISTE_BLANCHE_ATELIER : lidar_driver,
                      unitree_slam ; copie de SERVICES_CARTOGRAPHIE, comparée par le test), sont
                      comptés dans « interdits » (l'Atelier ne doit jamais les envoyer) ;
  1002 ReportFreq     code 0 ; autre api : 3203 ; parameter illisible : 3204.
Réglages : arretes (services arrêtés au départ : paramètre ROS services_arretes du nœud, ou la
variable G1_JUMEAU_SERVICES_ARRETES, ex. « lidar_driver,unitree_slam ») ; changer({nom: 0 ou 1}) :
sujet d'essai /g1_jumeau/services ; etat() : le champ services de /g1_jumeau/etat (services,
interdits, appels, les dernières requêtes 1001 dans switchs, et les dix dernières requêtes reçues,
paramètre compris, dans requetes).
La panne « muet » (aucune réponse) est traitée par FauxG1, avant ce service.
"""
import json

CODE_OK = 0
CODE_API = 3203
CODE_PARAMETRES = 3204

STATUT_ACTIF = 0
STATUT_ARRETE = 1
STATUT_INCONNU = 2
STATUT_PROTEGE = 5

# Services du faux G1 (noms et protections à vérifier sur le vrai robot, 13.10)
SERVICES_FAUX_G1 = (('ai_sport', True), ('motion_switcher', True), ('lidar_driver', False),
                    ('unitree_slam', False), ('voice', False), ('video_hub', False))
# Les seuls services que l'Atelier a le droit de démarrer (copie de
# atelier.lieu.diagnostic.SERVICES_CARTOGRAPHIE : le faux G1 tourne sans l'Atelier)
LISTE_BLANCHE_ATELIER = ('lidar_driver', 'unitree_slam')
DELAI_DEMARRAGE_S = 2.0
GARDES = 50                      # requêtes 1001 et interdits gardés dans l'état


def lire_json(texte):
    """Objet JSON d'un parameter, ou None."""
    try:
        d = json.loads(texte) if texte else {}
    except (TypeError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def entier(v):
    return isinstance(v, int) and not isinstance(v, bool)


class FauxRobotState:
    """Service robot_state du faux G1 : liste des services, démarrage et arrêt (1003, 1001)."""

    def __init__(self, horloge=None, arretes=(), delai_demarrage_s=DELAI_DEMARRAGE_S,
                 services=SERVICES_FAUX_G1):
        self.horloge = horloge
        self.arretes = tuple(arretes)
        self.delai_demarrage_s = float(delai_demarrage_s)
        if self.delai_demarrage_s < 0:
            raise ValueError(f'delai_demarrage_s = {delai_demarrage_s!r} : un nombre positif')
        self.protection = {nom: bool(protege) for nom, protege in services}
        inconnus = [n for n in self.arretes if n not in self.protection]
        if inconnus:
            raise ValueError(f'services_arretes : service inconnu {", ".join(inconnus)} (connus : '
                             f'{", ".join(self.protection)})')
        self.statuts = {nom: STATUT_ARRETE if nom in self.arretes else STATUT_ACTIF
                        for nom in self.protection}
        self.demarrages = {}             # nom → instant où il sera actif
        self.switchs = []                # [{t, name, switch, status}] : les requêtes 1001 reçues
        self.interdits = []              # [{t, name, switch, raison}]
        self.nombre_interdits = 0
        self.appels = {'1001': 0, '1002': 0, '1003': 0, 'autres': 0, 'illisibles': 0}
        self.requetes = []               # [{t, api, parameter}] : les dernières requêtes reçues

    def maintenant(self, t=None):
        if t is not None:
            return float(t)
        return float(self.horloge()) if self.horloge else 0.0

    def mettre_a_jour(self, t=None):
        """Les services en cours de démarrage dont le délai est passé deviennent actifs."""
        t = self.maintenant(t)
        for nom, fin in list(self.demarrages.items()):
            if t >= fin:
                self.statuts[nom] = STATUT_ACTIF
                del self.demarrages[nom]

    def liste(self):
        """Ce que rend 1003 : [{"name", "status", "protect"}], entiers comme le SDK C++."""
        return [{'name': nom, 'status': int(self.statuts[nom]),
                 'protect': int(self.protection[nom])} for nom in self.protection]

    def _noter_interdit(self, t, nom, switch, raison):
        self.nombre_interdits += 1
        self.interdits.append({'t': round(t, 3), 'name': nom, 'switch': switch, 'raison': raison})
        del self.interdits[:-GARDES]

    def traiter(self, api, parametre, t=None):
        """(code, data) de la réponse à une requête du service robot_state."""
        t = self.maintenant(t)
        self.mettre_a_jour(t)
        self.requetes.append({'t': round(t, 3), 'api': int(api),
                              'parameter': str(parametre)[:200]})
        del self.requetes[:-GARDES]
        d = lire_json(parametre)
        if api == 1003:
            self.appels['1003'] += 1
            if d is None:
                self.appels['illisibles'] += 1
                return (CODE_PARAMETRES, '')
            return (CODE_OK, json.dumps(self.liste()))
        if api == 1002:
            self.appels['1002'] += 1
            return (CODE_OK, '') if d is not None else (CODE_PARAMETRES, '')
        if api != 1001:
            self.appels['autres'] += 1
            return (CODE_API, '')
        self.appels['1001'] += 1
        if d is None or not isinstance(d.get('name'), str) or not entier(d.get('switch')) \
                or d['switch'] not in (0, 1):
            self.appels['illisibles'] += 1
            return (CODE_PARAMETRES, '')
        nom, switch = d['name'], d['switch']
        if switch == 0:
            self._noter_interdit(t, nom, switch, 'arrêt de service (switch 0)')
        elif nom not in LISTE_BLANCHE_ATELIER:
            self._noter_interdit(t, nom, switch, "service hors de la liste blanche de l'Atelier")
        if nom not in self.protection:
            statut = STATUT_INCONNU
        elif self.protection[nom]:
            statut = STATUT_PROTEGE
        elif switch == 1:
            if self.statuts[nom] == STATUT_ACTIF:
                statut = STATUT_ACTIF
            else:
                statut = STATUT_ARRETE
                self.demarrages.setdefault(nom, t + self.delai_demarrage_s)
            self.mettre_a_jour(t)
            statut = STATUT_ACTIF if self.statuts[nom] == STATUT_ACTIF else statut
        else:
            self.demarrages.pop(nom, None)
            self.statuts[nom] = STATUT_ARRETE
            statut = STATUT_ARRETE
        self.switchs.append({'t': round(t, 3), 'name': nom, 'switch': switch, 'status': statut})
        del self.switchs[:-GARDES]
        return (CODE_OK, json.dumps({'name': nom, 'status': statut}))

    def changer(self, statuts):
        """Statuts changés d'un coup ({nom: 0 ou 1}) par le sujet d'essai /g1_jumeau/services."""
        if not isinstance(statuts, dict):
            raise ValueError('un objet JSON {"nom du service": 0 ou 1} est attendu')
        for nom, statut in statuts.items():
            if nom not in self.protection:
                connus = ', '.join(self.protection)
                raise ValueError(f'service « {nom} » inconnu (connus : {connus})')
            if not entier(statut) or statut not in (STATUT_ACTIF, STATUT_ARRETE):
                raise ValueError(f'statut de « {nom} » : 0 (actif) ou 1 (arrêté), pas {statut!r}')
        for nom, statut in statuts.items():
            self.statuts[nom] = int(statut)
            self.demarrages.pop(nom, None)

    def etat(self, t=None):
        """Le champ services de /g1_jumeau/etat."""
        self.mettre_a_jour(t)
        return {'services': {nom: int(s) for nom, s in self.statuts.items()},
                'demarrage_en_cours': sorted(self.demarrages),
                'arretes_au_depart': list(self.arretes),
                'switchs': list(self.switchs[-20:]),
                'interdits': list(self.interdits[-20:]), 'nombre_interdits': self.nombre_interdits,
                'appels': dict(self.appels), 'requetes': list(self.requetes[-10:])}
