"""Le journal des actions d'une séance (actions.jsonl, schéma action_seance ; section 13.3 du plan).

L'accroche de main.py (JournalDesActions) donne à la boîte noire, après chaque réponse, l'action brute
{t, methode, chemin, requete, statut, reponse, duree_ms, client}. Ce module y ajoute ce que le contrat demande :
version, depuis_s, mode, source, le genre (GENRES_ACTION) et le texte en français (« ARRÊT », « Y aller : Salle
B204 », « Posture : S'asseoir »…), puis l'écrit, une ligne JSON par action.

  decrire(methode, chemin, requete, reponse, noms=None) → (genre, texte)   (fonction pure)
  ligne_action(action, debut, mode, noms=None)          → la ligne du journal (schéma action_seance)
  JournalActions(fichier, debut, mode, noms)            la file et le fil d'écriture : noter(action) rend la main
                                                        tout de suite (le serveur n'attend jamais le disque)

Rien de secret ne va dans le journal : le code opérateur de la borne est masqué (CHAMPS_MASQUES).
"""
import json
import logging
import queue
import re
import threading

from atelier.lieu.seance import GENRES_ACTION
from .manifeste import heure_iso, lire_heure

JOURNAL = logging.getLogger("atelier.seance")

LONGUEUR_TEXTE_MAX = 200                 # schéma action_seance
CHAMPS_MASQUES = ("code", "jeton")       # le code opérateur de la borne, un jeton : jamais en clair
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
        return "arreter", "Arrêter la navigation"
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
    """Copie du corps sans les champs secrets (code opérateur, jeton)."""
    if isinstance(corps, dict):
        return {k: ("••••" if k in CHAMPS_MASQUES and v not in (None, "") else _masquer(v)) for k, v in corps.items()}
    if isinstance(corps, list):
        return [_masquer(v) for v in corps]
    if isinstance(corps, str) and re.search(r'"(code|jeton)"\s*:', corps):
        return re.sub(r'("(?:code|jeton)"\s*:\s*)"[^"]*"', r'\1"••••"', corps)
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


class JournalActions:
    """File et fil d'écriture de actions.jsonl : noter(action) ne fait que mettre l'action dans la file (le
    serveur n'attend jamais le disque) ; le fil décrit l'action (ligne_action) et l'ajoute au fichier.
    surNote(n) est appelée après chaque ligne écrite (n : le nombre de lignes du journal)."""

    def __init__(self, fichier, debut, mode, noms=None, sur_note=None, mode_actuel=None):
        self.fichier = fichier
        self.debut = debut
        self.mode = mode
        self.noms = dict(noms or {})
        self.sur_note = sur_note
        self.mode_actuel = mode_actuel          # fonction : le mode de la navigation qui tourne, ou None
        self.nombre = self._compter()
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
        """Écrit une action tout de suite (sans la file) : « Terminer la séance », notée par la séance elle-même."""
        ligne = ligne_action(action, self.debut, self._mode(), self.noms)
        with open(self.fichier, "a", encoding="utf-8") as f:
            f.write(json.dumps(ligne, ensure_ascii=False) + "\n")
        self.nombre += 1
        if self.sur_note:
            self.sur_note(self.nombre)
        return ligne

    def _boucle(self):
        while True:
            try:
                action = self._file.get(timeout=0.2)
            except queue.Empty:
                if self._fin.is_set():
                    return
                continue
            if action is None:
                return
            try:
                self.ecrire(action)
            except Exception:       # noqa: BLE001 : une action illisible ne doit pas arrêter le journal
                JOURNAL.exception("journal des actions : une action n'a pas pu être écrite")

    def arreter(self, delai=2.0):
        """Écrit ce qui reste dans la file (delai secondes au plus), puis arrête le fil."""
        self._file.put(None)
        self._fil.join(timeout=delai)
        self._fin.set()
