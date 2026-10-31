"""Les emplacements de l'équipe (vague 4, section 11.6 du plan) : fichiers du lieu et sujets ROS 2.

L'équipe de l'utilisateur fait la caméra See3CAM, le chatbot à règles et les modes de personnalité.
L'Atelier leur prépare :
  - trois fichiers facultatifs du lieu, avec leurs schémas : personnalites.yaml, dialogues.yaml et
    camera.yaml (exemples : atelier/lieu/exemples/) ; charger_equipe, enregistrer_equipe et
    valider_equipe les lisent, les écrivent (atomique, validé) et les vérifient ;
  - des sujets ROS 2 entre les parties (SUJETS_EQUIPE) : ce que dit le visiteur, les visiteurs vus
    par la caméra, la personnalité active, les phrases à dire, et la demande de guidage.

En plus du contrat (agent Équipe) :
  - normaliser(texte) : la forme sans majuscules, accents ni ponctuation qui sert à comparer les
    phrases du visiteur aux motifs de dialogues.yaml (le chatbot est dans atelier/equipe/) ;
  - verifier_equipe(lieu) : ce que les schémas ne voient pas, entre les trois fichiers et avec
    salles.yaml (personnalité inconnue d'une règle, motif jamais utilisé, caméra mal placée…) ;
  - les messages des sujets : message_robot_dire, message_personnalite_active, personnalite_active ;
  - PREREGLAGES_CAMERA : les réglages de départ de la See3CAM_11CUG.

Ce module ne dépend que de la bibliothèque standard et d'atelier.lieu : il tourne aussi dans le
conteneur du Jetson (Python du système, sans jsonschema).

Fichier de l'agent Équipe (vague 4). Les fonctions et valeurs marquées « contrat » sont livrées et
testées par l'intégrateur (atelier/tests/test_contrats_vague4.py) : elles gardent leur nom, leurs
arguments et leur comportement.
"""
import re
import unicodedata
from datetime import datetime
from pathlib import Path

from .fichiers import ErreurLieu, charger_fichier, charger_salles, dossier_lieu, ecrire_yaml, lire_yaml
from .validation import valider_donnees

# ---------------------------------------------------------------- valeurs du contrat

FICHIERS_EQUIPE = {"personnalites": "personnalites.yaml", "dialogues": "dialogues.yaml", "camera": "camera.yaml"}
DOSSIER_EXEMPLES = Path(__file__).resolve().parent / "exemples"
ENTETES_EQUIPE = {
    "personnalites": "Modes de personnalité du robot. Format : atelier/lieu/schemas/personnalites.schema.json.",
    "dialogues": "Chatbot à règles du lieu. Format : atelier/lieu/schemas/dialogues.schema.json.",
    "camera": "Caméra du robot et détection des visiteurs. Format : atelier/lieu/schemas/camera.schema.json.",
}
ACTIONS_DIALOGUE = ("guider", "dire", "personnalite", "stop", "geste")

# Sujets ROS 2 entre les parties (section 11.6) : sujet → (type, schéma JSON ou None, qui publie)
SUJETS_EQUIPE = {
    "/visiteur/texte": ("std_msgs/String", None, "reconnaissance vocale de l'équipe (texte brut, en français)"),
    "/visiteurs/detectes": ("std_msgs/String", "personnes", "caméra de l'équipe (camera.yaml)"),
    "/personnalite/active": ("std_msgs/String", "personnalite_active", "gestion des personnalités (fiable, transient_local)"),
    "/robot/dire": ("std_msgs/String", "robot_dire", "chatbot, relais des événements du guide, chorégraphies"),
    "/guide/aller": ("std_msgs/String", "demande_guide", "chatbot (JSON {cible, accompagner, source})"),
    "/guide/evenement": ("std_msgs/String", "evenement_guide", "guide (relayé vers /robot/dire)"),
    # assemblage de la vague 4 : gestes des bras demandés par le chatbot, faits par le nœud pilotage
    "/robot/geste": ("std_msgs/String", "robot_geste", "chatbot (action geste, geste_salut de la personnalité)"),
    # vague 5 (section 12.7 du plan) : état du nœud de la caméra de poitrine (See3CAM)
    "/camera_poitrine/etat": ("std_msgs/String", "etat_camera", "nœud camera_usb (g1_equipe), 1 Hz"),
}

# Vague 5 (section 12.7 du plan) : sujets d'images (sensor_msgs/CompressedImage, JPEG), à part de
# SUJETS_EQUIPE qui ne contient que des std_msgs/String : sujet → (type, qui publie)
SUJETS_IMAGES = {
    "/camera_poitrine/image/compressed": ("sensor_msgs/CompressedImage",
                                          "nœud camera_usb (g1_equipe) : la See3CAM, 10 Hz, JPEG de 640 pixels de large"),
    "/visiteurs/image/compressed": ("sensor_msgs/CompressedImage",
                                    "g1-visiteurs --image (PC) : la même image avec les cadres dessinés, 2 à 5 Hz"),
}
SUJET_IMAGE_POITRINE = "/camera_poitrine/image/compressed"
SUJET_ETAT_CAMERA = "/camera_poitrine/etat"
CAMERA_CONTENEUR = "/dev/g1_camera"         # la See3CAM dans le conteneur du Jetson (docker run --device)

EXEMPLE_ROBOT_DIRE = {"version": 1, "texte": "Je vous emmène à la Salle B204. Suivez-moi !", "source": "dialogue",
                      "priorite": "normale"}
EXEMPLE_PERSONNALITE_ACTIVE = {"version": 1, "id": "accueillant", "nom": "Accueillant", "lieu": "demo"}


# ---------------------------------------------------------------- contrat (livré par l'intégrateur)

def _quoi(quoi):
    if quoi not in FICHIERS_EQUIPE:
        raise ValueError(f"fichier de l'équipe inconnu : {quoi} ({', '.join(FICHIERS_EQUIPE)})")
    return quoi


def chemin_equipe(lieu, quoi):
    """Contrat. lieux/<id>/<quoi>.yaml (quoi : personnalites, dialogues ou camera)."""
    return dossier_lieu(lieu) / FICHIERS_EQUIPE[_quoi(quoi)]


def exemple_equipe(quoi):
    """Contrat. Contenu de l'exemple livré (atelier/lieu/exemples/<quoi>.yaml), déjà vérifié."""
    chemin = DOSSIER_EXEMPLES / FICHIERS_EQUIPE[_quoi(quoi)]
    return lire_yaml(chemin.read_text(encoding="utf-8"), chemin.name)


def valider_equipe(quoi, donnees, fichier=None):
    """Contrat. Erreurs (en français) d'un fichier de l'équipe : schéma, puis règles. [] si tout va bien."""
    return valider_donnees(_quoi(quoi), donnees, fichier or FICHIERS_EQUIPE[quoi])


def charger_equipe(lieu, quoi):
    """Contrat. Contenu du fichier de l'équipe du lieu, vérifié ; None s'il n'existe pas (le lieu
    s'en passe). ErreurLieu s'il est faux."""
    chemin = chemin_equipe(lieu, quoi)
    if not chemin.is_file():
        return None
    return charger_fichier(chemin, quoi)


def enregistrer_equipe(lieu, quoi, donnees):
    """Contrat. Écrit le fichier de l'équipe (atomique) après l'avoir vérifié. ErreurLieu sinon.
    Renvoie le chemin."""
    erreurs = valider_equipe(quoi, donnees)
    if erreurs:
        raise ErreurLieu(erreurs)
    chemin = chemin_equipe(lieu, quoi)
    ecrire_yaml(chemin, donnees, ENTETES_EQUIPE[quoi])
    return chemin


# ---------------------------------------------------------------- agent Équipe : valeurs

# Repères des motifs de dialogues.yaml et des réponses (schéma dialogues)
REPERE_SALLE = "{salle}"            # motif : une salle du lieu (id, nom ou alias de salles.yaml)
REPERE_JOKER = "{*}"                # motif : n'importe quels mots (aucun compris)
REPERES_MOTIF = (REPERE_SALLE, REPERE_JOKER)
REPERES_REPONSE = ("{nom_salle}", "{salle}")     # réponse d'une règle guider : nom et id de la salle
REPERES_PHRASE = ("{nom}",)                       # phrases d'une personnalité : nom de la salle visée
_REPERE = re.compile(r"\{[^{}]*\}")

SOURCES_DIRE = ("guide", "dialogue", "personnalite", "choregraphie", "atelier", "autre")     # schéma robot_dire

# Réglages de départ d'une caméra connue (onglet Caméra, « Préréglage »). La See3CAM_11CUG d'e-con
# Systems est une caméra couleur USB 3 (UVC) de 1,3 mégapixel, à objectif interchangeable (M12) :
# son champ de vision dépend de l'objectif monté, et ses modes d'image sont à lire sur la caméra
# (v4l2-ctl -d /dev/videoN --list-formats-ext). Valeurs à vérifier, comme la position sur le robot.
PREREGLAGES_CAMERA = {
    "See3CAM_11CUG": {
        "modele": "See3CAM_11CUG",
        "largeur": 1280, "hauteur": 720, "ips": 30,
        "note": "Caméra couleur USB 3 de 1,3 mégapixel (e-con Systems), objectif M12 interchangeable. "
                "Mode 1280 × 720 à 30 images par seconde (YUYV), vérifié sur la See3CAM du PC le 31/10 "
                "(elle fait aussi 1280 × 960 à 20 et 640 × 480 à 60 ou 30 : « v4l2-ctl -d /dev/videoN "
                "--list-formats-ext »). Branchez-la en USB 3 (port bleu). Le champ de vision dépend de "
                "l'objectif : lisez sa fiche, ou mesurez-le (une règle à 1 m, d'un bord à l'autre de l'image).",
    },
}
MODES_IMAGE_11CUG = ((1280, 960), (1280, 720), (640, 480))   # modes UVC habituels, à confirmer sur la caméra

# Sens des valeurs de la caméra, pour la vérification (avertissements seulement)
HAUTEUR_CAMERA_M = (0.5, 1.6)      # G1 debout : la poitrine est vers 1 m, la tête vers 1,3 m
TANGAGE_MAX_RAD = 0.6              # au-delà, la caméra regarde surtout le sol ou le plafond
ROULIS_MAX_RAD = 0.35              # caméra penchée sur le côté
# Vague 5 : le vrai robot ne fait aucun pas sous 0,2 m/s (mesuré le 27/10 ; atelier.lieu.robot.VITESSE_MAX_MIN,
# comparé par les tests) : une vitesse_max de personnalité plus basse n'y a pas d'effet
VITESSE_PAS_MIN = 0.2


# ---------------------------------------------------------------- agent Équipe : textes

def normaliser(texte):
    """Forme d'un texte pour comparer une phrase aux motifs : minuscules, sans accents (é → e,
    œ → oe), toute ponctuation (y compris l'apostrophe, « _ » et « - ») remplacée par un espace,
    espaces réduits. « Emmène-moi à l'Accueil ! » → « emmene moi a l accueil »."""
    texte = str(texte).replace("œ", "oe").replace("Œ", "oe").replace("æ", "ae").replace("Æ", "ae")
    texte = unicodedata.normalize("NFKD", texte)
    texte = "".join(c for c in texte if not unicodedata.combining(c)).lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", texte).split())


def reperes(texte):
    """Repères {…} d'un texte, dans l'ordre (« je cherche {salle} » → ["{salle}"])."""
    return _REPERE.findall(str(texte))


def jetons_motif(motif):
    """Mots normalisés d'un motif de dialogues.yaml, avec les repères {salle} et {*} gardés tels quels :
    « Où est {salle} ? » → ["ou", "est", "{salle}"]. Un autre repère ({piece}…) devient un mot ordinaire
    (verifier_equipe le signale : il ne correspondra jamais)."""
    jetons = []
    for morceau in re.split(r"(\{salle\}|\{\*\})", str(motif)):
        if morceau in REPERES_MOTIF:
            jetons.append(morceau)
        else:
            jetons += normaliser(morceau).split()
    return jetons


def formes_salles(salles):
    """{forme normalisée: id de salle} pour l'id, le nom et chaque alias de chaque salle ; une forme
    partagée par deux salles va à la première (verifier_equipe le signale). salles : Salle ou dict."""
    formes = {}
    for s in salles:
        ident, nom, alias = _champs_salle(s)
        for texte in [ident, nom, *alias]:
            forme = normaliser(texte)
            if forme:
                formes.setdefault(forme, ident)
    return formes


def _champs_salle(s):
    if isinstance(s, dict):
        return s["id"], s.get("nom", s["id"]), list(s.get("alias") or [])
    return s.id, s.nom, list(s.alias)


def maintenant_iso():
    """Heure locale ISO 8601 avec décalage, à la seconde (champ temps des messages)."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


# ---------------------------------------------------------------- agent Équipe : messages des sujets

def personnalite_active(personnalites, ident=None):
    """La personnalité (dict de personnalites.yaml) d'id ident, ou l'active du fichier ; None si absente.
    personnalites : contenu de personnalites.yaml, ou None."""
    if not personnalites:
        return None
    ident = ident or personnalites.get("active")
    return next((p for p in personnalites.get("personnalites", []) if p.get("id") == ident), None)


def message_personnalite_active(personnalite, lieu=None):
    """Message de /personnalite/active (schéma personnalite_active) : la personnalité entière, telle
    que dans personnalites.yaml, plus version, lieu (id) et temps (heure de la publication : quand
    plusieurs éditeurs ont publié, un abonné garde le message le plus récent)."""
    message = dict(personnalite)
    message["version"] = 1
    if lieu:
        message["lieu"] = str(lieu)
    message["temps"] = maintenant_iso()
    return message


def message_robot_geste(geste, source, raison=None):
    """Message de /robot/geste (schéma robot_geste) : le geste des bras à faire (GESTES_BRAS, sans 99),
    écouté par le nœud pilotage, qui ne le fait que robot au repos."""
    message = {"version": 1, "geste": int(geste), "source": source, "temps": maintenant_iso()}
    if raison:
        message["raison"] = str(raison)[:200]
    return message


def message_robot_dire(texte, source, code=None, priorite="normale", personnalite=None, langue="fr"):
    """Message de /robot/dire (schéma robot_dire). personnalite : dict de la personnalité active ;
    son id et ses réglages de voix sont joints (champs en plus, permis par le schéma), pour que la
    partie voix n'ait pas à suivre /personnalite/active si elle ne veut pas."""
    if source not in SOURCES_DIRE:
        raise ValueError(f"source inconnue : {source} ({', '.join(SOURCES_DIRE)})")
    message = {"version": 1, "texte": str(texte).strip()[:500], "source": source, "priorite": priorite,
               "langue": langue, "temps": maintenant_iso()}
    if code:
        message["code"] = code
    if personnalite:
        message["personnalite"] = personnalite.get("id")
        if personnalite.get("voix"):
            message["voix"] = dict(personnalite["voix"])
    return message


# ---------------------------------------------------------------- agent Équipe : vérification

def _contenus(lieu, donnees):
    """(contenus, erreurs) : le contenu de chaque fichier de l'équipe, donné ou lu (None : absent)."""
    contenus, erreurs = {}, []
    for quoi, fichier in FICHIERS_EQUIPE.items():
        if donnees is not None and quoi in donnees:
            d = donnees[quoi]
            problemes = [] if d is None else valider_equipe(quoi, d)
            if problemes:
                erreurs += problemes
                d = None
            contenus[quoi] = d
            continue
        try:
            contenus[quoi] = charger_equipe(lieu, quoi)
        except ErreurLieu as e:
            erreurs += e.erreurs
            contenus[quoi] = None
    return contenus, erreurs


def _verifier_personnalites(p, av):
    fichier = FICHIERS_EQUIPE["personnalites"]
    for perso in p["personnalites"]:
        ou = f"{fichier}, personnalité « {perso['id']} »"
        for code, phrase in sorted((perso.get("phrases") or {}).items()):
            autres = [r for r in reperes(phrase) if r not in REPERES_PHRASE]
            if autres:
                av.append(f"{ou}, phrase « {code} » : {autres[0]} ne sera pas remplacé (seul {{nom}}, le nom de la "
                          "salle, l'est)")
        if perso.get("geste_salut") == 13:
            av.append(f"{ou} : le geste 13 n'est pas confirmé sur ce G1 (à essayer au portique)")
        voix = perso.get("voix") or {}
        if voix.get("volume") == 0:
            av.append(f"{ou} : volume 0, le robot sera muet dans ce mode")
        if perso.get("vitesse_max") is not None and perso["vitesse_max"] < 0.1:
            av.append(f"{ou} : vitesse_max de {perso['vitesse_max']:g} m/s, le robot avancera à peine")
        if perso.get("vitesse_max") is not None and perso["vitesse_max"] < VITESSE_PAS_MIN:
            # vague 5 : le vrai robot ne fait aucun pas sous 0,2 m/s ; le pont monte les petites consignes
            av.append(f"{ou} : une vitesse_max de {perso['vitesse_max']:g} m/s n'a pas d'effet sur le vrai robot : "
                      f"il ne marche pas sous {VITESSE_PAS_MIN:g} m/s (le pont monte les petites vitesses à "
                      f"{VITESSE_PAS_MIN:g}) ; elle ne joue qu'en simulation")


def _verifier_dialogues(d, personnalites, salles, err, av):
    fichier = FICHIERS_EQUIPE["dialogues"]
    ids_perso = [x["id"] for x in personnalites["personnalites"]] if personnalites else None
    vus = {}                    # motif normalisé → règle qui l'a en premier
    guider = False
    for r in d["regles"]:
        ou = f"{fichier}, règle « {r['id']} »"
        if r["action"] == "guider":
            guider = True
        if r["action"] == "personnalite":
            if ids_perso is None:
                av.append(f"{ou} : elle passe à la personnalité « {r['personnalite']} », mais le lieu n'a pas de "
                          "personnalites.yaml (Équipe › Personnalités)")
            elif r["personnalite"] not in ids_perso:
                err.append(f"{ou} : la personnalité « {r['personnalite']} » n'existe pas dans personnalites.yaml "
                           f"(personnalités : {', '.join(ids_perso)})")
        for motif in r["motifs"]:
            inconnus = [x for x in reperes(motif) if x not in REPERES_MOTIF]
            if inconnus:
                err.append(f"{ou} : le motif « {motif} » contient {inconnus[0]}, qui n'existe pas (seuls "
                           "{salle} et {*} existent) : il ne correspondra jamais")
                continue
            if reperes(motif).count(REPERE_SALLE) > 1:
                av.append(f"{ou} : le motif « {motif} » a plusieurs {{salle}} : le robot va à la dernière citée")
            jetons = jetons_motif(motif)
            if not jetons:
                err.append(f"{ou} : le motif « {motif} » ne contient aucun mot")
                continue
            if all(j == REPERE_JOKER for j in jetons):
                av.append(f"{ou} : le motif « {motif} » correspond à toutes les phrases : les règles suivantes "
                          "et le repli ne serviront plus")
            cle = tuple(jetons)
            if cle in vus:
                av.append(f"{ou} : le motif « {motif} » ne servira jamais : la règle « {vus[cle]} », plus haut, "
                          "a le même")
            else:
                vus[cle] = r["id"]
        hors = [x for x in reperes(r["reponse"]) if x not in REPERES_REPONSE]
        if hors:
            av.append(f"{ou} : la réponse contient {hors[0]}, qui ne sera pas remplacé (seuls {{nom_salle}} et "
                      "{salle} le sont, pour l'action guider)")
        elif r["action"] != "guider" and reperes(r["reponse"]):
            av.append(f"{ou} : {reperes(r['reponse'])[0]} n'est remplacé que pour l'action guider")
    if reperes(d["repli"]):
        av.append(f"{fichier} : le repli contient {reperes(d['repli'])[0]}, qui ne sera pas remplacé")
    if guider and not salles:
        av.append(f"{fichier} : des règles guident vers {{salle}}, mais le lieu n'a aucune salle (Placer › Salle)")
    # une même forme (id, nom ou alias) pour deux salles : le chatbot prend la première
    proprietaires = {}
    for s in salles:
        ident, nom, alias = _champs_salle(s)
        for texte in [ident, nom, *alias]:
            forme = normaliser(texte)
            if forme:
                proprietaires.setdefault(forme, [])
                if ident not in proprietaires[forme]:
                    proprietaires[forme].append(ident)
    for forme, ids in sorted(proprietaires.items()):
        if len(ids) > 1:
            av.append(f"salles.yaml : « {forme} » désigne plusieurs salles ({', '.join(ids)}) ; le chatbot choisit "
                      f"« {ids[0]} »")


def _verifier_camera(c, av):
    fichier = FICHIERS_EQUIPE["camera"]
    cam, det = c["camera"], c["detection"]
    pos = cam["position"]
    if not HAUTEUR_CAMERA_M[0] <= pos["z"] <= HAUTEUR_CAMERA_M[1]:
        av.append(f"{fichier} : la caméra est à {pos['z']:g} m du sol ; sur le G1 debout, elle est d'habitude entre "
                  f"{HAUTEUR_CAMERA_M[0]:g} et {HAUTEUR_CAMERA_M[1]:g} m (la poitrine est vers 1 m) : vérifiez z")
    if abs(pos["tangage"]) > TANGAGE_MAX_RAD:
        av.append(f"{fichier} : tangage de {pos['tangage']:g} rad : la caméra regarde surtout "
                  f"{'le sol' if pos['tangage'] > 0 else 'le plafond'} (positif : vers le bas)")
    if abs(pos["roulis"]) > ROULIS_MAX_RAD:
        av.append(f"{fichier} : roulis de {pos['roulis']:g} rad : l'image est penchée")
    if det["frequence_hz"] > cam["ips"]:
        av.append(f"{fichier} : la détection à {det['frequence_hz']:g} Hz ne peut pas aller plus vite que la "
                  f"caméra ({cam['ips']} images par seconde)")
    if "champ_horizontal_deg" not in cam:
        av.append(f"{fichier} : sans champ_horizontal_deg, l'écran Caméra ne peut pas dessiner ce que voit la "
                  "caméra (fiche de l'objectif, ou mesure)")
    if "11cug" in normaliser(cam.get("modele", "")).replace(" ", "") and \
            (cam["largeur"], cam["hauteur"]) not in MODES_IMAGE_11CUG:
        av.append(f"{fichier} : {cam['largeur']} × {cam['hauteur']} n'est pas un mode habituel de la See3CAM_11CUG : "
                  "vérifiez avec « v4l2-ctl -d " + cam["peripherique"] + " --list-formats-ext »")
    if det["actif"] and det.get("modele"):
        import atelier
        modeles = atelier.RACINE / "modeles"
        if modeles.is_dir() and not any(modeles.rglob(det["modele"])):
            av.append(f"{fichier} : le modèle de détection « {det['modele']} » est introuvable dans "
                      f"{modeles} sur cet ordinateur")


def verifier_equipe(lieu, donnees=None):
    """Vérifie les fichiers de l'équipe du lieu, entre eux et avec salles.yaml : ce que les schémas ne
    voient pas. donnees : {quoi: contenu} à vérifier à la place du fichier enregistré (contenu d'un
    onglet pas encore enregistré ; None : comme absent). Renvoie {ok, erreurs, avertissements}
    (messages en français) ; ne lève jamais d'exception pour un fichier faux (il est dans erreurs).

    erreurs : un fichier invalide, une règle qui passe à une personnalité inconnue, un motif qui ne
    correspondra jamais. avertissements : ce qui marche, mais surprendra sans doute (motif jamais
    utilisé, alias de deux salles, caméra mal placée…)."""
    contenus, erreurs = _contenus(lieu, donnees)
    avertissements = []
    try:
        salles = charger_salles(lieu)
    except ErreurLieu as e:
        salles = []
        avertissements.append("salles.yaml est invalide : les règles qui guident vers {salle} ne trouveront aucune "
                              f"salle ({e.erreurs[0]})")
    if contenus["personnalites"]:
        _verifier_personnalites(contenus["personnalites"], avertissements)
    if contenus["dialogues"]:
        _verifier_dialogues(contenus["dialogues"], contenus["personnalites"], salles, erreurs, avertissements)
    if contenus["camera"]:
        _verifier_camera(contenus["camera"], avertissements)
    return {"ok": not erreurs, "erreurs": erreurs, "avertissements": avertissements}


__all__ = ["ACTIONS_DIALOGUE", "DOSSIER_EXEMPLES", "ENTETES_EQUIPE", "EXEMPLE_PERSONNALITE_ACTIVE",
           "EXEMPLE_ROBOT_DIRE", "FICHIERS_EQUIPE", "SUJETS_EQUIPE", "charger_equipe", "chemin_equipe",
           "enregistrer_equipe", "exemple_equipe", "valider_equipe",
           # agent Équipe
           "MODES_IMAGE_11CUG", "PREREGLAGES_CAMERA", "REPERES_MOTIF", "REPERES_PHRASE", "REPERES_REPONSE",
           "REPERE_JOKER", "REPERE_SALLE", "SOURCES_DIRE", "formes_salles", "jetons_motif", "maintenant_iso",
           "message_personnalite_active", "message_robot_dire", "message_robot_geste", "normaliser",
           "personnalite_active", "reperes",
           "verifier_equipe",
           # vague 5 (section 12.7 du plan) : caméra de poitrine
           "CAMERA_CONTENEUR", "SUJET_ETAT_CAMERA", "SUJET_IMAGE_POITRINE", "SUJETS_IMAGES", "VITESSE_PAS_MIN"]
