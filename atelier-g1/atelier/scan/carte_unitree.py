"""g1-scan carte-unitree : récupérer la carte d'Unitree (le .pcd du repérage) par ROS 2 (vague 5, section 12.5).

D'après une documentation non officielle du G1, le service de cartographie publie sa carte globale
**une fois**, sur /unitree/slam_relocation/global_map (sensor_msgs/PointCloud2), après le début d'un
repérage 1804. La commande s'abonne avant (QoS fiable, avec et sans transient_local, et au mieux),
attend au plus --delai secondes, puis écrit dans le lieu :
  cartes/<etage>_unitree.pcd        les points, repère map de l'étage (voir plus bas) ;
  cartes/<etage>_unitree.nuage      le nuage d'affichage (.bin + .json, source unitree, grille de 5 cm,
                                    hauteur au-dessus du plan du sol).
Le repère d'Unitree a son origine au départ du scan ; pour un étage scanné, c'est le repère map
(repere_unitree vaut (0, 0, 0)). Sinon, les points sont ramenés dans map par repere_unitree de l'étage.

Usage (terminal du robot : source ~/robot-g1/setup/robot.sh) :
    g1-scan carte-unitree --lieu L [--etage E] [--delai 60]
puis, pendant l'attente, « Repérer le robot » dans l'Atelier (ou g1-slam relocaliser).
Code 0 si la carte est enregistrée, 1 sinon (le message dit quoi faire). Le faux service de la
répétition (g1-slam faux-service --jumeau) la publie aussi, une fois après chaque 1804 réussi.
"""
import math
import time

import numpy as np

SUJET = "/unitree/slam_relocation/global_map"
DELAI = 60.0
GRILLE = 0.05


def qos_essayees():
    """Les profils de QoS essayés à la fois : (nom, profil). Le profil du vrai publieur est inconnu."""
    from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
    return [("fiable, transient_local", QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                                                   durability=DurabilityPolicy.TRANSIENT_LOCAL)),
            ("fiable", QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                                  durability=DurabilityPolicy.VOLATILE)),
            ("au mieux", QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT,
                                    durability=DurabilityPolicy.VOLATILE))]


def attendre_carte(delai=DELAI, sujet=SUJET, afficher=print):
    """Attend un message du sujet au plus delai secondes. Renvoie (message PointCloud2, QoS) ou (None, None)."""
    import rclpy
    from rclpy.signals import SignalHandlerOptions
    from sensor_msgs.msg import PointCloud2
    contexte = rclpy.Context()
    rclpy.init(context=contexte, signal_handler_options=SignalHandlerOptions.NO)
    recu = []
    try:
        noeud = rclpy.create_node("g1_scan_carte_unitree", context=contexte)
        for nom, profil in qos_essayees():
            noeud.create_subscription(PointCloud2, sujet, lambda msg, nom=nom: recu.append((msg, nom)), profil)
        from rclpy.executors import SingleThreadedExecutor
        executeur = SingleThreadedExecutor(context=contexte)
        executeur.add_node(noeud)
        fin = time.monotonic() + delai
        prochain = time.monotonic() + 10.0
        while not recu and time.monotonic() < fin:
            executeur.spin_once(timeout_sec=0.1)
            if time.monotonic() >= prochain:
                prochain += 10.0
                afficher(f"  … toujours en attente ({fin - time.monotonic():.0f} s restantes)")
        executeur.shutdown()
        noeud.destroy_node()
    finally:
        rclpy.try_shutdown(context=contexte)
    return recu[0] if recu else (None, None)


def vers_carte(points, repere):
    """Points du repère d'Unitree → repère map de l'étage : repere (x, y, theta) est l'origine de la carte
    d'Unitree dans map (atelier.lieu.repere_unitree). z ne change pas."""
    points = np.asarray(points, dtype=float).reshape(-1, 3)
    x0, y0, theta = (float(v) for v in repere)
    c, s = math.cos(theta), math.sin(theta)
    return np.column_stack([x0 + c * points[:, 0] - s * points[:, 1], y0 + s * points[:, 0] + c * points[:, 1],
                            points[:, 2]])


def vers_unitree(points, repere):
    """Points du repère map de l'étage → repère d'Unitree (l'inverse de vers_carte)."""
    points = np.asarray(points, dtype=float).reshape(-1, 3)
    x0, y0, theta = (float(v) for v in repere)
    c, s = math.cos(theta), math.sin(theta)
    dx, dy = points[:, 0] - x0, points[:, 1] - y0
    return np.column_stack([c * dx + s * dy, -s * dx + c * dy, points[:, 2]])


def enregistrer(lieu, etage, points_unitree, afficher=print):
    """Écrit cartes/<etage>_unitree.pcd et cartes/<etage>_unitree.nuage (.bin + .json) depuis les points de la
    carte d'Unitree (repère d'Unitree). Renvoie {pcd, nuage, points, entete}."""
    from atelier.lieu import chemin_nuage, dossier_lieu, repere_unitree
    from atelier.scan import affichage, carte3d, sol as S
    points = np.asarray(points_unitree, dtype=float).reshape(-1, 3)
    points = points[np.isfinite(points).all(axis=1)]
    if len(points) == 0:
        raise ValueError("la carte reçue est vide")
    r = repere_unitree(lieu, etage)
    carte = vers_carte(points, (r.x, r.y, r.theta))
    pcd = dossier_lieu(lieu) / "cartes" / f"{etage}_unitree.pcd"
    pcd.parent.mkdir(parents=True, exist_ok=True)
    carte3d.ecrire_pcd(pcd, carte)
    reduits = affichage.reduire_grille(carte, GRILLE)
    sol = S.trouver_sol(reduits)
    entete = affichage.ecrire_nuage_affichage(chemin_nuage(lieu, etage, "unitree"), reduits, sol, "unitree",
                                              etage=etage, grille=GRILLE)
    afficher(f"Sol de la carte d'Unitree : plan incliné de {sol['inclinaison_deg']:.2f}° ({sol['methode']})")
    return {"pcd": pcd, "nuage": chemin_nuage(lieu, etage, "unitree"), "points": len(carte), "entete": entete}


def commande(lieu, etage=None, delai=DELAI, sujet=SUJET, afficher=print):
    """La commande g1-scan carte-unitree. Renvoie le code de sortie (0 enregistré, 1 sinon)."""
    from atelier.lieu import charger_fiche
    from atelier.scan.carte3d import points_du_nuage
    fiche = charger_fiche(lieu)
    etage = etage or (fiche.etages[0].id if fiche.etages else None)
    if fiche.etage(etage) is None:
        afficher(f"Erreur : le lieu {fiche.dossier} n'a pas d'étage « {etage} » "
                 f"(étages : {', '.join(e.id for e in fiche.etages)})")
        return 1
    afficher(f"Attente de la carte d'Unitree sur {sujet} (au plus {delai:g} s) : lancez « Repérer le robot » "
             "maintenant (Atelier, ou g1-slam relocaliser).")
    msg, qos = attendre_carte(delai, sujet, afficher)
    if msg is None:
        afficher(f"Erreur : aucune carte reçue sur {sujet} en {delai:g} s. Lancez « Repérer le robot » pendant "
                 f"l'attente (la carte n'est publiée qu'une fois, au début du repérage), et vérifiez que ce terminal "
                 "voit le robot (source ~/robot-g1/setup/robot.sh : domaine 0, câble branché).")
        return 1
    try:
        points = points_du_nuage(msg)
        r = enregistrer(lieu, etage, points, afficher)
    except Exception as e:     # noqa: BLE001 : un message clair (ErreurLieu, carte vide…), jamais de trace
        texte = "; ".join(getattr(e, "erreurs", [str(e)]))
        afficher(f"Erreur : carte reçue ({msg.width * msg.height} points, repère « {msg.header.frame_id} », QoS "
                 f"{qos}) mais non enregistrée : {texte}")
        return 1
    afficher(f"Carte d'Unitree reçue ({r['points']} points, repère « {msg.header.frame_id} », QoS {qos}).")
    afficher(f"Écrit : cartes/{etage}_unitree.pcd et cartes/{etage}_unitree.nuage.bin et .json "
             f"({r['entete']['points']} points d'affichage, grille de {GRILLE * 100:g} cm)")
    return 0
