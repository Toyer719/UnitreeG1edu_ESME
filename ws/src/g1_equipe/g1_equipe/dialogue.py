"""
Nœud dialogue (exécutable dialogue) : EXEMPLE de chatbot à règles, que l'équipe remplacera.

    ros2 run g1_equipe dialogue --ros-args -p lieu:=demo [-p etage:=rdc]

Section 11.6 du plan, et docs/integration-equipe.md pour les coéquipiers.

Il écoute :
  /visiteur/texte       std_msgs/String, texte brut : ce que le visiteur a dit (reconnaissance
                        vocale de l'équipe, ou l'onglet Dialogues de l'Atelier) ;
  /guide/evenement      std_msgs/String JSON (evenement_guide) : relayé vers /robot/dire, avec
                        les phrases de la personnalité active ;
  /guide/etat           std_msgs/String JSON (etat_guide) : une visite est-elle en cours ?
  /visiteurs/detectes   std_msgs/String JSON (personnes, source camera) : saluer un visiteur ;
  /personnalite/active  std_msgs/String JSON (personnalite_active), fiable, transient_local ;
  /mouvement/maitre     std_msgs/String JSON (maitre_mouvement), fiable, transient_local :
                        verrou du pilotage.
Il publie :
  /robot/dire           std_msgs/String JSON (robot_dire) : la seule entrée de la partie voix ;
  /guide/aller          std_msgs/String JSON (demande_guide) : {"cible", "accompagner", "source"} ;
  /guide/stop           std_msgs/Empty : la règle stop ;
  /personnalite/active  la personnalité choisie par une règle, ou celle du fichier au démarrage
                        si personne ne l'a encore annoncée ;
  /robot/geste          std_msgs/String JSON (robot_geste) : le geste d'une règle « geste », et le
                        geste_salut de la personnalité active quand il salue un visiteur.

Sécurité : ce nœud ne fait jamais bouger le robot lui-même. Il demande au guide (/guide/aller),
qui décide et conduit ; il ne le demande pas quand le robot est piloté à la main
(/mouvement/maitre : pilotage), ni pendant une visite (sauf remplacer_visite) ; l'arrêt
(/guide/stop) est toujours envoyé. Les gestes passent par le nœud pilotage (/robot/geste), qui ne
les fait que robot au repos ; la LED de la personnalité est mise par le nœud pilotage, qui écoute
/personnalite/active (voir docs/integration-equipe.md).

Paramètres : lieu (obligatoire : id ou chemin), etage (vide : toutes les salles), repondre
(true ; false : le chatbot de l'équipe répond à sa place, ce nœud ne garde que le relais et la
salutation), relayer_evenements (true), saluer (true), distance_salut_m (1.5),
delai_salut_s (30.0), remplacer_visite (false), taire_depart_s (10.0), relire_s (2.0 : relit les
fichiers du lieu s'ils changent ; 0 : jamais). Sans dialogues.yaml dans le lieu, il prend les
règles d'exemple (atelier/lieu/exemples/dialogues.yaml).
"""
import json
import sys
import time

# Le PC a ~/robot-g1 sur le chemin de Python (pip install -e) ; le conteneur, /opt/g1/python
from atelier import chemin_lieu
from atelier.equipe.dialogue import Chatbot, decider
from atelier.equipe.relais import Relais, Salueur
from atelier.lieu import charger_salles, ErreurLieu, valider_message
from atelier.lieu import equipe as E
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Empty, String

VERROU = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                    durability=DurabilityPolicy.TRANSIENT_LOCAL, history=HistoryPolicy.KEEP_LAST)
ETAT_GUIDE_PERIME_S = 5.0
ATTENTE_ANNONCE_S = 2.0
FICHIERS_SUIVIS = ('dialogues.yaml', 'personnalites.yaml', 'salles.yaml')


def lire_json(texte):
    """Lit un message JSON : un dict, ou None s'il est illisible."""
    try:
        d = json.loads(texte)
    except ValueError:
        return None
    return d if isinstance(d, dict) else None


def publier(publieur, message):
    """Publie un dict en JSON sur un sujet std_msgs/String."""
    publieur.publish(String(data=json.dumps(message, ensure_ascii=False)))


class Fichiers:
    """Les fichiers du lieu dont le nœud a besoin, relus quand ils changent."""

    def __init__(self, lieu):
        self.dossier = chemin_lieu(lieu)
        self.dates = None
        self.dialogues = self.personnalites = None
        self.salles = []
        self.exemple = False

    def dates_actuelles(self):
        """Dates de modification des fichiers suivis (None : absent)."""
        dates = []
        for nom in FICHIERS_SUIVIS:
            chemin = self.dossier / nom
            dates.append(chemin.stat().st_mtime_ns if chemin.exists() else None)
        return tuple(dates)

    def relire(self):
        """
        Relit les fichiers si l'un d'eux a changé.

        Renvoie None (rien de nouveau) ou la liste des messages à journaliser. ErreurLieu si un
        fichier est faux : les valeurs d'avant restent.
        """
        dates = self.dates_actuelles()
        if dates == self.dates:
            return None
        dialogues = E.charger_equipe(self.dossier, 'dialogues')
        personnalites = E.charger_equipe(self.dossier, 'personnalites')
        salles = charger_salles(self.dossier)
        messages = []
        self.exemple = dialogues is None
        if self.exemple:
            dialogues = E.exemple_equipe('dialogues')
            messages.append(f'{self.dossier.name} n\'a pas de dialogues.yaml : règles d\'exemple '
                            '(atelier/lieu/exemples/dialogues.yaml)')
        self.dialogues, self.personnalites, self.salles = dialogues, personnalites, salles
        self.dates = dates
        persos = (f'{len(personnalites["personnalites"])} personnalités' if personnalites
                  else 'pas de personnalites.yaml')
        messages.append(f'{len(dialogues["regles"])} règles, {len(salles)} salles, {persos}')
        return messages


class NoeudDialogue(Node):
    """Le nœud ROS 2 : branche le chatbot et le relais d'atelier.equipe sur les sujets."""

    def __init__(self):
        super().__init__('dialogue')
        p = self.declare_parameter
        self.lieu = p('lieu', '').value
        self.etage = p('etage', '').value or None
        self.repondre = p('repondre', True).value
        self.relayer = p('relayer_evenements', True).value
        self.saluer = p('saluer', True).value
        self.remplacer_visite = p('remplacer_visite', False).value
        relire_s = float(p('relire_s', 2.0).value)
        if not self.lieu:
            raise ValueError('donnez le lieu : ros2 run g1_equipe dialogue --ros-args '
                             '-p lieu:=demo')
        self.fichiers = Fichiers(self.lieu)
        self.chatbot = None
        self.relais = Relais(taire_depart_s=float(p('taire_depart_s', 10.0).value))
        self.salueur = Salueur(distance_m=float(p('distance_salut_m', 1.5).value),
                               delai_s=float(p('delai_salut_s', 30.0).value))
        self.personnalite = None     # personnalité active (dernier /personnalite/active)
        self.annoncee = False        # quelqu'un a annoncé une personnalité (nous ou un autre)
        self.etat_guide = None       # (dict, instant)
        self.maitre = None
        self.charger(premiere=True)

        self.pub_dire = self.create_publisher(String, '/robot/dire', 10)
        self.pub_aller = self.create_publisher(String, '/guide/aller', 10)
        self.pub_stop = self.create_publisher(Empty, '/guide/stop', 10)
        self.pub_perso = self.create_publisher(String, '/personnalite/active', VERROU)
        self.pub_geste = self.create_publisher(String, '/robot/geste', 10)
        self.create_subscription(String, '/visiteur/texte', self.sur_texte, 10)
        self.create_subscription(String, '/guide/evenement', self.sur_evenement, 20)
        self.create_subscription(String, '/guide/etat', self.sur_etat_guide, 10)
        self.create_subscription(String, '/visiteurs/detectes', self.sur_visiteurs, 10)
        self.create_subscription(String, '/personnalite/active', self.sur_personnalite, VERROU)
        self.create_subscription(String, '/mouvement/maitre', self.sur_maitre, VERROU)
        if relire_s > 0:
            self.create_timer(relire_s, self.charger)
        self._debut = time.monotonic()
        self._minuterie_annonce = self.create_timer(0.5, self.annoncer_au_demarrage)
        regles = 'règles d\'exemple' if self.fichiers.exemple else 'dialogues.yaml du lieu'
        self.get_logger().info(f'dialogue prêt : lieu {self.fichiers.dossier}, {regles} ; '
                               'j\'écoute /visiteur/texte (EXEMPLE de chatbot, que l\'équipe '
                               'remplacera)')

    # ------------------------------------------------------------ fichiers

    def charger(self, premiere=False):
        """Relit les fichiers du lieu s'ils ont changé (au démarrage : erreur s'ils sont faux)."""
        try:
            messages = self.fichiers.relire()
        except ErreurLieu as e:
            if premiere:
                raise
            self.get_logger().error('fichiers du lieu faux, je garde les précédents : '
                                    + ' ; '.join(e.erreurs[:3]))
            self.fichiers.dates = self.fichiers.dates_actuelles()   # ne pas le redire sans cesse
            return
        if messages is None:
            return
        for m in messages:
            self.get_logger().info(m)
        self.chatbot = Chatbot(self.fichiers.dialogues, self.fichiers.salles, etage=self.etage)
        if self.personnalite is None:
            self.personnalite = E.personnalite_active(self.fichiers.personnalites)
        elif self.fichiers.personnalites:
            # la personnalité active a pu changer dans le fichier (phrases, voix…) : on la relit
            relue = E.personnalite_active(self.fichiers.personnalites, self.personnalite.get('id'))
            if relue is not None:
                self.personnalite = dict(self.personnalite, **relue)

    def annoncer_au_demarrage(self):
        """Annonce la personnalité du fichier si personne ne l'a fait 2 s après le démarrage."""
        if time.monotonic() - self._debut < ATTENTE_ANNONCE_S:
            return
        self._minuterie_annonce.cancel()
        if not self.annoncee and self.personnalite is not None:
            self.annoncer(self.personnalite)

    def annoncer(self, perso):
        """Publie la personnalité active sur /personnalite/active."""
        self.annoncee = True
        self.personnalite = perso
        message = E.message_personnalite_active(perso, lieu=self.fichiers.dossier.name)
        publier(self.pub_perso, message)
        self.get_logger().info(f'personnalité active : {perso["id"]} ({perso["nom"]})')

    # ------------------------------------------------------------ réceptions

    def sur_personnalite(self, msg):
        """Retient la personnalité annoncée (par l'onglet, par nous, ou par l'équipe)."""
        d = lire_json(msg.data)
        if d is None or valider_message('personnalite_active', d):
            self.get_logger().warn('/personnalite/active : message hors du schéma, ignoré')
            return
        self.annoncee = True
        # un message réduit à {id, nom} (permis par le schéma) : le reste vient du fichier
        base = E.personnalite_active(self.fichiers.personnalites, d['id']) or {}
        self.personnalite = dict(base, **d)

    def sur_maitre(self, msg):
        """Retient le maître des mouvements (verrou du pilotage)."""
        self.maitre = lire_json(msg.data)

    def sur_etat_guide(self, msg):
        """Retient le dernier état du guide."""
        d = lire_json(msg.data)
        if d is not None:
            self.etat_guide = (d, time.monotonic())

    def etat_guide_frais(self):
        """Donne le dernier /guide/etat, ou None s'il est trop vieux (guide arrêté)."""
        if self.etat_guide is None or time.monotonic() - self.etat_guide[1] > ETAT_GUIDE_PERIME_S:
            return None
        return self.etat_guide[0]

    def sur_texte(self, msg):
        """Répond à une phrase du visiteur, et demande au guide d'y aller s'il le faut."""
        texte = msg.data.strip()
        if not self.repondre or not texte or self.chatbot is None:
            return
        r = self.chatbot.repondre(texte)
        if r is None:
            return
        phrases = (self.personnalite or {}).get('phrases')
        d = decider(self.chatbot, r, self.etat_guide_frais(), self.maitre, self.remplacer_visite,
                    self.fichiers.personnalites, phrases)
        quoi = r['action'] + (f' {r["salle"]}' if r['salle'] else '')
        refus = f', pas envoyé : {d["raison"]}' if d['raison'] else ''
        self.get_logger().info(f'« {texte} » → {r["regle"] or "repli"} ({quoi}){refus}')
        if d['stop']:
            self.pub_stop.publish(Empty())
        if d['dire']:
            self.dire(d['dire'], 'dialogue', priorite='haute' if d['stop'] else 'normale')
        if d['guide'] is not None:
            self.relais.noter_guidage(d['guide']['cible'])
            publier(self.pub_aller, d['guide'])
        if d['personnalite'] is not None:
            self.annoncer(d['personnalite'])
        if d['geste'] is not None:
            publier(self.pub_geste, E.message_robot_geste(d['geste'], 'dialogue',
                                                          raison=f'règle « {r["regle"]} »'))

    def sur_evenement(self, msg):
        """Relaie un événement du guide vers /robot/dire."""
        if not self.relayer:
            return
        evenement = lire_json(msg.data)
        if evenement is None:
            return
        message = self.relais.message(evenement, self.personnalite)
        if message is not None:
            publier(self.pub_dire, message)

    def sur_visiteurs(self, msg):
        """Salue un visiteur vu par la caméra, si le guide est au repos."""
        if not self.saluer:
            return
        message = self.salueur.recevoir(lire_json(msg.data), self.etat_guide_frais(),
                                        self.personnalite)
        if message is not None:
            publier(self.pub_dire, message)
            self.get_logger().info(f'salutation : « {message["texte"]} »')
            geste = (self.personnalite or {}).get('geste_salut')
            if isinstance(geste, int) and not isinstance(geste, bool):
                publier(self.pub_geste, E.message_robot_geste(geste, 'personnalite',
                                                              raison='salutation'))

    def dire(self, texte, source, priorite='normale'):
        """Publie une phrase sur /robot/dire."""
        publier(self.pub_dire, E.message_robot_dire(texte, source, priorite=priorite,
                                                    personnalite=self.personnalite))


def main(args=None):
    """Lance le nœud (ros2 run g1_equipe dialogue)."""
    rclpy.init(args=args)
    noeud = None
    try:
        noeud = NoeudDialogue()
        rclpy.spin(noeud)
    except (ValueError, ErreurLieu) as e:
        print(f'dialogue : {e}', file=sys.stderr)
        return 2
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        if noeud is not None:
            noeud.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0


if __name__ == '__main__':
    sys.exit(main())
