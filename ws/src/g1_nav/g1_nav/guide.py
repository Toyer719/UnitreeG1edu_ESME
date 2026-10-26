"""
Guide : emmène le robot jusqu'à une salle ou un nœud, et change de couloir s'il est coincé.

Sujets ROS 2 (section 4.2 du plan) :
  /guide/aller  std_msgs/String  id de salle ou de nœud (« b204 », « accueil »)
  /guide/stop   std_msgs/Empty   arrêt immédiat
  /guide/etat   std_msgs/String  JSON {"etat", "cible", "reste_m", "itineraire", "message"?}, 5
                                 fois par seconde et à chaque changement d'état ; message
                                 (facultatif, section 10.7) : phrase pour l'utilisateur
  /reperage/etat std_msgs/String JSON du relais odom_vers_tf (section 10.5), écouté

États : attente, en_route, bloque, detour, arrive, echec.
  - bloque : la distance restante ne baisse plus depuis 3 s (5 s juste après le départ) ;
  - detour : coincé depuis 8 s, le guide a annulé, marqué le couloir bloqué (120 s), puis
    il est reparti par un autre chemin. L'état reste « detour » jusqu'à l'arrivée.
  - attente avec un message, après /guide/aller : la navigation n'est pas encore prête (Nav2
    démarre, ou le robot n'a pas encore de position sur la carte). Le guide réessaie à chaque
    pas, DELAI_PREPARATION_S au plus, puis echec. Sans position sur la carte et si le relais dit
    que le robot n'est pas repéré : echec tout de suite (« Robot non repéré... »).
  - en route, repérage perdu : le pont arrête le robot. Ce n'est pas un couloir bouché : le guide
    ne compte pas ce temps-là (ni bloque, ni détour) et le dit dans le message ; il reprend seul
    quand le robot est de nouveau repéré.

Le guide ne parle jamais directement à Nav2 : il passe par un Moteur (moteurs.py). Le
paramètre ROS « moteur » le choisit : nav2 (MoteurNav2), unitree (MoteurUnitree, écrit par
l'agent Scan) ou factice (MoteurFactice, pour les essais sans simulation).

La logique (classe Guide) n'utilise pas ROS : elle se teste avec un moteur factice. Le nœud
ROS (NoeudGuide) l'appelle depuis un seul fil, environ 5 fois par seconde.

  ros2 run g1_nav guide --ros-args -p lieu:=demo -p etage:=rdc -p moteur:=nav2
"""
import json
import math
import signal
import sys
import time

from g1_nav.routeur import CibleInconnue, Routeur

try:
    import rclpy
    from rclpy.node import Node
except ImportError:      # logique seule, sans ROS (tests)
    rclpy = None
    Node = object

ETATS = ('attente', 'en_route', 'bloque', 'detour', 'arrive', 'echec')

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
MESSAGE_PERDU = ('Repérage perdu : le robot est arrêté, il repartira dès qu\'il aura retrouvé sa '
                 'position.')
# /reperage/etat plus vieux : on ne s'y fie plus
DELAI_REPERAGE_PERIME_S = 2.0


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


class Guide:
    """Machine à états du guide, sans ROS : routeur + moteur + position du robot."""

    def __init__(self, routeur, moteur, position=None, horloge=time.monotonic,
                 journal=None, au_changement=None, depart_defaut='accueil', preparation=None,
                 delai_preparation=DELAI_PREPARATION_S, suspension=None):
        """
        Prépare le guide.

        routeur       : Routeur de l'étage ;
        moteur        : un Moteur (moteurs.py) ;
        position      : fonction sans argument qui renvoie (x, y, theta) dans map, ou None ;
        horloge       : temps en secondes (fausse horloge des tests) ;
        journal       : fonction qui reçoit les messages pour l'utilisateur (print par défaut) ;
        au_changement : fonction appelée avec etat() à chaque changement d'état ;
        depart_defaut : nœud de départ quand la position du robot est inconnue ;
        preparation   : fonction sans argument : None si la navigation est prête, sinon
                        ('attendre', message) ou ('echec', message) ;
        delai_preparation : attente maximale de la navigation après /guide/aller, en s ;
        suspension    : fonction sans argument : None si le robot peut avancer, sinon le message
                        qui dit pourquoi il est arrêté (repérage perdu) ; ce temps ne
                        compte pas pour bloque ni détour.
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
        self._etat = 'attente'
        self._message = ''
        self._en_attente = None          # (cible, fin de l'attente) : départ dès que prêt
        self._cible = None
        self._itineraire = []
        self._reste = None
        self._dernier_progres = horloge()
        self._etat_route = 'en_route'    # en_route, ou detour après un changement de couloir
        self._relances = 0
        self.detours = 0
        self.arrets = 0

    # ------------------------------------------------------------ commandes

    def aller(self, cible):
        """Part vers une salle ou un nœud. Renvoie True si le robot est parti (ou va partir)."""
        self.detours = 0
        self.arrets = 0
        self._etat_route = 'en_route'
        self._en_attente = None
        try:
            but = self.routeur.resoudre(cible)
        except CibleInconnue as e:
            self._cible, self._itineraire, self._reste = str(cible).strip(), [], None
            return self._echouer(f'cible inconnue : {e}')
        self._cible = but
        verdict = self.preparation() if self.preparation else None
        if verdict is not None:
            genre, message = verdict
            if genre == 'echec':
                return self._echouer(message)
            self._en_attente = (but, self.horloge() + self.delai_preparation)
            self._itineraire, self._reste = [], None
            self._changer('attente', message, message)
            return True
        return self._partir_vers(but)

    def _partir_vers(self, but):
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
        return self._partir(itineraire, self.routeur.poses(itineraire, sauter), 'en_route')

    def stop(self):
        """Arrête le robot tout de suite ; le guide revient en attente."""
        self._en_attente = None
        self.moteur.annuler()
        self._cible, self._itineraire, self._reste = None, [], None
        self._changer('attente', 'arrêt demandé')

    def pas(self):
        """Lit l'état du moteur et fait avancer la machine à états. Renvoie etat()."""
        if self._en_attente is not None:
            self._attendre_preparation()
            return self.etat()
        if self._etat not in ('en_route', 'bloque', 'detour'):
            return self.etat()
        e = self.moteur.etat()
        maintenant = self.horloge()
        if e['reste_m'] is not None:
            self._reste = e['reste_m']
        if e['arrive']:
            self._reste = 0.0
            self._changer('arrive', f'arrivé à « {self._cible} »')
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
        elif self._suspendre(maintenant):
            pass
        else:
            approche = self._reste is not None and self._reste < DISTANCE_APPROCHE_M
            if e['progresse'] or approche:
                self._dernier_progres = maintenant
                if self._etat == 'bloque':
                    self._changer(self._etat_route, 'le robot avance de nouveau')
            immobile = maintenant - self._dernier_progres
            if immobile >= DELAI_DETOUR_S:
                self._detourner(f'aucun progrès depuis {immobile:.0f} s')
            elif immobile >= DELAI_BLOQUE_S and self._etat != 'bloque':
                self.arrets += 1
                self._changer('bloque', f'aucun progrès depuis {immobile:.0f} s')
        return self.etat()

    def etat(self):
        """Renvoie l'état à publier sur /guide/etat, au format des sections 4.2 et 10.7 du plan."""
        reste = None if self._reste is None else round(float(self._reste), 2)
        etat = {'etat': self._etat, 'cible': self._cible, 'reste_m': reste,
                'itineraire': list(self._itineraire)}
        if self._message:
            etat['message'] = self._message
        return etat

    @property
    def en_attente(self):
        """Vrai si une destination attend que la navigation soit prête."""
        return self._en_attente is not None

    # ------------------------------------------------------------ interne

    def _suspendre(self, maintenant):
        """Vrai si le robot est arrêté sans obstacle (repérage perdu) : le temps ne compte pas."""
        pause = self.suspension() if self.suspension else None
        if pause:
            self._dernier_progres = maintenant
            if pause != self._message:
                self._changer(self._etat, pause, pause)
            return True
        if self._message:
            self._changer(self._etat, 'le robot peut de nouveau avancer')
        return False

    def _attendre_preparation(self):
        """Une destination attend : part si la navigation est prête, renonce après le délai."""
        but, fin = self._en_attente
        verdict = self.preparation() if self.preparation else None
        if verdict is None:
            self._en_attente = None
            self._partir_vers(but)
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

    def _partir(self, itineraire, poses, etat):
        """Envoie les poses au moteur et passe à l'état donné (en_route ou detour)."""
        self._itineraire = list(itineraire)
        self._reste = self.routeur.longueur(itineraire)
        if not self.moteur.demarrer(poses):
            return self._echouer('le moteur a refusé le déplacement')
        self._dernier_progres = self.horloge() + DELAI_DEPART_S
        self._relances = 0
        self._etat_route = etat
        self._changer(etat, 'itinéraire : ' + ' → '.join(itineraire))
        return True

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

    def _detourner(self, raison):
        """Annule, marque le couloir actuel bloqué et repart par un autre chemin."""
        if self.detours >= MAX_DETOURS:
            return self._echouer(f'{raison}, et déjà {self.detours} détours : abandon')
        couloir = self._couloir_actuel()
        self.moteur.annuler()
        if couloir is None:
            return self._echouer(f'{raison}, et aucun couloir à éviter')
        a, b = couloir
        self.routeur.bloquer(a, b)
        self.journal(f'{raison} : couloir « {a} » – « {b} » marqué bloqué')
        itineraire = self.routeur.itineraire(a, self._cible)
        if itineraire is None:
            return self._echouer(f'aucun autre chemin de « {a} » à « {self._cible} »')
        self.detours += 1
        return self._partir(itineraire, self.routeur.poses(itineraire), 'detour')

    def _echouer(self, raison):
        """Arrête le robot (un trajet précédent ne doit pas continuer) et passe en echec."""
        self.moteur.annuler()
        self._changer('echec', raison, raison[:1].upper() + raison[1:])
        return False

    def _changer(self, etat, raison='', message=''):
        """
        Change d'état, prévient l'utilisateur et appelle au_changement.

        message : phrase du champ message de /guide/etat (vide : pas de champ).
        """
        ancien, ancien_message = self._etat, self._message
        self._etat, self._message = etat, message
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
        from rclpy.clock import Clock, ClockType
        from std_msgs.msg import Empty, String
        import tf2_ros

        lieu = self.declare_parameter('lieu', '').value
        etage = self.declare_parameter('etage', '').value
        nom_moteur = self.declare_parameter('moteur', 'nav2').value
        frequence = float(self.declare_parameter('frequence', 5.0).value)
        self.repere_carte = self.declare_parameter('repere_carte', 'map').value
        self.repere_robot = self.declare_parameter('repere_robot', 'base_link').value
        vitesse_factice = float(self.declare_parameter('vitesse_factice', 0.5).value)
        if not lieu or not etage:
            raise ErreurMoteur('paramètres lieu et etage obligatoires '
                               '(ex. --ros-args -p lieu:=demo -p etage:=rdc)')

        routeur = Routeur.depuis_lieu(lieu, etage)
        if not routeur.noeuds:
            raise ErreurMoteur(f'aucun nœud sur l\'étage « {etage} » dans itineraires.yaml')
        depart = routeur.pose_arrivee('accueil') if 'accueil' in routeur.noeuds else (0, 0, 0)
        self.moteur = fabriquer_moteur(nom_moteur, self, depart, vitesse_factice)

        self.tampon_tf = tf2_ros.Buffer()
        self.ecoute_tf = tf2_ros.TransformListener(self.tampon_tf, self)
        self.String = String
        self.pub_etat = self.create_publisher(String, '/guide/etat', 10)
        self._reperage = None            # (dernier /reperage/etat, instant de réception)
        self.guide = Guide(routeur, self.moteur, position=self.position,
                           journal=self.get_logger().info, au_changement=self.publier,
                           preparation=self.preparation, suspension=self.suspension)
        self.create_subscription(String, '/guide/aller', self._sur_aller, 10)
        self.create_subscription(Empty, '/guide/stop', self._sur_stop, 10)
        self.create_subscription(String, '/reperage/etat', self._sur_reperage, 10)
        # Horloge murale : le guide continue de répondre même si la simulation est en pause
        self.create_timer(1.0 / frequence, self._sur_minuterie,
                          clock=Clock(clock_type=ClockType.STEADY_TIME))
        self.get_logger().info(
            f'guide prêt : lieu {lieu}, étage {etage}, moteur {nom_moteur}, '
            f'{len(routeur.noeuds)} nœuds. En attente sur /guide/aller.')

    def position(self):
        """(x, y, theta) du robot dans map, par TF ; position du moteur factice ; ou None."""
        from atelier.lieu.conversions import quaternion_vers_cap
        from g1_nav.moteurs import MoteurFactice
        from rclpy.time import Time

        if isinstance(self.moteur, MoteurFactice):
            return self.moteur.position
        try:
            t = self.tampon_tf.lookup_transform(self.repere_carte, self.repere_robot, Time())
        except Exception:     # TF pas encore disponible
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
            return ('echec', MESSAGE_NON_REPERE)
        if self.position() is None or not self.moteur.pret():
            return ('attendre', MESSAGE_PREPARATION)
        return None

    def suspension(self):
        """Message si le relais dit le repérage perdu (le pont a arrêté le robot), sinon None."""
        reperage = self.reperage()
        if reperage is not None and reperage.get('etat') == 'perdu':
            return MESSAGE_PERDU
        return None

    def _sur_reperage(self, msg):
        try:
            donnees = json.loads(msg.data)
        except ValueError:
            return
        if isinstance(donnees, dict):
            self._reperage = (donnees, time.monotonic())

    def publier(self, etat=None):
        self.pub_etat.publish(self.String(data=json.dumps(etat or self.guide.etat(),
                                                          ensure_ascii=False)))

    def _sur_aller(self, msg):
        self.guide.aller(msg.data)
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
