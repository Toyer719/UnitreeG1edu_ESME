"""Outils communs aux essais de la borne et de la démo (vague 6, sections 13.4 et 13.5 du plan) : agent Borne et
orchestrateur. Ce fichier ne contient aucun test.

- PontDemo : un faux pont ROS 2 du serveur, branché sur la vraie machine d'états de la démo
  (g1_accueil.logique.Orchestrateur, sans ROS) : ce que le serveur publie sur /accueil/choix et /accueil/commande
  arrive à l'orchestrateur, et ce qu'il publie (/accueil/etat, /accueil/evenement, /guide/aller…) est « reçu » par
  le serveur, comme par le vrai pont (dernier, historique, avec age_recu_s) ;
- client_demo(tmp_path, monkeypatch) : l'application de l'Atelier (TestClient, sans ROS) sur une copie du lieu demo,
  avec ce faux pont et une démo en attente à l'accueil ;
- FAUSSES_COMMANDES : g1-accueil et g1-voix qui notent leurs arguments et attendent (lancement par l'Atelier).
"""
import os
import socket
import sys
import threading
import time
from pathlib import Path

import atelier
from atelier.lieu import copier_lieu

RACINE = atelier.RACINE
DEMO = RACINE / "lieux" / "demo"
PAQUET_ACCUEIL = RACINE / "ws" / "src" / "g1_accueil"
if str(PAQUET_ACCUEIL) not in sys.path:
    sys.path.insert(0, str(PAQUET_ACCUEIL))

from g1_accueil.logique import Orchestrateur  # noqa: E402

PRINCIPAL = (2.5, 10.0, 0.0)

FAUSSE_COMMANDE = r'''#!{python}
"""Fausse {nom} des essais de la démo : note ses arguments, puis attend."""
import os, sys, time
with open(os.environ["FAUX_JOURNAL_DEMO"], "a") as f:
    f.write("{nom} " + " ".join(sys.argv[1:]) + "\n")
if os.environ.get("FAUX_{variable}_ECHEC") == "1":
    print("{nom} : pas encore fait", flush=True)
    sys.exit(1)
time.sleep(300)
'''


def ecrire_fausses_commandes(dossier, journal):
    """g1-accueil et g1-voix factices dans dossier ; leurs appels sont notés dans journal."""
    dossier = Path(dossier)
    dossier.mkdir(parents=True, exist_ok=True)
    for nom, variable in (("g1-accueil", "ACCUEIL"), ("g1-voix", "VOIX")):
        chemin = dossier / nom
        chemin.write_text(FAUSSE_COMMANDE.format(python=sys.executable, nom=nom, variable=variable))
        chemin.chmod(0o755)
    os.environ["FAUX_JOURNAL_DEMO"] = str(journal)
    return dossier


class PontDemo:
    """Faux PontRos pour les routes de la démo et de la borne, branché sur l'orchestrateur de la démo."""

    def __init__(self, orchestrateur=None):
        self.actif = True
        self.erreur = None
        self.o = orchestrateur
        self.recus = {}            # sujet → [(données, instant)]
        self.publies = []          # (sujet, données) publiés par le serveur
        self.verrou = threading.RLock()    # le serveur (fils, boucle asyncio) et le test l'appellent
        self.muet = False                  # vrai : la démo ne publie pas son état (pas encore lancée)

    # ce que le vrai pont « reçoit »
    def recevoir(self, sujet, donnees):
        with self.verrou:
            self.recus.setdefault(sujet, []).append((donnees, time.monotonic()))
            del self.recus[sujet][:-50]

    def _avec_age(self, d, t):
        age = time.monotonic() - t
        return dict(d, age_recu_s=round(age, 2), perime=age > 2.0)

    def dernier(self, sujet):
        with self.verrou:
            liste = list(self.recus.get(sujet) or [])
        return self._avec_age(*liste[-1]) if liste else None

    def historique(self, sujet):
        with self.verrou:
            liste = list(self.recus.get(sujet, []))
        return [self._avec_age(d, t) for d, t in liste]

    def publier_json(self, sujet, donnees):
        if not self.actif:
            raise RuntimeError("le pont ROS 2 n'est pas démarré")
        with self.verrou:
            self.publies.append((sujet, donnees))
            if self.o is not None and sujet in ("/accueil/choix", "/accueil/commande"):
                self._garder(self.o.entrer(sujet, donnees))
        return 1 if self.o is not None else 0

    # la démo
    def _garder(self, sorties):
        for sujet, d in sorties:
            if d is not None:
                self.recevoir(sujet, d)

    def rafraichir(self):
        """La démo publie son état (2 fois par seconde en vrai) : il reste frais pour le serveur."""
        with self.verrou:
            if self.o is not None:
                self._garder(self.o.pas())
                if not self.muet:
                    self.recevoir("/accueil/etat", self.o.etat())

    def guide(self, etat, **champs):
        """Le guide publie son état (et la position du robot) ; la démo le lit."""
        pose = champs.pop("pose", PRINCIPAL)
        g = dict({"version": 1, "etat": etat, "cible": None, "reste_m": None, "itineraire": [], "mission": None,
                  "actif": etat in ("en_route", "retour")}, **champs)
        with self.verrou:
            self.dernier_guide = (g, pose)
            self._garder(self.o.entrer("/guide/etat", g))
            self._garder(self.o.entrer("position", pose))
            self.rafraichir()

    def entrer(self, sujet, donnees):
        """Un message pour la démo (pont, pilotage, personnes…), comme s'il venait de ROS 2."""
        with self.verrou:
            self._garder(self.o.entrer(sujet, donnees))
            self.rafraichir()

    def envoyes(self, sujet):
        """Ce que la démo a publié sur ce sujet (ex. /guide/aller), le plus ancien d'abord."""
        return [d for d, _ in self.recus.get(sujet, [])]

    # ce dont le reste du serveur a besoin (EtatServeur, /ws/etat)
    def etat(self):
        return {"actif": self.actif, "erreur": self.erreur, "robot": None, "guide": None, "nav2": None}

    def reperage(self):
        return None

    def etat_pont(self):
        return None

    def demarrer(self, attente=10.0):
        return True

    def arreter(self):
        pass

    def oublier(self):
        pass

    def abonnes_aller(self):
        return 0

    def stop(self):
        self.publies.append(("/guide/stop", None))
        return 0

    def bloquer(self, verrou):
        self.publies.append(("/pont/arret", bool(verrou)))
        return 0

    def guides_a_l_ecoute(self):
        return 0

    def temps_sim(self):
        return None


def orchestrateur(dossier, **reglages):
    """La machine d'états de la démo sur un lieu (salles.yaml), réglages de test."""
    from atelier.lieu import charger_salles
    from atelier.lieu.principal import point_principal
    p = point_principal(dossier)
    reglages.setdefault("presence_s", 0.0)
    return Orchestrateur(charger_salles(dossier), p.id, p.etage, reglages, lieu=dossier.name,
                         pose_principale=(p.pose.x, p.pose.y, p.pose.theta))


def client_demo(tmp_path, monkeypatch, nom="essai", ros=True, **reglages):
    """(TestClient, PontDemo, dossier du lieu) : l'Atelier sans ROS, sur une copie du demo, une démo à l'accueil."""
    from fastapi.testclient import TestClient
    from atelier.serveur.main import creer_app
    monkeypatch.setenv("ATELIER_LIEUX", str(tmp_path / "lieux"))
    monkeypatch.setenv("ATELIER_INTERFACE_ROBOT", "interface_absente_v6")
    monkeypatch.delenv("ATELIER_HOTE", raising=False)
    monkeypatch.delenv("ATELIER_DISTANT", raising=False)
    dossier = copier_lieu(DEMO, tmp_path / "lieux" / nom)
    app = creer_app(ros=False)
    pont = PontDemo(orchestrateur(dossier, **reglages) if ros else None)
    app.state.atelier.pont = pont
    if ros:
        pont.guide("attente")
    return app, pont, dossier


class ServeurDemo:
    """L'Atelier (sans ROS) servi par uvicorn dans un fil, avec le faux pont de la démo : pour Firefox. Un second
    fil rafraîchit l'état de la démo (2 fois par seconde, le guide republie son dernier état), comme le vrai nœud."""

    def __init__(self, app, pont):
        self.app, self.pont = app, pont
        self.serveur = self.fil = self.base = None
        self._fin = threading.Event()

    def __enter__(self):
        import uvicorn
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        config = uvicorn.Config(self.app, host="127.0.0.1", port=port, log_level="warning", lifespan="on")
        self.serveur = uvicorn.Server(config)
        self.fil = threading.Thread(target=self.serveur.run, name="uvicorn essai borne", daemon=True)
        self.fil.start()
        fin = time.monotonic() + 20
        while not self.serveur.started:
            if time.monotonic() > fin:
                raise RuntimeError("le serveur d'essai de la borne ne démarre pas")
            time.sleep(0.05)
        self.base = f"http://127.0.0.1:{port}"
        threading.Thread(target=self._rafraichir, name="démo d'essai", daemon=True).start()
        return self

    def _rafraichir(self):
        while not self._fin.wait(0.5):
            if self.pont.o is None:
                continue
            g = getattr(self.pont, "dernier_guide", None)
            if g is not None:
                self.pont.guide(g[0]["etat"], **{k: v for k, v in g[0].items()
                                                 if k not in ("etat", "version")}, pose=g[1])
            else:
                self.pont.rafraichir()

    def __exit__(self, *erreur):
        self._fin.set()
        self.serveur.should_exit = True
        self.fil.join(timeout=10)


# ---------------------------------------------------------------- la borne dans Firefox (critère 39)

# Firefox sans fenêtre ne descend pas sous 500 px de large : la borne est ouverte dans un cadre (iframe) de la taille
# exacte du téléphone ou de la tablette, et les scripts des essais tournent dans ce cadre.
CLE_ELEMENT = "element-6066-11e4-a52e-4f735466cecf"

CADRE = """
const [url, l, h] = arguments;
document.body.style.margin = '0';
document.body.textContent = '';
const f = document.createElement('iframe');
f.id = 'cadre-borne';
f.src = url;
f.style.cssText = 'border:0;display:block;width:' + l + 'px;height:' + h + 'px';
document.body.appendChild(f);
return f;
"""

# Mesures de la borne, dans le cadre : la page ne défile pas, chaque carte fait 64 px au moins et peut être
# amenée entière à l'écran (dans la liste qui défile), aucun nom de sujet ROS, aucune erreur de la page
MESURE_BORNE = r"""
const iw = window.innerWidth, ih = window.innerHeight;
const de = document.documentElement, b = document.body;
const fautes = [];
const sw = Math.max(de.scrollWidth, b.scrollWidth), sh = Math.max(de.scrollHeight, b.scrollHeight);
if (sw > iw + 1 || sh > ih + 1) fautes.push('la page déborde : ' + sw + ' × ' + sh + ' pour ' + iw + ' × ' + ih);
const liste = document.querySelector('[data-role=borne-salles]');
const cartes = Array.from(document.querySelectorAll('[data-salle]'));
const visibles = cartes.filter((c) => c.getBoundingClientRect().height > 0);
for (const c of visibles) {
  c.scrollIntoView({ block: 'nearest' });
  const r = c.getBoundingClientRect();
  const z = liste.getBoundingClientRect();
  if (r.height < 64) fautes.push(c.dataset.salle + ' : ' + Math.round(r.height) + ' px de haut');
  if (r.top < z.top - 1 || r.bottom > z.bottom + 1 || r.left < -1 || r.right > iw + 1 || r.bottom > ih + 1)
    fautes.push(c.dataset.salle + ' coupée : ' + [r.left, r.top, r.right, r.bottom].map(Math.round).join(', '));
  const t = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
  if (!(t === c || c.contains(t))) fautes.push(c.dataset.salle + ' recouverte');
}
if (liste) liste.scrollTop = 0;
const texte = b.innerText || '';
const sujets = texte.match(/\/(accueil|guide|robot|voix|pont|api|ws)|ROS|json|topic/gi) || [];
if (sujets.length) fautes.push('jargon à l\'écran : ' + sujets.join(', '));
for (const x of document.querySelectorAll('button, [data-salle]')) {
  const r = x.getBoundingClientRect();
  if (r.width > 0 && r.height > 0 && x.closest('.borne-voile') === null && (r.height < 44 || r.width < 44))
    fautes.push('cible trop petite : ' + (x.dataset.role || x.dataset.salle || x.className) + ' ' + Math.round(r.width) + ' × ' + Math.round(r.height));
}
return { fautes: fautes, cartes: visibles.map((c) => c.dataset.salle), ecran: document.querySelector('[data-role=borne]').dataset.ecran,
  erreurs: window.erreursBorne || ['window.erreursBorne absent'], taille: [iw, ih] };
"""


def preparer_firefox():
    """Écran sans fenêtre assez grand pour une tablette de 1024 × 768 et sa marge (défaut de Firefox : 1366 × 768).
    À appeler avant de lancer geckodriver."""
    os.environ.setdefault("MOZ_HEADLESS_WIDTH", "1600")
    os.environ.setdefault("MOZ_HEADLESS_HEIGHT", "1200")


def assurer_taille(nav, largeur, hauteur):
    """Fenêtre d'au moins largeur × hauteur px à l'intérieur (le cadre y tient entier, pour sa capture)."""
    voulu = [largeur + 20, hauteur + 20]
    for _ in range(6):
        nav._requete("POST", f"/session/{nav.session}/window/rect", {"width": voulu[0], "height": voulu[1]})
        time.sleep(0.3)
        iw, ih = nav.js("return [window.innerWidth, window.innerHeight]")
        if iw >= largeur and ih >= hauteur:
            return iw, ih
        # la fenêtre sans affichage a quand même ses barres : on les ajoute à la demande suivante
        voulu = [voulu[0] + max(0, largeur - iw) + 10, voulu[1] + max(0, hauteur - ih) + 10]
    raise AssertionError(f"la fenêtre de Firefox ne fait pas {largeur} × {hauteur} px (seulement {iw} × {ih})")


def ouvrir_borne_cadre(nav, base, largeur, hauteur, chemin="/borne"):
    """Ouvre la borne dans un cadre de largeur × hauteur px et y place les scripts ; renvoie l'élément du cadre."""
    try:
        sortir_du_cadre(nav)
    except RuntimeError:
        pass
    nav.ouvrir("about:blank")
    assurer_taille(nav, max(largeur, 500), hauteur)
    cadre = nav.js(CADRE, base + chemin, largeur, hauteur)
    nav._requete("POST", f"/session/{nav.session}/frame", {"id": cadre})
    nav.cadre = cadre
    fin = time.monotonic() + 20
    while time.monotonic() < fin:          # le cadre charge la borne (avant : son about:blank initial)
        try:
            if nav.js("return !!document.querySelector('[data-role=borne]') && !!window.borne"):
                return cadre
        except RuntimeError:
            pass
        time.sleep(0.1)
    raise AssertionError("la borne ne se charge pas dans le cadre")


def sortir_du_cadre(nav):
    nav._requete("POST", f"/session/{nav.session}/frame", {"id": None})


def capture_cadre(nav, chemin):
    """Capture du seul cadre de la borne (taille exacte du téléphone ou de la tablette)."""
    import base64
    sortir_du_cadre(nav)
    try:
        png = nav._requete("GET", f"/session/{nav.session}/element/{nav.cadre[CLE_ELEMENT]}/screenshot")
        Path(chemin).parent.mkdir(parents=True, exist_ok=True)
        Path(chemin).write_bytes(base64.b64decode(png))
    finally:
        nav._requete("POST", f"/session/{nav.session}/frame", {"id": nav.cadre})


def attendre_ecran(nav, ecran, delai=10.0):
    return nav.attendre("const b = document.querySelector('[data-role=borne]'); "
                        "return !!b && b.getAttribute('data-ecran') === arguments[0]", ecran, delai=delai,
                        message=f"écran {ecran} de la borne")


def ouvrir_client(app, **options):
    from fastapi.testclient import TestClient
    return TestClient(app, **options)
