"""
Nœud pont_g1 : /cmd_vel de Nav2 → ordres de marche 7105 du G1 (section 10.3 du plan).

  ros2 run g1_bridge pont [--ros-args --params-file config/pont.yaml]
  ros2 run g1_bridge pont --ros-args -p exiger_reperage:=false     (essai au portique seulement)

Entrées : /cmd_vel (geometry_msgs/Twist), /api/sport/response (unitree_api/Response, best_effort),
/reperage/etat (std_msgs/String JSON), /guide/stop (std_msgs/Empty), /pont/arret (std_msgs/Bool,
fiable et transient_local), /mouvement/maitre (std_msgs/String JSON, fiable et transient_local,
vague 4 : « pilotage » fait ignorer /cmd_vel, état pilotage).
Sorties : /api/sport/request (unitree_api/Request, fiable, profondeur 10) et /pont/etat
(std_msgs/String JSON, schéma etat_pont, 2 Hz et à chaque changement d'état).

Les règles (plafonds, délais, garde, verrou, repérage, robot muet, refus) sont dans logique.py.
Tous les délais comptent en temps mural monotone (minuteries sur l'horloge STEADY), jamais en
temps simulé. Le pont ne publie jamais sur /cmd_vel ni sur un sujet de Gazebo. Au lancement, il
envoie un arrêt (vérification du lien) ; à la sortie (Ctrl+C, SIGTERM), un arrêt, avant de quitter.
"""
import json
import signal
import sys

from .logique import ErreurReglages, Pont, Reglages
from .requete import remplir_requete, SUJET_REPONSE, SUJET_REQUETE

# Les règles sont évaluées toutes les 20 ms (chien de garde, cadence de 10 Hz, arrêts répétés)
PERIODE_PAS_S = 0.02
# Les abonnés à /api/sport/request (le service sport) sont comptés tous les 10 pas (0,2 s)
PAS_PAR_COMPTE_ABONNES = 10
PERIODE_ETAT_S = 0.5
# Attente de l'accusé de réception de l'arrêt envoyé en quittant
ATTENTE_SORTIE_S = 0.5


class Sortie(Exception):
    """Levée par SIGINT ou SIGTERM dans le fil principal : le pont envoie un arrêt et quitte."""


def _signal_vers_sortie(numero, _cadre):
    raise Sortie(signal.Signals(numero).name)


def lire_reglages(noeud):
    """Déclare les paramètres du nœud (défauts du contrat) ; renvoie (Reglages, sujets)."""
    defauts = Reglages()
    valeurs = {}
    for nom in Reglages.noms():
        defaut = getattr(defauts, nom)
        valeurs[nom] = noeud.declare_parameter(nom, defaut).value
        if isinstance(defaut, float) and isinstance(valeurs[nom], int) \
                and not isinstance(valeurs[nom], bool):
            valeurs[nom] = float(valeurs[nom])
    sujet_requete = noeud.declare_parameter('sujet_requete', SUJET_REQUETE).value
    sujet_reponse = noeud.declare_parameter('sujet_reponse', SUJET_REPONSE).value
    return Reglages(**valeurs), sujet_requete, sujet_reponse


def creer_noeud():
    """Le nœud pont_g1 (rclpy déjà initialisé). ErreurReglages si un réglage est refusé."""
    from geometry_msgs.msg import Twist
    from rclpy.clock import Clock, ClockType
    from rclpy.node import Node
    from rclpy.qos import (DurabilityPolicy, QoSProfile, ReliabilityPolicy)
    from std_msgs.msg import Bool, Empty, String
    from unitree_api.msg import Request, Response

    class NoeudPont(Node):
        """pont_g1 : passe les messages à la logique (Pont) et publie ses requêtes."""

        def __init__(self):
            super().__init__('pont_g1')
            reglages, sujet_requete, sujet_reponse = lire_reglages(self)
            self.pont = Pont(reglages)          # ErreurReglages : le nœud ne démarre pas
            self.Request = Request
            self.String = String
            journal = self.get_logger()

            fiable = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE,
                                durability=DurabilityPolicy.VOLATILE)
            reponses = QoSProfile(depth=50, reliability=ReliabilityPolicy.BEST_EFFORT,
                                  durability=DurabilityPolicy.VOLATILE)
            verrou = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                                durability=DurabilityPolicy.TRANSIENT_LOCAL)
            self.pub_requete = self.create_publisher(Request, sujet_requete, fiable)
            self.pub_etat = self.create_publisher(String, '/pont/etat', 10)
            self.create_subscription(Response, sujet_reponse, self._sur_reponse, reponses)
            self.create_subscription(Twist, '/cmd_vel', self._sur_cmd_vel, 10)
            self.create_subscription(String, '/reperage/etat', self._sur_reperage, 10)
            self.create_subscription(Empty, '/guide/stop', self._sur_guide_stop, 10)
            self.create_subscription(Bool, '/pont/arret', self._sur_verrou, verrou)
            self.create_subscription(String, '/mouvement/maitre', self._sur_maitre, verrou)

            # Temps mural monotone, même si use_sim_time est vrai
            mural = Clock(clock_type=ClockType.STEADY_TIME)
            self.create_timer(PERIODE_PAS_S, self._pas, clock=mural)
            self.create_timer(PERIODE_ETAT_S, self._publier_etat, clock=mural)

            self.dernier_etat = None
            self.reperage_illisible = False
            self.maitre_illisible = False
            self.pas_effectues = 0
            r = reglages
            journal.info(
                f'pont {"/cmd_vel"} → {sujet_requete} (7105) : plafonds vx {r.vx_max:g} m/s, '
                f'vy {r.vy_max:g} m/s, wz {r.wz_max:g} rad/s ; consigne de {r.duree_consigne:g} s '
                f'à {r.frequence:g} Hz ; arrêt après {r.delai_cmd_vel:g} s sans /cmd_vel ; '
                f'repérage {"exigé" if r.exiger_reperage else "NON exigé (essai au portique)"}')
            if not r.exiger_reperage:
                journal.warning('exiger_reperage est faux : le robot bougera sans être repéré. '
                                'À n\'utiliser qu\'au portique, télécommande en main.')
            # Arrêt de lancement : tout de suite si le service sport est déjà vu, sinon dès
            # qu'il apparaît (découverte DDS)
            self._publier(self.pont.demarrer(self.pub_requete.get_subscription_count()))
            self._publier_etat()

        # -------------------------------------------------------- publication

        def _publier(self, envois):
            for envoi in envois:
                self.pub_requete.publish(
                    remplir_requete(self.Request(), envoi.identifiant, envoi.parametre))
                if envoi.raison not in ('consigne',):
                    self.get_logger().info(f'arrêt envoyé ({envoi.raison})')
            if envois:
                self._publier_etat(seulement_si_change=True)

        def _publier_etat(self, seulement_si_change=False):
            etat = self.pont.etat()
            cle = (etat['etat'], etat['mouvement_permis'], etat['reperage'], etat['code'])
            if seulement_si_change and cle == self.dernier_etat:
                return
            if cle[0] != (self.dernier_etat or (None,))[0]:
                self._journaliser(etat)
            self.dernier_etat = cle
            self.pub_etat.publish(self.String(data=json.dumps(etat, ensure_ascii=False)))

        def _journaliser(self, etat):
            journal = self.get_logger()
            texte = f'état {etat["etat"]} : {etat["message"]}'
            if etat['etat'] == 'refus':
                journal.error(texte)
            elif etat['etat'] in ('robot_muet', 'arret_verrouille', 'attente_reperage'):
                journal.warning(texte)
            else:
                journal.info(texte)

        # -------------------------------------------------------- entrées

        def _sur_cmd_vel(self, msg):
            self._publier(self.pont.sur_cmd_vel(msg.linear.x, msg.linear.y, msg.angular.z))

        def _sur_reponse(self, msg):
            identite = msg.header.identity
            if not self.pont.sur_reponse(identite.id, msg.header.status.code):
                return                       # réponse à un autre client du robot
            if msg.header.status.code != 0:
                self.get_logger().error(
                    f'réponse {identite.id} (api {identite.api_id}) : code '
                    f'{msg.header.status.code}, data {msg.data!r}',
                    throttle_duration_sec=2.0)
            self._publier_etat(seulement_si_change=True)

        def _sur_reperage(self, msg):
            try:
                repere = json.loads(msg.data).get('repere') is True
                self.reperage_illisible = False
            except (ValueError, AttributeError):
                if not self.reperage_illisible:
                    self.get_logger().warning(f'/reperage/etat illisible : {msg.data[:200]!r}')
                self.reperage_illisible = True
                repere = False
            self._publier(self.pont.sur_reperage(repere))
            self._publier_etat(seulement_si_change=True)

        def _sur_guide_stop(self, _msg):
            self._publier(self.pont.sur_guide_stop())

        def _sur_maitre(self, msg):
            try:
                maitre = json.loads(msg.data).get('maitre')
                envois = self.pont.sur_maitre(maitre)
                self.maitre_illisible = False
            except (ValueError, AttributeError):
                if not self.maitre_illisible:
                    self.get_logger().warning(f'/mouvement/maitre illisible : {msg.data[:200]!r}')
                self.maitre_illisible = True
                return
            self.get_logger().info(f'maître des mouvements : {maitre}')
            self._publier(envois)
            self._publier_etat(seulement_si_change=True)

        def _sur_verrou(self, msg):
            self._publier(self.pont.sur_verrou(bool(msg.data)))
            self._publier_etat(seulement_si_change=True)

        def _pas(self):
            self.pas_effectues += 1
            if self.pas_effectues % PAS_PAR_COMPTE_ABONNES == 0:
                self._publier(self.pont.sur_abonnes(self.pub_requete.get_subscription_count()))
            self._publier(self.pont.pas())
            self._publier_etat(seulement_si_change=True)

        def quitter(self):
            """Arrêt envoyé en quittant ; attend son accusé de réception (0,5 s au plus)."""
            from rclpy.duration import Duration
            self._publier(self.pont.quitter())
            try:
                self.pub_requete.wait_for_all_acked(Duration(seconds=ATTENTE_SORTIE_S))
            except Exception:       # noqa: B902 (selon le RMW, l'accusé peut manquer)
                pass

    return NoeudPont()


def main(args=None):
    import rclpy
    from rclpy.executors import ExternalShutdownException, SingleThreadedExecutor
    from rclpy.signals import SignalHandlerOptions

    # Nos propres gestionnaires de SIGINT et SIGTERM : rclpy fermerait le contexte avant que
    # l'arrêt de sortie ne parte
    rclpy.init(args=args, signal_handler_options=SignalHandlerOptions.NO)
    signal.signal(signal.SIGINT, _signal_vers_sortie)
    signal.signal(signal.SIGTERM, _signal_vers_sortie)
    try:
        noeud = creer_noeud()
    except ErreurReglages as erreur:
        print(f'pont_g1 : réglage refusé, le pont ne démarre pas : {erreur}', file=sys.stderr)
        rclpy.try_shutdown()
        return 1
    except Sortie:
        rclpy.try_shutdown()
        return 0
    executeur = SingleThreadedExecutor()
    executeur.add_node(noeud)
    try:
        executeur.spin()
    except (Sortie, KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        signal.signal(signal.SIGINT, signal.SIG_IGN)     # un second signal ne coupe pas l'arrêt
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        try:
            noeud.quitter()
            noeud.get_logger().info('pont arrêté (arrêt envoyé au robot)')
        except Exception as erreur:     # noqa: B902 (contexte déjà fermé : rien à faire)
            print(f'pont_g1 : arrêt de sortie impossible : {erreur}', file=sys.stderr)
        executeur.shutdown(timeout_sec=1.0)
        noeud.destroy_node()
        rclpy.try_shutdown()
    return 0


if __name__ == '__main__':
    sys.exit(main())
