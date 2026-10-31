// Panneau de tâches à droite (PropertyManager de SolidWorks) : propriétés de l'élément choisi, ou
// formulaire de la commande en cours, avec ✓ OK et ✗ Annuler ; il défile seul (vague 5, section 12.2
// du plan). Module de l'agent Coquille.
//
// ouvrirPanneau(element, {titre, aide, ok, annuler, actifSurSaisie}) → {corps, fermer, titre(t), aide(t),
//   activer(ok, annuler)}
//   element : options.panneau d'un écran (le corps du panneau de la coque, [data-role=panneau-corps]) :
//     l'en-tête de la coque ([data-role=panneau-titre], [data-role=ok], [data-role=annuler]) est alors
//     réglé, et le corps vidé ; ou tout autre élément : en-tête et corps sont construits dedans.
//   ok, annuler : une fonction, ou {texte, action, actif} ; absent : pas de bouton.
//   actifSurSaisie : ✓ et ✗ s'activent dès qu'on tape dans un champ du panneau (formulaires d'édition :
//     le champ n'est validé qu'en le quittant, et un ✓ encore grisé ne recevrait pas le clic).
// Les boutons ✓ et ✗ restent les mêmes d'un appel à l'autre (seuls leur action, leur texte et leur état
// changent) : un champ quitté par l'appui sur ✓ redessine le panneau entre l'appui et le clic, et un bouton
// remplacé à ce moment perdait le clic (revue de la vague 5). Un ancien appel (écran fermé, panneau redessiné)
// n'a plus d'effet sur les boutons ni sur le corps. Redessiné avec le même titre, le panneau garde son
// défilement, ses blocs « Avancé » ouverts et le curseur (Tab passe au champ suivant même si le champ quitté
// redessine le panneau).

import { apresValidations } from '../formulaire.js';

function el(balise, classe, texte) {
  const e = document.createElement(balise);
  if (classe) e.className = classe;
  if (texte !== undefined && texte !== null) e.textContent = texte;
  return e;
}

function bouton(role, classe, symbole, texte) {
  const b = el('button', 'bouton-panneau ' + classe);
  b.type = 'button';
  b.setAttribute('data-role', role);
  b.appendChild(el('span', 'bouton-panneau-symbole', symbole));
  b.appendChild(el('span', 'bouton-panneau-texte', texte));
  return b;
}

// Éléments qui peuvent avoir le curseur, dans l'ordre du panneau (le même d'un dessin à l'autre)
const FOCALISABLES = 'input, select, textarea, button, summary, a[href], [tabindex]';

// Construit l'en-tête d'un panneau (titre, ✓, ✗, aide) dans « cadre », avant « corps »
export function construireEntete(cadre, corps) {
  const entete = el('div', 'panneau-entete');
  entete.setAttribute('data-role', 'panneau-entete');
  const titre = el('h2', 'panneau-titre-principal');
  titre.setAttribute('data-role', 'panneau-titre');
  const boutons = el('div', 'panneau-boutons');
  const ok = bouton('ok', 'bouton-ok', '✓', 'OK');
  const annuler = bouton('annuler', 'bouton-annuler', '✗', 'Annuler');
  boutons.appendChild(ok);
  boutons.appendChild(annuler);
  entete.appendChild(titre);
  entete.appendChild(boutons);
  const aide = el('p', 'panneau-aide');
  aide.setAttribute('data-role', 'panneau-aide');
  cadre.insertBefore(entete, corps);
  cadre.insertBefore(aide, corps);
  ok.hidden = true;
  annuler.hidden = true;
  aide.hidden = true;
  return entete;
}

function normaliser(choix, defaut) {
  if (!choix) return null;
  if (typeof choix === 'function') return { texte: defaut, action: choix, actif: true };
  return { texte: choix.texte || defaut, action: choix.action, actif: choix.actif !== false, titre: choix.titre };
}

// État du corps avant qu'il soit redessiné : défilement, blocs <details> ouverts, élément qui a le curseur
// (par sa place dans le panneau) et texte tapé pas encore validé
function photographier(corps) {
  const liste = Array.from(corps.querySelectorAll(FOCALISABLES));
  const actif = document.activeElement;
  const i = actif && actif !== corps && corps.contains(actif) ? liste.indexOf(actif) : -1;
  const p = { defilement: corps.scrollTop, ouverts: Array.from(corps.querySelectorAll('details')).map((d) => d.open), focus: null };
  if (i >= 0) {
    p.focus = { i: i, balise: actif.tagName, type: actif.type || '', valeur: actif.saisieEnCours ? actif.value : null, debut: null, fin: null };
    try {
      p.focus.debut = actif.selectionStart;
      p.focus.fin = actif.selectionEnd;
    } catch (e) {
      // champ sans sélection (nombre, case)
    }
  }
  return p;
}

function retrouver(corps, p) {
  const details = Array.from(corps.querySelectorAll('details'));
  if (details.length === p.ouverts.length) details.forEach((d, i) => { if (p.ouverts[i]) d.open = true; });
  const f = p.focus;
  const actif = document.activeElement;
  if (f && (!actif || actif === document.body || !document.contains(actif))) {
    const e = Array.from(corps.querySelectorAll(FOCALISABLES))[f.i];
    if (e && e.tagName === f.balise && (e.type || '') === f.type) {
      if (f.valeur !== null && f.valeur !== undefined) {
        e.value = f.valeur;
        e.saisieEnCours = true;
      }
      try {
        e.focus({ preventScroll: true });
        if (f.debut !== null && f.debut !== undefined) e.setSelectionRange(f.debut, f.fin);
      } catch (err) {
        // champ sans sélection : le curseur suffit
      }
    }
  }
  corps.scrollTop = p.defilement;
}

export function ouvrirPanneau(element, options) {
  options = options || {};
  let cadre = element.parentNode;
  let entete = cadre ? cadre.querySelector(':scope > [data-role=panneau-entete]') : null;
  let corps = element;
  if (!entete || element.getAttribute('data-role') !== 'panneau-corps') {
    // élément quelconque : on construit un petit panneau complet dedans
    element.textContent = '';
    cadre = element;
    corps = el('div', 'panneau-corps');
    corps.setAttribute('data-role', 'panneau-corps');
    element.appendChild(corps);
    entete = construireEntete(cadre, corps);
  }
  const titre = entete.querySelector('[data-role=panneau-titre]');
  const ok = entete.querySelector('[data-role=ok]');
  const annuler = entete.querySelector('[data-role=annuler]');
  const aide = cadre.querySelector(':scope > [data-role=panneau-aide]');
  const choixOk = normaliser(options.ok, 'OK');
  const choixAnnuler = normaliser(options.annuler, 'Annuler');
  // numéro de cet appel : un ancien appel (écran fermé, panneau redessiné) ne touche plus à rien
  const numero = (cadre.panneauNumero || 0) + 1;
  cadre.panneauNumero = numero;
  const courant = () => cadre.panneauNumero === numero;

  function regler(b, choix) {
    b.hidden = !choix;
    b.choixPanneau = choix;
    if (!choix) {
      b.onclick = null;
      return;
    }
    b.querySelector('.bouton-panneau-texte').textContent = choix.texte;
    b.title = choix.titre || choix.texte;
    b.disabled = !choix.actif;
    // après la validation du champ qu'on vient de quitter en appuyant sur ce bouton (formulaire.js) : ce champ
    // redessine souvent le panneau ; c'est alors l'action du panneau redessiné qui part (même bouton)
    b.onclick = () => {
      if (b.disabled || !choix.action || !courant()) return;
      apresValidations(() => {
        const c = b.choixPanneau;
        if (c && c.action && !b.hidden && !b.disabled) c.action();
      });
    };
  }

  regler(ok, choixOk);
  regler(annuler, choixAnnuler);
  // même titre : le même élément redessiné après une modification. Le panneau garde alors son défilement, ses
  // blocs « Avancé » ouverts et le curseur (avec ce qu'on tapait, pas encore validé)
  const memeTitre = titre.textContent === (options.titre || '') && corps.childNodes.length > 0;
  const avant = memeTitre ? photographier(corps) : null;
  titre.textContent = options.titre || '';
  if (aide) {
    aide.textContent = options.aide || '';
    aide.hidden = !options.aide;
  }
  corps.textContent = '';
  corps.scrollTop = 0;
  if (avant) {
    // l'écran remplit le corps juste après cet appel : on remet tout ensuite, avant l'affichage
    Promise.resolve().then(() => { if (courant()) retrouver(corps, avant); });
  }
  cadre.panneauSaisie = options.actifSurSaisie ? { ok: !!(choixOk && choixOk.action), annuler: !!(choixAnnuler && choixAnnuler.action) } : null;
  if (!corps.panneauEcoute) {
    // formulaire d'édition : dès qu'on tape, ✓ et ✗ deviennent cliquables (le champ se valide en le quittant)
    corps.panneauEcoute = true;
    corps.addEventListener('input', (ev) => {
      if (!ev.target || !/^(INPUT|TEXTAREA|SELECT)$/.test(ev.target.tagName)) return;
      ev.target.saisieEnCours = true;
      const s = cadre.panneauSaisie;
      if (!s) return;
      if (s.ok) ok.disabled = false;
      if (s.annuler) annuler.disabled = false;
    });
    corps.addEventListener('change', (ev) => { if (ev.target) ev.target.saisieEnCours = false; }, true);
  }
  return {
    corps: corps,
    titre: (t) => { if (courant()) titre.textContent = t || ''; },
    aide: (t) => {
      if (!aide || !courant()) return;
      aide.textContent = t || '';
      aide.hidden = !t;
    },
    // active ou grise ✓ et ✗ (undefined : inchangé)
    activer: (okActif, annulerActif) => {
      if (!courant()) return;
      if (okActif !== undefined) ok.disabled = !okActif;
      if (annulerActif !== undefined) annuler.disabled = !annulerActif;
    },
    fermer: () => {
      if (!courant()) return;
      cadre.panneauNumero = numero + 1;
      cadre.panneauSaisie = null;
      regler(ok, null);
      regler(annuler, null);
      corps.textContent = '';
    },
  };
}
