"""Outils communs des essais de la boîte noire (vague 6, section 13.3 du plan) : agent Boîte noire. Ce fichier ne
contient aucun test.

Une séance d'essai, écrite d'une seule source (scenario) de deux façons :
  - donnees_essai(t0)            les messages rangés dans atelier.seance.lecture.Donnees, sans ROS (analyse pure) ;
  - seance_essai(racine, t0)     un vrai dossier de séance : seance.json, actions.jsonl, lieu/ (copie du demo), et
                                 un bag rosbag2 écrit avec rosbag2_py (si ROS 2 est chargé ; sinon pas de bag).
Le scénario, dans le lieu demo (accueil (2,5 ; 10), b204 (21 ; 13), cdi (23 ; 7)) :
  0 s     séance ouverte ; robot à l'accueil, pas repéré ; verrou du pont faux (état d'avant, transient_local)
  5 s     « Repérer le robot » → repéré à 6 s (précision 2 à 4 cm)
  10 s    « Y aller : Salle B204 » → en route à 10,5 s, bloqué de 40 à 43 s, arrivé à 70 s (19,2 m)
  75 s    « Y aller : CDI » → en route ; 85 s : ARRÊT (verrou posé à 85,05 s) → attente, trajet interrompu
  95 s    « Débloquer » ; 100 s : « Y aller : Accueil » → arrivé à 150 s
  130 s   PUT …/salles refusé (422) ; 120 s : une erreur de controller_server sur /rosout
  160 s   le robot bouge seul 5 s (1,5 m) : /cmd_vel et ordres 7105 non nuls, sans mission du guide
  170 s   fin ; batterie 87 % → 85 %
"""
import json
import math
from types import SimpleNamespace

from atelier.lieu import copier_lieu
from atelier.seance import manifeste as M
from atelier.seance.lecture import Donnees

ACCUEIL, COIN, B204, CDI = (2.5, 10.0), (9.0, 13.0), (21.0, 13.0), (23.0, 7.0)
DUREE = 170.0
DISTANCE_B204 = math.dist(ACCUEIL, COIN) + math.dist(COIN, B204)     # 19,16 m


def _sur(a, b, f):
    return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)


def _le_long(points, f):
    """Le point à la fraction f (0 à 1) de la ligne brisée points."""
    longueurs = [math.dist(points[i], points[i + 1]) for i in range(len(points) - 1)]
    reste = max(0.0, min(1.0, f)) * sum(longueurs)
    for i, lg in enumerate(longueurs):
        if reste <= lg or i == len(longueurs) - 1:
            return _sur(points[i], points[i + 1], reste / lg if lg else 0.0)
        reste -= lg
    return points[-1]


ARRET_CDI = _sur(B204, CDI, 2.0 / math.dist(B204, CDI))       # ARRÊT après 2 m vers le cdi


def position(dt):
    """(x, y) du robot dt secondes après l'ouverture de la séance."""
    if dt < 10.5:
        return ACCUEIL
    if dt < 70.0:
        return _le_long([ACCUEIL, COIN, B204], (dt - 10.5) / (70.0 - 10.5))
    if dt < 75.5:
        return B204
    if dt < 85.0:
        return _sur(B204, ARRET_CDI, (dt - 75.5) / (85.0 - 75.5))
    if dt < 100.5:
        return ARRET_CDI
    if dt < 150.0:
        return _le_long([ARRET_CDI, B204, COIN, ACCUEIL], (dt - 100.5) / (150.0 - 100.5))
    if dt < 160.0:
        return ACCUEIL
    if dt < 165.0:
        return (ACCUEIL[0] + 0.3 * (dt - 160.0), ACCUEIL[1])
    return (ACCUEIL[0] + 1.5, ACCUEIL[1])


def etat_guide(dt):
    if dt < 10.5:
        return {"etat": "attente", "cible": None, "mission": None}
    if dt < 70.0:
        return {"etat": "bloque" if 40.0 <= dt < 43.0 else "en_route", "cible": "b204", "mission": "visite"}
    if dt < 75.5:
        return {"etat": "arrive", "cible": "b204", "mission": "visite"}
    if dt < 85.1:
        return {"etat": "en_route", "cible": "cdi", "mission": "visite"}
    if dt < 100.5:
        d = {"etat": "attente", "cible": None, "mission": None}
        if dt < 95.2:
            d.update(immobilise="verrou", message="Robot bloqué : le trajet vers « CDI » est annulé.")
        return d
    if dt < 150.0:
        return {"etat": "en_route", "cible": "accueil", "mission": "visite"}
    return {"etat": "arrive", "cible": "accueil", "mission": "visite"}


def en_mouvement(dt):
    return 10.5 <= dt < 70 and not 40 <= dt < 43 or 75.5 <= dt < 85 or 100.5 <= dt < 150 or 160 <= dt < 165


def scenario(t0):
    """Les messages de la séance d'essai : [(sujet, type, t, valeur)], valeur en Python simple."""
    ev = []

    def tous(periode, debut=0.0, fin=DUREE):
        k = 0
        while debut + k * periode <= fin:
            yield debut + k * periode
            k += 1
    for dt in tous(0.2):
        x, y = position(dt)
        repere = dt >= 6.0
        ev.append(("/reperage/etat", "json", t0 + dt, {
            "version": 1, "etat": "repere" if repere else "non_repere", "repere": repere, "localisation": "unitree",
            "message": "", "pose": {"x": x, "y": y, "theta": 0.0} if repere else None,
            "precision_m": (0.02 + 0.02 * (int(dt) % 2)) if repere else None, "age_s": 0.1, "demande": None,
            "carte": "repetition.pcd", "repere_unitree": {"x": 2.5, "y": 10.0, "theta": 0.0}, "sauts": 0}))
        g = etat_guide(dt)
        g.update(version=1, reste_m=None, itineraire=[], actif=g["etat"] not in ("attente", "arrive"))
        ev.append(("/guide/etat", "json", t0 + dt, g))
    for dt in tous(0.1):
        x, y = position(dt)
        ev.append(("/g1_jumeau/odom", "odom", t0 + dt, (x, y)))
    for dt in tous(0.5):
        verrou = 85.05 <= dt < 95.2
        etat = "arret_verrouille" if verrou else ("en_mouvement" if en_mouvement(dt) else "pret")
        ev.append(("/pont/etat", "json", t0 + dt, {"version": 1, "etat": etat, "verrou": verrou,
                                                   "mode_robot": {"fsm": 501, "nom": "marche", "en_marche": True,
                                                                  "age_s": 0.4}}))
    ev.append(("/pont/arret", "bool", t0 + 0.3, False))
    ev.append(("/pont/arret", "bool", t0 + 85.05, True))
    ev.append(("/pont/arret", "bool", t0 + 95.2, False))
    for dt in tous(1.0):
        ev.append(("/lf/bmsstate", "batterie", t0 + dt, 87 - int(2 * dt / DUREE)))
        ev.append(("/api/sport/request", "requete", t0 + dt + 0.05, (7001, "{}")))
        ev.append(("/api/sport/response", "reponse", t0 + dt + 0.07, (7001, 0, json.dumps({"data": 501}))))
    for dt in tous(0.1):
        if en_mouvement(dt):
            ev.append(("/api/sport/request", "requete", t0 + dt + 0.01,
                       (7105, json.dumps({"velocity": [0.3, 0.0, 0.0], "duration": 0.5}))))
            ev.append(("/cmd_vel", "vitesse", t0 + dt, (0.3, 0.0, 0.0)))
    for code, dt, salle in (("depart", 10.6, "b204"), ("arrivee", 70.0, "b204"), ("depart", 75.6, "cdi"),
                            ("arret", 85.1, None), ("immobilise", 85.15, None), ("depart", 100.6, "accueil"),
                            ("arrivee", 150.0, "accueil")):
        e = {"version": 1, "code": code, "texte": "…", "salle": salle}
        if code == "immobilise":
            e["raison"] = "verrou"
        ev.append(("/guide/evenement", "json", t0 + dt, e))
    ev.append(("/rosout", "journal", t0 + 120.0, (40, "controller_server", "Failed to make progress")))
    ev.append(("/rosout", "journal", t0 + 121.0, (20, "bt_navigator", "Begin navigating")))
    ev.sort(key=lambda e: e[2])
    return ev


def actions_essai(t0):
    """Les lignes de actions.jsonl de la séance d'essai (déjà décrites, comme les écrit la boîte noire)."""
    from atelier.seance.actions import ligne_action
    noms = {"accueil": "Accueil", "b204": "Salle B204", "cdi": "CDI"}
    brutes = [
        (0.2, "POST", "/api/seance/demarrer", {"mode": "repetition", "ouverture": "auto"}, 200, {"seance": {}}),
        (5.0, "POST", "/api/robot/reperer", {"lieu": "essai", "etage": "rdc"}, 200, {"repere": True}),
        (10.0, "POST", "/api/guide/aller", {"cible": "b204"}, 200, {"envoye": "b204", "ecoute": 1}),
        (75.0, "POST", "/api/guide/aller", {"cible": "cdi"}, 200, {"envoye": "cdi", "ecoute": 1}),
        (85.0, "POST", "/api/arret", {"mode": "repetition"}, 200, {"arrete": True, "verrou": True}),
        (95.0, "POST", "/api/arret/debloquer", None, 200, {"verrou": False}),
        (100.0, "POST", "/api/guide/aller", {"cible": "accueil"}, 200, {"envoye": "accueil", "ecoute": 1}),
        (130.0, "PUT", "/api/lieux/essai/salles", "pas du JSON", 422,
         {"detail": "salles.yaml n'a pas été enregistré : corrigez les points ci-dessous."}),
    ]
    return [ligne_action({"t": M.heure_iso(t0 + dt, ms=True), "methode": m, "chemin": c, "requete": q, "statut": s,
                          "reponse": r, "duree_ms": 12.0, "client": "local"}, t0, "repetition", noms)
            for dt, m, c, q, s, r in brutes]


def _faux_message(genre, valeur):
    """Un message décodé « comme rclpy », sans ROS (attributs seulement)."""
    N = SimpleNamespace
    if genre == "json":
        return N(data=json.dumps(valeur))
    if genre == "bool":
        return N(data=valeur)
    if genre == "odom":
        x, y = valeur
        return N(pose=N(pose=N(position=N(x=x, y=y, z=0.0), orientation=N(x=0.0, y=0.0, z=0.0, w=1.0))),
                 twist=N(twist=N(linear=N(x=0.0, y=0.0, z=0.0))))
    if genre == "batterie":
        return N(soc=valeur)
    if genre == "requete":
        api, parametre = valeur
        return N(header=N(identity=N(id=1, api_id=api)), parameter=parametre)
    if genre == "reponse":
        api, code, data = valeur
        return N(header=N(identity=N(id=1, api_id=api), status=N(code=code)), data=data)
    if genre == "vitesse":
        vx, vy, wz = valeur
        return N(linear=N(x=vx, y=vy, z=0.0), angular=N(x=0.0, y=0.0, z=wz))
    if genre == "journal":
        niveau, nom, texte = valeur
        return N(level=niveau, name=nom, msg=texte)
    raise ValueError(genre)


TYPES = {"json": "std_msgs/msg/String", "bool": "std_msgs/msg/Bool", "odom": "nav_msgs/msg/Odometry",
         "batterie": "unitree_hg/msg/BmsState", "requete": "unitree_api/msg/Request",
         "reponse": "unitree_api/msg/Response", "vitesse": "geometry_msgs/msg/Twist",
         "journal": "rcl_interfaces/msg/Log"}


def donnees_essai(t0):
    """La séance d'essai rangée dans Donnees, sans ROS."""
    d = Donnees()
    for sujet, genre, t, valeur in scenario(t0):
        d.ajouter(sujet, TYPES[genre], t, _faux_message(genre, valeur))
    return d


def _vrai_message(genre, valeur):
    """Le même message en vrai type ROS 2 (pour écrire un bag)."""
    if genre == "json":
        from std_msgs.msg import String
        return String(data=json.dumps(valeur))
    if genre == "bool":
        from std_msgs.msg import Bool
        return Bool(data=valeur)
    if genre == "odom":
        from nav_msgs.msg import Odometry
        m = Odometry()
        m.pose.pose.position.x, m.pose.pose.position.y = valeur
        m.pose.pose.orientation.w = 1.0
        return m
    if genre == "batterie":
        from unitree_hg.msg import BmsState
        return BmsState(soc=valeur)
    if genre == "requete":
        from unitree_api.msg import Request
        m = Request()
        m.header.identity.id, m.header.identity.api_id = 1, valeur[0]
        m.parameter = valeur[1]
        return m
    if genre == "reponse":
        from unitree_api.msg import Response
        m = Response()
        m.header.identity.id, m.header.identity.api_id = 1, valeur[0]
        m.header.status.code = valeur[1]
        m.data = valeur[2]
        return m
    if genre == "vitesse":
        from geometry_msgs.msg import Twist
        m = Twist()
        m.linear.x, m.linear.y, m.angular.z = valeur
        return m
    if genre == "journal":
        from rcl_interfaces.msg import Log
        return Log(level=valeur[0], name=valeur[1], msg=valeur[2])
    raise ValueError(genre)


def ros_disponible():
    try:
        import rclpy  # noqa: F401
        import rosbag2_py  # noqa: F401
        import unitree_api.msg  # noqa: F401
        import unitree_hg.msg  # noqa: F401
    except ImportError:
        return False
    return True


def ecrire_bag(dossier_bag, t0, sans_metadata=False):
    """Le bag de la séance d'essai (rosbag2_py, sqlite3) ; sans_metadata : comme après un plantage."""
    import rosbag2_py
    from rclpy.serialization import serialize_message
    w = rosbag2_py.SequentialWriter()
    w.open(rosbag2_py.StorageOptions(uri=str(dossier_bag), storage_id="sqlite3"),
           rosbag2_py.ConverterOptions("cdr", "cdr"))
    crees = set()
    for sujet, genre, t, valeur in scenario(t0):
        if sujet not in crees:
            w.create_topic(rosbag2_py.TopicMetadata(sujet, TYPES[genre], "cdr", ""))
            crees.add(sujet)
        w.write(sujet, serialize_message(_vrai_message(genre, valeur)), int(t * 1e9))
    w.close()
    if sans_metadata:
        (dossier_bag / "metadata.yaml").unlink()


def seance_essai(racine, t0, avec_bag=True, etat="fermee", sans_metadata=False, demo=None):
    """Un dossier de séance d'essai complet dans racine ; renvoie son dossier."""
    from pathlib import Path
    from atelier.seance import copier_lieu as copier_fichiers_lieu
    ident = "2026-11-12_14h03"
    dossier = Path(racine) / ident
    dossier.mkdir(parents=True)
    m = M.nouveau_manifeste(ident, "repetition", "essai", "rdc", "auto", debut=t0, port=8142)
    if etat != "ouverte":
        m.update(etat=etat, fin=M.heure_iso(t0 + DUREE), duree_s=DUREE,
                 fermeture="terminer" if etat == "fermee" else "plantage")
        m["enregistrement"].update(etat="arrete", octets=1000)
    lignes = actions_essai(t0)
    m["actions"] = len(lignes)
    M.ecrire_manifeste(dossier, m)
    with open(dossier / "actions.jsonl", "w", encoding="utf-8") as f:
        for ligne in lignes:
            f.write(json.dumps(ligne, ensure_ascii=False) + "\n")
    if demo is not None:
        source = Path(racine) / "_demo"
        if not source.exists():
            copier_lieu(demo, source)
        copier_fichiers_lieu(source, dossier / "lieu", "rdc")
    if avec_bag:
        ecrire_bag(dossier / "bag", t0, sans_metadata)
    return dossier
