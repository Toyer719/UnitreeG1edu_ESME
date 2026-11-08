"""Vérification d'un lieu entier : les règles entre fichiers et la géométrie (contrat 4.1).

  verifier_lieu(lieu)      sur un Lieu déjà chargé ;
  valider_lieu(dossier)    lit tout le dossier, sans jamais lever d'exception (g1-lieu valider).

Les deux renvoient un Rapport : des erreurs (à corriger : le guide ou la simulation ne marcheront
pas) et des avertissements (à regarder : fichier manquant, carte pas encore fabriquée...).
"""
import math
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import atelier
from . import geometrie
from .conversions import dans_image, monde_vers_pixel, pixel_vers_monde
from .fichiers import (FICHE, ITINERAIRES, SALLES, ZONES, ErreurLieu, chemin_carte, chemin_monde,
                       charger_carte, charger_info_carte, charger_lieu, dossier_lieu)
from .modeles import ETIQUETTE_PRINCIPAL, Lieu
from .principal import point_principal, salles_principales
from .validation import IDS_BOOLEENS, REGLE_ID, nombre

COULOIR_MAX = 8.0          # m : la navigation du vrai robot (1102) va par tronçons de 8 m au plus
RAYON_ROBOT = 0.35         # m : emprise circulaire du robot dans Nav2
TOLERANCE_POSITION = 1e-3  # m : salle et nœud « à la même position »
TOLERANCE_ANGLE = 1e-3     # rad


@dataclass
class Rapport:
    """Résultat d'une vérification. ok : aucune erreur. lieu : le Lieu lu (None s'il est illisible)."""
    erreurs: List[str] = field(default_factory=list)
    avertissements: List[str] = field(default_factory=list)
    lieu: Optional[Lieu] = None

    @property
    def ok(self):
        return not self.erreurs

    def erreur(self, message):
        if message not in self.erreurs:
            self.erreurs.append(message)

    def avertir(self, message):
        if message not in self.avertissements:
            self.avertissements.append(message)

    def ajouter(self, autre):
        for m in autre.erreurs:
            self.erreur(m)
        for m in autre.avertissements:
            self.avertir(m)
        self.lieu = self.lieu or autre.lieu

    def texte(self):
        """Le rapport à afficher, en français."""
        lignes = []
        if self.erreurs:
            lignes.append(f"Erreurs à corriger ({len(self.erreurs)}) :")
            lignes += [f"  - {m}" for m in self.erreurs]
        else:
            lignes.append("Aucune erreur.")
        if self.avertissements:
            lignes.append(f"Avertissements ({len(self.avertissements)}) :")
            lignes += [f"  - {m}" for m in self.avertissements]
        return "\n".join(lignes)


def _pt(x, y):
    return f"[{nombre(x)}, {nombre(y)}]"


def _obstacles(monde):
    """(nom, distance(a, b)) pour chaque mur et objet : distance d'un segment à son empreinte
    au sol, 0 s'il la touche. Pour un point p : distance(p, p). Une personne (objet hors carte,
    section 9.4) n'est pas un obstacle fixe : elle n'y est pas."""
    liste = []
    for m in monde.murs:
        liste.append((f"le mur « {m.id} »",
                      lambda a, b, poly=m.coins(): geometrie.dist_segment_polygone(a, b, poly)))
    for o in monde.objets:
        if not o.sur_la_carte:
            continue
        forme = o.empreinte()
        if forme[0] == "cercle":
            _, centre, rayon = forme
            liste.append((f"l'objet « {o.id} »",
                          lambda a, b, c=centre, r=rayon: max(0.0, geometrie.dist_point_segment(c, a, b) - r)))
        else:
            liste.append((f"l'objet « {o.id} »",
                          lambda a, b, poly=forme[1]: geometrie.dist_segment_polygone(a, b, poly)))
    return liste


def _de(nom):
    """« le mur « m1 » » → « du mur « m1 » » ; « l'objet « t1 » » → « de l'objet « t1 » »."""
    return "du " + nom[3:] if nom.startswith("le ") else "de " + nom


def _plus_proche(obstacles, a, b):
    """(distance, nom) de l'obstacle le plus proche du segment [a, b], ou (inf, None)."""
    return min(((distance(a, b), nom) for nom, distance in obstacles), default=(math.inf, None))


def _avertir_id(rapport, id, ou):
    if str(id).lower() in IDS_BOOLEENS:
        rapport.avertir(f"{ou} : l'id « {id} » est lu comme oui ou non par YAML s'il n'est pas entre "
                        "guillemets ; préférez un autre id")


def _accessibles(depart, couloirs):
    voisins = {}
    for a, b in couloirs:
        voisins.setdefault(a, set()).add(b)
        voisins.setdefault(b, set()).add(a)
    vus, file = {depart}, deque([depart])
    while file:
        for v in voisins.get(file.popleft(), ()):
            if v not in vus:
                vus.add(v)
                file.append(v)
    return vus


def _verifier_salles(lieu, r):
    etages = {e.id for e in lieu.etages}
    noeuds = lieu.itineraires.noeuds
    for s in lieu.salles:
        ou = f"salles.yaml, salle « {s.id} »"
        _avertir_id(r, s.id, ou)
        if s.etage not in etages:
            r.erreur(f"{ou} : l'étage « {s.etage} » n'existe pas dans lieu.yaml (étages : {', '.join(etages)})")
        n = noeuds.get(s.id)
        if n is None:
            r.erreur(f"{ou} : il n'y a pas de nœud « {s.id} » dans itineraires.yaml ; ajoutez dans noeuds : "
                     f"{s.id}: {{etage: {s.etage}, x: {nombre(s.pose.x)}, y: {nombre(s.pose.y)}}}")
        elif n.etage != s.etage or math.hypot(n.x - s.pose.x, n.y - s.pose.y) > TOLERANCE_POSITION:
            r.erreur(f"{ou} : le nœud « {s.id} » de itineraires.yaml n'est pas au même endroit "
                     f"(salle : {s.etage} {_pt(s.pose.x, s.pose.y)} ; nœud : {n.etage} {_pt(n.x, n.y)}) ; "
                     "mettez-les à la même position")
    _verifier_principal(lieu, r)


def _verifier_principal(lieu, r):
    """Un seul point principal par lieu, obligatoire (vague 4, section 11.2 du plan)."""
    marquees = salles_principales(lieu)
    if len(marquees) > 1:
        r.erreur(f"salles.yaml : {len(marquees)} salles portent l'étiquette « {ETIQUETTE_PRINCIPAL} » "
                 f"({', '.join(s.id for s in marquees)}) ; un lieu n'a qu'un point principal")
        return
    principal = point_principal(lieu)
    if principal is None:
        r.erreur(f"salles.yaml : le lieu n'a pas de point principal ; donnez l'étiquette « {ETIQUETTE_PRINCIPAL} » "
                 "à la salle où le robot accueille les visiteurs (onglet Salles), ou ajoutez une salle « accueil »")
        return
    # Sans étiquette (lieu d'avant la vague 4), le principal implicite est la salle « accueil » :
    # c'est valide, sans avertissement (lieux/demo, la référence des tests, reste ainsi).
    # « g1-lieu migrer » écrit l'étiquette, avec une sauvegarde.
    a, p = lieu.accueil, principal.pose
    if (principal.etage != a.etage or math.hypot(p.x - a.x, p.y - a.y) > TOLERANCE_POSITION
            or abs(p.theta - a.theta) > TOLERANCE_ANGLE):
        r.erreur(f"salles.yaml, salle « {principal.id} » : sa pose doit être celle de accueil dans lieu.yaml "
                 f"(etage: {a.etage}, x: {nombre(a.x)}, y: {nombre(a.y)}, theta: {nombre(a.theta)}), "
                 "car c'est le point principal du lieu")
    monde = lieu.mondes.get(principal.etage)
    if monde is not None:
        d = monde.depart_robot
        if math.hypot(d.x - p.x, d.y - p.y) > TOLERANCE_POSITION or abs(d.theta - p.theta) > TOLERANCE_ANGLE:
            r.avertir(f"mondes/{principal.etage}.monde.yaml, depart_robot ({nombre(d.x)}, {nombre(d.y)}, "
                      f"{nombre(d.theta)}) n'est pas le point principal « {principal.id} » ({nombre(p.x)}, "
                      f"{nombre(p.y)}, {nombre(p.theta)}) : la simulation ne partira pas de l'accueil ; "
                      "enregistrez le point principal dans l'onglet Salles, ou g1-lieu migrer")


def _verifier_itineraires(lieu, r):
    etages = {e.id for e in lieu.etages}
    itin = lieu.itineraires
    noeuds = itin.noeuds
    for id_noeud, n in noeuds.items():
        _avertir_id(r, id_noeud, f"itineraires.yaml, nœud « {id_noeud} »")
        if n.etage not in etages:
            r.erreur(f"itineraires.yaml, nœud « {id_noeud} » : l'étage « {n.etage} » n'existe pas dans "
                     f"lieu.yaml (étages : {', '.join(etages)})")
    vus, valides = set(), []
    for i, c in enumerate(itin.couloirs):
        ou = f"itineraires.yaml, couloir n°{i + 1} [{c.a}, {c.b}]"
        if c.a not in noeuds or c.b not in noeuds:
            continue          # déjà signalé à la lecture du fichier
        paire = frozenset((c.a, c.b))
        if paire in vus:
            r.avertir(f"{ou} : couloir en double ; retirez-le")
        vus.add(paire)
        if noeuds[c.a].etage != noeuds[c.b].etage:
            r.erreur(f"{ou} : ses nœuds sont sur deux étages ({noeuds[c.a].etage} et {noeuds[c.b].etage}) ; "
                     "un couloir reste sur un seul étage")
            continue
        longueur = itin.longueur(c)
        if longueur > COULOIR_MAX + 1e-9:
            r.erreur(f"{ou} : {longueur:.2f} m, plus de {COULOIR_MAX:g} m ; ajoutez un nœud entre les deux "
                     "(le vrai robot navigue par tronçons de 8 m au plus)")
        valides.append((c.a, c.b))
    relies = {n for c in valides for n in c}
    if len(noeuds) > 1:
        for id_noeud in noeuds:
            if id_noeud not in relies:
                r.avertir(f"itineraires.yaml, nœud « {id_noeud} » : il n'est relié à aucun couloir ; "
                          "le guide ne pourra ni y aller ni y passer")
    if "accueil" in noeuds:
        atteints = _accessibles("accueil", valides)
        for s in lieu.salles:
            n = noeuds.get(s.id)
            if (n is not None and s.id in relies and s.id not in atteints
                    and n.etage == noeuds["accueil"].etage):
                r.avertir(f"salles.yaml, salle « {s.id} » : aucun chemin depuis l'accueil dans itineraires.yaml")


def _verifier_zones(lieu, r):
    etages = {e.id for e in lieu.etages}
    noeuds = lieu.itineraires.noeuds
    for cle, mot in (("interdites", "zone interdite"), ("lentes", "zone lente")):
        for i, z in enumerate(getattr(lieu.zones, cle)):
            nom = f"zones.yaml, {mot} n°{i + 1}" + (f" (« {z.nom} »)" if z.nom else "")
            if z.etage not in etages:
                r.erreur(f"{nom} : l'étage « {z.etage} » n'existe pas dans lieu.yaml (étages : {', '.join(etages)})")
            if cle != "interdites":
                continue
            for id_noeud, n in noeuds.items():
                if n.etage == z.etage and geometrie.point_dans_polygone((n.x, n.y), z.polygone):
                    r.erreur(f"{nom} : le nœud « {id_noeud} » est dedans ; le robot ne pourra pas y aller. "
                             "Déplacez la zone ou le nœud")
            for c in lieu.itineraires.couloirs:
                if c.a in noeuds and c.b in noeuds and noeuds[c.a].etage == z.etage == noeuds[c.b].etage:
                    pa, pb = (noeuds[c.a].x, noeuds[c.a].y), (noeuds[c.b].x, noeuds[c.b].y)
                    if geometrie.dist_segment_polygone(pa, pb, z.polygone) <= 0:
                        r.erreur(f"{nom} : le couloir [{c.a}, {c.b}] la traverse ; déplacez la zone, ou faites "
                                 "passer le couloir à côté")
            monde = lieu.mondes.get(z.etage)
            if monde and geometrie.point_dans_polygone((monde.depart_robot.x, monde.depart_robot.y), z.polygone):
                r.avertir(f"{nom} : le départ du robot (depart_robot de mondes/{z.etage}.monde.yaml) est dedans")


def _verifier_carte_extrudee(lieu, id_etage, monde, fichier, r):
    """Vague 5 (section 12.5 du plan) : le maillage de la carte extrudée existe et n'est pas plus ancien
    que la carte de l'étage."""
    if monde.carte_extrudee is None or lieu.dossier is None:
        return
    stl = Path(lieu.dossier) / "mondes" / monde.carte_extrudee.fichier
    refaire = f"refaites-le : g1-monde generer --lieu {lieu.id} --etage {id_etage}"
    if not stl.is_file():
        r.avertir(f"{fichier}, carte_extrudee : le maillage mondes/{stl.name} est absent ; {refaire}")
        return
    carte = chemin_carte(lieu.dossier, id_etage)
    if carte.is_file() and carte.stat().st_mtime > stl.stat().st_mtime + 1:
        r.avertir(f"{fichier}, carte_extrudee : mondes/{stl.name} est plus ancien que cartes/{id_etage}.yaml ; {refaire}")


def _verifier_mondes(lieu, r):
    etages = {e.id: e for e in lieu.etages}
    noeuds = lieu.itineraires.noeuds
    for e in lieu.etages:
        if e.source_carte == "monde" and e.id not in lieu.mondes:
            r.avertir(f"étage « {e.id} » : pas encore de monde (mondes/{e.id}.monde.yaml) ; "
                      "dessinez-le dans l'Atelier")
    for id_etage, monde in lieu.mondes.items():
        fichier = f"mondes/{id_etage}.monde.yaml"
        if id_etage not in etages:
            r.avertir(f"{fichier} : l'étage « {id_etage} » n'existe pas dans lieu.yaml ; ce monde est ignoré")
            continue
        for id_element in monde.ids():
            _avertir_id(r, id_element, f"{fichier}, « {id_element} »")
        _verifier_carte_extrudee(lieu, id_etage, monde, fichier, r)
        obstacles = _obstacles(monde)
        depart = (monde.depart_robot.x, monde.depart_robot.y)
        d, nom = _plus_proche(obstacles, depart, depart)
        if d <= 0:
            r.erreur(f"{fichier}, depart_robot : le robot apparaîtrait dans {nom} ; déplacez le départ")
        elif d < RAYON_ROBOT:
            r.avertir(f"{fichier}, depart_robot : à {d:.2f} m {_de(nom)}, moins que le rayon du robot "
                      f"({RAYON_ROBOT:g} m)")
        for p in monde.pietons:
            trajet = p.trajet if p.aller_retour else p.trajet + p.trajet[:1]
            for a, b in zip(trajet, trajet[1:]):
                d, nom = _plus_proche(obstacles, a, b)
                if d <= 0:
                    r.avertir(f"{fichier}, piéton « {p.id} » : son trajet {_pt(*a)} → {_pt(*b)} traverse {nom}")
        if etages[id_etage].source_carte != "monde":
            continue      # étage scanné : le graphe se vérifie sur la carte du scan
        for id_noeud, n in noeuds.items():
            if n.etage != id_etage:
                continue
            d, nom = _plus_proche(obstacles, (n.x, n.y), (n.x, n.y))
            ou = f"itineraires.yaml, nœud « {id_noeud} »"
            if d <= 0:
                r.erreur(f"{ou} : il est dans {nom} ({fichier}) ; déplacez-le dans l'espace libre")
            elif d < RAYON_ROBOT:
                r.avertir(f"{ou} : à {d:.2f} m {_de(nom)}, moins que le rayon du robot ({RAYON_ROBOT:g} m)")
        for i, c in enumerate(lieu.itineraires.couloirs):
            if c.a not in noeuds or c.b not in noeuds or not (noeuds[c.a].etage == id_etage == noeuds[c.b].etage):
                continue
            pa, pb = (noeuds[c.a].x, noeuds[c.a].y), (noeuds[c.b].x, noeuds[c.b].y)
            d, nom = _plus_proche(obstacles, pa, pb)
            ou = f"itineraires.yaml, couloir n°{i + 1} [{c.a}, {c.b}]"
            if d <= 0:
                r.erreur(f"{ou} : il traverse {nom} ({fichier}) ; ajoutez un nœud pour le contourner, "
                         "ou laissez un passage")
            elif d < RAYON_ROBOT:
                r.avertir(f"{ou} : il passe à {d:.2f} m {_de(nom)}, moins que le rayon du robot ({RAYON_ROBOT:g} m)")


def _classe_pixel(valeur, info):
    """'occupe', 'libre' ou 'inconnu', comme map_server en mode trinary."""
    occupation = valeur / 255.0 if info.negate else (255 - valeur) / 255.0
    if occupation > info.occupied_thresh:
        return "occupe"
    if occupation < info.free_thresh:
        return "libre"
    return "inconnu"


def distance_obstacle_carte(x, y, info, image, portee=RAYON_ROBOT):
    """Distance (m) du point (x, y) au centre du pixel occupé le plus proche de la carte, cherché à moins de
    portee ; None s'il n'y en a pas si près. Comme map_server en mode trinary (seuils de la carte)."""
    import numpy as np
    col, lig = monde_vers_pixel(x, y, info)
    n = int(math.ceil(portee / info.resolution)) + 1
    c0, c1 = max(0, col - n), min(info.largeur, col + n + 1)
    l0, l1 = max(0, lig - n), min(info.hauteur, lig + n + 1)
    if c0 >= c1 or l0 >= l1:
        return None
    morceau = image[l0:l1, c0:c1].astype(float)
    occupation = morceau / 255.0 if info.negate else (255.0 - morceau) / 255.0
    lignes, colonnes = np.nonzero(occupation > info.occupied_thresh)
    if not len(lignes):
        return None
    px, py = pixel_vers_monde(colonnes + c0, lignes + l0, info)
    d = float(np.min(np.hypot(np.asarray(px) - x, np.asarray(py) - y)))
    return d if d < portee else None


def _graphe_sur_carte(lieu, id_etage, info, image, r, nom_carte):
    """Nœuds et couloirs d'un étage face aux pixels de sa carte (étage scanné)."""
    noeuds = lieu.itineraires.noeuds
    pas = info.resolution / 2

    def classes(a, b):
        n = max(1, int(math.ceil(math.dist(a, b) / pas)))
        vues = set()
        for k in range(n + 1):
            x, y = a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n
            col, lig = monde_vers_pixel(x, y, info)
            vues.add(_classe_pixel(int(image[lig, col]), info) if dans_image(col, lig, info) else "dehors")
        return vues

    for id_noeud, n in noeuds.items():
        if n.etage != id_etage:
            continue
        vues = classes((n.x, n.y), (n.x, n.y))
        ou = f"itineraires.yaml, nœud « {id_noeud} »"
        if "dehors" in vues:
            r.erreur(f"{ou} : {_pt(n.x, n.y)} est hors de la carte {nom_carte}")
        elif "occupe" in vues:
            r.erreur(f"{ou} : {_pt(n.x, n.y)} est sur un obstacle de la carte {nom_carte} ; déplacez-le")
        elif "inconnu" in vues:
            r.avertir(f"{ou} : {_pt(n.x, n.y)} est dans une partie inconnue de la carte {nom_carte}")
        else:
            # revue de la vague 5 : comme pour un monde dessiné, la marge du robot autour du nœud (et de la
            # salle de même identifiant) : Nav2 ne peut pas y amener le centre du robot
            d = distance_obstacle_carte(n.x, n.y, info, image)
            if d is not None:
                salle = " (et sa salle)" if any(s.id == id_noeud for s in lieu.salles) else ""
                r.avertir(f"{ou}{salle} : à {d:.2f} m d'un obstacle de la carte {nom_carte}, moins que le rayon "
                          f"du robot ({RAYON_ROBOT:g} m) ; écartez-le de l'obstacle (Placer)")
    for i, c in enumerate(lieu.itineraires.couloirs):
        if c.a not in noeuds or c.b not in noeuds or not (noeuds[c.a].etage == id_etage == noeuds[c.b].etage):
            continue
        vues = classes((noeuds[c.a].x, noeuds[c.a].y), (noeuds[c.b].x, noeuds[c.b].y))
        ou = f"itineraires.yaml, couloir n°{i + 1} [{c.a}, {c.b}]"
        if "dehors" in vues:
            r.erreur(f"{ou} : il sort de la carte {nom_carte}")
        elif "occupe" in vues:
            r.erreur(f"{ou} : il traverse un obstacle de la carte {nom_carte} ; ajoutez un nœud pour le contourner")
        elif "inconnu" in vues:
            r.avertir(f"{ou} : il passe par une partie inconnue de la carte {nom_carte}")


def _verifier_cartes(lieu, r):
    dossier = lieu.dossier
    id_lieu = lieu.id
    for e in lieu.etages:
        chemin = chemin_carte(dossier, e.id)
        nom = f"cartes/{e.id}.yaml"
        if not chemin.is_file():
            if e.source_carte == "monde" and e.id in lieu.mondes:
                r.avertir(f"étage « {e.id} » : pas encore de carte ({nom}) ; fabriquez-la : "
                          f"g1-monde generer --lieu {id_lieu} --etage {e.id}")
            elif e.source_carte == "scan":
                r.avertir(f"étage « {e.id} » : pas encore de carte ({nom}) ; fabriquez-la depuis le scan : "
                          f"g1-carte-2d --lieu {id_lieu} --etage {e.id}")
            continue
        try:
            info, image = charger_carte(chemin)
        except ErreurLieu as x:
            for m in x.erreurs:
                r.erreur(m)
            continue
        monde = chemin_monde(dossier, e.id)
        if (e.source_carte == "monde" and monde.is_file()
                and monde.stat().st_mtime > chemin.stat().st_mtime + 1):
            r.avertir(f"{nom} : plus ancienne que mondes/{e.id}.monde.yaml ; refabriquez-la : "
                      f"g1-monde generer --lieu {id_lieu} --etage {e.id}")
        for suffixe in ("_interdit", "_lent"):
            chemin_masque = chemin.parent / f"{e.id}{suffixe}.yaml"
            nom_masque = f"cartes/{e.id}{suffixe}.yaml"
            if not chemin_masque.is_file():
                if suffixe == "_interdit" and any(z.etage == e.id for z in lieu.zones.interdites):
                    r.avertir(f"étage « {e.id} » : pas de masque des zones interdites ({nom_masque}) ; "
                              f"fabriquez-le : g1-monde generer --lieu {id_lieu} --etage {e.id}")
                continue
            try:
                masque = charger_info_carte(chemin_masque)
            except ErreurLieu as x:
                for m in x.erreurs:
                    r.erreur(m)
                continue
            if ((masque.largeur, masque.hauteur) != (info.largeur, info.hauteur)
                    or not math.isclose(masque.resolution, info.resolution)
                    or any(abs(u - v) > 1e-6 for u, v in zip(masque.origin, info.origin))):
                r.erreur(f"{nom_masque} : le masque doit avoir la même taille, la même résolution et la même "
                         f"origine que la carte (masque : {masque.largeur} × {masque.hauteur} px à "
                         f"{nombre(masque.resolution)} m, origine {list(masque.origin)} ; carte : "
                         f"{info.largeur} × {info.hauteur} px à {nombre(info.resolution)} m, origine "
                         f"{list(info.origin)}) ; refabriquez-le : g1-monde generer --lieu {id_lieu} --etage {e.id}")
        if e.source_carte == "scan" or e.id not in lieu.mondes:
            _graphe_sur_carte(lieu, e.id, info, image, r, nom)


def verifier_lieu(lieu):
    """Règles entre fichiers et géométrie d'un Lieu chargé. Renvoie un Rapport.

    Erreurs : étage inconnu, salle sans nœud de même id et même position, accueil différent de
    lieu.yaml, couloir sur deux étages, de plus de 8 m, ou qui traverse un mur, un objet, une zone
    interdite ou un obstacle de la carte, nœud dans un obstacle ou une zone interdite, robot qui
    apparaît dans un mur, masque Keepout d'une autre taille que la carte.
    Avertissements : pas de salle accueil, nœud isolé, salle inaccessible, passage étroit,
    monde ou carte pas encore faits, carte plus ancienne que le monde, id lu comme un booléen.
    Vague 4 : les fichiers facultatifs de l'équipe (personnalites.yaml, dialogues.yaml, camera.yaml),
    par atelier.lieu.equipe.verifier_equipe, quand le lieu a un dossier. Vague 6 : demo.yaml (réglages de la démo).
    """
    r = Rapport(lieu=lieu)
    for e in lieu.etages:
        _avertir_id(r, e.id, f"lieu.yaml, étage « {e.id} »")
    _verifier_salles(lieu, r)
    _verifier_itineraires(lieu, r)
    _verifier_zones(lieu, r)
    _verifier_mondes(lieu, r)
    if lieu.dossier is not None:
        _verifier_cartes(lieu, r)
        _verifier_equipe(lieu, r)
        _verifier_demo(lieu, r)
    return r


def _verifier_demo(lieu, r):
    """demo.yaml (vague 6, section 13.4) : absent, rien à dire ; faux : ses erreurs ; une personnalité inconnue,
    un code opérateur absent : un avertissement."""
    from .accueil import charger_demo          # ici : accueil importe les modules que ce module importe aussi
    from .equipe import charger_equipe
    try:
        demo = charger_demo(lieu.dossier)
    except ErreurLieu as e:
        for m in e.erreurs:
            r.erreur(m)
        return
    if demo is None:
        return
    ident = demo.get("personnalite")
    if ident:
        try:
            personnalites = charger_equipe(lieu.dossier, "personnalites")
        except ErreurLieu:
            personnalites = None          # déjà signalé par _verifier_equipe
        ids = [p["id"] for p in (personnalites or {}).get("personnalites", [])]
        if personnalites is not None and ident not in ids:
            r.avertir(f"demo.yaml : la personnalité « {ident} » n'existe pas dans personnalites.yaml "
                      f"({', '.join(ids)}) ; la démo prendra la personnalité active")


def _verifier_equipe(lieu, r):
    """Fichiers de l'équipe (vague 4, section 11.6) : absents, rien à dire ; sinon leurs erreurs et avertissements."""
    from .equipe import verifier_equipe      # ici : equipe importe les modules que ce module importe aussi
    v = verifier_equipe(lieu.dossier)
    for m in v["erreurs"]:
        r.erreur(m)
    for m in v["avertissements"]:
        r.avertir(m)


def valider_lieu(lieu):
    """Lit et vérifie tout un dossier de lieu (chemin ou id seul). Ne lève jamais d'exception :
    tout est dans le Rapport renvoyé (rapport.ok, rapport.texte())."""
    r = Rapport()
    try:
        dossier = dossier_lieu(lieu)
    except ValueError as e:
        r.erreur(str(e))
        return r
    if not dossier.is_dir():
        r.erreur(f"le dossier {dossier} n'existe pas ; pour créer un lieu : g1-lieu creer ID --nom NOM")
        return r
    if not (dossier / FICHE).is_file():
        r.erreur(f"{dossier} : pas de lieu.yaml, ce dossier n'est pas un lieu ; "
                 "pour en créer un : g1-lieu creer ID --nom NOM")
        return r
    if not atelier.MOTIF_ID.match(dossier.name):
        r.avertir(f"le nom du dossier « {dossier.name} » n'est pas un identifiant de lieu valable "
                  f"({REGLE_ID}) ; renommez le dossier")
    for nom in (SALLES, ITINERAIRES, ZONES):
        if not (dossier / nom).exists():
            r.avertir(f"{nom} : fichier absent, pris comme vide ; il sera créé au prochain enregistrement")
    try:
        charge = charger_lieu(dossier)
    except ErreurLieu as e:
        for m in e.erreurs:
            r.erreur(m)
        r.avertir("les vérifications entre fichiers (salles, nœuds, couloirs, cartes) seront faites "
                  "une fois ces erreurs corrigées")
        return r
    ids_etages = {e.id for e in charge.etages}
    for f in sorted((dossier / "mondes").glob("*.monde.yaml")):
        id_etage = f.name[:-len(".monde.yaml")]
        if id_etage not in ids_etages:
            r.avertir(f"mondes/{f.name} : l'étage « {id_etage} » n'existe pas dans lieu.yaml ; ce monde est ignoré")
    r.ajouter(verifier_lieu(charge))
    return r
