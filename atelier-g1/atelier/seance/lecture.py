"""Lecture du bag d'une séance pour le rapport (vague 6, section 13.3 du plan) : agent Boîte noire.

Le bag est lu directement dans ses fichiers sqlite3 (bag/*.db3, module sqlite3 de Python) : il se lit même sans
metadata.yaml (bag d'un PC qui a planté) ; reindexer() refait ce fichier pour ros2 bag info. Les messages sont
décodés par rclpy (rclpy.serialization) d'après le type noté dans le bag, puis rangés par sujet dans Donnees :
les sujets JSON (std_msgs/String) deviennent des dict, l'odométrie des (t, x, y, cap), la batterie des (t, soc)…

  reindexer(bag)        → True si metadata.yaml existe (refait par rosbag2 s'il manquait)
  infos_bag(bag)        → {sujets: {nom: {type, nombre}}, messages, debut, fin, octets, metadata}
  lire_messages(bag)    → (sujet, type, t en secondes, octets) dans l'ordre du temps
  charger(bag)          → Donnees (vide, avec .erreur, si le bag manque ou est illisible)
"""
import json
import math
import sqlite3
import subprocess
from pathlib import Path

from .enregistreur import taille_dossier

NIVEAU_ERREUR = 40          # rcl_interfaces/msg/Log : ERROR
NIVEAU_AVERTISSEMENT = 30   # WARN


def fichiers_db(bag):
    return sorted(Path(bag).glob("*.db3")) if Path(bag).is_dir() else []


def reindexer(bag):
    """metadata.yaml refait s'il manque (rosbag2_py.Reindexer, sinon « ros2 bag reindex ») ; True s'il existe."""
    bag = Path(bag)
    if (bag / "metadata.yaml").is_file():
        return True
    if not fichiers_db(bag):
        return False
    try:
        import rosbag2_py
        rosbag2_py.Reindexer().reindex(rosbag2_py.StorageOptions(uri=str(bag), storage_id="sqlite3"))
    except Exception:       # noqa: BLE001 : rosbag2_py absent ou en échec : la commande
        try:
            subprocess.run(["ros2", "bag", "reindex", "-s", "sqlite3", str(bag)], stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120, check=False)
        except (OSError, subprocess.SubprocessError):
            pass
    return (bag / "metadata.yaml").is_file()


def _connexion(fichier):
    """Connexion sqlite3 au fichier du bag (en lecture seule si le dossier n'est pas modifiable)."""
    try:
        c = sqlite3.connect(str(fichier), timeout=10)
        c.execute("SELECT 1 FROM topics LIMIT 1")
        return c
    except sqlite3.Error:
        return sqlite3.connect(f"file:{fichier}?mode=ro", uri=True, timeout=10)


def infos_bag(bag):
    """Ce que contient le bag, sans décoder les messages : {sujets: {nom: {type, nombre}}, messages, debut, fin
    (secondes), octets, metadata (metadata.yaml présent)}."""
    sujets, debut, fin, total = {}, None, None, 0
    for fichier in fichiers_db(bag):
        try:
            c = _connexion(fichier)
            try:
                types = {i: (n, t) for i, n, t in c.execute("SELECT id, name, type FROM topics")}
                for ident, nombre, t0, t1 in c.execute(
                        "SELECT topic_id, COUNT(*), MIN(timestamp), MAX(timestamp) FROM messages GROUP BY topic_id"):
                    nom, type_ros = types.get(ident, (f"?{ident}", "?"))
                    s = sujets.setdefault(nom, {"type": type_ros, "nombre": 0, "debut": None, "fin": None})
                    s["nombre"] += nombre
                    s["debut"] = t0 * 1e-9 if s["debut"] is None else min(s["debut"], t0 * 1e-9)
                    s["fin"] = t1 * 1e-9 if s["fin"] is None else max(s["fin"], t1 * 1e-9)
                    total += nombre
                    debut = t0 * 1e-9 if debut is None else min(debut, t0 * 1e-9)
                    fin = t1 * 1e-9 if fin is None else max(fin, t1 * 1e-9)
                for ident, (nom, type_ros) in types.items():
                    sujets.setdefault(nom, {"type": type_ros, "nombre": 0, "debut": None, "fin": None})
            finally:
                c.close()
        except sqlite3.Error:
            continue
    return {"sujets": sujets, "messages": total, "debut": debut, "fin": fin,
            "octets": taille_dossier(bag) if Path(bag).is_dir() else 0,
            "metadata": (Path(bag) / "metadata.yaml").is_file()}


def lire_messages(bag, sujets=None):
    """(sujet, type, t en secondes, octets) de chaque message, dans l'ordre du temps (fichier par fichier)."""
    for fichier in fichiers_db(bag):
        c = _connexion(fichier)
        try:
            types = {i: (n, t) for i, n, t in c.execute("SELECT id, name, type FROM topics")}
            garder = None if sujets is None else {i for i, (n, _) in types.items() if n in sujets}
            for ident, t, donnees in c.execute("SELECT topic_id, timestamp, data FROM messages ORDER BY timestamp"):
                if garder is not None and ident not in garder:
                    continue
                nom, type_ros = types.get(ident, (None, None))
                if nom is not None:
                    yield nom, type_ros, t * 1e-9, bytes(donnees)
        finally:
            c.close()


def _cap(q):
    """Cap (lacet) d'un quaternion de geometry_msgs."""
    return math.atan2(2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y * q.y + q.z * q.z))


def _json(texte):
    try:
        d = json.loads(texte)
    except ValueError:
        return None
    return d if isinstance(d, (dict, list)) else None


class Donnees:
    """Les messages utiles au rapport, par sujet (listes dans l'ordre du temps, t en secondes depuis 1970) :
      json[sujet]      [(t, dict)] des sujets JSON (std_msgs/String) : /guide/etat, /pont/etat, /reperage/etat…
      textes[sujet]    [(t, texte)] des String qui ne sont pas du JSON (/guide/aller avec un id seul…)
      booleens[sujet]  [(t, bool)] (/pont/arret)
      vides[sujet]     [t] (std_msgs/Empty : /guide/stop)
      entiers[sujet]   [(t, n)] (/g1_jumeau/mode)
      odometrie[sujet] [(t, x, y, cap, vx, vy)] (/odom, /g1_jumeau/odom, /state_estimator/odom_pelvis…)
      vitesses[sujet]  [(t, vx, vy, wz)] (/cmd_vel)
      batterie         [(t, soc)] (/lf/bmsstate)
      requetes[sujet]  [(t, id, api_id, parametre)] (/api/<service>/request)
      reponses[sujet]  [(t, id, api_id, code, data)] (/api/<service>/response)
      journal          [(t, niveau, noeud, message)] de /rosout, avertissements et erreurs seulement
      niveaux          {niveau: nombre} de /rosout
      comptes          {sujet: nombre} de tous les sujets du bag
    """

    def __init__(self):
        self.json, self.textes, self.booleens, self.vides, self.entiers = {}, {}, {}, {}, {}
        self.odometrie, self.vitesses, self.requetes, self.reponses = {}, {}, {}, {}
        self.batterie, self.journal = [], []
        self.niveaux, self.comptes = {}, {}
        self.types = {}
        self.debut = self.fin = None
        self.erreur = None
        self.illisibles = 0

    def serie(self, famille, sujet):
        return getattr(self, famille).get(sujet, [])

    def ajouter(self, sujet, type_ros, t, msg):
        """Range un message décodé (fonction utilisée aussi par les tests, sans bag)."""
        self.comptes[sujet] = self.comptes.get(sujet, 0) + 1
        self.types.setdefault(sujet, type_ros)
        self.debut = t if self.debut is None else min(self.debut, t)
        self.fin = t if self.fin is None else max(self.fin, t)
        if type_ros == "std_msgs/msg/String":
            d = _json(msg.data)
            if isinstance(d, dict):
                self.json.setdefault(sujet, []).append((t, d))
            else:
                self.textes.setdefault(sujet, []).append((t, msg.data))
        elif type_ros == "std_msgs/msg/Bool":
            self.booleens.setdefault(sujet, []).append((t, bool(msg.data)))
        elif type_ros == "std_msgs/msg/Empty":
            self.vides.setdefault(sujet, []).append(t)
        elif type_ros in ("std_msgs/msg/Int32", "std_msgs/msg/Int64"):
            self.entiers.setdefault(sujet, []).append((t, int(msg.data)))
        elif type_ros == "nav_msgs/msg/Odometry":
            p, v = msg.pose.pose, msg.twist.twist
            self.odometrie.setdefault(sujet, []).append(
                (t, p.position.x, p.position.y, _cap(p.orientation), v.linear.x, v.linear.y))
        elif type_ros == "geometry_msgs/msg/Twist":
            self.vitesses.setdefault(sujet, []).append((t, msg.linear.x, msg.linear.y, msg.angular.z))
        elif type_ros.endswith("/BmsState"):
            self.batterie.append((t, int(msg.soc)))
        elif type_ros == "unitree_api/msg/Request":
            h = msg.header.identity
            self.requetes.setdefault(sujet, []).append((t, int(h.id), int(h.api_id), msg.parameter))
        elif type_ros == "unitree_api/msg/Response":
            h = msg.header.identity
            self.reponses.setdefault(sujet, []).append((t, int(h.id), int(h.api_id), int(msg.header.status.code),
                                                        msg.data))
        elif type_ros == "rcl_interfaces/msg/Log":
            niveau = int(msg.level)
            self.niveaux[niveau] = self.niveaux.get(niveau, 0) + 1
            if niveau >= NIVEAU_AVERTISSEMENT:
                self.journal.append((t, niveau, msg.name, msg.msg))


# Types décodés pour le rapport ; les autres sont seulement comptés
TYPES_DECODES = ("std_msgs/msg/String", "std_msgs/msg/Bool", "std_msgs/msg/Empty", "std_msgs/msg/Int32",
                 "std_msgs/msg/Int64", "nav_msgs/msg/Odometry", "geometry_msgs/msg/Twist",
                 "unitree_hg/msg/BmsState", "unitree_go/msg/BmsState", "unitree_api/msg/Request",
                 "unitree_api/msg/Response", "rcl_interfaces/msg/Log")


def charger(bag):
    """Les messages du bag décodés et rangés (Donnees). Sans bag, ou sans ROS 2 pour décoder : Donnees vide, avec
    erreur (une phrase en français)."""
    d = Donnees()
    bag = Path(bag)
    if not fichiers_db(bag):
        d.erreur = "pas d'enregistrement ROS 2 dans cette séance"
        return d
    try:
        from rclpy.serialization import deserialize_message
        from rosidl_runtime_py.utilities import get_message
    except ImportError as e:
        d.erreur = f"ROS 2 n'est pas chargé : le bag ne peut pas être décodé ({e})"
        return d
    classes = {}
    try:
        for sujet, type_ros, t, octets in lire_messages(bag):
            if type_ros not in TYPES_DECODES:
                d.comptes[sujet] = d.comptes.get(sujet, 0) + 1
                d.types.setdefault(sujet, type_ros)
                d.debut = t if d.debut is None else min(d.debut, t)
                d.fin = t if d.fin is None else max(d.fin, t)
                continue
            if type_ros not in classes:
                try:
                    classes[type_ros] = get_message(type_ros)
                except Exception:       # noqa: BLE001 : paquet du message absent sur ce PC
                    classes[type_ros] = None
            classe = classes[type_ros]
            if classe is None:
                d.illisibles += 1
                continue
            try:
                d.ajouter(sujet, type_ros, t, deserialize_message(octets, classe))
            except Exception:       # noqa: BLE001 : message abîmé (bag d'un PC qui a planté)
                d.illisibles += 1
    except sqlite3.Error as e:
        d.erreur = f"le bag est abîmé et n'a été lu qu'en partie ({e})"
    return d
