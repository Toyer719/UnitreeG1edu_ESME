"""Pont entre le serveur web et ROS 2 : un nœud rclpy qui tourne dans un fil de fond.

  écoute   /odom (nav_msgs/Odometry)       position du robot, repère map (simulation :
                                            map → odom est l'identité, contrat 4.2)
           /guide/etat (std_msgs/String)    état du guide, en JSON
           /clock (rosgraph_msgs/Clock)     temps simulé, pour placer les piétons à l'écran
           /reperage/etat (std_msgs/String) état du repérage (JSON, relais odom_vers_tf, vague 3)
           /pont/etat (std_msgs/String)     état du pont vers la marche (JSON, g1_bridge, vague 3)
  publie   /guide/aller (std_msgs/String)   id de la salle ou du nœud où aller
           /guide/stop (std_msgs/Empty)     arrêt immédiat
           /reperage/demander (String)      « Repérer le robot » (JSON {id, x?, y?, theta?})
           /pont/arret (std_msgs/Bool)      verrou du pont (fiable, transient_local, profondeur 1)
  demande  /bt_navigator/get_state          Nav2 est-il actif ? (sinon un but envoyé trop tôt,
                                            juste après le lancement, est refusé)
  vague 4  les sujets JSON de SUJETS_JSON (événements du guide, piétons, verrou des mouvements,
  (11)     personnes vues, pilotage, équipe) : dernier(sujet), historique(sujet) ; et les
           publications de PUBLICATIONS_JSON : publier_json(sujet, donnees). Les routes des agents de
           la vague 4 s'en servent sans modifier ce fichier.
  vague 5  les images de la caméra de poitrine (SUJETS_IMAGES : /camera_poitrine/image/compressed
  (12.7)   et /visiteurs/image/compressed, sensor_msgs/CompressedImage, QoS des capteurs) : la
           dernière de chacune est gardée dans images[sujet] (atelier.equipe.images.DernieresImages),
           lue par les routes /api/camera/* ; l'état du nœud camera_usb (/camera_poitrine/etat) est
           un sujet JSON de plus.

Le nœud a son propre contexte rclpy : il n'installe pas de gestionnaire de Ctrl+C (c'est
uvicorn qui s'en occupe) et ne gêne pas un autre nœud du même processus. Il respecte
ROS_DOMAIN_ID. Si rclpy est introuvable (env.sh pas chargé), le pont reste inactif et
dit pourquoi ; le reste de l'Atelier fonctionne.
"""
import importlib
import json
import threading
import time

from atelier.equipe.images import DernieresImages
from atelier.lieu import quaternion_vers_cap
from atelier.lieu.equipe import SUJET_ETAT_CAMERA, SUJETS_IMAGES

PERIMEE_S = 2.0      # s : au-delà, la position du robot est signalée comme ancienne
REPERAGE_PERIME_S = 2.0   # s : au-delà, /reperage/etat et /pont/etat sont tenus pour muets
FINS_REPERAGE = ("repere", "echec")

# Vague 4 (section 11 du plan) : sujets JSON (std_msgs/String) écoutés, avec le nombre de messages
# gardés (0 : le dernier seulement) et la QoS : « ecoute » (au mieux, compatible avec tout éditeur)
# ou « verrou » (fiable et transient_local : on reçoit le dernier message publié avant notre arrivée)
SUJETS_JSON = {
    "/guide/evenement": (50, "ecoute"),        # comportement du guide (11.4)
    "/pietons/etat": (0, "ecoute"),            # piétons crédibles de g1_sim (11.3)
    "/personnes/lidar": (0, "ecoute"),         # détecteur de personnes au LiDAR (11.4)
    "/mouvement/maitre": (0, "verrou"),        # verrou des mouvements (11.5)
    "/pilotage/etat": (0, "ecoute"),           # nœud pilotage (11.5)
    "/visiteurs/detectes": (0, "ecoute"),      # caméra de l'équipe (11.6)
    "/personnalite/active": (0, "verrou"),     # personnalité active (11.6)
    "/robot/dire": (20, "ecoute"),             # phrases à dire (11.6)
    SUJET_ETAT_CAMERA: (0, "ecoute"),          # état du nœud camera_usb (12.7)
}
# Publications possibles par les routes : sujet → (forme, QoS). « texte » : le texte brut ;
# « json » : un dict, envoyé en JSON
PUBLICATIONS_JSON = {
    "/visiteur/texte": ("texte", "defaut"),
    "/robot/dire": ("json", "defaut"),
    "/personnalite/active": ("json", "verrou"),
}
PIETONS_FRAIS_S = 1.0     # s : /pietons/etat plus vieux, l'Atelier recalcule les piétons depuis le monde


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
        self._reperage = None        # (dernier /reperage/etat, instant de réception)
        self._etat_pont = None       # (dernier /pont/etat, instant de réception)
        self._fins = {}              # id de demande → (état final repere ou echec, instant)
        self._condition = threading.Condition()
        self._pub_demande = None
        self._pub_arret = None
        self._Bool = None
        self._json = {}              # sujet → [(dict, instant de réception)], le plus récent à la fin
        self._pubs_json = {}         # sujet → publieur
        # vague 5 : dernière image JPEG de chaque sujet d'images (caméra de poitrine, visiteurs)
        self.images = {sujet: DernieresImages() for sujet in SUJETS_IMAGES}
        self.erreur_images = None

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
        from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
        from lifecycle_msgs.srv import GetState
        from nav_msgs.msg import Odometry
        from rosgraph_msgs.msg import Clock
        from std_msgs.msg import Bool, Empty, String

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
        # vague 3 : repérage et pont (section 10 du plan)
        noeud.create_subscription(String, "/reperage/etat", self._recevoir_reperage, ecoute)
        noeud.create_subscription(String, "/pont/etat", self._recevoir_pont, ecoute)
        self._pub_demande = noeud.create_publisher(String, "/reperage/demander", 10)
        # verrou : transient_local des deux côtés, sinon le pont ne l'entend pas (règle DDS)
        verrou = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                            durability=DurabilityPolicy.TRANSIENT_LOCAL, history=HistoryPolicy.KEEP_LAST)
        self._pub_arret = noeud.create_publisher(Bool, "/pont/arret", verrou)
        self._Bool = Bool
        # vague 4 : sujets JSON écoutés et publiés (section 11)
        for sujet, (_, qos) in SUJETS_JSON.items():
            noeud.create_subscription(String, sujet, self._recepteur_json(sujet),
                                      verrou if qos == "verrou" else ecoute)
        for sujet, (_, qos) in PUBLICATIONS_JSON.items():
            self._pubs_json[sujet] = noeud.create_publisher(String, sujet, verrou if qos == "verrou" else 10)
        # vague 5 : images de la caméra (JPEG), QoS des capteurs (au mieux, profondeur 2)
        try:
            from sensor_msgs.msg import CompressedImage
        except ImportError as e:
            self.erreur_images = f"sensor_msgs introuvable ({e}) : les images de la caméra ne s'affichent pas"
        else:
            capteurs = QoSProfile(depth=2, reliability=ReliabilityPolicy.BEST_EFFORT,
                                  durability=DurabilityPolicy.VOLATILE, history=HistoryPolicy.KEEP_LAST)
            for sujet in SUJETS_IMAGES:
                noeud.create_subscription(CompressedImage, sujet, self._recepteur_image(sujet), capteurs)
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

    @staticmethod
    def _lire_json(texte):
        try:
            donnees = json.loads(texte)
        except ValueError:
            return None
        return donnees if isinstance(donnees, dict) else None

    def _recevoir_reperage(self, msg):
        donnees = self._lire_json(msg.data)
        if donnees is None:
            return
        maintenant = time.monotonic()
        with self._condition:
            self._reperage = (donnees, maintenant)
            if donnees.get("etat") in FINS_REPERAGE and donnees.get("demande"):
                self._fins[str(donnees["demande"])] = (donnees, maintenant)
                if len(self._fins) > 50:
                    self._fins.pop(next(iter(self._fins)))
            self._condition.notify_all()

    def _recevoir_pont(self, msg):
        donnees = self._lire_json(msg.data)
        if donnees is not None:
            self._etat_pont = (donnees, time.monotonic())

    def _recepteur_json(self, sujet):
        garder = max(1, SUJETS_JSON[sujet][0])

        def recevoir(msg):
            donnees = self._lire_json(msg.data)
            if donnees is None:
                return
            with self._condition:
                liste = self._json.setdefault(sujet, [])
                liste.append((donnees, time.monotonic()))
                del liste[:-garder]
        return recevoir

    def _recepteur_image(self, sujet):
        images = self.images[sujet]

        def recevoir(msg):
            donnees = msg.data
            octets = donnees.tobytes() if hasattr(donnees, "tobytes") else bytes(donnees)
            images.ajouter(octets, temps=msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9)
        return recevoir

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

    def reperer(self, demande):
        """Publie une demande de repérage (dict {id, x?, y?, theta?}) sur /reperage/demander.
        Renvoie le nombre de nœuds qui écoutent (0 : le relais odom_vers_tf ne tourne pas)."""
        if not self.actif:
            raise RuntimeError(self.erreur or "le pont ROS 2 n'est pas démarré")
        with self._condition:
            self._fins.pop(str(demande.get("id")), None)
        self._pub_demande.publish(self._Chaine(data=json.dumps(demande)))
        return self._pub_demande.get_subscription_count()

    def abonnes_reperage(self):
        """Nombre de nœuds abonnés à /reperage/demander (le relais du repérage)."""
        return self._pub_demande.get_subscription_count() if self.actif else 0

    def attendre_reperage(self, ident, delai):
        """Attend l'état final (repere ou echec) de la demande ident, au plus delai secondes.
        Renvoie le message /reperage/etat, ou None."""
        fin = time.monotonic() + delai
        with self._condition:
            while str(ident) not in self._fins:
                reste = fin - time.monotonic()
                if reste <= 0:
                    return None
                self._condition.wait(min(reste, 0.2))
            return dict(self._fins[str(ident)][0])

    def bloquer(self, verrou):
        """Publie le verrou du pont sur /pont/arret. Renvoie le nombre de nœuds qui écoutent."""
        if not self.actif:
            raise RuntimeError(self.erreur or "le pont ROS 2 n'est pas démarré")
        self._pub_arret.publish(self._Bool(data=bool(verrou)))
        return self._pub_arret.get_subscription_count()

    def reperage(self):
        """Dernier /reperage/etat, avec age_recu_s et perime ; None si jamais reçu."""
        return self._avec_age(self._reperage)

    def etat_pont(self):
        """Dernier /pont/etat, avec age_recu_s et perime ; None si jamais reçu."""
        return self._avec_age(self._etat_pont)

    @staticmethod
    def _avec_age(recu):
        if recu is None:
            return None
        donnees, instant = recu
        age = time.monotonic() - instant
        return dict(donnees, age_recu_s=round(age, 2), perime=age > REPERAGE_PERIME_S)

    # ------------------------------------------------------------ vague 4 : sujets JSON (section 11)

    def dernier(self, sujet):
        """Dernier message JSON reçu sur un sujet de SUJETS_JSON, avec age_recu_s et perime ; None si rien."""
        with self._condition:
            liste = self._json.get(sujet)
            recu = liste[-1] if liste else None
        return self._avec_age(recu)

    def historique(self, sujet):
        """Messages gardés d'un sujet de SUJETS_JSON (le plus ancien d'abord), chacun avec age_recu_s."""
        maintenant = time.monotonic()
        with self._condition:
            liste = list(self._json.get(sujet, []))
        return [dict(d, age_recu_s=round(maintenant - t, 2)) for d, t in liste]

    def publier_json(self, sujet, donnees):
        """Publie sur un sujet de PUBLICATIONS_JSON (texte brut, ou dict en JSON). Renvoie le nombre
        de nœuds qui écoutent. KeyError pour un autre sujet ; RuntimeError sans pont ROS 2."""
        if sujet not in PUBLICATIONS_JSON:
            raise KeyError(f"sujet non prévu pour le serveur : {sujet} ({', '.join(PUBLICATIONS_JSON)})")
        if not self.actif:
            raise RuntimeError(self.erreur or "le pont ROS 2 n'est pas démarré")
        forme = PUBLICATIONS_JSON[sujet][0]
        texte = str(donnees) if forme == "texte" else json.dumps(donnees, ensure_ascii=False)
        publieur = self._pubs_json[sujet]
        publieur.publish(self._Chaine(data=texte))
        return publieur.get_subscription_count()

    # ------------------------------------------------------------ vague 5 : images (section 12.7)

    def derniere_image(self, sujet):
        """Dernière image (atelier.equipe.images.ImageRecue) d'un sujet de SUJETS_IMAGES, ou None."""
        images = self.images.get(sujet)
        return images.derniere() if images is not None else None

    def etat_images(self):
        """{sujet: {recue, numero, age_s, largeur, hauteur, octets, ips}} des sujets d'images."""
        return {sujet: images.etat() for sujet, images in self.images.items()}

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
        self._reperage = self._etat_pont = None
        with self._condition:
            self._fins.clear()
            # le verrou des mouvements et la personnalité active ne dépendent pas de la simulation
            for sujet in list(self._json):
                if SUJETS_JSON[sujet][1] != "verrou":
                    del self._json[sujet]
