#!/usr/bin/env python3
"""Outils du critère 40, la voix du robot contre le faux G1 (section 13.9 du plan, critère 40 ; section 13.6).

  outils_voix_e2e.py critere-40 --api URL --lieu ID --sons DOSSIER
      le faux G1 seul (ros2 run g1_jumeau jumeau) et l'Atelier tournent dans le domaine du test ; la voix est
      lancée par l'Atelier (POST /api/voix/demarrer, sortie robot, g1-voix). On vérifie :
        - au départ, 1006 {"volume": 70} puis 1005 ; /robot/dire « Bonjour, suivez-moi ! » : des 1003 conformes
          (erreurs_requete_voix), un seul stream_id, des morceaux de 96 000 octets au plus et pairs, une durée à
          5 % près de celle du WAV de Piper de la phrase (gardé par le nœud) rééchantillonné à 16 kHz, et le
          même son reçu par le faux G1 (octets, aucun écart, aucun trou) ;
        - trois phrases de suite : dites dans l'ordre, jamais deux flux en même temps (chaque flux commence
          après la fin du précédent ; le faux G1 ne voit aucun flux mêlé) ; une phrase haute : 1004 puis la
          nouvelle ; une phrase de sécurité : 1004, puis elle seule (les deux phrases en attente jamais dites) ;
        - /voix/commande volume 60 → 1006 {"volume": 60} ; taire → 1004 ; par l'Atelier :
          POST /api/voix/commande volume 65 → 1006 {"volume": 65}, POST /api/voix/essayer → la phrase dite ;
        - sortie robot_tts → 1001 {"index", "speaker_id", "text"} ; sortie borne → un WAV dans
          ATELIER_VOIX_SONS, /voix/son conforme, GET /api/voix/son/<id> en audio/wav, aucun 1003 ;
        - un 1003 de 3 octets envoyé par le test : le faux G1 le compte comme écart (réponse 3204) ; panne muet
          du faux G1 : /voix/etat dit que le robot ne répond plus, le nœud tourne toujours, puis répond de
          nouveau à la fin de la panne ;
        - /voix/etat conforme tout du long, aucune requête hors de 1001, 1003, 1004, 1005, 1006 ;
          POST /api/voix/arreter : plus de nœud voix.
  outils_voix_e2e.py restes --sons DOSSIER
      code 1 s'il reste un nœud voix lancé avec ce dossier de sons (ATELIER_VOIX_SONS).

Code de sortie : 0 réussi, 1 échoué. Jamais de son ni de requête vers le vrai robot : le domaine ROS du test, le
faux G1 seul (G1_SLAM_FAUX=1 de commun.sh).
"""
import argparse
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ICI = Path(__file__).resolve().parent
RACINE = ICI.parent
sys.path.insert(0, str(RACINE))

PREFIXE = "critère 40"
APIS = (1001, 1003, 1004, 1005, 1006)


class Echec(Exception):
    pass


def dire(texte):
    print(f"[{PREFIXE}] {texte}", flush=True)


def verifier(condition, message):
    if not condition:
        raise Echec(message)


def appel(api, methode, chemin, corps=None, delai=30, brut=False):
    """(code HTTP, JSON ou (en-têtes, octets) si brut) d'un appel à l'API de l'Atelier."""
    donnees = None if corps is None else json.dumps(corps).encode()
    r = urllib.request.Request(api + chemin, data=donnees, method=methode,
                               headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=delai) as reponse:
            contenu = reponse.read()
            if brut:
                return reponse.status, (dict(reponse.headers), contenu)
            return reponse.status, json.loads(contenu or b"null")
    except urllib.error.HTTPError as e:
        texte = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(texte)
        except ValueError:
            return e.code, {"detail": texte}


def attendre(condition, delai, message, pas=0.05):
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        valeur = condition()
        if valeur:
            return valeur
        time.sleep(pas)
    raise Echec(message)


class Observateur:
    """Un nœud du test : les requêtes du service voice (et leurs réponses), /voix/etat (validé), /voix/son,
    /g1_jumeau/etat ; il publie /robot/dire, /voix/commande, /g1_jumeau/panne et une requête faite exprès."""

    def __init__(self):
        import rclpy
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.qos import QoSProfile, ReliabilityPolicy
        from rclpy.signals import SignalHandlerOptions
        from std_msgs.msg import String
        from unitree_api.msg import Request, Response
        from atelier.lieu.validation import valider_donnees
        self.valider = valider_donnees
        rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
        self.rclpy = rclpy
        self.noeud = rclpy.create_node("e2e_voix")
        self.String, self.Request = String, Request
        fiable = QoSProfile(depth=100, reliability=ReliabilityPolicy.RELIABLE)
        au_mieux = QoSProfile(depth=100, reliability=ReliabilityPolicy.BEST_EFFORT)
        self.verrou = threading.Lock()
        self.requetes, self.reponses, self.etats, self.sons = [], {}, [], []
        self.non_conformes, self.jumeau = [], None
        n = self.noeud
        n.create_subscription(Request, "/api/voice/request", self._requete, fiable)
        n.create_subscription(Response, "/api/voice/response", self._reponse, au_mieux)
        n.create_subscription(String, "/voix/etat", self._etat, 100)
        n.create_subscription(String, "/voix/son", self._son, 100)
        n.create_subscription(String, "/g1_jumeau/etat", self._jumeau, 10)
        self.pub_dire = n.create_publisher(String, "/robot/dire", 10)
        self.pub_commande = n.create_publisher(String, "/voix/commande", 10)
        self.pub_panne = n.create_publisher(String, "/g1_jumeau/panne",
                                            QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE))
        self.pub_requete = n.create_publisher(Request, "/api/voice/request", fiable)
        self.executeur = SingleThreadedExecutor()
        self.executeur.add_node(n)
        self.fil = threading.Thread(target=self.executeur.spin, daemon=True)
        self.fil.start()

    # ---------------------------------------------------- réception

    def _requete(self, m):
        t = time.monotonic()
        binaire = bytes(m.binary)
        from atelier.lieu import voix as V
        erreurs = V.erreurs_requete_voix(m.header.identity.api_id, m.parameter, binaire)
        try:
            parametre = json.loads(m.parameter)
        except ValueError:
            parametre = None
        with self.verrou:
            self.requetes.append({"t": t, "api_id": m.header.identity.api_id, "id": m.header.identity.id,
                                  "parametre": parametre, "texte": m.parameter, "octets": len(binaire),
                                  "erreurs": erreurs})

    def _reponse(self, m):
        with self.verrou:
            self.reponses[m.header.identity.id] = (time.monotonic(), m.header.status.code, m.data)

    def _etat(self, m):
        try:
            d = json.loads(m.data)
        except ValueError:
            d = None
        erreurs = self.valider("etat_voix", d) if isinstance(d, dict) else ["pas du JSON"]
        with self.verrou:
            if erreurs:
                self.non_conformes.append(("etat_voix", erreurs, m.data[:300]))
            else:
                self.etats.append((time.monotonic(), d))
                del self.etats[:-500]

    def _son(self, m):
        d = json.loads(m.data)
        erreurs = self.valider("son_voix", d)
        with self.verrou:
            if erreurs:
                self.non_conformes.append(("son_voix", erreurs, m.data[:300]))
            self.sons.append(d)

    def _jumeau(self, m):
        try:
            self.jumeau = json.loads(m.data)
        except ValueError:
            pass

    # ---------------------------------------------------- outils

    def dire(self, texte, ident, **champs):
        message = dict({"version": 1, "id": ident, "texte": texte, "source": "guide"}, **champs)
        self.pub_dire.publish(self.String(data=json.dumps(message, ensure_ascii=False)))

    def commander(self, **champs):
        self.pub_commande.publish(self.String(data=json.dumps(dict({"version": 1}, **champs))))

    def panne(self, quoi):
        self.pub_panne.publish(self.String(data=quoi))

    def envoyer_requete(self, identifiant, api_id, parametre, binaire):
        from array import array
        r = self.Request()
        r.header.identity.id = identifiant
        r.header.identity.api_id = api_id
        r.parameter = parametre
        r.binary = array("B", binaire)
        self.pub_requete.publish(r)

    def rang(self):
        with self.verrou:
            return len(self.requetes)

    def depuis(self, rang=0):
        with self.verrou:
            return list(self.requetes[rang:])

    def etat(self):
        with self.verrou:
            return self.etats[-1][1] if self.etats else None

    def voix_jumeau(self):
        return (self.jumeau or {}).get("robot", {}).get("voix")

    def fermer(self):
        self.executeur.shutdown(timeout_sec=1.0)
        self.fil.join(timeout=3.0)
        self.noeud.destroy_node()
        self.rclpy.try_shutdown()


def flux(requetes):
    """[(stream_id, instant du premier morceau, octets)] des 1003, dans l'ordre de départ."""
    ordre = {}
    for r in requetes:
        if r["api_id"] == 1003 and isinstance(r["parametre"], dict):
            sid = r["parametre"].get("stream_id")
            if sid not in ordre:
                ordre[sid] = [sid, r["t"], 0]
            ordre[sid][2] += r["octets"]
    return [tuple(v) for v in ordre.values()]


def attendre_dite(obs, ident, delai=30):
    """Attend que la phrase ident ait fini (historique de /voix/etat) ; rend sa fin (dite, interrompue…)."""
    def fini():
        e = obs.etat() or {}
        for h in e.get("historique") or []:
            if h.get("id") == ident:
                return h.get("fin")
        return None
    return attendre(fini, delai, f"la phrase « {ident} » n'a pas fini en {delai} s (historique de /voix/etat)")


def attendre_depart(obs, ident, rang=0, delai=20):
    return attendre(lambda: any(f[0] == ident for f in flux(obs.depuis(rang))), delai,
                    f"la phrase « {ident} » n'est pas partie vers le robot en {delai} s")


def jamais_deux_flux(requetes, quoi):
    """Chaque flux commence après la fin du précédent, ou après un 1004."""
    debuts = flux(requetes)
    arrets = [r["t"] for r in requetes if r["api_id"] == 1004]
    for (a, ta, octets_a), (b, tb, _) in zip(debuts, debuts[1:]):
        fin_a = ta + octets_a / 32000.0
        coupe = any(ta <= t <= tb for t in arrets)
        verifier(coupe or tb >= fin_a - 0.05,
                 f"{quoi} : « {b} » commence à {tb - ta:.2f} s alors que « {a} » dure {fin_a - ta:.2f} s (deux flux)")


# ---------------------------------------------------------------- le critère

def critere_40(args):
    from atelier.lieu import voix as V
    from atelier.voix.synthese import lire_wav, reechantillonner
    sons = Path(args.sons)
    obs = Observateur()
    try:
        # 0. la voix lancée par l'Atelier, sortie robot
        code, d = appel(args.api, "POST", "/api/voix/demarrer", {"lieu": args.lieu, "sortie": "robot", "volume": 70})
        verifier(code == 200, f"POST /api/voix/demarrer : {code} {d}")
        attendre(lambda: (obs.etat() or {}).get("robot", {}).get("abonne"), 30,
                 "pas de /voix/etat avec le faux G1 abonné en 30 s")
        code, d = appel(args.api, "GET", "/api/voix/etat")
        verifier(code == 200 and d["lancee"] and d["tourne"], f"GET /api/voix/etat : {code} {d}")
        attendre(lambda: [r["api_id"] for r in obs.depuis()][:2] == [1006, 1005], 10, "pas de 1006 puis 1005 au départ")
        verifier(obs.depuis()[0]["parametre"] == {"volume": 70}, f"volume du départ : {obs.depuis()[0]}")
        dire("voix lancée par l'Atelier (sortie robot) ; au départ : 1006 {\"volume\": 70} puis 1005")

        # 1. « Bonjour, suivez-moi ! »
        rang = obs.rang()
        t_dire = time.monotonic()
        obs.dire("Bonjour, suivez-moi !", "e2e-bonjour")
        verifier(attendre_dite(obs, "e2e-bonjour") == "dite", "« Bonjour, suivez-moi ! » pas dite jusqu'au bout")
        lectures = [r for r in obs.depuis(rang) if r["api_id"] == 1003]
        verifier(lectures and all(r["erreurs"] == [] for r in lectures), f"1003 non conformes : {lectures[:2]}")
        verifier({r["parametre"]["stream_id"] for r in lectures} == {"e2e-bonjour"},
                 f"stream_id : {[r['parametre'] for r in lectures]}")
        verifier(all(r["parametre"] == {"app_name": "atelier", "stream_id": "e2e-bonjour"} for r in lectures),
                 "parameter de 1003 différent du SDK")
        tailles = [r["octets"] for r in lectures]
        verifier(all(0 < n <= 96000 and n % 2 == 0 for n in tailles), f"tailles des morceaux : {tailles}")
        wav = sons / "e2e-bonjour.wav"
        verifier(wav.is_file(), f"le WAV de Piper de la phrase manque : {wav}")
        frequence, echantillons = lire_wav(wav)
        attendu = len(reechantillonner(echantillons.astype("float32") / 32768.0, frequence)) / 16000.0
        recu = sum(tailles) / 32000.0
        verifier(abs(recu - attendu) <= 0.05 * attendu, f"durée reçue {recu:.3f} s, WAV de Piper {attendu:.3f} s")
        instants = [r["t"] for r in lectures]
        verifier(all(b - a >= 0.9 for a, b in zip(instants, instants[1:])), f"morceaux trop rapprochés : {instants}")
        voix_g1 = attendre(lambda: [f for f in (obs.voix_jumeau() or {}).get("flux", [])
                                    if f["stream_id"] == "e2e-bonjour"], 5, "le faux G1 n'a pas ce flux")
        verifier(voix_g1[0]["octets"] == sum(tailles) and voix_g1[0]["trous"] == 0, f"flux du faux G1 : {voix_g1}")
        dire(f"« Bonjour, suivez-moi ! » : {len(tailles)} morceau(x) {tailles}, {recu:.2f} s reçues pour "
             f"{attendu:.2f} s de Piper à 16 kHz ({frequence} Hz d'origine), même stream_id, reçues par le faux G1 ; "
             f"premier morceau {lectures[0]['t'] - t_dire:.2f} s après /robot/dire (synthèse comprise)")

        # 2. trois phrases de suite, puis haute, puis sécurité
        rang = obs.rang()
        phrases = [("Première phrase de la file.", "e2e-un"), ("Deuxième phrase, un peu plus longue.", "e2e-deux"),
                   ("Troisième et dernière.", "e2e-trois")]
        for texte, ident in phrases:
            obs.dire(texte, ident)
        for _, ident in phrases:
            verifier(attendre_dite(obs, ident) == "dite", f"« {ident} » pas dite")
        ordre = [f[0] for f in flux(obs.depuis(rang))]
        verifier(ordre == ["e2e-un", "e2e-deux", "e2e-trois"], f"ordre des phrases : {ordre}")
        jamais_deux_flux(obs.depuis(rang), "trois phrases")
        verifier(1004 not in [r["api_id"] for r in obs.depuis(rang)], "1004 entre des phrases normales")
        dire("trois phrases dites dans l'ordre, chacune après la fin de la précédente, sans 1004")

        rang = obs.rang()
        obs.dire("Je vous accompagne jusqu'à la salle B204, au bout du couloir nord ; restez bien derrière moi, "
                 "s'il vous plaît, et faites attention aux personnes que nous croisons.", "e2e-longue")
        attendre_depart(obs, "e2e-longue", rang)
        time.sleep(1.2)
        obs.dire("Attention, je passe !", "e2e-haute", priorite="haute")
        attendre_depart(obs, "e2e-haute", rang)
        apres = obs.depuis(rang)
        apis = [(r["api_id"], (r["parametre"] or {}).get("stream_id")) for r in apres if r["api_id"] in (1003, 1004)]
        premier_haute = apis.index((1003, "e2e-haute"))
        verifier(apis[premier_haute - 1] == (1004, None), f"pas de 1004 juste avant la phrase haute : {apis}")
        verifier(attendre_dite(obs, "e2e-longue") == "interrompue", "la phrase longue n'est pas notée interrompue")
        attendre_dite(obs, "e2e-haute")
        dire("phrase haute : 1004, puis la nouvelle phrase")

        rang = obs.rang()
        obs.dire("Une longue phrase que la sécurité va couper, avant les deux autres qui attendent leur tour "
                 "derrière elle dans la file.", "e2e-longue2")
        obs.dire("Celle-ci attend.", "e2e-attente1")
        obs.dire("Celle-là aussi.", "e2e-attente2")
        attendre_depart(obs, "e2e-longue2", rang)
        time.sleep(1.2)
        obs.dire("Je fais une petite pause.", "e2e-securite", priorite="securite", source="accueil")
        attendre_dite(obs, "e2e-securite")
        time.sleep(3.0)
        apres = obs.depuis(rang)
        ordre = [f[0] for f in flux(apres)]
        verifier(ordre == ["e2e-longue2", "e2e-securite"], f"après la phrase de sécurité : {ordre}")
        apis = [(r["api_id"], (r["parametre"] or {}).get("stream_id")) for r in apres if r["api_id"] in (1003, 1004)]
        premier = apis.index((1003, "e2e-securite"))
        verifier(apis[premier - 1] == (1004, None), f"pas de 1004 avant la phrase de sécurité : {apis}")
        verifier((obs.etat() or {}).get("file") == 0, f"file pas vidée : {obs.etat()}")
        g1 = obs.voix_jumeau() or {}
        verifier(g1.get("flux_meles") == 0 and g1.get("ecarts") == 0, f"faux G1 : flux mêlés ou écarts : {g1}")
        dire("phrase de sécurité : 1004, puis elle seule (les deux phrases en attente ne sont jamais dites) ; "
             "le faux G1 n'a vu ni flux mêlé ni écart")

        # 3. commandes : volume, taire ; par l'Atelier : volume et essayer
        rang = obs.rang()
        obs.commander(action="volume", volume=60)
        attendre(lambda: any(r["api_id"] == 1006 for r in obs.depuis(rang)), 5, "pas de 1006 après volume 60")
        verifier(next(r for r in obs.depuis(rang) if r["api_id"] == 1006)["parametre"] == {"volume": 60},
                 "parameter de 1006")
        rang = obs.rang()
        obs.commander(action="taire")
        attendre(lambda: [r["api_id"] for r in obs.depuis(rang)] == [1004], 5,
                 f"« taire » : {[r['api_id'] for r in obs.depuis(rang)]}")
        rang = obs.rang()
        code, d = appel(args.api, "POST", "/api/voix/commande", {"action": "volume", "volume": 65})
        verifier(code == 200, f"POST /api/voix/commande : {code} {d}")
        attendre(lambda: any(r["api_id"] == 1006 and r["parametre"] == {"volume": 65} for r in obs.depuis(rang)), 5,
                 "pas de 1006 {volume: 65} par l'Atelier")
        rang = obs.rang()
        code, d = appel(args.api, "POST", "/api/voix/essayer", {"texte": "Bonjour depuis l'Atelier."})
        verifier(code == 200 and d.get("envoye"), f"POST /api/voix/essayer : {code} {d}")
        attendre_depart(obs, d["id"], rang)
        attendre_dite(obs, d["id"])
        dire("/voix/commande volume 60 → 1006 {\"volume\": 60} ; taire → 1004 ; l'Atelier : volume 65 et « Essayer »")

        # 4. sortie robot_tts, puis borne
        rang = obs.rang()
        obs.commander(action="sortie", sortie="robot_tts")
        attendre(lambda: (obs.etat() or {}).get("sortie") == "robot_tts", 5, "sortie robot_tts pas prise")
        obs.dire("Bonjour à tous", "e2e-tts")
        attendre(lambda: any(r["api_id"] == 1001 for r in obs.depuis(rang)), 10, "pas de 1001")
        tts = next(r for r in obs.depuis(rang) if r["api_id"] == 1001)
        verifier(set(tts["parametre"]) == {"index", "speaker_id", "text"} and tts["parametre"]["text"] ==
                 "Bonjour à tous" and tts["erreurs"] == [], f"1001 : {tts}")
        attendre_dite(obs, "e2e-tts")
        dire(f"sortie robot_tts : 1001 {tts['texte']}")

        rang = obs.rang()
        obs.commander(action="sortie", sortie="borne")
        attendre(lambda: (obs.etat() or {}).get("sortie") == "borne", 5, "sortie borne pas prise")
        obs.dire("Bonjour, je parle par la borne.", "e2e-borne")
        son = attendre(lambda: [s for s in obs.sons if s["id"] == "e2e-borne"], 15, "pas de /voix/son")[0]
        verifier(son["url"] == "/api/voix/son/e2e-borne", f"/voix/son : {son}")
        verifier((sons / "e2e-borne.wav").is_file(), "pas de WAV dans ATELIER_VOIX_SONS")
        code, (entetes, contenu) = appel(args.api, "GET", son["url"], brut=True)
        verifier(code == 200 and entetes.get("content-type") == "audio/wav" and contenu[:4] == b"RIFF",
                 f"GET {son['url']} : {code} {entetes.get('content-type')}")
        attendre_dite(obs, "e2e-borne")
        verifier(not [r for r in obs.depuis(rang) if r["api_id"] in (1001, 1003)], "la borne a parlé au robot")
        dire(f"sortie borne : /voix/son conforme, WAV de {son['duree_s']:.2f} s servi en audio/wav, rien vers le robot")

        # 5. un 1003 de 3 octets du test, puis la panne muet
        obs.commander(action="sortie", sortie="robot")
        attendre(lambda: (obs.etat() or {}).get("sortie") == "robot", 5, "retour à la sortie robot")
        ecarts = (obs.voix_jumeau() or {}).get("ecarts", 0)
        identifiant = 4_000_000_000 + int(time.time())
        obs.envoyer_requete(identifiant, 1003, V.parametre_lecture("e2e-ecart"), b"\x00\x01\x02")
        attendre(lambda: (obs.voix_jumeau() or {}).get("ecarts", 0) == ecarts + 1, 5,
                 "le faux G1 n'a pas compté le 1003 de 3 octets comme écart")
        attendre(lambda: identifiant in obs.reponses, 5, "pas de réponse au 1003 de 3 octets")
        verifier(obs.reponses[identifiant][1] == 3204, f"réponse au 1003 de 3 octets : {obs.reponses[identifiant]}")
        dire("un 1003 de 3 octets du test : compté comme écart par le faux G1 (réponse 3204)")

        obs.panne("muet")
        time.sleep(1.0)
        obs.dire("Personne ne me répond.", "e2e-muet")
        attendre(lambda: ((obs.etat() or {}).get("robot") or {}).get("repond") is False, 10,
                 "/voix/etat ne dit pas que le robot ne répond plus")
        code, d = appel(args.api, "GET", "/api/voix/etat")
        verifier(code == 200 and d["lancee"] and d["tourne"], f"le nœud voix ne tourne plus : {d}")
        obs.panne("aucune")
        time.sleep(1.0)
        obs.dire("Me revoilà.", "e2e-retour")
        attendre(lambda: ((obs.etat() or {}).get("robot") or {}).get("repond") is True, 15,
                 "le robot ne répond toujours pas après la panne")
        attendre_dite(obs, "e2e-retour")
        dire(f"panne muet : /voix/etat dit « ne répond plus » ({obs.etat()['erreurs']} erreur(s) comptées), "
             "le nœud tourne, puis le robot répond de nouveau")

        # 6. tout du long
        toutes = obs.depuis()
        hors = sorted({r["api_id"] for r in toutes} - set(APIS))
        verifier(not hors, f"requêtes hors de 1001, 1003, 1004, 1005, 1006 : {hors}")
        mal = [r for r in toutes if r["erreurs"] and r["id"] != identifiant]
        verifier(not mal, f"requêtes du nœud voix non conformes : {mal[:3]}")
        verifier(not obs.non_conformes, f"messages non conformes : {obs.non_conformes[:3]}")
        dire(f"{len(obs.etats)} /voix/etat conformes, {len(toutes)} requêtes toutes dans 1001, 1003 à 1006")
        code, d = appel(args.api, "POST", "/api/voix/arreter")
        verifier(code == 200 and d.get("arrete"), f"POST /api/voix/arreter : {code} {d}")
        code, d = appel(args.api, "GET", "/api/voix/etat")
        verifier(code == 200 and not d["lancee"], f"le nœud voix tourne encore : {d}")
        dire("POST /api/voix/arreter : nœud voix arrêté")
    except Echec as e:
        dire(f"ÉCHEC : {e}")
        return 1
    finally:
        obs.fermer()
    return 0


def restes(args):
    """Code 1 s'il reste un nœud voix lancé avec ce dossier de sons."""
    trouves = []
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            commande = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
            env = (proc / "environ").read_bytes().split(b"\0")
        except OSError:
            continue
        if "atelier.voix" in commande and f"ATELIER_VOIX_SONS={args.sons}".encode() in env:
            trouves.append(f"{proc.name} {commande[:120]}")
    if trouves:
        dire(f"des nœuds voix restent : {trouves}")
        return 1
    return 0


def main():
    a = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sous = a.add_subparsers(dest="commande", required=True)
    s = sous.add_parser("critere-40")
    s.add_argument("--api", required=True)
    s.add_argument("--lieu", required=True)
    s.add_argument("--sons", required=True)
    s = sous.add_parser("restes")
    s.add_argument("--sons", required=True)
    args = a.parse_args()
    return {"critere-40": critere_40, "restes": restes}[args.commande](args)


if __name__ == "__main__":
    sys.exit(main())
