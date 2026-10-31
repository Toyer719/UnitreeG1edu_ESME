// Vue de la caméra de poitrine (See3CAM) avec les cadres des visiteurs (vague 5, section 12.7 du
// plan), module de l'agent Caméra. Le flux MJPEG de GET /api/camera/flux dans une balise <img>
// [data-role=camera-flux] ; les cadres « boite » des visiteurs (champ visiteurs de /ws/etat, publiés
// par g1-visiteurs) dessinés par-dessus dans <canvas data-role=camera-cadres>, mis à l'échelle de
// l'image analysée (champ image du message) ; l'état dans [data-role=camera-etat] (« Pas d'image : … »,
// d'après GET /api/camera/etat). Le flux ne tourne que si la vue est démarrée, visible à l'écran et
// l'onglet du navigateur visible. La coque s'en sert pour la vue « Caméra » et l'incrustation dans
// Piloter et Naviguer ; l'écran Caméra (js/ecrans/camera.js) aussi.

import { abonner } from '../direct.js';

const PERIODE_ETAT_MS = 2000;      // GET /api/camera/etat, tant que la vue tourne
const REESSAI_MS = 3000;           // flux refusé ou coupé : nouvel essai
const VISITEURS_PERIMES_S = 2.0;   // cadres plus vieux : effacés
const SOURCES = ['poitrine', 'visiteurs'];

function element(balise, classe, role) {
  const e = document.createElement(balise);
  if (classe) e.className = classe;
  if (role) e.setAttribute('data-role', role);
  return e;
}

function nombre(v, decimales) {
  return Number(v).toFixed(decimales === undefined ? 1 : decimales).replace('.', ',');
}

// Rectangle (en pixels CSS du conteneur) où l'image est dessinée avec object-fit: contain
export function rectangleImage(largeurBoite, hauteurBoite, largeurImage, hauteurImage) {
  if (!largeurImage || !hauteurImage || !largeurBoite || !hauteurBoite) return null;
  const echelle = Math.min(largeurBoite / largeurImage, hauteurBoite / hauteurImage);
  const l = largeurImage * echelle;
  const h = hauteurImage * echelle;
  return { x: (largeurBoite - l) / 2, y: (hauteurBoite - h) / 2, largeur: l, hauteur: h, echelle: echelle };
}

// Cadres à dessiner, en pixels du conteneur : [{x, y, largeur, hauteur, texte, face}] ; message : le
// champ visiteurs de /ws/etat ; rect : rectangleImage de l'image affichée
export function cadresAffiches(message, rect) {
  if (!message || !rect || message.perime || !Array.isArray(message.personnes)) return [];
  const image = message.image || {};
  const sx = image.largeur ? rect.largeur / image.largeur : rect.echelle;
  const sy = image.hauteur ? rect.hauteur / image.hauteur : rect.echelle;
  const cadres = [];
  message.personnes.forEach((p) => {
    if (!p || !Array.isArray(p.boite) || p.boite.length !== 4) return;
    const b = p.boite.map(Number);
    if (!(b[2] > b[0] && b[3] > b[1])) return;
    const distance = typeof p.distance_m === 'number' ? ' · ' + nombre(p.distance_m) + ' m' : '';
    cadres.push({ x: rect.x + b[0] * sx, y: rect.y + b[1] * sy, largeur: (b[2] - b[0]) * sx,
      hauteur: (b[3] - b[1]) * sy, texte: 'n° ' + p.id + distance, face: p.regarde_robot === true });
  });
  return cadres;
}

// options : {source: 'poitrine' | 'visiteurs', cadres: true, petit: false (incrustation), ips: 10}
// Renvoie {demarrer(), arreter(), etat(), detruire()}.
export function creerVueCamera(conteneur, options) {
  const o = Object.assign({ source: 'poitrine', cadres: true, petit: false, ips: 10 }, options || {});
  if (SOURCES.indexOf(o.source) < 0) o.source = 'poitrine';
  // l'image des visiteurs a déjà ses cadres (dessinés par g1-visiteurs)
  if (options && options.cadres === undefined && o.source === 'visiteurs') o.cadres = false;

  const racine = element('div', 'camera-vue' + (o.petit ? ' camera-vue-petite' : ''), 'camera-vue');
  racine.setAttribute('data-source', o.source);
  const cadre = element('div', 'camera-cadre');
  const img = element('img', 'camera-flux', 'camera-flux');
  img.alt = o.source === 'visiteurs' ? 'Image des visiteurs (cadres de g1-visiteurs)' : 'Image de la caméra de poitrine';
  img.decoding = 'async';
  const toile = element('canvas', 'camera-cadres', 'camera-cadres');
  const texte = element('p', 'camera-etat', 'camera-etat');
  texte.setAttribute('aria-live', 'polite');
  cadre.appendChild(img);
  cadre.appendChild(toile);
  racine.appendChild(cadre);
  racine.appendChild(texte);
  conteneur.appendChild(racine);

  let actif = false;
  let visible = true;
  let flux = false;
  let detruite = false;
  let visiteurs = null;
  let minuterieEtat = null;
  let minuterieReessai = null;
  let desabonner = null;
  let dernierEtat = null;
  let chargees = 0;
  let cadresDessines = 0;
  let observateurVisible = null;
  let observateurTaille = null;
  let attenteChargement = false;

  function pageVisible() {
    return document.visibilityState !== 'hidden';
  }

  // Un flux encore sans image retarde l'événement « load » de la page : on attend qu'elle soit chargée
  function attendreChargement() {
    if (attenteChargement) return;
    attenteChargement = true;
    window.addEventListener('load', () => {
      attenteChargement = false;
      majFlux();
    }, { once: true });
  }

  function brancher() {
    if (flux) return;
    if (document.readyState !== 'complete') {
      attendreChargement();
      return;
    }
    flux = true;
    img.src = '/api/camera/flux?source=' + encodeURIComponent(o.source) + '&ips=' + encodeURIComponent(o.ips)
      + '&t=' + Date.now();
    racine.setAttribute('data-flux', 'oui');
  }

  function debrancher() {
    if (!flux) return;
    flux = false;
    img.removeAttribute('src');          // ferme la connexion : le serveur arrête d'envoyer
    racine.setAttribute('data-flux', 'non');
  }

  function majFlux() {
    if (actif && visible && pageVisible() && !detruite) brancher();
    else debrancher();
  }

  function montrerEtat(message, genre) {
    texte.textContent = message || '';
    racine.setAttribute('data-etat', genre);
    texte.hidden = !message;
  }

  function lireJeton(nom, repli) {
    const v = getComputedStyle(racine).getPropertyValue(nom);
    return (v && v.trim()) || repli;
  }

  function dessiner() {
    const largeur = cadre.clientWidth;
    const hauteur = cadre.clientHeight;
    const ratio = window.devicePixelRatio || 1;
    if (toile.width !== Math.round(largeur * ratio) || toile.height !== Math.round(hauteur * ratio)) {
      toile.width = Math.max(1, Math.round(largeur * ratio));
      toile.height = Math.max(1, Math.round(hauteur * ratio));
    }
    const ctx = toile.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, largeur, hauteur);
    cadresDessines = 0;
    if (!actif || !o.cadres || !visiteurs) {
      toile.setAttribute('data-cadres', '0');
      return;
    }
    const image = visiteurs.image || {};
    const rect = rectangleImage(largeur, hauteur, img.naturalWidth || image.largeur, img.naturalHeight || image.hauteur);
    const cadres = cadresAffiches(visiteurs, rect);
    const couleurFace = lireJeton('--succes', '#3ccb85');
    const couleurAutre = lireJeton('--avertissement', '#f5a524');
    const police = o.petit ? 11 : 13;
    ctx.font = '600 ' + police + 'px system-ui, sans-serif';
    ctx.textBaseline = 'top';
    const etiquettes = [];       // rectangles déjà occupés par une étiquette
    const recouvre = (r) => etiquettes.some((e) => r.x < e.x + e.l && e.x < r.x + r.l && r.y < e.y + e.h && e.y < r.y + r.h);
    cadres.forEach((c) => {
      const couleur = c.face ? couleurFace : couleurAutre;
      ctx.lineWidth = o.petit ? 1.5 : 2;
      ctx.strokeStyle = couleur;
      ctx.strokeRect(c.x, c.y, c.largeur, c.hauteur);
      const h = police + 6;
      const l = ctx.measureText(c.texte).width + 8;
      // au-dessus du cadre ; sinon dedans, en haut ; sinon dedans, en bas (cadres voisins)
      const essais = [c.y >= h ? c.y - h : c.y, c.y + 1, c.y + c.hauteur - h - 1];
      const x = Math.max(0, Math.min(c.x, largeur - l));        // jamais coupée au bord de la vue
      let r = { x: x, y: essais[0], l: l, h: h };
      for (let i = 0; i < essais.length; i++) {
        r = { x: x, y: essais[i], l: l, h: h };
        if (!recouvre(r)) break;
      }
      etiquettes.push(r);
      ctx.fillStyle = couleur;
      ctx.fillRect(r.x, r.y, l, h);
      ctx.fillStyle = lireJeton('--vue-fond', '#1e1e1e');
      ctx.fillText(c.texte, r.x + 4, r.y + 3);
    });
    cadresDessines = cadres.length;
    toile.setAttribute('data-cadres', String(cadres.length));
  }

  function surDirect(d) {
    visiteurs = d && d.visiteurs && !(d.visiteurs.age_recu_s > VISITEURS_PERIMES_S) ? d.visiteurs : null;
    dessiner();
  }

  async function lireEtat() {
    if (!actif || detruite) return;
    try {
      const r = await fetch('/api/camera/etat', { cache: 'no-store' });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      dernierEtat = await r.json();
    } catch (e) {
      dernierEtat = null;
      montrerEtat('Pas d\'image : le serveur de l\'Atelier ne répond pas.', 'sans-image');
      return;
    }
    if (!actif || detruite) return;
    const source = dernierEtat.sources ? dernierEtat.sources[o.source] : null;
    const pourquoi = dernierEtat.messages ? dernierEtat.messages[o.source] : null;
    if (pourquoi) {
      montrerEtat(pourquoi, 'sans-image');
    } else if (source) {
      const vus = dernierEtat.visiteurs && !dernierEtat.visiteurs.perime ? dernierEtat.visiteurs.nombre : null;
      const morceaux = [];
      if (source.largeur) morceaux.push(source.largeur + ' × ' + source.hauteur);
      if (source.ips) morceaux.push(nombre(source.ips, 0) + ' images/s');
      if (vus !== null) morceaux.push(vus + ' visiteur' + (vus > 1 ? 's' : ''));
      montrerEtat(o.petit ? '' : morceaux.join(' · '), 'ok');
      // des images arrivent au serveur, mais rien ne s'affiche : on rebranche le flux
      if (flux && img.complete && !img.naturalWidth) {
        debrancher();
        majFlux();
      }
    }
  }

  function reessayer() {
    if (minuterieReessai) return;
    minuterieReessai = setTimeout(() => {
      minuterieReessai = null;
      if (actif && !detruite) {
        debrancher();
        majFlux();
      }
    }, REESSAI_MS);
  }

  img.addEventListener('load', () => {
    chargees += 1;
    racine.setAttribute('data-images', String(chargees));
    dessiner();
  });
  img.addEventListener('error', () => {
    if (!img.getAttribute('src')) return;      // débranché exprès
    flux = false;
    lireEtat();
    reessayer();
  });
  const surVisibilite = () => majFlux();
  document.addEventListener('visibilitychange', surVisibilite);
  if (typeof IntersectionObserver === 'function') {
    observateurVisible = new IntersectionObserver((entrees) => {
      visible = entrees.some((e) => e.isIntersecting);
      majFlux();
    });
    observateurVisible.observe(racine);
  }
  if (typeof ResizeObserver === 'function') {
    observateurTaille = new ResizeObserver(() => dessiner());
    observateurTaille.observe(cadre);
  }
  montrerEtat('Caméra arrêtée.', 'arrete');

  function demarrer() {
    if (detruite || actif) return;
    actif = true;
    montrerEtat('Connexion à la caméra…', 'attente');
    majFlux();
    if (o.cadres && !desabonner) desabonner = abonner(surDirect);
    lireEtat();
    minuterieEtat = setInterval(lireEtat, PERIODE_ETAT_MS);
  }

  function arreter() {
    if (!actif) return;
    actif = false;
    debrancher();
    if (minuterieEtat) clearInterval(minuterieEtat);
    if (minuterieReessai) clearTimeout(minuterieReessai);
    minuterieEtat = null;
    minuterieReessai = null;
    if (desabonner) desabonner();
    desabonner = null;
    visiteurs = null;
    dessiner();
    montrerEtat('Caméra arrêtée.', 'arrete');
  }

  function detruire() {
    arreter();
    detruite = true;
    document.removeEventListener('visibilitychange', surVisibilite);
    if (observateurVisible) observateurVisible.disconnect();
    if (observateurTaille) observateurTaille.disconnect();
    if (racine.parentNode) racine.parentNode.removeChild(racine);
  }

  function etat() {
    const source = dernierEtat && dernierEtat.sources ? dernierEtat.sources[o.source] : null;
    return {
      actif: actif, flux: flux, source: o.source, images: source ? source.numero : 0,
      age_s: source ? source.age_s : null, largeur: img.naturalWidth || 0, hauteur: img.naturalHeight || 0,
      chargees: chargees, cadres: cadresDessines,
      message: texte.textContent || null,
    };
  }

  return { demarrer: demarrer, arreter: arreter, etat: etat, detruire: detruire };
}
