"""Pont entre le serveur web et ROS 2 : un nœud rclpy qui tourne dans un fil de fond.

  écoute   /odom (nav_msgs/Odometry)       position du robot, repère map (simulation :
                                            map → odom est l'identité, contrat 4.2)
           /guide/etat (std_msgs/String)    état du guide, en JSON
           /clock (rosgraph_msgs/Clock)     temps simulé, pour placer les piétons à l'écran
  publie   /guide/aller (std_msgs/String)   id de la salle ou du nœud où aller
           /guide/stop (std_msgs/Empty)     arrêt immédiat
  demande  /bt_navigator/get_state          Nav2 est-il actif ? (sinon un but envoyé trop tôt,
                                            juste après le lancement, est refusé)

Le nœud a son propre contexte rclpy : il n'installe pas de gestionnaire de Ctrl+C (c'est
uvicorn qui s'en occupe) et ne gêne pas un autre nœud du même processus. Il respecte
ROS_DOMAIN_ID. Si rclpy est introuvable (env.sh pas chargé), le pont reste inactif et
dit pourquoi ; le reste de l'Atelier fonctionne.
"""
import importlib
import json
import threading
import time

from atelier.lieu import quaternion_vers_cap

PERIMEE_S = 2.0      # s : au-delà, la position du robot est signalée comme ancienne


class PontRos:
    def __init__(self, nom_noeud="atelier_pont"):
        self.nom_noeud = nom_noeud
        self.actif = False
        self.erreur = None
        self._robot = None           # (x, y, theta, instant de réception)
        self._guide = None           # (dict, instant de réception)
        self._temps_sim = None       # (secondes simulées, instant de réception)
        self._nav2 = None            # (Nav2 actif ?, instant de la réponse) ; None : pas de Nav2 vu
        self._client_nav2 = None
        self._fil = None
        self._pret = threading.Event()
        self._fin = threading.Event()
        self._noeud = None
        self._pub_aller = None
        self._pub_stop = None
        self._Chaine = None
        self._Vide = None

    # ------------------------------------------------------------ démarrage et arrêt

    def demarrer(self, attente=10.0):
        """Démarre le nœud dans un fil. Renvoie True si le pont est prêt."""
        if self.actif:
            return True
        try:
            importlib.import_module("rclpy")       # ROS 2 chargé ? (env.sh)
        except ImportError as e:
            self.erreur = (f"ROS 2 est introuvable ({e}) : lancez l'Atelier avec g1-atelier, "
                           "qui charge ~/robot-g1/setup/env.sh")
            return False
        self._fin.clear()
        self._pret.clear()
        self._fil = threading.Thread(target=self._boucle, name="pont ROS 2", daemon=True)
        self._fil.start()
        self._pret.wait(attente)
        return self.actif

    def arreter(self):
        """Arrête le nœud et attend la fin du fil."""
        self._fin.set()
        if self._fil is not None:
            self._fil.join(timeout=5.0)
        self.actif = False

    def _boucle(self):
        import rclpy
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
        from lifecycle_msgs.srv import GetState
        from nav_msgs.msg import Odometry
        from rosgraph_msgs.msg import Clock
        from std_msgs.msg import Empty, String

        contexte = rclpy.Context()
        try:
            rclpy.init(context=contexte)
            noeud = rclpy.create_node(self.nom_noeud, context=contexte)
        except Exception as e:      # noqa: BLE001 : on veut le message, quel qu'il soit
            self.erreur = f"le nœud ROS 2 du serveur n'a pas pu démarrer : {e}"
            self._pret.set()
            return
        # « au mieux » à la réception : compatible avec tous les éditeurs (fiables ou non)
        ecoute = QoSProfile(depth=5, reliability=ReliabilityPolicy.BEST_EFFORT,
                            history=HistoryPolicy.KEEP_LAST)
        noeud.create_subscription(Odometry, "/odom", self._recevoir_odom, ecoute)
        noeud.create_subscription(String, "/guide/etat", self._recevoir_guide, ecoute)
        noeud.create_subscription(Clock, "/clock", self._recevoir_horloge, ecoute)
        self._pub_aller = noeud.create_publisher(String, "/guide/aller", 10)
        self._pub_stop = noeud.create_publisher(Empty, "/guide/stop", 10)
        self._Chaine, self._Vide = String, Empty
        self._client_nav2 = noeud.create_client(GetState, "/bt_navigator/get_state")
        self._DemandeEtat = GetState.Request
        noeud.create_timer(1.0, self._sonder_nav2)
        self._noeud = noeud
        executeur = SingleThreadedExecutor(context=contexte)
        executeur.add_node(noeud)
        self.actif = True
        self.erreur = None
        self._pret.set()
        try:
            while not self._fin.is_set() and contexte.ok():
                executeur.spin_once(timeout_sec=0.1)
        finally:
            self.actif = False
            executeur.shutdown()
            noeud.destroy_node()
            try:
                rclpy.shutdown(context=contexte)
            except Exception:       # noqa: BLE001 : déjà arrêté
                pass

    # ------------------------------------------------------------ réception

    def _recevoir_odom(self, msg):
        p, q = msg.pose.pose.position, msg.pose.pose.orientation
        try:
            theta = quaternion_vers_cap(q)
        except ValueError:          # quaternion nul : on garde l'orientation précédente
            theta = self._robot[2] if self._robot else 0.0
        self._robot = (p.x, p.y, theta, time.monotonic())

    def _recevoir_guide(self, msg):
        try:
            donnees = json.loads(msg.data)
            if not isinstance(donnees, dict):
                raise ValueError
        except ValueError:
            donnees = {"etat": "inconnu", "texte": msg.data}
        self._guide = (donnees, time.monotonic())

    def _recevoir_horloge(self, msg):
        self._temps_sim = (msg.clock.sec + msg.clock.nanosec * 1e-9, time.monotonic())

    def _sonder_nav2(self):
        """Une fois par seconde : demande l'état du navigateur de Nav2 (actif ou non)."""
        if not self._client_nav2.service_is_ready():
            if self._nav2 is not None and time.monotonic() - self._nav2[1] > 3.0:
                self._nav2 = None          # Nav2 arrêté
            return
        futur = self._client_nav2.call_async(self._DemandeEtat())

        def reponse(f):
            try:
                self._nav2 = (f.result().current_state.label == "active", time.monotonic())
            except Exception:       # noqa: BLE001 : service parti entre-temps
                self._nav2 = None
        futur.add_done_callback(reponse)

    # ------------------------------------------------------------ commandes

    def aller(self, cible):
        """Publie la cible sur /guide/aller. Renvoie le nombre de nœuds qui écoutent ce sujet."""
        if not self.actif:
            raise RuntimeError(self.erreur or "le pont ROS 2 n'est pas démarré")
        self._pub_aller.publish(self._Chaine(data=str(cible)))
        return self._pub_aller.get_subscription_count()

    def stop(self):
        """Publie sur /guide/stop. Renvoie le nombre de nœuds qui écoutent ce sujet."""
        if not self.actif:
            raise RuntimeError(self.erreur or "le pont ROS 2 n'est pas démarré")
        self._pub_stop.publish(self._Vide())
        return self._pub_stop.get_subscription_count()

    def abonnes_aller(self):
        """Nombre de nœuds abonnés à /guide/aller (0 : le guide n'est pas lancé)."""
        return self._pub_aller.get_subscription_count() if self.actif else 0

    # ------------------------------------------------------------ état

    def temps_sim(self):
        """Temps simulé actuel (s), extrapolé depuis le dernier /clock, ou None."""
        if self._temps_sim is None:
            return None
        t, recu = self._temps_sim
        # si l'horloge s'est arrêtée (simulation en pause ou finie), on n'extrapole pas
        ecart = time.monotonic() - recu
        return t + ecart if ecart < 1.0 else t

    def etat(self):
        """{actif, erreur, robot, guide, nav2} pour le WebSocket. robot et guide valent None sans données ;
        nav2 : True (Nav2 actif), False (Nav2 démarre), None (pas de Nav2 en vue)."""
        maintenant = time.monotonic()
        robot = None
        if self._robot is not None:
            x, y, theta, recu = self._robot
            age = maintenant - recu
            robot = {"x": round(x, 3), "y": round(y, 3), "theta": round(theta, 4),
                     "age_s": round(age, 2), "perimee": age > PERIMEE_S}
        guide = None
        if self._guide is not None:
            donnees, recu = self._guide
            guide = dict(donnees, age_s=round(maintenant - recu, 2))
        nav2 = None
        if self._nav2 is not None and maintenant - self._nav2[1] < 5.0:
            nav2 = self._nav2[0]
        return {"actif": self.actif, "erreur": self.erreur, "robot": robot, "guide": guide, "nav2": nav2}

    def oublier(self):
        """Efface la dernière position et le dernier état du guide (nouvelle simulation)."""
        self._robot = self._guide = self._temps_sim = self._nav2 = None
