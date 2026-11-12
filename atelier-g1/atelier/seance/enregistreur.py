"""L'enregistreur ROS 2 de la boîte noire (vague 6, section 13.3 du plan) : g1-seance enregistrer --dossier D.

Un enregistreur à soi plutôt que « ros2 bag record », qui ne sait pas réduire la fréquence d'un sujet :
  - seulement les sujets de SUJETS_SEANCE, chacun au plus à sa fréquence ; jamais les types de TYPES_JAMAIS
    (nuages de points, images) ni SUJETS_JAMAIS (les morceaux de son) ; le type est lu sur le graphe, et un sujet
    qui apparaît en cours de séance est pris (graphe relu toutes les 2 s) ;
  - léger : pas d'exécuteur rclpy (son coût par message est élevé en Python) ; l'enregistreur vient PRENDRE les
    messages (take) dans la file de chaque abonnement, à son rythme. Un sujet à fréquence réduite (odométrie à
    10 Hz…) a une file de profondeur 1, relevée à cette fréquence : les messages en trop sont jetés par DDS, sans
    jamais passer par Python ; les autres sujets sont relevés 20 fois par seconde, tous leurs messages pris ;
  - /rosout : les avertissements et les erreurs sont toujours gardés ; les autres lignes, 50 par seconde au plus
    (en rafale : le démarrage de Nav2 écrit beaucoup d'un coup) ;
  - abonnements bruts (les messages ne sont pas décodés : ils vont tels quels dans le bag) ; QoS « au mieux » et
    « volatile » (jamais un lecteur fiable qui ralentirait le pont ou le robot), sauf les sujets dont tous les
    éditeurs sont fiables et gardent le dernier message (transient_local : /pont/arret, /mouvement/maitre…), lus en
    fiable et transient_local pour recevoir l'état d'avant l'ouverture ;
  - le bag : rosbag2 (rosbag2_py.SequentialWriter), stockage sqlite3 de Humble, réglage « resilient » (journal WAL :
    un plantage du PC laisse un bag lisible ; ros2 bag reindex refait metadata.yaml s'il manque) ; lisible par
    ros2 bag info ; horodatage : l'heure du PC quand le message est pris (à 50 ms près, 100 ms à 10 Hz) ;
  - garde-fous (REGLAGES_SEANCE, toutes les 5 s) : bag plus gros que taille_max_mo, ou place libre du disque sous
    place_libre_min_go → l'enregistrement s'arrête proprement (état « coupe », message en français) ; la séance de
    l'Atelier reste ouverte ;
  - os.nice(10) : l'enregistreur passe après Nav2 et le serveur ;
  - --atelier PID : si l'Atelier qui l'a lancé disparaît (plantage, SIGKILL), l'enregistreur ferme son bag
    proprement et s'arrête (il ne tourne jamais seul indéfiniment) ;
  - SIGINT ou SIGTERM : fermeture propre (le bag reçoit son metadata.yaml), puis fin.
L'état est écrit dans enregistrement.json (à côté de bag/), toutes les secondes, de façon atomique : {version, etat,
pid, debut, maj, octets, messages, sujets, par_sujet, recus, ignores, message, cpu_s, cpu_moyen, cpu_recent}.
Le serveur le lit pour le manifeste et le badge de la barre d'outils. Rien n'est jamais publié.
"""
import json
import os
import resource
import shutil
import signal
import sys
import threading
import time
from pathlib import Path

from atelier.lieu.fichiers import ecrire_atomique
from atelier.lieu.seance import FICHIERS_SEANCE, SUJETS_JAMAIS, SUJETS_SEANCE, TYPES_JAMAIS, reglage
from .manifeste import heure_iso

FICHIER_ETAT = "enregistrement.json"
NOEUD_ENREGISTREUR = "atelier_boite_noire"   # dans NOEUDS_ATELIER du pont : le diagnostic ne le prend pas pour le robot
PERIODE_GRAPHE_S = 2.0            # relecture du graphe ROS 2 (sujets apparus, éditeurs nouveaux)
PERIODE_ETAT_S = 1.0              # enregistrement.json et surveillance de l'Atelier
PERIODE_RELEVE_S = 0.05           # sujets gardés en entier : relevés 20 fois par seconde
PROFONDEUR = 100                  # file d'un sujet gardé en entier (2 000 messages par seconde au plus)
PROFONDEUR_JOURNAL = 500          # /rosout arrive par rafales
PRISES_MAX = 2000                 # messages pris au plus par sujet et par relevé
NIVEAU_TOUJOURS = 30              # /rosout : WARN (30), ERROR (40) et FATAL (50) toujours gardés
OCTET_NIVEAU_LOG = 12             # rcl_interfaces/msg/Log sérialisé : 4 octets d'en-tête CDR + stamp (8), puis level
MO = 1000 * 1000                  # unités des garde-fous : Mo et Go décimaux (comme df -H)
GO = 1000 * MO
SUJET_JOURNAL = "/rosout"
# Un sujet à fréquence réduite est relevé toutes les MARGE_FREQUENCE / f secondes : même compté « nombre / durée » sur
# quelques secondes, il reste sous sa fréquence (le compte a un message de plus que les intervalles)
MARGE_FREQUENCE = 1.03


class Limiteur:
    """Au plus `frequence` messages par seconde. Sans rafale : un message gardé au plus toutes les 1/frequence s ;
    avec rafale : un seau de `frequence` jetons rempli à `frequence` par seconde (les lignes de journal arrivent
    par paquets). frequence None : tout est gardé."""

    def __init__(self, frequence, rafale=False):
        self.frequence = frequence
        self.rafale = rafale
        self.dernier = None
        self.jetons = float(frequence or 0)
        self.t_jetons = None

    def garder(self, t):
        """t : secondes (horloge quelconque, croissante)."""
        if not self.frequence:
            return True
        if self.rafale:
            if self.t_jetons is not None:
                self.jetons = min(float(self.frequence), self.jetons + (t - self.t_jetons) * self.frequence)
            self.t_jetons = t
            if self.jetons >= 1.0:
                self.jetons -= 1.0
                return True
            return False
        if self.dernier is None or t - self.dernier >= 1.0 / self.frequence - 1e-9:
            self.dernier = t
            return True
        return False


def taille_dossier(dossier):
    """Octets de tous les fichiers d'un dossier (le bag : .db3, -wal, -shm, metadata.yaml)."""
    total = 0
    for racine, _, fichiers in os.walk(dossier):
        for nom in fichiers:
            try:
                total += os.stat(os.path.join(racine, nom)).st_size
            except OSError:
                pass
    return total


def raison_coupure(octets, libre, taille_max_mo, place_min_go):
    """Phrase qui dit pourquoi l'enregistrement doit s'arrêter (garde-fous), ou None (fonction pure)."""
    fr = lambda x, n: f"{x:,.{n}f}".replace(",", "\u202f").replace(".", ",")    # noqa: E731 (1 024,5)
    if libre is not None and libre < place_min_go * GO:
        return (f"Enregistrement arrêté : il ne reste que {fr(libre / GO, 1)} Go sur le disque (au moins "
                f"{fr(place_min_go, 0 if place_min_go == int(place_min_go) else 1)} Go sont gardés libres). La séance "
                "continue sans enregistrement : libérez de la place, puis ouvrez une nouvelle séance.")
    if octets > taille_max_mo * MO:
        return (f"Enregistrement arrêté : il a atteint {fr(octets / MO, 0)} Mo, la taille maximale d'une séance "
                f"({fr(taille_max_mo, 0)} Mo). La séance continue sans enregistrement ; terminez-la pour en ouvrir "
                "une nouvelle.")
    return None


def debut_processus(pid):
    """Heure de démarrage d'un processus (champ 22 de /proc/PID/stat, en tops d'horloge), ou None s'il n'existe
    pas : un PID réutilisé par un autre programme n'est pas pris pour l'Atelier."""
    try:
        texte = Path(f"/proc/{int(pid)}/stat").read_text()
    except (OSError, ValueError):
        return None
    champs = texte.rsplit(")", 1)[-1].split()
    try:
        return int(champs[19])
    except (IndexError, ValueError):
        return None


def qos_lecture(publieurs):
    """« transitoire » si tous les éditeurs sont fiables et gardent le dernier message (transient_local : un
    lecteur fiable et transient_local reçoit alors l'état d'avant son arrivée), sinon « au_mieux » (un lecteur au
    mieux et volatile convient à tout éditeur, et ne ralentit jamais un éditeur fiable)."""
    from rclpy.qos import DurabilityPolicy, ReliabilityPolicy
    if publieurs and all(getattr(p.qos_profile, "durability", None) == DurabilityPolicy.TRANSIENT_LOCAL
                         and getattr(p.qos_profile, "reliability", None) == ReliabilityPolicy.RELIABLE
                         for p in publieurs):
        return "transitoire"
    return "au_mieux"


class _Releve:
    """Un abonnement de l'enregistreur : sa file, son rythme de relevé, son limiteur (/rosout)."""

    def __init__(self, sujet, abonnement, genre, type_ros, frequence):
        self.sujet = sujet
        self.abonnement = abonnement
        self.genre = genre
        self.type_ros = type_ros
        self.frequence = frequence
        self.periode = MARGE_FREQUENCE / frequence if frequence and sujet != SUJET_JOURNAL else PERIODE_RELEVE_S
        self.echeance = 0.0
        self.limiteur = Limiteur(frequence, rafale=True) if sujet == SUJET_JOURNAL else None


class Enregistreur:
    """L'enregistrement d'une séance dans dossier/bag. reglages : taille_max_mo, place_libre_min_go,
    periode_controle_s (défaut : REGLAGES_SEANCE et leurs variables). atelier_pid : l'Atelier à surveiller."""

    def __init__(self, dossier, atelier_pid=None, reglages=None, sujets=None, sortie=sys.stdout):
        self.dossier = Path(dossier)
        self.bag = self.dossier / FICHIERS_SEANCE["bag"]
        reglages = dict(reglages or {})
        self.taille_max_mo = float(reglages.get("taille_max_mo") or reglage("taille_max_mo"))
        self.place_min_go = float(reglages.get("place_libre_min_go", reglage("place_libre_min_go")))
        self.periode_controle = float(reglages.get("periode_controle_s") or reglage("periode_controle_s"))
        self.sujets = dict(SUJETS_SEANCE if sujets is None else sujets)
        self.atelier_pid = int(atelier_pid) if atelier_pid else None
        self.atelier_debut = debut_processus(self.atelier_pid) if self.atelier_pid else None
        self.sortie = sortie
        self.etat = "demarrage"
        self.message = None
        self.debut = time.time()
        self.debut_iso = heure_iso(self.debut)
        self.messages = 0
        self.par_sujet = {}               # sujet → messages écrits
        self.recus = {}                   # sujet → messages pris dans la file (avant le limiteur de /rosout)
        self.ignores = {}                 # sujet → raison (type jamais enregistré, type introuvable…)
        self.releves = {}                 # sujet → _Releve
        self.types_ecrits = {}            # sujet → type déclaré au bag
        self.octets = 0
        self.fin = threading.Event()
        self.writer = None
        self.noeud = None
        self.contexte = None
        self._dernier_controle = 0.0
        self._cpu_avant = (time.monotonic(), self.cpu())
        self.cpu_recent = None

    # ------------------------------------------------------------ journal et état

    def dire(self, texte):
        try:
            print(f"[{heure_iso()}] {texte}", file=self.sortie, flush=True)
        except (OSError, ValueError):
            pass

    @staticmethod
    def cpu():
        r = resource.getrusage(resource.RUSAGE_SELF)
        return r.ru_utime + r.ru_stime

    def etat_courant(self):
        duree = max(1e-6, time.time() - self.debut)
        cpu = self.cpu()
        return {"version": 1, "etat": self.etat, "pid": os.getpid(), "debut": self.debut_iso, "maj": heure_iso(),
                "octets": self.octets, "messages": self.messages, "sujets": sorted(self.releves),
                "par_sujet": dict(sorted(self.par_sujet.items())), "recus": dict(sorted(self.recus.items())),
                "ignores": dict(sorted(self.ignores.items())), "message": self.message,
                "cpu_s": round(cpu, 3), "cpu_moyen": round(cpu / duree, 4), "cpu_recent": self.cpu_recent,
                "atelier_pid": self.atelier_pid,
                "reglages": {"taille_max_mo": self.taille_max_mo, "place_libre_min_go": self.place_min_go}}

    def ecrire_etat(self):
        if self.writer is not None and self.bag.exists():
            self.octets = taille_dossier(self.bag)          # le badge montre la taille à jour (une fois par seconde)
        try:
            ecrire_atomique(self.dossier / FICHIER_ETAT, json.dumps(self.etat_courant(), ensure_ascii=False,
                                                                    indent=1) + "\n")
        except OSError as e:
            self.dire(f"état non écrit : {e}")

    # ------------------------------------------------------------ garde-fous

    def controler(self, forcer=False):
        """Taille du bag et place libre ; coupe l'enregistrement si un garde-fou l'exige. Renvoie la raison ou None."""
        maintenant = time.monotonic()
        if not forcer and maintenant - self._dernier_controle < self.periode_controle:
            return None
        self._dernier_controle = maintenant
        self.octets = taille_dossier(self.bag) if self.bag.exists() else 0
        try:
            libre = shutil.disk_usage(self.dossier).free
        except OSError:
            libre = None
        raison = raison_coupure(self.octets, libre, self.taille_max_mo, self.place_min_go)
        if raison:
            self.couper(raison)
        return raison

    def couper(self, raison):
        self.dire(raison)
        self.etat = "coupe"
        self.message = raison
        self.fin.set()

    def atelier_vivant(self):
        if not self.atelier_pid:
            return True
        return debut_processus(self.atelier_pid) == self.atelier_debut

    # ------------------------------------------------------------ ROS 2

    def _ouvrir_bag(self):
        import rosbag2_py
        if self.bag.exists():
            raise RuntimeError(f"le dossier {self.bag} existe déjà : une séance n'a qu'un enregistrement")
        self.writer = rosbag2_py.SequentialWriter()
        self.writer.open(rosbag2_py.StorageOptions(uri=str(self.bag), storage_id="sqlite3",
                                                   storage_preset_profile="resilient"),
                         rosbag2_py.ConverterOptions("cdr", "cdr"))
        self._TopicMetadata = rosbag2_py.TopicMetadata

    def _qos(self, genre, sujet):
        from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
        if genre == "transitoire":
            return QoSProfile(depth=10, history=HistoryPolicy.KEEP_LAST, reliability=ReliabilityPolicy.RELIABLE,
                              durability=DurabilityPolicy.TRANSIENT_LOCAL)
        profondeur = PROFONDEUR_JOURNAL if sujet == SUJET_JOURNAL else (1 if self.sujets.get(sujet) else PROFONDEUR)
        return QoSProfile(depth=profondeur, history=HistoryPolicy.KEEP_LAST,
                          reliability=ReliabilityPolicy.BEST_EFFORT, durability=DurabilityPolicy.VOLATILE)

    def relire_graphe(self):
        """Abonne l'enregistreur aux sujets de la liste qui ont un éditeur ; refait un abonnement dont la QoS ne
        convient plus (un éditeur volatile est apparu sur un sujet lu en transient_local)."""
        from rosidl_runtime_py.utilities import get_message
        try:
            graphe = self.noeud.get_topic_names_and_types()
        except Exception as e:      # noqa: BLE001 : graphe indisponible (arrêt en cours)
            self.dire(f"graphe illisible : {e}")
            return
        for sujet, types in graphe:
            if sujet not in self.sujets:
                continue
            if sujet in SUJETS_JAMAIS:
                self.ignores[sujet] = "jamais enregistré (son du robot)"
                continue
            type_ros = types[0] if types else None
            if not type_ros:
                continue
            if type_ros in TYPES_JAMAIS:
                self.ignores[sujet] = f"jamais enregistré ({type_ros} : nuage de points ou image)"
                continue
            try:
                publieurs = list(self.noeud.get_publishers_info_by_topic(sujet))
            except Exception:       # noqa: BLE001
                continue
            if not publieurs:
                continue
            # /rosout : les éditeurs gardent leurs 1 000 dernières lignes (transient_local) ; un lecteur volatile ne
            # reçoit pas cet historique d'un coup (des milliers de lignes d'avant la séance)
            genre = "au_mieux" if sujet == SUJET_JOURNAL else qos_lecture(publieurs)
            ancien = self.releves.get(sujet)
            if ancien is not None:
                if ancien.genre == genre or genre == "transitoire":
                    continue            # garder : un abonnement volatile convient à tous les éditeurs
                self.noeud.destroy_subscription(ancien.abonnement)
                del self.releves[sujet]
            if sujet in self.types_ecrits and self.types_ecrits[sujet] != type_ros:
                self.ignores[sujet] = f"type changé en cours de séance ({type_ros})"
                continue
            try:
                classe = get_message(type_ros)
            except Exception:       # noqa: BLE001 : paquet du message absent sur ce PC
                self.ignores[sujet] = f"type introuvable sur ce PC ({type_ros})"
                continue
            if sujet not in self.types_ecrits:
                self.writer.create_topic(self._TopicMetadata(sujet, type_ros, "cdr", ""))
                self.types_ecrits[sujet] = type_ros
            self.ignores.pop(sujet, None)
            # pas de fonction de rappel : les messages sont pris par relever(), sans exécuteur
            abonnement = self.noeud.create_subscription(classe, sujet, lambda _m: None, self._qos(genre, sujet),
                                                        raw=True)
            self.releves[sujet] = _Releve(sujet, abonnement, genre, type_ros, self.sujets.get(sujet))
            self.dire(f"enregistré : {sujet} ({type_ros}, "
                      + (f"{self.sujets[sujet]:g} Hz au plus" if self.sujets.get(sujet) else "tous les messages")
                      + (", transient_local" if genre == "transitoire" else "") + ")")

    def relever(self, r, maintenant, t_mur=None):
        """Prend les messages en attente d'un abonnement et les écrit dans le bag, à l'heure murale t_mur (ns) du
        relevé : deux relevés d'un sujet réduit sont toujours séparés d'au moins sa période. Renvoie le nombre pris."""
        t_mur = time.time_ns() if t_mur is None else t_mur
        pris = 0
        abonnement = r.abonnement
        # un sujet réduit : un seul message par relevé (le plus récent). Un message neuf arrivé pendant l'écriture
        # dans le bag attend le relevé suivant : jamais deux messages en moins d'une période
        maximum = 1 if r.frequence and r.limiteur is None else PRISES_MAX
        while pris < maximum:
            with abonnement.handle:
                recu = abonnement.handle.take_message(abonnement.msg_type, True)
            if recu is None:
                break
            pris += 1
            donnees = recu[0]
            if r.limiteur is not None:
                urgent = len(donnees) > OCTET_NIVEAU_LOG and donnees[OCTET_NIVEAU_LOG] >= NIVEAU_TOUJOURS
                if not urgent and not r.limiteur.garder(maintenant):
                    continue
            try:
                self.writer.write(r.sujet, donnees, t_mur + pris)        # + pris : l'ordre d'arrivée reste
            except Exception as e:      # noqa: BLE001 : disque plein, bag fermé…
                self.dire(f"écriture impossible ({r.sujet}) : {e}")
                self.etat, self.message = "erreur", f"Enregistrement arrêté : écriture impossible ({e})."[:300]
                self.fin.set()
                break
            self.messages += 1
            self.par_sujet[r.sujet] = self.par_sujet.get(r.sujet, 0) + 1
        if pris:
            self.recus[r.sujet] = self.recus.get(r.sujet, 0) + pris
        return pris

    def _surveiller(self):
        """Toutes les secondes : l'Atelier vit-il encore ? les garde-fous ; le processeur ; l'état écrit."""
        if not self.atelier_vivant():
            self.dire("l'Atelier qui a lancé l'enregistrement ne tourne plus : fermeture du bag")
            self.message = "L'Atelier s'est arrêté sans fermer la séance : l'enregistrement a été fermé proprement."
            self.fin.set()
            return
        t, cpu = time.monotonic(), self.cpu()
        t0, cpu0 = self._cpu_avant
        if t - t0 >= 10.0:
            self.cpu_recent = round((cpu - cpu0) / (t - t0), 4)       # part d'un cœur sur les 10 dernières s
            self._cpu_avant = (t, cpu)
        self.controler()
        self.ecrire_etat()

    def executer(self):
        """Enregistre jusqu'à SIGINT, SIGTERM, un garde-fou ou la disparition de l'Atelier. Code de sortie : 0, ou 1
        si l'enregistrement n'a pas pu commencer."""
        try:
            os.nice(10)
        except OSError:
            pass
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: self.fin.set())
        self.dossier.mkdir(parents=True, exist_ok=True)
        # place libre trop faible dès le départ : rien n'est ouvert
        try:
            libre = shutil.disk_usage(self.dossier).free
        except OSError:
            libre = None
        raison = raison_coupure(0, libre, self.taille_max_mo, self.place_min_go)
        if raison:
            self.couper(raison)
            self.ecrire_etat()
            return 0
        try:
            import rclpy
            from rclpy.signals import SignalHandlerOptions
            self.contexte = rclpy.Context()
            rclpy.init(context=self.contexte, signal_handler_options=SignalHandlerOptions.NO)
            self.noeud = rclpy.create_node(NOEUD_ENREGISTREUR, context=self.contexte,
                                           start_parameter_services=False, enable_rosout=False)
            self._ouvrir_bag()
        except Exception as e:      # noqa: BLE001 : ROS 2 absent, bag impossible à créer…
            self.etat = "absent" if isinstance(e, ImportError) else "erreur"
            self.message = (f"Enregistrement impossible : {e}."[:300] if self.etat == "erreur" else
                            "Enregistrement impossible : ROS 2 n'est pas chargé (source ~/robot-g1/setup/env.sh).")
            self.dire(self.message)
            self.ecrire_etat()
            self._fermer_ros()
            return 1
        self.etat = "en_cours"
        self.dire(f"enregistrement de la séance dans {self.bag} (taille maximale {self.taille_max_mo:g} Mo, "
                  f"place libre gardée {self.place_min_go:g} Go)")
        self._cpu_avant = (time.monotonic(), self.cpu())
        self.relire_graphe()
        self.ecrire_etat()
        prochain_graphe = time.monotonic() + PERIODE_GRAPHE_S
        prochain_etat = time.monotonic() + PERIODE_ETAT_S
        try:
            while not self.fin.is_set() and self.contexte.ok():
                maintenant, t_mur = time.monotonic(), time.time_ns()
                for r in list(self.releves.values()):
                    if maintenant >= r.echeance:
                        self.relever(r, maintenant, t_mur)
                        r.echeance = maintenant + r.periode
                if maintenant >= prochain_graphe:
                    self.relire_graphe()
                    prochain_graphe = maintenant + PERIODE_GRAPHE_S
                if maintenant >= prochain_etat:
                    self._surveiller()
                    prochain_etat = maintenant + PERIODE_ETAT_S
                prochaine = min([r.echeance for r in self.releves.values()] + [prochain_graphe, prochain_etat])
                self.fin.wait(min(PERIODE_RELEVE_S, max(0.002, prochaine - time.monotonic())))
            # les derniers messages arrivés avant l'arrêt, des sujets gardés en entier seulement (un sujet réduit
            # relevé maintenant pourrait l'être moins d'une période après son dernier relevé)
            if self.etat == "en_cours":
                for r in list(self.releves.values()):
                    if not r.frequence or r.sujet == SUJET_JOURNAL:
                        self.relever(r, time.monotonic())
        finally:
            self.fermer()
        return 0

    def fermer(self):
        """Ferme le bag (metadata.yaml écrit) et le nœud ; l'état final est écrit."""
        for r in list(self.releves.values()):
            try:
                self.noeud.destroy_subscription(r.abonnement)
            except Exception:       # noqa: BLE001
                pass
        if self.writer is not None:
            writer, self.writer = self.writer, None
            try:
                writer.close()
            except Exception as e:      # noqa: BLE001
                self.dire(f"fermeture du bag : {e}")
        self.octets = taille_dossier(self.bag) if self.bag.exists() else 0
        if self.etat in ("demarrage", "en_cours"):
            self.etat = "arrete"
        self.ecrire_etat()
        self._fermer_ros()
        self.dire(f"fin : {self.messages} messages, {self.octets / MO:.1f} Mo, état {self.etat}, processeur "
                  f"{self.etat_courant()['cpu_moyen'] * 100:.1f} % d'un cœur en moyenne")

    def _fermer_ros(self):
        if self.noeud is not None:
            try:
                self.noeud.destroy_node()
            except Exception:       # noqa: BLE001
                pass
            self.noeud = None
        if self.contexte is not None:
            try:
                import rclpy
                rclpy.try_shutdown(context=self.contexte)
            except Exception:       # noqa: BLE001
                pass
            self.contexte = None


def lire_etat(dossier):
    """enregistrement.json d'une séance (dict), ou None."""
    try:
        donnees = json.loads((Path(dossier) / FICHIER_ETAT).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return donnees if isinstance(donnees, dict) else None


def enregistrer(dossier, atelier_pid=None, reglages=None):
    """g1-seance enregistrer : l'enregistreur seul, jusqu'à SIGINT. Renvoie le code de sortie."""
    return Enregistreur(dossier, atelier_pid=atelier_pid, reglages=reglages).executer()
