// Petits calculs de géométrie au sol, en mètres et en radians (repère map : x vers l'est,
// y vers le nord, angles depuis l'axe x dans le sens inverse des aiguilles d'une montre).

// Encombrement des modèles de mobilier (contrat 4.1 du plan), avant rotation par le cap
export const MOBILIER = {
  chaise: { longueur: 0.45, largeur: 0.45, hauteur: 0.9 },
  table: { longueur: 1.2, largeur: 0.8, hauteur: 0.75 },
  banc: { longueur: 1.5, largeur: 0.4, hauteur: 0.45 },
  poubelle: { rayon: 0.25, hauteur: 0.8 },
};

export const COULOIR_MAX = 8.0;     // m : tronçons de la navigation du vrai robot (1102)
export const MOTIF_ID = /^[a-z0-9][a-z0-9_-]{0,39}$/;
export const REGLE_ID = "de 1 à 40 lettres minuscules sans accent, chiffres, « _ » ou « - », en commençant par une lettre ou un chiffre";
const MOTS_BOOLEENS = ['yes', 'no', 'on', 'off', 'true', 'false', 'y', 'n'];

export function arrondir(v, decimales) {
  const f = Math.pow(10, decimales === undefined ? 3 : decimales);
  return Math.round(v * f) / f;
}

export function accrocher(v, pas) {
  return arrondir(Math.round(v / pas) * pas, 3);
}

export function accrocherPoint(p, pas) {
  return [accrocher(p[0], pas), accrocher(p[1], pas)];
}

export function distance(a, b) {
  return Math.hypot(b[0] - a[0], b[1] - a[1]);
}

export function degres(rad) {
  return rad * 180 / Math.PI;
}

export function radians(deg) {
  return deg * Math.PI / 180;
}

// Angle ramené dans ]-π, π]
export function normaliserAngle(a) {
  let r = ((a + Math.PI) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI) - Math.PI;
  if (r <= -Math.PI) r += 2 * Math.PI;
  return r;
}

// Angle arrondi à un multiple du pas (en degrés), dans ]-π, π] : un glissé à main levée donne 90° tout rond
export function accrocherAngle(theta, pasDegres) {
  const pas = radians(pasDegres);
  return arrondir(normaliserAngle(Math.round(theta / pas) * pas), 4);
}

// Nombre affiché à la française : 12,5
export function nb(v, decimales) {
  if (v === null || v === undefined || isNaN(v)) return '—';
  return Number(v).toLocaleString('fr-FR', { maximumFractionDigits: decimales === undefined ? 2 : decimales });
}

// Projection du point p sur le segment [a, b] : {t (0 à 1), point, distance}
export function projeterSurSegment(p, a, b) {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const l2 = dx * dx + dy * dy;
  let t = l2 === 0 ? 0 : ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l2;
  t = Math.max(0, Math.min(1, t));
  const q = [a[0] + t * dx, a[1] + t * dy];
  return { t: t, point: q, distance: distance(p, q) };
}

export function distancePolyligne(p, points, fermee) {
  let d = Infinity;
  for (let i = 0; i + 1 < points.length; i++) {
    d = Math.min(d, projeterSurSegment(p, points[i], points[i + 1]).distance);
  }
  if (fermee && points.length > 2) {
    d = Math.min(d, projeterSurSegment(p, points[points.length - 1], points[0]).distance);
  }
  if (points.length === 1) d = distance(p, points[0]);
  return d;
}

export function dansPolygone(p, poly) {
  let dedans = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const xi = poly[i][0], yi = poly[i][1], xj = poly[j][0], yj = poly[j][1];
    if ((yi > p[1]) !== (yj > p[1]) && p[0] < (xj - xi) * (p[1] - yi) / (yj - yi) + xi) dedans = !dedans;
  }
  return dedans;
}

// Les 4 coins d'un rectangle de centre c, longueur le long du cap, largeur en travers
export function rectangle(c, longueur, largeur, cap) {
  const ux = Math.cos(cap), uy = Math.sin(cap);
  const vx = -uy, vy = ux;
  const l = longueur / 2, w = largeur / 2;
  return [
    [c[0] - ux * l - vx * w, c[1] - uy * l - vy * w],
    [c[0] + ux * l - vx * w, c[1] + uy * l - vy * w],
    [c[0] + ux * l + vx * w, c[1] + uy * l + vy * w],
    [c[0] - ux * l + vx * w, c[1] - uy * l + vy * w],
  ];
}

export function capMur(mur) {
  return Math.atan2(mur.a[1] - mur.de[1], mur.a[0] - mur.de[0]);
}

export function longueurMur(mur) {
  return distance(mur.de, mur.a);
}

export function coinsMur(mur) {
  const c = [(mur.de[0] + mur.a[0]) / 2, (mur.de[1] + mur.a[1]) / 2];
  return rectangle(c, longueurMur(mur), mur.epaisseur, capMur(mur));
}

// Forme au sol d'un objet : {genre: 'cercle', centre, rayon} ou {genre: 'polygone', points}
export function empreinteObjet(o) {
  if (o.type === 'cylindre') return { genre: 'cercle', centre: o.centre, rayon: o.rayon };
  if (o.type === 'modele') {
    const m = MOBILIER[o.modele];
    if (!m) return { genre: 'cercle', centre: o.centre, rayon: 0.3 };
    if (m.rayon) return { genre: 'cercle', centre: o.centre, rayon: m.rayon };
    return { genre: 'polygone', points: rectangle(o.centre, m.longueur, m.largeur, o.cap || 0) };
  }
  return { genre: 'polygone', points: rectangle(o.centre, o.taille[0], o.taille[1], o.cap || 0) };
}

export function distanceEmpreinte(p, forme) {
  if (forme.genre === 'cercle') return Math.max(0, distance(p, forme.centre) - forme.rayon);
  if (dansPolygone(p, forme.points)) return 0;
  return distancePolyligne(p, forme.points, true);
}

// Premier identifiant libre de la forme prefixe_1, prefixe_2... (40 caractères au plus)
export function idLibre(prefixe, existants) {
  const pris = new Set(existants);
  const base = prefixe.slice(0, 34);
  for (let i = 1; ; i++) {
    const id = base + '_' + i;
    if (!pris.has(id)) return id;
  }
}

// Identifiant fabriqué depuis un nom : « Salle B204 » → salle_b204
export function idDepuisNom(nom) {
  let id = (nom || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase()
    .replace(/[^a-z0-9_-]+/g, '_').replace(/^[_-]+|_+$/g, '').slice(0, 40);
  if (MOTS_BOOLEENS.indexOf(id) >= 0) id = id + '_1';
  return id;
}

// Message d'erreur si l'id est refusé (forme, mot réservé, déjà pris), sinon null
export function verifierId(id, existants, quoi) {
  if (!MOTIF_ID.test(id)) return '« ' + id + ' » : identifiant refusé. Il faut ' + REGLE_ID + '.';
  if (MOTS_BOOLEENS.indexOf(id) >= 0) return '« ' + id + ' » est lu comme oui/non par YAML : choisissez un autre identifiant.';
  if (existants && existants.indexOf(id) >= 0) return 'Il y a déjà ' + (quoi || 'un élément') + ' « ' + id + ' ».';
  return null;
}

// Coupe un passage de la largeur donnée dans un mur, centré sur le point le plus proche de p.
// Renvoie les morceaux qui restent (0, 1 ou 2 murs) ; le premier garde l'id du mur.
export function couperMur(mur, p, largeur, idsPris) {
  const L = longueurMur(mur);
  if (L === 0) return [mur];
  const proj = projeterSurSegment(p, mur.de, mur.a);
  const centre = proj.t * L;
  const debut = Math.max(0, centre - largeur / 2);
  const fin = Math.min(L, centre + largeur / 2);
  const ux = (mur.a[0] - mur.de[0]) / L, uy = (mur.a[1] - mur.de[1]) / L;
  const point = (s) => [arrondir(mur.de[0] + ux * s), arrondir(mur.de[1] + uy * s)];
  const morceaux = [];
  if (debut > 0.05) morceaux.push(Object.assign({}, mur, { de: mur.de.slice(), a: point(debut) }));
  if (L - fin > 0.05) {
    const pris = (idsPris || []).concat(morceaux.map((m) => m.id));
    const id = morceaux.length ? idLibre(mur.id.replace(/_\d+$/, ''), pris.concat([mur.id])) : mur.id;
    morceaux.push(Object.assign({}, mur, { id: id, de: point(fin), a: mur.a.slice() }));
  }
  return morceaux;
}
