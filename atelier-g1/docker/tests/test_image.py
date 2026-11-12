"""Tests de l'image g1-jetson:amd64 : demarrer.sh, reseau.py et presence.py dans le conteneur.

Lancement : .venv-projet/bin/python -m pytest docker/tests
Sautés si Docker manque ou si l'image n'est pas construite (g1-jetson construire --arch amd64).
Tous les conteneurs tournent en --network none (rien ne sort de la machine, aucun robot), domaine 61,
et sont retirés à la fin, même après un échec.

Vague 5 (caméra de poitrine, vitesse minimale) : les scripts du dépôt (demarrer.sh, presence.py) sont
aussi essayés montés dans l'image, même construite avant ; ce que la couche 2d apporte (Pillow,
v4l2-ctl, camera_usb) n'est vérifié que dans une image qui l'a ; la vraie caméra dans le conteneur,
seulement avec G1_TEST_CAMERA=/dev/v4l/by-id/…-video-index0 (images lues par seconde : 20 au moins,
ou G1_TEST_CAMERA_IPS pour une autre caméra, ex. 8 pour une webcam USB 2 qui fait 10 images par
seconde en 1280 × 720). G1_TEST_IMAGE choisit une autre image (ex. une image d'essai construite
par-dessus).
"""
import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent.parent
IMAGE = os.environ.get('G1_TEST_IMAGE') or 'g1-jetson:amd64'
SCRIPTS_DU_DEPOT = [f'{RACINE}/docker/{nom}:/opt/g1/{nom}:ro' for nom in ('demarrer.sh', 'presence.py')]


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


def lancer(nom, env, *commande, volumes=(), detache=False, delai=60, reseau='none', depot=False):
    """docker run de l'image ; depot : avec demarrer.sh et presence.py du dépôt (montés, lancés par bash :
    ils ne sont pas exécutables dans le dépôt)."""
    cmd = ['docker', 'run', '--name', nom, '--network', reseau, '--init', '--stop-timeout', '20']
    cmd += ['-d'] if detache else []
    for cle, valeur in {'ROS_DOMAIN_ID': '61', **env}.items():
        cmd += ['-e', f'{cle}={valeur}']
    for v in list(volumes) + (SCRIPTS_DU_DEPOT if depot else []):
        cmd += ['-v', v]
    if depot:
        cmd += ['--entrypoint', 'bash']
        commande = ('/opt/g1/demarrer.sh', *commande)
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
    ({'G1_LANCEMENT': 'veille', 'G1_PILOTAGE': '2'}, 'G1_PILOTAGE=2'),
    ({'G1_LANCEMENT': 'veille', 'G1_PILOTAGE': '1', 'G1_PILOTAGE_PORT': '80'}, 'G1_PILOTAGE_PORT=80'),
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
    assert etat['image'] == 'g1-jetson:amd64' and etat['lieu'] is None and etat['depuis_s'] >= 0
    # « camera » : depuis la vague 5 (une image construite avant ne l'a pas)
    assert set(etat) - {'camera'} == {'version', 'image', 'arch', 'domaine', 'interfaces', 'lancement', 'lieu',
                                      'etage', 'depuis_s'}
    assert etat.get('camera') is None
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


LIRE_ETAT = """
import json, sys, urllib.request, urllib.error
requete = urllib.request.Request('http://127.0.0.1:%s/etat', headers=json.loads(sys.argv[1]))
try:
    with urllib.request.urlopen(requete, timeout=5) as r:
        print(r.status, r.read().decode())
except urllib.error.HTTPError as e:
    print(e.code, e.read().decode())
"""


def test_pilotage_dans_le_conteneur(conteneurs):
    """G1_PILOTAGE=1 (vague 4) : le nœud pilotage répond sur son port, exige le jeton, et s'arrête
    proprement avec docker stop (StopMove, main rendue au guide)."""
    nom = conteneurs()
    port = '18093'
    r = lancer(nom, {'G1_LANCEMENT': 'veille', 'G1_INTERFACES': 'defaut', 'G1_PILOTAGE': '1',
                     'G1_PILOTAGE_PORT': port, 'G1_PILOTAGE_JETON': 'jeton-essai'}, detache=True)
    assert r.returncode == 0, r.stderr
    assert attendre_journal(nom, 'pilotage port ' + port + ' avec jeton', 20), journal(nom)[-2000:]
    assert attendre_journal(nom, 'pilotage prêt', 30), journal(nom)[-2000:]

    def etat(entetes):
        sortie = subprocess.run(['docker', 'exec', nom, 'python3', '-c', LIRE_ETAT % port, json.dumps(entetes)],
                                capture_output=True, text=True, timeout=30)
        code, _, corps = sortie.stdout.strip().partition(' ')
        return int(code), json.loads(corps)
    code, corps = etat({})
    assert code == 401 and 'Jeton' in corps['detail']
    code, corps = etat({'X-Jeton': 'jeton-essai'})
    assert code == 200 and corps['maitre'] == 'guide' and corps['robot_repond'] is False
    debut = time.monotonic()
    subprocess.run(['docker', 'stop', nom], capture_output=True, timeout=40)
    assert time.monotonic() - debut < 12
    texte = journal(nom)
    assert 'arrêt du nœud pilotage' in texte and 'pilotage arrêté' in texte and 'g1-jetson : arrêté' in texte
    code = subprocess.run(['docker', 'inspect', '-f', '{{.State.ExitCode}}', nom],
                          capture_output=True, text=True).stdout.strip()
    assert code == '0'


# --- Vague 5 : vitesse minimale et caméra de poitrine -------------------------------------

def _avec_la_couche_camera():
    """L'image a-t-elle la couche 2d (Pillow, v4l2-ctl) et l'exécutable camera_usb ?"""
    r = subprocess.run(['docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'bash', IMAGE, '-c',
                        'source /opt/g1/env.sh >/dev/null; python3 -c "import PIL, numpy" && command -v v4l2-ctl '
                        '&& ros2 pkg executables g1_equipe | grep -q camera_usb'],
                       capture_output=True, text=True, timeout=120)
    return r.returncode == 0


@pytest.mark.parametrize('vitesse, message', [
    ('0.15', 'le robot ne marche pas sous 0,2 m/s'), ('.1', 'le robot ne marche pas sous 0,2 m/s'),
    ('0.5', 'au plus 0.4 m/s'), ('vite', 'G1_VITESSE_MAX=vite')])
def test_vitesse_trop_basse_refusee(conteneurs, vitesse, message):
    """demarrer.sh du dépôt : G1_VITESSE_MAX sous 0,2 (ou au-dessus de 0,4) refusé, même en veille."""
    r = lancer(conteneurs(), {'G1_LANCEMENT': 'veille', 'G1_INTERFACES': 'defaut', 'G1_VITESSE_MAX': vitesse},
               depot=True)
    assert r.returncode == 1 and message in r.stderr, r.stdout + r.stderr


def test_camera_absente_du_conteneur(conteneurs):
    """G1_CAMERA sans périphérique : le conteneur démarre sans caméra, et le dit ; presence : null."""
    nom = conteneurs()
    r = lancer(nom, {'G1_LANCEMENT': 'veille', 'G1_INTERFACES': 'defaut', 'G1_CAMERA': '/dev/g1_camera',
                     'G1_VITESSE_MAX': '0.2'}, depot=True, detache=True)
    assert r.returncode == 0, r.stderr
    assert attendre_journal(nom, 'caméra absente (/dev/g1_camera introuvable)', 20), journal(nom)[-1500:]
    assert attendre_journal(nom, 'démarrage sans caméra', 5)
    lecture = subprocess.run(['docker', 'exec', nom, 'bash', '-c',
                              'source /opt/g1/env.sh >/dev/null; python3 /opt/g1/presence.py --lire --delai 10'],
                             capture_output=True, text=True, timeout=60)
    assert json.loads(lecture.stdout.strip().splitlines()[-1])['camera'] is None
    subprocess.run(['docker', 'stop', nom], capture_output=True, timeout=40)
    texte = journal(nom)
    assert 'SIGINT au nœud de présence' in texte and 'g1-jetson : arrêté' in texte
    assert 'arrêt du nœud de la caméra' not in texte          # aucun nœud de caméra n'a été lancé


def test_image_avec_la_camera():
    """La couche 2d et camera_usb (image construite depuis la vague 5)."""
    demarrer = subprocess.run(['docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'cat', IMAGE,
                               '/opt/g1/demarrer.sh'], capture_output=True, text=True, timeout=60).stdout
    if 'G1_CAMERA' not in demarrer:
        pytest.skip(f'{IMAGE} construite avant la caméra (vague 5) : g1-jetson construire --arch amd64')
    assert _avec_la_couche_camera(), 'Pillow, v4l2-ctl ou camera_usb manque dans l\'image'


LIRE_CAMERA = """
import json, sys, time, rclpy
from std_msgs.msg import String
rclpy.init()
n = rclpy.create_node('lecture_camera')
recus = []
n.create_subscription(String, '/camera_poitrine/etat', lambda m: recus.append(json.loads(m.data)), 10)
fin = time.monotonic() + 20
while time.monotonic() < fin and not (recus and recus[-1]['ouverte'] and recus[-1]['publiees'] > 5):
    rclpy.spin_once(n, timeout_sec=0.2)
print(json.dumps(recus[-1] if recus else None))
"""


@pytest.mark.skipif(not os.environ.get('G1_TEST_CAMERA'), reason='G1_TEST_CAMERA non donné (vraie caméra)')
def test_vraie_camera_dans_le_conteneur(conteneurs):
    """La See3CAM passée comme le fait g1-jetson demarrer : --device, --group-add, G1_CAMERA ; l'utilisateur
    du PC (pas root) la lit, camera_usb publie ; docker stop arrête tout proprement."""
    if not _avec_la_couche_camera():
        pytest.skip(f'{IMAGE} n\'a pas la couche caméra : g1-jetson construire --arch amd64')
    chemin = os.path.realpath(os.environ['G1_TEST_CAMERA'])
    nom = conteneurs()
    cmd = ['docker', 'run', '-d', '--name', nom, '--network', 'none', '--init', '--user', f'{os.getuid()}:{os.getgid()}',
           '--device', f'{chemin}:/dev/g1_camera', '--group-add', str(os.stat(chemin).st_gid),
           '-e', 'ROS_DOMAIN_ID=61', '-e', 'G1_LANCEMENT=veille', '-e', 'G1_INTERFACES=defaut',
           '-e', 'G1_CAMERA=/dev/g1_camera', IMAGE]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert attendre_journal(nom, 'caméra /dev/g1_camera', 20), journal(nom)[-1500:]
    lecture = subprocess.run(['docker', 'exec', nom, 'bash', '-c', 'source /opt/g1/env.sh >/dev/null; python3 -c "$0"',
                              LIRE_CAMERA], capture_output=True, text=True, timeout=60)
    etat = json.loads(lecture.stdout.strip().splitlines()[-1])
    assert etat and etat['ouverte'] and etat['peripherique'] == '/dev/g1_camera' and etat['erreur'] is None, etat
    ips_min = float(os.environ.get('G1_TEST_CAMERA_IPS') or 20)     # See3CAM en USB 3 : 30 images par seconde
    assert etat['largeur'] == 640 and etat['ips_mesuree'] >= ips_min, etat
    subprocess.run(['docker', 'stop', nom], capture_output=True, timeout=40)
    texte = journal(nom)
    assert 'arrêt du nœud de la caméra' in texte and 'g1-jetson : arrêté' in texte
