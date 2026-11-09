"""Le journal des actions de la boîte noire (vague 6, section 13.3 du plan) : agent Boîte noire.

Le genre et le texte en français de chaque demande à l'API (decrire), la ligne complète conforme au schéma
action_seance (ligne_action), les secrets masqués (code opérateur de la borne, jeton), et la file d'écriture qui ne
bloque jamais (JournalActions).
"""
import json
import time

import pytest

from atelier.lieu import valider_donnees
from atelier.lieu.seance import GENRES_ACTION
from atelier.seance.actions import JournalActions, decrire, ligne_action
from atelier.seance.manifeste import heure_iso

NOMS = {"b204": "Salle B204", "accueil": "Accueil"}

CAS = [
    ("POST", "/api/arret", {"mode": "reel"}, None, "arret", "ARRÊT"),
    ("POST", "/api/arret/debloquer", None, None, "debloquer", "Débloquer"),
    ("POST", "/api/robot/arret", {"verrou": True}, None, "bloquer", "Bloquer"),
    ("POST", "/api/robot/arret", {"verrou": False}, None, "debloquer", "Débloquer"),
    ("POST", "/api/guide/aller", {"cible": "b204"}, None, "y_aller", "Y aller : Salle B204"),
    ("POST", "/api/guide/aller", {"cible": "principal"}, None, "y_aller", "Y aller : le point principal"),
    ("POST", "/api/guide/aller", {"cible": "b204", "accompagner": True, "retour": False}, None, "y_aller",
     "Y aller : Salle B204 (avec un visiteur), sans retour"),
    ("POST", "/api/guide/aller", {"cible": "inconnue"}, None, "y_aller", "Y aller : inconnue"),
    ("POST", "/api/guide/stop", None, None, "stop", "Arrêter le trajet"),
    ("POST", "/api/robot/reperer", {"lieu": "demo"}, {"repere": True}, "reperer", "Repérer le robot : repéré"),
    ("POST", "/api/robot/reperer", {"x": 1, "y": 2}, {"detail": "non"}, "reperer",
     "Repérer le robot (position donnée à la main)"),
    ("POST", "/api/simulation/demarrer", {"mode": "repetition"}, None, "lancer",
     "Lancer la navigation (répétition sans robot)"),
    ("POST", "/api/simulation/demarrer", {"mode": "robot"}, None, "lancer", "Lancer la navigation du robot"),
    ("POST", "/api/simulation/demarrer", {}, None, "lancer", "Lancer la simulation"),
    ("POST", "/api/simulation/arreter", None, None, "arreter", "Arrêter la navigation"),
    # corrections de la vague 6 (revue de l'interface, défaut 12) : ce qui a été arrêté, d'après la réponse
    ("POST", "/api/simulation/arreter", None, {"simulation": {"lieu": "demo", "mode": "simu"}}, "arreter",
     "Arrêter la simulation"),
    ("POST", "/api/simulation/arreter", None, '{"simulation": {"lieu": "demo", "en_cours": false, '
     '"mode": "repetition", "avertissements": []}, "processus": {"navigation": […]', "arreter",
     "Arrêter la navigation (répétition sans robot)"),
    ("POST", "/api/guide/visiteur", {"mode": "partir"}, None, "autre", "Faux visiteur : il s'en va"),
    ("POST", "/api/guide/visiteur", {"mode": "danser"}, None, "autre", "Faux visiteur : danser"),
    ("POST", "/api/scan/demarrer", {}, None, "scan", "Scan : démarrer"),
    ("POST", "/api/scan/arreter", {}, None, "scan", "Scan : fin"),
    ("POST", "/api/scan/sessions/2026-10-27_14h22/adopter", {}, None, "scan", "Scan : utiliser cette carte"),
    ("POST", "/api/pilotage/posture", {"fsm": 3}, None, "pilotage", "Posture : S'asseoir"),
    ("POST", "/api/pilotage/maitre", {"maitre": "pilotage", "forcer": True}, None, "pilotage",
     "Prendre la main (forcé)"),
    ("POST", "/api/pilotage/maitre", {"maitre": "guide"}, None, "pilotage", "Rendre la main au guide"),
    ("POST", "/api/pilotage/geste", {"action": 99}, None, "pilotage", "Geste : Relâcher les bras"),
    ("POST", "/api/pilotage/tache", {"tache": 0}, None, "pilotage", "Geste : Saluer"),
    ("POST", "/api/pilotage/danse", {"id": 604}, None, "pilotage", "Danse 604 (danse robot (environ 18 s))"),
    ("POST", "/api/pilotage/voix", {"texte": "Bonjour à tous"}, None, "pilotage", "Voix du robot : « Bonjour à tous »"),
    ("POST", "/api/pilotage/volume", {"volume": 60}, None, "pilotage", "Volume du robot : 60"),
    ("POST", "/api/pilotage/led", {"r": 0, "g": 0, "b": 0}, None, "pilotage", "Lumière éteinte"),
    ("POST", "/api/pilotage/led", {"r": 255, "g": 0, "b": 0}, None, "pilotage", "Lumière du robot"),
    ("POST", "/api/pilotage/arret", None, None, "pilotage", "ARRÊT du pilotage"),
    ("POST", "/api/pilotage/demarrer", None, None, "pilotage", "Lancer le pilotage"),
    ("POST", "/api/pilotage/choregraphies/exemple_kpop/jouer", {}, None, "choregraphie",
     "Chorégraphie : exemple_kpop"),
    ("POST", "/api/pilotage/choregraphies/verifier", {}, None, "choregraphie", "Chorégraphie vérifiée"),
    ("DELETE", "/api/pilotage/choregraphies/essai", None, None, "choregraphie",
     "Chorégraphie enregistrée ou supprimée : essai"),
    ("POST", "/api/robot/diagnostic/demarrer-services", {"confirme": True}, None, "diagnostic",
     "Diagnostic : Démarrer les services de cartographie"),
    ("POST", "/api/robot/diagnostic/inconnue", {}, None, "diagnostic", "Diagnostic : inconnue"),
    ("POST", "/api/seance/demarrer", {"ouverture": "auto"}, None, "seance", "Ouvrir la séance (automatique)"),
    ("POST", "/api/seance/arreter", {}, None, "seance", "Terminer la séance"),
    ("POST", "/api/seances/2026-11-12_14h03/rapport", None, None, "seance", "Refaire le rapport de séance"),
    ("POST", "/api/demo/lancer", {}, None, "demo", "Lancer la démo"),
    ("POST", "/api/demo/commande", {"action": "pause"}, None, "demo", "Démo : pause"),
    ("POST", "/api/borne/choisir", {"salle": "b204"}, None, "borne", "Borne : Salle B204"),
    ("POST", "/api/borne/appui", {}, None, "borne", "Borne : appui"),
    ("POST", "/api/borne/operateur", {"code": "1234"}, None, "borne", "Borne : code opérateur"),
    ("POST", "/api/borne/operateur/ramener", {}, None, "borne", "Borne (opérateur) : ramener"),
    ("POST", "/api/voix/essayer", {"texte": "Bonjour"}, None, "voix", "Voix : essayer « Bonjour »"),
    ("POST", "/api/voix/commande", {"action": "taire"}, None, "voix", "Voix : taire"),
    ("POST", "/api/equipe/visiteur", {}, None, "equipe", "Équipe : visiteur"),
    ("PUT", "/api/lieux/demo/personnalites", [], None, "equipe", "Personnalités enregistrées"),
    ("POST", "/api/lieux/demo/personnalites/active", {"id": "joyeux"}, None, "equipe",
     "Personnalité choisie : joyeux"),
    ("POST", "/api/lieux/demo/dialogues/essayer", {}, None, "equipe", "Dialogues : essayer une phrase"),
    ("PUT", "/api/lieux/demo/salles", [], None, "lieu", "Salles enregistrées"),
    ("PUT", "/api/lieux/demo/demo", {}, None, "lieu", "Réglages de la démo enregistrés"),
    ("PUT", "/api/lieux/demo", {}, None, "lieu", "Fiche du lieu enregistrée"),
    ("POST", "/api/lieux", {"id": "essai"}, None, "lieu", "Nouveau lieu : essai"),
    ("PUT", "/api/lieux/demo/etages/rdc/monde", {}, None, "lieu", "Monde enregistré"),
    ("POST", "/api/lieux/demo/etages/rdc/monde/generer", None, None, "lieu", "Carte refaite"),
    ("PUT", "/api/lieux/demo/principal", {"theta": 1.57}, None, "lieu", "Point principal déplacé"),
    ("POST", "/api/truc/inconnu", {}, None, "autre", "POST /api/truc/inconnu"),
]


@pytest.mark.parametrize("methode,chemin,requete,reponse,genre,texte", CAS)
def test_genre_et_texte(methode, chemin, requete, reponse, genre, texte):
    assert decrire(methode, chemin, requete, reponse, NOMS) == (genre, texte)
    assert genre in GENRES_ACTION


def test_tous_les_genres_du_contrat_sont_produits():
    assert {c[4] for c in CAS} == set(GENRES_ACTION)


def test_ligne_conforme_et_secrets_masques():
    debut = time.time() - 10
    action = {"t": heure_iso(ms=True), "methode": "POST", "chemin": "/api/borne/operateur", "requete": {"code": "1234"},
              "statut": 200, "reponse": {"jeton": "abc", "expire_s": 300}, "duree_ms": 4.2, "client": "borne"}
    ligne = ligne_action(action, debut, "reel", NOMS)
    assert valider_donnees("action_seance", ligne) == []
    assert ligne["requete"] == {"code": "••••"} and ligne["reponse"] == {"jeton": "••••", "expire_s": 300}
    assert ligne["source"] == "borne" and ligne["client"] == "borne" and 9 < ligne["depuis_s"] < 12
    # corps coupé (texte) : le code est masqué aussi
    texte = ligne_action(dict(action, requete='{"code": "9876", "x": "' + "a" * 50 + ' […]'), debut, "reel")
    assert "9876" not in texte["requete"]
    # corrections de la vague 6 (revue du code, défaut 6) : le code des réglages de la démo (PUT …/demo, la demande
    # et la réponse qui rend le fichier) était écrit en clair
    reglages = {"version": 1, "borne": {"code_operateur": "4826", "langue": "fr"}, "accompagner": True}
    demo = ligne_action({"t": heure_iso(ms=True), "methode": "PUT", "chemin": "/api/lieux/seance/demo",
                         "requete": reglages, "statut": 200, "reponse": {"enregistre": ["demo.yaml"],
                                                                         "donnees": reglages}}, debut, "reel")
    assert "4826" not in json.dumps(demo) and demo["requete"]["borne"] == {"code_operateur": "••••", "langue": "fr"}
    assert demo["reponse"]["donnees"]["borne"]["code_operateur"] == "••••" and reglages["borne"]["code_operateur"]
    for coupe in ('{"borne": {"code_operateur": "4826", "langue": "fr"}, "x": "a […]',
                  '{"borne": {"code_operateur": "48', '{"borne": {"code_operateur": 4826, "x": 1', '{"code": 1234}'):
        texte = ligne_action(dict(action, chemin="/api/lieux/seance/demo", methode="PUT", requete=coupe), debut,
                             "reel")["requete"]
        assert "4826" not in texte and "48" not in texte.replace("••••", "") and "1234" not in texte, texte
    # statut absent ou absurde, mode inconnu, client inconnu : la ligne reste conforme
    bizarre = ligne_action({"chemin": "/api/arret", "statut": 999, "client": "martien"}, None, "lune")
    assert valider_donnees("action_seance", bizarre) == []
    assert bizarre["statut"] is None and bizarre["mode"] is None and bizarre["client"] == "local"
    assert "depuis_s" not in bizarre
    # demande faite par g1-seance
    g1 = ligne_action({"chemin": "/api/seance/demarrer", "requete": {"ouverture": "g1-seance"}, "statut": 200}, debut,
                      "reel")
    assert g1["source"] == "g1-seance"


def test_journal_ne_bloque_jamais_et_garde_l_ordre(tmp_path):
    vus = []
    j = JournalActions(tmp_path / "actions.jsonl", time.time(), "repetition", NOMS, sur_note=vus.append,
                       mode_actuel=lambda: "robot")
    debut = time.monotonic()
    for i in range(200):
        j.noter({"t": heure_iso(ms=True), "methode": "POST", "chemin": "/api/guide/aller",
                 "requete": {"cible": "b204" if i % 2 else "accueil"}, "statut": 200, "client": "local"})
    assert time.monotonic() - debut < 0.1                       # la file seulement
    j.noter(None)                                               # une action illisible n'arrête pas le journal
    j.arreter(delai=5.0)
    lignes = [json.loads(x) for x in (tmp_path / "actions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(lignes) == 200 and j.nombre == 200 and vus[-1] == 200
    assert [x["texte"] for x in lignes[:2]] == ["Y aller : Accueil", "Y aller : Salle B204"]
    assert all(x["mode"] == "reel" for x in lignes)             # le mode de la navigation qui tourne
    # un journal rouvert compte ses lignes
    rouvert = JournalActions(tmp_path / "actions.jsonl", time.time(), "reel")
    assert rouvert.nombre == 200
    rouvert.arreter()


# ------------------------------------------------ corrections de la vague 6 (revue du code, défaut 9)
# Un client du réseau qui insiste (3 000 demandes refusées en 1,7 s, 476 octets chacune : 3 Go par heure) remplissait
# le disque par actions.jsonl et serveur.log, que les garde-fous de la séance (bag seulement) ne couvraient pas.

class Horloge:
    def __init__(self, t=1794000000.0):
        self.t = t

    def __call__(self):
        return self.t


def _lignes(fichier):
    return [json.loads(x) for x in fichier.read_text(encoding="utf-8").splitlines()]


def _refusee(h, client="distant", chemin="/api/arret/debloquer", **plus):
    return dict({"t": heure_iso(h.t, ms=True), "methode": "POST", "chemin": chemin, "requete": "x" * 400,
                 "statut": 403, "reponse": {"detail": "Depuis cette tablette, seule la borne est permise."},
                 "client": client, "garde": "borne"}, **plus)


def test_demandes_repetees_resumees_par_minute(tmp_path):
    from atelier.seance.actions import motif_repetition
    h = Horloge()
    j = JournalActions(tmp_path / "actions.jsonl", h.t, "repetition", NOMS, horloge=h)
    for _ in range(1000):                                  # une page ou une machine qui insiste, la même minute
        j.noter(_refusee(h))
    j.noter(_refusee(h, client="local", chemin="/api/voix/essayer", garde="origine"))   # autre client : à part
    j.noter({"t": heure_iso(h.t, ms=True), "methode": "POST", "chemin": "/api/arret", "requete": {"mode": "reel"},
             "statut": 200, "client": "local"})          # une action ordinaire : notée telle quelle
    for _ in range(3):                                     # rebonds de la borne et codes faux : résumés aussi
        j.noter({"t": heure_iso(h.t, ms=True), "methode": "POST", "chemin": "/api/borne/appui", "statut": 200,
                 "reponse": {"accepte": True, "rebond": True}, "client": "borne"})
        j.noter({"t": heure_iso(h.t, ms=True), "methode": "POST", "chemin": "/api/borne/operateur", "statut": 429,
                 "requete": {"code": "0000"}, "client": "borne"})
    deadline = time.monotonic() + 5
    while j.nombre < 5 and time.monotonic() < deadline:
        time.sleep(0.05)
    h.t += 61.0                                            # la minute suivante : un premier résumé, puis une ligne
    j.noter(_refusee(h))
    j.arreter(delai=5.0)
    lignes = _lignes(tmp_path / "actions.jsonl")
    assert all(valider_donnees("action_seance", x) == [] for x in lignes)
    resumes = {(x["client"], x["resume"]["motif"]): x for x in lignes if "resume" in x}
    assert resumes[("distant", "garde")]["resume"]["nombre"] == 999
    assert resumes[("distant", "garde")]["texte"].startswith("+999 demandes pareilles refusées par la garde")
    assert resumes[("distant", "garde")]["requete"] is None
    assert resumes[("borne", "rebond")]["resume"]["nombre"] == 2
    assert resumes[("borne", "trop_d_essais")]["resume"]["nombre"] == 2 and ("local", "garde") not in resumes
    assert [x["texte"] for x in lignes if x["genre"] == "arret"] == ["ARRÊT"]
    # 1 006 demandes : 9 lignes (les premières de chaque série, leurs résumés, l'ARRÊT, la minute suivante)
    assert len(lignes) == 9, [x["texte"] for x in lignes]
    assert motif_repetition({"statut": 403}) is None      # un refus d'une route (pas de la garde) reste une ligne


def test_journal_des_actions_coupe_a_sa_taille_maximale(tmp_path):
    h = Horloge()
    fichier = tmp_path / "actions.jsonl"
    j = JournalActions(fichier, h.t, "reel", NOMS, taille_max_mo=0.004, horloge=h)
    for i in range(40):
        h.t += 1.0
        j.noter({"t": heure_iso(h.t, ms=True), "methode": "POST", "chemin": "/api/guide/aller",
                 "requete": {"cible": "b204"}, "statut": 200, "client": "local"})
    for genre_chemin, client in ((("/api/arret", 200), "local"), (("/api/arret", 403), "distant"),
                                 (("/api/arret/debloquer", 200), "local")):
        h.t += 1.0
        j.noter({"t": heure_iso(h.t, ms=True), "methode": "POST", "chemin": genre_chemin[0],
                 "statut": genre_chemin[1], "client": client})
    j.arreter(delai=5.0)
    lignes = _lignes(fichier)
    assert all(valider_donnees("action_seance", x) == [] for x in lignes)
    coupures = [x for x in lignes if x.get("coupure")]
    assert len(coupures) == 1 and coupures[0]["texte"].startswith("Journal des actions coupé : il a atteint 0.004 Mo")
    apres = lignes[lignes.index(coupures[0]) + 1:]
    # après la coupure : l'ARRÊT et « Débloquer » de ce PC seulement, puis le nombre d'actions non notées
    assert [x["texte"] for x in apres[:2]] == ["ARRÊT", "Débloquer"]
    assert apres[-1]["non_notees"] >= 1 and "non notée" in apres[-1]["texte"]
    assert fichier.stat().st_size < 4000 + 3 * 600


def test_journal_du_serveur_plafonne(tmp_path):
    import logging
    from atelier.seance import _JournalPlafonne, _Plafond
    fichier = tmp_path / "serveur.log"
    plafond = _Plafond(fichier, 2000)
    journal = logging.getLogger("essai.plafond")
    journal.propagate = False
    journal.setLevel(logging.INFO)
    deux = [_JournalPlafonne(fichier, plafond), _JournalPlafonne(fichier, plafond)]    # racine et uvicorn
    for g in deux:
        journal.addHandler(g)
    try:
        for i in range(500):
            journal.info("demande refusée %d %s", i, "x" * 40)
    finally:
        for g in deux:
            journal.removeHandler(g)
            g.close()
    texte = fichier.read_text(encoding="utf-8")
    assert len(texte.encode("utf-8")) < 2000 + 200
    assert texte.count("Journal du serveur coupé : il a atteint 0.002 Mo") == 1


def test_ouvrir_une_seance_deja_ouverte_n_est_pas_note(tmp_path):
    """Corrections de la vague 6 (revue de l'interface, défaut 12) : chaque réouverture de l'espace en Réel notait
    « Ouvrir la séance (automatique) » (11 fois dans une séance) alors qu'elle était déjà ouverte."""
    from atelier.seance.actions import action_sans_effet
    h = Horloge()
    j = JournalActions(tmp_path / "actions.jsonl", h.t, "reel", NOMS, horloge=h)
    for nouvelle in (True, False, False):
        j.noter({"t": heure_iso(h.t, ms=True), "methode": "POST", "chemin": "/api/seance/demarrer",
                 "requete": {"mode": "reel", "ouverture": "auto"}, "statut": 200,
                 "reponse": {"seance": {"id": "s"}, "nouvelle": nouvelle}, "client": "local"})
    j.arreter(delai=5.0)
    assert [x["texte"] for x in _lignes(tmp_path / "actions.jsonl")] == ["Ouvrir la séance (automatique)"]
    assert not action_sans_effet({"chemin": "/api/seance/demarrer", "reponse": "texte coupé"})
    assert action_sans_effet({"chemin": "/api/seance/demarrer", "reponse": '{"nouvelle": false, "seance": {"id": […]'})
    assert not action_sans_effet({"chemin": "/api/seance/demarrer", "reponse": '{"nouvelle": true, "seance": {"i'})
    assert not action_sans_effet({"chemin": "/api/arret", "reponse": {"nouvelle": False}})
