"""Le journal de la séance face à un client qui insiste (corrections de la vague 6, revue du code, défaut 9).

Une séance ouverte et l'Atelier qui écoute le réseau : 3 000 demandes refusées par la garde de la borne, d'une même
machine du Wi-Fi, faisaient 3 000 lignes de actions.jsonl (476 octets chacune : 3 Go par heure), et la garde des
origines écrivait une alerte par demande refusée dans serveur.log. Maintenant : la première demande refusée de chaque
minute, puis une ligne qui dit combien ont suivi ; une alerte au plus toutes les 10 s.

  ~/robot-g1/.venv-projet/bin/python -m pytest ~/robot-g1/atelier/tests/test_corrections_journal_inonde.py -v
"""
import asyncio
import json
import logging

import httpx

from atelier.lieu import valider_donnees
from atelier.serveur.main import CLE_GARDE, GardeOrigine, creer_app


def test_demandes_refusees_par_la_garde_resumees(tmp_path, monkeypatch):
    monkeypatch.setenv("ATELIER_HOTE", "0.0.0.0")                 # la garde de la borne est active
    monkeypatch.delenv("ATELIER_DISTANT", raising=False)
    monkeypatch.setenv("ATELIER_SEANCES", str(tmp_path / "seances"))
    monkeypatch.setenv("ATELIER_INTERFACE_ROBOT", "interface_absente_v6")
    app = creer_app(ros=False)
    seance = app.state.atelier.seance
    m = seance.demarrer("repetition", ouverture="manuel")

    async def inonder():
        transport = httpx.ASGITransport(app=app, client=("192.168.0.50", 40000))
        async with httpx.AsyncClient(transport=transport, base_url="http://192.168.0.12:8000") as c:
            statuts = [(await c.post("/api/arret/debloquer", content="x" * 4000)).status_code for _ in range(300)]
            statuts.append((await c.post("/api/borne/appui")).status_code)     # permise : notée telle quelle
        return statuts
    statuts = asyncio.run(inonder())
    assert statuts[:300] == [403] * 300 and statuts[300] != 403
    seance.arreter()
    lignes = [json.loads(x) for x in (tmp_path / "seances" / m["id"] / "actions.jsonl").read_text(
        encoding="utf-8").splitlines()]
    assert all(valider_donnees("action_seance", x) == [] for x in lignes)
    refusees = [x for x in lignes if x["chemin"] == "/api/arret/debloquer"]
    # la première demande refusée, puis le résumé des 299 autres (même client, même minute ; ou deux minutes si
    # l'essai passe le changement de minute : jamais plus de quatre lignes)
    assert 2 <= len(refusees) <= 4 and refusees[0]["statut"] == 403 and refusees[0]["client"] == "distant"
    assert sum(x.get("resume", {}).get("nombre", 0) for x in refusees) + len(
        [x for x in refusees if "resume" not in x]) == 300
    assert any(x["chemin"] == "/api/borne/appui" for x in lignes)
    assert lignes[-1]["texte"] == "Terminer la séance"


class _Horloge:
    t = 100.0

    def __call__(self):
        return self.t


class _Recueil(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def test_alertes_de_la_garde_des_origines_espacees():
    async def application(scope, receive, send):
        raise AssertionError("une demande refusée ne doit pas atteindre l'Atelier")

    envoyes = []

    async def envoyer(message):
        envoyes.append(message)

    horloge = _Horloge()
    garde = GardeOrigine(application, horloge=horloge)

    def demande():
        scope = {"type": "http", "method": "POST", "path": "/api/voix/essayer",
                 "headers": [(b"host", b"127.0.0.1:8000"), (b"origin", b"https://site-quelconque.example"),
                             (b"sec-fetch-site", b"cross-site")]}
        asyncio.run(garde(scope, None, envoyer))
        return scope
    recueil, journal = _Recueil(), logging.getLogger("atelier.serveur")
    journal.addHandler(recueil)
    try:
        scopes = [demande() for _ in range(50)]
        horloge.t += 11.0
        demande()
    finally:
        journal.removeHandler(recueil)
    alertes = [m for m in recueil.messages if "garde des origines" in m]
    assert len(alertes) == 2 and alertes[1].endswith("49 autres refusées avant elle, sans alerte"), alertes
    assert all(s[CLE_GARDE] == "origine" for s in scopes)          # la boîte noire les résumera
    assert [m["status"] for m in envoyes if m["type"] == "http.response.start"] == [403] * 51
