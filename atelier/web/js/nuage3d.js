// Nuage de points 3D de l'aperçu du scan (apercu.json), avec three.js : les points vus par le
// LiDAR, colorés selon leur hauteur au-dessus du sol, la trajectoire et le robot.
// Repère map gardé tel quel (z vers le haut), comme vue3d.js.

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/OrbitControls.js';

const HAUTEUR_COULEURS = 2.0;      // m : du bleu (sol) au rouge (2 m et plus)
// G1 debout : 0,208 m d'avant en arrière, 0,477 m de large, 1,315 m de haut (robot proxy de g1_sim)
const ROBOT = { longueur: 0.208, largeur: 0.477, hauteur: 1.315 };

function couleurHauteur(t, couleur) {
  const u = Math.min(1, Math.max(0, t / HAUTEUR_COULEURS));
  return couleur.setHSL(0.66 * (1 - u), 0.85, 0.5);
}

function robot() {
  const g = new THREE.Group();
  const corps = new THREE.Mesh(new THREE.BoxGeometry(ROBOT.longueur, ROBOT.largeur, ROBOT.hauteur),
    new THREE.MeshLambertMaterial({ color: 0xe8772e }));
  corps.position.z = ROBOT.hauteur / 2;
  g.add(corps);
  const nez = new THREE.Mesh(new THREE.BoxGeometry(0.1, 0.12, 0.08), new THREE.MeshLambertMaterial({ color: 0x222222 }));
  nez.position.set(ROBOT.longueur / 2 + 0.05, 0, 1.2);      // tête et LiDAR vers 1,2 m
  g.add(nez);
  return g;
}

export class Nuage3D {
  constructor(element) {
    this.element = element;
    this.ok = false;
    this.cadre = false;
    try {
      this.rendu = new THREE.WebGLRenderer({ antialias: true });
    } catch (e) {
      element.textContent = 'La vue 3D n\'est pas disponible dans ce navigateur (WebGL manque) : l\'aperçu 2D suffit.';
      element.classList.add('vue3d-absente');
      return;
    }
    this.ok = true;
    this.rendu.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    element.appendChild(this.rendu.domElement);
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x10151d);
    this.camera = new THREE.PerspectiveCamera(50, 1, 0.1, 500);
    this.camera.up.set(0, 0, 1);
    this.camera.position.set(-5, -15, 18);
    this.controles = new OrbitControls(this.camera, this.rendu.domElement);
    this.controles.target.set(10, 8, 0);
    this.controles.maxPolarAngle = Math.PI / 2 - 0.05;
    this.controles.addEventListener('change', () => this.demanderRendu());
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x445566, 1.2));
    this.points = new THREE.Points(new THREE.BufferGeometry(),
      new THREE.PointsMaterial({ size: 0.07, vertexColors: true, sizeAttenuation: true }));
    this.scene.add(this.points);
    this.ligne = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ color: 0xffb070 }));
    this.scene.add(this.ligne);
    this.grille = null;
    this.robot = robot();
    this.robot.visible = false;
    this.scene.add(this.robot);
    this.observateur = new ResizeObserver(() => this.redimensionner());
    this.observateur.observe(element);
    this.redimensionner();
    this.actif = true;
    this.aRendre = true;
    const boucle = () => {
      if (!this.actif) return;
      if (this.aRendre) {
        this.aRendre = false;
        this.rendu.render(this.scene, this.camera);
      }
      requestAnimationFrame(boucle);
    };
    requestAnimationFrame(boucle);
  }

  demanderRendu() {
    this.aRendre = true;
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

  // Vue d'ensemble des bornes {xmin, ymin, xmax, ymax}, depuis le sud, et grille d'un mètre au sol
  cadrer(b) {
    if (!this.ok || !b) return;
    const cx = (b.xmin + b.xmax) / 2;
    const cy = (b.ymin + b.ymax) / 2;
    const taille = Math.max(b.xmax - b.xmin, b.ymax - b.ymin, 5);
    this.controles.target.set(cx, cy, 0);
    this.camera.position.set(cx, cy - 0.6 * taille, 0.8 * taille);
    this.controles.update();
    if (this.grille) {
      this.scene.remove(this.grille);
      this.grille.geometry.dispose();
    }
    const traits = [];
    for (let x = Math.ceil(b.xmin); x <= b.xmax; x += 1) traits.push(x, b.ymin, 0, x, b.ymax, 0);
    for (let y = Math.ceil(b.ymin); y <= b.ymax; y += 1) traits.push(b.xmin, y, 0, b.xmax, y, 0);
    const geometrie = new THREE.BufferGeometry();
    geometrie.setAttribute('position', new THREE.Float32BufferAttribute(traits, 3));
    this.grille = new THREE.LineSegments(geometrie, new THREE.LineBasicMaterial({ color: 0x2b3442 }));
    this.scene.add(this.grille);
    this.demanderRendu();
  }

  // apercu : le contenu d'apercu.json (section 9.2 du plan)
  afficher(apercu) {
    if (!this.ok || !apercu) return;
    if (!this.cadre && apercu.bornes) {
      this.cadrer(apercu.bornes);
      this.cadre = true;
    }
    const sol = typeof apercu.sol === 'number' ? apercu.sol : 0;
    const pts = apercu.points || [];
    const positions = new Float32Array(pts.length * 3);
    const couleurs = new Float32Array(pts.length * 3);
    const c = new THREE.Color();
    pts.forEach((p, i) => {
      positions[3 * i] = p[0];
      positions[3 * i + 1] = p[1];
      positions[3 * i + 2] = p[2] - sol;
      couleurHauteur(p[2] - sol, c);
      couleurs[3 * i] = c.r;
      couleurs[3 * i + 1] = c.g;
      couleurs[3 * i + 2] = c.b;
    });
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    g.setAttribute('color', new THREE.BufferAttribute(couleurs, 3));
    this.points.geometry.dispose();
    this.points.geometry = g;
    const traj = (apercu.trajectoire || []).map((q) => new THREE.Vector3(q[0], q[1], 0.03));
    this.ligne.geometry.dispose();
    this.ligne.geometry = new THREE.BufferGeometry().setFromPoints(traj);
    const r = apercu.robot;
    this.robot.visible = !!r;
    if (r) {
      this.robot.position.set(r.x, r.y, 0);
      this.robot.rotation.z = r.theta || 0;
    }
    this.demanderRendu();
  }

  nombrePoints() {
    const a = this.ok ? this.points.geometry.getAttribute('position') : null;
    return a ? a.count : 0;
  }

  detruire() {
    if (!this.ok) return;
    this.actif = false;
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
