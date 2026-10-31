"""
Guide : emmène le robot jusqu'à une salle ou un nœud, puis revient seul au point principal.

Il accompagne le visiteur, attend les passants, contourne les couloirs bouchés, s'arrête quand il
est perdu, et annonce chaque étape au visiteur (sections 4.2, 10.7 et 11.4 du plan).

Sujets ROS 2 :
  /guide/aller      std_msgs/String  id de salle ou de nœud (« b204 »), le mot « principal »,
                                     ou du JSON {cible, accompagner?, retour?, source?} (schéma
                                     demande_guide) ; l'id simple : visite sans accompagnement
  /guide/stop       std_msgs/Empty   arrêt immédiat (toujours accepté), retour prévu annulé
  /guide/etat       std_msgs/String  JSON (schéma etat_guide) {version, etat, cible, reste_m,
                                     itineraire, mission, accompagner, visiteur, depuis_s,
                                     message?, retour_dans_s?}, 5 fois par seconde et à chaque
                                     changement
  /guide/evenement  std_msgs/String  JSON (schéma evenement_guide), une fois par événement : la
                                     phrase à dire au visiteur (départ, détour, arrivée, retour...)
  /speed_limit      nav2_msgs/SpeedLimit  en pourcentage : le robot ralentit si le visiteur traîne,
                                     et ne dépasse pas la vitesse_max de la personnalité active
  écoutés : /reperage/etat (relais odom_vers_tf), /personnes/lidar (detecteur_personnes),
            /mouvement/maitre (verrou du pilotage, fiable et transient_local),
            /personnalite/active (fiable, transient_local ; au démarrage : personnalites.yaml)

États (atelier.lieu.comportement.ETATS_GUIDE) :
  attente          au repos ; après un retour, au point principal, tourné selon sa flèche ; aussi
                   avec un message quand la navigation n'est pas encore prête (Nav2 démarre, robot
                   pas encore repéré : DELAI_PREPARATION_S au plus, puis echec) ;
  en_route         visite vers la salle demandée (mission visite) ;
  retour           retour automatique vers le point principal (mission retour),
                   delai_avant_retour_s après une arrivée, un abandon ou un échec ; à l'arrivée, le
                   robot se tourne dans le sens de la flèche (TOLERANCE_RETOUR_RAD), puis attente ;
  bloque           plus de progrès depuis 3 s (5 s juste après le départ), personne devant ;
  attente_passage  plus de progrès et une personne vue devant à 2,5 m au plus (devant le robot ou
                   dans la direction du couloir) : le robot s'arrête et attend delai_passant_s
                   (« Pardon, puis-je passer ? ») ; passage libre : il repart (« Merci ! ») ;
                   sinon, couloir déclaré bloqué (détour) ;
  detour           couloir marqué bloqué (120 s), autre chemin, jusqu'à l'arrivée. Un détour
                   déraisonnable (plus de detour_facteur_max fois le trajet direct et plus de
                   detour_marge_m de plus) est refusé : le guide attend encore le passant, ou
                   renonce ;
  attente_visiteur le visiteur suivi traîne trop (distance_attendre_m) ou n'est plus vu depuis
                   2 s : robot arrêté, delai_visiteur_s au plus, puis abandon (visiteur_perdu) et
                   retour ;
  perdu            repérage perdu (relais), ou plus de position sur la carte depuis 2 s : robot
                   arrêté, delai_perdu_s au plus ; retrouvé : reprise ; sinon echec, sans retour ;
  arrive, echec    fin d'une visite (le retour qui suit est un nouveau trajet, cible : le
                   point principal).

Le guide ne parle jamais directement à Nav2 : il passe par un Moteur (moteurs.py). Le paramètre
ROS « moteur » le choisit : nav2 (MoteurNav2), unitree (MoteurUnitree) ou factice (MoteurFactice).

La logique (classe Guide) n'utilise pas ROS : elle se teste avec un moteur factice et une fausse
horloge. Le nœud ROS (NoeudGuide) l'appelle depuis un seul fil, environ 5 fois par seconde.

  ros2 run g1_nav guide --ros-args -p lieu:=demo -p etage:=rdc -p moteur:=nav2
      [-p accompagnement:=false] [-p passants:=false] [-p delai_avant_retour_s:=5.0] ...
"""
import json
import math
import signal
import sys
import time
from pathlib import Path

from atelier.lieu.comportement import (DELAI_VISITEUR_DEPART_S, DELAIS_GUIDE,
                                       DISTANCE_VISITEUR_DEPART_M, ETATS_GUIDE, evenement,
                                       TOLERANCE_RETOUR_M)
from g1_nav.routeur import CibleInconnue, Routeur
from g1_nav.visiteur import lire_personnes, personne_devant, SuiviVisiteur

try:
    import rclpy
    from rclpy.node import Node
except ImportError:      # logique seule, sans ROS (tests)
    rclpy = None
    Node = object

ETATS = ETATS_GUIDE
# États d'une mission en cours (le guide lit le moteur à chaque pas)
ETATS_ACTIFS = ('en_route', 'retour', 'bloque', 'detour', 'attente_passage', 'attente_visiteur',
                'perdu')

# Sans progrès pendant DELAI_BLOQUE_S : bloque ; pendant DELAI_DETOUR_S : détour
DELAI_BLOQUE_S = 3.0
DELAI_DETOUR_S = 8.0
# Au départ (et après un détour), le robot a DELAI_DEPART_S de plus pour démarrer : Nav2
# calcule le chemin et le robot se tourne dans le bon sens
DELAI_DEPART_S = 2.0
# Au-delà de MAX_DETOURS détours pour un même trajet, le guide renonce (echec)
MAX_DETOURS = 3
# Près du but, le robot peut tourner sur place sans gagner de distance : ce n'est pas bloqué
DISTANCE_APPROCHE_M = 0.5
# Attente de la navigation (Nav2 qui démarre, repérage) après /guide/aller, au plus
DELAI_PREPARATION_S = 90.0
MESSAGE_PREPARATION = 'La navigation démarre : départ dès qu\'elle est prête.'
MESSAGE_NON_REPERE = 'Robot non repéré : cliquez sur « Repérer le robot ».'
MESSAGE_REPERAGE_EN_COURS = 'Repérage en cours : départ dès que le robot est repéré.'
MESSAGE_PERDU = 'repérage perdu'
# /reperage/etat plus vieux : on ne s'y fie plus
DELAI_REPERAGE_PERIME_S = 2.0

# Vague 4 (section 11.4) ------------------------------------------------------------------
# Réglages du guide : ceux du contrat (DELAIS_GUIDE, section guide de lieu.yaml), plus ceux qui
# ne sont que des paramètres ROS du nœud (désactiver l'accompagnement ou la règle du passant,
# refuser les détours déraisonnables)
REGLAGES_NOEUD = {
    'accompagnement': True,         # false : {accompagner: true} part sans suivre le visiteur
    'passants': True,               # false : un passant devant ne change rien (bloque, détour)
    'detour_facteur_max': 3.5,      # détour refusé au-delà de ce facteur du trajet direct...
    'detour_marge_m': 45.0,         # ... et de cette marge (m) : max(facteur × d, d + marge)
    'vitesse_max_nav2': 0.0,        # vx_max du contrôleur de Nav2 (m/s) ; 0 : inconnue
    # Vague 5 (section 12.6) : rotation finale au point principal et ralenti, réglables. Défauts :
    # ceux de la simulation (SEUIL_ORIENTATION_RAD, POURCENTAGE_MIN) ; avec le pont, le lancement
    # en donne d'autres (navigation.launch.py, TOLERANCE_ORIENTATION_PONT_RAD)
    'tolerance_orientation_rad': 0.09,   # écart de cap toléré à l'arrivée au point principal
    'anticipation_rotation_rad': 0.0,    # la rotation demandée est raccourcie d'autant (au plus
                                         # la moitié) : le dépassement mesuré du robot
    'pourcentage_min': 10.0,             # /speed_limit jamais plus bas (pourcentage)
}
REGLAGES_DEFAUT = dict(DELAIS_GUIDE, **REGLAGES_NOEUD)
# Réglages qu'on peut changer en marche (vague 5 : à la séance 2, sans relancer la navigation),
# par exemple « ros2 param set /guide anticipation_rotation_rad 0.3 », avec leurs bornes
REGLAGES_EN_MARCHE = {'tolerance_orientation_rad': (0.0, math.pi),
                      'anticipation_rotation_rad': (0.0, 1.0), 'pourcentage_min': (0.0, 100.0)}


def refus_reglage_en_marche(nom, valeur):
    """None si le réglage nom peut prendre valeur en marche, sinon la raison, en français."""
    if nom not in REGLAGES_EN_MARCHE:
        return None
    bas, haut = REGLAGES_EN_MARCHE[nom]
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float)) \
            or not math.isfinite(valeur) or not bas <= valeur <= haut:
        return f'{nom} = {valeur!r} : il faut un nombre de {bas:g} à {haut:g}'
    return None


# Passant qui bouche : personne vue à moins de DISTANCE_PASSANT_M, dans un cône de ±60° autour de
# l'avant du robot ou de la direction du couloir de l'itinéraire, dans la dernière seconde.
# Assemblage de la vague 4 (critère 25) : 2,5 m et non 1,5 m, car Nav2 arrête le robot à 2,4 m
# environ d'un groupe qui bouche le couloir (les personnes sont dans sa carte globale), et le cône
# du couloir, car Nav2 le fait alors pivoter vers un autre chemin. Pendant l'attente, le robot est
# arrêté (moteur annulé) : sinon Nav2 contournerait lui-même le groupe par un autre couloir. Le
# passage est libre quand, depuis DELAI_PASSANT_PARTI_S, personne n'est vu à moins de
# DISTANCE_PASSANT_M + MARGE_PASSANT_M dans ces cônes, sauf qui s'éloigne du robot à plus de
# VITESSE_ELOIGNEMENT_M_S : le trajet reprend.
DISTANCE_PASSANT_M = 2.5
MARGE_PASSANT_M = 0.5
VITESSE_ELOIGNEMENT_M_S = 0.3
PERSISTANCE_DEVANT_S = 1.0
DELAI_PASSANT_PARTI_S = 1.5
# Détour refusé à cause d'un passant : le guide attend encore, au plus ce nombre de fois
MAX_PROLONGATIONS_PASSANT = 2
# « Pardon, puis-je passer ? » au plus une fois par ANNONCE_PASSANT_S (le robot qui avance un peu
# puis se rebloque devant la même personne ne le répète pas)
ANNONCE_PASSANT_S = 20.0
# Visiteur : il redevient « proche » sous distance_ralentir_m − HYSTERESE_VISITEUR_M ; à moins de
# DISTANCE_BUT_SANS_ATTENTE_M du but, le robot ne s'arrête plus pour l'attendre
HYSTERESE_VISITEUR_M = 0.3
DISTANCE_BUT_SANS_ATTENTE_M = 1.0
# Messages de /personnes/lidar plus vieux : ignorés
DELAI_PERSONNES_PERIME_S = 1.0
# Plus de position sur la carte depuis DELAI_TF_PERDU_S pendant une mission : robot perdu
DELAI_TF_PERDU_S = 2.0
# Retour : à l'arrivée, si le cap est à plus de SEUIL_ORIENTATION_RAD de la flèche, le robot se
# tourne (ESSAIS_ORIENTATION fois au plus, DELAI_ORIENTATION_S chacune) ; but :
# TOLERANCE_RETOUR_RAD. Vague 5 : le seuil est le réglage tolerance_orientation_rad (défaut
# SEUIL_ORIENTATION_RAD, la simulation) ; avec le pont du vrai robot, la rotation ne descend pas
# sous 0,3 rad/s et dépasse la flèche d'autant plus que le robot répond lentement : le lancement
# relève le seuil (section 12.6 du plan), et anticipation_rotation_rad raccourcit la rotation.
SEUIL_ORIENTATION_RAD = 0.09
ESSAIS_ORIENTATION = 3
DELAI_ORIENTATION_S = 15.0
# Ralenti pour le visiteur : ralenti × la vitesse mesurée sur les FENETRE_VITESSE_S dernières
# secondes (en pourcentage de vitesse_max_nav2), POURCENTAGE_MIN au moins. Le Collision Monitor
# freine déjà le robot quand le visiteur le suit de près : un pourcentage de la vitesse maximale
# ne le ralentirait pas toujours.
FENETRE_VITESSE_S = 4.0
VITESSE_MESURABLE_M_S = 0.05
POURCENTAGE_MIN = 10.0


def distance_segment(p, a, b):
    """Distance du point p au segment [a, b], en mètres."""
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    longueur2 = dx * dx + dy * dy
    if longueur2 == 0.0:
        return math.dist(p, a)
    t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / longueur2))
    return math.dist(p, (ax + t * dx, ay + t * dy))


def ecart_angle(a, b):
    """Renvoie a − b ramené entre −π et π."""
    return math.atan2(math.sin(a - b), math.cos(a - b))


class Guide:
    """Machine à états du guide, sans ROS : routeur + moteur + position du robot."""

    def __init__(self, routeur, moteur, position=None, horloge=time.monotonic,
                 journal=None, au_changement=None, depart_defaut='accueil', preparation=None,
                 delai_preparation=DELAI_PREPARATION_S, suspension=None, reglages=None,
                 principal=None, personnes=None, au_evenement=None, limiter_vitesse=None,
                 maitre=None):
        """
        Prépare le guide.

        routeur       : Routeur de l'étage ;
        moteur        : un Moteur (moteurs.py) ; s'il a une méthode tourner(angle), elle sert à se
                        mettre dans le sens de la flèche du point principal au retour ;
        position      : fonction sans argument qui renvoie (x, y, theta) dans map, ou None ;
        horloge       : temps en secondes (fausse horloge des tests) ;
        journal       : fonction qui reçoit les messages pour l'utilisateur (print par défaut) ;
        au_changement : fonction appelée avec etat() à chaque changement d'état ;
        depart_defaut : nœud de départ quand la position du robot est inconnue ;
        preparation   : fonction sans argument : None si la navigation est prête, sinon
                        ('attendre', message) ou ('echec', message) ;
        delai_preparation : attente maximale de la navigation après /guide/aller, en s ;
        suspension    : fonction sans argument : None si le robot sait où il est, sinon la raison
                        (repérage perdu) : le guide passe à « perdu » ;
        reglages      : délais et distances (REGLAGES_DEFAUT, atelier.lieu.reglages_guide) ;
        principal     : id du point principal (nœud de l'étage), cible du retour ; None : pas de
                        retour automatique ;
        personnes     : fonction sans argument : liste de Personne vues maintenant (visiteur.py),
                        ou None sans message frais du détecteur ; None : ni accompagnement ni
                        passants ;
        au_evenement  : fonction appelée avec chaque message /guide/evenement (dict) ;
        limiter_vitesse : fonction appelée avec un pourcentage de la vitesse permise, ou None pour
                        lever la limite ;
        maitre        : fonction sans argument : « guide » ou « pilotage » (verrou des mouvements).
        """
        self.routeur = routeur
        self.moteur = moteur
        self.position = position or (lambda: None)
        self.horloge = horloge
        self.journal = journal or print
        self.au_changement = au_changement
        self.depart_defaut = depart_defaut
        self.preparation = preparation
        self.delai_preparation = delai_preparation
        self.suspension = suspension
        self.reglages = dict(REGLAGES_DEFAUT, **{k: v for k, v in (reglages or {}).items()
                                                 if v is not None})
        self.principal = principal if principal in routeur.noeuds else None
        self.personnes = personnes
        self.au_evenement = au_evenement
        self.limiter_vitesse = limiter_vitesse
        self.maitre = maitre
        self._etat = 'attente'
        self._message = ''
        self._depuis = horloge()
        self._en_attente = None          # (cible, fin de l'attente) : départ dès que prêt
        self._cible = None
        self._itineraire = []
        self._reste = None
        self._dernier_progres = horloge()
        self._etat_route = 'en_route'    # en_route ou retour ; detour après un détour
        self._relances = 0
        self._mission = None             # visite, retour, ou None au repos
        self._demande = {}
        self._retour_prevu = None        # instant du retour automatique
        self._limite = 'inconnue'        # limite de vitesse envoyée (None : aucune)
        self._limite_visiteur = None     # limite demandée pour le visiteur qui traîne (%)
        self._plafond_personnalite = None    # plafond de la personnalité active (%)
        self._suivi = SuiviVisiteur()
        self._accompagner = False
        self._nouvelle_mission(None, None)
        self.detours = 0
        self.arrets = 0
        self.attentes_passage = 0

    # ------------------------------------------------------------ commandes

    def aller(self, cible, accompagner=False, retour=None, source=None):
        """
        Part vers une salle ou un nœud (« principal » : le point principal), en visite.

        accompagner : suivre le visiteur (la personne la plus proche au départ) ; retour : retour
        automatique au point principal après la visite (None : retour_auto du lieu) ; source : qui
        demande (journal). Renvoie True si le robot est parti (ou va partir).
        """
        self._retour_prevu = None
        self._en_attente = None
        texte = str(cible).strip()
        if self._pilote():
            self.moteur.annuler()
            self._nouvelle_mission('visite', texte)
            return self._refuser_pilotage()
        if texte == 'principal' and self.principal is not None:
            texte = self.principal
        try:
            but = self.routeur.resoudre(texte)
        except CibleInconnue as e:
            self._nouvelle_mission('visite', texte)
            if texte == 'principal':
                return self._echouer('le lieu n\'a pas de point principal sur cet étage')
            return self._echouer(f'cible inconnue : {e}')
        accompagner = bool(accompagner) and bool(self.reglages['accompagnement']) \
            and self.personnes is not None
        self._nouvelle_mission('visite', but, accompagner, {'retour': retour, 'source': source})
        if source:
            self.journal(f'demande de « {source} » : {but}'
                         + (' (accompagner le visiteur)' if accompagner else ''))
        verdict = self.preparation() if self.preparation else None
        if verdict is not None:
            genre, message = verdict
            if genre == 'echec':
                return self._echouer(message)
            self._en_attente = (but, self.horloge() + self.delai_preparation)
            self._changer('attente', message, message)
            return True
        return self._commencer_visite(but)

    def refuser(self, cible, raison):
        """Demande /guide/aller illisible : echec avec la raison, sans mouvement."""
        self._retour_prevu = None
        self._en_attente = None
        self._nouvelle_mission('visite', str(cible).strip()[:40] or None)
        return self._echouer(raison)

    def stop(self):
        """Arrête le robot tout de suite ; le guide revient en attente (retour prévu annulé)."""
        actif = (self._etat in ETATS_ACTIFS or self._en_attente is not None
                 or self._retour_prevu is not None)
        mission = self._mission
        self._en_attente = None
        self._retour_prevu = None
        self.moteur.annuler()
        self._nouvelle_mission(None, None)
        self._changer('attente', 'arrêt demandé')
        if actif:
            self._evenement('arret', salle=None, mission=mission)

    def pas(self):
        """Lit l'état du moteur et fait avancer la machine à états. Renvoie etat()."""
        maintenant = self.horloge()
        if self._en_attente is not None:
            if self._pilote():
                self._en_attente = None
                self._refuser_pilotage()
            else:
                self._attendre_preparation()
            return self.etat()
        if self._etat not in ETATS_ACTIFS:
            if self._retour_prevu is not None:
                if self._pilote():
                    self._retour_prevu = None
                    self.journal('retour annulé : le robot est piloté à la main')
                elif maintenant >= self._retour_prevu:
                    self._demarrer_retour()
            return self.etat()
        if self._pilote():
            self._interrompre_pilotage()
            return self.etat()
        pose = self.position()
        self._compter_parcours(pose)
        if self._verifier_perdu(maintenant, pose):
            return self.etat()
        if self._etat == 'attente_visiteur':
            self._attendre_visiteur(maintenant, pose)
            return self.etat()
        if self._orientation is not None:
            self._suivre_orientation(maintenant)
            return self.etat()
        if self._etat == 'attente_passage':
            self._attendre_passage(maintenant)
            return self.etat()
        e = self.moteur.etat()
        if e['reste_m'] is not None:
            self._reste = e['reste_m']
        if e['arrive']:
            self._arriver()
        elif e['echec']:
            # Premier abandon sur ce trajet : on relance depuis le couloir actuel ; ensuite,
            # détour (un abandon isolé de Nav2 ne doit pas fermer un couloir)
            if self._relances < 1:
                self._relances += 1
                self._reprendre()
            else:
                self._detourner('le moteur a renoncé deux fois')
        elif not e['en_cours']:
            self._echouer('le moteur s\'est arrêté sans arriver')
        else:
            if self._recherche_jusqu_a is not None:
                self._chercher_visiteur(maintenant, pose)
            elif self._accompagner and self._surveiller_visiteur(maintenant, pose):
                return self.etat()
            self._suivre_progres(maintenant, e)
        return self.etat()

    def etat(self):
        """Renvoie le message de /guide/etat : schéma etat_guide, sections 4.2 à 11.4 du plan."""
        maintenant = self.horloge()
        reste = None if self._reste is None else round(max(0.0, float(self._reste)), 2)
        etat = {'version': 1, 'etat': self._etat, 'cible': self._cible, 'reste_m': reste,
                'itineraire': list(self._itineraire), 'mission': self._mission,
                'accompagner': bool(self._accompagner),
                'visiteur': self._suivi.resume(maintenant) if self._accompagner else None,
                'depuis_s': round(max(0.0, maintenant - self._depuis), 1)}
        if self._message:
            etat['message'] = self._message
        if self._retour_prevu is not None:
            etat['retour_dans_s'] = round(max(0.0, self._retour_prevu - maintenant), 1)
        return etat

    @property
    def en_attente(self):
        """Vrai si une destination attend que la navigation soit prête."""
        return self._en_attente is not None

    @property
    def retour_prevu(self):
        """Instant (horloge du guide) du retour automatique au point principal, ou None."""
        return self._retour_prevu

    # ------------------------------------------------------------ missions

    def _nouvelle_mission(self, mission, cible, accompagner=False, demande=None):
        """Remet à zéro ce qui dépend du trajet : compteurs, visiteur, passant, perte, détours."""
        self._mission = mission
        self._cible = cible
        self._demande = dict(demande or {})
        self._itineraire, self._reste = [], None
        self._etat_route = 'retour' if mission == 'retour' else 'en_route'
        self._relances = 0
        self.detours = 0
        self.arrets = 0
        self._orientation = None
        self._essais_orientation = 0
        self._retour_annonce = True
        self._longueur_directe = None
        self._parcouru = 0.0
        self._derniere_pose = None
        self._recentes = []              # (instant, x, y) des dernières secondes : vitesse mesurée
        self._position_vue = False
        self._sans_position_depuis = None
        self._perdu_debut = None
        self._passage_debut = None
        self._passage_vu = None
        self._passant_annonce = None     # instant du dernier « Pardon, puis-je passer ? »
        self._devant_vu_a = None
        self._prolongations = 0
        self._attente_visiteur_debut = None
        self._recherche_jusqu_a = None
        self._ralenti = False
        self._suivi.oublier()
        self._accompagner = bool(accompagner)
        self._lever_limite()

    def _commencer_visite(self, but):
        """Départ d'une visite : itinéraire, puis l'annonce (depart, ou seul sans visiteur vu)."""
        if not self._partir_vers(but, 'en_route'):
            return False
        if self._accompagner:
            if self._suivi.choisir(self._personnes_fraiches(), self.horloge(), self.position(),
                                   DISTANCE_VISITEUR_DEPART_M):
                self.journal(f'visiteur choisi (personne n° {self._suivi.id}, à '
                             f'{self._suivi.distance:.1f} m)')
                self._evenement('depart')
            else:
                # Personne en vue tout de suite : on le cherche encore DELAI_VISITEUR_DEPART_S
                self._recherche_jusqu_a = self.horloge() + DELAI_VISITEUR_DEPART_S
        else:
            self._evenement('depart')
        return True

    def _retour_voulu(self):
        voulu = self._demande.get('retour')
        return bool(self.reglages['retour_auto']) if voulu is None else bool(voulu)

    def _programmer_retour(self):
        """Après une visite (arrivée, abandon, échec) : retour au point principal plus tard."""
        if self._mission != 'visite' or not self._retour_voulu():
            return
        if self.principal is None:
            return
        if self.position() is None or (self.suspension and self.suspension()):
            self.journal('pas de retour automatique : la position du robot est inconnue')
            return
        if self._pilote():
            return
        delai = float(self.reglages['delai_avant_retour_s'])
        self._retour_prevu = self.horloge() + delai
        self.journal(f'retour au point principal « {self.principal} » dans {delai:.0f} s')

    def _demarrer_retour(self):
        """Le retour automatique : nouveau trajet vers le point principal (mission retour)."""
        self._retour_prevu = None
        pose = self.position()
        if pose is None or (self.suspension and self.suspension()):
            self.journal('retour annulé : la position du robot est inconnue')
            return
        cible = self.principal
        px, py, ptheta = self.routeur.pose_arrivee(cible)
        if math.dist(pose[:2], (px, py)) <= TOLERANCE_RETOUR_M:
            # Déjà au point principal : au plus une rotation sur place, sans annonce
            self._nouvelle_mission('retour', cible)
            self._retour_annonce = False
            self._itineraire, self._reste = [cible], 0.0
            if not self._orienter():
                self._finir_retour()
            return
        verdict = self.preparation() if self.preparation else None
        if verdict is not None:
            self.journal(f'retour annulé : {verdict[1]}')
            return
        self._nouvelle_mission('retour', cible)
        self._retour_annonce = True
        self._evenement('retour')
        self._partir_vers(cible, 'retour')

    def _finir_retour(self):
        """
        Arrivé au point principal, dans le sens de la flèche : attente.

        Événement retour_arrive, sauf si le robot y était déjà.
        """
        annoncer = self._retour_annonce
        cible = self._cible
        pose = self.position()
        detail = ''
        if pose is not None:
            px, py, ptheta = self.routeur.pose_arrivee(cible)
            detail = (f' (à {math.dist(pose[:2], (px, py)):.2f} m et '
                      f'{math.degrees(abs(ecart_angle(pose[2], ptheta))):.0f}° de la flèche)')
        nom = self._nom(cible)
        self._nouvelle_mission(None, None)
        self._changer('attente', f'de retour au point principal « {cible} »{detail}',
                      f'De retour au point principal « {nom} ».')
        if annoncer:
            self._evenement('retour_arrive', salle=cible, nom=nom, mission='retour')

    def _arriver(self):
        """Le moteur dit arrivé : fin de la visite (puis retour prévu), ou fin du retour."""
        self._reste = 0.0
        if self._mission == 'retour':
            if not self._orienter():
                self._finir_retour()
            return
        self._lever_limite()
        self._changer('arrive', f'arrivé à « {self._cible} »')
        phrase = (self.routeur.salles.get(self._cible) or {}).get('phrase_arrivee') or None
        self._evenement('arrivee', texte=phrase)
        self._programmer_retour()

    def _orienter(self):
        """
        Au point principal : se tourne dans le sens de la flèche. True si le robot tourne.

        Pas de rotation sous tolerance_orientation_rad ; la rotation demandée est raccourcie de
        anticipation_rotation_rad (au plus la moitié de l'écart) : le robot dépasse un peu.
        """
        tourner = getattr(self.moteur, 'tourner', None)
        pose = self.position()
        if tourner is None or pose is None or self._essais_orientation >= ESSAIS_ORIENTATION:
            return False
        ecart = ecart_angle(self.routeur.pose_arrivee(self._cible)[2], pose[2])
        tolerance = float(self.reglages.get('tolerance_orientation_rad', SEUIL_ORIENTATION_RAD))
        if abs(ecart) <= tolerance:
            return False
        anticipation = max(0.0, float(self.reglages.get('anticipation_rotation_rad', 0.0)))
        demande = ecart - math.copysign(min(anticipation, abs(ecart) / 2.0), ecart)
        self._essais_orientation += 1
        if not tourner(demande):
            return False
        self._orientation = self.horloge()
        self._changer('retour', f'se tourne de {math.degrees(ecart):.0f}° vers la flèche',
                      'Le robot se tourne dans le sens de la flèche du point principal.')
        return True

    def _suivre_orientation(self, maintenant):
        e = self.moteur.etat()
        fini = e['arrive'] or e['echec'] or not e['en_cours']
        if not fini and maintenant - self._orientation < DELAI_ORIENTATION_S:
            return
        if not fini:
            self.moteur.annuler()
        self._orientation = None
        if not self._orienter():
            self._finir_retour()

    # ------------------------------------------------------------ visiteur

    def _personnes_fraiches(self):
        if self.personnes is None:
            return None
        try:
            return self.personnes()
        except Exception as e:     # noqa: BLE001 : un détecteur fautif n'arrête pas le guide
            self.journal(f'personnes illisibles : {e}')
            return None

    def _chercher_visiteur(self, maintenant, pose):
        """Les DELAI_VISITEUR_DEPART_S du départ : le visiteur est-il derrière ? Sinon : seul."""
        if self._suivi.choisir(self._personnes_fraiches(), maintenant, pose,
                               DISTANCE_VISITEUR_DEPART_M):
            self._recherche_jusqu_a = None
            self.journal(f'visiteur choisi (personne n° {self._suivi.id}, à '
                         f'{self._suivi.distance:.1f} m)')
            self._evenement('depart')
        elif maintenant >= self._recherche_jusqu_a:
            self._recherche_jusqu_a = None
            self._accompagner = False
            self.journal('personne à accompagner : le robot part seul')
            self._evenement('seul')

    def _surveiller_visiteur(self, maintenant, pose):
        """
        En route : ralentit si le visiteur traîne, l'attend s'il est trop loin ou n'est plus vu.

        Renvoie True si le robot s'arrête pour l'attendre.
        """
        obs = self._suivi.observer(self._personnes_fraiches(), maintenant, pose)
        d = obs['distance_m']
        proche_du_but = self._reste is not None and self._reste < DISTANCE_BUT_SANS_ATTENTE_M
        if not proche_du_but and (not obs['vu'] or d > self.reglages['distance_attendre_m']):
            raison = (f'le visiteur est à {d:.1f} m' if obs['vu']
                      else f'le visiteur n\'est plus vu depuis {obs["age_s"] or 0:.0f} s')
            self.moteur.annuler()
            self._attente_visiteur_debut = maintenant
            delai = float(self.reglages['delai_visiteur_s'])
            self._changer('attente_visiteur', raison, 'Le visiteur ne suit plus : le robot '
                          f'l\'attend ({delai:.0f} s au plus).')
            self._evenement('attente_visiteur')
            return True
        if obs['vu'] and d > self.reglages['distance_ralentir_m']:
            if not self._ralenti:
                self._ralenti = True
                pourcentage = self._pourcentage_ralenti()
                self._limiter(pourcentage)
                self.journal(f'le visiteur traîne ({d:.1f} m) : le robot ralentit '
                             f'({pourcentage:.0f} % de la vitesse maximale)')
                self._evenement('ralentir')
        elif self._ralenti and obs['vu'] and \
                d < self.reglages['distance_ralentir_m'] - HYSTERESE_VISITEUR_M:
            self._ralenti = False
            self._lever_limite()
            self.journal('le visiteur suit de nouveau : vitesse normale')
        return False

    def _attendre_visiteur(self, maintenant, pose):
        """Robot arrêté : le visiteur revient (reprise), ou l'attente dure trop (abandon)."""
        if self._suivi.reprendre(self._personnes_fraiches(), maintenant, pose,
                                 self.reglages['distance_ralentir_m']):
            self._ralenti = False
            self._lever_limite()
            self._evenement('visiteur_retrouve')
            self._relancer('le visiteur est revenu')
            return
        delai = float(self.reglages['delai_visiteur_s'])
        if maintenant - self._attente_visiteur_debut >= delai:
            self._evenement('visiteur_perdu')
            self._echouer(f'le visiteur ne suit plus depuis {delai:.0f} s : visite abandonnée',
                          annoncer=False)

    # ------------------------------------------------------------ robot perdu, verrou

    def _verifier_perdu(self, maintenant, pose):
        """
        Robot perdu (repérage perdu, ou plus de position) : arrêt, reprise ou échec.

        Renvoie True si le pas est traité ici.
        """
        raison = self.suspension() if self.suspension else None
        if pose is not None:
            self._position_vue = True
            self._sans_position_depuis = None
        elif self._position_vue:
            if self._sans_position_depuis is None:
                self._sans_position_depuis = maintenant
            elif maintenant - self._sans_position_depuis >= DELAI_TF_PERDU_S and not raison:
                raison = f'plus de position sur la carte depuis {DELAI_TF_PERDU_S:.0f} s'
        delai = float(self.reglages['delai_perdu_s'])
        if self._etat == 'perdu':
            if not raison:
                self._perdu_debut = None
                self._evenement('retrouve')
                self._relancer('le robot sait de nouveau où il est')
            elif maintenant - self._perdu_debut >= delai:
                nom = self._nom(self.principal) if self.principal else None
                ou = f'sur le point principal « {nom} »' if nom else 'sur le point principal'
                self._echouer(f'Le robot est perdu depuis {delai:.0f} s : replacez-le {ou}, puis '
                              'cliquez sur « Repérer le robot ».', retour=False)
            return True
        if not raison:
            return False
        self.moteur.annuler()
        self._orientation = None
        self._perdu_debut = maintenant
        self._changer('perdu', raison,
                      f'Robot perdu ({raison}) : il est arrêté et attend de retrouver sa position '
                      f'({delai:.0f} s au plus).')
        self._evenement('perdu')
        return True

    def _pilote(self):
        if self.maitre is None:
            return False
        try:
            return self.maitre() == 'pilotage'
        except Exception:      # noqa: BLE001
            return False

    def _refuser_pilotage(self):
        self._evenement('pilotage')
        return self._echouer('le robot est piloté à la main (onglet Pilotage) : rendez la main '
                             'pour l\'envoyer', retour=False, annoncer=False)

    def _interrompre_pilotage(self):
        mission = self._mission
        self.moteur.annuler()
        self._nouvelle_mission(None, None)
        self._changer('attente', 'le pilotage a pris la main',
                      'Piloté à la main : le guide s\'est arrêté.')
        self._evenement('pilotage', salle=None, mission=mission)

    # ------------------------------------------------------------ progrès, passants, détours

    def _suivre_progres(self, maintenant, e):
        approche = self._reste is not None and self._reste < DISTANCE_APPROCHE_M
        if e['progresse'] or approche:
            self._dernier_progres = maintenant
            if self._etat == 'bloque':
                self._changer(self._etat_route, 'le robot avance de nouveau')
            return
        immobile = maintenant - self._dernier_progres
        devant = self._passant_devant(maintenant)
        if immobile >= DELAI_BLOQUE_S and devant:
            # Le robot attend sur place : sans cela, Nav2, qui voit les personnes dans sa carte
            # globale, les contournerait de lui-même par un autre couloir
            self.moteur.annuler()
            self._passage_debut = self._passage_vu = maintenant
            self.attentes_passage += 1
            delai = float(self.reglages['delai_passant_s'])
            self._changer('attente_passage', 'une personne bouche le passage (aucun progrès '
                          f'depuis {immobile:.0f} s) : le robot s\'arrête et attend',
                          'Une personne bouche le passage : le robot '
                          f'attend qu\'elle s\'écarte ({delai:.0f} s au plus).')
            self._annoncer_passant(maintenant)
        elif immobile >= DELAI_DETOUR_S:
            self._detourner(f'aucun progrès depuis {immobile:.0f} s')
        elif immobile >= DELAI_BLOQUE_S and self._etat != 'bloque':
            self.arrets += 1
            self._changer('bloque', f'aucun progrès depuis {immobile:.0f} s')

    def _annoncer_passant(self, maintenant):
        """« Pardon, puis-je passer ? », au plus une fois par ANNONCE_PASSANT_S (pas en boucle)."""
        if self._passant_annonce is not None \
                and maintenant - self._passant_annonce < ANNONCE_PASSANT_S:
            return
        self._passant_annonce = maintenant
        self._evenement('passant_gene')

    def _passant_devant(self, maintenant):
        """Vrai si une personne (autre que le visiteur) a été vue devant depuis une seconde."""
        if not self.reglages['passants'] or self.personnes is None:
            return False
        if self._personne_qui_bouche(self._personnes_fraiches(), DISTANCE_PASSANT_M) is not None:
            self._devant_vu_a = maintenant
        return (self._devant_vu_a is not None
                and maintenant - self._devant_vu_a <= PERSISTANCE_DEVANT_S)

    def _personne_qui_bouche(self, personnes, distance):
        """
        La personne (autre que le visiteur) la plus proche devant, ou None.

        Devant : à moins de distance, dans le cône avant du robot ou dans celui de la direction
        du couloir où il est (Nav2 a pu le faire pivoter pour contourner les personnes).
        """
        if not personnes:
            return None
        sauf = self._suivi.id if self._accompagner else None
        p = personne_devant(personnes, distance, sauf=sauf)
        if p is None:
            cap = self._cap_du_couloir()
            if cap is not None:
                p = personne_devant(personnes, distance, sauf=sauf, cap=cap)
        return p

    def _cap_du_couloir(self):
        """Direction du couloir de l'itinéraire où est le robot, dans son repère (rad), ou None."""
        couloir = self._couloir_actuel()
        pose = self.position()
        if couloir is None or pose is None:
            return None
        (ax, ay), (bx, by) = self.routeur.noeuds[couloir[0]], self.routeur.noeuds[couloir[1]]
        if math.hypot(bx - ax, by - ay) < 1e-6:
            return None
        return ecart_angle(math.atan2(by - ay, bx - ax), float(pose[2]))

    def _attendre_passage(self, maintenant):
        """
        Robot arrêté devant des passants : le passage se libère, ou il reste bouché.

        Libre : reprise du trajet. Bouché delai_passant_s : détour, s'il est raisonnable ; sinon
        attente prolongée.
        """
        personnes = self._personnes_fraiches() if self.personnes is not None else None
        restent = [p for p in personnes or () if not p.s_eloigne(VITESSE_ELOIGNEMENT_M_S)]
        # sans message frais du détecteur, on ne sait pas : le passage n'est pas libre
        if personnes is None or self._personne_qui_bouche(
                restent, DISTANCE_PASSANT_M + MARGE_PASSANT_M) is not None:
            self._passage_vu = maintenant
        if maintenant - self._passage_vu >= DELAI_PASSANT_PARTI_S:
            if self._passant_annonce is not None:          # « Merci ! » après « Pardon... »
                self._evenement('passage_libre')
            self._relancer('le passage est libre')
        elif maintenant - self._passage_debut >= float(self.reglages['delai_passant_s']):
            self._detourner(f'le passant bouche le passage depuis '
                            f'{maintenant - self._passage_debut:.0f} s', passant=True)

    # ------------------------------------------------------------ interne

    def _attendre_preparation(self):
        """Une destination attend : part si la navigation est prête, renonce après le délai."""
        but, fin = self._en_attente
        verdict = self.preparation() if self.preparation else None
        if verdict is None:
            self._en_attente = None
            self._commencer_visite(but)
        elif verdict[0] == 'echec':
            self._en_attente = None
            self._echouer(verdict[1])
        elif self.horloge() > fin:
            self._en_attente = None
            self._echouer(f'la navigation n\'est pas prête après {self.delai_preparation:.0f} s '
                          f'({verdict[1]}) : vérifiez « Ce qui tourne » dans l\'onglet Simulation')
        elif verdict[1] != self._message:
            self._changer('attente', verdict[1], verdict[1])

    def _depart(self):
        """Nœud de départ (le plus proche du robot) et position (x, y) du robot, ou None."""
        pose = self.position()
        if pose is not None:
            position = (float(pose[0]), float(pose[1]))
            return self.routeur.noeud_proche(*position), position
        if self.depart_defaut in self.routeur.noeuds:
            self.journal(f'position du robot inconnue : départ supposé à « {self.depart_defaut} »')
            return self.depart_defaut, None
        return self.routeur.noeud_proche(0.0, 0.0), None

    def _partir_vers(self, but, etat='en_route'):
        """Itinéraire depuis la position du robot, envoyé au moteur."""
        depart, position = self._depart()
        if depart is None:
            return self._echouer('le graphe des itinéraires est vide')
        itineraire = self.routeur.itineraire(depart, but)
        if itineraire is None:
            return self._echouer(f'aucun chemin libre de « {depart} » à « {but} »')
        # Le robot est déjà sur le premier couloir : inutile de revenir au nœud de départ
        sauter = (position is not None and len(itineraire) > 1
                  and math.dist(position, self.routeur.noeuds[itineraire[1]])
                  < self.routeur.distance(itineraire[0], itineraire[1]))
        return self._partir(itineraire, self.routeur.poses(itineraire, sauter), etat)

    def _relancer(self, raison):
        """
        Reprise après un arrêt voulu (visiteur revenu, robot retrouvé).

        Nouvel itinéraire depuis la position du robot, dans le même état de route (en_route,
        retour ou detour).
        """
        self.journal(f'reprise : {raison}')
        self._partir_vers(self._cible, self._etat_route)

    def _partir(self, itineraire, poses, etat):
        """Envoie les poses au moteur et passe à l'état donné (en_route, retour ou detour)."""
        self._itineraire = list(itineraire)
        self._reste = self.routeur.longueur(itineraire)
        if self._longueur_directe is None:
            self._longueur_directe = self._reste
        if not self.moteur.demarrer(poses):
            return self._echouer('le moteur a refusé le déplacement')
        self._dernier_progres = self.horloge() + DELAI_DEPART_S
        self._relances = 0
        self._etat_route = etat
        self._changer(etat, 'itinéraire : ' + ' → '.join(itineraire))
        return True

    def _compter_parcours(self, pose):
        """Distance parcourue pendant la mission (détours) et positions récentes (vitesse)."""
        if pose is None:
            return
        if self._derniere_pose is not None:
            self._parcouru += math.dist(pose[:2], self._derniere_pose)
        self._derniere_pose = tuple(pose[:2])
        maintenant = self.horloge()
        self._recentes.append((maintenant, float(pose[0]), float(pose[1])))
        while self._recentes and self._recentes[0][0] < maintenant - FENETRE_VITESSE_S:
            self._recentes.pop(0)

    def _vitesse_recente(self):
        """Vitesse moyenne du robot sur les FENETRE_VITESSE_S dernières secondes (m/s), ou None."""
        r = self._recentes
        if len(r) < 2 or r[-1][0] - r[0][0] < FENETRE_VITESSE_S / 2:
            return None
        chemin = sum(math.dist(a[1:], b[1:]) for a, b in zip(r, r[1:]))
        return chemin / (r[-1][0] - r[0][0])

    def _pourcentage_ralenti(self):
        """
        Limite de vitesse quand le visiteur traîne, en pourcentage de la vitesse maximale de Nav2.

        ralenti × la vitesse mesurée juste avant (si elle et vitesse_max_nav2 sont connues), sinon
        ralenti × 100 ; POURCENTAGE_MIN au moins, ralenti × 100 au plus.
        """
        ralenti = 100.0 * float(self.reglages['ralenti'])
        vmax = float(self.reglages.get('vitesse_max_nav2') or 0.0)
        v = self._vitesse_recente()
        minimum = self._pourcentage_min()
        if vmax <= 0 or v is None or v < VITESSE_MESURABLE_M_S:
            return max(minimum, ralenti)
        return round(max(minimum, min(ralenti, ralenti * v / vmax)), 1)

    def _pourcentage_min(self):
        """Limite de vitesse la plus basse (pourcentage) : avec le pont, la vitesse minimale."""
        return min(100.0, max(0.0, float(self.reglages.get('pourcentage_min', POURCENTAGE_MIN))))

    def _couloir_actuel(self):
        """Couloir (a, b) de l'itinéraire où se trouve le robot, a étant le nœud déjà passé."""
        if len(self._itineraire) < 2:
            return None
        segments = list(zip(self._itineraire, self._itineraire[1:]))
        pose = self.position()
        if pose is not None:
            p = (float(pose[0]), float(pose[1]))
            noeuds = self.routeur.noeuds
            return min(segments, key=lambda s: distance_segment(p, noeuds[s[0]], noeuds[s[1]]))
        # Sans position : on remonte depuis le but de la distance restante
        if self._reste is not None:
            parcouru = self.routeur.longueur(self._itineraire) - self._reste
            for a, b in segments:
                parcouru -= self.routeur.distance(a, b)
                if parcouru < 0:
                    return a, b
            return segments[-1]
        return segments[0]

    def _reprendre(self):
        """Renvoie au moteur la fin de l'itinéraire, à partir du couloir où est le robot."""
        couloir = self._couloir_actuel()
        reste = self._itineraire[self._itineraire.index(couloir[1]):] if couloir \
            else self._itineraire
        self.journal('le moteur a renoncé : nouvel essai par ' + ' → '.join(reste))
        if not self.moteur.demarrer(self.routeur.poses(reste)):
            return self._echouer('le moteur a refusé le déplacement')
        self._dernier_progres = self.horloge() + DELAI_DEPART_S
        return True

    def _detour_raisonnable(self, itineraire, depart):
        """
        Dit si un détour est raisonnable : (oui ou non, longueur totale, limite).

        Longueur totale : parcouru + jusqu'au nœud de départ du détour + détour ; comparée au
        trajet direct de la mission.
        """
        pose = self.position()
        vers_depart = math.dist(pose[:2], self.routeur.noeuds[depart]) if pose is not None else 0.0
        parcouru = self._parcouru
        if not parcouru and self._longueur_directe and self._reste is not None:
            parcouru = max(0.0, self._longueur_directe - self._reste)
        total = parcouru + vers_depart + self.routeur.longueur(itineraire)
        direct = self._longueur_directe or self.routeur.longueur(itineraire)
        limite = max(float(self.reglages['detour_facteur_max']) * direct,
                     direct + float(self.reglages['detour_marge_m']))
        return total <= limite, total, limite

    def _detourner(self, raison, passant=False):
        """
        Annule, marque le couloir bloqué et repart par un autre chemin, s'il est raisonnable.

        passant : le couloir est bouché par des personnes (attente_passage) ; si le détour est
        refusé, le guide les attend encore.
        """
        if self.detours >= MAX_DETOURS:
            return self._echouer(f'{raison}, et déjà {self.detours} détours : abandon')
        couloir = self._couloir_actuel()
        if couloir is None:
            self.moteur.annuler()
            return self._echouer(f'{raison}, et aucun couloir à éviter')
        a, b = couloir
        self.routeur.bloquer(a, b)
        itineraire = self.routeur.itineraire(a, self._cible)
        if itineraire is None:
            self.moteur.annuler()
            return self._echouer(f'aucun autre chemin de « {a} » à « {self._cible} »')
        raisonnable, total, limite = self._detour_raisonnable(itineraire, a)
        if not raisonnable:
            self.routeur.debloquer(a, b)
            if passant and self._prolongations < MAX_PROLONGATIONS_PASSANT:
                self._prolongations += 1
                self._passage_debut = self._passage_vu = self.horloge()
                delai = float(self.reglages['delai_passant_s'])
                self._changer('attente_passage',
                              f'{raison} ; le détour ferait {total:.0f} m (au plus '
                              f'{limite:.0f} m) : le robot attend encore',
                              'Le passage reste encombré et le détour serait trop long '
                              f'({total:.0f} m) : le robot attend encore ({delai:.0f} s au plus).')
                self._passant_annonce = None
                self._annoncer_passant(self.horloge())
                return False
            self.moteur.annuler()
            return self._echouer(f'{raison}, et le seul détour ferait {total:.0f} m, bien plus '
                                 f'que le trajet direct ({self._longueur_directe or 0:.0f} m) : '
                                 'abandon')
        self.moteur.annuler()
        self.journal(f'{raison} : couloir « {a} » – « {b} » marqué bloqué ; détour de '
                     f'{self.routeur.longueur(itineraire):.0f} m (trajet total {total:.0f} m, au '
                     f'plus {limite:.0f} m)')
        self.detours += 1
        self._passage_debut = None
        ok = self._partir(itineraire, self.routeur.poses(itineraire), 'detour')
        if ok:
            self._evenement('detour')
        return ok

    def _echouer(self, raison, retour=True, annoncer=True):
        """
        Arrête le robot (un trajet précédent ne doit pas continuer) et passe en echec.

        retour : le retour automatique suit (visite seulement) ; annoncer : événement echec.
        """
        self.moteur.annuler()
        self._orientation = None
        self._lever_limite()
        self._changer('echec', raison, raison[:1].upper() + raison[1:])
        if annoncer:
            self._evenement('echec')
        if retour:
            self._programmer_retour()
        return False

    def fixer_vitesse_max(self, vitesse, nom=None):
        """
        Vitesse maximale de la personnalité active (m/s, /personnalite/active), ou None : aucune.

        Elle devient un plafond de /speed_limit, en pourcentage de vitesse_max_nav2 ; la limite
        envoyée est toujours la plus petite des deux (visiteur qui traîne, personnalité).
        """
        vmax = float(self.reglages.get('vitesse_max_nav2') or 0.0)
        plafond = None
        if vitesse is not None:
            if vmax <= 0:
                self.journal('vitesse maximale de la personnalité ignorée : vitesse_max_nav2 '
                             'inconnue')
            elif float(vitesse) < vmax:
                plafond = round(max(self._pourcentage_min(), 100.0 * float(vitesse) / vmax), 1)
        if plafond != self._plafond_personnalite:
            self._plafond_personnalite = plafond
            self.journal(f'personnalité « {nom or "?"} » : '
                         + (f'vitesse plafonnée à {plafond:.0f} %' if plafond is not None
                            else 'pas de plafond de vitesse'))
        self._appliquer_limite()

    def _limiter(self, pourcentage):
        """Limite du visiteur (pourcentage), ou None pour la lever ; voir _appliquer_limite."""
        self._limite_visiteur = pourcentage
        self._appliquer_limite()

    def _appliquer_limite(self):
        """Envoie la plus petite des limites (visiteur, personnalité), ou None, si elle change."""
        limites = [v for v in (self._limite_visiteur, self._plafond_personnalite) if v is not None]
        pourcentage = min(limites) if limites else None
        if pourcentage == self._limite:
            return
        self._limite = pourcentage
        if self.limiter_vitesse is not None:
            self.limiter_vitesse(pourcentage)

    def _lever_limite(self):
        self._limiter(None)

    def _nom(self, cible):
        salle = self.routeur.salles.get(cible) if cible else None
        return (salle or {}).get('nom') or cible

    def _evenement(self, code, texte=None, salle='cible', nom=None, mission='mission'):
        """Publie un message au visiteur (/guide/evenement) ; salle et mission : ceux du trajet."""
        if self.au_evenement is None:
            return
        salle = self._cible if salle == 'cible' else salle
        mission = self._mission if mission == 'mission' else mission
        nom = nom or (self._nom(salle) if salle else None)
        try:
            message = evenement(code, salle=salle, nom=nom, texte=texte, mission=mission)
        except KeyError as e:
            self.journal(f'événement inconnu : {e}')
            return
        self.au_evenement(message)

    def _changer(self, etat, raison='', message=''):
        """
        Change d'état, prévient l'utilisateur et appelle au_changement.

        message : phrase du champ message de /guide/etat (vide : pas de champ).
        """
        ancien, ancien_message = self._etat, self._message
        self._etat, self._message = etat, message
        if etat != ancien:
            self._depuis = self.horloge()
        if raison:
            self.journal(f'{etat} : {raison}')
        if self.au_changement is not None and (etat != ancien or etat == 'detour'
                                               or message != ancien_message):
            self.au_changement(self.etat())


# ---------------------------------------------------------------- moteurs


class ErreurMoteur(RuntimeError):
    """Le moteur demandé ne peut pas être créé ; le message dit quoi faire."""


def fabriquer_moteur(nom, noeud=None, depart=(0.0, 0.0, 0.0), vitesse_factice=0.5):
    """Crée le moteur nommé : nav2, unitree ou factice. Lève ErreurMoteur sinon."""
    if nom == 'nav2':
        from g1_nav.moteur_nav2 import MoteurNav2
        return MoteurNav2()
    if nom == 'unitree':
        try:
            from g1_nav.moteur_unitree import MoteurUnitree
        except ImportError as e:
            if getattr(e, 'name', None) == 'g1_nav.moteur_unitree':
                raise ErreurMoteur(
                    'MoteurUnitree est absent : g1_nav/moteur_unitree.py n\'est pas encore '
                    'écrit (agent Scan). Utilisez moteur:=nav2.') from None
            raise ErreurMoteur(f'MoteurUnitree n\'a pas pu être chargé : {e}') from None
        # Le contrat (section 4.6) ne fixe pas le constructeur : on propose le nœud du guide
        try:
            return MoteurUnitree(noeud=noeud)
        except TypeError:
            return MoteurUnitree()
    if nom == 'factice':
        from g1_nav.moteurs import MoteurFactice
        return MoteurFactice(depart=depart, vitesse=vitesse_factice)
    raise ErreurMoteur(f'moteur inconnu : « {nom} » (nav2, unitree ou factice)')


# ---------------------------------------------------------------- nœud ROS 2


class NoeudGuide(Node):
    """Nœud ROS 2 du guide : sujets /guide/*, position par TF map → base_link."""

    def __init__(self):
        super().__init__('guide')
        from rcl_interfaces.msg import ParameterDescriptor
        from rclpy.clock import Clock, ClockType
        from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
        from std_msgs.msg import Empty, String
        import tf2_ros
        from atelier import chemin_lieu
        from atelier.lieu.comportement import (reglages_guide, SUJET_EVENEMENT,
                                               SUJET_LIMITE_VITESSE, SUJET_PERSONNES)

        lieu = self.declare_parameter('lieu', '').value
        etage = self.declare_parameter('etage', '').value
        nom_moteur = self.declare_parameter('moteur', 'nav2').value
        frequence = float(self.declare_parameter('frequence', 5.0).value)
        self.repere_carte = self.declare_parameter('repere_carte', 'map').value
        self.repere_robot = self.declare_parameter('repere_robot', 'base_link').value
        vitesse_factice = float(self.declare_parameter('vitesse_factice', 0.5).value)
        sujet_personnes = self.declare_parameter('sujet_personnes', SUJET_PERSONNES).value
        if not lieu or not etage:
            raise ErreurMoteur('paramètres lieu et etage obligatoires '
                               '(ex. --ros-args -p lieu:=demo -p etage:=rdc)')
        # Délais et distances : défauts, section guide de lieu.yaml, puis ces paramètres s'ils
        # sont donnés (ex. -p delai_avant_retour_s:=5.0) ; et les réglages propres au nœud
        libre = ParameterDescriptor(dynamic_typing=True)
        donnes = {nom: self.declare_parameter(nom, None, libre).value for nom in DELAIS_GUIDE}
        reglages = reglages_guide(chemin_lieu(lieu), **donnes)
        for nom, defaut in REGLAGES_NOEUD.items():
            reglages[nom] = type(defaut)(self.declare_parameter(nom, defaut, libre).value)

        routeur = Routeur.depuis_lieu(lieu, etage)
        if not routeur.noeuds:
            raise ErreurMoteur(f'aucun nœud sur l\'étage « {etage} » dans itineraires.yaml')
        self.id_principal = None         # salle du point principal (vague 4, section 11.2)
        try:
            from atelier.lieu.principal import point_principal
            principal = point_principal(chemin_lieu(lieu))
            if principal is not None and principal.etage == etage \
                    and principal.id in routeur.noeuds:
                self.id_principal = principal.id
        except Exception as e:     # lieu illisible ici : le routeur l'a déjà lu, on s'en passe
            self.get_logger().warn(f'point principal inconnu : {e}')
        if 'accueil' in routeur.noeuds:
            depart = routeur.pose_arrivee('accueil')
        elif self.id_principal:
            depart = routeur.pose_arrivee(self.id_principal)
        else:
            depart = (0, 0, 0)
        self.moteur = fabriquer_moteur(nom_moteur, self, depart, vitesse_factice)

        self.tampon_tf = tf2_ros.Buffer()
        self.ecoute_tf = tf2_ros.TransformListener(self.tampon_tf, self)
        self.String = String
        self.pub_etat = self.create_publisher(String, '/guide/etat', 10)
        self.pub_evenement = self.create_publisher(String, SUJET_EVENEMENT, 10)
        self._limite_msg = None
        try:
            from nav2_msgs.msg import SpeedLimit
            self._limite_msg = SpeedLimit
            self.pub_limite = self.create_publisher(SpeedLimit, SUJET_LIMITE_VITESSE, 10)
        except ImportError:     # nav2_msgs absent : pas de ralenti pour le visiteur
            self.get_logger().warn('nav2_msgs introuvable : le guide ne pourra pas ralentir')
        self._reperage = None            # (dernier /reperage/etat, instant de réception)
        self._personnes = None           # (liste de Personne, instant de réception)
        self._maitre = None              # dernier /mouvement/maitre (dict)
        self.guide = Guide(routeur, self.moteur, position=self.position,
                           journal=self.get_logger().info, au_changement=self.publier,
                           preparation=self.preparation, suspension=self.suspension,
                           reglages=reglages, principal=self.id_principal,
                           personnes=self.personnes, au_evenement=self.publier_evenement,
                           limiter_vitesse=self.limiter_vitesse, maitre=self.maitre)
        self.create_subscription(String, '/guide/aller', self._sur_aller, 10)
        self.create_subscription(Empty, '/guide/stop', self._sur_stop, 10)
        self.create_subscription(String, '/reperage/etat', self._sur_reperage, 10)
        self.create_subscription(String, sujet_personnes, self._sur_personnes, 10)
        # Verrou des mouvements : fiable et transient_local, comme son éditeur (section 11.5)
        verrou = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                            durability=DurabilityPolicy.TRANSIENT_LOCAL,
                            history=HistoryPolicy.KEEP_LAST)
        self.create_subscription(String, '/mouvement/maitre', self._sur_maitre, verrou)
        # Personnalité active (section 11.6) : sa vitesse_max plafonne /speed_limit. Celle du
        # fichier du lieu au démarrage, puis chaque /personnalite/active (fiable, transient_local)
        self.lieu = lieu
        self._personnalite_du_fichier(chemin_lieu(lieu))
        self.create_subscription(String, '/personnalite/active', self._sur_personnalite, verrou)
        # Vague 5 : tolérance de cap, anticipation et ralenti minimal réglables en marche
        self.add_on_set_parameters_callback(self._sur_parametres)
        # Horloge murale : le guide continue de répondre même si la simulation est en pause
        self.create_timer(1.0 / frequence, self._sur_minuterie,
                          clock=Clock(clock_type=ClockType.STEADY_TIME))
        options = ', '.join(f'{k} {v}' for k, v in reglages.items())
        self.get_logger().info(
            f'guide prêt : lieu {lieu}, étage {etage}, moteur {nom_moteur}, '
            f'{len(routeur.noeuds)} nœuds, point principal {self.id_principal or "aucun"}. '
            f'Réglages : {options}. En attente sur /guide/aller.')

    def _sur_parametres(self, parametres):
        """« ros2 param set /guide … » : les REGLAGES_EN_MARCHE changent tout de suite."""
        from rcl_interfaces.msg import SetParametersResult
        for p in parametres:
            raison = refus_reglage_en_marche(p.name, p.value)
            if raison is not None:
                return SetParametersResult(successful=False, reason=raison)
        for p in parametres:
            if p.name in REGLAGES_EN_MARCHE and self.guide.reglages.get(p.name) != p.value:
                self.guide.reglages[p.name] = float(p.value)
                self.get_logger().info(f'réglage changé en marche : {p.name} = {p.value:g}')
        return SetParametersResult(successful=True)

    def position(self):
        """
        Renvoie (x, y, theta) du robot dans map, par TF (moteur factice : sa position), ou None.

        Une position plus vieille que DELAI_TF_PERDU_S (horloge du nœud) compte comme absente.
        """
        from atelier.lieu.conversions import quaternion_vers_cap
        from g1_nav.moteurs import MoteurFactice
        from rclpy.time import Time

        if isinstance(self.moteur, MoteurFactice):
            return self.moteur.position
        try:
            t = self.tampon_tf.lookup_transform(self.repere_carte, self.repere_robot, Time())
        except Exception:     # TF pas encore disponible
            return None
        tampon = Time.from_msg(t.header.stamp)
        if tampon.nanoseconds > 0:
            age = (self.get_clock().now() - tampon).nanoseconds * 1e-9
            if age > DELAI_TF_PERDU_S:
                return None
        return (t.transform.translation.x, t.transform.translation.y,
                quaternion_vers_cap(t.transform.rotation))

    def reperage(self):
        """Dernier /reperage/etat s'il est frais (DELAI_REPERAGE_PERIME_S), sinon None."""
        if self._reperage is None:
            return None
        if time.monotonic() - self._reperage[1] > DELAI_REPERAGE_PERIME_S:
            return None
        return self._reperage[0]

    def preparation(self):
        """
        Dit si la navigation peut partir (section 10.7 du plan).

        None : prête. ('attendre', message) : Nav2 démarre, ou pas encore de position sur la
        carte. ('echec', message) : le relais dit que le robot n'est pas repéré. Seul le moteur
        nav2 a besoin de tout cela ; les autres partent tout de suite.
        """
        from g1_nav.moteur_nav2 import MoteurNav2

        if not isinstance(self.moteur, MoteurNav2):
            return None
        reperage = self.reperage()
        if reperage is not None and not reperage.get('repere'):
            if reperage.get('etat') == 'en_cours':
                return ('attendre', MESSAGE_REPERAGE_EN_COURS)
            if reperage.get('etat') == 'perdu':
                return ('echec', 'Repérage perdu : replacez le robot sur le point principal, puis '
                                 'cliquez sur « Repérer le robot ».')
            return ('echec', MESSAGE_NON_REPERE)
        if self.position() is None or not self.moteur.pret():
            return ('attendre', MESSAGE_PREPARATION)
        return None

    def suspension(self):
        """La raison si le relais dit le repérage perdu (robot perdu), sinon None."""
        reperage = self.reperage()
        if reperage is not None and reperage.get('etat') == 'perdu':
            return MESSAGE_PERDU
        return None

    def personnes(self):
        """Personnes du dernier /personnes/lidar s'il est frais, sinon None."""
        if self._personnes is None \
                or time.monotonic() - self._personnes[1] > DELAI_PERSONNES_PERIME_S:
            return None
        return self._personnes[0]

    def maitre(self):
        """Maître des mouvements (/mouvement/maitre) : « guide » sans message."""
        return (self._maitre or {}).get('maitre', 'guide')

    def limiter_vitesse(self, pourcentage):
        """Publie /speed_limit en pourcentage ; None lève la limite (100 %, jamais 0)."""
        if self._limite_msg is None:
            return
        m = self._limite_msg()
        m.percentage = True
        m.speed_limit = float(pourcentage) if pourcentage else 100.0
        self.pub_limite.publish(m)
        self.get_logger().info(f'/speed_limit : {m.speed_limit:.0f} %')

    def publier_evenement(self, message):
        self.get_logger().info(f'événement {message["code"]} : {message["texte"]}')
        self.pub_evenement.publish(self.String(data=json.dumps(message, ensure_ascii=False)))

    @staticmethod
    def _lire(texte):
        try:
            donnees = json.loads(texte)
        except ValueError:
            return None
        return donnees if isinstance(donnees, dict) else None

    def _sur_reperage(self, msg):
        donnees = self._lire(msg.data)
        if donnees is not None:
            self._reperage = (donnees, time.monotonic())

    def _sur_personnes(self, msg):
        donnees = self._lire(msg.data)
        if donnees is not None:
            self._personnes = (lire_personnes(donnees), time.monotonic())

    def _personnalite_du_fichier(self, dossier):
        try:
            from atelier.lieu.equipe import charger_equipe, personnalite_active
            perso = personnalite_active(charger_equipe(dossier, 'personnalites'))
        except Exception as e:     # noqa: BLE001 : fichier de l'équipe faux, le guide s'en passe
            self.get_logger().warn(f'personnalites.yaml illisible : {e}')
            return
        if perso is not None:
            self._appliquer_personnalite(perso)

    def _appliquer_personnalite(self, perso):
        vitesse = perso.get('vitesse_max')
        if isinstance(vitesse, bool) or not isinstance(vitesse, (int, float)) \
                or not 0 < vitesse <= 0.4:
            vitesse = None
        self.guide.fixer_vitesse_max(vitesse, perso.get('nom') or perso.get('id'))

    def _sur_personnalite(self, msg):
        donnees = self._lire(msg.data)
        if donnees is None or not isinstance(donnees.get('id'), str):
            return
        lieu = donnees.get('lieu')
        if lieu and lieu != self.lieu and lieu != Path(str(self.lieu)).name:
            return      # personnalité d'un autre lieu
        self._appliquer_personnalite(donnees)

    def _sur_maitre(self, msg):
        donnees = self._lire(msg.data)
        if donnees is not None and donnees.get('maitre') in ('guide', 'pilotage'):
            if donnees.get('maitre') != self.maitre():
                self.get_logger().info(f'maître des mouvements : {donnees["maitre"]}')
            self._maitre = donnees

    def publier(self, etat=None):
        self.pub_etat.publish(self.String(data=json.dumps(etat or self.guide.etat(),
                                                          ensure_ascii=False)))

    def _sur_aller(self, msg):
        # /guide/aller : l'id simple (visite sans accompagnement), ou du JSON {cible, accompagner?,
        # retour?, source?} (atelier.lieu.comportement.lire_demande_aller) ; « principal » désigne
        # le point principal (section 11.4 du plan)
        from atelier.lieu.comportement import lire_demande_aller
        try:
            demande = lire_demande_aller(msg.data)
        except ValueError as e:
            self.get_logger().warn(f'/guide/aller illisible : {e}')
            self.guide.refuser(msg.data, f'demande illisible : {e}')
            self.publier()
            return
        self.guide.aller(demande['cible'], accompagner=demande['accompagner'],
                         retour=demande['retour'], source=demande['source'])
        self.publier()

    def _sur_stop(self, _msg):
        self.guide.stop()
        self.publier()

    def _sur_minuterie(self):
        self.guide.pas()
        self.publier()

    def arreter(self):
        """Arrête le robot avant de quitter."""
        try:
            self.moteur.annuler()
        except Exception as e:     # Nav2 déjà arrêté, par exemple
            self.get_logger().warn(f'annulation impossible en quittant : {e}')
        try:
            self.limiter_vitesse(None)
        except Exception:      # noqa: BLE001 : le contexte ROS se ferme
            pass


def main(args=None):
    from rclpy.executors import ExternalShutdownException, SingleThreadedExecutor

    rclpy.init(args=args)
    try:
        noeud = NoeudGuide()
    except Exception as e:     # lieu introuvable, moteur absent... : message clair, sans trace
        print(f'guide : {e}', file=sys.stderr)
        rclpy.try_shutdown()
        return 1
    # Exécuteur propre au guide : MoteurNav2 fait tourner son propre nœud dans l'exécuteur
    # global de rclpy (nav2_simple_commander), il ne faut pas mélanger les deux.
    executeur = SingleThreadedExecutor()
    executeur.add_node(noeud)
    try:
        executeur.spin()
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        signal.signal(signal.SIGINT, signal.SIG_IGN)     # un second Ctrl+C ne coupe pas l'arrêt
        noeud.arreter()
        executeur.shutdown()
        noeud.destroy_node()
        rclpy.try_shutdown()
    return 0


if __name__ == '__main__':
    sys.exit(main())
