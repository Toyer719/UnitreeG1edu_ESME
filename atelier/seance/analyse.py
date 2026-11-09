"""L'analyse d'une séance pour le rapport (vague 6, section 13.3 du plan) : agent Boîte noire.

Fonctions pures, sans ROS : elles prennent les messages déjà décodés (lecture.Donnees), le journal des actions,
le manifeste et le lieu de la séance, et rendent le contenu de rapport.json :
  trajets(...)        chaque trajet du guide : départ, but, résultat (arrive, echec, interrompu, abandonne,
                      remplace, en_cours), cause, durée, distance, arrêts et leurs causes ;
  etats_pont(...)     le temps passé dans chaque état du pont vers la marche ;
  modes_robot(...)    les modes du robot vus (7001, lus par le pont) ;
  erreurs(...)        refus de l'Atelier (4xx, 5xx), erreurs des nœuds (/rosout) et des journaux ;
  reperage(...)       la précision du repérage (moyenne et pire), les pertes, les sauts ;
  anomalies(...)      détectées toutes seules : mouvement sans demande, robot qui ne répond plus, arrêts
                      d'urgence, séance interrompue, enregistrement coupé, erreurs du serveur, repérage perdu ;
  chronologie(...)    tout ce qui s'est passé, dans l'ordre, en phrases simples ;
  analyser(...)       le tout : le dict de rapport.json.
Le temps est en secondes depuis 1970 (time.time) ; les heures du rapport sont en ISO 8601 locale.
"""
import json
import math
import re

from atelier.lieu.comportement import ETATS_EN_MISSION
from .manifeste import heure_iso, lire_heure

VERSION_RAPPORT = 1
SEUIL_MOUVEMENT_M_S = 0.05      # plus de 5 cm/s : le robot bouge (13.3)
GRACE_DEMANDE_S = 2.0           # après une mission du guide, le joystick ou le pilotage : encore permis
FENETRE_VITESSE_S = 0.5         # vitesse mesurée sur une demi-seconde
DUREE_MIN_ANOMALIE_S = 0.5
DISTANCE_MIN_ANOMALIE_M = 0.05
SAUT_MAX_M = 1.0                # entre deux positions proches : plus, c'est une correction du repérage
ECART_MAX_ETAT_S = 2.0          # /pont/etat (2 Hz) : au-delà, le temps n'est pas compté (pont absent)
DISTANCE_LIEU_M = 1.5           # un départ à moins de 1,5 m d'une salle porte son nom
FENETRE_CAUSE_S = 3.0           # une action à moins de 3 s de la fin d'un trajet en est la cause
ERREURS_MAX = 200
CHRONOLOGIE_MAX = 5000

RESULTATS = {"arrive": "arrivé", "echec": "échec", "interrompu": "interrompu", "abandonne": "abandonné",
             "remplace": "remplacé", "en_cours": "pas fini"}
ARRETS_GUIDE = {"bloque": "bloqué (plus de progrès)", "attente_passage": "une personne bouche le passage",
                "attente_visiteur": "il attend le visiteur", "perdu": "perdu (repérage)",
                "detour": "détour par un autre chemin"}
RAISONS = {"verrou": "robot bloqué (verrou)", "pas_en_marche": "robot pas en mode marche",
           "robot_muet": "robot qui ne répond plus", "refus": "robot qui refuse de marcher",
           "pont_absent": "plus de nouvelles du pont vers la marche"}
ETATS_PONT = {"demarrage": "démarrage", "attente_reperage": "attend le repérage", "pret": "prêt",
              "en_mouvement": "en mouvement", "arret": "arrêt demandé", "arret_verrouille": "bloqué (verrou)",
              "robot_muet": "robot muet", "refus": "refus du robot", "pilotage": "piloté à la main",
              "pas_en_marche": "pas en mode marche"}
ETATS_PONT_REPOS = ("pret", "en_mouvement")      # transitions trop fréquentes pour la chronologie
ETATS_REPERAGE = {"non_repere": "pas encore repéré", "en_cours": "repérage en cours", "repere": "repéré",
                  "perdu": "perdu", "echec": "repérage en échec"}
EVENEMENTS_GUIDE = {
    "depart": "départ vers {nom}", "seul": "départ vers {nom} (personne derrière le robot)",
    "ralentir": "ralentit pour le visiteur", "attente_visiteur": "attend le visiteur",
    "visiteur_retrouve": "visiteur retrouvé", "visiteur_perdu": "visiteur perdu : retour à l'accueil",
    "passant_gene": "une personne bouche le passage", "passage_libre": "passage libre",
    "detour": "détour par un autre chemin", "arrivee": "arrivé : {nom}", "retour": "retour vers l'accueil",
    "retour_arrive": "de retour à l'accueil", "perdu": "robot perdu (repérage)", "retrouve": "repérage retrouvé",
    "echec": "échec du trajet", "arret": "trajet arrêté", "pilotage": "refus : robot piloté à la main",
    "immobilise": "le robot ne peut pas bouger : {raison}"}
# Événements de la démo d'accueil (/accueil/evenement, 13.4) à voir dans la chronologie : la démo mise en pause
# (ARRÊT, verrou, robot assis ou muet, pilotage…) et la visite en échec (assemblage de la vague 6)
EVENEMENTS_DEMO_A_REGARDER = ("pause", "visite_echouee")
SOURCES_POSITION = ("/reperage/etat", "/g1_jumeau/odom", "/odom")
SOURCES_VITESSE = ("/g1_jumeau/odom", "/state_estimator/odom_pelvis", "/reperage/etat", "/odom")
MOTIF_ERREUR_JOURNAL = re.compile(r"\[ERROR\]|\bERROR\b|Traceback|\bErreur\b|\bException\b|process has died")


def heure(t):
    return heure_iso(t) if t is not None else None


def _arrondi(x, n=2):
    return None if x is None else round(float(x), n)


def fr(x, n=1):
    """Un nombre écrit à la française : 1.5 → « 1,5 »."""
    return f"{float(x):.{n}f}".replace(".", ",")


def initial(serie, debut, marge=3.0):
    """Vrai si le premier message d'une série arrive dans les `marge` secondes du début de l'enregistrement : pour un
    sujet qui garde son dernier message (transient_local, comme /pont/arret), c'est l'état d'avant la séance, pas
    un événement."""
    return bool(serie) and debut is not None and serie[0][0] <= debut + marge


# ---------------------------------------------------------------- lieu de la séance

class Lieu:
    """Ce que le rapport sait du lieu de la séance : noms et positions des salles et des nœuds, point principal."""

    def __init__(self, salles=None, noeuds=None, principal=None, etage=None, nom=None):
        self.salles = dict(salles or {})        # id → {nom, x, y, etage}
        self.noeuds = dict(noeuds or {})        # id → {x, y, etage}
        self.principal = principal
        self.etage = etage
        self.nom = nom

    def nom_de(self, ident):
        if ident in (None, ""):
            return "?"
        if ident == "principal" and self.principal:
            ident = self.principal
        s = self.salles.get(ident)
        if s:
            return s.get("nom") or ident
        return str(ident).replace("_", " ").capitalize() if ident in self.noeuds else str(ident)

    def noms(self):
        return {i: s.get("nom") or i for i, s in self.salles.items()}

    def endroit(self, x, y, distance=DISTANCE_LIEU_M):
        """Nom de la salle (ou, à défaut, du nœud) la plus proche à moins de `distance` mètres, sinon None."""
        meilleur = None
        for genre in (self.salles, self.noeuds):
            for ident, p in genre.items():
                if self.etage and p.get("etage") not in (None, self.etage):
                    continue
                d = math.hypot(p["x"] - x, p["y"] - y)
                if d < distance:
                    meilleur, distance = self.nom_de(ident), d
            if meilleur:
                return meilleur
        return meilleur


# ---------------------------------------------------------------- positions et vitesses

def positions(donnees, sources=SOURCES_POSITION):
    """(source, [(t, x, y)]) : la première source qui a des positions (le repérage d'abord : la carte)."""
    for source in sources:
        if source == "/reperage/etat":
            serie = [(t, d["pose"]["x"], d["pose"]["y"]) for t, d in donnees.serie("json", source)
                     if d.get("repere") and isinstance(d.get("pose"), dict) and "x" in d["pose"]]
        else:
            serie = [(o[0], o[1], o[2]) for o in donnees.serie("odometrie", source)]
        if len(serie) >= 2:
            return source, serie
    return None, []


def longueur(points, debut=None, fin=None):
    """Longueur du chemin (m) entre debut et fin ; les sauts de plus de SAUT_MAX_M (corrections du repérage) et les
    tremblements de moins de 1 cm ne comptent pas."""
    total, avant = 0.0, None
    for t, x, y in points:
        if (debut is not None and t < debut) or (fin is not None and t > fin):
            continue
        if avant is not None:
            d = math.hypot(x - avant[0], y - avant[1])
            if d > SAUT_MAX_M:
                avant = (x, y)
                continue
            if d < 0.01:
                continue
            total += d
        avant = (x, y)
    return total


def position_a(points, t):
    """La position la plus proche de l'instant t (2 s au plus), ou None."""
    meilleur = None
    for p in points:
        if abs(p[0] - t) <= 2.0 and (meilleur is None or abs(p[0] - t) < abs(meilleur[0] - t)):
            meilleur = p
    return meilleur


def vitesses(points, fenetre=FENETRE_VITESSE_S):
    """[(t, v, x, y)] : la vitesse (m/s) sur la dernière demi-seconde, à chaque position."""
    resultat, j = [], 0
    for i, (t, x, y) in enumerate(points):
        while j < i and points[j + 1][0] <= t - fenetre:
            j += 1
        t0, x0, y0 = points[j]
        if t - t0 >= fenetre * 0.8 and j < i:
            d = math.hypot(x - x0, y - y0)
            resultat.append((t, d / (t - t0) if d <= SAUT_MAX_M else 0.0, x, y))
    return resultat


# ---------------------------------------------------------------- trajets

def _en_mission(d):
    return d.get("etat") in ETATS_EN_MISSION


def _actions(actions, genres):
    return [(lire_heure(a.get("t")), a) for a in actions if a.get("genre") in genres and lire_heure(a.get("t"))]


def cause_fin(t, etat_fin, evenements, actions, verrous):
    """Pourquoi un trajet s'est arrêté avant d'arriver, en français (fonction pure)."""
    proches = lambda liste: [x for x in liste if t - FENETRE_CAUSE_S <= x[0] <= t + 1.0]   # noqa: E731
    for genre, texte in (("arret", "ARRÊT (bouton de l'Atelier ou Échap)"), ("bloquer", "« Bloquer »"),
                         ("stop", "« Arrêter le trajet »")):
        if proches(_actions(actions, (genre,))):
            return texte
    immobilise = etat_fin.get("immobilise")
    for te, e in proches(evenements):
        if e.get("code") == "immobilise" and e.get("raison"):
            immobilise = immobilise or e.get("raison")
    if immobilise:
        return RAISONS.get(immobilise, immobilise)
    if proches([(tv, v) for tv, v in verrous if v]):
        return "verrou posé hors de l'Atelier"
    if any(e.get("code") == "arret" for _, e in proches(evenements)):
        return "arrêt demandé par un programme (/guide/stop)"
    if any(e.get("code") == "pilotage" for _, e in proches(evenements)):
        return "pilotage à la main"
    return "arrêt sans cause connue"


def trajets(donnees, actions, lieu, fin_seance=None):
    """Les trajets du guide, d'après /guide/etat et /guide/evenement (voir le résumé du module)."""
    etats = donnees.serie("json", "/guide/etat")
    evenements = donnees.serie("json", "/guide/evenement")
    verrous = donnees.serie("booleens", "/pont/arret")
    _, pts = positions(donnees)
    resultat, courant, precedent = [], None, None

    def commencer(t, d):
        cible = d.get("cible")
        mission = d.get("mission") or ("retour" if d.get("etat") == "retour" else "visite")
        p = position_a(pts, t)
        depart = None
        if precedent and precedent["resultat"] == "arrive" and precedent["cible"]:
            depart = lieu.nom_de(precedent["cible"])
        if depart is None and p is not None:
            depart = lieu.endroit(p[1], p[2])
        if depart is None and p is not None:
            proche = lieu.endroit(p[1], p[2], distance=5.0)
            depart = (f"près de {proche} " if proche else "") + f"({fr(p[1])} ; {fr(p[2])})"
        return {"debut_t": t, "cible": cible, "nom": lieu.nom_de(cible), "mission": mission,
                "depart": depart or "?", "accompagner": bool(d.get("accompagner")), "arrets": [],
                "etat": d.get("etat"), "position_depart": None if p is None else [round(p[1], 2), round(p[2], 2)]}

    def finir(t, resultat_trajet, cause=None):
        nonlocal courant, precedent
        c = courant
        c["fin_t"] = t
        c["resultat"] = resultat_trajet
        c["cause"] = cause
        p = position_a(pts, t)
        c["position_fin"] = None if p is None else [round(p[1], 2), round(p[2], 2)]
        resultat.append(c)
        precedent, courant = c, None

    for t, d in etats:
        if courant is None:
            if _en_mission(d):
                courant = commencer(t, d)
            continue
        if _en_mission(d):
            mission = d.get("mission") or ("retour" if d.get("etat") == "retour" else "visite")
            if mission != courant["mission"] and mission == "retour" and courant["mission"] == "visite":
                finir(t, "abandonne", "visiteur perdu : le robot revient à l'accueil")
                courant = commencer(t, d)
            elif d.get("cible") != courant["cible"] or mission != courant["mission"]:
                finir(t, "remplace", "une autre demande a remplacé ce trajet")
                courant = commencer(t, d)
            elif d.get("etat") != courant["etat"]:
                if d.get("etat") in ARRETS_GUIDE:
                    courant["arrets"].append({"t": heure(t), "cause": ARRETS_GUIDE[d["etat"]],
                                              "depuis_debut_s": round(t - courant["debut_t"], 1)})
                courant["etat"] = d.get("etat")
            continue
        # le guide n'est plus en mission : fin du trajet
        etat = d.get("etat")
        if etat == "arrive":
            finir(t, "arrive")
        elif etat == "echec":
            perdu = courant["etat"] == "perdu"
            finir(t, "echec", "robot perdu (repérage)" if perdu else (d.get("message") or "échec du guide"))
        elif courant["mission"] == "retour" and any(
                e.get("code") == "retour_arrive" and abs(te - t) <= 3.0 for te, e in evenements):
            finir(t, "arrive")
        else:
            cause = cause_fin(t, d, evenements, actions, verrous)
            finir(t, "interrompu", cause)
            resultat[-1]["arrets"].append({"t": heure(t), "cause": cause,
                                           "depuis_debut_s": round(t - resultat[-1]["debut_t"], 1)})
    if courant is not None:
        finir(fin_seance if fin_seance is not None else courant["debut_t"], "en_cours",
              "la séance s'est terminée pendant le trajet")
    sortie = []
    for i, c in enumerate(resultat, 1):
        sortie.append({
            "numero": i, "depart": c["depart"], "cible": c["cible"], "nom": c["nom"], "mission": c["mission"],
            "accompagner": c["accompagner"], "resultat": c["resultat"], "cause": c["cause"],
            "debut": heure(c["debut_t"]), "fin": heure(c["fin_t"]),
            "duree_s": round(max(0.0, c["fin_t"] - c["debut_t"]), 1),
            "distance_m": round(longueur(pts, c["debut_t"], c["fin_t"]), 2), "arrets": c["arrets"],
            "position_depart": c["position_depart"], "position_fin": c["position_fin"],
            "_debut_t": c["debut_t"], "_fin_t": c["fin_t"]})
    return sortie


# ---------------------------------------------------------------- pont, modes, repérage, batterie

def etats_pont(donnees):
    """{état du pont: secondes} : chaque message compte jusqu'au suivant (2 s au plus)."""
    serie = donnees.serie("json", "/pont/etat")
    temps = {}
    for i, (t, d) in enumerate(serie):
        suite = serie[i + 1][0] if i + 1 < len(serie) else t + 0.5
        etat = d.get("etat") or "inconnu"
        temps[etat] = temps.get(etat, 0.0) + min(max(0.0, suite - t), ECART_MAX_ETAT_S)
    # un état de passage (« arrêt demandé », aussitôt suivi de « bloqué ») n'a pas de durée : il est dans la chronologie
    return {k: round(v, 1) for k, v in sorted(temps.items(), key=lambda x: -x[1]) if round(v, 1) > 0}


def modes_robot(donnees):
    """[{fsm, nom, secondes, premiere}] des modes du robot lus par le pont (mode_robot de /pont/etat), sinon par
    les réponses 7001 du service sport."""
    vus = []
    for t, d in donnees.serie("json", "/pont/etat"):
        m = d.get("mode_robot")
        if isinstance(m, dict) and m.get("fsm") is not None:
            vus.append((t, int(m["fsm"]), m.get("nom")))
    if not vus:
        from atelier.lieu.pilotage import nom_mode
        for t, _, api, code, data in donnees.serie("reponses", "/api/sport/response"):
            if api == 7001 and code == 0:
                try:
                    fsm = int(json.loads(data)["data"])
                except (ValueError, KeyError, TypeError):
                    continue
                vus.append((t, fsm, nom_mode(fsm)))
    modes = {}
    for i, (t, fsm, nom) in enumerate(vus):
        suite = vus[i + 1][0] if i + 1 < len(vus) else t + 1.0
        m = modes.setdefault(fsm, {"fsm": fsm, "nom": nom or str(fsm), "secondes": 0.0, "premiere": heure(t)})
        m["secondes"] += min(max(0.0, suite - t), 3.0)
    return [dict(m, secondes=round(m["secondes"], 1)) for m in modes.values()]


def reperage(donnees):
    """{precision_moyenne_m, precision_max_m, pertes, sauts, reperages} d'après /reperage/etat."""
    precisions, pertes, sauts, reussis, avant = [], 0, 0, 0, None
    for _, d in donnees.serie("json", "/reperage/etat"):
        etat = d.get("etat")
        if d.get("repere") and isinstance(d.get("precision_m"), (int, float)):
            precisions.append(float(d["precision_m"]))
        if etat == "perdu" and avant != "perdu":
            pertes += 1
        if etat == "repere" and avant not in ("repere", "perdu"):
            reussis += 1
        if isinstance(d.get("sauts"), int):
            sauts = max(sauts, d["sauts"])
        avant = etat
    return {"precision_moyenne_m": _arrondi(sum(precisions) / len(precisions), 3) if precisions else None,
            "precision_max_m": _arrondi(max(precisions), 3) if precisions else None,
            "pertes": pertes, "sauts": sauts, "reperages": reussis}


def batterie(donnees):
    """{debut, fin} : la charge (%) au premier et au dernier /lf/bmsstate, ou null."""
    serie = donnees.batterie
    return {"debut": serie[0][1] if serie else None, "fin": serie[-1][1] if serie else None}


# ---------------------------------------------------------------- erreurs

def _detail(reponse):
    if isinstance(reponse, dict) and isinstance(reponse.get("detail"), str):
        return reponse["detail"]
    if isinstance(reponse, str):
        return reponse[:200]
    return ""


def erreurs(donnees, actions, lignes_journaux=()):
    """[{t, source, texte, nombre}] : refus de l'Atelier (4xx, 5xx), erreurs des nœuds (/rosout, ERROR et FATAL,
    regroupées), lignes d'erreur des journaux (regroupées) ; ERREURS_MAX au plus."""
    liste = []
    for a in actions:
        statut = a.get("statut")
        if isinstance(statut, int) and statut >= 400:
            genre = "erreur du serveur" if statut >= 500 else "refusé"
            liste.append({"t": a.get("t"), "source": "Atelier", "nombre": 1, "statut": statut,
                          "texte": f"{a.get('texte', '?')} : {genre} ({statut})"
                                   + (f" : {_detail(a.get('reponse'))}" if _detail(a.get("reponse")) else "")})
    vus = {}
    for t, niveau, noeud, message in donnees.journal:
        if niveau < 40:
            continue
        cle = (noeud, message[:160])
        if cle in vus:
            vus[cle]["nombre"] += 1
            continue
        vus[cle] = {"t": heure(t), "source": f"nœud {noeud}", "nombre": 1, "texte": message[:300]}
        liste.append(vus[cle])
    deja = [m for (_, m) in vus]               # messages des nœuds : la même erreur recopiée dans un journal
    for source, ligne in lignes_journaux:
        cle = (source, ligne[:160])
        if cle in vus:
            vus[cle]["nombre"] += 1
            continue
        if any(m and m in ligne for m in deja):
            continue
        vus[cle] = {"t": None, "source": source, "nombre": 1, "texte": ligne[:300]}
        liste.append(vus[cle])
    liste.sort(key=lambda e: lire_heure(e["t"]) or float("inf"))
    return liste[:ERREURS_MAX]


def lignes_erreur(texte, source):
    """[(source, ligne)] des lignes d'erreur d'un journal (fonction pure)."""
    return [(source, x.strip()) for x in texte.splitlines() if MOTIF_ERREUR_JOURNAL.search(x)]


# ---------------------------------------------------------------- demandes et anomalies

def intervalles_demande(donnees, actions):
    """[(debut, fin)] où un mouvement du robot est demandé : mission du guide, pilotage (main prise, joystick,
    danse, chorégraphie), scan ; chacun prolongé de GRACE_DEMANDE_S (le robot freine)."""
    intervalles = []

    def ajouter_serie(serie, actif, periode):
        """Les moments où actif(message) est vrai ; periode : combien de temps compte le dernier message."""
        debut, dernier = None, None
        for t, d in serie:
            if actif(d):
                debut = t if debut is None else debut
                dernier = t
            elif debut is not None:
                intervalles.append((debut, t + GRACE_DEMANDE_S))
                debut = None
        if debut is not None:
            intervalles.append((debut, dernier + periode + GRACE_DEMANDE_S))

    ajouter_serie(donnees.serie("json", "/guide/etat"), _en_mission, 0.5)

    def pilotage_actif(d):
        c = d.get("consigne") or {}
        ordre = any(abs(float(c.get(k) or 0.0)) > 1e-3 for k in ("vx", "vy", "wz"))
        return (d.get("maitre") == "pilotage" or d.get("danse") or d.get("choregraphie")
                or (ordre and (d.get("age_ordre_s") is None or d.get("age_ordre_s") < 2.0)))
    ajouter_serie(donnees.serie("json", "/pilotage/etat"), pilotage_actif, 1.0)
    # /mouvement/maitre ne change qu'à la prise et au rendu de la main : le dernier message vaut jusqu'à la fin
    ajouter_serie(donnees.serie("json", "/mouvement/maitre"), lambda d: d.get("maitre") == "pilotage",
                  float("inf"))
    scan = None
    for t, a in sorted(_actions(actions, ("scan",)), key=lambda x: x[0]):
        if a.get("chemin") == "/api/scan/demarrer" and (a.get("statut") or 0) < 400:
            scan = t
        elif a.get("chemin") == "/api/scan/arreter" and scan is not None:
            intervalles.append((scan, t + 5.0))
            scan = None
    if scan is not None:
        intervalles.append((scan, float("inf")))
    return sorted(intervalles)


def _dans(t, intervalles):
    return any(a <= t <= b for a, b in intervalles)


def _ordres_marche(donnees, debut, fin):
    """(ordres 7105 non nuls du pont, /cmd_vel non nuls) entre debut et fin."""
    ordres = 0
    for t, _, api, parametre in donnees.serie("requetes", "/api/sport/request"):
        if api != 7105 or not debut <= t <= fin:
            continue
        try:
            v = json.loads(parametre).get("velocity") or [0, 0, 0]
        except (ValueError, AttributeError):
            continue
        if any(abs(float(x)) > 1e-3 for x in v):
            ordres += 1
    vitesses_cmd = sum(1 for t, vx, vy, wz in donnees.serie("vitesses", "/cmd_vel")
                       if debut <= t <= fin and (abs(vx) > 1e-3 or abs(vy) > 1e-3 or abs(wz) > 1e-3))
    return ordres, vitesses_cmd


def mouvements_sans_demande(donnees, actions):
    """[{t, genre, texte, gravite, technique, duree_s, distance_m, position}] : le robot bouge (plus de 5 cm/s)
    sans mission du guide, sans pilotage ni scan depuis 2 s."""
    source, pts = positions(donnees, SOURCES_VITESSE)
    if not pts:
        return []
    demandes = intervalles_demande(donnees, actions)
    episodes, courant = [], None
    for t, v, x, y in vitesses(pts):
        anormal = v > SEUIL_MOUVEMENT_M_S and not _dans(t, demandes)
        if anormal:
            if courant is None or t - courant["fin"] > 1.0:
                # le mouvement a commencé dans la demi-seconde de la mesure : au milieu, à peu près
                courant = {"debut": t - FENETRE_VITESSE_S / 2, "fin": t, "vmax": v, "x": x, "y": y}
                episodes.append(courant)
            courant["fin"], courant["vmax"] = t, max(courant["vmax"], v)
    resultat = []
    for e in episodes:
        distance = longueur(pts, e["debut"], e["fin"])
        duree = e["fin"] - e["debut"]
        if duree < DUREE_MIN_ANOMALIE_S or distance < DISTANCE_MIN_ANOMALIE_M:
            continue
        ordres, cmd = _ordres_marche(donnees, e["debut"] - 1.0, e["fin"])
        if ordres:
            texte = (f"Le robot a bougé sans qu'on le lui demande : {fr(distance)} m en {duree:.0f} s, sans mission du "
                     "guide ni pilotage. Des ordres de marche sont partis du PC : un programme a envoyé des vitesses "
                     "au pont (flèches de la téléopération en répétition, outil de test, ou défaut à corriger).")
            gravite = "probleme"
        else:
            texte = (f"Le robot a bougé sans ordre du PC : {fr(distance)} m en {duree:.0f} s, sans mission du guide ni "
                     "pilotage. Télécommande, robot poussé, ou mesure de position qui dérive ?")
            gravite = "attention"
        resultat.append({"t": heure_iso(e["debut"], ms=True), "genre": "mouvement_sans_demande", "gravite": gravite,
                         "texte": texte, "duree_s": round(duree, 1), "distance_m": round(distance, 2),
                         "position": [round(e["x"], 2), round(e["y"], 2)],
                         "technique": (f"vitesse mesurée sur {source} jusqu'à {fr(e['vmax'], 2)} m/s ; {ordres} ordres "
                                       f"7105 non nuls sur /api/sport/request et {cmd} /cmd_vel non nuls"),
                         "_t": e["debut"]})
    return resultat


def _episodes_pont(donnees, etat_cherche):
    """[(debut, fin)] des moments où /pont/etat vaut etat_cherche."""
    episodes, debut, dernier = [], None, None
    for t, d in donnees.serie("json", "/pont/etat"):
        if d.get("etat") == etat_cherche:
            debut = t if debut is None else debut
            dernier = t
        elif debut is not None:
            episodes.append((debut, t))
            debut = None
    if debut is not None:
        episodes.append((debut, dernier + 0.5))
    return episodes


def anomalies(donnees, actions, manifeste, trajets_vus=()):
    """Les anomalies détectées toutes seules, la plus ancienne d'abord (voir le résumé du module)."""
    liste = list(mouvements_sans_demande(donnees, actions))
    en_trajet = [(tr["_debut_t"], tr["_fin_t"]) for tr in trajets_vus]
    # robot qui ne répond plus
    for debut, fin in _episodes_pont(donnees, "robot_muet"):
        pendant = _dans(debut, en_trajet)
        liste.append({"t": heure(debut), "_t": debut, "genre": "robot_muet",
                      "gravite": "probleme" if pendant else "attention",
                      "texte": (f"Le robot ne répondait plus au pont pendant {fin - debut:.0f} s"
                                + (", pendant un trajet : le pont l'a arrêté." if pendant else
                                   ", au repos (sans doute une réponse perdue : à surveiller)."))})
    # arrêts d'urgence : ARRÊT de l'Atelier, verrou du pont posé
    arrets = _actions(actions, ("arret",))
    for t, a in arrets:
        liste.append({"t": heure(t), "_t": t, "genre": "arret_urgence", "gravite": "info",
                      "texte": "ARRÊT appuyé dans l'Atelier (bouton ou touche Échap) : robot arrêté"
                               + (" et bloqué." if (a.get("reponse") or {}).get("verrou") else ".")})
    bloquer = _actions(actions, ("bloquer",))
    verrous = donnees.serie("booleens", "/pont/arret")
    avant = False
    if initial(verrous, donnees.debut):
        avant = verrous[0][1]           # l'état d'avant la séance (transient_local), pas un événement
        if avant:
            liste.append({"t": heure(verrous[0][0]), "_t": verrous[0][0], "genre": "arret_urgence", "gravite": "info",
                          "texte": "Le robot était déjà bloqué au début de la séance (verrou du pont posé avant)."})
        verrous = verrous[1:]
    for t, v in verrous:
        if v and not avant and not any(abs(t - ta) <= 2.0 for ta, _ in arrets):
            par_bloquer = any(abs(t - ta) <= 2.0 for ta, _ in bloquer)
            liste.append({"t": heure(t), "_t": t, "genre": "arret_urgence", "gravite": "info" if par_bloquer else
                          "attention",
                          "texte": "Robot bloqué par « Bloquer » (verrou du pont posé)." if par_bloquer else
                          "Verrou du pont posé hors de l'Atelier (ligne de commande ou autre programme)."})
        avant = v
    # séance interrompue, enregistrement coupé
    m = manifeste or {}
    if m.get("etat") == "interrompue":
        t = lire_heure(m.get("fin"))
        liste.append({"t": m.get("fin"), "_t": t or 0.0, "genre": "seance_interrompue", "gravite": "attention",
                      "texte": "La séance s'est terminée sans « Terminer la séance » : l'Atelier s'est arrêté "
                               "brutalement (plantage, Ctrl+C forcé ou coupure). Ce qui a été enregistré est gardé."})
    enregistrement = m.get("enregistrement") or {}
    if enregistrement.get("etat") in ("coupe", "erreur"):
        texte = enregistrement.get("message") or "L'enregistrement s'est arrêté avant la fin de la séance."
        liste.append({"t": None, "_t": float("inf"), "genre": "enregistrement_coupe", "gravite": "attention",
                      "texte": texte})
    # erreurs du serveur, repérage perdu
    for a in actions:
        if isinstance(a.get("statut"), int) and a["statut"] >= 500 and a["statut"] not in (501, 503):
            t = lire_heure(a.get("t"))
            liste.append({"t": a.get("t"), "_t": t or 0.0, "genre": "erreur_serveur", "gravite": "probleme",
                          "texte": f"Erreur du serveur ({a['statut']}) sur « {a.get('texte')} » : "
                                   f"{_detail(a.get('reponse'))}".strip()})
    avant = None
    for t, d in donnees.serie("json", "/reperage/etat"):
        if d.get("etat") == "perdu" and avant == "repere":
            liste.append({"t": heure(t), "_t": t, "genre": "reperage_perdu", "gravite": "attention",
                          "texte": "Le robot a perdu son repérage (plus de relocalisation) : le pont l'a arrêté."})
        avant = d.get("etat")
    liste.sort(key=lambda e: e["_t"])
    return liste


# ---------------------------------------------------------------- chronologie

def chronologie(donnees, actions, manifeste, anomalies_vues=(), lieu=None):
    """[{t, depuis_s, genre, texte, gravite}] de tout ce qui s'est passé, dans l'ordre du temps."""
    lieu = lieu or Lieu()
    m = manifeste or {}
    debut = lire_heure(m.get("debut")) or donnees.debut or 0.0
    lignes = []

    def ajouter(t, genre, texte, gravite="info"):
        if t is not None:
            lignes.append((t, genre, texte, gravite))

    ouvertures = {"auto": " (automatique, à l'ouverture en Réel)", "manuel": " (à la main)",
                  "g1-seance": " (g1-seance)"}
    ajouter(debut, "seance", "Séance ouverte" + ouvertures.get(m.get("ouverture"), ""))
    for a in actions:
        t = lire_heure(a.get("t"))
        statut = a.get("statut")
        texte = a.get("texte") or a.get("chemin")
        gravite = "info"
        if isinstance(statut, int) and statut >= 400:
            texte = f"{texte} — refusé ({statut}) : {_detail(a.get('reponse'))}".strip()
            gravite = "probleme" if statut >= 500 and statut not in (501, 503) else "attention"
        ajouter(t, "action", texte, gravite)
    for t, e in donnees.serie("json", "/guide/evenement"):
        code = e.get("code")
        modele = EVENEMENTS_GUIDE.get(code)
        if modele is None:
            continue
        nom = e.get("nom") or lieu.nom_de(e.get("salle"))
        texte = modele.format(nom=nom, raison=RAISONS.get(e.get("raison"), e.get("raison") or "?"))
        ajouter(t, "guide", "Guide : " + texte, "attention" if code in ("echec", "perdu", "immobilise") else "info")
    avant = None
    for t, d in donnees.serie("json", "/pont/etat"):
        etat = d.get("etat")
        if etat != avant and not (etat in ETATS_PONT_REPOS and (avant in ETATS_PONT_REPOS or avant is None)):
            gravite = "attention" if etat in ("robot_muet", "refus", "pas_en_marche") else "info"
            ajouter(t, "pont", f"Pont vers la marche : {ETATS_PONT.get(etat, etat)}", gravite)
        avant = etat
    avant = None
    for t, d in donnees.serie("json", "/pont/etat"):
        mr = d.get("mode_robot")
        fsm = mr.get("fsm") if isinstance(mr, dict) else None
        if fsm is not None and fsm != avant:
            ajouter(t, "mode", f"Mode du robot : {mr.get('nom') or fsm} ({fsm})")
            avant = fsm
    verrous = donnees.serie("booleens", "/pont/arret")
    avant = None
    if initial(verrous, donnees.debut):
        avant = verrous[0][1]           # l'état d'avant la séance, gardé par le pont (transient_local)
        ajouter(verrous[0][0], "verrou", "Au début, le robot est bloqué (verrou du pont)" if avant else
                "Au début, le robot n'est pas bloqué (verrou du pont levé)")
        verrous = verrous[1:]
    for t, v in verrous:
        if v != avant:
            ajouter(t, "verrou", "Verrou du pont posé : robot bloqué" if v else "Verrou du pont levé")
        avant = v
    avant = None
    for t, d in donnees.serie("json", "/reperage/etat"):
        etat = d.get("etat")
        if etat != avant:
            texte = f"Repérage : {ETATS_REPERAGE.get(etat, etat)}"
            if etat == "repere" and isinstance(d.get("precision_m"), (int, float)):
                texte += f" (précision {d['precision_m'] * 100:.0f} cm)"
            ajouter(t, "reperage", texte, "attention" if etat in ("perdu", "echec") else "info")
        avant = etat
    for t, e in donnees.serie("json", "/accueil/evenement"):
        if e.get("texte") or e.get("code"):
            ajouter(t, "demo", f"Démo : {e.get('texte') or e.get('code')}",
                    "attention" if e.get("code") in EVENEMENTS_DEMO_A_REGARDER else "info")
    for t, texte in donnees.serie("textes", "/g1_jumeau/panne") + [
            (t, json.dumps(d)) for t, d in donnees.serie("json", "/g1_jumeau/panne")]:
        ajouter(t, "essai", f"Essai : panne simulée du faux G1 « {texte} »")
    for t, texte in donnees.serie("textes", "/faux_slam/panne"):
        ajouter(t, "essai", f"Essai : panne simulée du repérage « {texte} »")
    for j in m.get("jetson") or []:
        ajouter(lire_heure(j.get("t")), "jetson", "Journal du conteneur du Jetson récupéré"
                + ("" if j.get("ok") else " (en échec : " + str(j.get("message")) + ")"))
    for a in anomalies_vues:
        if a.get("genre") in ("mouvement_sans_demande", "robot_muet", "reperage_perdu"):
            ajouter(lire_heure(a.get("t")), "anomalie", "Anomalie : " + a["texte"], a.get("gravite", "attention"))
    fin = lire_heure(m.get("fin"))
    if fin is not None:
        ajouter(fin, "seance", {"interrompue": "Séance interrompue (l'Atelier s'est arrêté brutalement)"}
                .get(m.get("etat"), "Séance terminée" + {"terminer": " (« Terminer la séance »)",
                                                         "arret_atelier": " (arrêt de l'Atelier)",
                                                         "g1-seance": " (g1-seance arreter)",
                                                         "simulation": " (passage en Simulation)"}
                     .get(m.get("fermeture"), "")))
    lignes.sort(key=lambda x: x[0])
    return [{"t": heure_iso(t, ms=False), "depuis_s": round(max(0.0, t - debut), 1), "genre": g, "texte": x,
             "gravite": gr} for t, g, x, gr in lignes[:CHRONOLOGIE_MAX]]


# ---------------------------------------------------------------- le tout

def resume(trajets_vus, anomalies_vues, erreurs_vues, actions):
    """Les chiffres de « En bref »."""
    par_resultat = {}
    for tr in trajets_vus:
        par_resultat[tr["resultat"]] = par_resultat.get(tr["resultat"], 0) + 1
    gravites = {}
    for a in anomalies_vues:
        gravites[a["gravite"]] = gravites.get(a["gravite"], 0) + 1
    return {"trajets": len(trajets_vus), "par_resultat": par_resultat,
            "distance_m": round(sum(t["distance_m"] for t in trajets_vus), 1),
            "arrets_urgence": sum(1 for a in anomalies_vues if a["genre"] == "arret_urgence"),
            "anomalies": gravites, "erreurs": len(erreurs_vues), "actions": len(actions)}


def analyser(manifeste, actions, donnees, lieu=None, lignes_journaux=(), infos_bag=None, diagnostic=None,
             fichiers=()):
    """Le contenu de rapport.json (13.3) : {version, seance, mode, lieu, debut, fin, duree_s, batterie, actions,
    trajets, etats_pont, modes, erreurs, reperage, anomalies, fichiers} et, en plus, resume, chronologie,
    enregistrement, diagnostic, trajet_source, atelier."""
    lieu = lieu or Lieu()
    m = manifeste or {}
    debut = lire_heure(m.get("debut")) or donnees.debut
    fin = lire_heure(m.get("fin")) or donnees.fin
    trajets_vus = trajets(donnees, actions, lieu, fin_seance=fin)
    anomalies_vues = anomalies(donnees, actions, m, trajets_vus)
    erreurs_vues = erreurs(donnees, actions, lignes_journaux)
    source, pts = positions(donnees)
    rapport = {
        "version": VERSION_RAPPORT, "seance": m.get("id"), "mode": m.get("mode"), "lieu": m.get("lieu"),
        "etage": m.get("etage"), "etat": m.get("etat"), "debut": m.get("debut") or heure(debut),
        "fin": m.get("fin") or heure(fin),
        "duree_s": m.get("duree_s") if m.get("duree_s") is not None else (
            round(fin - debut, 1) if debut and fin else None),
        "batterie": batterie(donnees), "actions": len(actions),
        "trajets": [{k: v for k, v in t.items() if not k.startswith("_")} for t in trajets_vus],
        "etats_pont": etats_pont(donnees), "modes": modes_robot(donnees), "erreurs": erreurs_vues,
        "reperage": reperage(donnees),
        "anomalies": [{k: v for k, v in a.items() if not k.startswith("_")} for a in anomalies_vues],
        "fichiers": list(fichiers),
        # en plus du contrat
        "resume": dict(resume(trajets_vus, anomalies_vues, erreurs_vues, actions),
                       distance_totale_m=round(longueur(pts), 1)),
        "chronologie": chronologie(donnees, actions, m, anomalies_vues, lieu),
        "trajet_source": source,
        "enregistrement": {"etat": (m.get("enregistrement") or {}).get("etat"),
                           "message": (m.get("enregistrement") or {}).get("message"),
                           "lecture": donnees.erreur, "messages_illisibles": donnees.illisibles,
                           "sujets": {k: v.get("nombre") for k, v in ((infos_bag or {}).get("sujets") or {}).items()},
                           "octets": (infos_bag or {}).get("octets"), "metadata": (infos_bag or {}).get("metadata")},
        "diagnostic": diagnostic, "atelier": m.get("atelier"), "fermeture": m.get("fermeture"),
        "nom_lieu": lieu.nom,
    }
    return rapport
