"""Tests des contrats de l'Atelier G1 (agent Intégrateur) : schémas JSON et lieu demo.

  ~/robot-g1/.venv-projet/bin/python -m pytest ~/robot-g1/atelier/tests/test_contrats.py -v

Vérifie que :
  - chaque schéma de atelier/lieu/schemas est un schéma draft-07 valide ;
  - chaque fichier de lieux/demo respecte son schéma, et les erreurs courantes sont refusées ;
  - les fichiers du lieu demo sont cohérents entre eux (étages, salles, nœuds, accueil) ;
  - la géométrie du lieu demo convient au guide : couloirs de 8 m au plus et dans l'espace libre,
    deux chemins entre l'accueil et chaque salle, poses devant un passage, zones hors du graphe.
"""
import copy
import math
import sys
from collections import deque
from pathlib import Path

import jsonschema
import pytest
import yaml

import atelier

DOSSIER_SCHEMAS = Path(atelier.__file__).parent / "lieu" / "schemas"
DEMO = atelier.RACINE / "lieux" / "demo"
FICHIERS_DEMO = {
    "lieu": DEMO / "lieu.yaml",
    "monde": DEMO / "mondes" / "rdc.monde.yaml",
    "salles": DEMO / "salles.yaml",
    "itineraires": DEMO / "itineraires.yaml",
    "zones": DEMO / "zones.yaml",
}
# Encombrement indicatif des modèles au sol (longueur, largeur), ou rayon : voir monde.schema.json
MODELES = {"chaise": (0.45, 0.45), "table": (1.2, 0.8), "banc": (1.5, 0.4), "poubelle": 0.25}
DEGAGEMENT_GRAPHE = 0.5     # m entre un couloir ou une salle et un mur, un objet ou une zone interdite
DEGAGEMENT_PIETON = 0.3     # m entre le trajet d'un piéton et un mur ou un objet
COULOIR_MAX = 8.0           # m, longueur maximale d'un couloir (commande 1102 du vrai robot)


def charger_schema(nom):
    import json
    return json.loads((DOSSIER_SCHEMAS / f"{nom}.schema.json").read_text(encoding="utf-8"))


def erreurs(nom_schema, donnees):
    validateur = jsonschema.Draft7Validator(charger_schema(nom_schema))
    return [f"{'/'.join(map(str, e.absolute_path))} : {e.message}" for e in validateur.iter_errors(donnees)]


def lire(nom):
    return yaml.safe_load(FICHIERS_DEMO[nom].read_text(encoding="utf-8"))


# ---------------------------------------------------------------- géométrie plane

def dist_point_segment(p, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / l2))
    return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy))


def se_coupent(a, b, c, d):
    def orient(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    o1, o2, o3, o4 = orient(a, b, c), orient(a, b, d), orient(c, d, a), orient(c, d, b)
    return o1 * o2 < 0 and o3 * o4 < 0


def dist_segments(a, b, c, d):
    if se_coupent(a, b, c, d):
        return 0.0
    return min(dist_point_segment(a, c, d), dist_point_segment(b, c, d),
               dist_point_segment(c, a, b), dist_point_segment(d, a, b))


def dedans(p, polygone):
    x, y = p
    resultat = False
    for (x1, y1), (x2, y2) in zip(polygone, polygone[1:] + polygone[:1]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            resultat = not resultat
    return resultat


def dist_segment_polygone(a, b, polygone):
    if dedans(a, polygone) or dedans(b, polygone):
        return 0.0
    return min(dist_segments(a, b, c, d) for c, d in zip(polygone, polygone[1:] + polygone[:1]))


def rectangle(centre, longueur, largeur, cap):
    c, s = math.cos(cap), math.sin(cap)
    return [(centre[0] + c * u - s * v, centre[1] + s * u + c * v)
            for u, v in ((longueur / 2, largeur / 2), (-longueur / 2, largeur / 2),
                         (-longueur / 2, -largeur / 2), (longueur / 2, -largeur / 2))]


def obstacles(monde):
    """Murs et objets du monde, chacun sous forme d'une fonction distance(segment) en mètres."""
    liste = []
    for m in monde.get("murs", []):
        liste.append((m["id"], lambda a, b, m=m: dist_segments(a, b, m["de"], m["a"]) - m["epaisseur"] / 2))
    for o in monde.get("objets", []):
        rayon = None
        if o["type"] == "cylindre":
            rayon = o["rayon"]
        elif o["type"] == "modele" and not isinstance(MODELES[o["modele"]], tuple):
            rayon = MODELES[o["modele"]]
        if rayon is not None:
            liste.append((o["id"], lambda a, b, o=o, r=rayon: dist_point_segment(o["centre"], a, b) - r))
            continue
        longueur, largeur = o["taille"][:2] if o["type"] == "boite" else MODELES[o["modele"]]
        poly = rectangle(o["centre"], longueur, largeur, o["cap"])
        liste.append((o["id"], lambda a, b, poly=poly: dist_segment_polygone(a, b, poly)))
    return liste


def passages(monde):
    """Centres des passages : écart de 0,5 à 2,5 m entre les bouts de deux murs alignés."""
    murs = monde.get("murs", [])
    centres = []
    for i, m1 in enumerate(murs):
        for m2 in murs[i + 1:]:
            (x1, y1), (x2, y2) = m1["de"], m1["a"]
            dx, dy = x2 - x1, y2 - y1
            longueur = math.hypot(dx, dy)
            alignes = all(abs(dx * (p[1] - y1) - dy * (p[0] - x1)) / longueur < 1e-6 for p in (m2["de"], m2["a"]))
            if not alignes:
                continue
            ecart, p, q = min((math.dist(p, q), p, q) for p in (m1["de"], m1["a"]) for q in (m2["de"], m2["a"]))
            if 0.5 <= ecart <= 2.5:
                centres.append(((p[0] + q[0]) / 2, (p[1] + q[1]) / 2))
    return centres


def chemin_existe(depart, arrivee, aretes):
    voisins = {}
    for a, b in aretes:
        voisins.setdefault(a, set()).add(b)
        voisins.setdefault(b, set()).add(a)
    vus, file = {depart}, deque([depart])
    while file:
        n = file.popleft()
        if n == arrivee:
            return True
        for v in voisins.get(n, ()):
            if v not in vus:
                vus.add(v)
                file.append(v)
    return False


# ---------------------------------------------------------------- schémas

NOMS_SCHEMAS = ["lieu", "monde", "salles", "itineraires", "zones", "carte"]


@pytest.mark.parametrize("nom", NOMS_SCHEMAS)
def test_schema_draft07_valide(nom):
    schema = charger_schema(nom)
    assert schema["$schema"] == "http://json-schema.org/draft-07/schema#"
    jsonschema.Draft7Validator.check_schema(schema)


@pytest.mark.parametrize("nom", list(FICHIERS_DEMO))
def test_demo_respecte_son_schema(nom):
    assert erreurs(nom, lire(nom)) == []


def test_exemple_carte_nav2_respecte_son_schema():
    carte = {"image": "rdc.pgm", "resolution": 0.05, "origin": [-0.05, -0.05, 0.0], "negate": 0,
             "occupied_thresh": 0.65, "free_thresh": 0.196}
    assert erreurs("carte", carte) == []
    assert erreurs("carte", dict(carte, origin=[0.0, 0.0]))
    assert erreurs("carte", dict(carte, image="cartes/rdc.pgm"))


def modifier(nom, changement):
    donnees = copy.deepcopy(lire(nom))
    changement(donnees)
    return donnees


CAS_REFUSES = {
    "lieu sans accueil": ("lieu", lambda d: d.pop("accueil")),
    "lieu, source_carte inconnue": ("lieu", lambda d: d["etages"][0].update(source_carte="plan")),
    "lieu, id d'étage en majuscules": ("lieu", lambda d: d["etages"][0].update(id="RDC")),
    "lieu, version 2": ("lieu", lambda d: d.update(version=2)),
    "lieu, carte_unitree sans .pcd": ("lieu", lambda d: d.update(carte_unitree="test1")),
    "monde, champ mal orthographié": ("monde", lambda d: d.update(mur=d.pop("murs"))),
    "monde, mur sans épaisseur": ("monde", lambda d: d["murs"][0].pop("epaisseur")),
    "monde, point à 3 valeurs": ("monde", lambda d: d["murs"][0].update(de=[0, 0, 0])),
    "monde, boîte avec un rayon": ("monde", lambda d: d["objets"][0].update(rayon=0.3)),
    "monde, modèle inconnu": ("monde", lambda d: d["objets"][1].update(modele="armoire")),
    "monde, cylindre sans rayon": ("monde", lambda d: d["objets"][3].pop("rayon")),
    "monde, cap en degrés": ("monde", lambda d: d["objets"][1].update(cap=90)),
    "monde, piéton à un seul point": ("monde", lambda d: d["pietons"][0].update(trajet=[[1, 1]])),
    "monde, piéton sans vitesse": ("monde", lambda d: d["pietons"][0].pop("vitesse")),
    "salles, salle sans theta": ("salles", lambda d: d[1]["pose"].pop("theta")),
    "salles, id avec espace": ("salles", lambda d: d[1].update(id="vie scolaire")),
    "salles, alias en double": ("salles", lambda d: d[1].update(alias=["cpe", "cpe"])),
    "itineraires, couloir en boucle": ("itineraires", lambda d: d["couloirs"].append(["amphi", "amphi"])),
    "itineraires, couloir à 3 nœuds": ("itineraires", lambda d: d["couloirs"].append(["a", "b", "c"])),
    "itineraires, nœud sans étage": ("itineraires", lambda d: d["noeuds"]["amphi"].pop("etage")),
    "itineraires, nœud avec theta": ("itineraires", lambda d: d["noeuds"]["amphi"].update(theta=0.0)),
    "zones, polygone à 2 sommets": ("zones", lambda d: d["interdites"][0].update(polygone=[[0, 0], [1, 1]])),
    "zones, zone lente sans vitesse": ("zones", lambda d: d["lentes"][0].pop("vitesse_max")),
    "zones, vitesse nulle": ("zones", lambda d: d["lentes"][0].update(vitesse_max=0)),
    "zones, sans liste lentes": ("zones", lambda d: d.pop("lentes")),
}


@pytest.mark.parametrize("cas", list(CAS_REFUSES))
def test_schema_refuse(cas):
    nom, changement = CAS_REFUSES[cas]
    assert erreurs(nom, modifier(nom, changement)), f"le schéma {nom} aurait dû refuser : {cas}"


# ---------------------------------------------------------------- cohérence du lieu demo

def test_demo_coherence_entre_fichiers():
    lieu, monde, salles, itin = lire("lieu"), lire("monde"), lire("salles"), lire("itineraires")
    etages = [e["id"] for e in lieu["etages"]]
    assert len(etages) == len(set(etages)), "id d'étage en double"
    assert lieu["accueil"]["etage"] in etages

    ids_salles = [s["id"] for s in salles]
    assert len(ids_salles) == len(set(ids_salles)), "id de salle en double"
    assert "accueil" in ids_salles and len(ids_salles) == 6, "il faut l'accueil et 5 salles"
    for s in salles:
        assert s["etage"] in etages
        noeud = itin["noeuds"].get(s["id"])
        assert noeud is not None, f"la salle {s['id']} n'a pas de nœud de même id"
        assert (noeud["etage"], noeud["x"], noeud["y"]) == (s["etage"], s["pose"]["x"], s["pose"]["y"])
    accueil = next(s for s in salles if s["id"] == "accueil")
    assert dict(accueil["pose"], etage=accueil["etage"]) == lieu["accueil"]
    depart = monde["depart_robot"]
    assert (depart["x"], depart["y"], depart["theta"]) == tuple(lieu["accueil"][k] for k in "x y theta".split())

    ids_monde = [e["id"] for cle in ("murs", "objets", "pietons") for e in monde.get(cle, [])]
    assert len(ids_monde) == len(set(ids_monde)), "id en double dans le monde"
    assert len(monde["pietons"]) == 2

    for a, b in itin["couloirs"]:
        assert a in itin["noeuds"] and b in itin["noeuds"], f"couloir {a}-{b} : nœud inconnu"
        assert itin["noeuds"][a]["etage"] == itin["noeuds"][b]["etage"]
    for n in itin["noeuds"].values():
        assert n["etage"] in etages


def test_demo_tout_est_dans_l_emprise():
    monde, salles, itin, zones = lire("monde"), lire("salles"), lire("itineraires"), lire("zones")
    (xmin, ymin), (xmax, ymax) = monde["emprise"]["min"], monde["emprise"]["max"]
    assert (xmax - xmin, ymax - ymin) == (30.0, 20.0)

    def dans(p):
        return xmin <= p[0] <= xmax and ymin <= p[1] <= ymax
    points = [p for m in monde["murs"] for p in (m["de"], m["a"])]
    points += [o["centre"] for o in monde["objets"]]
    points += [p for h in monde["pietons"] for p in h["trajet"]]
    points += [(monde["depart_robot"]["x"], monde["depart_robot"]["y"])]
    points += [(s["pose"]["x"], s["pose"]["y"]) for s in salles]
    points += [(n["x"], n["y"]) for n in itin["noeuds"].values()]
    points += [p for liste in zones.values() for z in liste for p in z["polygone"]]
    hors = [p for p in points if not dans(p)]
    assert hors == []


def test_demo_couloirs_courts_et_libres():
    monde, itin = lire("monde"), lire("itineraires")
    obst = obstacles(monde)
    for a, b in itin["couloirs"]:
        pa = (itin["noeuds"][a]["x"], itin["noeuds"][a]["y"])
        pb = (itin["noeuds"][b]["x"], itin["noeuds"][b]["y"])
        assert math.dist(pa, pb) <= COULOIR_MAX, f"couloir {a}-{b} : {math.dist(pa, pb):.1f} m > 8 m"
        for nom, distance in obst:
            d = distance(pa, pb)
            assert d >= DEGAGEMENT_GRAPHE, f"couloir {a}-{b} à {d:.2f} m de {nom}"


def test_demo_deux_chemins_vers_chaque_salle():
    """Un couloir bloqué, quel qu'il soit, laisse toujours un chemin de l'accueil à chaque salle."""
    salles, itin = lire("salles"), lire("itineraires")
    aretes = [tuple(c) for c in itin["couloirs"]]
    for s in salles:
        if s["id"] == "accueil":
            continue
        assert chemin_existe("accueil", s["id"], aretes)
        for bloque in aretes:
            reste = [c for c in aretes if c != bloque]
            assert chemin_existe("accueil", s["id"], reste), f"{s['id']} inaccessible sans {bloque}"


def test_demo_salles_devant_un_passage_et_tournees_vers_lui():
    monde, salles = lire("monde"), lire("salles")
    obst = obstacles(monde)
    centres = passages(monde)
    assert len(centres) == 5, f"5 passages attendus, trouvés : {centres}"
    for s in salles:
        p = (s["pose"]["x"], s["pose"]["y"])
        for nom, distance in obst:
            assert distance(p, p) >= DEGAGEMENT_GRAPHE, f"salle {s['id']} à moins de 0,5 m de {nom}"
        if s["id"] == "accueil":
            continue
        centre = min(centres, key=lambda c: math.dist(c, p))
        assert math.dist(centre, p) <= 2.0, f"salle {s['id']} loin de tout passage"
        cap = math.atan2(centre[1] - p[1], centre[0] - p[0])
        ecart = abs((s["pose"]["theta"] - cap + math.pi) % (2 * math.pi) - math.pi)
        assert ecart < 0.05, f"salle {s['id']} pas tournée vers son passage"
        # Le regard traverse le passage sans toucher de mur, jusqu'à 1 m dans la salle
        au_dela = (centre[0] + math.cos(cap), centre[1] + math.sin(cap))
        for nom, distance in obst:
            assert distance(p, au_dela) >= DEGAGEMENT_PIETON, f"salle {s['id']} : regard bloqué par {nom}"


def test_demo_trajets_des_pietons_libres():
    monde = lire("monde")
    obst = obstacles(monde)
    for h in monde["pietons"]:
        trajet = h["trajet"] if h["aller_retour"] else h["trajet"] + h["trajet"][:1]
        for a, b in zip(trajet, trajet[1:]):
            for nom, distance in obst:
                assert distance(a, b) >= DEGAGEMENT_PIETON, f"piéton {h['id']} à moins de 0,3 m de {nom}"


def test_demo_zones_hors_du_graphe():
    itin, salles, zones = lire("itineraires"), lire("salles"), lire("zones")
    assert len(zones["interdites"]) >= 1 and len(zones["lentes"]) >= 1
    for z in zones["interdites"]:
        for a, b in itin["couloirs"]:
            pa = (itin["noeuds"][a]["x"], itin["noeuds"][a]["y"])
            pb = (itin["noeuds"][b]["x"], itin["noeuds"][b]["y"])
            assert dist_segment_polygone(pa, pb, z["polygone"]) >= DEGAGEMENT_GRAPHE, \
                f"zone interdite à moins de 0,5 m du couloir {a}-{b}"
        for s in salles:
            p = (s["pose"]["x"], s["pose"]["y"])
            assert dist_segment_polygone(p, p, z["polygone"]) >= DEGAGEMENT_GRAPHE, \
                f"zone interdite à moins de 0,5 m de la salle {s['id']}"


# ---------------------------------------------------------------- chemins communs

def test_chemin_lieu(monkeypatch, tmp_path):
    monkeypatch.delenv("ATELIER_LIEUX", raising=False)
    assert atelier.chemin_lieu("demo") == atelier.RACINE / "lieux" / "demo"
    monkeypatch.setenv("ATELIER_LIEUX", str(tmp_path))
    assert atelier.chemin_lieu("demo") == tmp_path / "demo"
    assert atelier.chemin_lieu(str(DEMO)) == DEMO
    assert atelier.chemin_lieu("./demo") == Path.cwd() / "demo"
    assert atelier.chemin_lieu("Demo") == Path.cwd() / "Demo"   # pas un id : un chemin relatif


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
