"""
Nœud accueil : la démo d'accueil (vague 6, section 13.4 du plan), lancé par g1-accueil.

    ros2 run g1_accueil accueil --ros-args -p lieu:=demo [-p etage:=rdc]

Il branche la machine d'états (logique.Orchestrateur, sans ROS) sur les sujets :
  écoute   /guide/etat, /guide/evenement, /pont/etat, /pont/arret (fiable, transient_local),
           /mouvement/maitre (transient_local), /visiteurs/detectes, /personnes/lidar,
           /personnalite/active (transient_local), /accueil/choix, /accueil/commande, et la
           position du robot sur la carte (TF map → base_link) ;
  publie   /guide/aller, /guide/stop, /robot/dire, /robot/geste, /accueil/etat (2 fois par
           seconde et à chaque changement), /accueil/evenement.
Paramètres : lieu (obligatoire : id ou dossier), etage (défaut : celui du point principal), et
ceux de atelier.lieu.accueil.REGLAGES_DEMO, dont les défauts viennent de demo.yaml du lieu
(visiteurs, délais, accompagner, retour) ; repere_carte (map), repere_robot (base_link),
frequence (10 Hz), relire_s (2 s : salles.yaml et personnalites.yaml relus s'ils changent).

Sécurité : ce nœud ne fait jamais bouger le robot lui-même ; il demande au guide (/guide/aller),
qui décide et conduit, et jamais pendant une pause (sauf « Ramener à l'accueil », une demande
explicite). Ctrl+C ou SIGTERM : l'événement arretee, puis il s'arrête ; une visite en cours est
finie par le guide, comme une visite de la vague 4 (le nœud n'envoie pas /guide/stop).
"""
import json
import math
import re
import signal
import sys
import time

from atelier import chemin_lieu
from atelier.lieu import accueil as A
from atelier.lieu import charger_salles, ErreurLieu, valider_message
from atelier.lieu import equipe as E
from g1_accueil.logique import Orchestrateur, SUJETS_ENTREE

FICHIERS_SUIVIS = ('salles.yaml', 'personnalites.yaml')
POSE_FIGEE_S = 2.0          # la transformée n'a pas changé depuis ce temps : position trop vieille
# demo.yaml → paramètres du nœud (REGLAGES_DEMO)
DEPUIS_DEMO_YAML = {
    'source_visiteurs': ('visiteurs', 'source'),
    'distance_visiteur_m': ('visiteurs', 'distance_m'),
    'presence_s': ('visiteurs', 'presence_s'), 'delai_choix_s': ('delais', 'choix_s'),
    'delai_depart_s': ('delais', 'depart_s'),
    'delai_entre_visiteurs_s': ('delais', 'entre_visiteurs_s'),
    'accompagner': ('accompagner',), 'retour': ('retour',),
}


def lire_json(texte):
    """Lit un message JSON : un dict, ou None s'il est illisible."""
    try:
        d = json.loads(texte)
    except ValueError:
        return None
    return d if isinstance(d, dict) else None


def reglages_du_lieu(dossier):
    """REGLAGES_DEMO complétés par demo.yaml (atelier.lieu.accueil.reglages_demo)."""
    demo = A.reglages_demo(dossier)
    reglages = dict(A.REGLAGES_DEMO)
    for nom, chemin in DEPUIS_DEMO_YAML.items():
        valeur = demo
        for cle in chemin:
            valeur = valeur.get(cle) if isinstance(valeur, dict) else None
        if valeur is not None:
            reglages[nom] = valeur
    return reglages, demo


def convertir(nom, valeur):
    """Valeur d'un paramètre ROS au type de son défaut (REGLAGES_DEMO) ; ValueError sinon."""
    defaut = A.REGLAGES_DEMO[nom]
    if isinstance(defaut, bool):
        if isinstance(valeur, str):
            if valeur.lower() not in ('true', 'false', '1', '0'):
                raise ValueError(f'{nom} : true ou false attendu, pas « {valeur} »')
            return valeur.lower() in ('true', '1')
        return bool(valeur)
    if isinstance(defaut, float):
        v = float(valeur)
        if not math.isfinite(v) or v < 0:
            raise ValueError(f'{nom} : nombre positif attendu, pas « {valeur} »')
        return v
    if nom == 'source_visiteurs' and valeur not in A.SOURCES_VISITEURS:
        raise ValueError(f'{nom} : {", ".join(A.SOURCES_VISITEURS)}, pas « {valeur} »')
    return str(valeur)


def personnalites_du_lieu(dossier):
    """Les personnalités de personnalites.yaml (liste), et l'active du fichier, ou ([], None)."""
    try:
        d = E.charger_equipe(dossier, 'personnalites')
    except ErreurLieu:
        return [], None
    if not d:
        return [], None
    return list(d.get('personnalites') or []), E.personnalite_active(d)


def main(args=None):
    """Point d'entrée de ros2 run g1_accueil accueil."""
    import rclpy
    from rclpy.executors import ExternalShutdownException, SingleThreadedExecutor
    from rclpy.signals import SignalHandlerOptions

    rclpy.init(args=args, signal_handler_options=SignalHandlerOptions.NO)
    fin = []
    signal.signal(signal.SIGINT, lambda *_: fin.append('SIGINT'))
    signal.signal(signal.SIGTERM, lambda *_: fin.append('SIGTERM'))
    try:
        noeud = NoeudAccueil()
    except (ValueError, ErreurLieu) as e:
        message = '; '.join(e.erreurs[:3]) if isinstance(e, ErreurLieu) else str(e)
        print(f'accueil : {message}', file=sys.stderr)
        rclpy.try_shutdown()
        return 1
    executeur = SingleThreadedExecutor()
    executeur.add_node(noeud)
    try:
        while rclpy.ok() and not fin:
            executeur.spin_once(timeout_sec=0.1)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        noeud.au_revoir(fin[0] if fin else 'fin')
        executeur.shutdown()
        noeud.destroy_node()
        rclpy.try_shutdown()
    return 0


try:
    from rclpy.node import Node
except ImportError:      # logique seule, sans ROS (tests)
    Node = object


class NoeudAccueil(Node):
    """Le nœud ROS 2 : la machine d'états de la démo branchée sur les sujets."""

    def __init__(self):
        super().__init__('accueil')
        from rcl_interfaces.msg import ParameterDescriptor
        from rclpy.clock import Clock, ClockType
        from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
        from std_msgs.msg import Bool, Empty, String
        import tf2_ros

        self.String, self.Empty = String, Empty
        lieu = self.declare_parameter('lieu', '').value
        etage = self.declare_parameter('etage', '').value
        if not lieu:
            raise ValueError('donnez le lieu : ros2 run g1_accueil accueil --ros-args '
                             '-p lieu:=demo')
        self.dossier = chemin_lieu(lieu)
        if not (self.dossier / 'lieu.yaml').is_file():
            raise ValueError(f'lieu introuvable : {self.dossier}')
        from atelier.lieu.principal import point_principal
        principal = point_principal(self.dossier)
        if principal is None:
            raise ValueError(f'le lieu {self.dossier.name} n\'a pas de point principal (Placer › '
                             'Accueil)')
        self.etage = etage or principal.etage
        libre = ParameterDescriptor(dynamic_typing=True)
        defauts, demo = reglages_du_lieu(self.dossier)
        reglages = {}
        for nom, defaut in defauts.items():
            reglages[nom] = convertir(nom, self.declare_parameter(nom, defaut, libre).value)
        self.repere_carte = self.declare_parameter('repere_carte', 'map').value
        self.repere_robot = self.declare_parameter('repere_robot', 'base_link').value
        frequence = float(self.declare_parameter('frequence', 10.0).value)
        relire_s = float(self.declare_parameter('relire_s', 2.0).value)

        self.personnalites, active = personnalites_du_lieu(self.dossier)
        voulue = demo.get('personnalite')
        personnalite = active
        if voulue:
            personnalite = next((p for p in self.personnalites if p.get('id') == voulue), None)
            if personnalite is None:
                self.get_logger().warn(f'demo.yaml : personnalité « {voulue} » absente de '
                                       'personnalites.yaml, je garde celle par défaut')
                personnalite = active
        self.salles = charger_salles(self.dossier)
        self.dates = self._dates()
        nom_lieu = self.dossier.name if id_valide(self.dossier.name) else 'lieu'
        self.logique = Orchestrateur(
            self.salles, principal.id, self.etage, reglages, horloge=time.monotonic,
            lieu=nom_lieu, pose_principale=(principal.pose.x, principal.pose.y,
                                            principal.pose.theta),
            personnalite=personnalite, personnalites=self.personnalites,
            suivre_personnalite=not voulue)

        verrou = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                            durability=DurabilityPolicy.TRANSIENT_LOCAL,
                            history=HistoryPolicy.KEEP_LAST)
        ecoute = QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT,
                            history=HistoryPolicy.KEEP_LAST)
        fiable = QoSProfile(depth=20, reliability=ReliabilityPolicy.RELIABLE,
                            history=HistoryPolicy.KEEP_LAST)
        self.pubs = {
            '/guide/aller': self.create_publisher(String, '/guide/aller', 10),
            '/guide/stop': self.create_publisher(Empty, '/guide/stop', 10),
            '/robot/dire': self.create_publisher(String, '/robot/dire', 10),
            '/robot/geste': self.create_publisher(String, '/robot/geste', 10),
            '/accueil/etat': self.create_publisher(String, '/accueil/etat', 10),
            '/accueil/evenement': self.create_publisher(String, '/accueil/evenement', fiable),
        }
        json_qos = {'/guide/etat': ecoute, '/guide/evenement': fiable, '/pont/etat': ecoute,
                    '/mouvement/maitre': verrou, '/visiteurs/detectes': ecoute,
                    '/personnes/lidar': ecoute, '/personnalite/active': verrou,
                    '/accueil/choix': fiable, '/accueil/commande': fiable}
        for sujet, qos in json_qos.items():
            assert sujet in SUJETS_ENTREE
            self.create_subscription(String, sujet, self._recepteur(sujet), qos)
        self.create_subscription(Bool, '/pont/arret', self._sur_verrou, verrou)
        self.tampon_tf = tf2_ros.Buffer()
        self.ecoute_tf = tf2_ros.TransformListener(self.tampon_tf, self)
        self._tf = None                  # (instant de la transformée, instant mural du changement)
        self._dernier_etat = 0.0
        # Horloge murale : la démo répond même si la simulation est en pause
        stable = Clock(clock_type=ClockType.STEADY_TIME)
        self.create_timer(1.0 / max(1.0, frequence), self._sur_minuterie, clock=stable)
        if relire_s > 0:
            self.create_timer(relire_s, self._relire, clock=stable)
        options = ', '.join(f'{k} {v}' for k, v in reglages.items())
        self.get_logger().info(
            f'démo d\'accueil prête : lieu {self.dossier}, étage {self.etage}, point principal '
            f'{principal.id}, personnalité {(personnalite or {}).get("id") or "aucune"}'
            + (' (imposée par demo.yaml)' if voulue else '') + f'. Réglages : {options}.')

    # ------------------------------------------------------------ réceptions

    def _recepteur(self, sujet):
        def recevoir(msg):
            d = lire_json(msg.data)
            if d is None:
                self.get_logger().warn(f'{sujet} : message illisible, ignoré')
                return
            if sujet in ('/accueil/choix', '/accueil/commande'):
                schema = 'choix_accueil' if sujet == '/accueil/choix' else 'commande_accueil'
                erreurs = valider_message(schema, d)
                if erreurs:
                    self._refuser_message(sujet, d, erreurs)
                    return
            self._publier_tout(self.logique.entrer(sujet, d))
        return recevoir

    def _refuser_message(self, sujet, d, erreurs):
        """Un choix ou une commande hors du schéma : refusé, avec sa réponse s'il a un id."""
        self.get_logger().warn(f'{sujet} : message refusé ({"; ".join(erreurs[:2])})')
        ident = d.get('id') if isinstance(d.get('id'), str) and len(d['id']) <= 80 else None
        code = 'choix_refuse' if sujet == '/accueil/choix' else 'commande_refusee'
        message = {'version': 1, 'code': code, 'texte': ('Message non conforme : '
                                                         + erreurs[0])[:300],
                   'temps': A.maintenant_iso(), 'raison': 'action_impossible'}
        if ident and not valider_message('evenement_demo', dict(message, id=ident)):
            message['id'] = ident
        self._publier('/accueil/evenement', message)

    def _sur_verrou(self, msg):
        self._publier_tout(self.logique.entrer('/pont/arret', bool(msg.data)))

    def _position(self):
        """(x, y, theta) du robot dans la carte par TF, ou None (absente ou figée)."""
        from rclpy.time import Time
        try:
            t = self.tampon_tf.lookup_transform(self.repere_carte, self.repere_robot, Time())
        except Exception:      # noqa: BLE001 : pas encore de transformée (repérage, démarrage)
            return None
        instant = (t.header.stamp.sec, t.header.stamp.nanosec)
        maintenant = time.monotonic()
        if self._tf is None or self._tf[0] != instant:
            self._tf = (instant, maintenant)
        elif maintenant - self._tf[1] > POSE_FIGEE_S:
            return None
        q = t.transform.rotation
        theta = math.atan2(2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y * q.y + q.z * q.z))
        return (t.transform.translation.x, t.transform.translation.y, theta)

    def _sur_minuterie(self):
        pose = self._position()
        sorties = self.logique.entrer('position', pose) if pose is not None else []
        sorties += self.logique.pas()
        self._publier_tout(sorties)
        # 2 fois par seconde (la minuterie tourne à 10 Hz : on vise juste avant la demi-seconde)
        if time.monotonic() - self._dernier_etat >= A.PERIODE_ETAT_S - 0.05:
            self._publier('/accueil/etat', self.logique.etat())

    # ------------------------------------------------------------ fichiers

    def _dates(self):
        dates = []
        for nom in FICHIERS_SUIVIS:
            chemin = self.dossier / nom
            dates.append(chemin.stat().st_mtime_ns if chemin.exists() else None)
        return tuple(dates)

    def _relire(self):
        """salles.yaml (salles cachées de la borne) et personnalites.yaml, s'ils ont changé."""
        dates = self._dates()
        if dates == self.dates:
            return
        self.dates = dates
        try:
            salles = charger_salles(self.dossier)
            personnalites, _ = personnalites_du_lieu(self.dossier)
        except ErreurLieu as e:
            self.get_logger().error('fichiers du lieu faux, je garde les précédents : '
                                    + ' ; '.join(e.erreurs[:3]))
            return
        self.logique.changer_salles(salles)
        self.logique.personnalites = {p.get('id'): p for p in personnalites}
        self.get_logger().info(f'fichiers du lieu relus : {len(salles)} salles')

    # ------------------------------------------------------------ publications

    def _publier_tout(self, sorties):
        for sujet, donnees in sorties:
            self._publier(sujet, donnees)

    def _publier(self, sujet, donnees):
        pub = self.pubs.get(sujet)
        if pub is None:
            return
        if sujet == '/guide/stop':
            pub.publish(self.Empty())
            self.get_logger().info('pause pendant une visite de la démo : /guide/stop')
            return
        if sujet == '/accueil/etat':
            self._dernier_etat = time.monotonic()
        elif sujet == '/guide/aller':
            self.get_logger().info(f'demande au guide : {json.dumps(donnees, ensure_ascii=False)}')
        elif sujet == '/accueil/evenement':
            self.get_logger().info(f'{donnees["code"]} : {donnees["texte"]}')
        pub.publish(self.String(data=json.dumps(donnees, ensure_ascii=False)))

    def au_revoir(self, raison):
        """L'événement arretee, à l'arrêt du nœud (Ctrl+C, SIGTERM)."""
        try:
            self._publier('/accueil/evenement', {
                'version': 1, 'code': 'arretee', 'texte': 'La démo d\'accueil est arrêtée.',
                'temps': A.maintenant_iso()})
            time.sleep(0.2)          # le temps que le message parte
        except Exception:       # noqa: BLE001 : contexte ROS déjà fermé
            pass
        self.get_logger().info(f'démo arrêtée ({raison})')


def id_valide(texte):
    """Vrai si texte est un identifiant de lieu valable (champ lieu de /accueil/etat)."""
    return bool(re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,39}', texte or ''))


if __name__ == '__main__':
    sys.exit(main())
