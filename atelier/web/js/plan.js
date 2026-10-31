// Plan 2D vu de dessus, avec Leaflet en CRS.Simple : une unité de la carte vaut un mètre.
// Leaflet range les points en (lat, lng) : ici lat = y et lng = x, en mètres du repère map.
// Le fond est la carte 2D du lieu (PNG servi par l'API, placé grâce aux bornes calculées par
// atelier.lieu.conversions côté serveur), ou à défaut le dessin du monde inventé.

import { api, urlEtage } from './api.js';
import { coinsMur, empreinteObjet, nb } from './geometrie.js';

const L = window.L;

export function ll(x, y) {
  return L.latLng(y, x);
}

export function xy(latlng) {
  return [latlng.lng, latlng.lat];
}

export function lls(points) {
  return points.map((p) => ll(p[0], p[1]));
}

// Mètres par pixel d'écran au zoom actuel (CRS.Simple : 2^zoom pixels par mètre)
export function metresParPixel(carte) {
  return 1 / Math.pow(2, carte.getZoom());
}

const CoordonneesControle = L.Control.extend({
  options: { position: 'bottomleft' },
  onAdd: function () {
    this._div = L.DomUtil.create('div', 'plan-coordonnees');
    this._div.textContent = 'x — · y —';
    return this._div;
  },
  montrer: function (p) {
    this._div.textContent = 'x ' + nb(p[0], 2) + ' m · y ' + nb(p[1], 2) + ' m';
  },
});

// Crée un plan dans l'élément donné. Renvoie un objet avec la carte Leaflet et des outils.
export function creerPlan(element) {
  const cadre = document.createElement('div');
  cadre.className = 'plan-cadre';
  const fond = document.createElement('div');
  fond.className = 'plan-carte';
  cadre.appendChild(fond);
  element.appendChild(cadre);

  const carte = L.map(fond, {
    crs: L.CRS.Simple, minZoom: -2, maxZoom: 8, zoomSnap: 0.25, zoomDelta: 0.5,
    wheelPxPerZoomLevel: 90, attributionControl: false, doubleClickZoom: false,
    boxZoom: false, keyboard: false,
  });
  carte.setView([10, 10], 4);
  L.control.scale({ metric: true, imperial: false, maxWidth: 150 }).addTo(carte);
  const coordonnees = new CoordonneesControle();
  coordonnees.addTo(carte);
  // le point sous le pointeur, en mètres : aussi pour la barre d'état de la coque (événement de la page)
  carte.on('mousemove', (e) => {
    const p = xy(e.latlng);
    coordonnees.montrer(p);
    document.dispatchEvent(new CustomEvent('atelier-pointeur', { detail: { x: p[0], y: p[1] } }));
  });
  carte.on('mouseout', () => document.dispatchEvent(new CustomEvent('atelier-pointeur', { detail: null })));

  const calques = {
    fond: L.layerGroup().addTo(carte),
    grille: L.layerGroup().addTo(carte),
    monde: L.layerGroup().addTo(carte),
  };
  const observateur = new ResizeObserver(() => carte.invalidateSize());
  observateur.observe(fond);

  const plan = {
    carte: carte,
    cadre: cadre,
    calques: calques,
    infoCarte: null,
    cadre_initial: false,

    // Recentre la vue sur un rectangle (xmin, ymin, xmax, ymax) en mètres
    cadrer: function (xmin, ymin, xmax, ymax) {
      carte.invalidateSize();
      // sans animation : un clic pendant l'animation serait converti avec l'ancien zoom
      carte.fitBounds([[ymin, xmin], [ymax, xmax]], { padding: [20, 20], animate: false });
    },

    // Grille de pas mètres sur le rectangle donné (traits plus marqués tous les mètres)
    afficherGrille: function (xmin, ymin, xmax, ymax, pas) {
      calques.grille.clearLayers();
      const fin = (v) => Math.abs(v - Math.round(v)) < 1e-6;
      const x0 = Math.floor(xmin), x1 = Math.ceil(xmax), y0 = Math.floor(ymin), y1 = Math.ceil(ymax);
      for (let x = x0; x <= x1 + 1e-9; x += pas) {
        L.polyline([ll(x, y0), ll(x, y1)], { className: fin(x) ? 'grille-metre' : 'grille-fine', interactive: false })
          .addTo(calques.grille);
      }
      for (let y = y0; y <= y1 + 1e-9; y += pas) {
        L.polyline([ll(x0, y), ll(x1, y)], { className: fin(y) ? 'grille-metre' : 'grille-fine', interactive: false })
          .addTo(calques.grille);
      }
    },

    // Fond : la carte 2D de l'étage si elle existe. Renvoie son info (carte.yaml) ou null.
    afficherCarte: async function (lieu, etage) {
      calques.fond.clearLayers();
      plan.infoCarte = null;
      let info;
      try {
        info = await api.lire(urlEtage(lieu, etage) + '/carte.yaml');
      } catch (e) {
        if (e.statut === 404) return null;
        throw e;
      }
      const b = info.bornes;
      L.imageOverlay(urlEtage(lieu, etage) + '/carte.png?v=' + Date.now(), [[b.ymin, b.xmin], [b.ymax, b.xmax]],
        { className: 'plan-image-carte', interactive: false }).addTo(calques.fond);
      plan.infoCarte = info;
      return info;
    },

    // Dessin simple du monde (murs, objets), pour servir de fond quand il n'y a pas de carte
    afficherMondeFond: function (monde) {
      calques.monde.clearLayers();
      if (!monde) return;
      const e = monde.emprise;
      L.rectangle([[e.min[1], e.min[0]], [e.max[1], e.max[0]]], { className: 'fond-emprise', interactive: false })
        .addTo(calques.monde);
      monde.murs.forEach((m) => L.polygon(lls(coinsMur(m)), { className: 'fond-mur', interactive: false })
        .addTo(calques.monde));
      monde.objets.forEach((o) => {
        const f = empreinteObjet(o);
        if (f.genre === 'cercle') L.circle(ll(f.centre[0], f.centre[1]), { radius: f.rayon, className: 'fond-objet', interactive: false }).addTo(calques.monde);
        else L.polygon(lls(f.points), { className: 'fond-objet', interactive: false }).addTo(calques.monde);
      });
    },

    // Fond complet d'un écran de placement : la carte, sinon le monde. Cadre la vue la 1re fois.
    // Renvoie {info, monde} ; info vaut null s'il n'y a pas encore de carte.
    afficherFond: async function (lieu, etage) {
      let monde = null;
      try {
        monde = await api.lire(urlEtage(lieu, etage) + '/monde');
      } catch (e) {
        if (e.statut !== 404) throw e;
      }
      const info = await plan.afficherCarte(lieu, etage);
      if (!info) plan.afficherMondeFond(monde);
      else calques.monde.clearLayers();
      if (!plan.cadre_initial) {
        if (info) plan.cadrer(info.bornes.xmin, info.bornes.ymin, info.bornes.xmax, info.bornes.ymax);
        else if (monde) plan.cadrer(monde.emprise.min[0], monde.emprise.min[1], monde.emprise.max[0], monde.emprise.max[1]);
        plan.cadre_initial = true;
      }
      return { info: info, monde: monde };
    },

    detruire: function () {
      observateur.disconnect();
      carte.remove();
      cadre.remove();
    },
  };
  return plan;
}

// Suivi du pointeur (souris, doigt, stylet) pour dessiner sur le plan.
// gestes : {debut(p, e) → vrai si le geste est pris en main, deplacer(p, e), fin(p, e), survol(p, e), annuler()}
// p = [x, y] en mètres. Pendant un geste pris en main, Leaflet ne fait pas glisser la carte.
// Un deuxième doigt (pincer pour zoomer) annule le geste en cours.
export function suivrePointeur(plan, gestes) {
  const carte = plan.carte;
  const cadre = plan.cadre;
  let actif = null;          // id du pointeur du geste en cours
  const pointeurs = new Set();
  let glisserAvant = true;

  function point(e) {
    return xy(carte.mouseEventToLatLng(e));
  }

  function surControle(e) {
    return e.target && e.target.closest && e.target.closest('.leaflet-control');
  }

  function bas(e) {
    pointeurs.add(e.pointerId);
    if (pointeurs.size > 1) {
      if (actif !== null) {
        actif = null;
        if (gestes.annuler) gestes.annuler();
        if (glisserAvant) carte.dragging.enable();
      }
      return;
    }
    if (e.button !== 0 || surControle(e)) return;
    // la barre d'outils a pu changer de hauteur : Leaflet doit connaître la taille actuelle du plan
    // avant de convertir le pointeur en mètres (sinon le dessin tombe à côté du clic)
    carte.invalidateSize();
    if (gestes.debut && gestes.debut(point(e), e)) {
      actif = e.pointerId;
      glisserAvant = carte.dragging.enabled();
      carte.dragging.disable();      // avant que Leaflet ne voie le mousedown ou le touchstart
      try {
        cadre.setPointerCapture(e.pointerId);
      } catch (err) {
        // pas grave : on reçoit quand même les mouvements au-dessus du plan
      }
      e.preventDefault();
      e.stopPropagation();
    }
  }

  function bouge(e) {
    if (actif === e.pointerId) {
      if (gestes.deplacer) gestes.deplacer(point(e), e);
    } else if (actif === null && pointeurs.size <= 1 && gestes.survol && !surControle(e)) {
      gestes.survol(point(e), e);
    }
  }

  function haut(e) {
    pointeurs.delete(e.pointerId);
    if (actif !== e.pointerId) return;
    actif = null;
    if (glisserAvant) carte.dragging.enable();
    if (gestes.fin) gestes.fin(point(e), e);
  }

  function perdu(e) {
    pointeurs.delete(e.pointerId);
    if (actif === e.pointerId) {
      actif = null;
      if (glisserAvant) carte.dragging.enable();
      if (gestes.annuler) gestes.annuler();
    }
  }

  cadre.addEventListener('pointerdown', bas, true);
  cadre.addEventListener('pointermove', bouge, true);
  cadre.addEventListener('pointerup', haut, true);
  cadre.addEventListener('pointercancel', perdu, true);
  return function arreter() {
    cadre.removeEventListener('pointerdown', bas, true);
    cadre.removeEventListener('pointermove', bouge, true);
    cadre.removeEventListener('pointerup', haut, true);
    cadre.removeEventListener('pointercancel', perdu, true);
  };
}

// Petite icône ronde orientée (salle, robot...), tournée de theta (radians, sens trigonométrique)
export function iconeOrientee(classe, theta) {
  const deg = -theta * 180 / Math.PI;     // à l'écran, y vers le bas : on tourne dans l'autre sens
  return L.divIcon({
    className: 'icone-orientee ' + classe,
    html: '<div class="icone-fleche" style="transform: rotate(' + deg + 'deg)"></div>',
    iconSize: [28, 28],
    iconAnchor: [14, 14],
  });
}
