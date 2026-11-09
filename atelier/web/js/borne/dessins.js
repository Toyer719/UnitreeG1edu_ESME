// Dessins de la borne visiteur (vague 6, section 13.5 du plan) : la mascotte du robot, avec son humeur selon
// l'écran, et les pictogrammes des salles. SVG fabriqué élément par élément (createElementNS) : aucun HTML inséré.
// Les couleurs sont celles du thème (classes de css/borne.css, jetons de css/theme.css). Agent Borne et orchestrateur.

const NS = 'http://www.w3.org/2000/svg';

// Un élément SVG : nom, attributs, enfants
export function svg(nom, attributs, enfants) {
  const e = document.createElementNS(NS, nom);
  Object.keys(attributs || {}).forEach((k) => e.setAttribute(k, String(attributs[k])));
  (enfants || []).forEach((x) => e.appendChild(x));
  return e;
}

// L'humeur de la mascotte pour chaque écran de la borne
export const HUMEURS = {
  hors_service: 'dort', salles: 'accueil', suivez_moi: 'marche', arrivee: 'content', retour: 'marche',
  occupe: 'occupe', pause: 'pause',
};

function yeux(humeur) {
  const g = svg('g', { class: 'm-yeux' });
  [46, 74].forEach((x) => {
    if (humeur === 'content') {
      g.appendChild(svg('path', { class: 'm-trait', d: `M${x - 7} 57 Q${x} 47 ${x + 7} 57` }));
    } else if (humeur === 'dort') {
      g.appendChild(svg('path', { class: 'm-trait', d: `M${x - 7} 55 Q${x} 60 ${x + 7} 55` }));
    } else if (humeur === 'pause') {
      g.appendChild(svg('path', { class: 'm-trait', d: `M${x - 7} 54 L${x + 7} 54` }));
      g.appendChild(svg('circle', { class: 'm-oeil', cx: x, cy: 57, r: 3 }));
    } else {
      const dx = humeur === 'marche' ? 3 : 0;
      const dy = humeur === 'occupe' ? -3 : 0;
      g.appendChild(svg('circle', { class: 'm-oeil m-clignote', cx: x + dx, cy: 54 + dy, r: 6.5 }));
      g.appendChild(svg('circle', { class: 'm-reflet', cx: x + dx + 2.2, cy: 51.5 + dy, r: 2 }));
    }
  });
  return g;
}

function bouche(humeur) {
  if (humeur === 'pause' || humeur === 'occupe') return svg('path', { class: 'm-trait m-bouche', d: 'M52 69 L68 69' });
  if (humeur === 'dort') return svg('circle', { class: 'm-trait m-bouche', cx: 60, cy: 69, r: 3 });
  if (humeur === 'content') return svg('path', { class: 'm-trait m-bouche', d: 'M46 65 Q60 80 74 65' });
  return svg('path', { class: 'm-trait m-bouche', d: 'M48 66 Q60 76 72 66' });
}

// La mascotte (tête du G1 dessinée simplement) ; humeur : accueil, marche, content, occupe, pause, dort
export function mascotte(humeur) {
  humeur = humeur || 'accueil';
  const enfants = [
    svg('line', { class: 'm-antenne-tige', x1: 60, y1: 10, x2: 60, y2: 24 }),
    svg('circle', { class: 'm-antenne', cx: 60, cy: 9, r: 5.5 }),
    svg('rect', { class: 'm-oreille', x: 9, y: 46, width: 11, height: 24, rx: 5.5 }),
    svg('rect', { class: 'm-oreille', x: 100, y: 46, width: 11, height: 24, rx: 5.5 }),
    svg('rect', { class: 'm-tete', x: 17, y: 22, width: 86, height: 72, rx: 24 }),
    svg('rect', { class: 'm-visage', x: 28, y: 34, width: 64, height: 48, rx: 16 }),
    yeux(humeur), bouche(humeur),
    svg('circle', { class: 'm-joue', cx: 36, cy: 68, r: 4.5 }),
    svg('circle', { class: 'm-joue', cx: 84, cy: 68, r: 4.5 }),
    svg('rect', { class: 'm-cou', x: 46, y: 94, width: 28, height: 8, rx: 3 }),
    svg('rect', { class: 'm-corps', x: 30, y: 101, width: 60, height: 17, rx: 8 }),
  ];
  if (humeur === 'dort' || humeur === 'pause') {
    enfants.push(svg('text', { class: 'm-z', x: 96, y: 26 }, [document.createTextNode('z')]));
    enfants.push(svg('text', { class: 'm-z m-z2', x: 106, y: 14 }, [document.createTextNode('z')]));
  }
  const s = svg('svg', { class: 'mascotte', viewBox: '0 0 120 120', 'aria-hidden': 'true',
    'data-humeur': humeur }, enfants);
  return s;
}

// La grosse flèche de « Suivez-moi ! »
export function fleche() {
  return svg('svg', { class: 'borne-fleche', viewBox: '0 0 120 60', 'aria-hidden': 'true' }, [
    svg('path', { class: 'f-corps', d: 'M8 30 L86 30' }),
    svg('path', { class: 'f-pointe', d: 'M70 10 L100 30 L70 50' }),
  ]);
}

// Pictogrammes des salles (étiquettes PICTOGRAMMES_BORNE, et « porte » par défaut) : traits de 3 px sur 48 × 48
const TRACES = {
  porte: [['rect', { x: 13, y: 6, width: 22, height: 37, rx: 2 }], ['circle', { cx: 29, cy: 26, r: 1.8 }],
    ['path', { d: 'M8 43 L40 43' }]],
  toilettes: [['circle', { cx: 15, cy: 9, r: 4 }], ['path', { d: 'M15 15 L15 30 M9 19 L21 19 M11 42 L15 30 L19 42' }],
    ['circle', { cx: 33, cy: 9, r: 4 }], ['path', { d: 'M33 15 L27 32 L39 32 Z M30 32 L30 42 M36 32 L36 42' }],
    ['path', { d: 'M24 4 L24 44' }]],
  sortie: [['rect', { x: 6, y: 6, width: 20, height: 36, rx: 2 }], ['path', { d: 'M18 24 L42 24 M34 16 L42 24 L34 32' }]],
  cafeteria: [['path', { d: 'M8 20 L32 20 L30 40 Q20 44 10 40 Z' }], ['path', { d: 'M32 24 Q42 24 40 32 Q38 37 31 36' }],
    ['path', { d: 'M14 14 Q12 10 15 6 M21 14 Q19 10 22 6 M28 14 Q26 10 29 6' }]],
  cdi: [['path', { d: 'M24 12 Q16 6 5 8 L5 38 Q16 36 24 42 Q32 36 43 38 L43 8 Q32 6 24 12 Z' }],
    ['path', { d: 'M24 12 L24 42' }]],
  infirmerie: [['rect', { x: 6, y: 6, width: 36, height: 36, rx: 8 }],
    ['path', { d: 'M24 14 L24 34 M14 24 L34 24', class: 'p-fort' }]],
  secretariat: [['rect', { x: 10, y: 5, width: 26, height: 34, rx: 2 }], ['path', { d: 'M15 14 L31 14 M15 21 L31 21 M15 28 L25 28' }],
    ['path', { d: 'M30 44 L42 30 L45 33 L33 46 Z' }]],
  ascenseur: [['rect', { x: 9, y: 4, width: 30, height: 40, rx: 3 }], ['path', { d: 'M18 18 L24 11 L30 18 M18 30 L24 37 L30 30' }]],
  labo: [['path', { d: 'M18 6 L30 6 M20 6 L20 20 L8 40 Q7 43 11 43 L37 43 Q41 43 40 40 L28 20 L28 6' }],
    ['path', { d: 'M13 33 L35 33' }]],
  gymnase: [['path', { d: 'M14 24 L34 24', class: 'p-fort' }], ['rect', { x: 6, y: 14, width: 8, height: 20, rx: 2 }],
    ['rect', { x: 34, y: 14, width: 8, height: 20, rx: 2 }], ['path', { d: 'M3 20 L3 28 M45 20 L45 28' }]],
  amphi: [['rect', { x: 10, y: 4, width: 28, height: 16, rx: 2 }], ['path', { d: 'M6 30 Q24 24 42 30 M4 38 Q24 31 44 38 M2 46 Q24 38 46 46' }]],
};

export function pictogramme(nom) {
  const traces = TRACES[nom] || TRACES.porte;
  return svg('svg', { class: 'pictogramme', viewBox: '0 0 48 48', 'aria-hidden': 'true', 'data-pictogramme':
    TRACES[nom] ? nom : 'porte' }, traces.map((t) => svg(t[0], Object.assign({}, t[1], {
    class: 'p-trait' + (t[1].class ? ' ' + t[1].class : ''),
  }))));
}

export const PICTOGRAMMES = Object.keys(TRACES);
