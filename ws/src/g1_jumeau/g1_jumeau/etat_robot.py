"""
Le service robot_state du faux G1 (vague 6, section 13.2 du plan) : fichier de l'agent Diagnostic.

Sans ROS, à horloge injectable. Squelette livré par l'agent Contrats : toute requête répond 3203
(api inconnue), comme le faux G1 d'avant la vague 6. L'agent Diagnostic l'écrit (format du SDK
d'Unitree, unitree_sdk2py/go2/robot_state/robot_state_client.py ; contrat en 13.2) :
  1003 ServiceList    parameter « {} » ; data : la liste JSON [{"name", "status", "protect"}] des
                      services (SERVICES_FAUX_G1), entiers comme le SDK C++ : status 0 = actif,
                      1 = arrêté (comme ce G1), protect 0 ou 1 ;
  1001 ServiceSwitch  parameter {"name", "switch": 0|1} ; data {"name", "status": s} : service
                      connu et non protégé, switch 1 → status 1 tout de suite, puis actif (0) après
                      delai_demarrage_s ; protégé → status 5 ; inconnu → status 2 ;
                      un switch 0, et tout service hors de la liste blanche de l'Atelier
                      (lidar_driver, unitree_slam), sont comptés dans « interdits » (jamais) ;
  1002 ReportFreq     code 0 ; autre api : 3203 ; parameter illisible : 3204.
Réglages : arretes (services arrêtés au départ : paramètre ROS services_arretes du nœud, ou la
variable G1_JUMEAU_SERVICES_ARRETES, ex. « lidar_driver,unitree_slam ») ; changer({nom: 0 ou 1}) :
sujet d'essai /g1_jumeau/services ; etat() : le champ services de /g1_jumeau/etat (services,
interdits, appels).
"""
CODE_API = 3203

# Services du faux G1 (noms et protections à vérifier sur le vrai robot, 13.10)
SERVICES_FAUX_G1 = (('ai_sport', True), ('motion_switcher', True), ('lidar_driver', False),
                    ('unitree_slam', False), ('voice', False), ('video_hub', False))
DELAI_DEMARRAGE_S = 2.0


class FauxRobotState:
    """Service robot_state du faux G1 (squelette : rien encore)."""

    def __init__(self, horloge=None, arretes=(), delai_demarrage_s=DELAI_DEMARRAGE_S):
        self.horloge = horloge
        self.arretes = tuple(arretes)
        self.delai_demarrage_s = float(delai_demarrage_s)

    def traiter(self, api, parametre, t=None):
        """(code, data) de la réponse à une requête du service robot_state."""
        return (CODE_API, '')

    def changer(self, statuts):
        """Statuts changés d'un coup ({nom: 0 ou 1}) par le sujet d'essai /g1_jumeau/services."""
        raise ValueError('pas encore fait : services du faux G1 (agent Diagnostic, '
                         'section 13.2 du plan)')

    def etat(self):
        """Le champ services de /g1_jumeau/etat."""
        return {'pas_encore_fait': True, 'arretes_au_depart': list(self.arretes)}
