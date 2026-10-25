"""Sessions de scan d'exemple, sans ROS, sans Gazebo ni robot (contrats de la section 9 du plan).

    from atelier.tests.outils_scan import creer_session_exemple
    s = creer_session_exemple(copie_du_demo, etat="termine")

La session est tirée du monde du lieu, comme si le scan avait été parfait : la carte du scan est
celle du monde, le nuage est fait de points posés sur les murs et les objets, et la reconnaissance
est la vérité terrain (atelier.lieu.reconnaissance_depuis_monde). Tous les fichiers respectent
les formats du contrat : les agents Interface et Testeur peuvent s'en servir avant que g1-scan
et la reconnaissance soient prêts. À n'utiliser que sur une copie d'un lieu (jamais lieux/demo).

Aussi en ligne de commande, pour regarder les fichiers :
    .venv-projet/bin/python -m atelier.tests.outils_scan DOSSIER_DU_LIEU [etat]
"""
import json
import math
import struct
import sys
import zlib
from pathlib import Path

import numpy as np

from atelier import lieu as L

ETATS_EXEMPLE = ("en_cours", "traitement", "termine", "echec")


def ecrire_png_gris(chemin, image):
    """Écrit un tableau (hauteur, largeur) uint8 en PNG niveaux de gris, sans bibliothèque d'image."""
    image = np.asarray(image, dtype=np.uint8)
    hauteur, largeur = image.shape

    def bloc(genre, donnees):
        return (struct.pack(">I", len(donnees)) + genre + donnees
                + struct.pack(">I", zlib.crc32(genre + donnees) & 0xFFFFFFFF))
    lignes = b"".join(b"\x00" + image[i].tobytes() for i in range(hauteur))
    octets = (b"\x89PNG\r\n\x1a\n" + bloc(b"IHDR", struct.pack(">IIBBBBB", largeur, hauteur, 8, 0, 0, 0, 0))
              + bloc(b"IDAT", zlib.compress(lignes, 6)) + bloc(b"IEND", b""))
    L.ecrire_atomique(chemin, octets)


def ecrire_pcd_ascii(chemin, points):
    """Nuage (N, 3) en PCD ASCII (champs x y z), lisible par Open3D et atelier.scan.carte3d."""
    points = np.asarray(points, dtype=float).reshape(-1, 3)
    entete = (f"# .PCD v0.7 - Atelier G1 (exemple)\nVERSION 0.7\nFIELDS x y z\nSIZE 4 4 4\nTYPE F F F\n"
              f"COUNT 1 1 1\nWIDTH {len(points)}\nHEIGHT 1\nVIEWPOINT 0 0 0 1 0 0 0\nPOINTS {len(points)}\n"
              "DATA ascii\n")
    corps = "\n".join(f"{x:.3f} {y:.3f} {z:.3f}" for x, y, z in points)
    L.ecrire_atomique(chemin, entete + corps + "\n")


def _points_occupes(info, image, pas=1):
    lignes, colonnes = np.nonzero(image == 0)
    x, y = L.pixel_vers_monde(colonnes[::pas], lignes[::pas], info)
    return np.asarray(x, dtype=float), np.asarray(y, dtype=float)


def _trajectoire(lieu, etage, pas=0.25):
    """Tour des couloirs de l'étage (nœuds dans l'ordre du graphe), un point tous les pas mètres."""
    itin = L.charger_itineraires(lieu)
    noeuds = [(i, n) for i, n in itin.noeuds.items() if n.etage == etage]
    if len(noeuds) < 2:
        monde = L.charger_monde(lieu, etage)
        return [[monde.depart_robot.x, monde.depart_robot.y, monde.depart_robot.theta]]
    points = []
    suite = [n for _, n in noeuds] + [noeuds[0][1]]
    for a, b in zip(suite, suite[1:]):
        longueur = math.hypot(b.x - a.x, b.y - a.y)
        cap = math.atan2(b.y - a.y, b.x - a.x)
        for k in range(max(1, int(longueur / pas))):
            t = k * pas / longueur if longueur else 0.0
            points.append([round(a.x + t * (b.x - a.x), 3), round(a.y + t * (b.y - a.y), 3), round(cap, 4)])
    return points


def ecrire_apercu(dossier, session, info, image, trajectoire):
    """apercu.png (vue de dessus) et apercu.json (points décimés, trajectoire), formats 9.2."""
    x, y = _points_occupes(info, image)
    n = len(x)
    pas = max(1, math.ceil(n / L.APERCU_POINTS_MAX))
    points = [[round(float(a), 2), round(float(b), 2), 1.0] for a, b in zip(x[::pas], y[::pas])]
    vue = np.full(image.shape, 205, dtype=np.uint8)
    vue[image == 0] = 0
    ecrire_png_gris(Path(dossier) / L.FICHIERS_SESSION["apercu_png"], vue)
    xmin, ymin, xmax, ymax = L.bornes_carte(info)
    robot = trajectoire[-1] if trajectoire else None
    apercu = {"version": 1, "session": session["id"], "maj": L.scans.instant(), "repere": "odom",
              "resolution": info.resolution, "bornes": {"xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax},
              "largeur": info.largeur, "hauteur": info.hauteur, "sol": 0.0,
              "points": points[:L.APERCU_POINTS_MAX], "trajectoire": trajectoire[:L.APERCU_TRAJECTOIRE_MAX],
              "robot": None if robot is None else {"x": robot[0], "y": robot[1], "theta": robot[2]},
              "statistiques": session["statistiques"]}
    L.ecrire_atomique(Path(dossier) / L.FICHIERS_SESSION["apercu_json"],
                      json.dumps(apercu, ensure_ascii=False) + "\n")
    return apercu


def creer_session_exemple(lieu, etat="termine", mode="simu", etage="rdc", repetition=False):
    """Crée dans le lieu (une copie !) une session de scan cohérente, dans l'état demandé :
      en_cours    session.json (processus = ce processus, donc vivant) et aperçu ;
      traitement  en plus : nuage.pcd, carte.pgm/.yaml, étape reconnaissance à 70 % ;
      termine     en plus : reconnaissance.yaml, monde_scan.monde.yaml, rapport.json ;
      echec       arrêt à l'étape carte_3d, avec un message qui dit quoi faire.
    Renvoie la session (dict, avec « dossier »)."""
    if etat not in ETATS_EXEMPLE:
        raise ValueError(f"état d'exemple inconnu : {etat} (possibles : {', '.join(ETATS_EXEMPLE)})")
    dossier_lieu = L.dossier_lieu(lieu)
    info, image = L.charger_carte(L.chemin_carte(dossier_lieu, etage))
    monde = L.charger_monde(dossier_lieu, etage)
    session = L.creer_session(dossier_lieu, etage, mode, repetition=repetition, refuser_si_active=False)
    ident = session["id"]
    dossier = L.dossier_session(dossier_lieu, ident)
    trajectoire = _trajectoire(dossier_lieu, etage)
    distance = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(trajectoire, trajectoire[1:]))
    x, y = _points_occupes(info, image)
    stats = {"duree_s": round(distance / 0.4, 1), "points": int(len(x) * 40), "distance_m": round(distance, 2),
             "nuages": int(distance / 0.4 * 10)}
    session = L.maj_session(dossier_lieu, ident, etape="enregistrement", statistiques=stats,
                            processus=L.infos_processus(),
                            message="Scan en cours : promenez le robot dans tout l'étage, puis « Fin ».")
    ecrire_apercu(dossier, session, info, image, trajectoire)
    if etat == "en_cours":
        session["dossier"] = str(dossier)
        return session

    fin = L.scans.instant()
    if etat == "echec":
        session = L.maj_session(dossier_lieu, ident, etat="echec", etape="carte_3d", progression=10, fin=fin,
                                message="La carte 3D n'a pas pu être fabriquée : l'enregistrement ne contient "
                                        "aucun nuage de points. Vérifiez que le LiDAR publie, puis refaites le scan.")
        session["dossier"] = str(dossier)
        return session

    # Nuage : les obstacles de la carte, de 0,2 à 1,2 m de haut ; carte : celle du monde
    hauteurs = np.linspace(0.2, 1.2, 6)
    nuage = np.column_stack([np.repeat(x, len(hauteurs)), np.repeat(y, len(hauteurs)),
                             np.tile(hauteurs, len(x))])
    ecrire_pcd_ascii(dossier / L.FICHIERS_SESSION["nuage"], nuage[::3])
    info_session = L.InfoCarte(image=L.FICHIERS_SESSION["carte_image"], resolution=info.resolution,
                               origin=info.origin)
    L.enregistrer_carte(dossier / L.FICHIERS_SESSION["carte"], info_session, image)
    if etat == "traitement":
        session = L.maj_session(dossier_lieu, ident, etat="traitement", etape="reconnaissance", fin=fin,
                                progression=L.progression_etape("reconnaissance", 0.2),
                                message="Reconnaissance des murs, des passages et des objets…")
        session["dossier"] = str(dossier)
        return session

    reconnaissance = L.reconnaissance_depuis_monde(monde, etage, session=ident)
    L.ecrire_reconnaissance(dossier, reconnaissance)
    L.ecrire_monde_scan(dossier, reconnaissance)
    rapport = {"version": 1, "session": ident, "termine": L.scans.instant(), "duree_traitement_s": 12.5,
               "etapes": [{"etape": e, "ok": True, "duree_s": 3.0, "message": ""} for e in L.ETAPES_TRAITEMENT],
               "nuage": {"fichier": L.FICHIERS_SESSION["nuage"], "points": int(len(nuage[::3])),
                         "nuages": stats["nuages"], "retires_mobiles": 0},
               "carte": {"fichier": L.FICHIERS_SESSION["carte"], "largeur": info.largeur, "hauteur": info.hauteur,
                         "resolution": info.resolution, "occupes": int((image == 0).sum()), "sol": 0.0},
               "reconnaissance": L.resume_reconnaissance(reconnaissance),
               "comparaison": {"reference": f"cartes/{etage}.yaml", "recouvrement": 1.0, "couverture": 1.0},
               "avertissements": []}
    L.ecrire_atomique(dossier / L.FICHIERS_SESSION["rapport"], json.dumps(rapport, ensure_ascii=False, indent=2) + "\n")
    session = L.maj_session(dossier_lieu, ident, etat="termine", etape="fini", progression=100, fin=fin,
                            message="Scan terminé : carte 2D et monde prêts. Vérifiez les éléments reconnus, "
                                    "puis « Adopter ».")
    session["dossier"] = str(dossier)
    return session


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    s = creer_session_exemple(sys.argv[1], *(sys.argv[2:3] or ["termine"]))
    print(f"Session d'exemple {s['id']} ({s['etat']}) : {s['dossier']}")
