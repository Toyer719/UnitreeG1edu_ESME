"""
Nœud ROS 2 « pilotage » : passe les messages au cœur (coeur.py) et publie ses sorties.

  sorties  /api/sport/request, /api/arm/request, /api/voice/request (unitree_api/Request, fiable)
           /arm_sdk (unitree_hg/LowCmd), 50 Hz pendant une chorégraphie seulement
           /mouvement/maitre (std_msgs/String JSON, fiable, transient_local, profondeur 1)
           /pilotage/etat (std_msgs/String JSON, 2 Hz et à chaque changement)
           /guide/stop (std_msgs/Empty), /robot/dire (std_msgs/String JSON)
  entrées  /api/<service>/response (unitree_api/Response, au mieux),
           /lowstate (unitree_hg/LowState),
           /guide/etat, /pont/etat (std_msgs/String JSON), /lf/bmsstate (unitree_hg/BmsState,
           batterie, à vérifier sur le robot)
           /personnalite/active (std_msgs/String JSON, fiable, transient_local) : LED du mode ;
           /robot/geste (std_msgs/String JSON) : geste demandé par l'équipe, robot au repos

Le pas de la logique (homme mort, lecture du mode, chorégraphie) tourne dans un fil à 50 Hz, à
échéances absolues sur l'horloge monotone (jamais le temps simulé).
"""
import json
import threading
import time

from .logique import ArretGuide, Bras, D, Dire, Envoi, Maitre

PERIODE_S = 1.0 / D.FREQUENCE_BRAS_HZ
PERIODE_ETAT_S = 0.5
ATTENTE_SORTIE_S = 0.5
DESCENTE_MAX_S = 2.0            # à la sortie : temps laissé à la descente du poids des bras


def remplir_requete(requete, identifiant, api_id, parametre):
    """Remplit un unitree_api/msg/Request comme le SDK d'Unitree (et le pont g1_bridge)."""
    entete = requete.header
    entete.identity.id = int(identifiant)
    entete.identity.api_id = int(api_id)
    entete.lease.id = 0
    entete.policy.priority = 0
    entete.policy.noreply = False
    requete.parameter = str(parametre)
    requete.binary = []
    return requete


def remplir_lowcmd(commande, bras):
    """Remplit un unitree_hg/msg/LowCmd (rt/arm_sdk) : bras, taille, poids dans motor_cmd[29].q."""
    for moteur in commande.motor_cmd:
        moteur.q = moteur.dq = moteur.tau = moteur.kp = moteur.kd = 0.0
    for indice, q in bras.q.items():
        # jamais : la logique ne les donne pas, on le revérifie
        if indice in D.INDICES_JAMBES:
            continue
        moteur = commande.motor_cmd[indice]
        moteur.q = float(q)
        moteur.kp = float(bras.kp.get(indice, 0.0))
        moteur.kd = float(bras.kd.get(indice, 0.0))
    commande.motor_cmd[D.INDICE_POIDS].q = float(max(0.0, min(1.0, bras.poids)))
    return commande


def creer_noeud(coeur):
    """Le nœud pilotage (rclpy déjà initialisé), relié au cœur."""
    from rclpy.node import Node
    from rclpy.qos import (DurabilityPolicy, HistoryPolicy, qos_profile_sensor_data, QoSProfile,
                           ReliabilityPolicy)
    from std_msgs.msg import Empty, String
    from unitree_api.msg import Request, Response
    from unitree_hg.msg import BmsState, LowCmd, LowState

    class NoeudPilotage(Node):
        """pilotage : services sport, arm et voice, rt/arm_sdk, verrou des mouvements."""

        def __init__(self):
            super().__init__('pilotage')
            self.coeur = coeur
            self.Request, self.LowCmd, self.String, self.Empty = Request, LowCmd, String, Empty
            fiable = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE,
                                durability=DurabilityPolicy.VOLATILE)
            reponses = QoSProfile(depth=50, reliability=ReliabilityPolicy.BEST_EFFORT,
                                  durability=DurabilityPolicy.VOLATILE)
            verrou = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                                durability=DurabilityPolicy.TRANSIENT_LOCAL,
                                history=HistoryPolicy.KEEP_LAST)
            ecoute = QoSProfile(depth=5, reliability=ReliabilityPolicy.BEST_EFFORT)
            self.pubs = {s: self.create_publisher(Request, f'{prefixe}/request', fiable)
                         for s, prefixe in D.SERVICES.items()}
            for service, prefixe in D.SERVICES.items():
                self.create_subscription(Response, f'{prefixe}/response', self._sur_reponse,
                                         reponses)
            self.pub_bras = self.create_publisher(LowCmd, D.SUJET_ARM_SDK, fiable)
            self.pub_maitre = self.create_publisher(String, D.SUJET_MAITRE, verrou)
            self.pub_etat = self.create_publisher(String, D.SUJET_ETAT, 10)
            self.pub_stop = self.create_publisher(Empty, '/guide/stop', 10)
            self.pub_dire = self.create_publisher(String, '/robot/dire', 10)
            self.create_subscription(LowState, D.SUJET_LOWSTATE, self._sur_lowstate,
                                     qos_profile_sensor_data)
            self.create_subscription(BmsState, '/lf/bmsstate', self._sur_batterie,
                                     qos_profile_sensor_data)
            self.create_subscription(String, '/guide/etat', self._recepteur('sur_guide_etat'),
                                     ecoute)
            self.create_subscription(String, '/pont/etat', self._recepteur('sur_pont_etat'),
                                     ecoute)
            # Équipe (assemblage de la vague 4) : LED de la personnalité active, gestes demandés
            self.create_subscription(String, '/personnalite/active',
                                     self._demande('appliquer_personnalite'), verrou)
            self.create_subscription(String, '/robot/geste', self._demande('geste_auto'), 10)
            self.commande_bras = LowCmd()
            self.bras_publies = 0
            self.dernier_etat = None
            self.t_etat = 0.0

        # ---------------------------------------------------- sorties

        def publier(self, sorties):
            for s in sorties:
                if isinstance(s, Envoi):
                    self.pubs[s.service].publish(
                        remplir_requete(self.Request(), s.identifiant, s.api_id, s.parametre))
                    if s.raison not in ('lecture_fsm', 'joystick', 'pas'):
                        self.get_logger().info(f'{s.service} {s.api_id} {s.parametre} '
                                               f'({s.raison})')
                elif isinstance(s, Bras):
                    self.pub_bras.publish(remplir_lowcmd(self.commande_bras, s))
                    self.bras_publies += 1
                elif isinstance(s, ArretGuide):
                    self.pub_stop.publish(self.Empty())
                    self.get_logger().info(f'/guide/stop ({s.raison})')
                elif isinstance(s, Maitre):
                    self.pub_maitre.publish(self.String(data=json.dumps(s.message,
                                                                        ensure_ascii=False)))
                    self.get_logger().info(f'maître des mouvements : {s.message["maitre"]} '
                                           f'({s.message["par"]})')
                elif isinstance(s, Dire):
                    self.pub_dire.publish(self.String(data=json.dumps(s.message,
                                                                      ensure_ascii=False)))

        def publier_etat(self, forcer=False):
            etat = self.coeur.etat()
            cle = (etat['maitre'], etat['activite'], etat['fsm'], etat['robot_repond'],
                   etat['bras_tenus'],
                   json.dumps(etat['dernier_refus'], default=str), etat['message'])
            t = time.monotonic()
            if not forcer and cle == self.dernier_etat and t - self.t_etat < PERIODE_ETAT_S:
                return
            self.dernier_etat, self.t_etat = cle, t
            self.pub_etat.publish(self.String(data=json.dumps(etat, ensure_ascii=False,
                                                              default=str)))

        # ---------------------------------------------------- entrées

        def _sur_reponse(self, msg):
            identite = msg.header.identity
            self.coeur.sur_reponse(identite.id, msg.header.status.code, msg.data)

        def _sur_lowstate(self, msg):
            self.coeur.entree('sur_lowstate', [m.q for m in msg.motor_state])

        def _sur_batterie(self, msg):
            self.coeur.entree('sur_batterie', msg.soc)

        def _demande(self, nom):
            """Message JSON de l'équipe → entrée de la logique qui envoie des ordres (journalisée)."""
            def recevoir(msg):
                try:
                    donnees = json.loads(msg.data)
                except ValueError:
                    self.get_logger().warn(f'{nom} : message illisible')
                    return
                resultat = self.coeur.faire(nom, donnees)
                detail = resultat.corps.get('detail', '')
                if resultat.ok:
                    self.get_logger().info(detail)
                else:
                    self.get_logger().warn(f'{detail} ({resultat.statut})')
            return recevoir

        def _recepteur(self, nom):
            def recevoir(msg):
                try:
                    donnees = json.loads(msg.data)
                except ValueError:
                    return
                self.coeur.entree(nom, donnees)
            return recevoir

    return NoeudPilotage()


class Boucle:
    """Fil à 50 Hz : le pas de la logique à échéances absolues, et l'état du pilotage."""

    def __init__(self, coeur, noeud):
        self.coeur = coeur
        self.noeud = noeud
        self.fin = threading.Event()
        self.fil = threading.Thread(target=self._tourner, name='pilotage 50 Hz', daemon=True)
        self.retards = 0

    def demarrer(self):
        self.fil.start()
        return self

    def _tourner(self):
        t = time.monotonic()
        while not self.fin.is_set():
            try:
                self.coeur.pas(t)
                self.noeud.publier_etat()
            except Exception as erreur:      # noqa: B902 (le fil ne doit jamais mourir en silence)
                self.noeud.get_logger().error(f'pas du pilotage : {erreur!r}')
            t += PERIODE_S
            attente = t - time.monotonic()
            if attente > 0:
                self.fin.wait(attente)
            elif attente < -2 * PERIODE_S:
                # trop en retard : on se recale (les bras ne sautent pas)
                self.retards += 1
                t = time.monotonic()

    def arreter(self):
        self.fin.set()
        if self.fil.is_alive():
            self.fil.join(timeout=2.0)
