"""Les routes de la borne visiteur (vague 6, section 13.5 du plan), sans ROS : agent Borne et orchestrateur.

Le serveur parle à la vraie machine d'états de la démo par un faux pont (test_borne_communs.PontDemo) : état de la
borne conforme au schéma etat_borne, salles proposées (ni l'accueil, ni une salle cachée), choix et ses refus
(404, 422, 409), anti-rebond (cinq appuis rapides : un seul choix), appui, annuler, suivi de la visite, son de la
sortie borne, code opérateur (403, 429, 409, jeton, 401), WebSocket /ws/borne, garde depuis le réseau, adresse de
la borne, textes en anglais.
"""
import time

import pytest

from atelier.lieu import accueil as A
from atelier.lieu import charger_salles, enregistrer_salles, valider_donnees

from .test_borne_communs import PRINCIPAL, client_demo, ouvrir_client


@pytest.fixture
def demo(tmp_path, monkeypatch):
    app, pont, dossier = client_demo(tmp_path, monkeypatch)
    with ouvrir_client(app) as c:
        c.pont, c.dossier = pont, dossier
        yield c


def _cacher(dossier, salle):
    salles = charger_salles(dossier)
    for s in salles:
        if s.id == salle:
            s.etiquettes = list(s.etiquettes or []) + ["hors_borne"]
    enregistrer_salles(dossier, salles)


def test_etat_sans_demo(tmp_path, monkeypatch):
    app, pont, _ = client_demo(tmp_path, monkeypatch, ros=False)
    with ouvrir_client(app) as c:
        e = c.get("/api/borne/etat").json()
        assert e["ecran"] == "hors_service" and e["texte"] == A.TEXTES_BORNE["hors_service"]
        assert e["detail"] and valider_donnees("etat_borne", e) == []
        for chemin in ("/api/borne/appui", "/api/borne/annuler"):
            r = c.post(chemin)
            assert r.status_code == 409 and "ne tourne pas" in r.json()["detail"], chemin
        r = c.post("/api/borne/choisir", json={"salle": "b204"})
        assert r.status_code == 409 and r.json()["raison"] == "demo_arretee"


def test_salles_de_la_borne(demo):
    _cacher(demo.dossier, "vie_scolaire")
    e = demo.get("/api/borne/etat").json()
    assert valider_donnees("etat_borne", e) == [], valider_donnees("etat_borne", e)
    assert e["ecran"] == "salles" and e["texte"] == "Bonjour ! Où voulez-vous aller ?"
    assert e["lieu"] == {"id": "essai", "nom": "Lycée démo"} and e["demo"]["etat"] == "attente"
    ids = [s["id"] for s in e["salles"]]
    assert ids == ["infirmerie", "cdi", "amphi", "b204"]           # ni l'accueil, ni la salle cachée
    cdi = next(s for s in e["salles"] if s["id"] == "cdi")
    assert cdi["nom_etage"] == "Rez-de-chaussée" and cdi["accessible"] and cdi["pictogramme"] is None
    assert e["operateur"] == {"possible": False, "actif": False} and e["langue"] == "fr"


def test_choix_refuses_et_accepte(demo):
    _cacher(demo.dossier, "vie_scolaire")
    attendus = {"nulle_part": (404, "salle_inconnue"), "vie_scolaire": (422, "salle_cachee"),
                "accueil": (422, "deja_la"), "B 204": (404, "salle_inconnue")}
    for salle, (code, raison) in attendus.items():
        r = demo.post("/api/borne/choisir", json={"salle": salle})
        assert r.status_code == code and r.json()["raison"] == raison and r.json()["detail"], (salle, r.text)
        time.sleep(A.ANTI_REBOND_S + 0.05)
    assert not [s for s, _ in demo.pont.publies if s == "/accueil/choix"]
    r = demo.post("/api/borne/choisir", json={"salle": "b204"})
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["accepte"] is True and corps["visite"] and corps["nom"] == "Salle B204"
    choix = [d for s, d in demo.pont.publies if s == "/accueil/choix"]
    assert len(choix) == 1 and choix[0]["source"] == "borne" and choix[0]["salle"] == "b204"
    assert demo.pont.envoyes("/guide/aller")[-1]["cible"] == "b204"
    demo.pont.rafraichir()
    e = demo.get("/api/borne/etat").json()
    assert e["ecran"] == "suivez_moi" and e["visite"]["salle"] == "b204"
    # pendant la visite : la borne est occupée (le guide, qui conduit, publie son état ; muet depuis 3 s, la démo
    # serait en pause : corrections de la vague 6, les pauses sont évaluées avant un choix)
    time.sleep(A.ANTI_REBOND_S + 0.05)
    demo.pont.guide("en_route", mission="visite", cible="b204", reste_m=18.0)
    r = demo.post("/api/borne/choisir", json={"salle": "cdi"})
    assert r.status_code == 409 and r.json()["raison"] == "occupe", r.text


def test_anti_rebond(demo):
    reponses = [demo.post("/api/borne/choisir", json={"salle": "b204"}) for _ in range(5)]
    assert [r.status_code for r in reponses] == [200] * 5
    assert [r.json().get("rebond", False) for r in reponses] == [False, True, True, True, True]
    assert len([s for s, _ in demo.pont.publies if s == "/accueil/choix"]) == 1
    appuis = [demo.post("/api/borne/appui") for _ in range(3)]
    assert len([d for s, d in demo.pont.publies if s == "/accueil/commande"]) == 1
    assert appuis[0].status_code == 409 and appuis[1].json()["rebond"]       # en visite : occupé


def _ensemble(app, demandes, client=("192.168.0.50", 40000)):
    """Les demandes [(chemin, corps)] envoyées ensemble par un même client (httpx.AsyncClient : elles se
    chevauchent vraiment dans la boucle du serveur, ce que TestClient ne fait pas)."""
    import asyncio
    import httpx

    async def tout():
        transport = httpx.ASGITransport(app=app, client=client)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000", timeout=30) as c:
            return await asyncio.gather(*[c.post(chemin, json=corps) for chemin, corps in demandes])
    return asyncio.run(tout())


def test_anti_rebond_de_demandes_simultanees(tmp_path, monkeypatch):
    """Corrections de la vague 6 (revue du code, défauts 4 et 10) : la réponse n'était retenue qu'après l'attente de
    la démo ; cinq choix envoyés ensemble (cinq doigts, ou un double appui pendant une latence du Wi-Fi) publiaient
    cinq /accueil/choix, et la démo répondait « occupé » à quatre d'entre eux. Avec une démo qui répond depuis un
    autre fil, comme le vrai pont."""
    from .test_borne_communs import PontLent, orchestrateur
    app, _, dossier = client_demo(tmp_path, monkeypatch)
    pont = PontLent(orchestrateur(dossier))
    app.state.atelier.pont = pont
    pont.guide("attente")
    reponses = _ensemble(app, [("/api/borne/choisir", {"salle": "b204"})] * 5)
    assert [r.status_code for r in reponses] == [200] * 5, [r.text for r in reponses]
    assert sorted(r.json().get("rebond", False) for r in reponses) == [False, True, True, True, True]
    assert len({r.json()["visite"] for r in reponses}) == 1
    assert len([s for s, _ in pont.publies if s == "/accueil/choix"]) == 1
    assert pont.o.etat()["statistiques"]["refus_occupe"] == 0
    # un autre client n'est pas confondu avec le premier : sa demande part (et la démo, occupée, la refuse)
    autre = _ensemble(app, [("/api/borne/choisir", {"salle": "cdi"})], client=("192.168.0.51", 40000))
    assert autre[0].status_code == 409 and len([s for s, _ in pont.publies if s == "/accueil/choix"]) == 2
    # trois appuis ensemble : une seule commande
    time.sleep(A.ANTI_REBOND_S + 0.05)
    appuis = _ensemble(app, [("/api/borne/appui", None)] * 3)
    assert len({r.status_code for r in appuis}) == 1
    assert len([s for s, _ in pont.publies if s == "/accueil/commande"]) == 1
    # la démo ne répond pas : une seule publication, la même erreur pour toutes, et la demande suivante repart
    time.sleep(A.ANTI_REBOND_S + 0.05)
    pont.sans_reponse = True
    muets = _ensemble(app, [("/api/borne/annuler", None)] * 3)
    assert [r.status_code for r in muets] == [503] * 3 and "pas répondu" in muets[0].json()["detail"]
    assert len([d for s, d in pont.publies if s == "/accueil/commande"]) == 2
    assert _ensemble(app, [("/api/borne/annuler", None)])[0].status_code == 503
    assert len([d for s, d in pont.publies if s == "/accueil/commande"]) == 3


def test_appui_annuler_et_suivi(demo):
    r = demo.post("/api/borne/appui")
    assert r.status_code == 200 and r.json()["accepte"]
    demo.pont.rafraichir()
    assert demo.pont.o.etat_courant == "salutation"
    time.sleep(A.ANTI_REBOND_S + 0.05)
    assert demo.post("/api/borne/annuler").status_code == 200
    assert demo.pont.o.etat_courant == "attente"
    # une visite suivie par la borne : suivez_moi (distance), arrivée, retour, salles
    assert demo.post("/api/borne/choisir", json={"salle": "cdi"}).status_code == 200
    demo.pont.guide("en_route", mission="visite", cible="cdi", reste_m=14.4, pose=(6.0, 10.0, 0.0))
    e = demo.get("/api/borne/etat").json()
    assert e["ecran"] == "suivez_moi" and e["detail"] == "Encore 14 m jusqu'à CDI."
    demo.pont.guide("arrive", mission="visite", cible="cdi", reste_m=0.0, actif=True, pose=(23.0, 7.0, -1.57))
    e = demo.get("/api/borne/etat").json()
    assert e["ecran"] == "arrivee" and e["texte"] == "Nous sommes arrivés." and e["detail"] == "Voici CDI."
    demo.pont.guide("retour", mission="retour", cible="accueil", pose=(20.0, 7.0, 3.1))
    assert demo.get("/api/borne/etat").json()["ecran"] == "retour"
    demo.pont.guide("attente")
    e = demo.get("/api/borne/etat").json()
    assert e["ecran"] == "salles" and e["visite"] is None and valider_donnees("etat_borne", e) == []


def test_pause_et_occupe_a_la_borne(demo):
    demo.pont.guide("en_route", mission="visite", cible="amphi", pose=(4.0, 10.0, 0.0))   # « Y aller » de l'Atelier
    e = demo.get("/api/borne/etat").json()
    assert e["ecran"] == "occupe" and e["texte"] == A.TEXTES_BORNE["occupe"]
    demo.pont.recevoir("/mouvement/maitre", {})
    demo.pont._garder(demo.pont.o.entrer("/mouvement/maitre", {"maitre": "pilotage"}))
    demo.pont.rafraichir()
    e = demo.get("/api/borne/etat").json()
    assert e["ecran"] == "pause" and e["texte"] == "Je fais une petite pause."
    r = demo.post("/api/borne/choisir", json={"salle": "b204"})
    assert r.status_code == 409 and r.json()["raison"] == "pause"


def test_son_de_la_sortie_borne(demo):
    assert demo.get("/api/borne/etat").json()["son"] is None
    demo.pont.recevoir("/voix/son", {"version": 1, "id": "s-20261109-101010-0001", "texte": "Bonjour !",
                                     "duree_s": 1.2, "url": "/api/voix/son/s-20261109-101010-0001"})
    son = demo.get("/api/borne/etat").json()["son"]
    assert son == {"id": "s-20261109-101010-0001", "texte": "Bonjour !", "duree_s": 1.2,
                   "url": "/api/voix/son/s-20261109-101010-0001"}


def test_code_operateur(demo):
    r = demo.post("/api/borne/operateur", json={"code": "1234"})
    assert r.status_code == 409 and "code opérateur" in r.json()["detail"]
    A.enregistrer_demo(demo.dossier, {"version": 1, "borne": {"code_operateur": "4826"}})
    assert demo.get("/api/borne/etat").json()["operateur"] == {"possible": True, "actif": False}
    assert demo.post("/api/borne/operateur/pause").status_code == 401
    codes = [demo.post("/api/borne/operateur", json={"code": "0000"}).status_code for _ in range(6)]
    assert codes == [403, 403, 403, 403, 429, 429]
    assert demo.post("/api/borne/operateur", json={"code": "4826"}).status_code == 429    # bloqué, même le bon


def test_jeton_operateur(demo):
    A.enregistrer_demo(demo.dossier, {"version": 1, "borne": {"code_operateur": "4826"}})
    assert demo.post("/api/borne/operateur", json={"code": "4825"}).status_code == 403
    r = demo.post("/api/borne/operateur", json={"code": "4826"})
    assert r.status_code == 200 and r.json()["expire_s"] == A.DUREE_JETON_OPERATEUR_S
    jeton = {A.ENTETE_JETON_BORNE: r.json()["jeton"]}
    e = demo.get("/api/borne/etat", headers=jeton).json()
    assert e["operateur"] == {"possible": True, "actif": True} and valider_donnees("etat_borne", e) == []
    assert e["mode_operateur"] == {"message": "Le robot attend un visiteur à l'accueil.", "actions": ["pause"]}
    assert "mode_operateur" not in demo.get("/api/borne/etat").json()
    assert demo.post("/api/borne/operateur/danser", headers=jeton).status_code == 404
    assert demo.post("/api/borne/operateur/debloquer", headers=jeton).status_code == 404
    r = demo.post("/api/borne/operateur/pause", headers=jeton)
    assert r.status_code == 200 and r.json()["accepte"] and demo.pont.o.raison == "operateur"
    commande = [d for s, d in demo.pont.publies if s == "/accueil/commande"][-1]
    assert commande["action"] == "pause" and commande["source"] == "operateur"
    r = demo.post("/api/borne/operateur/pause", headers=jeton)
    assert r.status_code == 409 and "déjà en pause" in r.json()["detail"]
    demo.pont.guide("attente")
    assert demo.post("/api/borne/operateur/reprendre", headers=jeton).status_code == 200
    assert demo.pont.o.etat_courant == "attente"
    r = demo.post("/api/borne/operateur/ramener", headers=jeton)
    assert r.status_code == 409 and "Ramener" not in r.json()["detail"]     # pas en pause : refusé


def test_jeton_d_un_autre_client(tmp_path, monkeypatch):
    app, pont, dossier = client_demo(tmp_path, monkeypatch)
    A.enregistrer_demo(dossier, {"version": 1, "borne": {"code_operateur": "4826"}})
    with ouvrir_client(app) as c:
        jeton = c.post("/api/borne/operateur", json={"code": "4826"}).json()["jeton"]
    with ouvrir_client(app, client=("192.168.1.50", 40000)) as autre:
        r = autre.post("/api/borne/operateur/pause", headers={A.ENTETE_JETON_BORNE: jeton})
        assert r.status_code == 401


def test_websocket_de_la_borne(demo):
    debut = time.monotonic()
    with demo.websocket_connect("/ws/borne") as ws:
        messages = [ws.receive_json() for _ in range(5)]
    duree = time.monotonic() - debut
    assert all(valider_donnees("etat_borne", m) == [] for m in messages)
    assert messages[0]["ecran"] == "salles" and duree < 2.5


def test_textes_en_anglais(demo):
    A.enregistrer_demo(demo.dossier, {"version": 1, "borne": {"langue": "en"}})
    e = demo.get("/api/borne/etat").json()
    assert e["langue"] == "en" and e["texte"] == "Hello! Where would you like to go?"
    assert e["detail"] == "Touch a room: I will take you there."
    A.enregistrer_demo(demo.dossier, {"version": 1, "borne": {"langue": "en", "titre": "Welcome to the lab!"}})
    assert demo.get("/api/borne/etat").json()["texte"] == "Welcome to the lab!"


def test_garde_de_la_borne_depuis_le_reseau(tmp_path, monkeypatch):
    app_essai = client_demo(tmp_path, monkeypatch)[0]
    monkeypatch.setenv("ATELIER_HOTE", "0.0.0.0")
    from atelier.serveur.main import creer_app
    app = creer_app(ros=False)
    app.state.atelier.pont = app_essai.state.atelier.pont
    with ouvrir_client(app, client=("192.168.1.20", 50000)) as c:
        assert c.get("/borne").status_code == 200
        assert c.get("/api/borne/etat").json()["ecran"] == "salles"
        assert c.get("/css/borne.css").status_code == 200 and c.get("/js/borne/borne.js").status_code == 200
        for methode, chemin in (("get", "/"), ("get", "/api/lieux"), ("post", "/api/arret/debloquer"),
                                ("post", "/api/guide/aller"), ("post", "/api/demo/commande"),
                                ("put", "/api/lieux/essai/demo"), ("get", "/js/app.js")):
            r = getattr(c, methode)(chemin)
            assert r.status_code == 403 and "seule la borne" in r.json()["detail"], chemin
        from starlette.websockets import WebSocketDisconnect
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect("/ws/etat") as ws:
                ws.receive_json()
        with c.websocket_connect("/ws/borne") as ws:
            assert ws.receive_json()["ecran"] == "salles"


def test_garde_de_la_borne_sans_detour_par_les_points(tmp_path, monkeypatch):
    """Corrections de la vague 6 (revue du code, défauts 3 et 10) : « .. » dans le chemin ne sort plus de la borne.
    httpx (donc TestClient) normalise lui-même « .. » avant l'envoi et ne pourrait pas montrer le défaut : les
    demandes partent ici en scope ASGI brut, le chemin tel qu'uvicorn le donne (déjà décodé : %2e%2e y est « .. »)."""
    import asyncio
    monkeypatch.setenv("ATELIER_HOTE", "0.0.0.0")
    monkeypatch.setenv("ATELIER_LIEUX", str(tmp_path))
    monkeypatch.delenv("ATELIER_DISTANT", raising=False)
    from atelier.serveur.main import creer_app
    app = creer_app(ros=False)

    async def demander(chemin):
        recu = []

        async def recevoir():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def envoyer(message):
            recu.append(message)
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET", "scheme": "http",
                 "path": chemin, "raw_path": chemin.encode("latin-1"), "root_path": "", "query_string": b"",
                 "headers": [(b"host", b"192.168.0.12:8000")], "client": ("192.168.1.20", 50000),
                 "server": ("192.168.0.12", 8000)}
        await app(scope, recevoir, envoyer)
        debut = next(m for m in recu if m["type"] == "http.response.start")
        corps = b"".join(m.get("body", b"") for m in recu if m["type"] == "http.response.body")
        return debut["status"], corps

    for chemin in ("/js/borne/../coque/coque.js", "/js/borne/../../index.html", "/api/borne/../../js/app.js",
                   "/api/voix/son/../../../js/coque/arret.js", "/js/borne//../app.js", "/css/../index.html"):
        statut, corps = asyncio.run(demander(chemin))
        assert statut == 403 and "seule la borne" in corps.decode("utf-8"), (chemin, statut, corps[:80])
    statut, corps = asyncio.run(demander("/js/borne/borne.js"))
    assert statut == 200 and b"<!doctype" not in corps[:50]


def test_adresse_de_la_borne(demo, monkeypatch):
    r = demo.get("/api/borne/adresse").json()
    assert r["ecoute_reseau"] is False and r["adresses"] == [] and "--hote 0.0.0.0" in r["message"]
    monkeypatch.setenv("ATELIER_HOTE", "192.168.0.12")
    monkeypatch.setenv("ATELIER_PORT", "8143")
    r = demo.get("/api/borne/adresse").json()
    assert r == {"adresses": ["http://192.168.0.12:8143/borne"], "ecoute_reseau": True, "port": 8143,
                 "locale": "http://127.0.0.1:8143/borne", "message": r["message"]}
    monkeypatch.setenv("ATELIER_HOTE", "0.0.0.0")
    r = demo.get("/api/borne/adresse").json()
    assert r["ecoute_reseau"] is True
    for a in r["adresses"]:
        assert a.startswith("http://") and a.endswith(":8143/borne")
        assert "127.0.0.1" not in a and "192.168.123." not in a


def test_salle_d_un_autre_etage(demo):
    from atelier.lieu import charger_fiche, enregistrer_fiche
    fiche = charger_fiche(demo.dossier)
    from atelier.lieu.modeles import Etage
    fiche.etages.append(Etage(id="etage1", nom="Premier étage", source_carte="monde"))
    enregistrer_fiche(fiche, demo.dossier)
    salles = charger_salles(demo.dossier)
    s = salles[1]
    s.etage = "etage1"
    enregistrer_salles(demo.dossier, salles)
    e = demo.get("/api/borne/etat").json()
    autre = next(x for x in e["salles"] if x["id"] == s.id)
    assert autre["accessible"] is False and autre["nom_etage"] == "Premier étage"
    r = demo.post("/api/borne/choisir", json={"salle": s.id})
    assert r.status_code == 422 and r.json()["raison"] == "autre_etage"


def test_jamais_d_erreur_500(demo):
    for methode, chemin, corps in (("post", "/api/borne/choisir", {}), ("post", "/api/borne/choisir", {"salle": 3}),
                                   ("post", "/api/borne/operateur", {"code": None}), ("post", "/api/borne/appui", None),
                                   ("post", "/api/borne/operateur/pause", None), ("get", "/api/borne/adresse", None)):
        r = getattr(demo, methode)(chemin, **({"json": corps} if corps is not None else {}))
        assert r.status_code < 500 and (r.status_code < 400 or r.json()["detail"]), (chemin, r.text)
    assert PRINCIPAL
