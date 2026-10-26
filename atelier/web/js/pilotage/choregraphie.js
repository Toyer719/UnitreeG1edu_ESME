// Chorégraphies du G1 (section 11.5 du plan) : la même interpolation que le nœud pilotage
// (atelier.lieu.pilotage.poses_bras, segments_bras, deplacement_pas), pour l'aperçu 3D et l'éditeur.
// Les limites viennent de GET /api/pilotage/config : rien n'est dupliqué ici, sauf l'ordre des
// articulations. La vérification qui fait foi reste celle du serveur et du nœud.

export const ARTICULATIONS = [
  'left_shoulder_pitch', 'left_shoulder_roll', 'left_shoulder_yaw', 'left_elbow',
  'left_wrist_roll', 'left_wrist_pitch', 'left_wrist_yaw',
  'right_shoulder_pitch', 'right_shoulder_roll', 'right_shoulder_yaw', 'right_elbow',
  'right_wrist_roll', 'right_wrist_pitch', 'right_wrist_yaw',
];

export const NOMS_ARTICULATIONS = {
  shoulder_pitch: 'épaule (avant/arrière)', shoulder_roll: 'épaule (écart)', shoulder_yaw: 'épaule (rotation)',
  elbow: 'coude', wrist_roll: 'poignet (rotation)', wrist_pitch: 'poignet (haut/bas)', wrist_yaw: 'poignet (côté)',
};

export const RAMPE_DEFAUT = 1.0;

export function repos() {
  const q = {};
  ARTICULATIONS.forEach((n) => { q[n] = 0; });
  return q;
}

export function libelleArticulation(nom) {
  const cote = nom.indexOf('left_') === 0 ? 'gauche' : 'droit';
  const reste = nom.replace('left_', '').replace('right_', '');
  return (NOMS_ARTICULATIONS[reste] || reste) + ' ' + cote;
}

function copie(q) {
  return Object.assign({}, q);
}

// Poses complètes : une articulation absente garde sa valeur précédente (au départ : le repos)
export function posesCompletes(d) {
  let courant = repos();
  const sortie = [];
  const poses = (d.bras && d.bras.poses) || [];
  poses.forEach((p) => {
    courant = Object.assign(copie(courant), p.q || {});
    sortie.push({ t: p.t, q: copie(courant) });
  });
  return sortie;
}

// Segments [t0, q0, t1, q1] : du repos (fin de la rampe) à la première pose, de pose en pose,
// puis de la dernière pose au repos (début de la rampe de fin)
export function segments(d) {
  if (!d.bras || !d.bras.poses || !d.bras.poses.length) return [];
  const rampe = d.bras.rampe_s === undefined ? RAMPE_DEFAUT : d.bras.rampe_s;
  const cles = [{ t: rampe, q: repos() }].concat(posesCompletes(d), [{ t: d.duree_s - rampe, q: repos() }]);
  const s = [];
  for (let i = 0; i + 1 < cles.length; i += 1) s.push([cles[i].t, cles[i].q, cles[i + 1].t, cles[i + 1].q]);
  return s;
}

// {poids, q} à l'instant t (comme poses_bras du contrat)
export function poses(d, t) {
  if (!d.bras || !d.bras.poses || !d.bras.poses.length) return { poids: 0, q: repos() };
  const rampe = d.bras.rampe_s === undefined ? RAMPE_DEFAUT : d.bras.rampe_s;
  const fin = d.duree_s;
  const poids = Math.max(0, Math.min(1, t / rampe, (fin - t) / rampe));
  const douce = (d.bras.interpolation || 'douce') === 'douce';
  const liste = segments(d);
  for (let i = 0; i < liste.length; i += 1) {
    const [t0, q0, t1, q1] = liste[i];
    if (t0 <= t && t <= t1) {
      let k = t1 <= t0 ? 0 : (t - t0) / (t1 - t0);
      if (douce) k = (1 - Math.cos(Math.PI * k)) / 2;
      const q = {};
      ARTICULATIONS.forEach((n) => { q[n] = q0[n] + (q1[n] - q0[n]) * k; });
      return { poids, q };
    }
  }
  return { poids, q: repos() };
}

// Angles vus par le robot : l'ordre pondéré par le poids d'arm_sdk, sinon la pose du contrôleur
// d'Unitree (bras le long du corps). Pour l'aperçu seulement.
export const POSE_CONTROLEUR = { left_shoulder_roll: 0.2, right_shoulder_roll: -0.2, left_elbow: 0.3, right_elbow: 0.3 };

export function anglesVus(d, t) {
  const p = poses(d, t);
  const q = {};
  ARTICULATIONS.forEach((n) => {
    const r = POSE_CONTROLEUR[n] || 0;
    q[n] = p.poids * p.q[n] + (1 - p.poids) * r;
  });
  return { poids: p.poids, q };
}

// Position du robot (repère de départ) à l'instant t : les pas intégrés, comme deplacement_pas
export function positionBase(d, t, pas) {
  pas = pas || 0.02;
  let x = 0;
  let y = 0;
  let cap = 0;
  const liste = (d.pas || []).slice().sort((a, b) => a.t - b.t);
  liste.forEach((p) => {
    const fin = Math.min(t, p.t + p.duree_s);
    if (fin <= p.t) return;
    const n = Math.max(1, Math.ceil((fin - p.t) / pas));
    const dt = (fin - p.t) / n;
    for (let i = 0; i < n; i += 1) {
      x += (p.vx * Math.cos(cap) - p.vy * Math.sin(cap)) * dt;
      y += (p.vx * Math.sin(cap) + p.vy * Math.cos(cap)) * dt;
      cap += p.wz * dt;
    }
  });
  return { x, y, cap };
}

// Distance maximale au départ et rotation cumulée (comme deplacement_pas)
export function deplacement(d) {
  let x = 0;
  let y = 0;
  let cap = 0;
  let loin = 0;
  let rotation = 0;
  (d.pas || []).slice().sort((a, b) => a.t - b.t).forEach((p) => {
    const n = Math.max(1, Math.ceil(p.duree_s / 0.05));
    const dt = p.duree_s / n;
    for (let i = 0; i < n; i += 1) {
      x += (p.vx * Math.cos(cap) - p.vy * Math.sin(cap)) * dt;
      y += (p.vx * Math.sin(cap) + p.vy * Math.cos(cap)) * dt;
      cap += p.wz * dt;
      rotation += Math.abs(p.wz) * dt;
      loin = Math.max(loin, Math.hypot(x, y));
    }
  });
  return { distance: loin, rotation };
}

// Vitesse la plus forte d'une articulation (rad/s), au plus fort de l'interpolation
export function vitesseMax(d) {
  const facteur = d.bras && (d.bras.interpolation || 'douce') === 'douce' ? Math.PI / 2 : 1;
  let v = 0;
  segments(d).forEach(([t0, q0, t1, q1]) => {
    if (t1 <= t0) return;
    ARTICULATIONS.forEach((n) => { v = Math.max(v, (facteur * Math.abs(q1[n] - q0[n])) / (t1 - t0)); });
  });
  return v;
}

// Couleur de la LED à l'instant t (dernière consigne passée), ou null
export function couleurLed(d, t) {
  let c = null;
  (d.led || []).forEach((e) => { if (e.t <= t && (!c || e.t >= c.t)) c = e; });
  return c;
}

// Le pas en cours à l'instant t, ou null
export function pasEnCours(d, t) {
  const liste = d.pas || [];
  for (let i = 0; i < liste.length; i += 1) {
    if (liste[i].t <= t && t < liste[i].t + liste[i].duree_s) return liste[i];
  }
  return null;
}

// Nouvelle chorégraphie vide (sûre) : 16 s, battement à 110 temps par minute, une pose
export function nouvelle(id, nom) {
  return {
    version: 1, id, nom: nom || id, auteur: 'Atelier G1', duree_s: 16, zone_libre_m: 2.5,
    musique: { fichier: null, battement: { bpm: 110, accent: 4 }, decalage_s: 0, sortie: 'navigateur' },
    bras: { rampe_s: 1.5, interpolation: 'douce', poses: [{ t: 4, nom: 'pose 1', q: { left_elbow: 0.8, right_elbow: 0.8 } }] },
    pas: [], led: [{ t: 0, r: 0, g: 160, b: 255 }], paroles: [],
  };
}

// Ajoute une pose des bras à l'instant t (les angles vus à cet instant), triée ; renvoie son rang
export function ajouterPose(d, t) {
  if (!d.bras) d.bras = { rampe_s: 1.5, interpolation: 'douce', poses: [] };
  const q = poses(d, t).q;
  const arrondi = {};
  ARTICULATIONS.forEach((n) => { arrondi[n] = Math.round(q[n] * 1000) / 1000; });
  const pose = { t: Math.round(t * 100) / 100, nom: 'pose', q: arrondi };
  d.bras.poses.push(pose);
  d.bras.poses.sort((a, b) => a.t - b.t);
  return d.bras.poses.indexOf(pose);
}

// Angles complets de la pose de rang i (avec les valeurs gardées des poses d'avant)
export function anglesDeLaPose(d, i) {
  return posesCompletes(d)[i].q;
}
