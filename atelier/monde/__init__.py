"""Générateur de monde : monde.yaml → monde Gazebo .sdf, carte 2D et masques (agent Monde).

Aucune dépendance à ROS ni à Gazebo : numpy et atelier.lieu suffisent.

    from atelier.monde import generer
    resultat = generer("demo", "rdc")      # lieu : chemin, id seul ou Lieu ; étage : son id
    print(resultat.texte())

API PUBLIQUE
============

Tout en une fois
----------------
    generer(lieu, etage, hauteur_carte=None) -> Generation
        écrit mondes/<etage>.sdf (+ mondes/pieton.dae s'il y a des piétons), cartes/<etage>.pgm
        et .yaml, puis cartes/<etage>_interdit.pgm et .yaml.
        Étage dont la carte vient du scan (source_carte: scan) : la carte n'est pas touchée ;
        le masque est aligné sur la carte du scan. Vague 5 (section 12.5 du plan) : la carte du scan
        est extrudée en un seul maillage, mondes/<etage>_carte.stl (extrusion.py, hauteur 1,5 m par
        défaut, ou celle de carte_extrudee, ou hauteur_carte), et le monde reçoit carte_extrudee ;
        sans monde, un monde minimal est écrit (emprise de la carte, départ sur le point principal).
        ErreurLieu (messages en français) si l'étage ou son monde manque, ou si un fichier est invalide.
    Generation : .sdf, .carte, .masque, .maillage (chemins, ou None), .murs, .objets, .pietons,
                 .zones_interdites, .triangles (nombres), .taille_carte ((largeur, hauteur) en pixels
                 ou None), .remarques (messages), .texte() (compte rendu), .vers_dict() (JSON du serveur)

Carte extrudée (extrusion.py, vague 5)
--------------------------------------
    maillage_carte(info, image, hauteur) -> {sommets, faces, boites, pixels}
    ecrire_maillage_carte(lieu, etage, hauteur) ; ecrire_stl, lire_stl, rectangles, nettoyer
    monde_minimal(lieu, etage, info) : le monde d'un étage scanné qui n'en a pas

Carte 2D (carte.py)
-------------------
    fabriquer_carte(monde, image="carte.pgm") -> (InfoCarte, image numpy uint8)
        tranche de 0,1 à 1,5 m, 0,05 m par pixel, marge d'un pixel autour de l'emprise.
        0 : mur ou objet ; 254 : libre dans l'emprise ; 205 : marge non couverte par un mur.
        Les piétons n'y sont pas.
    ecrire_carte(lieu, etage, monde=None) -> (chemin du .yaml, InfoCarte)
    OCCUPE, LIBRE, INCONNU, RESOLUTION, TRANCHE

Masque Keepout (zones.py)
-------------------------
    fabriquer_masque_interdit(zones, etage, info_carte, image=...) -> (InfoCarte, image)
        même taille, résolution et origine que info_carte ; 0 dans les zones interdites, 254 ailleurs.
    ecrire_masque_interdit(lieu, etage, zones=None, info_carte=None) -> (chemin du .yaml, nb de zones)

Monde Gazebo (sdf.py)
---------------------
    texte_sdf(monde, nom="monde") -> texte SDF 1.9 ; le monde Gazebo s'appelle nom (l'id de l'étage)
    ecrire_sdf(lieu, etage, monde=None) -> chemin de mondes/<etage>.sdf

Piétons (pietons.py)
--------------------
    points_de_passage(pieton) -> [(t, x, y, cap)]   un tour complet, ceux du <script> du SDF
    position_pieton(pieton, t) -> (x, y, cap)        position au temps t de la simulation (s)
    duree_tour(pieton) -> s

Commande : g1-monde generer --lieu L --etage E ; g1-monde simuler --lieu L --etage E [--sans-fenetre].
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from atelier.lieu import (HAUTEUR_CARTE_EXTRUDEE, CarteExtrudee, Emprise, ErreurLieu, Monde, Pose, bornes_carte,
                          charger_fiche, charger_info_carte, charger_monde, charger_zones, chemin_carte,
                          chemin_maillage, chemin_monde, dossier_lieu, enregistrer_monde)

from .carte import INCONNU, LIBRE, OCCUPE, RESOLUTION, TRANCHE, ecrire_carte, fabriquer_carte
from .extrusion import ecrire_maillage_carte, ecrire_stl, lire_stl, maillage_carte, nettoyer, rectangles
from .pietons import duree_tour, points_de_passage, position_pieton
from .sdf import ecrire_sdf, texte_sdf
from .zones import ecrire_masque_interdit, fabriquer_masque_interdit


@dataclass
class Generation:
    """Ce que generer() a écrit. Chemins absolus, None pour ce qui n'a pas été fait."""
    lieu: Path
    etage: str
    sdf: Optional[Path] = None
    carte: Optional[Path] = None
    masque: Optional[Path] = None
    maillage: Optional[Path] = None
    triangles: int = 0
    murs: int = 0
    objets: int = 0
    pietons: int = 0
    zones_interdites: int = 0
    taille_carte: Optional[Tuple[int, int]] = None
    remarques: List[str] = field(default_factory=list)

    def texte(self):
        """Compte rendu en français, une ligne par fichier."""
        def court(chemin):
            return f"{chemin.parent.name}/{chemin.name}"
        lignes = []
        if self.sdf:
            lignes.append(f"  monde Gazebo : {court(self.sdf)} ({self.murs} murs, {self.objets} objets, "
                          f"{self.pietons} piétons" + (", la carte extrudée" if self.maillage else "") + ")")
        if self.maillage:
            lignes.append(f"  carte extrudée : {court(self.maillage)} ({self.triangles} triangles)")
        if self.carte:
            largeur, hauteur = self.taille_carte
            resolution = f"{RESOLUTION:g}".replace(".", ",")
            lignes.append(f"  carte 2D : {court(self.carte)} et {court(self.carte.with_suffix('.pgm'))} "
                          f"({largeur} × {hauteur} pixels de {resolution} m)")
        if self.masque:
            lignes.append(f"  zones interdites : {court(self.masque)} et {court(self.masque.with_suffix('.pgm'))} "
                          f"({self.zones_interdites} zone{'s' if self.zones_interdites > 1 else ''})")
        lignes += [f"  remarque : {r}" for r in self.remarques]
        return "\n".join(lignes)

    def vers_dict(self):
        return {"lieu": str(self.lieu), "etage": self.etage,
                "sdf": str(self.sdf) if self.sdf else None,
                "carte": str(self.carte) if self.carte else None,
                "masque": str(self.masque) if self.masque else None,
                "maillage": str(self.maillage) if self.maillage else None, "triangles": self.triangles,
                "murs": self.murs, "objets": self.objets, "pietons": self.pietons,
                "zones_interdites": self.zones_interdites,
                "taille_carte": list(self.taille_carte) if self.taille_carte else None,
                "remarques": list(self.remarques)}


def monde_minimal(lieu, etage, info):
    """Monde d'un étage scanné qui n'en a pas : emprise des bornes de la carte (et du point principal),
    départ sur le point principal (atelier.lieu.principal.depart_simulation), aucun mur."""
    from atelier.lieu.principal import depart_simulation
    xmin, ymin, xmax, ymax = (round(v, 3) for v in bornes_carte(info))
    depart = depart_simulation(lieu, etage) or Pose(round((xmin + xmax) / 2, 3), round((ymin + ymax) / 2, 3), 0.0)
    marge = 0.5                     # le départ doit être dans l'emprise (règle du monde)
    emprise = Emprise(min(xmin, round(depart.x - marge, 3)), min(ymin, round(depart.y - marge, 3)),
                      max(xmax, round(depart.x + marge, 3)), max(ymax, round(depart.y + marge, 3)))
    return Monde(emprise, Pose(depart.x, depart.y, depart.theta), [], [], [])


def _carte_extrudee(dossier, etage, info, resultat, hauteur_carte):
    """Étage scanné : le maillage de sa carte, puis carte_extrudee dans son monde (écrit s'il change).
    Renvoie le monde, ou None (remarque) si la carte n'a rien à extruder."""
    if chemin_monde(dossier, etage).is_file():
        monde = charger_monde(dossier, etage)
    else:
        monde = monde_minimal(dossier, etage, info)
        resultat.remarques.append(f"mondes/{etage}.monde.yaml écrit : monde minimal de l'étage scanné "
                                  "(emprise de la carte, départ sur le point principal)")
    hauteur = hauteur_carte or (monde.carte_extrudee.hauteur if monde.carte_extrudee else HAUTEUR_CARTE_EXTRUDEE)
    try:
        m = ecrire_maillage_carte(dossier, etage, hauteur)
    except ErreurLieu as e:
        resultat.remarques.append(f"pas de carte extrudée : {e.erreurs[0]}")
        return monde if chemin_monde(dossier, etage).is_file() else None
    resultat.maillage, resultat.triangles = m["fichier"], m["triangles"]
    voulu = CarteExtrudee(chemin_maillage(dossier, etage).name, float(hauteur))
    if monde.carte_extrudee != voulu or not chemin_monde(dossier, etage).is_file():
        monde.carte_extrudee = voulu
        enregistrer_monde(dossier, etage, monde)
    return monde


def generer(lieu, etage, hauteur_carte=None):
    """Monde de l'étage → .sdf, carte 2D et masque Keepout, dans le dossier du lieu ; pour un étage scanné,
    la carte extrudée d'abord (hauteur_carte : sa hauteur, en m). Voir l'en-tête."""
    dossier = dossier_lieu(lieu)
    fiche = charger_fiche(dossier)
    info_etage = fiche.etage(etage)
    if info_etage is None:
        connus = ", ".join(e.id for e in fiche.etages)
        raise ErreurLieu(f"lieu.yaml : pas d'étage « {etage} » (étages du lieu : {connus})")
    resultat = Generation(lieu=dossier, etage=etage)
    scan = info_etage.source_carte == "scan"
    info = None
    if scan and chemin_carte(dossier, etage).is_file():
        info = charger_info_carte(chemin_carte(dossier, etage))

    if scan and info is not None:
        monde = _carte_extrudee(dossier, etage, info, resultat, hauteur_carte)
    elif chemin_monde(dossier, etage).is_file():
        monde = charger_monde(dossier, etage)
    elif not scan:
        raise ErreurLieu(f"mondes/{etage}.monde.yaml n'existe pas : dessinez d'abord le monde de l'étage "
                         f"« {etage} » dans l'Atelier (g1-atelier)")
    else:
        monde = None
    if monde is not None:
        resultat.sdf = ecrire_sdf(dossier, etage, monde)
        resultat.murs, resultat.objets, resultat.pietons = len(monde.murs), len(monde.objets), len(monde.pietons)
    else:
        resultat.remarques.append(f"pas de monde pour l'étage « {etage} » : pas de simulation possible")

    if scan:
        resultat.remarques.append(f"carte non modifiée : l'étage « {etage} » utilise la carte du scan "
                                  "(source_carte: scan dans lieu.yaml)")
        if info is None:
            resultat.remarques.append(f"pas encore de carte du scan, donc pas de masque des zones interdites ; "
                                      f"faites un scan, puis « Utiliser cette carte » (g1-scan adopter)")
    else:
        resultat.carte, info = ecrire_carte(dossier, etage, monde)

    if info is not None:
        resultat.taille_carte = (info.largeur, info.hauteur)
        resultat.masque, resultat.zones_interdites = ecrire_masque_interdit(dossier, etage,
                                                                            charger_zones(dossier), info)
    return resultat


__all__ = ["Generation", "generer", "monde_minimal", "maillage_carte", "ecrire_maillage_carte", "ecrire_stl",
           "lire_stl", "rectangles", "nettoyer", "fabriquer_carte", "ecrire_carte", "fabriquer_masque_interdit",
           "ecrire_masque_interdit", "texte_sdf", "ecrire_sdf", "points_de_passage", "position_pieton",
           "duree_tour", "OCCUPE", "LIBRE", "INCONNU", "RESOLUTION", "TRANCHE"]
