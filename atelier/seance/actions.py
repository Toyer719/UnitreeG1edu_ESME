"""Le journal des actions d'une séance (actions.jsonl, schéma action_seance ; section 13.3 du plan).

L'accroche de main.py (JournalDesActions) donne à la boîte noire, après chaque réponse, l'action brute
{t, methode, chemin, requete, statut, reponse, duree_ms, client}. Ce module y ajoute ce que le contrat demande :
version, depuis_s, mode, source, le genre (GENRES_ACTION) et le texte en français (« ARRÊT », « Y aller : Salle
B204 », « Posture : S'asseoir »…), puis l'écrit, une ligne JSON par action.

  decrire(methode, chemin, requete, reponse, noms=None) → (genre, texte)   (fonction pure)
  ligne_action(action, debut, mode, noms=None)          → la ligne du journal (schéma action_seance)
  JournalActions(fichier, debut, mode, noms)            la file et le fil d'écriture : noter(action) rend la main
                                                        tout de suite (le serveur n'attend jamais le disque)

Rien de secret ne va dans le journal : le code opérateur de la borne est masqué (CHAMPS_MASQUES), celui tapé sur la
borne comme celui des réglages de la démo.
"""
import json
import logging
import queue
import re
import threading
import time

from atelier.lieu.seance import GENRES_ACTION, reglage
from .manifeste import heure_iso, lire_heure

JOURNAL = logging.getLogger("atelier.seance")

LONGUEUR_TEXTE_MAX = 200                 # schéma action_seance
# le code opérateur de la borne (tapé sur la borne, ou dans les réglages de la démo : demo.yaml borne.code_operateur,
# corrections de la vague 6, revue du code, défaut 6), un jeton : jamais en clair
CHAMPS_MASQUES = ("code", "jeton", "code_operateur")
MASQUE = "••••"
# le même champ dans un corps gardé en texte (JSON coupé à LIMITE_CORPS_OCTETS : la valeur peut être coupée aussi)
MOTIF_CHAMP_MASQUE = re.compile(r'("(?:code|jeton|code_operateur)"\s*:\s*)("[^"]*(?:"|$)|-?\d+)')
SOURCES_CLIENT = {"local": "atelier", "borne": "borne", "distant": "distant"}

MODES_LANCEMENT = {"simu": "la simulation", "repetition": "la navigation (répétition sans robot)",
                   "robot": "la navigation du robot"}
FICHIERS_LIEU = {"salles": "Salles enregistrées", "itineraires": "Itinéraires enregistrés",
                 "zones": "Zones enregistrées", "monde": "Monde enregistré", "principal": "Point principal déplacé",
                 "guide": "Réglages du guide enregistrés", "demo": "Réglages de la démo enregistrés",
                 "passants": "Passants enregistrés"}
FICHIERS_EQUIPE = {"personnalites": "Personnalités enregistrées", "dialogues": "Dialogues enregistrés",
                   "camera": "Réglages de la caméra enregistrés"}


def _texte_court(texte, longueur=60):
    texte = " ".join(str(texte).split())
    return texte if len(texte) <= longueur else texte[:longueur - 1] + "…"


def _dict(x):
    return x if isinstance(x, dict) else {}


def _nom(noms, ident):
    """Nom lisible d'une salle (salles.yaml de la séance), sinon l'id ; « principal » : le point principal."""
    if ident == "principal":
        return "le point principal"
    return (noms or {}).get(ident) or str(ident)


def _pilotage(sous, corps):
    """(genre, texte) d'une commande de l'onglet Piloter (relayée au nœud pilotage)."""
    from atelier.lieu import pilotage as P
    if sous.startswith("choregraphies"):
        morceaux = sous.split("/")
        ident = morceaux[1] if len(morceaux) > 1 else ""
        if ident == "verifier":
            return "choregraphie", "Chorégraphie vérifiée"
        if morceaux[-1] == "jouer":
            return "choregraphie", f"Chorégraphie : {ident}"
        return "choregraphie", f"Chorégraphie enregistrée ou supprimée : {ident}"
    if sous == "posture":
        fsm = corps.get("fsm")
        return "pilotage", f"Posture : {P.POSTURES.get(fsm, fsm)}"
    if sous == "maitre":
        if corps.get("maitre") == "pilotage":
            return "pilotage", "Prendre la main" + (" (forcé)" if corps.get("forcer") else "")
        return "pilotage", "Rendre la main au guide"
    if sous == "geste":
        action = corps.get("action")
        return "pilotage", f"Geste : {P.GESTES_BRAS.get(action, action)}"
    if sous == "tache":
        tache = corps.get("tache")
        return "pilotage", f"Geste : {P.TACHES_LOCO.get(tache, tache)}"
    if sous == "danse":
        ident = corps.get("id")
        nom = P.DANSES_ESSAYEES.get(ident) or P.DANSES_NON_ESSAYEES.get(ident)
        return "pilotage", f"Danse {ident}" + (f" ({nom})" if nom and nom != "?" else "")
    if sous == "voix":
        return "pilotage", f"Voix du robot : « {_texte_court(corps.get('texte', ''))} »"
    if sous == "volume":
        return "pilotage", f"Volume du robot : {corps.get('volume')}"
    if sous == "led":
        eteinte = all(not corps.get(c) for c in ("r", "g", "b"))
        return "pilotage", "Lumière éteinte" if eteinte else "Lumière du robot"
    textes = {"arret": "ARRÊT du pilotage", "demarrer": "Lancer le pilotage", "arreter": "Arrêter le pilotage",
              "requete": "Ordre avancé du pilotage"}
    return "pilotage", textes.get(sous, f"Pilotage : {sous}")


# Le faux visiteur de la simulation (POST /api/guide/visiteur {mode}) en mots simples (corrections de la vague 6,
# revue de l'interface, défaut 12 : « POST /api/guide/visiteur » brut dans la chronologie)
MODES_VISITEUR = {"suivre": "il suit le robot", "trainer": "il traîne", "partir": "il s'en va",
                  "arreter": "il s'arrête"}


def _mode_arrete(reponse):
    """Le mode de ce qui vient d'être arrêté (réponse de POST /api/simulation/arreter : simulation.mode), aussi dans
    une réponse gardée en texte (coupée), ou None."""
    if isinstance(reponse, dict):
        return (reponse.get("simulation") or {}).get("mode")
    if isinstance(reponse, str):
        m = re.search(r'"simulation":\s*\{[^{}]*?"mode":\s*"(\w+)"', reponse)
        return m.group(1) if m else None
    return None


def action_sans_effet(action):
    """Vrai pour une demande qui n'a rien changé et n'a pas sa place dans le journal : rouvrir l'espace en Réel quand
    la séance est déjà ouverte (POST /api/seance/demarrer répond nouvelle: false ; « Ouvrir la séance
    (automatique) » revenait 11 fois dans une séance, corrections de la vague 6, revue de l'interface, défaut 12)."""
    if action.get("chemin") != "/api/seance/demarrer":
        return False
    reponse = action.get("reponse")
    if isinstance(reponse, dict):
        return reponse.get("nouvelle") is False
    # réponse coupée (gardée en texte) : « nouvelle » vient en premier
    return isinstance(reponse, str) and re.match(r'\{\s*"nouvelle"\s*:\s*false\b', reponse) is not None


def decrire(methode, chemin, requete=None, reponse=None, noms=None):
    """(genre, texte en français) d'une demande à l'API, pour la chronologie du rapport (fonction pure)."""
    corps = _dict(requete)
    rep = _dict(reponse)
    morceaux = [m for m in chemin.split("/") if m]          # ["api", "guide", "aller"]
    suite = "/".join(morceaux[1:])
    if chemin == "/api/arret":
        return "arret", "ARRÊT"
    if chemin == "/api/arret/debloquer":
        return "debloquer", "Débloquer"
    if chemin == "/api/robot/arret":
        return ("bloquer", "Bloquer") if corps.get("verrou", True) else ("debloquer", "Débloquer")
    if chemin == "/api/guide/aller":
        cible = corps.get("cible", "?")
        texte = f"Y aller : {_nom(noms, cible)}"
        if corps.get("accompagner"):
            texte += " (avec un visiteur)"
        if corps.get("retour") is False:
            texte += ", sans retour"
        return "y_aller", texte
    if chemin == "/api/guide/stop":
        return "stop", "Arrêter le trajet"
    if chemin == "/api/robot/reperer":
        texte = "Repérer le robot" + (" (position donnée à la main)" if "x" in corps else "")
        if rep.get("repere") is True:
            texte += " : repéré"
        return "reperer", texte
    if chemin == "/api/simulation/demarrer":
        mode = corps.get("mode", "simu")
        return "lancer", f"Lancer {MODES_LANCEMENT.get(mode, 'la navigation')}"
    if chemin == "/api/simulation/arreter":
        return "arreter", f"Arrêter {MODES_LANCEMENT.get(_mode_arrete(reponse), 'la navigation')}"
    if chemin == "/api/guide/visiteur":
        mode = str(corps.get("mode") or "?")
        return "autre", f"Faux visiteur : {MODES_VISITEUR.get(mode, mode)}"
    if suite.startswith("scan/"):
        if suite == "scan/demarrer":
            return "scan", "Scan : démarrer"
        if suite == "scan/arreter":
            return "scan", "Scan : fin"
        if suite.endswith("/adopter"):
            return "scan", "Scan : utiliser cette carte"
        return "scan", f"Scan : {morceaux[-1]}"
    if suite.startswith("pilotage/"):
        return _pilotage(suite[len("pilotage/"):], corps)
    if suite.startswith("robot/diagnostic/"):
        from atelier.lieu.diagnostic import ACTIONS_DIAGNOSTIC
        action = morceaux[-1]
        libelle = (ACTIONS_DIAGNOSTIC.get(action) or {}).get("libelle") or action
        return "diagnostic", f"Diagnostic : {libelle}"
    if suite.startswith("seance"):
        if suite == "seance/demarrer":
            ouverture = corps.get("ouverture", "manuel")
            return "seance", "Ouvrir la séance" + (" (automatique)" if ouverture == "auto" else "")
        if suite == "seance/arreter":
            return "seance", "Terminer la séance"
        if suite.endswith("/rapport"):
            return "seance", "Refaire le rapport de séance"
        return "seance", "Séance"
    if suite.startswith("demo/"):
        action = morceaux[-1]
        if action == "commande":
            return "demo", f"Démo : {corps.get('action', 'commande')}"
        return "demo", {"lancer": "Lancer la démo", "arreter": "Arrêter la démo"}.get(action, f"Démo : {action}")
    if suite.startswith("borne/"):
        action = morceaux[-1]
        if action == "choisir":
            return "borne", f"Borne : {_nom(noms, corps.get('salle', '?'))}"
        if len(morceaux) > 3 and morceaux[2] == "operateur":
            return "borne", f"Borne (opérateur) : {action}"
        return "borne", {"appui": "Borne : appui", "annuler": "Borne : annuler",
                         "operateur": "Borne : code opérateur"}.get(action, f"Borne : {action}")
    if suite.startswith("voix/"):
        action = morceaux[-1]
        if action == "essayer":
            return "voix", f"Voix : essayer « {_texte_court(corps.get('texte', ''))} »"
        return "voix", {"demarrer": "Lancer la voix", "arreter": "Arrêter la voix",
                        "commande": f"Voix : {corps.get('action', 'commande')}"}.get(action, f"Voix : {action}")
    if suite.startswith("equipe/"):
        return "equipe", f"Équipe : {morceaux[-1]}"
    if morceaux[:2] == ["api", "lieux"]:
        # /api/lieux (nouveau lieu), /api/lieux/{id} (lieu.yaml), /api/lieux/{id}/…/{fichier}
        if len(morceaux) == 2:
            return "lieu", f"Nouveau lieu : {corps.get('id') or corps.get('nom') or '?'}"
        if len(morceaux) == 3:
            return "lieu", "Fiche du lieu enregistrée"
        dernier = morceaux[-1]
        if dernier in FICHIERS_EQUIPE:
            return "equipe", FICHIERS_EQUIPE[dernier]
        if dernier == "essayer":
            return "equipe", "Dialogues : essayer une phrase"
        if dernier == "active" and "personnalites" in morceaux:
            return "equipe", f"Personnalité choisie : {corps.get('id') or '?'}"
        if dernier == "generer":
            return "lieu", "Carte refaite"
        if dernier in FICHIERS_LIEU:
            return "lieu", FICHIERS_LIEU[dernier]
        return "lieu", "Lieu enregistré"
    return "autre", _texte_court(f"{methode} {chemin}", LONGUEUR_TEXTE_MAX)


def _masquer(corps):
    """Copie du corps sans les champs secrets (code opérateur de la borne, jeton), aussi dans un corps gardé en
    texte."""
    if isinstance(corps, dict):
        return {k: (MASQUE if k in CHAMPS_MASQUES and v not in (None, "") else _masquer(v)) for k, v in corps.items()}
    if isinstance(corps, list):
        return [_masquer(v) for v in corps]
    if isinstance(corps, str):
        return MOTIF_CHAMP_MASQUE.sub(lambda m: m.group(1) + '"' + MASQUE + '"', corps)
    return corps


def ligne_action(action, debut=None, mode=None, noms=None):
    """La ligne du journal d'une action brute de l'accroche (schéma action_seance). debut : l'ouverture de la séance
    (time.time) pour depuis_s ; mode : simu, reel, repetition ou None."""
    methode = str(action.get("methode") or "POST").upper()
    chemin = str(action.get("chemin") or "/api/")
    requete, reponse = _masquer(action.get("requete")), _masquer(action.get("reponse"))
    genre, texte = decrire(methode, chemin, requete, reponse, noms)
    if genre not in GENRES_ACTION:
        genre = "autre"
    t = action.get("t") or heure_iso(ms=True)
    instant = lire_heure(t)
    client = action.get("client") if action.get("client") in SOURCES_CLIENT else "local"
    source = SOURCES_CLIENT[client]
    if isinstance(requete, dict) and "g1-seance" in (requete.get("ouverture"), requete.get("fermeture")):
        source = "g1-seance"
    statut = action.get("statut")
    ligne = {"version": 1, "t": t, "genre": genre, "texte": _texte_court(texte, LONGUEUR_TEXTE_MAX),
             "methode": methode, "chemin": chemin[:300], "requete": requete,
             "statut": statut if isinstance(statut, int) and 100 <= statut <= 599 else None,
             "reponse": reponse, "duree_ms": max(0.0, float(action.get("duree_ms") or 0.0)),
             "mode": mode if mode in ("simu", "reel", "repetition") else None, "client": client, "source": source}
    if debut is not None and instant is not None:
        ligne["depuis_s"] = round(max(0.0, instant - debut), 3)
    return ligne


# Corrections de la vague 6 (revue du code, défaut 9) : une borne ou une page qui insiste (3 000 demandes refusées
# en 1,7 s : 3 Go par heure) ne remplit plus le disque. Les demandes répétées (refusées par une garde de main.py,
# rebonds de la borne, trop de codes faux) : la première de chaque minute est notée, puis une ligne de résumé dit
# combien d'autres ont suivi (même client) ; au-delà de actions_max_mo, seules les actions qui comptent pour la
# sécurité sont encore notées (ARRÊT, Bloquer, Débloquer, la séance).
MOTIFS_REPETITION = {"garde": "refusées par la garde de l'Atelier", "rebond": "comptées pour une (anti-rebond)",
                     "trop_d_essais": "refusées : trop de codes faux"}
GENRES_TOUJOURS = ("arret", "bloquer", "debloquer", "seance")


def motif_repetition(action):
    """Pourquoi une demande se résume avec ses pareilles au lieu d'être notée une à une (MOTIFS_REPETITION) :
    garde (refusée par une garde de main.py, champ garde de l'action), rebond (anti-rebond de la borne),
    trop_d_essais (429) ; None pour une demande ordinaire."""
    if action.get("garde"):
        return "garde"
    if action.get("statut") == 429:
        return "trop_d_essais"
    reponse = action.get("reponse")
    if isinstance(reponse, dict) and reponse.get("rebond") is True:
        return "rebond"
    return None


def ligne_toujours_notee(ligne):
    """Vrai pour une action qui compte pour la sécurité, notée même quand le journal est coupé : ARRÊT, Bloquer,
    Débloquer, la séance, faits sur ce PC et acceptés."""
    statut = ligne.get("statut")
    return (ligne.get("genre") in GENRES_TOUJOURS and ligne.get("client") == "local"
            and (statut is None or statut < 400))


class JournalActions:
    """File et fil d'écriture de actions.jsonl : noter(action) ne fait que mettre l'action dans la file (le
    serveur n'attend jamais le disque) ; le fil décrit l'action (ligne_action) et l'ajoute au fichier.
    surNote(n) est appelée après chaque ligne écrite (n : le nombre de lignes du journal). Les demandes répétées
    sont résumées par minute (motif_repetition) et le fichier ne dépasse pas taille_max_mo (ensuite, seulement
    ligne_toujours_notee)."""

    def __init__(self, fichier, debut, mode, noms=None, sur_note=None, mode_actuel=None, taille_max_mo=None,
                 periode_resume_s=None, horloge=time.time):
        self.fichier = fichier
        self.debut = debut
        self.mode = mode
        self.noms = dict(noms or {})
        self.sur_note = sur_note
        self.mode_actuel = mode_actuel          # fonction : le mode de la navigation qui tourne, ou None
        self.taille_max = (reglage("actions_max_mo") if taille_max_mo is None else taille_max_mo) * 1e6
        self.periode_resume = reglage("resume_repetitions_s") if periode_resume_s is None else periode_resume_s
        self.horloge = horloge
        self.nombre = self._compter()
        self.octets = self._taille()
        self.coupe = False
        self.non_notees = 0                     # actions jetées après la coupure
        self._repetitions = {}                  # (client, motif) → {periode, nombre, dernier, premier_t}
        self._verrou = threading.RLock()        # le fil d'écriture, et ecrire() appelé par la séance
        self._file = queue.SimpleQueue()
        self._fin = threading.Event()
        self._fil = threading.Thread(target=self._boucle, name="journal des actions", daemon=True)
        self._fil.start()

    def _compter(self):
        try:
            with open(self.fichier, "rb") as f:
                return sum(1 for _ in f)
        except OSError:
            return 0

    def _taille(self):
        try:
            with open(self.fichier, "rb") as f:
                return f.seek(0, 2)
        except OSError:
            return 0

    def noter(self, action):
        """Met l'action dans la file ; rend la main tout de suite, sans jamais lever d'exception."""
        try:
            self._file.put(dict(action))
        except Exception:       # noqa: BLE001 : la boîte noire ne gêne jamais une demande
            pass

    def _mode(self):
        try:
            m = self.mode_actuel() if self.mode_actuel else None
        except Exception:       # noqa: BLE001
            m = None
        return {"robot": "reel"}.get(m, m) or self.mode

    def ecrire(self, action):
        """Écrit une action tout de suite (sans la file ni le résumé des répétitions) : « Terminer la séance », notée
        par la séance elle-même. Rend la ligne, ou None si le journal est coupé et qu'elle n'y va pas."""
        ligne = ligne_action(action, self.debut, self._mode(), self.noms)
        with self._verrou:
            return ligne if self._ajouter(ligne) else None

    def _ajouter(self, ligne):
        """Ajoute la ligne au fichier, dans la limite de taille ; vrai si elle est écrite."""
        texte = json.dumps(ligne, ensure_ascii=False) + "\n"
        if not self.coupe and self.octets + len(texte.encode("utf-8")) > self.taille_max:
            self.coupe = True
            mo = self.taille_max / 1e6
            self._ecrire_texte(json.dumps(self._ligne_seance(
                f"Journal des actions coupé : il a atteint {mo:g} Mo. Seuls l'ARRÊT, « Bloquer », « Débloquer » et la "
                "séance sont encore notés.", coupure=True), ensure_ascii=False) + "\n")
        if self.coupe and not ligne_toujours_notee(ligne):
            self.non_notees += 1
            return False
        self._ecrire_texte(texte)
        return True

    def _ecrire_texte(self, texte):
        with open(self.fichier, "a", encoding="utf-8") as f:
            f.write(texte)
        self.octets += len(texte.encode("utf-8"))
        self.nombre += 1
        if self.sur_note:
            self.sur_note(self.nombre)

    def _ligne_seance(self, texte, **plus):
        """Une ligne de la séance elle-même (coupure, actions non notées), conforme au schéma action_seance."""
        ligne = ligne_action({"t": heure_iso(self.horloge(), ms=True), "methode": "POST",
                              "chemin": "/api/seance/journal", "statut": None, "client": "local"},
                             self.debut, self._mode(), self.noms)
        ligne.update(genre="seance", texte=_texte_court(texte, LONGUEUR_TEXTE_MAX), **plus)
        return ligne

    def _traiter(self, action):
        """Une action de la file : notée, ou comptée avec ses pareilles (motif_repetition), ou laissée si elle n'a rien
        changé (action_sans_effet). Avant une action ordinaire, les résumés en cours sont écrits : le journal reste
        dans l'ordre du temps."""
        if action_sans_effet(action):
            return
        motif = motif_repetition(action)
        with self._verrou:
            if motif is None:
                for cle in list(self._repetitions):
                    self._resumer(cle)
            else:
                t = lire_heure(action.get("t")) or self.horloge()
                cle, periode = (action.get("client") or "local", motif), int(t // self.periode_resume)
                r = self._repetitions.get(cle)
                if r is not None and r["periode"] == periode:
                    r["nombre"] += 1
                    r["dernier"] = action
                    return
                if r is not None:
                    self._resumer(cle)
                self._repetitions[cle] = {"periode": periode, "nombre": 0, "dernier": action, "premier_t": t}
            self._ajouter(ligne_action(action, self.debut, self._mode(), self.noms))

    def _resumer(self, cle):
        """Écrit la ligne de résumé d'une série de demandes répétées (si d'autres ont suivi la première)."""
        r = self._repetitions.pop(cle, None)
        if r is None or r["nombre"] == 0:
            return
        derniere = ligne_action(r["dernier"], self.debut, self._mode(), self.noms)
        n = r["nombre"]
        derniere.update(texte=_texte_court(f"+{n} demande{'s' if n > 1 else ''} pareille{'s' if n > 1 else ''} "
                                           f"{MOTIFS_REPETITION[cle[1]]} (même client) : {derniere['texte']}",
                                           LONGUEUR_TEXTE_MAX),
                        requete=None, reponse=None, resume={"motif": cle[1], "nombre": n,
                                                            "depuis": heure_iso(r["premier_t"], ms=True)})
        self._ajouter(derniere)

    def _resumer_finies(self, toutes=False):
        """Les résumés des séries dont la minute est finie (ou de toutes, à la fermeture)."""
        with self._verrou:
            maintenant = int(self.horloge() // self.periode_resume)
            for cle in [c for c, r in self._repetitions.items() if toutes or r["periode"] < maintenant]:
                self._resumer(cle)

    def _boucle(self):
        while True:
            try:
                action = self._file.get(timeout=0.2)
            except queue.Empty:
                try:
                    self._resumer_finies()
                except Exception:       # noqa: BLE001
                    JOURNAL.exception("journal des actions : résumé non écrit")
                if self._fin.is_set():
                    return
                continue
            if action is None:
                return
            try:
                self._traiter(action)
            except Exception:       # noqa: BLE001 : une action illisible ne doit pas arrêter le journal
                JOURNAL.exception("journal des actions : une action n'a pas pu être écrite")

    def arreter(self, delai=2.0):
        """Écrit ce qui reste dans la file (delai secondes au plus), les résumés en cours et, si le journal a été
        coupé, le nombre d'actions non notées ; puis arrête le fil."""
        self._file.put(None)
        self._fil.join(timeout=delai)
        self._fin.set()
        try:
            with self._verrou:
                self._resumer_finies(toutes=True)
                if self.non_notees:
                    n = self.non_notees
                    self._ecrire_texte(json.dumps(self._ligne_seance(
                        f"{n} action{'s' if n > 1 else ''} de plus non notée{'s' if n > 1 else ''} (journal coupé).",
                        non_notees=n), ensure_ascii=False) + "\n")
                    self.non_notees = 0
        except Exception:       # noqa: BLE001
            JOURNAL.exception("journal des actions : fin non écrite")
