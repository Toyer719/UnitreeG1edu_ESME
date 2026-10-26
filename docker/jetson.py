#!/usr/bin/env python3
"""
Commande g1-jetson : le conteneur ROS 2 Humble du Jetson du G1 (section 10.2 du plan).

  g1-jetson construire [--arch arm64|amd64] [--sans-cache] [--incomplet]
      construit l'image g1-jetson:<arch> (arm64 par défaut, par émulation : 5 à 30 min la
      première fois ; amd64 pour les essais sur le PC). Une image à jour est réutilisée.
      --contexte DOSSIER : prépare seulement le contexte, pour construire sur le Jetson (plan B).
  g1-jetson envoyer
      robot : docker save g1-jetson:arm64 | gzip, copie par scp, puis docker load sur le Jetson
  g1-jetson lieu --lieu L
      robot : copie le dossier du lieu, sans scans/, dans ~/robot-g1/lieux/<id> du Jetson
  g1-jetson demarrer --lieu L --etage E [--local] [--localisation unitree|amcl] [--veille]
                     [--wifi IFACE --pair IP]
      lance le conteneur (sur le robot, le lieu est d'abord copié) ; rend la main quand il
      tourne (30 s au plus)
  g1-jetson tester-local --lieu L --etage E
      essai sur le PC : demarrer --local (image amd64, réseau de l'hôte, lieu monté), puis
      lecture de /g1_jetson/etat ; g1-jetson arreter --local pour finir
  g1-jetson arreter [--local]       docker stop (arrêt propre, 20 s au plus), puis docker rm
  g1-jetson etat [--local] [--json] conteneur, image, lieu, interfaces, dernier /g1_jetson/etat ;
                                    code 0 s'il tourne, 1 sinon
  g1-jetson journal [--local] [-f]  docker logs
  g1-jetson shell [--local]         un terminal dans le conteneur, environnement ROS 2 chargé
  g1-jetson verifier                robot : Docker, architecture, place, mémoire, interface
                                    192.168.123.x, puis un conteneur qui doit voir les sujets du robot

--dry-run (toutes les commandes) : affiche ce qui serait lancé, sans rien lancer ni rien envoyer.
Le Jetson est joint par ssh : unitree@192.168.123.164, ou la variable G1_JETSON. Avec
G1_SLAM_FAUX=1 (tous les tests), toute commande vers le Jetson est refusée, sauf à blanc.
Essai sur le PC (--local) : image amd64, conteneur g1-jetson-local (G1_JETSON_NOM le change),
ROS_DOMAIN_ID du terminal, G1_INTERFACES=defaut, lieux de $ATELIER_LIEUX, journaux dans
~/robot-g1/journaux/jetson_local/. G1_SIMU, G1_INTERFACES et G1_CYCLONEDDS_URI du terminal sont
transmis au conteneur s'ils sont définis ; G1_JETSON_ARCH=arm64 essaie l'image du robot sur le PC,
par émulation (lent, pour vérifier l'image avant de l'envoyer). G1_JETSON_RUNTIME=runc ajoute
--runtime runc au lancement (si le runtime nvidia par défaut du Jetson gêne).

Code de sortie : 0 réussi, 1 échec (message en français qui dit quoi faire), 2 commande mal tapée.
Python du système, sans ROS : seuls docker, ssh, scp, tar et gzip sont appelés.
"""
import argparse
import datetime
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

DOSSIER = Path(__file__).resolve().parent          # ~/robot-g1/docker
RACINE = DOSSIER.parent                             # ~/robot-g1
sys.path.insert(0, str(DOSSIER))
sys.dont_write_bytecode = True       # pas de __pycache__ dans docker/
import reseau  # noqa: E402  (module voisin, sans dépendance)

IMAGE = 'g1-jetson'
BASE = 'ros:humble-ros-base-jammy'     # image officielle multi-architecture (section 10.2)
NOM_ROBOT = 'g1-jetson'
NOM_LOCAL = 'g1-jetson-local'
HOTE_DEFAUT = 'unitree@192.168.123.164'
ARCHS = ('arm64', 'amd64')
ETIQUETTE = 'fr.robot-g1.image=g1-jetson'
CLE_EMPREINTE = 'fr.robot-g1.empreinte'

# Lancement du conteneur (fixé par le contrat, section 10.2)
ARRET_S = 20                    # --stop-timeout : docker stop attend 20 s avant SIGKILL
CPUS = '4'
MEMOIRE = '4g'
JOURNAL_DOCKER = ['--log-opt', 'max-size=20m', '--log-opt', 'max-file=5']  # le Jetson a peu de place
DELAI_DEMARRAGE_S = 30
GARDE_DEMARRAGE_S = 3.0         # après la ligne de démarrage, le conteneur doit encore tourner
LIGNE_DEMARRAGE = 'g1-jetson : domaine'

# Fichiers de l'image (le contexte de construction n'est jamais le dépôt entier)
FICHIERS_DOCKER = ['demarrer.sh', 'env.sh', 'reseau.py', 'presence.py', 'cyclonedds.xml.modele']
UNITREE_API = RACINE / 'third_party' / 'unitree_ros2' / 'cyclonedds_ws' / 'src' / 'unitree' / 'unitree_api'
UNITREE_HG = UNITREE_API.parent / 'unitree_hg'          # vague 4 : rt/arm_sdk et /lowstate (pilotage)
PAQUETS_WS = ['g1_nav', 'g1_bridge', 'g1_pilotage', 'g1_equipe']   # g1_equipe : à l'assemblage
# Pilotage (vague 4, section 11.5 du plan) : nœud lancé dans le conteneur avec G1_PILOTAGE=1 (défaut
# avec le robot), joint par l'Atelier sur le Wi-Fi avec un jeton partagé
FICHIER_JETON = RACINE / 'opt' / 'jetson' / 'jeton_pilotage'
PORT_PILOTAGE = '8010'
PYTHON_ATELIER = ['atelier/__init__.py', 'atelier/lieu', 'atelier/scan/__init__.py',
                  'atelier/scan/slam_client.py',
                  'atelier/equipe']     # chatbot d'exemple et relais (nœuds de g1_equipe), sans ROS
IGNORES = shutil.ignore_patterns('__pycache__', '*.pyc', '.pytest_cache', 'test', 'tests',
                                 '*.egg-info', '.gitkeep')
DOSSIER_ARCHIVES = RACINE / 'opt' / 'jetson'

# Côté Jetson (chemins relatifs au dossier personnel de unitree)
LIEUX_JETSON = 'robot-g1/lieux'
JOURNAUX_JETSON = 'robot-g1/journaux/jetson'
ARCHIVES_JETSON = 'robot-g1/opt/jetson'
SUJETS_ROBOT = ['/state_estimator/odom_pelvis', '/lf/sportmodestate']
PLACE_MIN_GO = 4.0              # archive (0,45 Go) + image décompressée (1,5 Go) + journaux, avec de la marge
MEMOIRE_MIN_GO = 4.0            # --memory 4g
MOTIF_ID = re.compile(r'^[a-z0-9][a-z0-9_-]{0,39}$')

# Messages d'argparse les plus courants, en français
TRADUCTIONS = [('the following arguments are required:', 'il manque :'),
               ('invalid choice:', 'choix inconnu :'), ('choose from', 'possibles :'),
               ('unrecognized arguments:', 'arguments inconnus :'),
               ('expected one argument', 'il faut une valeur'),
               ('not allowed with argument', 'impossible avec')]


class Erreur(Exception):
    """Échec qui arrête la commande (code 1) ; le message dit à l'utilisateur quoi faire."""


class Analyseur(argparse.ArgumentParser):
    """ArgumentParser qui parle français : aide, titres et messages d'erreur."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, add_help=False, **kwargs)
        self._positionals.title = 'arguments'
        self._optionals.title = 'options'
        self.add_argument('-h', '--help', action='help', help='affiche cette aide et quitte')

    def error(self, message):
        for anglais, francais in TRADUCTIONS:
            message = message.replace(anglais, francais)
        self.print_usage(sys.stderr)
        self.exit(2, f'erreur : {message}\nAide : {self.prog} --help\n')


def dire(texte=''):
    print(texte, flush=True)


# --- Commandes affichées et lancées --------------------------------------------------------

class Brut(str):
    """Morceau de commande à passer tel quel au shell du Jetson (contient $HOME ou $(id -u))."""


def texte_commande(cmd):
    """Une commande (liste) écrite comme dans un terminal ; les Brut ne sont pas protégés."""
    return ' '.join(m if isinstance(m, Brut) else shlex.quote(str(m)) for m in cmd)


def hote_jetson():
    return os.environ.get('G1_JETSON') or HOTE_DEFAUT


def options_ssh():
    # BatchMode : jamais de mot de passe demandé au milieu d'une commande (clé ssh obligatoire)
    return ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5', '-o', 'ServerAliveInterval=5',
            '-o', 'ServerAliveCountMax=3']


def commande_ssh(script, tty=False):
    """ssh vers le Jetson, qui lance « script » (texte du shell distant)."""
    return ['ssh'] + options_ssh() + (['-t'] if tty else []) + [hote_jetson(), script]


class Executeur:
    """Lance les commandes, ou les affiche seulement (--dry-run, « à blanc »)."""

    def __init__(self, a_blanc=False):
        self.a_blanc = a_blanc
        self.affichees = []

    def montrer(self, texte, entree=None):
        self.affichees.append(texte)
        dire(f'  $ {texte}')
        if entree:
            for ligne in entree.rstrip('\n').splitlines():
                dire(f'  | {ligne}')

    def lancer(self, cmd, capturer=True, entree=None, delai=None, toujours=False):
        """subprocess.run ; à blanc, affiche la commande et renvoie un résultat vide (code 0).

        toujours=True : lancée même à blanc (commandes locales qui ne changent rien).
        """
        if self.a_blanc and not toujours:
            self.montrer(texte_commande(cmd), entree)
            return subprocess.CompletedProcess(cmd, 0, '', '')
        try:
            return subprocess.run(cmd, capture_output=capturer, text=True, input=entree,
                                  timeout=delai)
        except FileNotFoundError:
            raise Erreur(f'programme {cmd[0]} introuvable : installez-le') from None
        except subprocess.TimeoutExpired:
            raise Erreur(f'« {texte_commande(cmd)[:120]} » ne répond pas en {delai:.0f} s') from None

    def interactif(self, cmd):
        """Commande qui garde le terminal (journal -f, shell) ; renvoie son code."""
        if self.a_blanc:
            self.montrer(texte_commande(cmd))
            return 0
        try:
            return subprocess.call(cmd)
        except KeyboardInterrupt:
            return 0


def refuser_robot_si_essai(executeur):
    """Aucune commande vers le Jetson pendant les tests (G1_SLAM_FAUX=1), sauf à blanc."""
    if os.environ.get('G1_SLAM_FAUX') == '1' and not executeur.a_blanc:
        raise Erreur('G1_SLAM_FAUX=1 (essais sans robot) : aucune commande n\'est envoyée au '
                     'Jetson. Utilisez --dry-run pour voir ce qui serait lancé, ou --local pour '
                     'le conteneur du PC')


class Cible:
    """Où tourne Docker : sur le PC (local) ou sur le Jetson (par ssh)."""

    def __init__(self, local, executeur):
        self.local = local
        self.executeur = executeur
        if not local:
            refuser_robot_si_essai(executeur)

    @property
    def nom_hote(self):
        return 'le PC' if self.local else f'le Jetson ({hote_jetson()})'

    def docker(self, *args, tty=False):
        if self.local:
            return ['docker', *args]
        return commande_ssh(texte_commande(['docker', *args]), tty=tty)

    def lancer_docker(self, *args, delai=60, toujours=False):
        return self.executeur.lancer(self.docker(*args), delai=delai, toujours=toujours)

    def ssh_script(self, script, delai=60):
        """Script shell lancé sur le Jetson par « bash -s » (texte passé sur l'entrée)."""
        return self.executeur.lancer(commande_ssh('bash -s'), entree=script, delai=delai)


def verifier_ssh(cible):
    """Le Jetson répond-il par ssh, avec une clé ? Sinon, dit quoi faire."""
    if cible.local or cible.executeur.a_blanc:
        return
    r = cible.executeur.lancer(commande_ssh('true'), delai=20)
    if r.returncode != 0:
        message = (r.stderr or '').strip().splitlines()
        detail = message[-1] if message else f'code {r.returncode}'
        raise Erreur(
            f'le Jetson ne répond pas par ssh ({hote_jetson()} : {detail}). Vérifiez le câble et '
            '« source ~/robot-g1/setup/robot.sh » ; la première fois, installez la clé : '
            f'ssh-copy-id {hote_jetson()} (mot de passe 123)')


# --- Le lieu --------------------------------------------------------------------------------

def dossier_lieux():
    """$ATELIER_LIEUX, sinon ~/robot-g1/lieux (comme atelier.dossier_lieux)."""
    return Path(os.environ.get('ATELIER_LIEUX') or RACINE / 'lieux').expanduser()


def resoudre_lieu(texte, etage=None):
    """(dossier du lieu, id) depuis --lieu (id ou chemin) ; vérifie lieu.yaml et la carte."""
    texte = str(texte).strip()
    dossier = dossier_lieux() / texte if MOTIF_ID.match(texte) else Path(texte).expanduser().resolve()
    if not (dossier / 'lieu.yaml').is_file():
        raise Erreur(f'lieu {dossier} introuvable (pas de lieu.yaml) : vérifiez --lieu '
                     '(un id de ~/robot-g1/lieux, ou un chemin)')
    ident = dossier.name
    if not MOTIF_ID.match(ident):
        raise Erreur(f'le dossier du lieu « {ident} » n\'a pas la forme d\'un id (minuscules, '
                     'chiffres, « _ » et « - ») : le conteneur ne pourrait pas le trouver. '
                     'Renommez-le, ou copiez-le avec un id')
    if etage is not None:
        if not MOTIF_ID.match(etage):
            raise Erreur(f'étage « {etage} » : il faut l\'id d\'un étage du lieu (ex. rdc)')
        carte = dossier / 'cartes' / f'{etage}.yaml'
        if not carte.is_file():
            raise Erreur(f'pas de carte {carte} : fabriquez-la d\'abord avec '
                         f'g1-monde generer --lieu {texte} --etage {etage} (ou un scan adopté)')
    return dossier, ident


# --- construire ----------------------------------------------------------------------------

def arch_hote():
    machine = platform.machine().lower()
    return {'x86_64': 'amd64', 'amd64': 'amd64', 'aarch64': 'arm64', 'arm64': 'arm64'}.get(machine, machine)


def emulation_prete(arch):
    """True si l'architecture tourne ici : la même que le PC, ou qemu enregistré dans binfmt."""
    if arch == arch_hote():
        return True
    nom = {'arm64': 'qemu-aarch64', 'amd64': 'qemu-x86_64'}[arch]
    try:
        return Path(f'/proc/sys/fs/binfmt_misc/{nom}').read_text().startswith('enabled')
    except OSError:
        return False


def paquets_ws(racine=RACINE):
    """{paquet: dossier} des paquets de l'image présents dans ws/src (g1_nav, g1_bridge)."""
    return {p: racine / 'ws' / 'src' / p for p in PAQUETS_WS
            if (racine / 'ws' / 'src' / p / 'package.xml').is_file()}


def assembler_contexte(destination, racine=RACINE, incomplet=False):
    """Copie dans « destination » ce que l'image contient. Renvoie la liste des paquets copiés."""
    destination = Path(destination)
    (destination / 'docker').mkdir(parents=True)
    shutil.copy2(racine / 'docker' / 'Dockerfile', destination / 'Dockerfile')
    for nom in FICHIERS_DOCKER:
        shutil.copy2(racine / 'docker' / nom, destination / 'docker' / nom)
    source_api = racine / UNITREE_API.relative_to(RACINE)
    if not (source_api / 'package.xml').is_file():
        raise Erreur(f'messages Unitree introuvables ({source_api}) : relancez '
                     'setup/installer_utilisateur.sh (dépôt unitree_ros2)')
    shutil.copytree(source_api, destination / 'unitree_api', ignore=IGNORES)
    source_hg = racine / UNITREE_HG.relative_to(RACINE)
    if not (source_hg / 'package.xml').is_file():
        raise Erreur(f'messages du G1 introuvables ({source_hg}) : relancez '
                     'setup/installer_utilisateur.sh (dépôt unitree_ros2)')
    shutil.copytree(source_hg, destination / 'unitree_hg', ignore=IGNORES)
    for chemin in PYTHON_ATELIER:
        source = racine / chemin
        cible = destination / 'python' / chemin
        cible.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, cible, ignore=IGNORES)
        else:
            shutil.copy2(source, cible)
    trouves = paquets_ws(racine)
    manquants = [p for p in PAQUETS_WS if p not in trouves]
    if manquants and not incomplet:
        raise Erreur(f'paquet {", ".join(manquants)} absent de ws/src : l\'image doit contenir '
                     'g1_nav, g1_bridge et g1_pilotage. Attendez qu\'il soit écrit, ou --incomplet '
                     '(mise au point seulement : sans g1_bridge, le robot ne peut pas marcher)')
    (destination / 'ws').mkdir()
    for paquet, source in trouves.items():
        shutil.copytree(source, destination / 'ws' / paquet, ignore=IGNORES)
    return sorted(trouves)


def empreinte_contexte(dossier, base=''):
    """Empreinte (sha256, 16 caractères) des fichiers du contexte, sauf VERSION, et de l'image de base."""
    dossier = Path(dossier)
    h = hashlib.sha256(base.encode() + b'\0')
    for chemin in sorted(p for p in dossier.rglob('*') if p.is_file()):
        relatif = chemin.relative_to(dossier).as_posix()
        if relatif == 'VERSION':
            continue
        h.update(relatif.encode() + b'\0')
        h.update(oct(chemin.stat().st_mode & 0o111).encode() + b'\0')
        h.update(chemin.read_bytes() + b'\0')
    return h.hexdigest()[:16]


def commit_git(racine=RACINE):
    """« 3f2c1ab », avec « +modifié » si l'arbre a changé depuis ; « inconnu » sans Git."""
    try:
        commit = subprocess.run(['git', '-C', str(racine), 'rev-parse', '--short', 'HEAD'],
                                capture_output=True, text=True, timeout=10)
        if commit.returncode != 0:
            return 'inconnu'
        # --no-optional-locks : lecture seule, l'index n'est pas réécrit
        etat = subprocess.run(['git', '--no-optional-locks', '-C', str(racine), 'status',
                               '--porcelain', '--untracked-files=no'],
                              capture_output=True, text=True, timeout=30)
        return commit.stdout.strip() + ('+modifié' if etat.stdout.strip() else '')
    except (OSError, subprocess.TimeoutExpired):
        return 'inconnu'


def texte_version(arch, empreinte, paquets, commit, date=None):
    date = date or datetime.datetime.now().astimezone().isoformat(timespec='seconds')
    return (f'date={date}\ncommit={commit}\nempreinte={empreinte}\narch={arch}\n'
            f'image={IMAGE}:{arch}\npaquets={" ".join(["unitree_api", "unitree_hg"] + paquets)}\n')


def _descripteur_base(arch):
    """Descripteur (dict) de l'image de base pour cette architecture, ou None."""
    r = subprocess.run(['docker', 'image', 'inspect', '--platform', f'linux/{arch}', BASE,
                        '--format', '{{json .Descriptor}}'], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    try:
        descripteur = json.loads(r.stdout)
    except ValueError:
        return None
    return descripteur if isinstance(descripteur, dict) else None


def base_pour(arch, executeur):
    """Image de base de l'architecture, désignée par l'empreinte de son manifeste.

    Avec le magasin containerd (Docker 29 sur le PC), « ros:humble-ros-base-jammy » désigne les deux
    architectures, et le constructeur classique prenait celle du PC même avec --platform. Un Docker
    plus ancien (le Jetson) ne donne pas ce descripteur : le nom seul suffit, il n'y a qu'une
    architecture.
    """
    descripteur = _descripteur_base(arch)
    if descripteur is None:
        present = subprocess.run(['docker', 'image', 'inspect', BASE], capture_output=True).returncode == 0
        if present and arch == arch_hote():
            return BASE
        commande = ['docker', 'pull', '--platform', f'linux/{arch}', BASE]
        if executeur.a_blanc:
            executeur.montrer(texte_commande(commande))
            return BASE
        dire(f'téléchargement de l\'image de base {BASE} ({arch}) : quelques minutes')
        if subprocess.run(commande).returncode != 0:
            raise Erreur(f'téléchargement de {BASE} ({arch}) impossible : il faut Internet sur ce PC')
        descripteur = _descripteur_base(arch)
    plateforme = (descripteur or {}).get('platform') or {}
    empreinte = (descripteur or {}).get('digest', '')
    if empreinte.startswith('sha256:') and plateforme.get('architecture') == arch:
        return f'{BASE}@{empreinte}'
    return BASE


def commande_build(arch, contexte, empreinte, sans_cache=False, cpus=None, base=BASE):
    cmd = ['docker', 'build', '--platform', f'linux/{arch}', '-t', f'{IMAGE}:{arch}',
           '--build-arg', f'BASE={base}', '--build-arg', f'G1_EMPREINTE={empreinte}']
    if sans_cache:
        cmd.append('--no-cache')
    if cpus:
        cmd += ['--cpuset-cpus', cpus]
    return cmd + [str(contexte)]


def empreinte_image(cible, arch):
    """Empreinte notée dans l'image g1-jetson:<arch> de la cible, ou None si elle n'existe pas."""
    r = cible.lancer_docker('image', 'inspect', '-f', '{{index .Config.Labels "%s"}}' % CLE_EMPREINTE,
                            f'{IMAGE}:{arch}', delai=60, toujours=cible.local)
    if r.returncode != 0:
        return None
    return r.stdout.strip() or None


# Vérifications de l'image (critère 16) : paquets, RMW, Python de l'Atelier, architecture
SCRIPT_VERIFICATION_IMAGE = (
    'source /opt/g1/env.sh >/dev/null && '
    'echo "arch=$(uname -m)" && echo "rmw=$RMW_IMPLEMENTATION" && '
    'for p in g1_nav g1_bridge g1_pilotage unitree_api unitree_hg nav2_bt_navigator rmw_cyclonedds_cpp; do '
    'echo "paquet_$p=$(ros2 pkg prefix $p 2>/dev/null || echo absent)"; done && '
    'python3 -c "import atelier.lieu, atelier.scan.slam_client; print(\'python=ok\')" && '
    'python3 -c "import tornado, atelier.lieu.pilotage; print(\'pilotage=ok\')" && '
    'echo "version=$(tr \'\\n\' \' \' < /opt/g1/VERSION)"')


def verifier_image(executeur, arch, image=None):
    """Lance les vérifications dans l'image ; renvoie le dict des résultats (Erreur si problème)."""
    image = image or f'{IMAGE}:{arch}'
    cmd = ['docker', 'run', '--rm', '--platform', f'linux/{arch}', '--network', 'none',
           '--entrypoint', 'bash', image, '-c', SCRIPT_VERIFICATION_IMAGE]
    r = executeur.lancer(cmd, delai=300)
    if executeur.a_blanc:
        return {}
    resultats = dict(ligne.split('=', 1) for ligne in r.stdout.splitlines() if '=' in ligne)
    problemes = []
    attendue = {'amd64': 'x86_64', 'arm64': 'aarch64'}[arch]
    if resultats.get('arch') != attendue:
        problemes.append(f'architecture {resultats.get("arch")} au lieu de {attendue}')
    if resultats.get('rmw') != 'rmw_cyclonedds_cpp':
        problemes.append(f'RMW_IMPLEMENTATION={resultats.get("rmw")}')
    for paquet in ['g1_nav', 'unitree_api', 'nav2_bt_navigator', 'rmw_cyclonedds_cpp']:
        if resultats.get(f'paquet_{paquet}', 'absent') == 'absent':
            problemes.append(f'paquet {paquet} absent')
    if resultats.get('python') != 'ok':
        problemes.append('import atelier.lieu, atelier.scan.slam_client impossible')
    if 'paquet_g1_pilotage' in resultats and resultats['paquet_g1_pilotage'] != 'absent':
        # image de la vague 4 : le pilotage aussi (une image plus ancienne n'a pas ces lignes)
        if resultats.get('paquet_unitree_hg', 'absent') == 'absent':
            problemes.append('paquet unitree_hg absent (pilotage des bras)')
        if resultats.get('pilotage') != 'ok':
            problemes.append('import tornado, atelier.lieu.pilotage impossible (nœud pilotage)')
    if r.returncode != 0 or problemes:
        detail = '; '.join(problemes) or (r.stderr or '').strip()[-300:]
        raise Erreur(f'l\'image {image} ne passe pas ses vérifications : {detail}')
    return resultats


def taille_image(arch):
    r = subprocess.run(['docker', 'image', 'inspect', '-f', '{{.Size}}', f'{IMAGE}:{arch}'],
                       capture_output=True, text=True)
    try:
        return int(r.stdout.strip())
    except ValueError:
        return None


def preparer_contexte_seul(args):
    """--contexte DOSSIER : le contexte de construction, pour construire ailleurs (sur le Jetson)."""
    dossier = Path(args.contexte).expanduser().resolve()
    if dossier.exists() and any(dossier.iterdir()):
        raise Erreur(f'{dossier} existe et n\'est pas vide : donnez un dossier nouveau')
    if dossier.exists():
        dossier.rmdir()
    paquets = assembler_contexte(dossier, incomplet=args.incomplet)
    empreinte = empreinte_contexte(dossier, BASE)
    (dossier / 'VERSION').write_text(texte_version(args.arch, empreinte, paquets, commit_git()),
                                     encoding='utf-8')
    dire(f'contexte de construction de {IMAGE}:{args.arch} prêt dans {dossier} '
         f'({sum(f.stat().st_size for f in dossier.rglob("*") if f.is_file()) / 1e6:.1f} Mo).')
    dire('Pour construire sur une machine de cette architecture (le Jetson, avec Internet) :')
    dire(f'  docker build -t {IMAGE}:{args.arch} --build-arg G1_EMPREINTE={empreinte} {dossier.name}')
    return 0


def construire(args, executeur):
    arch = args.arch
    if args.contexte:
        return preparer_contexte_seul(args)
    if not emulation_prete(arch):
        raise Erreur(f'ce PC ne sait pas faire tourner des programmes {arch} : installez '
                     'l\'émulation (sudo apt install qemu-user-static binfmt-support), puis '
                     'recommencez')
    contexte = Path(tempfile.mkdtemp(prefix=f'g1_jetson_contexte_{arch}_'))
    try:
        paquets = assembler_contexte(contexte, incomplet=args.incomplet)
        if 'g1_bridge' not in paquets:
            dire('attention : g1_bridge absent de ws/src, image incomplète (pas de pont vers la marche)')
        base = base_pour(arch, executeur)
        empreinte = empreinte_contexte(contexte, base)
        dire(f'g1-jetson construire : image {IMAGE}:{arch}, paquets unitree_api {" ".join(paquets)}, '
             f'empreinte {empreinte}, base {base}')
        cible = Cible(local=True, executeur=executeur)
        existante = empreinte_image(cible, arch)
        if existante == empreinte and not args.sans_cache:
            dire(f'image {IMAGE}:{arch} déjà à jour (même empreinte) : elle est réutilisée')
            if not executeur.a_blanc:
                verifier_image(executeur, arch)
                dire('vérifications de l\'image : réussies')
            return 0
        (contexte / 'VERSION').write_text(texte_version(arch, empreinte, paquets, commit_git()),
                                          encoding='utf-8')
        cmd = commande_build(arch, contexte, empreinte, args.sans_cache,
                             os.environ.get('G1_JETSON_CPUS_CONSTRUCTION'), base)
        if executeur.a_blanc:
            executeur.montrer(texte_commande(cmd))
            executeur.montrer(texte_commande(['docker', 'run', '--rm', '--platform', f'linux/{arch}',
                                              '--network', 'none', '--entrypoint', 'bash',
                                              f'{IMAGE}:{arch}', '-c', '…vérifications…']))
            return 0
        if arch != arch_hote():
            dire(f'construction par émulation ({arch} sur {arch_hote()}) : 5 à 30 min la première '
                 'fois selon le PC et Internet (4 min sur le PC du projet), 1 à 2 min ensuite')
        journal = RACINE / 'journaux' / f'jetson_construire_{arch}.log'
        journal.parent.mkdir(parents=True, exist_ok=True)
        debut = time.monotonic()
        code = construire_avec_journal(cmd, journal)
        duree = time.monotonic() - debut
        if code != 0:
            raise Erreur(f'la construction a échoué (code {code}) après {duree / 60:.1f} min : '
                         f'voir {journal}. Sans Internet, les paquets apt ne peuvent pas être '
                         'téléchargés')
        # Les anciennes versions de l'image, devenues sans étiquette, sont effacées
        subprocess.run(['docker', 'image', 'prune', '-f', '--filter', f'label={ETIQUETTE}'],
                       capture_output=True, text=True)
        taille = taille_image(arch)
        dire(f'image {IMAGE}:{arch} construite en {duree / 60:.1f} min'
             + (f', {taille / 1e9:.2f} Go' if taille else '') + f' (journal : {journal})')
        verifier_image(executeur, arch)
        dire('vérifications de l\'image : réussies (architecture, paquets, RMW, Python)')
        return 0
    finally:
        shutil.rmtree(contexte, ignore_errors=True)


def construire_avec_journal(cmd, journal):
    """docker build, sortie à l'écran et dans le journal ; renvoie le code."""
    with open(journal, 'w', encoding='utf-8') as sortie:
        sortie.write(f'$ {texte_commande(cmd)}\n')
        processus = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, errors='replace')
        try:
            for ligne in processus.stdout:
                sortie.write(ligne)
                sortie.flush()
                if ligne.startswith(('Step ', 'Successfully', ' ---> Running', 'ERROR', 'error')) \
                        or 'Setting up ros-humble-navigation2' in ligne or 'Finished <<<' in ligne:
                    dire('  ' + ligne.rstrip())
        except KeyboardInterrupt:
            processus.terminate()
            raise
        return processus.wait()


# --- envoyer -------------------------------------------------------------------------------

def chemin_archive(arch='arm64'):
    return DOSSIER_ARCHIVES / f'{IMAGE}_{arch}.tar.gz'


def commandes_envoi(archive):
    """Commandes de l'envoi, dans l'ordre : (texte, liste ou None pour un tube)."""
    distante = f'{ARCHIVES_JETSON}/{archive.name}'
    return {
        'save': f'docker save {IMAGE}:arm64 | gzip -1 > {shlex.quote(str(archive))}',
        'mkdir': commande_ssh(f'mkdir -p {ARCHIVES_JETSON} {LIEUX_JETSON} {JOURNAUX_JETSON}'),
        'scp': ['scp'] + options_ssh() + [str(archive), f'{hote_jetson()}:{distante}'],
        'load': commande_ssh(f'gunzip -c {distante} | docker load && rm -f {distante}'),
    }


def envoyer(args, executeur):
    cible = Cible(local=False, executeur=executeur)
    locale = Cible(local=True, executeur=executeur)
    empreinte = empreinte_image(locale, 'arm64')
    if empreinte is None:
        if not executeur.a_blanc:
            raise Erreur(f'pas d\'image {IMAGE}:arm64 sur ce PC : g1-jetson construire')
        dire(f'attention : pas d\'image {IMAGE}:arm64 sur ce PC (à construire d\'abord)')
    archive = chemin_archive()
    cmds = commandes_envoi(archive)
    verifier_ssh(cible)
    marque = archive.with_name(archive.name + '.empreinte')
    a_jour = archive.is_file() and marque.is_file() and marque.read_text().strip() == empreinte
    if executeur.a_blanc:
        dire('1/4 archive de l\'image')
        executeur.montrer(cmds['save'])
    elif a_jour:
        dire(f'archive {archive} déjà à jour : elle est réutilisée')
    else:
        dire(f'1/4 archive de l\'image : {archive} (quelques minutes)')
        DOSSIER_ARCHIVES.mkdir(parents=True, exist_ok=True)
        temporaire = archive.with_name(archive.name + '.tmp')
        with open(temporaire, 'wb') as fichier:
            save = subprocess.Popen(['docker', 'save', f'{IMAGE}:arm64'], stdout=subprocess.PIPE)
            gzip = subprocess.run(['gzip', '-1'], stdin=save.stdout, stdout=fichier)
            save.stdout.close()
            if save.wait() != 0 or gzip.returncode != 0:
                temporaire.unlink(missing_ok=True)
                raise Erreur('docker save | gzip a échoué : place libre sur le PC ?')
        temporaire.replace(archive)
        marque.write_text(empreinte + '\n')
    taille = archive.stat().st_size if archive.is_file() else 0
    if not executeur.a_blanc:
        place = place_jetson(cible)
        besoin = 4.5 * taille
        if place is not None and place < besoin:
            raise Erreur(f'le Jetson n\'a que {place / 1e9:.1f} Go libres, il en faut environ '
                         f'{besoin / 1e9:.1f} (archive et image). Faites de la place : '
                         'docker image prune, anciens fichiers')
    dire('2/4 dossiers sur le Jetson')
    r = executeur.lancer(cmds['mkdir'], delai=30)
    if r.returncode != 0:
        raise Erreur(f'création des dossiers sur le Jetson impossible : {r.stderr.strip()}')
    dire(f'3/4 copie de l\'archive ({taille / 1e9:.2f} Go) par scp : une minute environ au câble'
         if taille else '3/4 copie de l\'archive par scp')
    r = executeur.lancer(cmds['scp'], capturer=False, delai=3600)
    if r.returncode != 0:
        raise Erreur('la copie par scp a échoué : câble, place libre sur le Jetson ?')
    dire('4/4 docker load sur le Jetson (une à quelques minutes)')
    r = executeur.lancer(cmds['load'], capturer=False, delai=3600)
    if r.returncode != 0:
        raise Erreur('docker load a échoué sur le Jetson : voir le message ci-dessus. Plan B : '
                     'docs/jetson.md, « construire sur le Jetson »')
    if executeur.a_blanc:
        return 0
    distante = empreinte_image(cible, 'arm64')
    if distante != empreinte:
        raise Erreur(f'l\'image du Jetson ({distante}) n\'est pas celle du PC ({empreinte})')
    dire(f'image {IMAGE}:arm64 chargée sur le Jetson (empreinte {empreinte}). '
         'Ensuite : g1-jetson demarrer --lieu L --etage E')
    return 0


def place_jetson(cible):
    """Octets libres dans le dossier personnel du Jetson (None si inconnu)."""
    r = cible.executeur.lancer(commande_ssh("df -Pk \"$HOME\" | awk 'NR==2 {print $4}'"), delai=30)
    try:
        return int(r.stdout.strip()) * 1024
    except ValueError:
        return None


# --- lieu ----------------------------------------------------------------------------------

def commandes_lieu(dossier, ident):
    """Copie du lieu sur le Jetson : tar local (sans scans/) | ssh qui remplace l'ancien dossier."""
    tar = ['tar', '-C', str(dossier.parent), '--exclude', f'{ident}/scans', '-czf', '-', ident]
    nouveau = f'.{ident}.nouveau'
    script = (f'set -e; mkdir -p {LIEUX_JETSON}; cd {LIEUX_JETSON}; rm -rf {nouveau}; '
              f'mkdir {nouveau}; tar -xzf - -C {nouveau}; rm -rf {ident}; mv {nouveau}/{ident} {ident}; '
              f'rmdir {nouveau}')
    return tar, commande_ssh(script)


def copier_lieu(executeur, dossier, ident):
    tar, ssh = commandes_lieu(dossier, ident)
    if executeur.a_blanc:
        executeur.montrer(f'{texte_commande(tar)} | {texte_commande(ssh)}')
        return
    emballage = subprocess.Popen(tar, stdout=subprocess.PIPE)
    r = subprocess.run(ssh, stdin=emballage.stdout, capture_output=True, text=True, timeout=600)
    emballage.stdout.close()
    if emballage.wait() != 0 or r.returncode != 0:
        raise Erreur(f'copie du lieu {ident} sur le Jetson impossible : {r.stderr.strip()}')
    dire(f'lieu {ident} copié dans ~/{LIEUX_JETSON}/{ident} du Jetson (sans scans/)')


def lieu(args, executeur):
    cible = Cible(local=False, executeur=executeur)
    dossier, ident = resoudre_lieu(args.lieu)
    verifier_ssh(cible)
    copier_lieu(executeur, dossier, ident)
    return 0


# --- demarrer, arreter, etat, journal, shell -----------------------------------------------

def arch_conteneur(local):
    """arm64 sur le robot ; sur le PC, celle du PC, ou G1_JETSON_ARCH (image du robot par émulation)."""
    if not local:
        return 'arm64'
    arch = os.environ.get('G1_JETSON_ARCH') or arch_hote()
    if arch not in ARCHS:
        raise Erreur(f'G1_JETSON_ARCH={arch} : arm64 ou amd64')
    if not emulation_prete(arch):
        raise Erreur(f'ce PC ne fait pas tourner l\'architecture {arch} : installez qemu-user-static')
    return arch


def nom_conteneur(local):
    return (os.environ.get('G1_JETSON_NOM') or NOM_LOCAL) if local else NOM_ROBOT


def arguments_run(nom, image, utilisateur, lieux, journaux, environnement, runtime=None):
    """docker run du contrat (section 10.2) : réseau de l'hôte, pas de redémarrage, lieux en lecture seule.

    runtime : G1_JETSON_RUNTIME (ex. runc), si le runtime par défaut du Jetson (nvidia ?) gêne.
    """
    cmd = ['docker', 'run', '-d', '--name', nom, '--network', 'host', '--init', '--restart', 'no',
           '--stop-timeout', str(ARRET_S), '--user', utilisateur, '--cpus', CPUS, '--memory', MEMOIRE]
    if runtime:
        if not re.fullmatch(r'[a-z][a-z0-9_.-]{0,30}', runtime):
            raise Erreur(f'G1_JETSON_RUNTIME={runtime} : un nom de runtime Docker (ex. runc)')
        cmd += ['--runtime', runtime]
    cmd += JOURNAL_DOCKER
    for cle, valeur in environnement:
        cmd += ['-e', f'{cle}={valeur}']
    cmd += ['-v', lieux, '-v', journaux, image]
    return cmd


def environnement_conteneur(args, local, ident):
    """Variables du conteneur, dans l'ordre du contrat ; puis celles transmises du terminal."""
    domaine = os.environ.get('ROS_DOMAIN_ID', '0') if local else '0'
    if not re.fullmatch(r'\d{1,3}', domaine) or int(domaine) > 232:
        raise Erreur(f'ROS_DOMAIN_ID={domaine} : il faut un nombre de 0 à 232')
    interfaces = os.environ.get('G1_INTERFACES') or ('defaut' if local else 'auto')
    env = [('ROS_DOMAIN_ID', domaine), ('G1_INTERFACES', interfaces)]
    if args.veille:
        env.append(('G1_LANCEMENT', 'veille'))
    else:
        env += [('G1_LIEU', ident), ('G1_ETAGE', args.etage), ('G1_LANCEMENT', 'navigation')]
    if args.localisation:
        env.append(('G1_LOCALISATION', args.localisation))
    if args.wifi:
        reseau._noms(args.wifi, '--wifi')
        env.append(('G1_WIFI', args.wifi))
    if args.pair:
        env.append(('G1_PAIRS', ','.join(reseau.lire_pairs(','.join(args.pair)))))
    simu = os.environ.get('G1_SIMU')
    if simu:
        if simu not in ('true', 'false'):
            raise Erreur(f'G1_SIMU={simu} : true ou false')
        env.append(('G1_SIMU', simu))
    vitesse = (getattr(args, 'vitesse_max', None) or os.environ.get('G1_VITESSE_MAX') or '').strip()
    if vitesse:             # navigation (pont) et pilotage (joystick, pas des chorégraphies), même en veille
        env.append(('G1_VITESSE_MAX', lire_vitesse_max(vitesse)))
    if os.environ.get('G1_CYCLONEDDS_URI'):
        env.append(('G1_CYCLONEDDS_URI', os.environ['G1_CYCLONEDDS_URI']))
    env += environnement_pilotage(local)
    return env


def environnement_pilotage(local):
    """Variables du nœud pilotage (vague 4) : G1_PILOTAGE (1 par défaut avec le robot, 0 sur le PC),
    G1_PILOTAGE_PORT et le jeton G1_PILOTAGE_JETON (exigé sur le Wi-Fi : sans lui, le nœud n'accepte
    que le Jetson lui-même)."""
    pilotage = os.environ.get('G1_PILOTAGE') or ('0' if local else '1')
    if pilotage not in ('0', '1'):
        raise Erreur(f'G1_PILOTAGE={pilotage} : 1 (nœud pilotage lancé dans le conteneur) ou 0')
    env = [('G1_PILOTAGE', pilotage)]
    if pilotage == '0':
        return env
    port = os.environ.get('G1_PILOTAGE_PORT') or PORT_PILOTAGE
    if not re.fullmatch(r'\d{4,5}', port) or not 1024 <= int(port) <= 65535:
        raise Erreur(f'G1_PILOTAGE_PORT={port} : un port de 1024 à 65535 (8010 par défaut)')
    env.append(('G1_PILOTAGE_PORT', port))
    jeton = lire_jeton_pilotage()
    if jeton:
        env.append(('G1_PILOTAGE_JETON', jeton))      # sans jeton : le nœud n'accepte que 127.0.0.1
    return env


def lire_jeton_pilotage():
    """Jeton partagé du pilotage : $G1_PILOTAGE_JETON, sinon le fichier opt/jetson/jeton_pilotage."""
    if os.environ.get('G1_PILOTAGE_JETON'):
        return os.environ['G1_PILOTAGE_JETON'].strip()
    fichier = Path(os.environ.get('G1_PILOTAGE_JETON_FICHIER') or FICHIER_JETON)
    try:
        return fichier.read_text(encoding='utf-8').strip()
    except OSError:
        return ''


def creer_jeton_pilotage(executeur):
    """Crée le jeton du pilotage (robot) s'il n'existe pas ; l'Atelier le relit dans le même fichier."""
    if lire_jeton_pilotage() or (os.environ.get('G1_PILOTAGE') or '1') == '0':
        return
    fichier = Path(os.environ.get('G1_PILOTAGE_JETON_FICHIER') or FICHIER_JETON)
    if executeur.a_blanc:
        executeur.montrer(f'(jeton du pilotage créé dans {fichier})')
        os.environ['G1_PILOTAGE_JETON'] = 'jeton-du-pilotage'
        return
    import secrets
    fichier.parent.mkdir(parents=True, exist_ok=True)
    fichier.write_text(secrets.token_urlsafe(24) + '\n', encoding='utf-8')
    fichier.chmod(0o600)
    dire(f'jeton du pilotage créé : {fichier} (l\'Atelier le lit pour joindre le nœud pilotage par le Wi-Fi)')


def lire_vitesse_max(texte):
    """--vitesse-max ou G1_VITESSE_MAX : vitesse en m/s, plus grande que 0 et au plus 0,4."""
    try:
        vitesse = float(texte.replace(',', '.'))
    except ValueError:
        vitesse = float('nan')
    if not 0.0 < vitesse <= 0.4:
        raise Erreur(f'vitesse maximale « {texte} » : il faut une vitesse en m/s, plus grande que 0 et au '
                     'plus 0.4 (plafond du pont), par exemple 0.2')
    return f'{vitesse:g}'


def etat_docker(cible, nom):
    """{'status', 'code', 'image', 'debut', 'env'} du conteneur, ou None s'il n'existe pas."""
    r = cible.lancer_docker('inspect', nom, delai=30, toujours=cible.local)
    if r.returncode != 0 or not r.stdout.strip():
        return None
    try:
        infos = json.loads(r.stdout)[0]
    except (ValueError, IndexError):
        return None
    env = dict(e.split('=', 1) for e in infos.get('Config', {}).get('Env', []) if '=' in e)
    etat = infos.get('State', {})
    return {'status': etat.get('Status'), 'code': etat.get('ExitCode'),
            'image': infos.get('Config', {}).get('Image'), 'debut': etat.get('StartedAt'),
            'env': env}


def demarrer(args, executeur):
    local = args.local
    if not args.veille and (not args.lieu or not args.etage):
        raise Erreur('il faut --lieu et --etage (ou --veille, sans navigation)')
    if args.pair and not args.wifi:
        raise Erreur('--pair va avec --wifi IFACE (l\'interface Wi-Fi du Jetson)')
    cible = Cible(local=local, executeur=executeur)
    if not local:
        creer_jeton_pilotage(executeur)
    nom = nom_conteneur(local)
    arch = arch_conteneur(local)
    image = f'{IMAGE}:{arch}'
    ident = None
    if not args.veille:
        dossier, ident = resoudre_lieu(args.lieu, args.etage)
    env = environnement_conteneur(args, local, ident)
    if local:
        if ident is not None:
            lieux = f'{dossier.parent}:/lieux:ro'
        else:
            lieux = f'{dossier_lieux()}:/lieux:ro'
        dossier_journaux = RACINE / 'journaux' / 'jetson_local'
        if not executeur.a_blanc:
            dossier_journaux.mkdir(parents=True, exist_ok=True)
        journaux = f'{dossier_journaux}:/journaux'
        utilisateur = f'{os.getuid()}:{os.getgid()}'
    else:
        lieux = Brut(f'"$HOME/{LIEUX_JETSON}:/lieux:ro"')
        journaux = Brut(f'"$HOME/{JOURNAUX_JETSON}:/journaux"')
        utilisateur = Brut('"$(id -u):$(id -g)"')
    run = arguments_run(nom, image, utilisateur, lieux, journaux, env, os.environ.get('G1_JETSON_RUNTIME'))

    verifier_ssh(cible)
    if not executeur.a_blanc:
        existant = etat_docker(cible, nom)
        if existant and existant['status'] in ('running', 'restarting', 'paused'):
            e = existant['env']
            raise Erreur(f'le conteneur {nom} tourne déjà sur {cible.nom_hote} (lieu '
                         f'{e.get("G1_LIEU", "aucun")}, étage {e.get("G1_ETAGE", "-")}) : '
                         f'g1-jetson arreter{" --local" if local else ""}, puis recommencez')
        if empreinte_image(cible, arch) is None:
            conseil = (f'g1-jetson construire --arch {arch}' if local else
                       'g1-jetson construire, puis g1-jetson envoyer')
            raise Erreur(f'pas d\'image {image} sur {cible.nom_hote} : {conseil}')
        if existant:            # arrêté : on garde son journal jusqu'au démarrage suivant
            cible.lancer_docker('rm', '-f', nom, delai=60)
    if not local and ident is not None:
        copier_lieu(executeur, dossier, ident)
    if not local:
        r = executeur.lancer(commande_ssh(f'mkdir -p {JOURNAUX_JETSON} {LIEUX_JETSON}'), delai=30)
    if local:
        r = executeur.lancer(run, delai=120)
    else:
        r = executeur.lancer(commande_ssh(texte_commande(run)), delai=120)
    if executeur.a_blanc:
        return 0
    if r.returncode != 0:
        raise Erreur(f'docker run a échoué sur {cible.nom_hote} : {(r.stderr or "").strip()[-400:]}')
    return attendre_demarrage(cible, nom, args)


def attendre_demarrage(cible, nom, args):
    """Attend la ligne de démarrage (30 s au plus) ; code 1 si le conteneur s'arrête avant."""
    fin = time.monotonic() + DELAI_DEMARRAGE_S
    while time.monotonic() < fin:
        etat = etat_docker(cible, nom)
        journal = cible.lancer_docker('logs', nom, delai=30)    # tout : Nav2 écrit vite beaucoup
        texte = (journal.stdout or '') + (journal.stderr or '')
        if etat is None or etat['status'] not in ('running', 'created'):
            code = etat['code'] if etat else '?'
            # La dernière ligne est la plus utile (l'Atelier n'affiche que celle-là) : le refus du conteneur
            raise Erreur(f'le conteneur {nom} s\'est arrêté au démarrage (code {code}) ; journal complet : '
                         f'g1-jetson journal{" --local" if cible.local else ""}\n  '
                         + (dernieres_lignes(texte) or 'pas de message'))
        if LIGNE_DEMARRAGE in texte:
            ligne = [x for x in texte.splitlines() if LIGNE_DEMARRAGE in x][-1]
            # Encore quelques secondes : une erreur du lancement (carte illisible…) arrête tout tôt
            time.sleep(GARDE_DEMARRAGE_S)
            etat = etat_docker(cible, nom)
            if etat is None or etat['status'] != 'running':
                journal = cible.lancer_docker('logs', nom, delai=30)
                texte = (journal.stdout or '') + (journal.stderr or '')
                raise Erreur(f'le conteneur {nom} s\'est arrêté juste après son démarrage (code '
                             f'{etat["code"] if etat else "?"}) ; journal complet : '
                             f'g1-jetson journal{" --local" if cible.local else ""}\n  '
                             + (dernieres_lignes(texte) or 'pas de message'))
            dire(ligne)
            quoi = 'en veille' if args.veille else f'navigation sur {args.lieu}, étage {args.etage}'
            dire(f'conteneur {nom} démarré sur {cible.nom_hote} : {quoi}. '
                 f'Suivre : g1-jetson journal{" --local" if cible.local else ""} -f')
            return 0
        time.sleep(0.5)
    raise Erreur(f'le conteneur {nom} ne s\'est pas annoncé en {DELAI_DEMARRAGE_S} s : '
                 f'g1-jetson journal{" --local" if cible.local else ""}')


def dernieres_lignes(texte, n=6):
    """Les lignes utiles de la fin du journal ; la plus parlante en dernier (l'Atelier n'affiche que
    celle-là) : le refus du conteneur, ou l'erreur du lancement plutôt que « s'est arrêté seul »."""
    lignes = [x for x in texte.strip().splitlines() if x.strip()]
    motif = re.compile(r'g1-jetson :|g1_nav :|\[ERROR\]|[Ee]rreur')
    utiles = [x for x in lignes if motif.search(x)][-n:] or lignes[-n:]
    fins = [x for x in utiles if 's\'est arrêté seul' in x]
    utiles = fins + [x for x in utiles if x not in fins]
    return '\n  '.join(utiles)


def tester_local(args, executeur):
    """demarrer --local, puis lecture de /g1_jetson/etat : le conteneur tourne et parle DDS sur le PC."""
    args.local = True
    code = demarrer(args, executeur)
    if code != 0 or executeur.a_blanc:
        return code
    cible = Cible(local=True, executeur=executeur)
    nom = nom_conteneur(True)
    dernier, source = presence(cible, nom)
    if dernier is None:
        raise Erreur(f'le conteneur {nom} tourne, mais /g1_jetson/etat ne passe pas : g1-jetson journal --local')
    dire(f'/g1_jetson/etat ({source}) : {json.dumps(dernier, ensure_ascii=False)}')
    dire(f'Depuis ce terminal (domaine {os.environ.get("ROS_DOMAIN_ID", "0")}) : ros2 node list --no-daemon ; '
         'arrêter : g1-jetson arreter --local')
    return 0


def arreter(args, executeur):
    cible = Cible(local=args.local, executeur=executeur)
    nom = nom_conteneur(args.local)
    verifier_ssh(cible)
    if executeur.a_blanc:
        cible.lancer_docker('stop', '-t', str(ARRET_S), nom)
        cible.lancer_docker('rm', nom)
        return 0
    etat = etat_docker(cible, nom)
    if etat is None:
        dire(f'aucun conteneur {nom} sur {cible.nom_hote} : rien à arrêter')
        return 0
    debut = time.monotonic()
    if etat['status'] in ('running', 'restarting', 'paused', 'created'):
        dire(f'arrêt de {nom} sur {cible.nom_hote} (navigation arrêtée proprement, {ARRET_S} s au plus)')
        r = cible.lancer_docker('stop', '-t', str(ARRET_S), nom, delai=ARRET_S + 30)
        if r.returncode != 0:
            raise Erreur(f'docker stop a échoué : {r.stderr.strip()}')
    journal = cible.lancer_docker('logs', '--tail', '3', nom, delai=30)
    r = cible.lancer_docker('rm', '-f', nom, delai=60)
    if r.returncode != 0:
        raise Erreur(f'docker rm a échoué : {r.stderr.strip()}')
    fin = dernieres_lignes((journal.stdout or '') + (journal.stderr or ''), 2)
    dire(f'conteneur {nom} arrêté et retiré en {time.monotonic() - debut:.1f} s'
         + (f'\n  {fin}' if fin else ''))
    return 0


def presence(cible, nom):
    """Dernier /g1_jetson/etat (dict) lu dans le conteneur, et sa source ; (None, None) sinon."""
    script = ('source /opt/g1/env.sh >/dev/null 2>&1; '
              'python3 /opt/g1/presence.py --lire --delai 5 2>/dev/null')
    r = cible.lancer_docker('exec', nom, 'bash', '-c', script, delai=40)
    for ligne in reversed((r.stdout or '').strip().splitlines()):
        try:
            return json.loads(ligne), 'reçu par DDS'
        except ValueError:
            continue
    r = cible.lancer_docker('exec', nom, 'cat', '/tmp/g1_jetson_etat.json', delai=20)
    try:
        return json.loads(r.stdout), 'fichier du nœud (rien reçu par DDS en 5 s)'
    except ValueError:
        return None, None


def etat(args, executeur):
    cible = Cible(local=args.local, executeur=executeur)
    nom = nom_conteneur(args.local)
    verifier_ssh(cible)
    if executeur.a_blanc:
        cible.lancer_docker('inspect', nom)
        cible.lancer_docker('exec', nom, 'bash', '-c',
                            'source /opt/g1/env.sh; python3 /opt/g1/presence.py --lire --delai 5')
        return 0
    infos = etat_docker(cible, nom)
    en_marche = bool(infos and infos['status'] == 'running')
    dernier, source = presence(cible, nom) if en_marche else (None, None)
    env = infos['env'] if infos else {}
    bilan = {
        'nom': nom, 'hote': 'local' if args.local else hote_jetson(), 'existe': infos is not None,
        'en_marche': en_marche, 'statut': infos['status'] if infos else None,
        'code_sortie': infos['code'] if infos and not en_marche else None,
        'image': infos['image'] if infos else None, 'demarre': infos['debut'] if infos else None,
        'lancement': env.get('G1_LANCEMENT'), 'lieu': env.get('G1_LIEU'), 'etage': env.get('G1_ETAGE'),
        'domaine': env.get('ROS_DOMAIN_ID'),
        'interfaces': (dernier or {}).get('interfaces', env.get('G1_INTERFACES')),
        'presence': dernier, 'source_presence': source,
    }
    if args.json:
        print(json.dumps(bilan, ensure_ascii=False))
        return 0 if en_marche else 1
    if infos is None:
        dire(f'aucun conteneur {nom} sur {cible.nom_hote}')
        return 1
    dire(f'conteneur {nom} sur {cible.nom_hote} : {infos["status"]}'
         + ('' if en_marche else f' (code {infos["code"]})'))
    dire(f'  image {infos["image"]}, démarré {infos["debut"]}')
    dire(f'  lancement {env.get("G1_LANCEMENT")}, lieu {env.get("G1_LIEU", "aucun")}, '
         f'étage {env.get("G1_ETAGE", "-")}, domaine {env.get("ROS_DOMAIN_ID")}, '
         f'interfaces {bilan["interfaces"]}')
    if dernier:
        dire(f'  /g1_jetson/etat ({source}) : version {dernier.get("version")}, '
             f'{dernier.get("arch")}, depuis {dernier.get("depuis_s")} s')
    elif en_marche:
        dire('  /g1_jetson/etat : rien reçu (le nœud de présence démarre, ou DDS ne passe pas)')
    return 0 if en_marche else 1


def journal(args, executeur):
    cible = Cible(local=args.local, executeur=executeur)
    nom = nom_conteneur(args.local)
    verifier_ssh(cible)
    options = ['logs', '--tail', str(args.lignes)] + (['-f'] if args.suivre else [])
    return executeur.interactif(cible.docker(*options, nom, tty=args.suivre))


def shell(args, executeur):
    cible = Cible(local=args.local, executeur=executeur)
    nom = nom_conteneur(args.local)
    verifier_ssh(cible)
    if not executeur.a_blanc:
        infos = etat_docker(cible, nom)
        if not infos or infos['status'] != 'running':
            raise Erreur(f'le conteneur {nom} ne tourne pas sur {cible.nom_hote} : '
                         f'g1-jetson demarrer{" --local" if args.local else ""} d\'abord')
    return executeur.interactif(cible.docker('exec', '-it', nom, 'bash', '--rcfile',
                                             '/opt/g1/env.sh', '-i', tty=True))


# --- verifier ------------------------------------------------------------------------------

SCRIPT_VERIFIER = r'''
echo "arch=$(uname -m)"
echo "noyau=$(uname -r)"
echo "l4t=$(head -n 1 /etc/nv_tegra_release 2>/dev/null | cut -c1-60)"
echo "systeme=$(. /etc/os-release 2>/dev/null; echo "$PRETTY_NAME")"
echo "docker=$(docker version --format '{{.Server.Version}}' 2>/dev/null)"
echo "docker_ok=$(docker info >/dev/null 2>&1 && echo oui || echo non)"
echo "runtime=$(docker info --format '{{.DefaultRuntime}}' 2>/dev/null)"
echo "racine_docker=$(docker info --format '{{.DockerRootDir}}' 2>/dev/null)"
echo "place_ko=$(df -Pk "$HOME" | awk 'NR==2 {print $4}')"
racine=$(docker info --format '{{.DockerRootDir}}' 2>/dev/null); racine=${racine:-/var/lib/docker}
echo "place_docker_ko=$(df -Pk "$racine" 2>/dev/null | awk 'NR==2 {print $4}')"
echo "memoire_ko=$(awk '/MemAvailable/ {print $2}' /proc/meminfo)"
echo "memoire_totale_ko=$(awk '/MemTotal/ {print $2}' /proc/meminfo)"
echo "processeurs=$(nproc)"
echo "heure=$(date +%s.%N)"
echo "image=$(docker image inspect -f '{{index .Config.Labels "fr.robot-g1.empreinte"}}' g1-jetson:arm64 2>/dev/null)"
echo "conteneur=$(docker inspect -f '{{.State.Status}}' g1-jetson 2>/dev/null)"
echo "internet=$(timeout 5 bash -c 'exec 3<>/dev/tcp/registry-1.docker.io/443' 2>/dev/null && echo oui || echo non)"
echo "---ip"
ip -o -4 addr
'''


def lire_verification(texte):
    """(champs, sortie de ip) depuis la sortie de SCRIPT_VERIFIER."""
    avant, _, ip = texte.partition('---ip')
    champs = dict(x.split('=', 1) for x in avant.splitlines() if '=' in x)
    return champs, ip


def bilan_verification(champs, ip, heure_pc):
    """[(niveau, texte)] : niveau « ok », « probleme » ou « info »."""
    lignes = []

    def ko(nom):
        try:
            return int(champs.get(nom, '')) * 1024
        except ValueError:
            return None

    arch = champs.get('arch')
    lignes.append(('ok' if arch == 'aarch64' else 'probleme',
                   f'architecture {arch or "?"} (attendu : aarch64), noyau {champs.get("noyau", "?")}'))
    lignes.append(('info', f'système {champs.get("systeme") or "?"}, {champs.get("l4t") or "L4T ?"}'))
    if champs.get('docker_ok') == 'oui':
        lignes.append(('ok', f'Docker {champs.get("docker")} utilisable sans sudo, runtime par défaut '
                             f'{champs.get("runtime") or "?"}'))
    else:
        lignes.append(('probleme', 'Docker inutilisable sans sudo : sudo usermod -aG docker $USER '
                                   '(mot de passe 123), puis se reconnecter'))
    for nom, quoi in (('place_ko', 'dossier personnel'), ('place_docker_ko', 'dossier de Docker')):
        place = ko(nom)
        if place is None:
            lignes.append(('info', f'place libre ({quoi}) inconnue'))
        else:
            assez = place >= PLACE_MIN_GO * 1e9
            lignes.append(('ok' if assez else 'probleme',
                           f'place libre ({quoi}) : {place / 1e9:.1f} Go (il en faut {PLACE_MIN_GO:.0f})'))
    memoire = ko('memoire_ko')
    if memoire is not None:
        totale = ko('memoire_totale_ko') or 0
        lignes.append(('ok' if memoire >= MEMOIRE_MIN_GO * 1e9 else 'probleme',
                       f'mémoire disponible : {memoire / 1e9:.1f} Go sur {totale / 1e9:.1f} '
                       f'(le conteneur en prend {MEMOIRE_MIN_GO:.0f} au plus), '
                       f'{champs.get("processeurs", "?")} processeurs'))
    adresses = reseau.lire_adresses(ip)
    robot = reseau.interfaces_robot(adresses)
    if robot:
        detail = ', '.join(f'{n} ({a})' for n, a in adresses if n in robot)
        lignes.append(('ok', f'réseau interne du robot : {detail}'))
    else:
        vues = ', '.join(f'{n} ({a})' for n, a in adresses if n != 'lo') or 'aucune'
        lignes.append(('probleme', f'aucune interface en 192.168.123.x (vues : {vues})'))
    autres = [f'{n} ({a})' for n, a in adresses if n != 'lo' and n not in robot]
    if autres:
        lignes.append(('info', f'autres interfaces : {", ".join(autres)}'))
    try:
        ecart = float(champs['heure']) - heure_pc
        lignes.append(('info' if abs(ecart) < 1.0 else 'probleme',
                       f'horloge du Jetson : {ecart:+.2f} s par rapport au PC (temps de ssh compris)'))
    except (KeyError, ValueError):
        pass
    lignes.append(('info', f'Internet depuis le Jetson : {champs.get("internet", "?")} '
                           '(oui : on peut aussi construire l\'image sur le Jetson)'))
    image = champs.get('image')
    lignes.append(('ok' if image else 'info',
                   f'image g1-jetson:arm64 : {"empreinte " + image if image else "absente (g1-jetson envoyer)"}'))
    if champs.get('conteneur'):
        lignes.append(('info', f'conteneur g1-jetson : {champs["conteneur"]}'))
    return lignes


def commande_verification_robot():
    """Conteneur jetable qui doit voir les sujets du robot (domaine 0, interface 192.168.123.x)."""
    run = ['docker', 'run', '--rm', '--name', 'g1-jetson-verification', '--network', 'host',
           '--init', '--user', Brut('"$(id -u):$(id -g)"'), '-e', 'ROS_DOMAIN_ID=0',
           '-e', 'G1_INTERFACES=auto', '-e', 'G1_LANCEMENT=commande', f'{IMAGE}:arm64',
           'bash', '-c', 'python3 /opt/g1/presence.py --sujets ' + ' '.join(SUJETS_ROBOT) +
           ' --delai 20 && ros2 interface show unitree_api/msg/Request > /dev/null '
           '&& echo "unitree_api=ok"']
    return commande_ssh(texte_commande(run))


def verifier(args, executeur):
    cible = Cible(local=False, executeur=executeur)
    verifier_ssh(cible)
    dire(f'Vérification du Jetson {hote_jetson()}')
    heure_pc = time.time()
    r = cible.ssh_script(SCRIPT_VERIFIER, delai=60)
    if executeur.a_blanc:
        executeur.lancer(commande_verification_robot(), delai=120)
        return 0
    if r.returncode != 0 and '---ip' not in r.stdout:
        raise Erreur(f'vérification impossible sur le Jetson : {r.stderr.strip()[-300:]}')
    champs, ip = lire_verification(r.stdout)
    lignes = bilan_verification(champs, ip, (heure_pc + time.time()) / 2)
    marques = {'ok': 'OK      ', 'probleme': 'PROBLÈME', 'info': 'info    '}
    for niveau, texte in lignes:
        dire(f'  {marques[niveau]} {texte}')
    problemes = sum(1 for niveau, _ in lignes if niveau == 'probleme')
    if champs.get('image') and champs.get('docker_ok') == 'oui':
        dire(f'Conteneur de vérification : il doit voir {" et ".join(SUJETS_ROBOT)} (20 s au plus)')
        r = executeur.lancer(commande_verification_robot(), delai=180)
        sortie = (r.stdout or '').strip().splitlines()
        bilan = None
        for ligne in sortie:
            try:
                bilan = json.loads(ligne)
            except ValueError:
                pass
        if r.returncode == 0 and bilan and not bilan['manquants']:
            types = ', '.join(f'{s} ({"/".join(t or [])})' for s, t in bilan['vus'].items())
            dire(f'  OK       sujets du robot vus depuis le conteneur Humble : {types} ; '
                 f'{bilan["nombre_de_sujets"]} sujets en tout ; type unitree_api/msg/Request connu')
        else:
            problemes += 1
            manquants = ', '.join(bilan['manquants']) if bilan else '?'
            dire(f'  PROBLÈME sujets du robot invisibles depuis le conteneur : {manquants}. '
                 'Robot allumé ? Bonne interface (G1_INTERFACES) ? '
                 + ((r.stderr or '').strip().splitlines() or [''])[-1])
    else:
        dire('  info     pas de conteneur de vérification (image absente ou Docker inutilisable)')
    if problemes:
        dire(f'{problemes} problème(s) : voir ci-dessus et docs/jetson.md')
        return 1
    dire('Jetson prêt.')
    return 0


# --- Ligne de commande ---------------------------------------------------------------------

def analyseur():
    principal = Analyseur(prog='g1-jetson', description='Conteneur ROS 2 Humble du Jetson du G1 '
                          '(Nav2, guide, relais, pont), section 10.2 du plan.',
                          epilog='Guide pas à pas : docs/jetson.md')
    sous = principal.add_subparsers(dest='commande', required=True, parser_class=Analyseur,
                                    metavar='COMMANDE')

    def ajouter(nom, aide, local=True):
        p = sous.add_parser(nom, help=aide, description=aide)
        p.add_argument('--dry-run', action='store_true',
                       help='affiche les commandes sans rien lancer (à blanc)')
        if local:
            p.add_argument('--local', action='store_true',
                           help='le conteneur du PC (essais), au lieu de celui du Jetson')
        return p

    p = ajouter('construire', 'construit l\'image g1-jetson:<arch>', local=False)
    p.add_argument('--arch', choices=ARCHS, default='arm64',
                   help='arm64 (Jetson, par émulation, défaut) ou amd64 (essais sur le PC)')
    p.add_argument('--sans-cache', action='store_true', help='tout reconstruire (docker build --no-cache)')
    p.add_argument('--incomplet', action='store_true',
                   help='mise au point : construit même si g1_nav ou g1_bridge manque dans ws/src')
    p.add_argument('--contexte', metavar='DOSSIER',
                   help='prépare seulement le contexte de construction dans DOSSIER (nouveau), pour '
                        'construire ailleurs, par exemple sur le Jetson (docs/jetson.md, plan B)')
    ajouter('envoyer', 'copie l\'image arm64 sur le Jetson (docker save, scp, docker load)', local=False)
    p = ajouter('lieu', 'copie un lieu (sans scans/) sur le Jetson', local=False)
    p.add_argument('--lieu', required=True, help='id du lieu (dossier de ~/robot-g1/lieux) ou chemin')
    p = ajouter('demarrer', 'lance le conteneur (navigation, ou veille)')
    p.add_argument('--lieu', help='id du lieu ou chemin (obligatoire sans --veille)')
    p.add_argument('--etage', help='id de l\'étage (obligatoire sans --veille)')
    p.add_argument('--localisation', choices=['unitree', 'amcl'],
                   help='unitree (relocalisation d\'Unitree, défaut) ou amcl (secours : notre carte et le LiDAR)')
    p.add_argument('--veille', action='store_true', help='sans navigation : le nœud de présence seul')
    p.add_argument('--wifi', metavar='IFACE', help='interface Wi-Fi du Jetson, pour joindre l\'Atelier sans câble')
    p.add_argument('--pair', metavar='IP', action='append',
                   help='adresse du PC de l\'Atelier sur le Wi-Fi (plusieurs --pair possibles)')
    p.add_argument('--vitesse-max', metavar='M_PAR_S',
                   help='premiers essais : vitesse maximale en m/s (ex. 0.2), les plafonds du pont '
                        'baissent d\'autant (défaut : $G1_VITESSE_MAX, sinon 0,4 / 0,25 / 0,6)')
    p = ajouter('tester-local', 'essai sur le PC : demarrer --local (image amd64, réseau de l\'hôte, lieu '
                'monté), puis lecture de /g1_jetson/etat', local=False)
    p.add_argument('--lieu', help='id du lieu ou chemin (obligatoire sans --veille)')
    p.add_argument('--etage', help='id de l\'étage (obligatoire sans --veille)')
    p.add_argument('--localisation', choices=['unitree', 'amcl'], help='unitree (défaut) ou amcl')
    p.add_argument('--veille', action='store_true', help='sans navigation : le nœud de présence seul')
    p.set_defaults(wifi=None, pair=None)
    ajouter('arreter', 'arrête proprement le conteneur, puis le retire')
    p = ajouter('etat', 'état du conteneur et dernier /g1_jetson/etat (code 0 s\'il tourne)')
    p.add_argument('--json', action='store_true', help='seulement le bilan en JSON')
    p = ajouter('journal', 'journal du conteneur (docker logs)')
    p.add_argument('-f', '--suivre', action='store_true', help='suit le journal (Ctrl+C pour quitter)')
    p.add_argument('--lignes', type=int, default=200, help='nombre de lignes (200 par défaut)')
    ajouter('shell', 'terminal dans le conteneur, avec ROS 2 chargé (exit pour sortir)')
    ajouter('verifier', 'vérifie le Jetson : Docker, place, mémoire, réseau, sujets du robot', local=False)
    return principal


ACTIONS = {'construire': construire, 'envoyer': envoyer, 'lieu': lieu, 'demarrer': demarrer,
           'tester-local': tester_local,
           'arreter': arreter, 'etat': etat, 'journal': journal, 'shell': shell, 'verifier': verifier}


def main(argv=None):
    args = analyseur().parse_args(argv)
    executeur = Executeur(a_blanc=args.dry_run)
    if args.dry_run:
        dire(f'(à blanc : rien n\'est lancé{"" if getattr(args, "local", False) else " ni envoyé au Jetson"})')
    try:
        return ACTIONS[args.commande](args, executeur)
    except Erreur as erreur:
        print(f'g1-jetson {args.commande} : {erreur}', file=sys.stderr)
        return 1
    except reseau.ErreurReseau as erreur:
        print(f'g1-jetson {args.commande} : {erreur}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(f'g1-jetson {args.commande} : interrompu', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
