"""Tests de la commande g1-jetson (docker/jetson.py), sans Docker, sans ssh et sans robot.

Lancement : .venv-projet/bin/python -m pytest docker/tests
Les commandes externes (docker, ssh, scp, tar) sont remplacées par de faux programmes qui notent
leurs appels : on vérifie ce qui serait lancé, et surtout que rien ne part vers le Jetson pendant
les essais (G1_SLAM_FAUX=1) ou à blanc (--dry-run).
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

DOSSIER = Path(__file__).resolve().parent.parent
RACINE = DOSSIER.parent
sys.path.insert(0, str(DOSSIER))
import jetson  # noqa: E402
import presence  # noqa: E402

FAUX_PROGRAMME = """#!/bin/bash
echo "$(basename "$0") $*" >> "$JOURNAL_APPELS"
case "$(basename "$0") $1" in
  "docker inspect"|"docker image") exit 1 ;;    # ni conteneur ni image
esac
exit 0
"""


@pytest.fixture
def faux(tmp_path):
    """Dossier de faux programmes en tête du PATH, et lieux d'essai (copie du demo)."""
    bin_ = tmp_path / 'bin'
    bin_.mkdir()
    for nom in ['docker', 'ssh', 'scp']:
        (bin_ / nom).write_text(FAUX_PROGRAMME)
        (bin_ / nom).chmod(0o755)
    lieux = tmp_path / 'lieux'
    shutil.copytree(RACINE / 'lieux' / 'demo', lieux / 'essai',
                    ignore=shutil.ignore_patterns('scans', '*.pcd'))
    (lieux / 'essai' / 'scans' / 'session').mkdir(parents=True)
    journal = tmp_path / 'appels.txt'
    env = {k: v for k, v in os.environ.items()
           if k not in ('G1_SIMU', 'G1_INTERFACES', 'G1_CYCLONEDDS_URI', 'G1_JETSON', 'G1_JETSON_NOM')}
    env.update(PATH=f'{bin_}:/usr/bin:/bin', JOURNAL_APPELS=str(journal), ATELIER_LIEUX=str(lieux),
               ROS_DOMAIN_ID='61', G1_SLAM_FAUX='1')

    class Faux:
        dossier = tmp_path
        lieu = lieux / 'essai'

        def lancer(self, *args, **autres):
            e = dict(env, **autres)
            r = subprocess.run([sys.executable, str(DOSSIER / 'jetson.py'), *args],
                               capture_output=True, text=True, env=e, timeout=60)
            return r

        def appels(self):
            return journal.read_text().splitlines() if journal.exists() else []

        def appels_robot(self):
            return [a for a in self.appels() if a.split()[0] in ('ssh', 'scp')]

    return Faux()


# --- Commandes produites -------------------------------------------------------------------

def test_docker_run_du_contrat():
    """La commande de lancement sur le robot, dans l'ordre de la section 10.2."""
    class Args:
        veille = False
        etage = 'rdc'
        localisation = None
        wifi = None
        pair = None

    env = jetson.environnement_conteneur(Args, local=False, ident='demo')
    assert env == [('ROS_DOMAIN_ID', '0'), ('G1_INTERFACES', 'auto'), ('G1_LIEU', 'demo'),
                   ('G1_ETAGE', 'rdc'), ('G1_LANCEMENT', 'navigation')]
    cmd = jetson.arguments_run('g1-jetson', 'g1-jetson:arm64', jetson.Brut('"$(id -u):$(id -g)"'),
                               jetson.Brut('"$HOME/robot-g1/lieux:/lieux:ro"'),
                               jetson.Brut('"$HOME/robot-g1/journaux/jetson:/journaux"'), env)
    texte = jetson.texte_commande(cmd)
    assert texte.startswith(
        'docker run -d --name g1-jetson --network host --init --restart no --stop-timeout 20 '
        '--user "$(id -u):$(id -g)" --cpus 4 --memory 4g ')
    assert ('-e ROS_DOMAIN_ID=0 -e G1_INTERFACES=auto -e G1_LIEU=demo -e G1_ETAGE=rdc '
            '-e G1_LANCEMENT=navigation -v "$HOME/robot-g1/lieux:/lieux:ro" '
            '-v "$HOME/robot-g1/journaux/jetson:/journaux" g1-jetson:arm64') in texte
    assert '--privileged' not in texte and '--rm' not in texte and '--runtime' not in texte
    avec_runc = jetson.arguments_run('g1-jetson', 'g1-jetson:arm64', '1000:1000', 'l:/lieux:ro', 'j:/journaux',
                                     env, runtime='runc')
    assert avec_runc[avec_runc.index('--runtime') + 1] == 'runc'
    with pytest.raises(jetson.Erreur, match='G1_JETSON_RUNTIME'):
        jetson.arguments_run('n', 'i', 'u', 'l', 'j', env, runtime='runc; rm -rf /')


def test_variables_du_conteneur(monkeypatch):
    class Args:
        veille = False
        etage = 'rdc'
        localisation = 'amcl'
        wifi = 'wlan0'
        pair = ['192.168.1.50', '192.168.1.51']

    monkeypatch.setenv('ROS_DOMAIN_ID', '61')
    monkeypatch.setenv('G1_SIMU', 'true')
    monkeypatch.delenv('G1_INTERFACES', raising=False)
    env = dict(jetson.environnement_conteneur(Args, local=True, ident='essai'))
    assert env['ROS_DOMAIN_ID'] == '61' and env['G1_INTERFACES'] == 'defaut'
    assert env['G1_LOCALISATION'] == 'amcl' and env['G1_SIMU'] == 'true'
    assert env['G1_WIFI'] == 'wlan0' and env['G1_PAIRS'] == '192.168.1.50,192.168.1.51'
    # Sur le robot : domaine 0 et interface du robot, quel que soit le terminal
    env = dict(jetson.environnement_conteneur(Args, local=False, ident='essai'))
    assert env['ROS_DOMAIN_ID'] == '0' and env['G1_INTERFACES'] == 'auto'
    Args.veille = True
    env = dict(jetson.environnement_conteneur(Args, local=True, ident=None))
    assert env['G1_LANCEMENT'] == 'veille' and 'G1_LIEU' not in env
    monkeypatch.setenv('G1_SIMU', 'peut-etre')
    with pytest.raises(jetson.Erreur, match='G1_SIMU'):
        jetson.environnement_conteneur(Args, local=True, ident=None)
    monkeypatch.delenv('G1_SIMU')
    Args.pair = ['pas-une-ip']
    with pytest.raises(jetson.reseau.ErreurReseau):
        jetson.environnement_conteneur(Args, local=True, ident=None)


def test_vitesse_reduite(monkeypatch):
    """--vitesse-max, sinon G1_VITESSE_MAX : G1_VITESSE_MAX du conteneur (premiers essais)."""
    class Args:
        veille = False
        etage = 'rdc'
        localisation = None
        wifi = None
        pair = None
        vitesse_max = '0,2'

    monkeypatch.delenv('G1_VITESSE_MAX', raising=False)
    monkeypatch.delenv('G1_SIMU', raising=False)
    assert dict(jetson.environnement_conteneur(Args, local=False, ident='essai'))['G1_VITESSE_MAX'] == '0.2'
    Args.vitesse_max = None
    assert 'G1_VITESSE_MAX' not in dict(jetson.environnement_conteneur(Args, local=False, ident='essai'))
    monkeypatch.setenv('G1_VITESSE_MAX', '0.15')
    assert dict(jetson.environnement_conteneur(Args, local=True, ident='essai'))['G1_VITESSE_MAX'] == '0.15'
    for faux in ('0', '0.5', '-0.1', 'vite', 'nan'):
        Args.vitesse_max = faux
        with pytest.raises(jetson.Erreur, match='vitesse maximale'):
            jetson.environnement_conteneur(Args, local=False, ident='essai')


def test_envoi_et_lieu():
    cmds = jetson.commandes_envoi(Path('/x/opt/jetson/g1-jetson_arm64.tar.gz'))
    assert cmds['save'] == 'docker save g1-jetson:arm64 | gzip -1 > /x/opt/jetson/g1-jetson_arm64.tar.gz'
    assert cmds['scp'][-2:] == ['/x/opt/jetson/g1-jetson_arm64.tar.gz',
                                'unitree@192.168.123.164:robot-g1/opt/jetson/g1-jetson_arm64.tar.gz']
    assert cmds['load'][-1] == ('gunzip -c robot-g1/opt/jetson/g1-jetson_arm64.tar.gz | docker load '
                                '&& rm -f robot-g1/opt/jetson/g1-jetson_arm64.tar.gz')
    assert 'BatchMode=yes' in cmds['load']
    tar, ssh = jetson.commandes_lieu(Path('/l/lieux/demo'), 'demo')
    assert tar == ['tar', '-C', '/l/lieux', '--exclude', 'demo/scans', '-czf', '-', 'demo']
    assert ssh[-2] == 'unitree@192.168.123.164'
    assert 'tar -xzf - -C .demo.nouveau' in ssh[-1] and 'mv .demo.nouveau/demo demo' in ssh[-1]


def test_hote_du_jetson(monkeypatch):
    monkeypatch.setenv('G1_JETSON', 'unitree@10.0.0.5')
    assert jetson.commande_ssh('true')[-2:] == ['unitree@10.0.0.5', 'true']


# --- Contexte de construction --------------------------------------------------------------

def test_contexte_de_construction(tmp_path):
    a = tmp_path / 'a'
    paquets = jetson.assembler_contexte(a)
    assert paquets == ['g1_bridge', 'g1_nav']
    for chemin in ['Dockerfile', 'docker/demarrer.sh', 'docker/env.sh', 'docker/reseau.py',
                   'docker/presence.py', 'docker/cyclonedds.xml.modele', 'unitree_api/package.xml',
                   'unitree_api/msg/Request.msg', 'python/atelier/__init__.py',
                   'python/atelier/lieu/robot.py', 'python/atelier/lieu/schemas/etat_pont.schema.json',
                   'python/atelier/scan/__init__.py', 'python/atelier/scan/slam_client.py',
                   'ws/g1_nav/package.xml', 'ws/g1_bridge/package.xml']:
        assert (a / chemin).is_file(), chemin
    tout = [p.relative_to(a).as_posix() for p in a.rglob('*')]
    assert not [p for p in tout if '__pycache__' in p or p.endswith('.pyc')]
    assert not [p for p in tout if p.startswith('ws/') and '/test/' in p + '/']
    assert not (a / 'python' / 'atelier' / 'serveur').exists()
    assert not (a / 'python' / 'atelier' / 'scan' / 'faux_slam.py').exists()
    taille = sum(p.stat().st_size for p in a.rglob('*') if p.is_file())
    assert taille < 20e6, f'contexte de {taille / 1e6:.0f} Mo : il ne doit jamais contenir le dépôt'
    # Même contenu, même empreinte ; VERSION n'y entre pas ; un octet changé la change
    b = tmp_path / 'b'
    jetson.assembler_contexte(b)
    assert jetson.empreinte_contexte(a) == jetson.empreinte_contexte(b)
    assert jetson.empreinte_contexte(a, 'base@sha256:1') != jetson.empreinte_contexte(a, 'base@sha256:2')
    (b / 'VERSION').write_text('date=maintenant\n')
    assert jetson.empreinte_contexte(a) == jetson.empreinte_contexte(b)
    with open(b / 'ws' / 'g1_nav' / 'package.xml', 'a') as f:
        f.write('\n')
    assert jetson.empreinte_contexte(a) != jetson.empreinte_contexte(b)


def test_contexte_sans_pont(tmp_path):
    """Sans g1_bridge dans ws/src : refus, sauf --incomplet."""
    racine = tmp_path / 'depot'
    shutil.copytree(RACINE / 'docker', racine / 'docker', ignore=shutil.ignore_patterns('tests', '__pycache__'))
    shutil.copytree(jetson.UNITREE_API, racine / jetson.UNITREE_API.relative_to(RACINE))
    shutil.copytree(RACINE / 'atelier' / 'lieu', racine / 'atelier' / 'lieu')
    (racine / 'atelier' / 'scan').mkdir()
    for f in ['atelier/__init__.py', 'atelier/scan/__init__.py', 'atelier/scan/slam_client.py']:
        shutil.copy2(RACINE / f, racine / f)
    shutil.copytree(RACINE / 'ws' / 'src' / 'g1_nav', racine / 'ws' / 'src' / 'g1_nav')
    with pytest.raises(jetson.Erreur, match='g1_bridge absent'):
        jetson.assembler_contexte(tmp_path / 'c1', racine=racine)
    assert jetson.assembler_contexte(tmp_path / 'c2', racine=racine, incomplet=True) == ['g1_nav']


def test_version_et_commande_de_construction(tmp_path):
    texte = jetson.texte_version('arm64', 'abc', ['g1_bridge', 'g1_nav'], '3f2c1ab',
                                 date='2026-10-25T23:00:00+01:00')
    champs = presence.lire_version(_ecrire(tmp_path / 'VERSION', texte))
    assert champs == {'date': '2026-10-25T23:00:00+01:00', 'commit': '3f2c1ab', 'empreinte': 'abc',
                      'arch': 'arm64', 'image': 'g1-jetson:arm64', 'paquets': 'unitree_api g1_bridge g1_nav'}
    assert presence.texte_version(champs) == '2026-10-25T23:00:00+01:00 3f2c1ab'
    cmd = jetson.commande_build('arm64', '/tmp/ctx', 'abc', sans_cache=True,
                                base='ros:humble-ros-base-jammy@sha256:0123')
    assert cmd == ['docker', 'build', '--platform', 'linux/arm64', '-t', 'g1-jetson:arm64',
                   '--build-arg', 'BASE=ros:humble-ros-base-jammy@sha256:0123',
                   '--build-arg', 'G1_EMPREINTE=abc', '--no-cache', '/tmp/ctx']
    assert 'buildx' not in cmd


def _ecrire(chemin, texte):
    chemin.write_text(texte)
    return chemin


def test_etat_de_presence():
    env = {'G1_DEBUT': '1000.0', 'G1_INTERFACES_CHOISIES': 'eth0,wlan0', 'G1_LANCEMENT': 'navigation',
           'G1_LIEU': 'demo', 'G1_ETAGE': 'rdc', 'ROS_DOMAIN_ID': '0'}
    etat = presence.etat_presence(env, {'date': 'd', 'commit': 'c', 'image': 'g1-jetson:arm64'},
                                  1012.34, arch='aarch64')
    assert etat == {'version': 'd c', 'image': 'g1-jetson:arm64', 'arch': 'aarch64', 'domaine': 0,
                    'interfaces': ['eth0', 'wlan0'], 'lancement': 'navigation', 'lieu': 'demo',
                    'etage': 'rdc', 'depuis_s': 12.3}
    veille = presence.etat_presence({'G1_LANCEMENT': 'veille', 'G1_LIEU': 'demo'}, {}, 5.0)
    assert veille['lieu'] is None and veille['interfaces'] == [] and veille['version'] == 'inconnue'


# --- La ligne de commande, avec de faux programmes -----------------------------------------

def test_aide_et_commande_mal_tapee(faux):
    r = faux.lancer('--help')
    assert r.returncode == 0 and 'construire' in r.stdout and 'verifier' in r.stdout
    r = faux.lancer('construire', '--arch', 'x86')
    assert r.returncode == 2 and 'choix inconnu' in r.stderr
    r = faux.lancer('lieu')
    assert r.returncode == 2 and 'il manque' in r.stderr
    r = faux.lancer('decoller')
    assert r.returncode == 2
    assert faux.appels() == []


@pytest.mark.parametrize('commande', [
    ['envoyer'], ['lieu', '--lieu', 'essai'], ['demarrer', '--lieu', 'essai', '--etage', 'rdc'],
    ['demarrer', '--veille'], ['arreter'], ['etat'], ['journal'], ['shell'], ['verifier']])
def test_refus_du_robot_pendant_les_essais(faux, commande):
    """G1_SLAM_FAUX=1 : code 1, message clair, et aucun ssh ni scp."""
    r = faux.lancer(*commande)
    assert r.returncode == 1, r.stdout + r.stderr
    assert 'G1_SLAM_FAUX=1' in r.stderr and '--dry-run' in r.stderr
    assert faux.appels_robot() == []


def test_demarrer_robot_a_blanc(faux):
    r = faux.lancer('demarrer', '--lieu', 'essai', '--etage', 'rdc', '--dry-run')
    assert r.returncode == 0, r.stderr
    assert faux.appels_robot() == []                       # rien n'est parti
    sortie = r.stdout
    assert 'à blanc' in sortie
    assert f"tar -C {faux.lieu.parent} --exclude essai/scans -czf - essai | ssh" in sortie
    assert 'unitree@192.168.123.164' in sortie
    ligne_run = [x for x in sortie.splitlines() if 'docker run -d' in x][0]
    assert '--name g1-jetson --network host --init --restart no --stop-timeout 20' in ligne_run
    assert '-e ROS_DOMAIN_ID=0 -e G1_INTERFACES=auto -e G1_LIEU=essai -e G1_ETAGE=rdc' in ligne_run
    assert 'g1-jetson:arm64' in ligne_run


def test_demarrer_local_a_blanc(faux):
    r = faux.lancer('demarrer', '--local', '--lieu', str(faux.lieu), '--etage', 'rdc', '--dry-run',
                    G1_JETSON_NOM='g1-jetson-e2e-61', G1_SIMU='true')
    assert r.returncode == 0, r.stderr
    ligne = [x for x in r.stdout.splitlines() if 'docker run -d' in x][0]
    assert '--name g1-jetson-e2e-61' in ligne and 'ssh' not in ligne
    assert f'--user {os.getuid()}:{os.getgid()}' in ligne
    assert '-e ROS_DOMAIN_ID=61 -e G1_INTERFACES=defaut -e G1_LIEU=essai' in ligne
    assert '-e G1_SIMU=true' in ligne
    assert f'-v {faux.lieu.parent}:/lieux:ro' in ligne and 'jetson_local:/journaux' in ligne
    assert ligne.rstrip().endswith('g1-jetson:amd64')
    assert faux.appels_robot() == []


def test_tester_local_a_blanc(faux):
    """tester-local : le conteneur amd64 du PC, réseau de l'hôte, lieu monté (comme demarrer --local)."""
    r = faux.lancer('tester-local', '--lieu', 'essai', '--etage', 'rdc', '--dry-run')
    assert r.returncode == 0, r.stderr
    ligne = [x for x in r.stdout.splitlines() if 'docker run -d' in x][0]
    assert '--name g1-jetson-local --network host' in ligne and ligne.rstrip().endswith('g1-jetson:amd64')
    assert f'-v {faux.lieu.parent}:/lieux:ro' in ligne and '-e G1_INTERFACES=defaut' in ligne
    assert faux.appels_robot() == []
    r = faux.lancer('tester-local', '--lieu', 'essai', '--etage', 'rdc')    # pour de vrai, sans image
    assert r.returncode == 1 and 'g1-jetson construire --arch amd64' in r.stderr


def test_demarrer_refus_clairs(faux):
    r = faux.lancer('demarrer', '--local', '--lieu', 'inconnu', '--etage', 'rdc', '--dry-run')
    assert r.returncode == 1 and 'introuvable' in r.stderr
    r = faux.lancer('demarrer', '--local', '--lieu', 'essai', '--etage', 'grenier', '--dry-run')
    assert r.returncode == 1 and 'g1-monde generer' in r.stderr
    r = faux.lancer('demarrer', '--local', '--lieu', 'essai', '--dry-run')
    assert r.returncode == 1 and '--etage' in r.stderr
    r = faux.lancer('demarrer', '--local', '--veille', '--pair', '192.168.1.5', '--dry-run')
    assert r.returncode == 1 and '--wifi' in r.stderr
    r = faux.lancer('demarrer', '--local', '--veille', '--dry-run', ROS_DOMAIN_ID='999')
    assert r.returncode == 1 and 'ROS_DOMAIN_ID' in r.stderr


def test_demarrer_local_sans_image(faux):
    """Pour de vrai (sans --dry-run) mais sans image : refus avant tout docker run."""
    r = faux.lancer('demarrer', '--local', '--lieu', 'essai', '--etage', 'rdc')
    assert r.returncode == 1 and 'g1-jetson construire --arch' in r.stderr
    assert not [a for a in faux.appels() if a.startswith('docker run')]


def test_envoyer_et_verifier_a_blanc(faux):
    r = faux.lancer('envoyer', '--dry-run')
    assert r.returncode == 0, r.stderr
    assert 'docker save g1-jetson:arm64 | gzip -1 >' in r.stdout
    assert 'scp -o BatchMode=yes' in r.stdout and 'docker load' in r.stdout
    r = faux.lancer('verifier', '--dry-run')
    assert r.returncode == 0, r.stderr
    assert 'bash -s' in r.stdout and '| ip -o -4 addr' in r.stdout
    assert '/state_estimator/odom_pelvis /lf/sportmodestate' in r.stdout
    r = faux.lancer('lieu', '--lieu', 'essai', '--dry-run')
    assert r.returncode == 0 and '--exclude essai/scans' in r.stdout
    for commande in (['arreter'], ['etat'], ['journal', '-f'], ['shell']):
        r = faux.lancer(*commande, '--dry-run')
        assert r.returncode == 0, (commande, r.stderr)
        assert 'ssh -o BatchMode=yes' in r.stdout
    assert faux.appels_robot() == []


def test_arreter_et_etat_local_sans_conteneur(faux):
    r = faux.lancer('arreter', '--local')
    assert r.returncode == 0 and 'rien à arrêter' in r.stdout
    r = faux.lancer('etat', '--local', '--json')
    assert r.returncode == 1
    bilan = json.loads(r.stdout)
    assert bilan['existe'] is False and bilan['en_marche'] is False and bilan['nom'] == 'g1-jetson-local'


def test_contexte_seul(faux, tmp_path):
    """--contexte : le contexte est prêt pour un docker build ailleurs ; rien n'est construit."""
    dossier = tmp_path / 'contexte'
    r = faux.lancer('construire', '--contexte', str(dossier))
    assert r.returncode == 0, r.stderr
    assert (dossier / 'Dockerfile').is_file() and (dossier / 'ws' / 'g1_bridge' / 'package.xml').is_file()
    version = presence.lire_version(dossier / 'VERSION')
    assert version['arch'] == 'arm64' and version['empreinte'] in r.stdout
    assert f'docker build -t g1-jetson:arm64 --build-arg G1_EMPREINTE={version["empreinte"]} contexte' in r.stdout
    assert not [a for a in faux.appels() if a.startswith('docker build')]
    r = faux.lancer('construire', '--contexte', str(dossier))
    assert r.returncode == 1 and 'pas vide' in r.stderr


def test_construire_arm64_sans_emulation(faux, monkeypatch):
    monkeypatch.setattr(jetson, 'emulation_prete', lambda arch: False)

    class Args:
        arch = 'arm64'
        sans_cache = False
        incomplet = False
        contexte = None

    with pytest.raises(jetson.Erreur, match='qemu-user-static'):
        jetson.construire(Args, jetson.Executeur(a_blanc=True))


# --- g1-jetson verifier : lecture du bilan du Jetson ---------------------------------------

SORTIE_JETSON = """arch=aarch64
noyau=5.10.104-tegra
l4t=# R35 (release), REVISION: 3.1
systeme=Ubuntu 20.04.6 LTS
docker=24.0.7
docker_ok=oui
runtime=runc
racine_docker=/var/lib/docker
place_ko=52428800
place_docker_ko=52428800
memoire_ko=9437184
memoire_totale_ko=15728640
processeurs=8
heure=1000.20
image=
conteneur=
internet=non
---ip
2: eth0    inet 192.168.123.164/24 brd 192.168.123.255 scope global eth0\\       valid_lft forever
5: docker0    inet 172.17.0.1/16 brd 172.17.255.255 scope global docker0\\       valid_lft forever
"""


def test_bilan_de_verification():
    champs, ip = jetson.lire_verification(SORTIE_JETSON)
    lignes = jetson.bilan_verification(champs, ip, heure_pc=1000.0)
    problemes = [t for n, t in lignes if n == 'probleme']
    assert problemes == []
    textes = ' | '.join(t for _, t in lignes)
    assert 'eth0 (192.168.123.164)' in textes and 'Docker 24.0.7' in textes
    assert 'image g1-jetson:arm64 : absente' in textes and '+0.20 s' in textes
    # Jetson plein, sans réseau du robot, Docker réservé à root, mauvaise architecture
    mauvais = (SORTIE_JETSON.replace('arch=aarch64', 'arch=x86_64').replace('docker_ok=oui', 'docker_ok=non')
               .replace('place_ko=52428800', 'place_ko=1048576').replace('192.168.123.164', '10.0.0.2'))
    champs, ip = jetson.lire_verification(mauvais)
    problemes = [t for n, t in jetson.bilan_verification(champs, ip, 1000.0) if n == 'probleme']
    assert len(problemes) == 4
    assert any('usermod -aG docker' in t for t in problemes)
    assert any('il en faut 4' in t for t in problemes)
    assert any('aucune interface en 192.168.123.x' in t for t in problemes)
