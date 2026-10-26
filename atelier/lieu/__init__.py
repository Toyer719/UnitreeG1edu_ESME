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
    Etage(id, nom, source_carte="monde", repere_unitree=None)   source_carte : "monde" ou "scan" ;
        repere_unitree : Pose facultative (section 10 du plan), absente du fichier si None
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
    Mur(id, de, a, epaisseur=0.15, hauteur=2.5, source=None, confiance=None)
        .longueur, .cap, .centre, .coins()
    Objet(id, type, centre, cap=0.0, taille=None, rayon=None, hauteur=None, modele=None,
          categorie=None, source=None, confiance=None)
        Objet.boite(id, centre, taille, cap, **facultatifs), Objet.cylindre(id, centre, rayon, hauteur, ...),
        Objet.meuble(id, modele, centre, cap, ...) ; .empreinte() -> ("cercle", centre, rayon)
        ou ("polygone", [4 coins]) ; .hauteur_totale() ; .categorie_effective (categorie, sinon
        déduite : modele → son nom, cylindre → poteau, boite → meuble) ; .sur_la_carte (faux pour
        une personne)
        Champs facultatifs (section 9 du plan), absents du fichier quand ils valent None :
        categorie (CATEGORIES_OBJETS), source (« dessin » par défaut, ou « scan »), confiance (0 à 1).
    Pieton(id, trajet, vitesse=1.0, aller_retour=True)
    InfoCarte(image, resolution=0.05, origin=(x, y, 0.0), negate=0, occupied_thresh=0.65,
              free_thresh=0.196, largeur=None, hauteur=None, chemin=None, autres={})
        largeur, hauteur : taille de l'image en pixels (lue dans le .pgm) ; .chemin_image
    MODELES_MOBILIER   encombrement de chaise, table, banc (longueur, largeur, hauteur)
                       et poubelle (rayon, hauteur), en mètres
    CATEGORIES_OBJETS  table, chaise, banc, poteau, meuble, poubelle, personne, inconnu
    CATEGORIES_HORS_CARTE  (personne,) : jamais dessinée sur la carte 2D

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
    composer_poses(a, b), inverser_pose(a) -> (x, y, theta)     poses au sol (tuple, dict ou Pose)
    unitree_vers_carte(pose_unitree, repere), carte_vers_unitree(pose_carte, repere)

Vrai robot (robot.py, section 10 du plan) : repère d'Unitree, marque au sol, messages JSON
------------------------------------------------------------------------------------------
    repere_unitree(lieu, etage) -> Pose   origine de la carte d'Unitree dans le repère map de l'étage :
        champ repere_unitree de l'étage ; sinon (0, 0, 0) pour source_carte scan, depart_robot du
        monde pour source_carte monde
    marque_au_sol(lieu, etage) -> Pose    où poser le robot avant « Repérer le robot » (= repere_unitree)
    pose_unitree_depuis_carte(pose, lieu, etage), pose_carte_depuis_unitree(pose, lieu, etage)
    carte_pour_reperage(lieu, repetition=False) -> nom du .pcd pour 1804, ou None
    valider_message("etat_pont" | "etat_reperage" | "demande_reperage", donnees) -> [messages]
    Constantes : LIMITES_PONT, DUREE_CONSIGNE_S, DELAI_CMD_VEL_S, FREQUENCE_PONT_HZ, GARDE_APRES_STOP_S,
    CARTE_REPETITION, DELAI_REPERAGE_S, DELAI_PERDU_S, ECART_MAX_M, ECART_MAX_RAD, ETATS_PONT,
    ETATS_REPERAGE, LOCALISATIONS, MODES_NAVIGATION, EXEMPLE_ETAT_PONT, EXEMPLE_ETAT_REPERAGE...

Vague 4 (section 11 du plan) : modules de contrat, un par agent (importer le module pour le reste)
---------------------------------------------------------------------------------------------------
    principal.py   (A) point_principal(lieu) -> Salle | None, pose_principale(lieu), principal_explicite,
                   pose_de_reperage(lieu, etage), depart_simulation(lieu, etage), ETIQUETTE_PRINCIPAL ;
                   à écrire : definir_principal, synchroniser_depart, sauvegarder_lieu, migrer_lieu
    passants.py    (B) reglages_pieton, distance_bord, cause_contact, SuiviContacts, COLONNES_BANC_V4…
    comportement.py (C) ETATS_GUIDE, CODES_EVENEMENT, DELAIS_GUIDE, reglages_guide(lieu),
                   lire_demande_aller(texte), evenement(code, ...)
    pilotage.py    (D) refus_commande, confirmation_requise, POSTURES, DANSES_INTERDITES, GESTES_BRAS,
                   LIMITES_BRAS, verifier_choregraphie, charger_choregraphie, poses_bras…
    equipe.py      (E) charger_equipe / enregistrer_equipe / valider_equipe (personnalites, dialogues,
                   camera), SUJETS_EQUIPE
    Champs ajoutés : Salle.etiquettes, Pieton (reaction, distance_reaction_m, corps, rayon_m, pauses,
    depart_s, repeter, pilote), Lieu.guide ; valider_message connaît les messages de la vague 4.

Sessions de scan intégré (scans.py, section 9 du plan) : LIEU/scans/<session>/
--------------------------------------------------------------------------------
Identifiant de session : AAAA-MM-JJ_HHhMM (suffixe -2, -3... si la minute est prise). Fichiers :
FICHIERS_SESSION (session.json, apercu.png/json, nuage.pcd, carte.pgm/yaml, reconnaissance.yaml,
monde_scan.monde.yaml, rapport.json, enregistrement/). Écritures atomiques, et verrou entre processus.

    creer_session(lieu, etage, mode, nom=None, repetition=False, explorer=False) -> dict
        dossier et session.json (etat en_cours, etape preparation) ; ErreurLieu si un autre scan du
        lieu est actif. mode : robot ou simu.
    lire_session(lieu, session) -> dict ; ecrire_session(lieu, donnees) ; maj_session(lieu, session, **champs)
    lister_sessions(lieu) -> [dict] (plus récente d'abord) ; session_active(lieu) ; derniere_session(lieu)
    dossier_scans(lieu), dossier_session(lieu, session), chemin_session(lieu, session, quoi="session")
    infos_processus(pid=None) -> {pid, debut, hote} ; processus_vivant(session) ; session_interrompue(session)
    progression_etape(etape, fraction=0.0) -> 0..100 (PLAGES_PROGRESSION)
    etat_scan(lieu, session=None) -> dict    sortie de « g1-scan etat --json » et de GET /api/scan/etat
    nouvelle_reconnaissance(etage, emprise, depart_robot, session=None, sol=None, parametres=None) -> dict
    lire_reconnaissance(chemin) / ecrire_reconnaissance(chemin, donnees) ; valider_reconnaissance(donnees)
    a_garder_par_defaut(categorie) ; resume_reconnaissance(donnees)
    monde_depuis_reconnaissance(donnees) -> Monde ; ecrire_monde_scan(chemin, donnees) -> Monde
    reconnaissance_depuis_monde(monde, etage, session=None) -> dict   vérité terrain d'un monde dessiné
    passages_du_monde(monde) -> [{de, a, murs, largeur}]
    changer_a_garder(lieu, session, {id: bool}) -> {reconnaissance, monde, resume}
    carte_sans_elements_retires(info, image, donnees) -> image   (objets retirés et personnes effacés)
    Constantes : MODES, ETATS, ETATS_ACTIFS, ETAPES, SUJETS_PAR_MODE, APERCU_POINTS_MAX, PERIODE_APERCU...

Géométrie des passages (geometrie.py) : PASSAGE_MIN (0,7 m), PASSAGE_MAX (1,6 m), murs_alignes,
trou_entre, est_passage.

Constantes : COULOIR_MAX (8 m), RAYON_ROBOT (0,35 m), DOSSIER_SCHEMAS, TYPES_FICHIERS.
Commande : g1-lieu creer ID --nom NOM ; g1-lieu valider --lieu L ; g1-lieu liste.
"""
from .conversions import (bornes_carte, cap_vers_quaternion, carte_vers_unitree, centres_pixels,
                          composer_poses, dans_image, info_carte_pour_emprise, inverser_pose,
                          lire_info_carte, monde_vers_pixel, normaliser_angle, pixel_vers_monde,
                          quaternion_vers_cap, unitree_vers_carte)
from .fichiers import (ErreurLieu, charger_carte, charger_fiche, charger_fichier, charger_info_carte,
                       charger_itineraires, charger_lieu, charger_monde, charger_salles, charger_zones,
                       chemin_carte, chemin_interdit, chemin_lent, chemin_monde, chemin_pcd, chemin_sdf,
                       copier_lieu, creer_lieu, dossier_lieu, ecrire_atomique, ecrire_pgm, ecrire_yaml,
                       enregistrer_carte, enregistrer_fiche, enregistrer_fichier, enregistrer_info_carte,
                       enregistrer_itineraires, enregistrer_lieu, enregistrer_monde, enregistrer_salles,
                       enregistrer_zones, lire_pgm, lister_lieux, taille_pgm)
from .geometrie import PASSAGE_MAX, PASSAGE_MIN, est_passage, murs_alignes, trou_entre
from .modeles import (CATEGORIES_HORS_CARTE, CATEGORIES_OBJETS, MODELES_MOBILIER, SOURCES_ELEMENT, Couloir,
                      Emprise, Etage, InfoCarte, Itineraires, Lieu, Monde, Mur, Noeud, Objet, Pieton, Pose,
                      PoseEtage, Salle, Zone, Zones)
from .scans import (APERCU_POINTS_MAX, APERCU_TRAJECTOIRE_MAX, ETAPES, ETAPES_TRAITEMENT, ETATS, ETATS_ACTIFS,
                    FICHIERS_SESSION, MODES, PERIODE_APERCU, PERIODE_SESSION, PLAGES_PROGRESSION,
                    SUJETS_AUTRES, SUJETS_PAR_MODE, a_garder_par_defaut, carte_sans_elements_retires,
                    changer_a_garder, chemin_session, creer_session, derniere_session, dossier_scans,
                    dossier_session, ecrire_monde_scan, ecrire_reconnaissance, ecrire_session, etat_scan,
                    fichiers_presents, infos_processus, lire_reconnaissance, lire_session, lister_sessions,
                    maj_session, monde_depuis_reconnaissance, nouvelle_reconnaissance, passages_du_monde,
                    processus_vivant, progression_etape, reconnaissance_depuis_monde, resume_reconnaissance,
                    session_active, session_interrompue,
                    valider_reconnaissance, verifier_id_session, verrou_session)
from .robot import (API_RELOCALISER, API_SPORT_SET_VELOCITY, CARTE_REPETITION, DELAI_CMD_VEL_S, DELAI_PERDU_S,
                    DELAI_REPERAGE_PERIME_S, DELAI_REPERAGE_S, DELAI_ROBOT_MUET_S, DERIVE_ECHELLE,
                    DERIVE_LACET_PAR_M, DUREE_ARRET_S, DUREE_CONSIGNE_S, ECART_MAX_M, ECART_MAX_RAD,
                    ETATS_PONT, ETATS_REPERAGE, EXEMPLE_DEMANDE_REPERAGE, EXEMPLE_ETAT_PONT,
                    EXEMPLE_ETAT_REPERAGE, FREQUENCE_PONT_HZ, GARDE_APRES_STOP_S, HAUTEUR_PELVIS, LIMITES_PONT,
                    LOCALISATIONS, MODES_NAVIGATION, SAUT_M, SAUT_RAD, carte_pour_reperage, marque_au_sol,
                    pose_carte_depuis_unitree, pose_unitree_depuis_carte, repere_unitree, valider_message)
from .validation import DOSSIER_SCHEMAS, TYPES_FICHIERS, TYPES_MESSAGES, valider_donnees
from .verification import COULOIR_MAX, RAYON_ROBOT, Rapport, valider_lieu, verifier_lieu
# vague 4 (section 11 du plan) : l'essentiel des modules de contrat
from .modeles import ETIQUETTE_PRINCIPAL
from .principal import (depart_simulation, point_principal, pose_de_reperage, pose_principale,
                        principal_explicite)
from .comportement import CODES_EVENEMENT, DELAIS_GUIDE, ETATS_GUIDE, lire_demande_aller, reglages_guide
from .passants import distance_bord, cause_contact
from .pilotage import confirmation_requise, refus_commande, verifier_choregraphie
from .equipe import FICHIERS_EQUIPE, charger_equipe, enregistrer_equipe, valider_equipe
from . import comportement, equipe, passants, pilotage, principal

__all__ = ["bornes_carte", "cap_vers_quaternion", "centres_pixels", "dans_image",
           "carte_vers_unitree", "composer_poses", "inverser_pose", "unitree_vers_carte",
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
           "valider_lieu", "verifier_lieu",
           # géométrie des passages
           "PASSAGE_MAX", "PASSAGE_MIN", "est_passage", "murs_alignes", "trou_entre",
           # catégories et sources des éléments
           "CATEGORIES_HORS_CARTE", "CATEGORIES_OBJETS", "SOURCES_ELEMENT",
           # sessions de scan intégré
           "APERCU_POINTS_MAX", "APERCU_TRAJECTOIRE_MAX", "ETAPES", "ETAPES_TRAITEMENT", "ETATS", "ETATS_ACTIFS",
           "FICHIERS_SESSION", "MODES", "PERIODE_APERCU", "PERIODE_SESSION", "PLAGES_PROGRESSION",
           "SUJETS_AUTRES", "SUJETS_PAR_MODE", "a_garder_par_defaut", "carte_sans_elements_retires",
           "changer_a_garder", "chemin_session", "creer_session", "derniere_session", "dossier_scans",
           "dossier_session", "ecrire_monde_scan", "ecrire_reconnaissance", "ecrire_session", "etat_scan",
           "fichiers_presents", "infos_processus", "lire_reconnaissance", "lire_session", "lister_sessions",
           "maj_session", "monde_depuis_reconnaissance", "nouvelle_reconnaissance", "passages_du_monde",
           "processus_vivant", "progression_etape", "reconnaissance_depuis_monde", "resume_reconnaissance",
           "session_active", "session_interrompue",
           "valider_reconnaissance", "verifier_id_session", "verrou_session",
           # vrai robot (section 10 du plan)
           "API_RELOCALISER", "API_SPORT_SET_VELOCITY", "CARTE_REPETITION", "DELAI_CMD_VEL_S", "DELAI_PERDU_S",
           "DELAI_REPERAGE_PERIME_S", "DELAI_REPERAGE_S", "DELAI_ROBOT_MUET_S", "DERIVE_ECHELLE",
           "DERIVE_LACET_PAR_M", "DUREE_ARRET_S", "DUREE_CONSIGNE_S", "ECART_MAX_M", "ECART_MAX_RAD",
           "ETATS_PONT", "ETATS_REPERAGE", "EXEMPLE_DEMANDE_REPERAGE", "EXEMPLE_ETAT_PONT",
           "EXEMPLE_ETAT_REPERAGE", "FREQUENCE_PONT_HZ", "GARDE_APRES_STOP_S", "HAUTEUR_PELVIS", "LIMITES_PONT",
           "LOCALISATIONS", "MODES_NAVIGATION", "SAUT_M", "SAUT_RAD", "carte_pour_reperage", "marque_au_sol",
           "pose_carte_depuis_unitree", "pose_unitree_depuis_carte", "repere_unitree", "valider_message",
           # vague 4 (section 11 du plan)
           "TYPES_MESSAGES", "ETIQUETTE_PRINCIPAL", "depart_simulation", "point_principal", "pose_de_reperage",
           "pose_principale", "principal_explicite", "CODES_EVENEMENT", "DELAIS_GUIDE", "ETATS_GUIDE",
           "lire_demande_aller", "reglages_guide", "distance_bord", "cause_contact", "confirmation_requise",
           "refus_commande", "verifier_choregraphie", "FICHIERS_EQUIPE", "charger_equipe", "enregistrer_equipe",
           "valider_equipe", "comportement", "equipe", "passants", "pilotage", "principal"]
