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
  vague 6  les sujets de la démo et de la voix (/accueil/etat, /accueil/evenement, /voix/etat, /voix/son) et
  (13)     leurs entrées (/accueil/choix, /accueil/commande, /voix/commande) dans SUJETS_JSON et PUBLICATIONS_JSON ;
           pour le diagnostic : sujets() et infos_sujet(sujet) (le graphe ROS 2, sans le nœud du serveur),
           attendre_message(sujet, type, delai) (un message typé : batterie /lf/bmsstate…), et
           appeler_unitree(service, api_id, parametre) : une requête unitree_api au robot, seulement parmi
           atelier.lieu.diagnostic.APPELS_UNITREE_PERMIS (robot_state 1003 et 1001, sport 7001 en lecture).

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
NOEUD_GUIDE = "guide"     # nom du nœud du guide (g1_nav, navigation.launch.py le lance sans le renommer)
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
    # vague 6 (section 13 du plan) : démo d'accueil (nœud accueil) et voix (nœud voix)
    "/accueil/etat": (0, "ecoute"),            # état de la démo (13.4)
    "/accueil/evenement": (50, "ecoute"),      # événements de la démo, réponses aux choix et commandes (13.4)
    "/voix/etat": (0, "ecoute"),               # état du nœud voix (13.6)
    "/voix/son": (20, "ecoute"),               # phrases prêtes pour la borne (13.6)
}
# Publications possibles par les routes : sujet → (forme, QoS). « texte » : le texte brut ;
# « json » : un dict, envoyé en JSON
PUBLICATIONS_JSON = {
    "/visiteur/texte": ("texte", "defaut"),
    "/robot/dire": ("json", "defaut"),
    "/personnalite/active": ("json", "verrou"),
    # vague 6 (section 13 du plan) : la borne et l'Atelier parlent à la démo et à la voix
    "/accueil/choix": ("json", "defaut"),
    "/accueil/commande": ("json", "defaut"),
    "/voix/commande": ("json", "defaut"),
}
# Vague 6 (section 13.2) : requêtes unitree_api du diagnostic (le robot ne les reçoit que de cette liste)
DELAI_ABONNE_UNITREE_S = 2.0      # attente d'un abonné à /api/<service>/request avant d'envoyer
# Les nœuds de l'Atelier sur le PC qui ne font qu'écouter ou interroger le robot : ils ne prouvent jamais que le
# robot est là (corrections de la vague 6 : l'enregistreur de la séance, abonné à /api/sport/request, était pris
# pour le robot par le diagnostic). Plus les outils « ros2 » en ligne de commande (ros2 topic echo, le démon).
NOEUDS_ATELIER = frozenset({"atelier_pont", "g1_diagnostic", "atelier_boite_noire"})
PREFIXES_NOEUDS_OUTILS = ("_ros2cli",)
PIETONS_FRAIS_S = 1.0     # s : /pietons/etat plus vieux, l'Atelier recalcule les piétons depuis le monde


def noeud_observateur(nom):
    """Vrai pour un nœud de l'Atelier qui écoute ou interroge le robot sans en être un (NOEUDS_ATELIER) et pour les
    outils ros2 en ligne de commande (PREFIXES_NOEUDS_OUTILS) : le diagnostic ne les compte jamais comme le robot."""
    nom = str(nom or "").lstrip("/")
    return nom in NOEUDS_ATELIER or nom.startswith(PREFIXES_NOEUDS_OUTILS)


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
        # vague 6 : requêtes unitree_api du diagnostic (créées au premier appel de chaque service)
        self._unitree = {}           # service → publieur de /api/<service>/request
        self._reponses_unitree = {}  # identity.id d'une de NOS requêtes → (code, data)
        self._attendus_unitree = set()   # identity.id des requêtes en attente de réponse
        self._verrou_unitree = threading.Lock()
        self._numero_unitree = 0
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
        """Publie sur /guide/stop. Renvoie le nombre de nœuds qui écoutent ce sujet (le guide, mais aussi le pont
        vers la marche g1_bridge, qui s'arrête aussi sur /guide/stop)."""
        if not self.actif:
            raise RuntimeError(self.erreur or "le pont ROS 2 n'est pas démarré")
        self._pub_stop.publish(self._Vide())
        return self._pub_stop.get_subscription_count()

    def guides_a_l_ecoute(self):
        """Nombre de guides (nœuds nommés « guide », g1_nav) abonnés à /guide/stop ; le pont vers la marche, qui
        l'écoute aussi, ne compte pas (relecture du 01/11/2026). None si on ne peut pas le savoir."""
        if not self.actif or self._noeud is None:
            return None
        try:
            infos = self._noeud.get_subscriptions_info_by_topic("/guide/stop")
        except Exception:       # noqa: BLE001 : graphe ROS indisponible (arrêt en cours)
            return None
        return sum(1 for i in infos if i.node_name == NOEUD_GUIDE)

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

    # ------------------------------------------------------------ vague 6 : graphe et requêtes du diagnostic

    def sujets(self):
        """{sujet: [types]} de tout le graphe ROS 2 vu par le serveur ; {} sans pont."""
        if not self.actif or self._noeud is None:
            return {}
        try:
            return {nom: list(types) for nom, types in self._noeud.get_topic_names_and_types()}
        except Exception:       # noqa: BLE001 : graphe indisponible (arrêt en cours)
            return {}

    def infos_sujet(self, sujet):
        """{publieurs: [nœuds], abonnes: [nœuds]} d'un sujet, sans le nœud du serveur lui-même ni les autres nœuds
        de l'Atelier qui ne font qu'observer (noeud_observateur : l'enregistreur de la séance, g1-diagnostic,
        ros2 topic echo) : un sujet « vu » par le diagnostic est publié ou écouté par un autre programme, le
        robot ou le faux G1 ; None sans pont."""
        if not self.actif or self._noeud is None:
            return None
        try:
            publieurs = self._noeud.get_publishers_info_by_topic(sujet)
            abonnes = self._noeud.get_subscriptions_info_by_topic(sujet)
        except Exception:       # noqa: BLE001 : graphe indisponible
            return None

        def autres(infos):
            return sorted({i.node_name for i in infos
                           if i.node_name != self.nom_noeud and not noeud_observateur(i.node_name)})
        return {"publieurs": autres(publieurs), "abonnes": autres(abonnes)}

    def attendre_message(self, sujet, type_message, delai=2.0):
        """Le prochain message d'un sujet typé (ex. « unitree_hg/msg/BmsState » sur /lf/bmsstate, la batterie),
        reçu en moins de delai secondes (QoS des capteurs : au mieux), ou None. L'abonnement ne dure que l'attente.
        RuntimeError sans pont ROS 2 ; ValueError pour un type introuvable."""
        if not self.actif or self._noeud is None:
            raise RuntimeError(self.erreur or "le pont ROS 2 n'est pas démarré")
        try:
            paquet, _, nom = str(type_message).replace("/msg/", "/").partition("/")
            classe = getattr(importlib.import_module(f"{paquet}.msg"), nom)
        except (ImportError, AttributeError, ValueError):
            raise ValueError(f"type de message introuvable : {type_message}") from None
        from rclpy.qos import qos_profile_sensor_data
        recu = []
        arrive = threading.Event()

        def recevoir(msg):
            if not recu:
                recu.append(msg)
                arrive.set()
        abonnement = self._noeud.create_subscription(classe, sujet, recevoir, qos_profile_sensor_data)
        try:
            arrive.wait(delai)
        finally:
            try:
                self._noeud.destroy_subscription(abonnement)
            except Exception:       # noqa: BLE001 : nœud en cours d'arrêt
                pass
        return recu[0] if recu else None

    def appeler_unitree(self, service, api_id, parametre="{}", delai=2.0):
        """Une requête au robot (unitree_api/Request sur /api/<service>/request) et sa réponse : (code, data).
        Seulement les appels de APPELS_UNITREE_PERMIS, avec leur paramètre exact (verifier_appel_unitree : 1001 ne
        fait que démarrer un service de la cartographie ; PermissionError sinon, avant toute publication) ;
        RuntimeError sans pont ROS 2 ou sans unitree_api ; TimeoutError si personne n'écoute ou si la réponse
        n'arrive pas dans le délai."""
        from atelier.lieu.diagnostic import verifier_appel_unitree
        verifier_appel_unitree(service, api_id, parametre)
        if not self.actif or self._noeud is None:
            raise RuntimeError(self.erreur or "le pont ROS 2 n'est pas démarré")
        try:
            from unitree_api.msg import Request, Response
        except ImportError as e:
            raise RuntimeError(f"messages unitree_api introuvables ({e}) : lancez l'Atelier avec g1-atelier") from None
        from rclpy.qos import QoSProfile, ReliabilityPolicy
        debut = time.monotonic()
        with self._verrou_unitree:
            publieur = self._unitree.get(service)
            if publieur is None:
                fiable = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE)
                self._noeud.create_subscription(Response, f"/api/{service}/response", self._recevoir_unitree, fiable)
                publieur = self._noeud.create_publisher(Request, f"/api/{service}/request", fiable)
                self._unitree[service] = publieur
            self._numero_unitree += 1
            ident = time.monotonic_ns() + self._numero_unitree
        while publieur.get_subscription_count() == 0:
            if time.monotonic() - debut > min(delai, DELAI_ABONNE_UNITREE_S):
                raise TimeoutError(f"personne n'écoute /api/{service}/request : le robot (ou le faux G1) est-il "
                                   "relié ?")
            time.sleep(0.05)
        requete = Request()
        requete.header.identity.id = ident
        requete.header.identity.api_id = int(api_id)
        requete.parameter = str(parametre)
        fin = debut + delai
        with self._condition:
            self._attendus_unitree.add(ident)
        try:
            publieur.publish(requete)
            with self._condition:
                while ident not in self._reponses_unitree:
                    reste = fin - time.monotonic()
                    if reste <= 0:
                        raise TimeoutError(f"pas de réponse du robot à {service} {api_id} en {delai:g} s")
                    self._condition.wait(min(reste, 0.1))
                return self._reponses_unitree.pop(ident)
        finally:
            with self._condition:
                self._attendus_unitree.discard(ident)
                self._reponses_unitree.pop(ident, None)

    def _recevoir_unitree(self, msg):
        """Réponse d'un service du robot : gardée seulement si c'est celle d'une de nos requêtes (celles du pont et
        du pilotage passent sur le même sujet)."""
        with self._condition:
            ident = msg.header.identity.id
            if ident in self._attendus_unitree:
                self._reponses_unitree[ident] = (msg.header.status.code, msg.data)
                self._condition.notify_all()

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
