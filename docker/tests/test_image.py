"""Tests de l'image g1-jetson:amd64 : demarrer.sh, reseau.py et presence.py dans le conteneur.

Lancement : .venv-projet/bin/python -m pytest docker/tests
Sautés si Docker manque ou si l'image n'est pas construite (g1-jetson construire --arch amd64).
Tous les conteneurs tournent en --network none (rien ne sort de la machine, aucun robot), domaine 61,
et sont retirés à la fin, même après un échec.
"""
import json
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent.parent
IMAGE = 'g1-jetson:amd64'


def _image_presente():
    if not shutil.which('docker'):
        return False
    return subprocess.run(['docker', 'image', 'inspect', IMAGE], capture_output=True).returncode == 0


pytestmark = pytest.mark.skipif(not _image_presente(),
                                reason=f'image {IMAGE} absente : g1-jetson construire --arch amd64')


@pytest.fixture
def conteneurs():
    """Noms uniques ; tous les conteneurs nommés ainsi sont retirés à la fin."""
    noms = []

    def nouveau():
        nom = f'g1-jetson-essai-{uuid.uuid4().hex[:8]}'
        noms.append(nom)
        return nom

    yield nouveau
    for nom in noms:
        subprocess.run(['docker', 'rm', '-f', nom], capture_output=True)


@pytest.fixture
def lieux(tmp_path):
    dossier = tmp_path / 'lieux'
    shutil.copytree(RACINE / 'lieux' / 'demo', dossier / 'essai',
                    ignore=shutil.ignore_patterns('scans', '*.pcd'))
    return dossier


def lancer(nom, env, *commande, volumes=(), detache=False, delai=60, reseau='none'):
    cmd = ['docker', 'run', '--name', nom, '--network', reseau, '--init', '--stop-timeout', '20']
    cmd += ['-d'] if detache else []
    for cle, valeur in {'ROS_DOMAIN_ID': '61', **env}.items():
        cmd += ['-e', f'{cle}={valeur}']
    for v in volumes:
        cmd += ['-v', v]
    return subprocess.run(cmd + [IMAGE, *commande], capture_output=True, text=True, timeout=delai)


def journal(nom):
    r = subprocess.run(['docker', 'logs', nom], capture_output=True, text=True)
    return r.stdout + r.stderr


def attendre_journal(nom, texte, delai):
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        if texte in journal(nom):
            return True
        time.sleep(0.5)
    return False


@pytest.mark.parametrize('env, message', [
    ({'G1_LANCEMENT': 'danse'}, 'G1_LANCEMENT=danse inconnu'),
    ({}, 'G1_LIEU et G1_ETAGE sont obligatoires'),
    ({'G1_LIEU': 'demo', 'G1_ETAGE': 'rdc'}, 'introuvable dans /lieux'),
    ({'G1_LIEU': '../etc', 'G1_ETAGE': 'rdc'}, 'il faut l\'id d\'un lieu'),
    ({'G1_LANCEMENT': 'veille', 'ROS_DOMAIN_ID': '300'}, 'ROS_DOMAIN_ID=300'),
    ({'G1_LANCEMENT': 'commande'}, 'donnez la commande'),
    ({'G1_LIEU': 'essai', 'G1_ETAGE': 'rdc', 'G1_LOCALISATION': 'simu'}, 'refusé dans le conteneur'),
    ({'G1_LIEU': 'essai', 'G1_ETAGE': 'rdc', 'G1_SIMU': 'oui'}, 'G1_SIMU=oui'),
    ({'G1_LIEU': 'essai', 'G1_ETAGE': 'rdc', 'G1_VITESSE_MAX': 'vite'}, 'G1_VITESSE_MAX=vite'),
    ({'G1_LANCEMENT': 'veille', 'G1_INTERFACES': 'auto'}, 'réseau du robot introuvable'),
    ({'G1_LANCEMENT': 'veille', 'G1_INTERFACES': 'eth7'}, 'eth7 introuvable'),
    ({'G1_LANCEMENT': 'veille', 'G1_INTERFACES': 'lo', 'G1_PAIRS': 'x.y'}, 'n\'est pas une adresse IP'),
])
def test_refus_au_demarrage(conteneurs, lieux, env, message):
    """Réglage faux : code 1 tout de suite, message en français, rien n'est lancé."""
    r = lancer(conteneurs(), env, volumes=[f'{lieux}:/lieux:ro'], delai=60)
    assert r.returncode == 1, r.stdout + r.stderr
    assert message in r.stderr, r.stderr
    assert 'ros2 launch' not in r.stdout


def test_interfaces_et_ligne_de_demarrage(conteneurs):
    script = 'source /opt/g1/env.sh; echo "uri=$CYCLONEDDS_URI"; cat /tmp/cyclonedds.xml'
    r = lancer(conteneurs(), {'G1_LANCEMENT': 'commande', 'G1_INTERFACES': 'lo'}, 'bash', '-c', script)
    assert r.returncode == 0, r.stderr
    assert 'g1-jetson : domaine 61, interfaces lo, lieu aucun, lancement commande' in r.stdout
    assert 'uri=file:///tmp/cyclonedds.xml' in r.stdout
    assert '<NetworkInterface name="lo" priority="default" multicast="default"/>' in r.stdout
    # defaut : pas de CYCLONEDDS_URI ; G1_CYCLONEDDS_URI : repris tel quel
    script = 'source /opt/g1/env.sh; echo "uri=${CYCLONEDDS_URI:-aucune}"; ls /tmp/cyclonedds.xml 2>&1'
    r = lancer(conteneurs(), {'G1_LANCEMENT': 'commande', 'G1_INTERFACES': 'defaut'}, 'bash', '-c', script)
    assert 'uri=aucune' in r.stdout and 'interfaces par défaut' in r.stdout
    uri = '<CycloneDDS><Domain><General><Interfaces><NetworkInterface name="lo"/></Interfaces></General></Domain></CycloneDDS>'
    r = lancer(conteneurs(), {'G1_LANCEMENT': 'commande', 'G1_CYCLONEDDS_URI': uri}, 'bash', '-c', script)
    assert f'uri={uri}' in r.stdout and 'imposées par G1_CYCLONEDDS_URI' in r.stdout


def test_code_de_la_commande_et_utilisateur(conteneurs, tmp_path):
    """Le code de la commande est rendu ; un utilisateur quelconque peut écrire ses journaux."""
    journaux = tmp_path / 'journaux'
    journaux.mkdir()
    r = lancer(conteneurs(), {'G1_LANCEMENT': 'commande', 'G1_INTERFACES': 'defaut'},
               'bash', '-c', 'id -u; touch "$ROS_LOG_DIR/essai"; exit 3',
               volumes=[f'{journaux}:/journaux'])
    assert r.returncode == 3
    assert 's\'est arrêté seul (code 3)' in r.stdout
    assert (journaux / 'ros' / 'log' / 'essai').exists()


def test_presence_et_arret_propre(conteneurs):
    """Veille : /g1_jetson/etat publié ; docker stop arrête tout proprement (code 0)."""
    nom = conteneurs()
    r = lancer(nom, {'G1_LANCEMENT': 'veille', 'G1_INTERFACES': 'defaut'}, detache=True)
    assert r.returncode == 0, r.stderr
    assert attendre_journal(nom, 'g1-jetson : domaine 61', 20)
    lecture = subprocess.run(['docker', 'exec', nom, 'bash', '-c',
                              'source /opt/g1/env.sh >/dev/null; python3 /opt/g1/presence.py --lire --delai 10'],
                             capture_output=True, text=True, timeout=60)
    assert lecture.returncode == 0, lecture.stderr
    etat = json.loads(lecture.stdout.strip().splitlines()[-1])
    assert etat['lancement'] == 'veille' and etat['arch'] == 'x86_64' and etat['domaine'] == 61
    assert etat['image'] == IMAGE and etat['lieu'] is None and etat['depuis_s'] >= 0
    assert set(etat) == {'version', 'image', 'arch', 'domaine', 'interfaces', 'lancement', 'lieu',
                         'etage', 'depuis_s'}
    debut = time.monotonic()
    subprocess.run(['docker', 'stop', nom], capture_output=True, timeout=40)
    assert time.monotonic() - debut < 10
    texte = journal(nom)
    assert 'arrêt demandé' in texte and 'g1-jetson : arrêté' in texte
    code = subprocess.run(['docker', 'inspect', '-f', '{{.State.ExitCode}}', nom],
                          capture_output=True, text=True).stdout.strip()
    assert code == '0'


def test_navigation_arretee_par_sigint(conteneurs, lieux):
    """docker stop pendant la navigation : SIGINT à ros2 launch, arrêt en moins de 20 s, code 0."""
    nom = conteneurs()
    r = lancer(nom, {'G1_LIEU': 'essai', 'G1_ETAGE': 'rdc', 'G1_INTERFACES': 'defaut'},
               volumes=[f'{lieux}:/lieux:ro'], detache=True)
    assert r.returncode == 0, r.stderr
    assert attendre_journal(nom, '[pont-', 60) or attendre_journal(nom, 'process started', 5), journal(nom)[-2000:]
    time.sleep(3)
    debut = time.monotonic()
    subprocess.run(['docker', 'stop', nom], capture_output=True, timeout=60)
    duree = time.monotonic() - debut
    texte = journal(nom)
    assert duree < 20, texte[-2000:]
    assert 'SIGINT à ros2 launch' in texte and 'g1-jetson : arrêté' in texte
    assert 'ne s\'est pas arrêté' not in texte
    code = subprocess.run(['docker', 'inspect', '-f', '{{.State.ExitCode}}', nom],
                          capture_output=True, text=True).stdout.strip()
    assert code == '0'
