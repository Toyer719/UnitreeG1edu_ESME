// Vue 3D du monde avec three.js : murs, objets, piétons et robot.
// On garde le repère map tel quel : x vers l'est, y vers le nord, z vers le haut
// (la caméra a z comme verticale), donc aucune conversion de coordonnées.

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/OrbitControls.js';
import { MOBILIER, capMur, longueurMur } from './geometrie.js';

const COULEURS = {
  sol: 0xe9e6df, mur: 0xd8cfc0, murChoisi: 0x2f6fd6, boite: 0x9b7653, poteau: 0x8d939a,
  meuble: 0xb08a5a, poubelle: 0x5c7d5c, pieton: 0x3a7bd5, robot: 0xe8772e, nez: 0x222222,
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

function cylindre(rayon, hauteur, couleur, z0) {
  const m = new THREE.Mesh(new THREE.CylinderGeometry(rayon, rayon, hauteur, 24), materiau(couleur));
  m.rotation.x = Math.PI / 2;           // l'axe des cylindres de three.js est y : on le met sur z
  m.position.z = (z0 || 0) + hauteur / 2;
  return m;
}

// Meubles simplifiés, à l'encombrement du contrat (chaise, table, banc, poubelle)
function meuble(modele) {
  const g = new THREE.Group();
  const d = MOBILIER[modele];
  const c = COULEURS.meuble;
  if (modele === 'poubelle') {
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
    g.add(pave(0.5, 0.5, 0.5, c));
  }
  return g;
}

function pieton() {
  const g = new THREE.Group();
  g.add(cylindre(0.2, 1.4, COULEURS.pieton));
  const tete = new THREE.Mesh(new THREE.SphereGeometry(0.13, 16, 12), materiau(0xf0c8a0));
  tete.position.z = 1.58;
  g.add(tete);
  return g;
}

// Robot proxy du contrat : boîte de 0,45 × 0,30 × 1,30 m, avec un nez qui montre l'avant
function robot() {
  const g = new THREE.Group();
  g.add(pave(0.45, 0.30, 1.30, COULEURS.robot));
  const nez = pave(0.12, 0.10, 0.10, COULEURS.nez, 1.05);
  nez.position.x = 0.26;
  g.add(nez);
  return g;
}

function liberer(objet) {
  objet.traverse((o) => {
    if (o.geometry) o.geometry.dispose();
    if (o.material) o.material.dispose();
  });
}

export class Vue3D {
  // element : le conteneur. Si WebGL manque, un message remplace la vue (this.ok vaut false).
  constructor(element) {
    this.element = element;
    this.ok = false;
    this.pietons = new Map();
    this.choisi = null;
    try {
      this.rendu = new THREE.WebGLRenderer({ antialias: true });
    } catch (e) {
      element.innerHTML = '<p class="vue3d-absente">La vue 3D n\'est pas disponible dans ce navigateur '
        + '(WebGL manque). Le reste de l\'Atelier fonctionne.</p>';
      return;
    }
    this.ok = true;
    this.rendu.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    element.appendChild(this.rendu.domElement);
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0xf4f6f8);
    this.camera = new THREE.PerspectiveCamera(50, 1, 0.1, 500);
    this.camera.up.set(0, 0, 1);
    this.camera.position.set(-5, -15, 18);
    this.controles = new OrbitControls(this.camera, this.rendu.domElement);
    this.controles.target.set(10, 8, 0);
    this.controles.maxPolarAngle = Math.PI / 2 - 0.05;    // pas sous le sol
    this.controles.addEventListener('change', () => this.demanderRendu());
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x888877, 1.1));
    const soleil = new THREE.DirectionalLight(0xffffff, 1.4);
    soleil.position.set(-10, -20, 30);
    this.scene.add(soleil);
    this.groupeMonde = new THREE.Group();
    this.scene.add(this.groupeMonde);
    this.groupePietons = new THREE.Group();
    this.scene.add(this.groupePietons);
    this.robot = robot();
    this.robot.visible = false;
    this.scene.add(this.robot);
    this.observateur = new ResizeObserver(() => this.redimensionner());
    this.observateur.observe(element);
    this.redimensionner();
    this.aRendre = true;
    this.actif = true;
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

  // Vue d'ensemble de l'emprise, depuis le sud, assez haut pour voir le fond des couloirs
  cadrer(emprise) {
    if (!this.ok || !emprise) return;
    const cx = (emprise.min[0] + emprise.max[0]) / 2;
    const cy = (emprise.min[1] + emprise.max[1]) / 2;
    const taille = Math.max(emprise.max[0] - emprise.min[0], emprise.max[1] - emprise.min[1], 5);
    this.controles.target.set(cx, cy, 0);
    this.camera.position.set(cx, cy - 0.5 * taille, 0.85 * taille);
    this.controles.update();
    this.demanderRendu();
  }

  // Reconstruit toute la scène depuis le monde (format de monde.yaml). choisi : id à surligner.
  afficherMonde(monde, choisi, avecPietons) {
    if (!this.ok) return;
    this.scene.remove(this.groupeMonde);
    liberer(this.groupeMonde);
    const g = new THREE.Group();
    this.groupeMonde = g;
    this.scene.add(g);
    if (!monde) {
      this.demanderRendu();
      return;
    }
    const e = monde.emprise;
    const lx = e.max[0] - e.min[0], ly = e.max[1] - e.min[1];
    const sol = new THREE.Mesh(new THREE.PlaneGeometry(lx, ly), materiau(COULEURS.sol));
    sol.position.set(e.min[0] + lx / 2, e.min[1] + ly / 2, 0);
    g.add(sol);
    // grille d'un mètre, posée sur le sol, limitée à l'emprise
    const traits = [];
    for (let x = Math.ceil(e.min[0]); x <= e.max[0] + 1e-9; x += 1) traits.push(x, e.min[1], 0.003, x, e.max[1], 0.003);
    for (let y = Math.ceil(e.min[1]); y <= e.max[1] + 1e-9; y += 1) traits.push(e.min[0], y, 0.003, e.max[0], y, 0.003);
    const geometrieGrille = new THREE.BufferGeometry();
    geometrieGrille.setAttribute('position', new THREE.Float32BufferAttribute(traits, 3));
    g.add(new THREE.LineSegments(geometrieGrille, new THREE.LineBasicMaterial({ color: 0xcfcac0 })));

    monde.murs.forEach((m) => {
      const L = longueurMur(m);
      if (L <= 0) return;
      const b = pave(L, m.epaisseur, m.hauteur, m.id === choisi ? COULEURS.murChoisi : COULEURS.mur);
      b.position.x = (m.de[0] + m.a[0]) / 2;
      b.position.y = (m.de[1] + m.a[1]) / 2;
      b.rotation.z = capMur(m);
      g.add(b);
    });
    monde.objets.forEach((o) => {
      let obj;
      if (o.type === 'boite') obj = pave(o.taille[0], o.taille[1], o.taille[2], COULEURS.boite);
      else if (o.type === 'cylindre') obj = cylindre(o.rayon, o.hauteur, COULEURS.poteau);
      else obj = meuble(o.modele);
      const support = new THREE.Group();
      support.add(obj);
      support.position.set(o.centre[0], o.centre[1], 0);
      support.rotation.z = o.cap || 0;
      if (o.id === choisi) support.add(new THREE.BoxHelper(obj, COULEURS.murChoisi));
      g.add(support);
    });
    if (avecPietons !== false) {
      monde.pietons.forEach((p) => {
        const h = pieton();
        h.position.set(p.trajet[0][0], p.trajet[0][1], 0);
        g.add(h);
        const points = p.trajet.map((q) => new THREE.Vector3(q[0], q[1], 0.02));
        if (!p.aller_retour) points.push(points[0].clone());
        const ligne = new THREE.Line(new THREE.BufferGeometry().setFromPoints(points),
          new THREE.LineBasicMaterial({ color: COULEURS.pieton }));
        g.add(ligne);
      });
    }
    if (monde.depart_robot && !this.robotEnDirect) {
      this.placerRobot(monde.depart_robot.x, monde.depart_robot.y, monde.depart_robot.theta);
    }
    this.demanderRendu();
  }

  placerRobot(x, y, theta) {
    if (!this.ok) return;
    this.robot.visible = true;
    this.robot.position.set(x, y, 0);
    this.robot.rotation.z = theta || 0;
    this.demanderRendu();
  }

  cacherRobot() {
    if (!this.ok) return;
    this.robot.visible = false;
    this.demanderRendu();
  }

  // Piétons en direct : liste [{id, x, y, theta}]
  placerPietons(liste) {
    if (!this.ok) return;
    const vus = new Set();
    (liste || []).forEach((p) => {
      let h = this.pietons.get(p.id);
      if (!h) {
        h = pieton();
        this.pietons.set(p.id, h);
        this.groupePietons.add(h);
      }
      h.position.set(p.x, p.y, 0);
      h.rotation.z = p.theta || 0;
      vus.add(p.id);
    });
    this.pietons.forEach((h, id) => {
      if (!vus.has(id)) {
        this.groupePietons.remove(h);
        liberer(h);
        this.pietons.delete(id);
      }
    });
    this.demanderRendu();
  }

  detruire() {
    if (!this.ok) return;
    this.actif = false;
    this.observateur.disconnect();
    this.controles.dispose();
    liberer(this.scene);
    this.rendu.dispose();
    this.rendu.domElement.remove();
  }
}
