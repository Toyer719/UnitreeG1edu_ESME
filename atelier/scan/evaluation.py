"""Évaluation de la reconnaissance du scan (section 9.8 du plan), et nuages synthétiques pour l'essayer.

    from atelier.scan.evaluation import evaluer, texte_bilan
    bilan = evaluer(reconnaissance, monde_reference, info_carte, image_carte)
    print(texte_bilan(bilan))

La vérité terrain est un monde dessiné (ex. lieux/demo/mondes/rdc.monde.yaml : chaque objet y a sa
catégorie). Seul ce que le scan a VU compte dans les rappels : un pixel occupé de la carte de la
session à 0,10 m au plus (de la surface d'un mur, de l'empreinte d'un objet).

Mesures (tolérances dans TOLERANCES, objectifs de la vague dans OBJECTIFS) :
  murs       rappel : part des points des murs vrais vus (un tous les 0,05 m, sur l'axe du mur) à
             0,15 m au plus d'un mur gardé de même direction (10° près) ; précision : part des points
             des murs gardés à 0,15 m au plus d'un mur vrai. En plus, plus strict : murs vrais
             « retrouvés » (la moitié de leurs points vus à 0,2 m et 5° d'un mur gardé).
  passages   un passage vrai dont les deux bouts sont vus est trouvé si un passage reconnu a son
             milieu à 0,30 m au plus et sa largeur à 0,30 m près ; rappel et précision.
  objets     objets vrais vus (au moins 3 pixels occupés dans l'empreinte agrandie de 0,10 m),
             appariés un à un au plus proche reconnu, centres à 0,5 m au plus : détection ; part des
             appariés de la bonne catégorie ; en plus, retrouvés à 0,3 m avec la bonne catégorie.
  faux       objets reconnus gardés, ni appariés ni à 0,3 m d'un mur vrai.
  personnes  chaque personne vraie vue est reconnue « personne » avec a_garder faux, et aucun pixel
             occupé ne reste dans son empreinte après l'adoption (carte_sans_elements_retires) ;
             aucune personne reconnue n'est gardée d'office.

En ligne de commande (bilan en français ; --exiger : code 1 si un objectif n'est pas atteint) :
    python -m atelier.scan.evaluation --session DOSSIER --reference LIEU [--etage rdc] [--json]

Nuages synthétiques (sans ROS ni Gazebo), pour régler et tester la reconnaissance :
    nuage_synthetique(monde, points_de_vue)    lancer de rayons (Open3D) sur les murs et les objets
    points_de_vue_du_lieu(lieu, etage)          positions le long des couloirs des itinéraires
    essayer_sur_monde(monde, points_de_vue, dossier)   nuage → carte 2D → reconnaissance → bilan
"""
import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

from atelier import lieu as L
from atelier.lieu.geometrie import dist_point_segment

TOLERANCES = {
    "vu": 0.10,                      # m : un pixel occupé aussi près de la surface : l'élément a été vu
    "pas_mur": 0.05,                 # m : un point tous les 0,05 m le long des murs
    "mur_distance": 0.15,            # m : rappel et précision des murs
    "mur_angle": 10.0,               # degrés : même direction (rappel)
    "mur_retrouve_distance": 0.2,    # m : mesure plus stricte, mur par mur
    "mur_retrouve_angle": 5.0,       # degrés
    "mur_retrouve_part": 0.5,        # part des points vus d'un mur vrai qui doivent être retrouvés
    "passage_milieu": 0.30,          # m : écart des milieux
    "passage_largeur": 0.30,         # m : écart des largeurs
    "objet_vu_marge": 0.10,          # m : empreinte agrandie pour compter les pixels vus
    "objet_vu_pixels": 3,            # pixels occupés au moins pour qu'un objet soit vu
    "objet_distance": 0.5,           # m : appariement des centres
    "objet_distance_stricte": 0.3,   # m : objets retrouvés avec la bonne catégorie (mesure plus stricte)
    "faux_distance_mur": 0.3,        # m : un objet reconnu aussi près d'un mur vrai n'est pas un faux objet
}

OBJECTIFS = {"murs_rappel": 0.90, "murs_precision": 0.90, "passages_rappel": 0.8, "passages_precision": 0.8,
             "objets_detection": 0.8, "objets_categorie": 0.7, "faux_objets_max": 3, "personnes": True}

OCCUPE = 0


# ---------------------------------------------------------------- lecture des entrées

def _reconnaissance(r):
    if isinstance(r, dict):
        return r
    return L.lire_reconnaissance(r)


def _monde(m, etage="rdc"):
    if isinstance(m, L.Monde):
        return m
    if isinstance(m, dict):
        return L.Monde.depuis_dict(m)
    if Path(m).is_file():
        return L.Monde.depuis_dict(L.charger_fichier(m, "monde"))
    return L.charger_monde(m, etage)                         # lieu : id seul ou dossier


def _distance_aux_occupes(info, image):
    """Pour chaque pixel, distance (m) au centre du pixel occupé le plus proche."""
    import cv2
    source = np.where(np.asarray(image) == OCCUPE, 0, 1).astype(np.uint8)
    if source.min() == 1:
        return np.full(source.shape, np.inf)
    return cv2.distanceTransform(source, cv2.DIST_L2, 5).astype(float) * info.resolution


def _distance_en(points, distances, info):
    """Distance aux occupés lue sous chaque point (N, 2) ; inf hors de la carte."""
    points = np.asarray(points, dtype=float).reshape(-1, 2)
    colonnes, lignes = L.monde_vers_pixel(points[:, 0], points[:, 1], info)
    colonnes, lignes = np.atleast_1d(colonnes), np.atleast_1d(lignes)
    dedans = np.atleast_1d(L.dans_image(colonnes, lignes, info)).astype(bool)
    resultat = np.full(len(points), np.inf)
    resultat[dedans] = distances[lignes[dedans], colonnes[dedans]]
    return resultat


def _echantillons(de, a, pas):
    de, a = np.asarray(de, dtype=float), np.asarray(a, dtype=float)
    longueur = float(np.linalg.norm(a - de))
    n = max(2, int(math.floor(longueur / pas)) + 1)
    return de + np.linspace(0.0, 1.0, n)[:, None] * (a - de)


def _cap(de, a):
    return math.atan2(a[1] - de[1], a[0] - de[0])


def _ecart_angle(c1, c2):
    """Écart de direction de deux droites (sans sens), en degrés."""
    return math.degrees(abs((c1 - c2 + math.pi / 2) % math.pi - math.pi / 2))


def _empreinte(objet):
    """Empreinte d'un objet vrai : ("cercle", centre, rayon) ou ("rect", centre, longueur, largeur, cap)."""
    forme = objet.empreinte()
    if forme[0] == "cercle":
        return ("cercle", np.asarray(forme[1], dtype=float), float(forme[2]))
    if objet.type == "modele":
        d = L.MODELES_MOBILIER[objet.modele]
        return ("rect", np.asarray(objet.centre, dtype=float), d["longueur"], d["largeur"], objet.cap)
    return ("rect", np.asarray(objet.centre, dtype=float), objet.taille[0], objet.taille[1], objet.cap)


def _dans_empreinte(X, Y, empreinte, marge):
    if empreinte[0] == "cercle":
        return np.hypot(X - empreinte[1][0], Y - empreinte[1][1]) <= empreinte[2] + marge
    _, c, longueur, largeur, cap = empreinte
    dx, dy = X - c[0], Y - c[1]
    u = math.cos(cap) * dx + math.sin(cap) * dy
    v = -math.sin(cap) * dx + math.cos(cap) * dy
    return (np.abs(u) <= longueur / 2 + marge) & (np.abs(v) <= largeur / 2 + marge)


def _pixels_occupes_dans(info, image, empreinte, marge):
    X, Y = L.centres_pixels(info)
    return int((_dans_empreinte(X, Y, empreinte, marge) & (np.asarray(image) == OCCUPE)).sum())


# ---------------------------------------------------------------- mesures

def _evaluer_murs(reco, monde, distances, info, t):
    gardes = [m for m in reco["murs"] if m["a_garder"]]
    vus = trouves = 0
    vus_strict = trouves_strict = 0
    par_mur = []
    for m in monde.murs:
        points = _echantillons(m.de, m.a, t["pas_mur"])
        vu = _distance_en(points, distances, info) <= t["vu"] + m.epaisseur / 2 + 1e-9
        cap = _cap(m.de, m.a)
        trouve = np.zeros(len(points), dtype=bool)
        strict = np.zeros(len(points), dtype=bool)
        for g in gardes:
            angle = _ecart_angle(cap, _cap(g["de"], g["a"]))
            if angle > t["mur_angle"]:
                continue
            d = np.array([dist_point_segment(tuple(q), tuple(g["de"]), tuple(g["a"])) for q in points])
            trouve |= d <= t["mur_distance"]
            if angle <= t["mur_retrouve_angle"]:
                strict |= d <= t["mur_retrouve_distance"]
        n_vus = int(vu.sum())
        vus += n_vus
        trouves += int((vu & trouve).sum())
        retrouve = None
        if n_vus >= max(2, 0.3 * len(points)):          # mur vrai bien vu : compté dans la mesure stricte
            vus_strict += 1
            retrouve = bool((vu & strict).sum() >= t["mur_retrouve_part"] * n_vus)
            trouves_strict += int(retrouve)
        par_mur.append({"id": m.id, "points": len(points), "vus": n_vus, "trouves": int((vu & trouve).sum()),
                        "retrouve": retrouve})
    justes = total = 0
    faux_murs = []
    for g in gardes:
        points = _echantillons(g["de"], g["a"], t["pas_mur"])
        bons = np.zeros(len(points), dtype=bool)
        for m in monde.murs:
            bons |= np.array([dist_point_segment(tuple(q), m.de, m.a) for q in points]) <= t["mur_distance"]
        total += len(points)
        justes += int(bons.sum())
        if bons.mean() < 0.5:
            faux_murs.append(g["id"])
    return {"rappel": trouves / vus if vus else 1.0, "precision": justes / total if total else 1.0,
            "points_vus": vus, "points_trouves": trouves, "points_reconnus": total, "points_justes": justes,
            "murs_vrais": len(monde.murs), "murs_vus": vus_strict, "murs_retrouves": trouves_strict,
            "retrouves_part": trouves_strict / vus_strict if vus_strict else 1.0,
            "murs_reconnus": len(gardes), "murs_faux": faux_murs, "par_mur": par_mur}


def _evaluer_passages(reco, monde, distances, info, t):
    vrais = L.passages_du_monde(monde)
    epaisseurs = {m.id: m.epaisseur for m in monde.murs}
    reconnus = reco["passages"]

    def milieu(p):
        return (np.asarray(p["de"], dtype=float) + np.asarray(p["a"], dtype=float)) / 2

    def largeur(p):
        return float(np.linalg.norm(np.asarray(p["a"], dtype=float) - np.asarray(p["de"], dtype=float)))

    paires = []
    for i, v in enumerate(vrais):
        for j, r in enumerate(reconnus):
            ecart = float(np.linalg.norm(milieu(v) - milieu(r)))
            if ecart <= t["passage_milieu"] and abs(largeur(v) - largeur(r)) <= t["passage_largeur"]:
                paires.append((ecart, i, j))
    vrai_pris, reco_pris = {}, {}
    for ecart, i, j in sorted(paires):
        if i not in vrai_pris and j not in reco_pris:
            vrai_pris[i], reco_pris[j] = j, i
    details, vus, trouves = [], 0, 0
    for i, v in enumerate(vrais):
        epaisseur = max(epaisseurs.get(m, 0.15) for m in v["murs"])
        d = _distance_en([v["de"], v["a"]], distances, info)
        vu = bool((d <= t["vu"] + epaisseur / 2 + 1e-9).all())
        vus += vu
        trouves += vu and i in vrai_pris
        details.append({"murs": v["murs"], "largeur": round(v["largeur"], 3), "vu": vu,
                        "reconnu": reconnus[vrai_pris[i]]["id"] if i in vrai_pris else None})
    corrects = len(reco_pris)
    return {"rappel": trouves / vus if vus else 1.0, "precision": corrects / len(reconnus) if reconnus else 1.0,
            "vrais": len(vrais), "vus": vus, "trouves": trouves, "reconnus": len(reconnus), "corrects": corrects,
            "faux": [r["id"] for j, r in enumerate(reconnus) if j not in reco_pris], "details": details}


def _evaluer_objets(reco, monde, info, image, t):
    vrais = list(monde.objets)
    reconnus = reco["objets"]
    vus = [_pixels_occupes_dans(info, image, _empreinte(o), t["objet_vu_marge"]) >= t["objet_vu_pixels"]
           for o in vrais]
    paires = []
    for i, o in enumerate(vrais):
        for j, r in enumerate(reconnus):
            ecart = math.dist(o.centre, r["centre"])
            if ecart <= t["objet_distance"]:
                paires.append((ecart, i, j))
    vrai_pris, reco_pris = {}, {}
    for ecart, i, j in sorted(paires):
        if i not in vrai_pris and j not in reco_pris:
            vrai_pris[i], reco_pris[j] = j, i
    par_categorie, details = {}, []
    apparies = bons = stricts = n_vus = 0
    for i, o in enumerate(vrais):
        categorie = o.categorie_effective
        c = par_categorie.setdefault(categorie, {"vrais": 0, "vus": 0, "apparies": 0, "bonne_categorie": 0})
        c["vrais"] += 1
        r = reconnus[vrai_pris[i]] if i in vrai_pris else None
        detail = {"id": o.id, "categorie": categorie, "vu": bool(vus[i]),
                  "reconnu": r["id"] if r else None, "categorie_reconnue": r["categorie"] if r else None,
                  "ecart": round(math.dist(o.centre, r["centre"]), 3) if r else None}
        details.append(detail)
        if not vus[i]:
            continue
        n_vus += 1
        c["vus"] += 1
        if r is None:
            continue
        apparies += 1
        c["apparies"] += 1
        if r["categorie"] == categorie:
            bons += 1
            c["bonne_categorie"] += 1
            stricts += detail["ecart"] <= t["objet_distance_stricte"]
    faux = []
    for j, r in enumerate(reconnus):
        if not r["a_garder"] or j in reco_pris:
            continue
        pres_mur = any(dist_point_segment(tuple(r["centre"]), m.de, m.a) - m.epaisseur / 2 <= t["faux_distance_mur"]
                       for m in monde.murs)
        if not pres_mur:
            faux.append(r["id"])
    return {"detection": apparies / n_vus if n_vus else 1.0, "categorie": bons / apparies if apparies else 1.0,
            "vrais": len(vrais), "vus": n_vus, "apparies": apparies, "bonne_categorie": bons,
            "retrouves_stricts": stricts, "retrouves_stricts_part": stricts / n_vus if n_vus else 1.0,
            "reconnus": len(reconnus), "faux": faux, "par_categorie": par_categorie, "details": details}


def _evaluer_personnes(reco, monde, info, image, objets, t):
    apres = L.carte_sans_elements_retires(info, image, reco)
    details = []
    ok = True
    for d, o in zip(objets["details"], monde.objets):
        if o.categorie_effective != "personne":
            continue
        r = next((x for x in reco["objets"] if x["id"] == d["reconnu"]), None)
        reste = _pixels_occupes_dans(info, apres, _empreinte(o), 0.0)
        bonne = r is not None and r["categorie"] == "personne" and not r["a_garder"]
        details.append({"id": o.id, "vue": d["vu"], "reconnue": bonne, "pixels_apres_adoption": reste})
        ok &= bool(d["vu"] and bonne and reste == 0)
    gardees = [x["id"] for x in reco["objets"] if x["categorie"] == "personne" and x["a_garder"]]
    return {"ok": bool(ok and not gardees), "details": details, "personnes_gardees": gardees}


def evaluer(reconnaissance, monde_reference, info_carte, image_carte, tolerances=None, etage="rdc"):
    """Compare une reconnaissance (dict ou chemin) à la vérité terrain d'un monde dessiné (Monde, dict,
    chemin du .monde.yaml ou lieu), sur la carte du scan (InfoCarte et image, pour savoir ce qui a été
    vu). Renvoie un bilan chiffré : murs, passages, objets, personnes, objectifs (atteint ou non)."""
    t = dict(TOLERANCES, **(tolerances or {}))
    reco = _reconnaissance(reconnaissance)
    monde = _monde(monde_reference, etage)
    image = np.asarray(image_carte)
    distances = _distance_aux_occupes(info_carte, image)
    murs = _evaluer_murs(reco, monde, distances, info_carte, t)
    passages = _evaluer_passages(reco, monde, distances, info_carte, t)
    objets = _evaluer_objets(reco, monde, info_carte, image, t)
    personnes = _evaluer_personnes(reco, monde, info_carte, image, objets, t)
    valeurs = {"murs_rappel": murs["rappel"], "murs_precision": murs["precision"],
               "passages_rappel": passages["rappel"], "passages_precision": passages["precision"],
               "objets_detection": objets["detection"], "objets_categorie": objets["categorie"],
               "faux_objets_max": len(objets["faux"]), "personnes": personnes["ok"]}
    objectifs = {}
    for cle, cible in OBJECTIFS.items():
        v = valeurs[cle]
        atteint = (v == cible) if isinstance(cible, bool) else (v <= cible if cle.endswith("_max") else v >= cible)
        objectifs[cle] = {"valeur": round(v, 3) if isinstance(v, float) else v, "objectif": cible,
                          "atteint": bool(atteint)}
    return {"murs": murs, "passages": passages, "objets": objets, "personnes": personnes,
            "objectifs": objectifs, "tout_atteint": all(o["atteint"] for o in objectifs.values()),
            "tolerances": t}


def texte_bilan(bilan):
    """Bilan lisible, en français."""
    m, p, o, h = bilan["murs"], bilan["passages"], bilan["objets"], bilan["personnes"]

    def pc(v):
        return f"{100 * v:.0f} %"

    def marque(cle):
        return "ok" if bilan["objectifs"][cle]["atteint"] else "NON"
    lignes = [
        f"Murs : rappel {pc(m['rappel'])} ({m['points_trouves']}/{m['points_vus']} points vus), "
        f"précision {pc(m['precision'])} ({m['points_justes']}/{m['points_reconnus']}) "
        f"[{marque('murs_rappel')}, {marque('murs_precision')}] ; "
        f"murs retrouvés à 0,2 m et 5° : {m['murs_retrouves']}/{m['murs_vus']} ({pc(m['retrouves_part'])})",
        f"Passages : {p['trouves']}/{p['vus']} vus trouvés (rappel {pc(p['rappel'])}), {p['corrects']}/{p['reconnus']} "
        f"reconnus justes (précision {pc(p['precision'])}) "
        f"[{marque('passages_rappel')}, {marque('passages_precision')}]"
        + (f" ; en trop : {', '.join(p['faux'])}" if p["faux"] else ""),
        f"Objets : {o['apparies']}/{o['vus']} vus détectés ({pc(o['detection'])}) [{marque('objets_detection')}], "
        f"{o['bonne_categorie']}/{o['apparies']} de la bonne catégorie ({pc(o['categorie'])}) "
        f"[{marque('objets_categorie')}] ; retrouvés à 0,3 m avec la bonne catégorie : "
        f"{o['retrouves_stricts']}/{o['vus']} ({pc(o['retrouves_stricts_part'])})",
        f"Faux objets gardés (loin des murs) : {len(o['faux'])} [{marque('faux_objets_max')}]"
        + (f" : {', '.join(o['faux'])}" if o["faux"] else ""),
    ]
    for d in h["details"]:
        lignes.append(f"Personne {d['id']} : {'vue' if d['vue'] else 'pas vue'}, "
                      f"{'reconnue et décochée' if d['reconnue'] else 'NON reconnue (ou cochée)'}, "
                      f"{d['pixels_apres_adoption']} pixel(s) occupé(s) après l'adoption [{marque('personnes')}]")
    if h["personnes_gardees"]:
        lignes.append(f"Personnes cochées d'office (interdit) : {', '.join(h['personnes_gardees'])}")
    lignes.append("Par catégorie (vus / détectés / bonne catégorie) : " + " ; ".join(
        f"{c} {v['vus']}/{v['apparies']}/{v['bonne_categorie']}" for c, v in sorted(o["par_categorie"].items())))
    for d in o["details"]:
        if d["vu"] and (d["reconnu"] is None or d["categorie_reconnue"] != d["categorie"]):
            lignes.append(f"  - {d['id']} ({d['categorie']}) : "
                          + (f"reconnu {d['categorie_reconnue']} ({d['reconnu']}, à {d['ecart']} m)"
                             if d["reconnu"] else "non détecté"))
    lignes.append("Objectifs de la vague : " + ("tous atteints" if bilan["tout_atteint"] else "pas tous atteints"))
    return "\n".join(lignes)


# ---------------------------------------------------------------- nuages synthétiques

def _boite(longueur, largeur, hauteur, centre, cap=0.0, z0=0.0):
    """Maillage Open3D d'une boîte posée à z0, de longueur le long du cap."""
    import open3d as o3d
    b = o3d.geometry.TriangleMesh.create_box(max(longueur, 1e-3), max(largeur, 1e-3), max(hauteur, 1e-3))
    b.translate((-longueur / 2, -largeur / 2, 0.0))
    b.rotate(o3d.geometry.get_rotation_matrix_from_xyz((0.0, 0.0, cap)), center=(0.0, 0.0, 0.0))
    b.translate((centre[0], centre[1], z0))
    return b


def _cylindre(rayon, hauteur, centre, z0=0.0):
    import open3d as o3d
    c = o3d.geometry.TriangleMesh.create_cylinder(radius=rayon, height=hauteur, resolution=32, split=1)
    c.translate((centre[0], centre[1], z0 + hauteur / 2))
    return c


def _local(centre, cap, dx, dy):
    c, s = math.cos(cap), math.sin(cap)
    return (centre[0] + c * dx - s * dy, centre[1] + s * dx + c * dy)


def maillages_du_monde(monde, sol=True):
    """Maillages (Open3D) des murs et des objets d'un monde, meubles détaillés comme dans le SDF
    (atelier.monde.sdf) ; les piétons n'y sont pas (ils sont retirés du nuage d'un vrai scan)."""
    maillages = []
    if sol:
        e = monde.emprise
        maillages.append(_boite(e.taille_x + 2, e.taille_y + 2, 0.01, ((e.xmin + e.xmax) / 2, (e.ymin + e.ymax) / 2),
                                z0=-0.01))
    for m in monde.murs:
        maillages.append(_boite(m.longueur, m.epaisseur, m.hauteur, m.centre, m.cap))
    for o in monde.objets:
        c, cap = o.centre, o.cap
        if o.type == "boite":
            maillages.append(_boite(*o.taille, c, cap))
        elif o.type == "cylindre":
            maillages.append(_cylindre(o.rayon, o.hauteur, c))
        elif o.modele == "poubelle":
            d = L.MODELES_MOBILIER["poubelle"]
            maillages.append(_cylindre(d["rayon"], d["hauteur"], c))
        elif o.modele == "table":
            d = L.MODELES_MOBILIER["table"]
            lx, ly, h = d["longueur"], d["largeur"], d["hauteur"]
            maillages.append(_boite(lx, ly, 0.04, c, cap, h - 0.04))
            for sx, sy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
                pied = _local(c, cap, sx * (lx / 2 - 0.05), sy * (ly / 2 - 0.05))
                maillages.append(_boite(0.05, 0.05, h - 0.04, pied, cap))
        elif o.modele == "chaise":
            d = L.MODELES_MOBILIER["chaise"]
            lx, ly, h = d["longueur"], d["largeur"], d["hauteur"]
            maillages.append(_boite(lx, ly, 0.05, c, cap, 0.40))
            for sx, sy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
                pied = _local(c, cap, sx * (lx - 0.04) / 2, sy * (ly - 0.04) / 2)
                maillages.append(_boite(0.04, 0.04, 0.40, pied, cap))
            maillages.append(_boite(0.04, ly, h - 0.45, _local(c, cap, -(lx - 0.04) / 2, 0.0), cap, 0.45))
        elif o.modele == "banc":
            d = L.MODELES_MOBILIER["banc"]
            lx, ly, h = d["longueur"], d["largeur"], d["hauteur"]
            maillages.append(_boite(lx, ly, 0.05, c, cap, h - 0.05))
            for sx in (1, -1):
                maillages.append(_boite(0.06, ly, h - 0.05, _local(c, cap, sx * (lx / 2 - 0.15), 0.0), cap))
    return maillages


def nuage_synthetique(monde, points_de_vue, hauteur_capteur=1.245, champ_vertical=(-30.0, 52.0),
                      pas_horizontal=0.5, pas_vertical=1.0, portee=20.0, bruit=0.015, trous=0,
                      rayon_trous=(0.1, 0.3), grille=0.05, graine=0, personnes=()):
    """Nuage (N, 3) d'un monde dessiné, vu depuis des points de vue (x, y) à hauteur_capteur :
    lancer de rayons (Open3D RaycastingScene) sur le sol, les murs et les objets ; seules les surfaces
    visibles reçoivent des points. Bruit gaussien de « bruit » m, « trous » trous sphériques de
    rayon tiré dans rayon_trous, puis réduction à une grille de 5 cm (comme carte3d).
    personnes : cylindres (x, y, rayon, hauteur) ajoutés au nuage sans être dans le monde."""
    import open3d as o3d
    rng = np.random.default_rng(graine)
    scene = o3d.t.geometry.RaycastingScene()
    for maillage in maillages_du_monde(monde):
        scene.add_triangles(o3d.t.geometry.TriangleMesh.from_legacy(maillage))
    for x, y, rayon, hauteur in personnes:
        scene.add_triangles(o3d.t.geometry.TriangleMesh.from_legacy(_cylindre(rayon, hauteur, (x, y))))
    azimuts = np.radians(np.arange(-180.0, 180.0, pas_horizontal))
    sites = np.radians(np.arange(champ_vertical[0], champ_vertical[1] + 1e-9, pas_vertical))
    A, S = np.meshgrid(azimuts, sites)
    directions = np.stack([np.cos(S) * np.cos(A), np.cos(S) * np.sin(A), np.sin(S)], axis=-1).reshape(-1, 3)
    morceaux = []
    for x, y in points_de_vue:
        origine = np.array([x, y, hauteur_capteur])
        rayons = np.hstack([np.tile(origine, (len(directions), 1)), directions]).astype(np.float32)
        t_touche = scene.cast_rays(o3d.core.Tensor(rayons))["t_hit"].numpy()
        bon = np.isfinite(t_touche) & (t_touche <= portee)
        morceaux.append(origine + directions[bon] * t_touche[bon, None])
    points = np.vstack(morceaux) if morceaux else np.zeros((0, 3))
    if bruit > 0:
        points = points + rng.normal(0.0, bruit, points.shape)
    if trous > 0 and len(points):
        centres = points[rng.choice(len(points), size=trous, replace=False)]
        rayons = rng.uniform(*rayon_trous, size=trous)
        garde = np.ones(len(points), dtype=bool)
        for c, r in zip(centres, rayons):
            garde &= np.linalg.norm(points - c, axis=1) > r
        points = points[garde]
    nuage = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(points))
    return np.asarray(nuage.voxel_down_sample(grille).points)


def points_de_vue_du_lieu(lieu, etage, pas=0.5):
    """Positions (x, y) tous les « pas » mètres le long des couloirs de itineraires.yaml de l'étage."""
    itin = L.charger_itineraires(lieu)
    vues = []
    for couloir in itin.couloirs:
        a, b = itin.noeuds[couloir.a], itin.noeuds[couloir.b]
        if a.etage != etage or b.etage != etage:
            continue
        longueur = math.hypot(b.x - a.x, b.y - a.y)
        for k in range(max(1, int(longueur / pas)) + 1):
            f = min(1.0, k * pas / longueur) if longueur else 0.0
            vues.append((a.x + f * (b.x - a.x), a.y + f * (b.y - a.y)))
    return sorted(set((round(x, 3), round(y, 3)) for x, y in vues))


def essayer_sur_monde(monde, points_de_vue, dossier, parametres=None, personnes=(), **options_nuage):
    """Chaîne complète sans ROS : nuage synthétique → nuage.pcd → carte 2D (carte.yaml, emprise du
    monde) → reconnaissance → bilan. La vérité terrain est le monde, plus les personnes ajoutées.
    Renvoie (resultat de reconnaitre, bilan)."""
    from atelier.scan.carte2d import fabriquer_carte
    from atelier.scan.carte3d import ecrire_pcd
    from atelier.scan.reconnaissance import reconnaitre
    dossier = Path(dossier)
    dossier.mkdir(parents=True, exist_ok=True)
    points = nuage_synthetique(monde, points_de_vue, personnes=personnes, **options_nuage)
    ecrire_pcd(dossier / "nuage.pcd", points)
    e = monde.emprise
    info, image, _ = fabriquer_carte(points, (e.xmin, e.ymin, e.xmax, e.ymax), image="carte.pgm")
    L.enregistrer_carte(dossier / "carte.yaml", info, image)
    reference = monde
    if personnes:
        reference = L.Monde.depuis_dict(monde.vers_dict())
        for k, (x, y, rayon, hauteur) in enumerate(personnes, start=1):
            reference.objets.append(L.Objet.cylindre(f"personne_ajoutee_{k}", (x, y), rayon, hauteur,
                                                     categorie="personne"))
    resultat = reconnaitre(dossier / "nuage.pcd", dossier / "carte.yaml", dossier, parametres)
    bilan = evaluer(dossier / "reconnaissance.yaml", reference, info, image)
    return resultat, bilan


# ---------------------------------------------------------------- ligne de commande

def main(argv=None):
    analyseur = argparse.ArgumentParser(
        prog="python -m atelier.scan.evaluation",
        description="Compare la reconnaissance d'une session de scan à la vérité terrain d'un monde dessiné.")
    analyseur.add_argument("--session", required=True,
                           help="dossier de la session (reconnaissance.yaml et carte.yaml dedans)")
    analyseur.add_argument("--reference", required=True,
                           help="lieu de référence (id ou dossier, ex. demo) ou fichier .monde.yaml")
    analyseur.add_argument("--etage", default="rdc", help="étage du monde de référence (défaut : rdc)")
    analyseur.add_argument("--carte", help="carte du scan (défaut : carte.yaml de la session)")
    analyseur.add_argument("--json", action="store_true", help="bilan complet en JSON")
    analyseur.add_argument("--exiger", action="store_true", help="code de sortie 1 si un objectif n'est pas atteint")
    args = analyseur.parse_args(argv)
    session = Path(args.session)
    carte = Path(args.carte) if args.carte else session / L.FICHIERS_SESSION["carte"]
    try:
        reconnaissance = L.lire_reconnaissance(session)
        info, image = L.charger_carte(carte)
        monde = _monde(args.reference, args.etage)
    except (L.ErreurLieu, OSError) as e:
        message = "; ".join(e.erreurs) if getattr(e, "erreurs", None) else str(e)
        print(f"Erreur : {message}", file=sys.stderr)
        return 1
    bilan = evaluer(reconnaissance, monde, info, image)
    if args.json:
        print(json.dumps(bilan, ensure_ascii=False, indent=2, default=float))
    else:
        print(texte_bilan(bilan))
    return 1 if args.exiger and not bilan["tout_atteint"] else 0


if __name__ == "__main__":
    sys.exit(main())
