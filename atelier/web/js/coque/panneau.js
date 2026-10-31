// Panneau de tâches à droite (PropertyManager de SolidWorks) : propriétés de l'élément choisi, ou
// formulaire de la commande en cours, avec ✓ OK et ✗ Annuler ; il défile seul (vague 5, section 12.2
// du plan). Module de l'agent Coquille.
//
// ouvrirPanneau(element, {titre, aide, ok, annuler}) → {corps, fermer, titre(t), aide(t), activer(ok, annuler)}
//   element : options.panneau d'un écran (le corps du panneau de la coque, [data-role=panneau-corps]) :
//     l'en-tête de la coque ([data-role=panneau-titre], [data-role=ok], [data-role=annuler]) est alors
//     réglé, et le corps vidé ; ou tout autre élément : en-tête et corps sont construits dedans.
//   ok, annuler : une fonction, ou {texte, action, actif} ; absent : pas de bouton.

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
  // les boutons sont remplacés par des copies : plus aucun ancien écouteur
  const okNeuf = ok.cloneNode(true);
  const annulerNeuf = annuler.cloneNode(true);
  ok.replaceWith(okNeuf);
  annuler.replaceWith(annulerNeuf);
  const choixOk = normaliser(options.ok, 'OK');
  const choixAnnuler = normaliser(options.annuler, 'Annuler');

  function regler(b, choix) {
    b.hidden = !choix;
    if (!choix) return;
    b.querySelector('.bouton-panneau-texte').textContent = choix.texte;
    b.title = choix.titre || choix.texte;
    b.disabled = !choix.actif;
    b.onclick = () => { if (!b.disabled && choix.action) choix.action(); };
  }

  regler(okNeuf, choixOk);
  regler(annulerNeuf, choixAnnuler);
  titre.textContent = options.titre || '';
  if (aide) {
    aide.textContent = options.aide || '';
    aide.hidden = !options.aide;
  }
  corps.textContent = '';
  corps.scrollTop = 0;
  let ferme = false;
  return {
    corps: corps,
    titre: (t) => { titre.textContent = t || ''; },
    aide: (t) => {
      if (!aide) return;
      aide.textContent = t || '';
      aide.hidden = !t;
    },
    // active ou grise ✓ et ✗ (undefined : inchangé)
    activer: (okActif, annulerActif) => {
      if (okActif !== undefined) okNeuf.disabled = !okActif;
      if (annulerActif !== undefined) annulerNeuf.disabled = !annulerActif;
    },
    fermer: () => {
      if (ferme) return;
      ferme = true;
      regler(okNeuf, null);
      regler(annulerNeuf, null);
      corps.textContent = '';
    },
  };
}
