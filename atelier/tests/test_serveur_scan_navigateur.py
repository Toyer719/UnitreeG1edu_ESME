"""Parcours de l'onglet Scan dans un vrai navigateur sans fenêtre (Firefox par geckodriver) :
mode Robot sans câble (message clair) → mode Simulation → « Scan » → aperçu en direct (image,
trajectoire, compteurs, flèches au clavier) → « Fin » → progression → revue (éléments dessinés,
personne décochée, décocher une table) → « Ouvrir dans l'éditeur du monde » → onglet Monde.

Serveur : bin/g1-atelier, comme en vrai, sur une copie de demo, sans pont ROS 2, avec les fausses
commandes g1-* (g1-scan : test_serveur_scan_communs). Sauté si geckodriver ou Firefox manquent.
"""
import json
import shutil
import urllib.request

import pytest

from .test_serveur_communs import faux_bin, journaux, lieux  # noqa: F401
from .test_serveur_demarrage import serveur  # noqa: F401
from .test_serveur_navigateur import navigateur, sans_ros  # noqa: F401
from .test_serveur_scan_communs import faux_scan  # noqa: F401

pytestmark = pytest.mark.skipif(shutil.which("geckodriver") is None or shutil.which("firefox") is None,
                                reason="geckodriver ou Firefox absent")


@pytest.fixture
def scan_lent(monkeypatch):
    """Avant le serveur : traitement assez lent pour voir la progression, et pas de câble du robot."""
    monkeypatch.setenv("FAUX_SCAN_ETAPE_S", "1.5")
    monkeypatch.setenv("ATELIER_INTERFACE_ROBOT", "absente0")


def _api(base, chemin, corps=None):
    donnees = None if corps is None else json.dumps(corps).encode()
    req = urllib.request.Request(base + chemin, data=donnees, method="GET" if corps is None else "POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def _messages(nav, genre):
    return nav.js(f"return Array.from(document.querySelectorAll('.message-{genre}')).map(e => e.textContent)")


def test_onglet_scan_dans_le_navigateur(sans_ros, scan_lent, serveur, navigateur, lieux, faux_scan):
    _, base = serveur
    nav = navigateur
    _api(base, "/api/lieux/demo/etages/rdc/monde/generer", {})        # monde Gazebo de l'étage (faux g1-monde)

    nav.ouvrir(base + "/#lieux")
    nav.attendre("return document.querySelectorAll('#choix-lieu option').length > 1", message="liste des lieux")
    nav.js("const s = document.getElementById('choix-lieu'); s.value = 'demo'; s.dispatchEvent(new Event('change'));")
    nav.attendre("return document.getElementById('choix-etage').value === 'rdc'", message="lieu choisi")
    nav.bouton("Scan", ".onglets")
    nav.attendre("return document.querySelectorAll('.ecran-scan .scan-mode').length === 2", message="choix du mode")

    # Robot : les consignes du câble, puis un message clair sans câble
    nav.js("document.querySelector('.ecran-scan [data-mode=robot]').click()")
    consignes = nav.js("return document.querySelector('.ecran-scan [data-role=consignes]').textContent")
    assert "câble Ethernet" in consignes and "source ~/robot-g1/setup/robot.sh" in consignes
    assert "télécommande" in consignes and "derrière" in consignes
    assert nav.js("return document.querySelector('.ecran-scan [data-role=options]').textContent").startswith("Répétition")
    nav.js("window.confirm = () => true;")                # la confirmation du câble
    nav.bouton("Scan", ".ecran-scan")
    nav.attendre("return Array.from(document.querySelectorAll('.message-erreur')).some(m => "
                 "m.textContent.includes('Robot non détecté : branchez le câble'))", message="robot non détecté")
    nav.js("document.querySelectorAll('.message').forEach((m) => m.remove())")
    assert not [a for a in faux_scan.appels() if a.startswith("g1-scan")]

    # Simulation, pilotée aux flèches
    nav.js("document.querySelector('.ecran-scan [data-mode=simu]').click()")
    assert "Exploration automatique" in nav.js("return document.querySelector('.ecran-scan [data-role=options]').textContent")
    assert not nav.js("return document.querySelector('.ecran-scan [data-role=options] input[type=checkbox]').checked")
    nav.bouton("Scan", ".ecran-scan")
    nav.attendre("return document.querySelector('.ecran-scan .scan-vue-direct .bouton-fin')", message="scan en direct")
    assert any("--mode simu" in a for a in faux_scan.appels() if a.startswith("g1-scan demarrer"))
    # aperçu : image posée sur le plan, trajectoire, robot, compteurs qui avancent
    nav.attendre("const i = document.querySelector('.ecran-scan img.apercu-image'); "
                 "return i && i.complete && i.naturalWidth > 0", delai=20, message="image de l'aperçu")
    nav.attendre("return document.querySelector('.ecran-scan path.trajectoire-scan')", message="trajectoire")
    nav.attendre("return document.querySelector('.ecran-scan .leaflet-marker-icon.robot-direct')", message="robot")
    nav.attendre("return document.querySelector('[data-role=points]').textContent !== '—' && "
                 "document.querySelector('[data-role=distance]').textContent !== '0 m'", message="compteurs")
    maj = nav.js("return document.querySelector('.scan-vue-direct').dataset.apercu")
    nav.attendre("return document.querySelector('.scan-vue-direct').dataset.apercu !== arguments[0]", maj,
                 delai=10, message="aperçu rafraîchi")
    assert nav.js("return document.querySelector('[data-role=chrono]').textContent").count(":") == 1
    vue3d = nav.js("const n = document.querySelector('.ecran-scan [data-role=nuage]'); "
                   "return n.querySelector('canvas') ? 'canvas' : n.textContent")
    # flèche du clavier : la consigne part vers /api/simulation/teleop (ici sans ROS 2 : 503, dit une fois)
    nav.js("window.dispatchEvent(new KeyboardEvent('keydown', {key: 'ArrowUp'}));")
    assert nav.js("return document.querySelector('.teleop-bouton[data-commande=avancer]').classList.contains('appuye')")
    nav.attendre("return Array.from(document.querySelectorAll('.message-erreur')).some(m => "
                 "m.textContent.includes('ROS 2'))", message="téléopération sans ROS 2")
    nav.js("window.dispatchEvent(new KeyboardEvent('keyup', {key: 'ArrowUp'}));")
    assert not nav.js("return document.querySelector('.teleop-bouton.appuye')")
    assert len(_messages(nav, "erreur")) == 1, "l'erreur de la téléopération doit être dite une seule fois"
    nav.js("document.querySelectorAll('.message').forEach((m) => m.remove())")

    # « Fin » : progression du traitement, puis le résultat
    nav.bouton("Fin", ".ecran-scan")
    nav.attendre("return document.querySelector('.scan-vue-traitement .progression-barre')", delai=20,
                 message="progression du traitement")
    nav.attendre("const b = document.querySelector('.scan-vue-traitement .progression-barre'); "
                 "return b && parseFloat(b.style.width) >= 10 && "
                 "document.querySelector('.etape-scan.en-cours')", delai=20, message="barre qui avance")
    etape = nav.js("return document.querySelector('.etape-scan.en-cours').textContent")
    nav.attendre("return document.querySelectorAll('.ecran-scan .reco-ligne').length > 0", delai=30, message="revue")
    reco = _api(base, "/api/scan/sessions?lieu=demo")[0]
    assert reco["etat"] == "termine"
    ident = reco["id"]
    n_murs = nav.js("return document.querySelectorAll('.ecran-scan path.reco-mur').length")
    assert n_murs >= 18
    assert nav.js("return document.querySelectorAll('.ecran-scan path.reco-passage').length") == 5
    assert nav.js("return document.querySelectorAll('.ecran-scan .reco-table').length") == 2
    assert nav.js("return document.querySelector('.ecran-scan input[data-id=personne_b204]').checked") is False
    assert nav.js("return document.querySelector('.ecran-scan input[data-id=table_cdi]').checked") is True
    assert nav.js("return document.querySelectorAll('.ecran-scan .badge-douteux').length") >= 1
    # cliquer un nom le choisit sans changer sa case
    nav.js("document.querySelector('.ecran-scan input[data-id=table_cdi]').closest('label')"
           ".querySelector('.reco-nom').click()")
    assert nav.js("return document.querySelector('.ecran-scan input[data-id=table_cdi]').closest('label')"
                  ".classList.contains('choisi')")
    assert nav.js("return document.querySelector('.ecran-scan input[data-id=table_cdi]').checked") is True
    # décocher la table : enregistré tout seul
    nav.js("document.querySelector('.ecran-scan input[data-id=table_cdi]').click()")
    nav.attendre("return document.querySelector('[data-role=etat-choix]').textContent.startsWith('Choix enregistrés')",
                 message="choix enregistrés")
    r = _api(base, f"/api/scan/sessions/{ident}/reconnaissance?lieu=demo")
    assert next(o for o in r["reconnaissance"]["objets"] if o["id"] == "table_cdi")["a_garder"] is False
    # l'historique montre le scan
    nav.attendre("return document.querySelectorAll('.scan-sessions tr[data-session]').length === 1")
    assert "Terminé" in nav.js("return document.querySelector('.scan-sessions tr[data-session]').textContent")

    # « Ouvrir dans l'éditeur du monde » : adoption avec le monde, puis l'onglet Monde
    nav.bouton("Ouvrir dans l'éditeur du monde", ".ecran-scan")
    nav.attendre("return document.querySelector('.ecran-monde') && "
                 "document.querySelectorAll('.ecran-monde path.mur').length > 0", delai=30, message="onglet Monde")
    fiche = _api(base, "/api/lieux/demo")
    assert fiche["etages"][0]["source_carte"] == "scan"
    monde = _api(base, "/api/lieux/demo/etages/rdc/monde")
    ids = {o["id"] for o in monde["objets"]}
    assert "table_cdi" not in ids and "personne_b204" not in ids and "table_est" in ids
    assert any(m.get("source") == "scan" for m in monde["murs"])

    assert nav.js("return window.erreursAtelier") == []
    assert _messages(nav, "erreur") == []
    print(f"vue 3D du nuage : {vue3d} ; étape vue en cours : {etape}")


def test_fleches_repetees_puis_arret_dans_le_navigateur(sans_ros, serveur, navigateur):
    """js/teleop.js dans le navigateur, avec un faux fetch : la consigne repart toutes les 0,2 s tant
    que la touche est appuyée, les touches se combinent, et {0, 0, 0} part dès qu'on lâche."""
    _, base = serveur
    navigateur.ouvrir(base + "/")
    r = navigateur.js_async("""
        const fin = arguments[arguments.length - 1];
        const envois = [];
        window.fetch = (url, options) => {
          envois.push({t: performance.now(), url: url, corps: JSON.parse(options.body)});
          const c = JSON.parse(options.body);
          return Promise.resolve(new Response(JSON.stringify({envoye: c, ecoute: 1}), {status: 200}));
        };
        import('/js/teleop.js').then((T) => {
          const zone = document.createElement('div');
          document.body.appendChild(zone);
          const t = new T.Teleop(zone);
          t.activer();
          const touche = (genre, cle) => window.dispatchEvent(new KeyboardEvent(genre, {key: cle}));
          touche('keydown', 'ArrowUp');
          setTimeout(() => touche('keydown', 'q'), 300);
          setTimeout(() => { touche('keyup', 'ArrowUp'); touche('keyup', 'q'); }, 1000);
          setTimeout(() => {
            const n = envois.length;
            setTimeout(() => {
              t.detruire();
              fin({envois: envois, apres: envois.length - n, periode: T.PERIODE_TELEOP, vitesses: T.VITESSES,
                   texte: T.texteConsigne({vx: 0.4, vy: 0, wz: -0.6})});
            }, 700);
          }, 1100);
        }).catch((e) => fin({erreur: String(e)}));""")
    assert "erreur" not in r, r
    envois = r["envois"]
    assert all(e["url"] == "/api/simulation/teleop" for e in envois)
    corps = [(e["corps"]["vx"], e["corps"]["vy"], e["corps"]["wz"]) for e in envois]
    avant = [c for c, e in zip(corps, envois) if e["t"] - envois[0]["t"] < 280]
    assert avant and all(c == (0.4, 0, 0) for c in avant), corps
    assert (0.4, 0.2, 0) in corps                                   # flèche du haut + Q : avance et pas à gauche
    assert corps[-1] == (0, 0, 0) and r["apres"] == 0               # arrêt envoyé, puis plus rien
    assert 6 <= len([c for c in corps if c != (0, 0, 0)]) <= 8      # environ 1 s à 0,2 s d'intervalle
    ecarts = [b["t"] - a["t"] for a, b in zip(envois, envois[1:-1]) if a["corps"] == b["corps"]]
    assert ecarts and max(ecarts) < 450, ecarts                     # toujours sous les 0,5 s de l'homme mort
    assert r["periode"] == 200 and r["vitesses"] == {"vx": 0.4, "vy": 0.2, "wz": 0.6}
    assert r["texte"] == "avance à 0,4 m/s, tourne à droite à 0,6 rad/s"
