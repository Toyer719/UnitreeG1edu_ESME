"""Position actuelle du robot → nouvelle salle ou nouveau nœud d'itinéraire du lieu.

On amène le robot devant la porte (tourné vers elle), puis :
    g1-salle ajouter "Salle B204" --lieu demo          salle b204 et son nœud
    g1-salle ajouter carrefour_est --type noeud --lieu demo

La position est lue une fois sur /odom (simulation, ou relais de la relocalisation d'Unitree
sur le vrai robot), ou sur un autre sujet nav_msgs/Odometry (--sujet). Les fichiers sont écrits
par atelier.lieu : une salle a toujours un nœud de même id, à la même position, et la salle
« accueil » a la pose d'accueil de lieu.yaml (règles de la section 4.1).
"""
import math
import re
import time
import unicodedata

from atelier import MOTIF_ID
from atelier.lieu import (Noeud, Pose, PoseEtage, Salle, charger_fiche, charger_itineraires, charger_salles,
                          enregistrer_fiche, enregistrer_itineraires, enregistrer_salles, quaternion_vers_cap)

MOTS_RESERVES = ("yes", "no", "on", "off", "true", "false", "null", "y", "n")


def identifiant(nom):
    """Nom en clair → identifiant : « Salle B204 » → « salle_b204 », « Vie scolaire » → « vie_scolaire »."""
    texte = unicodedata.normalize("NFKD", str(nom)).encode("ascii", "ignore").decode().lower()
    texte = re.sub(r"[^a-z0-9_-]+", "_", texte).strip("_-")
    texte = re.sub(r"_+", "_", texte)[:40].strip("_-")
    if not texte or not MOTIF_ID.match(texte):
        raise ValueError(f"impossible de tirer un identifiant de « {nom} » : donnez-le avec --id")
    if texte in MOTS_RESERVES:
        raise ValueError(f"« {texte} » est lu par YAML comme un booléen : donnez un autre id avec --id")
    return texte


def lire_position(sujet="/odom", delai=5.0):
    """Lit un message nav_msgs/Odometry sur ce sujet → (x, y, theta), ou None après « delai » s."""
    import rclpy
    from nav_msgs.msg import Odometry
    from rclpy.context import Context
    from rclpy.executors import SingleThreadedExecutor
    from rclpy.qos import qos_profile_sensor_data

    contexte = Context()
    rclpy.init(context=contexte)
    recu = []
    try:
        noeud = rclpy.create_node("g1_salle", context=contexte)
        # Profil « capteur » (best effort) : accepte aussi les éditeurs fiables
        noeud.create_subscription(Odometry, sujet, recu.append, qos_profile_sensor_data)
        executeur = SingleThreadedExecutor(context=contexte)
        executeur.add_node(noeud)
        fin = time.monotonic() + delai
        while not recu and time.monotonic() < fin:
            executeur.spin_once(timeout_sec=0.1)
        noeud.destroy_node()
    finally:
        rclpy.shutdown(context=contexte)
    if not recu:
        return None
    p = recu[0].pose.pose
    return (p.position.x, p.position.y, quaternion_vers_cap(p.orientation))


def _noeud_proche(itineraires, etage, x, y, sauf):
    proches = [(math.hypot(n.x - x, n.y - y), i) for i, n in itineraires.noeuds.items()
               if n.etage == etage and i != sauf]
    return min(proches) if proches else None


def ajouter(lieu, nom, pose, type_="salle", etage=None, id_=None, alias=(), phrase=None):
    """Ajoute (ou déplace) une salle ou un nœud à la pose (x, y, theta).

    Renvoie {"id", "messages"} ; lève ErreurLieu (fichier invalide) ou ValueError.
    """
    if type_ not in ("salle", "noeud"):
        raise ValueError("type : salle ou noeud")
    fiche = charger_fiche(lieu)
    etage = etage or fiche.etages[0].id
    if fiche.etage(etage) is None:
        raise ValueError(f"le lieu n'a pas d'étage « {etage} » (étages : {', '.join(e.id for e in fiche.etages)})")
    id_ = id_ or identifiant(nom)
    if not MOTIF_ID.match(id_) or id_ in MOTS_RESERVES:
        raise ValueError(f"identifiant « {id_} » invalide : lettres minuscules, chiffres, _ et -, 40 au plus")
    x, y, theta = (round(float(v), 3) for v in pose)
    messages = []
    salles = charger_salles(lieu)
    itineraires = charger_itineraires(lieu)
    salle = next((s for s in salles if s.id == id_), None)
    ou = f"en ({x:.2f} ; {y:.2f}), cap {theta:.2f} rad, étage {etage}"

    if type_ == "salle" or salle is not None:
        if salle is None:
            salle = Salle(id_, str(nom), etage, Pose(x, y, theta), alias=list(alias),
                          phrase_arrivee=phrase or "")
            salles.append(salle)
            messages.append(f"Salle « {salle.nom} » ({id_}) ajoutée {ou}.")
        else:
            if type_ == "noeud":
                theta = salle.pose.theta          # un nœud n'a pas de cap : on garde celui de la salle
                ou = f"en ({x:.2f} ; {y:.2f}), étage {etage}"
            salle.etage, salle.pose = etage, Pose(x, y, theta)
            if type_ == "salle" and str(nom) != id_:
                salle.nom = str(nom)
            salle.alias += [a for a in alias if a not in salle.alias]
            if phrase is not None:
                salle.phrase_arrivee = phrase
            messages.append(f"Salle « {salle.nom} » ({id_}) déplacée {ou}.")
        enregistrer_salles(lieu, salles)
        if id_ == "accueil":
            fiche.accueil = PoseEtage(etage, x, y, salle.pose.theta)
            enregistrer_fiche(fiche)
            messages.append("Pose d'accueil de lieu.yaml mise à jour.")

    deja = id_ in itineraires.noeuds
    itineraires.noeuds[id_] = Noeud(etage, x, y)
    enregistrer_itineraires(lieu, itineraires)
    messages.append(f"Nœud {id_} {'déplacé' if deja else 'ajouté'} dans itineraires.yaml"
                    + (f" {ou}." if type_ == "noeud" and salle is None else "."))
    proche = _noeud_proche(itineraires, etage, x, y, id_)
    relie = any(id_ in (c.a, c.b) for c in itineraires.couloirs)
    if proche and not relie:
        messages.append(f"Nœud le plus proche : {proche[1]}, à {proche[0]:.1f} m. Reliez-les par un couloir "
                        "(Atelier, onglet Itinéraires), 8 m au plus.")
    return {"id": id_, "messages": messages}
