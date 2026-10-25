"""Paquet de lieu : modèles, lecture, écriture, validation et conversions (agent Données).

Aucune dépendance à ROS : PyYAML et numpy suffisent (le Python du système, celui des nœuds
ROS 2, convient aussi : la validation des schémas n'utilise pas le paquet jsonschema).
Tout s'importe depuis atelier.lieu :

    from atelier.lieu import charger_lieu, enregistrer_lieu, ErreurLieu

API PUBLIQUE
============

Dossier d'un lieu
-----------------
Partout, « lieu » peut être un chemin (str ou Path), un id seul (« demo » désigne
$ATELIER_LIEUX/demo, voir atelier.chemin_lieu) ou un objet Lieu déjà chargé.

    dossier_lieu(lieu) -> Path
    chemin_monde(lieu, etage)     mondes/<etage>.monde.yaml
    chemin_sdf(lieu, etage)       mondes/<etage>.sdf
    chemin_carte(lieu, etage)     cartes/<etage>.yaml   (image : cartes/<etage>.pgm)
    chemin_interdit(lieu, etage)  cartes/<etage>_interdit.yaml   (masque Keepout)
    chemin_lent(lieu, etage)      cartes/<etage>_lent.yaml
    chemin_pcd(lieu, etage)       cartes/<etage>.pcd
    lister_lieux(dossier=None) -> [Path]   les lieux de $ATELIER_LIEUX (ceux qui ont un lieu.yaml)

Modèles (dataclasses, modeles.py)
---------------------------------
Chaque classe a vers_dict() (ce qu'on écrit dans le YAML) et depuis_dict(d) (classmethod).
Point = tuple (x, y) en mètres ; angles en radians.

    Lieu(nom, etages, accueil, langue="fr", carte_unitree=None, version=1,
         salles=[], itineraires=Itineraires(), zones=Zones(), mondes={}, dossier=None)
        .id (nom du dossier), .etage(id), .salle(id) ; vers_dict() = lieu.yaml seulement
    Etage(id, nom, source_carte="monde")            source_carte : "monde" ou "scan"
    PoseEtage(etage, x, y, theta)  .pose()           (accueil de lieu.yaml)
    Pose(x, y, theta=0.0)
    Salle(id, nom, etage, pose, alias=[], phrase_arrivee="")
    Itineraires(noeuds={id: Noeud}, couloirs=[Couloir])  .longueur(couloir), .voisins(id)
    Noeud(etage, x, y)                               (l'id est la clé du dictionnaire)
    Couloir(a, b)                                    dans le fichier : [a, b] ; a, b = couloir
    Zones(interdites=[Zone], lentes=[Zone])
    Zone(etage, polygone, nom="", vitesse_max=None)  vitesse_max : None pour une zone interdite
    Monde(emprise, depart_robot, murs=[], objets=[], pietons=[], version=1)  .ids(), .element(id)
    Emprise(xmin, ymin, xmax, ymax)                  .taille_x, .taille_y, .contient(x, y)
    Mur(id, de, a, epaisseur=0.15, hauteur=2.5)      .longueur, .cap, .centre, .coins()
    Objet(id, type, centre, cap=0.0, taille=None, rayon=None, hauteur=None, modele=None)
        Objet.boite(id, centre, taille, cap), Objet.cylindre(id, centre, rayon, hauteur),
        Objet.meuble(id, modele, centre, cap) ; .empreinte() -> ("cercle", centre, rayon)
        ou ("polygone", [4 coins]) ; .hauteur_totale()
    Pieton(id, trajet, vitesse=1.0, aller_retour=True)
    InfoCarte(image, resolution=0.05, origin=(x, y, 0.0), negate=0, occupied_thresh=0.65,
              free_thresh=0.196, largeur=None, hauteur=None, chemin=None, autres={})
        largeur, hauteur : taille de l'image en pixels (lue dans le .pgm) ; .chemin_image
    MODELES_MOBILIER   encombrement de chaise, table, banc (longueur, largeur, hauteur)
                       et poubelle (rayon, hauteur), en mètres

Lire et enregistrer (fichiers.py)
---------------------------------
Lecture et écriture valident chaque fichier (schéma JSON + règles propres au fichier : ids
uniques, polygone qui répète son premier sommet...) et lèvent ErreurLieu sinon. Les écritures
sont atomiques (fichier temporaire puis renommage) ; rien n'est écrit si la validation échoue.

    charger_lieu(lieu) -> Lieu         tout le paquet ; salles, itinéraires, zones absents = vides
    enregistrer_lieu(lieu, dossier=None) -> Path   lieu.yaml, salles, itinéraires, zones, mondes
    creer_lieu(lieu, nom, etage="rdc", nom_etage="Rez-de-chaussée", largeur=20.0, profondeur=15.0)
        -> Lieu   lieu neuf : accueil en (1, 1), salle et nœud accueil, monde entouré de 4 murs
    copier_lieu(source, destination) -> Path      ex. copie de lieux/demo pour un test
    charger_fiche(lieu) / enregistrer_fiche(lieu, dossier=None)          lieu.yaml seul
    charger_salles(lieu) -> [Salle]     / enregistrer_salles(lieu, salles)
    charger_itineraires(lieu) -> Itineraires / enregistrer_itineraires(lieu, itineraires)
    charger_zones(lieu) -> Zones        / enregistrer_zones(lieu, zones)
    charger_monde(lieu, etage) -> Monde / enregistrer_monde(lieu, etage, monde)
    charger_info_carte(chemin_yaml) -> InfoCarte   (.yaml Nav2 + taille du .pgm)
    enregistrer_info_carte(chemin_yaml, info)
    charger_carte(chemin_yaml) -> (InfoCarte, image)    image numpy (hauteur, largeur), uint8
    enregistrer_carte(chemin_yaml, info, image)          écrit le .pgm puis le .yaml
    lire_pgm(chemin) -> image ; ecrire_pgm(chemin, image) ; taille_pgm(chemin) -> (largeur, hauteur)
        image[0] = ligne du haut = y maximal. Pixels : 0 occupé, 254 libre, 205 inconnu.
    charger_fichier(chemin, type_fichier) -> données brutes validées
    enregistrer_fichier(chemin, type_fichier, donnees)
        type_fichier : "lieu", "monde", "salles", "itineraires", "zones" ou "carte"
    ecrire_atomique(chemin, texte_ou_octets) ; ecrire_yaml(chemin, donnees) (sans validation)
    ErreurLieu(Exception)   .erreurs : liste de messages en français, ex.
        « salles.yaml, salle « b204 » : il manque theta dans pose »

Valider
-------
    valider_donnees(type_fichier, donnees, fichier=None) -> [messages]
        un fichier seul, déjà lu (ex. le corps JSON d'un PUT de l'interface) ; [] si tout va bien
    verifier_lieu(lieu) -> Rapport      règles entre fichiers et géométrie, sur un Lieu chargé
    valider_lieu(lieu) -> Rapport       tout le dossier, sans lever d'exception (g1-lieu valider)
    Rapport : .erreurs, .avertissements (listes de messages), .ok, .texte(), .lieu
    Ces règles ne bloquent ni charger_lieu ni enregistrer_lieu : un lieu en cours de dessin
    peut être enregistré, puis vérifié.

Conversions (conversions.py) : le seul endroit où l'on passe des mètres aux pixels
----------------------------------------------------------------------------------
Image : (colonne, ligne) depuis le coin haut gauche ; la ligne 0 est le y MAXIMAL.
Les fonctions acceptent des nombres ou des tableaux numpy.

    monde_vers_pixel(x, y, info) -> (colonne, ligne)   pixel qui contient le point (peut sortir)
    pixel_vers_monde(colonne, ligne, info) -> (x, y)   centre du pixel
    dans_image(colonne, ligne, info) -> bool
    bornes_carte(info) -> (xmin, ymin, xmax, ymax)     bords de l'image, en mètres (Leaflet)
    centres_pixels(info) -> (X, Y)                     tableaux (hauteur, largeur)
    info_carte_pour_emprise(xmin, ymin, xmax, ymax, resolution=0.05, marge=1, image=...)
        -> InfoCarte d'une carte qui couvre ce rectangle plus la marge (en pixels)
    lire_info_carte(chemin_yaml) -> InfoCarte          = charger_info_carte
    cap_vers_quaternion(theta) -> (x, y, z, w)
    quaternion_vers_cap(q) -> theta dans ]-π, π]       q : tuple, dict ou geometry_msgs/Quaternion
    normaliser_angle(theta) -> angle dans [-π, π[

Constantes : COULOIR_MAX (8 m), RAYON_ROBOT (0,35 m), DOSSIER_SCHEMAS, TYPES_FICHIERS.
Commande : g1-lieu creer ID --nom NOM ; g1-lieu valider --lieu L ; g1-lieu liste.
"""
from .conversions import (bornes_carte, cap_vers_quaternion, centres_pixels, dans_image,
                          info_carte_pour_emprise, lire_info_carte, monde_vers_pixel,
                          normaliser_angle, pixel_vers_monde, quaternion_vers_cap)
from .fichiers import (ErreurLieu, charger_carte, charger_fiche, charger_fichier, charger_info_carte,
                       charger_itineraires, charger_lieu, charger_monde, charger_salles, charger_zones,
                       chemin_carte, chemin_interdit, chemin_lent, chemin_monde, chemin_pcd, chemin_sdf,
                       copier_lieu, creer_lieu, dossier_lieu, ecrire_atomique, ecrire_pgm, ecrire_yaml,
                       enregistrer_carte, enregistrer_fiche, enregistrer_fichier, enregistrer_info_carte,
                       enregistrer_itineraires, enregistrer_lieu, enregistrer_monde, enregistrer_salles,
                       enregistrer_zones, lire_pgm, lister_lieux, taille_pgm)
from .modeles import (MODELES_MOBILIER, Couloir, Emprise, Etage, InfoCarte, Itineraires, Lieu, Monde, Mur,
                      Noeud, Objet, Pieton, Pose, PoseEtage, Salle, Zone, Zones)
from .validation import DOSSIER_SCHEMAS, TYPES_FICHIERS, valider_donnees
from .verification import COULOIR_MAX, RAYON_ROBOT, Rapport, valider_lieu, verifier_lieu

__all__ = ["bornes_carte", "cap_vers_quaternion", "centres_pixels", "dans_image",
           "info_carte_pour_emprise", "lire_info_carte", "monde_vers_pixel", "normaliser_angle",
           "pixel_vers_monde", "quaternion_vers_cap", "ErreurLieu", "charger_carte", "charger_fiche",
           "charger_fichier", "charger_info_carte", "charger_itineraires", "charger_lieu",
           "charger_monde", "charger_salles", "charger_zones", "chemin_carte", "chemin_interdit",
           "chemin_lent", "chemin_monde", "chemin_pcd", "chemin_sdf", "copier_lieu", "creer_lieu",
           "dossier_lieu", "ecrire_atomique", "ecrire_pgm", "ecrire_yaml", "enregistrer_carte",
           "enregistrer_fiche", "enregistrer_fichier", "enregistrer_info_carte",
           "enregistrer_itineraires", "enregistrer_lieu", "enregistrer_monde", "enregistrer_salles",
           "enregistrer_zones", "lire_pgm", "lister_lieux", "taille_pgm", "MODELES_MOBILIER",
           "Couloir", "Emprise", "Etage", "InfoCarte", "Itineraires", "Lieu", "Monde", "Mur", "Noeud",
           "Objet", "Pieton", "Pose", "PoseEtage", "Salle", "Zone", "Zones", "DOSSIER_SCHEMAS",
           "TYPES_FICHIERS", "valider_donnees", "COULOIR_MAX", "RAYON_ROBOT", "Rapport",
           "valider_lieu", "verifier_lieu"]
