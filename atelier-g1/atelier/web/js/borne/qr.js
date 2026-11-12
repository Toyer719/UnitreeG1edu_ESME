// Code QR de l'adresse de la borne (vague 6, section 13.5 du plan), pour l'écran Démo de l'Atelier : un petit
// encodeur écrit ici (aucune bibliothèque de plus dans vendor/), d'après la norme ISO/IEC 18004 : mode octets
// (UTF-8), correction d'erreurs M (15 %), versions 1 à 40, Reed-Solomon sur GF(256), placement en zigzag, masque
// choisi par les pénalités de la norme. Vérifié par les essais : le code dessiné est relu par OpenCV.
// Le dessin est un SVG (createElementNS, aucun HTML inséré) : modules sombres sur fond clair, couleurs du thème
// (classes qr-fond et qr-modules de css/demo.css). Agent Borne et orchestrateur.

// Niveaux de correction : bits du format (norme) et nombre de codes de correction par bloc, et de blocs
const NIVEAUX = {
  L: { format: 1, ecc: [-1, 7, 10, 15, 20, 26, 18, 20, 24, 30, 18, 20, 24, 26, 30, 22, 24, 28, 30, 28, 28, 28, 28, 30, 30, 26, 28, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30],
    blocs: [-1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 4, 4, 4, 4, 4, 6, 6, 6, 6, 7, 8, 8, 9, 9, 10, 12, 12, 12, 13, 14, 15, 16, 17, 18, 19, 19, 20, 21, 22, 24, 25] },
  M: { format: 0, ecc: [-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24, 24, 28, 28, 26, 26, 26, 26, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28],
    blocs: [-1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9, 10, 10, 11, 13, 14, 16, 17, 17, 18, 20, 21, 23, 25, 26, 28, 29, 31, 33, 35, 37, 38, 40, 43, 45, 47, 49] },
  Q: { format: 3, ecc: [-1, 13, 22, 18, 26, 18, 24, 18, 22, 20, 24, 28, 26, 24, 20, 30, 24, 28, 28, 26, 30, 28, 30, 30, 30, 30, 28, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30],
    blocs: [-1, 1, 1, 2, 2, 4, 4, 6, 6, 8, 8, 8, 10, 12, 16, 12, 17, 16, 18, 21, 20, 23, 23, 25, 27, 29, 34, 34, 35, 38, 40, 43, 45, 48, 51, 53, 56, 59, 62, 65, 68] },
  H: { format: 2, ecc: [-1, 17, 28, 22, 16, 22, 28, 26, 26, 24, 28, 24, 28, 22, 24, 24, 30, 28, 28, 26, 28, 30, 24, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30],
    blocs: [-1, 1, 1, 2, 4, 4, 4, 5, 6, 8, 8, 11, 11, 16, 16, 18, 16, 19, 21, 25, 25, 25, 34, 30, 32, 35, 37, 40, 42, 45, 48, 51, 54, 57, 60, 63, 66, 70, 74, 77, 81] },
};

function bit(x, i) {
  return ((x >>> i) & 1) !== 0;
}

// Multiplication dans GF(256), polynôme 0x11D
function multiplier(x, y) {
  let z = 0;
  for (let i = 7; i >= 0; i--) {
    z = (z << 1) ^ ((z >>> 7) * 0x11d);
    z ^= ((y >>> i) & 1) * x;
  }
  return z;
}

function diviseurReedSolomon(degre) {
  const r = [];
  for (let i = 0; i < degre - 1; i++) r.push(0);
  r.push(1);
  let racine = 1;
  for (let i = 0; i < degre; i++) {
    for (let j = 0; j < r.length; j++) {
      r[j] = multiplier(r[j], racine);
      if (j + 1 < r.length) r[j] ^= r[j + 1];
    }
    racine = multiplier(racine, 0x02);
  }
  return r;
}

function resteReedSolomon(donnees, diviseur) {
  const r = diviseur.map(() => 0);
  donnees.forEach((b) => {
    const facteur = b ^ r.shift();
    r.push(0);
    diviseur.forEach((c, i) => { r[i] ^= multiplier(c, facteur); });
  });
  return r;
}

// Nombre de modules pour les données (et la correction) d'une version
export function modulesDeDonnees(version) {
  let n = (16 * version + 128) * version + 64;
  if (version >= 2) {
    const alignements = Math.floor(version / 7) + 2;
    n -= (25 * alignements - 10) * alignements - 55;
    if (version >= 7) n -= 36;
  }
  return n;
}

export function codesDeDonnees(version, niveau) {
  const nv = NIVEAUX[niveau];
  return Math.floor(modulesDeDonnees(version) / 8) - nv.ecc[version] * nv.blocs[version];
}

function positionsAlignement(version) {
  if (version === 1) return [];
  const taille = version * 4 + 17;
  const n = Math.floor(version / 7) + 2;
  const pas = version === 32 ? 26 : Math.ceil((version * 4 + 4) / (n * 2 - 2)) * 2;
  const r = [6];
  for (let p = taille - 7; r.length < n; p -= pas) r.splice(1, 0, p);
  return r;
}

function utf8(texte) {
  if (typeof TextEncoder !== 'undefined') return Array.from(new TextEncoder().encode(texte));
  return Array.from(unescape(encodeURIComponent(texte))).map((c) => c.charCodeAt(0));
}

// Les codes de données (mode octets, terminateur, remplissage) pour une version donnée
function codesDuTexte(octets, version, niveau) {
  const bits = [];
  const ajouter = (valeur, longueur) => {
    for (let i = longueur - 1; i >= 0; i--) bits.push((valeur >>> i) & 1);
  };
  ajouter(0x4, 4);
  ajouter(octets.length, version <= 9 ? 8 : 16);
  octets.forEach((o) => ajouter(o, 8));
  const capacite = codesDeDonnees(version, niveau) * 8;
  ajouter(0, Math.min(4, capacite - bits.length));
  ajouter(0, (8 - bits.length % 8) % 8);
  for (let pad = 0xec; bits.length < capacite; pad ^= 0xec ^ 0x11) ajouter(pad, 8);
  const codes = [];
  for (let i = 0; i < bits.length; i += 8) codes.push(bits.slice(i, i + 8).reduce((a, b) => (a << 1) | b, 0));
  return codes;
}

// Ajoute la correction d'erreurs et entrelace les blocs
function avecCorrection(donnees, version, niveau) {
  const nv = NIVEAUX[niveau];
  const nBlocs = nv.blocs[version];
  const lEcc = nv.ecc[version];
  const bruts = Math.floor(modulesDeDonnees(version) / 8);
  const courts = nBlocs - bruts % nBlocs;
  const lCourt = Math.floor(bruts / nBlocs);
  const diviseur = diviseurReedSolomon(lEcc);
  const blocs = [];
  for (let i = 0, k = 0; i < nBlocs; i++) {
    const d = donnees.slice(k, k + lCourt - lEcc + (i < courts ? 0 : 1));
    k += d.length;
    const ecc = resteReedSolomon(d, diviseur);
    if (i < courts) d.push(0);
    blocs.push(d.concat(ecc));
  }
  const r = [];
  for (let i = 0; i < blocs[0].length; i++) {
    blocs.forEach((b, j) => {
      if (i !== lCourt - lEcc || j >= courts) r.push(b[i]);
    });
  }
  return r;
}

function masque(m, x, y) {
  switch (m) {
    case 0: return (x + y) % 2 === 0;
    case 1: return y % 2 === 0;
    case 2: return x % 3 === 0;
    case 3: return (x + y) % 3 === 0;
    case 4: return (Math.floor(x / 3) + Math.floor(y / 2)) % 2 === 0;
    case 5: return (x * y) % 2 + (x * y) % 3 === 0;
    case 6: return ((x * y) % 2 + (x * y) % 3) % 2 === 0;
    default: return ((x + y) % 2 + (x * y) % 3) % 2 === 0;
  }
}

// La grille du code : {taille, version, niveau, masque, sombre(x, y)} ; RangeError si le texte est trop long
export function codeQR(texte, niveau) {
  niveau = NIVEAUX[niveau] ? niveau : 'M';
  const octets = utf8(String(texte));
  let version = 1;
  for (; version <= 40; version++) {
    const bitsCompte = version <= 9 ? 8 : 16;
    if (4 + bitsCompte + octets.length * 8 <= codesDeDonnees(version, niveau) * 8 && octets.length < (1 << bitsCompte)) break;
  }
  if (version > 40) throw new RangeError('texte trop long pour un code QR');
  const taille = version * 4 + 17;
  const modules = [];
  const fonction = [];
  for (let y = 0; y < taille; y++) {
    modules.push(new Array(taille).fill(false));
    fonction.push(new Array(taille).fill(false));
  }
  const poser = (x, y, sombre) => {
    modules[y][x] = sombre;
    fonction[y][x] = true;
  };
  // motifs fixes : rythme, repères des coins, alignements, version
  for (let i = 0; i < taille; i++) {
    poser(6, i, i % 2 === 0);
    poser(i, 6, i % 2 === 0);
  }
  [[3, 3], [taille - 4, 3], [3, taille - 4]].forEach((c) => {
    for (let dy = -4; dy <= 4; dy++) {
      for (let dx = -4; dx <= 4; dx++) {
        const d = Math.max(Math.abs(dx), Math.abs(dy));
        const x = c[0] + dx;
        const y = c[1] + dy;
        if (x >= 0 && x < taille && y >= 0 && y < taille) poser(x, y, d !== 2 && d !== 4);
      }
    }
  });
  const alignements = positionsAlignement(version);
  alignements.forEach((ay, i) => {
    alignements.forEach((ax, j) => {
      const coin = (i === 0 && j === 0) || (i === 0 && j === alignements.length - 1) || (i === alignements.length - 1 && j === 0);
      if (coin) return;
      for (let dy = -2; dy <= 2; dy++) {
        for (let dx = -2; dx <= 2; dx++) poser(ax + dx, ay + dy, Math.max(Math.abs(dx), Math.abs(dy)) !== 1);
      }
    });
  });
  const format = (m) => {
    const d = (NIVEAUX[niveau].format << 3) | m;
    let reste = d;
    for (let i = 0; i < 10; i++) reste = (reste << 1) ^ ((reste >>> 9) * 0x537);
    const b = ((d << 10) | reste) ^ 0x5412;
    for (let i = 0; i <= 5; i++) poser(8, i, bit(b, i));
    poser(8, 7, bit(b, 6));
    poser(8, 8, bit(b, 7));
    poser(7, 8, bit(b, 8));
    for (let i = 9; i < 15; i++) poser(14 - i, 8, bit(b, i));
    for (let i = 0; i < 8; i++) poser(taille - 1 - i, 8, bit(b, i));
    for (let i = 8; i < 15; i++) poser(8, taille - 15 + i, bit(b, i));
    poser(8, taille - 8, true);
  };
  format(0);
  if (version >= 7) {
    let reste = version;
    for (let i = 0; i < 12; i++) reste = (reste << 1) ^ ((reste >>> 11) * 0x1f25);
    const b = (version << 12) | reste;
    for (let i = 0; i < 18; i++) {
      const a = taille - 11 + i % 3;
      const c = Math.floor(i / 3);
      poser(a, c, bit(b, i));
      poser(c, a, bit(b, i));
    }
  }
  // les données, en zigzag de deux colonnes, de droite à gauche
  const codes = avecCorrection(codesDuTexte(octets, version, niveau), version, niveau);
  let i = 0;
  for (let droite = taille - 1; droite >= 1; droite -= 2) {
    if (droite === 6) droite = 5;
    for (let v = 0; v < taille; v++) {
      for (let j = 0; j < 2; j++) {
        const x = droite - j;
        const montant = ((droite + 1) & 2) === 0;
        const y = montant ? taille - 1 - v : v;
        if (!fonction[y][x] && i < codes.length * 8) {
          modules[y][x] = bit(codes[i >>> 3], 7 - (i & 7));
          i++;
        }
      }
    }
  }
  // le masque : celui qui donne le moins de pénalités
  const appliquer = (m) => {
    for (let y = 0; y < taille; y++) {
      for (let x = 0; x < taille; x++) {
        if (!fonction[y][x] && masque(m, x, y)) modules[y][x] = !modules[y][x];
      }
    }
  };
  let meilleur = 0;
  let minimum = Infinity;
  for (let m = 0; m < 8; m++) {
    appliquer(m);
    format(m);
    const p = penalite(modules, taille);
    if (p < minimum) {
      minimum = p;
      meilleur = m;
    }
    appliquer(m);       // le même masque une seconde fois : retour à la grille sans masque
  }
  appliquer(meilleur);
  format(meilleur);
  return { taille: taille, version: version, niveau: niveau, masque: meilleur, sombre: (x, y) => modules[y][x] };
}

// Pénalités de la norme : suites de même couleur, carrés 2 × 2, motifs qui ressemblent aux repères, équilibre
export function penalite(modules, taille) {
  let p = 0;
  const motif = [true, false, true, true, true, false, true];
  const ressemble = (ligne, k) => {
    for (let a = 0; a < 7; a++) if (ligne(k + a) !== motif[a]) return false;
    const clair = (debut) => {
      for (let a = 0; a < 4; a++) {
        const v = ligne(debut + a);
        if (v === true) return false;
      }
      return true;
    };
    return clair(k - 4) || clair(k + 7);
  };
  for (let sens = 0; sens < 2; sens++) {
    for (let a = 0; a < taille; a++) {
      const lire = (b) => (b < 0 || b >= taille ? undefined : (sens === 0 ? modules[a][b] : modules[b][a]));
      let suite = 1;
      for (let b = 1; b <= taille; b++) {
        if (b < taille && lire(b) === lire(b - 1)) {
          suite++;
        } else {
          if (suite >= 5) p += suite - 2;
          suite = 1;
        }
      }
      for (let b = 0; b + 7 <= taille; b++) if (ressemble((c) => (lire(c) === undefined ? false : lire(c)), b)) p += 40;
    }
  }
  let sombres = 0;
  for (let y = 0; y < taille; y++) {
    for (let x = 0; x < taille; x++) {
      if (modules[y][x]) sombres++;
      if (x + 1 < taille && y + 1 < taille) {
        const c = modules[y][x];
        if (c === modules[y][x + 1] && c === modules[y + 1][x] && c === modules[y + 1][x + 1]) p += 3;
      }
    }
  }
  const total = taille * taille;
  p += Math.ceil(Math.abs(sombres * 20 - total * 10) / total - 1) * 10;
  return p;
}

// Les lignes de la grille, « 1 » pour un module sombre (essais)
export function lignesQR(texte, niveau) {
  const q = codeQR(texte, niveau);
  const lignes = [];
  for (let y = 0; y < q.taille; y++) {
    let l = '';
    for (let x = 0; x < q.taille; x++) l += q.sombre(x, y) ? '1' : '0';
    lignes.push(l);
  }
  return lignes;
}

// Le dessin SVG du code, avec sa marge de 4 modules ; options : {niveau, titre}
export function svgQR(texte, options) {
  options = options || {};
  const q = codeQR(texte, options.niveau || 'M');
  const marge = 4;
  const cote = q.taille + marge * 2;
  const NS = 'http://www.w3.org/2000/svg';
  const s = document.createElementNS(NS, 'svg');
  s.setAttribute('viewBox', '0 0 ' + cote + ' ' + cote);
  s.setAttribute('class', 'qr');
  s.setAttribute('shape-rendering', 'crispEdges');
  s.setAttribute('role', 'img');
  s.setAttribute('data-version', String(q.version));
  if (options.titre) s.setAttribute('aria-label', options.titre);
  const fond = document.createElementNS(NS, 'rect');
  fond.setAttribute('class', 'qr-fond');
  fond.setAttribute('width', String(cote));
  fond.setAttribute('height', String(cote));
  s.appendChild(fond);
  let d = '';
  for (let y = 0; y < q.taille; y++) {
    for (let x = 0; x < q.taille; x++) {
      if (q.sombre(x, y)) d += 'M' + (x + marge) + ' ' + (y + marge) + 'h1v1h-1z';
    }
  }
  const chemin = document.createElementNS(NS, 'path');
  chemin.setAttribute('class', 'qr-modules');
  chemin.setAttribute('d', d);
  s.appendChild(chemin);
  return s;
}
