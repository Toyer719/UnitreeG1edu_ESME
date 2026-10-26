"""Vue du robot de l'onglet Pilotage dans Firefox sans fenêtre (section 11.13 du plan).

Serveur : bin/g1-atelier avec son pont ROS 2, en répétition (fausses commandes g1-*), relié au nœud
pilotage en mémoire de test_pilotage_serveur (logique, cœur et API tornado réels, faux G1 et sa
caméra de test en mémoire). Le faux relais odom_vers_tf de test_robot_serveur_ros publie la position
du robot (/reperage/etat) ; les piétons viennent du monde du demo.
Parcours : la vue apparaît sous « Commandes » et « Danses du robot » (pas sous « Mes
chorégraphies »), la carte montre le robot et les passants, le G1 en 3D se charge, puis suit la
posture, la marche, un geste (aperçu approché), une danse (barre de progression) et une
chorégraphie (vraies poses) ; caméra : remplacement en répétition, puis l'image de test du faux G1 ;
ARRÊT toujours visible. Toutes les poses approchées restent dans les limites de l'URDF.
Sauté sans geckodriver, Firefox ou ROS 2. Domaine ROS : $ROS_DOMAIN_ID, 63 par défaut.
Variable CAPTURES_VUE=dossier : captures d'écran du parcours (pour les regarder).
"""
import base64
import json
import os
import shutil
import time
import urllib.request
from pathlib import Path

import pytest

os.environ.setdefault("ROS_DOMAIN_ID", "63")
pytest.importorskip("rclpy", reason="ROS 2 n'est pas chargé : source ~/robot-g1/setup/env.sh")

from atelier.lieu import pilotage as D  # noqa: E402

from .test_pilotage_navigateur import APPUI  # noqa: E402
from .test_pilotage_serveur import NoeudEnMemoire  # noqa: E402
from .test_robot_serveur_ros import FauxRelais  # noqa: E402
from .test_serveur_communs import attendre, faux_bin, journaux, lieux  # noqa: E402,F401
from .test_serveur_demarrage import serveur  # noqa: E402,F401
from .test_serveur_navigateur import GECKODRIVER, navigateur  # noqa: E402,F401

pytestmark = pytest.mark.skipif(GECKODRIVER is None or shutil.which("firefox") is None,
                                reason="geckodriver ou Firefox absent")

POSE_ROBOT = {"x": 7.0, "y": 7.0, "theta": 0.6}

LIMITES = """
const fini = arguments[arguments.length - 1];
Promise.all([import('/js/pilotage/poses_vue.js'), fetch('/api/pilotage/modele').then((r) => r.json()),
  fetch('/api/pilotage/config').then((r) => r.json())]).then(([P, modele, config]) => {
  const limites = P.limitesDuModele(modele);
  const fautes = [];
  const voir = (quoi, q) => P.horsLimites(q, limites).forEach((f) => fautes.push([quoi].concat(f)));
  Object.keys(P.POSTURES).forEach((n) => voir('posture ' + n, P.POSTURES[n].q));
  const manquent = [];
  [['bras', config.gestes], ['tache', config.taches]].forEach(([genre, liste]) => liste.forEach((g) => {
    if (!P.GESTES[genre][g.id]) manquent.push(genre + ' ' + g.id);
    P.posesClesGeste(genre, g.id).forEach((q, i) => voir(genre + ' ' + g.id + ' clé ' + i, q));
    const repos = P.poseDeRepos();
    for (let t = 0; t <= P.dureeGeste(genre, g.id) + 0.5; t += 0.05) {
      voir(genre + ' ' + g.id + ' à ' + t.toFixed(2), P.poseGeste(genre, g.id, t, repos, repos).q);
    }
  }));
  for (let t = 0; t < 8; t += 0.05) voir('danse à ' + t.toFixed(2), P.poseDanse(t));
  const l = config.limites_marche;
  [[l.vx, 0, 0], [-l.vx, 0, 0], [0, l.vy, 0], [0, 0, l.wz], [l.vx, -l.vy, -l.wz]].forEach(([vx, vy, wz]) => {
    for (let f = 0; f < 2 * Math.PI; f += 0.1) {
      Object.keys(P.POSTURES).forEach((n) => voir('marche ' + [vx, vy, wz] + ' ' + n,
        P.poseMarche(P.POSTURES[n].q, { vx, vy, wz }, f, l)));
    }
  });
  fini({ fautes: fautes.slice(0, 20), nombre: fautes.length, manquent, articulations: Object.keys(limites).length });
}).catch((e) => fini({ erreur: String(e) }));
"""


@pytest.fixture
def noeud(tmp_path, monkeypatch):
    n = NoeudEnMemoire().demarrer()
    dossier = tmp_path / "choregraphies"
    (dossier / "musique").mkdir(parents=True)
    exemple = D.chemin_choregraphie("exemple_kpop")
    (dossier / exemple.name).write_text(exemple.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv("G1_PILOTAGE_URL", f"http://127.0.0.1:{n.port}")
    monkeypatch.setenv("G1_PILOTAGE_JETON", "")
    monkeypatch.setenv("ATELIER_CHOREGRAPHIES", str(dossier))
    yield n
    n.arreter()


@pytest.fixture
def relais():
    r = FauxRelais()
    r.etat = FauxRelais._etat("repere", "vue", dict(POSE_ROBOT), "Robot repéré (faux relais).")
    yield r
    r.fermer()


def _api(base, chemin, corps=None):
    r = urllib.request.Request(base + chemin, method="GET" if corps is None else "POST",
                               data=None if corps is None else json.dumps(corps).encode(),
                               headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=20) as reponse:
        return json.loads(reponse.read())


def _capture(nav, nom):
    dossier = os.environ.get("CAPTURES_VUE")
    if not dossier:
        return
    png = nav._requete("GET", f"/session/{nav.session}/screenshot")
    Path(dossier).mkdir(parents=True, exist_ok=True)
    (Path(dossier) / f"{nom}.png").write_bytes(base64.b64decode(png))


def _legende(nav):
    return nav.js("return document.querySelector('.vue-robot-legende').innerText")


def test_vue_du_robot(noeud, relais, serveur, navigateur, faux_bin):
    _, base = serveur
    nav = navigateur
    _api(base, "/api/lieux/demo/etages/rdc/monde/generer", {})          # carte et .sdf (faux g1-monde)
    _api(base, "/api/simulation/demarrer", {"lieu": "demo", "etage": "rdc", "mode": "repetition"})
    assert attendre(lambda: _api(base, "/api/robot/etat?lieu=demo&etage=rdc")["repere"], 20, 0.3)
    nav.ouvrir(base + "/")
    nav.attendre("return document.querySelector('.onglet.actif') !== null", message="premier écran ouvert")
    nav.js("localStorage.setItem('atelier.lieu', 'demo'); localStorage.setItem('atelier.etage', 'rdc');"
           "localStorage.setItem('atelier.pilotage.onglet', 'commandes');")
    nav.ouvrir(base + "/?recharger=1#pilotage")
    nav.attendre("return document.querySelector('.pilotage-barre .bouton-arret')", delai=20, message="barre du pilotage")
    nav.attendre("return document.querySelector('.pastille-pilotage').textContent.includes('Robot relié')",
                 delai=20, message="robot relié")
    nav.js("window.confirm = () => true;")
    # la vue sous « Commandes » : carte avec le robot et les passants, G1 en 3D chargé
    nav.attendre("return document.querySelector('.zone-vue-robot') && !document.querySelector('.zone-vue-robot').hidden",
                 message="vue du robot visible")
    nav.attendre("return window.vueRobot3d && window.vueRobot3d.pret && window.vueRobot3d.images > 0", delai=20,
                 message="G1 en 3D chargé")
    assert nav.js("return window.vueRobot3d.mode") in ("webgl", "canvas")
    nav.attendre("return document.querySelector('.vue-robot .robot-direct')", delai=20, message="robot sur la carte")
    centre = nav.js("""const c = window.vueRobot.plan.carte; const m = window.vueRobot.marqueurRobot.getLatLng();
                       return [m.lng, m.lat, c.getBounds().contains(m)];""")
    assert centre[0] == pytest.approx(POSE_ROBOT["x"]) and centre[1] == pytest.approx(POSE_ROBOT["y"]) and centre[2]
    nav.attendre("return document.querySelectorAll('.vue-robot .pieton-direct').length > 0", message="passants")
    assert "« demo », rdc" in nav.js("return document.querySelector('.vue-robot-carte .vue-robot-etat').textContent")
    # pieds au sol, robot debout
    hauteur = nav.js("return window.vueRobot3d.bassin.position.z")
    assert 0.7 < hauteur < 0.85, hauteur
    # caméra : en répétition, le remplacement ; « Voir » : l'image de test du faux G1, par le nœud
    texte = nav.js("return document.querySelector('.vue-robot-remplacement').textContent")
    assert texte.startswith("Pas de caméra en répétition"), texte
    nav.bouton("Voir", ".vue-robot-camera")
    nav.attendre("""const i = document.querySelector('.vue-robot-image img');
                    return !i.hidden && i.complete && i.naturalWidth === 640;""", delai=10, message="image de test")
    assert "image de test du faux G1" in nav.js("return document.querySelector('.vue-robot-etat-camera').textContent")
    numero = noeud.camera.images
    time.sleep(1.5)
    assert 2 <= noeud.camera.images - numero <= 6                    # quelques images par seconde
    _capture(nav, "1_commandes")
    # posture : démarrer (801), puis amortir au portique, puis démarrer
    nav.bouton("Prendre la main", ".pilotage-barre")
    nav.attendre("return document.querySelector('.etat-maitre').textContent === 'Vous avez la main'", message="la main")
    nav.bouton("Démarrer", ".pilotage-postures")
    nav.attendre("return document.querySelector('.vue-robot-posture').textContent.startsWith('Debout · mode 801')",
                 message="debout")
    nav.js("document.querySelector('.zone-portique input[type=checkbox]').click()")
    nav.bouton("Amortir", ".zone-portique")
    nav.attendre("return document.querySelector('.vue-robot-posture').textContent.startsWith('Amorti')",
                 message="amorti")
    nav.attendre("return window.vueRobot.qAffiche.waist_pitch > 0.2", message="le robot s'affaisse")
    nav.bouton("Démarrer", ".pilotage-postures")
    attendre(lambda: noeud.robot.fsm == 801, 5, 0.1)
    # geste : aperçu approché, les bras bougent puis reviennent
    nav.bouton("Applaudir", ".pilotage-gestes")
    nav.attendre("return document.querySelector('.vue-robot-activite').textContent === 'Geste : Applaudir'",
                 message="geste montré")
    assert _legende(nav).endswith("Aperçu approché : le vrai geste est dans le robot.")
    nav.attendre("return window.vueRobot.qAffiche.left_shoulder_pitch < -0.7", message="bras levés")
    _capture(nav, "2_geste")
    nav.attendre("return window.vueRobot.geste === null && window.vueRobot.qAffiche.left_shoulder_pitch > -0.1",
                 delai=10, message="bras revenus")
    # marche au joystick : les jambes suivent la consigne
    nav.js(APPUI, ".joystick-pave", 0.5, 0.0, False)
    nav.attendre("return document.querySelector('.vue-robot-activite').textContent.startsWith('Marche : avance')",
                 message="marche montrée")
    genoux = set()
    for _ in range(6):
        genoux.add(round(nav.js("return window.vueRobot.qAffiche.left_knee"), 2))
        time.sleep(0.12)
    nav.js(APPUI, ".joystick-pave", 0.5, 0.0, True)
    assert len(genoux) >= 3, genoux
    time.sleep(1.2)                                # robot immobile depuis 1 s : la danse est permise
    # danse du robot : barre de progression, sous « Danses du robot »
    nav.bouton("Danses du robot", ".pilotage-sous-onglets")
    assert nav.js("return !document.querySelector('.zone-vue-robot').hidden")
    nav.bouton("Lire la liste du robot", ".pilotage-danses")
    nav.attendre("return document.querySelectorAll('.tableau-danses tbody tr').length >= 7", message="danses")
    nav.js("document.querySelector('.pilotage-danses input[type=checkbox]').click()")
    nav.attendre("return !document.querySelector('tr[data-danse=\"604\"] .jouer-danse').disabled", message="jouer 604")
    noeud.robot.echelle_danses = 0.25             # danse courte : la chorégraphie suit
    nav.js("document.querySelector('tr[data-danse=\"604\"] .jouer-danse').click()")
    nav.attendre("return document.querySelector('.vue-robot-activite').textContent.startsWith('Danse 604')",
                 message="danse montrée")
    nav.attendre("return !document.querySelector('.vue-robot-progres').hidden", message="barre de progression")
    assert _legende(nav).endswith("Aperçu approché : la vraie danse est dans le robot.")
    _capture(nav, "3_danse")
    # ARRÊT toujours visible, même en bas de la page
    nav.js("window.scrollTo(0, document.body.scrollHeight); document.querySelectorAll('*').forEach((e) => {"
           " if (e.scrollHeight > e.clientHeight) e.scrollTop = e.scrollHeight; });")
    rect = nav.js("const r = document.querySelector('.bouton-arret-pilotage').getBoundingClientRect();"
                  "return [r.top, r.bottom, window.innerHeight];")
    assert 0 <= rect[0] and rect[1] <= rect[2], rect
    assert attendre(lambda: noeud.coeur.etat()["danse"] is None, 40, 0.5)
    # sous « Mes chorégraphies », pas de vue (l'éditeur a son aperçu) ; puis chorégraphie jouée
    nav.bouton("Mes chorégraphies", ".pilotage-sous-onglets")
    assert nav.js("return document.querySelector('.zone-vue-robot').hidden") is True
    nav.bouton("Commandes", ".pilotage-sous-onglets")
    assert attendre(lambda: noeud.robot.fsm == 801, 20, 0.2)
    nav.bouton("Relâcher les bras (99)", ".pilotage-gestes")      # le geste tenait les bras
    assert attendre(lambda: not noeud.coeur.etat()["bras_tenus"], 5, 0.1)
    r = urllib.request.Request(base + "/api/pilotage/choregraphies/exemple_kpop/jouer", method="POST",
                               data=json.dumps({"zone_libre": True}).encode(),
                               headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=20) as reponse:
        assert reponse.status == 200
    nav.attendre("return document.querySelector('.vue-robot-activite').textContent.startsWith('Chorégraphie « ')",
                 delai=10, message="chorégraphie montrée")
    assert _legende(nav).endswith("Poses exactes de la chorégraphie (bras et pas).")
    time.sleep(3.0)
    ecarts = nav.js_async("""const fini = arguments[arguments.length - 1];
      Promise.all([import('/js/pilotage/choregraphie.js'), fetch('/api/pilotage/choregraphies/exemple_kpop').then((r) => r.json())])
        .then(([C, r]) => { const v = window.vueRobot; const q = C.anglesVus(r.choregraphie, v.tChor).q;
          fini([v.tChor, Math.max(...Object.keys(q).map((n) => Math.abs(q[n] - v.qAffiche[n])))]); });""")
    assert ecarts[0] > 2.0 and ecarts[1] < 1e-6, ecarts
    _capture(nav, "4_choregraphie")
    nav.js("document.querySelector('.bouton-arret-pilotage').click()")
    # tablette en portrait : pas de défilement de côté, la vue et ARRÊT restent là
    nav._requete("POST", f"/session/{nav.session}/window/rect", {"width": 820, "height": 1180})
    time.sleep(1.0)
    largeurs = nav.js("return [document.documentElement.scrollWidth, window.innerWidth,"
                      " document.querySelector('.vue-robot-apercu').clientWidth]")
    assert largeurs[0] <= largeurs[1] and largeurs[2] > 200, largeurs
    rect = nav.js("const r = document.querySelector('.bouton-arret-pilotage').getBoundingClientRect();"
                  "return [r.top, r.bottom, window.innerHeight];")
    assert 0 <= rect[0] and rect[1] <= rect[2], rect
    _capture(nav, "5_tablette")
    # toutes les poses approchées dans les limites de l'URDF (moins 0,05 rad)
    r = nav.js_async(LIMITES)
    assert "erreur" not in r, r
    assert r["articulations"] >= 29 and r["manquent"] == [] and r["nombre"] == 0, r
    assert nav.js("return window.erreursAtelier") == []
