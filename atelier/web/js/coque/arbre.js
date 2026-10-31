// Arbre du lieu (FeatureManager de SolidWorks) : Lieu ▸ Étage ▸ Carte, Monde, Points (★ Accueil
// d'abord), Itinéraires, Zones, Scans, Équipe ; pastilles ⚠ de « Vérifier le lieu » (vague 5,
// section 12.2 du plan). Module de l'agent Coquille.
//
// construireArbre(element, {lieu, etage, mode, surChoix({genre, id}), surDoubleClic({genre, id})})
//   → {rafraichir(), choisir(genre, id), detruire()}
// Repères : [data-role=arbre] ; chaque nœud porte data-noeud="<genre>:<id>" (lieu:demo, etage:rdc,
// carte:rdc, monde:rdc, salle:b204, noeud:c1, couloir:3, zone:interdite:0, scan:2026-10-27_14h22,
// equipe:camera) ; [data-alerte] sur les nœuds cités par GET /api/lieux/{id}/verification.

import { api, urlEtage, urlLieu } from '../api.js';
import { sallesDansLOrdre } from '../carte3d/geometrie3d.js';
import { icone } from './icones.js';

function el(balise, classe, texte) {
  const e = document.createElement(balise);
  if (classe) e.className = classe;
  if (texte !== undefined && texte !== null) e.textContent = texte;
  return e;
}

async function lire(url, defaut) {
  try {
    return await api.lire(url);
  } catch (e) {
    return defaut;
  }
}

function dateCourte(secondes) {
  if (!secondes) return '';
  const d = new Date(secondes * 1000);
  const z = (n) => ('0' + n).slice(-2);
  return z(d.getDate()) + '/' + z(d.getMonth() + 1);
}

// Principal d'une liste de salles : étiquette « principal », à défaut la salle « accueil »
function principal(salles) {
  const marquees = salles.filter((s) => (s.etiquettes || []).indexOf('principal') >= 0);
  if (marquees.length === 1) return marquees[0];
  return salles.find((s) => s.id === 'accueil') || null;
}

// Messages de vérification qui citent un identifiant (« b204 », b204 :, …) : {id: [messages]}. Chaque
// identifiant et chaque message une seule fois (une salle et son nœud ont le même identifiant).
export function alertesParId(rapport, ids) {
  const alertes = {};
  const messages = [].concat((rapport && rapport.erreurs) || [], (rapport && rapport.avertissements) || [])
    .filter((m, i, l) => l.indexOf(m) === i);
  const uniques = ids.filter((id, i) => ids.indexOf(id) === i);
  messages.forEach((m) => {
    uniques.forEach((id) => {
      const motif = new RegExp('(^|[^a-z0-9_-])' + id.replace(/[-]/g, '\\-') + '([^a-z0-9_-]|$)');
      if (motif.test(m)) (alertes[id] = alertes[id] || []).push(m);
    });
  });
  return alertes;
}

// Un identifiant rendu lisible : « couloir_sud_1 » → « Couloir sud 1 »
export function nomLisible(id) {
  const t = String(id === undefined || id === null ? '' : id).replace(/[_-]+/g, ' ').trim();
  return t ? t.charAt(0).toUpperCase() + t.slice(1) : t;
}

// États d'une session de scan, en français
const ETATS_SCAN = { en_cours: 'en cours', arret_en_cours: 'arrêt…', traitement: 'fabrication…', echec: 'échec',
  interrompu: 'interrompu', termine: '' };

function pluriel(n, mot) {
  return n + ' ' + mot + (n > 1 ? 's' : '');
}

export function construireArbre(element, options) {
  options = options || {};
  element.textContent = '';
  element.classList.add('arbre');
  element.setAttribute('data-role', 'arbre');
  const racine = el('ul', 'arbre-liste');
  racine.setAttribute('role', 'tree');
  racine.setAttribute('aria-label', 'Le lieu');
  element.appendChild(racine);
  const ouverts = new Set(['lieu', 'etage', 'points']);       // dossiers ouverts
  let choix = null;                // 'genre:id' choisi
  let detruit = false;
  let jeton = 0;

  function noeud(parent, cle, libelle, nomIcone, plus) {
    plus = plus || {};
    const li = el('li', 'arbre-element');
    li.setAttribute('role', 'treeitem');
    const ligne = el('button', 'arbre-ligne' + (plus.classe ? ' ' + plus.classe : ''));
    ligne.type = 'button';
    if (cle) ligne.setAttribute('data-noeud', cle);
    ligne.style.setProperty('--niveau', String(plus.niveau || 0));
    if (plus.dossier) {
      const ouvert = ouverts.has(plus.dossier);
      li.setAttribute('aria-expanded', ouvert ? 'true' : 'false');
      li.setAttribute('data-dossier', plus.dossier);
      const fleche = el('span', 'arbre-fleche', ouvert ? '▾' : '▸');
      fleche.setAttribute('aria-hidden', 'true');
      ligne.appendChild(fleche);
    } else {
      ligne.appendChild(el('span', 'arbre-fleche'));
    }
    const ic = el('span', 'arbre-icone' + (plus.couleur ? ' arbre-icone-' + plus.couleur : ''));
    ic.appendChild(icone(nomIcone, 16));
    ligne.appendChild(ic);
    // le numéro de l'épingle de la vue 3D (salles)
    if (plus.numero !== undefined && plus.numero !== null) ligne.appendChild(el('span', 'numero-salle', String(plus.numero)));
    ligne.appendChild(el('span', 'arbre-libelle', libelle));
    if (plus.note) ligne.appendChild(el('span', 'arbre-note', plus.note));
    if (plus.alertes && plus.alertes.length) {
      ligne.setAttribute('data-alerte', String(plus.alertes.length));
      const a = el('span', 'arbre-alerte', '⚠');
      a.title = plus.alertes.join('\n');
      ligne.appendChild(a);
    }
    ligne.title = plus.titre || (plus.alertes && plus.alertes.length ? plus.alertes.join('\n') : libelle);
    li.appendChild(ligne);
    let enfants = null;
    if (plus.dossier) {
      enfants = el('ul', 'arbre-liste');
      enfants.setAttribute('role', 'group');
      enfants.hidden = !ouverts.has(plus.dossier);
      li.appendChild(enfants);
      const basculer = () => {
        const ouvrir = enfants.hidden;
        enfants.hidden = !ouvrir;
        li.setAttribute('aria-expanded', ouvrir ? 'true' : 'false');
        ligne.querySelector('.arbre-fleche').textContent = ouvrir ? '▾' : '▸';
        if (ouvrir) ouverts.add(plus.dossier);
        else ouverts.delete(plus.dossier);
      };
      ligne.querySelector('.arbre-fleche').addEventListener('click', (ev) => {
        ev.stopPropagation();
        basculer();
      });
      if (!cle) ligne.addEventListener('click', basculer);
    }
    if (cle) {
      ligne.addEventListener('click', () => {
        const [genre] = cle.split(':');
        marquer(cle);
        if (options.surChoix) options.surChoix({ genre: genre, id: cle.slice(genre.length + 1) });
      });
      ligne.addEventListener('dblclick', () => {
        const [genre] = cle.split(':');
        if (options.surDoubleClic) options.surDoubleClic({ genre: genre, id: cle.slice(genre.length + 1) });
      });
      if (cle === choix) ligne.setAttribute('aria-selected', 'true');
    }
    parent.appendChild(li);
    return enfants;
  }

  function marquer(cle) {
    choix = cle;
    element.querySelectorAll('.arbre-ligne[aria-selected=true]').forEach((x) => x.removeAttribute('aria-selected'));
    if (!cle) return null;
    const ligne = element.querySelector('.arbre-ligne[data-noeud="' + cle.replace(/"/g, '') + '"]');
    if (!ligne) return null;
    ligne.setAttribute('aria-selected', 'true');
    return ligne;
  }

  async function rafraichir() {
    const moi = ++jeton;
    const lieu = options.lieu;
    const etage = options.etage;
    if (!lieu) {
      racine.textContent = '';
      const vide = el('li', 'arbre-vide');
      vide.appendChild(el('p', '', 'Aucun lieu ouvert.'));
      vide.appendChild(el('p', 'panneau-note', 'Revenez à l\'accueil (⌂) pour ouvrir ou créer un lieu.'));
      racine.appendChild(vide);
      return;
    }
    const base = urlLieu(lieu);
    const etageUrl = etage ? urlEtage(lieu, etage) : null;
    const [info, salles, itin, zones, verif, carte, monde, scans, perso, dialogues, camera] = await Promise.all([
      lire(base, null), lire(base + '/salles', []), lire(base + '/itineraires', { noeuds: {}, couloirs: [] }),
      lire(base + '/zones', { interdites: [], lentes: [] }), lire(base + '/verification', null),
      etageUrl ? lire(etageUrl + '/carte.yaml', null) : null,
      etageUrl && options.mode === 'simu' ? lire(etageUrl + '/monde', null) : null,
      lire('/api/scan/sessions?lieu=' + encodeURIComponent(lieu), []),
      lire(base + '/personnalites', null), lire(base + '/dialogues', null), lire(base + '/camera', null),
    ]);
    if (detruit || moi !== jeton) return;
    racine.textContent = '';
    if (!info) {
      racine.appendChild(el('li', 'arbre-vide', 'Le lieu « ' + lieu + ' » n\'a pas pu être lu.'));
      return;
    }
    const ids = [].concat(salles.map((s) => s.id), Object.keys(itin.noeuds || {}));
    const alertes = alertesParId(verif, ids);
    const nbProblemes = verif ? verif.erreurs.length + verif.avertissements.length : 0;
    const dansLieu = noeud(racine, 'lieu:' + lieu, info.nom, 'lieu', {
      dossier: 'lieu', niveau: 0, classe: 'arbre-racine',
      alertes: verif ? [].concat(verif.erreurs, verif.avertissements) : [],
      titre: nbProblemes ? 'Vérifier le lieu : ' + nbProblemes + ' point(s) à regarder' : 'Le lieu : ses étages et sa vérification',
    });
    info.etages.forEach((e) => {
      const courant = e.id === etage;
      if (!courant) {
        noeud(dansLieu, 'etage:' + e.id, e.nom, 'etage', { niveau: 1, note: e.id, titre: 'Changer d\'étage : ' + e.nom });
        return;
      }
      const dansEtage = noeud(dansLieu, 'etage:' + e.id, e.nom, 'etage', { dossier: 'etage', niveau: 1, classe: 'arbre-courant' });
      // carte
      let noteCarte = 'pas encore';
      if (carte) noteCarte = (e.source_carte === 'scan' ? 'scan' : 'monde') + (carte.modifiee ? ' · ' + dateCourte(carte.modifiee) : '');
      noeud(dansEtage, 'carte:' + e.id, 'Carte', 'carte', { niveau: 2, note: noteCarte,
        titre: carte ? 'Carte du robot : ' + carte.largeur + ' × ' + carte.hauteur + ' pixels' : 'Pas encore de carte pour cet étage' });
      // monde (simulation)
      if (options.mode === 'simu') {
        // le même décompte que le panneau du monde
        const nm = monde ? (monde.murs || []).length : 0;
        const no = monde ? (monde.objets || []).length : 0;
        const np = monde ? (monde.pietons || []).length : 0;
        noeud(dansEtage, 'monde:' + e.id, 'Monde', 'mur', { niveau: 2,
          note: monde ? pluriel(nm, 'mur') + ' · ' + pluriel(no, 'objet') : 'à dessiner',
          titre: monde ? pluriel(nm, 'mur') + ', ' + pluriel(no, 'objet') + ', ' + pluriel(np, 'piéton') : 'Monde à dessiner' });
      }
      // points
      const ici = salles.filter((s) => s.etage === e.id);
      const p = principal(salles);
      // dans l'ordre des épingles de la vue 3D, avec leur numéro (★ l'accueil d'abord)
      const tries = sallesDansLOrdre(ici, p ? p.id : null);
      const dansPoints = noeud(dansEtage, null, 'Points', 'salle', { dossier: 'points', niveau: 2,
        note: ici.length + ' point' + (ici.length > 1 ? 's' : ''), titre: 'L\'accueil et les salles de l\'étage' });
      if (!tries.length) dansPoints.appendChild(el('li', 'arbre-vide', 'Aucune salle : Placer › Salle.'));
      tries.forEach((x) => {
        const s = x.salle;
        noeud(dansPoints, 'salle:' + s.id, s.nom, s === p ? 'etoile' : 'salle', {
          niveau: 3, couleur: s === p ? 'accueil' : 'salle', alertes: alertes[s.id], note: s === p ? 'accueil' : '',
          numero: x.numero, titre: s.nom + (s === p ? ' (accueil)' : ' (épingle ' + x.numero + ')') + ' — id ' + s.id,
        });
      });
      // itinéraires
      const noeuds = Object.keys(itin.noeuds || {}).filter((k) => itin.noeuds[k].etage === e.id);
      const couloirs = (itin.couloirs || []).map((c, i) => ({ c: c, i: i }))
        .filter((x) => itin.noeuds[x.c[0]] && itin.noeuds[x.c[0]].etage === e.id);
      const dansItin = noeud(dansEtage, null, 'Itinéraires', 'relier', { dossier: 'itineraires', niveau: 2,
        note: pluriel(noeuds.length, 'nœud'), titre: pluriel(noeuds.length, 'nœud') + ' et ' + pluriel(couloirs.length, 'couloir') });
      const sallesIds = new Set(salles.map((s) => s.id));
      // un nœud de salle porte le nom de la salle ; les autres, leur identifiant rendu lisible
      const nomNoeud = (k) => {
        const s = salles.find((x) => x.id === k);
        return s ? s.nom : nomLisible(k);
      };
      noeuds.filter((k) => !sallesIds.has(k)).forEach((k) => {
        noeud(dansItin, 'noeud:' + k, nomNoeud(k), 'noeud', { niveau: 3, couleur: 'itineraire', alertes: alertes[k],
          titre: 'Nœud « ' + k + ' »' });
      });
      couloirs.forEach((x) => {
        const a = itin.noeuds[x.c[0]];
        const b = itin.noeuds[x.c[1]];
        const l = a && b ? Math.hypot(a.x - b.x, a.y - b.y) : 0;
        noeud(dansItin, 'couloir:' + x.i, nomNoeud(x.c[0]) + ' – ' + nomNoeud(x.c[1]), 'relier', {
          titre: 'Couloir ' + x.c[0] + ' – ' + x.c[1],
          niveau: 3, couleur: 'itineraire', note: l.toFixed(1).replace('.', ',') + ' m',
          alertes: l > 8 ? ['Couloir de plus de 8 m : coupez-le en deux (Placer › Relier, puis le couloir).'] : null,
        });
      });
      // zones
      const zi = (zones.interdites || []).map((z, i) => ({ z: z, i: i, genre: 'interdite' })).filter((x) => x.z.etage === e.id);
      const zl = (zones.lentes || []).map((z, i) => ({ z: z, i: i, genre: 'lente' })).filter((x) => x.z.etage === e.id);
      const dansZones = noeud(dansEtage, null, 'Zones', 'zone', { dossier: 'zones', niveau: 2,
        note: pluriel(zi.length + zl.length, 'zone') });
      zi.concat(zl).forEach((x) => {
        noeud(dansZones, 'zone:' + x.genre + ':' + x.i, x.z.nom || (x.genre === 'interdite' ? 'Zone interdite' : 'Zone lente'),
          x.genre === 'interdite' ? 'interdit' : 'lent', { niveau: 3, couleur: x.genre === 'interdite' ? 'interdite' : 'lente',
            note: x.genre === 'lente' && x.z.vitesse_max ? String(x.z.vitesse_max).replace('.', ',') + ' m/s' : '' });
      });
      // scans de cet étage
      const sessions = (Array.isArray(scans) ? scans : []).filter((s) => !s.etage || s.etage === e.id);
      if (sessions.length || options.mode !== 'simu') {
        const dansScans = noeud(dansEtage, null, 'Scans', 'scan', { dossier: 'scans', niveau: 2, note: pluriel(sessions.length, 'scan') });
        if (!sessions.length) dansScans.appendChild(el('li', 'arbre-vide', 'Aucun scan : Scanner › Scan.'));
        sessions.slice(0, 30).forEach((s) => {
          const adoptee = !!(s.adoption || s.adopte || s.adoptee);
          const etatScan = ETATS_SCAN[s.etat] !== undefined ? ETATS_SCAN[s.etat] : (s.etat || '');
          noeud(dansScans, 'scan:' + s.id, s.nom || s.id, 'scan', { niveau: 3, note: adoptee ? 'utilisé' : etatScan });
        });
      }
    });
    // équipe
    const dansEquipe = noeud(dansLieu, null, 'Équipe', 'visiteur', { dossier: 'equipe', niveau: 1 });
    [['personnalites', 'Personnalités', 'personnalite', perso], ['dialogues', 'Dialogues', 'dialogue', dialogues],
      ['camera', 'Caméra', 'camera', camera]].forEach((d) => {
      noeud(dansEquipe, 'equipe:' + d[0], d[1], d[2], { niveau: 2, note: d[3] ? '' : 'pas encore' });
    });
    if (choix) marquer(choix);
  }

  rafraichir();
  return {
    rafraichir: rafraichir,
    // met un nœud en valeur (ouvre son dossier et le fait défiler à l'écran) ; null : aucun
    choisir: (genre, id) => {
      const ligne = marquer(genre ? genre + ':' + id : null);
      if (!ligne) return;
      let li = ligne.closest('li');
      while (li) {
        const groupe = li.parentNode;
        if (groupe && groupe.hidden) {
          groupe.hidden = false;
          const parent = groupe.closest('li');
          if (parent) {
            parent.setAttribute('aria-expanded', 'true');
            if (parent.getAttribute('data-dossier')) ouverts.add(parent.getAttribute('data-dossier'));
            const f = parent.querySelector(':scope > .arbre-ligne .arbre-fleche');
            if (f) f.textContent = '▾';
          }
        }
        li = groupe ? groupe.closest('li') : null;
      }
      ligne.scrollIntoView({ block: 'nearest' });
    },
    reglages: (o) => { Object.assign(options, o); },
    detruire: () => {
      detruit = true;
      element.textContent = '';
    },
  };
}
