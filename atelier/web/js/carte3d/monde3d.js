// Monde de la simulation dans la carte 3D (vague 5, section 12.3 du plan) : murs, objets et meubles en
// volumes, trajets des piétons, et la carte extrudée d'un étage scanné (maillage STL de
// GET …/monde/maillage). Repère map tel quel (z vers le haut), comme js/vue3d.js, en couleurs sombres.

import * as THREE from 'three';
import { MOBILIER, capMur, longueurMur } from '../geometrie.js';

const COULEURS = {
  sol: 0x26262d, mur: 0xb9bdc9, boite: 0x9c7a55, poteau: 0x8d939a, meuble: 0xa98457,
  poubelle: 0x5c7d5c, maillage: 0xaeb3c0, trajetPieton: 0x8fa7d4,
};

function materiau(couleur) {
  return new THREE.MeshLambertMaterial({ color: couleur });
}

// Pavé posé au sol : longueur le long de x local, largeur le long de y, hauteur le long de z
function pave(longueur, largeur, hauteur, couleur, z0) {
  const m = new THREE.Mesh(new THREE.BoxGeometry(longueur, largeur, hauteur), materiau(couleur));
  m.position.z = (z0 || 0) + hauteur / 2;
  return m;
}

function cylindre(rayon, hauteur, couleur) {
  const m = new THREE.Mesh(new THREE.CylinderGeometry(rayon, rayon, hauteur, 24), materiau(couleur));
  m.rotation.x = Math.PI / 2;
  m.position.z = hauteur / 2;
  return m;
}

// Meubles simplifiés, à l'encombrement du contrat (chaise, table, banc, poubelle)
function meuble(modele) {
  const g = new THREE.Group();
  const d = MOBILIER[modele];
  const c = COULEURS.meuble;
  if (!d) {
    g.add(pave(0.5, 0.5, 0.5, c));
  } else if (modele === 'poubelle') {
    g.add(cylindre(d.rayon, d.hauteur, COULEURS.poubelle));
  } else if (modele === 'chaise') {
    g.add(pave(d.longueur, d.largeur, 0.05, c, 0.42));
    const dossier = pave(0.05, d.largeur, d.hauteur - 0.47, c, 0.47);
    dossier.position.x = -d.longueur / 2 + 0.025;
    g.add(dossier);
    [[-1, -1], [-1, 1], [1, -1], [1, 1]].forEach((s) => {
      const pied = pave(0.04, 0.04, 0.42, c);
      pied.position.x = s[0] * (d.longueur / 2 - 0.03);
      pied.position.y = s[1] * (d.largeur / 2 - 0.03);
      g.add(pied);
    });
  } else if (modele === 'table') {
    g.add(pave(d.longueur, d.largeur, 0.05, c, d.hauteur - 0.05));
    [[-1, -1], [-1, 1], [1, -1], [1, 1]].forEach((s) => {
      const pied = pave(0.06, 0.06, d.hauteur - 0.05, c);
      pied.position.x = s[0] * (d.longueur / 2 - 0.05);
      pied.position.y = s[1] * (d.largeur / 2 - 0.05);
      g.add(pied);
    });
  } else if (modele === 'banc') {
    g.add(pave(d.longueur, d.largeur, 0.06, c, d.hauteur - 0.06));
    [-1, 1].forEach((s) => {
      const cote = pave(0.06, d.largeur, d.hauteur - 0.06, c);
      cote.position.x = s * (d.longueur / 2 - 0.1);
      g.add(cote);
    });
  } else {
    g.add(pave(d.longueur || 0.5, d.largeur || 0.5, d.hauteur || 0.5, c));
  }
  return g;
}

// Groupe three.js du monde (format de monde.yaml) : {groupe, bornes {xmin, ymin, zmin, xmax, ymax, zmax}}.
// sol : vrai pour poser un sol sombre sur l'emprise (sans carte 2D en dessous).
export function construireMonde(monde, options) {
  const o = options || {};
  const g = new THREE.Group();
  if (!monde) return { groupe: g, bornes: null };
  let zmax = 0;
  const e = monde.emprise;
  let bornes = null;
  if (e && e.min && e.max) {
    bornes = { xmin: e.min[0], ymin: e.min[1], zmin: 0, xmax: e.max[0], ymax: e.max[1], zmax: 0 };
    if (o.sol) {
      const lx = e.max[0] - e.min[0];
      const ly = e.max[1] - e.min[1];
      const sol = new THREE.Mesh(new THREE.PlaneGeometry(lx, ly), new THREE.MeshBasicMaterial({ color: COULEURS.sol }));
      sol.position.set(e.min[0] + lx / 2, e.min[1] + ly / 2, -0.015);
      sol.renderOrder = 0;
      g.add(sol);
    }
  }
  (monde.murs || []).forEach((m) => {
    const L = longueurMur(m);
    if (L <= 0) return;
    const b = pave(L, m.epaisseur, m.hauteur, COULEURS.mur);
    b.position.x = (m.de[0] + m.a[0]) / 2;
    b.position.y = (m.de[1] + m.a[1]) / 2;
    b.rotation.z = capMur(m);
    b.userData = { genre: 'mur', id: m.id };
    g.add(b);
    zmax = Math.max(zmax, m.hauteur);
  });
  (monde.objets || []).forEach((obj) => {
    let forme;
    if (obj.type === 'boite') forme = pave(obj.taille[0], obj.taille[1], obj.taille[2], COULEURS.boite);
    else if (obj.type === 'cylindre') forme = cylindre(obj.rayon, obj.hauteur, COULEURS.poteau);
    else forme = meuble(obj.modele);
    const support = new THREE.Group();
    support.add(forme);
    support.position.set(obj.centre[0], obj.centre[1], 0);
    support.rotation.z = obj.cap || 0;
    support.userData = { genre: 'objet', id: obj.id };
    g.add(support);
  });
  (monde.pietons || []).forEach((p) => {
    const points = (p.trajet || []).map((q) => new THREE.Vector3(q[0], q[1], 0.025));
    if (points.length < 2) return;
    if (!p.aller_retour) points.push(points[0].clone());
    const ligne = new THREE.Line(new THREE.BufferGeometry().setFromPoints(points),
      new THREE.LineDashedMaterial({ color: COULEURS.trajetPieton, dashSize: 0.3, gapSize: 0.2 }));
    ligne.computeLineDistances();
    g.add(ligne);
  });
  if (bornes) bornes.zmax = zmax;
  return { groupe: g, bornes: bornes };
}

// Maillage d'un STL (binaire, ou texte) : BufferGeometry, ou une erreur en français
export function lireSTL(tampon) {
  const vue = new DataView(tampon);
  if (tampon.byteLength >= 84) {
    const n = vue.getUint32(80, true);
    if (84 + 50 * n === tampon.byteLength) {
      const positions = new Float32Array(9 * n);
      for (let i = 0; i < n; i++) {
        const debut = 84 + 50 * i + 12;
        for (let k = 0; k < 9; k++) positions[9 * i + k] = vue.getFloat32(debut + 4 * k, true);
      }
      const geometrie = new THREE.BufferGeometry();
      geometrie.setAttribute('position', new THREE.BufferAttribute(positions, 3));
      geometrie.computeVertexNormals();
      return geometrie;
    }
  }
  const texte = new TextDecoder().decode(new Uint8Array(tampon));
  if (/^\s*solid/.test(texte)) {
    const sommets = [];
    const motif = /vertex\s+([-+\d.eE]+)\s+([-+\d.eE]+)\s+([-+\d.eE]+)/g;
    let m = motif.exec(texte);
    while (m) {
      sommets.push(Number(m[1]), Number(m[2]), Number(m[3]));
      m = motif.exec(texte);
    }
    if (sommets.length && sommets.length % 9 === 0) {
      const geometrie = new THREE.BufferGeometry();
      geometrie.setAttribute('position', new THREE.Float32BufferAttribute(sommets, 3));
      geometrie.computeVertexNormals();
      return geometrie;
    }
  }
  throw new Error('Le maillage de la carte extrudée est illisible : refaites-le (g1-monde generer).');
}

// Le maillage de la carte extrudée, en volume gris clair
export function meshDuMaillage(geometrie) {
  const m = new THREE.Mesh(geometrie, new THREE.MeshLambertMaterial({ color: COULEURS.maillage }));
  m.userData = { genre: 'carte_extrudee' };
  return m;
}
