#!/usr/bin/env python3
"""Outils du critère 35, caméra (section 12.10 du plan) : de la fausse source aux visiteurs.

  outils_camera_e2e.py video --sortie FICHIER [--images 3]
      fabrique une vidéo YUYV de 1280 × 720 depuis bus.jpg d'ultralytics (l'image entière au milieu
      d'un fond gris, trois images un peu décalées), lisible par camera_usb (source:=fichier)
  outils_camera_e2e.py images [--delai 30] [--duree 3]
      /camera_poitrine/image/compressed à 8 Hz au moins, JPEG lisibles de 640 pixels de large ;
      /camera_poitrine/etat conforme au schéma etat_camera, ouverte vrai
  outils_camera_e2e.py atelier --api URL
      GET /api/camera/image?source=poitrine : un JPEG de moins de 1 s ; GET /api/camera/flux…&images=5 :
      5 images en moins de 2 s ; GET /api/camera/etat cohérent
  outils_camera_e2e.py visiteurs --api URL [--delai 60] [--depuis T]
      /visiteurs/detectes conforme au schéma personnes (source camera), au moins 3 personnes, chacune
      avec une boite dans l'image (640 × 360), avant T + délai (T : lancement de g1-visiteurs, en
      secondes de l'horloge murale) ; le champ visiteurs de /ws/etat les montre
  outils_camera_e2e.py navigateur --api URL
      Firefox sans fenêtre : la page d'essai de la vue Caméra et l'écran Caméra de l'Atelier (#camera) :
      [data-role=camera-flux] reçoit des images (naturalWidth 640) et [data-role=camera-cadres]
      dessine au moins 3 cadres ; aucune erreur dans la page
  outils_camera_e2e.py conteneur
      g1-jetson demarrer --local --dry-run : avec une fausse caméra by-id, --device …:/dev/g1_camera,
      --group-add et G1_CAMERA ; sans caméra, ni --device ni échec ; G1_CAMERA=0 : sans caméra ;
      G1_VITESSE_MAX=0.15 refusé (« le robot ne marche pas sous 0,2 m/s »)
  outils_camera_e2e.py restes --travail DOSSIER [--sauf PID…]
      aucun camera_usb, v4l2-ctl ni g1-visiteurs lancé par le critère ne doit rester

Code de sortie : 0 réussi, 1 échoué (le message dit pourquoi), 77 pas possible ici.
"""
import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))
SUJET_IMAGE = "/camera_poitrine/image/compressed"
SUJET_ETAT = "/camera_poitrine/etat"


class Echec(Exception):
    pass


class PasPossible(Exception):
    pass


def verifier(condition, message):
    if not condition:
        raise Echec(message)


def dire(texte):
    print(f"[critère 35] {texte}", flush=True)


# ---------------------------------------------------------------- vidéo de test

def video(args):
    try:
        import ultralytics
    except ImportError:
        raise PasPossible("ultralytics absent de .venv-projet (image bus.jpg)") from None
    from PIL import Image
    sys.path.insert(0, str(RACINE / "ws" / "src" / "g1_equipe"))
    from g1_equipe.image_jpeg import image_vers_yuyv
    bus = Path(ultralytics.__file__).parent / "assets" / "bus.jpg"
    morceaux = []
    with Image.open(bus) as photo:
        photo = photo.convert("RGB")
        for i in range(args.images):            # trois images un peu décalées : la vidéo « bouge »
            decalee = Image.new("RGB", photo.size, (110, 110, 110))
            decalee.paste(photo, (4 * i, 0))
            morceaux.append(image_vers_yuyv(decalee, 1280, 720))
    Path(args.sortie).write_bytes(b"".join(morceaux))
    dire(f"vidéo YUYV de test : {args.sortie} ({args.images} images de 1280 × 720, bus.jpg d'ultralytics)")
    return 0


# ---------------------------------------------------------------- ROS 2

def _noeud(nom):
    import rclpy
    from rclpy.executors import SingleThreadedExecutor
    contexte = rclpy.Context()
    rclpy.init(context=contexte)
    noeud = rclpy.create_node(nom, context=contexte)
    executeur = SingleThreadedExecutor(context=contexte)
    executeur.add_node(noeud)
    return rclpy, contexte, noeud, executeur


def _tourner(executeur, duree, condition=None):
    fin = time.monotonic() + duree
    while time.monotonic() < fin:
        executeur.spin_once(timeout_sec=0.05)
        if condition is not None and condition():
            return True
    return condition() if condition is not None else True


def images(args):
    from PIL import Image
    from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
    from sensor_msgs.msg import CompressedImage
    from std_msgs.msg import String

    from atelier.lieu import valider_message
    rclpy, contexte, noeud, executeur = _noeud("critere_35_images")
    recues, etats = [], []
    qos = QoSProfile(depth=5, reliability=ReliabilityPolicy.BEST_EFFORT, history=HistoryPolicy.KEEP_LAST)
    noeud.create_subscription(CompressedImage, SUJET_IMAGE, lambda m: recues.append((time.monotonic(), m)), qos)
    noeud.create_subscription(String, SUJET_ETAT, lambda m: etats.append(json.loads(m.data)), 10)
    try:
        verifier(_tourner(executeur, args.delai, lambda: len(recues) >= 3), f"aucune image sur {SUJET_IMAGE} en "
                 f"{args.delai:.0f} s (camera_usb lancé ? journal camera.log)")
        avant = len(recues)
        _tourner(executeur, args.duree)
        periode = recues[avant:]
        verifier(len(periode) >= 2, "les images ont cessé")
        frequence = (len(periode) - 1) / (periode[-1][0] - periode[0][0])
        verifier(frequence >= 8.0, f"{frequence:.1f} images par seconde sur {SUJET_IMAGE} (8 au moins)")
        msg = periode[-1][1]
        donnees = bytes(msg.data)
        verifier(msg.format == "jpeg" and msg.header.frame_id == "camera_poitrine",
                 f"format « {msg.format} », repère « {msg.header.frame_id} »")
        image = Image.open(io.BytesIO(donnees))
        image.load()
        verifier(image.width == 640, f"image de {image.width} × {image.height} (640 de large attendu)")
        verifier(etats, f"rien sur {SUJET_ETAT}")
        etat = etats[-1]
        erreurs = valider_message("etat_camera", etat)
        verifier(not erreurs, f"{SUJET_ETAT} non conforme : {erreurs}")
        verifier(etat["ouverte"] is True and etat["source"] == "fichier", f"état : {etat}")
        dire(f"{SUJET_IMAGE} : {frequence:.1f} images par seconde, JPEG {image.width} × {image.height} "
             f"({len(donnees) // 1024} Ko) ; {SUJET_ETAT} conforme, ouverte, {etat['ips_mesuree']} images lues par "
             "seconde")
        return 0
    finally:
        executeur.shutdown()
        noeud.destroy_node()
        rclpy.shutdown(context=contexte)


# ---------------------------------------------------------------- Atelier

def _lire(url, delai=10):
    with urllib.request.urlopen(url, timeout=delai) as r:
        return r.status, r.headers, r.read()


def atelier(args):
    api = args.api
    fin = time.monotonic() + 20
    while True:
        try:
            statut, entetes, corps = _lire(api + "/api/camera/image?source=poitrine")
            break
        except urllib.error.HTTPError as e:
            if time.monotonic() > fin:
                raise Echec(f"GET /api/camera/image : {e.code} {e.read().decode()[:300]}") from None
            time.sleep(0.3)
    age = float(entetes["X-Image-Age-S"])
    verifier(statut == 200 and entetes["Content-Type"] == "image/jpeg" and corps[:2] == b"\xff\xd8",
             f"GET /api/camera/image : {statut} {entetes['Content-Type']}")
    verifier(age < 1.0, f"image vieille de {age:.2f} s (moins de 1 s attendu)")
    verifier(entetes["X-Image-Largeur"] == "640", f"X-Image-Largeur {entetes['X-Image-Largeur']}")
    debut = time.monotonic()
    statut, entetes, corps = _lire(api + "/api/camera/flux?source=poitrine&images=5")
    duree = time.monotonic() - debut
    parties = corps.count(b"--image-g1\r\n")
    verifier(statut == 200 and entetes["Content-Type"].startswith("multipart/x-mixed-replace; boundary=image-g1"),
             f"GET /api/camera/flux : {statut} {entetes['Content-Type']}")
    verifier(parties == 5 and duree < 2.0, f"flux : {parties} images en {duree:.2f} s (5 en moins de 2 s attendues)")
    fin = time.monotonic() + 10           # l'état du nœud caméra part une fois par seconde
    etat = json.loads(_lire(api + "/api/camera/etat")[2])
    while etat["noeud"] is None and time.monotonic() < fin:
        time.sleep(0.3)
        etat = json.loads(_lire(api + "/api/camera/etat")[2])
    poitrine = etat["sources"]["poitrine"]
    verifier(etat["ros"]["actif"] and poitrine["recue"] and poitrine["largeur"] == 640 and poitrine["hauteur"] == 360,
             f"GET /api/camera/etat : {etat}")
    verifier(poitrine["ips"] >= 7.0 and poitrine["age_s"] < 1.0, f"cadence ou âge : {poitrine}")
    verifier(etat["noeud"] is not None and etat["noeud"]["ouverte"] and etat["messages"]["poitrine"] is None,
             f"état du nœud caméra : {etat['noeud']}, message {etat['messages']['poitrine']}")
    dire(f"Atelier : image de {age:.2f} s ; flux de 5 images en {duree:.2f} s ; état : {poitrine['ips']} images par "
         f"seconde reçues, {poitrine['largeur']} × {poitrine['hauteur']}, nœud caméra ouvert")
    return 0


def _ws_visiteurs(api, delai):
    """Le champ visiteurs de /ws/etat dès qu'il montre 3 personnes au moins, ou None."""
    from websockets.sync.client import connect
    adresse = api.replace("http://", "ws://") + "/ws/etat"
    fin = time.monotonic() + delai
    with connect(adresse, open_timeout=10) as ws:
        while time.monotonic() < fin:
            message = json.loads(ws.recv(timeout=5))
            v = message.get("visiteurs")
            if v and len(v.get("personnes") or []) >= 3 and not v.get("perime"):
                return v
    return None


def visiteurs(args):
    from std_msgs.msg import String

    from atelier.lieu import valider_message
    rclpy, contexte, noeud, executeur = _noeud("critere_35_visiteurs")
    recus = []
    noeud.create_subscription(String, "/visiteurs/detectes", lambda m: recus.append((time.time(), json.loads(m.data))),
                              10)
    depuis = args.depuis or time.time()
    try:
        bon = None

        def assez():
            nonlocal bon
            for t, m in recus:
                if len(m.get("personnes") or []) >= 3:
                    bon = (t, m)
                    return True
            return False
        reste = max(1.0, depuis + args.delai - time.time())
        verifier(_tourner(executeur, reste, assez), f"pas 3 personnes sur /visiteurs/detectes en {args.delai:.0f} s "
                 f"après le lancement de g1-visiteurs ({len(recus)} messages reçus"
                 + (f", le dernier avec {len(recus[-1][1]['personnes'])} personnes)" if recus else ")"))
        t, message = bon
        erreurs = valider_message("personnes", message)
        verifier(not erreurs, f"/visiteurs/detectes non conforme : {erreurs}")
        verifier(message["source"] == "camera", f"source {message['source']}")
        image = message.get("image") or {}
        verifier((image.get("largeur"), image.get("hauteur")) == (640, 360), f"image analysée : {image}")
        for p in message["personnes"]:
            b = p.get("boite")
            verifier(b and 0 <= b[0] < b[2] <= 640 and 0 <= b[1] < b[3] <= 360, f"personne {p['id']} : boite {b}")
        dire(f"/visiteurs/detectes : {len(message['personnes'])} personnes {t - depuis:.1f} s après le lancement de "
             "g1-visiteurs, cadres dans l'image 640 × 360 : "
             + ", ".join(f"n° {p['id']} à {p['distance_m']:.1f} m" for p in message["personnes"]))
    finally:
        executeur.shutdown()
        noeud.destroy_node()
        rclpy.shutdown(context=contexte)
    try:
        v = _ws_visiteurs(args.api, 10)
    except ImportError:
        raise PasPossible("le module websockets manque dans .venv-projet") from None
    verifier(v is not None, "le champ visiteurs de /ws/etat ne montre pas les 3 personnes")
    dire(f"/ws/etat : visiteurs montrés ({len(v['personnes'])} personnes, reçus il y a {v['age_recu_s']} s)")
    return 0


# ---------------------------------------------------------------- Firefox

class Navigateur:
    """Client WebDriver minimal pour geckodriver (Firefox sans fenêtre)."""

    def __init__(self, port):
        self.base = f"http://127.0.0.1:{port}"
        self.session = None

    def _requete(self, methode, chemin, corps=None, delai=120):
        donnees = None if corps is None else json.dumps(corps).encode()
        req = urllib.request.Request(self.base + chemin, data=donnees, method=methode,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=delai) as r:
                return json.loads(r.read() or b"null")["value"]
        except urllib.error.HTTPError as e:
            raise Echec(f"WebDriver {methode} {chemin} : {e.read().decode()[:300]}") from None

    def demarrer(self):
        options = {"args": ["-headless", "--width=1400", "--height=900"]}
        valeur = self._requete("POST", "/session", {"capabilities": {"alwaysMatch": {
            "browserName": "firefox", "moz:firefoxOptions": options}}})
        self.session = valeur["sessionId"]

    def ouvrir(self, url):
        self._requete("POST", f"/session/{self.session}/url", {"url": url})

    def js(self, script):
        return self._requete("POST", f"/session/{self.session}/execute/sync", {"script": script, "args": []})

    def fermer(self):
        if self.session:
            try:
                self._requete("DELETE", f"/session/{self.session}", delai=60)
            except Exception:      # noqa: BLE001 : geckodriver est arrêté de toute façon
                pass
            self.session = None


def navigateur(args):
    if not shutil.which("geckodriver") or not shutil.which("firefox"):
        raise PasPossible("geckodriver ou Firefox absent")
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    gecko = subprocess.Popen(["geckodriver", "--port", str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
    nav = Navigateur(port)
    try:
        fin = time.monotonic() + 20
        while True:
            try:
                urllib.request.urlopen(nav.base + "/status", timeout=2)
                break
            except (urllib.error.URLError, ConnectionError):
                verifier(time.monotonic() < fin and gecko.poll() is None, "geckodriver ne démarre pas")
                time.sleep(0.2)
        nav.demarrer()

        def attendre(script, delai, message):
            fin = time.monotonic() + delai
            while time.monotonic() < fin:
                valeur = nav.js(script)
                if valeur:
                    return valeur
                time.sleep(0.25)
            raise Echec(f"Firefox : {message} (erreurs de la page : {nav.js('return window.erreursAtelier')})")
        image = ("const i = document.querySelector('{0} [data-role=camera-flux]'); "
                 "return i && i.complete && i.naturalWidth === 640")
        cadres = ("const c = document.querySelector('{0} [data-role=camera-cadres]'); "
                  "return c && Number(c.dataset.cadres) >= 3 && Number(c.dataset.cadres)")
        nav.ouvrir(args.api + "/essais/camera.html")
        attendre(image.format(""), 20, "la page d'essai ne reçoit pas d'image de 640 pixels")
        n = attendre(cadres.format(""), 15, "la page d'essai ne dessine pas 3 cadres")
        verifier(nav.js("return window.erreursAtelier") == [], "erreurs JavaScript dans la page d'essai")
        dire(f"Firefox, page d'essai de la vue Caméra : image de 640 pixels, {n} cadres dessinés")
        nav.ouvrir(args.api + "/")
        nav.js("localStorage.setItem('atelier.lieu', 'essai'); localStorage.setItem('atelier.etage', 'rdc'); "
               "localStorage.setItem('atelier.mode', 'reel'); localStorage.setItem('atelier.repetition', '1');")
        nav.ouvrir(args.api + "/?recharger=1#camera")
        attendre("return document.querySelector('[data-ecran=camera], .ecran-camera') !== null", 20,
                 "l'écran Caméra de l'Atelier ne s'ouvre pas (#camera)")
        attendre(image.format("[data-role=camera-direct]"), 20, "l'écran Caméra ne reçoit pas l'image")
        n = attendre(cadres.format("[data-role=camera-direct]"), 15, "l'écran Caméra ne dessine pas 3 cadres")
        verifier(nav.js("return window.erreursAtelier") == [], "erreurs JavaScript dans l'Atelier")
        dire(f"Firefox, écran Caméra de l'Atelier : image de 640 pixels, {n} cadres dessinés, aucune erreur")
        return 0
    finally:
        nav.fermer()
        try:
            os.killpg(gecko.pid, 15)
            gecko.wait(timeout=10)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            pass


# ---------------------------------------------------------------- conteneur, à blanc

def _jetson(env_plus, *arguments):
    env = {k: v for k, v in os.environ.items() if not k.startswith("G1_CAMERA") and k != "G1_VITESSE_MAX"}
    env.update(env_plus)
    return subprocess.run([str(RACINE / "bin" / "g1-jetson"), *arguments], capture_output=True, text=True,
                          env=env, timeout=120)


def conteneur(args):
    lieux = os.environ.get("ATELIER_LIEUX") or str(RACINE / "lieux")
    verifier(Path(lieux, "essai", "lieu.yaml").is_file(), f"copie du demo « essai » absente de {lieux}")
    with tempfile.TemporaryDirectory(prefix="critere35_camera_") as dossier:
        d = Path(dossier)
        (d / "dev").mkdir()
        (d / "dev" / "video7").write_text("")
        (d / "by-id").mkdir()
        (d / "by-id" / "usb-e-con_Systems_See3CAM_11CUG_ESSAI-video-index0").symlink_to(d / "dev" / "video7")
        (d / "usb" / "2-1" / "2-1:1.0").mkdir(parents=True)
        (d / "usb" / "2-1" / "speed").write_text("5000\n")
        (d / "sys" / "video7").mkdir(parents=True)
        (d / "sys" / "video7" / "device").symlink_to(d / "usb" / "2-1" / "2-1:1.0")
        demarrer = ("demarrer", "--local", "--lieu", "essai", "--etage", "rdc", "--dry-run")
        r = _jetson({"G1_CAMERA_BY_ID": str(d / "by-id"), "G1_CAMERA_SYS": str(d / "sys")}, *demarrer)
        verifier(r.returncode == 0, f"g1-jetson demarrer --dry-run (caméra) : code {r.returncode} {r.stderr[-300:]}")
        ligne = [x for x in r.stdout.splitlines() if "docker run -d" in x]
        verifier(ligne, "pas de docker run affiché")
        gid = os.stat(d / "dev" / "video7").st_gid
        attendu = f"--device {d / 'dev' / 'video7'}:/dev/g1_camera --group-add {gid}"
        verifier(attendu in ligne[0] and "-e G1_CAMERA=/dev/g1_camera" in ligne[0],
                 f"options de la caméra absentes : {ligne[0][:400]}")
        verifier(ligne[0].index("--memory 4g") < ligne[0].index("--device"), "--device n'est pas après --memory")
        dire(f"à blanc, avec une fausse See3CAM : {attendu} et -e G1_CAMERA=/dev/g1_camera")
        r = _jetson({"G1_CAMERA_BY_ID": str(d / "rien"), "G1_CAMERA_SYS": str(d / "sys")}, *demarrer)
        ligne = [x for x in r.stdout.splitlines() if "docker run -d" in x]
        verifier(r.returncode == 0 and ligne and "--device" not in ligne[0] and "G1_CAMERA" not in ligne[0],
                 f"sans caméra : code {r.returncode}, {r.stdout[-300:]} {r.stderr[-300:]}")
        verifier("sans caméra" in r.stdout, "sans caméra : pas de message")
        r = _jetson({"G1_CAMERA_BY_ID": str(d / "by-id"), "G1_CAMERA": "0"}, *demarrer)
        ligne = [x for x in r.stdout.splitlines() if "docker run -d" in x]
        verifier(r.returncode == 0 and ligne and "--device" not in ligne[0], "G1_CAMERA=0 : la caméra est passée")
        dire("à blanc, sans caméra (ou G1_CAMERA=0) : ni --device ni échec")
        r = _jetson({"G1_VITESSE_MAX": "0.15"}, *demarrer)
        verifier(r.returncode == 1 and "le robot ne marche pas sous 0,2 m/s" in r.stderr,
                 f"G1_VITESSE_MAX=0.15 : code {r.returncode}, {r.stderr[-300:]}")
        dire("G1_VITESSE_MAX=0.15 refusé : " + r.stderr.strip().splitlines()[-1][:160])
    return 0


# ---------------------------------------------------------------- restes

def restes(args):
    exclus = {os.getpid(), os.getppid()} | {int(p) for p in args.sauf}
    motifs = (b"camera_usb", b"v4l2-ctl", b"visiteurs.py", b"g1-visiteurs")
    trouves = []
    for d in Path("/proc").iterdir():
        if not d.name.isdigit() or int(d.name) in exclus:
            continue
        try:
            ligne = (d / "cmdline").read_bytes().replace(b"\0", b" ")
            if not any(m in ligne for m in motifs):
                continue
            environ = (d / "environ").read_bytes().split(b"\0")
            if f"ATELIER_LIEUX={args.travail}/lieux".encode() not in environ and args.travail.encode() not in ligne:
                continue
            etat = (d / "stat").read_text().split(") ")[-1].split()[0]
            if etat != "Z":
                trouves.append(f"{d.name} {ligne.decode(errors='replace').strip()[:150]}")
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
    if trouves:
        print("Processus restants :\n  " + "\n  ".join(trouves))
        return 1
    print("Aucun processus restant (camera_usb, v4l2-ctl, g1-visiteurs).")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="outils_camera_e2e.py", description=__doc__.split("\n")[0])
    sous = p.add_subparsers(dest="action", required=True)
    s = sous.add_parser("video")
    s.add_argument("--sortie", required=True)
    s.add_argument("--images", type=int, default=3)
    s = sous.add_parser("images")
    s.add_argument("--delai", type=float, default=30.0)
    s.add_argument("--duree", type=float, default=3.0)
    s = sous.add_parser("atelier")
    s.add_argument("--api", required=True)
    s = sous.add_parser("visiteurs")
    s.add_argument("--api", required=True)
    s.add_argument("--delai", type=float, default=60.0)
    s.add_argument("--depuis", type=float, default=None)
    s = sous.add_parser("navigateur")
    s.add_argument("--api", required=True)
    sous.add_parser("conteneur")
    s = sous.add_parser("restes")
    s.add_argument("--travail", required=True)
    s.add_argument("--sauf", nargs="*", default=[])
    args = p.parse_args(argv)
    action = {"video": video, "images": images, "atelier": atelier, "visiteurs": visiteurs, "navigateur": navigateur,
              "conteneur": conteneur, "restes": restes}[args.action]
    try:
        return action(args)
    except Echec as e:
        dire(f"ÉCHEC : {e}")
        return 1
    except PasPossible as e:
        dire(f"PAS POSSIBLE : {e}")
        return 77


if __name__ == "__main__":
    sys.exit(main())
