"""Tests de l'API du comportement du guide (vague 4, section 11.4 du plan), sans ROS 2 ni robot.

  - GET/PUT /api/lieux/{id}/guide : la section guide de lieu.yaml (réglages, refus en français) ;
  - POST /api/guide/aller : l'id simple d'avant, ou le JSON {cible, accompagner, retour, source} ;
    la cible « principal » ; l'avertissement quand le robot est piloté à la main ;
  - GET /api/guide/evenements, POST /api/guide/visiteur (refus hors simulation) ;
  - le panneau de l'onglet Simulation (js/panneaux/guide.js) et sa feuille de style.
Le pont ROS 2 du serveur est remplacé par un faux qui garde ce qui est publié.
"""
import json

import pytest
import yaml

from atelier import RACINE
from atelier.lieu import charger_fiche
from atelier.lieu.comportement import DELAIS_GUIDE, lire_demande_aller

from .test_serveur_communs import client, faux_bin, journaux, lieux  # noqa: F401


class FauxPont:
    """Remplace les méthodes du pont ROS 2 utilisées par les routes du guide."""

    def __init__(self, pont, maitre=None, evenements=()):
        self.publies = []
        pont.actif = True
        pont.erreur = None
        pont.aller = self.aller
        pont.dernier = lambda sujet: maitre if sujet == "/mouvement/maitre" else None
        pont.historique = lambda sujet: list(evenements) if sujet == "/guide/evenement" else []

    def aller(self, message):
        self.publies.append(message)
        return 1


def _erreur(r, statut):
    assert r.status_code == statut, (r.status_code, r.text)
    d = r.json()
    assert isinstance(d["detail"], str) and d["detail"]
    return d


def test_lire_et_ecrire_les_reglages(client, lieux):
    r = client.get("/api/lieux/demo/guide")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["guide"] == {} and d["reglages"] == DELAIS_GUIDE and d["defauts"] == DELAIS_GUIDE
    assert d["principal"] == {"salle": "accueil", "nom": "Accueil", "etage": "rdc"}
    r = client.put("/api/lieux/demo/guide", json={"delai_avant_retour_s": 5, "retour_auto": False,
                                                  "delai_perdu_s": None})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["enregistre"] == ["lieu.yaml"] and d["guide"] == {"delai_avant_retour_s": 5, "retour_auto": False}
    assert d["reglages"]["delai_avant_retour_s"] == 5 and d["reglages"]["delai_perdu_s"] == 30.0
    assert d["rapport"]["ok"] is True
    brut = yaml.safe_load((lieux / "demo" / "lieu.yaml").read_text(encoding="utf-8"))
    assert brut["guide"] == {"delai_avant_retour_s": 5, "retour_auto": False}
    assert charger_fiche(lieux / "demo").guide == {"delai_avant_retour_s": 5, "retour_auto": False}
    # {} retire la section : le fichier redevient celui d'avant la vague 4
    assert client.put("/api/lieux/demo/guide", json={}).json()["guide"] == {}
    assert "guide" not in yaml.safe_load((lieux / "demo" / "lieu.yaml").read_text(encoding="utf-8"))


@pytest.mark.parametrize("corps, mot", [
    ({"delai_inconnu": 3}, "réglage inconnu"),
    ({"delai_avant_retour_s": -1}, "delai_avant_retour_s"),
    ({"distance_ralentir_m": 3.0, "distance_attendre_m": 2.5}, "distance_attendre_m"),
    ({"retour_auto": "oui"}, "retour_auto"),
    ([1, 2], "objet JSON"),
])
def test_reglages_refuses(client, lieux, corps, mot):
    avant = (lieux / "demo" / "lieu.yaml").read_bytes()
    d = _erreur(client.put("/api/lieux/demo/guide", json=corps), 422)
    assert mot in d["detail"] + " ".join(d.get("erreurs", []))
    assert (lieux / "demo" / "lieu.yaml").read_bytes() == avant


def test_lieu_inconnu(client):
    _erreur(client.get("/api/lieux/nulle_part/guide"), 404)
    _erreur(client.put("/api/lieux/Lieu%20faux/guide", json={}), 400)


def test_aller_id_simple_ou_json(client):
    pont = FauxPont(client.app.state.atelier.pont)
    r = client.post("/api/guide/aller", json={"cible": "b204"})
    assert r.status_code == 200, r.text
    assert pont.publies[-1] == "b204" and "demande" not in r.json()
    r = client.post("/api/guide/aller", json={"cible": "b204", "accompagner": True, "retour": False})
    assert r.status_code == 200, r.text
    demande = json.loads(pont.publies[-1])
    assert demande == {"cible": "b204", "accompagner": True, "retour": False, "source": "atelier"}
    assert lire_demande_aller(pont.publies[-1]) == {"cible": "b204", "accompagner": True, "retour": False,
                                                    "source": "atelier"}
    assert r.json()["demande"] == demande
    client.post("/api/guide/aller", json={"cible": "principal", "retour": True})
    assert json.loads(pont.publies[-1]) == {"cible": "principal", "accompagner": False, "retour": True,
                                            "source": "atelier"}
    _erreur(client.post("/api/guide/aller", json={"cible": "salle b204", "accompagner": True}), 400)
    _erreur(client.post("/api/guide/aller", json={"cible": "b204", "accompagner": "beaucoup"}), 422)


def test_aller_pendant_le_pilotage_avertit(client):
    maitre = {"version": 1, "maitre": "pilotage", "par": "atelier", "depuis": "2026-10-26T10:00:00+01:00",
              "message": "Piloté à la main"}
    pont = FauxPont(client.app.state.atelier.pont, maitre=maitre)
    r = client.post("/api/guide/aller", json={"cible": "b204"})
    assert r.status_code == 200 and "piloté à la main" in r.json()["avertissement"]
    assert pont.publies == ["b204"]          # le guide refusera lui-même (echec, événement pilotage)


def test_evenements_et_faux_visiteur(client):
    assert client.get("/api/guide/evenements").json()["evenements"] == []
    evenements = [{"version": 1, "code": "depart", "texte": "Suivez-moi, je vous emmène à Salle B204."}]
    FauxPont(client.app.state.atelier.pont, evenements=evenements)
    d = client.get("/api/guide/evenements").json()
    assert d["evenements"] == evenements and d["codes"]["arrivee"].startswith("Nous sommes arrivés")
    assert "inconnu" in _erreur(client.post("/api/guide/visiteur", json={"mode": "danser"}), 400)["detail"]
    assert "simulation" in _erreur(client.post("/api/guide/visiteur", json={"mode": "suivre"}), 409)["detail"]


def test_panneau_de_l_onglet_simulation():
    web = RACINE / "atelier" / "web"
    js = (web / "js" / "panneaux" / "guide.js").read_text(encoding="utf-8")
    for route in ("/api/guide/aller", "/api/guide/visiteur", "/guide'"):
        assert route in js
    for etat in ("retour", "attente_passage", "attente_visiteur", "perdu"):
        assert f"  {etat}: '" in js
    assert "export function monter(" in js
    css = (web / "css" / "guide.css").read_text(encoding="utf-8")
    assert ".liste-evenements" in css


def test_la_simulation_part_du_point_principal(client, lieux, faux_bin):
    """Un depart_robot qui diffère du point principal y est remis avant le lancement (11.2)."""
    from atelier.lieu import charger_monde, enregistrer_monde
    from atelier.lieu.modeles import Pose
    assert client.post("/api/lieux/demo/etages/rdc/monde/generer").status_code == 200
    monde = charger_monde(lieux / "demo", "rdc")
    monde.depart_robot = Pose(5.0, 13.0, 1.0)
    enregistrer_monde(lieux / "demo", "rdc", monde)
    r = client.post("/api/simulation/demarrer", json={"lieu": "demo", "etage": "rdc"})
    assert r.status_code == 200, r.text
    d = charger_monde(lieux / "demo", "rdc").depart_robot
    assert (d.x, d.y, d.theta) == (2.5, 10.0, 0.0)
    assert any("point principal" in a for a in r.json()["simulation"]["avertissements"])
    client.post("/api/simulation/arreter")
