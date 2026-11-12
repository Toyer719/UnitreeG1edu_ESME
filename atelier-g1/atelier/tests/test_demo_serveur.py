"""Les routes de la démo d'accueil (vague 6, section 13.4 du plan), sans ROS : agent Borne et orchestrateur.

Lancer la démo (409 sans guide, sur un autre lieu, robot pas repéré ; g1-accueil et g1-voix lancés avec les
bons arguments, sortie borne en simulation, suivre_pont), l'arrêter, l'état, les commandes de l'Atelier (pause,
reprendre, ramener, remise_a_zero : réponse de la démo, refus en français), demo.yaml par l'API (GET complété par
les défauts, PUT vérifié, 422 en français), jamais d'erreur 500.
"""
import time

import pytest

from atelier.lieu import accueil as A

from .test_borne_communs import client_demo, ecrire_fausses_commandes, ouvrir_client


@pytest.fixture
def demo(tmp_path, monkeypatch):
    app, pont, dossier = client_demo(tmp_path, monkeypatch)
    with ouvrir_client(app) as c:
        c.pont, c.dossier, c.etat = pont, dossier, app.state.atelier
        yield c


@pytest.fixture
def fausses(tmp_path, monkeypatch):
    journal = tmp_path / "appels.txt"
    monkeypatch.setenv("ATELIER_BIN", str(ecrire_fausses_commandes(tmp_path / "bin", journal)))
    monkeypatch.delenv("FAUX_VOIX_ECHEC", raising=False)
    return journal


def _appels(journal, nom, delai=5.0):
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        if journal.exists():
            lignes = [x for x in journal.read_text().splitlines() if x.startswith(nom + " ")]
            if lignes:
                return lignes
        time.sleep(0.05)
    return []


def _simulation(c, mode="simu", lieu="essai", etage="rdc"):
    c.etat.simulation = {"lieu": lieu, "etage": etage, "dossier": "", "monde": None, "debut": time.time(),
                         "avertissements": [], "mode": mode}
    c.etat.mode_navigation = lambda: mode


def test_etat_sans_demo(demo):
    r = demo.get("/api/demo/etat").json()
    assert r["lancee"] is False and r["processus"] == {"demo": None, "voix": None}
    assert r["etat"]["etat"] == "attente"           # le faux pont a une démo qui répond
    demo.pont.recus.pop("/accueil/etat")
    assert demo.get("/api/demo/etat").json()["etat"] is None


def test_lancer_sans_guide(demo, fausses):
    r = demo.post("/api/demo/lancer", json={"lieu": "essai"})
    assert r.status_code == 409 and "Simuler › Lancer" in r.json()["detail"]
    _simulation(demo, lieu="autre")
    r = demo.post("/api/demo/lancer", json={"lieu": "essai"})
    assert r.status_code == 409 and "« autre »" in r.json()["detail"]
    _simulation(demo, mode="repetition")
    r = demo.post("/api/demo/lancer", json={"lieu": "essai"})
    assert r.status_code == 409 and "Repérer le robot" in r.json()["detail"]
    assert demo.post("/api/demo/lancer", json={"lieu": "nulle_part"}).status_code == 404
    assert demo.post("/api/demo/lancer", json={"lieu": "essai", "etage": "etage9"}).status_code == 404


def test_lancer_sans_guide_dit_quoi_lancer_dans_ce_mode(demo, fausses):
    """Corrections de la vague 6 (revue de l'interface, défaut 13) : en répétition, la phrase parlait de « Simuler ›
    Lancer » (il n'y a pas d'onglet Simuler en Réel) et la barre d'état la coupait à 1 366 px."""
    from atelier.serveur.routes import demo as D
    reel = demo.post("/api/demo/lancer", json={"lieu": "essai", "mode": "reel"})
    assert reel.status_code == 409 and reel.json()["detail"] == D.MESSAGES_SANS_GUIDE["reel"]
    assert "Naviguer › Lancer" in reel.json()["detail"] and "Simuler" not in reel.json()["detail"]
    simu = demo.post("/api/demo/lancer", json={"lieu": "essai", "mode": "simu"})
    assert simu.status_code == 409 and "Simuler › Lancer" in simu.json()["detail"]
    assert "Naviguer" not in simu.json()["detail"]
    assert all(len(m) <= 80 for m in D.MESSAGES_SANS_GUIDE.values())
    autre = demo.post("/api/demo/lancer", json={"lieu": "essai", "mode": "martien"})     # mode inconnu : les deux
    assert autre.status_code == 409 and autre.json()["detail"] == D.MESSAGE_SANS_GUIDE


def test_lancer_refuse_si_une_demo_tourne_dehors(demo, fausses):
    _simulation(demo)
    demo.pont.rafraichir()                       # une démo répond, lancée hors de l'Atelier
    r = demo.post("/api/demo/lancer", json={"lieu": "essai"})
    assert r.status_code == 409 and "hors de l'Atelier" in r.json()["detail"]


def test_lancer_et_arreter_en_simulation(demo, fausses):
    _simulation(demo)
    demo.pont.recus.pop("/accueil/etat", None)    # pas de démo qui tourne déjà
    A.enregistrer_demo(demo.dossier, {"version": 1, "voix": {"sortie": "robot", "volume": 55}})
    r = demo.post("/api/demo/lancer", json={"lieu": "essai"})
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["lancee"] and corps["etage"] == "rdc" and corps["sortie_voix"] == "borne"
    assert any("borne" in a for a in corps["avertissements"])
    accueil = _appels(fausses, "g1-accueil")
    assert accueil and f"--lieu {demo.dossier} --etage rdc -- --ros-args -p suivre_pont:=false" in accueil[0]
    voix = _appels(fausses, "g1-voix")
    assert voix and f"--lieu {demo.dossier} --sortie borne --volume 55 --voix fr_FR-siwis-medium" in voix[0]
    e = demo.get("/api/demo/etat").json()
    assert e["lancee"] and e["processus"]["demo"]["en_cours"] and e["processus"]["voix"]["en_cours"]
    assert e["lieu"] == "essai" and e["avertissements"] == []
    r = demo.post("/api/demo/arreter")
    assert r.status_code == 200 and r.json()["lancee"] is False and "ARRÊT" in r.json()["message"]
    e = demo.get("/api/demo/etat").json()
    assert not e["lancee"] and not e["processus"]["voix"]["en_cours"]


def test_simulation_sans_faux_visiteur_dite_dans_l_ecran_demo(demo, fausses):
    """Corrections de la vague 6 (revue de l'interface, défaut 7) : en Simulation sans faux visiteur (scène d'essai),
    le robot partait seul à chaque visite (« Je ne vous vois pas derrière moi… ») et l'écran Démo ne disait rien."""
    from atelier.serveur.routes import demo as D
    _simulation(demo)
    demo.pont.recus.pop("/accueil/etat", None)
    abonnes = []
    demo.pont.infos_sujet = lambda sujet: {"publieurs": [], "abonnes": list(abonnes)} \
        if sujet == "/faux_visiteur/mode" else None
    r = demo.post("/api/demo/lancer", json={"lieu": "essai"})
    assert r.status_code == 200 and D.MESSAGE_SANS_FAUX_VISITEUR in r.json()["avertissements"]
    assert "Passants" in D.MESSAGE_SANS_FAUX_VISITEUR and "/faux_visiteur" not in D.MESSAGE_SANS_FAUX_VISITEUR
    assert D.MESSAGE_SANS_FAUX_VISITEUR in demo.get("/api/demo/etat").json()["avertissements"]
    abonnes.append("faux_visiteur")                 # le faux visiteur de la scène d'accompagnement écoute
    assert demo.get("/api/demo/etat").json()["avertissements"] == []
    abonnes.clear()
    demo.pont.actif = False                         # sans pont ROS 2 : on ne sait pas, on ne dit rien
    assert D.faux_visiteur_present(demo.etat) is None
    assert demo.get("/api/demo/etat").json()["avertissements"] == []
    demo.pont.actif = True
    demo.post("/api/demo/arreter")
    assert demo.get("/api/demo/etat").json()["avertissements"] == []     # démo arrêtée : plus rien à dire
    _simulation(demo, mode="repetition")            # en Réel ou en répétition, jamais ce message
    demo.pont.reperage = lambda: {"repere": True, "perime": False}
    r = demo.post("/api/demo/lancer", json={"lieu": "essai"})
    assert r.status_code == 200 and D.MESSAGE_SANS_FAUX_VISITEUR not in r.json()["avertissements"]
    assert D.MESSAGE_SANS_FAUX_VISITEUR not in demo.get("/api/demo/etat").json()["avertissements"]
    demo.post("/api/demo/arreter")


def test_lancer_en_repetition_et_voix_absente(demo, fausses, monkeypatch):
    _simulation(demo, mode="repetition")
    demo.pont.recus.pop("/accueil/etat", None)
    demo.pont.reperage = lambda: {"repere": True, "perime": False}
    monkeypatch.setenv("FAUX_VOIX_ECHEC", "1")
    r = demo.post("/api/demo/lancer", json={"lieu": "essai", "etage": "rdc"})
    assert r.status_code == 200 and r.json()["sortie_voix"] == "robot"
    assert "suivre_pont:=true" in _appels(fausses, "g1-accueil")[0]
    time.sleep(1.0)
    e = demo.get("/api/demo/etat").json()
    assert any("La voix ne tourne pas" in a for a in e["avertissements"])
    demo.post("/api/demo/arreter")


def test_commandes_de_l_atelier(demo):
    r = demo.post("/api/demo/commande", json={"action": "danser"})
    assert r.status_code == 400 and "inconnue" in r.json()["detail"]
    r = demo.post("/api/demo/commande", json={"action": "reprendre"})
    assert r.status_code == 409 and "pas en pause" in r.json()["detail"]
    r = demo.post("/api/demo/commande", json={"action": "pause"})
    assert r.status_code == 200 and r.json()["accepte"] and demo.pont.o.raison == "operateur"
    commande = [d for s, d in demo.pont.publies if s == "/accueil/commande"][-1]
    assert commande["source"] == "atelier" and commande["id"].startswith("atelier-")
    demo.pont.guide("attente", pose=(9.0, 13.0, 1.57))         # robot loin de l'accueil
    r = demo.post("/api/demo/commande", json={"action": "reprendre"})
    assert r.status_code == 409 and "Ramenez" in r.json()["detail"]
    r = demo.post("/api/demo/commande", json={"action": "ramener"})
    assert r.status_code == 200
    assert demo.pont.envoyes("/guide/aller")[-1] == {"cible": "principal", "accompagner": False, "retour": False,
                                                     "source": "accueil", "id": demo.pont.envoyes("/guide/aller")[-1]["id"]}
    assert demo.post("/api/demo/commande", json={"action": "remise_a_zero"}).status_code == 200
    assert demo.pont.o.etat()["statistiques"]["pauses"] == 0


def test_commande_sans_demo(tmp_path, monkeypatch):
    app, pont, _ = client_demo(tmp_path, monkeypatch, ros=False)
    with ouvrir_client(app) as c:
        r = c.post("/api/demo/commande", json={"action": "pause"})
        assert r.status_code == 409 and "ne tourne pas" in r.json()["detail"]
        pont.actif = False
        assert c.post("/api/demo/commande", json={"action": "pause"}).status_code == 503


def test_commande_sans_reponse(demo):
    demo.pont.o = None                         # la démo ne répond plus, son dernier état est encore frais
    t = time.monotonic()
    r = demo.post("/api/demo/commande", json={"action": "pause"})
    assert r.status_code == 503 and "pas répondu" in r.json()["detail"]
    assert 1.8 <= time.monotonic() - t <= 3.5


def test_demo_yaml_par_l_api(demo):
    r = demo.get("/api/lieux/essai/demo")
    assert r.status_code == 200 and r.json() == A.DEMO_DEFAUT
    r = demo.put("/api/lieux/essai/demo", json={"version": 1, "borne": {"code_operateur": "12"}})
    assert r.status_code == 422 and "demo.yaml" in r.json()["detail"] and r.json()["erreurs"]
    r = demo.put("/api/lieux/essai/demo", json={"version": 1, "voix": {"sortie": "pc"}})
    assert r.status_code == 422
    donnees = dict(A.DEMO_DEFAUT, delais={"choix_s": 30.0, "depart_s": 10.0, "entre_visiteurs_s": 5.0},
                   borne={"code_operateur": "4826", "langue": "fr", "titre": "Bienvenue au lycée !"})
    r = demo.put("/api/lieux/essai/demo", json=donnees)
    assert r.status_code == 200, r.text
    assert r.json()["enregistre"] == ["demo.yaml"] and r.json()["rapport"]["ok"]
    assert r.json()["donnees"]["borne"]["titre"] == "Bienvenue au lycée !"
    assert demo.get("/api/lieux/essai/demo").json()["delais"]["choix_s"] == 30.0
    assert "pas un mot de passe" in (demo.dossier / "demo.yaml").read_text(encoding="utf-8")
    assert demo.get("/api/lieux/nulle_part/demo").status_code == 404


def test_jamais_d_erreur_500(demo):
    for methode, chemin, corps in (("post", "/api/demo/lancer", {}), ("post", "/api/demo/lancer", {"lieu": 3}),
                                   ("post", "/api/demo/commande", {}), ("put", "/api/lieux/essai/demo", [1, 2]),
                                   ("put", "/api/lieux/essai/demo", {"version": 2}), ("post", "/api/demo/arreter", {}),
                                   ("get", "/api/lieux/../demo", None)):
        r = getattr(demo, methode)(chemin, **({"json": corps} if corps is not None else {}))
        assert r.status_code < 500 and (r.status_code < 400 or r.json()["detail"]), (chemin, r.text)
