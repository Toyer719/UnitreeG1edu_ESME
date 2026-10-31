// Fenêtre de confirmation dans la page, à la place de window.confirm (vague 5, section 12.2 du plan) :
// tous les écrans s'en servent (options.coque.confirmer). Module de l'agent Coquille.
// Repères : [data-role=confirmation], boutons [data-role=confirmer] et [data-role=renoncer].
// Entrée confirme, Échap renonce (la coque envoie quand même l'ARRÊT sur Échap : la sécurité d'abord).
// demanderSaisie(texte, {valeur}) : la même fenêtre avec un champ texte, à la place de window.prompt.

let ouverte = null;       // {fond, finir} : une seule fenêtre à la fois

function el(balise, classe, texte) {
  const e = document.createElement(balise);
  if (classe) e.className = classe;
  if (texte !== undefined && texte !== null) e.textContent = texte;
  return e;
}

function fenetre(texte, options, saisie) {
  options = options || {};
  if (ouverte) ouverte.finir(null);
  return new Promise((resoudre) => {
    const fond = el('div', 'confirmation-fond');
    const boite = el('div', 'confirmation' + (options.danger ? ' confirmation-danger' : ''));
    boite.setAttribute('role', 'dialog');
    boite.setAttribute('aria-modal', 'true');
    boite.setAttribute('data-role', 'confirmation');
    const titre = el('h2', 'confirmation-titre', options.titre || (options.danger ? 'Attention' : 'Confirmer'));
    titre.id = 'confirmation-titre';
    boite.setAttribute('aria-labelledby', titre.id);
    boite.appendChild(titre);
    // le texte peut avoir plusieurs paragraphes (lignes vides) et des listes (lignes « - »)
    const corps = el('div', 'confirmation-texte');
    String(texte || '').split(/\n{2,}/).forEach((bloc) => {
      const lignes = bloc.split('\n').filter((l) => l.trim());
      const puces = lignes.filter((l) => /^\s*[-•]\s/.test(l));
      if (puces.length && puces.length === lignes.length - 1 && !/^\s*[-•]\s/.test(lignes[0])) {
        corps.appendChild(el('p', '', lignes[0]));
        const ul = el('ul');
        puces.forEach((l) => ul.appendChild(el('li', '', l.replace(/^\s*[-•]\s/, ''))));
        corps.appendChild(ul);
      } else if (puces.length && puces.length === lignes.length) {
        const ul = el('ul');
        puces.forEach((l) => ul.appendChild(el('li', '', l.replace(/^\s*[-•]\s/, ''))));
        corps.appendChild(ul);
      } else if (lignes.length) {
        corps.appendChild(el('p', '', lignes.join('\n')));
      }
    });
    boite.appendChild(corps);
    let champ = null;
    if (saisie) {
      champ = el('input', 'confirmation-champ');
      champ.type = 'text';
      champ.value = saisie.valeur || '';
      champ.setAttribute('data-role', 'saisie');
      champ.setAttribute('aria-label', options.titre || 'Saisie');
      boite.appendChild(champ);
    }
    const boutons = el('div', 'confirmation-boutons');
    const renoncer = el('button', 'bouton', options.annuler || 'Annuler');
    renoncer.type = 'button';
    renoncer.setAttribute('data-role', 'renoncer');
    const confirmer = el('button', 'bouton ' + (options.danger ? 'bouton-danger-plein' : 'bouton-principal'),
      options.ok || 'OK');
    confirmer.type = 'button';
    confirmer.setAttribute('data-role', 'confirmer');
    boutons.appendChild(renoncer);
    boutons.appendChild(confirmer);
    boite.appendChild(boutons);
    fond.appendChild(boite);
    const avant = document.activeElement;

    function finir(valeur) {
      if (!ouverte || ouverte.fond !== fond) return;
      ouverte = null;
      document.removeEventListener('keydown', clavier, true);
      fond.remove();
      if (avant && avant.focus && document.contains(avant)) {
        try {
          avant.focus();
        } catch (e) {
          // l'élément n'accepte plus le focus : rien de grave
        }
      }
      resoudre(valeur);
    }

    function clavier(ev) {
      if (ev.key === 'Escape') {
        finir(saisie ? null : false);      // la coque reçoit aussi Échap (ARRÊT) : on ne l'arrête pas
      } else if (ev.key === 'Enter' && (!ev.target || ev.target.tagName !== 'BUTTON' || ev.target === confirmer)) {
        ev.preventDefault();
        finir(saisie ? champ.value : true);
      } else if (ev.key === 'Tab') {
        // le focus reste dans la fenêtre
        const cibles = [champ, renoncer, confirmer].filter((x) => x);
        const i = cibles.indexOf(document.activeElement);
        ev.preventDefault();
        cibles[(i + (ev.shiftKey ? cibles.length - 1 : 1)) % cibles.length].focus();
      }
    }

    renoncer.addEventListener('click', () => finir(saisie ? null : false));
    confirmer.addEventListener('click', () => finir(saisie ? champ.value : true));
    fond.addEventListener('mousedown', (ev) => { if (ev.target === fond) finir(saisie ? null : false); });
    document.addEventListener('keydown', clavier, true);
    ouverte = { fond: fond, finir: finir };
    (document.querySelector('[data-role=espace]') || document.body).appendChild(fond);
    (champ || (options.danger ? renoncer : confirmer)).focus();
    if (champ) champ.select();
  });
}

// options : {titre, ok: 'Libellé du bouton', annuler: 'Libellé', danger: bool} ; résout true ou false
export function demanderConfirmation(texte, options) {
  return fenetre(texte, options, null);
}

// Saisie d'un texte (à la place de window.prompt) : résout le texte, ou null si l'on renonce
export function demanderSaisie(texte, options) {
  options = options || {};
  return fenetre(texte, options, { valeur: options.valeur || '' });
}

// Vrai si une fenêtre est ouverte (la coque n'interprète pas alors Entrée et Ctrl+Z)
export function fenetreOuverte() {
  return !!ouverte;
}
