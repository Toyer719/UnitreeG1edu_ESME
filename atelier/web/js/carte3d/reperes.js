// Repères de la carte 3D (vague 5, section 12.3 du plan) : accueil (étoile ambre et flèche), salles
// (épingle couleur d'accent et flèche), nœuds et couloirs des itinéraires (cyan, au sol), zones
// (polygones translucides), robot (G1 simplifié, tourné vers son avant), piétons, trajet du scan.
// Repère map, z vers le haut : un repère posé en (x, y) est à (x, y, 0), sa flèche tournée de theta
// autour de z (rotation.z = theta, sans conversion).
//
// Les repères « à poser » (accueil, salles, nœuds) sont dessinés par-dessus le nuage (depthTest faux),
// pour qu'un mur ne les cache jamais ; leur tête numérotée et leur nom sont des éléments HTML posés par
// carte3d.js au-dessus de la toile.

import * as THREE from 'three';

export const HAUTEUR_POTEAU = 1.0;     // m : hauteur de l'épingle (sa tête HTML est posée en haut)
export const LONGUEUR_FLECHE = { salle: 1.0, principal: 1.5 };   // m, comme les poignées du plan 2D
const Z_SOL = { carte: -0.01, zone: 0.02, couloir: 0.03, trajet: 0.035, repere: 0.045 };

// G1 debout : 1,32 m de haut, épaules d'environ 0,45 m (robot proxy de g1_sim : 0,208 × 0,477 × 1,315)
const G1 = { hauteur: 1.32 };

function materiauPlat(couleur, options) {
  const o = options || {};
  return new THREE.MeshBasicMaterial({
    color: couleur, transparent: true, opacity: o.opacite === undefined ? 1 : o.opacite,
    depthTest: o.profondeur === true, depthWrite: false, side: THREE.DoubleSide,
  });
}

function aPlat(geometrie, couleur, z, ordre, options) {
  const m = new THREE.Mesh(geometrie, materiauPlat(couleur, options));
  m.position.z = z;
  m.renderOrder = ordre;
  return m;
}

// Flèche couchée au sol, de l'origine vers +x : une tige et une pointe
function flecheAuSol(longueur, largeur, couleur, ordre) {
  const g = new THREE.Group();
  const pointe = Math.min(0.35 * longueur, 0.4);
  const tige = new THREE.Mesh(new THREE.PlaneGeometry(longueur - pointe, largeur), materiauPlat(couleur));
  tige.position.x = (longueur - pointe) / 2;
  tige.renderOrder = ordre;
  g.add(tige);
  const forme = new THREE.Shape();
  forme.moveTo(longueur - pointe, -largeur * 2.2);
  forme.lineTo(longueur, 0);
  forme.lineTo(longueur - pointe, largeur * 2.2);
  forme.closePath();
  const tete = new THREE.Mesh(new THREE.ShapeGeometry(forme), materiauPlat(couleur));
  tete.renderOrder = ordre;
  g.add(tete);
  g.position.z = Z_SOL.repere;
  return g;
}

function formeEtoile(rayonExterieur, rayonInterieur, branches) {
  const s = new THREE.Shape();
  for (let i = 0; i < 2 * branches; i++) {
    const r = i % 2 === 0 ? rayonExterieur : rayonInterieur;
    const a = Math.PI / 2 + i * Math.PI / branches;
    if (i === 0) s.moveTo(r * Math.cos(a), r * Math.sin(a));
    else s.lineTo(r * Math.cos(a), r * Math.sin(a));
  }
  s.closePath();
  return s;
}

// Épingle d'une salle ou étoile de l'accueil, posée en (0, 0) : base au sol, flèche (enfant « fleche »,
// tournée par theta), poteau, anneau de sélection et poignée d'orientation (cachés au départ).
// couleurs : {repere, choisi} ; principal : étoile ambre et flèche plus longue ; fantome : translucide.
export function creerRepereSalle(couleurs, principal, fantome) {
  const g = new THREE.Group();
  const opacite = fantome ? 0.55 : 1;
  const c = couleurs.repere;
  const longueur = principal ? LONGUEUR_FLECHE.principal : LONGUEUR_FLECHE.salle;
  const base = principal
    ? aPlat(new THREE.ShapeGeometry(formeEtoile(0.36, 0.15, 5)), c, Z_SOL.repere, 11, { opacite: opacite })
    : aPlat(new THREE.CircleGeometry(0.2, 32), c, Z_SOL.repere, 11, { opacite: opacite });
  g.add(base);
  const fleche = flecheAuSol(longueur, principal ? 0.1 : 0.08, c, 12);
  fleche.children.forEach((m) => { m.material.opacity = opacite; });
  fleche.name = 'fleche';
  g.add(fleche);
  const poteau = new THREE.Mesh(new THREE.CylinderGeometry(0.018, 0.018, HAUTEUR_POTEAU, 8),
    materiauPlat(c, { opacite: opacite }));
  poteau.rotation.x = Math.PI / 2;            // l'axe des cylindres de three.js est y : on le met sur z
  poteau.position.z = HAUTEUR_POTEAU / 2;
  poteau.renderOrder = 13;
  poteau.name = 'poteau';
  g.add(poteau);
  const anneau = aPlat(new THREE.RingGeometry(principal ? 0.42 : 0.3, principal ? 0.5 : 0.38, 40), couleurs.choisi,
    Z_SOL.repere + 0.002, 14);
  anneau.name = 'anneau';
  anneau.visible = false;
  g.add(anneau);
  const poignee = aPlat(new THREE.CircleGeometry(0.13, 24), couleurs.choisi, Z_SOL.repere + 0.004, 15);
  poignee.name = 'poignee';
  poignee.position.x = longueur;
  poignee.visible = false;
  g.add(poignee);
  g.userData = { longueur: longueur, principal: !!principal };
  return g;
}

// Oriente la flèche d'un repère de salle (theta en radians, sens trigonométrique depuis x)
export function orienterRepere(repere, theta) {
  const f = repere.getObjectByName('fleche');
  const p = repere.getObjectByName('poignee');
  const t = theta || 0;
  if (f) f.rotation.z = t;
  if (p) p.position.set(repere.userData.longueur * Math.cos(t), repere.userData.longueur * Math.sin(t), p.position.z);
}

// Anneau de sélection, et poignée d'orientation (seulement si poignee n'est pas faux : un repère
// qu'aucun écran ne modifie n'a pas de poignée)
export function marquerChoisi(repere, choisi, poignee) {
  const a = repere.getObjectByName('anneau');
  const p = repere.getObjectByName('poignee');
  if (a) a.visible = !!choisi;
  if (p) p.visible = !!choisi && poignee !== false;
}

// Nœud d'itinéraire : disque cyan au sol (et son anneau de sélection)
export function creerRepereNoeud(couleurs) {
  const g = new THREE.Group();
  g.add(aPlat(new THREE.CircleGeometry(0.14, 24), couleurs.itineraire, Z_SOL.repere - 0.004, 9));
  const anneau = aPlat(new THREE.RingGeometry(0.2, 0.26, 32), couleurs.choisi, Z_SOL.repere - 0.002, 10);
  anneau.name = 'anneau';
  anneau.visible = false;
  g.add(anneau);
  g.userData = { longueur: 0 };
  return g;
}

// Ruban au sol le long d'une polyligne [[x, y], …] (largeur en m), plus un trait d'un pixel : il reste
// visible de loin, quand le ruban devient plus fin qu'un pixel.
export function creerRuban(points, largeur, couleur, z, ordre, options) {
  const g = new THREE.Group();
  if (points.length < 2) return g;
  const sommets = [];
  const indices = [];
  for (let i = 0; i < points.length; i++) {
    const a = points[Math.max(0, i - 1)];
    const b = points[Math.min(points.length - 1, i + 1)];
    let dx = b[0] - a[0];
    let dy = b[1] - a[1];
    const l = Math.hypot(dx, dy) || 1;
    dx /= l;
    dy /= l;
    const nx = -dy * largeur / 2;
    const ny = dx * largeur / 2;
    sommets.push(points[i][0] + nx, points[i][1] + ny, 0, points[i][0] - nx, points[i][1] - ny, 0);
    if (i > 0) {
      const k = 2 * (i - 1);
      indices.push(k, k + 1, k + 2, k + 1, k + 3, k + 2);
    }
  }
  const geometrie = new THREE.BufferGeometry();
  geometrie.setAttribute('position', new THREE.Float32BufferAttribute(sommets, 3));
  geometrie.setIndex(indices);
  const o = Object.assign({ profondeur: true }, options || {});
  const ruban = new THREE.Mesh(geometrie, materiauPlat(couleur, o));
  ruban.renderOrder = ordre;
  g.add(ruban);
  const trait = new THREE.Line(new THREE.BufferGeometry().setFromPoints(points.map((p) => new THREE.Vector3(p[0], p[1], 0))),
    new THREE.LineBasicMaterial({ color: couleur, transparent: true, opacity: o.opacite === undefined ? 1 : o.opacite,
      depthTest: o.profondeur, depthWrite: false }));
  trait.renderOrder = ordre;
  g.add(trait);
  g.position.z = z;
  return g;
}

// Un couloir : ruban cyan au sol de a à b ({x, y}) ; userData : ses deux bouts
export function creerCouloir(a, b, couleurs) {
  const r = creerRuban([[a.x, a.y], [b.x, b.y]], 0.09, couleurs.itineraire, Z_SOL.couloir, 8, { opacite: 0.85 });
  r.userData = { a: [a.x, a.y], b: [b.x, b.y] };
  return r;
}

// Couloirs et nœuds des itinéraires d'un étage : {groupe, noeuds: Map id → repère, couloirs: [{a, b, objet}]}
// (a, b : ids des nœuds ; objet : le ruban, que carte3d.js remplace quand on glisse un de ses nœuds)
export function creerItineraires(noeuds, couloirs, etage, couleurs) {
  const groupe = new THREE.Group();
  const reperes = new Map();
  const liste = [];
  const dict = noeuds || {};
  const ici = (id) => dict[id] && (!etage || dict[id].etage === etage);
  (couloirs || []).forEach((c) => {
    if (!Array.isArray(c) || c.length < 2 || !ici(c[0]) || !ici(c[1])) return;
    const objet = creerCouloir(dict[c[0]], dict[c[1]], couleurs);
    groupe.add(objet);
    liste.push({ a: String(c[0]), b: String(c[1]), objet: objet });
  });
  Object.keys(dict).forEach((id) => {
    if (!ici(id)) return;
    const r = creerRepereNoeud(couleurs);
    r.position.set(dict[id].x, dict[id].y, 0);
    r.userData.id = id;
    reperes.set(id, r);
    groupe.add(r);
  });
  return { groupe: groupe, noeuds: reperes, couloirs: liste };
}

// Zones d'un étage : polygones translucides et leur contour. {groupe, zones: [{id, genre, polygone, objet}]}
// id : « interdite:0 », « lente:1 » (rang dans zones.yaml, comme l'arbre du lieu)
export function creerZones(zones, etage, couleurs) {
  const groupe = new THREE.Group();
  const liste = [];
  [['interdites', 'interdite', couleurs.zoneInterdite], ['lentes', 'lente', couleurs.zoneLente]].forEach((t) => {
    ((zones || {})[t[0]] || []).forEach((z, i) => {
      if (etage && z.etage !== etage) return;
      const poly = z.polygone || [];
      if (poly.length < 3) return;
      const forme = new THREE.Shape();
      poly.forEach((p, k) => (k === 0 ? forme.moveTo(p[0], p[1]) : forme.lineTo(p[0], p[1])));
      forme.closePath();
      const g = new THREE.Group();
      const fond = aPlat(new THREE.ShapeGeometry(forme), t[2], Z_SOL.zone, 6, { opacite: 0.28, profondeur: true });
      fond.name = 'fond';
      g.add(fond);
      const contour = poly.concat([poly[0]]);
      const bord = creerRuban(contour, 0.06, t[2], Z_SOL.zone + 0.003, 7, { opacite: 0.9 });
      bord.name = 'bord';
      g.add(bord);
      const id = t[1] + ':' + i;
      g.userData = { id: id };
      groupe.add(g);
      liste.push({ id: id, genre: t[1], polygone: poly, objet: g });
    });
  });
  return { groupe: groupe, zones: liste };
}

export function marquerZoneChoisie(zone, choisie) {
  const fond = zone.objet.getObjectByName('fond');
  if (fond) fond.material.opacity = choisie ? 0.5 : 0.28;
}

// Trajet d'un scan : ruban rouge au sol
export function creerTrajet(points, couleur) {
  const p = (points || []).filter((q) => Array.isArray(q) && q.length >= 2).map((q) => [q[0], q[1]]);
  return creerRuban(p, 0.06, couleur, Z_SOL.trajet, 5, { opacite: 0.95 });
}

function lambert(couleur) {
  return new THREE.MeshLambertMaterial({ color: couleur });
}

function pave(longueur, largeur, hauteur, materiau, x, y, z) {
  const m = new THREE.Mesh(new THREE.BoxGeometry(longueur, largeur, hauteur), materiau);
  m.position.set(x || 0, y || 0, (z || 0) + hauteur / 2);
  return m;
}

// G1 simplifié, à sa taille (1,32 m), l'avant vers +x : jambes, bassin, torse, bras, tête avec le LiDAR ;
// au sol, un anneau et une flèche orange qui montrent sa direction (dessinés par-dessus le nuage).
export function creerRobot(couleurs) {
  const g = new THREE.Group();
  const corps = lambert(0xd5d8df);
  const sombre = lambert(0x2b2e36);
  const accent = lambert(couleurs.robot);
  g.add(pave(0.1, 0.1, 0.6, corps, 0, 0.09, 0));
  g.add(pave(0.1, 0.1, 0.6, corps, 0, -0.09, 0));
  g.add(pave(0.16, 0.3, 0.14, sombre, 0, 0, 0.6));
  g.add(pave(0.18, 0.36, 0.4, corps, 0, 0, 0.74));
  g.add(pave(0.02, 0.2, 0.14, accent, 0.1, 0, 0.94));            // plastron : l'avant du robot
  g.add(pave(0.08, 0.07, 0.46, corps, 0, 0.225, 0.66));
  g.add(pave(0.08, 0.07, 0.46, corps, 0, -0.225, 0.66));
  const tete = new THREE.Mesh(new THREE.SphereGeometry(0.105, 20, 14), corps);
  tete.position.z = G1.hauteur - 0.105;
  g.add(tete);
  g.add(pave(0.05, 0.15, 0.05, sombre, 0.08, 0, G1.hauteur - 0.14));   // LiDAR MID-360 dans la tête
  const sol = new THREE.Group();
  sol.name = 'sol';
  sol.add(aPlat(new THREE.RingGeometry(0.36, 0.43, 40), couleurs.robot, Z_SOL.repere, 11));
  const fleche = flecheAuSol(0.85, 0.06, couleurs.robot, 12);
  fleche.position.x = 0.15;
  sol.add(fleche);
  g.add(sol);
  return g;
}

// Rend le robot plus ou moins visible (pose périmée : translucide)
export function estomperRobot(robot, estompe) {
  robot.traverse((o) => {
    if (!o.material) return;
    o.material.transparent = true;
    o.material.opacity = estompe ? 0.35 : 1;
  });
}

// Piéton : corps et tête, à taille humaine
export function creerPieton(couleur) {
  const g = new THREE.Group();
  const m = lambert(couleur);
  const corps = new THREE.Mesh(new THREE.CylinderGeometry(0.17, 0.2, 1.3, 16), m);
  corps.rotation.x = Math.PI / 2;
  corps.position.z = 0.65;
  g.add(corps);
  const tete = new THREE.Mesh(new THREE.SphereGeometry(0.12, 16, 12), m);
  tete.position.z = 1.45;
  g.add(tete);
  return g;
}

// Trait de mesure entre deux points du sol
export function creerTraitMesure(a, b, couleur) {
  return creerRuban([[a.x, a.y], [b.x, b.y]], 0.04, couleur, Z_SOL.repere + 0.01, 16, { profondeur: false });
}

// Grille d'un mètre au sol sur des bornes {xmin, ymin, xmax, ymax}, très discrète
export function creerGrille(bornes, couleur) {
  const traits = [];
  const x0 = Math.floor(bornes.xmin);
  const x1 = Math.ceil(bornes.xmax);
  const y0 = Math.floor(bornes.ymin);
  const y1 = Math.ceil(bornes.ymax);
  for (let x = x0; x <= x1; x++) traits.push(x, y0, 0, x, y1, 0);
  for (let y = y0; y <= y1; y++) traits.push(x0, y, 0, x1, y, 0);
  const geometrie = new THREE.BufferGeometry();
  geometrie.setAttribute('position', new THREE.Float32BufferAttribute(traits, 3));
  const grille = new THREE.LineSegments(geometrie, new THREE.LineBasicMaterial({ color: couleur, transparent: true,
    opacity: 0.9, depthWrite: false }));
  grille.position.z = Z_SOL.carte - 0.01;
  grille.renderOrder = 1;
  return grille;
}

export const Z_REPERES = Z_SOL;

// Libère les géométries et matériaux d'un objet et de ses enfants (textures comprises)
export function liberer(objet) {
  if (!objet) return;
  objet.traverse((o) => {
    if (o.geometry) o.geometry.dispose();
    if (o.material) {
      (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => {
        if (m.map) m.map.dispose();
        m.dispose();
      });
    }
  });
}
