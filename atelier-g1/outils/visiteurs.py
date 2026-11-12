#!/usr/bin/env python3
"""
g1-visiteurs : les visiteurs vus par la caméra de poitrine (vague 5, section 12.7 du plan).

  g1-visiteurs                                l'image du robot (/camera_poitrine/image/compressed)
  g1-visiteurs --lieu demo --image            réglages de camera.yaml ; image avec les cadres publiée
  g1-visiteurs --source 2                     une caméra de ce PC (/dev/video2), sans robot
  g1-visiteurs --source bus.jpg --une-fois    les personnes d'une image, affichées (sans fenêtre)
  g1-visiteurs --fenetre                      l'image et les cadres à l'écran (touche q pour quitter)

YOLO pose (yolo11n-pose.pt) et le suivi ByteTrack (un numéro par personne, le même tant qu'elle est
suivie), sur la carte graphique s'il y en a une. Chaque personne est placée dans base_link par la
géométrie de atelier.equipe.camera : distance par sa taille dans l'image (ou celle du buste, ou des
épaules), position et champ de la caméra de camera.yaml. Elles partent sur /visiteurs/detectes
(std_msgs/String, JSON du schéma personnes, source camera), à detection.frequence_hz au plus, avec
leur cadre « boite » en pixels et l'image analysée (« image ») ; avec --image, la même image avec
les cadres dessinés sur /visiteurs/image/compressed (3 Hz), que l'Atelier peut montrer.

Python du projet (.venv-projet : ultralytics, torch, OpenCV), avec ROS 2 chargé (bin/g1-visiteurs).
Ne commande rien : il regarde et publie.
"""
import argparse
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from atelier import chemin_lieu  # noqa: E402
from atelier.equipe.camera import message_visiteurs, personnes_depuis_detections  # noqa: E402
from atelier.lieu import ErreurLieu  # noqa: E402
from atelier.lieu import equipe as E  # noqa: E402

SUJET_ENTREE = "/camera_poitrine/image/compressed"
SUJET_SORTIE = "/visiteurs/detectes"
SUJET_IMAGE = "/visiteurs/image/compressed"
FREQUENCE_IMAGE_HZ = 3.0          # images avec cadres (--image) : 2 à 5 Hz (contrat)
MODELE_DEFAUT = "yolo11n-pose.pt"
DOSSIER_MODELES = RACINE / "modeles"
EXTENSIONS_IMAGES = (".jpg", ".jpeg", ".png", ".bmp", ".webp")


class Erreur(Exception):
    """Échec qui arrête la commande (code 1), avec un message qui dit quoi faire."""


def dire(texte):
    """Message pour l'utilisateur, sur la sortie d'erreur (la sortie standard ne reçoit que le JSON
    de --une-fois)."""
    print(f"g1-visiteurs : {texte}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------- réglages

def lire_camera(lieu):
    """(contenu de camera.yaml, d'où il vient) : celui du lieu, sinon l'exemple livré."""
    if lieu:
        try:
            camera = E.charger_equipe(chemin_lieu(lieu), "camera")
        except ErreurLieu as e:
            raise Erreur(f"camera.yaml du lieu {lieu} est faux : {e.erreurs[0]} (onglet Caméra de l'Atelier)") from None
        if camera is not None:
            return camera, f"camera.yaml du lieu {lieu}"
        dire(f"le lieu {lieu} n'a pas de camera.yaml : réglages de l'exemple (atelier/lieu/exemples/camera.yaml)")
    return E.exemple_equipe("camera"), "exemple (atelier/lieu/exemples/camera.yaml)"


def trouver_modele(nom):
    """Chemin du modèle : un chemin donné, sinon un fichier de ce nom dans ~/robot-g1/modeles/."""
    chemin = Path(nom).expanduser()
    if chemin.is_file():
        return chemin
    trouves = sorted(DOSSIER_MODELES.rglob(Path(nom).name)) if DOSSIER_MODELES.is_dir() else []
    if not trouves:
        raise Erreur(f"modèle de détection « {nom} » introuvable (ni ce chemin, ni dans {DOSSIER_MODELES}) : "
                     f"le modèle de pose est modeles/yolo/{MODELE_DEFAUT}")
    return trouves[0]


# ---------------------------------------------------------------- détection

def _liste(valeur):
    """Tenseur torch, tableau numpy ou liste → liste Python (None reste None)."""
    if valeur is None:
        return None
    if hasattr(valeur, "cpu"):
        valeur = valeur.cpu()
    if hasattr(valeur, "numpy"):
        valeur = valeur.numpy()
    return valeur.tolist() if hasattr(valeur, "tolist") else list(valeur)


def detections_du_resultat(resultat):
    """Détections d'un résultat de YOLO (ultralytics.engine.results.Results) : [{id, boite,
    confiance, points}] ; id : numéro de suivi ByteTrack, ou None pas encore suivi."""
    boites = resultat.boxes
    if boites is None:
        return []
    xyxy = _liste(boites.xyxy) or []
    confiances = _liste(boites.conf) or [None] * len(xyxy)
    ids = _liste(getattr(boites, "id", None))
    ids = [None if i is None else int(i) for i in ids] if ids is not None else [None] * len(xyxy)
    cles = getattr(resultat, "keypoints", None)
    points = _liste(cles.data) if cles is not None and getattr(cles, "data", None) is not None else None
    if not points or len(points) != len(xyxy):
        points = [None] * len(xyxy)
    return [{"id": ids[i], "boite": [float(v) for v in xyxy[i]], "confiance": float(confiances[i] or 0.0),
             "points": points[i]} for i in range(len(xyxy))]


class Detecteur:
    """YOLO pose et ByteTrack : analyser(image BGR) → détections. modele : un objet YOLO déjà
    chargé (les tests en donnent un faux, avec une méthode track)."""

    def __init__(self, modele, confiance=0.5, appareil="cpu"):
        self.modele = modele
        self.confiance = float(confiance)
        self.appareil = appareil

    @classmethod
    def charger(cls, chemin, confiance=0.5, appareil="auto"):
        """Charge le modèle (quelques secondes) ; appareil : auto (GPU s'il y en a un), cpu ou 0."""
        try:
            import torch
            from ultralytics import YOLO
        except ImportError as e:
            raise Erreur(f"ultralytics ou torch manque ({e}) : lancez g1-visiteurs (Python du projet, "
                         ".venv-projet)") from None
        if appareil == "auto":
            appareil = 0 if torch.cuda.is_available() else "cpu"
        elif appareil not in ("cpu",):
            appareil = int(appareil)
        modele = YOLO(str(chemin))
        nom = ("carte graphique " + torch.cuda.get_device_name(0)) if appareil != "cpu" else "processeur"
        dire(f"modèle {Path(chemin).name} chargé, calcul sur : {nom}")
        return cls(modele, confiance, appareil)

    def analyser(self, image):
        resultats = self.modele.track(image, persist=True, tracker="bytetrack.yaml", classes=[0],
                                      conf=self.confiance, device=self.appareil, verbose=False)
        return detections_du_resultat(resultats[0]) if resultats else []


def analyser_image(detecteur, image, camera, temps, numero=None, sujet=None):
    """Une image BGR (numpy) → (message de /visiteurs/detectes, détections brutes)."""
    hauteur, largeur = image.shape[:2]
    detections = detecteur.analyser(image)
    personnes = personnes_depuis_detections(detections, camera, largeur, hauteur)
    message = message_visiteurs(temps, personnes, image={"largeur": int(largeur), "hauteur": int(hauteur),
                                                         "numero": numero, "sujet": sujet})
    return message, detections


def resume(message):
    """« 2 visiteurs : n° 1 à 2,1 m (face), n° 3 à 3,4 m » pour le terminal."""
    personnes = message["personnes"]
    if not personnes:
        return "aucun visiteur"
    morceaux = []
    for p in personnes[:6]:
        face = ", face" if p.get("regarde_robot") else ""
        morceaux.append(f"n° {p['id']} à {p['distance_m']:.1f} m ({p.get('methode_distance', '?')}{face})"
                        .replace(".", ","))
    return f"{len(personnes)} visiteur{'s' if len(personnes) > 1 else ''} : " + ", ".join(morceaux)


def dessiner(image, message):
    """Copie de l'image avec le cadre, le numéro et la distance de chaque personne (OpenCV) ; vert : la
    personne regarde le robot, orange : non. Étiquettes au-dessus du cadre, ou dedans si la place est
    prise par un cadre voisin."""
    import cv2
    sortie = image.copy()
    prises = []
    for p in message["personnes"]:
        x0, y0, x1, y1 = (int(round(v)) for v in p["boite"])
        couleur = (80, 200, 60) if p.get("regarde_robot") else (40, 160, 240)
        cv2.rectangle(sortie, (x0, y0), (x1, y1), couleur, 2)
        texte = f"{p['id']}  {p['distance_m']:.1f} m".replace(".", ",")      # OpenCV : ASCII seulement
        (largeur, hauteur), _ = cv2.getTextSize(texte, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
        x = max(0, min(x0, sortie.shape[1] - largeur - 6))        # jamais coupée au bord de l'image
        for y in (y0 - 6, y0 + hauteur + 4, y1 - 6):
            rect = (x, y - hauteur - 3, x + largeur + 6, y + 3)
            if y - hauteur > 0 and not any(rect[0] < r[2] and r[0] < rect[2] and rect[1] < r[3] and r[1] < rect[3]
                                           for r in prises):
                break
        prises.append(rect)
        cv2.rectangle(sortie, (rect[0], rect[1]), (rect[2], rect[3]), couleur, -1)
        cv2.putText(sortie, texte, (x + 3, y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (20, 20, 20), 1, cv2.LINE_AA)
    return sortie


# ---------------------------------------------------------------- sources d'images

class SourceRobot:
    """La dernière image de /camera_poitrine/image/compressed (abonnement du nœud ROS 2)."""

    def __init__(self, noeud, sujet=SUJET_ENTREE):
        from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
        from sensor_msgs.msg import CompressedImage
        self.sujet = sujet
        self._verrou = threading.Lock()
        self._derniere = None          # (numéro, octets, temps)
        self._numero = 0
        qos = QoSProfile(depth=2, reliability=ReliabilityPolicy.BEST_EFFORT, history=HistoryPolicy.KEEP_LAST)
        noeud.create_subscription(CompressedImage, sujet, self._recevoir, qos)

    def _recevoir(self, msg):
        donnees = msg.data
        octets = donnees.tobytes() if hasattr(donnees, "tobytes") else bytes(donnees)
        with self._verrou:
            self._numero += 1
            self._derniere = (self._numero, octets, msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9)

    def prendre(self, apres=0):
        """(numéro, image BGR, temps) de la dernière image si elle est plus récente que « apres »."""
        import cv2
        import numpy as np
        with self._verrou:
            derniere = self._derniere
        if derniere is None or derniere[0] <= apres:
            return None
        image = cv2.imdecode(np.frombuffer(derniere[1], np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            return None
        return derniere[0], image, derniere[2]

    def fermer(self):
        pass


def regler_exposition_auto(chemin):
    """See3CAM : l'exposition automatique (elle démarre en manuel, image noire dans une pièce sombre).
    Renvoie le texte de ce qui a été fait, ou None."""
    try:
        sortie = subprocess.run(["v4l2-ctl", "-d", chemin, "--list-ctrls-menus"], capture_output=True,
                                text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if sortie.returncode != 0 or "auto_exposure" not in sortie.stdout:
        return None
    sys.path.insert(0, str(RACINE / "ws" / "src" / "g1_equipe"))
    try:
        from g1_equipe.image_jpeg import commandes_exposition, reglages_camera
    except ImportError:
        return None
    appels, _ = commandes_exposition(reglages_camera(sortie.stdout), "auto")
    for appel in appels:
        subprocess.run(["v4l2-ctl", "-d", chemin, "-c", ",".join(appel)], capture_output=True, timeout=5)
    return ", ".join(",".join(a) for a in appels) or None


class SourceLocale:
    """Une caméra de ce PC (numéro ou /dev/…), une vidéo ou une image (répétée), lue par OpenCV.
    Les caméras sont lues en continu par un fil : on analyse toujours la dernière image."""

    def __init__(self, source, camera, noeud=None):
        import cv2
        self.cv2 = cv2
        self.noeud = noeud
        self.sujet = None
        self._image_fixe = None
        self._capture = None
        self._verrou = threading.Lock()
        self._derniere = None
        self._numero = 0
        self._fin = threading.Event()
        self._fil = None
        texte = str(source)
        if Path(texte).suffix.lower() in EXTENSIONS_IMAGES:
            image = cv2.imread(texte)
            if image is None:
                raise Erreur(f"image {texte} illisible")
            self._image_fixe = image
            self.description = f"image {texte}"
            return
        cam = (camera or {}).get("camera") or {}
        appareil = int(texte) if texte.isdigit() else texte
        if isinstance(appareil, int) or texte.startswith("/dev/"):
            chemin = f"/dev/video{appareil}" if isinstance(appareil, int) else texte
            fait = regler_exposition_auto(chemin)
            if fait:
                dire(f"{chemin} : exposition automatique ({fait})")
            self._capture = cv2.VideoCapture(chemin, cv2.CAP_V4L2)
            self._capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"YUYV"))
            self._capture.set(cv2.CAP_PROP_FRAME_WIDTH, int(cam.get("largeur") or 1280))
            self._capture.set(cv2.CAP_PROP_FRAME_HEIGHT, int(cam.get("hauteur") or 720))
            self._capture.set(cv2.CAP_PROP_FPS, int(cam.get("ips") or 30))
            self.description = f"caméra {chemin}"
            self.video = False
        else:
            if not Path(texte).is_file():
                raise Erreur(f"source {texte} introuvable : robot, un numéro de caméra, /dev/…, une vidéo ou une image")
            self._capture = cv2.VideoCapture(texte)
            self.description = f"vidéo {texte}"
            self.video = True
        if not self._capture.isOpened():
            raise Erreur(f"{self.description} ne s'ouvre pas (caméra occupée, débranchée, ou fichier illisible)")
        self._fil = threading.Thread(target=self._lire, daemon=True)
        self._fil.start()

    def _lire(self):
        periode = 1.0 / max(1.0, self._capture.get(self.cv2.CAP_PROP_FPS) or 30.0) if self.video else 0.0
        while not self._fin.is_set():
            ok, image = self._capture.read()
            if not ok:
                if self.video:          # vidéo finie : on recommence
                    self._capture.set(self.cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                time.sleep(0.05)
                continue
            with self._verrou:
                self._numero += 1
                self._derniere = (self._numero, image)
            if periode:
                time.sleep(periode)

    def _temps(self):
        if self.noeud is not None:
            return self.noeud.get_clock().now().nanoseconds * 1e-9
        return time.time()

    def prendre(self, apres=0):
        if self._image_fixe is not None:
            return apres + 1, self._image_fixe, self._temps()
        with self._verrou:
            derniere = self._derniere
        if derniere is None or derniere[0] <= apres:
            return None
        return derniere[0], derniere[1], self._temps()

    def fermer(self):
        self._fin.set()
        if self._fil is not None:
            self._fil.join(timeout=2)
        if self._capture is not None:
            self._capture.release()


# ---------------------------------------------------------------- ROS 2

class Publieur:
    """Le nœud ROS 2 g1_visiteurs : publie /visiteurs/detectes (et l'image avec les cadres), et
    tourne dans un fil pour recevoir les images du robot."""

    def __init__(self, nom="g1_visiteurs"):
        import rclpy
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
        from sensor_msgs.msg import CompressedImage
        from std_msgs.msg import String
        self.rclpy = rclpy
        self.contexte = rclpy.Context()
        rclpy.init(context=self.contexte)
        self.noeud = rclpy.create_node(nom, context=self.contexte)
        self.String, self.CompressedImage = String, CompressedImage
        self.pub = self.noeud.create_publisher(String, SUJET_SORTIE, 10)
        capteurs = QoSProfile(depth=2, reliability=ReliabilityPolicy.BEST_EFFORT, history=HistoryPolicy.KEEP_LAST)
        self.pub_image = self.noeud.create_publisher(CompressedImage, SUJET_IMAGE, capteurs)
        self.executeur = SingleThreadedExecutor(context=self.contexte)
        self.executeur.add_node(self.noeud)
        self._fin = threading.Event()
        self._fil = threading.Thread(target=self._tourner, daemon=True)
        self._fil.start()

    def _tourner(self):
        while not self._fin.is_set() and self.contexte.ok():
            try:
                self.executeur.spin_once(timeout_sec=0.05)
            except Exception:       # noqa: BLE001 : contexte fermé pendant l'arrêt
                break

    def publier(self, message):
        self.pub.publish(self.String(data=json.dumps(message, ensure_ascii=False)))

    def publier_image(self, image, temps):
        import array
        import cv2
        ok, jpeg = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 70])
        if not ok:
            return
        msg = self.CompressedImage()
        secondes = int(temps)
        msg.header.stamp.sec, msg.header.stamp.nanosec = secondes, int((temps - secondes) * 1e9)
        msg.header.frame_id = "camera_poitrine"
        msg.format = "jpeg"
        msg.data = array.array("B", jpeg.tobytes())
        self.pub_image.publish(msg)

    def fermer(self):
        self._fin.set()
        self._fil.join(timeout=3)
        self.executeur.shutdown()
        self.noeud.destroy_node()
        try:
            self.rclpy.shutdown(context=self.contexte)
        except Exception:           # noqa: BLE001 : déjà arrêté
            pass


# ---------------------------------------------------------------- boucle

def boucle(detecteur, source, camera, publieur, frequence, image=False, fenetre=False, duree=None,
           une_fois=False, horloge=time.monotonic):
    """Analyse les images de la source à « frequence » Hz au plus ; publie chaque message. Renvoie
    le dernier message (ou None). duree : arrêt après tant de secondes ; une_fois : une image."""
    periode = 1.0 / float(frequence)
    debut = horloge()
    dernier_numero, dernier_message = 0, None
    prochaine_image = 0.0
    prochain_resume = debut + 2.0
    sans_image_depuis = debut
    averti = False
    while duree is None or horloge() - debut < duree:
        tour = horloge()
        item = source.prendre(dernier_numero)
        if item is None:
            if not averti and tour - sans_image_depuis > 5.0:
                dire(f"aucune image de {getattr(source, 'description', None) or source.sujet} depuis 5 s "
                     "(nœud camera_usb lancé ? même ROS_DOMAIN_ID ?)")
                averti = True
            time.sleep(min(periode, 0.02))
            continue
        numero, vue, temps = item
        dernier_numero, sans_image_depuis, averti = numero, tour, False
        message, _ = analyser_image(detecteur, vue, camera, temps, numero, source.sujet)
        dernier_message = message
        if publieur is not None:
            publieur.publier(message)
            if image and tour >= prochaine_image:
                publieur.publier_image(dessiner(vue, message), temps)
                prochaine_image = tour + 1.0 / FREQUENCE_IMAGE_HZ
        if fenetre:
            import cv2
            cv2.imshow("Visiteurs (q pour quitter)", dessiner(vue, message))
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
        if une_fois:
            break
        if tour >= prochain_resume:
            dire(resume(message))
            prochain_resume = tour + 2.0
        reste = periode - (horloge() - tour)
        if reste > 0:
            time.sleep(reste)
    return dernier_message


def analyseur():
    p = argparse.ArgumentParser(prog="g1-visiteurs", add_help=False,
                                description="Visiteurs vus par la caméra de poitrine (YOLO pose et ByteTrack), "
                                            "publiés sur /visiteurs/detectes (section 12.7 du plan).")
    p.add_argument("-h", "--help", action="help", help="affiche cette aide et quitte")
    p.add_argument("--lieu", help="id ou dossier du lieu : camera.yaml (position et champ de la caméra, détection)")
    p.add_argument("--source", default="robot",
                   help="robot (défaut : /camera_poitrine/image/compressed), un numéro de caméra (2 = /dev/video2), "
                        "/dev/v4l/by-id/…, une vidéo ou une image")
    p.add_argument("--image", action="store_true", help="publie aussi l'image avec les cadres (/visiteurs/image/compressed)")
    p.add_argument("--fenetre", action="store_true", help="montre l'image et les cadres (touche q pour quitter)")
    p.add_argument("--modele", help=f"modèle de pose YOLO (défaut : camera.yaml, sinon {MODELE_DEFAUT})")
    p.add_argument("--frequence", type=float, help="analyses par seconde au plus (défaut : camera.yaml, sinon 10)")
    p.add_argument("--confiance", type=float, help="confiance minimale, de 0 à 1 (défaut : camera.yaml, sinon 0,5)")
    p.add_argument("--appareil", default="auto", help="auto (carte graphique s'il y en a une), cpu, ou 0")
    p.add_argument("--une-fois", action="store_true", help="analyse une seule image, affiche le message (JSON) et s'arrête")
    p.add_argument("--duree", type=float, help="s'arrête après tant de secondes (essais)")
    p.add_argument("--sans-ros", action="store_true", help="sans ROS 2 : rien n'est publié (avec --une-fois)")
    return p


def main(argv=None):
    args = analyseur().parse_args(argv)
    try:
        camera, origine = lire_camera(args.lieu)
        det = camera.get("detection") or {}
        if not det.get("actif", True):
            dire("attention : camera.yaml dit detection.actif = false (détection désactivée) ; on détecte quand même")
        frequence = float(args.frequence if args.frequence is not None else det.get("frequence_hz") or 10.0)
        if not 0 < frequence <= 60:
            raise Erreur(f"--frequence {frequence:g} : plus que 0 et au plus 60")
        confiance = args.confiance if args.confiance is not None else float(det.get("confiance_min", 0.5))
        if not 0 <= confiance <= 1:
            raise Erreur(f"--confiance {confiance:g} : de 0 à 1")
        if confiance != det.get("confiance_min"):
            camera = dict(camera, detection=dict(det, confiance_min=confiance))
        if args.source == "robot" and args.sans_ros:
            raise Erreur("--source robot demande ROS 2 (sans --sans-ros)")
        chemin = trouver_modele(args.modele or det.get("modele") or MODELE_DEFAUT)
        dire(f"réglages : {origine} ; source {args.source} ; {frequence:g} Hz au plus ; confiance {confiance:g}")
        detecteur = Detecteur.charger(chemin, confiance, args.appareil)
        publieur = None if args.sans_ros else Publieur()
        source = None
        try:
            if args.source == "robot":
                source = SourceRobot(publieur.noeud)
                dire(f"lit {SUJET_ENTREE} (domaine {os.environ.get('ROS_DOMAIN_ID', '0')}) ; publie {SUJET_SORTIE}"
                     + (f" et {SUJET_IMAGE}" if args.image else ""))
            else:
                source = SourceLocale(args.source, camera, publieur.noeud if publieur else None)
                dire(f"lit {source.description}" + ("" if publieur is None else f" ; publie {SUJET_SORTIE}"))
            message = boucle(detecteur, source, camera, publieur, frequence, args.image, args.fenetre,
                             args.duree if not args.une_fois else (args.duree or 60.0), args.une_fois)
            if args.une_fois:
                if message is None:
                    raise Erreur("aucune image reçue")
                print(json.dumps(message, ensure_ascii=False))
                dire(resume(message))
        finally:
            if source is not None:
                source.fermer()
            if publieur is not None:
                publieur.fermer()
            if args.fenetre:
                import cv2
                cv2.destroyAllWindows()
    except Erreur as e:
        print(f"g1-visiteurs : {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
