// Poses de la Vue du robot (onglet Pilotage, section 11.13 du plan) : postures, marche, gestes
// d'Unitree et danse du robot, en angles d'articulations du G1 29 ddl (noms de l'URDF sans _joint).
//
// Ce sont des APERÇUS APPROCHÉS : le vrai geste et la vraie danse sont dans le robot, dont on ne
// connaît que le numéro. Ici, de simples poses clés interpolées (cosinus), toutes dans les limites
// de l'URDF g1_29dof_rev_1_0 moins 0,05 rad (vérifié par test_pilotage_vue_navigateur.py ; la vue
// borne encore chaque angle avant de le dessiner). Les chorégraphies de l'Atelier, elles, sont
// montrées exactement (choregraphie.js : la même interpolation que le nœud).
//
// Conventions du G1 (URDF) : épaule (pitch) négative = bras vers l'avant puis vers le haut (−π/2 :
// à l'horizontale, −2,9 : en l'air) ; écart (roll) positif à gauche = bras écarté (négatif à
// droite) ; coude à 0 = avant-bras à l'horizontale vers l'avant, positif = bras qui se tend vers le
// bas (1,5 : tendu), négatif = avant-bras qui remonte.

import { POSE_CONTROLEUR } from './choregraphie.js';

export const MARGE = 0.05;

const COTES = ['left', 'right'];
// articulations dont le signe change d'un bras à l'autre (symétrie gauche ↔ droite)
const OPPOSEES = ['shoulder_roll', 'shoulder_yaw', 'wrist_roll', 'wrist_yaw', 'hip_roll', 'hip_yaw', 'ankle_roll'];

// q d'un côté (noms sans left_ ni right_) → noms complets ; le côté droit est le miroir du gauche
function cote(c, q) {
  const r = {};
  Object.keys(q).forEach((n) => {
    r[c + '_' + n] = c === 'right' && OPPOSEES.indexOf(n) >= 0 ? -q[n] : q[n];
  });
  return r;
}
const G = (q) => cote('left', q);
const D = (q) => cote('right', q);
const S = (q) => Object.assign(G(q), D(q));        // les deux bras, en miroir

// Bras au repos : la pose que tient le contrôleur de marche (comme l'aperçu des chorégraphies)
const BRAS_REPOS = Object.assign({
  left_shoulder_pitch: 0, left_shoulder_yaw: 0, left_wrist_roll: 0, left_wrist_pitch: 0, left_wrist_yaw: 0,
  right_shoulder_pitch: 0, right_shoulder_yaw: 0, right_wrist_roll: 0, right_wrist_pitch: 0, right_wrist_yaw: 0,
}, POSE_CONTROLEUR);
const JAMBES_DEBOUT = S({ hip_pitch: -0.1, hip_roll: 0, hip_yaw: 0, knee: 0.3, ankle_pitch: -0.2, ankle_roll: 0 });
const TAILLE_DROITE = { waist_yaw: 0, waist_roll: 0, waist_pitch: 0 };

function pose(...parties) {
  return Object.assign({}, JAMBES_DEBOUT, TAILLE_DROITE, BRAS_REPOS, ...parties);
}

// ---------------------------------------------------------------- postures (mode FSM du robot)

export const POSTURES = {
  debout: { texte: 'Debout', q: pose() },
  accroupi: {
    texte: 'Accroupi',
    q: pose(S({ hip_pitch: -1.0, knee: 1.9, ankle_pitch: -0.75 }), { waist_pitch: 0.2 },
      S({ shoulder_pitch: -0.5, shoulder_roll: 0.25, elbow: 0.5 })),
  },
  assis: {
    texte: 'Assis par terre',
    q: pose(S({ hip_pitch: -1.9, hip_roll: 0.15, knee: 2.1, ankle_pitch: -0.2 }), { waist_pitch: 0.1 },
      S({ shoulder_pitch: -0.6, shoulder_roll: 0.3, elbow: 0.9 })),
  },
  amorti: {
    texte: 'Amorti : il s\'affaisse s\'il n\'est pas tenu',
    q: pose(S({ hip_pitch: -0.25, knee: 0.6, ankle_pitch: -0.3 }), { waist_pitch: 0.25 },
      S({ shoulder_pitch: 0.15, shoulder_roll: 0.08, elbow: 1.2 })),
  },
  couple_nul: {
    texte: 'Couple nul : moteurs relâchés',
    q: pose(S({ hip_pitch: -0.3, knee: 0.8, ankle_pitch: -0.4 }), { waist_pitch: 0.3 },
      S({ shoulder_pitch: 0.2, shoulder_roll: 0.05, elbow: 1.4 })),
  },
};

// Mode FSM (7001) → posture montrée ; null : inconnu (debout, grisé dans la vue)
export function postureDuMode(fsm) {
  if (fsm === 706) return 'accroupi';
  if (fsm === 3) return 'assis';
  if (fsm === 1) return 'amorti';
  if (fsm === 0) return 'couple_nul';
  if (fsm === 500 || fsm === 501 || fsm === 801 || fsm === 702) return 'debout';
  return null;
}

// ---------------------------------------------------------------- gestes (poses clés approchées)

// Bras gauche aux poses clés des gestes, réutilisées (le droit s'en déduit en miroir)
const BOUCHE = { shoulder_pitch: -1.1, shoulder_roll: 0.25, shoulder_yaw: -0.5, elbow: -0.7 };
const ENVOI = { shoulder_pitch: -1.3, shoulder_roll: 0.6, shoulder_yaw: 0, elbow: 1.1 };
const EN_L_AIR = { shoulder_pitch: -2.9, shoulder_roll: 0.35, shoulder_yaw: 0, elbow: 1.3 };
const MAINS_JOINTES = { shoulder_pitch: -0.9, shoulder_roll: 0.15, shoulder_yaw: -0.55, elbow: -0.25 };
const MAINS_ECARTEES = { shoulder_pitch: -0.9, shoulder_roll: 0.35, shoulder_yaw: -0.1, elbow: -0.25 };
const BRAS_OUVERTS = { shoulder_pitch: -1.3, shoulder_roll: 0.7, shoulder_yaw: 0, elbow: 1.1 };
const BRAS_FERMES = { shoulder_pitch: -1.4, shoulder_roll: 0.25, shoulder_yaw: -1.3, elbow: 0.6 };
const MAIN_TENDUE = { shoulder_pitch: -0.75, shoulder_roll: 0.1, shoulder_yaw: -0.15, elbow: 0.55 };
const SALUT_HAUT = { shoulder_pitch: -2.5, shoulder_roll: 0.5, shoulder_yaw: 0, elbow: 0.9 };

// Oscillation : n allers-retours entre deux poses, toutes les « pas » secondes, à partir de t0
function oscille(t0, pas, n, a, b) {
  const cles = [];
  for (let i = 0; i < n; i += 1) cles.push([t0 + pas * (i + 1), i % 2 === 0 ? b : a]);
  return cles;
}

// genre « bras » : arm 7106 (action_id) ; genre « tache » : sport 7106 SetTaskId (en marchant)
// Chaque geste : {cles: [[t, q partiel], …]} ; le départ est la pose affichée, la fin le repos, sauf
// « tenir » (la dernière pose reste jusqu'au geste suivant).
export const GESTES = {
  bras: {
    99: { cles: [[1.0, {}]] },
    11: { cles: [[1.2, S(BOUCHE)], [2.0, S(BOUCHE)], [2.8, S(ENVOI)], [3.6, S(ENVOI)], [5.0, {}]] },
    12: { cles: [[1.2, G(BOUCHE)], [2.0, G(BOUCHE)], [2.8, G(ENVOI)], [3.6, G(ENVOI)], [5.0, {}]] },
    13: { cles: [[1.2, D(BOUCHE)], [2.0, D(BOUCHE)], [2.8, D(ENVOI)], [3.6, D(ENVOI)], [5.0, {}]] },
    15: {
      cles: [[1.2, S(EN_L_AIR)], [2.0, S(Object.assign({}, EN_L_AIR, { shoulder_roll: 0.55 }))],
        [2.8, S(EN_L_AIR)], [3.6, S(EN_L_AIR)], [5.0, {}]],
    },
    17: {
      cles: [[0.8, S(MAINS_JOINTES)]].concat(oscille(0.8, 0.35, 8, S(MAINS_JOINTES), S(MAINS_ECARTEES)),
        [[4.6, {}]]),
    },
    18: {
      cles: [[1.2, D({ shoulder_pitch: -2.3, shoulder_roll: 0.25, elbow: 0.6, wrist_pitch: -0.3 })],
        [1.7, D({ shoulder_pitch: -2.4, shoulder_roll: 0.25, elbow: 0.9, wrist_pitch: -0.3 })],
        [2.6, D({ shoulder_pitch: -2.4, shoulder_roll: 0.25, elbow: 0.9, wrist_pitch: -0.3 })], [3.8, {}]],
    },
    19: { cles: [[1.2, S(BRAS_OUVERTS)], [2.4, S(BRAS_FERMES)], [3.8, S(BRAS_FERMES)], [5.0, {}]] },
    20: {
      cles: [[1.4, S({ shoulder_pitch: -2.5, shoulder_roll: 0.6, shoulder_yaw: -1.3, elbow: 0.6 })],
        [3.4, S({ shoulder_pitch: -2.5, shoulder_roll: 0.6, shoulder_yaw: -1.3, elbow: 0.6 })], [4.8, {}]],
    },
    21: {
      cles: [[1.2, D({ shoulder_pitch: -0.8, shoulder_roll: 0.1, shoulder_yaw: -0.9, elbow: -0.6 })],
        [3.4, D({ shoulder_pitch: -0.8, shoulder_roll: 0.1, shoulder_yaw: -0.9, elbow: -0.6 })], [4.6, {}]],
    },
    22: {
      cles: [[1.0, D({ shoulder_pitch: -0.7, shoulder_roll: 0.15, elbow: -0.7 })]].concat(
        oscille(1.0, 0.4, 4, D({ shoulder_pitch: -0.7, shoulder_roll: 0.15, shoulder_yaw: 0.35, elbow: -0.7 }),
          D({ shoulder_pitch: -0.7, shoulder_roll: 0.15, shoulder_yaw: -0.35, elbow: -0.7 })),
        [[3.0, D({ shoulder_pitch: -0.7, shoulder_roll: 0.15, elbow: -0.7 })], [4.0, {}]]),
    },
    23: { cles: [[1.2, D(EN_L_AIR)], [3.2, D(EN_L_AIR)], [4.4, {}]] },
    24: {
      cles: [[1.2, S({ shoulder_pitch: -1.0, shoulder_roll: 0, shoulder_yaw: -0.9, elbow: -0.9 })],
        [3.2, S({ shoulder_pitch: -1.0, shoulder_roll: 0, shoulder_yaw: -0.9, elbow: -0.9 })], [4.4, {}]],
    },
    25: {
      cles: [[1.0, D({ shoulder_pitch: -0.9, shoulder_roll: 0.5, shoulder_yaw: -0.3, elbow: -0.9 })]].concat(
        oscille(1.0, 0.35, 6, D({ shoulder_pitch: -0.9, shoulder_roll: 0.5, shoulder_yaw: -0.3, elbow: -0.9 }),
          D({ shoulder_pitch: -0.9, shoulder_roll: 0.75, shoulder_yaw: -0.3, elbow: -0.9 })),
        [[4.2, {}]]),
    },
    26: {
      cles: [[1.2, D(SALUT_HAUT)]].concat(
        oscille(1.2, 0.4, 5, D(SALUT_HAUT), D(Object.assign({}, SALUT_HAUT, { shoulder_roll: 0.9 }))),
        [[4.4, {}]]),
    },
    27: {
      cles: [[1.2, D(MAIN_TENDUE)]].concat(
        oscille(1.2, 0.3, 4, D(MAIN_TENDUE), D(Object.assign({}, MAIN_TENDUE, { elbow: 0.75 }))),
        [[3.2, D(MAIN_TENDUE)], [4.4, {}]]),
    },
  },
  tache: {
    0: {
      cles: [[1.0, D(Object.assign({}, SALUT_HAUT, { shoulder_pitch: -2.2 }))]].concat(
        oscille(1.0, 0.4, 5, D(Object.assign({}, SALUT_HAUT, { shoulder_pitch: -2.2 })),
          D(Object.assign({}, SALUT_HAUT, { shoulder_pitch: -2.2, shoulder_roll: 0.9 }))),
        [[4.0, {}]]),
    },
    1: {
      cles: [[1.0, Object.assign({ waist_yaw: 0.4 }, D(SALUT_HAUT))],
        [2.0, Object.assign({ waist_yaw: -0.4 }, D(Object.assign({}, SALUT_HAUT, { shoulder_roll: 0.9 })))],
        [3.0, Object.assign({ waist_yaw: 0.4 }, D(SALUT_HAUT))],
        [4.0, Object.assign({ waist_yaw: 0 }, D(Object.assign({}, SALUT_HAUT, { shoulder_roll: 0.9 })))],
        [5.0, {}]],
    },
    2: { cles: [[1.2, D(MAIN_TENDUE)]], tenir: true },
    3: {
      cles: [[0.5, D(Object.assign({}, MAIN_TENDUE, { elbow: 0.4 }))], [0.9, D(Object.assign({}, MAIN_TENDUE, { elbow: 0.75 }))],
        [1.3, D(Object.assign({}, MAIN_TENDUE, { elbow: 0.45 }))], [2.5, {}]],
    },
  },
};

export function dureeGeste(genre, id) {
  const g = (GESTES[genre] || {})[id];
  return g ? g.cles[g.cles.length - 1][0] : 0;
}

function douce(k) {
  return (1 - Math.cos(Math.PI * Math.max(0, Math.min(1, k)))) / 2;
}

// Mélange a → b (k de 0 à 1) des articulations de a et b
export function melanger(a, b, k) {
  const q = Object.assign({}, a);
  Object.keys(b).forEach((n) => {
    const va = a[n] === undefined ? b[n] : a[n];
    q[n] = va + (b[n] - va) * k;
  });
  return q;
}

// Pose du geste à l'instant t (s) depuis son début, à partir de « depart » (la pose affichée quand le
// geste a commencé) et du repos « repos ». {q, fini} ; null pour un geste inconnu.
export function poseGeste(genre, id, t, depart, repos) {
  const g = (GESTES[genre] || {})[id];
  if (!g) return null;
  const cles = [[0, depart]].concat(g.cles.map(([tc, q], i) => {
    const derniere = i === g.cles.length - 1;
    return [tc, Object.assign({}, repos, derniere && !g.tenir ? {} : q)];
  }));
  const fin = cles[cles.length - 1][0];
  if (t >= fin) return { q: Object.assign({}, cles[cles.length - 1][1]), fini: true, tenu: !!g.tenir };
  for (let i = 1; i < cles.length; i += 1) {
    if (t <= cles[i][0]) {
      const [t0, q0] = cles[i - 1];
      const [t1, q1] = cles[i];
      return { q: melanger(q0, q1, douce((t - t0) / Math.max(1e-6, t1 - t0))), fini: false };
    }
  }
  return { q: Object.assign({}, cles[cles.length - 1][1]), fini: true };
}

// Toutes les poses clés d'un geste, complétées par le repos (pour les tests des limites)
export function posesClesGeste(genre, id) {
  const g = (GESTES[genre] || {})[id];
  return g ? g.cles.map(([, q]) => pose(q)) : [];
}

// ---------------------------------------------------------------- marche et danse

export const FREQUENCE_PAS_HZ = 1.4;

// Jambes et bras qui suivent la consigne du joystick {vx, vy, wz} ; phase en radians ; limites de
// la marche {vx, vy, wz}. Les pieds restent à plat (cheville = −(hanche + genou)).
export function poseMarche(base, consigne, phase, limites) {
  const l = limites || { vx: 0.4, vy: 0.25, wz: 0.6 };
  const c = consigne || { vx: 0, vy: 0, wz: 0 };
  const a = Math.min(1, Math.max(Math.hypot(c.vx / l.vx, c.vy / l.vy), Math.abs(c.wz / l.wz) * 0.7, 0.35));
  const sens = c.vx < -0.01 ? -1 : 1;
  const q = Object.assign({}, base);
  COTES.forEach((cote2, i) => {
    const phi = phase + i * Math.PI;
    const s = Math.sin(phi);
    const leve = Math.max(0, Math.cos(phi));
    const hanche = -0.1 - 0.3 * a * s * sens;
    const genou = 0.3 + 0.5 * a * leve;
    q[cote2 + '_hip_pitch'] = hanche;
    q[cote2 + '_knee'] = genou;
    q[cote2 + '_ankle_pitch'] = -(hanche + genou);
    q[cote2 + '_hip_roll'] = (cote2 === 'left' ? 1 : -1) * 0.06 * Math.abs(c.vy / l.vy) * leve;
    q[cote2 + '_shoulder_pitch'] = (base[cote2 + '_shoulder_pitch'] || 0) + 0.25 * a * s * sens;
  });
  return q;
}

// Danse du robot (laquelle, on ne sait pas la dessiner) : un mouvement générique en boucle de 4 s
export function poseDanse(t) {
  const k = (1 - Math.cos(4 * Math.PI * t)) / 2;          // deux rebonds par seconde
  const balance = Math.sin(Math.PI * t);                   // une seconde de chaque côté
  const s = Math.sin(2 * Math.PI * t);
  const q = pose(S({ hip_pitch: -0.1 - 0.2 * k, knee: 0.3 + 0.4 * k, ankle_pitch: -0.2 - 0.2 * k }),
    { waist_yaw: 0.35 * balance });
  q.left_hip_roll = 0.06 * balance;
  q.right_hip_roll = 0.06 * balance;
  q.left_shoulder_pitch = -1.2 - 0.8 * balance;
  q.right_shoulder_pitch = -1.2 + 0.8 * balance;
  q.left_shoulder_roll = 0.35 + 0.25 * s;
  q.right_shoulder_roll = -(0.35 + 0.25 * s);
  q.left_elbow = 0.2 + 0.4 * s;
  q.right_elbow = 0.2 - 0.4 * s;
  return q;
}

// ---------------------------------------------------------------- limites

// Limites {nom: [bas, haut]} depuis le modèle de /api/pilotage/modele, moins la marge
export function limitesDuModele(modele) {
  const l = {};
  ((modele && modele.articulations) || []).forEach((a) => {
    if (a.type === 'fixed' || typeof a.bas !== 'number' || typeof a.haut !== 'number') return;
    l[a.nom.replace(/_joint$/, '')] = [a.bas + MARGE, a.haut - MARGE];
  });
  return l;
}

// Chaque angle ramené dans ses limites (celles qui manquent : inchangé)
export function borner(q, limites) {
  const r = {};
  Object.keys(q).forEach((n) => {
    const b = limites && limites[n];
    r[n] = b ? Math.max(b[0], Math.min(b[1], q[n])) : q[n];
  });
  return r;
}

// Angles hors limites : [[nom, angle, bas, haut], …] (tests)
export function horsLimites(q, limites) {
  return Object.keys(q).filter((n) => limites[n] && (q[n] < limites[n][0] - 1e-9 || q[n] > limites[n][1] + 1e-9))
    .map((n) => [n, q[n], limites[n][0], limites[n][1]]);
}

export function poseDeRepos() {
  return pose();
}
