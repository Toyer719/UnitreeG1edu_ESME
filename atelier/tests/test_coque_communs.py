"""Outils communs des essais de la coque dans un vrai navigateur (vague 5, section 12.2 et critère 31 du plan) :
agent Coquille. Ils servent à atelier/tests/test_coque_navigateur.py (essai court, pytest) et à
tests_e2e/outils_coque_e2e.py (critère 31 complet : trois tailles de fenêtre, tous les onglets et toutes les
commandes). Ce fichier ne contient aucun test.

- installer_espions(nav) : remplace window.confirm, alert et prompt (aucune boîte native ne doit s'ouvrir) et
  note chaque appel à fetch (méthode et adresse), pour vérifier par exemple que l'ARRÊT envoie POST /api/arret ;
- mesurer(nav) : dans la page, la page ne défile pas (scrollWidth et scrollHeight au plus la fenêtre, à 1 px
  près) ; barre d'outils, ruban, arbre, vue, panneau et barre d'état sont entiers dans la fenêtre ; chaque
  élément cliquable visible (button, input, select, textarea, a[href], summary) de la barre d'outils, du ruban,
  de l'arbre, du panneau et de la barre flottante de la vue, amené à l'écran par scrollIntoView, y est entier
  (dans la fenêtre et dans chaque cadre qui coupe ce qui déborde) et non recouvert (elementFromPoint en son
  centre le rend, ou un de ses enfants) ; aucun cadre qui ne défile pas (overflow hidden) n'a dû défiler pour
  le montrer ; ARRÊT visible et non recouvert ;
- parcours_accueil, parcours_anciens_hash, parcours_theme, parcours_arret : les parcours du critère 31 et la
  partie navigateur du critère 36 (assert avec un message en français ; chacun renvoie ce qu'il a vu) ;
- balayer(nav, etiquette) : mesurer pour chaque onglet du ruban, puis pour chaque commande qui n'est pas
  Avancé (les actions qui lancent quelque chose, comme « Lancer » ou « Scan », sont mesurées dans l'état de
  leur onglet, sans être déclenchées ; les menus sont ouverts puis refermés ; les cases cochées puis
  décochées).
"""
import time

# Commandes du ruban qui déclenchent une action (lancer Gazebo, un scan, prendre la main…) : le balayage ne
# les clique pas (leur bouton est mesuré avec le reste du ruban)
ACTIONS = {"lancer", "arreter", "reperer", "bloquer", "debloquer", "main", "utiliser", "scan", "fin", "refaire"}

ESPIONS = """
if (!window.espionsCoque) {
  window.espionsCoque = { fenetres: [], requetes: [] };
  ['confirm', 'alert', 'prompt'].forEach((nom) => {
    window[nom] = function (texte) {
      window.espionsCoque.fenetres.push(nom + ' : ' + String(texte).slice(0, 120));
      return nom === 'confirm' ? false : null;
    };
  });
  const fetchAvant = window.fetch.bind(window);
  window.fetch = function (ressource, init) {
    const url = typeof ressource === 'string' ? ressource : (ressource && ressource.url) || String(ressource);
    const methode = ((init && init.method) || (ressource && ressource.method) || 'GET').toUpperCase();
    let corps = null;
    try {
      corps = init && typeof init.body === 'string' ? JSON.parse(init.body) : null;
    } catch (e) {
      corps = null;
    }
    window.espionsCoque.requetes.push({ methode: methode, url: url, corps: corps, t: Date.now() });
    return fetchAvant(ressource, init);
  };
}
return true;
"""

PRET = """
return !!document.querySelector('[data-role=espace]')
  && !document.querySelector('.chargement-panneau')
  && !document.querySelector('[data-role=vue-plan].chargement');
"""

MESURE = r"""
const iw = window.innerWidth;
const ih = window.innerHeight;
const de = document.documentElement;
const corps = document.body;
const fautes = [];
let verifies = 0;

function nom(e) {
  if (!e) return 'rien';
  if (e.nodeType !== 1) e = e.parentElement;
  if (!e) return 'rien';
  const attributs = ['data-commande', 'data-role', 'data-onglet', 'data-noeud', 'data-vue', 'data-cadrage',
    'data-calque', 'data-section', 'data-valeur', 'data-verif'];
  let n = e.tagName.toLowerCase();
  for (const a of attributs) {
    if (e.getAttribute(a)) {
      n += '[' + a + '=' + e.getAttribute(a) + ']';
      break;
    }
  }
  if (n === e.tagName.toLowerCase() && e.className && typeof e.className === 'string') n += '.' + e.className.split(' ')[0];
  const t = (e.textContent || e.value || e.getAttribute('aria-label') || e.title || '').trim().replace(/\s+/g, ' ').slice(0, 40);
  return t ? n + ' « ' + t + ' »' : n;
}

function cache(e) {
  // dans un <details> fermé, hors de son propre <summary> (à n'importe quel niveau) : pas affiché
  for (let d = e.closest('details'); d; d = d.parentElement ? d.parentElement.closest('details') : null) {
    const s = e.closest('summary');
    if (!d.open && !(s && s.parentElement === d)) return true;
  }
  for (let x = e; x && x.nodeType === 1; x = x.parentElement) {
    const s = getComputedStyle(x);
    if (s.display === 'none' || s.visibility === 'hidden' || s.visibility === 'collapse') return true;
    if (parseFloat(s.opacity) < 0.05) return true;
  }
  const r = e.getBoundingClientRect();
  return r.width < 1 || r.height < 1;
}

// zone où e peut se voir : la fenêtre, réduite par chaque ancêtre qui coupe ce qui déborde
function cadre(e) {
  let c = { l: 0, t: 0, r: iw, b: ih };
  for (let x = e; x && x !== de && x !== corps; x = x.parentElement) {
    const s = getComputedStyle(x);
    if (x !== e && !(s.overflowX === 'visible' && s.overflowY === 'visible')) {
      const r = x.getBoundingClientRect();
      const l = r.left + x.clientLeft;
      const t = r.top + x.clientTop;
      c = { l: Math.max(c.l, l), t: Math.max(c.t, t), r: Math.min(c.r, l + x.clientWidth), b: Math.min(c.b, t + x.clientHeight) };
    }
    if (s.position === 'fixed') break;
  }
  return c;
}

function recouvert(e, r) {
  const x = Math.min(Math.max(r.left + r.width / 2, 0), iw - 1);
  const y = Math.min(Math.max(r.top + r.height / 2, 0), ih - 1);
  const t = document.elementFromPoint(x, y);
  return t === e || (t && e.contains(t)) ? null : t;
}

function arrondi(r) {
  return [r.left, r.top, r.right, r.bottom].map((v) => Math.round(v)).join(', ');
}

// 1. la page ne défile jamais
const sw = Math.max(de.scrollWidth, corps.scrollWidth);
const sh = Math.max(de.scrollHeight, corps.scrollHeight);
if (sw > iw + 1 || sh > ih + 1) fautes.push('la page déborde : ' + sw + ' × ' + sh + ' px pour une fenêtre de ' + iw + ' × ' + ih);

// 2. les six zones de l'espace de travail, entières dans la fenêtre
const espace = document.querySelector('[data-role=espace]');
if (!espace) return { fautes: ['pas d\'espace de travail'], verifies: 0, page: [sw, sh, iw, ih] };
const plein = espace.classList.contains('plein-ecran');
const replie = espace.classList.contains('arbre-replie');
const etroit = iw < 1100;
const zones = [['barre d\'outils', '[data-role=barre-outils]'], ['ruban', '[data-role=ruban]'],
  ['arbre', '.espace .centre > .arbre'], ['vue', '[data-role=vue]'], ['panneau', '[data-role=panneau]'],
  ['barre d\'état', '[data-role=barre-etat]']];
for (const z of zones) {
  const e = document.querySelector(z[1]);
  const tiroir = (z[0] === 'arbre' || z[0] === 'panneau') && etroit && !espace.classList.contains('tiroir-' + z[0]);
  const facultative = (plein && ['ruban', 'arbre', 'panneau'].indexOf(z[0]) >= 0) || (z[0] === 'arbre' && replie) || tiroir;
  if (!e) {
    fautes.push(z[0] + ' absent');
    continue;
  }
  if (cache(e)) {
    if (!facultative) fautes.push(z[0] + ' caché ou de taille nulle');
    continue;
  }
  const r = e.getBoundingClientRect();
  if (r.left < -1 || r.top < -1 || r.right > iw + 1 || r.bottom > ih + 1) fautes.push(z[0] + ' sort de la fenêtre (' + arrondi(r) + ')');
  if (r.height < 20 && z[0] !== 'barre d\'état') fautes.push(z[0] + ' écrasé : ' + Math.round(r.height) + ' px de haut');
}

// 3. chaque élément cliquable visible : amené à l'écran, entier et non recouvert
const conteneurs = ['[data-role=barre-outils]', '[data-role=ruban]', '.espace .centre > .arbre', '[data-role=panneau]',
  '[data-role=barre-vue]'];
const tiroirOuvert = espace.classList.contains('tiroir-arbre') || espace.classList.contains('tiroir-panneau');
for (const sel of conteneurs) {
  const z = document.querySelector(sel);
  if (!z || cache(z)) continue;
  if (tiroirOuvert && sel === '[data-role=barre-vue]') continue;      // derrière le voile du tiroir, exprès
  const elements = Array.from(z.querySelectorAll('button, input:not([type=hidden]), select, textarea, a[href], summary'));
  for (const e of elements) {
    if (cache(e)) continue;
    verifies += 1;
    e.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    const r = e.getBoundingClientRect();
    const c = cadre(e);
    if (r.left < c.l - 1 || r.top < c.t - 1 || r.right > c.r + 1 || r.bottom > c.b + 1) {
      fautes.push(nom(e) + ' coupé : ' + arrondi(r) + ' pour une zone visible de ' + arrondi({ left: c.l, top: c.t, right: c.r, bottom: c.b }));
      continue;
    }
    const t = recouvert(e, r);
    if (t) fautes.push(nom(e) + ' recouvert par ' + nom(t));
  }
}

// 4. un cadre qui ne défile pas (overflow hidden) a dû défiler pour montrer un élément : il est hors d'atteinte
for (const x of espace.querySelectorAll('*')) {
  if (x.scrollTop < 0.5 && x.scrollLeft < 0.5) continue;
  const s = getComputedStyle(x);
  const coupeY = s.overflowY === 'hidden' || s.overflowY === 'clip';
  const coupeX = s.overflowX === 'hidden' || s.overflowX === 'clip';
  if ((coupeY && x.scrollTop >= 0.5) || (coupeX && x.scrollLeft >= 0.5)) {
    if (x.closest('.leaflet-container, canvas, [data-role=vue-3d]')) continue;     // cartes et vues : leur affaire
    fautes.push(nom(x) + ' cache une partie de son contenu (overflow hidden, défilé de ' + Math.round(x.scrollLeft) + ', '
      + Math.round(x.scrollTop) + ' px)');
    x.scrollTop = 0;
    x.scrollLeft = 0;
  }
}
const racines = [de, corps, document.getElementById('atelier'), espace].filter((x) => x);
if (window.scrollX > 0.5 || window.scrollY > 0.5 || racines.some((x) => x.scrollTop > 0.5 || x.scrollLeft > 0.5)) {
  fautes.push('la page a défilé (' + racines.map((x) => Math.round(x.scrollLeft) + ',' + Math.round(x.scrollTop)).join(' ; ') + ')');
  racines.forEach((x) => { x.scrollTop = 0; x.scrollLeft = 0; });
}

// 5. ARRÊT visible et cliquable partout
const a = document.querySelector('[data-role=arret]');
if (!a || cache(a)) {
  fautes.push('ARRÊT absent ou caché');
} else {
  const r = a.getBoundingClientRect();
  if (r.left < 0 || r.top < 0 || r.right > iw || r.bottom > ih) fautes.push('ARRÊT sort de la fenêtre (' + arrondi(r) + ')');
  const t = recouvert(a, r);
  if (t) fautes.push('ARRÊT recouvert par ' + nom(t));
}
return { fautes: fautes, verifies: verifies, page: [sw, sh, iw, ih] };
"""

# Commandes d'un onglet, d'après le registre du ruban (js/coque/ruban.js)
REGISTRE = """
const [mode, onglet, fini] = arguments;
import('/js/coque/ruban.js').then((R) => {
  fini(R.commandesDe(mode, onglet).map((c) => ({ id: c.id, commande: c.commande, avance: !!c.avance,
    case: !!c.case, menu: c.menu ? (c.menu === 'dynamique' ? 'dynamique' : 'liste') : null })));
}).catch((e) => fini({ erreur: String(e) }));
"""

CLIC_COMMANDE = """
const [id] = arguments;
const b = document.querySelector('.ruban-commandes [data-commande="' + id + '"]');
if (!b) return 'absente';
if (b.disabled) return 'grisée';
b.click();
return 'ok';
"""

# Ouvre (vrai) ou ferme (faux) un tiroir des écrans étroits (bouton de la barre d'outils)
TIROIR = """
const [quoi, ouvrir] = arguments;
const espace = document.querySelector('[data-role=espace]');
const ouvert = espace.classList.contains('tiroir-' + quoi);
if (ouvert !== ouvrir) document.querySelector('[data-role=basculer-' + quoi + ']').click();
return espace.classList.contains('tiroir-' + quoi);
"""

FERMER_MENUS = """
const m = document.querySelectorAll('.menu-ruban');
if (m.length) document.body.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }));
document.querySelectorAll('.menu-ruban').forEach((x) => x.remove());
return m.length;
"""


def installer_espions(nav):
    """Aucune boîte native (confirm, alert, prompt) ; chaque fetch noté. À refaire après chaque chargement."""
    nav.js(ESPIONS)


def fenetres_natives(nav):
    """Les boîtes natives demandées par la page depuis installer_espions (doit rester vide)."""
    return nav.js("return window.espionsCoque ? window.espionsCoque.fenetres : []")


def requetes(nav, methode=None, debut=None):
    """Les fetch notés : [{methode, url, corps, t}], filtrés par méthode et adresse (début)."""
    liste = nav.js("return window.espionsCoque ? window.espionsCoque.requetes : []") or []
    return [r for r in liste if (methode is None or r["methode"] == methode)
            and (debut is None or r["url"].split("?")[0].endswith(debut) or r["url"].startswith(debut))]


def attendre_pret(nav, delai=30.0, pause=0.35):
    """L'écran ouvert a fini de se charger (plus de « Chargement… ») ; puis une courte pause pour la mise en page."""
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        if nav.js(PRET):
            time.sleep(pause)
            return True
        time.sleep(0.15)
    return False


def mesurer(nav):
    """{fautes: [...], verifies: nombre d'éléments cliquables vérifiés, page: [sw, sh, iw, ih]}."""
    return nav.js(MESURE)


def mode_ruban(nav):
    mode = nav.js("const e = document.querySelector('[data-role=espace]'); return e ? e.getAttribute('data-mode') : null")
    return "simu" if mode == "simu" else "reel"


def onglets(nav):
    return nav.js("return Array.from(document.querySelectorAll('[data-onglet]')).map((b) => b.dataset.onglet)")


def commandes(nav, onglet):
    """Les commandes de l'onglet d'après le registre du ruban (mode de l'espace ouvert)."""
    liste = nav.js_async(REGISTRE, mode_ruban(nav), onglet)
    if isinstance(liste, dict):
        raise RuntimeError(f"registre du ruban illisible : {liste.get('erreur')}")
    return liste


def balayer(nav, etiquette, avec_commandes=True, journal=None):
    """Mesure chaque onglet du ruban, puis (avec_commandes) chaque commande qui n'est pas Avancé.
    Renvoie (fautes, nombre de mesures, nombre d'éléments vérifiés)."""
    fautes = []
    mesures = 0
    elements = 0

    def noter(ou, resultat):
        nonlocal mesures, elements
        mesures += 1
        elements += resultat["verifies"]
        fautes.extend(f"{etiquette} › {ou} : {f}" for f in resultat["fautes"])

    for o in onglets(nav):
        assert nav.js("const b = document.querySelector('[data-onglet=\"' + arguments[0] + '\"]'); if (!b) return false;"
                      "b.click(); return true;", o), f"onglet {o} introuvable"
        if not attendre_pret(nav):
            fautes.append(f"{etiquette} › {o} : l'écran de l'onglet ne finit pas de se charger")
            continue
        noter(o, mesurer(nav))
        if nav.js("return window.innerWidth") < 1100:
            # écran étroit : l'arbre et le panneau sont des tiroirs ; on mesure aussi leur contenu, ouverts
            for tiroir in ("arbre", "panneau"):
                nav.js(TIROIR, tiroir, True)
                time.sleep(0.35)
                noter(f"{o} › tiroir {tiroir}", mesurer(nav))
                nav.js(TIROIR, tiroir, False)
                time.sleep(0.25)
        if not avec_commandes:
            continue
        for c in commandes(nav, o):
            if c["avance"] or c["commande"] in ACTIONS:
                continue
            if nav.js(CLIC_COMMANDE, c["id"]) != "ok":
                continue
            attendre_pret(nav)
            nav.js(FERMER_MENUS)               # un menu ouvert recouvre ce qui est dessous : on le ferme d'abord
            noter(f"{o} › {c['id']}", mesurer(nav))
            if c["case"]:
                nav.js(CLIC_COMMANDE, c["id"])         # la case reprend son état
                attendre_pret(nav, pause=0.1)
        if journal:
            journal(f"{etiquette} › {o} : {mesures} mesures, {len(fautes)} fautes")
    return fautes, mesures, elements


# ---------------------------------------------------------------- parcours (pytest et critère 31)
# Chaque parcours vérifie par assert (message en français) et renvoie une phrase qui dit ce qui a été vu.

ONGLETS_ATTENDUS = {"simu": ["dessiner", "placer", "simuler", "equipe"],
                    "reel": ["scanner", "placer", "naviguer", "piloter", "equipe"]}
ANCIENS_HASH = {"salles": "salles", "simulation": "simulation", "scan": "scan", "pilotage": "pilotage",
                "camera": "camera"}
ACCUEIL = "return !!document.querySelector('[data-role=accueil]')"
ESPACE = "return !!document.querySelector('[data-role=espace]')"
DERNIER_ARRET = """const l = ((window.espionsCoque || {}).requetes || []).filter((x) => x.methode === 'POST'
  && x.url.split('?')[0].endsWith(arguments[1]));
return l.length > arguments[0] ? l[l.length - 1] : null;"""


def lire_json(base, chemin):
    """GET base + chemin, en JSON."""
    import json
    import urllib.request
    with urllib.request.urlopen(base + chemin, timeout=20) as r:
        return json.loads(r.read())


def charger(nav, url, attente, message):
    """Ouvre l'adresse, attend la condition (script), puis pose les espions."""
    nav.ouvrir(url)
    nav.attendre(attente, delai=30.0, message=message)
    installer_espions(nav)


def ouvrir_espace(nav, base, mode, lieu="demo", etage="rdc", hash_="", memoire=None):
    """L'espace de travail du mode (simu, reel, repetition), par la mémoire du navigateur puis ?recharger."""
    charger(nav, base + "/", ACCUEIL, "accueil")
    nav.js("localStorage.clear(); localStorage.setItem('atelier.lieu', arguments[0]);"
           "localStorage.setItem('atelier.etage', arguments[1]);"
           "localStorage.setItem('atelier.mode', arguments[2] === 'simu' ? 'simu' : 'reel');"
           "localStorage.setItem('atelier.repetition', arguments[2] === 'repetition' ? '1' : '0');"
           "Object.keys(arguments[3] || {}).forEach((k) => localStorage.setItem(k, arguments[3][k]));",
           lieu, etage, mode, memoire or {})
    charger(nav, base + "/?recharger=1" + hash_, ESPACE, "espace de travail")
    assert attendre_pret(nav), f"l'espace de travail ({mode}) ne finit pas de se charger"


def parcours_accueil(nav, base, cable_attendu=None):
    """L'accueil : Simulation + demo + Ouvrir, puis Robot réel (vérifications) et la répétition."""
    charger(nav, base + "/", ACCUEIL, "accueil")
    nav.js("localStorage.clear(); localStorage.setItem('atelier.lieu', 'demo');")
    charger(nav, base + "/", "return !!document.querySelector('[data-role=liste-lieux] [data-lieu=demo]')",
            "le demo dans la liste des lieux")
    assert nav.js("return !!document.querySelector('[data-role=mode-simu]') && "
                  "!!document.querySelector('[data-role=mode-reel]') && !!document.querySelector('[data-role=ouvrir]')"), \
        "il manque une carte (Simulation, Robot réel) ou le bouton Ouvrir"
    assert nav.js("return document.querySelector('[data-lieu=demo]').getAttribute('aria-selected')") == "true", \
        "le demo (atelier.lieu) n'est pas présélectionné"
    nav.clic("[data-role=mode-simu]")
    assert nav.js("return document.querySelector('[data-role=mode-simu]').getAttribute('aria-pressed')") == "true", \
        "la carte Simulation ne se choisit pas"
    nav.clic("[data-role=ouvrir]")
    nav.attendre("return !!document.querySelector('[data-role=espace][data-mode=simu]')", message="espace Simulation")
    attendre_pret(nav)
    vus = onglets(nav)
    assert vus == ONGLETS_ATTENDUS["simu"], f"onglets de la Simulation : {vus}"
    pilotage = [c["id"] for o in vus for c in commandes(nav, o) if c["id"].startswith("pilotage.")]
    pilotage += nav.js("return Array.from(document.querySelectorAll('[data-commande^=\"pilotage.\"]'))"
                       ".map((b) => b.dataset.commande)")
    assert not pilotage, f"des commandes pilotage.* en Simulation : {pilotage}"
    vu = [f"Simulation + demo + Ouvrir : [data-mode=simu], onglets {', '.join(vus)}, aucune commande pilotage.*"]

    nav.clic("[data-role=accueil-retour]")
    nav.attendre("return !!document.querySelector('[data-role=accueil] [data-role=liste-lieux] [data-lieu=demo]')",
                 message="retour à l'accueil")
    nav.clic("[data-role=mode-reel]")
    etats = nav.attendre("""const l = Array.from(document.querySelectorAll('[data-role=verifications] [data-verif]'));
        if (!l.length || l.some((v) => !v.getAttribute('data-etat'))) return null;
        const detail = (v) => (v.querySelector('.verification-detail') || {}).textContent;
        if (l.some((v) => detail(v) === 'vérification en cours…')) return null;
        return l.map((v) => [v.getAttribute('data-verif'), v.getAttribute('data-etat')]);""",
                         delai=10.0, message="résultat des vérifications du Réel")
    noms = [e[0] for e in etats]
    assert noms == ["ros", "cable", "robot", "telecommande"], f"vérifications du Réel : {noms}"
    assert all(e[1] in ("ok", "non", "inconnu") for e in etats), f"data-etat des vérifications : {etats}"
    if cable_attendu is not None:
        assert dict(etats)["cable"] == cable_attendu, f"vérification du câble : {dict(etats)['cable']} ({cable_attendu} attendu)"
    vu.append("Robot réel : vérifications " + ", ".join(f"{n} = {e}" for n, e in etats))
    nav.clic("[data-role=repetition]")
    restes = nav.attendre("""const c = document.querySelector('[data-role=repetition]');
        if (!c || !c.checked) return null;
        return Array.from(document.querySelectorAll('[data-role=verifications] [data-verif]')).map((v) => v.getAttribute('data-verif'));""",
                          message="case « Répétition sans robot » cochée")
    assert "cable" not in restes and "robot" not in restes, f"en répétition, vérifications sans objet encore là : {restes}"
    nav.clic("[data-role=ouvrir]")
    nav.attendre("return !!document.querySelector('[data-role=espace][data-mode=repetition]')", message="espace Répétition")
    attendre_pret(nav)
    vus = onglets(nav)
    assert vus == ONGLETS_ATTENDUS["reel"], f"onglets du Réel (répétition) : {vus}"
    assert nav.js("return localStorage.getItem('atelier.mode') === 'reel' && localStorage.getItem('atelier.repetition') === '1'"
                  " && localStorage.getItem('atelier.mode-simulation') === 'repetition'"), "mode non retenu (atelier.mode…)"
    fenetres = fenetres_natives(nav)
    assert not fenetres, f"boîtes natives ouvertes : {fenetres}"
    vu.append(f"Répétition sans robot : [data-mode=repetition], onglets {', '.join(vus)}, vérifications {restes}, "
              "aucune boîte native")
    return vu


def parcours_anciens_hash(nav, base):
    for h, ecran in ANCIENS_HASH.items():
        mode = "repetition" if h in ("pilotage", "camera", "scan") else "simu"
        ouvrir_espace(nav, base, mode)
        charger(nav, base + "/?recharger=1#" + h, f"return !!document.querySelector('[data-ecran={ecran}]')", f"#{h}")
        assert attendre_pret(nav), f"#{h} : l'écran ne finit pas de se charger"
        assert not nav.js(ACCUEIL), f"#{h} : l'accueil s'affiche"
    return "anciennes adresses : " + ", ".join(f"#{h} → [data-ecran={e}]" for h, e in ANCIENS_HASH.items()) + ", sans l'accueil"


def parcours_theme(nav, base):
    ouvrir_espace(nav, base, "simu")
    avant = nav.js("return [document.documentElement.getAttribute('data-theme'), localStorage.getItem('atelier.theme')]")
    assert avant[0] == "sombre" and avant[1] in (None, "sombre"), f"thème au départ : {avant} (sombre attendu)"
    fond = "return getComputedStyle(document.querySelector('[data-role=vue-3d]')).backgroundColor"
    fond_sombre = nav.js(fond)
    nav.clic("[data-role=theme]")
    apres = nav.attendre("const t = document.documentElement.getAttribute('data-theme');"
                         "return t === 'clair' ? [t, localStorage.getItem('atelier.theme')] : null", message="thème clair")
    assert apres[1] == "clair", f"atelier.theme vaut {apres[1]} après le passage au clair"
    page = nav.js("return getComputedStyle(document.body).backgroundColor")
    fond_clair = nav.js(fond)
    assert fond_clair == fond_sombre == "rgb(30, 30, 30)", \
        f"la vue 3D doit rester sombre (#1e1e1e) : {fond_sombre} puis {fond_clair}"
    charger(nav, base + "/?recharger=1", ESPACE, "rechargement")
    assert nav.js("return document.documentElement.getAttribute('data-theme')") == "clair", \
        "le thème clair n'est pas gardé au rechargement"
    nav.clic("[data-role=theme]")
    nav.attendre("return document.documentElement.getAttribute('data-theme') === 'sombre' && "
                 "localStorage.getItem('atelier.theme') === 'sombre'", message="retour au thème sombre")
    return (f"thème : clair (data-theme, atelier.theme, fond de page {page}), gardé au rechargement, puis sombre ; "
            f"vue 3D toujours sombre ({fond_clair})")


def parcours_arret(nav, base, mode, lieu="demo", verrou=False):
    """Le clic sur ARRÊT et la touche Échap envoient POST /api/arret {mode} ; avec verrou (Réel ou répétition,
    pont ROS 2 en marche), le bouton passe ensuite à « Débloquer » (data-etat=bloque)."""
    ouvrir_espace(nav, base, mode, lieu=lieu)
    vu = []
    for geste in ("clic", "Échap"):
        avant = len(requetes(nav, "POST", "/api/arret"))
        if geste == "clic":
            nav.clic("[data-role=arret]")
        else:
            nav.js("document.body.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true, cancelable: true}))")
        r = nav.attendre(DERNIER_ARRET, avant, "/api/arret", delai=5.0, message=f"POST /api/arret après {geste}")
        assert (r.get("corps") or {}).get("mode") == mode, f"{geste} : corps de l'ARRÊT {r.get('corps')} ({mode} attendu)"
        # la réponse est arrivée (un second appui pendant qu'un ARRÊT part encore ne renvoie rien de plus)
        nav.attendre("return !document.querySelector('[data-role=arret].appuye')", delai=5.0, message="réponse de l'ARRÊT")
        vu.append(f"{geste} → POST /api/arret {r.get('corps')}")
        if geste == "clic" and verrou and mode != "simu":
            etat = nav.attendre("const b = document.querySelector('[data-role=arret]');"
                                "return b.getAttribute('data-etat') === 'bloque' ? b.textContent.trim() : null",
                                delai=5.0, message="bouton « Débloquer » (data-etat=bloque)")
            assert "Débloquer" in etat, f"texte du bouton bloqué : {etat}"
            vu.append(f"bouton « {etat} » (data-etat=bloque)")
    assert not fenetres_natives(nav), f"boîtes natives : {fenetres_natives(nav)}"
    return vu


# ---------------------------------------------------------------- contrastes affichés

CONTRASTES = r"""
// Chaque élément visible qui porte du texte : couleur calculée du texte sur son fond réel (fonds composés
// jusqu'au premier fond opaque ; un dégradé ou une image : fond inconnu, ignoré). Seuil WCAG AA : 4,5:1,
// 3:1 pour le grand texte (24 px, ou 18,66 px gras). Les commandes désactivées sont exemptées (WCAG).
// Ignorés : la vue 3D et la caméra (toile), les cartes Leaflet sans fond propre.
function rgba(s) {
  const m = /rgba?\(([^)]+)\)/.exec(s || '');
  if (!m) return null;
  const p = m[1].split(',').map((x) => parseFloat(x));
  return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1];
}
function sur(h, b) {
  const a = h[3];
  return [h[0] * a + b[0] * (1 - a), h[1] * a + b[1] * (1 - a), h[2] * a + b[2] * (1 - a), 1];
}
function luminance(c) {
  const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
  return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]);
}
function rapport(a, b) {
  const x = luminance(a);
  const y = luminance(b);
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
}
function fond(e) {
  const couches = [];
  for (let x = e; x && x.nodeType === 1; x = x.parentElement) {
    const s = getComputedStyle(x);
    if (s.backgroundImage && s.backgroundImage !== 'none') return null;
    const c = rgba(s.backgroundColor);
    if (c && c[3] > 0.01) {
      couches.push(c);
      if (c[3] >= 0.99) break;
    }
  }
  let f = rgba(getComputedStyle(document.body).backgroundColor) || [255, 255, 255, 1];
  for (let i = couches.length - 1; i >= 0; i -= 1) f = sur(couches[i], f);
  return f;
}
function nom(e) {
  let n = e.tagName.toLowerCase();
  for (const a of ['data-role', 'data-commande', 'data-onglet', 'data-noeud', 'data-section', 'data-verif']) {
    if (e.getAttribute(a)) return n + '[' + a + '=' + e.getAttribute(a) + ']';
  }
  if (typeof e.className === 'string' && e.className) n += '.' + e.className.trim().split(/\s+/).join('.');
  const p = e.parentElement;
  return (p && typeof p.className === 'string' && p.className ? '.' + p.className.trim().split(/\s+/)[0] + ' > ' : '') + n;
}
const vus = {};
const faibles = [];
let mesures = 0;
for (const e of document.querySelectorAll('body *')) {
  if (['SCRIPT', 'STYLE', 'svg', 'path', 'CANVAS', 'OPTION'].indexOf(e.tagName) >= 0) continue;
  const texte = Array.from(e.childNodes).filter((n) => n.nodeType === 3).map((n) => n.textContent).join('').trim();
  if (!texte) continue;
  if (e.closest('[data-role=vue-3d], [data-role=vue-camera], .camera-vue, canvas')) continue;
  if (e.closest('button:disabled, input:disabled, select:disabled, textarea:disabled, fieldset:disabled, .desactive')) continue;
  const r = e.getBoundingClientRect();
  if (r.width < 1 || r.height < 1 || r.bottom < 0 || r.top > window.innerHeight) continue;
  let opacite = 1;
  let cache = false;
  for (let x = e; x && x.nodeType === 1; x = x.parentElement) {
    const s = getComputedStyle(x);
    if (s.display === 'none' || s.visibility === 'hidden') { cache = true; break; }
    opacite *= parseFloat(s.opacity);
  }
  if (cache || opacite < 0.05) continue;
  const s = getComputedStyle(e);
  const f = fond(e);
  if (!f) continue;
  const c = rgba(s.color);
  if (!c) continue;
  const texteVu = sur([c[0], c[1], c[2], c[3] * opacite], f);
  const taille = parseFloat(s.fontSize);
  const gras = parseInt(s.fontWeight, 10) >= 700;
  const seuil = taille >= 24 || (taille >= 18.66 && gras) ? 3.0 : 4.5;
  const k = rapport(texteVu, f);
  mesures += 1;
  if (k + 0.005 < seuil) {
    const cle = nom(e) + '|' + s.color + '|' + f.map(Math.round).join(',');
    if (vus[cle]) continue;
    vus[cle] = true;
    faibles.push(nom(e) + ' « ' + texte.slice(0, 30) + ' » : ' + k.toFixed(2) + ':1 (seuil ' + seuil + ', texte '
      + s.color + ', fond rgb(' + f.slice(0, 3).map(Math.round).join(', ') + ')' + (opacite < 1 ? ', opacité ' + opacite.toFixed(2) : '') + ')');
  }
}
return { faibles: faibles, mesures: mesures };
"""


def contrastes(nav):
    """{faibles: [...], mesures: n} : les textes affichés sous le seuil AA, dans l'état actuel de la page."""
    return nav.js(CONTRASTES)
