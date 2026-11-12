// Petits éléments de formulaire pour les panneaux de détails des écrans.
// Les textes viennent toujours de textContent ou de value : jamais de HTML venant des fichiers.
//
// Validation d'un champ (événement « change », quand on le quitte) : l'écran redessine alors souvent son
// panneau. Si on quitte le champ en appuyant sur un bouton (✓ Enregistrer, Supprimer…), le panneau redessiné
// tout de suite détruisait ce bouton entre l'appui et le relâchement, et le clic était perdu ; avec Tab, le
// champ suivant disparaissait et le curseur avec lui (revue de la vague 5). La validation attend donc que le
// bouton de la souris soit relâché (le clic passe d'abord), ou que Tab ait posé le curseur. Sans souris
// enfoncée ni Tab (Entrée, Ctrl+S, essais), elle est immédiate. apresValidations(f) lance f après les
// validations en attente (✓ et ✗ du panneau s'en servent : le champ quitté est enregistré avec le reste).

let appuye = false;           // un bouton de la souris (ou un doigt) est enfoncé
let apresTab = false;         // Tab vient d'être pressé : le curseur va dans le champ suivant
const enAttente = [];         // validations qui attendent la fin du clic

function viderAttente() {
  while (enAttente.length) {
    const f = enAttente.shift();
    try {
      f();
    } catch (e) {
      console.error(e);
    }
  }
}

function relacher() {
  if (!appuye) return;
  appuye = false;
  // après le clic (qui suit le relâchement dans la même tâche) : le bouton cliqué a fait son travail
  setTimeout(viderAttente, 0);
}

if (typeof document !== 'undefined') {
  document.addEventListener('pointerdown', () => { appuye = true; }, true);
  document.addEventListener('pointerup', relacher, true);
  document.addEventListener('pointercancel', relacher, true);
  window.addEventListener('blur', relacher);
  document.addEventListener('keydown', (ev) => {
    if (ev.key !== 'Tab') return;
    apresTab = true;
    setTimeout(() => { apresTab = false; }, 0);
  }, true);
}

// Lance la validation d'un champ : tout de suite, ou après le clic en cours, ou après le déplacement de Tab
export function valider(f) {
  if (appuye) {
    enAttente.push(f);
    // filet : un relâchement jamais reçu (hors de la fenêtre) ne bloque pas la validation
    setTimeout(() => {
      if (enAttente.indexOf(f) >= 0) {
        appuye = false;
        viderAttente();
      }
    }, 1500);
    return;
  }
  if (apresTab) {
    setTimeout(f, 0);
    return;
  }
  f();
}

// Lance f après les validations de champs en attente (tout de suite s'il n'y en a pas)
export function apresValidations(f) {
  if (enAttente.length || appuye) setTimeout(f, 0);
  else f();
}

export function el(balise, classe, texte) {
  const e = document.createElement(balise);
  if (classe) e.className = classe;
  if (texte !== undefined && texte !== null) e.textContent = texte;
  return e;
}

export function titre(parent, texte) {
  return parent.appendChild(el('h3', 'panneau-titre', texte));
}

export function paragraphe(parent, texte, classe) {
  return parent.appendChild(el('p', classe || 'panneau-texte', texte));
}

function ligne(parent, libelle, champ, unite) {
  const l = el('label', 'champ');
  l.appendChild(el('span', 'champ-libelle', libelle));
  l.appendChild(champ);
  if (unite) l.appendChild(el('span', 'champ-unite', unite));
  parent.appendChild(l);
  return champ;
}

// Champ nombre. options : {pas, min, max, unite, decimales}. surChangement(valeur) à chaque validation.
export function champNombre(parent, libelle, valeur, options, surChangement) {
  options = options || {};
  const c = el('input');
  c.type = 'number';
  c.step = options.pas === undefined ? 'any' : String(options.pas);
  if (options.min !== undefined) c.min = String(options.min);
  if (options.max !== undefined) c.max = String(options.max);
  const d = options.decimales === undefined ? 3 : options.decimales;
  c.value = valeur === null || valeur === undefined ? '' : String(Math.round(valeur * Math.pow(10, d)) / Math.pow(10, d));
  c.addEventListener('change', () => {
    const v = parseFloat(c.value.replace(',', '.'));
    if (isNaN(v)) return;
    valider(() => surChangement(v));
  });
  return ligne(parent, libelle, c, options.unite);
}

export function champTexte(parent, libelle, valeur, surChangement, options) {
  options = options || {};
  const c = el(options.lignes ? 'textarea' : 'input');
  if (!options.lignes) c.type = 'text';
  else c.rows = options.lignes;
  c.value = valeur || '';
  if (options.indice) c.placeholder = options.indice;
  if (options.lectureSeule) c.readOnly = true;
  c.addEventListener('change', () => {
    const v = c.value;
    valider(() => surChangement(v));
  });
  return ligne(parent, libelle, c, options.unite);
}

export function caseACocher(parent, libelle, valeur, surChangement) {
  const l = el('label', 'champ champ-case');
  const c = el('input');
  c.type = 'checkbox';
  c.checked = !!valeur;
  c.addEventListener('change', () => {
    const v = c.checked;
    valider(() => surChangement(v));
  });
  l.appendChild(c);
  l.appendChild(el('span', 'champ-libelle', libelle));
  parent.appendChild(l);
  return c;
}

// choix : [{id, texte}]
export function listeDeroulante(parent, libelle, valeur, choix, surChangement) {
  const s = el('select');
  choix.forEach((c) => {
    const o = el('option', '', c.texte);
    o.value = c.id;
    s.appendChild(o);
  });
  s.value = valeur;
  s.addEventListener('change', () => {
    const v = s.value;
    valider(() => surChangement(v));
  });
  return ligne(parent, libelle, s);
}

export function bouton(parent, texte, action, classe) {
  const b = el('button', classe || 'bouton', texte);
  b.type = 'button';
  b.addEventListener('click', action);
  parent.appendChild(b);
  return b;
}

// Valeur fixe affichée (ex. longueur calculée)
export function valeur(parent, libelle, texte) {
  const l = el('div', 'champ');
  l.appendChild(el('span', 'champ-libelle', libelle));
  l.appendChild(el('span', 'champ-valeur', texte));
  parent.appendChild(l);
  return l;
}

// Groupe de boutons d'outils exclusifs. outils : [{id, texte, titre}]. Renvoie {choisir(id)}.
export function barreOutils(parent, outils, actuel, surChoix) {
  const g = el('div', 'groupe-outils');
  g.setAttribute('role', 'radiogroup');
  const boutons = {};
  outils.forEach((o) => {
    const b = el('button', 'outil', o.texte);
    b.type = 'button';
    if (o.titre) b.title = o.titre;
    b.setAttribute('role', 'radio');
    b.addEventListener('click', () => surChoix(o.id));
    boutons[o.id] = b;
    g.appendChild(b);
  });
  parent.appendChild(g);
  const r = {
    choisir: (id) => {
      Object.keys(boutons).forEach((k) => {
        boutons[k].classList.toggle('actif', k === id);
        boutons[k].setAttribute('aria-checked', k === id ? 'true' : 'false');
      });
    },
  };
  r.choisir(actuel);
  return r;
}
