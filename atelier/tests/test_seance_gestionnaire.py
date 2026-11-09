"""Le gestionnaire de séance du serveur (vague 6, section 13.3 du plan) : agent Boîte noire.

Avec un vrai EtatServeur (pont ROS 2 non démarré), $ATELIER_SEANCES dans le dossier du test, et de fausses commandes
dans $ATELIER_BIN : g1-seance (un enregistreur qui écrit enregistrement.json et s'arrête au SIGINT) et g1-jetson
(journal du conteneur). On vérifie l'ouverture (dossier, manifeste conforme, copie du lieu, journal du serveur,
enregistreur, diagnostic du début), le journal des actions (lignes conformes, jamais bloquant), le journal du Jetson
avant « g1-jetson arreter », la fermeture (« Terminer la séance », enregistreur arrêté, journaux copiés, manifeste,
rapport en arrière-plan), l'arrêt de l'Atelier, la reprise après un plantage, et les refus (Simulation, lieu
inconnu, pas de serveur).
"""
import json
import os
import stat
import subprocess
import sys
import time

import pytest

from atelier.lieu import copier_lieu, valider_donnees
from atelier.lieu.diagnostic import EXEMPLE_DIAGNOSTIC
from atelier.seance import GestionnaireSeance, atelier_vivant, copier_fin, copier_lieu as copier_fichiers_lieu
from atelier.seance import manifeste as M
from atelier.serveur.communs import ErreurAtelier
from .test_serveur_communs import DEMO

FAUX_ENREGISTREUR = r"""#!/bin/bash
# faux g1-seance : « enregistrer --dossier D --atelier PID » écrit enregistrement.json, puis « arrete » au SIGINT ou
# quand l'Atelier PID disparaît (comme le vrai : un serveur de test tué ne laisse pas d'enregistreur)
[ "$1" = enregistrer ] || exit 2
D="$3"
ATELIER="$5"
[ -n "$FAUX_CODE_ENREGISTREUR" ] && exit "$FAUX_CODE_ENREGISTREUR"
ecrire() {
  printf '{"version": 1, "etat": "%s", "pid": %s, "octets": %s, "messages": 7, "sujets": ["/guide/etat"], ' \
    "$1" $$ "$2" > "$D/enregistrement.json.tmp"
  printf '"message": null}\n' >> "$D/enregistrement.json.tmp"
  mv "$D/enregistrement.json.tmp" "$D/enregistrement.json"
}
trap 'ecrire arrete 4096; echo "fin propre"; exit 0' INT TERM
echo "faux enregistreur dans $D"
ecrire en_cours 2048
while [ -z "$ATELIER" ] || kill -0 "$ATELIER" 2>/dev/null; do sleep 0.05; done
ecrire arrete 4096
echo "l'Atelier ne tourne plus : fin"
"""
FAUX_JETSON = r"""#!/bin/bash
# faux g1-jetson : « journal --lignes N » écrit quelques lignes (FAUX_JETSON_CODE, FAUX_JETSON_ATTENTE)
echo "g1-jetson $*" >> "$FAUX_JETSON_TRACE"
sleep "${FAUX_JETSON_ATTENTE:-0}"
echo "[INFO] [pont_g1]: pont prêt"
echo "[ERROR] [guide]: une erreur du conteneur"
exit "${FAUX_JETSON_CODE:-0}"
"""


def _ecrire(chemin, texte):
    chemin.write_text(texte, encoding="utf-8")
    chemin.chmod(chemin.stat().st_mode | stat.S_IXUSR)


@pytest.fixture
def banc(tmp_path, monkeypatch):
    """$ATELIER_SEANCES, $ATELIER_LIEUX (copie du demo) et $ATELIER_BIN (faux g1-seance et g1-jetson)."""
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    _ecrire(bin_ / "g1-seance", FAUX_ENREGISTREUR)
    _ecrire(bin_ / "g1-jetson", FAUX_JETSON)
    monkeypatch.setenv("ATELIER_BIN", str(bin_))
    monkeypatch.setenv("ATELIER_SEANCES", str(tmp_path / "seances"))
    monkeypatch.setenv("ATELIER_LIEUX", str(tmp_path / "lieux"))
    monkeypatch.setenv("FAUX_JETSON_TRACE", str(tmp_path / "jetson.txt"))
    monkeypatch.setenv("ATELIER_PORT", "8142")
    monkeypatch.delenv("FAUX_CODE_ENREGISTREUR", raising=False)
    copier_lieu(DEMO, tmp_path / "lieux" / "demo")
    import atelier
    monkeypatch.setattr(atelier, "dossier_journaux", lambda: tmp_path / "journaux")
    (tmp_path / "journaux").mkdir()
    # le diagnostic du début : l'exemple du contrat (l'agent Diagnostic écrit le vrai)
    import atelier.diagnostic
    monkeypatch.setattr(atelier.diagnostic, "diagnostiquer", lambda *a, **k: dict(EXEMPLE_DIAGNOSTIC))
    return tmp_path


@pytest.fixture
def etat(banc):
    from atelier.serveur.etat import EtatServeur
    e = EtatServeur(ros=True)           # le pont ROS 2 n'est pas démarré : la séance n'en a pas besoin
    yield e
    try:
        e.seance.fermer("arret_atelier")
    finally:
        e.gestionnaire.arreter_tout(attente_sigint=2.0)


def attendre(condition, delai=15.0, pas=0.1):
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        if condition():
            return True
        time.sleep(pas)
    return condition()


def _action(chemin, requete=None, statut=200, reponse=None, t=None):
    return {"t": t or M.heure_iso(ms=True), "methode": "POST", "chemin": chemin, "requete": requete,
            "statut": statut, "reponse": reponse, "duree_ms": 3.0, "client": "local"}


def test_ouverture_journal_jetson_et_fermeture(etat, banc):
    s = etat.seance
    m = s.demarrer("repetition", "demo", "rdc", "auto")
    dossier = banc / "seances" / m["id"]
    assert valider_donnees("seance", m) == []
    assert m["etat"] == "ouverte" and m["mode"] == "repetition" and m["lieu"] == "demo" and m["ouverture"] == "auto"
    assert m["atelier"]["pid"] == os.getpid() and m["atelier"]["port"] == 8142
    assert (dossier / "seance.json").is_file() and (dossier / "lieu" / "salles.yaml").is_file()
    assert (dossier / "lieu" / "lieu.yaml").is_file() and not (dossier / "lieu" / "mondes").exists()
    assert s.demarrer("reel")["id"] == m["id"]                 # une seule séance à la fois : la même est rendue
    # l'enregistreur (faux) tourne dans le rôle « seance », et l'état le dit
    assert etat.gestionnaire.en_cours("seance")
    assert attendre(lambda: (s.etat() or {}).get("badge") == "enregistrement"
                    and s.etat()["enregistrement"]["etat"] == "en_cours")
    assert attendre(lambda: M.lire_manifeste(dossier)["diagnostic_debut"] == "diagnostic_debut.json")
    assert json.loads((dossier / "diagnostic_debut.json").read_text())["etat"] == EXEMPLE_DIAGNOSTIC["etat"]
    # le journal des actions : noter_action rend la main tout de suite ; le fil écrit des lignes conformes
    debut = time.monotonic()
    s.noter_action(_action("/api/guide/aller", {"cible": "b204"}, reponse={"envoye": "b204"}))
    s.noter_action(_action("/api/arret", {"mode": "repetition"}, reponse={"arrete": True, "verrou": True}))
    s.noter_action(_action("/api/borne/operateur", {"code": "1234"}, reponse={"jeton": "secret", "expire_s": 300}))
    assert time.monotonic() - debut < 0.05
    assert attendre(lambda: M.lire_manifeste(dossier)["actions"] == 3)
    lignes = [json.loads(x) for x in (dossier / "actions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [x["genre"] for x in lignes] == ["y_aller", "arret", "borne"]
    assert lignes[0]["texte"] == "Y aller : Salle B204" and lignes[1]["texte"] == "ARRÊT"
    assert lignes[2]["requete"] == {"code": "••••"} and lignes[2]["reponse"]["jeton"] == "••••"   # jamais en clair
    assert all(valider_donnees("action_seance", x) == [] for x in lignes)
    assert all(x["mode"] == "repetition" and x["source"] == "atelier" and x["depuis_s"] >= 0 for x in lignes)
    # le journal du conteneur du Jetson, avant « g1-jetson arreter »
    entree = s.avant_arret_jetson(local=False)
    assert entree["ok"] and entree["raison"] == "avant_arret" and entree["octets"] > 0
    assert entree["fichier"].startswith("journaux/jetson/conteneur_") and entree["fichier"].endswith("_avant_arret.log")
    assert "une erreur du conteneur" in (dossier / entree["fichier"]).read_text()
    assert (banc / "jetson.txt").read_text().strip() == "g1-jetson journal --lignes 100000"
    assert M.lire_manifeste(dossier)["jetson"][0]["fichier"] == entree["fichier"]
    # « Terminer la séance »
    fin = s.arreter("terminer")
    assert fin["etat"] == "fermee" and fin["fermeture"] == "terminer" and fin["duree_s"] >= 0
    assert valider_donnees("seance", fin) == [] and s.etat() is None and s.arreter() is None
    assert not etat.gestionnaire.en_cours("seance")
    assert fin["enregistrement"]["etat"] == "arrete" and fin["enregistrement"]["octets"] == 4096   # SIGINT : propre
    derniere = json.loads((dossier / "actions.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert derniere["texte"] == "Terminer la séance" and derniere["genre"] == "seance" and fin["actions"] == 4
    journaux = sorted(p.name for p in (dossier / "journaux").glob("atelier_seance_*.log"))
    assert journaux and "fin propre" in (dossier / "journaux" / journaux[0]).read_text()
    assert (dossier / "journaux" / "serveur.log").is_file()
    # le rapport s'écrit en arrière-plan (g1-seance rapport, détaché)
    assert attendre(lambda: M.lire_manifeste(dossier)["rapport"]["etat"] == "pret", 90, 0.5), \
        (dossier / "journaux" / "rapport.log").read_text()
    assert (dossier / "rapport.html").is_file() and s.derniere()["id"] == m["id"]
    assert valider_donnees("seance", M.lire_manifeste(dossier)) == []


def test_actions_pendant_terminer_la_seance_gardees(etat, banc, monkeypatch):
    """Corrections de la vague 6 (revue du code, défaut 7) : pendant « Terminer la séance » (journal du conteneur du
    Jetson, jusqu'à 30 s, puis l'arrêt de l'enregistreur), chaque action était jetée, ARRÊT compris. Le journal des
    actions se ferme maintenant en dernier."""
    import threading
    s = etat.seance
    m = s.demarrer("reel", "demo", "rdc", "auto")
    dossier = banc / "seances" / m["id"]
    monkeypatch.setattr(etat, "mode_navigation", lambda: "robot")      # le robot tourne : journal du Jetson à la fin
    monkeypatch.setenv("FAUX_JETSON_ATTENTE", "2")
    s.noter_action(_action("/api/guide/aller", {"cible": "b204"}, reponse={"envoye": "b204"}))
    fin = {}
    fil = threading.Thread(target=lambda: fin.update(m=s.arreter("terminer")))
    fil.start()
    time.sleep(0.8)                                                    # pendant le journal du Jetson
    s.noter_action(_action("/api/arret", {"mode": "reel"}, reponse={"arrete": True, "verrou": True}))
    fil.join(timeout=30)
    assert fin["m"]["etat"] == "fermee", fin
    lignes = [json.loads(x) for x in (dossier / "actions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [x["genre"] for x in lignes] == ["y_aller", "seance", "arret"], [x["texte"] for x in lignes]
    assert lignes[1]["texte"] == "Terminer la séance" and fin["m"]["actions"] == 3
    # après la fermeture, plus rien n'est noté
    s.noter_action(_action("/api/arret", {"mode": "reel"}))
    time.sleep(0.3)
    assert len((dossier / "actions.jsonl").read_text(encoding="utf-8").splitlines()) == 3


def test_refus_simulation_lieu_inconnu_et_sans_serveur(etat, banc):
    s = etat.seance
    for mode in ("simu",):
        with pytest.raises(ErreurAtelier) as e:
            s.demarrer(mode)
        assert e.value.statut == 409 and "Simulation" in e.value.detail
    with pytest.raises(ErreurAtelier) as e:
        s.demarrer("lune")
    assert e.value.statut == 400
    with pytest.raises(ErreurAtelier) as e:
        s.demarrer("reel", "lieu_inconnu")
    assert e.value.statut == 404
    with pytest.raises(ErreurAtelier) as e:
        s.demarrer("reel", "demo", "etage_inconnu")
    assert e.value.statut == 404
    etat.simulation = {"lieu": "demo", "etage": "rdc", "mode": "simu"}
    etat.gestionnaire.en_cours = lambda role: role == "navigation"           # la simulation tourne
    with pytest.raises(ErreurAtelier) as e:
        s.demarrer(None)
    assert e.value.statut == 409
    with pytest.raises(ErreurAtelier) as e:
        GestionnaireSeance().demarrer("reel")
    assert e.value.statut == 503
    assert not (banc / "seances").exists() or not list((banc / "seances").iterdir())


def test_mode_et_lieu_par_defaut(etat, banc):
    """Sans mode : celui de la navigation qui tourne ; sans lieu : celui de la navigation ; robot → reel."""
    etat.simulation = {"lieu": "demo", "etage": "rdc", "mode": "repetition"}
    etat.gestionnaire.en_cours = lambda role: role in ("navigation", "simulation")
    m = etat.seance.demarrer(None, None, None, "g1-seance")
    assert (m["mode"], m["lieu"], m["etage"], m["ouverture"]) == ("repetition", "demo", "rdc", "g1-seance")
    etat.seance.arreter()
    etat.simulation = None
    m = etat.seance.demarrer("robot", "demo")
    assert m["mode"] == "reel" and m["etage"] == "rdc"          # l'étage du point principal


def test_sans_ros_sans_commande_et_enregistreur_qui_s_arrete(etat, banc, monkeypatch):
    etat.ros = False
    m = etat.seance.demarrer("reel")
    assert m["enregistrement"]["etat"] == "absent" and "sans ROS 2" in m["enregistrement"]["message"]
    assert not etat.gestionnaire.en_cours("seance") and m["lieu"] is None
    assert etat.seance.etat()["badge"] == "arrete"
    etat.seance.arreter()
    etat.ros = True
    (banc / "bin" / "g1-seance").unlink()
    m = etat.seance.demarrer("reel")
    assert m["enregistrement"]["etat"] == "absent" and "g1-seance est introuvable" in m["enregistrement"]["message"]
    etat.seance.arreter()
    _ecrire(banc / "bin" / "g1-seance", FAUX_ENREGISTREUR)
    monkeypatch.setenv("FAUX_CODE_ENREGISTREUR", "3")
    m = etat.seance.demarrer("reel")
    dossier = banc / "seances" / m["id"]
    assert attendre(lambda: M.lire_manifeste(dossier)["enregistrement"]["etat"] == "erreur")
    e = M.lire_manifeste(dossier)["enregistrement"]
    assert "code 3" in e["message"] and etat.seance.etat()["badge"] == "arrete"


def test_noter_action_ne_gene_jamais(etat, banc):
    s = etat.seance
    assert s.noter_action(_action("/api/arret")) is None                # sans séance : rien
    s.demarrer("repetition")
    for bizarre in ({}, {"chemin": None}, {"chemin": "/api/x", "statut": "pas un nombre", "requete": object()},
                    {"chemin": "/api/guide/aller", "requete": {"cible": None}}):
        assert s.noter_action(bizarre) is None
    s._ouverte.journal = None
    assert s.noter_action(_action("/api/arret")) is None


def test_fermer_a_l_arret_de_l_atelier(etat, banc):
    m = etat.seance.demarrer("repetition", "demo")
    debut = time.monotonic()
    etat.seance.fermer()
    assert time.monotonic() - debut < 10.0
    fin = M.lire_manifeste(banc / "seances" / m["id"])
    assert fin["etat"] == "fermee" and fin["fermeture"] == "arret_atelier"
    lignes = (banc / "seances" / m["id"] / "actions.jsonl")
    assert not lignes.exists() or "Terminer la séance" not in lignes.read_text(encoding="utf-8")
    etat.seance.fermer()                                                # une seconde fois : rien


def test_journal_du_jetson_en_echec_trop_long_et_sans_seance(etat, banc, monkeypatch):
    assert etat.seance.avant_arret_jetson() is None                     # sans séance : rien
    m = etat.seance.demarrer("reel")
    monkeypatch.setenv("FAUX_JETSON_CODE", "1")
    e = etat.seance.avant_arret_jetson(local=True)
    assert e["ok"] is False and "code 1" in e["message"]
    assert "--local" in (banc / "jetson.txt").read_text()
    monkeypatch.setenv("FAUX_JETSON_CODE", "0")
    monkeypatch.setenv("FAUX_JETSON_ATTENTE", "5")
    debut = time.monotonic()
    e = etat.seance.avant_arret_jetson(delai=1.0)
    assert time.monotonic() - debut < 4.0 and e["ok"] is False and "délai dépassé" in e["message"]
    (banc / "bin" / "g1-jetson").unlink()
    e = etat.seance.avant_arret_jetson()
    assert e["ok"] is False and "introuvable" in (banc / "seances" / m["id"] / e["fichier"]).read_text()
    assert valider_donnees("seance", M.lire_manifeste(banc / "seances" / m["id"])) == []
    # la navigation du robot qui tourne encore à la fermeture : son journal est gardé (raison « fin »)
    monkeypatch.setenv("FAUX_JETSON_ATTENTE", "0")
    _ecrire(banc / "bin" / "g1-jetson", FAUX_JETSON)
    etat.simulation = {"lieu": "demo", "etage": "rdc", "mode": "robot", "en_cours": True}
    fin = etat.seance.arreter()
    assert fin["jetson"][-1]["raison"] == "fin" and fin["jetson"][-1]["ok"]


def _seance_ouverte_orpheline(banc, pid_atelier):
    ident, dossier = M.creer_dossier(racine=banc / "seances")
    m = M.nouveau_manifeste(ident, "repetition", "demo", "rdc", "auto", debut=time.time() - 60)
    m["atelier"]["pid"] = pid_atelier
    m["enregistrement"].update(etat="en_cours", pid=pid_atelier)
    M.ecrire_manifeste(dossier, m)
    (dossier / "actions.jsonl").write_text('{"version": 1}\n{"version": 1}\n', encoding="utf-8")
    return dossier


def test_reprise_apres_un_plantage(etat, banc):
    mort = subprocess.Popen([sys.executable, "-c", "pass"])
    mort.wait()
    orpheline = _seance_ouverte_orpheline(banc, mort.pid)
    # une séance ouverte par un autre Atelier qui tourne encore n'est pas touchée
    vivant = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", "atelier.serveur.main:app"])
    try:
        # juste après Popen, le fils n'a pas toujours fait son exec : sa ligne de commande est encore celle d'avant
        # (échec vu sous charge à l'assemblage) ; on attend qu'elle soit la sienne
        assert attendre(lambda: atelier_vivant(vivant.pid), 5.0, 0.02)
        autre = _seance_ouverte_orpheline(banc, vivant.pid)
        etat.seance.demarrage_serveur()
        assert attendre(lambda: M.lire_manifeste(orpheline)["etat"] == "interrompue", 30)
        assert attendre(lambda: M.lire_manifeste(orpheline)["rapport"]["etat"] == "pret", 90, 0.5)
        m = M.lire_manifeste(orpheline)
        assert m["fermeture"] == "plantage" and m["actions"] == 2 and m["enregistrement"]["etat"] == "arrete"
        assert m["fin"] is not None and valider_donnees("seance", m) == []
        assert any("interrompue" in x for x in m["messages"])
        assert M.lire_manifeste(autre)["etat"] == "ouverte"
        assert etat.seance.etat() is None                     # aucune séance ne s'ouvre seule au démarrage
    finally:
        vivant.kill()
        vivant.wait()


def test_outils(tmp_path):
    source = tmp_path / "journal.log"
    source.write_text("".join(f"ligne {i}\n" for i in range(1000)), encoding="utf-8")
    copier_fin(source, tmp_path / "copie.log", 100)
    texte = (tmp_path / "copie.log").read_text(encoding="utf-8")
    assert texte.startswith("[… début du journal coupé") and texte.endswith("ligne 999\n") and len(texte) < 300
    copier_fin(source, tmp_path / "entier.log", 10 ** 6)
    assert (tmp_path / "entier.log").read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
    copies = copier_fichiers_lieu(DEMO, tmp_path / "lieu", "rdc")
    assert "salles.yaml" in copies and all(not c.startswith("mondes") for c in copies)
    assert not atelier_vivant(os.getpid()) and not atelier_vivant(None)
