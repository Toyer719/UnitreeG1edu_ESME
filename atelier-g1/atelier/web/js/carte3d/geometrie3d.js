// Géométrie de la carte 3D (vague 5, section 12.3 du plan), sans three.js : fonctions pures, testées
// seules dans le navigateur (atelier/tests/test_carte3d_geometrie.py).
//
// Repère : celui de la carte (map), z vers le haut, sans aucune conversion. x, y et theta sont ceux du
// plan 2D, de salles.yaml, itineraires.yaml et zones.yaml ; theta en radians, sens trigonométrique depuis
// l'axe x ; le sol est le plan z = 0 (le nuage d'affichage a déjà le plan du sol soustrait).
// Vecteurs : tableaux [x, y, z].

import { accrocher, accrocherAngle, arrondir, normaliserAngle } from '../geometrie.js';

export const PAS_POSITION = 0.05;       // m : un point posé s'accroche aux 5 cm (comme le plan 2D)
export const PAS_ANGLE = 15;            // degrés : l'orientation glissée s'accroche par pas de 15° (Maj : libre)
export const SEUIL_CLIC_PX = 5;         // px : en deçà, un appui relâché est un clic, pas un glissé
export const SEUIL_ORIENTATION_PX = 10; // px : glissé minimal depuis le point posé pour régler l'orientation
export const RAYON_TOUCHE_PX = 14;      // px : distance au repère sous laquelle on le touche
export const HAUTEUR_DEGRADE = 2.2;     // m : vert au sol, jaune à mi-hauteur, rose à 2,2 m

// Dégradé des points par la hauteur, repli des jetons --nuage-bas, --nuage-milieu, --nuage-haut de theme.css
export const PALETTE_NUAGE = { bas: '#2e9e6b', milieu: '#ccad78', haut: '#db3866' };

// Vues prédéfinies : direction de la cible vers la caméra (azimut depuis l'axe x et élévation au-dessus
// du sol, en degrés). Dessus : presque à la verticale (une infime inclinaison vers le sud garde le nord en
// haut de l'écran) ; Iso : depuis le sud-sud-ouest, à 35° ; Face : depuis le sud, presque à l'horizontale.
export const DIRECTIONS_VUES = {
  dessus: { azimut: -90, elevation: 89.97 },
  iso: { azimut: -120, elevation: 35 },
  face: { azimut: -90, elevation: 8 },
};

// ---------------------------------------------------------------- vecteurs

export function soustraire(a, b) {
  return [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
}

export function produitScalaire(a, b) {
  return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}

export function produitVectoriel(a, b) {
  return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
}

export function norme(a) {
  return Math.sqrt(produitScalaire(a, a));
}

export function normaliser(a) {
  const n = norme(a);
  return n > 0 ? [a[0] / n, a[1] / n, a[2] / n] : [0, 0, 0];
}

// Vecteur unitaire de la cible vers la caméra, depuis un azimut et une élévation en degrés
export function directionDepuisAngles(azimutDeg, elevationDeg) {
  const az = azimutDeg * Math.PI / 180;
  const el = elevationDeg * Math.PI / 180;
  return [Math.cos(el) * Math.cos(az), Math.cos(el) * Math.sin(az), Math.sin(el)];
}

// Azimut et élévation (degrés) d'un vecteur de la cible vers la caméra
export function anglesDepuisDirection(d) {
  const u = normaliser(d);
  return {
    azimut: arrondir(Math.atan2(u[1], u[0]) * 180 / Math.PI, 2),
    elevation: arrondir(Math.asin(Math.max(-1, Math.min(1, u[2]))) * 180 / Math.PI, 2),
  };
}

// ---------------------------------------------------------------- viser le sol

// Point où le rayon (origine, direction) coupe le plan horizontal z = zSol, devant l'origine :
// {x, y, z, t} (t : distance le long de la direction), ou null s'il ne le coupe pas (on vise le ciel,
// ou un rayon parallèle au sol).
export function intersectionSol(origine, direction, zSol) {
  const z0 = zSol || 0;
  const dz = direction[2];
  if (Math.abs(dz) < 1e-9) return null;
  const t = (z0 - origine[2]) / dz;
  if (!(t > 0) || !isFinite(t)) return null;
  return { x: origine[0] + t * direction[0], y: origine[1] + t * direction[1], z: z0, t: t };
}

// Point posé : accroché aux 5 cm (ou au pas donné)
export function accrocherPosition(x, y, pas) {
  const p = pas || PAS_POSITION;
  return { x: accrocher(x, p), y: accrocher(y, p) };
}

// Orientation de la flèche glissée de (x0, y0) vers (x1, y1) : radians dans ]-π, π], accrochée au pas
// (15° par défaut) ; libre (Maj enfoncée) : arrondie à 4 décimales. null si les deux points sont confondus.
export function angleFleche(x0, y0, x1, y1, libre, pasDeg) {
  const dx = x1 - x0;
  const dy = y1 - y0;
  if (Math.hypot(dx, dy) < 1e-9) return null;
  const theta = Math.atan2(dy, dx);
  if (libre) return arrondir(normaliserAngle(theta), 4);
  return accrocherAngle(theta, pasDeg || PAS_ANGLE);
}

// Bout de la flèche d'une pose : le point à la distance donnée devant (x, y), dans la direction theta
export function boutFleche(x, y, theta, longueur) {
  return { x: x + longueur * Math.cos(theta), y: y + longueur * Math.sin(theta) };
}

// Angle en degrés (affichage, panneau) ↔ radians (fichiers), comme le panneau du plan 2D
export function versDegres(theta) {
  return arrondir(theta * 180 / Math.PI, 1);
}

export function depuisDegres(deg) {
  return arrondir(normaliserAngle(deg * Math.PI / 180), 4);
}

// ---------------------------------------------------------------- écran

// Distance d'un point p à un segment [a, b] (pixels de l'écran, tableaux [x, y])
export function distancePointSegment(p, a, b) {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const l2 = dx * dx + dy * dy;
  let t = l2 === 0 ? 0 : ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l2;
  t = Math.max(0, Math.min(1, t));
  return Math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy));
}

// Facteur de zoom d'un cran de molette (> 1 : on s'éloigne). deltaMode : 0 pixels, 1 lignes, 2 pages ;
// pincement du pavé tactile (Ctrl) : petits deltas, plus sensibles.
export function facteurMolette(deltaY, deltaMode, pincement) {
  let d = deltaY * (deltaMode === 1 ? 16 : (deltaMode === 2 ? 400 : 1));
  d = Math.max(-250, Math.min(250, d));
  return Math.exp(d * (pincement ? 0.01 : 0.002));
}

// Homothétie de centre c et de facteur k : c + k (p - c). Zoomer ainsi la caméra et sa cible autour du
// point du sol sous le pointeur garde ce point sous le pointeur (la direction de visée ne change pas).
export function homothetie(p, c, k) {
  return [c[0] + k * (p[0] - c[0]), c[1] + k * (p[1] - c[1]), c[2] + k * (p[2] - c[2])];
}

// ---------------------------------------------------------------- cadrage des vues

// Bornes {xmin, ymin, zmin, xmax, ymax, zmax} des positions x y z… (Float32Array ou tableau), ou null
export function bornesPositions(positions) {
  const n = Math.floor(positions.length / 3);
  if (!n) return null;
  let xmin = Infinity, ymin = Infinity, zmin = Infinity, xmax = -Infinity, ymax = -Infinity, zmax = -Infinity;
  for (let i = 0; i < n; i++) {
    const x = positions[3 * i], y = positions[3 * i + 1], z = positions[3 * i + 2];
    if (x < xmin) xmin = x;
    if (x > xmax) xmax = x;
    if (y < ymin) ymin = y;
    if (y > ymax) ymax = y;
    if (z < zmin) zmin = z;
    if (z > zmax) zmax = z;
  }
  return { xmin: xmin, ymin: ymin, zmin: zmin, xmax: xmax, ymax: ymax, zmax: zmax };
}

// Réunion de deux bornes (l'une ou l'autre peut être null ; z facultatif)
export function reunirBornes(a, b) {
  if (!a) return b ? Object.assign({}, b) : null;
  if (!b) return Object.assign({}, a);
  const r = {
    xmin: Math.min(a.xmin, b.xmin), ymin: Math.min(a.ymin, b.ymin),
    xmax: Math.max(a.xmax, b.xmax), ymax: Math.max(a.ymax, b.ymax),
  };
  const zmin = [a.zmin, b.zmin].filter((v) => typeof v === 'number');
  const zmax = [a.zmax, b.zmax].filter((v) => typeof v === 'number');
  if (zmin.length) r.zmin = Math.min.apply(null, zmin);
  if (zmax.length) r.zmax = Math.max.apply(null, zmax);
  return r;
}

// Bornes de quelques points du sol [[x, y], …], élargies d'une marge (m)
export function bornesDePoints(points, marge) {
  if (!points.length) return null;
  const m = marge || 0;
  const xs = points.map((p) => p[0]);
  const ys = points.map((p) => p[1]);
  return {
    xmin: Math.min.apply(null, xs) - m, ymin: Math.min.apply(null, ys) - m,
    xmax: Math.max.apply(null, xs) + m, ymax: Math.max.apply(null, ys) + m,
  };
}

// Caméra qui montre toute la boîte des bornes depuis la direction u (unitaire, de la cible vers la
// caméra) : {position, cible, distance}. fovDeg : champ vertical ; aspect : largeur / hauteur ;
// hauteur : haut de la boîte (2,2 m par défaut : on ne cadre pas sur le plafond) ; marge : 1,08.
// Pour chaque coin p de la boîte, il faut |p·droite| ≤ (d + p·avant) tan(fov horizontal / 2) et
// |p·haut| ≤ (d + p·avant) tan(fov / 2) ; d est le plus petit qui convient à tous les coins. Puis la cible
// glisse (au sol, ou à sa hauteur en vue de face) pour centrer l'image des coins : la perspective
// rapetisse les coins lointains, et le centre de la boîte n'est pas le centre de son image.
export function cadrage(bornes, u, fovDeg, aspect, options) {
  const o = options || {};
  const b = bornes;
  const zHaut = typeof o.hauteur === 'number' ? o.hauteur : HAUTEUR_DEGRADE;
  const zCible = typeof o.zCible === 'number' ? o.zCible : 0;
  const avant = normaliser([-u[0], -u[1], -u[2]]);
  let droite = produitVectoriel(avant, [0, 0, 1]);
  if (norme(droite) < 1e-6) droite = [1, 0, 0];      // regard vertical : l'est à droite
  droite = normaliser(droite);
  const haut = produitVectoriel(droite, avant);
  const tv = Math.tan(fovDeg * Math.PI / 360);
  const th = tv * (aspect || 1);
  const coins = [];
  [b.xmin, b.xmax].forEach((x) => [b.ymin, b.ymax].forEach((y) => [0, zHaut].forEach((z) => coins.push([x, y, z]))));
  // avancer au sol de s déplace l'image de s·sin(élévation) vers le haut de l'écran
  const sinElevation = Math.max(0, u[2]);
  const auSol = normaliser([avant[0], avant[1], 0]);
  let cible = [(b.xmin + b.xmax) / 2, (b.ymin + b.ymax) / 2, zCible];
  const marge = o.marge || 1.08;
  let d = 0.5;
  for (let tour = 0; tour < 12; tour++) {
    d = 0.5;
    coins.forEach((c) => {
      const p = soustraire(c, cible);
      const profondeur = produitScalaire(p, avant);
      d = Math.max(d, Math.abs(produitScalaire(p, droite)) / th - profondeur,
        Math.abs(produitScalaire(p, haut)) / tv - profondeur);
    });
    d *= marge;
    // image des coins à cette distance (marge comprise) : on recentre la cible sur le milieu de l'image
    let xmin = Infinity, xmax = -Infinity, ymin = Infinity, ymax = -Infinity;
    coins.forEach((c) => {
      const p = soustraire(c, cible);
      const profondeur = d + produitScalaire(p, avant);
      const x = produitScalaire(p, droite) / (profondeur * th);
      const y = produitScalaire(p, haut) / (profondeur * tv);
      xmin = Math.min(xmin, x);
      xmax = Math.max(xmax, x);
      ymin = Math.min(ymin, y);
      ymax = Math.max(ymax, y);
    });
    const dx = (xmin + xmax) / 2 * d * th;
    const dy = (ymin + ymax) / 2 * d * tv;
    if (Math.abs(dx) < 1e-4 * d && Math.abs(dy) < 1e-4 * d) break;
    cible = [cible[0] + dx * droite[0], cible[1] + dx * droite[1], cible[2]];
    if (sinElevation > 0.34) {                          // au-dessus de 20° : la cible avance au sol
      const s = dy / sinElevation;
      cible = [cible[0] + s * auSol[0], cible[1] + s * auSol[1], cible[2]];
    } else {                                            // presque de face : la cible monte ou descend
      cible = [cible[0], cible[1], cible[2] + dy];
    }
  }
  return { position: [cible[0] + d * u[0], cible[1] + d * u[1], cible[2] + d * u[2]], cible: cible, distance: d };
}

// Bornes « robustes » d'un nuage : sans la part donnée (0,5 % par défaut) des points les plus écartés en x
// et en y (reflets, passants vus par une fenêtre) ; z comme bornesPositions. Histogramme de 512 cases.
export function bornesRobustes(positions, part) {
  const b = bornesPositions(positions);
  if (!b) return null;
  const n = Math.floor(positions.length / 3);
  const seuil = Math.floor(n * (part === undefined ? 0.005 : part));
  if (n < 200 || seuil < 1) return b;
  const CASES = 512;
  const quantiles = (axe, min, max) => {
    const largeur = (max - min) / CASES || 1;
    const h = new Uint32Array(CASES);
    for (let i = 0; i < n; i++) h[Math.min(CASES - 1, Math.floor((positions[3 * i + axe] - min) / largeur))] += 1;
    let bas = 0;
    let cumul = 0;
    while (bas < CASES - 1 && cumul + h[bas] <= seuil) cumul += h[bas++];
    let hautCase = CASES - 1;
    cumul = 0;
    while (hautCase > 0 && cumul + h[hautCase] <= seuil) cumul += h[hautCase--];
    return [min + bas * largeur, min + (hautCase + 1) * largeur];
  };
  const x = quantiles(0, b.xmin, b.xmax);
  const y = quantiles(1, b.ymin, b.ymax);
  return { xmin: x[0], ymin: y[0], zmin: b.zmin, xmax: x[1], ymax: y[1], zmax: b.zmax };
}

// Cadrage sous la barre flottante du haut de la vue (Dessus, Iso, Face, Recadrer) : la pose est calculée pour la
// partie libre de l'image (hauteur - marge, en pixels), puis caméra et cible glissent ensemble vers le
// « haut » de l'écran de quoi descendre l'image de marge / 2 : le contenu tient entre la barre et le bas.
// poseDe(fovDeg, aspect) → {position, cible, distance} (cadrage ou poseVue) ; fovDeg : champ vertical de la
// caméra ; largeur, hauteur : taille de la vue. Une vue plus basse que 4 marges : pas de marge.
export function cadrageSousMarge(poseDe, fovDeg, largeur, hauteur, marge) {
  const m = marge > 0 && hauteur > 4 * marge ? marge : 0;
  const libre = hauteur - m;
  const tanDemi = Math.tan(fovDeg * Math.PI / 360);
  const pose = poseDe(2 * Math.atan(tanDemi * libre / hauteur) * 180 / Math.PI, largeur / libre);
  if (!m) return pose;
  const glisse = (m / 2) / (hauteur / 2) * pose.distance * tanDemi;     // m, à la distance de la cible
  const avant = normaliser(soustraire(pose.cible, pose.position));
  let droite = produitVectoriel(avant, [0, 0, 1]);
  if (norme(droite) < 1e-6) droite = [1, 0, 0];
  const haut = produitVectoriel(normaliser(droite), avant);
  const d = haut.map((v) => v * glisse);
  return {
    position: [pose.position[0] + d[0], pose.position[1] + d[1], pose.position[2] + d[2]],
    cible: [pose.cible[0] + d[0], pose.cible[1] + d[1], pose.cible[2] + d[2]],
    distance: pose.distance,
  };
}

// Caméra d'une vue prédéfinie (dessus, iso, face) sur des bornes
export function poseVue(nom, bornes, fovDeg, aspect, options) {
  const v = DIRECTIONS_VUES[nom] || DIRECTIONS_VUES.iso;
  const o = Object.assign({}, options || {});
  if (nom === 'face' && typeof o.zCible !== 'number') {
    o.zCible = (typeof o.hauteur === 'number' ? o.hauteur : HAUTEUR_DEGRADE) / 2;   // le bâtiment centré
  }
  return cadrage(bornes, directionDepuisAngles(v.azimut, v.elevation), fovDeg, aspect, o);
}

// ---------------------------------------------------------------- nuage

// '#2e9e6b' (ou ' #2e9e6b', 'rgb(46, 158, 107)') → [r, g, b] de 0 à 1 ; null si illisible
export function couleurDepuisTexte(texte) {
  const t = String(texte || '').trim();
  let m = /^#([0-9a-f]{6})$/i.exec(t);
  if (m) {
    const v = parseInt(m[1], 16);
    return [((v >> 16) & 255) / 255, ((v >> 8) & 255) / 255, (v & 255) / 255];
  }
  m = /^#([0-9a-f]{3})$/i.exec(t);
  if (m) {
    return [0, 1, 2].map((i) => parseInt(m[1][i] + m[1][i], 16) / 255);
  }
  m = /^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)/i.exec(t);
  if (m) return [Number(m[1]) / 255, Number(m[2]) / 255, Number(m[3]) / 255];
  return null;
}

// Couleur [r, g, b] (0 à 1) d'un point à la hauteur h au-dessus du sol : bas au sol, milieu à mi-hauteur,
// haut à hauteurMax et au-dessus (le même calcul que le nuanceur des points de carte3d.js)
export function couleurHauteur(h, hauteurMax, palette) {
  const p = palette || {};
  const bas = p.bas || couleurDepuisTexte(PALETTE_NUAGE.bas);
  const milieu = p.milieu || couleurDepuisTexte(PALETTE_NUAGE.milieu);
  const haut = p.haut || couleurDepuisTexte(PALETTE_NUAGE.haut);
  const t = Math.max(0, Math.min(1, h / (hauteurMax || HAUTEUR_DEGRADE)));
  const a = t < 0.5 ? bas : milieu;
  const b = t < 0.5 ? milieu : haut;
  const s = t < 0.5 ? t * 2 : t * 2 - 1;
  return [a[0] + (b[0] - a[0]) * s, a[1] + (b[1] - a[1]) * s, a[2] + (b[2] - a[2]) * s];
}

// En-têtes HTTP d'un nuage (section 12.4 : X-Nuage-Points, -Grille, -Bornes, -Source, -Date, -Session).
// lire(nom) rend le texte de l'en-tête ou null (headers.get). Bornes : null si absentes ou fausses.
export function lireEntetesNuage(lire) {
  const texte = (nom) => {
    const v = lire('X-Nuage-' + nom);
    return v === null || v === undefined ? null : String(v);
  };
  const nombre = (v) => (v === null || v.trim() === '' || !isFinite(Number(v)) ? null : Number(v));
  let bornes = null;
  const b = texte('Bornes');
  if (b) {
    const v = b.split(',').map((x) => Number(x));
    if (v.length === 6 && v.every((x) => isFinite(x))) {
      bornes = { xmin: v[0], ymin: v[1], zmin: v[2], xmax: v[3], ymax: v[4], zmax: v[5] };
    }
  }
  const points = nombre(texte('Points'));
  return {
    points: points === null ? null : Math.round(points),
    grille: nombre(texte('Grille')),
    bornes: bornes,
    source: texte('Source'),
    date: texte('Date'),
    session: texte('Session') || null,
  };
}

// Points du sol et autres points d'un nuage (Float32Array x y z…) : {sol, reste}, deux Float32Array. Le sol :
// les points à moins de « seuil » mètres au-dessus du plan du sol (z < seuil). La carte 3D les dessine
// sans écrire la profondeur : les zones, couloirs et trajets posés au sol restent visibles par-dessus,
// et les murs et les meubles (le reste) les cachent toujours.
export function separerSol(positions, seuil) {
  const n = Math.floor(positions.length / 3);
  let nSol = 0;
  for (let i = 0; i < n; i++) if (positions[3 * i + 2] < seuil) nSol += 1;
  const sol = new Float32Array(3 * nSol);
  const reste = new Float32Array(3 * (n - nSol));
  let a = 0;
  let b = 0;
  for (let i = 0; i < n; i++) {
    const k = 3 * i;
    if (positions[k + 2] < seuil) {
      sol[a] = positions[k]; sol[a + 1] = positions[k + 1]; sol[a + 2] = positions[k + 2];
      a += 3;
    } else {
      reste[b] = positions[k]; reste[b + 1] = positions[k + 1]; reste[b + 2] = positions[k + 2];
      b += 3;
    }
  }
  return { sol: sol, reste: reste };
}

// Points x y z d'un tampon binaire (Float32 petit-boutistes, 12 octets par point) : Float32Array.
// Erreur en français si la taille n'est pas un multiple de 12. Sur une machine gros-boutiste (rare),
// les octets sont relus un par un.
export function positionsDepuisTampon(tampon) {
  if (tampon.byteLength % 12 !== 0) {
    throw new Error('Le nuage 3D reçu est tronqué (' + tampon.byteLength + ' octets, pas un multiple de 12) : '
      + 'rechargez la page ; si cela continue, refaites le nuage (g1-scan traiter --refaire).');
  }
  const petitBoutiste = new Uint8Array(new Uint16Array([1]).buffer)[0] === 1;
  if (petitBoutiste) return new Float32Array(tampon);
  const vue = new DataView(tampon);
  const n = tampon.byteLength / 4;
  const sortie = new Float32Array(n);
  for (let i = 0; i < n; i++) sortie[i] = vue.getFloat32(4 * i, true);
  return sortie;
}

// ---------------------------------------------------------------- salles

// Le point principal d'une liste de salles (même règle que js/ecrans/salles.js, sallePrincipale) : la
// salle qui porte l'étiquette « principal », à défaut la salle « accueil » ; null s'il n'y en a pas (ou
// s'il y en a deux : salles.yaml les refuse).
export function idPrincipal(salles) {
  const marquees = (salles || []).filter((s) => (s.etiquettes || []).indexOf('principal') >= 0);
  if (marquees.length === 1) return marquees[0].id;
  if (marquees.length) return null;
  const accueil = (salles || []).find((s) => s.id === 'accueil');
  return accueil ? accueil.id : null;
}

// Numéros des épingles : 1, 2, 3… dans l'ordre de salles.yaml, sans compter le point principal (étoile).
// Une salle dont le nom est un petit nombre (« 1 », « 12 ») garde ce nombre, et les autres prennent les
// numéros libres : l'épingle ne contredit jamais le nom (salles « 1 », « 2 », « 3 » de la séance du 27/10).
export function numerosSalles(salles, principal) {
  const numeros = {};
  const liste = (salles || []).filter((s) => s.id !== principal);
  const pris = new Set();
  liste.forEach((s) => {
    const nom = String(s.nom === undefined || s.nom === null ? '' : s.nom).trim();
    if (/^\d{1,3}$/.test(nom) && !pris.has(Number(nom))) {
      numeros[s.id] = Number(nom);
      pris.add(Number(nom));
    }
  });
  let n = 0;
  liste.forEach((s) => {
    if (numeros[s.id] !== undefined) return;
    do {
      n += 1;
    } while (pris.has(n));
    numeros[s.id] = n;
  });
  return numeros;
}

// Les salles dans l'ordre de leurs épingles : le point principal d'abord, puis 1, 2, 3… (numerosSalles). L'arbre
// et les listes des panneaux s'en servent, avec le même numéro que l'épingle : [{salle, numero}] (numero null
// pour le principal).
export function sallesDansLOrdre(salles, principal) {
  const numeros = numerosSalles(salles, principal);
  return (salles || []).map((s) => ({ salle: s, numero: s.id === principal ? null : numeros[s.id] }))
    .sort((a, b) => (a.numero === null ? -1 : (b.numero === null ? 1 : a.numero - b.numero)));
}

// Étiquettes des salles sans chevauchement. Le nom d'une salle se met à droite de sa tête numérotée, à
// défaut à gauche, dessus ou dessous ; sinon il est caché (la tête reste, et la liste du panneau donne
// le nom). candidats : [{id, x, y, largeur, hauteur, rayon}] (pixels ; x, y : centre de la tête ; rayon :
// demi-largeur de la tête), dans l'ordre de priorité (la salle en cours de pose, la salle choisie,
// l'accueil, puis les plus proches de la caméra). tetes : toutes les têtes affichées [{id, x, y, rayon}],
// même celles sans étiquette (par défaut, celles des candidats). Une étiquette ne couvre ni une étiquette
// déjà placée, ni la tête d'une autre salle. Rend {id: 'droite' | 'gauche' | 'dessus' | 'dessous' | null}.
export const PLACES_ETIQUETTE = ['droite', 'gauche', 'dessus', 'dessous'];
export const ECART_ETIQUETTE = 6;       // px entre le bord de la tête et son étiquette (carte3d.css)

// Rectangle {x0, y0, x1, y1} (pixels) de l'étiquette du candidat c à la place donnée
export function rectangleEtiquette(c, place) {
  const d = c.rayon + ECART_ETIQUETTE;
  if (place === 'droite') return { x0: c.x + d, y0: c.y - c.hauteur / 2, x1: c.x + d + c.largeur, y1: c.y + c.hauteur / 2 };
  if (place === 'gauche') return { x0: c.x - d - c.largeur, y0: c.y - c.hauteur / 2, x1: c.x - d, y1: c.y + c.hauteur / 2 };
  if (place === 'dessus') return { x0: c.x - c.largeur / 2, y0: c.y - d - c.hauteur, x1: c.x + c.largeur / 2, y1: c.y - d };
  return { x0: c.x - c.largeur / 2, y0: c.y + d, x1: c.x + c.largeur / 2, y1: c.y + d + c.hauteur };
}

export function rectanglesSeCoupent(a, b) {
  return a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1;
}

export function placerEtiquettes(candidats, toutesLesTetes) {
  const tetes = (toutesLesTetes || candidats).map((c) => ({ id: c.id, x0: c.x - c.rayon, y0: c.y - c.rayon,
    x1: c.x + c.rayon, y1: c.y + c.rayon }));
  const posees = [];
  const places = {};
  candidats.forEach((c) => {
    places[c.id] = null;
    for (let i = 0; i < PLACES_ETIQUETTE.length; i++) {
      const r = rectangleEtiquette(c, PLACES_ETIQUETTE[i]);
      const gene = posees.some((p) => rectanglesSeCoupent(r, p))
        || tetes.some((t) => t.id !== c.id && rectanglesSeCoupent(r, t));
      if (!gene) {
        places[c.id] = PLACES_ETIQUETTE[i];
        posees.push(r);
        return;
      }
    }
  });
  return places;
}

// Distance au format français : « 3,25 m »
export function texteDistance(m) {
  return arrondir(m, 2).toLocaleString('fr-FR', { maximumFractionDigits: 2 }) + ' m';
}
