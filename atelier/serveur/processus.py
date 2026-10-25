"""Lancer, suivre et arrêter les commandes longues de l'Atelier (simulation, navigation).

Chaque commande tourne dans son propre groupe de processus (start_new_session) : l'arrêter
arrête aussi tout ce qu'elle a lancé (ros2 launch, Gazebo, Nav2...). Sa sortie va dans un
journal de ~/robot-g1/journaux/.

Les commandes g1-* sont cherchées dans $ATELIER_BIN, sinon dans ~/robot-g1/bin. Les tests
mettent dans $ATELIER_BIN de fausses commandes, pour tourner sans Gazebo ni Nav2.
"""
import atexit
import os
import signal
import subprocess
import threading
import time
from collections import deque
from pathlib import Path

import atelier

ATTENTE_SIGINT = 10.0     # s laissées à ros2 launch pour tout arrêter proprement (Ctrl+C)
ATTENTE_SIGTERM = 5.0     # s après SIGTERM, avant SIGKILL


def dossier_bin():
    """Dossier des commandes g1-* : $ATELIER_BIN, sinon ~/robot-g1/bin."""
    return Path(os.environ.get("ATELIER_BIN") or atelier.RACINE / "bin").expanduser()


def commande(nom):
    """Chemin d'une commande g1-* (ex. « g1-monde »), ou None si elle n'existe pas encore."""
    chemin = dossier_bin() / nom
    return chemin if chemin.is_file() and os.access(chemin, os.X_OK) else None


class CommandeAbsente(Exception):
    """La commande g1-* demandée n'est pas installée (ex. g1-monde pas encore écrite)."""

    def __init__(self, nom):
        self.nom = nom
        super().__init__(f"la commande {nom} est introuvable dans {dossier_bin()} : "
                         "elle n'est pas encore installée")


def lancer_et_attendre(nom, arguments, delai=120.0):
    """Lance une commande courte (g1-monde generer, g1-slam...) et attend sa fin.
    Renvoie {code, sortie, duree_s}. CommandeAbsente si elle n'existe pas.
    Au-delà du délai, la commande est arrêtée et code vaut None."""
    chemin = commande(nom)
    if chemin is None:
        raise CommandeAbsente(nom)
    debut = time.monotonic()
    p = subprocess.Popen([str(chemin), *map(str, arguments)], stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
    try:
        sortie, _ = p.communicate(timeout=delai)
        code = p.returncode
    except subprocess.TimeoutExpired:
        _arreter_groupe(p)
        sortie, _ = p.communicate()
        sortie += f"\n(arrêtée par l'Atelier au bout de {delai:g} s)".encode()
        code = None
    return {"code": code, "sortie": sortie.decode("utf-8", "replace"),
            "duree_s": round(time.monotonic() - debut, 2)}


def _arreter_groupe(p, attente_sigint=ATTENTE_SIGINT):
    """Arrête tout le groupe de processus de p : SIGINT (comme Ctrl+C), puis SIGTERM, puis SIGKILL.
    On attend que le groupe entier soit vide, pas seulement le premier processus : un
    ros2 launch peut finir avant les Gazebo ou Nav2 qu'il a lancés."""
    for sig, attente in ((signal.SIGINT, attente_sigint), (signal.SIGTERM, ATTENTE_SIGTERM),
                         (signal.SIGKILL, 5.0)):
        try:
            os.killpg(p.pid, sig)
        except ProcessLookupError:
            return
        fin = time.monotonic() + attente
        while time.monotonic() < fin:
            p.poll()                      # ramasse le premier processus s'il est fini (pas de zombie)
            if not groupe_vivant(p.pid):
                return
            time.sleep(0.1)


def groupe_vivant(pgid):
    """Vrai s'il reste un processus dans le groupe pgid."""
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


class Processus:
    """Une commande longue lancée en arrière-plan, dans son groupe de processus."""

    def __init__(self, nom, arguments, journal=None, infos=None):
        self.nom = nom                    # ex. « g1-monde »
        self.arguments = [str(a) for a in arguments]
        self.infos = dict(infos or {})    # ex. {"lieu": "demo", "etage": "rdc"}
        self.journal = Path(journal) if journal else None
        self.popen = None
        self.debut = None
        self.fin = None
        self.arret_demande = False
        self._dernieres = deque(maxlen=30)
        self._fil = None

    def demarrer(self):
        chemin = commande(self.nom)
        if chemin is None:
            raise CommandeAbsente(self.nom)
        self.popen = subprocess.Popen([str(chemin), *self.arguments], stdout=subprocess.PIPE,
                                      stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                      start_new_session=True)
        self.debut = time.time()
        self._fil = threading.Thread(target=self._lire_sortie, name=f"sortie {self.nom}", daemon=True)
        self._fil.start()
        return self

    def _lire_sortie(self):
        """Recopie la sortie dans le journal et garde les dernières lignes pour l'interface."""
        f = open(self.journal, "a", encoding="utf-8") if self.journal else None
        try:
            if f:
                f.write(f"=== {time.strftime('%d/%m/%Y %H:%M:%S')} : {self.nom} {' '.join(self.arguments)}\n")
                f.flush()
            for ligne in iter(self.popen.stdout.readline, b""):
                texte = ligne.decode("utf-8", "replace").rstrip()
                self._dernieres.append(texte)
                if f:
                    f.write(texte + "\n")
                    f.flush()
            code = self.popen.wait()
            self.fin = time.time()
            if f:
                f.write(f"=== fin, code {code}\n")
        finally:
            if f:
                f.close()

    @property
    def en_cours(self):
        return self.popen is not None and self.popen.poll() is None

    def arreter(self, attente_sigint=ATTENTE_SIGINT):
        """Arrête la commande et tout ce qu'elle a lancé. Sans effet si elle est déjà finie."""
        self.arret_demande = True
        if self.popen is None:
            return
        self.popen.poll()
        if groupe_vivant(self.popen.pid):     # le groupe peut survivre à son premier processus
            _arreter_groupe(self.popen, attente_sigint)
        if self._fil:
            self._fil.join(timeout=2.0)

    def etat(self):
        """État pour l'interface : en cours, code de sortie, dernières lignes de la sortie."""
        code = None if self.popen is None else self.popen.poll()
        return {"commande": " ".join([self.nom, *self.arguments]), "en_cours": self.en_cours,
                "pid": None if self.popen is None else self.popen.pid,
                "code": code, "arret_demande": self.arret_demande,
                "debut": self.debut, "duree_s": None if self.debut is None else
                round((self.fin or time.time()) - self.debut, 1),
                "journal": str(self.journal) if self.journal else None,
                "dernieres_lignes": list(self._dernieres)[-12:], **self.infos}


class Gestionnaire:
    """Les commandes longues de l'Atelier, rangées par rôle : « simulation », « navigation »."""

    def __init__(self):
        self.processus = {}
        self.verrou = threading.Lock()
        # filet de sécurité : rien ne doit survivre au serveur
        atexit.register(self.arreter_tout, attente_sigint=3.0)

    def lancer(self, role, nom, arguments, infos=None):
        """Lance une commande pour un rôle. Une commande déjà en cours pour ce rôle est arrêtée."""
        with self.verrou:
            ancien = self.processus.get(role)
            if ancien is not None and ancien.en_cours:
                ancien.arreter()
            journal = atelier.dossier_journaux() / f"atelier_{role}_{time.strftime('%Y-%m-%d_%Hh%M%S')}.log"
            p = Processus(nom, arguments, journal, infos).demarrer()
            self.processus[role] = p
            return p

    def arreter(self, role, attente_sigint=ATTENTE_SIGINT):
        p = self.processus.get(role)
        if p is not None:
            p.arreter(attente_sigint)
        return p

    def arreter_tout(self, attente_sigint=ATTENTE_SIGINT):
        """Arrête tout, dans l'ordre inverse du lancement (la navigation avant la simulation)."""
        for role in reversed(list(self.processus)):
            self.arreter(role, attente_sigint)

    def en_cours(self, role):
        p = self.processus.get(role)
        return p is not None and p.en_cours

    def etat(self):
        return {role: p.etat() for role, p in self.processus.items()}

