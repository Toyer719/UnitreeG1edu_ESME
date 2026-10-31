// Nuage de points 3D du scan, avec three.js (vague 5, section 12.5 du plan) : le nuage en direct pendant
// le scan (GET /api/scan/nuage?apercu=1) et le nuage traité d'une session ou d'un étage (binaire Float32
// x y z, en-têtes X-Nuage-*), colorés d'après la hauteur au-dessus du sol (vert, jaune, rose, de 0 à
// 2,2 m, jetons --nuage-* du thème), le trajet et le robot. Fond toujours sombre (--vue-fond).
// Repère map gardé tel quel (z vers le haut) : x, y sont ceux de la carte 2D et des salles.
// Rendu à la demande : rien ne tourne au repos. Sans WebGL : un message, et toutes les méthodes
// restent appelables sans effet (etat().webgl faux).

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/OrbitControls.js';

export const HAUTEUR_COULEURS = 2.2;      // m : vert au sol, jaune au milieu, rose à 2,2 m et plus
export const HAUTEUR_COUPE = 2.2;         // m : les points plus hauts (le plafond) sont cachés, sauf demande
export const TAILLE_POINTS = 0.06;        // m : un peu plus que la grille de 5 cm, pour un nuage plein
// G1 debout : 0,208 m d'avant en arrière, 0,477 m de large, 1,315 m de haut (robot proxy de g1_sim)
const ROBOT = { longueur: 0.208, largeur: 0.477, hauteur: 1.315 };
// Couleurs de repli si le thème ne se lit pas (mêmes valeurs que css/theme.css)
const REPLI = {
  '--vue-fond': '#1e1e1e', '--vue-grille': '#34343c', '--nuage-bas': '#2e9e6b', '--nuage-milieu': '#ccad78',
  '--nuage-haut': '#db3866', '--trajet': '#e0453a', '--repere-robot': '#e8772e', '--nuage-sol': '#4b5468',
};
// m : les points plus bas sont le sol, de la couleur --nuage-sol (comme la carte 3D : SEUIL_SOL)
export const SEUIL_SOL = 0.12;

function jeton(nom) {
  try {
    const v = getComputedStyle(document.documentElement).getPropertyValue(nom).trim();
    return v || REPLI[nom];
  } catch (e) {
    return REPLI[nom];
  }
}

// Lit les en-têtes X-Nuage-* d'une réponse (section 12.4) : {points, grille, bornes, source, date, session}
export function lireEntetesNuage(reponse) {
  const h = (n) => reponse.headers.get('X-Nuage-' + n);
  const b = (h('Bornes') || '').split(',').map(Number);
  return {
    points: parseInt(h('Points') || '0', 10), grille: parseFloat(h('Grille') || '0'),
    bornes: b.length === 6 ? { xmin: b[0], ymin: b[1], zmin: b[2], xmax: b[3], ymax: b[4], zmax: b[5] } : null,
    source: h('Source'), date: h('Date'), session: h('Session') || null,
  };
}

// Télécharge un nuage binaire : {positions (Float32Array), entete}. Rejet avec un message en français ;
// e.statut vaut 404 quand il n'y a pas (encore) de nuage.
export async function telechargerNuage(url) {
  let reponse;
  try {
    reponse = await fetch(url, { cache: 'no-cache' });
  } catch (e) {
    const err = new Error('Le serveur de l\'Atelier ne répond pas : le nuage 3D n\'a pas pu être lu.');
    err.statut = 0;
    throw err;
  }
  if (!reponse.ok) {
    let detail = 'Nuage 3D indisponible (erreur ' + reponse.status + ').';
    try {
      const d = await reponse.json();
      if (d && d.detail) detail = d.detail;
    } catch (e) {
      // pas de JSON : le message par défaut
    }
    const err = new Error(detail);
    err.statut = reponse.status;
    throw err;
  }
  const entete = lireEntetesNuage(reponse);
  const tampon = await reponse.arrayBuffer();
  const n = Math.floor(tampon.byteLength / 12);
  return { positions: new Float32Array(tampon, 0, n * 3), entete: entete };
}

function robot(couleur) {
  const g = new THREE.Group();
  const corps = new THREE.Mesh(new THREE.BoxGeometry(ROBOT.longueur, ROBOT.largeur, ROBOT.hauteur),
    new THREE.MeshLambertMaterial({ color: couleur }));
  corps.position.z = ROBOT.hauteur / 2;
  g.add(corps);
  const nez = new THREE.Mesh(new THREE.BoxGeometry(0.16, 0.14, 0.1), new THREE.MeshLambertMaterial({ color: 0xffffff }));
  nez.position.set(ROBOT.longueur / 2 + 0.07, 0, 1.2);      // tête et LiDAR vers 1,2 m : l'avant du robot
  g.add(nez);
  return g;
}

export class Nuage3D {
  // options : {nomGlobal ('scanNuage3d' : window.scanNuage3d pour les tests), hauteurCoupe, taille}
  constructor(element, options) {
    const o = options || {};
    this.element = element;
    this.ok = false;
    this.cadre = false;
    this.suivreRobot = true;
    this.plafondVisible = false;
    this.hauteurCoupe = o.hauteurCoupe || HAUTEUR_COUPE;
    this.taille = o.taille || TAILLE_POINTS;
    this.tailleCadrage = o.tailleCadrage || 6;     // m : le premier cadrage montre au moins cette largeur
    this.positions = new Float32Array(0);
    this.bornes = null;
    this.trajetPoints = 0;
    this.prevu = false;
    if (o.nomGlobal) window[o.nomGlobal] = this;
    try {
      this.rendu = new THREE.WebGLRenderer({ antialias: true });
    } catch (e) {
      const m = document.createElement('div');
      m.className = 'nuage3d-absent';
      m.dataset.role = 'scan-sans-webgl';
      m.textContent = 'La vue 3D n\'est pas disponible dans ce navigateur (WebGL manque) : la vue de dessus suffit.';
      element.appendChild(m);
      return;
    }
    this.ok = true;
    this.rendu.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    element.appendChild(this.rendu.domElement);
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(jeton('--vue-fond'));
    this.couleurs = [new THREE.Color(jeton('--nuage-bas')), new THREE.Color(jeton('--nuage-milieu')),
      new THREE.Color(jeton('--nuage-haut'))];
    this.couleurSol = new THREE.Color(jeton('--nuage-sol'));
    this.camera = new THREE.PerspectiveCamera(50, 1, 0.1, 800);
    this.camera.up.set(0, 0, 1);
    this.camera.position.set(-8, -14, 14);
    this.controles = new OrbitControls(this.camera, this.rendu.domElement);
    this.controles.target.set(0, 0, 0);
    this.controles.maxPolarAngle = Math.PI / 2 - 0.03;         // jamais sous le sol
    this.controles.screenSpacePanning = false;
    this.controles.addEventListener('change', () => this.demanderRendu());
    this.controles.addEventListener('start', () => { this.suivreRobot = false; });   // l'utilisateur reprend la main
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x445566, 1.2));
    this.points = new THREE.Points(new THREE.BufferGeometry(),
      new THREE.PointsMaterial({ size: this.taille, vertexColors: true, sizeAttenuation: true }));
    this.scene.add(this.points);
    this.ligne = new THREE.Line(new THREE.BufferGeometry(),
      new THREE.LineBasicMaterial({ color: new THREE.Color(jeton('--trajet')) }));
    this.scene.add(this.ligne);
    this.grille = null;
    this.robot = robot(new THREE.Color(jeton('--repere-robot')));
    this.robot.visible = false;
    this.scene.add(this.robot);
    this.observateur = new ResizeObserver(() => this.redimensionner());
    this.observateur.observe(element);
    this.redimensionner();
  }

  demanderRendu() {
    if (!this.ok || this.prevu) return;
    this.prevu = true;
    requestAnimationFrame(() => {
      this.prevu = false;
      if (this.ok) this.rendu.render(this.scene, this.camera);
    });
  }

  redimensionner() {
    if (!this.ok) return;
    const l = Math.max(this.element.clientWidth, 50);
    const h = Math.max(this.element.clientHeight, 50);
    this.rendu.setSize(l, h, false);
    this.camera.aspect = l / h;
    this.camera.updateProjectionMatrix();
    this.demanderRendu();
  }

  // Couleur d'un point d'après sa hauteur au-dessus du sol (dégradé à trois couleurs)
  couleur(h, c) {
    const t = Math.min(1, Math.max(0, h / HAUTEUR_COULEURS));
    if (t < 0.5) c.copy(this.couleurs[0]).lerp(this.couleurs[1], t / 0.5);
    else c.copy(this.couleurs[1]).lerp(this.couleurs[2], (t - 0.5) / 0.5);
    return c;
  }

  // Grille d'un mètre au sol sur les bornes, et vue d'ensemble depuis le sud-ouest
  cadrer(b) {
    if (!this.ok || !b) return;
    const cx = (b.xmin + b.xmax) / 2;
    const cy = (b.ymin + b.ymax) / 2;
    const taille = Math.max(b.xmax - b.xmin, b.ymax - b.ymin, this.tailleCadrage);
    this.controles.target.set(cx, cy, 0);
    this.camera.position.set(cx - 0.35 * taille, cy - 0.75 * taille, 0.75 * taille);
    this.controles.update();
    this.dessinerGrille(b);
    this.cadre = true;
    this.demanderRendu();
  }

  dessinerGrille(b) {
    if (this.grille) {
      this.scene.remove(this.grille);
      this.grille.geometry.dispose();
    }
    const traits = [];
    const x0 = Math.floor(b.xmin) - 1;
    const x1 = Math.ceil(b.xmax) + 1;
    const y0 = Math.floor(b.ymin) - 1;
    const y1 = Math.ceil(b.ymax) + 1;
    for (let x = x0; x <= x1; x += 1) traits.push(x, y0, -0.01, x, y1, -0.01);
    for (let y = y0; y <= y1; y += 1) traits.push(x0, y, -0.01, x1, y, -0.01);
    this.bornesGrille = { xmin: x0, ymin: y0, xmax: x1, ymax: y1 };
    const geometrie = new THREE.BufferGeometry();
    geometrie.setAttribute('position', new THREE.Float32BufferAttribute(traits, 3));
    this.grille = new THREE.LineSegments(geometrie, new THREE.LineBasicMaterial({ color: new THREE.Color(jeton('--vue-grille')) }));
    this.scene.add(this.grille);
  }

  // Vue de dessus, ou vue oblique (« iso »), sur ce qui est montré
  vue(nom) {
    if (!this.ok) return;
    const b = this.bornes || { xmin: -5, ymin: -5, xmax: 5, ymax: 5 };
    const cx = (b.xmin + b.xmax) / 2;
    const cy = (b.ymin + b.ymax) / 2;
    const taille = Math.max(b.xmax - b.xmin, b.ymax - b.ymin, 6);
    this.suivreRobot = false;
    this.controles.target.set(cx, cy, 0);
    if (nom === 'dessus') this.camera.position.set(cx, cy - 0.01, 1.2 * taille);
    else this.camera.position.set(cx - 0.35 * taille, cy - 0.75 * taille, 0.75 * taille);
    this.controles.update();
    this.demanderRendu();
  }

  // Oublie le cadrage : le prochain nuage montré est recadré (largeur au moins tailleCadrage mètres)
  recommencer(tailleCadrage) {
    this.cadre = false;
    if (tailleCadrage) this.tailleCadrage = tailleCadrage;
    this.suivreRobot = true;
  }

  // positions : Float32Array x y z… (z : hauteur au-dessus du sol) ; bornes : {xmin, ymin, xmax, ymax} ou null
  afficherPoints(positions, bornes) {
    if (!this.ok) return;
    this.positions = positions || new Float32Array(0);
    if (bornes) this.bornes = bornes;
    else if (this.positions.length) this.bornes = this.calculerBornes(this.positions);
    this.construirePoints();
    if (!this.cadre && this.bornes && this.positions.length) this.cadrer(this.bornes);
    else if (this.cadre && this.bornes && this.grilleTrop(this.bornes)) this.dessinerGrille(this.bornes);
    this.demanderRendu();
  }

  // Vrai si les bornes sortent de la grille dessinée (le nuage du scan grandit) : on la redessine
  grilleTrop(b) {
    const g = this.bornesGrille;
    return !g || b.xmin < g.xmin || b.ymin < g.ymin || b.xmax > g.xmax || b.ymax > g.ymax;
  }

  calculerBornes(p) {
    let xmin = Infinity;
    let ymin = Infinity;
    let xmax = -Infinity;
    let ymax = -Infinity;
    for (let i = 0; i < p.length; i += 3) {
      if (p[i] < xmin) xmin = p[i];
      if (p[i] > xmax) xmax = p[i];
      if (p[i + 1] < ymin) ymin = p[i + 1];
      if (p[i + 1] > ymax) ymax = p[i + 1];
    }
    return { xmin: xmin, ymin: ymin, xmax: xmax, ymax: ymax };
  }

  // Géométrie des points montrés : sans le plafond (au-dessus de hauteurCoupe), sauf si demandé
  construirePoints() {
    const p = this.positions;
    const n = Math.floor(p.length / 3);
    const coupe = this.plafondVisible ? Infinity : this.hauteurCoupe;
    let garde = 0;
    for (let i = 0; i < n; i += 1) if (p[3 * i + 2] <= coupe) garde += 1;
    const positions = new Float32Array(garde * 3);
    const couleurs = new Float32Array(garde * 3);
    const c = new THREE.Color();
    let k = 0;
    for (let i = 0; i < n; i += 1) {
      const z = p[3 * i + 2];
      if (z > coupe) continue;
      positions[3 * k] = p[3 * i];
      positions[3 * k + 1] = p[3 * i + 1];
      positions[3 * k + 2] = z;
      if (z < SEUIL_SOL) c.copy(this.couleurSol);       // le sol ne domine pas la vue
      else this.couleur(z, c);
      couleurs[3 * k] = c.r;
      couleurs[3 * k + 1] = c.g;
      couleurs[3 * k + 2] = c.b;
      k += 1;
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    g.setAttribute('color', new THREE.BufferAttribute(couleurs, 3));
    this.points.geometry.dispose();
    this.points.geometry = g;
  }

  // Charge un nuage binaire (GET …/nuage) et l'affiche ; renvoie la promesse de {points, entete}
  async chargerBinaire(url) {
    const r = await telechargerNuage(url);
    const b = r.entete.bornes;
    this.grilleNuage(r.entete.grille);
    this.afficherPoints(r.positions, b ? { xmin: b.xmin, ymin: b.ymin, xmax: b.xmax, ymax: b.ymax } : null);
    return { points: r.positions.length / 3, entete: r.entete };
  }

  // Taille des points : celle de la grille du nuage montré (5 cm pour un nuage traité, 10 cm pour l'aperçu en
  // direct : le nuage paraît plein, pas clairsemé), fois le facteur du curseur « Taille des points »
  grilleNuage(grille) {
    if (grille > 0) this.taille = Math.max(TAILLE_POINTS, 1.15 * grille);
    this.majTaille();
  }

  facteurTaille(f) {
    this.facteur = Math.min(3, Math.max(0.3, Number(f) || 1));
    this.majTaille();
  }

  majTaille() {
    if (!this.ok) return;
    this.points.material.size = this.taille * (this.facteur || 1);
    this.demanderRendu();
  }

  // Trajet [[x, y, theta], …], dessiné juste au-dessus du sol
  afficherTrajet(trajet) {
    if (!this.ok) return;
    const t = (trajet || []).map((q) => new THREE.Vector3(q[0], q[1], 0.04));
    this.trajetPoints = t.length;
    this.ligne.geometry.dispose();
    this.ligne.geometry = new THREE.BufferGeometry().setFromPoints(t);
    this.demanderRendu();
  }

  // Le robot {x, y, theta} ou null ; la caméra le suit tant que l'utilisateur ne l'a pas déplacée
  afficherRobot(pose) {
    if (!this.ok) return;
    this.robot.visible = !!pose;
    if (pose) {
      this.robot.position.set(pose.x, pose.y, 0);
      this.robot.rotation.z = pose.theta || 0;
      if (this.suivreRobot && this.cadre) {
        const d = new THREE.Vector3(pose.x, pose.y, 0).sub(this.controles.target);
        this.controles.target.add(d);
        this.camera.position.add(d);
        this.controles.update();
      }
    }
    this.demanderRendu();
  }

  suivre(oui) {
    this.suivreRobot = !!oui;
    if (oui && this.ok && this.robot.visible) this.afficherRobot({ x: this.robot.position.x, y: this.robot.position.y, theta: this.robot.rotation.z });
  }

  plafond(oui) {
    this.plafondVisible = !!oui;
    if (this.ok) {
      this.construirePoints();
      this.demanderRendu();
    }
  }

  // Ancien format : le contenu d'apercu.json (section 9.2), sans nuage binaire : trajet, robot, points
  afficher(apercu) {
    if (!this.ok || !apercu) return;
    if (!this.cadre && apercu.bornes) this.cadrer(apercu.bornes);
    const sol = typeof apercu.sol === 'number' ? apercu.sol : 0;
    const pts = apercu.points || [];
    const positions = new Float32Array(pts.length * 3);
    pts.forEach((p, i) => {
      positions[3 * i] = p[0];
      positions[3 * i + 1] = p[1];
      positions[3 * i + 2] = p[2] - sol;
    });
    this.afficherPoints(positions, apercu.bornes || null);
    this.afficherTrajet(apercu.trajectoire);
    this.afficherRobot(apercu.robot ? { x: apercu.robot.x, y: apercu.robot.y, theta: apercu.robot.theta } : null);
  }

  nombrePoints() {
    const a = this.ok ? this.points.geometry.getAttribute('position') : null;
    return a ? a.count : 0;
  }

  etat() {
    return { webgl: this.ok, points: this.positions.length / 3, montres: this.nombrePoints(), trajet: this.trajetPoints,
      suivre: this.suivreRobot, plafond: this.plafondVisible, robot: this.ok && this.robot.visible };
  }

  detruire() {
    if (!this.ok) return;
    this.ok = false;
    this.observateur.disconnect();
    this.controles.dispose();
    this.scene.traverse((o) => {
      if (o.geometry) o.geometry.dispose();
      if (o.material) o.material.dispose();
    });
    this.rendu.dispose();
    this.rendu.domElement.remove();
  }
}
