"""Les primitives système des vérifications du diagnostic (vague 6, section 13.2 du plan) : agent Diagnostic.

Chaque vérification reçoit un contexte qui lui fournit ses primitives ; trois contextes, même interface :

  ContexteSysteme  le vrai : lit /sys, lance nmcli, ping, ssh et docker (jamais sudo), chacun avec son délai ;
  ContexteEssais   G1_SLAM_FAUX=1 sans fichier de faux (tous les tests de bout en bout) : comme le vrai, mais rien
                   ne part vers le réseau du robot : ni ping, ni ssh, ni « nmcli connection up » ou « modify »
                   (EssaisInterdits : la vérification dit « pas pendant les essais ») ;
  FauxContexte     ATELIER_DIAGNOSTIC_FAUX=<fichier.json> : tout est lu dans le fichier, rien n'est lancé ni
                   envoyé ; chaque commande « lancée » (et chaque ping, chaque ssh) est notée dans <fichier>.journal,
                   une ligne JSON, pour que le test vérifie ce que l'action aurait fait.

Le fichier du faux contexte (relu à chaque diagnostic : un test peut le réécrire entre deux appels) :
  {"fichiers": {"/sys/class/net/eno2/carrier": "1\\n"},
   "commandes": {"nmcli -t -f NAME,DEVICE,STATE connection show --active":
                 {"code": 0, "sortie": "robot-g1:eno2:activated\\n"}},
   "ping": {"192.168.123.161": 0.6, "192.168.123.164": null},
   "ssh": {"code": 0, "sortie": "docker_ok=oui\\n…"},
   "env": {"ROS_DOMAIN_ID": "0", "CYCLONEDDS_URI": "…"},
   "adresses": {"eno2": "192.168.123.99"},
   "delais": {"ping": 0.0, "ssh": 0.0, "commandes": 0.0}}
Une commande est la liste de ses mots joints par des espaces. Ce qui manque : fichier absent, commande
{"code": 127}, ping et ssh sans réponse, adresse absente ; une variable absente de « env » est lue dans
l'environnement du processus ; « {maintenant} » dans la sortie du ssh devient l'heure du PC au moment du ssh.
« adresses » (l'adresse IPv4 d'une interface, que le vrai contexte lit par l'ioctl SIOCGIFADDR) et « delais » (durée
simulée de chaque primitive, pour essayer les délais et le parallélisme) sont des ajouts de l'agent Diagnostic au
format de 13.2.
"""
import fcntl
import json
import os
import re
import socket
import struct
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

from atelier.lieu.diagnostic import VARIABLE_FAUX

DELAI_PING_S = 1.3              # garde-fou autour de « ping -W 1 » (comme routes/liaison.py)
DELAI_COMMANDE_S = 3.0          # une commande locale (nmcli, docker image inspect)
HOTE_JETSON = "unitree@192.168.123.164"
OPTIONS_SSH = ("-o", "BatchMode=yes", "-o", "ConnectTimeout=3")     # jamais de mot de passe demandé
SIOCGIFADDR = 0x8915            # ioctl : adresse IPv4 d'une interface
MOTIF_TEMPS = re.compile(r"time[=<]\s*([0-9.]+)\s*ms")
MOTIF_INTERFACE = (re.compile(r"""<NetworkInterface\b[^>]*\bname\s*=\s*["']([^"']+)["']"""),
                   re.compile(r"<NetworkInterfaceAddress>\s*([^<\s]+)\s*</NetworkInterfaceAddress>"))
CODE_ABSENTE = 127              # commande introuvable (comme le shell)
CODE_DELAI = 124                # délai dépassé (comme timeout)
# Commandes qui changent le réseau du PC (les actions du câble) : jamais pendant les essais
COMMANDES_RESEAU_ROBOT = (("nmcli", "connection", "up"), ("nmcli", "connection", "modify"),
                          ("nmcli", "con", "up"), ("nmcli", "con", "modify"))


class EssaisInterdits(RuntimeError):
    """Une primitive qui touche le réseau du robot, refusée pendant les essais (G1_SLAM_FAUX=1)."""


class Resultat(dict):
    """Résultat d'une commande : {code, sortie, erreur, duree_s} (un dict, pour le journal et les tests)."""

    @property
    def code(self):
        return self["code"]

    @property
    def sortie(self):
        return self.get("sortie", "")

    @property
    def erreur(self):
        return self.get("erreur", "")


def interface_cyclonedds(uri):
    """Interface réseau choisie par un CYCLONEDDS_URI (setup/robot.sh met eno2), ou None (comme routes/liaison.py)."""
    for motif in MOTIF_INTERFACE:
        m = motif.search(uri or "")
        if m:
            return m.group(1)
    return None


def lire_ping(sortie):
    """Durée en ms lue dans la sortie de ping (« time=0.62 ms »), ou None."""
    m = MOTIF_TEMPS.search(sortie or "")
    return float(m.group(1)) if m else None


def touche_reseau_robot(mots):
    """Vrai si la commande change la connexion du câble (nmcli connection up / modify)."""
    mots = tuple(str(m) for m in mots)
    return any(mots[:len(debut)] == debut for debut in COMMANDES_RESEAU_ROBOT)


def hote_jetson(env):
    """Hôte ssh du Jetson : la variable G1_JETSON (comme g1-jetson), sinon unitree@192.168.123.164."""
    return env("G1_JETSON") or HOTE_JETSON


class ContexteSysteme:
    """Le vrai contexte : les primitives lancent les commandes du PC, chacune avec son délai."""

    nom = "systeme"
    faux = False
    essais = False

    def env(self, nom, defaut=None):
        valeur = os.environ.get(nom)
        return defaut if valeur is None else valeur

    def maintenant(self):
        return time.time()

    def lire(self, chemin):
        """Texte d'un fichier (ex. /sys/class/net/eno2/carrier), ou None s'il est absent ou illisible."""
        try:
            with open(chemin, encoding="utf-8") as f:
                return f.read()
        except (OSError, ValueError):
            return None

    def adresse_ipv4(self, interface):
        """Adresse IPv4 du PC sur l'interface (ex. 192.168.123.99), ou None (ioctl, rien n'est envoyé)."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                brut = fcntl.ioctl(s.fileno(), SIOCGIFADDR, struct.pack("256s", str(interface)[:15].encode()))
            return socket.inet_ntoa(brut[20:24])
        except OSError:
            return None

    def commande(self, mots, delai=DELAI_COMMANDE_S, entree=None):
        """Lance une commande (liste de mots, sans shell), en anglais (LC_ALL=C : sorties de nmcli stables)."""
        debut = time.monotonic()
        env = dict(os.environ, LC_ALL="C", LANG="C")
        try:
            r = subprocess.run([str(m) for m in mots], input=entree, capture_output=True, text=True,
                               timeout=delai, env=env, stdin=None if entree is not None else subprocess.DEVNULL)
        except FileNotFoundError:
            return Resultat(code=CODE_ABSENTE, sortie="", erreur=f"{mots[0]} : commande introuvable",
                            duree_s=round(time.monotonic() - debut, 3))
        except subprocess.TimeoutExpired as e:
            sortie = e.stdout.decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
            return Resultat(code=CODE_DELAI, sortie=sortie, erreur=f"délai de {delai:g} s dépassé",
                            duree_s=round(time.monotonic() - debut, 3))
        except OSError as e:
            return Resultat(code=CODE_ABSENTE, sortie="", erreur=str(e), duree_s=round(time.monotonic() - debut, 3))
        return Resultat(code=r.returncode, sortie=r.stdout, erreur=r.stderr, duree_s=round(time.monotonic() - debut, 3))

    def ping(self, adresse, delai=DELAI_PING_S):
        """Durée d'un « ping -c 1 -W 1 » en ms, ou None sans réponse. FileNotFoundError si ping manque."""
        r = self.commande(["ping", "-n", "-c", "1", "-W", "1", str(adresse)], delai=delai)
        if r.code == CODE_ABSENTE:
            raise FileNotFoundError("la commande ping manque")
        if r.code != 0:
            return None
        ms = lire_ping(r.sortie)
        return ms if ms is not None else round(r["duree_s"] * 1000.0, 1)

    def ssh(self, script, delai=6.0):
        """UN ssh vers le Jetson (BatchMode, ConnectTimeout 3 s) qui lance le script par « bash -s »."""
        mots = ["ssh", *OPTIONS_SSH, hote_jetson(self.env), "bash -s"]
        return self.commande(mots, delai=delai, entree=script)


class ContexteEssais(ContexteSysteme):
    """Pendant les essais (G1_SLAM_FAUX=1) : le vrai contexte, sauf le réseau du robot (ni ping, ni ssh, ni nmcli
    connection up ou modify)."""

    nom = "essais"
    essais = True

    def ping(self, adresse, delai=DELAI_PING_S):
        raise EssaisInterdits("pas pendant les essais : aucun ping vers le robot")

    def ssh(self, script, delai=6.0):
        raise EssaisInterdits("pas pendant les essais : aucun ssh vers le Jetson")

    def commande(self, mots, delai=DELAI_COMMANDE_S, entree=None):
        if touche_reseau_robot(mots):
            raise EssaisInterdits("pas pendant les essais : la connexion du câble n'est pas touchée")
        return super().commande(mots, delai=delai, entree=entree)


class FauxContexte:
    """Le faux contexte des tests (ATELIER_DIAGNOSTIC_FAUX) : réponses lues dans un fichier JSON, rien n'est lancé ;
    chaque commande, ping et ssh « lancé » est noté dans <fichier>.journal."""

    nom = "faux"
    faux = True
    essais = False

    def __init__(self, donnees, journal=None):
        if not isinstance(donnees, dict):
            raise ValueError("faux contexte du diagnostic : un objet JSON est attendu")
        self.donnees = donnees
        self.journal = Path(journal) if journal else None
        self._verrou = threading.Lock()

    @classmethod
    def depuis_fichier(cls, chemin):
        """Le faux contexte d'un fichier JSON ; ValueError (en français) s'il est illisible."""
        chemin = Path(chemin)
        try:
            donnees = json.loads(chemin.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise ValueError(f"{VARIABLE_FAUX} : le fichier {chemin} est illisible ({e})") from None
        return cls(donnees, journal=Path(str(chemin) + ".journal"))

    def _partie(self, nom):
        partie = self.donnees.get(nom)
        return partie if isinstance(partie, dict) else {}

    def _attendre(self, genre):
        delai = self._partie("delais").get(genre)
        if isinstance(delai, (int, float)) and not isinstance(delai, bool) and delai > 0:
            time.sleep(min(float(delai), 60.0))

    def noter(self, genre, **champs):
        """Une ligne du journal : {t, genre, …}."""
        if self.journal is None:
            return
        ligne = dict(t=datetime.now().astimezone().isoformat(timespec="milliseconds"), genre=genre, **champs)
        with self._verrou:
            with open(self.journal, "a", encoding="utf-8") as f:
                f.write(json.dumps(ligne, ensure_ascii=False) + "\n")

    def env(self, nom, defaut=None):
        partie = self._partie("env")
        if nom in partie:
            valeur = partie[nom]
            return defaut if valeur is None else str(valeur)
        valeur = os.environ.get(nom)
        return defaut if valeur is None else valeur

    def maintenant(self):
        return time.time()

    def lire(self, chemin):
        valeur = self._partie("fichiers").get(str(chemin))
        return None if valeur is None else str(valeur)

    def adresse_ipv4(self, interface):
        valeur = self._partie("adresses").get(str(interface))
        return None if valeur is None else str(valeur)

    def commande(self, mots, delai=DELAI_COMMANDE_S, entree=None):
        texte = " ".join(str(m) for m in mots)
        self._attendre("commandes")
        reponse = self._partie("commandes").get(texte)
        if not isinstance(reponse, dict):
            r = Resultat(code=CODE_ABSENTE, sortie="", erreur=f"{mots[0]} : commande introuvable (faux contexte)",
                         duree_s=0.0)
        else:
            r = Resultat(code=int(reponse.get("code", 0)), sortie=str(reponse.get("sortie", "")),
                         erreur=str(reponse.get("erreur", "")), duree_s=0.0)
        self.noter("commande", commande=texte, mots=[str(m) for m in mots], code=r.code)
        return r

    def ping(self, adresse, delai=DELAI_PING_S):
        self._attendre("ping")
        valeur = self._partie("ping").get(str(adresse))
        self.noter("ping", adresse=str(adresse), repond=valeur is not None)
        if valeur is None or isinstance(valeur, bool):
            return None
        return float(valeur)

    def ssh(self, script, delai=6.0):
        self._attendre("ssh")
        hote = hote_jetson(self.env)
        self.noter("ssh", hote=hote, script=str(script)[:200])
        reponse = self.donnees.get("ssh")
        if not isinstance(reponse, dict):
            return Resultat(code=255, sortie="", erreur=f"ssh: connect to host {hote}: Connection timed out",
                            duree_s=0.0)
        # « {maintenant} » dans la sortie : l'heure du PC au moment du ssh (un Jetson à l'heure, quel que soit le
        # moment où le fichier a été écrit)
        sortie = str(reponse.get("sortie", "")).replace("{maintenant}", f"{time.time():.6f}")
        return Resultat(code=int(reponse.get("code", 0)), sortie=sortie, erreur=str(reponse.get("erreur", "")),
                        duree_s=0.0)


def contexte_par_defaut():
    """Le contexte des vérifications système : le faux de $ATELIER_DIAGNOSTIC_FAUX s'il est donné (tests), sinon
    celui des essais avec G1_SLAM_FAUX=1, sinon le vrai. ValueError si le fichier du faux est illisible."""
    chemin = os.environ.get(VARIABLE_FAUX)
    if chemin:
        return FauxContexte.depuis_fichier(chemin)
    if os.environ.get("G1_SLAM_FAUX") == "1":
        return ContexteEssais()
    return ContexteSysteme()
