"""Le nœud ROS 2 « voix » (vague 6, section 13.6 du plan) : commande g1-voix, sur le PC.

  g1-voix --lieu L [--sortie robot|borne|robot_tts] [--volume N] [--voix fr_FR-siwis-medium] [--vitesse V]
          [--locuteur N] [-- --ros-args …]
  g1-voix --mesurer [« phrase » …]      temps de synthèse de Piper sur ce PC, sans ROS ni robot

Entrées : /robot/dire (schéma robot_dire), /voix/commande (schéma commande_voix), /personnalite/active (fiable,
transient_local), /api/voice/response (unitree_api/Response, au mieux : seules les réponses à NOS requêtes
comptent). Sorties : /api/voice/request (unitree_api/Request, fiable : 1001, 1003 avec le PCM dans binary, 1004,
1005, 1006, rien d'autre), /voix/etat (schéma etat_voix, 1 fois par seconde et à chaque changement), /voix/son
(schéma son_voix, sortie borne). Les réglages de départ viennent de demo.yaml du lieu (voix : sortie, volume,
nom, vitesse), puis des options. Chaque phrase dite par Piper est gardée en WAV dans
atelier.lieu.voix.dossier_sons() (les SONS_GARDES dernières) : la borne joue celles de la sortie borne ; pour
la sortie robot, c'est la trace de ce qui a été dit (le critère 40 la compare au son reçu par le faux G1).
Ctrl+C ou SIGTERM : 1004 (STOP_PLAY) si le robot parle, puis arrêt. Jamais de son pendant les tests
automatiques : ils tournent contre le faux G1 (g1_jumeau), dans leur domaine ROS.
"""
import argparse
import json
import signal
import statistics
import sys
import threading
import time
from pathlib import Path

from atelier.lieu import voix as V

from .logique import Annonce, LOCUTEUR_TTS_DEFAUT, LogiqueVoix, Requete
from .synthese import ErreurSynthese, SynthesePiper, SyntheseFactice, ecrire_wav, voix_disponibles

PERIODE_PAS_S = 0.05            # 20 fois par seconde : morceaux, fin des phrases, état
SONS_GARDES = 200               # WAV gardés dans dossier_sons() (les plus récents)
ATTENTE_SORTIE_S = 0.5          # à l'arrêt : temps laissé au 1004 pour partir
PHRASES_MESURE = ("Bonjour, suivez-moi !", "Je vous accompagne à la Salle B204.",
                  "Bonjour ! Je suis le robot d'accueil du lycée. Où voulez-vous aller ?",
                  "Je fais une petite pause.")


def analyseur():
    a = argparse.ArgumentParser(
        prog="g1-voix", description="La voix du robot : dit les phrases de /robot/dire par le haut-parleur du "
                                    "robot (voix du PC), la borne ou la synthèse du robot (section 13.6 du plan).")
    a.add_argument("--lieu", help="lieu (id ou dossier) : réglages de départ dans son demo.yaml (voix)")
    a.add_argument("--sortie", choices=V.SORTIES_VOIX, help="robot (défaut), borne ou robot_tts")
    a.add_argument("--volume", type=int, help="volume du haut-parleur du robot, de 0 à 100")
    a.add_argument("--voix", help=f"voix Piper ({', '.join(V.VOIX_PIPER)})")
    a.add_argument("--vitesse", type=float, help="vitesse de la voix : 1,0 normal, de 0,5 à 2")
    a.add_argument("--locuteur", type=int, default=LOCUTEUR_TTS_DEFAUT,
                   help="speaker_id de la synthèse du robot (robot_tts) : 0 chinois, 1 anglais (le français : "
                        "à vérifier sur le robot)")
    a.add_argument("--factice", action="store_true", help="voix d'essai sans Piper (un bip), pour les essais")
    a.add_argument("--mesurer", nargs="*", metavar="PHRASE",
                   help="mesure le temps de synthèse de Piper sur ce PC (sans ROS) et s'arrête")
    return a


def reglages_depart(options):
    """{sortie, volume, voix, vitesse, avertissement} : demo.yaml du lieu (s'il est donné), puis les options."""
    reglages = {"sortie": "robot", "volume": None, "voix": V.VOIX_DEFAUT, "vitesse": 1.0, "avertissement": None}
    if options.lieu:
        try:
            import atelier
            from atelier.lieu.accueil import reglages_demo
            voix = reglages_demo(atelier.chemin_lieu(options.lieu)).get("voix") or {}
            reglages.update({"sortie": voix.get("sortie", "robot"), "volume": voix.get("volume"),
                             "voix": voix.get("nom", V.VOIX_DEFAUT), "vitesse": voix.get("vitesse", 1.0)})
        except Exception as e:      # noqa: BLE001 : demo.yaml faux ou lieu absent : les réglages par défaut
            reglages["avertissement"] = f"réglages de la démo illisibles ({e}) : réglages par défaut"
    for cle, option in (("sortie", options.sortie), ("volume", options.volume), ("voix", options.voix),
                        ("vitesse", options.vitesse)):
        if option is not None:
            reglages[cle] = option
    if reglages["volume"] is not None and not 0 <= int(reglages["volume"]) <= 100:
        raise ValueError("--volume : de 0 à 100")
    return reglages


def ranger_sons(dossier, garder=SONS_GARDES):
    """Ne garde que les « garder » WAV les plus récents du dossier des sons ; rend le nombre effacé."""
    try:
        sons = sorted(Path(dossier).glob("*.wav"), key=lambda f: f.stat().st_mtime, reverse=True)
    except OSError:
        return 0
    effaces = 0
    for vieux in sons[garder:]:
        try:
            vieux.unlink()
            effaces += 1
        except OSError:
            pass
    return effaces


class Coeur:
    """La logique sous un verrou, et le fil de synthèse qui calcule le son des phrases (Piper)."""

    def __init__(self, logique, synthese, journal=print):
        self.logique = logique
        self.synthese = synthese
        self.journal = journal
        self.verrou = threading.RLock()
        self.reveil = threading.Event()
        self.fin = threading.Event()
        self.fil = threading.Thread(target=self._synthetiser, name="synthese voix", daemon=True)

    def demarrer(self):
        self.fil.start()
        return self

    def arreter(self):
        self.fin.set()
        self.reveil.set()
        self.fil.join(timeout=2.0)

    def appeler(self, methode, *args, **kwargs):
        """Une méthode de la logique, sous le verrou ; le fil de synthèse est réveillé ensuite."""
        with self.verrou:
            sorties = getattr(self.logique, methode)(*args, **kwargs)
        self.reveil.set()
        return sorties

    def _prechauffer(self):
        """Charge la voix du nœud et calcule une première phrase dès le démarrage : sinon la première vraie phrase
        attend le chargement de Piper (0,7 s mesurées)."""
        try:
            self.synthese.synthetiser("Bonjour.", self.logique.voix)
        except Exception as e:      # noqa: BLE001 : la phrase dira l'erreur si la voix manque vraiment
            self.journal(f"voix pas préchargée : {e}")

    def _synthetiser(self):
        self._prechauffer()
        while not self.fin.is_set():
            with self.verrou:
                travail = self.logique.prochaine_synthese()
            if travail is None:
                self.reveil.wait(0.5)
                self.reveil.clear()
                continue
            ident, texte, voix, vitesse, gain = travail
            try:
                son = self.synthese.synthetiser(texte, voix, vitesse, gain)
                try:
                    ecrire_wav(V.chemin_son(ident), son.echantillons, son.frequence_hz)
                    ranger_sons(V.dossier_sons())
                except (OSError, ValueError) as e:   # disque plein… : le robot peut dire la phrase, pas la borne
                    son.infos["wav"] = False
                    self.journal(f"WAV de la phrase {ident} pas écrit : {e}")
            except (ErreurSynthese, OSError, ValueError) as e:
                with self.verrou:
                    self.logique.synthese_echouee(ident, e)
                self.journal(f"synthèse impossible : {e}")
                continue
            except Exception as e:      # noqa: BLE001 : Piper qui plante ne doit jamais arrêter le nœud
                with self.verrou:
                    self.logique.synthese_echouee(ident, f"erreur de Piper : {e}")
                self.journal(f"erreur de Piper : {e!r}")
                continue
            with self.verrou:
                self.logique.son_pret(ident, (voix, vitesse, gain), son)


def creer_noeud(coeur):
    """Le nœud voix (rclpy déjà initialisé), relié au cœur."""
    from rclpy.node import Node
    from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
    from std_msgs.msg import String
    from unitree_api.msg import Request, Response

    class NoeudVoix(Node):
        """voix : /robot/dire → service voice du robot (1001, 1003, 1004, 1005, 1006), borne, /voix/etat."""

        def __init__(self):
            super().__init__("voix")
            self.coeur = coeur
            self.Request, self.String = Request, String
            fiable = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE,
                                durability=DurabilityPolicy.VOLATILE)
            au_mieux = QoSProfile(depth=50, reliability=ReliabilityPolicy.BEST_EFFORT,
                                  durability=DurabilityPolicy.VOLATILE)
            verrou = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                                durability=DurabilityPolicy.TRANSIENT_LOCAL, history=HistoryPolicy.KEEP_LAST)
            self.pub_requete = self.create_publisher(Request, f"{V.SERVICE_VOIX}/request", fiable)
            self.pub_etat = self.create_publisher(String, "/voix/etat", 10)
            self.pub_son = self.create_publisher(String, "/voix/son", 10)
            self.create_subscription(Response, f"{V.SERVICE_VOIX}/response", self._sur_reponse, au_mieux)
            self.create_subscription(String, "/robot/dire", self._recepteur("dire"), 20)
            self.create_subscription(String, "/voix/commande", self._recepteur("commande"), 10)
            self.create_subscription(String, "/personnalite/active", self._recepteur("changer_personnalite"),
                                     verrou)
            self.t_etat = 0.0
            self.minuterie = self.create_timer(PERIODE_PAS_S, self._pas)

        # ---------------------------------------------------- entrées

        def _recepteur(self, methode):
            def recevoir(msg):
                try:
                    donnees = json.loads(msg.data)
                except ValueError:
                    donnees = None
                self.publier(self.coeur.appeler(methode, donnees))
            return recevoir

        def _sur_reponse(self, msg):
            identite = msg.header.identity
            self.publier(self.coeur.appeler("reponse", int(identite.id), int(msg.header.status.code), msg.data))

        def _pas(self):
            with self.coeur.verrou:
                self.coeur.logique.changer_abonnes(self.pub_requete.get_subscription_count())
                sorties = self.coeur.logique.pas()
            self.publier(sorties)

        # ---------------------------------------------------- sorties

        def publier(self, sorties):
            for s in sorties:
                if isinstance(s, Requete):
                    self._requete(s)
                elif isinstance(s, Annonce):
                    self.pub_son.publish(self.String(data=json.dumps(s.message, ensure_ascii=False)))
            maintenant = time.monotonic()
            with self.coeur.verrou:
                logique = self.coeur.logique
                if not (logique.change or maintenant - self.t_etat >= V.PERIODE_ETAT_S):
                    return
                logique.change = False
                etat = logique.etat()
            self.t_etat = maintenant
            self.pub_etat.publish(self.String(data=json.dumps(etat, ensure_ascii=False)))

        def _requete(self, s):
            erreurs = V.erreurs_requete_voix(s.api_id, s.parametre, s.binaire)
            if s.api_id not in V.APIS_NOEUD_VOIX or erreurs:     # filet : jamais une requête hors contrat
                self.get_logger().error(f"requête voice {s.api_id} retenue : {erreurs or 'api interdite'}")
                return
            from array import array
            msg = self.Request()
            msg.header.identity.id = int(s.identifiant)
            msg.header.identity.api_id = int(s.api_id)
            msg.header.lease.id = 0
            msg.header.policy.priority = 0
            msg.header.policy.noreply = False
            msg.parameter = str(s.parametre)
            msg.binary = array("B", s.binaire)
            self.pub_requete.publish(msg)
            if s.api_id != V.API_VOIX["start_play"] or s.raison.startswith("morceau 1/"):
                self.get_logger().info(f"voice {s.api_id} {s.parametre[:100]} ({s.raison}"
                                       f"{', ' + str(len(s.binaire)) + ' octets' if s.binaire else ''})")

    return NoeudVoix()


def mesurer(phrases, factice=False, sortie=print):
    """Temps de synthèse de Piper sur ce PC : chargement de chaque voix, puis chaque phrase (3 fois)."""
    synthese = SyntheseFactice() if factice else SynthesePiper()
    disponibles = synthese.disponibles() if factice else voix_disponibles()
    if not disponibles:
        sortie(f"Aucune voix Piper dans {V.DOSSIER_PIPER} : rien à mesurer.")
        return 1
    resultats = []
    for nom in disponibles:
        debut = time.perf_counter()
        try:
            synthese.synthetiser("Bonjour.", nom)          # chargement et première phrase (la plus lente)
        except ErreurSynthese as e:
            sortie(f"{nom} : {e}")
            return 1
        premiere = time.perf_counter() - debut
        sortie(f"Voix {nom} ({V.VOIX_PIPER.get(nom, nom)}) : chargée et prête en {premiere:.2f} s")
        for texte in phrases:
            temps, son = [], None
            for _ in range(3):
                son = synthese.synthetiser(texte, nom)
                temps.append(son.duree_synthese_s)
            calcul = statistics.median(temps)
            facteur = son.duree_s / calcul if calcul > 0 else float("inf")
            sortie(f"  « {texte} » : {son.duree_s:.2f} s de son ({son.frequence_hz} Hz, {len(son.pcm16)} octets à "
                   f"16 kHz, {len(V.morceaux_pcm(son.pcm16))} morceau(x)), calculé en {calcul:.3f} s "
                   f"({facteur:.0f} fois plus vite que la parole)")
            resultats.append({"voix": nom, "texte": texte, "duree_son_s": round(son.duree_s, 3),
                              "synthese_s": round(calcul, 4), "premiere_s": round(premiere, 3)})
    pire = max(r["synthese_s"] for r in resultats)
    sortie(f"Pire temps de synthèse d'une phrase : {pire:.3f} s (hors chargement).")
    return 0


def main(argv=None):
    """Point d'entrée de python -m atelier.voix (g1-voix)."""
    argv = list(sys.argv[1:] if argv is None else argv)
    a_analyser = argv
    if "--ros-args" in argv:
        a_analyser = argv[:argv.index("--ros-args")]
    a_analyser = [x for x in a_analyser if x != "--"]
    options = analyseur().parse_args(a_analyser)
    if options.mesurer is not None:
        return mesurer(options.mesurer or list(PHRASES_MESURE), options.factice)
    try:
        reglages = reglages_depart(options)
        synthese = SyntheseFactice() if options.factice else SynthesePiper()
        logique = LogiqueVoix(sortie=reglages["sortie"], voix=reglages["voix"], volume=reglages["volume"],
                              vitesse=reglages["vitesse"], locuteur_tts=options.locuteur,
                              disponibles=synthese.disponibles())
    except (ValueError, TypeError) as e:
        print(f"g1-voix : réglage refusé : {e}", file=sys.stderr)
        return 2
    try:
        import rclpy
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.signals import SignalHandlerOptions
    except ImportError as e:
        print(f"g1-voix : ROS 2 introuvable ({e}) : source ~/robot-g1/setup/env.sh", file=sys.stderr)
        return 1
    ros_args = argv[argv.index("--ros-args"):] if "--ros-args" in argv else []
    rclpy.init(args=["g1-voix", *ros_args], signal_handler_options=SignalHandlerOptions.NO)
    try:
        coeur = Coeur(logique, synthese)
        noeud = creer_noeud(coeur)
    except ImportError as e:
        print(f"g1-voix : messages unitree_api introuvables ({e}) : source ~/robot-g1/setup/env.sh",
              file=sys.stderr)
        rclpy.try_shutdown()
        return 1
    journal = noeud.get_logger()
    coeur.journal = journal.warning
    coeur.demarrer()
    if reglages["avertissement"]:
        journal.warning(reglages["avertissement"])
    executeur = SingleThreadedExecutor()
    executeur.add_node(noeud)
    fil_ros = threading.Thread(target=executeur.spin, name="ros", daemon=True)
    fil_ros.start()
    fin = threading.Event()

    def sortir(numero, _cadre):
        fin.set()

    signal.signal(signal.SIGINT, sortir)
    signal.signal(signal.SIGTERM, sortir)
    journal.info(f"voix prête : sortie {reglages['sortie']}, voix {logique.voix}, volume "
                 f"{'inchangé' if reglages['volume'] is None else reglages['volume']}, vitesse {logique.vitesse:g} ; "
                 f"sons dans {V.dossier_sons()} ; voix présentes : {', '.join(logique.disponibles) or 'aucune'}")
    try:
        while not fin.wait(0.2):
            if not fil_ros.is_alive():
                break
    finally:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        noeud.minuterie.cancel()
        with coeur.verrou:
            sorties = logique.arreter()
        noeud.publier(sorties)
        if sorties:
            journal.info("voix arrêtée : STOP_PLAY (1004) envoyé")
        try:
            from rclpy.duration import Duration
            noeud.pub_requete.wait_for_all_acked(Duration(seconds=ATTENTE_SORTIE_S))
        except Exception:       # noqa: BLE001 : selon le RMW, l'accusé peut manquer
            time.sleep(ATTENTE_SORTIE_S)
        coeur.arreter()
        executeur.shutdown(timeout_sec=1.0)
        fil_ros.join(timeout=2.0)
        noeud.destroy_node()
        rclpy.try_shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
