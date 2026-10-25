"""Générateur de monde : monde.yaml → monde Gazebo .sdf, carte 2D et masques (agent Monde).

Aucune dépendance à ROS ni à Gazebo : numpy et atelier.lieu suffisent.

    from atelier.monde import generer
    resultat = generer("demo", "rdc")      # lieu : chemin, id seul ou Lieu ; étage : son id
    print(resultat.texte())

API PUBLIQUE
============

Tout en une fois
----------------
    generer(lieu, etage) -> Generation
        écrit mondes/<etage>.sdf (+ mondes/pieton.dae s'il y a des piétons), cartes/<etage>.pgm
        et .yaml, puis cartes/<etage>_interdit.pgm et .yaml.
        Étage dont la carte vient du scan (source_carte: scan) : la carte n'est pas touchée ;
        le masque est aligné sur la carte du scan, si elle existe déjà.
        ErreurLieu (messages en français) si l'étage ou son monde manque, ou si un fichier est invalide.
    Generation : .sdf, .carte, .masque (chemins des .yaml, ou None), .murs, .objets, .pietons,
                 .zones_interdites (nombres), .taille_carte ((largeur, hauteur) en pixels ou None),
                 .remarques (messages), .texte() (compte rendu), .vers_dict() (pour le JSON du serveur)

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

from atelier.lieu import (ErreurLieu, charger_fiche, charger_info_carte, charger_monde, charger_zones,
                          chemin_carte, chemin_monde, dossier_lieu)

from .carte import INCONNU, LIBRE, OCCUPE, RESOLUTION, TRANCHE, ecrire_carte, fabriquer_carte
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
                          f"{self.pietons} piétons)")
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
                "murs": self.murs, "objets": self.objets, "pietons": self.pietons,
                "zones_interdites": self.zones_interdites,
                "taille_carte": list(self.taille_carte) if self.taille_carte else None,
                "remarques": list(self.remarques)}


def generer(lieu, etage):
    """Monde de l'étage → .sdf, carte 2D et masque Keepout, dans le dossier du lieu. Voir l'en-tête."""
    dossier = dossier_lieu(lieu)
    fiche = charger_fiche(dossier)
    info_etage = fiche.etage(etage)
    if info_etage is None:
        connus = ", ".join(e.id for e in fiche.etages)
        raise ErreurLieu(f"lieu.yaml : pas d'étage « {etage} » (étages du lieu : {connus})")
    resultat = Generation(lieu=dossier, etage=etage)
    scan = info_etage.source_carte == "scan"

    if chemin_monde(dossier, etage).is_file():
        monde = charger_monde(dossier, etage)
        resultat.sdf = ecrire_sdf(dossier, etage, monde)
        resultat.murs, resultat.objets, resultat.pietons = len(monde.murs), len(monde.objets), len(monde.pietons)
    elif not scan:
        raise ErreurLieu(f"mondes/{etage}.monde.yaml n'existe pas : dessinez d'abord le monde de l'étage "
                         f"« {etage} » dans l'Atelier (g1-atelier)")
    else:
        monde = None
        resultat.remarques.append(f"pas de monde inventé pour l'étage « {etage} » : pas de simulation possible")

    if scan:
        resultat.remarques.append(f"carte non modifiée : l'étage « {etage} » utilise la carte du scan "
                                  "(source_carte: scan dans lieu.yaml)")
        if chemin_carte(dossier, etage).is_file():
            info = charger_info_carte(chemin_carte(dossier, etage))
        else:
            info = None
            resultat.remarques.append(f"pas encore de carte du scan, donc pas de masque des zones interdites ; "
                                      f"fabriquez la carte : g1-carte-2d --lieu {dossier} --etage {etage}")
    else:
        resultat.carte, info = ecrire_carte(dossier, etage, monde)

    if info is not None:
        resultat.taille_carte = (info.largeur, info.hauteur)
        resultat.masque, resultat.zones_interdites = ecrire_masque_interdit(dossier, etage,
                                                                            charger_zones(dossier), info)
    return resultat


__all__ = ["Generation", "generer", "fabriquer_carte", "ecrire_carte", "fabriquer_masque_interdit",
           "ecrire_masque_interdit", "texte_sdf", "ecrire_sdf", "points_de_passage", "position_pieton",
           "duree_tour", "OCCUPE", "LIBRE", "INCONNU", "RESOLUTION", "TRANCHE"]
