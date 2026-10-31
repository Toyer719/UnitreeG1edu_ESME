// Aperçu 3D du G1 pour les chorégraphies (section 11.5 du plan) et la Vue du robot (11.13) : le modèle de l'URDF g1_29dof_rev_1_0
// (GET /api/pilotage/modele) et ses maillages STL (models/g1_proxy/meshes), animés articulation par
// articulation. Repère du robot : x vers l'avant, y vers la gauche, z vers le haut (comme l'URDF).
//
// Deux rendus : three.js (WebGL, avec les maillages) ; sans WebGL (Firefox sans fenêtre des tests,
// vieux navigateur), un dessin 2D en perspective du squelette des mêmes articulations. Les deux
// comptent les images dessinées (this.images), exposées aussi dans window.apercuPilotage (ou le nom
// donné par options.nomGlobal : window.vueRobot3d pour la Vue du robot).

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/OrbitControls.js';
import { api } from '../api.js';

const HAUTEUR_BASSIN = 0.793;          // m, bassin du G1 debout au-dessus du sol
const PARALLELE = 6;                   // maillages téléchargés en même temps
const COULEUR_GAUCHE = '#2f6fd6';
const COULEUR_DROITE = '#e8772e';
const COULEUR_CORPS = '#6b7280';
const HAUTEUR_COU = 0.32;              // m au-dessus de l'origine du torse (dessin sans WebGL)
const POSITION_TETE = [0.0, 0, 0.42];  // centre de la tête, dans le repère du torse
const POSITION_LED = [0.085, 0, 0.42]; // LED devant la tête (à vérifier sur le robot)
const SEMELLE = 0.035;                 // m, de l'origine de la cheville (ankle_roll_link) à la semelle
const DESSOUS_BASSIN = 0.1;            // m, de l'origine du bassin à son dessous (robot assis par terre)

// Squelette de secours si l'URDF manque : les mêmes noms d'articulations, longueurs approchées
const SQUELETTE_SECOURS = (function construire() {
  const a = [];
  const j = (nom, parent, enfant, xyz, axe, type) => a.push({ nom, type: type || 'revolute', parent, enfant, xyz, rpy: [0, 0, 0], axe });
  j('waist_yaw_joint', 'pelvis', 'torso_link', [0, 0, 0.05], [0, 0, 1]);
  j('head_joint', 'torso_link', 'head_link', [0, 0, 0.45], [0, 0, 1], 'fixed');
  [['left', 1], ['right', -1]].forEach(([c, s]) => {
    j(c + '_hip_pitch_joint', 'pelvis', c + '_hip_link', [0, 0.09 * s, -0.08], [0, 1, 0]);
    j(c + '_knee_joint', c + '_hip_link', c + '_knee_link', [0, 0, -0.33], [0, 1, 0]);
    j(c + '_ankle_pitch_joint', c + '_knee_link', c + '_ankle_pitch_link', [0, 0, -0.33], [0, 1, 0]);
    j(c + '_shoulder_pitch_joint', 'torso_link', c + '_shoulder_pitch_link', [0, 0.15 * s, 0.3], [0, 1, 0]);
    j(c + '_shoulder_roll_joint', c + '_shoulder_pitch_link', c + '_shoulder_roll_link', [0, 0.03 * s, 0], [1, 0, 0]);
    j(c + '_shoulder_yaw_joint', c + '_shoulder_roll_link', c + '_shoulder_yaw_link', [0, 0, -0.1], [0, 0, 1]);
    j(c + '_elbow_joint', c + '_shoulder_yaw_link', c + '_elbow_link', [0.01, 0, -0.08], [0, 1, 0]);
    j(c + '_wrist_roll_joint', c + '_elbow_link', c + '_wrist_roll_link', [0.1, 0, 0], [1, 0, 0]);
    j(c + '_wrist_pitch_joint', c + '_wrist_roll_link', c + '_wrist_pitch_link', [0.04, 0, 0], [0, 1, 0]);
    j(c + '_wrist_yaw_joint', c + '_wrist_pitch_link', c + '_wrist_yaw_link', [0.04, 0, 0], [0, 0, 1]);
    j(c + '_main_joint', c + '_wrist_yaw_link', c + '_main_link', [0.08, 0, 0], [0, 0, 1], 'fixed');
  });
  return { nom: 'g1_simplifie', racine: 'pelvis', liens: {}, articulations: a, maillages: false };
}());

// Maillage STL binaire (ou texte) → BufferGeometry
export function lireStl(tampon) {
  const vue = new DataView(tampon);
  const n = tampon.byteLength >= 84 ? vue.getUint32(80, true) : 0;
  const geometrie = new THREE.BufferGeometry();
  if (tampon.byteLength === 84 + n * 50 && n > 0) {
    const positions = new Float32Array(n * 9);
    const normales = new Float32Array(n * 9);
    for (let i = 0; i < n; i += 1) {
      const o = 84 + i * 50;
      const nx = vue.getFloat32(o, true);
      const ny = vue.getFloat32(o + 4, true);
      const nz = vue.getFloat32(o + 8, true);
      for (let k = 0; k < 3; k += 1) {
        const p = o + 12 + k * 12;
        const b = i * 9 + k * 3;
        positions[b] = vue.getFloat32(p, true);
        positions[b + 1] = vue.getFloat32(p + 4, true);
        positions[b + 2] = vue.getFloat32(p + 8, true);
        normales[b] = nx;
        normales[b + 1] = ny;
        normales[b + 2] = nz;
      }
    }
    geometrie.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geometrie.setAttribute('normal', new THREE.BufferAttribute(normales, 3));
    return geometrie;
  }
  const texte = new TextDecoder().decode(new Uint8Array(tampon));
  const valeurs = [];
  const motif = /vertex\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)/g;
  let m = motif.exec(texte);
  while (m) {
    valeurs.push(parseFloat(m[1]), parseFloat(m[2]), parseFloat(m[3]));
    m = motif.exec(texte);
  }
  geometrie.setAttribute('position', new THREE.BufferAttribute(new Float32Array(valeurs), 3));
  geometrie.computeVertexNormals();
  return geometrie;
}

function couleurCote(nom) {
  if (nom.indexOf('left') === 0) return COULEUR_GAUCHE;
  if (nom.indexOf('right') === 0) return COULEUR_DROITE;
  return COULEUR_CORPS;
}

const FOND_VUE = 0x1e1e1e;          // --vue-fond de theme.css

export class Apercu3D {
  // element : le conteneur. charger() lit le modèle ; poser(q, base, led, corps) place le G1.
  // options : {nomGlobal} (window.apercuPilotage par défaut), {camera: [x, y, z], cible: [x, y, z]}
  constructor(element, options) {
    this.element = element;
    this.nomGlobal = (options && options.nomGlobal) || 'apercuPilotage';
    this.images = 0;
    this.pret = false;
    this.maillagesCharges = 0;
    this.maillagesAttendus = 0;
    this.erreur = null;
    this.actif = true;
    this.aRendre = true;
    this.articulations = {};          // nom (sans _joint) → {groupe, axe}
    this.liens = {};                  // nom → Object3D (origine du lien)
    this.segments = [];               // [parent, enfant, couleur] pour le dessin sans WebGL
    this.scene = new THREE.Scene();
    // vague 5 (section 12.2, décision I6) : la vue 3D est toujours sombre, quel que soit le thème
    this.scene.background = new THREE.Color(FOND_VUE);
    this.camera = new THREE.PerspectiveCamera(40, 1, 0.05, 50);
    this.camera.up.set(0, 0, 1);
    const o = options || {};
    const position = o.camera || [2.6, 1.4, 1.5];
    this.camera.position.set(position[0], position[1], position[2]);
    this.cible = new THREE.Vector3(...(o.cible || [0, 0, 0.9]));
    this.distance2D = Math.hypot(position[0] - this.cible.x, position[1] - this.cible.y);
    this.hauteur2D = position[2];
    this.camera.lookAt(this.cible);
    try {
      this.rendu = new THREE.WebGLRenderer({ antialias: true });
      this.mode = 'webgl';
    } catch (e) {
      this.rendu = null;
      this.mode = 'canvas';
    }
    if (this.mode === 'webgl') {
      this.rendu.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      element.appendChild(this.rendu.domElement);
      this.controles = new OrbitControls(this.camera, this.rendu.domElement);
      this.controles.target.copy(this.cible);
      this.controles.update();         // sinon la caméra garde la cible du constructeur (l'origine, au sol)
      this.controles.addEventListener('change', () => this.demanderRendu());
      this.scene.add(new THREE.HemisphereLight(0xffffff, 0x8a8a80, 1.2));
      const soleil = new THREE.DirectionalLight(0xffffff, 1.3);
      soleil.position.set(3, -2, 5);
      this.scene.add(soleil);
      const grille = new THREE.GridHelper(4, 8, 0x6b6b88, 0x3a3a48);
      grille.rotation.x = Math.PI / 2;
      this.scene.add(grille);
    } else {
      this.toile = document.createElement('canvas');
      this.toile.className = 'apercu-toile';
      element.appendChild(this.toile);
      this.contexte = this.toile.getContext('2d');
      this.azimut = Math.atan2(this.camera.position.y - this.cible.y, this.camera.position.x - this.cible.x);
      this._glisser();
    }
    this.base = new THREE.Group();     // le robot dans son repère de départ (pas de marche)
    this.scene.add(this.base);
    this.bassin = new THREE.Group();
    this.bassin.position.z = HAUTEUR_BASSIN;
    this.base.add(this.bassin);
    this.led = null;
    this.observateur = new ResizeObserver(() => this.redimensionner());
    this.observateur.observe(element);
    this.redimensionner();
    window[this.nomGlobal] = this;
    const boucle = () => {
      if (!this.actif) return;
      if (this.aRendre) {
        this.aRendre = false;
        this.dessiner();
      }
      requestAnimationFrame(boucle);
    };
    requestAnimationFrame(boucle);
  }

  demanderRendu() {
    this.aRendre = true;
  }

  redimensionner() {
    const l = Math.max(this.element.clientWidth, 80);
    const h = Math.max(this.element.clientHeight, 80);
    this.camera.aspect = l / h;
    this.camera.updateProjectionMatrix();
    if (this.mode === 'webgl') {
      this.rendu.setSize(l, h, false);
    } else {
      const r = Math.min(window.devicePixelRatio || 1, 2);
      this.toile.width = Math.round(l * r);
      this.toile.height = Math.round(h * r);
      this.toile.style.width = l + 'px';
      this.toile.style.height = h + 'px';
    }
    this.demanderRendu();
  }

  // Lit le modèle, construit l'arbre des articulations, puis charge les maillages (WebGL seulement)
  async charger() {
    let modele;
    try {
      modele = await api.lire('/api/pilotage/modele');
    } catch (e) {
      modele = SQUELETTE_SECOURS;
      this.erreur = e.message;
    }
    this.modele = modele;
    this._construire(modele);
    this.pret = true;
    this.demanderRendu();
    if (this.mode === 'webgl' && modele.maillages) {
      await this._chargerMaillages(modele);
    }
    return this;
  }

  _construire(m) {
    const racine = new THREE.Group();
    racine.name = m.racine;
    this.bassin.add(racine);
    this.liens[m.racine] = racine;
    const restantes = m.articulations.slice();
    let progres = true;
    while (restantes.length && progres) {
      progres = false;
      for (let i = restantes.length - 1; i >= 0; i -= 1) {
        const a = restantes[i];
        const parent = this.liens[a.parent];
        if (!parent) continue;
        const origine = new THREE.Group();
        origine.position.set(a.xyz[0], a.xyz[1], a.xyz[2]);
        origine.quaternion.setFromEuler(new THREE.Euler(a.rpy[0], a.rpy[1], a.rpy[2], 'ZYX'));
        const tourne = new THREE.Group();
        tourne.name = a.enfant;
        origine.add(tourne);
        parent.add(origine);
        this.liens[a.enfant] = tourne;
        if (a.type !== 'fixed') {
          const axe = new THREE.Vector3(a.axe[0], a.axe[1], a.axe[2]).normalize();
          this.articulations[a.nom.replace(/_joint$/, '')] = { groupe: tourne, axe };
        }
        const capteur = /imu|d435|mid360|logo|head/.test(a.enfant);
        const epaule = a.parent === 'torso_link' && /shoulder_pitch/.test(a.enfant);
        if (!capteur && !epaule && Math.hypot(a.xyz[0], a.xyz[1], a.xyz[2]) > 0.015) {
          this.segments.push({ a: a.parent, b: a.enfant, couleur: couleurCote(a.enfant), largeur: 1 });
        }
        restantes.splice(i, 1);
        progres = true;
      }
    }
    // colonne, épaules et hanches du squelette (dessin sans WebGL), tête et LED sur le torse
    const torse = this.liens.torso_link ? 'torso_link' : m.racine;
    this.segments.push({ a: torse, b: torse, ob: [0, 0, HAUTEUR_COU], couleur: COULEUR_CORPS, largeur: 1.6 });
    [['left_shoulder_pitch_link', 'right_shoulder_pitch_link'], ['left_hip_pitch_link', 'right_hip_pitch_link']].forEach(([g, d]) => {
      if (this.liens[g] && this.liens[d]) this.segments.push({ a: g, b: d, couleur: COULEUR_CORPS, largeur: 1.3 });
    });
    this.lienTete = this.liens[torse];
    if (this.mode === 'webgl') {
      this.led = new THREE.Mesh(new THREE.SphereGeometry(0.03, 16, 12), new THREE.MeshBasicMaterial({ color: 0x222222 }));
      this.led.position.set(POSITION_LED[0], POSITION_LED[1], POSITION_LED[2]);
      this.lienTete.add(this.led);
    }
  }

  async _chargerMaillages(m) {
    const taches = [];
    Object.keys(m.liens).forEach((lien) => {
      (m.liens[lien] || []).forEach((v) => taches.push([lien, v]));
    });
    this.maillagesAttendus = taches.length;
    const materiaux = {};
    const prendre = async () => {
      while (taches.length && this.actif) {
        const [lien, v] = taches.shift();
        try {
          const r = await fetch('/api/pilotage/modele/maillages/' + encodeURIComponent(v.maillage));
          if (!r.ok) throw new Error('maillage ' + v.maillage + ' : ' + r.status);
          const geometrie = lireStl(await r.arrayBuffer());
          const c = v.couleur || [0.7, 0.7, 0.7, 1];
          const cle = c.join(',');
          if (!materiaux[cle]) materiaux[cle] = new THREE.MeshLambertMaterial({ color: new THREE.Color(c[0], c[1], c[2]) });
          const maille = new THREE.Mesh(geometrie, materiaux[cle]);
          maille.position.set(v.xyz[0], v.xyz[1], v.xyz[2]);
          maille.quaternion.setFromEuler(new THREE.Euler(v.rpy[0], v.rpy[1], v.rpy[2], 'ZYX'));
          if (this.liens[lien]) this.liens[lien].add(maille);
          this.maillagesCharges += 1;
          this.demanderRendu();
        } catch (e) {
          this.erreur = e.message;
        }
      }
    };
    const fils = [];
    for (let i = 0; i < PARALLELE; i += 1) fils.push(prendre());
    await Promise.all(fils);
  }

  // q : {articulation: angle} ; base : {x, y, cap} (repère de départ) ; led : {r, g, b} ou null ;
  // corps : {sol: true} pose le robot au sol (pieds, ou bassin s'il est assis), sinon bassin à 0,793 m
  poser(q, base, led, corps) {
    Object.keys(q || {}).forEach((nom) => {
      const a = this.articulations[nom];
      if (a) a.groupe.quaternion.setFromAxisAngle(a.axe, q[nom]);
    });
    this.bassin.position.z = HAUTEUR_BASSIN;
    if (corps && corps.sol) this._poserAuSol();
    if (base) {
      this.base.position.set(base.x, base.y, 0);
      this.base.rotation.set(0, 0, base.cap);
    }
    this.couleurLed = led ? 'rgb(' + led.r + ',' + led.g + ',' + led.b + ')' : null;
    if (this.led) this.led.material.color.set(this.couleurLed || '#222222');
    this.demanderRendu();
  }

  // Le point le plus bas (semelles, dessous du bassin) touche le sol
  _poserAuSol() {
    if (!this.contacts) {
      const noms = Object.keys(this.liens);
      let pieds = noms.filter((n) => /ankle_roll_link$/.test(n));
      if (!pieds.length) pieds = noms.filter((n) => /ankle_pitch_link$/.test(n));
      this.contacts = pieds.map((n) => [n, SEMELLE]);
      if (this.modele && this.liens[this.modele.racine]) this.contacts.push([this.modele.racine, DESSOUS_BASSIN]);
    }
    if (!this.contacts.length) return;
    this.base.updateMatrixWorld(true);
    let bas = Infinity;
    const v = new THREE.Vector3();
    this.contacts.forEach(([nom, sous]) => {
      this.liens[nom].getWorldPosition(v);
      bas = Math.min(bas, v.z - sous);
    });
    if (Number.isFinite(bas)) this.bassin.position.z = HAUTEUR_BASSIN - bas;
  }

  dessiner() {
    if (this.mode === 'webgl') {
      this.rendu.render(this.scene, this.camera);
    } else {
      this._dessiner2D();
    }
    this.images += 1;
  }

  _glisser() {
    let depart = null;
    this.toile.addEventListener('pointerdown', (e) => {
      depart = { x: e.clientX, azimut: this.azimut };
      this.toile.setPointerCapture(e.pointerId);
    });
    this.toile.addEventListener('pointermove', (e) => {
      if (!depart) return;
      this.azimut = depart.azimut - (e.clientX - depart.x) / 120;
      this.demanderRendu();
    });
    const fin = () => { depart = null; };
    this.toile.addEventListener('pointerup', fin);
    this.toile.addEventListener('pointercancel', fin);
  }

  _dessiner2D() {
    const c = this.contexte;
    const l = this.toile.width;
    const h = this.toile.height;
    const distance = this.distance2D;
    this.camera.position.set(this.cible.x + distance * Math.cos(this.azimut), this.cible.y + distance * Math.sin(this.azimut),
      this.hauteur2D);
    this.camera.lookAt(this.cible);
    this.camera.updateMatrixWorld();
    this.scene.updateMatrixWorld(true);
    c.fillStyle = '#1e1e1e';
    c.fillRect(0, 0, l, h);
    const projeter = (v) => {
      const p = v.clone().project(this.camera);
      return { x: (p.x + 1) * l / 2, y: (1 - p.y) * h / 2, z: p.z };
    };
    // sol : une grille de 4 m
    c.strokeStyle = '#3a3a48';
    c.lineWidth = 1;
    for (let i = -4; i <= 4; i += 1) {
      [[new THREE.Vector3(i * 0.5, -2, 0), new THREE.Vector3(i * 0.5, 2, 0)],
        [new THREE.Vector3(-2, i * 0.5, 0), new THREE.Vector3(2, i * 0.5, 0)]].forEach(([a, b]) => {
        const pa = projeter(a);
        const pb = projeter(b);
        c.beginPath();
        c.moveTo(pa.x, pa.y);
        c.lineTo(pb.x, pb.y);
        c.stroke();
      });
    }
    const traits = [];
    const pos = {};
    Object.keys(this.liens).forEach((nom) => {
      const v = new THREE.Vector3();
      this.liens[nom].getWorldPosition(v);
      pos[nom] = v;
    });
    const point = (nom, decalage) => {
      if (!decalage) return pos[nom];
      return this.liens[nom].localToWorld(new THREE.Vector3(decalage[0], decalage[1], decalage[2]));
    };
    this.segments.forEach((s) => {
      if (!pos[s.a] || !pos[s.b]) return;
      const pa = projeter(point(s.a, s.oa));
      const pb = projeter(point(s.b, s.ob));
      traits.push({ pa, pb, couleur: s.couleur, largeur: s.largeur, z: (pa.z + pb.z) / 2 });
    });
    traits.sort((u, v) => v.z - u.z);
    const echelle = h / 360;
    c.lineCap = 'round';
    traits.forEach((t) => {
      c.strokeStyle = t.couleur;
      c.lineWidth = Math.max(2, 9 * echelle * t.largeur * (1.2 - t.z * 0.3));
      c.beginPath();
      c.moveTo(t.pa.x, t.pa.y);
      c.lineTo(t.pb.x, t.pb.y);
      c.stroke();
    });
    if (this.lienTete) {
      const v = new THREE.Vector3(POSITION_TETE[0], POSITION_TETE[1], POSITION_TETE[2]);
      this.lienTete.localToWorld(v);
      const p = projeter(v);
      c.fillStyle = '#e9e6df';
      c.strokeStyle = COULEUR_CORPS;
      c.lineWidth = 2;
      c.beginPath();
      c.arc(p.x, p.y, 22 * echelle, 0, 2 * Math.PI);
      c.fill();
      c.stroke();
      if (this.couleurLed) {
        c.fillStyle = this.couleurLed;
        c.beginPath();
        c.arc(p.x, p.y, 9 * echelle, 0, 2 * Math.PI);
        c.fill();
      }
    }
  }

  fermer() {
    this.actif = false;
    if (this.observateur) this.observateur.disconnect();
    if (this.rendu) {
      this.scene.traverse((o) => {
        if (o.geometry) o.geometry.dispose();
        if (o.material) o.material.dispose();
      });
      this.rendu.dispose();
      this.rendu.domElement.remove();
    }
    if (window[this.nomGlobal] === this) window[this.nomGlobal] = null;
  }
}
